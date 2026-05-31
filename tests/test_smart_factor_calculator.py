import pytest
import pandas as pd
import numpy as np

from uniquant.data.utils.smart_factor_calculator import (
    GBBQProcessorV15,
    SmartFactorCalculatorV15,
)


class TestGBBQProcessorV15:
    def test_aggregate_events_empty(self):
        assert GBBQProcessorV15.aggregate_events(pd.DataFrame()).empty

    def test_aggregate_events_same_day(self):
        df = pd.DataFrame({
            'date': pd.to_datetime(['2025-06-01', '2025-06-01']),
            'cash': [1.0, 2.0],
            'split': [0.0, 3.0],
            'rights': [0.0, 0.0],
            'r_price': [0.0, 0.0],
        })
        result = GBBQProcessorV15.aggregate_events(df)
        assert len(result) == 1
        assert result['cash'].iloc[0] == 3.0
        assert result['split'].iloc[0] == 3.0


class TestSmartFactorCalculatorV15:
    def make_daily(self, close_prices, start="2025-01-01"):
        n = len(close_prices)
        dates = pd.date_range(start, periods=n, freq="B")
        close = np.array(close_prices, dtype=float)
        return pd.DataFrame({
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
        })

    def make_event(self, date, cash=0.0, split=0.0, rights=0.0, r_price=0.0):
        return pd.DataFrame([{
            'date': pd.Timestamp(date),
            'cash': cash,
            'split': split,
            'rights': rights,
            'r_price': r_price,
        }])

    def test_no_events_returns_one(self):
        df = self.make_daily([100] * 10)
        events = pd.DataFrame()
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert not result.empty
        assert (result['factor'] == 1.0).all()

    def test_empty_daily_returns_empty(self):
        result = SmartFactorCalculatorV15().calculate(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_cash_dividend(self):
        """每10股派1元(per-share cash=0.1) → factor = 10/(10-0.1) ≈ 1.0101"""
        df = self.make_daily([10.0, 10.0, 9.5, 9.8])
        events = self.make_event(df['date'].iloc[2], cash=0.1)
        result = SmartFactorCalculatorV15().calculate(df, events)
        f = result['factor'].iloc[2]
        expected = 10.0 / (10.0 - 0.1)
        assert abs(f - expected) < 1e-6

    def test_split_10_to_5(self):
        """10送5(per-share split=0.5) → factor ≈ 1.5 (rounding允许0.1%)"""
        df = self.make_daily([20.0, 20.0, 13.33, 13.5])
        events = self.make_event(df['date'].iloc[2], split=0.5)
        result = SmartFactorCalculatorV15().calculate(df, events)
        f = result['factor'].iloc[2]
        assert f == pytest.approx(1.5, rel=1e-3)

    def test_split_10_to_10(self):
        """10送10(per-share split=1.0) → factor = 2.0"""
        df = self.make_daily([30.0, 30.0, 15.0, 15.5])
        events = self.make_event(df['date'].iloc[2], split=1.0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        f = result['factor'].iloc[2]
        assert abs(f - 2.0) < 1e-6

    def test_rights_issue(self):
        """10配3(per-share rights=0.3), 配股价8元, pre_close=10"""
        pre_close = 10.0
        df = self.make_daily([pre_close, pre_close, 9.3, 9.5])
        events = self.make_event(df['date'].iloc[2], rights=0.3, r_price=8.0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        numerator = pre_close - 0 + (8.0 * 0.3)
        denominator = 1.0 + 0 + 0.3
        ex_price = round(numerator / denominator, 2)
        expected_factor = pre_close / ex_price
        f = result['factor'].iloc[2]
        assert abs(f - expected_factor) < 1e-6

    def test_multiple_events_cumulative(self):
        """10送10(×2 split=1.0) then 10派1(cash=0.1) → 累积验证"""
        df = self.make_daily([20.0, 10.0, 9.5, 9.8, 9.5, 9.6], start="2025-01-01")
        events = pd.concat([
            self.make_event(df['date'].iloc[1], split=1.0),
            self.make_event(df['date'].iloc[4], cash=0.1),
        ])
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert result['factor'].iloc[1] == pytest.approx(2.0, rel=1e-6)
        assert result['factor'].iloc[4] > result['factor'].iloc[1]

    def test_calculate_cumulative_factor_compat(self):
        df = self.make_daily([100] * 5)
        events = pd.DataFrame()
        calc = SmartFactorCalculatorV15()
        r1 = calc.calculate(df, events)
        r2 = calc.calculate_cumulative_factor(df, events)
        pd.testing.assert_frame_equal(r1, r2)

    def test_event_before_data_ignored(self):
        """除权日在第一根K线之前 → 忽略"""
        df = self.make_daily([100] * 5)
        events = self.make_event(pd.Timestamp("2024-12-01"), split=10.0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert (result['factor'] == 1.0).all()

    def test_zero_pre_close_skipped(self):
        """前收盘为0 → 跳过该事件"""
        df = self.make_daily([0.0, 10.0, 9.0])
        events = self.make_event(df['date'].iloc[1], split=10.0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert not result.empty

    def test_rights_no_price_skipped(self):
        """有配股比例但配股价为0 → rights 归零"""
        df = self.make_daily([10.0, 10.0, 9.5])
        events = self.make_event(df['date'].iloc[1], rights=3.0, r_price=0.0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert result['factor'].iloc[1] == pytest.approx(1.0, abs=1e-6)

    def test_pre_close_ex_price_zero_skipped(self):
        """除权价≤0 → 忽略"""
        df = self.make_daily([10.0, 10.0, 9.5])
        events = self.make_event(df['date'].iloc[1], cash=9999999, split=0, rights=0)
        result = SmartFactorCalculatorV15().calculate(df, events)
        assert result['factor'].iloc[1] == pytest.approx(1.0, abs=1e-6)
