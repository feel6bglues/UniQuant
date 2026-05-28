"""
Regime Strategy - 基于市场状态 (Regime) 驱动的交易策略

市场状态:
  - NORMAL: 正常交易，使用趋势跟踪信号 (MA20/MA60 金叉/死叉)
  - STRESSED: 减仓，降低风险敞口
  - FROZEN: 停止交易，清仓观望

依赖:
  - brain.regime_detector.RegimeDetector (流动性状态检测器)
  - backtrader (可选)
"""

from .base import HAS_BACKTRADER, BaseStrategy, bt

if HAS_BACKTRADER:
    import pandas as pd

    try:
        from uniquant.brain.regime_detector import Regime, RegimeDetector
    except ImportError:
        RegimeDetector = None
        Regime = None

    class RegimeStrategy(BaseStrategy):
        """
        Regime-driven strategy.

        Entry (NORMAL only):
          - Price crosses above MA60 (trend breakout).
        Exit:
          - Price falls below MA60, OR
          - Regime shifts to STRESSED (partial exit) or FROZEN (full exit).
        """

        params = (
            ("regime_threshold", 0.5),
            ("reduce_ratio", 0.5),
            ("ma_short", 20),
            ("ma_long", 60),
            ("verbose", True),
        )

        def __init__(self):
            super().__init__()
            self.atr = bt.indicators.ATR(self.data, period=14)
            self.ma20 = bt.indicators.SMA(
                self.data.close, period=self.params.ma_short
            )
            self.ma60 = bt.indicators.SMA(
                self.data.close, period=self.params.ma_long
            )
            self._regime_detector = (
                RegimeDetector() if RegimeDetector else None
            )
            self._current_regime = Regime.NORMAL if Regime else None

        def _detect_regime(self):
            """Build a rolling DataFrame from backtrader data and detect regime."""
            if not self._regime_detector:
                return Regime.NORMAL if Regime else "NORMAL"

            lookback = 120
            n = min(len(self), lookback)
            if n < 60:
                return Regime.NORMAL if Regime else "NORMAL"

            closes = [self.data.close[-i] for i in range(n - 1, -1, -1)]
            volumes = [self.data.volume[-i] for i in range(n - 1, -1, -1)]

            df = pd.DataFrame({"close": closes, "volume": volumes})
            return self._regime_detector.detect(df)

        def _regime_label(self) -> str:
            if self._current_regime is None:
                return "NORMAL"
            if hasattr(self._current_regime, "value"):
                return self._current_regime.value
            return str(self._current_regime)

        def next(self):
            if self.orders:
                return

            self._current_regime = self._detect_regime()
            regime = self._regime_label()

            if regime == "FROZEN":
                if self.position:
                    self.log(f"FROZEN regime -> close all: {self.data.close[0]:.2f}")
                    order = self.close()
                    self.orders[order.ref] = order
                return

            if not self.position:
                if regime != "NORMAL":
                    return

                if (
                    self.data.close[0] > self.ma60[0]
                    and self.data.close[-1] <= self.ma60[-1]
                ):
                    self.log(
                        f"NORMAL regime, breakout MA60: {self.data.close[0]:.2f}"
                    )
                    size = self.calculate_position_size(
                        stop_price=self.ma60[0]
                    )
                    if size > 0:
                        order = self.buy(size=size)
                        self.orders[order.ref] = order

                elif self.ma20[0] > self.ma60[0] and self.data.close[0] > self.ma60[0]:
                    diff_pct = abs(self.data.close[0] - self.ma20[0]) / self.ma20[0]
                    if diff_pct < 0.02:
                        self.log(
                            f"NORMAL regime, pullback MA20: {self.data.close[0]:.2f}"
                        )
                        size = self.calculate_position_size(
                            stop_price=self.ma60[0]
                        )
                        if size > 0:
                            order = self.buy(size=size)
                            self.orders[order.ref] = order
            else:
                if regime == "STRESSED":
                    reduce_size = max(
                        1, int(self.position.size * self.params.reduce_ratio)
                    )
                    self.log(
                        f"STRESSED regime -> reduce {reduce_size}: {self.data.close[0]:.2f}"
                    )
                    order = self.sell(size=reduce_size)
                    self.orders[order.ref] = order

                elif self.data.close[0] < self.ma60[0]:
                    self.log(f"EXIT (Price < MA60): {self.data.close[0]:.2f}")
                    order = self.close()
                    self.orders[order.ref] = order

else:

    class RegimeStrategy(BaseStrategy):
        """Mock RegimeStrategy when backtrader is not available."""

        def __init__(self):
            super().__init__()

        def next(self):
            pass
