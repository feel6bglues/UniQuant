# -*- coding: utf-8 -*-
"""pipeline_common.py — 共享数据层 (T0a)
统一入口: 财报面板(dict索引) / 收益矩阵 / xdxr / TTM / 截面标准化
消灭 run_*.py 之间的重复加载与口径不一致。
"""
import os, json
import numpy as np
import pandas as pd

FIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mx_fin_data")

# ---------- 财报面板 ----------
def load_panel(periods, need=("eps", "np", "ocf", "capex", "shares", "roe", "np_gr")):
    """预加载多期财报 -> pre[(code, period)] = {field: value}
    period 如 '20231231' / '20240930'。全A规模性能关键: dict 索引, 禁逐行布尔过滤。
    """
    from mootdx_client import MootdxClient
    c = MootdxClient()
    pre = {}
    for p in periods:
        fn = os.path.join(FIN_DIR, f"gpcw{p}.csv")
        if not os.path.exists(fn):
            continue
        df = pd.read_csv(fn, index_col=0, dtype=str)
        df.index = df.index.astype(str).str.zfill(6)
        for col in need:
            s = c._pick(df, col)
            if s is not None:
                df[col] = pd.to_numeric(s, errors="coerce")
        if "ocf" in df.columns and "capex" in df.columns:
            df["fcf"] = df["ocf"] - df["capex"].fillna(0)
        for code, r in df.iterrows():
            pre[(code, p)] = {k: r.get(k, np.nan) for k in need}
            pre[(code, p)]["fcf"] = r.get("fcf", np.nan)
    return pre

# ---------- 收益矩阵 ----------
def load_returns(codes, monthly, min_month=201401):
    """月收益矩阵 DataFrame(index=month, columns=code)"""
    months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
    months = [m for m in months if m >= min_month]
    ret_m = {}
    for code in codes:
        px = {int(k): v for k, v in monthly.get(code, {}).items()}
        seq = [px.get(m) for m in months]
        r = [np.nan]
        for i in range(1, len(seq)):
            r.append(seq[i] / seq[i - 1] - 1 if seq[i] and seq[i - 1] else np.nan)
        ret_m[code] = r
    return pd.DataFrame(ret_m, index=months), months

# ---------- xdxr ----------
def load_xdxr(name="hs300_xdxr.json"):
    path = os.path.join(FIN_DIR, name)
    return json.load(open(path)) if os.path.exists(path) else {}

def year_dps(xdxr, code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# ---------- 调仓日历 ----------
def fy_of(m, annual=False):
    """年频: 5月调仓用上年报; 季频: 见 rebal_period"""
    y = m // 100
    return y - 1 if m % 100 >= 5 else y - 2

def rebal_period(m, annual=False):
    """季频调仓点 -> (cur_period, fy)  PIT
    5月 -> 上年年报1231; 9月 -> 当年中报0630; 11月 -> 当年三季报0930
    annual=True 模拟年频 fy_of: 5-12月用上年报(y-1), 1-4月用再上年报(y-2)
    """
    y, mo = m // 100, m % 100
    if annual:
        return (f"{y-1}1231", y - 1) if mo >= 5 else (f"{y-2}1231", y - 2)
    if mo == 5:
        return f"{y-1}1231", y - 1
    if mo == 9:
        return f"{y}0630", y
    return f"{y}0930", y

def ttm(pre, code, cur_p, year):
    """TTM: 当期累计 + 上年年报 - 上年同期累计 (年报即 TTM)"""
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
        if all(isinstance(v, (int, float)) and not np.isnan(v) for v in (a, b, cc)):
            out[k] = a + b - cc
        else:
            out[k] = np.nan
    out["shares"], out["roe"] = cur["shares"], cur["roe"]
    out["np_gr"] = cur["np_gr"]
    if all(not np.isnan(out[k]) for k in ("ocf", "capex")):
        out["fcf"] = out["ocf"] - out["capex"]
    else:
        out["fcf"] = np.nan
    return out

# ---------- 截面标准化 ----------
def zscore(codes_dict, key):
    """{code: {factor...}} -> {code: z} (截面z-score)"""
    vals = {cd: v[key] for cd, v in codes_dict.items() if v.get(key) is not None and not np.isnan(v.get(key))}
    if len(vals) < 20:
        return {}
    arr = np.array(list(vals.values()))
    mu, sd = arr.mean(), arr.std()
    if sd == 0:
        return {}
    return {cd: (v - mu) / sd for cd, v in vals.items()}

# ---------- 因子缓存 ----------
def build_factor_cache(codes, pre, xdxr, monthly, months, keys=("fcfy", "cash", "dy"),
                       normalize="zscore", annual=False, include_ep=False):
    """构建逐调仓点截面因子 -> cache[m][code] = {key: 标准化值}
    normalize='zscore': 截面 z; 'raw': 原始值; 'rank': 分位(0-1)
    annual=True: 仅 5 月调仓(年频口径)
    """
    px_all = {code: {int(k): v for k, v in monthly.get(code, {}).items()} for code in codes}
    cache = {}
    all_keys = list(keys) + (["ep"] if include_ep else [])
    for mi, m in enumerate(months):
        cur_p, fy = rebal_period(m, annual)
        d = {}
        if annual:
            p_ym = fy * 100 + 12   # 年频: 因子用上年12月末价 (复现原口径)
        else:
            p_ym = months[mi - 1] if mi > 0 else m  # 季频: 调仓月初执行, 因子用上月(决策日)月末价, 防未来函数
        for code in codes:
            p = px_all[code].get(p_ym)
            if not p:
                continue
            f = ttm(pre, code, cur_p, m // 100)
            if f is None:
                continue
            mcap = p * f["shares"] if f["shares"] and f["shares"] > 0 else np.nan
            ep = f["eps"] / p if not np.isnan(f["eps"]) else np.nan
            fcf = f["fcf"] if not np.isnan(f["fcf"]) else np.nan
            fcfy = fcf / mcap if mcap and not np.isnan(fcf) else np.nan
            cash = f["ocf"] / f["np"] if f["np"] and f["np"] > 0 and not np.isnan(f["ocf"]) else np.nan
            dy = year_dps(xdxr, code, fy) / p
            d[code] = {"ep": ep, "fcfy": fcfy, "cash": cash, "dy": dy}
        # 标准化
        if normalize == "zscore":
            zs = {k: zscore(d, k) for k in all_keys}
            cache[m] = {cd: {k: zs[k].get(cd, np.nan) for k in all_keys} for cd in d}
        elif normalize == "raw":
            cache[m] = d
        else:  # rank
            out = {}
            for k in all_keys:
                vals = {cd: v[k] for cd, v in d.items() if v[k] is not None and not np.isnan(v[k])}
                srt = sorted(vals, key=vals.get)
                rank = {cd: (i + 1) / len(srt) for i, cd in enumerate(srt)}
                for cd in d:
                    d[cd][k] = rank.get(cd, np.nan)
            cache[m] = d
    return cache

def score_from_cache(cache, m, code, keys=("fcfy", "cash", "dy"), min_valid=2):
    """从缓存查分数: keys 的 mean (需 min_valid 个有效)"""
    d = cache.get(m)
    if not d or code not in d:
        return np.nan
    parts = [d[code][k] for k in keys if not np.isnan(d[code].get(k, np.nan))]
    return np.mean(parts) if len(parts) >= min_valid else np.nan

def pctile_rank(series, window=36, min_obs=24):
    """滚动分位 (0-100), NaN 直到窗口足够"""
    out = {}
    vals = list(series.index)
    for i, m in enumerate(vals):
        if i < window - 1:
            out[m] = np.nan
            continue
        win = series.iloc[max(0, i - window + 1):i + 1].dropna()
        if len(win) < min_obs or np.isnan(series.iloc[i]):
            out[m] = np.nan
            continue
        out[m] = (win < series.iloc[i]).mean() * 100
    return pd.Series(out)
