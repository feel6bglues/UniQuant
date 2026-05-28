import math
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

    def __init__(self, initial_capital: float = 100000.0, risk_pct: float = 0.05):
        self.capital = initial_capital
        self.risk_pct = risk_pct
        self.market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}  # T+1 penalty

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
        max_loss_allowed = safe_round(self.capital * self.risk_pct, PrecisionConstants.PRICE_DECIMALS)

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


class PortfolioSizer:
    def __init__(self, max_total_risk=0.25, max_single=0.10, max_daily_loss=0.02):
        self._max_total_risk = max_total_risk
        self._max_single = max_single
        self._max_daily_loss = max_daily_loss

    def allocate(
        self,
        signals: Dict[str, PositionSizingResult],
        portfolio_equity: float,
        daily_pnl: float = 0.0,
    ) -> PortfolioAllocation:
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
