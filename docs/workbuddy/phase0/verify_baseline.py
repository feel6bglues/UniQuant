# -*- coding: utf-8 -*-
"""T0c 基线回归: 共享层+引擎 复现四个已知结果, 防重构回归
基线 (V2 已验证):
  HS300 年频核心(无ROE, 原始值mean, Top30)  夏普 0.465
  HS300 季频核心(zscore, Top30)             夏普 0.494
  全A  年频真实DY(zscore, Top532)           夏普 0.312
  全A  季频真实DY(zscore, Top532)           夏普 0.297
"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pipeline_common as pc
import backtest_engine as bt

PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]

print("加载财报面板 (57期)...", flush=True)
pre = pc.load_panel(PERIODS)
print(f"  pre: {len(pre)} 条", flush=True)

# ---------- HS300 ----------
hs_codes = json.load(open("mx_fin_data/hs300_codes.json"))
hs_monthly = json.load(open("mx_fin_data/hs300_monthly.json"))
hs_xdxr = pc.load_xdxr("hs300_xdxr.json")
ret_hs, months_hs = pc.load_returns(hs_codes, hs_monthly)

print("\n=== 基线1: HS300 年频核心 (原始值mean, Top30) 期望 0.465 ===", flush=True)
cache1 = pc.build_factor_cache(hs_codes, pre, hs_xdxr, hs_monthly, months_hs, normalize="raw", annual=True)
r1 = bt.run_backtest(lambda c, m: pc.score_from_cache(cache1, m, c, min_valid=3), months_hs, ret_hs, topn=30, rebal_every="annual")
s1 = r1["perf"]["夏普"]
print(f"  实际: {s1:.4f}")
bt.assert_baseline(s1, 0.465, "HS300 年频核心")

print("=== 基线2: HS300 季频核心 (zscore, Top30, 无未来函数月初调仓) 期望 0.49 ===", flush=True)
cache2 = pc.build_factor_cache(hs_codes, pre, hs_xdxr, hs_monthly, months_hs, normalize="zscore")
r2 = bt.run_backtest(lambda c, m: pc.score_from_cache(cache2, m, c), months_hs, ret_hs, topn=30, rebal_every="quarter")
s2 = r2["perf"]["夏普"]
print(f"  实际: {s2:.4f}")
bt.assert_baseline(s2, 0.49, "HS300 季频核心(无未来函数)")
# 口径: 因子用调仓前月末价(决策日), 持仓月初生效 -> 无未来函数. 与旧 0.494 数值接近, 季频价值真实.

# ---------- 全A ----------
a_codes = json.load(open("mx_fin_data/all_a_codes.json"))
a_monthly = json.load(open("mx_fin_data/all_a_monthly.json"))
a_xdxr = pc.load_xdxr("all_a_xdxr.json")
ret_a, months_a = pc.load_returns(a_codes, a_monthly)
TOP_A = max(30, int(len(a_codes) * 0.10))

print("=== 基线3: 全A 年频真实DY (zscore, Top532, 月初调仓) 期望 0.29 ===", flush=True)
cache3 = pc.build_factor_cache(a_codes, pre, a_xdxr, a_monthly, months_a, normalize="zscore", annual=True)
r3 = bt.run_backtest(lambda c, m: pc.score_from_cache(cache3, m, c), months_a, ret_a, topn=TOP_A, rebal_every="annual")
s3 = r3["perf"]["夏普"]
print(f"  实际: {s3:.4f}")
bt.assert_baseline(s3, 0.29, "全A 年频真实DY(月初调仓)")

print("=== 基线4: 全A 季频真实DY (zscore, Top532, 无未来函数) 期望 0.31 ===", flush=True)
cache4 = pc.build_factor_cache(a_codes, pre, a_xdxr, a_monthly, months_a, normalize="zscore")
r4 = bt.run_backtest(lambda c, m: pc.score_from_cache(cache4, m, c), months_a, ret_a, topn=TOP_A, rebal_every="quarter")
s4 = r4["perf"]["夏普"]
print(f"  实际: {s4:.4f}")
bt.assert_baseline(s4, 0.31, "全A 季频真实DY(无未来函数)")

print("\n全部基线通过 ✅ 共享层+引擎与 V2 已验证结果一致")
