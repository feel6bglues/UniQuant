"""
实时行情桥接引擎

为日后支持分时级别的盘中探测铺平道路。
提供 WebSocket 轻量级桥接类，支持实时行情订阅和推送。

使用方法:
    bridge = RealtimeBridge()
    bridge.subscribe("600000.SH", on_tick)
    bridge.start()
"""

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ...shared.logger_factory import get_logger

logger = get_logger("RealtimeBridge")


class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class TickData:
    """Tick 数据结构"""
    symbol: str
    timestamp: datetime
    price: float
    volume: int
    turnover: float
    bid_price: float = 0.0
    bid_volume: int = 0
    ask_price: float = 0.0
    ask_volume: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "volume": self.volume,
            "turnover": self.turnover,
            "bid_price": self.bid_price,
            "bid_volume": self.bid_volume,
            "ask_price": self.ask_price,
            "ask_volume": self.ask_volume,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "pre_close": self.pre_close,
            "extra": self.extra,
        }


@dataclass
class KlineData:
    """K线数据结构"""
    symbol: str
    timestamp: datetime
    interval: str  # 1m, 5m, 15m, 30m, 60m, D
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "interval": self.interval,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "turnover": self.turnover,
        }


class DataSourceAdapter(ABC):
    """数据源适配器基类"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: List[str]) -> bool:
        """订阅股票"""
        pass
    
    @abstractmethod
    async def unsubscribe(self, symbols: List[str]) -> bool:
        """取消订阅"""
        pass
    
    @abstractmethod
    async def get_tick(self, symbol: str) -> Optional[TickData]:
        """获取最新 Tick"""
        pass


class MockDataSource(DataSourceAdapter):
    """模拟数据源 (用于测试)"""
    
    def __init__(self):
        self._connected = False
        self._subscribed: List[str] = []
        self._tick_cache: Dict[str, TickData] = {}
    
    async def connect(self) -> bool:
        self._connected = True
        logger.info("MockDataSource connected")
        return True
    
    async def disconnect(self) -> None:
        self._connected = False
        logger.info("MockDataSource disconnected")
    
    async def subscribe(self, symbols: List[str]) -> bool:
        self._subscribed.extend(symbols)
        logger.info(f"MockDataSource subscribed: {symbols}")
        return True
    
    async def unsubscribe(self, symbols: List[str]) -> bool:
        for s in symbols:
            if s in self._subscribed:
                self._subscribed.remove(s)
        return True
    
    async def get_tick(self, symbol: str) -> Optional[TickData]:
        if symbol not in self._subscribed:
            return None
        
        import random
        return TickData(
            symbol=symbol,
            timestamp=datetime.now(),
            price=10.0 + random.random(),
            volume=random.randint(1000, 10000),
            turnover=random.random() * 100000,
        )


class RealtimeBridge:
    """
    实时行情桥接引擎
    
    支持:
    - 多数据源适配
    - WebSocket 连接管理
    - 订阅/取消订阅管理
    - 回调函数注册
    - 自动重连
    """
    
    def __init__(
        self,
        data_source: Optional[DataSourceAdapter] = None,
        auto_reconnect: bool = True,
        reconnect_interval: float = 5.0,
    ):
        self.data_source = data_source or MockDataSource()
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        
        self._state = ConnectionState.DISCONNECTED
        self._subscribed_symbols: Dict[str, List[Callable]] = {}
        self._tick_callbacks: List[Callable[[TickData], None]] = []
        self._kline_callbacks: List[Callable[[KlineData], None]] = []
        self._error_callbacks: List[Callable[[Exception], None]] = []
        
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        
        logger.info("RealtimeBridge initialized")
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED
    
    def on_tick(self, callback: Callable[[TickData], None]) -> None:
        """注册 Tick 回调"""
        self._tick_callbacks.append(callback)
    
    def on_kline(self, callback: Callable[[KlineData], None]) -> None:
        """注册 K线回调"""
        self._kline_callbacks.append(callback)
    
    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """注册错误回调"""
        self._error_callbacks.append(callback)
    
    def subscribe(
        self,
        symbol: str,
        callback: Optional[Callable[[TickData], None]] = None
    ) -> None:
        """
        订阅股票行情
        
        Args:
            symbol: 股票代码
            callback: 可选的回调函数
        """
        if symbol not in self._subscribed_symbols:
            self._subscribed_symbols[symbol] = []
        
        if callback:
            self._subscribed_symbols[symbol].append(callback)
        
        if self._event_loop and self.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.data_source.subscribe([symbol]),
                self._event_loop
            )
        
        logger.info(f"Subscribed to {symbol}")
    
    def unsubscribe(self, symbol: str) -> None:
        """取消订阅"""
        if symbol in self._subscribed_symbols:
            del self._subscribed_symbols[symbol]
        
        if self._event_loop and self.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.data_source.unsubscribe([symbol]),
                self._event_loop
            )
        
        logger.info(f"Unsubscribed from {symbol}")
    
    async def _connect_loop(self) -> None:
        """连接循环"""
        while self._running:
            try:
                if not self.is_connected:
                    self._state = ConnectionState.CONNECTING
                    success = await self.data_source.connect()
                    
                    if success:
                        self._state = ConnectionState.CONNECTED
                        logger.info("RealtimeBridge connected")
                        
                        symbols = list(self._subscribed_symbols.keys())
                        if symbols:
                            await self.data_source.subscribe(symbols)
                    else:
                        self._state = ConnectionState.ERROR
                        if not self.auto_reconnect:
                            break
                        await asyncio.sleep(self.reconnect_interval)
                        continue
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Connection error: {e}")
                self._state = ConnectionState.ERROR
                
                for callback in self._error_callbacks:
                    try:
                        callback(e)
                    except Exception:
                        pass
                
                if self.auto_reconnect:
                    self._state = ConnectionState.RECONNECTING
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    break
    
    async def _tick_loop(self) -> None:
        """Tick 数据循环"""
        while self._running and self.is_connected:
            try:
                for symbol in list(self._subscribed_symbols.keys()):
                    tick = await self.data_source.get_tick(symbol)
                    
                    if tick:
                        for callback in self._tick_callbacks:
                            try:
                                callback(tick)
                            except Exception as e:
                                logger.error(f"Tick callback error: {e}")
                        
                        for callback in self._subscribed_symbols.get(symbol, []):
                            try:
                                callback(tick)
                            except Exception as e:
                                logger.error(f"Symbol callback error: {e}")
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Tick loop error: {e}")
                await asyncio.sleep(1)
    
    async def _run_async(self) -> None:
        """异步运行"""
        self._running = True
        
        connect_task = asyncio.create_task(self._connect_loop())
        tick_task = asyncio.create_task(self._tick_loop())
        
        await asyncio.gather(connect_task, tick_task)
    
    def _run_in_thread(self) -> None:
        """在线程中运行"""
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        
        try:
            self._event_loop.run_until_complete(self._run_async())
        finally:
            self._event_loop.close()
    
    def start(self) -> None:
        """启动桥接引擎"""
        if self._thread and self._thread.is_alive():
            logger.warning("RealtimeBridge is already running")
            return
        
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()
        
        logger.info("RealtimeBridge started")
    
    def stop(self) -> None:
        """停止桥接引擎"""
        self._running = False
        
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self.data_source.disconnect(),
                self._event_loop
            )
        
        if self._thread:
            self._thread.join(timeout=5.0)
        
        self._state = ConnectionState.DISCONNECTED
        logger.info("RealtimeBridge stopped")
    
    def get_subscribed_symbols(self) -> List[str]:
        """获取已订阅的股票列表"""
        return list(self._subscribed_symbols.keys())


class RealtimeBridgeBuilder:
    """RealtimeBridge 构建器"""
    
    def __init__(self):
        self._data_source: Optional[DataSourceAdapter] = None
        self._auto_reconnect: bool = True
        self._reconnect_interval: float = 5.0
        self._tick_callbacks: List[Callable[[TickData], None]] = []
        self._kline_callbacks: List[Callable[[KlineData], None]] = []
    
    def with_data_source(self, source: DataSourceAdapter) -> "RealtimeBridgeBuilder":
        self._data_source = source
        return self
    
    def with_auto_reconnect(
        self,
        enabled: bool = True,
        interval: float = 5.0
    ) -> "RealtimeBridgeBuilder":
        self._auto_reconnect = enabled
        self._reconnect_interval = interval
        return self
    
    def on_tick(self, callback: Callable[[TickData], None]) -> "RealtimeBridgeBuilder":
        self._tick_callbacks.append(callback)
        return self
    
    def on_kline(self, callback: Callable[[KlineData], None]) -> "RealtimeBridgeBuilder":
        self._kline_callbacks.append(callback)
        return self
    
    def build(self) -> RealtimeBridge:
        bridge = RealtimeBridge(
            data_source=self._data_source,
            auto_reconnect=self._auto_reconnect,
            reconnect_interval=self._reconnect_interval,
        )
        
        for callback in self._tick_callbacks:
            bridge.on_tick(callback)
        
        for callback in self._kline_callbacks:
            bridge.on_kline(callback)
        
        return bridge
