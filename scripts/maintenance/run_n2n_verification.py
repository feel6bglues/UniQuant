#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UniQuant 端到端 (N2N) 全链路系统级验收验证脚本 (v2.2 定稿实施版).

验证范围 (6 大核心闭环轨道):
  Track 1: 数据通道与本地湖原子写入安全 (含 20 只金丝雀标的 9 列契约与崩溃防线)
  Track 2: Bootstrap 组装器与决策仲裁收敛 (QARAdapter 映射与 Sell-Priority 冲突断言)
  Track 3: 机构执行编排、75/25 资本配置与中金所 3 PB 账户套保限仓分仓
  Track 4: 统一日终决策流水线与风控穿透对账闭环 (期指双边平准，严格 GREEN 退出)
  Track 5: 持久化 KillSwitch 熔断拦截与 StateStore 重启 Fail-Closed 恢复
  Track 6: Rule 4 假数据防御攻防与 Bootstrap <50ms 启动性能断言
"""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any, Dict, Generator, List
from unittest.mock import patch

import pandas as pd
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.shared.logger_factory import get_logger

logger = get_logger("run_n2n_verification")

BENCHMARK_INDEX = "000300.SH"

# 20 只金丝雀全覆盖标的 (6 大类)
CANARY_STOCKS: List[str] = [
    # 沪市核心蓝筹
    "600519.SH", "601398.SH", "600036.SH", "600900.SH",
    # 深市主板龙头
    "000001.SZ", "000002.SZ", "000858.SZ", "000333.SZ",
    # 创业板成长
    "300750.SZ", "300059.SZ", "300760.SZ",
    # 科创板科技
    "688981.SH", "688111.SH", "688012.SH",
    # 周期与特殊量纲
    "600959.SH", "601319.SH", "600028.SH",
]
CANARY_INDICES: List[str] = ["000300.SH", "000016.SH", "000905.SH"]
EXPECTED_DAILY_COLS = {
    "date", "open", "high", "low", "close", "amount", "volume", "reserved", "code"
}
EXPECTED_MINUTE_COLS = [
    "datetime", "open", "high", "low", "close", "volume", "amount", "code"
]


@contextlib.contextmanager
def isolated_sandbox_context() -> Generator[Path, None, None]:
    """沙盒隔离上下文: 隔离临时文件并确保清理。"""
    temp_dir = Path(tempfile.mkdtemp(prefix="uniquant_n2n_"))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _verify_canary_universe(lake_dir: Path) -> Dict[str, Any]:
    """金丝雀标的池 9 列物理 Parquet 契约与历史深度核验。"""
    checked = 0
    daily_dir = lake_dir / "quotes" / "daily"
    index_dir = lake_dir / "quotes" / "index"

    for sym in CANARY_STOCKS:
        p = daily_dir / f"{sym}.parquet"
        assert p.exists(), f"金丝雀股票文件缺失: {p}"
        df = pl.read_parquet(p)
        assert set(df.columns) == EXPECTED_DAILY_COLS, f"日线列契约不符: {sym}"
        assert len(df) > 365, f"历史深度不足 365 日: {sym} ({len(df)} 根)"
        checked += 1

    for sym in CANARY_INDICES:
        p = index_dir / f"{sym}.parquet"
        if not p.exists():
            p = daily_dir / f"{sym}.parquet"
        assert p.exists(), f"金丝雀指数文件缺失: {p}"
        df = pl.read_parquet(p)
        assert set(df.columns) == EXPECTED_DAILY_COLS, f"指数列契约不符: {sym}"
        assert len(df) > 365, f"历史深度不足 365 日: {sym} ({len(df)} 根)"
        checked += 1

    return {"canary_total": checked, "daily_schema_9col": "PASS", "depth_gt_365": True}


def _verify_atomic_write_and_crash(daily_dir: Path) -> Dict[str, Any]:
    """原子写入安全与写入崩溃仿真防护。"""
    from uniquant.data.lake.storage_manager import StorageManager

    sm = StorageManager()
    target = daily_dir / "TEST_N2N_ATOMIC_CRASH.parquet"
    try:
        df_init = pd.DataFrame({"date": ["2026-11-20"], "close": [100.0], "volume": [1000.0]})
        assert sm.write_parquet(str(target), df_init, overwrite=True) is True
        assert target.exists()

        with patch.object(pd.DataFrame, "to_parquet", side_effect=IOError("Simulated disk full")):
            df_crash = pd.DataFrame({"date": ["2026-11-21"], "close": [200.0], "volume": [2000.0]})
            assert sm.write_parquet(str(target), df_crash, overwrite=True) is False

        assert target.exists()
        df_read = sm.read_parquet(str(target))
        assert df_read["close"].iloc[0] == 100.0
        tmps = list(daily_dir.glob(".*TEST_N2N_ATOMIC_CRASH*"))
        assert len(tmps) == 0, f"发现残留临时文件: {tmps}"
    finally:
        if target.exists():
            target.unlink()

    return {"atomic_replace": "PASS", "crash_safe": "PASS", "tmp_cleaned": True}


class N2NVerificationRunner:
    """N2N 全链路验证执行器 (真机实测核验版)。"""

    def __init__(self, mode: str = "sandbox", seed: int = 42) -> None:
        self.mode = mode
        self.seed = seed
        self.lake_dir = PROJECT_ROOT / "data" / "lake"
        self.report: Dict[str, Any] = {
            "mode": mode,
            "seed": seed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tracks": {},
            "summary": {"total": 6, "passed": 0, "failed": 0},
        }

    def run_all(self) -> bool:
        """串联执行 6 大核心轨道。"""
        logger.info(f"=== 启动 UniQuant N2N 全链路验证 (mode={self.mode}) ===")
        with isolated_sandbox_context() as sandbox_dir:
            tracks = [
                ("Track 1: 数据通道与湖原子写", lambda: self._verify_track_1(sandbox_dir)),
                ("Track 2: 决策收敛与仲裁优先", lambda: self._verify_track_2(sandbox_dir)),
                ("Track 3: 机构执行与期指分仓", lambda: self._verify_track_3(sandbox_dir)),
                ("Track 4: 日终流水线与风控对账", lambda: self._verify_track_4(sandbox_dir)),
                ("Track 5: 熔断拦截与状态恢复", lambda: self._verify_track_5(sandbox_dir)),
                ("Track 6: 假数据防御与架构解耦", lambda: self._verify_track_6(sandbox_dir)),
            ]
            for name, runner in tracks:
                t0 = time.perf_counter()
                try:
                    res = runner()
                    elapsed = round(time.perf_counter() - t0, 3)
                    self.report["tracks"][name] = {"status": "PASS", "elapsed_sec": elapsed, "details": res}
                    self.report["summary"]["passed"] += 1
                    logger.info(f"✅ [{name}] 通过 (耗时 {elapsed}s)")
                except Exception as e:
                    elapsed = round(time.perf_counter() - t0, 3)
                    self.report["tracks"][name] = {"status": "FAIL", "elapsed_sec": elapsed, "error": str(e)}
                    self.report["summary"]["failed"] += 1
                    logger.error(f"❌ [{name}] 失败: {e}")

        is_success = self.report["summary"]["failed"] == 0
        self.report["overall_verdict"] = "PASS" if is_success else "FAIL"
        return is_success

    def _verify_track_1(self, sandbox: Path) -> Dict[str, Any]:
        """Track 1: 契约核验、原子落盘、崩溃仿真与 Freshness SLA。"""
        from uniquant.data.lake.freshness_validator import FreshnessValidator
        from uniquant.data.lake.storage_manager import StorageManager

        sm = StorageManager()
        canary_res = _verify_canary_universe(self.lake_dir)
        atomic_res = _verify_atomic_write_and_crash(sm.daily_dir)

        fv = FreshnessValidator(storage_manager=sm)
        sla_res = fv.validate_freshness(max_lag_days=10)
        assert "is_fresh" in sla_res, "新鲜度结果格式错误"

        minute_files = list((self.lake_dir / "quotes" / "5mins").glob("*.parquet"))
        for mf in minute_files:
            m_df = pl.read_parquet(mf)
            assert list(m_df.columns) == EXPECTED_MINUTE_COLS, f"分钟列契约不符: {mf.name}"

        details: Dict[str, Any] = {
            "canary_universe": canary_res,
            "atomic_and_crash": atomic_res,
            "freshness_sla": sla_res["is_fresh"],
            "minute_files_checked": len(minute_files),
        }

        if self.mode == "live":
            from uniquant.data.sources.tdxdata_online import TdxDataOnlineSource
            src = TdxDataOnlineSource()
            snap = src.fetch_real_time("600519.SH")
            assert snap is not None and not snap.empty and snap["last"].iloc[0] > 0
            details["live_probe"] = "PASS"

        return details

    def _verify_track_2(self, sandbox: Path) -> Dict[str, Any]:
        """Track 2: 决策收敛与横截面仲裁 (QARAdapter 映射与 Sell-Priority)。"""
        from uniquant.services.bootstrap import create_signal_arbitrator
        from uniquant.shared.interfaces import TradingSignal
        from uniquant.signal.adapters import QARAdapter

        qar_adapter = QARAdapter()
        sig_qar = qar_adapter.adapt({"weight": 0.05, "price": 1450.0}, symbol="600519.SH")
        assert sig_qar is not None and sig_qar.action == "BUY" and sig_qar.confidence > 0.5

        sig_buy = TradingSignal(
            action="BUY", symbol="600519.SH", confidence=0.95, price=1450.0, metadata={"strategy": "QAR"}
        )
        sig_sell = TradingSignal(
            action="SELL", symbol="600519.SH", confidence=0.80, price=1450.0, metadata={"strategy": "WYCKOFF"}
        )
        sig_norm = TradingSignal(
            action="BUY", symbol="601398.SH", confidence=0.70, price=5.20, metadata={"strategy": "QAR"}
        )

        arb = create_signal_arbitrator(sell_priority=True)
        arbitrated = arb.arbitrate([sig_buy, sig_sell, sig_norm])
        actions = {s.symbol: s.action for s in arbitrated}

        assert actions.get("600519.SH") == "SELL", "仲裁器未能优先执行 SELL 避险"
        assert actions.get("601398.SH") == "BUY", "正常多头标的未能成功留存"

        return {
            "qar_adapter_mapping": "PASS",
            "arbitrated_count": len(arbitrated),
            "conflict_resolution": "SELL_WON",
        }

    def _verify_track_3(self, sandbox: Path) -> Dict[str, Any]:
        """Track 3: 机构执行编排与中金所期指分仓。"""
        from uniquant.hands.backtest.institutional_execution_orchestrator import (
            InstitutionalExecutionOrchestrator,
            OrchestratorConfig,
            StrategyTrack,
        )

        cfg = OrchestratorConfig(initial_aum=50_000_000.0, track=StrategyTrack.INSTITUTIONAL_75_25)
        orch = InstitutionalExecutionOrchestrator(config=cfg)

        cap = orch.allocate_capital(50_000_000.0)
        assert cap["equity_ratio"] == 0.75, "多头比例非 75%"
        assert cap["futures_ratio"] == -0.75, "空头比例非 -75%"
        assert cap["cash_ratio"] == 0.25, "现金比例非 25%"

        hedge = orch.plan_futures_hedging_structure(
            equity_long_notional=37_500_000.0,
            futures_price_points=4000.0,
            num_pb_accounts=3,
        )

        assert hedge["hedge_ratio"] == 0.75, "对冲比率错误"
        assert hedge["num_accounts"] == 3, "PB 账户数非 3"
        assert hedge["regulatory_violation_risk"] == "SAFE", "突破 1200 手限仓红线"
        assert hedge["all_accounts_within_speculative_limit"] is True
        for acc in hedge["accounts"]:
            assert acc["allocated_contracts"] <= 1200, f"单 PB 账户持仓超标: {acc}"

        return {
            "hedged_notional": hedge["notional_hedged_rmb"],
            "total_contracts": hedge["total_short_contracts_needed"],
            "regulatory_status": hedge["regulatory_violation_risk"],
        }

    def _verify_track_4(self, sandbox: Path) -> Dict[str, Any]:
        """Track 4: 日终宏观安全阀与风控穿透对账 (真实双向平准)。"""
        from scripts.daily.unified_daily_eod import UnifiedDailyEODPipeline
        from scripts.monitoring.reconcile_qar import build_qar_reconciliation

        eod = UnifiedDailyEODPipeline(lake_root=self.lake_dir)
        macro = eod.evaluate_macro_gate(as_of_date="2026-11-20")
        assert macro.status in ["BULL_OFFENSE", "CAUTION_DEFENSE", "BEAR_PANIC_CASH"]

        ref_sig = PROJECT_ROOT / "results" / "daily_qar" / "2024-05-06.json"
        with open(ref_sig, "r", encoding="utf-8") as f:
            sig_payload = json.load(f)

        pos_csv = sandbox / "pos.csv"
        lines = ["code,shares,price"]
        for code, w in sig_payload["target_stock_weights"].items():
            sh = int((w * 50_000_000.0) / 100.0)
            lines.append(f"{code},{sh},100.0")
        pos_csv.write_text("\n".join(lines), encoding="utf-8")

        fut_csv = sandbox / "fut.csv"
        fut_lines = [
            "account,contract,contracts,direction",
            "ACC_ALPHA_01,IF_MAIN,12,SHORT",
            "ACC_BETA_02,IF_MAIN,11,SHORT",
            "ACC_GAMMA_03,IF_MAIN,11,SHORT",
        ]
        fut_csv.write_text("\n".join(fut_lines), encoding="utf-8")

        recon = build_qar_reconciliation(
            signal_path=str(ref_sig),
            positions_path=str(pos_csv),
            futures_path=str(fut_csv),
            cash_rmb=12_500_000.0,
            drift_tol_pp=0.50,
        )

        assert recon["overall_status"] == "GREEN", f"对账未达到 GREEN 状态: {recon.get('critical_breaches')}"
        assert recon["exit_code"] == 0, "对账退出码非 0"
        assert len(recon["critical_breaches"]) == 0, "存在严重合规违规"
        risk_recon = recon.get("risk_reconciliation", {})
        assert risk_recon.get("net_beta", 1.0) <= 0.10, "Net Beta 突破 0.10 阈值"
        assert risk_recon.get("is_beta_neutral") is True, "未能达到 Beta 中性"

        return {
            "macro_status": macro.status,
            "overall_status": recon["overall_status"],
            "exit_code": recon["exit_code"],
            "net_beta": risk_recon.get("net_beta"),
        }

    def _verify_track_5(self, sandbox: Path) -> Dict[str, Any]:
        """Track 5: 持久化 KillSwitch 熔断拦截与状态恢复。"""
        from uniquant.shared.kill_switch import KillSwitchError, get_kill_switch
        from uniquant.shared.state_store import DiskStateStore

        store = DiskStateStore(root_dir=sandbox / "state")
        ks = get_kill_switch(state_store=store)

        ks.reset()
        assert not ks.is_killed, "初始状态非未熔断"

        ks.kill("N2N 容灾测试紧急停机")
        assert ks.is_killed, "KillSwitch 触发未能生效"

        saved = store.get("kill_switch")
        assert saved is not None and saved.get("killed") is True, "状态未能持久化至 StateStore"

        ks_restarted = get_kill_switch(state_store=store)
        assert ks_restarted.is_killed is True, "重启未能自动继承熔断态 (Fail-Closed 违约)"

        tripped = False
        try:
            ks_restarted.check()
        except KillSwitchError as e:
            tripped = True
            assert "Trading stopped" in str(e)
        assert tripped, "未能阻断抛出 KillSwitchError"

        ks.reset()
        assert not ks.is_killed, "复位未能成功"
        assert not ks_restarted.is_killed, "关联实例未能同步复位"

        return {
            "trip_intercept": "PASS",
            "state_persistence": "PASS",
            "restart_fail_closed": "PASS",
            "reset": "PASS",
        }

    def _verify_track_6(self, sandbox: Path) -> Dict[str, Any]:
        """Track 6: 架构解耦耗时与 Rule 4 假数据渗透攻防。"""
        from scripts.daily.unified_daily_eod import UnifiedDailyEODPipeline
        from uniquant.services.bootstrap import create_data_service, create_storage_manager

        t0 = time.perf_counter()
        _sm = create_storage_manager()
        _ds = create_data_service(storage_manager=_sm)
        lat_ms = (time.perf_counter() - t0) * 1000.0
        assert lat_ms < 50.0, f"Bootstrap 耗时超标: {lat_ms:.2f}ms >= 50ms"

        empty_lake = sandbox / "empty_lake"
        empty_lake.mkdir(parents=True, exist_ok=True)
        eod_empty = UnifiedDailyEODPipeline(lake_root=empty_lake)

        fail_fast = False
        try:
            eod_empty.evaluate_macro_gate()
        except FileNotFoundError:
            fail_fast = True

        assert fail_fast, "缺失数据时未抛出 FileNotFoundError，存在合成假数据违规漏洞"

        return {"bootstrap_latency_ms": round(lat_ms, 2), "rule4_fail_fast": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description="UniQuant N2N 验收运行器 (v2.2)")
    parser.add_argument("--mode", choices=["sandbox", "live"], default="sandbox", help="运行模式")
    parser.add_argument("--output", type=str, default="results/migration/n2n_verification_report.json")
    args = parser.parse_args()

    runner = N2NVerificationRunner(mode=args.mode)
    success = runner.run_all()

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = PROJECT_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(runner.report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"N2N 验收报告已写入存证: {out_path}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
