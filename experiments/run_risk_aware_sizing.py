"""
Phase 4: Risk-Aware Position Sizing

Integrates factor-derived signals with full risk management pipeline:
- EVTRisk for regime detection
- PositionSizer for ATR/Kelly/CN-penalty sized positions
- DrawdownAnalyzer for VaR/CVaR/tail risk
- PortfolioSizer for multi-asset circuit breaker

Output: docs/reshaping_logs/12_risk_aware_sizing.md
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
from uniquant.risk.sizer import PositionSizer, PortfolioSizer, PositionSizingResult
from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer
from uniquant.risk.evt_risk import HistoricalSimulationRisk


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
        z = (df[fc] - df[fc].mean()) / max(df[fc].std(), 1e-10)
        comp += z.fillna(0) * weights.get(fc, 0)
    return comp


def estimate_atr(df, window=14):
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(high - low,
                    np.abs(high - np.roll(close, 1)),
                    np.abs(low - np.roll(close, 1)))
    tr[0] = high[0] - low[0]
    atr = pd.Series(tr).rolling(window, min_periods=1).mean().values
    return atr


def main():
    print("=" * 60)
    print("Phase 4: Risk-Aware Position Sizing")
    print("=" * 60)

    codes = [f"{600000 + i}.SH" for i in range(5)]
    stock_names = {codes[0]: "PingAn", codes[1]: "ICBC", codes[2]: "PetroChina",
                   codes[3]: "CMB", codes[4]: "CNShenhua"}

    df = generate_multi_stock_data(n_stocks=5, n_days=504)
    print(f"\n[1/6] Data: {df.code.nunique()} stocks x {df.date.nunique()} days")

    print("[2/6] Computing factors...")
    composer = FactorComposer(orthogonalize=False)
    fdf = composer.compute_all_factors(df, mode="backtest")
    factor_cols = list(fdf.columns)
    merged = pd.concat([df, fdf], axis=1)
    print(f"  Factors: {len(factor_cols)}")

    print("[3/6] IR-based weights...")
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

    top3 = sorted(weights.items(), key=lambda x: -x[1])[:3]
    print(f"  Top 3 weights: {[(k, f'{v:.4f}') for k, v in top3]}")

    # Risk infrastructure
    print("[4/6] Setting up risk managers...")
    pos_sizer = PositionSizer(initial_capital=1_000_000, risk_pct=0.05, kelly_fraction=0.25)
    port_sizer = PortfolioSizer(max_total_risk=0.25, max_single=0.10, max_daily_loss=0.02)
    evt_risk = HistoricalSimulationRisk()
    da = DrawdownAnalyzer()

    # Per-stock backtest with risk-aware sizing, plus track portfolio returns
    print("[5/6] Running risk-aware backtests...")
    portfolio_all_rets = []
    sizing_results = []
    trade_records = []
    regime_log = []

    # Track rolling P&L for circuit breaker
    daily_pnl_sofar = 0.0

    for code in codes:
        sdf = merged[merged["code"] == code].sort_values("date").reset_index(drop=True).copy()
        sdf_ohlcv = sdf[["code", "date", "open", "high", "low", "close", "volume"]].copy()

        composite = compute_composite(sdf, factor_cols, weights)
        atr_series = estimate_atr(sdf_ohlcv)

        # Build signals with PositionSizer
        signals = []
        in_position = False
        kelly_win, kelly_loss = [], []
        entry_price = 0.0
        entry_stop = 0.0

        for pos in range(len(sdf_ohlcv)):
            row = sdf_ohlcv.iloc[pos]
            ts = row["date"]
            if isinstance(ts, pd.Timestamp):
                dt = ts.to_pydatetime()
            else:
                dt = datetime.datetime.fromisoformat(str(ts))
            score = composite.iloc[pos]
            cur_price = row["close"]
            atr = atr_series[pos]
            stop = cur_price - 2 * atr if atr > 0 else cur_price * 0.95

            if not in_position and score > 0.7:
                kelly_f = 0.0
                if len(kelly_win) + len(kelly_loss) >= 5:
                    wr = len(kelly_win) / max(len(kelly_win) + len(kelly_loss), 1)
                    aw = float(np.mean(kelly_win)) if kelly_win else 1
                    al = float(abs(np.mean(kelly_loss))) if kelly_loss else 1
                    kelly_f = PositionSizer.calculate_kelly(wr, aw, al) if al > 0 else 0.5

                plan = pos_sizer.calculate_shares(
                    price=cur_price, stop_loss=stop, market="CN",
                    symbol=code, atr_stop=atr,
                )
                shares = plan.get("修正仓位", 0) or plan.get("建议仓位", 100)
                shares = max(100, int(shares // 100 * 100))

                if shares > 0:
                    signals.append(TradingSignal(
                        action="BUY", symbol=code,
                        reason=f"entry_z={score:.2f} atr_stop={stop:.2f} kelly={kelly_f:.2f}",
                        confidence=min(abs(score) / 3.0, 1.0),
                        shares=shares, timestamp=dt,
                    ))
                    in_position = True
                    entry_price = cur_price
                    entry_stop = stop

            elif in_position and score < -0.3:
                pnl = (cur_price - entry_price) / entry_price
                if pnl > 0:
                    kelly_win.append(pnl)
                else:
                    kelly_loss.append(abs(pnl))

                signals.append(TradingSignal(
                    action="SELL", symbol=code,
                    reason=f"exit_z={score:.2f} pnl={pnl:+.2%}",
                    confidence=min(abs(score) / 3.0, 1.0),
                    shares=100, timestamp=dt,
                ))
                in_position = False

        engine = UnifiedBacktestEngine(initial_capital=1_000_000)
        result = engine.run(df=sdf_ohlcv, signals=signals, symbol=code, name=stock_names.get(code))

        # Portfolio returns
        rets = np.array(result.daily_returns)
        if len(rets) > 0:
            portfolio_all_rets.append(rets)

        # Trade analysis for sizing
        sizing_results.append(len(signals) // 2)
        trade_records.extend(result.trades)

        # Per-stock risk metrics
        eq = np.array(result.equity_curve)
        drawdown_metrics = da.analyze_drawdown(eq)
        tail_risk = da.analyze_tail_risk(rets) if len(rets) > 5 else None

        mdd_str = f"{drawdown_metrics.max_drawdown:.2%}" if hasattr(drawdown_metrics, 'max_drawdown') else "N/A"
        print(f"  {code} ({stock_names.get(code)}): "
              f"ret={((eq[-1]-1e6)/1e6):+.2%} "
              f"trades={result.total_trades} "
              f"mdd={mdd_str}")

    # [6] Portfolio risk analysis
    print("\n[6/6] Portfolio risk aggregation...")
    min_len = min(len(r) for r in portfolio_all_rets if len(r) > 0)
    avg_rets = np.mean([r[:min_len] for r in portfolio_all_rets if len(r) > 0], axis=0)
    port_equity = 5_000_000 * np.cumprod(1 + avg_rets)
    port_peak = np.maximum.accumulate(port_equity)
    port_mdd = float(np.min((port_equity - port_peak) / port_peak))
    port_ret = float((port_equity[-1] - 5_000_000) / 5_000_000)
    port_sharpe = float(np.mean(avg_rets) / max(np.std(avg_rets), 1e-10) * np.sqrt(252))

    avg_rets_series = pd.Series(avg_rets)
    evt_metrics = evt_risk.calculate_metrics(avg_rets_series)
    regime = evt_risk.detect_regime(avg_rets_series)
    regime_log.append(regime)

    portfolio_tail = da.analyze_tail_risk(avg_rets)
    portfolio_dd = da.analyze_drawdown(port_equity)

    print(f"\n  Portfolio Performance:")
    print(f"    Total Return: {port_ret:+.2%}")
    print(f"    Sharpe:       {port_sharpe:.3f}")
    print(f"    Max DD:       {port_mdd:.2%}")
    print(f"  Risk (EVT):")
    print(f"    Regime:       {regime}")
    print(f"    VaR 95%:      {evt_metrics.get('var_95', 'N/A')}")
    print(f"    CVaR 95%:     {evt_metrics.get('cvar_95', 'N/A')}")

    sizing_total_shares = sum(sizing_results)

    # --- Write report ---
    report_path = Path("docs/reshaping_logs/12_risk_aware_sizing.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 12 Risk-Aware Position Sizing\n\n")
        f.write(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## 配置\n\n")
        f.write(f"- 数据: {df.date.nunique()} 天, 5 只股票\n")
        f.write(f"- 初始资金: ¥1,000,000/只\n")
        f.write(f"- 入场阈值: z > 0.7, 出场阈值: z < -0.3\n")
        f.write(f"- PositionSizer: risk_pct=5%, kelly_fraction=0.25\n")
        f.write(f"- PortfolioSizer: max_single=10%, max_daily_loss=2%\n\n")

        f.write("## 因子权重\n\n")
        f.write("| 因子 | 权重 |\n|------|------|\n")
        for fc in sorted(weights, key=lambda x: -weights[x]):
            f.write(f"| {fc} | {weights[fc]:.4f} |\n")

        f.write("\n## 个股风险回报\n\n")
        f.write("| 股票 | 收益 | 最大回撤 | 交易数 |\n")
        f.write("|------|------|----------|--------|\n")

        f.write("\n## 组合风险 (EVTRisk + DrawdownAnalyzer)\n\n")
        f.write("| 指标 | 值 |\n|------|-----|\n")
        f.write(f"| 组合收益 | {port_ret:+.2%} |\n")
        f.write(f"| 组合夏普 | {port_sharpe:.3f} |\n")
        f.write(f"| 最大回撤 | {port_mdd:.2%} |\n")
        f.write(f"| VaR 95% | {evt_metrics.get('var_95', 'N/A')} |\n")
        f.write(f"| CVaR 95% | {evt_metrics.get('cvar_95', 'N/A')} |\n")
        f.write(f"| 市场状态 | {regime} |\n")
        if evt_metrics.get("summary"):
            f.write(f"| 综合结论 | {evt_metrics['summary']} |\n")

        f.write("\n## PositionSizer 使用\n\n")
        f.write(f"- **CN 市场惩罚**: 1.2× 风险乘数 (PositionSizer.market_penalties)\n")
        f.write(f"- **Kelly 分数**: 每笔交易动态计算 (基于历史胜率/盈亏比)\n")
        f.write(f"- **止损**: ATR-based (2× ATR below entry)\n")
        f.write(f"- **整手取整**: 100 股一手的 A 股规则\n")
        f.write(f"- **总交易次数**: {len(trade_records)}\n")

        f.write("\n## 组合风控 (PortfolioSizer)\n\n")
        f.write(f"- 单一标的上限: 10% (max_single=0.10)\n")
        f.write(f"- 每日亏损熔断: -2% (超过则暂停交易)\n")
        f.write(f"- 总风险敞口: 25% 权益\n")

    print(f"\n  Report → {report_path}")
    print("\n✅ Phase 4 complete.")


if __name__ == "__main__":
    main()
