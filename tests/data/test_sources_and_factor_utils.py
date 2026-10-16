"""Behavioural tests for three live-but-undertested data-layer modules.

Targets:
  * ``uniquant.data.sources.mootdx_online``       (mootdx client fully mocked)
  * ``uniquant.data.utils.smart_factor_calculator`` (protected single-track
    corporate-action / qfq-hfq factor maths)
  * ``uniquant.data.utils.akshare_market_service``  (akshare ``call`` seam mocked)

No network access is performed: mootdx is patched at ``mootdx.quotes.Quotes``,
akshare is exercised through the injected callable, and all file I/O uses
``tmp_path`` (never the repository's real ``data/`` lake).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from uniquant.data.sources.mootdx_online import MootdxOnlineSource
from uniquant.data.utils import smart_factor_calculator as sfc
from uniquant.data.utils.akshare_market_service import AkshareMarketService
from uniquant.data.utils.smart_factor_calculator import (
    GBBQProcessorV15,
    SmartFactorCalculator,
    SmartFactorCalculatorV15,
    _process_single_stock,
    run_parallel_calculation,
)


# ===========================================================================
# mootdx_online.MootdxOnlineSource
# ===========================================================================


def _fake_mootdx_client():
    """Patch ``mootdx.quotes.Quotes`` and return (patched Quotes, fake client)."""
    fake_client = MagicMock(name="mootdx_client")
    patcher = patch("mootdx.quotes.Quotes")
    quotes_cls = patcher.start()
    quotes_cls.factory.return_value = fake_client
    return patcher, quotes_cls, fake_client


class TestMootdxOnlineSourceClientLifecycle:
    def test_init_starts_without_client(self):
        src = MootdxOnlineSource()
        assert src._client is None
        assert src.name == "MootdxOnline"

    def test_get_client_lazy_inits_and_caches(self):
        patcher, quotes_cls, fake_client = _fake_mootdx_client()
        try:
            src = MootdxOnlineSource()
            first = src._get_client()
            second = src._get_client()
        finally:
            patcher.stop()

        assert first is fake_client
        assert second is fake_client
        # factory called exactly once (cached thereafter) with the std market.
        quotes_cls.factory.assert_called_once_with(market="std", heartbeat=True)

    def test_close_clears_client(self):
        patcher, _, _ = _fake_mootdx_client()
        try:
            src = MootdxOnlineSource()
            src._get_client()
            assert src._client is not None
            src.close()
        finally:
            patcher.stop()
        assert src._client is None

    def test_fetch_market_cap_is_unsupported_zero(self):
        assert MootdxOnlineSource().fetch_market_cap("600000.SH") == 0.0

    def test_get_capabilities_declares_online_profile(self):
        caps = MootdxOnlineSource().get_capabilities()
        assert caps == {
            "offline": False,
            "daily": True,
            "minute": True,
            "realtime": True,
            "financial": False,
        }


class TestMootdxOnlineSourceNormalizeColumns:
    def test_renames_datetime_and_vol(self):
        df = pd.DataFrame({"datetime": ["2025-01-01"], "vol": [10], "close": [1.0]})
        out = MootdxOnlineSource._normalize_columns(df)
        assert "date" in out.columns
        assert "datetime" not in out.columns
        assert "volume" in out.columns
        assert "vol" not in out.columns
        assert out["volume"].iloc[0] == 10

    def test_no_known_columns_unchanged(self):
        df = pd.DataFrame({"foo": [1], "bar": [2]})
        out = MootdxOnlineSource._normalize_columns(df)
        assert list(out.columns) == ["foo", "bar"]

    def test_both_vol_and_volume_yields_single_canonical_column(self):
        """§7.4 #10: when both ``vol`` and ``volume`` are present the rename must not
        produce a duplicate ``volume`` column; the canonical column wins."""
        df = pd.DataFrame({"vol": [7], "volume": [10], "close": [1.0]})
        out = MootdxOnlineSource._normalize_columns(df)
        assert list(out.columns).count("volume") == 1
        assert "vol" not in out.columns
        assert out["volume"].iloc[0] == 10


class TestMootdxOnlineSourceFetchDaily:
    def _raw(self):
        return pd.DataFrame(
            {
                "datetime": ["2025-01-02", "2025-01-03", "2025-01-04"],
                "open": [10.0, 11.0, 12.0],
                "close": [10.5, 11.5, 12.5],
                "high": [10.6, 11.6, 12.6],
                "low": [9.9, 10.9, 11.9],
                "vol": [100, 200, 300],
                "amount": [1000.0, 2000.0, 3000.0],
            }
        )

    def test_happy_path_normalizes_filters_and_tags_code(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.bars.return_value = self._raw()
            src = MootdxOnlineSource()
            out = src.fetch_daily("600000.SH", "2025-01-02", "2025-01-03")
        finally:
            patcher.stop()

        client.bars.assert_called_once_with(symbol="600000", frequency=9, offset=0, count=800)
        assert list(out["date"]) == [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
        assert (out["code"] == "600000.SH").all()
        assert "volume" in out.columns
        assert pd.api.types.is_datetime64_any_dtype(out["date"])

    def test_empty_result_returns_empty_frame(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.bars.return_value = pd.DataFrame()
            out = MootdxOnlineSource().fetch_daily("600000.SH", "2025-01-01", "2025-12-31")
        finally:
            patcher.stop()
        assert out.empty

    def test_none_result_returns_empty_frame(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.bars.return_value = None
            out = MootdxOnlineSource().fetch_daily("600000.SH", "2025-01-01", "2025-12-31")
        finally:
            patcher.stop()
        assert out.empty

    def test_client_exception_is_swallowed_to_empty(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.bars.side_effect = RuntimeError("server down")
            out = MootdxOnlineSource().fetch_daily("600000.SH", "2025-01-01", "2025-12-31")
        finally:
            patcher.stop()
        assert out.empty


class TestMootdxOnlineSourceFetchRealTime:
    def test_symbol_normalizes_and_tags(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.quotes.return_value = pd.DataFrame(
                {"datetime": ["2025-01-02 10:00"], "close": [10.5], "vol": [42]}
            )
            out = MootdxOnlineSource().fetch_real_time("600000.SH")
        finally:
            patcher.stop()

        client.quotes.assert_called_once_with(symbol=["600000"])
        assert list(out["code"]) == ["600000.SH"]
        assert out["volume"].iloc[0] == 42

    def test_none_symbol_is_unsupported_and_does_not_call_client(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            out = MootdxOnlineSource().fetch_real_time(None)
        finally:
            patcher.stop()
        assert out.empty
        client.quotes.assert_not_called()

    def test_empty_result_returns_empty_frame(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.quotes.return_value = pd.DataFrame()
            out = MootdxOnlineSource().fetch_real_time("600000.SH")
        finally:
            patcher.stop()
        assert out.empty

    def test_client_exception_is_swallowed_to_empty(self):
        patcher, _, client = _fake_mootdx_client()
        try:
            client.quotes.side_effect = ConnectionError("timeout")
            out = MootdxOnlineSource().fetch_real_time("600000.SH")
        finally:
            patcher.stop()
        assert out.empty


# ===========================================================================
# smart_factor_calculator.GBBQProcessorV15
# ===========================================================================


class TestGBBQLoadAndClean:
    def test_missing_file_returns_empty(self, tmp_path):
        out = GBBQProcessorV15.load_and_clean(str(tmp_path / "nope.parquet"))
        assert out.empty

    def test_corrupt_file_returns_empty(self, tmp_path):
        bad = tmp_path / "gbbq.parquet"
        bad.write_text("this is not parquet")
        out = GBBQProcessorV15.load_and_clean(str(bad))
        assert out.empty

    def test_full_clean_maps_filters_and_scales(self, tmp_path):
        path = tmp_path / "gbbq.parquet"
        pd.DataFrame(
            {
                "code": [1, 2, 3, 4],
                "datetime": ["20250101", "20250601", "20260101", "20260101"],
                "cash_div": [5.0, 0.0, 10.0, 0.0],
                "split_ratio": [0.0, 0.0, 0.0, 0.0],
                "rights_ratio": [0.0, 0.0, 0.0, 0.0],
                "rights_price": [0.0, 0.0, 0.0, 0.0],
                # last row is category=2 -> must be dropped by the purity filter
                "category": [1, 1, 1, 2],
            }
        ).to_parquet(path)

        out = GBBQProcessorV15.load_and_clean(str(path))

        # category filter drops row 4; row 2 has no cash/split/rights -> dropped.
        assert len(out) == 2
        # code is zero-padded to 6 chars
        assert out["code"].tolist() == ["000001", "000003"]
        # cash is divided by 10 (per-10-share -> per-share)
        assert out.loc[out["code"] == "000001", "cash"].iloc[0] == pytest.approx(0.5)
        assert out.loc[out["code"] == "000003", "cash"].iloc[0] == pytest.approx(1.0)
        assert out["date"].is_monotonic_increasing

    def test_missing_optional_columns_default_to_zero(self, tmp_path):
        path = tmp_path / "gbbq.parquet"
        pd.DataFrame(
            {
                "code": [1],
                "datetime": ["20250101"],
                "cash_div": [5.0],
                # split_ratio / rights_ratio / rights_price intentionally absent
            }
        ).to_parquet(path)

        out = GBBQProcessorV15.load_and_clean(str(path))

        assert len(out) == 1
        for col in ("cash", "split", "rights", "r_price"):
            assert col in out.columns
        assert out["split"].iloc[0] == 0.0
        assert out["rights"].iloc[0] == 0.0
        assert out["r_price"].iloc[0] == 0.0
        assert out["cash"].iloc[0] == pytest.approx(0.5)


class TestGBBQAggregateEvents:
    def test_fills_missing_columns_then_aggregates(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2025-06-01", "2025-06-01"]), "cash": [1.0, 2.0]})
        out = GBBQProcessorV15.aggregate_events(df)

        assert set(out.columns) == {"date", "cash", "split", "rights", "r_price"}
        assert len(out) == 1
        assert out["cash"].iloc[0] == pytest.approx(3.0)
        assert out["split"].iloc[0] == 0.0

    def test_empty_input_returns_empty(self):
        assert GBBQProcessorV15.aggregate_events(pd.DataFrame()).empty


# ===========================================================================
# smart_factor_calculator.SmartFactorCalculatorV15
# ===========================================================================


def _daily(close, open_=None, start="2025-01-01"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    dates = pd.date_range(start, periods=n, freq="B")
    if open_ is None:
        open_ = close * 0.99
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.asarray(open_, dtype=float),
            "close": close,
        }
    )


def _event(date, cash=0.0, split=0.0, rights=0.0, r_price=0.0):
    return pd.DataFrame(
        [{"date": pd.Timestamp(date), "cash": cash, "split": split, "rights": rights, "r_price": r_price}]
    )


class TestSafeConvertDate:
    def test_datetime_dtype_passthrough(self):
        s = pd.Series(pd.to_datetime(["2025-01-01", "2025-01-02"]))
        out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert out.equals(s)

    def test_integer_dtype_is_zero_padded_yyyymmdd(self):
        s = pd.Series([20250101, 20250601])
        out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert list(out) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-01")]

    def test_string_yyyymmdd(self):
        s = pd.Series(["20250101", "20250601"])
        out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert list(out) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-01")]

    def test_string_iso_falls_back_when_compact_fails(self):
        s = pd.Series(["2025-01-01", "2025-06-01"])
        out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert list(out) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-01")]

    def test_other_dtype_uses_generic_parse(self):
        s = pd.Series([20250101.0, 20250601.0])
        out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert pd.api.types.is_datetime64_any_dtype(out)

    def test_conversion_failure_returns_original_series(self):
        s = pd.Series(["20250101", "20250601"])
        with patch.object(sfc.pd, "to_datetime", side_effect=ValueError("boom")):
            out = SmartFactorCalculatorV15._safe_convert_date(s)
        assert out.equals(s)


class TestCalculateGuards:
    def test_future_only_daily_returns_empty(self):
        df = _daily([10.0] * 5, start="2027-01-01")  # beyond REAL_TODAY
        out = SmartFactorCalculatorV15().calculate(df, pd.DataFrame())
        assert out.empty

    def test_all_invalid_event_dates_fall_back_to_ones(self):
        df = _daily([10.0] * 3)
        events = pd.DataFrame([{"date": "not-a-date", "cash": 1.0, "split": 0.0, "rights": 0.0, "r_price": 0.0}])
        out = SmartFactorCalculatorV15().calculate(df, events)
        assert (out["factor"] == 1.0).all()

    def test_zero_denominator_event_skipped(self):
        # split = -1 makes denominator (1 + split + rights) == 0
        df = _daily([10.0, 10.0, 10.0])
        events = _event(df["date"].iloc[1], split=-1.0)
        out = SmartFactorCalculatorV15().calculate(df, events)
        assert out["factor"].iloc[1] == pytest.approx(1.0)

    def test_implausible_event_with_tiny_real_drop_is_skipped(self):
        # factor ~2.0 but the ex-date open barely moved -> treated as non-event.
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                "open": [9.9, 9.9, 9.99],
                "close": [10.0, 10.0, 9.99],
            }
        )
        events = _event("2025-01-03", split=1.0)
        out = SmartFactorCalculatorV15().calculate(df, events)
        assert out["factor"].iloc[2] == pytest.approx(1.0)

    def test_zero_pre_close_with_split_multiplies_by_ratio(self):
        # close[0] == 0 -> pre_close guard (pre_close <= 0) multiplies by 1+split+rights
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                "open": [0.0, 5.0, 5.0],
                "close": [0.0, 5.0, 5.0],
            }
        )
        events = _event("2025-01-02", split=1.0)
        out = SmartFactorCalculatorV15().calculate(df, events)
        assert out["factor"].iloc[1] == pytest.approx(2.0)
        assert out["factor"].iloc[2] == pytest.approx(2.0)

    def test_cumulative_factor_compat(self):
        df = _daily([10.0] * 5)
        calc = SmartFactorCalculatorV15()
        assert calc.calculate_cumulative_factor(df, pd.DataFrame()).equals(calc.calculate(df, pd.DataFrame()))


class TestProcessSingleStock:
    def _write_daily(self, path: Path, n=4):
        _daily([10.0, 10.0, 9.5, 9.6][:n]).to_parquet(path)

    def test_filename_without_code_returns_false(self, tmp_path):
        out = _process_single_stock(tmp_path / "notes.txt", {}, tmp_path)
        assert out is False

    def test_valid_file_writes_hfq_output_and_returns_true(self, tmp_path):
        daily = tmp_path / "600000.SH.parquet"
        self._write_daily(daily)
        out_dir = tmp_path / "out"
        out_dir.mkdir()  # callers (run_parallel_calculation) create the dir first
        ok = _process_single_stock(daily, {}, out_dir, is_hfq=True)

        assert ok is True
        written = pd.read_parquet(out_dir / "600000.SH.parquet")
        assert (written["code"] == "600000").all()
        assert (written["market"] == "SH").all()
        assert (written["type"] == "hfq").all()
        # no events -> factor stays at the identity of 1.0
        assert (written["factor"] == 1.0).all()

    def test_valid_file_qfq_flag(self, tmp_path):
        daily = tmp_path / "000001.SZ.parquet"
        self._write_daily(daily)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        ok = _process_single_stock(daily, {}, out_dir, is_hfq=False)

        assert ok is True
        written = pd.read_parquet(out_dir / "000001.SZ.parquet")
        assert (written["type"] == "qfq").all()

    def test_valid_file_with_events_aggregates_gbbq(self, tmp_path):
        daily = tmp_path / "600519.SH.parquet"
        # ex-date = 3rd row; open actually gaps down ~35% (10送5) so the
        # plausibility guard does NOT skip the event.
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06"]),
                "open": [100.0, 100.0, 65.0, 66.0],
                "close": [100.0, 100.0, 66.0, 67.0],
            }
        )
        df.to_parquet(daily)
        gbbq = pd.DataFrame(
            {
                "date": pd.to_datetime([df["date"].iloc[2]]),
                "cash": [0.0],
                "split": [0.5],
                "rights": [0.0],
                "r_price": [0.0],
            }
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        ok = _process_single_stock(daily, {"600519": gbbq}, out_dir, is_hfq=True)

        assert ok is True
        written = pd.read_parquet(out_dir / "600519.SH.parquet")
        assert written["factor"].iloc[2] == pytest.approx(1.5, rel=1e-3)

    def test_corrupt_daily_file_returns_false(self, tmp_path):
        bad = tmp_path / "600000.SH.parquet"
        bad.write_text("garbage")
        assert _process_single_stock(bad, {}, tmp_path / "out") is False


class TestRunParallelCalculation:
    def test_empty_gbbq_short_circuits_to_zero(self, tmp_path):
        out_dir = tmp_path / "out"
        count = run_parallel_calculation(
            str(tmp_path / "daily"), str(tmp_path / "missing.parquet"), str(out_dir)
        )
        assert count == 0
        assert out_dir.is_dir()

    def test_sums_successful_workers(self, tmp_path):
        gbbq = tmp_path / "gbbq.parquet"
        pd.DataFrame(
            {
                "code": [600000],
                "datetime": ["20250101"],
                "cash_div": [5.0],
                "split_ratio": [0.0],
                "rights_ratio": [0.0],
                "rights_price": [0.0],
                "category": [1],
            }
        ).to_parquet(gbbq)

        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()
        pd.DataFrame({"date": pd.to_datetime(["2025-01-01"]), "open": [1.0], "close": [1.0]}).to_parquet(
            daily_dir / "600000.SH.parquet"
        )

        captured = {}

        class _FakeExecutor:
            def __init__(self, max_workers=None):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def map(self, func, iterable, chunksize=1):
                captured["files"] = list(iterable)
                captured["chunksize"] = chunksize
                return iter([True, False, True])

        with patch.object(sfc, "ProcessPoolExecutor", _FakeExecutor):
            count = run_parallel_calculation(
                str(daily_dir), str(gbbq), str(tmp_path / "out"), max_workers=2
            )

        assert count == 2
        assert captured["max_workers"] == 2
        assert captured["chunksize"] == 10
        assert [p.name for p in captured["files"]] == ["600000.SH.parquet"]


class TestSmartFactorCalculatorCompat:
    def test_init_wires_v15(self):
        calc = SmartFactorCalculator()
        assert isinstance(calc.v15_calculator, SmartFactorCalculatorV15)

    def test_default_event_factor(self):
        assert SmartFactorCalculator()._calculate_cumulative_factor({}) == pytest.approx(1.0)

    def test_split_factor_doubles_effective(self):
        got = SmartFactorCalculator()._calculate_cumulative_factor(
            {"split_factor": 2.0, "cash_div": 0.0, "pre_close": 10.0}
        )
        assert got == pytest.approx(2.0)

    def test_cash_dividend_lowers_effective(self):
        got = SmartFactorCalculator()._calculate_cumulative_factor(
            {"split_factor": 1.0, "cash_div": 2.0, "pre_close": 10.0}
        )
        assert got == pytest.approx(0.8)

    def test_non_positive_pre_close_returns_one(self):
        got = SmartFactorCalculator()._calculate_cumulative_factor({"pre_close": 0.0, "split_factor": 2.0})
        assert got == 1.0

    def test_effective_factor_floor(self):
        got = SmartFactorCalculator()._calculate_cumulative_factor(
            {"split_factor": 1.0, "cash_div": 100.0, "pre_close": 10.0}
        )
        assert got == pytest.approx(0.001)

    def test_calculate_cumulative_factor_delegates_to_v15(self):
        df = _daily([10.0] * 5)
        compat = SmartFactorCalculator()
        v15 = SmartFactorCalculatorV15()
        pd.testing.assert_frame_equal(
            compat.calculate_cumulative_factor(df, pd.DataFrame()),
            v15.calculate_cumulative_factor(df, pd.DataFrame()),
        )


# ===========================================================================
# akshare_market_service.AkshareMarketService
# ===========================================================================


class _Recorder:
    """Records (method, kwargs) and returns a per-method configured value."""

    def __init__(self, results=None, default=None):
        self.calls = []
        self._results = results or {}
        self._default = default

    def __call__(self, method_name, **kwargs):
        self.calls.append((method_name, kwargs))
        if method_name in self._results:
            value = self._results[method_name]
            if isinstance(value, Exception):
                raise value
            return value
        return self._default

    @property
    def methods(self):
        return [m for m, _ in self.calls]


class TestAkshareFetchStockDaily:
    def test_none_result_continues_to_next_method(self):
        rec = _Recorder(
            {"stock_zh_a_daily": None, "stock_zh_a_hist": pd.DataFrame({"date": ["2026-04-24"]})}
        )
        result = AkshareMarketService(rec).fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")
        assert list(result.columns) == ["date"]
        assert rec.methods == ["stock_zh_a_daily", "stock_zh_a_hist"]

    def test_non_dataframe_result_is_returned_directly(self):
        payload = [{"symbol": "000001"}]
        rec = _Recorder({"stock_zh_a_daily": payload})
        result = AkshareMarketService(rec).fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")
        assert result is payload
        assert rec.methods == ["stock_zh_a_daily"]

    def test_exception_is_logged_then_falls_through(self):
        rec = _Recorder(
            {
                "stock_zh_a_daily": RuntimeError("boom"),
                "stock_zh_a_hist": pd.DataFrame({"date": ["2026-04-24"]}),
            }
        )
        result = AkshareMarketService(rec).fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")
        assert not result.empty
        assert rec.methods == ["stock_zh_a_daily", "stock_zh_a_hist"]

    def test_all_methods_fail_returns_none(self):
        rec = _Recorder(default=pd.DataFrame())
        result = AkshareMarketService(rec).fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")
        assert result is None
        assert rec.methods == ["stock_zh_a_daily", "stock_zh_a_hist", "stock_zh_a_hist_tx"]

    def test_tx_fallback_uses_market_prefix_and_compact_dates(self):
        rec = _Recorder({"stock_zh_a_hist_tx": pd.DataFrame({"date": ["20260424"]})})
        AkshareMarketService(rec).fetch_stock_daily("600000.SH", "2026-04-01", "2026-04-24")
        _, kwargs = rec.calls[-1]
        assert kwargs == {"symbol": "sh600000", "start_date": "20260401", "end_date": "20260424"}

    def test_tx_fallback_sz_prefix_for_non_6(self):
        rec = _Recorder({"stock_zh_a_hist_tx": pd.DataFrame({"date": ["20260424"]})})
        AkshareMarketService(rec).fetch_stock_daily("000001.SZ", "2026-04-01", "2026-04-24")
        _, kwargs = rec.calls[-1]
        assert kwargs["symbol"] == "sz000001"


class TestAkshareFetchStockSpot:
    def test_primary_source_success_returns_immediately(self):
        rec = _Recorder({"stock_zh_a_spot": pd.DataFrame({"symbol": ["000001"]})})
        result = AkshareMarketService(rec).fetch_stock_spot("sina")
        assert result.iloc[0]["symbol"] == "000001"
        assert rec.methods == ["stock_zh_a_spot"]

    def test_em_source_maps_to_em_method(self):
        rec = _Recorder({"stock_zh_a_spot_em": pd.DataFrame({"symbol": ["600519"]})})
        result = AkshareMarketService(rec).fetch_stock_spot("em")
        assert rec.methods == ["stock_zh_a_spot_em"]
        assert result.iloc[0]["symbol"] == "600519"

    def test_all_sources_empty_returns_none(self):
        rec = _Recorder(default=pd.DataFrame())
        assert AkshareMarketService(rec).fetch_stock_spot("sina") is None
        assert rec.methods == ["stock_zh_a_spot", "stock_zh_a_spot_em", "stock_zh_a_spot_ths"]

    def test_unknown_source_falls_back_to_default_method(self):
        rec = _Recorder({"stock_zh_a_spot": pd.DataFrame({"symbol": ["000001"]})})
        result = AkshareMarketService(rec).fetch_stock_spot("unknown")
        assert rec.methods == ["stock_zh_a_spot"]
        assert result.iloc[0]["symbol"] == "000001"


class TestAkshareThinWrappers:
    def test_fetch_stock_daily_sina_forwards_args(self):
        rec = _Recorder({"stock_zh_a_daily": pd.DataFrame({"date": ["2026-04-24"]})})
        result = AkshareMarketService(rec).fetch_stock_daily_sina("600000", "2026-04-01", "2026-04-24")
        assert not result.empty
        assert rec.calls[0] == (
            "stock_zh_a_daily",
            {"symbol": "600000", "start_date": "2026-04-01", "end_date": "2026-04-24"},
        )

    def test_fetch_etf_hist_compacts_dates(self):
        rec = _Recorder({"fund_etf_hist_em": pd.DataFrame({"date": ["20260424"]})})
        AkshareMarketService(rec).fetch_etf_hist("510300", "2026-04-01", "2026-04-24")
        assert rec.calls[0] == (
            "fund_etf_hist_em",
            {"symbol": "510300", "period": "daily", "start_date": "20260401", "end_date": "20260424"},
        )

    def test_fetch_index_daily_success(self):
        rec = _Recorder({"stock_zh_index_daily": pd.DataFrame({"date": ["2026-04-24"], "close": [3000.0]})})
        result = AkshareMarketService(rec).fetch_index_daily("sh000300")
        assert len(result) == 1
        assert rec.calls[0] == ("stock_zh_index_daily", {"symbol": "sh000300"})

    def test_fetch_index_daily_empty_returns_empty_frame(self):
        rec = _Recorder({"stock_zh_index_daily": pd.DataFrame()})
        result = AkshareMarketService(rec).fetch_index_daily("sh000300")
        assert result is not None and result.empty


class TestAkshareMinuteAndFlow:
    def test_fetch_minute_data_forwards_adjust(self):
        rec = _Recorder({"stock_zh_a_hist_min_em": pd.DataFrame({"time": ["09:35"]})})
        result = AkshareMarketService(rec).fetch_minute_data("600000", "5", "2026-04-01", "2026-04-24", adjust="hfq")
        assert not result.empty
        assert rec.calls[0] == (
            "stock_zh_a_hist_min_em",
            {
                "symbol": "600000",
                "period": "5",
                "start_date": "2026-04-01",
                "end_date": "2026-04-24",
                "adjust": "hfq",
            },
        )

    def test_fetch_minute_data_empty_returns_empty_frame(self):
        rec = _Recorder({"stock_zh_a_hist_min_em": pd.DataFrame()})
        result = AkshareMarketService(rec).fetch_minute_data("600000", "5", "2026-04-01", "2026-04-24")
        assert result is not None and result.empty

    def test_fetch_fund_flow_forwards_stock_and_market(self):
        rec = _Recorder({"stock_individual_fund_flow": pd.DataFrame({"日期": ["2026-04-24"]})})
        result = AkshareMarketService(rec).fetch_fund_flow("600000", market="sh")
        assert not result.empty
        assert rec.calls[0] == ("stock_individual_fund_flow", {"stock": "600000", "market": "sh"})

    def test_fetch_fund_flow_empty_returns_empty_frame(self):
        rec = _Recorder({"stock_individual_fund_flow": pd.DataFrame()})
        result = AkshareMarketService(rec).fetch_fund_flow("600000", market="sz")
        assert result is not None and result.empty

    def test_fetch_tick_data_success(self):
        rec = _Recorder({"stock_zh_a_tick_tx_js": pd.DataFrame({"price": [10.0]})})
        result = AkshareMarketService(rec).fetch_tick_data("600000")
        assert len(result) == 1
        assert rec.calls[0] == ("stock_zh_a_tick_tx_js", {"symbol": "600000"})

    def test_fetch_tick_data_empty_returns_empty_frame(self):
        rec = _Recorder({"stock_zh_a_tick_tx_js": pd.DataFrame()})
        result = AkshareMarketService(rec).fetch_tick_data("600000")
        assert result is not None and result.empty


class TestAkshareDragonTiger:
    def test_missing_result_returns_empty_frame(self):
        rec = _Recorder({"stock_lhb_detail_em": None})
        result = AkshareMarketService(rec).fetch_dragon_tiger_list("600519.SH", "20260401", "20260424")
        assert isinstance(result, pd.DataFrame) and result.empty
        assert rec.calls[0] == (
            "stock_lhb_detail_em",
            {"start_date": "20260401", "end_date": "20260424"},
        )

    def test_empty_result_returns_empty_frame(self):
        rec = _Recorder({"stock_lhb_detail_em": pd.DataFrame()})
        result = AkshareMarketService(rec).fetch_dragon_tiger_list("600519.SH", "20260401", "20260424")
        assert result.empty

    def test_symbol_column_branch_filters(self):
        source = pd.DataFrame({"symbol": ["000001", "600519"], "名称": ["平安", "茅台"]})
        rec = _Recorder({"stock_lhb_detail_em": source})
        result = AkshareMarketService(rec).fetch_dragon_tiger_list("600519.SH", "20260401", "20260424")
        assert result["symbol"].tolist() == ["600519"]

    def test_no_code_or_symbol_column_returns_all_rows(self):
        source = pd.DataFrame({"名称": ["A", "B"]})
        rec = _Recorder({"stock_lhb_detail_em": source})
        result = AkshareMarketService(rec).fetch_dragon_tiger_list("600519.SH", "20260401", "20260424")
        assert result["名称"].tolist() == ["A", "B"]
