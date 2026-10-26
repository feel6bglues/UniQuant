"""``data/utils/normalizer.py`` 行为测试.

覆盖列名映射 / 数据源单位换算 / 涨跌幅与振幅派生 / 多源标准化 / 多源比对
的核心语义与边界 (空输入、缺列、单行、异常 swallow)。
"""

import contextlib
import logging

import pandas as pd
import pytest

from uniquant.data.utils import normalizer as nz

_NORMALIZER_LOGGER = "uniquant.data.utils.normalizer"


@contextlib.contextmanager
def _capture_logs():
    """工厂 logger 默认 ``propagate=False``; 临时放开以便 ``caplog`` 捕获。"""
    lg = logging.getLogger(_NORMALIZER_LOGGER)
    old_propagate, old_level = lg.propagate, lg.level
    lg.propagate = True
    lg.setLevel(logging.DEBUG)
    try:
        yield lg
    finally:
        lg.propagate = old_propagate
        lg.setLevel(old_level)


def _frame(**cols):
    """按列构造 DataFrame (各列等长)。"""
    return pd.DataFrame(cols)


class TestNormalizeColumnNames:
    def test_none_passthrough(self):
        assert nz.normalize_column_names(None) is None

    def test_empty_frame_passthrough(self):
        df = pd.DataFrame()
        out = nz.normalize_column_names(df)
        assert out is df  # empty 输入原样返回 (不 copy)

    def test_alias_mapping_chinese_and_english(self):
        df = _frame(**{"日期": ["2024-01-02"], "开盘": [1.0], "收盘": [2.0],
                       "最高": [3.0], "最低": [0.5], "成交量": [100.0]})
        out = nz.normalize_column_names(df)
        for col in ("date", "open", "close", "high", "low", "volume"):
            assert col in out.columns

    def test_standard_name_wins_over_alias(self):
        """已存在标准列时不应把别名覆盖上去。"""
        df = _frame(**{"date": [1], "trade_date": [2]})
        out = nz.normalize_column_names(df)
        assert out["date"].iloc[0] == 1
        assert "trade_date" in out.columns  # 别名保留原样, 未抢占 standard 名

    def test_input_not_mutated(self):
        df = _frame(**{"收盘": [1.0]})
        nz.normalize_column_names(df)
        assert "收盘" in df.columns and "close" not in df.columns


class TestConvertUnits:
    def test_eastmoney_volume_lots_to_shares(self):
        """eastmoney 成交量单位为手 → ×100 转股。"""
        df = _frame(volume=[10.0], amount=[1000.0])
        out = nz._convert_units(df, "eastmoney")
        assert out["volume"].iloc[0] == 1000.0
        assert out["amount"].iloc[0] == 1000.0  # 元→元, 不缩放

    def test_stock_source_wan_units(self):
        """stock 源成交量/额单位为万 → ×10000。"""
        df = _frame(volume=[2.0], amount=[3.0])
        out = nz._convert_units(df, "stock")
        assert out["volume"].iloc[0] == 2.0 * 10000
        assert out["amount"].iloc[0] == 3.0 * 10000

    def test_unknown_source_is_identity(self):
        df = _frame(volume=[7.0], amount=[8.0])
        out = nz._convert_units(df, "no_such_source")
        assert out["volume"].iloc[0] == 7.0
        assert out["amount"].iloc[0] == 8.0

    def test_missing_columns_tolerated(self):
        df = _frame(close=[1.0])
        out = nz._convert_units(df, "eastmoney")
        assert list(out.columns) == ["close"]

    def test_non_numeric_coerced_then_scaled(self):
        df = _frame(volume=["bad", 5.0], amount=["bad", 5.0])
        out = nz._convert_units(df, "eastmoney")
        assert out["volume"].iloc[0] == 0.0  # 非数值 → 0
        assert out["volume"].iloc[1] == 500.0


class TestCorrectCalculations:
    def test_no_close_returns_unchanged(self):
        df = _frame(open=[1.0])
        out = nz._correct_calculations(df, "s")
        assert list(out.columns) == ["open"]
        assert "change_rate" not in out.columns

    def test_change_rate_from_preclose(self):
        df = _frame(close=[11.0], preclose=[10.0], high=[12.0], low=[9.0])
        out = nz._correct_calculations(df, "s")
        assert out["change_rate"].iloc[0] == pytest.approx(10.0)
        assert out["amplitude"].iloc[0] == pytest.approx(30.0)

    def test_change_rate_falls_back_to_previous_close(self):
        """无 preclose 且多行 → 用 iloc[-2] 收盘作为**单一标量**参考应用于全帧。"""
        df = _frame(date=["2024-01-01", "2024-01-02"], close=[10.0, 11.0],
                    high=[10.0, 12.0], low=[9.0, 9.0], open=[10.0, 10.0])
        out = nz._correct_calculations(df, "s")
        # prev_close = iloc[-2].close = 10.0 (标量) → 两行共用同一分母
        assert out["change_rate"].iloc[0] == pytest.approx(0.0)   # (10-10)/10
        assert out["change_rate"].iloc[1] == pytest.approx(10.0)  # (11-10)/10
        assert out["amplitude"].iloc[0] == pytest.approx(10.0)    # (10-9)/10
        assert out["amplitude"].iloc[1] == pytest.approx(30.0)    # (12-9)/10

    def test_change_rate_single_row_uses_open(self):
        df = _frame(close=[11.0], high=[12.0], low=[9.0], open=[10.0])
        out = nz._correct_calculations(df, "s")
        assert out["change_rate"].iloc[0] == pytest.approx(10.0)
        assert out["amplitude"].iloc[0] == pytest.approx(30.0)

    def test_change_rate_zero_when_no_reference(self):
        """无 preclose / 无 open / 单行 → change_rate 与 amplitude 归零。"""
        df = _frame(close=[10.0], high=[12.0], low=[9.0])
        out = nz._correct_calculations(df, "s")
        assert out["change_rate"].iloc[0] == 0
        assert out["amplitude"].iloc[0] == 0

    def test_preclose_zero_sum_uses_previous_close_path(self):
        """preclose 列存在但全为 0 → 走 prev_close 分支。"""
        df = _frame(date=["2024-01-01", "2024-01-02"], close=[10.0, 11.0],
                    high=[10.5, 11.5], low=[9.5, 10.5], preclose=[0.0, 0.0])
        out = nz._correct_calculations(df, "s")
        assert out["change_rate"].iloc[1] == pytest.approx(10.0)


class TestGetPreviousClose:
    def test_single_row_returns_zero(self):
        assert nz._get_previous_close(_frame(close=[10.0])) == 0

    def test_empty_returns_zero(self):
        assert nz._get_previous_close(_frame(close=[])) == 0

    def test_sorts_by_date_before_taking_penultimate(self):
        df = _frame(date=["2024-01-03", "2024-01-01", "2024-01-02"],
                    close=[30.0, 10.0, 20.0])
        # 排序后倒数第二为 2024-01-02 → 20.0
        assert nz._get_previous_close(df) == pytest.approx(20.0)


class TestValidateData:
    def test_missing_required_columns_warns_without_raising(self, caplog):
        with _capture_logs(), caplog.at_level("WARNING"):
            nz._validate_data(_frame(close=[1.0]), "src")  # 不抛异常
        missing = {
            r.getMessage().split(": ")[-1] for r in caplog.records
        }
        assert {"date", "code", "open", "high", "low", "volume", "amount"} <= missing
        assert "close" not in missing

    def test_flags_absurd_volume_amount_and_price(self, caplog):
        df = _frame(volume=[2e12], amount=[2e15], close=[20000.0])
        with _capture_logs(), caplog.at_level("WARNING"):
            nz._validate_data(df, "src")  # 三条告警分支均执行, 不抛异常
        msgs = [r.getMessage() for r in caplog.records]
        assert any("成交量异常大" in m for m in msgs)
        assert any("成交额异常大" in m for m in msgs)
        assert any("价格异常" in m for m in msgs)

    def test_negative_and_tiny_price_flagged(self, caplog):
        df = _frame(close=[0.001], volume=[1.0], amount=[1.0])
        with _capture_logs(), caplog.at_level("WARNING"):
            nz._validate_data(df, "src")
        assert any("价格异常" in r.getMessage() for r in caplog.records)


class TestNormalizeStockData:
    def test_none_and_empty_passthrough(self):
        assert nz.normalize_stock_data(None, "eastmoney") is None
        empty = pd.DataFrame()
        assert nz.normalize_stock_data(empty, "eastmoney") is empty

    def test_end_to_end_column_and_unit_normalization(self):
        df = _frame(**{"日期": ["2024-01-02"], "开盘": [10.0], "收盘": [11.0],
                       "最高": [12.0], "最低": [9.0], "成交量": [5.0], "成交额": [100.0]})
        out = nz.normalize_stock_data(df, "eastmoney")
        assert out["volume"].iloc[0] == 500.0     # 手 → 股
        assert out["change_rate"].iloc[0] == pytest.approx(10.0)

    def test_exception_is_swallowed_and_original_copy_returned(self, monkeypatch):
        """标准化内部异常不得冒泡; 返回未标准化的副本。"""
        def _boom(_df):
            raise RuntimeError("boom")

        monkeypatch.setattr(nz, "normalize_column_names", _boom)
        df = _frame(**{"收盘": [1.0]})
        out = nz.normalize_stock_data(df, "eastmoney")
        assert out is not df          # 返回的是 copy
        assert "收盘" in out.columns  # 未做重命名 (try 中途失败)

    def test_does_not_mutate_input(self):
        df = _frame(**{"收盘": [11.0], "昨收": [10.0]})
        nz.normalize_stock_data(df, "sina")
        assert "close" not in df.columns


class TestMultipleAndCompare:
    def test_normalize_multiple_sources(self):
        sources = {
            "eastmoney": _frame(**{"日期": ["2024-01-02"], "收盘": [11.0], "成交量": [1.0]}),
            "sina": _frame(**{"日期": ["2024-01-02"], "收盘": [11.0], "成交量": [1.0]}),
        }
        out = nz.normalize_multiple_sources(sources)
        assert set(out) == {"eastmoney", "sina"}
        assert out["eastmoney"]["volume"].iloc[0] == 100.0  # eastmoney ×100
        assert out["sina"]["volume"].iloc[0] == 1.0         # sina ×1

    def test_compare_empty(self):
        assert nz.compare_sources({}) == {}

    def test_compare_prefers_baostock_as_reference(self):
        sources = {
            "sina": _frame(date=["2024-01-01", "2024-01-02"], close=[10.0, 20.0]),
            "baostock": _frame(date=["2024-01-01", "2024-01-02"], close=[10.0, 22.0]),
        }
        out = nz.compare_sources(sources)
        assert set(out) == {"sina", "baostock"}
        # 参考 = baostock 末日 close 22.0; sina 末日 20.0 → diff = |20-22|/22
        assert out["sina"]["close"]["reference"] == pytest.approx(22.0)
        assert out["sina"]["close"]["current"] == pytest.approx(20.0)
        assert out["sina"]["close"]["diff"] == pytest.approx(2.0 / 22.0)

    def test_compare_skips_zero_reference_and_missing_columns(self):
        sources = {
            "a": _frame(close=[0.0], volume=[1.0]),
            "b": _frame(close=[0.0], volume=[1.0]),
        }
        out = nz.compare_sources(sources)
        # 参考值 0 → close 被跳过 (不会除零)
        assert "close" not in out.get("a", {})

    def test_compare_ignores_empty_frames(self):
        sources = {"a": pd.DataFrame(), "b": _frame(close=[1.0], date=["2024-01-01"])}
        out = nz.compare_sources(sources)
        assert "a" not in out


class TestNormalizeMootdxColumns:
    def test_none_and_empty_passthrough(self):
        assert nz.normalize_mootdx_columns(None) is None
        assert nz.normalize_mootdx_columns(pd.DataFrame()).empty

    def test_datetime_renamed_to_date(self):
        df = pd.DataFrame({"datetime": ["2024-01-02"], "vol": [100]})
        out = nz.normalize_mootdx_columns(df)
        assert "date" in out.columns
        assert "volume" in out.columns
        assert "datetime" not in out.columns
        assert "vol" not in out.columns

    def test_both_vol_and_volume_drops_alias_vol(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "vol": [100], "volume": [200]})
        out = nz.normalize_mootdx_columns(df)
        assert "volume" in out.columns
        assert "vol" not in out.columns
        assert out["volume"].iloc[0] == 200

