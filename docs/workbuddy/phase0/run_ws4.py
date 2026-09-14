# -*- coding: utf-8 -*-
"""WS4 拥挤度信号工程化 + v2 §9.5 熔断开关回测
拥挤度指数 = mean(估值分位, 成交占比分位, 成交放大幅度)  (各指标滚动36月分位 0-100)
- 估值分位: 红利组合(HS300 中 DY top1/3) 加权 DY 的 36月分位 取反 (DY低=贵=拥挤)
- 成交占比: 红利组合月成交额 / HS300 总成交额 的 36月分位
- 放大幅度: 红利组合月成交额 / 前12月均值 的 36月分位
熔断: 拥挤度>=90 -> 核心仓位50%; >=95 -> 核心仓位0 (全部低波/现金)
对比: 无熔断 vs 有熔断 (组合 = 核心_无ROE 50% + 动量25% + 低波25%)
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
WINDOW = 36   # 滚动分位窗口(月)

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# ---------- 因子 (DY 真实) ----------
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

# ---------- 月度序列 ----------
months = sorted({int(k) for cc in ohlcv.values() for k in cc.keys()})
months = [m for m in months if m >= 201106]   # 需要 36 个月窗口
print(f"样本期: {months[0]}~{months[-1]} {len(months)} 个月")

# 每月红利组合 (DY top 1/3): 年报 PIT (5月调仓)
def dy_universe(m):
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    return factor_y.get(fy, {})

red_members = {}   # {month: [codes]} 红利组合
dy_series = {}
amt_red, amt_all = {}, {}
for m in months:
    d = dy_universe(m)
    sc = {cd: v["dy"] for cd, v in d.items() if v["dy"] is not None and not np.isnan(v["dy"])}
    if len(sc) < 60:
        continue
    n_red = max(1, len(sc) // 3)
    top = sorted(sc, key=sc.get, reverse=True)[:n_red]
    red_members[m] = top
    # 加权 DY (按 mcap 简单加权 -> 用平均)
    dy_series[m] = np.mean([sc[x] for x in top])
    # 成交额
    a_red = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in top)
    a_all = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in CODES)
    amt_red[m] = a_red
    amt_all[m] = a_all

ms = sorted(dy_series.keys())
s_dy = pd.Series({m: dy_series[m] for m in ms})
s_share = pd.Series({m: (amt_red[m] / amt_all[m] * 100) for m in ms if amt_all[m]})
s_amp = pd.Series({m: (amt_red[m] / np.mean([amt_red.get(m2, 0) for m2 in ms[max(0, ms.index(m)-12):ms.index(m)]])) if ms.index(m) >= 12 else np.nan for m in ms})

# ---------- 滚动 36 月分位 ----------
def pctile(series):
    out = {}
    vals = list(series.index)
    for i, m in enumerate(vals):
        if i < WINDOW - 1:
            out[m] = np.nan
            continue
        win = series.iloc[max(0, i-WINDOW+1):i+1].dropna()
        if len(win) < 24 or np.isnan(series.iloc[i]):
            out[m] = np.nan
            continue
        out[m] = (win < series.iloc[i]).mean() * 100
    return pd.Series(out)

p_dy = pctile(s_dy)
p_share = pctile(s_share)
p_amp = pctile(s_amp)
# 估值分位取反: DY 低 = 贵 = 拥挤
c_dy = 100 - p_dy
crowd = pd.concat([c_dy, p_share, p_amp], axis=1).mean(axis=1)

crowd_df = pd.DataFrame({
    "month": crowd.index, "crowd": crowd.values,
    "估值拥挤(100-DY分位)": c_dy.values, "成交占比分位": p_share.values,
    "放大幅度分位": p_amp.values,
})
crowd_df.to_csv("mx_fin_data/ws4_crowding.csv", index=False, encoding="utf-8-sig")
print("\n=== 拥挤度指数 (滚动36月分位合成) ===")
print(crowd_df.dropna().tail(15).round(1).to_string(index=False))

# ---------- 熔断回测 ----------
# 核心_无ROE + 动量 + 低波 (复用 HS300 WS2 逻辑)
def score_ret(score_fn):
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

core_noroe = score_ret(lambda v: np.nanmean([v["dy"], v["fcfy"], v["cash"]]))

def mom_score(code, m):
    ks = sorted({int(k) for k in ohlcv.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    c12 = ohlcv[code].get(str(ks[i-13]), {}).get("close")
    c1 = ohlcv[code].get(str(ks[i-2]), {}).get("close")
    return c1 / c12 - 1 if c12 and c1 else np.nan

def lowvol_score(code, m):
    ks = sorted({int(k) for k in ohlcv.get(code, {}).keys()})
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    seq = [ohlcv[code].get(str(k), {}).get("close") for k in ks[i-13:i]]
    if any(not p for p in seq):
        return np.nan
    r = [seq[j+1]/seq[j]-1 for j in range(len(seq)-1)]
    return -np.std(r)

mom = score_ret(lambda v: None)  # 占位, 下面直接算
# 动量/低波用 topN_ret 逻辑 (score_fn 传 code, month)
def topN(score_fn):
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

mom_r = topN(mom_score)
lowvol_r = topN(lowvol_score)

# 组合: 无熔断 (核心50+动量25+低波25)
base = np.array([0.5*c + 0.25*m + 0.25*l if not any(np.isnan([c, m, l])) else np.nan
                 for c, m, l in zip(core_noroe, mom_r, lowvol_r)])

# 有熔断: 拥挤度>=90 -> 核心仓位0.5; >=95 -> 核心仓位0
crowd_s = crowd.reindex(months)
# 方案B: 任一维度极端即触发 (估值拥挤>=90 OR 成交占比>=90 OR 放大幅度>=90 -> 减半; >=95 -> 清仓)
dim_max = pd.concat([c_dy, p_share, p_amp], axis=1).max(axis=1).reindex(months)

def fuse(r, cr, dm):
    if np.isnan(cr) or np.isnan(r):
        return r
    if cr >= 95 or dm >= 95:
        return 0.0
    if cr >= 90 or dm >= 90:
        return r * 0.5
    return r
fused = np.array([fuse(r, crowd_s.iloc[i], dim_max.iloc[i]) if i < len(crowd_s) else r for i, r in enumerate(base)])

# 方案A: 合成>=75 减半, >=85 清仓 (较敏感)
fused_a = np.array([(0.5*r if cr >= 75 else (0.0 if cr >= 85 else r)) if not np.isnan(cr) else r
                    for r, cr in zip(base, crowd_s.values)])

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
            "Calmar": ar / abs(dd) if dd < 0 else np.nan, "期末净值": nav.iloc[-1]}

print("\n=== 熔断开关回测对比 ===")
for name, r in [("无熔断", base), ("方案B_任一维度(90/95)", fused), ("方案A_合成(75/85)", fused_a)]:
    p = perf(r)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | Calmar {p['Calmar']:.3f}")

# 熔断触发统计
trig90 = (crowd_s.dropna() >= 90).sum()
trig95 = (crowd_s.dropna() >= 95).sum()
dim_trig90 = (dim_max.dropna() >= 90).sum()
dim_trig95 = (dim_max.dropna() >= 95).sum()
print(f"\n  合成拥挤>=90: {trig90}月 | >=95: {trig95}月 | 有效月 {len(crowd_s.dropna())}")
print(f"  任一维度>=90: {dim_trig90}月 | >=95: {dim_trig95}月")
# 触发时间点
trig_months = [str(m) for m in dim_max.index if not np.isnan(dim_max[m]) and dim_max[m] >= 90]
print(f"  任一维度>=90 触发月份: {trig_months[:20]}{'...' if len(trig_months)>20 else ''}")

# 预测力: 拥挤度 vs 未来12月红利组合超额
print("\n=== 拥挤度预测力 (拥挤度 vs 未来12月红利组合收益) ===")
ret_red = pd.Series({m: (s_dy.get(m, np.nan)) for m in ms})  # 占位
fwd = {}
for i, m in enumerate(ms):
    if i + 12 >= len(ms):
        break
    # 红利组合未来12月平均月收益
    members = red_members.get(m, [])
    rr = []
    for j in range(1, 13):
        mm = ms[i+j]
        rs = []
        for x in members:
            cc = ohlcv.get(x, {}).get(str(mm), {}).get("close")
            pp = ohlcv.get(x, {}).get(str(ms[i+j-1]), {}).get("close")
            if cc and pp:
                rs.append(cc / pp - 1)
        if rs:
            rr.append(np.mean(rs))
    if rr:
        fwd[m] = np.mean(rr) * 12   # 年化
fwd_s = pd.Series(fwd)
aligned = pd.concat([crowd_s, fwd_s], axis=1, keys=["crowd", "fwd_ret"]).dropna()
if len(aligned) > 10:
    ic = aligned["crowd"].rank().corr(aligned["fwd_ret"].rank())
    print(f"  拥挤度 vs 未来12月红利组合收益 rankIC = {ic:.4f} (n={len(aligned)})")
    hi = aligned[aligned["crowd"] >= 90]["fwd_ret"].mean()
    lo = aligned[aligned["crowd"] < 90]["fwd_ret"].mean()
    print(f"  拥挤>=90 未来12月红利收益 {hi*100:.1f}% vs 拥挤<90 {lo*100:.1f}%")

print("\nDONE")
