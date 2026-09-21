"""Tests for DataValidator and DataCleaner: verifies decoupled read-only gate and repair pipeline."""
import pandas as pd

from uniquant.data.pipeline.data_cleaner import DataCleaner
from uniquant.data.pipeline.data_validator import DataValidator


def _make_valid_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "code": ["000001.SZ"] * 3,
        "open": [10.0, 10.5, 10.3],
        "high": [11.0, 11.2, 10.8],
        "low": [9.5, 10.0, 9.8],
        "close": [10.5, 10.8, 10.2],
        "volume": [100000.0, 120000.0, 90000.0],
        "amount": [1050000.0, 1296000.0, 918000.0],
        "adjustflag": [2, 2, 2],
    })


class TestDataValidatorReadOnlyGate:
    """Verify DataValidator is a pure read-only assertion gate that never mutates and strictly blocks corrupted data."""

    def test_validate_does_not_mutate_input(self):
        df = _make_valid_df()
        original_high = df["high"].iloc[0]
        original_low = df["low"].iloc[0]

        validator = DataValidator()
        result = validator.validate(df)

        assert result is True
        assert df["high"].iloc[0] == original_high
        assert df["low"].iloc[0] == original_low

    def test_validate_strictly_rejects_corrupted_high_low(self):
        """R04 修复: 校验器严格返回 False 阻断落盘，严禁假修复真污染。"""
        df = _make_valid_df()
        df.loc[0, "high"] = 9.0
        df.loc[0, "low"] = 11.0
        orig_high = df["high"].iloc[0]
        orig_low = df["low"].iloc[0]

        validator = DataValidator()
        result = validator.validate(df)

        assert result is False
        # 确认未原地修改被校验帧
        assert df["high"].iloc[0] == orig_high
        assert df["low"].iloc[0] == orig_low

    def test_cleaner_repairs_and_validator_passes(self):
        """解耦契约: 脏数据经 DataCleaner 修复后，方可通过 DataValidator 门禁。"""
        df = _make_valid_df()
        df.loc[0, "high"] = 9.0
        df.loc[0, "low"] = 11.0

        cleaner = DataCleaner()
        validator = DataValidator()

        # 未清洗前门禁拦截
        assert validator.validate(df) is False

        # 清洗修复
        cleaned = cleaner.clean(df)

        # 清洗后四价自洽，门禁放行
        assert validator.validate(cleaned) is True
        assert cleaned.loc[0, "high"] >= cleaned.loc[0, "low"]
        assert cleaned.loc[0, "high"] >= max(cleaned.loc[0, "open"], cleaned.loc[0, "close"])

    def test_validate_returns_true_for_valid_data(self):
        df = _make_valid_df()
        validator = DataValidator()
        assert validator.validate(df) is True

    def test_validate_rejects_negative_volume(self):
        df = _make_valid_df()
        df.loc[0, "volume"] = -100.0
        validator = DataValidator()
        assert validator.validate(df) is False

    def test_validate_rejects_nan_in_core_numeric_columns(self):
        """FIX-2 验证: 严禁 IEEE 754 NaN 绕过价格门禁，核心行情列含 NaN 必须硬拦截。"""
        validator = DataValidator()
        for col in ["open", "high", "low", "close", "volume"]:
            df = _make_valid_df()
            df.loc[0, col] = float("nan")
            assert validator.validate(df) is False, f"Failed to reject NaN in column {col}"


class TestDataValidatorEdgeCases:
    def test_empty_dataframe(self):
        validator = DataValidator()
        assert validator.validate(pd.DataFrame()) is False

    def test_missing_required_columns(self):
        df = pd.DataFrame({"date": ["2024-01-01"], "close": [10.0]})
        validator = DataValidator()
        assert validator.validate(df) is False

    def test_validate_stock_daily_delegates(self):
        df = _make_valid_df()
        validator = DataValidator()
        assert validator.validate_stock_daily(df) is True
