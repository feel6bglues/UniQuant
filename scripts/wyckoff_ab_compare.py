#!/usr/bin/env python3
"""Wyckoff A/B 对比脚本 — 对比默认配置与最佳校准配置的扫描结果。

用法:
    python3 scripts/wyckoff_ab_compare.py --symbols golden_100
    python3 scripts/wyckoff_ab_compare.py --symbols golden_20 --calib tight
    python3 scripts/wyckoff_ab_compare.py --symbols all --max-workers 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import StorageManager  # noqa: E402
from uniquant.brain.wyckoff.engine import WyckoffEngine  # noqa: E402
from uniquant.brain.wyckoff.models import WyckoffPhase  # noqa: E402


@dataclass
class ABResult:
    config_name: str
    config_params: dict
    phase_counts: dict = field(default_factory=dict)
    phase_fwd_20d: dict = field(default_factory=dict)
    total_stocks: int = 0
    accumulation_fwd_gt_markup: bool = False
    fwd_diff: float = 0.0
    phase_pct: dict = field(default_factory=dict)


# 校准组合
CALIB_CONFIGS = {
    "default": {},
    "tight": {
        "markup_short_trend_min": 0.05,
        "markup_relative_position_min": 0.65,
        "markup_cp_above_ma": 0.97,
        "distribution_prior_trend_min": 0.08,
        "accum_short_trend_max": -0.05,
        "accum_require_both_bc_sc": True,
        "markdown_short_trend_max": -0.08,
        "markdown_cp_below_ma": 0.95,
    },
    "moderate": {
        "markup_short_trend_min": 0.04,
        "markup_relative_position_min": 0.55,
        "markup_cp_above_ma": 0.97,
        "distribution_prior_trend_min": 0.06,
        "accum_short_trend_max": -0.03,
        "accum_require_both_bc_sc": False,
        "markdown_short_trend_max": -0.06,
        "markdown_cp_below_ma": 0.95,
    },
}


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


def _is_index(symbol: str) -> bool:
    code = symbol.split(".")[0]
    if not code.isdigit() or len(code) != 6:
        return False
    return code.startswith(("0000", "0001", "0002", "0003", "0009", "399"))


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


def _get_symbols(args) -> list[str]:
    storage = StorageManager()
    all_symbols = storage.get_symbols()
    all_symbols = [s for s in all_symbols if not _is_etf(s) and not _is_index(s)]
    if args.symbols == "all":
        return all_symbols
    if args.symbols == "main_board":
        return [s for s in all_symbols if s.startswith(("600", "601", "603", "000", "002", "300"))]
    if args.symbols == "golden_100":
        golden = _load_golden_list("golden_100.txt")
        return [s for s in all_symbols if s in golden]
    if args.symbols == "golden_20":
        golden = _load_golden_list("golden_20.txt")
        return [s for s in all_symbols if s in golden]
    return all_symbols


def _load_golden_list(name: str) -> set[str]:
    path = PROJECT_ROOT / "tests" / "benchmark" / name
    if not path.exists():
        return set()
    symbols = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            sym = line.split("#")[0].strip()
            if sym:
                symbols.add(sym)
    return symbols


def analyze_one(storage, symbol: str, calib_params: dict, as_of: str | None) -> dict | None:
    try:
        raw_df = storage.read_data(symbol, data_type="daily")
        if raw_df is None or raw_df.empty or len(raw_df) < 180:
            return None
        raw_df = raw_df[["date", "open", "high", "low", "close", "volume"]].copy()
        raw_df = raw_df.sort_values(by=["date"]).reset_index(drop=True)

        analysis_df = _truncate_to_as_of(raw_df, as_of)
        if len(analysis_df) < 120:
            return None

        analysis_last_idx = len(analysis_df) - 1
        if analysis_last_idx + 20 >= len(raw_df):
            analysis_last_idx = len(raw_df) - 60

        df = raw_df.iloc[max(0, analysis_last_idx - 119):analysis_last_idx + 1].copy()
        if len(df) < 60:
            return None

        engine = WyckoffEngine()
        engine.calibration = dict(calib_params)
        report = engine.analyze(df, symbol=symbol)

        if report is None or report.structure is None:
            return None

        phase = None
        if report.structure.phase == WyckoffPhase.ACCUMULATION:
            phase = "accumulation"
        elif report.structure.phase == WyckoffPhase.MARKUP:
            phase = "markup"
        elif report.structure.phase == WyckoffPhase.DISTRIBUTION:
            phase = "distribution"
        elif report.structure.phase == WyckoffPhase.MARKDOWN:
            phase = "markdown"
        else:
            phase = "unknown"

        fwd20, _ = _compute_fwd_returns(raw_df, analysis_last_idx)

        return {"symbol": symbol, "phase": phase, "fwd_20d": fwd20}
    except Exception:
        return None


def run_config(
    storage: StorageManager,
    symbols: list[str],
    calib_params: dict,
    config_name: str,
    max_workers: int,
    as_of: str | None,
) -> ABResult:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(analyze_one, storage, sym, calib_params, as_of): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    phase_counts: dict[str, int] = {}
    phase_fwd: dict[str, list[float]] = {}
    for r in results:
        p = r["phase"]
        phase_counts[p] = phase_counts.get(p, 0) + 1
        fwd = r["fwd_20d"]
        if fwd is not None:
            phase_fwd.setdefault(p, []).append(fwd)

    phase_fwd_20d: dict[str, float] = {}
    for p, fwds in phase_fwd.items():
        phase_fwd_20d[p] = float(np.mean(fwds)) if fwds else 0.0

    phase_pct: dict[str, float] = {}
    total = len(results)
    for p, cnt in phase_counts.items():
        phase_pct[p] = cnt / total * 100 if total > 0 else 0.0

    accum_fwd = phase_fwd_20d.get("accumulation", 0.0)
    markup_fwd = phase_fwd_20d.get("markup", 0.0)
    fwd_diff = accum_fwd - markup_fwd

    return ABResult(
        config_name=config_name,
        config_params=calib_params,
        phase_counts=phase_counts,
        phase_fwd_20d=phase_fwd_20d,
        total_stocks=total,
        accumulation_fwd_gt_markup=accum_fwd > markup_fwd,
        fwd_diff=fwd_diff,
        phase_pct=phase_pct,
    )


def build_comparison_table(results: list[ABResult]) -> str:
    lines = [
        "=" * 130,
        "Wyckoff A/B 对比 — 相位分布 + 收益变化",
        "=" * 130,
    ]
    for r in results:
        lines.append(f"\n--- 配置: {r.config_name} ---")
        lines.append(f"  总标的: {r.total_stocks}")
        lines.append(f"  accum_fwd > markup_fwd: {r.accumulation_fwd_gt_markup}")
        lines.append(f"  accum_fwd - markup_fwd (diff): {r.fwd_diff:+.2f}%")
        lines.append(f"  {'Phase':<20} {'Count':<8} {'Pct%':<8} {'Fwd20d%':<10}")
        lines.append(f"  {'-'*48}")
        for phase_name in ("accumulation", "markup", "distribution", "markdown", "unknown"):
            cnt = r.phase_counts.get(phase_name, 0)
            pct = r.phase_pct.get(phase_name, 0.0)
            fwd = r.phase_fwd_20d.get(phase_name, float("nan"))
            fwd_str = f"{fwd:+.2f}" if not np.isnan(fwd) else "N/A"
            lines.append(f"  {phase_name:<20} {cnt:<8} {pct:>6.1f}%  {fwd_str:<10}")
        lines.append("")

    if len(results) >= 2:
        lines.append("=" * 130)
        lines.append("变化对比 (A - B):")
        lines.append("=" * 130)
        a = results[0]
        b = results[1]
        lines.append(f"  A: {a.config_name} | B: {b.config_name}")
        lines.append(f"  accum_fwd: A={a.phase_fwd_20d.get('accumulation', 0):+.2f}% → "
                      f"B={b.phase_fwd_20d.get('accumulation', 0):+.2f}% "
                      f"(Δ={b.phase_fwd_20d.get('accumulation', 0) - a.phase_fwd_20d.get('accumulation', 0):+.2f}%)")
        lines.append(f"  markup_fwd: A={a.phase_fwd_20d.get('markup', 0):+.2f}% → "
                      f"B={b.phase_fwd_20d.get('markup', 0):+.2f}% "
                      f"(Δ={b.phase_fwd_20d.get('markup', 0) - a.phase_fwd_20d.get('markup', 0):+.2f}%)")
        lines.append(f"  diff (accum - markup): A={a.fwd_diff:+.2f}% → B={b.fwd_diff:+.2f}%")
        lines.append(f"  accumulation 占比: A={a.phase_pct.get('accumulation', 0):.1f}% → "
                      f"B={b.phase_pct.get('accumulation', 0):.1f}%")
        lines.append(f"  markup 占比: A={a.phase_pct.get('markup', 0):.1f}% → "
                      f"B={b.phase_pct.get('markup', 0):.1f}%")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Wyckoff A/B 对比")
    parser.add_argument("--symbols", default="golden_100", choices=["all", "main_board", "golden_100", "golden_20"])
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--output-dir", default="results/wyckoff_ab")
    parser.add_argument("--as-of", default=None, help="回放日期 (YYYY-MM-DD)")
    parser.add_argument("--calib", default="tight", choices=["tight", "moderate", "default"],
                        help="校准配置 (A=default, B=所选配置)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[A/B] 加载标的: {args.symbols}")
    symbols = _get_symbols(args)
    print(f"[A/B] 共 {len(symbols)} 只标的")

    storage = StorageManager()

    config_a = ("default", {})
    config_b = (args.calib, CALIB_CONFIGS[args.calib])

    results: list[ABResult] = []
    for name, params in [config_a, config_b]:
        print(f"\n[A/B] 运行: {name}")
        t0 = time.time()
        r = run_config(storage, symbols, params, name, args.max_workers, args.as_of)
        elapsed = time.time() - t0
        print(f"[A/B] {name}: {r.total_stocks} 只, {elapsed:.1f}s")
        print(f"      相位: {r.phase_counts}")
        print(f"      fwd_20d: {r.phase_fwd_20d}")
        results.append(r)

    table = build_comparison_table(results)
    print(f"\n{table}")

    report_path = output_dir / "ab_comparison_report.txt"
    report_path.write_text(table)
    print(f"\n[A/B] 报告写入: {report_path}")

    json_path = output_dir / "ab_comparison_results.json"
    json_data = [asdict(r) for r in results]
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))
    print(f"[A/B] JSON 写入: {json_path}")

    if len(results) >= 2:
        a, b = results[0], results[1]
        print("\n[A/B] 总结:")
        print(f"  默认配置 '{a.config_name}': accum_fwd={a.phase_fwd_20d.get('accumulation', 0):+.2f}%, "
              f"markup_fwd={a.phase_fwd_20d.get('markup', 0):+.2f}%")
        print(f"  校准配置 '{b.config_name}': accum_fwd={b.phase_fwd_20d.get('accumulation', 0):+.2f}%, "
              f"markup_fwd={b.phase_fwd_20d.get('markup', 0):+.2f}%")
        print(f"  Diff (accum - markup): A={a.fwd_diff:+.2f}% → B={b.fwd_diff:+.2f}%")
        if b.fwd_diff > a.fwd_diff:
            print(f"  ✅ 校准后 accumulation fwd > markup fwd 差距改善 {b.fwd_diff - a.fwd_diff:+.2f}%")
        else:
            print(f"  ❌ 校准未改善, 差距恶化 {b.fwd_diff - a.fwd_diff:+.2f}%")


if __name__ == "__main__":
    main()