"""测试 DataFetcher 初始化容错 (Step3 WS-A 湖优先单源语义).

核心目标 (预注册裁决 D1 后的新语义):
1. 初始化只挂一个本地源 (MootdxLocalSource), 不再挂 5 个爬虫源
2. 单源构造失败时 DataFetcher 仍可创建 (构造容错)
3. 模块级不再导入/暴露 Sina/Ths/Tencent/Baostock/Tdx 爬虫源
4. fetch_stock_market_cap 的可恢复错误不中断整体查询
5. get_price 不经 source_router (湖优先), 只读不写
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from uniquant.shared.exceptions import DataFetchError


class TestDataFetcherInitFaultTolerance:
    """DataFetcher 初始化容错测试 (单源 + 湖优先)"""

    # ------------------------------------------------------------------ #
    #  测试 1：正常初始化 — 单一本地源
    # ------------------------------------------------------------------ #
    def test_normal_init_single_local_source(self):
        """正常初始化时，仅挂 MootdxLocalSource 一个源（爬虫源已下线）。"""
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_data_fetcher_single")

        assert fetcher is not None
        assert len(fetcher.data_sources) == 1
        assert type(fetcher.data_sources[0]).__name__ == "MootdxLocalSource"
        assert fetcher.mootdx_local_source is fetcher.data_sources[0]
        # SourceRouter 只剩本地源适配器 (保留给 stock_data_updater 兼容路径)
        assert len(fetcher.source_router.adapters) == 1

    # ------------------------------------------------------------------ #
    #  测试 2：本地源初始化失败 — DataFetcher 仍可创建
    # ------------------------------------------------------------------ #
    def test_local_source_init_failure_still_creates_fetcher(self):
        """MootdxLocalSource 构造失败时，DataFetcher 不应崩溃（空源列表）。"""
        from uniquant.data.data_fetcher import DataFetcher

        with patch(
            "uniquant.data.data_fetcher.MootdxLocalSource",
            side_effect=ImportError("mootdx dependency missing"),
        ):
            fetcher = DataFetcher(data_dir="/tmp/test_data_fetcher_local_fail")

        assert fetcher is not None
        assert fetcher.data_sources == []
        assert fetcher.mootdx_local_source is None
        assert isinstance(fetcher.source_router.adapters, list)
        assert fetcher.source_router.adapters == []

    # ------------------------------------------------------------------ #
    #  测试 3：爬虫源已从模块移除
    # ------------------------------------------------------------------ #
    def test_crawler_sources_removed_from_module(self):
        """模块级不再导入 5 个爬虫源名字（防止重新激活网络源）。"""
        import uniquant.data.data_fetcher as mod

        for crawler in (
            "SinaSource",
            "ThsSource",
            "TencentSource",
            "BaostockSource",
            "TdxSource",
        ):
            assert not hasattr(mod, crawler), f"{crawler} 应已从 data_fetcher 移除"

        # 本地兜底源仍以模块级名字暴露 (测试可 patch)
        assert hasattr(mod, "MootdxLocalSource")

    # ------------------------------------------------------------------ #
    #  测试 4：单个源 fetch_market_cap 失败时，其他源仍可继续
    # ------------------------------------------------------------------ #
    def test_fetch_stock_market_cap_skips_recoverable_source_errors(self):
        """fetch_market_cap 的可恢复错误不应中断整体查询。"""
        from uniquant.data.data_fetcher import DataFetcher

        failing_source = MagicMock()
        failing_source.fetch_market_cap.side_effect = DataFetchError(
            "market cap unavailable"
        )

        good_source = MagicMock()
        good_source.fetch_market_cap.return_value = 123.45

        fetcher = DataFetcher(data_dir="/tmp/test_market_cap")
        fetcher.data_sources = [failing_source, good_source]

        assert fetcher.fetch_stock_market_cap("000001.SZ") == 123.45

    # ------------------------------------------------------------------ #
    #  测试 5：get_price 湖优先 — 不经 source_router，只读湖
    # ------------------------------------------------------------------ #
    def test_get_price_reads_lake_and_bypasses_source_router(self):
        """get_price 应读湖 + 调用本地兜底，绝不触碰 source_router 抓取链。"""
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_df_lake_first")
        lake_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "open": [10.0, 10.5],
                "high": [10.8, 11.0],
                "low": [9.8, 10.2],
                "close": [10.2, 10.7],
                "amount": [10200.0, 10700.0],
                "volume": [1000, 2000],
                "reserved": [0, 0],
                "code": ["000001.SZ", "000001.SZ"],
            }
        )
        fetcher.storage_manager.write_data("000001.SZ", lake_df, data_type="daily")
        fetcher.clear_price_cache()

        spy_router_fetch = MagicMock()
        spy_router_fallback = MagicMock()
        fetcher.source_router.fetch_data = spy_router_fetch
        fetcher.source_router.fetch_with_fallback = spy_router_fallback
        spy_read_data = MagicMock(wraps=fetcher.storage_manager.read_data)
        fetcher.storage_manager.read_data = spy_read_data

        result = fetcher.get_price("000001.SZ")

        assert not result.empty
        spy_read_data.assert_called_with("000001.SZ", "daily")
        spy_router_fetch.assert_not_called()
        spy_router_fallback.assert_not_called()

        # 只读契约: get_price 不回写数据湖
        spy_write = MagicMock()
        fetcher.storage_manager.write_data = spy_write
        fetcher.get_price("000001.SZ")
        spy_write.assert_not_called()
