# R2-B: Brain ↔ Hands 跨域对抗审计

> **审计范围**: Brain 层信号输出格式 vs Hands 层回测引擎消费契约
> **审计员**: R2-B Cross Auditor
> **日期**: 2026-06-06
> **输入审计**: R1-1B (LPPL), R1-1C (Wyckoff/CZSC/FSM), R1-1E (Matching Engine)

---

## 0. 审计摘要

| 维度 | 结论 |
|------|------|
| **Brain 输出格式统一性** | **CRITICAL** — FSM/Dict vs CZSC/Dict vs Wyckoff/dataclass 三套异构格式，无公共信号接口 |
| **信号消费契约兼容性** | **CRITICAL** — DecisionBrain 输出 action 值 ("EXECUTE_BUY") 与 BacktestEngine 期望 ("BUY") 不匹配 |
| **T+1 信号延迟正确性** | **HIGH** — BacktestEngine T+1 机制正确 (信号→次日开盘成交)，但 UnifiedMatchingEngine T+1 有边界缺陷 |
| **未来函数/前视偏差** | **HIGH** — signal_generator 接收完整 df（含未来数据），依赖调用者自律 |
| **两套撮合引擎语义等价性** | **HIGH** — T+1 检查、整手对齐、IPO 涨跌停均存在行为差异，不等价 |

---

## 1. Brain 引擎输出格式目录

### 1.1 FSM / DecisionBrain 输出

**来源**: `brain/fsm/fsm.py:DecisionBrain.make_decision()`
**返回类型**: `Dict[str, Any]`

```python
# fsm.py:238-253 — _build_response 标准格式
{
    "action": str,        # "BUY" | "EXECUTE_BUY" | "ADD" | "EXECUTE_SELL" | "SELL"
                          # "HOLD" | "FORCE_WAIT" | "FORCE_EXIT" | "CIRCUIT_BREAK"
                          # "STAY_CURRENT_STATE" | "ERROR"
    "reason": str,        # 人类可读原因
    "regime": str,        # "NORMAL" | "STRESSED" | "FROZEN"
    "risk": str,          # "Safe" | "Warning" | "Danger"
    "bubble_confidence": float,
    "ntf_side": str,      # "NONE" | "SUPPORT" | "RESISTANCE"
    "ntf_intensity": float,
    "is_3rd_buy": bool,
    "bi_count": int,
    "alpha_score": float,
    "final_decision": str,
    "final_score": int,
    # 可选字段:
    "shares": int,        # 仅 BUY/EXECUTE_BUY 路径
    "position_details": dict,  # 仅 BUY 路径
    "sell_triggers": list,     # 仅 EXECUTE_SELL 路径
    "buy_blockers": list,      # 仅 HOLD (买入阻断) 路径
    "state": str,         # FSM 状态值
    "daily_return": float,# 仅 CIRCUIT_BREAK 路径
}
```

### 1.2 CZSC 输出

**来源**: `brain/czsc/czsc_engine.py:CZSCEngine`

**路径 A** — 增量接口 `update_and_get_signals()`:
```python
{
    "is_3rd_buy": bool,
    "bi_count": int,
    "error": str | None,  # None=成功, str=错误
}
```

**路径 B** — 批量接口 `get_czsc_signals()`:
```python
{
    "bi_count": int,
    "last_bi_direction": int | None,  # 1=向上, -1=向下
    "is_3rd_buy": bool,
    "czsc_signal": str,     # "3rd_BUY" | "NONE"
    "bottom_fractal": float | None,
    "czsc_bottom_price": float | None,
    "signals": dict,        # 原始 czsc 库信号
    "geometry_desc": str,
    "analysis_coverage": float,
    "error": str | None,
}
```

### 1.3 Wyckoff 输出

**来源**: `brain/wyckoff/engine.py:WyckoffEngine.analyze()`
**返回类型**: `WyckoffReport` (dataclass, **非 dict**)

```
WyckoffReport:
  ├─ symbol: str
  ├─ period: str
  ├─ structure: WyckoffStructure (dataclass)
  │   ├─ phase: WyckoffPhase (enum: ACCUMULATION|MARKUP|DISTRIBUTION|MARKDOWN|UNKNOWN)
  │   ├─ bc_point: BCPoint
  │   ├─ sc_point: SCPoint
  │   ├─ trading_range_high/low: float
  │   └─ current_price/date: float/str
  ├─ signal: WyckoffSignal (dataclass)
  │   ├─ signal_type: str ("spring"|"utad"|"sos"|"lps"|"no_signal"|...)
  │   ├─ trigger_price: float
  │   ├─ confidence: ConfidenceLevel (enum: A|B|C|D)
  │   ├─ phase: WyckoffPhase
  │   └─ t1_risk评估: str
  ├─ risk_reward: RiskRewardProjection (dataclass)
  │   ├─ entry_price / stop_loss / first_target: float
  │   └─ reward_risk_ratio: float
  ├─ trading_plan: TradingPlan (dataclass)
  │   ├─ direction: str ("long"|"空仓观望")
  │   ├─ trigger_condition / invalidation_point: str
  │   ├─ confidence: ConfidenceLevel
  │   ├─ spring_cooldown_days: int
  │   └─ t1_blocked: bool
  ├─ chip_analysis: ChipAnalysis (dataclass)
  └─ stress_tests: List[StressTest]
```

### 1.4 LPPL 输出

**来源**: `brain/lppl/engine.py:LPPLEngine` + `brain/lppl/calculator.py:LPPLCalculator`

**路径 A** — `detect_bubble()`:
```python
{
    "is_bubble": bool,
    "tc": float,             # 临界时间
    "days_to_tc": float,     # 距临界时间天数
    "confidence": float,
    "lppl_risk": str,        # "Safe" | "Warning" | "Danger"
    "risk_level": str,       # 同上
    "model_params": dict,    # {m, w, a, b, c, phi}
    "market_metrics": dict,
}
```

**路径 B** — `detect_bubble_confidence()`:
```python
{
    "risk_level": str,       # "Safe" | "Warning" | "Danger"
    "confidence": float,
    "votes": int,
    "details": list[dict],   # 每窗口的 fit 结果
}
```

---

## 2. 格式异构性分析

### 2.1 输出格式统一性审计

| 引擎 | 返回类型 | 键名体系 | 嵌套深度 | 与 BacktestEngine 兼容 |
|------|----------|---------|---------|----------------------|
| DecisionBrain | `Dict[str, Any]` | `action`/`reason` | 1层 | **部分兼容** (action 值不匹配) |
| CZSCEngine.update_and_get_signals | `Dict[str, Any]` | `is_3rd_buy`/`bi_count` | 1层 | **不兼容** (无 action 键) |
| CZSCEngine.get_czsc_signals | `Dict[str, Any]` | `bi_count`/`czsc_signal`/... | 1层 | **不兼容** (无 action 键) |
| WyckoffEngine.analyze | `WyckoffReport` (dataclass) | 嵌套 dataclass | 4层 | **不兼容** (非 dict, 无 action) |
| LPPLEngine.detect_bubble | `Dict[str, Any]` | `is_bubble`/`risk_level` | 1-2层 | **不兼容** (无 action 键) |

**结论**: **不存在统一的信号输出接口**。各 Brain 引擎各自定义输出格式，无 `SignalOutputProtocol` 或 `TradingSignal` dataclass。

### 2.2 数据载体类型不统一

| 引擎 | 输入类型 | 输出类型 |
|------|---------|---------|
| DecisionBrain | `MarketSignalContext` (dataclass) / `dict` | `Dict[str, Any]` |
| CZSCEngine | `pd.Series` / `pd.DataFrame` | `Dict[str, Any]` |
| WyckoffEngine | `pd.DataFrame` | `WyckoffReport` (dataclass) |
| LPPLEngine | `pd.DataFrame` | `Dict[str, Any]` |

**问题**: Wyckoff 是唯一返回 dataclass 的引擎。如果未来需要统一输出格式，Wyckoff 需要适配 `to_dict()` 或定义新的 `TradingSignal` dataclass。

---

## 3. Signal Generator 契约兼容性分析

### 3.1 BacktestEngine 期望的信号契约

```python
# engine.py:296,306
signal_generator: Callable[[pd.DataFrame, int, Dict[str, Any]], Dict[str, Any]]
# 返回值: {"action": "BUY"/"SELL"/"HOLD", "reason": "..."}
```

`run_backtest` 在 line 396 消费信号:
```python
action = signal.get("action", "HOLD")  # 默认 HOLD
```

line 400-413 仅处理三种 action:
```python
if action in ("BUY", "SELL") and next_idx < len(df):
    if action == "BUY" and self.position == 0:
        pending_order = {"action": "BUY", "size": position_size, "reason": reason}
    elif action == "SELL" and self.position > 0:
        pending_order = {"action": "SELL", "size": self.position, ...}
```

### 3.2 FSM → BacktestEngine Action 值映射断裂

| FSM 返回 action | BacktestEngine 处理 | 结果 |
|----------------|-------------------|------|
| `"BUY"` | 正常买入 | **正常** (但 FSM 实际不返回 "BUY") |
| `"EXECUTE_BUY"` | `action not in ("BUY","SELL")` → 忽略 | **[CRITICAL] 买入信号丢失** |
| `"ADD"` | `action not in ("BUY","SELL")` → 忽略 | **[CRITICAL] 加仓信号丢失** |
| `"EXECUTE_SELL"` | `action not in ("BUY","SELL")` → 忽略 | **[CRITICAL] 卖出信号丢失** |
| `"HOLD"` | 不处理 (默认) | 正确 |
| `"FORCE_WAIT"` | 不处理 | 正确 |
| `"FORCE_EXIT"` | 不处理 | **[HIGH] 强制退出信号丢失** |
| `"CIRCUIT_BREAK"` | 不处理 | 正确 (不做交易) |
| `"STAY_CURRENT_STATE"` | 不处理 | 正确 |

**[CRITICAL-FINDING-C1] FSM/DecisionBrain 的 action 值与 BacktestEngine 不兼容**

- DecisionBrain 返回 `"EXECUTE_BUY"` 而非 `"BUY"` — 买入信号被静默忽略
- DecisionBrain 返回 `"EXECUTE_SELL"` 而非 `"SELL"` — 卖出信号被静默忽略
- DecisionBrain 返回 `"ADD"` 而非 `"BUY"` — 加仓信号被静默忽略
- DecisionBrain 返回 `"FORCE_EXIT"` — 强制退出信号被静默忽略

**根因**: DecisionBrain 设计为在线交易系统的总控模块（直接驱动下单），而非为回测场景设计。其 action 值语义偏重"执行指令"而非"信号方向"。

### 3.3 桥接层缺失

当前 **没有任何适配层** 将 DecisionBrain 输出转换为 BacktestEngine 期望的格式。如果用户直接将 `DecisionBrain.make_decision` 作为 `signal_generator` 传入 `BacktestEngine.run_backtest`:

```python
# 伪代码 — 当前无法工作的组合
engine = BacktestEngine()
brain = DecisionBrain()
engine.run_backtest(df, lambda df, idx, ctx: brain.make_decision(packet))
# 结果: 所有 BUY/SELL 信号被静默丢弃，回测无交易
```

### 3.4 CZSC/Wyckoff/LPPL 无法直接作为 signal_generator

CZSC、Wyckoff、LPPL 均不返回 `{"action": ..., "reason": ...}` 格式:
- CZSC 返回 `{"is_3rd_buy": bool, "bi_count": int, ...}` — **无 action**
- Wyckoff 返回 `WyckoffReport` dataclass — **非 dict, 无 action**
- LPPL 返回 `{"is_bubble": bool, "risk_level": str, ...}` — **无 action**

这些引擎是 **分析层**（判断市场状态），不是 **决策层**（产生交易信号）。只有 DecisionBrain 是决策层。但 DecisionBrain 的输出与 BacktestEngine 不兼容。

**[CRITICAL-FINDING-C2] 从 Brain 到 Hands 的信号管线断裂**

```
Brain 分析引擎 (CZSC/Wyckoff/LPPL)
    ↓ 输出: 异构格式 (dict/dataclass)
DecisionBrain (FSM)
    ↓ 输出: {"action": "EXECUTE_BUY", ...}
    ↓
BacktestEngine.signal_generator()
    ↓ 期望: {"action": "BUY", ...}
    ↓ 实际: "EXECUTE_BUY" → 被忽略
    ↓
[信号丢失, 回测无交易]
```

---

## 4. T+1 信号延迟与未来函数审计

### 4.1 BacktestEngine T+1 时序分析

`run_backtest` 主循环 (engine.py:346-413):

```
Bar T (idx):
  1. 处理 pending_order → 以 Open[T] 执行交易 (来自 Bar T-1 的信号)
  2. update_equity(Close[T])
  3. signal = signal_generator(df, idx=T, portfolio_state)  ← 在 Bar T 生成信号
  4. 若 action=="BUY" → pending_order = {BUY, size=100}  ← 等到 Bar T+1 执行
  5. 若 action=="SELL" → pending_order = {SELL, size=pos} ← 等到 Bar T+1 执行
```

**时序确认**: 信号在 Bar T 生成 → 在 Bar T+1 以 Open[T+1] 价格执行 → **T+1 延迟实现正确**。

### 4.2 未来函数风险: signal_generator 接收完整 df

```python
# engine.py:390
signal = signal_generator(df, idx, {...})
```

`df` 是 **完整的** K 线 DataFrame（从 start 到 end），不是 `df.iloc[:idx+1]` 的切片。

**[HIGH-FINDING-F1] 前视偏差 (Look-ahead Bias) 风险**

如果 `signal_generator` 内部访问了 `df.iloc[idx+1:]` 的数据（如 df.tail(N) 但 N > len(df)-idx），将引入前视偏差。

| 引擎 | 前视偏差风险 | 原因 |
|------|------------|------|
| DecisionBrain | **低** — 依赖 MarketSignalContext 中的聚合数据，不直接操作 df | 由上游保证数据时效 |
| CZSC (增量模式) | **低** — `update_and_get_signals` 接收单行 Series | 逐行输入，无未来数据 |
| CZSC (批量模式) | **高** — `get_czsc_signals` 接收完整 df | 内部可能使用 df.tail() 获取上下文 |
| Wyckoff | **高** — `analyze()` 接收完整 df | 内部使用 `df.tail(lookback)` 取最近 120 根 K 线 |
| LPPL | **高** — `detect_bubble()` 接收完整 df | 使用 `df.iloc[-w:]` 滑动窗口 |

**实际影响**: 在回测场景中，如果 `signal_generator` 是一个适配层，将 `df.iloc[:idx+1]` 传给 Brain 引擎，则无前视偏差。但如果直接传完整 `df`，Brain 引擎在分析时会看到未来的 K 线数据。

### 4.3 T+1 边界场景: Bar T 同时 BUY + SELL

```python
# engine.py:400-413
if action in ("BUY", "SELL") and next_idx < len(df):
    if action == "BUY" and self.position == 0:
        pending_order = {"action": "BUY", ...}
    elif action == "SELL" and self.position > 0:
        pending_order = {"action": "SELL", ...}
```

在单次循环中，`pending_order` 只能是 BUY 或 SELL 之一。如果同一 bar 先执行 pending (来自 T-1 的 SELL)，然后 signal_generator 返回 BUY:
1. SELL 在 Bar T Open 执行 → position=0
2. signal_generator 返回 BUY → pending_order = {BUY}
3. Bar T+1 Open 执行 BUY → **正常**

但如果 signal_generator 返回 SELL (且 position > 0):
1. 无 pending → 无交易执行
2. signal_generator 返回 SELL → pending_order = {SELL}
3. Bar T+1 Open 执行 SELL
4. T+1 检查: buy_date=T-1, current=T+1 → 通过 → **正常**

**结论**: 单 pending_order 设计在 T+1 模式下不会导致信号丢失，但不支持同一 bar 内的多次交易。

### 4.4 FSM 状态机的 T+1 意外: DecisionBrain 内部已含涨跌停检查

```python
# fsm.py:296-314 — _check_sell_conditions
if ctx.price > 0 and ctx.pre_close > 0:
    limit_status = check_limit_status(ctx.price, ctx.pre_close, ctx.symbol, ctx.name)
    if limit_status.is_limit_down:
        sell_conditions.append("LIMIT_DOWN")
        sell_limit_blocked = True

action = "HOLD" if sell_limit_blocked else "EXECUTE_SELL"
```

**[HIGH-FINDING-F2] 双重涨跌停检查 + 行为不一致**

DecisionBrain 在 **信号生成阶段** 就检查了涨跌停，并返回 `"HOLD"` (跌停时)。BacktestEngine 在 **执行阶段** 也检查涨跌停:

```python
# engine.py:238-240
if pre_close > 0 and not self._check_limit_constraint(price, pre_close, "SELL", ...):
    return None  # 跌停不卖出
```

两层检查在大多数情况下一致，但存在差异:
1. **DecisionBrain 检查时机**: 使用 `ctx.price` (信号时刻的价格) 和 `ctx.pre_close` (前收盘价)
2. **BacktestEngine 检查时机**: 使用 `pending_order` 执行时刻的 `opens_arr[idx]` (次日开盘价) 和 `pre_close_arr[idx]` (次日前收盘价)
3. **差异场景**: 信号日跌停 (DecisionBrain 阻止) → 次日开盘不跌停 (BacktestEngine 不阻止) → 决策不同

---

## 5. 两套撮合引擎 T+1 语义等价性审计

### 5.1 实现对比

| 维度 | BacktestEngine (engine.py:122-147) | UnifiedMatchingEngine (unified_matching_engine.py:218-233) |
|------|-----------------------------------|-----------------------------------------------------------|
| **买入日期存储** | 单一 `buy_date` 变量 (仅支持 1 只) | `buy_dates` 数组 (每标的一个) |
| **T+1 判定方法** | 交易日历 DataFrame + `np.where` 索引差 | `toordinal()` 比较 + `_next_trading_day()` |
| **判定公式** | `current_idx[0] - buy_idx[0] >= 1` | `c_ts.toordinal() < next_td.toordinal()` |
| **极端假期** | 无上限 (依赖完整日历) | 10 天搜索上限 |
| **非交易日买入** | 保守拒绝卖出 | 保守拒绝卖出 |
| **复杂度** | O(M) per sell (M=日历长度) | O(1) per stock (但有 Python 循环) |

### 5.2 语义等价性验证

**场景 1: 正常 T+1**
- BacktestEngine: buy_date=Jan 2 (交易日), sell_date=Jan 3 (交易日) → idx差=1 → 允许 ✓
- UnifiedMatchingEngine: buy=Jan 2, sell=Jan 3 → next_td(Jan 2)=Jan 3 → toordinal(Jan 3) < toordinal(Jan 3) = false → 不违反 → 允许 ✓
- **一致** ✓

**场景 2: T+0 卖出**
- BacktestEngine: buy=Jan 2, sell=Jan 2 → idx差=0 < 1 → 拒绝 ✓
- UnifiedMatchingEngine: buy=Jan 2, sell=Jan 2 → toordinal(Jan 2) <= toordinal(Jan 2) = true → t1_violation → 拒绝 ✓
- **一致** ✓

**场景 3: 跨周末**
- BacktestEngine: buy=Fri, sell=Mon → 日历中 idx差=1 (跳过周末) → 允许 ✓
- UnifiedMatchingEngine: buy=Fri, sell=Mon → next_td(Fri)=Mon → toordinal(Mon) < toordinal(Mon) = false → 不违反 → 允许 ✓
- **一致** ✓

**场景 4: 春节假期 (>7天)**
- BacktestEngine: buy=Feb 8 (节前最后交易日), sell=Feb 17 (节后首交易日) → 日历 idx差=1 → 允许 ✓
- UnifiedMatchingEngine: buy=Feb 8, sell=Feb 17 → _next_trading_day(Feb 8) → 搜索 1-10 天 → Feb 9~15 都不是交易日 → Feb 16 找到 → next_td=Feb 16 → toordinal(Feb 17) < toordinal(Feb 16) = false → 不违反 → 允许 ✓
- **一致** ✓

**场景 5: 极端假期 (>10天, 如2020新冠)**
- BacktestEngine: buy=Jan 23 (2020), sell=Feb 3 (2020) → 日历 idx差=1 → 允许 ✓
- UnifiedMatchingEngine: buy=Jan 23, sell=Feb 3 → _next_trading_day(Jan 23) → 搜索 1~10 天: Jan 24~Feb 2 都不是交易日 → 搜索 10 天后返回 Feb 2 → next_td=Feb 2 → toordinal(Feb 3) < toordinal(Feb 2) = false → 不违反 → 允许 ✓
- **一致** ✓ (2020 春节假期 9 天，10 天上限刚好覆盖)

**场景 6: 极端假期 (>10天, 2022年上海封控延长假期)**
- 假设 buy=Apr 1 (2022), 4月5日清明后市场关闭至 4月22日 (模拟场景)
- BacktestEngine: 依赖 TradeCalendarManager 的日历数据，只要日历正确就能处理
- UnifiedMatchingEngine: _next_trading_day(Apr 1) → 搜索 1-10 天: Apr 2~Apr 11 → 未找到 → 返回 Apr 12 (非交易日) → next_td 不是真正交易日 → T+1 判断可能错误
- **不一致** ✗ (极端场景下 UnifiedMatchingEngine 可能失效)

**[HIGH-FINDING-T1] 两套 T+1 实现在极端假期场景下行为可能不一致**

### 5.3 UnifiedMatchingEngine T+1 检查的额外问题

```python
# unified_matching_engine.py:219-233
for i in range(n):
    if buy_dates[i] is None:
        continue
    b_ts = pd.Timestamp(buy_dates[i])
    c_ts = pd.Timestamp(timestamps[i])
    b_td = self.trade_calendar.is_trading_day(b_ts)
    c_td = self.trade_calendar.is_trading_day(c_ts)
    if not b_td or not c_td:
        t1_violation[i] = True
```

**问题**: 如果买入日不是交易日 (`b_td=False`)，则 `t1_violation=True`，导致永远无法卖出。但在正常业务中，买入只会在交易日发生，所以 `b_td` 应始终为 `True`。此处的保守检查在边界场景下可能导致持仓无法卖出。

---

## 6. FSM 输出 Dict vs CZSC 输出 Dict vs Wyckoff 输出 dataclass — 格式统一性

### 6.1 键名冲突分析

| 键名 | FSM | CZSC | Wyckoff | LPPL |
|------|-----|------|---------|------|
| `action` | ✓ (核心键) | ✗ | ✗ | ✗ |
| `reason` | ✓ (核心键) | ✗ | ✗ | ✗ |
| `is_3rd_buy` | ✓ (字段) | ✓ (核心键) | ✗ | ✗ |
| `bi_count` | ✓ (字段) | ✓ (核心键) | ✗ | ✗ |
| `risk_level` | ✗ (用 `risk`) | ✗ | ✗ | ✓ (核心键) |
| `phase` | ✗ | ✗ | ✓ (WyckoffPhase) | ✗ |
| `confidence` | ✗ | ✗ | ✓ (ConfidenceLevel) | ✓ (float) |
| `error` | ✗ | ✓ (字段) | ✗ | ✗ |

**问题**: 
- FSM 的 `risk` (值: "Safe"/"Warning"/"Danger") 与 LPPL 的 `risk_level` (同值) 语义相同但键名不同
- FSM 的 `confidence` 是 float (0-1)，Wyckoff 的 confidence 是 ConfidenceLevel enum (A/B/C/D) — **语义和类型都不同**
- FSM 的 `is_3rd_buy` 来自 CZSC 但经过 DecisionBrain 处理后含义可能变化

### 6.2 数据类型不一致

| 概念 | FSM | CZSC | Wyckoff | LPPL |
|------|-----|------|---------|------|
| 风险等级 | `str` ("Safe"/"Danger") | N/A | N/A | `str` ("Safe"/"Danger") |
| 置信度 | `float` (alpha_score) | N/A | `ConfidenceLevel` enum | `float` (confidence) |
| 信号方向 | `str` action ("BUY") | `bool` (is_3rd_buy) | `str` signal_type ("spring") | `bool` (is_bubble) |
| 阶段 | `FSMState` enum | N/A | `WyckoffPhase` enum | N/A |

---

## 7. 综合风险评级

| # | 发现 | 严重度 | Brain 文件 | Hands 文件 | 跨域影响 |
|---|------|--------|-----------|-----------|---------|
| C1 | DecisionBrain action 值 ("EXECUTE_BUY"/"EXECUTE_SELL") 与 BacktestEngine ("BUY"/"SELL") 不匹配 | **CRITICAL** | fsm.py:305,389,583 | engine.py:400 | Brain 输出 → Hands 无法消费, 回测无交易 |
| C2 | Brain→Hands 信号管线断裂, 无适配层 | **CRITICAL** | 全 Brain 层 | engine.py:296 | 整个回测集成不可用 |
| C3 | 三套 Brain 引擎输出格式异构 (dict vs dataclass), 无公共信号接口 | **CRITICAL** | czsc, wyckoff, lppl | engine.py:390 | 任何新引擎接入需手写适配 |
| F1 | signal_generator 接收完整 df, 前视偏差风险 | **HIGH** | — | engine.py:390 | Brain 引擎可能使用未来数据 |
| F2 | DecisionBrain 和 BacktestEngine 双重涨跌停检查, 时机不同 | **HIGH** | fsm.py:296-314 | engine.py:238 | 信号日跌停 → 次日可能不跌停, 决策不一致 |
| T1 | 两套撮合引擎 T+1 极端假期场景可能行为不一致 | **HIGH** | — | engine.py:122 vs unified:218 | 单标的 vs 组合回测结果不可比 |
| M1 | BacktestEngine pending_order 仅支持单一挂单, 信号覆盖 | **MEDIUM** | — | engine.py:344 | 高频信号场景丢失交易机会 |
| M2 | BacktestEngine execute_buy 现金不足回退路径未做整手对齐 | **MEDIUM** | — | engine.py:191 | 回测买入非整手, 与实盘不符 |
| M3 | FSM 输出 dict 与 LPPL 输出 dict 键名冲突 (risk vs risk_level) | **MEDIUM** | fsm.py, lppl | — | 上游集成混淆 |
| M4 | Wyckoff 返回 dataclass 而非 dict, 无法直接作为 signal_generator | **MEDIUM** | wyckoff/engine.py | engine.py:296 | 集成需额外 to_dict() 转换 |
| M5 | DecisionBrain 输出含中文键值 ("建议仓位"), Hands 层不消费 | **LOW** | fsm.py:388 | — | 信息冗余但无害 |

---

## 8. 修复建议

### P0 — 消除 CRITICAL 阻塞

**8.1 定义统一的 `TradingSignal` dataclass**

```python
# shared/interfaces.py — 新增
@dataclass
class TradingSignal:
    """统一交易信号 — Brain → Hands 的标准接口"""
    action: str              # "BUY" | "SELL" | "HOLD" | "ADD"
    reason: str              # 人类可读原因
    confidence: float = 0.0  # 0-1 统一置信度
    shares: int = 0          # 建议股数 (0=使用默认)
    stop_loss: float = 0.0   # 止损价
    take_profit: float = 0.0 # 止盈价
    
    # 可选分析字段
    regime: str = ""
    risk_level: str = ""     # "Safe" | "Warning" | "Danger"
    is_3rd_buy: bool = False
    bi_count: int = 0
    phase: str = ""          # Wyckoff phase
    analysis_detail: Dict[str, Any] = field(default_factory=dict)
```

**8.2 为 DecisionBrain 添加 `to_trading_signal()` 适配方法**

```python
# fsm.py — DecisionBrain 新增
def to_trading_signal(self, result: Dict[str, Any]) -> TradingSignal:
    action_map = {
        "EXECUTE_BUY": "BUY", "BUY": "BUY",
        "EXECUTE_SELL": "SELL", "SELL": "SELL",
        "ADD": "ADD",
        "HOLD": "HOLD", "FORCE_WAIT": "HOLD", "STAY_CURRENT_STATE": "HOLD",
        "FORCE_EXIT": "SELL", "CIRCUIT_BREAK": "HOLD",
    }
    return TradingSignal(
        action=action_map.get(result.get("action", ""), "HOLD"),
        reason=result.get("reason", ""),
        confidence=result.get("final_score", 0) / 100.0,
        shares=result.get("shares", 0),
    )
```

**8.3 修改 BacktestEngine.run_backtest 支持 `TradingSignal`**

```python
# engine.py:396 — 修改信号消费
signal = signal_generator(df, idx, {...})
if isinstance(signal, TradingSignal):
    action = signal.action
    reason = signal.reason
else:
    action = signal.get("action", "HOLD")
    reason = signal.get("reason", "")
```

### P1 — 消除 HIGH 风险

**8.4 信号 df 切片保护**

```python
# engine.py:390 — 传入安全切片
signal = signal_generator(df.iloc[:idx+1], idx, {...})
```

**8.5 统一 T+1 实现**

将 BacktestEngine 的 T+1 检查委托给 UnifiedMatchingEngine，消除代码重复。`_next_trading_day` 搜索上限从 10 天扩展到 20 天。

**8.6 消除双重涨跌停检查**

移除 DecisionBrain 中的涨跌停检查（`_check_sell_conditions` 和 `_check_buy_blockers` 中的 `check_limit_status` 调用），将涨跌停约束完全交给 Hands 层执行。Brain 层只负责信号生成。

### P2 — 消除 MEDIUM 风险

**8.7 BacktestEngine.execute_buy 整手对齐**

```python
# engine.py:191 — 修改为
lot_size = 100  # 或从 get_board_rule(symbol) 获取
shares = (int((self.cash - commission) / exec_price) // lot_size) * lot_size
```

---

## 9. 修复优先级矩阵

| 优先级 | 发现 | 修复内容 | 工作量 | 影响范围 |
|--------|------|---------|--------|---------|
| **P0** | C1 | DecisionBrain action 值映射 | 2h | 回测集成可用性 |
| **P0** | C2 | 定义 TradingSignal + 适配层 | 1d | 全 Brain↔Hands 接口 |
| **P0** | C3 | 统一信号输出接口 | 2d | 所有 Brain 引擎 |
| **P1** | F1 | signal_generator df 切片 | 0.5h | 回测前视偏差 |
| **P1** | F2 | 消除双重涨跌停检查 | 1h | Brain 层职责分离 |
| **P1** | T1 | 统一 T+1 实现 | 1d | 两套撮合引擎 |
| **P2** | M1-M5 | 各项中等修复 | 各 0.5-2h | 各模块 |

---

## 10. 审计结论

**Brain ↔ Hands 跨域集成当前处于"断裂"状态**:

1. **信号管线完全不可用**: DecisionBrain 输出的 action 值与 BacktestEngine 期望不匹配，直接组合使用会导致回测无交易
2. **无统一信号格式**: 4 套 Brain 引擎各自定义输出格式，无公共接口，每接入新引擎需手写适配
3. **T+1 实现不等价**: 两套撮合引擎在极端假期场景下行为可能不一致
4. **前视偏差风险**: signal_generator 接收完整 df 而非切片，依赖调用者自律

**核心修复路径**: 定义 `TradingSignal` dataclass → 为每个 Brain 引擎添加适配方法 → 修改 BacktestEngine 支持 TradingSignal → 统一 T+1 实现。

---

*审计员: R2-B Cross Auditor | 审计时间: 2026-06-06 | 基于代码事实, 禁止幻觉*
