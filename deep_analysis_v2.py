#!/usr/bin/env python3
"""
UniQuant 全量 A 股深度分析实验（优化版）
========================================
使用通达信全量 5000+ 只股票的本地日线数据，
选择从 2012 年到 2025 年的 20 个时间窗口，
进行全量 LPPL + 因子深度分析，
对比沪深300指数的相对收益，
分析夏普比率、算法正确性、策略组合。

优化策略：
- 20个时间窗口（每半年一个）
- 批量处理
- 详细进度输出
"""

import sys
import os
import time
import gc
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

import warnings
warnings.filterwarnings('ignore')


@dataclass
class WindowStats:
    """窗口统计"""
    window_name: str
    window_start: str
    window_end: str
    analyzed: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    trades: int
    win_rate: float
    avg_return: float
    median_return: float
    std_return: float
    sharpe_ratio: float
    max_drawdown: float
    avg_confidence: float
    avg_rsi: float
    avg_momentum: float


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
    max_drawdown: float


def run_deep_analysis():
    """执行深度分析实验"""
    print("=" * 80)
    print("UniQuant 全量 A 股深度分析实验（20窗口）")
    print("=" * 80)
    print(f"实验开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 数据目录
    data_dir = Path('data/lake/quotes/daily')

    # 获取所有可用股票
    all_files = [f for f in os.listdir(data_dir) if f.endswith('.parquet')]
    all_symbols = [f.replace('.parquet', '') for f in all_files if f != '000300.SH.parquet']
    print(f"总股票数: {len(all_symbols)}")

    # 20个时间窗口（每半年一个）
    time_windows = [
        ('2012-01-01', '2012-06-30', '2012H1'),
        ('2012-07-01', '2012-12-31', '2012H2'),
        ('2013-01-01', '2013-06-30', '2013H1'),
        ('2013-07-01', '2013-12-31', '2013H2'),
        ('2014-01-01', '2014-06-30', '2014H1'),
        ('2014-07-01', '2014-12-31', '2014H2'),
        ('2015-01-01', '2015-06-30', '2015H1'),
        ('2015-07-01', '2015-12-31', '2015H2'),
        ('2016-01-01', '2016-06-30', '2016H1'),
        ('2016-07-01', '2016-12-31', '2016H2'),
        ('2017-01-01', '2017-06-30', '2017H1'),
        ('2017-07-01', '2017-12-31', '2017H2'),
        ('2018-01-01', '2018-06-30', '2018H1'),
        ('2018-07-01', '2018-12-31', '2018H2'),
        ('2019-01-01', '2019-06-30', '2019H1'),
        ('2019-07-01', '2019-12-31', '2019H2'),
        ('2020-01-01', '2020-06-30', '2020H1'),
        ('2020-07-01', '2020-12-31', '2020H2'),
        ('2021-01-01', '2021-06-30', '2021H1'),
        ('2021-07-01', '2021-12-31', '2021H2'),
        ('2022-01-01', '2022-06-30', '2022H1'),
        ('2022-07-01', '2022-12-31', '2022H2'),
        ('2023-01-01', '2023-06-30', '2023H1'),
        ('2023-07-01', '2023-12-31', '2023H2'),
        ('2024-01-01', '2024-06-30', '2024H1'),
        ('2024-07-01', '2024-12-31', '2024H2'),
        ('2025-01-01', '2025-05-21', '2025H1'),
    ]

    print(f"时间窗口: {len(time_windows)} 个")
    print()

    # ============================================================
    # 初始化分析器
    # ============================================================
    from uniquant.brain.lppl.calculator import LPPLCalculator
    from uniquant.brain.factors.custom_factors import (
        compute_momentum_20d,
        compute_rsi_14,
        compute_ma_ratio_5_20,
        compute_volatility_20d
    )

    calc = LPPLCalculator()

    # 回测参数
    commission_rate = 0.0003
    stamp_duty_rate = 0.0005
    slippage_rate = 0.0005
    transfer_fee_rate = 0.00001
    hold_days = 20
    risk_free_rate = 0.02

    # 存储结果
    all_trades: List[TradeResult] = []
    window_stats_list: List[WindowStats] = []

    # LPPL 参数统计
    lppl_tc_values = []
    lppl_m_values = []
    lppl_valid_count = 0
    lppl_total_count = 0

    # ============================================================
    # 全量分析
    # ============================================================
    print("━" * 60)
    print("全量 LPPL + 因子分析")
    print("━" * 60)

    total_start_time = time.time()

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

                df_window = df[df['date'] <= pd.Timestamp(window_end)]
                if len(df_window) < 60:
                    continue

                df_analysis = df_window.tail(60).copy().reset_index(drop=True)
                close_prices = df_analysis['close'].values

                # LPPL 分析
                lppl_result = calc.fit_single_window(close_prices)
                if lppl_result is None:
                    continue

                # 统计 LPPL 参数
                lppl_total_count += 1
                params = lppl_result.get('params', [0]*7)
                if len(params) == 7:
                    tc, m, w, a, b, c, phi = params
                    lppl_tc_values.append(lppl_result.get('days_to_tc', 0))
                    lppl_m_values.append(m)

                    # 参数合理性检查
                    if 0.1 < m < 0.9 and 6 < w < 13:
                        lppl_valid_count += 1

                # 因子计算
                momentum = compute_momentum_20d(df_analysis)
                rsi = compute_rsi_14(df_analysis)
                volatility = compute_volatility_20d(df_analysis)
                ma_ratio = compute_ma_ratio_5_20(df_analysis)

                momentum_val = float(momentum.iloc[-1]) if not momentum.empty and not pd.isna(momentum.iloc[-1]) else 0.0
                rsi_val = float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0
                volatility_val = float(volatility.iloc[-1]) if not volatility.empty and not pd.isna(volatility.iloc[-1]) else 0.0
                ma_ratio_val = float(ma_ratio.iloc[-1]) if not ma_ratio.empty and not pd.isna(ma_ratio.iloc[-1]) else 0.0

                # 生成信号
                score = 0.0
                lppl_direction = lppl_result.get('direction', 'neutral')
                lppl_confidence = lppl_result.get('confidence', 0.0)
                lppl_days_to_tc = lppl_result.get('days_to_tc', 999)

                # LPPL 信号权重 35%
                if lppl_direction == 'bubble' and lppl_days_to_tc < 20:
                    score -= 0.35 * lppl_confidence
                elif lppl_direction == 'negative_bubble' and lppl_days_to_tc < 20:
                    score += 0.35 * lppl_confidence

                # 动量信号权重 20%
                if momentum_val > 0.1:
                    score -= 0.20
                elif momentum_val < -0.1:
                    score += 0.20

                # RSI 信号权重 20%
                if rsi_val > 70:
                    score -= 0.20
                elif rsi_val < 30:
                    score += 0.20

                # 均线比率信号权重 15%
                if ma_ratio_val > 0.05:
                    score -= 0.15
                elif ma_ratio_val < -0.05:
                    score += 0.15

                # 波动率信号权重 10%
                if volatility_val > 0.5:
                    score -= 0.10 * 0.5
                elif volatility_val < 0.2:
                    score += 0.10 * 0.5

                # 生成信号
                if score > 0.15:
                    signal = 'BUY'
                elif score < -0.15:
                    signal = 'SELL'
                else:
                    signal = 'HOLD'

                confidence = min(abs(score) / 0.5, 1.0)

                analyzed += 1
                confidences.append(confidence)
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

                            # 计算最大回撤
                            period_data = df_window.iloc[buy_idx:buy_idx + hold_days + 1]
                            peak = entry_price
                            max_dd = 0.0
                            for _, row in period_data.iterrows():
                                price = float(row['close'])
                                if price > peak:
                                    peak = price
                                dd = (peak - price) / peak
                                if dd > max_dd:
                                    max_dd = dd

                            trade = TradeResult(
                                symbol=symbol,
                                window_name=window_name,
                                entry_date=str(df_window.iloc[buy_idx]['date'].date()),
                                exit_date=str(df_window.iloc[buy_idx + hold_days]['date'].date()),
                                entry_price=entry_price,
                                exit_price=exit_price,
                                return_pct=net_return,
                                max_drawdown=max_dd
                            )
                            trades.append(trade)
                            all_trades.append(trade)

                elif signal == 'SELL':
                    sell_signals += 1
                else:
                    hold_signals += 1

            except:
                continue

        # 计算窗口统计
        elapsed = time.time() - start_time
        trade_returns = [t.return_pct for t in trades]
        win_rate = len([r for r in trade_returns if r > 0]) / len(trades) if trades else 0
        avg_return = np.mean(trade_returns) if trades else 0
        median_return = np.median(trade_returns) if trades else 0
        std_return = np.std(trade_returns) if trades else 0
        max_dd = max([t.max_drawdown for t in trades]) if trades else 0

        # 计算夏普比率
        if trade_returns and std_return > 0:
            rf_daily = risk_free_rate / 252 * hold_days
            sharpe = (avg_return - rf_daily) / std_return * np.sqrt(252 / hold_days)
        else:
            sharpe = 0.0

        print(f"  分析完成: {analyzed} 只股票, 耗时 {elapsed:.1f}s")
        print(f"  信号分布: BUY={buy_signals}, SELL={sell_signals}, HOLD={hold_signals}")
        if trades:
            print(f"  回测结果: {len(trades)} 笔交易")
            print(f"  胜率: {win_rate*100:.1f}%, 平均收益: {avg_return*100:.2f}%, 夏普: {sharpe:.2f}")

        window_stats_list.append(WindowStats(
            window_name=window_name,
            window_start=window_start,
            window_end=window_end,
            analyzed=analyzed,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            trades=len(trades),
            win_rate=win_rate,
            avg_return=avg_return,
            median_return=median_return,
            std_return=std_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            avg_confidence=np.mean(confidences) if confidences else 0,
            avg_rsi=np.mean(rsis) if rsis else 50,
            avg_momentum=np.mean(momentums) if momentums else 0
        ))

        gc.collect()

    total_elapsed = time.time() - total_start_time
    print(f"\n总耗时: {total_elapsed:.1f}s")

    # ============================================================
    # 计算基准收益
    # ============================================================
    print("\n" + "=" * 60)
    print("计算沪深300基准收益")
    print("=" * 60)

    index_file = data_dir / '000300.SH.parquet'
    hs300 = pd.read_parquet(index_file)
    hs300['date'] = pd.to_datetime(hs300['date'])
    hs300 = hs300.sort_values('date').reset_index(drop=True)

    benchmark_returns = []
    for ws in window_stats_list:
        window_data = hs300[(hs300['date'] >= pd.Timestamp(ws.window_start)) & 
                           (hs300['date'] <= pd.Timestamp(ws.window_end))]
        if len(window_data) > 1:
            start_price = float(window_data.iloc[0]['close'])
            end_price = float(window_data.iloc[-1]['close'])
            ret = (end_price - start_price) / start_price
            benchmark_returns.append({'window': ws.window_name, 'return_pct': ret})
            print(f"  {ws.window_name}: {ret*100:.2f}%")

    # ============================================================
    # 深度分析
    # ============================================================
    print("\n" + "=" * 60)
    print("深度数据分析")
    print("=" * 60)

    # 1. LPPL 参数验证
    print("\n1. LPPL 参数正确性验证:")
    print(f"  有效参数比例: {lppl_valid_count}/{lppl_total_count} ({lppl_valid_count/lppl_total_count*100:.1f}%)")
    if lppl_tc_values:
        print(f"  tc 分布: 均值={np.mean(lppl_tc_values):.1f}, 中位数={np.median(lppl_tc_values):.1f}")
    if lppl_m_values:
        print(f"  m 分布: 均值={np.mean(lppl_m_values):.3f}, 中位数={np.median(lppl_m_values):.3f}")

    # 2. 夏普比率分析
    print("\n2. 夏普比率分析:")
    all_returns = [t.return_pct for t in all_trades]
    if all_returns:
        overall_mean = np.mean(all_returns)
        overall_std = np.std(all_returns)
        rf_daily = risk_free_rate / 252 * hold_days
        overall_sharpe = (overall_mean - rf_daily) / overall_std * np.sqrt(252 / hold_days) if overall_std > 0 else 0
        print(f"  总体夏普比率: {overall_sharpe:.2f}")

    # 3. 因子相关性分析
    print("\n3. 因子与收益相关性:")
    # 这里简化处理，基于窗口统计
    for ws in window_stats_list:
        if ws.trades > 0:
            print(f"  {ws.window_name}: RSI={ws.avg_rsi:.1f}, 动量={ws.avg_momentum*100:.1f}%")

    # ============================================================
    # 生成报告
    # ============================================================
    print("\n" + "=" * 60)
    print("生成深度分析报告")
    print("=" * 60)

    report = generate_report(
        window_stats_list, benchmark_returns, all_trades,
        lppl_valid_count, lppl_total_count,
        lppl_tc_values, lppl_m_values, overall_sharpe
    )

    report_path = Path('docs/DEEP_ANALYSIS_REPORT_2012_2025.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_report(
    window_stats, benchmark_returns, all_trades,
    lppl_valid, lppl_total, tc_values, m_values, overall_sharpe
):
    """生成报告"""

    lines = []
    lines.append("# UniQuant 全量 A 股深度分析报告 (2012-2025)")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 实验类型: 全量 A 股 LPPL + 因子深度分析")
    lines.append("> 时间窗口: 2012H1 ~ 2025H1（27个窗口）")
    lines.append("> 数据规模: 全量股票，不抽样")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 总体统计
    lines.append("## 一、总体统计")
    lines.append("")

    total_analyzed = sum(w.analyzed for w in window_stats)
    total_buy = sum(w.buy_signals for w in window_stats)
    total_sell = sum(w.sell_signals for w in window_stats)
    total_hold = sum(w.hold_signals for w in window_stats)
    total_trades = sum(w.trades for w in window_stats)

    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总分析次数 | {total_analyzed:,} |")
    lines.append(f"| BUY 信号 | {total_buy:,} ({total_buy/total_analyzed*100:.1f}%) |")
    lines.append(f"| SELL 信号 | {total_sell:,} ({total_sell/total_analyzed*100:.1f}%) |")
    lines.append(f"| HOLD 信号 | {total_hold:,} ({total_hold/total_analyzed*100:.1f}%) |")
    lines.append(f"| 总交易数 | {total_trades:,} |")
    lines.append("")

    # 2. 各窗口表现
    lines.append("## 二、各窗口表现")
    lines.append("")
    lines.append("| 窗口 | 分析数 | BUY | 交易数 | 胜率 | 平均收益 | 中位数收益 | 标准差 | 夏普比率 | 最大回撤 |")
    lines.append("|------|--------|-----|--------|------|----------|------------|--------|----------|----------|")

    for w in window_stats:
        lines.append(f"| {w.window_name} | {w.analyzed:,} | {w.buy_signals:,} | {w.trades:,} | {w.win_rate*100:.1f}% | {w.avg_return*100:.2f}% | {w.median_return*100:.2f}% | {w.std_return*100:.2f}% | {w.sharpe_ratio:.2f} | {w.max_drawdown*100:.2f}% |")

    lines.append("")

    # 3. 夏普比率分析
    lines.append("## 三、夏普比率分析")
    lines.append("")
    lines.append(f"- **总体夏普比率**: {overall_sharpe:.2f}")
    lines.append(f"- **无风险利率**: 2% (年化)")
    lines.append(f"- **持有期**: 20 个交易日")
    lines.append("")

    # 按窗口展示夏普
    lines.append("### 各窗口夏普比率")
    lines.append("")
    lines.append("| 窗口 | 夏普比率 | 评价 |")
    lines.append("|------|----------|------|")

    for w in window_stats:
        if w.trades > 0:
            if w.sharpe_ratio > 1.0:
                rating = "优秀"
            elif w.sharpe_ratio > 0.5:
                rating = "良好"
            elif w.sharpe_ratio > 0:
                rating = "一般"
            else:
                rating = "差"
            lines.append(f"| {w.window_name} | {w.sharpe_ratio:.2f} | {rating} |")

    lines.append("")

    # 4. 算法正确性验证
    lines.append("## 四、算法正确性验证")
    lines.append("")
    lines.append("### 4.1 LPPL 参数验证")
    lines.append("")
    lines.append(f"- **有效参数比例**: {lppl_valid}/{lppl_total} ({lppl_valid/lppl_total*100:.1f}%)")

    if tc_values:
        lines.append(f"- **tc 分布**: 均值={np.mean(tc_values):.1f}, 中位数={np.median(tc_values):.1f}, 标准差={np.std(tc_values):.1f}")
    if m_values:
        lines.append(f"- **m 分布**: 均值={np.mean(m_values):.3f}, 中位数={np.median(m_values):.3f}, 标准差={np.std(m_values):.3f}")
    lines.append("")

    lines.append("### 4.2 LPPL 参数合理性标准")
    lines.append("")
    lines.append("| 参数 | 合理范围 | 当前均值 | 评价 |")
    lines.append("|------|----------|----------|------|")
    if m_values:
        lines.append(f"| m (缩放指数) | 0.1 ~ 0.9 | {np.mean(m_values):.3f} | {'✓ 合理' if 0.1 < np.mean(m_values) < 0.9 else '⚠ 异常'} |")
    if tc_values:
        lines.append(f"| tc (临界时间) | > 当前时间 | {np.mean(tc_values):.1f} 天 | {'✓ 合理' if np.mean(tc_values) > 0 else '⚠ 异常'} |")
    lines.append("")

    # 5. 与基准对比
    lines.append("## 五、与沪深300基准对比")
    lines.append("")

    if benchmark_returns:
        lines.append("### 5.1 各窗口超额收益")
        lines.append("")
        lines.append("| 窗口 | 策略收益 | 基准收益 | 超额收益 | 策略夏普 |")
        lines.append("|------|----------|----------|----------|----------|")

        for i, bm in enumerate(benchmark_returns):
            bm_return = bm['return_pct']

            if i < len(window_stats) and window_stats[i].trades > 0:
                strategy_return = window_stats[i].avg_return
                excess = strategy_return - bm_return
                sharpe = window_stats[i].sharpe_ratio
                lines.append(f"| {bm['window']} | {strategy_return*100:.2f}% | {bm_return*100:.2f}% | {excess*100:.2f}% | {sharpe:.2f} |")
            else:
                lines.append(f"| {bm['window']} | - | {bm_return*100:.2f}% | - | - |")

        lines.append("")

        # 累计收益
        lines.append("### 5.2 累计收益对比")
        lines.append("")
        lines.append("| 窗口 | 策略累计 | 基准累计 | 超额累计 |")
        lines.append("|------|----------|----------|----------|")

        strategy_cumulative = 1.0
        benchmark_cumulative = 1.0

        for i, bm in enumerate(benchmark_returns):
            bm_return = bm['return_pct']

            if i < len(window_stats) and window_stats[i].trades > 0:
                strategy_return = window_stats[i].avg_return
                strategy_cumulative *= (1 + strategy_return)
                benchmark_cumulative *= (1 + bm_return)
                excess_cumulative = strategy_cumulative - benchmark_cumulative
                lines.append(f"| {bm['window']} | {strategy_cumulative:.4f} | {benchmark_cumulative:.4f} | {excess_cumulative:.4f} |")

        lines.append("")

    # 6. 收益分布分析
    lines.append("## 六、收益分布分析")
    lines.append("")

    if all_trades:
        returns = [t.return_pct for t in all_trades]
        returns_array = np.array(returns)

        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 样本数 | {len(returns_array):,} |")
        lines.append(f"| 均值 | {np.mean(returns_array)*100:.2f}% |")
        lines.append(f"| 中位数 | {np.median(returns_array)*100:.2f}% |")
        lines.append(f"| 标准差 | {np.std(returns_array)*100:.2f}% |")
        lines.append(f"| 偏度 | {float(pd.Series(returns_array).skew()):.4f} |")
        lines.append(f"| 峰度 | {float(pd.Series(returns_array).kurtosis()):.4f} |")
        lines.append(f"| 最大值 | {np.max(returns_array)*100:.2f}% |")
        lines.append(f"| 最小值 | {np.min(returns_array)*100:.2f}% |")
        lines.append(f"| 5%分位数 | {np.percentile(returns_array, 5)*100:.2f}% |")
        lines.append(f"| 25%分位数 | {np.percentile(returns_array, 25)*100:.2f}% |")
        lines.append(f"| 75%分位数 | {np.percentile(returns_array, 75)*100:.2f}% |")
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

    # 7. 最佳与最差交易
    lines.append("## 七、最佳与最差交易")
    lines.append("")

    if all_trades:
        top_trades = sorted(all_trades, key=lambda x: x.return_pct, reverse=True)[:10]
        worst_trades = sorted(all_trades, key=lambda x: x.return_pct)[:10]

        lines.append("### 最佳交易 Top 10")
        lines.append("")
        lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 收益 | 最大回撤 |")
        lines.append("|---|------|------|--------|--------|------|----------|")

        for i, t in enumerate(top_trades, 1):
            lines.append(f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | {t.return_pct*100:.2f}% | {t.max_drawdown*100:.2f}% |")

        lines.append("")
        lines.append("### 最差交易 Top 10")
        lines.append("")
        lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 收益 | 最大回撤 |")
        lines.append("|---|------|------|--------|--------|------|----------|")

        for i, t in enumerate(worst_trades, 1):
            lines.append(f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | {t.return_pct*100:.2f}% | {t.max_drawdown*100:.2f}% |")

        lines.append("")

    # 8. 结论
    lines.append("## 八、结论与建议")
    lines.append("")

    if all_trades:
        returns = [t.return_pct for t in all_trades]
        win_rate = len([r for r in returns if r > 0]) / len(returns)
        avg_return = np.mean(returns)

        lines.append("### 核心发现")
        lines.append("")
        lines.append(f"1. **信号有效性**: 在 {len(all_trades):,} 笔交易中，胜率为 {win_rate*100:.1f}%，")
        lines.append(f"   平均收益率为 {avg_return*100:.2f}%（20日持仓期）。")
        lines.append("")
        lines.append(f"2. **夏普比率**: 总体夏普比率为 {overall_sharpe:.2f}，")
        if overall_sharpe > 1.0:
            lines.append("   表现优秀（>1.0）。")
        elif overall_sharpe > 0.5:
            lines.append("   表现良好（>0.5）。")
        else:
            lines.append("   表现一般，需要优化。")
        lines.append("")
        lines.append(f"3. **LPPL 参数有效性**: {lppl_valid/lppl_total*100:.1f}% 的参数在合理范围内。")
        lines.append("")

    lines.append("### 局限性")
    lines.append("")
    lines.append("1. 未使用复权因子数据（data/fq/ 目录为空）")
    lines.append("2. 回测使用简化模型（T+1、涨跌停未完全模拟）")
    lines.append("3. 未考虑分红、配股等公司行为")
    lines.append("4. Wyckoff 引擎未集成（计算量过大）")
    lines.append("")

    lines.append("### 改进建议")
    lines.append("")
    lines.append("1. 补充复权因子数据，使用前复权价格")
    lines.append("2. 集成 Wyckoff 引擎进行多模型共振")
    lines.append("3. 引入更多因子（财务因子、另类数据因子）")
    lines.append("4. 优化信号阈值，使用 Walk-Forward 方法校准")
    lines.append("5. 实现更精确的回测引擎（考虑滑点、冲击成本）")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 UniQuant 多模型共振投研系统自动生成，基于代码事实，零推测。*")

    return "\n".join(lines)


if __name__ == "__main__":
    run_deep_analysis()
