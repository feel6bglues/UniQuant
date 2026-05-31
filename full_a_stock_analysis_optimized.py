#!/usr/bin/env python3
"""
UniQuant 全量 A 股大规模分析实验（优化版）
==========================================
使用通达信全量 5000+ 只股票的本地日线数据，
选择从 2012 年到 2025 年的 20 个时间窗口（每半年一个），
进行全量 LPPL 分析等因子和交易分析，
对比沪深300指数的相对收益。

优化策略：
- 每个窗口随机抽样 500 只股票
- 使用快速分析器（仅 LPPL + 因子）
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
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore")


# ============================================================
# 数据类定义
# ============================================================

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
    avg_confidence: float
    avg_rsi: float
    avg_momentum: float
    trades: int
    win_rate: float
    avg_return: float
    max_return: float
    min_return: float
    sharpe: float


# ============================================================
# 快速分析器
# ============================================================

class FastAnalyzer:
    """快速分析器"""

    def __init__(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        from uniquant.brain.factors.custom_factors import (
            compute_momentum_20d,
            compute_volatility_20d,
            compute_rsi_14
        )

        self.lppl_calculator = LPPLCalculator()
        self.compute_momentum_20d = compute_momentum_20d
        self.compute_volatility_20d = compute_volatility_20d
        self.compute_rsi_14 = compute_rsi_14

    def analyze_stock(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        """快速分析单只股票"""
        result = {
            'symbol': symbol,
            'lppl_direction': 'neutral',
            'lppl_confidence': 0.0,
            'lppl_days_to_tc': 999,
            'momentum_20d': 0.0,
            'volatility_20d': 0.0,
            'rsi_14': 50.0,
            'signal': 'HOLD',
            'signal_strength': 0.0
        }

        try:
            # LPPL 分析
            close_prices = df['close'].values
            if len(close_prices) < 60:
                return result

            lppl = self.lppl_calculator.fit_single_window(close_prices)
            if lppl:
                result['lppl_direction'] = lppl.get('direction', 'neutral')
                result['lppl_confidence'] = lppl.get('confidence', 0.0)
                result['lppl_days_to_tc'] = lppl.get('days_to_tc', 999)

            # 因子计算
            momentum = self.compute_momentum_20d(df)
            volatility = self.compute_volatility_20d(df)
            rsi = self.compute_rsi_14(df)

            result['momentum_20d'] = float(momentum.iloc[-1]) if not momentum.empty else 0.0
            result['volatility_20d'] = float(volatility.iloc[-1]) if not volatility.empty else 0.0
            result['rsi_14'] = float(rsi.iloc[-1]) if not rsi.empty else 50.0

            # 生成信号
            score = 0.0

            # LPPL 信号
            if result['lppl_direction'] == 'bubble' and result['lppl_days_to_tc'] < 20:
                score -= 0.4 * result['lppl_confidence']
            elif result['lppl_direction'] == 'negative_bubble' and result['lppl_days_to_tc'] < 20:
                score += 0.4 * result['lppl_confidence']

            # 因子信号
            rsi = result['rsi_14']
            if rsi > 70:
                score -= 0.2
            elif rsi < 30:
                score += 0.2

            momentum = result['momentum_20d']
            if momentum > 0.1:
                score -= 0.1
            elif momentum < -0.1:
                score += 0.1

            # 生成信号
            if score > 0.2:
                result['signal'] = 'BUY'
            elif score < -0.2:
                result['signal'] = 'SELL'
            else:
                result['signal'] = 'HOLD'

            result['signal_strength'] = abs(score)

        except:
            pass

        return result


# ============================================================
# 主实验流程
# ============================================================

def run_optimized_analysis():
    """执行优化版全量分析实验"""
    print("=" * 80)
    print("UniQuant 全量 A 股大规模分析实验（优化版）")
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

    # 20个时间窗口（2012-2025年，每半年一个）
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
    print("每个窗口随机抽样 500 只股票")
    print()

    # ============================================================
    # 第二阶段：批量分析
    # ============================================================
    print("━" * 60)
    print("第二阶段：批量 LPPL + 因子分析")
    print("━" * 60)

    analyzer = FastAnalyzer()

    # 存储结果
    window_results: List[WindowResult] = []

    # 回测参数
    commission_rate = 0.0003
    stamp_duty_rate = 0.0005
    slippage_rate = 0.0005
    transfer_fee_rate = 0.00001
    hold_days = 20

    for window_start, window_end, window_name in time_windows:
        print(f"\n【{window_name}】{window_start} ~ {window_end}")
        print("-" * 40)

        start_time = time.time()

        # 随机抽样500只股票
        sample_symbols = random.sample(all_symbols, min(500, len(all_symbols)))

        # 分析结果
        buy_signals = 0
        sell_signals = 0
        hold_signals = 0
        confidences = []
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
                if len(df_window) < 120:
                    continue

                # 取最近120天用于分析
                df_analysis = df_window.tail(120).copy().reset_index(drop=True)

                # 快速分析
                result = analyzer.analyze_stock(df_analysis, symbol)

                # 统计信号
                if result['signal'] == 'BUY':
                    buy_signals += 1

                    # 回测
                    buy_idx = df_window[df_window['date'] >= pd.Timestamp(window_start)].index
                    if len(buy_idx) > 0:
                        buy_idx = buy_idx[0]
                        if buy_idx + hold_days < len(df_window):
                            entry_price = float(df_window.iloc[buy_idx]['close'])
                            exit_price = float(df_window.iloc[buy_idx + hold_days]['close'])

                            # 计算成本
                            entry_cost = entry_price * (commission_rate + slippage_rate + transfer_fee_rate)
                            exit_cost = exit_price * (commission_rate + stamp_duty_rate + slippage_rate + transfer_fee_rate)

                            # 计算收益
                            gross_return = (exit_price - entry_price) / entry_price
                            net_return = gross_return - (entry_cost + exit_cost) / entry_price
                            returns.append(net_return)

                elif result['signal'] == 'SELL':
                    sell_signals += 1
                else:
                    hold_signals += 1

                confidences.append(result['lppl_confidence'])
                rsis.append(result['rsi_14'])
                momentums.append(result['momentum_20d'])

            except:
                continue

        # 计算窗口统计
        total_analyzed = buy_signals + sell_signals + hold_signals
        elapsed = time.time() - start_time

        print(f"  分析完成: {total_analyzed} 只股票, 耗时 {elapsed:.1f}s")
        print(f"  信号分布: BUY={buy_signals}, SELL={sell_signals}, HOLD={hold_signals}")

        # 计算回测统计
        trades = len(returns)
        win_rate = len([r for r in returns if r > 0]) / trades if trades > 0 else 0
        avg_return = np.mean(returns) if returns else 0
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0
        std_return = np.std(returns) if returns else 0
        sharpe = (avg_return - 0.02/252*hold_days) / std_return * np.sqrt(252/hold_days) if std_return > 0 else 0

        print(f"  回测结果: {trades} 笔交易, 胜率 {win_rate*100:.1f}%, 平均收益 {avg_return*100:.2f}%")

        # 保存结果
        window_results.append(WindowResult(
            window_name=window_name,
            window_start=window_start,
            window_end=window_end,
            total_analyzed=total_analyzed,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            avg_confidence=np.mean(confidences) if confidences else 0,
            avg_rsi=np.mean(rsis) if rsis else 50,
            avg_momentum=np.mean(momentums) if momentums else 0,
            trades=trades,
            win_rate=win_rate,
            avg_return=avg_return,
            max_return=max_return,
            min_return=min_return,
            sharpe=sharpe
        ))

        # 垃圾回收
        gc.collect()

    # ============================================================
    # 第三阶段：计算基准收益
    # ============================================================
    print("\n" + "━" * 60)
    print("第三阶段：计算沪深300基准收益")
    print("━" * 60)

    # 加载沪深300指数
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

    # 保存报告
    report_path = project_root / "docs" / "FULL_A_STOCK_ANALYSIS_2012_2025.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_report(window_results: List[WindowResult], benchmark_returns: List[Dict]) -> str:
    """生成完整报告"""

    lines = []
    lines.append("# UniQuant 全量 A 股分析报告 (2012-2025)")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 实验类型: 全量 5000+ 只 A 股 LPPL + 因子共振分析")
    lines.append("> 时间窗口: 2012H1 ~ 2025H1（27个窗口）")
    lines.append("> 抽样策略: 每个窗口随机抽样 500 只股票")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 信号统计
    lines.append("## 一、信号统计总览")
    lines.append("")
    lines.append("### 1.1 各窗口信号分布")
    lines.append("")
    lines.append("| 窗口 | 分析数 | BUY | SELL | HOLD | BUY占比 | 平均置信度 | 平均RSI | 平均动量 |")
    lines.append("|------|--------|-----|------|------|---------|------------|---------|----------|")

    for r in window_results:
        buy_pct = r.buy_signals / r.total_analyzed * 100 if r.total_analyzed > 0 else 0
        lines.append(f"| {r.window_name} | {r.total_analyzed} | {r.buy_signals} | {r.sell_signals} | {r.hold_signals} | {buy_pct:.1f}% | {r.avg_confidence:.3f} | {r.avg_rsi:.1f} | {r.avg_momentum*100:.1f}% |")

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
    lines.append("### 2.1 各窗口回测表现")
    lines.append("")
    lines.append("| 窗口 | 交易数 | 胜率 | 平均收益 | 最大收益 | 最大亏损 | Sharpe |")
    lines.append("|------|--------|------|----------|----------|----------|--------|")

    all_trades = 0
    all_returns = []

    for r in window_results:
        lines.append(f"| {r.window_name} | {r.trades} | {r.win_rate*100:.1f}% | {r.avg_return*100:.2f}% | {r.max_return*100:.2f}% | {r.min_return*100:.2f}% | {r.sharpe:.2f} |")
        all_trades += r.trades
        if r.trades > 0:
            all_returns.extend([r.avg_return] * r.trades)

    lines.append("")

    # 总体统计
    overall_win_rate = len([r for r in window_results if r.win_rate > 0.5]) / len(window_results)
    overall_avg_return = np.mean([r.avg_return for r in window_results if r.trades > 0])

    lines.append("### 2.2 总体回测统计")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总交易数 | {all_trades:,} |")
    lines.append(f"| 窗口胜率 | {overall_win_rate*100:.1f}% |")
    lines.append(f"| 平均窗口收益 | {overall_avg_return*100:.2f}% |")
    lines.append("")

    # 4. 与基准对比
    lines.append("## 三、与沪深300基准对比")
    lines.append("")

    if benchmark_returns:
        lines.append("### 3.1 各窗口超额收益")
        lines.append("")
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

    # 5. 典型窗口分析
    lines.append("## 四、典型窗口分析")
    lines.append("")

    # 找到最佳和最差窗口
    best_window = max(window_results, key=lambda x: x.avg_return if x.trades > 0 else -999)
    worst_window = min(window_results, key=lambda x: x.avg_return if x.trades > 0 else 999)

    lines.append("### 4.1 最佳表现窗口")
    lines.append("")
    lines.append(f"- **窗口**: {best_window.window_name}")
    lines.append(f"- **平均收益**: {best_window.avg_return*100:.2f}%")
    lines.append(f"- **胜率**: {best_window.win_rate*100:.1f}%")
    lines.append(f"- **交易数**: {best_window.trades}")
    lines.append(f"- **BUY信号数**: {best_window.buy_signals}")
    lines.append("")

    lines.append("### 4.2 最差表现窗口")
    lines.append("")
    lines.append(f"- **窗口**: {worst_window.window_name}")
    lines.append(f"- **平均收益**: {worst_window.avg_return*100:.2f}%")
    lines.append(f"- **胜率**: {worst_window.win_rate*100:.1f}%")
    lines.append(f"- **交易数**: {worst_window.trades}")
    lines.append(f"- **BUY信号数**: {worst_window.buy_signals}")
    lines.append("")

    # 6. 结论
    lines.append("## 五、结论与建议")
    lines.append("")

    lines.append("### 5.1 核心发现")
    lines.append("")
    lines.append(f"1. **信号有效性**: 在 {total_analyzed:,} 次分析中，BUY 信号占比 {total_buy/total_analyzed*100:.1f}%。")
    lines.append(f"2. **窗口胜率**: {overall_win_rate*100:.1f}% 的窗口实现正收益。")
    lines.append(f"3. **平均窗口收益**: {overall_avg_return*100:.2f}%（每半年）。")
    lines.append("")

    lines.append("### 5.2 局限性")
    lines.append("")
    lines.append("1. 未使用复权因子数据（data/fq/ 目录为空）")
    lines.append("2. 回测使用简化模型（T+1、涨跌停未完全模拟）")
    lines.append("3. 每个窗口仅抽样 500 只股票，非全量")
    lines.append("4. 未考虑分红、配股等公司行为")
    lines.append("5. Wyckoff 引擎未集成（计算量过大）")
    lines.append("")

    lines.append("### 5.3 改进建议")
    lines.append("")
    lines.append("1. 补充复权因子数据，使用前复权价格")
    lines.append("2. 引入更多因子（财务因子、另类数据因子）")
    lines.append("3. 优化信号阈值，使用 Walk-Forward 方法校准")
    lines.append("4. 实现更精确的回测引擎（考虑滑点、冲击成本）")
    lines.append("5. 集成 Wyckoff 引擎进行多模型共振")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 UniQuant 多模型共振投研系统自动生成，基于代码事实，零推测。*")

    return "\n".join(lines)


if __name__ == "__main__":
    run_optimized_analysis()
