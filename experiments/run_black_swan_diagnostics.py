"""
Stage 3: LPPL & Wyckoff 极端行情诊断
======================================
针对 A 股两个教科书级极值点进行非线性模型检验:

  大顶测试 (LPPL):  2020-11 ~ 2021-03 茅指数大崩盘
  大底测试 (Wyckoff): 2023-11 ~ 2024-03 微盘股流动性危机大底
"""

import logging
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("black_swan")


def fmt_d(v) -> str:
    """格式化日期"""
    if isinstance(v, np.datetime64):
        return str(v)[:10]
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def fetch_index_data(symbol: str = "000300", start: str = "20180101",
                     end: str = "20250331") -> pd.DataFrame:
    """通过 akshare 获取指数日线数据"""
    import akshare as ak
    asym = f"sh{symbol}" if symbol[:1] == "0" else f"sz{symbol}"
    df = ak.stock_zh_index_daily(symbol=asym)
    if df is None or df.empty:
        raise RuntimeError(f"获取指数 {symbol} 数据失败")
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("date", "日期"): col_map[c] = "date"
        elif cl in ("open", "开盘"): col_map[c] = "open"
        elif cl in ("high", "最高"): col_map[c] = "high"
        elif cl in ("low", "最低"): col_map[c] = "low"
        elif cl in ("close", "收盘"): col_map[c] = "close"
        elif cl in ("volume", "成交量"): col_map[c] = "volume"
        elif cl in ("amount", "成交额"): col_map[c] = "amount"
    df.rename(columns=col_map, inplace=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start[:4]+"-"+start[4:6]+"-"+start[6:8])) &
            (df["date"] <= pd.Timestamp(end[:4]+"-"+end[4:6]+"-"+end[6:8]))].copy()
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"  [Data] {symbol}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 诊断 1: LPPL — 2021 茅指数大崩盘
# ═══════════════════════════════════════════════════════════════════════════

def diagnose_lppl_top(df: pd.DataFrame):
    """对 2020-11 ~ 2021-03 顶部区间运行 LPPL 日级滚动扫描"""
    from uniquant.brain.lppl.engine import (process_single_day_ensemble, LPPLConfig)

    print("\n" + "=" * 72)
    print("  诊断 1: LPPL → 2021 茅指数大崩盘 (2020-11 ~ 2021-03)")
    print("=" * 72)

    # 目标: 2021-02-18 茅指数大顶
    peak_date = pd.Timestamp("2021-02-18")
    scan_start = pd.Timestamp("2020-11-01")
    scan_end = pd.Timestamp("2021-03-31")

    df_scan = df[(df["date"] >= scan_start) & (df["date"] <= scan_end)].copy()
    close_arr = df["close"].values
    dates_arr = df["date"].values

    config = LPPLConfig(
        window_range=list(range(60, 160, 20)),
        optimizer="lbfgsb",
        maxiter=50,
        r2_threshold=0.3,
        consensus_threshold=0.3,
        n_workers=1,
    )

    days_to_peak = df_scan["date"].apply(lambda d: (peak_date - d).days)
    print(f"  \n  Peak Date: {fmt_d(peak_date)}")
    print(f"  Scan range: {fmt_d(scan_start)} to {fmt_d(scan_end)} ({len(df_scan)} days)")
    print(f"  \n  {'Date':<14} {'Idx':>5} {'D→Peak':>7} {'CrashD':>7} {'Consens':>7} "
          f"{'AvgR²':>7} {'Signal':>7} {'Alert?':>6}")
    print("  " + "-" * 66)

    scan_step = 3  # 每 N 天扫描一次以加速
    timeline = []
    for idx, (_, row) in enumerate(df_scan.iterrows()):
        if idx % scan_step != 0:
            continue
        date = row["date"]
        idx = df.index[df["date"] == date].tolist()
        if not idx:
            continue
        i = idx[0]
        if i < max(config.window_range) + 5:
            continue

        try:
            res = process_single_day_ensemble(
                close_prices=close_arr,
                idx=i,
                window_range=config.window_range,
                min_r2=config.r2_threshold,
                consensus_threshold=config.consensus_threshold,
                config=config,
            )
        except Exception:
            res = None

        if res is not None:
            days_to_p = days_to_peak.loc[row.name]
            is_danger = res["predicted_crash_days"] < 10 and res["consensus_rate"] > 0.4
            alert = "⚠️ DANGER" if is_danger else ("🔶 WARN" if res["consensus_rate"] > 0.3 else "")
            timeline.append({
                "date": fmt_d(date), "days_to_peak": int(days_to_p),
                "crash_days": round(res["predicted_crash_days"], 1),
                "consensus": round(res["consensus_rate"], 3),
                "avg_r2": round(res["avg_r2"], 3),
                "signal": round(res["signal_strength"], 3),
                "voting": f"{res['valid_windows']}/{len(config.window_range)}",
                "is_danger": is_danger,
            })

    # 输出关键节点
    if timeline:
        # 只输出信号较强的日期
        strong = [t for t in timeline if t["consensus"] > 0.25 or t["is_danger"]]
        for t in (strong if len(strong) > 10 else timeline):
            alert = "⚠️" if t["is_danger"] else ("🔶" if t["consensus"] > 0.3 else "  ")
            print(f"  {t['date']:<14} {t['days_to_peak']:>5} {t['days_to_peak']:>7} "
                  f"{t['crash_days']:>7} {t['consensus']:>7.3f} {t['avg_r2']:>7.3f} "
                  f"{t['signal']:>7.3f} {alert:>6}")

        # 统计摘要
        n_strong = sum(1 for t in timeline if t["is_danger"])
        n_warn = sum(1 for t in timeline if t["consensus"] > 0.3)
        print(f"\n  诊断摘要:")
        print(f"    扫描天数: {len(timeline)}")
        print(f"    发出预警天数: {n_warn} ({n_warn/len(timeline)*100:.1f}%)")
        print(f"    危险信号天数: {n_strong} ({n_strong/len(timeline)*100:.1f}%)")
        # 首次预警时间
        triggered = [t for t in timeline if t["consensus"] > 0.3]
        if triggered:
            first = triggered[0]
            print(f"    首次预警: {first['date']} (距离大顶 {first['days_to_peak']} 天)")
            if n_strong > 0:
                first_danger = [t for t in triggered if t["is_danger"]][0]
                print(f"    首次危险信号: {first_danger['date']} (距离大顶 {first_danger['days_to_peak']} 天)")
    else:
        print("  (无有效 LPPL 拟合结果)")

    return timeline


# ═══════════════════════════════════════════════════════════════════════════
# 诊断 2: Wyckoff — 2024 微盘股流动性危机大底
# ═══════════════════════════════════════════════════════════════════════════

def diagnose_wyckoff_bottom(df: pd.DataFrame):
    """对 2023-11 ~ 2024-03 底部区间每日运行 Wyckoff 分析"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    print("\n" + "=" * 72)
    print("  诊断 2: Wyckoff → 2024 微盘股流动性危机大底 (2023-11 ~ 2024-03)")
    print("=" * 72)

    # 目标: 2024-02-05 微盘股流动性危机极致恐慌底
    bottom_date = pd.Timestamp("2024-02-05")
    scan_start = pd.Timestamp("2023-11-01")
    scan_end = pd.Timestamp("2024-03-31")

    df_scan = df[(df["date"] >= scan_start) & (df["date"] <= scan_end)].copy()

    print(f"  \n  Bottom Date: {fmt_d(bottom_date)}")
    print(f"  Scan range: {fmt_d(scan_start)} to {fmt_d(scan_end)} ({len(df_scan)} days)")
    print(f"  \n  {'Date':<14} {'Phase':<16} {'Signal':<16} {'Conf.':>5} "
          f"{'Spring?':>7} {'UTAD?':>6} {'Direction':<10} {'R/R':>5}")
    print("  " + "-" * 85)

    engine = WyckoffEngine(lookback_days=250, weekly_lookback=360, monthly_lookback=240)
    timeline = []

    for _, row in df_scan.iterrows():
        date = row["date"]
        idx = df.index[df["date"] == date].tolist()
        if not idx:
            continue
        i = idx[0]
        lookback_start = max(0, i - 250)
        df_window = df.iloc[lookback_start:i + 1].copy()

        if len(df_window) < 60:
            continue

        try:
            report = engine.analyze(df_window, symbol="000300.SH", period="日线")
        except Exception:
            continue

        phase = report.structure.phase.value if hasattr(report.structure.phase, "value") else str(report.structure.phase)
        signal_type = report.signal.signal_type
        conf = report.trading_plan.confidence.value if hasattr(report.trading_plan.confidence, "value") else "?"
        direction = report.trading_plan.direction
        spring = "✓" if "spring" in signal_type.lower() else "✗"
        utad = "✓" if "utad" in signal_type.lower() else "✗"
        rr = report.risk_reward.reward_risk_ratio if report.risk_reward and report.risk_reward.reward_risk_ratio else 0.0

        days_to_bottom = (bottom_date - date).days

        timeline.append({
            "date": fmt_d(date),
            "days_to_bottom": days_to_bottom,
            "phase": phase,
            "signal": signal_type,
            "confidence": conf,
            "spring": spring,
            "utad": utad,
            "direction": direction,
            "rr": rr,
        })

    # 输出结果
    print(f"  扫描天数: {len(timeline)}")
    print()

    # 分组显示: 阶段变化前后
    prev_phase = ""
    for t in timeline:
        phase_changed = t["phase"] != prev_phase
        prefix = ">>> " if phase_changed else "    "
        print(f"  {prefix}{t['date']:<14} {t['phase']:<16} {t['signal']:<16} "
              f"{t['confidence']:>5} {t['spring']:>7} {t['utad']:>6} "
              f"{t['direction']:<10} {t['rr']:>5.1f}")
        prev_phase = t["phase"]

    # 诊断摘要
    spring_dates = [t for t in timeline if t["spring"] == "✓"]
    accumulation_phases = [t for t in timeline if "accumulation" in t["phase"].lower()]
    long_signals = [t for t in timeline if "long" in t["direction"].lower()]

    print(f"\n  诊断摘要:")
    print(f"    Spring 信号: {len(spring_dates)} 个")
    if spring_dates:
        print(f"    首次 Spring: {spring_dates[0]['date']} (距大底 {spring_dates[0]['days_to_bottom']} 天)")
    print(f"    吸筹阶段天数: {len(accumulation_phases)} 天")
    print(f"    做多信号天数: {len(long_signals)} 天")

    return timeline


# ═══════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 72)
    print("  Stage 3: 非线性模型极端行情诊断")
    print("  LPPL (泡沫崩溃预警) + Wyckoff (吸筹大底识别)")
    print("=" * 72)

    # 统一获取沪深 300 数据 (需要够长的历史窗口)
    df = fetch_index_data("000300", start="20180101", end="20250331")

    # 诊断 1: LPPL 顶部预警
    lppl_timeline = diagnose_lppl_top(df)

    # 诊断 2: Wyckoff 底部识别
    wyckoff_timeline = diagnose_wyckoff_bottom(df)

    # 汇总
    print("\n" + "=" * 72)
    print("  诊断完成")
    print("=" * 72)

    if lppl_timeline:
        n_warn = sum(1 for t in lppl_timeline if t["consensus"] > 0.3)
        n_danger = sum(1 for t in lppl_timeline if t["is_danger"])
        triggered = [t for t in lppl_timeline if t["consensus"] > 0.3]
        first_warn = triggered[0]["date"] if triggered else "N/A"
        first_warn_days = triggered[0]["days_to_peak"] if triggered else "?"
        print(f"  LPPL: {n_warn}预警/{n_danger}危险, 首次预警={first_warn} (T-{first_warn_days}d)")

    if wyckoff_timeline:
        springs = [t for t in wyckoff_timeline if t["spring"] == "✓"]
        aps = sum(1 for t in wyckoff_timeline if "accumulation" in t["phase"].lower())
        print(f"  Wyckoff: {aps}天吸筹期, {len(springs)}个Spring信号")
        if springs:
            s0 = springs[0]
            print(f"           首次Spring={s0['date']} (T-{abs(s0['days_to_bottom'])}d)")


if __name__ == "__main__":
    main()
