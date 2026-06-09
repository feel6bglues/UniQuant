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
