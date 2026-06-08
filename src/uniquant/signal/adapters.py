"""
信号适配器层 — Brain 引擎输出 → TradingSignal 标准化桥梁
=========================================================

职责:
  1. 将各 Brain 引擎的 Dict[str, Any] 输出转换为强类型 TradingSignal
  2. 从 AnalysisService 的 data_pack 中自动收集所有信号
  3. 消除两套并行决策体系的断裂点

设计原则:
  - 每个 Brain 引擎对应一个 Adapter 实现
  - Adapter 不做策略判断, 只做数据形态转换
  - 所有 Adapter 通过 TradingSignalFactory 统一调度
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..shared.interfaces import TradingSignal
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# 适配器基类
# ══════════════════════════════════════════════════════════════

class EngineAdapter(ABC):
    """Brain 引擎输出 → TradingSignal 适配器基类"""

    @abstractmethod
    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        """将引擎原始输出转换为标准 TradingSignal

        Args:
            raw_output: 引擎输出的 Dict
            symbol: 证券代码
            timestamp: 信号时间戳
            default_shares: 默认股数 (当引擎未指定时)

        Returns:
            TradingSignal, 或 None (如果输出不构成有效信号)
        """
        ...


# ══════════════════════════════════════════════════════════════
# LPPL 引擎适配器
# ══════════════════════════════════════════════════════════════

class LPPLAdapter(EngineAdapter):
    """LPPL 泡沫检测引擎输出适配器

    输入 keys: risk_level, confidence, bubble_confidence
    输出: BUY (Safe+高置信度) / SELL (Danger) / HOLD (Warning)
    """

    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        risk = raw_output.get("risk_level", raw_output.get("risk", "Safe"))
        confidence = float(
            raw_output.get("confidence", raw_output.get("bubble_confidence", 0.0))
        )

        if confidence < 0.05:
            return None

        if risk == "Danger":
            action = "SELL"
        elif risk == "Warning":
            action = "HOLD"
        else:
            action = "HOLD"

        return TradingSignal(
            action=action,
            reason=f"LPPL risk={risk} conf={confidence:.2f}",
            confidence=confidence,
            shares=default_shares if action == "SELL" else 0,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
        )


# ══════════════════════════════════════════════════════════════
# CZSC 引擎适配器
# ══════════════════════════════════════════════════════════════

class CZSCAdapter(EngineAdapter):
    """缠论 (CZSC) 引擎输出适配器

    输入 keys: is_3rd_buy, bi_count
    输出: BUY (三买成立) / HOLD
    """

    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        is_3rd_buy = raw_output.get("is_3rd_buy", False)
        bi_count = int(raw_output.get("bi_count", 0))

        if not is_3rd_buy and bi_count == 0:
            return None

        confidence = min(0.5 + bi_count * 0.05, 0.9) if is_3rd_buy else 0.3

        return TradingSignal(
            action="BUY" if is_3rd_buy else "HOLD",
            reason=f"CZSC 3rd_buy={is_3rd_buy} bi_count={bi_count}",
            confidence=confidence,
            shares=default_shares if is_3rd_buy else 0,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
        )


# ══════════════════════════════════════════════════════════════
# Wyckoff 引擎适配器
# ══════════════════════════════════════════════════════════════

class WyckoffAdapter(EngineAdapter):
    """Wyckoff 引擎输出适配器

    输入 keys: wyckoff_phase, wyckoff_confidence, wyckoff_spring, wyckoff_utad
    输出: BUY (accumulation+spring) / SELL (distribution+utad) / HOLD
    """

    _BULLISH_PHASES = {"accumulation"}
    _BEARISH_PHASES = {"distribution"}

    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        phase = raw_output.get(
            "wyckoff_phase", raw_output.get("phase", "unknown")
        )
        confidence = float(
            raw_output.get(
                "wyckoff_confidence", raw_output.get("confidence", 0.0)
            )
        )
        spring = raw_output.get("wyckoff_spring", False)
        utad = raw_output.get("wyckoff_utad", False)

        if phase == "unknown" or confidence < 0.3:
            return None

        if spring or phase in self._BULLISH_PHASES:
            action = "BUY"
        elif utad or phase in self._BEARISH_PHASES:
            action = "SELL"
        else:
            action = "HOLD"

        return TradingSignal(
            action=action,
            reason=f"Wyckoff phase={phase} spring={spring} utad={utad}",
            confidence=confidence,
            shares=default_shares if action != "HOLD" else 0,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
        )


# ══════════════════════════════════════════════════════════════
# FSM/DecisionBrain 引擎适配器
# ══════════════════════════════════════════════════════════════

class FSMAdapter(EngineAdapter):
    """FSM/DecisionBrain 引擎输出适配器

    输入 keys: action, final_decision, shares, score
    输出: 直接映射 action
    """

    _ACTION_MAP = {
        "BUY": "BUY",
        "SELL": "SELL",
        "HOLD": "HOLD",
        "ADD": "BUY",
        "EXECUTE_BUY": "BUY",
        "EXECUTE_SELL": "SELL",
        "FORCE_WAIT": "HOLD",
        "FORCE_EXIT": "SELL",
        "CIRCUIT_BREAK": "HOLD",
        "STAY_CURRENT_STATE": "HOLD",
    }

    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        raw_action = raw_output.get(
            "final_decision", raw_output.get("action", "HOLD")
        )
        action = self._ACTION_MAP.get(raw_action, "HOLD")
        shares = int(raw_output.get("shares", default_shares if action == "BUY" else 0))
        confidence = float(raw_output.get("confidence", 0.5))

        return TradingSignal(
            action=action,
            reason=raw_output.get("reason", ""),
            confidence=confidence,
            shares=shares,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
        )


# ══════════════════════════════════════════════════════════════
# Regime 引擎适配器
# ══════════════════════════════════════════════════════════════

class RegimeAdapter(EngineAdapter):
    """市场状态 (Regime) 引擎输出适配器

    输入 keys: regime
    输出: SELL (FROZEN/STRESSED) / HOLD (NORMAL)
    """

    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        regime = raw_output.get("regime", "NORMAL")

        if regime == "FROZEN":
            action = "HOLD"
            reason = "市场冻结, 不交易"
        elif regime == "STRESSED":
            action = "HOLD"
            reason = "市场紧张, 谨慎观望"
        else:
            return None

        return TradingSignal(
            action=action,
            reason=reason,
            confidence=0.5,
            shares=0,
            symbol=symbol,
            timestamp=timestamp,
        )


# ══════════════════════════════════════════════════════════════
# 适配器注册表
# ══════════════════════════════════════════════════════════════

class AdapterRegistry:
    """引擎适配器注册表"""

    def __init__(self) -> None:
        self._adapters: Dict[str, EngineAdapter] = {}

    def register(self, engine_name: str, adapter: EngineAdapter) -> None:
        self._adapters[engine_name] = adapter

    def get(self, engine_name: str) -> Optional[EngineAdapter]:
        return self._adapters.get(engine_name)

    def list_engines(self) -> List[str]:
        return list(self._adapters.keys())


def create_default_registry() -> AdapterRegistry:
    """创建包含所有内置适配器的注册表"""
    registry = AdapterRegistry()
    registry.register("lppl", LPPLAdapter())
    registry.register("czsc", CZSCAdapter())
    registry.register("wyckoff", WyckoffAdapter())
    registry.register("fsm", FSMAdapter())
    registry.register("regime", RegimeAdapter())
    return registry


# ══════════════════════════════════════════════════════════════
# 信号收集器 — 从 data_pack 提取所有 TradingSignal
# ══════════════════════════════════════════════════════════════

class TradingSignalCollector:
    """从 AnalysisService 的 data_pack 中收集所有 TradingSignal

    使用方式:
        collector = TradingSignalCollector()
        signals = collector.collect(data_pack)
    """

    def __init__(self, registry: Optional[AdapterRegistry] = None) -> None:
        self._registry = registry or create_default_registry()

    def collect(
        self,
        data_pack: Dict[str, Any],
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> List[TradingSignal]:
        """从 data_pack 中收集所有信号

        Args:
            data_pack: AnalysisService._run_engine_analysis() 的输出
            timestamp: 信号时间戳
            default_shares: 默认股数

        Returns:
            标准化的 TradingSignal 列表
        """
        signals: List[TradingSignal] = []
        symbol = data_pack.get("symbol", "")

        # LPPL
        lppl_out = self._extract_lppl(data_pack)
        if lppl_out:
            adapter = self._registry.get("lppl")
            if adapter:
                s = adapter.adapt(lppl_out, symbol, timestamp, default_shares)
                if s:
                    signals.append(s)

        # CZSC
        czsc_out = self._extract_czsc(data_pack)
        if czsc_out:
            adapter = self._registry.get("czsc")
            if adapter:
                s = adapter.adapt(czsc_out, symbol, timestamp, default_shares)
                if s:
                    signals.append(s)

        # Wyckoff
        wyckoff_out = self._extract_wyckoff(data_pack)
        if wyckoff_out:
            adapter = self._registry.get("wyckoff")
            if adapter:
                s = adapter.adapt(wyckoff_out, symbol, timestamp, default_shares)
                if s:
                    signals.append(s)

        # FSM/DecisionBrain
        if "action" in data_pack or "final_decision" in data_pack:
            adapter = self._registry.get("fsm")
            if adapter:
                s = adapter.adapt(data_pack, symbol, timestamp, default_shares)
                if s:
                    signals.append(s)

        # Regime
        if "regime" in data_pack:
            adapter = self._registry.get("regime")
            if adapter:
                s = adapter.adapt(
                    {"regime": data_pack["regime"]},
                    symbol,
                    timestamp,
                    default_shares,
                )
                if s:
                    signals.append(s)

        return signals

    @staticmethod
    def _extract_lppl(data_pack: Dict[str, Any]) -> Dict[str, Any]:
        if "risk" not in data_pack and "bubble_confidence" not in data_pack:
            return {}
        return {
            "risk_level": data_pack.get("risk", "Safe"),
            "confidence": data_pack.get("bubble_confidence", 0.0),
            "price": data_pack.get("price", 0.0),
        }

    @staticmethod
    def _extract_czsc(data_pack: Dict[str, Any]) -> Dict[str, Any]:
        if "is_3rd_buy" not in data_pack and "bi_count" not in data_pack:
            return {}
        return {
            "is_3rd_buy": data_pack.get("is_3rd_buy", False),
            "bi_count": data_pack.get("bi_count", 0),
            "price": data_pack.get("price", 0.0),
        }

    @staticmethod
    def _extract_wyckoff(data_pack: Dict[str, Any]) -> Dict[str, Any]:
        if "wyckoff_phase" not in data_pack:
            return {}
        return {
            "wyckoff_phase": data_pack.get("wyckoff_phase", "unknown"),
            "wyckoff_confidence": data_pack.get("wyckoff_confidence", 0.0),
            "wyckoff_spring": data_pack.get("wyckoff_spring", False),
            "wyckoff_utad": data_pack.get("wyckoff_utad", False),
            "price": data_pack.get("price", 0.0),
        }
