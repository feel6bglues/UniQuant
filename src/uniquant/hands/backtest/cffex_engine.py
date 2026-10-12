"""
CFFEX 股指期货撮合中枢、保证金核算与到期移仓风控引擎 (CFFEX Engine)
=============================================================================
遵循中金所交易规则与机构套保风控规范 (符合 CNMM-QAR 生产级蓝图 5.4 节设计):
1. 支持中金所四大股指期货品种: IF(300元/点)、IC(200元/点)、IM(200元/点)、IH(300元/点);
2. 每日无负债逐日盯市结算 (MTM, Mark-to-Market): 持仓盈亏、平仓盈亏与结算准备金分账;
3. 机构 PB 套保多账户分仓架构 (破除常规单客户号 1,200 手限仓, 1,042+1,042+1,041 手平分);
4. 到期前 5 日平稳阶梯移仓排程 (10%-20%-20%-25%-25%), 全流程约束单日最大 POV < 2.5%;
5. 保证金动态监控与追保/强平警戒线 (交易所 12%~15%, 券商 PB 15%~18%, 风险缓冲金 5%)。
=============================================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any


class FuturesContractType(str, Enum):
    IF = "IF"  # 沪深300股指期货 (300元/点)
    IC = "IC"  # 中证500股指期货 (200元/点)
    IM = "IM"  # 中证1000股指期货 (200元/点)
    IH = "IH"  # 上证50股指期货 (300元/点)


@dataclass(frozen=True)
class ContractSpec:
    """中金所期货合约规格参数"""
    symbol_prefix: FuturesContractType
    multiplier: float          # 合约乘数 (元/点)
    tick_size: float           # 最小变动价位 (点)
    exchange_margin_ratio: float  # 交易所最低保证金率 (如 0.12 或 0.15)
    broker_margin_ratio: float    # 券商 PB 保证金率 (如 0.15 或 0.18)
    speculative_limit: int = 1200 # 常规客户号单边投机限仓 (手)


# 中金所官方合约乘数与基准参数映射
CONTRACT_SPECS: Dict[FuturesContractType, ContractSpec] = {
    FuturesContractType.IF: ContractSpec(
        symbol_prefix=FuturesContractType.IF,
        multiplier=300.0,
        tick_size=0.2,
        exchange_margin_ratio=0.12,
        broker_margin_ratio=0.15,
        speculative_limit=1200,
    ),
    FuturesContractType.IC: ContractSpec(
        symbol_prefix=FuturesContractType.IC,
        multiplier=200.0,
        tick_size=0.2,
        exchange_margin_ratio=0.15,
        broker_margin_ratio=0.18,
        speculative_limit=1200,
    ),
    FuturesContractType.IM: ContractSpec(
        symbol_prefix=FuturesContractType.IM,
        multiplier=200.0,
        tick_size=0.2,
        exchange_margin_ratio=0.15,
        broker_margin_ratio=0.18,
        speculative_limit=1200,
    ),
    FuturesContractType.IH: ContractSpec(
        symbol_prefix=FuturesContractType.IH,
        multiplier=300.0,
        tick_size=0.2,
        exchange_margin_ratio=0.12,
        broker_margin_ratio=0.15,
        speculative_limit=1200,
    ),
}


@dataclass
class FuturesPosition:
    """单一合约持仓头寸"""
    symbol: str
    contract_type: FuturesContractType
    side: str  # "LONG" 或 "SHORT"
    contracts: int = 0
    open_avg_price: float = 0.0
    last_settlement_price: float = 0.0
    margin_held: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class PBSubAccount:
    """机构 PB 独立套保子账户"""
    account_id: str
    account_name: str
    broker_name: str
    allocated_contracts: int
    allocated_notional_rmb: float
    speculative_limit: int = 1200
    hedging_quota_approved: int = 1100
    utilization_pct: float = 0.0
    is_compliant: bool = True

    def __post_init__(self):
        self.utilization_pct = round(
            (self.allocated_contracts / self.speculative_limit) * 100.0, 2
        )
        self.is_compliant = self.allocated_contracts <= self.speculative_limit


@dataclass
class DailyMTMSettlementReport:
    """每日逐日盯市结算对账单"""
    date: str
    account_id: str
    initial_cash: float
    deposit_withdrawal: float
    realized_trading_pnl: float
    unrealized_holding_pnl: float
    total_commission: float
    ending_cash: float
    total_margin_used: float
    available_funds: float
    margin_ratio_pct: float       # 保证金占用比率
    is_margin_call: bool          # 是否触发追加保证金通知
    margin_call_amount: float     # 应追保金额


@dataclass
class DailyRollPlan:
    """阶梯跨期移仓日度计划"""
    day_index: int                       # 1 到 5 (T-4 到 T-0)
    day_label: str                       # T-4, T-3, T-2, T-1, T-0
    target_ratio_pct: float              # 10%, 20%, 20%, 25%, 25%
    planned_contracts: int               # 每日计划移仓手数
    cum_contracts: int                   # 累计移仓手数
    cum_ratio_pct: float                 # 累计百分比
    front_contract_adv: int              # 即期主力合约日均成交量 (手)
    next_contract_adv: int               # 次月合约日均成交量 (手)
    spread_market_adv: int               # 跨期价差综合成交量 (手)
    front_pov_pct: float                 # 移仓量占主力成交量比例
    next_pov_pct: float                  # 移仓量占次月成交量比例
    spread_pov_pct: float                # 移仓量占价差综合成交量比例
    max_contract_pov_pct: float          # 当日单合约最大 POV
    is_pov_strictly_below_2_5pct: bool   # 是否严格低于 2.5% 警戒线


class CFFEXMatchingAndRiskEngine:
    """
    CFFEX 股指期货撮合、保证金与风控中枢
    
    核心职责:
    1. 维护中金所标准合约规格 (乘数、跳价、保证金);
    2. 每日逐日盯市 (Mark-to-Market, MTM) 结算盈亏分账核算;
    3. 多账户 PB 套保分仓方案生成与穿透限仓审计;
    4. 5 日平稳阶梯跨期移仓排程与微观市场冲击 POV 约束校验。
    """

    def __init__(
        self,
        account_id: str = "CFFEX_MASTER_PB",
        initial_cash: float = 50_000_000.0,
        risk_buffer_ratio: float = 0.05,
    ):
        self.account_id = account_id
        self.cash = float(initial_cash)
        self.risk_buffer_ratio = float(risk_buffer_ratio)
        self.positions: Dict[str, FuturesPosition] = {}
        self.settlement_history: List[DailyMTMSettlementReport] = []

    @staticmethod
    def get_spec(contract_type: FuturesContractType) -> ContractSpec:
        """获取合约规格参数"""
        if contract_type not in CONTRACT_SPECS:
            raise ValueError(f"未知期货品种代码: {contract_type}")
        return CONTRACT_SPECS[contract_type]

    @staticmethod
    def calculate_notional(
        contract_type: FuturesContractType,
        points: float,
        contracts: int,
    ) -> float:
        """计算合约名义市值 (Notional Value = 点位 × 乘数 × 手数)"""
        spec = CFFEXMatchingAndRiskEngine.get_spec(contract_type)
        return float(points) * spec.multiplier * abs(int(contracts))

    @staticmethod
    def calculate_margin_required(
        contract_type: FuturesContractType,
        settlement_price: float,
        contracts: int,
        use_broker_rate: bool = True,
    ) -> float:
        """
        计算单合约持仓保证金占用
        Margin = 结算价 × 乘数 × 手数 × 保证金率
        """
        spec = CFFEXMatchingAndRiskEngine.get_spec(contract_type)
        margin_rate = spec.broker_margin_ratio if use_broker_rate else spec.exchange_margin_ratio
        return float(settlement_price) * spec.multiplier * abs(int(contracts)) * margin_rate

    # =========================================================================
    # 多 PB 账户套保分仓精算 (突破 1,200 手限仓)
    # =========================================================================

    @staticmethod
    def design_multi_pb_hedging_allocation(
        aum_rmb: float = 5_000_000_000.0,
        hedge_ratio: float = 0.75,
        points: float = 4000.0,
        contract_type: FuturesContractType = FuturesContractType.IF,
        num_accounts: int = 3,
    ) -> Dict[str, Any]:
        """
        精算 50 亿 AUM 下多 PB 账户套保分仓方案
        
        数理逻辑:
        1. 50 亿 × 75% = 37.5 亿元名义空头对冲需求;
        2. IF 单手合约价值 = 4000 点 × 300 元/点 = 120 万元/手;
        3. 总对冲需求 = 37.5 亿元 / 120 万元 = 3,125 手;
        4. 中金所单一客户号投机限仓 1,200 手, 3,125 手超限 1,925 手 (+160.42%);
        5. 分配给 3 家独立 PB: 1042 + 1042 + 1041 手, 全部 <= 1200 手 (合规率 100%)。
        """
        spec = CFFEXMatchingAndRiskEngine.get_spec(contract_type)
        notional_hedged = float(aum_rmb) * float(hedge_ratio)
        unit_val = float(points) * spec.multiplier
        total_contracts = int(round(notional_hedged / unit_val))

        base_contracts = total_contracts // num_accounts
        remainder = total_contracts % num_accounts

        account_profiles = [
            ("ACC_ALPHA_01", "CNMM 磐石增强 1 号私募证券投资基金", "中信证券 / 中信期货 PB 席位"),
            ("ACC_BETA_02", "CNMM 稳健对冲 2 号集合资产管理计划", "国泰君安证券 / 国泰君安期货 PB 席位"),
            ("ACC_GAMMA_03", "CNMM 远见对冲 3 号专属投资账户", "华泰证券 / 华泰期货 PB 席位"),
        ]

        allocations: List[PBSubAccount] = []
        total_allocated = 0

        for i in range(num_accounts):
            acc_id, acc_name, broker = account_profiles[i % len(account_profiles)]
            extra = 1 if i < remainder else 0
            n_c = base_contracts + extra
            notional = n_c * unit_val
            alloc = PBSubAccount(
                account_id=acc_id,
                account_name=acc_name,
                broker_name=broker,
                allocated_contracts=n_c,
                allocated_notional_rmb=round(notional, 2),
                speculative_limit=spec.speculative_limit,
                hedging_quota_approved=1100,
            )
            allocations.append(alloc)
            total_allocated += n_c

        assert total_allocated == total_contracts

        all_compliant = all(a.is_compliant for a in allocations)
        exceeds_single_account = total_contracts > spec.speculative_limit
        excess_over_limit = max(0, total_contracts - spec.speculative_limit)

        return {
            "aum_rmb": aum_rmb,
            "hedge_ratio": hedge_ratio,
            "notional_hedged_rmb": notional_hedged,
            "contract_type": contract_type.value,
            "multiplier": spec.multiplier,
            "unit_value_rmb": unit_val,
            "total_short_contracts_needed": total_contracts,
            "single_account_speculative_limit": spec.speculative_limit,
            "exceeds_single_account_limit": exceeds_single_account,
            "excess_contracts_over_limit": excess_over_limit,
            "regulatory_violation_risk": "CRITICAL" if exceeds_single_account else "SAFE",
            "num_accounts": num_accounts,
            "all_accounts_within_speculative_limit": all_compliant,
            "accounts": [asdict(a) for a in allocations],
        }

    # =========================================================================
    # 到期前 5 日阶梯平稳展期排程 (POV < 2.5%)
    # =========================================================================

    @staticmethod
    def generate_5day_staggered_roll_schedule(
        total_contracts: int = 3125,
        market_adv_profiles: Optional[List[Tuple[int, int, int]]] = None,
    ) -> List[DailyRollPlan]:
        """
        到期前 5 日阶梯平稳展期算法 (10%-20%-20%-25%-25%)
        
        Args:
            total_contracts: 需展期总手数 (如 3125 手)
            market_adv_profiles: 5 日 (主力ADV, 次月ADV, 价差ADV) 序列
            
        Returns:
            List[DailyRollPlan]: 包含逐日移仓量与主力/次月/价差 POV 精算结果
        """
        ratios = [0.10, 0.20, 0.20, 0.25, 0.25]
        assert len(ratios) == 5

        # 默认中金所交割周历史流动性实证基准 (Front ADV, Next ADV, Spread ADV)
        if market_adv_profiles is None:
            market_adv_profiles = [
                (92_000, 35_000, 127_000),  # T-4 周一
                (85_000, 48_000, 133_000),  # T-3 周二
                (70_000, 62_000, 132_000),  # T-2 周三
                (52_000, 78_000, 130_000),  # T-1 周四
                (36_000, 92_000, 128_000),  # T-0 周五 (交割日)
            ]

        # 整除精算与尾单配平: [312, 625, 625, 781, 782]
        daily_contracts = [
            int(math.floor(total_contracts * 0.10)),
            int(round(total_contracts * 0.20)),
            int(round(total_contracts * 0.20)),
            int(math.floor(total_contracts * 0.25)),
            0,
        ]
        daily_contracts[4] = total_contracts - sum(daily_contracts[:4])
        assert sum(daily_contracts) == total_contracts

        day_labels = [
            "T-4 (交割周周一, 移仓启动)",
            "T-3 (交割周周二, 稳步提速)",
            "T-2 (交割周周三, 跨期中枢)",
            "T-1 (交割周周四, 主力切换)",
            "T-0 (交割周周五, 到期交割收尾)",
        ]

        plans: List[DailyRollPlan] = []
        cum_contracts = 0

        for day_idx in range(5):
            c_rolled = daily_contracts[day_idx]
            cum_contracts += c_rolled
            cum_ratio = (cum_contracts / total_contracts) * 100.0

            front_adv, next_adv, spread_adv = market_adv_profiles[day_idx]
            front_pov = (c_rolled / front_adv) * 100.0
            next_pov = (c_rolled / next_adv) * 100.0
            spread_pov = (c_rolled / spread_adv) * 100.0
            max_pov = max(front_pov, next_pov)

            is_compliant = max_pov < 2.5

            plan = DailyRollPlan(
                day_index=day_idx + 1,
                day_label=day_labels[day_idx],
                target_ratio_pct=round(ratios[day_idx] * 100.0, 1),
                planned_contracts=c_rolled,
                cum_contracts=cum_contracts,
                cum_ratio_pct=round(cum_ratio, 2),
                front_contract_adv=front_adv,
                next_contract_adv=next_adv,
                spread_market_adv=spread_adv,
                front_pov_pct=round(front_pov, 3),
                next_pov_pct=round(next_pov, 3),
                spread_pov_pct=round(spread_pov, 3),
                max_contract_pov_pct=round(max_pov, 3),
                is_pov_strictly_below_2_5pct=is_compliant,
            )
            plans.append(plan)

        return plans

    # =========================================================================
    # 每日无负债逐日盯市结算 (Mark-to-Market, MTM)
    # =========================================================================

    def perform_daily_mtm_settlement(
        self,
        date: str,
        settlement_prices: Dict[str, float],
        intraday_trades: Optional[List[Dict[str, Any]]] = None,
        deposit_withdrawal: float = 0.0,
    ) -> DailyMTMSettlementReport:
        """
        中金所标准每日逐日盯市结算 (Mark-to-Market)
        
        结算流程:
        1. 结算当日日内平仓盈亏:
           PnL_close = (平仓价 - 开仓价/昨结算) × 乘数 × 手数 (空头反号)
        2. 结算历史持仓盈亏:
           PnL_holding = (昨结算价 - 今结算价) × 乘数 × 空头手数
        3. 划转手续费与出入金;
        4. 更新持仓保证金占用 (Margin Held = 今结算价 × 乘数 × 持仓手数 × PB保证金率);
        5. 计算可用资金与风险度 (Margin Ratio = 占用保证金 / 客户权益);
        6. 风险度 > 100% 触发追保通知 (Margin Call)。
        """
        initial_cash = self.cash
        self.cash += deposit_withdrawal

        realized_pnl = 0.0
        total_comm = 0.0

        # 处理日内交易 (开仓 / 平仓)
        if intraday_trades:
            for t in intraday_trades:
                sym = t["symbol"]
                c_type = FuturesContractType(t.get("contract_type", sym[:2]))
                spec = self.get_spec(c_type)
                side = t["side"]  # "BUY" 或 "SELL"
                action = t.get("action", "OPEN")  # "OPEN" 或 "CLOSE"
                contracts = int(t["contracts"])
                price = float(t["price"])
                comm = float(t.get("commission", 0.0))
                total_comm += comm

                if sym not in self.positions:
                    self.positions[sym] = FuturesPosition(
                        symbol=sym,
                        contract_type=c_type,
                        side=side,
                        contracts=0,
                        open_avg_price=price,
                        last_settlement_price=price,
                    )
                pos = self.positions[sym]

                if action == "OPEN":
                    new_c = pos.contracts + contracts
                    pos.open_avg_price = (
                        (pos.open_avg_price * pos.contracts + price * contracts) / new_c
                        if new_c > 0 else price
                    )
                    pos.contracts = new_c
                    pos.side = side
                elif action == "CLOSE":
                    # 平仓计算实现盈亏
                    sign = 1.0 if pos.side == "LONG" else -1.0
                    trade_pnl = (price - pos.last_settlement_price) * spec.multiplier * contracts * sign
                    realized_pnl += trade_pnl
                    pos.contracts -= contracts
                    if pos.contracts <= 0:
                        pos.contracts = 0

        self.cash += realized_pnl - total_comm

        # 计算持仓盈亏并更新保证金占用
        unrealized_holding_pnl = 0.0
        total_margin_used = 0.0

        for sym, pos in list(self.positions.items()):
            if pos.contracts <= 0:
                continue
            settle_p = settlement_prices.get(sym, pos.last_settlement_price)
            spec = self.get_spec(pos.contract_type)

            # 持仓盯市盈亏
            sign = 1.0 if pos.side == "LONG" else -1.0
            holding_pnl = (settle_p - pos.last_settlement_price) * spec.multiplier * pos.contracts * sign
            unrealized_holding_pnl += holding_pnl
            pos.unrealized_pnl = holding_pnl
            pos.last_settlement_price = settle_p

            # 重新核定保证金
            pos.margin_held = self.calculate_margin_required(
                pos.contract_type, settle_p, pos.contracts, use_broker_rate=True
            )
            total_margin_used += pos.margin_held

        # 逐日无负债结算: 浮动持仓盈亏当日结清并入动态权益
        # 在中金所逐日盯市下，持仓盈亏每日划转计入现金准备金
        self.cash += unrealized_holding_pnl

        # 客户总权益 (Equity) = 现金准备金余额
        client_equity = self.cash
        available_funds = client_equity - total_margin_used
        margin_ratio_pct = (total_margin_used / client_equity * 100.0) if client_equity > 0 else 999.0

        # 风控追保判定 (可用资金 < 0 或 风险度 > 100%)
        is_margin_call = available_funds < 0
        margin_call_amount = abs(available_funds) if is_margin_call else 0.0

        report = DailyMTMSettlementReport(
            date=date,
            account_id=self.account_id,
            initial_cash=round(initial_cash, 2),
            deposit_withdrawal=round(deposit_withdrawal, 2),
            realized_trading_pnl=round(realized_pnl, 2),
            unrealized_holding_pnl=round(unrealized_holding_pnl, 2),
            total_commission=round(total_comm, 2),
            ending_cash=round(self.cash, 2),
            total_margin_used=round(total_margin_used, 2),
            available_funds=round(available_funds, 2),
            margin_ratio_pct=round(margin_ratio_pct, 2),
            is_margin_call=is_margin_call,
            margin_call_amount=round(margin_call_amount, 2),
        )
        self.settlement_history.append(report)
        return report
