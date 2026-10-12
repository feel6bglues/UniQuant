#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMM RESEARCH OS v3.0 & UniQuant: 作战单元 C 生产级工程与数理门禁套件
=============================================================================
测试代号: TestUniQuantProductionArchitectureGates
门禁指标:
  - Gate 1: UniQuant 核心组合服务仓位限制放宽 (MIN_POSITION_PCT = -100%) 与负仓位计算验证
  - Gate 2: 多空对冲组合权重验证模式 (75% 股票 + (-75%) 期货 + 25% 现金, Gross 175%, Net ≈ 0%) 与再平衡
  - Gate 3: 单边做多存量策略向后兼容性检验 (100% 比例/百分比守恒与非法权重拦截)
  - Gate 4: C4 冲突治理与 Wyckoff 引擎宽泛异常根除审计 (AST 静态检测与具体异常告警运行时验证)
  - Gate 5: 轻量级生产级 SQLite WAL 订单状态机 3 日 TWAP 切片持久化与数理整除性校验
  - Gate 6: SQLite WAL 单写多读 (Single-Writer Multi-Reader) 高并发压力测试 (100% 无锁冲突)
  - Gate 7: 断电崩溃幂等恢复机制 (Crash Recovery & Idempotency) 与母子单状态一致性对账
=============================================================================
"""

import os
import ast
import sys
import json
import time
import shutil
import logging
import tempfile
import threading
from pathlib import Path
from decimal import Decimal
import pytest

# 注入项目路径
UNIQUANT_ROOT = Path("/home/james/Documents/Project/UniQuant")
UNIQUANT_SRC = UNIQUANT_ROOT / "src"
if str(UNIQUANT_SRC) not in sys.path:
    sys.path.insert(0, str(UNIQUANT_SRC))

CNNM_ROOT = Path("/home/james/Documents/Project/CNNM")
CNNM_SCRATCH = CNNM_ROOT / "scratch"
if str(CNNM_SCRATCH) not in sys.path:
    sys.path.insert(0, str(CNNM_SCRATCH))

from uniquant.services.portfolio_service import PortfolioService
from uniquant.shared.exceptions import PortfolioServiceError
from order_state_machine import (
    SQLiteWALOrderStateMachine,
    ParentOrder,
    ChildSlice,
    ParentOrderStatus,
    ChildSliceStatus,
    OrderSide,
    AlgoType,
)


# =============================================================================
# Gate 1: 组合服务仓位限制放宽与负仓位计算门禁
# =============================================================================

class TestPortfolioServicePositionGates:
    """Gate 1: MIN_POSITION_PCT 解除死锁并放宽至 -100%"""

    @pytest.fixture(scope="class")
    def portfolio_service(self):
        return PortfolioService()

    def test_gate_1_min_position_pct_constant_unblocked(self, portfolio_service):
        """验证 MIN_POSITION_PCT 常量已放宽至 Decimal('-100')"""
        assert portfolio_service.MIN_POSITION_PCT == Decimal("-100"), (
            f"MIN_POSITION_PCT 必须为 Decimal('-100')，当前为 {portfolio_service.MIN_POSITION_PCT}"
        )
        assert portfolio_service.MAX_POSITION_PCT == Decimal("100")

    def test_gate_1_validate_position_boundaries(self, portfolio_service):
        """验证 _validate_position 对正负仓位边界的精确约束"""
        # 合法边界区间 [-100, 100]
        assert portfolio_service._validate_position(Decimal("-100")) is True
        assert portfolio_service._validate_position(Decimal("-75")) is True
        assert portfolio_service._validate_position(Decimal("0")) is True
        assert portfolio_service._validate_position(Decimal("50")) is True
        assert portfolio_service._validate_position(Decimal("100")) is True

        # 越界拦截 (超出 [-100, 100])
        assert portfolio_service._validate_position(Decimal("-100.01")) is False
        assert portfolio_service._validate_position(Decimal("-150")) is False
        assert portfolio_service._validate_position(Decimal("100.01")) is False
        assert portfolio_service._validate_position(Decimal("200")) is False

    def test_gate_1_calculate_position_short_hedging(self, portfolio_service):
        """验证 calculate_position 支持空头对冲仓位计算 (-75% 仓位)"""
        # 1000 万资产规模，-75% 空头对冲，价格 4000 元 (如 IF 合约或股票)
        res = portfolio_service.calculate_position(
            symbol="IF2406",
            target_pct=Decimal("-75"),
            portfolio_value=Decimal("10000000"),
            price=Decimal("4000"),
        )
        assert res["symbol"] == "IF2406"
        assert res["target_pct"] == -75.0
        assert res["target_amount"] == -7500000.0
        # 股数取整为负数
        assert res["shares"] == -1875
        assert res["actual_amount"] == -7500000.0
        assert res["actual_pct"] == -75.0


# =============================================================================
# Gate 2: 多空对冲权重验证模式门禁
# =============================================================================

class TestPortfolioServiceHedgingWeightsGates:
    """Gate 2: 多空对冲验证模式 (75% 股票 + (-75%) 期货 + 25% 现金, Gross 175%, Net ≈ 0%)"""

    @pytest.fixture(scope="class")
    def portfolio_service(self):
        return PortfolioService()

    def test_gate_2_canonical_hedging_weights_percentage_mode(self, portfolio_service):
        """验证核心用例：75% 股票 + (-75%) 期货 + 25% 现金 (Gross 175%, Net ≈ 0%)"""
        weights_pct = {
            "000300.SH": Decimal("75"),
            "IF2406": Decimal("-75"),
            "CASH": Decimal("25"),
        }
        is_valid = portfolio_service._validate_weights(weights_pct)
        assert is_valid is True, "75% 股票 + (-75%) 期货 + 25% 现金 (百分比) 必须验证通过"

    def test_gate_2_canonical_hedging_weights_ratio_mode(self, portfolio_service):
        """验证核心用例：0.75 股票 + (-0.75) 期货 + 0.25 现金 (Gross 1.75, Net ≈ 0%)"""
        weights_ratio = {
            "000300.SH": Decimal("0.75"),
            "IF2406": Decimal("-0.75"),
            "CASH": Decimal("0.25"),
        }
        is_valid = portfolio_service._validate_weights(weights_ratio)
        assert is_valid is True, "0.75 股票 + (-0.75) 期货 + 0.25 现金 (比率制) 必须验证通过"

    def test_gate_2_multi_asset_long_short_hedging(self, portfolio_service):
        """验证多标的股票组合加期货对冲：40% 茅台 + 35% 宁德 - 75% 期货 + 25% 现金"""
        weights = {
            "600519.SH": Decimal("40"),
            "300750.SZ": Decimal("35"),
            "IF2406": Decimal("-75"),
            "CASH": Decimal("25"),
        }
        assert portfolio_service._validate_weights(weights) is True

    def test_gate_2_rebalance_integration_with_hedging_portfolio(self, portfolio_service):
        """验证组合再平衡接口支持多空对冲目标权重调度"""
        portfolio = {
            "symbols": ["600519.SH", "IF2406", "CASH"],
            "weights": {"600519.SH": 0.0, "IF2406": 0.0, "CASH": 1.0},
            "total_value": Decimal("10000000"),
        }
        target_weights = {
            "600519.SH": Decimal("0.75"),
            "IF2406": Decimal("-0.75"),
            "CASH": Decimal("0.25"),
        }
        prices = {
            "600519.SH": Decimal("1500"),
            "IF2406": Decimal("4000"),
            "CASH": Decimal("1"),
        }

        rebalanced = portfolio_service.rebalance(portfolio, target_weights, prices)
        assert "trades" in rebalanced
        trades = rebalanced["trades"]
        assert len(trades) >= 2
        buy_trade = next(t for t in trades if t["symbol"] == "600519.SH")
        sell_trade = next(t for t in trades if t["symbol"] == "IF2406")
        assert buy_trade["action"] == "BUY"
        assert sell_trade["action"] == "SELL"

    def test_gate_2_hedging_mode_rejections(self, portfolio_service):
        """验证非法多空组合被严格拦截 (越界、超杠杆、禁用空头等)"""
        # 1. 单资产超过 100% (比如 120% 股票)
        w_over = {"000300.SH": Decimal("120"), "IF2406": Decimal("-120"), "CASH": Decimal("20")}
        assert portfolio_service._validate_weights(w_over) is False

        # 2. 单资产低于 -100% (比如 -110% 期货)
        w_under = {"000300.SH": Decimal("75"), "IF2406": Decimal("-110"), "CASH": Decimal("25")}
        assert portfolio_service._validate_weights(w_under) is False

        # 3. 总杠杆 Gross 超过最大限制 (默认 300% / 3.0)
        w_high_leverage = {"A": Decimal("100"), "B": Decimal("100"), "C": Decimal("-110")}
        assert portfolio_service._validate_weights(w_high_leverage) is False

        # 4. allow_short=False 模式下禁止任何负权重
        w_hedging = {"000300.SH": Decimal("75"), "IF2406": Decimal("-75"), "CASH": Decimal("25")}
        assert portfolio_service._validate_weights(w_hedging, allow_short=False) is False


# =============================================================================
# Gate 3: 存量单边做多策略向后兼容性门禁
# =============================================================================

class TestPortfolioServiceLegacyCompatibilityGates:
    """Gate 3: 单边做多存量策略向后兼容性验证"""

    @pytest.fixture(scope="class")
    def portfolio_service(self):
        return PortfolioService()

    def test_gate_3_legacy_long_only_valid_cases(self, portfolio_service):
        """验证传统单边做多权重完全保持向后兼容"""
        # 1. 传统 1.0 比率制
        w_legacy_ratio = {"600519.SH": Decimal("0.6"), "000858.SZ": Decimal("0.4")}
        assert portfolio_service._validate_weights(w_legacy_ratio) is True

        # 2. 传统 100 百分比制
        w_legacy_pct = {"600519.SH": Decimal("60"), "000858.SZ": Decimal("40")}
        assert portfolio_service._validate_weights(w_legacy_pct) is True

        # 3. 等权重 3 标的 (浮点容差)
        w_equal = {"A": Decimal("0.3333"), "B": Decimal("0.3333"), "C": Decimal("0.3334")}
        assert portfolio_service._validate_weights(w_equal) is True

    def test_gate_3_legacy_long_only_invalid_sums_rejected(self, portfolio_service):
        """验证传统单边做多策略若权重和不等于 1 或 100，仍严格拒绝"""
        # 总和 1.10 != 1.0
        assert portfolio_service._validate_weights({"A": Decimal("0.6"), "B": Decimal("0.5")}) is False
        # 总和 90 != 100
        assert portfolio_service._validate_weights({"A": Decimal("50"), "B": Decimal("40")}) is False
        # 空字典
        assert portfolio_service._validate_weights({}) is False


# =============================================================================
# Gate 4: C4 冲突治理与 Wyckoff 引擎宽泛异常根除门禁
# =============================================================================

class TestWyckoffEngineExceptionHandlingGates:
    """Gate 4: 修复 C4 冲突，彻底根除 5 处宽泛 except Exception"""

    ENGINE_PATH = Path("/home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/engine.py")

    def test_gate_4_ast_audit_no_broad_exception_in_engine(self):
        """AST 语法树法医级审计：验证 engine.py 中绝无任何裸 'except Exception:'"""
        assert self.ENGINE_PATH.exists(), f"Missing wyckoff engine: {self.ENGINE_PATH}"

        with open(self.ENGINE_PATH, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        broad_exceptions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    broad_exceptions.append((node.lineno, "bare except:"))
                elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    broad_exceptions.append((node.lineno, "except Exception:"))

        assert len(broad_exceptions) == 0, (
            f"Wyckoff engine 仍存在宽泛异常捕获，违背 C4 规范: {broad_exceptions}"
        )

    def test_gate_4_specific_exceptions_and_explicit_warning_runtime(self, capsys, caplog):
        """运行时故障注入：模拟配置损坏，验证捕获具体异常并记录 warning 告警"""
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        import uniquant.brain.wyckoff.engine as engine_mod

        # 模拟 get_config 抛出具体的 KeyError
        orig_get_config = engine_mod.get_config

        def broken_get_config():
            raise KeyError("Simulated missing config key")

        engine_mod.get_config = broken_get_config

        try:
            with caplog.at_level(logging.WARNING):
                engine = WyckoffEngine()
                gate_val = engine._scan_buy_confidence_gate()
                assert gate_val == 0.40, "配置读取失败时应降级返回默认门限 0.40"

            # 验证日志或 stderr 输出了明确的 WARNING 告警，杜绝静默失败
            captured = capsys.readouterr()
            all_warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
            stderr_output = captured.err

            has_confidence_warning = (
                any("wyckoff.confidence_gate" in msg for msg in all_warnings)
                or "wyckoff.confidence_gate" in stderr_output
            )
            assert has_confidence_warning, (
                f"未检测到 confidence_gate 的显式告警日志! all_warnings={all_warnings}, stderr={stderr_output}"
            )
        finally:
            engine_mod.get_config = orig_get_config


# =============================================================================
# Gate 5: SQLite WAL 订单状态机与 3 日 TWAP 切片持久化门禁
# =============================================================================

class TestSQLiteWALOrderStateMachineGates:
    """Gate 5: 母单与 3 日 TWAP 子单切片持久化、Pragmas 与数理整除性"""

    @pytest.fixture
    def temp_fsm(self):
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test_order_fsm.db")
        fsm = SQLiteWALOrderStateMachine(db_path=db_path)
        yield fsm
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)

    def test_gate_5_wal_pragmas_and_initialization(self, temp_fsm):
        """验证 SQLite WAL 模式、外键约束、同步级别配置完整性"""
        pragmas = temp_fsm.inspect_wal_mode()
        assert pragmas["journal_mode"] == "WAL", f"Journal mode 必须为 WAL，当前为 {pragmas['journal_mode']}"
        assert pragmas["foreign_keys"] == 1, "Foreign keys 必须启用"
        assert pragmas["synchronous"] == 1, "Synchronous 必须为 NORMAL (1)"
        assert pragmas["busy_timeout"] == 5000, "Busy timeout 必须为 5000ms"

    def test_gate_5_twap_3d_slice_exact_shares_and_idempotency(self, temp_fsm):
        """验证 3 日 TWAP 切片数理整除性：3125 手 IF 空头切片份额精确守恒与幂等创建"""
        total_shares = 3125
        parent_id = "PARENT_TWAP_IF2406_001"

        parent, slices = temp_fsm.create_parent_order_with_3d_twap(
            parent_order_id=parent_id,
            symbol="IF2406",
            side=OrderSide.SELL,
            total_shares=total_shares,
            slices_per_day=10,  # 3 日共 30 个切片
            target_price=4000.0,
        )

        assert parent.total_shares == total_shares
        assert parent.status == ParentOrderStatus.PENDING
        assert len(slices) == 30

        # 检验 3 日切片份额和严格等于 3125 手
        sum_shares = sum(s.shares for s in slices)
        assert sum_shares == total_shares, f"切片总量和({sum_shares})与母单总量({total_shares})不符"

        # 检验各天切片数恰为 10
        for day in (1, 2, 3):
            day_slices = [s for s in slices if s.day_index == day]
            assert len(day_slices) == 10

        # 验证重复创建的幂等性：返回同一订单，数据库中记录不翻倍
        parent2, slices2 = temp_fsm.create_parent_order_with_3d_twap(
            parent_order_id=parent_id,
            symbol="IF2406",
            side=OrderSide.SELL,
            total_shares=total_shares,
            slices_per_day=10,
        )
        assert parent2.parent_order_id == parent.parent_order_id
        assert len(slices2) == 30


# =============================================================================
# Gate 6: SQLite WAL 单写多读高并发压力测试门禁
# =============================================================================

class TestWALSingleWriterMultiReaderConcurrencyGates:
    """Gate 6: WAL 单写多读并发压力测试 (10 个并发读线程 + 1 个写线程)"""

    @pytest.fixture
    def concurrent_fsm(self):
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "concurrent_fsm.db")
        fsm = SQLiteWALOrderStateMachine(db_path=db_path)
        yield fsm
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)

    def test_gate_6_single_writer_multi_reader_concurrency_stress(self, concurrent_fsm):
        """高并发压测：10 读者并发查询，1 写入者高频推进切片，0 读写冲突"""
        parent_id = "PARENT_CONCURRENCY_TEST"
        parent, slices = concurrent_fsm.create_parent_order_with_3d_twap(
            parent_order_id=parent_id,
            symbol="600519.SH",
            side=OrderSide.BUY,
            total_shares=30000,
            slices_per_day=10,
        )

        read_errors = []
        stop_event = threading.Event()

        def reader_worker(worker_id: int):
            while not stop_event.is_set():
                try:
                    p = concurrent_fsm.get_parent_order(parent_id)
                    s_list = concurrent_fsm.get_child_slices(parent_id)
                    assert p is not None
                    assert len(s_list) == 30
                    time.sleep(0.002)
                except Exception as err:
                    read_errors.append((worker_id, str(err)))

        # 启动 10 个读者线程
        reader_threads = [threading.Thread(target=reader_worker, args=(i,)) for i in range(10)]
        for t in reader_threads:
            t.daemon = True
            t.start()

        # 主写线程依次更新切片提交与成交
        for s in slices:
            concurrent_fsm.mark_slice_submitted(s.slice_id)
            concurrent_fsm.mark_slice_filled(s.slice_id, filled_shares=s.shares, filled_price=1680.0)
            time.sleep(0.005)

        stop_event.set()
        for t in reader_threads:
            t.join(timeout=2.0)

        assert len(read_errors) == 0, f"并发读取过程中出现锁冲突异常: {read_errors}"

        final_parent = concurrent_fsm.get_parent_order(parent_id)
        assert final_parent.status == ParentOrderStatus.FILLED
        assert final_parent.filled_shares == 30000
        assert final_parent.completed_slices == 30
        assert final_parent.average_price == 1680.0


# =============================================================================
# Gate 7: 断电崩溃幂等恢复机制门禁
# =============================================================================

class TestCrashOutageIdempotentRecoveryGates:
    """Gate 7: 断电崩溃恢复、孤儿切片处理与幂等对账重算"""

    @pytest.fixture
    def crash_fsm(self):
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "crash_fsm.db")
        fsm = SQLiteWALOrderStateMachine(db_path=db_path)
        yield fsm
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)

    def test_gate_7_crash_recovery_and_parent_reconciliation(self, crash_fsm):
        """模拟交易执行中断电崩溃：已发单挂起切片的幂等恢复与母单进度核算"""
        parent_id = "PARENT_CRASH_TEST_001"
        parent, slices = crash_fsm.create_parent_order_with_3d_twap(
            parent_order_id=parent_id,
            symbol="IF2406",
            side=OrderSide.SELL,
            total_shares=1000,
            slices_per_day=5,  # 15 个切片
        )

        # 1. 正常执行前 3 个切片
        for s in slices[:3]:
            crash_fsm.mark_slice_submitted(s.slice_id)
            crash_fsm.mark_slice_filled(s.slice_id, filled_shares=s.shares, filled_price=4000.0)

        # 2. 模拟断电崩溃现场：第 4、5 个切片已提交但进程意外猝死 (处于 SUBMITTED 挂起态)
        crash_fsm.mark_slice_submitted(slices[3].slice_id)
        crash_fsm.mark_slice_submitted(slices[4].slice_id)

        # 验证现场状态
        s3 = next(s for s in crash_fsm.get_child_slices(parent_id) if s.slice_id == slices[3].slice_id)
        s4 = next(s for s in crash_fsm.get_child_slices(parent_id) if s.slice_id == slices[4].slice_id)
        assert s3.status == ChildSliceStatus.SUBMITTED
        assert s4.status == ChildSliceStatus.SUBMITTED

        # 3. 系统重启，执行断电崩溃幂等恢复
        # 模拟外部经纪商对账单：第 4 切片在经纪商已成交，第 5 切片未在经纪商挂出
        broker_fill_mock = {
            slices[3].slice_id: {"filled_shares": slices[3].shares, "filled_price": 4005.0}
        }

        report = crash_fsm.recover_after_crash(broker_fill_mock=broker_fill_mock)
        assert report["status"] == "SUCCESS"
        assert report["in_flight_slices_found"] == 2
        assert report["slices_confirmed_filled"] == 1
        assert report["slices_rolled_back_to_pending"] == 1

        # 验证切片恢复后状态
        s3_after = next(s for s in crash_fsm.get_child_slices(parent_id) if s.slice_id == slices[3].slice_id)
        s4_after = next(s for s in crash_fsm.get_child_slices(parent_id) if s.slice_id == slices[4].slice_id)
        assert s3_after.status == ChildSliceStatus.FILLED
        assert s4_after.status == ChildSliceStatus.PENDING

        # 验证母单已被自动原子性对账更新
        p_recovered = crash_fsm.get_parent_order(parent_id)
        expected_filled = sum(s.shares for s in slices[:4])
        assert p_recovered.filled_shares == expected_filled
        assert p_recovered.completed_slices == 4
        assert p_recovered.status == ParentOrderStatus.PARTIALLY_FILLED

        # 4. 再次重复调用恢复，验证严格数学幂等性
        report2 = crash_fsm.recover_after_crash()
        assert report2["in_flight_slices_found"] == 0
        p_recovered2 = crash_fsm.get_parent_order(parent_id)
        assert p_recovered2.filled_shares == p_recovered.filled_shares

    def test_gate_7_redundant_fill_reporting_idempotency(self, crash_fsm):
        """验证网络抖动导致的重复上报成交具备 100% 幂等性，不发生重复记账"""
        parent_id = "PARENT_REDUNDANT_TEST"
        parent, slices = crash_fsm.create_parent_order_with_3d_twap(
            parent_order_id=parent_id,
            symbol="600519.SH",
            side=OrderSide.BUY,
            total_shares=500,
            slices_per_day=2,
        )

        slice_0 = slices[0]
        crash_fsm.mark_slice_submitted(slice_0.slice_id)

        # 第一次成交上报
        res1 = crash_fsm.mark_slice_filled(slice_0.slice_id, filled_shares=slice_0.shares, filled_price=1600.0)
        assert res1 is True
        p1 = crash_fsm.get_parent_order(parent_id)
        assert p1.filled_shares == slice_0.shares

        # 第二次重复上报相同成交
        res2 = crash_fsm.mark_slice_filled(slice_0.slice_id, filled_shares=slice_0.shares, filled_price=1600.0)
        assert res2 is True
        p2 = crash_fsm.get_parent_order(parent_id)
        # 绝不重复记账
        assert p2.filled_shares == slice_0.shares
        assert p2.filled_notional == p1.filled_notional
