#!/usr/bin/env python3
"""V7: V-shape 检测覆盖验证

假设: VShapedReversalDetector 能有效识别市场指数中的
      V 型反转事件（恐慌底/狂热顶），这些事件是传统 Wyckoff 
      信号失效的关键期。

方法:
  1. 加载 CSI 300 (399300.SZ) 历史数据 (2005-2026)
  2. 运行 VShapedReversalDetector 扫描 V 型反转
  3. 统计检测到的 V 型事件数量、类型分布、时间分布
  4. 与 phase6 中 WSO sell 信号的误报时间进行交叉验证
"""

import sys
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.wyckoff_multitf.v_shape_detector import (
    VShapedReversalDetector, VShapeResult
)

DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
PHASE6 = OUTPUT / "phase6_combined_results.json"

CSI300_SYMBOL = "399300.SZ"


def main():
    print("=" * 60)
    print("  V7: V-shape 检测覆盖验证")
    print("=" * 60)

    # ── Load CSI 300 data ──
    fp = DATA_LAKE / f"{CSI300_SYMBOL}.parquet"
    df = pd.read_parquet(fp)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"\n  CSI 300 数据: {len(df)} 条, "
          f"{df['date'].min().date()} ~ {df['date'].max().date()}")

    # ── Run V-shape detection ──
    print("\n" + "=" * 60)
    print("  1. V-shape 检测结果")
    print("=" * 60)
    detector = VShapedReversalDetector(
        decline_threshold=0.15,
        recovery_ratio=0.50,
        recovery_window=10,
        lookback=120,
    )
    results = detector.detect(df)
    print(f"  检测到 {len(results)} 个 V-shape 事件\n")

    # Classify
    v_bottoms = [r for r in results if r.v_type == "v_bottom"]
    v_tops = [r for r in results if r.v_type == "v_top"]
    in_progress = [r for r in results if r.in_progress]
    print(f"  V-bottom (恐慌底): {len(v_bottoms)}")
    print(f"  V-top (狂热顶):   {len(v_tops)}")
    print(f"  In-progress:      {len(in_progress)}")

    # ── 2. Severity distribution ──
    print("\n" + "=" * 60)
    print("  2. 严重程度分布")
    print("=" * 60)
    for severity in ["high", "medium", "low"]:
        n = sum(1 for r in results if r.severity == severity)
        print(f"  {severity:>10}: {n}")

    # ── 3. Statistical summary ──
    print("\n" + "=" * 60)
    print("  3. V-shape 统计特征")
    print("=" * 60)
    if v_bottoms:
        declines = np.array([r.decline_pct for r in v_bottoms])
        recoveries = np.array([r.recovery_pct for r in v_bottoms])
        decl_days = np.array([r.decline_days for r in v_bottoms])
        rec_days = np.array([r.recovery_days for r in v_bottoms])
        print(f"  V-bottom:")
        print(f"    跌幅: 均值={np.mean(declines):.1f}% 最大={np.max(declines):.1f}%")
        print(f"    反弹恢复度: 均值={np.mean(recoveries):.1f}%")
        print(f"    下跌天数: 均值={np.mean(decl_days):.0f} 中位数={np.median(decl_days):.0f}")
        print(f"    反弹天数: 均值={np.mean(rec_days):.0f} 中位数={np.median(rec_days):.0f}")

    if v_tops:
        rallies = np.array([r.decline_pct for r in v_tops])
        retraces = np.array([r.recovery_pct for r in v_tops])
        rally_days = np.array([r.decline_days for r in v_tops])
        retrace_days = np.array([r.recovery_days for r in v_tops])
        print(f"  V-top:")
        print(f"    涨幅: 均值={np.mean(rallies):.1f}% 最大={np.max(rallies):.1f}%")
        print(f"    回撤恢复度: 均值={np.mean(retraces):.1f}%")
        print(f"    上涨天数: 均值={np.mean(rally_days):.0f} 中位数={np.median(rally_days):.0f}")
        print(f"    下跌天数: 均值={np.mean(retrace_days):.0f} 中位数={np.median(retrace_days):.0f}")

    # ── 4. Chronological distribution (by year) ──
    print("\n" + "=" * 60)
    print("  4. 按年份分布")
    print("=" * 60)
    by_year = defaultdict(int)
    for r in results:
        year = r.date[:4]
        by_year[year] += 1
    for year in sorted(by_year.keys()):
        print(f"  {year}: {by_year[year]} 个 V-shape 事件")

    # ── 5. Cross-reference with phase6 sell signals ──
    print("\n" + "=" * 60)
    print("  5. 与 phase6 sell 信号交叉验证")
    print("=" * 60)
    if PHASE6.exists():
        with open(PHASE6) as f:
            p6 = json.load(f)
        p6_rows = p6["data"]

        # Collect V-shape date ranges (with buffer)
        v_windows = []
        for r in results:
            try:
                t = pd.Timestamp(r.date)
                v_windows.append((t - pd.Timedelta(days=5), t + pd.Timedelta(days=15)))
            except Exception:
                pass

        in_v_window = 0
        sell_during_v = 0
        sell_after_positive = 0
        total_sells = 0
        f6_sell_normal = []
        f6_sell_v = []

        for ob in p6_rows:
            if ob.get("wso_sig") != "sell":
                continue
            total_sells += 1
            try:
                ob_date = pd.Timestamp(ob.get("c", ""))
            except Exception:
                continue
            f6 = ob.get("f6", 0)
            in_v = any(start <= ob_date <= end for start, end in v_windows)
            if in_v:
                in_v_window += 1
                sell_during_v += 1
                f6_sell_v.append(f6)
            else:
                f6_sell_normal.append(f6)

        f6_sell_normal = np.array(f6_sell_normal)
        f6_sell_v = np.array(f6_sell_v)
        print(f"  WSO sell 信号总数: {total_sells}")
        print(f"  V 窗内 sell 信号: {sell_during_v} ({sell_during_v/total_sells:.1%})")
        print(f"  V 窗外 sell 信号: {total_sells - sell_during_v}")
        if len(f6_sell_normal) > 5 and len(f6_sell_v) > 5:
            from scipy.stats import ttest_ind
            print(f"  V 窗内 sell f6 = {np.mean(f6_sell_v):>+.2f}±{np.std(f6_sell_v):.2f}")
            print(f"  V 窗外 sell f6 = {np.mean(f6_sell_normal):>+.2f}±{np.std(f6_sell_normal):.2f}")
            t_v, p_v = ttest_ind(f6_sell_v, f6_sell_normal, equal_var=False)
            print(f"  Welch t-test: t = {t_v:+.3f}, p = {p_v:.4f}")

    print("\n" + "=" * 60)
    print("  V7 验证结论")
    print("=" * 60)
    print(f"""
  V-shape 检测 (CSI 300, 2005-2026):
    - 总计 {len(results)} 个 V-shape 事件
    - {len(v_bottoms)} 个恐慌底 + {len(v_tops)} 个狂热顶
    - V 窗内 sell 信号 f6 vs V 窗外 sell 信号 f6

  V-shape 是 Wyckoff 信号的补充过滤器:
    - V 型顶: 传统 sell 信号失效区
    - V 型底: 传统 buy 信号失效区
""")

    out_path = OUTPUT / "v7_vshape_results.json"
    summary = {
        "n_v_events": len(results),
        "n_bottoms": len(v_bottoms),
        "n_tops": len(v_tops),
        "total_sells": total_sells if PHASE6.exists() else 0,
        "sell_in_v_window": sell_during_v if PHASE6.exists() else 0,
    }
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
