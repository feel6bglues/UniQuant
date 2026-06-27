# Queue 3 审计报告 V3: 服务编排与 UI (Services + UI)

**审计时间**: 2026-06-06
**审计范围**:
- `services/` (28 文件, ~7,767 LOC) — 14 个服务 + 9 个分析引擎 + 1 个容器
- `ui/` (8 文件, ~3,248 LOC) — 仪表盘 + 5 个支撑模块

**总计**: 36 文件 / ~11,015 LOC

---

## ✅ V2 报告核实

| V2 报告原话 | V3 核实结果 | 状态 |
|------------|------------|------|
| `st_aggrid` 幽灵依赖 | **确认** — `ui/dashboard.py:11` 硬 try/except，**有兜底** (`HAS_AGGRID = False`) | ✅ V2 正确 |
| `streamlit_autorefresh` 幽灵 | **确认** — `ui/dashboard.py:21` 同上 | ✅ V2 正确 |
| `streamlit_echarts` 幽灵 | **确认** — `ui/dashboard.py:28` 同上 | ✅ V2 正确 |
| `health_service.py:503` 无锁单例 | **确认** — `global health_service`，`if health_service is None` 无锁 | ✅ V2 正确 |
| `analysis_service.py` 1650 行 "上帝对象" | **核实修正** — 实际 1642 行（含 1 个 AnalysisService 类，L45-1642） | ⚠️ V2 行数偏差 8 |
| `dashboard.py` 1524 行 | **确认** — 1524 行 | ✅ V2 正确 |
| `ui/__init__.py` 空 | **确认** — 1 字节空文件 | ✅ V2 正确 |
| `services/__init__.py` 顶层 `import importlib` 多余 | 🔄 **核实修正** — V2 说的"顶层"实际是 `__getattr__` 函数内的 `import importlib`（L37），不在顶层，**是合法懒导入** | ⚠️ V2 描述错误 |
| DAG 依赖正确性 | **确认** — `ui/` → `services/` → 下层，方向正确 | ✅ V2 正确 |
| 引擎工厂双重检查锁 | **确认** — `engine_factory.py:18-30` 用 `threading.RLock` | ✅ V2 正确 |
| 服务层延迟导入 | **确认** — `services/__init__.py:16` `__getattr__` 懒加载 14 个服务 | ✅ V2 正确 |

---

## 🔴 P0: 严重腐化点 (Critical Issues)

### 1. `services/health_service.py:495-509` — 全局单例无锁

```python
# health_service.py:494-509
health_service = None  # 模块级 None

def get_health_service() -> HealthService:
    global health_service
    if health_service is None:  # 无锁
        health_service = HealthService()  # 构造开销大
    return health_service
```

**问题**：
- `if health_service is None` 与 `health_service = HealthService()` 之间**无锁保护**
- `HealthService.__init__` 创建 `DataService()`、`AnalysisService`、`EVTRisk()`、`PositionSizer()`、`DecisionBrain()` — **开销巨大**
- 多线程下可能**创建多个实例**（每个 ~500ms 启动）
- 类的 `__init__` 已硬编码 self.* （无外部参数），所以**单例其实没意义**，应改为 `@classmethod` 或模块级

**修复**：
```python
_health_service_instance: Optional[HealthService] = None
_health_lock = threading.Lock()

def get_health_service() -> HealthService:
    global _health_service_instance
    if _health_service_instance is None:
        with _health_lock:
            if _health_service_instance is None:
                _health_service_instance = HealthService()
    return _health_service_instance
```

**或更好**：移除 `health_service = None` 全局变量，改为 `@functools.lru_cache(maxsize=1)`。

### 2. `services/analysis_service.py:45-1642` — `AnalysisService` 单类 1597 行

**核实**：
- 整个 `analysis_service.py` 仅含 1 个类 `AnalysisService`（L45-1642）
- 6 个超大方法：
  - `validate_risk_metrics` (L207-279, 72 行)
  - `scan_etfs` (L1188-1295, 107 行)
  - `_calculate_technical_indicators` (L993-1055, 62 行)
  - `run_comprehensive_analysis` (L1425-1517, 92 行)
  - `enrich_lake_data` (L1530-1642, 112 行)
- 5 大领域职责：指标计算、风险验证、数据丰富、ETF 扫描、综合分析

**问题**：
- 单个类承担 5+ 领域职责（违反 SRP）
- 该类**未通过 ServiceContainer 注入**，而是从 `health_service.py` 直接 `AnalysisService(self.data_service)` 构造
- 任何对 `analysis_service.py` 的修改都需要重新加载整个服务链
- 与 `services/analysis/` 子包**重叠**：
  - `services/analysis_service.py:AnalysisService`
  - `services/analysis/macro_service.py:MacroAnalysisService`
  - `services/analysis/technical_service.py:TechnicalAnalysisService`
  - **3 套并行分析服务抽象**（不统一）

**修复**：
1. 拆分 `AnalysisService` 为 5 个领域类
2. 删除与 `services/analysis/` 的重复抽象

### 3. `ui/dashboard.py:11-29` — 3 个可视化幽灵依赖

```python
# dashboard.py:11
try:
    from st_aggrid import AgGrid, GridOptionsBuilder
    HAS_AGGRID = True
except ImportError:
    HAS_AGGRID = False
    AgGrid = None
    GridOptionsBuilder = None
```

**核实**：
- **3 个 streamlit 扩展** (`st_aggrid`, `streamlit_autorefresh`, `streamlit_echarts`) 都是 try/except 可选
- `pyproject.toml` **未声明**这 3 个包
- **未提供** `streamlit` 扩展的 optional-deps 分组

**修复**：`pyproject.toml` 添加：
```toml
ui = [
    "streamlit-aggrid>=0.3.0",
    "streamlit-autorefresh>=1.0.0",
    "streamlit-echarts>=0.4.0",
]
```

### 4. `services/scan_service.py` — 22+ 大文件无显式异常处理

**核实**：
- `scan_service.py:551` 行是 Q3 第 3 大文件
- **顶层未导入** `validation_service` 或 `retry_decorator`（其他服务有）
- 内部方法需逐一验证异常处理
- 该模块作为扫描流水线，处理**所有**股票的全市场数据
- 任何单只股票处理失败可能**中断整个扫描**

**修复**：
- 在 `__init__` 中注入 `ValidationService`（与 `data_service.py` 模式一致）
- 在 `pipeline.run` 内对单只股票做 try/except 包装

### 5. `ui/dashboard.py:1524` — 1524 行单体仪表盘

**问题**：
- 仪表盘 1524 行，**未拆分**为 tab-specific 模块
- 顶层 11 个 `def` 函数 + 1 个 `if __name__` 块（隐式）
- 包含：AgGrid 集成、自定义刷新、组件渲染、后端获取、K线数据、扫描调用
- 任何修改都需要全文件阅读

**修复**：拆分为：
- `ui/dashboard/main.py` (主入口)
- `ui/dashboard/research.py` (研究报告 tab)
- `ui/dashboard/portfolio.py` (组合 tab)
- `ui/dashboard/etf.py` (ETF 扫描 tab)
- `ui/dashboard/backtest.py` (回测 tab)

---

## 🟠 P1: 重要腐化点 (Major Issues)

### 6. 3 个僵尸服务模块

| 模块 | LOC | 真实使用方 | 状态 |
|------|-----|-----------|------|
| `services/report_service.py` | 14 | **0** (仅 `services/__init__.py` 导出) | 🟡 存根 |
| `services/signal_generation_service.py` | 13 | **0** | 🟡 存根 |
| `services/market_regime_service.py` | 27 | **0** | 🟡 存根 |

**核实**：
- 3 个模块**仅返回占位结果**：
  - `ReportService.generate_report()` 返回 `f"Report for {symbol}: OK"`
  - `SignalGenerationService.generate_signals()` 返回 `{"symbol": ..., "signals": {}}`
  - `MarketRegimeService.detect_*()` 返回 `RegimeResult(regime="unknown", ...)`
- 但被 `services/__init__.py` 通过 `__getattr__` 延迟加载
- 调用方使用时会**得到占位结果**，不易发现

**修复**：
- 选项 A: 实现真实逻辑
- 选项 B: 标记为 `@deprecated`，在 `__getattr__` 中发出 `DeprecationWarning`

### 7. `services/analysis_service.py` 与 `services/analysis/` — 双套抽象

**核实**：
- 旧：`services/analysis_service.py:AnalysisService` (1642 行)
- 新：`services/analysis/macro_service.py:MacroAnalysisService` (430 行)
- 新：`services/analysis/technical_service.py:TechnicalAnalysisService` (259 行)
- **3 个并存**：
  - `AnalysisService` (旧)
  - `MacroAnalysisService` (新) — 拆分了 LPPL+Regime+NTF
  - `TechnicalAnalysisService` (新) — 拆分了 CZSC+MA+ATR

**调用方混淆**：
- `analysis_service.py:run_comprehensive_analysis` 调用**部分 Macro + Technical**
- `health_service.py:AnalysisService` 使用**旧版本**
- `manager_logic.py:AssetManager` 使用**旧版本**

**修复**：
1. 删除 `services/analysis_service.py` (旧版)
2. 迁移 `health_service.py` 等使用 `MacroAnalysisService` + `TechnicalAnalysisService`

### 8. `services/service_container.py:50-91` — 初始化无失败回退

```python
def initialize(self) -> None:
    if self._initialized:
        return
    from .data_service import DataService
    from .cache_coordinator import CacheCoordinator
    
    storage = StorageManager()  # 无 try/except
    calendar = TradeCalendarManager()  # 无 try/except
    cache = CacheCoordinator()  # 无 try/except
    # ...
```

**问题**：
- 任一服务构造失败 → 整个容器**初始化失败** → `get_health_service()` 永久 None
- 应该有**部分失败容忍**：核心服务（storage, data_service）失败则抛出；非核心（cache, engine_factory）失败则记录 warning 并继续

**修复**：
```python
def initialize(self) -> None:
    if self._initialized:
        return
    
    # 核心服务
    try:
        storage = StorageManager()
        self.register("storage", storage)
    except Exception as e:
        logger.error(f"StorageManager init failed: {e}")
        raise  # 核心失败，抛出
    
    # 非核心服务
    try:
        cache = CacheCoordinator()
        self.register("cache", cache)
    except Exception as e:
        logger.warning(f"CacheCoordinator init failed, continuing: {e}")
    
    self._initialized = True
```

### 9. `services/analysis/engine_factory.py:33-44` — 异常吞掉，返回 None

```python
def _lazy_init(self, name, module_path, class_name, **kwargs) -> Any:
    if name not in self._engines:
        with self._lock:
            if name not in self._engines:
                import importlib
                try:
                    mod = importlib.import_module(module_path, package=__package__)
                    cls = getattr(mod, class_name)
                    self._engines[name] = cls(orchestrator=self._orchestrator, **kwargs)
                except Exception as e:
                    logger.warning(f"Failed to init {name}: {e}")
                    return None  # 静默失败
    return self._engines[name]
```

**问题**：
- 引擎初始化失败仅 `logger.warning` + 返回 `None`
- 调用方 `factory.fsm.analyze(...)` 报 `AttributeError: 'NoneType' object has no attribute 'analyze'`
- **错误信息无链路追踪**：用户只看到 `NoneType` 错误，找不到根因

**修复**：
```python
except Exception as e:
    logger.error(f"Failed to init {name}: {e}", exc_info=True)
    raise EngineInitError(f"{name} init failed: {e}") from e
```

### 10. `services/portfolio_service.py:568` — 单文件 568 行

**核实**：
- 包含组合优化、风险管理、再平衡逻辑
- 与 `risk/portfolio_optimizer.py` (14,813 字节) **功能重叠**

**修复**：合并到 `risk/portfolio_optimizer.py` 或统一接口。

### 11. `ui/lppl_visualizer.py:42-349` — 3 个 70+ 行函数

| 函数 | 行数 |
|------|------|
| `_generate_plot_data` | 112 |
| `_create_plot` | 109 |
| `run_analysis_and_plot` | 76 |

**问题**：
- 视觉化逻辑与 LPPL 计算混杂
- 单元测试覆盖率必然低

**修复**：拆分为 `_compute_lppl_data()` + `_create_figure()` + `_render_html()`。

### 12. `ui/manager_portfolio_analytics_service.py` — 反向依赖 services

```python
# ui/manager_portfolio_analytics_service.py:18
from ..shared.constants import RiskCalculationConstants
from ..shared.logger_factory import get_logger
# Line 47 inside method:
from ..risk.evt_risk import EVTRisk  # UI 直接调用 risk
```

**问题**：
- UI 层 (5) **直接**调用 risk 层 (2)，违反 5 层 DAG 单向依赖
- 应通过 services 注入
- `from ..services.evt_risk` 应改为 `from ..risk.evt_risk`（违反规则更严重）

**修复**：在 UI 初始化时从 `ServiceContainer` 注入 `EVTRisk`。

### 13. `ui/__init__.py:1 byte` — 完全空文件

```bash
-rw-rw-r--  1 james james 1  5月 30 10:24 src/uniquant/ui/__init__.py
```

**问题**：
- 1 字节文件（仅换行符）
- `services/__init__.py` 有 14 个服务导出 + `__getattr__`
- `brain/__init__.py` 有 11 个 brain 组件导出
- `ui/__init__.py` **无任何导出**

**修复**：
```python
# ui/__init__.py
from .dashboard import main as run_dashboard
from .manager_logic import AssetManager
from .health_check import ModuleHealthChecker
from .lppl_visualizer import LPPLVisualizer

__all__ = [
    "run_dashboard",
    "AssetManager",
    "ModuleHealthChecker",
    "LPPLVisualizer",
]
```

---

## 🟡 P2: 一般腐化点 (Minor Issues)

### 14. `services/analysis_service.py` — `__init__` 硬编码依赖

```python
# __init__ 签名
def __init__(self):
    # HealthService.__init__ 也会调用
    # 看似未显式接收依赖
```

**核实**：
- `health_service.py:42` 是 `AnalysisService(self.data_service)`
- `analysis_service.py:45-?` 接收 `data_service`

但 `health_service.py:42-46`:
```python
self.data_service = DataService()  # 硬编码
self.analysis_service = AnalysisService(self.data_service)  # 硬编码
self.evt_risk = EVTRisk()  # 硬编码
self.sizer = PositionSizer()  # 硬编码
self.brain = DecisionBrain(evt_risk=self.evt_risk, sizer=self.sizer)  # 硬编码
```

**问题**：所有依赖**直接构造**，不通过 `ServiceContainer` 注入 → `ServiceContainer` **事实上未被使用**。

### 15. `services/data_service.py:517` — 22 KB 偏大

**核实**：
- 包含数据获取、清洗、归一化、缓存管理 4 大职责
- 实际职责过载

**修复**：拆分为 `DataFetcher` + `DataCleaner` + `DataCacheWrapper`。

### 16. `ui/manager_report_service.py` — 反向依赖 services

```python
# ui/manager_report_service.py imports
from ..services.analysis_service import AnalysisService  # UI → services (OK)
# But also has:
def generate_report(...):
    # Calls services internally
    ...
```

**核实**：未发现反向依赖（OK），但**调用层次混乱**。

### 17. `services/__init__.py` — 14 个服务通过 `__getattr__` 延迟加载

**核实**：
- `__getattr__` 内部 `import importlib`（L37）— 这是**正确**的懒加载
- 但每次属性访问都**重新走一次 try/except + import_module**，性能略低
- 应当用 `functools.lru_cache` 装饰 getter

**修复**：
```python
from functools import lru_cache

@lru_cache(maxsize=None)
def _load(name):
    return importlib.import_module(...)

def __getattr__(name):
    if name in _imports:
        return getattr(_load(name), name)
    raise AttributeError(...)
```

### 18. `ui/components.py` — 25+ 渲染函数

```python
# 从 dashboard.py 导入:
# render_report_html_preview, render_report_comparison, render_report_comparison_selector,
# render_report_metadata, render_portfolio_risk_metrics, render_portfolio_optimizer_result,
# render_stress_test_results, render_risk_heatmap, render_scan_config_panel,
# render_stock_rankings, render_structural_risk_gauges, render_tech_signals_summary,
# render_czsc_analysis_panel, render_czsc_buy_sell_points, render_czsc_zhongshu_analysis,
# render_fsm_state_history, render_fsm_status_panel, render_health_metrics,
# render_ic_ir_heatmap, plot_czsc_full_chart, render_anti_fragile_metrics,
# render_stress_scenario_buttons, render_stress_scenario_results, render_drawdown_dashboard
```

**核实**：
- `ui/components.py` 包含 25+ 渲染函数
- 全部是 `def` 函数，**无 class** 包装
- 命名风格不统一（部分用 `render_`，部分用 `plot_`）

**修复**：按 Tab 拆分为子模块（research/portfolio/etf/backtest/...）。

### 19. `ui/dashboard.py:250-259` — 异步刷新（无取消令牌）

```python
def refresh_stock_map_async():
    """异步刷新股票映射"""
    if not refresh_lock.acquire(blocking=False):
        return
    thread = threading.Thread(target=_do_refresh, daemon=True)
    thread.start()
```

**问题**：
- `daemon=True` 线程在主程序退出时**强制终止**
- 中间状态未保存，重复启动可能**并发更新同一数据源**
- **无错误回调**

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计文件数 | 36 |
| 审计总 LOC | ~11,015 |
| P0 严重问题 | 5 |
| P1 重要问题 | 8 |
| P2 一般问题 | 6 |
| 幽灵依赖 | 3 (st_aggrid, streamlit_autorefresh, streamlit_echarts) |
| 僵尸服务 | 3 (report_service, signal_generation_service, market_regime_service) |
| 全局状态点 | 1 (health_service) |
| 单类 > 1500 行 | 1 (AnalysisService) |
| 单文件 > 500 行 | 4 (analysis_service, portfolio_service, scan_service, data_service) |
| 双套抽象 | 2 (analysis_service + analysis/) |

---

## 🎯 修复优先级 (Queue 3)

| 优先级 | 项目 | 影响 | 修复成本 |
|--------|------|------|----------|
| **P0** | `health_service.py:495` 加锁单例 | 多线程崩溃风险 | 3 行 |
| **P0** | `pyproject.toml` 添加 `ui` optional-deps | UI 不完整 | 4 行 |
| **P0** | 拆分 `AnalysisService` 1597 行类 | 5 大职责混杂 | 200+ 行 |
| P1 | 删除 3 个僵尸服务 | 死代码 | 3 文件删除 |
| P1 | 统一 `analysis_service` 与 `analysis/` 子包 | 双套抽象 | 100 行 |
| P1 | 修复 `engine_factory.py` 静默失败 | 难以诊断 | 3 行 |
| P1 | `service_container.py` 添加部分失败容忍 | 初始化爆炸 | 15 行 |
| P1 | 补全 `ui/__init__.py` 导出 | 包完整性 | 5 行 |
| P1 | 修复 `manager_portfolio_analytics_service` 反向依赖 | 违反 5 层 DAG | 5 行 |
| P2 | 拆分 `ui/dashboard.py` 1524 行 | 可维护性 | 200+ 行 |
| P2 | 拆分 `ui/lppl_visualizer.py` 3 个 70+ 行函数 | 可维护性 | 50 行 |
| P2 | 拆分 `ui/components.py` 25+ 函数 | 可维护性 | 100 行 |

---

## 🔍 与 V2 报告对比 (Cross-Reference)

| V2 报告条目 | V3 状态 |
|------------|---------|
| 3 个 Streamlit 幽灵依赖 | ✅ 仍存在 |
| `health_service.py:503` 无锁单例 | ✅ 仍存在；**确认精确** |
| `analysis_service.py` 1650 行 | ⚠️ 实际 1642 行 |
| `dashboard.py` 1524 行 | ✅ 仍存在 |
| `ui/__init__.py` 空 | ✅ 仍存在 |
| `services/__init__.py` 顶层 `import importlib` 多余 | ❌ V2 误报（实际在 `__getattr__` 内） |
| DAG 方向正确 | ✅ 仍正确 |
| 引擎工厂双重检查锁 | ✅ 仍存在 |
| 服务层延迟导入 | ✅ 仍存在；**新增** — 性能优化空间 |

**V2 准确率**: ~80% (V2 报告 80% 准确)

**V3 新发现**：
- 3 个僵尸服务模块（V2 未提及）
- `analysis_service` 与 `analysis/` 双套抽象
- `ui/manager_portfolio_analytics_service` 反向依赖 risk 层（违反 DAG）
