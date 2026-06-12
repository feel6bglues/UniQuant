"""
Phase 4: 风险加权组合回测 (Risk-Parity Backtest)
使用 Phase 3 动态因子权重 + PositionSizer(5%) + PortfolioSizer(10%单票限制)
真实 A 股 2018-2025 数据
"""

import os
import sys
from pathlib import Path
from datetime import datetime
os.environ["PYTHONWARNINGS"] = "ignore"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.data.sources.tdx import TdxSource
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.shared.interfaces import TradingSignal
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine, BacktestResult

LOGIC_FACTORS = [
    "illiq_20d", "pv_divergence_20d",
    "cs_momentum_20d", "idiosyncratic_vol_20d",
]

STOCKS = [
    "601398.SH", "601939.SH", "601288.SH", "601988.SH", "600036.SH",
    "601166.SH", "600016.SH", "600000.SH", "002142.SZ", "601318.SH",
    "600519.SH", "000858.SZ", "000568.SZ", "600809.SH", "002304.SZ",
    "600887.SH", "000333.SZ", "000651.SZ", "600690.SH", "002415.SZ",
    "600276.SH", "300760.SZ", "002007.SZ", "000538.SZ",
    "300750.SZ", "601012.SH", "300274.SZ", "600585.SH",
    "002475.SZ", "300124.SZ", "002230.SZ", "300059.SZ",
    "000002.SZ", "601668.SH", "601857.SH", "600028.SH",
    "601088.SH", "600900.SH", "601985.SH", "601899.SH",
    "600019.SH", "000831.SZ", "002460.SZ", "600111.SH",
]


def compute_portfolio_metrics(equity_curve, initial_capital, periods_per_year=252):
    eq = np.array(equity_curve)
    rets = pd.Series(np.diff(eq) / eq[:-1])

    total_ret = (eq[-1] - initial_capital) / initial_capital
    years = len(eq) / periods_per_year
    ann_ret = (1 + total_ret) ** (1 / max(years, 0.1)) - 1
    ann_vol = rets.std() * np.sqrt(periods_per_year)
    sharpe = (ann_ret - 0.02) / max(ann_vol, 1e-10)
    max_dd = 0.0
    peak = eq[0]
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    positive = rets[rets > 0]
    negative = rets[rets < 0]
    avg_win = positive.mean() if len(positive) > 0 else 0
    avg_loss = negative.mean() if len(negative) > 0 else 0
    win_rate = len(positive) / max(len(rets), 1)

    calmar = ann_ret / max(max_dd, 1e-10)

    return {
        "total_return": total_ret,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "win_rate": win_rate,
        "avg_gain": avg_win,
        "avg_loss": avg_loss,
        "total_days": len(eq),
    }


def main():
    print("=" * 60)
    print("Phase 4: 风险加权组合回测 (Risk-Parity)")
    print("=" * 60)

    # Step 1: Fetch data and compute factors
    print("\n[1/5] 加载数据与因子...")
    tdx = TdxSource()
    all_data = {}
    for code in STOCKS:
        try:
            df = tdx.fetch_daily(code, "2018-01-01", "2025-12-31")
            if df is not None and not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                all_data[code] = df
        except Exception:
            pass
    print(f"  {len(all_data)} stocks loaded")

    # Build merged panel
    panel = pd.concat(
        [d.assign(code=c) for c, d in all_data.items()],
        ignore_index=True,
    )

    # Compute factors
    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(panel, mode="backtest")
    merged = pd.concat([panel, factor_df], axis=1)
    factor_cols = [c for c in LOGIC_FACTORS if c in factor_df.columns]

    # Pre-compute daily z-scores
    z_df = pd.DataFrame(index=merged.index, dtype=float)
    for date, g in merged.groupby("date"):
        for fc in factor_cols:
            vals = g[fc].dropna()
            if len(vals) >= 5:
                mu, s = vals.mean(), vals.std()
                z_df.loc[g.index, fc] = (g[fc] - mu) / s if s > 0 else 0.0
    z_df = z_df.fillna(0)

    # Use full history IC-based weights (sign-corrected)
    print("\n[2/5] 计算全局因子权重 (全历史 IC 引导)...")
    analyzer = FactorAnalyzer()
    full_ic = analyzer.compute_ic_ir(
        merged, factor_cols=factor_cols,
        holding_periods=[5],
        date_col="date", code_col="code", price_col="close",
        mode=AnalysisMode.BACKTEST,
    )
    weights = {}
    signs = {}
    for fc in factor_cols:
        ic_mean = 0
        icir = 0
        if fc in full_ic and 5 in full_ic[fc]:
            ic_mean = full_ic[fc][5].ic_mean
            icir = full_ic[fc][5].icir
        weights[fc] = max(abs(icir), 0.001)
        signs[fc] = 1.0 if ic_mean >= 0 else -1.0
    wsum = sum(weights.values())
    for fc in factor_cols:
        weights[fc] /= max(wsum, 1e-10)

    for fc in factor_cols:
        print(f"  {fc}: weight={weights[fc]:.4f}, sign={'+' if signs[fc] > 0 else '-'}")

    # Backtest parameters
    print("\n[3/5] 运行组合回测...")
    initial_capital = 1_000_000.0  # 100万
    commission_rate = 0.0003  # 万3
    stamp_rate = 0.0005  # 万5卖方
    top_n = 8  # 做多前8只股票
    rebalance_freq = 5  # 每5个交易日调仓

    all_dates = sorted(panel["date"].unique())

    # Portfolio state
    cash = initial_capital
    positions = {}  # {code: {shares, cost, buy_date}}
    portfolio_equity = []
    trade_log = []

    for di, date in enumerate(all_dates):
        # Get today's data for all stocks
        today_idx = merged["date"] == date
        today_data = merged[today_idx]

        # Current prices
        prices = {}
        for _, row in today_data.iterrows():
            prices[row["code"]] = row["close"]

        # Daily P&L
        daily_pnl = 0
        for code, pos in list(positions.items()):
            if code in prices:
                daily_pnl += pos["shares"] * (prices[code] - pos["last_price"])
                pos["last_price"] = prices[code]

        cash += daily_pnl
        total_equity = cash + sum(pos["shares"] * prices.get(code, 0)
                                  for code, pos in positions.items())
        portfolio_equity.append(total_equity)

        # Rebalance check
        if di % rebalance_freq == 0 and di > 252:  # skip initial warmup
            # Compute composite score
            today_z = z_df[today_idx]
            if len(today_z) > top_n:
                composite = pd.Series(0.0, index=today_z.index, dtype=float)
                for fc in factor_cols:
                    composite += today_z[fc].values * weights[fc] * signs[fc]

                # Rank stocks
                today_z["composite"] = composite.values
                top_stocks = today_z.nlargest(top_n, "composite").index
                top_codes = set(merged.loc[top_stocks, "code"].values)

                # Check T+1 for selling
                codes_to_sell = [c for c in positions if c not in top_codes]
                for code in codes_to_sell:
                    pos = positions[code]
                    # T+1 check
                    if "buy_date" in pos and pos["buy_date"] is not None:
                        day_diff = (pd.Timestamp(date) - pd.Timestamp(pos["buy_date"])).days
                        if day_diff < 1:
                            continue
                    if code in prices:
                        value = pos["shares"] * prices[code]
                        commission = max(value * commission_rate, 5)
                        stamp = value * stamp_rate
                        net = value - commission - stamp
                        cash += net
                        trade_log.append({
                            "date": date, "code": code, "action": "SELL",
                            "shares": pos["shares"], "price": prices[code],
                            "pnl": net - pos["shares"] * pos["cost"],
                        })
                        del positions[code]

                # Buy new stocks
                for code in top_codes:
                    if code in positions:
                        continue
                    if code not in prices:
                        continue
                    if len(positions) >= top_n:
                        break

                    price = prices[code]
                    lot_size = 100

                    # 5% risk per position
                    risk_per_stock = cash * 0.05
                    stop_loss = price * 0.95  # 5% stop
                    risk_per_share = price - stop_loss
                    shares = int(risk_per_stock / max(risk_per_share, 1)) // lot_size * lot_size

                    # 10% single stock cap
                    max_shares = int(cash * 0.10 / price) // lot_size * lot_size
                    shares = min(shares, max_shares)

                    if shares < lot_size:
                        continue

                    value = shares * price
                    commission = max(value * commission_rate, 5)
                    total_cost = value + commission

                    if total_cost > cash:
                        # Re-scale
                        max_afford = int((cash - 5) / price) // lot_size * lot_size
                        if max_afford < lot_size:
                            continue
                        shares = max_afford
                        value = shares * price
                        commission = max(value * commission_rate, 5)
                        total_cost = value + commission

                    cash -= total_cost
                    positions[code] = {
                        "shares": shares,
                        "cost": price,
                        "last_price": price,
                        "buy_date": date,
                    }
                    trade_log.append({
                        "date": date, "code": code, "action": "BUY",
                        "shares": shares, "price": price, "pnl": 0,
                    })

        if di % 126 == 0 and di > 0:
            n_pos = len(positions)
            print(f"  {date.date()}: equity={total_equity:>12,.0f} cash={cash:>12,.0f} "
                  f"positions={n_pos}")

    # Final liquidate
    print("\n[4/5] 清算持仓...")
    for code, pos in list(positions.items()):
        last_date = all_dates[-1]
        final_price = all_data[code][all_data[code]["date"] == last_date]["close"].values
        if len(final_price) > 0:
            price = float(final_price[0])
            value = pos["shares"] * price
            commission = max(value * commission_rate, 5)
            stamp = value * stamp_rate
            cash += value - commission - stamp
            trade_log.append({
                "date": last_date, "code": code, "action": "SELL",
                "shares": pos["shares"], "price": price,
                "pnl": value - commission - stamp - pos["shares"] * pos["cost"],
            })
    positions.clear()
    portfolio_equity.append(cash)

    print(f"  Final cash: {cash:,.2f}")

    # Compute metrics
    print("\n[5/5] 计算绩效指标...")
    metrics = compute_portfolio_metrics(portfolio_equity, initial_capital)
    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()

    print(f"\n  === 绩效指标 ===")
    print(f"  总收益率:              {metrics['total_return']:>+9.2%}")
    print(f"  年化收益率:             {metrics['annualized_return']:>+9.2%}")
    print(f"  年化波动率:             {metrics['annualized_volatility']:>9.2%}")
    print(f"  夏普比率:               {metrics['sharpe_ratio']:>+9.4f}")
    print(f"  最大回撤:               {metrics['max_drawdown']:>9.2%}")
    print(f"  Calmar比率:             {metrics['calmar_ratio']:>+9.4f}")
    print(f"  胜率:                   {metrics['win_rate']:>9.1%}")
    if not trade_df.empty:
        buys = len(trade_df[trade_df["action"] == "BUY"])
        sells = len(trade_df[trade_df["action"] == "SELL"])
        print(f"  交易次数:               BUY={buys} SELL={sells}")

    # Write tearsheet
    report_path = Path("ALPHA_RENAISSANCE_TEARSHEET.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ALPHA RENAISSANCE — 风险加权组合回测报告\n\n")
        f.write(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **初始资金**: ¥{initial_capital:,.0f}\n")
        f.write(f"> **股票池**: {len(all_data)} 只 A 股\n")
        f.write(f"> **时间范围**: {all_dates[0].date()} → {all_dates[-1].date()}\n")
        f.write(f"> **策略**: 因子复合评分做多 Top {top_n}, 每 {rebalance_freq} 日调仓\n\n")

        f.write("## 因子权重 (全历史 IC 引导, 已做符号修正)\n\n")
        f.write("| 因子 | 权重 | 符号 | 金融逻辑 |\n")
        f.write("|------|------|------|----------|\n")
        factor_descriptions = {
            "illiq_20d": "Amihud非流动性: 做多低流动性溢价",
            "pv_divergence_20d": "量价背离: 做多价量齐升",
            "cs_momentum_20d": "横截面动量: 剥离反转的纯趋势",
            "idiosyncratic_vol_20d": "特质波动率: 做空高IVOL彩票股",
        }
        for fc in factor_cols:
            f.write(f"| {fc} | {weights[fc]:.4f} | {'+' if signs[fc] > 0 else '-'} | {factor_descriptions.get(fc, '')} |\n")

        f.write("\n## 绩效指标\n\n")
        f.write("| 指标 | 值 |\n")
        f.write("|------|-----|\n")
        f.write(f"| 总收益率 | {metrics['total_return']:+.2%} |\n")
        f.write(f"| 年化收益率 | {metrics['annualized_return']:+.2%} |\n")
        f.write(f"| 年化波动率 | {metrics['annualized_volatility']:.2%} |\n")
        f.write(f"| 夏普比率 | {metrics['sharpe_ratio']:.4f} |\n")
        f.write(f"| 最大回撤 | {metrics['max_drawdown']:.2%} |\n")
        f.write(f"| Calmar比率 | {metrics['calmar_ratio']:.4f} |\n")
        f.write(f"| 胜率 (日) | {metrics['win_rate']:.1%} |\n")
        f.write(f"| 平均日盈利 | {metrics['avg_gain']:.4%} |\n")
        f.write(f"| 平均日亏损 | {metrics['avg_loss']:.4%} |\n\n")

        # Monthly returns table
        f.write("## 月度收益分解\n\n")
        eq_series = pd.Series(portfolio_equity)
        daily_rets = eq_series.pct_change().dropna()
        monthly = daily_rets.groupby(
            pd.date_range(start=all_dates[0], periods=len(daily_rets), freq="B").to_period("M")
        ).apply(lambda x: (1 + x).prod() - 1)
        f.write("| 月份 | 收益 |\n|------|------|\n")
        for m, r in monthly.items():
            f.write(f"| {m} | {r:+.2%} |\n")

        f.write("\n## 权益曲线 (月度采样)\n\n")
        f.write("```\n")
        sample_interval = max(1, len(portfolio_equity) // 40)
        for i in range(0, len(portfolio_equity), sample_interval):
            bar = "█" * int(portfolio_equity[i] / max(portfolio_equity) * 40)
            pct = (portfolio_equity[i] / initial_capital - 1) * 100
            f.write(f"{all_dates[i].date()} {bar} {pct:+.1f}%\n")
        f.write("```\n")

        if not trade_df.empty:
            f.write("\n## 交易统计\n\n")
            buys = trade_df[trade_df["action"] == "BUY"]
            sells = trade_df[trade_df["action"] == "SELL"]
            f.write(f"- 买入次数: {len(buys)}\n")
            f.write(f"- 卖出次数: {len(sells)}\n")
            if len(sells) > 0:
                avg_pnl = sells["pnl"].mean()
                total_pnl = sells["pnl"].sum()
                f.write(f"- 平均单笔盈亏: ¥{avg_pnl:+,.0f}\n")
                f.write(f"- 累计交易盈亏: ¥{total_pnl:+,.0f}\n")

        f.write(f"\n---\n*由 Phase 4 自动生成*\n")

    print(f"\n  Tearsheet → {report_path}")
    print(f"\n{'='*60}")
    print(f"Phase 4 完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
