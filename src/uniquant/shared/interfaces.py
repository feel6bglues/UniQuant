from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
import enum
from enum import Enum

import pandas as pd


class MarketRegime(Enum):
    """市场状态枚举"""
    NORMAL = "NORMAL"
    STRESSED = "STRESSED"
    FROZEN = "FROZEN"
    UNKNOWN = "UNKNOWN"


class NtfSide(Enum):
    """国家队行为方向"""
    NONE = "NONE"
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class RegimeType(enum.Enum):
    """Unified regime type covering both liquidity and trend detectors."""
    # Trend regimes (from LPPL)
    STRONG_BULL = "strong_bull"
    WEAK_BULL = "weak_bull"
    RANGE = "range"
    WEAK_BEAR = "weak_bear"
    STRONG_BEAR = "strong_bear"
    # Liquidity regimes (from RegimeDetector)
    NORMAL = "normal"
    STRESSED = "stressed"
    FROZEN = "frozen"
    # Fallback
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CandidateSignal:
    """候选信号 — 引擎输出到仲裁器的类型化输入

    将 per-engine 的 Dict[str, Any] 输出转换为结构化字段，
    使 SignalArbitrator 可以基于置信度、方向和强度进行仲裁。
    """
    source: str
    action: str
    confidence: float
    direction: int
    strength: float
    price_target: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSignalContext:
    """
    市场信号上下文数据包
    
    用于 DecisionBrain.make_decision() 的类型化输入，
    替代无类型的 dict 参数，提供编译时类型检查。
    """
    regime: MarketRegime = MarketRegime.NORMAL
    risk: str = "Safe"
    bubble_confidence: float = 0.0
    ntf_side: NtfSide = NtfSide.NONE
    ntf_intensity: float = 0.0
    is_3rd_buy: bool = False
    bi_count: int = 0
    alpha_score: float = 0.0
    ma_status: Optional[str] = None
    price: float = 0.0
    pre_close: float = 0.0
    symbol: str = ""
    name: Optional[str] = None
    atr_stop: float = 0.0
    czsc_bottom: Optional[float] = None
    market: str = "CN"
    returns: Optional[pd.Series] = None
    lppl_days_to_tc: Optional[float] = None
    engine_status: Dict[str, str] = field(default_factory=dict)
    engine_errors: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketSignalContext":
        """从字典创建实例，兼容旧代码"""
        regime_str = data.get("regime", "NORMAL")
        regime = MarketRegime(regime_str) if regime_str in [r.value for r in MarketRegime] else MarketRegime.NORMAL
        
        ntf_str = data.get("ntf_side", "NONE")
        ntf_side = NtfSide(ntf_str) if ntf_str in [n.value for n in NtfSide] else NtfSide.NONE
        
        return cls(
            regime=regime,
            risk=data.get("risk", "Safe"),
            bubble_confidence=data.get("bubble_confidence", 0.0),
            ntf_side=ntf_side,
            ntf_intensity=data.get("ntf_intensity", 0.0),
            is_3rd_buy=data.get("is_3rd_buy", False),
            bi_count=data.get("bi_count", 0),
            alpha_score=data.get("alpha_score", 0.0),
            ma_status=data.get("ma_status"),
            price=data.get("price", 0.0),
            pre_close=data.get("pre_close", 0.0),
            symbol=data.get("symbol", ""),
            name=data.get("name"),
            atr_stop=data.get("atr_stop", 0.0),
            czsc_bottom=data.get("czsc_bottom"),
            market=data.get("market", "CN"),
            returns=data.get("returns"),
            lppl_days_to_tc=data.get("lppl_days_to_tc"),
            engine_status=data.get("engine_status", {}),
            engine_errors=data.get("engine_errors", {}),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，兼容旧代码"""
        return {
            "regime": self.regime.value,
            "risk": self.risk,
            "bubble_confidence": self.bubble_confidence,
            "ntf_side": self.ntf_side.value,
            "ntf_intensity": self.ntf_intensity,
            "is_3rd_buy": self.is_3rd_buy,
            "bi_count": self.bi_count,
            "alpha_score": self.alpha_score,
            "ma_status": self.ma_status,
            "price": self.price,
            "pre_close": self.pre_close,
            "symbol": self.symbol,
            "name": self.name,
            "atr_stop": self.atr_stop,
            "czsc_bottom": self.czsc_bottom,
            "market": self.market,
            "lppl_days_to_tc": self.lppl_days_to_tc,
            "engine_status": self.engine_status,
            "engine_errors": self.engine_errors,
        }


@dataclass
class TradingSignal:
    """
    Brain ↔ Hands 统一信号接口。
    
    所有 Brain 引擎输出和 BacktestEngine 输入均使用此格式，
    消除 action 值不匹配导致的信号丢失。
    """
    action: str  # "BUY" | "SELL" | "HOLD"
    reason: str = ""
    confidence: float = 0.0
    shares: int = 0
    symbol: str = ""
    price: float = 0.0
    timestamp: Optional[datetime.datetime] = field(default=None, repr=False)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 兼容旧接口：从 dict 构造
    @classmethod
    def from_dict(cls, data: dict) -> "TradingSignal":
        action = data.get("action", "HOLD")
        # 统一 action 映射
        action_map = {
            "EXECUTE_BUY": "BUY",
            "EXECUTE_SELL": "SELL",
            "ADD": "BUY",
            "FORCE_WAIT": "HOLD",
            "FORCE_EXIT": "SELL",
            "CIRCUIT_BREAK": "HOLD",
            "STAY_CURRENT_STATE": "HOLD",
        }
        action = action_map.get(action, action)
        ts = data.get("timestamp")
        if ts is not None and isinstance(ts, str):
            ts = datetime.datetime.fromisoformat(ts)
        return cls(
            action=action,
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.0),
            shares=data.get("shares", 0),
            symbol=data.get("symbol", ""),
            price=data.get("price", 0.0),
            timestamp=ts,
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        ts = self.timestamp
        if isinstance(ts, datetime.datetime):
            ts = ts.isoformat()
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "shares": self.shares,
            "symbol": self.symbol,
            "price": self.price,
            "timestamp": ts,
            "metadata": dict(self.metadata),
        }


@dataclass
class ResearchDataPack:
    """Brain 引擎分析输出的类型化数据包

    替代无类型的 Dict[str, Any] data_pack，提供编译时类型检查。
    """
    symbol: str
    stock_df: Optional[pd.DataFrame] = None
    index_df: Optional[pd.DataFrame] = None
    regime: Optional[RegimeOutput] = None
    lppl: Optional[LPPLOutput] = None
    ntf: Optional[NtfOutput] = None
    czsc: Optional[CZSCOutput] = None
    wyckoff: Optional[WyckoffOutput] = None
    alpha: Optional[AlphaOutput] = None
    factors: Optional[Dict[str, float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], symbol: str = "") -> "ResearchDataPack":
        return cls(
            symbol=symbol or data.get("symbol", ""),
            stock_df=data.get("stock"),
            index_df=data.get("index") or data.get("bench"),
            regime=data.get("regime"),
            lppl=data.get("lppl"),
            ntf=data.get("ntf"),
            czsc=data.get("czsc"),
            wyckoff=data.get("wyckoff"),
            alpha=data.get("alpha"),
            factors=data.get("factors"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "symbol": self.symbol,
            "stock": self.stock_df,
            "index": self.index_df,
            "bench": self.index_df,
            "regime": self.regime,
            "lppl": self.lppl,
            "ntf": self.ntf,
            "czsc": self.czsc,
            "wyckoff": self.wyckoff,
            "alpha": self.alpha,
            "factors": self.factors,
            "metadata": self.metadata,
        }
        return result


@dataclass
class DecisionOutput:
    """DecisionBrain 输出的类型化决策结果

    替代无类型的 Dict[str, Any] decision，提供编译时类型检查。
    """
    action: str = "HOLD"
    reason: str = ""
    confidence: float = 0.0
    shares: int = 0
    price: float = 0.0
    regime: str = "UNKNOWN"
    score: float = 0.0
    engine_status: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionOutput":
        return cls(
            action=data.get("action", "HOLD"),
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.0),
            shares=data.get("shares", 0),
            price=data.get("price", 0.0),
            regime=data.get("regime", "UNKNOWN"),
            score=data.get("score") or data.get("final_score", 0.0),
            engine_status=data.get("engine_status", {}),
            metadata=data.get("metadata", {}),
        )


# ── 引擎输出类型 ──

@dataclass
class RegimeOutput:
    regime: str = "UNKNOWN"
    entropy: float = 0.0
    turnover_z: float = 0.0
    is_safe: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "entropy": self.entropy,
            "turnover_z": self.turnover_z,
            "is_safe": self.is_safe,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegimeOutput":
        return cls(
            regime=str(data.get("regime", "UNKNOWN")),
            entropy=float(data.get("entropy", 0.0)),
            turnover_z=float(data.get("turnover_z", 0.0)),
            is_safe=bool(data.get("is_safe", True)),
        )


@dataclass
class LPPLOutput:
    risk_level: str = "Safe"
    confidence: float = 0.0
    days_to_tc: Optional[float] = None
    price: float = 0.0
    r_squared: float = 0.0
    """R² from calculator.fit() (3-param variable projection, L-BFGS-B).
    ⚠ NOT comparable with scan_all_windows() R² (7-param full cost)."""
    out_of_sample_r_squared: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "bubble_confidence": self.confidence,
            "lppl_days_to_tc": self.days_to_tc,
            "price": self.price,
            "r_squared": self.r_squared,
            "out_of_sample_r_squared": self.out_of_sample_r_squared,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LPPLOutput":
        return cls(
            risk_level=str(data.get("risk_level", "Safe")),
            confidence=float(data.get("bubble_confidence", data.get("confidence", 0.0))),
            days_to_tc=data.get("lppl_days_to_tc"),
            price=float(data.get("price", 0.0)),
            r_squared=float(data.get("r_squared", 0.0)),
            out_of_sample_r_squared=float(data.get("out_of_sample_r_squared", 0.0)),
        )


@dataclass
class CZSCOutput:
    is_3rd_buy: bool = False
    bi_count: int = 0
    price: float = 0.0
    bottom: Optional[float] = None
    trend: str = "未知"
    current_state: str = "NEUTRAL"
    recent_highs: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_3rd_buy": self.is_3rd_buy,
            "bi_count": self.bi_count,
            "price": self.price,
            "czsc_bottom": self.bottom,
            "trend": self.trend,
            "current_state": self.current_state,
            "recent_highs": self.recent_highs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CZSCOutput":
        return cls(
            is_3rd_buy=bool(data.get("is_3rd_buy", False)),
            bi_count=int(data.get("bi_count", 0)),
            price=float(data.get("price", 0.0)),
            bottom=data.get("czsc_bottom"),
            trend=str(data.get("trend", "未知")),
            current_state=str(data.get("current_state", "NEUTRAL")),
            recent_highs=data.get("recent_highs"),
        )


@dataclass
class NtfOutput:
    side: str = "NONE"
    intensity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"ntf_side": self.side, "ntf_intensity": self.intensity}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NtfOutput":
        return cls(
            side=str(data.get("ntf_side", "NONE")),
            intensity=float(data.get("ntf_intensity", 0.0)),
        )


@dataclass
class WyckoffOutput:
    phase: str = "unknown"
    confidence: float = 0.0
    spring: bool = False
    utad: bool = False
    price: float = 0.0
    rr_ratio: float = 0.0
    bypassed: bool = False
    pnf_phase_hint: str = "neutral"
    pnf_breakout: bool = False
    pnf_count_target: float = 0.0
    regime_phase: Optional[str] = None
    vshape_detected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wyckoff_phase": self.phase,
            "wyckoff_confidence": self.confidence,
            "wyckoff_spring": self.spring,
            "wyckoff_utad": self.utad,
            "price": self.price,
            "rr_ratio": self.rr_ratio,
            "bypassed": self.bypassed,
            "pnf_phase_hint": self.pnf_phase_hint,
            "pnf_breakout": self.pnf_breakout,
            "pnf_count_target": self.pnf_count_target,
            "regime_phase": self.regime_phase,
            "vshape_detected": self.vshape_detected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WyckoffOutput":
        return cls(
            phase=str(data.get("wyckoff_phase", "unknown")),
            confidence=float(data.get("wyckoff_confidence", 0.0)),
            spring=bool(data.get("wyckoff_spring", False)),
            utad=bool(data.get("wyckoff_utad", False)),
            price=float(data.get("price", 0.0)),
            rr_ratio=float(data.get("rr_ratio", 0.0)),
            bypassed=bool(data.get("bypassed", False)),
            pnf_phase_hint=str(data.get("pnf_phase_hint", "neutral")),
            pnf_breakout=bool(data.get("pnf_breakout", False)),
            pnf_count_target=float(data.get("pnf_count_target", 0.0)),
            regime_phase=data.get("regime_phase"),
            vshape_detected=bool(data.get("vshape_detected", False)),
        )


@dataclass
class AlphaOutput:
    score: float = 0.0
    factors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"alpha_score": self.score, "scores": self.factors}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlphaOutput":
        return cls(
            score=float(data.get("alpha_score", 0.0)),
            factors=dict(data.get("scores", {})),
        )


@runtime_checkable
class DataFetcherProtocol(Protocol):
    """
    Protocol calling for DataFetcher.
    Allows decoupling Brain components from the concrete DataFetcher implementation.
    """

    def fetch_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        period: str = "daily",
    ) -> pd.DataFrame:
        """
        Fetch historical data.
        """
        ...


@runtime_checkable
class RiskAssessmentProtocol(Protocol):
    """
    Protocol for risk assessment components.
    Allows decoupling Brain components from concrete risk assessment implementations.
    """

    def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate risk metrics based on returns data.

        Args:
            returns: DataFrame of returns data

        Returns:
            Dict[str, Any]: Risk metrics including risk level
        """
        ...


@runtime_checkable
class PositionSizerProtocol(Protocol):
    """
    Protocol for position sizing components.
    Allows decoupling Brain components from concrete position sizing implementations.
    """

    def calculate_shares(
        self,
        price: float,
        stop_loss: float,
        czsc_bottom: Any,
        market: str = "CN",
        symbol: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """
        Calculate position size based on various parameters.

        Args:
            price: Current price
            stop_loss: Stop loss level
            czsc_bottom: CZSC bottom information
            market: Market identifier
            symbol: Symbol identifier

        Returns:
            Dict[str, Any]: Position sizing information
        """
        ...


@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    """
    Protocol for analysis engines.
    Allows decoupling AnalysisService from concrete analysis implementations.
    """

    def analyze(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        """
        Analyze data and return results.

        Args:
            data: DataFrame with data to analyze
            **kwargs: Additional parameters for analysis

        Returns:
            Dict[str, Any]: Analysis results
        """
        ...


@runtime_checkable
class CalculationPluginProtocol(Protocol):
    """
    Protocol for calculation plugins.
    Allows dynamic addition of new calculation methods.
    """

    @property
    def name(self) -> str:
        """
        Plugin name
        """
        ...

    @property
    def version(self) -> str:
        """
        Plugin version
        """
        ...

    @property
    def description(self) -> str:
        """
        Plugin description
        """
        ...

    def calculate(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        """
        Perform calculation and return results.

        Args:
            data: DataFrame with data to calculate on
            **kwargs: Additional parameters for calculation

        Returns:
            Dict[str, Any]: Calculation results
        """
        ...


class CalculationRegistry:
    """
    Registry for calculation plugins.
    """

    def __init__(self):
        self._plugins: Dict[str, CalculationPluginProtocol] = {}

    def register(self, plugin: CalculationPluginProtocol) -> None:
        """
        Register a calculation plugin.

        Args:
            plugin: Plugin to register
        """
        self._plugins[plugin.name] = plugin

    def unregister(self, plugin_name: str) -> None:
        """
        Unregister a calculation plugin.

        Args:
            plugin_name: Name of plugin to unregister
        """
        if plugin_name in self._plugins:
            del self._plugins[plugin_name]

    def get(self, plugin_name: str) -> CalculationPluginProtocol:
        """
        Get a registered plugin by name.

        Args:
            plugin_name: Name of plugin to get

        Returns:
            CalculationPluginProtocol: Registered plugin

        Raises:
            KeyError: If plugin is not registered
        """
        return self._plugins[plugin_name]

    def list(self) -> List[str]:
        """
        List all registered plugins.

        Returns:
            List[str]: List of plugin names
        """
        return list(self._plugins.keys())

    def has(self, plugin_name: str) -> bool:
        """
        Check if a plugin is registered.

        Args:
            plugin_name: Name of plugin to check

        Returns:
            bool: True if plugin is registered, False otherwise
        """
        return plugin_name in self._plugins


# Create a global calculation registry
calculation_registry = CalculationRegistry()
