# -*- coding: utf-8 -*-
"""
LPPL 工业级引擎 - 统一核心模块

包含:
- 拟合与优化算子再导出 (从 fitting_optimizer 引入)
- 峰值检测与多尺度分析
- 系综共识度与信号集成
- LPPLEngine 门面类 (窗口扫描、气泡置信度、跨指数结构性风险矩阵)
"""

import logging
import warnings
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from uniquant.brain.lppl.calculator import lppl_func
from uniquant.shared.constants import LPPLConstants, M_BOUNDS, W_BOUNDS
from uniquant.shared.logger_factory import get_logger

from .fitting_optimizer import (
    DEFAULT_CONFIG,
    LPPLConfig,
    _config,
    _in_parallel,
    calculate_risk_level,
    classify_top_phase,
    cost_function,
    danger_r2_threshold,
    fit_single_window,
    fit_single_window_lbfgsb,
    get_default_config,
    precheck_fit_input,
    scan_date_range,
    scan_single_date,
    track_fit_failure,
    validate_model,
    warning_r2_threshold,
    watch_r2_threshold,
)

logger = get_logger(__name__)

try:
    from numba import njit
except ImportError:

    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


warnings.filterwarnings("once", category=RuntimeWarning, module="numba")
logging.captureWarnings(True)


# ============================================================================
# 峰值检测与分析
# ============================================================================


def find_local_highs(
    df: pd.DataFrame, min_gap: int = 60, min_drop_pct: float = 0.05, window: int = 20
) -> List[Dict[str, Any]]:
    """
    查找局部最高点

    Args:
        df: 包含date和close的DataFrame
        min_gap: 两个高点之间的最小间隔天数
        min_drop_pct: 高点后最小跌幅百分比
        window: 检测窗口大小

    Returns:
        list of dict: 高点信息
    """
    highs = []
    close = df["close"].values
    dates = df["date"].values

    rolling_max = pd.Series(close).rolling(window * 2 + 1, center=True).max().values
    is_peak = close == rolling_max
    peak_candidates = np.where(is_peak)[0]

    for i in peak_candidates:
        future_window = min(60, len(close) - i - 1)
        if i < window or i >= len(close) - window or future_window <= 0:
            continue
        future_min = np.min(close[i + 1 : i + 1 + future_window])
        drop_pct = (close[i] - future_min) / close[i]

        if drop_pct >= min_drop_pct:
            too_close = False
            for h in highs:
                if abs(i - h["idx"]) < min_gap:
                    too_close = True
                    break

            if not too_close:
                highs.append(
                    {"idx": i, "date": dates[i], "price": close[i], "drop_pct": drop_pct}
                )

    return highs


def calculate_trend_scores(
    daily_results: List[Dict], ma_window: int = 5, config: Optional[LPPLConfig] = None
) -> pd.DataFrame:
    """
    计算趋势评分

    Args:
        daily_results: 每日最佳拟合结果列表
        ma_window: 移动平均窗口
        config: 配置参数

    Returns:
        DataFrame
    """
    if config is None:
        config = get_default_config()

    if not daily_results:
        return pd.DataFrame()

    df = pd.DataFrame(daily_results)
    df = df.sort_values("idx").reset_index(drop=True)

    # 如果没有is_danger列，根据参数计算 (向量化)
    if "is_danger" not in df.columns:
        m_arr = df["m"].values
        w_arr = df["w"].values
        d_arr = df["days_to_crash"].values
        r_arr = df["r_squared"].values
        df["is_danger"] = (
            (config.m_bounds[0] < m_arr) & (m_arr < config.m_bounds[1]) &
            (config.w_bounds[0] < w_arr) & (w_arr < config.w_bounds[1]) &
            (d_arr < config.danger_days) & (r_arr > config.r2_threshold)
        )

    # 如果没有is_warning列，根据参数计算 (向量化)
    if "is_warning" not in df.columns:
        m_arr = df["m"].values
        w_arr = df["w"].values
        d_arr = df["days_to_crash"].values
        r_arr = df["r_squared"].values
        in_bounds = (
            (config.m_bounds[0] < m_arr) & (m_arr < config.m_bounds[1]) &
            (config.w_bounds[0] < w_arr) & (w_arr < config.w_bounds[1])
        )
        phases = np.array([
            classify_top_phase(float(d), float(r), config, None)
            for d, r in zip(d_arr, r_arr)
        ])
        df["is_warning"] = in_bounds & np.isin(phases, ["watch", "warning", "danger"])

    # R²移动平均
    df["r2_ma"] = df["r_squared"].rolling(window=ma_window, min_periods=1).mean()

    # Danger信号计数
    df["danger_count"] = df["is_danger"].rolling(window=ma_window, min_periods=1).sum()

    # 趋势得分
    df["trend_score"] = df["r2_ma"] * (df["danger_count"] / ma_window)

    return df


def analyze_peak(
    df: pd.DataFrame,
    peak_idx: int,
    window_range: List[int],
    scan_step: int = 2,
    ma_window: int = 5,
    config: Optional[LPPLConfig] = None,
) -> Optional[Dict[str, Any]]:
    """
    分析单个高点前后的LPPL信号

    Args:
        df: DataFrame with date and close
        peak_idx: 高点索引
        window_range: LPPL窗口范围
        scan_step: 扫描步长
        ma_window: 移动平均窗口
        config: 配置参数

    Returns:
        dict: 分析结果
    """
    if config is None:
        config = get_default_config()

    close_prices = df["close"].values

    # 扫描范围: 高点前120天到高点
    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx

    if start_idx >= end_idx:
        return None

    indices = list(range(start_idx, end_idx + 1, scan_step))

    results = Parallel(n_jobs=config.n_workers, backend="loky", verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range, config) for idx in indices
    )
    results = [r for r in results if r is not None]

    if len(results) == 0:
        return None

    # 添加日期和价格
    for r in results:
        r["date"] = df.iloc[r["idx"]]["date"]
        r["price"] = df.iloc[r["idx"]]["close"]
        r["days_to_peak"] = r["idx"] - peak_idx

    # 计算趋势得分
    trend_df = calculate_trend_scores(results, ma_window, config)

    # 分析危险信号
    danger_signals = trend_df[trend_df["is_danger"]]
    danger_before_peak = danger_signals[danger_signals["days_to_peak"] <= 0]

    first_danger = (
        danger_before_peak.sort_values("date").iloc[0] if len(danger_before_peak) > 0 else None
    )

    # 最高趋势得分
    before_peak = trend_df[trend_df["days_to_peak"] <= 0]
    if len(before_peak) > 0 and len(before_peak[before_peak["trend_score"] > 0]) > 0:
        best_trend = before_peak.loc[before_peak["trend_score"].idxmax()]
    else:
        best_trend = None

    peak_date = df.iloc[peak_idx]["date"]
    peak_price = df.iloc[peak_idx]["close"]

    return {
        "peak_idx": peak_idx,
        "peak_date": peak_date if isinstance(peak_date, str) else peak_date.strftime("%Y-%m-%d"),
        "peak_price": peak_price,
        "total_scans": len(results),
        "danger_count": len(danger_signals),
        "danger_before_peak": len(danger_before_peak),
        "first_danger_days": first_danger["days_to_peak"] if first_danger is not None else None,
        "first_danger_r2": first_danger["r_squared"] if first_danger is not None else None,
        "first_danger_m": first_danger["m"] if first_danger is not None else None,
        "first_danger_w": first_danger["w"] if first_danger is not None else None,
        "best_trend_days": best_trend["days_to_peak"] if best_trend is not None else None,
        "best_trend_score": best_trend["trend_score"] if best_trend is not None else None,
        "best_trend_r2": best_trend["r_squared"] if best_trend is not None else None,
        "detected": len(danger_before_peak) > 0,
        "mode": "single_window",
        "timeline": trend_df.to_dict("records"),
    }


def analyze_peak_ensemble(
    df: pd.DataFrame,
    peak_idx: int,
    window_range: List[int],
    scan_step: int = 2,
    ma_window: int = 5,
    config: Optional[LPPLConfig] = None,
) -> Optional[Dict[str, Any]]:
    """
    分析单个高点前后的 Ensemble 信号

    Returns:
        dict: 与 analyze_peak 兼容的 summary 字段，并额外包含 timeline
    """
    if config is None:
        config = get_default_config()

    close_prices = df["close"].values

    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx

    if start_idx >= end_idx:
        return None

    indices = list(range(start_idx, end_idx + 1, scan_step))

    if config.n_workers == 1:
        results = [
            process_single_day_ensemble(
                close_prices,
                idx,
                window_range,
                min_r2=config.r2_threshold,
                consensus_threshold=config.consensus_threshold,
                config=config,
            )
            for idx in indices
        ]
    else:
        results = Parallel(n_jobs=config.n_workers, backend="loky", verbose=0)(
            delayed(process_single_day_ensemble)(
                close_prices,
                idx,
                window_range,
                config.r2_threshold,
                config.consensus_threshold,
                config,
            )
            for idx in indices
        )

    results = [r for r in results if r is not None]

    if not results:
        return None

    for r in results:
        r["date"] = df.iloc[r["idx"]]["date"]
        r["price"] = df.iloc[r["idx"]]["close"]
        r["days_to_peak"] = r["idx"] - peak_idx
        r["is_danger"] = bool(r["predicted_crash_days"] < config.danger_days)
        r["is_warning"] = bool(r["predicted_crash_days"] < config.warning_days)
        r["trend_score"] = r["signal_strength"]

    trend_df = pd.DataFrame(results).sort_values("idx").reset_index(drop=True)
    before_peak = trend_df[trend_df["days_to_peak"] <= 0]
    danger_before_peak = before_peak[before_peak["is_danger"]]

    first_danger = (
        danger_before_peak.sort_values("date").iloc[0] if len(danger_before_peak) > 0 else None
    )
    best_trend = (
        before_peak.loc[before_peak["signal_strength"].idxmax()] if len(before_peak) > 0 else None
    )

    peak_date = df.iloc[peak_idx]["date"]
    peak_price = df.iloc[peak_idx]["close"]

    return {
        "peak_idx": peak_idx,
        "peak_date": peak_date if isinstance(peak_date, str) else peak_date.strftime("%Y-%m-%d"),
        "peak_price": peak_price,
        "total_scans": len(results),
        "danger_count": int(trend_df["is_danger"].sum()),
        "danger_before_peak": len(danger_before_peak),
        "first_danger_days": first_danger["days_to_peak"] if first_danger is not None else None,
        "first_danger_r2": first_danger["avg_r2"] if first_danger is not None else None,
        "first_danger_m": None,
        "first_danger_w": None,
        "best_trend_days": best_trend["days_to_peak"] if best_trend is not None else None,
        "best_trend_score": best_trend["signal_strength"] if best_trend is not None else None,
        "best_trend_r2": best_trend["avg_r2"] if best_trend is not None else None,
        "detected": len(danger_before_peak) > 0,
        "mode": "ensemble",
        "timeline": trend_df.to_dict("records"),
    }


# ============================================================================
# Ensemble集成
# ============================================================================


def _is_valid_bubble(m, w, b, c):
    if any(v is None for v in (m, w, b, c)):
        return False
    return (
        M_BOUNDS[0] < m < M_BOUNDS[1]
        and W_BOUNDS[0] < w < W_BOUNDS[1]
        and b < 0
        and abs(c) > 0.01
    )


def process_single_day_ensemble(
    close_prices: np.ndarray,
    idx: int,
    window_range: List[int],
    min_r2: Optional[float] = None,
    consensus_threshold: Optional[float] = None,
    config: Optional[LPPLConfig] = None,
) -> Optional[Dict[str, Any]]:
    """
    处理特定交易日，执行系综集成

    Args:
        close_prices: 收盘价数组
        idx: 当前索引
        window_range: 窗口范围
        min_r2: 最小R²阈值
        consensus_threshold: 共识度阈值
        config: 配置参数

    Returns:
        dict 或 None
    """
    if config is None:
        config = get_default_config()
    if min_r2 is None:
        min_r2 = config.r2_threshold
    if consensus_threshold is None:
        consensus_threshold = config.consensus_threshold

    valid_fits = []
    total_windows = len(window_range)

    # 1. 扫描当天所有窗口
    for w_size in window_range:
        if idx < w_size:
            continue

        subset = close_prices[idx - w_size : idx]

        if config.optimizer == "lbfgsb":
            res = fit_single_window_lbfgsb(subset, w_size, config)
        else:
            res = fit_single_window(subset, w_size, config)

        # 2. 硬过滤
        if res is not None and res["r_squared"] > min_r2:
            if (
                config.m_bounds[0] < res["m"] < config.m_bounds[1]
                and config.w_bounds[0] < res["w"] < config.w_bounds[1]
            ):
                valid_fits.append(res)

    valid_n = len(valid_fits)
    consensus_rate = valid_n / total_windows if total_windows > 0 else 0

    # 3. 共识度验证
    if consensus_rate < consensus_threshold:
        return None

    # 4. 崩溃时间聚类分析
    tc_array = np.array([fit["days_to_crash"] for fit in valid_fits])
    tc_std = np.std(tc_array)

    positive_fits = []
    negative_fits = []
    for fit in valid_fits:
        p = fit.get("params", (None, None, None, None, None, None, None))
        if len(p) >= 6 and _is_valid_bubble(fit.get("m", 0), fit.get("w", 0), p[4], p[5]):
            positive_fits.append(fit)
        else:
            negative_fits.append(fit)

    # consensus_rate = valid_n / total_windows（有效拟合占总窗口比例）
    # 方向共识以有效拟合为分母，避免被无效窗口稀释
    positive_consensus_rate = len(positive_fits) / valid_n if valid_n > 0 else 0.0
    negative_consensus_rate = len(negative_fits) / valid_n if valid_n > 0 else 0.0
    predicted_rebound_days = (
        np.median([fit["days_to_crash"] for fit in negative_fits]) if negative_fits else None
    )

    # 5. 信号强度计算
    signal_strength = consensus_rate * (1.0 / (tc_std + 1.0))

    return {
        "idx": idx,
        "consensus_rate": consensus_rate,
        "valid_windows": valid_n,
        "predicted_crash_days": np.median(tc_array),
        "tc_std": tc_std,
        "signal_strength": signal_strength,
        "avg_r2": np.mean([fit["r_squared"] for fit in valid_fits]),
        "positive_consensus_rate": positive_consensus_rate,
        "negative_consensus_rate": negative_consensus_rate,
        "predicted_rebound_days": predicted_rebound_days,
    }


LPPL_ENGINE_RECOVERABLE_ERRORS = (
    AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError,
)


class LPPLEngine:
    def __init__(self):
        from ...brain.lppl.calculator import LPPLCalculator as Calc
        self.calculator = Calc()

    def scan_all_windows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        valid_windows = [w for w in LPPLConstants.WINDOWS_ALL if len(df) >= w]
        if not valid_windows:
            return []
        if _in_parallel():
            raw = [self._process_window(df, w) for w in valid_windows]
        else:
            raw = Parallel(n_jobs=-1, backend="loky")(
                delayed(self._process_window)(df, w) for w in valid_windows
            )
        results = [r for r in raw if r is not None]
        buckets = {
            "Short (100-300d)": lambda w: w <= 300,
            "Medium (300-600d)": lambda w: 300 < w <= 600,
            "Long (>600d)": lambda w: w > 600,
        }
        selected = []
        for name, condition in buckets.items():
            candidates = [r for r in results if condition(r["window"])]
            if not candidates:
                continue
            best = min(candidates, key=lambda r: r["rmse"])
            best["span"] = name
            selected.append(best)
        return selected

    @staticmethod
    def _process_window(df, window):
        try:
            subset = df["close"].iloc[-window:].values
            config = LPPLConfig(window_range=[window])
            res = fit_single_window_lbfgsb(subset, window, config)
            if res and res.get("rmse", float("inf")) < LPPLConstants.RMSE_REJECT_THRESHOLD:
                res["window"] = window
                return res
        except LPPL_ENGINE_RECOVERABLE_ERRORS:
            logger.exception("单窗口 LPPL 拟合失败")
            pass
        return None

    def detect_bubble(self, df: pd.DataFrame, column: str = "close") -> Dict[str, Any]:
        # calculator.fit() 路径 (L-BFGS-B 主优化, DE 降级, 3-param variable projection)
        # 与 scan_all_windows() (7-param 全量 L-BFGS-B) 构成双路径 API
        # ⚠ R² 口径不同: 本方法使用 3-param variable projection (线性参数解析最优),
        #   scan_all_windows 使用 7-param 全局优化 (线性与非线性同时求解),
        #   两者 R² 绝对值不可直接比较
        result = self.calculator.fit(df, column)
        if result:
            result["out_of_sample_r_squared"] = self._calc_oos_r_squared(df, result, column)
        return result

    @staticmethod
    def _calc_oos_r_squared(df: pd.DataFrame, result: Dict[str, Any], column: str = "close") -> float:
        prices = df[column].to_numpy()
        n = len(prices)
        if n < 60 or "model_params" not in result:
            return 0.0
        params = result.get("model_params", {})
        if not params:
            return 0.0
        tc = result.get("tc", n + 30)
        m = params.get("m", 0.5)
        w_val = params.get("w", 10)
        log_ret = np.log(prices)
        t = np.arange(n)
        split = n - 30
        t_train = t[:split]
        log_train = log_ret[:split]
        tau_train = np.maximum(tc - t_train, 1e-8)
        f = tau_train ** m
        g = f * np.cos(w_val * np.log(tau_train))
        h = f * np.sin(w_val * np.log(tau_train))
        X = np.column_stack([np.ones_like(t_train), f, g, h])
        beta, _, _, _ = np.linalg.lstsq(X, log_train, rcond=None)
        a, b1, c1, c2 = beta
        t_hold = t[split:]
        log_hold = log_ret[split:]
        tau_hold = np.maximum(tc - t_hold, 1e-8)
        f_hold = tau_hold ** m
        g_hold = f_hold * np.cos(w_val * np.log(tau_hold))
        h_hold = f_hold * np.sin(w_val * np.log(tau_hold))
        fitted_hold = a + b1 * f_hold + c1 * g_hold + c2 * h_hold
        ss_res = float(np.sum((log_hold - fitted_hold) ** 2))
        ss_tot = float(np.sum((log_hold - np.mean(log_hold)) ** 2))
        return round(1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0, 4)

    def detect_bubble_confidence(self, df: pd.DataFrame, column: str = "close") -> Dict[str, Any]:
        windows = LPPLConstants.WINDOWS_LIST
        bubble_votes = 0
        details = []
        for w in windows:
            if len(df) < w:
                continue
            subset = df.iloc[-w:].copy()
            try:
                res = self.calculator.fit(subset, column)
                if res.get("is_bubble") and res.get("risk_level") == "Danger":
                    bubble_votes += 1
                details.append(res)
            except LPPL_ENGINE_RECOVERABLE_ERRORS:
                logger.exception("气泡检测窗口失败，跳过")
                continue
        confidence = bubble_votes / len(windows) if windows else 0.0
        risk_level = "Danger" if confidence >= LPPLConstants.CONFIDENCE_THRESHOLD else (
            "Warning" if confidence > LPPLConstants.CONFIDENCE_WARNING else "Safe"
        )
        return {"risk_level": risk_level, "confidence": confidence, "votes": bubble_votes, "details": details}

    def calculate_tc_days(self, df: pd.DataFrame, column: str = "close") -> float:
        result = self.detect_bubble(df, column)
        return max(0, result.get("days_to_tc", 45.0)) if "days_to_tc" in result else 45.0

    def calc_structural_risk_matrix(self, indices_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        risk_matrix = {}
        for symbol, df in indices_data.items():
            if df.empty:
                risk_matrix[symbol] = {"tc": None, "status": "Safe", "confidence": 0.0, "is_bubble": False}
                continue
            try:
                result = self.detect_bubble(df, "close")
                risk_matrix[symbol] = {
                    "tc": result.get("tc"), "tc_days": max(0, result.get("days_to_tc", 45.0)),
                    "status": result.get("risk_level", "Safe"), "confidence": result.get("confidence", 0.0),
                    "is_bubble": result.get("is_bubble", False),
                }
            except LPPL_ENGINE_RECOVERABLE_ERRORS:
                risk_matrix[symbol] = {"tc": None, "status": "Safe", "confidence": 0.0, "is_bubble": False}
        danger_count = sum(1 for r in risk_matrix.values() if r.get("status") == "Danger")
        return {
            "risk_matrix": risk_matrix,
            "overall_risk": "Danger" if danger_count > 0 else "Warning" if sum(
                1 for r in risk_matrix.values() if r.get("status") == "Warning"
            ) > 0 else "Safe",
            "indices_analyzed": len(indices_data),
            "danger_count": danger_count,
        }


__all__ = [
    "DEFAULT_CONFIG",
    "LPPLConfig",
    "LPPLEngine",
    "LPPL_ENGINE_RECOVERABLE_ERRORS",
    "_config",
    "_in_parallel",
    "_is_valid_bubble",
    "analyze_peak",
    "analyze_peak_ensemble",
    "calculate_risk_level",
    "calculate_trend_scores",
    "classify_top_phase",
    "cost_function",
    "danger_r2_threshold",
    "find_local_highs",
    "fit_single_window",
    "fit_single_window_lbfgsb",
    "get_default_config",
    "lppl_func",
    "precheck_fit_input",
    "process_single_day_ensemble",
    "scan_date_range",
    "scan_single_date",
    "track_fit_failure",
    "validate_model",
    "warning_r2_threshold",
    "watch_r2_threshold",
]
