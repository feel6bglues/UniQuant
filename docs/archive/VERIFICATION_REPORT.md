# 评估报告核实报告

> **核实对象:** docs/EVALUATION_REPORT.md
>
> **核实方法:** 4 个独立核实 Agent 并行执行，分别验证文件计数、文档可信度、依赖声明、测试与导入链
>
> **原则:** 禁止幻觉 — 所有结论必须有文件路径、行号或命令输出作为依据
>
> **核实日期:** 2026-05-26

---

## 核实结论汇总

### ✅ 完全确认 (无修正)

| 报告声明 | 核实结果 | 依据 |
|---------|---------|------|
| shared/ 有 23 个 Python 文件 | ✅ 确认 | glob `src/uniquant/shared/**/*.py` 返回 23 个文件 |
| brain/ 有 5 个文件 | ✅ 确认 | `brain/czsc/czsc_engine.py`, `brain/fsm/fsm.py`, `brain/lppl/{__init__,engine,numba_optimizer}.py` |
| ui/ 有 2 个文件 | ✅ 确认 | `dashboard.py`, `health_check.py` |
| risk/ 有 1 个文件 | ✅ 确认 | `drawdown_analyzer.py` |
| hands/ 有 1 个文件 (空壳) | ✅ 确认 | 仅 `__init__.py`，无实际代码 |
| data/ 不存在 (0 文件) | ✅ 确认 | `ls src/uniquant/data/` 目录不存在 |
| signal/ 不存在 (0 文件) | ✅ 确认 | `ls src/uniquant/signal/` 目录不存在 |
| services/__init__.py 导入 8 个不存在模块 | ✅ 确认 | 逐一检查：CacheCoordinator, DataQualityService, DataService, HealthService, PortfolioService, ScanPipeline, StockQueryService, ValidationService — **全部文件不存在** |
| services/analysis/__init__.py 导入 signal_service + wyckoff | ✅ 确认 | 两个模块文件均不存在 |
| hands/__init__.py 使用 __getattr__ 懒加载 3 个不存在模块 | ✅ 确认 | Reporter, ResultsManager, strategies — 全部文件不存在 |
| brain/fsm/fsm.py 的 indicators 导入会失败 | ✅ 确认 | `from ..indicators import Indicators`，而 `brain/indicators.py` 不存在 |
| mootdx 在 pyproject.toml 中声明但代码中 0 使用 | ✅ 确认 | pyproject.toml:17 有 `mootdx>=0.11.7`，grep `src/` 返回 0 结果 |
| pybreaker 和 tenacity 未在 pyproject.toml 中声明 | ✅ 确认 | grep pybreaker/tenacity 返回 0 结果 |
| analysis_service.py = 1650 行 | ✅ 确认 | `wc -l` 返回 1650 |
| constants.py = 1139 行 | ✅ 确认 | `wc -l` 返回 1139 |
| dashboard.py = 1518 行 | ✅ 确认 | `wc -l` 返回 1518 |
| TDX 项目存在于 /home/james/Documents/Project/TDX/ | ✅ 确认 | `ls` 返回 src/ 目录含 145 个 .py 文件 |
| reference/constants.md 与实际 constants.py 一致 | ✅ 确认 | 文档中列出的 20 个常量类在源码中全部存在 |
| reference/exceptions.md 异常层次与实际一致 | ✅ 确认 | 异常树与 exceptions.py 精确匹配 |
| 10 个文档不可信 (引用不存在模块) | ✅ 确认 | data.md, hands.md, signal.md, quickstart.md, backtest.md, factors.md, strategies.md, data_sources.md, testing.md, project_structure.md — 全部引用不存在的模块 |
| 65 个测试函数 | ✅ 确认 | `grep "def test_" tests/` 返回 65 个匹配 |

---

### ⚠️ 发现差异 (需修正)

#### 差异 1: services/ 文件计数

| | 报告声明 | 实际 | 修正 |
|--|---------|------|------|
| | 10 个文件 (42%) | **11 个文件** | 修正为 11/24 (46%) |

**依据:** glob `src/uniquant/services/**/*.py` 返回 11 个文件:
```
services/__init__.py
services/analysis_service.py
services/service_container.py
services/analysis/__init__.py          ← 报告漏计此文件
services/analysis/czsc_analysis_engine.py
services/analysis/engine_factory.py
services/analysis/macro_service.py
services/analysis/ntf_analysis_engine.py
services/analysis/regime_analysis_engine.py
services/analysis/report_generator_engine.py
services/analysis/technical_service.py
```

**原因:** 报告漏计了 `services/analysis/__init__.py`。

---

#### 差异 2: 总 LOC 估算

| | 报告声明 | 实际 | 修正 |
|--|---------|------|------|
| | ~15K LOC | **12,616 行** | 修正为 ~12.6K LOC |

**依据:** `find src/ -name "*.py" -exec cat {} + | wc -l` 返回 12,616。

**原因:** 报告高估了约 16%。

---

#### 差异 3: 文件总数内部不一致

| | 报告位置 | 声明 | 实际 |
|--|---------|------|------|
| 标题行 / 附录 | "43 个源文件" | **44 个文件** |
| 正文 / 总览表 | "44 文件" | **44 个文件** |

**依据:** glob `src/uniquant/**/*.py` 返回 44 个文件。正确总数为 44（含顶层 `__init__.py`）。

**原因:** 报告附录标题写 "43 文件" 但正文写 "44 文件"，存在内部矛盾。正确值为 **44**。

---

#### 差异 4: 测试类计数

| | 报告声明 | 实际 | 修正 |
|--|---------|------|------|
| | 12 个测试类 | **10 个测试类** | 修正为 10 |

**依据:** `grep "class Test" tests/*.py` 返回 10 个类:
```
TestNTFEngine, TestNTFEngineEdgeCases, TestCZSCEngine, TestCZSCEngineEdgeCases,
TestEngineFactory, TestRegimeDetector, TestRegimeEnum, TestNTFEngineAdditional,
TestRegimeDetectorAdditional, TestPrepareBarListVectorization
```

**注意:** 65 个测试函数数是正确的。

---

#### 差异 5: "import uniquant 崩溃"表述不精确

| | 报告声明 | 实际 | 修正 |
|--|---------|------|------|
| | `import uniquant` 即时崩溃 | `import uniquant` 本身成功；`import uniquant.services` 崩溃 | 修正表述 |

**依据:**
- `python -c "import uniquant"` → 成功（`__init__.py` 仅设置 `__version__`）
- `python -c "import uniquant.services"` → 失败：`ModuleNotFoundError: No module named 'uniquant.services.cache_coordinator'`

**原因:** 顶层 `import uniquant` 不会崩溃（`__init__.py` 不导入 services）。但任何触及 `uniquant.services` 的代码都会崩溃，包括所有分析引擎导入。

---

#### 差异 6: 异常子类数量

| | 报告声明 | 实际 | 修正 |
|--|---------|------|------|
| | "~40+ 子类" | **37 个子类** | 修正为 ~37 |

**依据:** `grep -c "class.*Error\|class.*Exception" src/uniquant/shared/exceptions.py` 返回 37。

---

#### 差异 7: constants.md 覆盖度

| | 报告暗示 | 实际 | 说明 |
|--|---------|------|------|
| | constants.md 与源码完全一致 | 文档覆盖 20/30 个常量类 | 文档准确但不完整 |

**依据:** 源码中定义了 30 个常量类，文档列出了 20 个。缺失: `WindowConfig`, `ToolConstants`, `DataServiceConstants`, `NTFConstants`, `LPPLConstants`, `RegimeConstants`, `UATConstants`, `ResultsConstants`, `BacktestConstants`, `MarketHours`。

**结论:** 文档对其所覆盖的内容是准确的（可信），但不完整。

---

## 核实后修正清单

| # | 文件 | 位置 | 原文 | 修正为 |
|---|------|------|------|--------|
| 1 | EVALUATION_REPORT.md | §1.2 大盘对比表 | 44 文件, ~15K LOC | 44 文件, **~12.6K LOC** |
| 2 | EVALUATION_REPORT.md | §1.3 百分比表 services/ | 10/24 (42%) | **11/24 (46%)** |
| 3 | EVALUATION_REPORT.md | §二 2.4 标题 | 10 个文件 (42%) | **11 个文件 (46%)** |
| 4 | EVALUATION_REPORT.md | §五 阻塞表 #1 | `import uniquant` 崩溃 | **`import uniquant.services` 崩溃** |
| 5 | EVALUATION_REPORT.md | §七 风险矩阵 | ~40+ 子类 | **~37 子类** |
| 6 | EVALUATION_REPORT.md | 附录 A.1 标题 | 43 文件 | **44 文件** |
| 7 | EVALUATION_REPORT.md | 测试状态 | 12 个测试类 | **10 个测试类** |
| 8 | STATUS.md | 测试数描述 | 仅 1 个可运行 | **仅 1 个可运行** (已正确) |
| 9 | README.md | 测试行 | 10 文件 | **10 文件** (已正确) |

---

## 各核实 Agent 独立结论

### Agent 1: 文件计数核实

**核实范围:** 逐包 glob 计数 + 幽灵导入验证

| 声明 | 结论 |
|------|------|
| shared/ 23 文件 | ✅ 确认 |
| services/ 10 文件 | ❌ **实际 11** (漏计 analysis/__init__.py) |
| brain/ 5 文件 | ✅ 确认 |
| ui/ 2 文件 | ✅ 确认 |
| risk/ 1 文件 | ✅ 确认 |
| hands/ 1 文件 | ✅ 确认 |
| data/ 0 文件 | ✅ 确认 |
| signal/ 0 文件 | ✅ 确认 |
| 总计 43 文件 | ✅ 确认 (实际 44，含顶层 __init__.py) |
| tests/ 10 测试文件 | ⚠️ 11 .py 文件; 10 个测试文件 (排除 conftest.py) |
| services/__init__.py 8 个幽灵导入 | ✅ 确认 |
| brain/lppl/__init__.py 7 个幽灵导入 | ✅ 确认 (9 个导入目标, 7 个不存在) |
| services/analysis/__init__.py signal_service + wyckoff 缺失 | ✅ 确认 |

### Agent 2: 文档可信度核实

**核实范围:** 逐文档交叉验证

| 声明 | 结论 |
|------|------|
| 10 个文档不可信 | ✅ 确认 — 全部引用不存在模块 |
| 4 个文档完全可信 | ✅ 确认 — reference/ 3 文件 + packages/shared.md |
| 9 个文档部分可信 | ✅ 确认 |
| data.md 描述 8 子包但 0 文件存在 | ✅ 确认 |
| hands.md 描述 19+ 文件但仅空壳 | ✅ 确认 |
| signal.md 描述 6 文件但 0 存在 | ✅ 确认 |
| quickstart.md 引用 DataFetcher/BacktestEngine | ✅ 确认 — 两者均不存在 |
| constants.md 准确但不完整 | ✅ 确认 — 覆盖 20/30 类 |
| exceptions.md 层次精确匹配 | ✅ 确认 |

### Agent 3: 依赖与代码核实

**核实范围:** pyproject.toml, 行数计数, TDX 项目

| 声明 | 结论 |
|------|------|
| mootdx 声明但未使用 | ✅ 确认 |
| 缺少 pybreaker/tenacity | ✅ 确认 |
| 44 文件 ~15K LOC | ⚠️ 44 文件确认; LOC **实际 12,616** (~12.6K) |
| analysis_service.py = 1650 行 | ✅ 确认 |
| constants.py = 1139 行 | ✅ 确认 |
| dashboard.py = 1518 行 | ✅ 确认 |
| TDX 项目存在 (145 文件) | ✅ 确认 |
| 项目根目录无 pyproject.toml | ✅ 确认 — 仅在 docs/ 中存在 |

### Agent 4: 测试与导入链核实

**核实范围:** 逐文件导入验证, 测试计数

| 声明 | 结论 |
|------|------|
| tests/ 10 个测试文件 | ✅ 确认 (排除 conftest.py) |
| 仅 test_engine_factory 可导入 | ✅ 确认 — 它使用 unittest.mock 全量模拟 |
| 9/10 测试文件导入失败 | ✅ 确认 |
| `import uniquant` 崩溃 | ⚠️ 不精确 — `import uniquant` 成功; `import uniquant.services` 崩溃 |
| 65 个测试函数 | ✅ 确认 |
| 12 个测试类 | ❌ **实际 10 个** |
| brain/fsm/fsm.py indicators 导入失败 | ✅ 确认 |
| hands/__init__.py 懒加载 3 个不存在模块 | ✅ 确认 |

---

## 修正后的最终数据

| 指标 | 修正前 | 修正后 | 依据 |
|------|--------|--------|------|
| 源码文件总数 | 43/44 | **44** | glob 实际计数 |
| 源码总行数 | ~15K | **~12.6K** | wc -l 实际计数 |
| services/ 文件数 | 10 (42%) | **11 (46%)** | glob 含 analysis/__init__.py |
| 测试类数 | 12 | **10** | grep class Test |
| 异常子类数 | ~40+ | **~37** | grep 计数 |
| import 崩溃描述 | "import uniquant 崩溃" | "**import uniquant.services 崩溃**" | 实际测试 |
| 测试文件数 | 10 | **10** (11 含 conftest.py) | glob + 排除 conftest |

---

*核实报告版本: v1.0 | 核实日期: 2026-05-26 | 4 个独立 Agent 并行核实*
