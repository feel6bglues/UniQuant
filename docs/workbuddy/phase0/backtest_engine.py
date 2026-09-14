# -*- coding: utf-8 -*-
"""backtest_engine.py — 统一回测引擎 (T0b)
- 调仓日历: 月度(动量/低波) / 季度(5/9/11 核心)
- 持仓快照 -> 换手率 (卖出比例)
- 成本模型: 单边成本 c, 每期成本拖累 = 2*c*换手率
- 绩效: 年化/波动/夏普/回撤/Calmar/净值
- 基线断言: assert_baseline 复现已知结果防重构回归
"""
import numpy as np

RF = 0.02

def run_backtest(score_fn, months, ret_m, topn=30, rebal_every="month", cost=0.0, rebal_months=None):
    """score_fn(code, m) 用 m 之前的因子(禁当月价); 收益取当月.
    rebal_every='month': 每月调仓当月持有
    rebal_every='quarter': 仅 5/9/11 调仓, 持有到下个调仓点
    rebal_every='annual': 仅 5 月调仓 (年频口径)
    rebal_months: 自定义调仓月列表 (覆盖 rebal_every)
    返回 dict: returns(ndarray) / holdings(list) / turnover(ndarray) / perf(dict)
    """
    if rebal_months is not None:
        pass
    elif rebal_every == "quarter":
        rebal_months = [m for m in months if m % 100 in (5, 9, 11)]
    elif rebal_every == "annual":
        # 首月建仓(因子用再上年报) + 每年5月切换 -> 复现 run_hs300_ws2 逐月持仓口径
        rebal_months = [months[0]] + [m for m in months if m % 100 == 5]
    else:
        rebal_months = months

    n = len(months)
    returns = np.full(n, np.nan)
    holdings = [None] * n
    turnover = np.full(n, np.nan)
    prev_top = None

    def month_ret(m_idx, top):
        rs = [ret_m.loc[months[m_idx], x] for x in top if not np.isnan(ret_m.loc[months[m_idx], x])]
        return np.mean(rs) if rs else np.nan

    for i, m in enumerate(months):
        if i == 0:
            # 首月: 若为调仓月则建仓(不记收益, 无前月价)
            if m in rebal_months:
                sc = {c: score_fn(c, m) for c in ret_m.columns}
                sc = {c: v for c, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
                if len(sc) >= topn:
                    prev_top = sorted(sc, key=sc.get, reverse=True)[:topn]
                    holdings[0] = prev_top
            continue
        if rebal_every in ("quarter", "annual") and m not in rebal_months:
            # 非调仓月: 沿用上次持仓, 且收益需算(由上期调仓点持有逻辑处理)
            continue
        sc = {c: score_fn(c, m) for c in ret_m.columns}
        sc = {c: v for c, v in sc.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if len(sc) < topn:
            continue
        top = sorted(sc, key=sc.get, reverse=True)[:topn]
        holdings[i] = top
        # 换手率 (相对上次调仓持仓)
        if prev_top is not None:
            inter = len(set(top) & set(prev_top))
            turnover[i] = 1.0 - inter / max(len(top), 1)
        prev_top = top
        # 持有到下个调仓点 (季/年频) 或 当月 (月频)
        if rebal_every in ("quarter", "annual"):
            nxt = next((mm for mm in rebal_months if mm > m), months[-1])
            seg = [mm for mm in months if m < mm < nxt]  # 不含 nxt: 下个调仓月收益由该次调仓决定
            for j, mm in enumerate(seg):
                idx = months.index(mm)
                r = month_ret(idx, top)
                if not np.isnan(r):
                    tc = turnover[i] * cost * 2 if j == 0 else 0.0  # 成本只在调仓月扣
                    returns[idx] = r - tc
        else:
            r = month_ret(i, top)
            if not np.isnan(r):
                returns[i] = r - (turnover[i] * cost * 2 if not np.isnan(turnover[i]) else 0.0)

    # 非调仓月 (季/年频) 收益: 用持仓填充 (调仓点失败则后续不填, 复现原版尾部NaN口径)
    if rebal_every in ("quarter", "annual"):
        last_top = None
        pending = False
        for i, m in enumerate(months):
            if m in rebal_months:
                if holdings[i] is not None:
                    last_top = holdings[i]
                    pending = True
                else:
                    pending = False
            if pending and np.isnan(returns[i]) and i > 0 and last_top is not None:
                r = month_ret(i, last_top)
                if not np.isnan(r):
                    returns[i] = r

    perf_res = perf(returns)
    return {"returns": returns, "holdings": holdings, "turnover": turnover, "perf": perf_res}

def perf(r):
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 12:
        return {"年化收益": np.nan, "年化波动": np.nan, "夏普": np.nan,
                "最大回撤": np.nan, "Calmar": np.nan, "期末净值": np.nan, "月数": len(r)}
    nav = np.cumprod(1 + r)
    yrs = len(r) / 12
    ar = nav[-1] ** (1 / yrs) - 1
    av = r.std() * np.sqrt(12)
    shp = (ar - RF) / av if av > 0 else np.nan
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    return {"年化收益": ar, "年化波动": av, "夏普": shp, "最大回撤": dd,
            "Calmar": ar / abs(dd) if dd < 0 else np.nan, "期末净值": nav[-1], "月数": len(r)}

def assert_baseline(actual, expected, name, tol=0.01):
    """基线断言: |actual-expected| <= tol, 失败即抛出(防重构回归)"""
    assert abs(actual - expected) <= tol, \
        f"[基线回归失败] {name}: 实际 {actual:.4f} != 期望 {expected:.4f} (±{tol})"
    print(f"  ✓ 基线通过: {name} = {actual:.4f} (±{tol})")
