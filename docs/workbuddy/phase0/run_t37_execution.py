# -*- coding: utf-8 -*-
"""T37 执行建模: 停牌/涨跌停实测 + 回测修正
数据: core_pool_daily.json (2545只日线)
Step1 统计: 调仓月(5/9/11)月初 核心持仓 停牌率 / 涨跌停率 (执行乐观度量化)
Step2 修正: 调仓日不可交易股剔除, 可交易池内重选 Top532, 对比绩效
涨跌停判定: 主板 ±9.8%, 创业板300/科创板688 ±19.5%; 停牌 = 当日无成交
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
daily = json.load(open("mx_fin_data/core_pool_daily.json"))
pool = json.load(open("mx_fin_data/core_pool_codes.json"))
print(f"日线池 {len(daily)} 只 | pool {len(pool)} 只", flush=True)

PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
print("加载财报面板...", flush=True)
pre = pc.load_panel(PERIODS)
ret_m, months = pc.load_returns(ALL_CODES, a_monthly)
TOP = max(30, int(len(ALL_CODES) * 0.10))
KEYS = ("cash", "fcfy", "ep")
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)

REBAL = [m for m in months if m % 100 in (5, 9, 11)]

# 调仓日 = 该月第一个有交易的交易日 (全池)
def first_trading_day(m):
    y, mo = m // 100, m % 100
    days = []
    for code, dd in daily.items():
        for d in dd:
            if d[:6] == f"{y}{mo:02d}":
                days.append(d)
                break
    return min(days) if days else None

def tradable_status(code, m):
    """返回: 'ok' | 'suspended'(停牌) | 'limit_up'(涨停不可买) | 'limit_down'(跌停不可卖)
    全历史日线下: 当月无记录 = 真实停牌 (mootdx 跳过停牌日)"""
    dd = daily.get(code, {})
    if not dd:
        return "ok"   # 非池内股票(未拉日线) = 无停牌证据, 可成交
    y, mo = m // 100, m % 100
    pref = f"{y}{mo:02d}"
    days = sorted(d for d in dd if d.startswith(pref))
    if not days:
        return "suspended"   # 池内股票当月无记录 = 真实停牌
    d0 = days[0]
    r = dd[d0]
    if not r.get("v") or r["v"] == 0:
        return "suspended"
    # 涨跌停: 对比前一个交易日
    all_days = sorted(dd.keys())
    i = all_days.index(d0)
    if i == 0:
        return "ok"
    prev_c = dd[all_days[i - 1]]["c"]
    if not prev_c:
        return "ok"
    chg = r["c"] / prev_c - 1
    lim = 0.195 if code[:3] in ("300", "688") else 0.098
    if chg >= lim - 0.002:
        return "limit_up"
    if chg <= -(lim - 0.002):
        return "limit_down"
    return "ok"

def top_holdings(m, tradable_only=False):
    sc = {cd: pc.score_from_cache(cache, m, cd, keys=KEYS, min_valid=2) for cd in ALL_CODES}
    sc = {cd: v for cd, v in sc.items() if v is not None and not np.isnan(v)}
    if len(sc) < TOP:
        return []
    ranked = sorted(sc, key=sc.get, reverse=True)
    if not tradable_only:
        return ranked[:TOP]
    # 可交易池重选: 停牌/涨停剔除, 不足补位
    ok = [cd for cd in ranked if tradable_status(cd, m) in ("ok", "limit_down")]  # 跌停可卖不可买? 买入端: 涨停不可买
    buyable = [cd for cd in ranked if tradable_status(cd, m) in ("ok", "limit_down")]  # 跌停可买
    # 买入视角: 剔除停牌+涨停
    buyable = [cd for cd in ranked if tradable_status(cd, m) == "ok"]
    return buyable[:TOP]

# ---------- Step1: 执行乐观度统计 ----------
print("\n=== T37 Step1: 调仓日执行统计 (2014-2026, 每季3次) ===", flush=True)
stats = {"n": 0, "suspended": 0, "limit_up": 0, "limit_down": 0, "ok": 0}
for m in REBAL:
    top = top_holdings(m)
    if not top:
        continue
    fd = first_trading_day(m)
    if not fd:
        continue
    for cd in top:
        st = tradable_status(cd, m)
        stats[st] = stats.get(st, 0) + 1
        stats["n"] += 1
print(f"  样本: {stats['n']} 个持仓-调仓日观测")
for k in ("ok", "suspended", "limit_up", "limit_down"):
    print(f"  {k:<12}: {stats[k]} ({stats[k]/stats['n']*100:.1f}%)", flush=True)
print(f"  -> 停牌率 {stats['suspended']/stats['n']*100:.1f}% | 涨停(不可买) {stats['limit_up']/stats['n']*100:.1f}% | 跌停(不可卖) {stats['limit_down']/stats['n']*100:.1f}%", flush=True)

# ---------- Step2: 修正回测 (可交易池重选) ----------
print("\n=== T37 Step2: 修正回测 (可交易池重选 vs 无修正) ===", flush=True)
def bt_no_fix():
    return bt.run_backtest(lambda cd, m: pc.score_from_cache(cache, m, cd, keys=KEYS, min_valid=2),
                           months, ret_m, topn=TOP, rebal_every="quarter")["returns"]
def bt_fixed():
    scores = {}
    for m in REBAL:
        buyable = [cd for cd in ALL_CODES if tradable_status(cd, m) == "ok"]
        sc = {cd: pc.score_from_cache(cache, m, cd, keys=KEYS, min_valid=2) for cd in buyable}
        sc = {cd: v for cd, v in sc.items() if v is not None and not np.isnan(v)}
        if len(sc) >= TOP:
            scores[m] = {cd: sc[cd] for cd in sorted(sc, key=sc.get, reverse=True)[:TOP]}
    def score_fn(cd, m):
        s = scores.get(m)
        return 1.0 if s and cd in s else np.nan
    return bt.run_backtest(score_fn, months, ret_m, topn=TOP, rebal_every="quarter")["returns"]

r0 = bt_no_fix()
r1 = bt_fixed()
for name, r in [("无修正 (假设全可成交)", r0), ("修正 (可交易池重选)", r1)]:
    p = bt.perf(r)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | 净值 {p['期末净值']:.2f}", flush=True)
print(f"  执行乐观度代价: 夏普 {bt.perf(r0)['夏普']-bt.perf(r1)['夏普']:+.3f}")

pd.DataFrame({"month": months, "no_fix": r0, "fixed": r1}).to_csv("mx_fin_data/t37_execution.csv", index=False)
print("\n已存 mx_fin_data/t37_execution.csv")
