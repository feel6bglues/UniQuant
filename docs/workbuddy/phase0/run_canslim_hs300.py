# -*- coding: utf-8 -*-
"""T25 CANSLIM 卫星策略 (HS300 口径, 月频 Top30)
因子 (PIT, 5月调仓用上年报; C 因子季报就绪后自动启用):
  C = 当季 EPS 同比 (依赖 gpcw 季报, 缺失时跳过)
  A = 年报净利润同比增速 (np_gr)
  N = 12月新高强度: 当月收盘 / 过去12月最高价
  S = 供给: -log(总股本) (HS300 内偏小盘)
  L = 相对强度: 个股12月动量 - HS300 12月动量
合成: 各因子截面分位等权 -> Top30, 与核心/动量/低波正交性检验
"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd

CODES = json.load(open("mx_fin_data/hs300_codes.json"))
monthly = json.load(open("mx_fin_data/hs300_monthly.json"))
xdxr = json.load(open("mx_fin_data/hs300_xdxr.json"))
idx = json.load(open("mx_fin_data/hs300_index.json"))
from mootdx_client import MootdxClient
c = MootdxClient()

# ---------- 财报面板 (年报) ----------
panel_frames = []
for y in range(2010, 2025):
    df = c.fetch_report(f"gpcw{y}1231.zip")
    if len(df):
        snap = c.factor_snapshot(df)
        snap["period"] = str(y)
        panel_frames.append(snap)
panel = pd.concat(panel_frames)
panel.index = panel.index.astype(str).str.zfill(6)
# dict 索引加速 (全A规模性能教训: 禁止逐行布尔过滤)
pre = {}
for code, r in panel.iterrows():
    pre[(code, r["period"])] = r

# ---------- 季报面板 (C 因子, 若已缓存) ----------
q_avail = {}
if os.path.exists("mx_fin_data/gpcw20240930.csv"):
    print("[C因子] 季报缓存就绪, 启用 C = 当季EPS同比", flush=True)
    qframes = []
    for y in range(2011, 2025):
        for q in ("0331", "0630", "0930"):
            fn = f"gpcw{y}{q}.csv"
            if os.path.exists(f"mx_fin_data/{fn}"):
                qf = pd.read_csv(f"mx_fin_data/{fn}", index_col=0, dtype=str)
                qf.index = qf.index.astype(str).str.zfill(6)
                eps_s = pd.to_numeric(c._pick(qf, "eps"), errors="coerce") if "eps" in qf.columns else pd.Series(np.nan, index=qf.index)
                qframes.append(pd.DataFrame({"eps": eps_s, "q": f"{y}{q}"}, index=qf.index))
    qpanel = pd.concat(qframes)
    qpanel = qpanel.rename_axis("code").reset_index()
    # 当季 vs 上年同期
    qprev = qpanel[["code", "q", "eps"]].copy()
    qprev["q"] = qprev["q"].map(lambda s: f"{int(s[:4])-1}{s[4:]}")
    qprev.columns = ["code", "q", "eps_p"]
    qj = qpanel.merge(qprev, on=["code", "q"], how="left")
    qj["eps_gr"] = qj["eps"] / qj["eps_p"].replace(0, np.nan) - 1
    q_eps_gr = qj.set_index("code")["eps_gr"]

# ---------- 收益矩阵 ----------
months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
months = [m for m in months if m >= 201401]
ret_m = {}
for code in CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    seq = [px.get(m) for m in months]
    r = [np.nan]
    for i in range(1, len(seq)):
        r.append(seq[i] / seq[i - 1] - 1 if seq[i] and seq[i - 1] else np.nan)
    ret_m[code] = r
ret_m = pd.DataFrame(ret_m, index=months)

# HS300 指数收益
idx_px = {int(k): v for k, v in idx.items()}
idx_seq = [idx_px.get(m) for m in months]
idx_ret = pd.Series([np.nan] + [idx_seq[i] / idx_seq[i - 1] - 1 for i in range(1, len(idx_seq)) if idx_seq[i] and idx_seq[i - 1]], index=months)

def fy_of(m):
    y = m // 100
    return y - 1 if m % 100 >= 5 else y - 2

# ---------- CANSLIM 因子 (逐月, 截面) ----------
def canslim_score(code, m, factor_cache):
    """返回 0-1 合成分。factor_cache[m][code] = {A,N,S,L,(C)}"""
    f = factor_cache.get(m, {}).get(code)
    if not f:
        return np.nan
    ks = [k for k in ("C", "A", "N", "S", "L") if k in f and not np.isnan(f[k])]
    if not ks:
        return np.nan
    return np.mean([f[k] for k in ks])

factor_cache = {}
px_all = {code: {int(k): v for k, v in monthly.get(code, {}).items()} for code in CODES}
for i, m in enumerate(months):
    fy = fy_of(m)
    prev_m = months[i - 1] if i > 0 else None
    d = {}
    for code in CODES:
        px = px_all[code]
        p_use = px.get(prev_m) if prev_m else None   # 上月末价格: 调仓基准, 不含当月(防未来函数)
        if not p_use:
            continue
        r = pre.get((code, str(fy)))
        if r is None:
            continue
        # A: 年报净利增速
        a = r.get("np_gr", np.nan)
        # N: 12月新高强度 (到上月末为止, 不含当月)
        p12 = [px.get(prev_m - k) for k in range(0, 12)]
        p12 = [x for x in p12 if x]
        n = p_use / max(p12) if p12 else np.nan
        # S: 供给 (总股本, 相对小盘)
        s = -np.log(r["shares"]) if r["shares"] and r["shares"] > 0 else np.nan
        # L: 相对强度 (12月动量 - 指数12月动量, 均截至上月末)
        p_prev = px.get(prev_m - 12)
        mom = p_use / p_prev - 1 if p_prev else np.nan
        idx_now, idx_prev = idx_px.get(prev_m), idx_px.get(prev_m - 12)
        idx_mom = idx_now / idx_prev - 1 if idx_now and idx_prev else np.nan
        l = mom - idx_mom if mom is not None and idx_mom is not None and not np.isnan(mom) and not np.isnan(idx_mom) else np.nan
        f = {"A": a, "N": n, "S": s, "L": l}
        if q_avail and code in q_eps_gr.index:
            qkey = f"{fy}0930" if m % 100 >= 11 else f"{fy}0630" if m % 100 >= 9 else f"{fy}0331"
            f["C"] = q_eps_gr.get(code, np.nan)
        d[code] = f
    # 截面分位 (0-1)
    for k in ("C", "A", "N", "S", "L"):
        vals = {cd: f[k] for cd, f in d.items() if k in f and not (isinstance(f[k], float) and np.isnan(f[k]))}
        if len(vals) < 30:
            continue
        srt = sorted(vals, key=vals.get)
        rank = {cd: (i + 1) / len(srt) for i, cd in enumerate(srt)}
        for cd in d:
            if cd in rank:
                d[cd][k] = rank[cd]
    factor_cache[m] = d

# ---------- 回测 ----------
def topN_ret(score_fn, topn=30):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan)
            continue
        sc = {cd: score_fn(cd, m) for cd in CODES}
        sc = {cd: v for cd, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < topn:
            out.append(np.nan)
            continue
        top = sorted(sc, key=sc.get, reverse=True)[:topn]
        rs = [ret_m.loc[months[i], x] for x in top if not np.isnan(ret_m.loc[months[i], x])]
        out.append(np.mean(rs) if rs else np.nan)
    return out

canslim_ret = topN_ret(lambda cd, m: canslim_score(cd, m, factor_cache))

# 对比: 动量 / 低波 / 核心_无ROE (复用 HS300 WS2 结果缓存)
def perf(r):
    r = pd.Series(r).dropna()
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    ar = nav.iloc[-1] ** (1 / yrs) - 1
    av = r.std() * np.sqrt(12)
    shp = (ar - 0.02) / av if av > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {"年化": ar, "夏普": shp, "回撤": dd, "Calmar": ar / abs(dd) if dd else np.nan}

eq = ret_m[CODES].mean(axis=1)
results = {}
results["CANSLIM_四因子"] = canslim_ret
results["基准_HS300等权"] = eq.values

# 与既有策略相关性 (加载 WS2 导航缓存)
nav_ws2 = pd.read_csv("mx_fin_data/hs300_ws2_nav.csv") if os.path.exists("mx_fin_data/hs300_ws2_nav.csv") else None
if nav_ws2 is not None:
    # 由净值推月收益
    for col in nav_ws2.columns:
        if col in ("组合等权1/3_无ROE", "卫星_动量", "卫星_低波"):
            v = nav_ws2[col].values
            r = pd.Series([np.nan] + [v[i] / v[i - 1] - 1 for i in range(1, len(v)) if v[i] and v[i - 1]], index=months[:len(v)])
            results[col] = r.reindex(months).values

print("\n=== CANSLIM 卫星回测 (HS300, Top30, 2014-01~2026-08) ===")
for k, r in results.items():
    p = perf(r)
    print(f"  {k:<18} 年化 {p['年化']*100:6.1f}% | 夏普 {p['夏普']:6.3f} | 回撤 {p['回撤']*100:6.1f}%")

# 相关性 (统一 months index 对齐)
if nav_ws2 is not None:
    df = pd.DataFrame({k: pd.Series(list(v), index=months) for k, v in results.items()})
    corr = df.corr()
    print("\n=== 与既有策略相关性 ===")
    print(corr.loc[["CANSLIM_四因子"], [c for c in corr.columns if c != "CANSLIM_四因子"]].round(3).to_string())

# 保存
pd.DataFrame({k: pd.Series(list(v), index=months) for k, v in results.items()}).to_csv("mx_fin_data/canslim_results.csv", index=False)
print("\n已存 mx_fin_data/canslim_results.csv")
