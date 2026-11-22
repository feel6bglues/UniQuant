"""services/bootstrap.py 单元测试 (轻量服务装配验证)。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from uniquant.services.bootstrap import (
    create_analysis_service,
    create_data_service,
    create_engine_factory,
    create_research_pipeline,
    create_signal_arbitrator,
    create_storage_manager,
    create_trading_signal_collector,
)


def test_bootstrap_instantiation_is_fast():
    t0 = time.perf_counter()
    storage = create_storage_manager()
    ds = create_data_service(storage_manager=storage)
    ef = create_engine_factory(data_service=ds)
    asvc = create_analysis_service(data_service=ds, engine_factory=ef)
    arb = create_signal_arbitrator()
    sc = create_trading_signal_collector()
    pipe = create_research_pipeline(
        analysis_service=asvc,
        arbitrator=arb,
        signal_collector=sc,
    )
    duration = time.perf_counter() - t0

    assert pipe is not None
    assert asvc is not None
    assert arb is not None
    assert duration < 0.5  # 远快于全容器初始化


def test_bootstrap_wiring_and_isolation(tmp_path):
    mock_storage = MagicMock()
    mock_storage.data_dir = str(tmp_path)
    ds1 = create_data_service(storage_manager=mock_storage)
    ds2 = create_data_service(storage_manager=mock_storage)

    # 实例相互独立，非全局单例
    assert ds1 is not ds2

    asvc = create_analysis_service(data_service=ds1)
    assert asvc.data_service is ds1


def test_create_signal_arbitrator_parameters():
    arb = create_signal_arbitrator(sell_priority=False, quality_threshold=0.5)
    assert arb._sell_priority is False
    assert arb._quality_threshold == 0.5
