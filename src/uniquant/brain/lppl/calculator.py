import hashlib
import logging
from collections import OrderedDict
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution

from ...shared.config_loader import config
from ...shared.constants import LPPLConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError, LPPLFitError
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class LPPLCalculator:
    """
    LPPL计算器
    负责核心的LPPL计算逻辑
    """

    def __init__(self):
        """
        初始化LPPL计算器
        """
        # 加载配置
        self._load_config()

        # 添加缓存 - 使用 OrderedDict LRU 缓存，避免内存泄漏
        self._fit_cache: OrderedDict = OrderedDict()
        self._max_cache_size = 2000

    def _load_config(self):
        """从配置文件加载LPPL参数"""
        try:
            # 优化器配置
            self.maxiter = config.get("lppl.optimizer.max_iter", 500)
            self.popsize = config.get("lppl.optimizer.popsize", 10)
            self.tol = config.get("lppl.optimizer.tolerance", 0.01)
            self.mutation = (
                config.get("lppl.optimizer.mutation_min", 0.5),
                config.get("lppl.optimizer.mutation_max", 1.0),
            )
            self.recombination = config.get("lppl.optimizer.recombination", 0.7)
            self.seed = config.get("lppl.optimizer.seed", 42)
            self.workers = config.get("lppl.optimizer.workers", LPPLConstants.WORKERS)

            # 数据配置
            self.min_data_points = config.get("lppl.data.min_data_points", 60)
            self.tc_search_range = config.get("lppl.data.tc_search_range", 50)
            self.tc_future_range = config.get("lppl.data.tc_future_range", 100)

            # 参数边界配置
            self.tc_backward = config.get("lppl.bounds.tc_backward", 50)
            self.tc_forward = config.get("lppl.bounds.tc_forward", 100)
            self.a_multiplier = config.get("lppl.bounds.a_multiplier", 1.1)
            self.b_min = config.get("lppl.bounds.b_min", -20)
            self.b_max = config.get("lppl.bounds.b_max", 20)
            self.c_min = config.get("lppl.bounds.c_min", -20)
            self.c_max = config.get("lppl.bounds.c_max", 20)
            self.phi_max = config.get("lppl.bounds.phi_max", 2 * np.pi)

            # Sornette约束配置
            self.m_min = config.get("lppl.constraints.m_range", [0.1, 0.9])[0]
            self.m_max = config.get("lppl.constraints.m_range", [0.1, 0.9])[1]
            self.w_min = config.get("lppl.constraints.w_range", [6, 13])[0]
            self.w_max = config.get("lppl.constraints.w_range", [6, 13])[1]
            self.c_min_abs = config.get("lppl.constraints.c_min_abs", 0.01)
            self.c_abs_for_bubble = config.get("lppl.constraints.c_abs_for_bubble", 0.1)

            # 置信度计算配置
            self.tc_weight = config.get("lppl.confidence.tc_weight", 0.4)
            self.cost_weight = config.get("lppl.confidence.cost_weight", 0.4)
            self.data_weight = config.get("lppl.confidence.data_weight", 0.2)
            self.data_reference = config.get("lppl.confidence.data_reference", 200)
            self.cost_scale = config.get("lppl.confidence.cost_scale", 0.1)

            # 风险等级阈值
            self.danger_days = config.get("lppl.risk_levels.danger_days", 10)
            self.warning_days = config.get("lppl.risk_levels.warning_days", 20)

            # 泡沫判断阈值
            self.confidence_threshold = config.get(
                "lppl.bubble.confidence_threshold", 0.6
            )

            # 性能配置
            self.cache_enabled = config.get("lppl.performance.cache_enabled", True)
            self.cache_precision = config.get("lppl.performance.cache_precision", 4)

            logger.debug("LPPL配置加载完成")
        except Exception as e:
            logger.error(f"加载LPPL配置时发生错误: {e}")
            # 使用默认值
            logger.info("使用默认LPPL配置")

            # 优化器配置
            self.maxiter = LPPLConstants.MAX_ITER
            self.popsize = LPPLConstants.POP_SIZE
            self.tol = LPPLConstants.TOLERANCE
            self.mutation = (LPPLConstants.MUTATION_MIN, LPPLConstants.MUTATION_MAX)
            self.recombination = LPPLConstants.RECOMBINATION
            self.seed = LPPLConstants.SEED
            self.workers = LPPLConstants.WORKERS

            # 数据配置
            self.min_data_points = LPPLConstants.MIN_DATA_POINTS
            self.tc_search_range = LPPLConstants.TC_SEARCH_RANGE
            self.tc_future_range = LPPLConstants.TC_FUTURE_RANGE

            # 参数边界配置
            self.tc_backward = LPPLConstants.TC_BACKWARD
            self.tc_forward = LPPLConstants.TC_FORWARD
            self.a_multiplier = LPPLConstants.A_MULTIPLIER
            self.b_min = LPPLConstants.B_MIN
            self.b_max = LPPLConstants.B_MAX
            self.c_min = LPPLConstants.C_MIN
            self.c_max = LPPLConstants.C_MAX
            self.phi_max = LPPLConstants.PHI_MAX

            # Sornette约束配置
            self.m_min = LPPLConstants.M_MIN
            self.m_max = LPPLConstants.M_MAX
            self.w_min = LPPLConstants.W_MIN
            self.w_max = LPPLConstants.W_MAX
            self.c_min_abs = LPPLConstants.C_MIN_ABS
            self.c_abs_for_bubble = LPPLConstants.C_ABS_FOR_BUBBLE

            # 置信度计算配置
            self.tc_weight = LPPLConstants.TC_WEIGHT
            self.cost_weight = LPPLConstants.COST_WEIGHT
            self.data_weight = LPPLConstants.DATA_WEIGHT
            self.data_reference = LPPLConstants.DATA_REFERENCE
            self.cost_scale = LPPLConstants.COST_SCALE

            # 风险等级阈值
            self.danger_days = LPPLConstants.DANGER_DAYS
            self.warning_days = LPPLConstants.WARNING_DAYS

            # 泡沫判断阈值
            self.confidence_threshold = LPPLConstants.CONFIDENCE_THRESHOLD

            # 性能配置
            self.cache_enabled = LPPLConstants.CACHE_ENABLED
            self.cache_precision = LPPLConstants.CACHE_PRECISION

    def _get_cached(self, key: str):
        if key in self._fit_cache:
            self._fit_cache.move_to_end(key)
            return self._fit_cache[key]
        return None

    def _set_cached(self, key: str, value):
        self._fit_cache[key] = value
        while len(self._fit_cache) > self._max_cache_size:
            self._fit_cache.popitem(last=False)

    def _get_rmse_threshold(self, prices) -> float:
        try:
            if getattr(LPPLConstants, 'USE_DYNAMIC_RMSE', False):
                avg_price = prices.mean()
                return max(0.05, float(avg_price) / 100 * 0.02)
        except AttributeError:
            pass
        return LPPLConstants.RMSE_REJECT_THRESHOLD

    def lppl_func(self, t, tc, m, w, a, b, c, phi):
        """
        LPPL函数实现

        Args:
            t: 时间序列
            tc: 临界点时间
            m: 缩放指数
            w: 角频率
            a: 常数项
            b: 线性项系数
            c: 周期性项系数
            phi: 相位角

        Returns:
            LPPL模型值（tau <= 0 时返回 NaN）
        """
        tau = tc - t  # 不使用 abs，保持数学正确性
        result = np.full_like(t, np.nan, dtype=np.float64)
        valid = tau > 0
        if np.any(valid):
            tau_v = tau[valid]
            result[valid] = (
                a
                + b * (tau_v**m)
                + c * (tau_v**m) * np.cos(w * np.log(tau_v) + phi)
            )
        return result

    def cost_function(self, params, t, log_prices):
        """
        成本函数，用于优化

        Args:
            params: 模型参数 [tc, m, w, a, b, c, phi]
            t: 时间序列
            log_prices: 对数价格序列

        Returns:
            均方误差
        """
        tc, m, w, a, b, c, phi = params
        prediction = self.lppl_func(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sum(residuals**2)

    def cost_function_reduced(self, nonlinear_params, t, log_prices):
        """
        降维后的成本函数，使用变量投影法

        Args:
            nonlinear_params: 非线性参数 [tc, m, w]
            t: 时间序列
            log_prices: 对数价格序列

        Returns:
            均方误差
        """
        tc, m, w = nonlinear_params

        # 硬约束，防止 tc 过于接近数据末端
        current_t = t[-1]
        if tc <= current_t + 0.5:  # 强制 tc 至少在最后一天之后 0.5 天
            return 1e20  # 返回一个巨大的惩罚值

        tau = tc - t  # 不使用 abs
        if np.any(tau <= 0):
            return 1e20

        # 构建设计矩阵 X
        f = tau**m
        g = f * np.cos(w * np.log(tau))
        h = f * np.sin(w * np.log(tau))
        X = np.column_stack([np.ones_like(t), f, g, h])

        # 直接求解线性参数 (A, B, C1, C2)
        _, residuals, _, _ = np.linalg.lstsq(X, log_prices, rcond=None)

        return np.sum(residuals**2)

    @handle_errors(
        LPPLFitError, AnalysisError, default_return=None, log_level=logging.ERROR
    )
    def fit_single_window(self, close_prices: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        对单一时间窗口进行模型拟合（带缓存）

        Args:
            close_prices: 收盘价序列

        Returns:
            拟合结果或None
        """
        # 创建缓存键 - 使用 hashlib 确保跨进程稳定
        cache_key = hashlib.sha256(close_prices.tobytes()).hexdigest()[:16]

        # 检查缓存（进程本地，无需锁）
        if self.cache_enabled:
            cached = self._get_cached(cache_key)
            if cached is not None:
                logger.debug("  Using cached fit result")
                return cached

        t = np.arange(len(close_prices))

        if np.any(close_prices <= 0) or np.any(np.isnan(close_prices)):
            logger.warning("Price data contains invalid values (<=0 or NaN)")
            return None

        log_price = np.log(close_prices)
        current_t = len(close_prices)

        # 参数边界 - 只包含非线性参数 [tc, m, w]
        bounds = [
            (max(0, current_t - self.tc_backward), current_t + self.tc_forward),  # tc
            (self.m_min, self.m_max),  # m
            (self.w_min, self.w_max),  # w
        ]

        # 差分进化算法 - 使用配置
        result = differential_evolution(
            self.cost_function_reduced,
            bounds,
            args=(t, log_price),
            strategy="best1bin",
            maxiter=self.maxiter,
            popsize=self.popsize,
            tol=self.tol,
            mutation=self.mutation,
            recombination=self.recombination,
            seed=self.seed,
            workers=self.workers,
        )

        if not result.success:
            return None

        # 计算线性参数
        tc, m, w = result.x
        tau = tc - t  # 不使用 abs
        if np.any(tau <= 0):
            logger.warning("Optimization produced invalid tc (tau <= 0)")
            return None

        # 构建设计矩阵 X
        f = tau**m
        g = f * np.cos(w * np.log(tau))
        h = f * np.sin(w * np.log(tau))
        X = np.column_stack([np.ones_like(t), f, g, h])

        # 求解线性参数
        beta, residuals, _, _ = np.linalg.lstsq(X, log_price, rcond=None)
        a, b, c1, c2 = beta

        # 计算c和phi
        c = np.sqrt(c1**2 + c2**2)
        phi = np.arctan2(-c2, c1)

        # 完整参数
        params = [tc, m, w, a, b, c, phi]

        # 计算指标 - 直接使用residuals，省去一次lppl_func计算
        rmse = np.sqrt(np.mean(residuals))

        # 缓存结果（进程本地，无需锁）
        fit_result = {"params": params, "rmse": rmse, "t_len": current_t}
        if self.cache_enabled:
            self._set_cached(cache_key, fit_result)

        return fit_result

    def _apply_sornette_constraints(self, m, w, b, c) -> bool:
        """
        应用Sornette约束条件

        Args:
            m: 缩放指数
            w: 角频率
            b: 线性项系数
            c: 周期性项系数

        Returns:
            是否满足约束
        """
        # 使用配置的约束条件
        if not (self.m_min < m < self.m_max):
            return False
        if not (self.w_min < w < self.w_max):
            return False
        if b >= 0:
            return False
        if abs(c) < self.c_min_abs:
            return False
        return True

    def _calculate_confidence(
        self, days_to_tc: float, cost_value: float, data_length: int
    ) -> float:
        """
        计算置信度

        Args:
            days_to_tc: 到临界点的天数
            cost_value: 成本函数值
            data_length: 数据长度

        Returns:
            置信度分数
        """
        # 基于到tc的天数的置信度
        if days_to_tc < self.danger_days:
            tc_confidence = 0.9
        elif days_to_tc < self.warning_days:
            tc_confidence = 0.7
        elif days_to_tc < self.warning_days + 10:
            tc_confidence = 0.5
        else:
            tc_confidence = 0.3

        # 基于成本函数值的置信度（值越小越好）
        cost_confidence = max(
            0.1, min(1.0, 1.0 - (cost_value / (data_length * self.cost_scale)))
        )

        # 基于数据长度的置信度
        data_confidence = min(1.0, data_length / self.data_reference)

        # 组合置信度 - 使用配置的权重
        return (
            self.tc_weight * tc_confidence
            + self.cost_weight * cost_confidence
            + self.data_weight * data_confidence
        )

    def _determine_risk_level(self, days_to_tc: float) -> str:
        """
        确定风险等级

        Args:
            days_to_tc: 到临界点的天数

        Returns:
            风险等级
        """
        if days_to_tc < self.danger_days:
            return "Danger"
        elif days_to_tc < self.warning_days:
            return "Warning"
        else:
            return "Safe"

    @handle_errors(
        LPPLFitError, AnalysisError, default_return={}, log_level=logging.ERROR
    )
    def fit(self, df: pd.DataFrame, column: str = "close") -> Dict[str, Any]:
        """
        拟合LPPL模型

        Args:
            df: 数据DataFrame
            column: 价格列名

        Returns:
            拟合结果
        """
        if df.empty:
            logger.error("Input DataFrame is empty")
            return {}

        if len(df) < self.min_data_points:
            logger.warning(
                f"Insufficient data points: need at least {self.min_data_points}, got {len(df)}"
            )
            return {}

        # 验证列存在性
        if column not in df.columns:
            logger.error(f"Column '{column}' not found in DataFrame")
            return {}

        # 准备数据
        prices = df[column].to_numpy()

        if np.any(prices <= 0) or np.any(np.isnan(prices)):
            logger.warning(
                f"Price data contains zero, negative, or NaN values. "
                f"Min={np.nanmin(prices)}, Max={np.nanmax(prices)}"
            )
            return {}

        t = np.arange(len(df))
        log_prices = np.log(prices)

        current_max_t = len(df)
        logger.info(f"Current max time point: {current_max_t}")

        # 设置参数搜索边界 - 只包含非线性参数 [tc, m, w]
        bounds = [
            (
                max(0, current_max_t - self.tc_backward),
                current_max_t + self.tc_forward,
            ),  # tc
            (self.m_min, self.m_max),  # m
            (self.w_min, self.w_max),  # w
        ]

        logger.info("Starting differential evolution optimization")
        # 使用差分进化算法进行全局优化
        result = differential_evolution(
            self.cost_function_reduced,
            bounds,
            args=(t, log_prices),
            strategy="best1bin",
            maxiter=self.maxiter,
            popsize=self.popsize,
            tol=self.tol,
            mutation=self.mutation,
            recombination=self.recombination,
            seed=self.seed,
            workers=self.workers,
        )

        if not result.success:
            logger.warning("Optimization failed, returning default result")
            return self._get_default_result()

        # 计算线性参数
        tc, m, w = result.x
        tau = tc - t  # 不使用 abs
        if np.any(tau <= 0):
            logger.warning("Optimization produced invalid tc (tau <= 0)")
            return self._get_default_result()

        # 构建设计矩阵 X
        f = tau**m
        g = f * np.cos(w * np.log(tau))
        h = f * np.sin(w * np.log(tau))
        X = np.column_stack([np.ones_like(t), f, g, h])

        # 求解线性参数
        beta, _, _, _ = np.linalg.lstsq(X, log_prices, rcond=None)
        a, b, c1, c2 = beta

        # 计算c和phi
        c = np.sqrt(c1**2 + c2**2)
        phi = np.arctan2(-c2, c1)

        days_to_tc = tc - current_max_t
        logger.info(f"Calculated tc: {tc}, days_to_tc: {days_to_tc}")

        # 应用Sornette约束
        is_valid = self._apply_sornette_constraints(m, w, b, c)
        logger.info(f"Sornette constraints check: {is_valid}")

        # 计算置信度
        confidence = self._calculate_confidence(days_to_tc, result.fun, len(df))
        logger.info(f"Calculated confidence: {confidence:.4f}")

        # 确定风险等级
        risk_level = self._determine_risk_level(days_to_tc)
        logger.info(f"Risk level: {risk_level}")

        # 确定是否为泡沫
        is_bubble = (
            is_valid
            and (b < 0)
            and (abs(c) > self.c_abs_for_bubble)
            and confidence > self.confidence_threshold
        )
        logger.info(f"Is bubble: {is_bubble}")

        return {
            "is_bubble": is_bubble,
            "tc": tc,
            "days_to_tc": days_to_tc,
            "confidence": confidence,
            "lppl_risk": risk_level,
            "risk_level": risk_level,
            "model_params": {
                "m": m,
                "w": w,
                "a": a,
                "b": b,
                "c": c,
                "phi": phi,
            },
            "market_metrics": {
                "optimization_success": result.success,
                "cost_function_value": result.fun,
                "valid_constraints": is_valid,
                "data_points": len(df),
            },
        }

    def _get_default_result(self) -> Dict[str, Any]:
        """
        获取默认结果

        Returns:
            默认结果
        """
        return {
            "is_bubble": False,
            "tc": None,
            "days_to_tc": 50.0,
            "confidence": 0.0,
            "lppl_risk": "Safe",
            "risk_level": "Safe",
            "model_params": {},
            "market_metrics": {},
        }
