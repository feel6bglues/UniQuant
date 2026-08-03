#!/usr/bin/env python3
"""
Wyckoff 实证验收闸门 — 基于 fwd 收益的全面验证。

用法:
    python3 scripts/wyckoff_empirical_verify.py --scan-csv results/wyckoff_full/wyckoff_scan_all.csv
    python3 scripts/wyckoff_empirical_verify.py --symbols golden_20 --as-of 2026-05-15 --output-dir /tmp/verify
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.wyckoff_full_scan import (  # noqa: E402
    build_empirical_table,
    load_symbols,
    load_index_df,
    summarize,
)


def _load_scan_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "symbol" not in df.columns:
        raise ValueError(f"CSV 缺少 symbol 列: {path}")
    return df


def _compute_structural_rank_ic(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    if len(ok) < 5:
        return {"spearman_rho": None, "p_value": None, "n": len(ok)}
    valid = ok.dropna(subset=["structural_score", "fwd_20d"])
    if len(valid) < 5:
        return {"spearman_rho": None, "p_value": None, "n": len(valid)}
    from scipy.stats import spearmanr

    rho, p = spearmanr(valid["structural_score"], valid["fwd_20d"])
    return {"spearman_rho": round(float(rho), 4), "p_value": round(float(p), 4), "n": len(valid)}


def _compute_lps_conduction(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    springs = ok[ok.get("spring", False)]
    if len(springs) < 5:
        return {"count": int(len(springs)), "lps_stage_distribution": {}, "lps_confirmed_rate": None, "note": "too_few_samples"}
    dist = springs["lps_stage"].value_counts().to_dict()
    dist = {str(k): int(v) for k, v in dist.items()}
    confirmed = int(springs[springs["lps_stage"] == "lps_confirmed"].shape[0])
    total = int(springs.shape[0])
    rate = round(confirmed / total, 4) if total > 0 else None
    return {"count": total, "lps_stage_distribution": dist, "lps_confirmed": confirmed, "lps_confirmed_rate": rate}


def _compute_pnf_divergence(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    has_div = ok[ok["pnf_phase_divergence"].notna() & (ok["pnf_phase_divergence"] != "")]
    no_div = ok[ok["pnf_phase_divergence"].isna() | (ok["pnf_phase_divergence"] == "")]
    groups = {}
    for label, sub in [("分歧", has_div), ("一致", no_div)]:
        fwd20 = sub["fwd_20d"].dropna()
        fwd60 = sub["fwd_60d"].dropna()
        groups[label] = {
            "count": int(len(sub)),
            "mean_fwd_20d": round(float(fwd20.mean()), 2) if len(fwd20) > 0 else None,
            "median_fwd_20d": round(float(fwd20.median()), 2) if len(fwd20) > 0 else None,
            "mean_fwd_60d": round(float(fwd60.mean()), 2) if len(fwd60) > 0 else None,
        }
    return groups


def _compute_vdb_empirical(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    groups = {}
    for label in ("none", "bullish_divergence", "bearish_divergence"):
        sub = ok[ok["vdb_divergence"] == label]
        if sub.empty:
            groups[label] = {"count": 0, "mean_fwd_20d": None, "median_fwd_20d": None}
            continue
        fwd20 = sub["fwd_20d"].dropna()
        groups[label] = {
            "count": int(len(sub)),
            "mean_fwd_20d": round(float(fwd20.mean()), 2) if len(fwd20) > 0 else None,
            "median_fwd_20d": round(float(fwd20.median()), 2) if len(fwd20) > 0 else None,
        }
    return groups


def _compute_markup_rs_empirical(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    markup = ok[ok["phase"] == "markup"]
    if markup.empty:
        return {}
    groups = {}
    for rs_label in ("leader", "follower", "systemic_decline", "weak_independent"):
        sub = markup[markup["relative_strength"] == rs_label]
        if sub.empty:
            continue
        fwd20 = sub["fwd_20d"].dropna()
        groups[rs_label] = {
            "count": int(len(sub)),
            "mean_fwd_20d": round(float(fwd20.mean()), 2) if len(fwd20) > 0 else None,
            "median_fwd_20d": round(float(fwd20.median()), 2) if len(fwd20) > 0 else None,
        }
    return groups


def compute_verification_report(df: pd.DataFrame) -> dict:
    ok = df[df.get("ok", True)].copy()
    emp = build_empirical_table(ok.to_dict("records"))
    report = {
        "total_symbols": int(len(df)),
        "ok_symbols": int(len(ok)),
        "phase_empirical": emp.get("phase", {}),
        "spring_empirical": emp.get("spring", {}),
        "confidence_empirical": emp.get("confidence_level", {}),
        "structural_rank_ic": _compute_structural_rank_ic(ok),
        "lps_conduction": _compute_lps_conduction(ok),
        "pnf_divergence": _compute_pnf_divergence(ok),
        "vdb_empirical": _compute_vdb_empirical(ok),
        "markup_rs_empirical": _compute_markup_rs_empirical(ok),
    }
    return report


def run_scan_and_verify(
    symbols: list[str],
    max_workers: int,
    output_dir: Path,
    as_of: str | None = None,
) -> dict:
    from scripts.wyckoff_full_scan import analyze_one

    storage = None
    from uniquant.data.lake.storage_manager import StorageManager
    storage = StorageManager(str(PROJECT_ROOT / "data"))
    index_df = load_index_df(storage)

    print(f"待分析股票: {len(symbols)} 只, workers={max_workers}")
    if as_of:
        print(f"回放模式 as_of={as_of}")

    from uniquant.brain.wyckoff.engine import WyckoffEngine
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

    df = pd.DataFrame(results)
    df = df.sort_values("symbol").reset_index(drop=True)
    csv_path = output_dir / f"wyckoff_verify_{len(symbols)}.csv"
    df.to_csv(csv_path, index=False)
    print(f"CSV: {csv_path}")

    summary = summarize(results)
    summary["duration_seconds"] = round(time.time() - t0, 1)
    json_path = output_dir / f"wyckoff_verify_{len(symbols)}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    report = compute_verification_report(df)
    report_path = output_dir / f"wyckoff_verify_{len(symbols)}_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    print(f"\n验证报告: {report_path}")
    print(f"结构评分 Rank-IC: {report['structural_rank_ic']}")
    print(f"LPS 传导率: {report['lps_conduction']}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff 实证验收闸门")
    parser.add_argument("--scan-csv", default=None, help="扫描 CSV 路径")
    parser.add_argument("--symbols", default=None, choices=["all", "main_board", "golden_20", "golden_100"],
                        help="扫描 symbol 列表（与 --scan-csv 互斥）")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-dir", default="/tmp/verify")
    parser.add_argument("--as-of", default=None, help="回放模式: 截断至该日期进行分析")
    args = parser.parse_args()

    if args.scan_csv:
        df = _load_scan_csv(args.scan_csv)
        print(f"读取 {len(df)} 条记录: {args.scan_csv}")
        report = compute_verification_report(df)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "verification_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(f"\n验证报告: {report_path}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if args.symbols:
        from uniquant.data.lake.storage_manager import StorageManager
        storage = StorageManager(str(PROJECT_ROOT / "data"))
        symbols = load_symbols(args.symbols, storage)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = run_scan_and_verify(symbols, args.max_workers, output_dir, as_of=args.as_of)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()