# -*- coding: utf-8 -*-
"""WS3 FCF 因子深挖: FCF 是质量/红利的进化版还是换皮?
1) 真实股息率重建 (xdxr 除权除息)
2) 因子相关性: FCFyield vs ROE/EP/DY/现金含量
3) FCF 正交化: 控制 ROE+EP+DY 后残差因子 IC/IR (核心验证)
4) 双变量分组: ROE×FCFyield 四象限次年收益
5) 结论
数据: 15 只龙头 × 2010-2024 年报 (mootdx gpcw) + 月线 + xdxr
"""
import sys
import io
import os
import json
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

BASKET = ["600519", "000858", "601318", "600036", "000333", "002594", "600900",
          "601012", "000001", "600276", "603259", "300750", "600030", "000651", "601888"]
YEARS = list(range(2010, 2025))

# ---------- 1. 拉真实分红 (xdxr) ----------
print("=== [1] 拉取 xdxr 除权除息 (15 只) ===")
from mootdx.quotes import Quotes
qc = Quotes.factory(market="std", timeout=20)

xdxr_cache = "mx_fin_data/xdxr_cache.json"
if os.path.exists(xdxr_cache):
    div_by_code = json.load(open(xdxr_cache))
    print("  用缓存:", len(div_by_code), "只")
else:
    div_by_code = {}
    for i, code in enumerate(BASKET):
        try:
            df = qc.xdxr(symbol=code)
            recs = []
            if df is not None and len(df):
                for _, r in df.iterrows():
                    if r["category"] == 1 and r["fenhong"] and r["fenhong"] > 0:
                        recs.append({"year": int(r["year"]), "dps": float(r["fenhong"]) / 10.0})  # 每10股->每股
            div_by_code[code] = recs
            print(f"  [{i+1}/15] {code}: {len(recs)} 次派息", flush=True)
        except Exception as e:
            print(f"  [{i+1}/15] {code} 失败: {e}", flush=True)
        time.sleep(0.8)
    json.dump(div_by_code, open(xdxr_cache, "w"))
print("  示例 600519 派息(元/股):", [(r["year"], round(r["dps"], 2)) for r in div_by_code["600519"][-8:]])

# ---------- 2. 面板 + 真实 DY ----------
print("\n=== [2] 因子面板 + 真实 DY ===")
panel = pd.read_csv("mx_fin_data/factor_panel_ws1.csv", index_col=0)
panel.index = panel.index.astype(str).str.zfill(6)
panel["period"] = panel["period"].astype(str)
monthly = json.load(open("mx_fin_data/monthly_prices.json"))

def year_dps(code, y):
    return sum(r["dps"] for r in div_by_code.get(code, []) if r["year"] == y)

rows = []
for _, r in panel.iterrows():
    code = r.name
    y = int(r["period"][:4])
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    p_end = px.get(y * 100 + 12)
    p_next = px.get((y + 1) * 100 + 12)
    if not p_end or not p_next:
        continue
    mcap = p_end * r["shares"]
    dps = year_dps(code, y)
    rows.append({
        "code": code, "year": y,
        "roe": r["roe"],
        "ep": r["eps"] / p_end,
        "fcfy": r["fcf"] / mcap if mcap else np.nan,
        "dy": dps / p_end if p_end else np.nan,             # 真实股息率
        "fcf_ps": r["fcf_ps"],
        "np": r["np"],
        "ocf": r.get("ocf", np.nan),
        "cash_content": r.get("ocf", np.nan) / r["np"] if r["np"] and r["np"] > 0 else np.nan,  # 现金含量 OCF/净利润
        "ret_next": p_next / p_end - 1,
    })
df = pd.DataFrame(rows)
df = df.dropna(subset=["ret_next"])
print(f"样本: {len(df)} (15只 x {df['year'].nunique()}年)")
print("真实DY样本(非NaN):", df["dy"].notna().sum(), "| 茅台近年DY:",
      [round(v, 4) for v in df[df["code"] == "600519"]["dy"].dropna().tail(5)])

# ---------- 3. 因子相关性 (逐年均值) ----------
print("\n=== [3] 因子截面相关性 (逐年均值) ===")
fcols = ["roe", "ep", "fcfy", "dy", "cash_content"]
corr_sum = []
for y in sorted(df["year"].unique()):
    sub = df[df["year"] == y][fcols].dropna()
    if len(sub) >= 5:
        c = sub.corr(method="spearman")
        corr_sum.append(c)
avg_corr = pd.concat(corr_sum).groupby(level=0).mean()
avg_corr = pd.concat([avg_corr.iloc[[i]].groupby(level=0).mean() for i in range(len(avg_corr))])
print("FCFyield 与各因子平均秩相关:")
for f in fcols:
    print(f"  FCFyield vs {f:14s} = {avg_corr.loc['fcfy', f]:.3f}")
print("\n全相关矩阵:")
print(avg_corr.round(3).to_string())
avg_corr.round(3).to_csv("mx_fin_data/ws3_corr.csv", encoding="utf-8-sig")

# ---------- 4. FCF 正交化: 残差因子 IC/IR ----------
print("\n=== [4] FCF 正交化 (控制 ROE/EP/DY 后残差) ===")
def yearly_resid(y, controls):
    sub = df[df["year"] == y][["fcfy"] + controls].dropna()
    if len(sub) < 6:
        return None
    X = sub[controls].values
    yv = sub["fcfy"].values
    # 最小二乘残差 (带截距)
    Xd = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xd, yv, rcond=None)
    resid = yv - Xd @ beta
    return pd.Series(resid, index=sub.index)

def ortho_ic(controls, label):
    ics = []
    for y in sorted(df["year"].unique()):
        resid = yearly_resid(y, controls)
        if resid is None:
            continue
        sub = df.loc[resid.index]
        if len(sub) < 5:
            continue
        ic = resid.rank().corr(sub["ret_next"].rank())
        ics.append(ic)
    ics = pd.Series(ics).dropna()
    if len(ics) >= 5:
        return {"控制": label, "meanIC": ics.mean(), "IR": ics.mean() / ics.std() if ics.std() else np.nan, "n": len(ics)}
    return None

ortho_rows = [ortho_ic(["roe"], "FCF 控制ROE"),
              ortho_ic(["roe", "ep"], "FCF 控制ROE+EP"),
              ortho_ic(["roe", "ep", "dy"], "FCF 控制ROE+EP+DY"),
              ortho_ic(["roe", "dy"], "FCF 控制ROE+DY")]
ortho_df = pd.DataFrame([r for r in ortho_rows if r])
print(ortho_df.round(4).to_string(index=False))
ortho_df.to_csv("mx_fin_data/ws3_ortho.csv", index=False, encoding="utf-8-sig")

# 对照: 各因子原始 IC
print("\n各因子原始 IC 对照:")
raw_ics = {}
for f in fcols:
    ics = []
    for y in sorted(df["year"].unique()):
        sub = df[df["year"] == y][[f, "ret_next"]].dropna()
        if len(sub) >= 5:
            ics.append(sub[f].rank().corr(sub["ret_next"].rank()))
    s = pd.Series(ics).dropna()
    raw_ics[f] = s.mean()
    print(f"  {f:14s}: meanIC={s.mean():.4f} IR={s.mean()/s.std() if s.std() else np.nan:.3f}")

# ---------- 5. 双变量分组: ROE × FCFyield ----------
print("\n=== [5] 双变量分组 (ROE中位 × FCFyield中位) 次年平均收益 ===")
gp_rows = []
for y in sorted(df["year"].unique()):
    sub = df[df["year"] == y][["roe", "fcfy", "ret_next"]].dropna()
    if len(sub) < 8:
        continue
    roe_med, fcf_med = sub["roe"].median(), sub["fcfy"].median()
    for rl, rh in [(True, True), (True, False), (False, True), (False, False)]:
        sel = sub[sub["roe"] > roe_med] if rl else sub[sub["roe"] <= roe_med]
        sel = sel[sel["fcfy"] > fcf_med] if rh else sel[sel["fcfy"] <= fcf_med]
        if len(sel):
            gp_rows.append({"year": y, "roe_hi": rl, "fcf_hi": rh, "ret": sel["ret_next"].mean()})
gp = pd.DataFrame(gp_rows)
pt = gp.pivot_table(index="roe_hi", columns="fcf_hi", values="ret", aggfunc="mean")
pt.index = ["ROE低", "ROE高"]
pt.columns = ["FCF低", "FCF高"]
print("四象限次年平均收益 (15年均值):")
print(pt.round(4).to_string())
print(f"  FCF 在 ROE高组内增量: {(pt.loc['ROE高','FCF高']-pt.loc['ROE高','FCF低'])*100:.2f}pp")
print(f"  FCF 在 ROE低组内增量: {(pt.loc['ROE低','FCF高']-pt.loc['ROE低','FCF低'])*100:.2f}pp")
print(f"  ROE 在 FCF高组内增量: {(pt.loc['ROE高','FCF高']-pt.loc['ROE低','FCF高'])*100:.2f}pp")

# 增量显著性: 逐年 FCF 组内差
gp["fcf_inc"] = gp.groupby(["year", "roe_hi"])["ret"].transform(lambda x: x - x.iloc[::-1].iloc[0]) if False else np.nan
inc_rows = []
for y in gp["year"].unique():
    for roe_hi in [True, False]:
        sub = gp[(gp["year"] == y) & (gp["roe_hi"] == roe_hi)]
        if len(sub) == 2:
            d = sub[sub["fcf_hi"] == True]["ret"].iloc[0] - sub[sub["fcf_hi"] == False]["ret"].iloc[0]
            inc_rows.append({"year": y, "roe_hi": roe_hi, "inc": d})
inc = pd.DataFrame(inc_rows)
print("\nFCF 组内增量(逐年, pp):")
for rh, label in [(True, "ROE高组"), (False, "ROE低组")]:
    s = inc[inc["roe_hi"] == rh]["inc"] * 100
    print(f"  {label}: 均值 {s.mean():.2f}pp, t≈{s.mean()/(s.std()/np.sqrt(len(s))) if s.std() else np.nan:.2f}")

df.to_csv("mx_fin_data/ws3_panel.csv", encoding="utf-8-sig")
print("\nDONE")
