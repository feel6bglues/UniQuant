# 架构导航

## 何时使用

AI 首次进入项目、需要定位模块、理解依赖关系、判断修改影响范围时。

## 架构概览

UniQuant 采用五层 DAG 架构（基础设施 → 数据 → 分析 → 服务 → 应用），各层仅允许上层依赖下层，严禁反向依赖。

```
┌─────────────────────────────────────────────────────────┐
│                   应用层 (Application)                    │
│  hands/ (回测引擎、策略库)    ui/ (Streamlit 仪表盘)      │
├─────────────────────────────────────────────────────────┤
│                   服务层 (Services)                       │
│  ServiceContainer DAG 容器、AnalysisEngineFactory        │
│  AnalysisService、DataService、CacheCoordinator          │
├─────────────────────────────────────────────────────────┤
│                   分析层 (Analysis/Brain)                 │
│  brain/ (FSM、CZSC、LPPL)    risk/ (回撤分析)            │
├─────────────────────────────────────────────────────────┤
│                   数据层 (Data)                           │
│  尚未实现，架构文档规划了 7 个数据源和管道组件            │
├─────────────────────────────────────────────────────────┤
│                基础设施层 (Infrastructure/Shared)          │
│  Protocol 接口、常量、异常、日志、缓存、重试、配置       │
└─────────────────────────────────────────────────────────┘
```

各层职责：
- **基础设施层** (`shared/`)：提供 Protocol 接口、常量、异常体系、日志工厂、缓存抽象、重试机制等横切关注点。
- **数据层** (`data/`)：规划中，负责外部数据获取、清洗、标准化和持久化。
- **分析层** (`brain/` + `risk/`)：核心量化分析引擎，包含 CZSC/FSM/LPPL 等分析子模块和风险度量。
- **服务层** (`services/`)：通过 DAG 容器编排所有服务，延迟初始化分析引擎。
- **应用层** (`hands/` + `ui/`)：面向用户的回测执行引擎和 Streamlit 可视化仪表盘。

## 各包职责速查表

| 包 | 路径 | .py 文件数 | 状态 | 核心类 |
|---|------|-----------|------|--------|
| shared | `src/uniquant/shared/` | 23 | ✅ 基本完整 | `ServiceContainer`(via interfaces)、`AnalysisResult`、`LoggerFactory`、`CacheInterface` |
| brain | `src/uniquant/brain/` | 5 | ⚠️ 部分可用 | `CZSCEngine`、`FSM`、`DecisionBrain`、`LPPL Engine` |
| services | `src/uniquant/services/` | 11 | ⚠️ 部分可用 | `ServiceContainer`、`AnalysisEngineFactory`、`AnalysisService` |
| risk | `src/uniquant/risk/` | 1 | ⚠️ 最小可用 | `DrawdownAnalyzer` |
| hands | `src/uniquant/hands/` | 1 | 🔲 仅骨架 | — |
| ui | `src/uniquant/ui/` | 2 | ⚠️ 部分可用 | `Dashboard`、`HealthCheck` |
| data | `src/uniquant/data/` | 0 | 🔲 不存在 | 架构文档规划，源码尚未创建 |
| signal | `src/uniquant/signal/` | 0 | 🔲 不存在 | 架构文档规划，源码尚未创建 |

> 文件数来源：`glob src/uniquant/<包>/**/*.py` 实际计数（2026-05-26）

## 5 个 Protocol 接口

来源：`src/uniquant/shared/interfaces.py`，均使用 `@runtime_checkable` 装饰器。

### 1. DataFetcherProtocol（第 102-120 行）

```python
@runtime_checkable
class DataFetcherProtocol(Protocol):
    def fetch_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        period: str = "daily",
    ) -> pd.DataFrame: ...
```

### 2. RiskAssessmentProtocol（第 123-140 行）

```python
@runtime_checkable
class RiskAssessmentProtocol(Protocol):
    def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]: ...
```

### 3. PositionSizerProtocol（第 143-171 行）

```python
@runtime_checkable
class PositionSizerProtocol(Protocol):
    def calculate_shares(
        self,
        price: float,
        stop_loss: float,
        czsc_bottom: Any,
        market: str = "CN",
        symbol: str = "UNKNOWN",
    ) -> Dict[str, Any]: ...
```

### 4. AnalysisEngineProtocol（第 174-192 行）

```python
@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    def analyze(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...
```

### 5. CalculationPluginProtocol（第 195-234 行）

```python
@runtime_checkable
class CalculationPluginProtocol(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    @property
    def description(self) -> str: ...
    def calculate(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...
```

## ServiceContainer DAG 拓扑

来源：`src/uniquant/services/service_container.py` 第 54-82 行 `initialize()` 方法。

初始化顺序（严格 DAG，无循环依赖）：

```
第 1 步: 基础组件（无依赖）
    StorageManager()         ← data.lake.storage_manager
    TradeCalendarManager()   ← data.managers.trade_calendar_manager
    CacheCoordinator()       ← services.cache_coordinator
    StockQueryService()      ← services.stock_query_service

第 2 步: 数据服务（依赖第 1 步）
    DataService(storage, cache, stock_query)

第 3 步: 分析引擎工厂（依赖第 2 步）
    AnalysisEngineFactory(orchestrator=data_svc)
```

注册到容器的服务名：
`storage` → `calendar` → `cache` → `data_service` → `engine_factory`

## AnalysisEngineFactory 延迟加载

来源：`src/uniquant/services/analysis/engine_factory.py` 第 31-65 行。

9 个 `@property` 引擎，首次访问时通过 `_lazy_init()` 动态导入并实例化：

| 属性 | 引擎类 | 模块路径 | 行号 |
|------|--------|---------|------|
| `fsm` | `FsmAnalysisEngine` | `..analysis.fsm_analysis_engine` | 32-33 |
| `czsc` | `CzscAnalysisEngine` | `..analysis.czsc_analysis_engine` | 36-37 |
| `lppl` | `LpplAnalysisEngine` | `..analysis.lppl_analysis_engine` | 40-41 |
| `regime` | `RegimeAnalysisEngine` | `..analysis.regime_analysis_engine` | 44-45 |
| `ntf` | `NtfAnalysisEngine` | `..analysis.ntf_analysis_engine` | 48-49 |
| `macro` | `MacroAnalysisEngine` | `..analysis.macro_analysis_engine` | 52-53 |
| `report` | `ReportGeneratorEngine` | `..analysis.report_generator_engine` | 56-57 |
| `brain` | `DecisionBrain` | `...brain.fsm` | 60-61 |
| `wyckoff` | `WyckoffAnalysisEngine` | `..analysis.wyckoff_analysis_engine` | 64-65 |

`_lazy_init()` 机制（第 18-29 行）：检查 `self._engines` 缓存 → `importlib.import_module` 动态导入 → 实例化并缓存 → 失败时 `logger.warning` 并返回 `None`。

## 模块间数据流

基于代码实际结构的完整路径（从数据源到 UI）：

```
[外部数据源]
    │
    ▼
shared/config_loader.py  ← GlobalConfig 加载配置
shared/interfaces.py     ← DataFetcherProtocol 定义数据获取契约
    │
    ▼
services/data_service.py ← DataService 协调数据获取
services/cache_coordinator.py ← CacheCoordinator 缓存层
    │
    ▼
brain/czsc/  ← CZSC 缠论分析
brain/fsm/   ← FSM 状态机决策
brain/lppl/  ← LPPL 泡沫检测
    │
    ▼
risk/drawdown_analyzer.py ← 风险度量
    │
    ▼
services/analysis_service.py ← AnalysisService 编排分析流程
services/analysis/engine_factory.py ← AnalysisEngineFactory 延迟加载引擎
    │
    ▼
hands/  ← 回测执行引擎（骨架）
    │
    ▼
ui/dashboard.py       ← Streamlit 仪表盘
ui/health_check.py    ← 健康监控
```

数据流向原则：`shared` → `data/brain/risk` → `services` → `hands/ui`，反向依赖被禁止。

## 禁止事项

- **禁止跨层反向依赖**：`shared/` 不得 import 任何上层包（`brain/`、`services/`、`hands/`、`ui/`）。违反会导致循环导入。
- **禁止在 `__init__.py` 中添加未验证的导入**：`shared/__init__.py`（第 1-61 行）已移除 deprecated 的 `cache_manager` 导入。新增导出前必须确认模块存在且无循环依赖。
- **禁止修改 `interfaces.py` 中的 Protocol 签名**：5 个 `@runtime_checkable` Protocol 是全局契约，修改会影响所有实现类和调用方。变更需全量 grep 影响范围。
- **禁止手动实例化引擎**：所有分析引擎必须通过 `AnalysisEngineFactory` 的 `@property` 延迟加载，不得直接 `import` + 构造。
- **禁止绕过 ServiceContainer**：服务获取必须通过 `ServiceContainer.instance().get("name")`，不得自行创建实例。

## 快速定位指南

| 需求 | 去哪里 |
|------|--------|
| 查看所有 Protocol 定义 | `src/uniquant/shared/interfaces.py` |
| 理解服务初始化顺序 | `src/uniquant/services/service_container.py:54` |
| 添加新分析引擎 | `src/uniquant/services/analysis/engine_factory.py` 新增 `@property` |
| 查看常量定义 | `src/uniquant/shared/constants.py` |
| 查看异常体系 | `src/uniquant/shared/exceptions.py` |
| 修改缓存策略 | `src/uniquant/shared/cache/` |
| 查看分析引擎实现 | `src/uniquant/brain/{czsc,fsm,lppl}/` |
| 查看服务层编排 | `src/uniquant/services/analysis_service.py` |
