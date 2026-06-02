from typing import Optional

import pandas as pd

from uniquant.signal.models import Signal
from uniquant.signal.aggregator import SignalAggregator, SignalAggregationMethod


class SignalBacktestIntegrator:
    def __init__(self, aggregator: Optional[SignalAggregator] = None):
        self.aggregator = aggregator or SignalAggregator(
            method=SignalAggregationMethod.WEIGHTED_AVERAGE
        )

    def generate_trades_from_signals(
        self, signals: list[Signal], price_data: pd.DataFrame
    ) -> pd.DataFrame:
        if not signals or price_data.empty:
            return pd.DataFrame()

        by_time: dict = {}
        for s in signals:
            ts = s.timestamp.replace(minute=0, second=0, microsecond=0)
            if ts not in by_time:
                by_time[ts] = []
            by_time[ts].append(s)

        trades = []
        for ts, sigs in sorted(by_time.items()):
            agg = self.aggregator.aggregate(sigs)
            if agg is None or agg.direction == 0:
                continue
            price = sigs[0].price
            if price <= 0 and ts in price_data.index:
                price = price_data.loc[ts].iloc[0] if isinstance(price_data.loc[ts], pd.Series) else price_data.loc[ts]
            trades.append({
                "timestamp": ts,
                "direction": agg.direction,
                "confidence": agg.confidence,
                "price": price,
                "signal_count": len(sigs),
                "agreement_ratio": agg.agreement_ratio,
                "weighted_score": agg.weighted_score,
            })

        return pd.DataFrame(trades)

    def merge_with_backtest(
        self, trades: pd.DataFrame, backtest_results: pd.DataFrame
    ) -> pd.DataFrame:
        if trades.empty:
            return backtest_results
        merged = backtest_results.copy()
        if "signal_direction" not in merged.columns:
            merged["signal_direction"] = 0
            merged["signal_confidence"] = 0.0
        for idx, row in trades.iterrows():
            mask = merged.index.get_indexer([row["timestamp"]], method="nearest")
            if len(mask) > 0 and mask[0] >= 0:
                merged.iloc[mask[0], merged.columns.get_loc("signal_direction")] = row["direction"]
                merged.iloc[mask[0], merged.columns.get_loc("signal_confidence")] = row["confidence"]
        return merged

    @staticmethod
    def evaluate_signal_value(
        trades: pd.DataFrame, price_data: pd.Series, holding_periods: int = 5
    ) -> float:
        if trades.empty:
            return 0.0
        total_return = 0.0
        for _, trade in trades.iterrows():
            try:
                idx = price_data.index.get_loc(trade["timestamp"])
            except (KeyError, TypeError):
                continue
            if idx + holding_periods >= len(price_data):
                continue
            entry = trade["price"]
            exit_price = price_data.iloc[idx + holding_periods]
            ret = (exit_price - entry) / entry
            total_return += ret * trade["direction"]
        return total_return


class SignalBasedStrategy:
    def __init__(
        self,
        min_confidence: float = 0.6,
        min_agreement: float = 0.5,
        signal_expiry: int = 24,
    ):
        self.min_confidence = min_confidence
        self.min_agreement = min_agreement
        self.signal_expiry = signal_expiry

    def should_enter(self, signal: Signal, position: int = 0) -> bool:
        if position != 0:
            return False
        if signal.confidence < self.min_confidence:
            return False
        if signal.is_expired():
            return False
        return True

    def should_exit(self, signal: Signal, position: int) -> bool:
        if position == 0:
            return False
        if signal.is_expired():
            return True
        if signal.direction != 0 and signal.direction != position:
            if signal.confidence >= self.min_confidence:
                return True
        return False

    def generate_signal_action(self, signal: Signal, position: int) -> int:
        if self.should_exit(signal, position):
            return 0
        if self.should_enter(signal, position):
            return signal.direction
        return position
