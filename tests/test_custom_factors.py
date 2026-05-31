import pytest
import pandas as pd
import numpy as np
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.custom_factors import compute_turnover_momentum_20d

def test_custom_factor_registered():
    factor = FactorRegistry.get_factor("turnover_momentum_20d")
    assert factor is not None
    assert factor.category == "technical"
    assert factor.default_weight == 0.85

def test_compute_turnover_momentum_20d():
    # 构造能够触发 20日动量的测试数据 (至少需要21条)
    df = pd.DataFrame({
        "volume": [1000] * 25,
        "close": [1.0] * 25,
        "circulating_market_cap": [10] * 25
    })
    
    # 改变第 21 行的前20日对比值
    # Day 0: vol=1000 * close=1 / cap=10 => turnover = 100
    # Day 20: vol=2000 * close=1 / cap=10 => turnover = 200
    # Pct Change (20 days): (200 - 100) / 100 = 1.0
    
    df.loc[20, "volume"] = 2000
    
    result = compute_turnover_momentum_20d(df)
    
    assert len(result) == 25
    # 前20天应该是 NaN
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[19])
    
    # 第21天应该是 1.0 (100% 提升)
    assert np.isclose(result.iloc[20], 1.0)


def test_compute_turnover_momentum_20d_uses_turnover_rate_when_available():
    df = pd.DataFrame({
        "volume": [1000] * 25,
        "turnover_rate": [10.0] * 25,
    })
    df.loc[20, "turnover_rate"] = 20.0

    result = compute_turnover_momentum_20d(df)

    assert np.isclose(result.iloc[20], 1.0)


def test_compute_turnover_momentum_20d_does_not_invent_amount_proxy():
    df = pd.DataFrame({
        "volume": [1000] * 25,
        "amount": [10000] * 25,
    })

    result = compute_turnover_momentum_20d(df)

    assert result.isna().all()
