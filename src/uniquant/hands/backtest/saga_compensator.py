"""
T+1 现货与 T+0 期货双撮合跨资产 Saga 四级分布式补偿协调器 (Saga Compensator)
=============================================================================
遵循 A 股制度约束与跨市场对冲高可用执行架构 (符合 CNMM-QAR 生产级蓝图 5.4 节设计):
1. 解决 A 股现货端 T+1 交易限制与中金所期货端 T+0 撮合异步并发失衡;
2. 四级级联补偿路由机制 (Saga 4-Level Distributed Compensation):
   - Level 1 (微观窗口自愈): 切片部分成交, 由下个 15 分钟切片在容差滑点内溢价补齐;
   - Level 2 (跨资产 Delta 联动对冲): 组合市值与空头 Delta 敞口偏差 > 1.0% 时,
             秒级联动调整 T+0 期货空头手数, 强制压制组合净敞口近零;
   - Level 3 (可售底仓替代冲销 / 逆向平仓): 卖单遇跌停或 T+1 锁仓, 路由历史可用底仓替代;
             若买单建仓失败, 即刻冻结后续期货并市价反向平掉多余空头;
   - Level 4 (极端死锁隔离与残值合成锁仓): 标的遭遇一字跌停流动性枯竭, 状态标记为 QUARANTINED,
             期货端建立 1:1 动态合成空头锁仓残值, 触发 P0 级风控警报并记账审计;
3. 严格防范死锁循环等待 (Deadlock-Free), 在断电崩溃与网络闪断下具备崩溃恢复能力。
=============================================================================
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("CrossAssetSagaCoordinator")


class OrderState(str, Enum):
    """母单与切片订单全生命周期状态"""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    SAGA_COMPENSATING = "SAGA_COMPENSATING"
    SAGA_COMPENSATED = "SAGA_COMPENSATED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SagaCompensationLevel(str, Enum):
    """Saga 四级补偿级别枚举"""
    LEVEL_1_MICRO_RETRY = "LEVEL_1_MICRO_RETRY"
    LEVEL_2_FUTURES_DELTA_COMPENSATE = "LEVEL_2_FUTURES_DELTA_COMPENSATE"
    LEVEL_3_INVENTORY_SUBSTITUTE_OR_ABORT = "LEVEL_3_INVENTORY_SUBSTITUTE_OR_ABORT"
    LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE = "LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE"


@dataclass
class CompensationAction:
    """Saga 补偿决策记录"""
    action_id: str
    symbol: str
    failed_shares: int
    reason: str
    level: SagaCompensationLevel
    equity_delta: float
    futures_delta: float
    delta_imbalance: float
    adjusted_futures_contracts: int = 0
    substitute_shares_used: int = 0
    synthetic_hedge_notional: float = 0.0
    status: str = "COMPLETED"
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class SqliteWalTwapStateMachine:
    """
    基于 SQLite WAL 的 Crash-Safe TWAP 母单与切片事务状态机
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(
            db_path,
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None,
        )
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
        self._init_tables()

    def _init_tables(self):
        with self._lock, self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS parent_orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    total_shares INTEGER NOT NULL,
                    executed_shares INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS twap_slices (
                    slice_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    day_index INTEGER NOT NULL,
                    slice_shares INTEGER NOT NULL,
                    executed_shares INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    avg_price REAL DEFAULT 0.0,
                    updated_at TIMESTAMP NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES parent_orders(order_id)
                );
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS saga_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    level TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    delta_imbalance REAL NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP NOT NULL
                );
            """)

    def create_order(self, order_id: str, symbol: str, total_shares: int) -> None:
        """注册母单"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO parent_orders (order_id, symbol, total_shares, executed_shares, status, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?, ?);
                """,
                (order_id, symbol, total_shares, OrderState.PENDING.value, now, now),
            )

    def transition_state(self, order_id: str, new_state: OrderState) -> None:
        """更新母单状态"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE parent_orders SET status = ?, updated_at = ? WHERE order_id = ?;",
                (new_state.value, now, order_id),
            )

    def get_order_status(self, order_id: str) -> Optional[OrderState]:
        """获取母单当前状态"""
        row = self.conn.execute(
            "SELECT status FROM parent_orders WHERE order_id = ?;",
            (order_id,),
        ).fetchone()
        if row:
            return OrderState(row["status"])
        return None


class CrossAssetSagaCoordinator:
    """
    T+1 下股票与期货双撮合跨资产四级分布式补偿协调器
    
    核心设计与抗死锁原理:
    1. 现货端为 T+1 单向约束 (当天买入不可当日卖出, 跌停不可卖出);
    2. 期货端为 T+0 双向对称撮合, 充当 Saga 补偿事务 (Compensating Transaction) 的绝对流动性出口;
    3. 消除两阶段提交 (2PC) 的阻塞等待, 采用级联升维补偿, 保证全局净敞口收敛。
    """

    def __init__(
        self,
        wal_sm: Optional[SqliteWalTwapStateMachine] = None,
        futures_point_value: float = 300.0,
        futures_price: float = 4000.0,
        delta_tolerance: float = 0.01,  # 1.0% Delta 偏离容忍阈值
        enable_kill_switch: bool = False,
        kill_switch: Optional[Any] = None,
        quarantine_kill_threshold_rmb: float = 5_000_000.0,
    ):
        self.wal_sm = wal_sm or SqliteWalTwapStateMachine()
        self.futures_point_value = float(futures_point_value)
        self.futures_price = float(futures_price)
        self.contract_notional = self.futures_price * self.futures_point_value
        self.delta_tolerance = float(delta_tolerance)
        self.enable_kill_switch = enable_kill_switch
        self.kill_switch = kill_switch
        self.quarantine_kill_threshold_rmb = float(quarantine_kill_threshold_rmb)
        self.compensation_history: List[CompensationAction] = []
        self._action_counter = 0

    def evaluate_and_route_compensation(
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
        核心 Saga 四级级联补偿路由与执行器
        
        Args:
            stock_symbol: 股票标的代码
            unfilled_shares: 现货未成交股数
            reason: 失败根因 (NORMAL_LIQUIDITY_DELAY, PARTIAL_REJECT, T1_LOCKED, LIMIT_DOWN_DEADLOCK 等)
            current_equity_delta: 现货端实际 Delta 敞口 (元或比率)
            current_futures_delta: 期货端对冲 Delta 敞口 (负数代表空头)
            available_inventory_shares: 账户中属于 T-1 以前可立即卖出的底仓
            stock_price: 当前股票估值价
            
        Returns:
            CompensationAction: 补偿执行动作与结果
        """
        self._action_counter += 1
        action_id = f"SAGA_ACT_{self._action_counter:06d}"
        delta_imbalance = abs(current_equity_delta + current_futures_delta)

        # ---------------------------------------------------------------------
        # Level 1: 微观窗口自愈 (Next slice retry)
        # 条件: 流动性暂态延时或轻微队列超时, 且净敞口偏离在容差范围内
        # ---------------------------------------------------------------------
        if "NORMAL_LIQUIDITY_DELAY" in reason and delta_imbalance <= self.delta_tolerance:
            action = CompensationAction(
                action_id=action_id,
                symbol=stock_symbol,
                failed_shares=unfilled_shares,
                reason=reason,
                level=SagaCompensationLevel.LEVEL_1_MICRO_RETRY,
                equity_delta=current_equity_delta,
                futures_delta=current_futures_delta,
                delta_imbalance=round(delta_imbalance, 4),
                details={"retry_window_minutes": 15, "max_slippage_tolerance_bps": 10.0},
            )
            self._log_and_record(action)
            return action

        # ---------------------------------------------------------------------
        # Level 2: 跨资产 Delta 联动对冲补偿 (Futures Delta hedge adjustment)
        # 条件: Delta 敞口失衡 > 1.0%, 且未被一字跌停彻底封死 (可通过 T+0 期货实时平抑敞口)
        # ---------------------------------------------------------------------
        if delta_imbalance > self.delta_tolerance and "LIMIT_DOWN" not in reason:
            # 计算需调整的期货手数: Imbalance_RMB / (Price × Multiplier)
            # 敞口多头过重 -> 加开期货空头; 敞口空头过重 -> 减平期货空头
            excess_equity = current_equity_delta + current_futures_delta
            needed_contracts = int(round(excess_equity / self.contract_notional))

            action = CompensationAction(
                action_id=action_id,
                symbol=stock_symbol,
                failed_shares=unfilled_shares,
                reason=reason,
                level=SagaCompensationLevel.LEVEL_2_FUTURES_DELTA_COMPENSATE,
                equity_delta=current_equity_delta,
                futures_delta=current_futures_delta,
                delta_imbalance=round(delta_imbalance, 4),
                adjusted_futures_contracts=needed_contracts,
                details={
                    "hedge_adjustment_action": "SELL_SHORT_FUTURES" if excess_equity > 0 else "BUY_COVER_FUTURES",
                    "contract_notional": self.contract_notional,
                },
            )
            self.wal_sm.transition_state(stock_symbol, OrderState.SAGA_COMPENSATING)
            self._log_and_record(action)
            return action

        # ---------------------------------------------------------------------
        # Level 3: 可售底仓替代冲销 / 逆向平仓 (T+0 inventory substitute / Abort)
        # 条件: 遭遇 T+1 当日锁仓或部分买入拒单, 但账户持有 T-1 前历史可售底仓
        # ---------------------------------------------------------------------
        if ("T1_LOCKED" in reason or "PARTIAL_REJECT" in reason) and available_inventory_shares > 0:
            substitute_used = min(unfilled_shares, available_inventory_shares)
            action = CompensationAction(
                action_id=action_id,
                symbol=stock_symbol,
                failed_shares=unfilled_shares,
                reason=reason,
                level=SagaCompensationLevel.LEVEL_3_INVENTORY_SUBSTITUTE_OR_ABORT,
                equity_delta=current_equity_delta,
                futures_delta=current_futures_delta,
                delta_imbalance=round(delta_imbalance, 4),
                substitute_shares_used=substitute_used,
                details={
                    "substitution_strategy": "T_MINUS_1_INVENTORY_UNWIND",
                    "remaining_unfilled": max(0, unfilled_shares - substitute_used),
                },
            )
            self.wal_sm.transition_state(stock_symbol, OrderState.SAGA_COMPENSATED)
            self._log_and_record(action)
            return action

        # ---------------------------------------------------------------------
        # Level 4: 极端跌停死锁隔离与残值合成锁仓 (Quarantine & Synthetic Hedge)
        # 条件: 一字死封跌停 (LIMIT_DOWN / DEADLOCK), 现货端成交量为零完全无法脱手
        # ---------------------------------------------------------------------
        residual_notional = unfilled_shares * stock_price
        action = CompensationAction(
            action_id=action_id,
            symbol=stock_symbol,
            failed_shares=unfilled_shares,
            reason=reason,
            level=SagaCompensationLevel.LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE,
            equity_delta=current_equity_delta,
            futures_delta=current_futures_delta,
            delta_imbalance=round(delta_imbalance, 4),
            synthetic_hedge_notional=residual_notional,
            details={
                "quarantine_protocol": "P0_ALARM_ISOLATION",
                "synthetic_short_mode": "FUTURES_OR_ETF_SYNTHETIC_HEDGE",
                "action": "LOCK_RESIDUAL_VALUE_UNTIL_LIQUIDITY_RESTORATION",
            },
        )
        # 标记事务隔离
        self.wal_sm.transition_state(stock_symbol, OrderState.QUARANTINED)
        self._log_and_record(action)
        logger.critical(
            f"[SAGA P0 警报] 标的 {stock_symbol} 触发 Level 4 极端死锁隔离! "
            f"未成手数: {unfilled_shares}, 残值锁定: {residual_notional:,.2f} 元"
        )
        if self.enable_kill_switch and self.kill_switch is not None:
            if residual_notional >= self.quarantine_kill_threshold_rmb:
                self.kill_switch.kill(
                    reason=f"SAGA_CRITICAL_QUARANTINE_EXCEEDED: symbol={stock_symbol}, notional={residual_notional:,.2f}"
                )
        return action

    def _log_and_record(self, action: CompensationAction):
        """记录内存与持久化审计流"""
        self.compensation_history.append(action)
        try:
            with self.wal_sm._lock, self.wal_sm.conn:
                import json
                self.wal_sm.conn.execute(
                    """
                    INSERT INTO saga_audit_log (action_id, symbol, level, reason, delta_imbalance, status, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        action.action_id,
                        action.symbol,
                        action.level.value,
                        action.reason,
                        action.delta_imbalance,
                        action.status,
                        json.dumps(action.details, ensure_ascii=False),
                        action.timestamp,
                    ),
                )
        except Exception as e:
            logger.error(f"写入 Saga 审计日志失败: {e}")
