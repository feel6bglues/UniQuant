# services -- 服务层

> **状态:** ⚠️ 部分可用 | **当前文件:** 10/24 | **可用:** analysis_service, service_container, 6 个引擎适配器

`uniquant.services` 模块是 UniQuant 的服务编排层，约 7.8K LOC。该模块通过依赖注入容器（DAG 拓扑）管理所有服务的生命周期，提供分析服务、数据服务、扫描服务、组合服务、健康监控、缓存协调等核心功能。服务层位于 brain（分析引擎）和 UI 之间，是系统的中间协调层。

`__init__.py` 导出以下服务：`CacheCoordinator`、`DataQualityService`、`DataService`、`HealthService`、`PortfolioService`、`ScanPipeline`、`StockQueryService`、`ValidationService`。

---

## ServiceContainer DAG 容器

`ServiceContainer` 位于 `services.service_container`，是全局依赖注入容器，采用单例模式。

### 拓扑结构

```
StorageManager --> MarketDataReader --> DataService --> AnalysisService
     |                                               |
TradeCalendarManager                     AnalysisEngineFactory
     |                                       |
CacheCoordinator                             +-- FsmAnalysisEngine
                                             +-- CzscAnalysisEngine
                                             +-- LpplAnalysisEngine
                                             +-- RegimeAnalysisEngine
                                             +-- ReportGeneratorEngine
```

零循环依赖设计。`AnalysisService` 不直接 import `DataService`，二者通过容器注入接口依赖。

### 核心方法

| 方法 | 说明 |
|------|------|
| `instance()` | 类方法，返回全局单例。 |
| `register(name, service)` | 注册服务实例到容器。 |
| `get(name)` | 按名称获取已注册服务。 |
| `initialize()` | 按 DAG 顺序初始化所有服务：`StorageManager` -> `TradeCalendarManager` -> `CacheCoordinator` -> `StockQueryService` -> `DataService` -> `AnalysisEngineFactory`。仅执行一次（`_initialized` 标志位保护）。 |
| `reset()` | 清除所有服务并重置初始化标志，用于测试环境。 |
| `clear()` | 清除所有服务引用。 |

---

## AnalysisEngineFactory

`AnalysisEngineFactory` 位于 `services.analysis.engine_factory`，负责延迟初始化所有分析引擎。

### _lazy_init 机制

```python
def _lazy_init(self, name: str, module_path: str, class_name: str, **kwargs) -> Any
```

使用 `importlib.import_module` 动态导入引擎模块，仅在首次访问时实例化，结果缓存在 `_engines` 字典中。初始化失败时返回 `None` 并记录警告日志。

### 引擎列表

通过 `@property` 属性延迟暴露以下引擎：

| 属性 | 引擎类 | 模块路径 |
|------|--------|----------|
| `fsm` | `FsmAnalysisEngine` | `analysis.fsm_analysis_engine` |
| `czsc` | `CzscAnalysisEngine` | `analysis.czsc_analysis_engine` |
| `lppl` | `LpplAnalysisEngine` | `analysis.lppl_analysis_engine` |
| `regime` | `RegimeAnalysisEngine` | `analysis.regime_analysis_engine` |
| `ntf` | `NtfAnalysisEngine` | `analysis.ntf_analysis_engine` |
| `macro` | `MacroAnalysisEngine` | `analysis.macro_analysis_engine` |
| `report` | `ReportGeneratorEngine` | `analysis.report_generator_engine` |
| `brain` | `DecisionBrain` | `brain.fsm` |

所有引擎构造时注入 `data_service` 参数。

---

## AnalysisService 分析服务

`AnalysisService` 位于 `services.analysis_service`，是分析层的主门面（Facade），编排所有分析引擎和辅助服务。

### 构造函数

```python
AnalysisService(
    data_service: DataService,
    engine_factory=None,
    evt_risk=None,
    sizer=None,
    validation_service=None,
)
```

若未提供 `engine_factory`，内部自动创建 `AnalysisEngineFactory`。初始化时配置内存缓存（`CacheFactory.create("memory")`）和磁盘缓存（`CacheFactory.create("disk")`），并初始化 `ValidationService`。

### 引擎代理属性

通过 `@property` 代理到 `AnalysisEngineFactory` 的对应属性：`fsm_engine`、`czsc_engine`、`lppl_engine`、`regime_engine`、`ntf_engine`、`macro_engine`、`report_engine`、`brain`。

### analyze_ticker 全流程分析

```python
def analyze_ticker(self, ticker: str) -> bool
```

执行单只股票的端到端分析流程：
1. `_prepare_data_for_analysis`：通过 `data_service.fetch_for_brain` 获取数据包
2. `_run_engine_analysis`：依次运行 Regime / LPPL / NTF / CZSC / Alpha / MA / Returns / Price&Stop / TechnicalIndicators
3. `_make_decision`：调用 `brain.make_decision` 生成决策
4. `_save_analysis_result`：保存 JSON 结果到 `hands/results/YYYY-MM-DD/`
5. `_generate_analysis_report`：委托 `report_engine` 生成报告

### 市场级缓存（线程安全）

使用 `threading.Lock` 保护的市场级缓存，避免重复计算全市场共享数据：
- `_market_regime` / `_market_regime_details`：市场状态（每日计算一次）
- `_ntf_signals`：国家队干预信号（每日计算一次）
- `_benchmark_data`：基准指数数据
- `_sector_data_cache`：板块数据缓存

`clear_market_cache()` 和 `get_cache_status()` 均为线程安全操作。

### 其他关键方法

| 方法 | 说明 |
|------|------|
| `run_comprehensive_analysis(symbol)` | 综合分析：依次运行 LPPL / CZSC / FSM 分析，合并结果并缓存（2 小时 TTL）。 |
| `analyze_macro_health(mock=False)` | 宏观健康分析，委托 `macro_engine`。 |
| `get_macro_returns(window=200)` | 获取沪深 300 宏观收益率序列。 |
| `scan_etfs()` | ETF 扫描，批量预加载后向量化计算信号、强度和 CZSC 状态。 |
| `run_lppl_analysis(symbol, df)` | LPPL 泡沫检测。 |
| `run_czsc_analysis(symbol, df)` | 缠论技术分析。 |
| `run_regime_detection(symbol, df)` | 市场状态检测。 |
| `run_ntf_detection(symbol, df)` | 国家队干预检测。 |
| `run_fsm_analysis(symbol, df)` | 有限状态机交易逻辑分析。 |
| `enrich_lake_data(df_raw)` | 对原始数据湖数据添加 Name / Signal / Strength / CZSC 等 UI 友好列。 |
| `generate_report(ticker, data)` | 生成个股研究报告。 |
| `generate_reports_from_results(symbols, date, force)` | 从已保存结果批量生成报告（快速模式，跳过计算）。 |

### 数据验证

- `validate_risk_metrics(metrics)`：验证 VaR/CVaR/最大回撤/置信度的合理性
- `validate_position_sizing(sizing_result)`：验证仓位计算结果
- `validate_analysis_result(result)`：验证分析结果状态和信号强度
- `validate_comprehensive_result(result)`：验证综合分析结果
- `ensure_precision_consistency(data)`：根据字段名自动应用精度规则

---

## 分析引擎

`AnalysisEngineFactory` 通过延迟初始化管理以下分析引擎，每个引擎封装对应的 brain 模块：

| 引擎 | 包装的 brain 模块 | 关键方法 |
|------|-------------------|----------|
| `FsmAnalysisEngine` | `brain.fsm.DecisionBrain` | `run_fsm_analysis(symbol, df)` -- 有限状态机交易决策 |
| `CzscAnalysisEngine` | `brain.czsc_engine.CZSCEngine` | `run_czsc_analysis(symbol, df)` -- 缠中说禅笔段分析 |
| `LpplAnalysisEngine` | `brain.lppl.engine.LPPLEngine` | `run_lppl_analysis(symbol, df)` -- 对数周期幂律泡沫检测 |
| `RegimeAnalysisEngine` | `brain.regime_detector.RegimeDetector` | `run_regime_detection(symbol, df)` -- 市场状态检测 |
| `NtfAnalysisEngine` | `brain.ntf_engine.NTFEngine` | `run_ntf_detection(symbol, df)` -- 国家队干预信号检测 |
| `MacroAnalysisEngine` | EVT 风险计算 + 宏观指标 | `analyze_macro_health(mock)` -- 宏观健康分析 |
| `ReportGeneratorEngine` | 报告生成模块 | `generate_report(ticker, data)` -- 个股研究报告生成 |

每个引擎均实现降级处理（`_fallback_xxx_analysis`），当 brain 模块不可用时使用基本统计方法替代。

---

## DataService

`DataService` 位于 `services.data_service`，是数据访问的门面（Facade），协调以下专职服务：

- `CacheCoordinator`：缓存管理
- `DataQualityService`：数据质量检查
- `StockQueryService`：股票查询

### 构造函数

```python
DataService(
    fetcher: Optional[DataFetcher] = None,
    storage_manager: Optional[StorageManager] = None,
    cleaner: Optional[DataCleaner] = None,
    cache_coordinator: Optional[object] = None,
    stock_query: Optional[object] = None,
)
```

内部持有 `DataAccessService` 实例，委托所有具体的数据访问操作。`self.lake` 指向 `StorageManager`。

### 核心方法

| 方法 | 说明 |
|------|------|
| `fetch_data(symbol, start_date, end_date, use_cache)` | 获取数据（带缓存降级策略）：缓存 -> 数据源 -> 数据湖。 |
| `fetch_and_save_stock(symbol, start_date, end_date)` | 获取、清洗并保存股票数据到数据湖。 |
| `fetch_and_save_index(symbol, start_date, end_date)` | 获取、清洗并保存指数数据到数据湖。 |
| `fetch_for_brain(symbol)` | 为决策大脑准备完整数据包：股票日线 + 沪深 300 基准 + ETF 数据。 |
| `batch_process_stocks(symbols, start_date, end_date)` | 多核并行批量处理股票（使用 joblib Parallel）。 |
| `get_stock_name(symbol)` | 股票代码到名称的查询（委托 StockQueryService）。 |
| `calculate_data_quality(symbol, data_type, market)` | 计算数据质量指标。 |
| `check_data_health(symbols, data_type, market)` | 批量检查数据健康状态。 |
| `check_cache_consistency(symbol, data_type, market)` | 检查缓存与数据源的一致性。 |
| `rebuild_cache(symbol, data_type, market)` | 从数据源重建缓存。 |

---

## DataAccessService

`DataAccessService` 位于 `services.data_access_service`，是 `DataService` 的内部协调器，实现缓存/数据源/数据湖的三级读取和持久化逻辑。

### 核心方法

| 方法 | 说明 |
|------|------|
| `fetch_data(symbol, start_date, end_date, use_cache)` | 三级降级读取：缓存 -> 数据源 -> 数据湖。 |
| `fetch_from_cache(cache_key, symbol)` | 从缓存获取数据，失败降级到数据源。 |
| `fetch_from_source(symbol, start_date, end_date, cache_key, use_cache)` | 从数据源获取并写入缓存。 |
| `fetch_from_lake(symbol, start_date, end_date)` | 从数据湖读取并过滤日期范围。 |
| `fetch_and_save_dataset(symbol, start_date, end_date, data_type)` | 获取、清洗、保存到数据湖，支持 stock 和 index 类型。 |
| `load_data_with_fallback(symbol, data_type, description)` | 从数据湖加载，失败回退到数据源获取并保存。支持指数代码的多种后缀尝试（`.SH`、`.SZ`、无后缀）。 |
| `load_etf_data()` | 加载 ETF 数据（510300），优先数据湖，回退到数据源。 |

所有返回的 DataFrame 均通过 `_clone_dataframe` 深拷贝，避免外部修改影响缓存。

---

## ScanService

`ScanPipeline` 位于 `services.scan_service`，实现全市场扫描流水线。

### 流水线步骤

```
数据加载 -> 因子计算 -> IC/IR 分析 -> 合成评分 -> 扫描 -> 报告输出
```

### ScanConfig 配置

```python
@dataclass
class ScanConfig:
    top_n: int = 50                  # 输出头部股票数
    bottom_n: int = 50               # 输出尾部股票数
    min_data_points: int = 60        # 最少数据点
    holding_periods: List[int]       # 持有期列表，默认 [1, 5, 20]
    factor_cols: List[str]           # 因子列名列表
    weight_method: str = "ic_weighted"
    lightweight: bool = False        # 轻量模式（跳过 IC/IR）
    walk_forward_mode: bool = False  # Walk-forward 因子权重
    walk_forward_train: int = 504
    walk_forward_test: int = 63
    batch_size: int = 500
    financial_subdir: str = "financial"
```

### 核心方法

| 方法 | 说明 |
|------|------|
| `load_data(symbols)` | 从 `StorageManager` 批量加载日线和财务 Parquet 数据。 |
| `build_factors()` | 合并日线数据，调用 `FinancialFactorBridge` 合并财务因子，调用 `FactorComposer.compute_all_factors` 计算所有注册因子。 |
| `analyze_factors()` | 调用 `FactorAnalyzer.compute_ic_ir` 或 `WalkForwardFactorPipeline.run` 分析因子有效性。 |
| `compose_scores()` | 调用 `FactorComposer.process` 生成 IC 加权合成评分。 |
| `generate_report(output_dir)` | 生成多份报告：top_stocks、bottom_stocks、market_risk、sector_top、factor_analysis、tech_signals_top20。 |
| `run(output_dir, symbols)` | 执行完整流水线，返回执行统计信息。 |

### 依赖组件

- `FinancialFactorBridge`：财务因子桥接
- `FactorAnalyzer`：IC/IR 计算
- `FactorComposer`：因子合成
- `WalkForwardFactorPipeline`：Walk-forward 因子权重
- `StockScreener`：股票筛选和报告格式化
- `Indicators`：技术指标计算

---

## PortfolioService

`PortfolioService` 位于 `services.portfolio_service`，处理投资组合构建和管理。使用 `Decimal` 避免浮点误差。

### 核心特性

- **仓位边界限制**：`MIN_POSITION_PCT = 0%`，`MAX_POSITION_PCT = 100%`
- **精度控制**：`DECIMAL_PLACES = 0.0001`（4 位小数）
- **权重验证**：`_validate_weights` 确保权重总和为 1 或 100，且无负值
- **失败回滚**：`_backup_weights` / `_rollback_weights` 机制，仓位计算失败时自动回滚

### 核心方法

| 方法 | 说明 |
|------|------|
| `create_portfolio(strategy, symbols)` | 创建投资组合，调用 `calculate_weights` 分配权重。 |
| `calculate_weights(strategy, symbols)` | 按策略计算权重。支持 `"equal_weight"` 等权重策略。 |
| `calculate_position(symbol, target_pct, portfolio_value, price)` | 计算单只股票仓位：目标百分比 -> 目标金额 -> 股数 -> 实际百分比。 |
| `calculate_position_size(price, stop_loss, risk_pct, capital, market, czsc_bottom)` | 基于风险百分比计算建议股数，A 股修正为 100 股整数倍。 |
| `analyze_portfolio(portfolio)` | 分析组合风险和绩效指标。 |
| `rebalance(portfolio, target_weights, prices)` | 再平衡投资组合到目标权重，计算所需交易并执行。失败时回滚权重。 |
| `get_structural_risks()` | 获取结构化风险指标（委托 risk_service）。 |
| `get_portfolio()` | 获取当前持仓详情，返回 DataFrame。 |

---

## StockQueryService

`StockQueryService` 位于 `services.stock_query_service`，负责股票代码映射和信息查询。

### 核心方法

| 方法 | 说明 |
|------|------|
| `refresh_stock_map()` | 从 `DataFetcher.fetch_stock_info()` 刷新股票代码到名称的映射。 |
| `get_stock_name(symbol)` | 查询股票名称，按优先级：内部映射 -> 添加市场后缀查找 -> 去除后缀查找 -> 外部数据源。 |
| `scan_etfs()` | 扫描 ETF 列表（以 "51" 开头的代码）。 |
| `get_stock_info()` | 获取完整的股票代码到名称映射。 |
| `is_etf(symbol)` | 判断是否为 ETF。 |
| `get_market(symbol)` | 根据代码判断所属市场（SH/SZ）。 |

市场判断规则：代码以 "6" 开头为上海（SH），以 "000"/"002"/"300" 开头为深圳（SZ）。

---

## HealthService

`HealthService` 位于 `services.health_service`，提供全系统健康监控。

### 构造函数

内部初始化完整的服务栈：`DataService`、`AnalysisService`、`EVTRisk`、`PositionSizer`、`DecisionBrain`。

### 核心方法

| 方法 | 说明 |
|------|------|
| `get_system_health()` | 综合健康检查，返回包含所有组件状态、系统指标和建议的字典。 |
| `get_health_summary()` | 获取健康摘要和状态趋势。 |
| `get_health_history()` | 获取健康检查历史记录（最多保留 100 条）。 |
| `export_health_report(format)` | 导出健康报告（支持 json 和 txt 格式）。 |
| `save_health_report(file_path, format)` | 保存健康报告到文件。 |

### 检查项目

| 检查方法 | 检查内容 |
|----------|----------|
| `_check_config_health()` | 配置验证、brain 配置加载状态 |
| `_check_data_service_health()` | 数据获取测试、缓存统计 |
| `_check_analysis_service_health()` | 宏观分析测试、风险指标计算 |
| `_check_brain_health()` | 决策大脑功能测试 |
| `_check_risk_health()` | EVT 风险计算测试 |
| `_check_cache_health()` | 缓存健康状态 |
| `_check_data_lake_health()` | 数据湖目录和文件数 |
| `_check_system_health()` | CPU/内存/磁盘使用率（依赖 psutil） |

全局单例通过 `get_health_service()` 获取。

---

## CacheCoordinator

`CacheCoordinator` 位于 `services.cache_coordinator`，负责跨服务的缓存管理。

### 核心方法

| 方法 | 说明 |
|------|------|
| `generate_cache_key(prefix, *args, namespace)` | 生成缓存键，格式为 `{namespace}:{prefix}:{arg1_arg2_...}`。 |
| `get(key)` | 获取缓存数据。 |
| `set(key, value, ttl, data_type)` | 设置缓存，`ttl` 根据 `data_type` 自动选择。 |
| `clear()` | 清除所有缓存。 |
| `get_stats()` | 获取缓存统计信息。 |
| `check_health()` | 检查缓存健康状态（命中率、缓存大小等）。 |
| `check_consistency(symbol, cached_data, source_data)` | 检查缓存与数据源的一致性（比较最新时间戳）。 |
| `safe_cache_data(key, data, ttl, data_type)` | 安全缓存操作，失败不影响业务流程。 |

### TTL 策略

根据 `DataServiceConstants` 中的配置，不同数据类型使用不同的 TTL：

| data_type | 常量 |
|-----------|------|
| `"stock"` | `CACHE_TTL_STOCK` |
| `"index"` | `CACHE_TTL_INDEX` |
| `"etf"` | `CACHE_TTL_ETF` |
| `"realtime"` | `CACHE_TTL_REALTIME` |
| `"industry"` | `CACHE_TTL_INDUSTRY` |
| `"concept"` | `CACHE_TTL_CONCEPT` |
| `"general"` | `CACHE_TTL_GENERAL` |

---

## TechnicalService

`TechnicalAnalysisService` 位于 `services.analysis.technical_service`，封装技术分析相关的计算。

### 核心方法

| 方法 | 说明 |
|------|------|
| `run_czsc_analysis(symbol, df)` | 运行缠论分析，调用 `CZSCEngine.get_czsc_signals`。支持缓存（2 小时 TTL）和降级处理。返回信号状态、趋势、支撑/阻力位、笔数等。 |
| `_fallback_czsc_analysis(symbol, df)` | 降级方案：使用 MA 均线交叉和价格动量判断趋势和信号。 |
| `detect_czsc_signals(ticker, data_pack)` | 检测 CZSC 信号并写入 data_pack（`is_3rd_buy`、`bi_count`）。 |
| `calculate_ma_status(data_pack)` | 计算 MA 均线状态（MA20 vs MA60），写入 `data_pack["ma_status"]`。 |
| `calculate_price_and_stop(data_pack)` | 计算当前价格和 ATR 止损价格，写入 `data_pack["price"]` 和 `data_pack["atr_stop"]`。 |

支持内存缓存和磁盘缓存的双级缓存策略。

---

## SignalService

`SignalAnalysisService` 位于 `services.analysis.signal_service`，负责信号层面的分析。

### 核心方法

| 方法 | 说明 |
|------|------|
| `run_fsm_analysis(symbol, df)` | 运行有限状态机分析。调用 `DecisionBrain.make_decision`，输出信号强度、推荐操作、止损/止盈价格。支持缓存和降级。 |
| `_fallback_fsm_analysis(symbol, df)` | 降级方案：使用 MA 短/中/长期均线排列判断多空信号。 |
| `_map_decision_to_recommendation(decision)` | 将 FSM 决策映射为中文推荐操作（通过 `AnalysisServiceConstants.RECOMMENDATION_MAP`）。 |
| `analyze_alpha(data_pack)` | 运行 `AlphaDecoupler` 分析，计算 alpha 评分。基准数据（沪深 300）使用每日缓存。 |
| `calculate_returns(data_pack)` | 计算日收益率序列，写入 `data_pack["returns"]`。 |
| `make_decision(data_pack)` | 调用 FSM 引擎进行决策。 |

### _get_fsm_engine

按需创建 `DecisionBrain` 实例。若未提供 `brain` 参数，自动初始化 `EVTRisk` 和 `PositionSizer` 后构造。
