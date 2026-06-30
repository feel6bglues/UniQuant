"""Tests for TradeCalendarManager AkShare auto-update feature."""
import datetime
import os
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

from uniquant.data.managers.trade_calendar_manager import TradeCalendarManager


def _build_mock_calendar(*, years: list[int], holidays: set[str]) -> pd.DataFrame:
    """Build a mock DataFrame simulating ak.tool_trade_date_hist_sina() output."""
    all_dates = pd.bdate_range(
        f"{min(years)}-01-01", f"{max(years)}-12-31"
    )
    trade_dates = [
        d for d in all_dates if d.strftime("%Y-%m-%d") not in holidays
    ]
    return pd.DataFrame({"trade_date": trade_dates})


class TestTradeCalendarManagerAkShare:
    """Test the AkShare auto-update integration."""

    MOCK_HOLIDAYS = {
        "2027-01-01",
        "2027-02-08", "2027-02-09", "2027-02-10",
        "2027-02-11", "2027-02-12", "2027-02-13", "2027-02-14",
        "2024-01-01",
    }

    @pytest.fixture
    def mock_calendar(self):
        return _build_mock_calendar(
            years=[2024, 2025, 2026, 2027],
            holidays=self.MOCK_HOLIDAYS,
        )

    @pytest.fixture
    def manager(self, mock_calendar):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.return_value = mock_calendar
                mgr = TradeCalendarManager(data_dir=tmpdir)
            yield mgr

    def test_new_year_2027_not_trading_day(self, manager):
        assert not manager.is_trading_day(datetime.date(2027, 1, 1))

    def test_cny_2027_not_trading_day(self, manager):
        assert not manager.is_trading_day(datetime.date(2027, 2, 8))

    def test_normal_weekday_2027_is_trading_day(self, manager):
        assert manager.is_trading_day(datetime.date(2027, 1, 4))

    def test_normal_friday_2027_is_trading_day(self, manager):
        assert manager.is_trading_day(datetime.date(2027, 1, 8))

    def test_weekend_2027_not_trading_day(self, manager):
        assert not manager.is_trading_day(datetime.date(2027, 1, 9))

    def test_existing_holiday_2024_still_works(self, manager):
        assert not manager.is_trading_day(datetime.date(2024, 1, 1))


class TestTradeCalendarManagerStaleCache:
    """Test stale cache triggers auto-update."""

    def test_auto_update_triggers_on_stale_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "trade_calendar.csv")
            old_df = pd.DataFrame({"trade_date": ["2024-01-02"]})
            old_df.to_csv(cache_file, index=False)
            old_ts = (
                datetime.datetime.now() - datetime.timedelta(days=200)
            ).timestamp()
            os.utime(cache_file, (old_ts, old_ts))

            new_calendar = pd.DataFrame(
                {"trade_date": pd.date_range("2027-01-01", "2027-12-31")}
            )

            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.return_value = new_calendar
                mgr = TradeCalendarManager(data_dir=tmpdir)
                mock_func.assert_called_once()
                assert "2027-01-04" in mgr._akshare_calendar

    def test_fresh_cache_does_not_trigger_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "trade_calendar.csv")
            calendar_data = _build_mock_calendar(
                years=[2024, 2025, 2026, 2027],
                holidays={"2027-01-01"},
            )
            calendar_data.to_csv(cache_file, index=False, encoding="utf-8-sig")

            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mgr = TradeCalendarManager(data_dir=tmpdir)
                mock_func.assert_not_called()
                assert mgr._akshare_calendar is not None

    def test_missing_cache_triggers_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_calendar = _build_mock_calendar(
                years=[2027], holidays={"2027-01-01"}
            )
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.return_value = new_calendar
                mgr = TradeCalendarManager(data_dir=tmpdir)
                mock_func.assert_called_once()
                assert mgr._akshare_calendar is not None


class TestTradeCalendarManagerHardcodedFallback:
    """Test hardcoded fallback when AkShare is unavailable."""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.side_effect = ImportError("no akshare")
                mgr = TradeCalendarManager(data_dir=tmpdir)
            yield mgr

    def test_2024_new_year_not_trading(self, manager):
        assert not manager.is_trading_day(datetime.date(2024, 1, 1))

    def test_2024_weekday_is_trading_day(self, manager):
        assert manager.is_trading_day(datetime.date(2024, 1, 2))

    def test_2024_weekend_not_trading_day(self, manager):
        assert not manager.is_trading_day(datetime.date(2024, 1, 6))

    def test_2024_special_workday_is_trading(self, manager):
        assert manager.is_trading_day(datetime.date(2024, 2, 4))

    def test_2025_new_year_not_trading(self, manager):
        assert not manager.is_trading_day(datetime.date(2025, 1, 1))

    def test_2025_cny_not_trading(self, manager):
        assert not manager.is_trading_day(datetime.date(2025, 1, 28))


class TestTradeCalendarManagerEdgeCases:
    """Test edge cases for the auto-update feature."""

    def test_akshare_returns_empty_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.return_value = pd.DataFrame()
                mgr = TradeCalendarManager(data_dir=tmpdir)
                assert mgr._akshare_calendar is None

    def test_akshare_raises_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.side_effect = RuntimeError("network error")
                mgr = TradeCalendarManager(data_dir=tmpdir)
                assert mgr._akshare_calendar is None

    def test_is_trading_day_year_before_2024(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_calendar = _build_mock_calendar(
                years=[2020, 2021, 2022, 2023, 2024],
                holidays={"2021-01-01"},
            )
            with patch("akshare.tool_trade_date_hist_sina") as mock_func:
                mock_func.return_value = new_calendar
                mgr = TradeCalendarManager(data_dir=tmpdir)

            assert mgr.is_trading_day(datetime.date(2020, 1, 2))
            assert not mgr.is_trading_day(datetime.date(2021, 1, 1))
