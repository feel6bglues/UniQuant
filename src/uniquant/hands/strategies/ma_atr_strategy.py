from .base import HAS_BACKTRADER, BaseStrategy, bt

if HAS_BACKTRADER:

    class MaAtrStrategy(BaseStrategy):
        """
        MA-ATR Strategy: 均线交叉 + ATR 动态止损。

        入场: MA5 上穿 MA20 (金叉)
        出场: MA5 下穿 MA20 (死叉) 或 ATR 止损触发

        Parameters:
            fast_period: 快线周期, default 5
            slow_period: 慢线周期, default 20
            atr_period: ATR 计算周期, default 20
            atr_multiplier: ATR 止损倍数, default 2.0
        """

        params = (
            ("fast_period", 5),
            ("slow_period", 20),
            ("atr_period", 20),
            ("atr_multiplier", 2.0),
            ("verbose", True),
        )

        def __init__(self):
            super().__init__()
            self.ma_fast = bt.indicators.SMA(
                self.data.close, period=self.params.fast_period
            )
            self.ma_slow = bt.indicators.SMA(
                self.data.close, period=self.params.slow_period
            )
            self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
            self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)
            self.stop_price = None

        def next(self):
            if self.orders:
                return

            if not self.position:
                # 金叉入场
                if self.crossover[0] > 0:
                    self.stop_price = self.data.close[0] - self.params.atr_multiplier * self.atr[0]
                    self.log(
                        f"BUY SIGNAL (Golden Cross): Price={self.data.close[0]:.2f}, "
                        f"Stop={self.stop_price:.2f}"
                    )
                    size = self.calculate_position_size(stop_price=self.stop_price)
                    if size > 0:
                        order = self.buy(size=size)
                        self.orders[order.ref] = order
            else:
                # 死叉出场
                if self.crossover[0] < 0:
                    self.log(
                        f"SELL SIGNAL (Death Cross): Price={self.data.close[0]:.2f}"
                    )
                    order = self.close()
                    self.orders[order.ref] = order
                    self.stop_price = None
                # ATR 止损
                elif self.stop_price and self.data.close[0] < self.stop_price:
                    self.log(
                        f"SELL SIGNAL (ATR Stop): Price={self.data.close[0]:.2f}, "
                        f"Stop={self.stop_price:.2f}"
                    )
                    order = self.close()
                    self.orders[order.ref] = order
                    self.stop_price = None
                else:
                    # 移动止损: 跟踪最高价
                    new_stop = self.data.close[0] - self.params.atr_multiplier * self.atr[0]
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop

else:

    class MaAtrStrategy(BaseStrategy):
        """
        Mock MaAtrStrategy class when backtrader is not available.
        """

        def __init__(self):
            super().__init__()

        def next(self):
            pass
