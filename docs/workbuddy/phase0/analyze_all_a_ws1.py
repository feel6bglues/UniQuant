# -*- coding: utf-8 -*-
"""WS1 全 A 重测: 全 A 截面 × 2010-2024 年报 -> 次年收益
IC/IR + 牛熊拆分 + 2024-02 压力 (读 all_a_monthly.json, 财报 gpcw 缓存)
"""
import sys
import io
import os
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

CODES = json.load(open("mx_fin_data/all_a_codes.json"))
monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
YEARS = list(range(2010, 2025))

print(f"全A列表: {len(CODES)} 只 | 月线缓存: {len(monthly)} 只")

# ---------- 载入 15 期年报因子 ----------
from mootdx_client import MootdxClient
c = MootdxClient()
panel_frames = []
for y in YEARS:
    df = c.fetch_report(f"gpcw{y}1231.zip")
    if len(df):
        snap = c.factor_snapshot(df)
        snap["period"] = str(y)
        panel_frames.append(snap)
panel = pd.concat(panel_frames)
panel.index = panel.index.astype(str).str.zfill(6)   # CSV 往返丢前导零
print(f"财报面板: {panel.shape}")

# ---------- 构建年度样本 (dict 索引加速) ----------
pre = {}
for code, g in panel.groupby(level=0):
    for _, r in g.iterrows():
        pre[(code, str(r["period"]))] = r

rows = []
for code in CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    for y in YEARS:
        p_end = px.get(y * 100 + 12)
        p_next = px.get((y + 1) * 100 + 12)
        if not p_end or not p_next:
            continue
        r = pre.get((code, str(y)))
        if r is None:
            continue
        mcap = p_end * r["shares"]
        rows.append({
            "code": code, "year": y,
            "roe": r["roe"],
            "ep": r["eps"] / p_end,
            "fcfy": r["fcf"] / mcap if mcap else np.nan,
            "np_gr": r.get("np_gr", np.nan),
            "cash_content": (r.get("ocf", np.nan) / r["np"]) if r["np"] and r["np"] > 0 else np.nan,
            "ret_next": p_next / p_end - 1,
        })
df = pd.DataFrame(rows)
print(f"年度样本: {len(df)} ({df['code'].nunique()} 只 x {df['year'].nunique()} 年)")
print("因子覆盖:")
print(df[["roe", "ep", "fcfy", "np_gr", "cash_content"]].notna().mean().round(3).to_string())

# ---------- IC/IR ----------
factors = {"ROE": "roe", "EP": "ep", "FCF_Yield": "fcfy", "SUE(np_gr)": "np_gr", "现金含量": "cash_content"}

def rank_ic(col, y):
    sub = df[df["year"] == y][["code", col, "ret_next"]].dropna()
    if len(sub) < 50:
        return np.nan
    return sub[col].rank().corr(sub["ret_next"].rank())

ic_rows = []
for y in sorted(df["year"].unique()):
    ic_rows.append({"year": y, **{k: rank_ic(v, y) for k, v in factors.items()}})
ic_df = pd.DataFrame(ic_rows).set_index("year")
ic_df.to_csv("mx_fin_data/all_a_ic_matrix.csv", encoding="utf-8-sig")
print("\n=== 逐期 rank IC (全A) ===")
print(ic_df.round(3).to_string())

summ = []
for label, col in factors.items():
    ics = ic_df[label].dropna()
    if len(ics) >= 10:
        summ.append({"因子": label, "meanIC": round(ics.mean(), 4), "IC_std": round(ics.std(), 4),
                     "IR": round(ics.mean() / ics.std(), 3), "n": len(ics)})
summ_df = pd.DataFrame(summ)
print("\n=== IC 汇总 (全A) ===")
print(summ_df.to_string(index=False))
summ_df.to_csv("mx_fin_data/all_a_ic_summary.csv", index=False, encoding="utf-8-sig")

# ---------- 牛熊拆分 (上证指数) ----------
idx = json.load(open("mx_fin_data/index_monthly.json"))
idx_y = {}
for ym, v in idx.items():
    if int(str(ym)[4:6]) == 12:
        idx_y[int(str(ym)[:4])] = v
regime = {}
for y in sorted(df["year"].unique()):
    r = idx_y.get(y + 1) / idx_y.get(y) - 1 if idx_y.get(y) and idx_y.get(y + 1) else np.nan
    regime[y] = "牛" if r > 0.05 else ("熊" if r < -0.05 else "震荡")

regime_sum = []
for label, col in factors.items():
    for rg in ["牛", "熊", "震荡"]:
        yrs = [y for y, v in regime.items() if v == rg]
        ics = [rank_ic(col, y) for y in yrs]
        ics = [x for x in ics if not np.isnan(x)]
        if ics:
            regime_sum.append({"因子": label, "regime": rg, "meanIC": round(np.mean(ics), 4), "n": len(ics)})
rdf = pd.DataFrame(regime_sum)
print("\n=== 牛熊拆分 (全A) ===")
print(rdf.pivot(index="因子", columns="regime", values="meanIC").round(4).to_string())
rdf.to_csv("mx_fin_data/all_a_ic_regime.csv", index=False, encoding="utf-8-sig")

# ---------- 2024-02 压力 ----------
print("\n=== 2024-02 压力测试 (全A) ===")
stress = []
for code in CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    p_jan, p_feb = px.get(202401), px.get(202402)
    if not p_jan or not p_feb:
        continue
    r = df[(df["code"] == code) & (df["year"] == 2023)]
    if len(r):
        stress.append({"code": code, "ret": p_feb / p_jan - 1, "roe": r.iloc[0]["roe"]})
sdf = pd.DataFrame(stress)
print(f"样本: {len(sdf)} 只 | 平均收益: {sdf['ret'].mean()*100:.2f}%")
ic = sdf["roe"].rank().corr(sdf["ret"].rank())
print(f"  ROE rankIC(2024-02) = {ic:.4f}")
med = sdf["roe"].median()
print(f"  高ROE组 {sdf[sdf['roe']>med]['ret'].mean()*100:.2f}% vs 低ROE组 {sdf[sdf['roe']<=med]['ret'].mean()*100:.2f}%")
sdf.to_csv("mx_fin_data/all_a_stress_202402.csv", index=False, encoding="utf-8-sig")

df.to_csv("mx_fin_data/all_a_annual_panel.csv", encoding="utf-8-sig")
print("\nDONE")
