# -*- coding: utf-8 -*-
"""独立核验: 不用 pipeline_common/backtest_engine, 纯 pandas/numpy 手写
复现全A 季频核心 (cash+FCFY+EP) 全样本/IS/OOS 夏普
预期: 全样本 ~0.348 | IS 2014-18 ~0.229 | OOS 2019-26 ~0.496
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd

FIN = "mx_fin_data"
ALL_CODES = json.load(open(f"{FIN}/all_a_codes.json"))
monthly = json.load(open(f"{FIN}/all_a_monthly.json"))
xdxr = json.load(open(f"{FIN}/all_a_xdxr.json"))
RF = 0.02
TOP_PCT = 0.10

# ---------- 1. 财报面板 (原始 CSV, 手写解析) ----------
print("加载财报 (57期手写解析)...", flush=True)
pre = {}
for y in range(2010, 2025):
    fn = f"{FIN}/gpcw{y}1231.csv"
    if os.path.exists(fn):
        df = pd.read_csv(fn, index_col=0, dtype=str)
        df.index = df.index.astype(str).str.zfill(6)
        for col in ("eps", "np", "ocf", "capex", "shares"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                # gpcw 列名是中文: 精确名优先, 否则子串匹配
                exact = {"eps": "基本每股收益", "np": "归属于母公司所有者的净利润",
                         "ocf": "经营活动产生的现金流量净额",
                         "capex": "购建固定资产、无形资产和其他长期资产支付的现金",
                         "shares": "总股本"}
                match = [c for c in df.columns if c == exact[col]] if exact[col] in df.columns else (
                    [c for c in df.columns if ("每股收益" in c and "基本" in c and "单季" not in c)] if col == "eps" else (
                    [c for c in df.columns if "净利润" in c and "归母" in c and "所有" in c and "增长率" not in c and "快报" not in c] if col == "np" else (
                    [c for c in df.columns if c.startswith("经营活动产生的现金流量净额")] if col == "ocf" else (
                    [c for c in df.columns if "购建固定" in c] if col == "capex" else (
                    [c for c in df.columns if c == "总股本"] if col == "shares" else [])))))
                if match:
                    df[col] = pd.to_numeric(df[match[0]], errors="coerce")
        if "ocf" in df.columns and "capex" in df.columns:
            df["fcf"] = df["ocf"] - df["capex"].fillna(0)
        for code, r in df.iterrows():
            pre[(code, f"{y}1231")] = r   # 键用完整期格式, 与 ttm 查询一致
    for q in ("0331", "0630", "0930"):
        if y < 2011:
            continue
        fn = f"{FIN}/gpcw{y}{q}.csv"
        if not os.path.exists(fn):
            continue
        df = pd.read_csv(fn, index_col=0, dtype=str)
        df.index = df.index.astype(str).str.zfill(6)
        for col in ("eps", "np", "ocf", "capex", "shares"):
            exact = {"eps": "基本每股收益", "np": "归属于母公司所有者的净利润",
                     "ocf": "经营活动产生的现金流量净额",
                     "capex": "购建固定资产、无形资产和其他长期资产支付的现金",
                     "shares": "总股本"}
            m = [c for c in df.columns if c == exact[col]] if exact[col] in df.columns else (
                [c for c in df.columns if ("每股收益" in c and "基本" in c and "单季" not in c)] if col == "eps" else (
                [c for c in df.columns if "净利润" in c and "归母" in c and "所有" in c and "增长率" not in c and "快报" not in c] if col == "np" else (
                [c for c in df.columns if c.startswith("经营活动产生的现金流量净额")] if col == "ocf" else (
                [c for c in df.columns if "购建固定" in c] if col == "capex" else (
                [c for c in df.columns if c == "总股本"] if col == "shares" else [])))))
            if m:
                df[col] = pd.to_numeric(df[m[0]], errors="coerce")
        if "ocf" in df.columns and "capex" in df.columns:
            df["fcf"] = df["ocf"] - df["capex"].fillna(0)
        for code, r in df.iterrows():
            pre[(code, f"{y}{q}")] = r
print(f"pre: {len(pre)} 条", flush=True)

# ---------- 2. 收益矩阵 (手写) ----------
months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
months = [m for m in months if m >= 201401]
ret_m = pd.DataFrame(index=months)
for code in ALL_CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    seq = [px.get(m) for m in months]
    r = [np.nan]
    for i in range(1, len(seq)):
        r.append(seq[i] / seq[i - 1] - 1 if seq[i] and seq[i - 1] else np.nan)
    ret_m[code] = r

# ---------- 3. TTM + 因子 (手写) ----------
def ttm(code, cur_p, year):
    cur = pre.get((code, cur_p))
    if cur is None:
        return None
    if cur_p.endswith("1231"):
        return cur
    pv_q = pre.get((code, f"{year-1}{cur_p[4:]}"))
    pv_y = pre.get((code, f"{year-1}1231"))
    if pv_q is None or pv_y is None:
        return None
    out = {}
    for k in ("eps", "np", "ocf", "capex"):
        a, b, cc = cur[k], pv_y[k], pv_q[k]
        out[k] = a + b - cc if all(isinstance(v, (int, float)) and not np.isnan(v) for v in (a, b, cc)) else np.nan
    out["shares"] = cur["shares"]
    return out

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

px_all = {code: {int(k): v for k, v in monthly.get(code, {}).items()} for code in ALL_CODES}
REBAL = [m for m in months if m % 100 in (5, 9, 11)]
TOP = max(30, int(len(ALL_CODES) * TOP_PCT))

def rebal_month_factors(m):
    """决策日月末(m-1)价 -> {code: {cash,fcfy,ep}} (zscore)"""
    y, mo = m // 100, m % 100
    if mo == 5:
        cur_p = f"{y-1}1231"
    elif mo == 9:
        cur_p = f"{y}0630"
    else:
        cur_p = f"{y}0930"
    dm = m - 1 if mo > 1 else (y - 1) * 100 + 12   # 决策日月末
    raw = {}
    for code in ALL_CODES:
        p = px_all[code].get(dm)
        if not p:
            continue
        f = ttm(code, cur_p, y)
        if f is None or not f.get("shares") or np.isnan(f["shares"]):
            continue
        mcap = p * f["shares"]
        raw[code] = {
            "cash": f["ocf"] / f["np"] if f["np"] and f["np"] > 0 and not np.isnan(f["ocf"]) else np.nan,
            "fcfy": (f["ocf"] - f["capex"]) / mcap if not np.isnan(f["ocf"]) else np.nan,
            "ep": f["eps"] / p if not np.isnan(f["eps"]) else np.nan,
        }
    # 截面 zscore
    out = {}
    for k in ("cash", "fcfy", "ep"):
        vals = {cd: v[k] for cd, v in raw.items() if v[k] is not None and not np.isnan(v[k])}
        if len(vals) < 100:
            continue
        arr = np.array(list(vals.values()))
        mu, sd = arr.mean(), arr.std()
        if sd == 0:
            continue
        for cd, v in vals.items():
            raw[cd][k + "_z"] = (v - mu) / sd
    for cd in raw:
        parts = [raw[cd].get(k + "_z") for k in ("cash", "fcfy", "ep")]
        parts = [x for x in parts if x is not None]
        if len(parts) >= 2:
            out[cd] = np.mean(parts)
    return out

# ---------- 4. 回测 (手写: 季频调仓, 月初执行, 持有到下个调仓点) ----------
print("独立回测...", flush=True)
_debug = rebal_month_factors(202405)
print(f"[debug] 202405 有效分: {len(_debug)}", flush=True)
if _debug:
    _t = sorted(_debug, key=_debug.get, reverse=True)[:3]
    print(f"[debug] top3: {[(c, round(_debug[c],3)) for c in _t]}", flush=True)
else:
    # 内部诊断 (不重 import)
    r_dbg = pre.get(("600519", "20231231"))
    print(f"[debug] pre 600519/20231231 存在: {r_dbg is not None}", flush=True)
    if r_dbg is not None:
        print(f"[debug] pre np/ocf/shares: {r_dbg.get('np')} / {r_dbg.get('ocf')} / {r_dbg.get('shares')}", flush=True)
    f_dbg = ttm("600519", "20231231", 2024)
    print(f"[debug] ttm 600519 eps/np: {f_dbg.get('eps') if f_dbg else None} / {f_dbg.get('np') if f_dbg else None}", flush=True)
def backtest():
    """全样本单跑, 返回 (months_list, returns)"""
    m_out, holds = [], []
    for i, m in enumerate(REBAL):
        sc = rebal_month_factors(m)
        if len(sc) < TOP:
            continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP]
        nxt = REBAL[i + 1] if i + 1 < len(REBAL) else months[-1]
        seg = [mm for mm in months if m <= mm < nxt]
        for mm in seg:
            rs = [ret_m.loc[mm, cd] for cd in top if not np.isnan(ret_m.loc[mm, cd])]
            if rs:
                m_out.append(mm)
                holds.append(np.mean(rs))
    return m_out, np.array(holds)

m_list, r_all = backtest()
print(f"[debug] 全样本序列: {len(r_all)} 个月 ({m_list[0]}~{m_list[-1]})", flush=True)
for _dm in (201405, 201411):
    _sc = rebal_month_factors(_dm)
    if _sc:
        _t = sorted(_sc, key=_sc.get, reverse=True)[:5]
        print(f"[debug] 独立 {_dm} top5: {[(c, round(_sc[c],2)) for c in _t]}", flush=True)
    else:
        print(f"[debug] 独立 {_dm}: 无有效分", flush=True)

def perf(r):
    r = pd.Series(r).dropna().values
    if len(r) < 12:
        return (np.nan, np.nan, np.nan)
    nav = np.cumprod(1 + r)
    yrs = len(r) / 12
    ar = nav[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ar - RF) / vol if vol > 0 else np.nan
    return (ar, vol, sh)

def slice_perf(lo, hi):
    sel = [i for i, mm in enumerate(m_list) if (lo is None or mm >= lo) and (hi is None or mm <= hi)]
    r = r_all[sel]
    ar, vol, sh = perf(r)
    return ar, vol, sh, len(r)

print("\n=== 独立实现复现 v2 (全样本跑完再切分, 与引擎一致) ===", flush=True)
for lo, hi, name in [(None, None, "全样本"), (201401, 201812, "IS 2014-18"), (201901, None, "OOS 2019-26")]:
    ar, vol, sh, n = slice_perf(lo, hi)
    print(f"  {name}: 年化 {ar*100:5.1f}% | 波动 {vol*100:5.1f}% | 夏普 {sh:.3f} | 月数 {n}", flush=True)
print("\n预期对照: 全样本 ~0.348 | IS ~0.229 | OOS ~0.496")

def perf(r):
    r = pd.Series(r).dropna().values
    if len(r) < 12:
        return (np.nan, np.nan, np.nan)
    nav = np.cumprod(1 + r)
    yrs = len(r) / 12
    ar = nav[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ar - RF) / vol if vol > 0 else np.nan
    return (ar, vol, sh)

print("\n=== 独立实现复现 (手写, 不依赖共享层) ===", flush=True)
print("(v2 结果见上方 slice_perf 输出)")

# 保存全样本逐月序列供对比 (DataFrame, month 显式列)
import pandas as _pd
_pd.DataFrame({"month": m_list, "indep": r_all}).to_csv("mx_fin_data/verify_indep_series.csv", index=False)
print("已存 verify_indep_series.csv")
