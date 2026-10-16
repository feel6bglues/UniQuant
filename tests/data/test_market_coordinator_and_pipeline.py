"""``data/managers/market_data_coordinator.py`` + ``data/data_pipeline_service.py`` 测试.

两者都在**生产链路**上:

* ``MarketDataCoordinator`` 是 ``DataFetcher`` 的市场级数据代理 ——
  ``fetch_index_daily`` 被 ``data_access_service``(data_type=="index")、
  ``macro_service``、``macro_analysis_engine`` 消费; ``fetch_sector_daily``
  被 ``data_service`` 消费。指数/板块不在数据湖内, 故此处为 **akshare 实盘兜底**。
* ``DataPipelineService`` 是清洗 → 校验 → 单轨复权 (``CorporateActionAdjuster``)
  的编排入口。

纪律: akshare 与复权器全部 mock, 不触网、不读写真实 ``data/``。
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.data_pipeline_service import DataPipelineService
from uniquant.data.managers.market_data_coordinator import MarketDataCoordinator


# ════════════════════════════════════════════════════════════════════════════
# MarketDataCoordinator
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_ak(monkeypatch):
    """替换模块级 ``akshare_wrapper`` 单例里的 index 方法。"""
    import uniquant.data.utils.akshare_wrapper as aw

    wrapper = MagicMock()
    monkeypatch.setattr(aw, "akshare_wrapper", wrapper)
    return wrapper


class TestMarketDataCoordinatorInit:
    def test_stores_fetcher(self):
        fetcher = MagicMock()
        assert MarketDataCoordinator(fetcher).data_fetcher is fetcher


class TestFetchIndexDaily:
    def _coord(self, fake_ak, df):
        fake_ak.fetch_index_daily.return_value = df
        return MarketDataCoordinator(MagicMock())

    def test_none_payload_returns_empty(self, fake_ak):
        coord = self._coord(fake_ak, None)
        assert coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31").empty

    def test_empty_payload_returns_empty(self, fake_ak):
        coord = self._coord(fake_ak, pd.DataFrame())
        assert coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31").empty

    def test_window_filter_is_inclusive(self, fake_ak):
        coord = self._coord(
            fake_ak,
            pd.DataFrame(
                {
                    "date": ["2023-12-29", "2024-01-02", "2024-06-28", "2025-01-02"],
                    "close": [1.0, 2.0, 3.0, 4.0],
                }
            ),
        )
        out = coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
        assert list(out["close"]) == [2.0, 3.0]
        assert out["date"].dtype.kind == "M"        # 已转 datetime64

    def test_no_date_column_is_returned_unfiltered(self, fake_ak):
        coord = self._coord(fake_ak, pd.DataFrame({"close": [1.0, 2.0]}))
        out = coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
        assert len(out) == 2

    def test_renames_chinese_volume_only(self, fake_ak):
        coord = self._coord(
            fake_ak,
            pd.DataFrame({"date": ["2024-01-02"], "成交量": [100.0], "close": [1.0]}),
        )
        out = coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
        assert "volume" in out.columns and "成交量" not in out.columns

    def test_renames_chinese_ohlc_when_open_absent(self, fake_ak):
        coord = self._coord(
            fake_ak,
            pd.DataFrame(
                {
                    "date": ["2024-01-02"],
                    "开盘": [1.0], "收盘": [2.0], "最高": [3.0], "最低": [0.5],
                }
            ),
        )
        out = coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
        assert {"open", "close", "high", "low"} <= set(out.columns)

    def test_english_columns_not_renamed(self, fake_ak):
        coord = self._coord(
            fake_ak,
            pd.DataFrame({"date": ["2024-01-02"], "open": [1.0], "volume": [10.0]}),
        )
        out = coord.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
        assert "volume" in out.columns
        assert out["volume"].iloc[0] == 10.0


class TestFetchEtfDailyRobust:
    def test_delegates_with_explicit_empty_adjust(self):
        """ETF/指数不复权 —— 必须显式传 adjust="" 而非继承 fetch_stock_daily 的 qfq 默认。"""
        fetcher = MagicMock()
        fetcher.fetch_stock_daily.return_value = pd.DataFrame({"close": [1.0]})
        coord = MarketDataCoordinator(fetcher)
        out = coord.fetch_etf_daily_robust("510300.SH", "2024-01-01", "2024-02-01")
        assert len(out) == 1
        assert fetcher.fetch_stock_daily.call_args == (
            ("510300.SH", "2024-01-01", "2024-02-01"),
            {"adjust": ""},
        )


class TestFetchIndustryConceptData:
    def test_returns_two_empty_frames(self):
        a, b = MarketDataCoordinator(MagicMock()).fetch_industry_concept_data()
        assert a.empty and b.empty


class TestFetchSectorDaily:
    @pytest.mark.parametrize(
        "sector,code",
        [
            ("金融", "000038.SH"),
            ("医药", "000037.SH"),
            ("信息技术", "000039.SH"),
            ("沪深300金融", "000914.SH"),
            ("沪深300公用事业", "000917.SH"),
        ],
    )
    def test_known_sector_maps_to_index(self, monkeypatch, sector, code):
        coord = MarketDataCoordinator(MagicMock())
        coord.fetch_index_daily = MagicMock(return_value=pd.DataFrame({"close": [1.0]}))
        out = coord.fetch_sector_daily(sector, "2024-01-01", "2024-12-31")
        assert len(out) == 1
        assert coord.fetch_index_daily.call_args[0][0] == code

    def test_unknown_sector_returns_empty(self, monkeypatch):
        coord = MarketDataCoordinator(MagicMock())
        coord.fetch_index_daily = MagicMock()
        assert coord.fetch_sector_daily("不存在的板块", "2024-01-01", "2024-12-31").empty
        coord.fetch_index_daily.assert_not_called()

    def test_alias_sectors_share_a_code(self):
        """'金融' 与 '金融地产' 指向同一指数 (别名, 非重复项)。"""
        coord = MarketDataCoordinator(MagicMock())
        coord.fetch_index_daily = MagicMock(return_value=pd.DataFrame())
        coord.fetch_sector_daily("金融", "2024-01-01", "2024-12-31")
        first = coord.fetch_index_daily.call_args[0][0]
        coord.fetch_sector_daily("金融地产", "2024-01-01", "2024-12-31")
        assert coord.fetch_index_daily.call_args[0][0] == first


# ════════════════════════════════════════════════════════════════════════════
# DataPipelineService
# ════════════════════════════════════════════════════════════════════════════


def _clean_frame(n: int = 3) -> pd.DataFrame:
    """构造能通过 ``DataValidator`` 的合法帧 (涨跌均在限内、无 NaN、High≥Open/Close)。"""
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    close = [10.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "code": ["600519.SH"] * n,
            "open": [c - 0.05 for c in close],
            "high": [c + 0.2 for c in close],
            "low": [c - 0.2 for c in close],
            "close": close,
            "volume": [100.0] * n,
            "amount": [1000.0] * n,
        }
    )


@pytest.fixture
def service():
    """注入 stub storage_manager, 避免真实 data/ 主数据表依赖。"""
    return DataPipelineService(data_dir="/nonexistent", storage_manager=MagicMock())


class TestDataPipelineServiceInit:
    def test_uses_injected_storage_manager(self, service):
        assert service.storage_manager is not None
        assert service.cleaner is not None
        assert service.validator is not None
        assert service.adjuster is not None

    def test_wires_single_track_adjuster(self, service):
        from uniquant.data.corporate_action import CorporateActionAdjuster

        assert isinstance(service.adjuster, CorporateActionAdjuster)


class TestProcess:
    def test_validation_failure_skips_adjustment(self, service):
        """门禁不过 → 原样返回清洗结果, 绝不进入复权 (QTR-OS §4.3 只读门禁)。"""
        service.validator.validate = MagicMock(return_value=False)
        service.adjuster.adjust = MagicMock()
        frame = _clean_frame()
        out = service.process(frame, "600519.SH", adjust="qfq")
        service.adjuster.adjust.assert_not_called()
        service.validator.validate.assert_called_once()
        assert "adj_factor" not in out.columns
        assert len(out) == len(frame)

    def test_cleaner_runs_before_validator(self, service):
        """清洗修复必须发生在门禁之前 —— 否则 High<Low 的原始帧会被误拒。"""
        order = []
        service.cleaner.clean_stock_daily = MagicMock(
            side_effect=lambda df: (order.append("clean"), df)[1]
        )
        service.validator.validate = MagicMock(
            side_effect=lambda df: (order.append("validate"), True)[1]
        )
        service.adjuster.adjust = MagicMock(side_effect=lambda df, s, adjust_type: df)
        service.process(_clean_frame(), "600519.SH", adjust="qfq")
        assert order == ["clean", "validate"]

    @pytest.mark.parametrize("adjust", ["", "none", "raw", "weird"])
    def test_invalid_adjust_returns_unadjusted(self, service, adjust):
        service.adjuster.adjust = MagicMock()
        out = service.process(_clean_frame(), "600519.SH", adjust=adjust)
        service.adjuster.adjust.assert_not_called()
        assert "adj_factor" not in out.columns

    @pytest.mark.parametrize("adjust", ["qfq", "hfq"])
    def test_qfq_hfq_call_adjuster_with_sorted_coerced_dates(self, service, adjust):
        service.adjuster.adjust = MagicMock(
            side_effect=lambda df, symbol, adjust_type: df.assign(adj_factor=1.0)
        )
        scrambled = _clean_frame().iloc[::-1].reset_index(drop=True)
        out = service.process(scrambled, "600519.SH", adjust=adjust)
        assert "adj_factor" in out.columns
        passed_df = service.adjuster.adjust.call_args[0][0]
        assert passed_df["date"].is_monotonic_increasing
        assert service.adjuster.adjust.call_args[0][1] == "600519.SH"
        assert service.adjuster.adjust.call_args[1]["adjust_type"] == adjust

    def test_null_dates_dropped_before_adjustment(self, service):
        """``None`` 日期能穿过 cleaner (to_datetime→NaT) 但被 process 丢弃。"""
        base = _clean_frame()
        frame = pd.DataFrame(
            {
                "date": [*base["date"], None],
                "code": [*base["code"], "600519.SH"],
                "open": [*base["open"], 10.5],
                "high": [*base["high"], 10.7],
                "low": [*base["low"], 10.3],
                "close": [*base["close"], 10.6],
                "volume": [*base["volume"], 100.0],
                "amount": [*base["amount"], 1000.0],
            }
        )
        assert len(frame) == 4
        service.adjuster.adjust = MagicMock(side_effect=lambda df, s, adjust_type: df)
        service.process(frame, "600519.SH", adjust="qfq")
        passed_df = service.adjuster.adjust.call_args[0][0]
        assert len(passed_df) == 3
        assert passed_df["date"].notna().all()

    def test_garbage_date_raises_in_cleaner_not_silently_dropped(self, service):
        """口径注记: ``DataCleaner`` 用严格 ``to_datetime`` (垃圾串→抛错),
        而 ``process`` 自身用 ``errors="coerce"`` + dropna。因 cleaner 先跑,
        垃圾日期**不会**走到 process 的宽容分支 —— 这里锁定该实际契约。
        """
        frame = _clean_frame()
        frame.loc[len(frame)] = ["not-a-date", "600519.SH", 10.0, 11.0, 9.0, 10.5, 100.0, 1000.0]
        service.adjuster.adjust = MagicMock()
        with pytest.raises(Exception, match="not-a-date"):
            service.process(frame, "600519.SH", adjust="qfq")
        service.adjuster.adjust.assert_not_called()

    def test_cleaner_is_applied_first(self, service):
        service.cleaner.clean_stock_daily = MagicMock(
            return_value=_clean_frame().assign(cleaner_marker=1)
        )
        out = service.process(_clean_frame(), "600519.SH", adjust="")
        service.cleaner.clean_stock_daily.assert_called_once()
        assert "cleaner_marker" in out.columns
