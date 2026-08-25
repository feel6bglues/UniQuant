#!/usr/bin/env python3
"""v2.0 Plan Medium-Scale Validation — captures context data for Phase 0/1/2 simulation.

For each stock × cutoff:
  1. Build PnF on 120-bar monthly frame → compute current + calibrated hints
  2. Run engine analyze() → current engine phase + forward returns
  3. Compute chain phase via _step1_phase_determine(pnf_hint=None)
  4. Capture step1 context (short_trend, relative_position, prior_trend, ma5, ma20)
  5. Simulate Phase 1 proposed changes using context data
  6. Report phase distribution, returns, and Phase 1 counterfactual

Run:  python3 scripts/wyckoff_multitf/v9_v2_medium_validation.py --max-stocks 1000
"""
import sys, time, json, collections
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
MONTH_LOOKBACK = 120
PHASES = ["accumulation", "markup", "distribution", "markdown", "unknown"]
RNG = np.random.RandomState(42)


# ── P&F calibrated threshold candidates ──
# Each accum candidate: (rising, contraction, recent_rl, avg_ratio, down_ratio)
# - down_ratio=None means no down_ratio constraint (current behavior)
ACCUM_CANDIDATES = {
    "A0": (0.50, 0.85, 0.40, 0.90, None),  # current code: NO down_ratio constraint
    "A1": (0.55, 0.83, 0.45, 0.88, 0.48),  # v2.0 proposal
    "A2": (0.55, 0.85, 0.45, 0.88, 0.50),
    "A3": (0.55, 0.83, 0.40, 0.85, 0.48),
    "A4": (0.50, 0.83, 0.45, 0.88, 0.48),
    "A5": (0.55, 0.83, 0.45, 0.85, 0.45),
}
# Each dist candidate: (falling, contraction, down_ratio, avg_ratio, rising_lows)
# - rising_lows=None means no rising_lows constraint (current behavior)
DIST_CANDIDATES = {
    "D0": (0.30, 1.20, 0.50, 1.10, None),  # current code: NO rising_lows constraint
    "D1": (0.30, 1.18, 0.47, 1.08, 0.55),  # v2.0 proposal
    "D2": (0.30, 1.15, 0.47, 1.08, 0.55),
    "D3": (0.30, 1.18, 0.45, 1.08, 0.50),
    "D4": (0.35, 1.18, 0.47, 1.08, 0.55),
}


def synthesize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["mk"] = df["date"].dt.to_period("M").astype(str)
    agg = df.groupby("mk", sort=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), amount=("amount", "sum"),
        date=("date", "min"),
    ).reset_index()
    return agg.sort_values("date").reset_index(drop=True)


def gen_cutoffs(start="2019-01-31", end="2024-06-28"):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end, freq="ME")]


def calibrated_hint(pnf, accum_key="A1", dist_key="D1"):
    """Compute P&F hint with calibrated thresholds."""
    highs, lows = pnf._column_stats()
    n = len(highs)
    if n < 8:
        return "unknown"
    rising = sum(1 for i in range(1, n) if lows[i] > lows[i-1]) / (n-1)
    falling = sum(1 for i in range(1, n) if highs[i] < highs[i-1]) / (n-1)
    recent_rl = sum(1 for i in range(n//2, n) if lows[i] > lows[i-1]) / max(1, n - n//2 - 1)
    ranges = [highs[i]-lows[i] for i in range(n)]
    recent = np.mean(ranges[n//2:]) if ranges[n//2:] else 0
    early = np.mean(ranges[:n//2]) if ranges[:n//2] else 1
    contr = recent/early if early else 1
    up = sum(1 for i in range(1, n) if highs[i] > highs[i-1])
    down = 1 - up/max(1, n-1)

    r1, c1, rl1, ar1, dr1 = ACCUM_CANDIDATES[accum_key]
    accum = (rising > r1 and contr < c1 and recent_rl > rl1 and recent < early*ar1)
    if dr1 is not None:
        accum = accum and (down < dr1)
    r2, c2, dr2, ar2, rl2 = DIST_CANDIDATES[dist_key]
    dist = (falling > r2 and (contr > c2 or recent > early*ar2) and down > dr2)
    if rl2 is not None:
        dist = dist and (rising < rl2)
    if accum: return "accumulation"
    if dist: return "distribution"
    return "unknown"


def all_calibrated_hints(pnf):
    """Compute all calibrated hint combinations."""
    results = {}
    for ak in ACCUM_CANDIDATES:
        for dk in DIST_CANDIDATES:
            h = calibrated_hint(pnf, ak, dk)
            results[f"{ak}+{dk}"] = h
    return results


def simulate_phase1_accum(ctx, rule0):
    """Simulate the proposed Phase 1 accumulation loosening."""
    if ctx["is_in_trading_range"]:
        if ctx["prior_trend_pct"] < -0.02:
            return True
        if ctx["relative_position"] <= 0.45 and rule0.bc_found:
            return True
    else:
        bc_sc_ok = rule0.bc_found or rule0.sc_found
        if (ctx["short_trend_pct"] <= -0.01
            and ctx["current_price"] < ctx["ma20"]
            and bc_sc_ok):
            return True
    return False


def simulate_phase1_markdown(df, ctx, rule0):
    """Simulate the proposed Phase 1 markdown tightening."""
    cp = ctx["current_price"]
    ma5 = ctx["ma5"]
    ma20 = ctx["ma20"]
    st = ctx["short_trend_pct"]
    rp = ctx["relative_position"]

    if ctx["is_in_trading_range"]:
        if (rule0.bc_found and rule0.bc_position is not None
            and cp <= rule0.bc_position.price * 0.85
            and cp < ma20 * 0.95
            and ma5 <= ma20 and st <= -0.02):
            if len(df) >= 5:
                vol_5 = float(df.tail(5)["volume"].mean())
                vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
                if vol_20 > 0 and vol_5 > vol_20 * 1.1:
                    return True
    else:
        if st <= -0.05 and cp < ma20 * 0.95:
            if len(df) >= 5:
                vol_5 = float(df.tail(5)["volume"].mean())
                vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
                if vol_20 > 0 and vol_5 > vol_20 * 1.1 and rp >= 0.20:
                    return True
        if (rule0.bc_found and rule0.bc_position is not None
            and cp <= rule0.bc_position.price * 0.85
            and cp < ma20 and ma5 <= ma20 and st <= -0.02):
            return True
    return False


def simulate_phase1_markup(ctx):
    """Simulate the proposed Phase 1 markup loosening."""
    cp = ctx["current_price"]
    ma5 = ctx["ma5"]
    ma20 = ctx["ma20"]
    rp = ctx["relative_position"]
    st = ctx["short_trend_pct"]

    if ctx["is_in_trading_range"]:
        if (rp >= 0.50 or st >= 0.02) and (
            (cp > ma20 * 0.97 and ma5 >= ma20 * 0.95) or (cp > ma5 and rp >= 0.45)
        ):
            return True
    else:
        if st >= 0.005 and cp > ma20 and ma5 >= ma20 * 0.98 and rp >= 0.35:
            return True
        if st >= 0.015 and (
            (cp > ma20 and ma5 >= ma20) or (cp > ma5 and rp >= 0.35)
        ):
            return True
    return False


def process_symbol(symbol):
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from uniquant.brain.wyckoff.pnf import PointAndFigure

    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return []
    try:
        daily = pd.read_parquet(fp)
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date").reset_index(drop=True)
        if len(daily) < 200:
            return []
        monthly = synthesize_monthly(daily)
    except Exception:
        return []

    day_close = daily["close"].values
    day_dates = daily["date"].values
    mn_engine = WyckoffEngine(lookback_days=6)
    rows = []
    for me_str in gen_cutoffs():
        me = pd.Timestamp(me_str)
        m = monthly[monthly["date"] <= me]
        d = daily[daily["date"] <= me]
        if len(m) < 12 or len(d) < 120:
            continue
        cutoff_idx = None
        for i in range(len(day_dates)):
            if day_dates[i] <= me:
                cutoff_idx = i
        if cutoff_idx is None or cutoff_idx >= len(day_close) - 21:
            continue

        frame = m.tail(min(len(m), MONTH_LOOKBACK)).reset_index(drop=True)

        # PnF hints
        try:
            pnf = PointAndFigure(box_size=0.02, reversal=2)
            pnf.build(frame)
            hint_curr = pnf.wyckoff_phase_hint()
            cal_hints = all_calibrated_hints(pnf)
        except Exception:
            hint_curr = "unknown"
            cal_hints = {}

        # Engine phase (current — P&F override wins)
        try:
            cur_report = mn_engine.analyze(m, symbol=symbol, period="月线")
            cur_phase = getattr(getattr(cur_report, "structure", None), "phase", None)
            cur_phase = getattr(cur_phase, "value", "unknown")
        except Exception:
            continue

        # Chain phase + context data (via manual steps)
        try:
            rule0 = mn_engine._step0_bc_tr_scan(frame, pnf_zone=pnf.congestion_zone())
            ctx = mn_engine._compute_step1_context(frame, rule0)
            chain_step1 = mn_engine._step1_phase_determine(frame, rule0, pnf_hint=None)
            chain_phase = getattr(chain_step1.phase, "value", "unknown")
        except Exception:
            continue

        # Phase 1 simulation
        p1_accum = simulate_phase1_accum(ctx, rule0)
        p1_markdown = simulate_phase1_markdown(frame, ctx, rule0)
        p1_markup = simulate_phase1_markup(ctx)

        # Forward returns
        fwd3 = (day_close[min(cutoff_idx+63, len(day_close)-1)] / day_close[cutoff_idx] - 1) * 100
        fwd6 = (day_close[min(cutoff_idx+126, len(day_close)-1)] / day_close[cutoff_idx] - 1) * 100

        row = {
            "symbol": symbol, "cutoff": me_str,
            "pnf_hint": hint_curr,
            "engine_phase": cur_phase, "chain_phase": chain_phase,
            "short_trend": round(ctx["short_trend_pct"], 4),
            "relative_position": round(ctx["relative_position"], 4),
            "prior_trend": round(ctx["prior_trend_pct"], 4),
            "is_in_tr": ctx["is_in_trading_range"],
            "ma5": round(ctx["ma5"], 2),
            "ma20": round(ctx["ma20"], 2),
            "p1_accum": p1_accum, "p1_markdown": p1_markdown, "p1_markup": p1_markup,
            "fwd3": round(fwd3, 4), "fwd6": round(fwd6, 4),
        }
        row.update(cal_hints)
        rows.append(row)
    return rows


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-stocks", type=int, default=1000)
    args = ap.parse_args()

    from scripts.wyckoff_multitf.a_universe import scan_universe, stratified_sample
    from scripts.wyckoff_multitf.config import VerifierConfig
    cfg = VerifierConfig(max_stocks=args.max_stocks)
    records = scan_universe(cfg)
    sampled = stratified_sample(records, seed=42, n_per=args.max_stocks // 5 + 1)
    stocks = [r.symbol for r in sampled[:args.max_stocks]]
    print(f"Universe: {len(stocks)} stocks")

    t0 = time.time()
    all_rows = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(process_symbol, s): s for s in stocks}
        done = 0
        for fut in as_completed(futs):
            done += 1
            all_rows.extend(fut.result())
            if done % 50 == 0:
                print(f"  {done}/{len(stocks)} stocks, {len(all_rows)} obs, {time.time()-t0:.0f}s")
    print(f"Complete: {len(all_rows)} obs in {time.time()-t0:.0f}s")
    tot = max(len(all_rows), 1)

    # === ANALYSIS ===
    def show(title, key):
        nonlocal tot
        if isinstance(key, list):
            vals = [r.get(k, "?") for k in key for r in all_rows]
            c = collections.Counter(vals)
        else:
            c = collections.Counter(r.get(key, "?") for r in all_rows)
        print(f"\n=== {title} ===")
        for k, v in c.most_common():
            print(f"  {k:<14} {v:>7} {v/tot*100:5.1f}%")
        return c

    show("P&F hint (current)", "pnf_hint")
    show("Engine phase (current)", "engine_phase")
    show("Chain phase (override removed)", "chain_phase")

    # Calibrated hints
    print("\n=== Calibrated P&F hint distributions ===")
    for ck in sorted(ACCUM_CANDIDATES):
        for dk in sorted(DIST_CANDIDATES):
            key = f"{ck}+{dk}"
            vals = [r.get(key, "unknown") for r in all_rows]
            c = collections.Counter(vals)
            accum_pct = c.get("accumulation", 0) / tot * 100
            dist_pct = c.get("distribution", 0) / tot * 100
            unk_pct = c.get("unknown", 0) / tot * 100
            print(f"  {key:<8} accum={accum_pct:5.1f}% dist={dist_pct:5.1f}% unk={unk_pct:5.1f}%"
                  f"  {'✅' if 25 <= accum_pct <= 45 and 15 <= dist_pct <= 35 else ' '}")

    # Phase 1 simulation
    print("\n=== Phase 1 simulation (using context data) ===")
    sim_accum = sum(1 for r in all_rows if r["p1_accum"])
    sim_markdown = sum(1 for r in all_rows if r["p1_markdown"])
    sim_markup = sum(1 for r in all_rows if r["p1_markup"])
    print(f"  Phase 1 accum trigger:    {sim_accum:>7} {sim_accum/tot*100:5.1f}%")
    print(f"  Phase 1 markdown trigger: {sim_markdown:>7} {sim_markdown/tot*100:5.1f}%")
    print(f"  Phase 1 markup trigger:   {sim_markup:>7} {sim_markup/tot*100:5.1f}%")

    # Context data stats
    print("\n=== Context data statistics ===")
    st = np.array([r["short_trend"] for r in all_rows])
    rp = np.array([r["relative_position"] for r in all_rows])
    pt = np.array([r["prior_trend"] for r in all_rows])
    tr = np.array([r["is_in_tr"] for r in all_rows])
    print(f"  short_trend:      mean={np.mean(st):+7.4f} median={np.median(st):+7.4f} p10={np.percentile(st,10):+7.4f} p90={np.percentile(st,90):+7.4f}")
    print(f"  relative_position: mean={np.mean(rp):+7.4f} median={np.median(rp):+7.4f}")
    print(f"  prior_trend:      mean={np.mean(pt):+7.4f} median={np.median(pt):+7.4f}")
    print(f"  is_in_tr:         {np.mean(tr)*100:.1f}%")

    # Forward returns by chain phase
    print("\n=== Forward 3m by chain phase ===")
    by_p = collections.defaultdict(list)
    for r in all_rows:
        by_p[r["chain_phase"]].append(r["fwd3"])
    for p in PHASES:
        v = np.array(by_p.get(p, []))
        if len(v):
            print(f"  {p:<12} n={len(v):>6} mean={np.mean(v):+7.2f} med={np.median(v):+7.2f} pos={(v>0).mean()*100:5.1f}%")

    # Save
    out = Path("scripts/wyckoff_multitf/output_v2_validation")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "v2_medium_rows.json", "w") as f:
        json.dump(all_rows, f, indent=1)
    print(f"\nSaved {len(all_rows)} obs to {out}")


if __name__ == "__main__":
    main()