# 导入链修复

## 何时使用
遇到 `ImportError`、`ModuleNotFoundError` 时；执行 Phase 0 修复时；新增模块需要导出时。

---

## 已知幽灵导入清单

### services/__init__.py (行 4-11)

```python
# 行 4-11：8 个幽灵导入
from .cache_coordinator import CacheCoordinator        # ❌ 不存在
from .data_quality_service import DataQualityService    # ❌ 不存在
from .data_service import DataService                   # ❌ 不存在
from .health_service import HealthService               # ❌ 不存在
from .portfolio_service import PortfolioService         # ❌ 不存在
from .scan_service import ScanPipeline                  # ❌ 不存在
from .stock_query_service import StockQueryService      # ❌ 不存在
from .validation_service import ValidationService       # ❌ 不存在
```

**状态**：8/8 目标文件不存在。`__all__` 中额外声明的 `AnalysisService`、`DataAccessService`、`ServiceContainer` 也无对应导入。

---

### services/analysis/__init__.py (行 11-14)

```python
# 行 11-14：4 个导入
from .macro_service import MacroAnalysisService         # ✅ 存在
from .technical_service import TechnicalAnalysisService # ✅ 存在
from .signal_service import SignalAnalysisService       # ❌ 不存在
from .wyckoff_analysis_engine import WyckoffAnalysisEngine # ❌ 不存在
```

**状态**：2/4 目标文件存在。`signal_service.py` 和 `wyckoff_analysis_engine.py` 缺失。

**实际存在的文件**（未被导入）：
- `ntf_analysis_engine.py`
- `regime_analysis_engine.py`
- `czsc_analysis_engine.py`
- `report_generator_engine.py`
- `engine_factory.py`

---

### brain/lppl/__init__.py (行 1-9)

```python
# 行 1-9：9 个导入
from ...brain.lppl.calculator import LPPLCalculator            # ❌ 不存在
from ...brain.lppl.core import lppl_func, detect_negative_bubble # ❌ 不存在
from ...brain.lppl.engine import LPPLConfig, LPPLEngine         # ✅ 存在
from ...brain.lppl.multifit import fit_multi_window, calculate_multifit_score # ❌ 不存在
from ...brain.lppl.cluster import SignalClusterDetector         # ❌ 不存在
from ...brain.lppl.regime import MarketRegimeDetector           # ❌ 不存在
from ...brain.lppl.computation import LPPLComputation           # ❌ 不存在
from ...brain.lppl.data_manager import LPPLDataManager          # ❌ 不存在
from ...brain.lppl.visualizer import LPPLVisualizer             # ❌ 不存在
```

**状态**：1/9 目标文件存在。仅 `engine.py` 存在。

**实际存在的文件**：
- `engine.py` ✅
- `numba_optimizer.py`（未被导入）

---

### hands/__init__.py (__getattr__ 模式)

```python
# 行 19-32：3 个懒加载目标
def __getattr__(name):
    if name == "Reporter":
        from uniquant.hands.reporter import Reporter      # ❌ 不存在
        return Reporter
    elif name == "ResultsManager":
        from uniquant.hands.results_manager import ResultsManager # ❌ 不存在
        return ResultsManager
    elif name == "strategies":
        import uniquant.hands.strategies                  # ❌ 不存在
        return uniquant.hands.strategies
```

**状态**：3/3 目标文件不存在。`hands/` 目录下仅有 `__init__.py`。

---

### brain/fsm/fsm.py indicators 导入

```python
# 行 19
from ..indicators import Indicators
```

**问题**：使用相对导入 `..indicators`，期望 `brain/indicators.py` 或 `brain/indicators/__init__.py` 存在，但两者均不存在。

**影响**：`fsm.py` 是 FSM（有限状态机）核心模块，导入失败将阻断整个信号分析链。

---

### ui/dashboard.py components 导入

```python
# 行 38-64
from uniquant.ui.components import (
    render_report_html_preview,
    render_report_comparison,
    render_report_comparison_selector,
    render_report_library_actions,
    render_report_metadata,
    render_portfolio_risk_metrics,
    render_portfolio_optimizer_result,
    render_stress_test_results,
    render_risk_heatmap,
    render_scan_config_panel,
    render_stock_rankings,
    render_structural_risk_gauges,
    render_tech_signals_summary,
    render_czsc_analysis_panel,
    render_czsc_buy_sell_points,
    render_czsc_zhongshu_analysis,
    render_fsm_state_history,
    render_fsm_status_panel,
    render_health_metrics,
    render_ic_ir_heatmap,
    plot_czsc_full_chart,
    render_anti_fragile_metrics,
    render_stress_scenario_buttons,
    render_stress_scenario_results,
    render_drawdown_dashboard,
)
```

**问题**：导入 26 个组件函数，但 `ui/components.py` 和 `ui/components/__init__.py` 均不存在。

---

## Phase 0 修复清单

### 步骤 1：修复 services/__init__.py

**问题**：8 个导入指向不存在的文件，`__all__` 声明了未导入的符号。

**方案 A**（推荐）：注释掉所有幽灵导入，保留空 `__all__`。

```python
"""
服务层模块
"""

__all__ = [
    # 待实现：以下模块尚未创建
    # "CacheCoordinator",
    # "DataQualityService",
    # "DataService",
    # "HealthService",
    # "PortfolioService",
    # "ScanPipeline",
    # "StockQueryService",
    # "ValidationService",
]
```

**方案 B**：创建桩文件。对每个缺失模块创建最小实现。

**验证命令**：
```bash
python -c "import uniquant.services"
```

---

### 步骤 2：修复 brain/lppl/__init__.py

**问题**：9 个导入中 8 个目标不存在。

**方案**：仅保留 `engine.py` 导入。

```python
from uniquant.brain.lppl.engine import LPPLConfig, LPPLEngine

__all__ = [
    "LPPLConfig",
    "LPPLEngine",
]
```

**验证命令**：
```bash
python -c "import uniquant.brain.lppl"
```

---

### 步骤 3：修复 services/analysis/__init__.py

**问题**：`signal_service.py` 和 `wyckoff_analysis_engine.py` 不存在。

**方案**：仅导入存在的模块。

```python
"""
Analysis Services Package
"""

from .macro_service import MacroAnalysisService
from .technical_service import TechnicalAnalysisService

__all__ = [
    "MacroAnalysisService",
    "TechnicalAnalysisService",
]
```

**验证命令**：
```bash
python -c "import uniquant.services.analysis"
```

---

### 步骤 4：修复 brain/fsm/fsm.py indicators 导入

**问题**：`from ..indicators import Indicators` 目标不存在。

**方案 A**（临时）：注释导入，在使用处添加防御。

```python
# 行 19：注释掉
# from ..indicators import Indicators

# 在使用 Indicators 的地方添加：
Indicators = None  # TODO: 实现 brain/indicators.py
```

**方案 B**（长期）：创建 `brain/indicators.py`，实现 `Indicators` 类。

**验证命令**：
```bash
python -c "from uniquant.brain.fsm.fsm import FSMState"
```

---

### 步骤 5：验证完整导入链

```bash
# 核心模块导入测试
python -c "import uniquant; import uniquant.shared"

# 子模块测试
python -c "import uniquant.services"
python -c "import uniquant.services.analysis"
python -c "import uniquant.brain.lppl"
python -c "import uniquant.hands"

# 幽灵导入检测（应无输出）
python -c "
import ast, sys
for mod in ['uniquant.services', 'uniquant.brain.lppl']:
    try:
        __import__(mod)
    except ImportError as e:
        print(f'FAIL: {mod} -> {e}')
        sys.exit(1)
print('OK')
"
```

---

## 新增模块规范

### 正确的 __init__.py 导出模式

```python
# src/uniquant/example/__init__.py

# 1. 显式导入
from .module_a import ClassA
from .module_b import function_b

# 2. 声明 __all__
__all__ = [
    "ClassA",
    "function_b",
]

# 3. 可选：版本信息
__version__ = "0.1.0"
```

### 禁止的做法

```python
# ❌ 禁止：通配符导入
from .module_a import *

# ❌ 禁止：导入不存在的模块
from .nonexistent import Something

# ❌ 禁止：__all__ 声明未导入的符号
__all__ = ["UndeclaredSymbol"]
```

### 验证清单

新增模块后执行：
```bash
# 1. 检查导入
python -c "import uniquant.new_module"

# 2. 检查 __all__ 一致性
python -c "
import uniquant.new_module as m
declared = set(getattr(m, '__all__', []))
imported = set(k for k in dir(m) if not k.startswith('_'))
missing = declared - imported
if missing:
    print(f'__all__ 声明但未导入: {missing}')
"
```

---

## 懒加载模式

### hands/__init__.py 的 __getattr__ 模式

**适用场景**：
- 循环依赖无法通过重组解决
- 模块导入成本高（如含大量计算）
- 可选依赖（可能未安装）

**实现模板**：

```python
__all__ = ["HeavyClass", "optional_module"]


def __getattr__(name: str):
    """延迟导入，避免循环依赖和启动开销"""
    if name == "HeavyClass":
        from .heavy_module import HeavyClass
        return HeavyClass
    elif name == "optional_module":
        from . import optional_module
        return optional_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**注意事项**：
- `__getattr__` 仅在模块级别属性访问时触发
- 必须 `raise AttributeError` 作为兜底
- IDE 类型提示需要配合 `TYPE_CHECKING`：

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .heavy_module import HeavyClass
```
