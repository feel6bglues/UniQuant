from abc import ABC, abstractmethod
from datetime import datetime


class SlippageModel(ABC):
    @abstractmethod
    def estimate(self, symbol: str, quantity: int, direction: str,
                 price: float, timestamp: datetime) -> float:
        pass


class DefaultSlippage(SlippageModel):
    def estimate(self, symbol: str, quantity: int, direction: str,
                 price: float, timestamp: datetime) -> float:
        return 0.001


class DynamicSlippage(SlippageModel):
    def estimate(self, symbol: str, quantity: int, direction: str,
                 price: float, timestamp: datetime) -> float:
        liquidity = self._get_liquidity(symbol)
        volatility = self._get_atr(symbol)
        impact = self._market_impact(quantity, liquidity)
        time_premium = self._time_decay(timestamp)
        raw = impact + volatility * 0.1 + time_premium
        return min(0.005, max(0.0001, raw))

    def _get_liquidity(self, symbol: str) -> float:
        return 1_000_000_000.0

    def _get_atr(self, symbol: str) -> float:
        return 0.02

    def _market_impact(self, quantity: int, liquidity: float) -> float:
        ratio = quantity * 100 * 10 / max(liquidity, 1)
        return min(0.003, ratio * 0.01)

    def _time_decay(self, timestamp: datetime) -> float:
        minute = timestamp.hour * 60 + timestamp.minute
        if 570 <= minute <= 600 or 870 <= minute <= 900:
            return 0.0005
        return 0.0
