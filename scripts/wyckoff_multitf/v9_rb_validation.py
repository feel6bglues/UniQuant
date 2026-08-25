#!/usr/bin/env python3
"""Red-Blue adversarial validation — empirically test the phase-rebalance plan's core premise.

Measures on real 120-bar monthly frames:
  1. The true P&F hint distribution (current thresholds).
  2. The P&F hint distribution under the plan's PROPOSED new thresholds.
  3. The engine final phase (current: P&F override wins).
  4. The engine final phase with the P&F override DISABLED via monkeypatch
     (i.e., exactly what Phase 0 mod 2 produces: detector-chain-only).
  5. Forward returns by phase in both worlds.

Run:
    python3 scripts/wyckoff_multitf/v9_rb_validation.py --max-stocks 500
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


def proposed_phase_hint(pnf):
    """Replicate the plan's Phase 0 mod 1 tightened thresholds on an already-built PnF."""
    highs, lows = pnf._column_stats()
    n = len(highs)
    if n < 8:
        return "unknown"
    rising = sum(1 for i in range(1, n) if lows[i] > lows[i-1]) / (n - 1)
    falling = sum(1 for i in range(1, n) if highs[i] < highs[i-1]) / (n - 1)
    recent_rl = sum(1 for i in range(n//2, n) if lows[i] > lows[i-1]) / max(1, n - n//2 - 1)
    ranges = [highs[i]-lows[i] for i in range(n)]
    recent = np.mean(ranges[n//2:]) if ranges[n//2:] else 0
    early = np.mean(ranges[:n//2]) if ranges[:n//2] else 1
    contr = recent/early if early else 1
    up = sum(1 for i in range(1, n) if highs[i] > highs[i-1])
    down = 1 - up/max(1, n-1)

    accum = (rising > 0.60 and contr < 0.80 and recent_rl > 0.50 and recent < early*0.85 and down < 0.45)
    dist = (falling > 0.30 and (contr > 1.15 or recent > early*1.05) and down > 0.45 and rising < 0.55)
    if accum:
        return "accumulation"
    if dist:
        return "distribution"
    return "unknown"


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

        # Current P&F hint on the true engine frame
        try:
            pnf = PointAndFigure(box_size=0.02, reversal=2)
            pnf.build(frame)
            hint_curr = pnf.wyckoff_phase_hint()
            hint_new = proposed_phase_hint(pnf)
        except Exception:
            hint_curr = "none"
            hint_new = "none"

        # Engine phase — current behavior (overrides with P&F hint)
        try:
            cur_report = mn_engine.analyze(m, symbol=symbol, period="月线")
            cur_phase = getattr(getattr(cur_report, "structure", None), "phase", None)
            cur_phase = getattr(cur_phase, "value", "unknown")
        except Exception:
            continue

        # Engine phase — P&F override disabled (exactly Phase 0 mod 2)
        try:
            with mock.patch.object(PointAndFigure, "wyckoff_phase_hint",
                                   return_value="neutral"):
                chain_report = mn_engine.analyze(m, symbol=symbol, period="月线")
            chain_phase = getattr(getattr(chain_report, "structure", None), "phase", None)
            chain_phase = getattr(chain_phase, "value", "unknown")
        except Exception:
            chain_phase = "unknown"

        fwd3 = (day_close[min(cutoff_idx+63, len(day_close)-1)] / day_close[cutoff_idx] - 1) * 100
        fwd6 = (day_close[min(cutoff_idx+126, len(day_close)-1)] / day_close[cutoff_idx] - 1) * 100

        rows.append({
            "symbol": symbol, "cutoff": me_str,
            "pnf_hint": hint_curr, "pnf_hint_new": hint_new,
            "engine_phase": cur_phase, "chain_phase": chain_phase,
            "fwd3": fwd3, "fwd6": fwd6,
        })
    return rows


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-stocks", type=int, default=300)
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

    def show(title, key):
        print(f"\n=== {title} ===")
        c = collections.Counter(r[key] for r in all_rows)
        for k, v in c.most_common():
            print(f"  {k:<12} {v:>7} {v/tot*100:5.1f}%")
        return c

    show("P&F hint (current thresholds)", "pnf_hint")
    show("P&F hint (PROPOSED new thresholds)", "pnf_hint_new")
    cur_phase = show("Engine final phase (current, override wins)", "engine_phase")
    chain_phase = show("Engine phase (override DISABLED = chain-only, Phase 0 mod2)", "chain_phase")

    print("\n=== Phase shift: engine(current) -> chain-only ===")
    cross = collections.Counter(f"{r['engine_phase']}->{r['chain_phase']}" for r in all_rows)
    for k, v in cross.most_common(15):
        print(f"  {k:<32} {v:>7} {v/tot*100:5.1f}%")

    print("\n=== Forward 3m by engine phase (current world) ===")
    by_p = collections.defaultdict(list)
    for r in all_rows:
        by_p[r["engine_phase"]].append(r["fwd3"])
    for p in PHASES:
        v = np.array(by_p[p])
        if len(v):
            print(f"  {p:<12} n={len(v):>6} mean={np.mean(v):+7.2f} med={np.median(v):+7.2f} pos={(v>0).mean()*100:5.1f}%")

    print("\n=== Forward 3m by CHAIN phase (world after Phase 0 mod2) ===")
    by_c = collections.defaultdict(list)
    for r in all_rows:
        by_c[r["chain_phase"]].append(r["fwd3"])
    for p in PHASES:
        v = np.array(by_c[p])
        if len(v):
            print(f"  {p:<12} n={len(v):>6} mean={np.mean(v):+7.2f} med={np.median(v):+7.2f} pos={(v>0).mean()*100:5.1f}%")

    # Hint raises -> how often it overrides / agrees
    print("\n=== P&F:hint vs engine-phase agreement ===")
    forced = sum(1 for r in all_rows if r["pnf_hint"] in ("accumulation", "distribution"))
    agree = sum(1 for r in all_rows if r["pnf_hint"] == r["engine_phase"])
    print(f"  P&F hinted (->override possible): {forced}/{tot} = {forced/tot*100:.1f}%")
    print(f"  Engine phase == P&F hint: {agree}/{tot} = {agree/tot*100:.1f}%")

    out = Path("scripts/wyckoff_multitf/output_rb_validation")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "rb_validation_rows.json", "w") as f:
        json.dump(all_rows, f, indent=1)
    summary = {
        "n_obs": len(all_rows),
        "pnf_hint": dict(collections.Counter(r["pnf_hint"] for r in all_rows)),
        "pnf_hint_new": dict(collections.Counter(r["pnf_hint_new"] for r in all_rows)),
        "engine_phase": dict(cur_phase),
        "chain_phase": dict(chain_phase),
        "agreement_pct": round(agree/tot*100, 2),
        "forced_pct": round(forced/tot*100, 2),
    }
    with open(out / "rb_validation_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()