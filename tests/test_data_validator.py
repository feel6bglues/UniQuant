"""Tests for DataValidator: verifies no mutation of caller's DataFrame."""
import pandas as pd

from uniquant.data.pipeline.data_validator import DataValidator


def _make_valid_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "code": ["000001.SZ"] * 3,
        "open": [10.0, 10.5, 10.3],
        "high": [11.0, 11.2, 10.8],
        "low": [9.5, 10.0, 9.8],
        "close": [10.5, 10.8, 10.2],
        "volume": [100000, 120000, 90000],
        "amount": [1050000, 1296000, 918000],
        "adjustflag": [2, 2, 2],
    })


class TestDataValidatorMutation:
    """Verify DataValidator does NOT mutate the caller's DataFrame."""

    def test_validate_does_not_mutate_input(self):
        df = _make_valid_df()
        original_high = df["high"].iloc[0]
        original_low = df["low"].iloc[0]

        validator = DataValidator()
        result = validator.validate(df)

        assert result is True
        assert df["high"].iloc[0] == original_high
        assert df["low"].iloc[0] == original_low

    def test_validate_repair_without_mutating_input(self):
        df = _make_valid_df()
        df.loc[0, "high"] = 9.0
        df.loc[0, "low"] = 11.0
        swapped_high_orig = df["high"].iloc[0]
        swapped_low_orig = df["low"].iloc[0]

        validator = DataValidator()
        result = validator.validate(df)

        assert result is True
        assert df["high"].iloc[0] == swapped_high_orig
        assert df["low"].iloc[0] == swapped_low_orig

    def test_validate_returns_true_for_valid_data(self):
        df = _make_valid_df()
        validator = DataValidator()
        assert validator.validate(df) is True

    def test_validate_can_repair_swapped_high_low(self):
        df = _make_valid_df()
        df.loc[:, "high"] = 0.0
        df.loc[:, "low"] = 100.0
        validator = DataValidator()
        assert validator.validate(df) is True


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
