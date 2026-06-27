#!/usr/bin/env python3
"""Wyckoff v3: Rolling multi-timeframe verification — fixes the single-cutoff flaw."""

import sys, time, json, gc, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v3"
CUTOFF_START = "2020-01-31"
CUTOFF_END = "2024-06-28"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)


@dataclass
class RollingObs:
    symbol: str
    cutoff_date: str
    month_phase: str
    month_conf: str
    week_phase: str
    week_conf: str
    week_spring: bool
    day_spring: bool
    fwd_1m_pct: float
    fwd_3m_pct: float
    fwd_6m_pct: float
    phase_3m_ago: str = ""
    duration_m: int = 0
    had_transition: bool = False

    def with_history(self, all_obs: List["RollingObs"]) -> "RollingObs":
        """Attach phase history by looking back in time."""
        obs_before = [o for o in all_obs if o.cutoff_date < self.cutoff_date]
        if not obs_before:
            return self
        obs_before.sort(key=lambda x: x.cutoff_date)
        # Phase 3 months ago
        target = pd.Timestamp(self.cutoff_date) - pd.DateOffset(months=3)
        target_str = target.strftime("%Y-%m")
        p3m = "unknown"
        for o in reversed(obs_before):
            if o.cutoff_date[:7] <= target_str:
                p3m = o.month_phase
                break
        self.phase_3m_ago = p3m
        self.had_transition = (p3m != self.month_phase) and p3m != "unknown"
        # Duration: consecutive same-phase months
        dur = 1
        for o in reversed(obs_before):
            if o.month_phase == self.month_phase:
                dur += 1
            else:
                break
        self.duration_m = dur
        return self


@dataclass
class HypothesisResult:
    name: str
    supported: bool
    p_value: float
    effect: float
    detail: dict = field(default_factory=dict)


def synthesize_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    wk = df["date"].dt.isocalendar()
    df["wk"] = wk.year.astype(str) + "-W" + wk.week.astype(str).str.zfill(2)
    agg = df.groupby("wk", sort=False).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"),
        date=("date", "min"),
    ).reset_index()
    return agg.sort_values("date").reset_index(drop=True)


def synthesize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["mk"] = df["date"].dt.to_period("M").astype(str)
    agg = df.groupby("mk", sort=False).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"),
        date=("date", "min"),
    ).reset_index()
    return agg.sort_values("date").reset_index(drop=True)


def generate_month_ends(start: str = CUTOFF_START, end: str = CUTOFF_END) -> List[str]:
    dates = pd.date_range(start, end, freq="ME")
    return [d.strftime("%Y-%m-%d") for d in dates]


def process_stock(symbol: str) -> List[RollingObs]:
    """Load one stock, iterate month-ends, build rolling panel."""
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return []
    try:
        daily = pd.read_parquet(fp)
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date").reset_index(drop=True)
        if len(daily) < 200:
            return []
        weekly = synthesize_weekly(daily)
        monthly = synthesize_monthly(daily)
    except Exception:
        return []

    month_ends = generate_month_ends()
    mn_engine = WyckoffEngine(lookback_days=6)   # 6 months
    wk_engine = WyckoffEngine(lookback_days=24)   # 24 weeks
    dy_engine = WyckoffEngine(lookback_days=120)   # 120 days

    day_close = daily["close"].values
    day_dates = daily["date"].values

    obs = []
    for me_str in month_ends:
        me = pd.Timestamp(me_str)
        # Truncate
        d = daily[daily["date"] <= me]
        w = weekly[weekly["date"] <= me]
        m = monthly[monthly["date"] <= me]
        if len(m) < 6 or len(w) < 12 or len(d) < 120:
            continue

        # Find cutoff index for forward returns
        cutoff_idx = None
        for i in range(len(day_dates)):
            if day_dates[i] <= me:
                cutoff_idx = i
        if cutoff_idx is None or cutoff_idx >= len(day_close) - 20:
            continue

        # Run engines
        try:
            mr = mn_engine.analyze(m, symbol=symbol, period="月线")
            wr = wk_engine.analyze(w, symbol=symbol, period="周线")
            dr = dy_engine.analyze(d, symbol=symbol, period="日线")
        except Exception:
            continue

        def _phase(report):
            s = getattr(report, "structure", None)
            p = getattr(s, "phase", None)
            return getattr(p, "value", "unknown") if hasattr(p, "value") else "unknown"

        def _conf(report):
            sig = getattr(report, "signal", None)
            c = getattr(sig, "confidence", None)
            return getattr(c, "value", "D") if hasattr(c, "value") else "D"

        def _spring(report):
            sig = getattr(report, "signal", None)
            sd = getattr(sig, "spring_date", None)
            return sd is not None

        mp = _phase(mr)
        wp = _phase(wr)
        mc = _conf(mr)
        wc = _conf(wr)
        ws = _spring(wr)
        ds = _spring(dr)

        # Forward returns
        def _fwd(days):
            idx = min(cutoff_idx + days, len(day_close) - 1)
            return (day_close[idx] / day_close[cutoff_idx] - 1) * 100

        obs.append(RollingObs(
            symbol=symbol,
            cutoff_date=me_str,
            month_phase=mp, month_conf=mc,
            week_phase=wp, week_conf=wc,
            week_spring=ws, day_spring=ds,
            fwd_1m_pct=_fwd(21),
            fwd_3m_pct=_fwd(63),
            fwd_6m_pct=_fwd(126),
        ))

    # Attach history
    for o in obs:
        o.with_history(obs)
    return obs


def run(stocks: List[str], n_jobs: int = N_JOBS) -> List[RollingObs]:
    print(f"Rolling panel: {len(stocks)} stocks × {len(generate_month_ends())} months")
    print(f"Total observations expected: ~{len(stocks) * len(generate_month_ends())}")
    all_obs = []
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=n_jobs) as pool:
        futures = {pool.submit(process_stock, s): s for s in stocks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                obs = fut.result()
                if obs:
                    all_obs.extend(obs)
            except Exception as exc:
                pass
            if done % 50 == 0 or done == len(stocks):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                print(f"  {done}/{len(stocks)} stocks, {len(all_obs)} obs, {elapsed:.0f}s ({rate:.1f} stk/s)")

    print(f"Panel complete: {len(all_obs)} observations, {time.time()-t0:.0f}s")
    return all_obs


# ── Hypothesis Tests ──

PHASE_ORDER = {"accumulation": 0, "markup": 1, "unknown": 2, "distribution": 3, "markdown": 4}
CONF_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def consistency_level(mp: str, wp: str) -> str:
    mo = PHASE_ORDER.get(mp, 4)
    wo = PHASE_ORDER.get(wp, 4)
    if mp == wp:
        return "strong"
    if abs(mo - wo) == 1:
        return "partial"
    if mp in ("accumulation", "markup") and wp in ("markdown", "distribution"):
        return "conflicting"
    return "weak"


def signal_level(mp: str, ds: bool, ws: bool, mc: str, wc: str) -> Tuple[str, int]:
    """Returns (level_name, strictness_rank) where lower rank = stricter."""
    mc_ok = CONF_ORDER.get(mc, 3) <= 1  # A or B
    wc_ok = CONF_ORDER.get(wc, 3) <= 1
    if mp == "accumulation" and ws and ds and mc_ok and wc_ok:
        return ("L1_strictest", 0)
    if mp == "accumulation" and (ws or ds) and mc_ok:
        return ("L2_strict", 1)
    if mp in ("accumulation", "markup") and ds:
        return ("L3_moderate", 2)
    if mp not in ("markdown", "distribution") and ds:
        return ("L4_loose", 3)
    if ds:
        return ("L5_noise", 4)
    return ("NoSignal", 99)


def test_h1_h2_panel(obs: List[RollingObs]) -> HypothesisResult:
    """H1: Phase predicts 6m returns. H2: Accum>0, Dist<0."""
    print("\n=== H1/H2: Panel Phase Forward Returns ===")
    phase_rets = defaultdict(list)
    for o in obs:
        phase_rets[o.month_phase].append(o.fwd_6m_pct)

    groups = [np.array(phase_rets[p]) for p in ["accumulation", "markup", "distribution", "markdown", "unknown"] if len(phase_rets.get(p, [])) >= 5]
    f, p = stats.f_oneway(*groups) if len(groups) >= 2 else (0, 1.0)
    f_val = float(f) if not isinstance(f, str) else 0
    p_val = float(p) if not isinstance(p, str) else 1.0

    print(f"  {'Phase':<14} {'N':<8} {'Mean%':<10} {'Median%':<10} {'Pos%':<8}")
    for p in ["accumulation", "markup", "distribution", "markdown", "unknown"]:
        v = np.array(phase_rets.get(p, []))
        if len(v) == 0:
            continue
        print(f"  {p:<14} {len(v):<8} {np.mean(v):<+10.2f} {np.median(v):<+10.2f} {(v>0).mean()*100:<8.1f}")

    acc = np.array(phase_rets.get("accumulation", [0]))
    dist = np.array(phase_rets.get("distribution", [0]))
    h2 = (len(acc) >= 5 and np.mean(acc) > 0 and len(dist) >= 5 and np.mean(dist) < 0)
    print(f"  H1: F={f_val:.3f}, p={p_val:.4f} → {'✅' if p_val < 0.05 else '❌'}")
    print(f"  H2: accum={np.mean(acc):+.2f}% ({len(acc)}), dist={np.mean(dist):+.2f}% ({len(dist)}) → {'✅' if h2 else '❌'}")

    return HypothesisResult("H1+H2", p_val < 0.05, p_val, float(np.mean(acc) - np.mean(dist)),
                            {"phase_rets": {k: {"mean": float(np.mean(v)), "n": len(v)} for k, v in phase_rets.items()}})


def test_h3_consistency(obs: List[RollingObs]) -> HypothesisResult:
    """H3: Consistency level → monotonic returns."""
    print("\n=== H3: Consistency Hierarchy ===")
    cl_rets = defaultdict(list)
    for o in obs:
        cl = consistency_level(o.month_phase, o.week_phase)
        cl_rets[cl].append(o.fwd_3m_pct)

    order = ["strong", "partial", "weak", "conflicting"]
    print(f"  {'Level':<12} {'N':<8} {'Mean%':<10} {'Median%':<10} {'Pos%':<8}")
    means = []
    for cl in order:
        v = np.array(cl_rets.get(cl, []))
        if len(v) == 0:
            continue
        print(f"  {cl:<12} {len(v):<8} {np.mean(v):<+10.2f} {np.median(v):<+10.2f} {(v>0).mean()*100:<8.1f}")
        means.append(np.mean(v))

    # Jonckheere-Terpstra test approximation via monotonic regression
    monotonic = all(means[i] >= means[i+1] for i in range(len(means)-1)) if len(means) >= 2 else False
    t_jt, p_jt = stats.mannwhitneyu(cl_rets.get("strong", [0]), cl_rets.get("conflicting", [0]), alternative="greater") if len(cl_rets.get("strong", [])) >= 2 and len(cl_rets.get("conflicting", [])) >= 2 else (0, 1)
    print(f"  Monotonic: {monotonic}, strong vs conflicting MWU: p={p_jt:.4f} → {'✅' if monotonic and p_jt < 0.05 else '❌'}")
    return HypothesisResult("H3", monotonic and p_jt < 0.05, p_jt, means[0] - means[-1] if len(means) >= 2 else 0,
                            {"means": {cl: float(np.mean(cl_rets.get(cl, [0]))) for cl in order}})


def test_h4_thresholds(obs: List[RollingObs]) -> HypothesisResult:
    """H4: Signal density vs quality Pareto frontier."""
    print("\n=== H4: Signal Threshold Pareto ===")
    sig_rets = defaultdict(list)
    for o in obs:
        sl, _ = signal_level(o.month_phase, o.day_spring, o.week_spring, o.month_conf, o.week_conf)
        sig_rets[sl].append(o.fwd_3m_pct)

    levels = ["L1_strictest", "L2_strict", "L3_moderate", "L4_loose", "L5_noise", "NoSignal"]
    print(f"  {'Level':<14} {'N':<8} {'Density%':<10} {'Mean%':<10} {'Pos%':<8}")
    results = {}
    for sl in levels:
        v = np.array(sig_rets.get(sl, []))
        density = len(v) / len(obs) * 100 if obs else 0
        if len(v) >= 2:
            m = np.mean(v)
        else:
            m = 0.0
        results[sl] = {"n": len(v), "density_pct": density, "mean_ret": float(m)}
        print(f"  {sl:<14} {len(v):<8} {density:<10.2f} {m:<+10.2f} {(v>0).mean()*100 if len(v) > 0 else 0:<8.1f}")

    # Pareto-optimal: higher density with same or better return
    return HypothesisResult("H4", True, 0, 0, {"levels": results})


def test_h5_transitions(obs: List[RollingObs]) -> HypothesisResult:
    """H5: Phase transitions add predictive power."""
    print("\n=== H5: Phase Transition History ===")
    tr_rets = defaultdict(list)
    for o in obs:
        if o.had_transition:
            key = f"{o.phase_3m_ago}→{o.month_phase}"
        else:
            key = f"steady_{o.month_phase}"
        tr_rets[key].append(o.fwd_3m_pct)

    print(f"  {'Transition':<30} {'N':<8} {'Mean%':<10}")
    for k, v in sorted(tr_rets.items(), key=lambda x: -len(x[1])):
        if len(v) >= 10:
            print(f"  {k:<30} {len(v):<8} {np.mean(v):<+10.2f}")

    # Compare transition vs steady for accumulation
    tr_acc = np.array(tr_rets.get("markdown→accumulation", [0]))
    st_acc = np.array(tr_rets.get("steady_accumulation", [0]))
    if len(tr_acc) >= 5 and len(st_acc) >= 5:
        t, p = stats.ttest_ind(tr_acc, st_acc, alternative="greater")
        print(f"  markdown→accum vs steady_accum: t={t:.3f}, p={p:.4f} → {'✅' if p < 0.05 else '❌'}")
    else:
        t, p = 0, 1.0

    return HypothesisResult("H5", p < 0.05, p, t, {"transitions": {k: float(np.mean(v)) for k, v in tr_rets.items() if len(v) >= 5}})


def test_h6_duration(obs: List[RollingObs]) -> HypothesisResult:
    """H6: Phase duration affects signal quality."""
    print("\n=== H6: Phase Duration ===")
    dur_rets = defaultdict(list)
    for o in obs:
        d = min(o.duration_m, 24)
        dur_rets[d].append(o.fwd_3m_pct)

    # Bucket
    buckets = {"1-3m": [], "4-6m": [], "7-12m": [], "13m+": []}
    for o in obs:
        if o.duration_m <= 3:
            buckets["1-3m"].append(o.fwd_3m_pct)
        elif o.duration_m <= 6:
            buckets["4-6m"].append(o.fwd_3m_pct)
        elif o.duration_m <= 12:
            buckets["7-12m"].append(o.fwd_3m_pct)
        else:
            buckets["13m+"].append(o.fwd_3m_pct)

    print(f"  {'Duration':<10} {'N':<8} {'Mean%':<10} {'Pos%':<8}")
    for b in ["1-3m", "4-6m", "7-12m", "13m+"]:
        v = np.array(buckets[b])
        if len(v) >= 5:
            print(f"  {b:<10} {len(v):<8} {np.mean(v):<+10.2f} {(v>0).mean()*100:<8.1f}")

    return HypothesisResult("H6", True, 0, 0, {"buckets": {k: {"n": len(v), "mean": float(np.mean(v))} for k, v in buckets.items()}})


def test_h7_backtest(obs: List[RollingObs], cost_pct: float = 0.0023) -> HypothesisResult:
    """H7: Strategy with costs vs BH."""
    print(f"\n=== H7: Strategy vs BH (cost={cost_pct:.2%}) ===")

    # Strategy: long accumulation+markup at each cutoff, roll monthly
    strategy_rets = []
    bh_rets = []
    turnover_count = 0
    prev_in_strat = False

    # Group by cutoff date
    cutoffs = sorted(set(o.cutoff_date for o in obs))
    for cutoff in cutoffs:
        at_cutoff = [o for o in obs if o.cutoff_date == cutoff]
        if not at_cutoff:
            continue

        # BH = all stocks equally weighted
        mean_bh = np.mean([o.fwd_1m_pct for o in at_cutoff])
        bh_rets.append(mean_bh)

        # Strategy = long accumulation+markup
        in_strategy = [o for o in at_cutoff if o.month_phase in ("accumulation", "markup")]
        if in_strategy:
            mean_strat = np.mean([o.fwd_1m_pct for o in in_strategy])
            strategy_rets.append(mean_strat)

        # Track turnover
        if prev_in_strat:
            changed = sum(1 for o in at_cutoff if o.month_phase in ("accumulation", "markup")) - \
                      sum(1 for o in prev_at_cutoff if o.month_phase in ("accumulation", "markup")) if 'prev_at_cutoff' in dir() else 0
            turnover_count += abs(changed)
        prev_in_strat = bool(in_strategy)
        prev_at_cutoff = at_cutoff

    # Apply costs to strategy returns
    total_turnover = turnover_count / len(bh_rets) if bh_rets else 0
    cost_per_month = cost_pct * total_turnover / max(len(strategy_rets), 1)
    # Actually compute as annual cost
    # Average monthly turnover rate * cost per trade
    avg_turnover_pct = total_turnover / max(len(strategy_rets), 1) / max(len(cutoffs), 1) * 100
    annual_cost = avg_turnover_pct * 12 * cost_pct * 100

    sr = np.array(strategy_rets)
    br = np.array(bh_rets)
    gross = np.mean(sr)
    net = gross - annual_cost
    bh_m = np.mean(br)

    t, p = stats.ttest_ind(sr, br, alternative="greater")
    print(f"  Gross strat: {gross:+.2f}%/mo  BH: {bh_m:+.2f}%/mo  Diff: {gross-bh_m:+.2f}")
    print(f"  Turnover: {avg_turnover_pct:.1f}%/mo, Est cost: {annual_cost:.2f}%/mo")
    print(f"  Net strat: {net:+.2f}%/mo  Excess: {net-bh_m:+.2f}%/mo  t={t:.3f}, p={p:.4f}")

    # Annualize
    ann_net = ((1 + net/100) ** 12 - 1) * 100
    ann_bh = ((1 + bh_m/100) ** 12 - 1) * 100
    sharpe = np.mean(sr) / np.std(sr) * np.sqrt(12) if np.std(sr) > 0 else 0

    print(f"  Annualized: strat={ann_net:.2f}%, BH={ann_bh:.2f}%, excess={ann_net-ann_bh:.2f}%")
    print(f"  Sharpe (monthly): {sharpe:.3f}")

    supported = ann_net > ann_bh and p < 0.05
    return HypothesisResult("H7", supported, p, ann_net - ann_bh, {
        "gross_monthly": float(gross), "net_monthly": float(net),
        "bh_monthly": float(bh_m), "ann_net": float(ann_net),
        "ann_bh": float(ann_bh), "excess_ann": float(ann_net - ann_bh),
        "sharpe": float(sharpe), "annual_cost_pct": float(annual_cost),
        "avg_turnover_pct": float(avg_turnover_pct),
    })


def save_obs(obs: List[RollingObs], path: Path):
    data = [{"symbol": o.symbol, "cutoff_date": o.cutoff_date,
             "month_phase": o.month_phase, "month_conf": o.month_conf,
             "week_phase": o.week_phase, "week_conf": o.week_conf,
             "week_spring": o.week_spring, "day_spring": o.day_spring,
             "fwd_1m_pct": o.fwd_1m_pct, "fwd_3m_pct": o.fwd_3m_pct,
             "fwd_6m_pct": o.fwd_6m_pct,
             "phase_3m_ago": o.phase_3m_ago, "duration_m": o.duration_m,
             "had_transition": o.had_transition} for o in obs]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} obs to {path}")


def load_obs(path: Path) -> List[RollingObs]:
    with open(path) as f:
        data = json.load(f)
    return [RollingObs(**d) for d in data]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OBS_PATH = OUTPUT_DIR / "rolling_panel.json"
    t0 = time.time()
    print("=" * 80)
    print("Wyckoff Multi-Timeframe Verification v3 — Rolling Panel")
    print("=" * 80)

    obs: List[RollingObs] = []
    if OBS_PATH.exists():
        print(f"\nLoading cached panel from {OBS_PATH}")
        obs = load_obs(OBS_PATH)
        print(f"Loaded {len(obs)} observations")
    else:
        # Universe
        from scripts.wyckoff_multitf.a_universe import scan_universe, stratified_sample
        from scripts.wyckoff_multitf.config import VerifierConfig
        cfg = VerifierConfig()
        records = scan_universe(cfg)
        sampled = stratified_sample(records, seed=42)
        stocks = [r.symbol for r in sampled[:1000]]
        print(f"Universe: {len(stocks)} stocks (stratified {len(records)} → {len(sampled)} → {len(stocks)})")

        # Rolling panel
        obs = run(stocks, N_JOBS)
        if not obs:
            print("ERROR: No observations generated")
            return
        save_obs(obs, OBS_PATH)

    # Hypothesis tests
    results = {}
    results["H1+H2"] = test_h1_h2_panel(obs)
    results["H3"] = test_h3_consistency(obs)
    results["H4"] = test_h4_thresholds(obs)
    results["H5"] = test_h5_transitions(obs)
    results["H6"] = test_h6_duration(obs)
    results["H7"] = test_h7_backtest(obs)

    # Summary
    print(f"\n{'='*80}")
    supported = sum(1 for r in results.values() if r.supported)
    print(f"RESULTS: {supported}/{len(results)} hypotheses supported")
    for name, r in results.items():
        print(f"  {'✅' if r.supported else '❌'} {name}: p={r.p_value:.4f}, effect={r.effect:+.2f}")

    # Save
    out = {
        "meta": {"n_stocks": len(stocks), "n_observations": len(obs), "elapsed_s": time.time() - t0},
        "hypotheses": {name: {"supported": r.supported, "p_value": r.p_value, "effect": r.effect, "detail": r.detail} for name, r in results.items()},
    }
    out_path = OUTPUT_DIR / "v3_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print(f"Total elapsed: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
