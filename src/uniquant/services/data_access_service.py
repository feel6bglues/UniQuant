from typing import Any, Optional

import pandas as pd

from ..shared.exceptions import CacheError, DataFetchError
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)

# R2 污染通道护栏 (DATA_SOURCE_MIGRATION_PLAN §5 Step 0): 湖为不复权 raw SSOT,
# 复权结果 (adjust="qfq"/"hfq") 或带复权因子列的数据禁止写入 data/lake/**。
# 本文件全部 write_data 调用点 (fetch_and_save_dataset / load_data_with_fallback /
# load_etf_data) 均须先过 _assert_unadjusted_for_lake, raw 语义显式传 adjust=""。
_ADJUSTED_FACTOR_COLUMNS = ("adj_factor", "qfq_factor", "hfq_factor")

#: 模块级护栏事件记录, 供测试/验收断言: blocked_count=累计拦截次数,
#: last_blocked=最近一次拦截 {symbol, adjust, columns}。
LAKE_WRITE_GUARD_STATS: dict[str, Any] = {"blocked_count": 0, "last_blocked": None}


class DataAccessService:
    """Coordinates cache/source/lake reads and persistence for DataService."""

    def __init__(self, service: Any):
        self.service = service

    def fetch_data(
        self, symbol: str, start_date: str, end_date: str, use_cache: bool = True
    ) -> Optional[pd.DataFrame]:
        cache_key = self.service._get_cache_key("data", symbol, start_date, end_date)

        if use_cache:
            cached = self.fetch_from_cache(cache_key, symbol)
            if cached is not None:
                return self.service._clone_dataframe(cached)

        source_data = self.fetch_from_source(
            symbol, start_date, end_date, cache_key, use_cache
        )
        if source_data is not None:
            return self.service._clone_dataframe(source_data)

        return self.service._clone_dataframe(
            self.fetch_from_lake(symbol, start_date, end_date)
        )

    def fetch_from_cache(self, cache_key: str, symbol: str) -> Optional[pd.DataFrame]:
        try:
            cached = self.service._get_cached(cache_key)
            if cached is not None:
                logger.debug("从缓存获取 %s 数据", symbol)
                return self.service._clone_dataframe(cached)
        except (CacheError, Exception) as exc:
            logger.warning("缓存读取失败，降级到数据源: %s", exc)
        return None

    def fetch_from_source(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        cache_key: str,
        use_cache: bool,
    ) -> Optional[pd.DataFrame]:
        """从数据源取数并按日期过滤, 命中后回填缓存.

        语义 (Step3: adjust 显式化（预注册§8 #13）): 显式 ``adjust=""`` —— 湖是
        不复权 raw SSOT, 研究/展示统一原始价; ``fetch_stock_daily`` 默认
        ``adjust="qfq"`` 不得在此被隐式继承 (否则"缓存=前复权 / 湖=原始价"分叉)。
        健康探针 ``health_service._check_data_service_health`` 依赖本链 (§8 #13),
        其断言仅为"取数非 None", 显式 raw 不改变探针语义。
        """
        try:
            df = None
            if hasattr(self.service.fetcher, "fetch_stock_daily"):
                # Step3: adjust 显式化（预注册§8 #13）— 显式原始价, 禁止继承 qfq 默认
                df = self.service.fetcher.fetch_stock_daily(
                    symbol, start_date, end_date, adjust=""
                )

            if df is None or df.empty:
                df = self._fetch_and_filter_price(symbol, start_date, end_date)

            if df is not None and not df.empty:
                if use_cache:
                    try:
                        self.service._set_cache(cache_key, self.service._clone_dataframe(df))
                    except (CacheError, Exception) as exc:
                        logger.warning("缓存写入失败: %s", exc)
                return self.service._clone_dataframe(df)
        except (DataFetchError, Exception) as exc:
            logger.warning("数据源获取失败: %s", exc)
        return None

    def fetch_from_lake(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        try:
            logger.info("尝试从数据湖读取 %s", symbol)
            df = self.service.lake.read_data(symbol, data_type="stock", market="cn")
            if df is not None and not df.empty:
                return self._filter_by_date(df, start_date, end_date)
        except Exception as exc:
            logger.error("数据湖读取也失败: %s", exc)
        logger.error("无法获取 %s 的数据", symbol)
        return None

    def fetch_and_save_dataset(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        *,
        data_type: str,
    ) -> Optional[pd.DataFrame]:
        """取数 → 清洗 → 写湖 → 回读 (迁移表 #14 标记的最危险回写入口).

        语义 (Step3: adjust 显式化（预注册§8 #14）): 取数一律显式 ``adjust=""``
        (湖为不复权 raw SSOT), 写湖前必须先过 ``_assert_unadjusted_for_lake``。
        """
        try:
            if data_type == "stock" and hasattr(self.service.fetcher, "fetch_stock_daily"):
                # Step3: adjust 显式化（预注册§8 #14）— 显式原始价, 禁止继承 qfq 默认
                df = self.service.fetcher.fetch_stock_daily(
                    symbol, start_date, end_date, adjust=""
                )
                if df is None or df.empty:
                    df = self._fetch_and_filter_price(symbol, start_date, end_date)
            elif data_type == "index" and hasattr(self.service.fetcher, "fetch_index_daily"):
                df = self.service.fetcher.fetch_index_daily(symbol, start_date, end_date)
                if df is None or df.empty:
                    df = self._fetch_and_filter_index(symbol, start_date, end_date)
            elif data_type == "index":
                df = self._fetch_and_filter_index(symbol, start_date, end_date)
            else:
                df = self._fetch_and_filter_price(symbol, start_date, end_date)

            if df is None or df.empty:
                logger.warning("No data fetched for %s %s", data_type, symbol)
                return None
        except Exception as exc:
            logger.error("Error fetching %s data: %s", data_type, exc)
            return None

        cleaned_df = self.service.cleaner.clean_stock_daily(df)
        # Step3: adjust 显式化（预注册§8 #14）+ 写湖断言 — 该路径取数显式
        # adjust="" (见上), 故此处以 adjust="" 过 R2 护栏并放行; **写入前必须已过
        # _assert_unadjusted_for_lake** (禁止绕过), 上游若悄悄改成复权则被拦。
        if self._assert_unadjusted_for_lake(cleaned_df, adjust="", symbol=symbol):
            self.service.lake.write_data(
                symbol, cleaned_df, data_type=data_type, market="cn", overwrite=True
            )
        else:
            logger.warning(
                "Skip lake write for %s %s (unadjusted-data guard)", data_type, symbol
            )
        return self.service.lake.read_data(symbol, data_type=data_type, market="cn")

    def get_from_lake(self, symbol: str, data_type: str) -> Optional[pd.DataFrame]:
        df = self.service.lake.read_data(symbol, data_type=data_type, market="cn")
        if not df.empty:
            logger.info("Loaded %s %s from data lake", data_type, symbol)
            return self.service._clone_dataframe(df)
        logger.warning("No data for %s %s in data lake", data_type, symbol)
        return None

    def _assert_unadjusted_for_lake(
        self, df: pd.DataFrame, adjust: str, symbol: str
    ) -> bool:
        """写湖前硬断言: 仅不复权数据允许写入 data/lake/** (R2 污染通道护栏)。

        规则:
            R-a ``adjust`` 非空 (qfq/hfq/任意复权语义) → 拦截, 即便 df 无因子列;
            R-b df 含 ``adj_factor``/``qfq_factor``/``hfq_factor`` 任一列 → 拦截;
            R-c 走"复权语义"的写入必须带 ``adj_factor`` 列 (供事后对账),
                缺列即拦 — 报文明确提示"复权输出必须带 adj_factor 列且禁止写湖"。
                旧轨 qfq 会改 volume 却不留因子列 (列白名单盲区), 无法从 df 验证
                volume 是否为 raw, 故凡 ``adjust`` 非空一律按 R-a/R-c 拦截。

        Returns:
            True=允许写湖; False=复权数据, logger.error + 记录模块级事件并跳过写入。
        """
        offending = [c for c in df.columns if c in _ADJUSTED_FACTOR_COLUMNS]
        adjust_declared = bool((adjust or "").strip())
        if not adjust_declared and not offending:
            return True

        rules = [rule for rule, hit in (
            ("R-a", adjust_declared),
            ("R-b", bool(offending)),
            ("R-c", adjust_declared),
        ) if hit]
        LAKE_WRITE_GUARD_STATS["blocked_count"] += 1
        LAKE_WRITE_GUARD_STATS["last_blocked"] = {
            "symbol": symbol,
            "adjust": adjust,
            "columns": offending,
            "rules": rules,
        }
        logger.error(
            "复权数据禁写湖 (R2 护栏 %s): symbol=%s adjust=%r factor_columns=%s — "
            "复权输出必须带 adj_factor 列且禁止写湖",
            "+".join(rules),
            symbol,
            adjust,
            offending,
        )
        return False

    def load_data_with_fallback(
        self, symbol: str, data_type: str, description: str
    ) -> pd.DataFrame:
        try:
            data = self.service.lake.read_data(symbol, data_type=data_type, market="cn")
            if data is not None and not data.empty:
                logger.info("Loaded %s from data lake", description)
                return self.service._clone_dataframe(data)

            if data_type == "index":
                clean_symbol = symbol.replace("sh", "").replace("sz", "").upper()
                for suffix in [".SH", ".SZ", ""]:
                    test_symbol = f"{clean_symbol}{suffix}" if suffix else clean_symbol
                    data = self.service.lake.read_data(
                        test_symbol, data_type=data_type, market="cn"
                    )
                    if data is not None and not data.empty:
                        logger.info(
                            "Loaded %s from data lake (symbol: %s)",
                            description,
                            test_symbol,
                        )
                        return self.service._clone_dataframe(data)

            logger.warning("No %s in data lake, falling back to data source", description)
            # Step3: adjust 显式化（预注册§8 #9）— 湖 miss → 源取数: stock 显式走
            # qfq (研究/展示口径), index 显式原始价; qfq 结果**只返回不写湖**
            # (湖为不复权 raw SSOT, 复权数据落湖 = R2 污染通道)。
            adjust = "" if data_type == "index" else "qfq"
            data = self.service.fetcher.get_price(symbol, adjust=adjust)
            if data is None or data.empty:
                logger.warning("Failed to fetch %s from data source", description)
                return pd.DataFrame()

            cleaned_data = self.service.cleaner.clean_stock_daily(data)
            if cleaned_data.empty:
                logger.warning("Cleaned %s is empty", description)
                return pd.DataFrame()

            # 写湖必须过 R2 护栏 (保留现有接线): qfq → R-a 拦截且只返回不写湖;
            # raw 且通过 cleaner 校验 → 放行写入。
            if self._assert_unadjusted_for_lake(cleaned_data, adjust, symbol):
                self.service.lake.write_data(
                    symbol,
                    cleaned_data,
                    data_type=data_type,
                    market="cn",
                    overwrite=True,
                )
                logger.info("Fetched and saved %s from data source", description)
            elif adjust:
                # Step3: adjust 显式化（预注册§8 #9）— qfq 分支只返回不写湖
                logger.info(
                    "Skip lake write for %s (adjust=%r): qfq 只返回不写湖",
                    description,
                    adjust,
                )
            else:
                logger.warning(
                    "Skip lake write for %s (unadjusted-data guard)", description
                )
            return self.service._clone_dataframe(cleaned_data)
        except Exception as exc:
            logger.error("Error loading %s: %s", description, exc)
            return pd.DataFrame()

    def load_etf_data(self) -> pd.DataFrame:
        try:
            for symbol in ["510300", "510300.SH"]:
                etf_data = self.service.lake.read_data(symbol, data_type="stock", market="cn")
                if etf_data is not None and not etf_data.empty:
                    logger.info("Loaded ETF data (%s) from data lake", symbol)
                    return self.service._clone_dataframe(etf_data)

            logger.warning("No ETF data (510300) in data lake, falling back to data source")
            # Step3: adjust 显式化（预注册§8 #10）— ETF 读湖原始价, 源兜底同样显式
            # adjust="" (湖是不复权 raw SSOT, 禁止继承任何复权默认值)。
            etf_data = self.service.fetcher.get_price("510300", adjust="")
            if etf_data is None or etf_data.empty:
                logger.warning("Failed to fetch ETF data from data source")
                return pd.DataFrame()

            cleaned_data = self.service.cleaner.clean_stock_daily(etf_data)
            if cleaned_data.empty:
                logger.warning("Cleaned ETF data is empty")
                return pd.DataFrame()

            # Step3: adjust 显式化（预注册§8 #10）— 写湖过 R2 护栏: 显式 raw → 放行;
            # 若上游返回带复权因子列的 df 则被拦, 读数行为不变。
            if self._assert_unadjusted_for_lake(
                cleaned_data, adjust="", symbol="510300"
            ):
                self.service.lake.write_data(
                    "510300",
                    cleaned_data,
                    data_type="stock",
                    market="cn",
                    overwrite=True,
                )
                logger.info("Fetched and saved ETF data (510300) from data source")
            else:
                logger.warning(
                    "Skip lake write for ETF 510300 (unadjusted-data guard)"
                )
            return self.service._clone_dataframe(cleaned_data)
        except Exception as exc:
            logger.error("Error loading ETF data: %s", exc)
            return pd.DataFrame()

    def _fetch_and_filter_price(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """个股取数并按日期过滤 (Step3: adjust 显式化（预注册§8 #11）).

        语义: 显式 ``adjust=""`` —— 湖是不复权的, 研究/展示统一原始价; 此前
        ``get_price(symbol)`` 未传 adjust, 会继承 qfq 默认 (断链期从未真正生效,
        Step3 打通后会把前复权价混入 raw 口径)。
        """
        # Step3: adjust 显式化（预注册§8 #11）— 个股路径 = 原始价
        df = self.service.fetcher.get_price(symbol, adjust="")
        if df is None or df.empty:
            return None
        return self._filter_by_date(df, start_date, end_date)

    def _fetch_and_filter_index(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """指数取数并按日期过滤 (Step3: adjust 显式化（预注册§8 #12）— 保持显式 raw)."""
        # Step3: adjust 显式化（预注册§8 #12）— 指数不复权, 保持 adjust=""
        df = self.service.fetcher.get_price(symbol, adjust="")
        if df is None or df.empty:
            return None
        return self._filter_by_date(df, start_date, end_date)

    @staticmethod
    def _filter_by_date(
        df: pd.DataFrame, start_date: str, end_date: str
    ) -> pd.DataFrame:
        filtered = df.copy()
        if "date" in filtered.columns:
            filtered["date"] = pd.to_datetime(filtered["date"])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            filtered = filtered[(filtered["date"] >= start) & (filtered["date"] <= end)]
        return filtered
