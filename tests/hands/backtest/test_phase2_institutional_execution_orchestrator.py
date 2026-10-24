"""
CNMM-QAR 第二阶段 (Phase 2) 生产级多空对冲与微观执行中枢完整门禁测试
=============================================================================
测试范围:
1. 任务 2.1: 资本配置三轨分配与真实利息结算 (CNMM-EX 纯多, CNMM-IH 经典, 75/25-IH 合规)
   - 验证无风险利息仅对 25% 现金准备金计提 (1.5%/年)，彻底消除 200% 虚假增量;
2. 任务 2.2: CFFEX 撮合中枢、BasisSurfaceModel 与 3 PB 账户穿透限仓
   - 验证点位基差、年化贴水率、跨期价差移仓摩擦与 1042+1042+1041 手合规分仓;
   - 验证 5 日阶梯移仓排程 (10%-20%-20%-25%-25%) 与单日最大 POV < 2.5%;
3. 任务 2.3: LiquidityImpactModel (Square-Root Law) 与微观 TWAP 执行切片
   - 验证非线性平方根流动性冲击公式: Slippage = eta * sigma * sqrt(Order_Vol / ADV);
   - 验证单日参与率超过 10% ADV 强制触发跨交易日平滑拆单;
4. 任务 2.4: 跨资产 Saga 四级级联补偿与 SharedKillSwitch 熔断联动
   - 验证 Level 4 极端一字跌停死锁隔离并建立动态合成空头残值锁仓;
   - 验证当极端死锁或保证金耗尽时，自动触发 SharedKillSwitch 停机熔断。
=============================================================================
"""

import math
import pytest
from uniquant.hands.backtest.institutional_execution_orchestrator import (
    InstitutionalExecutionOrchestrator,
    StrategyTrack,
    OrchestratorConfig,
)
from uniquant.hands.backtest.twap_execution_slicer import (
    LiquidityImpactModel,
)
from uniquant.hands.backtest.cffex_engine import (
    BasisSurfaceModel,
    CFFEXMatchingAndRiskEngine,
    FuturesContractType,
)
from uniquant.hands.backtest.saga_compensator import (
    SagaCompensationLevel,
    OrderState,
)
from uniquant.shared.kill_switch import SharedKillSwitch, KillSwitchError


class TestPhase2InstitutionalExecutionGates:
    """Phase 2 生产级门禁全量测试套件"""

    @pytest.fixture
    def fresh_kill_switch(self):
        # 必须绕过 SharedKillSwitch 的进程级单例 (__new__ 缓存 _instance):
        # 直接 SharedKillSwitch() 拿到的是全局单例——本文件 saga/cffex 熔断用例
        # 会把它 kill 且无 teardown 复位, 毒化同进程内后续所有消费
        # get_kill_switch() 的测试 (arbitrator/e2e/health), 全量跑时曾致
        # 28+ 例连锁假失败 (CI 0c2f604/7b51635 红)。此处构造真正隔离的临时实例。
        ks = object.__new__(SharedKillSwitch)
        ks._killed = False
        ks._reason = ""
        ks._hooks = []
        ks._initialized = True
        yield ks
        # 防御性兜底: 若被测代码内部改触全局单例, 离场时一律复位, 严禁泄漏熔断态
        SharedKillSwitch().reset()

    # =========================================================================
    # 1. 任务 2.1 门禁测试: 资本配置三轨与利息核算
    # =========================================================================

    def test_capital_allocation_pure_long(self, fresh_kill_switch):
        """测试纯多增强轨 (CNMM-EX): 100% 股票, 0% 期货, 0% 现金"""
        config = OrchestratorConfig(track=StrategyTrack.PURE_LONG)
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)
        res = orch.allocate_capital(10_000_000.0)

        assert res["track"] == "CNMM-EX"
        assert res["equity_long_value"] == 10_000_000.0
        assert res["equity_ratio"] == 1.00
        assert res["futures_short_notional"] == 0.0
        assert res["cash_buffer_value"] == 0.0
        assert res["gross_leverage"] == 1.00
        assert res["net_exposure_ratio"] == 1.00

    def test_capital_allocation_classic_hedge(self, fresh_kill_switch):
        """测试经典对冲轨 (CNMM-IH): 100% 股票, -100% 期货, 0% 现金"""
        config = OrchestratorConfig(track=StrategyTrack.CLASSIC_HEDGE)
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)
        res = orch.allocate_capital(10_000_000.0)

        assert res["track"] == "CNMM-IH"
        assert res["equity_long_value"] == 10_000_000.0
        assert res["equity_ratio"] == 1.00
        assert res["futures_short_notional"] == 10_000_000.0
        assert res["futures_ratio"] == -1.00
        assert res["cash_buffer_value"] == 0.0
        assert res["gross_leverage"] == 2.00
        assert res["net_exposure_ratio"] == 0.00

    def test_capital_allocation_institutional_75_25(self, fresh_kill_switch):
        """测试机构合规实盘轨 (75/25-IH): 75% 股票, -75% 期货, 25% 现金"""
        config = OrchestratorConfig(track=StrategyTrack.INSTITUTIONAL_75_25)
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)
        res = orch.allocate_capital(10_000_000.0)

        assert res["track"] == "75/25-IH"
        assert res["equity_long_value"] == 7_500_000.0
        assert res["equity_ratio"] == 0.75
        assert res["futures_short_notional"] == 7_500_000.0
        assert res["futures_ratio"] == -0.75
        assert res["cash_buffer_value"] == 2_500_000.0
        assert res["cash_ratio"] == 0.25
        assert res["gross_leverage"] == 1.75
        assert res["net_exposure_ratio"] == 0.00

    def test_daily_gross_return_settlement_attribution(self, fresh_kill_switch):
        """测试日频收益结算与真实利息归因: 75/25 仅对 25% 现金计息"""
        config = OrchestratorConfig(track=StrategyTrack.INSTITUTIONAL_75_25, deposit_annual_rate=0.015)
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)

        # 假定现货涨 1.0%, 基准指数涨 0.5%, 基差贴水平稳
        settle = orch.calculate_daily_gross_return(
            long_return=0.010,
            benchmark_return=0.005,
            spot_price=4000.0,
            futures_price=3980.0,
            days_to_expiry=20,
        )

        attr = settle["attribution"]
        # 多头贡献: 0.75 * 1.0% = 0.0075 (75 bps)
        assert pytest.approx(attr["equity_contrib"], abs=1e-5) == 0.0075
        # 期货空头贡献: -0.75 * 0.5% = -0.00375 (-37.5 bps)
        assert pytest.approx(attr["futures_contrib"], abs=1e-5) == -0.00375
        # 现金存款收益: 0.25 * (1.5% / 252) ≈ 0.00001488 (约 0.15 bps)
        daily_dep = (0.25 * (0.015 / 252.0))
        assert pytest.approx(attr["deposit_contrib"], abs=1e-6) == daily_dep
        # 确认综合毛收益 > 0 且无 100% 现金利息虚增
        assert settle["daily_gross_return"] > 0

    # =========================================================================
    # 2. 任务 2.2 门禁测试: CFFEX 撮合中枢与基差曲面
    # =========================================================================

    def test_basis_surface_model_calculations(self):
        """测试动态基差曲面与年化贴水率计算"""
        spot = 4000.0
        futures = 3960.0  # 贴水 40 点
        basis = BasisSurfaceModel.calculate_basis(spot, futures)
        assert basis == -40.0

        # 到期日剩余 20 个交易日
        annual_rate = BasisSurfaceModel.calculate_annualized_basis_rate(spot, futures, days_to_expiry=20)
        # (3960/4000 - 1) * (252 / 20) = -0.01 * 12.6 = -0.126 (-12.60% 年化贴水)
        assert pytest.approx(annual_rate, abs=1e-4) == -0.1260

        # 移仓价差摩擦估算 (2 个 tick, 每个 0.2 点, 现货 4000 点)
        roll_cost_bps = BasisSurfaceModel.estimate_roll_over_cost_bps(front_price=4000.0, next_price=3960.0)
        # 0.4 / 4000 * 10000 = 1.0 bps
        assert pytest.approx(roll_cost_bps, abs=1e-2) == 1.00

    def test_multi_pb_hedging_allocation_and_staggered_roll(self, fresh_kill_switch):
        """测试 50 亿 AUM 下多 PB 账户对冲分仓与 5 日移仓"""
        config = OrchestratorConfig(track=StrategyTrack.INSTITUTIONAL_75_25, futures_contract_type=FuturesContractType.IF)
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)

        hedge_plan = orch.plan_futures_hedging_structure(
            equity_long_notional=3_750_000_000.0,
            futures_price_points=4000.0,
            num_pb_accounts=3,
        )
        assert hedge_plan["total_short_contracts_needed"] == 3125
        assert hedge_plan["all_accounts_within_speculative_limit"] is True
        for acc in hedge_plan["accounts"]:
            assert acc["allocated_contracts"] <= 1200

        roll_sched = orch.generate_roll_over_schedule(total_contracts=3125)
        assert len(roll_sched) == 5
        assert sum(p.planned_contracts for p in roll_sched) == 3125
        for p in roll_sched:
            assert p.max_contract_pov_pct < 2.5

    # =========================================================================
    # 3. 任务 2.3 门禁测试: 非线性流动性冲击与 TWAP 拆单
    # =========================================================================

    def test_liquidity_impact_square_root_formula(self):
        """测试基于 Almgren-Chriss 的平方根流动性冲击公式"""
        model = LiquidityImpactModel(eta=0.12, max_single_day_pov=0.10)

        # 调仓量 100,000 股, ADV 1,000,000 股 (参与率 10%), 日波动率 2%
        # Impact = 0.12 * 0.02 * sqrt(0.10) = 0.0024 * 0.3162277 = 0.0007589 (7.59 bps)
        slip_bps = model.calculate_slippage_bps(order_volume=100_000, adv=1_000_000, daily_volatility=0.02)
        expected_bps = 0.12 * 0.02 * math.sqrt(0.10) * 10000.0
        assert pytest.approx(slip_bps, abs=0.05) == expected_bps

        # 测试边界安全: ADV <= 0 或 Volume <= 0 返回 0.0
        assert model.calculate_slippage_bps(0, 1_000_000) == 0.0
        assert model.calculate_slippage_bps(100_000, 0) == 0.0

    def test_pov_and_multi_day_slicing_requirement(self):
        """测试单日参与率超过 10% ADV 强制触发跨日拆单"""
        model = LiquidityImpactModel(eta=0.12, max_single_day_pov=0.10)

        # 1. 参与率 5% <= 10%: 不需要跨日拆单
        eval_safe = model.evaluate_pov_and_slicing_requirement(order_volume=50_000, adv=1_000_000)
        assert eval_safe["is_pov_compliant"] is True
        assert eval_safe["requires_multi_day_slicing"] is False
        assert eval_safe["recommended_slicing_days"] == 1

        # 2. 参与率 25% > 10%: 强制建议 3 日拆单
        eval_heavy = model.evaluate_pov_and_slicing_requirement(order_volume=250_000, adv=1_000_000)
        assert eval_heavy["is_pov_compliant"] is False
        assert eval_heavy["requires_multi_day_slicing"] is True
        assert eval_heavy["recommended_slicing_days"] == 3

    def test_orchestrator_rebalance_execution_evaluation(self, fresh_kill_switch):
        """测试总装引擎对组合调仓订单的微观冲击综合精算"""
        orch = InstitutionalExecutionOrchestrator(kill_switch=fresh_kill_switch)
        orders = [
            {"symbol": "600519.SH", "volume_shares": 10000, "price": 1800.0},
            {"symbol": "000858.SZ", "volume_shares": 500000, "price": 150.0},
        ]
        adv_map = {
            "600519.SH": 200000,    # 10000 / 200000 = 5% (合规)
            "000858.SZ": 1000000,   # 500000 / 1000000 = 50% (严重超标，需拆单)
        }
        res = orch.evaluate_rebalance_execution(orders=orders, adv_map=adv_map)

        assert res["total_orders"] == 2
        assert res["slicing_required_count"] == 1
        assert res["volume_weighted_slippage_bps"] > 0
        assert res["total_slippage_cost_rmb"] > 0

    # =========================================================================
    # 4. 任务 2.4 门禁测试: Saga 补偿与 KillSwitch 熔断防护
    # =========================================================================

    def test_saga_level_4_quarantine_triggers_kill_switch(self, fresh_kill_switch):
        """测试遭遇极端一字跌停死锁且未成残值超标时，自动触发 KillSwitch 熔断"""
        config = OrchestratorConfig(
            enable_kill_switch=True,
            quarantine_kill_threshold_rmb=1_000_000.0,  # 100万阈值
        )
        orch = InstitutionalExecutionOrchestrator(config=config, kill_switch=fresh_kill_switch)

        # 模拟跌停死锁: 100,000 股 @ 20.0 元 = 200 万元 (超过 100 万熔断阈值)
        orch.wal_sm.create_order("000001.SZ", "000001.SZ", 100000)
        action = orch.compensate_execution_anomaly(
            stock_symbol="000001.SZ",
            unfilled_shares=100000,
            reason="LIMIT_DOWN_ZERO_VOLUME_DEADLOCK",
            current_equity_delta=2_000_000.0,
            current_futures_delta=-2_000_000.0,
            stock_price=20.0,
        )

        assert action.level == SagaCompensationLevel.LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE
        assert action.synthetic_hedge_notional == 2_000_000.0
        assert orch.wal_sm.get_order_status("000001.SZ") == OrderState.QUARANTINED

        # 验证 KillSwitch 已被熔断触发
        assert fresh_kill_switch.is_killed is True
        assert "SAGA_CRITICAL_QUARANTINE_EXCEEDED" in fresh_kill_switch.reason

        # 再次调用交易补偿应直接抛出 KillSwitchError
        with pytest.raises(KillSwitchError):
            orch.compensate_execution_anomaly(
                stock_symbol="600519.SH",
                unfilled_shares=100,
                reason="NORMAL_LIQUIDITY_DELAY",
                current_equity_delta=100_000.0,
                current_futures_delta=-100_000.0,
            )

    def test_cffex_critical_margin_call_triggers_kill_switch(self, fresh_kill_switch):
        """测试 CFFEX 保证金极度穿透 (风险度 > 115%) 自动触发 KillSwitch 熔断"""
        engine = CFFEXMatchingAndRiskEngine(
            account_id="TEST_KILL_PB",
            initial_cash=10_000_000.0,
            enable_kill_switch=True,
            kill_switch=fresh_kill_switch,
            kill_switch_margin_call_threshold=1.15,
        )

        # 开仓 100 手 IF 空头 @ 4000 点
        trades = [{
            "symbol": "IF2406",
            "contract_type": "IF",
            "side": "SHORT",
            "action": "OPEN",
            "contracts": 100,
            "price": 4000.0,
        }]
        # 结算价暴涨至 4300 点 (空头巨亏 300 点 = 300 * 300 * 100 = 900 万元亏损)
        # 剩余权益 = 1000万 - 900万 = 100万元
        # 保证金占用 = 4300 * 300 * 100 * 0.15 = 19,350,000 元
        # 风险度 = 1935万 / 100万 = 1935% >> 115%
        settle_prices = {"IF2406": 4300.0}
        report = engine.perform_daily_mtm_settlement(
            date="2026-06-15",
            settlement_prices=settle_prices,
            intraday_trades=trades,
        )

        assert report.is_margin_call is True
        assert report.margin_ratio_pct > 115.0
        assert fresh_kill_switch.is_killed is True
        assert "CFFEX_CRITICAL_MARGIN_DEPLETION" in fresh_kill_switch.reason
