"""本地通达信 .lc5 批量转换 → 日级隔夜因子基础表。

输入: Wine 通达信 vipdoc/{sh,sz}/fzline/*.lc5 (审计见 lc5_reader.py 模块注释)
输出: data/lake/quotes/minutedaily/{symbol}.parquet
列: date, open_px(首bar vwap), close_px(末bar vwap), on(隔夜), intra(日内),
    amount, volume, last30_share, n_bars
口径: OHLC 整数字段为本客户端压缩轨迹(不可用), 全部价格经 vwap=amount/volume。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.factor_mining.lc5_reader import parse_lc5  # noqa: E402

VIPDOC = Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc"
OUT_DIR = PROJECT_ROOT / "data/lake/quotes/minutedaily"


def symbol_from_path(p: Path) -> str | None:
    stem = p.stem.lower()
    if len(stem) != 8 or not stem[2:].isdigit():
        return None
    mkt, code = stem[:2], stem[2:]
    suffix = {"sh": "SH", "sz": "SZ"}.get(mkt)
    return f"{code}.{suffix}" if suffix else None


def convert_one(lc5_path: Path) -> pd.DataFrame | None:
    try:
        df = parse_lc5(lc5_path)
    except Exception:
        return None
    if df.empty:
        return None
    d = df.copy()
    d["vwap"] = d["amount"] / d["volume"].replace(0, np.nan)
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
    ap = argparse.ArgumentParser(description="本地 .lc5 → minutedaily 批量转换")
    ap.add_argument("--limit", type=int, default=None, help="仅处理前 N 只 (冒烟)")
    args = ap.parse_args(argv)

    t0 = time.time()
    files = sorted(VIPDOC.glob("*/fzline/*.lc5"))
    if args.limit:
        files = files[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_ok = n_skip = 0
    for i, p in enumerate(files, 1):
        sym = symbol_from_path(p)
        if sym is None:
            n_skip += 1
            continue
        day = convert_one(p)
        if day is None or len(day) < 10:
            n_skip += 1
            continue
        day.to_parquet(OUT_DIR / f"{sym}.parquet", index=False)
        n_ok += 1
        if i % 500 == 0:
            print(f"  {i}/{len(files)} 已完成 {n_ok} 跳过 {n_skip}", flush=True)
    print(f"完成: {n_ok} 只转换, {n_skip} 跳过, {time.time()-t0:.1f}s → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())