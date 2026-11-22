"""``data/utils/normalizer.py`` 行为测试.

覆盖列名映射与 mootdx 列标准化的核心语义与边界。
"""

import pandas as pd

from uniquant.data.utils import normalizer as nz


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
