"""H-A 条件流动性策略 — 每日信号运行器 (工程化形态)。

用法 (cron 每交易日收盘后):
    python3 scripts/canslim/daily_signal_ha.py [--as-of YYYY-MM-DD]

输出: results/h_a_signals/{date}.json  状态 + (在场时) 目标组合
参数与预注册一致 (P7/P8/D+10 冻结); AMOUNT_FLOOR=None 主版本 / 2e7 回撤敏感变体。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TOP_N = 30
AMOUNT_FLOOR = None
LIMIT_UP_PCT = 0.095
MA_WINDOW = 200
VOL_ROLL = 20
VOL_PIT_WINDOW = 750
VOL_PIT_MIN = 250
VOL_Q = (0.33, 0.67)
SIGNAL_DIR = PROJECT_ROOT / "results/h_a_signals"


def compute_state(idx: pd.DataFrame, as_of: str | None) -> dict:
    idx = idx.sort_values("date").copy()
    idx["date"] = pd.to_datetime(idx["date"])
    if as_of:
        idx = idx[idx["date"] <= pd.Timestamp(as_of)]
    close = idx["close"]
    trend_on = bool(close.iloc[-1] > close.rolling(MA_WINDOW).mean().iloc[-1])
    vol20 = close.pct_change().rolling(VOL_ROLL).std()
    q_lo = vol20.rolling(VOL_PIT_WINDOW, min_periods=VOL_PIT_MIN).quantile(VOL_Q[0])
    q_hi = vol20.rolling(VOL_PIT_WINDOW, min_periods=VOL_PIT_MIN).quantile(VOL_Q[1])
    v, lo, hi = vol20.iloc[-1], q_lo.iloc[-1], q_hi.iloc[-1]
    if any(pd.isna(x) for x in (v, lo, hi)):
        vol_state = "insufficient_history"
    else:
        vol_state = "vol_low" if v <= lo else ("vol_mid" if v <= hi else "vol_high")
    hot_bull = bool(trend_on and vol_state == "vol_high")
    return {
        "as_of": str(idx["date"].iloc[-1].date()),
        "idx_close": round(float(close.iloc[-1]), 2),
        "trend_on": trend_on,
        "vol_state": vol_state,
        "hot_bull": hot_bull,
    }


def build_target(as_of: str | None) -> dict:
    from scripts.canslim.growth_factors import load_financial_codes
    from scripts.factor_mining.data_loader import load_universe
    from uniquant.brain.factors.custom_factors import compute_illiq_20d

    df = load_universe(as_of=as_of, max_workers=16)
    df["date"] = pd.to_datetime(df["date"])
    last_dt = df["date"].max()
    day = df[df["date"] == last_dt].copy()
    prev = (df[df["date"] < last_dt].sort_values("date").groupby("code").tail(1))
    gap = day.set_index("code")["close"] / prev.set_index("code")["close"] - 1

    parts = []
    for code, g in df.sort_values("date").groupby("code"):
        s = compute_illiq_20d(g.tail(40).reset_index(drop=True))
        if len(s):
            parts.append({"code": code, "illiq": float(s.iloc[-1])})
    illiq = pd.DataFrame(parts).set_index("code")

    fin = load_financial_codes()
    amt_med = (df[df["date"] > last_dt - pd.Timedelta(days=45)]
               .groupby("code")["amount"].median())

    elig = illiq.join(gap.rename("gap")).join(amt_med.rename("amt_med")).dropna(subset=["illiq"])
    m_fin = np.asarray(elig.index.map(lambda c: c[:6] in fin))
    m_gap = elig["gap"] < LIMIT_UP_PCT
    m_amt = (pd.Series(True, index=elig.index) if AMOUNT_FLOOR is None
             else elig["amt_med"] >= AMOUNT_FLOOR)
    keep = elig[~m_fin & m_gap & m_amt]
    target = keep.sort_values("illiq", ascending=False).head(TOP_N)
    return {
        "as_of": str(last_dt.date()),
        "n_eligible": int(len(elig)),
        "target": [
            {"code": c,
             "weight": round(1.0 / max(len(target), 1), 4),
             "illiq": round(float(r["illiq"]), 2),
             "adv20_wan": round(float(r["amt_med"]) / 1e4, 1) if pd.notna(r["amt_med"]) else None}
            for c, r in target.iterrows()
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="H-A 每日信号")
    ap.add_argument("--as-of", type=str, default=None)
    args = ap.parse_args(argv)

    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    state = compute_state(pd.read_parquet(idx_path), args.as_of)
    out = {"generated_at": _dt.now().isoformat(timespec="seconds"),
           "strategy": "H-A conditional illiquidity (P7/P8/D+10)",
           "state": state}

    tgt_asof = None
    if state["hot_bull"]:
        tgt = build_target(args.as_of)
        tgt_asof = tgt["as_of"]
        out["target_portfolio"] = tgt
        out["action"] = f"HOLD top{TOP_N} illiq (equal weight)"
        print(f"[H-A] 过热牛 ✓ → 目标 {len(tgt['target'])} 只 (合格池 {tgt['n_eligible']})")
        for t in tgt["target"][:10]:
            print(f"    {t['code']} w={t['weight']:.4f} illiq={t['illiq']:,.0f} ADV≈{t['adv20_wan']:,.0f}万")
    else:
        out["action"] = "CASH (state off)"
        out["target_portfolio"] = {"as_of": state["as_of"], "target": []}
        print(f"[H-A] {state['trend_on']}/{state['vol_state']} → 空仓")

    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    fp = SIGNAL_DIR / f"{tgt_asof or state['as_of']}.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"信号 → {fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
