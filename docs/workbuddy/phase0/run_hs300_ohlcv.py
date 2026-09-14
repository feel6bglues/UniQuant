# -*- coding: utf-8 -*-
"""补拉 HS300 完整月线 OHLCV (含 amount 成交额), 断点续传
存 mx_fin_data/hs300_ohlcv.json: {code: {ym: {close, amount}}}
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
qc = Quotes.factory(market="std", timeout=20)

OUT = "mx_fin_data/hs300_ohlcv.json"
data = json.load(open(OUT)) if os.path.exists(OUT) else {}
print(f"已缓存: {len(data)} 只")

def pull(code):
    for attempt in range(4):
        try:
            df = qc.bars(symbol=code, frequency=6, start=0, offset=210)
            if df is not None and len(df):
                out = {}
                for _, r in df.iterrows():
                    dt = str(r["datetime"])
                    ym = dt[:4] + dt[5:7]
                    out[ym] = {"close": float(r["close"]),
                               "amount": float(r["amount"]) if r["amount"] else 0.0,
                               "vol": float(r["vol"]) if r["vol"] else 0.0}
                return out
        except Exception as e:
            if attempt == 3:
                print(f"    ⚠️ {code} 失败: {e}", flush=True)
        time.sleep(1.2)
    return {}

for i, code in enumerate(CODES):
    if code in data and len(data[code]) > 100 and any("amount" in v for v in data[code].values()):
        continue
    m = pull(code)
    if m:
        data[code] = m
        if (i + 1) % 25 == 0 or i == len(CODES) - 1:
            json.dump(data, open(OUT, "w"))
            print(f"  [{i+1}/{len(CODES)}] {len(data)} 只", flush=True)
    time.sleep(0.6)
json.dump(data, open(OUT, "w"))
print(f"DONE: {len(data)} 只含 amount")
