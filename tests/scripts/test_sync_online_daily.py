"""sync_online_daily 单元测试 (免网免湖 CI 安全)。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scripts.maintenance.sync_online_daily import (
    DAILY_CONTRACT_COLUMNS,
    discover_symbols,
    load_fingerprints,
    run_sync,
    save_fingerprints,
    sync_single_symbol,
)


def _sample_df(code: str, dates: list[str]) -> pd.DataFrame:
    rows = []
    for d in dates:
        rows.append({
            "date": pd.Timestamp(d),
            "open": 100.0,
            "high": 105.0,
            "low": 98.0,
            "close": 102.0,
            "amount": 1000000.0,
            "volume": 10000,
            "code": code,
        })
    return pd.DataFrame(rows)


class TestFingerprints:
    def test_load_and_save_fingerprints(self, tmp_path: Path):
        fp_path = tmp_path / "sub" / ".fingerprints.json"
        data = load_fingerprints(fp_path)
        assert data["version"] == 1
        assert data["symbols"] == {}

        data["symbols"]["600519.SH"] = {"last_date": "2026-11-20", "status": "updated"}
        save_fingerprints(fp_path, data)

        reloaded = load_fingerprints(fp_path)
        assert reloaded["symbols"]["600519.SH"]["last_date"] == "2026-11-20"
        assert reloaded["last_updated"] is not None

    def test_corrupted_fingerprint_file_returns_default(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        data = load_fingerprints(bad_file)
        assert data["version"] == 1
        assert data["symbols"] == {}


class TestDiscoverSymbols:
    def test_discover_symbols(self, tmp_path: Path):
        idx_dir = tmp_path / "index"
        daily_dir = tmp_path / "daily"
        idx_dir.mkdir(parents=True)
        daily_dir.mkdir(parents=True)

        (idx_dir / "000300.SH.parquet").touch()
        (daily_dir / "600519.SH.parquet").touch()
        (daily_dir / "000001.SZ.parquet").touch()

        all_syms = discover_symbols(tmp_path)
        assert set(all_syms) == {("000300.SH", True), ("600519.SH", False), ("000001.SZ", False)}

        idx_only = discover_symbols(tmp_path, include_stock=False)
        assert idx_only == [("000300.SH", True)]

        stk_only = discover_symbols(tmp_path, include_index=False)
        assert set(stk_only) == {("600519.SH", False), ("000001.SZ", False)}


class TestSyncSingleSymbol:
    def test_create_new_symbol_parquet(self, tmp_path: Path):
        mock_source = MagicMock()
        mock_source.fetch_daily.return_value = _sample_df("600519.SH", ["2026-11-18", "2026-11-19"])

        res = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            source=mock_source,
            end_date="2026-11-20",
        )
        assert res["status"] == "created_new"
        assert res["new_bars"] == 2
        assert res["last_date"] == "2026-11-19"

        target_file = tmp_path / "daily" / "600519.SH.parquet"
        assert target_file.exists()

        written_df = pd.read_parquet(target_file)
        assert list(written_df.columns) == DAILY_CONTRACT_COLUMNS
        assert len(written_df) == 2
        assert written_df["volume"].dtype == "int64"
        assert written_df["reserved"].dtype == "int64"

    def test_incremental_update_existing_symbol(self, tmp_path: Path):
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir(parents=True)
        init_df = _sample_df("600519.SH", ["2026-11-16", "2026-11-17"])
        init_df["reserved"] = 0
        init_df[DAILY_CONTRACT_COLUMNS].to_parquet(daily_dir / "600519.SH.parquet")

        mock_source = MagicMock()
        mock_source.fetch_daily.return_value = _sample_df("600519.SH", ["2026-11-18", "2026-11-19"])

        res = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            source=mock_source,
            end_date="2026-11-20",
        )
        assert res["status"] == "updated"
        assert res["new_bars"] == 2
        assert res["total_bars"] == 4
        assert res["last_date"] == "2026-11-19"

        updated_df = pd.read_parquet(daily_dir / "600519.SH.parquet")
        assert len(updated_df) == 4
        assert updated_df["date"].is_monotonic_increasing

    def test_up_to_date_skipped_without_fetch(self, tmp_path: Path):
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir(parents=True)
        init_df = _sample_df("600519.SH", ["2026-11-20"])
        init_df["reserved"] = 0
        init_df[DAILY_CONTRACT_COLUMNS].to_parquet(daily_dir / "600519.SH.parquet")

        mock_source = MagicMock()

        res = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            source=mock_source,
            end_date="2026-11-20",
        )
        assert res["status"] == "up_to_date"
        assert res["new_bars"] == 0
        mock_source.fetch_daily.assert_not_called()

    def test_dry_run_does_not_modify_disk(self, tmp_path: Path):
        mock_source = MagicMock()
        mock_source.fetch_daily.return_value = _sample_df("600519.SH", ["2026-11-20"])

        res = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            source=mock_source,
            dry_run=True,
        )
        assert res["status"] == "created_new"
        assert not (tmp_path / "daily" / "600519.SH.parquet").exists()


class TestRunSync:
    def test_run_sync_multi_symbol(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        mock_source = MagicMock()
        mock_source.fetch_daily.side_effect = lambda sym, start_date, end_date: _sample_df(sym, ["2026-11-20"])

        monkeypatch.setattr(
            "scripts.maintenance.sync_online_daily.TdxDataOnlineSource",
            lambda *args, **kwargs: mock_source,
        )

        fp_path = tmp_path / ".fingerprints.json"
        stats = run_sync(
            lake_quotes=tmp_path,
            symbols=["000300.SH", "600519.SH"],
            workers=2,
            dry_run=False,
            fingerprint_path=fp_path,
        )

        assert stats.total_scanned == 2
        assert stats.created_new == 2
        assert stats.failed == 0
        assert (tmp_path / "index" / "000300.SH.parquet").exists()
        assert (tmp_path / "daily" / "600519.SH.parquet").exists()

        with open(fp_path) as f:
            fp_data = json.load(f)
        assert "000300.SH" in fp_data["symbols"]
        assert "600519.SH" in fp_data["symbols"]


class TestCrossValidate:
    def test_cross_validate_pass_and_fail(self, tmp_path: Path):
        import struct
        vipdoc = tmp_path / "vipdoc"
        lday_sh = vipdoc / "sh" / "lday"
        lday_sh.mkdir(parents=True)
        day_file = lday_sh / "sh600519.day"

        # Write matching local day record for 2026-11-20
        with open(day_file, "wb") as f:
            f.write(struct.pack("<IIIIIfII", 20261120, 10000, 10500, 9800, 10200, 1000000.0, 10000, 0))

        mock_source = MagicMock()
        mock_source.fetch_daily.return_value = _sample_df("600519.SH", ["2026-11-20"])

        lake_dir = tmp_path / "lake"
        res_pass = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=lake_dir,
            source=mock_source,
            vipdoc_dir=vipdoc,
        )
        assert res_pass["status"] == "created_new"
        assert "VERIFIED" in str(res_pass.get("verified"))

        # Now test price mismatch: source returns close=200.0
        bad_df = _sample_df("600519.SH", ["2026-11-20"])
        bad_df["close"] = 200.0
        mock_source.fetch_daily.return_value = bad_df

        res_fail = sync_single_symbol(
            symbol="600519.SH",
            lake_quotes=lake_dir,
            source=mock_source,
            vipdoc_dir=vipdoc,
            force=True,
        )
        assert res_fail["status"] == "validation_failed"
        assert "CLOSE_MISMATCH" in str(res_fail.get("error"))
