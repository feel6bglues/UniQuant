"""
向量化极限回撤分析引擎
全部 NumPy 算子，零 iterrows

MDD_t = max(0, (max_{τ≤t} P_τ - P_t) / max_{τ≤t} P_τ)

Calmar = R_ann / |MDD|
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class DrawdownMetrics:
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    avg_drawdown: float = 0.0
    avg_drawdown_duration: float = 0.0
    calmar_ratio: float = 0.0
    ulcer_index: float = 0.0
    rolling_mdd_60d: float = 0.0
    rolling_mdd_120d: float = 0.0
    rolling_mdd_252d: float = 0.0

    def __str__(self) -> str:
        return (
            f"DrawdownMetrics(max_drawdown={self.max_drawdown:.4%}, "
            f"max_drawdown_duration={self.max_drawdown_duration}d, "
            f"calmar_ratio={self.calmar_ratio:.4f}, "
            f"ulcer_index={self.ulcer_index:.4f}, "
            f"rolling_mdd_60d={self.rolling_mdd_60d:.4%}, "
            f"rolling_mdd_120d={self.rolling_mdd_120d:.4%}, "
            f"rolling_mdd_252d={self.rolling_mdd_252d:.4%})"
        )


@dataclass
class TailRiskMetrics:
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    cvar_99: float = 0.0
    tail_ratio: float = 1.0
    skewness: float = 0.0
    kurtosis: float = 3.0

    def __str__(self) -> str:
        return (
            f"TailRiskMetrics(VaR(95%)={self.var_95:.4%}, "
            f"VaR(99%)={self.var_99:.4%}, "
            f"CVaR(95%)={self.cvar_95:.4%}, "
            f"CVaR(99%)={self.cvar_99:.4%}, "
            f"tail_ratio={self.tail_ratio:.4f}, "
            f"skewness={self.skewness:.4f}, "
            f"kurtosis={self.kurtosis:.4f})"
        )


@dataclass
class StressTestResult:
    scenario: str
    loss_pct: float
    loss_value: float
    recovered: bool = False
    recovery_days: int = 0

    @property
    def max_dd_pct(self) -> float:
        return self.loss_pct

    def __str__(self) -> str:
        status = "recovered" if self.recovered else "unrecovered"
        return (
            f"StressTestResult(scenario={self.scenario}, "
            f"loss_pct={self.loss_pct:.4%}, "
            f"loss_value={self.loss_value:,.2f}, "
            f"status={status}, "
            f"recovery_days={self.recovery_days})"
        )


class DrawdownAnalyzer:
    @staticmethod
    def compute_drawdown_series(equity: np.ndarray) -> np.ndarray:
        assert equity.ndim == 1 and len(equity) > 1
        rolling_max = np.maximum.accumulate(equity)
        return (equity - rolling_max) / np.maximum(rolling_max, 1e-10)

    @staticmethod
    def compute_rolling_mdd(equity: np.ndarray, window: int) -> np.ndarray:
        n = len(equity)
        result = np.zeros(n, dtype=np.float64)
        for i in range(window - 1, n):
            seg = equity[i - window + 1 : i + 1]
            rm = np.maximum.accumulate(seg)
            dd = (seg - rm) / np.maximum(rm, 1e-10)
            result[i] = -np.min(dd)
        return result

    @classmethod
    def analyze_drawdown(cls, equity: np.ndarray, annual_return: float = 0.0) -> DrawdownMetrics:
        n = len(equity)
        if n < 2:
            return DrawdownMetrics()

        dd = cls.compute_drawdown_series(equity)

        mdd = -np.min(dd)
        avg_dd = -np.nanmean(dd)

        dd_below_zero = dd < 0
        changes = np.diff(dd_below_zero.astype(np.int8))
        starts = np.where(changes == 1)[0] + 1
        ends = np.where(changes == -1)[0] + 1

        if dd_below_zero[0]:
            starts = np.concatenate([[0], starts])
        if dd_below_zero[-1]:
            ends = np.concatenate([ends, [n]])

        durations = ends - starts if len(starts) > 0 and len(ends) > 0 else np.array([0])
        max_duration = int(np.max(durations)) if len(durations) > 0 else 0
        avg_duration = float(np.mean(durations)) if len(durations) > 0 else 0.0

        squares = dd[dd < 0] ** 2
        ui = float(np.sqrt(np.nanmean(squares))) if len(squares) > 0 else 0.0

        calmar = abs(annual_return / mdd) if mdd > 1e-10 else 0.0

        rmdd_60 = float(-np.min(cls.compute_rolling_mdd(equity, 60))) if n >= 60 else 0.0
        rmdd_120 = float(-np.min(cls.compute_rolling_mdd(equity, 120))) if n >= 120 else 0.0
        rmdd_252 = float(-np.min(cls.compute_rolling_mdd(equity, 252))) if n >= 252 else 0.0

        return DrawdownMetrics(
            max_drawdown=mdd,
            max_drawdown_duration=max_duration,
            avg_drawdown=avg_dd,
            avg_drawdown_duration=avg_duration,
            calmar_ratio=calmar,
            ulcer_index=ui,
            rolling_mdd_60d=rmdd_60,
            rolling_mdd_120d=rmdd_120,
            rolling_mdd_252d=rmdd_252,
        )

    @staticmethod
    def analyze_tail_risk(returns: np.ndarray) -> TailRiskMetrics:
        assert returns.ndim == 1 and len(returns) > 1

        var_95 = float(-np.percentile(returns, 5))
        var_99 = float(-np.percentile(returns, 1))
        cvar_95 = float(-np.mean(returns[returns <= -var_95])) if np.any(returns <= -var_95) else var_95
        cvar_99 = float(-np.mean(returns[returns <= -var_99])) if np.any(returns <= -var_99) else var_99

        p95 = float(np.percentile(returns, 95))
        p05 = float(np.percentile(returns, 5))
        tail_ratio = p95 / abs(p05) if p05 != 0 else 1.0

        s = np.std(returns, ddof=0)
        m = np.mean(returns)
        skew = float(np.mean((returns - m) ** 3) / (s ** 3)) if s > 0 else 0.0
        kurt = float(np.mean((returns - m) ** 4) / (s ** 4)) if s > 0 else 3.0

        return TailRiskMetrics(
            var_95=var_95, var_99=var_99,
            cvar_95=cvar_95, cvar_99=cvar_99,
            tail_ratio=tail_ratio, skewness=skew, kurtosis=kurt,
        )

    @staticmethod
    def stress_scenario(equity: np.ndarray, scenario_name: str) -> StressTestResult:
        scenarios = {
            "2015_crash": -0.40,
            "2016_meltdown": -0.10,
            "2018_bear": -0.30,
            "2020_covid": -0.15,
            "2024_microcap_stampede": -0.25,
        }
        crash = scenarios.get(scenario_name, -0.10)
        stressed = equity * (1.0 + crash)
        return StressTestResult(
            scenario=scenario_name,
            loss_pct=crash,
            loss_value=float(stressed[-1] - equity[-1]),
        )
