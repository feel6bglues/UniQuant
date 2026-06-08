# UniQuant 系统现状全景侦察报告

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> 审计时间：2026-05-30 | 基于代码事实，零推测 | 4 路 Subagent 并发审计

---

## 一、模块状态矩阵

| 包 | 文件数 | 代码行 | 状态 | 关键证据 |
|---|--------|--------|------|----------|
| **shared/** | 23 | ~4,500 | ✅ 生产可用 | 31 个异常类、Protocol 接口、成本模型、涨跌停检查均完整 |
| **data/** | 62 | ~15,000 | ⚠️ 勉强可用 | 9 个数据源、Parquet 存储完整；DuckDB 零实现、NaN 填 0 有风险 |
| **brain/lppl/** | 8 | ~2,200 | ✅ 生产可用 | 变量投影法 DE + Numba JIT 真实加速；numba_optimizer.py 是死代码 |
| **brain/wyckoff/** | 11 | ~4,900 | ✅ 生产可用 | 九步分析完整，核心 `_scan_bc_sc()` 完全向量化 |
| **brain/czsc/** | 2 | ~640 | ⚠️ 勉强可用 | 依赖第三方 `czsc` 库，笔/线段/中枢计算不自主 |
| **brain/factors/** | 8 | ~1,700 | ✅ 生产可用 | IC/IR 评估完整，Walk-Forward 严格防泄漏，前视偏差断言存在 |
| **brain/fsm/** | 2 | ~660 | ✅ 生产可用 | 7 状态 FSM + DecisionBrain，FileLock 状态持久化 |
| **brain/ntf/** | 1 | 183 | ✅ 生产可用 | 国家队干预检测，量价脉冲分析 |
| **brain/regime/** | 1 | 272 | ✅ 生产可用 | Shannon 熵 + 换手率 Z-Score 市场状态检测 |
| **brain/indicators** | 2 | 808 | ⚠️ 代码重复 | 两份 100% 相同的 Indicators 类（模块文件 vs 包目录） |
| **hands/backtest/** | 10 | ~2,000 | ⚠️ 勉强可用 | 双引擎并存；T+1 向量化版本有缺陷；look-ahead bias |
| **hands/strategies/** | 12 | ~1,200 | ⚠️ 勉强可用 | 双轨策略（A轨 backtrader / B轨函数）未桥接；B轨使用未来数据 |
| **risk/** | 7 | ~1,300 | ⚠️ 勉强可用 | DrawdownAnalyzer 生产级；EVT 名不副实（实为历史模拟法） |
| **services/** | 11 | ~4,500 | ⚠️ 勉强可用 | AnalysisEngineFactory 注册 9 引擎；绕过工厂模式、静默吞错 |
| **signal/** | 5 | ~1,300 | ✅ 生产可用 | 归一化、聚合、持久化、质量评估完整 |
| **ui/** | 5 | ~2,500 | ✅ 生产可用 | Streamlit 仪表盘完整，LPPL 可视化器存在 |

---

## 二、核心数据流图解

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据采集层]                                      │
│  mootdx本地 ─┐                                                          │
│  mootdx在线 ─┤                                                          │
│  baostock   ─┤                                                          │
│  sina       ─┼─→ SourceRouter ─→ DataFetcher ─→ DataIngestionService    │
│  ths        ─┤     (故障转移)      (LRU缓存)         (同步脚本)          │
│  tencent    ─┤                                                          │
│  eastmoney  ─┘  [未注册]                                                │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ DataFrame(date,open,high,low,close,volume)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据存储层]                                      │
│  StorageManager ──→ data/lake/quotes/{daily,weekly,monthly}/*.parquet   │
│       │                (原子写入 + FileLock + Snappy压缩)                │
│       ├─→ synthesize_weekly() / synthesize_monthly()  (日→周/月合成)     │
│       └─→ DataAdjuster ──→ 前复权/后复权 (merge_asof + SmartFactorV15)  │
│                                                                         │
│  ⚠️ DuckDB: config.yaml 声明 engine:"duckdb"，代码零实现                 │
│  ⚠️ Zero-Copy: 不存在，全部经过 Pandas 中间层                             │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ 复权后 DataFrame
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [分析引擎层]                                      │
│                                                                         │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐   │
│  │  LPPL   │  │  Wyckoff │  │  CZSC   │  │  Factors │  │   FSM    │   │
│  │ 泡沫检测 │  │ 量价分析  │  │ 缠论分析 │  │ 因子管道  │  │ 状态机   │   │
│  │ DE+Numba│  │ 9步向量化 │  │ czsc库  │  │ IC/IR+WF │  │ 7状态    │   │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └────┬─────┘  └────┬─────┘   │
│       │            │             │             │             │          │
│       └────────────┴─────────────┴─────────────┴─────────────┘          │
│                              │ AnalysisResult (dataclass)               │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │              DecisionBrain (brain/fsm/fsm.py)                 │       │
│  │  综合所有引擎输出 → 状态转换 → 买入/卖出/持有决策              │       │
│  └──────────────────────────────┬───────────────────────────────┘       │
└─────────────────────────────────┼───────────────────────────────────────┘
                                  │ 交易信号
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [回测撮合层]                                      │
│                                                                         │
│  BacktestEngine (逐bar)  ←──冲突──→  UnifiedMatchingEngine (向量化)     │
│       │                                      │                          │
│       ├─ T+1: 交易日历 ✅                    ├─ T+1: 日历天数 ❌         │
│       ├─ 涨跌停: 5板块 ✅                    ├─ 涨跌停: 5板块 ✅         │
│       ├─ 滑点: 非线性模型 ⚠️                ├─ 滑点: 向量化 ✅          │
│       └─ 手数取整: ❌                        └─ 手数取整: ❌             │
│                                                                         │
│  B轨策略函数 (wyckoff/ma_cross/reversal/regime)                         │
│  ⚠️ 使用 as_of_date 之后的真实数据，非实时信号生成器                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ 回测结果
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [风控层]                                          │
│                                                                         │
│  DrawdownAnalyzer ✅     PositionSizer ✅     PortfolioOptimizer ✅      │
│  (向量化MDD+尾部风险)    (T+1惩罚+手数取整)   (风险平价+均值方差)        │
│                                                                         │
│  EVTRisk ⚠️ (名不副实，实为历史模拟法，非GPD极值理论)                    │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [UI 层]                                           │
│  Streamlit Dashboard ─→ LPPL Visualizer ─→ Manager Logic                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、技术债与高危地带雷达

### 🔴 TOP 3 高危代码位置

**1. `unified_matching_engine.py:162` — T+1 向量化实现使用日历天数而非交易日**

```python
t1_violation = (cur_ord - buy_ord < 1) & (buy_ord > 0)
```

`pd.Timestamp.toordinal()` 计算的是公历序数差，周末和节假日会导致误判。周五买入、周日尝试卖出，ordinal 差为 2 ≥ 1，会错误允许卖出。**回测结果不可信。**

**2. `analysis_service.py:74-77` — AnalysisService 自愈式初始化导致 orchestrator 指向错误**

```python
if engine_factory is None:
    from .analysis.engine_factory import AnalysisEngineFactory
    engine_factory = AnalysisEngineFactory(orchestrator=self)  # self = AnalysisService, 非 DataService
```

当 ServiceContainer 未注入 engine_factory 时，引擎的 orchestrator 指向 AnalysisService 而非 DataService，导致引擎无法获取数据。

**3. `data/pipeline/data_cleaner.py:26` — NaN 填 0 掩盖数据质量问题**

```python
pd.to_numeric(df[col], errors="coerce").fillna(0)
```

对 `open/high/low/close` 等价格列的 NaN 全部填 0，下游引擎会将价格 0 视为有效数据，可能导致除零错误或计算结果异常。

### 🟡 次高危地带

| # | 位置 | 问题 |
|---|------|------|
| 4 | `evt_risk.py:33` | 类名 EVTRisk 实为历史模拟法，注释承认非真正 EVT |
| 5 | `services/__init__.py` 全局 | `@handle_errors` 123+ 处静默吞错，调用方无法区分正常结果和错误降级 |
| 6 | `engine.py:320` | 信号生成和成交在同一 bar 的 close 价格，look-ahead bias |
| 7 | `ma_cross.py:30` | B轨策略使用 `as_of_date` 之后的数据计算收益，非真实回测 |
| 8 | `brain/indicators.py` vs `brain/indicators/` | 模块/包命名冲突（3 处），Python 优先解析包，模块文件成死代码 |
| 9 | `data_pipeline_service.py:20` | 调用 `self.adjuster.adjust()` 但方法不存在，运行时必崩 |
| 10 | `service_container.py:36-39` | 单例无锁保护，多线程下竞态条件 |

---

## 四、可跑通的最小可用闭环

### ✅ 已验证可跑通的路径

**闭环 A：LPPL 泡沫检测**

```
mootdx本地读取 → Parquet存储 → 后复权(DataAdjuster) → LPPLCalculator.fit_single_window()
→ DE优化(tc,m,w) + OLS求解(a,b,c) → Sornette约束过滤 → 置信度评分
```

**证据**：`calculator.py:250-339` 完整实现，`core.py:81-94` Numba JIT 加速真实。

**闭环 B：Wyckoff 量价分析**

```
mootdx本地读取 → Parquet存储 → 后复权 → WyckoffEngine.analyze()
→ 9步分析(向量化) → Spring/SOS/UTAD信号 → Markdown报告
```

**证据**：`wyckoff/engine.py` 1356 行完整实现，`_scan_bc_sc()` 完全向量化。

**闭环 C：因子 Walk-Forward 回测**

```
mootdx本地读取 → 后复权 → custom_factors计算10个技术因子
→ Z-score标准化 → IC加权合成 → Walk-Forward时序分割 → 样本外评估
```

**证据**：`factors/analyzer.py:116-157` Rank IC 完整，`walk_forward_pipeline.py:62-78` 严格时序分割。

**闭环 D：FSM 状态机决策**

```
mootdx本地读取 → 后复权 → Indicators.calc_ma() → FSM.infer_state()
→ DecisionBrain.make_decision() → 买入/卖出/持有信号 → 状态持久化(JSON+FileLock)
```

**证据**：`fsm.py:95-158` 状态推断、`fsm.py:484-553` 决策流程完整。

### ⚠️ 可跑通但结果不可信的路径

**闭环 E：B轨策略回测**（存在 look-ahead bias）

```
数据读取 → as_of_date截断 → 但策略函数内部使用as_of_date之后的数据
→ 计算"收益" → 输出回测报告（非真实回测）
```

**证据**：`ma_cross.py:30` 使用未来数据的 open 价入场。

---

## 五、下一步行动建议

### P0 — 紧急修复（影响回测正确性）

1. **修复 T+1 向量化实现**：`unified_matching_engine.py:162` 改用交易日历计算交易日间隔
2. **修复 data_pipeline_service.py:20**：`adjust()` 方法不存在，改为 `apply_adjustment()` 或 `get_adjusted_data()`
3. **消除 NaN 填 0**：`data_cleaner.py:26` 对价格列改为前向填充，仅对成交量填 0

### P1 — 架构统一（影响可维护性）

4. **统一撮合引擎**：废弃 UnifiedMatchingEngine 或修复其 T+1 实现，保留 BacktestEngine
5. **桥接双轨策略**：为 A轨(backtrader) 和 B轨(函数) 策略创建统一接口
6. **消除模块/包命名冲突**：删除 `brain/indicators.py`、`brain/screener.py`、`brain/alpha_decoupler.py` 冗余模块文件
7. **修复 AnalysisService 自愈初始化**：确保 orchestrator 指向 DataService

### P2 — 功能补全（影响系统完整性）

8. **实现 DuckDB 引擎**：当前 config.yaml 声明但零实现
9. **注册 EastmoneySource**：1091 行完整实现但未被 DataFetcher 注册
10. **实现真正的 EVT（GPD 拟合）**：当前 `evt_risk.py` 实为历史模拟法
11. **加载遗漏的配置文件**：`trading.yaml`、`factors.yaml`、`optimal_params.yaml` 未被 GlobalConfig 加载

### P3 — 代码质量（影响长期健康）

12. **统一异常定义**：消除 `brain/czsc`、`brain/fsm`、`brain/indicators` 的局部异常重复定义
13. **清理死代码**：`shared/di_container.py`、`lppl/numba_optimizer.py`、`shared/interfaces.py:CalculationRegistry`
14. **修复 `@handle_errors` 静默吞错**：关键路径应提供区分正常结果和错误降级的机制
15. **添加手数取整**：BacktestEngine 和 PortfolioEngine 的 `shares` 计算应做 100 股整数倍取整

---

## 附录：四路审计详细发现

### A. 数据基座与 I/O 审计 (`src/uniquant/data/`)

#### A.1 mootdx 数据管道

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| MootdxLocalSource | `sources/mootdx_local.py:47-48` | ✅ | 延迟初始化 `mootdx.reader.Reader` |
| 日线读取 | `sources/mootdx_local.py:67` | ⚠️ | 一次性读取全量，无分页或增量机制 |
| 分钟线读取 | `sources/mootdx_local.py:105` | ⚠️ | 同上，全量读取后内存过滤 |
| MootdxOnlineSource | `sources/mootdx_online.py:27-28` | ✅ | `Quotes.factory(market='std', heartbeat=True)` |
| 日线在线获取 | `sources/mootdx_online.py:48` | ⚠️ | 硬编码 `count=800`（约3.5年），长历史回测不足 |
| TDX 二进制解析 | `parsers/tdx_parser.py:56-59` | ✅ | `struct.iter_unpack` 高效批量解析 |
| 价格除数 | `parsers/tdx_parser.py:80-93` | ✅ | 按证券类型区分：债券/10000，ETF/1000，普通股/100 |
| GBBQ 解密 | `parsers/tdx_parser.py:172-265` | ✅ | pytdx 首选 + TEA 手动解密回退 |

#### A.2 DuckDB / Parquet 数据湖

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| DuckDB 配置 | `config/config.yaml:6-9` | ❌ | 声明 `engine: "duckdb"` 但代码零实现 |
| Parquet 写入 | `lake/storage_manager.py:83` | ✅ | `df.to_parquet(compression="snappy")` |
| Parquet 读取 | `lake/storage_manager.py:106` | ✅ | `pd.read_parquet(file_path)` |
| 原子写入 | `lake/storage_manager.py:316-334` | ✅ | 先写 `.tmp` 再 `rename` |
| 文件锁 | `lake/storage_manager.py:80-81` | ✅ | `FileLock` 防并发写冲突 |
| Zero-Copy | 全局 | ❌ | 无 PyArrow RecordBatch/memory_map 零拷贝 |

#### A.3 前后复权与 NaN 处理

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| SmartFactorCalculatorV15 | `utils/smart_factor_calculator.py:85-199` | ✅ | 涨跌幅复权法，逐事件 searchsorted 定位 |
| 核心公式 | `utils/smart_factor_calculator.py:177-178` | ✅ | `ex_price = (pre_close - cash + r_price * rights) / (1 + split + rights)` |
| 异常因子过滤 | `utils/smart_factor_calculator.py:188-194` | ✅ | factor>1.05 或 <0.95 时检查实际跌幅匹配度 |
| DataAdjuster | `pipeline/data_adjuster.py:159-270` | ✅ | `merge_asof(direction="backward")` 合并因子表 |
| 前复权 | `pipeline/data_adjuster.py:238-263` | ✅ | `price * factor / latest_factor` |
| 后复权 | `pipeline/data_adjuster.py:225-237` | ✅ | `price * factor` |
| NaN 处理 | `pipeline/data_cleaner.py:26` | ❌ | 数值列 NaN 全部填 0，掩盖价格缺失 |

#### A.4 数据源路由

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| SourceRouter | `managers/source_router.py:14-18` | ✅ | 并发数限制 `min(3, len(adapters))` |
| 故障转移 | `managers/source_router.py:22-74` | ✅ | 顺序尝试 + 重试(2次) + 超时控制 |
| 竞速模式 | `managers/source_router.py:112-167` | ✅ | 并发请求多源，选择最快有效数据 |
| 熔断器 | `managers/source_router.py:232-246` | ✅ | `pybreaker.CircuitBreakerError` 集成 |
| EastmoneySource | `sources/eastmoney.py` | ⚠️ | 1091 行完整实现但未被注册使用 |

---

### B. 核心算法与分析引擎审计 (`src/uniquant/brain/`)

#### B.1 LPPL 引擎

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| DE 算法(变量投影法) | `calculator.py:290-302` | ✅ | `scipy.optimize.differential_evolution`，仅优化 3 参数 |
| DE 算法(全参数) | `engine.py:209-220` | ✅ | 7 参数直接优化 |
| Numba JIT DE | `numba_optimizer.py:176-264` | ⚠️ | 完整实现但未被任何主入口调用（死代码） |
| LPPL 模型函数 | `core.py:81-94` | ✅ | `@njit(cache=True, fastmath=True)` 真实 JIT |
| 成本函数 | `core.py:127-139` | ✅ | `@njit` 真实 JIT |
| 融合成本 | `core.py:141-156` | ✅ | `@njit` 手动展开矩阵运算为标量累加 |
| 分发控制 | `core.py:102` | ✅ | `if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT` 全局开关 |
| Sornette 约束 | `calculator.py:341-363` | ✅ | m/w 范围、b<0、|c|>阈值 |
| 置信度计算 | `calculator.py:365-402` | ✅ | tc_weight=0.4, cost_weight=0.4, data_weight=0.2 |
| 三层窗口拟合 | `multifit.py:36-70` | ✅ | 短期[40,60,80], 中期[80,120,180], 长期[180,240,360] |
| 负泡沫检测 | `core.py:182-196` | ✅ | `detect_negative_bubble()` 抄底信号 |

**潜在问题**：`calculator.py:332` — `rmse = np.sqrt(np.mean(residuals))` 在满秩时 `residuals` 为空数组，返回 NaN。

#### B.2 Wyckoff 引擎

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 九步分析主引擎 | `engine.py` (1356行) | ✅ | 完整实现 |
| BC/SC 扫描 | `engine.py:1217-1315` | ✅ | **完全向量化**：`np.where`、`pd.Series.rank(pct=True)`、`rolling()` |
| 数据模型 | `models.py` (817行) | ✅ | 40+ 个 dataclass |
| 规则验证层 | `rules.py` (352行) | ✅ | 10 条规则独立验证 |
| 子状态分类 | `classifiers.py` (294行) | ✅ | UNKNOWN 子状态 + 涨跌停检测 |
| 状态持久化 | `state.py` (292行) | ✅ | Spring 冷冻期管理 |
| 融合引擎 | `fusion_engine.py` (468行) | ✅ | 数据+图像融合 |
| 报告生成 | `reporting.py` (395行) | ✅ | Markdown/HTML/CSV/JSON |

**循环分析**：所有 `itertuples()` 循环均在小窗口（5-20行）内操作，不影响整体性能。

#### B.3 CZSC 缠论引擎

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 核心依赖 | `czsc_engine.py:6` | ⚠️ | `from czsc import CZSC, Freq, RawBar` 依赖第三方库 |
| 笔列表获取 | `czsc_engine.py:206` | ⚠️ | `getattr(self.analyzer, "bi_list", None)` 从 czsc 库获取 |
| 三买检测 | `czsc_engine.py:355` | ⚠️ | `czsc_signals.cxt_third_buy_V230228(analyzer)` 委托第三方 |
| 信号枚举 | `czsc_engine.py:31-77` | ✅ | `CZSCSignalType` 中英文映射，避免字符串脆性 |
| RawBar 构建 | `czsc_engine.py:296-313` | ⚠️ | 逐行循环构建（czsc 库 API 限制） |

#### B.4 Factor 管道

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 因子注册中心 | `registry.py` (102行) | ✅ | 单例 + 线程安全 |
| Rank IC 计算 | `analyzer.py:116-157` | ✅ | Spearman 秩相关系数 |
| IC/IR 批量计算 | `analyzer.py:177-312` | ✅ | 多因子、多持有期、半衰期加权 |
| 前视偏差防护 | `analyzer.py:97-102` | ✅ | `mode == "live": raise ValueError("Lookahead bias detected...")` |
| 未来时间戳检测 | `analyzer.py:104-111` | ✅ | `max_date > pd.Timestamp.now()` |
| Walk-Forward | `walk_forward_pipeline.py:62-78` | ✅ | 严格时序分割，测试窗口永远在训练窗口之后 |
| 对称正交化 | `composer.py:170-214` | ✅ | 特征值分解消除因子共线性 |
| 10 个技术因子 | `custom_factors.py` (183行) | ✅ | 全部向量化实现 |
| 财务桥接 | `financial_bridge.py:241-351` | ⚠️ | 逐股票循环 `merge_asof`，大规模场景可能瓶颈 |

#### B.5 FSM 状态机

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 7 状态枚举 | `fsm.py:27-34` | ✅ | IDLE/SIGNAL/PROBE/MONITOR/PYRAMID/EXIT/CIRCUIT_BREAK |
| 状态推断 | `fsm.py:95-158` | ✅ | MA60突破→SIGNAL, 缩量回踩→PROBE, MA20>MA60→MONITOR |
| Look-ahead 修复 | `fsm.py:99-101` | ✅ | 盘中模式排除当前未确定的 K 线 |
| 状态转换矩阵 | `fsm.py:417-428` | ✅ | 合法转换验证 |
| 状态持久化 | `fsm.py:592-644` | ✅ | JSON + FileLock |
| Indicators 依赖 | `fsm.py:19-22` | ⚠️ | try/except 降级，但使用处无 None 检查 |

#### B.6 指标计算

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| `calc_ma` | `indicators.py:43-50` | ✅ | `rolling(window).mean()` 向量化 |
| `calc_ema` | `indicators.py:54-57` | ✅ | `ewm(span=window).mean()` 向量化 |
| `calc_atr` | `indicators.py:61-76` | ✅ | `np.maximum` + `rolling().mean()` |
| `calc_bollinger` | `indicators.py:80-102` | ✅ | `rolling().mean()` + `rolling().std()` |
| `calc_macd` | `indicators.py:106-125` | ✅ | `ewm().mean()` 三次 |
| `calc_rsi` | `indicators.py:129-147` | ✅ | Wilder's RSI，`ewm(alpha=1/window)` |
| `calc_market_entropy` | `indicators.py:151-188` | ⚠️ | 半向量化：stride_tricks 零拷贝 + 逐窗口 Python 循环 |
| 缓存机制 | 全方法 | ✅ | `@smart_cache` 装饰器，TTL=日级 |
| 代码重复 | `indicators/indicators.py` | ⚠️ | 与顶层 `indicators.py` 100% 相同 |

---

### C. 撮合回测与风控审计 (`src/uniquant/hands/` + `src/uniquant/risk/`)

#### C.1 撮合引擎

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| BacktestEngine | `hands/backtest/engine.py` (521行) | ⚠️ | 单标的逐bar，含滚动/前瞻/压力测试 |
| UnifiedMatchingEngine | `hands/backtest/unified_matching_engine.py` (191行) | ⚠️ | 向量化批量撮合 |
| PortfolioEngine | `hands/backtest/portfolio_engine.py` (362行) | ⚠️ | 多标的组合 |
| T+1 (BacktestEngine) | `engine.py:114-139` | ✅ | 使用 `TradeCalendarManager` 真实交易日历 |
| T+1 (UnifiedMatching) | `unified_matching_engine.py:162` | ❌ | `toordinal()` 日历天数差，非交易日差 |
| 涨跌停 (5板块) | `shared/limit_checker.py:69-135` | ✅ | ST±5%, 科创/创业±20%, 北交±30%, 主板±10% |
| 非线性滑点 | `engine.py:77-112` | ⚠️ | 模型存在但 `run_backtest()` 未传 volume 参数，冲击成本始终为 0 |
| 佣金 | `shared/cost_model.py:25-32` | ✅ | 万3，最低5元/笔 |
| 印花税 | `shared/cost_model.py:25-32` | ✅ | 万5卖方(2024起)，千1(2024前) |
| 历史印花税切换 | `strategies/backtest.py:320-329` | ✅ | `max_year < 2024` 自动选择 |
| 手数取整 | `engine.py:181` | ❌ | `int(...)` 未做 100 股整数倍 |
| Look-ahead bias | `engine.py:320-324` | ❌ | 信号和成交在同一 bar 的 close 价格 |

#### C.2 策略层

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| A轨 BaseStrategy | `strategies/base.py:26-108` | ⚠️ | 依赖 backtrader，未安装时退化为 Mock |
| A轨 FSMStrategy | `strategies/fsm_strategy.py:5-68` | ⚠️ | MA20/MA60 趋势跟踪 |
| A轨 WyckoffStrategy | `strategies/wyckoff_strategy.py:5-128` | ⚠️ | 威科夫量价分析 |
| B轨 trade_wyckoff | `strategies/wyckoff.py:40-165` | ⚠️ | 使用未来数据 |
| B轨 trade_ma | `strategies/ma_cross.py:8-49` | ⚠️ | 使用未来数据 |
| STRATEGY_MAP (定义一) | `strategies/__init__.py:23-29` | ⚠️ | 路径字符串映射，延迟导入 A轨 |
| STRATEGY_MAP (定义二) | `strategies/registry.py:6-13` | ⚠️ | 函数引用映射，backtest.py 使用此版本 |
| 双轨桥接 | 全局 | ❌ | 无任何桥接代码 |

#### C.3 回测结果

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 资金曲线 (BacktestEngine) | `engine.py:260-269` | ✅ | `equity = cash + position * price` |
| 资金曲线 (PortfolioEngine) | `portfolio_engine.py:195-201` | ✅ | 防除零 `max(prev_equity, 1e-8)` |
| MDD (result.py) | `result.py:88-94` | ✅ | 逐点迭代，逻辑正确 |
| MDD (portfolio_engine) | `portfolio_engine.py:341-343` | ✅ | `expanding().max()` 向量化 |
| MDD (drawdown_analyzer) | `risk/drawdown_analyzer.py:86-89` | ✅ | 最完善：滚动MDD + Ulcer指数 |
| Sharpe (result.py) | `result.py:97-99` | ⚠️ | 未减无风险利率 |
| Sharpe (portfolio_engine) | `portfolio_engine.py:339` | ⚠️ | 减了无风险利率，口径不一致 |

#### C.4 风控模块

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| DrawdownAnalyzer | `risk/drawdown_analyzer.py` (187行) | ✅ | 纯向量化，零 iterrows，含滚动MDD/尾部风险/压力测试 |
| EVTRisk | `risk/evt_risk.py:24-33` | ❌ | 注释承认非真正 EVT，实为历史模拟法 |
| VaR/CVaR | `risk/evt_risk.py:139,162-167` | ✅ | 分位数法 + 尾部均值法（但名不副实） |
| PositionSizer | `risk/sizer.py:71-187` | ✅ | T+1 惩罚系数 1.2x，手数取整，几何止损 |
| PortfolioSizer | `risk/sizer.py:234-266` | ⚠️ | 第 253 行直接修改输入 `sig.notional`（违反不可变性） |
| 风险平价 | `risk/portfolio_optimizer.py:112-191` | ✅ | SLSQP 优化，收敛失败时 fallback 到等权 |
| 均值-方差 | `risk/portfolio_optimizer.py:213-301` | ✅ | max_sharpe/min_volatility/target_return 三目标 |
| 有效前沿 | `risk/portfolio_optimizer.py:303-348` | ✅ | 逐目标收益率优化 |
| 过户费 | 全局 | ❌ | A股过户费 0.001% 未实现 |

---

### D. 架构与工程质量审计

#### D.1 依赖图与循环依赖

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| services→data 依赖 | `analysis_service.py:28` | ⚠️ | 直接 `from .data_service import DataService` |
| 潜在循环链 | `services→data→data_fetcher` | ⚠️ | 模块级导入在 import 时触发 |
| __getattr__ 延迟加载 | `services/__init__.py:16-43` | ✅ | 有效避免循环依赖 |
| 模块/包命名冲突 | `brain/indicators.py` vs `brain/indicators/` | ❌ | 3 处同名冲突，Python 优先解析包 |
| 绝对/相对导入混用 | `brain/wyckoff/__init__.py:1-11` | ⚠️ | 与其他包使用相对导入不一致 |

#### D.2 依赖注入容器

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| DIContainer | `shared/di_container.py:5-80` | ❌ | 未被任何模块使用，死代码 |
| ServiceContainer | `services/service_container.py:28-83` | ⚠️ | 实际使用的容器 |
| 单例线程安全 | `service_container.py:36-39` | ❌ | `instance()` 无锁保护 |
| AnalysisService 未注册 | `service_container.py:54-82` | ⚠️ | 需在外部手动创建 |
| 自愈初始化 | `analysis_service.py:74-77` | ❌ | orchestrator 指向 self 而非 DataService |

#### D.3 配置系统

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| GlobalConfig 单例 | `config_loader.py:10-29` | ✅ | 双重检查锁，线程安全 |
| dot-notation 访问 | `config_loader.py:122-134` | ✅ | `config.get("brain.fsm.ma_short", 20)` |
| 配置验证 | `config_loader.py:136-303` | ✅ | 完整的类型和范围检查 |
| config.yaml 加载 | `config_loader.py:66-69` | ✅ | 主配置文件 |
| trading.yaml | 全局 | ❌ | 未被 GlobalConfig 加载 |
| factors.yaml | 全局 | ❌ | 未被 GlobalConfig 加载 |
| optimal_params.yaml | 全局 | ❌ | 未被 GlobalConfig 加载 |
| 混合日志系统 | `config_loader.py:8` | ⚠️ | 使用 `logging.getLogger` 而非项目 `get_logger` |

#### D.4 Protocol 接口

| Protocol | 文件:行号 | 使用处 | 运行时检查 |
|----------|-----------|--------|------------|
| DataFetcherProtocol | `interfaces.py:102-120` | `brain/indicators.py:8` (仅类型提示) | ❌ |
| RiskAssessmentProtocol | `interfaces.py:123-140` | `brain/fsm/fsm.py:16` (参数注解) | ❌ |
| PositionSizerProtocol | `interfaces.py:143-171` | `brain/fsm/fsm.py:16` (参数注解) | ❌ |
| AnalysisEngineProtocol | `interfaces.py:174-192` | 未使用 | ❌ |
| CalculationPluginProtocol | `interfaces.py:195-234` | 仅 CalculationRegistry 内部 | ❌ |
| CalculationRegistry | `interfaces.py:301-302` | 全局实例，未被任何模块调用 | ❌ |

#### D.5 异常处理机制

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| 异常层次 | `shared/exceptions.py:1-123` | ✅ | 31 个自定义异常，按领域组织 |
| @handle_errors 装饰器 | `shared/error_handling.py:63-176` | ⚠️ | 123+ 处调用，默认返回值而非抛异常 |
| 静默吞错 | `analysis_service.py:667-682` | ❌ | 返回硬编码默认字典，无法区分真实结果 |
| 过宽捕获 | `analysis_service.py:31-40` | ⚠️ | `RECOVERABLE_ERRORS` 捕获 8 种异常 |
| 异常重复定义 | `brain/czsc/czsc_engine.py:80` 等 | ⚠️ | 局部异常与中心化 exceptions.py 冲突 |
| 重试装饰器重复 | `error_handling.py:179-251` vs `retry_decorator.py:15-85` | ⚠️ | 两个实现共存 |

#### D.6 日志系统

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| LoggerFactory 单例 | `logger_factory.py:13-149` | ⚠️ | 无锁保护 |
| QueueHandler+QueueListener | `logger_factory.py:84-110` | ✅ | 线程安全的文件日志写入 |
| 根 logger 清空 | `logger_factory.py:67` | ⚠️ | `root_logger.handlers = []` 移除第三方 handler |
| 全局工厂变量 | `logger_factory.py:153-174` | ⚠️ | `_factory` 延迟初始化无锁 |
| 关键路径日志覆盖 | 全局 | ✅ | AnalysisService/DataService/DecisionBrain 30+ 处 |

#### D.7 服务层编排

| 组件 | 文件:行号 | 状态 | 说明 |
|------|-----------|------|------|
| AnalysisEngineFactory | `analysis/engine_factory.py:13-73` | ⚠️ | 注册 9 引擎，静默失败 return None |
| analyze_ticker 流程 | `analysis_service.py:727-744` | ✅ | prepare→run_engine→decision→save→report |
| 绕过工厂模式 | `analysis_service.py:803,859,923,954,981,996` | ❌ | 私有方法内直接导入 brain 子模块 |
| DataService 门面 | `data_service.py:35-517` | ⚠️ | 子依赖硬编码创建，无法 mock 测试 |
| DataFetcher 上帝对象 | `data/data_fetcher.py:58-268` | ⚠️ | 导入 10+ 模块，承担过多职责 |

---

*报告生成时间：2026-05-30 | 基于代码事实，零推测*
