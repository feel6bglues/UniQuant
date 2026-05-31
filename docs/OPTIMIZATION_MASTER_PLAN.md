# UniQuant 总体优化方案

> 版本: v1.0 | 日期: 2026-05-31
> 基于源码级分析, 覆盖 data(65), brain(47), hands(32), risk(7), shared(37), services(28), ui(8), signal(6) 共 231 个源文件

---

## 1. 项目现状概览

### 1.1 模块就绪度

| 模块 | 文件数 | 状态 | 关键问题 |
|------|--------|------|----------|
| shared/ | 37 | ✅ 完整 | 板块识别分散(limit_checker + market_rules 两套) |
| data/ | 65 | ⚠️ 基本可用 | 缺复权因子 fq/ 子目录 |
| brain/ | 47 | ⚠️ 部分可用 (47文件, 含wyckoff 12/lppl 11/factors 9) | LPPL 单线程 DE, Factors 无并行 |
| hands/ | 32 | ⚠️ 基本可用 | 手数取整硬编码 100, T+1 日历不统一 |
| risk/ | 7 | ✅ 完整 | sizer 已使用 market_rules, 但止损缺流动性感知 |
| services/ | 28 | ⚠️ engine_factory 参数错配 | `__init__.py` 使用 `__getattr__` 延迟加载，无幽灵导入 |
| ui/ | 8 | ⚠️ 部分 | Streamlit 仪表盘 (1518 行) + 健康检查 |
| signal/ | 6 | 🔲 待规划 | 信号归一化/聚合, 无数据服务 |

> **AGENTS.md 过时警告**: AGENTS.md 声称 data/ 不存在/hands/ 仅空壳/risk/ 仅1文件 — 实际均远超此数，AGENTS.md 严重过时

### 1.2 代码热路径性能基线

| 热路径 | 当前耗时 | 瓶颈 |
|--------|----------|------|
| LPPL cost_function (×500K) | ~12.5s | numpy 分配 + 单线程 DE |
| Factors compute_all (10 因子) | ~76.5s | 双重串行循环 + 重复 groupby |
| MatchingEngine fill_buy/sell | ~O(n) | Python 循环取整 |
| 全市场扫描 (5000 股) | ~数分钟 | 无向量化, 逐股循环 |

---

## 2. 优化优先级矩阵

```
影响正确性 ─┬─ P0 手数取整 ──────────── 主板100/科创板200 混淆
            ├─ P0 T+1 检查 ──────────── 两套日历逻辑不一致
            └─ P0 复权因子 ──────────── fq/ 目录缺失, 前复权数据不可用

影响质量 ───┬─ P1 A 股规则模块 ──────── market_rules.py 未被回测引擎使用
            ├─ P1 回测引擎集成 ──────── engine.py 硬编码 //100
            └─ P1 LPPL Numba JIT ────── cost_function 未 JIT 编译

影响可维护性┬─ P2 统一板块识别 ──────── limit_checker + market_rules 两套
            ├─ P2 统一异常定义 ──────── exceptions.py 已完整但部分模块未使用
            └─ P2 线程安全 ──────────── GlobalConfig 单例无锁保护

功能增强 ───┬─ P3 因子扩展 ──────────── 量能因子/板块因子缺失
            ├─ P3 动态 T+1 惩罚 ──────── sizer 固定 1.2 倍
            └─ P3 流动性感知止损 ──────── 止损不考虑成交量
```

---

## 3. 依赖关系图

```
                    ┌─────────────────────────────────────┐
                    │           P0: 紧急修复               │
                    │  ┌─────────┐ ┌─────────┐ ┌────────┐│
                    │  │手数取整  │ │T+1 检查  │ │复权因子 ││
                    │  └────┬────┘ └────┬────┘ └───┬────┘│
                    └───────┼──────────┼──────────┼─────┘
                            │          │          │
                    ┌───────▼──────────▼──────────▼─────┐
                    │        P1: 重要改进                  │
                    │  ┌──────────────────┐  ┌─────────┐│
                    │  │A 股规则模块       │  │LPPL JIT ││
                    │  │(shared/a_share_  │  │(numba_  ││
                    │  │ rules.py)        │  │optimizer)││
                    │  └────────┬─────────┘  └─────────┘│
                    │           │                        │
                    │  ┌────────▼─────────┐              │
                    │  │回测引擎集成       │              │
                    │  │(engine.py 引用    │              │
                    │  │ a_share_rules)    │              │
                    │  └──────────────────┘              │
                    └─────────────────────────────────────┘
                            │
                    ┌───────▼─────────────────────────────┐
                    │        P2: 架构优化                   │
                    │  ┌─────────┐ ┌─────────┐ ┌────────┐│
                    │  │统一板块  │ │统一异常  │ │线程安全 ││
                    │  └─────────┘ └─────────┘ └────────┘│
                    └─────────────────────────────────────┘
                            │
                    ┌───────▼─────────────────────────────┐
                    │        P3: 功能增强                   │
                    │  ┌─────────┐ ┌─────────┐ ┌────────┐│
                    │  │因子扩展  │ │动态T+1  │ │流动性   ││
                    │  │         │ │惩罚     │ │止损     ││
                    │  └─────────┘ └─────────┘ └────────┘│
                    └─────────────────────────────────────┘
```

**关键依赖链**:
- Phase 0.0: 导入链健壮性检查 ──→ 一切测试 (先决条件)
- P0 手数取整 ──→ P1 A 股规则门面 ──→ P1 回测引擎集成
- P0 T+1 检查 ──→ P2 统一板块识别
- P1 A 股规则模块 ──→ P3 动态 T+1 惩罚
- P1 LPPL JIT ──→ P3 因子扩展 (性能基础)
- (新增) P0 engine.py:184 佣金未重算 ──→ P0.1 手数取整 (同位置修复)
- (新增) P0 market_rules ST 检测缺失 ──→ P2 统一板块识别

---

## P0.0 — 阻塞修复: 导入链健壮性 (先决条件)

> **第二轮核实更正**: 经实际代码验证，`services/__init__.py` 和 `brain/lppl/__init__.py` 均已使用 `try/except` + `__getattr__` 延迟加载机制，目标模块全部存在，**不会崩溃**。AGENTS.md (v0.3) 中的"幽灵导入"描述已过时。

### 现状核实

| 文件 | 实际机制 | 幽灵导入数 | 会崩溃？ |
|------|---------|:----------:|:-------:|
| `services/__init__.py` | `__getattr__` 延迟加载 (14 个目标) | 0 | ❌ |
| `brain/lppl/__init__.py` | `try/except` 条件导入 (3 个目标) | 0 | ❌ |
| `brain/fsm/fsm.py:20` | `try/except` 导入 `Indicators` (目标存在于 `brain/indicators/`) | 0 | ❌ |
| `services/analysis/engine_factory.py:24` | 传递 `orchestrator=` 给 7 个引擎，部分不接受此参数 | 0 (参数错配) | ❌ (有 try/except) |

### 仍需修复的问题

### Problem 1: engine_factory 构造函数参数错配
`engine_factory.py:24` 对所有引擎调用 `cls(orchestrator=self._orchestrator, **kwargs)`，
但 7 个引擎中部分不接受 `orchestrator` 参数。由于外层有 `try/except`，不会崩溃但会静默返回 `None`。

**修复**: 使用 `inspect.signature(cls)` 检查参数，或改为 `cls(**kwargs)` + 仅传入已知参数。

**估计**: 0.5-1 天。

---

## 4. P0 — 紧急修复 (影响正确性)

### 4.1 手数取整: 区分主板 100 股和科创板 200 股

**问题**: `engine.py:103` 和 `unified_matching_engine.py:97` 硬编码 `// 100 * 100`, 科创板(688/689)应为 200 股。

**现状分析**:
- `shared/market_rules.py` 已定义 `BOARD_RULES`, 含正确 lot_size (STAR=200)
- `risk/sizer.py` 已正确调用 `get_board_rule(symbol).lot_size`
- `hands/backtest/engine.py` 未引用 `market_rules`, 硬编码 100
- `hands/backtest/unified_matching_engine.py` 同样硬编码 100

**修复方案**:

```python
# hands/backtest/engine.py — execute_buy()
from ...shared.market_rules import get_board_rule

lot_size = get_board_rule(symbol).lot_size if symbol else 100
shares = (shares // lot_size) * lot_size  # 替换原有 //100*100
```

```python
# hands/backtest/unified_matching_engine.py — fill_buy()
from ...shared.market_rules import get_board_rule

lot_sizes = np.array([get_board_rule(s).lot_size if s else 100 for s in symbols])
shares_adj = (shares_adj // lot_sizes) * lot_sizes
```

**影响范围**: `engine.py:103`, `unified_matching_engine.py:97`, `portfolio_engine.py`(如有)

**验证方法**:
```python
# 测试科创板取整
rule = get_board_rule("688001.SH")
assert rule.lot_size == 200
assert rule.round_lot(250) == 200
assert rule.round_lot(450) == 400

# 测试主板取整
rule = get_board_rule("000001.SZ")
assert rule.lot_size == 100
assert rule.round_lot(150) == 100
```

### 4.2 T+1 检查: 统一使用交易日历

**问题**: `engine.py` 和 `unified_matching_engine.py` 各自实现 T+1 检查, 逻辑不一致。

**现状分析**:
- `engine.py:_check_t1_constraint()` 使用 `trade_calendar.get_trade_calendar()` 查询交易日
- `unified_matching_engine.py:fill_sell()` 先用 ordinal 比较, 再调用 `is_trading_day()` 二次确认
- 两处 fallback 策略不同: engine 拒绝卖出, matching_engine 也拒绝但逻辑更复杂

**修复方案**: 提取公共 T+1 检查函数到 `shared/`:

```python
# shared/t1_checker.py (新建)
from .market_rules import detect_board

def check_t1_eligible(
    buy_date,
    sell_date,
    trade_calendar,
    symbol: str = "",
) -> bool:
    """
    统一 T+1 检查: 买入日后至少经过 1 个交易日方可卖出.
    
    规则:
    - 主板/创业板/北交所: T+1
    - 科创板(688/689): T+1 (2020.7.22 起)
    - ST 股: T+1
    
    Returns:
        True if eligible to sell, False otherwise.
    """
    if buy_date is None:
        return True
    
    if not trade_calendar.is_trading_day(sell_date):
        return False
    
    trading_days = trade_calendar.get_trade_calendar(
        start_date=buy_date.strftime("%Y-%m-%d"),
        end_date=sell_date.strftime("%Y-%m-%d"),
    )
    
    if trading_days.empty:
        return False  # 保守: 无法确认时拒绝
    
    trade_dates = trading_days['trade_date'].values
    import numpy as np
    import pandas as pd
    buy_idx = np.where(trade_dates == pd.Timestamp(buy_date))[0]
    sell_idx = np.where(trade_dates == pd.Timestamp(sell_date))[0]
    
    if len(buy_idx) == 0 or len(sell_idx) == 0:
        return False
    
    return bool(sell_idx[0] - buy_idx[0] >= 1)
```

**影响范围**: `engine.py:_check_t1_constraint`, `unified_matching_engine.py:fill_sell`

### 4.3 复权因子: 补充 data/fq/ 数据

**问题**: `data/fq/` 目录不存在, 前复权/后复权因子无法获取, 回测价格不准确。

**现状分析**:
- `data/` 目录下有 `lake/`, `managers/`, `parsers/`, `pipeline/`, `sources/`, `utils/` 等子目录
- 无 `fq/` 子目录, 无复权因子管理器
- `data_fetcher.py` 可能有原始行情, 但未处理复权

**修复方案**:

```python
# data/fq/__init__.py
from .fq_manager import FQManager

# data/fq/fq_manager.py (新建)
class FQManager:
    """复权因子管理器 — 从 TDX/AKShare 获取并缓存"""
    
    def get_adjusted_price(
        self,
        df: pd.DataFrame,
        adjust: str = "hfq",  # hfq=后复权, qfq=前复权
    ) -> pd.DataFrame:
        """应用复权因子到 OHLCV 数据"""
        ...
    
    def refresh_fq_factors(self, symbols: list[str]) -> None:
        """批量刷新复权因子"""
        ...
```

**数据源优先级**:
1. AKShare `stock_zh_a_daily(symbol, adjust="hfq")` — 直接获取后复权数据
2. TDX 除权文件 `~/.pytdx/cache/` — 本地缓存
3. 手动计算: `hfq_price = price * cum_factor`

**工期估算**: 新建 data/fq/ 模块 (2 个文件), 对接 AKShare + TDX 两个数据源, 编写复权验证。估计 4-5 天 (原估算 2 天，因数据源对接+验证工作量大)。

---

## 5. P1 — 重要改进 (影响质量)

### 5.1 A 股规则模块: 创建 shared/a_share_rules.py

**问题**: 板块规则分散在 `market_rules.py`、`limit_checker.py`、`constants.py` 三处, 回测引擎未使用统一模块。

**现状分析**:
- `shared/market_rules.py`: `BoardType` 枚举 + `BOARD_RULES` 字典 + `detect_board()` + `get_board_rule()`
- `shared/limit_checker.py`: `get_board_type()` 返回字符串("main"/"sci_tech"/"gem"/"st"/"beijing")
- `shared/constants.py`: `MarketConstants.LIMIT_RATIO` 和 `MarketConstants.BOARD_PREFIX`
- 三处板块类型定义不一致: 枚举 vs 字符串 vs 常量

**修复方案**: 创建统一 A 股规则门面模块:

```python
# shared/a_share_rules.py (新建)
"""
A 股规则统一入口 — 所有模块必须通过此模块获取规则.

合并 market_rules.py + limit_checker.py + constants.py 中的规则定义,
消除三处不一致.
"""
from .market_rules import BoardType, BoardRule, BOARD_RULES, detect_board, get_board_rule
from .limit_checker import check_limit_status, LimitStatus

# 统一对外接口
__all__ = [
    "BoardType", "BoardRule", "BOARD_RULES",
    "detect_board", "get_board_rule",
    "check_limit_status", "LimitStatus",
    "round_lot", "get_lot_size", "get_price_limit",
]

def round_lot(symbol: str, shares: int) -> int:
    """取整到最小交易单位"""
    return get_board_rule(symbol).round_lot(shares)

def get_lot_size(symbol: str) -> int:
    """获取最小交易单位"""
    return get_board_rule(symbol).lot_size

def get_price_limit(symbol: str) -> float:
    """获取涨跌停比例"""
    return get_board_rule(symbol).price_limit_pct
```

### 5.2 回测引擎集成: 使用 A 股规则模块

**修复方案**:

```python
# hands/backtest/engine.py 修改
from ...shared.a_share_rules import round_lot, get_lot_size

# execute_buy() 中:
lot_size = get_lot_size(symbol) if symbol else 100
shares = (shares // lot_size) * lot_size

# unified_matching_engine.py 修改:
from ...shared.a_share_rules import get_lot_size

lot_sizes = np.array([get_lot_size(s) if s else 100 for s in symbols])
shares_adj = (shares_adj // lot_sizes) * lot_sizes
```

### 5.3 性能优化: LPPL Numba JIT

**问题**: `brain/lppl/numba_optimizer.py` 已存在但 `cost_function_reduced()` 未使用 JIT 编译。

**现状分析**:
- `numba_optimizer.py` 文件存在, 但 `engine.py` 中 DE 仍使用 numpy 版本
- 每次 cost function 调用 ~25μs, 全市场扫描 ~500K 次 = ~12.5s
- JIT 后预估: ~3μs/次, 总计 ~1.5s (8x 加速)

**修复方案**:

```python
# brain/lppl/numba_optimizer.py — 启用 JIT
from numba import njit

@njit(cache=True, fastmath=True)
def cost_function_reduced(params, t, m, omega):
    """Numba JIT 编译的 LPPL cost function"""
    tc, beta, phi = params
    tau = tc - t
    mask = tau > 0
    if mask.sum() < 4:
        return 1e10
    tau_m = tau[mask] ** beta
    cos_term = np.cos(omega * np.log(tau[mask]) + phi)
    # ... 同原逻辑, 但使用 numba 兼容的 numpy
```

```python
# brain/lppl/engine.py — 使用 JIT 版本
from .numba_optimizer import cost_function_reduced  # 替换原 numpy 版本
```

**预期收益**: LPPL 全市场扫描 4-8x 加速

---

## 6. P2 — 架构优化 (影响可维护性)

### 6.1 统一板块识别

**问题**: `limit_checker.get_board_type()` 返回字符串, `market_rules.detect_board()` 返回枚举, 两套逻辑并存。

**修复方案**:
1. `limit_checker.get_board_type()` 改为调用 `market_rules.detect_board()` 并映射
2. 或创建 `a_share_rules.py` 门面模块统一接口 (见 5.1)

```python
# shared/limit_checker.py 修改
from .market_rules import detect_board, BoardType

_BOARD_MAP = {
    BoardType.MAIN_SH: "main",
    BoardType.MAIN_SZ: "main",
    BoardType.GEM: "gem",
    BoardType.STAR: "sci_tech",
    BoardType.BEIJING: "beijing",
    BoardType.ST: "st",
}

def get_board_type(symbol: str, name: Optional[str] = None) -> str:
    """统一板块识别 — 委托给 market_rules.detect_board()"""
    try:
        board = detect_board(symbol)
        return _BOARD_MAP.get(board, "main")
    except ValueError:
        return "main"
```

### 6.2 统一异常定义

**现状**: `shared/exceptions.py` 已定义 37 个异常类, 覆盖完整。部分模块未使用统一异常。

**修复方案**:
1. 扫描所有 `raise ValueError` / `raise RuntimeError` 替换为对应自定义异常
2. 在 `__init__.py` 导出所有异常类

```bash
# 扫描非统一异常使用
rg "raise (ValueError|RuntimeError|TypeError)" src/uniquant/ --count
```

**工期估算**: 扫描 231 个文件中的 raise ValueError/RuntimeError, 逐一替换为 shared/exceptions.py 中定义的 37 个自定义异常子类，跨模块回归测试。估计 3-4 天 (原估算 1 天，因文件数量远超预期)。

### 6.3 修复线程安全问题

**问题**: `GlobalConfig` 单例模式无锁保护, 多线程环境下可能重复初始化。

**现状分析**:
- `shared/config_loader.py` 中 `GlobalConfig` 使用 `_instance` 类变量
- 无 `threading.Lock` 保护

**修复方案**:

```python
# shared/config_loader.py
import threading

class GlobalConfig:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # 双重检查锁
                    cls._instance = super().__new__(cls)
        return cls._instance
```

---

## 7. P3 — 功能增强

### 7.1 因子扩展: 量能因子、板块因子

**现状**: `brain/factors/` 已有基础因子, 但缺少量能类和板块类因子。

**新增因子清单**:

| 因子名 | 计算公式 | 类别 |
|--------|----------|------|
| volume_ratio | vol / ma(vol, 20) | 量能 |
| turnover_rate | vol / circulating_shares | 量能 |
| money_flow | (close - low) - (high - close) / (high - low) * vol | 量能 |
| sector_momentum | sector_avg_return_20d | 板块 |
| sector_breadth | sector_advance_count / sector_total | 板块 |
| relative_strength | stock_return / sector_return | 板块 |

**实现位置**: `brain/factors/` 下新建 `volume_factors.py` 和 `sector_factors.py`

### 7.2 风控增强: 动态 T+1 惩罚

**现状**: `risk/sizer.py` 中 T+1 惩罚固定为 1.2 倍。

**修复方案**: 根据持仓周期和波动率动态调整:

```python
def _dynamic_t1_penalty(
    self,
    volatility: float,
    holding_days: int,
) -> float:
    """
    动态 T+1 惩罚:
    - 高波动率 (>3%): 惩罚 1.5x
    - 中波动率 (1-3%): 惩罚 1.2x
    - 低波动率 (<1%): 惩罚 1.0x
    - 持仓 >5 天: 惩罚减半 (T+1 影响降低)
    """
    base = 1.5 if volatility > 0.03 else (1.2 if volatility > 0.01 else 1.0)
    decay = max(0.5, 1.0 - holding_days * 0.1)
    return base * decay
```

### 7.3 止损优化: 流动性感知止损

**现状**: 止损仅基于价格(ATR/CZSC), 不考虑流动性。

**修复方案**:

```python
def liquidity_aware_stop_loss(
    price_stop: float,
    current_price: float,
    avg_daily_volume: float,
    position_shares: int,
    liquidation_days: int = 3,
) -> float:
    """
    流动性感知止损:
    - 如果清仓需要 >liquidation_days 天, 向下调整止损
    - 流动性差的股票止损更紧
    """
    daily_capacity = avg_daily_volume * 0.1  # 最多吃 10% 成交量
    days_to_exit = position_shares / max(daily_capacity, 1)
    
    if days_to_exit > liquidation_days:
        # 流动性不足, 收紧止损
        tightening = min(0.02, (days_to_exit - liquidation_days) * 0.005)
        return current_price * (1 - tightening)
    
    return price_stop
```

> **跨文档冲突**: OPTIMIZATION_BACKTEST_ENGINE.md 要求 hands/backtest/stop_loss.py (StopLossManager)，OPTIMIZATION_RISK_MODULE.md 要求 risk/stop_loss.py (StopLossPolicy 接口)。统一方案: 接口定义在 risk/stop_loss.py，回测引擎引用风险模块，遵循 5 层 DAG 单向依赖。

---

## 8. 实施时间表 (甘特图)

```
Week 1:   Phase 0.0 — 导入链健壮性检查 + engine_factory 参数修复 (1 天)
├─ Mon-Tue ── [P0.0] 修复 engine_factory 构造函数参数错配 (7 个引擎)
├─ Wed  ─── [P0.0] 全模块导入链验证 + 回归测试
├─ Thu-Fri ── [P0.1] 手数取整修复 (engine.py + unified_matching_engine.py + portfolio_engine.py)

Week 2: Phase 0.1 — 手数取整 + T+1 统一
├─ Mon  ─┬─ [P0.1] 手数取整修复 (engine.py + unified_matching_engine.py)
│         └─ [P0.1] 编写手数取整单元测试
├─ Tue  ─┬─ [P0.2] 创建 shared/t1_checker.py
│         └─ [P0.2] 集成到 engine.py + unified_matching_engine.py
├─ Wed  ─┬─ [P0.2] T+1 单元测试 + 集成测试
│         └─ [P0.3] 创建 data/fq/__init__.py + fq_manager.py
├─ Thu  ─┬─ [P0.3] 复权因子数据源对接 (AKShare + TDX)
│         └─ [P0.3] 复权价格验证测试
└─ Fri  ─── [P0.3] 复权验证完成 + P0 回归测试

Week 2-3: Phase 0.1 — 复权因子 (扩展至 4-5 天)
├─ Week 2 Thu → Week 3 Wed: data/fq/ 模块 + 数据源对接 + 验证

Week 3-4: Phase 1 — A 股规则门面 + 回测引擎集成 + 性能优化
├─ Wed  ─┬─ [P1.1] 创建 shared/a_share_rules.py 门面模块
│         └─ [P1.1] 统一 limit_checker + market_rules 接口
├─ Thu  ─┬─ [P1.2] engine.py + unified_matching_engine.py 集成
│         └─ [P1.2] 回测引擎集成测试
├─ Fri  ─── P1 回归测试 (部分)
├─ Mon  ─┬─ [P1.3] LPPL numba_optimizer.py JIT 启用
│         └─ [P1.3] LPPL 性能基准测试
├─ Tue  ─┬─ [P1.3] 全市场扫描加速验证
│         └─ P1 回归测试完成
└─ Wed-Fri ── P1 代码审查

Week 5: Phase 2 — 架构优化 (P2.2 统一异常扩展至 3 天)
├─ Mon  ─┬─ [P2.1] limit_checker 统一到 market_rules
│         └─ [P2.1] 板块识别一致性测试
├─ Tue  ─┬─ [P2.2] 扫描 231 个文件的非统一异常使用
│         └─ [P2.2] 替换 raise ValueError/RuntimeError
├─ Wed  ─┬─ [P2.2] 继续替换 + 跨模块回归测试
│         └─ [P2.3] GlobalConfig 线程安全修复
├─ Thu  ─┬─ [P2.2] 异常统一化完成
│         └─ [P2.3] ServiceContainer 线程安全检查
└─ Fri  ─── P2 回归测试 + 代码审查

Week 6: Phase 3 — 功能增强
├─ Mon  ─┬─ [P3.1] volume_factors.py 实现
│         └─ [P3.1] sector_factors.py 实现
├─ Tue  ─┬─ [P3.1] 因子计算集成测试
│         └─ [P3.2] 动态 T+1 惩罚实现
├─ Wed  ─┬─ [P3.2] sizer 集成测试
│         └─ [P3.3] 流动性感知止损实现
├─ Thu  ─┬─ [P3.3] 止损策略统一 + 回测验证
│         └─ 全量回归测试
└─ Fri  ─── 最终代码审查 + 文档更新

Week 7: Phase 4 — 高级风控 (可选)
├─ Mon-Tue ── 真 EVT GPD 实现
├─ Wed-Thu ── 路径依赖压力测试
└─ Fri  ─── 奇异协方差矩阵处理
```

---

## 9. 风险评估

### 9.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Numba JIT 与 numpy 版本不兼容 | 中 | P1 延迟 | 先在 `numba_optimizer.py` 独立测试, 不影响主路径 |
| 复权因子数据源不稳定 | 低 | P0 延迟 | 多源备选: AKShare → TDX → 手动计算 |
| 板块识别统一后遗漏边界情况 | 中 | P0 回归 | 对 688/689/300/301/ST 全覆盖测试 |
| 线程安全修复引入死锁 | 低 | P2 延迟 | 使用 `threading.Lock` 而非 `RLock`, 保持简单 |

### 9.2 进度风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| P0 复权因子依赖外部数据源 | 中 | Week 1 延迟 | 优先使用本地 TDX 缓存 |
| P1 回测引擎集成范围超预期 | 中 | Week 2 延迟 | 先改 engine.py, unified_matching_engine 次优先 |
| P3 因子扩展计算性能不达标 | 低 | Week 4 延迟 | 先用 ThreadPool, 后续再优化 |

### 9.3 回滚策略

每个 P 级别独立分支, 失败可单独回滚:
```bash
git checkout -b fix/p0-lot-sizing
git checkout -b feat/p1-a-share-rules
git checkout -b refactor/p2-unify-board
git checkout -b feat/p3-factor-expansion
```

---

## 10. 验收标准

### Phase 0.0 验收: 导入链健壮性
```bash
# 验证 services 模块可导入 (使用 __getattr__ 延迟加载，14 个目标全部存在)
python -c "import uniquant; import uniquant.services; print('OK')"
# 验证 LPPL 引擎可导入 (使用 try/except 条件导入)
python -c "from uniquant.brain.lppl import LPPLEngine; print('LPPL OK')"
# 验证 FSM 模块可导入 (Indicators 存在于 brain/indicators/)
python -c "from uniquant.brain.fsm import DecisionBrain; print('FSM OK')"
# 验证 engine_factory 可初始化 (需修复 orchestrator 参数错配)
python -c "from uniquant.services.analysis.engine_factory import AnalysisEngineFactory; print('Factory OK')"
```

### P0 验收
- [ ] 科创板(688xxx.SH) 按 200 股取整
- [ ] 主板(600xxx.SH/000xxx.SZ) 按 100 股取整
- [ ] T+1 检查使用统一交易日历, engine 和 matching_engine 结果一致
- [ ] 复权因子可获取, 前复权/后复权价格与 AKShare 一致

### P1 验收
- [ ] `shared/a_share_rules.py` 作为唯一规则入口
- [ ] 回测引擎无硬编码手数
- [ ] LPPL cost_function JIT 加速 ≥4x

### P2 验收
- [ ] 板块识别仅通过 `market_rules.detect_board()`
- [ ] 无 `raise ValueError` / `raise RuntimeError` (全部使用自定义异常)
- [ ] GlobalConfig 多线程初始化测试通过

### P3 验收
- [ ] 新增 ≥4 个因子, 计算耗时 <10s (5000 股)
- [ ] 动态 T+1 惩罚回测 Sharpe 提升 ≥0.1
- [ ] 流动性感知止损在低流动性股票上止损更紧

---

## 附录 A: 文件变更清单 (共 18+ 文件)

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `src/uniquant/services/analysis/engine_factory.py` | P0.0 修复 orchestrator 参数错配 (7 个引擎) |
| 修改 | `src/uniquant/brain/fsm/fsm.py` | P0.0 修复 Indicators 导入 |
| 修改 | `src/uniquant/services/analysis/engine_factory.py` | P0.0 修复构造函数参数错配 |
| 修改 | `hands/backtest/engine.py` | P0 手数取整 + P1 集成 a_share_rules |
| 修改 | `hands/backtest/unified_matching_engine.py` | P0 手数取整 + P1 集成 a_share_rules |
| 新建 | `shared/t1_checker.py` | P0 统一 T+1 检查 |
| 新建 | `data/fq/__init__.py` | P0 复权因子模块 |
| 新建 | `data/fq/fq_manager.py` | P0 复权因子管理器 |
| 新建 | `shared/a_share_rules.py` | P1 A 股规则门面 |
| 修改 | `shared/limit_checker.py` | P2 统一板块识别 |
| 修改 | `shared/config_loader.py` | P2 线程安全 |
| 修改 | `brain/lppl/numba_optimizer.py` | P1 JIT 启用 |
| 修改 | `brain/lppl/engine.py` | P1 使用 JIT 版本 |
| 新建 | `brain/factors/volume_factors.py` | P3 量能因子 |
| 新建 | `brain/factors/sector_factors.py` | P3 板块因子 |
| 修改 | `risk/sizer.py` | P3 动态 T+1 + 流动性止损 |

## 附录 B: 测试覆盖要求

| 优先级 | 最低覆盖率 | 测试类型 |
|--------|-----------|----------|
| P0 | 90% | 单元测试 + 集成测试 |
| P1 | 80% | 单元测试 + 性能基准 |
| P2 | 70% | 单元测试 + 导入测试 |
| P3 | 70% | 单元测试 + 回测验证 |
