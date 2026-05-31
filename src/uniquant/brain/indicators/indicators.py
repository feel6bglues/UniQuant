from typing import Optional, Set, Union

import numpy as np
import pandas as pd

from ...shared.cache import smart_cache
from ...shared.constants import IndicatorThresholds, CacheConstants
from ...shared.interfaces import DataFetcherProtocol
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class IndicatorError(ValueError):
    """Indicator calculation error"""

    pass


class Indicators:
    _REQUIRED_COLUMNS = frozenset({"close", "high", "low"})
    _VOLUME_COLUMNS = ["volume", "vol"]

    @staticmethod
    def _get_volume_column(df: pd.DataFrame) -> str:
        """获取成交量列名，兼容 volume 和 vol"""
        for col in Indicators._VOLUME_COLUMNS:
            if col in df.columns:
                return col
        return "volume"

    @staticmethod
    def _validate_input(df: pd.DataFrame, required_columns: Optional[Set[str]] = None) -> None:
        if df is None or df.empty:
            raise IndicatorError("输入数据不能为空")
        cols = required_columns or Indicators._REQUIRED_COLUMNS
        missing = cols - set(df.columns)
        if missing:
            raise IndicatorError(f"缺少必要列: {missing}")

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_ma(df: pd.DataFrame, window: int, column: str = "close") -> pd.Series:
        Indicators._validate_input(df, {column})
        if window <= 0:
            raise IndicatorError("Window 必须为正数")
        # 使用 min_periods 兼容次新股/停牌股
        min_periods = max(int(window * IndicatorThresholds.ROLLING_MIN_PERIODS_RATIO), 
                          IndicatorThresholds.ROLLING_MIN_PERIODS_MIN)
        return df[column].rolling(window=window, min_periods=min_periods).mean()

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_ema(df: pd.DataFrame, window: int, column: str = "close") -> pd.Series:
        Indicators._validate_input(df, {column})
        # adjust=False 是为了匹配标准的递归EMA公式
        return df[column].ewm(span=window, adjust=False).mean()

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_atr(
        df: pd.DataFrame, window: int = IndicatorThresholds.ATR_PERIOD
    ) -> pd.Series:
        Indicators._validate_input(df)
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)

        tr = np.maximum(
            high - low, np.maximum((high - close_prev).abs(), (low - close_prev).abs())
        )
        # 标准ATR通常使用简单移动平均也可换为EMA
        # 使用 min_periods 兼容次新股/停牌股
        min_periods = max(int(window * IndicatorThresholds.ROLLING_MIN_PERIODS_RATIO), 
                          IndicatorThresholds.ROLLING_MIN_PERIODS_MIN)
        return pd.Series(tr).rolling(window=window, min_periods=min_periods).mean()

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_bollinger(
        df: pd.DataFrame,
        window: int = IndicatorThresholds.BOLLINGER_PERIOD,
        num_std: float = 2.0,
    ) -> pd.DataFrame:
        Indicators._validate_input(df, {"close"})
        # 使用 min_periods 兼容次新股/停牌股
        min_periods = max(int(window * IndicatorThresholds.ROLLING_MIN_PERIODS_RATIO), 
                          IndicatorThresholds.ROLLING_MIN_PERIODS_MIN)
        rolling_mean = df["close"].rolling(window=window, min_periods=min_periods).mean()
        rolling_std = df["close"].rolling(window=window, min_periods=min_periods).std()

        upper = rolling_mean + (rolling_std * num_std)
        lower = rolling_mean - (rolling_std * num_std)

        return pd.DataFrame(
            {
                "bollinger_middle": rolling_mean,
                "bollinger_upper": upper,
                "bollinger_lower": lower,
            },
            index=df.index,
        )

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_macd(
        df: pd.DataFrame,
        fast: int = IndicatorThresholds.MACD_FAST,
        slow: int = IndicatorThresholds.MACD_SLOW,
        signal: int = IndicatorThresholds.MACD_SIGNAL,
    ) -> pd.DataFrame:
        Indicators._validate_input(df, {"close"})
        if fast >= slow:
            raise IndicatorError("Fast window 必须小于 Slow window")

        # 使用 ewm 直接计算，效率更高
        exp1 = df["close"].ewm(span=fast, adjust=False).mean()
        exp2 = df["close"].ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line

        return pd.DataFrame(
            {"macd": macd_line, "signal": signal_line, "hist": hist}, index=df.index
        )

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_rsi(
        df: pd.DataFrame, window: int = IndicatorThresholds.RSI_PERIOD
    ) -> pd.Series:
        """
        标准 Wilder's RSI 实现 (使用 EMA 而非 SMA)
        """
        Indicators._validate_input(df, {"close"})
        delta = df["close"].diff()

        # alpha=1/window 是 Wilder's RSI 的标准平滑参数
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)  # 避免除以零的情况
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)  # 初始阶段填充默认值50

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_market_entropy(
        df: pd.DataFrame, window: int = IndicatorThresholds.ENTROPY_WINDOW, bins: int = 10
    ) -> pd.Series:
        """
        市场熵，衡量市场不确定性，对极端数据更敏感
        使用 NumPy 向量化优化，避免 rolling.apply 的性能问题
        """
        Indicators._validate_input(df, {"close"})
        
        # 1. 准备数据：计算收益率
        pct = df["close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0).values
        
        N = len(pct)
        if N < window:
            return pd.Series(np.nan, index=df.index)
        
        # 2. 确保内存连续 - Gemini警告: 必须使用 ascontiguousarray 避免 stride_tricks 出错
        pct = np.ascontiguousarray(pct, dtype=np.float64)
        
        # 3. 构建滑动窗口视图 (View, 不复制内存)
        shape = (N - window + 1, window)
        strides = (pct.strides[0], pct.strides[0])
        windows = np.lib.stride_tricks.as_strided(pct, shape=shape, strides=strides)
        
        # 4. 计算熵 (比 Pandas rolling.apply 快得多)
        entropies = np.zeros(shape[0])
        for i in range(shape[0]):
            w = windows[i]
            counts, _ = np.histogram(w, bins=bins)
            p = counts / counts.sum()
            p = p[p > 0]
            entropies[i] = -(p * np.log2(p)).sum()
        
        # 5. 填充结果，保持与原始索引对齐
        result = np.full(N, np.nan)
        result[window - 1:] = entropies
        
        return pd.Series(result, index=df.index)

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_turnover_z(
        df: pd.DataFrame, window: int = IndicatorThresholds.TURNOVER_Z_PERIOD
    ) -> pd.Series:
        """
        换手率/成交量的 Z-Score，用于识别异常放量
        """
        if "turnover" in df.columns:
            target_col = "turnover"
        else:
            target_col = Indicators._get_volume_column(df)
        
        if target_col not in df.columns:
            return pd.Series(index=df.index, data=0.0)
        
        data = df[target_col]
        # 使用 min_periods 兼容次新股/停牌股
        min_periods = max(int(window * IndicatorThresholds.ROLLING_MIN_PERIODS_RATIO), 
                          IndicatorThresholds.ROLLING_MIN_PERIODS_MIN)
        rolling_mean = data.rolling(window=window, min_periods=min_periods).mean()
        rolling_std = data.rolling(window=window, min_periods=min_periods).std()

        z_score = (data - rolling_mean) / rolling_std.replace(0, np.nan)
        return z_score.fillna(0)

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calc_vol_ratio(
        df: pd.DataFrame, window: int = IndicatorThresholds.VOLUME_MA_PERIOD
    ) -> pd.Series:
        """
        成交量比，即当前成交量 / 过去N日平均成交量
        """
        vol_col = Indicators._get_volume_column(df)
        if vol_col not in df.columns:
            return pd.Series(index=df.index, data=1.0)
        
        # 使用 min_periods 兼容次新股/停牌股
        min_periods = max(int(window * IndicatorThresholds.ROLLING_MIN_PERIODS_RATIO), 
                          IndicatorThresholds.ROLLING_MIN_PERIODS_MIN)
        avg_vol = df[vol_col].rolling(window=window, min_periods=min_periods).mean().shift(1)
        ratio = df[vol_col] / avg_vol.replace(0, np.nan)
        return ratio.fillna(1.0)

    @staticmethod
    @smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标

        参数:
        df: 包含价格数据的DataFrame，必须包含close, high, low, volume列

        返回:
        包含所有计算指标的DataFrame
        """
        try:
            Indicators._validate_input(df)

            # 创建结果DataFrame
            result = df.copy()

            # 计算RSI
            result["rsi"] = Indicators.calc_rsi(df)

            # 计算MACD
            macd_result = Indicators.calc_macd(df)
            result["macd"] = macd_result["macd"]
            result["macd_signal"] = macd_result["signal"]
            result["macd_hist"] = macd_result["hist"]

            # 计算ATR
            result["atr"] = Indicators.calc_atr(df)

            # 计算MA
            result["ma20"] = Indicators.calc_ma(df, 20)
            result["ma60"] = Indicators.calc_ma(df, 60)

            # 计算EMA
            result["ema20"] = Indicators.calc_ema(df, 20)

            # 计算布林带
            bollinger = Indicators.calc_bollinger(df)
            result["bollinger_upper"] = bollinger["bollinger_upper"]
            result["bollinger_middle"] = bollinger["bollinger_middle"]
            result["bollinger_lower"] = bollinger["bollinger_lower"]

            # 计算市场熵
            result["market_entropy"] = Indicators.calc_market_entropy(df)

            # 计算成交量Z-score
            result["turnover_z"] = Indicators.calc_turnover_z(df)

            return result
        except Exception as e:
            logger.exception(f"Error calculating all indicators: {e}")
            raise IndicatorError(f"计算所有指标时发生错误: {e}")

    @staticmethod
    def calculate_indicator_from_data(
        data_fetcher: DataFetcherProtocol,
        symbol: str,
        start_date: str,
        end_date: str,
        indicator_name: str,
        **kwargs,
    ) -> Union[pd.Series, pd.DataFrame]:
        """
        从数据模块获取数据并计算指定指标
        
        .. deprecated::
            此方法破坏 Data Lake 原则，大脑模块不应直接调用 DataFetcher。
            请使用对应的指标方法（如 `calc_ma`, `calc_rsi` 等）替代，传入已标准化的 DataFrame。

        参数:
        data_fetcher: DataFetcherProtocol实例，用于获取数据
        symbol: 证券代码
        start_date: 开始日期，格式为"YYYY-MM-DD"
        end_date: 结束日期，格式为"YYYY-MM-DD"
        indicator_name: 指标名称，如"ma", "ema", "rsi"等
        **kwargs: 指标计算所需的额外参数

        返回:
        计算后的指标值，可能是Series或DataFrame

        Raises:
            IndicatorError: 当指标计算失败时
            ValueError: 当输入参数无效时
        """
        import warnings
        warnings.warn(
            "calculate_indicator_from_data is deprecated. "
            "Use specific indicator methods (calc_ma, calc_rsi, etc.) with pre-loaded DataFrame instead.",
            DeprecationWarning,
            stacklevel=2
        )
        try:
            if not symbol or not isinstance(symbol, str):
                raise ValueError("symbol must be a non-empty string")

            if not indicator_name or not isinstance(indicator_name, str):
                raise ValueError("indicator_name must be a non-empty string")

            # 获取数据
            df = data_fetcher.fetch_history(symbol, start_date, end_date)

            # 验证数据
            if df is None or df.empty:
                raise IndicatorError(f"无法获取 {symbol} 的数据")

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

            # 根据指标名称计算指标
            indicator_name = indicator_name.lower()

            if indicator_name == "ma":
                window = kwargs.get("window", IndicatorThresholds.BOLLINGER_PERIOD)
                column = kwargs.get("column", "close")
                return Indicators.calc_ma(df, window, column)
            elif indicator_name == "ema":
                window = kwargs.get("window", IndicatorThresholds.BOLLINGER_PERIOD)
                column = kwargs.get("column", "close")
                return Indicators.calc_ema(df, window, column)
            elif indicator_name == "atr":
                window = kwargs.get("window", IndicatorThresholds.ATR_PERIOD)
                return Indicators.calc_atr(df, window)
            elif indicator_name == "macd":
                fast = kwargs.get("fast", IndicatorThresholds.MACD_FAST)
                slow = kwargs.get("slow", IndicatorThresholds.MACD_SLOW)
                signal = kwargs.get("signal", IndicatorThresholds.MACD_SIGNAL)
                return Indicators.calc_macd(df, fast, slow, signal)
            elif indicator_name == "rsi":
                window = kwargs.get("window", IndicatorThresholds.RSI_PERIOD)
                return Indicators.calc_rsi(df, window)
            elif indicator_name == "market_entropy":
                window = kwargs.get("window", IndicatorThresholds.ENTROPY_WINDOW)
                return Indicators.calc_market_entropy(df, window)
            elif indicator_name == "turnover_z":
                window = kwargs.get("window", IndicatorThresholds.TURNOVER_Z_PERIOD)
                return Indicators.calc_turnover_z(df, window)
            elif indicator_name == "vol_ratio":
                window = kwargs.get("window", IndicatorThresholds.VOLUME_MA_PERIOD)
                return Indicators.calc_vol_ratio(df, window)
            elif indicator_name == "bollinger":
                window = kwargs.get("window", IndicatorThresholds.BOLLINGER_PERIOD)
                num_std = kwargs.get("num_std", 2.0)
                return Indicators.calc_bollinger(df, window, num_std)
            else:
                raise IndicatorError(f"不支持的指标名称: {indicator_name}")

        except IndicatorError:
            # Re-raise IndicatorError as is
            raise
        except ValueError as e:
            logger.error(f"Invalid parameter in calculate_indicator_from_data: {e}")
            raise IndicatorError(f"参数错误: {e}")
        except KeyError as e:
            logger.error(f"Missing required column in data: {e}")
            raise IndicatorError(f"数据列缺失: {e}")
        except Exception as e:
            logger.exception(
                f"Unexpected error calculating indicator {indicator_name} for {symbol}: {e}"
            )
            raise IndicatorError(f"计算指标时发生错误: {e}")
