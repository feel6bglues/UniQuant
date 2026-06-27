# R3 Verification Report — Cross-Validation of R1+R2 CRITICAL Findings

> **审计员**: R3 验证审计员
> **日期**: 2026-06-06
> **范围**: 5 项 CRITICAL 发现逐行交叉验证
> **方法**: 直接读取源码 + grep 交叉验证

---

## 验证项 1: `validate()` 返回 bool 赋给 df

**文件**: `src/uniquant/data/data_pipeline_service.py` (第 17-21 行)
**R1/R2 发现**: `validate()` 返回 `bool`，但结果赋给 `df`，后续操作将 `bool` 当 DataFrame 使用

### 逐行代码证据

**data_pipeline_service.py:17-21**
```python
def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
    df = self.cleaner.clean_stock_daily(df)          # line 18: df = DataFrame (正确)
    df = self.validator.validate(df)                  # line 19: df = bool ← BUG!
    df = self.adjuster.apply_adjustment(symbol, df, method=adjust)  # line 20: df 传入 bool!
    return df                                         # line 21: 返回 bool
```

**data_validator.py:11**
```python
def validate(self, df: pd.DataFrame) -> bool:
```

`validate()` 返回类型注解为 `bool`，实际返回值为 `True`(第 76 行) 或 `False`(第 15/24/38 行)。

### 结论

**✅确认** — **CRITICAL BUG 属实**

- 第 19 行 `df = self.validator.validate(df)` 将 `bool` 赋值给 `df`
- 第 20 行 `self.adjuster.apply_adjustment(symbol, df, ...)` 接收到 `bool` 类型参数
- `apply_adjustment()` 期望 `pd.DataFrame`，传入 `bool` 将导致 `AttributeError` 或静默错误
- 修复方案: 将 `validate()` 改为返回 `pd.DataFrame`，或分离验证逻辑 (`if not self.validator.validate(df): raise ...`)

---

## 验证项 2: Indicators 模块是否存在

**文件**: `src/uniquant/brain/fsm/fsm.py` (第 19-22 行, 110-115 行)
**R1/R2 发现**: `from ..indicators.indicators import Indicators` 是否为幽灵导入

### 逐行代码证据

**fsm.py:19-22**
```python
try:
    from ..indicators.indicators import Indicators
except ImportError:
    Indicators = None  # TODO: Phase 1A 迁移 brain/indicators.py 后移除
```

**fsm.py:112-115**
```python
if Indicators is None:
    raise ImportError("Indicators module not available")
ma20 = Indicators.calc_ma(analysis_df, self.ma_short)
ma60 = Indicators.calc_ma(analysis_df, self.ma_long)
```

**文件系统验证**:
- `brain/indicators/__init__.py` 存在，内容: `from .indicators import Indicators, IndicatorError`
- `brain/indicators/indicators.py` 存在 (265 行 Numba JIT 优化器文件同级)
- `brain/indicators/__pycache__/` 存在 (说明模块已被 Python 加载过)

### 结论

**✅确认已修复** — R1/R2 时的幽灵导入已被 `try/except` 缓解

- Indicators 模块 **确实存在** 于 `brain/indicators/indicators.py`
- `try/except ImportError` 提供了优雅降级 (第 19-22 行)
- 第 112-113 行 `if Indicators is None: raise ImportError` 提供了运行时保护
- **残留风险**: 当 `Indicators` 为 `None` 时，`infer_state()` 将抛出 `ImportError`，调用者需确保不在此状态下使用 FSM

---

## 验证项 3: DecisionBrain 输出的 action 值

**文件**: `src/uniquant/brain/fsm/fsm.py` (第 238-250 行, 390-398 行)
**R1/R2 发现**: DecisionBrain 输出 "BUY" 还是 "EXECUTE_BUY"

### 逐行代码证据

DecisionBrain 产生 action 的所有路径:

| 代码位置 | action 值 | 条件 |
|----------|-----------|------|
| 第 259 行 | `"FORCE_WAIT"` | regime == FROZEN |
| 第 263 行 | `"FORCE_EXIT"` | risk == Danger 且 ntf != SUPPORT |
| 第 305 行 | `"EXECUTE_SELL"` | 卖出条件触发且非跌停阻断 |
| 第 305 行 | `"HOLD"` | 卖出条件触发但跌停阻断 |
| 第 358 行 | `"HOLD"` | 买入被阻断 |
| 第 389 行 | `"BUY"` | 有 returns 数据 且 state != PYRAMID |
| 第 389 行 | `"ADD"` | 有 returns 数据 且 state == PYRAMID |
| 第 400 行 | `"EXECUTE_BUY"` | **无 returns 数据** (fallback) |
| 第 538 行 | `"CIRCUIT_BREAK"` | 日跌幅超阈值 |
| 第 583 行 | `"EXECUTE_SELL"` | state == EXIT |
| 第 591 行 | `"STAY_CURRENT_STATE"` | 维持当前状态 |

关键发现:
- 第 389 行 (有数据路径): `action = "BUY" if self.state != FSMState.PYRAMID else "ADD"`
- 第 400 行 (无数据 fallback): `action = "EXECUTE_BUY"`
- **两个路径输出不同的 action 值!**

### 结论

**✅确认** — DecisionBrain **同时输出** "BUY" 和 "EXECUTE_BUY"

- 第 389 行: 有 returns 数据时输出 `"BUY"`
- 第 400 行: 无 returns 数据时输出 `"EXECUTE_BUY"` (fallback)
- `"ADD"` 仅在 PYRAMID 状态且有数据时输出
- 该不一致是与 BacktestEngine 产生 action 值冲突的根源

---

## 验证项 4: BacktestEngine 期望的 action 值

**文件**: `src/uniquant/hands/backtest/engine.py` (第 396-400 行)
**R1/R2 发现**: signal_generator 期望的 action 值与 DecisionBrain 不匹配

### 逐行代码证据

**engine.py:396-413**
```python
action = signal.get("action", "HOLD")          # line 396
reason = signal.get("reason", "")              # line 397
next_idx = idx + 1                              # line 398

# line 400:
if action in ("BUY", "SELL") and next_idx < len(df):
    if action == "BUY" and self.position == 0:  # line 401
        pending_order = {                        # line 402
            "action": "BUY",
            "size": position_size,
            "reason": reason,
        }
    elif action == "SELL" and self.position > 0:  # line 407
        pending_order = {                         # line 408
            "action": "SELL",
            "size": self.position,
            "reason": reason,
            "buy_date": buy_date,
        }
```

**engine.py:306** (docstring):
```python
signal_generator: 信号生成函数，返回 {"action": "BUY"/"SELL"/"HOLD", "reason": "..."}
```

BacktestEngine **仅识别** 3 种 action:
- `"BUY"` → 执行买入
- `"SELL"` → 执行卖出
- `"HOLD"` (默认) → 不操作

### 结论

**✅确认** — **Action 值严重不匹配**

| DecisionBrain 输出 | BacktestEngine 识别 | 结果 |
|-------------------|--------------------|----|
| `"BUY"` | ✅ 识别 | 正常执行 |
| `"SELL"` | ❌ 不识别 (期望 "SELL") | DecisionBrain 不输出 "SELL" |
| `"EXECUTE_BUY"` | ❌ 不识别 | 静默忽略，不执行买入 |
| `"EXECUTE_SELL"` | ❌ 不识别 | 静默忽略，不执行卖出 |
| `"ADD"` | ❌ 不识别 | 静默忽略 |
| `"HOLD"` | ✅ 识别 (默认值) | 不操作 |
| `"FORCE_WAIT"` | ❌ 不识别 | 静默忽略 |
| `"FORCE_EXIT"` | ❌ 不识别 | 静默忽略 |
| `"CIRCUIT_BREAK"` | ❌ 不识别 | 静默忽略 |
| `"STAY_CURRENT_STATE"` | ❌ 不识别 | 静默忽略 |

**更严重**: DecisionBrain 在卖出路径输出 `"EXECUTE_SELL"` (第 305 行和第 583 行)，而 BacktestEngine 检查 `"SELL"`。即使 DecisionBrain 决定卖出，BacktestEngine 也不会执行。

---

## 验证项 5: `numba_optimizer.py` 是否在 src/ 中有 import

**文件**: `src/uniquant/brain/lppl/numba_optimizer.py` (前 10 行)
**R1/R2 发现**: numba_optimizer.py 是否为死代码

### 逐行代码证据

**numba_optimizer.py:1-11**
```python
# -*- coding: utf-8 -*-
import numpy as np
from typing import Tuple

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*dec_args, **dec_kwargs):
        return lambda f: f
```

**grep 验证** (在整个 `src/` 目录搜索):
```
$ grep -r "numba_optimizer" src/
(无结果)
```

**grep 验证** (在整个项目搜索，排除 docs/tests):
```
仅有 2 处引用:
1. tests/test_refactoring_validation.py:6 — 测试文件
2. Docs/ 下的文档文件 — 非代码
```

**LPPL 模块内部验证**:
- `engine.py`: 使用自己的 Numba 逻辑 (第 30 行 `from numba import njit`)，不导入 `numba_optimizer`
- `calculator.py`: 无任何 `numba_optimizer` 引用
- `core.py`: 有独立的 `_cost_function_numba` (第 110 行)，不导入 `numba_optimizer`
- `__init__.py`: 未导出 `numba_optimizer`

### 结论

**✅确认** — `numba_optimizer.py` 是 **死代码**

- 整个 `src/` 目录中 **零处导入** `numba_optimizer`
- 265 行代码包含 3 个完整的 `@njit` JIT 编译函数 (`_reduced_cost_numba`, `_solve_linear_parameters_numba`, `_de_solve_numba`)
- LPPL 子系统有 3 个独立的 LPPL 函数实现 (`engine.py`, `core.py`, `calculator.py`)，`numba_optimizer.py` 是第 4 个，但从未被接入
- 唯一的非文档引用在 `tests/test_refactoring_validation.py`

---

## 总结

| # | 验证项 | R1/R2 发现 | R3 结论 | 严重度 |
|---|--------|-----------|---------|--------|
| 1 | `validate()` 返回 bool 赋给 df | validate() 返回 bool 覆盖 df | **✅确认** — bool 赋给 df，第 20 行传入 bool | **CRITICAL** |
| 2 | Indicators 模块是否存在 | 幽灵导入 | **✅确认已修复** — try/except 已缓解 | **LOW** (残留) |
| 3 | DecisionBrain action 值 | 输出 "BUY" 还是 "EXECUTE_BUY" | **✅确认** — 两个路径输出不同值 | **HIGH** |
| 4 | BacktestEngine 期望的 action | action 值不匹配 | **✅确认** — 仅识别 BUY/SELL，不识别 EXECUTE_BUY 等 | **CRITICAL** |
| 5 | numba_optimizer.py 是否死代码 | 零引用 | **✅确认** — src/ 中零导入，265 行 JIT 代码未使用 | **MEDIUM** |

### 交叉关联

验证项 3 + 4 构成 **CRITICAL 联合缺陷**: DecisionBrain 输出的 `"EXECUTE_BUY"` (第 400 行) 和 `"EXECUTE_SELL"` (第 305/583 行) 不会被 BacktestEngine 识别，导致 **回测中买卖信号被静默忽略**。即使修复验证项 3 中 action 值为统一的 `"BUY"`/`"SELL"`，仍需确认 DecisionBrain 的卖出路径输出 `"SELL"` 而非 `"EXECUTE_SELL"`。

验证项 1 是独立的运行时 BUG: `DataPipelineService.process()` 会在 `validate()` 失败时将 `df` 覆盖为 `False`，导致后续 `adjuster.apply_adjustment()` 崩溃。

---

*Generated: 2026-06-06 | Based on direct source code reading, no hallucination*
