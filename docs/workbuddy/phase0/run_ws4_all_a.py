# -*- coding: utf-8 -*-
"""T24 全 A 拥挤度重标定 + 熔断回测 (真实 DY, xdxr)
拥挤度 = mean(估值拥挤, 成交占比分位, 放大幅度分位) 滚动36月分位
红利组合 = 全A 中 DY top 1/3 (年报 PIT 5月调仓)
熔断回测基准: 全A 季频核心收益 (all_quarterly_ws2.csv)
"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd

CODES = json.load(open("mx_fin_data/all_a_codes.json"))
ohlcv = json.load(open("mx_fin_data/all_a_ohlcv.json"))
xdxr = json.load(open("mx_fin_data/all_a_xdxr.json"))
YEARS = list(range(2010, 2025))
RF = 0.02
WINDOW = 36
TOP_N = max(30, int(len(CODES) * 0.10))

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# ---------- 因子 (真实 DY, dict 索引) ----------
from mootdx_client import MootdxClient
c = MootdxClient()
pre = {}
for y in YEARS:
    fn = f"mx_fin_data/gpcw{y}1231.csv"
    if not os.path.exists(fn):
        continue
    df = pd.read_csv(fn, index_col=0, dtype=str)
    df.index = df.index.astype(str).str.zfill(6)
    for col in ("np", "ocf", "capex", "shares"):
        s = c._pick(df, col)
        if s is not None:
            df[col] = pd.to_numeric(s, errors="coerce")
    if "ocf" in df.columns and "capex" in df.columns:
        df["fcf"] = df["ocf"] - df["capex"].fillna(0)
    for code, r in df.iterrows():
        pre[(code, str(y))] = r

factor_y = {}
for y in YEARS:
    d = {}
    for code in CODES:
        m = ohlcv.get(code, {}).get(str(y * 100 + 12))
        px = m.get("close") if m else None
        if not px:
            continue
        r = pre.get((code, str(y)))
        if r is None:
            continue
        mcap = px * r["shares"] if r["shares"] and r["shares"] > 0 else np.nan
        d[code] = {"dy": year_dps(code, y) / px,
                   "fcfy": r["fcf"] / mcap if mcap and not np.isnan(r["fcf"]) else np.nan,
                   "cash": (r["ocf"] / r["np"]) if r["np"] and r["np"] > 0 and not np.isnan(r["ocf"]) else np.nan}
    factor_y[y] = d
print("因子面板就绪 (真实DY)", flush=True)

# ---------- 月度序列 ----------
months = sorted({int(k) for cc in ohlcv.values() for k in cc.keys()})
months = [m for m in months if m >= 201106]
print(f"样本期: {months[0]}~{months[-1]} {len(months)} 个月", flush=True)

def dy_universe(m):
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    return factor_y.get(fy, {})

red_members, dy_series, amt_red, amt_all = {}, {}, {}, {}
for m in months:
    d = dy_universe(m)
    sc = {cd: v["dy"] for cd, v in d.items() if v["dy"] is not None and not np.isnan(v["dy"])}
    if len(sc) < 200:
        continue
    n_red = max(1, len(sc) // 3)
    top = sorted(sc, key=sc.get, reverse=True)[:n_red]
    red_members[m] = top
    dy_series[m] = np.mean([sc[x] for x in top])
    a_red = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in top)
    a_all = sum(ohlcv.get(x, {}).get(str(m), {}).get("amount", 0) for x in CODES)
    amt_red[m], amt_all[m] = a_red, a_all

ms = sorted(dy_series.keys())
s_dy = pd.Series({m: dy_series[m] for m in ms})
s_share = pd.Series({m: amt_red[m] / amt_all[m] * 100 for m in ms if amt_all[m]})
s_amp = pd.Series({m: (amt_red[m] / np.mean([amt_red.get(m2, 0) for m2 in ms[max(0, ms.index(m) - 12):ms.index(m)]])) if ms.index(m) >= 12 else np.nan for m in ms})

def pctile(series):
    out = {}
    vals = list(series.index)
    for i, m in enumerate(vals):
        if i < WINDOW - 1:
            out[m] = np.nan
            continue
        win = series.iloc[max(0, i - WINDOW + 1):i + 1].dropna()
        if len(win) < 24 or np.isnan(series.iloc[i]):
            out[m] = np.nan
            continue
        out[m] = (win < series.iloc[i]).mean() * 100
    return pd.Series(out)

p_dy, p_share, p_amp = pctile(s_dy), pctile(s_share), pctile(s_amp)
c_dy = 100 - p_dy
crowd = pd.concat([c_dy, p_share, p_amp], axis=1).mean(axis=1)

crowd_df = pd.DataFrame({"month": crowd.index, "crowd": crowd.values,
                         "估值拥挤(100-DY分位)": c_dy.values, "成交占比分位": p_share.values,
                         "放大幅度分位": p_amp.values})
crowd_df.to_csv("mx_fin_data/ws4_crowding_all_a.csv", index=False, encoding="utf-8-sig")
print("\n=== 全A 拥挤度 (真实DY, 滚动36月分位) ===")
print(crowd_df.dropna().tail(12).round(1).to_string(index=False), flush=True)

# ---------- 熔断回测 (基准: 季频核心收益) ----------
q = pd.read_csv("mx_fin_data/all_quarterly_ws2.csv")
base_map = dict(zip(q["month"].astype(int), q["quarterly_core"]))
base = np.array([base_map.get(m, np.nan) for m in months])
crowd_s = crowd.reindex(months)
dim_max = pd.concat([c_dy, p_share, p_amp], axis=1).max(axis=1).reindex(months)

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

fuse_b = np.array([(0.0 if (cr >= 95 or dm >= 95) else (r * 0.5 if (cr >= 90 or dm >= 90) else r))
                   if not np.isnan(cr) and not np.isnan(dm) else r for r, cr, dm in zip(base, crowd_s.values, dim_max.values)])
fuse_a = np.array([(0.5 * r if cr >= 75 else (0.0 if cr >= 85 else r)) if not np.isnan(cr) else r
                   for r, cr in zip(base, crowd_s.values)])

print("\n=== 全A 熔断回测 (季频核心 Top10%) ===")
for name, r in [("无熔断", base), ("方案A_合成(75/85)", fuse_a), ("方案B_任一维度(90/95)", fuse_b)]:
    p = perf(r)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | Calmar {p['Calmar']:.3f}", flush=True)

dim_trig = (dim_max.dropna() >= 90).sum()
print(f"\n  任一维度>=90 触发: {dim_trig}月 | 合成>=75: {(crowd_s.dropna() >= 75).sum()}月 | >=85: {(crowd_s.dropna() >= 85).sum()}月")
trig_ms = [str(m) for m in dim_max.index if not np.isnan(dim_max[m]) and dim_max[m] >= 90]
print(f"  触发月份: {trig_ms[:25]}{'...' if len(trig_ms) > 25 else ''}")

# 预测力
print("\n=== 预测力: 拥挤度 vs 未来12月红利组合收益 ===")
fwd = {}
for i, m in enumerate(ms):
    if i + 12 >= len(ms):
        break
    members = red_members.get(m, [])
    rr = []
    for j in range(1, 13):
        mm = ms[i + j]
        rs = []
        for x in members:
            cc = ohlcv.get(x, {}).get(str(mm), {}).get("close")
            pp = ohlcv.get(x, {}).get(str(ms[i + j - 1]), {}).get("close")
            if cc and pp:
                rs.append(cc / pp - 1)
        if rs:
            rr.append(np.mean(rs))
    if rr:
        fwd[m] = np.mean(rr) * 12
fwd_s = pd.Series(fwd)
aligned = pd.concat([crowd_s, fwd_s], axis=1, keys=["crowd", "fwd_ret"]).dropna()
if len(aligned) > 10:
    ic = aligned["crowd"].rank().corr(aligned["fwd_ret"].rank())
    print(f"  rankIC = {ic:.4f} (n={len(aligned)})")
    hi = aligned[aligned["crowd"] >= 75]["fwd_ret"].mean()
    lo = aligned[aligned["crowd"] < 75]["fwd_ret"].mean()
    print(f"  拥挤>=75 未来12月红利 {hi*100:.1f}% vs <75 {lo*100:.1f}%")
print("\nDONE")
