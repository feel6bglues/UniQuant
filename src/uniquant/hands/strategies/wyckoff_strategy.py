from .base import HAS_BACKTRADER, BaseStrategy, bt

if HAS_BACKTRADER:

    class WyckoffStrategy(BaseStrategy):
        """
        Wyckoff Volume-Price Analysis Strategy.

        Entries:
          - SPRING: Price breaks below recent support then quickly rebounds
            with expanding volume (failed breakdown).
          - SOS (Sign of Strength): Price breaks above resistance with
            volume confirmation.

        Exits:
          - Price falls below support level.
          - Take-profit target reached (risk-reward based).
        """

        params = (
            ("lookback_days", 200),
            ("volume_ratio_threshold", 1.5),
            ("atr_multiplier", 2.0),
            ("atr_period", 14),
            ("volume_ma_period", 20),
            ("support_resistance_lookback", 20),
            ("rr_ratio", 3.0),
            ("verbose", True),
        )

        def __init__(self):
            super().__init__()
            self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
            self.volume_ma = bt.indicators.SMA(
                self.data.volume, period=self.params.volume_ma_period
            )
            self.lowest = bt.indicators.Lowest(
                self.data.low, period=self.params.support_resistance_lookback
            )
            self.highest = bt.indicators.Highest(
                self.data.high, period=self.params.support_resistance_lookback
            )

        def _is_volume_expanded(self) -> bool:
            """Check if current volume exceeds threshold * MA(volume)."""
            if self.volume_ma[0] == 0:
                return False
            return (
                self.data.volume[0] / self.volume_ma[0]
                > self.params.volume_ratio_threshold
            )

        def _detect_spring(self) -> bool:
            """
            Spring: price dipped below recent low (support) within lookback
            and then closed back above it, with volume expansion.
            """
            support = self.lowest[-1]
            # Previous bar touched or broke support
            prev_broke_support = self.data.low[-1] <= support
            # Current bar closes back above support
            recovered = self.data.close[0] > support
            return prev_broke_support and recovered and self._is_volume_expanded()

        def _detect_sos(self) -> bool:
            """
            Sign of Strength: price breaks above recent high (resistance)
            with volume confirmation.
            """
            resistance = self.highest[-1]
            breakout = (
                self.data.close[0] > resistance
                and self.data.close[-1] <= resistance
            )
            return breakout and self._is_volume_expanded()

        def next(self):
            if self.orders:
                return

            if not self.position:
                # Entry Logic
                if self._detect_spring():
                    stop_price = self.data.low[0] - self.atr[0] * self.params.atr_multiplier
                    self.log(
                        f"SPRING DETECTED: close={self.data.close[0]:.2f}, "
                        f"stop={stop_price:.2f}, vol_ratio={self.data.volume[0] / self.volume_ma[0]:.2f}"
                    )
                    size = self.calculate_position_size(stop_price=stop_price)
                    if size > 0:
                        order = self.buy(size=size)
                        self.orders[order.ref] = order

                elif self._detect_sos():
                    stop_price = self.data.low[0] - self.atr[0] * self.params.atr_multiplier
                    self.log(
                        f"SOS DETECTED: close={self.data.close[0]:.2f}, "
                        f"stop={stop_price:.2f}, vol_ratio={self.data.volume[0] / self.volume_ma[0]:.2f}"
                    )
                    size = self.calculate_position_size(stop_price=stop_price)
                    if size > 0:
                        order = self.buy(size=size)
                        self.orders[order.ref] = order
            else:
                # Exit Logic
                entry_price = self.position.price
                atr_at_entry = self.atr[0]
                support = self.lowest[0]
                take_profit = entry_price + atr_at_entry * self.params.atr_multiplier * self.params.rr_ratio

                # Hard exit: price falls below support
                if self.data.close[0] < support:
                    self.log(
                        f"EXIT (Price < Support): close={self.data.close[0]:.2f}, "
                        f"support={support:.2f}"
                    )
                    order = self.close()
                    self.orders[order.ref] = order

                # Take-profit exit
                elif self.data.close[0] >= take_profit:
                    self.log(
                        f"EXIT (Take Profit): close={self.data.close[0]:.2f}, "
                        f"target={take_profit:.2f}"
                    )
                    order = self.close()
                    self.orders[order.ref] = order

else:

    class WyckoffStrategy(BaseStrategy):
        """
        Mock WyckoffStrategy class when backtrader is not available.
        """

        def __init__(self):
            super().__init__()

        def next(self):
            pass
