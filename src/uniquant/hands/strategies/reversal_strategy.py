from .base import HAS_BACKTRADER, BaseStrategy, bt

if HAS_BACKTRADER:

    class ReversalStrategy(BaseStrategy):
        """
        Short-term oversold reversal strategy.

        Entry:
          - Price drops more than threshold_pct within lookback_days.
          - RSI enters oversold zone (below 30).

        Exit:
          - Take profit: price rises take_profit_pct from entry.
          - Stop loss: price falls stop_loss_pct from entry.
          - Max hold: exit after hold_days bars.
        """

        params = (
            ("lookback_days", 5),
            ("threshold_pct", 5.0),
            ("hold_days", 5),
            ("take_profit_pct", 4.0),
            ("stop_loss_pct", 4.0),
            ("rsi_period", 14),
            ("rsi_oversold", 30),
            ("verbose", True),
        )

        def __init__(self):
            super().__init__()
            self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
            self.atr = bt.indicators.ATR(self.data, period=14)
            self.entry_price = None
            self.entry_bar = None

        def next(self):
            if self.orders:
                return

            if not self.position:
                self._try_entry()
            else:
                self._try_exit()

        def _try_entry(self):
            lookback = self.params.lookback_days
            if len(self) < lookback + 1:
                return

            past_close = self.data.close[-lookback]
            curr_close = self.data.close[0]
            drop_pct = (past_close - curr_close) / past_close * 100.0

            if drop_pct >= self.params.threshold_pct and self.rsi[0] < self.params.rsi_oversold:
                self.log(
                    f"REVERSAL SIGNAL: drop {drop_pct:.2f}% in {lookback}d, "
                    f"RSI {self.rsi[0]:.1f}, close {curr_close:.2f}"
                )
                stop_price = curr_close * (1.0 - self.params.stop_loss_pct / 100.0)
                size = self.calculate_position_size(stop_price=stop_price)
                if size > 0:
                    order = self.buy(size=size)
                    self.orders[order.ref] = order
                    self.entry_price = curr_close
                    self.entry_bar = len(self)

        def _try_exit(self):
            if self.entry_price is None:
                return

            curr_close = self.data.close[0]
            pnl_pct = (curr_close - self.entry_price) / self.entry_price * 100.0
            bars_held = len(self) - self.entry_bar

            if pnl_pct >= self.params.take_profit_pct:
                self.log(
                    f"TAKE PROFIT: +{pnl_pct:.2f}% after {bars_held} bars"
                )
                order = self.close()
                self.orders[order.ref] = order
                self._reset_entry()
            elif pnl_pct <= -self.params.stop_loss_pct:
                self.log(
                    f"STOP LOSS: {pnl_pct:.2f}% after {bars_held} bars"
                )
                order = self.close()
                self.orders[order.ref] = order
                self._reset_entry()
            elif bars_held >= self.params.hold_days:
                self.log(
                    f"MAX HOLD EXIT: {pnl_pct:.2f}% after {bars_held} bars"
                )
                order = self.close()
                self.orders[order.ref] = order
                self._reset_entry()

        def _reset_entry(self):
            self.entry_price = None
            self.entry_bar = None

else:

    class ReversalStrategy(BaseStrategy):
        """
        Mock ReversalStrategy when backtrader is not available.
        """

        def __init__(self):
            super().__init__()

        def next(self):
            pass
