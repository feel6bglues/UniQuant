# UniQuant 系统架构文档

本文档详细描述 UniQuant 量化交易平台的整体架构设计、核心组件、数据流转以及关键设计决策。

---

## 目录

1. [分层架构](#1-分层架构)
2. [DAG 依赖注入容器](#2-dag-依赖注入容器)
3. [AnalysisEngineFactory 延迟初始化](#3-analysisengineFactory-延迟初始化)
4. [数据流](#4-数据流)
5. [协议与接口](#5-协议与接口)
6. [配置系统](#6-配置系统)
7. [关键设计决策](#7-关键设计决策)

---

## 1. 分层架构

UniQuant 采用四层架构，自下而上分别为基础设施层、数据层、分析层和应用层。各层之间仅允许上层依赖下层，严禁反向依赖和跨层越级调用。

```
+======================================================================+
|                         应用层 (Application)                          |
|  hands/          services/              ui/                          |
|  - BacktestEngine        - ServiceContainer      - Dashboard         |
|  - UnifiedMatchingEngine - AnalysisService        - LPPLVisualizer   |
|  - PortfolioEngine       - DataService            - HealthCheck      |
|  - Strategies            - CacheCoordinator       - Components       |
|  - ResultsManager        - ScanService            - ManagerLogic     |
+======================================================================+
        |                     |                      |
        v                     v                      v
+======================================================================+
|                          分析层 (Analysis)                            |
|  brain/                  signal/              risk/                   |
|  - FSM (有限状态机)       - SignalNormalizer   - DrawdownAnalyzer     |
|  - CZSC (缠中说禅)       - SignalAggregator   - EVTRisk (极值理论)   |
|  - LPPL (对数周期幂律)   - SignalQuality      - HistoricalRisk       |
|  - Regime (市场状态)     - SignalDB           - PortfolioOptimizer   |
|  - NTF (国家队追踪)     - SignalModels        - PositionSizer        |
|  - Wyckoff (威科夫)                           - StructuralRisk       |
|  - AlphaDecoupler                                                    |
|  - Factors (因子系统)                                                |
|  - Indicators (技术指标)                                             |
|  - Screener (选股器)                                                 |
+======================================================================+
        |                     |                      |
        v                     v                      v
+======================================================================+
|                           数据层 (Data)                               |
|  sources/                pipeline/            lake/                   |
|  - TDX (通达信)          - DataValidator      - StorageManager       |
|  - BaoStock              - DataCleaner          (Parquet + DuckDB)   |
|  - Eastmoney (东方财富)  - DataAdjuster                              |
|  - Sina (新浪财经)                                                   |
|  - Tencent (腾讯财经)   managers/                                    |
|  - THS (同花顺)         - SourceRouter (优先级路由)                  |
|  - RealtimeBridge        - TradeCalendarManager                      |
|                          - AdjustFactorManager                       |
|                          - StockMetadataManager                      |
+======================================================================+
        |                     |                      |
        v                     v                      v
+======================================================================+
|                       基础设施层 (Infrastructure)                      |
|  shared/                                                             |
|  - constants/       (常量子包: 市场/技术/数据/风险/路径/杂项)       |
|  - exceptions.py    (统一异常体系)                                   |
|  - config_loader.py (GlobalConfig 配置单例)                          |
|  - logger_factory.py(统一日志工厂)                                   |
|  - cache/           (CacheInterface + 多后端实现)                    |
|  - interfaces.py    (Protocol 协议定义)                              |
|  - retry_decorator  (网络重试装饰器)                                 |
|  - cost_model.py    (交易费用模型)                                   |
|  - slippage_model.py(滑点模型)                                       |
|  - limit_checker.py (涨跌停检测)                                     |
|  - env_config.py    (环境变量配置)                                   |
|  - parallel.py      (并行计算工具)                                   |
+======================================================================+
```

### 各层职责详述

**基础设施层 (`shared/`)**

为所有上层模块提供横切关注点（cross-cutting concerns）。包括常量定义、统一异常体系、配置加载、日志工厂、缓存抽象、协议接口、重试机制、费用与滑点模型。该层不依赖任何业务模块。

**数据层 (`data/`)**

负责外部数据的获取、清洗、标准化和持久化。支持 7 个数据源（TDX、BaoStock、Eastmoney、Sina、Tencent、THS、RealtimeBridge），通过 `SourceRouter` 实现优先级路由和故障转移。数据管道（`DataValidator` -> `DataCleaner` -> `DataAdjuster`）保证数据质量。`StorageManager` 以 Parquet 格式组织分层存储。

**分析层 (`brain/` + `signal/` + `risk/`)**

核心量化分析引擎层。`brain/` 包含 10 个分析子模块（FSM、CZSC、LPPL、Regime、NTF、Wyckoff、AlphaDecoupler、Factors、Indicators、Screener）。`signal/` 负责信号归一化、聚合和质量评估。`risk/` 提供风险度量（回撤分析、极值理论、结构性风险）和仓位管理。

**应用层 (`hands/` + `services/` + `ui/`)**

面向最终用户的功能层。`hands/` 包含回测执行引擎（`BacktestEngine`、`UnifiedMatchingEngine`、`PortfolioEngine`）和交易策略库。`services/` 以 DAG 容器编排所有服务。`ui/` 基于 Streamlit 构建可视化仪表盘。

---

## 2. DAG 依赖注入容器

### 设计动机

传统的 "God Object" 模式（一个大类持有所有引用）会导致隐式循环依赖和不可测试的耦合。UniQuant 使用轻量级 DAG（有向无环图）容器 `ServiceContainer` 替代框架级 DI，在保持简单性的同时消除循环依赖。

### ServiceContainer 实现

```python
# src/uniquant/services/service_container.py

class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._initialized = False

    @classmethod
    def instance(cls) -> "ServiceContainer":
        """单例访问入口"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, service: Any) -> None:
        """注册服务实例"""
        self._services[name] = service

    def get(self, name: str) -> Any:
        """按名称获取服务"""
        return self._services.get(name)

    def reset(self) -> None:
        """重置容器（用于测试）"""
        self._services.clear()
        self._initialized = False
```

### 初始化拓扑

`initialize()` 方法按严格的 DAG 顺序创建和注册所有服务。依赖关系图如下：

```
StorageManager ──> DataService ──> AnalysisEngineFactory
      |                |
      v                v
TradeCalendar    CacheCoordinator
Manager
                 StockQueryService
```

初始化流程（按执行顺序）：

```
第 1 步: 基础组件（无依赖）
    StorageManager()           -- 文件系统存储
    TradeCalendarManager()     -- 交易日历
    CacheCoordinator()         -- 缓存协调
    StockQueryService()        -- 股票查询

第 2 步: 数据服务（依赖第 1 步）
    DataService(
        storage_manager=storage,
        cache_coordinator=cache,
        stock_query=stock_query,
    )

第 3 步: 分析引擎工厂（依赖第 2 步）
    AnalysisEngineFactory(data_service=data_svc)
```

实际代码中的 `initialize()` 方法：

```python
def initialize(self) -> None:
    if self._initialized:
        return

    # 延迟导入避免模块级循环依赖
    from .data_service import DataService
    from .cache_coordinator import CacheCoordinator
    from .data_access_service import DataAccessService
    from .stock_query_service import StockQueryService

    # 第 1 步: 基础组件
    storage = StorageManager()
    calendar = TradeCalendarManager()
    cache = CacheCoordinator()
    stock_query = StockQueryService()

    # 第 2 步: 数据服务
    data_svc = DataService(
        storage_manager=storage,
        cache_coordinator=cache,
        stock_query=stock_query,
    )
    self.register("storage", storage)
    self.register("calendar", calendar)
    self.register("cache", cache)
    self.register("data_service", data_svc)

    # 第 3 步: 分析引擎工厂
    from .analysis.engine_factory import AnalysisEngineFactory
    engine_factory = AnalysisEngineFactory(data_service=data_svc)
    self.register("engine_factory", engine_factory)

    self._initialized = True
    logger.info("ServiceContainer initialized with DAG topology")
```

### 零循环依赖保证

源码文档中明确声明：

> 零循环依赖（DAG）。AnalysisService 不再 import DataService；二者通过容器注入接口依赖。

具体措施：

1. **延迟导入**：`initialize()` 中的 `from .data_service import DataService` 等语句放在方法内部而非模块顶部，避免模块加载时的循环引用。
2. **接口解耦**：`AnalysisService` 不直接 import `DataService`，而是通过容器获取注入的接口。
3. **单向依赖**：DAG 拓扑保证依赖方向始终是 `基础组件 -> 数据服务 -> 分析工厂`，无反向边。

### 使用方式

```python
# 获取容器单例并初始化
container = ServiceContainer.instance()
container.initialize()

# 获取服务
data_svc = container.get("data_service")
engine_factory = container.get("engine_factory")
```

---

## 3. AnalysisEngineFactory 延迟初始化

### 设计思路

`AnalysisEngineFactory` 是分析引擎的统一入口，采用延迟初始化（lazy initialization）模式。引擎仅在首次访问时通过 `importlib.import_module` 动态加载，而非在容器初始化阶段一次性创建所有引擎。

### 核心机制

```python
# src/uniquant/services/analysis/engine_factory.py

class AnalysisEngineFactory:
    def __init__(self, data_service):
        self._data_service = data_service
        self._engines: Dict[str, Any] = {}

    def _lazy_init(self, name: str, module_path: str, class_name: str, **kwargs) -> Any:
        """通用延迟初始化方法"""
        if name not in self._engines:
            import importlib
            try:
                mod = importlib.import_module(module_path, package=__package__)
                cls = getattr(mod, class_name)
                self._engines[name] = cls(data_service=self._data_service, **kwargs)
                logger.debug(f"Lazy-initialized {name}")
            except Exception as e:
                logger.warning(f"Failed to init {name}: {e}")
                return None
        return self._engines[name]
```

### 引擎注册表

工厂通过 `@property` 暴露 8 个延迟加载的分析引擎，每个属性对应一个 `brain/` 或 `services/analysis/` 下的具体引擎类：

| 属性名 | 引擎类 | 模块路径 | 功能描述 |
|--------|--------|----------|----------|
| `fsm` | `FsmAnalysisEngine` | `analysis.fsm_analysis_engine` | 有限状态机分析，基于均线状态判断市场趋势 |
| `czsc` | `CzscAnalysisEngine` | `analysis.czsc_analysis_engine` | 缠中说禅分析，笔/段/中枢识别与买卖点判定 |
| `lppl` | `LpplAnalysisEngine` | `analysis.lppl_analysis_engine` | 对数周期幂律模型，泡沫检测与崩盘预警 |
| `regime` | `RegimeAnalysisEngine` | `analysis.regime_analysis_engine` | 市场状态检测（NORMAL/STRESSED/FROZEN） |
| `ntf` | `NtfAnalysisEngine` | `analysis.ntf_analysis_engine` | 国家队资金追踪，识别政策干预信号 |
| `macro` | `MacroAnalysisEngine` | `analysis.macro_analysis_engine` | 宏观经济分析引擎 |
| `report` | `ReportGeneratorEngine` | `analysis.report_generator_engine` | 分析报告自动生成 |
| `brain` | `DecisionBrain` | `brain.fsm` | 综合决策大脑，整合多引擎信号输出最终决策 |

### 延迟加载的优势

1. **启动时间优化**：应用启动时只创建 `AnalysisEngineFactory` 本身，各引擎在首次使用时才初始化。对于只需要部分引擎的场景（如仅运行回测），可以避免加载所有分析模块。

2. **优雅的错误处理**：如果某个引擎的依赖缺失（例如缺少可选的第三方库），`_lazy_init` 会捕获异常并返回 `None`，不会导致整个系统崩溃。调用方可据此判断引擎是否可用。

3. **避免循环导入**：`importlib.import_module` 在运行时动态加载模块，绕过了 Python 模块加载顺序导致的循环引用问题。

4. **内存效率**：`_engines` 字典作为缓存，保证每个引擎只实例化一次。

### 使用示例

```python
factory = container.get("engine_factory")

# 首次访问时触发延迟初始化
fsm_result = factory.fsm.analyze(price_data)

# 二次访问直接返回缓存实例
czsc_result = factory.czsc.analyze(price_data)

# 引擎不可用时返回 None
if factory.ntf is not None:
    ntf_result = factory.ntf.analyze(price_data)
```

---

## 4. 数据流

### 端到端数据流转

```
外部数据源 (TDX / BaoStock / Eastmoney / Sina / Tencent / THS / RealtimeBridge)
    |
    v
DataFetcher (SourceRouter -> 优先级路由 + 故障转移)
    |
    v
数据管道 (DataValidator -> DataCleaner -> DataAdjuster)
    |
    v
存储层 (StorageManager: Parquet 分层存储)
    |    目录结构: data/lake/quotes/{daily,1mins,5mins}/
    |              data/factors/
    v
DataService (CacheCoordinator 缓存 + 统一访问接口)
    |
    v
分析引擎 (AnalysisEngineFactory 延迟加载)
    |    FSM / CZSC / LPPL / Wyckoff / NTF / Regime / Macro / Factors
    |
    v
信号系统 (signal/)
    |    SignalNormalizer -> SignalAggregator -> SignalQuality
    |    归一化               聚合                质量评估
    v
回测与执行 (hands/)
    |    UnifiedMatchingEngine: T+1 / 涨跌停 / 费用 / 非线性滑点
    |    BacktestEngine / PortfolioEngine
    v
UI 展示 (ui/)
    |    Streamlit 仪表盘 / LPPL 可视化 / 健康检查
    v
最终用户
```

### 数据获取阶段

`SourceRouter` 是数据获取的核心路由器。它接收一组按优先级排序的 `DataSourceAdapter`，逐一尝试获取数据，实现多源故障转移：

```python
class SourceRouter:
    def __init__(self, adapters: Sequence[DataSourceAdapter]):
        self.adapters = adapters
        self.max_workers = min(3, len(adapters))
        self.source_health: Dict[int, Dict[str, Any]] = {}

    def fetch_data(self, symbol, start_date, max_retries=2) -> pd.DataFrame:
        for i, adapter in enumerate(self.adapters):
            health_status = self.check_source_health(i)
            if health_status != "available":
                continue  # 跳过不健康的数据源
            for retry in range(max_retries + 1):
                try:
                    df = self._fetch_with_timeout(adapter, symbol, start_date, ...)
                    if not df.empty and self._validate_data_integrity(df):
                        self.update_source_health(i, "available")
                        return df
                except TimeoutError:
                    if retry >= max_retries:
                        self.update_source_health(i, "unavailable")
        return pd.DataFrame()  # 所有源失败
```

关键特性：
- **健康状态追踪**：维护每个数据源的健康状态缓存，跳过已知不可用的源。
- **超时控制**：使用 `NetworkConstants.SOCKET_TIMEOUT` 限制单次请求时间。
- **数据完整性校验**：在接受数据前验证其完整性。
- **重试机制**：每个数据源最多重试 `max_retries` 次。

### 数据管道阶段

数据管道由三个组件串联组成，保证进入存储层的数据质量：

**DataValidator（数据验证器）**

```python
class DataValidator:
    def validate(self, df: pd.DataFrame) -> bool:
        # 1. 检查必要列: date, code, open, high, low, close, volume, amount
        # 2. 智能修复: High < Low 时自动交换
        # 3. 严格校验: 修复后仍不满足则拒绝
```

**DataCleaner（数据清洗器）**

```python
class DataCleaner:
    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        # 1. 标准化列名（小写）
        # 2. 数值列类型转换，缺失值填充 0
        # 3. 停牌数据处理（volume=0）
        # 4. 去重（按日期保留最新）
        # 5. 补全 amount 列
```

**DataAdjuster（数据复权器）**

```python
class DataAdjuster:
    def __init__(self, storage_manager):
        self.factor_manager = FactorManager(storage_manager.data_dir)
    # 支持前复权(qfq)和后复权(hfq)
    # 根据股票代码前缀判断市场板块（沪市主板/科创板/深市主板/创业板）
```

### 存储层

`StorageManager` 管理 Parquet 文件的分层存储结构：

```
data/
  lake/
    quotes/
      daily/       -- 日线数据 (Parquet)
      1mins/       -- 1分钟K线 (Parquet)
      5mins/       -- 5分钟K线 (Parquet)
  factors/         -- 因子数据
```

特性：
- 基于 `filelock.FileLock` 的文件级并发安全
- Parquet 列式存储，高压缩比，查询效率优异
- 自动创建目录结构
- 启动时加载所有股票代码索引

### 信号处理阶段

信号系统（`signal/`）对多引擎输出进行标准化处理：

**1. 归一化（SignalNormalizer）**

每种分析引擎有对应的归一化器（如 `LPPLSignalNormalizer`），将引擎特有的原始输出转换为统一的 `Signal` 数据结构：

```python
class LPPLSignalNormalizer(SignalNormalizer):
    SOURCE = SignalSource.LPPL

    def normalize(self, raw_signal: dict[str, Any]) -> Signal:
        # 将 LPPL 引擎输出映射到标准 SignalType
        # bubble -> SignalType.LPPL_BUBBLE
        # crash  -> SignalType.LPPL_CRASH
        # 计算 confidence 和 strength
```

**2. 聚合（SignalAggregator）**

支持四种聚合策略：

```python
class SignalAggregationMethod(Enum):
    WEIGHTED_AVERAGE      # 加权平均（默认）
    MAJORITY_VOTE         # 多数投票
    MAX_CONFIDENCE        # 最大置信度
    CONSENSUS_THRESHOLD   # 共识阈值
```

可按信号源设置权重，按信号类型分组聚合，计算方向共识度。

**3. 质量评估（SignalQualityMetrics）**

```python
@dataclass
class SignalQualityMetrics:
    precision: float         # 精确率
    recall: float            # 召回率
    f1_score: float          # F1 分数
    accuracy: float          # 准确率
    average_lead_time: float # 平均提前时间
    hit_rate: float          # 命中率
    false_positive_rate: float  # 假阳性率
    profit_factor: float     # 盈亏比
    sharpe_ratio: float      # 夏普比率
```

### 回测与执行阶段

`UnifiedMatchingEngine` 是向量化撮合引擎，强制用于 `BacktestEngine` 和 `PortfolioEngine`：

```python
class UnifiedMatchingEngine:
    """
    统一向量化撮合引擎
    所有执行约束（T+1、涨跌停、印花税、最低佣金、非线性滑点）
    强制用于 BacktestEngine 和 PortfolioEngine
    """
    def __init__(self,
        commission_rate=BacktestConstants.DEFAULT_COMMISSION_RATE,
        stamp_duty_rate=0.0005,
        min_commission=BacktestConstants.DEFAULT_MIN_COMMISSION,
        slippage_rate=BacktestConstants.DEFAULT_SLIPPAGE_RATE,
        trade_calendar=None,
    ): ...
```

`FillResult` 数据类封装撮合结果：

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray      # 实际成交股数
    exec_prices: np.ndarray          # 执行价格
    commissions: np.ndarray          # 佣金
    stamp_duties: np.ndarray         # 印花税
    slippages: np.ndarray            # 滑点
    rejected_mask: np.ndarray        # 被拒绝的订单
    t1_violation_mask: np.ndarray    # T+1 违规
    limit_violation_mask: np.ndarray # 涨跌停违规
    cash_shortfall_mask: np.ndarray  # 资金不足
```

滑点模型采用非线性公式，考虑成交量冲击：

```python
def compute_execution_prices(self, prices, volumes, avg_daily_volumes, is_buy):
    vol_ratios = volumes / avg_daily_volumes  # 成交量占比
    impact = min(0.001 * sqrt(vol_ratios), 0.02)  # 冲击成本上限 2%
    total_slip = slippage_rate + impact
    return prices * (1.0 + direction * total_slip)
```

---

## 5. 协议与接口

UniQuant 广泛使用 Python `Protocol`（PEP 544）实现结构性子类型（structural subtyping），以鸭子类型方式解耦组件间的依赖。

### 数据源基类

```python
# src/uniquant/data/sources/base.py

class DataSource(ABC):
    """数据源抽象基类 -- 所有数据源必须实现的最小接口"""

    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Source", "")

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_market_cap(self, symbol: str) -> float: ...
```

### 能力协议（Capability Protocols）

数据源的可选能力通过独立的 `Protocol` 类定义。一个数据源可以实现其中任意组合，系统在运行时通过 `isinstance` 检查能力是否可用：

```python
# src/uniquant/data/sources/protocols.py

class HasBasicInfo(Protocol):
    """获取股票基本信息"""
    def fetch_basic_info(self, symbol: str) -> pd.DataFrame: ...

class HasFundFlow(Protocol):
    """获取资金流数据"""
    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame: ...

class HasIndustryList(Protocol):
    """获取行业列表"""
    def fetch_industry_list(self) -> pd.DataFrame: ...

class HasConceptList(Protocol):
    """获取概念列表"""
    def fetch_concept_list(self) -> pd.DataFrame: ...

class HasSectorFundFlow(Protocol):
    """获取板块资金流"""
    def fetch_sector_fund_flow(self) -> pd.DataFrame: ...

class HasHotRanking(Protocol):
    """获取热门排名"""
    def fetch_hot_ranking(self) -> pd.DataFrame: ...

class HasMinuteData(Protocol):
    """获取分钟级K线数据（1/5/15/30/60分钟）"""
    def fetch_minute_data(self, symbol, period, start_date, end_date,
                          adjust="qfq") -> pd.DataFrame: ...

class HasDragonTiger(Protocol):
    """获取龙虎榜数据"""
    def fetch_dragon_tiger_list(self, symbol, start_date, end_date) -> pd.DataFrame: ...

class HasTickData(Protocol):
    """获取逐笔成交数据"""
    def fetch_tick_data(self, symbol: str) -> pd.DataFrame: ...
```

各数据源的能力矩阵（示意）：

| 数据源 | BasicInfo | FundFlow | MinuteData | DragonTiger | TickData | HotRanking |
|--------|-----------|----------|------------|-------------|----------|------------|
| TDX | - | - | Y | - | Y | - |
| BaoStock | Y | - | Y | - | - | - |
| Eastmoney | Y | Y | Y | Y | - | Y |
| Sina | - | - | - | - | - | - |
| Tencent | - | - | Y | - | - | - |
| THS | Y | Y | - | - | - | Y |

### 核心业务协议

定义在 `shared/interfaces.py` 中，均使用 `@runtime_checkable` 装饰器支持运行时类型检查：

```python
@runtime_checkable
class DataFetcherProtocol(Protocol):
    """数据获取协议 -- 解耦 Brain 组件与 DataFetcher 实现"""
    def fetch_history(self, symbol, start_date, end_date,
                      adjust="qfq", period="daily") -> pd.DataFrame: ...

@runtime_checkable
class RiskAssessmentProtocol(Protocol):
    """风险评估协议"""
    def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]: ...

@runtime_checkable
class PositionSizerProtocol(Protocol):
    """仓位计算协议"""
    def calculate_shares(self, price, stop_loss, czsc_bottom,
                         market="CN", symbol="UNKNOWN") -> Dict[str, Any]: ...

@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    """分析引擎协议"""
    def analyze(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...

@runtime_checkable
class CalculationPluginProtocol(Protocol):
    """计算插件协议 -- 支持动态扩展"""
    name: str
    version: str
    description: str
    def calculate(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...
```

### 市场信号上下文

`MarketSignalContext` 是类型化的数据包，替代无类型的 `dict` 参数传递，为 `DecisionBrain.make_decision()` 提供编译时类型检查：

```python
@dataclass
class MarketSignalContext:
    regime: MarketRegime = MarketRegime.NORMAL    # NORMAL/STRESSED/FROZEN
    risk: str = "Safe"
    bubble_confidence: float = 0.0
    ntf_side: NtfSide = NtfSide.NONE             # NONE/SUPPORT/RESISTANCE
    ntf_intensity: float = 0.0
    is_3rd_buy: bool = False                      # 缠论三买信号
    bi_count: int = 0                             # 笔数量
    alpha_score: float = 0.0                      # Alpha 得分
    ma_status: Optional[str] = None               # 均线状态
    price: float = 0.0
    pre_close: float = 0.0
    symbol: str = ""
    atr_stop: float = 0.0                         # ATR 止损位
    czsc_bottom: Optional[float] = None           # 缠论底部价位
    market: str = "CN"
    returns: Optional[pd.Series] = None
    lppl_days_to_tc: Optional[float] = None       # LPPL 临界点剩余天数

    @classmethod
    def from_dict(cls, data: Dict) -> "MarketSignalContext": ...

    def to_dict(self) -> Dict[str, Any]: ...
```

### 计算插件注册中心

`CalculationRegistry` 提供全局的插件注册与查询能力：

```python
class CalculationRegistry:
    def register(self, plugin: CalculationPluginProtocol) -> None: ...
    def unregister(self, plugin_name: str) -> None: ...
    def get(self, plugin_name: str) -> CalculationPluginProtocol: ...
    def list(self) -> List[str]: ...
    def has(self, plugin_name: str) -> bool: ...

# 全局实例
calculation_registry = CalculationRegistry()
```

### 缓存接口

```python
# src/uniquant/shared/cache/cache_interface.py

class CacheInterface(ABC):
    """缓存管理器统一接口 -- 所有缓存实现必须遵循此接口"""

    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, ttl: int = 3600) -> bool: ...
    def delete(self, key: str) -> bool: ...
    def clear(self, pattern: Optional[str] = None) -> int: ...
    def get_stats(self) -> Dict[str, Any]: ...  # hits, misses, size, files
    def reset_stats(self) -> None: ...
    def cleanup(self) -> int: ...               # 清理过期缓存
```

---

## 6. 配置系统

### GlobalConfig 单例

`GlobalConfig` 是线程安全的单例配置加载器，使用双重检查锁定（double-checked locking）模式：

```python
# src/uniquant/shared/config_loader.py

class GlobalConfig:
    _instance = None
    _lock = threading.Lock()
    _config: Dict[str, Any] = {}
    _root_dir: Path = Path(__file__).parent.parent.parent.resolve()

    _REQUIRED_SECTIONS = ["base", "cache", "network", "data_sources"]

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GlobalConfig, cls).__new__(cls)
                    cls._instance._load_config()
        return cls._instance
```

### YAML 配置文件加载

支持两种加载模式：

**模式一：统一配置文件**

如果 `config/config.yaml` 存在，直接加载为根配置。

**模式二：分散配置文件**

如果不存在统一配置文件，按命名空间加载多个独立文件：

| 文件名 | 命名空间 | 说明 |
|--------|----------|------|
| `settings.yaml` | `settings` | 基础设置 |
| `markets.yaml` | `markets` | 市场参数 |
| `brain.yaml` | `brain` | 分析引擎参数 |
| `data_sources.yaml` | `data_sources` | 数据源配置 |
| `cache.yaml` | `cache` | 缓存策略 |
| `czsc.yaml` | `czsc` | 缠论参数 |
| `indicators.yaml` | `indicators` | 技术指标参数 |
| `indices.yaml` | `indices` | 指数配置 |
| `lppl.yaml` | `lppl` | LPPL 模型参数 |
| `network.yaml` | `network` | 网络超时与重试 |

两种模式下均额外加载：

| 文件名 | 命名空间 | 说明 |
|--------|----------|------|
| `trading.yaml` | `trading` | 交易参数 |
| `factors.yaml` | `factors` | 因子配置 |

### 点号路径访问

`get()` 方法支持点号分隔的路径访问嵌套配置：

```python
def get(self, key_path: str, default: Any = None) -> Any:
    """
    使用点号路径访问配置值
    例如: get('brain.fsm.ma_short', 20)
    """
    keys = key_path.split(".")
    value = self._config
    try:
        for k in keys:
            value = value[k]
        return value
    except (KeyError, TypeError):
        return default
```

使用示例：

```python
from uniquant.shared.config_loader import get_config

config = get_config()

# 基础配置
data_dir = config.DATA_DIR             # 数据目录 Path
lake_dir = config.LAKE_DIR             # 数据湖目录 Path
log_dir  = config.LOG_DIR              # 日志目录 Path (自动创建)
cache_dir = config.CACHE_DIR           # 缓存目录 Path (自动创建)

# 点号路径访问
ma_short = config.get("brain.fsm.ma_short", 20)
timeout  = config.get("network.timeout.default", 30)
risk_pct = config.get("risk.default_risk_pct", 0.1)
engine   = config.get("base.data_lake.engine", "duckdb")
```

### 配置验证

`validate_config()` 在加载完成后自动执行，检查以下必需配置段：

1. **必需段检查**：`base`、`cache`、`network`、`data_sources` 必须存在
2. **base 验证**：`data_lake.path` 和 `data_lake.engine` 必须存在
3. **cache 验证**：`global.enabled`、`global.path`、`ttl.stock_data`、`ttl.realtime_data` 必须存在
4. **network 验证**：`timeout.default` 必须存在
5. **data_sources 验证**：`sources` 必须存在
6. **risk 验证**：`default_risk_pct` 必须在 (0, 1] 范围内
7. **brain 验证**（警告级别）：检查 `alpha_decoupler`、`ntf`、`regime`、`fsm` 子段
8. **lppl 验证**（警告级别）：检查 `optimizer.max_iter`、`optimizer.popsize`、`data.min_data_points`

### 环境变量配置

`env_config.py` 模块在导入时自动配置底层并行库的线程数，防止多进程环境下的资源争抢：

```python
# src/uniquant/shared/env_config.py

def configure_environment() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("BLIS_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("LPPL_DISABLE_PARALLEL", "1")

configure_environment()  # 模块加载时自动执行
```

---

## 7. 关键设计决策

### 7.1 DAG 容器而非框架级 DI

**决策**：采用自建的轻量级 `ServiceContainer` 而非 Spring/Guice 风格的 DI 框架。

**理由**：
- Python 生态中不需要 Java 级别的 DI 框架，过度工程化会增加认知负担
- DAG 容器的 `register()`/`get()` 接口足够简单，代码量不到 50 行
- 显式的 `initialize()` 方法使初始化顺序一目了然，便于调试
- 测试时可通过 `reset()` 清空容器，注入 mock 对象

### 7.2 协议鸭子类型而非继承

**决策**：使用 `typing.Protocol`（PEP 544）定义接口，而非抽象基类继承。

**理由**：
- 结构性子类型无需显式继承，任何实现了相同方法签名的类自动满足协议
- `@runtime_checkable` 支持 `isinstance()` 检查，兼顾静态类型检查和运行时验证
- 降低耦合度：新的分析引擎只需实现 `analyze(data, **kwargs) -> Dict[str, Any]` 即可接入系统，无需 import 任何基类
- 能力协议（`HasBasicInfo`、`HasFundFlow` 等）允许数据源按需实现可选功能，避免"胖接口"问题

### 7.3 向量化撮合引擎（NumPy）

**决策**：`UnifiedMatchingEngine` 全部使用 NumPy 向量化操作，而非逐笔撮合。

**理由**：
- 回测通常涉及数万到数十万根 K 线，逐笔循环的 Python 代码性能瓶颈严重
- NumPy 向量化可以利用底层 C/Fortran 加速，性能提升 10-100 倍
- 所有约束（T+1、涨跌停、费用、滑点）统一在向量空间中计算，逻辑一致且不易遗漏
- `FillResult` 使用 `np.ndarray` 返回批量结果，避免对象创建开销

### 7.4 Walk-Forward 因子管道防前瞻偏差

**决策**：因子分析采用 Walk-Forward（滚动前进）管道，而非全样本回测。

**理由**：
- 全样本回测中因子选择和参数优化会引入前瞻偏差（look-ahead bias），导致回测结果虚高
- Walk-Forward 将数据分为训练窗口和验证窗口，因子权重在训练窗口上计算，在验证窗口上评估
- `brain/factors/walk_forward_pipeline.py` 实现了完整的滚动验证框架
- `FactorAnalyzer` 和 `FactorComposer` 仅使用历史数据计算 IC/IR，确保因子评估的真实性

### 7.5 线程安全单例

**决策**：`FactorRegistry`、`GlobalConfig` 均使用双重检查锁定（double-checked locking）实现线程安全单例。

**理由**：

```python
# FactorRegistry 的线程安全实现
class FactorRegistry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:          # 第一次检查（无锁，快速路径）
            with cls._lock:                # 获取锁
                if cls._instance is None:  # 第二次检查（有锁，安全路径）
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def register(cls, name, compute_func, ...):
        with cls._lock:                    # 写操作加锁保护
            cls._factors[name] = FactorInfo(...)
```

- `FactorRegistry` 在多个分析引擎之间共享因子定义，必须保证并发安全
- `GlobalConfig` 可能在多线程环境中被首次访问，需要安全的初始化
- 双重检查锁定避免了每次访问都加锁的性能开销

### 7.6 延迟导入避免循环依赖

**决策**：在 `ServiceContainer.initialize()` 和 `AnalysisEngineFactory._lazy_init()` 中使用延迟导入（函数内 import）。

**理由**：
- `services/` 和 `data/` 包之间存在潜在的循环引用（DataService 需要 StorageManager，分析引擎需要 DataService）
- 模块顶部的 import 在加载时立即执行，容易触发循环导入错误
- 延迟导入将 import 推迟到运行时方法调用，此时被依赖的模块已经完成加载
- `importlib.import_module` 提供了更灵活的动态加载能力，支持按字符串路径加载模块

### 7.7 能力模式（Capability Pattern）

**决策**：数据源的可选功能通过独立的能力协议（`HasBasicInfo`、`HasFundFlow` 等）定义，而非放在基类中。

**理由**：
- 7 个数据源各有不同的能力集合，强制所有源实现所有方法违反接口隔离原则
- 能力协议允许运行时按需检查：`if isinstance(source, HasFundFlow): source.fetch_fund_flow(...)`
- 新增能力只需添加新的 Protocol 类，不影响现有数据源的实现
- 与 `SourceRouter` 的故障转移机制配合，可以针对特定能力选择合适的数据源

---

## 附录：模块目录总览

```
src/uniquant/
  shared/           # 基础设施层
    cache/          #   缓存子系统 (CacheInterface + 多后端)
    constants/      #   常量子包 (7 模块)
    exceptions.py   #   异常体系
    interfaces.py   #   Protocol 定义
    config_loader.py#   GlobalConfig
    logger_factory.py#  日志工厂
    cost_model.py   #   费用模型
    slippage_model.py#  滑点模型
    limit_checker.py#   涨跌停检测
    retry_decorator.py# 重试机制
    env_config.py   #   环境变量
    parallel.py     #   并行工具
    ...

  data/             # 数据层
    sources/        #   7 个数据源实现 + 协议定义
    pipeline/       #   数据管道 (Validator/Cleaner/Adjuster)
    lake/           #   存储管理 (StorageManager)
    managers/       #   路由/日历/复权/元数据管理
    parsers/        #   数据解析器
    services/       #   数据导入服务
    utils/          #   工具函数

  brain/            # 分析层 - 引擎
    fsm/            #   有限状态机
    czsc/           #   缠中说禅
    lppl/           #   对数周期幂律
    regime/         #   市场状态检测
    ntf/            #   国家队追踪
    wyckoff/        #   威科夫分析
    alpha_decoupler/#   Alpha 解耦器
    factors/        #   因子系统 (Registry/Analyzer/Composer/WalkForward)
    indicators/     #   技术指标库
    screener/       #   选股器

  signal/           # 分析层 - 信号
    models.py       #   Signal/SignalBatch/AggregatedSignal 数据模型
    normalizer.py   #   信号归一化器
    aggregator.py   #   信号聚合器
    quality.py      #   信号质量评估
    db.py           #   信号存储

  risk/             # 分析层 - 风险
    drawdown_analyzer.py  # 回撤分析
    evt_risk.py           # 极值理论风险
    historical_risk.py    # 历史风险度量
    portfolio_optimizer.py# 组合优化
    sizer.py              # 仓位管理
    structural.py         # 结构性风险

  hands/            # 应用层 - 回测与执行
    backtest/       #   回测引擎
      engine.py     #     核心回测引擎
      unified_matching_engine.py  # 向量化撮合
      portfolio_engine.py         # 组合回测
      monte_carlo.py              # 蒙特卡洛模拟
      overfitting_detector.py     # 过拟合检测
      robustness_checker.py       # 稳健性检验
      sensitivity_analyzer.py     # 敏感性分析
      trade_analysis/             # 交易分析
    strategies/     #   策略库
      base.py       #     策略基类
      fsm_strategy.py    # FSM 策略
      wyckoff.py         # Wyckoff 策略
      ma_cross.py        # 均线交叉
      regime.py          # 状态策略
      registry.py        # 策略注册中心

  services/         # 应用层 - 服务编排
    service_container.py  # DAG 依赖注入容器
    data_service.py       # 数据服务
    analysis_service.py   # 分析服务
    analysis/             # 分析引擎适配层
      engine_factory.py   #   延迟加载工厂
      fsm_analysis_engine.py
      czsc_analysis_engine.py
      lppl_analysis_engine.py
      regime_analysis_engine.py
      ntf_analysis_engine.py
      macro_analysis_engine.py
      wyckoff_analysis_engine.py
      report_generator_engine.py
    cache_coordinator.py  # 缓存协调
    scan_service.py       # 扫描服务
    portfolio_service.py  # 组合服务

  ui/               # 应用层 - 用户界面
    dashboard.py    #   Streamlit 主仪表盘
    components.py   #   UI 组件库
    lppl_visualizer.py  # LPPL 可视化
    health_check.py     # 系统健康检查
    manager_logic.py    # 管理逻辑
```
