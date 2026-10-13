"""
数据获取器 - 系统的大脑和总指挥
根据 datapipeline.md 架构设计重构
"""

import logging
from datetime import datetime
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple
import pandas as pd

from ..shared.error_handling import handle_errors
from ..shared.exceptions import DataFetchError, DataValidationError
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider

from .lake.storage_manager import StorageManager
from .pipeline.data_cleaner import DataCleaner
from .pipeline.data_validator import DataValidator

# 湖优先单源 (预注册裁决 D1): 仅保留本地 mootdx 解包兜底。
# 爬虫源 (Tdx/Baostock/Sina/Ths/Tencent) 模块级 import 已删除 — 如需网络源请走后续裁决,
# 且必须从 sources/ 直接导入, 不得回流本模块。
from .corporate_action import get_corporate_action_adjuster
from .sources.mootdx_local import MootdxLocalSource
from .data_pipeline_service import DataPipelineService

# 新增的 Managers
from .managers.stock_metadata_manager import StockMetadataManager
from .managers.trade_calendar_manager import TradeCalendarManager
from .managers.market_data_coordinator import MarketDataCoordinator

logger = get_logger("DataFetcher")

# ---------------------------------------------------------------------------
# get_price 返回契约 (Step3 WS-A 预注册裁决 D1, 冻结勿改)
# ---------------------------------------------------------------------------
# 湖日线 schema 实测锚点 (data/lake/quotes/daily/*.parquet):
#   列序 = date/open/high/low/close/amount/volume/reserved/code (9 列)
#   date dtype = datetime64[ns], 已按 date 升序, 无重复 date
#   量纲: volume = 股 (shares), amount = 元 (CNY) (amount/close≈volume 中位 0.9999)
GET_PRICE_LAKE_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "amount",
    "volume",
    "reserved",
    "code",
]
GET_PRICE_ADJUSTED_COLUMNS = GET_PRICE_LAKE_COLUMNS + ["adj_factor"]

GET_PRICE_RETURN_CONTRACT = {
    "columns": GET_PRICE_LAKE_COLUMNS,
    "adjusted_columns": GET_PRICE_ADJUSTED_COLUMNS,
    "date_dtype": "datetime64[ns]",
    "order": "date ascending",
    "dedup": "date unique (keep last)",
    "empty": "empty DataFrame carrying the contract columns (df.empty is True)",
    "sources": ("lake", "mootdx_local"),
    "volume_unit": "shares",
    "amount_unit": "CNY",
    "adjust": "qfq/hfq -> CorporateActionAdjuster (OHLC only, +adj_factor); "
              "otherwise raw lake prices",
    "anchor": "qfq anchored to the latest lake date (adjust before slicing)",
    "write_back": "never (lake writes belong to data_access_service)",
}

# 量纲锚点 (实测): 湖 volume=股 / amount=元 -> amount/(close*volume) 中位 ≈ 1.0。
# mootdx 本地解包对股票输出 volume=手 (amount 仍为元 -> 比值 ≈ 100), 对 ETF 又输出
# 股 (比值 ≈ 1) — compat 系数跨资产类不一致。故按 amount/close 自校准, 只有比值明确
# 落在 "手" 区间时才 x100; 其余 (含 amount 缺失/为 0) 一律保持原样。
LOCAL_VOLUME_HAND_RATIO_RANGE = (60.0, 160.0)
LOCAL_VOLUME_HAND_FACTOR = 100.0


def lake_candidate_symbols(symbol: str) -> list[str]:
    """湖读取候选符号: 带市场后缀原样优先, 裸代码按板块推断后缀展开。

    裸代码 (如 '600519') 直接 read_data 会 miss 湖文件 (湖按 '600519.SH' 存),
    不解析就会错误地滑进本地兜底。推断顺序: 6/9->SH, 0/2/3->SZ, 4/8->BJ。
    """
    sym = str(symbol)
    if "." in sym or not sym.isdigit():
        return [sym]
    if sym.startswith(("6", "9")):
        order = (".SH", ".SZ", ".BJ")
    elif sym.startswith(("0", "2", "3")):
        order = (".SZ", ".SH", ".BJ")
    elif sym.startswith(("4", "8")):
        order = (".BJ", ".SH", ".SZ")
    else:
        order = (".SH", ".SZ", ".BJ")
    return [sym] + [f"{sym}{suffix}" for suffix in order]


def harmonize_local_volume_unit(df: pd.DataFrame) -> pd.DataFrame:
    """本地兜底源 volume 量纲对齐湖契约 (股), 依据 amount/close 自校准。

    Args:
        df: 本地 mootdx 解包得到的日线帧 (含 close/volume/amount)。

    Returns:
        volume 已对齐为股的帧 (比值不在手区间时原样返回, 不改 amount)。
    """
    if df is None or df.empty:
        return df
    required = {"amount", "close", "volume"}
    if not required.issubset(df.columns):
        return df
    valid = df[(df["close"] > 0) & (df["volume"] > 0) & (df["amount"] > 0)]
    if len(valid) < 5:
        return df
    ratio = float((valid["amount"] / (valid["close"] * valid["volume"])).median())
    low, high = LOCAL_VOLUME_HAND_RATIO_RANGE
    if low <= ratio <= high:
        out = df.copy()
        out["volume"] = out["volume"] * LOCAL_VOLUME_HAND_FACTOR
        logger.info(
            f"本地兜底 volume 量纲 手->股 校正: amount/(close*vol)={ratio:.4f}, "
            f"rows={len(out)}"
        )
        return out
    return df


FETCHER_INIT_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

MARKET_CAP_RECOVERABLE_ERRORS = (
    AttributeError,
    DataFetchError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class DataFetcher:
    """
    数据获取器 - 系统的大脑和总指挥
    根据 datapipeline.md 架构设计实现
    """

    def __init__(
        self,
        data_dir: str = "./data",
        storage_manager: Optional[StorageManager] = None,
        pipeline: Optional[DataPipelineService] = None,
    ):
        logger.info("初始化 DataFetcher - 系统的大脑和总指挥")

        self.storage_manager = (
            storage_manager if storage_manager is not None else StorageManager(data_dir)
        )
        data_dir = str(self.storage_manager.data_dir)

        # 湖优先单源 (裁决 D1): 只挂本地 mootdx 解包源; 构造容错, 单源失败不阻塞
        self.mootdx_local_source: Optional[MootdxLocalSource] = None
        self.data_sources = []
        try:
            self.mootdx_local_source = MootdxLocalSource()
            self.data_sources.append(self.mootdx_local_source)
        except FETCHER_INIT_RECOVERABLE_ERRORS as e:
            logger.warning(f"本地数据源 MootdxLocalSource 初始化失败，跳过: {e}")

        self.data_cleaner = DataCleaner()
        self.data_validator = DataValidator()

        # 初始化独立的专门管理器
        self.metadata_manager = StockMetadataManager(data_dir=data_dir)
        self.calendar_manager = TradeCalendarManager(data_dir=data_dir)
        self.market_coordinator = MarketDataCoordinator(self)

        self.pipeline = (
            pipeline
            if pipeline is not None
            else DataPipelineService(data_dir, storage_manager=self.storage_manager)
        )

        self._price_cache: OrderedDict = OrderedDict()
        self._max_cache_size = 5000

        logger.info("DataFetcher 初始化完成")

    def get_price(
        self,
        symbol: str,
        adjust: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """湖优先单源读取日线 (返回契约见模块级 GET_PRICE_RETURN_CONTRACT)。

        数据通道 (裁决 D1): ``StorageManager.read_data`` 读湖 -> 缺失时本地
        ``MootdxLocalSource.fetch_daily`` 兜底 -> 仍缺失返回带合同列的空表
        (不 raise, 兼容旧调用方 "空表=无数据" 契约, 但 logger.warning)。
        **只读**: 绝不回写数据湖 (写湖归 data_access_service)。

        Args:
            symbol: 股票代码, 如 '600519.SH' / '600519'。
            adjust: 复权类型。'qfq'/'hfq' 走 ``CorporateActionAdjuster`` (只调 OHLC、
                volume 不动、新增 adj_factor 列、缺 gbbq 硬失败); 其余值返回湖原始价。
            start_date: 可选起始日期 (含), 读湖整段并复权后切片 (qfq 锚点不受窗口影响)。
            end_date: 可选结束日期 (含)。

        Returns:
            按 ``GET_PRICE_RETURN_CONTRACT`` 冻结的 DataFrame: 列 = 湖 9 列
            (qfq/hfq 时含 adj_factor 共 10 列), date 为 datetime64[ns], 按 date
            升序并按 date 去重 (keep last); 无数据时返回带合同列的空 DataFrame。
        """
        cached = self._get_price_cached(symbol, adjust)
        if cached is not None:
            return self._slice_by_date(cached, start_date, end_date)

        logger.info(f"获取 {symbol} 数据，复权类型: {adjust}")

        raw = self._read_raw_price(symbol, start_date, end_date)
        if raw is None or raw.empty:
            logger.warning(f"未获取到 {symbol} 的数据 (湖与本地 mootdx 均无) — 返回空表")
            return self._empty_price_frame(adjust)

        df = self._normalize_price_frame(raw, symbol)
        if df.empty:
            logger.warning(f"{symbol} 数据清洗后无有效行 — 返回空表")
            return self._empty_price_frame(adjust)

        df = self._apply_adjustment(df, symbol, adjust)
        self._set_price_cache(symbol, adjust, df)
        return self._slice_by_date(df, start_date, end_date)

    def _read_raw_price(
        self, symbol: str, start_date: Optional[str], end_date: Optional[str]
    ) -> Optional[pd.DataFrame]:
        """湖优先读取: 湖 miss 时回退本地 mootdx 解包 (不写湖)。"""
        df = self._read_lake(symbol)
        if df is not None and not df.empty:
            return df
        return self._fetch_local_fallback(symbol, start_date, end_date)

    def _read_lake(self, symbol: str) -> Optional[pd.DataFrame]:
        """按候选符号序列读湖 (裸代码自动补市场后缀), 只读不写。"""
        has_data = getattr(self.storage_manager, "has_data", None)
        for candidate in lake_candidate_symbols(symbol):
            if has_data is not None:
                try:
                    if not has_data(candidate):
                        continue
                except Exception as e:
                    logger.warning(f"检查湖数据存在性失败 {candidate}: {e}")
            try:
                df = self.storage_manager.read_data(candidate, "daily")
            except Exception as e:
                logger.warning(f"读取数据湖失败 {candidate}: {e}")
                continue
            if df is not None and not df.empty:
                if candidate != symbol:
                    logger.info(f"湖数据按候选符号命中: {symbol} -> {candidate}")
                return df
        return None

    def _fetch_local_fallback(
        self, symbol: str, start_date: Optional[str], end_date: Optional[str]
    ) -> Optional[pd.DataFrame]:
        """本地 mootdx 解包兜底 (离线, 不联网, 不回写)。"""
        source = getattr(self, "mootdx_local_source", None)
        if source is None:
            logger.warning(f"本地 mootdx 源不可用，跳过兜底: {symbol}")
            return None
        start = str(start_date) if start_date else "1990-01-01"
        end = (
            str(end_date)
            if end_date
            else get_time_provider().now().strftime("%Y-%m-%d")
        )
        try:
            local = source.fetch_daily(symbol, start, end)
        except Exception as e:
            logger.warning(f"本地 mootdx 兜底读取失败 {symbol}: {e}")
            return None
        # 量纲对齐湖契约: 湖 volume=股, 本地 mootdx 按资产类输出 手/股 混杂
        return harmonize_local_volume_unit(local)

    @staticmethod
    def _normalize_price_frame(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """对齐 GET_PRICE_RETURN_CONTRACT: date 转 datetime64、升序去重、列序冻结。"""
        if "date" not in df.columns:
            logger.warning(f"日线数据缺少 date 列: {symbol}")
            return pd.DataFrame()
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"])
        out = out.sort_values("date", kind="mergesort")
        out = out.drop_duplicates(subset=["date"], keep="last")
        if "code" not in out.columns or out["code"].isna().all():
            out["code"] = symbol
        # 冻结合同列序: 多余列丢弃, 缺失列补 NaN (本地兜底源无 reserved 列)
        out = out.reindex(columns=GET_PRICE_LAKE_COLUMNS)
        return out.reset_index(drop=True)

    @staticmethod
    def _apply_adjustment(df: pd.DataFrame, symbol: str, adjust: str) -> pd.DataFrame:
        """qfq/hfq 走 CorporateActionAdjuster; 其余值按湖原始价返回 (旧契约)。"""
        method = (adjust or "").strip().lower()
        if method in ("qfq", "hfq"):
            return get_corporate_action_adjuster().adjust(
                df, symbol, adjust_type=method
            )
        if method not in ("", "none", "raw"):
            logger.warning(
                f"未知复权类型 {adjust!r}，按不复权返回 (仅 qfq/hfq 触发复权)"
            )
        return df

    @staticmethod
    def _empty_price_frame(adjust: str) -> pd.DataFrame:
        """空数据仍带合同列: 兼容旧 `df.empty` 判断, 同时保证列契约成立。"""
        method = (adjust or "").strip().lower()
        columns = (
            GET_PRICE_ADJUSTED_COLUMNS
            if method in ("qfq", "hfq")
            else GET_PRICE_LAKE_COLUMNS
        )
        return pd.DataFrame(columns=columns)

    @staticmethod
    def _slice_by_date(
        df: pd.DataFrame,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> pd.DataFrame:
        """按 start/end 切片 (含端点); 无边界时原样返回。"""
        if start_date is None and end_date is None:
            return df
        if df.empty or "date" not in df.columns:
            return df
        out = df.copy()
        dates = pd.to_datetime(out["date"])
        mask = pd.Series(True, index=out.index)
        if start_date is not None:
            mask &= dates >= pd.to_datetime(start_date)
        if end_date is not None:
            mask &= dates <= pd.to_datetime(end_date)
        return out[mask].reset_index(drop=True)

    def _get_price_cached(self, symbol: str, adjust: str):
        key = (symbol, adjust)
        if key in self._price_cache:
            self._price_cache.move_to_end(key)
            return self._price_cache[key].copy()
        return None

    def _set_price_cache(self, symbol: str, adjust: str, df):
        key = (symbol, adjust)
        self._price_cache[key] = df.copy()
        while len(self._price_cache) > self._max_cache_size:
            self._price_cache.popitem(last=False)

    def clear_price_cache(
        self,
        symbol: Optional[str] = None,
        adjust: Optional[str] = None,
    ) -> int:
        """Clear in-memory price cache entries by symbol and optional adjust."""
        if symbol is None:
            count = len(self._price_cache)
            self._price_cache.clear()
            return count

        keys_to_delete = [
            key for key in self._price_cache
            if key[0] == symbol and (adjust is None or key[1] == adjust)
        ]
        for key in keys_to_delete:
            del self._price_cache[key]
        return len(keys_to_delete)

    def fetch_stock_daily(self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
        logger.info(f"获取个股日线数据: {symbol}, {start_date} 到 {end_date}")
        # 湖优先读取 + 起止切片直接委托 get_price (默认 qfq 保持不变)
        return self.get_price(
            symbol, adjust, start_date=start_date, end_date=end_date
        )

    def fetch_stock_market_cap(self, symbol: str) -> float:
        for source in self.data_sources:
            try:
                if hasattr(source, "fetch_market_cap"):
                    market_cap = source.fetch_market_cap(symbol)
                    if market_cap > 0:
                        return market_cap
            except MARKET_CAP_RECOVERABLE_ERRORS as e:
                logger.warning(f"获取市值失败 {symbol} from {source.__class__.__name__}: {e}")
        return 0.0

    def fetch_stocks_daily(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        result = {}
        max_workers = min(16, len(symbols)) if symbols else 1
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.fetch_stock_daily, symbol, start_date, end_date): symbol
                for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result[symbol] = future.result()
                except Exception as e:
                    logger.warning(f"获取 {symbol} 数据失败: {e}")
                    result[symbol] = pd.DataFrame()
        
        return result

    def fetch_index_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_index_daily(symbol, start_date, end_date)

    def fetch_etf_daily_robust(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_etf_daily_robust(symbol, start_date, end_date)

    def fetch_industry_concept_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        return self.market_coordinator.fetch_industry_concept_data()

    def fetch_sector_daily(self, sector_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_sector_daily(sector_name, start_date, end_date)

    def fetch_stock_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        logger.info(f"获取实时数据: {symbol}")
        return pd.DataFrame()

    @handle_errors(DataFetchError, DataValidationError, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_history(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        is_index = symbol.startswith(("sh000", "sz399")) or (symbol.startswith("000") and symbol.endswith(".SH"))
        if is_index:
            return self.fetch_index_daily(symbol, start_date, end_date)
        return self.fetch_stock_daily(symbol, start_date, end_date)

    def get_symbols(self):
        return self.storage_manager.get_symbols()

    def fetch_for_brain(self, symbol: str) -> Dict:
        logger.info(f"为大脑获取 {symbol} 数据")
        # 直读湖原始价 (adjust=""), 不经任何网络源
        stock_data = self.get_price(symbol, adjust="")
        return {
            "stock": stock_data,
            "symbol": symbol,
            "timestamp": get_time_provider().now().isoformat(),
        }

    # ---- 委托给 StockMetadataManager 的方法 ----
    def fetch_all_stock_codes(self, force_update: bool = False) -> pd.DataFrame:
        logger.info("获取全量股票代码和名称")
        self.metadata_manager.load()
        codes = []
        names = []
        for code, meta in self.metadata_manager._metadata_cache.items():
            codes.append(code)
            names.append(meta.name)
        if not codes:
            logger.warning("未能通过 MetadataManager 加载股票代码缓存")
            return pd.DataFrame()
        return pd.DataFrame({"代码": codes, "名称": names})

    def fetch_stock_info(self) -> Dict[str, str]:
        logger.info("获取所有股票的基础信息")
        df = self.fetch_all_stock_codes()
        if not df.empty:
            return dict(zip(df["代码"], df["名称"]))
        return {}

    def is_valid_symbol(self, symbol: str) -> bool:
        logger.info(f"验证股票代码 {symbol} 的有效性")
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace("sh", "").replace("sz", "").replace("bj", "").replace(".", "")
        df = self.fetch_all_stock_codes()
        if not df.empty and "代码" in df.columns:
            return clean_symbol in [str(code).strip() for code in df["代码"].astype(str).tolist()]
        return False

    def validate_symbols(self, symbols: list) -> list:
        logger.info(f"开始批量验证 {len(symbols)} 个股票代码")
        return [s for s in symbols if self.is_valid_symbol(s)]
        
    # ---- 委托给 TradeCalendarManager 的方法 ----
    def generate_trade_calendar(self, year: int, force_update: bool = False) -> pd.DataFrame:
        return self.calendar_manager.generate_trade_calendar(year, force_update)

    def is_trading_day(self, date: datetime) -> bool:
        return self.calendar_manager.is_trading_day(date)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self.calendar_manager.get_trade_calendar(start_date, end_date)


class LegacyDataFetcher(DataFetcher):
    """
    传统数据获取器（保持原有行为）
    """
    def __init__(self) -> None:
        super().__init__()

def create_fetcher(data_dir: str = "./data") -> DataFetcher:
    return DataFetcher(data_dir)
