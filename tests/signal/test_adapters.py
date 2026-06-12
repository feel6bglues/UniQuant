"""信号适配器测试"""
import datetime
from uniquant.signal.adapters import NTFAdapter


class TestNTFAdapter:
    def _adapt(self, side: str, intensity: float = 0.5):
        adapter = NTFAdapter()
        return adapter.adapt(
            {"ntf_side": side, "ntf_intensity": intensity, "price": 10.0},
            "000001.SZ",
            timestamp=datetime.datetime(2024, 6, 1),
        )

    def test_support_returns_hold(self):
        """SUPPORT + 高强度 → HOLD (不自动 BUY)"""
        sig = self._adapt("SUPPORT", 0.8)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_resistance_high_intensity_sells(self):
        """RESISTANCE + 高强度 → SELL"""
        sig = self._adapt("RESISTANCE", 0.8)
        assert sig is not None
        assert sig.action == "SELL"

    def test_resistance_low_intensity_skips(self):
        """RESISTANCE + 低强度 → None (跳过)"""
        sig = self._adapt("RESISTANCE", 0.3)
        assert sig is None

    def test_none_returns_none(self):
        """NONE → None"""
        sig = self._adapt("NONE")
        assert sig is None

    def test_unknown_side_returns_none(self):
        """未知 side → None"""
        sig = self._adapt("LONG")
        assert sig is None

    def test_support_confidence_scaled(self):
        """SUPPORT confidence = intensity * 0.5"""
        sig = self._adapt("SUPPORT", 0.6)
        assert sig is not None
        assert sig.confidence == 0.3  # 0.6 * 0.5

    def test_resistance_confidence_capped(self):
        """RESISTANCE confidence = min(intensity, 0.9)"""
        sig = self._adapt("RESISTANCE", 0.95)
        assert sig is not None
        assert sig.confidence == 0.9
