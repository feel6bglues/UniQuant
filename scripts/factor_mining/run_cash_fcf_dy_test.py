"""P14 — 现金流价值因子裁决 Walk-Forward 测试 (外部研究候选 × 本项目五门)。

预注册冻结于 docs/analysis/P14_CASH_FCF_DY_PREREGISTRATION.md (2026-08-28):
- 3 新因子 (cash_ratio/fcf_yield/real_dy) + 基线正因子对照 (cfp_ttm/illiq_20d)
- 504/63 窗, 500 只 × 1600d, as-of 2026-05-29, 与 P11/P12 同面板
- 五门: 方向 (双向裁决) + IC (|OOS IC|>0.01) + ICIR (>0.5) + PBO (<0.2)
  + 动量残差门 (控 mom20: 残差>0 且 tail>0 且 pos_frac≥2/3, 双向)
- 数据口径: TDX 财务双 TTM (capex 2026-08-28 实测累计 YTD) +
  data/lake/dividend 真实派现 (365d TTM, 无未来函数)
- 冗余预检 (T5): fcf_yield vs cfp_ttm spearman=0.792<0.9 → 全部保留

⚠️ 2026-08-28 D+15 重大修正 (fwd5 错位 bug + OOS 口径):
  1. 原 `panel["fwd5"] = pct_change(-5).shift(-5)` 经 pandas 语义验证 =
     close[t+5]/close[t+10]-1 (未来5-10日收益, 视野错位5天) → 改
     `correct_fwd5 = close[t+5]/close[t]-1` (未来0-5日, 与 analyzer 官方一致)
  2. 原 `oos_ic_mean` 取自 pipeline.w.ic_mean (= 训练窗 IC, 且 1/5/20 期再平均)
     → 改真实 OOS 测试窗 panel 逐日 IC (five_gate.factor_gates)
  3. 修复后 cash_ratio/fcf_yield 动量残差门实为 PASS (残差 IC +0.0119/+0.0133),
     原 "动量 beta 幻影" 结论系 fwd5 错位伪影

用法:
    python3 scripts/factor_mining/run_cash_fcf_dy_test.py            # sample 500
    python3 scripts/factor_mining/run_cash_fcf_dy_test.py --smoke    # sample 60
    python3 scripts/factor_mining/run_cash_fcf_dy_test.py --full     # 全市场
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
from scripts.factor_mining.five_gate import correct_fwd5, factor_gates  # noqa: E402
from scripts.factor_mining.run_t5_redundancy_precheck import merge_dividend  # noqa: E402
from uniquant.brain.factors.analyzer import FactorAnalyzer  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.brain.factors.custom_factors import (  # noqa: E402
    compute_cash_ratio, compute_fcf_yield, compute_real_dy,
    compute_cfp_ttm, compute_illiq_20d,
)
from uniquant.brain.factors.walk_forward_pipeline import (  # noqa: E402
    WalkForwardFactorPipeline,
)
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.cash_fcf_dy_test")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "cash_fcf_dy_test.json"

NEW_FACTORS = ["cash_ratio", "fcf_yield", "real_dy"]
BASELINE_POSITIVE = ["cfp_ttm", "illiq_20d"]
TEST_FACTORS = NEW_FACTORS + BASELINE_POSITIVE

# 预注册 §2 冻结方向: 全部正 (外部研究主张), 双向裁决 (红队 R2)
EXPECTED_DIRECTION = {
    "cash_ratio": 1, "fcf_yield": 1, "real_dy": 1,
    "cfp_ttm": 1, "illiq_20d": 1,
}

CASH_TRIO = ["cash_ratio", "fcf_yield", "real_dy"]

# P14 新增财务列 (capex_ttm 由 bridge 计算; dividend_dps_ttm 由脚本侧合并)
EXTRA = EXTRA_FINANCIAL_FIELDS + ["capex_ttm"]


def _make_factor_func():
    def _func(df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["cash_ratio"] = compute_cash_ratio(df)
        result["fcf_yield"] = compute_fcf_yield(df)
        result["real_dy"] = compute_real_dy(df)
        result["cfp_ttm"] = compute_cfp_ttm(df)
        result["illiq_20d"] = compute_illiq_20d(df)
        return result

    return _func


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

    logger.info("合并财务列 (PIT merge_asof + capex_ttm)...")
    df = merge_financial_metrics(df, extra_fields=EXTRA, max_workers=max_workers)
    logger.info("合并真实分红 (dividend_dps_ttm, 365d TTM)...")
    df = merge_dividend(df)

    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].nunique()} 天, {len(df):,} 行")
    coverage = {}
    for col in ("cash_ratio", "fcf_yield", "real_dy", "capex_ttm", "ocf_ttm"):
        if col in df.columns:
            cov = float(df[col].notna().mean())
            coverage[col] = round(cov, 4)
            logger.info(f"  {col} 覆盖: {cov:.1%}")

    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])
    # 2026-08-28 fwd5 错位 bug 修复: pct_change(-5).shift(-5)=未来5-10日收益(错位),
    # 正确 = close[t+5]/close[t]-1 (未来0-5日, 与 analyzer 官方逐位一致)
    panel["fwd5"] = correct_fwd5(panel)
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
    for name in factor_cols_avail:
        # 2026-08-28 修正: 原用 pipeline.w.ic_mean(=训练窗 IC, 且 1/5/20 期再平均)
        # 现统一用真实 OOS 测试窗 panel 逐日 IC (正确 fwd5), 见 five_gate.factor_gates
        d = factor_gates(panel, result.windows, name, EXPECTED_DIRECTION[name])
        per_factor[name] = d

    # 复合 (全部通过三因子才构建; 双向裁决下, 通过者组合)
    passing = [
        n for n in CASH_TRIO
        if n in per_factor and per_factor[n].get("passed_all")
    ]
    composite_info = None
    if passing:
        logger.info(f"复合组件: {passing}")
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
                for n in passing:
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
                "components": passing,
                "oos_ic_mean": round(float(np.mean(comp_ics)), 4),
                "oos_ic_std": round(float(np.std(comp_ics)), 4),
                "n_windows": len(comp_ics),
            }

    print(f"\n{'='*96}")
    print("P14 现金流价值因子裁决 Walk-Forward 测试 (预注册 2026-08-28)")
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
        print(f"\n现金流复合 ({'+'.join(composite_info['components'])}): "
              f"OOS IC={composite_info['oos_ic_mean']:+.4f} "
              f"(±{composite_info['oos_ic_std']:.4f}, {composite_info['n_windows']} 窗)")
    print(f"\n{'='*96}")

    report = {
        "_meta": {
            "prereg": "docs/analysis/P14_CASH_FCF_DY_PREREGISTRATION.md (2026-08-28)",
            "n_symbols": int(df["code"].nunique()),
            "as_of": "2026-05-29", "lookback_days": lookback,
            "sample": not full, "n_windows": len(result.windows),
            "coverage": coverage,
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
            "n_correct_sign": sum(1 for d in per_factor.values() if d.get("correct_sign")),
        },
    }
    out_path = Path(DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 → {out_path}")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="P14 现金流价值因子五门裁决")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--max-workers", type=int, default=32)
    args = ap.parse_args()
    run_test(60 if args.smoke else args.sample, args.full, args.max_workers)


if __name__ == "__main__":
    main()
