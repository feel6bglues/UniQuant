"""A 路线: 通达信服务器 5 分钟线拉取 → 日级聚合 → 与本地 lc5 段拼接。

背景: 本地 Wine 客户端 .lc5 止于 2026-02-25; 服务器分页可回溯至 ~2025-10。
本脚本拉取研究面板 (500 只 seed=42) 的服务器 5 分钟线, 用与本地完全相同的
vwap 口径聚合为日级表, 并在重叠期 (2025-11~2026-02) 做水平校准后拼接。

口径一致性 (防接缝污染):
  - 价格 = 逐 bar amount/volume (vwap); 首末 bar vwap 作开/收盘代理
  - 校准: 取重叠日 close_px 比值中位数 scale, 服务器段整体除以该比值;
    要求重叠期日收益相关 ≥0.9 否则丢弃该股服务器段 (QA 报告记录)
输出: data/lake/quotes/minutedaily_full/{symbol}.parquet
QA: results/factor_mining/minute_fetch_qa.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_DIR = PROJECT_ROOT / "data/lake/quotes/minutedaily"
OUT_DIR = PROJECT_ROOT / "data/lake/quotes/minutedaily_full"
QA_PATH = PROJECT_ROOT / "results/factor_mining/minute_fetch_qa.json"
PAGES_MAX = 16          # 16×800=12800 根 ≈ 全深度
BARS_PER_PAGE = 800


def fetch_bars_5m(client, symbol6: str) -> pd.DataFrame | None:
    """分页拉取单只 5 分钟线; 返回含 datetime/open/high/low/close/volume/amount。"""
    frames = []
    start = 0
    for _ in range(PAGES_MAX):
        try:
            df = client.bars(symbol=symbol6, frequency=0, offset=BARS_PER_PAGE,
                             start=start)
        except Exception:
            time.sleep(1.0)
            try:
                df = client.bars(symbol=symbol6, frequency=0,
                                 offset=BARS_PER_PAGE, start=start)
            except Exception:
                return None
        if df is None or len(df) == 0:
            break
        frames.append(df)
        start += len(df)
        if len(df) < BARS_PER_PAGE:
            break
        time.sleep(0.03)
    if not frames:
        return None
    out = pd.concat(frames)
    if "datetime" in out.columns:
        out = out.reset_index(drop=True)
    else:
        out = out.reset_index()
    out = out.rename(columns={c: str(c).lower() for c in out.columns})
    if "datetime" not in out.columns:
        return None
    out["datetime"] = pd.to_datetime(out["datetime"])
    return out.sort_values("datetime").drop_duplicates("datetime")


def daily_from_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """与本地 lc5 相同的 vwap 口径日级聚合。"""
    d = bars.copy()
    d["vwap"] = d["amount"] / d["volume"].replace(0, np.nan)
    # 服务器量纲自检: 若 vwap 中位数明显偏离常识 (>1e4 或 <1e-2), 记录但继续
    d["dte"] = d["datetime"].dt.date
    g = d.groupby("dte")
    day = g.agg(
        open_px=("vwap", "first"),
        close_px=("vwap", "last"),
        amount=("amount", "sum"),
        volume=("volume", "sum"),
        n_bars=("datetime", "count"),
    ).reset_index(names="date")
    day["on"] = day["open_px"] / day["close_px"].shift(1) - 1
    day["intra"] = day["close_px"] / day["open_px"] - 1
    tail = (
        d[d["datetime"].dt.strftime("%H:%M") >= "14:30"]
        .groupby("dte")["amount"]
        .sum()
    )
    day["last30_share"] = day["date"].map(tail / day.set_index("date")["amount"])
    return day


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务器 5 分钟线拉取+拼接")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    t0 = time.time()

    # 研究面板 (同 P1-P8): 500 只 seed=42
    from scripts.factor_mining.data_loader import load_universe

    dfu = load_universe(as_of="2026-05-29", max_workers=16)
    codes_all = sorted(dfu["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes_all, size=min(500, len(codes_all)), replace=False)

    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qa = {}
    targets = list(selected[: args.limit] if args.limit else selected)

    for i, sym in enumerate(targets, 1):
        code6 = sym.split(".")[0]
        q = {"status": "ok"}
        bars = fetch_bars_5m(client, code6)
        if bars is None or len(bars) < 200:
            q = {"status": "fetch_failed", "bars": 0 if bars is None else len(bars)}
            qa[sym] = q
            continue
        srv = daily_from_bars(bars)

        local_p = LOCAL_DIR / f"{sym}.parquet"
        scale, corr, src_local = 1.0, None, False
        if local_p.exists():
            loc = pd.read_parquet(local_p)
            m = srv.merge(loc[["date", "close_px"]], on="date", suffixes=("_s", "_l"))
            m = m.dropna()
            if len(m) >= 15:
                rs = m["close_px_s"].pct_change()
                rl = m["close_px_l"].pct_change()
                corr = float(pd.concat([rs, rl], axis=1).corr().iloc[0, 1])
                base_ratio = (m["close_px_l"] / m["close_px_s"]).median()
                scale = float(base_ratio) if np.isfinite(base_ratio) and base_ratio > 0 else 1.0
                src_local = True
        srv["close_px"] = srv["close_px"] * scale
        srv["open_px"] = srv["open_px"] * scale
        srv["on"] = srv["open_px"] / srv["close_px"].shift(1) - 1
        srv["intra"] = srv["close_px"] / srv["open_px"] - 1
        srv["src"] = "srv"

        if src_local and corr is not None and corr < 0.9:
            q = {"status": "rejected_low_corr", "overlap_days": int(len(m)),
                 "corr": round(corr, 3)}
            qa[sym] = q
            continue

        merged_parts = [srv]
        if local_p.exists():
            loc = pd.read_parquet(local_p)
            loc["src"] = "local"
            cutoff = srv["date"].min()
            loc_old = loc[loc["date"] < cutoff]
            if len(loc_old):
                merged_parts.append(loc_old)
        full = pd.concat(merged_parts, ignore_index=True)
        full = full.drop_duplicates(subset="date", keep="first")
        full = full.sort_values("date").reset_index(drop=True)
        full.to_parquet(OUT_DIR / f"{sym}.parquet", index=False)

        q.update({
            "srv_days": int(len(srv)), "merged_days": int(len(full)),
            "scale": round(scale, 6),
            "overlap_corr": None if corr is None else round(corr, 4),
        })
        qa[sym] = q
        if i % 50 == 0:
            print(f"  {i}/{len(targets)} 完成", flush=True)

    ok = sum(1 for v in qa.values() if v.get("status") == "ok")
    scales = [v.get("scale") for v in qa.values() if v.get("status") == "ok"]
    corrs = [v.get("overlap_corr") for v in qa.values()
             if v.get("status") == "ok" and v.get("overlap_corr") is not None]
    summary = {
        "n_ok": ok, "elapsed_sec": round(time.time() - t0, 1),
        "scale_median": round(float(np.median(scales)), 6) if scales else None,
        "overlap_corr_median": round(float(np.median(corrs)), 4) if corrs else None,
        "n_with_overlap": len(corrs),
    }
    QA_PATH.parent.mkdir(parents=True, exist_ok=True)
    QA_PATH.write_text(json.dumps({"summary": summary, "symbols": qa},
                                  ensure_ascii=False, indent=1))
    print(f"完成: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())