"""
Portfolio Analytics and Validation Helpers for PortfolioService.
================================================================

Extracts risk metrics, EVT stress testing, optimization helpers,
and portfolio weight validation routines to keep PortfolioService lean (<800 lines).
"""

from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from ..shared.exceptions import DataValidationError
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider

logger = get_logger("PortfolioAnalyticsHelper")


def validate_portfolio_weights(
    weights: Dict[str, Any],
    min_position_pct: Decimal = Decimal("-100"),
    max_position_pct: Decimal = Decimal("100"),
    allow_short: bool = True,
    max_gross_leverage: Optional[Decimal] = None,
    log: Optional[logging.Logger] = None,
) -> bool:
    """
    验证权重是否有效

    支持两种模式：
    1. 经典单边做多存量模式：
       所有权重 >= 0，且权重总和严格为 1 (比例制) 或 100 (百分比制)。
    2. 多空对冲模式 (Long-Short Hedging)：
       允许负权重（做空/衍生品空头对冲，如 75% 股票 + (-75%) 期货 + 25% 现金，Gross 175%，Net ≈ 0%）。
       单资产仓位处于 [min_position_pct, max_position_pct] 范围内；
       总敞口 Gross Leverage <= max_gross_leverage (默认 300% 或 3.0)。
    """
    active_logger = log or logger

    if not weights or not isinstance(weights, dict):
        active_logger.error("权重字典不能为空且必须为字典")
        return False

    tolerance = Decimal("0.0001")
    decimal_weights: Dict[str, Decimal] = {}

    # 1. 转换所有权重为 Decimal
    for symbol, weight in weights.items():
        if not symbol or not isinstance(symbol, str):
            active_logger.error(f"证券代码非法: {symbol}")
            return False
        try:
            if isinstance(weight, float):
                decimal_weights[symbol] = Decimal(str(weight))
            elif isinstance(weight, Decimal):
                decimal_weights[symbol] = weight
            else:
                decimal_weights[symbol] = Decimal(str(weight))
        except (ValueError, TypeError, ArithmeticError) as e:
            active_logger.error(f"权重值无法转换为Decimal: {symbol}={weight}, error={e}")
            return False

    has_short = any(w < Decimal("0") for w in decimal_weights.values())
    if has_short and not allow_short:
        active_logger.error("当前策略配置禁止空头/负权重")
        return False

    # 2. 判断量纲：比率制 (Base 1.0) 还是 百分比制 (Base 100)
    gross_raw = sum(abs(w) for w in decimal_weights.values())
    is_percentage = (
        any(abs(w) > Decimal("1.0001") for w in decimal_weights.values())
        or gross_raw > Decimal("3.0")
    )

    # 3. 边界约束检查
    min_bound = (
        min_position_pct
        if is_percentage
        else (min_position_pct / Decimal("100"))
    )
    max_bound = (
        max_position_pct
        if is_percentage
        else (max_position_pct / Decimal("100"))
    )

    if not allow_short:
        min_bound = Decimal("0")

    for symbol, w in decimal_weights.items():
        if w < min_bound - tolerance:
            active_logger.error(f"权重低于下限({min_bound}): {symbol}={w}")
            return False
        if w > max_bound + tolerance:
            active_logger.error(f"权重超过上限({max_bound}): {symbol}={w}")
            return False

    # 4. 单边做多存量策略模式（所有权重非负）
    if not has_short:
        total = sum(decimal_weights.values())
        if (
            abs(total - Decimal("1")) > tolerance
            and abs(total - Decimal("100")) > tolerance
        ):
            active_logger.error(f"单边做多策略权重总和必须为1或100: {total}")
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
        active_logger.error(
            f"多空组合总杠杆敞口(Gross={gross})超出最大允许限制({max_gross})"
        )
        return False

    if gross <= tolerance:
        active_logger.error(f"多空组合总敞口必须为正: Gross={gross}")
        return False

    if abs(net_total) > gross + tolerance:
        active_logger.error(f"多空组合净敞口异常: Net={net_total}, Gross={gross}")
        return False

    active_logger.info(
        f"多空对冲权重验证通过: 标的数={len(decimal_weights)}, Gross={gross}{'%' if is_percentage else ''}, "
        f"Net={net_total}{'%' if is_percentage else ''}"
    )
    return True


def validate_hedged_portfolio_spec(
    stock_weights: Dict[str, Any],
    futures_weights: Dict[str, Any],
    cash_weight: Any,
    industry_map: Optional[Dict[str, str]] = None,
    max_stock_weight: Optional[Any] = None,
    max_industry_weight: Optional[Any] = None,
    max_industry_stocks: int = 4,
    log: Optional[logging.Logger] = None,
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
    active_logger = log or logger

    if not stock_weights or not isinstance(stock_weights, dict):
        active_logger.error("股票多头权重字典不能为空且必须为字典")
        return False
    if not futures_weights or not isinstance(futures_weights, dict):
        active_logger.error("股指期货空头权重字典不能为空且必须为字典")
        return False

    def _conv_dec(v: Any, name: str) -> Optional[Decimal]:
        try:
            return Decimal(str(v))
        except (ValueError, TypeError, ArithmeticError) as e:
            active_logger.error(f"权重值无法转换为Decimal: {name}={v}, error={e}")
            return None

    dec_stocks: Dict[str, Decimal] = {}
    for s, w in stock_weights.items():
        dw = _conv_dec(w, s)
        if dw is None:
            return False
        if dw <= Decimal("0"):
            active_logger.error(f"现货多头股票权重必须为正: {s}={dw}")
            return False
        dec_stocks[s] = dw

    dec_futures: Dict[str, Decimal] = {}
    for f_sym, w in futures_weights.items():
        dw = _conv_dec(w, f_sym)
        if dw is None:
            return False
        if dw >= Decimal("0"):
            active_logger.error(f"衍生品对冲期货权重必须为负(做空): {f_sym}={dw}")
            return False
        dec_futures[f_sym] = dw

    dec_cash = _conv_dec(cash_weight, "CASH")
    if dec_cash is None:
        return False
    if dec_cash <= Decimal("0"):
        active_logger.error(f"现金缓冲池权重必须为正: CASH={dec_cash}")
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
        active_logger.error(f"股票多头总仓位偏离 75%: 实际={total_stock}, 目标={target_stock}")
        return False

    total_futures = sum(dec_futures.values())
    if abs(total_futures - target_futures) > tol:
        active_logger.error(f"期指空头总仓位偏离 -75%: 实际={total_futures}, 目标={target_futures}")
        return False

    if abs(dec_cash - target_cash) > tol:
        active_logger.error(f"流动性现金缓冲池偏离 25%: 实际={dec_cash}, 目标={target_cash}")
        return False

    # 总杠杆与净敞口严格核算
    gross = total_stock + abs(total_futures) + dec_cash
    if abs(gross - target_gross) > tol:
        active_logger.error(f"多空总杠杆偏离 175%: 实际={gross}, 目标={target_gross}")
        return False

    net_exposure = total_stock + total_futures
    if abs(net_exposure - target_net) > tol:
        active_logger.error(f"多空净敞口偏离 0%: 实际={net_exposure}, 目标={target_net}")
        return False

    # 2. 单票权重硬拦截 (<= 2.5%)
    limit_stock = _conv_dec(max_stock_weight, "max_stock_weight") if max_stock_weight is not None else def_max_stock
    for s, w in dec_stocks.items():
        if w > limit_stock + spec_tol:
            active_logger.error(f"单票超标硬拦截: {s} 权重 {w} > 上限 {limit_stock}")
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
                active_logger.error(f"申万一级行业权重超标硬拦截: {ind} 权重 {w} > 上限 {limit_ind_w}")
                return False
            if ind_counts[ind] > max_industry_stocks:
                active_logger.error(
                    f"申万一级行业持股只数超标硬拦截: {ind} 持有 {ind_counts[ind]} 只 > 上限 {max_industry_stocks} 只"
                )
                return False

    active_logger.info(
        f"CNMM-QAR 生产级多空治理三元配置验证通过: 股票={total_stock}, 期货={total_futures}, "
        f"现金={dec_cash}, Gross={gross}, Net={net_exposure}"
    )
    return True


def calculate_risk_metrics_helper(portfolio: Dict[str, Any]) -> Dict[str, float]:
    """Calculate portfolio risk metrics placeholder."""
    return {
        "volatility": 0.15,
        "max_drawdown": 0.25,
        "sharpe_ratio": 0.8,
        "sortino_ratio": 0.6,
    }


def calculate_performance_metrics_helper(portfolio: Dict[str, Any]) -> Dict[str, float]:
    """Calculate portfolio performance metrics placeholder."""
    return {"total_return": 0.12, "annual_return": 0.08, "alpha": 0.02, "beta": 0.9}


def calculate_evt_risk_metrics_helper(portfolio_returns: pd.Series) -> Dict[str, Any]:
    """
    Calculate EVT-style portfolio risk metrics from a return series.
    """
    from ..risk.evt_risk import EVTRisk

    if not isinstance(portfolio_returns, pd.Series):
        raise TypeError("portfolio_returns must be a pandas Series")
    if portfolio_returns.empty:
        raise ValueError("portfolio_returns cannot be empty")

    return EVTRisk().calculate_metrics(portfolio_returns)


def optimize_returns_portfolio_helper(
    returns_df: pd.DataFrame, method: str = "risk_parity"
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


def run_evt_stress_test_helper(
    portfolio_returns: pd.Series, scenarios: List[str]
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


def rebalance_portfolio_compat(
    portfolio: Dict[str, Any],
    target_weights: Dict[str, float],
    log: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """
    Rebalance portfolio to target weights (legacy compatibility).
    """
    active_logger = log or logger
    try:
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
        active_logger.error(f"Failed to rebalance portfolio: {e}")
        return {}
    except ValueError as e:
        active_logger.error(f"Invalid input for rebalance_portfolio: {e}")
        return {}
    except (AttributeError, RuntimeError, TypeError) as e:
        active_logger.critical(
            f"Unexpected error in rebalance_portfolio: {e}", exc_info=True
        )
        return {}


def generate_rebalancing_signals_helper(
    portfolio: Dict[str, Any],
    log: Optional[logging.Logger] = None,
) -> Dict[str, str]:
    """
    Generate rebalancing signals for portfolio.
    """
    active_logger = log or logger
    try:
        if not isinstance(portfolio, dict):
            raise ValueError("Portfolio must be a dictionary")

        signals = {}
        for symbol in portfolio.get("symbols", []):
            signals[symbol] = "HOLD"
        return signals
    except ValueError as e:
        active_logger.error(f"Invalid input for generate_rebalancing_signals: {e}")
        return {}
    except (AttributeError, RuntimeError, TypeError) as e:
        active_logger.critical(
            f"Unexpected error in generate_rebalancing_signals: {e}", exc_info=True
        )
        return {}
