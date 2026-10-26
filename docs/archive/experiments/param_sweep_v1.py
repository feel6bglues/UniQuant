#!/usr/bin/env python3
"""
Script v1 — 参数扫描验证脚本

验证 walk-forward 结论对不同参数组合的稳健性:
  - window_size: [120, 252]
  - range_threshold: [0.20, 0.30, 0.40]
  - trend_threshold: [0.05, 0.08]

输出: golden_20 上各参数组合的 Spring/UTAD/TR/Phase 分布 + fwd 收益
"""
import os
import sys
import time
import warnings
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import List

import pandas as pd
from scipy.stats import ttest_ind

warnings.filterwarnings("ignore")
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

SRC = Path("/home/james/Documents/Project/UniQuant")
sys.path.insert(0, str(SRC / "src"))

from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import WyckoffReport

DATA_DIR = SRC / "data/lake/quotes/daily"
GOLDEN_DIR = SRC / "tests/benchmark"
OUT_DIR = SRC / "scripts/output"

FW = [5, 10, 20, 60]

# ── Sweep params ──────────────────────────────────────────────
WINDOW_SIZES = [120, 252]
RANGE_THRESHOLDS = [0.20, 0.30, 0.40]
TREND_THRESHOLDS = [0.05, 0.08]
STEP = 20
MAX_WINDOWS = 6
MIN_BARS = 504          # 252*2 — enough for longest window + fwd

@dataclass
class WindowResult:
    symbol: str
    window_size: int
    range_threshold: float
    trend_threshold: float
    window_idx: int
    # Phase
    phase: str = ""
    sub_phase: str = ""
    unknown_candidate: str = ""
    # Signal
    signal_type: str = ""
    spring_detected: bool = False
    utad_detected: bool = False
    # TR
    tr_detected: bool = False
    tr_upper: float = 0.0
    tr_lower: float = 0.0
    # Trading plan
    tp_direction: str = ""
    # Confidence
    confidence: str = ""
    # Forward returns
    fwd_5d: float = 0.0
    fwd_10d: float = 0.0
    fwd_20d: float = 0.0
    fwd_60d: float = 0.0
    # Error
    error: str = ""


def load_symbols(name: str = "golden_20") -> List[str]:
    path = GOLDEN_DIR / f"{name}.txt"
    with open(path) as f:
        out = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            symbol = line.split("#")[0].strip()
            if symbol:
                out.append(symbol)
        return out


def extract_report(rep: WyckoffReport) -> dict:
    """Extract structured fields from a WyckoffReport."""
    out = {"phase": "", "sub_phase": "", "unknown_candidate": "",
           "signal_type": "", "spring": False, "utad": False,
           "tr_detected": False, "tr_upper": 0.0, "tr_lower": 0.0,
           "tp_direction": "", "confidence": ""}

    if not rep:
        return out

    # Phase
    if hasattr(rep, "structure") and rep.structure:
        p = rep.structure.phase
        out["phase"] = str(p.value if hasattr(p, "value") else (p or ""))
        sp = getattr(rep.structure, "sub_phase", None)
        out["sub_phase"] = sp or ""
        uc = getattr(rep.structure, "unknown_candidate", None)
        out["unknown_candidate"] = uc or ""

    # Signal
    if hasattr(rep, "signal") and rep.signal:
        s = rep.signal
        out["signal_type"] = str(getattr(s, "signal_type", ""))
        out["spring"] = getattr(s, "signal_type", "") == "spring"
        out["utad"] = getattr(s, "signal_type", "") == "utad"
        c = getattr(s, "confidence", None)
        out["confidence"] = str(c.value if hasattr(c, "value") else (c or ""))

    # TR
    if hasattr(rep, "structure") and rep.structure:
        st = rep.structure
        thu = getattr(st, "trading_range_high", None)
        thl = getattr(st, "trading_range_low", None)
        out["tr_upper"] = float(thu) if thu else 0.0
        out["tr_lower"] = float(thl) if thl else 0.0
        out["tr_detected"] = out["tr_upper"] > 0 and out["tr_lower"] > 0

    # Trading plan
    if hasattr(rep, "trading_plan") and rep.trading_plan:
        tp = rep.trading_plan
        d = getattr(tp, "direction", "")
        out["tp_direction"] = d or ""

    return out


def analyze_stock(symbol: str) -> List[dict]:
    """Run all param combos on one stock."""
    # Load data
    try:
        df = pd.read_parquet(DATA_DIR / f"{symbol}.parquet")
    except Exception as e:
        return [asdict(WindowResult(symbol=symbol, error=f"load_fail:{e}",
                                    window_size=0, range_threshold=0.0, trend_threshold=0.0, window_idx=0))]

    close = df["close"].values
    n = len(close)
    if n < MIN_BARS:
        return [asdict(WindowResult(symbol=symbol, error=f"insufficient_data:{n}<{MIN_BARS}",
                                    window_size=0, range_threshold=0.0, trend_threshold=0.0, window_idx=0))]

    results = []

    for ws in WINDOW_SIZES:
        for rt in RANGE_THRESHOLDS:
            for tt in TREND_THRESHOLDS:
                eng = WyckoffEngine(range_threshold=rt, trend_threshold=tt)

                # Generate windows: last N points, slide back
                max_start = n - ws - max(FW)
                starts = list(range(max_start, ws - 1, -STEP))[:MAX_WINDOWS]

                for idx, start in enumerate(starts):
                    segment = df.iloc[start - ws:start]
                    try:
                        rep = eng.analyze(segment, symbol=symbol, multi_timeframe=False)
                        ext = extract_report(rep)
                    except Exception:
                        ext = {"phase": "ERROR", "signal_type": "", "spring": False,
                               "utad": False, "tr_detected": False, "tr_upper": 0.0,
                               "tr_lower": 0.0, "tp_direction": "", "confidence": "",
                               "sub_phase": "", "unknown_candidate": ""}

                    # Forward returns
                    c_seg = close[start - ws:start]
                    base = c_seg[-1]
                    fwd = {}
                    for fd in FW:
                        target_idx = start + fd
                        if target_idx < n:
                            fwd[f"fwd_{fd}d"] = round(float((close[target_idx] / base - 1) * 100), 2)
                        else:
                            fwd[f"fwd_{fd}d"] = 0.0

                    wr = WindowResult(
                        symbol=symbol, window_size=ws,
                        range_threshold=rt, trend_threshold=tt,
                        window_idx=idx,
                        phase=ext["phase"], sub_phase=ext["sub_phase"],
                        unknown_candidate=ext["unknown_candidate"],
                        signal_type=ext["signal_type"],
                        spring_detected=ext["spring"],
                        utad_detected=ext["utad"],
                        tr_detected=ext["tr_detected"],
                        tr_upper=ext["tr_upper"], tr_lower=ext["tr_lower"],
                        tp_direction=ext["tp_direction"],
                        confidence=ext["confidence"],
                        fwd_5d=fwd["fwd_5d"], fwd_10d=fwd["fwd_10d"],
                        fwd_20d=fwd["fwd_20d"], fwd_60d=fwd["fwd_60d"],
                    )
                    results.append(asdict(wr))

    return results


def run_scan():
    symbols = load_symbols("golden_20")
    print(f"Symbols: {len(symbols)}")
    print(f"Param combos: {len(WINDOW_SIZES)}×{len(RANGE_THRESHOLDS)}×{len(TREND_THRESHOLDS)} = "
          f"{len(WINDOW_SIZES)*len(RANGE_THRESHOLDS)*len(TREND_THRESHOLDS)}")
    print(f"Workers: {os.cpu_count() or 4}")
    t0 = time.perf_counter()

    all_rows = []
    with ProcessPoolExecutor(max_workers=(os.cpu_count() or 4) - 1) as pool:
        fut = {pool.submit(analyze_stock, s): s for s in symbols}
        for f in as_completed(fut):
            try:
                all_rows.extend(f.result())
            except Exception as e:
                print(f"  FAIL {fut[f]}: {e}")
            done = sum(1 for _ in fut if _.done())
            if done % 5 == 0:
                print(f"  {done}/{len(symbols)} done", flush=True)

    df = pd.DataFrame(all_rows)
    out_path = OUT_DIR / "param_sweep_v1_results.parquet"
    df.to_parquet(out_path)
    print(f"\nSaved: {out_path}  ({len(df)} rows, {time.perf_counter()-t0:.0f}s)")

    # ── Report ──────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("PARAM SWEEP REPORT v1")
    print(f"{'='*80}")

    for ws in WINDOW_SIZES:
        for rt in RANGE_THRESHOLDS:
            for tt in TREND_THRESHOLDS:
                sub = df[(df["window_size"] == ws) &
                         (df["range_threshold"] == rt) &
                         (df["trend_threshold"] == tt)]
                if sub.empty:
                    continue

                n = len(sub)
                spring_n = sub["spring_detected"].sum()
                utad_n = sub["utad_detected"].sum()
                tr_n = sub["tr_detected"].sum()
                phases = sub["phase"].value_counts()
                buy_n = len(sub[sub["tp_direction"] == "买入"])
                sell_n = len(sub[sub["tp_direction"] == "卖出"])

                # Forward return: buy vs non-buy
                buy = sub[sub["tp_direction"] == "买入"]
                nobuy = sub[sub["tp_direction"] == ""]
                buy_str = ""
                if len(buy) >= 3 and len(nobuy) >= 3:
                    t, p = ttest_ind(buy["fwd_20d"], nobuy["fwd_20d"])
                    buy_str = f"  buy_fwd20={buy['fwd_20d'].mean():+.2f}%  nobuy_fwd20={nobuy['fwd_20d'].mean():+.2f}%  p={p:.4f}"

                print(f"\nW={ws:3d} RT={rt:.2f} TT={tt:.2f}  n={n:3d}  "
                      f"Spring={spring_n:2d}  UTAD={utad_n:2d}  TR={tr_n:2d}  "
                      f"Buy={buy_n:2d}  Sell={sell_n:2d}")
                print(f"  Phases: {dict(phases)}")
                if buy_str:
                    print(f"  {buy_str}")

    # ── Compare with walk-forward baseline ──────────────────
    print(f"\n{'─'*80}")
    print("BASELINE COMPARISON (W=120 RT=0.20 TT=0.05)")
    bl = df[(df["window_size"] == 120) & (df["range_threshold"] == 0.20) & (df["trend_threshold"] == 0.05)]
    print(f"  Spring: {bl['spring_detected'].sum()} / {len(bl)}")
    print(f"  UTAD:   {bl['utad_detected'].sum()} / {len(bl)}")
    print(f"  TR:     {bl['tr_detected'].sum()} / {len(bl)}")
    print(f"  Buy:    {len(bl[bl['tp_direction']=='买入'])} / {len(bl)}")
    print(f"  Sell:   {len(bl[bl['tp_direction']=='卖出'])} / {len(bl)}")
    print(f"  UNKNOWN: {len(bl[bl['phase']=='unknown'])} / {len(bl)}")

    print(f"\nDone: {time.perf_counter()-t0:.0f}s")


if __name__ == "__main__":
    run_scan()
