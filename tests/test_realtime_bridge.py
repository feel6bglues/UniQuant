"""
RealtimeBridge 单元测试
"""

import pytest
import asyncio
import time

from uniquant.data.sources.realtime_bridge import (
    RealtimeBridge,
    RealtimeBridgeBuilder,
    MockDataSource,
    TickData,
    KlineData,
    ConnectionState,
)


class TestTickData:
    """TickData 测试"""
    
    def test_tick_data_creation(self):
        """测试 Tick 数据创建"""
        from datetime import datetime
        
        tick = TickData(
            symbol="600000.SH",
            timestamp=datetime.now(),
            price=10.5,
            volume=10000,
            turnover=105000.0,
        )
        
        assert tick.symbol == "600000.SH"
        assert tick.price == 10.5
        assert tick.volume == 10000
    
    def test_tick_data_to_dict(self):
        """测试 Tick 数据转字典"""
        from datetime import datetime
        
        tick = TickData(
            symbol="600000.SH",
            timestamp=datetime(2024, 1, 1, 9, 30),
            price=10.5,
            volume=10000,
            turnover=105000.0,
        )
        
        d = tick.to_dict()
        assert d["symbol"] == "600000.SH"
        assert d["price"] == 10.5
        assert "timestamp" in d


class TestKlineData:
    """KlineData 测试"""
    
    def test_kline_data_creation(self):
        """测试 K线数据创建"""
        from datetime import datetime
        
        kline = KlineData(
            symbol="600000.SH",
            timestamp=datetime.now(),
            interval="1m",
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.3,
            volume=50000,
            turnover=515000.0,
        )
        
        assert kline.symbol == "600000.SH"
        assert kline.interval == "1m"
        assert kline.high >= kline.low
    
    def test_kline_data_to_dict(self):
        """测试 K线数据转字典"""
        from datetime import datetime
        
        kline = KlineData(
            symbol="600000.SH",
            timestamp=datetime(2024, 1, 1, 9, 30),
            interval="5m",
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.3,
            volume=50000,
            turnover=515000.0,
        )
        
        d = kline.to_dict()
        assert d["symbol"] == "600000.SH"
        assert d["interval"] == "5m"


class TestMockDataSource:
    """MockDataSource 测试"""
    
    @pytest.fixture
    def source(self):
        return MockDataSource()
    
    def test_connect(self, source):
        """测试连接"""
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(source.connect())
        loop.close()
        assert result is True
    
    def test_subscribe(self, source):
        """测试订阅"""
        loop = asyncio.new_event_loop()
        loop.run_until_complete(source.connect())
        result = loop.run_until_complete(source.subscribe(["600000.SH"]))
        loop.close()
        assert result is True
    
    def test_get_tick(self, source):
        """测试获取 Tick"""
        loop = asyncio.new_event_loop()
        loop.run_until_complete(source.connect())
        loop.run_until_complete(source.subscribe(["600000.SH"]))
        
        tick = loop.run_until_complete(source.get_tick("600000.SH"))
        loop.close()
        assert tick is not None
        assert tick.symbol == "600000.SH"


class TestRealtimeBridge:
    """RealtimeBridge 测试"""
    
    @pytest.fixture
    def bridge(self):
        return RealtimeBridge(data_source=MockDataSource())
    
    def test_bridge_creation(self, bridge):
        """测试桥接器创建"""
        assert bridge.state == ConnectionState.DISCONNECTED
        assert not bridge.is_connected
    
    def test_subscribe(self, bridge):
        """测试订阅"""
        bridge.subscribe("600000.SH")
        
        symbols = bridge.get_subscribed_symbols()
        assert "600000.SH" in symbols
    
    def test_unsubscribe(self, bridge):
        """测试取消订阅"""
        bridge.subscribe("600000.SH")
        bridge.unsubscribe("600000.SH")
        
        symbols = bridge.get_subscribed_symbols()
        assert "600000.SH" not in symbols
    
    def test_on_tick_callback(self, bridge):
        """测试 Tick 回调注册"""
        received = []
        
        def callback(tick):
            received.append(tick)
        
        bridge.on_tick(callback)
        assert callback in bridge._tick_callbacks
    
    def test_on_error_callback(self, bridge):
        """测试错误回调注册"""
        received = []
        
        def callback(error):
            received.append(error)
        
        bridge.on_error(callback)
        assert callback in bridge._error_callbacks
    
    def test_start_stop(self, bridge):
        """测试启动和停止"""
        bridge.start()
        
        time.sleep(1)
        
        assert bridge._thread is not None
        assert bridge._thread.is_alive()
        
        bridge.stop()
        
        time.sleep(0.5)
        
        assert bridge.state == ConnectionState.DISCONNECTED


class TestRealtimeBridgeBuilder:
    """RealtimeBridgeBuilder 测试"""
    
    def test_builder_default(self):
        """测试默认构建"""
        bridge = RealtimeBridgeBuilder().build()
        
        assert bridge is not None
        assert bridge.data_source is not None
    
    def test_builder_with_data_source(self):
        """测试自定义数据源"""
        source = MockDataSource()
        bridge = RealtimeBridgeBuilder().with_data_source(source).build()
        
        assert bridge.data_source is source
    
    def test_builder_with_callbacks(self):
        """测试回调函数"""
        ticks = []
        
        def on_tick(tick):
            ticks.append(tick)
        
        bridge = (
            RealtimeBridgeBuilder()
            .on_tick(on_tick)
            .build()
        )
        
        assert on_tick in bridge._tick_callbacks


class TestRealtimeBridgeIntegration:
    """集成测试"""
    
    def test_full_workflow(self):
        """测试完整工作流"""
        received_ticks = []
        
        def on_tick(tick):
            received_ticks.append(tick)
        
        bridge = (
            RealtimeBridgeBuilder()
            .with_auto_reconnect(True, 1.0)
            .on_tick(on_tick)
            .build()
        )
        
        bridge.subscribe("600000.SH")
        bridge.subscribe("000001.SZ")
        
        bridge.start()
        
        time.sleep(2)
        
        bridge.stop()
        
        assert len(bridge.get_subscribed_symbols()) == 2
