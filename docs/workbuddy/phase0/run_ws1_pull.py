# -*- coding: utf-8 -*-
"""WS1 数据拉取 (mootdx): 2010-2024 年报因子面板 + 15 只龙头月线 + 上证指数月线
产出: mx_fin_data/factor_panel_ws1.csv, mx_fin_data/monthly_prices.csv, mx_fin_data/index_monthly.csv
"""
import sys
import io
import os
import time
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mootdx_client import MootdxClient
import pandas as pd

BASKET = ["600519", "000858", "601318", "600036", "000333", "002594", "600900",
          "601012", "000001", "600276", "603259", "300750", "600030", "000651", "601888"]
YEARS = list(range(2010, 2025))          # 2010-2024 年报
PERIODS = [f"{y}1231" for y in YEARS]

c = MootdxClient()
os.makedirs("mx_fin_data", exist_ok=True)

# ---------- 1. 财报面板 ----------
print("=== [1/3] 下载 2010-2024 年报 ({n} 期) ===".format(n=len(PERIODS)))
panel_frames = []
for i, p in enumerate(PERIODS):
    fn = f"gpcw{p}.zip"
    print(f"  [{i+1}/{len(PERIODS)}] {fn} ...", flush=True)
    df = c.fetch_report(fn)
    if len(df):
        print(f"    OK {df.shape[0]} 只")
        snap = c.factor_snapshot(df)   # 先不加价格, ep/dy 后续用月线补
        snap["period"] = p
        panel_frames.append(snap)
    else:
        print(f"    ⚠️ 空")
    time.sleep(1.0)   # 财报服务器节流

if panel_frames:
    panel = pd.concat(panel_frames)
    panel = panel[panel.index.isin(BASKET)]
    panel.to_csv("mx_fin_data/factor_panel_ws1.csv", encoding="utf-8-sig")
    print(f"面板已存: {panel.shape} (15只 x {len(PERIODS)}期)")

# ---------- 2. 月线收盘价 ----------
print("\n=== [2/3] 拉 15 只龙头月线 (2010→今) ===")
monthly = {}
for i, code in enumerate(BASKET):
    m = c.monthly_closes(code, start=0, offset=210)   # 210 个月 ≈ 17.5 年
    monthly[code] = m
    print(f"  [{i+1}/{len(BASKET)}] {code}: {len(m)} 个月点", flush=True)
    time.sleep(1.0)
with open("mx_fin_data/monthly_prices.json", "w") as f:
    json.dump(monthly, f)
print("月线已存 mx_fin_data/monthly_prices.json")

# ---------- 3. 上证指数月线 (牛熊基准) ----------
print("\n=== [3/3] 上证指数月线 ===")
try:
    idx = c.quotes().index_bars(symbol="000001", frequency=6, start=0, offset=210)
    if idx is not None and len(idx):
        idx_map = {}
        for _, r in idx.iterrows():
            ym = str(r["datetime"])[:4] + str(r["datetime"])[5:7]
            ym = ym.replace("-", "")
            idx_map[int(ym[:6])] = float(r["close"])
        with open("mx_fin_data/index_monthly.json", "w") as f:
            json.dump(idx_map, f)
        print(f"上证指数月线已存: {len(idx_map)} 个月点")
    else:
        print("⚠️ 指数返回空")
except Exception as e:
    print("⚠️ 指数拉取失败:", repr(e))

print("\nDONE")
