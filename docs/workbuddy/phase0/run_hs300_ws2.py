# -*- coding: utf-8 -*-
"""WS2 重测: 沪深300 全成分 (300只) × 核心+卫星
核心: ROE+EP+2×DY真实 (增强版) vs 原版(等权4因子)
卫星: 12-1动量 / 12月低波
选股: Top 10% = 30 只; 组合: 核心50% + 动量25% + 低波25% vs 等权1/3
"""
import sys
import io
import os
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

CODES = json.load(open("mx_fin_data/hs300_codes.json"))
monthly = json.load(open("mx_fin_data/hs300_monthly.json"))
xdxr = json.load(open("mx_fin_data/hs300_xdxr.json"))
idx = json.load(open("mx_fin_data/hs300_index.json"))
YEARS = list(range(2010, 2025))
RF = 0.02
TOP_N = 30   # 300 只的 10%

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# ---------- 载入因子 (15期年报, 本地 zip) ----------
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
panel.index = panel.index.astype(str)

# 因子按年 {code: {roe,ep,fcfy,dy_real,dy_approx}}
factor_y = {}
for y in YEARS:
    d = {}
    for code in CODES:
        px = {int(k): v for k, v in monthly.get(code, {}).items()}.get(y * 100 + 12)
        if not px:
            continue
        r = panel[(panel.index == code) & (panel["period"] == str(y))]
        if not len(r):
            continue
        r = r.iloc[0]
        mcap = px * r["shares"]
        d[code] = {
            "roe": r["roe"], "ep": r["eps"] / px,
            "fcfy": r["fcf"] / mcap if mcap else np.nan,
            "dy_approx": r["np"] * 0.3 / mcap if mcap else np.nan,
            "dy_real": year_dps(code, y) / px if px else np.nan,
            "cash_content": (r.get("ocf", np.nan) / r["np"]) if r["np"] and r["np"] > 0 else np.nan,
        }
    factor_y[y] = d
print("因子面板就绪")

# ---------- 月度收益矩阵 ----------
def build_ret():
    months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
    months = [m for m in months if m >= 201401]
    ret = {}
    for code in CODES:
        px = {int(k): v for k, v in monthly.get(code, {}).items()}
        seq = [px.get(m) for m in months]
        r = [np.nan]
        for i in range(1, len(seq)):
            if seq[i] and seq[i-1]:
                r.append(seq[i] / seq[i-1] - 1)
            else:
                r.append(np.nan)
        ret[code] = r
    return months, pd.DataFrame(ret, index=months)

months, ret_m = build_ret()
print(f"样本期: {months[0]}~{months[-1]} {len(months)} 个月")

# ---------- 打分 ----------
def core_score(code, fy, dy_key="dy_real"):
    f = factor_y.get(fy, {}).get(code)
    if not f:
        return np.nan
    vals = [f.get("roe"), f.get("ep"), f.get("fcfy"), f.get(dy_key)]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return np.nan
    return np.nanmean(vals)

def core_score_boosted(code, fy):
    f = factor_y.get(fy, {}).get(code)
    if not f:
        return np.nan
    vals = [f.get("roe"), f.get("ep"), f.get("dy_real")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return np.nan
    return np.nanmean([f["roe"], f["ep"], 2 * f["dy_real"]])

def core_score_noroe(code, fy):
    """无 ROE 核心: DY + FCFY + 现金含量 (300只实证: ROE 为负因子)"""
    f = factor_y.get(fy, {}).get(code)
    if not f:
        return np.nan
    vals = [f.get("dy_real"), f.get("fcfy"), f.get("cash_content")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return np.nan
    return np.nanmean(vals)

def fy_of(m):
    y = m // 100
    return y - 1 if m % 100 >= 5 else y - 2

def mom_score(code, m):
    ks = sorted({int(k) for k in monthly.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    px = {int(k): v for k, v in monthly[code].items()}
    p12, p1 = px.get(ks[i-13]), px.get(ks[i-2])
    return p1 / p12 - 1 if p12 and p1 else np.nan

def lowvol_score(code, m):
    ks = sorted({int(k) for k in monthly.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    px = {int(k): v for k, v in monthly[code].items()}
    seq = [px.get(k) for k in ks[i-13:i]]
    if any(not p for p in seq):
        return np.nan
    r = [seq[j+1]/seq[j]-1 for j in range(len(seq)-1)]
    return -np.std(r)

def topN_ret(score_fn):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan); continue
        sc = {c: score_fn(c, m) for c in CODES}
        sc = {c: v for c, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < TOP_N:
            out.append(np.nan); continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP_N]
        rs = [ret_m.loc[months[i], c] for c in top if not np.isnan(ret_m.loc[months[i], c])]
        out.append(np.mean(rs) if rs else np.nan)
    return out

core_real = topN_ret(lambda c, m: core_score(c, fy_of(m), "dy_real"))
core_boosted = topN_ret(lambda c, m: core_score_boosted(c, fy_of(m)))
core_noroe = topN_ret(lambda c, m: core_score_noroe(c, fy_of(m)))
mom = topN_ret(mom_score)
lowvol = topN_ret(lowvol_score)

def comb(core_r, w_core=0.5, w_mom=0.25, w_lv=0.25):
    return np.array([w_core*cc + w_mom*m + w_lv*l if not any(np.isnan([cc, m, l])) else np.nan
                     for cc, m, l in zip(core_r, mom, lowvol)])

strategies = {
    "核心_真实DY": core_real,
    "核心_增强DY": core_boosted,
    "核心_无ROE": core_noroe,
    "卫星_动量": mom,
    "卫星_低波": lowvol,
    "组合50/25/25_真实DY": comb(core_real),
    "组合50/25/25_增强DY": comb(core_boosted),
    "组合50/25/25_无ROE": comb(core_noroe),
    "组合等权1/3_无ROE": comb(core_noroe, 1/3, 1/3, 1/3),
    "基准_HS300等权": ret_m[CODES].mean(axis=1).values,
}
# 基准: HS300 指数
idx_ret = []
for i, m in enumerate(months):
    px = {int(k): v for k, v in idx.items()}
    ks = sorted(px.keys())
    try:
        j = ks.index(m)
    except ValueError:
        idx_ret.append(np.nan); continue
    if j == 0:
        idx_ret.append(np.nan)
    else:
        p0, p1 = px[ks[j-1]], px[m]
        idx_ret.append(p1/p0 - 1 if p0 and p1 else np.nan)
strategies["基准_HS300指数"] = np.array(idx_ret)

# ---------- 绩效 ----------
def perf(r):
    r = pd.Series(r).dropna()
    if len(r) < 12: return None
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    ann_ret = nav.iloc[-1] ** (1 / yrs) - 1
    ann_vol = r.std() * np.sqrt(12)
    sharpe = (ann_ret - RF) / ann_vol if ann_vol > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {"年化收益": ann_ret, "年化波动": ann_vol, "夏普": sharpe, "最大回撤": dd,
            "Calmar": ann_ret / abs(dd) if dd < 0 else np.nan, "月数": len(r), "期末净值": nav.iloc[-1]}

mdf = pd.DataFrame({k: v for k, v in {k: perf(v) for k, v in strategies.items()}.items() if v}).T.round(4)
mdf.to_csv("mx_fin_data/hs300_ws2_metrics.csv", encoding="utf-8-sig")
print("\n=== WS2 绩效 (沪深300, Top30, 2014-01~2026-08) ===")
print(mdf.to_string())

corr_df = pd.DataFrame({k: pd.Series(v) for k, v in strategies.items()}).corr()
print("\n=== 核心 vs 卫星 相关性 ===")
print(corr_df.loc[["核心_增强DY", "卫星_动量", "卫星_低波"], ["核心_增强DY", "卫星_动量", "卫星_低波"]].round(3).to_string())
corr_df.round(3).to_csv("mx_fin_data/hs300_ws2_corr.csv", encoding="utf-8-sig")

nav_df = pd.DataFrame({"month": months})
for k, v in strategies.items():
    nav_df[k] = (1 + pd.Series(v)).cumprod().round(4)
nav_df.to_csv("mx_fin_data/hs300_ws2_nav.csv", index=False, encoding="utf-8-sig")
print("DONE")
