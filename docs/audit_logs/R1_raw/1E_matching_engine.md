# R1-1E: Matching Engine Deep Audit Report

## 审计范围
`src/uniquant/hands/backtest/` 全层：engine.py, unified_matching_engine.py, portfolio_engine.py, result.py

## 文件清单
| 文件 | 行数 | 职责 |
|------|------|------|
| backtest/engine.py | 650 | 逐 bar 回测引擎（BacktestEngine），单标的 |
| backtest/unified_matching_engine.py | 261 | 向量化撮合引擎（UnifiedMatchingEngine），多标的 |
| backtest/portfolio_engine.py | 360 | 组合回测引擎，封装 UnifiedMatchingEngine |
| backtest/result.py | 162 | BacktestResult / TradeRecord 数据结构 |

## 依赖关系
```
engine.py ──→ TradeCalendarManager, check_limit_status, get_stamp_tax_pct
unified_matching_engine.py ──→ TradeCalendarManager, get_board_type, get_board_rule, get_stamp_tax_pct
portfolio_engine.py ──→ UnifiedMatchingEngine, BacktestConstants
```

---

## 发现 (按严重度排序)

### [CRITICAL-1] unified_matching_engine.py:159-174 fill_buy 现金不足时使用原始佣金估算导致买入股数偏少

- 文件: `unified_matching_engine.py:159-174`
- 行号: 159-174
- 描述: 当 `total_costs > cash_available` 时，代码使用基于 `shares_requested`（原始请求股数）计算的 `commissions` 来估算可买股数。由于原始佣金高于实际需要的佣金（因为原始股数远大于可买股数），导致可用预算被低估，买入股数偏少。
- 代码路径:
  ```python
  # line 159: 用原始 shares_requested 计算 commission
  values = exec_prices * shares_requested
  commissions = np.maximum(values * self.commission_rate, self.min_commission)
  transfer_fees = values * TRANSFER_FEE_PCT
  total_costs = values + commissions + transfer_fees

  # line 164-174: 现金不足时，用原始 commission 估算可买股数
  cash_shortfall = total_costs > cash_available
  shares_adj = np.where(
      ~cash_shortfall,
      shares_requested,
      np.where(
          cash_available > commissions + transfer_fees,   # <-- 这里 commissions 是原始股数的佣金
          ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // lot_sizes * lot_sizes,
          0,
      ),
  )
  ```
- 复现路径:
  ```
  shares_requested = 10000, exec_price = 1.0, lot_size = 100, cash_available = 205
  原始 commission = max(10000 * 1.0 * 0.0003, 5) = 5.0
  shares_adj = int((205 - 5) / 1.0) // 100 * 100 = 100
  但实际 200 股: 200 * 1.0 + max(200 * 0.0003, 5) + 200 * 0.00001 = 205.062 ≈ 205 → 可以买 200 股
  ```
- 影响: **买入能力被低估**，回测收益率偏保守。在资金紧张的场景下（如尾盘资金不足），偏差更明显。
- 修复建议: 使用迭代法或最小佣金（`self.min_commission`）进行初始估算，再用实际佣金校正:
  ```python
  # 用最小佣金估算上界
  shares_est = ((cash_available - self.min_commission) / exec_prices).astype(np.int64) // lot_sizes * lot_sizes
  # 再用实际佣金校正
  values_est = exec_prices * shares_est
  commissions_est = np.maximum(values_est * self.commission_rate, self.min_commission)
  shares_adj = ((cash_available - commissions_est - transfer_fees_est) / exec_prices).astype(np.int64) // lot_sizes * lot_sizes
  ```

---

### [HIGH-1] engine.py:122-147 _check_t1_constraint O(n²) 复杂度 — 每次卖出重建交易日历

- 文件: `engine.py:122-147`
- 行号: 130-141
- 描述: `_check_t1_constraint` 在每次卖出时调用 `self.trade_calendar.get_trade_calendar(start_date, end_date)`，该方法:
  1. 按年遍历生成日历（`generate_trade_calendar` 每年一次 I/O 或计算）
  2. `pd.concat` 合并多年日历
  3. 过滤日期范围
  4. 排序并 reset_index

  然后用 `np.where(trade_dates == pd.Timestamp(buy_date))` 做线性扫描查找索引。
- 复杂度: 假设回测 N 根 bar，其中 K 根触发卖出。每次卖出重建日历 O(M)（M=交易日总数），加线性扫描 O(M)。总复杂度 O(K * M)。对于 10 年回测（M≈2500, K≈500），总操作量约 125 万次。
- 影响: **全市场回测性能瓶颈**。单标的尚可接受，但 PortfolioEngine 如果逐标的调用，性能急剧下降。
- 修复建议:
  1. 在 `__init__` 或 `run_backtest` 开头预计算完整交易日历并缓存
  2. 用 `np.searchsorted` 替代 `np.where` 做 O(log n) 二分查找
  3. 预建 `date -> ordinal_index` 字典映射

---

### [HIGH-2] unified_matching_engine.py:218-233 T+1 检查使用 Python for-loop — 未向量化

- 文件: `unified_matching_engine.py:218-233`
- 行号: 218-233
- 描述: 尽管 UnifiedMatchingEngine 声称是"向量化撮合引擎"，T+1 检查却使用 Python for-loop:
  ```python
  for i in range(n):
      if buy_dates[i] is None:
          continue
      b_ts = pd.Timestamp(buy_dates[i])
      c_ts = pd.Timestamp(timestamps[i])
      b_td = self.trade_calendar.is_trading_day(b_ts)
      c_td = self.trade_calendar.is_trading_day(c_ts)
      if not b_td or not c_td:
          t1_violation[i] = True
      elif c_ts.toordinal() <= b_ts.toordinal():
          t1_violation[i] = True
      else:
          next_td = self._next_trading_day(b_ts)
          if c_ts.toordinal() < next_td.toordinal():
              t1_violation[i] = True
  ```
  每次迭代调用 `is_trading_day`（可能涉及日历查询）和 `_next_trading_day`（最多循环 10 次）。
- 影响: 对于 1000+ 只股票的组合回测，T+1 检查成为热点。Python 循环开销远高于 NumPy 向量化操作。
- 修复建议: 预计算交易日序号数组，用 NumPy 向量化比较:
  ```python
  buy_ordinals = np.array([self._date_to_ordinal(d) for d in buy_dates])
  current_ordinals = np.array([self._date_to_ordinal(d) for d in timestamps])
  next_td_ordinals = np.array([self._date_to_ordinal(self._next_trading_day(pd.Timestamp(d))) for d in buy_dates])
  t1_violation = (buy_ordinals >= 0) & (current_ordinals <= buy_ordinals) | \
                 (buy_ordinals >= 0) & (current_ordinals < next_td_ordinals)
  ```

---

### [HIGH-3] engine.py:346-413 pending_order 仅支持单一挂单 — 信号丢失风险

- 文件: `engine.py:346-413`
- 行号: 344, 386, 400-413
- 描述: `pending_order` 是单个 dict（第 344 行），每次循环只能保留一个挂单。如果在 BUY pending 存在时收到 SELL 信号，BUY pending 会被覆盖（第 386 行 `pending_order = None`，然后第 408 行创建 SELL pending）。反之亦然。
- 复现路径:
  ```
  Bar T: signal = BUY → pending = {BUY, ...}
  Bar T+1: 执行 BUY → pending = None; signal = SELL → pending = {SELL, ...}
  Bar T+2: 执行 SELL → OK

  但如果:
  Bar T: signal = BUY → pending = {BUY, ...}
  Bar T+1: 不执行 pending（因为 pending_order 在循环开头处理，然后 signal 被覆盖）
  ```
  实际上更严重的问题是：如果 BUY 在 Bar T 执行成功，然后在同一 Bar T 的 signal 阶段产生 SELL 信号，SELL pending 会在 Bar T+1 执行。此时 `buy_date` 是 Bar T 的时间戳，T+1 检查会通过（因为 T 到 T+1 隔了 1 个交易日）。这在逻辑上是正确的，但代码意图不够清晰。
- 影响: 信号覆盖导致回测遗漏交易机会。在高频信号生成场景下尤为明显。
- 修复建议: 使用 `collections.deque` 或列表存储多个 pending orders，按 FIFO 顺序执行。

---

### [HIGH-4] engine.py:185-196 execute_buy 现金不足回退路径未做整手对齐

- 文件: `engine.py:185-196`
- 行号: 191
- 描述: 当 `total_cost > self.cash` 时，回退路径:
  ```python
  shares = int((self.cash - commission) / exec_price)
  ```
  仅做整数截断，未对齐到 A 股最小交易单位（100 股整手）。可能买入 150 股而非 100 或 200 股。
- 影响: 回测结果与实际交易不符。A 股主板/创业板/北交所最小买入单位为 100 股，科创板为 200 股。非整手买入在实际中无法下单。
- 修复建议:
  ```python
  lot_size = get_board_rule(symbol).lot_size if symbol else 100
  shares = (int((self.cash - commission) / exec_price) // lot_size) * lot_size
  ```

---

### [HIGH-5] unified_matching_engine.py:54-60 _next_trading_day 最多搜索 10 天 — 极端假期场景失效

- 文件: `unified_matching_engine.py:54-60`
- 行号: 54-60
- 描述:
  ```python
  def _next_trading_day(self, date: pd.Timestamp) -> pd.Timestamp:
      d = date + pd.Timedelta(days=1)
      for _ in range(10):
          if self.trade_calendar.is_trading_day(d):
              return d
          d += pd.Timedelta(days=1)
      return d  # 第 11 天，可能不是交易日
  ```
  中国 A 股春节假期通常 7 天，国庆 7 天，但极端情况（如 2020 年新冠）可能超过 10 天。如果搜索 10 天后仍未找到交易日，函数返回一个非交易日的时间戳，导致 T+1 检查使用错误的"下一个交易日"。
- 影响: 极端假期后 T+1 判断可能错误，导致本应允许的卖出被拒绝，或本应拒绝的卖出被允许。
- 修复建议: 使用 `TradeCalendarManager` 的完整日历做查找，或增加搜索范围到 20 天并添加 fallback 日志告警。

---

### [MEDIUM-1] engine.py:130-133 get_trade_calendar 每次调用重复生成日历

- 文件: `engine.py:130-133`, `trade_calendar_manager.py:144-169`
- 行号: engine.py:130-133
- 描述: `get_trade_calendar` 每次调用都会按年遍历 `generate_trade_calendar`，然后 `pd.concat` + 过滤。对于跨 10 年的回测，每次卖出调用都会重复生成 10 年的日历数据。
- 影响: 与 HIGH-1 叠加，进一步加剧性能问题。
- 修复建议: 在 `BacktestEngine.__init__` 或 `run_backtest` 开头预加载并缓存完整交易日历。

---

### [MEDIUM-2] unified_matching_engine.py:240-243 fill_sell 印花税计算使用 Python 循环

- 文件: `unified_matching_engine.py:240-243`
- 行号: 240-243
- 描述:
  ```python
  stamp_dates = pd.to_datetime(timestamps)
  unique_dates = {d.date() for d in stamp_dates}
  date_to_rate = {d: get_stamp_tax_pct(d) for d in unique_dates}
  stamp_duties = np.array([values[i] * date_to_rate[stamp_dates[i].date()] for i in range(n)])
  ```
  最后一行是 Python 列表推导式，在 NumPy 向量化引擎中混用 Python 循环。
- 影响: 对于 1000+ 只股票，印花税计算有明显的 Python 开销。
- 修复建议: 预计算日期到税率的映射后，用向量化索引:
  ```python
  rates = np.array([date_to_rate[d.date()] for d in stamp_dates])
  stamp_duties = values * rates
  ```

---

### [MEDIUM-3] unified_matching_engine.py:97-101 compute_limit_status_vectorized 快速路径仍用 Python 循环

- 文件: `unified_matching_engine.py:94-101`
- 行号: 97
- 描述: 即使在快速路径（无 names、无 trading_days_listed）中，仍使用:
  ```python
  board_mask = np.array([get_board_type(s) == board_type for s in symbols])
  ```
  对每个 symbol 调用 `get_board_type`（涉及字符串分割和前缀匹配），且对每个 board type 重复此操作。
- 复杂度: O(n * k)，n=股票数，k=板块类型数（5-6）。对于 1000 只股票约 5000-6000 次 Python 函数调用。
- 影响: 限制检查是每次 fill_buy/fill_sell 的必经路径，性能直接影响回测速度。
- 修复建议: 预计算 symbol → board_type 映射并缓存，或用 NumPy 向量化字符串操作。

---

### [MEDIUM-4] 两套撮合引擎行为不一致 — BacktestEngine vs UnifiedMatchingEngine

- 文件: `engine.py` vs `unified_matching_engine.py`
- 描述: 两个引擎在以下方面存在差异:

  | 行为 | BacktestEngine | UnifiedMatchingEngine |
  |------|---------------|----------------------|
  | T+1 检查 | `get_trade_calendar` + `np.where` | `toordinal()` + `_next_trading_day` |
  | 整手对齐 | 不强制 | fill_buy 强制，fill_sell 不强制 |
  | 涨跌停检查 | `check_limit_status`（单标的） | `compute_limit_status_vectorized`（批量） |
  | 印花税 | `_calculate_commission` 内联 | `fill_sell` 独立计算 |
  | 滑点模型 | `_calculate_slippage`（相同公式） | `compute_execution_prices`（相同公式） |
  | 现金不足处理 | 整数截断，不整手对齐 | 原始佣金估算，整手对齐 |

- 影响: 同一策略在单标的（BacktestEngine）和组合（PortfolioEngine + UnifiedMatchingEngine）回测中可能产生不同结果，难以对比和归因。
- 修复建议: 统一到 UnifiedMatchingEngine，BacktestEngine 作为薄封装调用 UnifiedMatchingEngine。

---

### [MEDIUM-5] engine.py:329-336 pre_close 和 avg_daily_volume 填充策略引入早期偏差

- 文件: `engine.py:321-327`
- 行号: 321-327
- 描述:
  ```python
  if "pre_close" not in df.columns:
      df["pre_close"] = df["close"].shift(1)
      df["pre_close"] = df["pre_close"].fillna(df["open"])  # 第 1 根 bar 用 open 替代
  if "avg_daily_volume" not in df.columns:
      df["avg_daily_volume"] = df["volume"].rolling(20).mean().fillna(0)  # 前 19 根 bar 为 0
  ```
  - 第 1 根 bar 的 `pre_close` 使用 `open` 价格，可能导致涨跌停判断偏差
  - 前 19 根 bar 的 `avg_daily_volume = 0`，导致滑点模型中冲击成本为 0（`impact_slippage = 0`），买入价格偏乐观
- 影响: 回测前 20 根 bar 的交易成本被低估。
- 修复建议: 前 19 根 bar 使用可用的 volume 均值，或从外部数据源获取历史日均成交量。

---

### [MEDIUM-6] engine.py:390 signal_generator 接收完整 DataFrame — 潜在前视偏差

- 文件: `engine.py:390`
- 行号: 390-394
- 描述:
  ```python
  signal = signal_generator(df, idx, {
      "position": self.position,
      "position_cost": self.position_cost,
      "cash": self.cash,
  })
  ```
  `df` 是完整的 K 线 DataFrame，`idx` 是当前索引。如果 `signal_generator` 的实现不小心访问了 `df.iloc[idx+1:]` 的数据，就会引入前视偏差（Look-ahead Bias）。
- 影响: 策略开发者可能无意中使用未来数据，导致回测收益率虚高。
- 修复建议: 传入 `df.iloc[:idx+1]` 的切片，或在文档中明确标注"禁止访问 idx 之后的数据"。

---

### [MEDIUM-7] portfolio_engine.py:119 batch_open_positions 现金均分可能导致资金浪费

- 文件: `portfolio_engine.py:119`
- 行号: 119
- 描述:
  ```python
  cash_arr = np.full(n, self.cash / max(n, 1), dtype=np.float64)
  ```
  每个持仓获得等额现金分配。如果某些股票因涨跌停或整手对齐无法用完分配资金，剩余资金不会重新分配给其他股票。
- 影响: 资金利用率偏低，在持仓数接近 `max_positions` 时尤为明显。
- 修复建议: 使用两轮 fill：第一轮均分，第二轮将剩余资金重新分配给未满仓的持仓。

---

### [MEDIUM-8] engine.py:251 卖出手续费计算 — commission 包含印花税和过户费

- 文件: `engine.py:75-83, 245-251`
- 行号: 75-83, 251
- 描述: `_calculate_commission` 返回 `commission + stamp_duty + transfer_fee` 的总和，变量名 `commission` 具有误导性。在 `execute_sell` 中:
  ```python
  commission = self._calculate_commission(value, timestamp=timestamp, is_sell=True)
  # ...
  self.cash += value - commission
  ```
  `commission` 实际上是"总交易成本"，而非仅佣金。`TradeRecord` 中的 `commission` 字段同样记录了总成本，而非纯佣金。
- 影响: 交易记录中的佣金数据不准确，无法区分佣金、印花税、过户费。审计和成本分析时产生困惑。
- 修复建议: 将 `_calculate_commission` 重命名为 `_calculate_trading_cost`，或返回具名元组 `(commission, stamp_duty, transfer_fee)`。

---

### [LOW-1] engine.py:80-81 stamp_date_aware 默认值可能导致历史回测偏差

- 文件: `engine.py:46, 80-81`
- 行号: 46, 80-81
- 描述: `stamp_date_aware` 默认为 `True`，此时使用 `get_stamp_tax_pct(timestamp.date())` 返回日期感知的税率。但如果用户显式设置 `stamp_date_aware=False`，则使用固定的 `self.stamp_duty_rate`（默认 0.0005，即 2023-08-28 之后的税率）。如果回测区间在 2023-08-28 之前，印花税被低估。
- 影响: 仅在用户主动禁用 `stamp_date_aware` 且回测历史数据时触发。
- 修复建议: 当 `stamp_date_aware=False` 时打印警告日志，或移除此选项强制使用日期感知税率。

---

### [LOW-2] unified_matching_engine.py:188 fill_buy stamp_duties 全零 — 设计正确但缺乏注释

- 文件: `unified_matching_engine.py:188`
- 行号: 188
- 描述: `stamp_duties=np.zeros(n)` — 买入不收印花税，这是 A 股正确行为。但代码中没有注释说明为什么买入的印花税为零，可能让维护者困惑。
- 影响: 无功能问题，仅代码可读性。
- 修复建议: 添加注释 `# A 股印花税仅对卖出征收，买入为 0`。

---

### [LOW-3] result.py:101 夏普比率使用日收益率标准差而非超额收益标准差

- 文件: `result.py:101`
- 行号: 101
- 描述:
  ```python
  self.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)
  ```
  标准夏普比率公式为 `(R_p - R_f) / σ_p`，此处未减去无风险收益率。但 `cost_model.py:47-54` 中的 `calculate_sharpe_ratio` 函数正确地减去了 `risk_free_rate / 252`（默认 3% 年化，即 `RISK_FREE_RATE = 0.03`）:
  ```python
  return float((np.mean(arr) - risk_free_rate / 252.0) / np.std(arr, ddof=1) * np.sqrt(252.0))
  ```
  另外注意 `result.py` 使用 `np.std(returns)`（ddof=0），而 `cost_model.py` 使用 `np.std(arr, ddof=1)`（样本标准差），标准差计算方式也不同。
- 影响: `BacktestResult.calculate_metrics` 计算的夏普比率偏高（约 0.03/√252 ≈ 0.002/日 的偏差），且标准差计算方式不一致导致进一步偏差。
- 修复建议: 使用 `calculate_sharpe_ratio(returns, RISK_FREE_RATE)` 替代内联计算，确保与 `cost_model.py` 基准一致。

---

### [LOW-4] engine.py:277 daily_returns 除零保护缺失

- 文件: `engine.py:277`
- 行号: 277
- 描述: `daily_return = (equity - self._prev_equity) / self._prev_equity` — 如果 `_prev_equity` 为 0（理论上仅在 `initial_capital=0` 时发生），会触发除零错误。
- 影响: 极端边界条件，正常使用不会触发。`portfolio_engine.py:212` 已用 `max(self._prev_equity, 1e-8)` 做了保护，但 `engine.py` 未做。
- 修复建议: 统一使用 `max(self._prev_equity, 1e-8)` 或在 `__init__` 中断言 `initial_capital > 0`。

---

### [LOW-5] unified_matching_engine.py:97-101 快速路径 board_mask 重复计算

- 文件: `unified_matching_engine.py:96-100`
- 行号: 97
- 描述: 对每个 board type 都重新计算 `board_mask = np.array([get_board_type(s) == board_type for s in symbols])`。如果 symbols 有 n 个，board types 有 k 个，总计算量为 O(n * k)。实际上每个 symbol 只属于一个 board type，可以预先计算一次 `board_types` 数组。
- 影响: 性能浪费约 k-1 倍（k≈6）。
- 修复建议:
  ```python
  board_types = np.array([get_board_type(s) for s in symbols])
  for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
      mask = (board_types == board_type) & valid
      ...
  ```

---

## 架构级发现

### [ARCH-1] 两套引擎并行维护成本高

BacktestEngine（engine.py）和 UnifiedMatchingEngine（unified_matching_engine.py）实现相同的功能但代码完全独立。新功能（如新的成本模型、新的约束规则）需要在两处同步修改，容易遗漏。

**建议**: 将 BacktestEngine 重构为 UnifiedMatchingEngine 的薄封装，消除代码重复。

### [ARCH-2] T+1 实现策略不统一

- BacktestEngine 使用交易日历 DataFrame + np.where 索引查找
- UnifiedMatchingEngine 使用 toordinal() + _next_trading_day 线性搜索

两种方法在语义上等价，但实现路径完全不同，增加了维护负担和潜在不一致性。

**建议**: 统一 T+1 实现，推荐使用预计算的交易日序号数组 + np.searchsorted。

### [ARCH-3] PortfolioEngine 未复用 BacktestEngine

PortfolioEngine（portfolio_engine.py）独立实现了完整的回测循环（run 方法），未复用 BacktestEngine 的逻辑。两者在 equity 计算、daily return 计算等方面存在微小差异。

**建议**: 将 PortfolioEngine 的回测循环提取为共享基类或 mixin。

---

## 涨跌停约束审计

| 检查项 | engine.py | unified_matching_engine.py | 结论 |
|--------|-----------|---------------------------|------|
| 主板 ±10% | ✅ `check_limit_status` | ✅ `LIMIT_RATIO["main"]` | 正确 |
| 科创板 ±20% | ✅ `get_board_type` 识别 | ✅ `LIMIT_RATIO["sci_tech"]` | 正确 |
| 创业板 ±20% | ✅ | ✅ | 正确 |
| 北交所 ±30% | ✅ | ✅ | 正确 |
| ST 股 ±5% | ✅ | ✅ (name 检测) | 正确 |
| IPO 首日无限制 | ⚠️ 不支持 `trading_days_listed` | ✅ 支持 | engine.py 缺失 |
| 科创板/创业板前5日 | ⚠️ 不支持 | ✅ 支持 | engine.py 缺失 |
| 涨停不买入 | ✅ line 159 | ✅ line 155 | 正确 |
| 跌停不卖出 | ✅ line 161 | ✅ line 216 | 正确 |
| 容差处理 | ✅ `PRICE_TOLERANCE` | ✅ `tol` | 正确 |

**结论**: unified_matching_engine.py 的涨跌停检查更完整（支持 IPO 特殊规则），engine.py 缺少 IPO 期间的涨跌停豁免。

---

## 印花税 / 佣金 / 过户费计算审计

| 费用项 | engine.py | unified_matching_engine.py | cost_model.py 基准 |
|--------|-----------|---------------------------|-------------------|
| 佣金率 | 0.03% ✅ | 0.03% ✅ | 0.0003 |
| 最低佣金 | 5 元 ✅ | 5 元 ✅ | 5.0 |
| 印花税(卖) | 0.05% (日期感知) ✅ | 0.05% (日期感知) ✅ | 0.0005 |
| 印花税(买) | 0 ✅ | 0 ✅ | N/A |
| 过户费 | 0.001% ✅ | 0.001% ✅ | 0.00001 |
| 2023-08-28 前税率 | ✅ `get_stamp_tax_pct` | ✅ `get_stamp_tax_pct` | 0.001 (千1) |

**结论**: 费用计算在两个引擎中均正确，且与 cost_model.py 基准一致。日期感知印花税实现正确。

---

## T+1 约束交叉验证

### 两引擎 T+1 实现对比

| 维度 | BacktestEngine (engine.py:122-147) | UnifiedMatchingEngine (unified_matching_engine.py:218-233) |
|------|-----------------------------------|-----------------------------------------------------------|
| 买入日期存储 | 单一 `buy_date` 变量 | `buy_dates` 数组（每标的一个） |
| 日历查询 | `get_trade_calendar()` → DataFrame | `is_trading_day()` → bool |
| 日期比较 | `np.where(trade_dates == pd.Timestamp(buy_date))` → 索引差 | `c_ts.toordinal() <= b_ts.toordinal()` + `_next_trading_day()` |
| 下一交易日 | 不需要（索引差 ≥ 1） | 需要 `_next_trading_day()` + ordinal 比较 |
| 复杂度 | O(M) per sell（M=日历长度） | O(1) per stock（但有 Python 循环） |
| 极端假期处理 | 保守策略：空日历拒绝卖出 | 10 天搜索上限，可能失效 |
| 非交易日处理 | `is_trading_day` 检查 | `is_trading_day` 检查（一致） |

**语义等价性分析**:
- BacktestEngine: `current_idx[0] - buy_idx[0] >= 1` → 买入日和卖出日之间至少隔 1 个交易日
- UnifiedMatchingEngine: `c_ts.toordinal() < next_td.toordinal()` → 卖出日在买入日的下一个交易日之后

两者在语义上等价（都要求 T+1），但实现路径完全不同。在边界情况下（如买入日和卖出日相同但都是交易日），两者行为一致：均拒绝卖出。

**不一致风险**: UnifiedMatchingEngine 的 `_next_trading_day` 有 10 天搜索上限，而 BacktestEngine 的 `get_trade_calendar` 不受此限制。在极端假期场景下，两者可能产生不同结果。

---

## 修改后验证清单

```bash
# 1. 导入链验证
python -c "from uniquant.hands.backtest.engine import BacktestEngine; print('engine OK')"
python -c "from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine; print('unified OK')"
python -c "from uniquant.hands.backtest.portfolio_engine import PortfolioEngine; print('portfolio OK')"

# 2. 核心测试
pytest tests/ -xvs -k "backtest or matching or engine"

# 3. T+1 约束验证
python -c "
from uniquant.hands.backtest.engine import BacktestEngine
e = BacktestEngine()
# 模拟 T+1: buy on day 0, try sell on day 0 → should fail
from datetime import datetime
result = e._check_t1_constraint(datetime(2024,1,2), datetime(2024,1,2))
assert result == False, 'T+0 sell should be rejected'
result = e._check_t1_constraint(datetime(2024,1,2), datetime(2024,1,3))
assert result == True, 'T+1 sell should be allowed'
print('T+1 check OK')
"

# 4. 涨跌停验证
python -c "
from uniquant.hands.backtest.engine import BacktestEngine
e = BacktestEngine()
# 涨停 10% → should reject buy
result = e._check_limit_constraint(11.0, 10.0, 'BUY', '000001.SZ')
assert result == False, 'Limit up buy should be rejected'
# 跌停 -10% → should reject sell
result = e._check_limit_constraint(9.0, 10.0, 'SELL', '000001.SZ')
assert result == False, 'Limit down sell should be rejected'
print('Limit check OK')
"

# 5. Lint
ruff check src/uniquant/hands/backtest/
```

---

*审计时间: 2026-06-06 | 审计员: R1-Matching Engine Auditor | 审计深度: 全文件逐行 + 跨模块交叉验证*
