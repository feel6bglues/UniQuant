# -*- coding: utf-8 -*-
"""全 A xdxr 真实分红 + 月线 OHLCV(含 amount) 并行拉取
线程池 12 (网络 IO 密集, 每 worker 独立 TDX 连接), 断点续传, 失败重试
产物: all_a_xdxr.json {code: [{year, dps}]}, all_a_ohlcv.json {code: {ym: {close, amount, vol}}}
"""
import sys, io, os, json, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ThreadPoolExecutor, as_completed
from mootdx.quotes import Quotes

CODES = json.load(open("mx_fin_data/all_a_codes.json"))
print(f"全A 列表: {len(CODES)} 只", flush=True)

XDXR_OUT, OHLCV_OUT = "mx_fin_data/all_a_xdxr.json", "mx_fin_data/all_a_ohlcv.json"
xdxr_data = json.load(open(XDXR_OUT)) if os.path.exists(XDXR_OUT) else {}
ohlcv_data = json.load(open(OHLCV_OUT)) if os.path.exists(OHLCV_OUT) else {}
print(f"已缓存 xdxr: {len(xdxr_data)} | ohlcv: {len(ohlcv_data)}", flush=True)

_local = threading.local()
def get_qc():
    if not hasattr(_local, "qc"):
        _local.qc = Quotes.factory(market="std", timeout=20)
    return _local.qc

def pull_xdxr(code):
    qc = get_qc()
    for attempt in range(3):
        try:
            df = qc.xdxr(symbol=code)
            recs = []
            if df is not None and len(df):
                for _, r in df.iterrows():
                    try:
                        if r["category"] == 1 and r["fenhong"] and r["fenhong"] > 0:
                            recs.append({"year": int(r["year"]), "dps": float(r["fenhong"]) / 10.0})
                    except Exception:
                        pass
            return code, recs
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return code, None

def pull_ohlcv(code):
    qc = get_qc()
    for attempt in range(3):
        try:
            df = qc.bars(symbol=code, frequency=6, start=0, offset=160)
            if df is not None and len(df):
                out = {}
                for _, r in df.iterrows():
                    dt = str(r["datetime"])
                    out[dt[:4] + dt[5:7]] = {
                        "close": float(r["close"]),
                        "amount": float(r["amount"]) if r["amount"] else 0.0,
                        "vol": float(r["vol"]) if r["vol"] else 0.0}
                return code, out
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return code, None

todo_x = [c for c in CODES if c not in xdxr_data or not xdxr_data.get(c)]
todo_o = [c for c in CODES if c not in ohlcv_data or len(ohlcv_data.get(c, {})) < 100]
tasks = [("x", c) for c in todo_x] + [("o", c) for c in todo_o]
print(f"待拉 xdxr: {len(todo_x)} | ohlcv: {len(todo_o)} | 总任务: {len(tasks)} (池12)", flush=True)

t0 = time.time()
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(pull_xdxr if t == "x" else pull_ohlcv, c): (t, c) for t, c in tasks}
    for i, fut in enumerate(as_completed(futs)):
        t, c = futs[fut]
        try:
            res = fut.result()
            if res is None:
                continue
            if t == "x":
                code, recs = res
                if recs is not None and recs:
                    xdxr_data[code] = recs
            else:
                code, m = res
                if m:
                    ohlcv_data[code] = m
        except Exception:
            pass
        if (i + 1) % 300 == 0:
            json.dump(xdxr_data, open(XDXR_OUT, "w"))
            json.dump(ohlcv_data, open(OHLCV_OUT, "w"))
            el = (time.time() - t0) / 60
            print(f"  [{i+1}/{len(tasks)}] xdxr {len(xdxr_data)} | ohlcv {len(ohlcv_data)} | {el:.1f}min", flush=True)

json.dump(xdxr_data, open(XDXR_OUT, "w"))
json.dump(ohlcv_data, open(OHLCV_OUT, "w"))
print(f"DONE: xdxr {len(xdxr_data)} | ohlcv {len(ohlcv_data)} | {(time.time()-t0)/60:.1f}min", flush=True)
