"""
样本外 Walk-Forward 因子扫描流水线
严格切断训练/测试泄漏：
  - 训练窗口 {train_window} 天 → 计算 IC/IR → 确定权重
  - 测试窗口 {test_window} 天 → 用训练权重打分
  - 滚动前进，永不使用未来数据
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger
from .analyzer import AnalysisMode, FactorAnalyzer, check_lookahead_leakage, LookaheadBiasError
from .composer import FactorComposer

if TYPE_CHECKING:  # 科研控制平面为可选依赖：仅在显式传入 ledger 时才需要
    from ...research.ledger.degrees_of_freedom import DegreesOfFreedomLedger

logger = get_logger(__name__)


@dataclass
class WalkForwardWindowResult:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    ic_mean: Dict[str, float]
    icir: Dict[str, float]
    weights: Dict[str, float]
    n_train_stocks: int
    n_test_stocks: int


@dataclass
class WalkForwardResult:
    windows: List[WalkForwardWindowResult]
    final_weights: Dict[str, float]
    oos_ic_mean: float
    oos_ic_std: float
    oos_icir: float
    weight_stability: Dict[str, float]
    ledger_audit: Optional[Dict[str, Any]] = None


class WalkForwardFactorPipeline:
    def __init__(
        self,
        factor_analyzer: Optional[FactorAnalyzer] = None,
        factor_composer: Optional[FactorComposer] = None,
        train_window: int = 504,
        test_window: int = 63,
        min_train_days: int = 252,
        weight_method: str = "rank_icir",
        half_life: Optional[int] = None,
        ledger: Optional["DegreesOfFreedomLedger"] = None,
        ledger_family_id: str = "walk_forward",
    ):
        self.analyzer = factor_analyzer or FactorAnalyzer()
        self.composer = factor_composer or FactorComposer()
        self.train_window = train_window
        self.test_window = test_window
        self.min_train_days = min_train_days
        self.weight_method = weight_method
        self.half_life = half_life
        self.ledger = ledger
        self.ledger_family_id = ledger_family_id
        self._ic_history: Dict[str, Dict[str, List[float]]] = {}

    def _temporal_split(
        self,
        df: pd.DataFrame,
        date_col: str = "date",
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        dates = pd.to_datetime(df[date_col].unique())
        dates = np.sort(dates)
        train = self.train_window
        test = self.test_window
        n = len(dates)
        windows: List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
        for start in range(train, n - test, test):
            windows.append((
                dates[start - train], dates[start - 1],
                dates[start], dates[start + test - 1],
            ))
        return windows

    def _compute_weights(
        self,
        ic_results: Dict[str, Dict[int, Any]],
        factor_cols: List[str],
    ) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for col in factor_cols:
            if col not in ic_results or not ic_results[col]:
                weights[col] = 1.0 / max(len(factor_cols), 1)
                continue
            period_results = ic_results[col]
            best_icir = 0.0
            for period, result in period_results.items():
                ir = abs(float(getattr(result, "icir", 0)))
                if ir > best_icir:
                    best_icir = ir
            weights[col] = max(best_icir, 0.0)

        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            weights = {col: 1.0 / max(len(factor_cols), 1) for col in factor_cols}
        return weights

    def run(
        self,
        df: pd.DataFrame,
        factor_cols: Optional[List[str]] = None,
        date_col: str = "date",
        code_col: str = "code",
        price_col: str = "close",
        factor_func = None,
    ) -> WalkForwardResult:
        if date_col not in df.columns:
            raise ValueError(f"Missing date_col={date_col}")
        if code_col not in df.columns:
            raise ValueError(f"Missing code_col={code_col}")
        if price_col not in df.columns:
            raise ValueError(f"Missing price_col={price_col}")

        df = df.sort_values([code_col, date_col]).reset_index(drop=True)

        # 如果传入了 factor_func，先展开列
        if factor_func is not None:
            df_with_factors = factor_func(df.copy())
            # 展开后重新发现 factor_cols（如果未指定）
            if factor_cols is None:
                factor_cols = [
                    c for c in df_with_factors.columns
                    if c not in (date_col, code_col, price_col)
                ]
            if not factor_cols:
                raise ValueError("factor_func produced no new columns")
        else:
            df_with_factors = df
            if factor_cols is None:
                factor_cols = [
                    c for c in df.columns if c not in (date_col, code_col, price_col)
                ]

        # 前视偏差检测：在使用 factor_func 之前检查
        if factor_func is not None:
            try:
                check_lookahead_leakage(df, factor_func, factor_cols)
            except LookaheadBiasError as e:
                logger.error(f"前视偏差检测失败: {e}")
                raise

        if factor_func is not None:
            self.analyzer.compute_ic_ir(
                df_with_factors,
                factor_cols=factor_cols,
                date_col=date_col,
                code_col=code_col,
                price_col=price_col,
                mode=AnalysisMode.BACKTEST,
            )

        windows = self._temporal_split(df, date_col)
        if not windows:
            raise ValueError(f"Data insufficient: need >= {self.train_window + self.test_window} days")

        window_results: List[WalkForwardWindowResult] = []
        final_weights: Dict[str, float] = {}
        oos_ic_values = []
        window_ic_results: List[Dict[str, Dict[int, Any]]] = []

        for ts, te, ss, se in windows:
            train_df = df[(pd.to_datetime(df[date_col]) >= ts) & (pd.to_datetime(df[date_col]) <= te)].copy()
            test_df = df[(pd.to_datetime(df[date_col]) >= ss) & (pd.to_datetime(df[date_col]) <= se)].copy()

            if factor_func is not None:
                train_df = factor_func(train_df.copy())
                test_df = factor_func(test_df.copy())

            if len(train_df) < self.min_train_days:
                raise ValueError(f"Train window too short: {len(train_df)} < {self.min_train_days}")
            if test_df.empty:
                raise ValueError(f"Empty test window: {ss} to {se}")

            ic_results = self.analyzer.compute_ic_ir(
                train_df,
                factor_cols=factor_cols,
                holding_periods=[1, 5, 20],
                date_col=date_col,
                code_col=code_col,
                price_col=price_col,
                mode=AnalysisMode.BACKTEST,
            )
            window_ic_results.append(ic_results)

            for col in factor_cols:
                if col not in ic_results:
                    continue
                col_icir_values = {}
                for period, result in ic_results[col].items():
                    period_key = f"{period}d"
                    ir_val = float(getattr(result, "icir", 0))
                    col_icir_values[period_key] = ir_val
                if col not in self._ic_history:
                    self._ic_history[col] = {}
                for pk, ir_val in col_icir_values.items():
                    if pk not in self._ic_history[col]:
                        self._ic_history[col][pk] = []
                    self._ic_history[col][pk].append(ir_val)

            weights = self._compute_weights(ic_results, factor_cols)
            final_weights = weights

            ic_mean = {col: float(np.mean([r.ic_mean for r in ic_results.get(col, {}).values() if hasattr(r, "ic_mean")])) for col in factor_cols}
            icir = {col: float(np.mean([r.icir for r in ic_results.get(col, {}).values() if hasattr(r, "icir")])) for col in factor_cols}

            scored_df, _ = self.composer.process(
                test_df,
                factor_cols=factor_cols,
                ic_results={col: dict(ic_results.get(col, {})) for col in factor_cols},
                date_col=date_col,
                ic_history=self._ic_history,
                half_life=self.half_life,
            )

            # Evaluate composite score on OOS test data
            oos_ic_res = self.analyzer.compute_ic_ir(
                scored_df,
                factor_cols=["composite_score"],
                holding_periods=[1, 5, 20],
                date_col=date_col,
                code_col=code_col,
                price_col=price_col,
                mode=AnalysisMode.BACKTEST,
            )

            if "composite_score" in oos_ic_res and oos_ic_res["composite_score"]:
                window_oos_ic = float(np.mean([r.ic_mean for r in oos_ic_res["composite_score"].values() if hasattr(r, "ic_mean")]))
                oos_ic_values.append(window_oos_ic)

            train_stocks = train_df[code_col].nunique()
            test_stocks = test_df[code_col].nunique()

            window_results.append(WalkForwardWindowResult(
                train_start=pd.Timestamp(ts), train_end=pd.Timestamp(te),
                test_start=pd.Timestamp(ss), test_end=pd.Timestamp(se),
                ic_mean=ic_mean, icir=icir, weights=weights,
                n_train_stocks=int(train_stocks), n_test_stocks=int(test_stocks),
            ))

        oos_arr = np.array(oos_ic_values)
        oos_ic_mean = float(np.mean(oos_arr)) if len(oos_arr) > 0 else 0.0
        oos_ic_std = float(np.std(oos_arr)) if len(oos_arr) > 1 else 0.0
        oos_icir = oos_ic_mean / oos_ic_std if oos_ic_std > 0 else 0.0

        weight_stability = {}
        for col in factor_cols:
            w_series = [wr.weights.get(col, 0.0) for wr in window_results]
            w_arr = np.array(w_series)
            weight_stability[col] = float(np.std(w_arr)) if len(w_arr) > 1 else 0.0

        ledger_audit = self._register_with_ledger(window_ic_results, df, code_col)

        return WalkForwardResult(
            windows=window_results,
            final_weights=final_weights,
            oos_ic_mean=oos_ic_mean,
            oos_ic_std=oos_ic_std,
            oos_icir=oos_icir,
            weight_stability=weight_stability,
            ledger_audit=ledger_audit,
        )

    def _register_with_ledger(
        self,
        window_ic_results: List[Dict[str, Dict[int, Any]]],
        df: pd.DataFrame,
        code_col: str,
    ) -> Optional[Dict[str, Any]]:
        """把 Walk-Forward 因子试验登记进科研控制平面（自由度账本）。

        为防止单窗尖峰（正是 PBO 过拟合关注点），对每个 ``(因子, 持有期)``
        取**跨窗 t 统计量中位数**作为登记统计量，而非某一幸运窗口的估计。
        未传入 ledger 时为 no-op。
        """
        if self.ledger is None or not window_ic_results:
            return None

        collected: Dict[Tuple[str, int], List[Any]] = {}
        for ic_res in window_ic_results:
            for factor, period_results in (ic_res or {}).items():
                for period, result in (period_results or {}).items():
                    if result is None:
                        continue
                    collected.setdefault((str(factor), int(period)), []).append(result)

        if not collected:
            return None

        merged: Dict[str, Dict[int, Any]] = {}
        for (factor, period), results in collected.items():
            t_values = [float(getattr(r, "ic_t_stat", 0.0) or 0.0) for r in results]
            n_values = [int(getattr(r, "n_periods", 0) or 0) for r in results]
            finite_t = [t for t in t_values if np.isfinite(t)]
            if not finite_t:
                continue
            merged.setdefault(factor, {})[period] = SimpleNamespace(
                ic_t_stat=float(np.median(finite_t)),
                n_periods=int(np.median(n_values)),
            )

        from ...research.ledger.bridge import register_factor_trials

        try:
            audit = register_factor_trials(
                self.ledger,
                merged,
                family_id=self.ledger_family_id,
                cross_section_N=int(df[code_col].nunique()) if code_col in df.columns else 0,
                metadata={
                    "source": "WalkForwardFactorPipeline.run",
                    "n_windows": len(window_ic_results),
                    "aggregation": "median_across_windows",
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("科研控制平面(walk-forward)登记失败（不影响回测）: %s", exc)
            return None

        logger.info(
            "科研控制平面(walk-forward): 登记 %d 项试验 / 平台累计 %d / BH-FDR 显著 %d",
            audit.registered,
            audit.total_platform_trials,
            len(audit.significant_factors),
        )
        return audit.to_dict()
