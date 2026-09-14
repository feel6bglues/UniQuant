# -*- coding: utf-8 -*-
"""任务#19: WS4 拥挤度熔断接入 WS2 组合 — 动态降权
组合: 核心_无ROE(DY+FCFY+现金含量 Top30) 50% + 动量 25% + 低波 25%
动态规则: 拥挤度(任一维度)>=90 -> 核心权重 50%->25% (多余给低波); >=95 -> 核心清仓(全低波)
对比: 静态组合 vs 动态降权 (夏普/回撤/Calmar)
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
ohlcv = json.load(open("mx_fin_data/hs300_ohlcv.json"))
xdxr = json.load(open("mx_fin_data/hs300_xdxr.json"))
YEARS = list(range(2010, 2025))
RF = 0.02
TOP_N = 30
WINDOW = 36

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

factor_y = {}
for y in YEARS:
    d = {}
    for code in CODES:
        px = {int(k): v for k, v in ohlcv.get(code, {}).items()}.get(y * 100 + 12, {}).get("close")
        if not px:
            continue
        r = panel[(panel.index == code) & (panel["period"] == str(y))]
        if not len(r):
            continue
        r = r.iloc[0]
        mcap = px * r["shares"]
        d[code] = {"dy": year_dps(code, y) / px if px else np.nan,
                   "fcfy": r["fcf"] / mcap if mcap else np.nan,
                   "cash": (r.get("ocf", np.nan) / r["np"]) if r["np"] and r["np"] > 0 else np.nan}
    factor_y[y] = d

months = sorted({int(k) for cc in ohlcv.values() for k in cc.keys()})
months = [m for m in months if m >= 201401]
print(f"样本期: {months[0]}~{months[-1]} {len(months)} 个月")

# ---------- 拥挤度 (复用 WS4) ----------
def dy_universe(m):
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    return factor_y.get(fy, {})

red_members, dy_series, amt_red, amt_all = {}, {}, {}, {}
for m in months:
    d = dy_universe(m)
    sc = {cd: v["dy"] for cd, v in d.items() if v["dy"] is not None and not np.isnan(v["dy"])}
    if len(sc) < 60:
        continue
    n_red = max(1, len(sc) // 3)
    top = sorted(sc, key=sc.get, reverse=True)[:n_red]
    red_members[m] = top
    dy_series[m] = np.mean([sc[x] for x in top])
    amt_red[m] = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in top)
    amt_all[m] = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in CODES)

ms = sorted(dy_series.keys())
s_dy = pd.Series({m: dy_series[m] for m in ms})
s_share = pd.Series({m: (amt_red[m] / amt_all[m] * 100) for m in ms if amt_all[m]})
s_amp = pd.Series({m: (amt_red[m] / np.mean([amt_red.get(m2, 0) for m2 in ms[max(0, ms.index(m)-12):ms.index(m)]])) if ms.index(m) >= 12 else np.nan for m in ms})

def pctile(series):
    out = {}
    vals = list(series.index)
    for i, m in enumerate(vals):
        if i < WINDOW - 1:
            out[m] = np.nan; continue
        win = series.iloc[max(0, i-WINDOW+1):i+1].dropna()
        if len(win) < 24 or np.isnan(series.iloc[i]):
            out[m] = np.nan; continue
        out[m] = (win < series.iloc[i]).mean() * 100
    return pd.Series(out)

c_dy = 100 - pctile(s_dy)
p_share = pctile(s_share)
p_amp = pctile(s_amp)
dim_max = pd.concat([c_dy, p_share, p_amp], axis=1).max(axis=1).reindex(months)
crowd = pd.concat([c_dy, p_share, p_amp], axis=1).mean(axis=1).reindex(months)

# ---------- 组合策略收益 (Top30) ----------
def topN_ret(score_fn):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan); continue
        fy = m // 100 - 1 if m % 100 >= 5 else m // 100 - 2
        f = factor_y.get(fy, {})
        sc = {cd: score_fn(v) for cd, v in f.items() if v is not None}
        sc = {cd: v for cd, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < TOP_N:
            out.append(np.nan); continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP_N]
        rs = []
        for x in top:
            cc = ohlcv.get(x, {}).get(str(months[i]), {}).get("close")
            pp = ohlcv.get(x, {}).get(str(months[i-1]), {}).get("close")
            if cc and pp:
                rs.append(cc / pp - 1)
        out.append(np.mean(rs) if rs else np.nan)
    return out

def mom_score(code, m):
    ks = sorted({int(k) for k in ohlcv.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13: return np.nan
    c12 = ohlcv[code].get(str(ks[i-13]), {}).get("close")
    c1 = ohlcv[code].get(str(ks[i-2]), {}).get("close")
    return c1 / c12 - 1 if c12 and c1 else np.nan

def lowvol_score(code, m):
    ks = sorted({int(k) for k in ohlcv.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13: return np.nan
    seq = [ohlcv[code].get(str(k), {}).get("close") for k in ks[i-13:i]]
    if any(not p for p in seq): return np.nan
    r = [seq[j+1]/seq[j]-1 for j in range(len(seq)-1)]
    return -np.std(r)

def topN_price(score_fn):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan); continue
        sc = {cd: score_fn(cd, m) for cd in CODES}
        sc = {cd: v for cd, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < TOP_N:
            out.append(np.nan); continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP_N]
        rs = []
        for x in top:
            cc = ohlcv.get(x, {}).get(str(months[i]), {}).get("close")
            pp = ohlcv.get(x, {}).get(str(months[i-1]), {}).get("close")
            if cc and pp:
                rs.append(cc / pp - 1)
        out.append(np.mean(rs) if rs else np.nan)
    return out

core_nr = topN_ret(lambda v: np.nanmean([v["dy"], v["fcfy"], v["cash"]]))
mom_r = topN_price(mom_score)
lowvol_r = topN_price(lowvol_score)

# 静态组合
base = np.array([0.5*c + 0.25*m + 0.25*l if not any(np.isnan([c, m, l])) else np.nan
                 for c, m, l in zip(core_nr, mom_r, lowvol_r)])

# 动态降权: 任一维度>=90 -> 核心50%->25%, 低波25%->50%; >=95 -> 核心0, 低波75%
dim_s = dim_max.reindex(months).values
crowd_s = crowd.reindex(months).values
dyn = []
for i, r in enumerate(base):
    if np.isnan(r):
        dyn.append(np.nan); continue
    dm = dim_s[i]
    if np.isnan(dm) or dm < 90:
        dyn.append(r)
    elif dm >= 95:
        # 核心清仓 -> 动量25 + 低波75
        dyn.append(0.25*mom_r[i] + 0.75*lowvol_r[i] if not np.isnan(mom_r[i]) and not np.isnan(lowvol_r[i]) else np.nan)
    else:
        # 核心减半 -> 核心25 + 动量25 + 低波50
        dyn.append(0.25*core_nr[i] + 0.25*mom_r[i] + 0.5*lowvol_r[i] if not any(np.isnan([core_nr[i], mom_r[i], lowvol_r[i]])) else np.nan)
dyn = np.array(dyn)

# 低波基准 (全部低波)
all_lv = np.array([l if not np.isnan(l) else np.nan for l in lowvol_r])

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

print("\n=== 熔断接入组合对比 (沪深300, Top30, 2014-01~2026-08) ===")
for name, r in [("静态组合(无熔断)", base), ("动态降权(熔断接入)", dyn), ("低波基准(全低波)", all_lv)]:
    p = perf(r)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | Calmar {p['Calmar']:.3f}")

trig90 = int((dim_s >= 90).sum())
trig95 = int((dim_s >= 95).sum())
print(f"\n  熔断触发: >=90 共 {trig90} 个月 | >=95 共 {trig95} 个月")

nav_df = pd.DataFrame({"month": months, "static": (1 + pd.Series(base)).cumprod().values,
                       "dynamic": (1 + pd.Series(dyn)).cumprod().values,
                       "dim_max": dim_s})
nav_df.to_csv("mx_fin_data/ws4_ws2_integration_nav.csv", index=False, encoding="utf-8-sig")
print("净值已存 ws4_ws2_integration_nav.csv")
print("DONE")
