# -*- coding: utf-8 -*-
"""
LPPL 拟合与优化核心模块 (Fitting & Optimization Module)

职责:
- LPPL 目标代价函数 (RMSE)
- 窗口拟合前置校验与失败统计
- 单窗口拟合求解 (DE 全局差分进化 / L-BFGS-B 局部极小化)
- 模型有效性验证与崩盘预警等级判定
- 日期与窗口扫描算子 (串行 / 并行)
"""

import logging
import os
import warnings
from dataclasses import dataclass
from multiprocessing import current_process
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from joblib import Parallel, delayed
from scipy.optimize import differential_evolution, minimize

from uniquant.brain.lppl.calculator import lppl_func
from uniquant.shared.constants import M_BOUNDS, RANDOM_SEED, W_BOUNDS
from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)

warnings.filterwarnings("once", category=RuntimeWarning, module="numba")
logging.captureWarnings(True)


def _in_parallel() -> bool:
    if os.environ.get("LPPL_DISABLE_PARALLEL") == "1":
        return True
    return current_process().name.startswith("LokyProcess")


# ============================================================================
# 配置类
# ============================================================================


@dataclass
class LPPLConfig:
    """LPPL配置参数"""

    # 窗口配置
    window_range: List[int]

    # 优化器配置 (L-BFGS-B 生产默认; DE 仅用于离线研究, 速度慢 ~50倍)
    optimizer: str = "lbfgsb"
    maxiter: int = 30
    popsize: int = 5        # DE 用: 默认值对 7 维 (min ~70) 不够, 见 de_popsize
    tol: float = 0.05
    de_popsize: int = 70    # DE 模式有效种群数, 仅 optimizer="de" 时使用

    # 风险阈值 (与 constants/technical.py W_BOUNDS/M_BOUNDS 统一)
    m_bounds: Tuple[float, float] = M_BOUNDS
    w_bounds: Tuple[float, float] = W_BOUNDS
    tc_bound: Tuple[float, float] = (1, 100)  # days after current_t

    # 信号阈值
    r2_threshold: float = 0.5
    danger_r2_offset: float = 0.0
    danger_days: int = 5
    warning_days: int = 12
    watch_days: int = 25

    # Ensemble配置
    consensus_threshold: float = 0.5

    # 并行配置
    n_workers: int = -1

    def __post_init__(self):
        self.danger_days = max(1, int(self.danger_days))
        self.warning_days = max(self.danger_days + 1, int(self.warning_days))
        self.watch_days = max(self.warning_days + 1, int(self.watch_days))
        if self.n_workers == -1:
            self.n_workers = max(1, (os.cpu_count() or 4) - 2)


DEFAULT_CONFIG = LPPLConfig(
    window_range=list(range(40, 100, 20)),  # 与verify_lppl.py一致
)

# 全局config引用
_config = DEFAULT_CONFIG


def get_default_config() -> LPPLConfig:
    return _config


# ============================================================================
# 阈值与阶段分类
# ============================================================================


def warning_r2_threshold(config: LPPLConfig) -> float:
    return max(0.0, float(config.r2_threshold) - 0.05)


def watch_r2_threshold(config: LPPLConfig) -> float:
    return max(0.0, float(config.r2_threshold) - 0.15)


def danger_r2_threshold(config: LPPLConfig) -> float:
    return min(1.0, max(0.0, float(config.r2_threshold) + float(config.danger_r2_offset)))


def classify_top_phase(
    days_left: float,
    r2: float,
    config: LPPLConfig,
    price_ret: Optional[float] = None,
    atr_pct: Optional[float] = None,
) -> str:
    if days_left < 0:
        return "none"

    adjusted_r2 = r2
    if atr_pct is not None and atr_pct > 0:
        if atr_pct < 2.0:
            adjusted_r2 = r2 - 0.20
        elif atr_pct < 4.0:
            adjusted_r2 = r2 - 0.10
    elif price_ret is not None and abs(price_ret) < 0.10:
        adjusted_r2 = r2 - 0.15

    if days_left < config.danger_days and adjusted_r2 >= danger_r2_threshold(config):
        return "danger"
    if days_left < config.warning_days and adjusted_r2 >= warning_r2_threshold(config):
        return "warning"
    if days_left < config.watch_days and adjusted_r2 >= watch_r2_threshold(config):
        return "watch"
    return "none"


# ============================================================================
# 辅助函数 (代价函数与前置校验)
# ============================================================================


def cost_function(params: Tuple, t_data: np.ndarray, log_price: np.ndarray) -> float:
    """LPPL cost function (RMSE)"""
    tc, m, w, a, b, c, phi = params
    fitted = lppl_func(t_data, tc, m, w, a, b, c, phi)
    return float(np.sqrt(np.mean((fitted - log_price) ** 2)))


def precheck_fit_input(close_prices: np.ndarray, window_size: int) -> Optional[str]:
    """Validate input before fitting. Returns error message string or None."""
    if close_prices is None or len(close_prices) < window_size:
        return "insufficient_data"
    if window_size < 10:
        return "window_too_small"
    recent = close_prices[-min(5, len(close_prices)) :]
    if np.std(recent) < 1e-8:
        return "no_price_variation"
    return None


def track_fit_failure(reason: str, context: str = "") -> None:
    """Log a fit failure with context."""
    logger.debug(f"LPPL fit skipped: {reason} ({context})")


# ============================================================================
# 拟合函数
# ============================================================================


def fit_single_window(
    close_prices: np.ndarray, window_size: int, config: Optional[LPPLConfig] = None
) -> Optional[Dict[str, Any]]:
    """
    拟合单个窗口 (使用DE优化器，与verify_lppl.py一致)

    Args:
        close_prices: 收盘价数组
        window_size: 窗口大小
        config: 配置参数

    Returns:
        dict 或 None
    """
    if config is None:
        config = get_default_config()

    if close_prices is None or len(close_prices) == 0:
        raise ValueError("close_prices cannot be empty")

    precheck = precheck_fit_input(close_prices, window_size)
    if precheck is not None:
        track_fit_failure(precheck, context=f"window={window_size}")
        return None

    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)

    current_t = float(window_size)

    # 边界参数 (与verify_lppl.py一致)
    log_min = np.min(log_price_data)
    log_max = np.max(log_price_data)

    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),  # tc
        config.m_bounds,  # m
        config.w_bounds,  # w
        (log_min, log_max * 1.1),  # a
        (-20, 20),  # b
        (-20, 20),  # c
        (0, 2 * np.pi),  # phi
    ]

    _DE_WORKERS = int(os.environ.get("UNIQUANT_DE_WORKERS", "-1"))
    de_workers = _DE_WORKERS if _DE_WORKERS != -1 else max(1, (os.cpu_count() or 4) - 1)

    try:
        result = differential_evolution(
            cost_function,
            bounds,
            args=(t_data, log_price_data),
            strategy="best1bin",
            maxiter=config.maxiter,
            popsize=config.popsize,
            tol=config.tol,
            seed=RANDOM_SEED,
            workers=de_workers,
            timeout=120,
        )

        if not result.success:
            return None

        tc, m, w, a, b, c, phi = result.x
        days_to_crash = tc - current_t

        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)

        # 计算R²
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - np.mean(log_price_data)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        rmse = np.sqrt(np.mean((fitted_curve - log_price_data) ** 2))

        price_ret = (price_data[-1] - price_data[0]) / price_data[0] if len(price_data) > 1 else 0

        is_danger = (
            (config.m_bounds[0] < m < config.m_bounds[1])
            and (config.w_bounds[0] < w < config.w_bounds[1])
            and classify_top_phase(days_to_crash, r_squared, config, price_ret) == "danger"
            and r_squared > 0
        )

        return {
            "window_size": window_size,
            "rmse": rmse,
            "r_squared": r_squared,
            "m": m,
            "w": w,
            "tc": tc,
            "days_to_crash": days_to_crash,
            "is_danger": bool(is_danger),
            "params": (tc, m, w, a, b, c, phi),
        }
    except (ValueError, TypeError, FloatingPointError) as e:
        logger.debug(f"fit_single_window DE failed: {e}")
        return None


def fit_single_window_lbfgsb(
    close_prices: np.ndarray, window_size: int, config: Optional[LPPLConfig] = None
) -> Optional[Dict[str, Any]]:
    """
    拟合单个窗口 (使用L-BFGS-B优化器，更快)

    Args:
        close_prices: 收盘价数组
        window_size: 窗口大小
        config: 配置参数

    Returns:
        dict 或 None
    """
    if config is None:
        config = get_default_config()

    precheck = precheck_fit_input(close_prices, window_size)
    if precheck is not None:
        track_fit_failure(precheck, context=f"window={window_size}")
        return None

    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)

    current_t = float(window_size)
    log_mean = np.mean(log_price_data)
    log_range = float(np.ptp(log_price_data))

    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),
        config.m_bounds,
        config.w_bounds,
        (np.min(log_price_data), np.max(log_price_data) * 1.1),
        (-20, 20),
        (-20, 20),
        (0, 2 * np.pi),
    ]

    w_lo, w_hi = config.w_bounds
    w_mid = (w_lo + w_hi) / 2
    initial_guesses = [
        [current_t + 5, 0.5, w_mid, log_mean, log_range * 0.1, log_range * 0.01, 0.0],
        [current_t + 10, 0.4, w_hi * 0.85, log_mean, log_range * 0.05, -log_range * 0.02, np.pi / 2],
        [current_t + 15, 0.6, w_lo * 1.3, log_mean, log_range * 0.08, log_range * 0.005, np.pi],
        [current_t + 8, 0.7, w_mid, log_mean, log_range * 0.06, -log_range * 0.01, np.pi / 4],
        [current_t + 3, 0.3, w_hi * 0.9, log_mean, log_range * 0.12, log_range * 0.02, 0.0],
        [current_t + 20, 0.8, w_lo * 1.2, log_mean, log_range * 0.03, -log_range * 0.005, np.pi],
        [current_t + 12, 0.5, w_mid * 0.8, log_mean, log_range * 0.07, log_range * 0.01, np.pi / 3],
        [current_t + 6, 0.6, w_hi * 0.95, log_mean, log_range * 0.04, -log_range * 0.015, np.pi * 0.75],
        [current_t + 18, 0.4, w_lo * 1.1, log_mean, log_range * 0.09, log_range * 0.008, np.pi * 0.5],
        [current_t + 9, 0.55, w_mid * 1.1, log_mean, log_range * 0.05, -log_range * 0.01, np.pi * 0.25],
    ]

    best_cost = np.inf
    best_params = None

    for x0 in initial_guesses:
        try:
            res = minimize(
                cost_function,
                x0,
                args=(t_data, log_price_data),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 50, "ftol": 1e-6},
            )

            if res.fun < best_cost:
                best_cost = res.fun
                best_params = res.x
        except (ValueError, TypeError, FloatingPointError):
            logger.exception("优化窗口失败，跳过")
            continue

    if best_params is None:
        return None

    try:
        tc, m, w, a, b, c, phi = best_params
        days_to_crash = tc - current_t

        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)

        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - log_mean) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        rmse = best_cost

        price_ret = (price_data[-1] - price_data[0]) / price_data[0] if len(price_data) > 1 else 0

        is_danger = (
            (config.m_bounds[0] < m < config.m_bounds[1])
            and (config.w_bounds[0] < w < config.w_bounds[1])
            and classify_top_phase(days_to_crash, r_squared, config, price_ret) == "danger"
            and r_squared > 0
        )

        return {
            "window_size": window_size,
            "rmse": rmse,
            "r_squared": r_squared,
            "m": m,
            "w": w,
            "tc": tc,
            "days_to_crash": days_to_crash,
            "is_danger": bool(is_danger),
            "params": (tc, m, w, a, b, c, phi),
        }
    except (ValueError, TypeError, FloatingPointError) as e:
        logger.debug(f"fit_single_window_lbfgsb result failed: {e}")
        return None


# ============================================================================
# 风险判定与验证
# ============================================================================


def calculate_risk_level(
    m: float, w: float, days_left: float, r2: float = 1.0, lppl_config: Optional[LPPLConfig] = None
) -> Tuple[str, bool, bool]:
    """
    计算风险等级

    Args:
        m: 模型参数 m
        w: 模型参数 w
        days_left: 距离崩盘的天数
        r2: 拟合 R²
        lppl_config: LPPL 配置（可选），默认使用 DEFAULT_CONFIG

    Returns:
        (risk_level, is_danger, is_warning)
    """
    cfg = lppl_config if lppl_config is not None else get_default_config()
    valid_model = cfg.m_bounds[0] < m < cfg.m_bounds[1] and cfg.w_bounds[0] < w < cfg.w_bounds[1]

    if not valid_model:
        return "无效模型", False, False

    phase = classify_top_phase(days_left, r2, cfg, None)
    is_danger = phase == "danger"
    is_warning = phase in {"warning", "danger"}

    critical_days = max(1, cfg.danger_days // 2)
    if days_left < critical_days:
        return "极高危", is_danger, is_warning
    elif days_left < cfg.danger_days:
        return "高危", is_danger, is_warning
    elif days_left < cfg.watch_days:
        return "观察", is_danger, is_warning
    else:
        return "安全", is_danger, is_warning


def validate_model(params: Dict, config: Optional[LPPLConfig] = None) -> bool:
    """验证模型是否有效"""
    if config is None:
        config = get_default_config()

    m, w = params.get("m", 0), params.get("w", 0)
    r2 = params.get("r_squared", 0)

    return (
        config.m_bounds[0] < m < config.m_bounds[1]
        and config.w_bounds[0] < w < config.w_bounds[1]
        and r2 > config.r2_threshold
    )


# ============================================================================
# 扫描函数
# ============================================================================


def scan_single_date(
    close_prices: np.ndarray, idx: int, window_range: List[int], config: Optional[LPPLConfig] = None
) -> Optional[Dict[str, Any]]:
    """
    扫描单个日期的所有窗口，选择最佳拟合

    Args:
        close_prices: 收盘价数组
        idx: 当前索引
        window_range: 窗口范围列表
        config: 配置参数

    Returns:
        dict 或 None
    """
    if config is None:
        config = get_default_config()

    results = []
    for window_size in window_range:
        if idx < window_size:
            continue

        subset = close_prices[idx - window_size : idx]

        if config.optimizer == "de":
            res = fit_single_window(subset, window_size, config)
        else:
            res = fit_single_window_lbfgsb(subset, window_size, config)

        if res is not None:
            res["idx"] = idx
            results.append(res)

    if not results:
        return None

    # 选择RMSE最低的结果
    best = min(results, key=lambda x: x["rmse"])
    return best


def scan_date_range(
    close_prices: np.ndarray,
    start_idx: int,
    end_idx: int,
    window_range: List[int],
    step: int = 1,
    config: Optional[LPPLConfig] = None,
) -> List[Dict[str, Any]]:
    """
    扫描日期范围内的所有窗口

    Args:
        close_prices: 收盘价数组
        start_idx: 起始索引
        end_idx: 结束索引
        window_range: 窗口范围列表
        step: 步长
        config: 配置参数

    Returns:
        list of dict
    """
    if config is None:
        config = get_default_config()

    indices = list(range(start_idx, end_idx, step))

    if _in_parallel():
        results = [scan_single_date(close_prices, idx, window_range, config) for idx in indices]
    else:
        results = Parallel(n_jobs=config.n_workers, backend="loky", verbose=0)(
            delayed(scan_single_date)(close_prices, idx, window_range, config) for idx in indices
        )

    return [r for r in results if r is not None]


__all__ = [
    "DEFAULT_CONFIG",
    "LPPLConfig",
    "_config",
    "_in_parallel",
    "calculate_risk_level",
    "classify_top_phase",
    "cost_function",
    "danger_r2_threshold",
    "fit_single_window",
    "fit_single_window_lbfgsb",
    "get_default_config",
    "precheck_fit_input",
    "scan_date_range",
    "scan_single_date",
    "track_fit_failure",
    "validate_model",
    "warning_r2_threshold",
    "watch_r2_threshold",
]
