# -*- coding: utf-8 -*-
"""P0 walk-forward 样本外验证 + 指数趋势风控叠加 (全A 新核心)
协议 (固定):
  A) IS/OOS 切分: 2014-2018 训练 / 2019-2026 验证 (固定构成 cash+FCFY+EP)
  B) 滚动重估: 每年5月用过去5年季度IC选 top3 因子构成 -> 次年执行 (2019-2020 为干净OOS)
  C) 趋势风控: HS300 月线 MA12, 决策日月末价 < MA12 -> 降仓50% / 清仓0
输出: IS vs OOS 衰减 / 滚动 vs 固定 / 风控 vs 无风控 (含 2018/2022 熊市对比)
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
idx = json.load(open("mx_fin_data/hs300_index.json"))
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(ALL_CODES, a_monthly)
TOP = max(30, int(len(ALL_CODES) * 0.10))
FACTORS = ("ep", "fcfy", "cash", "dy")
FIXED = ("cash", "fcfy", "ep")

# 全因子 z 缓存 (含 ep/dy, 供任意构成组合)
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)
print(f"全A {len(ALL_CODES)} 只 | Top{TOP} | {months[0]}~{months[-1]}", flush=True)

def core_ret(keys, sub_months=None, months_all=None, ret=None):
    """引擎季频回测, 支持子区间(仅用 sub_months 的收益)"""
    ms = months_all if months_all is not None else months
    rm = ret if ret is not None else ret_m
    return bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, keys=keys, min_valid=2),
                           ms, rm, topn=TOP, rebal_every="quarter")

def sub_perf(r, lo=None, hi=None):
    r = pd.Series(r, index=months)
    if lo: r = r[r.index >= lo]
    if hi: r = r[r.index <= hi]
    return bt.perf(r.values)

# ---------- A. IS/OOS 切分 (固定构成) ----------
print("\n=== A. IS/OOS 切分 (固定构成 cash+FCFY+EP) ===", flush=True)
r_fixed = core_ret(FIXED)["returns"]
p_is = sub_perf(r_fixed, 201401, 201812)
p_oos = sub_perf(r_fixed, 201901)
print(f"  IS 2014-2018: 夏普 {p_is['夏普']:.3f} | 年化 {p_is['年化收益']*100:.1f}% | 月数 {p_is['月数']}", flush=True)
print(f"  OOS 2019-2026: 夏普 {p_oos['夏普']:.3f} | 年化 {p_oos['年化收益']*100:.1f}% | 月数 {p_oos['月数']}", flush=True)

# ---------- B. 滚动因子重估 (每年5月用过去5年季度IC选top3) ----------
print("\n=== B. 滚动因子重估 (5年窗口季度IC选top3) ===", flush=True)
REBAL = [m for m in months if m % 100 in (5, 9, 11)]
# 预计算每个调仓点的 forward return (个股: 到下个调仓点连乘)
fwd = {}
for i, m in enumerate(REBAL):
    nxt = REBAL[i + 1] if i + 1 < len(REBAL) else months[-1]
    seg = [mm for mm in months if m < mm <= nxt]
    if not seg:
        continue
    fwd[m] = {}
    for code in ret_m.columns:
        prod = 1.0
        for mm in seg:
            v = ret_m.loc[mm, code]
            if not np.isnan(v):
                prod *= (1 + v)
        fwd[m][code] = prod - 1

# 每月因子截面 z -> IC (个股 fwd)
def factor_ic(m):
    """返回 {factor: rankIC(z vs 个股fwd)}"""
    out = {}
    fw = fwd.get(m)
    if fw is None:
        return {f: np.nan for f in FACTORS}
    for f in FACTORS:
        z = {cd: cache[m][cd][f] for cd in cache[m] if not np.isnan(cache[m][cd][f])}
        if len(z) < 100:
            out[f] = np.nan
            continue
        df = pd.DataFrame({"z": pd.Series(z), "fwd": pd.Series(fw)}).dropna()
        if len(df) < 100:
            out[f] = np.nan
            continue
        out[f] = df["z"].rank().corr(df["fwd"].rank())
    return out

# 每年 5 月决策: 过去 5 年调仓点 IC 均值 -> top3
selected = {}   # {5月年份: top3 因子}
for m in REBAL:
    if m % 100 != 5:
        continue
    y = m // 100
    win = [mm for mm in REBAL if y * 100 - 500 <= mm < m]   # 过去5年
    ic_sum = {f: [] for f in FACTORS}
    for mm in win:
        ic = factor_ic(mm)
        for f in FACTORS:
            if not np.isnan(ic.get(f, np.nan)):
                ic_sum[f].append(ic[f])
    avg = {f: np.mean(v) if len(v) >= 8 else np.nan for f, v in ic_sum.items()}
    top3 = sorted(FACTORS, key=lambda f: -avg[f] if not np.isnan(avg[f]) else 1e9)[:3]
    selected[y] = top3
    print(f"  {y}年5月决策(窗口{y-5}-{y-1}): IC均值 { {f: round(avg[f],3) for f in FACTORS} } -> 选 {top3}", flush=True)

# 滚动策略: 每年5月后到次年5月用该年构成
score_roll = {}
for m in months:
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2   # 当年5月起用当年决策
    key = y if m % 100 >= 5 else y - 1      # 5月后用该年决策; 1-4月用去年决策
    if m % 100 < 5:
        key = y - 1
    if key not in selected:
        continue
    score_roll[m] = (selected[key],)
r_roll = bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, keys=score_roll.get(m, FIXED)[0], min_valid=2),
                         months, ret_m, topn=TOP, rebal_every="quarter")
p_roll_is = sub_perf(r_roll["returns"], 201401, 201812)
p_roll_oos = sub_perf(r_roll["returns"], 201901)
print(f"  滚动 IS: 夏普 {p_roll_is['夏普']:.3f} | 滚动 OOS: 夏普 {p_roll_oos['夏普']:.3f}", flush=True)
print(f"  OOS 对比: 固定 {p_oos['夏普']:.3f} vs 滚动 {p_roll_oos['夏普']:.3f}", flush=True)

# ---------- C. 指数趋势风控 (HS300 MA12) ----------
print("\n=== C. 指数趋势风控 (HS300 月线 MA12) ===", flush=True)
idx_px = {int(k): v for k, v in idx.items()}
idx_seq = sorted(idx_px.keys())
ma12 = {}
for i, m in enumerate(idx_seq):
    if i >= 11:
        ma12[m] = np.mean([idx_px[idx_seq[j]] for j in range(i - 11, i + 1)])
# 信号: 决策日月末 (m-1) 价 < MA12(m-1) -> 风控
sig = {}
for m in months:
    y, mo = m // 100, m % 100
    dm = m - 1 if mo > 1 else (y - 1) * 100 + 12   # 上月(跨年)
    pv = idx_px.get(dm)
    mv = ma12.get(dm)
    sig[m] = (pv < mv) if pv and mv else None

r_core = r_fixed
core_s = pd.Series(r_core, index=months)
for name, frac in [("降仓50%", 0.5), ("清仓", 0.0)]:
    r_f = np.array([r * frac if sig.get(mm) else r for r, mm in zip(r_core, months)])
    p = bt.perf(r_f)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | Calmar {p['Calmar']:.3f}", flush=True)
    # 熊市检验
    for bname, lo, hi in [("2018", 201801, 201812), ("2022", 202201, 202212)]:
        f_s = pd.Series(r_f, index=months)
        seg_f = f_s[(f_s.index >= lo) & (f_s.index <= hi)]
        seg_c = core_s[(core_s.index >= lo) & (core_s.index <= hi)]
        print(f"    {bname}熊市: 风控累计 {(1+seg_f).prod()-1:+.1%} vs 无风控 {(1+seg_c).prod()-1:+.1%}", flush=True)

# 触发统计
trig = sum(1 for m in months if sig.get(m))
print(f"\n  趋势信号触发月数: {trig}/{len(months)} ({trig/len(months)*100:.0f}%)")

# 保存
pd.DataFrame({"month": months, "fixed_core": r_fixed, "roll_core": r_roll["returns"]}).to_csv(
    "mx_fin_data/p0_walkforward.csv", index=False)
print("\n已存 mx_fin_data/p0_walkforward.csv")
