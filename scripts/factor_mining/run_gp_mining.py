"""P2 — 真实数据 GP 因子挖掘 (净化底座 × 既有 GP 引擎 × Reaper v2)。

复接 `experiments/gp_factor_mining`（原只跑合成数据）到净化真实数据:
- 输入: `load_universe`（get_symbols 已剔 554 指数）+ 与 P1 基线同参数采样
  （500 只 seed=42, as-of 2026-05-29, lookback 1600 交易日）→ 逐位可比。
- GP: `GeneticFactorMiner.mine()`; 面板 (code, date) MultiIndex,
  generator 的终端/时序算子已逐股票分组（避免跨股票边界泄漏）。
- Reaper v2 (死神校验): Walk-Forward 504/63 窗 × 逐日横截面 Spearman IC + 4 道门:
    1. IC 门槛: OOS IC(5d) > max(0.07, 基线最正因子 OOS IC)
    2. PBO < 0.2 (块 Bootstrap, 保留 IC 时序自相关)
    3. 动量残差门: 控 20d 相对动量（残差化 IC + 剔右尾 IC）须仍为正且 ≥2/3 窗正
    4. 多样性门: 与基线正因子 (idiosyncratic_vol_20d / illiq_20d) 横截面 |corr| < 0.7
- 幸存 → 输出 .py 因子代码 + JSON/Markdown 报告。

用法:
    python3 scripts/factor_mining/run_gp_mining.py --smoke            # pop60×10, sample 200
    python3 scripts/factor_mining/run_gp_mining.py                    # pop200×20, sample 500
    python3 scripts/factor_mining/run_gp_mining.py --full --pop-size 300 --generations 30
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
EXPERIMENTS = PROJECT_ROOT / "experiments" / "gp_factor_mining"
for _p in (str(PROJECT_ROOT), str(EXPERIMENTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from generator import GeneticFactorMiner, GPConfig  # noqa: E402
from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from uniquant.brain.factors.composer import FactorComposer  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.gp_mining")

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "gp_mining.json"
DEFAULT_GEN_DIR = PROJECT_ROOT / "results" / "factor_mining" / "generated"

BASELINE_OOS = PROJECT_ROOT / "results" / "factor_mining" / "baseline_walkforward_sample500_oos.json"
BASELINE_POSITIVE_FACTORS = ["idiosyncratic_vol_20d", "illiq_20d"]


# ─── 数据 ────────────────────────────────────────────────────────────────


def load_and_sample(
    as_of: str,
    sample: int,
    lookback_days: int,
    full: bool,
    max_workers: int,
    symbols: list | None = None,
) -> pd.DataFrame:
    """净化池加载 + 采样 + 回看截断 (返回 flat 长表)。

    `symbols` 非 None 时跳过全量加载 (冒烟预采样路径)。
    """
    if symbols is not None:
        df = load_universe(as_of=as_of or None, max_workers=max_workers, symbols=list(symbols))
        logger.info(f"预采样 {len(symbols)} 只加载")
    else:
        df = load_universe(as_of=as_of or None, max_workers=max_workers)
        if not full:
            codes = sorted(df["code"].unique())
            rng = np.random.RandomState(42)
            selected = rng.choice(codes, size=min(sample, len(codes)), replace=False)
            symbols = sorted(str(s) for s in selected)
            df = df[df["code"].isin(symbols)].reset_index(drop=True)
            logger.info(f"采样 {len(symbols)} 只 (seed=42)")
    if lookback_days and df["date"].nunique() > lookback_days:
        cutoff = df["date"].sort_values().unique()[-lookback_days]
        df = df[df["date"] >= cutoff].reset_index(drop=True)
        logger.info(f"回看截断: {str(cutoff)[:10]} 起 ({lookback_days} 交易日)")
    logger.info(f"数据集: {df['code'].nunique()} 只, {df['date'].min().date()} → {df['date'].max().date()}, {len(df):,} 行")
    return df


def sample_symbols(n: int, max_workers: int = 32) -> list[str]:
    """从净化符号池预采样 (冒烟用, 免全量加载)。"""
    from uniquant.data.lake.storage_manager import StorageManager
    storage = StorageManager("./data")
    syms = sorted(str(s) for s in storage.get_symbols())
    rng = np.random.RandomState(42)
    selected = rng.choice(syms, size=min(n, len(syms)), replace=False)
    return sorted(str(s) for s in selected)


def to_panel(df: pd.DataFrame) -> pd.DataFrame:
    """flat 长表 → MultiIndex (code, date) 面板。

    保留 date/code 列 (mine()/reaper 按列访问), 索引层级改名避免
    groupby('date') 的 level/column 二义性。"""
    pdf = df.copy()
    pdf["date"] = pd.to_datetime(pdf["date"])
    pdf = pdf.set_index(["code", "date"], drop=False)
    pdf.index = pdf.index.set_names(["code_idx", "date_idx"])
    return pdf


def baseline_threshold() -> tuple[float, dict]:
    """从 P1 基线产物读取最正因子 OOS IC → IC 门槛 = max(0.07, 最正)。"""
    if not BASELINE_OOS.exists():
        logger.warning(f"基线产物缺失 {BASELINE_OOS} → 门槛退回 0.07")
        return 0.07, {}
    report = json.loads(BASELINE_OOS.read_text(encoding="utf-8"))
    per = report.get("per_oos_ic", {})
    pos = {}
    for f, vals in per.items():
        clean = [v for v in vals if isinstance(v, (int, float)) and v == v]
        if not clean:
            continue
        m = float(np.mean(clean))
        if m > 0:
            pos[f] = m
    best = max(pos.values()) if pos else 0.0
    thr = max(0.07, best)
    logger.info(f"基线正因子: { {k: round(v, 4) for k, v in pos.items()} } → 门槛 IC={thr:.4f}")
    return thr, pos


def compute_baseline_pos_factors(df_flat: pd.DataFrame) -> dict[str, pd.Series]:
    """一次性计算基线正因子横截面值 (对齐面板索引)。"""
    composer = FactorComposer()
    factors = composer.compute_all_factors(df_flat, mode="backtest")
    if isinstance(factors, tuple):
        factors = factors[0]
    panel = to_panel(df_flat.reset_index(drop=True))
    out = {}
    for name in BASELINE_POSITIVE_FACTORS:
        if name not in factors.columns:
            logger.warning(f"基线因子 {name} 缺失")
            continue
        out[name] = pd.Series(factors[name].to_numpy(), index=panel.index, dtype=float)
    return out


# ─── Reaper v2 ──────────────────────────────────────────────────────────


def build_windows(all_dates: list, train_w: int = 504, test_w: int = 63):
    """Walk-Forward 窗口 (同日口径与 P1 基线一致: train 504 / test 63, step 63)。"""
    windows = []
    for start in range(train_w, len(all_dates) - test_w + 1, test_w):
        windows.append(
            (
                all_dates[start - train_w], all_dates[start - 1],
                all_dates[start], all_dates[start + test_w - 1],
            )
        )
    return windows


def _daily_ic_series(panel: pd.DataFrame, factor: pd.Series, fwd_col: str, dates: pd.Series):
    """面板内逐日横截面 Spearman IC (向量化 rank → Pearson)。"""
    fx = factor.reindex(panel.index)
    fwd = panel[fwd_col]
    valid = fx.notna() & fwd.notna()
    ff = fx[valid]
    ff_r = ff.groupby(level=1).rank()
    rv = fwd[valid]
    rv_r = rv.groupby(level=1).rank()
    df = pd.DataFrame({"f": ff_r, "r": rv_r, "date": rv.index.get_level_values(1)})
    out = []
    for _d, g in df.groupby(level=1):
        n = len(g)
        if n < 20:
            continue
        fs, rs = g["f"].to_numpy(), g["r"].to_numpy()
        num = n * float(np.dot(fs, rs)) - float(fs.sum()) * float(rs.sum())
        den = np.sqrt(
            (n * float(np.dot(fs, fs)) - float(fs.sum()) ** 2)
            * (n * float(np.dot(rs, rs)) - float(rs.sum()) ** 2)
        )
        if den > 1e-12:
            out.append(num / den)
    return out


def _mom_20(panel: pd.DataFrame) -> pd.Series:
    """面板逐股票 20d 收益 (动量控制变量)。"""
    return panel["close"].groupby(level=0).pct_change(20, fill_method=None)


def reaper_v2(
    candidates: list,
    panel: pd.DataFrame,
    threshold_ic: float,
    baseline_pos: dict[str, pd.Series],
    holding_period: int = 5,
    train_w: int = 504,
    test_w: int = 63,
    n_bootstrap: int = 2000,
    n_jobs: int = 1,
) -> dict:
    """死神校验 v2 — Walk-Forward × 4 道门。"""
    all_dates = list(panel.index.get_level_values(1).unique())
    windows = build_windows(all_dates, train_w, test_w)
    logger.info(f"Walk-Forward: {len(windows)} 窗 (train={train_w}d, test={test_w}d)")

    # 预计算动量面板 + fwd 收益列
    mom = _mom_20(panel)
    for hp_name, hp in (("fwd5", 5), ("fwd20", 20)):
        panel[hp_name] = (
            panel["close"].groupby(level=0).shift(-hp) / panel["close"] - 1
        )

    results = []
    for rank, (tree, fitness) in enumerate(candidates):
        formula = tree.to_formula()
        row = {
            "rank": rank + 1,
            "formula": tree.to_formula(),
            "fitness": round(fitness, 4),
            "depth": tree.depth,
            "complexity": round(tree.complexity, 2),
            "has_amount": is_amount_dep(tree),
        }

        oos5, oos20 = [], []
        mom_ctl, mom_tail = [], []
        for ws, we, ss, se in windows:
            sub = panel[(panel.index.get_level_values(1) >= ss) & (panel.index.get_level_values(1) <= se)]
            if sub.empty:
                continue
            try:
                factor = tree.evaluate(sub)
            except Exception:
                continue

            ic5 = _daily_ic_series(sub, factor, "fwd5", None)
            ic20 = _daily_ic_series(sub, factor, "fwd20", None)
            if ic5:
                oos5.append(float(np.mean(ic5)))
            if ic20:
                oos20.append(float(np.mean(ic20)))

            # 动量残差门 (逐窗内)
            m = mom.reindex(sub.index)
            f = factor.reindex(sub.index)
            ctl, tail = [], []
            for _d, day_idx in _date_slices(sub):
                fi = f.iloc[day_idx]
                ri = sub["fwd5"].iloc[day_idx]
                mi = m.iloc[day_idx]
                ff = pd.concat([fi, ri, mi], axis=1, join="inner")
                ff.columns = ["f", "r", "m"]
                ff = ff.dropna()
                if len(ff) < 20 or ff["f"].nunique() < 2 or ff["r"].nunique() < 2:
                    continue
                try:
                    from scipy import stats
                    ic_raw, _ = stats.spearmanr(ff["f"], ff["r"])
                    # 残差化 IC: 控制 20d 动量
                    if ff["m"].nunique() >= 2:
                        cv = np.cov(ff["f"], ff["m"])[0, 1]
                        var = np.var(ff["m"])
                        beta = cv / var if var > 1e-12 else 0.0
                        f_res = ff["f"] - beta * (ff["m"] - ff["m"].mean())
                        ic_ctl, _ = stats.spearmanr(f_res, ff["r"])
                    else:
                        ic_ctl = ic_raw
                    # 剔右尾: 去掉动量最上十分位
                    th = np.quantile(ff["m"], 0.9)
                    keep = ff["m"] <= th
                    if keep.sum() >= 20 and ff.loc[keep, "f"].nunique() >= 2:
                        ic_tail, _ = stats.spearmanr(ff.loc[keep, "f"], ff.loc[keep, "r"])
                    else:
                        ic_tail = ic_raw
                    ctl.append(ic_ctl)
                    tail.append(ic_tail)
                except Exception:
                    continue
            if ctl:
                mom_ctl.append(float(np.mean(ctl)))
            if tail:
                mom_tail.append(float(np.mean(tail)))

        if len(oos5) < 2:
            row["verdict"] = "DEAD(无窗)"
            row["survived"] = False
            results.append(row)
            continue

        oos5_mean = float(np.mean(oos5))
        pbo = GeneticFactorMiner.block_bootstrap_pbo(oos5, n_bootstrap=n_bootstrap)

        mom_ctl_mean = float(np.mean(mom_ctl)) if mom_ctl else 0.0
        mom_tail_mean = float(np.mean(mom_tail)) if mom_tail else 0.0
        ctl_pos_frac = (np.mean(np.array(mom_ctl) > 0) if mom_ctl else 0.0)

        # 多样性门: 全面板评估一次 (不能用最后窗口的 factor)
        try:
            full_factor = tree.evaluate(panel)
        except Exception:
            full_factor = factor
        corrs = {}
        for name, bf in baseline_pos.items():
            c = _panel_corr(factor_series=full_factor, baseline_series=bf, panel=panel, dates=all_dates)
            corrs[name] = round(c, 4) if c == c else None
        div_scores = [abs(v) for v in corrs.values() if v is not None] or [1.0]
        max_corr = max(div_scores)

        g_ic = oos5_mean > threshold_ic
        g_pbo = pbo < 0.2
        g_mom = (mom_ctl_mean > 0) and (mom_tail_mean > 0) and (ctl_pos_frac >= 2.0 / 3.0)
        g_div = max_corr < 0.7
        survived = g_ic and g_pbo and g_mom and g_div

        row.update(
            {
                "oos_ic5_mean": round(oos5_mean, 4),
                "oos_ic5_std": round(float(np.std(oos5)), 4),
                "oos_ic5_per_window": [round(x, 4) for x in oos5],
                "oos_ic20_mean": round(float(np.mean(oos20)), 4) if oos20 else None,
                "pbo": round(pbo, 4),
                "n_windows": len(oos5),
                "mom_ctl_mean": round(mom_ctl_mean, 4),
                "mom_tail_mean": round(mom_tail_mean, 4),
                "mom_ctl_pos_frac": round(float(ctl_pos_frac), 3),
                "corr_vs_baseline_pos": corrs,
                "max_corr": round(max_corr, 4),
                "gate_ic": bool(g_ic),
                "gate_pbo": bool(g_pbo),
                "gate_momentum": bool(g_mom),
                "gate_diversity": bool(g_div),
                "survived": bool(survived),
                "verdict": f"✅ SURVIVED IC={oos5_mean:.4f} PBO={pbo:.3f}" if survived
                else f"☠️ IC={oos5_mean:.4f} PBO={pbo:.3f}",
            }
        )
        results.append(row)
        trends = "  ".join(
            f"{k}={'Y' if row[k] else 'N'}" for k in ("gate_ic", "gate_pbo", "gate_momentum", "gate_diversity")
        )
        print(f"  {row['verdict']}  {trends}  {formula[:60]}")

    n_surv = sum(1 for r in results if r["survived"])
    print(f"\n  🏆 幸存: {n_surv}/{len(candidates)}  (门槛 IC>{threshold_ic:.4f})")
    return {"threshold_ic": threshold_ic, "candidates": results, "n_survivors": n_surv}


def _date_slices(panel: pd.DataFrame):
    """按日期切片 (返回 (date, positional index array))。"""
    return [(d, np.flatnonzero(panel.index.get_level_values(1).values == d)) for d in panel.index.get_level_values(1).unique()]


def _panel_corr(factor_series: pd.Series, baseline_series: pd.Series, panel: pd.DataFrame, dates: list):
    """面板逐日横截面 |Spearman corr| 均值 (多样门)。"""
    fx = factor_series.reindex(panel.index)
    bx = baseline_series.reindex(panel.index)
    valid = fx.notna() & bx.notna()
    ff = fx[valid].groupby(level=1).rank()
    bb = bx[valid].groupby(level=1).rank()
    df = pd.DataFrame({"f": ff, "b": bb})
    corrs = []
    for _d, g in df.groupby(level=1):
        fs, bs = g["f"].to_numpy(), g["b"].to_numpy()
        n = len(fs)
        if n < 20:
            continue
        num = n * float(np.dot(fs, bs)) - float(fs.sum()) * float(bs.sum())
        den = np.sqrt(
            (n * float(np.dot(fs, fs)) - float(fs.sum()) ** 2)
            * (n * float(np.dot(bs, bs)) - float(bs.sum()) ** 2)
        )
        if den > 1e-12:
            corrs.append(abs(num / den))
    return float(np.mean(corrs)) if corrs else None


def is_amount_dep(tree) -> bool:
    def _walk(node):
        if node.terminal and node.terminal.name == "amount":
            return True
        return any(_walk(c) for c in node.children)
    return _walk(tree.root)


# ─── 输出 ────────────────────────────────────────────────────────────────


def write_factor_code(tree, index: int, row: dict):
    name = f"compute_auto_factor_{index:03d}"
    code = tree.to_python_code(
        name,
        comment=(
            f"自动因子 #{index:03d}\n"
            f"    公式: {tree.to_formula()}\n"
            f"    树深: {tree.depth}  复杂度: {row['complexity']}\n"
            f"    OOS IC@5: {row['oos_ic5_mean']}  PBO: {row['pbo']}  "
            f"动量残差门 IC: {row['mom_ctl_mean']}"
        ),
    )
    return f"import numpy as np\nimport pandas as pd\n\n{code}"


def write_markdown(report: dict, out_dir: Path) -> Path:
    lines = [
        "# P2 — 真实数据 GP 因子挖掘结果\n",
        f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> **元信息**: {json.dumps(report['_meta'], ensure_ascii=False)}",
        f"> **IC 门槛**: > {report['reaper']['threshold_ic']:.4f} (max(0.07, 基线最正因子))",
        f"> **幸存**: {report['reaper']['n_survivors']}/{len(report['reaper']['candidates'])}\n",
    ]
    lines.append("| # | 公式 | fit | IC@5 | PBO | momCtl | corr_idio | corr_illiq | 门 |\n"
                 "|---|------|-----|------|-----|--------|-----------|------------|----|")
    for r in report["reaper"]["candidates"]:
        gates = "".join("Y" if r.get("gate_" + k) else "N" for k in ("ic", "pbo", "momentum", "diversity"))
        lines.append(
            f"| {r['rank']} | `{r['formula'][:70]}` | {r['fitness']:.3f} | {r['oos_ic5_mean']:.4f} "
            f"| {r['pbo']:.3f} | {r['mom_ctl_mean']:.4f} | {r['corr_vs_baseline_pos'].get('idiosyncratic_vol_20d')} "
            f"| {r['corr_vs_baseline_pos'].get('illiq_20d')} | {gates} |"
        )
    lines.append("")
    out = out_dir / "gp_mining_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ─── 入口 ────────────────────────────────────────────────────────────────


def main():
    import warnings
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description="真实数据 GP 因子挖掘 (P2)")
    parser.add_argument("--full", action="store_true", help="全量 (默认 sample 500)")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--as-of", default="2026-05-29", help="截断日期 (默认与 P1 基线一致)")
    parser.add_argument("--lookback-days", type=int, default=1600, help="回看交易日 (与基线一致)")
    parser.add_argument("--smoke", action="store_true", help="冒烟预设: pop=60 gen=10, sample=200 (可被显式参数覆盖)")
    parser.add_argument("--pop-size", type=int, default=None)
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--candidates", type=int, default=25, help="Reaper 候选数")
    parser.add_argument("--n-jobs", type=int, default=8, help="GP 适应度并行 worker")
    parser.add_argument("--max-workers", type=int, default=32, help="数据加载 worker")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--gen-dir", default=str(DEFAULT_GEN_DIR))
    args = parser.parse_args()

    t0 = time.time()
    sample = args.sample if args.sample is not None else (200 if args.smoke else 500)
    pop_size = args.pop_size if args.pop_size is not None else (60 if args.smoke else 200)
    generations = args.generations if args.generations is not None else (10 if args.smoke else 20)

    # 冒烟路径: 直接从净化池预采样, 免全量加载
    presample = sample_symbols(sample) if args.smoke else None
    df_flat = load_and_sample(
        args.as_of, sample, args.lookback_days, args.full, args.max_workers,
        symbols=presample,
    )
    panel = to_panel(df_flat.reset_index(drop=True))

    base_thr, baseline_pos = baseline_threshold()

    config = GPConfig(
        pop_size=pop_size,
        n_generations=generations,
        max_depth=args.max_depth,
        holding_period=5,
        train_ratio=0.7,
        seed=args.seed,
        n_jobs=args.n_jobs,
    )
    miner = GeneticFactorMiner(config=config)
    logger.info(f"[GP] 进化: pop={pop_size} × {generations} 代, max_depth={max_depth_safe(args.max_depth)}")
    results = miner.mine(panel)

    candidates = results[: args.candidates]
    baseline_panel = compute_baseline_pos_factors(df_flat)

    logger.info(f"[Reaper v2] {args.candidates} 候选 × Walk-Forward 校验...")
    reaper_report = reaper_v2(
        candidates,
        panel,
        threshold_ic=base_thr,
        baseline_pos=baseline_panel,
        holding_period=config.holding_period,
        n_jobs=args.n_jobs,
    )

    gen_dir = Path(args.gen_dir)
    gen_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    idx = 1
    for r, (tree, _f) in zip(reaper_report["candidates"], candidates):
        if not r["survived"]:
            continue
        code = write_factor_code(tree, idx, r)
        fp = gen_dir / f"factor_{idx:03d}.py"
        fp.write_text(code, encoding="utf-8")
        generated.append(str(fp))
        idx += 1

    report = {
        "_meta": {
            "n_symbols": int(panel.index.get_level_values(0).nunique()),
            "n_days": int(panel.index.get_level_values(1).nunique()),
            "as_of": args.as_of,
            "lookback_days": args.lookback_days,
            "sample": not args.full,
            "seed": args.seed,
            "pop_size": pop_size,
            "n_generations": generations,
            "max_depth": args.max_depth,
            "holding_period": config.holding_period,
            "n_candidates": len(candidates),
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "baseline_positive_factors": baseline_pos,
        "reaper": reaper_report,
        "generated_files": generated,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = write_markdown(report, out_path.parent)
    print(f"\n📋 报告 → {out_path}")
    print(f"📋 Markdown → {md}")
    print(f"🏆 幸存因子 → {len(generated)} 个: {generated}")
    print(f"⏱ 总耗时 {time.time() - t0:.1f}s")


def max_depth_safe(v: int) -> int:
    return v or 5


if __name__ == "__main__":
    main()