# -*- coding: utf-8 -*-
"""WS2 多策略回测: 核心(基本面 质量×价值×红利) + 卫星(动量 + 低波) 低相关组合
数据口径: 15 只龙头 × 2010-2024 年报因子 + 月线 2009-2026 (mootdx)
调仓: 核心年频(每年5月用上一年报, PIT 合理), 卫星月频
组合: 核心50% + 动量25% + 低波25% (另对比等权 1/3)
对比: 单因子 Top5 策略 / 15 只等权 / 上证指数
"""
import sys
import io
import os
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

BASKET = ["600519", "000858", "601318", "600036", "000333", "002594", "600900",
          "601012", "000001", "600276", "603259", "300750", "600030", "000651", "601888"]
YEARS = list(range(2010, 2025))
RF = 0.02   # 无风险利率 2%
TOP_N = 5

# ---------- 载入 ----------
panel = pd.read_csv("mx_fin_data/factor_panel_ws1.csv", index_col=0)
panel.index = panel.index.astype(str).str.zfill(6)
panel["period"] = panel["period"].astype(str)
monthly = json.load(open("mx_fin_data/monthly_prices.json"))
idx = json.load(open("mx_fin_data/index_monthly.json"))
xdxr = json.load(open("mx_fin_data/xdxr_cache.json"))   # 真实除权除息

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# 月度收益矩阵
def build_ret_matrix():
    months = sorted({int(k) for c in BASKET for k in monthly[c].keys()})
    months = [m for m in months if m >= 201401]   # 动量需 13 个月历史, 样本期从 2014 起
    ret = {}
    for c in BASKET:
        px = {int(k): v for k, v in monthly[c].items()}
        seq = [px.get(m) for m in months]
        r = [np.nan]
        for i in range(1, len(seq)):
            if seq[i] and seq[i-1]:
                r.append(seq[i] / seq[i-1] - 1)
            else:
                r.append(np.nan)
        ret[c] = r
    return months, pd.DataFrame(ret, index=months)

months, ret_m = build_ret_matrix()
print(f"样本期: {months[0]} ~ {months[-1]} 共 {len(months)} 个月")

# ---------- 因子准备 (PIT: 年报 t -> 次年5月起持有) ----------
# 每年 5 月调仓, 用上一年报 (t-1 年报因子, 4月底前披露)
factor_y = {}   # {调仓年: {code: {roe,ep,fcfy,dy_approx,dy_real}}}
for y in YEARS:
    sub = panel[panel["period"] == f"{y}1231"]
    d = {}
    for code, r in sub.iterrows():
        px = {int(k): v for k, v in monthly.get(code, {}).items()}.get(y * 100 + 12)
        if not px:
            continue
        mcap = px * r["shares"]
        d[code] = {
            "roe": r["roe"],
            "ep": r["eps"] / px,
            "fcfy": r["fcf"] / mcap if mcap else np.nan,
            "dy_approx": r["np"] * 0.3 / mcap if mcap else np.nan,   # 30%分红率近似
            "dy_real": year_dps(code, y) / px if px else np.nan,     # 真实股息率 xdxr
        }
    factor_y[y] = d

def core_score(code, y, use_real_dy=True):
    """质量(ROE) × 价值(EP×FCFY) × 红利(DY) 等权 z 合成"""
    f = factor_y.get(y, {}).get(code)
    if not f:
        return np.nan
    dy_key = "dy_real" if use_real_dy else "dy_approx"
    vals = {k: f.get(k) for k in ["roe", "ep", "fcfy", dy_key]}
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals.values()):
        return np.nan
    return np.nanmean([vals["roe"], vals["ep"], vals["fcfy"], vals[dy_key]])

def core_score_boosted(code, y):
    """增强核心: ROE + EP + 2×DY真实 (去 FCFY——WS3 证明无独立增量; DY 双倍权重——真实DY 最强因子)"""
    f = factor_y.get(y, {}).get(code)
    if not f:
        return np.nan
    vals = [f.get("roe"), f.get("ep"), f.get("dy_real")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return np.nan
    return np.nanmean([f["roe"], f["ep"], 2 * f["dy_real"]])

# ---------- 策略收益 ----------
def top5_ret(score_fn, months):
    """每月: 取当月有分值的股票 Top5 等权 -> 下月收益"""
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan)
            continue
        sc = {c: score_fn(c, m) for c in BASKET}
        sc = {c: v for c, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < TOP_N:
            out.append(np.nan)
            continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP_N]
        rs = [ret_m.loc[months[i], c] for c in top if not np.isnan(ret_m.loc[months[i], c])]
        out.append(np.mean(rs) if rs else np.nan)
    return out

def core_score_m(code, m, use_real_dy=True):
    """核心: 调仓年 = 上年 (5月调仓). 若当月<5月用再上年报"""
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    f = factor_y.get(fy, {})
    if code not in f:
        return np.nan
    return core_score(code, fy, use_real_dy=use_real_dy)

def core_score_m_boosted(code, m):
    y = m // 100
    fy = y - 1 if m % 100 >= 5 else y - 2
    f = factor_y.get(fy, {})
    if code not in f:
        return np.nan
    return core_score_boosted(code, fy)

def mom_score(code, m):
    """12-1 动量: 过去12个月收益 (跳过最近1月)"""
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    p_old = px.get(m // 100 * 100 - 100 + (m % 100))   # m 减 12 个月
    p_prev = px.get(m - 1)
    if not p_old or not p_prev:
        return np.nan
    # 更稳妥: 用 index 定位
    ks = sorted(px.keys())
    try:
        i_cur = ks.index(m)
    except ValueError:
        return np.nan
    if i_cur < 13:
        return np.nan
    p_12 = px.get(ks[i_cur - 13])
    p_1 = px.get(ks[i_cur - 2])
    if not p_12 or not p_1:
        return np.nan
    return p_1 / p_12 - 1

def lowvol_score(code, m):
    """低波: 过去12个月月收益 std 的相反数"""
    ks = sorted({int(k) for k in monthly[code].keys()})
    try:
        i_cur = ks.index(m)
    except ValueError:
        return np.nan
    if i_cur < 13:
        return np.nan
    px = {int(k): v for k, v in monthly[code].items()}
    seq = [px.get(k) for k in ks[i_cur-13:i_cur]]
    if any(not p for p in seq):
        return np.nan
    r = [seq[j+1]/seq[j]-1 for j in range(len(seq)-1)]
    return -np.std(r)

# 计算各策略月度收益 (核心分真实DY / 近似DY / 增强DY 三版对比)
core_ret_real = top5_ret(lambda c, m: core_score_m(c, m, use_real_dy=True), months)
core_ret_approx = top5_ret(lambda c, m: core_score_m(c, m, use_real_dy=False), months)
core_ret_boosted = top5_ret(core_score_m_boosted, months)
mom_ret = top5_ret(mom_score, months)
lowvol_ret = top5_ret(lowvol_score, months)

# 单因子策略 (对比): 每年年报因子选 Top5 持有次年 (年频)
def single_factor_ret(fk, months):
    out = []
    for i, m in enumerate(months):
        if i == 0:
            out.append(np.nan)
            continue
        y = m // 100
        fy = y - 1 if m % 100 >= 5 else y - 2
        d = factor_y.get(fy, {})
        sc = {c: v.get(fk) for c, v in d.items() if v.get(fk) is not None and not np.isnan(v.get(fk))}
        if len(sc) < TOP_N:
            out.append(np.nan)
            continue
        top = sorted(sc, key=sc.get, reverse=True)[:TOP_N]
        rs = [ret_m.loc[months[i], c] for c in top if not np.isnan(ret_m.loc[months[i], c])]
        out.append(np.mean(rs) if rs else np.nan)
    return out

# 基准: 15只等权 + 上证指数
eq_ret = ret_m[BASKET].mean(axis=1).values
idx_ret_series = []
for m in months:
    px = {int(k): v for k, v in idx.items()}
    ks = sorted(px.keys())
    try:
        i_cur = ks.index(m)
    except ValueError:
        idx_ret_series.append(np.nan)
        continue
    if i_cur == 0:
        idx_ret_series.append(np.nan)
    else:
        p0, p1 = px[ks[i_cur-1]], px[m]
        idx_ret_series.append(p1/p0 - 1 if p0 and p1 else np.nan)
idx_ret = np.array(idx_ret_series)

# 组合: 核心50% + 动量25% + 低波25% (仅当月三者都有数据) — 真实DY版/近似DY版/增强DY版
comb50_real = np.array([0.5*c + 0.25*mom + 0.25*lv if not any(np.isnan([c, mom, lv])) else np.nan
                        for c, mom, lv in zip(core_ret_real, mom_ret, lowvol_ret)])
comb33_real = np.array([(c + mom + lv)/3 if not any(np.isnan([c, mom, lv])) else np.nan
                        for c, mom, lv in zip(core_ret_real, mom_ret, lowvol_ret)])
comb50_approx = np.array([0.5*c + 0.25*mom + 0.25*lv if not any(np.isnan([c, mom, lv])) else np.nan
                          for c, mom, lv in zip(core_ret_approx, mom_ret, lowvol_ret)])
comb33_approx = np.array([(c + mom + lv)/3 if not any(np.isnan([c, mom, lv])) else np.nan
                          for c, mom, lv in zip(core_ret_approx, mom_ret, lowvol_ret)])
comb50_boosted = np.array([0.5*c + 0.25*mom + 0.25*lv if not any(np.isnan([c, mom, lv])) else np.nan
                           for c, mom, lv in zip(core_ret_boosted, mom_ret, lowvol_ret)])
comb33_boosted = np.array([(c + mom + lv)/3 if not any(np.isnan([c, mom, lv])) else np.nan
                           for c, mom, lv in zip(core_ret_boosted, mom_ret, lowvol_ret)])

strategies = {
    "核心_真实DY": core_ret_real,
    "核心_近似DY": core_ret_approx,
    "核心_增强DY": core_ret_boosted,
    "卫星_动量(25%)": mom_ret,
    "卫星_低波(25%)": lowvol_ret,
    "组合50/25/25_真实DY": comb50_real,
    "组合等权1/3_真实DY": comb33_real,
    "组合50/25/25_近似DY": comb50_approx,
    "组合等权1/3_近似DY": comb33_approx,
    "组合50/25/25_增强DY": comb50_boosted,
    "组合等权1/3_增强DY": comb33_boosted,
    "单因子_ROE": single_factor_ret("roe", months),
    "单因子_EP": single_factor_ret("ep", months),
    "单因子_FCFY": single_factor_ret("fcfy", months),
    "单因子_DY真实": single_factor_ret("dy_real", months),
    "单因子_DY近似": single_factor_ret("dy_approx", months),
    "基准_15只等权": eq_ret,
    "基准_上证指数": idx_ret,
}

# ---------- 绩效指标 ----------
def perf(r):
    r = pd.Series(r).dropna()
    if len(r) < 12:
        return None
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    ann_ret = nav.iloc[-1] ** (1 / yrs) - 1
    ann_vol = r.std() * np.sqrt(12)
    sharpe = (ann_ret - RF) / ann_vol if ann_vol > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    calmar = ann_ret / abs(dd) if dd < 0 else np.nan
    return {"年化收益": ann_ret, "年化波动": ann_vol, "夏普": sharpe,
            "最大回撤": dd, "Calmar": calmar, "月数": len(r), "期末净值": nav.iloc[-1]}

metrics = {k: perf(v) for k, v in strategies.items()}
mdf = pd.DataFrame({k: v for k, v in metrics.items() if v}).T
mdf = mdf.round(4)
mdf.to_csv("mx_fin_data/ws2_metrics.csv", encoding="utf-8-sig")
print("\n=== 绩效对比 (样本期 2014-01~2026-08) ===")
print(mdf.to_string())

# ---------- 相关性 ----------
corr_df = pd.DataFrame({k: pd.Series(v) for k, v in strategies.items()}).corr()
corr_df.round(3).to_csv("mx_fin_data/ws2_corr.csv", encoding="utf-8-sig")
print("\n=== 核心 vs 卫星 相关性 ===")
print(corr_df.loc[["核心_真实DY", "核心_近似DY", "卫星_动量(25%)", "卫星_低波(25%)", "组合等权1/3_真实DY"],
                  ["核心_真实DY", "核心_近似DY", "卫星_动量(25%)", "卫星_低波(25%)"]].round(3).to_string())

# ---------- 净值序列 ----------
nav_df = pd.DataFrame({"month": months})
for k, v in strategies.items():
    s = pd.Series(v)
    nav_df[k] = (1 + s).cumprod().round(4)
nav_df.to_csv("mx_fin_data/ws2_nav.csv", index=False, encoding="utf-8-sig")
print("\n净值已存 ws2_nav.csv")
print("DONE")
