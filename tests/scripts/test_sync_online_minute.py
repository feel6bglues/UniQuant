"""sync_online_minute 单元测试 (免网免湖 CI 安全)。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scripts.maintenance.sync_online_minute import (
    MINUTE_CONTRACT_COLUMNS,
    discover_minute_symbols,
    load_fingerprints,
    run_minute_sync,
    save_fingerprints,
    sync_single_minute_symbol,
)


def _sample_minute_df(code: str, dts: list[str]) -> pd.DataFrame:
    rows = []
    for dt in dts:
        rows.append({
            "datetime": pd.Timestamp(dt),
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "volume": 50000.0,
            "amount": 510000.0,
            "code": code,
        })
    return pd.DataFrame(rows)


class TestMinuteFingerprints:
    def test_load_and_save_minute_fingerprints(self, tmp_path: Path):
        fp_path = tmp_path / "sub" / ".min_fingerprints.json"
        data = load_fingerprints(fp_path)
        assert data["version"] == 1
        assert data["symbols"] == {}

        data["symbols"]["000300.SH"] = {
            "5min": {"last_datetime": "2026-11-20 15:00:00", "status": "updated"}
        }
        save_fingerprints(fp_path, data)

        reloaded = load_fingerprints(fp_path)
        assert reloaded["symbols"]["000300.SH"]["5min"]["last_datetime"] == "2026-11-20 15:00:00"
        assert reloaded["last_updated"] is not None


class TestDiscoverMinuteSymbols:
    def test_discover_from_existing_minute_dir(self, tmp_path: Path):
        m5_dir = tmp_path / "5mins"
        m5_dir.mkdir(parents=True)
        (m5_dir / "000300.SH.parquet").touch()
        (m5_dir / "600519.SH.parquet").touch()

        syms = discover_minute_symbols(tmp_path, "5mins")
        assert syms == ["000300.SH", "600519.SH"]

    def test_discover_fallback_to_daily_and_index_when_minute_empty(self, tmp_path: Path):
        idx_dir = tmp_path / "index"
        daily_dir = tmp_path / "daily"
        idx_dir.mkdir(parents=True)
        daily_dir.mkdir(parents=True)

        (idx_dir / "000300.SH.parquet").touch()
        (daily_dir / "600519.SH.parquet").touch()

        syms = discover_minute_symbols(tmp_path, "5mins")
        assert set(syms) == {"000300.SH", "600519.SH"}


class TestSyncSingleMinuteSymbol:
    def test_create_new_minute_parquet(self, tmp_path: Path):
        mock_source = MagicMock()
        mock_source.fetch_minute.return_value = _sample_minute_df(
            "600519.SH", ["2026-11-20 14:55:00", "2026-11-20 15:00:00"]
        )

        res = sync_single_minute_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            frequency="5min",
            source=mock_source,
            end_dt="2026-11-20 15:00:00",
        )
        assert res["status"] == "created_new"
        assert res["new_bars"] == 2
        assert res["last_datetime"] == "2026-11-20 15:00:00"

        target_file = tmp_path / "5mins" / "600519.SH.parquet"
        assert target_file.exists()

        written_df = pd.read_parquet(target_file)
        assert list(written_df.columns) == MINUTE_CONTRACT_COLUMNS
        assert len(written_df) == 2
        assert written_df["volume"].dtype == "float64"

    def test_incremental_minute_update(self, tmp_path: Path):
        m5_dir = tmp_path / "5mins"
        m5_dir.mkdir(parents=True)
        init_df = _sample_minute_df("600519.SH", ["2026-11-20 14:45:00", "2026-11-20 14:50:00"])
        init_df[MINUTE_CONTRACT_COLUMNS].to_parquet(m5_dir / "600519.SH.parquet")

        mock_source = MagicMock()
        mock_source.fetch_minute.return_value = _sample_minute_df(
            "600519.SH", ["2026-11-20 14:55:00", "2026-11-20 15:00:00"]
        )

        res = sync_single_minute_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            frequency="5min",
            source=mock_source,
            end_dt="2026-11-20 15:00:00",
        )
        assert res["status"] == "updated"
        assert res["new_bars"] == 2
        assert res["total_bars"] == 4

        updated_df = pd.read_parquet(m5_dir / "600519.SH.parquet")
        assert len(updated_df) == 4
        assert updated_df["datetime"].is_monotonic_increasing

    def test_minute_up_to_date_skipped(self, tmp_path: Path):
        m5_dir = tmp_path / "5mins"
        m5_dir.mkdir(parents=True)
        init_df = _sample_minute_df("600519.SH", ["2026-11-20 15:00:00"])
        init_df[MINUTE_CONTRACT_COLUMNS].to_parquet(m5_dir / "600519.SH.parquet")

        mock_source = MagicMock()

        res = sync_single_minute_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            frequency="5min",
            source=mock_source,
            end_dt="2026-11-20 15:00:00",
        )
        assert res["status"] == "up_to_date"
        assert res["new_bars"] == 0
        mock_source.fetch_minute.assert_not_called()

    def test_minute_dry_run(self, tmp_path: Path):
        mock_source = MagicMock()
        mock_source.fetch_minute.return_value = _sample_minute_df("600519.SH", ["2026-11-20 15:00:00"])

        res = sync_single_minute_symbol(
            symbol="600519.SH",
            lake_quotes=tmp_path,
            frequency="5min",
            source=mock_source,
            dry_run=True,
        )
        assert res["status"] == "created_new"
        assert not (tmp_path / "5mins" / "600519.SH.parquet").exists()


class TestRunMinuteSync:
    def test_run_minute_sync_multi_symbol(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        mock_source = MagicMock()
        mock_source.fetch_minute.side_effect = lambda symbol, frequency, start_dt, end_dt: _sample_minute_df(
            symbol, ["2026-11-20 15:00:00"]
        )

        monkeypatch.setattr(
            "scripts.maintenance.sync_online_minute.TdxDataOnlineSource",
            lambda *args, **kwargs: mock_source,
        )

        fp_path = tmp_path / ".min_fingerprints.json"
        stats = run_minute_sync(
            lake_quotes=tmp_path,
            symbols=["000300.SH", "600519.SH"],
            frequency="5min",
            workers=2,
            dry_run=False,
            fingerprint_path=fp_path,
        )

        assert stats.total_scanned == 2
        assert stats.created_new == 2
        assert stats.failed == 0
        assert (tmp_path / "5mins" / "000300.SH.parquet").exists()
        assert (tmp_path / "5mins" / "600519.SH.parquet").exists()

        with open(fp_path) as f:
            fp_data = json.load(f)
        assert "000300.SH" in fp_data["symbols"]
        assert "5min" in fp_data["symbols"]["000300.SH"]
