#!/usr/bin/env python3
"""Wyckoff 多周期多阶段实证分析。

对多个 as-of 日期运行 Wyckoff 扫描，输出相位分布、前向收益、阶段转换统计
和经典 Wyckoff 理论一致性评估。

用法:
    python3 scripts/wyckoff_multi_period_analysis.py --symbols golden_100
    python3 scripts/wyckoff_multi_period_analysis.py --symbols golden_100 --output-dir /tmp/multi_period
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

from scripts.wyckoff_full_scan import (  # noqa: E402
    analyze_one,
    load_symbols,
    load_index_df,
    summarize,
    build_empirical_table,
)
from uniquant.data.lake.storage_manager import StorageManager  # noqa: E402
from uniquant.brain.wyckoff.engine import WyckoffEngine  # noqa: E402

AS_OF_DATES = [
    "2024-01-31",
    "2024-06-28",
    "2024-12-31",
    "2025-06-30",
    "2026-01-30",
    "2026-05-15",
]

PHASE_CYCLE = ["accumulation", "markup", "distribution", "markdown"]


def run_period_scan(
    symbols: list[str],
    as_of: str,
    max_workers: int,
) -> list[dict]:
    storage = StorageManager(str(PROJECT_ROOT / "data"))
    index_df = load_index_df(storage)
    engine = WyckoffEngine()
    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(analyze_one, s, storage, index_df, engine, as_of): s
            for s in symbols
        }
        done = 0
        for fut in as_completed(futures):
            done += 1
            rec = fut.result()
            results.append(rec)
            if done % 50 == 0 or done == len(symbols):
                elapsed = time.time() - t0
                print(f"  [{as_of}] {done}/{len(symbols)} ({elapsed:.1f}s)")
    print(f"  [{as_of}] 完成: {len(results)} 只, {time.time()-t0:.1f}s")
    return results


def compute_lps_conduction_rate(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    spring_count = sum(1 for r in ok if r.get("spring"))
    lps_confirmed = sum(1 for r in ok if r.get("lps_stage") == "lps_confirmed")
    lps_test_held = sum(1 for r in ok if r.get("lps_stage") == "test_held")
    return {
        "spring_count": spring_count,
        "lps_confirmed": lps_confirmed,
        "lps_test_held": lps_test_held,
        "lps_conduction_rate": round(lps_confirmed / max(spring_count, 1), 4),
        "lps_any_rate": round((lps_confirmed + lps_test_held) / max(spring_count, 1), 4),
    }


def compute_phase_forward_stats(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    phases = {}
    for r in ok:
        ph = r.get("phase", "unknown")
        f20 = r.get("fwd_20d")
        f60 = r.get("fwd_60d")
        if ph not in phases:
            phases[ph] = {"fwd_20d": [], "fwd_60d": []}
        if f20 is not None and not (isinstance(f20, float) and np.isnan(f20)):
            phases[ph]["fwd_20d"].append(f20)
        if f60 is not None and not (isinstance(f60, float) and np.isnan(f60)):
            phases[ph]["fwd_60d"].append(f60)
    out = {}
    for ph, vals in phases.items():
        f20 = vals["fwd_20d"]
        f60 = vals["fwd_60d"]
        win_rate = round(sum(1 for v in f20 if v > 0) / max(len(f20), 1) * 100, 1) if f20 else 0.0
        out[ph] = {
            "count": len(f20),
            "mean_fwd_20d": round(float(np.mean(f20)), 2) if f20 else None,
            "median_fwd_20d": round(float(np.median(f20)), 2) if f20 else None,
            "std_fwd_20d": round(float(np.std(f20)), 2) if f20 else None,
            "win_rate_20d": win_rate,
            "mean_fwd_60d": round(float(np.mean(f60)), 2) if f60 else None,
            "median_fwd_60d": round(float(np.median(f60)), 2) if f60 else None,
        }
    return out


def build_phase_transition_matrix(
    period_results: dict[str, list[dict]],
) -> dict:
    symbols = set()
    for pr in period_results.values():
        for r in pr:
            if r.get("ok"):
                symbols.add(r["symbol"])

    transitions = {}
    dates = sorted(period_results.keys())
    for sym in sorted(symbols):
        phases = {}
        for d in dates:
            for r in period_results[d]:
                if r["symbol"] == sym and r.get("ok"):
                    phases[d] = r["phase"]
        seq = [phases.get(d, "N/A") for d in dates]
        transitions[sym] = {
            "phases": seq,
            "dates": dates,
        }

    correct_forward = 0
    total_transitions = 0
    for sym, info in transitions.items():
        seq = info["phases"]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            if a == "N/A" or b == "N/A":
                continue
            total_transitions += 1
            if a == "accumulation" and b in ("markup", "accumulation"):
                correct_forward += 1
            elif a == "markup" and b in ("distribution", "markup"):
                correct_forward += 1
            elif a == "distribution" and b in ("markdown", "distribution"):
                correct_forward += 1
            elif a == "markdown" and b in ("accumulation", "markdown"):
                correct_forward += 1
            else:
                correct_forward += 0
    transition_matrix = {}
    for a_phase in PHASE_CYCLE + ["unknown"]:
        for b_phase in PHASE_CYCLE + ["unknown", "N/A"]:
            count = 0
            for sym, info in transitions.items():
                seq = info["phases"]
                for i in range(len(seq) - 1):
                    if seq[i] == a_phase and seq[i + 1] == b_phase:
                        count += 1
            if count > 0:
                transition_matrix[f"{a_phase}->{b_phase}"] = count

    return {
        "symbol_count": len(symbols),
        "total_transitions": total_transitions,
        "correct_transitions": correct_forward,
        "correct_transition_rate": round(correct_forward / max(total_transitions, 1), 4),
        "transition_matrix": transition_matrix,
        "symbol_transitions": transitions,
    }


def evaluate_wyckoff_theory(period_stats: dict[str, dict]) -> dict:
    results = []
    for as_of, stats in period_stats.items():
        row = {"as_of": as_of}
        for ph in PHASE_CYCLE:
            if ph in stats:
                row[f"{ph}_mean_fwd_20d"] = stats[ph].get("mean_fwd_20d")
                row[f"{ph}_median_fwd_20d"] = stats[ph].get("median_fwd_20d")
                row[f"{ph}_win_rate"] = stats[ph].get("win_rate_20d")
            else:
                row[f"{ph}_mean_fwd_20d"] = None
                row[f"{ph}_median_fwd_20d"] = None
                row[f"{ph}_win_rate"] = None

        accum_ok = (row.get("accumulation_mean_fwd_20d") or 0) > 0
        markup_ok = (row.get("markup_mean_fwd_20d") or 0) > 0
        dist_ok = (row.get("distribution_mean_fwd_20d") or 0) < 0
        markdown_ok = (row.get("markdown_mean_fwd_20d") or 0) < 0

        passed = [accum_ok, markup_ok, dist_ok, markdown_ok]
        row["accumulation_pass"] = accum_ok
        row["markup_pass"] = markup_ok
        row["distribution_pass"] = dist_ok
        row["markdown_pass"] = markdown_ok
        row["theory_passed"] = sum(1 for p in passed if p)
        row["theory_total"] = 4
        row["theory_score"] = round(row["theory_passed"] / 4 * 100, 1)
        results.append(row)

    overall_passed = sum(r["theory_passed"] for r in results)
    overall_total = sum(r["theory_total"] for r in results)
    return {
        "period_results": results,
        "overall_score": round(overall_passed / max(overall_total, 1) * 100, 1),
        "overall_passed": overall_passed,
        "overall_total": overall_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff 多周期多阶段实证分析")
    parser.add_argument("--symbols", default="golden_100",
                        choices=["golden_20", "golden_100"])
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-dir",
                        default=str(PROJECT_ROOT / "results" / "multi_period"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageManager(str(PROJECT_ROOT / "data"))
    symbols = load_symbols(args.symbols, storage)
    print(f"符号列表: {len(symbols)} 只")
    print(f"As-of 日期: {AS_OF_DATES}")

    period_results: dict[str, list[dict]] = {}
    period_summaries: dict[str, dict] = {}
    period_empirical: dict[str, dict] = {}
    period_phase_stats: dict[str, dict] = {}

    for as_of in AS_OF_DATES:
        print(f"\n{'='*60}")
        print(f"扫描 as_of={as_of}")
        print(f"{'='*60}")
        t0 = time.time()
        results = run_period_scan(symbols, as_of, args.max_workers)
        elapsed = time.time() - t0
        period_results[as_of] = results

        summary = summarize(results)
        summary["duration_seconds"] = round(elapsed, 1)
        period_summaries[as_of] = summary

        emp = build_empirical_table(results)
        period_empirical[as_of] = emp

        pstats = compute_phase_forward_stats(results)
        period_phase_stats[as_of] = pstats

        lps = compute_lps_conduction_rate(results)
        print(f"  相位分布: {summary['phase_distribution']}")
        print(f"  置信度分布: {summary['confidence_distribution']}")
        print(f"  结构评分分位: {summary['structural_score_percentiles']}")
        print(f"  LPS传导率: {lps}")

    print(f"\n{'='*60}")
    print("构建阶段转换矩阵...")
    transition_data = build_phase_transition_matrix(period_results)

    print("构建理论评估...")
    theory_eval = evaluate_wyckoff_theory(period_phase_stats)

    print("保存结果...")
    output = {
        "as_of_dates": AS_OF_DATES,
        "symbols_count": len(symbols),
        "period_summaries": period_summaries,
        "period_empirical": period_empirical,
        "period_phase_forward_stats": period_phase_stats,
        "phase_transition_analysis": {
            "symbol_count": transition_data["symbol_count"],
            "total_transitions": transition_data["total_transitions"],
            "correct_transitions": transition_data["correct_transitions"],
            "correct_transition_rate": transition_data["correct_transition_rate"],
            "transition_matrix": transition_data["transition_matrix"],
        },
        "wyckoff_theory_evaluation": theory_eval,
    }

    json_path = output_dir / f"wyckoff_multi_period_{args.symbols}.json"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    print(f"\nJSON 报告: {json_path}")

    csv_path = output_dir / f"wyckoff_multi_period_{args.symbols}.csv"
    rows = []
    for as_of, results in period_results.items():
        for r in results:
            rows.append({
                "as_of": as_of,
                "symbol": r.get("symbol", ""),
                "ok": r.get("ok", False),
                "phase": r.get("phase", "unknown"),
                "confidence_level": r.get("confidence_level", ""),
                "structural_score": r.get("structural_score", 0.0),
                "fwd_20d": r.get("fwd_20d"),
                "fwd_60d": r.get("fwd_60d"),
                "relative_strength": r.get("relative_strength", ""),
                "spring": r.get("spring", False),
                "utad": r.get("utad", False),
                "lps_stage": r.get("lps_stage", "not_test"),
                "error": r.get("error", ""),
            })
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(f"CSV 明细: {csv_path}")

    print(f"\n{'='*60}")
    print("经典 Wyckoff 理论一致性评估")
    print(f"{'='*60}")
    print(f"\n{'as_of':<14} {'accum_fwd':>10} {'markup_fwd':>10} {'dist_fwd':>10} {'md_fwd':>10} {'score':>7}")
    print("-" * 65)
    for pr in theory_eval["period_results"]:
        a = pr.get("accumulation_mean_fwd_20d") or 0
        m = pr.get("markup_mean_fwd_20d") or 0
        d = pr.get("distribution_mean_fwd_20d") or 0
        md = pr.get("markdown_mean_fwd_20d") or 0
        s = pr["theory_score"]
        print(f"{pr['as_of']:<14} {a:>+9.2f}% {m:>+9.2f}% {d:>+9.2f}% {md:>+9.2f}% {s:>6.1f}%")

    te = theory_eval
    print(f"\n总体理论一致性: {te['overall_score']}% ({te['overall_passed']}/{te['overall_total']})")

    ta = output["phase_transition_analysis"]
    print("\n阶段转换统计:")
    print(f"  总股票: {ta['symbol_count']}")
    print(f"  总转换次数: {ta['total_transitions']}")
    print(f"  正确转换次数: {ta['correct_transitions']}")
    print(f"  正确转换率: {ta['correct_transition_rate']*100:.1f}%")

    score = te["overall_score"]
    tr = ta["correct_transition_rate"] * 100
    if score >= 75 and tr >= 50:
        verdict = "✅ 落地良好 — 引擎基本实现经典 Wyckoff 模型"
    elif score >= 50 and tr >= 30:
        verdict = "⚠️ 部分落地 — 引擎在部分市场环境下有效，但需持续改进"
    else:
        verdict = "❌ 未落地 — 引擎与经典 Wyckoff 理论存在显著偏差"

    print(f"\n最终落地评估: {verdict}")


if __name__ == "__main__":
    main()