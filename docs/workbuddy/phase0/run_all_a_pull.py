# -*- coding: utf-8 -*-
"""全 A 股票列表 + 月线拉取 (断点续传)
1) stock_all -> 过滤 A 股 (60/68 沪, 00/30 深, 8x 北交所) -> all_a_codes.json
2) 逐只拉月线 offset=160 (覆盖 2013-01~2026-08) -> all_a_monthly.json
"""
import sys
import io
import os
import json
import re
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mootdx.quotes import Quotes

# ---------- 1. 列表 ----------
if os.path.exists("mx_fin_data/all_a_codes.json"):
    CODES = json.load(open("mx_fin_data/all_a_codes.json"))
    print(f"复用列表: {len(CODES)} 只")
else:
    q = Quotes.factory(market="std", timeout=20)
    df = q.stock_all()
    print(f"stock_all: {len(df)} 行")
    # 过滤 A 股: 6位数字 + 前缀规则
    pat = re.compile(r"^(60[0135]|68[89]|00[0-3]|30[01]|83|87|88)\d{3}$")
    codes = []
    for _, r in df.iterrows():
        code = str(r["code"]).zfill(6)
        if pat.match(code):
            codes.append(code)
    CODES = sorted(set(codes))
    json.dump(CODES, open("mx_fin_data/all_a_codes.json", "w"))
    print(f"过滤后 A 股: {len(CODES)} 只")
    # 抽查
    import random
    print("  样例:", random.sample(CODES, 8))

# ---------- 2. 月线 (断点续传) ----------
qc = Quotes.factory(market="std", timeout=20)
OUT = "mx_fin_data/all_a_monthly.json"
data = json.load(open(OUT)) if os.path.exists(OUT) else {}
print(f"已缓存月线: {len(data)} 只")

def pull(code):
    for attempt in range(4):
        try:
            df = qc.bars(symbol=code, frequency=6, start=0, offset=160)
            if df is not None and len(df):
                out = {}
                for _, r in df.iterrows():
                    dt = str(r["datetime"])
                    out[dt[:4] + dt[5:7]] = float(r["close"])
                return out
        except Exception as e:
            if attempt == 3:
                print(f"    ⚠️ {code} 失败: {e}", flush=True)
        time.sleep(1.0)
    return {}

t0 = time.time()
for i, code in enumerate(CODES):
    if code in data and len(data[code]) > 100:
        continue
    m = pull(code)
    if m:
        data[code] = m
    if (i + 1) % 100 == 0 or i == len(CODES) - 1:
        json.dump(data, open(OUT, "w"))
        el = (time.time() - t0) / 60
        print(f"  [{i+1}/{len(CODES)}] 已缓存 {len(data)} 只 | 用时 {el:.1f}min", flush=True)
    time.sleep(0.35)
json.dump(data, open(OUT, "w"))
print(f"DONE: {len(data)} 只月线")
