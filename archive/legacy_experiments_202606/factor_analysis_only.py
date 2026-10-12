#!/usr/bin/env python3
"""
UniQuant 全量 A 股因子分析实验（轻量版）
========================================
使用通达信全量 5000+ 只股票的本地日线数据，
选择从 2012 年到 2025 年的 20 个时间窗口，
进行因子分析和交易分析，
对比沪深300指数的相对收益。

优化策略：
- 仅使用因子分析（跳过 LPPL）
- 每个窗口随机抽样 300 只股票
- 批量处理减少 I/O
"""

import sys
import warnings
import time
import gc
import os
import random
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore")


@dataclass
class WindowResult:
    """窗口结果"""
    window_name: str
    window_start: str
    window_end: str
    total_analyzed: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    avg_rsi: float
    avg_momentum: float
    trades: int
    win_rate: float
    avg_return: float
    max_return: float
    min_return: float


def run_factor_analysis():
    """执行因子分析实验"""
    print("=" * 80)
    print("UniQuant 全量 A 股因子分析实验")
    print("=" * 80)
    print(f"实验开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ============================================================
    # 第一阶段：数据准备
    # ============================================================
    print("━" * 60)
    print("第一阶段：数据准备")
    print("━" * 60)

    data_dir = Path("data/lake/quotes/daily")

    # 获取所有可用股票
    all_files = [f for f in os.listdir(data_dir) if f.endswith('.parquet')]
    all_symbols = [f.replace('.parquet', '') for f in all_files if f != '000300.SH.parquet']
    print(f"总股票数: {len(all_symbols)}")

    # 20个时间窗口
    time_windows = [
        ("2012-01-01", "2012-06-30", "2012H1"),
        ("2012-07-01", "2012-12-31", "2012H2"),
        ("2013-01-01", "2013-06-30", "2013H1"),
        ("2013-07-01", "2013-12-31", "2013H2"),
        ("2014-01-01", "2014-06-30", "2014H1"),
        ("2014-07-01", "2014-12-31", "2014H2"),
        ("2015-01-01", "2015-06-30", "2015H1"),
        ("2015-07-01", "2015-12-31", "2015H2"),
        ("2016-01-01", "2016-06-30", "2016H1"),
        ("2016-07-01", "2016-12-31", "2016H2"),
        ("2017-01-01", "2017-06-30", "2017H1"),
        ("2017-07-01", "2017-12-31", "2017H2"),
        ("2018-01-01", "2018-06-30", "2018H1"),
        ("2018-07-01", "2018-12-31", "2018H2"),
        ("2019-01-01", "2019-06-30", "2019H1"),
        ("2019-07-01", "2019-12-31", "2019H2"),
        ("2020-01-01", "2020-06-30", "2020H1"),
        ("2020-07-01", "2020-12-31", "2020H2"),
        ("2021-01-01", "2021-06-30", "2021H1"),
        ("2021-07-01", "2021-12-31", "2021H2"),
        ("2022-01-01", "2022-06-30", "2022H1"),
        ("2022-07-01", "2022-12-31", "2022H2"),
        ("2023-01-01", "2023-06-30", "2023H1"),
        ("2023-07-01", "2023-12-31", "2023H2"),
        ("2024-01-01", "2024-06-30", "2024H1"),
        ("2024-07-01", "2024-12-31", "2024H2"),
        ("2025-01-01", "2025-05-21", "2025H1"),
    ]

    print(f"时间窗口: {len(time_windows)} 个")
    print("每个窗口随机抽样 300 只股票")
    print()

    # ============================================================
    # 第二阶段：批量因子分析
    # ============================================================
    print("━" * 60)
    print("第二阶段：批量因子分析")
    print("━" * 60)

    # 回测参数
    commission_rate = 0.0003
    stamp_duty_rate = 0.0005
    slippage_rate = 0.0005
    transfer_fee_rate = 0.00001
    hold_days = 20

    window_results: List[WindowResult] = []

    for window_start, window_end, window_name in time_windows:
        print(f"\n【{window_name}】{window_start} ~ {window_end}")
        print("-" * 40)

        start_time = time.time()

        # 随机抽样300只股票
        sample_symbols = random.sample(all_symbols, min(300, len(all_symbols)))

        buy_signals = 0
        sell_signals = 0
        hold_signals = 0
        rsis = []
        momentums = []
        returns = []

        for symbol in sample_symbols:
            try:
                # 加载数据
                file_path = data_dir / f"{symbol}.parquet"
                if not file_path.exists():
                    continue

                df = pd.read_parquet(file_path)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)

                # 过滤日期范围
                df_window = df[df['date'] <= pd.Timestamp(window_end)]
                if len(df_window) < 60:
                    continue

                # 取最近60天用于分析
                df_analysis = df_window.tail(60).copy().reset_index(drop=True)

                # 计算因子
                close = df_analysis['close'].values

                # RSI
                delta = pd.Series(close).diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi = 100 - (100 / (1 + rs))
                rsi_val = float(rsi.iloc[-1]) if not rsi.empty and not np.isnan(rsi.iloc[-1]) else 50.0

                # 动量
                if len(close) >= 20:
                    momentum = (close[-1] - close[-20]) / close[-20]
                else:
                    momentum = 0.0

                rsis.append(rsi_val)
                momentums.append(momentum)

                # 生成信号
                score = 0.0
                if rsi_val > 70:
                    score -= 0.3
                elif rsi_val < 30:
                    score += 0.3

                if momentum > 0.1:
                    score -= 0.2
                elif momentum < -0.1:
                    score += 0.2

                if score > 0.2:
                    signal = 'BUY'
                elif score < -0.2:
                    signal = 'SELL'
                else:
                    signal = 'HOLD'

                if signal == 'BUY':
                    buy_signals += 1

                    # 回测
                    buy_idx = df_window[df_window['date'] >= pd.Timestamp(window_start)].index
                    if len(buy_idx) > 0:
                        buy_idx = buy_idx[0]
                        if buy_idx + hold_days < len(df_window):
                            entry_price = float(df_window.iloc[buy_idx]['close'])
                            exit_price = float(df_window.iloc[buy_idx + hold_days]['close'])

                            entry_cost = entry_price * (commission_rate + slippage_rate + transfer_fee_rate)
                            exit_cost = exit_price * (commission_rate + stamp_duty_rate + slippage_rate + transfer_fee_rate)

                            gross_return = (exit_price - entry_price) / entry_price
                            net_return = gross_return - (entry_cost + exit_cost) / entry_price
                            returns.append(net_return)

                elif signal == 'SELL':
                    sell_signals += 1
                else:
                    hold_signals += 1

            except:
                continue

        # 计算窗口统计
        total_analyzed = buy_signals + sell_signals + hold_signals
        elapsed = time.time() - start_time

        trades = len(returns)
        win_rate = len([r for r in returns if r > 0]) / trades if trades > 0 else 0
        avg_return = np.mean(returns) if returns else 0
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0

        print(f"  分析完成: {total_analyzed} 只股票, 耗时 {elapsed:.1f}s")
        print(f"  信号分布: BUY={buy_signals}, SELL={sell_signals}, HOLD={hold_signals}")
        print(f"  回测结果: {trades} 笔交易, 胜率 {win_rate*100:.1f}%, 平均收益 {avg_return*100:.2f}%")

        window_results.append(WindowResult(
            window_name=window_name,
            window_start=window_start,
            window_end=window_end,
            total_analyzed=total_analyzed,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            avg_rsi=np.mean(rsis) if rsis else 50,
            avg_momentum=np.mean(momentums) if momentums else 0,
            trades=trades,
            win_rate=win_rate,
            avg_return=avg_return,
            max_return=max_return,
            min_return=min_return
        ))

        gc.collect()

    # ============================================================
    # 第三阶段：计算基准收益
    # ============================================================
    print("\n" + "━" * 60)
    print("第三阶段：计算沪深300基准收益")
    print("━" * 60)

    index_file = data_dir / "000300.SH.parquet"
    hs300 = pd.read_parquet(index_file)
    hs300['date'] = pd.to_datetime(hs300['date'])
    hs300 = hs300.sort_values('date').reset_index(drop=True)
    print(f"沪深300指数: {len(hs300)} 条记录")

    benchmark_returns = []
    for window_start, window_end, window_name in time_windows:
        window_data = hs300[(hs300['date'] >= pd.Timestamp(window_start)) & 
                           (hs300['date'] <= pd.Timestamp(window_end))]
        if len(window_data) > 1:
            start_price = float(window_data.iloc[0]['close'])
            end_price = float(window_data.iloc[-1]['close'])
            ret = (end_price - start_price) / start_price
            benchmark_returns.append({
                'window': window_name,
                'start': window_start,
                'end': window_end,
                'return_pct': ret
            })

    # ============================================================
    # 第四阶段：生成报告
    # ============================================================
    print("\n" + "━" * 60)
    print("第四阶段：生成分析报告")
    print("━" * 60)

    report = generate_report(window_results, benchmark_returns)

    report_path = project_root / "docs" / "FULL_A_STOCK_FACTOR_ANALYSIS_2012_2025.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_report(window_results: List[WindowResult], benchmark_returns: List[Dict]) -> str:
    """生成报告"""

    lines = []
    lines.append("# UniQuant 全量 A 股因子分析报告 (2012-2025)")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 实验类型: 全量 5000+ 只 A 股因子共振分析")
    lines.append("> 时间窗口: 2012H1 ~ 2025H1（27个窗口）")
    lines.append("> 抽样策略: 每个窗口随机抽样 300 只股票")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 信号统计
    lines.append("## 一、信号统计总览")
    lines.append("")
    lines.append("| 窗口 | 分析数 | BUY | SELL | HOLD | BUY占比 | 平均RSI | 平均动量 |")
    lines.append("|------|--------|-----|------|------|---------|---------|----------|")

    for r in window_results:
        buy_pct = r.buy_signals / r.total_analyzed * 100 if r.total_analyzed > 0 else 0
        lines.append(f"| {r.window_name} | {r.total_analyzed} | {r.buy_signals} | {r.sell_signals} | {r.hold_signals} | {buy_pct:.1f}% | {r.avg_rsi:.1f} | {r.avg_momentum*100:.1f}% |")

    lines.append("")

    # 2. 总体统计
    total_analyzed = sum(r.total_analyzed for r in window_results)
    total_buy = sum(r.buy_signals for r in window_results)
    total_sell = sum(r.sell_signals for r in window_results)
    total_hold = sum(r.hold_signals for r in window_results)

    lines.append("### 1.2 总体信号统计")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总分析次数 | {total_analyzed:,} |")
    lines.append(f"| BUY 信号 | {total_buy:,} ({total_buy/total_analyzed*100:.1f}%) |")
    lines.append(f"| SELL 信号 | {total_sell:,} ({total_sell/total_analyzed*100:.1f}%) |")
    lines.append(f"| HOLD 信号 | {total_hold:,} ({total_hold/total_analyzed*100:.1f}%) |")
    lines.append("")

    # 3. 回测结果
    lines.append("## 二、回测结果")
    lines.append("")
    lines.append("| 窗口 | 交易数 | 胜率 | 平均收益 | 最大收益 | 最大亏损 |")
    lines.append("|------|--------|------|----------|----------|----------|")

    all_trades = 0

    for r in window_results:
        lines.append(f"| {r.window_name} | {r.trades} | {r.win_rate*100:.1f}% | {r.avg_return*100:.2f}% | {r.max_return*100:.2f}% | {r.min_return*100:.2f}% |")
        all_trades += r.trades

    lines.append("")

    # 4. 与基准对比
    lines.append("## 三、与沪深300基准对比")
    lines.append("")

    if benchmark_returns:
        lines.append("| 窗口 | 策略收益 | 基准收益 | 超额收益 |")
        lines.append("|------|----------|----------|----------|")

        for i, bm in enumerate(benchmark_returns):
            bm_return = bm['return_pct']

            if i < len(window_results) and window_results[i].trades > 0:
                strategy_return = window_results[i].avg_return
                excess = strategy_return - bm_return
                lines.append(f"| {bm['window']} | {strategy_return*100:.2f}% | {bm_return*100:.2f}% | {excess*100:.2f}% |")
            else:
                lines.append(f"| {bm['window']} | - | {bm_return*100:.2f}% | - |")

        lines.append("")

        # 累计收益
        lines.append("### 3.2 累计收益对比")
        lines.append("")
        lines.append("| 窗口 | 策略累计 | 基准累计 | 超额累计 |")
        lines.append("|------|----------|----------|----------|")

        strategy_cumulative = 1.0
        benchmark_cumulative = 1.0

        for i, bm in enumerate(benchmark_returns):
            bm_return = bm['return_pct']

            if i < len(window_results) and window_results[i].trades > 0:
                strategy_return = window_results[i].avg_return
                strategy_cumulative *= (1 + strategy_return)
                benchmark_cumulative *= (1 + bm_return)
                excess_cumulative = strategy_cumulative - benchmark_cumulative
                lines.append(f"| {bm['window']} | {strategy_cumulative:.4f} | {benchmark_cumulative:.4f} | {excess_cumulative:.4f} |")

        lines.append("")

    # 5. 结论
    lines.append("## 四、结论")
    lines.append("")

    win_windows = len([r for r in window_results if r.trades > 0 and r.win_rate > 0.5])
    total_windows = len([r for r in window_results if r.trades > 0])

    lines.append(f"1. **窗口胜率**: {win_windows}/{total_windows} 个窗口实现正胜率")
    lines.append(f"2. **总交易数**: {all_trades:,} 笔")
    lines.append(f"3. **BUY信号占比**: {total_buy/total_analyzed*100:.1f}%")
    lines.append("")

    lines.append("### 局限性")
    lines.append("")
    lines.append("1. 未使用复权因子数据")
    lines.append("2. 回测使用简化模型")
    lines.append("3. 每个窗口仅抽样 300 只股票")
    lines.append("4. 未集成 LPPL 和 Wyckoff 引擎")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 UniQuant 投研系统自动生成*")

    return "\n".join(lines)


if __name__ == "__main__":
    run_factor_analysis()
