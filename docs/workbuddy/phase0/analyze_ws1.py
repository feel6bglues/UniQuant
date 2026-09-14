# -*- coding: utf-8 -*-
"""WS1 分析: mootdx 面板 -> PIT 对齐 IC/IR + 牛熊拆分 + 2024-02 压力测试
读 mx_fin_data/factor_panel_ws1.csv + monthly_prices.json + index_monthly.json
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

# ---------- 载入 ----------
panel = pd.read_csv("mx_fin_data/factor_panel_ws1.csv", index_col=0)
panel.index = panel.index.astype(str).str.zfill(6)   # CSV 往返丢前导零, 补回
panel["period"] = panel["period"].astype(str)
monthly = json.load(open("mx_fin_data/monthly_prices.json"))
idx = json.load(open("mx_fin_data/index_monthly.json"))
print(f"面板: {panel.shape}, 月线股票: {len(monthly)}, 指数月点: {len(idx)}")

# ---------- 1. 因子_t -> 次年收益 (PIT 近似: 年报次年可用, 用次年全年收益) ----------
# 收益计算: 从 12 月末收盘到次年 12 月末收盘
def ret_next(monthly_map, code, y):
    px = {int(k): v for k, v in monthly_map.get(code, {}).items()}
    p0 = px.get(y * 100 + 12)
    p1 = px.get((y + 1) * 100 + 12)
    if p0 and p1:
        return p1 / p0 - 1.0
    return np.nan

rows = []
for _, r in panel.iterrows():
    code = r.name
    y = int(r["period"][:4])
    if y >= 2024:      # 2024 年报 -> 2025 收益, 有数据
        pass
    rows.append({
        "code": code, "year": y, "period": r["period"],
        "roe": r.get("roe"), "np": r.get("np"), "fcf": r.get("fcf"),
        "fcf_ps": r.get("fcf_ps"), "eps": r.get("eps"), "shares": r.get("shares"),
        "np_gr": r.get("np_gr"), "equity": r.get("equity"), "assets": r.get("assets"),
        "sales": r.get("sales"),
        "ret_next": ret_next(monthly, code, y),
    })
df = pd.DataFrame(rows)
df = df.dropna(subset=["ret_next"])
print(f"有收益样本: {len(df)} (15只 x {df['year'].nunique()}年)")

# 派生因子
df["ep"] = df["eps"] / 12   # 简化: 用年末价? 下面用月线价格重算
# 用年末月线价格算 EP/FCFyield/DY
px_end = {}
for code in BASKET:
    m = {int(k): v for k, v in monthly.get(code, {}).items()}
    for y in YEARS:
        p = m.get(y * 100 + 12)
        if p:
            px_end[(code, y)] = p
df["px"] = df.apply(lambda r: px_end.get((r["code"], r["year"])), axis=1)
df["mcap"] = df["px"] * df["shares"]
df["ep"] = df["eps"] / df["px"]
df["fcfy"] = df["fcf"] / df["mcap"]
df["dy"] = df["np"].abs() * 0.3 / df["mcap"]   # 30% 分红率近似 (无派息数据, 占位)

# SUE: 净利润同比 -> 截面标准化
df["sue_raw"] = df["np_gr"]
print("\n=== 因子覆盖 ===")
print(df[["roe", "ep", "fcfy", "dy", "sue_raw"]].notna().mean().round(3).to_string())

# ---------- 2. 逐期截面 rank IC ----------
def rank_ic(factor_col, year):
    sub = df[df["year"] == year][["code", factor_col, "ret_next"]].dropna()
    if len(sub) < 5:
        return np.nan, len(sub)
    ic = sub[factor_col].rank().corr(sub["ret_next"].rank())
    return ic, len(sub)

factors = {"ROE": "roe", "EP": "ep", "FCF_Yield": "fcfy", "SUE": "sue_raw", "DY": "dy",
           "合成(等权z)": "composite"}
# 合成因子: 截面 z-score 等权
df["composite"] = np.nan
for y in YEARS:
    sub = df[df["year"] == y].copy()
    zs = []
    for f in ["roe", "ep", "fcfy", "sue_raw"]:
        z = (sub[f] - sub[f].mean()) / sub[f].std()
        zs.append(z)
    comp = pd.concat(zs, axis=1).mean(axis=1)
    df.loc[sub.index, "composite"] = comp

ic_rows = []
for y in sorted(df["year"].unique()):
    row = {"year": y}
    for label, col in factors.items():
        ic, n = rank_ic(col, y)
        row[label] = ic
    ic_rows.append(row)
ic_df = pd.DataFrame(ic_rows).set_index("year")
ic_df.to_csv("mx_fin_data/ic_matrix_ws1.csv", encoding="utf-8-sig")

print("\n=== 逐期 rank IC ===")
print(ic_df.round(3).to_string())

# ---------- 3. IC 汇总 ----------
print("\n=== IC 汇总 (meanIC / IC_std / IR) ===")
summ = []
for label, col in factors.items():
    ics = ic_df[label].dropna()
    if len(ics):
        mean_ic, std_ic, ir = ics.mean(), ics.std(), ics.mean() / ics.std() if ics.std() else np.nan
        summ.append({"因子": label, "meanIC": round(mean_ic, 4), "IC_std": round(std_ic, 4),
                     "IR": round(ir, 3), "n": len(ics)})
summ_df = pd.DataFrame(summ)
print(summ_df.to_string(index=False))
summ_df.to_csv("mx_fin_data/ic_summary_ws1.csv", index=False, encoding="utf-8-sig")

# ---------- 4. 牛熊拆分 (上证指数年度收益) ----------
idx_y = {}
for ym, v in idx.items():
    y = int(str(ym)[:4])
    if int(str(ym)[4:6]) == 12:
        idx_y[y] = v
idx_ret = {y: idx_y.get(y + 1, np.nan) / idx_y.get(y, np.nan) - 1 for y in sorted(idx_y) if idx_y.get(y + 1)}

print("\n=== 牛熊拆分 (指数年度涨跌) ===")
regime = {}
for y in sorted(df["year"].unique()):
    r = idx_ret.get(y + 1, np.nan)   # 收益年
    regime[y] = "牛" if r > 0.05 else ("熊" if r < -0.05 else "震荡")
df["regime"] = df["year"].map(regime)
print(pd.Series(regime).to_string())

regime_sum = []
for label, col in factors.items():
    for rg in ["牛", "熊", "震荡"]:
        yrs = [y for y, v in regime.items() if v == rg]
        ics = [rank_ic(col, y)[0] for y in yrs]
        ics = [x for x in ics if not np.isnan(x)]
        if ics:
            regime_sum.append({"因子": label, "regime": rg, "meanIC": round(np.mean(ics), 4),
                               "n": len(ics)})
regime_df = pd.DataFrame(regime_sum)
print("\n=== 牛熊拆分 IC ===")
print(regime_df.pivot(index="因子", columns="regime", values="meanIC").round(4).to_string())
regime_df.to_csv("mx_fin_data/ic_regime_ws1.csv", index=False, encoding="utf-8-sig")

# ---------- 5. 2024-02 压力测试 (月度收益对齐 2024-02 前因子) ----------
print("\n=== 2024-02 压力测试 (2024-02 当月收益 vs 2023 年报因子) ===")
stress = []
for code in BASKET:
    m = {int(k): v for k, v in monthly.get(code, {}).items()}
    p_jan = m.get(202401)
    p_feb = m.get(202402)
    if p_jan and p_feb:
        r = df[(df["code"] == code) & (df["year"] == 2023)]
        if len(r):
            stress.append({"code": code, "ret_202402": p_feb / p_jan - 1,
                           "roe": r.iloc[0]["roe"], "fcfy": r.iloc[0]["fcfy"], "ep": r.iloc[0]["ep"]})
sdf = pd.DataFrame(stress)
if len(sdf):
    sdf.to_csv("mx_fin_data/stress_202402.csv", index=False, encoding="utf-8-sig")
    print(f"样本: {len(sdf)} 只")
    for f in ["roe", "ep", "fcfy"]:
        ic, _ = sdf[f].rank().corr(sdf["ret_202402"].rank()), len(sdf)
        print(f"  {f} rankIC(2024-02) = {ic:.4f}")
    print("  高ROE组平均收益:", sdf[sdf['roe'] > sdf['roe'].median()]['ret_202402'].mean().round(4),
          "| 低ROE组:", sdf[sdf['roe'] <= sdf['roe'].median()]['ret_202402'].mean().round(4))

print("\nDONE")
