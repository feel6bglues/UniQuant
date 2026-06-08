# -*- coding: utf-8 -*-
from __future__ import annotations

"""
LPPL 底层数值核心

职责：提供 LPPL 模型函数、代价函数、单窗口拟合、输入校验等基础运算。
被 src.lppl_engine 策略层调用，不包含策略级逻辑（扫描、集成、风险解释）。

关系：
- src.lppl_engine 是本模块的调用方（策略级入口）
"""

from typing import Dict, Literal, Optional, Tuple

import pandas as pd

from uniquant.shared.constants import ENABLE_NUMBA_JIT, REQUIRED_COLUMNS, W_BOUNDS, M_BOUNDS
from uniquant.shared.logger_factory import get_logger

LPPL_RMSE_THRESHOLD = 10.0

FitFailureReason = Literal[
    "insufficient_data",
    "non_positive_price",
    "nan_or_inf",
    "constant_price",
    "optimizer_failed",
    "numeric_error",
]

FitFailureStats = Dict[FitFailureReason, int]


def track_fit_failure(
    reason: FitFailureReason, stats: Optional[FitFailureStats] = None, context: str = ""
) -> None:
    if stats is not None:
        stats[reason] = stats.get(reason, 0) + 1
    logger.debug(f"LPPL fit failure [{reason}]{' - ' + context if context else ''}")


import numpy as np

logger = get_logger(__name__)

NUMBA_AVAILABLE = False
try:
    from numba import njit

    NUMBA_AVAILABLE = True
    logger.info("Numba JIT compilation available")
except ImportError:
    NUMBA_AVAILABLE = False
    logger.warning("Numba not available, using pure Python implementation")


def precheck_fit_input(close_prices: np.ndarray, window_size: int) -> Optional[FitFailureReason]:
    if len(close_prices) < window_size:
        return "insufficient_data"
    subset = close_prices[-window_size:]
    if np.any(subset <= 0):
        return "non_positive_price"
    if np.any(~np.isfinite(subset)):
        return "nan_or_inf"
    if np.ptp(subset) < 1e-10:
        return "constant_price"
    return None


from uniquant.brain.lppl.calculator import lppl_func


def cost_function(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:

    if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT:
        return _cost_function_numba(params, t, log_prices)
    return _cost_function_python(params, t, log_prices)


def _cost_function_python(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    tc, m, w, a, b, c, phi = params
    try:
        prediction = lppl_func(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sqrt(np.mean(residuals**2))
    except (FloatingPointError, OverflowError, ValueError) as e:
        logger.warning("cost_function numerical error: %s", e)
        return 1e10


if NUMBA_AVAILABLE:

    @njit(cache=True, fastmath=True)
    def _lppl_func_numba(
        t: np.ndarray, tc: float, m: float, w: float, a: float, b: float, c: float, phi: float
    ) -> np.ndarray:
        tau = tc - t
        n = len(tau)
        result = np.empty(n)
        for i in range(n):
            if tau[i] < 1e-8:
                tau_i = 1e-8
            else:
                tau_i = tau[i]
            result[i] = a + b * (tau_i**m) + c * (tau_i**m) * np.cos(w * np.log(tau_i) + phi)
        return result

    @njit(cache=True, fastmath=True)
    def _cost_function_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
        tc = params[0]
        m = params[1]
        w = params[2]
        a = params[3]
        b = params[4]
        c = params[5]
        phi = params[6]

        prediction = _lppl_func_numba(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sqrt(np.mean(residuals**2))

    @njit(cache=True, fastmath=True)
    def _fused_cost_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
        tc = params[0]; m = params[1]; w = params[2]
        a  = params[3]; b = params[4]; c = params[5]; phi = params[6]
        sse = 0.0
        n = len(t)
        for i in range(n):
            tau_i = tc - t[i]
            if tau_i < 1e-8:
                tau_i = 1e-8
            tau_m = tau_i ** m
            log_tau = np.log(tau_i)
            pred = a + b * tau_m + c * tau_m * np.cos(w * log_tau + phi)
            diff = pred - log_prices[i]
            sse += diff * diff
        return np.sqrt(sse / n)


def validate_input_data(df: pd.DataFrame, symbol: str) -> Tuple[bool, str]:
    if df is None or df.empty:
        return False, "DataFrame is None or empty"

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"Missing required columns: {missing_cols}"

    if len(df) < 50:
        return False, f"Insufficient data rows: {len(df)} < 50"

    if df["close"].isnull().any():
        return False, "Null values found in close column"

    if (df["close"] <= 0).any():
        return False, "Non-positive prices found in close column"

    return True, ""





def detect_negative_bubble(m: float, w: float, b: float, days_left: float) -> Tuple[bool, str]:
    is_negative = False
    signal = "无抄底信号"

    if M_BOUNDS[0] < m < M_BOUNDS[1] and W_BOUNDS[0] < w < W_BOUNDS[1]:
        if b > 0:
            is_negative = True
            if days_left < 20:
                signal = "强抄底信号 (Strong Buy)"
            elif days_left < 40:
                signal = "中等抄底信号 (Buy)"
            else:
                signal = "弱抄底信号 (Watch for Buy)"

    return is_negative, signal


def calculate_bottom_signal_strength(m: float, w: float, b: float, rmse: float) -> float:
    strength = 0.0

    if not (M_BOUNDS[0] < m < M_BOUNDS[1] and W_BOUNDS[0] < w < W_BOUNDS[1]):
        return 0.0

    if b <= 0:
        return 0.0

    m_score = 1.0 - abs(m - 0.5) / 0.4

    w_score = 1.0 - abs(w - 8.0) / 5.0

    b_score = min(b / 1.0, 1.0)

    rmse_score = max(0.0, 1.0 - rmse / 0.1)

    strength = m_score * 0.3 + w_score * 0.3 + b_score * 0.2 + rmse_score * 0.2

    return min(max(strength, 0.0), 1.0)
