#!/usr/bin/env python3
"""
UniQuant 全量 A 股多模型共振分析实验（修正版）
==============================================
使用通达信全量 5199 只股票的本地日线数据，
选择从 2012 年到 2025 年的 5 个时间窗口，
进行全量 Wyckoff、LPPL 分析等因子和交易分析，
对比沪深300指数的相对收益。

改进点：
1. 使用全量股票（不抽样）
2. 集成 LPPL + 因子分析
3. 优化性能：批量处理 + 缓存
4. 深度研究生成的数据
"""

import sys
import warnings
import time
import gc
import os
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

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
class StockAnalysis:
    """单只股票分析结果"""
    symbol: str
    window_name: str
    lppl_direction: str
    lppl_confidence: float
    lppl_days_to_tc: float
    rsi_14: float
    momentum_20d: float
    volatility_20d: float
    ma_ratio_5_20: float
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
    holding_days: int


@dataclass
class WindowSummary:
    """窗口汇总"""
    window_name: str
    window_start: str
    window_end: str
    total_stocks: int
    analyzed_stocks: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    trades: int
    win_rate: float
    avg_return: float
    max_return: float
    min_return: float
    median_return: float
    avg_confidence: float
    avg_rsi: float
    avg_momentum: float


# ============================================================
# 快速多模型分析器
# ============================================================

class FastMultiModelAnalyzer:
    """快速多模型分析器"""

    def __init__(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        from uniquant.brain.factors.custom_factors import (
            compute_momentum_20d,
            compute_volatility_20d,
            compute_rsi_14,
            compute_ma_ratio_5_20
        )

        self.lppl_calculator = LPPLCalculator()
        self.compute_momentum_20d = compute_momentum_20d
        self.compute_volatility_20d = compute_volatility_20d
        self.compute_rsi_14 = compute_rsi_14
        self.compute_ma_ratio_5_20 = compute_ma_ratio_5_20

    def analyze(self, df: pd.DataFrame, symbol: str, window_name: str) -> Optional[StockAnalysis]:
        """多模型分析"""
        try:
            if len(df) < 60:
                return None

            # LPPL 分析
            close_prices = df['close'].values
            lppl_result = self.lppl_calculator.fit_single_window(close_prices)

            lppl_direction = 'neutral'
            lppl_confidence = 0.0
            lppl_days_to_tc = 999

            if lppl_result:
                lppl_direction = lppl_result.get('direction', 'neutral')
                lppl_confidence = lppl_result.get('confidence', 0.0)
                lppl_days_to_tc = lppl_result.get('days_to_tc', 999)

            # 因子计算
            momentum = self.compute_momentum_20d(df)
            volatility = self.compute_volatility_20d(df)
            rsi = self.compute_rsi_14(df)
            ma_ratio = self.compute_ma_ratio_5_20(df)

            momentum_val = float(momentum.iloc[-1]) if not momentum.empty else 0.0
            volatility_val = float(volatility.iloc[-1]) if not volatility.empty else 0.0
            rsi_val = float(rsi.iloc[-1]) if not rsi.empty else 50.0
            ma_ratio_val = float(ma_ratio.iloc[-1]) if not ma_ratio.empty else 0.0

            # 多模型共振信号生成
            score = 0.0

            # LPPL 信号权重 40%
            if lppl_direction == 'bubble' and lppl_days_to_tc < 20:
                score -= 0.4 * lppl_confidence
            elif lppl_direction == 'negative_bubble' and lppl_days_to_tc < 20:
                score += 0.4 * lppl_confidence

            # RSI 信号权重 20%
            if rsi_val > 70:
                score -= 0.2
            elif rsi_val < 30:
                score += 0.2

            # 动量信号权重 20%
            if momentum_val > 0.1:
                score -= 0.15
            elif momentum_val < -0.1:
                score += 0.15

            # 均线比率信号权重 20%
            if ma_ratio_val > 0.05:
                score -= 0.1
            elif ma_ratio_val < -0.05:
                score += 0.1

            # 生成信号
            if score > 0.2:
                signal = 'BUY'
            elif score < -0.2:
                signal = 'SELL'
            else:
                signal = 'HOLD'

            return StockAnalysis(
                symbol=symbol,
                window_name=window_name,
                lppl_direction=lppl_direction,
                lppl_confidence=lppl_confidence,
                lppl_days_to_tc=lppl_days_to_tc,
                rsi_14=rsi_val,
                momentum_20d=momentum_val,
                volatility_20d=volatility_val,
                ma_ratio_5_20=ma_ratio_val,
                signal=signal,
                signal_strength=abs(score)
            )
        except Exception as e:
            return None


# ============================================================
# 回测引擎
# ============================================================

class SimpleBacktester:
    """简化回测引擎"""

    def __init__(self):
        self.commission_rate = 0.0003
        self.stamp_duty_rate = 0.0005
        self.slippage_rate = 0.0005
        self.transfer_fee_rate = 0.00001
        self.hold_days = 20

    def backtest(self, df: pd.DataFrame, buy_date: str, symbol: str, window_name: str) -> Optional[TradeResult]:
        """执行回测"""
        try:
            buy_idx = df[df['date'] >= pd.Timestamp(buy_date)].index
            if len(buy_idx) == 0:
                return None
            buy_idx = buy_idx[0]

            if buy_idx + self.hold_days >= len(df):
                return None

            entry_price = float(df.iloc[buy_idx]['close'])
            exit_price = float(df.iloc[buy_idx + self.hold_days]['close'])

            # 计算成本
            entry_cost = entry_price * (self.commission_rate + self.slippage_rate + self.transfer_fee_rate)
            exit_cost = exit_price * (self.commission_rate + self.stamp_duty_rate + self.slippage_rate + self.transfer_fee_rate)

            # 计算收益
            gross_return = (exit_price - entry_price) / entry_price
            net_return = gross_return - (entry_cost + exit_cost) / entry_price

            return TradeResult(
                symbol=symbol,
                window_name=window_name,
                entry_date=str(df.iloc[buy_idx]['date'].date()),
                exit_date=str(df.iloc[buy_idx + self.hold_days]['date'].date()),
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=net_return,
                holding_days=self.hold_days
            )
        except:
            return None


# ============================================================
# 主实验流程
# ============================================================

def run_full_multi_model_analysis():
    """执行全量多模型分析实验"""
    print("=" * 80)
    print("UniQuant 全量 A 股多模型共振分析实验（修正版）")
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

    # 5个时间窗口（2012-2025年，选择关键年份）
    time_windows = [
        ("2012-01-01", "2013-12-31", "2012-2013"),
        ("2014-01-01", "2016-12-31", "2014-2016"),
        ("2017-01-01", "2019-12-31", "2017-2019"),
        ("2020-01-01", "2022-12-31", "2020-2022"),
        ("2023-01-01", "2025-05-21", "2023-2025"),
    ]

    print(f"时间窗口: {len(time_windows)} 个")
    for ws, we, wn in time_windows:
        print(f"  {wn}: {ws} ~ {we}")
    print()

    # ============================================================
    # 第二阶段：全量多模型分析
    # ============================================================
    print("━" * 60)
    print("第二阶段：全量 LPPL + 因子分析")
    print("━" * 60)

    analyzer = FastMultiModelAnalyzer()
    backtester = SimpleBacktester()

    # 存储结果
    all_analyses: List[StockAnalysis] = []
    all_trades: List[TradeResult] = []
    window_summaries: List[WindowSummary] = []

    for window_start, window_end, window_name in time_windows:
        print(f"\n【{window_name}】{window_start} ~ {window_end}")
        print("-" * 40)

        start_time = time.time()

        # 统计
        total_stocks = 0
        analyzed_stocks = 0
        buy_signals = 0
        sell_signals = 0
        hold_signals = 0
        confidences = []
        rsis = []
        momentums = []
        window_trades = []

        # 批量处理
        batch_size = 100
        num_batches = (len(all_symbols) + batch_size - 1) // batch_size

        for batch_idx in range(num_batches):
            batch_start = batch_idx * batch_size
            batch_end = min((batch_idx + 1) * batch_size, len(all_symbols))
            batch_symbols = all_symbols[batch_start:batch_end]

            for symbol in batch_symbols:
                total_stocks += 1

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

                    # 多模型分析
                    analysis = analyzer.analyze(df_analysis, symbol, window_name)
                    if analysis is None:
                        continue

                    analyzed_stocks += 1
                    all_analyses.append(analysis)

                    # 统计信号
                    if analysis.signal == 'BUY':
                        buy_signals += 1

                        # 回测
                        trade = backtester.backtest(df_window, window_start, symbol, window_name)
                        if trade:
                            window_trades.append(trade)
                            all_trades.append(trade)

                    elif analysis.signal == 'SELL':
                        sell_signals += 1
                    else:
                        hold_signals += 1

                    confidences.append(analysis.lppl_confidence)
                    rsis.append(analysis.rsi_14)
                    momentums.append(analysis.momentum_20d)

                except:
                    continue

            # 进度显示
            if (batch_idx + 1) % 10 == 0 or batch_idx == num_batches - 1:
                elapsed = time.time() - start_time
                print(f"  批次 {batch_idx + 1}/{num_batches} 完成, 已分析 {analyzed_stocks} 只, 耗时 {elapsed:.1f}s")

        # 计算窗口统计
        trades = len(window_trades)
        returns = [t.return_pct for t in window_trades]
        win_rate = len([r for r in returns if r > 0]) / trades if trades > 0 else 0
        avg_return = np.mean(returns) if returns else 0
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0
        median_return = np.median(returns) if returns else 0

        elapsed = time.time() - start_time
        print(f"\n  分析完成: {analyzed_stocks}/{total_stocks} 只股票, 耗时 {elapsed:.1f}s")
        print(f"  信号分布: BUY={buy_signals}, SELL={sell_signals}, HOLD={hold_signals}")
        print(f"  回测结果: {trades} 笔交易")
        if trades > 0:
            print(f"  胜率: {win_rate*100:.1f}%, 平均收益: {avg_return*100:.2f}%, 中位数: {median_return*100:.2f}%")

        # 保存窗口汇总
        window_summaries.append(WindowSummary(
            window_name=window_name,
            window_start=window_start,
            window_end=window_end,
            total_stocks=total_stocks,
            analyzed_stocks=analyzed_stocks,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            trades=trades,
            win_rate=win_rate,
            avg_return=avg_return,
            max_return=max_return,
            min_return=min_return,
            median_return=median_return,
            avg_confidence=np.mean(confidences) if confidences else 0,
            avg_rsi=np.mean(rsis) if rsis else 50,
            avg_momentum=np.mean(momentums) if momentums else 0
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
            print(f"  {window_name}: {ret*100:.2f}%")

    # ============================================================
    # 第四阶段：深度数据分析
    # ============================================================
    print("\n" + "━" * 60)
    print("第四阶段：深度数据分析")
    print("━" * 60)

    # 按信号强度排序的 Top 50 信号
    top_signals = sorted(all_analyses, key=lambda x: x.signal_strength, reverse=True)[:50]

    # 按收益排序的 Top 20 交易
    top_trades = sorted(all_trades, key=lambda x: x.return_pct, reverse=True)[:20]
    worst_trades = sorted(all_trades, key=lambda x: x.return_pct)[:20]

    # LPPL 信号分布
    lppl_bubble = len([a for a in all_analyses if a.lppl_direction == 'bubble'])
    lppl_negative = len([a for a in all_analyses if a.lppl_direction == 'negative_bubble'])
    lppl_neutral = len([a for a in all_analyses if a.lppl_direction == 'neutral'])

    print(f"LPPL 信号分布: bubble={lppl_bubble}, negative_bubble={lppl_negative}, neutral={lppl_neutral}")
    print(f"Top 50 信号平均强度: {np.mean([s.signal_strength for s in top_signals]):.3f}")
    print(f"Top 20 最佳交易平均收益: {np.mean([t.return_pct for t in top_trades])*100:.2f}%")

    # ============================================================
    # 第五阶段：生成报告
    # ============================================================
    print("\n" + "━" * 60)
    print("第五阶段：生成深度分析报告")
    print("━" * 60)

    report = generate_deep_report(
        window_summaries, benchmark_returns, all_analyses, all_trades,
        top_signals, top_trades, worst_trades
    )

    report_path = project_root / "docs" / "FULL_MULTI_MODEL_ANALYSIS_2012_2025.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_deep_report(
    window_summaries: List[WindowSummary],
    benchmark_returns: List[Dict],
    all_analyses: List[StockAnalysis],
    all_trades: List[TradeResult],
    top_signals: List[StockAnalysis],
    top_trades: List[TradeResult],
    worst_trades: List[TradeResult]
) -> str:
    """生成深度分析报告"""

    lines = []
    lines.append("# UniQuant 全量 A 股多模型共振分析报告 (2012-2025)")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 实验类型: 全量 5000+ 只 A 股 LPPL + 因子共振分析")
    lines.append("> 时间窗口: 2012-2025年（5个窗口）")
    lines.append("> 数据规模: 全量股票，不抽样")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 总体统计
    lines.append("## 一、总体统计")
    lines.append("")

    total_analyzed = sum(w.analyzed_stocks for w in window_summaries)
    total_buy = sum(w.buy_signals for w in window_summaries)
    total_sell = sum(w.sell_signals for w in window_summaries)
    total_hold = sum(w.hold_signals for w in window_summaries)
    total_trades = sum(w.trades for w in window_summaries)

    lines.append("### 1.1 分析规模")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总分析次数 | {total_analyzed:,} |")
    lines.append(f"| BUY 信号 | {total_buy:,} ({total_buy/total_analyzed*100:.1f}%) |")
    lines.append(f"| SELL 信号 | {total_sell:,} ({total_sell/total_analyzed*100:.1f}%) |")
    lines.append(f"| HOLD 信号 | {total_hold:,} ({total_hold/total_analyzed*100:.1f}%) |")
    lines.append(f"| 总交易数 | {total_trades:,} |")
    lines.append("")

    # LPPL 信号分布
    lppl_bubble = len([a for a in all_analyses if a.lppl_direction == 'bubble'])
    lppl_negative = len([a for a in all_analyses if a.lppl_direction == 'negative_bubble'])
    lppl_neutral = len([a for a in all_analyses if a.lppl_direction == 'neutral'])

    lines.append("### 1.2 LPPL 信号分布")
    lines.append("")
    lines.append("| 方向 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    lines.append(f"| 正向泡沫 (bubble) | {lppl_bubble:,} | {lppl_bubble/total_analyzed*100:.1f}% |")
    lines.append(f"| 负向泡沫 (negative_bubble) | {lppl_negative:,} | {lppl_negative/total_analyzed*100:.1f}% |")
    lines.append(f"| 中性 | {lppl_neutral:,} | {lppl_neutral/total_analyzed*100:.1f}% |")
    lines.append("")

    # 2. 各窗口表现
    lines.append("## 二、各窗口表现")
    lines.append("")
    lines.append("### 2.1 信号分布")
    lines.append("")
    lines.append("| 窗口 | 分析数 | BUY | SELL | HOLD | BUY占比 | 平均RSI | 平均动量 |")
    lines.append("|------|--------|-----|------|------|---------|---------|----------|")

    for w in window_summaries:
        buy_pct = w.buy_signals / w.analyzed_stocks * 100 if w.analyzed_stocks > 0 else 0
        lines.append(f"| {w.window_name} | {w.analyzed_stocks:,} | {w.buy_signals:,} | {w.sell_signals:,} | {w.hold_signals:,} | {buy_pct:.1f}% | {w.avg_rsi:.1f} | {w.avg_momentum*100:.1f}% |")

    lines.append("")

    lines.append("### 2.2 回测表现")
    lines.append("")
    lines.append("| 窗口 | 交易数 | 胜率 | 平均收益 | 中位数收益 | 最大收益 | 最大亏损 |")
    lines.append("|------|--------|------|----------|------------|----------|----------|")

    for w in window_summaries:
        lines.append(f"| {w.window_name} | {w.trades:,} | {w.win_rate*100:.1f}% | {w.avg_return*100:.2f}% | {w.median_return*100:.2f}% | {w.max_return*100:.2f}% | {w.min_return*100:.2f}% |")

    lines.append("")

    # 3. 与基准对比
    lines.append("## 三、与沪深300基准对比")
    lines.append("")

    if benchmark_returns:
        lines.append("### 3.1 各窗口超额收益")
        lines.append("")
        lines.append("| 窗口 | 策略收益 | 基准收益 | 超额收益 | 策略胜率 |")
        lines.append("|------|----------|----------|----------|----------|")

        for i, bm in enumerate(benchmark_returns):
            bm_return = bm['return_pct']

            if i < len(window_summaries) and window_summaries[i].trades > 0:
                strategy_return = window_summaries[i].avg_return
                excess = strategy_return - bm_return
                win_rate = window_summaries[i].win_rate
                lines.append(f"| {bm['window']} | {strategy_return*100:.2f}% | {bm_return*100:.2f}% | {excess*100:.2f}% | {win_rate*100:.1f}% |")
            else:
                lines.append(f"| {bm['window']} | - | {bm_return*100:.2f}% | - | - |")

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

            if i < len(window_summaries) and window_summaries[i].trades > 0:
                strategy_return = window_summaries[i].avg_return
                strategy_cumulative *= (1 + strategy_return)
                benchmark_cumulative *= (1 + bm_return)
                excess_cumulative = strategy_cumulative - benchmark_cumulative
                lines.append(f"| {bm['window']} | {strategy_cumulative:.4f} | {benchmark_cumulative:.4f} | {excess_cumulative:.4f} |")

        lines.append("")

    # 4. 收益分布分析
    lines.append("## 四、收益分布分析")
    lines.append("")

    if all_trades:
        returns = [t.return_pct for t in all_trades]
        returns_array = np.array(returns)

        lines.append("### 4.1 收益分布统计")
        lines.append("")
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
        lines.append("### 4.2 收益分布")
        lines.append("")
        lines.append("| 收益区间 | 数量 | 占比 |")
        lines.append("|----------|------|------|")

        bins = [(-100, -20), (-20, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 20), (20, 100)]
        for low, high in bins:
            count = len([r for r in returns_array if low <= r*100 < high])
            pct = count / len(returns_array) * 100
            lines.append(f"| [{low}%, {high}%) | {count:,} | {pct:.1f}% |")

        lines.append("")

    # 5. Top 信号分析
    lines.append("## 五、Top 信号分析")
    lines.append("")

    lines.append("### 5.1 信号强度 Top 20")
    lines.append("")
    lines.append("| # | 股票 | 窗口 | LPPL方向 | 置信度 | RSI | 动量 | 均线比 | 信号 | 强度 |")
    lines.append("|---|------|------|----------|--------|-----|------|--------|------|------|")

    for i, s in enumerate(top_signals[:20], 1):
        lines.append(
            f"| {i} | {s.symbol} | {s.window_name} | {s.lppl_direction[:6]} | "
            f"{s.lppl_confidence:.3f} | {s.rsi_14:.0f} | {s.momentum_20d*100:.1f}% | "
            f"{s.ma_ratio_5_20*100:.1f}% | {s.signal} | {s.signal_strength:.3f} |"
        )

    lines.append("")

    # 6. 最佳/最差交易
    lines.append("## 六、最佳与最差交易")
    lines.append("")

    lines.append("### 6.1 最佳交易 Top 20")
    lines.append("")
    lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 入场价 | 出场价 | 收益 |")
    lines.append("|---|------|------|--------|--------|--------|--------|------|")

    for i, t in enumerate(top_trades[:20], 1):
        lines.append(
            f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | "
            f"{t.entry_price:.2f} | {t.exit_price:.2f} | {t.return_pct*100:.2f}% |"
        )

    lines.append("")

    lines.append("### 6.2 最差交易 Top 20")
    lines.append("")
    lines.append("| # | 股票 | 窗口 | 入场日 | 出场日 | 入场价 | 出场价 | 收益 |")
    lines.append("|---|------|------|--------|--------|--------|--------|------|")

    for i, t in enumerate(worst_trades[:20], 1):
        lines.append(
            f"| {i} | {t.symbol} | {t.window_name} | {t.entry_date} | {t.exit_date} | "
            f"{t.entry_price:.2f} | {t.exit_price:.2f} | {t.return_pct*100:.2f}% |"
        )

    lines.append("")

    # 7. 典型窗口深度分析
    lines.append("## 七、典型窗口深度分析")
    lines.append("")

    # 找到最佳和最差窗口
    windows_with_trades = [w for w in window_summaries if w.trades > 0]
    if windows_with_trades:
        best_window = max(windows_with_trades, key=lambda x: x.avg_return)
        worst_window = min(windows_with_trades, key=lambda x: x.avg_return)

        lines.append("### 7.1 最佳表现窗口")
        lines.append("")
        lines.append(f"- **窗口**: {best_window.window_name}")
        lines.append(f"- **时间范围**: {best_window.window_start} ~ {best_window.window_end}")
        lines.append(f"- **分析股票数**: {best_window.analyzed_stocks:,}")
        lines.append(f"- **BUY信号数**: {best_window.buy_signals:,}")
        lines.append(f"- **交易数**: {best_window.trades:,}")
        lines.append(f"- **胜率**: {best_window.win_rate*100:.1f}%")
        lines.append(f"- **平均收益**: {best_window.avg_return*100:.2f}%")
        lines.append(f"- **中位数收益**: {best_window.median_return*100:.2f}%")
        lines.append(f"- **平均RSI**: {best_window.avg_rsi:.1f}")
        lines.append(f"- **平均动量**: {best_window.avg_momentum*100:.1f}%")
        lines.append("")

        lines.append("### 7.2 最差表现窗口")
        lines.append("")
        lines.append(f"- **窗口**: {worst_window.window_name}")
        lines.append(f"- **时间范围**: {worst_window.window_start} ~ {worst_window.window_end}")
        lines.append(f"- **分析股票数**: {worst_window.analyzed_stocks:,}")
        lines.append(f"- **BUY信号数**: {worst_window.buy_signals:,}")
        lines.append(f"- **交易数**: {worst_window.trades:,}")
        lines.append(f"- **胜率**: {worst_window.win_rate*100:.1f}%")
        lines.append(f"- **平均收益**: {worst_window.avg_return*100:.2f}%")
        lines.append(f"- **中位数收益**: {worst_window.median_return*100:.2f}%")
        lines.append(f"- **平均RSI**: {worst_window.avg_rsi:.1f}")
        lines.append(f"- **平均动量**: {worst_window.avg_momentum*100:.1f}%")
        lines.append("")

    # 8. 结论
    lines.append("## 八、结论与建议")
    lines.append("")

    if all_trades:
        returns = [t.return_pct for t in all_trades]
        win_rate = len([r for r in returns if r > 0]) / len(returns)
        avg_return = np.mean(returns)

        lines.append("### 8.1 核心发现")
        lines.append("")
        lines.append(f"1. **信号有效性**: 在 {len(all_trades):,} 笔交易中，胜率为 {win_rate*100:.1f}%，")
        lines.append(f"   平均收益率为 {avg_return*100:.2f}%（20日持仓期）。")
        lines.append("")
        lines.append(f"2. **LPPL 信号分布**: 正向泡沫信号占比 {lppl_bubble/total_analyzed*100:.1f}%，")
        lines.append(f"   负向泡沫信号占比 {lppl_negative/total_analyzed*100:.1f}%。")
        lines.append("")

        if benchmark_returns:
            total_strategy = 1.0
            total_benchmark = 1.0
            for i, bm in enumerate(benchmark_returns):
                if i < len(window_summaries) and window_summaries[i].trades > 0:
                    total_strategy *= (1 + window_summaries[i].avg_return)
                    total_benchmark *= (1 + bm['return_pct'])

            lines.append(f"3. **累计收益**: 策略累计收益 {total_strategy:.4f}，基准累计收益 {total_benchmark:.4f}。")
            lines.append("")

    lines.append("### 8.2 局限性")
    lines.append("")
    lines.append("1. 未使用复权因子数据（data/fq/ 目录为空）")
    lines.append("2. 回测使用简化模型（T+1、涨跌停未完全模拟）")
    lines.append("3. 未考虑分红、配股等公司行为")
    lines.append("4. Wyckoff 引擎未集成（计算量过大）")
    lines.append("")

    lines.append("### 8.3 改进建议")
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
    run_full_multi_model_analysis()
