from enum import Enum
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ...shared.config_loader import config
from ...shared.constants import RegimeConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError
from ...shared.interfaces import RegimeOutput
from ...shared.logger_factory import get_logger

from ..indicators.indicators import Indicators

logger = get_logger(__name__)


class Regime(Enum):
    NORMAL = "NORMAL"  # Liquid, high entropy
    STRESSED = "STRESSED"  # Volatile, shallow depth
    FROZEN = "FROZEN"  # Liquidity hole, no bid/ask
    UNKNOWN = "UNKNOWN"  # 无法检测


class RegimeDetectionError(AnalysisError):
    """市场状态检测错误"""


class RegimeDetector:
    """
    V1.0 Liquidity Regime Detector (LRD).
    Identifies market 'phase transitions' to prevent trading in illiquid conditions.
    """

    def __init__(
        self,
        entropy_threshold: Optional[float] = None,
        turnover_z_limit: Optional[float] = None,
        min_data_points: Optional[int] = None,
    ):
        """
        初始化市场状态检测器

        Args:
            entropy_threshold: 熵值阈值，None则使用配置
            turnover_z_limit: 成交量Z-Score阈值，None则使用配置
            min_data_points: 最小数据点数，None则使用配置

        Raises:
            ValueError: 参数无效时抛出
        """
        if entropy_threshold is not None and not (0 <= entropy_threshold <= 1):
            raise ValueError("entropy_threshold必须在0-1之间")
        if turnover_z_limit is not None and turnover_z_limit <= 0:
            raise ValueError("turnover_z_limit必须为正数")
        if min_data_points is not None and min_data_points < 10:
            raise ValueError("min_data_points至少为10")

        if entropy_threshold is None:
            self.entropy_threshold = config.get(
                "brain.regime.entropy_threshold",
                RegimeConstants.ENTROPY_PERCENTILE_THRESHOLD,
            )
        else:
            self.entropy_threshold = entropy_threshold

        if turnover_z_limit is None:
            self.turnover_z_limit = config.get(
                "brain.regime.turnover_z_limit",
                RegimeConstants.TURNOVER_Z_SCORE_THRESHOLD,
            )
        else:
            self.turnover_z_limit = turnover_z_limit

        self.min_data_points = min_data_points or config.get(
            "brain.regime.min_data_points", RegimeConstants.MIN_DATA_POINTS
        )

        logger.info(
            "RegimeDetector初始化: entropy_threshold=%s, "
            "turnover_z_limit=%s, min_data_points=%s",
            self.entropy_threshold,
            self.turnover_z_limit,
            self.min_data_points,
        )

    def _validate_input_data(self, df: pd.DataFrame) -> bool:
        """
        验证输入数据

        Args:
            df: 输入数据框

        Returns:
            bool: 数据是否有效
        """
        if df is None:
            logger.warning("输入数据为None")
            return False

        if not isinstance(df, pd.DataFrame):
            logger.warning("输入数据类型错误: %s", type(df))
            return False

        if df.empty:
            logger.warning("输入数据为空")
            return False

        if len(df) < self.min_data_points:
            logger.warning("数据点不足: %s < %s", len(df), self.min_data_points)
            return False

        # 检查必需列
        required_cols = ["close", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning("缺少必需列: %s", missing_cols)
            return False

        # 检查是否全为NaN
        if df["close"].isna().all():
            logger.warning("收盘价列全为NaN")
            return False

        return True

    @handle_errors(
        AnalysisError, Exception, default_return=Regime.UNKNOWN, log_level=logger.error, reraise=False
    )
    def detect(self, df: pd.DataFrame) -> Regime:
        """
        Analyze current data to determine market regime using sliding window percentile.

        Args:
            df: 市场数据框

        Returns:
            Regime: 市场状态枚举值
        """
        if not self._validate_input_data(df):
            return Regime.UNKNOWN

        # 1. Entropy Check (Shannon Entropy of price changes)
        entropy_series = Indicators.calc_market_entropy(df)

        # Handle empty series
        if (
            entropy_series.empty
            or entropy_series.iloc[-1] is None
            or np.isnan(entropy_series.iloc[-1])
        ):
            logger.warning("Empty entropy series detected, defaulting to UNKNOWN regime")
            return Regime.UNKNOWN

        curr_entropy = entropy_series.iloc[-1]

        # 计算当前熵值在过去60天的分位数位置
        if len(entropy_series) >= RegimeConstants.ENTROPY_WINDOW:
            entropy_window = entropy_series.tail(RegimeConstants.ENTROPY_WINDOW)
            e_pct = (curr_entropy - entropy_window.min()) / (
                entropy_window.max() - entropy_window.min() + 1e-10
            )
        else:
            e_pct = 0.5  # 默认值

        # 2. Turnover Z-Score Check (Crowding)
        z_series = Indicators.calc_turnover_z(df)

        # Handle empty series
        if z_series.empty or z_series.iloc[-1] is None or np.isnan(z_series.iloc[-1]):
            logger.warning(
                "Empty turnover Z-series detected, defaulting to UNKNOWN regime"
            )
            return Regime.UNKNOWN

        curr_z = z_series.iloc[-1]

        # 3. Micro-Logic from V9.0 Specs
        # 如果熵值分位数 < 阈值，则返回FROZEN状态
        if e_pct < self.entropy_threshold:
            logger.warning("FROZEN regime detected (Entropy percentile: %.4f)", e_pct)
            return Regime.FROZEN

        # 如果成交量Z-Score的绝对值 > 阈值，则返回STRESSED状态
        if abs(curr_z) > self.turnover_z_limit:
            logger.warning("STRESSED regime detected (Turnover Z: %.2f)", curr_z)
            return Regime.STRESSED

        return Regime.NORMAL

    def get_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detailed metrics for the dashboard."""
        regime = self.detect(df)

        entropy_series = Indicators.calc_market_entropy(df)
        z_series = Indicators.calc_turnover_z(df)

        entropy = (
            entropy_series.iloc[-1]
            if not entropy_series.empty and len(entropy_series) > 0
            else 0.0
        )
        z = z_series.iloc[-1] if not z_series.empty and len(z_series) > 0 else 0.0

        # Handle NaN values
        if np.isnan(entropy):
            entropy = 0.0
        if np.isnan(z):
            z = 0.0

        return {
            "regime": regime.value,
            "entropy": round(float(entropy), 4),
            "turnover_z": round(float(z), 2),
            "is_safe": regime == Regime.NORMAL,
        }

    def detect_from_data(
        self, data_fetcher, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        """
        从数据模块获取数据并检测市场状态
        
        .. deprecated::
            此方法破坏 Data Lake 原则，大脑模块不应直接调用 DataFetcher。
            请使用 `get_summary(df)` 替代，传入已标准化的 DataFrame。

        参数:
        data_fetcher: DataFetcher实例，用于获取数据
        symbol: 证券代码
        start_date: 开始日期，格式为"YYYY-MM-DD"
        end_date: 结束日期，格式为"YYYY-MM-DD"

        返回:
        Dict[str, Any]: 市场状态检测结果
        """
        import warnings
        warnings.warn(
            "detect_from_data is deprecated. "
            "Use get_summary(df) with pre-loaded DataFrame instead.",
            DeprecationWarning,
            stacklevel=2
        )
        df = data_fetcher.fetch_history(symbol, start_date, end_date)

        # 验证数据
        if df is None or df.empty:
            logger.error("无法获取 %s 的数据", symbol)
            return {
                "regime": Regime.NORMAL.value,
                "entropy": 0.0,
                "turnover_z": 0.0,
                "is_safe": True,
                "error": "无法获取数据",
            }

        # 标准化列名
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        if "Close" in df.columns:
            df = df.rename(columns={"Close": "close"})
        if "High" in df.columns:
            df = df.rename(columns={"High": "high"})
        if "Low" in df.columns:
            df = df.rename(columns={"Low": "low"})
        if "Volume" in df.columns:
            df = df.rename(columns={"Volume": "volume"})

        # 检测市场状态
        summary = self.get_summary(df)

        return summary

    def get_typed_summary(self, df: pd.DataFrame) -> RegimeOutput:
        """类型化的 get_summary, 返回 RegimeOutput 替代 Dict."""
        result = self.get_summary(df)
        return RegimeOutput(
            regime=result.get("regime", "UNKNOWN"),
            entropy=float(result.get("entropy", 0.0)),
            turnover_z=float(result.get("turnover_z", 0.0)),
            is_safe=bool(result.get("is_safe", True)),
        )
