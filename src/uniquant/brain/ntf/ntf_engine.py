from typing import Any, Dict, Optional

import pandas as pd

try:
    from ...data.data_fetcher import DataFetcher
except ImportError:
    DataFetcher = None
from ...shared.config_loader import config
from ...shared.constants import NTFConstants

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class NTFEngine:
    """
    V2.0 National Team Factor (NTF) Engine.
    Monitors pulse-like volume anomalies in large ETFs to identify intervention points.
    Target ETFs: 510300 (CSI300), 510050 (SSE50), 563300 (CSI2000).
    """

    def __init__(self, volume_ratio_threshold: Optional[float] = None):
        try:
            # Load defaults from config if not provided
            if volume_ratio_threshold is None:
                self.volume_ratio_threshold = config.get(
                    "brain.ntf.volume_ratio_threshold",
                    NTFConstants.VOLUME_RATIO_THRESHOLD,
                )
            else:
                self.volume_ratio_threshold = volume_ratio_threshold

            # 使用常量类中的阈值
            self.heat_threshold = NTFConstants.HEAT_THRESHOLD
            self.panic_threshold = NTFConstants.PANIC_THRESHOLD

            self.critical_etfs = config.get("markets.etfs.critical", {})
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"初始化NTF引擎时出错: {e}")
            # 设置默认值以确保引擎可以运行
            self.volume_ratio_threshold = NTFConstants.VOLUME_RATIO_THRESHOLD
            self.heat_threshold = NTFConstants.HEAT_THRESHOLD
            self.panic_threshold = NTFConstants.PANIC_THRESHOLD
            self.critical_etfs = {}

    def detect_intervention(
        self, etf_df: pd.DataFrame, window: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Analyze ETF data for volume pulsars and national team intervention.
        """
        try:
            if window is None:
                window = config.get("brain.ntf.window", NTFConstants.WINDOW)

            if len(etf_df) < 20:
                return {"detected": False, "side": "NONE"}

            volume_col = "volume" if "volume" in etf_df.columns else "vol"
            if volume_col not in etf_df.columns:
                logger.warning("数据缺少成交量列 (volume/vol)")
                return {"detected": False, "side": "NONE", "error": "缺少成交量数据"}

            curr_volume = etf_df[volume_col].iloc[-1]
            mean_volume = etf_df[volume_col].iloc[-(window + 1) : -1].mean()
            vol_ratio = curr_volume / mean_volume if mean_volume > 0 else 1.0

            # 2. 计算价格所处位置 (使用最近20天的分位数)
            price_window = etf_df["close"].iloc[-20:]
            current_price = etf_df["close"].iloc[-1]
            # 计算当前价格在过去20天内的百分比位置
            price_percentile = (current_price - price_window.min()) / (
                price_window.max() - price_window.min() + 1e-10
            )

            # 3. 综合判定方向
            is_pulse = vol_ratio >= self.volume_ratio_threshold
            side = "NONE"
            confidence = 0.0

            if is_pulse:
                if price_percentile < self.panic_threshold:
                    side = "SUPPORT"  # 护盘买入
                    confidence = NTFConstants.CONFIDENCE_SUPPORT
                elif price_percentile > self.heat_threshold:
                    side = "RESISTANCE"  # 降温卖出
                    confidence = NTFConstants.CONFIDENCE_RESISTANCE
                else:
                    side = "LIQUIDITY_PULSE"  # 普通放量，方向不明
                    confidence = NTFConstants.CONFIDENCE_LIQUIDITY

                logger.info(
                    f"NTF SIGNAL: Volume pulsar detected (Ratio: {vol_ratio:.2f}, Side: {side}, Confidence: {confidence:.2f})"
                )

            return {
                "detected": is_pulse,
                "side": side,
                "volume_ratio": round(vol_ratio, 2),
                "price_percentile": round(price_percentile, 2),
                "confidence": confidence,
                "action": self._get_action_desc(side),
            }
        except (ValueError, TypeError, KeyError, IndexError) as e:
            logger.error(f"检测干预时出错: {e}")
            return {
                "detected": False,
                "side": "NONE",
                "action": "检测过程出错",
                "error": str(e),
            }

    def _get_action_desc(self, side: str) -> str:
        try:
            mapping = {
                "SUPPORT": "国家队疑似进场护盘，关注底部支撑",
                "RESISTANCE": "市场过热，国家队疑似减持降温，警惕回调",
                "LIQUIDITY_PULSE": "大额资金调仓，建议观察",
                "NONE": "无明显干预迹象",
            }
            return mapping.get(side, "")
        except (TypeError, KeyError) as e:
            logger.error(f"获取动作描述时出错: {e}")
            return ""

    def scan_for_giants(
        self, market_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Dict[str, Any]]:
        """Scan all critical ETFs for intervention signals."""
        results = {}
        for symbol, df in market_data.items():
            if symbol in self.critical_etfs or symbol.split(".")[0] in [
                s.split(".")[0] for s in self.critical_etfs.keys()
            ]:
                results[symbol] = self.detect_intervention(df)
        return results

    def detect_intervention_from_data(
        self,
        data_fetcher: DataFetcher,
        etf_symbol: str,
        start_date: str,
        end_date: str,
        window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        从数据模块获取ETF数据并检测国家队干预

        参数:
        data_fetcher: DataFetcher实例，用于获取数据
        etf_symbol: ETF代码
        start_date: 开始日期，格式为"YYYY-MM-DD"
        end_date: 结束日期，格式为"YYYY-MM-DD"
        window: 计算成交量均值的窗口大小

        返回:
        干预检测结果
        """
        # 获取数据
        df = data_fetcher.fetch_history(etf_symbol, start_date, end_date)

        # 验证数据
        if df is None or df.empty:
            logger.error(f"无法获取 {etf_symbol} 的数据")
            return {"detected": False, "side": "NONE", "action": "无法获取数据"}

        # 标准化列名
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        if "Close" in df.columns:
            df = df.rename(columns={"Close": "close"})
        if "Volume" in df.columns:
            df = df.rename(columns={"Volume": "volume"})

        # 检查必要列
        if "close" not in df.columns or "volume" not in df.columns:
            logger.error(f"数据缺少必要列: close 或 volume")
            return {"detected": False, "side": "NONE", "action": "数据缺少必要列"}

        # 检测干预
        return self.detect_intervention(df, window)
