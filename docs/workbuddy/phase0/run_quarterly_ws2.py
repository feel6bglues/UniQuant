# -*- coding: utf-8 -*-
"""T22 季频升级: 年频(5月) -> 季频(5/9/11月), TTM 因子, PIT
调仓日历 (财报披露完):
  5 月 -> 上年年报 1231
  9 月 -> 当年中报 0630 (TTM = 0630 + 上年1231 - 上年0630)
  11月 -> 当年三季报 0930 (TTM = 0930 + 上年1231 - 上年0930)
因子: ep_ttm / fcfy_ttm / cash_ttm / dy(真实xdxr) -> 无ROE核心 z-score 等权
用法: python run_quarterly_ws2.py <hs300|all> [--topn 30]
"""
import sys, io, os, json, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from mootdx_client import MootdxClient

ap = argparse.ArgumentParser()
ap.add_argument("universe", choices=["hs300", "all"], default="hs300", nargs="?")
ap.add_argument("--topn", type=int, default=30)
ap.add_argument("--annual", action="store_true", help="年频模式: 仅5月调仓+年报")
args = ap.parse_args()

UNI = args.universe
TOP_N = args.topn if args.universe == "hs300" else max(int(len(json.load(open("mx_fin_data/all_a_codes.json"))) * 0.1), 50)

CODES = json.load(open(f"mx_fin_data/{'hs300' if UNI=='hs300' else 'all_a'}_codes.json"))
monthly = json.load(open(f"mx_fin_data/{'hs300' if UNI=='hs300' else 'all_a'}_monthly.json"))
xdxr_file = "mx_fin_data/hs300_xdxr.json" if UNI == "hs300" else "mx_fin_data/all_a_xdxr.json"
xdxr = json.load(open(xdxr_file)) if os.path.exists(xdxr_file) else {}
print(f"[{UNI}] {len(CODES)} 只 | Top{TOP_N} | xdxr 覆盖 {len(xdxr)} 只 | 季频调仓 5/9/11", flush=True)

# ---------- 财报预加载 (dict 索引, 全A规模性能关键) ----------
PERIODS = []
for y in range(2010, 2025):
    PERIODS.append(f"{y}1231")
    if y >= 2011:
        PERIODS += [f"{y}0331", f"{y}0630", f"{y}0930"]
c = MootdxClient()
NEED = ["eps", "np", "ocf", "capex", "shares", "roe"]
pre = {}
for p in PERIODS:
    fn = f"mx_fin_data/gpcw{p}.csv"
    if not os.path.exists(fn):
        continue
    df = pd.read_csv(fn, index_col=0, dtype=str)
    df.index = df.index.astype(str).str.zfill(6)
    for col in NEED:
        s = c._pick(df, col)
        if s is not None:
            df[col] = pd.to_numeric(s, errors="coerce")
    for code, r in df.iterrows():
        pre[(code, p)] = {k: r.get(k, np.nan) for k in NEED}
print(f"财报缓存: {len(PERIODS)} 期, {len(pre)} 条 (code,period)", flush=True)

def ttm(code, cur_p, year):
    """TTM: 当期累计 + 上年年报 - 上年同期累计"""
    prev_q = f"{year-1}{cur_p[4:]}"
    prev_y = f"{year-1}1231"
    cur = pre.get((code, cur_p))
    if cur is None:
        return None
    pv_q = pre.get((code, prev_q))
    pv_y = pre.get((code, prev_y))
    if cur_p.endswith("1231"):
        return cur  # 年报即 TTM
    if pv_q is None or pv_y is None:
        return None
    out = {}
    for k in ("eps", "np", "ocf", "capex"):
        a, b, cc = cur[k], pv_y[k], pv_q[k]
        if all(isinstance(v, (int, float)) and not np.isnan(v) for v in (a, b, cc)):
            out[k] = a + b - cc
        else:
            out[k] = np.nan
    out["shares"], out["roe"] = cur["shares"], cur["roe"]
    return out

# ---------- 收益矩阵 ----------
months = sorted({int(k) for cc in monthly.values() for k in cc.keys()})
months = [m for m in months if m >= 201401]
ret_m = {}
for code in CODES:
    px = {int(k): v for k, v in monthly.get(code, {}).items()}
    seq = [px.get(m) for m in months]
    r = [np.nan]
    for i in range(1, len(seq)):
        r.append(seq[i] / seq[i - 1] - 1 if seq[i] and seq[i - 1] else np.nan)
    ret_m[code] = r
ret_m = pd.DataFrame(ret_m, index=months)

def year_dps(code, y):
    return sum(r["dps"] for r in xdxr.get(code, []) if r["year"] == y)

# ---------- 调仓点因子 ----------
REBAL = [m for m in months if (m % 100 in (5, 9, 11)) and (m % 100 == 5 or not args.annual)]
def rebal_factors(m):
    """返回 {code: {ep,fcfy,cash,dy}}"""
    y, mo = m // 100, m % 100
    if args.annual or mo == 5:
        cur_p, fy = f"{y-1}1231", y - 1
    elif mo == 9:
        cur_p, fy = f"{y}0630", y
    else:
        cur_p, fy = f"{y}0930", y
    d = {}
    for code in CODES:
        px = {int(k): v for k, v in monthly.get(code, {}).items()}
        p = px.get(m)
        if not p:
            continue
        f = ttm(code, cur_p, y)
        if f is None:
            continue
        mcap = p * f["shares"] if f["shares"] and f["shares"] > 0 else np.nan
        ep = f["eps"] / p if f["eps"] and not np.isnan(f["eps"]) else np.nan
        fcf = f["ocf"] - f["capex"] if not np.isnan(f["ocf"]) else np.nan
        fcfy = fcf / mcap if mcap and not np.isnan(fcf) else np.nan
        cash = f["ocf"] / f["np"] if f["np"] and f["np"] > 0 and not np.isnan(f["ocf"]) else np.nan
        dy = year_dps(code, fy) / p
        if not np.isnan(ep) or not np.isnan(fcfy) or not np.isnan(cash) or not np.isnan(dy):
            d[code] = {"ep": ep, "fcfy": fcfy, "cash": cash, "dy": dy}
    return d

def zscore(codes_dict, key):
    vals = {cd: v[key] for cd, v in codes_dict.items() if v.get(key) is not None and not np.isnan(v.get(key))}
    if len(vals) < 20:
        return {}
    arr = np.array(list(vals.values()))
    mu, sd = arr.mean(), arr.std()
    if sd == 0:
        return {}
    return {cd: (v - mu) / sd for cd, v in vals.items()}

# ---------- 回测 ----------
print(f"\n调仓点: {len(REBAL)} 个 (5/9/11月)", flush=True)
holds = []
for i, m in enumerate(REBAL):
    d = rebal_factors(m)
    zs = {k: zscore(d, k) for k in ("ep", "fcfy", "cash", "dy")}
    score = {}
    for cd in d:
        parts = [zs[k].get(cd) for k in ("fcfy", "cash", "dy")]
        parts = [x for x in parts if x is not None]
        if len(parts) >= 2:
            score[cd] = np.mean(parts)
    if len(score) < TOP_N:
        continue
    top = sorted(score, key=score.get, reverse=True)[:TOP_N]
    # 持有到下个调仓点
    nxt = REBAL[i + 1] if i + 1 < len(REBAL) else months[-1]
    seg = [mm for mm in months if m < mm <= nxt]
    if not seg:
        continue
    for mm in seg:
        rs = [ret_m.loc[mm, x] for x in top if not np.isnan(ret_m.loc[mm, x])]
        holds.append(np.mean(rs) if rs else np.nan)

def perf(r):
    r = pd.Series(r).dropna()
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    ar = nav.iloc[-1] ** (1 / yrs) - 1
    av = r.std() * np.sqrt(12)
    shp = (ar - 0.02) / av if av > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {"年化收益": ar, "年化波动": av, "夏普": shp, "最大回撤": dd,
            "Calmar": ar / abs(dd) if dd else np.nan, "期末净值": nav.iloc[-1]}

q_ret = np.array(holds)
eq = ret_m[CODES].mean(axis=1).values
print(f"\n=== 季频回测 [{UNI}] Top{TOP_N} (无ROE核心: FCFY+现金含量+DY) ===")
for name, r in [("季频核心", q_ret), ("基准等权", eq)]:
    p = perf(r)
    print(f"  {name}: 夏普 {p['夏普']:.3f} | 年化 {p['年化收益']*100:.1f}% | 回撤 {p['最大回撤']*100:.1f}% | Calmar {p['Calmar']:.3f} | 净值 {p['期末净值']:.2f}", flush=True)

pd.DataFrame({"month": months[:len(q_ret)], "quarterly_core": q_ret}).to_csv(f"mx_fin_data/{UNI}_quarterly_ws2.csv", index=False)
print(f"\n已存 mx_fin_data/{UNI}_quarterly_ws2.csv")
