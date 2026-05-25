# 回测指南

本指南详细介绍 UniQuant 回测引擎的各种模式、配置选项和使用方法。

## 回测模式总览

UniQuant 提供四种回测模式，覆盖从基础验证到稳健性检验的完整流程：

| 模式 | 方法 | 说明 | 适用场景 |
|------|------|------|----------|
| 单资产回测 | `run_backtest()` | 对单只股票运行策略，逐K线生成信号 | 策略原型验证、快速迭代 |
| 滚动窗口回测 | `run_rolling_backtest()` | 按固定窗口滚动切片，分段回测 | 策略在不同市场周期的表现评估 |
| Walk-Forward 验证 | `run_walk_forward()` | 训练-测试滚动推进，使用工厂函数 | 防止过拟合、样本外验证 |
| 压力测试 | `run_stress_test()` | 在极端历史场景下测试策略表现 | 风险评估、极端行情承受能力 |

所有模式均通过 `UnifiedMatchingEngine` 统一撮合引擎执行，强制遵循 A 股 T+1、涨跌停、印花税等约束。

## 单资产回测

单资产回测是最基本的回测模式。通过 `run_backtest()` 方法运行：

```python
result = engine.run_backtest(
    df=df,                          # K线数据 DataFrame
    signal_generator=my_signal,     # 信号生成函数
    symbol="600036",                # 股票代码
    position_size=1000,             # 每次交易股数
)
```

### 信号生成器约定

`signal_generator` 是一个可调用对象，其签名和返回值必须遵循以下约定：

```python
def signal_generator(
    df_slice: pd.DataFrame,   # 截至当前K线的历史数据切片 df.iloc[:idx+1]
    idx: int,                  # 当前K线索引
    context: dict,             # 当前状态 {"position", "position_cost", "cash"}
) -> dict:
    """
    返回值格式:
    {
        "action": "BUY" | "SELL" | "HOLD",
        "reason": "信号原因描述"
    }
    """
```

关键行为说明：

- 信号在当前K线收盘时生成，交易在下一根K线的开盘价执行（避免未来数据偏差）
- `BUY` 信号仅在空仓时触发，`SELL` 信号仅在持仓时触发
- `context` 包含当前持仓、成本和可用资金，可用于仓位管理逻辑

### 完整代码示例

```python
import pandas as pd
from uniquant.hands.backtest.engine import BacktestEngine
from uniquant.data.data_fetcher import DataFetcher

fetcher = DataFetcher(data_dir="./data")
df = fetcher.fetch_stock_daily("600036", "2023-01-01", "2024-12-31", adjust="qfq")

def rsi_signal(df_slice: pd.DataFrame, idx: int, context: dict) -> dict:
    """RSI 超买超卖策略"""
    if len(df_slice) < 15:
        return {"action": "HOLD", "reason": "数据不足"}

    close = df_slice["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 0
    rsi = 100 - (100 / (1 + rs))

    if rsi < 30:
        return {"action": "BUY", "reason": f"RSI={rsi:.1f} 超卖"}
    elif rsi > 70:
        return {"action": "SELL", "reason": f"RSI={rsi:.1f} 超买"}
    return {"action": "HOLD", "reason": f"RSI={rsi:.1f}"}

engine = BacktestEngine(initial_capital=100000.0)
result = engine.run_backtest(df=df, signal_generator=rsi_signal, symbol="600036", position_size=500)

print(f"总收益率: {result.total_return:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
print(f"最大回撤: {result.max_drawdown:.2%}")
```

## 组合回测

`PortfolioEngine` 支持同时持有多只股票，并通过 `UnifiedMatchingEngine` 批量撮合：

```python
from uniquant.hands.backtest.portfolio_engine import PortfolioEngine

portfolio = PortfolioEngine(
    initial_capital=500000.0,      # 初始资金 50万
    max_positions=5,               # 最大同时持仓数
    commission_rate=0.0003,        # 佣金 万3
    stamp_duty_rate=0.0005,        # 印花税 万5
    slippage_rate=0.001,           # 滑点 千1
    min_commission=5.0,            # 最低佣金 5元
    risk_free_rate=0.03,           # 无风险利率 3%
)
```

### 批量开仓与平仓

`PortfolioEngine` 提供向量化的批量操作接口：

```python
import pandas as pd

# 信号字典: 正值表示买入信号，负值表示卖出信号
buy_signals = {"600036": 1.0, "000001": 0.8, "601318": 1.2}
sell_signals = {"600036": -1.0, "000001": -0.5}

# 当前价格和前收盘价
prices = {"600036": 35.5, "000001": 12.3, "601318": 48.7}
pre_closes = {"600036": 35.0, "000001": 12.1, "601318": 48.0}

timestamp = pd.Timestamp("2024-06-03")

# 批量开仓 -- 自动按 sizing_fraction 分配资金
opened = portfolio.batch_open_positions(
    signals=buy_signals,
    prices=prices,
    pre_closes=pre_closes,
    timestamps=timestamp,
    sizing_fraction=0.25,          # 每个标的分配可用资金的 25%
)
print(f"成功开仓 {len(opened)} 个标的")

# 检查是否还能开新仓位
if portfolio.can_open_new_position():
    print(f"当前持仓 {len(portfolio.positions)}/{portfolio.max_positions}")

# 批量平仓
closed_count = portfolio.batch_close_positions(
    signals=sell_signals,
    prices=prices,
    pre_closes=pre_closes,
    timestamps=pd.Timestamp("2024-06-05"),
)
print(f"成功平仓 {closed_count} 个标的")

# 更新权益曲线
equity = portfolio.update_equity(prices)
```

### 组合回测完整流程

```python
import pandas as pd
from uniquant.hands.backtest.portfolio_engine import PortfolioEngine
from uniquant.data.data_fetcher import DataFetcher

fetcher = DataFetcher(data_dir="./data")
symbols = ["600036", "000001", "601318", "000858", "600519"]

# 获取所有标的数据
all_data = fetcher.fetch_stocks_daily(symbols, "2024-01-01", "2024-12-31")

portfolio = PortfolioEngine(initial_capital=500000.0, max_positions=3)

# 假设你有一个生成每日信号的函数
def generate_daily_signals(all_data, date):
    """根据当日数据生成多标的信号 (示例简化版)"""
    signals = {}
    for sym, df in all_data.items():
        df_to_date = df[df["date"] <= date]
        if len(df_to_date) < 20:
            continue
        close = df_to_date["close"]
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        if ma5 > ma20:
            signals[sym] = 1.0   # 买入信号
        elif ma5 < ma20:
            signals[sym] = -1.0  # 卖出信号
    return signals

# 获取共同交易日序列
common_dates = sorted(set.intersection(*[set(df["date"]) for df in all_data.values()]))

for date in common_dates:
    signals = generate_daily_signals(all_data, date)
    prices = {sym: float(df[df["date"] == date]["close"].iloc[0])
              for sym, df in all_data.items() if date in df["date"].values}
    pre_closes = {sym: float(df[df["date"] == date]["open"].iloc[0])
                  for sym, df in all_data.items() if date in df["date"].values}

    buy_sigs = {s: v for s, v in signals.items() if v > 0}
    sell_sigs = {s: v for s, v in signals.items() if v < 0}

    if sell_sigs:
        portfolio.batch_close_positions(sell_sigs, prices, pre_closes, pd.Timestamp(date))
    if buy_sigs:
        portfolio.batch_open_positions(buy_sigs, prices, pre_closes, pd.Timestamp(date))

    portfolio.update_equity(prices)
```

## 滚动窗口回测

`run_rolling_backtest()` 将数据按固定窗口切片，在每个测试窗口上独立运行回测：

```python
from uniquant.hands.backtest.engine import BacktestEngine

engine = BacktestEngine(initial_capital=100000.0)

results = engine.run_rolling_backtest(
    df=df,
    signal_generator=ma_cross_signal,
    symbol="600036",
    position_size=1000,
    train_window=252,     # 训练窗口: 252 个交易日 (约1年)
    test_window=63,       # 测试窗口: 63 个交易日 (约1季度)
)

# results 是 List[BacktestResult]，每个元素对应一个测试窗口
for i, r in enumerate(results):
    print(f"窗口 {i+1}: 收益率={r.total_return:.2%}, "
          f"夏普={r.sharpe_ratio:.2f}, 回撤={r.max_drawdown:.2%}")
```

运行逻辑说明：

- 数据长度必须大于 `train_window + test_window`，否则返回空列表
- 从第 `train_window` 个交易日开始，每隔 `test_window` 天取一段测试数据
- 训练窗口仅用于确定起始位置，信号生成函数接收的是测试窗口内的数据
- 每个窗口独立运行 `run_backtest()`，引擎状态自动重置

## Walk-Forward 验证

Walk-Forward 验证在滚动回测的基础上引入"训练-测试"分离机制。关键区别在于：你需要提供一个 `signal_generator_factory`，它接收训练数据并返回一个新的信号生成器。

```python
def signal_generator_factory(train_df: pd.DataFrame):
    """
    工厂函数: 根据训练数据确定策略参数，
    返回一个适配该参数的信号生成器。
    """
    # 在训练集上优化参数
    close = train_df["close"]
    volatility = close.pct_change().std()

    # 根据波动率自适应调整均线周期
    short_period = 5 if volatility > 0.03 else 10
    long_period = 20 if volatility > 0.03 else 40

    def signal_generator(df_slice, idx, context):
        if len(df_slice) < long_period:
            return {"action": "HOLD", "reason": "数据不足"}

        ma_short = df_slice["close"].rolling(short_period).mean()
        ma_long = df_slice["close"].rolling(long_period).mean()

        if (len(ma_short) >= 2
            and ma_short.iloc[-1] > ma_long.iloc[-1]
            and ma_short.iloc[-2] <= ma_long.iloc[-2]):
            return {"action": "BUY", "reason": f"MA{short_period}上穿MA{long_period}"}

        if (len(ma_short) >= 2
            and ma_short.iloc[-1] < ma_long.iloc[-1]
            and ma_short.iloc[-2] >= ma_long.iloc[-2]):
            return {"action": "SELL", "reason": f"MA{short_period}下穿MA{long_period}"}

        return {"action": "HOLD", "reason": "无信号"}

    return signal_generator

engine = BacktestEngine(initial_capital=100000.0)

results = engine.run_walk_forward(
    df=df,
    signal_generator_factory=signal_generator_factory,
    symbol="600036",
    position_size=1000,
    train_window=252,     # 1年训练
    test_window=63,       # 1季度测试
)

for i, r in enumerate(results):
    print(f"Walk-Forward 窗口 {i+1}: 收益率={r.total_return:.2%}, "
          f"夏普={r.sharpe_ratio:.2f}")
```

运行逻辑说明：

- 从位置 0 开始，取 `[0:train_window]` 作为训练集、`[train_window:train_window+test_window]` 作为测试集
- 调用 `signal_generator_factory(train_df)` 获取该窗口专属的信号生成器
- 在测试集上运行 `run_backtest()`
- 窗口按 `test_window` 步长向前滑动
- 这种模式能有效检测策略是否存在过拟合问题

## 压力测试

`run_stress_test()` 在多个极端历史场景下测试策略的抗风险能力。它通过对价格数据施加冲击系数来模拟崩盘：

```python
engine = BacktestEngine(initial_capital=100000.0)

stress_results = engine.run_stress_test(
    df=df,
    signal_generator=ma_cross_signal,
    symbol="600036",
    position_size=1000,
    scenarios=None,       # None 表示使用全部内置场景
)

for scenario, result in stress_results.items():
    print(f"{scenario}: 收益率={result.total_return:.2%}, "
          f"回撤={result.max_drawdown:.2%}")
```

### 内置崩盘场景

系统在 `RiskCalculationConstants.CRASH_SCENARIOS` 中定义了 5 个内置场景：

| 场景名称 | 冲击幅度 | 模拟事件 |
|----------|----------|----------|
| `market_crash_2008` | -50% | 2008年全球金融危机 |
| `market_crash_2015` | -40% | 2015年A股股灾 |
| `flash_crash_2010` | -10% | 2010年闪崩 |
| `circuit_breaker_2020` | -7% | 2020年熔断 |
| `financial_crisis_2008` | -50% | 2008年金融危机（等同于 market_crash_2008） |

冲击方式是将全部 OHLC 价格乘以 `(1 + crash_pct)`。你也可以传入自定义场景列表：

```python
# 只测试特定场景
stress_results = engine.run_stress_test(
    df=df,
    signal_generator=ma_cross_signal,
    symbol="600036",
    scenarios=["market_crash_2015", "circuit_breaker_2020"],
)
```

## 统一撮合引擎

`UnifiedMatchingEngine` 是所有回测引擎（包括 `BacktestEngine` 和 `PortfolioEngine`）的底层执行组件。它以向量化方式强制执行 A 股市场的全部交易约束。

### 约束机制

| 约束 | 实现方式 |
|------|----------|
| **T+1 规则** | 检查买入日期与卖出日期，同日买入不可卖出 |
| **涨跌停限制** | 根据股票板块类型判定（主板 10%、创业板/科创板 20%、北交所 30%、ST 5%） |
| **最低佣金** | 单笔佣金不足 5 元按 5 元计算 |
| **印花税** | 仅在卖出时收取 |
| **非线性滑点** | 基础滑点 + 基于成交量比率的市场冲击（`0.001 * sqrt(vol_ratio)`，上限 2%） |
| **现金不足** | 买入时自动检查可用资金 |

### FillResult 解读

撮合引擎返回 `FillResult` 数据类，包含以下字段（均为 numpy 数组，支持批量操作）：

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray     # 实际成交股数
    exec_prices: np.ndarray         # 实际成交价格（含滑点）
    commissions: np.ndarray         # 佣金
    stamp_duties: np.ndarray        # 印花税（仅卖出有值）
    slippages: np.ndarray           # 滑点金额
    rejected_mask: np.ndarray       # 是否被拒绝 (True=被拒)
    t1_violation_mask: np.ndarray   # T+1违规标记
    limit_violation_mask: np.ndarray  # 涨跌停违规标记
    cash_shortfall_mask: np.ndarray   # 资金不足标记
```

当 `rejected_mask[i]` 为 `True` 时，可以通过 `t1_violation_mask`、`limit_violation_mask`、`cash_shortfall_mask` 判断拒绝原因。

## 交易成本配置

### 默认成本参数

回测引擎使用 `BacktestConstants` 中的默认值：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DEFAULT_INITIAL_CAPITAL` | 100,000.0 | 初始资金 10万元 |
| `DEFAULT_COMMISSION_RATE` | 0.0003 (万3) | 券商佣金率（双向收取） |
| `DEFAULT_STAMP_DUTY_RATE` | 0.001 (千1) | 印花税率（仅卖出） |
| `DEFAULT_SLIPPAGE_RATE` | 0.001 (千1) | 基础滑点率 |
| `DEFAULT_MIN_COMMISSION` | 5.0 | 单笔最低佣金（元） |

### 在引擎中覆盖

创建 `BacktestEngine` 或 `PortfolioEngine` 时直接传入自定义值：

```python
engine = BacktestEngine(
    initial_capital=500000.0,
    commission_rate=0.00025,       # 万2.5（券商优惠费率）
    stamp_duty_rate=0.0005,        # 万5（2024年新税率）
    slippage_rate=0.0005,          # 万5
    min_commission=5.0,
)
```

### CostConfig 配置类

系统还提供了 `CostConfig` 数据类，支持从环境变量或 YAML 文件加载成本配置：

```python
from uniquant.shared.cost_model import CostConfig

# 使用默认值
config = CostConfig()
print(f"买入成本: {config.cost_buy:.4%}")    # 0.0003 (万3)
print(f"卖出成本: {config.cost_sell:.4%}")    # 0.0008 (万3佣金 + 万5印花税)

# 从环境变量覆盖
# export LPPL_COST_BUY_FEE=0.00025
# export LPPL_COST_STAMP_TAX=0.0005
config_env = CostConfig.from_env()

# 从 YAML 文件加载
config_yaml = CostConfig.from_yaml("config/trading.yaml")
```

## 回测结果解读

`BacktestResult` 包含以下核心指标：

| 指标 | 字段名 | 说明 |
|------|--------|------|
| 初始资金 | `initial_capital` | 回测起始资金 |
| 最终资金 | `final_capital` | 回测结束时总权益 |
| 总收益率 | `total_return` | `(最终资金 - 初始资金) / 初始资金` |
| 年化收益率 | `annualized_return` | `(1 + 总收益率) ^ (252/交易天数) - 1` |
| 最大回撤 | `max_drawdown` | 从峰值到谷底的最大跌幅 |
| 夏普比率 | `sharpe_ratio` | `均值(日收益) / 标准差(日收益) * sqrt(252)` |
| 胜率 | `win_rate` | 盈利交易数 / 总交易数 |
| 盈亏比 | `profit_factor` | 总盈利 / 总亏损的绝对值 |
| 总交易次数 | `total_trades` | 完成的卖出交易数（不含未平仓） |
| 盈利交易数 | `winning_trades` | 盈亏大于 0 的交易数 |
| 亏损交易数 | `losing_trades` | 盈亏小于 0 的交易数 |
| 平均盈利 | `avg_win` | 盈利交易的平均盈利金额 |
| 平均亏损 | `avg_loss` | 亏损交易的平均亏损金额 |
| 平均持仓天数 | `avg_holding_days` | 每笔交易的平均持仓时间 |

此外，`BacktestResult` 还包含：

- `equity_curve` -- 每日权益曲线列表
- `daily_returns` -- 每日收益率列表
- `trades` -- 完整交易记录列表（`TradeRecord` 对象）
- `drawdown_metrics` -- 回撤详细分析（由 `DrawdownAnalyzer` 计算）
- `tail_risk_metrics` -- 尾部风险指标

可以将结果转为字典或 DataFrame 用于进一步分析：

```python
# 转为字典
result_dict = result.to_dict()

# 交易记录转为 DataFrame
trades_df = result.to_dataframe()
print(trades_df[["timestamp", "action", "price", "shares", "pnl", "reason"]])
```

## 常见陷阱

### 1. 未来数据偏差 (Lookahead Bias)

回测引擎已通过设计避免了最常见的未来数据偏差：信号在当前K线收盘时生成，交易在下一根K线的开盘价执行。但信号生成函数内部仍需注意：

- 不要使用 `df_slice` 之后的数据
- 避免在信号函数中使用当日的最高价/最低价作为入场判断（收盘时才能确认）
- 使用技术指标时注意指标本身是否包含前瞻计算

### 2. 数据不足

- 单次回测至少需要 2 根K线（引擎循环到 `len(df) - 1`）
- 滚动回测需要 `train_window + test_window` 根K线（默认 252 + 63 = 315）
- 技术指标计算需要额外的预热期（如 MA20 至少需要 20 根K线）
- 数据不足时引擎会打印警告并返回空结果，不会抛出异常

### 3. 交易成本模型偏差

- 默认成本参数基于 A 股 2024 年标准费率，历史回测应根据实际费率调整
- 印花税历史变化较大（2024 年前为千1，2024 年后为万5），长周期回测需注意切换
- 滑点对高频换手策略影响显著，建议针对具体品种校准 `slippage_rate`
- 撮合引擎的非线性滑点模型（基于成交量比率）比固定滑点更贴近真实交易

### 4. 过拟合风险

- 在单一时间段反复优化参数会导致严重过拟合
- 使用 `run_walk_forward()` 进行样本外验证是检测过拟合的有效手段
- 关注 Walk-Forward 各窗口结果的方差：如果训练期表现远好于测试期，说明存在过拟合
- 策略参数越少、逻辑越简洁，过拟合风险越低
- 使用 `run_stress_test()` 评估极端市场条件下策略是否依然稳健

### 5. A 股特殊规则

- **T+1**：当日买入的股票无法当日卖出，撮合引擎会自动拒绝违规卖出
- **涨跌停**：涨停时无法买入、跌停时无法卖出，撮合引擎通过 `limit_violation_mask` 标记
- **手数限制**：A 股最小交易单位为 100 股（1手），设置 `position_size` 时需为 100 的整数倍
- **停牌**：如果数据中存在停牌日（无成交），应提前过滤或标记
