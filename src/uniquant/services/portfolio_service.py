import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

import pandas as pd

from ..shared.error_handling import handle_errors
from ..shared.exceptions import (
    AnalysisError,
    DataValidationError,
    PortfolioServiceError,
    RiskCalculationError,
)
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider
from .portfolio_analytics_helper import (
    calculate_evt_risk_metrics_helper,
    calculate_performance_metrics_helper,
    calculate_risk_metrics_helper,
    generate_rebalancing_signals_helper,
    optimize_returns_portfolio_helper,
    rebalance_portfolio_compat,
    run_evt_stress_test_helper,
    validate_hedged_portfolio_spec,
    validate_portfolio_weights,
)

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
        return validate_portfolio_weights(
            weights=weights,
            min_position_pct=self.MIN_POSITION_PCT,
            max_position_pct=self.MAX_POSITION_PCT,
            allow_short=allow_short,
            max_gross_leverage=max_gross_leverage,
            log=logger,
        )

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
        return validate_hedged_portfolio_spec(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=industry_map,
            max_stock_weight=max_stock_weight,
            max_industry_weight=max_industry_weight,
            max_industry_stocks=max_industry_stocks,
            log=logger,
        )

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
        return calculate_risk_metrics_helper(portfolio)

    @handle_errors(ValueError, TypeError, default_return={}, log_level=logging.ERROR)
    def calculate_performance_metrics(
        self, portfolio: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculate portfolio performance metrics.
        """
        return calculate_performance_metrics_helper(portfolio)

    def calculate_evt_risk_metrics(self, portfolio_returns: pd.Series) -> Dict[str, Any]:
        """
        Calculate EVT-style portfolio risk metrics from a return series.

        UI callers should delegate risk calculations here instead of importing
        risk engines directly, keeping service boundaries explicit.
        """
        return calculate_evt_risk_metrics_helper(portfolio_returns)

    def optimize_returns_portfolio(
        self, returns_df: pd.DataFrame, method: str = "risk_parity"
    ) -> Dict[str, Any]:
        """
        Optimize a portfolio from aligned asset return columns.
        """
        return optimize_returns_portfolio_helper(returns_df, method=method)

    def run_evt_stress_test(
        self, portfolio_returns: pd.Series, scenarios: List[str]
    ) -> Dict[str, float]:
        """
        Run EVT stress scenarios from a portfolio return series.
        """
        return run_evt_stress_test_helper(portfolio_returns, scenarios=scenarios)

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
        return rebalance_portfolio_compat(portfolio, target_weights, log=logger)

    def generate_rebalancing_signals(self, portfolio: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate rebalancing signals for portfolio.
        """
        return generate_rebalancing_signals_helper(portfolio, log=logger)

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
