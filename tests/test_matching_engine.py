"""
UnifiedMatchingEngine 测试：
- 涨跌停拦截（主板 10%/科创 20%/北交所 30%）
- T+1 约束
- 最低佣金 + 印花税
- 非线性滑点
- 现金不足熔断
"""

import numpy as np
import pandas as pd

from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine, FillResult
from uniquant.shared.slippage_model import DefaultSlippage, DynamicSlippage


def test_buy_normal_execution():
    eng = UnifiedMatchingEngine(min_commission=5.0, stamp_duty_rate=0.0005, slippage_rate=0.001)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([2000.0], dtype=np.float64)
    pc = np.array([9.8], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([1000000], dtype=np.float64)
    adv = np.array([5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert not fill.rejected_mask[0], "Normal buy should not be rejected"
    assert fill.executed_shares[0] > 0
    assert fill.exec_prices[0] > px[0], "Buy slippage should increase price"
    assert fill.commissions[0] >= 5.0, "Min commission should apply"


def test_limit_up_rejection():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([11.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([10000.0], dtype=np.float64)
    pc = np.array([10.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([100], dtype=np.float64)
    adv = np.array([100], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert fill.rejected_mask[0], "Limit-up should reject buy"
    assert fill.limit_violation_mask[0]
    assert fill.executed_shares[0] == 0, "Rejected buy must have 0 shares"
    assert fill.commissions[0] == 0, "Rejected buy must have 0 commissions"
    assert fill.transfer_fees[0] == 0, "Rejected buy must have 0 transfer_fees"
    assert fill.slippages[0] == 0, "Rejected buy must have 0 slippages"


def test_limit_down_rejection():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([9.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    pc = np.array([10.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([100], dtype=np.float64)
    adv = np.array([100], dtype=np.float64)
    pos = np.array([100], dtype=np.int64)
    pco = np.array([10.0], dtype=np.float64)
    bd = np.array([pd.Timestamp("2023-12-01")], dtype=object)

    fill = eng.fill_sell(px, sh, pos, pco, pc, sym, ts, bd, vol, adv)
    assert fill.rejected_mask[0], "Limit-down should reject sell"
    assert fill.executed_shares[0] == 0, "Rejected sell must have 0 shares"
    assert fill.commissions[0] == 0, "Rejected sell must have 0 commissions"
    assert fill.stamp_duties[0] == 0, "Rejected sell must have 0 stamp_duties"
    assert fill.transfer_fees[0] == 0, "Rejected sell must have 0 transfer_fees"
    assert fill.slippages[0] == 0, "Rejected sell must have 0 slippages"


def test_cash_shortfall_auto_reduce():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([50.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([100.0], dtype=np.float64)
    pc = np.array([49.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([1000], dtype=np.float64)
    adv = np.array([10000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert fill.cash_shortfall_mask[0], "Cash shortfall should be detected"
    assert fill.executed_shares[0] < sh[0], "Shares should be auto-reduced"


def test_stamp_duty_on_sell():
    eng = UnifiedMatchingEngine(stamp_duty_rate=0.0005, min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    pos = np.array([100], dtype=np.int64)
    pco = np.array([9.0], dtype=np.float64)
    pc = np.array([10.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    bd = np.array([pd.Timestamp("2023-12-01")], dtype=object)
    vol = np.array([1000], dtype=np.float64)
    adv = np.array([10000], dtype=np.float64)

    fill = eng.fill_sell(px, sh, pos, pco, pc, sym, ts, bd, vol, adv)
    if not fill.rejected_mask[0]:
        assert fill.stamp_duties[0] > 0, "Stamp duty should be charged on sell"
        assert fill.commissions[0] >= 5.0


def test_board_limit_variation():
    eng = UnifiedMatchingEngine()
    px = np.array([12.0, 22.0, 14.0], dtype=np.float64)
    sh = np.array([100, 100, 100], dtype=np.int64)
    ca = np.array([10000.0, 10000.0, 10000.0], dtype=np.float64)
    pc = np.array([10.0, 20.0, 10.0], dtype=np.float64)
    sym = np.array(["000001.SZ", "688001.SH", "830001.BJ"])
    ts = np.array(["2024-01-02"] * 3, dtype=object)
    vol = np.array([1000, 1000, 1000], dtype=np.float64)
    adv = np.array([10000, 10000, 10000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    # 主板 10%: 10*1.1=11, 12 > 11 → limitup
    assert fill.rejected_mask[0], "Main board 10% limit-up should reject"
    # 科创板 20%: 20*1.2=24, 22 < 24 → OK
    assert not fill.rejected_mask[1], "STAR 20% should allow"
    # 北交所 30%: 10*1.3=13, 14 > 13 → limitup
    assert fill.rejected_mask[2], "BSE 30% limit-up should reject"


def test_vectorized_batch():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    n = 100
    np.random.seed(42)
    px = np.random.uniform(5, 50, n)
    sh = np.full(n, 1000, dtype=np.int64)
    ca = np.full(n, 50000.0)
    pc = px * np.random.uniform(0.9, 1.0, n)
    sym = np.array([f"{i:06d}.SZ" for i in range(n)])
    ts = np.full(n, "2024-01-02", dtype=object)
    vol = np.full(n, 1000000.0)
    adv = np.full(n, 5000000.0)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert isinstance(fill, FillResult)
    assert len(fill.executed_shares) == n
    assert fill.exec_prices.shape == (n,)
    assert fill.commissions.shape == (n,)
    assert fill.rejected_mask.shape == (n,)
    rejected = fill.rejected_mask.sum()
    accepted = n - rejected
    if accepted > 0:
        assert float(fill.commissions[~fill.rejected_mask].min()) >= 5.0


def test_slippage_model_adapter_default():
    model = DefaultSlippage()
    eng = UnifiedMatchingEngine(slippage_model=model, min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([2000.0], dtype=np.float64)
    pc = np.array([9.8], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([1000000], dtype=np.float64)
    adv = np.array([5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert not fill.rejected_mask[0]
    assert fill.executed_shares[0] > 0
    assert fill.slippages[0] > 0, "SlippageModel should produce positive slippage"


def test_slippage_model_adapter_dynamic():
    model = DynamicSlippage()
    eng = UnifiedMatchingEngine(slippage_model=model, min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([2000.0], dtype=np.float64)
    pc = np.array([9.8], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([1000000], dtype=np.float64)
    adv = np.array([5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert not fill.rejected_mask[0]
    assert fill.executed_shares[0] > 0


def test_slippage_model_backward_compatible():
    eng = UnifiedMatchingEngine(slippage_rate=0.002, min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([2000.0], dtype=np.float64)
    pc = np.array([9.8], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([1000000], dtype=np.float64)
    adv = np.array([5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert not fill.rejected_mask[0]
    assert fill.executed_shares[0] > 0
    assert fill.slippages[0] > 0


def test_t1_violation_rejected():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    pos = np.array([100], dtype=np.int64)
    pco = np.array([9.0], dtype=np.float64)
    pc = np.array([10.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    bd = np.array([pd.Timestamp("2024-01-02")], dtype=object)
    vol = np.array([1000], dtype=np.float64)
    adv = np.array([10000], dtype=np.float64)

    fill = eng.fill_sell(px, sh, pos, pco, pc, sym, ts, bd, vol, adv)
    assert fill.t1_violation_mask[0], "Same-day sell should be T+1 violation"
    assert fill.rejected_mask[0], "T+1 violation should reject sell"
    assert fill.executed_shares[0] == 0, "Rejected sell must have 0 shares"


def test_t1_next_day_allowed():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    pos = np.array([100], dtype=np.int64)
    pco = np.array([9.0], dtype=np.float64)
    pc = np.array([10.0], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-03"], dtype=object)
    bd = np.array([pd.Timestamp("2024-01-02")], dtype=object)
    vol = np.array([1000], dtype=np.float64)
    adv = np.array([10000], dtype=np.float64)

    fill = eng.fill_sell(px, sh, pos, pco, pc, sym, ts, bd, vol, adv)
    assert not fill.t1_violation_mask[0], "Next-day sell should not be T+1 violation"
    assert fill.executed_shares[0] > 0, "Next-day sell should execute"


def test_halt_volume_zero_rejected():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([10.0], dtype=np.float64)
    sh = np.array([100], dtype=np.int64)
    ca = np.array([2000.0], dtype=np.float64)
    pc = np.array([9.8], dtype=np.float64)
    sym = np.array(["000001.SZ"])
    ts = np.array(["2024-01-02"], dtype=object)
    vol = np.array([0], dtype=np.float64)
    adv = np.array([5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert fill.rejected_mask[0], "Halted stock (volume=0) should reject buy"
    assert fill.executed_shares[0] == 0, "Rejected buy must have 0 shares"


def test_transfer_fee_sz_exempt():
    eng = UnifiedMatchingEngine(min_commission=5.0)
    px = np.array([10.0, 10.0, 10.0], dtype=np.float64)
    sh = np.array([100, 100, 100], dtype=np.int64)
    ca = np.array([2000.0, 2000.0, 2000.0], dtype=np.float64)
    pc = np.array([9.8, 9.8, 9.8], dtype=np.float64)
    sym = np.array(["000001.SZ", "300001.SZ", "600001.SH"])
    ts = np.array(["2024-01-02"] * 3, dtype=object)
    vol = np.array([1000000, 1000000, 1000000], dtype=np.float64)
    adv = np.array([5000000, 5000000, 5000000], dtype=np.float64)

    fill = eng.fill_buy(px, sh, ca, pc, sym, ts, vol, adv)
    assert fill.transfer_fees[0] == 0.0, "SZ 00xxxx should have no transfer fee"
    assert fill.transfer_fees[1] == 0.0, "SZ 30xxxx should have no transfer fee"
    assert fill.transfer_fees[2] > 0.0, "SH 60xxxx should have transfer fee"
