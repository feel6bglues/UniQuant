# -*- coding: utf-8 -*-
"""全量数据验证: 全A(5328只) 口径完整策略链路
季频新核心(现金+FCFY+EP, Top10%) + 动量25% + 低波25% + 熔断A(全A拥挤度) + 成本敏感性
对标: HS300 当前成分口径 (T2: 组合 0.559) -> 得到无幸存者偏差的全量可信结论
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
print(f"全A {len(ALL_CODES)} 只 | Top{TOP} | months {months[0]}~{months[-1]}", flush=True)

# ---------- 1. 核心: 季频新核心 (cash+FCFY+EP) ----------
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)
core_res = bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, keys=("cash", "fcfy", "ep"), min_valid=2),
                           months, ret_m, topn=TOP, rebal_every="quarter")
print(f"\n全A 季频新核心: 夏普 {core_res['perf']['夏普']:.3f}", flush=True)

# ---------- 2. 卫星: 动量 / 低波 (月频 Top10%, 性能优化: 预构建价格索引) ----------
px_all = {code: {int(k): v for k, v in a_monthly.get(code, {}).items()} for code in ALL_CODES}
ks_all = {code: sorted(px_all[code].keys()) for code in ALL_CODES}

def mom_score(code, m):
    ks = ks_all[code]
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    px = px_all[code]
    p12, p1 = px.get(ks[i - 13]), px.get(ks[i - 2])
    return p1 / p12 - 1 if p12 and p1 else np.nan

def lowvol_score(code, m):
    ks = ks_all[code]
    try:
        i = ks.index(m)
    except ValueError:
        return np.nan
    if i < 13:
        return np.nan
    px = px_all[code]
    seq = [px.get(k) for k in ks[i - 13:i]]
    if any(not p for p in seq):
        return np.nan
    r = [seq[j + 1] / seq[j] - 1 for j in range(len(seq) - 1)]
    return -np.std(r)

mom_res = bt.run_backtest(mom_score, months, ret_m, topn=TOP, rebal_every="month")
lv_res = bt.run_backtest(lowvol_score, months, ret_m, topn=TOP, rebal_every="month")
print(f"动量: 夏普 {mom_res['perf']['夏普']:.3f} | 低波: 夏普 {lv_res['perf']['夏普']:.3f}", flush=True)

# ---------- 3. 组合 (全A 修正构型: 核心60 + 低波40, 无动量——全A 动量反转负因子) ----------
core_r, mom_r, lv_r = core_res["returns"], mom_res["returns"], lv_res["returns"]
comb = np.array([0.6 * c + 0.4 * l if not any(np.isnan([c, l])) else np.nan
                 for c, l in zip(core_r, lv_r)])
to_comb = np.array([0.6 * tc + 0.4 * tl
                    if not any(np.isnan([tc, tl])) else np.nan
                    for tc, tl in zip(core_res["turnover"], lv_res["turnover"])])
print(f"\n组合(核心60+低波40) 平均月换手: {np.nanmean(to_comb)*100:.1f}%", flush=True)

# ---------- 4. 熔断A (全A 拥挤度) ----------
crowd_df = pd.read_csv("mx_fin_data/ws4_crowding_all_a.csv")
crowd_map = dict(zip(crowd_df["month"].astype(int), crowd_df["crowd"]))
crowd_s = np.array([crowd_map.get(m, np.nan) for m in months])

def apply_fuse(cr):
    out = []
    for i, c in enumerate(cr):
        if np.isnan(c) or np.isnan(crowd_s[i]):
            out.append(np.nan)
            continue
        if crowd_s[i] >= 85:
            out.append(lv_r[i])                          # 核心清仓 -> 全低波
        elif crowd_s[i] >= 75:
            out.append(0.3 * c + 0.7 * lv_r[i])          # 核心减半 -> 低波补位
        else:
            out.append(0.6 * c + 0.4 * lv_r[i])
    return np.array(out)

comb_fused = apply_fuse(comb)

# ---------- 5. 成本敏感性 ----------
print("\n=== 全量验证 (全A, 季频新核心组合) ===")
for name, r in [("静态组合", comb), ("熔断A组合", comb_fused)]:
    p = bt.perf(r)
    print(f"  {name:<10} 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:5.1f}% | 回撤 {p['最大回撤']*100:6.1f}% | Calmar {p['Calmar']:.3f} | 净值 {p['期末净值']:.2f}", flush=True)
print("  成本敏感性 (熔断A组合):")
for cost in (0.0, 0.001, 0.002, 0.003):
    adj = comb_fused.copy()
    for i in range(len(months)):
        if not np.isnan(adj[i]) and not np.isnan(to_comb[i]):
            adj[i] -= 2 * cost * to_comb[i]
    p = bt.perf(adj)
    print(f"    单边{cost*100:.1f}%: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}%", flush=True)

# ---------- 6. 2024-02 压力测试 ----------
print("\n=== 2024-02 微盘崩塌压力测试 ===")
i24 = months.index(202402)
for name, r in [("新核心", core_r), ("组合60/40", comb), ("熔断A", comb_fused), ("全A等权", ret_m[ALL_CODES].mean(axis=1).values)]:
    v = r[i24]
    print(f"  {name:<10} 202402 收益: {v*100:+.2f}%" if not np.isnan(v) else f"  {name}: NaN")

# 保存
pd.DataFrame({"month": months, "core": core_r, "mom": mom_r, "lowvol": lv_r,
              "comb": comb, "comb_fused": comb_fused, "turnover": to_comb,
              "crowd": crowd_s}).to_csv("mx_fin_data/full_a_validation.csv", index=False)
print("\n已存 mx_fin_data/full_a_validation.csv")
