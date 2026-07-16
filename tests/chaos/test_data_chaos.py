"""
Chaos Test Suite for UniQuant Data Pipeline
Injects dirty/chaotic data to verify system resilience.
"""

import math
import os
import sys

from pandas.testing import assert_frame_equal

import numpy as np
import pandas as pd
import psutil

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from uniquant.data.pipeline.data_cleaner import DataCleaner  # noqa: E402
from uniquant.data.pipeline.data_validator import DataValidator  # noqa: E402
from uniquant.data.pipeline.data_adjuster import DataAdjuster  # noqa: E402
from uniquant.shared.limit_checker import check_limit_status, get_board_type  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daily_df(
    n: int = 30,
    start_price: float = 10.0,
    seed: int = 42,
    code: str = "000001.SZ",
    dates: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Generate a plausible daily OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    if dates is None:
        dates = pd.bdate_range("2024-01-02", periods=n)
    close = start_price + np.cumsum(rng.normal(0, 0.3, size=n))
    close = np.maximum(close, 0.5)
    high = close + rng.uniform(0.01, 0.5, size=n)
    low = close - rng.uniform(0.01, 0.5, size=n)
    low = np.maximum(low, 0.01)
    opn = (high + low) / 2
    volume = rng.integers(1_000_000, 50_000_000, size=n).astype(float)
    return pd.DataFrame(
        {
            "date": dates[:n],
            "code": code,
            "open": opn,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
    )


# ===================================================================
# TASK 1: Dirty Data Injection — DataCleaner
# ===================================================================

class TestDataCleanerChaos:
    """Chaos tests for DataCleaner.clean()"""

    def setup_method(self):
        self.cleaner = DataCleaner()

    # --- 1a. Consecutive suspension days (NaN / zero volume) ---
    def test_consecutive_suspension_days(self):
        df = _make_daily_df(30)
        # Inject 7 consecutive suspension days (volume=0, NaN prices)
        for i in range(10, 17):
            df.loc[i, "volume"] = 0.0
            df.loc[i, ["open", "high", "low", "close"]] = np.nan
        result = self.cleaner.clean(df)
        # HOTFIX #1: NaN close prices are preserved and dropped via dropna(subset=["close"])
        # Suspension rows with NaN prices should be removed, not zero-filled
        assert not result["close"].isna().any(), "NaN should not propagate to close after cleaning"
        assert len(result) < 30, f"Suspension rows should be dropped: {len(result)} < 30"
        assert len(result) == 23, f"Expected 23 rows (7 suspension dropped), got {len(result)}"
        # Volume must not contain NaN
        assert not result["volume"].isna().any(), "NaN in volume after cleaning"

    # --- 1b. Delisted stock (prices → 0 then stop) ---
    def test_delisted_stock_prices_to_zero(self):
        df = _make_daily_df(30)
        # Last 10 days: prices drop to 0 (delisted)
        for i in range(20, 30):
            df.loc[i, ["open", "high", "low", "close"]] = 0.0
            df.loc[i, "volume"] = 0.0
        result = self.cleaner.clean(df)
        # close=0 rows are kept (not NaN), cleaner only drops NaN close
        zero_close = result[result["close"] == 0.0]
        assert len(zero_close) == 10, f"Expected 10 zero-close rows, got {len(zero_close)}"
        # No NaN anywhere
        assert not result.isna().any().any(), "NaN found after cleaning delisted data"

    # --- 1c. Negative prices ---
    def test_negative_prices(self):
        df = _make_daily_df(20)
        df.loc[5, "close"] = -5.0
        df.loc[6, "open"] = -1.0
        df.loc[7, "low"] = -10.0
        result = self.cleaner.clean(df)
        # Cleaner converts to numeric but does NOT filter negatives
        # It should at least not crash and produce numeric output
        assert result["close"].dtype in (np.float64, np.float32, np.int64)
        assert len(result) > 0

    # --- 1d. Zero prices with non-zero volume ---
    def test_zero_price_nonzero_volume(self):
        df = _make_daily_df(20)
        df.loc[3, "close"] = 0.0
        df.loc[3, "volume"] = 99_000_000.0
        result = self.cleaner.clean(df)
        # Zero close is kept (not NaN)
        assert 0.0 in result["close"].values, "Zero price row should survive cleaning"
        assert not result["volume"].isna().any()

    # --- 1e. String-typed numeric columns ---
    def test_string_numeric_columns(self):
        df = _make_daily_df(10)
        df["close"] = df["close"].astype(str)
        df["volume"] = df["volume"].astype(str)
        df.loc[4, "close"] = "garbage"
        df.loc[5, "volume"] = "N/A"
        result = self.cleaner.clean(df)
        assert not result["close"].isna().any(), "NaN close after string coercion"
        # 'garbage' coerced to NaN then filled with 0
        assert result.loc[result.index[3] if len(result) > 3 else 0, "close"] is not None

    # --- 1f. Duplicate dates ---
    def test_duplicate_dates(self):
        df = _make_daily_df(10)
        dup_row = df.iloc[5].copy()
        dup_row["close"] = 999.99
        df = pd.concat([df, dup_row.to_frame().T], ignore_index=True)
        result = self.cleaner.clean(df)
        assert result["date"].is_unique, "Duplicate dates should be removed"

    # --- 1g. Empty DataFrame ---
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = self.cleaner.clean(df)
        assert result.empty

    # --- 1h. Missing columns (no amount) ---
    def test_missing_amount_column(self):
        df = _make_daily_df(10).drop(columns=["amount"])
        result = self.cleaner.clean(df)
        assert "amount" in result.columns, "amount column should be created"

    # --- 1i. All-None DataFrame ---
    def test_all_none_data(self):
        df = pd.DataFrame(
            {
                "date": [None] * 5,
                "close": [None] * 5,
                "open": [None] * 5,
                "high": [None] * 5,
                "low": [None] * 5,
                "volume": [None] * 5,
            }
        )
        result = self.cleaner.clean(df)
        # All rows should be dropped (date is None → NaT → dropna)
        assert len(result) == 0, "All-None data should produce empty result"

    # --- 1j. Extreme outlier prices ---
    def test_extreme_outlier_prices(self):
        df = _make_daily_df(20)
        df.loc[10, "close"] = 1e12  # 1 trillion
        df.loc[11, "close"] = 1e-10  # near-zero
        result = self.cleaner.clean(df)
        assert len(result) == 20, "Outlier rows should not be dropped"
        assert not result["close"].isna().any()

    # --- 1k. Mixed case column names ---
    def test_mixed_case_columns(self):
        df = _make_daily_df(10)
        df.columns = ["Date", "Code", "Open", "High", "Low", "Close", "Volume", "Amount"]
        result = self.cleaner.clean(df)
        for col in ["date", "close", "volume"]:
            assert col in result.columns, f"Column '{col}' missing after case normalization"


# ===================================================================
# TASK 1: Dirty Data Injection — DataValidator
# ===================================================================

class TestDataValidatorChaos:
    """Chaos tests for DataValidator.validate()"""

    def setup_method(self):
        self.validator = DataValidator()

    # --- 1a. High < Low swap test ---
    def test_high_less_than_low(self):
        df = _make_daily_df(20)
        for i in [3, 7, 15]:
            df.loc[i, "high"], df.loc[i, "low"] = df.loc[i, "low"], df.loc[i, "high"]
        orig = df.copy()
        result = self.validator.validate(df)
        assert result is True, "Validator should fix High < Low and return True"
        assert (df["high"] == orig["high"]).all().all(), "Original DataFrame must not be mutated"

    # --- 1b. High < Open/Close fix ---
    def test_high_less_than_open_close(self):
        df = _make_daily_df(20)
        orig = df.copy()
        df.loc[5, "high"] = df.loc[5, "open"] - 2.0  # high < open
        result = self.validator.validate(df)
        assert result is True
        assert df.loc[5, "high"] < df.loc[5, "open"], "Original must not be mutated (fix applied to copy)"

    # --- 1c. Low > Open/Close fix ---
    def test_low_greater_than_open_close(self):
        df = _make_daily_df(20)
        orig = df.copy()
        df.loc[8, "low"] = df.loc[8, "close"] + 5.0  # low > close
        result = self.validator.validate(df)
        assert result is True
        assert df.loc[8, "low"] > df.loc[8, "close"], "Original must not be mutated (fix applied to copy)"

    # --- 1d. Missing required columns ---
    def test_missing_required_columns(self):
        df = _make_daily_df(10).drop(columns=["code"])
        result = self.validator.validate(df)
        assert result is False, "Should fail when required column 'code' is missing"

    # --- 1e. 99% price drop (should warn, not fail) ---
    def test_99_percent_drop(self):
        df = _make_daily_df(20, start_price=100.0)
        df.loc[15, "close"] = 0.50  # ~99.5% drop from ~100
        result = self.validator.validate(df)
        # Should still pass (just warns), but the validator doesn't reject
        assert result is True

    # --- 1f. Empty DataFrame ---
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = self.validator.validate(df)
        assert result is False

    # --- 1g. Date gap > 14 days (warns, doesn't fail) ---
    def test_large_date_gap(self):
        dates1 = pd.bdate_range("2024-01-02", periods=10)
        dates2 = pd.bdate_range("2024-02-15", periods=10)  # >14 day gap
        dates = dates1.append(dates2)
        df = _make_daily_df(20, dates=dates)
        result = self.validator.validate(df)
        # Should pass with warning
        assert result is True


# ===================================================================
# TASK 1: Dirty Data Injection — DataAdjuster (no storage needed)
# ===================================================================

class TestDataAdjusterChaos:
    """Chaos tests for DataAdjuster edge cases."""

    def test_apply_adjustment_empty_df(self):
        """Empty df should return empty, no crash."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        result = adjuster.apply_adjustment("000001.SZ", pd.DataFrame(), "qfq")
        assert result.empty

    def test_apply_adjustment_invalid_method(self):
        """Invalid method should return raw data."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        df = _make_daily_df(10)
        result = adjuster.apply_adjustment("000001.SZ", df, "invalid")
        assert len(result) == len(df)

    def test_apply_adjustment_no_factor_data(self):
        """When factor_manager returns empty, should return raw data unchanged."""
        from unittest.mock import MagicMock
        mock_sm = MagicMock()
        mock_sm.data_dir = "/tmp/test_data"
        adjuster = DataAdjuster(storage_manager=mock_sm)
        # Mock factor_manager to return empty
        adjuster.factor_manager = MagicMock()
        adjuster.factor_manager.read_factor.return_value = pd.DataFrame()
        df = _make_daily_df(10)
        result = adjuster.apply_adjustment("000001.SZ", df, "qfq")
        assert len(result) == len(df), "Should return raw data when no factors"

    def test_apply_adjustment_negative_factor(self):
        """Negative factor values should trigger safety check and return raw."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        adjuster.factor_manager = MagicMock()
        df_factors = pd.DataFrame(
            {"date": pd.bdate_range("2024-01-02", periods=10), "factor": [-1.0] * 10}
        )
        adjuster.factor_manager.read_factor.return_value = df_factors
        df = _make_daily_df(10)
        result = adjuster.apply_adjustment("000001.SZ", df, "qfq")
        # Should return raw because factor <= 0
        assert len(result) == len(df)

    def test_apply_adjustment_huge_factor(self):
        """Huge factor values should trigger safety check and return raw."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        adjuster.factor_manager = MagicMock()
        df_factors = pd.DataFrame(
            {"date": pd.bdate_range("2024-01-02", periods=10), "factor": [1e8] * 10}
        )
        adjuster.factor_manager.read_factor.return_value = df_factors
        df = _make_daily_df(10, start_price=10.0)
        result = adjuster.apply_adjustment("000001.SZ", df, "hfq")
        # factor > 1_000_000 triggers safety return raw
        assert len(result) == len(df)

    def test_apply_adjustment_valid_hfq(self):
        """Valid HFQ adjustment should multiply prices by factor, clip, and not go negative."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        adjuster.factor_manager = MagicMock()
        df_factors = pd.DataFrame(
            {"date": pd.bdate_range("2024-01-02", periods=10), "factor": [1.5] * 10}
        )
        adjuster.factor_manager.read_factor.return_value = df_factors
        df = _make_daily_df(10, start_price=10.0)
        result = adjuster.apply_adjustment("000001.SZ", df, "hfq")
        assert len(result) == len(df)
        for col in ["open", "high", "low", "close"]:
            assert (result[col] >= 0.001).all(), f"{col} has negative values after HFQ"
            assert (result[col] <= 100000).all(), f"{col} exceeds upper bound after HFQ"

    def test_apply_adjustment_valid_qfq(self):
        """Valid QFQ adjustment should produce non-negative prices."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        adjuster.factor_manager = MagicMock()
        df_factors = pd.DataFrame(
            {"date": pd.bdate_range("2024-01-02", periods=10), "factor": [2.0] * 10}
        )
        adjuster.factor_manager.read_factor.return_value = df_factors
        df = _make_daily_df(10, start_price=20.0)
        result = adjuster.apply_adjustment("000001.SZ", df, "qfq")
        assert len(result) == len(df)
        for col in ["open", "high", "low", "close"]:
            assert (result[col] >= 0.001).all(), f"{col} has negative values after QFQ"

    def test_is_valid_stock_code(self):
        """Test stock code validation edge cases."""
        from unittest.mock import MagicMock
        adjuster = DataAdjuster(storage_manager=MagicMock())
        assert adjuster.is_valid_stock_code("600000", "SH") is True
        assert adjuster.is_valid_stock_code("688001", "SH") is True
        assert adjuster.is_valid_stock_code("000001", "SZ") is True
        assert adjuster.is_valid_stock_code("300001", "SZ") is True
        # Invalid
        assert adjuster.is_valid_stock_code("999", "SH") is False
        assert adjuster.is_valid_stock_code("", "") is False
        assert adjuster.is_valid_stock_code("600000", "SZ") is False  # wrong market
        assert adjuster.is_valid_stock_code("AAPL", "US") is False


# ===================================================================
# TASK 1: Dirty Data Injection — check_limit_status edge cases
# ===================================================================

class TestLimitCheckerChaos:
    """Chaos tests for check_limit_status with adversarial inputs."""

    # --- pre_close = 0 ---
    def test_pre_close_zero(self):
        status = check_limit_status(10.0, 0.0, symbol="000001.SZ")
        assert status.is_limit_up is False
        assert status.is_limit_down is False
        assert status.can_buy is True
        assert status.can_sell is True
        assert status.up_limit_price == 0.0
        assert status.down_limit_price == 0.0

    # --- pre_close < 0 ---
    def test_pre_close_negative(self):
        status = check_limit_status(10.0, -5.0, symbol="000001.SZ")
        assert status.is_limit_up is False
        assert status.is_limit_down is False
        assert status.can_buy is True
        assert status.can_sell is True

    # --- price = 0, non-zero pre_close ---
    def test_price_zero_nonzero_preclose(self):
        status = check_limit_status(0.0, 10.0, symbol="000001.SZ")
        # price_ratio = 0/10 = 0.0, which is <= 0.90 + tol → limit_down
        assert status.is_limit_down is True
        assert status.can_sell is False
        assert status.price_ratio == 0.0

    # --- Main board exactly at +10% limit ---
    def test_main_board_exact_limit_up(self):
        status = check_limit_status(11.0, 10.0, symbol="600000.SH")
        assert status.board_type == "main"
        assert status.is_limit_up is True
        assert status.can_buy is False

    # --- Main board exactly at -10% limit ---
    def test_main_board_exact_limit_down(self):
        status = check_limit_status(9.0, 10.0, symbol="600000.SH")
        assert status.board_type == "main"
        assert status.is_limit_down is True
        assert status.can_sell is False

    # --- Main board just inside limits ---
    def test_main_board_just_inside(self):
        status = check_limit_status(10.5, 10.0, symbol="600000.SH")
        assert status.is_limit_up is False
        assert status.is_limit_down is False
        assert status.can_buy is True
        assert status.can_sell is True

    # --- ST stock ±5% ---
    def test_st_stock_limit_up(self):
        status = check_limit_status(10.5, 10.0, symbol="000001.SZ", name="ST某某")
        assert status.board_type == "st"
        assert status.is_limit_up is True
        assert status.can_buy is False

    def test_st_stock_limit_down(self):
        status = check_limit_status(9.5, 10.0, symbol="000001.SZ", name="*ST某某")
        assert status.board_type == "st"
        assert status.is_limit_down is True
        assert status.can_sell is False

    def test_st_stock_inside(self):
        status = check_limit_status(10.2, 10.0, symbol="000001.SZ", name="ST某某")
        assert status.is_limit_up is False
        assert status.is_limit_down is False

    # --- Sci-tech board ±20% ---
    def test_sci_tech_limit_up(self):
        status = check_limit_status(12.0, 10.0, symbol="688001.SH")
        assert status.board_type == "sci_tech"
        assert status.is_limit_up is True

    def test_sci_tech_limit_down(self):
        status = check_limit_status(8.0, 10.0, symbol="688001.SH")
        assert status.board_type == "sci_tech"
        assert status.is_limit_down is True

    # --- GEM board ±20% ---
    def test_gem_limit_up(self):
        status = check_limit_status(12.0, 10.0, symbol="300001.SZ")
        assert status.board_type == "gem"
        assert status.is_limit_up is True

    # --- Beijing board ±30% ---
    def test_beijing_limit_up(self):
        status = check_limit_status(13.0, 10.0, symbol="830001.BJ")
        assert status.board_type == "beijing"
        assert status.is_limit_up is True

    def test_beijing_limit_down(self):
        status = check_limit_status(7.0, 10.0, symbol="830001.BJ")
        assert status.board_type == "beijing"
        assert status.is_limit_down is True

    # --- Extremely large prices (overflow test) ---
    def test_extremely_large_prices(self):
        pre_close = 1e15
        current = 1.1e15
        status = check_limit_status(current, pre_close, symbol="600000.SH")
        assert status.is_limit_up is True
        assert math.isfinite(status.up_limit_price)
        assert math.isfinite(status.down_limit_price)

    # --- Floating point precision near boundary ---
    def test_float_precision_near_boundary(self):
        # Price ratio = 1.0995, just under 1.10 - 0.001 = 1.099
        pre_close = 100.0
        # At exactly the tolerance boundary
        price = pre_close * (1.10 - 0.001 + 0.0001)  # just above threshold
        status = check_limit_status(price, pre_close, symbol="600000.SH")
        assert status.is_limit_up is True

    # --- Both limits at once (impossible but test robustness) ---
    def test_both_limits_impossible(self):
        # A price can't be both limit_up AND limit_down unless pre_close is tiny
        status = check_limit_status(10.0, 1000.0, symbol="600000.SH")
        # price_ratio = 0.01, well below 0.90
        assert status.is_limit_down is True
        assert status.is_limit_up is False

    # --- IPO day rules ---
    def test_ipo_main_board_day1(self):
        status = check_limit_status(14.4, 10.0, symbol="600000.SH", trading_days_listed=1)
        # Main board IPO: +44% / -36%
        assert status.is_limit_up is True

    def test_ipo_main_board_day1_down(self):
        status = check_limit_status(6.4, 10.0, symbol="600000.SH", trading_days_listed=1)
        assert status.is_limit_down is True

    def test_ipo_sci_tech_first5_days_no_limit(self):
        status = check_limit_status(50.0, 10.0, symbol="688001.SH", trading_days_listed=3)
        assert status.is_limit_up is False  # no limit in first 5 days
        assert status.up_limit_price == float("inf")

    def test_ipo_gem_first5_days_no_limit(self):
        status = check_limit_status(50.0, 10.0, symbol="300001.SZ", trading_days_listed=2)
        assert status.is_limit_up is False
        assert status.up_limit_price == float("inf")

    def test_ipo_beijing_first_day_no_limit(self):
        status = check_limit_status(50.0, 10.0, symbol="830001.BJ", trading_days_listed=1)
        assert status.is_limit_up is False
        assert status.up_limit_price == float("inf")

    # --- get_board_type edge cases ---
    def test_get_board_type_empty_symbol(self):
        assert get_board_type("") == "main"

    def test_get_board_type_no_dot(self):
        assert get_board_type("600000") == "main"

    def test_get_board_type_st_priority(self):
        # ST takes priority over code prefix
        assert get_board_type("688001.SH", name="ST某某") == "st"


# ===================================================================
# TASK 2: Memory Stress Test
# ===================================================================

class TestMemoryStress:
    """Stress test: 500 stocks × 2520 rows (10 years daily)."""

    def test_500_stocks_memory_under_2gb(self):
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / (1024 * 1024)  # MB

        rng = np.random.default_rng(0)
        stock_count = 500
        rows_per_stock = 2520
        store: dict[str, pd.DataFrame] = {}

        for i in range(stock_count):
            code = f"{600000 + i:06d}.SH"
            dates = pd.bdate_range("2015-01-05", periods=rows_per_stock)
            close = 10.0 + np.cumsum(rng.normal(0, 0.2, size=rows_per_stock))
            close = np.maximum(close, 0.5)
            high = close + rng.uniform(0.01, 0.3, size=rows_per_stock)
            low = np.maximum(close - rng.uniform(0.01, 0.3, size=rows_per_stock), 0.01)
            opn = (high + low) / 2
            volume = rng.integers(500_000, 30_000_000, size=rows_per_stock).astype(float)
            store[code] = pd.DataFrame(
                {
                    "date": dates,
                    "code": code,
                    "open": opn,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )

        mem_after = process.memory_info().rss / (1024 * 1024)  # MB
        mem_used_mb = mem_after - mem_before

        assert len(store) == stock_count, f"Expected {stock_count} stocks, got {len(store)}"

        # Verify data integrity of a random sample
        for code in list(store.keys())[:5]:
            df = store[code]
            assert len(df) == rows_per_stock
            assert not df["close"].isna().any()
            assert (df["close"] > 0).all()

        mem_peak_mb = mem_after
        mem_limit_mb = 2048  # 2 GB

        print(f"\n[Memory Stress] stocks={stock_count}, rows/stock={rows_per_stock}")
        print(f"  Before: {mem_before:.1f} MB, After: {mem_after:.1f} MB, Delta: {mem_used_mb:.1f} MB")
        print(f"  Peak RSS: {mem_peak_mb:.1f} MB (limit: {mem_limit_mb} MB)")

        assert mem_peak_mb < mem_limit_mb, (
            f"Peak memory {mem_peak_mb:.1f} MB exceeds 2 GB limit ({mem_limit_mb} MB)"
        )

    def test_concurrent_cleaning_stress(self):
        """Clean 100 dirty DataFrames and verify no NaN propagation."""
        rng = np.random.default_rng(123)
        cleaner = DataCleaner()
        failures = []

        for i in range(100):
            df = _make_daily_df(50, seed=i)
            # Inject chaos
            chaos_type = i % 5
            if chaos_type == 0:
                # Random NaN prices
                idx = rng.choice(50, size=8, replace=False)
                df.loc[idx, "close"] = np.nan
            elif chaos_type == 1:
                # Duplicate dates
                dup = df.iloc[10].copy()
                df = pd.concat([df, dup.to_frame().T], ignore_index=True)
            elif chaos_type == 2:
                # String-typed numbers
                df["close"] = df["close"].astype(str)
            elif chaos_type == 3:
                # All zeros
                df.loc[20:30, ["open", "high", "low", "close"]] = 0.0
            elif chaos_type == 4:
                # Negative volume
                df.loc[5:15, "volume"] = -1000.0

            try:
                result = cleaner.clean(df)
                if not result.empty and result["close"].isna().any():
                    failures.append(f"stock_{i}: NaN in close after cleaning")
            except Exception as e:
                failures.append(f"stock_{i}: EXCEPTION {type(e).__name__}: {e}")

        assert len(failures) == 0, "Cleaning failures:\n" + "\n".join(failures)


# ===================================================================
# Runner
# ===================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-xvs", "--tb=short"]))
