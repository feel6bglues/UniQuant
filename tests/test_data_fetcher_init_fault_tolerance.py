"""
测试 DataFetcher 初始化容错

核心目标：
1. 验证单个数据源初始化失败时，DataFetcher 不会崩溃
2. 验证所有数据源初始化失败时，DataFetcher 仍能创建（但无可用源）
3. 验证成功初始化的数据源仍可用
"""

from unittest.mock import patch, MagicMock

from uniquant.shared.exceptions import DataFetchError


class TestDataFetcherInitFaultTolerance:
    """DataFetcher 初始化容错测试"""

    # ------------------------------------------------------------------ #
    #  测试 1：SinaSource 初始化失败 — 其他源仍可用
    # ------------------------------------------------------------------ #
    def test_sina_source_init_failure_does_not_crash(self):
        """SinaSource 初始化失败时，DataFetcher 不应崩溃。"""
        from uniquant.data.data_fetcher import DataFetcher

        def raise_sina_error(*args, **kwargs):
            raise ImportError("sina dependency missing")

        with patch("uniquant.data.data_fetcher.SinaSource", side_effect=raise_sina_error):
            with patch("uniquant.data.data_fetcher.TencentSource", side_effect=ImportError("tencent missing")):
                # 应不抛异常，跳过失败的源
                fetcher = DataFetcher(data_dir="/tmp/test_data_fetcher")

        assert fetcher is not None
        # 至少应有 3 个可用源（Tdx, Baostock, Ths）
        assert len(fetcher.data_sources) >= 3

    # ------------------------------------------------------------------ #
    #  测试 2：所有数据源初始化失败 — DataFetcher 仍可创建
    # ------------------------------------------------------------------ #
    def test_all_sources_fail_still_creates_fetcher(self):
        """所有数据源初始化失败时，DataFetcher 仍可创建（空源列表）。"""
        from uniquant.data.data_fetcher import DataFetcher

        def raise_error(*args, **kwargs):
            raise ImportError("dependency missing")

        with patch("uniquant.data.data_fetcher.TdxSource", side_effect=raise_error):
            with patch("uniquant.data.data_fetcher.BaostockSource", side_effect=raise_error):
                with patch("uniquant.data.data_fetcher.SinaSource", side_effect=raise_error):
                    with patch("uniquant.data.data_fetcher.ThsSource", side_effect=raise_error):
                        with patch("uniquant.data.data_fetcher.TencentSource", side_effect=raise_error):
                            fetcher = DataFetcher(data_dir="/tmp/test_data_fetcher_all_fail")

        assert fetcher is not None
        # 源列表可能为空或部分可用
        assert isinstance(fetcher.data_sources, list)

    # ------------------------------------------------------------------ #
    #  测试 3：正常初始化 — 所有源可用
    # ------------------------------------------------------------------ #
    def test_normal_init_all_sources_available(self):
        """正常初始化时，应有 5 个数据源。"""
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_data_fetcher_normal")

        assert fetcher is not None
        assert len(fetcher.data_sources) == 5

    # ------------------------------------------------------------------ #
    #  测试 4：SourceRouter 初始化 — 空适配器列表
    # ------------------------------------------------------------------ #
    def test_source_router_with_empty_adapters(self):
        """SourceRouter 应能处理空适配器列表。"""
        from uniquant.data.managers.source_router import SourceRouter

        router = SourceRouter([])

        assert router is not None
        assert len(router.adapters) == 0
        # fetch_data 应返回空 DataFrame 而非崩溃
        df = router.fetch_data("000001.SZ", "2024-01-01")
        assert df.empty

    # ------------------------------------------------------------------ #
    #  测试 5：单个源 fetch_market_cap 失败时，其他源仍可继续
    # ------------------------------------------------------------------ #
    def test_fetch_stock_market_cap_skips_recoverable_source_errors(self):
        """fetch_market_cap 的可恢复错误不应中断整体查询。"""
        from uniquant.data.data_fetcher import DataFetcher

        failing_source = MagicMock()
        failing_source.fetch_market_cap.side_effect = DataFetchError("market cap unavailable")

        good_source = MagicMock()
        good_source.fetch_market_cap.return_value = 123.45

        fetcher = DataFetcher(data_dir="/tmp/test_market_cap")
        fetcher.data_sources = [failing_source, good_source]

        assert fetcher.fetch_stock_market_cap("000001.SZ") == 123.45
