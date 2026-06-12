"""
The Institutional Crucible — 机构级 1亿 终极回测
=================================================

Phase 1: 纯 A 股 + ILLIQ 负向剔除 + 多因子复合 (CS_Mom - IVOL - PV_Div) + Top 300 逆波动率
Phase 2: LPPL 宏观熔断 + Wyckoff 微观一票否决
Phase 3: 全市场 1亿 极限回测

Usage:
  python3 experiments/run_institutional_crucible.py
"""

import os, sys, warnings, time
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uniquant.risk.sizer import VolumeLimitSizer, InverseVolatilitySizer

# ─── 惰性加载 (Phase 2) ───
def _lppl_engine():
    from uniquant.brain.lppl.engine import LPPLEngine
    return LPPLEngine()

def _wyckoff_engine():
    from uniquant.brain.wyckoff import WyckoffEngine
    return WyckoffEngine()


# ══════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════
@dataclass
class Config:
    initial_capital: float = 100_000_000
    volume_cap_pct: float = 0.05
    cost_rate: float = 0.0008
    lot_size: int = 100

    n_select: int = 300
    candidate_buffer: int = 100           # 缓冲供 Wyckoff 过滤

    # Phase 1: ILLIQ 负向剔除
    illiq_remove_pct: float = 0.20        # 剔除 ILLIQ 最高的 20%

    # Phase 1: 多因子复合 (等权)
    use_inverse_vol: bool = True
    vol_period: int = 20

    # Phase 2: LPPL
    enable_lppl: bool = False
    lppl_idx: str = "000300.SH"
    lppl_conf_threshold: float = 0.6
    lppl_vote_threshold: int = 2
    lppl_sustain_days: int = 3
    lppl_lift_threshold: float = 0.4

    # Phase 2: Wyckoff
    enable_wyckoff: bool = False

    # 路径
    qualified_file: str = "data/qualified_universe.csv"
    lake_dir: str = "data/lake/quotes/daily"
    start_date: str = "2018-01-01"
    end_date: str = "2019-12-31"

cfg = Config()

LAKE_DIR = Path(cfg.lake_dir)


# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════
def load_stock(symbol: str) -> Optional[pd.DataFrame]:
    fp = LAKE_DIR / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp, columns=[
            "date", "open", "high", "low", "close", "volume", "amount",
        ])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 250:
            return None
        return df
    except Exception:
        return None


def load_universe() -> list[str]:
    fp = Path(cfg.qualified_file)
    if not fp.exists():
        print(f"  ❌ 缺失 {fp}")
        return []
    return pd.read_csv(fp)["symbol"].tolist()


def load_index(symbol: str) -> Optional[pd.DataFrame]:
    df = load_stock(symbol)
    if df is not None:
        df = df[["date", "close"]].copy()
    return df


# ══════════════════════════════════════════════════════════════════
# 因子计算 (矢量化, 每只股票独立)
# ══════════════════════════════════════════════════════════════════
def calc_illiq(close: np.ndarray, amount: np.ndarray) -> np.ndarray:
    ret = np.abs(np.diff(close, prepend=close[0]) / np.maximum(close, 1e-10))
    daily = np.where(amount > 0, ret / amount, np.nan)
    return pd.Series(daily).rolling(20, min_periods=10).mean().values * 1e9


def calc_cs_momentum(close: np.ndarray) -> np.ndarray:
    n = len(close)
    r20 = np.full(n, np.nan); r5 = np.full(n, np.nan)
    r20[20:] = close[20:] / np.maximum(close[:-20], 1e-10) - 1
    r5[5:] = close[5:] / np.maximum(close[:-5], 1e-10) - 1
    r5 = np.where(r5 <= -1.0, np.nan, r5)
    mom = np.full(n, np.nan)
    mom[20:] = (1 + r20[20:]) / (1 + r5[20:]) - 1
    return mom


def calc_ma_ratio(close: np.ndarray) -> np.ndarray:
    n = len(close)
    ratio = np.full(n, np.nan)
    ma5 = pd.Series(close).rolling(5).mean().values
    ma20 = pd.Series(close).rolling(20, min_periods=5).mean().values
    mask = ma20 > 1e-10
    ratio[mask] = ma5[mask] / ma20[mask] - 1
    return ratio


def calc_pv_divergence(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    close_pct = pd.Series(close).rolling(20, min_periods=5).rank(pct=True).values
    vol_pct = pd.Series(volume).rolling(20, min_periods=5).rank(pct=True).values
    return vol_pct - close_pct


def calc_total_vol(close: np.ndarray) -> np.ndarray:
    """
    总波动率: 过去 60 天日收益率标准差 (年化)。
    低波 = 核心资产 = 高评分。
    """
    n = len(close)
    vol = np.full(n, np.nan)
    ret = np.diff(close) / np.maximum(close[:-1], 1e-10)
    for i in range(60, n):
        seg = ret[i-60:i]
        seg = seg[np.isfinite(seg)]
        if len(seg) < 20:
            continue
        vol[i] = np.std(seg, ddof=1) * np.sqrt(252)
    return vol


# ══════════════════════════════════════════════════════════════════
# Phase 2: LPPL + Wyckoff
# ══════════════════════════════════════════════════════════════════
def check_lppl_veto(ds: str, idx_df: pd.DataFrame, engine) -> dict:
    sub = idx_df[idx_df["date"] <= ds]
    if len(sub) < 200:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "short"}
    sub = sub.iloc[-600:]
    if len(sub) < 200:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "short"}
    try:
        r = engine.detect_bubble_confidence(sub)
        conf = r.get("confidence", 0.0)
        votes = r.get("votes", 0)
        veto = conf > cfg.lppl_conf_threshold and votes >= cfg.lppl_vote_threshold
        return {"veto": veto, "confidence": conf, "votes": votes,
                "risk_level": r.get("risk_level", "Safe")}
    except Exception:
        return {"veto": False, "confidence": 0.0, "votes": 0, "risk_level": "error"}


def wyckoff_is_distribution(sym: str, stock_data: dict, engine) -> bool:
    df = stock_data.get(sym)
    if df is None or len(df) < 100:
        return False
    try:
        r = engine.scan_signal(df.iloc[-180:].copy(), symbol=sym)
        return r.get("phase") == "distribution"
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 横截面 Z-Score 标准化
# ══════════════════════════════════════════════════════════════════
def cross_sectional_z(scores: dict[str, float]) -> dict[str, float]:
    arr = np.array([v for v in scores.values() if np.isfinite(v)])
    if len(arr) < 5:
        return {k: 0.0 for k in scores}
    mu, sigma = np.nanmean(arr), np.nanstd(arr)
    if sigma < 1e-12:
        sigma = 1.0
    return {k: ((v - mu) / sigma) if np.isfinite(v) else 0.0
            for k, v in scores.items()}


# ══════════════════════════════════════════════════════════════════
# 主引擎
# ══════════════════════════════════════════════════════════════════
class InstitutionalCrucible:
    def __init__(self):
        self.vol_sizer = InverseVolatilitySizer(
            vol_period=cfg.vol_period, lot_size=cfg.lot_size,
        )
        self.volume_capper = VolumeLimitSizer(cfg.volume_cap_pct)
        self.lppl_eng = _lppl_engine() if cfg.enable_lppl else None
        self.wyckoff_eng = _wyckoff_engine() if cfg.enable_wyckoff else None
        self._veto_active = False

    def run(self, symbols: list[str]) -> dict:
        t0 = time.time()

        # ── 1. 加载股票数据 + 因子 ──
        print(f"\n  [1/6] 加载 {len(symbols)} 只 A 股...")
        stock_data: dict = {}
        idx_df = load_index(cfg.lppl_idx)

        for i, sym in enumerate(symbols):
            df = load_stock(sym)
            if df is None:
                continue
            c = df["close"].values.astype(float)
            a = df["amount"].values.astype(float)
            v = df["volume"].values.astype(float)
            df["illiq"] = calc_illiq(c, a)
            df["pv_div"] = calc_pv_divergence(c, v)
            df["ma_ratio"] = calc_ma_ratio(c)
            df["total_vol"] = calc_total_vol(c)
            stock_data[sym] = df
            if (i + 1) % 500 == 0:
                print(f"    {i+1}/{len(symbols)}...", end="\r")
        print(f"\n  ✓ {len(stock_data)} 只 ({(time.time()-t0):.0f}s)")

        # ── 2. 日历 ──
        print("  [2/6] 日历...")
        all_dates = sorted({str(d)[:10] for sdf in stock_data.values()
                            for d in sdf["date"]})
        all_dates = [d for d in all_dates if cfg.start_date <= d <= cfg.end_date]
        rebal_dates, ym_set = [], set()
        for d in reversed(all_dates):
            if d[:7] not in ym_set:
                ym_set.add(d[:7])
                rebal_dates.append(d)
        rebal_dates = sorted(rebal_dates[1:])
        rebal_set = set(rebal_dates)
        print(f"    {len(all_dates)} 天, {len(rebal_dates)} 调仓日")

        # ── 3. 指数 (LPPL) ──
        if cfg.enable_lppl and idx_df is not None:
            print(f"  ✓ {cfg.lppl_idx}: {len(idx_df)} 行")
        elif cfg.enable_lppl:
            print(f"  ⚠ {cfg.lppl_idx} 缺失, LPPL 禁用")
            cfg.enable_lppl = False

        # ── 4. 回测 ──
        print("  [3/6] 运行回测...")
        cash = cfg.initial_capital
        positions: dict = {}
        eq_curve: list = []
        cd_log: list = []
        trade_log: list = []
        lppl_log: list = []
        wyckoff_log: list = []

        veto_streak = 0
        market_returns = None
        rebal_count = 0

        for di, ds in enumerate(all_dates):
            nav = cash
            for sym in list(positions.keys()):
                sdf = stock_data.get(sym)
                if sdf is None:
                    continue
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                nav += positions[sym]["shares"] * row["close"].values[0]
            eq_curve.append({"date": ds, "equity": nav, "cash": cash})

            if ds not in rebal_set:
                continue

            # ── LPPL ──
            lppl_veto = False
            if cfg.enable_lppl and idx_df is not None:
                state = check_lppl_veto(ds, idx_df, self.lppl_eng)
                lppl_log.append({"date": ds, **state})
                veto_streak = (veto_streak + 1) if state["veto"] else 0
                if veto_streak >= cfg.lppl_sustain_days:
                    lppl_veto = True
                    self._veto_active = True
                if self._veto_active and not state["veto"] and state["confidence"] < cfg.lppl_lift_threshold:
                    self._veto_active = False
                    veto_streak = 0

            if lppl_veto or self._veto_active:
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
                    actual = min(pos["shares"], max_sell // cfg.lot_size * cfg.lot_size)
                    if actual > 0:
                        cash += actual * r["close"] * (1 - cfg.cost_rate)
                        trade_log.append({"date": ds, "symbol": sym, "action": "SELL_LPPL",
                                          "shares": actual, "price": r["close"]})
                cd_log.append({"date": ds, "n": 0, "drag": 0.0, "nav": nav, "cash": cash, "veto": True})
                print(f"  🛡️ [{ds}] LPPL VETO — 清仓, NAV={nav:,.0f}")
                continue

            # ── 获取当日因子值 ──
            factors_at_date = {}
            for sym, sdf in stock_data.items():
                row = sdf[sdf["date"] == ds]
                if row.empty:
                    continue
                r = row.iloc[0]
                illiq = r.get("illiq", np.nan)
                pv_div = r.get("pv_div", np.nan)
                total_vol = r.get("total_vol", np.nan)
                ma_ratio = r.get("ma_ratio", np.nan)
                if not all(np.isfinite(x) for x in (pv_div, total_vol)):
                    continue
                factors_at_date[sym] = {
                    "illiq": illiq,
                    "pv_div": pv_div, "total_vol": total_vol,
                    "ma_ratio": ma_ratio,
                    "close": r["close"], "volume": r["volume"], "open": r["open"],
                }

            if len(factors_at_date) < cfg.n_select + 100:
                continue

            # ── Phase 1a: ILLIQ 负向剔除 (去掉最不流动的 20%) ──
            illiq_threshold = np.nanpercentile(
                [f["illiq"] for f in factors_at_date.values() if np.isfinite(f["illiq"])],
                100 * (1 - cfg.illiq_remove_pct),
            )
            screened = {
                sym: f for sym, f in factors_at_date.items()
                if np.isfinite(f["illiq"]) and f["illiq"] < illiq_threshold
            }
            if len(screened) < cfg.n_select + 100:
                illiq_threshold = float("inf")
                screened = factors_at_date
            print(f"  [{ds}] ILLIQ剔除后: {len(screened)} 只 (阈值={illiq_threshold:.3f})")

            # ── Phase 1b: 多因子复合打分 (秩标准化, 抗异常值) ──
            # Final_Score = Rank(-Total_Vol) + Rank(MaRatio_5_20) + Rank(-PV_Div)
            def rank_score(pairs: dict) -> dict:
                items = [(k, v) for k, v in pairs.items() if np.isfinite(v)]
                sorted_items = sorted(items, key=lambda x: x[1])
                n = len(sorted_items)
                if n < 10:
                    return {k: 0.0 for k in pairs}
                ranks = {sorted_items[i][0]: 2 * i / (n - 1) - 1 for i in range(n)}
                return ranks
            tv_s = rank_score({s: -f["total_vol"] for s, f in screened.items()})
            mr_s = rank_score({s: f["ma_ratio"] for s, f in screened.items()})
            pv_s = rank_score({s: -f["pv_div"] for s, f in screened.items()})
            scores = {s: tv_s.get(s, 0) + mr_s.get(s, 0) + pv_s.get(s, 0)
                      for s in screened}

            # ── 排序取 Top N + buffer ──
            ranked = sorted([(s, sc) for s, sc in scores.items() if np.isfinite(sc)],
                           key=lambda x: x[1], reverse=True)
            buffer_n = cfg.n_select + cfg.candidate_buffer
            top_candidates = ranked[:buffer_n]
            top_syms = {s for s, _ in top_candidates}

            # ── Phase 2: Wyckoff 过滤 ──
            if cfg.enable_wyckoff and self.wyckoff_eng:
                wyckoff_rejects = 0
                w_t0 = time.time()
                filtered = []
                for sym, sc in top_candidates:
                    if wyckoff_is_distribution(sym, stock_data, self.wyckoff_eng):
                        wyckoff_rejects += 1
                        wyckoff_log.append({"date": ds, "symbol": sym, "action": "REJECT_DIST"})
                        continue
                    filtered.append((sym, sc))
                print(f"  [{ds}] Wyckoff: {wyckoff_rejects} 否决, {len(filtered)} 通过 ({time.time()-w_t0:.0f}s)")
                top_candidates = filtered
                if len(top_candidates) < 50:
                    continue

            selected = top_candidates[:cfg.n_select]
            selected_syms = {s for s, _ in selected}
            selected_details = {s: factors_at_date[s] for s, _ in selected if s in factors_at_date}

            # ── DIAGNOSTIC: first 2 rebalances ──
            if rebal_count < 2:
                fvals = factors_at_date
                print(f"\n  === DIAGNOSTIC {ds} ===")
                for name in ["pv_div", "total_vol", "ma_ratio", "illiq"]:
                    vals = [f[name] for f in fvals.values() if np.isfinite(f.get(name))]
                    if not vals:
                        continue
                    p = np.percentile(vals, [1, 5, 25, 50, 75, 95, 99])
                    print(f"  {name:>12}: p1={p[0]:.3f} p5={p[1]:.3f} p25={p[2]:.3f} p50={p[3]:.3f} p75={p[4]:.3f} p95={p[5]:.3f} p99={p[6]:.3f}")
                print(f"  Top 10 selected:")
                for i, (sym, sc) in enumerate(selected[:10]):
                    f = factors_at_date.get(sym, {})
                    pv, tv, mr = f.get("pv_div",0), f.get("total_vol",0), f.get("ma_ratio",0)
                    print(f"  {i+1}. {sym} Score={sc:+.2f} PV={pv:.3f} TV={tv:.3f} MR={mr:.3f}")
                next_dates = sorted([d for d in all_dates if d > ds])[:21]
                if next_dates:
                    nd = next_dates[-1]
                    sr, ur = [], []
                    for sym, sdf in stock_data.items():
                        r0 = sdf[sdf["date"] == ds]
                        r1 = sdf[sdf["date"] == nd]
                        if r0.empty or r1.empty:
                            continue
                        p0, p1 = r0.iloc[0]["close"], r1.iloc[0]["close"]
                        if p0 > 0:
                            rr = p1/p0 - 1
                            ur.append(rr)
                            if sym in selected_syms:
                                sr.append(rr)
                    if sr and ur:
                        print(f"  Fwd1m: sel avg={np.mean(sr):+.2%} med={np.median(sr):+.2%}  uni avg={np.mean(ur):+.2%} med={np.median(ur):+.2%}")
                print()
            rebal_count += 1

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
                    actual = min(pos["shares"], max_sell // cfg.lot_size * cfg.lot_size)
                    if actual > 0:
                        cash += actual * r["close"] * (1 - cfg.cost_rate)
                        trade_log.append({"date": ds, "symbol": sym, "action": "SELL",
                                          "shares": actual, "price": r["close"]})

            # ── Phase 1c: 逆波动率加权 ──
            if cfg.use_inverse_vol:
                vols = self.vol_sizer.compute_volatilities(
                    stock_data, list(selected_details.keys()), ds,
                )
                weights = self.vol_sizer.compute_weights(
                    vols, list(selected_details.keys()),
                )
                prices = {s: info["close"] for s, info in selected_details.items()}
                allocs = self.vol_sizer.allocate_target_notionals(
                    weights, nav * 0.95, prices,
                )
            else:
                target = nav / max(len(selected_details), 1) * 0.95
                allocs = {}
                for sym in selected_details:
                    p = selected_details[sym]["close"]
                    sh = max(int(target / p) // cfg.lot_size * cfg.lot_size, 0)
                    allocs[sym] = {"target_shares": sh, "weight": 1.0/len(selected_details)}

            # ── 买入 ──
            total_drag = 0
            for sym, info in selected_details.items():
                a = allocs.get(sym)
                if a is None or a["target_shares"] <= 0:
                    continue
                ep = info["close"]
                result = self.volume_capper.cap_shares(a["target_shares"], info["volume"], ep)
                actual = result["actual_shares"]
                cost = actual * ep
                if cash < cost:
                    continue
                if actual > 0:
                    cash -= cost * (1 + cfg.cost_rate)
                    positions[sym] = {"shares": actual, "buy_price": ep, "buy_date": ds}
                    trade_log.append({"date": ds, "symbol": sym, "action": "BUY",
                                      "shares": actual, "price": ep, "notional": cost,
                                      "fill_rate": result["fill_rate"], "capped": result["capped"]})
                if result["capped"]:
                    total_drag += result["cash_drag"]

            drag_rate = total_drag / max(nav, 1)
            cd_log.append({"date": ds, "n": len(selected_details), "drag": drag_rate,
                           "nav": nav, "cash": cash, "veto": False})
            print(f"  [{ds}] NAV={nav:>10,.0f}  nPos={len(positions):>3}  "
                  f"Drag={drag_rate:.1%}  Score={selected[0][1]:+.2f}")

        # ── 5. 清算 ──
        for sym in list(positions.keys()):
            sdf = stock_data.get(sym)
            if sdf is None:
                continue
            last = sdf.iloc[-1]
            cash += positions[sym]["shares"] * last["close"] * (1 - cfg.cost_rate)
        positions.clear()

        # ── 6. 绩效 ──
        r = self._metrics(eq_curve, cd_log, trade_log, lppl_log, wyckoff_log, cash)
        r["stock_data"] = stock_data
        r["run_time"] = time.time() - t0
        return r

    def _metrics(self, eq, cd, trades, lppl_log, wyckoff_log, final):
        if not eq:
            return {"error": "no data"}
        eq_df = pd.DataFrame(eq)
        eq_df["ret"] = eq_df["equity"].pct_change().fillna(0)
        eq_df = eq_df[eq_df["ret"] != 0]
        n_days = len(eq_df)
        n_yrs = n_days / 252
        if n_yrs < 0.2 or eq_df["ret"].std() == 0:
            return {"error": "insufficient data"}
        tot_ret = final / cfg.initial_capital - 1
        ann_ret = (1 + tot_ret) ** (1 / max(n_yrs, 0.1)) - 1
        ann_vol = eq_df["ret"].std() * np.sqrt(252)
        sharpe = ann_ret / max(ann_vol, 1e-10)
        cum = (1 + eq_df["ret"]).cumprod()
        dd = (cum / cum.cummax() - 1).min()

        cd_df = pd.DataFrame(cd)
        avg_drag = cd_df["drag"].mean() if not cd_df.empty else 0.0
        calmar = ann_ret / max(abs(dd), 1e-10)
        buys = pd.DataFrame([t for t in trades if t["action"] == "BUY"])
        avg_fill = buys["fill_rate"].mean() if not buys.empty else 0.0
        lppl_df = pd.DataFrame(lppl_log)
        n_lppl = int(lppl_df["veto"].sum()) if not lppl_df.empty else 0
        n_veto_days = int(cd_df["veto"].sum()) if "veto" in cd_df.columns else 0

        return {
            "initial_capital": cfg.initial_capital,
            "final_equity": round(final, 2),
            "total_return": tot_ret,
            "annual_return": ann_ret,
            "annual_volatility": ann_vol,
            "sharpe_ratio": sharpe,
            "max_drawdown": dd,
            "calmar_ratio": calmar,
            "avg_cash_drag": avg_drag,
            "avg_fill_rate": avg_fill,
            "n_trading_days": n_days,
            "n_trades_buy": len(buys),
            "n_lppl_vetos": n_lppl,
            "n_lppl_veto_days": n_veto_days,
        }


# ══════════════════════════════════════════════════════════════════
# TEARSHEET
# ══════════════════════════════════════════════════════════════════
def tearsheet(r: dict):
    if "error" in r:
        print(f"\n  ❌ {r['error']}")
        return
    print(f"\n{'='*65}")
    print(f"  ⚔️  机构级 1亿 全维 TEARSHEET")
    print(f"{'='*65}")
    print(f"  Phase 1: ILLIQ剔除{cfg.illiq_remove_pct:.0%} + 多因子复合 + Top {cfg.n_select} + 逆波动率")
    print(f"  Phase 2: LPPL{'✅' if cfg.enable_lppl else '❌'}  Wyckoff{'✅' if cfg.enable_wyckoff else '❌'}")
    print(f"  初始资金: {cfg.initial_capital:>13,.0f} CNY")
    print(f"  {'─'*50}")
    print(f"  累计收益率:      {r['total_return']:>+12.2%}")
    print(f"  年化收益率:      {r['annual_return']:>+12.2%}")
    print(f"  年化波动率:      {r['annual_volatility']:>12.2%}")
    print(f"  夏普比率:        {r['sharpe_ratio']:>+12.4f}")
    print(f"  最大回撤:        {r['max_drawdown']:>12.2%}")
    print(f"  Calmar比率:      {r['calmar_ratio']:>+12.4f}")
    print(f"  资金闲置率:      {r['avg_cash_drag']:>12.2%}")
    print(f"  平均成交率:      {r['avg_fill_rate']:>12.2%}")
    print(f"  LPPL触发:        {r['n_lppl_vetos']} 次 ({r['n_lppl_veto_days']}天)")
    print(f"  {'─'*50}")
    ad, sr, dd = r['avg_cash_drag'], r['sharpe_ratio'], r['max_drawdown']
    print(f"  闲置率<20%: {'✅' if ad < 0.20 else '❌'} ({ad:.1%})  回撤<25%: {'✅' if abs(dd) < 0.25 else '❌'} ({dd:.1%})  夏普>1.0: {'✅' if sr > 1.0 else '❌'} ({sr:.2f})")
    print(f"{'='*65}\n")


def main():
    print("╔" + "═" * 63 + "╗")
    print("║  Institutional Crucible — 机构级 1亿 终极回测       ║")
    print(f"║  复合Alpha Top {cfg.n_select} + 逆波动率 + 5%VolCap         ║")
    print(f"║  ILLIQ剔除{cfg.illiq_remove_pct:.0%}  LPPL{'✅' if cfg.enable_lppl else '❌'} Wyckoff{'✅' if cfg.enable_wyckoff else '❌'}  ║")
    print("╚" + "═" * 63 + "╝")

    symbols = load_universe()
    if not symbols:
        return
    print(f"  A股池: {len(symbols)} 只 (已剔除基金/LOF/ETF)")

    engine = InstitutionalCrucible()
    results = engine.run(symbols)
    tearsheet(results)

    report_path = Path("docs/reshaping_logs/06_institutional_crucible.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 06 — 机构级 1亿 全维 TEARSHEET\n\n")
        for k in ["total_return", "annual_return", "annual_volatility", "sharpe_ratio",
                   "max_drawdown", "avg_cash_drag"]:
            if k in results:
                f.write(f"- **{k}**: {results[k]:+.4f}\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"  ⏸ [Halt & Wait]  Phase 1 引擎确认")


if __name__ == "__main__":
    main()
