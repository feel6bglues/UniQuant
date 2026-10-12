#!/usr/bin/env python3
"""
UniQuant 全量 A 股深度分析实验
==============================
使用通达信全量 5000+ 只股票的本地日线数据，
选择从 2012 年到 2025 年的 20 个时间窗口，
进行全量 LPPL + 因子分析，
对比沪深300指数的相对收益，
分析夏普比率、算法正确性、策略组合。

分析维度：
1. 夏普比率分析（滚动窗口、不同持有期）
2. 算法正确性验证（LPPL参数合理性、因子有效性）
3. 策略组合分析（多因子组合、风险平价）
4. 深度数据研究
"""

import sys
import os
import time
import gc
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class LPPLResult:
    """LPPL 分析结果"""
    tc: float  # 临界时间点
    m: float   # 缩放指数
    w: float   # 角频率
    b: float   # 线性项系数
    c: float   # 周期性项系数
    rmse: float
    confidence: float
    direction: str
    days_to_tc: float
    is_valid: bool  # 参数是否合理


@dataclass
class FactorExposure:
    """因子暴露"""
    momentum_20d: float
    momentum_60d: float
    volatility_20d: float
    volatility_60d: float
    rsi_14: float
    ma_ratio_5_20: float
    volume_ratio_5_20: float


@dataclass
class SignalResult:
    """信号结果"""
    symbol: str
    window_name: str
    date: str
    lppl: LPPLResult
    factors: FactorExposure
    signal: str  # BUY/SELL/HOLD
    signal_score: float
    confidence: float


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
    max_drawdown: float


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


# ============================================================
# LPPL 分析器（带正确性验证）
# ============================================================

class LPPLAnalyzer:
    """LPPL 分析器"""

    def __init__(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        self.calculator = LPPLCalculator()

    def analyze(self, close_prices: np.ndarray) -> Optional[LPPLResult]:
        """分析 LPPL"""
        try:
            if len(close_prices) < 60:
                return None

            result = self.calculator.fit_single_window(close_prices)
            if result is None:
                return None

            params = result.get('params', [0]*7)
            tc, m, w, a, b, c, phi = params if len(params) == 7 else [0]*7

            # 参数合理性验证
            is_valid = True
            if m < 0 or m > 1:
                is_valid = False
            if w < 0 or w > 30:
                is_valid = False
            if tc < len(close_prices) * 0.5:
                is_valid = False

            return LPPLResult(
                tc=tc,
                m=m,
                w=w,
                b=b,
                c=c,
                rmse=result.get('rmse', 999),
                confidence=result.get('confidence', 0.0),
                direction=result.get('direction', 'neutral'),
                days_to_tc=result.get('days_to_tc', 999),
                is_valid=is_valid
            )
        except Exception as e:
            return None


# ============================================================
# 因子计算器
# ============================================================

class FactorCalculator:
    """因子计算器"""

    def calculate(self, df: pd.DataFrame) -> Optional[FactorExposure]:
        """计算因子"""
        try:
            if len(df) < 60:
                return None

            from uniquant.brain.factors.custom_factors import (
                compute_momentum_20d,
                compute_momentum_60d,
                compute_volatility_20d,
                compute_volatility_60d,
                compute_rsi_14,
                compute_ma_ratio_5_20,
                compute_volume_ratio_5_20
            )

            return FactorExposure(
                momentum_20d=float(compute_momentum_20d(df).iloc[-1]),
                momentum_60d=float(compute_momentum_60d(df).iloc[-1]),
                volatility_20d=float(compute_volatility_20d(df).iloc[-1]),
                volatility_60d=float(compute_volatility_60d(df).iloc[-1]),
                rsi_14=float(compute_rsi_14(df).iloc[-1]),
                ma_ratio_5_20=float(compute_ma_ratio_5_20(df).iloc[-1]),
                volume_ratio_5_20=float(compute_volume_ratio_5_20(df).iloc[-1])
            )
        except:
            return None


# ============================================================
# 信号生成器（多因子组合）
# ============================================================

class SignalGenerator:
    """信号生成器"""

    def generate(self, lppl: LPPLResult, factors: FactorExposure) -> Tuple[str, float, float]:
        """生成信号"""
        score = 0.0
        weights = {
            'lppl': 0.35,
            'momentum': 0.20,
            'rsi': 0.20,
            'volatility': 0.15,
            'ma_ratio': 0.10
        }

        # LPPL 信号
        if lppl.direction == 'bubble' and lppl.days_to_tc < 20:
            score -= weights['lppl'] * lppl.confidence
        elif lppl.direction == 'negative_bubble' and lppl.days_to_tc < 20:
            score += weights['lppl'] * lppl.confidence

        # 动量信号
        if factors.momentum_20d > 0.1:
            score -= weights['momentum']
        elif factors.momentum_20d < -0.1:
            score += weights['momentum']

        # RSI 信号
        if factors.rsi_14 > 70:
            score -= weights['rsi']
        elif factors.rsi_14 < 30:
            score += weights['rsi']

        # 波动率信号
        if factors.volatility_20d > 0.5:
            score -= weights['volatility'] * 0.5
        elif factors.volatility_20d < 0.2:
            score += weights['volatility'] * 0.5

        # 均线比率信号
        if factors.ma_ratio_5_20 > 0.05:
            score -= weights['ma_ratio']
        elif factors.ma_ratio_5_20 < -0.05:
            score += weights['ma_ratio']

        # 生成信号
        if score > 0.15:
            signal = 'BUY'
        elif score < -0.15:
            signal = 'SELL'
        else:
            signal = 'HOLD'

        # 计算置信度
        confidence = min(abs(score) / 0.5, 1.0)

        return signal, score, confidence


# ============================================================
# 回测引擎
# ============================================================

class BacktestEngine:
    """回测引擎"""

    def __init__(self, hold_days: int = 20):
        self.commission_rate = 0.0003
        self.stamp_duty_rate = 0.0005
        self.slippage_rate = 0.0005
        self.transfer_fee_rate = 0.00001
        self.hold_days = hold_days

    def backtest(self, df: pd.DataFrame, buy_date: str, symbol: str) -> Optional[TradeResult]:
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

            # 计算最大回撤
            period_data = df.iloc[buy_idx:buy_idx + self.hold_days + 1]
            peak = entry_price
            max_dd = 0.0
            for _, row in period_data.iterrows():
                price = float(row['close'])
                if price > peak:
                    peak = price
                dd = (peak - price) / peak
                if dd > max_dd:
                    max_dd = dd

            return TradeResult(
                symbol=symbol,
                window_name='',
                entry_date=str(df.iloc[buy_idx]['date'].date()),
                exit_date=str(df.iloc[buy_idx + self.hold_days]['date'].date()),
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=net_return,
                holding_days=self.hold_days,
                max_drawdown=max_dd
            )
        except:
            return None


# ============================================================
# 夏普比率计算器
# ============================================================

class SharpeCalculator:
    """夏普比率计算器"""

    def __init__(self, risk_free_rate: float = 0.02):
        self.risk_free_rate = risk_free_rate

    def calculate(self, returns: List[float], holding_days: int = 20) -> float:
        """计算夏普比率"""
        if not returns or len(returns) < 2:
            return 0.0

        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return == 0:
            return 0.0

        # 年化夏普比率
        rf_daily = self.risk_free_rate / 252 * holding_days
        excess_return = mean_return - rf_daily
        sharpe = excess_return / std_return * np.sqrt(252 / holding_days)

        return float(sharpe)

    def rolling_sharpe(self, returns: List[float], window: int = 20) -> List[float]:
        """滚动夏普比率"""
        if len(returns) < window:
            return []

        sharpes = []
        for i in range(window, len(returns)):
            window_returns = returns[i-window:i]
            sharpes.append(self.calculate(window_returns))

        return sharpes


# ============================================================
# 策略组合分析器
# ============================================================

class PortfolioAnalyzer:
    """策略组合分析器"""

    def risk_parity_weights(self, returns_matrix: np.ndarray) -> np.ndarray:
        """风险平价权重"""
        n_assets = returns_matrix.shape[1]
        vols = np.std(returns_matrix, axis=0)
        inv_vols = 1.0 / np.maximum(vols, 1e-8)
        weights = inv_vols / np.sum(inv_vols)
        return weights

    def equal_weight_returns(self, returns_list: List[List[float]]) -> List[float]:
        """等权组合收益"""
        if not returns_list:
            return []

        min_len = min(len(r) for r in returns_list)
        combined = []
        for i in range(min_len):
            avg_return = np.mean([r[i] for r in returns_list])
            combined.append(avg_return)

        return combined

    def max_sharpe_weights(self, returns_matrix: np.ndarray) -> np.ndarray:
        """最大夏普比率权重（简化版）"""
        n_assets = returns_matrix.shape[1]

        # 计算协方差矩阵
        cov = np.cov(returns_matrix.T)
        mean_returns = np.mean(returns_matrix, axis=0)

        # 简化：使用逆波动率加权
        vols = np.sqrt(np.diag(cov))
        inv_vols = 1.0 / np.maximum(vols, 1e-8)
        weights = inv_vols / np.sum(inv_vols)

        return weights


# ============================================================
# 主实验流程
# ============================================================

def run_deep_analysis():
    """执行深度分析实验"""
    print("=" * 80)
    print("UniQuant 全量 A 股深度分析实验")
    print("=" * 80)
    print(f"实验开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ============================================================
    # 第一阶段：数据准备
    # ============================================================
    print("━" * 60)
    print("第一阶段：数据准备")
    print("━" * 60)

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
    # 第二阶段：全量分析
    # ============================================================
    print("━" * 60)
    print("第二阶段：全量 LPPL + 因子分析")
    print("━" * 60)

    lppl_analyzer = LPPLAnalyzer()
    factor_calculator = FactorCalculator()
    signal_generator = SignalGenerator()
    backtester = BacktestEngine(hold_days=20)
    sharpe_calculator = SharpeCalculator()

    # 存储结果
    all_signals: List[SignalResult] = []
    all_trades: List[TradeResult] = []
    window_stats_list: List[WindowStats] = []

    # LPPL 参数统计
    lppl_params_valid = 0
    lppl_params_total = 0
    lppl_tc_distribution = []
    lppl_m_distribution = []

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
        window_signals = []

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
                lppl_result = lppl_analyzer.analyze(close_prices)
                if lppl_result is None:
                    continue

                # 统计 LPPL 参数
                lppl_params_total += 1
                if lppl_result.is_valid:
                    lppl_params_valid += 1
                lppl_tc_distribution.append(lppl_result.days_to_tc)
                lppl_m_distribution.append(lppl_result.m)

                # 因子计算
                factors = factor_calculator.calculate(df_analysis)
                if factors is None:
                    continue

                # 生成信号
                signal, score, confidence = signal_generator.generate(lppl_result, factors)

                analyzed += 1
                confidences.append(confidence)
                rsis.append(factors.rsi_14)
                momentums.append(factors.momentum_20d)

                # 保存信号
                sig_result = SignalResult(
                    symbol=symbol,
                    window_name=window_name,
                    date=window_end,
                    lppl=lppl_result,
                    factors=factors,
                    signal=signal,
                    signal_score=score,
                    confidence=confidence
                )
                all_signals.append(sig_result)
                window_signals.append(sig_result)

                if signal == 'BUY':
                    buy_signals += 1

                    # 回测
                    trade = backtester.backtest(df_window, window_start, symbol)
                    if trade:
                        trade.window_name = window_name
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
        sharpe = sharpe_calculator.calculate(trade_returns)
        max_dd = max([t.max_drawdown for t in trades]) if trades else 0

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

    # ============================================================
    # 第三阶段：基准收益计算
    # ============================================================
    print("\n" + "━" * 60)
    print("第三阶段：计算沪深300基准收益")
    print("━" * 60)

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
    # 第四阶段：深度分析
    # ============================================================
    print("\n" + "━" * 60)
    print("第四阶段：深度数据分析")
    print("━" * 60)

    # 1. LPPL 参数正确性验证
    print("\n1. LPPL 参数正确性验证:")
    print(f"  有效参数比例: {lppl_params_valid}/{lppl_params_total} ({lppl_params_valid/lppl_params_total*100:.1f}%)")
    print(f"  tc 分布: 均值={np.mean(lppl_tc_distribution):.1f}, 中位数={np.median(lppl_tc_distribution):.1f}")
    print(f"  m 分布: 均值={np.mean(lppl_m_distribution):.3f}, 中位数={np.median(lppl_m_distribution):.3f}")

    # 2. 夏普比率分析
    print("\n2. 夏普比率分析:")
    all_returns = [t.return_pct for t in all_trades]
    overall_sharpe = sharpe_calculator.calculate(all_returns)
    print(f"  总体夏普比率: {overall_sharpe:.2f}")

    # 滚动夏普
    rolling_sharpes = sharpe_calculator.rolling_sharpe(all_returns, window=100)
    if rolling_sharpes:
        print(f"  滚动夏普(100): 均值={np.mean(rolling_sharpes):.2f}, 标准差={np.std(rolling_sharpes):.2f}")

    # 3. 策略组合分析
    print("\n3. 策略组合分析:")

    # 按窗口分组的收益
    window_returns = {}
    for trade in all_trades:
        if trade.window_name not in window_returns:
            window_returns[trade.window_name] = []
        window_returns[trade.window_name].append(trade.return_pct)

    # 等权组合
    if window_returns:
        min_len = min(len(r) for r in window_returns.values())
        combined_returns = []
        for i in range(min_len):
            avg = np.mean([window_returns[w][i] for w in window_returns if i < len(window_returns[w])])
            combined_returns.append(avg)

        combined_sharpe = sharpe_calculator.calculate(combined_returns)
        print(f"  等权组合夏普比率: {combined_sharpe:.2f}")

    # 4. 因子有效性分析
    print("\n4. 因子有效性分析:")
    factor_names = ['momentum_20d', 'rsi_14', 'volatility_20d', 'ma_ratio_5_20']
    for factor_name in factor_names:
        factor_values = [getattr(s.factors, factor_name) for s in all_signals]
        returns = [all_trades[i].return_pct for i in range(min(len(all_trades), len(factor_values)))]

        if len(factor_values) > 0 and len(returns) > 0:
            # 计算因子与收益的相关性
            correlation = np.corrcoef(factor_values[:len(returns)], returns)[0, 1]
            print(f"  {factor_name}: 相关系数={correlation:.4f}")

    # ============================================================
    # 第五阶段：生成报告
    # ============================================================
    print("\n" + "━" * 60)
    print("第五阶段：生成深度分析报告")
    print("━" * 60)

    report = generate_deep_report(
        window_stats_list, benchmark_returns, all_signals, all_trades,
        lppl_params_valid, lppl_params_total,
        lppl_tc_distribution, lppl_m_distribution,
        overall_sharpe, rolling_sharpes
    )

    report_path = Path('docs/DEEP_ANALYSIS_REPORT_2012_2025.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n报告已保存至: {report_path}")
    print("\n" + "=" * 80)
    print("实验完成")
    print("=" * 80)


def generate_deep_report(
    window_stats, benchmark_returns, all_signals, all_trades,
    lppl_valid, lppl_total, tc_dist, m_dist, overall_sharpe, rolling_sharpes
):
    """生成深度分析报告"""

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
    lines.append("### 3.1 总体夏普比率")
    lines.append("")
    lines.append(f"- **总体夏普比率**: {overall_sharpe:.2f}")
    lines.append(f"- **无风险利率**: 2% (年化)")
    lines.append(f"- **持有期**: 20 个交易日")
    lines.append("")

    if rolling_sharpes:
        lines.append("### 3.2 滚动夏普比率（窗口=100）")
        lines.append("")
        lines.append(f"- **均值**: {np.mean(rolling_sharpes):.2f}")
        lines.append(f"- **标准差**: {np.std(rolling_sharpes):.2f}")
        lines.append(f"- **最小值**: {np.min(rolling_sharpes):.2f}")
        lines.append(f"- **最大值**: {np.max(rolling_sharpes):.2f}")
        lines.append("")

    # 4. 算法正确性验证
    lines.append("## 四、算法正确性验证")
    lines.append("")
    lines.append("### 4.1 LPPL 参数验证")
    lines.append("")
    lines.append(f"- **有效参数比例**: {lppl_valid}/{lppl_total} ({lppl_valid/lppl_total*100:.1f}%)")
    lines.append(f"- **tc 分布**: 均值={np.mean(tc_dist):.1f}, 中位数={np.median(tc_dist):.1f}, 标准差={np.std(tc_dist):.1f}")
    lines.append(f"- **m 分布**: 均值={np.mean(m_dist):.3f}, 中位数={np.median(m_dist):.3f}, 标准差={np.std(m_dist):.3f}")
    lines.append("")

    lines.append("### 4.2 LPPL 参数合理性标准")
    lines.append("")
    lines.append("| 参数 | 合理范围 | 当前均值 | 评价 |")
    lines.append("|------|----------|----------|------|")
    lines.append(f"| m (缩放指数) | 0.1 ~ 0.9 | {np.mean(m_dist):.3f} | {'✓ 合理' if 0.1 < np.mean(m_dist) < 0.9 else '⚠ 异常'} |")
    lines.append(f"| tc (临界时间) | > 当前时间 | {np.mean(tc_dist):.1f} 天 | {'✓ 合理' if np.mean(tc_dist) > 0 else '⚠ 异常'} |")
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

    # 7. 因子分析
    lines.append("## 七、因子分析")
    lines.append("")

    factor_names = ['momentum_20d', 'rsi_14', 'volatility_20d', 'ma_ratio_5_20']
    lines.append("| 因子 | 均值 | 标准差 | 与收益相关系数 |")
    lines.append("|------|------|--------|----------------|")

    for factor_name in factor_names:
        factor_values = [getattr(s.factors, factor_name) for s in all_signals]
        returns = [all_trades[i].return_pct for i in range(min(len(all_trades), len(factor_values)))]

        if len(factor_values) > 0 and len(returns) > 0:
            correlation = np.corrcoef(factor_values[:len(returns)], returns)[0, 1]
            lines.append(f"| {factor_name} | {np.mean(factor_values):.4f} | {np.std(factor_values):.4f} | {correlation:.4f} |")

    lines.append("")

    # 8. 最佳与最差交易
    lines.append("## 八、最佳与最差交易")
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

    # 9. 结论
    lines.append("## 九、结论与建议")
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
