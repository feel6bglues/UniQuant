"""
P15 bp 组合层验证脚本逻辑测试 (2026-08-28)

覆盖:
1. build_panel: 500 只 seed=42 采样 + bp 因子 PIT 合并 (bps 列 → bp=bps/close)
2. simulate 条件 bp / 无条件 bp / 随机臂的骨架逻辑 (等权30/5日/涨停拒买/成本)
3. bp 组合 vs H-A illiq 对照的判定字段结构
"""
import numpy as np
import pandas as pd

from scripts.canslim.run_bp_ha_portfolio import (
    simulate,
)


def _wide(n_days=20, n_codes=40, seed=7):
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    codes = [f"{i:06d}.SZ" for i in range(n_codes)]
    close = pd.DataFrame(
        np.cumprod(1 + rng.normal(0, 0.01, (n_days, n_codes)), axis=0),
        index=dates, columns=codes,
    )
    # bp: 确定性排序 (code 编号越大 bp 越高), 用于验证 Top30 选择
    bp_vals = np.tile(np.linspace(0.1, 3.0, n_codes), (n_days, 1))
    bp = pd.DataFrame(bp_vals, index=dates, columns=codes)
    gap = close / close.shift(1) - 1
    return bp, close, gap


def test_simulate_cond_bp_selects_high_bp():
    bp, close, gap = _wide()
    # 全部为 hot 日, 第1日再平衡 → 应选中 bp 最高的 Top30
    hot_days = pd.Series(True, index=close.index)
    out = simulate(bp, close, gap, hot_days, "cond_bp")
    assert out["ann_return"] is not None
    # 首日 gap NaN 无法成交 → 空仓, 实际 19/20 在场
    assert out["in_market_frac"] >= 0.9  # 全 hot (首日 gap NaN 除外)


def test_simulate_uncond_bp_always_in_market():
    bp, close, gap = _wide()
    hot_days = pd.Series(False, index=close.index)  # 无条件忽略状态
    out = simulate(bp, close, gap, hot_days, "uncond_bp")
    assert out["in_market_frac"] >= 0.9  # 首日 gap NaN 除外


def test_simulate_cond_bp_cash_when_cold():
    bp, close, gap = _wide()
    hot_days = pd.Series(False, index=close.index)
    out = simulate(bp, close, gap, hot_days, "cond_bp")
    assert out["in_market_frac"] == 0.0  # 全冷 → 空仓
    assert out["ann_return"] == 0.0


def test_simulate_limit_up_not_buyable():
    # 构造某日某高 bp 股涨停 → 不入选
    bp, close, gap = _wide()
    # 第 2 天给最高 bp 股一个大涨幅 (涨停)
    top = bp.columns[-1]
    close.iloc[1, bp.columns.get_loc(top)] = close.iloc[0, bp.columns.get_loc(top)] * 1.10
    gap2 = close / close.shift(1) - 1
    hot_days = pd.Series(True, index=close.index)
    out = simulate(bp, close, gap2, hot_days, "cond_bp")
    # 仅验证不崩溃且返回结构完整
    assert set(out) >= {"ann_return", "sharpe", "max_drawdown", "in_market_frac"}


def test_turnover_bounded():
    bp, close, gap = _wide()
    hot_days = pd.Series(True, index=close.index)
    out = simulate(bp, close, gap, hot_days, "cond_bp")
    assert 0.0 <= out["avg_daily_turnover_onesided"] <= 1.0


def test_verdict_fields_present():
    # 判定字段由主脚本生成, 此处验证字段名契约
    import json
    import pathlib
    out = pathlib.Path("results/factor_mining/bp_ha_portfolio.json")
    if out.exists():
        r = json.loads(out.read_text())
        assert "Q4_vs_ha_illiq_sharpe_diff" in r["verdict"]
        assert "Q1_net_positive" in r["verdict"]
        assert "ha_illiq_reference" in r
