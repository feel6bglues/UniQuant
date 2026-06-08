# R2-C: Architecture vs All — 跨域对抗审计

**审计员**: R2-C (Cross-Domain Auditor)
**日期**: 2026-06-06
**审计类型**: Architecture ↔ Data I/O / Brain / Services 跨域交叉验证
**输入**: R1-1F (Architecture), R1-1A (Data I/O), 源码全量交叉检查

---

## 审计摘要

| # | 严重性 | 发现 | 跨域路径 |
|---|--------|------|----------|
| 1 | CRITICAL | StorageManager 实例爆炸 — 最少 7 个独立实例 | Architecture → Data I/O → Brain |
| 2 | CRITICAL | 引擎缓存无过期/刷新机制 — CZSC 跨股票状态污染 | Architecture → Brain |
| 3 | HIGH | 引擎生命周期无管理 — 无 dispose/destroy/cleanup | Architecture → Services |
| 4 | HIGH | DecisionBrain 状态在多股票分析间泄漏 | Brain → Architecture → Services |
| 5 | HIGH | AnalysisService 内部绕过 Factory 直接 new StorageManager/DataFetcher | Architecture → Services |
| 6 | HIGH | AnalysisEngineFactory brain 属性绕过 DAG + 无 orchestrator 注入 | Architecture → Brain |
| 7 | HIGH | 引擎加载失败静默吞掉 — 下游 NoneType 链式崩溃 | Architecture → All |
| 8 | MEDIUM | 依赖注入树无循环依赖，但存在隐式双向耦合 | Architecture (结构) |
| 9 | MEDIUM | ServiceContainer 初始化无回滚 — 半初始化状态残留 | Architecture (内部) |
| 10 | MEDIUM | LPPL/Wyckoff 引擎每次调用都 new 一个临时 brain 实例 | Services → Brain |

---

## 逐项审计

### CROSS-01 [CRITICAL]: StorageManager 实例爆炸 — 最少 7 个独立实例

**跨域路径**: `service_container.py` → `data_fetcher.py` → `data_service.py` → `analysis_service.py` → `lppl_data_service.py` → `data/manager.py` → `lppl_analysis_engine.py`

**证据汇总**:

| # | 位置 | 代码 | 语境 |
|---|------|------|------|
| 1 | `service_container.py:77` | `StorageManager()` | ServiceContainer.initialize() |
| 2 | `data_fetcher.py:67` | `StorageManager(data_dir)` | DataFetcher 构造函数 |
| 3 | `data_service.py:66` | `StorageManager()` | DataService 降级 fallback |
| 4 | `analysis_service.py:931` | `StorageManager()` | _run_alpha_analysis() 内部 |
| 5 | `lppl_data_service.py:22` | `StorageManager()` | LPPLDataService 构造函数 |
| 6 | `data/manager.py:9` | `StorageManager()` | DataManager 构造函数 |
| 7 | `data_pipeline_service.py:235` (R1-1A 证据) | `StorageManager(data_dir)` | DataPipelineService 构造函数 |

**实例链追踪**:

```
ServiceContainer.initialize()
  ├─ StorageManager()           ← 实例 #1
  └─ DataService(storage_manager=#1)
       ├─ DataFetcher()         ← 内部 new StorageManager() → 实例 #2
       ├─ StorageManager()      ← fallback → 实例 #3
       └─ CacheCoordinator()

AnalysisService.__init__(data_service=DataService)
  └─ _run_alpha_analysis()
       └─ StorageManager()      ← 实例 #4 (每次调用都 new!)

LPPLDataService()
  ├─ DataFetcher()              ← 内部 new StorageManager() → 实例 #5
  └─ StorageManager()           ← 实例 #6

DataManager()
  └─ StorageManager()           ← 实例 #7
```

**问题**:
- 每个 `StorageManager()` 构造函数执行 6 次 `mkdir`（storage_manager.py:41-46）和 1 次 `_load_all_stock_codes()`（storage_manager.py:48），这是一个读 CSV + 标准化全市场代码的重量级操作
- 7 个实例各自维护独立的 `all_stock_codes` 集合（set），修改一个不影响其他
- `read_local_raw()` 有 6 种文件名格式的 I/O 放大（R1-1A MEDIUM），7 个实例 × 6 次尝试 = 最坏 42 次文件系统检查/股票
- 并发写入同一文件时，不同实例的 `FileLock` 路径相同但实例不同，可能导致锁竞争异常

**影响**: CRITICAL — 资源浪费（7 次 mkdir × 6 = 42 次系统调用，7 次读 CSV），内存膨胀（7 × all_stock_codes set），潜在并发写入冲突

**修复建议**:
```python
# 1. StorageManager 改为单例或由 ServiceContainer 统一管理
class StorageManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, data_dir="./data"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once(data_dir)
            return cls._instance

# 2. 或更优：ServiceContainer 传递共享实例
# 禁止任何位置使用 StorageManager() 无参构造
```

---

### CROSS-02 [CRITICAL]: 引擎缓存无过期/刷新机制 — CZSC 跨股票状态污染

**跨域路径**: `AnalysisEngineFactory._engines` → `CZSCEngine.analyzer` → `DecisionBrain.state`

**证据**:

**CZSCEngine 内部状态** (czsc_engine.py:94-96):
```python
def __init__(self):
    self.analyzer = None
    self._current_symbol: str = ""
    self._analysis_coverage = 0.0
```

**CZSCEngine 跨股票检测** (czsc_engine.py:183-186):
```python
# Reset analyzer when symbol changes to prevent cross-stock state pollution
if symbol and symbol != self._current_symbol:
    self.analyzer = None
    self._current_symbol = symbol
```

**关键发现**: `CZSCEngine` 在 `update_and_get_signals()` 中有跨股票重置逻辑，但这个保护**仅存在于增量接口**。分析完整数据的 `get_czsc_signals()` (czsc_engine.py:470) 创建了局部 `analyzer`，不污染全局状态。但是：

**问题 1**: `CzscAnalysisEngine` (services 层) 在 `run_czsc_analysis()` 中**每次调用都 new 一个新的 `CZSCEngine()`** (czsc_analysis_engine.py:69):
```python
czsc_engine = CZSCEngine()
result = czsc_engine.get_czsc_signals(df)
```
这意味着 brain 层的跨股票保护**永远不会被触发**，因为每次都是全新实例。这实际上是正确的（无状态），但造成了设计矛盾：brain 层实现了复杂的状态管理，但 services 层每次都绕过它。

**问题 2**: `AnalysisEngineFactory._engines` 是一个永不释放的字典缓存:
```python
self._engines: Dict[str, Any] = {}
# 引擎被缓存后永远不会被清除或替换
```
引擎实例被创建后就永远驻留在 `_engines` 中。没有：
- TTL 过期机制
- 手动刷新接口
- 内存回收策略
- LRU 淘汰

对于无状态引擎（如 `CzscAnalysisEngine` 适配器）这不是问题，但对于持有内部状态的引擎（如通过 Factory 缓存的 brain）会累积状态。

**问题 3**: `DecisionBrain` 有**持久化状态**（fsm.py:206-208, 640-691）:
```python
self.state = FSMState.IDLE
self._previous_state = FSMState.IDLE
self._persist_state = persist_state
```
DecisionBrain 将 FSM 状态持久化到磁盘（`fsm_state.json`），并从磁盘恢复。当 `AnalysisEngineFactory.brain` 属性缓存了 DecisionBrain 实例后：
- 分析股票 A 后 state 变为 `MONITOR`
- 分析股票 B 时，DecisionBrain 从 `MONITOR` 开始，而非 `IDLE`
- 跨股票状态污染通过 FSM 状态机传播

**影响**: CRITICAL — DecisionBrain 状态在股票间泄漏，可能导致错误的买卖决策

**修复建议**:
```python
# 1. AnalysisEngineFactory 添加引擎生命周期管理
def invalidate(self, name: str = None):
    """清除缓存的引擎实例，下次访问时重新创建"""
    with self._lock:
        if name:
            self._engines.pop(name, None)
        else:
            self._engines.clear()

# 2. DecisionBrain.make_decision() 应接受 symbol 参数并重置
def make_decision(self, data_packet, symbol: str = ""):
    if symbol != self._last_symbol:
        self.state = FSMState.IDLE  # 跨股票时重置
        self._last_symbol = symbol
```

---

### CROSS-03 [HIGH]: 引擎生命周期无管理 — 无 dispose/destroy/cleanup

**跨域路径**: `AnalysisEngineFactory._engines` → 所有引擎 → brain 层资源

**证据**:

`AnalysisEngineFactory` (engine_factory.py):
```python
class AnalysisEngineFactory:
    def __init__(self, orchestrator):
        self._engines: Dict[str, Any] = {}  # 引擎缓存

    # 只有创建，没有销毁
    # 没有 close() / dispose() / destroy() / __del__ 方法
```

`ServiceContainer.reset()` (service_container.py:61-63):
```python
def reset(self) -> None:
    self._services.clear()
    self._initialized = False
    # 注意: 不清理 AnalysisEngineFactory._engines
```

`ServiceContainer.clear()` (service_container.py:65-68):
```python
def clear(self) -> None:
    self._services.clear()
    self._factories.clear()
    self._registrations.clear()
    # 不调用 engine_factory.dispose()，引擎资源泄漏
```

**引擎实例持有的资源**:
- `DecisionBrain`: 持有 `evt_risk`, `sizer`, `_state_history` 列表, 文件锁
- `CzscAnalysisEngine`(services 适配器): 持有 `orchestrator` 引用（形成引用链）
- `MacroAnalysisEngine`: 持有 `orchestrator` 引用
- 所有引擎: 持有 `orchestrator` 引用，形成到 `AnalysisService` → `DataService` → `DataFetcher` → `StorageManager` 的完整引用链

**生命周期问题**:
1. 引擎被创建后永不释放 → 内存持续增长
2. `ServiceContainer.reset()` 清除服务注册但不清除引擎实例 → 引擎引用已清除的服务 → `AttributeError`
3. 无 `__del__` 方法 → Python GC 回收时无清理逻辑
4. 引擎持有 orchestrator 引用 → 即使 orchestrator 被替换，旧引擎仍持有旧引用

**影响**: HIGH — 长时间运行的 Streamlit dashboard 内存持续增长；reset 后引擎引用失效的中间状态

**修复建议**:
```python
class AnalysisEngineFactory:
    def dispose(self):
        """清理所有引擎资源"""
        with self._lock:
            for name, engine in self._engines.items():
                if hasattr(engine, 'dispose'):
                    engine.dispose()
            self._engines.clear()
    
    def invalidate(self, name: str = None):
        """使指定引擎失效，下次访问时重建"""
        with self._lock:
            if name:
                self._engines.pop(name, None)
            else:
                self._engines.clear()
```

---

### CROSS-04 [HIGH]: DecisionBrain 状态在多股票分析间泄漏

**跨域路径**: `AnalysisService._make_decision()` → `DecisionBrain.make_decision()` → `self.state`

**证据**:

`AnalysisService._make_decision()` (analysis_service.py:1057-1063):
```python
def _make_decision(self, ticker: str, data_pack: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return self.brain.make_decision(data_pack)
    except RECOVERABLE_ERRORS as e:
        logger.error(f"{ticker} 决策计算失败: {e}")
        return None
```

`DecisionBrain.make_decision()` (fsm.py:496-596):
```python
def make_decision(self, data_packet):
    # self.state 在整个调用间持久化!
    self._previous_state = self.state
    # ... 状态转换逻辑 ...
    if target_state != self.state:
        self.state = target_state
```

**跨股票泄漏路径**:
1. `analyze_ticker("600519")` → DecisionBrain state 变为 `MONITOR`
2. `analyze_ticker("000858")` → DecisionBrain 从 `MONITOR` 开始判断
3. 如果 000858 应该是 `IDLE`（无买入信号），但 state 已是 `MONITOR`，FSM 逻辑会认为已在持有状态，可能触发 `PYRAMID` 或 `EXIT` 而非 `SIGNAL`

**具体影响路径** (fsm.py:318-333):
```python
def _determine_target_state(self, score, is_3rd_buy):
    if self.state == FSMState.IDLE:
        # 新股票应该从这里开始
        ...
    elif self.state == FSMState.MONITOR:
        # 但前一只股票的状态残留导致从这里判断!
        if score >= SCORE_THRESHOLD_TO_PYRAMID:
            return FSMState.PYRAMID  # 错误地建议加仓
        if score < SCORE_THRESHOLD_EXIT:
            return FSMState.EXIT     # 错误地建议卖出
```

**影响**: HIGH — 多股票批量分析时，后面的股票会受到前面股票的 FSM 状态影响，产生错误的交易信号

**修复建议**:
```python
def make_decision(self, data_packet, reset_state: bool = False):
    if reset_state:
        self.state = FSMState.IDLE
        self._previous_state = FSMState.IDLE
    # ...
```
或在 `AnalysisService.analyze_ticker()` 调用前重置。

---

### CROSS-05 [HIGH]: AnalysisService 内部绕过 Factory 直接 new 实例

**跨域路径**: `AnalysisService._run_ntf_detection()` → `DataFetcher()`, `StorageManager()`

**证据**:

`analysis_service.py:860-862`:
```python
def _run_ntf_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
    from ..brain.ntf.ntf_engine import NTFEngine
    from ..data.data_fetcher import DataFetcher
    fetcher = DataFetcher()  # 绕过 DI，直接 new!
```

`analysis_service.py:931`:
```python
def _run_alpha_analysis(self, data_pack: Dict[str, Any]) -> None:
    storage = StorageManager()  # 绕过 DI，直接 new!
```

**问题**: `AnalysisService` 持有 `self.data_service` (通过 DI 注入)，但 `_run_ntf_detection()` 和 `_run_alpha_analysis()` 完全忽略已注入的 `data_service`，自行创建新的 `DataFetcher()` 和 `StorageManager()`。

这导致:
1. NTF 分析使用独立的 DataFetcher → 独立的 StorageManager → 独立的 all_stock_codes
2. Alpha 分析使用独立的 StorageManager → 独立的文件句柄
3. DI 容器注入的实例被浪费

**对比**: `_run_regime_detection()` (analysis_service.py:808) 正确使用了 `self.data_service.lake.read_data()`

**影响**: HIGH — DI 架构被破坏，实例管理失控，潜在的数据不一致

**修复建议**:
```python
def _run_ntf_detection(self, ticker: str, data_pack):
    ntf_engine = NTFEngine()
    # 使用已注入的 data_service 而非 new DataFetcher()
    df = self.data_service.fetcher.fetch_index_daily(...)
    ntf_result = ntf_engine.detect_intervention_from_data(self.data_service.fetcher, ...)

def _run_alpha_analysis(self, data_pack):
    # 使用已注入的 storage_manager 而非 new StorageManager()
    bench_df = self.data_service.lake.read_data("000300.SH", "index")
```

---

### CROSS-06 [HIGH]: AnalysisEngineFactory brain 属性绕过 DAG + 无 orchestrator 注入

**跨域路径**: `engine_factory.py:69` → `brain.fsm.DecisionBrain` (无 orchestrator)

**证据**:

`engine_factory.py:64-75`:
```python
@property
def brain(self):
    if "brain" not in self._engines:
        with self._lock:
            if "brain" not in self._engines:
                try:
                    from ...brain.fsm import DecisionBrain
                    self._engines["brain"] = DecisionBrain()  # 无参构造!
                    # 其他所有引擎都接收 orchestrator=self._orchestrator
                    # 但 brain 被特殊对待
```

对比其他引擎:
```python
# 所有其他引擎都通过 _lazy_init 创建:
self._engines[name] = cls(orchestrator=self._orchestrator, **kwargs)
# 但 brain 不走这条路
```

**DAG 违反**: `services.analysis.engine_factory` 直接 import `brain.fsm.DecisionBrain`，形成了 `services → brain` 的反向依赖。虽然 `brain` 在 DAG 中位于 `services` 下层，但通过 DI 注入应是 `services` 接收 brain 实例，而非主动构造。

**orchestrator 缺失**: `DecisionBrain()` 无参构造忽略了 `AnalysisEngineFactory` 持有的 `orchestrator`（即 `AnalysisService`）。其他引擎都能通过 `orchestrator` 访问 `data_service`、缓存等共享资源，但 `brain` 无法访问。

**对比 `AnalysisService.brain`** (analysis_service.py:113-115):
```python
@property
def brain(self):
    return self._factory.brain  # 直接委托给 Factory
```

这意味着 `AnalysisService.brain` 返回的 DecisionBrain 也没有 orchestrator 引用。

**影响**: HIGH — 架构违规，brain 无法访问共享服务，维护困难

**修复建议**:
```python
# ServiceContainer.initialize() 中:
brain = DecisionBrain(orchestrator=data_svc)
self.register("brain", brain)

# AnalysisEngineFactory 接受 brain 参数:
engine_factory = AnalysisEngineFactory(orchestrator=data_svc, brain=brain)
```

---

### CROSS-07 [HIGH]: 引擎加载失败静默吞掉 — 下游 NoneType 链式崩溃

**跨域路径**: `engine_factory.py:30-32` → 所有引擎属性 → `AnalysisService.*_engine` → 调用方

**证据**:

`engine_factory.py:30-32`:
```python
except Exception as e:
    logger.warning(f"Failed to init {name}: {e}")
    return None  # 静默返回 None
```

**崩溃链追踪**:
```
1. engine_factory.fsm → _lazy_init() 失败 → return None
2. AnalysisService.fsm_engine → self._factory.fsm → None
3. AnalysisService._run_engine_analysis() 中:
   - _run_regime_detection() → RegimeDetector() 独立创建，不走 Factory
   - _run_lppl_detection() → self.lppl_engine.run_lppl_analysis() → None.run_lppl_analysis() → AttributeError
   - _run_czsc_detection() → self.czsc_engine.run_czsc_analysis() → None.run_czsc_analysis() → AttributeError
```

所有 9 个引擎（fsm, czsc, lppl, regime, ntf, macro, report, wyckoff, brain）都受此影响。加载失败时：
1. 只有 warning 日志
2. 返回 None
3. 调用方尝试调用 None 的方法 → `AttributeError: 'NoneType' object has no attribute 'xxx'`
4. 错误信息完全丢失了原始的 `ImportError` 上下文

**影响**: HIGH — 引擎缺失时难以定位根因，错误信息链断裂

**修复建议**:
```python
# NullEngine 代理模式
class NullEngine:
    def __getattr__(self, name):
        def _null_method(*args, **kwargs):
            raise RuntimeError(f"Engine not available: {name}")
        return _null_method
```

---

### CROSS-08 [MEDIUM]: 依赖注入树无循环依赖，但存在隐式双向耦合

**分析范围**: ServiceContainer → DataService → AnalysisService → AnalysisEngineFactory → brain 层

**依赖树验证**:

```
ServiceContainer (DAG root)
  ├─ StorageManager          [data layer]
  ├─ TradeCalendarManager    [data layer]
  ├─ CacheCoordinator        [services layer]
  ├─ DataService             [services layer]
  │    ├─ DataFetcher        [data layer]  ← 注意: DataService 构造函数中 new DataFetcher()
  │    ├─ StorageManager     [data layer]  ← 注意: DataService fallback new StorageManager()
  │    └─ CacheCoordinator   [services layer]
  └─ AnalysisEngineFactory   [services layer]
       ├─ FsmAnalysisEngine  [services layer]
       ├─ CzscAnalysisEngine [services layer]
       ├─ ... (7 more engines)
       └─ brain 属性 → DecisionBrain [brain layer] ← DAG 违规
```

**循环依赖分析**:
- ServiceContainer → DataService → DataFetcher → StorageManager: 无循环 ✅
- ServiceContainer → AnalysisEngineFactory → 各引擎 → orchestrator(AnalysisService): **隐式循环** ⚠️
  - AnalysisEngineFactory 接收 `orchestrator=data_svc` (DataService)
  - 各引擎的 `orchestrator` 被设为 DataService
  - 但 AnalysisService._run_czsc_detection() 中 CZSC 引擎访问 `self.orchestrator.data_service.lake` — 如果 orchestrator 是 DataService 则 `data_service.lake` 是 `StorageManager`，这恰好正确
  - 但如果 orchestrator 被替换为 AnalysisService (analysis_service.py:76)，则 `self.orchestrator.data_service` 是 DataService，`lake` 是 StorageManager — 也是正确的
  - **无运行时循环依赖**，但设计上 orchestrator 的类型不明确（可能是 DataService 也可能是 AnalysisService）

**隐式双向耦合**:
- `services.analysis.engine_factory` import `brain.fsm` → `services → brain` (DAG 违规)
- `services.analysis_service` import `brain.regime.regime_detector` → `services → brain` (DAG 违规)
- `services.analysis_service` import `brain.ntf.ntf_engine` → `services → brain` (DAG 违规)
- `services.analysis_service` import `brain.alpha_decoupler` → `services → brain` (DAG 违规)

**结论**: 无直接循环依赖（没有模块 A import B 且 B import A），但 `services` 层大量主动 import `brain` 层模块，形成了隐式的双向耦合。DAG 文档约定 `services → brain` 是允许的（上层依赖下层），但实际代码中是 `services 主动构造 brain 对象`，而非 `services 接收 brain 注入`。

**影响**: MEDIUM — 架构文档与实际代码不一致，重构时容易引入真正的循环依赖

---

### CROSS-09 [MEDIUM]: ServiceContainer 初始化无回滚 — 半初始化状态残留

**证据**:

`service_container.py:70-94`:
```python
def initialize(self) -> None:
    if self._initialized:
        return
    # 无 try/except!
    storage = StorageManager()       # 可能失败
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

**失败场景分析**:

| 步骤 | 失败 | 已注册 | 未注册 | _initialized | 后果 |
|------|------|--------|--------|-------------|------|
| StorageManager() | 目录权限 | 无 | 全部 | False | 可重试 ✅ |
| DataService() | 导入失败 | storage, calendar, cache | data_svc, engine_factory | False | 半初始化 ⚠️ |
| AnalysisEngineFactory() | brain 导入 | storage, calendar, cache, data_svc | engine_factory | False | 半初始化 ⚠️ |
| register("engine_factory") | — | 全部 | 无 | False → True | 正常 ✅ |

**半初始化状态的危险**:
- `self.has("storage")` 返回 True，但 `self.has("engine_factory")` 返回 False
- 调用方检查 `has()` 会认为服务可用，但获取 engine_factory 时得到 None
- 重试时 `self.register("storage", new_storage)` 会覆盖旧的，但旧的 calendar/cache 不会被清理
- 已注册的 StorageManager 不会被关闭/清理（无 close 方法）

**影响**: MEDIUM — 生产环境中DataService初始化失败后，容器处于不一致状态

**修复建议**:
```python
def initialize(self) -> None:
    if self._initialized:
        return
    try:
        # ... 所有初始化步骤
        self._initialized = True
    except Exception as e:
        logger.error(f"ServiceContainer initialization failed: {e}")
        self.clear()  # 回滚所有已注册的服务
        raise
```

---

### CROSS-10 [MEDIUM]: LPPL/Wyckoff 引擎每次调用都 new 临时 brain 实例

**跨域路径**: `lppl_analysis_engine.py:67` → `brain.lppl.engine.LPPLEngine()`, `wyckoff_analysis_engine.py:42` → `brain.wyckoff.engine.WyckoffEngine()`

**证据**:

`lppl_analysis_engine.py:64-68`:
```python
try:
    from ...brain.lppl.engine import LPPLEngine
    engine = LPPLEngine()     # 每次调用都 new!
    result = engine.detect_bubble(df)
```

`wyckoff_analysis_engine.py:41-44`:
```python
from ...brain.wyckoff.engine import WyckoffEngine
wyckoff_engine = WyckoffEngine()  # 每次调用都 new!
result = wyckoff_engine.analyze(df)
```

`czsc_analysis_engine.py:68-69`:
```python
from ...brain.czsc.czsc_engine import CZSCEngine
czsc_engine = CZSCEngine()  # 每次调用都 new!
result = czsc_engine.get_czsc_signals(df)
```

**对比**: `AnalysisEngineFactory` 通过 `_engines` 字典缓存引擎实例（延迟初始化 + 复用）。但三个 services 层引擎适配器在 `run_xxx_analysis()` 中每次都创建新的 brain 引擎实例，绕过了 Factory 的缓存机制。

**影响**:
1. Factory 的缓存机制对这三个引擎无效
2. 每次创建新实例的开销（LPPLEngine 可能加载模型文件）
3. 与 FSM/Regime/NTF 引擎的行为不一致（它们通过 orchestrator 访问共享 brain）

**影响**: MEDIUM — 性能浪费，设计不一致

**修复建议**:
```python
class LpplAnalysisEngine:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self._engine = None  # 缓存 brain 引擎
    
    @property
    def engine(self):
        if self._engine is None:
            from ...brain.lppl.engine import LPPLEngine
            self._engine = LPPLEngine()
        return self._engine
```

---

## 交叉验证矩阵

### R1-1F 发现在跨域视角下的重新评估

| R1-1F # | 发现 | R2-C 重新评估 |
|---------|------|--------------|
| FINDING-01 | ServiceContainer 线程不安全 | **升级**: 不仅线程不安全，且被 AnalysisService._run_ntf_detection() 绕过直接 new DataFetcher()，使得加锁意义降低 |
| FINDING-02 | StorageManager data_dir 依赖 CWD | **降级**: 多实例问题更严重，CWD 问题在实例爆炸面前是次要的 |
| FINDING-03 | initialize() 无回滚 | **确认**: CROSS-09 详述了半初始化的具体危害 |
| FINDING-04 | importlib 相对路径脆弱 | **确认**: 但优先级低于引擎状态泄漏 |
| FINDING-05 | 引擎加载失败静默吞掉 | **升级**: CROSS-07 详述了 9 个引擎的链式崩溃 |
| FINDING-06 | brain 属性绕过 DAG | **升级**: CROSS-06 发现不仅是绕过 DAG，还缺少 orchestrator 注入 |
| FINDING-07 | returns 类型不一致 | **确认**: R1-1F CRITICAL 保持，跨域影响 DecisionBrain._execute_buy() |
| FINDING-08 | to_dict() 遗漏 returns | **确认**: R1-1F HIGH 保持 |

### R1-1A 发现在跨域视角下的重新评估

| R1-1A # | 发现 | R2-C 重新评估 |
|---------|------|--------------|
| CRITICAL | DataPipelineService.process() 类型错误 | **确认**: 影响链扩展到 AnalysisService → DataService → DataFetcher → pipeline.process() → 崩溃 |
| LOW | DataPipelineService 创建独立 StorageManager | **升级**: 从 LOW 升至 CROSS-01 CRITICAL 的一部分 |

---

## 风险矩阵

| 严重性 | 数量 | 发现 |
|--------|------|------|
| CRITICAL | 2 | CROSS-01 (实例爆炸), CROSS-02 (CZSC/DecisionBrain 状态污染) |
| HIGH | 5 | CROSS-03 (无 dispose), CROSS-04 (FSM 状态泄漏), CROSS-05 (绕过 DI), CROSS-06 (brain 绕过 DAG), CROSS-07 (静默 None) |
| MEDIUM | 3 | CROSS-08 (隐式双向耦合), CROSS-09 (半初始化), CROSS-10 (临时 brain 实例) |

**最优先修复**:
1. CROSS-01 (CRITICAL) — StorageManager 单例化或统一 DI
2. CROSS-02 (CRITICAL) — DecisionBrain 跨股票状态重置
3. CROSS-04 (HIGH) — 批量分析时 FSM 状态隔离
4. CROSS-05 (HIGH) — AnalysisService 使用已注入的实例
5. CROSS-07 (HIGH) — NullEngine 代理模式

---

## 架构合规性总结

| DAG 层级 | 约定 | 实际 | 合规 |
|----------|------|------|------|
| shared → data | 无外部依赖 | shared 无外部依赖 | ✅ |
| data → brain/risk | 依赖 shared, data | brain.czsc 依赖 czsc 第三方库 | ⚠️ |
| brain/risk → services | 依赖 shared, data | services 主动 import brain | ⚠️ (文档允许但实现不规范) |
| services → ui | 依赖 services, shared | ui 依赖 services, shared | ✅ |

**关键违规**: services 层（特别是 AnalysisService 和 AnalysisEngineFactory）大量直接 import brain 层模块，而非通过 DI 容器接收注入。这使得 DAG 的单向依赖约定名存实亡。

---

*审计完成时间: 2026-06-06*
*跨域审计员: R2-C*
