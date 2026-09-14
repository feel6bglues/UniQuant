# -*- coding: utf-8 -*-
"""T36 容量与冲击建模 (月线近似版先行, 日线就绪后校准)
规则: 单票买入额 <= 0.3% × 日均成交额 (月amount/20)
资金规模 S: 1千万 / 5千万 / 1亿 / 5亿 / 10亿
每调仓期: 等权 Top532, 权重截断 -> 实际可投资金 + cap加权收益 vs 等权
输出: 容量-夏普曲线, 截断票数, 资金上限
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
a_ohlcv = json.load(open("mx_fin_data/all_a_ohlcv.json"))
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
KEYS = ("cash", "fcfy", "ep")
CAP_PCT = 0.003   # 0.3% 日成交
TRADING_DAYS = 20

cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)
print("缓存就绪", flush=True)

# 月日均成交额: {code: {ym: 日均amount}}
dvol = {}
for code, mm in a_ohlcv.items():
    dvol[code] = {int(ym): v["amount"] / TRADING_DAYS for ym, v in mm.items() if v.get("amount")}

REBAL = [m for m in months if m % 100 in (5, 9, 11)]
SCALES = [1e7, 5e7, 1e8, 5e8, 1e9]

def top_holdings(m):
    sc = {cd: pc.score_from_cache(cache, m, cd, keys=KEYS, min_valid=2) for cd in ALL_CODES}
    sc = {cd: v for cd, v in sc.items() if v is not None and not np.isnan(v)}
    if len(sc) < TOP:
        return []
    return sorted(sc, key=sc.get, reverse=True)[:TOP]

print("\n=== T36 容量测算 (单票<=0.3%日均成交, 季频调仓) ===", flush=True)
results = []
for S in SCALES:
    cap_rets = []
    trunc_total = 0
    per_hold_cap = []
    for m in REBAL:
        top = top_holdings(m)
        if not top:
            continue
        N = len(top)
        w_eq = 1.0 / N
        amt_per = S / N
        ws, cap_ok = [], 0
        for code in top:
            dv = dvol.get(code, {}).get(m, 0)
            cap = CAP_PCT * dv            # 单票可买金额上限
            if cap >= amt_per:
                ws.append(w_eq)
                cap_ok += 1
            else:
                ws.append(cap / S)        # 截断
                trunc_total += 1
        ws = np.array(ws) / np.sum(ws)    # 归一化
        # 持有: 含调仓月(月初执行) 到下个调仓点
        idx = REBAL.index(m)
        nxt = REBAL[idx + 1] if idx + 1 < len(REBAL) else months[-1]
        seg = [mm for mm in months if m <= mm < nxt]
        for mm in seg:
            rs = np.array([ret_m.loc[mm, cd] for cd in top])
            rs = np.where(np.isnan(rs), 0.0, rs)
            cap_rets.append(np.sum(ws * rs))
    p = bt.perf(np.array(cap_rets))
    trunc_ratio = trunc_total / (len(REBAL) * TOP)
    results.append({"资金": S / 1e8, "夏普": p["夏普"], "年化": p["年化收益"],
                    "回撤": p["最大回撤"], "截断率": trunc_ratio})
    print(f"  {S/1e8:.1f}亿: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | 截断票 {trunc_ratio*100:.0f}%", flush=True)

# 参考: 等权无限制
eq_rets = []
for m in REBAL:
    top = top_holdings(m)
    if not top:
        continue
    idx = REBAL.index(m)
    nxt = REBAL[idx + 1] if idx + 1 < len(REBAL) else months[-1]
    seg = [mm for mm in months if m <= mm < nxt]
    for mm in seg:
        rs = [ret_m.loc[mm, cd] for cd in top if not np.isnan(ret_m.loc[mm, cd])]
        if rs:
            eq_rets.append(np.mean(rs))
p_eq = bt.perf(np.array(eq_rets))
print(f"\n  等权无限制参考: 夏普 {p_eq['夏普']:.3f} | 年化 {p_eq['年化收益']*100:.1f}%", flush=True)

pd.DataFrame(results).to_csv("mx_fin_data/t36_capacity.csv", index=False)
print("已存 mx_fin_data/t36_capacity.csv")
