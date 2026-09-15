"""测试 H-A 轮换引擎动态弹性缓冲槽位与防饿死机制。"""

import numpy as np
import pandas as pd

from scripts.canslim.ha_rotation_sim import SlotRotationSim, _Slot, _reset_slot


def test_slot_reset_clears_flags():
    sl = _Slot(10000.0)
    sl.code = "000001.SZ"
    sl.shares = 1000.0
    sl.is_locked = True
    sl.is_buffer = True

    _reset_slot(sl)
    assert sl.shares == 0.0
    assert sl.code is None
    assert sl.is_locked is False
    assert sl.is_buffer is False


def test_slot_rotation_backward_compatibility():
    """验证 n_buffer_slots=0 时与旧版完全兼容。"""
    dates = pd.bdate_range("2024-01-02", periods=20)
    codes = ["000001.SZ", "000002.SZ", "600001.SH"]
    closes = pd.DataFrame(
        {
            "000001.SZ": np.full(20, 10.0),
            "000002.SZ": np.full(20, 20.0),
            "600001.SH": np.full(20, 30.0),
        },
        index=dates,
    )
    pre = closes.shift(1).fillna(closes)
    volumes = pd.DataFrame(np.full((20, 3), 1e6), index=dates, columns=codes)
    adv = volumes.copy()

    # 调仓计划: 第 0 天持仓 000001.SZ, 第 5 天换持仓 000002.SZ
    hmap = {
        dates[0]: {"000001.SZ"},
        dates[5]: {"000002.SZ"},
    }

    sim = SlotRotationSim(n_slots=2, initial_capital=1e6, n_buffer_slots=0)
    res = sim.run(closes, pre, volumes, adv, hmap, list(dates))

    assert res["n_rebalances"] >= 2
    assert res["ann_return"] is not None
    assert res["sharpe"] is not None


def test_slot_rotation_buffer_saves_from_starvation():
    """验证当发生拒卖导致正常槽位占满时，弹性缓冲槽位成功接纳新进 Alpha 股票。"""
    dates = pd.bdate_range("2024-01-02", periods=10)
    codes = ["000001.SZ", "000002.SZ"]

    # 标的 000001.SZ 在第 3 天跌停 (价格从 10.0 跌到 8.5，跌幅超过 10%)
    px_a = np.full(10, 10.0)
    px_a[3:] = 8.5  # 严重跌停拒卖
    pre_a = np.full(10, 10.0)
    pre_a[3] = 10.0  # 8.5 / 10.0 = -15% -> 触发跌停拒卖

    px_b = np.full(10, 20.0)
    pre_b = np.full(10, 20.0)

    closes = pd.DataFrame({"000001.SZ": px_a, "000002.SZ": px_b}, index=dates)
    pre = pd.DataFrame({"000001.SZ": pre_a, "000002.SZ": pre_b}, index=dates)
    volumes = pd.DataFrame(np.full((10, 2), 1e6), index=dates, columns=codes)
    adv = volumes.copy()

    # 初始持续持仓 000001.SZ (占满唯一的 1 个槽位)
    # 第 3 天尝试从 000001.SZ 换仓到 000002.SZ (但 000001.SZ 跌停拒卖)
    hmap = {d: {"000001.SZ"} for d in dates[:3]}
    for d in dates[3:]:
        hmap[d] = {"000002.SZ"}

    # 1. 对照组: 无缓冲槽位 (n_buffer_slots=0) -> 000002.SZ 被直接丢弃
    sim_rigid = SlotRotationSim(n_slots=1, initial_capital=1e6, n_buffer_slots=0, buffer_cash_pct=0.0)
    res_rigid = sim_rigid.run(closes, pre, volumes, adv, hmap, list(dates), nav_capture=True)

    # 2. 实验组: 启用 1 个缓冲槽位 (n_buffer_slots=1, buffer_cash_pct=0.20)
    sim_buffer = SlotRotationSim(n_slots=1, initial_capital=1e6, n_buffer_slots=1, buffer_cash_pct=0.20)
    res_buffer = sim_buffer.run(closes, pre, volumes, adv, hmap, list(dates), nav_capture=True)

    # 验证拒单触发且缓冲槽位减缓了跌停造成的净值回撤
    assert res_rigid["n_rejected_fills"] >= 1
    assert res_buffer["n_rejected_fills"] >= 1
    assert res_buffer["end_nav"] > res_rigid["end_nav"]
    assert res_buffer["max_drawdown"] > res_rigid["max_drawdown"]
