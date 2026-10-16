"""``data/lake/storage_manager.py`` — 湖存储行为测试.

补充 ``tests/test_storage_freshness_sla.py`` (两级 SLA) 与
``tests/test_baostock_decouple.py`` (R-5 硬失败), 本文件覆盖: 模块级辅助
(指数判定 / NaN / 日期格式化)、parquet 原子读写与路径遍历防护、股票代码
规范化与后缀推断、日/周/月线合成、``_find_tdx_max_date`` 真实 .day 锚点、
``_get_file_path`` 分支、批量读与元数据。

纪律: 全部 I/O 走 ``tmp_path``, 绝不触碰真实 ``data/`` 数据湖。
"""

import struct
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.lake import storage_manager as sm_mod
from uniquant.data.lake.storage_manager import (
    StorageManager,
    _format_date_val,
    _isnan_symbol,
    is_index_symbol,
)

_DAY_HEADER = "code,name\n"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "all_stock_codes.csv").write_text(
        _DAY_HEADER
        + "sh.600519,贵州茅台\n"
        + "sz.000001,平安银行\n"
        + "sz.399001,深证成指\n"
        + "sh.000001,上证指数\n"
        + "bj.830799,艾融软件\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def sm(data_dir: Path) -> StorageManager:
    return StorageManager(data_dir=str(data_dir))


def _daily_frame(dates, **cols):
    base = {
        "date": list(dates),
        "open": [10.0, 11.0, 20.0, 21.0][: len(dates)],
        "high": [15.0, 12.0, 25.0, 22.0][: len(dates)],
        "low": [9.0, 8.0, 19.0, 18.0][: len(dates)],
        "close": [12.0, 13.0, 22.0, 23.0][: len(dates)],
        "volume": [100.0, 200.0, 300.0, 400.0][: len(dates)],
        "amount": [1000.0, 2000.0, 3000.0, 4000.0][: len(dates)],
    }
    base.update(cols)
    return pd.DataFrame(base)


def _write_day_file(path: Path, last_date: int, records: int = 2) -> None:
    """写出可被 ``_find_tdx_max_date`` 读取的合成 .day 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = b""
    for i in range(records):
        d = last_date - (records - 1 - i)
        buf += struct.pack("<IIIIIfii", d, 1000, 1100, 900, 1050, 1e6, 100, 0)
    path.write_bytes(buf)


# ── module helpers ────────────────────────────────────────────────────────


class TestIsIndexSymbol:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("000001.SH", True),   # 上证指数
            ("399001.SZ", True),   # 深证成指
            ("000001.SZ", False),  # 平安银行 (SZ 主板股票, 非指数)
            ("600000.SH", False),
            ("830799.BJ", False),
            (None, False),
            (float("nan"), False),
            ("00001.SH", False),    # 非 6 位
            ("ABCDEF.SH", False),   # 非数字
            ("000001", False),      # 无交易所后缀
            ("", False),
        ],
    )
    def test_symbol_level_judgement(self, symbol, expected):
        assert is_index_symbol(symbol) is expected


class TestIsnanSymbol:
    def test_nan_true(self):
        assert _isnan_symbol(float("nan")) is True

    def test_regular_value_false(self):
        assert _isnan_symbol("600000.SH") is False

    def test_exception_swallowed_returns_false(self, monkeypatch):
        def _boom(_v):
            raise RuntimeError("no pandas")

        monkeypatch.setattr(pd, "isna", _boom)
        assert _isnan_symbol("x") is False


class TestFormatDateVal:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (float("nan"), None),
            (date(2024, 1, 2), "2024-01-02"),
            (datetime(2024, 1, 2, 15, 30), "2024-01-02"),
            (pd.Timestamp("2024-01-02"), "2024-01-02"),
            ("20240102", "2024-01-02"),
            ("2024-01-02", "2024-01-02"),
            ("  20240102  ", "2024-01-02"),
        ],
    )
    def test_formats(self, value, expected):
        assert _format_date_val(value) == expected

    def test_garbage_returns_none(self):
        assert _format_date_val("not-a-date") is None


# ── parquet primitives ────────────────────────────────────────────────────


class TestWriteParquet:
    def test_empty_frame_rejected(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "x.parquet"
        assert sm.write_parquet(str(target), pd.DataFrame()) is False
        assert not target.exists()

    def test_happy_write(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        df = pd.DataFrame({"date": [1], "close": [10.0]})
        assert sm.write_parquet(str(target), df) is True
        assert target.exists()

    def test_path_traversal_rejected(self, sm, tmp_path):
        """真正的目录外路径 → 拒绝。"""
        outside = tmp_path.parent / "totally_elsewhere" / "evil.parquet"
        assert sm.write_parquet(str(outside), pd.DataFrame({"close": [1.0]})) is False
        assert not outside.exists()

    def test_sibling_dir_with_shared_name_prefix_rejected(self, sm, data_dir):
        """回归: 兄弟目录名与 data_dir 共享前缀 (data → data_evil) 不得绕过护栏。

        旧实现用 ``str.startswith`` 做字符串前缀判定 → ``.../data_evil`` 被误判为
        ``.../data`` 之下; 现改为 ``Path.is_relative_to`` 的路径级包含判定。
        """
        sibling = data_dir.parent / (data_dir.name + "_evil") / "evil.parquet"
        assert sm.write_parquet(str(sibling), pd.DataFrame({"close": [1.0]})) is False
        assert not sibling.exists()

    def test_existing_file_skipped_when_not_overwrite(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        df = pd.DataFrame({"close": [1.0]})
        assert sm.write_parquet(str(target), df) is True
        assert sm.write_parquet(str(target), df.assign(close=[2.0])) is False
        assert pd.read_parquet(target)["close"].iloc[0] == 1.0

    def test_existing_file_replaced_when_overwrite(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        sm.write_parquet(str(target), pd.DataFrame({"close": [1.0]}))
        assert sm.write_parquet(str(target), pd.DataFrame({"close": [2.0]}), overwrite=True)
        assert pd.read_parquet(target)["close"].iloc[0] == 2.0

    def test_write_failure_returns_false(self, sm, data_dir, monkeypatch):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"

        def _boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", _boom)
        assert sm.write_parquet(str(target), pd.DataFrame({"close": [1.0]})) is False


class TestReadParquet:
    def test_missing_returns_empty(self, sm, tmp_path):
        assert sm.read_parquet(str(tmp_path / "nope.parquet")).empty

    def test_happy_read(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        sm.write_parquet(str(target), pd.DataFrame({"date": [1], "close": [10.0]}))
        out = sm.read_parquet(str(target))
        assert len(out) == 1

    def test_corrupt_file_returns_empty(self, sm, tmp_path):
        bad = tmp_path / "corrupt.parquet"
        bad.write_bytes(b"not a parquet at all")
        assert sm.read_parquet(str(bad)).empty


class TestDeleteListExists:
    def test_delete_missing_returns_true(self, sm, tmp_path):
        assert sm.delete_file(str(tmp_path / "nope.parquet")) is True

    def test_delete_removes_file_and_lock(self, sm, data_dir):
        target = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        sm.write_parquet(str(target), pd.DataFrame({"close": [1.0]}))
        lock = target.with_suffix(".parquet.lock")
        lock.write_text("")
        assert sm.delete_file(str(target)) is True
        assert not target.exists()
        assert not lock.exists()

    def test_list_files_filters_and_handles_missing(self, sm, data_dir):
        assert sm.list_files(str(data_dir / "nope")) == []
        d = data_dir / "lake" / "quotes" / "daily"
        (d / "a.parquet").write_bytes(b"x")
        (d / "b.txt").write_text("x")
        assert sm.list_files(str(d)) == ["a.parquet"]

    def test_file_exists(self, sm, data_dir):
        assert sm.file_exists(str(data_dir / "all_stock_codes.csv")) is True
        assert sm.file_exists(str(data_dir / "nope")) is False

    def test_ensure_directory_creates_nested(self, sm, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        sm.ensure_directory(str(nested))
        assert nested.is_dir()


# ── code normalisation ────────────────────────────────────────────────────


class TestLoadAllStockCodes:
    def test_missing_master_file_hard_fails(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            StorageManager(data_dir=str(tmp_path))

    def test_chinese_column_supported(self, tmp_path):
        (tmp_path / "all_stock_codes.csv").write_text(
            "代码\nsh.600519\nsz.000001\n", encoding="utf-8"
        )
        assert StorageManager(data_dir=str(tmp_path)).all_stock_codes == {
            "600519.SH",
            "000001.SZ",
        }

    def test_missing_both_columns_returns_empty_set(self, tmp_path):
        (tmp_path / "all_stock_codes.csv").write_text("foo\nbar\n", encoding="utf-8")
        assert StorageManager(data_dir=str(tmp_path)).all_stock_codes == set()

    def test_read_error_returns_empty_set(self, tmp_path, monkeypatch):
        (tmp_path / "all_stock_codes.csv").write_text(_DAY_HEADER, encoding="utf-8")

        def _boom(*_a, **_k):
            raise ValueError("bad csv")

        monkeypatch.setattr(pd, "read_csv", _boom)
        assert StorageManager(data_dir=str(tmp_path)).all_stock_codes == set()


class TestNormalizeStockCode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("600519.SH", "600519.SH"),
            ("SH.600519", "600519.SH"),
            ("600519.sh", "600519.SH"),
            ("600519", "600519.SH"),
            ("000001", "000001.SZ"),
            ("300750", "300750.SZ"),
            ("830799", "830799.BJ"),
            ("430047", "430047.BJ"),
            ("870508", "870508.BJ"),
            ("111111", "111111.SH"),  # 未知前缀 → 兜底 .SH
            ("  600519  ", "600519.SH"),
        ],
    )
    def test_normalisation_matrix(self, sm, raw, expected):
        assert sm._normalize_stock_code(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", float("nan")])
    def test_empty_inputs_return_none(self, sm, raw):
        assert sm._normalize_stock_code(raw) is None


class TestGetStockSuffix:
    def test_shanghai(self, sm):
        assert sm._get_stock_suffix("600519") == ".SH"

    def test_shenzhen_master_hit(self, sm):
        assert sm._get_stock_suffix("000001") == ".SZ"

    def test_shenzhen_falls_back_to_sh_when_only_sh_known(self, sm):
        sm.all_stock_codes = {"000001.SH"}
        assert sm._get_stock_suffix("000001") == ".SH"

    def test_shenzhen_default_when_unknown(self, sm):
        sm.all_stock_codes = set()
        assert sm._get_stock_suffix("000002") == ".SZ"

    def test_beijing(self, sm):
        assert sm._get_stock_suffix("830799") == ".BJ"

    def test_unknown_prefix_scans_master_then_returns_empty(self, sm):
        sm.all_stock_codes = {"777777.BJ"}
        assert sm._get_stock_suffix("777777") == ".BJ"
        sm.all_stock_codes = set()
        assert sm._get_stock_suffix("777777") == ""

    def test_lowercase_prefix_stripped(self, sm):
        assert sm._get_stock_suffix("sh600519") == ".SH"


# ── local raw / factor / save / has / symbols / clean ──────────────────────


class TestLocalReadWrite:
    def test_read_local_raw_prefers_standard_symbol(self, sm, data_dir):
        d = data_dir / "lake" / "quotes" / "daily"
        sm.write_parquet(str(d / "600519.SH.parquet"), pd.DataFrame({"close": [1.0]}))
        assert not sm.read_local_raw("600519").empty

    def test_read_local_raw_index_fallback_to_index_dir(self, sm, data_dir):
        idx = data_dir / "lake" / "quotes" / "index"
        sm.write_parquet(str(idx / "000001.SH.parquet"), pd.DataFrame({"close": [1.0]}))
        assert not sm.read_local_raw("000001.SH").empty

    def test_read_local_raw_missing_returns_empty(self, sm):
        assert sm.read_local_raw("999999").empty

    def test_read_local_factor(self, sm, data_dir):
        f = data_dir / "factors"
        sm.write_parquet(str(f / "600519.SH.parquet"), pd.DataFrame({"factor": [1.1]}))
        assert not sm.read_local_factor("600519").empty

    def test_read_local_factor_missing_returns_empty(self, sm):
        assert sm.read_local_factor("999999").empty

    def test_save_data_atomic_and_readable(self, sm, data_dir):
        assert sm.save_data("600519.SH", pd.DataFrame({"close": [1.0]})) is True
        assert (data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet").exists()

    def test_save_data_empty_frame_returns_false(self, sm):
        assert sm.save_data("600519.SH", pd.DataFrame()) is False

    def test_save_factor_atomic(self, sm, data_dir):
        assert sm.save_factor("600519.SH", pd.DataFrame({"factor": [1.0]})) is True
        assert (data_dir / "factors" / "600519.SH.parquet").exists()

    def test_save_factor_empty_frame_returns_false(self, sm):
        assert sm.save_factor("600519.SH", pd.DataFrame()) is False

    def test_has_data_daily_and_index(self, sm, data_dir):
        assert sm.has_data("600519.SH") is False
        sm.write_parquet(
            str(data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"),
            pd.DataFrame({"close": [1.0]}),
        )
        assert sm.has_data("600519.SH") is True
        sm.write_parquet(
            str(data_dir / "lake" / "quotes" / "index" / "000001.SH.parquet"),
            pd.DataFrame({"close": [1.0]}),
        )
        assert sm.has_data("000001.SH") is True

    def test_get_symbols_excludes_indices_by_default(self, sm, data_dir):
        d = data_dir / "lake" / "quotes" / "daily"
        idx = data_dir / "lake" / "quotes" / "index"
        sm.write_parquet(str(d / "600519.SH.parquet"), pd.DataFrame({"close": [1.0]}))
        sm.write_parquet(str(d / "000001.SH.parquet"), pd.DataFrame({"close": [1.0]}))
        sm.write_parquet(str(idx / "399001.SZ.parquet"), pd.DataFrame({"close": [1.0]}))
        assert sm.get_symbols() == ["600519.SH"]
        full = sm.get_symbols(exclude_indices=False)
        assert set(full) == {"600519.SH", "000001.SH", "399001.SZ"}

    def test_clean_data_removes_daily_and_factor(self, sm, data_dir):
        d = data_dir / "lake" / "quotes" / "daily" / "600519.SH.parquet"
        f = data_dir / "factors" / "600519.SH.parquet"
        sm.write_parquet(str(d), pd.DataFrame({"close": [1.0]}))
        sm.write_parquet(str(f), pd.DataFrame({"factor": [1.0]}))
        sm.clean_data("600519.SH")
        assert not d.exists() and not f.exists()
        sm.clean_data("600519.SH")  # 幂等: 再次调用不抛异常


# ── weekly / monthly synthesis ────────────────────────────────────────────


class TestSynthesize:
    _DATES = ["2024-01-01", "2024-01-03", "2024-01-08", "2024-01-10"]

    def test_weekly_empty_when_no_daily(self, sm):
        assert sm.synthesize_weekly("600519.SH").empty

    def test_monthly_empty_when_no_daily(self, sm):
        assert sm.synthesize_monthly("600519.SH").empty

    def test_weekly_missing_date_column_returns_empty(self, sm):
        sm.write_parquet(
            str(sm.daily_dir / "600519.SH.parquet"),
            pd.DataFrame({"close": [1.0], "volume": [1.0]}),
        )
        assert sm.synthesize_weekly("600519.SH").empty

    def test_weekly_no_aggregatable_columns_returns_empty(self, sm):
        sm.write_parquet(
            str(sm.daily_dir / "600519.SH.parquet"),
            pd.DataFrame({"date": ["2024-01-01"]}),
        )
        assert sm.synthesize_weekly("600519.SH").empty

    def test_weekly_aggregation_rules(self, sm):
        sm.write_data("600519.SH", _daily_frame(self._DATES), data_type="daily")
        weekly = sm.synthesize_weekly("600519.SH")
        assert list(weekly.columns[:2]) == ["year", "week"]
        w1 = weekly.iloc[0]
        assert (w1["open"], w1["high"], w1["low"], w1["close"]) == (10.0, 15.0, 8.0, 13.0)
        assert (w1["volume"], w1["amount"]) == (300.0, 3000.0)
        w2 = weekly.iloc[1]
        assert (w2["open"], w2["high"], w2["low"], w2["close"]) == (20.0, 25.0, 18.0, 23.0)
        # 周线已落盘
        assert (sm.weekly_dir / "600519.SH.parquet").exists()

    def test_monthly_missing_date_column_returns_empty(self, sm):
        sm.write_parquet(
            str(sm.daily_dir / "600519.SH.parquet"),
            pd.DataFrame({"close": [1.0]}),
        )
        assert sm.synthesize_monthly("600519.SH").empty

    def test_monthly_no_aggregatable_columns_returns_empty(self, sm):
        sm.write_parquet(
            str(sm.daily_dir / "600519.SH.parquet"),
            pd.DataFrame({"date": ["2024-01-01"]}),
        )
        assert sm.synthesize_monthly("600519.SH").empty

    def test_monthly_aggregation_rules(self, sm):
        sm.write_data("600519.SH", _daily_frame(self._DATES), data_type="daily")
        monthly = sm.synthesize_monthly("600519.SH")
        assert len(monthly) == 1
        m = monthly.iloc[0]
        assert (m["year"], m["month"]) == (2024, 1)
        assert (m["open"], m["high"], m["low"], m["close"]) == (10.0, 25.0, 8.0, 23.0)
        assert (m["volume"], m["amount"]) == (1000.0, 10000.0)
        assert (sm.monthly_dir / "600519.SH.parquet").exists()


# ── TDX freshness anchors ─────────────────────────────────────────────────


class TestReadParquetMaxDate:
    def test_pyarrow_statistics_path(self, sm, tmp_path):
        f = tmp_path / "d.parquet"
        pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-01-10"]), "close": [1.0, 2.0]}).to_parquet(f)
        assert sm._read_parquet_max_date(f) == "2024-01-10"

    def test_missing_file_raises(self, sm, tmp_path):
        with pytest.raises(Exception):
            sm._read_parquet_max_date(tmp_path / "nope.parquet")


class TestFindTdxMaxDate:
    def test_explicit_missing_dir_returns_none_none(self, sm, tmp_path):
        assert sm._find_tdx_max_date(str(tmp_path / "nope")) == (None, None)

    def test_sh_lday_layout(self, sm, tmp_path):
        root = tmp_path / "vipdoc"
        _write_day_file(root / "sh" / "lday" / "sh600519.day", 20261015)
        _write_day_file(root / "sz" / "lday" / "sz000001.day", 20261014)
        d, resolved = sm._find_tdx_max_date(str(root))
        assert d == "2026-10-15"
        assert resolved == root

    def test_flat_layout(self, sm, tmp_path):
        root = tmp_path / "flat"
        _write_day_file(root / "sh600519.day", 20261010)
        d, resolved = sm._find_tdx_max_date(str(root))
        assert d == "2026-10-10"
        assert resolved == root

    def test_empty_dir_returns_none_with_resolved(self, sm, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        assert sm._find_tdx_max_date(str(root)) == (None, root)

    def test_env_var_discovery(self, sm, tmp_path, monkeypatch):
        root = tmp_path / "envvip"
        _write_day_file(root / "sh" / "lday" / "sh600519.day", 20261012)
        monkeypatch.setenv("TDX_VIPDOC_DIR", str(root))
        d, _ = sm._find_tdx_max_date()
        assert d == "2026-10-12"

    def test_malformed_day_file_ignored(self, sm, tmp_path):
        root = tmp_path / "bad"
        _write_day_file(root / "sh600519.day", 20261001)
        (root / "truncated.day").write_bytes(b"\x01\x02\x03")  # <32 字节
        d, _ = sm._find_tdx_max_date(str(root))
        assert d == "2026-10-01"


class TestValidateFreshness:
    def test_lake_empty_not_fresh(self, sm):
        res = sm.validate_freshness(as_of_date="2026-10-16", check_tdx=False)
        assert res["is_fresh"] is False
        assert res["lake_max_date"] == ""
        assert "L2_LAKE_EMPTY" in res["details"]["stale_reasons"]
        assert res["details"]["lake_empty"] is True

    def test_lake_fresh_within_threshold(self, sm):
        sm.write_data(
            "600519.SH",
            pd.DataFrame({"date": pd.to_datetime(["2026-10-15"]), "close": [1.0]}),
            data_type="daily",
        )
        res = sm.validate_freshness(as_of_date="2026-10-16", check_tdx=False)
        assert res["lake_max_date"] == "2026-10-15"
        assert res["l2_lag_days"] == 1
        assert res["is_fresh"] is True

    def test_lake_stale_exceeds_threshold(self, sm):
        sm.write_data(
            "600519.SH",
            pd.DataFrame({"date": pd.to_datetime(["2026-09-01"]), "close": [1.0]}),
            data_type="daily",
        )
        res = sm.validate_freshness(as_of_date="2026-10-16", max_lag_days=7, check_tdx=False)
        assert res["is_fresh"] is False
        assert any(r.startswith("L2_LAG_EXCEEDED") for r in res["details"]["stale_reasons"])

    def test_l2_lag_measured_against_tdx_when_available(self, sm, tmp_path):
        root = tmp_path / "vipdoc"
        _write_day_file(root / "sh" / "lday" / "sh600519.day", 20261015)
        sm.write_data(
            "600519.SH",
            pd.DataFrame({"date": pd.to_datetime(["2026-10-10"]), "close": [1.0]}),
            data_type="daily",
        )
        res = sm.validate_freshness(as_of_date="2026-10-16", tdx_dir=str(root))
        assert res["tdx_max_date"] == "2026-10-15"
        assert res["l2_lag_days"] == 5          # TDX 2026-10-15 → 湖 2026-10-10
        assert res["details"]["l1_lag_days"] == 1
        assert res["details"]["l1_is_fresh"] is True
        assert res["is_fresh"] is True

    def test_require_l1_fresh_fails_on_stale_tdx(self, sm, tmp_path):
        root = tmp_path / "vipdoc"
        _write_day_file(root / "sh" / "lday" / "sh600519.day", 20260901)
        sm.write_data(
            "600519.SH",
            pd.DataFrame({"date": pd.to_datetime(["2026-09-01"]), "close": [1.0]}),
            data_type="daily",
        )
        res = sm.validate_freshness(
            as_of_date="2026-10-16", tdx_dir=str(root), require_l1_fresh=True
        )
        assert res["details"]["l2_lag_days"] == 0
        assert res["details"]["l1_is_fresh"] is False
        assert res["is_fresh"] is False
        assert any(r.startswith("L1_TDX_STALE") for r in res["details"]["stale_reasons"])

    def test_as_of_date_accepts_date_and_datetime(self, sm):
        for as_of in (date(2026, 10, 16), datetime(2026, 10, 16, 12, 0)):
            res = sm.validate_freshness(as_of_date=as_of, check_tdx=False)
            assert res["details"]["as_of_date"] == "2026-10-16"

    def test_full_scan_sample_size_zero(self, sm):
        for code in ("600519.SH", "000001.SZ"):
            sm.write_data(
                code,
                pd.DataFrame({"date": pd.to_datetime(["2026-10-15"]), "close": [1.0]}),
                data_type="daily",
            )
        res = sm.validate_freshness(as_of_date="2026-10-16", sample_size=0, check_tdx=False)
        assert res["details"]["scanned_files_count"] == 2

    def test_read_errors_collected_not_raised(self, sm, monkeypatch):
        sm.write_data(
            "600519.SH",
            pd.DataFrame({"date": pd.to_datetime(["2026-10-15"]), "close": [1.0]}),
            data_type="daily",
        )
        monkeypatch.setattr(
            sm, "_read_parquet_max_date", MagicMock(side_effect=RuntimeError("boom"))
        )
        res = sm.validate_freshness(as_of_date="2026-10-16", check_tdx=False)
        assert res["details"]["read_errors"]
        assert res["is_fresh"] is False


# ── compat surface ────────────────────────────────────────────────────────


class TestFilePathAndCompat:
    @pytest.mark.parametrize(
        "data_type,attr",
        [
            ("daily", "daily_dir"),
            ("stock", "daily_dir"),
            ("weekly", "weekly_dir"),
            ("monthly", "monthly_dir"),
            ("factor", "factor_dir"),
            ("1mins", "min1_dir"),
            ("min1", "min1_dir"),
            ("5mins", "min5_dir"),
            ("min5", "min5_dir"),
        ],
    )
    def test_known_types_map_to_dirs(self, sm, data_type, attr):
        assert sm._get_file_path("600519.SH", data_type) == getattr(sm, attr) / "600519.SH.parquet"

    def test_index_type(self, sm):
        assert sm._get_file_path("000001.SH", "index") == sm.index_dir / "000001.SH.parquet"

    def test_unknown_type_under_base_dir(self, sm):
        assert sm._get_file_path("x", "custom") == sm.base_dir / "custom" / "x.parquet"

    def test_read_data_missing_returns_empty(self, sm):
        assert sm.read_data("600519.SH").empty

    def test_read_data_index_fallback(self, sm):
        sm.write_parquet(
            str(sm.index_dir / "000001.SH.parquet"), pd.DataFrame({"close": [1.0]})
        )
        assert not sm.read_data("000001.SH", "daily").empty

    def test_write_data_roundtrip_and_empty_reject(self, sm):
        df = _daily_frame(["2024-01-01"])
        assert sm.write_data("600519.SH", df, "daily") is True
        assert not sm.read_data("600519.SH", "daily").empty
        assert sm.write_data("600519.SH", pd.DataFrame(), "daily") is False

    def test_delete_data(self, sm):
        sm.write_data("600519.SH", _daily_frame(["2024-01-01"]), "daily")
        assert sm.delete_data("600519.SH", "daily") is True
        assert not (sm.daily_dir / "600519.SH.parquet").exists()

    def test_batch_read_data_skips_missing(self, sm):
        sm.write_data("600519.SH", _daily_frame(["2024-01-01"]), "daily")
        out = sm.batch_read_data(["600519.SH", "000002.SZ"])
        assert set(out) == {"600519.SH"}

    def test_batch_read_data_swallows_per_symbol_errors(self, sm, monkeypatch):
        sm.write_data("600519.SH", _daily_frame(["2024-01-01"]), "daily")
        monkeypatch.setattr(sm, "read_data", MagicMock(side_effect=RuntimeError("boom")))
        assert sm.batch_read_data(["600519.SH"]) == {}

    def test_load_portfolio(self, sm, data_dir):
        assert sm.load_portfolio() == {}
        pd.DataFrame([{"code": "600519.SH", "weight": 1.0}]).to_parquet(
            data_dir / "portfolio.parquet"
        )
        assert sm.load_portfolio() == [{"code": "600519.SH", "weight": 1.0}]

    def test_normalize_dataframe_columns_delegates(self, sm):
        out = sm.normalize_dataframe_columns(pd.DataFrame({"收盘": [1.0]}))
        assert "close" in out.columns

    def test_get_stock_metadata_maps_fields(self, sm, monkeypatch):
        info = SimpleNamespace(
            code="600519.SH", name="贵州茅台", market="SH", sector=None,
            ipo_date=None, delist_date=None, stock_type=None, stock_status=None,
        )
        mgr = MagicMock()
        mgr.get_stock_info.return_value = info
        monkeypatch.setattr(
            "uniquant.data.managers.stock_metadata_manager.StockMetadataManager",
            lambda _d: mgr,
        )
        out = sm.get_stock_metadata("600519.SH")
        assert out["name"] == "贵州茅台" and out["code"] == "600519.SH"

    def test_get_stock_metadata_unknown_returns_none(self, sm, monkeypatch):
        mgr = MagicMock()
        mgr.get_stock_info.return_value = None
        monkeypatch.setattr(
            "uniquant.data.managers.stock_metadata_manager.StockMetadataManager",
            lambda _d: mgr,
        )
        assert sm.get_stock_metadata("999999.SH") is None

    def test_module_reexports_are_stable(self):
        assert sm_mod.is_index_symbol is is_index_symbol
