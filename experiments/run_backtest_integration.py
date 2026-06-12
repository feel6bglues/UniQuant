"""
Phase 3: Backtest Integration

Multi-stock approach:
1. Generate 5 stocks for cross-sectional IC (differentiated weights)
2. Compute per-stock composite score from IR weights
3. Run UnifiedBacktestEngine on each stock individually
4. Aggregate portfolio-level metrics

Output: docs/reshaping_logs/11_backtest_integration.md
"""

import datetime
import os
import sys
import warnings
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
warnings.filterwarnings("ignore")

import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.shared.interfaces import TradingSignal


def generate_multi_stock_data(n_stocks=5, n_days=504, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2021-01-01", periods=n_days)
    rows = []
    for si in range(n_stocks):
        code = f"{600000 + si}.SH"
        price = 50.0 + rng.random() * 30.0
        phi = rng.random() * 2 * np.pi
        for d in dates:
            trend = np.sin(d.toordinal() / 100 + phi) * 2
            ret = trend * 0.005 + rng.normal(0.0005, 0.025)
            o = price * (1 + rng.normal(0, 0.005))
            c = o * (1 + ret)
            h = max(o, c) * 1.005
            l = min(o, c) * 0.995
            v = int(abs(rng.normal(2e6, 5e5)))
            rows.append({
                "code": code, "date": d, "open": o, "high": h,
                "low": l, "close": c, "volume": v,
            })
            price = c
    return pd.DataFrame(rows)


def compute_composite(df, factor_cols, weights):
    comp = pd.Series(0.0, index=df.index, dtype=float)
    for fc in factor_cols:
        values = df[fc]
        z = (values - values.mean()) / max(values.std(), 1e-10)
        comp += z.fillna(0) * weights.get(fc, 0)
    return comp


def generate_signals(df, composite, entry_z=0.7, exit_z=-0.3):
    signals = []
    in_position = False
    for idx in df.index:
        row = df.loc[idx]
        ts = row["date"]
        if isinstance(ts, pd.Timestamp):
            dt = ts.to_pydatetime()
        else:
            dt = datetime.datetime.fromisoformat(str(ts))
        score = composite.loc[idx]

        if not in_position and score > entry_z:
            signals.append(TradingSignal(
                action="BUY", symbol=row["code"],
                reason=f"entry_z={score:.2f}",
                confidence=min(abs(score) / 3.0, 1.0),
                shares=100, timestamp=dt,
            ))
            in_position = True
        elif in_position and score < exit_z:
            signals.append(TradingSignal(
                action="SELL", symbol=row["code"],
                reason=f"exit_z={score:.2f}",
                confidence=min(abs(score) / 3.0, 1.0),
                shares=100, timestamp=dt,
            ))
            in_position = False
    return signals, in_position


def compute_metrics(result):
    eq = np.array(result.equity_curve)
    rets = np.array(result.daily_returns)
    total_ret = (eq[-1] - result.initial_capital) / result.initial_capital if len(eq) > 1 else 0
    sharpe = 0.0
    if len(rets) > 1 and np.std(rets) > 0:
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252))
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = float(np.min(dd)) if len(dd) > 0 else 0
    profits = [t.pnl for t in result.trades if t.pnl > 0]
    losses = [t.pnl for t in result.trades if t.pnl < 0]
    win_rate = len(profits) / max(len(result.trades), 1)
    return {
        "total_return": total_ret, "sharpe_ratio": sharpe,
        "max_drawdown": mdd, "total_trades": result.total_trades,
        "win_rate": win_rate,
        "avg_profit": float(np.mean(profits)) if profits else 0,
        "avg_loss": float(np.mean(losses)) if losses else 0,
        "final_cash": result.final_cash,
        "equity_curve": eq,
        "daily_returns": rets,
    }


def main():
    print("=" * 60)
    print("Phase 3: Backtest Integration")
    print("=" * 60)

    codes = [f"{600000 + i}.SH" for i in range(5)]
    stock_names = {codes[0]: "PingAn", codes[1]: "ICBC", codes[2]: "PetroChina",
                   codes[3]: "CMB", codes[4]: "CNShenhua"}

    df = generate_multi_stock_data(n_stocks=5, n_days=504)
    print(f"\n[1/5] Data: {df.code.nunique()} stocks x {df.date.nunique()} days ({len(df)} rows)")

    print("[2/5] Computing factors (all stocks)...")
    composer = FactorComposer(orthogonalize=False)
    fdf = composer.compute_all_factors(df, mode="backtest")
    factor_cols = list(fdf.columns)
    merged = pd.concat([df, fdf], axis=1)
    print(f"  Factors: {len(factor_cols)}")

    print("[3/5] Computing IR-based weights (cross-sectional IC)...")
    analyzer = FactorAnalyzer()
    ic_res = analyzer.compute_ic_ir(
        merged, factor_cols=factor_cols,
        holding_periods=[5], date_col="date", code_col="code", price_col="close",
    )
    wsum = 0
    weights = {}
    for fc in factor_cols:
        ir = 0
        if fc in ic_res and 5 in ic_res[fc]:
            ir = abs(ic_res[fc][5].icir)
        weights[fc] = max(ir, 0.01)
        wsum += weights[fc]
    for fc in factor_cols:
        weights[fc] /= wsum

    top5 = sorted(weights.items(), key=lambda x: -x[1])[:5]
    print(f"  Top 5 weights: {[(k, f'{v:.4f}') for k, v in top5]}")

    # [4-5] Per-stock backtest
    print("[4/5] Generating per-stock signals + backtesting...")
    all_results = {}
    portfolio_daily_rets = []

    for code in codes:
        sdf = merged[merged["code"] == code].sort_values("date").copy()
        sdf_ohlcv = sdf[["code", "date", "open", "high", "low", "close", "volume"]].copy()

        composite = compute_composite(sdf, factor_cols, weights)
        signals, ends_in = generate_signals(sdf_ohlcv, composite, entry_z=0.7, exit_z=-0.3)

        engine = UnifiedBacktestEngine(initial_capital=1_000_000)
        result = engine.run(df=sdf_ohlcv, signals=signals, symbol=code, name=stock_names.get(code))

        metrics = compute_metrics(result)
        all_results[code] = metrics
        portfolio_daily_rets.append(metrics["daily_returns"])

        status = "✔" if metrics["total_trades"] > 0 else "✗"
        print(f"  {status} {code} ({stock_names.get(code)}): "
              f"ret={metrics['total_return']:+.2%} sharpe={metrics['sharpe_ratio']:.3f} "
              f"mdd={metrics['max_drawdown']:.2%} trades={metrics['total_trades']}")

    # Portfolio aggregate
    print("[5/5] Portfolio aggregation...")
    min_len = min(len(r) for r in portfolio_daily_rets if len(r) > 0)
    eq_rets = [r[:min_len] for r in portfolio_daily_rets if len(r) > 0]
    if eq_rets:
        avg_rets = np.mean(eq_rets, axis=0)
        port_sharpe = float(np.mean(avg_rets) / max(np.std(avg_rets), 1e-10) * np.sqrt(252))
        port_equity = 5_000_000 * np.cumprod(1 + avg_rets)
        port_peak = np.maximum.accumulate(port_equity)
        port_mdd = float(np.min((port_equity - port_peak) / port_peak))
        port_ret = float((port_equity[-1] - 5_000_000) / 5_000_000)
    else:
        port_sharpe = port_mdd = port_ret = 0

    print(f"\n  Portfolio (5 stocks, ¥5M):")
    print(f"    Total Return: {port_ret:+.2%}")
    print(f"    Sharpe:       {port_sharpe:.3f}")
    print(f"    Max DD:       {port_mdd:.2%}")

    total_trades = sum(r["total_trades"] for r in all_results.values())
    weighted_trades = sum(r["total_trades"] for r in all_results.values())

    # Write report
    report_path = Path("docs/reshaping_logs/11_backtest_integration.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 11 Backtest Integration Results\n\n")
        f.write(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## 配置\n\n")
        f.write(f"- 数据: {df.date.nunique()} 天, 5 只股票\n")
        f.write(f"- 初始资金: ¥1,000,000/只\n")
        f.write(f"- 入场阈值: z > 0.7, 出场阈值: z < -0.3\n")
        f.write(f"- 因子权重: cross-sectional IC/IR (全市场)\n\n")

        f.write("## 因子权重\n\n")
        f.write("| 因子 | 权重 |\n|------|------|\n")
        for fc in sorted(weights, key=lambda x: -weights[x]):
            f.write(f"| {fc} | {weights[fc]:.4f} |\n")

        f.write("\n## 个股回测\n\n")
        f.write("| 股票 | 总收益 | 夏普 | 最大回撤 | 交易数 | 胜率 |\n")
        f.write("|------|--------|------|----------|--------|------|\n")
        for code in codes:
            m = all_results.get(code, {})
            f.write(f"| {code} ({stock_names.get(code,'')}) | {m.get('total_return',0):+.2%} | "
                    f"{m.get('sharpe_ratio',0):.3f} | {m.get('max_drawdown',0):.2%} | "
                    f"{m.get('total_trades',0)} | {m.get('win_rate',0):.0%} |\n")

        f.write("\n## 等权投资组合\n\n")
        f.write("| 指标 | 值 |\n|------|-----|\n")
        f.write(f"| 总投资收益率 | {port_ret:+.2%} |\n")
        f.write(f"| 组合夏普比率 | {port_sharpe:.3f} |\n")
        f.write(f"| 组合最大回撤 | {port_mdd:.2%} |\n")
        f.write(f"| 总交易次数 | {total_trades} |\n")
        f.write(f"| 活跃股票数 | {sum(1 for m in all_results.values() if m.get('total_trades',0) > 0)}/5 |\n")

    print(f"\n  Report → {report_path}")
    print("\n✅ Phase 3 complete.")


if __name__ == "__main__":
    main()
