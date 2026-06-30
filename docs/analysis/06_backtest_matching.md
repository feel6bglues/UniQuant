# Stage 6 — 回测与撮合系统深度分析

> **日期**: 2026-06-29 | **状态**: ✅ 完成
> **范围**: `hands/backtest/` (15 文件, 3,644 LOC)
> **依赖**: `shared/` (cost_model, limit_checker, market_rules), `data/` (TradeCalendarManager)

---

## 1. 总览

### 架构

```
TradingSignal (来自仲裁器)
        │
        ▼
UnifiedBacktestEngine.run(df, signals, symbol)
        │
        ├─ _prepare_dataframe()
        ├─ _index_signals_by_date()
        │
        ├─ bar 循环 (逐行遍历):
        │   ├─ Step 1: 执行前日挂单
        │   │   ├─ BUY  → _execute_buy()
        │   │   └─ SELL → _execute_sell() → _check_t1()
        │   │
        │   ├─ Step 2: 更新权益
        │   │
        │   └─ Step 3: 收集当日信号 → 生成挂单
        │       ├─ LPPL SELL（最高优先）
        │       ├─ BUY（中间优先）
        │       └─ 非LPPL SELL（最低优先）
        │
        └─ BacktestResult
```

### 7 道防线 (A-G)

| 防线 | 规则 | 位置 |
|------|------|------|
| **A. T+1 铁律** | 交易日序号差 ≥ 1 | `unified_engine.py:_check_t1()`, `unified_matching_engine.py:T+1 vectorized` |
| **B. 涨跌停拦截** | 涨停不买入, 跌停不卖出 | `unified_engine.py:_check_limit()`, `matching:compute_limit_status_vectorized()` |
| **C. 停牌拦截** | volume=0 不成交 | `unified_engine.py:195-197` |
| **D. 资金不透支** | 实时 cash_available 全局扣减 | `unified_engine.py:_execute_buy()`, `matching:cash_shortfall_mask` |
| **E. 非对称成本** | 印花税仅卖方, 最低佣金 5 元 | `unified_engine.py:_calc_commission/stamp_duty/transfer_fee()` |
| **F. 滑点方向** | 买高卖低, 使用交易量而非日均量 | `unified_engine.py:_calc_slippage()`, `matching:compute_execution_prices()` |
| **G. 整手取整** | A 股 100 股为一手 | `unified_engine.py:528-529`, matching:lot_size |

---

## 2. 文件清单

| 文件 | LOC | 职责 | 状态 |
|------|-----|------|------|
| `unified_engine.py` | 604 | **统一回测引擎** (主) | ✅ 活跃 |
| `unified_matching_engine.py` | 263 | 向量化撮合引擎 (主) | ✅ 活跃 |
| `engine.py` | 747 | ~~旧版回测引擎~~ | ⚠️ 已弃用 |
| `portfolio_engine.py` | 373 | ~~投资组合回测~~ | ⚠️ 已弃用 |
| `result.py` | 175 | ~~旧版回测结果~~ | ⚠️ 已弃用 |
| `signal_integrator.py` | 124 | Signal → 交易 DataFrame | ✅ 活跃 |
| `benchmark.py` | 156 | 基准计算 | ✅ |
| `report_generator.py` | 279 | 回测报告生成 | ✅ |
| `monte_carlo.py` | 199 | 蒙特卡洛模拟 | ✅ |
| `overfitting_detector.py` | 187 | 过拟合检测 | ✅ |
| `param_validator.py` | 112 | 参数验证 | ✅ |
| `robustness_checker.py` | 233 | 稳健性检查 | ✅ |
| `sensitivity_analyzer.py` | 162 | 敏感性分析 | ✅ |
| `trade_analysis/analyzer.py` | — | 交易分析 | ✅ |
| `trade_analysis/statistics.py` | — | 交易统计 | ✅ |

---

## 3. UnifiedBacktestEngine (`unified_engine.py`)

### 核心流程

```python
run(df, signals, symbol) → BacktestResult

for each bar (逐行遍历):
  Step 1: 执行前日挂单 (T+1 延迟成交)
    ├─ BUY: 涨跌停检查 → 滑点计算 → 整手取整 → 现金扣减 → TradeRecord
    └─ SELL: T+1 检查 → 涨跌停检查 → 滑点计算 → 印花税 → 现金回收

  Step 2: 更新权益曲线 equity = cash + position * close

  Step 3: 收集当日信号 → 生成挂单
    Priority 1: LPPL SELL (位置 > 0)
    Priority 2: BUY (位置 == 0)
    Priority 3: 其他 SELL (位置 > 0)
```

### 信号优先级 (挂单生成)

与仲裁器不同，回测引擎内部运行独立的信号优先级规则：

```
LPPL SELL (position > 0) → 立即挂单卖出全部持仓
       ↓
BUY (position == 0) → 挂单买入 (shares = sig.shares)
       ↓
其他 SELL (position > 0) → 挂单卖出全部持仓
```

### 滑点计算

```python
ratio = trade_volume / avg_daily_volume          # 使用本次交易量
impact = min(0.001 * sqrt(ratio), 0.02)           # 非线性市场冲击
total_slip = slippage_rate + impact               # 基础滑点 + 冲击成本
exec_price = price * (1 + direction * total_slip) # 买高卖低
```

### 防止幸存者偏差

```python
# 在回测结束时检查股票是否已退市
delist_date = StockMetadataManager().get_delist_date(symbol)
if delist_date is not None and delist_date <= last_bar:
    metadata["survivorship_warning"] = ...
```

---

## 4. UnifiedMatchingEngine (`unified_matching_engine.py`)

### 向量化接口

```python
class UnifiedMatchingEngine:
    fill_buy(prices, shares_requested, cash_available, pre_closes,
             symbols, timestamps, volumes, avg_daily_volumes, ...) → FillResult
    fill_sell(prices, shares_requested, positions_held, position_costs,
              pre_closes, symbols, timestamps, buy_dates, volumes,
              avg_daily_volumes, ...) → FillResult
```

### FillResult

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray     # 实际成交股数
    exec_prices: np.ndarray          # 执行价格 (含滑点)
    commissions: np.ndarray          # 佣金
    stamp_duties: np.ndarray         # 印花税 (仅卖方)
    slippages: np.ndarray            # 滑点成本
    transfer_fees: np.ndarray        # 过户费
    rejected_mask: np.ndarray        # 全局拒绝掩码
    t1_violation_mask: np.ndarray    # T+1 违反掩码
    limit_violation_mask: np.ndarray # 涨跌停违反掩码
    cash_shortfall_mask: np.ndarray  # 资金不足掩码
```

### 向量化涨跌停计算

```python
compute_limit_status_vectorized(prices, pre_closes, symbols, names, trading_days_listed):
  Fast path: 无 names/trading_days_listed → 纯向量化, board_types 预计算
  Slow path: 含 ST 名称检测 + IPO 特殊规则（新股首日 44% 涨跌幅, 科创/创业前 5 日无限制）
```

### 向量化滑点

```python
compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy):
  vol_ratios = min(volumes / avg_daily_volumes, 1.0)
  impact = min(0.001 * sqrt(vol_ratios), 0.02)
  total_slip = slippage_rate + impact
  direction = 1 if is_buy else -1
  return prices * (1 + direction * total_slip)
```

### 向量化 T+1 检查

```python
for i in range(n):
    if buy_dates[i] is None: continue
    b_ts, c_ts = buy_dates[i], timestamps[i]
    if c_ts.toordinal() <= b_ts.toordinal(): t1_violation[i] = True
    next_td = _next_trading_day(b_ts)
    if c_ts.toordinal() < next_td.toordinal(): t1_violation[i] = True
```

---

## 5. 执行方法细节

### _execute_buy

```
1. 涨跌停检查 (防线 B)
2. 滑点计算 (防线 F)
3. 整手取整 (防线 G)
4. 总成本 = 股数 * 执行价格 + 佣金 + 过户费
5. 资金检查 (防线 D)
6. → TradeRecord(commission, transfer_fee, slippage)
```

### _execute_sell

```
1. T+1 检查 (防线 A)
2. 涨跌停检查 (防线 B)
3. 滑点计算 (防线 F)
4. 印花税 (仅卖方, 防线 E)
5. 佣金 + 过户费
6. PnL = 回收现金 - (持仓成本 * 股数)
7. → TradeRecord(commission, stamp_duty, transfer_fee, slippage, pnl)
```

---

## 6. 成本模型参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `COMMISSION_PCT` | 0.00025 (万 2.5) | 佣金费率 |
| `MIN_COMMISSION` | 5.0 元 | 最低佣金 |
| `STAMP_TAX_PCT` | 0.0005 (万 5) | 印花税 (卖方) |
| `TRANSFER_FEE_PCT` | 0.00001 (万 0.1) | 过户费 |
| `SLIPPAGE_PCT` | 0.001 (千 1) | 基础滑点率 |

---

## 7. 旧版弃用组件

| 组件 | 替代 | 弃用原因 |
|------|------|----------|
| `BacktestEngine` (engine.py) | `UnifiedBacktestEngine` | 旧版接受 Callable 策略, 新引擎强类型 List[TradingSignal] |
| `PortfolioEngine` | `UnifiedBacktestEngine` | 多标的回测移至上层 ; 新引擎每标的运行一次 |
| `result.py TradeRecord` | `unified_engine.py TradeRecord` | 旧版缺少 stamp_duty/transfer_fee 字段 |
| `result.py BacktestResult` | `unified_engine.py BacktestResult` | 旧版混合计算和存储职责 |

---

## 8. 辅助工具

| 工具 | 用途 |
|------|------|
| `benchmark.py` | 基准收益/波动/夏普计算 |
| `monte_carlo.py` | 随机路径模拟, 风险价值评估 |
| `overfitting_detector.py` | 过拟合检测 (D-M 检验, 子区间一致性) |
| `param_validator.py` | 参数合法性验证 |
| `robustness_checker.py` | 市场状态稳定性, 参数敏感性, 子区间一致性, 成本敏感性 |
| `sensitivity_analyzer.py` | 参数敏感性分析 |
| `report_generator.py` | HTML/文本回测报告生成 |
| `signal_integrator.py` | Signal 模型 → 交易 DataFrame 融合 |
| `trade_analysis/analyzer.py` | 交易行为分析 |
| `trade_analysis/statistics.py` | 交易统计指标 |

---

## 9. 关键观察

### 架构风险

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R6-1 | **回测与匹配引擎有两套信号优先级规则**: UnifiedBacktestEngine 的 bar 循环内使用 LPPL→BUY→SELL 优先级, 与 SignalArbitrator 的规则不同 | `unified_engine.py:220-250` | 相同信号在仲裁器和回测引擎中可能产生不同交易行为 |
| R6-2 | **向量化 T+1 未完全利用**: `fill_sell()` 中使用 Python for-loop 逐元素检查, 而非纯向量化 | `unified_matching_engine.py:198-209` | 性能瓶颈 |
| R6-3 | **旧版代码体积大 (747 LOC)**: `engine.py` 虽弃用但仍可被引用, 维护负担 | `engine.py` | 需清理 |
| R6-4 | **挂单一日期有多个信号时只执行第一个**: bar 循环 `break` 后忽略后续信号 | `unified_engine.py:230,237,244` | 同一天多个引擎触发时可能丢失交易机会 |
| R6-5 | **缺失交易量约束**: 滑点计算使用 `trade_volume` 但不验证挂单量是否超过当日可交易量 | `unified_engine.py:_calc_slippage()` | 大单滑点可能低估 |

### 设计亮点

| # | 亮点 | 位置 |
|---|------|------|
| S6-1 | **7 道防线 (A-G)**: T+1、涨跌停、停牌、不透支、成本、滑点、整手 — A 股全约束覆盖 | 全部 `unified_engine.py` |
| S6-2 | **向量化匹配引擎**: 支撑 PortfolioEngine 和 UnifiedBacktestEngine 两个引擎, 消除成本计算偏移 | `unified_matching_engine.py` |
| S6-3 | **非线性滑点**: `0.001 * sqrt(vol_ratio)`, 使用 trade_volume 而非 daily_volume | `unified_engine.py:480-488` |
| S6-4 | **IPO 新股规则**: 首日 44% 涨跌幅, 科创/创业板前 5 日无限制 | `matching.py:153-163` |
| S6-5 | **印花税日期感知**: `get_stamp_tax_pct(timestamp.date())` 支持历史税率回溯 | `unified_engine.py:461-465` |
| S6-6 | **幸存者偏差检测**: 自动检查退市日期 | `unified_engine.py:254-269` |
| S6-7 | **涨跌停向量化快速路径/慢速路径**: 按数据情况自动选择最优路径 | `matching.py:110-170` |
| S6-8 | **辅助工具丰富**: 8 个分析工具覆盖蒙特卡洛/过拟合/稳健性/敏感性/报告 |

### 回测 vs 仲裁信号优先级对比

| 阶段 | 优先级规则 |
|------|-----------|
| **SignalArbitrator** | DecisionOutput 硬约束 > SELL > FSM BUY > 非-FSM BUY > 引擎优先级 |
| **UnifiedBacktestEngine** | LPPL SELL > BUY > 非LPPL SELL |

两者独立运行, 可能导致:
- 仲裁器选择 BUY → 回测引擎内部可能被非LPPL SELL 覆盖
- 仲裁器选择 SELL (非LPPL) → 回测引擎中 LPPL SELL 优先级更高

### 测试覆盖

| 测试 | 函数数 | 覆盖 |
|------|--------|------|
| `tests/test_backtest_engine.py` | — | 旧版引擎测试 |
| `tests/test_unified_backtest_engine.py` | — | 统一引擎测试 |
| `tests/test_matching_engine.py` | — | 撮合引擎测试 |
| `tests/test_portfolio_engine_v2.py` | 12+ | 组合引擎测试 |
| `tests/benchmark/golden_20.txt/100.txt` | — | 基线回归黄金列表 |

---

## 10. 建议

### P1
1. **R6-1 (双重优先级)**: 统一回测引擎内部的信号优先级与仲裁器一致 — 让 `UnifiedBacktestEngine.run()` 使用仲裁后的信号, 不再重复仲裁

### P2
2. **R6-2 (T+1 向量化)**: 将 `fill_sell()` 中的 T+1 for-loop 转换为向量化 `numpy` 操作
3. **R6-5 (交易量约束)**: 添加挂单量 vs 当日可交易量的检查

### P3
4. **R6-3 (旧版清理)**: 清除 `engine.py`, `portfolio_engine.py`, `result.py` 弃用代码
5. **R6-4 (多信号覆盖)**: 考虑同一天多信号场景, 改为信号取并集而非仅执行第一个

---

## 11. 验证清单

- [x] 读取 `unified_engine.py` (完整 bar 循环, 7 道防线, 3 步流程)
- [x] 读取 `unified_matching_engine.py` (向量化 BUY/SELL, FillResult, 涨跌停/T+1)
- [x] 读取 `engine.py` (弃用声明)
- [x] 读取 `portfolio_engine.py` (弃用, 使用 UnifiedMatchingEngine)
- [x] 读取 `result.py` (弃用, 双重 BacktestResult)
- [x] 读取 `signal_integrator.py` (Signal → DataFrame 桥接)
- [x] 读取 `robustness_checker.py` (市场状态/参数/子区间 4 检查)
- [x] 检查 `cost_model.py` 参数 (佣金/印花税/过户费/滑点)
- [x] 检查 `limit_checker.py` (涨跌停板规则)
- [x] 检查 `market_rules.py` (lot_size, board rules)
- [x] 检查基线回归测试 (golden_20.txt/100.txt)
