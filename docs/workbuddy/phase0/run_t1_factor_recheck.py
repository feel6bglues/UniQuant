# -*- coding: utf-8 -*-
"""T1 全A 因子复核 + 新核心对照 (无未来函数口径)
1) 单因子 IR 复核 (真实DY 口径): EP / FCFY / 现金含量 / DY
2) 构成因子截面相关性矩阵 (防冗余暴露)
3) 新核心 (现金含量+FCFY+EP) vs 含DY旧核心 vs 全A等权基准
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import pipeline_common as pc
import backtest_engine as bt

CODES = json.load(open("mx_fin_data/all_a_codes.json"))
monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
xdxr = pc.load_xdxr("all_a_xdxr.json")
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(CODES, monthly)
TOP_A = max(30, int(len(CODES) * 0.10))
print(f"全A {len(CODES)} 只 | Top{TOP_A} | months {months[0]}~{months[-1]}", flush=True)

# ---------- 1. 单因子 IR (季度调仓, 月初执行无未来函数) ----------
cache = pc.build_factor_cache(CODES, pre, xdxr, monthly, months, normalize="zscore", include_ep=True)
print("\n=== 1. 单因子复核 (全A, 季频调仓 Top10%, 无未来函数) ===", flush=True)
for fk in ("ep", "fcfy", "cash", "dy"):
    r = bt.run_backtest(lambda cd, m, fk=fk: pc.score_from_cache(cache, m, cd, keys=(fk,), min_valid=1),
                        months, ret_m, topn=TOP_A, rebal_every="quarter")
    p = r["perf"]
    print(f"  {fk:<6} 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}% | 净值 {p['期末净值']:.2f}", flush=True)

# ---------- 2. 构成因子相关性矩阵 (2024 年报截面) ----------
print("\n=== 2. 构成因子截面相关性 (2024年报, spearman) ===", flush=True)
cur_p, fy = pc.rebal_period(202605, annual=False)
d = {}
px_all = {code: {int(k): v for k, v in monthly.get(code, {}).items()} for code in CODES}
for code in CODES:
    p = px_all[code].get(202604)   # 调仓月 202605 的决策日月末 = 202604
    if not p:
        continue
    f = pc.ttm(pre, code, cur_p, 2026)
    if f is None:
        continue
    mcap = p * f["shares"] if f["shares"] and f["shares"] > 0 else np.nan
    d[code] = {"ep": f["eps"] / p if not np.isnan(f["eps"]) else np.nan,
               "fcfy": (f["fcf"] / mcap) if mcap and not np.isnan(f["fcf"]) else np.nan,
               "cash": (f["ocf"] / f["np"]) if f["np"] and f["np"] > 0 and not np.isnan(f["ocf"]) else np.nan,
               "dy": pc.year_dps(xdxr, code, fy) / p}
df = pd.DataFrame(d).T
corr = df.corr(method="spearman")
print(corr.round(3).to_string())

# ---------- 3. 新核心对照 ----------
print("\n=== 3. 核心对照 (全A, 季频 Top10%, 无未来函数) ===", flush=True)
def core_ret(keys):
    return bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, keys=keys, min_valid=2),
                           months, ret_m, topn=TOP_A, rebal_every="quarter")
for name, keys in [("新核心(现金+FCFY+EP)", ("cash", "fcfy", "ep")),
                   ("旧核心(现金+FCFY+DY)", ("cash", "fcfy", "dy")),
                   ("混合(现金+FCFY+DY+EP)", ("cash", "fcfy", "dy", "ep"))]:
    r = core_ret(keys)
    p = r["perf"]
    print(f"  {name:<22} 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}% | Calmar {p['Calmar']:.3f}", flush=True)

eq = ret_m[CODES].mean(axis=1).values
p = bt.perf(eq)
print(f"  {'基准_全A等权':<22} 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}%", flush=True)

# 换手率对比 (新核心)
r_new = core_ret(("cash", "fcfy", "ep"))
to = r_new["turnover"]
print(f"\n  新核心平均季换手率: {np.nanmean(to)*100:.1f}% | 月均换手: {np.nanmean(to)*100/3:.1f}%")
print("\nDONE")
