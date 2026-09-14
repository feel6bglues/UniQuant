# -*- coding: utf-8 -*-
"""T35 核心持仓池日线拉取 (P1 共同数据前置)
1) 重建季频核心 cache -> 收集全部调仓点 Top10% 并集 = core pool
2) 线程池 12 拉日线 (frequency=9, offset=1900, 2014-2026) -> core_pool_daily.json
存储: {code: {YYYYMMDD: {o,h,l,c,v,a}}} 精简字段
"""
import sys, io, json, os, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pipeline_common as pc

ALL_CODES = json.load(open("mx_fin_data/all_a_codes.json"))
a_monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
xdxr_all = pc.load_xdxr("all_a_xdxr.json")
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(ALL_CODES, a_monthly)
TOP = max(30, int(len(ALL_CODES) * 0.10))

# ---------- 1. 核心持仓池 (季频新核心 Top10% 并集) ----------
print("构建因子缓存...", flush=True)
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)
pool = set()
REBAL = [m for m in months if m % 100 in (5, 9, 11)]
for m in REBAL:
    sc = {cd: pc.score_from_cache(cache, m, cd, keys=("cash", "fcfy", "ep"), min_valid=2) for cd in ALL_CODES}
    sc = {cd: v for cd, v in sc.items() if v is not None and not np.isnan(v)}
    if len(sc) >= TOP:
        pool.update(sorted(sc, key=sc.get, reverse=True)[:TOP])
pool = sorted(pool)
print(f"核心持仓池: {len(pool)} 只 (季度调仓 Top10% 并集)", flush=True)
json.dump(pool, open("mx_fin_data/core_pool_codes.json", "w"))
print("已存 core_pool_codes.json", flush=True)

# ---------- 2. 日线拉取 (线程池 12, 断点续传) ----------
from concurrent.futures import ThreadPoolExecutor, as_completed
from mootdx.quotes import Quotes

OUT = "mx_fin_data/core_pool_daily.json"
data = json.load(open(OUT)) if os.path.exists(OUT) else {}
print(f"已缓存日线: {len(data)} 只", flush=True)

_local = threading.local()
def get_qc():
    if not hasattr(_local, "qc"):
        _local.qc = Quotes.factory(market="std", timeout=20)
    return _local.qc

def pull(code):
    qc = get_qc()
    for attempt in range(3):
        try:
            df = qc.bars(symbol=code, frequency=9, start=0, offset=1900)
            if df is not None and len(df):
                out = {}
                for _, r in df.iterrows():
                    dt = str(r["datetime"]).replace("-", "")[:8]
                    if len(dt) != 8:
                        continue
                    out[dt] = {"o": float(r["open"]), "h": float(r["high"]),
                               "l": float(r["low"]), "c": float(r["close"]),
                               "v": float(r["vol"]) if r["vol"] else 0.0,
                               "a": float(r["amount"]) if r["amount"] else 0.0}
                return code, out
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return code, None

todo = [c for c in pool if c not in data]
print(f"待拉: {len(todo)} 只 (池 {len(pool)})", flush=True)
t0 = time.time()
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(pull, c): c for c in todo}
    for i, fut in enumerate(as_completed(futs)):
        code, out = fut.result()
        if out:
            data[code] = out
        if (i + 1) % 100 == 0:
            json.dump(data, open(OUT, "w"))
            el = (time.time() - t0) / 60
            print(f"  [{i+1}/{len(todo)}] {len(data)} 只 | {el:.1f}min", flush=True)
json.dump(data, open(OUT, "w"))
print(f"DONE: {len(data)} 只日线 | {(time.time()-t0)/60:.1f}min", flush=True)
