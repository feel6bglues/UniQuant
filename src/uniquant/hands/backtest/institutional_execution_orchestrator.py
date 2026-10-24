"""
CNMM-QAR 机构级多空对冲与微观执行总装调度引擎 (Institutional Execution Orchestrator)
=============================================================================
核心职责 (整合 Phase 2 四大 P0 级核心组件):
1. 任务 2.1: 资本配置三轨驱动 (纯多增强轨、经典对冲轨、机构 75/25 合规实盘轨)，
             剥离虚增利息，按 25% 现金头寸真实核算协定存款收益 (1.5%/年);
2. 任务 2.2: 接入 CFFEXMatchingAndRiskEngine 与 BasisSurfaceModel，
             多 PB 账户分仓穿透限仓、5 日阶梯移仓排程 (POV < 2.5%) 与动态基差摩擦;
3. 任务 2.3: 接入 TWAPExecutionSlicer 与 LiquidityImpactModel (Square-Root Law)，
             单日参与率超过 10% ADV 自动触发 3 日平滑拆单与 OFI 防抢跑;
4. 任务 2.4: 接入 CrossAssetSagaCoordinator 四级级联补偿与 SharedKillSwitch 熔断防护。
=============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from uniquant.hands.backtest.cffex_engine import (
    CFFEXMatchingAndRiskEngine,
    FuturesContractType,
    BasisSurfaceModel,
)
from uniquant.hands.backtest.twap_execution_slicer import (
    LiquidityImpactModel,
)
from uniquant.hands.backtest.saga_compensator import (
    CrossAssetSagaCoordinator,
    SqliteWalTwapStateMachine,
    CompensationAction,
)
from uniquant.hands.backtest.institutional_fee_ledger import (
    InstitutionalFeeLedger,
)
from uniquant.shared.kill_switch import SharedKillSwitch, get_kill_switch


class StrategyTrack(str, Enum):
    """策略多轨运行架构枚举"""
    PURE_LONG = "CNMM-EX"                 # 纯多增强轨: 100% 股票多头, 不对冲
    CLASSIC_HEDGE = "CNMM-IH"             # 经典对冲轨: 100% 股票多头, -100% 股指空头
    INSTITUTIONAL_75_25 = "75/25-IH"       # 机构合规实盘轨: 75% 股票多头, -75% 股指空头, 25% 准备金


@dataclass
class OrchestratorConfig:
    """机构总装调度配置"""
    track: StrategyTrack = StrategyTrack.INSTITUTIONAL_75_25
    initial_aum: float = 50_000_000.0
    deposit_annual_rate: float = 0.015             # 协定存款年化收益率 1.50%
    futures_contract_type: FuturesContractType = FuturesContractType.IF
    annual_basis_drag: float = 0.025               # 基差年化贴水拖累基准 2.50%
    twap_eta: float = 0.12                         # 平方根市场冲击系数
    max_single_day_pov: float = 0.10               # 单日参与率上限 (10% ADV)
    enable_kill_switch: bool = True
    quarantine_kill_threshold_rmb: float = 5_000_000.0  # Level 4 熔断阈值
    margin_call_kill_threshold: float = 1.15       # 风险度 > 115% 熔断阈值
    mgmt_fee_rate: float = 0.02                    # 私募管理费率 2.0%
    carry_rate: float = 0.20                       # 业绩报酬提成 20.0%
    hurdle_rate: float = 0.06                      # 业绩提成基准 6.0%


class InstitutionalExecutionOrchestrator:
    """
    机构级多空对冲与微观执行总装调度中枢
    """

    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        kill_switch: Optional[SharedKillSwitch] = None,
    ):
        self.config = config or OrchestratorConfig()
        self.kill_switch = kill_switch or get_kill_switch()

        # 1. 任务 2.2: 中金所撮合与风控中枢
        initial_cash_for_cffex = (
            self.config.initial_aum * 0.25
            if self.config.track == StrategyTrack.INSTITUTIONAL_75_25
            else self.config.initial_aum * 0.15
        )
        self.cffex_engine = CFFEXMatchingAndRiskEngine(
            account_id="ORCHESTRATOR_MASTER_PB",
            initial_cash=initial_cash_for_cffex,
            enable_kill_switch=self.config.enable_kill_switch,
            kill_switch=self.kill_switch,
            kill_switch_margin_call_threshold=self.config.margin_call_kill_threshold,
        )

        # 2. 任务 2.3: 平方根流动性冲击与微观执行模型
        self.impact_model = LiquidityImpactModel(
            eta=self.config.twap_eta,
            max_single_day_pov=self.config.max_single_day_pov,
        )

        # 3. 任务 2.4: 跨资产 Saga 补偿协调器
        self.wal_sm = SqliteWalTwapStateMachine(db_path=":memory:")
        self.saga_coordinator = CrossAssetSagaCoordinator(
            wal_sm=self.wal_sm,
            futures_point_value=300.0,
            futures_price=4000.0,
            enable_kill_switch=self.config.enable_kill_switch,
            kill_switch=self.kill_switch,
            quarantine_kill_threshold_rmb=self.config.quarantine_kill_threshold_rmb,
        )

        # 4. 私募机构治理账本
        self.fee_ledger = InstitutionalFeeLedger(
            mgmt_fee_rate=self.config.mgmt_fee_rate,
            carry_rate=self.config.carry_rate,
            hurdle_rate=self.config.hurdle_rate,
            initial_nav=1.0,
            start_date="2000-01-01",
        )

    # =========================================================================
    # 任务 2.1: 资本配置三轨分配与真实利息结算
    # =========================================================================

    def allocate_capital(self, total_capital: float) -> Dict[str, Any]:
        """
        按照策略轨别对总资本进行合法合规资产分配
        """
        c = float(total_capital)
        if self.config.track == StrategyTrack.PURE_LONG:
            return {
                "track": self.config.track.value,
                "total_capital": c,
                "equity_long_value": c,
                "equity_ratio": 1.00,
                "futures_short_notional": 0.0,
                "futures_ratio": 0.00,
                "cash_buffer_value": 0.0,
                "cash_ratio": 0.00,
                "gross_leverage": 1.00,
                "net_exposure_ratio": 1.00,
            }
        elif self.config.track == StrategyTrack.CLASSIC_HEDGE:
            return {
                "track": self.config.track.value,
                "total_capital": c,
                "equity_long_value": c,
                "equity_ratio": 1.00,
                "futures_short_notional": c,
                "futures_ratio": -1.00,
                "cash_buffer_value": 0.0,
                "cash_ratio": 0.00,
                "gross_leverage": 2.00,
                "net_exposure_ratio": 0.00,
            }
        else:  # StrategyTrack.INSTITUTIONAL_75_25
            equity_val = round(c * 0.75, 2)
            futures_notional = round(c * 0.75, 2)
            cash_val = round(c * 0.25, 2)
            return {
                "track": self.config.track.value,
                "total_capital": c,
                "equity_long_value": equity_val,
                "equity_ratio": 0.75,
                "futures_short_notional": futures_notional,
                "futures_ratio": -0.75,
                "cash_buffer_value": cash_val,
                "cash_ratio": 0.25,
                "gross_leverage": 1.75,
                "net_exposure_ratio": 0.00,
            }

    # =========================================================================
    # 任务 2.3: 微观调仓执行与非线性流动性冲击精算
    # =========================================================================

    def evaluate_rebalance_execution(
        self,
        orders: List[Dict[str, Any]],
        adv_map: Dict[str, float],
        volatility_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        精算组合调仓微观执行滑点 (Square-Root Law) 与拆单需求
        
        Args:
            orders: [{"symbol": "600519.SH", "volume_shares": 50000, "price": 1800.0}, ...]
            adv_map: {"600519.SH": 1_000_000, ...}
            volatility_map: {"600519.SH": 0.022, ...} (可选)
        """
        vol_map = volatility_map or {}
        detailed_executions = []
        total_order_notional = 0.0
        total_slippage_cost_rmb = 0.0
        slicing_required_count = 0

        for o in orders:
            sym = o["symbol"]
            vol = float(o["volume_shares"])
            px = float(o.get("price", 10.0))
            notional = vol * px
            total_order_notional += notional

            adv = float(adv_map.get(sym, vol * 10.0))
            sigma = float(vol_map.get(sym, 0.02))

            # 1. 冲击与拆单判定
            pov_eval = self.impact_model.evaluate_pov_and_slicing_requirement(vol, adv)
            if pov_eval["requires_multi_day_slicing"]:
                slicing_required_count += 1

            # 2. 滑点基点精算
            # 若拆单平滑执行，按拆单后日度冲击估算
            effective_vol = vol / pov_eval["recommended_slicing_days"] if pov_eval["requires_multi_day_slicing"] else vol
            slip_bps = self.impact_model.calculate_slippage_bps(effective_vol, adv, sigma)
            slip_cost = notional * (slip_bps / 10000.0)
            total_slippage_cost_rmb += slip_cost

            detailed_executions.append({
                "symbol": sym,
                "order_shares": int(vol),
                "price": px,
                "notional_rmb": round(notional, 2),
                "adv": adv,
                "pov_pct": pov_eval["pov_pct"],
                "requires_slicing": pov_eval["requires_multi_day_slicing"],
                "recommended_days": pov_eval["recommended_slicing_days"],
                "slippage_bps": round(slip_bps, 2),
                "slippage_cost_rmb": round(slip_cost, 2),
            })

        avg_slip_bps = (
            (total_slippage_cost_rmb / total_order_notional) * 10000.0
            if total_order_notional > 0 else 0.0
        )

        return {
            "total_orders": len(orders),
            "total_order_notional_rmb": round(total_order_notional, 2),
            "total_slippage_cost_rmb": round(total_slippage_cost_rmb, 2),
            "volume_weighted_slippage_bps": round(avg_slip_bps, 2),
            "slicing_required_count": slicing_required_count,
            "detailed_executions": detailed_executions,
        }

    # =========================================================================
    # 任务 2.2: 股指期货多 PB 分仓与动态基差曲面核算
    # =========================================================================

    def plan_futures_hedging_structure(
        self,
        equity_long_notional: float,
        futures_price_points: float = 4000.0,
        num_pb_accounts: int = 3,
    ) -> Dict[str, Any]:
        """
        精算机构 PB 套保分仓方案与合规穿透
        """
        if self.config.track == StrategyTrack.PURE_LONG:
            return {
                "track": self.config.track.value,
                "hedging_required": False,
                "total_short_contracts_needed": 0,
            }

        hedge_ratio = 0.75 if self.config.track == StrategyTrack.INSTITUTIONAL_75_25 else 1.00
        # 对应多头名义市值的 100% 对冲
        allocation_res = self.cffex_engine.design_multi_pb_hedging_allocation(
            aum_rmb=equity_long_notional / (0.75 if self.config.track == StrategyTrack.INSTITUTIONAL_75_25 else 1.00),
            hedge_ratio=hedge_ratio,
            points=futures_price_points,
            contract_type=self.config.futures_contract_type,
            num_accounts=num_pb_accounts,
        )
        return allocation_res

    def generate_roll_over_schedule(self, total_contracts: int) -> List[Any]:
        """生成交割周到期前 5 日阶梯移仓排程 (POV < 2.5%)"""
        return self.cffex_engine.generate_5day_staggered_roll_schedule(total_contracts=total_contracts)

    # =========================================================================
    # 任务 2.1 & 2.2: 日频组合多资产净收益严格结算
    # =========================================================================

    def calculate_daily_gross_return(
        self,
        long_return: float,
        benchmark_return: float,
        spot_price: float = 4000.0,
        futures_price: float = 3980.0,
        days_to_expiry: int = 20,
    ) -> Dict[str, Any]:
        """
        精算单日组合各组分及综合毛收益率 (剔除虚增利息)
        """
        r_long = float(long_return)
        r_bm = float(benchmark_return)

        # 动态基差与贴水拖累计算 (A股贴水导致空头移仓到期承担收敛成本)
        annual_basis_rate = BasisSurfaceModel.calculate_annualized_basis_rate(
            spot_price, futures_price, days_to_expiry
        )
        # 若贴水 (Futures < Spot)，基差率为负，空头端面临持有拖累
        basis_drag_daily = max(0.0, -annual_basis_rate / 252.0) if annual_basis_rate < 0 else 0.0

        daily_deposit = self.config.deposit_annual_rate / 252.0

        if self.config.track == StrategyTrack.PURE_LONG:
            r_gross = r_long
            attribution = {
                "equity_contrib": r_long,
                "futures_contrib": 0.0,
                "basis_drag": 0.0,
                "deposit_contrib": 0.0,
            }
        elif self.config.track == StrategyTrack.CLASSIC_HEDGE:
            daily_roll = 0.025 / 252.0
            r_gross = r_long - r_bm - daily_roll
            attribution = {
                "equity_contrib": r_long,
                "futures_contrib": -r_bm,
                "basis_drag": -daily_roll,
                "deposit_contrib": 0.0,
            }
        else:  # StrategyTrack.INSTITUTIONAL_75_25
            equity_c = 0.75 * r_long
            futures_c = -0.75 * r_bm
            basis_d = -0.75 * (basis_drag_daily if basis_drag_daily > 0 else (self.config.annual_basis_drag / 252.0))
            deposit_c = 0.25 * daily_deposit
            r_gross = equity_c + futures_c + basis_d + deposit_c
            attribution = {
                "equity_contrib": round(equity_c, 6),
                "futures_contrib": round(futures_c, 6),
                "basis_drag": round(basis_d, 6),
                "deposit_contrib": round(deposit_c, 6),
            }

        return {
            "track": self.config.track.value,
            "daily_gross_return": round(r_gross, 6),
            "attribution": attribution,
        }

    # =========================================================================
    # 任务 2.4: 跨资产 Saga 补偿与熔断防线
    # =========================================================================

    def compensate_execution_anomaly(
        self,
        stock_symbol: str,
        unfilled_shares: int,
        reason: str,
        current_equity_delta: float,
        current_futures_delta: float,
        available_inventory_shares: int = 0,
        stock_price: float = 100.0,
    ) -> CompensationAction:
        """
        触发 Saga 四级补偿机制
        """
        # 前置检查 Kill Switch
        self.kill_switch.check()

        action = self.saga_coordinator.evaluate_and_route_compensation(
            stock_symbol=stock_symbol,
            unfilled_shares=unfilled_shares,
            reason=reason,
            current_equity_delta=current_equity_delta,
            current_futures_delta=current_futures_delta,
            available_inventory_shares=available_inventory_shares,
            stock_price=stock_price,
        )
        return action
