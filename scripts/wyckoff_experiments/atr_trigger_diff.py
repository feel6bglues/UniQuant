#!/usr/bin/env python3
"""T4 — P1-1 ATR 相对化 before-after 触发集对照 (golden_100, 三窗)。

A = 现状 `_scan_spring` (engine.py:746-782): 固定深带 [0.985,1.0)×boundary_lower
B = 方案 P1-1: minBreak=max(atr*0.25, rangeWidth*2%), 跌破 boundary_lower−minBreak,
    维持量缩(vol_ratio≤0.8)与 1-2 列收回 (pine:265/279 对齐)。

漂移率 = |AΔB| / max(|A|,|B|)。

预注册阈值 (PREREGISTRATION T4 / 方案红线):
  漂移率 > 5% → 撤回 P1-1 或升级为 P0 独立验证; ≤5% → 采纳。

用法: python3 scripts/wyckoff_experiments/atr_trigger_diff.py [--golden golden_100.txt] [--round 2]
输出: results/wyckoff_experiments/atr_trigger_diff.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"pandas required: {_ie}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

DAILY = ROOT / "data" / "lake" / "quotes" / "daily"
ASOFS = {"W1": "2026-04-30", "W2": "2026-03-31", "W3": "2026-05-29"}
PRE_REGISTERED_DRIFT = 0.05


def load_symbols(golden_file: str) -> list[str]:
    p = ROOT / golden_file
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip().split("#")[0].strip()
        if line and "." in line:
            out.append(line)
    return out


def _load_engine():
    from uniquant.brain.indicators import Indicators  # noqa: F401
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    return WyckoffEngine, Indicators


def scan_spring_A(df: pd.DataFrame, boundary_lower: float) -> str | None:
    """现状 `_scan_spring` 复刻 (engine.py:746-782)。"""
    if boundary_lower <= 0 or len(df) < 5:
        return None
    recent = df.tail(30)
    vol_med = float(recent["volume"].median())
    if vol_med <= 0:
        return None
    lows = recent["low"].to_numpy()
    closes = recent["close"].to_numpy()
    vols = recent["volume"].to_numpy()
    dates = recent["date"].to_numpy()
    n = len(recent)
    for i in range(n):
        low = lows[i]
        if not (boundary_lower * 0.985 <= low < boundary_lower):
            continue
        vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
        if vol_ratio > 0.8:
            continue
        for j in range(i + 1, min(i + 3, n)):
            if closes[j] >= boundary_lower:
                return str(dates[i])
    return None


def scan_spring_B(
    df: pd.DataFrame, boundary_lower: float, boundary_upper: float, atr: float
) -> str | None:
    """方案 P1-1: minBreak=max(atr*0.25, rangeWidth*2%), 跌破下沿≥minBreak。"""
    if boundary_lower <= 0 or len(df) < 5:
        return None
    width = max(boundary_upper - boundary_lower, 1e-9)
    min_break = max(atr * 0.25, width * 0.02)
    recent = df.tail(30)
    vol_med = float(recent["volume"].median())
    if vol_med <= 0:
        return None
    lows = recent["low"].to_numpy()
    closes = recent["close"].to_numpy()
    vols = recent["volume"].to_numpy()
    dates = recent["date"].to_numpy()
    n = len(recent)
    for i in range(n):
        low = lows[i]
        if not (boundary_lower - min_break < low < boundary_lower):
            continue
        vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
        if vol_ratio > 0.8:
            continue
        for j in range(i + 1, min(i + 3, n)):
            if closes[j] >= boundary_lower:
                return str(dates[i])
    return None


def analyze_symbol(
    WyckoffEngine, Indicators, symbol: str, asof: str
) -> dict:
    f = DAILY / f"{symbol}.parquet"
    if not f.exists():
        return {"symbol": symbol, "error": "no data"}
    df = pd.read_parquet(f)
    if "date" not in df.columns or df.empty:
        return {"symbol": symbol, "error": "bad data"}
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= pd.Timestamp(asof)].reset_index(drop=True)
    if len(df) < 120:
        return {"symbol": symbol, "error": "too_short"}
    try:
        eng = WyckoffEngine()
        rpt = eng.analyze(df, symbol=symbol, period="日线", multi_timeframe=True)
    except Exception as e:
        return {"symbol": symbol, "error": f"engine: {type(e).__name__}"}
    try:
        bl = float(rpt.structure.trading_range_low)
        bu = float(rpt.structure.trading_range_high)
    except (AttributeError, TypeError, ValueError):
        return {"symbol": symbol, "error": "no TR"}

    atr = float(Indicators.calc_atr(df).iloc[-1] or 0.0)
    a = scan_spring_A(df, bl)
    b = scan_spring_B(df, bl, bu, atr)
    return {"symbol": symbol, "as_of": asof, "bound_low": bl, "bound_up": bu,
            "atr": atr, "A": a, "B": b}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="tests/benchmark/golden_100.txt")
    ap.add_argument("--symbols", nargs="*", default=[])
    ap.add_argument("--as-of", default="all")
    args = ap.parse_args()

    symbols = args.symbols or load_symbols(args.golden)
    wins = [w for w, _ in ASOFS.items() if args.as_of in ("all", w)]
    WyckoffEngine, Indicators = _load_engine()

    results: dict = {"pre_registered_drift_threshold": PRE_REGISTERED_DRIFT, "windows": {}}
    for w in wins:
        asof = ASOFS[w]
        per_symbol = [analyze_symbol(WyckoffEngine, Indicators, s, asof) for s in symbols]
        ok = [r for r in per_symbol if "error" not in r]
        a_set = {(r["symbol"], r["A"]) for r in ok if r["A"]}
        b_set = {(r["symbol"], r["B"]) for r in ok if r["B"]}
        only_a = {(s, d) for s, d in a_set if (s, d) not in b_set}
        only_b = {(s, d) for s, d in b_set if (s, d) not in a_set}
        drift_pct = (len(only_a) + len(only_b)) / max(len(a_set) | len(b_set), 1)
        verdict = "PASS" if drift_pct <= PRE_REGISTERED_DRIFT else "FAIL->撤回或升级P0"
        results["windows"][w] = {
            "as_of": asof,
            "n_symbols": len(ok),
            "n_A_triggers": len(a_set),
            "n_B_triggers": len(b_set),
            "only_A": sorted(only_a),
            "only_B": sorted(only_b),
            "drifting": len(only_a) + len(only_b),
            "drift_pct": round(drift_pct, 4),
            "verdict": verdict,
        }
        print(f"[{w}] A={len(a_set)} B={len(b_set)} only_A={len(only_a)} "
              f"only_B={len(only_b)} drift={drift_pct:.2%} -> {verdict}")

    out = ROOT / "results" / "wyckoff_experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "atr_trigger_diff.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())