"""信号适配器测试"""
import datetime
from typing import Any, Dict, Optional

from uniquant.signal.adapters import (
    AdapterRegistry,
    AlphaScoreAdapter,
    CZSCAdapter,
    FSMAdapter,
    LPPLAdapter,
    MAStatusAdapter,
    NTFAdapter,
    RegimeAdapter,
    TradingSignalCollector,
    WyckoffAdapter,
)
from uniquant.shared.interfaces import TradingSignal


class TestLPPLAdapter:
    def _adapt(
        self, risk: str = "Safe", confidence: float = 0.0, **kwargs
    ) -> Optional[TradingSignal]:
        adapter = LPPLAdapter()
        raw: Dict[str, Any] = {"risk_level": risk, "confidence": confidence, "price": 10.0}
        raw.update(kwargs)
        return adapter.adapt(raw, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))

    def test_danger_high_conf_sells(self):
        sig = self._adapt("Danger", 0.8)
        assert sig is not None
        assert sig.action == "SELL"

    def test_warning_returns_hold(self):
        sig = self._adapt("Warning", 0.6)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_safe_returns_hold(self):
        sig = self._adapt("Safe", 0.5)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_confidence_below_threshold_returns_none(self):
        sig = self._adapt("Danger", 0.04)
        assert sig is None

    def test_empty_dict_returns_none(self):
        adapter = LPPLAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_uses_risk_fallback_key(self):
        sig = LPPLAdapter().adapt(
            {"risk": "Danger", "bubble_confidence": 0.7, "price": 10.0},
            "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )
        assert sig is not None
        assert sig.action == "SELL"

    def test_metadata_contains_r_squared(self):
        sig = self._adapt("Danger", 0.7, r_squared=0.92, out_of_sample_r_squared=0.85)
        assert sig is not None
        assert sig.metadata["r_squared"] == 0.92
        assert sig.metadata["out_of_sample_r_squared"] == 0.85

    def test_never_returns_buy(self):
        for risk in ("Danger", "Warning", "Safe"):
            sig = self._adapt(risk, 0.7)
            assert sig is not None
            assert sig.action != "BUY", f"LPPL risk={risk} should not produce BUY"

    def test_danger_uppercase_is_hold(self):
        sig = self._adapt("DANGER", 0.7)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_high_risk_level_is_hold(self):
        sig = self._adapt("HIGH", 0.7)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_confidence_at_boundary_returns_signal(self):
        sig = self._adapt("Danger", 0.05)
        assert sig is not None

    def test_confidence_just_below_boundary_returns_none(self):
        sig = self._adapt("Danger", 0.049)
        assert sig is None


class TestCZSCAdapter:
    def _adapt(
        self, is_3rd_buy: bool = False, bi_count: int = 0, **kwargs
    ) -> Optional[TradingSignal]:
        adapter = CZSCAdapter()
        raw: Dict[str, Any] = {"is_3rd_buy": is_3rd_buy, "bi_count": bi_count, "price": 10.0}
        raw.update(kwargs)
        return adapter.adapt(raw, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))

    def test_third_buy_returns_buy(self):
        sig = self._adapt(True, 5)
        assert sig is not None
        assert sig.action == "BUY"

    def test_no_third_buy_zero_bi_returns_none(self):
        sig = self._adapt(False, 0)
        assert sig is None

    def test_no_third_buy_with_bi_returns_hold(self):
        sig = self._adapt(False, 3)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_confidence_scaled_with_bi_count(self):
        sig = self._adapt(True, 10)
        assert sig is not None
        assert sig.confidence == 0.9

    def test_empty_dict_returns_none(self):
        adapter = CZSCAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_default_shares_on_buy(self):
        sig = self._adapt(True, 4)
        assert sig is not None
        assert sig.shares == 100

    def test_zero_shares_on_hold(self):
        sig = self._adapt(False, 2)
        assert sig is not None
        assert sig.shares == 0


class TestWyckoffAdapter:
    def _adapt(
        self, phase: str = "unknown", confidence: float = 0.0, spring: bool = False, utad: bool = False, **kwargs
    ) -> Optional[TradingSignal]:
        adapter = WyckoffAdapter()
        raw: Dict[str, Any] = {
            "wyckoff_phase": phase, "wyckoff_confidence": confidence,
            "wyckoff_spring": spring, "wyckoff_utad": utad, "price": 10.0,
        }
        raw.update(kwargs)
        return adapter.adapt(raw, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))

    def test_accumulation_high_conf_returns_buy(self):
        sig = self._adapt("accumulation", 0.7)
        assert sig is not None
        assert sig.action == "BUY"

    def test_distribution_high_conf_returns_sell(self):
        sig = self._adapt("distribution", 0.7)
        assert sig is not None
        assert sig.action == "SELL"

    def test_unknown_phase_returns_none(self):
        sig = self._adapt("unknown", 0.5)
        assert sig is None

    def test_low_confidence_returns_none(self):
        sig = self._adapt("accumulation", 0.2)
        assert sig is None

    def test_spring_triggers_buy(self):
        sig = self._adapt("markup", 0.6, spring=True)
        assert sig is not None
        assert sig.action == "BUY"

    def test_utad_triggers_sell(self):
        sig = self._adapt("markup", 0.6, utad=True)
        assert sig is not None
        assert sig.action == "SELL"

    def test_phase_fallback_key(self):
        sig = WyckoffAdapter().adapt(
            {"phase": "accumulation", "confidence": 0.7, "price": 10.0},
            "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )
        assert sig is not None
        assert sig.action == "BUY"

    def test_empty_dict_returns_none(self):
        adapter = WyckoffAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_markup_phase_returns_hold(self):
        sig = self._adapt("markup", 0.6)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_markdown_phase_returns_hold(self):
        sig = self._adapt("markdown", 0.6)
        assert sig is not None
        assert sig.action == "HOLD"

    def test_markup_with_spring_returns_buy(self):
        sig = self._adapt("markup", 0.6, spring=True)
        assert sig is not None
        assert sig.action == "BUY"

    def test_markdown_with_utad_returns_sell(self):
        sig = self._adapt("markdown", 0.6, utad=True)
        assert sig is not None
        assert sig.action == "SELL"

    def test_confidence_zero_returns_none(self):
        sig = self._adapt("accumulation", 0.0)
        assert sig is None


class TestFSMAdapter:
    def _adapt(
        self, action: str = "HOLD", shares: int = 0, confidence: float = 0.5, **kwargs
    ) -> Optional[TradingSignal]:
        adapter = FSMAdapter()
        raw: Dict[str, Any] = {"action": action, "shares": shares, "confidence": confidence, "price": 10.0}
        raw.update(kwargs)
        return adapter.adapt(raw, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))

    def test_buy_action(self):
        sig = self._adapt("BUY", 100)
        assert sig is not None
        assert sig.action == "BUY"

    def test_sell_action(self):
        sig = self._adapt("SELL")
        assert sig is not None
        assert sig.action == "SELL"

    def test_hold_action(self):
        sig = self._adapt("HOLD")
        assert sig is not None
        assert sig.action == "HOLD"

    def test_add_mapped_to_buy(self):
        sig = self._adapt("ADD", 100)
        assert sig.action == "BUY"

    def test_force_exit_mapped_to_sell(self):
        sig = self._adapt("FORCE_EXIT")
        assert sig.action == "SELL"

    def test_circuit_break_mapped_to_hold(self):
        sig = self._adapt("CIRCUIT_BREAK")
        assert sig.action == "HOLD"

    def test_final_decision_overrides_action(self):
        sig = FSMAdapter().adapt(
            {"final_decision": "SELL", "action": "BUY", "price": 10.0},
            "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )
        assert sig is not None
        assert sig.action == "SELL"

    def test_price_in_signal(self):
        sig = self._adapt("BUY", 100, price=15.5)
        assert sig is not None
        assert sig.price == 15.5

    def test_empty_dict_defaults_to_hold(self):
        sig = FSMAdapter().adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is not None
        assert sig.action == "HOLD"


class TestRegimeAdapter:
    def _adapt(self, regime: str = "NORMAL") -> Optional[TradingSignal]:
        adapter = RegimeAdapter()
        return adapter.adapt(
            {"regime": regime}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )

    def test_frozen_returns_hold(self):
        sig = self._adapt("FROZEN")
        assert sig is not None
        assert sig.action == "HOLD"

    def test_stressed_returns_hold(self):
        sig = self._adapt("STRESSED")
        assert sig is not None
        assert sig.action == "HOLD"

    def test_normal_returns_none(self):
        sig = self._adapt("NORMAL")
        assert sig is None

    def test_empty_dict_returns_none(self):
        adapter = RegimeAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_unknown_regime_returns_none(self):
        sig = self._adapt("UNKNOWN")
        assert sig is None

    def test_frozen_has_zero_shares(self):
        sig = self._adapt("FROZEN")
        assert sig is not None
        assert sig.shares == 0


class TestAlphaScoreAdapter:
    def _adapt(self, score: float = 0.5) -> Optional[TradingSignal]:
        adapter = AlphaScoreAdapter()
        return adapter.adapt(
            {"alpha_score": score, "price": 10.0}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )

    def test_high_score_returns_buy(self):
        sig = self._adapt(0.8)
        assert sig is not None
        assert sig.action == "BUY"

    def test_low_score_returns_sell(self):
        sig = self._adapt(0.2)
        assert sig is not None
        assert sig.action == "SELL"

    def test_mid_score_returns_none(self):
        sig = self._adapt(0.45)
        assert sig is None

    def test_empty_dict_returns_none(self):
        adapter = AlphaScoreAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_confidence_equals_abs_diff_from_mid(self):
        sig = self._adapt(0.9)
        assert sig is not None
        assert sig.confidence == 0.8

    def test_buy_sets_default_shares(self):
        sig = self._adapt(0.9)
        assert sig is not None
        assert sig.shares == 100

    def test_sell_sets_default_shares(self):
        sig = self._adapt(0.1)
        assert sig is not None
        assert sig.shares == 100

    def test_boundary_score_06_returns_buy(self):
        sig = self._adapt(0.61)
        assert sig is not None
        assert sig.action == "BUY"

    def test_boundary_score_03_returns_none(self):
        sig = self._adapt(0.3)
        assert sig is None

    def test_boundary_score_029_returns_sell(self):
        sig = self._adapt(0.29)
        assert sig is not None
        assert sig.action == "SELL"

    def test_zero_score_returns_none(self):
        sig = self._adapt(0.0)
        assert sig is None

    def test_exact_mid_score_five_returns_none(self):
        sig = self._adapt(0.5)
        assert sig is None


class TestMAStatusAdapter:
    def _adapt(self, ma_status: str = "") -> Optional[TradingSignal]:
        adapter = MAStatusAdapter()
        return adapter.adapt(
            {"ma_status": ma_status, "price": 10.0}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1),
        )

    def test_ma20_gt_ma60_returns_buy(self):
        sig = self._adapt("MA20 > MA60")
        assert sig is not None
        assert sig.action == "BUY"

    def test_ma20_lte_ma60_returns_sell(self):
        sig = self._adapt("MA20 <= MA60")
        assert sig is not None
        assert sig.action == "SELL"

    def test_empty_string_returns_none(self):
        sig = self._adapt("")
        assert sig is None

    def test_unknown_status_returns_none(self):
        sig = self._adapt("unknown")
        assert sig is None

    def test_empty_dict_returns_none(self):
        adapter = MAStatusAdapter()
        sig = adapter.adapt({}, "000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        assert sig is None

    def test_buy_sets_default_shares(self):
        sig = self._adapt("MA20 > MA60")
        assert sig is not None
        assert sig.shares == 100

    def test_sell_sets_default_shares(self):
        sig = self._adapt("MA20 <= MA60")
        assert sig is not None
        assert sig.shares == 100

    def test_confidence_is_03(self):
        sig = self._adapt("MA20 > MA60")
        assert sig is not None
        assert sig.confidence == 0.3


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


class TestAdapterRegistryDiscover:
    def test_discover_finds_default_adapters(self):
        registry = AdapterRegistry.discover()
        assert len(registry.list_engines()) >= 7

    def test_discover_returns_valid_registry(self):
        registry = AdapterRegistry.discover()
        for name in ["lppl", "czsc", "fsm", "regime"]:
            adapter = registry.get(name)
            assert adapter is not None, f"{name} adapter should be discoverable"

    def test_discover_handles_bad_module(self):
        registry = AdapterRegistry.discover("nonexistent.module.path")
        assert len(registry.list_engines()) == 0


class TestTradingSignalCollectorEvent:
    def test_collect_with_event_bus(self):
        from uniquant.shared.event_bus import EventBus

        received = []

        def handler(event):
            received.append(event)

        bus = EventBus()
        bus.subscribe("signal.generated", handler)
        collector = TradingSignalCollector(event_bus=bus)
        data_pack = {
            "symbol": "000001.SZ",
            "alpha_score": 0.7,
            "price": 10.0,
        }
        signals = collector.collect(data_pack)
        assert len(signals) >= 1
        assert len(received) >= 1
        assert received[0].topic == "signal.generated"
        assert received[0].payload["signal"]["action"] == "BUY"

    def test_collect_without_event_bus(self):
        collector = TradingSignalCollector()
        data_pack = {
            "symbol": "000001.SZ",
            "alpha_score": 0.7,
            "price": 10.0,
        }
        signals = collector.collect(data_pack)
        assert len(signals) >= 1
        assert signals[0].action == "BUY"
