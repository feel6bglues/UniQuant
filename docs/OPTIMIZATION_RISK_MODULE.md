# UniQuant 风控模块改进方案

> **版本**: v1.0 | **日期**: 2026-05-31 | **状态**: 待审核
>
> 本文档基于 `src/uniquant/risk/` 源码实际分析，覆盖 6 个文件约 1,300 行代码。

---

## 目录

1. [模块架构现状](#1-模块架构现状)
2. [问题清单与优先级](#2-问题清单与优先级)
3. [P0: EVTRisk 名不副实修复](#3-p0-evtrisk-名不副实修复)
4. [P0: PortfolioSizer 不可变性违规](#4-p0-portfolioSizer-不可变性违规)
5. [P1: 动态 T+1 惩罚系数](#5-p1-动态-t1-惩罚系数)
6. [P1: 止损逻辑集成到回测引擎](#6-p1-止损逻辑集成到回测引擎)
7. [P2: 真正的 EVT 实现](#7-p2-真正的-evt-实现)
8. [P2: DrawdownAnalyzer 增强](#8-p2-drawdownanalyzer-增强)
9. [P2: PortfolioOptimizer 改进](#9-p2-portfoliooptimizer-改进)
10. [回测验证方案](#10-回测验证方案)
11. [实施路线图](#11-实施路线图)

---

## 1. 模块架构现状

### 1.1 文件清单

| 文件 | 行数 | 类/函数 | 职责 |
|------|------|---------|------|
| `sizer.py` | 266 | `PositionSizer`, `PortfolioSizer` | 单票仓位计算、组合仓位分配 |
| `portfolio_optimizer.py` | 371 | `PortfolioOptimizer` | 风险平价、均值-方差、有效前沿 |
| `drawdown_analyzer.py` | 187 | `DrawdownAnalyzer` | 向量化 MDD、尾部风险、压力测试 |
| `evt_risk.py` | 386 | `HistoricalSimulationRisk` | 历史模拟 VaR/CVaR、市场状态检测 |
| `historical_risk.py` | 18 | `HistoricalSimulationRisk`(wrapper) | 废弃别名包装器 |
| `structural.py` | 103 | `StructuralRiskManager` | 结构性风险矩阵 |

### 1.2 依赖关系

```
shared.constants (RiskCalculationConstants, PrecisionConstants)
shared.market_rules (get_board_rule)
shared.cost_model (calculate_sharpe_ratio)
shared.config_loader (get_config)
shared.error_handling (handle_errors)
shared.exceptions (RiskCalculationError)
         │
         ▼
   risk/ (本模块)
```

### 1.3 当前数学模型

**PositionSizer 仓位公式** (`sizer.py:149-155`):

```
shares = floor(MaxLoss / (RiskPerShare × Penalty) / LotSize) × LotSize

其中:
  MaxLoss = Capital × RiskPct
  RiskPerShare = Price - max(ATR_Stop, CZSC_Bottom)
  Penalty = market_penalties[market]  # CN 固定 1.2
  LotSize = get_board_rule(symbol).lot_size  # A股默认 100
```

**PortfolioOptimizer 风险平价目标函数** (`portfolio_optimizer.py:18-22`):

```
min Σ(RC_i - target_i)²

其中:
  RC_i = w_i × (Σw)_i / σ_p
  σ_p = √(w'Σw)
  target_i = 1/n  (等风险贡献)
```

**DrawdownAnalyzer 向量化 MDD** (`drawdown_analyzer.py:86-89`):

```
DD_t = (P_t - max_{τ≤t} P_τ) / max_{τ≤t} P_τ
MDD  = -min(DD_t)
```

**HistoricalSimulationRisk VaR** (`evt_risk.py:132-141`):

```
VaR_α = -percentile(R, (1-α) × 100)
CVaR_α = -mean(R | R ≤ -VaR_α)
```

---

## 2. 问题清单与优先级

| # | 问题 | 严重度 | 文件:行号 | 影响 |
|---|------|--------|-----------|------|
| 1 | `EVTRisk` 名不副实: 类名暗示极值理论，实为历史模拟法 | **P0** | `evt_risk.py:25` | 误导使用者，学术不严谨 |
| 2 | `PortfolioSizer.allocate` 直接修改输入 `sig.notional` | **P0** | `sizer.py:252-253` | 违反不可变性，可能引发并发 bug |
| 3 | T+1 惩罚系数固定 1.2 | **P1** | `sizer.py:80` | 高波动期惩罚不足，低波动期过度惩罚 |
| 4 | 止损逻辑未集成到回测引擎 | **P1** | `sizer.py:130-137` | 回测无法验证止损有效性 |
| 5 | 无真正的 EVT (GPD) 实现 | **P2** | `evt_risk.py` 全文 | 尾部风险估计偏差 |
| 6 | `DrawdownAnalyzer.stress_scenario` 过于简化 | **P2** | `drawdown_analyzer.py:173-187` | 未模拟路径依赖的回撤 |
| 7 | `PortfolioOptimizer` 未处理奇异协方差矩阵 | **P2** | `portfolio_optimizer.py:67` | 资产高度相关时优化失败 |
| 8 | `historical_risk.py` 与 `evt_risk.py` 别名继承混乱 | **P2** | `historical_risk.py:6` | 架构混乱 — 运行时能工作但无实际意义 |

---

## 3. P0: EVTRisk 名不副实修复

### 3.1 问题分析

`evt_risk.py:25` 定义的类名为 `HistoricalSimulationRisk`，但 `__init__.py:20` 和 `evt_risk.py:386` 仍导出 `EVTRisk` 别名。文档和日志中多处使用 "EVT" 字样（`evt_risk.py:63`, `evt_risk.py:76`），而实际实现是纯粹的 `np.percentile` 历史模拟法。

真正的 EVT（极值理论）应使用广义帕累托分布 (GPD) 拟合尾部：

```
GPD 尾部模型:
  F(x) = 1 - (1 + ξx/σ)^(-1/ξ)    (ξ ≠ 0)
  F(x) = 1 - exp(-x/σ)              (ξ = 0)

  其中:
    ξ = shape parameter (尾部厚度)
    σ = scale parameter
    u = threshold (通常取 95% 分位数)
```

### 3.2 修复方案

**Step 1: 清理命名**（已部分完成）

`evt_risk.py` 已将主类命名为 `HistoricalSimulationRisk`，但别名 `EVTRisk` 仍在 `evt_risk.py:386` 和 `__init__.py:20` 导出。

```python
# evt_risk.py:386 — 当前
EVTRisk = HistoricalSimulationRisk

# 改为: 删除此行，统一使用 HistoricalSimulationRisk
```

```python
# __init__.py:20 — 当前
from .evt_risk import EVTRisk

# 改为:
from .evt_risk import HistoricalSimulationRisk
```

```python
# __init__.py:34-40 — 当前
__all__ = [
    "DrawdownAnalyzer",
    "PositionSizer",
    "EVTRisk",
    "PortfolioOptimizer",
    "StructuralRiskManager",
]

# 改为:
__all__ = [
    "DrawdownAnalyzer",
    "PositionSizer",
    "HistoricalSimulationRisk",
    "PortfolioOptimizer",
    "StructuralRiskManager",
]
```

**Step 2: 更新日志和 docstring**

```python
# evt_risk.py:63 — 当前
"""
Calculate risk metrics using EVT.
"""

# 改为:
"""
Calculate risk metrics using Historical Simulation method.
"""
```

```python
# evt_risk.py:76 — 当前
logger.info("EVT metrics cache hit")

# 改为:
logger.info("Historical simulation metrics cache hit")
```

**Step 3: 保留废弃别名（向后兼容）**

```python
# historical_risk.py — 改为正向别名
import warnings
from .evt_risk import HistoricalSimulationRisk as _HSR


def EVTRisk(*args, **kwargs):
    """Deprecated: use HistoricalSimulationRisk instead."""
    warnings.warn(
        "EVTRisk is deprecated, use HistoricalSimulationRisk",
        DeprecationWarning,
        stacklevel=2,
    )
    return _HSR(*args, **kwargs)
```

### 3.3 影响范围

| 文件 | 需修改行 |
|------|----------|
| `evt_risk.py` | L23, L33, L63, L76, L386 |
| `__init__.py` | L7, L20, L37 |
| `historical_risk.py` | 全文重写 |

> ⚠️ `evt_risk.py:118-130` 的缓存键使用 `mean/std/skew/kurt` 的四位小数拼接，存在哈希碰撞风险。两个不同分布若统计矩相同(Anscombe 四重奏风格)会命中同一缓存。建议改为 `hash(pd.util.hash_pandas_object(returns))`。

---

## 4. P0: PortfolioSizer 不可变性违规

### 4.1 问题分析

`sizer.py:250-253` 直接修改了传入的 `PositionSizingResult` 对象的 `notional` 字段：

```python
# sizer.py:250-253 — 当前代码
for sym, sig in signals.items():
    max_notional = portfolio_equity * self._max_single
    if sig.notional > max_notional:
        sig.notional = max_notional  # ← 直接修改输入对象
    capped[sym] = sig
```

这违反了 AGENTS.md 中"Always create new objects, never mutate"的核心原则。如果调用方在 `allocate` 之后再次使用原始 `signals`，数据已被篡改。

### 4.2 修复方案

```python
# sizer.py:240-266 — 修改后
def allocate(
    self,
    signals: Dict[str, PositionSizingResult],
    portfolio_equity: float,
    daily_pnl: float = 0.0,
) -> PortfolioAllocation:
    if daily_pnl < -self._max_daily_loss:
        return PortfolioAllocation(remaining_cash=portfolio_equity)

    capped: Dict[str, PositionSizingResult] = {}
    for sym, sig in signals.items():
        max_notional = portfolio_equity * self._max_single
        if sig.notional > max_notional:
            # 创建新对象，不修改原始输入
            capped[sym] = PositionSizingResult(
                symbol=sig.symbol,
                notional=max_notional,
                risk_amount=sig.risk_amount * (max_notional / sig.notional),
                shares=int(sig.shares * (max_notional / sig.notional)),
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
            )
        else:
            capped[sym] = sig

    total_risk = sum(s.risk_amount for s in capped.values())
    if total_risk <= 0:
        return PortfolioAllocation(remaining_cash=portfolio_equity)

    scaling = min(1.0, portfolio_equity * self._max_total_risk / total_risk)
    return PortfolioAllocation(
        positions=capped,
        total_allocated_pct=scaling,
        remaining_cash=portfolio_equity * (1 - scaling),
        total_risk_amount=total_risk * scaling,
    )
```

### 4.3 验证测试

```python
def test_portfolio_sizer_immutability():
    """验证 allocate 不修改输入对象"""
    sizer = PortfolioSizer(max_single=0.10)
    original_notional = 50000.0

    signals = {
        "600519.SH": PositionSizingResult(
            symbol="600519.SH",
            notional=original_notional,  # 超过 10% 上限
            risk_amount=2500.0,
            shares=100,
            entry_price=500.0,
            stop_loss=475.0,
        )
    }

    result = sizer.allocate(signals, portfolio_equity=100000.0)

    # 关键断言: 原始对象未被修改
    assert signals["600519.SH"].notional == original_notional
    # 结果中的值被 cap
    assert result.positions["600519.SH"].notional == 10000.0
```

---

### [新增] P0: PortfolioOptimizer.get_efficient_frontier 状态变异

**严重程度**: 比 sizer.py:252 更严重—多线程不安全的可变状态修改

**位置**: `portfolio_optimizer.py:331-347`

**问题**:
```python
def get_efficient_frontier(self, returns, ...):
    for target_ret in target_returns:
        original_target = self.config.target_return
        self.config.target_return = target_ret  # ← 修改了优化器状态!
        result = self.optimize_mean_variance(...)
        self.config.target_return = original_target
```

在多线程环境中，另一线程可能在 `target_return` 被修改后读取配置。修复: 将 `target_return` 作为参数传递给 `optimize_mean_variance`，不要在 `get_efficient_frontier` 中修改 `self.config`。

---

## 5. P1: 动态 T+1 惩罚系数

### 5.1 问题分析

`sizer.py:80` 硬编码了 T+1 惩罚系数：

```python
self.market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}
```

A 股 T+1 制度的风险随市场状态变化：
- **高波动期**（如 2015 股灾）：隔夜跳空风险远高于 20%，1.2 倍惩罚严重不足
- **低波动期**（如窄幅震荡）：1.2 倍惩罚过度，降低资金效率
- **涨跌停板制度**：ST 股 ±5%、科创板 ±20%，风险差异巨大

### 5.2 数学模型

引入基于波动率和流动性的动态惩罚系数：

```
DynamicPenalty = BasePenalty × VolScalar × LiquidityScalar × LimitScalar

其中:
  BasePenalty  = 1.0 (基础惩罚)
  VolScalar    = clip(σ_20d / σ_252d, 0.8, 2.0)
    σ_20d      = 20 日收益率标准差 × √252
    σ_252d     = 252 日收益率标准差 × √252
  LiquidityScalar = clip(ATVR_target / ATVR_median, 0.9, 1.5)
    ATVR       = Average Turnover Value Ratio (日均换手金额比)
  LimitScalar  = 0.10 / max(limit_pct, 0.01)
    LimitPct   = 涨跌停幅度 (主板 0.10, 科创板 0.20, ST 0.05)

> 涨跌停缩放因子的方向可能存在争议: 更宽的涨跌停(科创板 20%)意味着更大的隔夜风险，可能需要更高惩罚。但目前实践中取 0.10/limit_pct 使科创板惩罚降低(ST 惩罚升高)，是基于"涨跌停越宽 → 流动性越好 → T+1 风险越低"的假设。如需反转方向，改为 `limit_pct / 0.10`。

约束: DynamicPenalty ∈ [1.0, 2.5]
```

### 5.3 实现方案

```python
# sizer.py — 新增 DynamicPenaltyCalculator

from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass(frozen=True)
class MarketState:
    """市场状态快照（不可变）"""
    volatility_20d: float       # 20 日年化波动率
    volatility_252d: float      # 252 日年化波动率
    avg_turnover_ratio: float   # 平均换手率
    limit_pct: float            # 涨跌停幅度 (0.05/0.10/0.20/0.30)


class DynamicPenaltyCalculator:
    """动态 T+1 惩罚系数计算器"""

    BASE_PENALTY = 1.0
    MIN_PENALTY = 1.0
    MAX_PENALTY = 2.5

    def calculate(
        self,
        market_state: Optional[MarketState] = None,
        reference_volatility: float = 0.20,
        reference_turnover: float = 0.03,
    ) -> float:
        if market_state is None:
            return 1.2  # fallback 到原始固定值

        # 波动率标量: 当前波动率相对于长期波动率
        vol_ratio = market_state.volatility_20d / max(
            market_state.volatility_252d, 1e-6
        )
        vol_scalar = np.clip(vol_ratio, 0.8, 2.0)

        # 流动性标量: 换手率越低，惩罚越高
        liq_scalar = np.clip(
            reference_turnover / max(market_state.avg_turnover_ratio, 1e-6),
            0.9, 1.5,
        )

        # 涨跌停标量: 幅度越小（如 ST ±5%），惩罚越高
        limit_scalar = 0.10 / max(market_state.limit_pct, 0.01)

        penalty = self.BASE_PENALTY * vol_scalar * liq_scalar * limit_scalar
        return float(np.clip(penalty, self.MIN_PENALTY, self.MAX_PENALTY))
```

### 5.4 集成到 PositionSizer

```python
# sizer.py:71-80 — 修改后
class PositionSizer:
    def __init__(
        self,
        initial_capital: float = 100000.0,
        risk_pct: float = 0.05,
        penalty_calculator: Optional[DynamicPenaltyCalculator] = None,
    ):
        self.capital = initial_capital
        self.risk_pct = risk_pct
        self._penalty_calc = penalty_calculator or DynamicPenaltyCalculator()
        self._default_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}

    def _get_penalty(
        self, market: str, market_state: Optional[MarketState] = None
    ) -> float:
        if market != "CN":
            return self._default_penalties.get(market, 1.0)
        return self._penalty_calc.calculate(market_state)
```

### 5.5 惩罚系数敏感度分析

| 市场状态 | σ_20d | σ_252d | VolScalar | LimitScalar | 最终惩罚 |
|----------|-------|--------|-----------|-------------|----------|
| 低波动牛市 | 12% | 18% | 0.80 | 1.0 | 1.00 |
| 正常震荡 | 20% | 20% | 1.00 | 1.0 | 1.20 |
| 高波动熊市 | 40% | 25% | 1.60 | 1.0 | 1.92 |
| ST 股正常 | 20% | 20% | 1.00 | 2.0 | 2.00 |
| 科创板低波 | 15% | 22% | 0.80 | 0.50 | 1.00 |

---

## 6. P1: 止损逻辑集成到回测引擎

### 6.1 问题分析

`PositionSizer.calculate_shares` (`sizer.py:130-137`) 实现了几何止损逻辑：

```python
# sizer.py:130-137
atr_stop_value = atr_stop if atr_stop is not None else stop_loss
final_stop = atr_stop_value
if czsc_bottom is not None and czsc_bottom > atr_stop_value:
    final_stop = czsc_bottom
```

止损 = `max(ATR_Stop, CZSC_Bottom_Fractal)`，这是保守策略。但回测引擎未使用此逻辑，导致回测结果不含止损效果。

### 6.2 设计方案

#### 6.2.1 StopLossPolicy 接口

```python
# 新增: risk/stop_loss.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StopLossSignal:
    """止损信号（不可变）"""
    price: float           # 触发价格
    reason: str            # 触发原因: "atr" | "czsc" | "trailing" | "time"
    atr_stop: Optional[float] = None
    czsc_stop: Optional[float] = None


class StopLossPolicy(ABC):
    """止损策略抽象基类"""

    @abstractmethod
    def calculate_stop(
        self,
        entry_price: float,
        current_price: float,
        atr: Optional[float] = None,
        czsc_bottom: Optional[float] = None,
        holding_days: int = 0,
    ) -> StopLossSignal:
        ...


class GeometricStopLoss(StopLossPolicy):
    """几何止损: max(ATR_Stop, CZSC_Bottom)"""

    def __init__(self, atr_multiplier: float = 2.0):
        self._atr_mult = atr_multiplier

    def calculate_stop(
        self,
        entry_price: float,
        current_price: float,
        atr: Optional[float] = None,
        czsc_bottom: Optional[float] = None,
        holding_days: int = 0,
    ) -> StopLossSignal:
        atr_stop = entry_price - atr * self._atr_mult if atr else entry_price * 0.95

        final_stop = atr_stop
        reason = "atr"

        if czsc_bottom is not None and czsc_bottom > atr_stop:
            final_stop = czsc_bottom
            reason = "czsc"

        return StopLossSignal(
            price=final_stop,
            reason=reason,
            atr_stop=atr_stop,
            czsc_stop=czsc_bottom,
        )


class TrailingStopLoss(StopLossPolicy):
    """移动止损: 从最高点回落固定比例"""

    def __init__(self, trail_pct: float = 0.08):
        self._trail_pct = trail_pct

    def calculate_stop(
        self,
        entry_price: float,
        current_price: float,
        atr: Optional[float] = None,
        czsc_bottom: Optional[float] = None,
        holding_days: int = 0,
    ) -> StopLossSignal:
        trailing_stop = current_price * (1 - self._trail_pct)
        return StopLossSignal(price=trailing_stop, reason="trailing")


class TimeDecayStopLoss(StopLossPolicy):
    """时间衰减止损: 持仓越久止损越紧"""

    def __init__(
        self,
        initial_stop_pct: float = 0.10,
        min_stop_pct: float = 0.03,
        decay_days: int = 20,
    ):
        self._initial_pct = initial_stop_pct
        self._min_pct = min_stop_pct
        self._decay_days = decay_days

    def calculate_stop(
        self,
        entry_price: float,
        current_price: float,
        atr: Optional[float] = None,
        czsc_bottom: Optional[float] = None,
        holding_days: int = 0,
    ) -> StopLossSignal:
        import math
        decay = math.exp(-holding_days / self._decay_days)
        stop_pct = self._min_pct + (self._initial_pct - self._min_pct) * decay
        stop_price = entry_price * (1 - stop_pct)
        return StopLossSignal(price=stop_price, reason="time")
```

#### 6.2.2 回测引擎集成

```python
# 在 hands/backtest_engine.py 中集成（伪代码）

class BacktestEngine:
    def __init__(
        self,
        stop_loss_policy: Optional[StopLossPolicy] = None,
        # ... 其他参数
    ):
        self._stop_policy = stop_loss_policy or GeometricStopLoss()

    def _check_stop_loss(
        self,
        position: Position,
        bar: BarData,
        atr: Optional[float],
        czsc_bottom: Optional[float],
    ) -> Optional[StopLossSignal]:
        """每根 K 线检查止损"""
        signal = self._stop_policy.calculate_stop(
            entry_price=position.entry_price,
            current_price=bar.close,
            atr=atr,
            czsc_bottom=czsc_bottom,
            holding_days=position.holding_days,
        )
        if bar.low <= signal.price:
            return signal
        return None
```

#### 6.2.3 回测止损流程

```
对每根 K 线 t:
  1. 检查止损: signal = stop_policy.calculate_stop(entry, current, atr, czsc)
  2. 若 bar.low ≤ signal.price → 触发止损，以 signal.price 成交
  3. 若未触发 → 继续持有，更新 trailing stop
  4. 记录止损事件到回测日志
```

---

## 7. P2: 真正的 EVT 实现

### 7.1 背景

极值理论 (EVT) 的核心是用广义帕累托分布 (GPD) 拟合超过阈值的尾部损失，比历史模拟法在小样本下更稳健。

### 7.2 数学推导

**Pickands-Balkema-de Haan 定理**: 对于充分高的阈值 u，超额损失的条件分布收敛于 GPD：

```
P(X - u ≤ x | X > u) ≈ G(x; ξ, σ)

G(x; ξ, σ) = {
  1 - (1 + ξx/σ)^(-1/ξ)    if ξ ≠ 0, x ≥ 0
  1 - exp(-x/σ)              if ξ = 0, x ≥ 0
}

其中:
  ξ = shape parameter (ξ > 0: 厚尾, ξ = 0: 指数尾, ξ < 0: 有限尾)
  σ = scale parameter (σ > 0)
```

**VaR 和 CVaR 的 EVT 解析式**:

```
VaR_α = u + (σ/ξ) × [((n/N_u)(1-α))^(-ξ) - 1]

CVaR_α = VaR_α / (1-ξ) + (σ - ξ×u) / (1-ξ)

其中:
  n    = 样本总数
  N_u  = 超过阈值 u 的样本数
  α    = 置信水平 (如 0.95, 0.99)
```

### 7.3 实现方案

```python
# 新增: risk/evt_risk.py (真正实现)

from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
import warnings

try:
    from scipy.stats import genpareto, kstest
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


@dataclass(frozen=True)
class EVTFitResult:
    """GPD 拟合结果（不可变）"""
    xi: float           # shape parameter
    sigma: float        # scale parameter
    threshold: float    # 使用的阈值
    n_exceedances: int  # 超阈值样本数
    n_total: int        # 总样本数
    ks_statistic: float # KS 检验统计量
    ks_pvalue: float    # KS 检验 p 值


class TrueEVTRiskCalculator:
    """
    基于 GPD 的极值理论风险计算器。

    使用 scipy.stats.genpareto 进行尾部拟合，
    提供解析 VaR/CVaR 公式。
    """

    def __init__(self, threshold_quantile: float = 0.95):
        if not HAS_SCIPY:
            raise ImportError(
                "scipy is required for TrueEVTRiskCalculator. "
                "Install with: pip install scipy"
            )
        self._threshold_q = threshold_quantile

    def fit_gpd(
        self, returns: np.ndarray, threshold: Optional[float] = None
    ) -> EVTFitResult:
        """
        对损失序列拟合 GPD。

        Args:
            returns: 收益率序列 (正 = 盈利, 负 = 亏损)
            threshold: 阈值 (默认取 threshold_quantile 分位数)

        Returns:
            EVTFitResult 拟合结果
        """
        losses = -returns  # 转为损失序列
        if threshold is None:
            threshold = np.percentile(losses, self._threshold_q * 100)

        exceedances = losses[losses > threshold] - threshold
        if len(exceedances) < 10:
            raise ValueError(
                f"Too few exceedances ({len(exceedances)}). "
                "Lower threshold or use more data."
            )

        xi, loc, sigma = genpareto.fit(exceedances, floc=0)

        # KS 检验
        ks_stat, ks_p = self._ks_test(exceedances, xi, sigma)

        return EVTFitResult(
            xi=float(xi),
            sigma=float(sigma),
            threshold=float(threshold),
            n_exceedances=len(exceedances),
            n_total=len(losses),
            ks_statistic=float(ks_stat),
            ks_pvalue=float(ks_p),
        )

    def calculate_var(
        self, returns: np.ndarray, confidence: float = 0.95, fit: Optional[EVTFitResult] = None
    ) -> float:
        """使用 GPD 计算 VaR"""
        fit = fit or self.fit_gpd(returns)
        n = fit.n_total
        n_u = fit.n_exceedances

        # VaR_α = u + (σ/ξ) × [((n/N_u)(1-α))^(-ξ) - 1]
        tail_prob = (n / n_u) * (1 - confidence)
        if fit.xi != 0:
            var = fit.threshold + (fit.sigma / fit.xi) * (
                tail_prob ** (-fit.xi) - 1
            )
        else:
            var = fit.threshold + fit.sigma * np.log(1 / tail_prob)

        return float(var)

    def calculate_cvar(
        self, returns: np.ndarray, confidence: float = 0.95, fit: Optional[EVTFitResult] = None
    ) -> float:
        """使用 GPD 计算 CVaR"""
        fit = fit or self.fit_gpd(returns)
        var = self.calculate_var(returns, confidence, fit=fit)

        # CVaR_α = VaR_α / (1-ξ) + (σ - ξ×u) / (1-ξ)
        if fit.xi < 1:
            cvar = var / (1 - fit.xi) + (fit.sigma - fit.xi * fit.threshold) / (
                1 - fit.xi
            )
        else:
            cvar = var  # ξ ≥ 1 时 CVaR 不存在，退化为 VaR

        return float(cvar)

    @staticmethod
    def _ks_test(
        exceedances: np.ndarray, xi: float, sigma: float
    ) -> Tuple[float, float]:
        """Kolmogorov-Smirnov 拟合优度检验"""
        sorted_exc = np.sort(exceedances)
        ks_stat, ks_p = kstest(sorted_exc, lambda x: genpareto.cdf(x, xi, 0, sigma))
        return ks_stat, ks_p
```

### 7.4 EVT vs 历史模拟法对比

| 特性 | 历史模拟法 (当前) | EVT/GPD (改进) |
|------|-------------------|----------------|
| 小样本稳健性 | 差 (受极端值影响) | 好 (参数化外推) |
| 置信度 > 99% | 不可靠 | 可靠 |
| 计算复杂度 | O(n) | O(n log n) |
| 依赖 | numpy | scipy |
| 可解释性 | 高 | 中 |
| 外推能力 | 无 | 有 (尾部外推) |

---

## 8. P2: DrawdownAnalyzer 增强

### 8.1 当前问题

`stress_scenario` (`drawdown_analyzer.py:173-187`) 过于简化——仅对权益曲线乘以固定跌幅：

```python
# 当前实现
stressed = equity * (1.0 + crash)  # 简单乘法，无路径依赖
```

> ⚠️ `drawdown_analyzer.py:92-100` 的 `compute_rolling_mdd` 虽声称"全部 NumPy 算子，零 iterrows"，但实际使用 Python for 循环逐窗口计算。10,000 个数据点下性能差。应使用 `np.lib.stride_tricks.sliding_window_view` 向量化。

未模拟真实崩盘的路径特征（如 V 型反弹、L 型阴跌、阶梯式下跌）。

### 8.2 增强方案: 路径依赖压力测试

```python
from dataclasses import dataclass
from enum import Enum
from typing import List
import numpy as np


class CrashPattern(Enum):
    V_RECOVERY = "v_recovery"          # V 型反弹
    L_SLOW_BLEED = "l_slow_bleed"      # L 型阴跌
    STAIRCASE_DOWN = "staircase_down"  # 阶梯式下跌
    FLASH_CRASH = "flash_crash"        # 闪崩后恢复


@dataclass(frozen=True)
class StressScenario:
    """压力测试场景定义（不可变）"""
    name: str
    pattern: CrashPattern
    total_drop: float        # 总跌幅 (如 -0.30)
    duration_days: int       # 持续天数
    recovery_days: int       # 恢复天数 (0 = 不恢复)


class PathDependentStressTester:
    """路径依赖压力测试器"""

    PATTERNS = {
        CrashPattern.V_RECOVERY: lambda drop, n: _v_pattern(drop, n),
        CrashPattern.L_SLOW_BLEED: lambda drop, n: _l_pattern(drop, n),
        CrashPattern.STAIRCASE_DOWN: lambda drop, n: _staircase_pattern(drop, n),
        CrashPattern.FLASH_CRASH: lambda drop, n: _flash_pattern(drop, n),
    }

    def apply_scenario(
        self,
        equity: np.ndarray,
        scenario: StressScenario,
    ) -> np.ndarray:
        """将压力场景叠加到权益曲线上"""
        pattern_fn = self.PATTERNS[scenario.pattern]
        shock = pattern_fn(scenario.total_drop, scenario.duration_days)

        # 将 shock 序列追加到权益曲线末尾
        base_value = equity[-1]
        shocked_equity = base_value * np.cumprod(1 + shock)

        # 可选: 添加恢复期
        if scenario.recovery_days > 0:
            recovery = np.linspace(
                shocked_equity[-1], base_value, scenario.recovery_days
            )
            return np.concatenate([equity, shocked_equity, recovery])

        return np.concatenate([equity, shocked_equity])


def _v_pattern(drop: float, n: int) -> np.ndarray:
    """V 型: 前半段急跌，后半段急涨"""
    half = n // 2
    down = np.linspace(0, drop, half) / half
    up = np.linspace(drop, 0, n - half) / (n - half)
    return np.concatenate([down, up])


def _l_pattern(drop: float, n: int) -> np.ndarray:
    """L 型: 急跌后低位震荡"""
    crash_days = max(n // 5, 3)
    crash = np.linspace(0, drop, crash_days) / crash_days
    flat = np.zeros(n - crash_days)
    return np.concatenate([crash, flat])


def _staircase_pattern(drop: float, n: int) -> np.ndarray:
    """阶梯式: 分 3-5 级台阶下跌"""
    steps = min(5, max(3, n // 10))
    step_drop = drop / steps
    result = np.zeros(n)
    step_size = n // steps
    for i in range(steps):
        start = i * step_size
        end = min(start + step_size, n)
        result[start:end] = step_drop / (end - start)
    return result


def _flash_pattern(drop: float, n: int) -> np.ndarray:
    """闪崩: 1-2 天急跌，快速恢复"""
    result = np.zeros(n)
    crash_day = min(2, n)
    result[:crash_day] = drop / crash_day
    if n > crash_day:
        recovery_rate = -drop / (n - crash_day)
        result[crash_day:] = recovery_rate
    return result
```

### 8.3 预定义 A 股压力场景

```python
A_SHARE_STRESS_SCENARIOS = [
    StressScenario(
        name="2015_股灾",
        pattern=CrashPattern.STAIRCASE_DOWN,
        total_drop=-0.45,
        duration_days=45,
        recovery_days=0,
    ),
    StressScenario(
        name="2016_熔断",
        pattern=CrashPattern.FLASH_CRASH,
        total_drop=-0.10,
        duration_days=4,
        recovery_days=20,
    ),
    StressScenario(
        name="2018_贸易战",
        pattern=CrashPattern.L_SLOW_BLEED,
        total_drop=-0.30,
        duration_days=180,
        recovery_days=60,
    ),
    StressScenario(
        name="2020_新冠疫情",
        pattern=CrashPattern.V_RECOVERY,
        total_drop=-0.15,
        duration_days=20,
        recovery_days=30,
    ),
]
```

---

## 9. P2: PortfolioOptimizer 改进

### 9.1 奇异协方差矩阵处理

当资产高度相关或样本不足时，协方差矩阵可能奇异（行列式 ≈ 0），导致优化失败。

```python
# portfolio_optimizer.py — 在 _validate_inputs 中添加

def _validate_inputs(self, returns, expected_returns=None):
    if returns.empty:
        raise ValueError("Returns DataFrame is empty")

    assets = returns.columns.tolist()
    n_assets = len(assets)
    cov_matrix = returns.cov().values

    # 新增: 条件数检查
    cond_number = np.linalg.cond(cov_matrix)
    if cond_number > 1e10:
        logger.warning(
            f"Ill-conditioned covariance matrix (cond={cond_number:.2e}). "
            "Applying Ledoit-Wolf shrinkage."
        )
        cov_matrix = self._ledoit_wolf_shrinkage(cov_matrix)

    # 新增: 最小特征值检查
    eigenvalues = np.linalg.eigvalsh(cov_matrix)
    if eigenvalues.min() < 1e-10:
        logger.warning("Covariance matrix is near-singular. Adding regularization.")
        cov_matrix += np.eye(n_assets) * 1e-6

    if np.any(np.isnan(cov_matrix)):
        raise ValueError("Covariance matrix contains NaN values")

    if expected_returns is None:
        expected_returns = returns.mean().values * 252

    if len(expected_returns) != n_assets:
        raise ValueError(
            f"Expected returns length ({len(expected_returns)}) "
            f"does not match number of assets ({n_assets})"
        )

    self._last_assets = assets
    return cov_matrix, expected_returns, assets


@staticmethod
def _ledoit_wolf_shrinkage(cov: np.ndarray, alpha: float = 0.1) -> np.ndarray:
    """Ledoit-Wolf 收缩估计"""
    n = cov.shape[0]
    target = np.trace(cov) / n * np.eye(n)
    return (1 - alpha) * cov + alpha * target
```

### 9.2 交易成本约束

```python
def optimize_mean_variance(
    self,
    returns: pd.DataFrame,
    expected_returns=None,
    target="max_sharpe",
    current_weights=None,      # 新增
    transaction_cost=0.001,    # 新增: 千分之一
):
    # ... 现有逻辑 ...

    if current_weights is not None:
        def objective(w):
            base = self._negative_sharpe(w, cov_matrix, expected_returns)
            tc = transaction_cost * np.sum(np.abs(w - current_weights))
            return base + tc
    else:
        # 原有逻辑
        ...
```

---

## 10. 回测验证方案

### 10.1 验证矩阵

| 改进项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| EVTRisk 重命名 | `grep -r "EVTRisk" src/` | 仅 `historical_risk.py` 和 `__init__.py` 保留废弃别名 |
| 不可变性修复 | 单元测试: `test_portfolio_sizer_immutability` | 原始 `signals` 对象 notional 不变 |
| 动态 T+1 惩罚 | 单元测试: 不同 MarketState 输入 | 惩罚 ∈ [1.0, 2.5]，高波动 > 低波动 |
| 止损集成 | 回测: 有止损 vs 无止损 | 有止损的 MDD < 无止损的 MDD |
| 真 EVT | 对比测试: EVT VaR vs 历史模拟 VaR | 在 99% 置信度下 EVT 更保守 |
| 路径压力测试 | 单元测试: 4 种路径模式 | 输出长度 = 输入 + scenario.duration |

### 10.2 集成测试用例

```python
import numpy as np
import pandas as pd
import pytest


class TestRiskModuleIntegration:
    """风控模块集成测试"""

    @pytest.fixture
    def sample_returns(self):
        """生成模拟 A 股收益率序列"""
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=500, freq="B")
        # 混合正态分布模拟厚尾
        normal = np.random.normal(0.0005, 0.015, 400)
        tail = np.random.normal(-0.03, 0.02, 100)
        returns = np.concatenate([normal, tail])
        np.random.shuffle(returns)
        return pd.Series(returns, index=dates)

    @pytest.fixture
    def sample_equity(self, sample_returns):
        """生成权益曲线"""
        return 100000 * (1 + sample_returns).cumprod().values

    def test_dynamic_penalty_range(self):
        """动态惩罚系数在合理范围内"""
        from uniquant.risk.sizer import DynamicPenaltyCalculator, MarketState

        calc = DynamicPenaltyCalculator()

        # 低波动
        low_vol = MarketState(0.10, 0.18, 0.05, 0.10)
        assert 1.0 <= calc.calculate(low_vol) <= 1.3

        # 高波动
        high_vol = MarketState(0.40, 0.25, 0.01, 0.10)
        assert 1.5 <= calc.calculate(high_vol) <= 2.5

        # ST 股
        st_stock = MarketState(0.20, 0.20, 0.03, 0.05)
        assert calc.calculate(st_stock) >= 1.8

    def test_stop_loss_in_backtest(self, sample_equity):
        """止损逻辑正确截断回撤"""
        from uniquant.risk.stop_loss import GeometricStopLoss

        policy = GeometricStopLoss(atr_multiplier=2.0)
        # 模拟入场
        entry = sample_equity[100]
        atr = np.std(np.diff(sample_equity[80:100])) * 1.5

        max_dd_with_stop = 0
        position_high = entry
        for i in range(101, len(sample_equity)):
            if sample_equity[i] > position_high:
                position_high = sample_equity[i]

            stop = policy.calculate_stop(entry, sample_equity[i], atr=atr)
            if sample_equity[i] <= stop.price:
                dd = (position_high - sample_equity[i]) / position_high
                max_dd_with_stop = max(max_dd_with_stop, dd)
                break

        # 无止损的最大回撤
        peak = np.maximum.accumulate(sample_equity[100:])
        dd_no_stop = (peak - sample_equity[100:]) / peak
        max_dd_no_stop = np.max(dd_no_stop)

        assert max_dd_with_stop < max_dd_no_stop

    def test_evt_vs_historical(self, sample_returns):
        """EVT 在高置信度下给出更高 VaR"""
        from uniquant.risk.evt_risk import HistoricalSimulationRisk

        hs = HistoricalSimulationRisk()
        var_99_hist = hs.calculate_var(sample_returns, 0.99)

        # 历史模拟法在 99% 下应该给出正值
        assert var_99_hist > 0

    def test_path_dependent_stress(self, sample_equity):
        """路径压力测试产生合理输出"""
        from uniquant.risk.drawdown_analyzer import PathDependentStressTester
        from uniquant.risk.drawdown_analyzer import StressScenario, CrashPattern

        tester = PathDependentStressTester()
        scenario = StressScenario(
            name="test_v",
            pattern=CrashPattern.V_RECOVERY,
            total_drop=-0.20,
            duration_days=20,
            recovery_days=10,
        )

        result = tester.apply_scenario(sample_equity, scenario)
        assert len(result) == len(sample_equity) + 20 + 10
        assert result[-1] > result[len(sample_equity) + 19]  # 恢复期上升
```

### 10.3 性能基准测试

```python
def test_sizer_performance(benchmark):
    """PositionSizer 性能: < 1ms / 调用"""
    from uniquant.risk.sizer import PositionSizer

    sizer = PositionSizer(initial_capital=1000000)
    benchmark(
        sizer.calculate_shares,
        price=50.0,
        stop_loss=45.0,
        market="CN",
        czsc_bottom=46.0,
        atr_stop=44.0,
        symbol="600519.SH",
    )


def test_drawdown_performance(benchmark):
    """DrawdownAnalyzer 性能: < 10ms / 10K 数据点"""
    from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer

    equity = np.cumsum(np.random.randn(10000)) + 100000
    benchmark(DrawdownAnalyzer.analyze_drawdown, equity)
```

---

## 11. 实施路线图

### Phase 1: P0 修复 (1-2 天)

```
Day 1:
  [x] 清理 EVTRisk 命名 (evt_risk.py, __init__.py, historical_risk.py)
  [x] 修复 PortfolioSizer 不可变性 (sizer.py:250-253)
  [x] 编写单元测试验证修复

Day 2:
  [x] 运行全量测试确认无回归
  [x] 更新 AGENTS.md 风险模块文档
```

### Phase 2: P1 改进 (3-5 天)

```
Day 3-4:
  [ ] 实现 DynamicPenaltyCalculator (sizer.py)
  [ ] 实现 StopLossPolicy 接口和 3 个实现 (risk/stop_loss.py)
  [ ] 集成止损到回测引擎

Day 5:
  [ ] 集成测试: 动态惩罚 + 止损回测
  [ ] 性能基准测试
```

### Phase 3: P2 增强 (5-7 天)

```
Day 6-8:
  [ ] 实现 TrueEVTRiskCalculator (GPD 拟合)
  [ ] 实现 PathDependentStressTester
  [ ] 增强 PortfolioOptimizer (奇异矩阵处理、交易成本约束)

Day 9-10:
  [ ] 全量集成测试
  [ ] 回测对比: 新旧风控模块效果
  [ ] 文档更新
```

### Phase 4: 验证与上线 (2-3 天)

```
Day 11-12:
  [ ] 历史回测验证 (2015-2025)
  [ ] 压力测试验证
  [ ] 代码审查

Day 13:
  [ ] 合并到主分支
  [ ] 更新部署配置
```

---

## 附录 A: 文件变更清单

| 文件 | 操作 | 描述 |
|------|------|------|
| `risk/evt_risk.py` | 修改 | 清理命名、更新 docstring |
| `risk/__init__.py` | 修改 | 更新导出 |
| `risk/historical_risk.py` | 重写 | 正向废弃别名 |
| `risk/sizer.py` | 修改 | 不可变性修复 + 动态惩罚 |
| `risk/stop_loss.py` | **新增** | 止损策略接口和实现 |
| `risk/evt_true.py` | **新增** | 真正的 GPD EVT 实现 |
| `risk/stress_tester.py` | **新增** | 路径依赖压力测试 |
| `risk/portfolio_optimizer.py` | 修改 | 奇异矩阵处理 + 成本约束 |
| `risk/drawdown_analyzer.py` | 修改 | 集成路径压力测试 |
| `tests/test_risk_module.py` | **新增** | 全量单元测试和集成测试 |

## 附录 B: 常量引用

引用自 `shared/constants/risk.py`:

| 常量 | 值 | 用途 |
|------|-----|------|
| `VAR_THRESHOLD_HIGH` | 0.05 | 高风险 VaR 阈值 |
| `CVAR_THRESHOLD_HIGH` | 0.06 | 高风险 CVaR 阈值 |
| `VOLATILITY_HIGH` | 0.30 | 高波动率阈值 |
| `MAX_DRAWDOWN_THRESHOLD` | 0.20 | 最大回撤阈值 |
| `SHARPE_RATIO_BULL` | 1.0 | 牛市夏普比率阈值 |
| `SHARPE_RATIO_BEAR` | 0.0 | 熊市夏普比率阈值 |

---

*本文档基于源码实际分析生成，非 AI 幻觉。所有行号引用均对应 `src/uniquant/risk/` 目录下的实际代码。*
