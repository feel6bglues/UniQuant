# -*- coding: utf-8 -*-
"""WS2 全 A 重测: 核心_无ROE + 动量 + 低波 (Top 10% ≈ 450 只)
对比: 含ROE核心 / 无ROE核心 / 基准全A等权 / 上证指数
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
RF = 0.02
PCT = 0.10   # Top 10%

def top_n_for(n_univ):
    return max(30, int(n_univ * PCT))

xdxr = json.load(open("mx_fin_data/all_a_xdxr.json")) if os.path.exists("mx_fin_data/all_a_xdxr.json") else {}
print(f"全A xdxr 真实分红: {len(xdxr)} 只")

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

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

# 因子按年
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
        d[code] = {"roe": r["roe"], "ep": r["eps"] / px,
                   "fcfy": r["fcf"] / mcap if mcap else np.nan,
                   "dy": year_dps(code, y) / px,                     # 真实 DY (xdxr)
                   "cash": (r.get("ocf", np.nan) / r["np"]) if r["np"] and r["np"] > 0 else np.nan}
    factor_y[y] = d
print("因子面板就绪")

months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
months = [m for m in months if m >= 201401]
ret_m = {}
for code in CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    seq = [px.get(m) for m in months]
    r = [np.nan]
    for i in range(1, len(seq)):
        r.append(seq[i]/seq[i-1]-1 if seq[i] and seq[i-1] else np.nan)
    ret_m[code] = r
ret_m = pd.DataFrame(ret_m, index=months)
print(f"样本期: {months[0]}~{months[-1]} {len(months)} 个月 | 月度覆盖 {ret_m.notna().sum().mean():.0f} 只/月")

def fy_of(m):
    y = m // 100
    return y - 1 if m % 100 >= 5 else y - 2

def topN_ret(score_fn):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan); continue
        fy = fy_of(m)
        f = factor_y.get(fy, {})
        sc = {cd: score_fn(cd, f.get(cd)) for cd in CODES}
        sc = {cd: v for cd, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < 100:
            out.append(np.nan); continue
        n = top_n_for(len(sc))
        top = sorted(sc, key=sc.get, reverse=True)[:n]
        rs = [ret_m.loc[months[i], x] for x in top if not np.isnan(ret_m.loc[months[i], x])]
        out.append(np.mean(rs) if rs else np.nan)
    return out

def core_noroe(cd, f):
    if not f: return np.nan
    vals = [f.get("dy"), f.get("fcfy"), f.get("cash")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals): return np.nan
    return np.nanmean(vals)

def core_withroe(cd, f):
    if not f: return np.nan
    vals = [f.get("roe"), f.get("dy"), f.get("fcfy")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals): return np.nan
    return np.nanmean(vals)

def mom_score(cd, m):
    px = {int(k): v for k, v in monthly.get(cd, {}).items()}
    ks = sorted(px.keys())
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13: return np.nan
    p12, p1 = px.get(ks[i-13]), px.get(ks[i-2])
    return p1 / p12 - 1 if p12 and p1 else np.nan

def lowvol_score(cd, m):
    px = {int(k): v for k, v in monthly.get(cd, {}).items()}
    ks = sorted(px.keys())
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13: return np.nan
    seq = [px.get(k) for k in ks[i-13:i]]
    if any(not p for p in seq): return np.nan
    r = [seq[j+1]/seq[j]-1 for j in range(len(seq)-1)]
    return -np.std(r)

core_nr = topN_ret(core_noroe)
core_wr = topN_ret(core_withroe)
mom = topN_ret(mom_score)
lowvol = topN_ret(lowvol_score)

def comb(core_r, w1=0.5, w2=0.25, w3=0.25):
    return np.array([w1*c + w2*m + w3*l if not any(np.isnan([c, m, l])) else np.nan
                     for c, m, l in zip(core_r, mom, lowvol)])

strategies = {
    "核心_含ROE": core_wr,
    "核心_无ROE": core_nr,
    "卫星_动量": mom,
    "卫星_低波": lowvol,
    "组合50/25/25_无ROE": comb(core_nr),
    "组合等权1/3_无ROE": comb(core_nr, 1/3, 1/3, 1/3),
    "基准_全A等权": ret_m[CODES].mean(axis=1).values,
}
idx = json.load(open("mx_fin_data/index_monthly.json"))
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
strategies["基准_上证指数"] = np.array(idx_ret)

def perf(r):
    r = pd.Series(r).dropna()
    if len(r) < 12: return None
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    ar = nav.iloc[-1] ** (1 / yrs) - 1
    av = r.std() * np.sqrt(12)
    shp = (ar - RF) / av if av > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {"年化收益": ar, "年化波动": av, "夏普": shp, "最大回撤": dd,
            "Calmar": ar / abs(dd) if dd < 0 else np.nan, "月数": len(r), "期末净值": nav.iloc[-1]}

mdf = pd.DataFrame({k: v for k, v in {k: perf(v) for k, v in strategies.items()}.items() if v}).T.round(4)
mdf.to_csv("mx_fin_data/all_a_ws2_metrics.csv", encoding="utf-8-sig")
print("\n=== WS2 绩效 (全A, Top10%, 2014-01~2026-08) ===")
print(mdf.to_string())

nav_df = pd.DataFrame({"month": months})
for k, v in strategies.items():
    nav_df[k] = (1 + pd.Series(v)).cumprod().round(4)
nav_df.to_csv("mx_fin_data/all_a_ws2_nav.csv", index=False, encoding="utf-8-sig")
print("DONE")
