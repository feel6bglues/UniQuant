# -*- coding: utf-8 -*-
"""拉取 45 期季报 gpcw zip (2010Q1~2024Q3: 0331/0630/0930), 8 线程并行
产物: mx_fin_data/gpcw{YYYYMMDD}.zip + .csv (与年报同目录, 供季频因子面板)
"""
import sys, io, os, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ThreadPoolExecutor, as_completed
from mootdx_client import MootdxClient

PERIODS = [f"{y}{q}" for y in range(2010, 2025) for q in ("0331", "0630", "0930")]
todo = [p for p in PERIODS if not os.path.exists(f"mx_fin_data/gpcw{p}.csv")]
print(f"季报期数: {len(PERIODS)} | 待拉: {len(todo)}", flush=True)

_local = threading.local()
def get_client():
    if not hasattr(_local, "c"):
        _local.c = MootdxClient()
    return _local.c

def pull(p):
    c = get_client()
    try:
        df = c.fetch_report(f"gpcw{p}.zip")
        return p, len(df)
    except Exception as e:
        return p, f"ERR:{e}"

t0 = time.time()
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(pull, p): p for p in todo}
    done = 0
    for fut in as_completed(futs):
        p, n = fut.result()
        done += 1
        if isinstance(n, int):
            print(f"  [{done}/{len(todo)}] {p}: {n} 行", flush=True)
        else:
            print(f"  [{done}/{len(todo)}] {p}: {n}", flush=True)
        if done % 5 == 0:
            el = (time.time() - t0) / 60
            print(f"    ... {el:.1f}min", flush=True)

print(f"DONE: {(time.time()-t0)/60:.1f}min")
