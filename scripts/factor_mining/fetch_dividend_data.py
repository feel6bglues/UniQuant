"""TDX xdxr 真实分红拉取器 — 填充 data/lake/dividend/。

数据源: 通达信行情服务器 xdxr (mootdx.quotes.Quotes.xdxr)。
字段语义 (经 600519 实测锚定, 2026-08-28):
  fenhong = 每 10 股派现额(元) → 每股股息 dps = fenhong/10
  category == 1 为"除权除息"记录 (含派现); 2/5 为股本变化(送配股/股本变化)
  songzhuangu = 每 10 股送转股数; xingquanjia = 除权参考价
只保留 category==1 的派现记录 (real_dy 分子 = 当年 dps 之和)。

用法:
    python3 scripts/factor_mining/fetch_dividend_data.py            # 全量
    python3 scripts/factor_mining/fetch_dividend_data.py --smoke    # 冒烟 20 只
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FIN_DIR = PROJECT_ROOT / "data" / "lake" / "financial"
OUTPUT_DIR = PROJECT_ROOT / "data" / "lake" / "dividend"


def _mootdx_quotes():
    from mootdx.quotes import Quotes
    return Quotes.factory(market="std")


def fetch_one(q, symbol: str) -> pd.DataFrame | None:
    """拉取单只股票 xdxr, 仅保留 category==1 派现记录, 返回 {code, year, ex_date, dps}。"""
    code6 = symbol.split(".")[0]
    try:
        res = q.xdxr(symbol=code6)
    except Exception:
        return None
    if res is None or getattr(res, "empty", True):
        return None
    cash = res[res["category"] == 1].copy()
    if cash.empty:
        return None
    cash["code"] = symbol
    cash["dps"] = cash["fenhong"] / 10.0
    cash["ex_date"] = cash["year"].astype(int) * 10000 + cash["month"].astype(int) * 100 + cash["day"].astype(int)
    keep = ["code", "year", "ex_date", "dps"]
    out = cash[keep].drop_duplicates(subset=["code", "ex_date"]).sort_values("ex_date")
    return out


def main():
    ap = argparse.ArgumentParser(description="TDX xdxr 真实分红拉取 (P14 real_dy 数据轨道)")
    ap.add_argument("--smoke", action="store_true", help="冒烟: 仅 20 只")
    ap.add_argument("--max-workers", type=int, default=16)
    args = ap.parse_args()

    symbols = sorted(p.name.removesuffix(".parquet") for p in FIN_DIR.glob("*.parquet"))
    if args.smoke:
        symbols = symbols[:20]
    print(f"目标池 {len(symbols)} 只 (financial 目录对齐)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    todo = [s for s in symbols if not (OUTPUT_DIR / f"{s}.parquet").exists()]
    print(f"待拉取 {len(todo)} 只 (断点续传跳过已有)")
    if not todo:
        print("全部已完成")
        return

    q = _mootdx_quotes()
    t0 = time.time()
    done, fail = 0, 0
    for i, sym in enumerate(todo):
        df = fetch_one(q, sym)
        if df is not None:
            df.to_parquet(OUTPUT_DIR / f"{sym}.parquet", index=False)
            done += 1
        else:
            fail += 1
        if (i + 1) % 200 == 0 or i == len(todo) - 1:
            el = time.time() - t0
            print(f"  [{i+1}/{len(todo)}] 成功 {done} 失败 {fail} 耗时 {el:.0f}s "
                  f"({(i+1)/el:.1f} 只/s)")
    print(f"完成: 成功 {done}, 失败 {fail}, 总计 {(time.time()-t0)/60:.1f} min")
    print(f"输出: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
