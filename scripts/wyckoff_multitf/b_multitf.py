"""Module B: Multi-timeframe Wyckoff analysis with hierarchical signals."""

import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from .config import VerifierConfig
from .data_synthesis import load_and_synthesize
from .a_universe import StockRecord


TIME_LABELS = {"daily": "日线", "weekly": "周线", "monthly": "月线"}


@dataclass
class TfAnalysis:
    phase: str = "unknown"
    confidence: str = "D"
    spring_detected: bool = False
    lps_confirmed: bool = False
    rr_ratio: float = 0.0
    direction: str = ""
    action: str = ""
    unknown_candidate: str = ""


@dataclass
class MultiTfResult:
    symbol: str
    monthly: TfAnalysis = field(default_factory=TfAnalysis)
    weekly: TfAnalysis = field(default_factory=TfAnalysis)
    daily: TfAnalysis = field(default_factory=TfAnalysis)

    def signal_level(self) -> Tuple[str, float]:
        """Hierarchical signal level + position weight.
        
        Rules (from v2 plan §4.1):
          S+: monthly=accum + weekly=accum + weekly_spring → full position
          A:  monthly=accum + weekly=accum + daily_spring → 75%
          B:  monthly=accum + weekly_spring + daily_spring → 50%
          C:  monthly=accum + daily_spring → 25%
          D:  anything else → 0%
        """
        mp = self.monthly.phase
        wp = self.weekly.phase
        ws = self.weekly.spring_detected
        ds = self.daily.spring_detected
        wc = self.weekly.confidence

        def _conf_order(c):
            return {"A": 0, "B": 1, "C": 2, "D": 3}.get(c, 3)
        
        def _phase_order(p):
            return {"accumulation": 0, "markup": 1, "distribution": 2, "markdown": 3, "unknown": 4}.get(p, 4)

        mo = _phase_order(mp)
        wo = _phase_order(wp)

        # Rule 1: S+
        if mo <= 0 and wo <= 0 and ws and _conf_order(wc) <= 1:
            return ("S+", 1.0)
        # Rule 2: A
        if mo <= 0 and wo <= 0 and ds and _conf_order(wc) <= 2:
            return ("A", 0.75)
        # Rule 3: B
        if mo <= 0 and ws and ds:
            return ("B", 0.50)
        # Rule 4: C
        if mo <= 0 and ds:
            return ("C", 0.25)
        # Markup hold
        if mp == "markup" and wp == "markup":
            return ("B_hold", 0.50)
        # Markdown/distribution reduction
        if mp == "markdown" and (wp == "distribution" or self.daily.spring_detected):
            return ("C_reduce", -0.25)
        # Default: D
        return ("D", 0.0)

    @property
    def has_tradeable_signal(self) -> bool:
        level, _ = self.signal_level()
        return level in ("S+", "A", "B")


def analyze_stock_multitf(
    symbol: str, data_path: Path, config: VerifierConfig, cutoff_date: Optional[str] = None
) -> Optional[MultiTfResult]:
    """Run multi-timeframe Wyckoff analysis on one stock.
    
    If cutoff_date is provided, only data up to that date is analyzed,
    allowing forward return computation from the cutoff to end of data.
    """
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    raw_data = load_and_synthesize(symbol, data_path)
    if raw_data is None:
        return None
    daily_full, weekly_full, monthly_full = raw_data

    # If cutoff_date, truncate all three dataframes
    if cutoff_date is not None:
        cd = pd.Timestamp(cutoff_date)
        daily = daily_full[daily_full["date"] <= cd].copy()
        weekly = weekly_full[weekly_full["date"] <= cd].copy()
        monthly = monthly_full[monthly_full["date"] <= cd].copy()
        # Need at least min_bars in each
        if len(monthly) < 6 or len(weekly) < 12 or len(daily) < 120:
            return None
    else:
        daily, weekly, monthly = daily_full, weekly_full, monthly_full

    result = MultiTfResult(symbol=symbol)

    tf_configs = [
        ("daily", daily, config.daily_params.lookback, 120),
        ("weekly", weekly, config.weekly_params.lookback, 12),
        ("monthly", monthly, config.monthly_params.lookback, 6),
    ]

    for tf_name, tf_df, lookback, min_bars in tf_configs:
        if len(tf_df) < min_bars:
            continue
        try:
            engine = WyckoffEngine(lookback_days=lookback)
            report = engine.analyze(tf_df, symbol=symbol, period=TIME_LABELS[tf_name])

            analysis = TfAnalysis()
            # WyckoffReport is a dataclass
            structure = getattr(report, "structure", None)
            signal = getattr(report, "signal", None)
            rr = getattr(report, "risk_reward", None)
            plan = getattr(report, "trading_plan", None)

            if structure is not None:
                analysis.phase = getattr(structure.phase, "value", "unknown") if hasattr(structure.phase, "value") else str(structure.phase)
                analysis.unknown_candidate = getattr(structure, "unknown_candidate", "")
            if signal is not None:
                conf = getattr(signal, "confidence", None)
                analysis.confidence = getattr(conf, "value", "D") if hasattr(conf, "value") else str(conf)
                analysis.spring_detected = getattr(signal, "spring_date", None) is not None
            if rr is not None:
                analysis.rr_ratio = getattr(rr, "reward_risk_ratio", 0.0)
            if plan is not None:
                analysis.direction = getattr(plan, "direction", "")
                analysis.action = plan.direction if hasattr(plan, "direction") else ""

            setattr(result, tf_name, analysis)

        except Exception as exc:
            pass

    return result


def analyze_batch(
    records: List[StockRecord], config: VerifierConfig, cutoff_date: Optional[str] = None
) -> List[MultiTfResult]:
    """Run multi-timeframe analysis on all stocks in parallel.
    
    If cutoff_date is provided, only data up to that date is analyzed.
    """
    print(f"\n=== Multi-Timeframe Wyckoff Analysis{'' if cutoff_date is None else ' (cutoff: ' + cutoff_date + ')'} ===")
    results: List[MultiTfResult] = []
    n_total = len(records)

    with ProcessPoolExecutor(max_workers=config.n_jobs) as pool:
        fut_map = {
            pool.submit(analyze_stock_multitf, r.symbol, config.data_lake, config, cutoff_date): r.symbol
            for r in records
        }
        done = 0
        for fut in as_completed(fut_map):
            done += 1
            try:
                res = fut.result()
                if res is not None:
                    results.append(res)
            except Exception as exc:
                pass
            if done % 100 == 0:
                print(f"  {done}/{n_total}")

    # Report phase distribution
    counts = defaultdict(int)
    for r in results:
        counts[r.monthly.phase] += 1
    print(f"  Monthly phase distribution ({len(results)} stocks):")
    for p in ["accumulation", "markup", "distribution", "markdown", "unknown"]:
        print(f"    {p}: {counts[p]} ({counts[p]/len(results)*100:.1f}%)")

    # Signal distribution
    sig_counts = defaultdict(int)
    for r in results:
        level, _ = r.signal_level()
        sig_counts[level] += 1
    print(f"  Signal level distribution:")
    for l in ["S+", "A", "B", "B_hold", "C", "C_reduce", "D"]:
        c = sig_counts.get(l, 0)
        print(f"    {l}: {c} ({c/len(results)*100:.1f}%)")

    return results
