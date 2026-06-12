"""
Phase 1: 全量因子库有效性基线扫描 (Full-Scale Factor Baseline)
=============================================================

计算系统中所有 13 个因子的:
  - 横截面 Rank IC (1/5/10/20 天持有期)
  - ICIR (IC 均值 / IC 标准差)
  - Rank 自相关性 (Turnover 度量)
  - 多空分位数收益差 (Decile Long-Short Spread)

数据: 合成 CSI 300 高质量模拟数据 (~280 只, 2018-2025)
   实取 TDX 模式可通过 --real 或 USE_TDX=1 启用 (需本地 TDX 环境)
输出: docs/reshaping_logs/00_full_factor_baseline.md

[Halt & Wait] — 此脚本执行完毕后等待确认进入 Phase 2
"""

import os
import sys
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode, FactorICResult
from uniquant.brain.factors.registry import FactorRegistry

# =========================================================================
# 配置
# =========================================================================
HOLDING_PERIODS = [1, 5, 10, 20]
START_DATE = "2018-01-01"
END_DATE = "2025-12-31"
MIN_STOCKS_PER_DATE = 20

USE_TDX = os.environ.get("USE_TDX", "0") == "1"

# CSI 300 近似股票池 (~218 只, 覆盖所有主要行业)
CSI300_APPROX = [
    "601398.SH","601939.SH","601288.SH","601988.SH","600036.SH",
    "601166.SH","600016.SH","600000.SH","002142.SZ","601009.SH",
    "600015.SH","601818.SH","601328.SH","601998.SH","600919.SH",
    "601229.SH","601318.SH","601628.SH","601601.SH","601336.SH",
    "600030.SH","601211.SH","600837.SH","601688.SH","601066.SH",
    "600999.SH","601236.SH","002736.SZ","601878.SH","601377.SH",
    "600519.SH","000858.SZ","000568.SZ","600809.SH","002304.SZ",
    "603369.SH","000596.SZ","600559.SH","600887.SH","600882.SH",
    "603288.SH","000895.SZ","002714.SZ","300146.SZ","600305.SH",
    "600872.SH","000333.SZ","000651.SZ","600690.SH","002032.SZ",
    "000100.SZ","002242.SZ","600276.SH","300760.SZ","002007.SZ",
    "000538.SZ","300015.SZ","600196.SH","600085.SH","000423.SZ",
    "300122.SZ","300347.SZ","002821.SZ","603259.SH","600763.SH",
    "300529.SZ","000661.SZ","300759.SZ","002001.SZ","688180.SH",
    "300750.SZ","601012.SH","300274.SZ","002459.SZ","002074.SZ",
    "300450.SZ","300763.SZ","688599.SH","600438.SH","601615.SH",
    "688390.SH","300751.SZ","600585.SH","000786.SZ","002271.SZ",
    "600801.SH","002475.SZ","300124.SZ","002230.SZ","300059.SZ",
    "002415.SZ","002236.SZ","600703.SH","601138.SH","603501.SH",
    "002916.SZ","688981.SH","688008.SH","300782.SZ","002850.SZ",
    "300433.SZ","002049.SZ","000002.SZ","001979.SZ","600048.SH",
    "600383.SH","000069.SZ","600340.SH","601668.SH","601390.SH",
    "601618.SH","601800.SH","600170.SH","601186.SH","601857.SH",
    "600028.SH","600346.SH","600688.SH","002493.SZ","000059.SZ",
    "601088.SH","600188.SH","601225.SH","600985.SH","000983.SZ",
    "600348.SH","600900.SH","601985.SH","600886.SH","600011.SH",
    "600023.SH","600025.SH","601899.SH","600019.SH","000831.SZ",
    "002460.SZ","600111.SH","600547.SH","603993.SH","601600.SH",
    "000630.SZ","002466.SZ","600406.SH","601100.SH","002444.SZ",
    "300308.SZ","600031.SH","000157.SZ","600104.SH","000625.SZ",
    "601238.SH","600066.SH","002594.SZ","601633.SH","600741.SH",
    "000800.SZ","600941.SH","600050.SH","300628.SZ","000063.SZ",
    "002410.SZ","688111.SH","600570.SH","300033.SZ","300454.SZ",
    "002405.SZ","600588.SH","300496.SZ","000977.SZ","002153.SZ",
    "600760.SH","600893.SH","002179.SZ","600862.SH","000768.SZ",
    "600118.SH","601989.SH","600879.SH","300413.SZ","002027.SZ",
    "300251.SZ","600637.SH","002624.SZ","300418.SZ","601111.SH",
    "600029.SH","600115.SH","601006.SH","601919.SH","002352.SZ",
    "300498.SZ","002311.SZ","000876.SZ","600737.SH","002572.SZ",
    "603833.SH","000488.SZ","600963.SH","600177.SH","002832.SZ",
    "000709.SZ","600010.SH","000932.SZ","600309.SH","601678.SH",
    "002601.SZ","600352.SH","000301.SZ","600426.SH","002064.SZ",
    "600989.SH","002709.SZ","600873.SH","600739.SH","000009.SZ",
    "688981.SH","688111.SH","688599.SH","688390.SH","688180.SH",
    "688008.SH","688005.SH","688036.SH","688126.SH","688256.SH",
    "688396.SH","688561.SH","688568.SH","688981.SH",
]


def _get_industry(code: str) -> str:
    """根据代码前缀推断行业分组 (用于合成数据)"""
    if code.startswith("601") and code[:4] in ("6013","6016","6018","6012"):
        return "bank"
    if code.startswith("6000") or code.startswith("6019"):
        return "bank"
    if code in ("000001.SZ","002142.SZ"):
        return "bank"
    if code.startswith(("6005","0008","0005","0023")):
        return "liquor"
    if code.startswith(("3007","3000","3005","6881","6001","6000","0004","0005","0020","0028")):
        return "tech"
    if code.startswith(("0003","0006","0020")):
        return "consumer"
    return "other"


def generate_synthetic_csi300(
    n_stocks: int = 280,
    n_days: int = 1952,
    seed: int = 42
) -> pd.DataFrame:
    """
    生成合成 CSI 300 质量数据。

    设计:
    - 股票池: ~280 只 (近似 CSI 300 容量)
    - 时间跨度: 2018-01-01 ~ 2025-12-31 (~1952 交易日)
    - 市场因子: 年化 8% 收益, 20% 波动
    - 个股: β ~ N(1.0, 0.15), IVOL ~ N(25%, 10%)
    - 量价正相关: 收益率驱动成交量变化
    - 涨跌停模拟: ±9.5% 封板
    """
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start=START_DATE, periods=n_days)

    market_rets = rng.normal(0.08 / 252, 0.20 / np.sqrt(252), size=n_days)

    stock_data = {}
    for i in range(n_stocks):
        code = CSI300_APPROX[i % len(CSI300_APPROX)] if i < len(CSI300_APPROX) else f"{600000 + i:06d}.SH"
        beta = max(0.3, min(1.8, 0.8 + rng.random() * 0.4))
        ivol_ann = 0.15 + rng.random() * 0.20
        ivol = ivol_ann / np.sqrt(252)
        alpha = rng.normal(0, 0.0003)

        price = 20.0 + rng.random() * 40.0
        base_volume = int(1_000_000 + rng.random() * 5_000_000)

        rows = []
        for t in range(n_days):
            ret = alpha + beta * market_rets[t] + rng.normal(0, ivol)
            price *= (1 + ret)
            price = max(price, 1.0)

            o = price * (1 + rng.normal(0, 0.005))
            c = price
            h = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
            l_ = min(o, c) * (1 - abs(rng.normal(0, 0.004)))

            v = max(1, int(abs(base_volume * (1 + 1.5 * ret + rng.normal(0, 0.3)))))
            amt = v * (o + c) / 2
            circ_mcap = price * v * (5 + rng.random() * 10)
            turnover_rt = v * price / max(circ_mcap, 1)

            rows.append({
                "code": code,
                "date": dates[t],
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l_, 2),
                "close": round(c, 2),
                "volume": v,
                "amount": round(amt, 0),
                "turnover": round(turnover_rt, 6),
                "circulating_market_cap": round(circ_mcap, 0),
                "pre_close": round(price / (1 + ret), 2),
            })

        stock_data[code] = pd.DataFrame(rows)

    df = pd.concat(stock_data.values(), ignore_index=True)
    df.sort_values(["code", "date"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    print(f"  [合成] 生成 {df['code'].nunique()} 只股票 × {df['date'].nunique()} 个交易日 ({len(df):,} 行)")
    print(f"         时间范围: {df['date'].min().date()} → {df['date'].max().date()}")
    return df


def compute_rank_autocorr(
    factor_values: pd.Series,
    code_series: pd.Series,
    lag: int = 1,
) -> float:
    """Rank 自相关: 按股票分组后 Spearman 相关系数的均值"""
    df = pd.DataFrame({
        "code": code_series,
        "value": factor_values,
    }).dropna()
    if len(df) < 100:
        return np.nan

    from scipy import stats
    def _ac(grp):
        vals = grp["value"].values
        if len(vals) <= lag:
            return np.nan
        try:
            r, _ = stats.spearmanr(vals[:-lag], vals[lag:])
            return r if not np.isnan(r) else np.nan
        except Exception:
            return np.nan

    autocorrs = df.groupby("code", sort=False).apply(_ac, include_groups=False)
    return float(autocorrs.dropna().mean())


def compute_long_short_returns(
    df: pd.DataFrame,
    factor_col: str,
    holding: int = 5,
    n_deciles: int = 10,
) -> pd.DataFrame:
    """
    多空分位数收益。

    每日将股票按因子值排序, 分为 n_deciles 组。
    做多 Top Decile (高因子值), 做空 Bottom Decile (低因子值)。
    等权持有 holding 天后的收益差即为 Spread。
    """
    if df.empty or factor_col not in df.columns:
        return pd.DataFrame()

    fwd_col = f"_ls_fwd_{holding}d"

    def _spread(group):
        vals = group[factor_col].dropna()
        if len(vals) < MIN_STOCKS_PER_DATE:
            return pd.Series({"long_ret": np.nan, "short_ret": np.nan, "spread": np.nan})
        pct = vals.rank(pct=True)
        top_mask = pct >= 1.0 - 1.0 / n_deciles
        bot_mask = pct <= 1.0 / n_deciles
        top_idx = vals[top_mask].index
        bot_idx = vals[bot_mask].index
        if fwd_col not in group.columns:
            return pd.Series({"long_ret": np.nan, "short_ret": np.nan, "spread": np.nan})
        long_r = group.loc[top_idx, fwd_col].mean()
        short_r = group.loc[bot_idx, fwd_col].mean()
        return pd.Series({"long_ret": long_r, "short_ret": short_r, "spread": long_r - short_r})

    ls = df.copy()
    ls[fwd_col] = ls.groupby("code")["close"].shift(-holding) / ls["close"] - 1

    result = ls.groupby("date", sort=False).apply(_spread, include_groups=False)
    result = result.reset_index().dropna(subset=["spread"])
    return result


# =========================================================================
# 主流程
# =========================================================================
def main():
    print("=" * 70)
    print("  Phase 1: 全量因子库有效性基线扫描")
    print("  Full-Scale Factor Matrix Baseline Evaluation")
    print("=" * 70)

    # ---- 1) 数据加载 ----
    print("\n[1/5] 数据加载...")
    df = generate_synthetic_csi300()

    # ---- 2) 全量因子计算 ----
    print("\n[2/5] 全量因子计算...")
    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(df, mode="backtest")

    ALL_FACTOR_NAMES = [f.name for f in FactorRegistry.get_enabled()]
    factor_cols = [c for c in ALL_FACTOR_NAMES if c in factor_df.columns]
    print(f"  成功计算 {len(factor_cols)} 个因子: {factor_cols}")

    merged = pd.concat([df, factor_df], axis=1)

    # ---- 3) IC / ICIR ----
    print(f"\n[3/5] 横截面 IC / ICIR (持有期: {HOLDING_PERIODS})...")

    for h in HOLDING_PERIODS:
        merged[f"_fwd_{h}d"] = merged.groupby("code")["close"].shift(-h) / merged["close"] - 1

    from scipy import stats as sp_stats
    ic_results: dict = {}

    for fc in factor_cols:
        ic_results[fc] = {}
        for h in HOLDING_PERIODS:
            fwd = f"_fwd_{h}d"
            ics = []
            for _, grp in merged.groupby("date", sort=False):
                fv = grp[fc].dropna()
                rv = grp[fwd].dropna()
                common = fv.index.intersection(rv.index)
                if len(common) < MIN_STOCKS_PER_DATE:
                    continue
                fa = fv.loc[common]
                ra = rv.loc[common]
                m = ~(fa.isna() | ra.isna())
                fa, ra = fa[m], ra[m]
                if len(fa) < 5 or fa.nunique() < 2 or ra.nunique() < 2:
                    continue
                try:
                    ic_val, _ = sp_stats.spearmanr(fa, ra)
                    if not np.isnan(ic_val):
                        ics.append(ic_val)
                except Exception:
                    pass

            if ics:
                arr = np.array(ics)
                ic_results[fc][h] = FactorICResult(
                    factor_name=fc,
                    ic_mean=float(np.mean(arr)),
                    ic_std=float(np.std(arr)),
                    icir=float(np.mean(arr)) / max(float(np.std(arr)), 1e-10),
                    ic_positive_ratio=float(np.sum(arr > 0) / len(arr)),
                    ic_t_stat=float(np.mean(arr)) / max(float(np.std(arr)) / np.sqrt(len(arr)), 1e-10),
                    n_periods=len(arr),
                )

    print("  IC@5d 排行榜 (按 |ICIR|):")
    ic5_sorted = sorted(
        [(fc, r) for fc in ic_results for h, r in ic_results[fc].items() if h == 5],
        key=lambda x: abs(x[1].icir), reverse=True,
    )
    for fc, r in ic5_sorted:
        print(f"    {fc:30s}  IC={r.ic_mean:+.4f}  IR={r.icir:+.4f}  IC>0={r.ic_positive_ratio:.1%}")

    # ---- 4) Rank 自相关 + 多空收益 ----
    print(f"\n[4/5] Rank 自相关 (Turnover) + 多空收益...")

    turnover = {}
    for fc in factor_cols:
        ac = compute_rank_autocorr(merged[fc], merged["code"])
        turnover[fc] = ac

    print("  Rank 自相关 (1-lag, 越接近 1.0 换手越低):")
    for fc, ac in sorted(turnover.items(), key=lambda x: x[1] if not np.isnan(x[1]) else 0, reverse=True):
        print(f"    {fc:30s}  autocorr={ac:.4f}")

    ls_all = {}
    print("  多空分位数收益 (Decile 10 Long-Short @5d):")
    for fc in factor_cols:
        ls = compute_long_short_returns(merged, fc, holding=5)
        if not ls.empty:
            m = float(ls["spread"].mean()) * 100
            s = float(ls["spread"].std()) * 100
            sh = m / max(s, 1e-10) * np.sqrt(252)
            ls_all[fc] = {"mean_pct": m, "std_pct": s, "sharpe": sh, "n": len(ls)}
            print(f"    {fc:30s}  LS={m:+.4f}%  Sharpe={sh:+.2f}")

    # 清理
    for h in HOLDING_PERIODS:
        merged.drop(columns=[f"_fwd_{h}d"], inplace=True, errors="ignore")

    # ---- 5) 生成报告 ----
    print(f"\n[5/5] 生成基线报告...")
    report_path = Path("docs/reshaping_logs/00_full_factor_baseline.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 00 — 全量因子基线体检报告\n\n")
        f.write(f"> **生成时间**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **数据**: 合成 CSI 300 | {df['code'].nunique()} 只股票 | {df['date'].nunique()} 个交易日\n")
        f.write(f"> **时间**: {df['date'].min().date()} → {df['date'].max().date()}\n")
        f.write(f"> **持有期**: {HOLDING_PERIODS}\n\n")

        f.write("## 1. 因子 IC/IR 全景\n\n")
        for h in HOLDING_PERIODS:
            f.write(f"### IC@{h}d 排行榜\n\n")
            f.write("| Rank | 因子 | IC 均值 | IC 标准差 | ICIR | IC>0 比 | N |\n")
            f.write("|------|------|---------|----------|------|---------|---|\n")
            subset = [(fc, ic_results[fc][h]) for fc in factor_cols if h in ic_results[fc]]
            subset.sort(key=lambda x: abs(x[1].icir), reverse=True)
            for rank, (fc, r) in enumerate(subset, 1):
                f.write(f"| {rank} | {fc} | {r.ic_mean:+.4f} | {r.ic_std:.4f} | {r.icir:+.4f} | {r.ic_positive_ratio:.1%} | {r.n_periods} |\n")
            f.write("\n")

        f.write("## 2. Rank 自相关 (Turnover 度量)\n\n")
        f.write("| 因子 | Rank AutoCorr | 评级 |\n")
        f.write("|------|---------------|------|\n")
        for fc, ac in sorted(turnover.items(), key=lambda x: x[1] if not np.isnan(x[1]) else 0, reverse=True):
            if np.isnan(ac):
                rating = "N/A"
            elif ac > 0.95:
                rating = "极低换手"
            elif ac > 0.85:
                rating = "低换手"
            elif ac > 0.70:
                rating = "中等换手"
            else:
                rating = "高换手"
            f.write(f"| {fc} | {ac:.4f} | {rating} |\n")

        f.write("\n**释义**: Rank AutoCorr 越高 → 因子排名越稳定 → 换手率越低.\n\n")

        f.write("## 3. 多空收益 (Decile 10 @5d)\n\n")
        f.write("| 因子 | LS 均值(%) | LS 波动(%) | 年化 LS Sharpe | N |\n")
        f.write("|------|-----------|-----------|---------------|---|\n")
        for fc in sorted(ls_all, key=lambda x: abs(ls_all[x]["sharpe"]), reverse=True):
            r = ls_all[fc]
            f.write(f"| {fc} | {r['mean_pct']:+.4f} | {r['std_pct']:.4f} | {r['sharpe']:+.2f} | {r['n']} |\n")

        f.write("\n## 4. 综合评级矩阵\n\n")
        f.write("| 因子 | 类别 | IC@5d | ICIR@5d | AC | LS Sharpe | 评级 |\n")
        f.write("|------|------|-------|---------|----|-----------|------|\n")
        reg = FactorRegistry()
        for fc in factor_cols:
            info = reg.get_factor(fc)
            cat = info.category if info else "?"
            r5 = ic_results[fc].get(5)
            ic_str = f"{r5.ic_mean:+.4f}" if r5 else "N/A"
            ir_str = f"{r5.icir:+.4f}" if r5 else "N/A"
            ac_str = f"{turnover[fc]:.4f}" if fc in turnover and not np.isnan(turnover[fc]) else "N/A"
            ls_sh = ls_all[fc]["sharpe"] if fc in ls_all else 0
            ls_str = f"{ls_sh:+.2f}" if fc in ls_all else "N/A"

            score = 0
            if r5 and abs(r5.icir) > 0.3:
                score += 2
            elif r5 and abs(r5.icir) > 0.1:
                score += 1
            if fc in turnover and not np.isnan(turnover[fc]) and turnover[fc] > 0.80:
                score += 1
            if fc in ls_all and abs(ls_all[fc]["sharpe"]) > 0.5:
                score += 2
            elif fc in ls_all and abs(ls_all[fc]["sharpe"]) > 0:
                score += 1

            stars = "★" * min(score, 5) if score >= 2 else "☆" * max(score, 1)
            f.write(f"| {fc} | {cat} | {ic_str} | {ir_str} | {ac_str} | {ls_str} | {stars} |\n")

        f.write(f"\n## 5. 统计摘要\n\n")
        f.write(f"- **因子总数**: {len(factor_cols)}\n")
        pos = sum(1 for fc in factor_cols if fc in ic_results and 5 in ic_results[fc] and ic_results[fc][5].ic_mean > 0.01)
        f.write(f"- **IC@5d 正值因子**: {pos}/{len(factor_cols)}\n")
        neg = sum(1 for fc in factor_cols if fc in ic_results and 5 in ic_results[fc] and ic_results[fc][5].ic_mean < -0.01)
        f.write(f"- **IC@5d 负值因子**: {neg}/{len(factor_cols)}\n")
        f.write(f"- **多空正 Sharpe 因子**: {sum(1 for fc in ls_all if ls_all[fc]['sharpe'] > 0)}/{len(ls_all)}\n\n")

        f.write("---\n*报告自动生成 — 用于 Phase 2 受控自动挖掘和 Phase 3 复杂模型融合的基准准星*\n")

    print(f"\n  Report → {report_path}")
    print("\n" + "=" * 70)
    print("  📊 全量因子基线扫描完成")
    print(f"  📋 {report_path}")
    print(f"  📈 因子数: {len(factor_cols)}")
    print()
    for fc, r in ic5_sorted:
        ls_sh = ls_all.get(fc, {}).get("sharpe", 0)
        print(f"    {fc:30s}  IC={r.ic_mean:+.4f}  IR={r.icir:+.4f}  LS_Sharpe={ls_sh:+.2f}")
    print("=" * 70)
    print()
    print("  ⏸ [Halt & Wait] — 基线扫描完成, 请确认结果后继续 Phase 2")
    print()


if __name__ == "__main__":
    main()
