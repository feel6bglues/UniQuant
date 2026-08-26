"""P12 — 尾部风险因子族 + 筹码结构因子族 Walk-Forward 测试。

预注册冻结于 docs/analysis/P12_PREREGISTRATION_TAIL_CHIP_FACTORS.md (2026-08-26):
- Batch A 价格尾部×4: cvar_95_60d(+)/max_drawdown_20d(+)/downside_semivol_20d(−)/kurtosis_20d(−)
- Batch B 筹码流×3: holder_num_chg_1q(−)/inst_shares_chg_1q(+)/top10_float_chg_1q(+)
  (季频快照在脚本侧派生 q-o-q 变化率 → bridge extra_fields PIT 合并)
- 基线对照: illiq_20d / idiosyncratic_vol_20d
- 五门同 P11; 与 P3/P11 同面板横向可比

用法:
    python3 scripts/factor_mining/run_p12_factor_test.py            # sample 500
    python3 scripts/factor_mining/run_p12_factor_test.py --smoke    # sample 60
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

from scripts.factor_mining.data_loader import load_universe, merge_financial_metrics  # noqa: E402
from uniquant.brain.factors.analyzer import FactorAnalyzer  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.p12_factor_test")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "p12_tail_chip_factor_test.json"

TAIL_FACTORS = ["cvar_95_60d", "max_drawdown_20d", "downside_semivol_20d", "kurtosis_20d"]
CHIP_FACTORS = ["holder_num_chg_1q", "inst_shares_chg_1q", "top10_float_chg_1q"]
TEST_FACTORS = TAIL_FACTORS + CHIP_FACTORS + ["illiq_20d", "idiosyncratic_vol_20d"]

EXPECTED_DIRECTION = {
    "cvar_95_60d": 1, "max_drawdown_20d": 1,
    "downside_semivol_20d": -1, "kurtosis_20d": -1,
    "holder_num_chg_1q": -1, "inst_shares_chg_1q": 1, "top10_float_chg_1q": 1,
    "illiq_20d": 1, "idiosyncratic_vol_20d": 1,
}

CHIP_RAW_COLS = ["holder_num", "inst_shares", "top10_float_shares"]
CHIP_DERIVED_COLS = ["holder_num_chg_1q", "inst_shares_chg_1q", "top10_float_chg_1q"]


def derive_chip_change_frames(
    financial_dir: Path, codes: list[str]
) -> dict[str, pd.DataFrame]:
    """读季频财务帧 → 中文字段映射标准名 → 派生筹码 q-o-q 变化率。"""
    from uniquant.brain.factors.financial_bridge import FinancialFactorBridge

    bridge = FinancialFactorBridge()
    frames: dict[str, pd.DataFrame] = {}
    for code in codes:
        path = financial_dir / f"{code}.parquet"
        if not path.exists():
            continue
        try:
            fin = pd.read_parquet(path)
        except Exception as e:
            logger.warning(f"read {code} failed: {e}")
            continue
        fin = bridge.map_fields(fin)  # 中文列名 → holder_num/inst_shares/...
        fin = fin.sort_values("report_date")
        for col in CHIP_RAW_COLS:
            if col in fin.columns:
                fin[col] = pd.to_numeric(fin[col], errors="coerce")
        fin["holder_num_chg_1q"] = (
            np.log(fin["holder_num"].where(fin["holder_num"] > 0))
            .diff()
            if "holder_num" in fin.columns else np.nan
        )
        for src, dst in [("inst_shares", "inst_shares_chg_1q"),
                         ("top10_float_shares", "top10_float_chg_1q")]:
            if src in fin.columns:
                prev = fin.groupby("code")[src].shift(1)
                fin[dst] = np.where(prev.abs() > 0, fin[src] / prev - 1.0, np.nan)
                fin.loc[fin[src].isna() | prev.isna(), dst] = np.nan
            else:
                fin[dst] = np.nan
        keep = ["code", "report_date"] + [
            c for c in (*CHIP_DERIVED_COLS, *CHIP_RAW_COLS) if c in fin.columns
        ]
        frames[code] = fin[keep]
    return frames


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
        if mm_r.var() > 1e-12:
            beta = np.cov(ff_r, mm_r)[0, 1] / mm_r.var()
            res = pd.Series(ff_r - beta * mm_r).rank().to_numpy()
            n = len(res)
            num = n * float(np.dot(res, rr_r)) - float(res.sum()) * float(rr_r.sum())
            den = np.sqrt(
                (n * float(np.dot(res, res)) - float(res.sum()) ** 2)
                * (n * float(np.dot(rr_r, rr_r)) - float(rr_r.sum()) ** 2)
            )
            res_ics.append(num / den if den > 1e-12 else 0.0)
        th = np.quantile(mm_r, 0.9)
        keep = mm_r <= th
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

    logger.info("派生筹码变化率帧 + PIT 合并...")
    chip_frames = derive_chip_change_frames(
        PROJECT_ROOT / "data" / "lake" / "financial",
        sorted(df["code"].unique()),
    )
    logger.info(f"筹码帧覆盖 {len(chip_frames)} 只")
    df = merge_financial_metrics(
        df, extra_fields=CHIP_DERIVED_COLS, max_workers=max_workers,
        financial_frames=chip_frames,
    )

    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].nunique()} 天, {len(df):,} 行")
    coverage = {}
    for col in CHIP_DERIVED_COLS:
        cov = float(df[col].notna().mean())
        coverage[col] = round(cov, 4)
        logger.info(f"  筹码列覆盖 {col}: {cov:.1%}")

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
        logger.warning(f"因子缺失: {missing}")
    for col in factor_cols_avail:
        panel[col] = all_factors[col].to_numpy()

    pipeline = WalkForwardFactorPipeline(
        factor_analyzer=FactorAnalyzer(), factor_composer=FactorComposer(),
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
            ic = w.ic_mean.get(name)
            if ic is not None and np.isfinite(ic):
                ic_vals.append(ic)
        if not ic_vals:
            per_factor[name] = {"n_windows": 0, "note": "no valid window IC"}
            continue
        oos_mean, oos_std = float(np.mean(ic_vals)), float(np.std(ic_vals))
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
        res_all, tail_all, pos_windows, n_win = [], [], 0, 0
        for w in result.windows:
            sub = panel[
                (panel.index.get_level_values(1) >= w.test_start)
                & (panel.index.get_level_values(1) <= w.test_end)
            ]
            if sub.empty or name not in sub.columns:
                continue
            daily = _daily_ic_series_for_window(sub, name)
            n_win += 1
            if daily["res"]:
                res_all.extend(daily["res"])
                pos_windows += (np.mean(daily["res"]) > 0)
            tail_all.extend(daily["tail"])
        if res_all:
            exp_dir = EXPECTED_DIRECTION[name]
            res_m, tail_m = float(np.mean(res_all)), float(np.mean(tail_all))
            frac_pos = pos_windows / max(n_win, 1)
            if exp_dir < 0:
                res_m, tail_m = -res_m, -tail_m
                frac_pos = 1.0 - frac_pos
            d["mom_res_mean"] = round(res_m, 4)
            d["mom_tail_mean"] = round(tail_m, 4)
            d["mom_pos_frac"] = round(frac_pos, 3)
            d["passed_mom"] = bool(res_m > 0 and tail_m > 0 and frac_pos >= 2.0 / 3.0)
            d["passed_all"] = bool(d.get("passed_all_base") and d["passed_mom"])

    print(f"\n{'='*96}")
    print("P12 尾部风险+筹码结构因子 Walk-Forward 测试结果 (预注册 2026-08-26)")
    print(f"{'='*96}")
    print(f"数据: {df['code'].nunique()} 只, {df['date'].nunique()} 天 | 筹码覆盖 {coverage}")
    print(f"Walk-Forward: {len(result.windows)} 窗 (504/63) | 耗时 {time.time()-t0:.1f}s")
    print(f"\n{'因子':<24} {'OOS IC':>8} {'ICIR':>8} {'PBO':>7} {'窗':>4} {'方向':>4} "
          f"{'IC✓':>4} {'IR✓':>4} {'PBO✓':>5} {'MOM✓':>5} {'ALL✓':>5}")
    print("-" * 96)
    for name in TEST_FACTORS:
        d = per_factor.get(name, {})
        if d.get("n_windows", 0) == 0 and "oos_ic_mean" not in d:
            print(f"{name:<24} 全窗无有效 IC")
            continue
        sign = "+" if d.get("correct_sign") else "x"
        cells = ["Y" if d.get(k) else "." for k in
                 ("passed_ic", "passed_icir", "passed_pbo", "passed_mom", "passed_all")]
        print(f"{name:<24} {d['oos_ic_mean']:>+8.4f} {d['oos_icir']:>+8.2f} "
              f"{d['pbo']:>7.3f} {d['n_windows']:>4} {sign:>4} "
              f"{cells[0]:>4} {cells[1]:>4} {cells[2]:>5} {cells[3]:>5} {cells[4]:>5}")
    print(f"\n{'='*96}")

    report = {
        "_meta": {
            "prereg": "docs/analysis/P12_PREREGISTRATION_TAIL_CHIP_FACTORS.md",
            "n_symbols": int(df["code"].nunique()),
            "as_of": "2026-05-29", "lookback_days": lookback,
            "sample": not full, "n_windows": len(result.windows),
            "chip_coverage": coverage,
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "per_factor": per_factor,
        "summary": {
            "n_tested": len(TEST_FACTORS),
            "n_passed_all": sum(1 for d in per_factor.values() if d.get("passed_all")),
            "n_passed_base_gates": sum(
                1 for d in per_factor.values() if d.get("passed_all_base")
            ),
            "n_correct_sign": sum(1 for d in per_factor.values() if d.get("correct_sign")),
        },
    }
    out_path = Path(DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 → {out_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="尾部风险+筹码结构因子测试 (P12)")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=32)
    args = parser.parse_args()
    sample = args.sample if args.sample is not None else (60 if args.smoke else 500)
    run_test(load_sample=sample, full=args.full, max_workers=args.max_workers)


if __name__ == "__main__":
    main()
