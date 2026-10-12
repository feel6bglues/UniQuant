"""
CFFEX 撮合中枢、TWAP 切片器与 Saga 四级补偿生产级单元测试套件
=============================================================================
测试范围:
1. CFFEXMatchingAndRiskEngine:
   - 合约规格 (IF 300, IC 200, IM 200, IH 300);
   - 保证金账户 (12%~15% 交易所, 15%~18% 券商 PB);
   - 逐日盯市结算 (MTM) 盈亏分账与追保判定;
   - 3 PB 账户套保分仓 (1042, 1042, 1041 手, 突破 1200 手限仓);
   - 到期前 5 日阶梯展期 (10-20-20-25-25%, POV < 2.5%).
2. TWAPExecutionSlicer:
   - 3 日黄金窗口 (10:00-14:30, 每日 180 分钟, 540 切片);
   - OFI 限价防抢跑与被动 Maker 比例提升;
   - 对比 Naive TWAP 的滑点摩擦节省.
3. CrossAssetSagaCoordinator:
   - Level 1 微观自愈重试;
   - Level 2 期货 Delta 联动对冲;
   - Level 3 可售底仓替代冲销;
   - Level 4 极端跌停死锁隔离 (QUARANTINED) 与残值合成对冲.
=============================================================================
"""

import pytest

from uniquant.hands.backtest.cffex_engine import (
    CFFEXMatchingAndRiskEngine,
    FuturesContractType,
    CONTRACT_SPECS,
)
from uniquant.hands.backtest.twap_execution_slicer import (
    TWAPExecutionSlicer,
)
from uniquant.hands.backtest.saga_compensator import (
    CrossAssetSagaCoordinator,
    SqliteWalTwapStateMachine,
    OrderState,
    SagaCompensationLevel,
)


# =============================================================================
# 1. CFFEX 撮合中枢与风控门禁测试
# =============================================================================

class TestCFFEXEngineProductionGates:
    """CFFEX 撮合与风控门禁验证"""

    def test_cffex_contract_multipliers_and_ticks(self):
        """验证四大股指期货合约乘数与跳价"""
        assert CONTRACT_SPECS[FuturesContractType.IF].multiplier == 300.0
        assert CONTRACT_SPECS[FuturesContractType.IF].tick_size == 0.2
        assert CONTRACT_SPECS[FuturesContractType.IC].multiplier == 200.0
        assert CONTRACT_SPECS[FuturesContractType.IC].tick_size == 0.2
        assert CONTRACT_SPECS[FuturesContractType.IM].multiplier == 200.0
        assert CONTRACT_SPECS[FuturesContractType.IM].tick_size == 0.2
        assert CONTRACT_SPECS[FuturesContractType.IH].multiplier == 300.0
        assert CONTRACT_SPECS[FuturesContractType.IH].tick_size == 0.2

    def test_cffex_margin_ratios(self):
        """验证交易所基准保证金与券商 PB 保证金标准"""
        if_spec = CONTRACT_SPECS[FuturesContractType.IF]
        assert if_spec.exchange_margin_ratio == 0.12
        assert if_spec.broker_margin_ratio == 0.15

        ic_spec = CONTRACT_SPECS[FuturesContractType.IC]
        assert ic_spec.exchange_margin_ratio == 0.15
        assert ic_spec.broker_margin_ratio == 0.18

        im_spec = CONTRACT_SPECS[FuturesContractType.IM]
        assert im_spec.exchange_margin_ratio == 0.15
        assert im_spec.broker_margin_ratio == 0.18

    def test_cffex_multi_pb_hedging_allocation(self):
        """验证 50 亿 AUM 下 75% 对冲 3 PB 分仓 (1042+1042+1041 手)"""
        res = CFFEXMatchingAndRiskEngine.design_multi_pb_hedging_allocation(
            aum_rmb=5_000_000_000.0,
            hedge_ratio=0.75,
            points=4000.0,
            contract_type=FuturesContractType.IF,
            num_accounts=3,
        )
        assert res["notional_hedged_rmb"] == 3_750_000_000.0
        assert res["total_short_contracts_needed"] == 3125
        assert res["exceeds_single_account_limit"] is True
        assert res["excess_contracts_over_limit"] == 1925
        assert res["all_accounts_within_speculative_limit"] is True

        allocated_contracts = [a["allocated_contracts"] for a in res["accounts"]]
        assert allocated_contracts == [1042, 1042, 1041]
        for a in res["accounts"]:
            assert a["allocated_contracts"] <= 1200
            assert a["utilization_pct"] < 90.0

    def test_cffex_staggered_5day_roll_pov(self):
        """验证到期前 5 日阶梯移仓比例与 POV 严格 < 2.5%"""
        schedule = CFFEXMatchingAndRiskEngine.generate_5day_staggered_roll_schedule(
            total_contracts=3125
        )
        assert len(schedule) == 5
        planned = [p.planned_contracts for p in schedule]
        assert planned == [312, 625, 625, 781, 782]
        assert sum(planned) == 3125

        ratios = [p.target_ratio_pct for p in schedule]
        assert ratios == [10.0, 20.0, 20.0, 25.0, 25.0]

        for p in schedule:
            assert p.max_contract_pov_pct < 2.5
            assert p.is_pov_strictly_below_2_5pct is True
            assert p.front_pov_pct < 2.5
            assert p.next_pov_pct < 2.5
            assert p.spread_pov_pct < 2.5

    def test_cffex_daily_mtm_settlement(self):
        """验证每日逐日盯市 (MTM) 结算与保证金追保逻辑"""
        engine = CFFEXMatchingAndRiskEngine(
            account_id="TEST_PB_001",
            initial_cash=50_000_000.0,
        )
        # 开仓 100 手 IF2406 空头, 开仓价 4000 点
        trades = [
            {
                "symbol": "IF2406",
                "contract_type": "IF",
                "side": "SHORT",
                "action": "OPEN",
                "contracts": 100,
                "price": 4000.0,
                "commission": 1500.0,
            }
        ]
        # 结算价上涨至 4050 点 (空头亏损 50 点)
        # 单点 300 元, 50 点 × 300 × 100 手 = 150 万元亏损
        settle_prices = {"IF2406": 4050.0}
        report = engine.perform_daily_mtm_settlement(
            date="2026-06-15",
            settlement_prices=settle_prices,
            intraday_trades=trades,
        )
        assert report.total_commission == 1500.0
        assert report.unrealized_holding_pnl == -1_500_000.0
        # 保证金计算: 4050 × 300 × 100 × 0.15 = 18,225,000 元
        assert report.total_margin_used == 18_225_000.0
        # 权益 = 50,000,000 - 1500 - 1,500,000 = 48,498,500 元
        assert report.ending_cash == 48_498_500.0
        assert report.available_funds > 0
        assert report.is_margin_call is False


# =============================================================================
# 2. TWAP 切片器与 OFI 防抢跑测试
# =============================================================================

class TestTWAPExecutionSlicerGates:
    """TWAP 切片与微观 OFI 防抢跑门禁"""

    def test_twap_slice_generation(self):
        """验证 3 日 10:00-14:30 切片计划数量与份额守恒"""
        slicer = TWAPExecutionSlicer(
            target_contracts=2031,
            num_days=3,
            daily_minutes=180,
        )
        assert slicer.total_slices == 540
        slices = slicer.slice_parent_order(total_shares=2031)
        assert len(slices) == 540
        sum_shares = sum(s["planned_shares"] for s in slices)
        assert sum_shares == 2031

    def test_twap_ofi_simulation_and_savings(self):
        """验证 OFI 防抢跑触发、被动 Maker 比例与滑点节省"""
        slicer = TWAPExecutionSlicer(
            target_contracts=2031,
            num_days=3,
            daily_minutes=180,
            ofi_threshold=0.35,
            seed=20260924,
        )
        res = slicer.execute_3day_simulation()
        assert res["total_slices"] == 540
        assert res["executed_contracts"] == 2031
        assert res["completion_rate_pct"] == 100.0
        assert res["anti_frontrunning_triggers"] > 0
        assert res["passive_maker_ratio_pct"] >= 60.0
        assert res["ofi_twap_slippage_bps"] < res["naive_twap_slippage_bps"]
        assert res["slippage_savings_bps"] > 0
        assert res["slippage_savings_rmb"] > 0


# =============================================================================
# 3. Saga 四级分布式补偿与抗死锁测试
# =============================================================================

class TestSagaCompensatorGates:
    """Saga 四级补偿与抗死锁验证"""

    @pytest.fixture
    def saga_coordinator(self):
        sm = SqliteWalTwapStateMachine(db_path=":memory:")
        coord = CrossAssetSagaCoordinator(wal_sm=sm)
        return coord

    def test_saga_level_1_micro_retry(self, saga_coordinator):
        """Level 1: 微观窗口流动性自愈"""
        action = saga_coordinator.evaluate_and_route_compensation(
            stock_symbol="600519.SH",
            unfilled_shares=100,
            reason="NORMAL_LIQUIDITY_DELAY",
            current_equity_delta=100_000.0,
            current_futures_delta=-100_000.0,
        )
        assert action.level == SagaCompensationLevel.LEVEL_1_MICRO_RETRY
        assert action.status == "COMPLETED"

    def test_saga_level_2_futures_delta_compensate(self, saga_coordinator):
        """Level 2: 现货未完全成交导致 Delta 偏差 > 1.0%, 期货秒级联动补偿"""
        # 现货多头 5000 万, 期货空头 4000 万, 失衡 1000 万 (远大于 1.0%)
        action = saga_coordinator.evaluate_and_route_compensation(
            stock_symbol="000300.SH",
            unfilled_shares=50000,
            reason="PARTIAL_FILL_DRIFT",
            current_equity_delta=50_000_000.0,
            current_futures_delta=-40_000_000.0,
        )
        assert action.level == SagaCompensationLevel.LEVEL_2_FUTURES_DELTA_COMPENSATE
        assert action.adjusted_futures_contracts > 0
        assert action.details["hedge_adjustment_action"] == "SELL_SHORT_FUTURES"

    def test_saga_level_3_inventory_substitution(self, saga_coordinator):
        """Level 3: 卖单遭遇 T+1 或拒单, 调取历史可用底仓冲销"""
        action = saga_coordinator.evaluate_and_route_compensation(
            stock_symbol="600519.SH",
            unfilled_shares=500,
            reason="T1_LOCKED_CANNOT_SELL",
            current_equity_delta=0.0,
            current_futures_delta=0.0,
            available_inventory_shares=800,
        )
        assert action.level == SagaCompensationLevel.LEVEL_3_INVENTORY_SUBSTITUTE_OR_ABORT
        assert action.substitute_shares_used == 500

    def test_saga_level_4_limit_down_deadlock_quarantine(self, saga_coordinator):
        """Level 4: 遭遇一字跌停死锁, 标记 QUARANTINED 并建立动态合成空头残值锁仓"""
        stock_sym = "000001.SZ"
        saga_coordinator.wal_sm.create_order(stock_sym, stock_sym, 10000)
        action = saga_coordinator.evaluate_and_route_compensation(
            stock_symbol=stock_sym,
            unfilled_shares=10000,
            reason="LIMIT_DOWN_ZERO_VOLUME_DEADLOCK",
            current_equity_delta=100_000.0,
            current_futures_delta=-100_000.0,
            stock_price=10.0,
        )
        assert action.level == SagaCompensationLevel.LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE
        assert action.synthetic_hedge_notional == 100_000.0
        # 验证母单状态已被置为 QUARANTINED
        state = saga_coordinator.wal_sm.get_order_status(stock_sym)
        assert state == OrderState.QUARANTINED
