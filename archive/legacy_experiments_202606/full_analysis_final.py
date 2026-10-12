#!/usr/bin/env python3
"""
UniQuant 全量 A 股多模型共振分析实验（最终版）
==============================================
使用通达信全量 5000+ 只股票的本地日线数据，
选择从 2012 年到 2025 年的 5 个时间窗口，
进行全量 LPPL + 因子分析，
对比沪深300指数的相对收益。

优化策略：
- 降低数据要求（60天即可）
- 批量处理
- 详细进度输出
"""

import sys
import os
import time
import gc
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

import warnings
warnings.filterwarnings('ignore')


@dataclass
class StockResult:
    """股票分析结果"""
    symbol: str
    window_name: str
    lppl_direction: str
    lppl_confidence: float
    lppl_days_to_tc: float
    rsi_14: float
    momentum_20d: float
    signal: str
    signal_strength: float


@dataclass
class TradeResult:
    """交易结果"""
    symbol: str
    window_name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float


def run_analysis():
    """执行分析"""
    print("=" * 80)
    print("UniQuant 全量 A 股多模型共振分析实验")
    print("=" * 80)
    print(f"实验开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 数据目录
    data_dir = Path('data/lake/quotes/daily')

    # 获取所有可用股票
    all_files = [f for f in os.listdir(data_dir) if f.endswith('.parquet')]
    all_symbols = [f.replace('.parquet', '') for f in all_files if f != '000300.SH.parquet']
    print(f"总股票数: {len(all_symbols)}")

    # 5个时间窗口
    time_windows = [
        ('2012-01-01', '2013-12-31', '2012-2013'),
        ('2014-01-01', '2016-12-31', '2014-2016'),
        ('2017-01-01', '2019-12-31', '2017-2019'),
        ('2020-01-01', '2022-12-31', '2020-2022'),
        ('2023-01-01', '2025-05-21', '2023-2025'),
    ]

    # 初始化分析器
    from uniquant.brain.lppl.calculator import LPPLCalculator
    from uniquant.brain.factors.custom_factors import (
        compute_momentum_20d,
        compute_rsi_14,
    )

    calc = LPPLCalculator()

    # 存储结果
    all_results: List[StockResult] = []
    all_trades: List[TradeResult] = []

    # 回测参数
    commission_rate = 0.0003
    stamp_duty_rate = 0.0005
    slippage_rate = 0.0005
    transfer_fee_rate = 0.00001
    hold_days = 20

    # 统计
    window_stats = []

    for window_start, window_end, window_name in time_windows:
        print(f"\n【{window_name}】{window_start} ~ {window_end}")
        print("-" * 40)

        start_time = time.time()

        analyzed = 0
        buy_signals = 0
        sell_signals = 0
        hold_signals = 0
        trades = []
        confidences = []
        rsis = []
        momentums = []

        for symbol in all_symbols:
            file_path = data_dir / f'{symbol}.parquet'
            if not file_path.exists():
                continue

            try:
                df = pd.read_parquet(file_path)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)

                # 过滤日期范围
                df_window = df[df['date'] <= pd.Timestamp(window_end)]
                if len(df_window) < 60:  # 降低要求到60天
                    continue

                # 取最近60天用于分析
                df_analysis = df_window.tail(60).copy().reset_index(drop=True)
                close_prices = df_analysis['close'].values

                # LPPL 分析
                lppl_result = calc.fit_single_window(close_prices)

                # 因子计算
                momentum = compute_momentum_20d(df_analysis)
                rsi = compute_rsi_14(df_analysis)

                momentum_val = float(momentum.iloc[-1]) if not momentum.empty and not pd.isna(momentum.iloc[-1]) else 0.0
                rsi_val = float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0

                # 生成信号
                score = 0.0
                lppl_direction = 'neutral'
                lppl_confidence = 0.0
                lppl_days_to_tc = 999

                if lppl_result:
                    lppl_direction = lppl_result.get('direction', 'neutral')
                    lppl_confidence = lppl_result.get('confidence', 0.0)
                    lppl_days_to_tc = lppl_result.get('days_to_tc', 999)

                    if lppl_direction == 'bubble' and lppl_days_to_tc < 20:
                        score -= 0.4 * lppl_confidence
                    elif lppl_direction == 'negative_bubble' and lppl_days_to_tc < 20:
                        score += 0.4 * lppl_confidence

                if rsi_val > 70:
                    score -= 0.2
                elif rsi_val < 30:
                    score += 0.2

                if momentum_val > 0.1:
                    score -= 0.15
                elif momentum_val < -0.1:
                    score += 0.15

                if score > 0.2:
                    signal = 'BUY'
                elif score < -0.2:
                    signal = 'SELL'
                else:
                    signal = 'HOLD'

                analyzed += 1
                confidences.append(lppl_confidence)
                rsis.append(rsi_val)
                momentums.append(momentum_val)

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

                            trade = TradeResult(
                                symbol=symbol,
                                window_name=window_name,
                                entry_date=str(df_window.iloc[buy_idx]['date'].date()),
                                exit_date=str(df_window.iloc[buy_idx + hold_days]['date'].date()),
                                entry_price=entry_price,
                                exit_price=exit_price,
                                return_pct=net_return
                            )
                            trades.append(trade)
                            all_trades.append(trade)

                elif signal == 'SELL':
                    sell_signals += 1
                else:
                    hold_signals += 1

                # 保存结果
                all_results.append(StockResult(
                    symbol=symbol,
                    window_name=window_name,
                    lppl_direction=lppl_direction,
                    lppl_confidence=lppl_confidence,
                    lppl_days_to_tc=lppl_days_to_tc,
                    rsi_14=rsi_val,
                    momentum_20d=momentum_val,
                    signal=signal,
                    signal_strength=abs(score)
                ))

            except Exception as e:
                continue

        # 计算窗口统计
        elapsed = time.time() - start_time
        trade_returns = [t.return_pct for t in trades]
        win_rate = len([r for r in trade_returns if r > 0]) / len(trades) if trades else 0
        avg_return = np.mean(trade_returns) if trades else 0

        print(f"  分析完成: {analyzed} 只股票, 耗时 {elapsed:.1f}s")
        print(f"  信号分布: BUY={buy_signals}, SELL={sell_signals}, HOLD={hold_signals}")
        if trades:
            print(f"  回测结果: {len(trades)} 笔交易, 胜率 {win_rate*100:.1f}%, 平均收益 {avg_return*100:.2f}%")

        window_stats.append({
            'window': window_name,
            'start': window_start,
            'end': window_end,
            'analyzed': analyzed,
            'buy': buy_signals,
            'sell': sell_signals,
            'hold': hold_signals,
            'trades': len(trades),
            'win_rate': win_rate,
            'avg_return': avg_return,
            'avg_confidence': np.mean(confidences) if confidences else 0,
            'avg_rsi': np.mean(rsis) if rsis else 50,
            'avg_momentum': np.mean(momentums) if momentums else 0,
        })

        gc.collect()

    # 计算基准收益
    print("\n" + "=" * 60)
    print("计算沪深300基准收益")
    print("=" * 60)

    index_file = data_dir / '000300.SH.parquet'
    hs300 = pd.read_parquet(index_file)
    hs300['date'] = pd.to_datetime(hs300['date'])
    hs300 = hs300.sort_values('date').reset_index(drop=True)

    benchmark_returns = []
    for ws in window_stats:
        window_data = hs300[(hs300['date'] >= pd.Timestamp(ws['start'])) & 
                           (hs300['date'] <= pd.Timestamp(ws['end']))]
        if len(window_data) > 1:
            start_price = float(window_data.iloc[0]['close'])
            end_price = float(window_data.iloc[-1]['close'])
            ret = (end_price - start_price) / start_price
            benchmark_returns.append({'window': ws['window'], 'return_pct': ret})
            print(f"  {ws['window']}: {ret*100:.2f}%")

    # 生成报告
    print("\n" + "=" * 60)
    print("生成分析报告")
    print("=" * 60)

    report = generate_report(window_stats, benchmark_returns, all_results, all_trades)

    report_path = Path('docs/FULL_MULTI_MODEL_ANALYSIS_2012_2025.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_report(window_stats, benchmark_returns, all_results, all_trades):
    """生成报告"""

    lines = []
    lines.append("# UniQuant 全量 A 股多模型共振分析报告 (2012-2025)")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 实验类型: 全量 A 股 LPPL + 因子共振分析")
    lines.append("> 时间窗口: 2012-2025年（5个窗口）")
    lines.append("> 数据规模: 全量股票，不抽样")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 总体统计
    lines.append("## 一、总体统计")
    lines.append("")

    total_analyzed = sum(w['analyzed'] for w in window_stats)
    total_buy = sum(w['buy'] for w in window_stats)
    total_sell = sum(w['sell'] for w in window_stats)
    total_hold = sum(w['hold'] for w in window_stats)
    total_trades = sum(w['trades'] for w in window_stats)

    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总分析次数 | {total_analyzed:,} |")
    lines.append(f"| BUY 信号 | {total_buy:,} ({total_buy/total_analyzed*100:.1f}%) |")
    lines.append(f"| SELL 信号 | {total_sell:,} ({total_sell/total_analyzed*100:.1f}%) |")
    lines.append(f"| HOLD 信号 | {total_hold:,} ({total_hold/total_analyzed*100:.1f}%) |")
    lines.append(f"| 总交易数 | {total_trades:,} |")
    lines.append("")

    # LPPL 信号分布
    lppl_bubble = len([r for r in all_results if r.lppl_direction == 'bubble'])
    lppl_negative = len([r for r in all_results if r.lppl_direction == 'negative_bubble'])
    lppl_neutral = len([r for r in all_results if r.lppl_direction == 'neutral'])

    lines.append("### LPPL 信号分布")
    lines.append("")
    lines.append("| 方向 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    lines.append(f"| 正向泡沫 | {lppl_bubble:,} | {lppl_bubble/total_analyzed*100:.1f}% |")
    lines.append(f"| 负向泡沫 | {lppl_negative:,} | {lppl_negative/total_analyzed*100:.1f}% |")
    lines.append(f"| 中性 | {lppl_neutral:,} | {lppl_neutral/total_analyzed*100:.1f}% |")
    lines.append("")

    # 2. 各窗口表现
    lines.append("## 二、各窗口表现")
    lines.append("")
    lines.append("| 窗口 | 分析数 | BUY | SELL | HOLD | 交易数 | 胜率 | 平均收益 | 平均RSI | 平均动量 |")
    lines.append("|------|--------|-----|------|------|--------|------|----------|---------|----------|")

    for w in window_stats:
        lines.append(f"| {w['window']} | {w['analyzed']:,} | {w['buy']:,} | {w['sell']:,} | {w['hold']:,} | {w['trades']:,} | {w['win_rate']*100:.1f}% | {w['avg_return']*100:.2f}% | {w['avg_rsi']:.1f} | {w['avg_momentum']*100:.1f}% |")

    lines.append("")

    # 3. 与基准对比
    lines.append("## 三、与沪深300基准对比")
    lines.append("")
    lines.append("| 窗口 | 策略收益 | 基准收益 | 超额收益 |")
    lines.append("|------|----------|----------|----------|")

    strategy_cumulative = 1.0
    benchmark_cumulative = 1.0

    for i, bm in enumerate(benchmark_returns):
        bm_return = bm['return_pct']

        if i < len(window_stats) and window_stats[i]['trades'] > 0:
            strategy_return = window_stats[i]['avg_return']
            excess = strategy_return - bm_return
            strategy_cumulative *= (1 + strategy_return)
            benchmark_cumulative *= (1 + bm_return)
            lines.append(f"| {bm['window']} | {strategy_return*100:.2f}% | {bm_return*100:.2f}% | {excess*100:.2f}% |")
        else:
            benchmark_cumulative *= (1 + bm_return)
            lines.append(f"| {bm['window']} | - | {bm_return*100:.2f}% | - |")

    lines.append("")
    lines.append(f"**累计收益**: 策略 {strategy_cumulative:.4f}, 基准 {benchmark_cumulative:.4f}")
    lines.append("")

    # 4. 收益分布
    if all_trades:
        lines.append("## 四、收益分布分析")
        lines.append("")

        returns = [t.return_pct for t in all_trades]
        returns_array = np.array(returns)

        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 样本数 | {len(returns_array):,} |")
        lines.append(f"| 均值 | {np.mean(returns_array)*100:.2f}% |")
        lines.append(f"| 中位数 | {np.median(returns_array)*100:.2f}% |")
        lines.append(f"| 标准差 | {np.std(returns_array)*100:.2f}% |")
        lines.append(f"| 最大值 | {np.max(returns_array)*100:.2f}% |")
        lines.append(f"| 最小值 | {np.min(returns_array)*100:.2f}% |")
        lines.append(f"| 5%分位数 | {np.percentile(returns_array, 5)*100:.2f}% |")
        lines.append(f"| 95%分位数 | {np.percentile(returns_array, 95)*100:.2f}% |")
        lines.append("")

        # 收益分布
        lines.append("### 收益分布")
        lines.append("")
        lines.append("| 收益区间 | 数量 | 占比 |")
        lines.append("|----------|------|------|")

        bins = [(-100, -20), (-20, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 20), (20, 100)]
        for low, high in bins:
            count = len([r for r in returns_array if low <= r*100 < high])
            pct = count / len(returns_array) * 100
            lines.append(f"| [{low}%, {high}%) | {count:,} | {pct:.1f}% |")

        lines.append("")

    # 5. Top 交易
    if all_trades:
        lines.append("## 五、最佳与最差交易")
        lines.append("")

        top_trades = sorted(all_trades, key=lambda x: x.return_pct, reverse=True)[:20]
        worst_trades = sorted(all_trades, key=lambda x: x.return_pct)[:20]

        lines.append("### 最佳交易 Top 10")
        lines.append("")
        lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 收益 |")
        lines.append("|---|------|------|--------|--------|------|")

        for i, t in enumerate(top_trades[:10], 1):
            lines.append(f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | {t.return_pct*100:.2f}% |")

        lines.append("")
        lines.append("### 最差交易 Top 10")
        lines.append("")
        lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 收益 |")
        lines.append("|---|------|------|--------|--------|------|")

        for i, t in enumerate(worst_trades[:10], 1):
            lines.append(f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | {t.return_pct*100:.2f}% |")

        lines.append("")

    # 6. 结论
    lines.append("## 六、结论")
    lines.append("")

    if all_trades:
        returns = [t.return_pct for t in all_trades]
        win_rate = len([r for r in returns if r > 0]) / len(returns)
        avg_return = np.mean(returns)

        lines.append(f"1. **总交易数**: {len(all_trades):,} 笔")
        lines.append(f"2. **胜率**: {win_rate*100:.1f}%")
        lines.append(f"3. **平均收益**: {avg_return*100:.2f}%（20日持仓期）")
        lines.append(f"4. **LPPL 正向泡沫信号占比**: {lppl_bubble/total_analyzed*100:.1f}%")
        lines.append(f"5. **LPPL 负向泡沫信号占比**: {lppl_negative/total_analyzed*100:.1f}%")
        lines.append("")

    lines.append("### 局限性")
    lines.append("")
    lines.append("1. 未使用复权因子数据")
    lines.append("2. 回测使用简化模型")
    lines.append("3. 未考虑分红、配股等公司行为")
    lines.append("4. Wyckoff 引擎未集成")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 UniQuant 多模型共振投研系统自动生成*")

    return "\n".join(lines)


if __name__ == "__main__":
    run_analysis()
