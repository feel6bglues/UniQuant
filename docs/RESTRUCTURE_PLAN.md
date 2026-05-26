# UniQuant 全系统重构策略 — 细分模块方案

**版本:** v3.1 | **日期:** 2026-05-25 | **状态:** 待执行
**审查状态:** 架构审查完成 (2026-05-25) — 6 项修正已合并

---

## 总览

```
TDX (完整源, 145文件, 68测试) → UniQuant (44源文件, 7测试)
重构 = TDX迁移(~90%) + mootdx数据层重写(~10%)
未迁移: 111个源文件 + 57个测试文件
```

### 执行顺序 (支持并行)

```
Phase 0 (串行, 必须先完成)
  ↓
Phase 1A ─┬→ Phase 1C → Phase 1F    (路径A: services → UI)
          │
          └→ Phase 1D                (路径C: brain LPPL+Factor, 与A并行)
          │
Phase 1B ─┬→ Phase 1E               (路径B: data → hands回测)
          │
Phase 2 (mootdx适配, 依赖1B)
  ↓
Phase 3 (验证+修复, 依赖全部)
  ↓
Phase 4 (清理)
```

---

# Phase 0: 紧急修复 (导入链恢复)

**目标:** 让 `import uniquant` 的所有子包可正常导入
**预计:** 30 分钟
**依赖:** 无
**验证:** `python -c "import uniquant; import uniquant.shared; import uniquant.brain.fsm"`

---

## 0.1 修复 `services/__init__.py`

**文件:** `src/uniquant/services/__init__.py`
**操作:** 改写

当前问题: 导入了 8 个不存在的模块 (cache_coordinator, data_quality_service, data_service, health_service, portfolio_service, scan_service, stock_query_service, validation_service)

```python
# 改写为:
from .analysis_service import AnalysisService
from .service_container import ServiceContainer

__all__ = ["AnalysisService", "ServiceContainer"]
```

**提交:** `fix(services): remove phantom imports from __init__.py to restore importability`

---

## 0.2 修复 `brain/lppl/__init__.py`

**文件:** `src/uniquant/brain/lppl/__init__.py`
**操作:** 改写

当前问题: 导入 7 个不存在的子模块 (calculator, core, multifit, cluster, regime, computation, data_manager, visualizer)

```python
# 改写为:
from .engine import LPPLConfig, LPPLEngine
from .numba_optimizer import NumbaOptimizer

__all__ = ["LPPLConfig", "LPPLEngine", "NumbaOptimizer"]
```

**提交:** `fix(brain/lppl): remove phantom submodule imports, keep only engine and numba_optimizer`

---

## 0.3 修复 `services/analysis/__init__.py`

**文件:** `src/uniquant/services/analysis/__init__.py`
**操作:** 改写

当前问题: 导入 signal_service 和 wyckoff_analysis_engine (均不存在)

```python
# 改写为:
from .macro_service import MacroAnalysisService
from .technical_service import TechnicalAnalysisService
from .engine_factory import AnalysisEngineFactory

__all__ = ["MacroAnalysisService", "TechnicalAnalysisService", "AnalysisEngineFactory"]
```

**提交:** `fix(services/analysis): remove phantom signal_service and wyckoff imports`

---

## 0.4 修复 `ui/dashboard.py` 幽灵导入

**文件:** `src/uniquant/ui/dashboard.py`
**操作:** 修改顶部导入区域 (行 38-67)

将 3 个幽灵模块导入改为 try/except:

```python
try:
    from uniquant.ui.components import (
        render_health_metrics, render_anti_fragile_metrics,
        render_fsm_status_panel, render_fsm_state_history,
        render_structural_risk_gauges, render_scan_config_panel,
        render_stock_rankings, render_tech_signals_summary,
        render_ic_ir_heatmap, render_czsc_analysis_panel,
        render_czsc_zhongshu_analysis, render_czsc_buy_sell_points,
        render_report_html_preview, render_report_comparison,
        render_report_comparison_selector, render_report_metadata,
        render_portfolio_risk_metrics, render_portfolio_optimizer_result,
        render_stress_test_results, render_risk_heatmap,
        render_stress_scenario_buttons, render_stress_scenario_results,
        render_drawdown_dashboard,
    )
except ImportError:
    pass

try:
    from uniquant.ui.lppl_visualizer import LPPLVisualizer
except ImportError:
    LPPLVisualizer = None

try:
    from uniquant.ui.manager_logic import AssetManager
except ImportError:
    AssetManager = None
```

**提交:** `fix(ui): wrap phantom imports in try/except for graceful degradation`

---

## 0.5 创建缺失的 `__init__.py`

| 文件 | 操作 | 内容 |
|------|------|------|
| `brain/czsc/__init__.py` | 新建 | `from .czsc_engine import CZSCEngine` |
| `brain/fsm/__init__.py` | 新建 | `from .fsm import DecisionBrain, FSM` |
| `brain/ntf/__init__.py` | 新建 (空) | 等待 Phase 1 迁移 ntf_engine |
| `brain/regime/__init__.py` | 新建 (空) | 等待 Phase 1 迁移 regime_detector |
| `risk/__init__.py` | 新建 | `from .drawdown_analyzer import DrawdownAnalyzer` |
| `ui/__init__.py` | 新建 (空) | |

**提交:** `fix: create missing __init__.py files for brain/czsc, brain/fsm, risk, ui packages`

---

## 0.6 修复 `brain/fsm/fsm.py` 的 indicators 导入

**文件:** `src/uniquant/brain/fsm/fsm.py`
**操作:** 修改行 19

当前: `from ..indicators import Indicators` (brain/indicators.py 不存在)

临时修复: 改为 try/except，提供 fallback:

```python
try:
    from ..indicators import Indicators
except ImportError:
    class Indicators:
        @staticmethod
        def calc_ma(df, window, column="close"):
            return df[column].rolling(window=window, min_periods=max(int(window * 0.5), 5)).mean()
```

**提交:** `fix(brain/fsm): add fallback Indicators when brain.indicators module not yet migrated`

---

## 0.7 修复 `services/analysis/__init__.py` Wyckoff 幽灵导入

**文件:** `src/uniquant/services/analysis/__init__.py`
**操作:** 删除第 14 行

当前问题: `from .wyckoff_analysis_engine import WyckoffAnalysisEngine` — 模块不存在于 TDX 或 UniQuant

```python
# 删除此行:
from .wyckoff_analysis_engine import WyckoffAnalysisEngine
```

**提交:** `fix(services/analysis): remove phantom WyckoffAnalysisEngine import`

---

# Phase 1A: Shared 基础层迁移

**目标:** 迁移 brain/indicators.py 和 shared 缺失模块
**预计:** 30 分钟
**依赖:** Phase 0
**验证:** `python -c "from uniquant.brain.indicators import Indicators; from uniquant.risk.evt_risk import EVTRisk"`

---

## Import 适配规则 (所有 Phase 共用)

### 自动替换规则

```bash
# 批量替换绝对导入为相对导入
sed -i 's/from src\shared\./from ...shared./g' *.py
sed -i 's/from src\brain\./from ...brain./g' *.py
sed -i 's/from src\data\./from ...data./g' *.py
sed -i 's/from src\hands\./from ...hands./g' *.py
sed -i 's/from src\risk\./from ...risk./g' *.py
sed -i 's/from src\services\./from ...services./g' *.py
sed -i 's/from src\ui\./from ...ui./g' *.py
```

### 需要手动处理的文件 (深度差异)

| 文件 | 原始 | 目标 |
|------|------|------|
| `risk/sizer.py:4-6` | `from src.shared.constants/logger_factory/market_rules` | `from ...shared.constants/...` |
| `brain/factors/custom_factors.py:1` | `from src.brain.factors.registry` | `from .registry` |
| `ui/manager_logic.py:1-10` | `from src.services.*` / `from src.data.*` | `from ...services.*` / `from ...data.*` |
| `hands/strategies/base.py` | `from risk.sizer import PositionSizer` | `from ...risk.sizer import PositionSizer` |
| `hands/strategies/__init__.py` | `from src.hands.strategies.*` | `from .xxx` |
| `hands/__init__.py` | `from src.hands.*` | `from ...hands.*` |

### 层级深度对照

```
uniquant/shared/     →  ..shared.     (从 brain/risk/ui/services 出发)
uniquant/data/       →  ...data.      (从 services/analysis 出发)
uniquant/brain/      →  ...brain.     (从 services/analysis 出发)
uniquant/risk/       →  ...risk.      (从 services/analysis 出发)
```

---

## 1A.1 从 TDX 复制 `brain/indicators.py`

**源:** `/home/james/Documents/Project/TDX/src/brain/indicators.py` (404行)
**目标:** `src/uniquant/brain/indicators.py`
**操作:** 复制 + 适配 import

Import 适配:
```
from ...shared.constants import IndicatorThresholds  →  from ..shared.constants import IndicatorThresholds
from ...shared.cache import smart_cache              →  from ..shared.cache import smart_cache (如有)
from ...shared.exceptions import IndicatorError       →  from ..shared.exceptions import IndicatorError
from ...shared.logger_factory import get_logger       →  from ..shared.logger_factory import get_logger
```

**提交:** `feat(brain): migrate indicators.py from TDX (10 technical indicator methods)`

---

## 1A.2 从 TDX 复制 `brain/alpha_decoupler.py`

**源:** `/home/james/Documents/Project/TDX/src/brain/alpha_decoupler.py` (~350行)
**目标:** `src/uniquant/brain/alpha_decoupler.py`
**操作:** 复制 + import 适配

**提交:** `feat(brain): migrate alpha_decoupler.py from TDX`

---

## 1A.3 从 TDX 复制 `risk/evt_risk.py`

**源:** `/home/james/Documents/Project/TDX/src/risk/evt_risk.py` (391行)
**目标:** `src/uniquant/risk/evt_risk.py`
**操作:** 复制 + import 适配

Import 适配:
```
from ..shared.constants import RiskCalculationConstants
from ..shared.exceptions import RiskCalculationError
from ..shared.logger_factory import get_logger
```

**提交:** `feat(risk): migrate evt_risk.py from TDX (HistoricalSimulationRisk + EVTRisk)`

---

## 1A.4 从 TDX 复制 `risk/sizer.py`

**源:** `/home/james/Documents/Project/TDX/src/risk/sizer.py` (269行)
**目标:** `src/uniquant/risk/sizer.py`
**操作:** 复制 + import 适配

Import 适配:
```
from src.shared.constants → from ...shared.constants
from src.shared.logger_factory → from ...shared.logger_factory
from src.shared.market_rules → from ...shared.market_rules (需先复制)
```

**提交:** `feat(risk): migrate sizer.py from TDX (PositionSizer + PortfolioSizer)`

---

## 1A.5 从 TDX 复制 `shared/market_rules.py`

**源:** `/home/james/Documents/Project/TDX/src/shared/market_rules.py`
**目标:** `src/uniquant/shared/market_rules.py`
**操作:** 复制 + import 适配

**提交:** `feat(shared): migrate market_rules.py from TDX (board type detection)`

---

## 1A.6 从 TDX 复制 `risk/portfolio_optimizer.py`

**源:** `/home/james/Documents/Project/TDX/src/risk/portfolio_optimizer.py` (366行)
**目标:** `src/uniquant/risk/portfolio_optimizer.py`
**操作:** 复制 + import 适配

**已知 Bug:** `generate_report()` 中 `self.weights_.items()` 调用失败 — 在复制时修复:
```python
# 修复: 保存 assets 列表
self._last_assets = symbols
# generate_report() 中:
for asset, weight in zip(self._last_assets, self.weights_):
```

**提交:** `feat(risk): migrate portfolio_optimizer.py from TDX (fix generate_report bug)`

---

## 1A.7 从 TDX 复制 `risk/structural.py`

**源:** `/home/james/Documents/Project/TDX/src/risk/structural.py`
**目标:** `src/uniquant/risk/structural.py`
**操作:** 复制

**提交:** `feat(risk): migrate structural.py from TDX`

---

## 1A.8 从 TDX 复制 brain/ntf 和 brain/regime

| 源 | 目标 | 行数 |
|-----|------|------|
| `brain/ntf_engine.py` | `brain/ntf/ntf_engine.py` | ~200 |
| `brain/regime_detector.py` | `brain/regime/regime_detector.py` | ~250 |

Import 适配: `from src.*` → `from ..*` 或 `from ...*`

**提交:** `feat(brain): migrate ntf_engine and regime_detector from TDX`

---

## 1A.10 从 TDX 复制 4 个 shared 子模块

| 源 | 目标 |
|-----|------|
| `shared/market_constants.py` | `shared/market_constants.py` |
| `shared/network_constants.py` | `shared/network_constants.py` |
| `shared/price_collar.py` | `shared/price_collar.py` |
| `shared/risk_constants.py` | `shared/risk_constants.py` |

**提交:** `feat(shared): migrate market_constants, network_constants, price_collar, risk_constants from TDX`

---

## 1A.9 修复 engine_factory.py DecisionBrain 签名

**文件:** `src/uniquant/services/analysis/engine_factory.py`
**操作:** 修改 `_lazy_init` 方法

问题: `_lazy_init` 传 `orchestrator=self._orchestrator` 给所有引擎，但 DecisionBrain.__init__ 不接受 orchestrator

修复: 在 `brain` 属性中使用独立的初始化逻辑:

```python
@property
def brain(self):
    if "brain" not in self._engines:
        try:
            from ...brain.fsm import DecisionBrain
            self._engines["brain"] = DecisionBrain(
                evt_risk=self._get_evt_risk(),
                sizer=self._get_sizer(),
            )
        except Exception as e:
            logger.warning(f"DecisionBrain init failed: {e}")
            self._engines["brain"] = None
    return self._engines["brain"]
```

**提交:** `fix(services): fix engine_factory DecisionBrain instantiation (signature mismatch)`

---

# Phase 1B: Data 全层迁移

**目标:** 从 TDX 复制完整数据层
**预计:** 1-1.5 小时
**依赖:** Phase 0, Phase 1A
**验证:** `python -c "from uniquant.data.data_fetcher import DataFetcher; from uniquant.data.lake.storage_manager import StorageManager"`

---

## 1B.1 数据源协议和工具

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/sources/base.py` | `data/sources/base.py` | 78 |
| `data/sources/protocols.py` | `data/sources/protocols.py` | 172 |
| `data/utils/normalizer.py` | `data/utils/normalizer.py` | ~200 |

**提交:** `feat(data/sources): migrate base.py, protocols.py from TDX (DataSource ABC)`

---

## 1B.2 数据源实现 (7个)

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/sources/tdx.py` | `data/sources/tdx.py` | 177 |
| `data/sources/baostock.py` | `data/sources/baostock.py` | 461 |
| `data/sources/sina.py` | `data/sources/sina.py` | 607 |
| `data/sources/tencent.py` | `data/sources/tencent.py` | 367 |
| `data/sources/ths.py` | `data/sources/ths.py` | 620 |
| `data/sources/eastmoney.py` | `data/sources/eastmoney.py` | 1095 |
| `data/sources/realtime_bridge.py` | `data/sources/realtime_bridge.py` | 425 |

每个文件的 import 适配规则:
```
from src.shared.* → from ...shared.*
from src.data.*   → from ...data.*
```

**提交:** `feat(data/sources): migrate 7 data sources from TDX (tdx, baostock, sina, tencent, ths, eastmoney, realtime_bridge)`

---

## 1B.3 数据管理器 (11个)

| 源 | 目标 | 行数 |
|-----|------|------|
| `managers/source_router.py` | `managers/source_router.py` | 246 |
| `managers/standard_adapter.py` | `managers/standard_adapter.py` | 94 |
| `managers/stock_metadata_manager.py` | `managers/stock_metadata_manager.py` | 323 |
| `managers/trade_calendar_manager.py` | `managers/trade_calendar_manager.py` | 159 |
| `managers/adjust_factor_manager.py` | `managers/adjust_factor_manager.py` | 173 |
| `managers/factor_manager.py` | `managers/factor_manager.py` | 454 |
| `managers/tdx_updater.py` | `managers/tdx_updater.py` | 645 |
| `managers/stock_data_updater.py` | `managers/stock_data_updater.py` | 148 |
| `managers/market_data_coordinator.py` | `managers/market_data_coordinator.py` | 99 |
| `managers/cache_manager.py` | `managers/cache_manager.py` | 68 |
| `managers/baostock_cache_manager.py` | `managers/baostock_cache_manager.py` | 143 |
| `managers/data_normalizer.py` | `managers/data_normalizer.py` | 27 |

**提交:** `feat(data/managers): migrate 12 data managers from TDX (source_router, metadata, calendar, factors, updater)`

---

## 1B.4 数据管道

| 源 | 目标 |
|-----|------|
| `data/pipeline/data_adjuster.py` | `data/pipeline/data_adjuster.py` |
| `data/pipeline/data_cleaner.py` | `data/pipeline/data_cleaner.py` |
| `data/pipeline/data_validator.py` | `data/pipeline/data_validator.py` |

**提交:** `feat(data/pipeline): migrate data_adjuster, data_cleaner, data_validator from TDX`

---

## 1B.5 TDX 二进制解析器

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/parsers/tdx_parser.py` | `data/parsers/tdx_parser.py` | 561 |

**提交:** `feat(data/parsers): migrate tdx_parser.py from TDX (.day/.gbbq binary parsing)`

---

## 1B.6 数据导入服务 (6个)

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/services/data_importer.py` | `data/services/data_importer.py` | 709 |
| `data/services/import_1min.py` | `data/services/import_1min.py` | 303 |
| `data/services/import_5min.py` | `data/services/import_5min.py` | 303 |
| `data/services/import_financial.py` | `data/services/import_financial.py` | 433 |
| `data/services/import_index.py` | `data/services/import_index.py` | 380 |
| `data/services/lppl_data_service.py` | `data/services/lppl_data_service.py` | 252 |

**提交:** `feat(data/services): migrate 6 import services from TDX (daily, 1min, 5min, financial, index, lppl)`

---

## 1B.7 存储层

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/lake/storage_manager.py` | `data/lake/storage_manager.py` | 592 |

**提交:** `feat(data/lake): migrate storage_manager.py from TDX (Parquet I/O, atomic writes)`

---

## 1B.8 数据层核心

| 源 | 目标 | 行数 |
|-----|------|------|
| `data/data_fetcher.py` | `data/data_fetcher.py` | 268 |
| `data/data_ingestion_service.py` | `data/data_ingestion_service.py` | 48 |
| `data/data_pipeline_service.py` | `data/data_pipeline_service.py` | 22 |
| `data/__init__.py` | `data/__init__.py` | 57 |

**提交:** `feat(data): migrate data_fetcher.py and data layer init from TDX`

---

## 1B.9 复制数据文件

| 源 | 目标 |
|-----|------|
| `data/all_stock_codes.csv` | `data/all_stock_codes.csv` |
| `data/stock_list.csv` | `data/stock_list.csv` |

**提交:** `chore(data): copy stock metadata CSV files from TDX`

---

# Phase 1C: Services 层迁移

**目标:** 迁移所有缺失的服务模块
**预计:** 30-45 分钟
**依赖:** Phase 1B (data 层)
**验证:** `python -c "from uniquant.services.data_service import DataService; from uniquant.services.scan_service import ScanPipeline"`

---

## 1C.1 核心服务

| 源 | 目标 | 行数 |
|-----|------|------|
| `services/data_service.py` | `services/data_service.py` | 517 |
| `services/validation_service.py` | `services/validation_service.py` | 415 |
| `services/cache_coordinator.py` | `services/cache_coordinator.py` | 232 |
| `services/stock_query_service.py` | `services/stock_query_service.py` | 213 |

**提交:** `feat(services): migrate data_service, validation_service, cache_coordinator, stock_query_service from TDX`

---

## 1C.2 业务服务

| 源 | 目标 | 行数 |
|-----|------|------|
| `services/scan_service.py` | `services/scan_service.py` | 547 |
| `services/portfolio_service.py` | `services/portfolio_service.py` | 568 |
| `services/data_access_service.py` | `services/data_access_service.py` | 238 |
| `services/data_quality_service.py` | `services/data_quality_service.py` | 346 |
| `services/health_service.py` | `services/health_service.py` | ~200 |
| `services/report_service.py` | `services/report_service.py` | ~300 |
| `services/signal_generation_service.py` | `services/signal_generation_service.py` | ~100 |
| `services/market_regime_service.py` | `services/market_regime_service.py` | ~100 |

**提交:** `feat(services): migrate scan_service, portfolio_service and auxiliary services from TDX`

---

## 1C.3 分析引擎适配器

| 源 | 目标 | 行数 |
|-----|------|------|
| `services/analysis/fsm_analysis_engine.py` | `services/analysis/fsm_analysis_engine.py` | 247 |
| `services/analysis/lppl_analysis_engine.py` | `services/analysis/lppl_analysis_engine.py` | 178 |
| `services/analysis/macro_analysis_engine.py` | `services/analysis/macro_analysis_engine.py` | 198 |
| `services/analysis/signal_service.py` | `services/analysis/signal_service.py` | 302 |

**提交:** `feat(services/analysis): migrate fsm, lppl, macro, signal analysis engines from TDX`

---

## 1C.4 修复 `services/__init__.py`

迁移完成后恢复完整导入:

```python
from .cache_coordinator import CacheCoordinator
from .data_quality_service import DataQualityService
from .data_service import DataService
from .health_service import HealthService
from .portfolio_service import PortfolioService
from .scan_service import ScanPipeline
from .stock_query_service import StockQueryService
from .validation_service import ValidationService

__all__ = [
    "CacheCoordinator", "DataQualityService", "DataService",
    "HealthService", "PortfolioService", "ScanPipeline",
    "StockQueryService", "ValidationService",
]
```

**提交:** `fix(services): restore full __init__.py imports after migration`

---

## 1C.5 修复 `services/analysis/__init__.py`

```python
from .macro_service import MacroAnalysisService
from .technical_service import TechnicalAnalysisService
from .signal_service import SignalAnalysisService
from .engine_factory import AnalysisEngineFactory

__all__ = [
    "MacroAnalysisService", "TechnicalAnalysisService",
    "SignalAnalysisService", "AnalysisEngineFactory",
]
```

**提交:** `fix(services/analysis): restore signal_service import after migration`

---

# Phase 1D: Brain LPPL + Factor 迁移

**目标:** 迁移 LPPL 子模块和完整因子流水线
**预计:** 30-45 分钟
**依赖:** Phase 1A
**验证:** `python -c "from uniquant.brain.lppl import calculator, core; from uniquant.brain.factors import FactorAnalyzer, FactorComposer"`

---

## 1D.1 LPPL 子模块 (6个)

| 源 | 目标 |
|-----|------|
| `brain/lppl/calculator.py` | `brain/lppl/calculator.py` |
| `brain/lppl/core.py` | `brain/lppl/core.py` |
| `brain/lppl/multifit.py` | `brain/lppl/multifit.py` |
| `brain/lppl/cluster.py` | `brain/lppl/cluster.py` |
| `brain/lppl/regime.py` | `brain/lppl/regime.py` |
| `brain/lppl/computation.py` | `brain/lppl/computation.py` |
| `brain/lppl/data_manager.py` | `brain/lppl/data_manager.py` |
| `brain/lppl/visualizer.py` | `brain/lppl/visualizer.py` |

迁移完成后修复 `brain/lppl/__init__.py` 恢复完整导入。

**提交:** `feat(brain/lppl): migrate 8 LPPL submodules from TDX (calculator, core, multifit, cluster, regime, computation, data_manager, visualizer)`

---

## 1D.2 因子流水线 (8个)

| 源 | 目标 | 行数 |
|-----|------|------|
| `brain/factors/__init__.py` | `brain/factors/__init__.py` | 7 |
| `brain/factors/registry.py` | `brain/factors/registry.py` | 102 |
| `brain/factors/analyzer.py` | `brain/factors/analyzer.py` | 459 |
| `brain/factors/composer.py` | `brain/factors/composer.py` | 308 |
| `brain/factors/custom_factors.py` | `brain/factors/custom_factors.py` | 183 |
| `brain/factors/financial_bridge.py` | `brain/factors/financial_bridge.py` | 406 |
| `brain/factors/neutralizer.py` | `brain/factors/neutralizer.py` | 40 |
| `brain/factors/industry_provider.py` | `brain/factors/industry_provider.py` | 20 |

Import 适配:
```
from src.brain.factors.registry → from .registry
from ...shared.* → from ..shared.*
```

**提交:** `feat(brain/factors): migrate complete factor pipeline from TDX (registry, analyzer, composer, 10 custom factors, financial bridge)`

---

## 1D.3 股票筛选器

| 源 | 目标 | 行数 |
|-----|------|------|
| `brain/screener.py` | `brain/screener.py` | ~400 |

**提交:** `feat(brain): migrate screener.py from TDX (StockScreener + ScreenerConfig)`

---

## 1D.4 修复 brain/fsm/fsm.py indicators 导入

迁移 indicators.py 后，移除 Phase 0 的 fallback，恢复直接导入:

```python
# 恢复:
from ..indicators import Indicators
```

**提交:** `fix(brain/fsm): restore direct Indicators import after migration`

---

# Phase 1E: Hands + 回测迁移

**目标:** 迁移报告、结果管理和回测引擎
**预计:** 20-30 分钟
**依赖:** Phase 1A (risk), Phase 1B (data)
**验证:** `python -c "from uniquant.hands.backtest import BacktestEngine, BacktestResult; from uniquant.hands.reporter import Reporter"`

---

## 1E.1 报告和结果管理

| 源 | 目标 | 行数 |
|-----|------|------|
| `hands/reporter.py` | `hands/reporter.py` | 150 |
| `hands/results_manager.py` | `hands/results_manager.py` | 362 |

**提交:** `feat(hands): migrate reporter.py and results_manager.py from TDX`

---

## 1E.2 回测引擎

| 源 | 目标 | 行数 |
|-----|------|------|
| `hands/backtest/__init__.py` | `hands/backtest/__init__.py` | 4 |
| `hands/backtest/engine.py` | `hands/backtest/engine.py` | 521 |
| `hands/backtest/result.py` | `hands/backtest/result.py` | 160 |

**提交:** `feat(hands/backtest): migrate BacktestEngine and BacktestResult from TDX (standard, rolling, walk-forward, stress test)`

---

## 1E.3 策略

| 源 | 目标 | 行数 |
|-----|------|------|
| `hands/strategies/__init__.py` | `hands/strategies/__init__.py` | 31 |
| `hands/strategies/base.py` | `hands/strategies/base.py` | 147 |
| `hands/strategies/fsm_strategy.py` | `hands/strategies/fsm_strategy.py` | 81 |

Import 适配: `from src.*` → 相对导入

**提交:** `feat(hands/strategies): migrate BaseStrategy and FSMStrategy from TDX (backtrader integration)`

---

## 1E.4 修复 `hands/__init__.py`

迁移完成后恢复:

```python
from .reporter import Reporter
from .results_manager import ResultsManager

__all__ = ["Reporter", "ResultsManager"]
```

**提交:** `fix(hands): restore __init__.py imports after migration`

---

# Phase 1F: UI 层迁移

**目标:** 迁移 UI 幽灵模块
**预计:** 20-30 分钟
**依赖:** Phase 1C (services)
**验证:** `python -c "from uniquant.ui.components import render_health_metrics; from uniquant.ui.manager_logic import AssetManager"`

---

## 1F.1 UI 组件

| 源 | 目标 | 行数 |
|-----|------|------|
| `ui/components.py` | `ui/components.py` | 435 |
| `ui/lppl_visualizer.py` | `ui/lppl_visualizer.py` | 350 |
| `ui/manager_logic.py` | `ui/manager_logic.py` | 466 |
| `ui/manager_portfolio_analytics_service.py` | `ui/manager_portfolio_analytics_service.py` | ~200 |
| `ui/manager_report_service.py` | `ui/manager_report_service.py` | ~200 |

Import 适配: `from src.*` → `from ...*`

**提交:** `feat(ui): migrate components, lppl_visualizer, manager_logic from TDX (25 render functions, AssetManager)`

---

## 1F.2 恢复 dashboard.py 幽灵导入

Phase 0 的 try/except 改为正常导入:

```python
from uniquant.ui.components import render_health_metrics, ...
from uniquant.ui.lppl_visualizer import LPPLVisualizer
from uniquant.ui.manager_logic import AssetManager
```

**提交:** `fix(ui): restore dashboard.py imports after UI module migration`

---

# Phase 2: mootdx 数据层适配

**目标:** 在 TDX 迁移基础上集成 mootdx 为主数据源
**预计:** 2-3 小时
**依赖:** Phase 1B
**验证:** 端到端测试 mootdx 读取 → Parquet 存储 → 周线月线合成

---

## 2.1 新增 mootdx 离线数据源

**文件:** `src/uniquant/data/sources/mootdx_local.py` (新建)
**行数:** ~100

```python
from .base import DataSource
from mootdx.reader import Reader

class MootdxLocalSource(DataSource):
    def __init__(self, tdx_dir: str):
        self._reader = Reader.factory(market='std', tdxdir=tdx_dir)

    def fetch_daily(self, symbol, start_date, end_date):
        code = symbol.split('.')[0]
        return self._reader.daily(symbol=code)

    def fetch_real_time(self, symbol):
        return pd.DataFrame()

    def fetch_market_cap(self, symbol):
        return 0.0
```

**提交:** `feat(data/sources): add MootdxLocalSource (Tier 1 offline reader)`

---

## 2.2 新增 mootdx 在线数据源

**文件:** `src/uniquant/data/sources/mootdx_online.py` (新建)
**行数:** ~80

```python
from mootdx.quotes import Quotes

class MootdxOnlineSource(DataSource):
    def __init__(self):
        self._client = Quotes.factory(market='std', heartbeat=True)

    def fetch_daily(self, symbol, start_date, end_date):
        code = symbol.split('.')[0]
        return self._client.k(symbol=code, begin=start_date, end=end_date)

    def fetch_real_time(self, symbol):
        code = symbol.split('.')[0]
        return self._client.quotes(symbol=[code])

    def fetch_market_cap(self, symbol):
        return 0.0
```

**提交:** `feat(data/sources): add MootdxOnlineSource (Tier 2 online API)`

---

## 2.3 新增 mootdx 因子管理器

**文件:** `src/uniquant/data/managers/mootdx_factor_manager.py` (新建)
**行数:** ~120

功能: 从新浪 API 下载 qfq 因子，存储到 `data/factors/qfq/` 目录（非缓存）

```python
from pathlib import Path
from mootdx.utils.factor import fq_factor
from mootdx.utils import get_stock_market

class MootdxFactorManager:
    def __init__(self, lake_dir: str):
        self._qfq_dir = Path(lake_dir) / "factors" / "qfq"
        self._qfq_dir.mkdir(parents=True, exist_ok=True)

    def download(self, code: str, method: str = "qfq") -> Path:
        factor = fq_factor(code, method)
        path = self._get_path(code, method)
        factor.to_pickle(str(path))
        return path

    def download_batch(self, codes: list[str], method: str = "qfq") -> dict[str, bool]:
        results = {}
        for code in codes:
            try:
                path = self.download(code, method)
                results[code] = path.exists()
            except Exception:
                results[code] = False
        return results

    def load(self, code: str, method: str = "qfq") -> pd.DataFrame:
        path = self._get_path(code, method)
        return pd.read_pickle(str(path)) if path.exists() else pd.DataFrame()

    def has_factor(self, code: str, method: str = "qfq") -> bool:
        return self._get_path(code, method).exists()

    def list_factors(self, method: str = "qfq") -> list[str]:
        return [f.stem for f in self._qfq_dir.glob("*.pkl")]

    def _get_path(self, code: str, method: str) -> Path:
        market = get_stock_market(code, string=True)
        clean = code.replace("sh", "").replace("sz", "").replace("bj", "")
        d = self._qfq_dir if method == "qfq" else self._hfq_dir
        return d / f"{market}{clean}.pkl"
```

**提交:** `feat(data/managers): add MootdxFactorManager (qfq factor download and local storage)`

---

## 2.4 修改 DataFetcher 集成 mootdx

**文件:** `src/uniquant/data/data_fetcher.py`
**操作:** 修改 `__init__` 方法 sources 列表

```python
# 在 sources 列表头部添加:
try:
    from .sources.mootdx_local import MootdxLocalSource
    sources.insert(0, MootdxLocalSource(tdx_dir))
except ImportError:
    pass
```

**提交:** `feat(data): integrate MootdxLocalSource into DataFetcher (highest priority source)`

---

## 2.5 扩展 StorageManager 周线/月线

**文件:** `src/uniquant/data/lake/storage_manager.py`
**操作:** 新增 2 个方法

```python
def synthesize_weekly(self, symbol: str) -> pd.DataFrame:
    """日线 → 周线: 按周聚合 OHLCV"""
    df = self.read_data(symbol, data_type="daily")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["week"] = df["date"].dt.to_period("W")
    weekly = df.groupby("week").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).reset_index()
    weekly["date"] = weekly["week"].dt.to_timestamp() + pd.Timedelta(days=4)
    return weekly.drop(columns=["week"])

def synthesize_monthly(self, symbol: str) -> pd.DataFrame:
    """日线 → 月线: 按月聚合 OHLCV"""
    df = self.read_data(symbol, data_type="daily")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).reset_index()
    monthly["date"] = monthly["month"].dt.to_timestamp() + pd.offsets.MonthEnd(0)
    return monthly.drop(columns=["month"])
```

**提交:** `feat(data/lake): add synthesize_weekly and synthesize_monthly to StorageManager`

---

## 2.6 新增同步脚本

**目录:** `data/scripts/` (新建)

| 脚本 | 功能 |
|------|------|
| `sync_daily_mootdx.py` | mootdx 日线增量同步 |
| `sync_minute_mootdx.py` | mootdx 分钟线同步 |
| `sync_financial_mootdx.py` | mootdx 财务数据同步 |
| `sync_factors_mootdx.py` | mootdx qfq 因子批量同步 |

每个脚本 ~80-120 行，CLI 入口: `python -m data.scripts.sync_daily_mootdx --codes 600519 000001`

**提交:** `feat(data/scripts): add mootdx sync scripts for daily, minute, financial, and factor data`

---

# Phase 3: 验证 + 修复

**目标:** 全量验证 + 修复已知 Bug + 迁移测试
**预计:** 1-2 小时
**依赖:** Phase 1 + Phase 2

---

## 3.1 全量导入验证

```bash
python -c "
import uniquant
import uniquant.shared
import uniquant.brain
import uniquant.brain.fsm
import uniquant.brain.czsc
import uniquant.brain.lppl
import uniquant.brain.factors
import uniquant.data
import uniquant.services
import uniquant.services.analysis
import uniquant.risk
import uniquant.hands
import uniquant.ui
print('All imports OK')
"
```

**提交:** `test: add import smoke test for all packages`

---

## 3.2 修复 PortfolioOptimizer Bug

**文件:** `src/uniquant/risk/portfolio_optimizer.py`

```python
# 修复前:
self.weights_ = result.x
# 修复后:
self.weights_ = result.x
self._last_assets = list(returns.columns)
```

```python
# 修复前 (generate_report):
for asset, weight in self.weights_.items() if hasattr(self.weights_, 'items') else []:
# 修复后:
for asset, weight in zip(self._last_assets, self.weights_):
```

**提交:** `fix(risk): fix PortfolioOptimizer.generate_report() numpy array .items() bug`

---

## 3.3 修复 Protocol 类型不匹配

**文件:** `src/uniquant/shared/interfaces.py`

```python
# 修复前:
def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]:
# 修复后:
def calculate_metrics(self, returns: pd.Series) -> Dict[str, Any]:
```

**提交:** `fix(shared): correct RiskAssessmentProtocol.calculate_metrics type (DataFrame → Series)`

---

## 3.4 从 TDX 复制测试文件

```bash
# 复制所有测试
cp /home/james/Documents/Project/TDX/tests/*.py /home/james/Documents/Project/UniQuant/tests/
cp /home/james/Documents/Project/TDX/tests/conftest.py /home/james/Documents/Project/UniQuant/tests/
```

Import 适配: 批量 `from src.` → `from uniquant.`

**提交:** `test: copy 68 test files from TDX and adapt import paths`

---

## 3.5 运行测试

```bash
pytest tests/ -v --tb=short
```

对于失败的测试: 逐个修复 import 路径或 mock 依赖。

**提交:** `fix: resolve test failures from import path adaptation`

---

# Phase 4: 清理

**目标:** 删除废弃代码、清理死代码
**预计:** 30-60 分钟
**依赖:** Phase 3

---

## 4.1 删除废弃模块

| 文件 | 操作 | 理由 |
|------|------|------|
| `shared/errors.py` | 删除 | deprecated shim，所有引用已迁移到 exceptions.py |
| `shared/limits.py` | 删除 | 与 limit_checker.py 完全重复 |
| `shared/error_handling.py` 中 `retry_on_exception` | 删除 | 与 retry_decorator.py 重复 |

**提交:** `refactor(shared): remove deprecated errors.py, limits.py, and duplicate retry_on_exception`

---

## 4.2 清理死代码

| 文件 | 操作 |
|------|------|
| `risk/drawdown_analyzer.py` | 删除未使用的 `new_dd` 变量 |
| `brain/lppl/engine.py` | 删除未使用的 `multiprocessing` 导入 |
| `ui/health_check.py` | 删除未使用的 `Any` 导入 |
| `hands/__init__.py` | 修正 `src.hands` → `uniquant.hands` 错误消息 |

**提交:** `refactor: remove dead code and fix stale references`

---

## 4.3 拆分 constants.py (可选, 后续优化)

将 1139 行的 `shared/constants.py` 拆分为:

```
shared/constants/
├── __init__.py          # 统一导出
├── market.py            # MarketConstants, MarketHours
├── risk.py              # RiskThresholds
├── data.py              # DataValidationConstants
├── performance.py       # CacheConstants, NetworkConstants
├── indicators.py        # IndicatorThresholds, LPPLConstants
└── service.py           # AnalysisServiceConstants, TimeConstants
```

**提交:** `refactor(shared/constants): split monolithic 1139-line constants.py into 6 domain modules`

---

## 4.4 提取 CacheMixin (可选, 后续优化)

将 3 个 service 中的重复缓存逻辑提取到:

```python
# shared/cache_mixin.py
class CacheMixin:
    def _generate_cache_key(self, prefix: str, **kwargs) -> str: ...
    def _get_cached(self, key: str) -> Any: ...
    def _set_cached(self, key: str, value: Any, ttl: int = 300) -> bool: ...
```

**提交:** `refactor(shared): extract CacheMixin to eliminate 3x cache logic duplication`

---

## 4.5 补充缺失依赖

**文件:** `pyproject.toml`
**操作:** 新增 2 个必要依赖

`pyproject.toml` 缺少 TDX 数据层所需的运行时依赖:

```toml
# 在 [project.dependencies] 中新增:
"pybreaker>=1.0.0",       # SourceRouter 熔断器 (data/managers/source_router.py)
"tenacity>=8.0.0",        # retry 装饰器 (shared/retry_decorator.py, 各数据源)
```

**验证:** `pip install pybreaker tenacity && python -c "from data.managers.source_router import SourceRouter"`

**提交:** `chore: add missing pybreaker and tenacity dependencies to pyproject.toml`

---

# 数据多源降级架构

## 降级链路图

```
get_daily("600519.SH", "20200101", "20241231")
  │
  ├── Tier 1: MootdxLocalSource.fetch_daily()
  │   熔断器: 5次失败/30s恢复
  │   超时: SOCKET_TIMEOUT
  │
  ├── Tier 2: MootdxOnlineSource.fetch_daily()
  │   同上
  │
  ├── Tier 3: TdxSource.fetch_daily()
  │   本地 .day 文件直接解析
  │
  ├── Tier 4: BaostockSource.fetch_daily()
  │   @retry(3次, 指数退避)
  │
  ├── Tier 5: SinaSource.fetch_daily()
  │   请求间隔 1.5-3s
  │
  ├── Tier 6: TencentSource.fetch_daily()
  │
  ├── Tier 7: ThsSource.fetch_daily()
  │
  └── Tier 8: EastmoneySource.fetch_daily()
      请求间隔 1s, 每10次额外 3-5s
      SSL verify=False
```

## 复权因子降级

```
get_adjusted_daily("600519.SH", adjust="qfq")
  │
  ├── Tier 1: MootdxFactorManager.load(code)  ← 本地 qfq/*.pkl
  │   数据源: 新浪API预下载
  │
  ├── Tier 2: FactorManager.read_factor(code)  ← 本地 factors/*.parquet
  │   数据源: TDX GBBQ 本地计算
  │
  └── Tier 3: DataAdjuster 直接从 GBBQ 计算
      源文件: data/fq/gbbq.parquet
```

---

# 执行清单

逐项检查，完成后标记 `[x]`:

## Phase 0: 紧急修复
- [ ] 0.1 修复 `services/__init__.py` 幽灵导入
- [ ] 0.2 修复 `brain/lppl/__init__.py` 幽灵导入
- [ ] 0.3 修复 `services/analysis/__init__.py` 幽灵导入
- [ ] 0.4 修复 `ui/dashboard.py` 幽灵导入 (try/except)
- [ ] 0.5 创建 brain/czsc/, brain/fsm/, risk/, ui/ 的 `__init__.py`
- [ ] 0.6 修复 brain/fsm/fsm.py indicators 临时 fallback
- [ ] 0.7 删除 `services/analysis/__init__.py` 中 WyckoffAnalysisEngine 幽灵导入

**Phase 0 验收:** `python -c "import uniquant; import uniquant.shared; import uniquant.brain.fsm"`

## Phase 1A: Shared + Brain 基础层
- [ ] 1A.1 复制 brain/indicators.py
- [ ] 1A.2 复制 brain/alpha_decoupler.py
- [ ] 1A.3 复制 risk/evt_risk.py
- [ ] 1A.4 复制 risk/sizer.py + 修复 3 个绝对导入
- [ ] 1A.5 复制 shared/market_rules.py
- [ ] 1A.6 复制 risk/portfolio_optimizer.py + 修复 numpy bug
- [ ] 1A.7 复制 risk/structural.py
- [ ] 1A.8 复制 brain/ntf/ 和 brain/regime/
- [ ] 1A.9 修复 engine_factory.py DecisionBrain 签名
- [ ] 1A.10 复制 shared/ 的 4 个缺失子模块 (market_constants, network_constants, price_collar, risk_constants)

**Phase 1A 验收:** `python -c "from uniquant.brain.indicators import Indicators; from uniquant.risk.evt_risk import EVTRisk; from uniquant.risk.sizer import PositionSizer"`

## Phase 1B: Data 全层
- [ ] 1B.1 复制 sources/base.py, protocols.py, utils/normalizer.py
- [ ] 1B.2 复制 7 个数据源 (tdx, baostock, sina, tencent, ths, eastmoney, realtime_bridge)
- [ ] 1B.3 复制 12 个管理器
- [ ] 1B.4 复制 pipeline (adjuster, cleaner, validator)
- [ ] 1B.5 复制 parsers/tdx_parser.py
- [ ] 1B.6 复制 6 个导入服务
- [ ] 1B.7 复制 lake/storage_manager.py
- [ ] 1B.8 复制 data_fetcher.py, ingestion, pipeline service
- [ ] 1B.9 复制 CSV 数据文件

**Phase 1B 验收:** `python -c "from uniquant.data.data_fetcher import DataFetcher; from uniquant.data.lake.storage_manager import StorageManager"`

## Phase 1C: Services 层
- [ ] 1C.1 复制核心服务 (data_service, validation, cache, stock_query)
- [ ] 1C.2 复制业务服务 (scan, portfolio, access, quality, health, report, signal, market_regime)
- [ ] 1C.3 复制分析引擎适配器 (fsm, lppl, macro, signal)
- [ ] 1C.4 恢复 services/__init__.py 完整导入
- [ ] 1C.5 恢复 services/analysis/__init__.py 完整导入

**Phase 1C 验收:** `python -c "from uniquant.services.data_service import DataService; from uniquant.services.scan_service import ScanPipeline"`

## Phase 1D: Brain LPPL + Factor
- [ ] 1D.1 复制 8 个 LPPL 子模块
- [ ] 1D.2 复制 8 个因子流水线模块
- [ ] 1D.3 复制 screener.py
- [ ] 1D.4 恢复 brain/fsm/fsm.py indicators 导入

**Phase 1D 验收:** `python -c "from uniquant.brain.factors import FactorAnalyzer, FactorComposer; from uniquant.brain.screener import StockScreener"`

## Phase 1E: Hands + 回测
- [ ] 1E.1 复制 reporter.py, results_manager.py
- [ ] 1E.2 复制 backtest/ (engine, result)
- [ ] 1E.3 复制 strategies/ (base, fsm_strategy)
- [ ] 1E.4 恢复 hands/__init__.py

**Phase 1E 验收:** `python -c "from uniquant.hands.backtest import BacktestEngine; from uniquant.hands.reporter import Reporter"`

## Phase 1F: UI 层
- [ ] 1F.1 复制 components.py, lppl_visualizer.py, manager_logic.py + 辅助服务
- [ ] 1F.2 恢复 dashboard.py 正常导入

**Phase 1F 验收:** `python -c "from uniquant.ui.components import render_health_metrics; from uniquant.ui.manager_logic import AssetManager"`

## Phase 2: mootdx 适配
- [ ] 2.1 新建 data/sources/mootdx_local.py
- [ ] 2.2 新建 data/sources/mootdx_online.py
- [ ] 2.3 新建 data/managers/mootdx_factor_manager.py
- [ ] 2.4 修改 data_fetcher.py 集成 mootdx
- [ ] 2.5 扩展 storage_manager.py 周线/月线
- [ ] 2.6 新增 data/scripts/ 同步脚本

**Phase 2 验收:** mootdx 端到端测试通过

## Phase 3: 验证 + 修复
- [ ] 3.1 全量导入验证
- [ ] 3.2 修复 PortfolioOptimizer bug
- [ ] 3.3 修复 Protocol 类型不匹配
- [ ] 3.4 复制 68 个测试文件 + import 适配
- [ ] 3.5 运行测试 + 修复失败项

**Phase 3 验收:** `pytest tests/ -v` 通过率 > 80%

## Phase 4: 清理
- [ ] 4.1 删除 deprecated 模块
- [ ] 4.2 清理死代码
- [ ] 4.3 拆分 constants.py (可选)
- [ ] 4.4 提取 CacheMixin (可选)
- [ ] 4.5 补充缺失依赖 (pybreaker, tenacity)

**最终验收:**
```bash
python -c "import uniquant; print('Import OK')"
pytest tests/ -v
python -c "
from uniquant.data.data_fetcher import DataFetcher
from uniquant.services.analysis_service import AnalysisService
from uniquant.hands.backtest import BacktestEngine
print('All major modules OK')
"
```

---

## Commit 规范

遵循 Conventional Commits:

```
feat(scope): 描述新功能
fix(scope): 描述修复
refactor(scope): 描述重构
test(scope): 描述测试
chore(scope): 描述杂项
```

Scope 取值: `shared`, `brain`, `brain/lppl`, `brain/factors`, `brain/fsm`, `risk`, `data`, `data/sources`, `data/lake`, `data/managers`, `data/services`, `services`, `services/analysis`, `hands`, `hands/backtest`, `hands/strategies`, `ui`

---

## 估计总时间

| Phase | 时间 | 提交数 |
|-------|------|--------|
| Phase 0 | 0.5h | 7 |
| Phase 1A | 0.5h | 10 |
| Phase 1B | 1.5h | 9 |
| Phase 1C | 0.5h | 5 |
| Phase 1D | 0.5h | 4 |
| Phase 1E | 0.3h | 4 |
| Phase 1F | 0.3h | 2 |
| Phase 2 | 2.5h | 6 |
| Phase 3 | 1.5h | 5 |
| Phase 4 | 0.5h | 5 |
| **合计** | **~8.6h** | **~57** |

---

*文档版本: v3.1 | 生成时间: 2026-05-25 | 架构审查: 2026-05-25*
*基于 TDX 原始项目 145 个源文件 + 68 个测试文件的完整分析*
*审查发现: 6项修正已合并 (Wyckoff幽灵导入、shared子模块、import映射、依赖补充、文件计数、并行优化)*
