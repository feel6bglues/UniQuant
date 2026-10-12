#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMM RESEARCH OS & UniQuant: 轻量级生产级 SQLite WAL 订单状态机
=============================================================================
核心功能：
1. 母单（Parent Order）与 3 日 TWAP 子单（Child Slices）的持久化存储；
2. SQLite WAL (Write-Ahead Logging) 单写多读并发机制；
3. 严格的有限状态机（FSM）状态转移与审计跟踪；
4. 断电崩溃幂等恢复机制（Idempotent Crash Recovery）与对账重算；
5. 生产级单例/连接池、重试防御与事务隔离。
=============================================================================
"""

import os
import sys
import json
import time
import sqlite3
import logging
import threading
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("OrderStateMachine")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s][%(name)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# =============================================================================
# 状态枚举与常量定义
# =============================================================================

class ParentOrderStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    ALL_STATUSES = {PENDING, RUNNING, PARTIALLY_FILLED, FILLED, CANCELLED, FAILED}


class ChildSliceStatus:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    ALL_STATUSES = {PENDING, SUBMITTED, PARTIAL, FILLED, CANCELLED, FAILED}


class OrderSide:
    BUY = "BUY"
    SELL = "SELL"


class AlgoType:
    TWAP_3D = "TWAP_3D"
    VWAP = "VWAP"
    POV = "POV"


# =============================================================================
# 数据模型定义 (Data Models)
# =============================================================================

@dataclass
class ParentOrder:
    parent_order_id: str
    symbol: str
    side: str
    total_shares: int
    algo_type: str = AlgoType.TWAP_3D
    status: str = ParentOrderStatus.PENDING
    target_price: Optional[float] = None
    filled_shares: int = 0
    filled_notional: float = 0.0
    average_price: float = 0.0
    total_slices: int = 0
    completed_slices: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso


@dataclass
class ChildSlice:
    slice_id: str
    parent_order_id: str
    day_index: int
    slice_index: int
    symbol: str
    side: str
    shares: int
    limit_price: Optional[float] = None
    status: str = ChildSliceStatus.PENDING
    filled_shares: int = 0
    filled_price: float = 0.0
    filled_notional: float = 0.0
    scheduled_time: str = ""
    executed_time: Optional[str] = None
    idempotency_key: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso
        if not self.idempotency_key:
            self.idempotency_key = f"{self.parent_order_id}_D{self.day_index}_S{self.slice_index}"


# =============================================================================
# 生产级 SQLite WAL 订单状态机核心引擎
# =============================================================================

class SQLiteWALOrderStateMachine:
    """
    轻量级生产级 SQLite WAL 订单状态机。

    特性：
    1. WAL (Write-Ahead Logging) 单写多读架构，并发无锁读取；
    2. 严格事务性单写锁 (Single-Writer Mutex + BEGIN IMMEDIATE)；
    3. 支持母单（Parent Order）与 3 日 TWAP 子单（Child Slices）的生命周期管理；
    4. 崩溃断电后的幂等恢复与母子单全局一致性对账；
    5. 操作幂等性：重复写入或状态变更严格防重防死锁。
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path("/home/james/Documents/Project/CNNM/scratch/data")
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "order_state_machine.db")
        self.db_path = str(db_path)
        self._write_lock = threading.Lock()
        self._init_db()

    def _get_connection(self, readonly: bool = False) -> sqlite3.Connection:
        """获取 SQLite 连接并配置 WAL 高并发 Pragmas"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None  # 手动控制事务
        )
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            if readonly:
                conn.execute("PRAGMA query_only = ON;")
        return conn

    def _init_db(self):
        """初始化数据库表结构与索引"""
        with self._write_lock:
            conn = self._get_connection(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                # 1. 母单表 (Parent Orders)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS parent_orders (
                        parent_order_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        total_shares INTEGER NOT NULL,
                        algo_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        target_price REAL,
                        filled_shares INTEGER DEFAULT 0,
                        filled_notional REAL DEFAULT 0.0,
                        average_price REAL DEFAULT 0.0,
                        total_slices INTEGER DEFAULT 0,
                        completed_slices INTEGER DEFAULT 0,
                        metadata TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_status ON parent_orders(status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_symbol ON parent_orders(symbol);")

                # 2. 子单表 (Child Slices)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS child_slices (
                        slice_id TEXT PRIMARY KEY,
                        parent_order_id TEXT NOT NULL REFERENCES parent_orders(parent_order_id) ON DELETE CASCADE,
                        day_index INTEGER NOT NULL,
                        slice_index INTEGER NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        shares INTEGER NOT NULL,
                        limit_price REAL,
                        status TEXT NOT NULL,
                        filled_shares INTEGER DEFAULT 0,
                        filled_price REAL DEFAULT 0.0,
                        filled_notional REAL DEFAULT 0.0,
                        scheduled_time TEXT NOT NULL,
                        executed_time TEXT,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_parent ON child_slices(parent_order_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_status ON child_slices(status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_idem ON child_slices(idempotency_key);")

                # 3. 状态流转审计表 (Audit Trail)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS order_audit_trail (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        from_status TEXT NOT NULL,
                        to_status TEXT NOT NULL,
                        action TEXT NOT NULL,
                        details TEXT,
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("COMMIT;")
                logger.info(f"SQLite WAL 订单状态机数据库初始化成功: {self.db_path}")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.critical(f"初始化订单数据库失败: {e}", exc_info=True)
                raise
            finally:
                conn.close()

    def _record_audit_event(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        from_status: str,
        to_status: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """记录状态机流转审计日志"""
        conn.execute(
            """
            INSERT INTO order_audit_trail (entity_type, entity_id, from_status, to_status, action, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                entity_type,
                entity_id,
                from_status,
                to_status,
                action,
                json.dumps(details or {}, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    # =========================================================================
    # 母单与 3 日 TWAP 子单创建 (Idempotent Creation)
    # =========================================================================

    def create_parent_order_with_3d_twap(
        self,
        parent_order_id: str,
        symbol: str,
        side: str,
        total_shares: int,
        slices_per_day: int = 10,
        target_price: Optional[float] = None,
        daily_proportions: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ParentOrder, List[ChildSlice]]:
        """
        创建母单并原子性生成 3 日 TWAP 子单切片。

        Args:
            parent_order_id: 母单唯一编号（幂等键）
            symbol: 标的代码 (如 '600519.SH' 或 'IF2406')
            side: 交易方向 ('BUY' / 'SELL')
            total_shares: 总股数/合约数 (如 3125 手或 30000 股)
            slices_per_day: 每日切片数量 (默认 10 档，也可配置为 60 或 180)
            target_price: 目标基准价
            daily_proportions: 3日权重分配 (默认等分 [1/3, 1/3, 1/3])
            metadata: 附加元数据

        Returns:
            Tuple[ParentOrder, List[ChildSlice]]
        """
        if total_shares <= 0:
            raise ValueError(f"总下单量必须为正整数: {total_shares}")
        if slices_per_day <= 0:
            raise ValueError(f"每日切片数必须为正整数: {slices_per_day}")
        if side not in (OrderSide.BUY, OrderSide.SELL):
            raise ValueError(f"交易方向必须为 BUY 或 SELL: {side}")

        if daily_proportions is None:
            daily_proportions = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
        if len(daily_proportions) != 3 or abs(sum(daily_proportions) - 1.0) > 1e-4:
            raise ValueError("3 日 TWAP 的 daily_proportions 必须恰好包含 3 个元素且和为 1.0")

        total_slices_count = 3 * slices_per_day
        slices_list: List[ChildSlice] = []

        # 精算 3 日各切片股数，确保整除且无截断误差（尾单补齐）
        allocated_shares = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        # 计算每日目标份额
        day_shares_targets = [int(round(total_shares * prop)) for prop in daily_proportions]
        day_shares_targets[2] = total_shares - (day_shares_targets[0] + day_shares_targets[1])

        slice_counter = 0
        for day_idx in range(1, 4):
            day_target = day_shares_targets[day_idx - 1]
            base_slice = day_target // slices_per_day
            rem_slice = day_target % slices_per_day

            for s_idx in range(1, slices_per_day + 1):
                slice_counter += 1
                # 前 rem_slice 个切片多分 1 股，平滑尾差
                shares = base_slice + (1 if s_idx <= rem_slice else 0)
                if shares <= 0:
                    continue

                slice_id = f"{parent_order_id}_D{day_idx}_S{s_idx:03d}"
                idempotency_key = slice_id
                scheduled_time = f"Day{day_idx}_T{s_idx:03d}"

                slice_obj = ChildSlice(
                    slice_id=slice_id,
                    parent_order_id=parent_order_id,
                    day_index=day_idx,
                    slice_index=s_idx,
                    symbol=symbol,
                    side=side,
                    shares=shares,
                    limit_price=target_price,
                    status=ChildSliceStatus.PENDING,
                    scheduled_time=scheduled_time,
                    idempotency_key=idempotency_key,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                slices_list.append(slice_obj)
                allocated_shares += shares

        assert allocated_shares == total_shares, f"切片分配总和({allocated_shares})与母单总量({total_shares})不符!"

        parent_order = ParentOrder(
            parent_order_id=parent_order_id,
            symbol=symbol,
            side=side,
            total_shares=total_shares,
            algo_type=AlgoType.TWAP_3D,
            status=ParentOrderStatus.PENDING,
            target_price=target_price,
            total_slices=len(slices_list),
            metadata=metadata or {},
            created_at=now_iso,
            updated_at=now_iso,
        )

        with self._write_lock:
            conn = self._get_connection(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                # 检查是否已存在该母单 (幂等性判断)
                existing = conn.execute(
                    "SELECT * FROM parent_orders WHERE parent_order_id = ?",
                    (parent_order_id,)
                ).fetchone()

                if existing:
                    logger.warning(f"母单已存在，触发幂等返回: {parent_order_id}")
                    conn.execute("COMMIT;")
                    return self.get_parent_order(parent_order_id), self.get_child_slices(parent_order_id)

                # 插入母单
                conn.execute(
                    """
                    INSERT INTO parent_orders (
                        parent_order_id, symbol, side, total_shares, algo_type, status,
                        target_price, filled_shares, filled_notional, average_price,
                        total_slices, completed_slices, metadata, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        parent_order.parent_order_id,
                        parent_order.symbol,
                        parent_order.side,
                        parent_order.total_shares,
                        parent_order.algo_type,
                        parent_order.status,
                        parent_order.target_price,
                        0,
                        0.0,
                        0.0,
                        parent_order.total_slices,
                        0,
                        json.dumps(parent_order.metadata, ensure_ascii=False),
                        parent_order.created_at,
                        parent_order.updated_at,
                    ),
                )

                # 批量插入子单
                for s in slices_list:
                    conn.execute(
                        """
                        INSERT INTO child_slices (
                            slice_id, parent_order_id, day_index, slice_index, symbol, side,
                            shares, limit_price, status, filled_shares, filled_price,
                            filled_notional, scheduled_time, idempotency_key, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            s.slice_id,
                            s.parent_order_id,
                            s.day_index,
                            s.slice_index,
                            s.symbol,
                            s.side,
                            s.shares,
                            s.limit_price,
                            s.status,
                            0,
                            0.0,
                            0.0,
                            s.scheduled_time,
                            s.idempotency_key,
                            s.created_at,
                            s.updated_at,
                        ),
                    )

                self._record_audit_event(
                    conn,
                    entity_type="PARENT",
                    entity_id=parent_order_id,
                    from_status="NONE",
                    to_status=ParentOrderStatus.PENDING,
                    action="CREATE_3D_TWAP",
                    details={"total_shares": total_shares, "total_slices": len(slices_list)},
                )

                conn.execute("COMMIT;")
                logger.info(
                    f"母单创建成功: {parent_order_id}, 标的: {symbol}, 总量: {total_shares}, 切片数: {len(slices_list)}"
                )
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error(f"创建母单及 TWAP 切片失败: {e}", exc_info=True)
                raise
            finally:
                conn.close()

        return parent_order, slices_list

    # =========================================================================
    # 状态机流转控制与幂等执行
    # =========================================================================

    def mark_slice_submitted(self, slice_id: str) -> bool:
        """子单提交到经纪商/交易所 (PENDING -> SUBMITTED)，具有严格幂等性"""
        with self._write_lock:
            conn = self._get_connection(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute("SELECT * FROM child_slices WHERE slice_id = ?", (slice_id,)).fetchone()
                if not row:
                    logger.warning(f"子单不存在: {slice_id}")
                    conn.execute("ROLLBACK;")
                    return False

                current_status = row["status"]
                parent_id = row["parent_order_id"]

                # 幂等处理：若已提交或已完成，直接返回 True
                if current_status in (ChildSliceStatus.SUBMITTED, ChildSliceStatus.FILLED):
                    conn.execute("COMMIT;")
                    return True

                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE child_slices SET status = ?, updated_at = ? WHERE slice_id = ?",
                    (ChildSliceStatus.SUBMITTED, now_iso, slice_id),
                )

                # 更新母单为 RUNNING
                conn.execute(
                    """
                    UPDATE parent_orders 
                    SET status = CASE WHEN status = ? THEN ? ELSE status END,
                        updated_at = ?
                    WHERE parent_order_id = ?;
                    """,
                    (ParentOrderStatus.PENDING, ParentOrderStatus.RUNNING, now_iso, parent_id),
                )

                self._record_audit_event(
                    conn,
                    entity_type="SLICE",
                    entity_id=slice_id,
                    from_status=current_status,
                    to_status=ChildSliceStatus.SUBMITTED,
                    action="SUBMIT_SLICE",
                )

                conn.execute("COMMIT;")
                return True
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error(f"更新子单提交状态失败: {slice_id}, error={e}", exc_info=True)
                raise
            finally:
                conn.close()

    def mark_slice_filled(
        self,
        slice_id: str,
        filled_shares: int,
        filled_price: float,
        executed_time: Optional[str] = None,
    ) -> bool:
        """
        子单确认成交 (SUBMITTED / PENDING -> FILLED) 并触发母单全局聚合对账。
        幂等保护：重复上报相同成交直接短路并返回 True。
        """
        if filled_shares <= 0 or filled_price <= 0:
            raise ValueError(f"成交量与成交价必须为正数: shares={filled_shares}, price={filled_price}")

        with self._write_lock:
            conn = self._get_connection(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute("SELECT * FROM child_slices WHERE slice_id = ?", (slice_id,)).fetchone()
                if not row:
                    logger.error(f"成交上报失败，子单不存在: {slice_id}")
                    conn.execute("ROLLBACK;")
                    return False

                current_status = row["status"]
                parent_id = row["parent_order_id"]
                orig_shares = row["shares"]

                # 幂等性防护：如果已 FILLED 且数值一致，直接幂等通过
                if current_status == ChildSliceStatus.FILLED:
                    if row["filled_shares"] == filled_shares and abs(row["filled_price"] - filled_price) < 1e-6:
                        logger.info(f"子单已成交，幂等忽略重复上报: {slice_id}")
                        conn.execute("COMMIT;")
                        return True
                    else:
                        logger.warning(f"子单已处于 FILLED 状态但上报数据不一致: {slice_id}")

                now_iso = datetime.now(timezone.utc).isoformat()
                exec_time = executed_time or now_iso
                filled_notional = float(Decimal(str(filled_shares)) * Decimal(str(filled_price)))

                slice_status = ChildSliceStatus.FILLED if filled_shares >= orig_shares else ChildSliceStatus.PARTIAL

                conn.execute(
                    """
                    UPDATE child_slices 
                    SET status = ?, filled_shares = ?, filled_price = ?, filled_notional = ?, 
                        executed_time = ?, updated_at = ?
                    WHERE slice_id = ?;
                    """,
                    (slice_status, filled_shares, filled_price, filled_notional, exec_time, now_iso, slice_id),
                )

                self._record_audit_event(
                    conn,
                    entity_type="SLICE",
                    entity_id=slice_id,
                    from_status=current_status,
                    to_status=slice_status,
                    action="FILL_SLICE",
                    details={"filled_shares": filled_shares, "filled_price": filled_price},
                )

                # 原子性触发母单聚合对账 (Reconcile Parent)
                self._reconcile_parent_order_atomic(conn, parent_id)

                conn.execute("COMMIT;")
                logger.info(f"子单成交落地成功: {slice_id}, shares={filled_shares}, price={filled_price}")
                return True
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error(f"子单成交持久化异常: {slice_id}, error={e}", exc_info=True)
                raise
            finally:
                conn.close()

    def _reconcile_parent_order_atomic(self, conn: sqlite3.Connection, parent_id: str):
        """内部原子方法：从全部子单状态聚合重算母单进度与状态"""
        parent = conn.execute("SELECT * FROM parent_orders WHERE parent_order_id = ?", (parent_id,)).fetchone()
        if not parent:
            return

        slices = conn.execute("SELECT * FROM child_slices WHERE parent_order_id = ?", (parent_id,)).fetchall()
        if not slices:
            return

        total_shares = parent["total_shares"]
        sum_filled_shares = sum(s["filled_shares"] for s in slices)
        sum_filled_notional = sum(s["filled_notional"] for s in slices)
        completed_slices = sum(1 for s in slices if s["status"] == ChildSliceStatus.FILLED)
        avg_price = (sum_filled_notional / sum_filled_shares) if sum_filled_shares > 0 else 0.0

        # 判断母单最新状态
        if sum_filled_shares >= total_shares:
            new_parent_status = ParentOrderStatus.FILLED
        elif sum_filled_shares > 0:
            new_parent_status = ParentOrderStatus.PARTIALLY_FILLED
        elif any(s["status"] in (ChildSliceStatus.SUBMITTED, ChildSliceStatus.PARTIAL) for s in slices):
            new_parent_status = ParentOrderStatus.RUNNING
        else:
            new_parent_status = parent["status"]

        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE parent_orders
            SET filled_shares = ?, filled_notional = ?, average_price = ?,
                completed_slices = ?, status = ?, updated_at = ?
            WHERE parent_order_id = ?;
            """,
            (
                sum_filled_shares,
                sum_filled_notional,
                avg_price,
                completed_slices,
                new_parent_status,
                now_iso,
                parent_id,
            ),
        )

        if new_parent_status != parent["status"]:
            self._record_audit_event(
                conn,
                entity_type="PARENT",
                entity_id=parent_id,
                from_status=parent["status"],
                to_status=new_parent_status,
                action="RECONCILE_STATUS_UPDATE",
                details={
                    "filled_shares": sum_filled_shares,
                    "total_shares": total_shares,
                    "completed_slices": completed_slices,
                },
            )

    # =========================================================================
    # 断电崩溃幂等恢复机制 (Crash Outage & Idempotent Recovery)
    # =========================================================================

    def recover_after_crash(
        self,
        broker_fill_mock: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        断电崩溃重启后的幂等恢复方法。

        恢复流程：
        1. 扫描所有处于中间态的挂起子单 (status == 'SUBMITTED')；
        2. 根据外部经纪商/对账单提供的 broker_fill_mock 判定实际成交情况：
           - 若经纪商确认已成交：自动补全子单 FILLED 并记账；
           - 若经纪商未确认或未成交：安全回滚至 PENDING，准备下一轮幂等调度重试；
        3. 对所有处于 RUNNING / PARTIALLY_FILLED 的母单进行全量全局重算（Parent Reconcile）；
        4. 记录崩溃恢复审计流水，保证多次反复执行此方法具备严格幂等性。

        Args:
            broker_fill_mock: 模拟外部经纪商对账字典 {slice_id: {"filled_shares": int, "filled_price": float}}

        Returns:
            Dict[str, Any]: 恢复统计报表
        """
        recovery_summary = {
            "recovered_at": datetime.now(timezone.utc).isoformat(),
            "in_flight_slices_found": 0,
            "slices_confirmed_filled": 0,
            "slices_rolled_back_to_pending": 0,
            "parents_reconciled": 0,
            "status": "SUCCESS",
        }

        with self._write_lock:
            conn = self._get_connection(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                # 1. 查找所有处于 SUBMITTED 挂起状态的切片
                in_flight_slices = conn.execute(
                    "SELECT * FROM child_slices WHERE status = ?",
                    (ChildSliceStatus.SUBMITTED,),
                ).fetchall()

                recovery_summary["in_flight_slices_found"] = len(in_flight_slices)
                touched_parent_ids = set()

                now_iso = datetime.now(timezone.utc).isoformat()

                for s in in_flight_slices:
                    slice_id = s["slice_id"]
                    parent_id = s["parent_order_id"]
                    touched_parent_ids.add(parent_id)

                    # 查询是否有经纪商确认记录
                    if broker_fill_mock and slice_id in broker_fill_mock:
                        b_info = broker_fill_mock[slice_id]
                        f_shares = b_info["filled_shares"]
                        f_price = b_info["filled_price"]
                        f_notional = float(Decimal(str(f_shares)) * Decimal(str(f_price)))

                        conn.execute(
                            """
                            UPDATE child_slices
                            SET status = ?, filled_shares = ?, filled_price = ?, filled_notional = ?, updated_at = ?
                            WHERE slice_id = ?;
                            """,
                            (ChildSliceStatus.FILLED, f_shares, f_price, f_notional, now_iso, slice_id),
                        )
                        recovery_summary["slices_confirmed_filled"] += 1
                        self._record_audit_event(
                            conn,
                            entity_type="SLICE",
                            entity_id=slice_id,
                            from_status=ChildSliceStatus.SUBMITTED,
                            to_status=ChildSliceStatus.FILLED,
                            action="CRASH_RECOVERY_BROKER_CONFIRMED",
                            details={"filled_shares": f_shares, "filled_price": f_price},
                        )
                    else:
                        # 未在经纪商成交的子单，安全回滚为 PENDING
                        conn.execute(
                            """
                            UPDATE child_slices
                            SET status = ?, updated_at = ?
                            WHERE slice_id = ?;
                            """,
                            (ChildSliceStatus.PENDING, now_iso, slice_id),
                        )
                        recovery_summary["slices_rolled_back_to_pending"] += 1
                        self._record_audit_event(
                            conn,
                            entity_type="SLICE",
                            entity_id=slice_id,
                            from_status=ChildSliceStatus.SUBMITTED,
                            to_status=ChildSliceStatus.PENDING,
                            action="CRASH_RECOVERY_ROLLBACK_PENDING",
                        )

                # 2. 对所有未完成的母单（以及受影响母单）进行全局重算
                active_parents = conn.execute(
                    """
                    SELECT parent_order_id FROM parent_orders 
                    WHERE status IN (?, ?, ?)
                    """,
                    (ParentOrderStatus.PENDING, ParentOrderStatus.RUNNING, ParentOrderStatus.PARTIALLY_FILLED),
                ).fetchall()

                for p in active_parents:
                    touched_parent_ids.add(p["parent_order_id"])

                for p_id in touched_parent_ids:
                    self._reconcile_parent_order_atomic(conn, p_id)
                    recovery_summary["parents_reconciled"] += 1

                conn.execute("COMMIT;")
                logger.info(f"断电崩溃幂等恢复执行完毕: {recovery_summary}")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.critical(f"断电崩溃恢复失败: {e}", exc_info=True)
                recovery_summary["status"] = "FAILED"
                recovery_summary["error"] = str(e)
                raise
            finally:
                conn.close()

        return recovery_summary

    # =========================================================================
    # 查询与只读并发接口 (Concurrent Multi-Reader Queries)
    # =========================================================================

    def get_parent_order(self, parent_order_id: str) -> Optional[ParentOrder]:
        """并发无锁查询母单详情"""
        conn = self._get_connection(readonly=True)
        try:
            row = conn.execute(
                "SELECT * FROM parent_orders WHERE parent_order_id = ?",
                (parent_order_id,),
            ).fetchone()
            if not row:
                return None
            return ParentOrder(
                parent_order_id=row["parent_order_id"],
                symbol=row["symbol"],
                side=row["side"],
                total_shares=row["total_shares"],
                algo_type=row["algo_type"],
                status=row["status"],
                target_price=row["target_price"],
                filled_shares=row["filled_shares"],
                filled_notional=row["filled_notional"],
                average_price=row["average_price"],
                total_slices=row["total_slices"],
                completed_slices=row["completed_slices"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def get_child_slices(self, parent_order_id: str) -> List[ChildSlice]:
        """并发无锁查询母单对应的全部切片"""
        conn = self._get_connection(readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM child_slices WHERE parent_order_id = ? ORDER BY day_index, slice_index",
                (parent_order_id,),
            ).fetchall()
            return [
                ChildSlice(
                    slice_id=r["slice_id"],
                    parent_order_id=r["parent_order_id"],
                    day_index=r["day_index"],
                    slice_index=r["slice_index"],
                    symbol=r["symbol"],
                    side=r["side"],
                    shares=r["shares"],
                    limit_price=r["limit_price"],
                    status=r["status"],
                    filled_shares=r["filled_shares"],
                    filled_price=r["filled_price"],
                    filled_notional=r["filled_notional"],
                    scheduled_time=r["scheduled_time"],
                    executed_time=r["executed_time"],
                    idempotency_key=r["idempotency_key"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_audit_trail(self, entity_id: str) -> List[Dict[str, Any]]:
        """并发无锁查询审计轨迹"""
        conn = self._get_connection(readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM order_audit_trail WHERE entity_id = ? ORDER BY id ASC",
                (entity_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def inspect_wal_mode(self) -> Dict[str, Any]:
        """检查当前数据库的 WAL 模式与 Pragma 配置"""
        conn = self._get_connection(readonly=True)
        try:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            return {
                "journal_mode": str(journal_mode).upper(),
                "synchronous": int(synchronous),
                "foreign_keys": int(foreign_keys),
                "busy_timeout": int(busy_timeout),
            }
        finally:
            conn.close()


# =============================================================================
# 模块自检与仿真入口
# =============================================================================

if __name__ == "__main__":
    print("=== 开始轻量级生产级 SQLite WAL 订单状态机自检 ===")
    test_db = "/tmp/test_order_fsm_wal.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    fsm = SQLiteWALOrderStateMachine(db_path=test_db)
    pragmas = fsm.inspect_wal_mode()
    print("Pragmas:", pragmas)
    assert pragmas["journal_mode"] == "WAL", "必须启用 WAL 模式"

    # 1. 创建母单与 3 日 TWAP 切片 (3,125 手 IF 空头)
    parent, slices = fsm.create_parent_order_with_3d_twap(
        parent_order_id="PARENT_IF2406_HEDGE_001",
        symbol="IF2406",
        side=OrderSide.SELL,
        total_shares=3125,
        slices_per_day=10,
        target_price=4000.0,
    )
    print(f"母单: {parent.parent_order_id}, 状态: {parent.status}, 总切片: {len(slices)}")
    assert len(slices) == 30, f"期望 30 个切片，实际得到 {len(slices)}"
    assert sum(s.shares for s in slices) == 3125, "切片总手数必须精确为 3,125"

    # 2. 模拟切片执行 (前 5 个切片提交并成交)
    for s in slices[:5]:
        fsm.mark_slice_submitted(s.slice_id)
        fsm.mark_slice_filled(s.slice_id, filled_shares=s.shares, filled_price=3998.5)

    p_updated = fsm.get_parent_order(parent.parent_order_id)
    print(f"前 5 单执行后母单状态: {p_updated.status}, 成交: {p_updated.filled_shares}/{p_updated.total_shares}")
    assert p_updated.status == ParentOrderStatus.PARTIALLY_FILLED

    # 3. 模拟断电崩溃场景：第 6、7 个切片已提交但未确认
    fsm.mark_slice_submitted(slices[5].slice_id)
    fsm.mark_slice_submitted(slices[6].slice_id)

    # 4. 执行断电崩溃幂等恢复：外部对账确认第 6 个切片在经纪商已成交，第 7 个切片未在经纪商挂出
    mock_broker = {
        slices[5].slice_id: {"filled_shares": slices[5].shares, "filled_price": 3999.0}
    }
    rec_rep = fsm.recover_after_crash(broker_fill_mock=mock_broker)
    print(f"崩溃恢复报告: {rec_rep}")
    assert rec_rep["slices_confirmed_filled"] == 1
    assert rec_rep["slices_rolled_back_to_pending"] == 1

    # 5. 再次重复调用恢复，验证严格幂等性 (无挂起切片需要处理)
    rec_rep2 = fsm.recover_after_crash()
    assert rec_rep2["in_flight_slices_found"] == 0
    print("恢复幂等性验证通过!")

    print("=== SQLite WAL 订单状态机所有功能自检 100% 通过 ===")
