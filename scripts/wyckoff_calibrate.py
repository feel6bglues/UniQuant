#!/usr/bin/env python3
"""Wyckoff 相位判定阈值校准脚本 — 扫描阈值组合, 找到最优参数。

用法:
    python3 scripts/wyckoff_calibrate.py --symbols golden_100
    python3 scripts/wyckoff_calibrate.py --symbols golden_20 --quick
    python3 scripts/wyckoff_calibrate.py --output-dir results/wyckoff_calibrate
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
class CalibrationConfig:
    name: str
    params: dict

    markup_short_trend_min: float = 0.03
    markup_relative_position_min: float = 0.50
    markup_cp_above_ma: float = 0.97
    distribution_prior_trend_min: float = 0.05
    accum_short_trend_max: float = -0.02
    accum_require_both_bc_sc: bool = False
    markdown_short_trend_max: float = -0.05
    markdown_cp_below_ma: float = 0.95


@dataclass
class ConfigResult:
    name: str
    params: dict
    phase_counts: dict = field(default_factory=dict)
    phase_fwd_20d: dict = field(default_factory=dict)
    total_stocks: int = 0
    accumulation_fwd_gt_markup: bool = False
    fwd_diff: float = 0.0  # accum_fwd - markup_fwd


# 推荐校准组合
DEFAULT_CONFIGS = [
    CalibrationConfig(
        name="default",
        params={},
    ),
    CalibrationConfig(
        name="tight",
        params={
            "markup_short_trend_min": 0.05,
            "markup_relative_position_min": 0.65,
            "markup_cp_above_ma": 0.97,
            "distribution_prior_trend_min": 0.08,
            "accum_short_trend_max": -0.05,
            "accum_require_both_bc_sc": True,
            "markdown_short_trend_max": -0.08,
            "markdown_cp_below_ma": 0.95,
        },
    ),
    CalibrationConfig(
        name="moderate",
        params={
            "markup_short_trend_min": 0.04,
            "markup_relative_position_min": 0.55,
            "markup_cp_above_ma": 0.97,
            "distribution_prior_trend_min": 0.06,
            "accum_short_trend_max": -0.03,
            "accum_require_both_bc_sc": False,
            "markdown_short_trend_max": -0.06,
            "markdown_cp_below_ma": 0.95,
        },
    ),
    CalibrationConfig(
        name="loose_accum",
        params={
            "markup_short_trend_min": 0.03,
            "markup_relative_position_min": 0.50,
            "markup_cp_above_ma": 0.97,
            "distribution_prior_trend_min": 0.05,
            "accum_short_trend_max": -0.01,
            "accum_require_both_bc_sc": False,
            "markdown_short_trend_max": -0.05,
            "markdown_cp_below_ma": 0.95,
        },
    ),
    CalibrationConfig(
        name="tightest",
        params={
            "markup_short_trend_min": 0.06,
            "markup_relative_position_min": 0.70,
            "markup_cp_above_ma": 0.98,
            "distribution_prior_trend_min": 0.10,
            "accum_short_trend_max": -0.06,
            "accum_require_both_bc_sc": True,
            "markdown_short_trend_max": -0.10,
            "markdown_cp_below_ma": 0.92,
        },
    ),
]


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


def analyze_one(storage, symbol: str, calib: CalibrationConfig, as_of: str | None) -> dict | None:
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
        engine.calibration = dict(calib.params)
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
    calib: CalibrationConfig,
    max_workers: int,
    as_of: str | None,
) -> ConfigResult:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(analyze_one, storage, sym, calib, as_of): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    phase_counts: dict[str, int] = {}
    phase_fwd: dict[str, list[float]] = {}
    for r in results:
        phase = r["phase"]
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        fwd = r["fwd_20d"]
        if fwd is not None:
            phase_fwd.setdefault(phase, []).append(fwd)

    phase_fwd_20d: dict[str, float] = {}
    for phase, fwds in phase_fwd.items():
        phase_fwd_20d[phase] = float(np.mean(fwds)) if fwds else 0.0

    accum_fwd = phase_fwd_20d.get("accumulation", 0.0)
    markup_fwd = phase_fwd_20d.get("markup", 0.0)
    fwd_diff = accum_fwd - markup_fwd

    return ConfigResult(
        name=calib.name,
        params=calib.params,
        phase_counts=phase_counts,
        phase_fwd_20d=phase_fwd_20d,
        total_stocks=len(results),
        accumulation_fwd_gt_markup=accum_fwd > markup_fwd,
        fwd_diff=fwd_diff,
    )


def build_empirical_table(config_results: list[ConfigResult]) -> str:
    lines = [
        "=" * 120,
        "Wyckoff 相位判定阈值校准 — 实证对比表",
        "=" * 120,
        f"{'Config':<20} {'Phase':<16} {'Count':<8} {'Fwd20d%':<10} {'Total':<8} {'Accum>Markup':<14} {'Diff':<10}",
        "-" * 120,
    ]
    for cr in config_results:
        first = True
        for phase_name in ("accumulation", "markup", "distribution", "markdown", "unknown"):
            cnt = cr.phase_counts.get(phase_name, 0)
            fwd = cr.phase_fwd_20d.get(phase_name, float("nan"))
            fwd_str = f"{fwd:+.2f}" if not np.isnan(fwd) else "N/A"
            label = cr.name if first else ""
            lines.append(
                f"{label:<20} {phase_name:<16} {cnt:<8} {fwd_str:<10} "
                f"{cr.total_stocks if first else '':<8} "
                f"{'YES' if cr.accumulation_fwd_gt_markup else 'NO':<14} "
                f"{cr.fwd_diff:+.2f} {'' if not first else ''}"
            )
            first = False
    lines.append("=" * 120)
    return "\n".join(lines)


def find_best_config(config_results: list[ConfigResult]) -> ConfigResult:
    scored = []
    for cr in config_results:
        score = 0.0
        if cr.accumulation_fwd_gt_markup:
            score += 10.0
        score += cr.fwd_diff  # positive diff is good
        if cr.phase_counts:
            max_phase_pct = max(cr.phase_counts.values()) / max(cr.total_stocks, 1) * 100
            if max_phase_pct <= 50:
                score += 5.0
        scored.append((score, cr))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else config_results[0]


def main():
    parser = argparse.ArgumentParser(description="Wyckoff 相位判定阈值校准")
    parser.add_argument("--symbols", default="golden_100", choices=["all", "main_board", "golden_100", "golden_20"])
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--output-dir", default="results/wyckoff_calibrate")
    parser.add_argument("--as-of", default=None, help="回放日期 (YYYY-MM-DD)")
    parser.add_argument("--quick", action="store_true", help="只跑 default + tight 两个组合")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[校准] 加载标的列表: {args.symbols}")
    symbols = _get_symbols(args)
    print(f"[校准] 共 {len(symbols)} 只标的")

    storage = StorageManager()

    configs = DEFAULT_CONFIGS[:2] if args.quick else DEFAULT_CONFIGS

    results: list[ConfigResult] = []
    for calib in configs:
        print(f"\n[校准] 运行配置: {calib.name} ({calib.params})")
        t0 = time.time()
        cr = run_config(storage, symbols, calib, args.max_workers, args.as_of)
        elapsed = time.time() - t0
        print(f"[校准] {calib.name}: {cr.total_stocks} 只, {elapsed:.1f}s")
        print(f"       相位分布: {cr.phase_counts}")
        print(f"       fwd_20d: {cr.phase_fwd_20d}")
        print(f"       accum_fwd > markup_fwd: {cr.accumulation_fwd_gt_markup} (diff={cr.fwd_diff:+.2f})")
        results.append(cr)

    table = build_empirical_table(results)
    print(f"\n{table}")

    report_path = output_dir / "calibration_report.txt"
    report_path.write_text(table)
    print(f"\n[校准] 报告写入: {report_path}")

    best = find_best_config(results)
    print(f"\n[校准] 最佳配置: {best.name}")
    print(f"       params: {best.params}")
    print(f"       accum_fwd > markup_fwd: {best.accumulation_fwd_gt_markup}")
    print(f"       fwd_diff: {best.fwd_diff:+.2f}")

    json_path = output_dir / "calibration_results.json"
    json_data = []
    for cr in results:
        json_data.append(asdict(cr))
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))
    print(f"[校准] JSON 数据写入: {json_path}")

    print("\n[校准] 建议校准参数:")
    print(f"       {json.dumps(best.params, indent=8)}")


if __name__ == "__main__":
    main()