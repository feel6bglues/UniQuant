import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..shared.constants import PrecisionConstants
from ..shared.logger_factory import get_logger
from ..shared.market_rules import get_board_rule

logger = get_logger(__name__)


def safe_round(value: float, precision: int = 2) -> float:
    """
    精度安全的四舍五入
    
    Args:
        value: 待处理的值
        precision: 小数点后位数
        
    Returns:
        float: 处理后的值
    """
    if value is None or math.isnan(value) or math.isinf(value):
        return 0.0
    return round(float(value), precision)


def safe_compare(a: float, b: float, epsilon: float = 1e-9) -> int:
    """
    精度安全的浮点数比较
    
    Args:
        a: 第一个数
        b: 第二个数
        epsilon: 容差
        
    Returns:
        int: -1 if a < b, 0 if a == b, 1 if a > b
    """
    diff = a - b
    if abs(diff) < epsilon:
        return 0
    return -1 if diff < 0 else 1


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    精度安全的除法
    
    Args:
        numerator: 被除数
        denominator: 除数
        default: 除数为0时的默认值
        
    Returns:
        float: 计算结果
    """
    if abs(denominator) < 1e-9:
        return default
    return numerator / denominator


class InvalidStopLossError(ValueError):
    def __init__(self, price: float, stop_loss: float):
        super().__init__(
            f"Invalid stop loss: {stop_loss} is above or at entry price {price}. "
            "Stop loss must be below entry price."
        )


class PositionSizer:
    """
    Position Sizer for Alpha-Tactician Pro V8.0.
    Implements T+1 overnight risk penalty and CZSC Geometry adjusted stop loss.
    """

    def __init__(self, initial_capital: float = 100000.0, risk_pct: float = 0.05,
                 kelly_fraction: Optional[float] = None):
        self.capital = initial_capital
        self.risk_pct = risk_pct
        self.kelly_fraction = kelly_fraction
        self.market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}  # T+1 penalty

    @staticmethod
    def calculate_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
        if avg_loss <= 0:
            return 0.0
        b = avg_win / avg_loss
        q = 1.0 - win_rate
        if b <= 0 or win_rate <= 0:
            return 0.0
        kelly = (b * win_rate - q) / b
        return max(0.0, min(kelly, 1.0))

    def _get_lot_size(self, market: str, symbol: str = "UNKNOWN") -> int:
        if market == "CN":
            try:
                return get_board_rule(symbol).lot_size
            except ValueError:
                return 100
        elif market == "US":
            return 1
        elif market == "HK":
            return 100
        return 1

    def _entry_zone(self, price: float, entry_pct: float = 0.005):
        return (price * (1 - entry_pct), price * (1 + entry_pct))

    def calculate_shares(
        self,
        price: float,
        stop_loss: float,
        market: str = "CN",
        czsc_bottom: Optional[float] = None,
        atr_stop: Optional[float] = None,
        symbol: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """
        Calculate suggested shares and position size.
        Uses Geometry Stop Loss: max(ATR_Stop, CZSC_Bottom_Fractal).

        Args:
            price: Entry price
            stop_loss: Initial stop loss (e.g., ATR stop)
            market: Market code (CN, US, HK)
            czsc_bottom: CZSC bottom fractal price
            atr_stop: ATR-based stop loss (optional, for reference)

        Returns:
            Dictionary containing detailed sizing information:
            -建议动作: "BUY" or "HOLD"
            -入场区间: Entry price range
            -几何止损: CZSC bottom fractal
            -ATR止损: ATR-based stop loss
            -执行止损: Final stop loss used
            -风险敞口: Risk per share (with penalty)
            -建议仓位: Suggested shares
            -资金占用: Total position value
            -是否触发熔断: Whether capital circuit break was triggered
            -修正仓位: Adjusted shares if circuit break triggered
        """
        # 1. Determine final stop loss (higher is more conservative)
        atr_stop_value = atr_stop if atr_stop is not None else stop_loss
        final_stop = atr_stop_value

        # Use the highest stop loss value (most conservative)
        if czsc_bottom is not None and czsc_bottom > atr_stop_value:
            final_stop = czsc_bottom
            logger.info(f"Using CZSC Bottom Fractal for stop loss: {final_stop}")

        # 2. Risk per share calculation with precision safety
        risk_per_share = safe_round(price - final_stop, PrecisionConstants.PRICE_DECIMALS)
        if safe_compare(risk_per_share, 0) <= 0:
            logger.error(f"Stop loss {final_stop} is above or at entry price {price}.")
            raise InvalidStopLossError(price, final_stop)

        # 3. Apply T+1 penalty to the risk amount
        penalty = self.market_penalties.get(market, 1.0)
        effective_risk_pct = self.risk_pct * self.kelly_fraction if self.kelly_fraction is not None else self.risk_pct
        max_loss_allowed = safe_round(self.capital * effective_risk_pct, PrecisionConstants.PRICE_DECIMALS)

        # 4. Calculate shares with precision safety
        # Shares = MaxLoss / (RiskPerShare * Penalty)
        shares = safe_divide(max_loss_allowed, risk_per_share * penalty, 0)

        # Get lot size based on market and symbol
        lot_size = self._get_lot_size(market, symbol)
        shares = math.floor(safe_divide(shares, lot_size, 0)) * lot_size  # Round down to nearest lot
        suggested_shares = int(shares)

        # 5. Calculate risk exposure and position value with precision safety
        total_value = safe_round(shares * price, PrecisionConstants.PRICE_DECIMALS)
        risk_exposure = safe_round(risk_per_share * penalty, PrecisionConstants.PRICE_DECIMALS)  # Risk per share with penalty

        # 6. Principal Circuit Break (Safety)
        circuit_break_triggered = False
        adjusted_shares = suggested_shares

        if safe_compare(total_value, self.capital) > 0:
            logger.warning(f"Position value {total_value} exceeds capital. Maxing out.")
            circuit_break_triggered = True
            lot_size = self._get_lot_size(market, symbol)
            adjusted_shares = int(math.floor(safe_divide(self.capital, price * lot_size, 0)) * lot_size)
            total_value = safe_round(adjusted_shares * price, PrecisionConstants.PRICE_DECIMALS)

        return {
            "建议动作": "BUY",
            "入场区间": f"{self._entry_zone(price)[0]:.2f} - {self._entry_zone(price)[1]:.2f}",
            "几何止损": czsc_bottom,
            "ATR止损": atr_stop_value,
            "执行止损": final_stop,
            "风险敞口": round(risk_exposure, 2),
            "建议仓位": suggested_shares,
            "资金占用": round(total_value, 2),
            "是否触发熔断": circuit_break_triggered,
            "修正仓位": adjusted_shares,
            "penalty_applied": penalty,
            "risk_per_share": round(risk_per_share, 2),
            "max_loss_allowed": round(max_loss_allowed, 2),
        }

    def calculate_position(
        self,
        price: float,
        stop_loss: float,
        market: str = "CN",
        czsc_bottom: Optional[float] = None,
        atr_stop: Optional[float] = None,
        symbol: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """
        兼容性别名：calculate_position 方法，调用 calculate_shares 实现

        Args:
            price: Entry price
            stop_loss: Initial stop loss (e.g., ATR stop)
            market: Market code (CN, US, HK)
            czsc_bottom: CZSC bottom fractal price
            atr_stop: ATR-based stop loss (optional, for reference)

        Returns:
            Dictionary containing detailed sizing information
        """
        return self.calculate_shares(
            price, stop_loss, market, czsc_bottom, atr_stop, symbol
        )


@dataclass
class PositionSizingResult:
    symbol: str
    notional: float
    risk_amount: float
    shares: int
    entry_price: float
    stop_loss: float


@dataclass
class PortfolioAllocation:
    positions: Dict[str, PositionSizingResult] = field(default_factory=dict)
    total_allocated_pct: float = 0.0
    remaining_cash: float = 0.0
    total_risk_amount: float = 0.0


class VolumeLimitSizer:
    """
    成交量容量限制器 (Volume Capacity Sizer)

    限制每笔订单的成交量不超过该股当日真实成交量的 volume_cap_pct。
    买不进去的资金记为"闲置"，用于计算 Cash Drag (资金闲置率)。

    Args:
        volume_cap_pct: 单笔订单成交量上限占日成交量的比例 (默认 0.05 = 5%)
    """

    def __init__(self, volume_cap_pct: float = 0.05):
        self.volume_cap_pct = volume_cap_pct

    def cap_shares(
        self,
        target_shares: int,
        daily_volume: float,
        price: float,
    ) -> dict:
        """
        计算容量受限后的实际可执行股数。

        Args:
            target_shares: 策略目标股数
            daily_volume: 该股当日真实成交量 (股数)
            price: 当前股价

        Returns:
            dict: {
                "actual_shares": int,      实际可执行股数
                "target_notional": float,  目标金额
                "actual_notional": float,  实际成交金额
                "cash_drag": float,        因容量不足未成交的金额
                "fill_rate": float,        成交率 (0~1)
                "capped": bool,            是否被容量限制截断
            }
        """
        if daily_volume <= 0 or target_shares <= 0:
            return {
                "actual_shares": 0,
                "target_notional": 0.0,
                "actual_notional": 0.0,
                "cash_drag": 0.0,
                "fill_rate": 0.0,
                "capped": False,
            }

        max_shares = int(daily_volume * self.volume_cap_pct)
        max_shares = max(max_shares // 100 * 100, 0)  # round down to lot
        actual_shares = min(target_shares, max_shares)

        target_notional = target_shares * price
        actual_notional = actual_shares * price
        cash_drag = target_notional - actual_notional
        fill_rate = actual_shares / max(target_shares, 1)

        return {
            "actual_shares": int(actual_shares),
            "target_notional": round(target_notional, 2),
            "actual_notional": round(actual_notional, 2),
            "cash_drag": round(max(cash_drag, 0), 2),
            "fill_rate": round(fill_rate, 4),
            "capped": actual_shares < target_shares,
        }


class InverseVolatilitySizer:
    """
    波动率倒数风险平价分配器 (Inverse Volatility Risk Parity Sizer)。

    计算每只备选股票的过去 N 日真实波动率（年化）。
    权重与波动率成反比：波动率越高的股票获得越低的配置，
    波动率越低的蓝筹大盘股获得越高配置。

    这解决了纯等权重/ILLIQ排序下"小盘低流动性股权重过高"的问题，
    通过风险平价降低组合波动并提升资金容量。

    Args:
        vol_period: 波动率计算窗口（默认 20 日）
        min_periods: 最小有效数据点数（默认 10）
        lot_size: A 股最小交易单位（默认 100 股）
    """

    def __init__(self, vol_period: int = 20, min_periods: int = 10, lot_size: int = 100):
        self.vol_period = vol_period
        self.min_periods = min_periods
        self.lot_size = lot_size

    def compute_volatilities(
        self,
        stock_data: Dict[str, pd.DataFrame],
        symbols: list[str],
        date_str: str,
        price_col: str = "close",
    ) -> Dict[str, float]:
        """
        计算每只股票的过去 vol_period 日年化波动率。

        Args:
            stock_data: {symbol -> OHLCV DataFrame}
            symbols: 需要计算波动率的股票列表
            date_str: 当前调仓日期 (YYYY-MM-DD)
            price_col: 价格列名

        Returns:
            {symbol -> 年化波动率 (decimal, e.g. 0.25 = 25%)}
        """
        vols: Dict[str, float] = {}
        for sym in symbols:
            df = stock_data.get(sym)
            if df is None or len(df) < self.min_periods + 1:
                continue
            # 找到指定日期之前的数据窗口
            idx = df[df["date"] == date_str].index
            if idx.empty:
                continue
            end_idx = idx[0]
            start_idx = max(0, end_idx - self.vol_period)
            window = df.iloc[start_idx:end_idx + 1]
            if len(window) < self.min_periods + 1:
                continue
            close = window[price_col].values.astype(np.float64)
            ret = np.diff(close) / close[:-1]
            ret = ret[np.isfinite(ret)]
            if len(ret) < self.min_periods:
                continue
            daily_vol = np.std(ret, ddof=1)
            ann_vol = daily_vol * np.sqrt(252)
            vols[sym] = max(ann_vol, 1e-10)
        return vols

    def compute_weights(
        self,
        volatilities: Dict[str, float],
        symbols: list[str],
    ) -> Dict[str, float]:
        """
        根据波动率计算逆波动率权重。

        Args:
            volatilities: {symbol -> 年化波动率}
            symbols: 需要计算权重的股票列表

        Returns:
            {symbol -> 权重 (总和 = 1.0)}
        """
        inv_vols: Dict[str, float] = {}
        for sym in symbols:
            vol = volatilities.get(sym)
            if vol is None or vol <= 0:
                continue
            inv_vols[sym] = 1.0 / vol

        if not inv_vols:
            return {}

        total_inv = sum(inv_vols.values())
        return {sym: v / total_inv for sym, v in inv_vols.items()}

    def allocate_target_notionals(
        self,
        weights: Dict[str, float],
        total_capital: float,
        prices: Dict[str, float],
    ) -> Dict[str, dict]:
        """
        根据逆波动率权重生成每只股票的目标股数（含整手处理）。

        Args:
            weights: {symbol -> 权重}
            total_capital: 总可投资金
            prices: {symbol -> 当前股价}

        Returns:
            {symbol -> {"target_shares": int, "weight": float, "notional": float}}
        """
        allocations: Dict[str, dict] = {}
        for sym, w in weights.items():
            price = prices.get(sym, 0)
            if price <= 0:
                continue
            target_notional = total_capital * w
            target_shares = int(target_notional / price)
            target_shares = max(target_shares // self.lot_size * self.lot_size, 0)
            allocations[sym] = {
                "target_shares": target_shares,
                "weight": w,
                "notional": target_shares * price,
            }
        return allocations


class PortfolioSizer:
    def __init__(self, max_total_risk=0.25, max_single=0.10, max_daily_loss=0.02,
                 max_single_sector_pct=0.20):
        self._max_total_risk = max_total_risk
        self._max_single = max_single
        self._max_daily_loss = max_daily_loss
        self._max_single_sector_pct = max_single_sector_pct

    def allocate(
        self,
        signals: Dict[str, PositionSizingResult],
        portfolio_equity: float,
        daily_pnl: float = 0.0,
    ) -> PortfolioAllocation:
        # TODO: Enforce max_single_sector_pct using industry classification
        # Requires industry mapping per symbol, not yet implemented.
        if daily_pnl < -self._max_daily_loss:
            return PortfolioAllocation(remaining_cash=portfolio_equity)

        capped = {}
        for sym, sig in signals.items():
            max_notional = portfolio_equity * self._max_single
            if sig.notional > max_notional:
                sig.notional = max_notional
            capped[sym] = sig

        total_risk = sum(s.risk_amount for s in capped.values())
        if total_risk <= 0:
            return PortfolioAllocation(remaining_cash=portfolio_equity)

        scaling = min(1.0, portfolio_equity * self._max_total_risk / total_risk)
        return PortfolioAllocation(
            positions=capped,
            total_allocated_pct=scaling,
            remaining_cash=portfolio_equity * (1 - scaling),
            total_risk_amount=total_risk * scaling,
        )
