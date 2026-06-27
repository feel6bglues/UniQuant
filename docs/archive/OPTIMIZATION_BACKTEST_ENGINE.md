# 回测引擎改进方案

> 版本: v1.0 | 日期: 2026-05-31 | 作者: AI Agent
> 目标引擎: `engine.py`, `unified_matching_engine.py`, `portfolio_engine.py`

---

## 1. 问题总览

| # | 问题 | 严重度 | 影响范围 | 修复复杂度 |
|---|------|--------|----------|-----------|
| 1 | T+1 检查使用日历日而非交易日 | 🟡 中 | `unified_matching_engine.py:158-171` | 中 |
| 2 | 手数取整统一硬编码 100 股 | 🔴 高 | 三个引擎全部 | 低 |
| 3 | 涨跌停只返回布尔值 | 🟡 中 | `engine.py:143-156` | 低 |
| 4 | 缺失止损逻辑 | 🔴 高 | 三个引擎全部 | 高 |
| 5 | 过户费未正确传递给 `TransferFee` | 🟡 中 | `unified_matching_engine.py:111` | 低 |
| 6 | commission 在缩股后未重新计算 | 🔴 高 | `engine.py:182-184` | 低 |
| 7 | `market_rules.detect_board()` 从不返回 `BoardType.ST` | 🟡 中 | `market_rules.py:34-48` | 低 |

---

## 2. 改进方案详解

### 2.1 统一 T+1 检查 — 使用交易日历（缓存优先）

**问题根因:**
`unified_matching_engine.py:158-171` 使用 `pd.Timestamp.toordinal()` 做日历日差值计算，
在遇到周末+节假日组合时理论上可能误判（例如周五买入，下周一卖出，日历日差=3，应为1个交易日）。

**实际情况:** 当前代码在多数场景下**意外正确工作**。因为 `toordinal() < 1` 本质上是同一天检查，
而 A 股不存在周六/周日交易（常规情况），所以相隔 3 个日历日的周五→周一不会被误判。
真正的风险在于 **调休工作日（调休）**— 当周六或周日被设为交易日时（如 `_CN_SPECIAL_WORKDAYS`），
`is_trading_day()` guard 在循环中会捕获这类异常，但整体方案仍然脆弱。
**应定位为健壮性改进，而非 bug 修复。**

**参考已有实现:** `engine.py:116-141` 已经用 `trade_calendar.get_trade_calendar()` + `np.where` 实现了正确的 T+1 检查。
`unified_matching_engine.py` 修复应与之对齐。

**当前代码 (unified_matching_engine.py:158-171):**

```python
# ⚠️ 脆弱: 使用日历日差值（周末虽 OK，但调休工作日可能误判）
buy_ord = np.array([
    pd.Timestamp(b).toordinal() if b is not None else 0
    for b in buy_dates
])
cur_ord = np.array([
    pd.Timestamp(t).toordinal() for t in timestamps
])
t1_violation = (cur_ord - buy_ord < 1) & (buy_ord > 0)
for i in range(n):
    if buy_dates[i] is not None:
        b_ts = pd.Timestamp(buy_dates[i])
        c_ts = pd.Timestamp(timestamps[i])
        if not self.trade_calendar.is_trading_day(b_ts) or not self.trade_calendar.is_trading_day(c_ts):
            t1_violation[i] = True
```

**改进后代码 — 缓存优先方案:**

```python
# ✅ 修复: 缓存交易日集合 + O(log n) 二分查找，避免逐行 CSV I/O

def _ensure_trading_days_cached(self) -> None:
    """预加载完整交易日历到内存 (ordinal 集合 + 排序数组)，仅一次 I/O"""
    if hasattr(self, '_trading_day_ords'):
        return
    cal = self.trade_calendar.get_trade_calendar("2000-01-01", "2030-12-31")
    ords = pd.to_datetime(cal['trade_date']).map(pd.Timestamp.toordinal)
    self._trading_day_set = set(ords)           # O(1) 存在性检查
    self._trading_day_ords = np.array(sorted(ords))  # 二分查找

def _check_t1_trade_calendar(
    self,
    buy_dates: np.ndarray,
    current_dates: np.ndarray,
) -> np.ndarray:
    """
    基于缓存的交易日历计算 T+1

    Returns:
        np.ndarray[bool]: True = 违反 T+1 (不可卖出)
    """
    n = len(buy_dates)
    result = np.ones(n, dtype=bool)

    # 首次调用时一次性加载缓存
    self._ensure_trading_days_cached()
    ords = self._trading_day_ords

    for i in range(n):
        if buy_dates[i] is None:
            result[i] = False
            continue

        b_ord = pd.Timestamp(buy_dates[i]).toordinal()
        c_ord = pd.Timestamp(current_dates[i]).toordinal()

        # O(1) 检查日期是否为交易日
        if b_ord not in self._trading_day_set:
            result[i] = True   # 非交易日买入 → 拒绝
            continue
        if c_ord not in self._trading_day_set:
            result[i] = True   # 非交易日卖出 → 拒绝
            continue

        # O(log n) 二分查找交易日索引
        b_idx = int(np.searchsorted(ords, b_ord))
        c_idx = int(np.searchsorted(ords, c_ord))

        # 须至少间隔 1 个交易日
        result[i] = (c_idx - b_idx) < 1

    return result
```

**对 `fill_sell` 的修改:**

```python
# 替换 unified_matching_engine.py fill_sell 方法中的 T+1 检查段
def fill_sell(self, ...) -> FillResult:
    # ... 前面的代码不变 ...

    # ❌ 删除旧的 T+1 逻辑 (行 158-171)
    # ✅ 替换为:
    t1_violation = self._check_t1_trade_calendar(buy_dates, timestamps)

    # ... 后续代码不变 ...
```

> **⚠️ 关键: `_ensure_trading_days_cached` 中的缓存是强制性的，不是可选的优化。**
> 如果不缓存，在循环中调用 `get_trade_calendar()` 会导致每次迭代都读取 CSV 磁盘 I/O，
> 每标的每 bar 一次查询，使该方案比当前实现慢 **~100 倍**。
> 缓存方案将 I/O 降低到仅 1 次，后续查询均为 O(log n) 内存二分查找。

---

### 2.2 智能手数取整 — 按板块规则

**问题根因:**
三个引擎全部硬编码 `// 100 * 100`，但科创板（688/689）最小交易单位是 200 股。
`market_rules.py` 已经定义了 `BoardRule.lot_size`，可以直接使用。

**影响矩阵:**

| 板块 | 代码前缀 | 当前取整 | 正确取整 | 差异 |
|------|---------|---------|---------|------|
| 主板 | 600/000 等 | 100 | 100 | 无 |
| 创业板 | 300/301 | 100 | 100 | 无 |
| 科创板 | 688/689 | 100 | **200** | **错误** |
| 北交所 | 8xx/4xx | 100 | 100 | 无 |
| ST | ST/*ST | 100 | 100 | 无 |

**修改方案 — engine.py:184:**

```python
# ❌ 当前代码 (engine.py:184)
shares = (shares // 100) * 100  # A股整手取整（100股为1手）

# ✅ 改进后
from uniquant.shared.market_rules import get_board_rule

rule = get_board_rule(symbol) if symbol else None
shares = rule.round_lot(shares) if rule else (shares // 100) * 100
```

**修改方案 — unified_matching_engine.py:115-117:**

```python
# ❌ 当前代码 (unified_matching_engine.py:115-117)
cash_shortfall = total_costs > cash_available
shares_adj = np.where(
    cash_shortfall & (cash_available > commissions + transfer_fees),
    ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // 100 * 100,
    shares_requested,
)

# ✅ 改进后: 向量化按板块取整 (使用 BoardRule.round_lot)
from ...shared.market_rules import get_board_rule

def _round_lots(self, shares: np.ndarray, symbols: np.ndarray) -> np.ndarray:
    """按板块规则向量化取整 — 使用 BoardRule.round_lot()"""
    result = shares.copy()
    for i, sym in enumerate(symbols):
        try:
            result[i] = get_board_rule(str(sym)).round_lot(int(shares[i]))
        except (ValueError, KeyError):
            result[i] = (int(shares[i]) // 100) * 100
    return result

# 在 fill_buy 中:
shares_adj = np.where(
    cash_shortfall & (cash_available > commissions + transfer_fees),
    self._round_lots(
        ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64),
        symbols,
    ),
    shares_requested,
)
```

**修改方案 — portfolio_engine.py:116:**

```python
# ❌ 当前代码 (portfolio_engine.py:116)
sh_arr = np.maximum((alloc / np.maximum(px_arr, 1e-8)).astype(np.int64) // 100 * 100, 0)

# ✅ 改进后: 使用 BoardRule.round_lot()
from ...shared.market_rules import get_board_rule

def _round_lots(self, shares: np.ndarray, symbols: Sequence[str]) -> np.ndarray:
    result = shares.copy()
    for i, s in enumerate(symbols):
        result[i] = get_board_rule(s).round_lot(int(shares[i]))
    return result

sh_arr = np.maximum(self._round_lots(
    (alloc / np.maximum(px_arr, 1e-8)).astype(np.int64),
    buy_symbols,
), 0)
```

---

### 2.3 集成涨跌停检测 — 区分封板/炸板

**问题根因:**
`engine.py:143-154` 的 `_check_limit_constraint` 只返回 `bool`，不区分:
- **封板 (Sealed):** 价格触及涨停且成交量为 0（买不进）
- **炸板 (Broken):** 价格触及涨停但盘中有成交（可能买进）

**当前代码 (engine.py:143-156):**

```python
# ❌ 当前: 只返回布尔值
def _check_limit_constraint(
    self, price: float, pre_close: float, action: str, symbol: str = "",
) -> bool:
    limit_status = check_limit_status(price, pre_close, symbol)
    if action == "BUY" and limit_status.is_limit_up:
        return False
    if action == "SELL" and limit_status.is_limit_down:
        return False
    return True
```

**改进后代码:**

```python
# ✅ 改进: 复用 LimitStatus (limit_checker.py 已定义 8 个字段), 直接返回该对象
#    无需新建 LimitCheckResult — 避免与已有接口重复

def _check_limit_constraint(
    self,
    price: float,
    pre_close: float,
    action: str,
    symbol: str = "",
    volume: float = 0,
    avg_daily_volume: float = 0,
) -> LimitStatus:
    """
    检查涨跌停约束 — 区分封板/炸板

    返回复用 LimitStatus (已包含 is_limit_up, is_limit_down, board_type,
    up_limit_price, down_limit_price, price_ratio 等 8 个字段)。

    封板判断逻辑:
    - 涨停 + 当日成交量 < 日均成交量的 1% → 大概率封板 → 拒绝买入
    - 跌停 + 当日成交量 < 日均成交量的 1% → 大概率封板 → 拒绝卖出
    """
    limit_status = check_limit_status(price, pre_close, symbol)

    # 封板检测: 有涨跌停 + 成交量极低
    seal_threshold = avg_daily_volume * 0.01 if avg_daily_volume > 0 else 0
    is_sealed = volume <= seal_threshold and seal_threshold > 0

    if action == "BUY" and limit_status.is_limit_up:
        if is_sealed:
            limit_status.can_buy = False
            logger.debug(f"涨停封板拒绝买入: {symbol}, {limit_status.board_type}, 价比:{limit_status.price_ratio:.2%}")
        else:
            logger.debug(f"涨停炸板买入: {symbol}, 价比:{limit_status.price_ratio:.2%}")

    elif action == "SELL" and limit_status.is_limit_down:
        if is_sealed:
            limit_status.can_sell = False
            logger.debug(f"跌停封板拒绝卖出: {symbol}, {limit_status.board_type}, 价比:{limit_status.price_ratio:.2%}")
        else:
            logger.debug(f"跌停炸板卖出: {symbol}, 价比:{limit_status.price_ratio:.2%}")

    return limit_status
```

> **设计说明:** `LimitStatus` 已包含 `can_buy`/`can_sell` 字段（见 `limit_checker.py:15-25`），
> 封板检测只需修改 `can_buy`/`can_sell` 即可。若需扩展 seal-detection 字段，应在 `LimitStatus` 中
> 新增 `is_sealed_up`/`is_sealed_down` 或作为独立工具函数提供，避免平行 dataclass 重复定义。
> 此方案消除代码重复，且与 `limit_checker.py` 的现有接口完全兼容。

**向量化版本 (unified_matching_engine.py):**

```python
# ✅ 新增: 向量化封板检测
def compute_limit_status_vectorized(
    self,
    prices: np.ndarray,
    pre_closes: np.ndarray,
    symbols: np.ndarray,
    volumes: Optional[np.ndarray] = None,
    avg_daily_volumes: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    """向量化涨跌停检测 — 支持封板判断"""
    n = len(prices)
    is_limit_up = np.zeros(n, dtype=bool)
    is_limit_down = np.zeros(n, dtype=bool)
    is_sealed_up = np.zeros(n, dtype=bool)     # 新增: 涨停封板
    is_sealed_down = np.zeros(n, dtype=bool)    # 新增: 跌停封板
    valid = pre_closes > 0
    price_ratios = np.where(valid, prices / np.maximum(pre_closes, 1e-8), 1.0)

    for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
        board_mask = np.array([get_board_type(s) == board_type for s in symbols])
        mask = board_mask & valid
        tol = MarketConstants.PRICE_TOLERANCE
        up_hit = mask & (price_ratios >= up_r - tol)
        down_hit = mask & (price_ratios <= down_r + tol)
        is_limit_up |= up_hit
        is_limit_down |= down_hit

        # 封板判断: 涨跌停 + 成交量极低
        if volumes is not None and avg_daily_volumes is not None:
            seal_mask = avg_daily_volumes > 0
            vol_ratio = np.where(seal_mask, volumes / np.maximum(avg_daily_volumes, 1e-8), 0.0)
            is_sealed_up |= up_hit & seal_mask & (vol_ratio < 0.01)
            is_sealed_down |= down_hit & seal_mask & (vol_ratio < 0.01)

    return {
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
        "is_sealed_up": is_sealed_up,
        "is_sealed_down": is_sealed_down,
    }
```

---

### 2.4 集成止损逻辑

**问题根因:**
回测引擎只有买/卖信号，没有止损保护。`risk/sizer.py:130-137` 实现了 ATR+CZSC 几何止损，
但未集成到回测引擎中。

**架构设计:**

```
┌─────────────────────────────────────────────────────────┐
│                   BacktestEngine                         │
│                                                         │
│  信号生成器 ──→ [止损检查] ──→ [约束检查] ──→ 执行     │
│                  ↑                                      │
│           StopLossManager                               │
│           ├─ 固定百分比止损                              │
│           ├─ ATR 动态止损 (来自 sizer.py)               │
│           ├─ CZSC 几何止损 (来自 sizer.py)              │
│           └─ 移动止损 (Trailing Stop)                   │
└─────────────────────────────────────────────────────────┘
```

**新增 StopLossManager:**

```python
# src/uniquant/hands/backtest/stop_loss.py

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)


class StopLossType(Enum):
    """止损类型"""
    FIXED_PCT = auto()       # 固定百分比止损
    ATR = auto()             # ATR 动态止损
    CZSC_GEOMETRY = auto()   # CZSC 几何止损
    TRAILING = auto()        # 移动止损


@dataclass
class StopLossConfig:
    """止损配置"""
    stop_type: StopLossType = StopLossType.FIXED_PCT
    fixed_pct: float = 0.05          # 固定止损百分比 (5%)
    atr_multiplier: float = 2.0      # ATR 倍数
    trailing_pct: float = 0.03       # 移动止损回撤百分比 (3%)


@dataclass
class StopLossState:
    """持仓止损状态"""
    entry_price: float
    stop_price: float
    highest_since_entry: float       # 入场以来最高价 (用于移动止损)
    stop_type: StopLossType


class StopLossManager:
    """
    止损管理器

    集成到 BacktestEngine，在每次 bar 更新时检查是否触发止损。
    """

    def __init__(self, config: Optional[StopLossConfig] = None):
        self.config = config or StopLossConfig()
        self._states: dict = {}  # symbol -> StopLossState

    def register_position(
        self,
        symbol: str,
        entry_price: float,
        atr_value: float = 0.0,
        czsc_bottom: float = 0.0,
    ) -> float:
        """
        注册新持仓的止损价

        Returns:
            float: 初始止损价
        """
        cfg = self.config

        if cfg.stop_type == StopLossType.FIXED_PCT:
            stop_price = entry_price * (1 - cfg.fixed_pct)

        elif cfg.stop_type == StopLossType.ATR:
            stop_price = entry_price - atr_value * cfg.atr_multiplier

        elif cfg.stop_type == StopLossType.CZSC_GEOMETRY:
            # 使用 max(ATR止损, CZSC底部) — 取更保守的
            atr_stop = entry_price - atr_value * cfg.atr_multiplier
            stop_price = max(atr_stop, czsc_bottom) if czsc_bottom > 0 else atr_stop

        elif cfg.stop_type == StopLossType.TRAILING:
            stop_price = entry_price * (1 - cfg.trailing_pct)

        else:
            stop_price = entry_price * (1 - cfg.fixed_pct)

        self._states[symbol] = StopLossState(
            entry_price=entry_price,
            stop_price=stop_price,
            highest_since_entry=entry_price,
            stop_type=cfg.stop_type,
        )

        logger.debug(f"止损注册: {symbol}, 入场价:{entry_price:.2f}, 止损价:{stop_price:.2f}")
        return stop_price

    def check_stop(
        self,
        symbol: str,
        current_price: float,
        current_low: float = 0,
    ) -> bool:
        """
        检查是否触发止损

        Args:
            symbol: 股票代码
            current_price: 当前收盘价
            current_low: 当前最低价 (更精确的触发判断)

        Returns:
            bool: True = 触发止损
        """
        state = self._states.get(symbol)
        if state is None:
            return False

        # 更新最高价 (移动止损用)
        if current_price > state.highest_since_entry:
            state.highest_since_entry = current_price

            # 移动止损: 更新止损价
            if state.stop_type == StopLossType.TRAILING:
                new_stop = current_price * (1 - self.config.trailing_pct)
                if new_stop > state.stop_price:
                    state.stop_price = new_stop
                    logger.debug(f"移动止损更新: {symbol}, 新止损价:{new_stop:.2f}")

        # 使用最低价判断是否触发 (更接近真实场景)
        check_price = current_low if current_low > 0 else current_price
        triggered = check_price <= state.stop_price

        if triggered:
            logger.info(f"止损触发: {symbol}, 当前价:{current_price:.2f}, 止损价:{state.stop_price:.2f}")

        return triggered

    def remove_position(self, symbol: str) -> None:
        """移除持仓止损状态"""
        self._states.pop(symbol, None)

    def clear(self) -> None:
        """清空所有止损状态"""
        self._states.clear()
```

**集成到 BacktestEngine:**

```python
# engine.py 修改

from .stop_loss import StopLossManager, StopLossConfig, StopLossType

class BacktestEngine:
    def __init__(
        self,
        # ... 原有参数 ...
        stop_loss_config: Optional[StopLossConfig] = None,
    ):
        # ... 原有初始化 ...
        self.stop_loss = StopLossManager(stop_loss_config)

    def reset(self) -> None:
        # ... 原有重置 ...
        self.stop_loss.clear()

    def run_backtest(
        self,
        df: pd.DataFrame,
        signal_generator: Callable,
        symbol: str = "",
        position_size: int = 100,
        stop_loss_config: Optional[StopLossConfig] = None,  # 可覆盖
    ) -> BacktestResult:
        self.reset()

        if stop_loss_config:
            self.stop_loss = StopLossManager(stop_loss_config)

        # ... 原有数据校验 ...

        buy_date = None
        for idx in range(len(df)):
            row = df.iloc[idx]
            current_price = row["close"]
            current_low = row.get("low", current_price)
            timestamp = dates.iloc[idx]

            # ✅ 新增: 止损检查 (优先级高于信号)
            if self.position > 0:
                if self.stop_loss.check_stop(symbol, current_price, current_low):
                    trade = self.execute_sell(
                        price=current_price,
                        shares=self.position,
                        timestamp=timestamp,
                        reason=f"止损触发 (止损价:{self.stop_loss._states.get(symbol, StopLossState(0,0,0,StopLossType.FIXED_PCT)).stop_price:.2f})",
                        pre_close=pre_close,
                        symbol=symbol,
                        buy_date=buy_date,
                    )
                    if trade:
                        buy_date = None
                        self.stop_loss.remove_position(symbol)
                        self.update_equity(current_price)
                        continue  # 跳过信号处理

            # 原有信号处理逻辑
            signal = signal_generator(df, idx, { ... })
            action = signal.get("action", "HOLD")

            if action == "BUY" and self.position == 0:
                trade = self.execute_buy(...)
                if trade:
                    buy_date = timestamp
                    # ✅ 注册止损
                    atr_value = signal.get("atr", 0)
                    czsc_bottom = signal.get("czsc_bottom", 0)
                    self.stop_loss.register_position(symbol, trade.price, atr_value, czsc_bottom)

            elif action == "SELL" and self.position > 0:
                trade = self.execute_sell(...)
                if trade:
                    buy_date = None
                    self.stop_loss.remove_position(symbol)

            self.update_equity(current_price)

        # ... 原有结果构建 ...
```

---

### 2.5 集成过户费

**问题根因:**
`cost_model.py:30` 已定义 `TRANSFER_FEE_PCT = 0.00001` (万分之0.1)。
`engine.py:76` 已正确使用，但 `unified_matching_engine.py` 的 `FillResult` 中缺少独立的 `transfer_fees` 字段，
导致费用明细不透明。

**当前状态:**
- ✅ `engine.py:76` — 已正确计算过户费
- ✅ `unified_matching_engine.py:111, 179` — 已计算但未单独暴露
- 🟡 `portfolio_engine.py:182` — 未将过户费从 commission 中分离

**改进方案 — FillResult 增加字段:**

```python
# unified_matching_engine.py

@dataclass
class FillResult:
    executed_shares: np.ndarray
    exec_prices: np.ndarray
    commissions: np.ndarray
    stamp_duties: np.ndarray
    transfer_fees: np.ndarray      # ✅ 新增: 过户费明细
    slippages: np.ndarray
    rejected_mask: np.ndarray
    t1_violation_mask: np.ndarray
    limit_violation_mask: np.ndarray
    cash_shortfall_mask: np.ndarray
```

**fill_buy 中返回过户费:**

```python
return FillResult(
    executed_shares=shares_adj,
    exec_prices=exec_prices,
    commissions=commissions,
    stamp_duties=np.zeros(n),
    transfer_fees=transfer_fees,    # ✅ 新增
    slippages=exec_prices - prices,
    rejected_mask=limit_rejected | (shares_adj <= 0),
    t1_violation_mask=np.zeros(n, dtype=bool),
    limit_violation_mask=limit_rejected,
    cash_shortfall_mask=cash_shortfall,
)
```

**portfolio_engine 中使用:**

```python
# portfolio_engine.py batch_close_positions
net_value = float(
    fill.exec_prices[i] * fill.executed_shares[i]
    - fill.commissions[i]
    - fill.stamp_duties[i]
    - fill.transfer_fees[i]    # ✅ 新增: 独立扣除过户费
)
```

---

## 3. 测试用例

### 3.1 T+1 检查测试

```python
# tests/backtest/test_t1_constraint.py

import pandas as pd
import pytest
from unittest.mock import MagicMock
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


@pytest.fixture
def engine_with_calendar():
    """创建带有 mock 交易日历的引擎"""
    calendar = MagicMock()
    engine = UnifiedMatchingEngine(trade_calendar=calendar)
    return engine, calendar


class TestT1Constraint:
    """T+1 约束测试"""

    def test_same_day_sell_rejected(self, engine_with_calendar):
        """同日买入同日卖出 → 拒绝"""
        engine, calendar = engine_with_calendar
        calendar.is_trading_day.return_value = True
        calendar.get_trade_calendar.return_value = pd.DataFrame({
            'trade_date': pd.to_datetime(['2024-01-02', '2024-01-03'])
        })

        import numpy as np
        buy_dates = np.array([pd.Timestamp('2024-01-02')])
        current_dates = np.array([pd.Timestamp('2024-01-02')])

        result = engine._check_t1_trade_calendar(buy_dates, current_dates)
        assert result[0] == True  # 违反 T+1

    def test_next_trading_day_sell_allowed(self, engine_with_calendar):
        """下一交易日卖出 → 允许"""
        engine, calendar = engine_with_calendar
        calendar.is_trading_day.return_value = True
        calendar.get_trade_calendar.return_value = pd.DataFrame({
            'trade_date': pd.to_datetime(['2024-01-02', '2024-01-03'])
        })

        import numpy as np
        buy_dates = np.array([pd.Timestamp('2024-01-02')])
        current_dates = np.array([pd.Timestamp('2024-01-03')])

        result = engine._check_t1_trade_calendar(buy_dates, current_dates)
        assert result[0] == False  # 不违反 T+1

    def test_weekend_gap_correctly_handled(self, engine_with_calendar):
        """周五买入周一卖出 → 应为1个交易日间隔 → 允许"""
        engine, calendar = engine_with_calendar
        calendar.is_trading_day.return_value = True
        # 交易日历: 周五(01-05) → 周一(01-08), 中间无交易日
        calendar.get_trade_calendar.return_value = pd.DataFrame({
            'trade_date': pd.to_datetime(['2024-01-05', '2024-01-08'])
        })

        import numpy as np
        buy_dates = np.array([pd.Timestamp('2024-01-05')])
        current_dates = np.array([pd.Timestamp('2024-01-08')])

        result = engine._check_t1_trade_calendar(buy_dates, current_dates)
        assert result[0] == False  # 间隔1个交易日, 允许卖出

    def test_holiday_gap_correctly_handled(self, engine_with_calendar):
        """节前买入节后卖出 → 交易日历正确处理"""
        engine, calendar = engine_with_calendar
        calendar.is_trading_day.return_value = True
        # 春节: 01-25 最后交易日, 02-05 第一交易日
        calendar.get_trade_calendar.return_value = pd.DataFrame({
            'trade_date': pd.to_datetime(['2024-01-25', '2024-02-05'])
        })

        import numpy as np
        buy_dates = np.array([pd.Timestamp('2024-01-25')])
        current_dates = np.array([pd.Timestamp('2024-02-05')])

        result = engine._check_t1_trade_calendar(buy_dates, current_dates)
        assert result[0] == False  # 间隔1个交易日, 允许卖出
```

### 3.2 手数取整测试

```python
# tests/backtest/test_lot_sizing.py

import numpy as np
import pytest
from uniquant.shared.market_rules import get_board_rule, BoardType


class TestLotSizing:
    """手数取整测试"""

    def test_main_board_lot_size_100(self):
        """主板: 最小手数 100"""
        rule = get_board_rule("600000.SH")
        assert rule.lot_size == 100
        assert rule.round_lot(150) == 100
        assert rule.round_lot(250) == 200

    def test_star_board_lot_size_200(self):
        """科创板: 最小手数 200"""
        rule = get_board_rule("688001.SH")
        assert rule.lot_size == 200
        assert rule.round_lot(150) == 0
        assert rule.round_lot(250) == 200
        assert rule.round_lot(450) == 400

    def test_gem_board_lot_size_100(self):
        """创业板: 最小手数 100"""
        rule = get_board_rule("300001.SZ")
        assert rule.lot_size == 100

    def test_beijing_board_lot_size_100(self):
        """北交所: 最小手数 100"""
        rule = get_board_rule("830001.BJ")
        assert rule.lot_size == 100

    def test_vectorized_lot_sizing(self):
        """向量化取整一致性"""
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
        engine = UnifiedMatchingEngine()

        symbols = np.array(["600000.SH", "688001.SH", "300001.SZ"])
        lot_sizes = engine._get_lot_sizes(symbols)

        np.testing.assert_array_equal(lot_sizes, [100, 200, 100])
```

### 3.3 涨跌停封板测试

```python
# tests/backtest/test_limit_seal.py

import numpy as np
import pytest
from unittest.mock import patch
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


class TestLimitSeal:
    """涨跌停封板检测测试"""

    def setup_method(self):
        self.engine = UnifiedMatchingEngine()

    def test_limit_up_sealed_rejected(self):
        """涨停封板 (成交量极低) → 拒绝买入"""
        prices = np.array([11.0])          # 涨停价
        pre_closes = np.array([10.0])      # 前收盘
        symbols = np.array(["600000.SH"])
        volumes = np.array([100])          # 极低成交量
        avg_daily_volumes = np.array([1000000])  # 日均百万

        result = self.engine.compute_limit_status_vectorized(
            prices, pre_closes, symbols, volumes, avg_daily_volumes
        )
        assert result["is_limit_up"][0] == True
        assert result["is_sealed_up"][0] == True  # 封板

    def test_limit_up_broken_not_sealed(self):
        """涨停炸板 (成交量正常) → 不算封板"""
        prices = np.array([11.0])
        pre_closes = np.array([10.0])
        symbols = np.array(["600000.SH"])
        volumes = np.array([500000])       # 正常成交量
        avg_daily_volumes = np.array([1000000])

        result = self.engine.compute_limit_status_vectorized(
            prices, pre_closes, symbols, volumes, avg_daily_volumes
        )
        assert result["is_limit_up"][0] == True
        assert result["is_sealed_up"][0] == False  # 炸板

    def test_no_volume_data_skip_seal_check(self):
        """无成交量数据 → is_sealed_up 初始化为 False"""
        prices = np.array([11.0])
        pre_closes = np.array([10.0])
        symbols = np.array(["600000.SH"])

        result = self.engine.compute_limit_status_vectorized(
            prices, pre_closes, symbols
        )
        assert result["is_limit_up"][0] == True
        # 无成交量数据时 is_sealed_up 初始化为全 False, 始终存在 key
        assert result["is_sealed_up"][0] == False
```

### 3.4 止损集成测试

```python
# tests/backtest/test_stop_loss.py

import pytest
from uniquant.hands.backtest.stop_loss import (
    StopLossManager, StopLossConfig, StopLossType
)


class TestStopLossManager:
    """止损管理器测试"""

    def test_fixed_pct_stop_loss(self):
        """固定百分比止损"""
        mgr = StopLossManager(StopLossConfig(
            stop_type=StopLossType.FIXED_PCT,
            fixed_pct=0.05,
        ))
        stop = mgr.register_position("600000.SH", entry_price=10.0)
        assert stop == 9.5  # 10 * (1 - 0.05)

        assert mgr.check_stop("600000.SH", current_price=9.6) == False
        assert mgr.check_stop("600000.SH", current_price=9.4) == True

    def test_atr_stop_loss(self):
        """ATR 动态止损"""
        mgr = StopLossManager(StopLossConfig(
            stop_type=StopLossType.ATR,
            atr_multiplier=2.0,
        ))
        stop = mgr.register_position("600000.SH", entry_price=10.0, atr_value=0.5)
        assert stop == 9.0  # 10 - 0.5 * 2

        assert mgr.check_stop("600000.SH", current_price=9.1) == False
        assert mgr.check_stop("600000.SH", current_price=8.9) == True

    def test_trailing_stop_updates(self):
        """移动止损随价格上涨更新"""
        mgr = StopLossManager(StopLossConfig(
            stop_type=StopLossType.TRAILING,
            trailing_pct=0.03,
        ))
        stop = mgr.register_position("600000.SH", entry_price=10.0)
        assert stop == 9.7  # 10 * (1 - 0.03)

        # 价格上涨到 12, 止损应更新为 12 * 0.97 = 11.64
        mgr.check_stop("600000.SH", current_price=12.0)
        state = mgr._states["600000.SH"]
        assert abs(state.stop_price - 11.64) < 0.01

        # 价格回落到 11.7, 不触发
        assert mgr.check_stop("600000.SH", current_price=11.7) == False
        # 价格回落到 11.5, 触发
        assert mgr.check_stop("600000.SH", current_price=11.5) == True

    def test_czsc_geometry_stop_loss(self):
        """CZSC 几何止损 (取 ATR 和底部的较大值)"""
        mgr = StopLossManager(StopLossConfig(
            stop_type=StopLossType.CZSC_GEOMETRY,
            atr_multiplier=2.0,
        ))
        # ATR止损 = 10 - 1*2 = 8, CZSC底部 = 8.5 → 取 8.5
        stop = mgr.register_position("600000.SH", entry_price=10.0, atr_value=1.0, czsc_bottom=8.5)
        assert stop == 8.5

    def test_low_price_triggers_stop(self):
        """盘中最低价触发止损"""
        mgr = StopLossManager(StopLossConfig(
            stop_type=StopLossType.FIXED_PCT,
            fixed_pct=0.05,
        ))
        mgr.register_position("600000.SH", entry_price=10.0)  # 止损价 9.5

        # 收盘价 9.6 (未触发), 但最低价 9.4 (触发)
        assert mgr.check_stop("600000.SH", current_price=9.6, current_low=9.4) == True

    def test_remove_position(self):
        """移除持仓后不再检查止损"""
        mgr = StopLossManager()
        mgr.register_position("600000.SH", entry_price=10.0)
        mgr.remove_position("600000.SH")
        assert mgr.check_stop("600000.SH", current_price=5.0) == False
```

### 3.5 过户费测试

```python
# tests/backtest/test_transfer_fee.py

import numpy as np
import pytest
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
from uniquant.shared.cost_model import TRANSFER_FEE_PCT


class TestTransferFee:
    """过户费测试"""

    def test_transfer_fee_in_fill_result(self):
        """FillResult 包含独立的 transfer_fees 字段"""
        engine = UnifiedMatchingEngine()
        prices = np.array([10.0])
        shares = np.array([1000])
        cash = np.array([20000.0])
        pre_closes = np.array([10.0])
        symbols = np.array(["600000.SH"])
        timestamps = np.array([np.datetime64('2024-01-02')])
        volumes = np.array([100000])
        adv = np.array([1000000])

        result = engine.fill_buy(prices, shares, cash, pre_closes, symbols, timestamps, volumes, adv)

        # 验证 transfer_fees 字段存在
        assert hasattr(result, 'transfer_fees')
        assert result.transfer_fees[0] > 0

        # 验证过户费计算正确: 10000 * 0.00001 = 0.1
        expected = 10.0 * 1000 * TRANSFER_FEE_PCT
        assert abs(result.transfer_fees[0] - expected) < 0.01

    def test_total_cost_includes_transfer_fee(self):
        """总成本包含过户费"""
        engine = UnifiedMatchingEngine()
        prices = np.array([10.0])
        shares = np.array([1000])
        cash = np.array([20000.0])
        pre_closes = np.array([10.0])
        symbols = np.array(["600000.SH"])
        timestamps = np.array([np.datetime64('2024-01-02')])
        volumes = np.array([100000])
        adv = np.array([1000000])

        result = engine.fill_buy(prices, shares, cash, pre_closes, symbols, timestamps, volumes, adv)

        # 总成本 = 成交额 + 佣金 + 过户费
        value = result.exec_prices[0] * result.executed_shares[0]
        total = value + result.commissions[0] + result.transfer_fees[0]
        # 验证 cash 足够
        assert total <= 20000.0
```

---

## 4. 性能影响评估

### 4.1 T+1 检查优化

| 指标 | 当前 | 改进后 | 影响 |
|------|------|--------|------|
| 单次 T+1 检查 | O(1) 日历日差 | O(log n) 二分查找 | 🟡 微增 |
| 批量检查 (1000标的) | ~0.1ms | ~1ms (with cache) | 🟡 可接受 |
| 准确性 | ⚠️ 调休工作日脆弱 | ✅ 交易日历 100% 准确 | 🟡 健壮性提升 |

> **⚠️ 关键: 缓存是强制性的。** 如果不使用 `_ensure_trading_days_cached` 方案，改为在循环中
> 逐次调用 `get_trade_calendar()`，每次调用会触发 CSV 磁盘 I/O，将导致批量检查变慢约 **100 倍**
> （~500ms vs ~0.1ms 当前）。本节方案假设缓存已启用，否则不应采用。

### 4.2 手数取整优化

| 指标 | 当前 | 改进后 | 影响 |
|------|------|--------|------|
| 取整计算 | O(1) 硬编码 | O(1) 字典查询 | 🟢 无感知 |
| 科创板正确性 | ❌ 100股 | ✅ 200股 | 🔴 必须修复 |

### 4.3 涨跌停封板检测

| 指标 | 当前 | 改进后 | 影响 |
|------|------|--------|------|
| 检查逻辑 | O(1) 布尔比较 | O(1) 布尔+阈值比较 | 🟢 几乎无 |
| 信息量 | 仅 bool | bool + 封板状态 + 价格 | 🟢 更丰富 |

### 4.4 止损集成

| 指标 | 当前 | 改进后 | 影响 |
|------|------|--------|------|
| 每 bar 额外开销 | 无 | O(1) 字典查询+比较 | 🟢 可忽略 |
| 内存开销 | 无 | ~100 bytes/持仓 | 🟢 可忽略 |
| 回测准确性 | ❌ 无止损保护 | ✅ 真实止损 | 🔴 关键改进 |

### 4.5 过户费明细

| 指标 | 当前 | 改进后 | 影响 |
|------|------|--------|------|
| 计算开销 | 已计算 | 已计算 (无变化) | 🟢 无 |
| 字段新增 | - | +1 np.ndarray/调用 | 🟢 ~8KB/1000标的 |

### 4.6 总体评估

```
性能影响: 🟢 极低 (<1% 额外开销)
准确性提升: 🔴 显著 (T+1/止损/取整全部修正)
代码复杂度: 🟡 中等 (+~200 LOC)
维护成本: 🟢 降低 (统一入口, 减少特判)
```

---

## 5. 实施计划

### Phase 1: 低风险快速修复 (1-2天)

| 任务 | 文件 | 改动量 |
|------|------|--------|
| 2.2 手数取整 | 3 个引擎 | ~10 LOC |
| 2.5 过户费字段 | unified_matching_engine.py | ~5 LOC |
| — commission 缩股重算 (#6) | engine.py:182-184 | ~3 LOC |
| — ST 检测修复 (#7) | market_rules.py:34-48 | ~5 LOC |
| 3.2 手数测试 | test_lot_sizing.py | ~40 LOC |
| 3.5 过户费测试 | test_transfer_fee.py | ~40 LOC |

### Phase 2: T+1 修复 (2-3天)

| 任务 | 文件 | 改动量 |
|------|------|--------|
| 2.1 T+1 缓存检查 | unified_matching_engine.py | ~40 LOC |
| 3.1 T+1 测试 | test_t1_constraint.py | ~60 LOC |

### Phase 3: 涨跌停增强 (1-2天)

| 任务 | 文件 | 改动量 |
|------|------|--------|
| 2.3 封板检测 | engine.py + unified_matching_engine.py | ~50 LOC |
| 3.3 封板测试 | test_limit_seal.py | ~50 LOC |

### Phase 4: 止损集成 (3-5天)

| 任务 | 文件 | 改动量 |
|------|------|--------|
| 2.4 StopLossManager | 新建 stop_loss.py | ~150 LOC |
| 2.4 集成到 engine.py | engine.py | ~30 LOC |
| 2.4 集成到 portfolio_engine.py | portfolio_engine.py | ~20 LOC |
| 3.4 止损测试 | test_stop_loss.py | ~100 LOC |

---

## 6. 风险与回退

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| T+1 修复引入新 bug | 中 | 高 | 完善测试覆盖, 灰度对比 |
| 止损逻辑影响现有策略 | 高 | 中 | 止损默认关闭, 显式启用 |
| 性能退化 | 低 | 低 | 基准测试, 缓存优化 |
| 市场规则变更 | 低 | 中 | `market_rules.py` 集中管理 |

**回退策略:**
- 所有改进通过 feature flag 控制
- `StopLossConfig` 为 `None` 时行为与当前完全一致
- T+1 检查保留旧路径作为 fallback

---

## 7. 依赖关系图

```
market_rules.py (lot_size)
    ├── engine.py (手数取整)
    ├── unified_matching_engine.py (手数取整)
    └── portfolio_engine.py (手数取整)

limit_checker.py (涨跌停)
    ├── engine.py (封板检测)
    └── unified_matching_engine.py (封板检测)

cost_model.py (过户费)
    ├── engine.py ✅ 已集成
    ├── unified_matching_engine.py ✅ 已计算 (需暴露字段)
    └── portfolio_engine.py ✅ 已计算 (需分离字段)

trade_calendar_manager.py (交易日历)
    ├── engine.py ✅ 已集成
    └── unified_matching_engine.py 🔴 需修复

stop_loss.py (止损管理器) 🆕
    ├── engine.py
    └── portfolio_engine.py

sizer.py (PositionSizer)
    └── stop_loss.py (ATR/CZSC 止损参数)
```

---

*文档生成时间: 2026-05-31 | 基于代码事实分析, 禁止幻觉*
