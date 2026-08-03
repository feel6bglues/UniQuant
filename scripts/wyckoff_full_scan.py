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


def _is_etf(symbol: str) -> bool:
    code = symbol.split(".")[0]
    if not code.isdigit():
        return False
    if len(code) == 6:
        prefix = code[:3]
        if code[:2] in ("51", "56", "58"):
            return True
        if prefix in ("159", "161", "162", "163", "164", "165", "166"):
            return True
    return False


def _compute_fwd_returns(
    full_df: pd.DataFrame,
    analysis_last_idx: int | None = None,
) -> tuple[float | None, float | None]:
    if len(full_df) < 2:
        return None, None
    if analysis_last_idx is None:
        analysis_last_idx = len(full_df) - 1
    last_close = float(full_df["close"].iloc[analysis_last_idx])
    fwd20 = None
    fwd60 = None
    fwd20_idx = analysis_last_idx + 20
    fwd60_idx = analysis_last_idx + 60
    if fwd20_idx < len(full_df):
        fwd20 = ((float(full_df["close"].iloc[fwd20_idx]) - last_close) / last_close) * 100
    if fwd60_idx < len(full_df):
        fwd60 = ((float(full_df["close"].iloc[fwd60_idx]) - last_close) / last_close) * 100
    return fwd20, fwd60


def _truncate_to_as_of(df: pd.DataFrame, as_of: str | None) -> pd.DataFrame:
    if as_of is None:
        return df
    mask = df["date"] <= pd.Timestamp(as_of)
    truncated = df[mask].copy()
    if truncated.empty:
        return df
    return truncated


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
    as_of: str | None = None,
) -> dict:
    """Run Wyckoff on one symbol; always returns a record (never raises).

    When as_of is set, truncate df to that date for analysis and compute
    forward returns from the truncation point.
    """
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
        "pnf_phase_divergence": None,
        "vdb_divergence": "none",
        "lps_stage": "not_test",
        "trading_plan_direction": "",
        "entry_trigger": "",
        "invalidation": "",
        "target_1": "",
        "rows": 0,
        "last_close": None,
        "is_etf": _is_etf(symbol),
        "fwd_20d": None,
        "fwd_60d": None,
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

        if as_of is not None:
            analysis_df = _truncate_to_as_of(df, as_of)
            if len(analysis_df) < 30:
                record["error"] = "too_short_for_as_of"
                return record
            record["fwd_20d"], record["fwd_60d"] = _compute_fwd_returns(df, len(analysis_df) - 1)
        else:
            analysis_df = df
            record["fwd_20d"], record["fwd_60d"] = _compute_fwd_returns(df, None)

        if len(analysis_df) < 30:
            record["error"] = "too_short"
            return record

        report = engine.analyze(analysis_df, symbol=symbol, period="日线", multi_timeframe=True, index_df=index_df)
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

        record["pnf_phase_divergence"] = getattr(report, "pnf_phase_divergence", None)
        record["vdb_divergence"] = str(getattr(report, "vdb_divergence", "none"))
        record["lps_stage"] = str(getattr(report, "lps_stage", "not_test"))

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


def run_scan(symbols: list[str], max_workers: int, output_dir: Path, as_of: str | None = None) -> list[dict]:
    storage = StorageManager(str(PROJECT_ROOT / "data"))
    index_df = load_index_df(storage)
    print(f"指数数据: {'OK (' + str(len(index_df)) + ' rows)' if index_df is not None else '不可用 (RS 将跳过)'}")
    print(f"待分析股票: {len(symbols)} 只, workers={max_workers}")
    if as_of:
        print(f"回放模式 as_of={as_of}")
    engine = WyckoffEngine()
    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(analyze_one, s, storage, index_df, engine, as_of): s for s in symbols}
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


def build_empirical_table(results: list[dict]) -> dict:
    """Build empirical forward-return statistics grouped by phase/spring/confidence.

    Returns nested dict keyed by dimension -> group -> {count, mean_fwd_20d, ...}.
    """
    if not results:
        return {}
    ok = [r for r in results if r.get("ok")]
    if not ok:
        return {}
    table: dict = {}
    for dim, label in [("phase", "phase"), ("spring", "spring"), ("confidence_level", "confidence_level")]:
        groups: dict = {}
        for r in ok:
            key = str(r.get(dim, "unknown"))
            if key not in groups:
                groups[key] = {"fwd_20d": [], "fwd_60d": []}
            f20 = r.get("fwd_20d")
            f60 = r.get("fwd_60d")
            if f20 is not None and not (isinstance(f20, float) and np.isnan(f20)):
                groups[key]["fwd_20d"].append(f20)
            if f60 is not None and not (isinstance(f60, float) and np.isnan(f60)):
                groups[key]["fwd_60d"].append(f60)
        out = {}
        for key, vals in groups.items():
            f20 = vals["fwd_20d"]
            f60 = vals["fwd_60d"]
            out[key] = {
                "count": len(f20),
                "mean_fwd_20d": round(float(np.mean(f20)), 2) if f20 else None,
                "median_fwd_20d": round(float(np.median(f20)), 2) if f20 else None,
                "mean_fwd_60d": round(float(np.mean(f60)), 2) if f60 else None,
                "median_fwd_60d": round(float(np.median(f60)), 2) if f60 else None,
            }
        table[label] = out
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="全量 Wyckoff 分析扫描")
    parser.add_argument("--symbols", default="all",
                        choices=["all", "main_board", "golden_20", "golden_100"])
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "results" / "wyckoff_full"))
    parser.add_argument("--as-of", default=None,
                        help="回放模式: 截断至该日期进行分析, 从截断点之后算 fwd 收益 (YYYY-MM-DD)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageManager(str(PROJECT_ROOT / "data"))
    symbols = load_symbols(args.symbols, storage)
    results = run_scan(symbols, args.max_workers, output_dir, as_of=args.as_of)

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

    emp_table = build_empirical_table(results)
    if emp_table:
        emp_path = output_dir / f"wyckoff_scan_{args.symbols}_empirical.json"
        emp_path.write_text(json.dumps(emp_table, ensure_ascii=False, indent=2, default=str))
        print(f"\n实证统计表: {emp_path}")


if __name__ == "__main__":
    main()
