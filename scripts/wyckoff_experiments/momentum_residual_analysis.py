#!/usr/bin/env python3
"""动量残差研究：剥离 20d 相对动量后，leader∧distribution 是否仍具稳健增量

研究问题：WYCKOFF_FIX_REDBLUE_20260809.md 对抗暴露——leader∧dist 可能只是
20d 相对动量因子 (relmom = stk_ret_20d - idx_ret_20d) 的皮肤。

方法（三窗 W1/W2/W3 as-of 回放）：
  M1 分位残差: 按 relmom 10 分位分桶，桶内比较 leader∧dist vs 桶内其他；
               跨桶加权 = 控制动量后的纯增量（相位门的独立信息）
  M2 OLS 残差 : fwd_20d ~ relmom（+ 平方项），系数自由拟合后取残差
               leader∧dist 残差均值 vs 全池 = 非线性剥离后的相位增量
  M3 独有子集 : leader∧dist 中不属于 relmom-top10% 的部分（相位独有凭据）
  M4 双因子   : relmom 分位 × leader 分组 fwd 网格

输入: data/lake/quotes/daily/*.parquet + results/wyckoff_xs*/scan CSV
用法: python3 scripts/wyckoff_experiments/momentum_residual_analysis.py
"""
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from _symbols import is_index_symbol  # noqa: E402

DAILY = "data/lake/quotes/daily"
INDEX = "000300.SH"
AN = 13 ** 0.5

ASOFS = {"W1": "2026-04-30", "W2": "2026-03-31", "W3": "2026-05-29"}
SCANS = {
    "W1": "results/wyckoff_xs/wyckoff_scan_all.csv",
    "W2": "results/wyckoff_xs2/wyckoff_scan_all.csv",
    "W3": "results/wyckoff_xs3/wyckoff_scan_all.csv",
}


def sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    if len(x) < 2 or float(x.std()) == 0:
        return 0.0
    return float(x.mean() / x.std() * AN)


def load_index(which: str = INDEX) -> pd.DataFrame:
    p = os.path.join(DAILY, f"{which}.parquet")
    idx = pd.read_parquet(p)
    idx["date"] = pd.to_datetime(idx["date"])
    return idx.set_index("date").sort_index()


def load_cache() -> dict[str, pd.DataFrame]:
    """一次性加载全部股票日线, 缓存复用三窗"""
    cache: dict[str, pd.DataFrame] = {}
    for f in os.listdir(DAILY):
        if not f.endswith(".parquet"):
            continue
        sym = f[: -8]
        try:
            d = pd.read_parquet(os.path.join(DAILY, f))
            if "date" in d.columns:
                d["date"] = pd.to_datetime(d["date"])
            cache[sym] = d
        except Exception:
            continue
    return cache


def relmom_for(sym: str, cache: dict[str, pd.DataFrame], asof: pd.Timestamp, idx_close: pd.Series) -> float:
    d = cache.get(sym)
    if d is None or len(d) < 21:
        return np.nan
    sub = d[d["date"] <= asof]
    if len(sub) < 21:
        return np.nan
    stk = float(sub["close"].iloc[-1] / sub["close"].iloc[-21] - 1)
    ib = idx_close[idx_close.index <= asof]
    if len(ib) < 21:
        return np.nan
    ir = float(ib["close"].iloc[-1] / ib["close"].iloc[-21] - 1)
    return stk - ir


def quantile_strat(df: pd.DataFrame, nq: int = 10) -> float:
    """M1: relmom 分位桶内 leader∧dist vs 桶内其他, 跨桶加权"""
    df = df.copy()
    df["q"] = pd.qcut(df["relmom"], nq, labels=False, duplicates="drop")
    tot_effect = 0.0
    tot_n = 0
    rows = []
    for q, g in df.groupby("q"):
        sig = g[(g["relative_strength"] == "leader") & (g["phase"] == "distribution")]
        if len(sig) < 5 or len(g) - len(sig) < 5:
            continue
        other = g[~((g["relative_strength"] == "leader") & (g["phase"] == "distribution"))]
        effect = sig["fwd_20d"].mean() - other["fwd_20d"].mean()
        w = len(sig)
        tot_effect += effect * w
        tot_n += w
        rows.append({"q": q, "n_sig": len(sig), "n_other": len(other), "effect": effect})
    return (tot_effect / tot_n if tot_n else np.nan), rows


def ols_resid(df: pd.DataFrame) -> tuple[float, float, int]:
    """M2: fwd_20d ~ relmom + relmom^2, leader∧dist 残差均值 vs 全池残差 (MWU)"""
    d = df[["fwd_20d", "relmom"]].dropna().copy()
    x = np.column_stack([np.ones(len(d)), d["relmom"], d["relmom"] ** 2]).astype(float)
    y = d["fwd_20d"].astype(float).to_numpy()
    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        resid_by_sym = dict(zip(d.index.tolist(), resid))
        sig_idx = df.index[df["relative_strength"] == "leader"]
        w2 = df[df["phase"] == "distribution"]
        sig_idx2 = set(w2.index)
        sig_idx = [i for i in sig_idx if i in sig_idx2 and i in resid_by_sym]
        resid_sig = np.array([resid_by_sym[i] for i in sig_idx])
        resid_all = np.array([r for r in resid_by_sym.values()])
        if len(resid_sig) > 5:
            from scipy.stats import mannwhitneyu

            _, p = mannwhitneyu(resid_sig, resid_all)
            return float(resid_sig.mean()), p, len(resid_sig)
    except Exception:
        pass
    return np.nan, np.nan, 0


def main() -> int:
    print("加载基准指数与全池日线缓存 ...")
    idx = load_index()
    cache = load_cache()
    print(f"缓存股票数: {len(cache)}")

    results = {}
    print("=" * 78)
    print("三窗动量残差研究")
    print("=" * 78)
    for nm, asof_s in ASOFS.items():
        asof = pd.Timestamp(asof_s)
        scan = pd.read_csv(SCANS[nm])
        scan = scan[scan["fwd_20d"].notna() & ~scan["is_etf"].fillna(False) & ~scan["symbol"].map(lambda s: is_index_symbol(str(s)) if pd.notna(s) else False)]
        scan["fwd_20d"] = scan["fwd_20d"].astype(float)
        scan["relmom"] = [relmom_for(s, cache, asof, idx) for s in scan["symbol"]]
        scan = scan[scan["relmom"].notna()].copy()
        scan["exc"] = scan["fwd_20d"] - scan["fwd_20d"].mean()

        ld = scan[scan["relative_strength"] == "leader"]
        ldd = scan[(scan["relative_strength"] == "leader") & (scan["phase"] == "distribution")]

        # M1 分位残差
        m1, m1rows = quantile_strat(scan)
        # M2 OLS 残差
        m2mean, m2p, m2n = ols_resid(scan)
        # M3 独有子集
        th = scan["relmom"].quantile(0.90)
        top = set(scan[scan["relmom"] >= th]["symbol"])
        dedup = ldd[~ldd["symbol"].isin(top)]
        # M4 网格
        scan["q5"] = pd.qcut(scan["relmom"], 5, labels=False, duplicates="drop")

        rho, p_ic = spearmanr(scan["relmom"], scan["fwd_20d"])
        results[nm] = {
            "n": len(scan),
            "ld_n": len(ld),
            "ldd_n": len(ldd),
            "ldd_exc": ldd["exc"].mean(),
            "idc_rm": rho,
            "idc_p": p_ic,
            "m1_weighted": m1,
            "m2_resid": m2mean,
            "m2_p": m2p,
            "m3_dedup_n": len(dedup),
            "m3_dedup_exc": dedup["exc"].mean() if len(dedup) else np.nan,
            "m1rows": m1rows,
        }
        print(f"\n【{nm}】 as-of {asof_s}  池 n={len(scan)}")
        print(f"  leader∧dist: n={len(ldd)}  exc={ldd['exc'].mean():>+.2f}%  sharpe={sharpe(ldd['exc']):.2f}")
        print(f"  relmom IC: {rho:+.3f} (p={p_ic:.2g})")
        print(f"  M1 分位残差(控制动量后相位增量): {m1:+.2f}pp")
        for r in m1rows:
            print(f"      q{r['q']}: n_sig={r['n_sig']:>3} n_other={r['n_other']:>4} effect={r['effect']:>+.2f}pp")
        print(f"  M2 OLS残差(非线性剥离后相位增量): {m2mean:+.2f}pp (n={m2n})")
        print(f"  M3 独有子集(不在relmom-top10): n={len(dedup):>3} exc={dedup['exc'].mean() if len(dedup) else float('nan'):+.2f}%")
        print("  M4 5分位网格(relmom × leader):")
        for q, g in scan.groupby("q5"):
            s_ld = g[g["relative_strength"] == "leader"]
            s_non = g[g["relative_strength"] != "leader"]
            ldstr = f"leader:{s_ld['fwd_20d'].mean():+.2f}(n={len(s_ld)})" if len(s_ld) else "leader:-"
            nonstr = f"non:{s_non['fwd_20d'].mean():+.2f}(n={len(s_non)})" if len(s_non) else "non:-"
            print(f"      q{q}: {ldstr} | {nonstr}")

    save = "/tmp/opencode/momentum_residual_results.json"
    import json

    def clean(x):
        if isinstance(x, (np.floating, float)):
            return float(x)
        if isinstance(x, (np.integer, int)):
            return int(x)
        if isinstance(x, list):
            return [clean(i) for i in x]
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        return x

    with open(save, "w", encoding="utf-8") as f:
        json.dump({k: clean(v) for k, v in results.items()}, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())