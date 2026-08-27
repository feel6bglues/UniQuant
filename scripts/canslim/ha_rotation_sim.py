"""H-A — 真实 30-slot 轮换回测引擎 (生产匹配成交, 替代 scaled_30 线性近似)。

背景 (P13 对账固化):
  - ha_unified_adapter --full 给出 slot_pool (385 独立子账户) +0.97%/1.12/−1.71%
    (任一时刻仅 ~30/385≈8% slot 在场, 资金效率被 N=len(ever_held) 稀释)
  - scaled_30 = slot_pool ×(N/30) 是"资金效率归一到 30-slot"的线性近似,
    它假设 slot 日收益线性放大, 未模拟"腾出 slot 的 NAV 复利投入下一只
    名称"的滚动轮换路径 —— 本引擎消除该假设。

本引擎 (SlotRotationSim): 真正的 30 个持久仓位单元。
  - 每 slot 持 ≤1 只名称 + 现金; 退出名卖出后, 该 slot 的累积 NAV 投入下个新进名
    (slot 级复利 — 这正是 ×12.83 线性缩放伪造的部分)
  - 再平衡日 (hmap 变更): 目标 = Top30 illiq, 5 日再平衡 + 状态切换, 涨停不可追;
    keeps 不动 (零换手, 对应 P8 仅对 set-change 计成本的理想约定);
    退出卖出 / 新进买入均经生产 UnifiedMatchingEngine 成交
    (万3佣金 + 千1滑点 + 万5印花税卖出 + 单笔最低5元 + 过户费 + T+1 + 涨停拒单 + lot100)
  - 成交价: 决策日 t 收盘 ± 滑点 (近收盘成交); 建仓日当日计入 NAV 标记但收益从
    次日开始 (中性), 与 P8 "加权作用于 t 日 close→close" 理想口径的建仓日时序差
    如实披露
  - NAV(t) = Σ_slot(cash + 持仓×close_t) + 残余现金

对照参照 (冻结): P8 STRAT-A 样本500 +15.82%/1.33/−12.9% (理想 mean-of-returns
  口径); P10 FULL +9.98%/0.93/−22.2%。本引擎为生产口径, 允许建仓日时序差带来
  的保守偏差, 目标为量级一致 + 差异可解释。

用法:
    python3 scripts/canslim/ha_rotation_sim.py            # 500 只样本
    python3 scripts/canslim/ha_rotation_sim.py --full     # 全市场
    python3 scripts/canslim/ha_rotation_sim.py --smoke    # 100 只

输出: results/factor_mining/ha_rotation_sim.json
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
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.canslim.ha_unified_adapter import (  # noqa: E402
    TOP_N,
    build_holdings_map,
    build_panel,
    load_hot_days,
)
from uniquant.hands.backtest.unified_matching_engine import (  # noqa: E402
    UnifiedMatchingEngine,
)

OUT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "ha_rotation_sim.json"
ENGINE_PARAMS = {
    "commission_rate": 0.0003,
    "stamp_duty_rate": 0.0005,
    "slippage_rate": 0.0010,
    "min_commission": 5.0,
}


class _Slot:
    """单个持久仓位单元: code=None 表示空仓 (现金)。"""

    __slots__ = ("code", "shares", "cash", "buy_date", "cost")

    def __init__(self, cash: float):
        self.code: str | None = None
        self.shares: float = 0.0
        self.cash: float = cash
        self.buy_date = None
        self.cost: float = 0.0

    @property
    def invested(self) -> bool:
        return self.code is not None and self.shares > 0


def _day_vec(pivot: pd.DataFrame, dt: pd.Timestamp, names: list[str]) -> np.ndarray:
    """按 name 顺序取 pivot 在 dt 的单行值 (缺列/缺日 → NaN)。"""
    row = pivot.loc[dt] if dt in pivot.index else None
    out = np.full(len(names), np.nan)
    if row is None:
        return out
    for i, c in enumerate(names):
        if c in row.index:
            out[i] = row[c]
    return out


class SlotRotationSim:
    """30 个持久仓位单元的滚动轮换执行 (生产匹配成交)。"""

    def __init__(self, n_slots: int = TOP_N, initial_capital: float = 1e7,
                 engine_params: dict | None = None):
        self.n_slots = n_slots
        self._init = initial_capital
        ep = dict(ENGINE_PARAMS)
        if engine_params:
            ep.update(engine_params)
        self.matcher = UnifiedMatchingEngine(**ep)
        self.engine_params = ep

    def run(self, closes: pd.DataFrame, pre_closes: pd.DataFrame,
            volumes: pd.DataFrame, adv: pd.DataFrame,
            hmap: dict, calendar: list,
            nav_capture: bool = False) -> dict:
        """closes/pre_closes/volumes/adv: date×code pivot。返回统计 + 诊断。"""
        slots = [_Slot(self._init / self.n_slots) for _ in range(self.n_slots)]
        by_code: dict[str, _Slot] = {}
        portfolio_cash = 0.0

        nav_series: list[float] = []
        date_idx: list[pd.Timestamp] = []
        in_market: list[bool] = []
        d_sold = d_bought = 0.0
        n_rejects = 0
        n_rebalances = 0

        for dts in calendar:
            dt = pd.Timestamp(dts)
            target = set(hmap.get(dt, set()))
            current = {s.code for s in slots if s.invested}

            if target != current:
                n_rebalances += 1
                removed = sorted(current - target)
                added = sorted(target - current)

                # ── 1) 卖出退出名 (生产 fill_sell) ──
                if removed:
                    px_r = _day_vec(closes, dt, removed)
                    keep = [c for i, c in enumerate(removed)
                            if c in closes.columns and np.isfinite(px_r[i])
                            and px_r[i] > 0]
                    # 缺收盘价的退出名无法成交: 按成本清零退出
                    for c in removed:
                        if c not in keep and c in by_code:
                            _reset_slot(by_code[c])
                            del by_code[c]
                    if keep:
                        fr = self.matcher.fill_sell(
                            prices=_day_vec(closes, dt, keep),
                            shares_requested=np.array([by_code[c].shares for c in keep]),
                            positions_held=np.array([by_code[c].shares for c in keep]),
                            position_costs=np.array([by_code[c].cost for c in keep]),
                            pre_closes=_day_vec(pre_closes, dt, keep),
                            symbols=np.array(keep, dtype=object),
                            timestamps=np.array([dt] * len(keep), dtype=object),
                            buy_dates=np.array([by_code[c].buy_date for c in keep],
                                               dtype=object),
                            volumes=_day_vec(volumes, dt, keep),
                            avg_daily_volumes=_day_vec(adv, dt, keep),
                        )
                        n_rejects += int(fr.rejected_mask.sum())
                        for i, c in enumerate(keep):
                            sl = by_code[c]
                            if fr.rejected_mask[i] or fr.executed_shares[i] <= 0:
                                continue
                            proceeds = (fr.executed_shares[i] * fr.exec_prices[i]
                                        - fr.commissions[i] - fr.stamp_duties[i]
                                        - fr.transfer_fees[i])
                            sl.cash += float(proceeds)
                            d_sold += float(fr.executed_shares[i] * fr.exec_prices[i])
                            _reset_slot(sl)
                            del by_code[c]

                # ── 2) 买入新进名: 分配给空置 slot (NAV 复利投入) ──
                free = [s for s in slots if not s.invested]
                for c in added:
                    if not free or c not in closes.columns:
                        continue
                    px_vec = _day_vec(closes, dt, [c])
                    if not np.isfinite(px_vec[0]) or px_vec[0] <= 0:
                        continue
                    sl = free.pop(0)
                    budget = sl.cash
                    if not np.isfinite(budget) or budget <= 0:
                        continue
                    shares = int(budget / px_vec[0] / 100) * 100
                    if shares <= 0:
                        continue
                    fb = self.matcher.fill_buy(
                        prices=px_vec,
                        shares_requested=np.array([shares]),
                        cash_available=np.array([budget]),
                        pre_closes=_day_vec(pre_closes, dt, [c]),
                        symbols=np.array([c], dtype=object),
                        timestamps=np.array([dt], dtype=object),
                        volumes=_day_vec(volumes, dt, [c]),
                        avg_daily_volumes=_day_vec(adv, dt, [c]),
                    )
                    if fb.rejected_mask[0] or fb.executed_shares[0] <= 0:
                        n_rejects += 1
                        continue
                    ex_sh = float(fb.executed_shares[0])
                    ex_px = float(fb.exec_prices[0])
                    sl.code = c
                    sl.shares = ex_sh
                    sl.cash -= (ex_sh * ex_px + fb.commissions[0]
                                + fb.transfer_fees[0])
                    sl.buy_date = dt
                    sl.cost = float(ex_px)
                    by_code[c] = sl
                    d_bought += ex_sh * ex_px

            # ── 每日 NAV 标记 ──
            row = closes.loc[dt] if dt in closes.index else None
            nav = portfolio_cash
            for s in slots:
                nav += s.cash
                if s.invested and row is not None:
                    px = row.get(s.code, np.nan)
                    nav += s.shares * (float(px) if np.isfinite(px) else s.cost)
            nav_series.append(float(nav))
            date_idx.append(dt)
            in_market.append(any(s.invested for s in slots))

        nav = pd.Series(nav_series, index=pd.DatetimeIndex(date_idx))
        rets = nav.pct_change().dropna()
        eq = nav / nav.iloc[0]
        mdd = float(((eq / eq.cummax()) - 1.0).min())
        yearly = len(rets) / 244.0
        ann = float(eq.iloc[-1] ** (1.0 / max(yearly, 1e-9)) - 1.0)
        sharpe = float(rets.mean() / max(rets.std(), 1e-12) * np.sqrt(244))
        peak_nav = float(nav.max())

        out = {
            "ann_return": round(ann, 4),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 4),
            "total_return": round(eq.iloc[-1] - 1.0, 4),
            "in_market_frac": round(float(np.mean(in_market)), 4),
            "n_rebalances": n_rebalances,
            "total_turnover_onesided": round((d_sold + d_bought) / 2.0 / peak_nav, 4),
            "peak_nav": round(peak_nav, 2),
            "end_nav": round(float(nav.iloc[-1]), 2),
            "n_rejected_fills": n_rejects,
            "n_slots": self.n_slots,
            "engine_params": self.engine_params,
        }
        if nav_capture:
            out["_nav"] = nav
        return out


def _reset_slot(sl: _Slot) -> None:
    sl.shares = 0.0
    sl.code = None
    sl.buy_date = None
    sl.cost = 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="H-A 30-slot 轮换回测 (生产成交)")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--zero-cost", action="store_true",
                    help="诊断: 归零滑点/佣金/印花税 (保留市场冲击), 隔离执行摩擦 (非生产)")
    ap.add_argument("--floor", type=float, default=None,
                    help="成交额地板 (元); 2e7 = P10 F2 地板变体")
    args = ap.parse_args(argv)
    t0 = time.time()

    n_sample = args.sample if args.sample is not None else (100 if args.smoke else 500)
    panel = build_panel(None if args.full else n_sample)
    hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
    print(f"[1/3] 面板 {panel['code'].nunique()} 只 × {panel['date'].nunique()} 天")

    hmap = build_holdings_map(panel, hot, amount_floor=args.floor)
    tag = f" (floor={args.floor:,.0f})" if args.floor else ""
    print(f"[2/3] 持仓映射{tag}: {sum(1 for v in hmap.values() if v)} 天有持仓")

    closes = panel.pivot_table(index="date", columns="code", values="close",
                               aggfunc="last").sort_index()
    pre = closes.shift(1)
    volumes = panel.pivot_table(index="date", columns="code", values="volume",
                                aggfunc="last").sort_index()
    adv = volumes.rolling(20, min_periods=10).mean().shift(1)

    params = None
    if args.zero_cost:
        # 匹配引擎要求 0<rate<1: 用 1e-9 近似零成本 (诊断隔离执行摩擦)
        params = {"commission_rate": 1e-9, "stamp_duty_rate": 1e-9,
                  "slippage_rate": 1e-9, "min_commission": 0.0}
        print("  [诊断] 零成本/零滑点模式 (1e-9)")
    result = SlotRotationSim(engine_params=params).run(
        closes, pre, volumes, adv, hmap, list(closes.index))
    result["elapsed_sec"] = round(time.time() - t0, 1)
    result["universe"] = "full" if args.full else f"sample{n_sample}"

    print(f"[3/3] 30-slot 轮换 (生产成交): "
          f"年化 {result['ann_return']:+.2%} 夏普 {result['sharpe']:.2f} "
          f"回撤 {result['max_drawdown']:.2%} 在场 {result['in_market_frac']:.0%} "
          f"调仓 {result['n_rebalances']} 次")
    if args.full:
        print("      参照 P10 FULL: +9.98%/0.93/−22.2% | 样本口径 P8: "
              "+15.82%/1.33/−12.9%")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())