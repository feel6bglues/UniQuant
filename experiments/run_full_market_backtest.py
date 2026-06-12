"""
Stage 3+4: 成交量容量锁 + 全市场极限容量 1亿 回测
==================================================

Stage 3: VolumeLimitSizer 已挂载到 risk/sizer.py
Stage 4: 全市场 3500+ 只股票, 1亿初始资金, 月度 ILLIQ 因子选股

关键指标:
  - 年化收益率, 最大回撤, 夏普比率
  - ★ 平均资金闲置率 (Average Cash Drag) — 最核心的容量指标

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
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uniquant.risk.sizer import VolumeLimitSizer

QUALIFIED_FILE = Path("data/qualified_universe.csv")
LAKE_DIR = Path("data/lake/quotes/daily")
INITIAL_CAPITAL = 100_000_000  # 1亿
VOLUME_CAP_PCT = 0.05          # 5% 成交量限制
REBALANCE_MONTHS = 1           # 月度调仓
N_SELECT = 100                 # 选股数量 (ILLIQ Top 100)
COST_RATE = 0.0008             # 交易成本 (万8: 佣金+印花税+过户费)


def load_daily_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """加载单只股票日线数据。"""
    fp = LAKE_DIR / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
        if len(df) < 60:
            return None
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


def compute_illiq_series(df: pd.DataFrame) -> np.ndarray:
    """计算 ILLIQ 时间序列 (矢量化)。"""
    close = df["close"].values.astype(np.float64)
    amount = df["amount"].values.astype(np.float64)
    ret = np.diff(close, prepend=close[0])
    close_safe = np.maximum(close, 1e-10)
    ret_pct = np.abs(ret / close_safe)
    daily = np.where(amount > 0, ret_pct / amount, np.nan)
    return pd.Series(daily).rolling(20, min_periods=10).mean().values * 1e9


class PortfolioBacktest:
    """
    全市场组合回测引擎。

    月度调仓, ILLIQ 因子选股, 5% 成交量容量锁。
    """

    def __init__(self, initial_capital: float, volume_cap_pct: float = 0.05,
                 n_select: int = 100, cost_rate: float = 0.0008):
        self.initial_capital = initial_capital
        self.sizer = VolumeLimitSizer(volume_cap_pct)
        self.n_select = n_select
        self.cost_rate = cost_rate

    def run(self, symbols: list[str], start_date: str, end_date: str) -> dict:
        t0 = time.time()
        print(f"\n  加载 {len(symbols)} 只股票数据...")

        # ---- Step 1: 加载全量数据 ----
        stock_data = {}
        load_count = 0
        for sym in symbols:
            df = load_daily_data(sym, "2017-01-01", end_date)  # 多加载1年用于因子预热
            if df is not None:
                illiq = compute_illiq_series(df)
                df["illiq"] = illiq
                stock_data[sym] = df
                load_count += 1
            if load_count % 500 == 0:
                print(f"    加载 {load_count}/{len(symbols)}...", end="\r")

        print(f"\n  有效股票: {load_count}, 耗时 {time.time()-t0:.0f}s")

        # ---- Step 2: 构建月度调仓日历 ----
        all_dates = sorted(set(
            d for sdf in stock_data.values()
            for d in pd.to_datetime(sdf["date"]).values
        ))
        all_dates = [d for d in all_dates if start_date <= str(d)[:10] <= end_date]
        dates_arr = np.array([str(d)[:10] for d in all_dates])
        print(f"  交易日: {len(dates_arr)} ({dates_arr[0]} ~ {dates_arr[-1]})")

        # 月度末调仓日
        rebalance_dates = []
        ym_set = set()
        for d in reversed(dates_arr):
            ym = str(d)[:7]
            if ym not in ym_set:
                ym_set.add(ym)
                rebalance_dates.append(d)
        rebalance_dates = sorted(rebalance_dates[1:])  # 跳过第一个月(预热)
        print(f"  调仓日: {len(rebalance_dates)} 个月")

        # ---- Step 3: 组合回测主循环 ----
        cash = self.initial_capital
        positions: dict[str, dict] = {}  # symbol -> {shares, buy_price, buy_date}
        equity_curve = []
        cash_drag_log = []
        trade_log = []

        date_to_idx: dict[str, int] = {}
        for sdf in stock_data.values():
            for i, d in enumerate(sdf["date"]):
                ds = str(d)[:10]
                if ds not in date_to_idx:
                    date_to_idx[ds] = i

        rebalance_set = set(rebalance_dates)

        for di, d_str in enumerate(dates_arr):
            ds = str(d_str)
            today_equity = cash

            # 更新持仓市值 (用当日收盘价)
            for sym, pos in list(positions.items()):
                if sym not in stock_data:
                    continue
                sdf = stock_data[sym]
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                close_p = row["close"].values[0]
                pos_value = pos["shares"] * close_p
                today_equity += pos_value

            equity_curve.append({"date": ds, "equity": today_equity, "cash": cash})

            # 检查是否是调仓日
            if ds in rebalance_set:
                self._rebalance(ds, stock_data, positions,
                                cash, today_equity, cash_drag_log, trade_log)

        # ---- Step 4: 清算 ----
        for sym, pos in positions.items():
            if sym not in stock_data:
                continue
            last_row = stock_data[sym].iloc[-1]
            last_close = last_row["close"]
            cash += pos["shares"] * last_close * (1 - self.cost_rate)
        positions.clear()
        final_equity = cash

        # ---- Step 5: 计算绩效指标 ----
        results = self._compute_metrics(equity_curve, cash_drag_log, trade_log, final_equity)
        results["equity_curve"] = equity_curve
        results["cash_drag_log"] = cash_drag_log
        results["trade_log"] = trade_log
        results["run_time"] = time.time() - t0
        return results

    def _rebalance(self, ds, stock_data, positions, cash, today_equity,
                   cash_drag_log, trade_log):
        """月度调仓。"""
        # 获取当月 ILLIQ 排名
        candidates = []
        for sym, sdf in stock_data.items():
            row = sdf[sdf["date"] == ds]
            if row.empty:
                continue
            illiq_v = row["illiq"].values[0]
            if np.isnan(illiq_v) or illiq_v <= 0:
                continue
            candidates.append((sym, illiq_v, row["close"].values[0],
                              row["volume"].values[0], row["open"].values[0]))

        if len(candidates) < self.n_select:
            return

        # 按 ILLIQ 降序排列 (低流动性溢价)
        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:self.n_select]

        # 等权重分配可投资金 (已有持仓部分不算)
        # 先卖出不在新的选中列表中的持仓
        selected_syms = {s[0] for s in selected}
        for sym in list(positions.keys()):
            if sym not in selected_syms:
                sdf = stock_data.get(sym)
                if sdf is None:
                    continue
                    row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                close_p = row["close"].values[0]
                vol = row["volume"].values[0]
                pos = positions.pop(sym)
                max_sell = int(vol * VOLUME_CAP_PCT)
                actual_sell = min(pos["shares"], max_sell // 100 * 100)
                if actual_sell > 0:
                    proceeds = actual_sell * close_p * (1 - self.cost_rate)
                    cash += proceeds
                    trade_log.append({
                        "date": ds, "symbol": sym, "action": "SELL",
                        "shares": actual_sell, "price": close_p,
                        "notional": actual_sell * close_p,
                        "reason": "drop_from_selection",
                    })

        # 计算每个股票的目标配置
        target_per_stock = today_equity / self.n_select * 0.98  # 留 2% 缓冲

        # 为每个选中股票生成买单
        total_cash_drag = 0
        for sym, illiq_v, close_p, vol, open_p in selected:
            # 用开盘价执行 (T+1 以开盘价成交)
            exec_price = open_p if open_p > 0 else close_p

            target_shares = int(target_per_stock / exec_price)
            target_shares = max(target_shares // 100 * 100, 0)

            if target_shares <= 0:
                continue

            # 应用 5% 成交量容量锁
            result = self.sizer.cap_shares(target_shares, vol, exec_price)
            actual_shares = result["actual_shares"]
            cost_notional = actual_shares * exec_price

            if cash < cost_notional:
                continue  # 现金不足, 跳过

            if actual_shares > 0:
                cash -= cost_notional * (1 + self.cost_rate)
                positions[sym] = {
                    "shares": actual_shares,
                    "buy_price": exec_price,
                    "buy_date": ds,
                }
                trade_log.append({
                    "date": ds, "symbol": sym, "action": "BUY",
                    "shares": actual_shares, "price": exec_price,
                    "notional": cost_notional,
                    "illiq": illiq_v,
                    "fill_rate": result["fill_rate"],
                    "capped": result["capped"],
                })

            if result["capped"]:
                total_cash_drag += result["cash_drag"]

        # 记录 cash drag
        cash_drag_rate = total_cash_drag / max(today_equity, 1)
        cash_drag_log.append({
            "date": ds, "n_selected": len(selected),
            "total_cash_drag": total_cash_drag,
            "cash_drag_rate": cash_drag_rate,
            "equity": today_equity,
            "cash": cash,
        })

        # 已经买入的, 更新现金余额后清理多余现金
        # (现金已经在上面的 buy 循环中扣除了)

    def _compute_metrics(self, equity_curve, cash_drag_log, trade_log, final_equity):
        """计算绩效指标。"""
        if not equity_curve:
            return {"error": "no trades"}

        eq_df = pd.DataFrame(equity_curve)
        eq_df["daily_ret"] = eq_df["equity"].pct_change()
        eq_df = eq_df.dropna()

        total_days = len(eq_df)
        total_years = total_days / 252

        if total_years < 0.5 or eq_df["daily_ret"].std() == 0:
            return {"error": "insufficient data"}

        total_return = final_equity / self.initial_capital - 1
        annual_ret = (1 + total_return) ** (1 / max(total_years, 0.1)) - 1
        annual_vol = eq_df["daily_ret"].std() * np.sqrt(252)
        sharpe = annual_ret / max(annual_vol, 1e-10)

        # 最大回撤
        cumulative = (1 + eq_df["daily_ret"]).cumprod()
        running_max = cumulative.cummax()
        drawdown = cumulative / running_max - 1
        max_dd = drawdown.min()

        # 平均现金闲置率
        cd_df = pd.DataFrame(cash_drag_log)
        avg_cash_drag = cd_df["cash_drag_rate"].mean() if not cd_df.empty else 0.0

        # Calmar 比率
        calmar = annual_ret / max(abs(max_dd), 1e-10)

        # 胜率
        trades = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
        win_rate = 0.0
        if not trades.empty:
            buys = trades[trades["action"] == "BUY"]
            # 简易胜率: 找到被卖出的股票, 比较卖出价和买入价
            sells = trades[trades["action"] == "SELL"]
            if not sells.empty:
                merged = sells.merge(
                    buys[["symbol", "price"]].rename(columns={"price": "buy_price"}),
                    on="symbol", how="left"
                )
                if not merged.empty:
                    merged["pnl"] = merged["price"] / merged["buy_price"] - 1
                    win_rate = (merged["pnl"] > 0).mean()

        # 交易频率
        avg_monthly_trades = len(buys) / max(total_years * 12, 1) if not buys.empty else 0

        return {
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "total_return": total_return,
            "annual_return": annual_ret,
            "annual_volatility": annual_vol,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "calmar_ratio": calmar,
            "avg_cash_drag": avg_cash_drag,
            "total_years": total_years,
            "total_trading_days": total_days,
            "n_trades_buy": len(buys) if not trades.empty else 0,
            "win_rate": win_rate,
            "avg_monthly_trades": avg_monthly_trades,
        }


def print_tearsheet(results: dict):
    """打印 Tearsheet。"""
    if "error" in results:
        print(f"\n  ❌ {results['error']}")
        return

    print("\n" + "=" * 60)
    print("  📊 全市场极限容量 TEARSHEET")
    print("=" * 60)

    print(f"\n  ┌─ 基本参数 ─────────────────────────────┐")
    print(f"  │  初始资金:        {results['initial_capital']:>15,.0f} CNY")
    print(f"  │  最终净值:        {results['final_equity']:>15,.0f} CNY")
    print(f"  │  回测区间:        {results['total_years']:>13.1f} 年 ({results['total_trading_days']}天)")
    print(f"  │  成交量限制:      {VOLUME_CAP_PCT*100:>13.0f}%")
    print(f"  │  选股数量:        Top {N_SELECT:>8}")
    print(f"  └──────────────────────────────────────────┘")

    print(f"\n  ┌─ 收益指标 ─────────────────────────────┐")
    print(f"  │  累计收益率:      {results['total_return']:>+14.2%}")
    print(f"  │  年化收益率:      {results['annual_return']:>+14.2%}")
    print(f"  │  年化波动率:      {results['annual_volatility']:>14.2%}")
    print(f"  └──────────────────────────────────────────┘")

    print(f"\n  ┌─ 风险指标 ─────────────────────────────┐")
    print(f"  │  夏普比率:        {results['sharpe_ratio']:>+14.4f}")
    print(f"  │  最大回撤:        {results['max_drawdown']:>14.2%}")
    print(f"  │  Calmar比率:      {results['calmar_ratio']:>+14.4f}")
    print(f"  └──────────────────────────────────────────┘")

    print(f"\n  ⚠️  ★★★ 核心容量指标 ★★★")
    print(f"  ┌─ 资金容量分析 ─────────────────────────┐")
    print(f"  │  平均资金闲置率:  {results['avg_cash_drag']:>14.2%}")
    print(f"  │  资金利用率:      {1-results['avg_cash_drag']:>14.2%}")
    print(f"  └──────────────────────────────────────────┘")

    print(f"\n  ┌─ 交易统计 ─────────────────────────────┐")
    print(f"  │  总买入次数:      {results['n_trades_buy']:>14}")
    print(f"  │  月均交易次数:    {results['avg_monthly_trades']:>14.1f}")
    print(f"  │  简易胜率:        {results['win_rate']:>14.1%}")
    print(f"  └──────────────────────────────────────────┘")

    print(f"\n  {'='*60}\n")


def main():
    print("=" * 70)
    print("  Stage 3+4: 成交量容量锁 + 全市场 1亿 极限回测")
    print(f"  初始资金: {INITIAL_CAPITAL/1e8:.1f}亿  |  成交量限制: {VOLUME_CAP_PCT*100:.0f}%")
    print("=" * 70)

    # ---- 加载合格股票池 ----
    print("\n[1/3] 加载合格股票池...")
    if not QUALIFIED_FILE.exists():
        print(f"  ❌ 未找到 {QUALIFIED_FILE}, 请先运行 Stage 1")
        return
    qualified = pd.read_csv(QUALIFIED_FILE)
    symbols = qualified["symbol"].tolist()
    print(f"  合格股票: {len(symbols)}")

    # ---- 运行回测 ----
    print("\n[2/3] 运行全市场组合回测...")
    backtest = PortfolioBacktest(
        initial_capital=INITIAL_CAPITAL,
        volume_cap_pct=VOLUME_CAP_PCT,
        n_select=N_SELECT,
        cost_rate=COST_RATE,
    )
    results = backtest.run(symbols, start_date="2018-01-01", end_date="2026-06-09")

    # ---- 输出 Tearsheet ----
    print("\n[3/3] 生成 Tearsheet...")
    print_tearsheet(results)

    # ---- 保存报告 ----
    report_path = Path("docs/reshaping_logs/06_full_market_tearsheet.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 06 — 全市场极限容量 TEARSHEET\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **策略**: ILLIQ 月度选股 Top {N_SELECT}, 等权重, 成交量限制 {VOLUME_CAP_PCT*100:.0f}%\n")
        f.write(f"> **初始资金**: {INITIAL_CAPITAL:,.0f} CNY\n")
        f.write(f"> **交易成本**: {COST_RATE:.4f}\n\n")

        if "error" in results:
            f.write(f"**错误**: {results['error']}\n")
        else:
            f.write("## 绩效总结\n\n")
            f.write("| 指标 | 值 |\n")
            f.write("|------|-----|\n")
            for k, v in [
                ("初始资金", f"{results['initial_capital']:,.0f}"),
                ("最终净值", f"{results['final_equity']:,.0f}"),
                ("累计收益率", f"{results['total_return']:+.2%}"),
                ("年化收益率", f"{results['annual_return']:+.2%}"),
                ("年化波动率", f"{results['annual_volatility']:.2%}"),
                ("夏普比率", f"{results['sharpe_ratio']:+.4f}"),
                ("最大回撤", f"{results['max_drawdown']:.2%}"),
                ("Calmar比率", f"{results['calmar_ratio']:+.4f}"),
                ("平均资金闲置率", f"{results['avg_cash_drag']:.2%}"),
                ("总交易日", str(results['total_trading_days'])),
                ("总买入次数", str(results['n_trades_buy'])),
                ("简易胜率", f"{results['win_rate']:.1%}"),
            ]:
                f.write(f"| {k} | {v} |\n")

            f.write("\n## 容量分析\n\n")
            f.write(f"- **成交量限制**: {VOLUME_CAP_PCT*100:.0f}%\n")
            f.write(f"- **平均资金闲置率**: {results['avg_cash_drag']:.2%}\n")
            f.write(f"- 资金闲置率 = ∑ (目标配置 - 实际成交) / 总权益\n")
            f.write(f"- 闲置率越高 → 策略资金容量越小, 大资金摩擦越大\n")
            f.write(f"- 闲置率 > 30% → 该规模超出策略舒适容量\n\n")

            f.write("## 判定\n\n")
            ad = results['avg_cash_drag']
            sr = results['sharpe_ratio']
            dd = results['max_drawdown']

            if ad < 0.10 and sr > 0.5:
                f.write(f"✅ 通过: 资金容量充裕 (闲置率{ad:.1%}), 夏普{sr:.2f}\n")
            elif ad < 0.30 and sr > 0.3:
                f.write(f"⚠️ 边缘: 资金容量适中 (闲置率{ad:.1%}), 夏普{sr:.2f}\n")
            else:
                f.write(f"❌ 不通过: 资金容量不足 (闲置率{ad:.1%}) 或 Sharpe过低 ({sr:.2f})\n")

            f.write("\n---\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print("  Stage 3+4 完成!")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — 请确认 Tearsheet")


if __name__ == "__main__":
    main()
