# UniQuant 审计报告源码核实结果

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> **核实方法**: 5线程并行源码逐行比对
> **核实日期**: 2026-05-31
> **核实范围**: 35+ 具体断言，覆盖审计报告全部7个维度

---

## 总体结论

审计报告整体质量高，核心断言准确率约 **90%**。发现 5 处需要修正的错误，其余所有关键 Bug 均已源码确认。

---

## 一、已确认的 Bug（源码逐行核实）

### Phase 0 紧急 Bug — 全部确认

| # | Bug | 文件 | 行号 | 确认状态 |
|---|-----|------|------|---------|
| 1 | 印花税用 `max_year < 2024` 判断，应为 2023-08-28 | `hands/strategies/backtest.py` | 321 | **确认** |
| 2 | `AnalysisError` 在装饰器中使用但未导入 → 模块加载时 NameError | `brain/czsc/czsc_engine.py` | 147, 442 | **确认** |
| 3 | `Indicators` 设为 None 后直接调用 `.calc_ma()` 无 None 检查 | `brain/fsm/fsm.py` | 112-113 | **确认** |
| 4 | `best_cost` 已是 RMSE，再次 `np.sqrt(best_cost / n)` 双重开方 | `brain/lppl/engine.py` | 348 | **确认** |
| 5 | `np.abs(tc - t)` 数学错误，产生虚假对称波形 | `brain/lppl/visualizer.py` | 123 | **确认** |
| 6 | `MemoryCacheBackend` get/set/delete 完全无线程锁 | `shared/cache/backends.py` | 48-98 | **确认** |

**补充细节**:
- Bug #2 是**模块加载时**的 NameError，不是运行时。Python 解析装饰器参数时立即求值 `AnalysisError`，模块无法加载。
- Bug #3 的 `Indicators = None` 有 TODO 注释，说明是已知技术债，但 None 检查确实缺失。

### Phase 1 重要 Bug — 全部确认

| # | Bug | 文件 | 行号 | 确认状态 |
|---|-----|------|------|---------|
| 7 | FSM `infer_state()` 只能到达 IDLE/SIGNAL/PROBE/MONITOR，PYRAMID/EXIT/CIRCUIT_BREAK 不可达 | `brain/fsm/fsm.py` | 95-158 | **确认** |
| 8 | EXIT 状态：`self.state` 立即重置为 IDLE，但返回值中 state 字段仍为 EXIT | `brain/fsm/fsm.py` | 532-540 | **确认** |
| 9 | 科创板/创业板 `price_collar_pct = 0.01`（±1%），A股规则应为 ±2% | `shared/market_rules.py` | 27-28 | **确认** |
| 10 | 北交所前缀包含 `"4"`（新三板），应为 `"83"/"87"` | `shared/constants/market.py` | 70 | **确认** |
| 11 | LPPL core.py 返回 SSE，engine.py 返回 RMSE，代价函数不一致 | `brain/lppl/core.py:119`, `engine.py:135` | — | **确认** |

### 架构与导入 — 全部确认

| 断言 | 文件 | 确认状态 |
|------|------|---------|
| `data/services/__init__.py` 声明 6 个符号但无任何导入语句 | `data/services/__init__.py` | **确认** |
| `data/scripts/__init__.py` 声明 4 个函数但无任何导入语句 | `data/scripts/__init__.py` | **确认** |
| `lppl_visualizer.py` 第 9 行导入 brain，第 10 行导入 data | `ui/lppl_visualizer.py` | **确认** |
| `manager_portfolio_analytics_service.py` 第 23 行导入 risk | `ui/manager_portfolio_analytics_service.py` | **确认** |
| `dashboard.py` 第 612 行导入 brain | `ui/dashboard.py` | **确认** |
| `brain/wyckoff/__init__.py` 使用绝对导入违反项目规范 | `brain/wyckoff/__init__.py` | **确认** |
| `ServiceContainer.initialize()` 只注册 5 个服务，AnalysisService/HealthService/PortfolioService 未注册 | `services/service_container.py` | **确认** |

### YAML vs 常量冲突 — 确认 9/10 项

| 参数 | YAML 值 | 常量值 | 偏差 | 确认状态 |
|------|---------|--------|------|---------|
| 滑点率 | 0.1% | 0.05% | 2倍 | **确认** |
| FSM MA 短期 | 20 | 5 | 4倍 | **确认** |
| FSM MA 长期 | 60 | 20 | 3倍 | **确认** |
| NTF 窗口 | 5 | 20 | 4倍 | **确认** |
| 大盘市值阈值 | 500亿 | 1000亿 | 2倍 | **确认** |
| 中盘市值阈值 | 100亿 | 300亿 | 3倍 | **确认** |
| 最大回撤阈值 | 0.15 | 0.15 | **无冲突** | **报告有误** |

---

## 二、审计报告的 5 处错误

### 错误 1：ServiceContainer `__all__` 描述不准确（第 1.2 节）

**报告原文**: "ServiceContainer 初始化不完整：`__all__` 列出了 13 个服务类"

**实际情况**: `service_container.py` 中**不存在 `__all__`**。正确描述应为：`initialize()` 方法只注册了 5 个服务，而系统实际需要更多（AnalysisService、HealthService、PortfolioService 等均未注册）。核心问题属实，但引用的 `__all__` 证据不存在。

---

### 错误 2：`get_config()` 线程安全描述过重（第 1.5 节）

**报告原文**: "`get_config()` 非线程安全：使用 `global config` + `if config is None` 检查，没有加锁，存在竞态条件"

**实际情况**: `GlobalConfig.__new__` 使用了**双重检查锁定模式**（`cls._lock`），单例创建是线程安全的。模块级 `config` 变量确实存在轻微竞态，但远没有报告描述的严重。这不是 P1 级问题。

---

### 错误 3：最大回撤阈值冲突不存在（第 5.1 节）

**报告原文**: "最大回撤阈值：YAML 0.15 vs 常量 0.20，不一致"

**实际情况**: YAML (`circuit_break_pct: 0.15`) 和常量 (`MAX_DRAWDOWN_LIMIT = 0.15`) **均为 0.15**，无冲突。报告列出的 10 项冲突中此项为误报。

---

### 错误 4：LPPL 实现数量描述略有偏差（第 2.3 节）

**报告原文**: "4 个文件中存在 4 种 LPPL 函数实现"，其中 `numba_optimizer.py` 有 `_lppl_func_numba`

**实际情况**: `numba_optimizer.py` **没有独立的 `_lppl_func_numba` 函数**，LPPL 计算被内联在 `_reduced_cost_numba()` 的循环体内（第 42-51 行）。实际是 3 个独立函数 + 1 个内联实现，"4 种独立实现"的说法略有夸大，但代码重复问题属实。

---

### 错误 5：价格笼子术语混淆（第 3.6 节）

**报告原文**: 使用"价格笼子"术语，并描述为 `limit_checker.py` 中的实现

**实际情况**: 代码中该功能叫 **`price_collar`**，实现在 `shared/price_collar.py` + `shared/market_rules.py`，与 `limit_checker.py`（涨跌停检查）是两个独立模块。±1% 不合规的核心断言**完全正确**，只是文件定位和术语有偏差。

---

## 三、核实结论汇总

| 类别 | 数量 | 结果 |
|------|------|------|
| Phase 0 紧急 Bug | 6 | 全部确认 |
| Phase 1 重要 Bug | 5 | 全部确认 |
| 架构/导入断言 | 7 | 全部确认 |
| YAML/常量冲突 | 10 | 9 确认，1 误报（最大回撤） |
| 报告错误 | 5 | 已列出并说明 |

**审计报告可信度**: 核心 Bug 断言 100% 准确，整体准确率约 90%。5 处错误均为描述细节问题，不影响修复优先级判断。

---

## 四、Phase 0 修复文件速查

```
hands/strategies/backtest.py:321     印花税年份判断 → 改为 date >= 2023-08-28
brain/czsc/czsc_engine.py:14         添加 from ...shared.exceptions import AnalysisError
brain/fsm/fsm.py:112                 添加 if Indicators is None: raise ImportError(...)
brain/lppl/engine.py:348             rmse = best_cost  (删除 np.sqrt 和 /len)
brain/lppl/visualizer.py:123         tau = tc - t; result[tau <= 0] = np.nan
shared/cache/backends.py:28          添加 self._lock = threading.Lock()
```

---

*核实完成时间: 2026-05-31 | 基于源码事实，5线程并行验证*
