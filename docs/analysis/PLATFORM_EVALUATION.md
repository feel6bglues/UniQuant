# UniQuant 研究平台综合评价

> **日期**: 2026-06-29 | **方法论**: 8 阶段深度分析 (Stage 0-7)
> **版本**: Phase 0-4 完成, 1363 测试通过, 12 预存失败

---

## 1. 总评

| 维度 | 得分 | 级别 |
|------|------|------|
| 整体成熟度 | **87/100** | 成熟研究平台 |
| 数据系统 | 9/10 | ✅ 顶级 |
| 研究引擎 | 8/10 | ✅ 强 |
| 信号系统 | 8/10 | ✅ 强 |
| 回测仿真 | 9/10 | ✅ 顶级 |
| 风控分析 | 8/10 | ✅ 强 |
| 服务编排 | 8/10 | ✅ 强 |
| 可复现性 | 6/10 | ⚠️ 需改进 |
| 可观测性 | 4/10 | ❌ 不足 |
| 文档同步 | 4/10 | ❌ 不足 |

**一句话**: UniQuant 是**A 股原生**的量化研究平台，在**数据获取、回测仿真、信号生成**方面达到生产级水准，但在**可观测性、研究结果持久化、文档维护**方面存在明显不足。

---

## 2. 架构评价

### 层设计

```
shared ← data ← brain/risk/signal → hands → services → ui
```

| 特性 | 评价 |
|------|------|
| 依赖方向 | **✅ 优秀** — 严格单向, 无循环依赖 |
| 模块化 | **✅ 优秀** — 8 层职责清晰, 边界明确 |
| 延迟导入 | **✅ 优秀** — `__getattr__` + `try/except` 模式贯穿各层 |
| 接口契约 | **✅ 好** — `Protocol`, `TradingSignal`, `RefactoringConfig` |
| 依赖注入 | **✅ 好** — `ServiceContainer` DAG 初始化 |
| 特征标记 | **✅ 好** — `FeatureFlags` 控制渐进式迁移 |
| 事件总线 | **✅ 好** — 同步 + 异步 `EventBus` |
| 文件大小 | **⚠️ 部分** — 多数 <800 LOC, 但 `eastmoney.py:1094` 超出 |

### 代码度量

| 指标 | 值 | 评价 |
|------|-----|------|
| Python 文件 | 254 | 合理规模 |
| 总 LOC | 62,816 | 中等规模项目 |
| 测试函数 | ~1,354 | 覆盖广泛 |
| 测试通过率 | 1363/1375 (99.1%) | 优秀, 12 失败预存 |
| 单文件最大 | `eastmoney.py` 1,094 LOC | 超出 800 限, 需拆分 |
| __init__ 延迟导入 | 全部 8 层 | 一致性好 |

---

## 3. 分层评价

### 3.1 数据系统 (9/10) ✅ 最强层

```
5 数据源 → SourceRouter(故障转移+竞速) → StandardAdapter(标准化)
  → DataPipeline(清洗→验证→复权) → StorageManager(Parquet 湖)
  → 12 Managers + 7 脚本 + 6 工具
```

**优势**:
- **5 源故障转移**: TDX(本地)+BaoStock+Sina+THS+Tencent, 单源失败不影响整体
- **双模式路由**: 顺序重试 + 并发竞速, 熔断器保护上游
- **向量化复权**: `merge_asof` + `cutoff_date` 防未来泄露 + 因子异常值检查
- **20+ 列名标准化**: 统一各源不同的中文/英文/缩写命名
- **原子写入 + 路径安全**: FileLock + tmp rename + resolve() 检查
- **7 个增量更新脚本**: 独立运维的数据加载管道

**不足**:
- `DataFetcher` 和 `DataIngestionService` 功能重复 (R2-1)
- `TradeCalendarManager` 假期硬编码至 2026 年 (R2-3)
- 价格缓存重启即失效 (R2-4)
- 实时桥接 RealtimeBridge 仅脚手架 — 但研究平台可接受

### 3.2 研究引擎 (8/10) ✅ 强

```
7 引擎: Regime → LPPL → NTF → CZSC → Wyckoff → Alpha → Derived
决策: FSM(7 状态) → Veto(硬约束) → Score(加权) → SELL(优先) → BUY(阻塞检查)
```

**优势**:
- **7 引擎组合**: 覆盖技术分析(CZSC/Wyckoff), 统计(Regime), 泡沫检测(LPPL), 异常检测(NTF), 因子(Alpha)
- **Veto-Scoring 决策架构**: 先否决(硬约束), 再评分(软决策), 最后 SELL 优先
- **Typed Outputs**: `RegimeOutput`, `LPPLOutput`, `NtfOutput`, `CZSCOutput`, `WyckoffOutput`, `AlphaOutput`
- **EngineFactory 注册制**: 引擎可插拔, 新引擎只需注册
- **16 个 FactorRegistry 导入**: 因子被多处使用

**不足**:
- Brain 文件数骤降 (74→55, -19 文件) 未解释 (R3-1)
- Wyckoff 12 个测试预存失败 — 需要排查根本原因 (R3-2)
- 两套信号体系并行 — 旧 Dict 路径和新 ResearchDataPack 路径 (R5-1)

### 3.3 信号系统 (8/10) ✅ 强

```
TradingSignalCollector(7 适配器) → SignalArbitrator(SELL 优先)
  → UnifiedBacktestEngine(7 道防线)
```

**优势**:
- **仲裁器 7 步流水线**: `arbitrate_candidates` → veto_ids → bypass → _filter_by_quality → _prioritize → _sell_priority → _compare_signals
- **SELL 优先**: LPPL SELL > BUY > 非LPPL SELL
- **质量门**: 最低置信度 + Veto 链 + 投票 vs 仲裁
- **Bypass 机制**: 高置信度 LPPL SELL 跳过仲裁直接执行

**不足**:
- 两套并行信号体系 (TradingSignal + 旧 Dict) (R5-1)
- Signal 协议未集成到 Gate (R5-3)
- 冗余适配器 `adapt_NtfOutput` 和 `noop_adapter_for_ntf` (R5-4)

### 3.4 回测仿真 (9/10) ✅ 最强层

```
UnifiedBacktestEngine → UnifiedMatchingEngine(Vectorized)
7 道防线: T+1 → 涨跌停 → 停牌 → 不透支 → 成本 → 滑点 → 整手
```

**优势**:
- **7 道防线**: A 股全套约束 — T+1 交易日检查、涨跌停拦截、停牌不成交、现金实时扣减、非对称成本(印花税卖方+最低佣金)、滑点(非线性/交易量感知)、整手 100 股
- **向量化撮合**: 支持批量回测, `FillResult` 含 8 个掩码, 拒绝原因可追溯
- **非线性滑点**: `0.001 * sqrt(trade_volume / avg_daily_volume)`, clip at 2%
- **幸存者偏差检测**: 自动检查退市日期
- **8 个辅助分析工具**: 蒙特卡洛、过拟合检测、稳健性检查、敏感性分析、参数验证、报告生成

**不足**:
- 回测引擎内部有独立的信号优先级 — 与仲裁器优先级不同 (R6-1)
- 向量化 T+1 用 Python for-loop 而非纯向量化 (R6-2)
- 同一天多信号只执行第一个 (R6-4)

### 3.5 风控分析 (8/10) ✅ 强

```
PositionSizer → DrawdownAnalyzer + HistoricalSimulationRisk + PortfolioOptimizer
  → StructuralRiskManager
```

**优势**:
- **4 种风险评估**: VaR/CVaR/MDD/结构性风险
- **纯 NumPy 向量化**: 回撤分析零 iterrows
- **Ledoit-Wolf Shrinkage**: 组合优化的协方差稳定估计
- **线程安全**: EVTRisk 使用 threading.Lock 保护缓存
- **凯利+T+1+整手**: A 股原生仓位计算

**不足**:
- 研究结果无持久化 (R7-1)
- 因子无衰减监控 (R7-8)
- 参数网格搜索缺失 (R7-5)
- Walk-Forward 分析未集成主流水线 (R7-6)

### 3.6 服务编排 (8/10) ✅ 强

```
ServiceContainer.initialize() → 15 步 DAG 初始化 → 9 引擎注册 → Pipeline
```

**优势**:
- **DAG 依赖注入**: 15 步初始化, 生命周期管理
- **延迟加载**: EngineFactory 按需初始化引擎
- **缓存协调**: 三级 TTL (short/standard/extended)
- **完整分析流水线**: prepare → engines → decision → collect → arbitrate → backtest
- **批处理并行**: ThreadPoolExecutor + 原子 checkpoint

**不足**:
- 非 Engine 服务(scan/health/report) 未在 DAG 中的引擎部分统一注册
- 6 处接口漂移点 (R1-2)

---

## 4. 平台优势总结

### 4.1 A 股原生 (核心竞争力)

| 特性 | 实现 |
|------|------|
| T+1 铁律 | `_check_t1()` + 向量化 T+1 mask |
| 涨跌停板 | `_check_limit()` + `compute_limit_status_vectorized()` |
| 停牌检查 | volume=0 跳过成交 |
| 非对称成本 | 佣金(max(value×费率, 5元)) + 印花税(仅卖方) + 过户费 |
| 整手取整 | `lot_size = get_board_rule(symbol).lot_size` |
| 新股规则 | 首日 44% 涨跌幅, 科创/创业板前 5 日无限制 |
| 印花税日期感知 | `get_stamp_tax_pct(timestamp.date())` 历史税率回溯 |
| 复权防泄露 | `cutoff_date` 防止未来除权泄露 |

### 4.2 多源容错

- **5 数据源**: TDX(速度) + BaoStock(质量) + Sina(实时) + THS(资金流) + Tencent(因子)
- **攻模式**: 顺序重试 + 熔断器 + 健康状态追踪
- **竞速模式**: 并发请求取最快
- **标准化**: 所有源输出统一列名格式

### 4.3 决策引擎

- **7 引擎组合**: 不同方法论交叉验证
- **Veto-Scoring**: 先否决再评分, 减少假阳性
- **SELL 优先**: 风险控制优先
- **EventBus**: 引擎完成事件驱动

### 4.4 研究复现

- **FrozenTimeProvider**: 测试用冻结时间
- **基线回归测试**: `golden_20.txt` / `golden_100.txt`
- **RefactoringConfig**: 特征标记控制渐进式迁移
- **FactorRegistry + Gate**: 因子可见性控制

---

## 5. 待改进项 (按优先级)

### P0 — 无 (0 项阻塞)

### P1 — 研究质量 (4 项)

| ID | 问题 | 影响 | 建议 |
|----|------|------|------|
| **R5-1** | 两套并行信号体系 | 信号路径分裂, 行为不一致 | 统一到 TradingSignal, 移除旧 Dict 路径 |
| **R3-2** | 12 个 Wyckoff 测试预存失败 | 测试面不纯净 | 修复或确诊预存原因 |
| **R6-1** | 回测引擎内部独立优先级 | 仲裁结果可能被覆盖 | 回测使用仲裁后信号, 不再重复仲裁 |
| **R7-1** | 研究结果无持久化 | 重启丢失分析记录 | 添加 SQLite/Parquet 结果存储 |

### P2 — 研究效率 (5 项)

| ID | 问题 | 影响 | 建议 |
|----|------|------|------|
| **R2-1** | DataFetcher + DataIngestionService 重复 | 两条数据入口 | 合并/委托 |
| **R6-2** | T+1 for-loop 非向量化 | 批量回测性能瓶颈 | 向量化 numpy |
| **R7-2** | 无交互式 Notebook 集成 | 限制深层探索 | 添加 `uniquant.research` 模块 |
| **R7-5** | 参数网格搜索缺失 | 手动调参 | 集成 optuna |
| **R3-4** | EngineFactory import 错误捕获不完整 | 引擎静默失败 | 精确异常处理 |

### P3 — 研究体验 (5 项)

| ID | 问题 | 影响 | 建议 |
|----|------|------|------|
| **R2-3** | 假期硬编码 2024-2026 | 2027 年 T+1 失效 | 添加自动假期更新 |
| **R7-8** | 因子无衰减监控 | 因子失效不易察觉 | IC 半衰期跟踪 |
| **R7-6** | Walk-Forward 未集成 | 固定区间回测 | 集成到主流水线 |
| **R5-3** | Signal 协议未集成 Gate | 因子门无效 | Signal 通过 Gate 注册 |
| **R6-4** | 同天多信号只执行第一个 | 丢失交易机会 | 信号取并集 |

---

## 6. 代码质量评价

| 维度 | 评价 |
|------|------|
| **类型提示** | ✅ 优秀 — Protocol + TypedDict + dataclass 广泛使用 |
| **错误处理** | ✅ 好 — handle_errors 装饰器 + RECOVERABLE_ERRORS 元组 |
| **文档字符串** | ✅ 好 — 大多数函数有 docstring |
| **代码注释** | ✅ 适度 — 有但不过量 |
| **测试覆盖** | ✅ 好 — 1,354 函数, 115 文件 |
| **导入管理** | ✅ 优秀 — 延迟导入 + try/except 容错 |
| **代码重复** | ⚠️ 部分 — DataFetcher/IngestionService, adapt_NtfOutput/noop_adapter |
| **大文件** | ⚠️ 部分 — eastmoney.py 1,094 LOC, ths.py 620, sina.py 609 |
| **死代码** | ⚠️ 部分 — engine.py(747LOC) 弃用, portfolio_engine.py(373) 弃用, result.py(175) 弃用 |
| **文档同步** | ❌ 不足 — AGENTS.md 多处过时, docs/ 与代码不同步 |

---

## 7. 与同类平台对比

| 特性 | UniQuant | Backtrader | QuantConnect | Zipline |
|------|----------|------------|--------------|---------|
| **A 股规则** | ✅ 完整 (7 道防线) | ❌ 需自定义 | ❌ 需自定义 | ❌ 需自定义 |
| **多源故障转移** | ✅ 5 源 + 熔断 | ❌ 单源 | ⚠️ 多 API | ❌ 单源 |
| **复权** | ✅ QFQ/HFQ + cutoff 防泄露 | ❌ 无 | ⚠️ 有限 | ✅ 有 |
| **研究引擎** | ✅ 7 引擎组合 | ⚠️ 需扩展 | ⚠️ 需扩展 | ❌ 无 |
| **信号仲裁** | ✅ SELL 优先 + 质量门 | ❌ 无 | ❌ 无 | ❌ 无 |
| **向量化撮合** | ✅ A 股 7 道防线 | ❌ 逐行 | ✅ 向量化 | ✅ 向量化 |
| **因子门控** | ✅ FactorRegistry+Gate | ❌ 无 | ❌ 无 | ❌ 无 |
| **特征标记** | ✅ FeatureFlags | ❌ 无 | ❌ 无 | ❌ 无 |
| **事件驱动** | ✅ EventBus(同步+异步) | ✅ 有 | ✅ 有 | ❌ 无 |
| **中国市场数据** | ✅ 5 数据源内置 | ❌ 需第三方 | ⚠️ 有限 | ❌ 无 |
| **延迟导入** | ✅ 全层 | ❌ 无 | N/A | ❌ 无 |
| **DAG 注入** | ✅ ServiceContainer | ❌ 无 | ❌ 无 | ❌ 无 |

**UniQuant 核心差异化**: A 股原生 + 多源容错 + 信号仲裁 + 因子门控 + 7 引擎研究

---

## 8. 结论

UniQuant 是一个**以 A 股市场为核心**的成熟量化研究平台。与通用平台 (Backtrader/QuantConnect/Zipline) 相比, 其最大差异在于:

1. **A 股内建** — T+1、涨跌停、停牌、非对称成本、整手取含、新股规则、历史印花税回溯 — **无需自定义**, 开箱即用
2. **多源容错** — 5 个 A 股数据源故障转移, 研究不依赖单一数据源
3. **研究引擎丰富** — 7 个量化模型引擎覆盖不同方法论
4. **信号仲裁** — SELL 优先 + 质量门, 业内罕见的信号治理层
5. **工程纪律好** — 8 层无循环依赖、延迟导入、特征标记控制系统迁移

主要短板在**可观测性**和**研究结果管理** — 作为研究平台, 缺少 Notebook 集成和系统化的结果持久化, 限制了深层探索和团队协作。

**评级: 87/100 — 适合 A 股量化研究团队的中长期平台选择**。
