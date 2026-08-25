"""P3 — 逻辑驱动因子方向族 Walk-Forward 测试 (v2: 含动量残差 + 复合因子)。

测试 8 个新因子 (加 neg_range_20d) + 2 基线正因子, 504/63 窗, 500 只 × 1600d。
增加:
  - 动量残差校验 (P2 同款: 残差化 IC + 剔右尾 IC)
  - 复合因子组合 (等权组合通过因子)

用法:
    python3 scripts/factor_mining/run_logic_factor_test.py          # sample 500
    python3 scripts/factor_mining/run_logic_factor_test.py --full   # 全量
    python3 scripts/factor_mining/run_logic_factor_test.py --smoke  # sample 100
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from uniquant.brain.factors.analyzer import FactorAnalyzer  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.brain.factors.walk_forward_pipeline import (  # noqa: E402
    WalkForwardFactorPipeline,
)
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.logic_factor_test")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "logic_factor_test.json"

NEW_FACTORS = [
    "max_ret_20d", "reversal_1d", "amivest_20d", "range_20d",
    "skew_20d", "reversal_5d", "reversal_20d", "neg_range_20d",
]
BASELINE_POSITIVE = ["illiq_20d", "idiosyncratic_vol_20d"]

EXPECTED_DIRECTION = {
    "max_ret_20d": -1, "reversal_1d": 1, "amivest_20d": -1, "range_20d": 1,
    "skew_20d": -1, "reversal_5d": 1, "reversal_20d": 1, "neg_range_20d": 1,
    "illiq_20d": 1, "idiosyncratic_vol_20d": 1,
}

# 反彩票族 (用于复合因子)
ANTI_LOTTERY = ["max_ret_20d", "skew_20d", "neg_range_20d", "idiosyncratic_vol_20d"]


def _make_factor_func():
    composer = FactorComposer()
    def _func(df: pd.DataFrame) -> pd.DataFrame:
        out = composer.compute_all_factors(df, mode="backtest")
        result = df.copy()
        for col in out.columns:
            result[col] = out[col].to_numpy()
        return result
    return _func


def block_bootstrap_pbo(oos_ics: list, n_bootstrap: int = 2000) -> float:
    arr = np.array(oos_ics)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 5:
        return 1.0
    rng = np.random.RandomState(42)
    best_idx = int(np.argmax(arr))
    block_size = max(1, int(n / 5))
    n_blocks = int(np.ceil(n / block_size))
    worse = 0
    for _ in range(n_bootstrap):
        blocks = rng.choice(n_blocks, size=n_blocks, replace=True)
        boot = np.concatenate([arr[i * block_size: (i + 1) * block_size] for i in blocks])[:n]
        if np.max(boot[:best_idx + 1] if best_idx < len(boot) else boot) >= arr[best_idx]:
            worse += 1
    return worse / n_bootstrap


def _daily_spearman_ic(f: pd.Series, r: pd.Series) -> float:
    valid = f.notna() & r.notna()
    if valid.sum() < 20 or f[valid].nunique() < 2 or r[valid].nunique() < 2:
        return 0.0
    fv, rv = f[valid].to_numpy(), r[valid].to_numpy()
    n = len(fv)
    fr = pd.Series(fv).rank().to_numpy()
    rr = pd.Series(rv).rank().to_numpy()
    num = n * float(np.dot(fr, rr)) - float(fr.sum()) * float(rr.sum())
    den = np.sqrt((n * float(np.dot(fr, fr)) - float(fr.sum()) ** 2) * (n * float(np.dot(rr, rr)) - float(rr.sum()) ** 2))
    return num / den if den > 1e-12 else 0.0


def _daily_ic_series_for_window(panel: pd.DataFrame, factor_col: str, fwd_col: str, mom_col: str) -> dict:
    """窗口内逐日 IC 计算: raw, residualized, trimmed."""
    raw_ics, res_ics, tail_ics = [], [], []
    for d, g in panel.groupby(level=1):
        f = g[factor_col].dropna()
        r = g[fwd_col].dropna()
        m = g[mom_col].dropna()
        common = f.index.intersection(r.index).intersection(m.index)
        if len(common) < 20:
            continue
        ff, rr, mm = f.loc[common], r.loc[common], m.loc[common]
        ff_r = ff.rank()  # 横截面秩
        rr_r = rr.rank()
        mm_r = mm.rank()
        raw = _spearman_from_ranks(ff_r, rr_r)
        if raw is None:
            continue
        raw_ics.append(raw)
        # residualized: regress factor_rank on momentum_rank
        fv, mv = ff_r.to_numpy(), mm_r.to_numpy()
        if mv.var() > 1e-12:
            beta = np.cov(fv, mv)[0, 1] / mv.var()
            res = fv - beta * mv
            res_r = pd.Series(res).rank().to_numpy()
            rr_arr = rr_r.to_numpy()
            n = len(res_r)
            num = n * float(np.dot(res_r, rr_arr)) - float(res_r.sum()) * float(rr_arr.sum())
            den = np.sqrt((n * float(np.dot(res_r, res_r)) - float(res_r.sum()) ** 2) * (n * float(np.dot(rr_arr, rr_arr)) - float(rr_arr.sum()) ** 2))
            res_ics.append(num / den if den > 1e-12 else 0.0)
        # trimmed: remove top 10% momentum
        th = np.quantile(mv, 0.9)
        keep = mv <= th
        if keep.sum() >= 20:
            keep_ff = ff_r[keep]
            keep_rr = rr_r[keep]
            kf = keep_ff.to_numpy()
            kr = keep_rr.to_numpy()
            nk = len(kf)
            num = nk * float(np.dot(kf, kr)) - float(kf.sum()) * float(kr.sum())
            den = np.sqrt((nk * float(np.dot(kf, kf)) - float(kf.sum()) ** 2) * (nk * float(np.dot(kr, kr)) - float(kr.sum()) ** 2))
            tail_ics.append(num / den if den > 1e-12 else 0.0)
    return {"raw": raw_ics, "res": res_ics, "tail": tail_ics}


def _spearman_from_ranks(fr: pd.Series, rr: pd.Series) -> float | None:
    fv, rv = fr.to_numpy(), rr.to_numpy()
    n = len(fv)
    num = n * float(np.dot(fv, rv)) - float(fv.sum()) * float(rv.sum())
    den = np.sqrt((n * float(np.dot(fv, fv)) - float(fv.sum()) ** 2) * (n * float(np.dot(rv, rv)) - float(rv.sum()) ** 2))
    return num / den if den > 1e-12 else None


def run_test(load_sample: int, full: bool, max_workers: int = 32):
    t0 = time.time()

    df = load_universe(as_of="2026-05-29", max_workers=max_workers)
    if not full:
        codes = sorted(df["code"].unique())
        rng = np.random.RandomState(42)
        selected = rng.choice(codes, size=min(load_sample, len(codes)), replace=False)
        df = df[df["code"].isin(selected)].reset_index(drop=True)
        logger.info(f"采样 {len(selected)} 只 (seed=42)")

    lookback = 1600
    if df["date"].nunique() > lookback:
        cutoff = df["date"].sort_values().unique()[-lookback]
        df = df[df["date"] >= cutoff].reset_index(drop=True)
        logger.info(f"回看截断: {str(cutoff)[:10]} 起 ({lookback} 交易日)")

    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].nunique()} 天, {len(df):,} 行")

    # 构建面板 (row-wise 计算用 code 列分组)
    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])
    panel["fwd5"] = panel["close"].groupby(level=0).pct_change(-5, fill_method=None).shift(-5)  # forward 5d
    panel["mom20"] = panel["close"].groupby(level=0).pct_change(20, fill_method=None)

    factor_func = _make_factor_func()

    # 预计算因子值 (一次, 供动量残差校验复用)
    logger.info("预计算因子值...")
    all_factors = factor_func(df)
    factor_col_names = [c for c in all_factors.columns if c not in ["date", "code", "close"]]
    for col in factor_col_names:
        panel[col] = all_factors[col].to_numpy()

    # 运行 Walk-Forward
    analyzer = FactorAnalyzer()
    composer = FactorComposer()
    pipeline = WalkForwardFactorPipeline(
        factor_analyzer=analyzer, factor_composer=composer,
        train_window=504, test_window=63, min_train_days=252,
    )
    result = pipeline.run(df, factor_cols=None, factor_func=factor_func,
                          date_col="date", code_col="code", price_col="close")

    # 提取每因子 OOS IC
    test_factors = NEW_FACTORS + [n for n in BASELINE_POSITIVE if n not in NEW_FACTORS]
    per_factor = {}
    for name in test_factors:
        ic_vals = []
        for w in result.windows:
            ic = w.ic_mean.get(name, None)
            if ic is not None and np.isfinite(ic):
                ic_vals.append(ic)
        if not ic_vals:
            continue
        oos_mean = float(np.mean(ic_vals))
        oos_std = float(np.std(ic_vals))
        icir = oos_mean / max(oos_std, 1e-10)
        pbo = block_bootstrap_pbo(ic_vals)
        exp_dir = EXPECTED_DIRECTION.get(name, 0)
        correct_sign = (oos_mean > 0 and exp_dir > 0) or (oos_mean < 0 and exp_dir < 0)
        per_factor[name] = {
            "oos_ic_mean": round(oos_mean, 4), "oos_ic_std": round(oos_std, 4),
            "oos_icir": round(icir, 4), "pbo": round(pbo, 4),
            "n_windows": len(ic_vals),
            "expected_direction": exp_dir, "correct_sign": bool(correct_sign),
            "passed_ic": bool(abs(oos_mean) > 0.01),
            "passed_icir": bool(abs(icir) > 0.5),
            "passed_pbo": bool(pbo < 0.2),
            "passed_all": bool(abs(oos_mean) > 0.01 and abs(icir) > 0.5 and pbo < 0.2 and correct_sign),
        }

    # ─── 动量残差校验 (窗口级, 复用预计算因子) ─────────────────────────────
    for name in test_factors:
        d = per_factor.get(name, {})
        if not d:
            continue
        raw_all, res_all, tail_all, ctl_pos = [], [], [], 0
        n_windows = 0
        for w in result.windows:
            sub = panel[(panel.index.get_level_values(1) >= w.test_start) &
                        (panel.index.get_level_values(1) <= w.test_end)].copy()
            if sub.empty or name not in sub.columns:
                continue
            daily = _daily_ic_series_for_window(sub, name, "fwd5", "mom20")
            n_windows += 1
            if daily["raw"]:
                raw_all.extend(daily["raw"])
            if daily["res"]:
                res_all.extend(daily["res"])
                ctl_pos += (np.mean(daily["res"]) > 0)
            if daily["tail"]:
                tail_all.extend(daily["tail"])
        if raw_all:
            _ = float(np.mean(raw_all))
            res_m = float(np.mean(res_all)) if res_all else 0.0
            tail_m = float(np.mean(tail_all)) if tail_all else 0.0
            ctl_frac = ctl_pos / max(n_windows, 1)
            # 如果预期方向为负, 动量残差 IC 应也为负
            exp_dir = EXPECTED_DIRECTION.get(name, 0)
            if exp_dir < 0:
                res_m = -res_m
                tail_m = -tail_m
                ctl_frac = (n_windows - ctl_pos) / max(n_windows, 1)  # 负方向窗口分数
            d["mom_res_mean"] = round(res_m, 4)
            d["mom_tail_mean"] = round(tail_m, 4)
            d["mom_pos_frac"] = round(ctl_frac, 3)
            d["passed_mom"] = bool(res_m > 0 and tail_m > 0 and ctl_frac >= 2.0 / 3.0)
            # 更新 passed_all (含动量残差门)
            base = d.get("passed_ic", False) and d.get("passed_icir", False) and d.get("passed_pbo", False) and d.get("correct_sign", False)
            d["passed_all"] = bool(base and d["passed_mom"])

    # ─── 复合因子 ──────────────────────────────────────────────────────────
    passing = [n for n in ANTI_LOTTERY if n in per_factor and per_factor[n].get("passed_all")]
    if passing:
        logger.info(f"复合因子: {passing}")
        comp_ics = []
        for w in result.windows:
            sub = panel[(panel.index.get_level_values(1) >= w.test_start) &
                        (panel.index.get_level_values(1) <= w.test_end)].copy()
            if sub.empty or not all(n in sub.columns for n in passing):
                continue
            # z-score 每因子每日横截面, 等权平均
            daily_comp_ics = []
            for d, g in sub.groupby(level=1):
                scores = []
                for n in passing:
                    f = sub[n].loc[g.index]
                    if f.notna().sum() < 20:
                        continue
                    z = (f - f.mean()) / f.std()
                    scores.append(z)
                if len(scores) < 2:
                    continue
                composite = pd.concat(scores, axis=1).mean(axis=1)
                fwd = g["fwd5"]
                ic = _daily_spearman_ic(composite, fwd)
                if ic != 0.0:
                    daily_comp_ics.append(ic)
            if daily_comp_ics:
                comp_ics.append(float(np.mean(daily_comp_ics)))
        if comp_ics:
            per_factor["_composite"] = {
                "oos_ic_mean": round(float(np.mean(comp_ics)), 4),
                "oos_ic_std": round(float(np.std(comp_ics)), 4),
                "oos_icir": round(float(np.mean(comp_ics)) / max(float(np.std(comp_ics)), 1e-10), 4),
                "pbo": round(block_bootstrap_pbo(comp_ics), 4),
                "n_windows": len(comp_ics),
                "components": passing,
                "expected_direction": 1,
                "correct_sign": bool(np.mean(comp_ics) > 0),
            }

    # 输出
    print(f"\n{'='*80}")
    print("逻辑驱动因子 Walk-Forward 测试结果 (v2)")
    print(f"{'='*80}")
    print(f"数据: {df['code'].nunique()} 只, {df['date'].nunique()} 天")
    print(f"Walk-Forward: {len(result.windows)} 窗 (504/63)")
    print(f"耗时: {time.time() - t0:.1f}s")
    print(f"\n{'因子':<22} {'OOS IC':>8} {'ICIR':>8} {'PBO':>8} {'窗数':>6} {'方向':>4} {'IC✓':>5} {'IR✓':>5} {'PBO✓':>5} {'MOM✓':>6} {'ALL✓':>5}")
    print(f"{'-'*90}")
    for name in test_factors + (["_composite"] if "_composite" in per_factor else []):
        d = per_factor.get(name, {})
        if not d:
            print(f"{name:<22} {'—':>8} {'—':>8} {'—':>8} {'0':>6} {'—':>4} {'—':>5} {'—':>5} {'—':>5} {'—':>6} {'—':>5}")
            continue
        ic = d["oos_ic_mean"]
        icir = d["oos_icir"]
        pbo = d["pbo"]
        nw = d["n_windows"]
        sign = "+" if d.get("correct_sign", False) else "✗"
        ic_p = "✓" if d.get("passed_ic", False) else "✗"
        ir_p = "✓" if d.get("passed_icir", False) else "✗"
        pbo_p = "✓" if d.get("passed_pbo", False) else "✗"
        mom_p = "✓" if d.get("passed_mom", False) else "—"
        all_p = "✓" if d.get("passed_all", False) else "✗"
    
        print(f"{name:<22} {ic:>+8.4f} {icir:>+8.2f} {pbo:>8.3f} {nw:>6} {sign:>4} {ic_p:>5} {ir_p:>5} {pbo_p:>5} {mom_p:>6} {all_p:>5}")
        if name.startswith("_"):
            comps = d.get("components", [])
            print(f"  {'':>22} 组件: {comps}")

    print(f"\n{'='*80}")

    report = {
        "_meta": {
            "n_symbols": int(df["code"].nunique()),
            "n_days": int(df["date"].nunique()),
            "as_of": "2026-05-29", "lookback_days": lookback,
            "sample": not full, "n_windows": len(result.windows),
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "per_factor": per_factor,
        "summary": {
            "n_tested": len(test_factors),
            "n_passed_all": sum(1 for d in per_factor.values() if d.get("passed_all")),
            "n_passed_ic": sum(1 for d in per_factor.values() if d.get("passed_ic")),
            "n_passed_icir": sum(1 for d in per_factor.values() if d.get("passed_icir")),
            "n_passed_pbo": sum(1 for d in per_factor.values() if d.get("passed_pbo")),
            "n_passed_mom": sum(1 for d in per_factor.values() if d.get("passed_mom")),
            "n_correct_sign": sum(1 for d in per_factor.values() if d.get("correct_sign")),
        },
    }
    out_path = Path(DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告 → {out_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="逻辑驱动因子方向族 Walk-Forward 测试 (v2)")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=32)
    args = parser.parse_args()
    sample = args.sample if args.sample is not None else (100 if args.smoke else 500)
    run_test(load_sample=sample, full=args.full, max_workers=args.max_workers)


if __name__ == "__main__":
    main()