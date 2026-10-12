import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

import pandas as pd

from ..shared.time_provider import get_time_provider
from ..shared.error_handling import handle_errors
from ..shared.exceptions import (
    AnalysisError,
    DataValidationError,
    PortfolioServiceError,
    RiskCalculationError,
)
from ..shared.logger_factory import get_logger

logger = get_logger("PortfolioService")

PORTFOLIO_RECOVERABLE_ERRORS = (
    ArithmeticError,
    AttributeError,
    DataValidationError,
    KeyError,
    OSError,
    PortfolioServiceError,
    RiskCalculationError,
    TypeError,
    ValueError,
)


class PortfolioService:
    """
    PortfolioService V9.0: Handles portfolio construction and management.
    """

    # 仓位边界限制
    MIN_POSITION_PCT = Decimal("-100")  # 放宽至-100%（支持多空对冲与期货做空）
    MAX_POSITION_PCT = Decimal("100")  # 最大仓位100%
    # 金额精度
    DECIMAL_PLACES = Decimal("0.0001")  # 4位小数精度

    def __init__(self, risk_service=None, analysis_service=None):
        # 依赖注入
        self.risk_service = risk_service
        self.analysis_service = analysis_service
        # 原始仓位备份，用于失败回滚
        self._previous_weights: Dict[str, Decimal] = {}
        self._current_weights: Dict[str, Decimal] = {}

    def _validate_position(self, position_pct: Decimal) -> bool:
        """
        验证仓位百分比

        Args:
            position_pct: 仓位百分比

        Returns:
            bool: 是否有效
        """
        if not isinstance(position_pct, Decimal):
            try:
                position_pct = Decimal(str(position_pct))
            except (ValueError, TypeError, ArithmeticError):
                logger.error(f"仓位值无法转换为Decimal: {position_pct}")
                return False

        if position_pct < self.MIN_POSITION_PCT:
            logger.error(f"仓位不能低于{self.MIN_POSITION_PCT}%: {position_pct}%")
            return False

        if position_pct > self.MAX_POSITION_PCT:
            logger.error(f"仓位不能超过{self.MAX_POSITION_PCT}%: {position_pct}%")
            return False

        return True

    def _validate_weights(
        self,
        weights: Dict[str, Any],
        allow_short: bool = True,
        max_gross_leverage: Optional[Decimal] = None,
    ) -> bool:
        """
        验证权重是否有效

        支持两种模式：
        1. 经典单边做多存量模式：
           所有权重 >= 0，且权重总和严格为 1 (比例制) 或 100 (百分比制)。
        2. 多空对冲模式 (Long-Short Hedging)：
           允许负权重（做空/衍生品空头对冲，如 75% 股票 + (-75%) 期货 + 25% 现金，Gross 175%，Net ≈ 0%）。
           单资产仓位处于 [MIN_POSITION_PCT, MAX_POSITION_PCT] 范围内；
           总敞口 Gross Leverage <= max_gross_leverage (默认 300% 或 3.0)。

        Args:
            weights: 权重字典
            allow_short: 是否允许空头仓位（默认 True）
            max_gross_leverage: 最大允许杠杆总敞口（默认为 300% 或 3.0）

        Returns:
            bool: 是否有效
        """
        if not weights or not isinstance(weights, dict):
            logger.error("权重字典不能为空且必须为字典")
            return False

        tolerance = Decimal("0.0001")
        decimal_weights: Dict[str, Decimal] = {}

        # 1. 转换所有权重为 Decimal
        for symbol, weight in weights.items():
            if not symbol or not isinstance(symbol, str):
                logger.error(f"证券代码非法: {symbol}")
                return False
            try:
                if isinstance(weight, float):
                    decimal_weights[symbol] = Decimal(str(weight))
                elif isinstance(weight, Decimal):
                    decimal_weights[symbol] = weight
                else:
                    decimal_weights[symbol] = Decimal(str(weight))
            except (ValueError, TypeError, ArithmeticError) as e:
                logger.error(f"权重值无法转换为Decimal: {symbol}={weight}, error={e}")
                return False

        has_short = any(w < Decimal("0") for w in decimal_weights.values())
        if has_short and not allow_short:
            logger.error("当前策略配置禁止空头/负权重")
            return False

        # 2. 判断量纲：比率制 (Base 1.0) 还是 百分比制 (Base 100)
        gross_raw = sum(abs(w) for w in decimal_weights.values())
        is_percentage = (
            any(abs(w) > Decimal("1.0001") for w in decimal_weights.values())
            or gross_raw > Decimal("3.0")
        )

        # 3. 边界约束检查
        min_bound = (
            self.MIN_POSITION_PCT
            if is_percentage
            else (self.MIN_POSITION_PCT / Decimal("100"))
        )
        max_bound = (
            self.MAX_POSITION_PCT
            if is_percentage
            else (self.MAX_POSITION_PCT / Decimal("100"))
        )

        if not allow_short:
            min_bound = Decimal("0")

        for symbol, w in decimal_weights.items():
            if w < min_bound - tolerance:
                logger.error(f"权重低于下限({min_bound}): {symbol}={w}")
                return False
            if w > max_bound + tolerance:
                logger.error(f"权重超过上限({max_bound}): {symbol}={w}")
                return False

        # 4. 单边做多存量策略模式（所有权重非负）
        if not has_short:
            total = sum(decimal_weights.values())
            if (
                abs(total - Decimal("1")) > tolerance
                and abs(total - Decimal("100")) > tolerance
            ):
                logger.error(f"单边做多策略权重总和必须为1或100: {total}")
                return False
            return True

        # 5. 多空对冲模式 (Long-Short Hedging Mode)
        gross = sum(abs(w) for w in decimal_weights.values())
        net_total = sum(decimal_weights.values())

        if max_gross_leverage is not None:
            max_gross = (
                max_gross_leverage
                if is_percentage
                else (
                    max_gross_leverage / Decimal("100")
                    if max_gross_leverage > Decimal("10")
                    else max_gross_leverage
                )
            )
        else:
            max_gross = Decimal("300") if is_percentage else Decimal("3.0")

        if gross > max_gross + tolerance:
            logger.error(
                f"多空组合总杠杆敞口(Gross={gross})超出最大允许限制({max_gross})"
            )
            return False

        if gross <= tolerance:
            logger.error(f"多空组合总敞口必须为正: Gross={gross}")
            return False

        if abs(net_total) > gross + tolerance:
            logger.error(f"多空组合净敞口异常: Net={net_total}, Gross={gross}")
            return False

        logger.info(
            f"多空对冲权重验证通过: 标的数={len(decimal_weights)}, Gross={gross}{'%' if is_percentage else ''}, "
            f"Net={net_total}{'%' if is_percentage else ''}"
        )
        return True

    def validate_hedged_portfolio(
        self,
        stock_weights: Dict[str, Any],
        futures_weights: Dict[str, Any],
        cash_weight: Any,
        industry_map: Optional[Dict[str, str]] = None,
        max_stock_weight: Optional[Any] = None,
        max_industry_weight: Optional[Any] = None,
        max_industry_stocks: int = 4,
    ) -> bool:
        """
        CNMM-QAR 专用生产级多空治理中台合法性穿透校验。

        校验三元配置约束：
          1. 现货多头：股票总权重 75% (或 0.75)；
             单票权重上限 <= 2.5% (或 0.025)；
             单申万一级行业集中度 <= 10.0% (或 0.10) 且持股数 <= 4 只；
          2. 衍生品空头：股指期货总权重 -75% (或 -0.75)；
          3. 现金缓冲池：预留流动性 25% (或 0.25)；
          4. 杠杆与敞口约束：
             总杠杆 Gross Leverage = |75%| + |-75%| + |25%| = 175% (或 1.75)；
             多空净敞口 Net Exposure = 75% + (-75%) = 0% (或 0.0)。
        """
        if not stock_weights or not isinstance(stock_weights, dict):
            logger.error("股票多头权重字典不能为空且必须为字典")
            return False
        if not futures_weights or not isinstance(futures_weights, dict):
            logger.error("股指期货空头权重字典不能为空且必须为字典")
            return False

        def _conv_dec(v: Any, name: str) -> Optional[Decimal]:
            try:
                return Decimal(str(v))
            except (ValueError, TypeError, ArithmeticError) as e:
                logger.error(f"权重值无法转换为Decimal: {name}={v}, error={e}")
                return None

        dec_stocks: Dict[str, Decimal] = {}
        for s, w in stock_weights.items():
            dw = _conv_dec(w, s)
            if dw is None:
                return False
            if dw <= Decimal("0"):
                logger.error(f"现货多头股票权重必须为正: {s}={dw}")
                return False
            dec_stocks[s] = dw

        dec_futures: Dict[str, Decimal] = {}
        for f_sym, w in futures_weights.items():
            dw = _conv_dec(w, f_sym)
            if dw is None:
                return False
            if dw >= Decimal("0"):
                logger.error(f"衍生品对冲期货权重必须为负(做空): {f_sym}={dw}")
                return False
            dec_futures[f_sym] = dw

        dec_cash = _conv_dec(cash_weight, "CASH")
        if dec_cash is None:
            return False
        if dec_cash <= Decimal("0"):
            logger.error(f"现金缓冲池权重必须为正: CASH={dec_cash}")
            return False

        # 判断量纲：百分比制 (Base 100) 还是 比率制 (Base 1.0)
        total_stock = sum(dec_stocks.values())
        is_percentage = (
            total_stock > Decimal("1.5")
            or any(w > Decimal("1.0") for w in dec_stocks.values())
            or abs(dec_cash) > Decimal("1.5")
        )

        target_stock = Decimal("75") if is_percentage else Decimal("0.75")
        target_futures = Decimal("-75") if is_percentage else Decimal("-0.75")
        target_cash = Decimal("25") if is_percentage else Decimal("0.25")
        def_max_stock = Decimal("2.5") if is_percentage else Decimal("0.025")
        def_max_ind_w = Decimal("10.0") if is_percentage else Decimal("0.10")
        target_gross = Decimal("175") if is_percentage else Decimal("1.75")
        target_net = Decimal("0")

        tol = Decimal("0.5") if is_percentage else Decimal("0.005")
        spec_tol = Decimal("0.0001")

        # 1. 资产大类三元配置比例校验
        if abs(total_stock - target_stock) > tol:
            logger.error(f"股票多头总仓位偏离 75%: 实际={total_stock}, 目标={target_stock}")
            return False

        total_futures = sum(dec_futures.values())
        if abs(total_futures - target_futures) > tol:
            logger.error(f"期指空头总仓位偏离 -75%: 实际={total_futures}, 目标={target_futures}")
            return False

        if abs(dec_cash - target_cash) > tol:
            logger.error(f"流动性现金缓冲池偏离 25%: 实际={dec_cash}, 目标={target_cash}")
            return False

        # 总杠杆与净敞口严格核算
        gross = total_stock + abs(total_futures) + dec_cash
        if abs(gross - target_gross) > tol:
            logger.error(f"多空总杠杆偏离 175%: 实际={gross}, 目标={target_gross}")
            return False

        net_exposure = total_stock + total_futures
        if abs(net_exposure - target_net) > tol:
            logger.error(f"多空净敞口偏离 0%: 实际={net_exposure}, 目标={target_net}")
            return False

        # 2. 单票权重硬拦截 (<= 2.5%)
        limit_stock = _conv_dec(max_stock_weight, "max_stock_weight") if max_stock_weight is not None else def_max_stock
        for s, w in dec_stocks.items():
            if w > limit_stock + spec_tol:
                logger.error(f"单票超标硬拦截: {s} 权重 {w} > 上限 {limit_stock}")
                return False

        # 3. 申万一级行业集中度硬拦截 (<= 10% 且 <= 4 只)
        if industry_map is not None:
            limit_ind_w = _conv_dec(max_industry_weight, "max_industry_weight") if max_industry_weight is not None else def_max_ind_w
            ind_weights: Dict[str, Decimal] = {}
            ind_counts: Dict[str, int] = {}
            for s, w in dec_stocks.items():
                ind = industry_map.get(s, "UNKNOWN")
                ind_weights[ind] = ind_weights.get(ind, Decimal("0")) + w
                ind_counts[ind] = ind_counts.get(ind, 0) + 1

            for ind, w in ind_weights.items():
                if w > limit_ind_w + spec_tol:
                    logger.error(f"申万一级行业权重超标硬拦截: {ind} 权重 {w} > 上限 {limit_ind_w}")
                    return False
                if ind_counts[ind] > max_industry_stocks:
                    logger.error(f"申万一级行业持股只数超标硬拦截: {ind} 持有 {ind_counts[ind]} 只 > 上限 {max_industry_stocks} 只")
                    return False

        logger.info(
            f"CNMM-QAR 生产级多空治理三元配置验证通过: 股票={total_stock}, 期货={total_futures}, "
            f"现金={dec_cash}, Gross={gross}, Net={net_exposure}"
        )
        return True

    _validate_hedged_portfolio = validate_hedged_portfolio

    def _to_decimal(self, value: Any) -> Decimal:
        """
        将值转换为Decimal

        Args:
            value: 任意数值

        Returns:
            Decimal: 转换后的值
        """
        if isinstance(value, Decimal):
            return value.quantize(self.DECIMAL_PLACES, rounding=ROUND_HALF_UP)
        return Decimal(str(value)).quantize(self.DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    def _backup_weights(self):
        """备份当前权重"""
        self._previous_weights = self._current_weights.copy()

    def _rollback_weights(self):
        """回滚到之前的权重"""
        if self._previous_weights:
            logger.warning("仓位计算失败，回滚到之前的权重")
            self._current_weights = self._previous_weights.copy()

    def get_structural_risks(self) -> Dict[str, Any]:
        """
        获取结构化风险指标 (Facade Proxy)
        """
        if self.risk_service:
            return self.risk_service.get_structural_risks()
        return {
            "Market Risk": 0.25,
            "Sector Risk": 0.15,
            "Liquidity Risk": 0.10,
        }

    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        risk_pct: float,
        capital: float,
        market: str = "CN",
        czsc_bottom: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        计算建议仓位股数 (Sizer Logic)
        """
        if self.risk_service:
            return self.risk_service.calculate_position_size(
                price, stop_loss, risk_pct, capital, market, czsc_bottom
            )

        # 简单实现作为降级方案
        risk_per_share = max(price - stop_loss, price * 0.01)
        total_risk_allowed = capital * risk_pct
        shares = int(total_risk_allowed / risk_per_share)
        # 修正股数（A股100股一手）
        if market == "CN":
            shares = (shares // 100) * 100

        return {
            "建议股数": shares,
            "修正仓位": shares,
            "执行止损": stop_loss,
            "资金占用": shares * price,
        }

    def add_position(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        shares: int,
    ) -> None:
        """记录持仓"""
        self._current_weights[symbol] = Decimal(str(shares * current_price))

    def remove_position(self, symbol: str) -> None:
        """移除持仓"""
        if symbol in self._current_weights:
            del self._current_weights[symbol]

    @handle_errors(
        AnalysisError, ValueError, TypeError, default_return={}, log_level=logging.ERROR
    )
    def create_portfolio(self, strategy: str, symbols: List[str]) -> Dict[str, Any]:
        """
        Create a new portfolio based on strategy and symbols.
        """
        # Validate input
        if not strategy or not isinstance(strategy, str):
            raise ValueError("Strategy must be a non-empty string")
        if not isinstance(symbols, list):
            raise ValueError("Symbols must be a list")

        portfolio = {
            "strategy": strategy,
            "symbols": symbols,
            "weights": self.calculate_weights(strategy, symbols),
            "created_at": pd.Timestamp(get_time_provider().now()).isoformat(),
        }
        return portfolio

    @handle_errors(
        PortfolioServiceError, ValueError, TypeError, default_return={}, log_level=logging.ERROR
    )
    def calculate_position(
        self, symbol: str, target_pct: Decimal, portfolio_value: Decimal, price: Decimal
    ) -> Dict[str, Any]:
        """
        计算仓位

        使用Decimal避免浮点误差，并验证仓位边界。

        Args:
            symbol: 股票代码
            target_pct: 目标仓位百分比(0-100)
            portfolio_value: 组合总价值
            price: 当前价格

        Returns:
            Dict: 仓位计算结果
        """
        # 备份当前状态
        self._backup_weights()

        try:
            # 参数验证
            if not symbol or not isinstance(symbol, str):
                raise ValueError("股票代码必须是非空字符串")

            target_pct = self._to_decimal(target_pct)
            portfolio_value = self._to_decimal(portfolio_value)
            price = self._to_decimal(price)

            if price <= 0:
                raise ValueError(f"价格必须为正数: {price}")

            if portfolio_value <= 0:
                raise ValueError(f"组合价值必须为正数: {portfolio_value}")

            # 验证仓位边界
            if not self._validate_position(target_pct):
                raise PortfolioServiceError(f"仓位验证失败: {target_pct}%")

            # 计算目标金额
            target_amount = portfolio_value * (target_pct / Decimal("100"))

            # 计算股数（向下取整）
            shares = int(target_amount / price)

            # 计算实际仓位
            actual_amount = self._to_decimal(shares) * price
            actual_pct = (actual_amount / portfolio_value) * Decimal("100")

            # 验证实际仓位
            if not self._validate_position(actual_pct):
                raise PortfolioServiceError(f"实际仓位验证失败: {actual_pct}%")

            result = {
                "symbol": symbol,
                "target_pct": float(target_pct),
                "actual_pct": float(actual_pct.quantize(self.DECIMAL_PLACES)),
                "target_amount": float(target_amount.quantize(self.DECIMAL_PLACES)),
                "actual_amount": float(actual_amount.quantize(self.DECIMAL_PLACES)),
                "shares": shares,
                "price": float(price.quantize(self.DECIMAL_PLACES)),
                "portfolio_value": float(portfolio_value.quantize(self.DECIMAL_PLACES)),
            }

            # 更新当前权重
            self._current_weights[symbol] = actual_pct / Decimal("100")

            logger.info(
                f"仓位计算成功: {symbol} - 目标{target_pct}%, 实际{actual_pct}%"
            )
            return result

        except PORTFOLIO_RECOVERABLE_ERRORS as e:
            # 回滚状态
            self._rollback_weights()
            logger.error(f"仓位计算失败: {e}")
            raise PortfolioServiceError(f"仓位计算失败: {e}") from e

    @handle_errors(ValueError, TypeError, default_return={}, log_level=logging.ERROR)
    def calculate_weights(
        self, strategy: str, symbols: List[str]
    ) -> Dict[str, Decimal]:
        """
        Calculate portfolio weights based on strategy.

        使用Decimal避免浮点误差。

        Args:
            strategy: 策略名称
            symbols: 股票代码列表

        Returns:
            Dict[str, Decimal]: 权重字典
        """
        weights: Dict[str, Decimal] = {}
        n = len(symbols)

        if n == 0:
            return weights

        if strategy == "equal_weight":
            weight = Decimal("1") / Decimal(str(n))
            weights = {symbol: weight for symbol in symbols}
        elif strategy == "market_cap":
            # In a real implementation, we would fetch market caps
            # For now, return equal weights as a placeholder
            weight = Decimal("1") / Decimal(str(n))
            weights = {symbol: weight for symbol in symbols}
        else:
            # Default to equal weights
            weight = Decimal("1") / Decimal(str(n))
            weights = {symbol: weight for symbol in symbols}

        # 验证权重
        if not self._validate_weights(weights):
            logger.warning("权重验证失败，使用默认等权重")
            weight = Decimal("1") / Decimal(str(n))
            weights = {symbol: weight for symbol in symbols}

        return weights

    @handle_errors(
        RiskCalculationError,
        ValueError,
        TypeError,
        default_return={},
        log_level=logging.ERROR,
    )
    def analyze_portfolio(self, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze portfolio risk and performance.
        """
        # Validate input
        if not isinstance(portfolio, dict):
            raise ValueError("Portfolio must be a dictionary")
        if "symbols" not in portfolio or "weights" not in portfolio:
            raise ValueError("Portfolio must contain 'symbols' and 'weights' keys")

        analysis = {
            "risk_metrics": self.calculate_risk_metrics(portfolio),
            "performance_metrics": self.calculate_performance_metrics(portfolio),
            "analysis_date": pd.Timestamp(get_time_provider().now()).isoformat(),
        }
        return analysis

    @handle_errors(
        RiskCalculationError, ValueError, TypeError, default_return={}, log_level=logging.ERROR
    )
    def calculate_risk_metrics(self, portfolio: Dict[str, Any]) -> Dict[str, float]:
        """
        Calculate portfolio risk metrics.
        """
        # Placeholder implementation
        return {
            "volatility": 0.15,
            "max_drawdown": 0.25,
            "sharpe_ratio": 0.8,
            "sortino_ratio": 0.6,
        }

    @handle_errors(ValueError, TypeError, default_return={}, log_level=logging.ERROR)
    def calculate_performance_metrics(
        self, portfolio: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculate portfolio performance metrics.
        """
        # Placeholder implementation
        return {"total_return": 0.12, "annual_return": 0.08, "alpha": 0.02, "beta": 0.9}

    def calculate_evt_risk_metrics(self, portfolio_returns: pd.Series) -> Dict[str, Any]:
        """
        Calculate EVT-style portfolio risk metrics from a return series.

        UI callers should delegate risk calculations here instead of importing
        risk engines directly, keeping service boundaries explicit.
        """
        from ..risk.evt_risk import EVTRisk

        if not isinstance(portfolio_returns, pd.Series):
            raise TypeError("portfolio_returns must be a pandas Series")
        if portfolio_returns.empty:
            raise ValueError("portfolio_returns cannot be empty")

        return EVTRisk().calculate_metrics(portfolio_returns)

    def optimize_returns_portfolio(
        self, returns_df: pd.DataFrame, method: str = "risk_parity"
    ) -> Dict[str, Any]:
        """
        Optimize a portfolio from aligned asset return columns.
        """
        from ..risk.portfolio_optimizer import OptimizerConfig, PortfolioOptimizer

        if not isinstance(returns_df, pd.DataFrame):
            raise TypeError("returns_df must be a pandas DataFrame")
        if returns_df.empty or len(returns_df.columns) < 2:
            return {"error": "需要至少2只股票进行优化"}

        optimizer = PortfolioOptimizer(OptimizerConfig(max_weight=0.4, min_weight=0.0))
        if method == "risk_parity":
            result = optimizer.optimize_risk_parity(returns_df)
        elif method == "mean_variance":
            result = optimizer.optimize_mean_variance(returns_df, target="max_sharpe")
        else:
            return {"error": f"未知的优化方法: {method}"}

        if result is None:
            return {"error": "优化失败"}

        return {
            "status": "success",
            "method": method,
            "weights": result.get("weights", {}),
            "expected_return": result.get("expected_return", 0),
            "expected_volatility": result.get("expected_volatility", 0),
            "sharpe_ratio": result.get("sharpe_ratio", 0),
            "risk_contributions": result.get("risk_contributions", {}),
        }

    def run_evt_stress_test(
        self, portfolio_returns: pd.Series, scenarios: List[str]
    ) -> Dict[str, float]:
        """
        Run EVT stress scenarios from a portfolio return series.
        """
        from ..risk.evt_risk import EVTRisk

        if not isinstance(portfolio_returns, pd.Series):
            raise TypeError("portfolio_returns must be a pandas Series")
        if portfolio_returns.empty:
            raise ValueError("portfolio_returns cannot be empty")

        return EVTRisk().calculate_stress_test(portfolio_returns, scenarios)

    @handle_errors(
        PortfolioServiceError, ValueError, TypeError, default_return={}, log_level=logging.ERROR
    )
    def rebalance(
        self,
        portfolio: Dict[str, Any],
        target_weights: Dict[str, Decimal],
        prices: Dict[str, Decimal],
    ) -> Dict[str, Any]:
        """
        再平衡投资组合

        使用Decimal避免浮点误差，失败时保持原有仓位。

        Args:
            portfolio: 当前投资组合
            target_weights: 目标权重
            prices: 当前价格

        Returns:
            Dict: 再平衡结果
        """
        # 备份当前权重
        self._backup_weights()

        try:
            # 验证输入
            if not isinstance(portfolio, dict):
                raise ValueError("Portfolio必须是字典")
            if not isinstance(target_weights, dict):
                raise ValueError("Target weights必须是字典")
            if not target_weights:
                raise ValueError("Target weights不能为空")
            if not isinstance(prices, dict):
                raise ValueError("Prices必须是字典")

            # 验证权重
            if not self._validate_weights(target_weights):
                raise PortfolioServiceError("目标权重验证失败")

            # 获取组合总价值
            portfolio_value = self._to_decimal(portfolio.get("total_value", 0))
            if portfolio_value <= 0:
                raise ValueError("组合价值必须为正数")

            # 计算再平衡交易
            trades = []
            current_weights = portfolio.get("weights", {})

            for symbol, target_weight in target_weights.items():
                if symbol not in prices:
                    logger.warning(f"缺少 {symbol} 的价格信息，跳过")
                    continue

                price = self._to_decimal(prices[symbol])
                if price <= 0:
                    logger.warning(f"{symbol} 价格无效: {price}")
                    continue

                current_weight = self._to_decimal(current_weights.get(symbol, 0))
                target_weight_decimal = self._to_decimal(target_weight)
                weight_diff = target_weight_decimal - current_weight

                # 计算需要交易的金额
                trade_amount = portfolio_value * weight_diff

                # 计算股数
                shares = int(abs(trade_amount) / price)

                if shares > 0:
                    action = "BUY" if trade_amount > 0 else "SELL"
                    trades.append(
                        {
                            "symbol": symbol,
                            "action": action,
                            "shares": shares,
                            "price": float(price.quantize(self.DECIMAL_PLACES)),
                            "amount": float(
                                abs(trade_amount).quantize(self.DECIMAL_PLACES)
                            ),
                        }
                    )

            # 更新权重
            self._current_weights = target_weights.copy()

            rebalanced = portfolio.copy()
            rebalanced["weights"] = {k: float(v) for k, v in target_weights.items()}
            rebalanced["rebalanced_at"] = pd.Timestamp(get_time_provider().now()).isoformat()
            rebalanced["trades"] = trades

            logger.info(f"再平衡完成: {len(trades)} 笔交易")
            return rebalanced

        except PORTFOLIO_RECOVERABLE_ERRORS as e:
            # 回滚权重
            self._rollback_weights()
            logger.error(f"再平衡失败，权重已回滚: {e}")
            raise PortfolioServiceError(f"再平衡失败: {e}") from e

    def rebalance_portfolio(
        self, portfolio: Dict[str, Any], target_weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Rebalance portfolio to target weights.

        兼容旧版本接口。
        """
        try:
            # Validate input
            if not isinstance(portfolio, dict):
                raise ValueError("Portfolio must be a dictionary")
            if not isinstance(target_weights, dict):
                raise ValueError("Target weights must be a dictionary")
            if not target_weights:
                raise ValueError("Target weights cannot be empty")

            rebalanced = portfolio.copy()
            rebalanced["weights"] = target_weights
            rebalanced["rebalanced_at"] = pd.Timestamp(get_time_provider().now()).isoformat()
            return rebalanced
        except DataValidationError as e:
            logger.error(f"Failed to rebalance portfolio: {e}")
            return {}
        except ValueError as e:
            logger.error(f"Invalid input for rebalance_portfolio: {e}")
            return {}
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            logger.critical(
                f"Unexpected error in rebalance_portfolio: {e}", exc_info=True
            )
            return {}

    def generate_rebalancing_signals(self, portfolio: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate rebalancing signals for portfolio.
        """
        try:
            # Validate input
            if not isinstance(portfolio, dict):
                raise ValueError("Portfolio must be a dictionary")

            # Placeholder implementation
            signals = {}
            for symbol in portfolio.get("symbols", []):
                signals[symbol] = "HOLD"
            return signals
        except ValueError as e:
            logger.error(f"Invalid input for generate_rebalancing_signals: {e}")
            return {}
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            logger.critical(
                f"Unexpected error in generate_rebalancing_signals: {e}", exc_info=True
            )
            return {}

    def get_portfolio(self) -> pd.DataFrame:
        """
        获取投资组合详情

        Returns:
            pd.DataFrame: 包含证券代码、权重等信息的DataFrame
        """
        if not self._current_weights:
            return pd.DataFrame()

        data = []
        for symbol, weight in self._current_weights.items():
            data.append({"证券代码": symbol, "权重": float(weight), "状态": "持仓"})

        return pd.DataFrame(data)
