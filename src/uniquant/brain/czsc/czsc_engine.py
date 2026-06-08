from enum import Enum
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from czsc import CZSC, Freq, RawBar

try:
    import czsc.signals as czsc_signals
    HAS_CZSC_SIGNALS = True
except ImportError:
    HAS_CZSC_SIGNALS = False

from ...shared.constants import DataValidationConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


CZSC_RECOVERABLE_ERRORS = (
    AttributeError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
)


class CZSCSignalType(Enum):
    """CZSC信号类型枚举 - 避免字符串匹配脆性问题"""
    FIRST_BUY = "一买"
    FIRST_SELL = "一卖"
    SECOND_BUY = "二买"
    SECOND_SELL = "二卖"
    THIRD_BUY = "三买"
    THIRD_SELL = "三卖"
    UNKNOWN = "UNKNOWN"
    
    @classmethod
    def from_signal_value(cls, value: Any) -> "CZSCSignalType":
        """
        从信号值解析信号类型
        
        Args:
            value: 信号值（可能是字符串、枚举或其他类型）
            
        Returns:
            CZSCSignalType: 信号类型枚举
        """
        if value is None:
            return cls.UNKNOWN
        
        value_str = str(value)
        
        # 支持中文和英文两种格式
        signal_mapping = {
            "一买": cls.FIRST_BUY,
            "一卖": cls.FIRST_SELL,
            "二买": cls.SECOND_BUY,
            "二卖": cls.SECOND_SELL,
            "三买": cls.THIRD_BUY,
            "三卖": cls.THIRD_SELL,
            "1st_BUY": cls.FIRST_BUY,
            "1st_SELL": cls.FIRST_SELL,
            "2nd_BUY": cls.SECOND_BUY,
            "2nd_SELL": cls.SECOND_SELL,
            "3rd_BUY": cls.THIRD_BUY,
            "3rd_SELL": cls.THIRD_SELL,
        }
        
        for pattern, signal_type in signal_mapping.items():
            if pattern in value_str:
                return signal_type
        
        return cls.UNKNOWN


class CZSCAnalysisError(AnalysisError):
    """缠论分析错误"""


class CZSCEngine:
    """
    缠论分析引擎
    提供缠论技术分析功能
    """

    MIN_DATA_POINTS = DataValidationConstants.MIN_DATA_POINTS
    REQUIRED_COLUMNS = {"date", "open", "close", "high", "low"}
    VOLUME_COLUMNS = ["volume", "vol"]

    def __init__(self):
        self.analyzer = None
        self._current_symbol: str = ""
        self._analysis_coverage = 0.0  # 分析覆盖率

    def _get_volume(self, row) -> float:
        """获取成交量，兼容 volume 和 vol 两种列名"""
        for col in self.VOLUME_COLUMNS:
            if col in (row.index if isinstance(row, pd.Series) else row):
                return float(row[col])
        return 0.0

    def _validate_input_row(self, df_latest_row) -> bool:
        """
        验证输入数据行

        Args:
            df_latest_row: 数据行 (pd.Series 或 dict)

        Returns:
            bool: 是否有效
        """
        if df_latest_row is None:
            logger.warning("输入数据行为None")
            return False

        if isinstance(df_latest_row, dict):
            cols = set(df_latest_row.keys())
        elif isinstance(df_latest_row, pd.Series):
            cols = set(df_latest_row.index)
        else:
            logger.warning(f"输入数据类型错误: {type(df_latest_row)}")
            return False

        missing_cols = self.REQUIRED_COLUMNS - cols
        if missing_cols:
            logger.warning(f"缺少必需列: {missing_cols}")
            return False

        # 检查OHLC完整性
        ohlc_cols = ["open", "high", "low", "close"]
        for col in ohlc_cols:
            if pd.isna(df_latest_row[col]):
                logger.warning(f"{col}值为NaN")
                return False
            if df_latest_row[col] <= 0:
                logger.warning(f"{col}值必须为正数: {df_latest_row[col]}")
                return False

        # 检查价格逻辑
        if not (
            df_latest_row["low"] <= df_latest_row["close"] <= df_latest_row["high"]
        ):
            logger.warning("价格逻辑错误: low <= close <= high 不满足")
            return False

        if not (df_latest_row["low"] <= df_latest_row["open"] <= df_latest_row["high"]):
            logger.warning("价格逻辑错误: low <= open <= high 不满足")
            return False

        return True

    @handle_errors(
        AnalysisError,
        Exception,
        default_return={"is_3rd_buy": False, "bi_count": 0, "error": "分析失败"},
        log_level=logger.error,
        reraise=False,
    )
    def update_and_get_signals(self, df_latest_row: pd.Series, symbol: str = "") -> Dict[str, Any]:
        """
        增量更新CZSC分析器并获取信号

        Args:
            df_latest_row: 最新一行数据，必须包含date, open, close, high, low, volume列

        Returns:
            包含以下键的字典:
            - is_3rd_buy (bool): 是否为第三类买点
            - bi_count (int): 笔的数量
            - error (str): 错误信息（如果有）

        Raises:
            CZSCAnalysisError: 分析失败时抛出
        """
        # 验证输入数据
        if not self._validate_input_row(df_latest_row):
            logger.warning("K线数据验证失败，跳过本次分析")
            return {"is_3rd_buy": False, "bi_count": 0, "error": "数据验证失败"}

        # Reset analyzer when symbol changes to prevent cross-stock state pollution
        if symbol and symbol != self._current_symbol:
            self.analyzer = None
            self._current_symbol = symbol

        try:
            # 计算amount值
            if "amount" in df_latest_row:
                amount = df_latest_row["amount"]
            else:
                amount = df_latest_row["close"] * self._get_volume(df_latest_row)

            volume = self._get_volume(df_latest_row)
            
            bar = RawBar(
                symbol=symbol or "S",
                dt=df_latest_row["date"],
                open=df_latest_row["open"],
                close=df_latest_row["close"],
                high=df_latest_row["high"],
                low=df_latest_row["low"],
                vol=volume,
                amount=amount,
                freq=Freq.D,
            )

            if not self.analyzer:
                self.analyzer = CZSC([bar])
            else:
                self.analyzer.update(bar)  # 增量更新，支持毫秒级响应

            # 提取信号字典中的三买标记 - 使用枚举类型避免字符串匹配脆性
            signals = getattr(self.analyzer, "signals", None) or {}
            bi_list = getattr(self.analyzer, "bi_list", None) or []

            is_3buy = any(
                CZSCSignalType.from_signal_value(v) == CZSCSignalType.THIRD_BUY
                for v in signals.values()
            )
            bi_count = len(bi_list)

            logger.debug(f"CZSC分析完成: 笔数量={bi_count}, 三买信号={is_3buy}")

            return {"is_3rd_buy": is_3buy, "bi_count": bi_count, "error": None}

        except CZSC_RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC增量分析失败: {e}")
            raise CZSCAnalysisError(f"增量分析失败: {e}") from e

    def _validate_input_dataframe(self, df: pd.DataFrame) -> bool:
        """
        验证输入数据框

        Args:
            df: 数据框

        Returns:
            bool: 是否有效
        """
        if df is None:
            logger.warning("输入数据为None")
            return False

        if not isinstance(df, pd.DataFrame):
            logger.warning(f"输入数据类型错误: {type(df)}")
            return False

        if df.empty:
            logger.warning("输入数据为空")
            return False

        if len(df) < self.MIN_DATA_POINTS:
            logger.warning(f"数据点不足: {len(df)} < {self.MIN_DATA_POINTS}")
            return False

        missing_cols = self.REQUIRED_COLUMNS - set(df.columns)
        if missing_cols:
            logger.warning(f"缺少必需列: {missing_cols}")
            return False

        # 检查OHLC完整性
        ohlc_cols = ["open", "high", "low", "close"]
        for col in ohlc_cols:
            if df[col].isna().all():
                logger.warning(f"{col}列全为NaN")
                return False

        return True

    def _prepare_bar_list(self, df: pd.DataFrame) -> tuple:
        """
        准备RawBar列表（向量化过滤优化）

        Args:
            df: 输入数据框

        Returns:
            tuple: (RawBar列表, 跳过的K线数量)
        """
        dates = pd.to_datetime(df["date"]).tolist()
        opens = df["open"].values
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values

        volume_col = "volume" if "volume" in df.columns else "vol"
        vols = df[volume_col].values if volume_col in df.columns else np.zeros(len(df))

        if "amount" in df.columns:
            amounts = df["amount"].values
        else:
            amounts = closes * vols

        # 向量化过滤：一次性计算所有行的有效性掩码
        nan_mask = ~(np.isnan(opens) | np.isnan(closes) | np.isnan(highs) | np.isnan(lows))
        positive_mask = (opens > 0) & (closes > 0) & (highs > 0) & (lows > 0)
        logic_mask = (lows <= closes) & (closes <= highs) & (lows <= opens) & (opens <= highs)

        valid_mask = nan_mask & positive_mask & logic_mask
        valid_indices = np.where(valid_mask)[0]
        skipped_count = int(np.sum(~valid_mask))

        # 仅对有效行构建 RawBar 对象
        bars = []
        for i in valid_indices:
            try:
                bar = RawBar(
                    symbol="STOCK",
                    dt=dates[i],
                    open=float(opens[i]),
                    close=float(closes[i]),
                    high=float(highs[i]),
                    low=float(lows[i]),
                    vol=float(vols[i]),
                    amount=float(amounts[i]),
                    freq=Freq.D,
                )
                bars.append(bar)
            except CZSC_RECOVERABLE_ERRORS as e:
                logger.warning(f"跳过异常K线 {i}: {e}")
                skipped_count += 1

        return bars, skipped_count

    def _initialize_czsc_analyzer(self, bars: List[RawBar]) -> CZSC:
        """
        初始化CZSC分析器

        Args:
            bars: RawBar列表

        Returns:
            CZSC分析器实例
        """
        return CZSC(bars)

    def _extract_czsc_signals(self, analyzer: CZSC) -> Dict[str, Any]:
        """
        从CZSC分析器中提取信号

        Args:
            analyzer: CZSC分析器实例

        Returns:
            包含笔和信号的字典
        """
        bi_list = analyzer.bi_list
        signals = analyzer.signals

        is_3rd_buy = False
        last_bi = bi_list[-1] if bi_list else None
        pen_count = len(bi_list)
        bottom_fractal = None
        czsc_bottom_price = None

        if pen_count >= 3:
            if last_bi and last_bi.direction.value == -1:
                bottom_fractal = last_bi.low
                czsc_bottom_price = round(bottom_fractal, 2)

        if HAS_CZSC_SIGNALS:
            try:
                third_buy_result = czsc_signals.cxt_third_buy_V230228(analyzer)
                if third_buy_result:
                    for key, value in third_buy_result.items():
                        value_str = str(value)
                        if "三买_" in value_str or "三买" == value_str:
                            is_3rd_buy = True
                            logger.info(f"检测到三买信号: {key}={value}")
                            break
            except CZSC_RECOVERABLE_ERRORS as e:
                logger.debug(f"三买信号检测失败: {e}")

        if not is_3rd_buy:
            # 使用枚举类型检测三买信号
            for signal_value in signals.values():
                if CZSCSignalType.from_signal_value(signal_value) == CZSCSignalType.THIRD_BUY:
                    is_3rd_buy = True
                    break

        return {
            "bi_list": bi_list,
            "signals": signals,
            "is_3rd_buy": is_3rd_buy,
            "last_bi": last_bi,
            "pen_count": pen_count,
            "bottom_fractal": bottom_fractal,
            "czsc_bottom_price": czsc_bottom_price,
        }

    def _build_czsc_result(
        self, signal_data: Dict[str, Any], bars: List[RawBar], df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        构建CZSC分析结果

        Args:
            signal_data: 信号数据
            bars: RawBar列表
            df: 原始数据框

        Returns:
            CZSC分析结果字典
        """
        # 计算分析覆盖率
        self._analysis_coverage = len(bars) / len(df)
        logger.info(
            f"CZSC分析: 总K线={len(df)}, 有效={len(bars)}, "
            f"覆盖率={self._analysis_coverage:.2%}"
        )

        return {
            "bi_count": signal_data["pen_count"],
            "last_bi_direction": (
                signal_data["last_bi"].direction.value
                if signal_data["last_bi"]
                else None
            ),
            "is_3rd_buy": signal_data["is_3rd_buy"],
            "czsc_signal": "3rd_BUY" if signal_data["is_3rd_buy"] else "NONE",
            "bottom_fractal": signal_data["bottom_fractal"],
            "czsc_bottom_price": signal_data["czsc_bottom_price"],
            "signals": signal_data["signals"],
            "geometry_desc": self._generate_geometry_desc(
                signal_data["bi_list"], signal_data["is_3rd_buy"]
            ),
            "analysis_coverage": self._analysis_coverage,
            "error": None,
        }

    def _build_error_result(self, error_msg: str) -> Dict[str, Any]:
        """
        构建错误结果

        Args:
            error_msg: 错误信息

        Returns:
            错误结果字典
        """
        return {
            "bi_count": 0,
            "last_bi_direction": None,
            "is_3rd_buy": False,
            "czsc_signal": "NONE",
            "bottom_fractal": None,
            "czsc_bottom_price": None,
            "signals": {},
            "geometry_desc": error_msg,
            "analysis_coverage": 0.0,
            "error": error_msg,
        }

    @handle_errors(
        AnalysisError,
        Exception,
        default_return={
            "bi_count": 0,
            "is_3rd_buy": False,
            "czsc_signal": "NONE",
            "czsc_bottom_price": None,
            "signals": {},
            "geometry_desc": "分析失败",
            "error": "分析异常",
        },
        log_level=logger.error,
        reraise=False,
    )
    def get_czsc_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        获取缠论信号

        Args:
            df: 输入数据框，必须包含date, open, close, high, low, volume列

        Returns:
            包含以下键的字典:
            - bi_count (int): 笔的数量
            - last_bi_direction (int): 最后一笔的方向（1表示向上，-1表示向下）
            - is_3rd_buy (bool): 是否为第三类买点
            - czsc_signal (str): 缠论信号
            - bottom_fractal (float): 底部分形价格
            - czsc_bottom_price (float): 缠论底部价格
            - signals (Dict): 原始信号
            - geometry_desc (str): 几何分析描述
            - analysis_coverage (float): 分析覆盖率
            - error (str): 错误信息（如果有）

        Raises:
            CZSCAnalysisError: 分析失败时抛出
        """
        # 验证输入数据
        if not self._validate_input_dataframe(df):
            logger.warning("输入数据验证失败，返回空分析结果")
            return self._build_error_result("数据验证失败")

        try:
            # 准备RawBar列表
            bars, _ = self._prepare_bar_list(df)

            if len(bars) < 10:
                logger.warning(f"有效K线数量不足: {len(bars)}")
                return self._build_error_result("有效K线数量不足")

            # 初始化CZSC分析器
            analyzer = self._initialize_czsc_analyzer(bars)

            # 提取信号
            signal_data = self._extract_czsc_signals(analyzer)

            # 构建结果
            return self._build_czsc_result(signal_data, bars, df)

        except CZSC_RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC分析失败: {e}")
            raise CZSCAnalysisError(f"分析失败: {e}") from e

    def _generate_geometry_desc(self, bi_list: List[Any], is_3rd_buy: bool) -> str:
        """
        生成几何分析描述

        Args:
            bi_list: 笔的列表
            is_3rd_buy: 是否为第三类买点

        Returns:
            几何分析描述字符串
        """
        pen_count = len(bi_list)

        if pen_count < 3:
            return f"当前笔数量不足，无法进行完整几何分析（当前笔数量：{pen_count}）"

        last_bi = bi_list[-1]
        prev_bi = bi_list[-2]

        desc = f"已识别{pen_count}笔结构。"

        if last_bi.direction.value == -1:  # Downward pen
            desc += f"当前处于向下一笔回调，最低价：{round(last_bi.low, 2)}。"
            if prev_bi.direction.value == 1:  # Previous was upward
                desc += f"前一笔为向上突破，最高价：{round(prev_bi.high, 2)}。"
        else:  # Upward pen
            desc += f"当前处于向上一笔，最高价：{round(last_bi.high, 2)}。"

        if is_3rd_buy:
            desc += "已确认第三类买点（3rd_BUY），满足笔结构和中枢突破条件。"

        return desc

    def get_czsc_signals_from_data(
        self, data_fetcher, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        """
        从数据模块获取数据并检测缠论信号
        
        .. deprecated::
            此方法破坏 Data Lake 原则，大脑模块不应直接调用 DataFetcher。
            请使用 `get_czsc_signals(df)` 替代，传入已标准化的 DataFrame。

        Args:
            data_fetcher: DataFetcher实例，用于获取数据
            symbol: 证券代码
            start_date: 开始日期，格式为"YYYY-MM-DD"
            end_date: 结束日期，格式为"YYYY-MM-DD"

        Returns:
            缠论信号检测结果，包含以下键:
            - bi_count (int): 笔的数量
            - last_bi_direction (int): 最后一笔的方向（1表示向上，-1表示向下）
            - is_3rd_buy (bool): 是否为第三类买点
            - czsc_signal (str): 缠论信号
            - bottom_fractal (float): 底部分形价格
            - czsc_bottom_price (float): 缠论底部价格
            - signals (Dict): 原始信号
            - geometry_desc (str): 几何分析描述
            - error (str): 错误信息（如果有）
        """
        import warnings
        warnings.warn(
            "get_czsc_signals_from_data is deprecated. "
            "Use get_czsc_signals(df) with pre-loaded DataFrame instead.",
            DeprecationWarning,
            stacklevel=2
        )

        try:
            df = data_fetcher.fetch_history(symbol, start_date, end_date)

            # 验证数据
            if df is None or df.empty:
                logger.error(f"无法获取 {symbol} 的数据")
                return {
                    "bi_count": 0,
                    "is_3rd_buy": False,
                    "czsc_signal": "NONE",
                    "czsc_bottom_price": None,
                    "signals": {},
                    "geometry_desc": "无法获取数据",
                    "error": "无法获取数据",
                }

            # 标准化列名
            if "Date" in df.columns:
                df = df.rename(columns={"Date": "date"})
            if "Open" in df.columns:
                df = df.rename(columns={"Open": "open"})
            if "Close" in df.columns:
                df = df.rename(columns={"Close": "close"})
            if "High" in df.columns:
                df = df.rename(columns={"High": "high"})
            if "Low" in df.columns:
                df = df.rename(columns={"Low": "low"})
            if "Volume" in df.columns:
                df = df.rename(columns={"Volume": "volume"})

            # 检测缠论信号
            result = self.get_czsc_signals(df)

            return result
        except CZSC_RECOVERABLE_ERRORS as e:
            logger.error(f"检测缠论信号时出错: {e}")
            return {
                "bi_count": 0,
                "is_3rd_buy": False,
                "czsc_signal": "NONE",
                "czsc_bottom_price": None,
                "signals": {},
                "geometry_desc": "几何分析失败",
                "error": str(e),
            }
