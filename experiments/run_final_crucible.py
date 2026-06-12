"""
Phase 1+2+3: The 100M Final Crucible — 机构级终极回测
=====================================================

装甲配置:
  Phase 1 — 纯 ILLIQ Top 300 + 逆波动率 + 5% 容量锁
  Phase 2 — LPPL 大盘熔断闸门 + Wyckoff 微观一票否决

启动命令:
  python3 experiments/run_final_crucible.py

[Halt & Wait — Phase 1 代码改动待确认后进入 Phase 2]
"""

import os, sys, warnings, time
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uniquant.risk.sizer import VolumeLimitSizer, InverseVolatilitySizer

# ─── Phase 2 进口 (惰性加载, 避免 import 拖慢启动) ───
def _get_lppl_engine():
    from uniquant.brain.lppl.engine import LPPLEngine
    return LPPLEngine()

def _get_wyckoff_engine():
    from uniquant.brain.wyckoff import WyckoffEngine
    return WyckoffEngine()


# ══════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════
@dataclass
class Config:
    # ─── 资金与容量 ───
    initial_capital: float = 100_000_000
    volume_cap_pct: float = 0.05
    cost_rate: float = 0.0008
    lot_size: int = 100

    # ─── 选股 ───
    n_select: int = 300                     # 暴力扩容至 Top 300
    candidate_buffer: int = 100             # 提前多选 N 只供 Wyckoff 过滤缓冲

    # ─── Phase 1: 纯 ILLIQ + 逆波动率 ───
    use_inverse_vol: bool = True
    vol_period: int = 20

    # ─── Phase 2: LPPL 宏观熔断 ───
    enable_lppl: bool = False               # 🔴 暂时关闭 (debug)
    lppl_idx_symbol: str = "000300.SH"      # 沪深 300
    lppl_confidence_threshold: float = 0.6  # 置信度 > 0.6
    lppl_vote_threshold: int = 2            # 多窗口 > 2/3 投票
    lppl_sustain_days: int = 3              # 持续天数
    lppl_lift_threshold: float = 0.4        # 恢复交易阈值 (滞后)

    # ─── Phase 2: Wyckoff 微观过滤 ───
    enable_wyckoff: bool = False            # 🔴 暂时关闭 (debug)

    # ─── 路径 ───
    qualified_file: str = "data/qualified_universe.csv"
    lake_dir: str = "data/lake/quotes/daily"
    start_date: str = "2018-01-01"
    end_date: str = "2026-06-09"

config = Config()

# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════
LAKE_DIR = Path(config.lake_dir)
QUALIFIED_FILE = Path(config.qualified_file)


def load_stock_data(symbol: str) -> pd.DataFrame | None:
    fp = LAKE_DIR / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp, columns=[
            "date", "open", "high", "low", "close", "volume", "amount",
        ])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def load_universe() -> list[str]:
    if not QUALIFIED_FILE.exists():
        print(f"  ❌ 未找到 {QUALIFIED_FILE}")
        return []
    q = pd.read_csv(QUALIFIED_FILE)
    return q["symbol"].tolist()


# ══════════════════════════════════════════════════════════════════
# ILLIQ 计算 (矢量化)
# ══════════════════════════════════════════════════════════════════
def compute_illiq(close: np.ndarray, amount: np.ndarray) -> np.ndarray:
    ret = np.abs(np.diff(close, prepend=close[0]) / np.maximum(close, 1e-10))
    daily = np.where(amount > 0, ret / amount, np.nan)
    return pd.Series(daily).rolling(20, min_periods=10).mean().values * 1e9


# ══════════════════════════════════════════════════════════════════
# Phase 2: LPPL 宏观熔断检测
# ══════════════════════════════════════════════════════════════════
def check_lppl_macro_veto(
    ds: str,
    idx_data: pd.DataFrame,
    engine,
) -> dict:
    """
    检查是否触发 LPPL 宏观熔断。

    规则:
      - 取 index 数据截至 ds 的最近 600 交易日
      - 如果 detect_bubble_confidence 返回
        confidence > 0.6 AND votes >= 2 → 触发预警

    Returns:
      {"veto": bool, "confidence": float, "votes": int, "risk_level": str}
    """
    sub = idx_data[idx_data["date"] <= ds]
    if len(sub) < 200:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "insufficient_data"}

    sub = sub.iloc[-600:]
    if len(sub) < 200:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "insufficient_data"}

    try:
        result = engine.detect_bubble_confidence(sub)
        conf = result.get("confidence", 0.0)
        votes = result.get("votes", 0)
        risk = result.get("risk_level", "Safe")

        veto = (conf > config.lppl_confidence_threshold and
                votes >= config.lppl_vote_threshold)

        return {
            "veto": veto,
            "confidence": conf,
            "votes": votes,
            "risk_level": risk,
        }
    except Exception:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "error"}


# ══════════════════════════════════════════════════════════════════
# Phase 2: Wyckoff 微观过滤
# ══════════════════════════════════════════════════════════════════
def wyckoff_is_distribution(
    sym: str,
    stock_data: dict,
    engine,
) -> bool:
    """
    检查单只股票是否处于 Wyckoff 派发 (Distribution) 阶段。
    一票否决: True = 踢出买入名单
    """
    df = stock_data.get(sym)
    if df is None or len(df) < 100:
        return False

    try:
        # 取最后 180 天 (Wyckoff 推荐窗口)
        sub = df.iloc[-180:].copy()
        result = engine.scan_signal(sub, symbol=sym)
        return result.get("phase") == "distribution"
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 主回测引擎
# ══════════════════════════════════════════════════════════════════
class FinalCrucible:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.vol_sizer = InverseVolatilitySizer(
            vol_period=cfg.vol_period, lot_size=cfg.lot_size,
        )
        self.volume_capper = VolumeLimitSizer(cfg.volume_cap_pct)
        self.lppl_engine = _get_lppl_engine() if cfg.enable_lppl else None
        self.wyckoff_engine = _get_wyckoff_engine() if cfg.enable_wyckoff else None
        self._macro_veto_active = False       # 熔断状态

    def run(self, symbols: list[str]) -> dict:
        t0 = time.time()
        cfg = self.cfg

        # ── 1. 加载数据 ──
        print(f"\n  [1/5] 加载 {len(symbols)} 只股票...")
        stock_data: dict = {}
        for i, sym in enumerate(symbols):
            df = load_stock_data(sym)
            if df is not None and len(df) >= 120:
                close = df["close"].values.astype(np.float64)
                amount = df["amount"].values.astype(np.float64)
                df["illiq"] = compute_illiq(close, amount)
                stock_data[sym] = df
            if (i + 1) % 500 == 0:
                print(f"    {i+1}/{len(symbols)}...", end="\r")
        print(f"\n  ✓ {len(stock_data)} 只有效 ({(time.time()-t0):.0f}s)")

        # ── 2. 交易日历 ──
        print("  [2/5] 构建交易日历...")
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
        rebalance_dates = sorted(rebalance_dates[1:])
        rebalance_set = set(rebalance_dates)
        print(f"    {len(all_dates)} 天, {len(rebalance_dates)} 个调仓日")

        # ── 2b. 加载 CSI 300 指数数据 ──
        idx_data = None
        if cfg.enable_lppl:
            idx_df = load_stock_data(cfg.lppl_idx_symbol)
            if idx_df is not None:
                idx_data = idx_df
                print(f"  ✓ LPPL 指数 {cfg.lppl_idx_symbol}: {len(idx_data)} 行")
            else:
                print(f"  ⚠ LPPL 指数 {cfg.lppl_idx_symbol} 未加载, 熔断禁用")

        # ── 3. 回测主循环 ──
        print("  [3/5] 运行组合回测...")
        cash = cfg.initial_capital
        positions: dict[str, dict] = {}
        equity_curve: list[dict] = []
        cash_drag_log: list[dict] = []
        trade_log: list[dict] = []
        lppl_log: list[dict] = []
        wyckoff_log: list[dict] = []

        self._macro_veto_active = False
        veto_streak = 0

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
                today_equity += positions[sym]["shares"] * row["close"].values[0]

            equity_curve.append({"date": ds, "equity": today_equity, "cash": cash})

            if ds not in rebalance_set:
                continue

            # ── 每个调仓日逻辑 ──

            # ── Phase 2a: LPPL 宏观熔断 ──
            lppl_veto = False
            if cfg.enable_lppl and idx_data is not None:
                lppl_state = check_lppl_macro_veto(ds, idx_data, self.lppl_engine)
                lppl_log.append({"date": ds, **lppl_state})

                if lppl_state["veto"]:
                    veto_streak += 1
                else:
                    veto_streak = 0

                # 持续 3 天以上触发熔断
                if veto_streak >= cfg.lppl_sustain_days:
                    lppl_veto = True
                    self._macro_veto_active = True

                # 熔断恢复: 置信度回落至 0.4 以下
                if self._macro_veto_active and not lppl_state["veto"]:
                    if lppl_state["confidence"] < cfg.lppl_lift_threshold:
                        self._macro_veto_active = False
                        veto_streak = 0

            if lppl_veto or self._macro_veto_active:
                # 清仓 → 100% 现金
                for sym in list(positions.keys()):
                    sdf = stock_data.get(sym)
                    if sdf is None:
                        continue
                    row = sdf[sdf["date"] == ds]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                    pos = positions.pop(sym)
                    max_sell = int(r["volume"] * cfg.volume_cap_pct)
                    actual_sell = min(pos["shares"],
                                      max_sell // cfg.lot_size * cfg.lot_size)
                    if actual_sell > 0:
                        cash += actual_sell * r["close"] * (1 - cfg.cost_rate)
                        trade_log.append({
                            "date": ds, "symbol": sym, "action": "SELL_LPPL",
                            "shares": actual_sell, "price": r["close"],
                            "notional": actual_sell * r["close"],
                        })
                cash_drag_log.append({
                    "date": ds, "n_selected": 0,
                    "total_cash_drag": 0, "cash_drag_rate": 0.0,
                    "equity": today_equity, "cash": cash,
                    "lppl_veto": True,
                })
                continue

            # ── A股代码类型过滤 (剔除基金/ETF/LOF) ──
            # 有效: 600/601/603=沪主板, 000/001/002=深主板/SME,
            #       300=创业板, 688=科创板, 4xx/8xx=北交所
            # 无效: 15xxx=LOF, 16xxx=LOF, 51xxx=ETF, 159xxx=深ETF
            def _is_stock_code(sym: str) -> bool:
                code = sym.split(".")[0]
                if len(code) != 6:
                    return False
                return (code.startswith(("600", "601", "603", "605",
                                         "000", "001", "002",
                                         "300", "301",
                                         "688", "689",
                                         "4", "8")))

            # ── 正常调仓: ILLIQ 排序 ──
            candidates = []
            for sym, sdf in stock_data.items():
                if not _is_stock_code(sym):
                    continue
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                r = row.iloc[0]
                illiq = r.get("illiq", np.nan)
                if not np.isfinite(illiq) or illiq <= 0:
                    continue
                candidates.append({
                    "symbol": sym, "score": illiq,
                    "close": r["close"], "volume": r["volume"], "open": r["open"],
                })

            if len(candidates) < cfg.n_select:
                continue

            # 按 ILLIQ 降序
            candidates.sort(key=lambda x: x["score"], reverse=True)

            # ── Phase 2b: Wyckoff 微观过滤 ──
            buffer_n = cfg.n_select + cfg.candidate_buffer
            top_candidates = candidates[:buffer_n]

            if cfg.enable_wyckoff and self.wyckoff_engine is not None:
                wyckoff_t0 = time.time()
                filtered = []
                wyckoff_rejects = 0
                for c in top_candidates:
                    if wyckoff_is_distribution(
                        c["symbol"], stock_data, self.wyckoff_engine,
                    ):
                        wyckoff_rejects += 1
                        wyckoff_log.append({
                            "date": ds, "symbol": c["symbol"],
                            "action": "REJECT_DISTRIBUTION",
                        })
                        continue
                    filtered.append(c)
                wyckoff_time = time.time() - wyckoff_t0
                top_candidates = filtered

                if len(top_candidates) < cfg.n_select:
                    print(f"  ⚠ [{ds}] 只剩 {len(top_candidates)} 只通过 Wyckoff, "
                          f"不足 {cfg.n_select}")
                    if len(top_candidates) < 50:
                        # 太少股票 → 跳过本月
                        continue

            selected = top_candidates[:cfg.n_select]
            selected_syms = {s["symbol"] for s in selected}
            selected_details = {s["symbol"]: s for s in selected}

            # ── 卖出 ──
            for sym in list(positions.keys()):
                if sym not in selected_syms:
                    sdf = stock_data.get(sym)
                    if sdf is None:
                        continue
                    row = sdf[sdf["date"] == ds]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                    pos = positions.pop(sym)
                    max_sell = int(r["volume"] * cfg.volume_cap_pct)
                    actual_sell = min(pos["shares"],
                                      max_sell // cfg.lot_size * cfg.lot_size)
                    if actual_sell > 0:
                        cash += actual_sell * r["close"] * (1 - cfg.cost_rate)
                        trade_log.append({
                            "date": ds, "symbol": sym, "action": "SELL",
                            "shares": actual_sell, "price": r["close"],
                            "notional": actual_sell * r["close"],
                        })

            # ── Phase 1b: 逆波动率风险平价 ──
            if cfg.use_inverse_vol:
                vols = self.vol_sizer.compute_volatilities(
                    stock_data, list(selected_details.keys()), ds,
                )
                weights = self.vol_sizer.compute_weights(
                    vols, list(selected_details.keys()),
                )
                prices = {sym: info["open"] for sym, info in selected_details.items()}
                allocations = self.vol_sizer.allocate_target_notionals(
                    weights, today_equity * 0.95, prices,
                )
            else:
                target_notional = today_equity / max(len(selected_details), 1) * 0.95
                allocations = {}
                for sym in selected_details:
                    price = selected_details[sym]["open"]
                    target_shares = int(target_notional / price)
                    target_shares = max(
                        target_shares // cfg.lot_size * cfg.lot_size, 0
                    )
                    allocations[sym] = {
                        "target_shares": target_shares,
                        "weight": 1.0 / len(selected_details),
                        "notional": target_shares * price,
                    }

            # ── 执行买入 (含 5% 容量锁) ──
            total_cash_drag = 0
            for sym, info in selected_details.items():
                alloc = allocations.get(sym)
                if alloc is None or alloc["target_shares"] <= 0:
                    continue
                exec_price = info["open"] if info["open"] > 0 else info["close"]
                result = self.volume_capper.cap_shares(
                    alloc["target_shares"], info["volume"], exec_price,
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
                        "date": ds, "symbol": sym,
                        "action": "BUY",
                        "shares": actual_shares,
                        "price": exec_price,
                        "notional": cost,
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
                "lppl_veto": False,
            })

            # 每月打印 NAV 轨迹
            print(f"  [{ds}] NAV={today_equity:>12,.0f}  "
                  f"Cash={cash:>10,.0f}  "
                  f"nPos={len(positions):>3}  "
                  f"Drag={cash_drag_rate:.1%}  "
                  f"{'🛡️VETO' if self._macro_veto_active else ''}")

        # ── 4. 清算 ──
        for sym in list(positions.keys()):
            sdf = stock_data.get(sym)
            if sdf is None:
                continue
            last = sdf.iloc[-1]
            cash += positions[sym]["shares"] * last["close"] * (1 - cfg.cost_rate)
        positions.clear()
        final_equity = cash

        # ── 5. 绩效 ──
        results = self._compute_metrics(equity_curve, cash_drag_log, trade_log,
                                        lppl_log, wyckoff_log, final_equity)
        results["run_time"] = time.time() - t0
        return results

    def _compute_metrics(self, equity_curve, cash_drag_log, trade_log,
                          lppl_log, wyckoff_log, final_equity):
        if not equity_curve:
            return {"error": "no trades"}

        eq_df = pd.DataFrame(equity_curve)
        eq_df["daily_ret"] = eq_df["equity"].pct_change().fillna(0)
        eq_df = eq_df[eq_df["daily_ret"] != 0]

        total_days = len(eq_df)
        total_years = total_days / 252

        if total_years < 0.2 or eq_df["daily_ret"].std() == 0:
            return {"error": "insufficient data"}

        total_ret = final_equity / self.cfg.initial_capital - 1
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

        # LPPL 统计
        lppl_df = pd.DataFrame(lppl_log)
        n_lppl_vetos = lppl_df["veto"].sum() if not lppl_df.empty else 0

        # Wyckoff 统计
        wyckoff_df = pd.DataFrame(wyckoff_log)
        n_wyckoff_rejects = len(wyckoff_df) if not wyckoff_df.empty else 0

        # 熔断天数
        n_veto_days = cd_df["lppl_veto"].sum() if "lppl_veto" in cd_df.columns else 0

        return {
            "initial_capital": self.cfg.initial_capital,
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
            "n_trading_days": total_days,
            "n_trades_buy": n_buys,
            "n_lppl_vetos": int(n_lppl_vetos),
            "n_lppl_veto_days": int(n_veto_days),
            "n_wyckoff_rejects": n_wyckoff_rejects,
        }


# ══════════════════════════════════════════════════════════════════
# TEARSHEET
# ══════════════════════════════════════════════════════════════════
def print_tearsheet(r: dict, cfg: Config):
    if "error" in r:
        print(f"\n  ❌ {r['error']}")
        return

    print(f"\n{'='*65}")
    print(f"  ⚔️  1亿终极决战 — 机构级全维 TEARSHEET")
    print(f"{'='*65}")

    print(f"\n  ┌─ 装甲配置 {'─'*38}┐")
    print(f"  │  Phase 1: 纯 ILLIQ Top {cfg.n_select} + 逆波动率 + 5% VolCap")
    print(f"  │  Phase 2: LPPL熔断{'✅' if cfg.enable_lppl else '❌'}  "
          f"Wyckoff过滤{'✅' if cfg.enable_wyckoff else '❌'}")
    print(f"  │  初始资金: {cfg.initial_capital:>13,.0f} CNY")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 收益 {'─'*44}┐")
    print(f"  │  累计收益率:   {r['total_return']:>+12.2%}")
    print(f"  │  年化收益率:   {r['annual_return']:>+12.2%}")
    print(f"  │  年化波动率:   {r['annual_volatility']:>12.2%}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 风险 {'─'*44}┐")
    print(f"  │  夏普比率:     {r['sharpe_ratio']:>+12.4f}")
    print(f"  │  最大回撤:     {r['max_drawdown']:>12.2%}")
    print(f"  │  Calmar比率:   {r['calmar_ratio']:>+12.4f}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 容量 {'─'*44}┐")
    print(f"  │  平均资金闲置率: {r['avg_cash_drag']:>12.2%}")
    print(f"  │  资金利用率:     {1-r['avg_cash_drag']:>12.2%}")
    print(f"  │  平均成交率:     {r['avg_fill_rate']:>12.2%}")
    print(f"  └{'─'*50}┘")

    print(f"\n  ┌─ 风控统计 {'─'*40}┐")
    print(f"  │  LPPL 熔断触发:  {r['n_lppl_vetos']:>8} 次  "
          f"({r['n_lppl_veto_days']}天)")
    print(f"  │  Wyckoff 否决:   {r['n_wyckoff_rejects']:>8} 次")
    print(f"  │  总买入:         {r['n_trades_buy']:>8} 次")
    print(f"  └{'─'*50}┘")

    # 判定
    ad = r['avg_cash_drag']
    sr = r['sharpe_ratio']
    dd = r['max_drawdown']
    print(f"\n  {'─'*50}")
    print(f"  📋 目标达标判定")
    print(f"  {'─'*50}")
    print(f"  ✅ 回撤 < 25%:   {'✅ PASS' if abs(dd) < 0.25 else '❌ FAIL'}  "
          f"({dd:.1%})")
    print(f"  ✅ 闲置率 < 20%: {'✅ PASS' if ad < 0.20 else '❌ FAIL'}  "
          f"({ad:.1%})")
    print(f"  ✅ 夏普 > 1.0:   {'✅ PASS' if sr > 1.0 else '❌ FAIL'}  "
          f"({sr:.2f})")
    print(f"  {'─'*50}")
    n_pass = sum([abs(dd) < 0.25, ad < 0.20, sr > 1.0])
    print(f"  🔥 综合: {n_pass}/3 通过")
    print(f"\n{'='*65}\n")


def main():
    cfg = Config()

    print("╔" + "═" * 63 + "╗")
    print("║  1 亿 终极决战 — The 100M Final Crucible              ║")
    print(f"║  ILLIQ Top {cfg.n_select} + 逆波动率 + 5% VolCap            ║")
    print(f"║  LPPL {'✅' if cfg.enable_lppl else '❌'}  Wyckoff {'✅' if cfg.enable_wyckoff else '❌'}                          ║")
    print("╚" + "═" * 63 + "╝")

    symbols = load_universe()
    if not symbols:
        return
    print(f"  合格股票池: {len(symbols)} 只")

    bt = FinalCrucible(cfg)
    results = bt.run(symbols)

    print_tearsheet(results, cfg)

    report_path = Path("docs/reshaping_logs/06_final_crucible.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 06 — 1亿终极决战 TEARSHEET\n\n")
        f.write(f"> Phase 1: ILLIQ Top {cfg.n_select} + 逆波动率 + 5%VolCap\n")
        f.write(f"> Phase 2: LPPL={'ON' if cfg.enable_lppl else 'OFF'} "
                f"Wyckoff={'ON' if cfg.enable_wyckoff else 'OFF'}\n")
        f.write(f"> 初始资金: {cfg.initial_capital:,.0f}\n\n")
        for k, label in [
            ("total_return", "累计收益率"),
            ("annual_return", "年化收益率"),
            ("annual_volatility", "年化波动率"),
            ("sharpe_ratio", "夏普比率"),
            ("max_drawdown", "最大回撤"),
            ("avg_cash_drag", "平均资金闲置率"),
            ("avg_fill_rate", "平均成交率"),
        ]:
            if k in results:
                f.write(f"- **{label}**: {results[k]:+.4f}\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n  ⏸ [Halt & Wait] Phase 1 代码就绪。")
    print(f"    确认后进入 Phase 2 (激活 LPPL+Wyckoff) 并执行 1亿 终极回测")


if __name__ == "__main__":
    main()
