"""``data/parsers/tdx_parser.py`` — .day 二进制解析 / I/O / 入口函数测试.

补充 ``tests/test_tdx_parser_gbbq_mapping.py`` (该文件冻结 GBBQ 列契约), 本文件
覆盖: ``parse_day_file`` 的价格分档除数、``save_*`` 落盘契约、``parse_gbbq_native``
降级链、``get_adjust_factors`` 过滤与排序、``get_symbol_from_filename``。

纪律: 绝不写真实 ``data/fq/gbbq.parquet`` (save 测试只写 tmp_path)。
"""

import struct
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.parsers import tdx_parser as mod
from uniquant.data.parsers.tdx_parser import TDXParser

_DAY_FMT = "<IIIIIfii"  # 32 bytes, 与解析器冻结结构一致


def _write_day(path: Path, records) -> Path:
    """写出合成 .day 文件 (每条 32 字节)。"""
    buf = b"".join(struct.pack(_DAY_FMT, *r) for r in records)
    path.write_bytes(buf)
    return path


def _rec(date=20240102, o=1000, h=1100, lo=900, c=1050, amount=1_000_000.0, vol=1000, res=0):
    return (date, o, h, lo, c, amount, vol, res)


class TestParseDayFile:
    def test_standard_stock_price_divisor_100(self, tmp_path):
        p = _write_day(tmp_path / "sh600000.day", [_rec()])
        df = TDXParser().parse_day_file(str(p))
        assert len(df) == 1
        assert df["open"].iloc[0] == pytest.approx(10.0)
        assert df["close"].iloc[0] == pytest.approx(10.5)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index[0] == pd.Timestamp("2024-01-02")

    def test_fund_prefix_5_divisor_1000(self, tmp_path):
        p = _write_day(tmp_path / "sh510300.day", [_rec()])
        df = TDXParser().parse_day_file(str(p))
        assert df["open"].iloc[0] == pytest.approx(1.0)

    def test_bond_prefix_11_divisor_10000(self, tmp_path):
        p = _write_day(tmp_path / "sh110000.day", [_rec()])
        df = TDXParser().parse_day_file(str(p))
        assert df["open"].iloc[0] == pytest.approx(0.1)

    def test_b_share_prefix_9_divisor_1000(self, tmp_path):
        p = _write_day(tmp_path / "sh900001.day", [_rec()])
        df = TDXParser().parse_day_file(str(p))
        assert df["open"].iloc[0] == pytest.approx(1.0)

    def test_filename_without_exchange_prefix(self, tmp_path):
        p = _write_day(tmp_path / "600519.day", [_rec()])
        df = TDXParser().parse_day_file(str(p))
        assert df["close"].iloc[0] == pytest.approx(10.5)

    def test_non_multiple_of_32_warns_but_parses_whole_records(self, tmp_path):
        p = tmp_path / "sh600000.day"
        p.write_bytes(struct.pack(_DAY_FMT, *_rec()) + b"\x01\x02\x03")  # 35 bytes
        df = TDXParser().parse_day_file(str(p))
        assert len(df) == 1  # iter_unpack 丢弃尾部残缺记录

    def test_unparseable_date_dropped(self, tmp_path):
        p = _write_day(tmp_path / "sh600000.day", [_rec(date=99999999)])
        df = TDXParser().parse_day_file(str(p))
        assert df.empty  # NaT → dropna


class TestGetSymbolFromFilename:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("sh600000.day", "600000.SH"),
            ("sz000001.day", "000001.SZ"),
        ],
    )
    def test_recognized(self, name, expected):
        assert TDXParser().get_symbol_from_filename(name) == expected

    def test_unrecognized_returns_none(self):
        assert TDXParser().get_symbol_from_filename("600000.day") is None

    def test_exception_path_returns_none(self):
        assert TDXParser().get_symbol_from_filename(None) is None  # type: ignore[arg-type]


class TestSaveGbbq:
    def _frame(self):
        return pd.DataFrame(
            {
                "code": ["600000"],
                "market": [1],
                "date": [20240102],
                "category": [1],
                "cash_div": [0.5],
                "split_ratio": [0.0],
                "rights_ratio": [0.0],
                "rights_price": [0.0],
            }
        )

    def test_save_empty_skips_and_writes_nothing(self, tmp_path):
        out = tmp_path / "gbbq.parquet"
        TDXParser().save_gbbq_data(pd.DataFrame(), str(out))
        assert not out.exists()

    def test_save_data_writes_parquet(self, tmp_path):
        out = tmp_path / "gbbq.parquet"
        TDXParser().save_gbbq_data(self._frame(), str(out))
        assert out.exists()
        assert len(pd.read_parquet(out)) == 1

    def test_save_stock_empty_skips(self, tmp_path):
        TDXParser().save_stock_gbbq_data(pd.DataFrame(), "600000", str(tmp_path))
        assert list(tmp_path.iterdir()) == []

    def test_save_stock_writes_code_named_file(self, tmp_path):
        TDXParser().save_stock_gbbq_data(self._frame(), "600000", str(tmp_path))
        assert (tmp_path / "600000.parquet").exists()

    def test_save_error_is_swallowed(self, tmp_path):
        """落盘失败不得冒泡 (日志记录即可)。"""
        bad_dir = tmp_path / "nope"
        bad_dir.mkdir()
        bad_dir.chmod(0o500)
        target = bad_dir / "sub" / "x.parquet"
        try:
            TDXParser().save_gbbq_data(self._frame(), str(target))
            assert not target.exists()
        finally:
            bad_dir.chmod(0o700)


class TestSaveGbbqToFq:
    def test_empty_parse_returns_false_and_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "parse_gbbq_native", lambda _p: pd.DataFrame())
        out = tmp_path / "gbbq.parquet"
        assert TDXParser().save_gbbq_to_fq("ignored", str(out)) is False
        assert not out.exists()

    def test_writes_normalized_contract_columns(self, tmp_path, monkeypatch):
        raw = pd.DataFrame(
            {
                "datetime": [20240102],
                "code": [600000],
                "market": [1],
                "category": [1],
                "hongli_panqianliutong": [0.5],
                "songgu_qianzongguben": [0.0],
                "peigu_houzongguben": [0.0],
                "peigujia_qianzongguben": [0.0],
            }
        )
        monkeypatch.setattr(mod, "parse_gbbq_native", lambda _p: raw)
        out = tmp_path / "nested" / "gbbq.parquet"
        assert TDXParser().save_gbbq_to_fq("ignored", str(out)) is True
        written = pd.read_parquet(out)
        assert list(written.columns) == [
            "code", "market", "date", "category",
            "cash_div", "split_ratio", "rights_ratio", "rights_price",
        ]
        assert written["date"].iloc[0] == 20240102

    def test_parse_exception_returns_false(self, tmp_path, monkeypatch):
        def _boom(_p):
            raise RuntimeError("parse exploded")

        monkeypatch.setattr(mod, "parse_gbbq_native", _boom)
        assert TDXParser().save_gbbq_to_fq("ignored", str(tmp_path / "g.parquet")) is False


class TestParseGbbqNative:
    def test_pytdx_path_used_when_non_empty(self, monkeypatch):
        parser_cls = MagicMock()
        fake = pd.DataFrame({"code": ["600000"], "date": [20240102]})
        parser_cls.return_value.parse_gbbq_file.return_value = fake
        monkeypatch.setattr(mod, "TDXParser", parser_cls)
        out = mod.parse_gbbq_native("gbbq")
        assert out is fake
        parser_cls.return_value._parse_gbbq_manually.assert_not_called()

    def test_falls_back_to_manual_when_pytdx_empty(self, monkeypatch):
        parser_cls = MagicMock()
        parser_cls.return_value.parse_gbbq_file.return_value = pd.DataFrame()
        parser_cls.return_value._parse_gbbq_manually.return_value = pd.DataFrame({"x": [1]})
        monkeypatch.setattr(mod, "TDXParser", parser_cls)
        out = mod.parse_gbbq_native("gbbq")
        parser_cls.return_value._parse_gbbq_manually.assert_called_once_with("gbbq")
        assert list(out.columns) == ["x"]


class TestGetAdjustFactors:
    def test_missing_symbol_returns_none(self, monkeypatch):
        gbbq = pd.DataFrame({"code": ["600000"], "date": [20240102]})
        monkeypatch.setattr(mod, "parse_gbbq_native", lambda _p: gbbq)
        assert mod.get_adjust_factors("000001.SZ", "gbbq") is None

    def test_empty_parse_returns_none(self, monkeypatch):
        monkeypatch.setattr(mod, "parse_gbbq_native", lambda _p: pd.DataFrame())
        assert mod.get_adjust_factors("600000.SH", "gbbq") is None

    def test_filters_by_code_and_sorts_by_date(self, monkeypatch):
        gbbq = pd.DataFrame(
            {
                "code": ["600000", "600000", "000001"],
                "date": [20240103, 20240101, 20240102],
            }
        )
        monkeypatch.setattr(mod, "parse_gbbq_native", lambda _p: gbbq)
        out = mod.get_adjust_factors("600000.SH", "gbbq")
        assert list(out["date"]) == [20240101, 20240103]


class TestParseGbbqFileBranches:
    def test_missing_file_returns_empty(self, tmp_path):
        assert TDXParser().parse_gbbq_file(str(tmp_path / "nope.gbbq")).empty

    def test_pytdx_none_result_returns_empty(self, tmp_path, monkeypatch):
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(b"\x00" * 8)
        import pytdx.reader

        monkeypatch.setattr(pytdx.reader, "GbbqReader", lambda: MagicMock(
            get_df=MagicMock(return_value=None)))
        assert TDXParser().parse_gbbq_file(str(gbbq)).empty

    def test_pytdx_exception_returns_empty(self, tmp_path, monkeypatch):
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(b"\x00" * 8)
        import pytdx.reader

        monkeypatch.setattr(pytdx.reader, "GbbqReader", lambda: MagicMock(
            get_df=MagicMock(side_effect=RuntimeError("decode fail"))))
        assert TDXParser().parse_gbbq_file(str(gbbq)).empty

    def test_non_six_digit_codes_filtered_out(self, tmp_path, monkeypatch):
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(b"\x00" * 8)
        import pytdx.reader

        raw = pd.DataFrame(
            {
                "datetime": [20240102, 20240103],
                "code": ["600000", "ABCDEF"],
                "market": [1, 1],
                "category": [1, 1],
                "hongli_panqianliutong": [0.0, 0.0],
                "peigujia_qianzongguben": [0.0, 0.0],
                "songgu_qianzongguben": [0.0, 0.0],
                "peigu_houzongguben": [0.0, 0.0],
            }
        )
        monkeypatch.setattr(pytdx.reader, "GbbqReader", lambda: MagicMock(
            get_df=MagicMock(return_value=raw)))
        out = TDXParser().parse_gbbq_file(str(gbbq))
        assert list(out["code"]) == ["600000"]


class TestParseGbbqManuallyShortCircuit:
    def test_short_file_returns_empty(self, tmp_path):
        p = tmp_path / "gbbq"
        p.write_bytes(b"\x00\x01")
        assert TDXParser()._parse_gbbq_manually(str(p)).empty

    def test_zero_record_file_returns_contract_shaped_empty(self, tmp_path):
        p = tmp_path / "gbbq"
        p.write_bytes(struct.pack("<I", 0))
        out = TDXParser()._parse_gbbq_manually(str(p))
        assert out.empty
        assert list(out.columns) == [
            "code", "market", "date", "category",
            "cash_div", "split_ratio", "rights_ratio", "rights_price",
        ]
