import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..services.portfolio_service import PortfolioService
from ..shared.constants import RiskCalculationConstants
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider

logger = get_logger(__name__)


class ManagerPortfolioAnalyticsService:
    """Portfolio analytics helpers used by AssetManager."""

    def __init__(self, manager: Any):
        self.manager = manager
        self.portfolio_service = getattr(manager, "portfolio_service", None) or PortfolioService()

    def calculate_portfolio_risk_metrics(
        self, symbols: List[str], lookback_days: int = 252
    ) -> Dict[str, Any]:
        try:
            portfolio_returns = self._collect_returns(
                symbols=symbols,
                lookback_days=lookback_days,
                min_points=lookback_days,
                symbol_limit=10,
            )
            if not portfolio_returns:
                return {"error": "无法获取足够的股票数据"}

            portfolio_returns_series = self._build_equal_weight_series(portfolio_returns)
            risk_metrics = self.portfolio_service.calculate_evt_risk_metrics(
                portfolio_returns_series
            )

            return {
                "status": "success",
                "symbols_count": len(portfolio_returns),
                "lookback_days": lookback_days,
                "var_95": risk_metrics.get("var_95", 0),
                "var_99": risk_metrics.get("var_99", 0),
                "cvar_95": risk_metrics.get("cvar_95", 0),
                "cvar_99": risk_metrics.get("cvar_99", 0),
                "max_drawdown": risk_metrics.get("max_drawdown", 0),
                "regime": risk_metrics.get("regime", "NORMAL"),
                "summary": risk_metrics.get("summary", ""),
            }
        except (ValueError, TypeError) as exc:
            logger.error("风险指标计算输入错误: %s", exc)
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            logger.critical("风险指标计算异常: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    def optimize_portfolio(
        self,
        symbols: List[str],
        method: str = "risk_parity",
        lookback_days: int = 252,
    ) -> Dict[str, Any]:
        try:
            returns_data = self._collect_returns(
                symbols=symbols,
                lookback_days=lookback_days,
                min_points=30,
                symbol_limit=10,
            )
            if len(returns_data) < 2:
                return {"error": "需要至少2只股票进行优化"}

            returns_df = self._build_returns_frame(returns_data)
            return self.portfolio_service.optimize_returns_portfolio(returns_df, method)
        except (ValueError, TypeError) as exc:
            logger.error("组合优化输入错误: %s", exc)
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            logger.critical("组合优化异常: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    def run_stress_test(
        self, symbols: List[str], scenarios: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        try:
            portfolio_returns = self._collect_returns(
                symbols=symbols,
                lookback_days=252,
                min_points=60,
                symbol_limit=5,
            )
            if not portfolio_returns:
                return {"error": "无法获取足够的股票数据"}

            portfolio_returns_series = self._build_equal_weight_series(portfolio_returns)
            if scenarios is None:
                scenarios = list(RiskCalculationConstants.CRASH_SCENARIOS.keys())[:5]
            stress_results = self.portfolio_service.run_evt_stress_test(
                portfolio_returns_series, scenarios
            )
            return {
                "status": "success",
                "scenarios_tested": len(scenarios),
                "scenario_results": stress_results,
                "scenarios": scenarios,
            }
        except (ValueError, TypeError) as exc:
            logger.error("压力测试输入错误: %s", exc)
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            logger.critical("压力测试异常: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    def _collect_returns(
        self,
        *,
        symbols: List[str],
        lookback_days: int,
        min_points: int,
        symbol_limit: int,
    ) -> Dict[str, pd.Series]:
        returns_data: Dict[str, pd.Series] = {}
        end_date = get_time_provider().now()
        start_date = end_date - datetime.timedelta(days=lookback_days * 2)

        for symbol in symbols[:symbol_limit]:
            try:
                df = self.manager.get_real_kline_data(
                    symbol,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                )
                if df is None or df.empty or len(df) < min_points:
                    continue
                returns = df["close"].pct_change().dropna()
                if len(returns) >= min_points:
                    returns_data[symbol] = returns.iloc[-lookback_days:]
            except Exception as exc:
                logger.warning("获取 %s 数据失败: %s", symbol, exc)
        return returns_data

    @staticmethod
    def _build_equal_weight_series(returns_data: Dict[str, pd.Series]) -> pd.Series:
        min_len = min(len(r) for r in returns_data.values())
        aligned_returns = [returns.iloc[-min_len:].values for returns in returns_data.values()]
        return pd.Series(np.mean(aligned_returns, axis=0))

    @staticmethod
    def _build_returns_frame(returns_data: Dict[str, pd.Series]) -> pd.DataFrame:
        min_len = min(len(r) for r in returns_data.values())
        return pd.DataFrame(
            {
                symbol: returns.iloc[-min_len:].values
                for symbol, returns in returns_data.items()
            }
        )
