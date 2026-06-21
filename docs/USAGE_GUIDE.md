# UniQuant 使用指南

> 基于 179 文件 / 42,549 LOC 实测输出 | 2026-05-28

---

## 目录

1. [数据管道](#1-数据管道)
2. [技术指标](#2-技术指标)
3. [分析引擎](#3-分析引擎)
4. [因子系统](#4-因子系统)
5. [信号系统](#5-信号系统)
6. [风险管理](#6-风险管理)
7. [回测与策略](#7-回测与策略)
8. [服务层与 DI 容器](#8-服务层与-di-容器)
9. [A 股交易约束](#9-a-股交易约束)
10. [端到端工作流](#10-端到端工作流)

---

## 1. 数据管道

### 1.1 数据源

| 数据源 | 类 | 能力 |
|--------|---|------|
| mootdx 在线 | `MootdxOnlineSource` | 日线, 市值, 实时, 财务 |
| mootdx 本地 | `MootdxLocalSource` | 日线, 分钟线, 市值, 实时 |
| TDX | `TdxSource` | 日线, 市值, 实时 |
| 东方财富 | `EastMoneySource` | 日线, 财务, 行业 |
| 新浪 | `SinaSource` | 实时行情 |
| 腾讯 | `TencentSource` | 实时行情 |
| 同花顺 | `THsSource` | 日线, 实时 |
| Baostock | `BaostockSource` | 日线, 分钟线, 财务, 因子 |
| AkShare | (DataFetcher 包装) | 日线, ETF, 指数, 行业 |

### 1.2 DataFetcher — 统一数据入口

```python
from uniquant.data.data_fetcher import DataFetcher

fetcher = DataFetcher()

# 个股日线 (默认前复权)
df = fetcher.fetch_stock_daily("000001.SZ", "2025-01-01", "2025-12-31")

# 批量获取
dfs = fetcher.fetch_stocks_daily(
    ["000001.SZ", "600519.SH"], "2025-01-01", "2025-12-31"
)

# ETF / 指数
etf = fetcher.fetch_etf_daily_robust("510050.SH", "2025-01-01", "2025-12-31")
index = fetcher.fetch_index_daily("000001.SH", "2025-01-01", "2025-12-31")

# 实时行情
realtime = fetcher.fetch_stock_real_time()  # 全市场

# 行业概念
industries, concepts = fetcher.fetch_industry_concept_data()

# 交易日历
calendar = fetcher.get_trade_calendar("2025-01-01", "2025-12-31")
is_open = fetcher.is_trading_day(datetime.now())

# 股票代码列表
all_stocks = fetcher.fetch_all_stock_codes()
valid = fetcher.is_valid_symbol("600519.SH")
```

### 1.3 StorageManager — 本地数据湖 (Parquet)

```python
from uniquant.data.lake.storage_manager import StorageManager

lake = StorageManager(data_dir="./data")

# 读写
lake.write_data("000001.SZ", df, data_type="daily")
df2 = lake.read_data("000001.SZ", data_type="daily")

# 周线/月线合成
weekly = lake.synthesize_weekly("000001.SZ")
monthly = lake.synthesize_monthly("000001.SZ")

# 管理
symbols = lake.list_symbols()
stats = lake.get_symbol_stats()
```

### 1.4 DataImporter — 数据导入

```python
from uniquant.data.services.data_importer import DataImporter

importer = DataImporter()

# 从 CSV 批量导入
importer.import_directory("/path/to/csv/files")
importer.import_daily_data(max_workers=4)

# 从 TDX day 文件导入
importer.import_tdx_directory("/path/to/tdx/day")
```

### 1.5 同步脚本

| 脚本 | 用途 | 数据来源 |
|------|------|---------|
| `sync_daily_mootdx.py` | 日线同步(断点续传) | mootdx → Parquet |
| `sync_minute_mootdx.py` | 1min/5min 分钟线同步 | mootdx → Parquet |
| `sync_financial_mootdx.py` | 财务数据同步(gpcw*.dat) | mootdx → Parquet |
| `sync_factors_mootdx.py` | 复权因子同步(gbbq) | mootdx → Parquet |
| `update_daily_data_akshare.py` | 日线更新(稳健版) | AkShare → Parquet |
| `update_daily_incremental.py` | 增量更新(断点续传) | AkShare → Parquet |

```bash
python src/uniquant/data/scripts/sync_daily_mootdx.py --symbol 000001.SZ
python src/uniquant/data/scripts/update_daily_incremental.py
```

---

## 2. 技术指标

```python
from uniquant.brain.indicators import Indicators

# 基础指标
ma20  = Indicators.calc_ma(df, window=20)       # 移动平均
ema12 = Indicators.calc_ema(df, window=12)       # 指数移动平均
rsi   = Indicators.calc_rsi(df, window=14)       # RSI
atr   = Indicators.calc_atr(df, window=14)       # ATR
macd  = Indicators.calc_macd(df)                 # MACD → macd/signal/hist
boll  = Indicators.calc_bollinger(df)            # 布林带 → upper/lower/mid

# 高级指标
vol_ratio = Indicators.calc_vol_ratio(df)         # 量比
turnover_z = Indicators.calc_turnover_z(df)       # 换手率 Z-Score
entropy  = Indicators.calc_market_entropy(df)     # 市场熵

# 一键全量计算
all_indicators = Indicators.calculate_all_indicators(df)
# 返回列: ma_5, ma_10, ma_20, ma_60, ema_12, ema_26,
#          rsi_14, macd_macd, macd_signal, macd_hist,
#          atr_14, boll_upper, boll_lower, boll_mid,
#          vol_ratio_20, turnover_z_20, market_entropy_60
```

---

## 3. 分析引擎

### 3.1 FSM 有限状态机

```python
from uniquant.brain.fsm.fsm import FSM

fsm = FSM(ma_short=5, ma_long=20, is_intraday=False)
result = fsm.infer_state(df)
# → {'state': FSMState.IDLE/BUY/SELL/HOLD,
#     'ma_short': ..., 'ma_long': ...,
#     'trend': 'bullish'/'bearish'}
```

### 3.2 CZSC 缠论引擎

```python
from uniquant.brain.czsc import CZSCEngine

czsc = CZSCEngine()
signals = czsc.get_czsc_signals(df)
# → { 'bi_count': 23, 'last_bi_direction': 'up',
#     'is_3rd_buy': False, 'czsc_signal': 'BUY',
#     'bottom_fractal': 98.5, 'czsc_bottom_price': 98.5,
#     'signals': {...} }

# 数据需要包含: open, high, low, close, volume, date(index)
```

### 3.3 LPPL 泡沫检测

```python
from uniquant.brain.lppl import LPPLCalculator, LPPLVisualizer, LPPLDataManager

# 拟合
calc = LPPLCalculator()
result = calc.fit(df, column='close')
# → { 'converged': True/False, 'tc': 352.0,
#     'm': 0.35, 'w': 8.2, 'omega': 6.5,
#     'confidence': 0.72, 'is_bubble': False,
#     'risk_level': 'Safe', 'days_to_tc': 100 }

# 可视化
viz = LPPLVisualizer()
chart_path = viz.visualize_fit(df, result, "上证指数")

# 数据管理
dm = LPPLDataManager()
clean = dm.clean_data(df)
fetched = dm.fetch_data('000001.SH', '上证指数')
```

### 3.4 NTF 非线性趋势过滤

```python
from uniquant.brain.ntf.ntf_engine import NTFEngine

ntf = NTFEngine()

# 检测干预/巨量异动
intervention = ntf.detect_intervention(etf_df)
# → { 'intervention_detected': True, 'window': 20,
#     'date': '2025-06-15', 'signal': 'SELL' }

# 全市场扫描巨量信号
giants = ntf.scan_for_giants(market_data_dict)
```

### 3.5 RegimeDetector 市场状态

```python
from uniquant.brain.regime.regime_detector import RegimeDetector

detector = RegimeDetector()

# 单次检测
regime = detector.detect(df)
# → Regime(name='NORMAL'/'HIGH_VOL'/'LOW_VOL'/'TRENDING'/'RANGING',
#          volatility=0.15, trend_strength=0.6, ...)

# 汇总报告
summary = detector.get_summary(df)
# → { 'regime': 'NORMAL', 'entropy': 0.85,
#     'turnover_z': 0.5, 'volatility': 0.15 }
```

### 3.6 AnalysisEngineFactory

```python
from uniquant.services.analysis.engine_factory import AnalysisEngineFactory

class DummyOrchestrator:
    def get_data(self, *a, **kw): return None

factory = AnalysisEngineFactory(DummyOrchestrator())

# 9 个注册引擎:
factory.fsm       # → FSMEngine
factory.czsc      # → CZSCEngine
factory.lppl      # → LPPLAnalysisEngine
factory.ntf       # → NTFEngine
factory.regime    # → RegimeEngine
factory.macro     # → MacroService
factory.report    # → ReportGeneratorEngine
factory.brain     # → DecisionBrain
```

---

## 4. 因子系统

### 4.1 FactorRegistry — 因子注册

```python
from uniquant.brain.factors import FactorRegistry

registry = FactorRegistry()
# 启动时自动注册 10 个内置因子:
#   momentum_20d, momentum_60d (动量)
#   volatility_20d, volatility_60d (波动率)
#   ma_ratio_5_20, ma_ratio_10_60 (均线比)
#   volume_ratio_5_20 (量比)
#   rsi_14 (RSI)
#   price_position_20d (价格位置)
#   turnover_momentum_20d (换手动量)

# 列出所有因子
for f in registry.list_factors():
    print(f['name'], f['category'], f['weight'])
```

### 4.2 FactorAnalyzer — 因子计算

```python
from uniquant.brain.factors import FactorAnalyzer

analyzer = FactorAnalyzer()

# 计算全部因子
factor_df = analyzer.compute_factors(df)
# → DataFrame with columns: momentum_20d, volatility_20d, ...

# IC / IR 分析
ic_series = analyzer.calculate_ic(factor_df, forward_returns)
ir = analyzer.calculate_ir(ic_series)
```

### 4.3 FactorComposer — 因子合成

```python
from uniquant.brain.factors import FactorComposer

composer = FactorComposer()
signal = composer.compose(factor_df)
# → 综合信号值 (加权合成)
```

### 4.4 自定义因子

```python
from uniquant.brain.factors.custom_factors import CustomFactorBase

class MyAlpha(CustomFactorBase):
    def calculate(self, df):
        return df['close'] / df['close'].rolling(20).mean() - 1

registry.register(MyAlpha(), name="my_alpha", weight=0.5)
```

---

## 5. 信号系统

### 5.1 SignalType — 27 种信号类型

```
趋势:    TREND_BULLISH, TREND_BEARISH, TREND_NEUTRAL
动量:    MOMENTUM_OVERBOUGHT, MOMENTUM_OVERSOLD, MOMENTUM_DIVERGENCE
波动率:  VOLATILITY_BREAKOUT, VOLATILITY_CONTRACTION
成交量:  VOLUME_SURGE, VOLUME_CLIMAX
形态:    PATTERN_BREAKOUT, PATTERN_REVERSAL, PATTERN_CONTINUATION
LPPL:    LPPL_BUBBLE, LPPL_CRASH, LPPL_NEGATIVE_BUBBLE
Wyckoff: WYCKOFF_ACCUMULATION, WYCKOFF_DISTRIBUTION, WYCKOFF_SPRING,
         WYCKOFF_UTAD, WYCKOFF_LPS, WYCKOFF_SOW
CZSC:    CZSC_BI_END, CZSC_ZHONGSHU_3RD, CZSC_TREND_EXHAUST
复合:    COMPOSITE_CONSENSUS, COMPOSITE_DIVERGENCE
```

### 5.2 创建与聚合信号

```python
from uniquant.signal import Signal, SignalType, SignalAggregator, SignalNormalizer

# 创建信号
s1 = Signal(
    type=SignalType.TREND_BULLISH,
    value=0.75,           # -1 到 +1
    weight=0.5,           # 权重
    confidence=0.8,       # 置信度
    source="indicators",  # 信号来源
)

# 批量聚合
aggregator = SignalAggregator()
consensus = aggregator.calculate_consensus([s1, s2])
# → SignalConsensus(
#     agreement_ratio=0.67,
#     consensus_direction=1,   # 1=涨, -1=跌, 0=中性
#     consensus_confidence=0.7,
#     total_sources=2,
#     agreeing_sources=1
#   )

# 归一化外部信号
normalizer = SignalNormalizer()
signal = normalizer.normalize({'type': 'BUY', 'strength': 0.8})

# 质量评估
from uniquant.signal.quality import SignalQualityAssessor
qa = SignalQualityAssessor()
hit_rate = qa.calculate_hit_rate(signals, price_data)
```

---

## 6. 风险管理

### 6.1 DrawdownAnalyzer — 回撤分析

```python
from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer
import numpy as np

dd = DrawdownAnalyzer()

# 回撤序列
drawdown_series = dd.compute_drawdown_series(equity_array)

# 完整回撤分析
metrics = dd.analyze_drawdown(equity_array, annual_return=0.12)
# → DrawdownMetrics(max_drawdown, avg_drawdown, max_duration, ...)

# 尾部风险
tail = dd.analyze_tail_risk(returns_array)
# → TailRiskMetrics(var_95, cvar_95, tail_ratio, ...)

# 压力场景测试
stress = dd.stress_scenario(equity_array, "2008_crisis")
# → StressTestResult(scenario, max_dd, recovery_days, ...)

# 滚动最大回撤
rolling_mdd = dd.compute_rolling_mdd(equity_array, window=252)
```

### 6.2 EVTRisk — 极值风险

```python
from uniquant.risk.evt_risk import EVTRisk

evt = EVTRisk()

# 完整风险指标
metrics = evt.calculate_metrics(returns)
# → { 'var_95': -0.0077, 'cvar_95': -0.0095,
#     'max_drawdown': 0.15, 'skewness': -0.3,
#     'kurtosis': 3.5, 'regime': 'NORMAL',
#     'ntf_signal': 'HOLD' }

# 分项计算
var_95 = evt.calculate_var(returns, confidence=0.95)
cvar_95 = evt.calculate_cvar(returns, confidence=0.95)
max_dd = evt.calculate_max_drawdown(returns)

# 相关性矩阵
corr = evt.calculate_correlation_matrix(
    {'000001': ret1, '600519': ret2}
)
```

### 6.3 PositionSizer — 仓位计算

```python
from uniquant.risk.sizer import PositionSizer

# 支持 capital= 或 initial_capital=
sizer = PositionSizer(capital=1_000_000, risk_pct=0.02)

# 计算仓位 (A股 T+1 惩罚自动应用)
pos = sizer.calculate_shares(
    price=15.0,
    stop_loss=14.0,      # 止损价
    market="CN",          # CN/US/HK → T+1 惩罚不同
    symbol="000001.SZ",
    czsc_bottom=13.8,    # 缠论底部 (可选)
    atr_stop=14.2,       # ATR 止损 (可选)
)
# → { '建议仓位': 16600, '资金占用': 249000,
#     '执行止损': 14.0, '风险敞口': 1.24,
#     '是否触发熔断': False, '修正仓位': 16600,
#     '入场区间': '14.93 - 15.08', ... }

# 兼容别名
pos2 = sizer.calculate_position(price=15.0, stop_loss=14.0)
pos3 = sizer.calculate_position_size(price=15.0, stop_loss=14.0)
```

### 6.4 PortfolioOptimizer — 组合优化

```python
from uniquant.risk.portfolio_optimizer import PortfolioOptimizer, OptimizerConfig

opt = PortfolioOptimizer(OptimizerConfig(
    risk_free_rate=0.03,     # 无风险利率
    max_weight=0.4,          # 个股权重上限
    min_weight=0.0,          # 个股权重下限
))

returns_df = pd.DataFrame({
    '茅台': ret1, '平安': ret2, '招行': ret3
})

# 风险平价
result = opt.optimize_risk_parity(returns_df)
# → { 'weights': {'茅台': 0.5, '平安': 0.3, '招行': 0.2},
#     'sharpe': 1.2, 'volatility': 0.15 }

# 均值-方差
mv = opt.optimize_mean_variance(returns_df, target='max_sharpe')

# 有效前沿
ef = opt.get_efficient_frontier(returns_df, n_points=20)

# 报告
report = opt.generate_report()
```

### 6.5 StructuralRiskManager — 结构性风险

```python
from uniquant.risk.structural import StructuralRiskManager

srm = StructuralRiskManager()

# 从相关性矩阵评估
corr = np.corrcoef(returns_df.T)
risk_matrix = srm.assess(corr)
# → { 'avg_correlation': 0.35, 'concentration': 0.2,
#     'systematic_risk': 0.5, 'idiosyncratic_risk': 0.3, ... }

context = srm.generate_structural_context(risk_matrix, overall_risk="中")
```

---

## 7. 回测与策略

### 7.1 BacktestEngine — 回测引擎

```python
from uniquant.hands.backtest import BacktestEngine

engine = BacktestEngine(
    initial_capital=1_000_000,
    commission_rate=0.0003,    # 万3
    stamp_duty_rate=0.0005,    # 万5
    slippage_rate=0.0005,      # 万5
    min_commission=5.0,        # 最低5元
)

# ── 单次回测 ──
def signal_generator(df, idx, state):
    """自定义信号函数: 接收当前数据、索引、状态, 返回操作指令"""
    if idx < 20:
        return {'action': 'HOLD'}
    ma5 = df['close'].rolling(5).mean().iloc[idx]
    ma20 = df['close'].rolling(20).mean().iloc[idx]
    rsi = Indicators.calc_rsi(df, 14).iloc[idx]
    has_pos = state.get('has_position', False)

    if not has_pos and ma5 > ma20 and rsi < 70:
        return {'action': 'BUY', 'shares': 1000}
    elif has_pos and (ma5 < ma20 or rsi > 80):
        return {'action': 'SELL', 'shares': state['shares']}
    return {'action': 'HOLD'}

result = engine.run_backtest(df, signal_generator, symbol="000001.SZ")
# → BacktestResult

# 回测结果
result.total_return     # 总收益率
result.sharpe_ratio     # 夏普比
result.win_rate         # 胜率
result.max_drawdown     # 最大回撤
result.profit_factor    # 盈亏比
result.total_trades     # 总交易次数
result.avg_win          # 平均盈利
result.avg_loss         # 平均亏损
result.avg_holding_days # 平均持仓天数
result.final_capital    # 最终资金

# 导出
report_text = result.generate_report()
result_df = result.to_dataframe()  # 逐笔交易明细
result_dict = result.to_dict()     # 结构化指标

# ── 滚动回测 ──
rolling_results = engine.run_rolling_backtest(
    df, signal_generator, train_window=252, test_window=63
)

# ── 压力测试 ──
stress_results = engine.run_stress_test(
    df, signal_generator,
    scenarios=["2008", "2015", "2020"]
)

# ── Walk-Forward 分析 ──
wf_results = engine.run_walk_forward(
    df, lambda: signal_generator,
    train_window=252, test_window=63
)

# ── 手动交易执行 ──
engine.execute_buy(price=10.0, shares=1000, timestamp=now,
                   reason="均线金叉", symbol="000001.SZ")
engine.execute_sell(price=10.5, shares=1000, timestamp=now,
                    reason="达到止盈", symbol="000001.SZ")

# ── 重置 ──
engine.reset()
```

### 7.2 内置策略

```python
from uniquant.hands.strategies import STRATEGY_MAP

# 查看所有已注册策略
print(STRATEGY_MAP.keys())
# → dict_keys(['fsm', 'wyckoff', 'regime', 'reversal', 'ma_atr'])

# 每个策略的 __init__ 签名:
#   FSMStrategy(*args, **kwargs)
#   WyckoffStrategy(*args, **kwargs)
#   RegimeStrategy(*args, **kwargs)
#   ReversalStrategy(*args, **kwargs)
#   MaAtrStrategy(*args, **kwargs)
```

### 7.3 自定义策略

```python
from uniquant.hands.strategies import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.ma_short = 5
        self.ma_long = 20

    def start(self):
        pass

    def stop(self):
        pass

    def calculate_position_size(self, stop_price):
        return 1000

    def notify_order(self, order):
        pass

    def notify_trade(self, trade):
        pass

    def log(self, txt, dt=None):
        print(f"{dt}: {txt}")
```

### 7.4 Reporter / ResultsManager

```python
from uniquant.hands.reporter import Reporter
from uniquant.hands.results_manager import ResultsManager

# 生成策略报告
reporter = Reporter()
report_path = reporter.generate(result, format="html")  # 或 pdf, md

# 管理历史结果
manager = ResultsManager()
manager.save(result, strategy_name="fsm", symbol="000001.SZ")
history = manager.list_results()
```

---

## 8. 服务层与 DI 容器

### 8.1 ServiceContainer — 依赖注入

```python
from uniquant.services import ServiceContainer

container = ServiceContainer.instance()
container.initialize()

# 获取服务
data_svc = container.get('data_service')
scan_svc = container.get('scan_pipeline')
health_svc = container.get('health_service')
portfolio_svc = container.get('portfolio_service')
analysis_svc = container.get('analysis_service')
```

### 8.2 可用服务列表

| 服务 | 类 | 职责 |
|------|----|------|
| `data_service` | `DataService` | 数据获取与管理 |
| `scan_pipeline` | `ScanPipeline` | 全市场因子扫描 |
| `health_service` | `HealthService` | 系统健康检查 |
| `portfolio_service` | `PortfolioService` | 投资组合管理 |
| `analysis_service` | `AnalysisService` | 分析引擎编排 |
| `cache_coordinator` | `CacheCoordinator` | 缓存协调 |
| `validation_service` | `ValidationService` | 数据验证 |
| `data_access_service` | `DataAccessService` | 数据访问层 |
| `data_quality_service` | `DataQualityService` | 数据质量 |
| `stock_query_service` | `StockQueryService` | 股票查询 |
| `market_regime_service` | `MarketRegimeService` | 市场状态 |
| `report_service` | `ReportService` | 报表生成 |
| `signal_generation_service` | `SignalGenerationService` | 信号生成 |

---

## 9. A 股交易约束

| 约束 | 值 | 使用 |
|------|-----|------|
| 主板涨跌停 | ±10% | `check_limit_status(11.0, 10.0, '600519.SH')` |
| 科创/创业板 | ±20% | `check_limit_status(12.0, 10.0, '688001.SH')` |
| 北交所 | ±30% | `check_limit_status(13.0, 10.0, '830001.BJ')` |
| ST 股 | ±5% | `check_limit_status(10.5, 10.0, '600001.SH', name='ST宁通信')` |
| 佣金 | 万3 | `calculate_commission(10000)` → 5.0 (最低) |
| 印花税 | 万5 (卖方) | `calculate_stamp_tax(10000, is_buy=False)` → 5.0 |
| 最低佣金 | 5 元/笔 | `calculate_total_cost(10000, is_buy=False)` → 10.0 |
| 滑点 | 万5 | `DefaultSlippage().calculate_slippage(10.0, 10000)` |
| 交易时段 | 9:30-11:30, 13:00-15:00 | `MarketHours.is_market_open(dt)` |

### 9.1 板块规则

```python
from uniquant.shared.market_rules import BoardType, get_board_rule

rule = get_board_rule('600519')
print(rule.limit_pct, rule.lot_size, rule.price_collar_pct)
# → 0.1, 100, 0.005

for bt in BoardType:
    print(bt.name, bt.value)
# → MAIN_SH, MAIN_SZ, GEM, STAR, BEIJING, ST
```

### 9.2 涨跌停检查

```python
from uniquant.shared.limit_checker import check_limit_status, validate_trade_action

# 检查状态
status = check_limit_status(11.0, 10.0, '600519.SH')
status.is_limit_up   # True/False
status.is_limit_down # True/False
status.can_buy       # True/False (涨停不可买)
status.can_sell      # True/False (跌停不可卖)

# 验证交易动作
result = validate_trade_action('BUY', 11.0, 10.0, '600519.SH')
result['allowed']  # False (涨停)
result['reason']   # "涨停无法买入..."
```

---

## 10. 端到端工作流

### 10.1 完整流程

```python
import pandas as pd
import numpy as np
from datetime import datetime

from uniquant.data.data_fetcher import DataFetcher
from uniquant.brain.indicators import Indicators
from uniquant.brain.fsm.fsm import FSM
from uniquant.brain.czsc import CZSCEngine
from uniquant.brain.lppl import LPPLCalculator
from uniquant.brain.regime.regime_detector import RegimeDetector
from uniquant.risk.evt_risk import EVTRisk
from uniquant.risk.sizer import PositionSizer
from uniquant.signal import Signal, SignalType, SignalAggregator
from uniquant.hands.backtest import BacktestEngine

# 1. 获取数据
fetcher = DataFetcher()
df = fetcher.fetch_stock_daily("000001.SZ", "2025-01-01", "2025-12-31")

# 2. 计算指标
all_indicators = Indicators.calculate_all_indicators(df)
macd = Indicators.calc_macd(df)
rsi = Indicators.calc_rsi(df, 14).iloc[-1]

# 3. 分析引擎
fsm_state = FSM(5, 20).infer_state(df)['state']
czsc_signal = CZSCEngine().get_czsc_signals(df)['czsc_signal']
lppl_result = LPPLCalculator().fit(df)
regime = RegimeDetector().detect(df).name

# 4. 风险
returns = df['close'].pct_change().dropna()
risk = EVTRisk().calculate_metrics(returns)
sizer = PositionSizer(capital=1_000_000)
position = sizer.calculate_shares(price=df['close'].iloc[-1],
                                   stop_loss=df['close'].iloc[-1]*0.95)

# 5. 信号
signals = [
    Signal(SignalType.TREND_BULLISH, 0.7, 0.5, 0.8),
    Signal(SignalType.CZSC_BI_END, 0.3, 0.3, 0.6),
]
consensus = SignalAggregator().calculate_consensus(signals)

# 6. 回测
engine = BacktestEngine(initial_capital=1_000_000)

def my_strategy(df, idx, state):
    if idx < 20:
        return {'action': 'HOLD'}
    ma5 = df['close'].rolling(5).mean().iloc[idx]
    ma20 = df['close'].rolling(20).mean().iloc[idx]
    rsi_val = Indicators.calc_rsi(df, 14).iloc[idx]
    hp = state.get('has_position', False)
    if not hp and ma5 > ma20 and rsi_val < 70:
        return {'action': 'BUY', 'shares': 1000}
    elif hp and (ma5 < ma20 or rsi_val > 80):
        return {'action': 'SELL', 'shares': state['shares']}
    return {'action': 'HOLD'}

result = engine.run_backtest(df, my_strategy)
print(f"收益: {result.total_return:.2%}, "
      f"夏普: {result.sharpe_ratio:.2f}, "
      f"胜率: {result.win_rate:.1%}")
```

### 10.2 Streamlit 仪表盘

```bash
streamlit run src/uniquant/ui/dashboard.py
```

仪表盘包含 8 个标签页:
1. **宏观驾驶舱** — FSM 状态、反脆弱指标、结构风险
2. **策略扫描器** — 全市场因子扫描、SQL 选股、ETF 择时
3. **深度几何分析** — CZSC 结构、K 线图表、交易计划
4. **机会跟踪器** — 持仓管理、手工录入
5. **数据管理** — 同步下载、数据湖清单
6. **投研报表库** — 报表生成、预览、对比、RAG
7. **LPPL 泡沫分析** — 指数泡沫检测、可视化
8. **风险管理** — 风险指标、组合优化、压力测试、热力图
