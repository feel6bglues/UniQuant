from .base import HAS_BACKTRADER, BaseStrategy, bt

if HAS_BACKTRADER:

    class FSMStrategy(BaseStrategy):
        """
        FSM Strategy based on MA20/MA60 trend analysis.
        Entries:
          - SIGNAL: Price breakout MA60.
          - PROBE: Price pullback to MA20 while MA20 > MA60.
        Exits:
          - Price falls below MA60.
        """

        params = (
            ("ma_short", 20),
            ("ma_long", 60),
        )

        def __init__(self):
            super().__init__()
            self.ma20 = bt.indicators.SMA(self.data.close, period=self.params.ma_short)
            self.ma60 = bt.indicators.SMA(self.data.close, period=self.params.ma_long)

        def next(self):
            # Allow orders only if we are not pending
            if self.orders:
                return

            if not self.position:
                # Entry Logic

                # 1. SIGNAL State (Breakout)
                # Price crosses over MA60
                if (
                    self.data.close[0] > self.ma60[0]
                    and self.data.close[-1] <= self.ma60[-1]
                ):
                    self.log(
                        f"SIGNAL DETECTED (Breakout MA60): {self.data.close[0]:.2f}"
                    )
                    # Stop loss at MA60
                    size = self.calculate_position_size(stop_price=self.ma60[0])
                    if size > 0:
                        order = self.buy(size=size)
                        self.orders[order.ref] = order

                # 2. PROBE State (Pullback)
                # MA20 > MA60 and Price is close to MA20 (within 2%)
                elif self.ma20[0] > self.ma60[0] and self.data.close[0] > self.ma60[0]:
                    diff_pct = abs(self.data.close[0] - self.ma20[0]) / self.ma20[0]
                    if diff_pct < 0.02:
                        # Check if we have positive momentum or just wait?
                        # Simple logic: Buy
                        self.log(
                            f"PROBE DETECTED (Pullback MA20): {self.data.close[0]:.2f}"
                        )
                        size = self.calculate_position_size(stop_price=self.ma60[0])
                        if size > 0:
                            order = self.buy(size=size)
                            self.orders[order.ref] = order
            else:
                # Exit Logic
                # Hard Exit: Price < MA60
                if self.data.close[0] < self.ma60[0]:
                    self.log(f"EXIT SIGNAL (Price < MA60): {self.data.close[0]:.2f}")
                    order = self.close()
                    self.orders[order.ref] = order

else:

    class FSMStrategy(BaseStrategy):
        """
        Mock FSMStrategy class when backtrader is not available.
        """

        def __init__(self):
            super().__init__()

        def next(self):
            pass
