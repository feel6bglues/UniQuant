"""
Phase 1+2+3: 机构级全市场回测引擎
==================================

单脚本架构, 分段激活。

Phase 1 (激活):  Composite Alpha 多因子融合 + 波动率倒数风险平价
Phase 2 (待激活): LPPL 大盘熔断 + Wyckoff 个股过滤
Phase 3 (待激活): 全量 1 亿终极回测

[Halt & Wait — Phase 1]
  需确认: 因子权重, 波动率窗口, 等权 vs 逆波动率

Usage:
  python3 experiments/run_composite_alpha_backtest.py
"""

import os, sys, warnings, time
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uniquant.risk.sizer import VolumeLimitSizer, InverseVolatilitySizer

# ──────────────────────────────────────────────────────────────────────
# 配置 — 修改此处参数以实验
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # 资金与容量
    initial_capital: float = 100_000_000       # 1 亿
    volume_cap_pct: float = 0.05               # 5% 日成交量拦截
    cost_rate: float = 0.0008                  # 万 8 (佣金+印花税+过户费)
    lot_size: int = 100                        # A 股整手

    # 选股
    n_select: int = 100                        # 选股数量
    rebalance_days: int = 21                   # 约月度调仓

    # ── Phase 1: 因子权重 ──
    # Composite = w1*Z(ILLIQ) + w2*Z(CS_Mom) - w3*Z(PV_Div)
    # PV_Div 预期 IC 为负, 因此减去等于反向做多
    factor_weights: dict = field(default_factory=lambda: {
        "illiq": 0.50,
        "cs_momentum": 0.25,
        "pv_divergence": -0.25,   # 负号: PV_Div 预期 IC 为负, 做多低 PV_Div
    })

    # ── Phase 1: 波动率风险平价 ──
    use_inverse_vol: bool = True               # True=逆波动率, False=等权重
    vol_period: int = 20                       # 波动率计算窗口

    # ── Phase 2: 非线性风控 (暂存根) ──
    enable_lppl_macro_veto: bool = False       # 待激活
    enable_wyckoff_micro_filter: bool = False  # 待激活
    lppl_crash_threshold: float = 0.6          # LPPL 崩盘概率阈值
    lppl_sustain_days: int = 3                 # 持续天数要求

    # 路径
    qualified_file: str = "data/qualified_universe.csv"
    lake_dir: str = "data/lake/quotes/daily"
    start_date: str = "2018-01-01"
    end_date: str = "2026-06-09"

config = Config()

# ──────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────
LAKE_DIR = Path(config.lake_dir)
QUALIFIED_FILE = Path(config.qualified_file)


def load_daily_data(symbol: str, config: Config) -> pd.DataFrame | None:
    fp = LAKE_DIR / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(
            fp,
            columns=["date", "open", "high", "low", "close", "volume", "amount"],
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= "2017-01-01") & (df["date"] <= config.end_date)]
        if len(df) < 120:
            return None
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


def load_universe(config: Config) -> list[str]:
    if not QUALIFIED_FILE.exists():
        print(f"  ❌ 未找到 {QUALIFIED_FILE}")
        return []
    qualified = pd.read_csv(QUALIFIED_FILE)
    return qualified["symbol"].tolist()


# ──────────────────────────────────────────────────────────────────────
# 因子计算 (矢量化)
# ──────────────────────────────────────────────────────────────────────
def compute_illiq(close: np.ndarray, amount: np.ndarray) -> np.ndarray:
    ret = np.abs(np.diff(close, prepend=close[0]) / np.maximum(close, 1e-10))
    daily = np.where(amount > 0, ret / amount, np.nan)
    return pd.Series(daily).rolling(20, min_periods=10).mean().values * 1e9


def compute_cs_momentum(close: np.ndarray) -> np.ndarray:
    n = len(close)
    r20 = np.full(n, np.nan)
    r5 = np.full(n, np.nan)
    r20[20:] = close[20:] / np.maximum(close[:-20], 1e-10) - 1
    r5[5:] = close[5:] / np.maximum(close[:-5], 1e-10) - 1
    r5 = np.where(r5 <= -1.0, np.nan, r5)
    mom = np.full(n, np.nan)
    mom[20:] = (1 + r20[20:]) / (1 + r5[20:]) - 1
    return mom


def compute_pv_divergence(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    close_pct = pd.Series(close).rolling(20, min_periods=5).rank(pct=True).values
    vol_pct = pd.Series(volume).rolling(20, min_periods=5).rank(pct=True).values
    return vol_pct - close_pct


# ──────────────────────────────────────────────────────────────────────
# 核心: 横截面 Z-Score 标准化 + 复合打分
# ──────────────────────────────────────────────────────────────────────
def compute_composite_alpha(
    stock_data: dict,
    date_str: str,
    factors: list[str],
    weights: list[float],
) -> dict[str, float]:
    """
    横截面 z-score 标准化 + 加权复合打分。

    Args:
        stock_data: {symbol -> DataFrame}
        date_str: 调仓日期 YYYY-MM-DD
        factors: 因子列名列表, e.g. ["illiq", "cs_momentum", "pv_divergence"]
        weights: 对应权重, e.g. [0.5, 0.25, -0.25]

    Returns:
        {symbol -> composite_score (z-score weighted sum)}
    """
    raw: dict[str, dict[str, float]] = {}
    for sym, df in stock_data.items():
        row = df[df["date"] == date_str]
        if row.empty:
            continue
        r = row.iloc[0]
        vals = {}
        for f in factors:
            v = r.get(f, np.nan)
            vals[f] = v if (not np.isnan(v) and np.isfinite(v)) else 0.0
        raw[sym] = vals

    if not raw:
        return {}

    scores: dict[str, float] = {sym: 0.0 for sym in raw}
    for fi, f in enumerate(factors):
        arr = np.array([raw[s][f] for s in raw])
        mu = np.nanmean(arr)
        sigma = np.nanstd(arr)
        if sigma < 1e-12:
            sigma = 1.0
        for sym in raw:
            scores[sym] += weights[fi] * (raw[sym][f] - mu) / sigma

    return scores


# ──────────────────────────────────────────────────────────────────────
# 组合回测引擎
# ──────────────────────────────────────────────────────────────────────
class InstitutionalBacktest:
    def __init__(self, config: Config):
        self.config = config
        self.vol_sizer = InverseVolatilitySizer(
            vol_period=config.vol_period, lot_size=config.lot_size
        )
        self.volume_capper = VolumeLimitSizer(config.volume_cap_pct)

    def run(self, symbols: list[str]) -> dict:
        t0 = time.time()
        cfg = self.config

        # ── 1. 加载数据 ──
        print(f"\n  [数据] 加载 {len(symbols)} 只股票 (1-yr warmup period)...")
        stock_data: dict = {}
        load_count = 0
        for sym in symbols:
            df = load_daily_data(sym, cfg)
            if df is not None:
                close = df["close"].values.astype(np.float64)
                amount = df["amount"].values.astype(np.float64)
                volume = df["volume"].values.astype(np.float64)

                df["illiq"] = compute_illiq(close, amount)
                df["cs_momentum"] = compute_cs_momentum(close)
                df["pv_divergence"] = compute_pv_divergence(close, volume)

                stock_data[sym] = df
                load_count += 1
            if load_count % 500 == 0:
                print(f"    {load_count}/{len(symbols)}...", end="\r")
        print(f"  ✓ {load_count} 只有效 ({(time.time()-t0):.0f}s)")

        # ── 2. 构建交易日历 ──
        all_dates = sorted({
            str(d)[:10] for sdf in stock_data.values()
            for d in sdf["date"]
        })
        all_dates = [d for d in all_dates if cfg.start_date <= d <= cfg.end_date]

        rebalance_dates = []
        ym_seen = set()
        for d in reversed(all_dates):
            ym = d[:7]
            if ym not in ym_seen:
                ym_seen.add(ym)
                rebalance_dates.append(d)
        rebalance_dates = sorted(rebalance_dates[1:])  # 跳过第一个月预热
        rebalance_set = set(rebalance_dates)

        print(f"  [日历] {len(all_dates)} 天, {len(rebalance_dates)} 个调仓日")

        # ── 3. 回测主循环 ──
        cash = cfg.initial_capital
        positions: dict[str, dict] = {}
        equity_curve: list[dict] = []
        cash_drag_log: list[dict] = []
        trade_log: list[dict] = []

        for di, ds in enumerate(all_dates):
            today_equity = cash

            # 更新持仓市值
            for sym in list(positions.keys()):
                sdf = stock_data.get(sym)
                if sdf is None:
                    continue
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                close_p = row["close"].values[0]
                today_equity += positions[sym]["shares"] * close_p

            equity_curve.append({"date": ds, "equity": today_equity, "cash": cash})

            if ds in rebalance_set:
                self._rebalance(
                    ds, stock_data, positions, cash, today_equity,
                    cash_drag_log, trade_log,
                )

        # ── 4. 清算 ──
        for sym in list(positions.keys()):
            sdf = stock_data.get(sym)
            if sdf is None:
                continue
            last = sdf.iloc[-1]
            cash += positions[sym]["shares"] * last["close"] * (1 - cfg.cost_rate)
        positions.clear()
        final_equity = cash

        # ── 5. 绩效计算 ──
        results = self._compute_metrics(equity_curve, cash_drag_log, trade_log, final_equity)
        results["stock_data"] = stock_data
        results["run_time"] = time.time() - t0
        return results

    def _rebalance(self, ds, stock_data, positions, cash, today_equity,
                   cash_drag_log, trade_log):
        cfg = self.config
        factors = list(cfg.factor_weights.keys())
        weights = list(cfg.factor_weights.values())

        # ── 1. 横截面复合打分 ──
        score_dict = compute_composite_alpha(stock_data, ds, factors, weights)

        # ── 2. 获取候选池 ──
        candidates = []
        for sym, sc in score_dict.items():
            if not np.isfinite(sc):
                continue
            sdf = stock_data[sym]
            row = sdf[sdf["date"] == ds]
            if row.empty:
                continue
            r = row.iloc[0]
            candidates.append({
                "symbol": sym, "score": sc,
                "close": r["close"], "volume": r["volume"], "open": r["open"],
            })

        if len(candidates) < cfg.n_select:
            return

        candidates.sort(key=lambda x: x["score"], reverse=True)
        selected = candidates[:cfg.n_select]
        selected_syms = {s["symbol"] for s in selected}

        # ── 转为 dict 方便查找 ──
        selected_details = {s["symbol"]: s for s in selected}

        # ── 卖出不持有的股票 ──
        for sym in list(positions.keys()):
            if sym not in selected_syms:
                sdf = stock_data.get(sym)
                if sdf is None:
                    continue
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                r = row.iloc[0]
                close_p = r["close"]
                vol = r["volume"]
                pos = positions.pop(sym)
                max_sell = int(vol * cfg.volume_cap_pct)
                actual_sell = min(pos["shares"], max_sell // cfg.lot_size * cfg.lot_size)
                if actual_sell > 0:
                    proceeds = actual_sell * close_p * (1 - cfg.cost_rate)
                    cash += proceeds
                    trade_log.append({
                        "date": ds, "symbol": sym, "action": "SELL",
                        "shares": actual_sell, "price": close_p,
                        "notional": actual_sell * close_p,
                    })

        if not selected_details:
            return

        # ── Phase 1: 逆波动率风险平价 vs 等权重 ──
        if cfg.use_inverse_vol:
            vols = self.vol_sizer.compute_volatilities(
                stock_data, list(selected_details.keys()), ds,
            )
            weights_dict = self.vol_sizer.compute_weights(
                vols, list(selected_details.keys()),
            )
            prices = {sym: info["open"] for sym, info in selected_details.items()}
            allocations = self.vol_sizer.allocate_target_notionals(
                weights_dict, today_equity * 0.95, prices,
            )
        else:
            target_notional = today_equity / max(len(selected_details), 1) * 0.95
            allocations = {}
            for sym in selected_details:
                price = selected_details[sym]["open"]
                target_shares = int(target_notional / price)
                target_shares = max(target_shares // cfg.lot_size * cfg.lot_size, 0)
                allocations[sym] = {
                    "target_shares": target_shares,
                    "weight": 1.0 / len(selected_details),
                    "notional": target_shares * price,
                }

        # ── 执行买入 (含 5% 成交量容量锁) ──
        total_cash_drag = 0
        for sym, info in selected_details.items():
            alloc = allocations.get(sym)
            if alloc is None or alloc["target_shares"] <= 0:
                continue

            exec_price = info["open"] if info["open"] > 0 else info["close"]
            daily_vol = info["volume"]

            result = self.volume_capper.cap_shares(
                alloc["target_shares"], daily_vol, exec_price,
            )
            actual_shares = result["actual_shares"]
            cost = actual_shares * exec_price

            if cash < cost:
                continue

            if actual_shares > 0:
                cash -= cost * (1 + cfg.cost_rate)
                positions[sym] = {
                    "shares": actual_shares,
                    "buy_price": exec_price,
                    "buy_date": ds,
                }
                trade_log.append({
                    "date": ds, "symbol": sym, "action": "BUY",
                    "shares": actual_shares, "price": exec_price,
                    "notional": cost,
                    "score": info["score"],
                    "fill_rate": result["fill_rate"],
                    "capped": result["capped"],
                })

            if result["capped"]:
                total_cash_drag += result["cash_drag"]

        cash_drag_rate = total_cash_drag / max(today_equity, 1)
        cash_drag_log.append({
            "date": ds,
            "n_selected": len(selected_details),
            "total_cash_drag": total_cash_drag,
            "cash_drag_rate": cash_drag_rate,
            "equity": today_equity,
            "cash": cash,
        })

    def _compute_metrics(self, equity_curve, cash_drag_log, trade_log, final_equity):
        if not equity_curve:
            return {"error": "no trades"}

        eq_df = pd.DataFrame(equity_curve)
        eq_df["daily_ret"] = eq_df["equity"].pct_change().fillna(0)
        eq_df = eq_df[eq_df["daily_ret"] != 0]

        total_days = len(eq_df)
        total_years = total_days / 252

        if total_years < 0.2 or eq_df["daily_ret"].std() == 0:
            return {"error": "insufficient data"}

        total_ret = final_equity / self.config.initial_capital - 1
        ann_ret = (1 + total_ret) ** (1 / max(total_years, 0.1)) - 1
        ann_vol = eq_df["daily_ret"].std() * np.sqrt(252)
        sharpe = ann_ret / max(ann_vol, 1e-10)

        cumulative = (1 + eq_df["daily_ret"]).cumprod()
        running_max = cumulative.cummax()
        drawdown = cumulative / running_max - 1
        max_dd = drawdown.min()

        cd_df = pd.DataFrame(cash_drag_log)
        avg_cash_drag = cd_df["cash_drag_rate"].mean() if not cd_df.empty else 0.0
        calmar = ann_ret / max(abs(max_dd), 1e-10)

        buys = pd.DataFrame([t for t in trade_log if t["action"] == "BUY"])
        avg_fill = buys["fill_rate"].mean() if not buys.empty else 0.0

        n_buys = len(buys)
        avg_monthly = n_buys / max(total_years * 12, 1)

        return {
            "initial_capital": self.config.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return": total_ret,
            "annual_return": ann_ret,
            "annual_volatility": ann_vol,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "calmar_ratio": calmar,
            "avg_cash_drag": avg_cash_drag,
            "avg_fill_rate": avg_fill,
            "total_years": total_years,
            "total_trading_days": total_days,
            "n_trades_buy": n_buys,
            "avg_monthly_trades": avg_monthly,
        }


# ──────────────────────────────────────────────────────────────────────
# TEARSHEET 输出
# ──────────────────────────────────────────────────────────────────────
def print_tearsheet(results: dict, config: Config):
    if "error" in results:
        print(f"\n  ❌ {results['error']}")
        return

    phase = "Phase 1 (Composite Alpha + InvVol)" if config.use_inverse_vol else "Phase 1 (Composite Alpha + EqualWeight)"
    if config.enable_lppl_macro_veto or config.enable_wyckoff_micro_filter:
        phase += " + Phase 2 (LPPL+Wyckoff)"

    print(f"\n{'='*65}")
    print(f"  📊 机构级全维 TEARSHEET — {phase}")
    print(f"{'='*65}")

    print(f"\n  ┌─ 基本参数 {'─'*36}┐")
    print(f"  │  初始资金:     {results['initial_capital']:>14,.0f} CNY")
    print(f"  │  最终净值:     {results['final_equity']:>14,.0f} CNY")
    print(f"  │  回测区间:     {results['total_years']:>8.1f} 年 ({results['total_trading_days']}天)")
    print(f"  │  选股数量:     Top {config.n_select:>5}")
    print(f"  │  交易成本:     {config.cost_rate:.4f}  ({config.volume_cap_pct*100:.0f}% vol cap)")
    parts = [f"{k}={v:+.2f}" for k, v in config.factor_weights.items()]
    print(f"  │  因子权重:     {'  '.join(parts)}")
    print(f"  │  风险平价:     {'逆波动率' if config.use_inverse_vol else '等权重'}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 收益指标 {'─'*40}┐")
    print(f"  │  累计收益率:   {results['total_return']:>+12.2%}")
    print(f"  │  年化收益率:   {results['annual_return']:>+12.2%}")
    print(f"  │  年化波动率:   {results['annual_volatility']:>12.2%}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 风险指标 {'─'*40}┐")
    print(f"  │  夏普比率:     {results['sharpe_ratio']:>+12.4f}")
    print(f"  │  最大回撤:     {results['max_drawdown']:>12.2%}")
    print(f"  │  Calmar比率:   {results['calmar_ratio']:>+12.4f}")
    print(f"  └{'─'*50}┘")

    print(f"\n  🛡️  ★★★ 容量与执行指标 ★★★")
    print(f"  ┌─ 资金容量 {'─'*40}┐")
    print(f"  │  平均资金闲置率: {results['avg_cash_drag']:>12.2%}")
    print(f"  │  资金利用率:     {1-results['avg_cash_drag']:>12.2%}")
    print(f"  │  平均成交率:     {results['avg_fill_rate']:>12.2%}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 交易统计 {'─'*40}┐")
    print(f"  │  总买入次数:     {results['n_trades_buy']:>10}")
    print(f"  │  月均交易次数:   {results['avg_monthly_trades']:>10.1f}")
    print(f"  └{'─'*50}┘")

    # 判定
    ad = results['avg_cash_drag']
    sr = results['sharpe_ratio']
    dd = results['max_drawdown']
    print(f"\n  ┌─ 目标达标判定 {'─'*36}┐")
    print(f"  │  回撤 < 25%:     {'✅' if abs(dd) < 0.25 else '❌'}  ({dd:.1%})")
    print(f"  │  闲置率 < 20%:   {'✅' if ad < 0.20 else '❌'}  ({ad:.1%})")
    print(f"  │  夏普 > 1.0:     {'✅' if sr > 1.0 else '❌'}  ({sr:.2f})")
    print(f"  └{'─'*50}┘")

    print(f"\n  {'='*65}\n")


def main():
    cfg = Config()

    print("╔" + "═" * 63 + "╗")
    print("║  机构级全市场回测引擎                                    ║")
    print(f"║  资金: {cfg.initial_capital/1e8:.1f}亿  Vol Cap: {cfg.volume_cap_pct*100:.0f}%  "
          f"选股: Top {cfg.n_select}  {'逆波动率' if cfg.use_inverse_vol else '等权重'}  ║")
    print("╚" + "═" * 63 + "╝")

    symbols = load_universe(cfg)
    if not symbols:
        return
    print(f"\n  合格股票池: {len(symbols)}")

    # 预打分 (全量因子计算在 load_daily_data 阶段已完成)
    print(f"\n  因子矩阵: {list(cfg.factor_weights.keys())}")
    print(f"  权重配置: {cfg.factor_weights}")

    bt = InstitutionalBacktest(cfg)
    results = bt.run(symbols)

    print_tearsheet(results, cfg)

    # 保存报告
    report_path = Path("docs/reshaping_logs/06_institutional_tearsheet.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 06 — 机构级全维 TEARSHEET\n\n")
        f.write(f"> **Phase**: {'Phase 1' if not cfg.enable_lppl_macro_veto else 'Phase 1+2'}\n")
        f.write(f"> **资金**: {cfg.initial_capital:,.0f} CNY\n")
        f.write(f"> **因子**: {cfg.factor_weights}\n")
        f.write(f"> **风险平价**: {'逆波动率' if cfg.use_inverse_vol else '等权重'}\n")
        if "error" not in results:
            for k, label in [
                ("final_equity", "最终净值"),
                ("total_return", "累计收益率"),
                ("annual_return", "年化收益率"),
                ("annual_volatility", "年化波动率"),
                ("sharpe_ratio", "夏普比率"),
                ("max_drawdown", "最大回撤"),
                ("avg_cash_drag", "平均资金闲置率"),
            ]:
                f.write(f"- **{label}**: {results[k]:+.4f}\n" if k in ("total_return", "annual_return") else
                        f"- **{label}**: {results[k]:.4f}\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n  ⏸ [Halt & Wait — Phase 1 完成]")
    print(f"     请确认: 因子权重, 逆波动率是否启用, 或调整参数后重新运行\n")


if __name__ == "__main__":
    main()
