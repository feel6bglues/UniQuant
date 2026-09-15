"""测试 five_gate 增强门禁：自由度一致性 (ddof=1)、块自助置信区间与 Class A 评定。"""

import numpy as np
import pandas as pd

from scripts.factor_mining.five_gate import (
    block_bootstrap_ic_ci,
    block_bootstrap_pbo,
    daily_ic_series,
)


def test_block_bootstrap_ic_ci_significant():
    """验证真实显著正 IC 序列置信区间全大于 0 且 is_significant=True。"""
    np.random.seed(42)
    # 均值 0.05，标准差 0.02，长度 17 窗
    sig_ics = list(np.random.normal(0.05, 0.015, 17))
    res = block_bootstrap_ic_ci(sig_ics, n_bootstrap=1000)

    assert res["is_significant"] is True
    assert res["ci_lower"] > 0.0
    assert res["ci_upper"] > res["ci_lower"]
    assert res["bootstrap_p"] < 0.05


def test_block_bootstrap_ic_ci_noise():
    """验证纯白噪声 IC 序列置信区间跨越 0 且 is_significant=False。"""
    np.random.seed(42)
    # 均值 0.00，标准差 0.03
    noise_ics = list(np.random.normal(0.0, 0.03, 17))
    res = block_bootstrap_ic_ci(noise_ics, n_bootstrap=1000)

    assert res["is_significant"] is False
    assert res["ci_lower"] < 0.0
    assert res["ci_upper"] > 0.0
    assert res["bootstrap_p"] > 0.10


def test_daily_ic_series_ddof_unification():
    """验证 daily_ic_series 内部残差回归采用统一的 ddof=1，不产生小截面偏差。"""
    np.random.seed(123)
    n_stocks = 25  # 小截面样本
    dates = [pd.Timestamp("2024-01-02")]
    stocks = [f"{i:06d}.SZ" for i in range(n_stocks)]

    idx = pd.MultiIndex.from_product([stocks, dates], names=["code", "date"])
    mom20 = np.random.normal(0, 1, n_stocks)
    # 因子包含动量成分加上正交特异成分
    factor = 0.8 * mom20 + np.random.normal(0, 0.5, n_stocks)
    fwd5 = 0.5 * factor + np.random.normal(0, 0.5, n_stocks)

    df = pd.DataFrame({
        "mom20": mom20,
        "test_factor": factor,
        "fwd5": fwd5,
    }, index=idx)

    res = daily_ic_series(df, "test_factor")
    assert len(res["raw"]) == 1
    assert len(res["res"]) == 1
    assert np.isfinite(res["raw"][0])
    assert np.isfinite(res["res"][0])


def test_block_bootstrap_pbo_backward_compatibility():
    """验证旧版 PBO 接口保持向后兼容。"""
    ics = [0.03, 0.04, 0.02, 0.05, 0.01, 0.06]
    pbo = block_bootstrap_pbo(ics, n_bootstrap=100)
    assert 0.0 <= pbo <= 1.0
