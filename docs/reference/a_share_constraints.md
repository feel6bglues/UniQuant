# A 股约束详解

本文档描述 UniQuant 系统中针对 A 股市场特有约束的实现细节，涵盖 T+1 交割制度、涨跌停板、交易费用、手数限制、交易时间、撮合引擎执行流程，以及约束在系统各层之间的传播方式。

---

## T+1 交割制度

A 股市场实行 T+1 交割制度：当日买入的股票不能在当日卖出，最早在下一个交易日才可卖出。

### UnifiedMatchingEngine 中的实现

在 `src/uniquant/hands/backtest/unified_matching_engine.py` 的 `fill_sell()` 方法中，T+1 约束通过日期序数（ordinal）比较实现：

```python
buy_ord = np.array([
    pd.Timestamp(b).toordinal() if b is not None else 0
    for b in buy_dates
])
cur_ord = np.array([
    pd.Timestamp(t).toordinal() for t in timestamps
])
t1_violation = (cur_ord - buy_ord < 1) & (buy_ord > 0)
```

当卖出日期的 ordinal 值与买入日期的 ordinal 值之差小于 1（即同一日历日），且买入日期有效（`buy_ord > 0`），则标记为 T+1 违规。

### TradeCalendarManager 集成

序数比较之后，引擎还会逐笔检查买入日和卖出日是否为交易日：

```python
for i in range(n):
    if buy_dates[i] is not None:
        b_ts = pd.Timestamp(buy_dates[i])
        c_ts = pd.Timestamp(timestamps[i])
        if not self.trade_calendar.is_trading_day(b_ts) or \
           not self.trade_calendar.is_trading_day(c_ts):
            t1_violation[i] = True
```

若买入日或卖出日不是交易日（如周末、节假日），同样标记为 T+1 违规并拒绝成交。这确保了即使日历日差值满足要求，非交易日的卖出仍会被阻止。

### T+1 违规的影响

T+1 违规的订单进入 `rejected_mask`，最终执行股数被置为 0：

```python
rejected = limit_rejected | t1_violation | (shares_clamped <= 0)
# ...
executed_shares=np.where(rejected, 0, shares_clamped),
```

### PositionSizer 中的 1.2 倍隔夜惩罚

在 `src/uniquant/risk/sizer.py` 中，`PositionSizer` 通过 `market_penalties` 字典为不同市场设定风险惩罚系数：

```python
self.market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}  # T+1 penalty
```

CN 市场的惩罚系数为 1.2，意味着在计算仓位时，单位风险被放大 20%，以补偿 T+1 制度下无法当日止损的额外隔夜风险。

仓位计算公式：

```
建议股数 = 最大允许亏损 / (单位风险 * 惩罚系数)
```

其中：
- `最大允许亏损 = 资金 * risk_pct`
- `单位风险 = 入场价 - 执行止损价`
- `惩罚系数 = 1.2`（CN 市场）

对应源码：

```python
penalty = self.market_penalties.get(market, 1.0)
max_loss_allowed = safe_round(self.capital * self.risk_pct, PrecisionConstants.PRICE_DECIMALS)
shares = safe_divide(max_loss_allowed, risk_per_share * penalty, 0)
```

---

## 涨跌停板

A 股不同板块的涨跌停幅度不同。系统通过板块分类和价格比例计算来判断涨跌停状态。

### 板块分类 (get_board_type)

`get_board_type()` 定义于 `src/uniquant/shared/limit_checker.py`，根据股票代码前缀和名称识别板块类型。判断优先级如下：

1. ST 股（最高优先级）：检查股票名称是否以 `"ST"` 或 `"*ST"` 开头
2. 科创板：代码前缀 `688`
3. 创业板：代码前缀 `300` 或 `301`
4. 北交所：代码前缀 `8` 或 `4`
5. 主板（兜底）：代码前缀 `600`、`601`、`603`、`605`、`000`、`001`、`002`

这些前缀定义在 `MarketConstants.BOARD_PREFIX` 中：

```python
BOARD_PREFIX = {
    "st": ["ST", "*ST"],
    "sci_tech": ["688"],
    "gem": ["300", "301"],
    "beijing": ["8", "4"],
    "main": ["600", "601", "603", "605", "000", "001", "002"],
}
```

### 涨跌停比例

`MarketConstants.LIMIT_RATIO` 定义了各板块的涨跌停价格比例（相对于前收盘价）：

| 板块类型 | 板块名称 | 涨停比例 | 跌停比例 | 涨跌幅 |
|---|---|---|---|---|
| `"main"` | 主板 | 1.10 | 0.90 | +-10% |
| `"gem"` | 创业板 | 1.20 | 0.80 | +-20% |
| `"sci_tech"` | 科创板 | 1.20 | 0.80 | +-20% |
| `"st"` | ST 股 | 1.05 | 0.95 | +-5% |
| `"beijing"` | 北交所 | 1.30 | 0.70 | +-30% |

源码定义：

```python
LIMIT_RATIO = {
    "st": (1.05, 0.95),
    "sci_tech": (1.20, 0.80),
    "gem": (1.20, 0.80),
    "beijing": (1.30, 0.70),
    "main": (1.10, 0.90),
}
```

### 价格容差

为避免浮点精度问题，涨跌停判断引入了 0.001（0.1%）的容差：

```python
PRICE_TOLERANCE = 0.001
```

涨停判定：`price_ratio >= up_limit_ratio - tolerance`
跌停判定：`price_ratio <= down_limit_ratio + tolerance`

### LimitStatus 数据结构

`LimitStatus` 是涨跌停检查的返回结构：

```python
@dataclass
class LimitStatus:
    is_limit_up: bool       # 是否涨停
    is_limit_down: bool     # 是否跌停
    can_buy: bool           # 是否可买入（涨停时不可买）
    can_sell: bool          # 是否可卖出（跌停时不可卖）
    board_type: str         # 板块类型
    up_limit_price: float   # 涨停价格
    down_limit_price: float # 跌停价格
    price_ratio: float      # 当前价格/前收盘价
```

### UME 中的涨跌停执行流程

在 `UnifiedMatchingEngine` 中，涨跌停检查通过向量化方法 `compute_limit_status_vectorized()` 实现：

1. 计算价格比例：`price_ratios = prices / pre_closes`
2. 遍历所有板块类型，为每个板块生成掩码 `board_mask`
3. 对有效价格（`pre_closes > 0`）应用涨跌停阈值（含容差）

买入时检查涨停（涨停封板无法买入）：

```python
limit_rejected = limit_status["is_limit_up"]
```

卖出时检查跌停（跌停封板无法卖出）：

```python
limit_rejected = limit_status["is_limit_down"]
```

---

## 交易费用

### 佣金

- 标准费率：万3（0.03%，即 `0.0003`）
- 最低佣金：5 元人民币
- 买卖双向收取

定义于 `src/uniquant/shared/cost_model.py`：

```python
COMMISSION_PCT: float = 0.0003   # 万3
MIN_COMMISSION: float = 5.0      # 单笔最低5元
```

佣金计算公式：

```
佣金 = max(成交金额 * 佣金率, 最低佣金)
```

对应 UME 中的向量化实现：

```python
commissions = np.maximum(values * self.commission_rate, self.min_commission)
```

### 印花税

- 税率：万5（0.05%，即 `0.0005`）（2024 年新规）
- 仅卖出时收取
- 历史税率（2024 年前）：千1（0.1%，即 `0.001`）

```python
STAMP_TAX_PCT: float = 0.0005        # 万5 (2024+)
STAMP_TAX_PCT_OLD: float = 0.001     # 千1 (pre-2024)
```

卖出总费用率：

```
卖出费用率 = 佣金率 + 印花税率 = 0.0003 + 0.0005 = 0.0008 (万8)
```

在 UME 的 `fill_sell()` 中：

```python
stamp_duties = values * self.stamp_duty_rate
```

在 `fill_buy()` 中，印花税为零：

```python
stamp_duties=np.zeros(n),
```

### 滑点

系统使用基础滑点加市场冲击的非线性滑点模型。

基础滑点率定义：

```python
SLIPPAGE_PCT: float = 0.0005  # 万5
```

在 UME 的 `compute_execution_prices()` 中，滑点由两部分组成：

```python
vol_ratios = np.where(
    (avg_daily_volumes > 0) & (volumes > 0),
    np.minimum(volumes / np.maximum(avg_daily_volumes, 1e-8), 1.0),
    0.0,
)
impact = np.minimum(0.001 * np.sqrt(vol_ratios), 0.02)
total_slip = self.slippage_rate + impact
```

1. **基础滑点** (`slippage_rate`)：固定的万5（默认 `0.001`，由 `BacktestConstants.DEFAULT_SLIPPAGE_RATE` 决定）
2. **市场冲击** (`impact`)：与成交量占日均量比率的平方根成正比，上限 2%

完整公式：

```
vol_ratio = min(order_volume / avg_daily_volume, 1.0)
impact = min(0.001 * sqrt(vol_ratio), 0.02)
total_slippage = base_slippage + impact
exec_price = price * (1 + direction * total_slippage)
```

其中 `direction` 在买入时为 +1（执行价高于市价），卖出时为 -1（执行价低于市价）。

### CostConfig 汇总

`CostConfig` 数据类将所有费用参数封装在一起：

```python
@dataclass
class CostConfig:
    buy_fee_pct: float = 0.0003        # 买入佣金率 万3
    sell_fee_pct: float = 0.0003       # 卖出佣金率 万3
    stamp_tax_pct: float = 0.0005      # 印花税率 万5
    slippage_pct: float = 0.0005       # 滑点率 万5
    min_commission: float = 5.0        # 最低佣金 5元
```

提供两种外部配置方式：
- `CostConfig.from_env()`：从环境变量 `LPPL_COST_*` 加载
- `CostConfig.from_yaml()`：从 `config/trading.yaml` 的 `execution` 节加载

便捷属性：
- `cost_buy` -> `buy_fee_pct`（买入成本率）
- `cost_sell` -> `sell_fee_pct + stamp_tax_pct`（卖出成本率，含印花税）

### 滑点模型抽象层

`src/uniquant/shared/slippage_model.py` 还提供了面向对象的滑点模型抽象：

- `DefaultSlippage`：固定返回 0.001（0.1%）
- `DynamicSlippage`：基于流动性、ATR 波动率、市场冲击和时间衰减的动态模型

`DynamicSlippage` 中的时间衰减逻辑：

```python
def _time_decay(self, timestamp: datetime) -> float:
    minute = timestamp.hour * 60 + timestamp.minute
    if 570 <= minute <= 600 or 870 <= minute <= 900:
        return 0.0005
    return 0.0
```

在集合竞价时段（9:30-10:00 和 14:30-15:00）附加 0.05% 的额外滑点。

---

## 手数限制

A 股（CN 市场）的最小交易单位为 100 股（1 手），下单数量必须为 100 的整数倍。

在 `PositionSizer` 中：

```python
def _get_lot_size(self, market: str, symbol: str = "UNKNOWN") -> int:
    if market == "CN":
        return 100
    elif market == "US":
        return 1
    elif market == "HK":
        return 100
    return 1
```

向下取整到最近的整手数：

```python
shares = math.floor(safe_divide(shares, lot_size, 0)) * lot_size
```

在 UME 的 `fill_buy()` 中，现金不足时同样按整股向下取整：

```python
shares_adj = np.where(
    cash_shortfall & (cash_available > commissions),
    ((cash_available - commissions) / np.maximum(exec_prices, 1e-8)).astype(np.int64),
    shares_requested,
)
```

---

## 交易时间

A 股交易时间由 `MarketHours` 类定义于 `src/uniquant/shared/constants/market.py`：

| 时段 | 起始时间 | 结束时间 |
|---|---|---|
| 上午盘 | 09:30 | 11:30 |
| 午休 | 11:30 | 13:00 |
| 下午盘 | 13:00 | 15:00 |

交易日为周一至周五（`weekday` 0-4）。

```python
class MarketHours:
    MORNING_START_HOUR = 9
    MORNING_START_MINUTE = 30
    MORNING_END_HOUR = 11
    MORNING_END_MINUTE = 30
    AFTERNOON_START_HOUR = 13
    AFTERNOON_START_MINUTE = 0
    AFTERNOON_END_HOUR = 15
    AFTERNOON_END_MINUTE = 0
    TRADING_DAYS = [0, 1, 2, 3, 4]
```

提供的方法：

| 方法 | 描述 |
|---|---|
| `is_market_open(dt)` | 检查指定时间市场是否开放 |
| `get_next_open_time(dt)` | 获取下一个开盘时间 |
| `get_market_status(dt)` | 返回状态描述：`"交易中"` / `"休市(周末)"` / `"开盘前"` / `"已收盘"` / `"午休"` |

注意：`MarketHours` 只考虑周末休市，不包含法定节假日判断。法定节假日的处理依赖 `TradeCalendarManager`。

---

## 撮合引擎执行流程

`UnifiedMatchingEngine`（UME）定义于 `src/uniquant/hands/backtest/unified_matching_engine.py`，是系统中所有回测执行约束的集中实施点。

### 初始化参数

```python
class UnifiedMatchingEngine:
    def __init__(
        self,
        commission_rate: float = BacktestConstants.DEFAULT_COMMISSION_RATE,   # 0.0003
        stamp_duty_rate: float = 0.0005,
        min_commission: float = BacktestConstants.DEFAULT_MIN_COMMISSION,     # 5.0
        slippage_rate: float = BacktestConstants.DEFAULT_SLIPPAGE_RATE,       # 0.001
        trade_calendar: Optional[TradeCalendarManager] = None,
    ):
```

所有参数在初始化时通过 `assert` 进行范围校验。

### fill_buy 执行流程

输入参数：`prices`、`shares_requested`、`cash_available`、`pre_closes`、`symbols`、`timestamps`、`volumes`、`avg_daily_volumes`（均为 numpy 数组，长度为 n）。

**第 1 步：涨跌停检查**

```python
limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols)
limit_rejected = limit_status["is_limit_up"]
```

涨停股票被标记为拒绝买入。

**第 2 步：计算执行价格**

```python
exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=True)
```

买入方向滑点使得执行价高于市场价。

**第 3 步：计算费用**

```python
values = exec_prices * shares_requested
commissions = np.maximum(values * self.commission_rate, self.min_commission)
total_costs = values + commissions
```

买入不收印花税。

**第 4 步：现金不足调整**

```python
cash_shortfall = total_costs > cash_available
shares_adj = np.where(
    cash_shortfall & (cash_available > commissions),
    ((cash_available - commissions) / np.maximum(exec_prices, 1e-8)).astype(np.int64),
    shares_requested,
)
shares_adj = np.maximum(shares_adj, 0)
```

当现金不足但扣除最低佣金后仍有余额时，自动缩减买入股数。

**第 5 步：重算费用并返回**

以调整后的股数重新计算成交金额和佣金，构造 `FillResult` 返回：

```python
rejected_mask = limit_rejected | (shares_adj <= 0)
```

拒绝掩码 = 涨停拒绝 | 调整后股数为 0。

买入时 `t1_violation_mask` 始终为全 False（T+1 仅约束卖出）。

### fill_sell 执行流程

输入参数：`prices`、`shares_requested`、`positions_held`、`position_costs`、`pre_closes`、`symbols`、`timestamps`、`buy_dates`、`volumes`、`avg_daily_volumes`。

**第 1 步：涨跌停检查**

```python
limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols)
limit_rejected = limit_status["is_limit_down"]
```

跌停股票被标记为拒绝卖出。

**第 2 步：T+1 检查**

```python
buy_ord = np.array([
    pd.Timestamp(b).toordinal() if b is not None else 0
    for b in buy_dates
])
cur_ord = np.array([
    pd.Timestamp(t).toordinal() for t in timestamps
])
t1_violation = (cur_ord - buy_ord < 1) & (buy_ord > 0)
```

加上 `TradeCalendarManager` 的逐笔非交易日检查。

**第 3 步：卖出数量截断**

```python
shares_clamped = np.minimum(shares_requested, positions_held)
```

卖出数量不能超过持仓数量。

**第 4 步：计算执行价格和费用**

```python
exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=False)
values = exec_prices * shares_clamped
commissions = np.maximum(values * self.commission_rate, self.min_commission)
stamp_duties = values * self.stamp_duty_rate
```

卖出方向的滑点使得执行价低于市场价。卖出时收取印花税。

**第 5 步：综合拒绝掩码**

```python
rejected = limit_rejected | t1_violation | (shares_clamped <= 0)
```

三种拒绝原因取并集：跌停、T+1 违规、无有效股数。

被拒绝的订单执行股数置为 0：

```python
executed_shares=np.where(rejected, 0, shares_clamped),
```

### FillResult 返回结构

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray    # 实际成交股数
    exec_prices: np.ndarray        # 执行价格（含滑点）
    commissions: np.ndarray        # 佣金
    stamp_duties: np.ndarray       # 印花税
    slippages: np.ndarray          # 滑点金额
    rejected_mask: np.ndarray      # 综合拒绝掩码
    t1_violation_mask: np.ndarray  # T+1 违规掩码
    limit_violation_mask: np.ndarray  # 涨跌停违规掩码
    cash_shortfall_mask: np.ndarray   # 现金不足掩码
```

所有字段均为 numpy 数组，长度与输入一致，支持向量化后续处理。

---

## 约束在系统中的传播

A 股交易约束从常量定义出发，经过多个层级传播到最终的回测和组合引擎。

### 传播路径

```
shared/constants/ (MarketConstants, BacktestConstants, MarketHours)
    |
    +---> limit_checker.py (get_board_type, check_limit_status, LimitStatus)
    |         |
    |         +---> unified_matching_engine.py (UME)
    |
    +---> cost_model.py (CostConfig, COMMISSION_PCT, STAMP_TAX_PCT)
    |         |
    |         +---> unified_matching_engine.py (UME)
    |
    +---> slippage_model.py (DefaultSlippage, DynamicSlippage)
    |
    +---> sizer.py (PositionSizer, T+1 penalty, lot_size)
    |
    +---> trade_calendar_manager.py (TradeCalendarManager)
              |
              +---> unified_matching_engine.py (UME)
```

### 层级职责

**第 1 层：常量定义（shared/constants/）**

- `MarketConstants.LIMIT_RATIO`：涨跌停比例
- `MarketConstants.BOARD_PREFIX`：板块前缀
- `MarketConstants.PRICE_TOLERANCE`：价格容差
- `BacktestConstants.DEFAULT_COMMISSION_RATE`：默认佣金率（0.0003）
- `BacktestConstants.DEFAULT_STAMP_DUTY_RATE`：默认印花税率（0.001）
- `BacktestConstants.DEFAULT_SLIPPAGE_RATE`：默认滑点率（0.001）
- `BacktestConstants.DEFAULT_MIN_COMMISSION`：最低佣金（5.0）
- `MarketHours`：交易时间段

**第 2 层：约束检查器（limit_checker.py, cost_model.py, slippage_model.py）**

- `get_board_type()`：代码前缀到板块类型的映射
- `check_limit_status()`：单票涨跌停状态检查
- `validate_trade_action()`：交易动作可行性验证
- `CostConfig`：统一费用配置
- `SlippageModel`：滑点抽象

**第 3 层：撮合引擎（unified_matching_engine.py）**

`UnifiedMatchingEngine` 是所有 A 股约束的集中执行点。它从第 1 层和第 2 层获取约束参数，在 `fill_buy()` 和 `fill_sell()` 中统一实施：

- 涨跌停拒绝
- T+1 交割验证
- 非线性滑点计算
- 佣金（含最低佣金）和印花税扣除
- 现金不足自动缩减

**第 4 层：回测引擎（BacktestEngine / PortfolioEngine）**

回测引擎调用 UME 的 `fill_buy()` / `fill_sell()` 方法执行订单，并根据 `FillResult` 更新持仓、现金和净值。UME 的文档注释明确声明：

> 所有执行约束（T+1、涨跌停、印花税、最低佣金、非线性滑点）强制用于 BacktestEngine 和 PortfolioEngine

这意味着任何回测路径都无法绕过 UME 中实施的 A 股约束。

### 设计原则

1. **单一真相源**：所有常量集中在 `shared/constants/` 子包和 `cost_model.py` 中定义，避免各引擎自行定义导致不一致
2. **强制执行**：UME 作为唯一撮合入口，通过 `assert` 校验参数合法性，确保约束不被跳过
3. **向量化处理**：所有约束检查均支持 numpy 数组输入，避免逐笔 Python 循环带来的性能损耗（T+1 的非交易日检查是唯一例外，因为需要调用 `TradeCalendarManager`）
4. **掩码分离**：`FillResult` 分别暴露 `t1_violation_mask`、`limit_violation_mask`、`cash_shortfall_mask`，便于上层引擎分析拒绝原因
