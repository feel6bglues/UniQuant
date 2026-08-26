"""P11 — 基本面价值/质量因子族 Walk-Forward 测试。

预注册冻结于 docs/analysis/FUNDAMENTAL_FACTOR_PREREGISTRATION.md (2026-08-26):
- 7 新因子 (ep_ttm/bp/cfp_ttm/sp_ttm/gross_profitability/accruals/turnover_20d)
  + 2 基线正因子对照 (illiq_20d/idiosyncratic_vol_20d)
- 504/63 窗, 500 只 × 1600d, as-of 2026-05-29, 与 P3 同面板
- 四重门 + 方向 + 动量残差门; 幸存 = 五门全过
- 数据口径: TDX 财务双 TTM 口径 (营收成本单季直滚 / 利润现金流累计差分),
  merge_asof 公告日 PIT 对齐

用法:
    python3 scripts/factor_mining/run_fundamental_factor_test.py            # sample 500
    python3 scripts/factor_mining/run_fundamental_factor_test.py --smoke    # sample 60
    python3 scripts/factor_mining/run_fundamental_factor_test.py --full     # 全市场
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

from scripts.factor_mining.data_loader import (  # noqa: E402
    EXTRA_FINANCIAL_FIELDS,
    load_universe,
    merge_financial_metrics,
)
from uniquant.brain.factors.analyzer import FactorAnalyzer  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.brain.factors.walk_forward_pipeline import (  # noqa: E402
    WalkForwardFactorPipeline,
)
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.fundamental_factor_test")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "fundamental_factor_test.json"

NEW_FACTORS = [
    "ep_ttm", "bp", "cfp_ttm", "sp_ttm",
    "gross_profitability", "accruals", "turnover_20d",
]
BASELINE_POSITIVE = ["illiq_20d", "idiosyncratic_vol_20d"]
TEST_FACTORS = NEW_FACTORS + BASELINE_POSITIVE

# 预注册 §2 冻结方向
EXPECTED_DIRECTION = {
    "ep_ttm": 1, "bp": 1, "cfp_ttm": 1, "sp_ttm": 1,
    "gross_profitability": 1, "accruals": -1, "turnover_20d": -1,
    "illiq_20d": 1, "idiosyncratic_vol_20d": 1,
}

VALUE_TRIO = ["ep_ttm", "bp", "cfp_ttm"]


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
    arr = np.array([x for x in oos_ics if np.isfinite(x)])
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
        boot = np.concatenate(
            [arr[i * block_size: (i + 1) * block_size] for i in blocks]
        )[:n]
        cand = boot[: best_idx + 1] if best_idx < len(boot) else boot
        if len(cand) and np.max(cand) >= arr[best_idx]:
            worse += 1
    return worse / n_bootstrap


def _spearman_from_ranks(fr: pd.Series, rr: pd.Series) -> float | None:
    fv, rv = fr.to_numpy(), rr.to_numpy()
    n = len(fv)
    num = n * float(np.dot(fv, rv)) - float(fv.sum()) * float(rv.sum())
    den = np.sqrt(
        (n * float(np.dot(fv, fv)) - float(fv.sum()) ** 2)
        * (n * float(np.dot(rv, rv)) - float(rv.sum()) ** 2)
    )
    return num / den if den > 1e-12 else None


def _daily_ic_series_for_window(panel: pd.DataFrame, factor_col: str) -> dict:
    """窗口内逐日 IC: raw / momentum 残差化 / 剔右尾。"""
    raw_ics, res_ics, tail_ics = [], [], []
    for _, g in panel.groupby(level=1):
        f = g[factor_col].dropna()
        r = g["fwd5"].dropna()
        m = g["mom20"].dropna()
        common = f.index.intersection(r.index).intersection(m.index)
        if len(common) < 20:
            continue
        ff_r = f.loc[common].rank().to_numpy()
        rr_r = r.loc[common].rank().to_numpy()
        mm_r = m.loc[common].rank().to_numpy()
        raw = _spearman_from_ranks(pd.Series(ff_r), pd.Series(rr_r))
        if raw is None:
            continue
        raw_ics.append(raw)
        mv = mm_r
        if mv.var() > 1e-12:
            beta = np.cov(ff_r, mv)[0, 1] / mv.var()
            res = pd.Series(ff_r - beta * mv).rank().to_numpy()
            n = len(res)
            num = n * float(np.dot(res, rr_r)) - float(res.sum()) * float(rr_r.sum())
            den = np.sqrt(
                (n * float(np.dot(res, res)) - float(res.sum()) ** 2)
                * (n * float(np.dot(rr_r, rr_r)) - float(rr_r.sum()) ** 2)
            )
            res_ics.append(num / den if den > 1e-12 else 0.0)
        th = np.quantile(mv, 0.9)
        keep = mv <= th
        if keep.sum() >= 20:
            kf, kr = ff_r[keep], rr_r[keep]
            nk = len(kf)
            num = nk * float(np.dot(kf, kr)) - float(kf.sum()) * float(kr.sum())
            den = np.sqrt(
                (nk * float(np.dot(kf, kf)) - float(kf.sum()) ** 2)
                * (nk * float(np.dot(kr, kr)) - float(kr.sum()) ** 2)
            )
            tail_ics.append(num / den if den > 1e-12 else 0.0)
    return {"raw": raw_ics, "res": res_ics, "tail": tail_ics}


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

    logger.info("合并财务列 (PIT merge_asof)...")
    df = merge_financial_metrics(
        df, extra_fields=EXTRA_FINANCIAL_FIELDS, max_workers=max_workers
    )

    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].nunique()} 天, {len(df):,} 行")
    for col in ("eps_ttm", "revenue_ttm", "total_assets", "free_float_shares"):
        if col in df.columns:
            cov = float(df[col].notna().mean())
            logger.info(f"  财务列覆盖 {col}: {cov:.1%}")

    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])
    panel["fwd5"] = panel["close"].groupby(level=0).pct_change(-5, fill_method=None).shift(-5)
    panel["mom20"] = panel["close"].groupby(level=0).pct_change(20, fill_method=None)

    factor_func = _make_factor_func()

    logger.info("预计算因子值...")
    all_factors = factor_func(df)
    factor_cols_avail = [c for c in TEST_FACTORS if c in all_factors.columns]
    missing = [c for c in TEST_FACTORS if c not in all_factors.columns]
    if missing:
        logger.warning(f"因子缺失 (财务列未覆盖?): {missing}")
    for col in factor_cols_avail:
        panel[col] = all_factors[col].to_numpy()

    analyzer = FactorAnalyzer()
    composer = FactorComposer()
    pipeline = WalkForwardFactorPipeline(
        factor_analyzer=analyzer, factor_composer=composer,
        train_window=504, test_window=63, min_train_days=252,
    )
    result = pipeline.run(
        df, factor_cols=factor_cols_avail, factor_func=factor_func,
        date_col="date", code_col="code", price_col="close",
    )

    per_factor = {}
    for name in TEST_FACTORS:
        ic_vals = []
        for w in result.windows:
            ic = w.ic_mean.get(name, None)
            if ic is not None and np.isfinite(ic):
                ic_vals.append(ic)
        if not ic_vals:
            per_factor[name] = {"n_windows": 0, "note": "no valid window IC"}
            continue
        oos_mean = float(np.mean(ic_vals))
        oos_std = float(np.std(ic_vals))
        icir = oos_mean / max(oos_std, 1e-10)
        pbo = block_bootstrap_pbo(ic_vals)
        exp_dir = EXPECTED_DIRECTION[name]
        correct_sign = (oos_mean > 0 and exp_dir > 0) or (oos_mean < 0 and exp_dir < 0)
        d = {
            "oos_ic_mean": round(oos_mean, 4), "oos_ic_std": round(oos_std, 4),
            "oos_icir": round(icir, 4), "pbo": round(pbo, 4),
            "n_windows": len(ic_vals),
            "expected_direction": exp_dir, "correct_sign": bool(correct_sign),
            "passed_ic": bool(abs(oos_mean) > 0.01),
            "passed_icir": bool(abs(icir) > 0.5),
            "passed_pbo": bool(pbo < 0.2),
        }
        d["passed_all_base"] = bool(
            d["passed_ic"] and d["passed_icir"] and d["passed_pbo"] and correct_sign
        )
        per_factor[name] = d

    for name in factor_cols_avail:
        d = per_factor.get(name, {})
        if not d or d.get("n_windows", 0) == 0:
            continue
        raw_all, res_all, tail_all, pos_windows = [], [], [], 0
        n_win = 0
        for w in result.windows:
            sub = panel[
                (panel.index.get_level_values(1) >= w.test_start)
                & (panel.index.get_level_values(1) <= w.test_end)
            ]
            if sub.empty or name not in sub.columns:
                continue
            daily = _daily_ic_series_for_window(sub, name)
            n_win += 1
            raw_all.extend(daily["raw"])
            if daily["res"]:
                res_all.extend(daily["res"])
                pos_windows += (np.mean(daily["res"]) > 0)
            tail_all.extend(daily["tail"])
        if raw_all:
            exp_dir = EXPECTED_DIRECTION[name]
            res_m = float(np.mean(res_all)) if res_all else 0.0
            tail_m = float(np.mean(tail_all)) if tail_all else 0.0
            frac_pos = pos_windows / max(n_win, 1)
            if exp_dir < 0:
                res_m, tail_m = -res_m, -tail_m
                frac_pos = 1.0 - frac_pos
            d["mom_res_mean"] = round(res_m, 4)
            d["mom_tail_mean"] = round(tail_m, 4)
            d["mom_pos_frac"] = round(frac_pos, 3)
            d["passed_mom"] = bool(res_m > 0 and tail_m > 0 and frac_pos >= 2.0 / 3.0)
            d["passed_all"] = bool(d.get("passed_all_base") and d["passed_mom"])

    passing_value = [
        n for n in VALUE_TRIO
        if n in per_factor and per_factor[n].get("passed_all")
    ]
    composite_info = None
    if passing_value:
        logger.info(f"价值组合组件: {passing_value}")
        comp_ics = []
        for w in result.windows:
            sub = panel[
                (panel.index.get_level_values(1) >= w.test_start)
                & (panel.index.get_level_values(1) <= w.test_end)
            ]
            if sub.empty:
                continue
            daily_comp = []
            for _, g in sub.groupby(level=1):
                scores = []
                for n in passing_value:
                    f = g[n].dropna()
                    if f.notna().sum() < 20 or f.std() == 0:
                        continue
                    scores.append((f - f.mean()) / f.std())
                if len(scores) < 2:
                    continue
                composite = pd.concat(scores, axis=1).mean(axis=1)
                fwd = g["fwd5"]
                common = composite.dropna().index.intersection(fwd.dropna().index)
                if len(common) < 20:
                    continue
                fr = composite.loc[common].rank().to_numpy()
                rr = fwd.loc[common].rank().to_numpy()
                n = len(fr)
                num = n * float(np.dot(fr, rr)) - float(fr.sum()) * float(rr.sum())
                den = np.sqrt(
                    (n * float(np.dot(fr, fr)) - float(fr.sum()) ** 2)
                    * (n * float(np.dot(rr, rr)) - float(rr.sum()) ** 2)
                )
                if den > 1e-12:
                    daily_comp.append(num / den)
            if daily_comp:
                comp_ics.append(float(np.mean(daily_comp)))
        if comp_ics:
            composite_info = {
                "components": passing_value,
                "oos_ic_mean": round(float(np.mean(comp_ics)), 4),
                "oos_ic_std": round(float(np.std(comp_ics)), 4),
                "n_windows": len(comp_ics),
            }

    print(f"\n{'='*96}")
    print("P11 基本面价值/质量因子族 Walk-Forward 测试结果 (预注册 2026-08-26)")
    print(f"{'='*96}")
    print(f"数据: {df['code'].nunique()} 只, {df['date'].nunique()} 天")
    print(f"Walk-Forward: {len(result.windows)} 窗 (504/63)")
    print(f"耗时: {time.time() - t0:.1f}s")
    hdr = (f"\n{'因子':<22} {'OOS IC':>8} {'ICIR':>8} {'PBO':>7} {'窗':>4} {'方向':>4} "
           f"{'IC✓':>4} {'IR✓':>4} {'PBO✓':>5} {'MOM✓':>5} {'ALL✓':>5}")
    print(hdr)
    print("-" * 96)
    for name in TEST_FACTORS:
        d = per_factor.get(name, {})
        if d.get("n_windows", 0) == 0 and "oos_ic_mean" not in d:
            print(f"{name:<22} {'—':>8} {'—':>8} {'—':>7} {'0':>4} — 全窗无有效 IC")
            continue
        sign = "+" if d.get("correct_sign") else "x"
        cells = ["Y" if d.get(k) else "." for k in
                 ("passed_ic", "passed_icir", "passed_pbo", "passed_mom", "passed_all")]
        print(f"{name:<22} {d['oos_ic_mean']:>+8.4f} {d['oos_icir']:>+8.2f} "
              f"{d['pbo']:>7.3f} {d['n_windows']:>4} {sign:>4} "
              f"{cells[0]:>4} {cells[1]:>4} {cells[2]:>5} {cells[3]:>5} {cells[4]:>5}")
    if composite_info:
        print(f"\n价值复合 ({'+'.join(composite_info['components'])}): "
              f"OOS IC={composite_info['oos_ic_mean']:+.4f} "
              f"(±{composite_info['oos_ic_std']:.4f}, {composite_info['n_windows']} 窗)")
    print(f"\n{'='*96}")

    report = {
        "_meta": {
            "prereg": "docs/analysis/FUNDAMENTAL_FACTOR_PREREGISTRATION.md (2026-08-26)",
            "n_symbols": int(df["code"].nunique()),
            "n_days": int(df["date"].nunique()),
            "as_of": "2026-05-29", "lookback_days": lookback,
            "sample": not full, "n_windows": len(result.windows),
            "financial_coverage": {
                col: round(float(df[col].notna().mean()), 4)
                for col in ("eps_ttm", "revenue_ttm", "operating_cost_ttm",
                            "net_profit_parent_ttm", "ocf_ttm", "ocf_ps_ttm",
                            "total_assets", "total_shares", "free_float_shares")
                if col in df.columns
            },
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "per_factor": per_factor,
        "composite": composite_info,
        "summary": {
            "n_tested": len(TEST_FACTORS),
            "n_passed_all": sum(1 for d in per_factor.values() if d.get("passed_all")),
            "n_passed_base_gates": sum(
                1 for d in per_factor.values() if d.get("passed_all_base")
            ),
            "n_correct_sign": sum(
                1 for d in per_factor.values() if d.get("correct_sign")
            ),
        },
    }
    out_path = Path(DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 → {out_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="基本面因子族 Walk-Forward 测试 (P11)")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=32)
    args = parser.parse_args()
    sample = args.sample if args.sample is not None else (60 if args.smoke else 500)
    run_test(load_sample=sample, full=args.full, max_workers=args.max_workers)


if __name__ == "__main__":
    main()
