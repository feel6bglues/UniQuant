"""Tests for ResultStore — analysis result persistence."""

from __future__ import annotations

import json
from datetime import date

import pytest

from uniquant.shared.result_store import AnalysisRecord, ResultStore


@pytest.fixture
def store(tmp_path):
    return ResultStore(path=str(tmp_path))


def make_record(symbol: str, analysis_date: date, **kwargs) -> AnalysisRecord:
    defaults = dict(
        symbol=symbol,
        analysis_date=analysis_date,
        regime="NORMAL",
        lppl_score=0.5,
        ntf_detected=False,
        czsc_signal="buy_1",
        wyckoff_signal="ACCUMULATION",
        action="BUY",
        confidence=0.8,
        backtest_sharpe=1.5,
        backtest_return=0.12,
        backtest_mdd=-0.05,
        metadata={"source": "test"},
    )
    defaults.update(kwargs)
    return AnalysisRecord(**defaults)


class TestSaveAndLoad:
    def test_save_creates_json_file(self, store, tmp_path):
        d = date(2026, 6, 29)
        record = make_record("000001.SZ", d)
        store.save("000001.SZ", record)

        expected = tmp_path / "2026-06-29" / "000001.SZ.json"
        assert expected.exists()
        data = json.loads(expected.read_text(encoding="utf-8"))
        assert data["symbol"] == "000001.SZ"
        assert data["action"] == "BUY"

    def test_load_returns_matching_record(self, store):
        d = date(2026, 6, 29)
        record = make_record("000001.SZ", d)
        store.save("000001.SZ", record)

        loaded = store.load("000001.SZ", d)
        assert loaded is not None
        assert loaded.symbol == "000001.SZ"
        assert loaded.analysis_date == d
        assert loaded.action == "BUY"
        assert loaded.confidence == 0.8
        assert loaded.backtest_sharpe == 1.5
        assert loaded.metadata == {"source": "test"}

    def test_load_nonexistent_returns_none(self, store):
        loaded = store.load("999999.XSHE", date(2026, 6, 29))
        assert loaded is None


class TestQueryByDate:
    def test_query_returns_all_symbols_for_date(self, store):
        d = date(2026, 6, 29)
        for sym in ("000001.SZ", "000002.SZ", "000003.SZ"):
            store.save(sym, make_record(sym, d))

        results = store.query(d)
        assert len(results) == 3
        symbols = {r.symbol for r in results}
        assert symbols == {"000001.SZ", "000002.SZ", "000003.SZ"}

    def test_query_empty_date(self, store):
        results = store.query(date(2026, 6, 29))
        assert results == []


class TestQueryRange:
    def test_query_range_returns_all_records_in_order(self, store):
        d1 = date(2026, 6, 28)
        d2 = date(2026, 6, 29)
        d3 = date(2026, 6, 30)

        store.save("000001.SZ", make_record("000001.SZ", d1, action="HOLD"))
        store.save("000001.SZ", make_record("000001.SZ", d2, action="BUY"))
        store.save("000001.SZ", make_record("000001.SZ", d3, action="SELL"))

        results = store.query_range("000001.SZ", d1, d3)
        assert len(results) == 3
        assert [r.analysis_date for r in results] == [d1, d2, d3]

    def test_query_range_no_results(self, store):
        results = store.query_range("000001.SZ", date(2026, 1, 1), date(2026, 1, 31))
        assert results == []


class TestCompare:
    def test_compare_two_dates_returns_diff(self, store):
        d1 = date(2026, 6, 28)
        d2 = date(2026, 6, 29)

        store.save("000001.SZ", make_record("000001.SZ", d1, action="HOLD", confidence=0.3))
        store.save("000001.SZ", make_record("000001.SZ", d2, action="BUY", confidence=0.8))

        diff = store.compare("000001.SZ", d1, d2)
        assert diff["action"] == ("HOLD", "BUY")
        assert diff["confidence"] == (0.3, 0.8)

    def test_compare_when_one_missing_returns_empty(self, store):
        d1 = date(2026, 6, 28)
        d2 = date(2026, 6, 29)
        store.save("000001.SZ", make_record("000001.SZ", d1))

        diff = store.compare("000001.SZ", d1, d2)
        assert diff == {}


class TestLoadLatest:
    def test_load_latest_returns_newest(self, store):
        d1 = date(2026, 6, 28)
        d2 = date(2026, 6, 29)

        store.save("000001.SZ", make_record("000001.SZ", d1, action="HOLD"))
        store.save("000001.SZ", make_record("000001.SZ", d2, action="BUY"))

        latest = store.load_latest("000001.SZ")
        assert latest is not None
        assert latest.analysis_date == d2
        assert latest.action == "BUY"

    def test_load_latest_no_records(self, store):
        latest = store.load_latest("000001.SZ")
        assert latest is None


class TestWriteVerify:
    """Save must produce a valid, readable file (anti-drift for P3.6)."""

    def test_save_atomic_rename_no_partial_write(self, store, tmp_path):
        d = date(2026, 6, 29)
        file_path = tmp_path / "2026-06-29" / "000001.SZ.json"
        record = make_record("000001.SZ", d)
        store.save("000001.SZ", record)

        assert file_path.exists()
        content = file_path.read_text(encoding="utf-8")
        assert content.endswith("}\n") or content.endswith("}")

    def test_corrupted_file_returns_none(self, store, tmp_path):
        d = date(2026, 6, 29)
        file_path = tmp_path / "2026-06-29" / "corrupt.SZ.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("{invalid json", encoding="utf-8")

        loaded = store.load("corrupt.SZ", d)
        assert loaded is None


class TestEdgeCases:
    def test_save_with_minimal_fields(self, store):
        d = date(2026, 6, 29)
        record = AnalysisRecord(symbol="000001.SZ", analysis_date=d)
        store.save("000001.SZ", record)

        loaded = store.load("000001.SZ", d)
        assert loaded is not None
        assert loaded.regime is None
        assert loaded.action is None

    def test_save_overwrites_existing(self, store):
        d = date(2026, 6, 29)
        store.save("000001.SZ", make_record("000001.SZ", d, action="HOLD"))
        store.save("000001.SZ", make_record("000001.SZ", d, action="BUY"))

        loaded = store.load("000001.SZ", d)
        assert loaded is not None
        assert loaded.action == "BUY"
