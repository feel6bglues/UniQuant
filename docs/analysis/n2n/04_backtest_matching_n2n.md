# 工作流 4：回测撮合模块 N2N 深度分析报告

> **分析日期**：2026-11-24  
> **代码基线**：`434aab1` (第25轮)  
> **分析范围**：`src/uniquant/hands/backtest/` (10 文件, 3,723 行) + `src/uniquant/shared/limit_checker.py`  
> **方法论**：Name-to-Name 代码级点对点审查  

---

## 1. Name 定义（命名与契约）

### 1.1 **七大防线清单**

**防线文档** (`unified_engine.py:7-15`)：
```
防线清单:
  A. T+1 铁律: 交易日序号差 >= 1
  B. 涨跌停拦截: 涨停不买入, 跌停不卖出
  C. 停牌拦截: volume=0 不成交
  D. 资金永不透支: 实时 cash_available 全局扣减
  E. 非对称成本: 印花税仅卖方, 最低佣金5元
  F. 滑点方向: 买高卖低, 使用交易量而非日均量
  G. 整手取整: A股100股为一手
```

**✅ 防线命名清晰**：
- 7 条防线字母编号 A-G
- 每条防线有明确的中文名称和规则描述
- 对应实现方法命名一致（`_check_t1`, `_check_limit`, `_calc_commission` 等）

### 1.2 **TradeRecord 数据契约**

**成交记录** (`unified_models.py:33-47`)：
```python
@dataclass
class TradeRecord:
    """成交记录"""
    timestamp: datetime.datetime
    action: str  # "BUY" | "SELL"
    symbol: str
    price: float
    shares: int
    commission: float
    stamp_duty: float = 0.0
    transfer_fee: float = 0.0
    slippage: float = 0.0
    pnl: float = 0.0
    reason: str = ""
```

**✅ 契约完整性**：
- 必填字段：timestamp/action/symbol/price/shares/commission
- 可选字段（带默认值）：stamp_duty/transfer_fee/slippage/pnl/reason
- 类型注解完整

### 1.3 **BacktestResult 数据契约**

**回测结果** (`unified_models.py:49-170`)：
```python
@dataclass
class BacktestResult:
    """回测结果"""
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    initial_capital: float = 0.0
    final_cash: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    benchmark_return: float = 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def total_return(self) -> float:
        if not self.equity_curve or self.initial_capital <= 0:
            return 0.0
        return (self.equity_curve[-1] - self.initial_capital) / self.initial_capital

    @property
    def sharpe(self) -> float:
        if len(self.daily_returns) < 2:
            return 0.0
        return calculate_sharpe_ratio(self.daily_returns, period_days=1)

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        ec = np.array(self.equity_curve, dtype=np.float64)
        rolling_max = np.maximum.accumulate(ec)
        dd = (rolling_max - ec) / np.maximum(rolling_max, 1e-10)
        return float(np.max(dd))

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t.action == "SELL"]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.pnl > 0)
        return wins / len(closed)

    @property
    def profit_factor(self) -> float:
        closed = [t for t in self.trades if t.action == "SELL"]
        if not closed:
            return 0.0
        total_profit = sum(t.pnl for t in closed if t.pnl > 0)
        total_loss = abs(sum(t.pnl for t in closed if t.pnl < 0))
        if total_loss == 0:
            return float("inf") if total_profit > 0 else 0.0
        return total_profit / total_loss
```

**✅ 指标计算完整**：
- 7 个核心指标：total_trades/total_return/sharpe/annualized_return/max_drawdown/win_rate/profit_factor
- 所有指标处理边界条件（空列表、除零、负数）
- `compare()` 方法支持敏感性分析

---

## 2. Name 映射（数据流转映射）

### 2.1 **七大防线执行顺序**

**UnifiedBacktestEngine.run 主循环** (`unified_engine.py:191-388`)：

```python
for idx in range(len(df)):
    ts = pd.Timestamp(dates[idx])
    date_key = ts.strftime("%Y-%m-%d")

    # 跳过非交易日
    if not self.trade_calendar.is_trading_day(ts):
        # 非交易日也更新权益
        equity = cash + position * closes[idx]
        # ... 更新 equity_curve, daily_returns ...
        continue

    # ── Step 1: 执行前一根 bar 的挂单 (T+1 延迟) ──
    if pending_order is not None:
        exec_price_raw = opens[idx]
        vol = int(volumes[idx])
        pc = pre_closes[idx]
        adv = avg_daily_volumes[idx]

        # 防线 C: 停牌拦截
        if vol <= 0:
            # ... 停牌拒绝逻辑 ...
        else:
            if pending_order["action"] == "BUY":
                # 防线 B: 涨停检查 (在 _execute_buy 内部)
                record, cash = self._execute_buy(...)
                # ...

            elif pending_order["action"] == "SELL":
                # 防线 A: T+1 检查
                if buy_date is not None and not self._check_t1(buy_date, ts):
                    # T+1 未达，结转至下一交易日
                    pending_order["status"] = "RETRYING"
                else:
                    # 防线 B: 跌停检查 (在 _execute_sell 内部)
                    record, cash = self._execute_sell(...)
                    # ...

    # ── Step 2: 更新权益 ──
    equity = cash + position * closes[idx]
    # ... 更新 equity_curve, daily_returns ...

    # ── Step 3: 收集当日信号 → 生成挂单 ──
    # 互斥排队保护 (INV-6): RETRYING 状态拦截买入信号
    if pending_order is not None and pending_order.get("status") == "RETRYING":
        # 拦截买入信号
        # ...
    else:
        # 优先级：LPPL SELL > BUY > 其他 SELL
        # ...
```

**✅ 执行顺序清晰**：
- Step 1: 执行挂单（T+1 延迟）→ 防线 A/B/C 检查
- Step 2: 更新权益（使用收盘价）
- Step 3: 收集信号 → 生成挂单（下一交易日执行）

### 2.2 **防线 B: 涨跌停检查**

**check_limit_price 实现** (`unified_models.py:236-262`)：
```python
def check_limit_price(
    price: float,
    pre_close: float,
    action: str,
    symbol: str = "",
    name: Optional[str] = None,
) -> bool:
    """防线 B: 涨跌停检查"""
    if pre_close <= 0:
        return True

    ratio = price / pre_close
    board = get_board_type(symbol, name)
    up_ratio, down_ratio = MarketConstants.LIMIT_RATIO.get(
        board, MarketConstants.LIMIT_RATIO["main"]
    )
    tol = MarketConstants.PRICE_TOLERANCE

    if action == "BUY" and ratio >= up_ratio - tol:
        return False  # 涨停拒绝买入
    if action == "SELL" and ratio <= down_ratio + tol:
        return False  # 跌停拒绝卖出
    return True
```

**LIMIT_RATIO 常量** (`shared/constants/market.py:79-85`)：
```python
LIMIT_RATIO = {
    "st": (1.05, 0.95),      # ST股 ±5%
    "sci_tech": (1.20, 0.80), # 科创板 ±20%
    "gem": (1.20, 0.80),      # 创业板 ±20%
    "beijing": (1.30, 0.70),  # 北交所 ±30%
    "main": (1.10, 0.90),     # 主板 ±10%
}
```

**✅ 涨跌停规则完整**：
- 5 种板块类型：st/sci_tech/gem/beijing/main
- 涨跌幅限制：±5%/±20%/±20%/±30%/±10%
- 价格容差：0.001（0.1%）

### 2.3 **防线 A: T+1 检查**

**check_t1_compliance 实现** (`unified_models.py:217-233`)：
```python
def check_t1_compliance(
    buy_date: Optional[pd.Timestamp],
    sell_date: pd.Timestamp,
    trade_calendar: Any,
) -> bool:
    """防线 A: T+1 检查 — 交易日序号差 >= 1"""
    if buy_date is None:
        return True

    buy_ord = buy_date.toordinal()
    sell_ord = sell_date.toordinal()

    if sell_ord <= buy_ord:
        return False  # 同日或更早，违反 T+1

    next_td = get_next_trading_day(buy_date, trade_calendar)
    return sell_date.toordinal() >= next_td.toordinal()  # 必须在下一个交易日或之后
```

**UnifiedBacktestEngine._check_t1 调用** (`unified_engine.py:255`)：
```python
if buy_date is not None and not self._check_t1(buy_date, ts):
    logger.debug(f"T+1拒绝: buy={buy_date} sell={ts}")
    pending_order["status"] = "RETRYING"  # T+1 未达，结转至下一交易日
    pending_order["retry_count"] = pending_order.get("retry_count", 0) + 1
```

**✅ T+1 逻辑正确**：
- 买入日期为 None 时允许卖出（无持仓）
- 同日卖出拒绝（sell_ord <= buy_ord）
- 必须在下一个交易日或之后卖出
- T+1 未达时挂单结转（RETRYING 状态）

### 2.4 **防线 D: 资金永不透支**

**_execute_buy 资金检查** (`unified_engine.py:571-585`)：
```python
# 防线 D: 资金不足时自动减量
if total_cost > cash_available:
    # 重新计算可买股数
    affordable = int((cash_available - commission - transfer_fee) / exec_price)
    shares = (affordable // lot_size) * lot_size
    if shares <= 0:
        return None, cash_available
    value = exec_price * shares
    commission = self._calc_commission(value)
    transfer_fee = self._calc_transfer_fee(value, symbol)
    total_cost = value + commission + transfer_fee

# 防线 D: 最终检查
if total_cost > cash_available:
    return None, cash_available

remaining_cash = cash_available - total_cost
```

**✅ 资金检查严格**：
- 第一次检查：资金不足时自动减量（重新计算可买股数）
- 第二次检查：最终检查（减量后仍不足则拒绝）
- 永不透支：`remaining_cash = cash_available - total_cost`

### 2.5 **防线 F: 滑点计算**

**calculate_slippage 实现** (`unified_models.py:288-309`)：
```python
def calculate_slippage(
    price: float,
    is_buy: bool,
    trade_volume: int,
    avg_daily_volume: float,
    slippage_rate: float,
) -> float:
    """防线 F: 滑点计算 — 使用交易量, 不是日均量"""
    impact = 0.0
    if avg_daily_volume > 0 and trade_volume > 0:
        ratio = trade_volume / avg_daily_volume
        impact = min(0.001 * (ratio ** 0.5), 0.02)  # 平方根冲击模型，上限 2%

    total = slippage_rate + impact
    if is_buy:
        return price * (1 + total)  # 买入滑点向上
    else:
        return price * (1 - total)  # 卖出滑点向下
```

**✅ 滑点模型正确**：
- 基础滑点率：`slippage_rate`（默认 0.001 = 0.1%）
- 市场冲击：`0.001 * sqrt(trade_volume / avg_daily_volume)`，上限 2%
- 方向正确：买入滑点向上（买高），卖出滑点向下（卖低）
- 使用交易量而非日均量（更真实）

---

## 3. Name 传播（依赖链追踪）

### 3.1 **UnifiedBacktestEngine 输入输出**

**输入** (`unified_engine.py:149-167`)：
```python
def run(
    self,
    df: pd.DataFrame,
    signals: List[TradingSignal],
    symbol: str = "",
    name: Optional[str] = None,
    benchmark_returns: Optional[pd.Series] = None,
) -> BacktestResult:
    """运行回测"""
```

**输出** (`unified_engine.py:433-441`)：
```python
return BacktestResult(
    trades=trades,
    equity_curve=equity_curve,
    daily_returns=daily_returns,
    initial_capital=self.initial_capital,
    final_cash=cash,
    metadata=metadata,
    benchmark_return=benchmark_return,
)
```

**下游消费者**：
- `UnifiedResearchPipeline.run()` (`research_pipeline.py:410-424`)
- `sensitivity_scan()` (`unified_engine.py:100-147`)

### 3.2 **UnifiedMatchingEngine 向量化路径**

**fill_buy 方法** (`unified_matching_engine.py:182-242`)：
```python
def fill_buy(
    self,
    prices: np.ndarray,
    shares_requested: np.ndarray,
    cash_available: np.ndarray,
    pre_closes: np.ndarray,
    symbols: np.ndarray,
    timestamps: np.ndarray,
    volumes: np.ndarray,
    avg_daily_volumes: np.ndarray,
    names: np.ndarray | None = None,
    trading_days_listed: np.ndarray | None = None,
) -> FillResult:
    """向量化买入撮合"""
    limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols, names, trading_days_listed)
    limit_rejected = limit_status["is_limit_up"]
    volume_zero = np.array([vol <= 0 for vol in volumes], dtype=bool)

    exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=True, symbols=symbols, quantities=shares_requested, timestamps=timestamps)

    values = exec_prices * shares_requested
    commissions = np.maximum(values * self.commission_rate, self.min_commission)
    fee_mask = has_transfer_fee_mask(symbols)  # 过户费
    transfer_fees = np.where(fee_mask, values * TRANSFER_FEE_PCT, 0.0)
    total_costs = values + commissions + transfer_fees

    cash_shortfall = total_costs > cash_available
    lot_sizes = np.array([get_board_rule(s).lot_size for s in symbols], dtype=np.int64)
    shares_adj = np.where(
        ~cash_shortfall,
        shares_requested,
        np.where(
            cash_available > commissions + transfer_fees,
            ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // lot_sizes * lot_sizes,
            0,
        ),
    )
    shares_adj = np.maximum(shares_adj, 0)
    shares_adj = np.where(limit_rejected, 0, shares_adj)

    values = exec_prices * shares_adj
    commissions = np.maximum(values * self.commission_rate, self.min_commission)
    transfer_fees = np.where(fee_mask, values * TRANSFER_FEE_PCT, 0.0)
    total_costs = values + commissions + transfer_fees

    rejected_mask = limit_rejected | volume_zero | (shares_adj <= 0)
    shares_adj = np.where(rejected_mask, 0, shares_adj)
    return FillResult(
        executed_shares=shares_adj,
        exec_prices=exec_prices,
        commissions=np.where(rejected_mask, 0, commissions),
        stamp_duties=np.zeros(n),  # 买入无印花税
        slippages=np.where(rejected_mask, 0, exec_prices - prices),
        transfer_fees=np.where(rejected_mask, 0, transfer_fees),
        rejected_mask=rejected_mask,
        t1_violation_mask=np.zeros(n, dtype=bool),  # 向量化路径不检查 T+1（由调用方负责）
        limit_violation_mask=limit_rejected,
        cash_shortfall_mask=cash_shortfall,
    )
```

**✅ 向量化实现完整**：
- 防线 B: `compute_limit_status_vectorized` 检查涨跌停
- 防线 C: `volume_zero` 检查停牌
- 防线 D: `cash_shortfall` 检查资金不足并自动减量
- 防线 E: `commissions`, `transfer_fees` 计算成本（买入无印花税）
- 防线 F: `compute_execution_prices` 计算滑点
- 防线 G: `lot_sizes` 整手取整

### 3.3 **Fast Path vs Slow Path 分支条件**

**compute_limit_status_vectorized 分支** (`unified_matching_engine.py:136-180`)：
```python
def compute_limit_status_vectorized(
    self,
    prices: np.ndarray,
    pre_closes: np.ndarray,
    symbols: np.ndarray,
    names: np.ndarray | None = None,
    trading_days_listed: np.ndarray | None = None,
) -> Dict[str, np.ndarray]:
    # Fast path: no names or trading_days_listed — fully vectorized
    if names is None and trading_days_listed is None:
        # 预计算所有 symbol 的 board_type，避免 5n 次重复调用
        board_types = np.array([get_board_type(s) for s in symbols])
        for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
            board_mask = board_types == board_type
            mask = board_mask & valid
            is_limit_up |= mask & (price_ratios >= up_r - tol)
            is_limit_down |= mask & (price_ratios <= down_r + tol)
        return {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}

    # Slow path: element-wise for ST name detection and/or IPO special rules
    for i in range(n):
        if not valid[i]:
            continue

        # Board type with ST name detection
        bt = get_board_type(symbols[i])
        if names is not None and names[i]:
            nu = names[i].upper()
            if any(nu.startswith(p) for p in ("ST", "*ST", "S*ST")):
                bt = "st"
        pr = price_ratios[i]

        # IPO special rules
        if trading_days_listed is not None and trading_days_listed[i] > 0:
            tdl = int(trading_days_listed[i])
            if bt == "main" and tdl == 1:
                # 主板 IPO 首日: +44%/-36%
                if pr >= 1.44 - tol:
                    is_limit_up[i] = True
                if pr <= 0.64 + tol:
                    is_limit_down[i] = True
                continue
            if bt in ("sci_tech", "gem") and tdl <= 5:
                continue  # 科创板/创业板前 5 日无涨跌停限制
            if bt == "beijing" and tdl == 1:
                continue  # 北交所首日无涨跌停限制

        up_r, down_r = MarketConstants.LIMIT_RATIO.get(bt, MarketConstants.LIMIT_RATIO["main"])
        if pr >= up_r - tol:
            is_limit_up[i] = True
        if pr <= down_r + tol:
            is_limit_down[i] = True

    return {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}
```

**✅ 分支条件清晰**：
- **Fast Path**（完全向量化）：`names is None and trading_days_listed is None`
- **Slow Path**（逐元素循环）：需要 ST name 检测或 IPO 特殊规则
- **IPO 特殊规则**：
  - 主板首日：+44%/-36%
  - 科创板/创业板前 5 日：无涨跌停限制
  - 北交所首日：无涨跌停限制

---

## 4. Name 变异（边界条件与异常）

### 4.1 **30 日坏账清退 (INV-7)**

**跌停拒卖 30 日上限** (`unified_engine.py:283-315`)：
```python
# 防线 B: 跌停拒卖强制结转 (Mandatory Rollover, INV-6)
retry_count = pending_order.get("retry_count", 0) + 1
if retry_count < 30 and position > 0:
    pending_order["status"] = "RETRYING"
    pending_order["retry_count"] = retry_count
    pending_order["shares"] = position  # 同步最新持仓
    logger.info(
        f"跌停拒卖强制结转 (RETRYING {retry_count}/30): "
        f"{ts} {symbol} shares={position}"
    )
else:
    logger.warning(
        f"跌停结转达到30日上限，执行终局坏账清退 (0元出清, INV-7): {ts} {symbol} shares={position}"
    )
    if position > 0:
        bad_debt_record = TradeRecord(
            timestamp=ts,
            action="SELL",
            symbol=symbol,
            price=0.0,  # 0 元出清
            shares=position,
            commission=0.0,
            stamp_duty=0.0,
            transfer_fee=0.0,
            slippage=exec_price_raw,
            pnl=-position_cost * position,  # 全额亏损
            reason="BAD_DEBT_LIMIT_DOWN_30D_EXPIRED",
        )
        trades.append(bad_debt_record)
        position = 0
        position_cost = 0.0
        buy_date = None
    pending_order = None
```

**✅ 坏账清退机制**：
- 触发条件：跌停拒卖连续 30 日（`retry_count >= 30`）
- 清退方式：0 元出清（`price=0.0`）
- 亏损计算：`pnl = -position_cost * position`（全额亏损）
- 标记原因：`BAD_DEBT_LIMIT_DOWN_30D_EXPIRED`

### 4.2 **互斥排队保护 (INV-6)**

**RETRYING 状态拦截买入信号** (`unified_engine.py:327-335`)：
```python
# 互斥排队保护 (INV-6): 若存在处于 RETRYING 结转状态的清仓卖单，严禁被 BUY 信号覆写
if pending_order is not None and pending_order.get("status") == "RETRYING":
    day_signals = signal_map.get(date_key, [])
    for sig in day_signals:
        if sig.action == "BUY":
            logger.warning(
                f"标的 {symbol} 存在结转中的清仓卖单 (RETRYING), 拦截买入信号"
            )
    # 保持 pending_order 结转状态不变，次日集合竞价置顶重试
```

**✅ 互斥保护机制**：
- 触发条件：`pending_order.status == "RETRYING"`（清仓卖单结转中）
- 拦截行为：所有 BUY 信号被拦截（logger.warning）
- 保持状态：pending_order 不变，次日继续重试

### 4.3 **Survivorship Bias Check**

**退市检查** (`unified_engine.py:389-403`)：
```python
# Survivorship bias check (conditional — only if delist data available)
survivorship_warning = ""
try:
    from ...data.managers.stock_metadata_manager import StockMetadataManager
    mgr = StockMetadataManager()
    delist_date = mgr.get_delist_date(symbol) if hasattr(mgr, 'get_delist_date') else None
    if delist_date is not None:
        last_bar = pd.to_datetime(df["date"].iloc[-1]) if len(df) else None
        if last_bar is not None and pd.to_datetime(delist_date) <= last_bar:
            survivorship_warning = (
                f"Symbol delisted {delist_date}; "
                f"backtest extends to {last_bar.date()}"
            )
except (OSError, KeyError, TypeError):
    pass

metadata: Dict[str, Any] = {
    # ... 其他字段 ...
}
if survivorship_warning:
    metadata["survivorship_warning"] = survivorship_warning
```

**✅ 幸存者偏差检查**：
- 检查股票是否已退市（`get_delist_date`）
- 如果退市日期 <= 回测结束日期，添加警告到 metadata
- 异常时静默跳过（try/except）

### 4.4 **非交易日权益更新**

**非交易日处理** (`unified_engine.py:196-205`)：
```python
# 跳过非交易日 (周末/节假日)
if not self.trade_calendar.is_trading_day(ts):
    # 非交易日也更新权益 (使用收盘价)
    equity = cash + position * closes[idx]
    equity_curve.append(equity)
    if prev_equity > 0:
        daily_returns.append((equity - prev_equity) / prev_equity)
    else:
        daily_returns.append(0.0)
    prev_equity = equity
    continue
```

**✅ 边界条件处理**：
- 非交易日不执行挂单（跳过 Step 1）
- 非交易日更新权益（使用收盘价）
- 防止除零（`if prev_equity > 0`）

---

## 5. Name 治理（可观测性与可测试性）

### 5.1 **结构化日志**

**防线拦截日志**：
- 防线 A: `logger.debug(f"T+1拒绝: buy={buy_date} sell={ts}")` (`unified_engine.py:256`)
- 防线 B: `logger.debug(f"涨停拒绝买入: {timestamp}")` (`unified_engine.py:549`)
- 防线 C: `logger.debug(f"停牌拒绝: {date_key} volume=0")` (`unified_engine.py:218`)
- 坏账清退: `logger.warning(f"跌停结转达到30日上限...")` (`unified_engine.py:294`)
- 互斥保护: `logger.warning(f"标的 {symbol} 存在结转中的清仓卖单...")` (`unified_engine.py:332`)

**✅ 可观测性**：
- 每条防线拦截都有日志记录
- 使用 debug 级别（防线 A/B/C）和 warning 级别（坏账清退/互斥保护）
- 包含关键信息（时间戳、价格、持仓）

### 5.2 **Metadata 审计追踪**

**metadata 字段** (`unified_engine.py:405-420`)：
```python
metadata: Dict[str, Any] = {
    "symbol": symbol if symbol else "",
    "engine": "unified",
    "start_date": str(pd.to_datetime(df["date"].iloc[0]).date()) if len(df) else "",
    "end_date": str(pd.to_datetime(df["date"].iloc[-1]).date()) if len(df) else "",
    "signal_count": len(signals),
    "trading_days_count": trading_days_count,
    "final_equity": float(equity_curve[-1]) if equity_curve else 0.0,
    "max_position": max_position,
    "commission_rate": self.commission_rate,
    "stamp_duty_rate": self.stamp_duty_rate,
    "slippage_rate": self.slippage_rate,
    "min_commission": self.min_commission,
}
if survivorship_warning:
    metadata["survivorship_warning"] = survivorship_warning
```

**✅ 审计追踪**：
- 记录回测参数（commission_rate/stamp_duty_rate/slippage_rate）
- 记录统计信息（signal_count/trading_days_count/max_position）
- 记录幸存者偏差警告（如果有）

### 5.3 **敏感性分析**

**sensitivity_scan 方法** (`unified_engine.py:100-147`)：
```python
def sensitivity_scan(
    self,
    df: pd.DataFrame,
    signals: List[TradingSignal],
    symbol: str = "",
    name: Optional[str] = None,
    slippages: Optional[List[float]] = None,
    commissions: Optional[List[float]] = None,
    benchmark_returns: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """滑点/佣金敏感性分析"""
    def _factory(comm: float, slp: float) -> UnifiedBacktestEngine:
        return UnifiedBacktestEngine(
            initial_capital=self.initial_capital,
            commission_rate=comm,
            stamp_duty_rate=self.stamp_duty_rate,
            slippage_rate=slp,
            min_commission=self.min_commission,
            trade_calendar=self.trade_calendar,
        )

    return run_sensitivity_scan(
        engine_factory=_factory,
        df=df,
        signals=signals,
        symbol=symbol,
        name=name,
        slippages=slippages,
        commissions=commissions,
        benchmark_returns=benchmark_returns,
    )
```

**✅ 可测试性**：
- 支持滑点/佣金敏感性分析
- 工厂模式创建不同参数的引擎
- 返回 DataFrame 便于分析

---

## 6. 端到端数据流追踪

### 6.1 **典型路径 1：正常买入**

```
TradingSignal(action="BUY", shares=1000, reason="Wyckoff SPRING", timestamp=T)
    ↓ UnifiedBacktestEngine.run(df, signals, symbol="600519.SH")
    ↓ _index_signals_by_date(signals) → signal_map[T] = [signal]
    ↓ for idx in range(len(df)):
  ├─ Step 3 (T日): 收集信号 → pending_order = {action: "BUY", shares: 1000, status: "PENDING"}
  ├─ Step 1 (T+1日): 执行挂单
  │   ├─ vol > 0 (非停牌) ✓
  │   ├─ _execute_buy(price_raw=opens[T+1], shares_requested=1000, ...)
  │   │   ├─ 防线 B: _check_limit(price, pre_close, "BUY") → True (非涨停) ✓
  │   │   ├─ 防线 F: _calc_slippage(price, is_buy=True, trade_volume=1000, avg_daily_volume) → exec_price
  │   │   ├─ 防线 G: lot_size=100, shares = (1000 // 100) * 100 = 1000 ✓
  │   │   ├─ 防线 E: commission = max(value * 0.0003, 5.0), transfer_fee = value * 0.00001
  │   │   ├─ 防线 D: total_cost <= cash_available ✓
  │   │   └─ return TradeRecord(action="BUY", price=exec_price, shares=1000, commission, transfer_fee, slippage)
  │   └─ position += 1000, cash -= total_cost
  └─ Step 2: equity = cash + position * closes[T+1]
```

### 6.2 **典型路径 2：涨停拒绝买入**

```
TradingSignal(action="BUY", shares=1000, timestamp=T)
    ↓ UnifiedBacktestEngine.run(df, signals, symbol="600519.SH")
    ↓ for idx in range(len(df)):
  ├─ Step 3 (T日): pending_order = {action: "BUY", shares: 1000, status: "PENDING"}
  ├─ Step 1 (T+1日): 执行挂单
  │   ├─ vol > 0 (非停牌) ✓
  │   └─ _execute_buy(price_raw=opens[T+1], shares_requested=1000, ...)
  │       ├─ 防线 B: _check_limit(price, pre_close, "BUY", symbol)
  │       │   ├─ ratio = price / pre_close = 1.10 (涨停)
  │       │   ├─ up_ratio = 1.10 (主板)
  │       │   ├─ ratio >= up_ratio - tol → True
  │       │   └─ return False (涨停拒绝买入)
  │       └─ return None, cash_available
  └─ pending_order = None (Auto-Cancel, 不结转)
```

### 6.3 **典型路径 3：跌停拒卖 + 30日坏账清退**

```
TradingSignal(action="SELL", shares=1000, timestamp=T)
    ↓ UnifiedBacktestEngine.run(df, signals, symbol="600519.SH", position=1000)
    ↓ for idx in range(len(df)):
  ├─ Step 3 (T日): pending_order = {action: "SELL", shares: 1000, status: "PENDING", retry_count: 0}
  ├─ Step 1 (T+1日): 执行挂单
  │   ├─ vol > 0 (非停牌) ✓
  │   ├─ 防线 A: _check_t1(buy_date, ts) → True (T+1 已达) ✓
  │   └─ _execute_sell(price_raw=opens[T+1], shares_to_sell=1000, ...)
  │       ├─ 防线 B: _check_limit(price, pre_close, "SELL", symbol)
  │       │   ├─ ratio = price / pre_close = 0.90 (跌停)
  │       │   ├─ down_ratio = 0.90 (主板)
  │       │   ├─ ratio <= down_ratio + tol → True
  │       │   └─ return False (跌停拒绝卖出)
  │       └─ return None, cash
  │   └─ pending_order.status = "RETRYING", retry_count = 1
  ├─ Step 1 (T+2日): 重试
  │   └─ 跌停拒绝 → retry_count = 2
  ├─ ... (连续 30 日跌停) ...
  ├─ Step 1 (T+30日): retry_count = 30
  │   └─ retry_count >= 30 → 执行终局坏账清退 (INV-7)
  │       ├─ bad_debt_record = TradeRecord(action="SELL", price=0.0, shares=1000, pnl=-position_cost * 1000, reason="BAD_DEBT_LIMIT_DOWN_30D_EXPIRED")
  │       ├─ trades.append(bad_debt_record)
  │       └─ position = 0, pending_order = None
  └─ Step 2: equity = cash (持仓已清零)
```

### 6.4 **典型路径 4：互斥排队保护**

```
TradingSignal(action="SELL", shares=1000, timestamp=T)  # 清仓卖单
    ↓ UnifiedBacktestEngine.run(df, signals, symbol="600519.SH", position=1000)
    ↓ for idx in range(len(df)):
  ├─ Step 3 (T日): pending_order = {action: "SELL", shares: 1000, status: "PENDING"}
  ├─ Step 1 (T+1日): 跌停拒绝 → pending_order.status = "RETRYING", retry_count = 1
  ├─ Step 3 (T+1日): 
  │   ├─ pending_order.status == "RETRYING" → 互斥排队保护 (INV-6)
  │   ├─ day_signals 包含 BUY 信号
  │   ├─ for sig in day_signals: if sig.action == "BUY": logger.warning("拦截买入信号")
  │   └─ 保持 pending_order 结转状态不变
  └─ Step 1 (T+2日): 继续重试卖单
```

---

## 7. 发现的问题

### 7.1 **CRITICAL 级别**

无

### 7.2 **HIGH 级别**

无

### 7.3 **MEDIUM 级别**

#### M1: LPPL SELL 优先级遗留逻辑

**位置**：`unified_engine.py:337-348`  
**问题**：信号处理优先级中，LPPL SELL 被优先处理（在 BUY 之前），但 LPPL 已被 Monte-Carlo 证伪为零预测力引擎（`adapters.py:72-75`）。  
**代码**：
```python
# 优先级：LPPL SELL > BUY > 其他 SELL
if pending_order is None:
    for sig in day_signals:
        if (sig.action == "SELL" and position > 0 and pending_order is None
                and sig.reason and "lppl" in sig.reason.lower()):  # LPPL SELL 优先
            pending_order = {...}
            break
if pending_order is None:
    for sig in day_signals:
        if sig.action == "BUY" and position == 0:  # BUY 其次
            pending_order = {...}
            break
if pending_order is None:
    for sig in day_signals:
        if sig.action == "SELL" and position > 0:  # 其他 SELL 最后
            pending_order = {...}
            break
```

**影响**：LPPL SELL 优先于 BUY 和其他 SELL，但 LPPL 默认 `diagnostic_only=True`（不产 SELL 强平）。如果上游适配器错误地产生了 LPPL SELL（非 diagnostic），这里会优先执行。  
**规则 4 冲突**：CLAUDE.md Rule 4 要求"禁止硬编码 pass"，这里是硬编码 LPPL 优先级。  
**修复建议**：移除 LPPL 特殊优先级，统一按信号优先级仲裁（SELL > BUY）：
```python
# 移除 LPPL 特殊优先级
if pending_order is None:
    for sig in day_signals:
        if sig.action == "SELL" and position > 0:
            pending_order = {...}
            break
if pending_order is None:
    for sig in day_signals:
        if sig.action == "BUY" and position == 0:
            pending_order = {...}
            break
```

### 7.4 **LOW 级别**

#### L1: UnifiedMatchingEngine 不检查 T+1

**位置**：`unified_matching_engine.py:239`  
**问题**：`fill_buy` 方法返回的 `FillResult` 中，`t1_violation_mask=np.zeros(n, dtype=bool)`，表示向量化路径不检查 T+1。  
**影响**：向量化路径（`UnifiedMatchingEngine`）依赖调用方负责 T+1 检查，如果调用方忘记检查，可能导致 T+1 违规。  
**说明**：`fill_sell` 方法检查 T+1（`unified_matching_engine.py:266-281`），但 `fill_buy` 不检查（因为买入不需要 T+1）。  
**修复建议**：在文档中明确说明向量化路径的 T+1 责任分工。

#### L2: 涨跌停检查使用比例而非绝对价格

**位置**：`unified_models.py:236-262`  
**问题**：`check_limit_price` 使用价格比例（`ratio = price / pre_close`）而非绝对涨跌停价格（`up_limit_price`, `down_limit_price`）。  
**影响**：可能与交易所实际涨跌停价格（四舍五入到 0.01 元）有微小差异。  
**对比**：`limit_checker.py:124-127` 计算了绝对涨跌停价格（`_round_limit_price`），但 `unified_models.py` 只使用比例。  
**修复建议**：考虑使用绝对涨跌停价格（与交易所一致）：
```python
up_limit_price = _round_limit_price(pre_close * up_ratio, price_tick)
down_limit_price = _round_limit_price(pre_close * down_ratio, price_tick)
if action == "BUY" and price >= up_limit_price - tol:
    return False
if action == "SELL" and price <= down_limit_price + tol:
    return False
```

---

## 8. 与深度验证报告的交叉验证

### 8.1 **已验证的事实**

1. **七大防线**：✅ 已确认（A/B/C/D/E/F/G，`unified_engine.py:7-15`）
2. **T+1 检查**：✅ 已确认（`unified_models.py:217-233`, 交易日序号差 >= 1）
3. **涨跌停规则**：✅ 已确认（main±10%/sci_tech±20%/gem±20%/beijing±30%/st±5%，`shared/constants/market.py:79-85`）
4. **停牌拦截**：✅ 已确认（`unified_engine.py:216-229`, volume=0 不成交）
5. **资金永不透支**：✅ 已确认（`unified_engine.py:571-585`, 自动减量 + 最终检查）
6. **非对称成本**：✅ 已确认（印花税仅卖方，`unified_models.py:270-280`）
7. **滑点方向**：✅ 已确认（买高卖低，`unified_models.py:288-309`）
8. **整手取整**：✅ 已确认（`unified_engine.py:559-563`, lot_size=100/200）
9. **30 日坏账清退**：✅ 已确认（`unified_engine.py:283-315`, INV-7, 0 元出清）
10. **互斥排队保护**：✅ 已确认（`unified_engine.py:327-335`, INV-6, RETRYING 拦截买入）
11. **向量化快路径 vs 慢路径**：✅ 已确认（`unified_matching_engine.py:136-180`, names 和 trading_days_listed 是否存在）

### 8.2 **新发现的问题**

1. **LPPL SELL 优先级遗留逻辑**（MEDIUM）：LPPL SELL 优先于 BUY，但 LPPL 已被证伪
2. **向量化路径不检查 T+1**（LOW）：依赖调用方负责
3. **涨跌停检查使用比例而非绝对价格**（LOW）：可能与交易所实际价格有微小差异

### 8.3 **工作流文档问题验证**

**工作流文档声称**（`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:231`）：
> LPPL SELL 优先级遗留逻辑 (unified_engine.py:340) — 确认是否已修复？

**实际答案**：**未修复**。LPPL SELL 优先级逻辑仍然存在（`unified_engine.py:339-340`），LPPL SELL 被优先处理（在 BUY 之前）。但 LPPL 默认 `diagnostic_only=True`，正常情况下不会产生 SELL 信号，因此实际影响有限。

---

## 9. 结论

### 9.1 **回测撮合模块健康度评估**

- **A股规则实现**：✅ 优秀（七大防线完整、板块涨跌停规则完整、T+1 严格）
- **异常处理**：✅ 优秀（30 日坏账清退、互斥排队保护、资金永不透支）
- **向量化实现**：✅ 优秀（Fast Path/Slow Path 分支、向量化成本计算）
- **可观测性**：✅ 良好（结构化日志、metadata 审计追踪、敏感性分析）
- **遗留逻辑**：⚠️ 良好（LPPL SELL 优先级遗留，但实际影响有限）

### 9.2 **关键风险**

1. **LPPL SELL 优先级遗留**（MEDIUM）：与 Rule 4 冲突，但实际影响有限（LPPL 默认 diagnostic_only）
2. **涨跌停检查精度**（LOW）：使用比例而非绝对价格，可能有微小差异

### 9.3 **修复优先级**

1. **P1**：移除 LPPL SELL 优先级遗留逻辑（M1）
2. **P2**：考虑使用绝对涨跌停价格（L2）
3. **P3**：文档化向量化路径的 T+1 责任分工（L1）

---

**分析人**：Claude (Anthropic)  
**审查时间**：2026-11-24  
**代码引用精度**：所有引用精确到行号  
**交叉验证基础**：DEEP_VERIFICATION_9_REPORTS_20261124.md (98.9% 准确率)  
**下一步**：工作流 5（风控合规模块 N2N 分析）
---

# 独立第三方评审意见（量化算法专家视角）

> 评审基线：代码 commit `434aab1` · 评审人：量化算法/Alpha 研究员

## 评审结论：**部分可信**

A股微观规则覆盖是三份里最扎实的，七大防线 + IPO/ST/板块规则基本对得上；但"零 HIGH" + 对几处真实方法论隐患轻描淡写，且**完全没有任何回测绩效结果**。

## 优点
1. A股规则覆盖完整且基本准确：板块涨跌停（main±10%/科创创业±20%/北证±30%/ST±5%）与 `LIMIT_RATIO` 一致；IPO 特殊规则（主板首日 +44/−36%、科创创业前 5 日无限制、北证首日无限制）体现真实领域知识；印花税仅卖方、最低佣金 5 元、整手 100 股均正确。
2. Fast/Slow Path 向量化分支讲清楚了。
3. 敢于标出真问题（M1 LPPL SELL 优先级遗留），并正确指出与 Rule 4"禁止硬编码"的冲突。
4. 异常路径有亮点：30 日跌停坏账清退（INV-7）、RETRYING 互斥排队保护（INV-6）、资金永不透支二次检查。

## 问题清单

**HIGH — H1：'零 CRITICAL/HIGH'与若干方法论隐患并存，评级过松。** 下列 M 级问题里，至少 M1（win_rate 口径）和 M3（成本率时变性）在长周期 A 股回测里能造成**实质性绩效失真**，却被压到 LOW/MEDIUM 甚至当"✅"。一份只夸不疑的回测评审价值有限。

**HIGH — H2：全报告无任何回测结果。** 详尽描述撮合机器，却**没有一条 equity curve、没有一个 Sharpe / 胜率 / 回撤 / 年化实测值**。委托书要的是"撮合假设是否成立"的验证——**唯一方式就是跑出来看，报告停在了"代码看起来对"**。

**MEDIUM — M1：win_rate / profit_factor 口径在加仓(金字塔)下有偏。** §1.3 定义 `closed = [t for t in trades if action=="SELL"]; win_rate = wins/len(closed)`——每笔 SELL 记一笔平仓。但 FSM 有 PYRAMID 状态、引擎支持多次 BUY，**多次买入 + 一次清仓**时分母既不等于交易轮次也不等于持仓批次，盈亏配对是错的。报告把 §1.3 标为"✅ 指标计算完整"。

**MEDIUM — M2：30 日跌停 0 元出清（INV-7）是极端会计假设，会扭曲绩效。** 连续 30 日跌停拒卖后 `price=0.0` 全额清零，会**系统性高估尾部亏损**。作为保守假设可接受，但报告必须点明"这是会计约定、会实质影响极端情形结果"，而非当亮点罗列。

**MEDIUM — M3：unified_engine 用固定 stamp_duty_rate，未用 cost_model 的时变印花税。** `cost_model.py` 明确有 `get_stamp_tax_pct(date)`（2023-08-28 前 0.1%、之后 0.05%），而 `unified_engine.py:73` 的 `stamp_duty_rate` 是构造时固定的；向量化路径 `unified_matching_engine.py:39` 同样固定 `0.0005`。**两条撮合路径都没体现印花税历史变化**，跨 2023-08-28 回测时 2023 年前卖出成本被低估（用万5算本应千1）。报告大谈"非对称成本 ✅"却完全没提税率时间一致性。

**MEDIUM — M4：幸存者偏差检查实际是'空转'，报告夸成'✅ 优秀'。** §4.3 `get_delist_date` 拿不到就 `except: pass` 静默跳过，且**仅往 metadata 塞一条 warning 字符串，并不剔除/处理退市股**。即只要元数据管理器不可用，退市股就照常留在样本里且无任何标记。§8.1 把它列为"✅ 已确认"的正面事实，掩盖了"这只是 best-effort 警告、不构成对幸存者偏差的修正"。

**LOW — L-A**：滑点模型参数（系数 0.001、上限 2%、基础 0.001）全是裸常数，无经验标定或敏感性（`sensitivity_scan` 工具存在但报告未给结果）。**L-B**：未提及除权/除息对 `pre_close` 的影响——涨跌停判定 `ratio=price/pre_close` 依赖前复权/除权调整，是 A 股回测经典坑。

## 需对照代码确认的关键声明
1. win_rate/profit_factor 在加仓 + 部分平仓下的实际配对逻辑（是否有 position 批次追踪）。
2. unified_engine / unified_matching_engine 是否在别处按 `trade_date` 调用 `get_stamp_tax_pct`。
3. `get_delist_date` 在生产数据源下实际能否取到（决定幸存者检查是真防护还是空转）。
4. `sensitivity_scan` 是否真被跑过并产出结论（工具存在 ≠ 用过）。
5. §8.1 声称"✅ 已确认"的 11 条是否都有对应测试覆盖（Rule 1 要求 80% 覆盖 + Rule 6 要求 A 股规则改动需专项测试）。

---

# 独立第三方评审意见（资深 A 股交易员视角）

> 评审基线：代码 commit `434aab1` · 评审人：资深 A 股交易员

## 评审结论：**部分可信**

七大防线的**骨架**建模得比多数业余回测框架认真，但撮合被简化成"次日开盘价 ± 滑点"这一理想化假设，且报告自评"无 CRITICAL/HIGH"过于宽松，漏掉两处会真实扭曲收益的撮合失真。

## 优点
1. T+1 / 停牌 / 资金不透支 / 印花税仅卖方 / 整手取整 / 滑点方向（买高卖低）确实落地成代码；滑点用**当根成交量而非日均量**做冲击是加分项。
2. 涨跌停覆盖 5 类板块 + IPO 特殊规则，这层细节多数框架根本没有。
3. "跌停卖不掉"没被假装成"按收盘价成交"，而是 RETRYING 结转 + 30 日后坏账清退，并配套互斥排队保护。
4. 自曝 LPPL SELL 优先级遗留（M1）与文档声称"已修复"实际"未修复"的矛盾，没有粉饰。

## 问题清单

**HIGH — H1：一字板/涨跌停的撮合判定口径失真，且报告未讨论'开板'情形。**
挂单统一在"次根 bar 的 `opens[idx]`"执行，涨跌停判定用 `ratio = 开盘价/昨收` 落在涨跌停比例即整单拒绝/结转。真实 A 股里**"开盘涨停/跌停"≠"全天一字板"**——开盘涨停常会开板（可成交），开盘跌停也可能盘中撬开。当前逻辑把"开盘价触板"一律整单 cancel（买）或结转（卖），方向一刀切。对买入偏保守（漏掉能成交的开板板），但报告把这描述成"涨跌停拦截：涨停不买入"却**没讨论"开盘触板但盘中开板"该如何撮合**，回避了撮合真实性最关键的一段。

**HIGH — H2：滑点模型对流动性差的标的严重低估，上限 2% 是拍脑袋。**
`impact = min(0.001 * (ratio ** 0.5), 0.02)` 上限封顶 2%，对主板大盘蓝筹够用，但小市值/ST/流动性差的票真实冲击远超 2%。交易员关心"小票策略在回测里被系统性高估收益"，报告对此**没有任何敏感性警示**（`sensitivity_scan` 存在但未给"提高滑点后收益衰减多少"的任何数据）。典型"回测赚钱、实盘不可复现"风险点，被轻描淡写。

**MEDIUM — M1：ST ±5% 的检测在向量化快路径被整体跳过。**
Fast Path 条件 `names is None and trading_days_listed is None` 时直接返回，ST name 检测只在 Slow Path 执行。若调用方没传 `names`，ST 股会被当主板按 ±10% 判定，**±5% 限制形同虚设**——这是"放水"。报告把 Fast/Slow Path 只当性能优化描述，**没指出这条正确性隐患**。

**MEDIUM — M2：涨跌停用比例而非交易所绝对涨停价（报告自评 LOW，低估）。**
L2 承认用 `price/pre_close` 比例，而 `limit_checker.py:124-127` 已实现四舍五入到 0.01 元的绝对涨停价 `_round_limit_price`。交易所涨停价是按 0.01 元取整后的绝对价，低价股上比例法边界判定可能差一档。报告归为 LOW，对"边界单被误判拒单/放行"的实盘影响估计不足。

**MEDIUM — M3：印花税/过户费具体费率未在报告中给出数值，无法核对是否为最新。**
2.x 与 8.1 只说"印花税仅卖方""过户费 `value * TRANSFER_FEE_PCT`"，**从未写出费率数字**（印花税现行为卖出 0.05%，过户费为成交金额 0.001%）。交易员无法确认用的是 2023 年 8 月减半后的印花税率；若沿用旧 0.1%，卖出成本被高估。

**LOW**：30 日坏账清退是"诚实"但假设极端（连续 30 个跌停板真实 A 股除财务造假退市股外极罕见），报告未说明其触发频率。

## 需对照代码确认的关键声明
- 印花税率、佣金率、过户费 `TRANSFER_FEE_PCT` 的实际数值及计费基数（过户费应为面值 1 元计，非成交额）。
- ST 快路径（names 缺失）是否真会被实际调用路径命中。
- `_execute_sell` 卖出成本里是否也扣了印花税+过户费，且滑点后价格正确。
- `sensitivity_scan` 是否真被用来做滑点/佣金敏感性并留有结果。
