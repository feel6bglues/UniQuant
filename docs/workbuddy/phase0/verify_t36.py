# -*- coding: utf-8 -*-
"""独立核验 T36 容量结论: 统一NaN处理 + 收益/波动/夏普分解 + 权重集中度"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pipeline_common as pc

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
cache = pc.build_factor_cache(ALL_CODES, pre, xdxr_all, a_monthly, months, normalize="zscore", include_ep=True)
dvol = {}
for code, mm in a_ohlcv.items():
    dvol[code] = {int(ym): v["amount"] / 20 for ym, v in mm.items() if v.get("amount")}
REBAL = [m for m in months if m % 100 in (5, 9, 11)]
CAP = 0.003

def top_holdings(m):
    sc = {cd: pc.score_from_cache(cache, m, cd, keys=("cash", "fcfy", "ep"), min_valid=2) for cd in ALL_CODES}
    sc = {cd: v for cd, v in sc.items() if v is not None and not np.isnan(v)}
    if len(sc) < TOP:
        return []
    return sorted(sc, key=sc.get, reverse=True)[:TOP]

def run(S):
    """统一 NaN 处理: 权重按有效股票归一化 (丢弃NaN)"""
    rets = []
    for m in REBAL:
        top = top_holdings(m)
        if not top:
            continue
        N = len(top)
        w_eq = 1.0 / N
        amt = S / N
        ws = []
        for cd in top:
            if S == 0:
                ws.append(w_eq)
                continue
            capv = CAP * dvol.get(cd, {}).get(m, 0)
            ws.append(min(w_eq, capv / S) if capv else w_eq)
        ws = np.array(ws)
        idx = REBAL.index(m)
        nxt = REBAL[idx + 1] if idx + 1 < len(REBAL) else months[-1]
        seg = [mm for mm in months if m <= mm < nxt]
        for mm in seg:
            r_row = np.array([ret_m.loc[mm, cd] for cd in top])
            mask = ~np.isnan(r_row)
            if mask.sum() == 0:
                continue
            ww = ws[mask]
            ww = ww / ww.sum()
            rets.append((ww * r_row[mask]).sum())
    return np.array(rets)

def stats(r):
    nav = np.cumprod(1 + r)
    yrs = len(r) / 12
    ar = nav[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    return ar, vol, (ar - 0.02) / vol, len(r)

print("=== 独立核验 T36 (统一丢弃NaN, 分解) ===", flush=True)
for S, label in [(0, "等权"), (1e7, "0.1亿"), (1e8, "1.0亿"), (1e9, "10亿")]:
    r = run(S)
    ar, vol, sh, n = stats(r)
    print(f"  {label:<6} 年化 {ar*100:5.1f}% | 波动 {vol*100:5.1f}% | 夏普 {sh:.3f} | 月数 {n}", flush=True)

print("\n=== 权重集中度 (10亿) ===", flush=True)
for m in REBAL[:6]:
    top = top_holdings(m)
    if not top:
        continue
    S = 1e9
    N = len(top)
    ws = np.array([min(1 / N, CAP * dvol.get(cd, {}).get(m, 0) / S) if dvol.get(cd, {}).get(m, 0) else 1 / N for cd in top])
    ws = ws / ws.sum()
    hhi = (ws ** 2).sum()
    eff_n = 1 / hhi
    print(f"  {m}: HHI {hhi:.4f} | 有效持仓 {eff_n:.0f} 只 (名义 {N})", flush=True)
