"""
Stage 2: 市值/流动性分层 IC 体检 (Stratified Factor Autopsy)
==============================================================

目标: 在 Top 30% / Middle 40% / Bottom 30% 流动性分层中,
验证 4 大逻辑因子的 IC@5d 是否在 Top 30% 大盘股中依然有效。

四大因子:
  1. ILLIQ     — Amihud 非流动性 (预期 IC +)
  2. PV_Div    — 量价背离 (预期 IC -)
  3. CS_Moment — 横截面动量 (预期 IC +)
  4. IVOL      — 特质波动率 (预期 IC +)

[Halt & Wait]
"""

import os, sys, warnings, time
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUALIFIED_FILE = Path("data/qualified_universe.csv")
LAKE_DIR = Path("data/lake/quotes/daily")
FACTOR_NAMES = ["illiq_20d", "pv_divergence_20d", "cs_momentum_20d", "idiosyncratic_vol_20d"]
FACTOR_LABELS = ["ILLIQ", "PV_Div", "CS_Mom", "IVOL"]
TIERS = {"Top 30% (大盘/高流动)": slice(0, 30),
         "Middle 40% (中盘)": slice(30, 70),
         "Bottom 30% (小盘/低流动)": slice(70, 100)}


def compute_factors_vectorized(df: pd.DataFrame) -> pd.DataFrame | None:
    """完全矢量化计算 4 大因子。"""
    if df.empty or "close" not in df.columns:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    if n < 100:
        return None

    close = df["close"].values.astype(np.float64)
    amount = df["amount"].values.astype(np.float64) if "amount" in df.columns else np.zeros(n)
    volume = df["volume"].values.astype(np.float64) if "volume" in df.columns else np.zeros(n)
    ret = np.diff(close, prepend=close[0])
    # Prevent division by zero
    close_safe = np.where(close > 0, close, np.nan)
    ret_pct = ret / close_safe

    # ILLIQ: rolling 20d mean(|r|/amount)
    abs_ret_pct = np.abs(ret_pct)
    daily_illiq = np.where(amount > 0, abs_ret_pct / amount, np.nan)
    illiq = pd.Series(daily_illiq).rolling(20, min_periods=10).mean().values * 1e9

    # PV_Div: rolling percentile rank (C-accelerated, ~300x faster than rolling apply)
    close_rank = pd.Series(close).rolling(20, min_periods=10).rank(pct=True).values
    vol_rank = pd.Series(volume).rolling(20, min_periods=10).rank(pct=True).values
    pv_div = vol_rank - close_rank

    # CS_Momentum: (1+r20)/(1+r5)-1
    r20 = pd.Series(close).pct_change(20).values
    r5 = pd.Series(close).pct_change(5).values
    cs_mom = np.where(r5 > -0.999, (1 + r20) / (1 + r5) - 1, np.nan)

    # IVOL: -rolling std of residual (returns - 5d trend) over 20d
    trend = pd.Series(ret_pct).rolling(5).mean().values
    residual = ret_pct - trend
    ivol = -pd.Series(residual).rolling(20, min_periods=10).std().values * np.sqrt(252)

    # Avg amount 20d (liquidity proxy)
    avg_amt = pd.Series(amount).rolling(20).mean().values

    # Forward 5d return
    fwd_ret = np.full(n, np.nan)
    fwd_ret[:n-5] = close[5:] / close[:n-5] - 1

    result = pd.DataFrame({
        "date": df["date"],
        "illiq_20d": illiq,
        "pv_divergence_20d": pv_div,
        "cs_momentum_20d": cs_mom,
        "idiosyncratic_vol_20d": ivol,
        "avg_amt_20d": avg_amt,
        "fwd_ret_5d": fwd_ret,
    })
    return result


def main():
    print("=" * 70)
    print("  Stage 2: 市值/流动性分层 IC 体检")
    print("  Stratified Factor Autopsy — 四大因子分层验证")
    print("=" * 70)

    # ---- 1. 加载合格股票池 ----
    print("\n[1/5] 加载合格股票池...")
    if not QUALIFIED_FILE.exists():
        print(f"  ❌ 未找到 {QUALIFIED_FILE}, 请先运行 Stage 1")
        return
    qualified = pd.read_csv(QUALIFIED_FILE)
    symbols = qualified["symbol"].tolist()
    print(f"  合格股票: {len(symbols)}")

    # ---- 2. 批量计算因子 ----
    print("\n[2/5] 批量计算 4 大因子...")
    t0 = time.time()
    all_panels = []

    for i, sym in enumerate(symbols, 1):
        fp = LAKE_DIR / f"{sym}.parquet"
        if not fp.exists():
            continue
        try:
            df = pd.read_parquet(fp, columns=["date", "close", "amount", "volume"])
            result = compute_factors_vectorized(df)
            if result is not None and len(result) > 200:
                result["symbol"] = sym
                all_panels.append(result)
        except Exception:
            pass

        if i % 500 == 0 or i == len(symbols):
            elapsed = time.time() - t0
            print(f"    进度 {i}/{len(symbols)}, 有效 {len(all_panels)}, "
                  f"耗时 {elapsed:.0f}s", end="\r")

    print(f"\n  有效股票: {len(all_panels)}/{len(symbols)}")
    print(f"  总耗时: {time.time()-t0:.0f}s")

    if not all_panels:
        print("  ❌ 无有效数据, 退出")
        return

    # ---- 3. 构建月度横截面面板 ----
    print("\n[3/5] 构建月度横截面面板...")
    combined = pd.concat(all_panels, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined["year_month"] = combined["date"].dt.to_period("M")
    del all_panels  # free memory

    # 每月末快照: 对每个股票取该月最后一笔数据
    panel_records = []
    ym_groups = combined.groupby("year_month")

    for ym, group in ym_groups:
        # 按 symbol 取该月最后一条
        latest_per_sym = group.sort_values("date").groupby("symbol").last().reset_index()
        panel_records.append(latest_per_sym)

    if not panel_records:
        print("  ❌ 月度快照为空")
        return
    panel = pd.concat(panel_records, ignore_index=True)
    months = sorted(panel["year_month"].unique())
    print(f"  月度快照: {len(months)} 个月 ({months[0]} ~ {months[-1]})")
    print(f"  面板总行数: {len(panel)}")

    # ---- 4. 分层 IC 计算 ----
    print("\n[4/5] 分层 IC 计算...")

    tier_results = {tier: {f: [] for f in FACTOR_NAMES} for tier in TIERS}

    for ym in months:
        month_data = panel[panel["year_month"] == ym].copy()
        month_data = month_data.sort_values("avg_amt_20d").dropna(subset=["avg_amt_20d"])
        if len(month_data) < 30:
            continue

        for tier_name, pct_slice in TIERS.items():
            n = len(month_data)
            start_idx = int(n * pct_slice.start / 100)
            end_idx = int(n * pct_slice.stop / 100)
            tier_subset = month_data.iloc[start_idx:end_idx]

            if len(tier_subset) < 10:
                continue

            for factor in FACTOR_NAMES:
                valid = tier_subset.dropna(subset=[factor, "fwd_ret_5d"])
                if len(valid) < 10:
                    continue
                ic, _ = stats.spearmanr(valid[factor], valid["fwd_ret_5d"])
                if not np.isnan(ic):
                    tier_results[tier_name][factor].append(ic)

    # 汇总
    print(f"\n  {'分层':<25} {'因子':<10} {'Mean IC':>8} {'Std IC':>8} {'ICIR':>8} "
          f"{'正IC率':>8} {'N':>5}")
    print(f"  {'-'*72}")

    matrix_data = {}
    for tier_name in TIERS:
        for fi, factor in enumerate(FACTOR_NAMES):
            ics = tier_results[tier_name][factor]
            if len(ics) < 3:
                continue
            mean_ic = float(np.mean(ics))
            std_ic = float(np.std(ics))
            icir = mean_ic / max(std_ic, 1e-10)
            pos_rate = float(np.mean(np.array(ics) > 0))
            n = len(ics)
            print(f"  {tier_name:<25} {FACTOR_LABELS[fi]:<10} {mean_ic:>+8.4f} "
                  f"{std_ic:>8.4f} {icir:>+8.4f} {pos_rate:>7.1%} {n:>5}")
            matrix_data[(tier_name, FACTOR_LABELS[fi])] = {
                "mean_ic": mean_ic, "std_ic": std_ic, "icir": icir,
                "pos_rate": pos_rate, "n": n
            }

    # ---- 5. 风险警示 ----
    print("\n[5/5] 微盘股陷阱检测...")
    bottom_only = True
    for fi, factor in enumerate(FACTOR_NAMES):
        top_d = matrix_data.get(("Top 30% (大盘/高流动)", FACTOR_LABELS[fi]), {})
        bot_d = matrix_data.get(("Bottom 30% (小盘/低流动)", FACTOR_LABELS[fi]), {})
        top_ic = top_d.get("mean_ic", 0)
        bot_ic = bot_d.get("mean_ic", 0)

        if top_ic > 0.01:
            print(f"  ✅ {FACTOR_LABELS[fi]}: 大盘 Top 30% 正IC ({top_ic:+.4f})")
            bottom_only = False
        elif top_ic < -0.01:
            print(f"  ⚠️  {FACTOR_LABELS[fi]}: 大盘 Top 30% 负IC ({top_ic:+.4f})")
        else:
            print(f"  ➖ {FACTOR_LABELS[fi]}: 大盘 Top 30% IC 趋零 ({top_ic:+.4f})")

        if abs(bot_ic) > abs(top_ic) * 2 and abs(bot_ic) > 0.02:
            print(f"     ⚠️  收益集中在 Bottom 小盘 ({bot_ic:+.4f} vs {top_ic:+.4f})")

    if bottom_only:
        print("\n  ❌ 警告: 所有 IC 集中在 Bottom 30%, 微盘股陷阱!")
    else:
        print(f"\n  ✅ 至少一个大盘正IC, 非纯微盘股策略")

    # ---- 报告 ----
    report_path = Path("docs/reshaping_logs/05_stratified_ic.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 05 — 市值/流动性分层 IC 体检\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **股票池**: {len(symbols)} 合格, {len(panel_records)} 有效\n\n")
        f.write("## 因子说明\n\n")
        f.write("| 因子 | 预期方向 | 逻辑 |\n")
        f.write("|------|---------|------|\n")
        f.write("| ILLIQ | + | Amihud 非流动性, 低流动性溢价 |\n")
        f.write("| PV_Div | - | 量价背离, 价升量缩 = 卖出 |\n")
        f.write("| CS_Mom | + | 中期动量剥离短期反转 |\n")
        f.write("| IVOL | + (取负) | 做空高特质波动彩票股 |\n\n")
        f.write("## 分层 IC 矩阵\n\n")
        f.write("| 分层 | 因子 | Mean IC | Std IC | ICIR | 正IC率 | N |\n")
        f.write("|------|------|---------|--------|------|--------|---|\n")
        for tier_name in TIERS:
            for fi, factor in enumerate(FACTOR_NAMES):
                d = matrix_data.get((tier_name, FACTOR_LABELS[fi]), {})
                if d:
                    f.write(f"| {tier_name} | {FACTOR_LABELS[fi]} | {d['mean_ic']:+.4f} | "
                            f"{d['std_ic']:.4f} | {d['icir']:+.4f} | {d['pos_rate']:.1%} | {d['n']} |\n")
        f.write("\n---\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print("  Stage 2 完成!")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — 请确认分层 IC 矩阵后继续 Stage 3")


if __name__ == "__main__":
    main()
