# 策略开发指南

## 策略体系概览

UniQuant 的策略系统位于 `uniquant.hands.strategies` 模块，采用**注册表模式**管理所有策略。系统提供两种策略形态：

1. **信号生成函数 (signal_generator)**：轻量级函数，接收行情数据和日期，输出交易结果字典。用于回测扫描。
2. **BaseStrategy 类**：基于 Backtrader 框架的完整策略类，支持实时信号生成、仓位管理和订单追踪。

**核心协议：**

所有信号生成函数遵循统一的调用协议：

```python
def signal_generator(
    df: pd.DataFrame,           # 个股行情数据（含 date, open, high, low, close, volume）
    as_of_date: str,            # 信号日期
    cost_buy: Optional[float],  # 买入手续费率（可选）
    cost_sell: Optional[float], # 卖出手续费率（可选）
    csi: pd.DataFrame = None,   # 大盘指数数据（可选，用于市场状态判断）
    mode: str = "backtest",     # 运行模式: "backtest" / "live"
    **kwargs,                   # 扩展参数
) -> Optional[Dict]:
    # 返回 {"ret": 收益率(%), "days": 持有天数} 或 None（无信号）
```

---

## 策略注册表

`STRATEGY_MAP` 是策略的全局注册字典，定义在 `uniquant.hands.strategies.registry` 中：

```python
from uniquant.hands.strategies.ma_cross import trade_ma
from uniquant.hands.strategies.regime import trade_regime
from uniquant.hands.strategies.str_reversal import trade_str_reversal
from uniquant.hands.strategies.wyckoff import trade_wyckoff

STRATEGY_MAP = {
    "wyckoff": trade_wyckoff,
    "ma_atr": trade_ma,
    "ma_cross": trade_ma,
    "reversal": trade_str_reversal,
    "str_reversal": trade_str_reversal,
    "regime": trade_regime,
}
```

**说明：**

- `"ma_atr"` 和 `"ma_cross"` 是同一策略 `trade_ma` 的别名
- `"reversal"` 和 `"str_reversal"` 是同一策略 `trade_str_reversal` 的别名
- 键名对应 `config/trading.yaml` 中的策略配置名

### 添加自定义策略

```python
from uniquant.hands.strategies.registry import STRATEGY_MAP

def my_strategy(df, as_of_date, **kwargs):
    # 策略逻辑
    return {"ret": 2.5, "days": 10}

STRATEGY_MAP["my_strategy"] = my_strategy
```

---

## BaseStrategy

`BaseStrategy` 是基于 Backtrader 的策略基类，提供订单管理、交易日志和仓位计算等基础功能。

### 条件导入

系统通过条件导入支持 Backtrader 的可选依赖：

```python
try:
    import backtrader as bt
    HAS_BACKTRADER = True
except ImportError:
    HAS_BACKTRADER = False
```

当 Backtrader 未安装时，`BaseStrategy` 退化为 Mock 实现，仅提供日志输出功能。

### 核心参数

```python
params = (
    ("verbose", True),      # 是否输出详细日志
    ("risk_pct", 0.05),     # 单次交易风险比例
    ("stop_atr_n", 2.0),    # ATR 止损倍数
)
```

### 关键方法

| 方法 | 说明 |
|------|------|
| `log(txt, dt)` | 输出带日期的策略日志 |
| `notify_order(order)` | 订单状态回调：处理成交、取消、拒绝等事件 |
| `notify_trade(trade)` | 交易完成回调：输出毛利润和净利润 |
| `calculate_position_size(stop_price)` | 根据止损价和风险比例计算仓位大小（依赖 PositionSizer） |
| `start()` | 策略启动回调 |
| `stop()` | 策略停止回调 |

### StrategyResult 数据类

```python
@dataclass
class StrategyResult:
    ret: float = 0.0          # 收益率 (%)
    days: int = 0             # 持有天数
    exit_reason: str = ""     # 退出原因
    entry_price: float = 0.0  # 入场价格
    exit_price: float = 0.0   # 出场价格
```

---

## 内置策略详解

### MA 交叉 (trade_ma)

**策略名称**：`ma_atr` / `ma_cross`

**策略逻辑**：基于快慢均线金叉/死叉的趋势跟踪策略。

- **快均线**：5 日移动平均线
- **慢均线**：20 日移动平均线
- **买入条件**：前一日快均线在慢均线下方，当日快均线上穿慢均线（金叉确认）
- **卖出条件**：快均线下穿慢均线（死叉），或持有超过 120 天
- **入场价**：金叉确认后次日开盘价
- **出场价**：死叉当日收盘价

**配置参数** (`config/trading.yaml`)：

```yaml
ma_atr:
  enabled: true
  fast_period: 5
  slow_period: 20
  atr_period: 20
  weight: 0.35
  min_score: 0.0
```

**函数签名**：

```python
def trade_ma(
    df: pd.DataFrame,
    as_of_date: str,
    cost_buy: Optional[float] = None,
    cost_sell: Optional[float] = None,
    csi: pd.DataFrame = None,
    mode: str = "backtest",
    **kwargs,
) -> Optional[Dict]:
    # 返回 {"ret": 收益率(%), "days": 持有天数} 或 None
```

---

### Wyckoff (trade_wyckoff)

**策略名称**：`wyckoff`

**策略逻辑**：基于 Wyckoff 方法论的多时间框架分析策略，通过 WyckoffEngine 识别吸筹/派发阶段的关键信号。

- **信号类型**：spring（弹簧效应）、breakout（突破）等，由 WyckoffEngine 自动检测
- **置信度等级**：A（最高）/ B / C / D（最低），默认最低要求 B 级
- **市场状态过滤**：熊市（bear）环境下不开仓
- **止损**：Wyckoff 分析提供的止损位，或默认入场价 * 0.93
- **止盈**：Wyckoff 目标位与 2 倍 ATR 目标位取较高者
- **跟踪止损**：持有 30 天后启动，止损线 = 最高价 - ATR 乘数 * ATR
- **半仓机制**：达到目标位时卖出一半，剩余用跟踪止损

**市场状态参数调整**：

| 市场状态 | ATR 乘数 | 时间止损 (天) | 最大持有 (天) |
|----------|----------|---------------|---------------|
| range (震荡) | 1.5 | 45 | 90 |
| bear (熊市) | 2.5 | 90 | 180 |
| bull (牛市) | 3.0 | 60 | 120 |
| unknown | 2.0 | 60 | 120 |

**配置参数**：

```yaml
wyckoff:
  enabled: true
  lookback_days: 400
  weekly_lookback: 120
  monthly_lookback: 40
  weight: 0.30
  score_threshold: 0.45
  min_score: 0.0
  min_confidence_level: "B"
```

**退出原因**：

| 退出原因 | 说明 |
|----------|------|
| `stop_loss` | 触及止损价 |
| `gap_stop_loss` | 跳空低于止损价 |
| `trailing_stop` | 跟踪止损 |
| `time_stop` | 持有时间超过时间止损限制 |
| `max_hold` | 持有到最大天数 |
| `target_50pct+*` | 半仓止盈后剩余仓位的退出原因 |

---

### Regime (trade_regime)

**策略名称**：`regime`

**策略逻辑**：市场状态感知策略，仅在牛市环境中交易。

- **市场状态判断** (`get_regime()`)：
  - **bull（牛市）**：当前价 > 120 日均线 * 1.02 且 60 日均线 > 120 日均线
  - **bear（熊市）**：当前价 < 120 日均线 * 0.98
  - **range（震荡）**：其他情况
- **买入条件**：仅当大盘为 `bull` 状态时开仓
- **持有期**：固定 20 个交易日
- **入场价**：当日收盘价
- **出场价**：20 日后收盘价

**配置参数**：

```yaml
regime:
  enabled: true
  weight: 0.15
```

**函数签名**：

```python
def trade_regime(
    df: pd.DataFrame,
    as_of_date: str,
    cost_buy: Optional[float] = None,
    cost_sell: Optional[float] = None,
    csi: pd.DataFrame = None,   # 大盘指数数据（必须提供以判断市场状态）
    **kwargs,
) -> Optional[Dict]:
```

---

### 均值回归 (trade_str_reversal)

**策略名称**：`reversal` / `str_reversal`

**策略逻辑**：捕捉短期超跌反弹的均值回归策略。

- **入场条件**：近 5 日收益率 < -5%（显著下跌后做多）
- **入场价**：次日开盘价
- **持有期**：最长 5 个交易日
- **止盈**：入场价 + 2 倍 ATR（14 日 ATR）
- **止损**：入场价 - 2 倍 ATR
- **退出逻辑**：先触及止盈/止损者优先，否则持有到期按收盘价退出

**配置参数**：

```yaml
reversal:
  enabled: true
  lookback_days: 5
  threshold_pct: 5.0
  hold_days: 5
  take_profit_pct: 4.0
  stop_loss_pct: 4.0
  weight: 0.20
  min_score: 0.0
```

---

### FSM (FSMStrategy)

**策略名称**：FSMStrategy（Backtrader 策略类，非 signal_generator 函数）

**策略逻辑**：基于有限状态机（Finite State Machine）的趋势策略，使用 MA20/MA60 双均线系统。

- **SIGNAL 状态（突破入场）**：价格从 MA60 下方上穿 MA60
- **PROBE 状态（回踩入场）**：MA20 > MA60 且价格回踩至 MA20 附近（偏离 < 2%）
- **退出条件**：价格跌破 MA60

**策略参数**：

```python
params = (
    ("ma_short", 20),   # 短期均线周期
    ("ma_long", 60),    # 长期均线周期
)
```

**使用示例**（需安装 Backtrader）：

```python
import backtrader as bt
from uniquant.hands.strategies.fsm_strategy import FSMStrategy

cerebro = bt.Cerebro()
cerebro.addstrategy(FSMStrategy, ma_short=20, ma_long=60)
cerebro.adddata(data_feed)
cerebro.broker.setcash(100000.0)
results = cerebro.run()
```

---

## 自定义策略开发

### 开发步骤

#### 第 1 步：编写信号生成函数

```python
import pandas as pd
from typing import Dict, Optional
from uniquant.shared.cost_model import COST_BUY, COST_SELL


def trade_breakout(
    df: pd.DataFrame,
    as_of_date: str,
    cost_buy: Optional[float] = None,
    cost_sell: Optional[float] = None,
    csi: pd.DataFrame = None,
    mode: str = "backtest",
    **kwargs,
) -> Optional[Dict]:
    """
    突破策略：价格突破 N 日最高价时买入
    """
    # 实盘模式守卫
    if mode == "live":
        raise NotImplementedError("Live mode not yet implemented")

    a = pd.Timestamp(as_of_date)
    hist = df[df["date"] <= a].tail(30)

    if len(hist) < 20:
        return None

    # 买入条件：当日收盘价突破 20 日最高价
    current_close = float(hist.iloc[-1]["close"])
    high_20d = float(hist.tail(20)["high"].max())

    if current_close <= high_20d * 0.99:  # 需要明确突破
        return None

    # 模拟持有
    fut = df[df["date"] > a].head(10)
    if len(fut) < 5:
        return None

    entry = float(fut.iloc[0]["open"])
    exit_price = float(fut.iloc[-1]["close"])

    # 计算收益率（扣除手续费）
    ret = (exit_price - entry) / entry * 100
    cb = cost_buy if cost_buy is not None else COST_BUY
    cs = cost_sell if cost_sell is not None else COST_SELL
    ret -= (cb + cs) * 100

    return {"ret": round(ret, 2), "days": len(fut)}
```

#### 第 2 步：注册到策略表

```python
from uniquant.hands.strategies.registry import STRATEGY_MAP

STRATEGY_MAP["breakout"] = trade_breakout
```

#### 第 3 步：回测验证

```python
# 使用 STRATEGY_MAP 中的策略进行回测
strategy_func = STRATEGY_MAP["breakout"]

# 对单只股票测试
result = strategy_func(
    df=stock_df,
    as_of_date="2024-06-01",
    mode="backtest",
)
if result:
    print(f"收益率: {result['ret']}%, 持有天数: {result['days']}")
else:
    print("无交易信号")
```

### 完整代码示例

以下是一个包含市场状态过滤和 ATR 止损的完整策略：

```python
import pandas as pd
import numpy as np
from typing import Dict, Optional
from uniquant.shared.cost_model import COST_BUY, COST_SELL
from uniquant.hands.strategies.indicators import calc_atr
from uniquant.hands.strategies.regime import get_regime


def trade_momentum_breakout(
    df: pd.DataFrame,
    as_of_date: str,
    cost_buy: Optional[float] = None,
    cost_sell: Optional[float] = None,
    csi: pd.DataFrame = None,
    mode: str = "backtest",
    **kwargs,
) -> Optional[Dict]:
    """
    动量突破策略
    - 市场状态过滤：仅牛市/震荡市交易
    - 入场条件：价格突破 20 日最高价 + 20 日动量为正
    - 止损：2 倍 ATR
    - 最大持有：20 天
    """
    if mode == "live":
        raise NotImplementedError("Live mode not yet implemented")

    # 市场状态过滤
    regime = get_regime(csi, as_of_date) if csi is not None else "unknown"
    if regime == "bear":
        return None

    a = pd.Timestamp(as_of_date)
    hist = df[df["date"] <= a].tail(30)
    if len(hist) < 25:
        return None

    # 入场条件
    current = float(hist.iloc[-1]["close"])
    high_20 = float(hist.tail(20)["high"].max())
    momentum = (current - float(hist.iloc[-20]["close"])) / float(hist.iloc[-20]["close"])

    if current < high_20 or momentum <= 0:
        return None

    # 模拟交易
    fut = df[df["date"] > a].head(20)
    if len(fut) < 5:
        return None

    entry = float(fut.iloc[0]["open"])
    atr = calc_atr(hist, 14) if len(hist) >= 15 else entry * 0.02
    if atr <= 0:
        atr = entry * 0.02
    stop_loss = entry - 2.0 * atr

    exit_price = entry
    days = 0
    for _, row in fut.iterrows():
        days += 1
        low = float(row["low"])
        if low <= stop_loss:
            exit_price = stop_loss
            break
        exit_price = float(row["close"])

    ret = (exit_price - entry) / entry * 100
    cb = cost_buy if cost_buy is not None else COST_BUY
    cs = cost_sell if cost_sell is not None else COST_SELL
    ret -= (cb + cs) * 100

    return {"ret": round(ret, 2), "days": days}


# 注册策略
from uniquant.hands.strategies.registry import STRATEGY_MAP
STRATEGY_MAP["momentum_breakout"] = trade_momentum_breakout
```

---

## 策略配置

策略参数在 `config/trading.yaml` 的 `strategies` 部分配置：

```yaml
strategies:
  wyckoff:
    enabled: true                  # 是否启用
    lookback_days: 400             # Wyckoff 分析回看天数
    weekly_lookback: 120           # 周线回看天数
    monthly_lookback: 40           # 月线回看天数
    weight: 0.30                   # 综合评分权重
    score_threshold: 0.45          # 最低得分阈值
    min_score: 0.0                 # 最低分数
    min_confidence_level: "B"      # 最低置信度等级 (A/B/C/D)

  ma_atr:
    enabled: true
    fast_period: 5                 # 快均线周期
    slow_period: 20                # 慢均线周期
    atr_period: 20                 # ATR 周期
    weight: 0.35
    min_score: 0.0

  reversal:
    enabled: true
    lookback_days: 5               # 回看天数
    threshold_pct: 5.0             # 跌幅阈值 (%)
    hold_days: 5                   # 持有天数
    take_profit_pct: 4.0           # 止盈比例 (%)
    stop_loss_pct: 4.0             # 止损比例 (%)
    weight: 0.20
    min_score: 0.0

  regime:
    enabled: true
    weight: 0.15                   # 综合评分权重
```

**配置说明：**

| 参数 | 说明 |
|------|------|
| `enabled` | 策略是否参与扫描和评分 |
| `weight` | 策略在综合评分中的权重（所有策略权重之和无需为 1，系统内部归一化） |
| `min_score` | 策略最低通过分数 |
| `min_confidence_level` | Wyckoff 专用，信号最低置信度 |

**执行参数** (`config/trading.yaml` 的 `execution` 部分)：

```yaml
execution:
  broker: "simulator"
  slippage_pct: 0.1               # 滑点比例 (%)
  initial_capital: 100000.0       # 初始资金
  buy_fee_pct: 0.0003             # 买入手续费率
  sell_fee_pct: 0.0003            # 卖出手续费率
  min_commission: 5.0             # 最低佣金
```

---

## 策略验证

UniQuant 提供三种回测验证方式，适用于不同的验证需求。

### 单次回测 (run_backtest)

对固定时间段进行一次性回测：

```python
from uniquant.hands.strategies.registry import STRATEGY_MAP

strategy = STRATEGY_MAP["wyckoff"]

# 遍历多个日期测试
results = []
for date in test_dates:
    result = strategy(
        df=stock_df,
        as_of_date=date,
        csi=csi_df,
        mode="backtest",
    )
    if result:
        results.append(result)

# 统计表现
if results:
    avg_ret = sum(r["ret"] for r in results) / len(results)
    avg_days = sum(r["days"] for r in results) / len(results)
    win_rate = sum(1 for r in results if r["ret"] > 0) / len(results)
    print(f"平均收益: {avg_ret:.2f}%, 平均持有: {avg_days:.0f}天, 胜率: {win_rate:.2%}")
```

### 滚动回测 (run_rolling_backtest)

在多个时间窗口上滚动回测，检验策略在不同市场环境下的稳定性：

```python
import pandas as pd

def run_rolling_backtest(df, strategy_func, start_date, end_date, step_days=5, csi=None):
    """
    滚动回测
    """
    dates = pd.bdate_range(start_date, end_date, freq=f"{step_days}B")
    results = []

    for date in dates:
        date_str = date.strftime("%Y-%m-%d")
        result = strategy_func(
            df=df,
            as_of_date=date_str,
            csi=csi,
            mode="backtest",
        )
        if result:
            result["date"] = date_str
            results.append(result)

    return pd.DataFrame(results)


# 使用示例
rolling_results = run_rolling_backtest(
    df=stock_df,
    strategy_func=STRATEGY_MAP["ma_cross"],
    start_date="2023-01-01",
    end_date="2024-12-31",
    step_days=5,
    csi=csi_df,
)
print(rolling_results.describe())
```

### Walk-Forward 验证 (run_walk_forward)

结合因子系统的 Walk-Forward 管道进行策略验证，确保策略参数在样本外环境中依然有效：

```python
from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline
from uniquant.brain.factors.composer import FactorComposer

# 使用 Walk-Forward 管道验证因子驱动的策略
pipeline = WalkForwardFactorPipeline(
    train_window=504,
    test_window=63,
)

# 运行 walk-forward 验证
wf_result = pipeline.run(
    df=panel_df,
    factor_cols=["momentum_20d", "volatility_20d", "rsi_14"],
)

# 检查样本外表现
print(f"OOS IC Mean: {wf_result.oos_ic_mean:.4f}")
print(f"OOS ICIR: {wf_result.oos_icir:.4f}")
print(f"权重稳定性: {wf_result.weight_stability}")

# 使用最终权重执行策略
final_weights = wf_result.final_weights
composer = FactorComposer()
scored_df = composer.compose_scores(df, ic_weights=final_weights)

# 根据 composite_score 排名选股
top_stocks = scored_df.nlargest(10, "composite_score")
```

**三种验证方式对比：**

| 方式 | 适用场景 | 前瞻偏差防护 | 计算成本 |
|------|----------|--------------|----------|
| 单次回测 | 快速测试策略逻辑 | 低 | 低 |
| 滚动回测 | 检验策略时间稳定性 | 中 | 中 |
| Walk-Forward | 严格样本外验证 | 高 | 高 |
