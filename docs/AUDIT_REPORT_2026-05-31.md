# UniQuant 项目全维度深度审计报告

> **审计角色**: 顶级量化金融算法工程师 × 顶级Python程序员 × 顶级A股交易员
> **审计范围**: 7大维度 × 150+ 源码模块 × 64 测试文件 × 4 配置文件
> **审计日期**: 2026-05-31

---

## 总体评估

| 维度 | 评分 | 核心问题 |
|------|------|---------|
| 架构设计 | **6.0/10** | 5层DAG理念正确但UI层5处违规；两套DI容器并存 |
| 量化算法 | **5.5/10** | FSM 3个状态不可达；LPPL 3种独立+1种内联函数实现不统一；CZSC致命导入缺失 |
| A股合规性 | **5.0/10** | 印花税日期标注错误；新股涨跌停缺失；价格笼子比例错误 |
| 代码质量 | **5.4/10** | 线程安全大面积缺失；异常捕获顺序错误；常量重复定义严重 |
| 配置系统 | **4.0/10** | "双重真值源"问题——YAML与常量9处数值冲突 |
| 测试覆盖 | **4.5/10** | signal/wyckoff/策略/高级回测零覆盖；测试空白恰在最关键模块 |
| 导入链 | **7.0/10** | 原始5大阻塞已修复3个；残留2个幽灵`__all__`和1个NoneType崩溃 |

**综合评分: 5.3/10** — 项目处于重构中期，基础设施和核心算法存在影响回测正确性的严重缺陷，需优先修复后再继续功能开发。

---

## 一、架构设计分析

### 1.1 Protocol 接口分析

| Protocol | 职责 | 评估 |
|----------|------|------|
| `DataFetcherProtocol` | 数据获取 | 接口清晰，方法签名合理 |
| `RiskAssessmentProtocol` | 风险评估 | 接口过于简单，仅一个 `calculate_metrics` |
| `PositionSizerProtocol` | 仓位计算 | `czsc_bottom: Any` 类型不精确 |
| `AnalysisEngineProtocol` | 分析引擎 | 与 CalculationPluginProtocol 高度重复 |
| `CalculationPluginProtocol` | 计算插件 | 多了 name/version/description 属性 |

**设计缺陷:**

1. **AnalysisEngineProtocol 与 CalculationPluginProtocol 职责重叠**: 两者核心方法签名几乎一致（`analyze(data, **kwargs) -> Dict` vs `calculate(data, **kwargs) -> Dict`），仅差元数据属性。建议合并或建立继承关系。

2. **CalculationRegistry 不应出现在 interfaces.py 中**: 这是一个具体实现类，不是接口定义，违反了接口文件的单职责原则。应移至独立的 registry 模块。

3. **缺少关键 Protocol**: 系统中缺少 `DataServiceProtocol`、`StorageManagerProtocol`、`DecisionBrainProtocol` 等核心接口。

4. **PositionSizerProtocol 类型不精确**: `czsc_bottom: Any` 应该定义为 `Optional[float]`。

5. **MarketSignalContext 职责过重**: 该 dataclass 包含 17 个字段，混合了市场状态、技术指标、价格数据和元数据。建议拆分为 `MarketContext` + `TechnicalIndicators` + `PriceData`。

### 1.2 ServiceContainer 与 DI 容器

**关键发现:**

1. **两套 DI 系统并存**: `shared/di_container.py` 的 `DIContainer` 和 `services/service_container.py` 的 `ServiceContainer` 功能高度重叠，但互不关联。DIContainer 支持 factory 注册，ServiceContainer 支持 initialize 拓扑初始化。DIContainer 的全局实例未被任何地方使用。

2. **ServiceContainer 初始化不完整**: `initialize()` 方法仅注册了 5 个服务（storage、calendar、cache、data_service、engine_factory），`service_container.py` 中不存在 `__all__`。AnalysisService、HealthService、PortfolioService 等核心服务均未注册。

3. **线程安全差异**: DIContainer 使用 `RLock`（可重入锁），ServiceContainer 使用 `Lock`（普通锁）。DIContainer 的 `get()` 方法在锁内执行 factory 创建，可能导致长时间持锁。

**建议:** 合并为一个 DI 容器，保留 ServiceContainer 的拓扑初始化 + DIContainer 的 factory 注册能力。

### 1.3 AnalysisEngineFactory

1. **brain 属性破坏了统一模式**: `brain` 属性直接 `from ...brain.fsm import DecisionBrain`，没有走 `_lazy_init` 统一路径，且构造参数不同。

2. **orchestrator 语义模糊**: 在 ServiceContainer 中传入 DataService，在 AnalysisService 中传入 AnalysisService。同一个参数名，两种完全不同的类型，违反里氏替换原则。

3. **错误静默吞没**: 初始化失败时仅 `logger.warning` 并返回 None，调用方需要频繁做 None 检查。

4. **缺少引擎生命周期管理**: 没有 `shutdown()`、`health_check()` 或 `reset()` 方法。

### 1.4 5 层 DAG 依赖规则检查

**UI 层 5 处 DAG 违规**（最严重）:

| 严重度 | 依赖方向 | 文件 | 说明 |
|--------|----------|------|------|
| 高 | ui -> brain | lppl_visualizer.py:9 | UI 直接访问 brain 层 |
| 高 | ui -> data | lppl_visualizer.py:10 | UI 直接访问 data 层 |
| 高 | ui -> risk | manager_portfolio_analytics_service.py:23 | UI 直接访问 risk 层 |
| 高 | ui -> brain | dashboard.py:612 | UI 直接访问 brain 层 |
| 中 | services -> hands | report_generator_engine.py:159 | services 不应依赖 hands |

**循环依赖风险:**

1. **brain <-> risk 运行时耦合**: `brain/fsm/fsm.py` 延迟导入 `risk.evt_risk` 和 `risk.sizer`，如果未来 risk 层需要访问 brain 的信号，就会形成循环。

2. **AnalysisService 的 God Object 问题**: 被作为 `orchestrator` 传给所有分析引擎，创建间接循环引用。

3. **ServiceContainer.initialize() 中的延迟导入**: 如果 DataService 的模块级代码触发了 ServiceContainer 的初始化，会形成导入循环。

### 1.5 GlobalConfig 配置加载器

1. **`_config` 是类变量而非实例变量**: 在 `__new__` 创建实例前就被所有潜在实例共享，设计隐患。

2. **`_root_dir` 也是类变量**: `Path(__file__).parent.parent.parent.resolve()` 在类定义时求值，如果项目被安装为 egg/wheel，路径可能不正确。

3. **get_config() 线程安全已有保障**: `GlobalConfig.__new__` 使用双重检查锁定模式（`cls._lock`），单例创建是线程安全的。模块级 `config` 变量存在轻微竞态，但不是 P1 级问题，无需紧急修复。

4. **缺少 set() 方法**: 配置加载后无法运行时修改，测试时无法注入 mock 配置。

5. **LOG_DIR 和 CACHE_DIR 有副作用**: 属性访问时自动创建目录，违反命令查询分离原则（CQS）。

---

## 二、核心量化算法分析

### 2.1 CZSC 缠论引擎

**BUG: AnalysisError 未导入（致命）**

`@handle_errors(AnalysisError, ...)` 中 `AnalysisError` 未在文件顶部导入（仅导入了 `CZSCEngineError`），**模块加载时**即抛出 `NameError`（非运行时），导致整个模块无法导入。同样的问题出现在 `get_czsc_signals` 方法（第 147 行和第 442 行）。

**价格验证逻辑不完整**: 只验证了 `low <= close <= high` 和 `low <= open <= high`，没有验证 `low <= high`。

**缠论核心逻辑完全外包**: 引擎本身不实现笔、线段、中枢的判断逻辑，完全依赖 `czsc` 第三方库，无法对缠论核心逻辑进行定制或修正。当前只提取了三买信号，缺少一买、二买信号。

### 2.2 FSM 状态机

**BUG: infer_state() 永远无法到达 PYRAMID 和 CIRCUIT_BREAK 状态（严重逻辑缺陷）**

7 个状态中只有 4 个（IDLE/SIGNAL/PROBE/MONITOR）可以通过 `infer_state` 到达。PYRAMID（加仓）、EXIT（平仓）、CIRCUIT_BREAK（熔断）永远无法被推断。转换表中没有任何状态可以转入 CIRCUIT_BREAK，使其成为死状态。

**BUG: EXIT 状态立即重置为 IDLE**

`self.state` 被立即设为 IDLE，但返回的响应中 `state` 字段仍然是 EXIT，造成内部状态与返回状态不一致。

**BUG: _check_sell_conditions 和 _determine_target_state 的阈值不一致**

两套卖出逻辑可能产生冲突。例如，`_check_sell_conditions` 可能返回 "EXECUTE_SELL"，但 `_determine_target_state` 可能认为应该保持 MONITOR。

**BUG: Indicators 导入可能为 None**

try/except 将 Indicators 设为 None，但 `infer_state()` 直接调用 `Indicators.calc_ma()` 无 None 检查，触发 `AttributeError`。

**BUG: DecisionBrain 构造函数中的延迟导入可能失败**

`from ...risk.evt_risk import HistoricalSimulationRisk` 和 `from ...risk.sizer import PositionSizer`，如果 risk 模块内部依赖未满足，DecisionBrain 无法被实例化。

### 2.3 LPPL 泡沫检测模块

**BUG: 4 个文件中有 4 种不同的 tau 处理方式（3种独立实现 + 1种内联）**

| 文件 | tau 处理 | 评估 |
|------|---------|------|
| core.py | `np.maximum(tau, 1e-8)` | 截断精度不一致 |
| engine.py | `np.maximum(tau, 1e-10)` | 截断精度不一致 |
| calculator.py | `tau <= 0` 返回 NaN | **最正确** |
| visualizer.py | `np.abs(tc - t)` | **数学错误** — 产生虚假对称波形 |

**BUG: 代价函数定义不一致 — SSE vs RMSE**

- core.py 返回 SSE（误差平方和）
- engine.py 返回 RMSE（均方根误差）
- 两者差一个因子 `sqrt(1/n)`，影响收敛判据 `tol` 的含义

**BUG: engine.py 中 fit_single_window_lbfgsb 的 RMSE 计算错误**

`rmse = np.sqrt(best_cost / len(log_price_data))` 中 `best_cost` 已经是 RMSE，再开方导致双重开方，结果偏小。

**BUG: core.py 中 calculate_bottom_signal_strength 的评分公式可能产生负值**

当 `m` 接近边界时 `m_score` 可能为负，虽然外层有截断，但计算不直观。

**LPPL 模块内部代码重复严重:**

| 功能 | core.py | engine.py | calculator.py | numba_optimizer.py |
|------|---------|-----------|---------------|-------------------|
| LPPL 函数 | `_lppl_func_python` | `lppl_func` | `lppl_func` | 内联于 `_reduced_cost_numba` |
| 代价函数 | SSE | RMSE | SSE / VarPro | `_reduced_cost_numba` |
| 输入校验 | `precheck_fit_input` | `precheck_fit_input` | 内联校验 | 无 |
| 风险判定 | `detect_negative_bubble` | `calculate_risk_level` | `_determine_risk_level` | 无 |

3 个文件中存在 3 种独立 LPPL 函数实现 + 1 种内联实现（numba_optimizer.py 无独立函数，LPPL 计算内联于 `_reduced_cost_numba` 第 42-51 行）、3 种代价函数、2 种输入校验、3 种风险判定逻辑。

**数值稳定性问题:**

1. `tau^m` 的溢出风险: 当 `tau` 很大且 `m` 接近 1 时，`tau^m` 可能非常大。
2. 设计矩阵可能病态: 当 `tau` 值范围很大或很小时，`np.linalg.lstsq` 的解不稳定。
3. DE 优化器 `maxiter=100` 对多模态 LPPL 代价函数可能不够，文献中通常使用 200-500。

### 2.4 Indicators 指标模块

1. `calc_market_entropy` 的 `stride_tricks.as_strided` 存在安全隐患，且 Python 循环对大数据集性能不佳。
2. RSI 计算中 `fillna(50)` 可能掩盖数据质量问题。

---

## 三、A股交易规则合规性分析

### 3.1 费用模型

| 项目 | 代码值 | 实际A股规则 | 合规性 |
|------|--------|------------|--------|
| 佣金率 | 万3 | 万1~万3 | 合规 |
| 最低佣金 | 5元/笔 | 5元/笔 | 合规 |
| 印花税(当前) | 万5 | 2023.8.28起万5 | **数值正确，日期标注错误** |
| 印花税(旧) | 千1 | 2023.8.28前千1 | **数值正确，日期标注错误** |
| 过户费 | 0.001% | 2022.4月起0.001% | 合规 |

**严重问题 — 印花税日期标注错误:**

代码标注为"pre-2024"和"2024年起"，实际应为 2023年8月28日。backtest.py 使用 `if max_year < 2024` 作为切换条件，导致 2023.08.28-2023.12.31 期间回测多扣一倍印花税。

**CostConfig.from_yaml() 缺陷:**

1. 未加载 `stamp_tax_pct` 和 `transfer_fee_pct`，始终使用硬编码默认值
2. 滑点单位转换不一致: YAML 中 0.1% 被解释为 0.001，而默认 SLIPPAGE_PCT = 0.0005（0.05%），从YAML加载后滑点翻倍

### 3.2 滑点模型

**三套独立滑点实现并存且数值不一致:**

| 实现 | 滑点值 |
|------|--------|
| cost_model.py | 0.05% |
| slippage_model.py DefaultSlippage | 0.1% |
| BacktestEngine._calculate_slippage | 基础+非线性冲击 |

**DynamicSlippage 返回硬编码值:** 所有"动态"计算都基于硬编码值（流动性10亿、波动率2%），未接入真实数据源。

### 3.3 涨跌停检查

**涨跌停比例验证 — 合规:**

| 板块 | 代码值 | 实际A股规则 | 合规性 |
|------|--------|------------|--------|
| 主板 | ±10% | ±10% | 合规 |
| 科创板 | ±20% | ±20% | 合规 |
| 创业板 | ±20% | ±20% | 合规 |
| 北交所 | ±30% | ±30% | 合规 |
| ST股 | ±5% | ±5% | 合规 |

**严重缺失 — 新股上市首日/前5日无涨跌停:**

- 主板新股首日: 最高涨44%
- 科创板/创业板前5日: 不设涨跌停
- 北交所首日: 不设涨跌停
- 代码对所有股票一律按板块比例执行，回测新股时涨跌停判断错误

**板块识别问题:**

1. 北交所前缀 `"4"` 对应新三板而非北交所，新三板股票被错误应用30%涨跌停
2. ST股识别依赖 name 参数，未传入时降级为板块默认涨跌停
3. 两套板块识别系统（limit_checker vs market_rules）不一致

**涨跌停价格精度:** 未先四舍五入到0.01元再比较，极端价格下判断偏差。

### 3.4 市场时间与竞价规则

**集合竞价时段完全缺失:**

| 时段 | 时间 | 代码现状 |
|------|------|---------|
| 开盘集合竞价(可撤单) | 9:15-9:20 | 缺失 |
| 开盘集合竞价(不可撤单) | 9:20-9:25 | 缺失 |
| 收盘集合竞价 | 14:57-15:00 | 缺失 |

**盘中临时停牌机制缺失:** 科创板/创业板首次涨跌30%/60%时停牌10分钟。

### 3.5 T+1 规则

**BacktestEngine:** 使用真实交易日历判断，逻辑正确，但仅跟踪单个 buy_date 变量，不支持加仓场景。

**UnifiedMatchingEngine:** 使用日历日（ordinal）而非交易日判断，与 BacktestEngine 方式不一致，两套实现可能产生不同结果。

### 3.6 价格笼子

价格笼子功能实现于 `shared/price_collar.py` + `shared/market_rules.py`（代码中称 `price_collar`，非 `limit_checker.py`）。

| 板块 | 代码值 | 实际A股规则 | 合规性 |
|------|--------|------------|--------|
| 主板 | ±2% | ±2% | 合规 |
| 科创板 | ±1% | ±2% | **不合规** |
| 创业板 | ±1% | ±2% | **不合规** |

科创板（`market_rules.py:28`）和创业板（`market_rules.py:27`）的 `price_collar_pct = 0.01`（±1%）过于严格，合法限价单被错误拒绝。价格笼子未区分交易时段（仅连续竞价生效）。

### 3.7 交易单位

科创板 lot_size=200 正确，但卖出时不足200股的零股应允许一次性卖出，代码中 `round_lot` 始终向下取整到整手，无法处理零股卖出。

---

## 四、代码质量分析

### 4.1 线程安全问题（P0-P1 级）

| 组件 | 问题 | 严重度 |
|------|------|--------|
| MemoryCacheBackend | 完全无线程安全保护，get/set/delete/hits/misses 无锁 | P0 |
| LoggerFactory | `__new__` 无锁，`_loggers` 字典并发读写风险 | P1 |
| get_config() | 模块级 config 变量存在轻微竞态，但 GlobalConfig.__new__ 已有双重检查锁，实际风险低 | P3 |
| AnalysisEngineFactory._lazy_init | `_engines` 字典无锁，importlib 期间释放 GIL | P1 |
| perf.py | `_COUNTERS` 和 `_TIMERS` 非原子操作 | P2 |

### 4.2 异常处理问题

**handle_errors 装饰器异常捕获顺序错误:**

如果 `expected_exceptions` 包含 `AlphaTacticianError` 子类，第1层先捕获，第2层永远不会触发。无参数调用时 `except ()` 不捕获任何异常，所有异常都落到兜底层。

**with_timeout 使用 daemon 线程无法真正取消执行:**

超时后函数并未停止，daemon 线程继续占用资源，可能导致死锁。

### 4.3 缓存系统问题

1. **smart_cache 无法区分"缓存值为 None"和"缓存未命中"**: 使用哨兵对象替代 None 检查。
2. **generate_cache_key 对 DataFrame 仅取首尾5行**: 中间数据变化但首尾不变时产生哈希碰撞，返回过期缓存。
3. **DiskCacheBackend.cleanup() 逐个 joblib.load**: 大量缓存文件时性能极差，应优先检查文件修改时间。

### 4.4 异常层次结构冗余

- `LPPLFitError` 和 `LPPLException` + `ComputationError` 语义重叠
- `DataNotFoundError` 继承自 `LPPLException` 而非 `DataError`，违反 5 层 DAG 架构
- `WyckoffError` 下的 `ImageProcessingError`、`FusionConflictError` 过于具体

### 4.5 其他代码质量问题

1. `AnalysisResult.timestamp` 使用 `datetime.now` 不带时区信息
2. `handle_network_errors` 每次调用都 `import requests`
3. `MarketHours.is_market_open` 不考虑节假日
4. `parallel.py` 仅9行代码，`worker_init` 为空函数
5. `loader.py` 缺少 `encoding` 参数和 None 检查
6. 类型注解不一致: `list[float] | "np.ndarray"` 混合语法、多处参数为 `Any`

---

## 五、配置系统分析

### 5.1 "双重真值源"问题（核心缺陷）

YAML 配置文件和 Python 常量类各自定义了几乎相同的一组参数，但数值存在多处不一致:

| 参数 | YAML值 | 常量值 | 偏差 |
|------|--------|--------|------|
| 滑点率 | 0.1% | 0.05% | **2倍** |
| 缓存TTL(指数) | 3600s | 7200s | **2倍** |
| 缓存TTL(实时) | 60s | 300s | **5倍** |
| FSM MA周期(短/长) | 20/60 | 5/20 | **完全不同** |
| NTF窗口 | 5 | 20 | **4倍** |
| 市值阈值(大盘) | 500亿元 | 1000亿元 | **2倍** |
| 市值阈值(中盘) | 100亿元 | 300亿元 | **3倍** |
| 最大回撤阈值 | 0.15 | 0.15 | 一致（无冲突） |
| 熵值阈值 | 0.2 | 0.1 | **2倍** |
| 换手率Z-Score | 3.0 | 2.5 | **不一致** |

运行时行为取决于调用路径——部分模块读取 YAML，部分直接引用常量，属于不确定性缺陷。

### 5.2 常量冗余和重复定义

| 概念 | 定义位置 | 数量 |
|------|---------|------|
| MAX_RETRIES=3 | DataSourceConstants, NetworkConstants, AnalysisServiceConstants, network_constants.py | 4处 |
| CACHE_TTL_* (7个) | DataServiceConstants, CacheConstants | 14处 |
| MAX_CACHE_SIZE | CacheConstants(1000), PerformanceConstants(5000) | **值不同** |
| RISK_FREE_RATE=0.02 | cost_model.py, risk_constants.py | 2处 |
| MAJOR_INDEXES | MarketConstants.MAJOR_INDEXES, 模块级MAJOR_INDEXES | 2处 |
| TestConstants | RISK_TEST_* / TEST_RISK_* 完全重复 | 约30个 |
| 文件后缀 | FILE_SUFFIX_* / *_SUFFIX | 2组完全重复 |

### 5.3 敏感信息暴露

| 风险等级 | 位置 | 内容 |
|---------|------|------|
| 高 | config.yaml:17 | TDX路径暴露用户主目录 |
| 中 | config.yaml:80 | 硬编码浏览器 UA 字符串 |
| 低 | data.py:219 | 硬编码新浪API地址和Referer头 |

### 5.4 配置热更新能力

当前几乎无热更新能力: GlobalConfig 单例无 reload 机制，常量类属性在模块加载时确定，配置文件变更无监听。

---

## 六、导入链与阻塞问题分析

### 6.1 原始5大阻塞问题现状

| # | 问题 | 文档描述 | 当前状态 |
|---|------|---------|---------|
| 1 | services/__init__.py 幽灵导入 | 8个幽灵导入 | **已修复** — 使用 __getattr__ 延迟导入，14个模块均存在 |
| 2 | brain/lppl/__init__.py 幽灵导入 | 7个幽灵导入 | **已改善** — try/except 模式，但6个已存在子模块未导出 |
| 3 | brain/fsm/fsm.py Indicators导入 | 导入崩溃 | **部分修复** — try/except fallback，但 NoneType 崩溃隐患 |
| 4 | data/ 整层不存在 | 无数据服务 | **已完全修复** — data/ 层已完整迁移 |
| 5 | engine_factory 参数错配 | 构造函数错误 | **部分修复** — brain 属性独立处理，但 orchestrator 语义仍模糊 |

### 6.2 当前幽灵 `__all__`（声明了但不可访问）

| 文件 | 声明的符号数 |
|------|-------------|
| data/services/__init__.py | 6个（DataImporter, LPPLDataService 等） |
| data/scripts/__init__.py | 4个（sync_daily_mootdx 等） |

### 6.3 遗漏导出（文件存在但未在 __init__.py 中导出）

| 包 | 遗漏模块数 |
|----|-----------|
| brain/lppl/ | 6个（core, multifit, cluster, regime, computation, numba_optimizer） |
| services/analysis/ | 2个（signal_service, wyckoff_analysis_engine） |
| data/sources/ | 8个（仅导出3/11个模块） |
| risk/ | 1个（historical_risk） |

### 6.4 导入风格违规

- brain/wyckoff/__init__.py 使用绝对导入，违反项目相对导入规范
- dashboard.py 26个组件函数硬导入，无 try/except 保护

---

## 七、测试覆盖分析

### 7.1 测试覆盖关键盲区

| 零测试模块 | 文件数 | 风险 |
|-----------|--------|------|
| signal/ 信号层 | 5 | 极高 — 交易信号的直接输入 |
| brain/wyckoff/ | 10 | 极高 — 吸筹/派发识别无验证 |
| hands/strategies/ 6个策略 | 6 | 极高 — 策略信号生成无验证 |
| hands/backtest/ 高级功能 | 6 | 高 — 过拟合检测/蒙特卡洛无验证 |
| data/pipeline/ | 4 | 高 — 数据清洗/验证无验证 |
| ui/ | 5+ | 中 — 1516行dashboard零测试 |

### 7.2 测试质量评估

**做得好的方面:**

1. A股微观结构防御测试极其扎实 — 涨跌停/T+1全覆盖
2. 防御编程测试体系完善 — 除零/NaN/Inf/空尾部防御
3. 未来函数（Lookahead Bias）防护测试 — 量化项目最关键的测试之一
4. Walk-Forward 因子管道测试 — 时序分割无泄漏验证
5. 向量化等价性测试 — 重构验证的最佳实践

**严重不足:**

1. signal 包零测试 — 信号归一化/聚合/质量评估是交易决策的直接输入
2. Wyckoff 方法论零测试 — 10个文件的完整子系统无测试
3. 回测高级功能零测试 — 过拟合检测/蒙特卡洛/鲁棒性检查是回测可信度的保障
4. 6个交易策略零测试 — 策略是交易系统的核心输出

### 7.3 测试反模式

1. **Mock 过度使用**: test_engine_factory.py 将所有引擎替换为 MagicMock，7个引擎的真实初始化完全没有被验证
2. **测试间状态泄漏**: FactorRegistry._factors.clear() 清理方式不统一
3. **条件跳过过多**: CI环境中大量测试可能全部被跳过
4. **回归测试命名模糊**: test_final_service_regressions.py 等文件名过于泛化

---

## 八、修复优先级路线图

### Phase 0 — 紧急（1周内）

| # | 问题 | 修复方案 |
|---|------|---------|
| 1 | 印花税日期标注错误 | 将年份分界改为精确日期判断（2023-08-28） |
| 2 | CZSC AnalysisError 导入缺失 | 添加 `from ...shared.exceptions import AnalysisError` |
| 3 | FSM Indicators NoneType 崩溃 | 添加 None 检查或内联 calc_ma 实现 |
| 4 | LPPL RMSE 双重开方 | `rmse = best_cost`（best_cost 已经是 RMSE） |
| 5 | LPPL visualizer np.abs 数学错误 | 改用 calculator.py 的方式（tau<=0 返回 NaN） |
| 6 | MemoryCacheBackend 无线程安全 | 添加 `threading.Lock()` 保护所有读写操作 |

### Phase 1 — 重要（2周内）

| # | 问题 | 修复方案 |
|---|------|---------|
| 7 | FSM 3个不可达状态 | 补全 PYRAMID/EXIT/CIRCUIT_BREAK 的推断条件，修复转换表 |
| 8 | 新股涨跌停规则缺失 | 在 limit_checker 中添加上市天数判断 |
| 9 | 价格笼子比例错误 | `shared/market_rules.py:27-28` 科创板/创业板 `price_collar_pct` 改为 0.02（±2%） |
| 10 | 北交所前缀包含新三板 | `shared/constants/market.py:70` 移除前缀 `"4"`，改为 `["83", "87"]` |
| 11 | 配置-常量9处数值冲突 | 确立 YAML 为唯一真值源，常量仅作 fallback |
| 12 | 三套滑点实现不统一 | 统一为单一 SlippageModel 实现 |
| 13 | PortfolioEngine 过户费遗漏 | 在 batch_open/close_positions 中添加过户费计算 |
| 14 | handle_errors 异常捕获顺序 | 调整为先捕获 AlphaTacticianError，再捕获 expected |
| 15 | with_timeout 无法取消执行 | 改用 concurrent.futures.ThreadPoolExecutor |
| 16 | ST股识别降级 | 添加股票名称必传校验或通过数据服务获取ST状态 |

### Phase 2 — 改善（1月内）

| # | 问题 | 修复方案 |
|---|------|---------|
| 17 | UI层5处DAG违规 | 在 services 层创建门面方法，UI 只依赖 services |
| 18 | LPPL 3种独立+1种内联函数实现不统一 | 以 calculator.py 的 VarPro 方法为权威实现，删除其余副本 |
| 19 | 两套DI容器并存 | 合并为统一实现 |
| 20 | AnalysisService 1642行 God Object | 拆分为 Orchestrator + CacheManager + ValidationService |
| 21 | 集合竞价时段缺失 | 在 MarketHours 中添加集合竞价时段和状态 |
| 22 | LoggerFactory 非线程安全 | 添加双重检查锁（`get_config()` 已有保护，无需修改） |
| 23 | signal/ 包零测试 | 添加完整测试覆盖 |
| 24 | wyckoff/ 零测试 | 添加核心逻辑测试 |
| 25 | 6个策略零测试 | 添加单元测试 |

### Phase 3 — 优化（持续）

| # | 建议 |
|---|------|
| 26 | 确立 YAML 为唯一真值源，常量仅作 fallback 默认值 |
| 27 | 补全缺失 Protocol: DataServiceProtocol, StorageManagerProtocol, DecisionBrainProtocol |
| 28 | 为 GlobalConfig 添加 reload() 方法，支持配置热更新 |
| 29 | 将 tdx.path 等敏感路径改为环境变量引用 |
| 30 | 清理 TestConstants 中 30 个重复常量 |
| 31 | 合并散落常量文件到 constants/ 子模块 |
| 32 | 统一涨跌停规则双重体系（LIMIT_RATIO + BOARD_RULES） |
| 33 | CalculationRegistry 移出 interfaces.py |
| 34 | brain 层通过 Protocol 访问 risk 层，消除直接导入 |
| 35 | 补充数据管道/高级回测测试 |
| 36 | 减少 mock 过度使用，增加真实对象测试 |
| 37 | 统一全局状态清理方式（使用 fixture 而非手动 try/finally） |

---

## 九、核心结论

UniQuant 项目在架构理念（5层DAG + Protocol解耦）和防御编程（除零/NaN/涨跌停/T+1）方面展现了量化系统的专业水准。但当前最紧迫的问题不是架构设计，而是**正确性**:

1. **印花税日期错误** — 2023年下半年回测多扣一倍印花税
2. **FSM 状态不可达** — 7状态机实际只有4状态工作
3. **LPPL 函数不统一** — 3种独立实现+1种内联、3种代价函数、RMSE双重开方
4. **配置常量冲突** — 9处关键参数YAML与常量不一致，行为不可预测
5. **滑点三套实现** — 回测成本取决于调用路径

建议在继续功能开发前，优先完成 Phase 0 和 Phase 1 的修复，确保"算出来的数字是对的"。量化系统的核心价值不在于功能多少，而在于**每一个数字都经得起验证**。

---

*审计完成时间: 2026-05-31 | 源码核实修正时间: 2026-05-31 | 基于代码事实，禁止幻觉*
