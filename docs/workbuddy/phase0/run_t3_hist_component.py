# -*- coding: utf-8 -*-
"""T3 历史成分重建 + 幸存者偏差量化
市值代理: 每年年末 全A(5328只) 市值 top300 近似当年 HS300 成分
对比三个口径下同一策略(季频核心 无ROE)的绩效:
  1) 当前 HS300 成分 (固定300)   -> 基线
  2) 历史成分代理 (每年动态 top300) -> 消除成分选择偏差
  3) 全A (5328只, Top532)        -> 规模参照
结论: (2) vs (1) 之差 = 成分选择型幸存者偏差的量级
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import pipeline_common as pc
import backtest_engine as bt

ALL_CODES = json.load(open("mx_fin_data/all_a_codes.json"))
HS_CODES = json.load(open("mx_fin_data/hs300_codes.json"))
a_monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
hs_monthly = json.load(open("mx_fin_data/hs300_monthly.json"))
xdxr_all = pc.load_xdxr("all_a_xdxr.json")
xdxr_hs = pc.load_xdxr("hs300_xdxr.json")
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)

# ---------- 历史成分代理: 每年年末市值 top300 (全A) ----------
px_all = {code: {int(k): v for k, v in m.items()} for code, m in a_monthly.items()}
hist = {}
for y in range(2013, 2025):
    fy_row = pre.get((ALL_CODES[0], f"{y}1231"))
    if fy_row is None:
        continue
    # 该年报的 shares (取全A 面板)
    shares = {}
    for code in ALL_CODES:
        r = pre.get((code, f"{y}1231"))
        if r and r.get("shares") and not np.isnan(r["shares"]):
            px = px_all.get(code, {}).get(y * 100 + 12)
            if px:
                shares[code] = px * r["shares"]
    top = sorted(shares, key=shares.get, reverse=True)[:300]
    hist[y] = top
    print(f"  {y} 年末: 可算市值 {len(shares)} 只 | 近似成分 {len(top)} 只", flush=True)

# ---------- 三口径回测 (季频核心 无ROE: cash+fcfy+dy, zscore) ----------
ret_a, months_a = pc.load_returns(ALL_CODES, a_monthly)
ret_hs, months_hs = pc.load_returns(HS_CODES, hs_monthly)

def build_hist_cache(codes, monthly, xdxr):
    """季频 zscore cache (无未来函数)"""
    return pc.build_factor_cache(codes, pre, xdxr, monthly, months_a if codes is ALL_CODES else months_hs,
                                 normalize="zscore")

print("\n=== 口径1: 当前 HS300 成分 (固定300, Top30) ===", flush=True)
cache_hs = build_hist_cache(HS_CODES, hs_monthly, xdxr_hs)
r1 = bt.run_backtest(lambda cd, m: pc.score_from_cache(cache_hs, m, cd), months_hs, ret_hs, topn=30, rebal_every="quarter")
p1 = r1["perf"]
print(f"  夏普 {p1['夏普']:.3f} | 年化 {p1['年化收益']*100:.1f}% | 回撤 {p1['最大回撤']*100:.1f}% | 净值 {p1['期末净值']:.2f}")

print("=== 口径2: 历史成分代理 (动态 top300, Top30) ===", flush=True)
# 历史成分: 逐调仓月用该年报期的 hist 成分池
cache_a = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months_a, normalize="zscore")
def hist_score(code, m):
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    pool = hist.get(fy)
    if pool is None or code not in pool:
        return np.nan
    return pc.score_from_cache(cache_a, m, code)
r2 = bt.run_backtest(hist_score, months_a, ret_a, topn=30, rebal_every="quarter")
p2 = r2["perf"]
print(f"  夏普 {p2['夏普']:.3f} | 年化 {p2['年化收益']*100:.1f}% | 回撤 {p2['最大回撤']*100:.1f}% | 净值 {p2['期末净值']:.2f}")

print("=== 口径3: 全A (5328只, Top532) ===", flush=True)
TOP_A = max(30, int(len(ALL_CODES) * 0.10))
r3 = bt.run_backtest(lambda cd, m: pc.score_from_cache(cache_a, m, cd), months_a, ret_a, topn=TOP_A, rebal_every="quarter")
p3 = r3["perf"]
print(f"  夏普 {p3['夏普']:.3f} | 年化 {p3['年化收益']*100:.1f}% | 回撤 {p3['最大回撤']*100:.1f}% | 净值 {p3['期末净值']:.2f}")

print("\n=== 幸存者偏差量化 ===")
print(f"  成分选择偏差 (口径2 vs 1): 夏普 {p2['夏普']-p1['夏普']:+.3f} | 年化 {(p2['年化收益']-p1['年化收益'])*100:+.1f}pp")
print(f"  规模/分散 (口径3 vs 1): 夏普 {p3['夏普']-p1['夏普']:+.3f}")

pd.DataFrame({
    "month": months_a, "hist_core": r2["returns"], "all_a_core": r3["returns"],
}).to_csv("mx_fin_data/t3_hist_component.csv", index=False)
print("\n已存 mx_fin_data/t3_hist_component.csv")
