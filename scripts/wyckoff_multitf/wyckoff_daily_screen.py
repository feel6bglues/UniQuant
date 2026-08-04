#!/usr/bin/env python3
"""Phase G: Wyckoff Daily Signal Screen — production-ready daily pipeline.

Scans all tradeable A-share stocks through WyckoffEngine, scores signals
with WSOScorer, applies A-share constraints, and outputs ranked signal list.

Usage:
    python3 scripts/wyckoff_multitf/wyckoff_daily_screen.py [--date 2024-06-28] [--top 20]
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.uniquant.brain.wyckoff.engine import WyckoffEngine
from src.uniquant.brain.wyckoff.events import detect_all_events, event_sequence_key
from src.uniquant.brain.wyckoff.sequence import WSOScorer, WyckoffScorer
from src.uniquant.shared.cost_model import COST_BUY, COST_SELL
from scripts.wyckoff_multitf.ashare_constraints import AShareConstraints

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)


def estimate_round_trip_cost(price: float) -> float:
    """Round-trip transaction cost as percentage of notional (1-lot assumption)."""
    return round((COST_BUY + COST_SELL) * 100, 4)


@dataclass
class SignalCandidate:
    symbol: str
    date: str
    signal: str  # 'buy' | 'sell' | 'hold'
    score: float
    confidence: float
    events: list[str]
    last_close: float
    volume_ratio: float
    tradeable: bool
    reject_reason: str = ""
    regime: str = "neutral"
    n_events: int = 0
    cost_pct: float = 0.0
    score_net: float = 0.0
    expected_return_pct: float = 0.0


def analyze_one(symbol: str, date: str) -> Optional[SignalCandidate]:
    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        daily = pd.read_parquet(fp)
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date").reset_index(drop=True)
        if len(daily) < 200:
            return None

        idx = daily[daily["date"] <= pd.Timestamp(date)].index[-1] if any(
            daily["date"] <= pd.Timestamp(date)) else -1
        if idx < 120:
            return None

        window = daily.iloc[max(0, idx - 119): idx + 1].reset_index(drop=True)

        constraints = AShareConstraints()
        tradeable, reason = constraints.can_trade(symbol, date, daily)
        if constraints.is_suspended(daily):
            tradeable, reason = False, "suspended_5d"

        engine = WyckoffEngine(lookback_days=120)
        engine.analyze(window, symbol=symbol, period="日线")
        events = detect_all_events(window)
        event_types = [e.event_type for e in events if e.confidence > 0.3]
        seq_key = event_sequence_key(events) if events else "NONE"

        if not event_types:
            return SignalCandidate(
                symbol=symbol, date=date, signal="hold", score=0.0,
                confidence=0.0, events=[], last_close=float(window["close"].iloc[-1]),
                volume_ratio=0.0, tradeable=tradeable, reject_reason="no_events",
                n_events=0,
            )

        WSS_PATH = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4" / "wss_lookup_v2.json"
        if WSS_PATH.exists():
            scorer = WyckoffScorer(wss_path=str(WSS_PATH))
        else:
            scorer = WSOScorer()

        if isinstance(scorer, WyckoffScorer):
            wso_score_raw, sig = scorer.score_sequence(event_types, seq_key=seq_key)
        else:
            wso_score_raw = scorer.score_events(event_types)
            sig = scorer.signal(wso_score_raw)

        raw_conf = abs(wso_score_raw) * 10
        confidence = min(1.0, raw_conf)

        last_price = float(window["close"].iloc[-1])
        cost_pct = estimate_round_trip_cost(last_price)
        score_net = round(wso_score_raw - cost_pct * 10, 4)
        expected_return_pct = round(abs(wso_score_raw) * 10 - cost_pct, 4)

        last_vol = int(window["volume"].iloc[-1])
        vol_ma = int(window["volume"].tail(20).mean()) if len(window) >= 20 else last_vol
        vol_ratio = last_vol / vol_ma if vol_ma > 0 else 1.0

        return SignalCandidate(
            symbol=symbol, date=date, signal=sig,
            score=round(wso_score_raw, 4), confidence=round(confidence, 4),
            events=event_types, last_close=last_price,
            volume_ratio=round(vol_ratio, 2), tradeable=tradeable,
            reject_reason=reason if not tradeable else "",
            n_events=len(event_types),
            cost_pct=cost_pct,
            score_net=score_net,
            expected_return_pct=expected_return_pct,
        )
    except Exception:
        return None


def screen(date: str, symbols: Optional[list[str]] = None, top_k: int = 50) -> list[SignalCandidate]:
    if symbols is None:
        parquet_files = sorted(DATA_LAKE.glob("*.parquet"))
        symbols = sorted(set(p.stem for p in parquet_files))

    print(f"Screening {len(symbols)} stocks on {date}...")
    t0 = time.time()
    results: list[SignalCandidate] = []
    with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
        fut = {pool.submit(analyze_one, s, date): s for s in symbols}
        done = 0
        for f in as_completed(fut):
            done += 1
            try:
                r = f.result()
                if r is not None:
                    results.append(r)
            except Exception:
                pass
            if done % 500 == 0 or done == len(symbols):
                print(f"  {done}/{len(symbols)}, {len(results)} candidates, {time.time()-t0:.0f}s")

    print(f"\nDone: {len(results)} stocks analyzed in {time.time()-t0:.0f}s")

    # Rank: non-hold signals first, by confidence
    signals = [r for r in results if r.signal != "hold"]
    [r for r in results if r.signal == "hold"]
    signals.sort(key=lambda x: (x.confidence, abs(x.score)), reverse=True)
    top = signals[:top_k]

    print(f"\n── Top {len(top)} Signals (out of {len(signals)} total) ──")
    print(f"  {'Rank':<5} {'Symbol':<12} {'Sig':<6} {'Score':>8} {'NetScr':>8} {'Cost%':>7} {'ExpRet%':>9} {'Conf':>6} {'Events':<28} {'VolRat':>7}")
    for i, c in enumerate(top):
        ev = ">".join(c.events) if c.events else "—"
        print(f"  {i+1:<5} {c.symbol:<12} {c.signal:<6} {c.score:>+8.4f} {c.score_net:>+8.4f} {c.cost_pct:>7.4f} {c.expected_return_pct:>9.4f} {c.confidence:>6.2f} {ev:<28} {c.volume_ratio:>7.2f}")

    summary = {
        "date": date,
        "total_stocks": len(symbols),
        "analyzed": len(results),
        "buy_signals": sum(1 for r in results if r.signal == "buy"),
        "sell_signals": sum(1 for r in results if r.signal == "sell"),
        "hold_count": sum(1 for r in results if r.signal == "hold"),
        "tradeable_ratio": sum(1 for r in results if r.tradeable) / max(1, len(results)),
        "top_signals": [
            {
                "symbol": c.symbol,
                "signal": c.signal,
                "score": c.score,
                "score_net": c.score_net,
                "cost_pct": c.cost_pct,
                "expected_return_pct": c.expected_return_pct,
                "confidence": c.confidence,
                "events": c.events,
                "last_close": c.last_close,
                "volume_ratio": c.volume_ratio,
                "tradeable": c.tradeable,
            }
            for c in top
        ],
    }

    out_path = OUTPUT_DIR / f"daily_screen_{date}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wyckoff Daily Signal Screen")
    parser.add_argument("--date", default=pd.Timestamp.today().strftime("%Y-%m-%d"),
                        help="Screen date (default: today)")
    parser.add_argument("--top", type=int, default=50, help="Top K signals to report")
    parser.add_argument("--symbols", nargs="*", help="Specific symbols to screen")
    args = parser.parse_args()

    screen(date=args.date, symbols=args.symbols, top_k=args.top)


if __name__ == "__main__":
    main()
