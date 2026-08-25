"""P1 — 净化真实数据 13 因子 Walk-Forward 基线。

复用 `WalkForwardFactorPipeline` (src 研究工具, 此前从未在真实数据跑过)。
输入: 净化符号池 (get_symbols 已剔除 554 指数) 合并长表。
输出: 基线表 (每因子 OOS IC@1/5/20d / ICIR / 权重稳定性 Std / n_windows) JSON。

用法:
    python3 scripts/factor_mining/run_walk_forward_baseline.py --sample 500
    python3 scripts/factor_mining/run_walk_forward_baseline.py --full
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.brain.factors.registry import FactorRegistry  # noqa: E402
from uniquant.brain.factors.walk_forward_pipeline import (  # noqa: E402
    WalkForwardFactorPipeline,
    WalkForwardResult,
)
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.baseline")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "baseline_walkforward.json"


def _make_factor_func():
    """包装 FactorComposer.compute_all_factors 为 walk_forward 需要的完整 df 函数。"""
    composer = FactorComposer()

    def _func(df: pd.DataFrame) -> pd.DataFrame:
        out = composer.compute_all_factors(df, mode="backtest")
        result = df.copy()
        for col in out.columns:
            result[col] = out[col].to_numpy()
        return result

    return _func


def build_report(
    wf: WalkForwardResult,
    factor_cols: list[str],
    df: pd.DataFrame | None = None,
    factor_func=None,
) -> dict:
    """汇总窗口结果为每因子基线。"""
    report = {
        "factor_cols": factor_cols,
        "n_windows": len(wf.windows),
        "window_dates": [
            {
                "train": [str(w.train_start.date()), str(w.train_end.date())],
                "test": [str(w.test_start.date()), str(w.test_end.date())],
                "n_train_stocks": w.n_train_stocks,
                "n_test_stocks": w.n_test_stocks,
                "weights": {k: round(vi, 6) for k, vi in w.weights.items()},
            }
            for w in wf.windows
        ],
        "oos_ic_mean": round(wf.oos_ic_mean, 6),
        "oos_ic_std": round(wf.oos_ic_std, 6),
        "oos_icir": round(wf.oos_icir, 6),
        "per_oos_ic": {},
        "per_oos_icir": {},
        "final_weights": {k: round(v, 6) for k, v in wf.final_weights.items()},
        "weight_stability": {k: round(v, 6) for k, v in wf.weight_stability.items()},
    }

    # 管线只给 composite OOS IC；这里对每个测试窗直接算每因子 OOS IC
    if df is not None and factor_func is not None:
        analyzer = FactorAnalyzer()
        oos_ic: dict[str, list] = {c: [] for c in factor_cols}
        oos_icir: dict[str, list] = {c: [] for c in factor_cols}
        for w in wf.windows:
            d = pd.to_datetime(df["date"])
            test_df = df[(d >= w.test_start) & (d <= w.test_end)].reset_index(drop=True)
            if test_df.empty:
                continue
            tf = factor_func(test_df.copy())
            res = analyzer.compute_ic_ir(
                tf,
                factor_cols=factor_cols,
                holding_periods=[1, 5, 20],
                date_col="date", code_col="code", price_col="close",
                mode=AnalysisMode.BACKTEST,
            )
            for c in factor_cols:
                if c not in res or not res[c]:
                    continue
                vals = [r.ic_mean for r in res[c].values() if hasattr(r, "ic_mean")]
                irs = [r.icir for r in res[c].values() if hasattr(r, "icir")]
                oos_ic[c].append(float(np.mean(vals)) if vals else float("nan"))
                oos_icir[c].append(float(np.mean(irs)) if irs else float("nan"))
        report["per_oos_ic"] = {c: [round(x, 6) for x in v] for c, v in oos_ic.items()}
        report["per_oos_icir"] = {c: [round(x, 6) for x in v] for c, v in oos_icir.items()}

    return report


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward 因子基线 (净化数据)")
    parser.add_argument("--full", action="store_true", help="全量 5018 只 (默认 sample 500 只)")
    parser.add_argument("--sample", type=int, default=500, help="样本股票数")
    parser.add_argument("--as-of", default=None, help="截断日期")
    parser.add_argument("--lookback-days", type=int, default=1600,
                        help="回看交易日数 (默认约 6.4 年 → ~17 窗; 全历史 8704 天 → 130 窗)")
    parser.add_argument("--train-window", type=int, default=504)
    parser.add_argument("--test-window", type=int, default=63)
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--max-workers", type=int, default=32)
    args = parser.parse_args()

    registry = FactorRegistry()
    factor_cols = [f.name for f in registry.get_enabled()]
    logger.info(f"因子集 ({len(factor_cols)}): {factor_cols}")

    df = load_universe(
        as_of=args.as_of, max_workers=args.max_workers
    )
    if args.full:
        symbols = None
        logger.info("全量模式")
    else:
        codes = sorted(df["code"].unique())
        rng = np.random.RandomState(42)
        selected = rng.choice(codes, size=min(args.sample, len(codes)), replace=False)
        symbols = sorted(str(s) for s in selected)
        df = df[df["code"].isin(symbols)].reset_index(drop=True)
        logger.info(f"采样 {len(symbols)} 只")

    if args.lookback_days and df["date"].nunique() > args.lookback_days:
        cutoff = df["date"].sort_values().unique()[-args.lookback_days]
        df = df[df["date"] >= cutoff].reset_index(drop=True)
        logger.info(f"回看截断: {str(cutoff)[:10]} 起 ({args.lookback_days} 交易日)")

    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].min().date()} → {df['date'].max().date()}, {len(df):,} 行")

    wf = WalkForwardFactorPipeline(
        train_window=args.train_window,
        test_window=args.test_window,
    )

    t0 = time.time()
    logger.info("运行 Walk-Forward (每窗: ICIR 加权 → composer 打分 → OOS IC)...")
    result = wf.run(
        df,
        factor_cols=factor_cols,
        date_col="date",
        code_col="code",
        price_col="close",
        factor_func=_make_factor_func(),
    )
    elapsed = time.time() - t0
    logger.info(f"完成: {result.oos_ic_mean:+.4f} OOS IC, ICIR {result.oos_icir:+.3f}, {len(result.windows)} 窗, {elapsed:.1f}s")

    report = build_report(result, factor_cols, df=df, factor_func=_make_factor_func())
    report["_meta"] = {
        "n_symbols": int(df["code"].nunique()),
        "n_rows": int(len(df)),
        "sample": not args.full,
        "as_of": args.as_of,
        "train_window": args.train_window,
        "test_window": args.test_window,
        "elapsed_sec": round(elapsed, 1),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告 → {out_path}")
    print(f"OOS IC mean = {result.oos_ic_mean:+.4f}  ICIR = {result.oos_icir:+.3f}")
    print("final weights:", {k: round(v, 3) for k, v in result.final_weights.items()})


if __name__ == "__main__":
    main()