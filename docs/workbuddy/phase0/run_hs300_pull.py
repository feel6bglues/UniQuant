# -*- coding: utf-8 -*-
"""沪深300 全成分数据拉取 (断点续传):
1) 300 只月线 (2010-2026, offset=210) -> hs300_monthly.json
2) 300 只 xdxr 真实分红 -> hs300_xdxr.json
3) 沪深300 指数月线 -> hs300_index.json
"""
import sys
import io
import os
import json
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mootdx.quotes import Quotes

CODES = json.load(open("mx_fin_data/hs300_codes.json"))
print(f"成分股: {len(CODES)} 只")

qc = Quotes.factory(market="std", timeout=20)

# ---------- 1. 月线 (断点续传) ----------
monthly_file = "mx_fin_data/hs300_monthly.json"
monthly = json.load(open(monthly_file)) if os.path.exists(monthly_file) else {}
print(f"已缓存月线: {len(monthly)} 只")

def pull_monthly(code):
    for attempt in range(4):
        try:
            df = qc.bars(symbol=code, frequency=6, start=0, offset=210)
            if df is not None and len(df):
                out = {}
                for _, r in df.iterrows():
                    dt = str(r["datetime"])
                    ym = dt[:4] + dt[5:7]
                    out[ym] = float(r["close"])
                return out
        except Exception as e:
            if attempt == 3:
                print(f"    ⚠️ {code} 月线最终失败: {e}", flush=True)
        time.sleep(1.2)
    return {}

for i, code in enumerate(CODES):
    if code in monthly and len(monthly[code]) > 100:
        continue
    m = pull_monthly(code)
    if m:
        monthly[code] = m
        if (i + 1) % 25 == 0 or i == len(CODES) - 1:
            json.dump(monthly, open(monthly_file, "w"))
            print(f"  [{i+1}/{len(CODES)}] 月线进度 {len(monthly)} 只", flush=True)
    time.sleep(0.6)
json.dump(monthly, open(monthly_file, "w"))
print(f"月线完成: {len(monthly)} 只")

# ---------- 2. xdxr 真实分红 (断点续传) ----------
xdxr_file = "mx_fin_data/hs300_xdxr.json"
div = json.load(open(xdxr_file)) if os.path.exists(xdxr_file) else {}
print(f"已缓存 xdxr: {len(div)} 只")

for i, code in enumerate(CODES):
    if code in div:
        continue
    try:
        df = qc.xdxr(symbol=code)
        recs = []
        if df is not None and len(df):
            for _, r in df.iterrows():
                if r["category"] == 1 and r["fenhong"] and r["fenhong"] > 0:
                    recs.append({"year": int(r["year"]), "dps": float(r["fenhong"]) / 10.0})
        div[code] = recs
        if (i + 1) % 25 == 0 or i == len(CODES) - 1:
            json.dump(div, open(xdxr_file, "w"))
            print(f"  [{i+1}/{len(CODES)}] xdxr 进度 {len(div)} 只", flush=True)
    except Exception as e:
        print(f"  ⚠️ {code} xdxr失败: {e}", flush=True)
    time.sleep(0.5)
json.dump(div, open(xdxr_file, "w"))
print(f"xdxr 完成: {len(div)} 只")

# ---------- 3. 沪深300 指数月线 ----------
try:
    df = qc.index_bars(symbol="000300", frequency=6, start=0, offset=210)
    idx = {}
    if df is not None and len(df):
        for _, r in df.iterrows():
            dt = str(r["datetime"])
            idx[dt[:4] + dt[5:7]] = float(r["close"])
    json.dump(idx, open("mx_fin_data/hs300_index.json", "w"))
    print(f"沪深300指数月线: {len(idx)} 点")
except Exception as e:
    print(f"⚠️ 指数失败: {e}")

print("DONE")
