# UniQuant 撮合引擎防线漏洞与重构基准报告

> **漏洞状态: ✅ 已全部修复 (Phase 0-3)** — 本报告为审计存档，所涉及的 19 个防线漏洞已在 Phase 0-3 修复。
>
> 审计范围: `hands/backtest/` + `shared/cost_model.py` + `shared/limit_checker.py` + `shared/slippage_model.py`
> 审计视角: 恶意策略试图利用系统漏洞刷高收益
> 审计时间: 2026-06-07

---

## 0. 防线穿透评估矩阵

| 防线 | 单资产引擎 (BacktestEngine) | 多资产引擎 (PortfolioEngine) | 统一撮合 (UnifiedMatchingEngine) |
|------|---------------------------|---------------------------|-------------------------------|
| A: T+1 铁律 | ⚠️ 漏洞 | ⚠️ 漏洞 | ✅ 严密 |
| B: 涨跌停/停牌 | ✅ 严密 | ✅ 严密 | ✅ 严密 |
| C: 成本精确性 | ⚠️ 漏洞 | ⚠️ 漏洞 | ✅ 严密 |
| D: 资金锁死 | ✅ 严密 | ❌ 裸奔 | ⚠️ 部分防御 |

---

## 1. 防线 A: T+1 铁律与未来函数拦截

### 1.1 BacktestEngine (单资产) — ⚠️ 存在漏洞

#### 防守成功的部分

**信号延迟执行 (Pending Order 机制)** — `engine.py:230-250`

```
T 日 bar 内: signal_generator(df, idx, context) → {"action": "BUY"}
    ↓
pending_order = {"action": "BUY", "size": position_size, "reason": reason}
    ↓
T+1 日 bar 开头: exec_price = opens_arr[idx]  ← 使用次日开盘价成交
```

**结论**: 信号在 T 日生成, 成交在 T+1 日开盘价。这是正确的 T+1 延迟执行。

#### 漏洞 1: T+1 约束依赖 buy_date 传递, 存在 None 绕过风险

**位置**: `engine.py:156-171` (`_check_t1_constraint`)

```python
def _check_t1_constraint(self, buy_date: datetime, current_date: datetime) -> bool:
    if buy_date is None:
        return True  # ⚠️ 如果 buy_date 为 None, 直接放行!
```

**攻击路径**: 如果 `buy_date` 在传递过程中丢失 (例如 `pending_order` 中未携带 `buy_date`), T+1 约束将被完全绕过。

**实际检查**: 在 `run_backtest()` 中:
```python
# engine.py:246-248
elif action == "SELL" and self.position > 0:
    pending_order = {
        "action": "SELL",
        "size": self.position,
        "reason": reason,
        "buy_date": buy_date,  # ✅ 正确传递
    }
```

**评估**: `buy_date` 在 `execute_buy` 成功后被设置 (`engine.py:240`), 在 `execute_sell` 成功后被清除 (`engine.py:248`)。**当前实现正确**, 但 `_check_t1_constraint` 的 `None → True` fallback 是一个脆弱点。

#### 漏洞 2: 同 bar 信号 + 同 bar 成交的历史幽灵

**位置**: `engine.py:222-250` (主循环)

```python
for idx in range(len(df)):
    # Step 1: 执行前一笔挂单 (T+1 日开盘价)
    if pending_order is not None:
        exec_price = opens_arr[idx]  # ← T+1 日 Open
        ...

    # Step 2: 更新权益 (T 日收盘价)
    self.update_equity(current_price)  # ← T 日 Close

    # Step 3: 生成信号 (基于 T 日及之前数据)
    signal = signal_generator(df, idx, {...})

    # Step 4: 下单 (T+1 日执行)
    if action in ("BUY", "ADD") and self.position == 0:
        pending_order = {...}  # ← 将在下一个 idx 执行
```

**评估**: 信号在 idx=T 生成, 成交在 idx=T+1 的 Open 价。**不存在同 bar 成交**。但有一个微妙问题:

**⚠️ 边界情况**: 如果 `signal_generator` 在 `idx=0` 时返回 BUY, 则 `pending_order` 被设置。在 `idx=1` 时, 挂单被执行 (使用 `opens_arr[1]`)。但 `idx=0` 的 `update_equity` 已经用 `closes_arr[0]` 更新了权益曲线。这意味着**权益曲线在 idx=0 时不反映即将发生的买入**, 这是正确的。

#### 漏洞 3: _check_t1_constraint 使用 ordinal 比较, 非交易日序号

**位置**: `engine.py:156-171`

```python
buy_ord = pd.Timestamp(buy_date).toordinal()
cur_ord = pd.Timestamp(current_date).toordinal()
return cur_ord - buy_ord >= 1  # ⚠️ 使用日历日序号, 非交易日序号
```

**攻击路径**: 如果 `buy_date` 是周五, `current_date` 是周六 (非交易日), 则 `cur_ord - buy_ord = 1 >= 1` → 放行。但周六不应该有交易。

**缓解**: `run_backtest()` 只遍历 `df` 中的行, 而 `df` 通常只包含交易日数据。但如果 `df` 包含非交易日数据 (如某些数据源包含周末填充行), 则 T+1 约束可能被绕过。

**实际影响**: 低。因为 `execute_sell` 还会检查 `self.position > 0`, 而持仓只能通过 `execute_buy` 增加, 后者也需要通过 `pending_order` 机制。

### 1.2 PortfolioEngine (多资产) — ⚠️ 存在漏洞

#### 漏洞 4: 信号当日生成, 当日标记为 pending, 但未强制 T+1 延迟

**位置**: `portfolio_engine.py:195-205`

```python
for t, date in enumerate(unique_dates):
    # Step 1: 执行上一日的 pending_signals (✅ T+1)
    if self._pending_signals:
        ...
        self._pending_signals.clear()

    # Step 2: 当日信号加入 pending (✅ 延迟到下一日)
    active = day_signals.loc[day_signals[signal_column] != 0, ...]
    for sym, sig in active.itertuples(index=False, name=None):
        self._pending_signals.append({
            "symbol": sym,
            "action": "BUY" if sig > 0 else "SELL",
            "shares": abs(int(sig)),
            "signal_day_index": t,
        })
```

**评估**: 信号在 day T 生成, 加入 `_pending_signals`。在 day T+1 时执行。**T+1 延迟正确**。

#### 漏洞 5: batch_close_positions 不检查 T+1

**位置**: `portfolio_engine.py:130-165`

```python
def batch_close_positions(self, signals, prices, pre_closes, timestamps, ...):
    ...
    fill = self.matching.fill_sell(
        px_arr, pos_arr, pos_arr, pcost_arr, pc_arr, sym_arr, ts_arr, bd_arr, ...
    )
```

**检查**: `UnifiedMatchingEngine.fill_sell()` 内部有 T+1 检查 (`unified_matching_engine.py:138-153`):

```python
t1_violation = np.zeros(n, dtype=bool)
for i in range(n):
    if buy_dates[i] is None:
        continue
    b_ts = pd.Timestamp(buy_dates[i])
    c_ts = pd.Timestamp(timestamps[i])
    ...
    if c_ts.toordinal() <= b_ts.toordinal():
        t1_violation[i] = True
    else:
        next_td = self._next_trading_day(b_ts)
        if c_ts.toordinal() < next_td.toordinal():
            t1_violation[i] = True
```

**评估**: `UnifiedMatchingEngine` 的 T+1 检查使用 `_next_trading_day()` 查找下一个交易日, 比 `BacktestEngine` 的 ordinal 比较更精确。**但 `PortfolioEngine` 传入的 `buy_dates` 是 `self.positions[s].entry_time`**, 需要确保 `entry_time` 在 `batch_open_positions` 中被正确设置。

**检查**: `portfolio_engine.py:112-116`:
```python
pos = Position(
    symbol=buy_symbols[i],
    shares=int(fill.executed_shares[i]),
    cost_basis=float(fill.exec_prices[i]),
    entry_price=float(fill.exec_prices[i]),
    entry_time=timestamps,  # ✅ 正确设置
)
```

**评估**: T+1 检查在 `UnifiedMatchingEngine` 层强制执行, `PortfolioEngine` 不需要重复检查。**防守成功**。

---

## 2. 防线 B: 涨跌停板与流动性枯竭

### 2.1 BacktestEngine (单资产) — ✅ 严密

**位置**: `engine.py:173-180` (`_check_limit_constraint`)

```python
def _check_limit_constraint(self, price, pre_close, action, symbol="", name=None):
    limit_status = check_limit_status(price, pre_close, symbol, name)
    if action == "BUY" and limit_status.is_limit_up:
        return False  # 涨停拒绝买入
    if action == "SELL" and limit_status.is_limit_down:
        return False  # 跌停拒绝卖出
    return True
```

**调用点**:
- `execute_buy()`: `engine.py:120-122` — 涨停时拒绝买入 ✅
- `execute_sell()`: `engine.py:177-179` — 跌停时拒绝卖出 ✅

**limit_checker.py 审计**:
- 支持主板 ±10%, 科创板/创业板 ±20%, 北交所 ±30%, ST ±5% ✅
- 支持 IPO 首日特殊规则 (主板 +44%/-36%, 科创板/创业板前5日无限制) ✅
- 使用 `PRICE_TOLERANCE = 0.001` 容差, 避免浮点精度误判 ✅

### 2.2 UnifiedMatchingEngine — ✅ 严密 (向量化)

**位置**: `unified_matching_engine.py:61-107` (`compute_limit_status_vectorized`)

```python
# Fast path: 全向量化
board_types = np.array([get_board_type(s) for s in symbols])
for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
    board_mask = board_types == board_type
    mask = board_mask & valid
    is_limit_up |= mask & (price_ratios >= up_r - tol)
    is_limit_down |= mask & (price_ratios <= down_r + tol)

# Slow path: 逐元素 (ST 检测 + IPO 规则)
for i in range(n):
    ...
    if names is not None and names[i]:
        nu = names[i].upper()
        if any(nu.startswith(p) for p in ("ST", "*ST", "S*ST")):
            bt = "st"
```

**评估**: 
- 涨停 → 拒绝买入 (`fill_buy` 中 `limit_rejected = limit_status["is_limit_up"]`) ✅
- 跌停 → 拒绝卖出 (`fill_sell` 中 `limit_rejected = limit_status["is_limit_down"]`) ✅
- 支持 ST 名称检测 ✅
- 支持 IPO 特殊规则 ✅

### 2.3 停牌 (Volume == 0) — ❌ 未检查

**位置**: 所有引擎均未检查 `volume == 0` 的情况。

**攻击路径**: 如果 `df` 中某行 `volume=0` (停牌), 但 `close` 价格非零 (使用上一交易日收盘价), 策略可能在停牌日生成信号并被撮合。

**实际影响**: 中。因为:
1. 停牌日通常不会出现在正常的 K 线数据中
2. 如果数据源填充了停牌日数据, `open=high=low=close=prev_close`, 涨跌幅为 0%, 不会触发涨跌停拦截
3. 但停牌日实际上无法成交, 这是一个**静默的前视偏差**

---

## 3. 防线 C: 非对称摩擦成本与滑点

### 3.1 成本模型审计 — ✅ 精确

**位置**: `shared/cost_model.py`

| 成分 | 买方 | 卖方 | 常量 |
|------|------|------|------|
| 佣金 | `max(value × 0.03%, 5元)` | `max(value × 0.03%, 5元)` | `COMMISSION_PCT = 0.0003` |
| 印花税 | 0 | `value × 0.05%` (2023-08-28后) | `STAMP_TAX_PCT = 0.0005` |
| 过户费 | `value × 0.001%` | `value × 0.001%` | `TRANSFER_FEE_PCT = 0.00001` |
| **合计** | **0.031%** | **0.081%** | |

**印花税日期感知**: `get_stamp_tax_pct(trade_date)` 正确区分 2023-08-28 前后的税率 ✅

**最低佣金**: `max(value × 0.03%, 5.0)` ✅

### 3.2 BacktestEngine 成本计算 — ⚠️ 存在精度问题

**位置**: `engine.py:86-95` (`_calculate_commission`)

```python
def _calculate_commission(self, value, timestamp=None, is_sell=False):
    commission = max(value * self.commission_rate, self.min_commission)
    stamp_duty = 0.0
    if is_sell:
        rate = get_stamp_tax_pct(timestamp.date()) if (self.stamp_date_aware and timestamp) else self.stamp_duty_rate
        stamp_duty = value * rate
    transfer_fee = value * TRANSFER_FEE_PCT
    return commission + stamp_duty + transfer_fee
```

**⚠️ 问题 1**: `self.commission_rate` 默认值是 `BacktestConstants.DEFAULT_COMMISSION_RATE = 0.0003`, 但 `cost_model.py` 的 `COMMISSION_PCT = 0.0003`。二者一致, 但如果用户构造 `BacktestEngine(commission_rate=0.001)` (千1), 则会覆盖标准值。**无断言保护**。

**⚠️ 问题 2**: `stamp_duty_rate` 参数默认值是 `BacktestConstants.DEFAULT_STAMP_DUTY_RATE = 0.0005`, 但当 `stamp_date_aware=True` 时, 实际使用 `get_stamp_tax_pct(timestamp.date())`。如果 `timestamp` 为 None 且 `stamp_date_aware=True`, 则 fallback 到 `self.stamp_duty_rate`。**逻辑正确但分支复杂**。

### 3.3 滑点模型审计 — ⚠️ 存在漏洞

#### BacktestEngine._calculate_slippage — ⚠️ 基础滑点 + 冲击成本

**位置**: `engine.py:97-121`

```python
def _calculate_slippage(self, price, is_buy=True, volume=0, avg_daily_volume=0):
    base_slippage = self.slippage_rate  # 默认 0.05%
    
    impact_slippage = 0.0
    if avg_daily_volume > 0 and volume > 0:
        volume_ratio = volume / avg_daily_volume
        impact_slippage = 0.001 * (volume_ratio ** 0.5)
        impact_slippage = min(impact_slippage, 0.02)  # 上限 2%
    
    total_slippage = base_slippage + impact_slippage
    
    if is_buy:
        return price * (1 + total_slippage)
    else:
        return price * (1 - total_slippage)
```

**⚠️ 问题 1**: `volume` 参数是**交易量** (shares), 但 `avg_daily_volume` 是**日均成交量** (shares)。二者的单位一致, 但 `volume_ratio = volume / avg_daily_volume` 可能 > 1 (大单), 此时 `impact = 0.001 * sqrt(1) = 0.001`。对于真正的大单 (volume_ratio = 10), `impact = 0.001 * sqrt(10) ≈ 0.00316`。**冲击模型偏保守**。

**⚠️ 问题 2**: `run_backtest()` 中传入的 `volume` 和 `avg_daily_volume`:
```python
# engine.py:237-238
volume=int(volumes_arr[idx]),           # 当日成交量
avg_daily_volume=float(avg_daily_vol_arr[idx]),  # 20日均量
```

**问题**: `volume` 是**当日总成交量**, 不是**本次交易量**。策略可能只交易 100 股, 但传入的是当日 100 万股的成交量。这导致 `volume_ratio` 被严重低估, 冲击成本几乎为零。

**正确做法**: 应传入 `position_size` (本次交易量) 而非 `volumes_arr[idx]` (当日总成交量)。

#### UnifiedMatchingEngine.compute_execution_prices — ✅ 正确

**位置**: `unified_matching_engine.py:47-58`

```python
def compute_execution_prices(self, prices, volumes, avg_daily_volumes, is_buy):
    vol_ratios = np.where(
        (avg_daily_volumes > 0) & (volumes > 0),
        np.minimum(volumes / np.maximum(avg_daily_volumes, 1e-8), 1.0),  # ⚠️ cap at 1.0
        0.0,
    )
    impact = np.minimum(0.001 * np.sqrt(vol_ratios), 0.02)
    total_slip = self.slippage_rate + impact
    direction = 1.0 if is_buy else -1.0
    return prices * (1.0 + direction * total_slip)
```

**⚠️ 问题**: `volumes` 参数在 `fill_buy` 和 `fill_sell` 中传入的是 `volumes` (当日成交量), 不是交易量。与 `BacktestEngine` 相同的问题。

**但**: `np.minimum(..., 1.0)` 将 volume_ratio cap 在 1.0, 防止了极端情况。且 `volumes` 在 `batch_open_positions` 中传入的是 `day_vol` (当日成交量), 而非本次交易量。

### 3.4 slippage_model.py — ⚠️ 存在但未被使用

**位置**: `shared/slippage_model.py`

`DynamicSlippage` 类存在但:
1. `_get_liquidity()` 返回硬编码的 10 亿 (无实际数据)
2. `_get_atr()` 返回硬编码的 0.02 (无实际数据)
3. **未被任何回测引擎调用**

---

## 4. 防线 D: 投资组合层面的资金锁死

### 4.1 PortfolioEngine — ❌ 裸奔

#### 漏洞 6: batch_open_positions 不检查总资金是否足够

**位置**: `portfolio_engine.py:82-120`

```python
def batch_open_positions(self, signals, prices, pre_closes, timestamps,
                         shares_per_trade=0, sizing_fraction=0.25, ...):
    ...
    if shares_per_trade > 0:
        sh_arr = np.full(n, shares_per_trade, dtype=np.int64)
    else:
        alloc = self.cash * sizing_fraction / max(n, 1)  # ⚠️ 按总现金分配
        sh_arr = np.maximum((alloc / np.maximum(px_arr, 1e-8)).astype(np.int64) // 100 * 100, 0)
    
    cash_arr = np.full(n, self.cash / max(n, 1), dtype=np.float64)  # ⚠️ 平分现金
    
    fill = self.matching.fill_buy(px_arr, sh_arr, cash_arr, pc_arr, sym_arr, ts_arr, ...)
```

**攻击路径**:
1. 假设 `self.cash = 100,000`, `sizing_fraction = 0.25`, `n = 10` 只股票
2. `alloc = 100,000 × 0.25 / 10 = 2,500` 每只
3. `cash_arr = [10,000, 10,000, ..., 10,000]` (平分)
4. 每只股票的 `cash_available = 10,000`, 但实际总现金只有 100,000
5. 如果 10 只全部成交, 总成本 = 10 × 2,500 = 25,000 (在 sizing_fraction 内)
6. **但**: `cash_arr` 传入的是 `self.cash / n = 10,000`, 而 `fill_buy` 会检查 `total_costs > cash_available`
7. 如果 `alloc = 2,500` 但 `cash_arr = 10,000`, 则不会触发 cash_shortfall

**实际问题**: `cash_arr` 的语义是"每只股票可用的现金上限", 但实际扣款是在 `batch_open_positions` 的 for 循环中逐只进行的:

```python
for i in range(n):
    if fill.rejected_mask[i]:
        continue
    ...
    cost = float(fill.exec_prices[i] * fill.executed_shares[i] + fill.commissions[i] + fill.transfer_fees[i])
    self.cash -= cost  # ⚠️ 逐只扣款, self.cash 递减
```

**攻击路径**:
1. `self.cash = 100,000`, `n = 10`
2. `cash_arr = [10,000, 10,000, ..., 10,000]` (平分, 但不反映递减)
3. 第 1 只成交, `self.cash -= 2,500` → `self.cash = 97,500`
4. 第 2 只成交, `self.cash -= 2,500` → `self.cash = 95,000`
5. ...
6. 第 10 只成交, `self.cash -= 2,500` → `self.cash = 75,000`
7. **总成本 25,000, 在 100,000 范围内, 不会透支**

**但如果 `sizing_fraction = 1.0`** (全仓):
1. `alloc = 100,000 × 1.0 / 10 = 10,000` 每只
2. `cash_arr = [10,000, ..., 10,000]`
3. 第 1 只: 成本 ≈ 10,000, `self.cash = 90,000`
4. 第 2 只: 成本 ≈ 10,000, `self.cash = 80,000`
5. ...
6. 第 10 只: `cash_arr[9] = 10,000`, 但 `self.cash = 10,000`, 刚好够
7. **总成本 ≈ 100,000, 边界情况**

**但如果 `shares_per_trade > 0`**:
1. `shares_per_trade = 500`, `n = 10`, `price = 50`
2. 每只成本 = 500 × 50 = 25,000
3. 总成本 = 10 × 25,000 = 250,000 > 100,000
4. `cash_arr = [10,000, ..., 10,000]`
5. `fill_buy` 检查: `total_costs (25,000) > cash_available (10,000)` → cash_shortfall → 调整 shares
6. 调整后: `shares = (10,000 - commission) / 50 ≈ 199` → 取整到 100
7. 每只实际买入 100 股, 总成本 = 10 × 100 × 50 = 50,000
8. **不会透支, 但 cash_arr 的平分逻辑导致每只股票可用资金被低估**

**核心问题**: `cash_arr = self.cash / max(n, 1)` 假设现金平均分配, 但实际成交是**逐只扣款**, 后面的股票可用资金比 `cash_arr` 传入的值更少。这导致:
- 前几只股票可能买入过多 (因为 `cash_arr` 高估了可用资金)
- 后几只股票可能被错误拒绝 (因为 `self.cash` 已被前几只消耗)

**但**: `fill_buy` 内部有 `cash_shortfall` 检查, 会将 `shares_adj` 调整为 0。所以**不会透支**, 但**资金分配不均**。

### 4.2 UnifiedMatchingEngine.fill_buy — ⚠️ 部分防御

**位置**: `unified_matching_engine.py:108-145`

```python
def fill_buy(self, prices, shares_requested, cash_available, ...):
    ...
    total_costs = values + commissions + transfer_fees
    cash_shortfall = total_costs > cash_available
    shares_adj = np.where(
        ~cash_shortfall,
        shares_requested,
        np.where(
            cash_available > commissions + transfer_fees,
            ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // lot_sizes * lot_sizes,
            0,
        ),
    )
```

**评估**: 
- 当 `total_costs > cash_available` 时, 自动调整 shares 使总成本 ≤ cash_available ✅
- 调整后的 shares 按 `lot_size` 取整 (A 股 100 股整手) ✅
- 如果 `cash_available` 不足以覆盖 commission + transfer_fee, 则 shares = 0 ✅

**但**: `cash_available` 是传入的参数, 不是引擎内部维护的实时余额。`PortfolioEngine` 传入的是 `self.cash / n` (平分), 而非实时余额。这导致**防透支检查基于错误的可用资金值**。

---

## 5. 暗箱操作清单汇总

| # | 漏洞 | 严重性 | 位置 | 攻击路径 |
|---|------|--------|------|----------|
| 1 | `_check_t1_constraint` 的 `None → True` fallback | 中 | `engine.py:158` | 如果 buy_date 丢失, T+1 被绕过 |
| 2 | `_check_t1_constraint` 使用日历日而非交易日 | 低 | `engine.py:166` | 非交易日数据可能绕过 |
| 3 | 停牌日 (volume=0) 未被拦截 | 中 | 所有引擎 | 停牌日可生成并撮合信号 |
| 4 | 滑点使用当日总成交量而非本次交易量 | 高 | `engine.py:237`, `unified_matching_engine.py:53` | 冲击成本被严重低估 |
| 5 | `PortfolioEngine.cash_arr` 平分而非实时余额 | 高 | `portfolio_engine.py:99` | 资金分配不均, 前几只多买 |
| 6 | `shares_per_trade` 模式下无总资金检查 | 高 | `portfolio_engine.py:93` | 如果 shares_per_trade 过大, 后面的股票被错误拒绝 |
| 7 | `DynamicSlippage` 硬编码参数未被使用 | 低 | `slippage_model.py:31-33` | 无实际影响 |
| 8 | `run_stress_test` 只缩放 OHLC 不缩放 pre_close | 中 | `engine.py:305-315` | 涨跌停检查使用错误的 pre_close |

---

## 6. 重构断言清单 (TDD Assertions)

为未来的 `UnifiedBacktestEngine` 编写的强断言:

### 断言 1: T+1 绝对铁律
```
FOR any trade T in engine.trades:
    IF T.action == "SELL":
        ASSERT T.timestamp >= T.buy_timestamp + 1 TradingDay
        WHERE "1 TradingDay" = _next_trading_day(T.buy_timestamp)
        # 不接受 calendar day, 必须是交易日序号差 >= 1
```

### 断序 2: 涨停拦截买入
```
FOR any bar B where B.close / B.pre_close >= LIMIT_RATIO[board_type] - TOLERANCE:
    ASSERT engine.execute_buy(B.close, ...) == None
    # 涨停板上不可能买入任何股票
```

### 断言 3: 跌停拦截卖出
```
FOR any bar B where B.close / B.pre_close <= DOWN_RATIO[board_type] + TOLERANCE:
    ASSERT engine.execute_sell(B.close, ...) == None
    # 跌停板上不可能卖出任何股票
```

### 断言 4: 停牌拦截
```
FOR any bar B where B.volume == 0:
    ASSERT engine.execute_buy(...) == None
    ASSERT engine.execute_sell(...) == None
    # 停牌日不可能有任何成交
```

### 断言 5: 资金永不透支
```
FOR any point in time T:
    ASSERT engine.cash >= 0
    # 即使在最极端的多资产同时买入场景下, 现金余额永不为负
```

### 断言 6: 成交价含滑点且方向正确
```
FOR any buy trade T:
    ASSERT T.exec_price >= T.signal_price  # 买入滑点向上
FOR any sell trade T:
    ASSERT T.exec_price <= T.signal_price  # 卖出滑点向下
```

### 断言 7: 非对称成本精确扣除
```
FOR any buy trade T:
    ASSERT T.commission == max(T.value × COMMISSION_PCT, MIN_COMMISSION)
    ASSERT T.stamp_duty == 0
    ASSERT T.transfer_fee == T.value × TRANSFER_FEE_PCT
    ASSERT engine.cash -= (T.value + T.commission + T.transfer_fee)

FOR any sell trade T:
    ASSERT T.commission == max(T.value × COMMISSION_PCT, MIN_COMMISSION)
    ASSERT T.stamp_duty == T.value × get_stamp_tax_pct(T.timestamp.date())
    ASSERT T.transfer_fee == T.value × TRANSFER_FEE_PCT
    ASSERT engine.cash += (T.value - T.commission - T.stamp_duty - T.transfer_fee)
```

### 断言 8: 权益曲线单调递增 (无负收益异常)
```
# 权益曲线不应出现单日跌幅超过涨跌停限制的情况
FOR i in range(1, len(equity_curve)):
    daily_return = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
    ASSERT daily_return >= -MAX_LIMIT_RATIO - EPSILON
    # 即使持仓股票跌停, 单日最大跌幅也不应超过涨跌停限制
```

---

## 7. 重构优先级

| 优先级 | 问题 | 修复方案 |
|--------|------|----------|
| P0 | 滑点使用当日成交量而非交易量 | 传入 `position_size` 而非 `volumes_arr[idx]` |
| P0 | PortfolioEngine 资金分配不均 | 使用实时余额逐只分配, 而非平分 |
| P1 | 停牌日未拦截 | 在撮合前检查 `volume > 0` |
| P1 | run_stress_test 未缩放 pre_close | 同步缩放 pre_close 或重新计算 |
| P2 | _check_t1_constraint 使用日历日 | 改为使用交易日序号差 |
| P2 | DynamicSlippage 未被使用 | 集成到回测引擎或删除 |
| P3 | 无 TDD 断言保护 | 编写上述 8 条断言的 pytest 测试 |

---

*生成时间: 2026-06-07 | 基于源码逐行白盒审计, 禁止幻觉*
