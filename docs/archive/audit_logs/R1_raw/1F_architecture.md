# R1 Architecture Audit: services/ + shared/interfaces.py

**审计员**: R1-Architecture  
**日期**: 2026-06-06  
**审计范围**: `src/uniquant/services/service_container.py`, `src/uniquant/services/analysis/engine_factory.py`, `src/uniquant/shared/interfaces.py`

---

## 审计摘要

| # | 文件 | 行号 | 严重性 | 问题 |
|---|------|------|--------|------|
| 1 | service_container.py | 37-41 | HIGH | `instance()` 单例无线程安全保护 |
| 2 | service_container.py | 77-78 | MEDIUM | `StorageManager()` / `TradeCalendarManager()` 无参调用，`data_dir` 依赖 CWD |
| 3 | service_container.py | 70-95 | HIGH | `initialize()` 无异常回滚，失败后容器处于半初始化状态 |
| 4 | engine_factory.py | 26 | MEDIUM | `importlib.import_module` 使用 `..` 相对路径 + `package=__package__`，路径解析脆弱 |
| 5 | engine_factory.py | 30-32 | HIGH | 加载失败被静默吞掉，返回 `None`，调用方无感知 |
| 6 | engine_factory.py | 64-75 | HIGH | `brain` 属性绕过 DAG，直接 import brain 层模块，无 DI 注入 |
| 7 | interfaces.py | 63 vs 147 | CRITICAL | 类型不一致：`returns` 字段为 `pd.Series`，`RiskAssessmentProtocol.calculate_metrics` 参数为 `pd.DataFrame` |
| 8 | interfaces.py | 96-116 | MEDIUM | `to_dict()` 遗漏 `returns` 字段，序列化丢失数据 |

---

## 逐项审计

### FINDING-01: ServiceContainer.instance() 线程不安全

**文件**: `src/uniquant/services/service_container.py:37-41`

```python
@classmethod
def instance(cls) -> "ServiceContainer":
    if cls._instance is None:
        cls._instance = cls()
    return cls._instance
```

**问题**: 经典的 check-then-act 竞态条件。两个线程同时检查 `cls._instance is None`，可能各自创建一个实例，导致单例语义被破坏。

**证据**:
- `AnalysisEngineFactory` 内部使用了 `threading.RLock()` (engine_factory.py:18)，说明项目存在多线程场景
- `ServiceContainer` 本身没有任何锁机制

**影响**: HIGH — 多线程环境下可能产生多个独立的 ServiceContainer 实例，导致服务注册表不一致、重复初始化资源

**修复建议**:
```python
import threading

class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None
    _lock = threading.Lock()  # 类级锁

    @classmethod
    def instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # Double-checked locking
                    cls._instance = cls()
        return cls._instance
```

---

### FINDING-02: StorageManager() 无参调用 — data_dir 依赖 CWD

**文件**: `src/uniquant/services/service_container.py:77-78`

```python
storage = StorageManager()
calendar = TradeCalendarManager()
```

**交叉验证** (`src/uniquant/data/lake/storage_manager.py:22`):
```python
def __init__(self, data_dir: str = "./data"):
```

**交叉验证** (`src/uniquant/data/managers/trade_calendar_manager.py:57`):
```python
def __init__(self, data_dir: str = "./data"):
```

**问题**: 两个管理器都使用 `data_dir="./data"` 作为默认值，这是**相对路径**。实际解析结果取决于 Python 进程的 CWD（当前工作目录）：
- 从项目根目录运行 → `./data` 正确
- 从 `src/` 或其他子目录运行 → `./data` 指向错误位置
- Streamlit dashboard 运行时 CWD 可能与 CLI 不同

此外，`StorageManager.__init__` 会在初始化时立即创建 6 个子目录（`lake/quotes/daily` 等，storage_manager.py:41-46），且调用 `_load_all_stock_codes()` (storage_manager.py:48)，这是一个有副作用的重量级构造函数调用。

**影响**: MEDIUM — 部署环境或 IDE 调试时可能写入错误位置

**修复建议**: `ServiceContainer.initialize()` 应从配置读取 `data_dir`，显式传入：
```python
from ..shared.config_loader import get_config
config = get_config()
data_dir = config.get("base.data_lake.path", "./data")
storage = StorageManager(data_dir=data_dir)
calendar = TradeCalendarManager(data_dir=data_dir)
```

---

### FINDING-03: initialize() 无异常回滚

**文件**: `src/uniquant/services/service_container.py:70-95`

```python
def initialize(self) -> None:
    if self._initialized:
        return

    storage = StorageManager()
    calendar = TradeCalendarManager()
    cache = CacheCoordinator()

    data_svc = DataService(storage_manager=storage)
    self.register("storage", storage)
    self.register("calendar", calendar)
    self.register("cache", cache)
    self.register("data_service", data_svc)

    engine_factory = AnalysisEngineFactory(orchestrator=data_svc)
    self.register("engine_factory", engine_factory)

    self._initialized = True
```

**问题**: 存在多个失败点，但没有任何异常处理或回滚逻辑：

1. **StorageManager() 失败**（如权限问题创建目录失败）→ 后续服务全部未注册，但 `_initialized` 仍为 `False`，可以重试。这部分尚可接受。

2. **DataService() 失败** → `storage`、`calendar`、`cache` 已注册但 `data_svc` 未注册，`_initialized` 为 `False`。容器处于**半初始化状态**。下次调用 `initialize()` 会重新尝试（因 `_initialized` 为 `False`），但已注册的 `storage` 等不会被清理。

3. **AnalysisEngineFactory() 失败** → 前 4 个服务已注册，`engine_factory` 未注册，`_initialized` 为 `False`。容器半初始化。

4. **任何步骤中抛出非预期异常** → `self.register()` 可能已部分执行，容器内残留部分服务。

**关键缺陷**: 没有 try/except 包裹，没有 try/finally 清理。虽然 `_initialized` 未设为 `True` 意味着重试是可能的，但已注册的服务不会被清理，可能导致新旧实例混合。

**影响**: HIGH — 初始化部分失败后，容器状态不一致，后续 `get()` 可能返回部分有效部分无效的服务

**修复建议**:
```python
def initialize(self) -> None:
    if self._initialized:
        return
    try:
        storage = StorageManager(data_dir=data_dir)
        # ... 所有初始化步骤
        self._initialized = True
    except Exception as e:
        logger.error(f"ServiceContainer initialization failed: {e}")
        self.clear()  # 回滚所有已注册的服务
        raise
```

---

### FINDING-04: importlib 相对路径解析脆弱

**文件**: `src/uniquant/services/analysis/engine_factory.py:20-28`

```python
def _lazy_init(self, name: str, module_path: str, class_name: str, **kwargs) -> Any:
    # ...
    import importlib
    mod = importlib.import_module(module_path, package=__package__)
```

调用示例 (engine_factory.py:37):
```python
return self._lazy_init("fsm", "..analysis.fsm_analysis_engine", "FsmAnalysisEngine")
```

**问题**: `__package__` 的值为 `uniquant.services.analysis`。`importlib.import_module("..analysis.fsm_analysis_engine", package="uniquant.services.analysis")` 的解析过程：
- `..` 从 `uniquant.services.analysis` 向上到 `uniquant.services`
- 然后进入 `analysis.fsm_analysis_engine`
- 最终路径: `uniquant.services.analysis.fsm_analysis_engine`

这个解析**恰好正确**，但非常脆弱：
- 如果 `engine_factory.py` 移动到不同层级的包，所有 `..` 路径都会断裂
- 如果包结构重命名（如 `services/analysis/` 变为 `services/engines/`），路径全部失效
- 错误信息不直观（`ModuleNotFoundError` 不会显示相对路径的解析结果）

**影响**: MEDIUM — 维护成本高，重构时容易引入隐蔽 bug

**修复建议**: 使用绝对路径或在模块顶部集中注册引擎路径：
```python
ENGINE_REGISTRY = {
    "fsm": ("uniquant.services.analysis.fsm_analysis_engine", "FsmAnalysisEngine"),
    "czsc": ("uniquant.services.analysis.czsc_analysis_engine", "CzscAnalysisEngine"),
    # ...
}
```

---

### FINDING-05: 引擎加载失败被静默吞掉

**文件**: `src/uniquant/services/analysis/engine_factory.py:30-32`

```python
except Exception as e:
    logger.warning(f"Failed to init {name}: {e}")
    return None
```

**问题**: `importlib.import_module` 或 `getattr` 失败时，仅记录 warning 日志并返回 `None`。调用方完全不知道引擎不可用。

**影响链**:
1. `AnalysisEngineFactory.fsm` 返回 `None`
2. 上层代码调用 `factory.fsm.analyze(...)` → `AttributeError: 'NoneType' object has no attribute 'analyze'`
3. 错误信息完全丢失了原始的 `ImportError` 上下文
4. 所有 9 个引擎（fsm, czsc, lppl, regime, ntf, macro, report, wyckoff, brain）都存在此问题

**影响**: HIGH — 引擎缺失时错误信息不透明，难以定位问题根因

**修复建议**:
- 方案 A: 返回一个 `NullEngine` 代理对象，实现 `AnalysisEngineProtocol`，在 `analyze()` 中抛出明确异常
- 方案 B: 在 `initialize()` 时预检所有引擎可用性，失败则拒绝启动

---

### FINDING-06: brain 属性绕过 DAG 层级

**文件**: `src/uniquant/services/analysis/engine_factory.py:64-75`

```python
@property
def brain(self):
    if "brain" not in self._engines:
        with self._lock:
            if "brain" not in self._engines:
                try:
                    from ...brain.fsm import DecisionBrain
                    self._engines["brain"] = DecisionBrain()
                    logger.debug("Lazy-initialized brain")
                except Exception as e:
                    logger.warning(f"Failed to init brain: {e}")
                    return None
    return self._engines["brain"]
```

**问题**:

1. **DAG 违反**: 项目架构约定 `shared → data → brain/risk/signal → hands → services → ui`。`services` 层的 `AnalysisEngineFactory` 直接 import `brain` 层的 `DecisionBrain`，这是**上层依赖下层的反向调用**（`services` → `brain`）。虽然在 DAG 中 `brain` 应该低于 `services`，但这里 `services` 直接构造 `brain` 层对象而非通过 DI 注入。

2. **无参构造**: `DecisionBrain()` 无参数调用。如果 `DecisionBrain` 未来需要依赖（如配置、数据源），这里无法注入。

3. **与其他引擎不一致**: 所有其他引擎通过 `_lazy_init()` 加载（使用 `importlib`），但 `brain` 使用硬编码的直接 import。这违反了单一职责原则。

4. **与 `service_container.py` 不一致**: `service_container.py:89-91` 已经为 `AnalysisEngineFactory` 注入了 `orchestrator=data_svc`，但 `brain` 属性完全忽略了这个 orchestrator，自行构造。

**影响**: HIGH — 架构违规，维护混乱，未来重构困难

**修复建议**: 将 `DecisionBrain` 的注册移入 `ServiceContainer.initialize()`，通过工厂注入：
```python
from ..brain.fsm import DecisionBrain
brain = DecisionBrain(orchestrator=data_svc)
self.register("brain", brain)
engine_factory = AnalysisEngineFactory(orchestrator=data_svc, brain=brain)
```

---

### FINDING-07: returns 类型不一致 — Series vs DataFrame

**文件**: `src/uniquant/shared/interfaces.py:63` vs `interfaces.py:147`

```python
# Line 63: MarketSignalContext 数据类
returns: Optional[pd.Series] = None

# Line 147: RiskAssessmentProtocol 协议
def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]:
```

**问题**: `MarketSignalContext.returns` 的类型是 `Optional[pd.Series]`，但 `RiskAssessmentProtocol.calculate_metrics` 的 `returns` 参数类型是 `pd.DataFrame`。这意味着：
- 如果将 `MarketSignalContext.returns` 传给 `calculate_metrics()`，类型不匹配
- 如果 `calculate_metrics()` 返回的结果需要关联到 `MarketSignalContext`，类型也不兼容
- 静态类型检查器（mypy）会标记此不一致

**影响**: CRITICAL — 运行时可能抛出 `TypeError` 或 `AttributeError`（Series 没有 DataFrame 的方法）

**修复建议**: 统一类型。根据实际使用场景决定用哪个：
```python
# 方案 A: 统一为 DataFrame（推荐，DataFrame 是多列收益率的标准容器）
returns: Optional[pd.DataFrame] = None

# 方案 B: 统一为 Series（如果确实只有单列收益率）
def calculate_metrics(self, returns: pd.Series) -> Dict[str, Any]:
```

---

### FINDING-08: to_dict() 遗漏 returns 字段

**文件**: `src/uniquant/shared/interfaces.py:96-116`

```python
def to_dict(self) -> Dict[str, Any]:
    return {
        "regime": self.regime.value,
        "risk": self.risk,
        "bubble_confidence": self.bubble_confidence,
        "ntf_side": self.ntf_side.value,
        "ntf_intensity": self.ntf_intensity,
        "is_3rd_buy": self.is_3rd_buy,
        "bi_count": self.bi_count,
        "alpha_score": self.alpha_score,
        "ma_status": self.ma_status,
        "price": self.price,
        "pre_close": self.pre_close,
        "symbol": self.symbol,
        "name": self.name,
        "atr_stop": self.atr_stop,
        "czsc_bottom": self.czsc_bottom,
        "market": self.market,
        "lppl_days_to_tc": self.lppl_days_to_tc,
    }
```

**对比 `from_dict()`** (lines 67-94): `from_dict()` 从字典中读取 `returns`：
```python
returns=data.get("returns"),
```

**对比 dataclass 字段** (line 63):
```python
returns: Optional[pd.Series] = None
```

**问题**: `to_dict()` 输出的字典中**没有 `returns` 键**。这导致：
- `from_dict(ctx.to_dict())` 无法恢复 `returns` 字段 — **序列化/反序列化不对称**
- 通过字典传递 `MarketSignalContext` 时，`returns` 数据丢失
- 调试时 `to_dict()` 输出不完整

**注意**: 这可能是有意的（避免序列化大型 Series 对象），但如果是有意的，应在文档中说明，且 `from_dict()` 不应从字典中读取它。

**影响**: MEDIUM — 数据丢失，序列化/反序列化不对称

**修复建议**:
```python
def to_dict(self) -> Dict[str, Any]:
    d = {
        "regime": self.regime.value,
        # ... 所有其他字段
        "lppl_days_to_tc": self.lppl_days_to_tc,
    }
    if self.returns is not None:
        d["returns"] = self.returns  # 或 self.returns.to_dict() 如果需要可序列化
    return d
```

---

## 架构层级依赖关系审计

基于代码实际分析，当前 DAG 拓扑的合规性：

```
shared          ← 无外部依赖 ✅
   ↓
data            ← 依赖 shared, 第三方库 ✅
   ↓
brain/risk      ← 依赖 shared, data ✅
   ↓
services        ← 依赖 shared, data ⚠️ (FINDING-06: 直接 import brain 层)
   ↓
ui              ← 依赖 services, shared ✅
```

**关键违规**: `services/analysis/engine_factory.py:69` 的 `from ...brain.fsm import DecisionBrain` 打破了 `services` → `brain` 的单向依赖约定。虽然在 DAG 中 `brain` 是 `services` 的下层，但这里 `services` **主动构造** `brain` 对象而非接受注入，形成了隐式的双向耦合。

---

## 风险矩阵

| 严重性 | 数量 | 发现 |
|--------|------|------|
| CRITICAL | 1 | FINDING-07 (类型不一致) |
| HIGH | 4 | FINDING-01, 03, 05, 06 |
| MEDIUM | 3 | FINDING-02, 04, 08 |

**最优先修复**: FINDING-07 (CRITICAL) > FINDING-01 (HIGH, 线程安全) > FINDING-05 (HIGH, 错误吞噬) > FINDING-03 (HIGH, 无回滚)

---

## 附录: 文件行数统计

| 文件 | 总行数 | 审计覆盖行数 |
|------|--------|-------------|
| service_container.py | 95 | 95 (100%) |
| engine_factory.py | 79 | 79 (100%) |
| interfaces.py | 319 | 150 (47%) |

*审计完成时间: 2026-06-06*
