#!/usr/bin/env python3
"""T5 — P1-11 止损触发层触发率/误杀率 (golden_100, 三窗)。

proposed `_stop_loss_trigger` (对齐 yc:2600-2677):
  1. 深度破位短路: last_close ≤ stop*0.95 → 触发 "deep_break"
  2. 节后宽限期: 与前一交易日 gap≥3 自然日 → 不触发 "holiday_grace"
  3. 缩量洗盘不触发: 量比<0.8 且当日跌幅>-2% → 不触发 "volume_washout"
  4. 否则 last_close ≤ stop → 触发 "stop"

预注册阈值 (PREREGISTRATION T5):
  PASS ⇔ 触发率 ≤30% 且 误杀率 ≤50%
  误杀 = 触发后 5 日内任意 close 收回至 stop 之上

用法: python3 scripts/wyckoff_experiments/stoploss_exit_check.py [--symbols ...]
输出: results/wyckoff_experiments/stoploss_exit_check.json
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
PRE_REGISTERED_TRIGGER = 0.30
PRE_REGISTERED_FALSEKILL = 0.50


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


def stop_loss_trigger(df: pd.DataFrame, stop: float) -> tuple[bool, str]:
    """proposed P1-11 退出触发判定。df 含 date/open/high/low/close/volume。"""
    if len(df) < 2 or stop <= 0:
        return False, "no_stop"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    last_close = float(last["close"])
    prev_close = float(prev["close"])
    if last_close > stop:
        return False, "above_stop"

    if last_close <= stop * 0.95:
        return True, "deep_break"

    gap_days = (pd.Timestamp(last["date"]) - pd.Timestamp(prev["date"])).days
    if gap_days >= 3:
        return False, "holiday_grace"

    vol_med = df["volume"].tail(20).median()
    vol_ratio = float(last["volume"]) / vol_med if vol_med > 0 else 1.0
    day_ret = last_close / prev_close - 1 if prev_close > 0 else 0.0
    if vol_ratio < 0.8 and day_ret > -0.02:
        return False, "volume_washout"

    return True, "stop"


def recover_within(df: pd.DataFrame, stop: float, days: int = 5) -> bool:
    """触发后 days 日内任意 close 收回至 stop 之上 → 误杀。"""
    window = df.tail(days)
    return bool((window["close"] > stop).any())


def analyze(
    WyckoffEngine, symbol: str, asof: str
) -> dict:
    f = DAILY / f"{symbol}.parquet"
    if not f.exists():
        return {"symbol": symbol, "error": "no data"}
    df = pd.read_parquet(f)
    if "date" not in df.columns or df.empty:
        return {"symbol": symbol, "error": "bad data"}
    df["date"] = pd.to_datetime(df["date"])
    sub = df[df["date"] <= pd.Timestamp(asof)].reset_index(drop=True)
    if len(sub) < 120:
        return {"symbol": symbol, "error": "too_short"}
    try:
        rpt = WyckoffEngine().analyze(sub, symbol=symbol, period="日线", multi_timeframe=True)
    except Exception as e:
        return {"symbol": symbol, "error": f"engine: {type(e).__name__}"}
    stop = None
    try:
        stop = float(rpt.trading_plan.stop_loss.stop_loss_price)
    except (AttributeError, TypeError, ValueError):
        pass
    if not stop or stop <= 0:
        try:
            stop = float(rpt.structure.trading_range_low)
        except (AttributeError, TypeError, ValueError):
            return {"symbol": symbol, "error": "no stop"}
    trig, reason = stop_loss_trigger(sub, stop)
    # 用触发后实际出现的 K 线判断误杀
    future = df[df["date"] > pd.Timestamp(asof)]
    killed = recover_within(future, stop) if trig and len(future) >= 5 else False
    return {"symbol": symbol, "as_of": asof, "stop": stop,
            "triggered": trig, "reason": reason, "false_kill": killed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="tests/benchmark/golden_100.txt")
    ap.add_argument("--symbols", nargs="*", default=[])
    ap.add_argument("--as-of", default="all")
    args = ap.parse_args()

    symbols = args.symbols or load_symbols(args.golden)
    wins = [w for w, _ in ASOFS.items() if args.as_of in ("all", w)]
    sys.path.insert(0, str(ROOT / "src"))
    from uniquant.brain.wyckoff.engine import WyckoffEngine  # noqa: E402

    results: dict = {
        "pre_registered": {"trigger_rate<=0.30": PRE_REGISTERED_TRIGGER,
                           "false_kill_rate<=0.50": PRE_REGISTERED_FALSEKILL},
        "windows": {},
    }
    for w in wins:
        asof = ASOFS[w]
        rows = [analyze(WyckoffEngine, s, asof) for s in symbols]
        ok = [r for r in rows if "error" not in r]
        trig = [r for r in ok if r["triggered"]]
        fk = [r for r in trig if r["false_kill"]]
        rate = len(trig) / len(ok) if ok else 0.0
        fkrate = len(fk) / len(trig) if trig else 0.0
        reason_ctr: dict[str, int] = {}
        for r in trig:
            reason_ctr[r["reason"]] = reason_ctr.get(r["reason"], 0) + 1
        verdict = "PASS" if (rate <= PRE_REGISTERED_TRIGGER and fkrate <= PRE_REGISTERED_FALSEKILL) else "FAIL"
        results["windows"][w] = {
            "as_of": asof,
            "n": len(ok),
            "n_triggered": len(trig),
            "trigger_rate": round(rate, 4),
            "false_kill_rate": round(fkrate, 4),
            "reason_dist": reason_ctr,
            "verdict": verdict,
        }
        print(f"[{w}] n={len(ok)} trig={len(trig)} rate={rate:.1%} "
              f"falsekill={fkrate:.1%} reasons={reason_ctr} -> {verdict}")

    out = ROOT / "results" / "wyckoff_experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stoploss_exit_check.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())