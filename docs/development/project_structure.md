# UniQuant 项目结构文档

> 版本: 0.1.0 | 最后更新: 2026-05-23

---

## 1. 顶层目录

```
UniQuant/
├── pyproject.toml          — 项目元数据、依赖管理 (PEP 621)
├── config/                 — YAML 配置文件 (策略参数、因子权重、系统设置)
├── data/                   — 运行时数据 (数据湖 lake、缓存 cache、复权因子 factors)
├── logs/                   — 日志输出
├── output/                 — 分析结果输出 (研究报告、扫描结果)
├── scripts/                — 数据工具脚本 (因子计算、数据导入校验、市场扫描)
├── src/uniquant/           — 主源码 (8 个子包)
└── tests/                  — 测试套件 (pytest)
```

---

## 2. src/uniquant/ 源码清单

### 2.1 brain/ — 分析大脑 (核心算法引擎)

```
brain/
├── __init__.py                         — 汇总导出所有引擎: CZSCEngine, NTFEngine, FSM, RegimeDetector, Indicators, StockScreener, AlphaDecoupler, factors, lppl
├── czsc_engine.py                      — [废弃] 兼容桩，重定向至 czsc/czsc_engine.py
├── ntf_engine.py                       — [废弃] 兼容桩，重定向至 ntf/ntf_engine.py
├── regime_detector.py                  — [废弃] 兼容桩，重定向至 regime/regime_detector.py
│
├── alpha_decoupler/
│   ├── __init__.py                     — 导出 AlphaDecoupler
│   └── alpha_decoupler.py              — Alpha 解耦器，计算相对强度 RS Slope 并过滤低相关性资产
│
├── czsc/
│   ├── __init__.py                     — 导出 CZSCEngine, CZSCSignalType, CZSCAnalysisError
│   └── czsc_engine.py                  — 缠中说禅 (CZSC) 分析引擎，基于 czsc 库进行笔/段/中枢识别
│
├── factors/
│   ├── __init__.py                     — 导出 FinancialFactorBridge, FactorAnalyzer, FactorComposer, FactorRegistry
│   ├── analyzer.py                     — 因子分析器，计算因子有效性指标 IC / IR / IC>0 比例
│   ├── composer.py                     — 因子合成器，从 FactorRegistry 读取因子并进行多因子合成
│   ├── custom_factors.py               — 自定义因子库，注册动量、换手率、波动率、价格位置等因子
│   ├── financial_bridge.py             — 财务因子桥接器，将财务 Parquet 中文字段映射为标准因子并计算 PE_TTM / PB
│   ├── registry.py                     — 因子注册中心，所有因子必须在此注册，支持无限扩展
│   └── walk_forward_pipeline.py        — 样本外 Walk-Forward 因子扫描流水线，严格切断训练/测试数据泄漏
│
├── fsm/
│   ├── __init__.py                     — 导出 FSM, FSMState, InvalidInputError, StateTransitionError, DecisionBrain
│   └── fsm.py                          — 有限状态机决策引擎，基于技术指标驱动买入/卖出/持仓状态转换
│
├── indicators/
│   ├── __init__.py                     — 导出 Indicators, IndicatorError
│   └── indicators.py                   — 技术指标计算器，提供 MA/EMA/MACD/RSI/布林带/ATR 等指标计算
│
├── lppl/
│   ├── __init__.py                     — 导出 LPPLCalculator, lppl_func, LPPLConfig, fit_multi_window, SignalClusterDetector, MarketRegimeDetector, LPPLComputation, LPPLDataManager, LPPLVisualizer
│   ├── calculator.py                   — LPPL 计算器，基于差分进化算法拟合 LPPL 模型参数
│   ├── cluster.py                      — 三层 LPPL 系统 Layer 2: 信号聚类检测 (30 天内 danger 信号累积判定)
│   ├── computation.py                  — LPPL 并行计算引擎，基于多进程 ProcessPoolExecutor 批量拟合
│   ├── core.py                         — LPPL 底层数值核心，提供模型函数、代价函数、单窗口拟合、输入校验
│   ├── data_manager.py                 — LPPL 数据管理器，负责数据获取、验证和清洗
│   ├── engine.py                       — LPPL 工业级引擎，包含 Numba 加速算子、多窗口拟合、风险判定、峰值检测
│   ├── multifit.py                     — 三层 LPPL 系统 Layer 1: 多窗口拟合 (短期/中期/长期三层独立拟合)
│   ├── regime.py                       — 三层 LPPL 系统 Layer 3: 市场环境检测 (牛市/熊市信号准确率差异化处理)
│   └── visualizer.py                   — LPPL 可视化器，生成拟合曲线图和风险热力图
│
├── ntf/
│   ├── __init__.py                     — 导出 NTFEngine
│   └── ntf_engine.py                   — 国家队因子引擎 (NTF)，监测 ETF 脉冲式放量异常以识别国家队干预点
│
├── regime/
│   ├── __init__.py                     — 导出 RegimeDetector, Regime, RegimeDetectionError
│   └── regime_detector.py              — 市场状态检测器，识别 NORMAL / STRESSED / FROZEN 三种市场状态
│
├── screener/
│   ├── __init__.py                     — 导出 StockScreener, ScreenerConfig
│   └── screener.py                     — 全市场扫描器，基于 composite_score 生成 Top/Bottom 榜单并进行技术信号验证
│
└── wyckoff/
    ├── __init__.py                     — 导出 WyckoffEngine, FusionEngine, ImageEngine, WyckoffStateManager, 模型类, WyckoffConfig, V3Rules, WyckoffReportGenerator
    ├── analysis.py                     — Wyckoff 分析函数，从 engine.py 提取的筹码分析、多时间框架分析
    ├── classifiers.py                  — Wyckoff 分类函数，阶段识别、量能分类、涨跌停判定
    ├── config.py                       — Wyckoff 配置管理，管理规则引擎、图像引擎、融合引擎的配置参数
    ├── engine.py                       — v3.0 威科夫分析引擎，唯一入口，合并分析器与数据引擎
    ├── fusion_engine.py                — Wyckoff 融合引擎，融合数据引擎和图像引擎的分析结果并处理冲突
    ├── image_engine.py                 — Wyckoff 图像引擎，扫描图表文件夹、提取视觉证据、识别时间周期
    ├── models.py                       — Wyckoff 数据模型定义 (WyckoffPhase, WyckoffSignal, WyckoffReport, TradingPlan 等)
    ├── reporting.py                    — 威科夫报告生成器，输出 Markdown / HTML / CSV / JSON 报告
    ├── rules.py                        — v3.0 规则执行器，10 条规则的独立验证层
    ├── state.py                        — Wyckoff 状态管理器，分析状态持久化、连续性追踪和 Spring 冷冻期管理
    └── trading.py                      — Wyckoff 交易模拟工具函数，正确模拟入场价、止损、止盈逻辑
```

### 2.2 data/ — 数据层 (获取、存储、清洗、导入)

```
data/
├── __init__.py                         — 数据模块初始化，导出 DataFetcher, DataLake, DataPipeline, LPPLDataService (延迟导入)
├── data_fetcher.py                     — 数据获取器，系统总指挥，协调路由/存储/清洗/复权的完整数据流水线
├── manager.py                          — 数据管理器简化入口，封装 StorageManager 的读取操作
├── tdx_loader.py                       — 通达信数据加载器，使用 pytdx 读取 .day 文件
│
├── lake/
│   ├── __init__.py                     — 导出 StorageManager (延迟导入)
│   └── storage_manager.py              — 存储管理器，负责 Parquet 文件读写、目录管理、文件锁定
│
├── managers/
│   ├── __init__.py                     — 导出 DataSourceAdapter, StandardAdapter, SourceRouter, StockMetadataManager
│   ├── adjust_factor_manager.py        — 复权因子管理器，从 GBBQ 文件获取除权因子
│   ├── baostock_cache_manager.py       — Baostock 缓存管理器，获取全量股票代码并创建本地缓存
│   ├── cache_manager.py                — 综合缓存管理器，协调创建股票代码缓存和交易日历缓存
│   ├── data_normalizer.py              — 数据标准化门面 (facade)，实际实现已迁移至 utils/normalizer.py
│   ├── factor_manager.py               — 复权因子管理器，负责复权因子的计算、存储和管理
│   ├── market_data_coordinator.py      — 市场数据协调器，获取指数、ETF、行业、概念等市场级数据
│   ├── source_router.py                — 数据源路由中心，管理多数据源并发获取与健康状态
│   ├── standard_adapter.py             — 数据源适配器接口与标准适配器实现
│   ├── stock_data_updater.py           — 股票数据更新器，负责增量更新、脏数据清洗、并行更新
│   ├── stock_metadata_manager.py       — 股票元数据管理器，管理 IPO 日期、退市日期、板块等元数据
│   ├── tdx_updater.py                  — 通达信数据更新器，批量更新日线数据和 GBBQ 数据 (智能增量策略)
│   └── trade_calendar_manager.py       — 交易日历管理器，获取并缓存完整交易日历
│
├── parsers/
│   ├── __init__.py                     — 导出 parse_gbbq_native
│   └── tdx_parser.py                   — 通达信文件解析器，解析 .day 日线文件和 gbbq 除权文件
│
├── pipeline/
│   ├── __init__.py                     — 导出 DataCleaner, DataValidator, DataAdjuster
│   ├── data_adjuster.py                — 数据复权器，核心复权算法实现
│   ├── data_cleaner.py                 — 数据清洗器，标准化列名、去重、异常值处理
│   └── data_validator.py               — 数据验证器，校验必要列、数据类型、数据完整性
│
├── scripts/
│   ├── download_baostock_factors.py    — 从 Baostock 下载全量因子数据
│   ├── download_baostock_pro.py        — Baostock 专业版下载脚本，全量股票代码批量下载
│   ├── update_daily_data_akshare.py    — AKShare 东方财富数据更新脚本，包含原始/前复权/后复权价格
│   └── update_daily_incremental.py     — AKShare 日线数据增量更新脚本 v2.0，支持断点续传和安全写入
│
├── services/
│   ├── __init__.py                     — (空)
│   ├── data_importer.py                — 数据导入工具，将 CSV 数据转换为 Parquet 格式，支持通达信 TDX 导入
│   ├── import_1min.py                  — 1 分钟线数据导入模块，从通达信本地文件多线程导入到数据湖
│   ├── import_5min.py                  — 5 分钟线数据导入模块，从通达信本地文件多线程导入到数据湖
│   ├── import_financial.py             — 财务数据导入模块，解析通达信 gpcw*.dat 文件 (两阶段: 多线程解析 + 顺序写入)
│   ├── import_index.py                 — TDX 指数数据导入器，从通达信导入上证综指/沪深 300 等主要指数
│   └── lppl_data_service.py            — LPPL 数据服务，专门为 LPPL 引擎提供数据获取、清洗和存储
│
├── sources/
│   ├── base.py                         — 数据源基类，定义 fetch_daily 等抽象接口
│   ├── protocols.py                    — 数据源能力协议 (Protocol)，定义 HasBasicInfo、HasFundFlow 等可选能力
│   ├── baostock.py                     — Baostock 数据源实现，免费开源，支持前/后/不复权
│   ├── eastmoney.py                    — 东方财富数据源实现，基于 AKShare 包装
│   ├── sina.py                         — 新浪财经数据源实现，基于 AKShare 包装
│   ├── tencent.py                      — 腾讯财经数据源实现，基于 AKShare 包装
│   ├── ths.py                          — 同花顺数据源实现，支持 JS 加密参数生成
│   ├── tdx.py                          — 通达信本地数据源，解析 .day 二进制文件
│   └── realtime_bridge.py              — 实时行情桥接引擎，WebSocket 轻量级桥接，支持盘中实时推送
│
└── utils/
    ├── __init__.py                     — 数据工具包 (空导出)
    ├── akshare_market_service.py       — AKShare 行情服务封装，获取日线/分钟线/指数等市场数据
    ├── akshare_reference_service.py    — AKShare 参考数据服务，获取行业/概念/新闻等参考信息
    ├── akshare_wrapper.py              — AKShare 统一包装器，集成行情服务和参考服务，提供重试和错误处理
    ├── js_executor.py                  — JavaScript 执行器，使用 py_mini_racer 执行 ths.js 生成加密参数
    ├── normalizer.py                   — 数据标准化模块，统一处理所有数据源输出的列名和格式
    ├── request_utils.py                — 请求工具模块，实现指数退避重试和请求间隔控制
    └── smart_factor_calculator.py      — 智能复权因子计算器 (V15 版)，GBBQ 数据清洗与并行计算
```

### 2.3 hands/ — 策略执行层 (回测、策略、报告)

```
hands/
├── __init__.py                         — 策略执行模块初始化，导出 Reporter, ResultsManager, strategies (延迟导入)
├── reporter.py                         — 研究报告生成器，生成标准化 Markdown 研究报告
├── results_manager.py                  — 计算结果管理器，管理分析结果的存储、读取和报告生成
│
├── backtest/
│   ├── __init__.py                     — 导出 BacktestEngine, BacktestResult, TradeRecord, SignalBacktestIntegrator, PortfolioEngine, MonteCarloSimulator, OverfittingDetector, RobustnessChecker, SensitivityAnalyzer, BenchmarkComparator, BacktestReportGenerator
│   ├── engine.py                       — 回测引擎核心，基于策略协议驱动逐日回测并生成绩效统计
│   ├── result.py                       — 回测结果数据结构，定义 TradeRecord 和 BacktestResult
│   ├── unified_matching_engine.py      — 统一向量化撮合引擎，强制 T+1、涨跌停、印花税、滑点等 A 股约束
│   ├── portfolio_engine.py             — 投资组合回测引擎，使用 UnifiedMatchingEngine 强制 A 股约束
│   ├── signal_integrator.py            — 信号回测集成器，将信号系统与回测引擎对接
│   ├── benchmark.py                    — 基准比较器，计算 CAPM Alpha/Beta、跟踪误差、信息比率
│   ├── monte_carlo.py                  — Monte Carlo 回测模拟器，提供随机排列和 Bootstrap 重采样
│   ├── overfitting_detector.py         — 过拟合检测器，实现 Deflated Sharpe Ratio 和最大回撤显著性检验
│   ├── robustness_checker.py           — 策略稳健性检查器，检查不同市场条件下的表现稳健性
│   ├── sensitivity_analyzer.py         — 参数敏感性分析器，提供 OAT 分析和龙卷风图数据
│   ├── report_generator.py             — 回测报告生成器，生成 HTML 格式的回测报告
│   │
│   └── trade_analysis/
│       ├── __init__.py                 — 导出 TradeAnalyzer, TradeStatistics
│       ├── analyzer.py                 — 交易分析器，提供盈亏分析、时间维度分析、市场状态分析
│       └── statistics.py               — 交易统计计算器，计算盈亏比、平均收益、最大连续亏损等指标
│
└── strategies/
    ├── __init__.py                     — 导出所有策略: BaseStrategy, FSMStrategy, run_backtest, STRATEGY_MAP, trade_wyckoff, trade_ma, trade_str_reversal 等
    ├── base.py                         — 策略基类，定义 StrategyResult 数据类，可选依赖 backtrader
    ├── backtest.py                     — 回测运行器，负责加载数据、并行执行策略、汇总结果
    ├── fsm_strategy.py                 — FSM 策略 (backtrader)，基于 MA20/MA60 趋势分析的买卖策略
    ├── indicators.py                   — 策略级指标计算工具函数 (ATR 等)
    ├── ma_cross.py                     — 均线交叉策略，基于短期/长期均线金叉死叉信号
    ├── regime.py                       — 市场状态判断函数，基于 MA120/MA60 划分牛/熊/震荡
    ├── registry.py                     — 策略注册表，映射策略名称到执行函数 (STRATEGY_MAP)
    ├── str_reversal.py                 — 反转策略，基于短期超卖反弹逻辑
    ├── wyckoff.py                      — Wyckoff 策略 (v1)，基于 WyckoffEngine 信号的交易策略
    └── wyckoff_strategy.py             — Wyckoff 策略 (v2)，改进版 Wyckoff 交易策略
```

### 2.4 services/ — 服务层 (业务编排与协调)

```
services/
├── __init__.py                         — 导出 CacheCoordinator, DataQualityService, DataService, HealthService, PortfolioService, ScanPipeline, StockQueryService, ValidationService
├── analysis_service.py                 — 综合分析服务，协调宏观/技术/信号/威科夫分析并汇总结果
├── cache_coordinator.py                — 缓存协调器，负责缓存一致性、健康管理和缓存操作
├── data_access_service.py              — 数据访问服务，协调缓存/数据源/数据湖的读取与持久化
├── data_quality_service.py             — 数据质量服务，负责数据质量检查、报告生成和监控
├── data_service.py                     — 数据服务 (门面模式)，协调 DataFetcher / StorageManager / CacheCoordinator
├── health_service.py                   — 系统健康服务，检查各模块运行状态并生成健康报告
├── portfolio_service.py                — 投资组合服务，提供组合风险计算、持仓分析、再平衡建议
├── scan_service.py                     — 全市场扫描流水线服务，端到端编排: 数据加载 -> 因子计算 -> IC/IR -> 合成 -> 扫描 -> 输出
├── service_container.py                — 依赖注入容器，消除循环依赖，以 DAG 拓扑初始化所有服务
├── stock_query_service.py              — 股票查询服务，负责股票代码映射、名称查询和 ETF 列表管理
├── validation_service.py               — 验证服务，与标准计算方法的对比和验证
│
└── analysis/
    ├── __init__.py                     — 导出 MacroAnalysisService, TechnicalAnalysisService, SignalAnalysisService, WyckoffAnalysisEngine
    ├── czsc_analysis_engine.py         — 缠论 (CZSC) 分析引擎，封装 CZSCEngine 的服务层调用
    ├── engine_factory.py               — 分析引擎工厂，延迟初始化各分析引擎实例
    ├── fsm_analysis_engine.py          — 有限状态机 (FSM) 分析引擎，封装 FSM 的服务层调用
    ├── lppl_analysis_engine.py         — LPPL 分析引擎，封装 LPPL 模型拟合与风险判定的服务层调用
    ├── macro_analysis_engine.py        — 宏观分析引擎，整合 LPPL / Regime / NTF 的综合宏观分析
    ├── macro_service.py                — 宏观分析服务，LPPL 泡沫检测 / 市场状态检测 / 国家队干预检测
    ├── ntf_analysis_engine.py          — 国家队干预 (NTF) 检测引擎，封装 NTFEngine 的服务层调用
    ├── regime_analysis_engine.py       — 市场状态 (Regime) 检测引擎，封装 RegimeDetector 的服务层调用
    ├── report_generator_engine.py      — 研究报告生成与读取引擎
    ├── signal_service.py               — 信号分析服务，FSM 决策分析 / Alpha 分析 / 收益率计算
    ├── technical_service.py            — 技术分析服务，CZSC 缠论分析 / MA 均线 / ATR 止损
    └── wyckoff_analysis_engine.py      — 威科夫分析引擎，封装 WyckoffEngine 的服务层调用
```

### 2.5 shared/ — 共享基础设施 (常量、工具、缓存、异常)

```
shared/
├── __init__.py                         — 导出 AnalysisResult, 常量类, LoggerFactory, retry, 工具函数等
├── analysis_result.py                  — 分析结果统一格式模块，提供 AnalysisResult / AnalysisResultBuilder / AnalysisStatus
├── backtest_utils.py                   — 回测工具函数，提供停牌股过滤 (filter_suspended) 等
├── config_loader.py                    — 配置加载器 (单例)，从 config/*.yaml 加载并提供统一配置接口
├── constants.py                        — 全局常量定义，按功能模块分组 (日期、网络、指标阈值、风险、缓存、回测等)
├── cost_model.py                       — 统一交易成本模型，佣金/印花税/最低佣金/滑点的唯一真值源
├── di_container.py                     — [废弃] 旧版依赖注入容器，已迁移至 ServiceContainer
├── env_config.py                       — 环境变量配置模块，确保底层并行库不与 Python 多进程冲突
├── error_handling.py                   — 错误处理装饰器框架，提供 handle_errors / validate_inputs 等
├── errors.py                           — [废弃] 旧版异常模块，保留用于向后兼容
├── exceptions.py                       — 统一异常体系，AlphaTacticianError 为基类，派生数据/分析/风险等异常
├── import_state.py                     — 导入状态管理模块，提供线程安全的导入进度跟踪
├── interfaces.py                       — 协议接口定义 (Protocol)，MarketRegime / DataFetcherProtocol / PositionSizerProtocol 等
├── limit_checker.py                    — 涨跌停检查模块，A 股微观结构防御 (主板 10% / 科创 20% / 北交所 30%)
├── limits.py                           — 涨跌停判定工具函数，基于收盘价和前收判断涨停/跌停
├── loader.py                           — 策略权重加载器，从 trading.yaml 读取策略权重配置
├── logger_factory.py                   — Logger 工厂模块，统一管理所有模块的日志创建和配置
├── optimal_params.py                   — 最优参数加载器，从 optimal_params.yaml 读取 LPPL 等引擎参数
├── parallel.py                         — 并行计算工具，提供最优 worker 数量计算
├── retry_decorator.py                  — 重试装饰器模块，提供统一的指数退避重试逻辑
├── slippage_model.py                   — 滑点模型定义，包含默认滑点和动态滑点实现
├── utils.py                            — 通用工具函数，with_timeout / safe_execute / normalize_dataframe 等
│
└── cache/
    ├── __init__.py                     — 统一缓存管理模块，导出 smart_cache 装饰器、CacheFactory、后端实现
    ├── backends.py                     — 缓存后端实现，DiskCacheBackend (joblib 持久化) 和 MemoryCacheBackend
    ├── cache_factory.py                — 缓存工厂，根据类型创建不同缓存实例
    └── cache_interface.py              — 缓存接口定义 (ABC)，统一 get / set / delete / clear 接口
```

### 2.6 signal/ — 信号层 (信号标准化、聚合、质量评估)

```
signal/
├── __init__.py                         — 导出 Signal, SignalBatch, SignalType, SignalSource, SignalNormalizer, SignalAggregator, SignalQualityAssessor, SignalDatabase 等
├── models.py                           — 信号数据模型定义 (Signal, SignalBatch, SignalType, SignalSource, SignalStrength, SignalConsensus 等)
├── normalizer.py                       — 信号标准化器，将各引擎 (LPPL/Wyckoff/Indicator/CZSC) 原始输出转换为统一信号格式
├── aggregator.py                       — 信号聚合器，支持加权平均/多数投票/最大置信度/共识阈值等聚合方法
├── quality.py                          — 信号质量评估，计算精确率/召回率/F1/命中率等质量指标
└── db.py                               — 信号数据库，基于 SQLAlchemy 的信号持久化存储与查询
```

### 2.7 risk/ — 风险管理层

```
risk/
├── __init__.py                         — 导出 PositionSizer, PortfolioOptimizer, HistoricalSimulationRisk, StructuralRiskManager
├── drawdown_analyzer.py                — 向量化极限回撤分析引擎，全 NumPy 算子计算 MDD / Calmar
├── evt_risk.py                         — 极端值风险计算器 (EVT)，VaR / CVaR / 压力测试
├── historical_risk.py                  — 历史模拟风险计算器，继承 EVTRisk 的兼容包装
├── portfolio_optimizer.py              — 组合优化模块，实现 Risk Parity (风险平价) 和 Mean-Variance (均值-方差) 优化
├── sizer.py                            — 仓位计算器 (PositionSizer)，基于 Kelly / ATR / 固定比例等方法计算仓位
└── structural.py                       — 结构性风险管理器，实现多指数风险矩阵并提供整体风险评估
```

### 2.8 ui/ — 用户界面层 (Streamlit 仪表盘)

```
ui/
├── __init__.py                                 — 导出 AssetManager, ManagerReportService, ManagerPortfolioAnalyticsService, LPPLVisualizer, ModuleHealthChecker
├── components.py                               — Streamlit UI 组件，研究报告 HTML 预览渲染
├── dashboard.py                                — Streamlit 主仪表盘，集成 AgGrid / 自动刷新 / 交互式分析界面
├── health_check.py                             — 模块健康检查器，验证所有核心模块的导入完整性
├── lppl_visualizer.py                          — LPPL 可视化模块，使用 Plotly 绘制拟合曲线和风险图表
├── manager_logic.py                            — 资产管理器核心逻辑 (AssetManager)，协调分析/数据/组合服务
├── manager_portfolio_analytics_service.py      — 组合分析服务 (UI 层)，为资产管理器提供风险指标计算
└── manager_report_service.py                   — 报告服务 (UI 层)，为资产管理器提供报告预览/导出/对比
```

---

## 3. config/ 配置文件清单

```
config/
├── config.yaml
├── factors.yaml
├── optimal_params.yaml
└── trading.yaml
```

### config.yaml — 主配置文件

集中管理所有配置项，按功能模块划分:

| 配置段 | 说明 |
|--------|------|
| `base.data_lake` | 数据湖路径、压缩格式、引擎 (duckdb) |
| `base.logging` | 日志级别、格式 |
| `base.tdx` | 通达信本地数据路径 |
| `cache.global` | 缓存开关、路径、最大保存天数、批量大小 |
| `cache.ttl` | 各类数据的缓存 TTL (秒) |

### factors.yaml — 因子配置文件

定义各因子的启用状态、权重和分类:

| 配置段 | 说明 |
|--------|------|
| `factors.<因子名>.enabled` | 是否启用 |
| `factors.<因子名>.weight` | 因子权重 |
| `factors.<因子名>.category` | 因子分类 (technical / fundamental) |

已配置因子: `momentum_20d`, `turnover_momentum_20d`, `pe_ttm`。

### optimal_params.yaml — 最优参数配置

LPPL 引擎和信号模型的最优参数:

| 配置段 | 说明 |
|--------|------|
| `defaults` | 默认参数 (优化器、前瞻天数、阈值、趋势 MA 等) |
| `window_sets` | 窗口集合定义 (如 `narrow_40_120`) |

### trading.yaml — 交易配置文件

数据路径和策略参数:

| 配置段 | 说明 |
|--------|------|
| `data.tdx_paths` | 通达信数据目录 (上海/深圳) |
| `data.db_path` | 交易数据库路径 |
| `data.csi300_path` | 沪深 300 指数数据路径 |
| `strategies.wyckoff` | Wyckoff 策略参数 (回望天数、权重、阈值、最低置信度) |
| `strategies.ma_atr` | 均线 ATR 策略参数 (快慢周期、ATR 周期、权重) |
| `strategies.reversal` | 反转策略参数 (回望天数、阈值、持仓天数、止盈比例) |

---

## 4. scripts/ 脚本清单

```
scripts/
├── calculate_factors_single.py     — 单进程计算复权因子 (用于调试)
├── calculate_factors_v15.py        — V15 版多进程并行计算复权因子
├── download_etf_data.py            — 从通达信本地数据导入国家队 ETF 数据 (用于 NTF 检测)
├── full_comparison.py              — 全量对比本地计算的复权因子与 Baostock 因子
├── rebuild_financial_lake.py       — 重建财务数据湖并输出基础质量校验结果
├── run_market_scan.py              — 启动全市场扫描流水线
├── test_incremental_update.py      — 测试增量更新功能，抽样 100 个代码进行校验
├── verify_200.py                   — 兼容入口: 随机抽样 200 只股票验证通达信导入
├── verify_import.py                — 兼容入口: 深度抽样校验 500 只股票
└── verify_tdx_import.py            — 统一的通达信导入校验脚本 (支持多种校验模式)
```

---

## 5. tests/ 测试文件清单

```
tests/
├── conftest.py                                     — Pytest 配置，提供通用 fixture
│
│   ─── 数据层测试 ───
├── test_akshare_market_service.py                  — AKShare 行情服务单元测试
├── test_akshare_reference_service.py               — AKShare 参考数据服务单元测试
├── test_data_access_service.py                     — 数据访问服务测试 (缓存优先读取)
├── test_data_and_stock_query_regressions.py        — DataService / StockQueryService 回归测试
├── test_data_fetcher_init_fault_tolerance.py       — DataFetcher 初始化容错测试 (单源/全源失败)
├── test_field_mapping.py                           — 数据字段映射一致性验证
├── test_import_financial.py                        — 财务数据导入链路测试
├── test_import_state.py                            — 导入状态管理器测试 (线程安全计数器)
├── test_realtime_bridge.py                         — 实时行情桥接引擎单元测试
├── test_smart_factor_calculator.py                 — 智能复权因子计算器测试
├── test_tdx_incremental.py                         — 通达信增量更新测试
├── test_verify_tdx_import.py                       — 通达信导入校验脚本测试
│
│   ─── 分析引擎测试 ───
├── test_alpha_decoupler.py                         — Alpha 解耦器测试 (停牌复牌场景)
├── test_analysis_engines.py                        — CzscAnalysisEngine / FsmAnalysisEngine 测试
├── test_analysis_result_helpers.py                 — AnalysisResult 辅助方法测试
├── test_analysis_service_strength_div_zero.py      — AnalysisService 中 strength 除零防御测试
├── test_brain_additional.py                        — NTFEngine / RegimeDetector 废弃导入兼容测试
├── test_czsc_bar_list_vectorization.py             — CZSCEngine 向量化优化等价性测试
├── test_czsc_engine.py                             — 缠论引擎单元测试
├── test_fsm.py                                     — 有限状态机逻辑正确性测试
├── test_indicators.py                              — 技术指标计算正确性测试
├── test_lppl_calculator_defense.py                 — LPPL 计算器防御编程测试 (零/负价格、缓存键稳定性)
├── test_lppl_engine_scan_windows.py                — LPPL 引擎多窗口扫描测试
├── test_ntf_engine.py                              — 国家队因子引擎单元测试
├── test_regime_detector.py                         — 市场状态检测器单元测试
├── test_stock_screener.py                          — 全市场扫描器测试
│
│   ─── 因子系统测试 ───
├── test_custom_factors.py                          — 自定义因子注册与计算测试
├── test_factor_analyzer.py                         — 因子分析器 IC/IR 计算测试
├── test_factor_composer.py                         — 因子合成器测试
├── test_factor_div_zero_defense.py                 — 自定义因子除零 / NaN 防御测试
├── test_factor_registry.py                         — 因子注册中心功能测试
├── test_financial_bridge.py                        — 财务因子桥接器测试
├── test_lookahead_bias.py                          — 因子分析器未来函数防护测试
├── test_walk_forward_pipeline.py                   — Walk-Forward 流水线测试
│
│   ─── 回测与策略测试 ───
├── test_backtest_engine.py                         — 回测引擎核心逻辑测试
├── test_hands_strategies.py                        — 策略基类与 FSM 策略测试
├── test_matching_engine.py                         — 统一撮合引擎测试 (涨跌停/T+1/佣金/滑点)
├── test_portfolio_engine_v2.py                     — 投资组合回测引擎测试
├── test_t1_constraint_boundary.py                  — T+1 约束边界条件测试
│
│   ─── 风险管理测试 ───
├── test_cvar_empty_tail.py                         — CVaR 空尾部防御测试
├── test_drawdown_analyzer.py                       — 回撤分析器测试 (零回撤/精确 MDD/滚动窗口)
├── test_evt_risk.py                                — 极端值风险压力测试逻辑验证
├── test_portfolio_optimizer.py                     — 组合优化器单元测试
├── test_sizer.py                                   — 仓位计算器正确性测试
│
│   ─── 服务层测试 ───
├── test_di_container_and_cache.py                  — DI 容器与缓存后端测试
├── test_engine_factory.py                          — 分析引擎工厂测试
├── test_error_handling.py                          — 线程安全错误统计测试
├── test_error_handling_additional.py               — 错误处理装饰器扩展测试
├── test_final_service_regressions.py               — CacheCoordinator / DataQualityService / PortfolioService 回归测试
├── test_limit_checker.py                           — 涨跌停检查功能测试
├── test_macro_and_fsm_engine_regressions.py        — MacroAnalysisEngine / FsmAnalysisEngine 回归测试
├── test_macro_and_scan_regressions.py              — MacroAnalysisService / ScanPipeline 回归测试
├── test_more_analysis_engine_regressions.py        — Czsc / LPPL / Regime 分析引擎回归测试
├── test_report_and_ntf_regressions.py              — NTF / 报告生成引擎回归测试
├── test_report_paths.py                            — 报告路径与输出目录测试
├── test_results_manager_extra.py                   — 结果管理器扩展测试
├── test_results_protocol.py                        — 结果协议一致性测试
├── test_retry_and_utils.py                         — 重试装饰器与工具函数测试
├── test_service_container.py                       — ServiceContainer 依赖注入测试
├── test_technical_and_signal_regressions.py        — 技术分析 / 信号分析服务回归测试
├── test_validation_service.py                      — 验证服务功能测试
│
│   ─── UI 层测试 ───
├── test_manager_portfolio_analytics_service.py     — 组合分析服务 (UI) 测试
│
│   ─── 脚本测试 ───
├── test_build_financial_v2.py                      — 财务数据构建脚本测试
├── test_offline_entry.py                           — 离线测试脚本编译验证
└── test_stock_list_cli.py                          — 股票列表 CLI 脚本测试
```

---

## 6. 包依赖关系

以下是各包之间的高层依赖关系 (有向无环图 DAG):

```
                    ┌──────────┐
                    │  shared   │  无内部依赖 (基础设施层)
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              v          v          v
         ┌────────┐ ┌────────┐ ┌────────┐
         │  data   │ │  risk   │ │ signal │
         └────┬───┘ └────┬───┘ └────┬───┘
              │          │          │
              v          │          │
         ┌────────┐      │          │
         │  brain  │─────┘          │
         └────┬───┘                 │
              │                     │
              ├─────────────────────┘
              v
         ┌────────┐
         │  hands  │
         └────┬───┘
              │
              v
        ┌──────────┐
        │ services  │
        └────┬─────┘
             │
             v
        ┌──────────┐
        │    ui     │
        └──────────┘
```

### 详细依赖说明

| 包 | 依赖 | 说明 |
|-----|------|------|
| **shared** | (无) | 基础设施层: 常量、异常、日志、缓存、配置加载、工具函数 |
| **data** | shared | 数据获取/存储/清洗/导入，使用 shared 的常量、日志、异常、重试机制 |
| **risk** | shared | 风险计算模块，使用 shared 的常量、日志、异常 |
| **brain** | shared, data | 核心分析引擎，使用 shared 的配置/常量/缓存，使用 data 的数据获取服务 |
| **signal** | shared, brain | 信号标准化层，将 brain 各引擎输出转换为统一信号格式 |
| **hands** | shared, brain, risk, signal | 策略执行层，调用 brain 引擎生成信号，使用 risk 计算仓位，使用 signal 进行信号集成 |
| **services** | shared, data, brain, risk, signal, hands | 服务编排层，协调所有下层模块提供业务功能 |
| **ui** | shared, services | 用户界面层，通过 services 层访问所有功能，不直接依赖底层模块 |

### 关键设计原则

1. **单向依赖**: 依赖关系严格单向，禁止循环依赖
2. **延迟导入**: 使用 `__getattr__` 和 `TYPE_CHECKING` 避免导入时循环
3. **依赖注入**: `ServiceContainer` 以 DAG 拓扑顺序初始化所有服务，消除隐式耦合
4. **协议驱动**: 通过 `Protocol` 接口解耦模块间依赖，降低编译时耦合度
