# -*- coding: utf-8 -*-
"""T2 HS300 季频组合全链路: 核心(季频) + 动量25% + 低波25% + 熔断A
输出: 收益 / 换手率 / 成本敏感性 (0, 0.1%, 0.2%, 0.3% 单边)
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import pipeline_common as pc
import backtest_engine as bt

CODES = json.load(open("mx_fin_data/hs300_codes.json"))
monthly = json.load(open("mx_fin_data/hs300_monthly.json"))
xdxr = pc.load_xdxr("hs300_xdxr.json")
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(CODES, monthly)
print(f"HS300 {len(CODES)} 只 | months {months[0]}~{months[-1]}", flush=True)

# ---------- 三腿策略 ----------
cache = pc.build_factor_cache(CODES, pre, xdxr, monthly, months, normalize="zscore")
core_res = bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, min_valid=2),
                           months, ret_m, topn=30, rebal_every="quarter")

def mom_score(code, m):
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    ks = sorted(px.keys())
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    p12, p1 = px.get(ks[i - 13]), px.get(ks[i - 2])
    return p1 / p12 - 1 if p12 and p1 else np.nan

def lowvol_score(code, m):
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    ks = sorted(px.keys())
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    seq = [px.get(k) for k in ks[i - 13:i]]
    if any(not p for p in seq):
        return np.nan
    r = [seq[j + 1] / seq[j] - 1 for j in range(len(seq) - 1)]
    return -np.std(r)

mom_res = bt.run_backtest(mom_score, months, ret_m, topn=30, rebal_every="month")
lv_res = bt.run_backtest(lowvol_score, months, ret_m, topn=30, rebal_every="month")

# ---------- 组合 (核心50 + 动量25 + 低波25) ----------
core_r, mom_r, lv_r = core_res["returns"], mom_res["returns"], lv_res["returns"]
comb = np.array([0.5 * c + 0.25 * m + 0.25 * l if not any(np.isnan([c, m, l])) else np.nan
                 for c, m, l in zip(core_r, mom_r, lv_r)])

# 组合换手 (加权)
to_comb = np.array([0.5 * tc + 0.25 * tm + 0.25 * tl
                    if not any(np.isnan([tc, tm, tl])) else np.nan
                    for tc, tm, tl in zip(core_res["turnover"], mom_res["turnover"], lv_res["turnover"])])
avg_to = np.nanmean(to_comb)
print(f"\n=== 组合 (核心50+动量25+低波25) ===")
print(f"  平均月换手: {avg_to*100:.1f}% | 平均季度换手: {avg_to*300:.1f}%")

# ---------- 熔断A (HS300 拥挤度) ----------
crowd_df = pd.read_csv("mx_fin_data/ws4_crowding.csv")
crowd_map = dict(zip(crowd_df["month"].astype(int), crowd_df["crowd"]))
crowd_s = np.array([crowd_map.get(m, np.nan) for m in months])
dim_map = dict(zip(crowd_df["month"].astype(int),
                   crowd_df[["估值拥挤(100-DY分位)", "成交占比分位", "放大幅度分位"]].max(axis=1)))
dim_s = np.array([dim_map.get(m, np.nan) for m in months])

def apply_fuse(core_r, cr, dm):
    """熔断A: 合成>=75 核心减半(低波补), >=85 清仓(动量+低波)"""
    out = []
    for i, c in enumerate(core_r):
        if np.isnan(c) or np.isnan(cr[i]):
            out.append(np.nan)
            continue
        if cr[i] >= 85:
            out.append(0.5 * mom_r[i] + 0.5 * lv_r[i])      # 核心清仓
        elif cr[i] >= 75:
            out.append(0.25 * c + 0.25 * mom_r[i] + 0.5 * lv_r[i])  # 核心减半
        else:
            out.append(0.5 * c + 0.25 * mom_r[i] + 0.25 * lv_r[i])
    return np.array(out)

comb_fused = apply_fuse(core_r, crowd_s, dim_s)

print("\n=== 熔断A 效果 (无成本) ===")
for name, r in [("静态组合", comb), ("熔断A组合", comb_fused)]:
    p = bt.perf(r)
    print(f"  {name:<10} 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}% | Calmar {p['Calmar']:.3f} | 净值 {p['期末净值']:.2f}")

# ---------- 成本敏感性 ----------
print("\n=== 成本敏感性 (单边成本, 熔断A组合) ===")
for cost in (0.0, 0.001, 0.002, 0.003):
    adj = comb_fused.copy()
    for i in range(len(months)):
        if not np.isnan(adj[i]) and not np.isnan(to_comb[i]):
            adj[i] -= 2 * cost * to_comb[i]
    p = bt.perf(adj)
    print(f"  单边{cost*100:.1f}%: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}%", flush=True)

# 保存
pd.DataFrame({"month": months, "core": core_r, "mom": mom_r, "lowvol": lv_r,
              "comb": comb, "comb_fused": comb_fused, "turnover": to_comb,
              "crowd": crowd_s}).to_csv("mx_fin_data/t2_quarterly_combo.csv", index=False)
print("\n已存 mx_fin_data/t2_quarterly_combo.csv")
