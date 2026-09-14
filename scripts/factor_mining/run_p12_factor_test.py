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
from scripts.factor_mining.five_gate import correct_fwd5, factor_gates  # noqa: E402
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
    # 2026-08-28 fwd5 错位 bug 修复: 正确 = close[t+5]/close[t]-1 (未来0-5日)
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
        per_factor[name] = factor_gates(panel, result.windows, name, EXPECTED_DIRECTION[name])

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
