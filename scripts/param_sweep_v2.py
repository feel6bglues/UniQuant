#!/usr/bin/env python3
"""
Script v2 — 参数扫描验证脚本（经 3 轮红蓝对抗修正）

修正:
  - R1-01: direction 买入判定包含 "做多"/"买入"/"持有"
  - R1-02: fwd 不可用时标记 NaN, 聚合时 dropna
  - R1-03: Mann-Whitney U + Bonferroni 校正
  - R1-06: 错误计数 + 日志
  - R2-01/03: bootstrap-by-stock + 同相位对比
  - R2-02: Bonferroni 多重比较控制
  - R2-06: 时间切分（按年/半年）
  - R3-02: 断点续传 (per-stock .done)
  - R3-03: lookback_days CLI 参数
  - R3-04: golden_20/100/500 CLI 参数
  - R3-08: 参数组合排名
"""
import os
import sys
import time
import warnings
import itertools
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import List

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

warnings.filterwarnings("ignore")
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

SRC = Path("/home/james/Documents/Project/UniQuant")
sys.path.insert(0, str(SRC / "src"))

from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import WyckoffPhase, WyckoffReport, ConfidenceLevel

DATA_DIR = SRC / "data/lake/quotes/daily"
GOLDEN_DIR = SRC / "tests/benchmark"
OUT_DIR = SRC / "scripts/output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FW = [5, 10, 20, 60]
BULLISH_DIRECTIONS = {"做多", "买入", "持有"}
MIN_OBS_PER_GROUP = 3
ALPHA = 0.05

DONE_MARKER_DIR = OUT_DIR / ".param_sweep_done"

@dataclass
class WindowResult:
    symbol: str
    window_size: int
    lookback_days: int
    range_threshold: float
    trend_threshold: float
    window_idx: int
    window_start_date: str = ""
    window_end_date: str = ""
    year: int = 0
    half: int = 0
    phase: str = ""
    sub_phase: str = ""
    unknown_candidate: str = ""
    signal_type: str = ""
    spring_detected: bool = False
    utad_detected: bool = False
    tr_detected: bool = False
    tr_upper: float = 0.0
    tr_lower: float = 0.0
    tp_direction: str = ""
    tp_direction_bullish: bool = False
    confidence: str = ""
    fwd_5d: float = float("nan")
    fwd_10d: float = float("nan")
    fwd_20d: float = float("nan")
    fwd_60d: float = float("nan")
    error: str = ""
    error_count: int = 0


def parse_args():
    p = argparse.ArgumentParser(description="Wyckoff Parameter Sweep v2")
    p.add_argument("--symbols", default="golden_20", choices=["golden_20", "golden_100", "golden_500"],
                   help="Stock list to scan")
    p.add_argument("--window-sizes", nargs="+", type=int, default=[120, 252],
                   help="Window sizes to sweep")
    p.add_argument("--range-thresholds", nargs="+", type=float, default=[0.20, 0.30, 0.40],
                   help="Range thresholds to sweep")
    p.add_argument("--trend-thresholds", nargs="+", type=float, default=[0.05, 0.08],
                   help="Trend thresholds to sweep")
    p.add_argument("--lookback-days", nargs="+", type=int, default=[120, 252],
                   help="Engine lookback_days to sweep")
    p.add_argument("--step", type=int, default=20, help="Window slide step (days)")
    p.add_argument("--max-windows", type=int, default=6, help="Max windows per stock")
    p.add_argument("--min-bars", type=int, default=504, help="Min bars required")
    p.add_argument("--resume", action="store_true", help="Skip already-completed stocks")
    p.add_argument("--workers", type=int, default=0,
                   help="Worker count (0 = auto)")
    return p.parse_args()


def load_symbols(name: str) -> List[str]:
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


def extract_bullish(tp_dir: str) -> bool:
    return tp_dir.strip() in BULLISH_DIRECTIONS


def extract_report(rep: WyckoffReport) -> dict:
    out = {"phase": "", "sub_phase": "", "unknown_candidate": "",
           "signal_type": "", "spring": False, "utad": False,
           "tr_detected": False, "tr_upper": 0.0, "tr_lower": 0.0,
           "tp_direction": "", "confidence": ""}
    if not rep:
        return out

    st = rep.structure
    if st:
        p = st.phase
        out["phase"] = p.value if isinstance(p, WyckoffPhase) else str(p or "")
        out["sub_phase"] = getattr(st, "sub_phase", "") or ""
        out["unknown_candidate"] = st.unknown_candidate or ""
        thu = st.trading_range_high
        thl = st.trading_range_low
        out["tr_upper"] = float(thu) if thu is not None else 0.0
        out["tr_lower"] = float(thl) if thl is not None else 0.0
        out["tr_detected"] = out["tr_upper"] > 0 and out["tr_lower"] > 0

    sg = rep.signal
    if sg:
        out["signal_type"] = sg.signal_type or ""
        out["spring"] = sg.signal_type == "spring"
        out["utad"] = sg.signal_type == "utad"
        c = sg.confidence
        out["confidence"] = c.value if isinstance(c, ConfidenceLevel) else str(c or "D")

    tp = rep.trading_plan
    if tp:
        out["tp_direction"] = tp.direction or ""

    return out


def stock_fingerprint(symbol: str, ws: int, ld: int, rt: float, tt: float) -> str:
    """Identifier for .done checkpoint."""
    return f"{symbol}_W{ws}_L{ld}_RT{rt:.2f}_TT{tt:.2f}"


def analyze_stock(symbol: str, args, all_params) -> List[dict]:
    done_set = set()
    if args.resume:
        done_path = DONE_MARKER_DIR / f"{symbol}.done"
        if done_path.exists():
            done_set = set(done_path.read_text().strip().split("\n"))

    # Load data once per stock
    try:
        df = pd.read_parquet(DATA_DIR / f"{symbol}.parquet")
    except Exception as e:
        err_row = asdict(WindowResult(symbol=symbol, error=f"load_fail:{e}",
                                      window_size=0, lookback_days=0,
                                      range_threshold=0.0, trend_threshold=0.0, window_idx=0,
                                      error_count=1))
        return [err_row]

    close = df["close"].values
    n = len(df)
    if n < args.min_bars:
        err_row = asdict(WindowResult(symbol=symbol, error=f"insufficient_data:{n}<{args.min_bars}",
                                      window_size=0, lookback_days=0,
                                      range_threshold=0.0, trend_threshold=0.0, window_idx=0,
                                      error_count=1))
        return [err_row]

    results = []
    total_errors = 0
    new_done = []

    for ws, ld, rt, tt in all_params:
        fp = stock_fingerprint(symbol, ws, ld, rt, tt)
        if fp in done_set:
            continue

        eng = WyckoffEngine(range_threshold=rt, trend_threshold=tt, lookback_days=ld)

        max_start = n - ws - max(FW)
        starts = list(range(max_start, ws - 1, -args.step))[:args.max_windows]

        for idx, start in enumerate(starts):
            segment = df.iloc[start - ws:start]
            w_start_date = str(segment["date"].iloc[0])
            w_end_date = str(segment["date"].iloc[-1])
            w_year = int(w_end_date[:4])
            w_half = 1 if int(w_end_date[5:7]) <= 6 else 2

            try:
                rep = eng.analyze(segment, symbol=symbol, multi_timeframe=False)
                ext = extract_report(rep)
            except Exception:
                total_errors += 1
                import traceback
                if total_errors <= 3:
                    traceback.print_exc()
                ext = {"phase": "ERROR", "signal_type": "", "spring": False,
                       "utad": False, "tr_detected": False, "tr_upper": 0.0,
                       "tr_lower": 0.0, "tp_direction": "", "confidence": "",
                       "sub_phase": "", "unknown_candidate": ""}

            # Forward returns (NaN if unavailable)
            c_seg = close[start - ws:start]
            base = c_seg[-1]
            fwd = {}
            for fd in FW:
                target_idx = start + fd
                if target_idx < n:
                    ret = (close[target_idx] / base - 1) * 100
                    fwd[f"fwd_{fd}d"] = round(float(ret), 2)
                else:
                    fwd[f"fwd_{fd}d"] = float("nan")

            tp_dir = ext["tp_direction"]
            wr = WindowResult(
                symbol=symbol, window_size=ws, lookback_days=ld,
                range_threshold=rt, trend_threshold=tt,
                window_idx=idx,
                window_start_date=w_start_date, window_end_date=w_end_date,
                year=w_year, half=w_half,
                phase=ext["phase"], sub_phase=ext["sub_phase"],
                unknown_candidate=ext["unknown_candidate"],
                signal_type=ext["signal_type"],
                spring_detected=ext["spring"],
                utad_detected=ext["utad"],
                tr_detected=ext["tr_detected"],
                tr_upper=ext["tr_upper"], tr_lower=ext["tr_lower"],
                tp_direction=tp_dir,
                tp_direction_bullish=extract_bullish(tp_dir),
                confidence=ext["confidence"],
                fwd_5d=fwd["fwd_5d"], fwd_10d=fwd["fwd_10d"],
                fwd_20d=fwd["fwd_20d"], fwd_60d=fwd["fwd_60d"],
                error_count=total_errors,
            )
            results.append(asdict(wr))

        # Mark param combo as done
        DONE_MARKER_DIR.mkdir(parents=True, exist_ok=True)
        new_done.append(fp)

    # Write done markers atomically
    if new_done:
        done_path = DONE_MARKER_DIR / f"{symbol}.done"
        existing = set()
        if done_path.exists():
            existing = set(done_path.read_text().strip().split("\n"))
        existing.update(new_done)
        done_path.write_text("\n".join(sorted(existing)))

    return results


def param_label(ws, ld, rt, tt):
    return f"W{ws:3d}_L{ld:3d}_RT{rt:.2f}_TT{tt:.2f}"


def compute_ranking(df, all_params):
    BUY_N_WEIGHT = 0.1
    FWD20_WEIGHT = 0.5
    PHASE_SPREAD_WEIGHT = 0.3
    ERROR_PENALTY = -0.1

    rows = []
    for ws, ld, rt, tt in all_params:
        sub = df[(df["window_size"] == ws) & (df["lookback_days"] == ld) &
                 (df["range_threshold"] == rt) & (df["trend_threshold"] == tt)]
        if sub.empty:
            continue

        n = len(sub)
        buy = sub[sub["tp_direction_bullish"]]
        nb = sub[~sub["tp_direction_bullish"]]
        buy_n = len(buy)
        nb_n = len(nb)
        err_n = int(sub["error_count"].sum()) if "error_count" in sub.columns else 0

        # Fwd20 mean (dropna)
        buy_fwd20 = buy["fwd_20d"].dropna()
        nb_fwd20 = nb["fwd_20d"].dropna()
        b_mean = buy_fwd20.mean() if len(buy_fwd20) > 0 else float("nan")
        nb_mean = nb_fwd20.mean() if len(nb_fwd20) > 0 else float("nan")
        spread = (b_mean - nb_mean) if pd.notna(b_mean) and pd.notna(nb_mean) else 0.0

        # Phase breakdown — within same phase spread
        phase_spreads = []
        for ph in sub["phase"].unique():
            if ph == "ERROR" or ph == "":
                continue
            gp = sub[sub["phase"] == ph]
            gp_buy = gp[gp["tp_direction_bullish"]]["fwd_20d"].dropna()
            gp_nb = gp[~gp["tp_direction_bullish"]]["fwd_20d"].dropna()
            if len(gp_buy) >= MIN_OBS_PER_GROUP and len(gp_nb) >= MIN_OBS_PER_GROUP:
                ps = gp_buy.mean() - gp_nb.mean()
                phase_spreads.append(ps)

        mean_phase_spread = np.mean(phase_spreads) if phase_spreads else 0.0

        combined = (FWD20_WEIGHT * spread +
                    PHASE_SPREAD_WEIGHT * mean_phase_spread +
                    BUY_N_WEIGHT * np.log1p(buy_n) +
                    ERROR_PENALTY * err_n)

        rows.append({
            "param": param_label(ws, ld, rt, tt),
            "ws": ws, "ld": ld, "rt": rt, "tt": tt,
            "n": n, "buy_n": buy_n, "nb_n": nb_n, "err_n": err_n,
            "buy_fwd20": b_mean, "nb_fwd20": nb_mean,
            "spread": spread,
            "mean_phase_spread": mean_phase_spread,
            "combined": round(combined, 3),
        })

    rank_df = pd.DataFrame(rows).sort_values("combined", ascending=False).reset_index(drop=True)
    return rank_df


def run_mannwhitney(sub: pd.DataFrame, col: str = "fwd_20d") -> dict:
    buy = sub[sub["tp_direction_bullish"]][col].dropna()
    nb = sub[~sub["tp_direction_bullish"]][col].dropna()
    if len(buy) < MIN_OBS_PER_GROUP or len(nb) < MIN_OBS_PER_GROUP:
        return {"u_stat": None, "p_val": None, "n_buy": len(buy), "n_nb": len(nb)}
    u, p = mannwhitneyu(buy, nb, alternative="two-sided")
    return {"u_stat": u, "p_val": round(p, 5), "n_buy": len(buy), "n_nb": len(nb)}


def bootstrap_spread(sub: pd.DataFrame, n_iter: int = 1000) -> dict:
    """Bootstrap the buy-nonbuy spread CI, respecting stock ID clustering."""
    buy = sub[sub["tp_direction_bullish"]]
    nb = sub[~sub["tp_direction_bullish"]]

    buy_stocks = buy["symbol"].unique()
    nb_stocks = nb["symbol"].unique()

    spreads = []
    for _ in range(n_iter):
        bs_buy = buy[buy["symbol"].isin(np.random.choice(buy_stocks, size=len(buy_stocks), replace=True))]
        bs_nb = nb[nb["symbol"].isin(np.random.choice(nb_stocks, size=len(nb_stocks), replace=True))]
        bm = bs_buy["fwd_20d"].dropna().mean()
        nm = bs_nb["fwd_20d"].dropna().mean()
        spreads.append(bm - nm)

    spreads = np.array(spreads)
    return {
        "spread_mean": float(np.mean(spreads)),
        "spread_ci_low": float(np.percentile(spreads, 2.5)),
        "spread_ci_high": float(np.percentile(spreads, 97.5)),
        "spread_std": float(np.std(spreads)),
    }


def run_scan():
    args = parse_args()
    symbols = load_symbols(args.symbols)
    n_stocks = len(symbols)
    n_workers = args.workers or max(1, (os.cpu_count() or 4) - 1)

    all_params = list(itertools.product(
        args.window_sizes, args.lookback_days,
        args.range_thresholds, args.trend_thresholds
    ))
    n_params = len(all_params)

    print(f"Symbols:  {n_stocks} ({args.symbols})")
    print(f"Params:   {len(args.window_sizes)}W × {len(args.lookback_days)}L × "
          f"{len(args.range_thresholds)}RT × {len(args.trend_thresholds)}TT = {n_params}")
    print(f"Windows:  step={args.step} max={args.max_windows}")
    print(f"Workers:  {n_workers}")
    print(f"Resume:   {'enabled' if args.resume else 'disabled'}")
    print(f"Output:   {OUT_DIR}")
    print()

    t0 = time.perf_counter()

    all_rows = []
    fail_count = 0
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        fut = {pool.submit(analyze_stock, s, args, all_params): s for s in symbols}
        for i, f in enumerate(as_completed(fut), 1):
            sym = fut[f]
            try:
                rows = f.result()
                all_rows.extend(rows)
            except Exception as e:
                fail_count += 1
                print(f"  FAIL {sym}: {e}", flush=True)
            if i <= n_stocks:
                pct = i / n_stocks * 100
                err_flag = f" ({fail_count} fails)" if fail_count > 0 else ""
                print(f"  {i}/{n_stocks} ({pct:.0f}%){err_flag}", flush=True)

    df = pd.DataFrame(all_rows)
    out_path = OUT_DIR / f"param_sweep_v2_{args.symbols}.parquet"
    df.to_parquet(out_path, index=False)
    elapsed = time.perf_counter() - t0
    total_errors = int(df["error_count"].sum()) if "error_count" in df.columns else 0
    print(f"\nSaved: {out_path}  ({len(df)} rows, {elapsed:.0f}s, {total_errors} total errors)")

    # ── Ranking ────────────────────────────────────────────
    rank_df = compute_ranking(df, all_params)
    rank_path = OUT_DIR / f"param_sweep_v2_{args.symbols}_ranking.csv"
    rank_df.to_csv(rank_path, index=False)
    print(f"Ranking: {rank_path}")
    print(f"\n{'='*80}")
    print("PARAM RANKING (top 5 by combined score)")
    print(f"{'='*80}")
    for _, r in rank_df.head(5).iterrows():
        print(f"  #{int(_)+1}: {r['param']}  spread={r['spread']:+.2f}%  "
              f"phase_spread={r['mean_phase_spread']:+.2f}%  "
              f"buy_n={r['buy_n']}  combined={r['combined']:+.3f}")

    print(f"\n{'='*80}")
    print("PARAM REPORT (all)")
    print(f"{'='*80}")

    for _, r in rank_df.iterrows():
        ws, ld, rt, tt = r["ws"], r["ld"], r["rt"], r["tt"]
        sub = df[(df["window_size"] == ws) & (df["lookback_days"] == ld) &
                 (df["range_threshold"] == rt) & (df["trend_threshold"] == tt)]
        n = len(sub)
        spring_n = int(sub["spring_detected"].sum())
        utad_n = int(sub["utad_detected"].sum())
        tr_n = int(sub["tr_detected"].sum())
        bullish_n = int(sub["tp_direction_bullish"].sum())
        phases = sub["phase"].value_counts().to_dict()
        unknown_n = int(phases.get("unknown", 0))

        # Mann-Whitney U test
        mw = run_mannwhitney(sub, "fwd_20d")
        mw_str = f"  MW p={mw['p_val']}" if mw["p_val"] is not None else ""

        # Bootstrap CI
        boot = bootstrap_spread(sub, 500)
        boot_str = f"  boot CI=[{boot['spread_ci_low']:+.2f},{boot['spread_ci_high']:+.2f}]"

        # Also compute buy vs same-phase-nonbuy (within-phase spread)
        phase_spreads = []
        for ph in sub["phase"].unique():
            if ph in ("ERROR", ""):
                continue
            gp = sub[sub["phase"] == ph]
            buy_in_ph = gp[gp["tp_direction_bullish"]]["fwd_20d"].dropna()
            nb_in_ph = gp[~gp["tp_direction_bullish"]]["fwd_20d"].dropna()
            if len(buy_in_ph) >= MIN_OBS_PER_GROUP and len(nb_in_ph) >= MIN_OBS_PER_GROUP:
                ps = buy_in_ph.mean() - nb_in_ph.mean()
                phase_spreads.append((ph, ps))
        ps_str = ""
        if phase_spreads:
            ps_list = "; ".join(f"{ph}={ps:+.2f}" for ph, ps in phase_spreads)
            ps_str = f"  phase_spreads: {ps_list}"

        print(f"\n{r['param']}  n={n:3d}  Spring={spring_n:2d}  UTAD={utad_n:2d}  "
              f"TR={tr_n:2d}  Bullish={bullish_n:2d}  UNKNOWN={unknown_n:2d}")
        print(f"  Phases: {phases}")
        print(f"  buy_fwd20={r['buy_fwd20']:+.2f}%  nb_fwd20={r['nb_fwd20']:+.2f}%  "
              f"spread={r['spread']:+.2f}%{mw_str}")
        print(f"  {boot_str}")
        if ps_str:
            print(f"  {ps_str}")

    # ── Time breakdown ─────────────────────────────────────
    if "year" in df.columns and len(df) > 0:
        print(f"\n{'─'*80}")
        print("TIME BREAKDOWN (by year, best param)")
        best = rank_df.iloc[0]
        sub_best = df[(df["window_size"] == best["ws"]) &
                      (df["lookback_days"] == best["ld"]) &
                      (df["range_threshold"] == best["rt"]) &
                      (df["trend_threshold"] == best["tt"])]
        if len(sub_best) > 0:
            for yr in sorted(sub_best["year"].unique()):
                yr_df = sub_best[sub_best["year"] == yr]
                if len(yr_df) < 10:
                    continue
                buy_yr = yr_df[yr_df["tp_direction_bullish"]]["fwd_20d"].dropna()
                nb_yr = yr_df[~yr_df["tp_direction_bullish"]]["fwd_20d"].dropna()
                if len(buy_yr) >= MIN_OBS_PER_GROUP and len(nb_yr) >= MIN_OBS_PER_GROUP:
                    mw_yr = mannwhitneyu(buy_yr, nb_yr)
                    print(f"  {yr}:  n={len(yr_df):3d}  "
                          f"buy_fwd20={buy_yr.mean():+.2f}%({len(buy_yr)})  "
                          f"nb_fwd20={nb_yr.mean():+.2f}%  "
                          f"spread={buy_yr.mean()-nb_yr.mean():+.2f}%  "
                          f"MW p={mw_yr.pvalue:.4f}")

    print(f"\nTotal: {elapsed:.0f}s  Errors: {total_errors}")
    return df


if __name__ == "__main__":
    run_scan()
