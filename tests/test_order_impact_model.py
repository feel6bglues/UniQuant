"""测试统一撮合引擎基于真实订单参与率的市场冲击模型。"""

import numpy as np

from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


def test_retail_order_near_zero_impact():
    """验证散户 1 手 (100股) 对日均 1000万股流动性的标的冲击近乎为零 (< 1 bps)。"""
    engine = UnifiedMatchingEngine(slippage_rate=0.0)
    prices = np.array([10.0])
    volumes = np.array([10_000_000.0])
    advs = np.array([10_000_000.0])
    quantities = np.array([100.0])  # 1 手

    exec_px = engine.compute_execution_prices(
        prices=prices,
        volumes=volumes,
        avg_daily_volumes=advs,
        is_buy=True,
        quantities=quantities,
    )
    # 理论冲击: 0.001 * sqrt((100 / 1e7) / 0.1) = 0.001 * sqrt(0.0001) = 0.00001 (0.1 bps)
    # 执行价 = 10.0 * (1 + 0.00001) = 10.0001
    impact_rate = (exec_px[0] / prices[0]) - 1.0
    assert impact_rate < 0.0001  # 小于 1 bps
    assert np.isclose(exec_px[0], 10.0001, atol=1e-5)


def test_moderate_order_sqrt_impact():
    """验证 5% ADV 委托量的冲击约为 7.07 bps。"""
    engine = UnifiedMatchingEngine(slippage_rate=0.0)
    prices = np.array([100.0])
    volumes = np.array([1_000_000.0])
    advs = np.array([1_000_000.0])
    quantities = np.array([50_000.0])  # 5% ADV

    exec_px = engine.compute_execution_prices(
        prices=prices,
        volumes=volumes,
        avg_daily_volumes=advs,
        is_buy=True,
        quantities=quantities,
    )
    # 理论冲击: 0.001 * sqrt(0.05 / 0.10) = 0.001 * sqrt(0.5) = 0.0007071 (7.07 bps)
    impact_rate = (exec_px[0] / prices[0]) - 1.0
    assert np.isclose(impact_rate, 0.0007071, atol=1e-5)


def test_threshold_10pct_adv_impact():
    """验证刚好 10% ADV 委托量的冲击精确为 10 bps (0.001)。"""
    engine = UnifiedMatchingEngine(slippage_rate=0.0)
    prices = np.array([50.0])
    volumes = np.array([1_000_000.0])
    advs = np.array([1_000_000.0])
    quantities = np.array([100_000.0])  # 10% ADV

    exec_px = engine.compute_execution_prices(
        prices=prices,
        volumes=volumes,
        avg_daily_volumes=advs,
        is_buy=True,
        quantities=quantities,
    )
    # 理论冲击: 0.001 * sqrt(0.10 / 0.10) = 0.001 (10 bps)
    impact_rate = (exec_px[0] / prices[0]) - 1.0
    assert np.isclose(impact_rate, 0.001, atol=1e-6)


def test_large_order_linear_penalty_and_cap():
    """验证超过 10% ADV 的大单冲击线性加剧，并受 5% (500 bps) 封顶。"""
    engine = UnifiedMatchingEngine(slippage_rate=0.0)
    prices = np.array([20.0, 20.0])
    volumes = np.array([1_000_000.0, 1_000_000.0])
    advs = np.array([1_000_000.0, 1_000_000.0])
    quantities = np.array([300_000.0, 10_000_000.0])  # 30% ADV, 1000% ADV

    exec_px = engine.compute_execution_prices(
        prices=prices,
        volumes=volumes,
        avg_daily_volumes=advs,
        is_buy=True,
        quantities=quantities,
    )
    # 30% ADV: 0.001 + 0.01 * (0.30 - 0.10) = 0.001 + 0.002 = 0.003 (30 bps)
    impact_30 = (exec_px[0] / prices[0]) - 1.0
    assert np.isclose(impact_30, 0.003, atol=1e-5)

    # 1000% ADV: 封顶为 0.05 (500 bps)
    impact_huge = (exec_px[1] / prices[1]) - 1.0
    assert np.isclose(impact_huge, 0.05, atol=1e-5)


def test_fallback_when_quantities_is_none():
    """验证未传入 quantities 时的向后兼容退化行为。"""
    engine = UnifiedMatchingEngine(slippage_rate=0.001)
    prices = np.array([10.0])
    volumes = np.array([1_000_000.0])
    advs = np.array([1_000_000.0])

    exec_px = engine.compute_execution_prices(
        prices=prices,
        volumes=volumes,
        avg_daily_volumes=advs,
        is_buy=True,
        quantities=None,
    )
    # vol_ratio = 1.0, impact = 0.001 * sqrt(1.0) = 0.001
    # total_slip = 0.001 (slippage_rate) + 0.001 (impact) = 0.002
    assert np.isclose(exec_px[0], 10.0 * 1.002)
