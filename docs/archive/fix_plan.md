# UniQuant 系统修复计划

> 基于 5 路并行 Agent 全面审计结果制定的修复方案
> 审计范围：276 文件，~60K 行代码
> 编制日期：2026-05-24

---

## 目录

1. [修复优先级](#1-修复优先级)
2. [第一阶段：致命错误修复（CRITICAL）](#2-第一阶段致命错误修复critical)
3. [第二阶段：高优先级修复（HIGH）](#3-第二阶段高优先级修复high)
4. [第三阶段：中优先级修复（MEDIUM）](#4-第三阶段中优先级修复medium)
5. [第四阶段：低优先级修复（LOW）](#5-第四阶段低优先级修复low)
6. [修复方案详述](#6-修复方案详述)
7. [验证标准](#7-验证标准)
8. [附录：文件变更清单](#8-附录文件变更清单)

---

## 1. 修复优先级

| 优先级 | 数量 | 说明 |
|--------|------|------|
| 🚨 CRITICAL | 1 | 运行时必定崩溃，必须立即修复 |
| 🔴 HIGH | 4 | 功能缺失或错误行为，影响主要分析流程 |
| 🟡 MEDIUM | 9 | 代码质量、可维护性问题 |
| 🟢 LOW | 9 | 清理、优化、风格问题 |

---

## 2. 第一阶段：致命错误修复（CRITICAL）

### CRIT-1: EngineFactory 构造函数参数错配

**现象：** `engine_factory.py:24` 的 `_lazy_init` 传递 `data_service`，但所有 6 个 `services/analysis/*_engine.py` 的构造函数期望 `orchestrator`。首次访问任何引擎属性立刻 `TypeError`。

**根因分析：** 设计上 `AnalysisEngineFactory` 应作为 `AnalysisService` 的子工厂，引擎需要访问 `AnalysisService` 的方法（缓存、报告等），因此需要 `orchestrator` 引用而非 `data_service`。但工厂设计时采用了通用的 `data_service` 注入模式。

**修复方式（方案 A — 推荐）：**

重构 `_lazy_init` 为接受 `orchestrator` 参数，引擎工厂由 `AnalysisService` 在初始化时传入自身引用：

```
AnalysisService.__init__
  → 创建 AnalysisEngineFactory(orchestrator=self)  // 传入自身
  → factory._lazy_init 使用 orchestrator 而非 data_service
```

涉及文件：

| 文件 | 修改内容 |
|------|----------|
| `services/analysis/engine_factory.py` | `_lazy_init` 改为传递 `orchestrator` 而非 `data_service`；`__init__` 接受 `orchestrator`；移除 `data_service` 参数 |
| `services/analysis_service.py` | 第 83 行 `AnalysisEngineFactory(data_service=data_service)` → `AnalysisEngineFactory(orchestrator=self)` |
| 所有 6 个 `services/analysis/*_engine.py` | 构造函数保留 `orchestrator` 签名不变（已经正确） |

**风险：** `DecisionBrain`（通过 `factory.brain` 访问）当前接受 `data_service=None`，需确保不受影响——`DecisionBrain` 在 `fsm.py:190` 接受 `**kwargs` 或检查其构造函数实现。

---

## 3. 第二阶段：高优先级修复（HIGH）

### HIGH-1: 消除双引擎层级

**现象：** `_run_engine_analysis()` 直接 inline import 脑层引擎，绕过服务层引擎，导致 `services/analysis/` 下 7 个引擎文件成为无效代码。

**修复方式：**

将 `_run_*_detection` 方法从直接 import brain 模块改为通过 `self.*_engine`（服务层引擎）调用。

| 方法 | 当前（脑层引擎） | 改为（服务层引擎） |
|------|-----------------|-------------------|
| `_run_lppl_detection` | `from ..brain.lppl.engine import LPPLEngine` / 直接 new | `self.lppl_engine.run_lppl_analysis(...)` |
| `_run_czsc_detection` | `from ..brain.czsc_engine import CZSCEngine` | `self.czsc_engine.run_czsc_analysis(...)` |
| `_run_regime_detection` | `from ..brain.regime_detector import RegimeDetector` | `self.regime_engine.run_regime_analysis(...)` |
| `_run_ntf_detection` | `from ..brain.ntf_engine import NTFEngine` | `self.ntf_engine.run_ntf_analysis(...)` |

**前置依赖：** 必须先修复 CRIT-1（EngineFactory 参数错配），否则 `self.lppl_engine` 等属性会崩溃。

**额外调整：** 各服务层引擎的 `run_*_analysis()` 方法签名需与 `_run_*_detection` 的调用方式匹配，可能需要小幅调整方法参数（数据传递方式）。

---

### HIGH-2: Wyckoff 分析引擎接入

**现象：** WyckoffAnalysisEngine 已编写（`services/analysis/wyckoff_analysis_engine.py`），WyckoffEngine（`brain/wyckoff/engine.py`）功能完整，但两者均未接入分析流程。

**修复步骤：**

| 步骤 | 文件 | 修改 |
|------|------|------|
| 1 | `engine_factory.py` | 添加 `@property def wyckoff(self)` → 延迟初始化 `WyckoffAnalysisEngine` |
| 2 | `analysis_service.py` | 添加 `@property def wyckoff_engine(self)` → 代理到 `self._factory.wyckoff` |
| 3 | `analysis_service.py` | 添加 `_run_wyckoff_detection()` 方法 |
| 4 | `analysis_service.py:790` | 在 `_run_engine_analysis()` 中添加调用 `self._run_wyckoff_detection(ticker, data_pack)` |
| 5 | `analysis_service.py:1420` | 在 `run_comprehensive_analysis()` 中添加 Wyckoff 分析 |
| 6 | `wyckoff_analysis_engine.py` | 验证构造函数签名兼容性（当前用 `orchestrator`，CRIT-1 修复后应匹配） |

---

### HIGH-3: 修复 `hands/__init__.py` 导入路径

**现象：** `__getattr__` 中使用 `from src.hands.strategies import ...`，但正确路径应为 `uniquant.hands.strategies`。

**修复：**

```python
# 第 13 行
from src.hands.strategies import ...
# 改为
from uniquant.hands.strategies import ...
```

---

### HIGH-4: LPPL 引擎 logger 统一

**现象：** `brain/lppl/engine.py` 第 29 行和第 916 行存在两个不同的 logger 赋值。

**修复：**

```python
# 删除第 29 行的 stdlib logger
# line 29: logger = logging.getLogger(__name__)  ← 删除

# 合并 import（第 12-13 行）
import logging  # 如果其他地方仍需要，保留
from ...shared.logger_factory import get_logger  # 移到文件顶部

# 在第 28-30 行统一设置
from ...shared.logger_factory import get_logger
logger = get_logger(__name__)
# 删除第 914-916 行的重复导入和赋值
```

---

## 4. 第三阶段：中优先级修复（MEDIUM）

### MED-1：删除死代码

| 文件 | 行号 | 操作 |
|------|-------|------|
| `czsc/czsc_engine.py` | 205-206 | 删除第一组重复的 `signals = getattr(...)` / `bi_list = getattr(...)` |
| `lppl/engine.py` | 266-267 | 删除第一组 `best_cost = np.inf; best_params = None` |

---

### MED-2：废弃 shim 文件消除

**现象：** `brain/czsc_engine.py`、`brain/ntf_engine.py`、`brain/regime_detector.py` 三个 7 行的废弃重导出 shim，import 时触发 `DeprecationWarning`。

**修复方式：**

```python
# 方案：直接删除 shim 文件，更新 analysis_service.py 中的 import

# analysis_service.py 中：
from ..brain.regime_detector import RegimeDetector   # shim
# 改为：
from ..brain.regime.regime_detector import RegimeDetector

from ..brain.czsc_engine import CZSCEngine           # shim  
# 改为：
from ..brain.czsc.czsc_engine import CZSCEngine

from ..brain.ntf_engine import NTFEngine              # shim
# 改为：
from ..brain.ntf.ntf_engine import NTFEngine
```

**注意：** HIGH-1 修复后这些 inline import 本应被删除（通过服务层引擎调用），因此此修复可能成为 HIGH-1 的副产品。如果 HIGH-1 完成，删除 shim 文件即可。

---

### MED-3：补充缺失导出

| 文件 | 补充内容 |
|------|----------|
| `services/__init__.py` | 在 `__all__` 中添加 `AnalysisService`、`DataAccessService`、`ServiceContainer` |
| `brain/lppl/__init__.py` | 在 `__all__` 中添加 `LPPLEngine` |
| `brain/__init__.py` | 在导出中添加 `DecisionBrain` |

---

### MED-4：`numba_optimizer.py` 添加 import guard

```python
# brain/lppl/numba_optimizer.py 开头
try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
```

所有使用 `@njit` 装饰器的函数改为条件编译：

```python
if HAS_NUMBA:
    @njit
    def _reduced_cost_numba(...): ...
else:
    def _reduced_cost_numba(...): ...
    # raise NotImplementedError("Numba is required for JIT-accelerated optimizer")
```

---

### MED-5：`ServiceContainer` 删除孤立 import

```python
# service_container.py:60
from .data_access_service import DataAccessService  # ← 删除
```

---

### MED-6：修复文档字符串

```python
# analysis/__init__.py:9
"""...协调器..."""  
# 改为：
"""...模块..."""  
# 或者创建 analysis_coordinator.py
```

---

### MED-7：脑层引擎统一接口（可选）

**建议：** 为所有脑层引擎定义一个 `AnalysisProtocol`（`shared/interfaces.py` 中已存在 `AnalysisEngineProtocol`），逐步让各引擎实现统一接口。这是较大重构，可分阶段进行。

---

### MED-8：LPPL 异常改为非静默模式

```python
# analysis_service.py:838-844
def _run_lppl_detection(self, data_pack: Dict[str, Any]) -> None:
    try:
        result = self.lppl_eengine.detect_bubble(data_pack["stock"])
        ...
    except RECOVERABLE_ERRORS as e:
        logger.warning(f"LPPLEngine 分析失败: {e}")
        # 改为记录更详细的日志，包括 traceback
        logger.exception(f"LPPLEngine 分析详情: ")
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0
```

---

## 5. 第四阶段：低优先级修复（LOW）

| # | 问题 | 修复方式 |
|---|------|----------|
| OW-1 | Wyckoff 策略重复 | 删除 `hands/strategies/wyckoff.py` 或 `wyckoff_strategy.py`，合并功能 |
| OW-2 | `data/services/__init__.py` 空文件 | 添加 `# Data services sub-package` 注释或删除 |
| OW-3 | `data/__init__.py` 遗留 stub | 删除 `DataLake`/`DataPipeline` 的 `__getattr__` 处理 |
| OW-4 | 超大文件拆分 | `analysis_service.py` 拆分出 mixin；`lppl/engine.py` 拆分；`constants.py` 拆分 |
| OW-5 | `ScanService` 缺 DI | 改为通过构造函数注入依赖 |
| OW-6 | `AlphaDecoupler` 内部函数重复 | 提取 `_calc_aligned_slope` 为独立方法，消除与 `calc_rs_slope` 的重复 |
| OW-7 | 过薄测试增强 | 为 `test_offline_entry.py`、`test_verify_tdx_inport.py` 等添加实质性断言 |
| OW-8 | `os` import 顺序 | 将 `import os` 移到 `engine.py` 文件顶部 |
| OW-9 | `ReportGeneratorEngine` 循环引用 | 使用弱引用（`weakref`）持有 `orchestrator` |

---

## 6. 修复方案详述

### 6.1 CRIT-1 详细实现

```python
# engine_factory.py — 修改后

class AnalysisEngineFactory:
    def __init__(self, orchestrator):
        self._orchestrator = orchestrator
        # 如果外部代码仍需 data_service，可以通过 orchestrator.data_service 访问
        self._engines: Dict[str, Any] = {}

    def _lazy_init(self, name: str, module_path: str, class_name: str, **kwargs) -> Any:
        if name not in self._engines:
            import importlib
            try:
                mod = importlib.import_module(module_path, package=__package__)
                cls = getattr(mod, class_name)
                # 传递 orchestrator 而不是 data_service
                self._engines[name] = cls(orchestrator=self._orchestrator, **kwargs)
                logger.debug(f"Lazy-initialized {name}")
            except Exception as e:
                logger.warning(f"Failed to init {name}: {e}")
                return None
        return self._engines[name]

    @property
    def fsm(self):
        return self._lazy_init("fsm", "...analysis.fsm_analysis_engine", "FsmAnalysisEngine")

    # ... 其余 @property 定义不变 ...
```

```python
# analysis_service.py — 构造函数修改

def __init__(self, data_service, engine_factory=None, ...):
    self.data_service = data_service
    ...
    if engine_factory is None:
        from .analysis.engine_factory import AnalysisEngineFactory
        # 传入 self（orchestrator）而非 data_service
        engine_factory = AnalysisEngineFactory(orchestrator=self)
    self._factory = engine_factory

    self._initialize_cache()
    self._initialize_validation_service()
```

### 6.2 HIGH-1 详细实现

以 `_ru_lppl_detection` 为例：

```python
def _ru_lppl_detection(self, data_pack: Dict[str, Any]) -> None:
    """运行 LPPLEngine 分析（通过服务层引擎）"""
    try:
        result = self.lppl_engine.run_lppl_analysis(
            symbol=data_pack.get("symbol", "unknown"),
            df=data_pack.get("stock")
        )
        data_pack["risk"] = result.get("risk", "Safe")
        data_pack["bubble_confidence"] = result.get("confidence", 0.0)    except RECOVERABLE_ERRORS as e:
        logger.warning(f"LPPLEngine 分析失败: {e}")
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0```

### 6.3 修复依赖关系图

```
CRIT-1 (EngineFactory 参数错配)
  │
  ├─→ HIGH-1 (消除双引擎层级) — 前置依赖：CRIT-1
  │     │
  │     └─→ MED-2 (删除 shim 文件) — 副产品：HIGH-1 完成后 shim 不再被引用
  │
  ├─→ HIGH-2 (Wyckoff 接入) — 前置依赖：CRIT-1
  │
  └─→ MED-7 (统一引擎接口) — 建议在 HIGH-1 之后进行
```

---

## 7. 验证标准

每个修复完成后需通过以下验证：

### 7.1 自动化测试

```bash
# 全量回归测试
PYTHONPATH=. pytest tests/ -v --tb=short 2>&1 | tail -30

# 覆盖新增路径的专项测试
PYTHONPATH=. pytest tests/test_analysis_engines.py -v
PYTHONPATH=. pytest tests/test_engine_factory.py -v
PYTHONPATH=. pytest tests/test_lppl_calculator_defense.py -v
```

### 7.2 手动验证清单

| 检查项 | 验证方法 |
|--------|----------|
| EngineFactory 所有 9 个属性可访问 | `factory.fsm; factory.czsc; factory.lppl; factory.regime; factory.ntf; factory.macro; factory.report; factory.brain; factory.wyckoff` |
| `analysis_service.lppl_engine` 工作 | 返回 `LpplAnalysisEngine` 实例，不抛 `TypeError` |
| `analyze_ticker` 不崩溃 | 使用模拟数据调用 `analysis_service.analyze_ticker("000001")` |
| Wyckoff 在决策结果中出现 | 检查保存的 JSON 结果文件包含 wyckoff 字段 |
| `hands/__init__` 导入正常 | `from uniquant.hands import ...` 不抛 `ModuleNotFoundError` |
| 无 DeprecationWarning | `python -W all -c "from uniquant import *"` 无 deprecated shim 警告 |

### 7.3 回归风险控制

- CRIT-1 只修改 `engine_factory.py` 和 `analysis_service.py` 的构造函数，不影响其他代码路径
- 每次修改后运行全量测试套件（69 个文件），确保 35+ 回归用例绿
- Wyckoff 当前无调用点，接入后不破坏现有逻辑

---

## 8. 附录：文件变更清单

### 必须修改（按阶段顺序）

| 阶段 | 文件 | 变更类型 | 说明 |
|------|------|----------|------|
| P1 | `services/analysis/engine_factory.py` | 重构 | `__init__` 接受 `orchestrator`，`_azy_init` 传递 `orchestrator` |
| P1 | `services/analysis_service.py` | 修改 | 构造函数传 `orchestrator=self` |
| P2-H1 | `services/analysis_service.py` | 重构 | 4 个 `_ru_*` 方法改为通过服务层引擎调用 |
| P2-H2 | `services/analysis/engine_factory.py` | 新增 | 添加 `@property def wyckoff` |
| P2-H2 | `services/analysis_service.py` | 新增 | 添加 `wyckoff_engine` 属性和 `_ru_wyckoff_detection` |
| P2-H2 | `services/analysis_service.py` | 修改 | `_ru_engine_analysis()` 和 `ru_comprehensive_analysis()` 添加 Wyckoff |
| P2-H3 | `hands/__init__.py` | 修复 | `src.hands` → `uniquant.hands` |
| P2-H4 | `brain/lppl/engine.py` | 重构 | 合并两个 logger，删除第 29 行，移动 import 到顶部 |
| P3-M1 | `brain/czsc/czsc_engine.py` | 清理 | 删除重复的 205-206 行 |
| P3-M1 | `brain/lppl/engine.py` | 清理 | 删除重复的 266-267 行 |
| P3-M2 | 3 个 shim 文件 | 删除 | 如果 HIGH-1 完成后不再被引用 |
| P3-M3 | 3 个 `__init__.py` | 修改 | 补充缺失导出 |
| P3-M4 | `brain/lppl/numba_optimizer.py` | 修改 | 添加 `try/except ImportError` guard |
| P3-M5 | `services/service_container.py` | 清理 | 删除孤立 import |
| P3-M6 | `services/analysis/__init__.py` | 修复 | 更新文档字符串或创建缺失模块 |
| P3-M8 | `services/analysis_service.py` | 修改 | LPPL 异常添加 `logger.exception` 输出 stack trace |

### 可选修复（第四阶段）

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `hands/strategies/wyckoff.py` 或 `wyckoff_strategy.py` | 删除 | 合并两套 Wyckoff 策略 |
| `data/services/__init__.py` | 修改 | 添加内容或删除 |
| `data/__init__.py` | 清理 | 删除 `DataLake`/`DataPipeline` stub |
| `services/scan_service.py` | 重构 | 改为构造函数注入依赖 |
| `brain/alpha_decoupler.py` | 重构 | 消除 `_calc_aligned_slope` 与 `calc_rs_slope` 重复 |
| `brain/lppl/engine.py` | 修复 | 将 `import os` 移到文件顶部 |
| `services/analysis_service.py` | 修复 | `ReportGeneratorEngine` 改为弱引用 |

### 建议拆分的大文件

| 文件 | 建议拆分方式 |
|------|-------------|
| `services/analysis_service.py` (1627行) | 将 `_run_*` 方法组提取为 `TechnicalAnalysisMixin`、`SignalAnalysisMixin` |
| `brain/lppl/engine.py` (1003 行) | 将 `LPPLEngine` 类提取到独立文件；将工具函数移到 `utils.py` |
| `shared/constants.py` (1139 行) | 按领域拆分：`brain_constants.py`、`data_constants.py`、`risk_constants.py` |
| `brain/wyckoff/engine.py` (1356 行) | 将步骤方法提取到 `steps.py`、`analysis.py` |

---

> **说明：** 本修复计划遵循 **CRIT-1 → HIG-H1 → HIG-H2 → MEdIUM → OW** 的依赖顺序。CRIT-1 是所有引擎接入的阻塞依赖，必须最先修复。HIG-H1 和 HIG-H2 可以并行修复（都依赖 CRIT-1 但不互相依赖）。