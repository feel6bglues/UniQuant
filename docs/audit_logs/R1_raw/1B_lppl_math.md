# R1-LPPL 数学层深度审计

> 审计范围: `src/uniquant/brain/lppl/` (11 文件)
> 审计员: R1-LPPL Auditor
> 日期: 2026-06-06

---

## 1. 审计文件清单

| 文件 | 行数 | 角色 |
|------|------|------|
| `engine.py` | 1037 | 顶层引擎：DE 7维优化 + L-BFGS-B + 扫描 + 集成 + 风险判定 |
| `calculator.py` | 601 | 核心计算器：DE 3维 VarPro + 置信度 + Sornette 约束 |
| `core.py` | 200 | 底层核心：cost_function、输入校验、抄底信号 |
| `numba_optimizer.py` | 265 | Numba JIT 3维 VarPro DE（孤立模块） |
| `computation.py` | 391 | 多进程批处理编排 |
| `__init__.py` | 25 | 包导出 |
| 其余 5 文件 | -- | data_manager/visualizer/regime/multifit/cluster |

---

## 2. 三套差分进化 (DE) 优化器语义一致性审计

### 2.1 三套 DE 概览

| 维度 | `engine.py:fit_single_window` | `calculator.py:fit_single_window` / `fit` | `numba_optimizer.py:_de_solve_numba` |
|------|------|------|------|
| **优化维度** | **7 维** [tc, m, w, a, b, c, phi] | **3 维** [tc, m, w] → VarPro 求解 a,b,c,phi | **3 维** [tc, m, w] → VarPro 求解 a,b,c,phi |
| **目标函数** | `cost_function()` → RMSE = sqrt(mean(residuals^2)) | `cost_function_reduced()` → SSE = ||y - X*beta||^2 | `_reduced_cost_numba()` → SSE (手动 OLS) |
| **优化器** | scipy `differential_evolution` | scipy `differential_evolution` | 手写 JIT-compiled DE |
| **tc 下界** | `current_t + tc_bound[0]` = window+1 | `max(0, current_t - tc_backward)` | 隐式: tc > t[n-1] + 0.5 |
| **tc 上界** | `current_t + tc_bound[1]` = window+100 | `current_max_t + tc_forward` = len(df)+100 | 无上界 |
| **w 范围** | config.w_bounds = **(5, 18)** | config.w_range = **(6, 13)** | 调用方传入 bounds |
| **m 范围** | config.m_bounds = (0.1, 0.9) | config.m_range = (0.1, 0.9) | 调用方传入 bounds |
| **策略** | `best1bin` | `best1bin` | `DE/rand/1/bin` (rand 选3个) |
| **种群** | popsize=15 (默认) | popsize=10 (配置) | popsize=15 (默认) |
| **收敛判据** | scipy 内置 (tol=0.05) | scipy 内置 (tol=0.01) | max(fitness)-min(fitness) < tol |
| **变异** | scipy 默认 | mutation=(0.5, 1.0) | F = uniform(0.5, 1.0) |
| **重组** | scipy 默认 0.7 | recombination=0.7 | recombination=0.7 |
| **目标函数值** | RMSE | SSE | SSE |

### 2.2 关键不一致：**[CRITICAL] 7 维 vs 3 维 VarPro**

`engine.py:fit_single_window` (line 204) 对全部 7 个参数做 DE：
```python
bounds = [
    (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),  # tc
    config.m_bounds,     # m
    config.w_bounds,     # w
    (log_min, log_max * 1.1),  # a
    (-20, 20),           # b
    (-20, 20),           # c
    (0, 2 * np.pi),      # phi
]
result = differential_evolution(cost_function, bounds, args=(...))
```

`calculator.py:fit_single_window` (line 309) 和 `numba_optimizer.py:_de_solve_numba` (line 176) 只对 3 个非线性参数做 DE，线性参数 (a, b, c, phi) 通过 OLS/VarPro 解析求解：
```python
bounds = [
    (max(0, current_t - self.tc_backward), current_t + self.tc_forward),  # tc
    (self.m_min, self.m_max),   # m
    (self.w_min, self.w_max),   # w
]
result = differential_evolution(self.cost_function_reduced, bounds, args=(...))
```

**语义差异**:
- 7 维 DE 在 7D 空间搜索，搜索空间体积 = (100 * 0.8 * 13 * ~1.3 * 40 * 40 * 6.28) ≈ 1.35e8
- 3 维 VarPro DE 在 3D 空间搜索，搜索空间体积 = (150 * 0.8 * 7) ≈ 840
- VarPro 将线性参数投影消除，**在相同迭代次数下收敛概率更高**，且理论等价（给定非线性参数后，线性参数有唯一最优解）
- engine.py 的 7 维搜索**理论上可以找到等价解**，但实际在相同 popsize/maxiter 下**更难收敛**，且 `a, b, c, phi` 的 bounds 是人为设定的硬截断，可能截断真实最优解

**影响**: engine.py 的 `fit_single_window`（及其调用方 `scan_single_date`, `scan_date_range`, `process_single_day_ensemble`）使用次优的 7 维优化；calculator.py 的 `fit_single_window` 和 `fit` 使用更优的 3 维 VarPro。两套并行运行，产生不同结果。

### 2.3 关键不一致：**[HIGH] W_BOUNDS 范围不一致**

| 来源 | w_min | w_max |
|------|-------|-------|
| `constants/technical.py:W_BOUNDS` | **6.0** | **13.0** |
| `engine.py:LPPLConfig.w_bounds` | **5** | **18** |
| `calculator.py:w_range` (配置默认) | **6** | **13** |

engine.py 的 LPPLConfig 默认 w 范围 (5, 18) 比 constants 定义的 (6, 13) 宽 **~2 倍**。engine.py 虽然 import 了 `W_BOUNDS`（line 23），但从未使用它——LPPLConfig 自带默认值覆盖了。

`_is_valid_bubble()` (engine.py:818) 使用从 constants import 的 `W_BOUNDS` (6, 13)；`classify_top_phase()` (engine.py:106) 使用 LPPLConfig 的 w_bounds (5, 18)。**同一引擎内部对 w 的有效范围判定不一致。**

### 2.4 关键不一致：**[MEDIUM] 目标函数语义不一致**

| 优化器 | 目标函数 | 惩罚值 |
|--------|---------|--------|
| engine.py (7D) | RMSE | 无显式惩罚 (scipy 处理) |
| calculator.py (3D VarPro) | SSE | tc <= current_t+0.5 → 1e20; tau<=0 → 1e20; non-finite → 1e10 |
| numba_optimizer.py (3D VarPro) | SSE | tc <= t[n-1]+0.5 → 1e20; tau<=0 → 1e20; singular → 1e20 |

engine.py 的 cost_function **无任何边界惩罚**（tau <= 0 时不保护），而另外两个版本都有严格的惩罚机制。当 DE 探索到 tc <= max(t) 时，engine.py 会产生 `log(负数)` 或 `负数的非整数次幂`，导致 `nan`/`inf` 返回值，scipy 可能静默处理或抛出异常。

---

## 3. numba_optimizer.py 生产调用审计

### 3.1 grep 结果

```
$ grep -r "numba_optimizer" src/
  (无结果)
```

**结论: `numba_optimizer.py` 是死代码，无任何生产调用。**

### 3.2 模块依赖分析

- `__init__.py` 未导出 numba_optimizer
- `engine.py` 不 import numba_optimizer
- `core.py` 不 import numba_optimizer
- `computation.py` 不 import numba_optimizer
- `calculator.py` 不 import numba_optimizer

该文件可能是从旧版本保留的实验性代码，或为未来性能优化预留的未启用实现。

### 3.3 代码质量备注

即使未来启用，numba_optimizer.py 存在以下问题:
- `_de_solve_numba` 使用 `DE/rand/1/bin` 策略，与 scipy 的 `best1bin` 不同
- 手写 DE 实现缺少 scipy DE 的多项改进（自适应变异、多策略、边界处理）
- `try/except Exception` (line 89, 171) 过于宽泛，会吞掉所有异常

---

## 4. engine.py:584 itertuples() 性能审计

### 4.1 代码位置

`engine.py:582-605` (`calculate_trend_scores` 函数):
```python
if "is_danger" not in df.columns:
    is_danger_list = []
    for row in df.itertuples():
        is_d = (
            config.m_bounds[0] < row.m < config.m_bounds[1]
            and config.w_bounds[0] < row.w < config.w_bounds[1]
            and row.days_to_crash < config.danger_days
            and row.r_squared > config.r2_threshold
        )
        is_danger_list.append(is_d)
    df["is_danger"] = is_danger_list

if "is_warning" not in df.columns:
    is_warning_list = []
    for row in df.itertuples():
        phase = classify_top_phase(float(row.days_to_crash), float(row.r_squared), config)
        ...
```

### 4.2 性能评估

- `itertuples()` 比 `iterrows()` 快约 10-100x，但仍是**逐行 Python 循环**
- 典型调用: `analyze_peak()` 中 `daily_results` 可能有 60-120 行（120 天扫描范围，step=2）
- 在 60 行规模下，性能影响微乎其微 (< 1ms)
- 但在 `calculate_trend_scores` 被**批量调用**时（如 `analyze_peak` 内部已通过 joblib 并行），累积影响可能显现

### 4.3 向量化替代方案

```python
# 可替代 lines 583-592
m_arr = df["m"].values
w_arr = df["w"].values
days_arr = df["days_to_crash"].values
r2_arr = df["r_squared"].values
df["is_danger"] = (
    (config.m_bounds[0] < m_arr) & (m_arr < config.m_bounds[1])
    & (config.w_bounds[0] < w_arr) & (w_arr < config.w_bounds[1])
    & (days_arr < config.danger_days)
    & (r2_arr > config.r2_threshold)
)
```

**评级: [LOW]** — 当前规模下性能影响可忽略，但属于技术债。

---

## 5. core.py:71 循环导入风险审计

### 5.1 导入链分析

```
core.py line 71:  from uniquant.brain.lppl.calculator import lppl_func
engine.py line 123: from ...brain.lppl.calculator import lppl_func
computation.py line 15: from uniquant.brain.lppl.core import (...)
computation.py line 20: from uniquant.brain.lppl.engine import (...)
__init__.py line 4: from .engine import LPPLConfig, LPPLEngine
__init__.py line 7: from .calculator import LPPLCalculator, lppl_func
```

当前导入链:
```
__init__.py → engine.py → calculator.py (lppl_func)
            → calculator.py (lppl_func, LPPLCalculator)
core.py → calculator.py (lppl_func)
computation.py → core.py → calculator.py
             → engine.py → calculator.py
```

**当前无循环**: calculator.py 不导入 core.py 或 engine.py。

### 5.2 风险评估

core.py:71 的顶层导入是**脆弱设计**:
1. core.py 位于包的"底层"（命名暗示），却依赖 calculator.py（"高层"计算模块）
2. 如果未来 calculator.py 需要 import core 的功能（如 `validate_input_data`），将产生循环导入
3. `engine.py:123` 和 `core.py:71` 都导入同一个 `lppl_func`，说明 `lppl_func` 应该被提升到更底层的共享位置（如 `__init__.py` 或独立的 `_lppl_model.py`）

**评级: [MEDIUM]** — 当前无循环，但架构设计上是定时炸弹。core.py 不应依赖 calculator.py。

### 5.3 建议

将 `lppl_func` 从 `calculator.py` 提取到独立的 `_lppl_model.py`（或放入 `core.py` 本身），消除 core → calculator 的反向依赖。

---

## 6. precheck_fit_input 重复定义且不一致

### 6.1 两处定义对比

| 属性 | `engine.py:133-142` | `core.py:58-68` |
|------|---------------------|-----------------|
| 返回类型 | `Optional[str]` | `Optional[FitFailureReason]` (Literal) |
| 检查 1 | None 或 len < window_size → "insufficient_data" | len < window_size → "insufficient_data" |
| 检查 2 | window_size < 10 → "window_too_small" | any(subset <= 0) → "non_positive_price" |
| 检查 3 | std(recent[-5:]) < 1e-8 → "no_price_variation" | any(~isfinite(subset)) → "nan_or_inf" |
| 检查 4 | -- | ptp(subset) < 1e-10 → "constant_price" |
| None 检查 | 检查 close_prices is None | 不检查 None |
| 正价格检查 | 不检查 | 检查 subset <= 0 |
| NaN/Inf 检查 | 不检查 | 检查 ~isfinite |
| 窗口最小值 | 检查 window < 10 | 不检查 |
| 价格变化检查 | std < 1e-8 (最近5个) | ptp < 1e-10 (整个窗口) |

### 6.2 不一致影响

**engine.py 遗漏的校验**:
- 不检查正价格（非正价格可能导致 `log()` 出错）
- 不检查 NaN/Inf（NaN 会传播到优化器导致不可预测行为）
- 不检查 None 输入（line 172 另有单独检查，但 line 272 的 lbfgsb 路径无此检查）

**core.py 遗漏的校验**:
- 不检查 window_size < 10（过小窗口导致过拟合）
- 不检查 close_prices is None

**两处各覆盖对方的盲区，但没有一处是完整的。**

### 6.3 调用方分析

- engine.py 的 `fit_single_window` (line 175) 和 `fit_single_window_lbfgsb` (line 272) 调用 **engine.py 自己的** precheck_fit_input
- core.py 的 precheck_fit_input **无直接调用方**（computation.py 通过 core 导入了其他函数，但未导入 precheck_fit_input）

**实际影响**: core.py 的 precheck_fit_input 可能是为 core 内部的拟合函数预留的，但 core.py 内部并无拟合函数调用它。两套 precheck 形成冗余代码。

**评级: [HIGH]** — 功能重复 + 校验逻辑不一致，且任一路径都可能遗漏关键校验。

---

## 7. cost_function 重复定义且不一致

### 7.1 三处定义对比

| 属性 | `engine.py:126-130` | `core.py:74-89` | `calculator.py:212-230` |
|------|---------------------|-----------------|------------------------|
| 类型 | 模块函数 | 模块函数 | 实例方法 |
| 异常处理 | 无 (裸调 lppl_func) | catch FloatingPointError/OverflowError/ValueError → 1e10 | 检查 NaN/Inf → 1e10 |
| lppl_func 来源 | 从 calculator 导入 | 从 calculator 导入 (Python 路径) 或内联 numba 版 | self.lppl_func (委托到模块级) |
| NumPy 保护 | 无 | Python 路径有 try/except; Numba 路径无 | NaN/Inf 检查 |
| 调用方 | engine.py 自身 | core.py 内部 (无直接调用方) | calculator.py 内部 |

### 7.2 engine.py cost_function 的脆弱性

```python
def cost_function(params: Tuple, t_data: np.ndarray, log_price: np.ndarray) -> float:
    tc, m, w, a, b, c, phi = params
    fitted = lppl_func(t_data, tc, m, w, a, b, c, phi)
    return float(np.sqrt(np.mean((fitted - log_price) ** 2)))
```

- 若 `lppl_func` 返回含 NaN 的数组（tc <= max(t) 时发生），`np.mean` 会返回 NaN，`float(NaN)` 被 scipy DE 接受但语义错误
- 无 fallback/惩罚值，与 calculator.py 的 `1e10` 惩罚不一致
- scipy DE 可能因 NaN 返回值而产生不可预测的收敛行为

**评级: [HIGH]** — engine.py 的 cost_function 缺少 NaN 保护，在边界条件下可能产生错误结果。

---

## 8. 附加发现

### 8.1 [LOW] engine.py 重复导入

engine.py 顶部导入了 `joblib.Parallel, delayed` (line 20-21)，但 `scan_date_range` (line 494) 和 `analyze_peak` (line 655) 又在函数内部 `from joblib import Parallel, delayed`。冗余但无害。

### 8.2 [LOW] engine.py 重复 `import os`

engine.py 顶部已 `import os` (line 13)，但 `LPPLConfig.__post_init__` (line 84) 再次 `import os`。

### 8.3 [MEDIUM] calculator.py RMSE 计算方式

`calculator.py:fit_single_window` (line 351):
```python
rmse = np.sqrt(residuals[0] / current_t)
```
其中 `residuals[0]` 来自 `np.linalg.lstsq`，返回的是残差平方和 (SSE)。`current_t = len(close_prices)`。所以 RMSE = sqrt(SSE/n)，这是正确的。

但注意：`cost_function_reduced` 返回的 `result.fun` 是 SSE（不是 RMSE），而 `fit` (line 546) 做了 `np.sqrt(result.fun / len(df))` 转换。两处都正确，但**语义不透明**：同一个 cost function 返回 SSE，但 `cost_function` (line 212) 返回 RMSE。

### 8.4 [MEDIUM] engine.py L-BFGS-B 路径无 NaN 保护

`fit_single_window_lbfgsb` (line 255-365) 使用 `minimize(method="L-BFGS-B")` + `cost_function`。由于 cost_function 无 NaN 保护，L-BFGS-B 在探索边界时可能接收到 NaN 梯度，导致静默失败。

---

## 9. 风险评级汇总

| # | 发现 | 严重度 | 文件 | 行号 |
|---|------|--------|------|------|
| F1 | 三套 DE 优化维度不一致 (7D vs 3D VarPro) | **CRITICAL** | engine.py / calculator.py / numba_optimizer.py | 204 / 309 / 176 |
| F2 | W_BOUNDS 范围不一致 (5,18 vs 6,13) | **CRITICAL** | engine.py vs constants/technical.py | 63 / 6 |
| F3 | cost_function 缺少 NaN 保护 | **HIGH** | engine.py | 126-130 |
| F4 | precheck_fit_input 重复且校验不一致 | **HIGH** | engine.py / core.py | 133 / 58 |
| F5 | numba_optimizer.py 死代码 | **MEDIUM** | numba_optimizer.py | 全文件 |
| F6 | core.py → calculator.py 反向依赖 | **MEDIUM** | core.py | 71 |
| F7 | _is_valid_bubble vs classify_top_phase w 范围不一致 | **MEDIUM** | engine.py | 818 vs 106 |
| F8 | itertuples() 可向量化 | **LOW** | engine.py | 584, 597 |
| F9 | 重复 import os / import joblib | **LOW** | engine.py | 84, 494, 655 |

---

## 10. 修复建议优先级

1. **P0 — 统一优化维度**: engine.py 的 `fit_single_window` 应改用 3 维 VarPro（与 calculator.py 一致），消除 7 维搜索
2. **P0 — 统一 W_BOUNDS**: LPPLConfig 默认 w_bounds 应与 constants.W_BOUNDS 对齐为 (6, 13)
3. **P1 — 统一 cost_function**: 在 core.py 定义唯一权威的 cost_function，engine.py 和 calculator.py 均导入使用
4. **P1 — 统一 precheck_fit_input**: 在 core.py 定义唯一完整版本（合并两者的校验逻辑），engine.py 导入使用
5. **P2 — 消除 core → calculator 反向依赖**: 提取 lppl_func 到独立模块
6. **P2 — 删除 numba_optimizer.py** 或明确标记为实验性/未启用
7. **P3 — 向量化 itertuples**: 使用 NumPy 数组操作替代逐行循环
