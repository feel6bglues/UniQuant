# -*- coding: utf-8 -*-
"""T38 市值中性化归因: 拆解 alpha vs 市值风格 beta
原始: 全截面 zscore 选 Top10% (cash+FCFY+EP)
中性化: 按总市值分5组, 组内 zscore 选 Top10% 等权 -> 市值暴露中性
差异 = 市值风格 beta 贡献; 中性化后残留 = 纯 alpha
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import pipeline_common as pc
import backtest_engine as bt

ALL_CODES = json.load(open("mx_fin_data/all_a_codes.json"))
a_monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
xdxr_all = pc.load_xdxr("all_a_xdxr.json")
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(ALL_CODES, a_monthly)
TOP = max(30, int(len(ALL_CODES) * 0.10))
N_GROUP = 5
KEYS = ("cash", "fcfy", "ep")

px_all = {code: {int(k): v for k, v in a_monthly.get(code, {}).items()} for code in ALL_CODES}

# 每月市值 + 原始因子
def mcap_of(m):
    y, mo = m // 100, m % 100
    cur_p, fy = pc.rebal_period(m)
    out = {}
    for code in ALL_CODES:
        p = px_all[code].get(m)
        if not p:
            continue
        f = pc.ttm(pre, code, cur_p, y)
        if f is None or not f["shares"] or f["shares"] <= 0:
            continue
        out[code] = {"mcap": p * f["shares"],
                     "cash": cache[m].get(code, {}).get("cash", np.nan),
                     "fcfy": cache[m].get(code, {}).get("fcfy", np.nan),
                     "ep": cache[m].get(code, {}).get("ep", np.nan)}
    return out

def group_zscore(codes_dict, key, groups):
    """组内 zscore: codes_dict[code][key], groups: {code: group_id}"""
    out = {}
    for g in range(N_GROUP):
        members = [cd for cd in groups if groups[cd] == g]
        vals = {cd: codes_dict[cd][key] for cd in members if codes_dict[cd].get(key) is not None and not np.isnan(codes_dict[cd][key])}
        if len(vals) < 20:
            continue
        arr = np.array(list(vals.values()))
        mu, sd = arr.mean(), arr.std()
        if sd == 0:
            continue
        for cd, v in vals.items():
            out[cd] = (v - mu) / sd
    return out

# 预构建原始因子 (全截面 z, 复用 build_factor_cache)
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)

def build_scores(m, neutralized):
    """返回 {code: score}"""
    if m not in cache:
        return {}
    mc = mcap_of(m)
    if len(mc) < 500:
        return {}
    if neutralized:
        # 市值分5组, 组内 zscore (用全截面z值重组内标准化)
        srt = sorted(mc, key=lambda cd: -mc[cd]["mcap"])
        groups = {cd: i * N_GROUP // len(srt) for i, cd in enumerate(srt)}
        zs = {k: group_zscore(mc, k, groups) for k in KEYS}
    else:
        zs = {k: {cd: cache[m][cd][k] for cd in cache[m] if not np.isnan(cache[m][cd][k])} for k in KEYS}
    score = {}
    for cd in mc:
        parts = [zs[k].get(cd) for k in KEYS]
        parts = [x for x in parts if x is not None]
        if len(parts) >= 2:
            score[cd] = np.mean(parts)
    return score

def backtest(neutralized):
    # 预计算调仓月分数表 (避免引擎逐股调用 O(n²) 爆炸)
    REBAL = [m for m in months if m % 100 in (5, 9, 11)]
    scores = {}
    for m in REBAL:
        s = build_scores(m, neutralized)
        if s:
            scores[m] = s
    def score_fn(cd, m):
        s = scores.get(m)
        return s.get(cd, np.nan) if s else np.nan
    # 引擎口径: 季频调仓, 月初执行, 非调仓月不重选(避免未来函数)
    return bt.run_backtest(score_fn, months, ret_m, topn=TOP, rebal_every="quarter")["returns"]

print("\n=== T38 市值中性化归因 (全A 季频核心 cash+FCFY+EP, Top10%) ===", flush=True)
r_raw = backtest(False)
r_neu = backtest(True)

p_raw, p_neu = bt.perf(r_raw), bt.perf(r_neu)
print(f"  原始 (全截面):         夏普 {p_raw['夏普']:.3f} | 年化 {p_raw['年化收益']*100:.1f}% | 回撤 {p_raw['最大回撤']*100:.1f}%", flush=True)
print(f"  市值中性化 (组内z):    夏普 {p_neu['夏普']:.3f} | 年化 {p_neu['年化收益']*100:.1f}% | 回撤 {p_neu['最大回撤']*100:.1f}%", flush=True)
print(f"\n  市值风格贡献: 夏普 {p_raw['夏普']-p_neu['夏普']:+.3f} | 年化 {(p_raw['年化收益']-p_neu['年化收益'])*100:+.1f}pp")
print(f"  中性化后纯 alpha: 夏普 {p_neu['夏普']:.3f}", flush=True)

# IS/OOS 拆解
for lo, hi, name in [(201401, 201812, "IS 2014-18"), (201901, None, "OOS 2019-26")]:
    def seg(r):
        s = pd.Series(r, index=months)
        return s[(s.index >= lo) & (s.index <= (hi or 209901))]
    a = bt.perf(seg(r_raw).values)["夏普"]
    b = bt.perf(seg(r_neu).values)["夏普"]
    print(f"  {name}: 原始 {a:.3f} vs 中性化 {b:.3f} (市值贡献 {a-b:+.3f})", flush=True)

pd.DataFrame({"month": months, "raw": r_raw, "neutralized": r_neu}).to_csv("mx_fin_data/t38_neutralization.csv", index=False)
print("\n已存 mx_fin_data/t38_neutralization.csv")
