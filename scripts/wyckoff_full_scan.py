#!/usr/bin/env python3
"""全量 Wyckoff 分析扫描脚本 — 对本地数据湖全部股票运行经典 Wyckoff 引擎。

输出每只股票的相位/置信度/结构评分/复权状态/相对强弱/交易计划，
生成 CSV + JSON 汇总，供全市场候选池筛选。

用法:
    python3 scripts/wyckoff_full_scan.py --symbols all
    python3 scripts/wyckoff_full_scan.py --symbols main_board
    python3 scripts/wyckoff_full_scan.py --symbols golden_20
    python3 scripts/wyckoff_full_scan.py --symbols golden_100
    python3 scripts/wyckoff_full_scan.py --max-workers 8 --output-dir results/wyckoff_full
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import StorageManager  # noqa: E402
from uniquant.brain.wyckoff.engine import WyckoffEngine  # noqa: E402

_MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003", "300", "301")
_INDEX_EXCLUSIONS = ("000001", "000002", "000003", "000004", "000005",
                     "000006", "000007", "000008", "000009", "0000", "0001",
                     "0002", "0003", "0009", "399")


def load_symbols(kind: str, storage: StorageManager) -> list[str]:
    """Resolve symbol list by kind: all / main_board / golden_20 / golden_100."""
    if kind in ("golden_20", "golden_100"):
        path = PROJECT_ROOT / "tests" / "benchmark" / f"{kind}.txt"
        symbols = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            symbols.append(line.split()[0])
        return symbols

    all_symbols = storage.get_symbols()
    if kind == "all":
        return sorted(all_symbols)
    if kind == "main_board":
        return sorted(
            s for s in all_symbols
            if s.startswith(_MAIN_BOARD_PREFIXES)
            and not s.startswith(_INDEX_EXCLUSIONS)
        )
    raise SystemExit(f"未知 symbol 类型: {kind}")


def load_index_df(storage: StorageManager) -> pd.DataFrame | None:
    """Load CSI300 index for relative-strength alignment."""
    for sym in ("000300.SH",):
        df = storage.read_data(sym, data_type="daily")
        if not df.empty:
            return df
    for p in ("data/csi300_index.parquet",):
        path = PROJECT_ROOT / p
        if path.exists():
            return pd.read_parquet(path)
    return None


def analyze_one(
    symbol: str,
    storage: StorageManager,
    index_df: pd.DataFrame | None,
    engine: WyckoffEngine,
) -> dict:
    """Run Wyckoff on one symbol; always returns a record (never raises)."""
    record = {
        "symbol": symbol,
        "ok": False,
        "error": None,
        "phase": "unknown",
        "confidence": 0.0,
        "confidence_level": "",
        "structural_score": 0.0,
        "adjustment_status": "unknown",
        "relative_strength": None,
        "spring": False,
        "utad": False,
        "signal_type": "",
        "pnf_hint": "",
        "trading_plan_direction": "",
        "entry_trigger": "",
        "invalidation": "",
        "target_1": "",
        "rows": 0,
        "last_close": None,
    }
    try:
        df = storage.read_data(symbol, data_type="daily")
        if df is None or df.empty:
            record["error"] = "empty"
            return record
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values(by=["date"]).reset_index(drop=True)
        if "volume" not in df.columns or bool(df["volume"].isna().all()):
            record["error"] = "no_volume"
            return record
        if len(df) < 30:
            record["error"] = "too_short"
            return record

        report = engine.analyze(df, symbol=symbol, period="日线", multi_timeframe=True, index_df=index_df)
        record["ok"] = True
        record["rows"] = len(df)
        record["last_close"] = float(df["close"].iloc[-1]) if len(df) else None

        st = getattr(report, "structure", None)
        if st is not None and getattr(st, "phase", None) is not None:
            record["phase"] = str(st.phase.value) if hasattr(st.phase, "value") else str(st.phase)

        sig = getattr(report, "signal", None)
        if sig is not None:
            record["signal_type"] = str(getattr(sig, "signal_type", ""))
            conf = getattr(sig, "confidence", None)
            if conf is not None:
                record["confidence_level"] = str(conf.value) if hasattr(conf, "value") else str(conf)
                record["confidence"] = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}.get(
                    record["confidence_level"], 0.3)
            record["spring"] = "spring" in str(getattr(sig, "signal_type", "")).lower()
            record["utad"] = "utad" in str(getattr(sig, "signal_type", "")).lower()

        record["structural_score"] = float(getattr(report, "structural_score", 0.0) or 0.0)
        record["adjustment_status"] = str(getattr(report, "adjustment_status", "unknown"))
        rs = getattr(report, "relative_strength", None)
        record["relative_strength"] = rs if rs else None

        pnf = getattr(report, "pnf_analysis", None)
        if isinstance(pnf, dict):
            record["pnf_hint"] = str(pnf.get("hint", "")) or str(pnf.get("phase_hint", ""))

        tp = getattr(report, "trading_plan", None)
        if tp is not None:
            record["trading_plan_direction"] = str(getattr(tp, "direction", ""))
            record["entry_trigger"] = str(getattr(tp, "entry_trigger", ""))
            record["invalidation"] = str(getattr(tp, "invalidation", ""))
            record["target_1"] = str(getattr(tp, "target_1", ""))
    except Exception as e:  # noqa: BLE001 — isolate per-symbol failures
        record["error"] = f"{type(e).__name__}: {e}"
    return record


def run_scan(symbols: list[str], max_workers: int, output_dir: Path) -> list[dict]:
    storage = StorageManager(str(PROJECT_ROOT / "data"))
    index_df = load_index_df(storage)
    print(f"指数数据: {'OK (' + str(len(index_df)) + ' rows)' if index_df is not None else '不可用 (RS 将跳过)'}")
    print(f"待分析股票: {len(symbols)} 只, workers={max_workers}")

    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(analyze_one, s, storage, index_df, WyckoffEngine()): s for s in symbols}
        done = 0
        for fut in as_completed(futures):
            done += 1
            rec = fut.result()
            results.append(rec)
            if done % 500 == 0 or done == len(symbols):
                elapsed = time.time() - t0
                print(f"  进度 {done}/{len(symbols)} ({elapsed:.1f}s, {elapsed / max(done, 1):.3f}s/只)")

    print(f"完成: {len(results)} 只, 耗时 {time.time() - t0:.1f}s")
    return results


def summarize(results: list[dict]) -> dict:
    phases = {}
    conf_levels = {}
    rs_classes = {}
    adj = {}
    for r in results:
        if r["ok"]:
            phases[r["phase"]] = phases.get(r["phase"], 0) + 1
            cl = r["confidence_level"]
            conf_levels[cl] = conf_levels.get(cl, 0) + 1
            rs = r["relative_strength"]
            rs_classes[rs] = rs_classes.get(rs, 0) + 1
            adj[r["adjustment_status"]] = adj.get(r["adjustment_status"], 0) + 1

    scores = [r["structural_score"] for r in results if r["ok"] and r["structural_score"] > 0]
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "errors": sum(1 for r in results if not r["ok"]),
        "error_types": {e: sum(1 for r in results if not r["ok"] and r["error"] == e)
                        for e in {r["error"] for r in results if not r["ok"]}},
        "phase_distribution": phases,
        "confidence_distribution": conf_levels,
        "relative_strength_distribution": rs_classes,
        "adjustment_status_distribution": adj,
        "structural_score_percentiles": {
            f"p{int(q * 100)}": round(float(np.percentile(scores, q * 100)), 2)
            for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        } if scores else {},
        "duration_seconds": 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="全量 Wyckoff 分析扫描")
    parser.add_argument("--symbols", default="all",
                        choices=["all", "main_board", "golden_20", "golden_100"])
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "results" / "wyckoff_full"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageManager(str(PROJECT_ROOT / "data"))
    symbols = load_symbols(args.symbols, storage)
    results = run_scan(symbols, args.max_workers, output_dir)

    df = pd.DataFrame(results)
    df = df.sort_values("symbol").reset_index(drop=True)
    csv_path = output_dir / f"wyckoff_scan_{args.symbols}.csv"
    df.to_csv(csv_path, index=False)

    summary = summarize(results)
    summary["duration_seconds"] = round(summary.get("duration_seconds", 0), 1)
    json_path = output_dir / f"wyckoff_scan_{args.symbols}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    print(f"\nCSV: {csv_path}")
    print(f"JSON: {json_path}")
    print("\n=== 汇总 ===")
    print(f"总股票: {summary['total']} | 成功: {summary['ok']} | 失败: {summary['errors']}")
    print(f"相位分布: {summary['phase_distribution']}")
    print(f"置信度分布: {summary['confidence_distribution']}")
    print(f"相对强弱分布: {summary['relative_strength_distribution']}")
    print(f"复权状态分布: {summary['adjustment_status_distribution']}")
    print(f"结构评分分位: {summary['structural_score_percentiles']}")
    if summary["error_types"]:
        print(f"错误类型: {summary['error_types']}")


if __name__ == "__main__":
    main()
