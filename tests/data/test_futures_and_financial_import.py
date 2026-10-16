# -*- coding: utf-8 -*-
"""Behavioural tests for two live-but-undertested data-layer modules.

Covers:
  * ``uniquant.data.lake.futures_storage_manager`` — CFFEX contract metadata,
    basis-surface math (ACT/365 carry, term slope), MLSI hedge-ratio branches
    and the atomic basis-surface lake writer.
  * ``uniquant.data.services.import_financial`` — TDX gpcw ingestion: stock-code
    normalisation, date normalisation, fingerprinting, the two-phase importer
    (memory aggregation + sequential write) and its error/edge paths.

Everything is hermetic: all file I/O under ``tmp_path`` and every mootdx /
remote call is mocked. The repository's real ``data/`` lake is never touched.
"""

import json
import math
from itertools import count
from pathlib import Path

import pandas as pd
import pytest

import uniquant.data.services.import_financial as ifin
from uniquant.data.lake.futures_storage_manager import (
    FuturesStorageManager,
    calculate_third_friday,
)


# =========================================================================
# Shared helpers
# =========================================================================

def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _contract_frame(dates, closes, settles=None, volumes=None, holds=None):
    n = len(dates)
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "volume": volumes if volumes is not None else [100] * n,
            "hold": holds if holds is not None else [100] * n,
        }
    )
    if settles is not None:
        frame["settle"] = settles
    return frame


def _manager(
    tmp_path: Path,
    *,
    calendar=None,
    contracts=None,
    spot=None,
    spot_dir: str = "index",
) -> FuturesStorageManager:
    """Build a FuturesStorageManager wired entirely to ``tmp_path``."""
    root = Path(tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    lake = root / "futures"
    quotes = root / "quotes"
    cal = root / "trade_calendar.csv"
    if calendar is not None:
        pd.DataFrame({"trade_date": list(calendar)}).to_csv(cal, index=False)
    for sym, frame in (contracts or {}).items():
        _write_parquet(lake / f"{sym}.parquet", frame)
    if spot is not None:
        _write_parquet(quotes / spot_dir / "000300.SH.parquet", spot)
    return FuturesStorageManager(
        lake_dir=lake, quotes_dir=quotes, trade_calendar_path=cal
    )


def _install_reader(monkeypatch, resolver) -> None:
    """Replace mootdx ``FinancialReader`` with a stub keyed by file name."""

    class _FakeReader:
        @staticmethod
        def to_data(path):
            return resolver(Path(path).name)

    monkeypatch.setattr(ifin, "FinancialReader", _FakeReader)


def _make_cw(tmp_path: Path, names) -> Path:
    cw = Path(tmp_path) / "tdx" / "vipdoc" / "cw"
    cw.mkdir(parents=True, exist_ok=True)
    for name in names:
        (cw / name).write_bytes(b"stub")
    return cw


@pytest.fixture
def make_importer(tmp_path, monkeypatch):
    """Factory that builds hermetic TDXFinancialImporter instances.

    The default fingerprint file is redirected into ``tmp_path`` so no test
    ever writes to the repository's real ``data/`` directory.
    """
    fp_paths = iter(tmp_path / f"fingerprint_{i}.json" for i in count())
    real_fingerprint = ifin.FinancialFingerprint

    def _factory():
        return real_fingerprint(next(fp_paths))

    monkeypatch.setattr(ifin, "FinancialFingerprint", _factory)

    def _make(**kwargs):
        kwargs.setdefault("tdx_dir", tmp_path / "tdx")
        kwargs.setdefault("output_dir", tmp_path / "lake" / "financial")
        kwargs.setdefault("stock_codes_file", tmp_path / "no_such_codes.csv")
        return ifin.TDXFinancialImporter(**kwargs)

    return _make


# =========================================================================
# FuturesStorageManager
# =========================================================================

class TestFuturesStorageManager:
    def test_continuous_contract_metadata_and_properties(self, tmp_path):
        mgr = _manager(tmp_path)
        cont = mgr.get_contract("IC0")
        assert cont.underlying == "000905.SH"
        assert cont.multiplier == 200.0
        assert cont.margin_ratio == 0.12
        assert cont.expiry_date == pd.Timestamp("2099-12-31")
        assert cont.variety == "IC"
        assert cont.delivery_month == ""  # no YYMM digits for continuous series

    def test_get_contract_unknown_variety_and_cache(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr.get_contract("XX2406") is None  # monthly, unknown variety
        assert mgr.get_contract("XX0") is None  # continuous, unknown variety
        assert mgr.get_contract("IF") is None  # no digits at all

        first = mgr.get_contract("IF2406")
        cached = mgr.get_contract("if2406.cfx")
        assert cached is first  # case/suffix insensitive cache hit
        assert first.underlying == "000300.SH"
        assert first.expiry_date == calculate_third_friday(2024, 6)

    def test_expiry_rolls_forward_on_holiday(self, tmp_path):
        mgr = _manager(tmp_path, calendar=["2024-06-24", "2024-06-25"])
        assert mgr.get_contract("IF2406").expiry_date == pd.Timestamp("2024-06-24")

    def test_expiry_kept_when_calendar_has_no_later_date(self, tmp_path):
        mgr = _manager(tmp_path / "b", calendar=["2020-01-02"])
        assert mgr.get_contract("IF2406").expiry_date == pd.Timestamp("2024-06-21")

    def test_expiry_without_calendar_file(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr._get_trade_calendar() is None
        assert mgr.get_contract("IF2406").expiry_date == pd.Timestamp("2024-06-21")

    def test_expiry_with_empty_calendar(self, tmp_path):
        cal = tmp_path / "cal.csv"
        cal.write_text("trade_date\n")
        mgr = FuturesStorageManager(
            lake_dir=tmp_path / "l",
            quotes_dir=tmp_path / "q",
            trade_calendar_path=cal,
        )
        assert mgr.get_contract("IF2406").expiry_date == pd.Timestamp("2024-06-21")

    def test_trade_calendar_read_failure_is_swallowed(self, tmp_path):
        cal_dir = tmp_path / "cal_is_a_dir.csv"
        cal_dir.mkdir()
        mgr = FuturesStorageManager(
            lake_dir=tmp_path / "l",
            quotes_dir=tmp_path / "q",
            trade_calendar_path=cal_dir,
        )
        assert mgr._get_trade_calendar() is None
        assert mgr.get_contract("IF2406").expiry_date == pd.Timestamp("2024-06-21")

    def test_contract_chain_filters_by_expiry_and_presence(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0]),
                "IF2406": _contract_frame(["2024-03-15"], [3450.0]),
                "IF2409": _contract_frame(["2024-03-01"], [3500.0]),  # no row today
                "IF2312": _contract_frame(["2024-03-15"], [3300.0]),  # expired
                "IF0": _contract_frame(["2024-03-15"], [3400.0]),  # continuous
            },
        )
        assert mgr.get_contract_chain("999999.SZ", pd.Timestamp("2024-03-15")) == []
        chain = mgr.get_contract_chain("000300.SH", pd.Timestamp("2024-03-15"))
        assert [c.clean_symbol for c in chain] == ["IF2403", "IF2406"]

    def test_dominant_contract_scores_on_hold_and_volume(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(
                    ["2024-03-15"], [3400.0], volumes=[100], holds=[900]
                ),
                "IF2406": _contract_frame(
                    ["2024-03-15"], [3450.0], volumes=[800], holds=[100]
                ),
            },
        )
        assert (
            mgr.get_dominant_contract("000300.SH", pd.Timestamp("2024-03-15"))
            == "IF2403"
        )
        assert mgr.get_dominant_contract("999999.SZ", pd.Timestamp("2024-03-15")) is None

    def test_read_futures_daily_missing_and_cache(self, tmp_path):
        mgr = _manager(
            tmp_path, contracts={"IF2406": _contract_frame(["2024-03-15"], [3400.0])}
        )
        assert mgr.read_futures_daily("ZZ9999").empty
        loaded = mgr.read_futures_daily("if2406.cfx")
        assert mgr._data_cache["IF2406"] is loaded
        assert mgr.read_futures_daily("IF2406") is loaded

    def test_read_futures_daily_corrupt_file_returns_empty(self, tmp_path):
        mgr = _manager(tmp_path)
        bad = tmp_path / "futures" / "IF2406.parquet"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not a parquet file")
        assert mgr.read_futures_daily("IF2406").empty

    def test_read_spot_daily_cache_and_missing(self, tmp_path):
        spot = pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]})
        mgr = _manager(tmp_path, spot=spot)
        loaded = mgr.read_spot_daily("000300.SH")
        assert not loaded.empty
        assert mgr.read_spot_daily("000300.SH") is loaded  # cache hit
        assert mgr.read_spot_daily("000016.SH").empty  # neither path exists

    def test_read_spot_daily_falls_back_to_daily_dir(self, tmp_path):
        spot = pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]})
        mgr = _manager(tmp_path, spot=spot, spot_dir="daily")
        assert not mgr.read_spot_daily("000300.SH").empty

    def test_read_spot_daily_corrupt_file_returns_empty(self, tmp_path):
        mgr = _manager(tmp_path)
        bad = tmp_path / "quotes" / "index" / "000300.SH.parquet"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"garbage")
        assert mgr.read_spot_daily("000300.SH").empty

    def test_basis_surface_missing_spot_raises(self, tmp_path):
        mgr = _manager(tmp_path)
        with pytest.raises(ValueError, match="无法读取标的"):
            mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))

    def test_basis_surface_spot_without_date_raises(self, tmp_path):
        spot = pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]})
        mgr = _manager(tmp_path, spot=spot)
        with pytest.raises(ValueError, match="无现货数据"):
            mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-20"))

    def test_basis_surface_full_detail_and_month_labels(self, tmp_path):
        contracts = {}
        spec = [
            ("IF2403", 3400.0, 3390.0, 1000, 500),
            ("IF2406", 3450.0, 3440.0, 800, 600),
            ("IF2409", 3480.0, 3470.0, 500, 400),
            ("IF2412", 3500.0, 3490.0, 300, 200),
            ("IF2503", 3520.0, 3510.0, 200, 100),
            ("IF2506", 3540.0, 3530.0, 100, 50),
        ]
        for sym, close, settle, vol, hold in spec:
            contracts[sym] = _contract_frame(
                ["2024-03-15"], [close], settles=[settle],
                volumes=[vol], holds=[hold],
            )
        spot = pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]})
        mgr = _manager(tmp_path, contracts=contracts, spot=spot)

        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        months = [c["contract_month"] for c in surface["contracts"]]
        assert months == [
            "current", "next", "quarter", "next_quarter", "far_quarter", "term_6"
        ]
        first = surface["contracts"][0]
        assert first["symbol"] == "IF2403"
        assert first["dte"] == 0
        assert first["futures_settle"] == 3390.0
        assert first["open_interest"] == 500
        assert first["volume"] == 1000
        assert first["basis"] == pytest.approx(-100.0)
        assert first["basis_rate_pct"] == pytest.approx(-100.0 / 3500.0 * 100.0)
        # dte is clamped to 1 in the ACT/365 denominator
        assert first["annualized_carry"] == pytest.approx(-100.0 / 3500.0 * 365.0)
        assert surface["spot_close"] == 3500.0
        assert surface["dominant_symbol"] == "IF2403"
        assert surface["dominant_basis"] == pytest.approx(-100.0)
        assert surface["term_slope"] > 0.0

    def test_basis_surface_settle_falls_back_to_close(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={"IF2403": _contract_frame(["2024-03-15"], [3400.0])},
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert surface["contracts"][0]["futures_settle"] == 3400.0

    def test_basis_surface_zero_spot_gives_zero_rates(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0], settles=[3390.0])
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [0.0]}),
        )
        item = mgr.get_dynamic_basis_surface(
            "000300.SH", pd.Timestamp("2024-03-15")
        )["contracts"][0]
        assert item["basis"] == 3400.0
        assert item["basis_rate_pct"] == 0.0
        assert item["annualized_carry"] == 0.0

    def test_basis_surface_skips_non_finite_close_contract(self, tmp_path):
        """§7.4 #2: a NaN close makes the contract row unusable, so it is dropped
        (same class as a missing row) instead of leaking a NaN basis / term_slope
        into the basis-surface lake."""
        nan = float("nan")
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(
                    ["2024-03-15"], [nan], settles=[nan], volumes=[100], holds=[900]
                ),
                "IF2406": _contract_frame(
                    ["2024-03-15"], [3450.0], settles=[3440.0],
                    volumes=[100], holds=[100],
                ),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert [c["symbol"] for c in surface["contracts"]] == ["IF2406"]
        assert all(math.isfinite(c["basis"]) for c in surface["contracts"])
        assert math.isfinite(surface["term_slope"])
        assert surface["term_slope"] == 0.0  # single usable contract => no slope

    def test_basis_surface_non_finite_spot_close_raises(self, tmp_path):
        """§7.4 #2: a NaN spot close is as unusable as a missing spot row."""
        nan = float("nan")
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0], settles=[3390.0]),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [nan]}),
        )
        with pytest.raises(ValueError, match="非有限值"):
            mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))

    def test_basis_surface_non_finite_fit_falls_back_to_zero(self, tmp_path, monkeypatch):
        """§7.4 #2: polyfit can return NaN without raising, so the finite check
        (not just try/except) must degrade the slope to 0.0."""
        import uniquant.data.lake.futures_storage_manager as fsm

        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0], settles=[3390.0]),
                "IF2406": _contract_frame(["2024-03-15"], [3450.0], settles=[3440.0]),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        monkeypatch.setattr(
            fsm.np, "polyfit", lambda *a, **k: (float("nan"), float("nan"))
        )
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert len(surface["contracts"]) == 2
        assert surface["term_slope"] == 0.0

    def test_basis_surface_degenerate_term_slope_falls_back_to_zero(
        self, tmp_path, monkeypatch
    ):
        """When the term-structure fit fails the slope degrades to 0.0."""
        import uniquant.data.lake.futures_storage_manager as fsm

        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0], settles=[3390.0]),
                "IF2406": _contract_frame(["2024-03-15"], [3450.0], settles=[3440.0]),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )

        def _raise(*_args, **_kwargs):
            raise ValueError("fit failed")

        monkeypatch.setattr(fsm.np, "polyfit", _raise)
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert len(surface["contracts"]) == 2
        assert surface["term_slope"] == 0.0

    def test_basis_surface_no_contracts(self, tmp_path):
        mgr = _manager(
            tmp_path,
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert surface["contracts"] == []
        assert surface["dominant_symbol"] == ""
        assert surface["term_slope"] == 0.0

    def test_basis_surface_skips_chain_contract_without_row(self, tmp_path, monkeypatch):
        mgr = _manager(
            tmp_path,
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        contract = mgr.get_contract("IF2403")
        empty = pd.DataFrame(
            {"date": pd.to_datetime([]), "close": [], "settle": [], "volume": [], "hold": []}
        )
        monkeypatch.setattr(mgr, "get_contract_chain", lambda u, d: [contract])
        monkeypatch.setattr(mgr, "get_dominant_contract", lambda u, d: None)
        monkeypatch.setattr(mgr, "read_futures_daily", lambda sym: empty)
        surface = mgr.get_dynamic_basis_surface("000300.SH", pd.Timestamp("2024-03-15"))
        assert surface["contracts"] == []

    def test_mlsi_deep_discount_floors_phi_and_ranks_weights(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(
                    ["2024-03-15"], [3400.0], settles=[3390.0],
                    volumes=[900], holds=[900],
                ),
                "IF2406": _contract_frame(
                    ["2024-03-15"], [3450.0], settles=[3440.0],
                    volumes=[100], holds=[100],
                ),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        beta, weights = mgr.compute_mlsi_hedge_ratio(
            "000300.SH", 2.0, pd.Timestamp("2024-03-15")
        )
        assert beta == pytest.approx(2.0 * 0.75)  # phi floored at 0.75
        # best (least-negative) carry gets 70%, runner-up 30%
        assert weights == pytest.approx({"IF2406": 0.70, "IF2403": 0.30})

    def test_mlsi_premium_caps_phi(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(
                    ["2024-03-15"], [3600.0], settles=[3590.0],
                    volumes=[900], holds=[900],
                ),
                "IF2406": _contract_frame(
                    ["2024-03-15"], [3550.0], settles=[3540.0],
                    volumes=[100], holds=[100],
                ),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        beta, weights = mgr.compute_mlsi_hedge_ratio(
            "000300.SH", 1.0, pd.Timestamp("2024-03-15")
        )
        assert beta == pytest.approx(1.15)  # phi capped at 1.15
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_mlsi_normal_band_single_contract_weight(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2406": _contract_frame(["2024-03-15"], [3480.0], settles=[3470.0])
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        beta, weights = mgr.compute_mlsi_hedge_ratio(
            "000300.SH", 1.0, pd.Timestamp("2024-03-15")
        )
        assert beta == pytest.approx(1.0)
        assert weights == {"IF2406": 1.0}

    def test_mlsi_steep_negative_slope_lowers_phi(self, tmp_path):
        mgr = _manager(
            tmp_path,
            contracts={
                "IF2403": _contract_frame(
                    ["2024-03-15"], [3498.0], settles=[3490.0],
                    volumes=[900], holds=[900],
                ),
                "IF2406": _contract_frame(
                    ["2024-03-15"], [3000.0], settles=[2990.0],
                    volumes=[10], holds=[10],
                ),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        beta, _ = mgr.compute_mlsi_hedge_ratio(
            "000300.SH", 1.0, pd.Timestamp("2024-03-15")
        )
        assert beta == pytest.approx(0.95)  # slope_adj = -0.05

    def test_build_lake_requires_trade_calendar(self, tmp_path):
        mgr = _manager(tmp_path)
        with pytest.raises(RuntimeError, match="缺失交易日历"):
            mgr.build_basis_surface_lake()

    def test_build_lake_without_data_returns_empty(self, tmp_path):
        mgr = _manager(tmp_path, calendar=["2024-03-15"])
        out = mgr.build_basis_surface_lake()  # underlyings defaults to all
        assert out.empty
        assert not (mgr.lake_dir / "basis_surface").exists()

    def test_build_lake_writes_sorted_parquet_atomically(self, tmp_path):
        mgr = _manager(
            tmp_path,
            calendar=["2024-03-14", "2024-03-15"],
            contracts={
                "IF2403": _contract_frame(["2024-03-15"], [3400.0], settles=[3390.0]),
                "IF2406": _contract_frame(["2024-03-15"], [3450.0], settles=[3440.0]),
            },
            spot=pd.DataFrame({"date": ["2024-03-15"], "close": [3500.0]}),
        )
        out = mgr.build_basis_surface_lake(
            start_date="2024-03-15",
            end_date="2024-03-15",
            underlyings=["000300.SH"],
        )
        path = mgr.lake_dir / "basis_surface" / "basis_surface_daily.parquet"
        assert path.exists()
        assert not (mgr.lake_dir / "basis_surface" / "basis_surface_daily.parquet.tmp").exists()

        written = pd.read_parquet(path)
        assert len(written) == 2
        assert list(written["contract_symbol"]) == ["IF2403", "IF2406"]  # sorted by dte
        assert (written["underlying"] == "000300.SH").all()
        assert (written["spot_close"] == 3500.0).all()
        expected_cols = {
            "date", "underlying", "contract_symbol", "contract_month",
            "spot_close", "futures_close", "futures_settle", "dte", "basis",
            "basis_rate_pct", "annualized_carry", "open_interest", "volume",
            "term_slope",
        }
        assert expected_cols.issubset(set(written.columns))
        assert out.equals(written)


# =========================================================================
# FinancialFingerprint
# =========================================================================

class TestFinancialFingerprint:
    def test_load_missing_and_corrupt(self, tmp_path):
        assert ifin.FinancialFingerprint(tmp_path / "none.json")._fingerprints == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert ifin.FinancialFingerprint(bad)._fingerprints == {}

    def test_save_roundtrip(self, tmp_path):
        path = tmp_path / "fp.json"
        fp = ifin.FinancialFingerprint(path)
        target = tmp_path / "gpcw.dat"
        target.write_bytes(b"abc")
        fp.update(target, record_count=7, success=True)
        fp.save()

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk[target.name]["records"] == 7
        assert on_disk[target.name]["status"] == "success"
        assert ifin.FinancialFingerprint(path)._fingerprints == on_disk

    def test_is_update_needed_branches(self, tmp_path):
        fp = ifin.FinancialFingerprint(tmp_path / "fp.json")
        target = tmp_path / "gpcw.dat"
        target.write_bytes(b"1234")
        assert fp.is_update_needed(target) is True  # unknown file

        fp.update(target, 1, success=False)
        assert fp.is_update_needed(target) is True  # previous run failed

        fp.update(target, 1, success=True)
        assert fp.is_update_needed(target) is False  # unchanged mtime/size

        target.write_bytes(b"12345")  # changed
        assert fp.is_update_needed(target) is True

        target.unlink()
        assert fp.is_update_needed(target) is True  # OSError on stat

    def test_update_on_missing_file_is_noop(self, tmp_path):
        fp = ifin.FinancialFingerprint(tmp_path / "fp.json")
        fp.update(tmp_path / "ghost.dat", 5, success=True)
        assert fp._fingerprints == {}

    def test_get_stats(self, tmp_path):
        fp = ifin.FinancialFingerprint(tmp_path / "fp.json")
        a = tmp_path / "a.dat"
        a.write_bytes(b"a")
        b = tmp_path / "b.dat"
        b.write_bytes(b"b")
        fp.update(a, 1, success=True)
        fp.update(b, 0, success=False)
        assert fp.get_stats() == {"total": 2, "success": 1, "failed": 1}


# =========================================================================
# TDXFinancialImporter
# =========================================================================

class TestImportFinancialHelpers:
    def test_market_suffix_and_all_stock_codes_format(self, make_importer):
        imp = make_importer()
        assert imp._get_market_suffix("600000") == "SH"
        assert imp._get_market_suffix("300001") == "SZ"
        assert imp._get_market_suffix("430001") == "BJ"
        assert imp._get_market_suffix("990001") is None

        assert imp._to_all_stock_codes_format("600000.SH") == "sh.600000"
        assert imp._to_all_stock_codes_format("000001.SZ") == "sz.000001"
        assert imp._to_all_stock_codes_format("430001.BJ") == "bj.430001"
        assert imp._to_all_stock_codes_format("600000.XX") is None
        assert imp._to_all_stock_codes_format("600000") is None
        assert imp._to_all_stock_codes_format("") is None

    def test_normalize_stock_code_variants(self, make_importer):
        imp = make_importer()
        assert imp._normalize_stock_code(float("nan")) is None
        assert imp._normalize_stock_code("   ") is None
        assert imp._normalize_stock_code("sh.600000") == "600000.SH"
        assert imp._normalize_stock_code("600000.SH") == "600000.SH"
        assert imp._normalize_stock_code("1600000") == "600000.SH"  # keeps last 6
        assert imp._normalize_stock_code("123456") is None  # unknown prefix

    def test_load_allowed_codes_missing_bad_and_headerless(self, tmp_path, make_importer):
        imp = make_importer(stock_codes_file=tmp_path / "missing.csv")
        assert imp.allowed_stock_codes == set()
        assert imp.is_allowed_security("600000.SH") is True  # empty -> allow all

        bad_dir = tmp_path / "codes_dir"
        bad_dir.mkdir()
        assert make_importer(stock_codes_file=bad_dir).allowed_stock_codes == set()

        headerless = tmp_path / "no_cols.csv"
        pd.DataFrame({"foo": [1], "bar": [2]}).to_csv(headerless, index=False)
        assert make_importer(stock_codes_file=headerless).allowed_stock_codes == set()

    def test_load_allowed_codes_without_status_column(self, tmp_path, make_importer):
        codes = tmp_path / "codes.csv"
        pd.DataFrame(
            {"code": ["sz.000001", "sh.000001"], "type": [1, 2]}
        ).to_csv(codes, index=False)
        imp = make_importer(stock_codes_file=codes)
        assert imp.allowed_stock_codes == {"000001.SZ"}
        assert imp.is_allowed_security("000001.SH") is False

    def test_normalize_date_column_formats(self, make_importer):
        imp = make_importer()
        out = imp._normalize_date_column(
            pd.Series(["20240331", "240331", "2024-03-31", "bad"])
        )
        assert out.iloc[0] == pd.Timestamp("2024-03-31")
        assert out.iloc[1] == pd.Timestamp("2024-03-31")
        assert out.iloc[2] == pd.Timestamp("2024-03-31")
        assert pd.isna(out.iloc[3])

    def test_normalize_financial_df_drops_unmappable_and_nat(self, make_importer):
        imp = make_importer()  # no whitelist -> no code filtering
        df = pd.DataFrame(
            {
                "code": ["600000", "990001", float("nan")],
                "report_date": ["20240331", "20240331", "not-a-date"],
                "v": [1, 2, 3],
            }
        )
        out = imp._normalize_financial_df(df)
        assert out["code"].tolist() == ["600000.SH"]
        assert out["report_date"].tolist() == [pd.Timestamp("2024-03-31")]

    def test_normalize_financial_df_drops_invalid_report_dates(self, make_importer):
        imp = make_importer()
        df = pd.DataFrame({"report_date": ["20240331", "bad"], "v": [1, 2]})
        out = imp._normalize_financial_df(df)
        assert out["report_date"].tolist() == [pd.Timestamp("2024-03-31")]

    def test_fix_duplicate_columns(self, make_importer):
        imp = make_importer()
        df = pd.DataFrame([[1, 2, 3]], columns=["code", "code", "code"])
        out = imp._fix_duplicate_columns(df)
        assert list(out.columns) == ["code", "code_1", "code_2"]


class TestImportFinancialParsing:
    def test_parse_gpcw_file_none_and_empty(self, tmp_path, monkeypatch, make_importer):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")

        _install_reader(monkeypatch, lambda name: None)
        assert imp._parse_gpcw_file(f) is None

        _install_reader(monkeypatch, lambda name: pd.DataFrame())
        assert imp._parse_gpcw_file(f) is None

    def test_parse_gpcw_file_resets_index_and_normalizes(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")
        raw = pd.DataFrame(
            {"基本每股收益": [1.2]}, index=pd.Index(["sz.000001"], name="code")
        )
        _install_reader(monkeypatch, lambda name: raw)

        out = imp._parse_gpcw_file(f)
        assert out["code"].tolist() == ["000001.SZ"]
        assert "基本每股收益" in out.columns

    def test_parse_gpcw_file_reader_exception_returns_none(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw.dat"
        f.write_bytes(b"x")

        def boom(_name):
            raise OSError("boom")

        _install_reader(monkeypatch, boom)
        assert imp._parse_gpcw_file(f) is None

    def test_process_file_skips_non_gpcw(self, tmp_path, make_importer):
        imp = make_importer()
        other = tmp_path / "random.dat"
        other.write_bytes(b"x")
        assert imp._process_file_to_memory(other) == (False, "skipped", 0)

    def test_process_file_skips_unchanged_until_forced(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")
        imp.fingerprint.update(f, 10, success=True)
        assert imp._process_file_to_memory(f) == (True, "skipped", 0)

        _install_reader(
            monkeypatch,
            lambda name: pd.DataFrame({"code": ["600000"], "report_date": ["20231231"]}),
        )
        assert imp._process_file_to_memory(f, force=True) == (True, "parsed", 1)

    def test_process_file_empty_and_no_code_mark_failure(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")
        _install_reader(monkeypatch, lambda name: pd.DataFrame())
        assert imp._process_file_to_memory(f) == (False, "empty", 0)
        assert imp.fingerprint._fingerprints[f.name]["status"] == "failed"

        imp2 = make_importer()
        f2 = tmp_path / "gpcw20240630.dat"
        f2.write_bytes(b"x")
        _install_reader(
            monkeypatch,
            lambda name: pd.DataFrame({"v": [1], "report_date": ["20240630"]}),
        )
        assert imp2._process_file_to_memory(f2) == (False, "no_code", 0)
        assert imp2.fingerprint._fingerprints[f2.name]["status"] == "failed"

    def test_process_file_exception_marks_failure(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")
        _install_reader(monkeypatch, lambda name: pd.DataFrame({"code": ["600000"]}))

        def boom(_df):
            raise RuntimeError("boom")

        monkeypatch.setattr(imp, "_fix_duplicate_columns", boom)
        assert imp._process_file_to_memory(f) == (False, "failed", 0)
        assert imp.fingerprint._fingerprints[f.name]["status"] == "failed"

    def test_process_file_aggregates_memory_per_code(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        f = tmp_path / "gpcw20231231.dat"
        f.write_bytes(b"x")
        raw = pd.DataFrame(
            {
                "code": ["600000", "000001", "600000"],
                "report_date": ["20231231", "20231231", "20231231"],
                "v": [1, 2, 3],
            }
        )
        _install_reader(monkeypatch, lambda name: raw)

        ok, status, stored = imp._process_file_to_memory(f)
        assert (ok, status, stored) == (True, "parsed", 2)
        assert set(imp._memory_store.keys()) == {"600000.SH", "000001.SZ"}
        assert imp.fingerprint._fingerprints[f.name]["records"] == 3


class TestImportFinancialWriting:
    def test_write_single_stock_rejects_empty_and_bad_code(self, tmp_path, make_importer):
        imp = make_importer()
        assert imp._write_single_stock("600000", []) is False
        bad = pd.DataFrame({"code": ["990000"]})
        assert imp._write_single_stock("990000", [bad]) is False

    def test_write_single_stock_dedups_and_sorts(self, tmp_path, make_importer):
        imp = make_importer()
        imp.output_dir.mkdir(parents=True, exist_ok=True)
        dfs = [
            pd.DataFrame({"code": ["600000"], "report_date": ["20231231"], "v": [1]}),
            pd.DataFrame({"code": ["600000"], "report_date": ["20231231"], "v": [2]}),
            pd.DataFrame({"code": ["600000"], "report_date": ["20230930"], "v": [0]}),
        ]
        assert imp._write_single_stock("600000", dfs) is True

        written = pd.read_parquet(imp.output_dir / "600000.SH.parquet")
        assert written["report_date"].tolist() == [
            pd.Timestamp("2023-09-30"),
            pd.Timestamp("2023-12-31"),
        ]
        # keep="last" retains the later duplicate value
        dup = written[written["report_date"] == pd.Timestamp("2023-12-31")]
        assert dup["v"].iloc[0] == 2

    def test_write_single_stock_io_failure_raises(self, tmp_path, make_importer):
        """§7.4 #3: a genuine IO failure propagates (it used to be swallowed into
        the same ``False`` as an intentional skip, hiding total write failure)."""
        blocker = tmp_path / "blocked"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")
        imp = make_importer(output_dir=blocker)
        df = pd.DataFrame({"code": ["600000"], "report_date": ["20231231"], "v": [1]})
        with pytest.raises(OSError):
            imp._write_single_stock("600000", [df])

    def test_write_single_stock_skips_disallowed_security(self, tmp_path, make_importer):
        codes = tmp_path / "codes.csv"
        pd.DataFrame({"code": ["sz.000001"], "type": [1]}).to_csv(codes, index=False)
        imp = make_importer(stock_codes_file=codes)
        imp.output_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({"code": ["600000"], "report_date": ["20231231"], "v": [1]})
        assert imp._write_single_stock("600000", [df]) is False
        assert not (imp.output_dir / "600000.SH.parquet").exists()


class TestImportFinancialBatch:
    def test_import_batch_no_files(self, tmp_path, make_importer):
        imp = make_importer()
        imp.cw_dir.mkdir(parents=True, exist_ok=True)
        assert imp.import_batch() == (0, 0, 0)

    def test_import_batch_end_to_end_skip_and_force(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20231231.dat", "gpcw20230930.dat"])
        mapping = {
            "gpcw20231231.dat": pd.DataFrame(
                {"code": ["600000", "000001"], "report_date": ["20231231", "20231231"], "v": [1, 2]}
            ),
            "gpcw20230930.dat": pd.DataFrame(
                {"code": ["600000"], "report_date": ["20230930"], "v": [3]}
            ),
        }
        _install_reader(monkeypatch, lambda name: mapping.get(name))

        assert imp.import_batch(workers=2) == (2, 0, 0)
        assert (imp.output_dir / "600000.SH.parquet").exists()
        assert (imp.output_dir / "000001.SZ.parquet").exists()
        assert imp._memory_store == {}  # cleared after run

        # Fingerprints persisted -> a second run skips everything.
        assert imp.import_batch(workers=2) == (0, 2, 0)
        # force re-parses.
        assert imp.import_batch(workers=2, force=True) == (2, 0, 0)

    def test_import_batch_limit(self, tmp_path, monkeypatch, make_importer):
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20230930.dat", "gpcw20231231.dat"])
        _install_reader(
            monkeypatch,
            lambda name: pd.DataFrame({"code": ["600000"], "report_date": ["20231231"], "v": [1]}),
        )
        assert imp.import_batch(limit=1) == (1, 0, 0)

    def test_import_batch_worker_exception_counted_as_failure(
        self, tmp_path, monkeypatch, make_importer
    ):
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20231231.dat"])

        def boom(_filepath, force=False):
            raise RuntimeError("boom")

        monkeypatch.setattr(imp, "_process_file_to_memory", boom)
        assert imp.import_batch(workers=1) == (0, 0, 1)

    def test_import_batch_parse_failure_counted(self, tmp_path, monkeypatch, make_importer):
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20231231.dat"])
        _install_reader(monkeypatch, lambda name: pd.DataFrame())
        assert imp.import_batch(workers=1) == (0, 0, 1)

    def test_import_batch_write_failure_is_counted_as_failure(
        self, tmp_path, monkeypatch, make_importer
    ):
        """§7.4 #3: a genuine write failure is counted in the returned failure total
        (previously the batch reported pure success)."""
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20231231.dat"])
        _install_reader(
            monkeypatch,
            lambda name: pd.DataFrame({"code": ["600000"], "report_date": ["20231231"]}),
        )

        def _boom(code, dfs):
            raise OSError("disk full")

        monkeypatch.setattr(imp, "_write_single_stock", _boom)

        logged = []
        monkeypatch.setattr(ifin.logger, "info", lambda msg, *a, **k: logged.append(msg))
        result = imp.import_batch(workers=1)

        assert result == (1, 0, 1)
        assert "写入完成：成功 0, 跳过 0, 失败 1" in logged

    def test_import_batch_write_skip_is_not_a_failure(
        self, tmp_path, monkeypatch, make_importer
    ):
        """A rule-based skip stays a skip and must NOT inflate the failure total."""
        imp = make_importer()
        _make_cw(tmp_path, ["gpcw20231231.dat"])
        _install_reader(
            monkeypatch,
            lambda name: pd.DataFrame({"code": ["600000"], "report_date": ["20231231"]}),
        )
        monkeypatch.setattr(imp, "_write_single_stock", lambda code, dfs: False)

        logged = []
        monkeypatch.setattr(ifin.logger, "info", lambda msg, *a, **k: logged.append(msg))
        result = imp.import_batch(workers=1)

        assert result == (1, 0, 0)
        assert "写入完成：成功 0, 跳过 1, 失败 0" in logged


class TestImportFinancialCli:
    def test_main_returns_zero_on_success(self, monkeypatch):
        calls = {}

        class _FakeImporter:
            def import_batch(self, limit=0, force=False, workers=ifin.MAX_WORKERS):
                calls["kwargs"] = {"limit": limit, "force": force, "workers": workers}
                return (2, 1, 0)

        monkeypatch.setattr(ifin, "TDXFinancialImporter", _FakeImporter)
        monkeypatch.setattr(
            "sys.argv", ["import_financial", "--force", "-n", "3", "-w", "2"]
        )
        assert ifin.main() == 0
        assert calls["kwargs"] == {"limit": 3, "force": True, "workers": 2}

    def test_main_returns_one_on_failure(self, monkeypatch):
        class _FakeImporter:
            def import_batch(self, limit=0, force=False, workers=ifin.MAX_WORKERS):
                return (0, 0, 1)

        monkeypatch.setattr(ifin, "TDXFinancialImporter", _FakeImporter)
        monkeypatch.setattr("sys.argv", ["import_financial"])
        assert ifin.main() == 1
