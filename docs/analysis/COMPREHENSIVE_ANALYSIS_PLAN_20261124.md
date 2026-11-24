# UniQuant 系统全面分析计划（2026-11-24）

> **背景**：项目已完成25轮迭代，当前工作树干净。本计划旨在对系统进行全面、系统化的深度分析，
> 识别架构优势、潜在风险和改进机会，形成可落地的整改建议。

---

## 一、分析目标

1. **架构健康度评估**：验证8层架构的清晰度、依赖方向和耦合程度
2. **核心链路完整性**：端到端追踪数据→引擎→信号→回测→风控的关键路径
3. **A股规则合规性**：审计T+1、涨跌停、成本模型等交易规则的正确性
4. **生产就绪度评估**：识别从当前状态到实盘部署的差距
5. **代码质量与可维护性**：评估测试覆盖、文档同步、技术债务
6. **性能与可扩展性**：识别瓶颈和优化机会

---

## 二、分析阶段规划

### 阶段 0：全局架构识别（1-2小时）
**目标**：建立系统总览，识别模块边界、依赖方向、核心业务链路

**任务清单**：
- [ ] 阅读控制文档：`AGENTS.md`、`docs/index.md`、`pyproject.toml`、`config/config.yaml`
- [ ] 扫描 `src/uniquant/` 目录结构，统计各层文件数和LOC
- [ ] 分析8层职责：shared、data、brain、signal、hands、risk、services、ui
- [ ] 绘制核心数据流：`DataService → AnalysisService → DecisionBrain → SignalCollector → BacktestEngine`
- [ ] 识别关键入口文件和高风险文件（至少10个）
- [ ] 验证DAG依赖方向，检查是否存在循环依赖
- [ ] 区分当前事实vs历史文档vs待验证假设

**产物**：`docs/analysis/00_architecture_map.md`
**校验标准**：
- 覆盖全部8层模块
- 说明DAG依赖方向
- 列出≥10个关键文件
- 明确哪些旧文档不可直接信任

---

### 阶段 1：服务编排分析（1-2小时）
**目标**：分析services层如何组织数据、引擎、信号、回测和研究流水线

**任务清单**：
- [ ] 画出 `ServiceContainer.initialize()` 初始化顺序图
- [ ] 追踪 `AnalysisService.run_ticker_analysis()` 完整流程
- [ ] 分析 `AnalysisEngineFactory` 的懒加载机制
- [ ] 分析 `UnifiedResearchPipeline` 如何串联分析、信号和回测
- [ ] 检查循环依赖、隐式耦合、接口漂移和失败路径
- [ ] 验证服务注册表和引擎工厂注册清单

**重点文件**：
- `src/uniquant/services/service_container.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis/engine_factory.py`

**产物**：`docs/analysis/01_services_orchestration.md`
**校验标准**：
- 能解释 `ServiceContainer.initialize` 每一步
- 能解释 `run_ticker_analysis` 的输入输出
- 说明 engine_factory 何时 bind orchestrator

---

### 阶段 2：数据系统分析（2-3小时）
**目标**：理解A股数据接入、数据湖、缓存、清洗、校验、复权和更新机制

**任务清单**：
- [ ] 梳理所有数据源（mootdx本地/在线、财务、指数）和source routing
- [ ] 分析 `fetch_for_brain` 如何生成 `data_pack`
- [ ] 追踪数据清洗→校验→复权→对齐流程
- [ ] 分析数据湖存储结构（日线/5分钟/财务）和读取方式
- [ ] 审计数据质量风险：
  - 缺失数据、错价、未来数据（look-ahead bias）
  - 缓存污染、字段不一致
  - 复权因子错误、停牌处理
- [ ] 验证Freshness SLA和在线同步机制（第24-25轮新增）

**重点文件**：
- `src/uniquant/data/data_fetcher.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/data/lake/storage_manager.py`
- `src/uniquant/data/pipeline/data_cleaner.py`
- `src/uniquant/data/pipeline/data_validator.py`
- `src/uniquant/data/sources/mootdx_local.py`

**产物**：`docs/analysis/02_data_system.md`
**校验标准**：
- 说明股票/指数/ETF/行业数据路径
- 说明数据为空或数据源失败时的行为
- 检查date/open/high/low/close/volume/pre_close字段

---

### 阶段 3：多引擎分析（2-3小时）
**目标**：理解每个分析引擎的策略含义、输入输出、信号解释和A股适用性

**任务清单**：
- [ ] 对8个引擎建立输入→处理→输出表：
  - FSM（状态机）
  - CZSC（缠中说禅）
  - LPPL（对数周期幂律）
  - NTF（神经时序森林？）
  - Regime（市场状态识别）
  - Wyckoff（威科夫方法）
  - Alpha Decoupler（阿尔法解耦）
  - Indicators（技术指标）
- [ ] 分析每个引擎如何写入 `data_pack`
- [ ] 分析 `DecisionBrain` 如何综合各类信息
- [ ] 区分交易信号、风险过滤器、市场环境判断
- [ ] 检查多引擎之间的信号冲突（如BUY vs SELL）
- [ ] 评估每个引擎的A股适用性和实证效果（参考Wyckoff研究报告）

**重点文件**：
- `src/uniquant/brain/fsm/`
- `src/uniquant/brain/czsc/`
- `src/uniquant/brain/lppl/`
- `src/uniquant/brain/wyckoff/`
- `src/uniquant/services/analysis/*_analysis_engine.py`
- `src/uniquant/services/analysis_service_v2.py`

**产物**：`docs/analysis/03_brain_engines.md`
**校验标准**：
- 覆盖全部8个引擎
- 说明每个引擎失败时的默认值
- 说明哪些输出适合买入/卖出/观望/风控

---

### 阶段 4：因子系统分析（1-2小时）
**目标**：分析因子注册、计算、评价、组合、样本外验证和未来函数防护

**任务清单**：
- [ ] 分析 `FactorRegistry` 如何注册、启用、禁用和加权
- [ ] 分析 `FactorAnalyzer` 如何计算Rank IC、ICIR、持有期收益
- [ ] 验证未来函数检测机制（negative shift风险）
- [ ] 分析因子组合、权重、行业中性化、滚动验证
- [ ] 检查四阶门禁诚实化机制（Rule 4：不允许伪造输入）
- [ ] 从A股横截面选股角度评价因子系统
- [ ] 分析alpha_tier_engine的四层门禁（TIER_UNRATED fail-closed机制）

**重点文件**：
- `src/uniquant/brain/factors/registry.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/research/gates/alpha_tier_engine.py`
- `src/uniquant/research/` (科学控制平面)

**产物**：`docs/analysis/04_factor_system.md`
**校验标准**：
- 区分backtest mode和live mode
- 说明negative shift的风险
- 说明样本内/样本外/滚动验证
- 提出可执行的因子准入标准

---

### 阶段 5：信号系统分析（1-2小时）
**目标**：理解Brain输出如何转换为统一TradingSignal，分析多信号冲突、优先级和实盘适配

**任务清单**：
- [ ] 分析 `TradingSignal` 数据结构（字段、类型、约束）
- [ ] 分析各 `EngineAdapter` 的映射规则（LPPL→Signal、CZSC→Signal等）
- [ ] 分析 `TradingSignalCollector` 如何从 `data_pack` 收集信号
- [ ] 检查BUY、SELL、HOLD冲突处理（验证Sell-Priority机制）
- [ ] 检查confidence、shares、price、timestamp是否合理
- [ ] 验证timestamp对T+1规则的影响
- [ ] 设计更适合A股实盘的信号聚合方案

**重点文件**：
- `src/uniquant/shared/interfaces.py` (TradingSignal定义)
- `src/uniquant/signal/adapters.py`
- `src/uniquant/signal/arbitrator.py` (Sell-Priority)
- `src/uniquant/signal/aggregator.py`
- `src/uniquant/signal/quality.py`

**产物**：`docs/analysis/05_signal_system.md`
**校验标准**：
- 覆盖LPPL/CZSC/Wyckoff/FSM/Regime/NTF/Alpha/MA
- 指出多个BUY/SELL同时出现时的风险
- 检查timestamp对回测T+1的影响
- 给出确定性聚合规则

---

### 阶段 6：回测与撮合分析（2-3小时）
**目标**：分析回测真实性，重点检查A股T+1、涨跌停、停牌、滑点、佣金、印花税、整手和现金约束

**任务清单**：
- [ ] 分析 `UnifiedBacktestEngine` 的单标的回测流程
- [ ] 分析 `UnifiedMatchingEngine` 的向量化撮合规则
- [ ] 验证A股交易约束：
  - T+1（T日信号，T+1 open成交）
  - 涨停不买、跌停不卖
  - 印花税只在卖出侧
  - 资金不能透支
  - 停牌（volume=0）
  - 整手交易（100股整数倍）
- [ ] 分析成交成本模型（佣金/印花税/过户费/滑点）
- [ ] 分析信号时间和成交时间是否合理
- [ ] 分析单票回测vs组合回测差异
- [ ] 检查期指分仓和对冲机制（第25轮新增的IH对冲）

**重点文件**：
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/shared/cost_model.py`
- `src/uniquant/shared/limit_checker.py`
- `src/uniquant/shared/market_rules.py`

**产物**：`docs/analysis/06_backtest_matching.md`
**校验标准**：
- 验证T日信号→T+1 open成交逻辑
- 验证涨停不买、跌停不卖
- 验证印花税只在卖出侧
- 验证资金不能透支
- 检查停牌volume=0

---

### 阶段 7：风控与实盘就绪分析（2-3小时）
**目标**：分析仓位管理、风险度量、组合优化、回撤控制，形成实盘前整改清单

**任务清单**：
- [ ] 分析 `PositionSizer` 仓位计算逻辑（risk_pct、kelly_fraction、T+1 penalty）
- [ ] 分析止损、ATR、CZSC底分型、T+1 penalty如何影响仓位
- [ ] 分析风险指标：回撤、历史风险、EVT、组合优化
- [ ] 检查风控是否真正接入信号、回测和服务层
- [ ] 验证 `SharedKillSwitch` 熔断机制（第25轮Track 5）
- [ ] 审计实盘前缺口：
  - 数据：实时性、完整性
  - 信号：延迟、冲突
  - 风控：止损有效性、仓位限制
  - 执行：滑点、部分成交
  - 监控：告警、对账
- [ ] 给出优先级排序的P0/P1/P2整改路线

**重点文件**：
- `src/uniquant/risk/sizer.py`
- `src/uniquant/risk/drawdown_analyzer.py`
- `src/uniquant/risk/evt_risk.py`
- `src/uniquant/risk/portfolio_optimizer.py`
- `src/uniquant/shared/kill_switch.py`
- `src/uniquant/services/health_service.py`

**产物**：`docs/analysis/07_risk_live_readiness.md`
**校验标准**：
- 说明risk_pct、kelly_fraction、T+1 penalty
- 检查止损无效时的异常处理
- 说明风控是否影响实际下单或回测
- 形成实盘前检查清单

---

### 最终验收阶段（1-2小时）
**目标**：综合阶段0-7的发现，形成完整的系统评估报告

**任务清单**：
- [ ] 检查每个阶段产物是否完整
- [ ] 检查结论是否绑定具体代码文件
- [ ] 检查是否存在互相矛盾的判断
- [ ] 汇总系统能力矩阵（已具备/部分具备/缺失）
- [ ] 输出最终报告：
  - 系统功能总览
  - 已具备能力清单
  - 核心风险清单（按严重程度排序）
  - P0/P1/P2整改计划
  - 下一步开发建议

**产物**：`docs/analysis/FINAL_ACCEPTANCE_REPORT_20261124.md`

---

## 三、执行策略

### 并行执行建议
```
Wave 1（串行）：阶段 0（全局架构）
     ↓
Wave 2（并行）：阶段 1（服务编排） + 阶段 2（数据系统）
     ↓
Wave 3（并行）：阶段 3（多引擎） + 阶段 4（因子系统） + 阶段 5（信号系统）
     ↓
Wave 4（并行）：阶段 6（回测撮合） + 阶段 7（风控）
     ↓
Wave 5（串行）：最终验收报告
```

### 时间估算
- **总时长**：12-18小时（纯工作时间）
- **日历时长**：3-5个工作日（考虑审查和整理）
- **最优执行方式**：分3-5天，每天2-4小时深度分析

### 质量保证
1. **证据驱动**：所有结论必须绑定到具体文件、类、函数
2. **实测优先**：运行测试和验证命令，不依赖文档声明
3. **红蓝对抗**：对关键发现进行自我质疑和反驳
4. **诚实原则**：不夸大能力，不掩盖问题，未知就说未知

---

## 四、输出物清单

完成分析后，将产生以下文档：

```
docs/analysis/
├── COMPREHENSIVE_ANALYSIS_PLAN_20261124.md    (本文件)
├── 00_architecture_map.md                     (架构图)
├── 01_services_orchestration.md               (服务编排)
├── 02_data_system.md                          (数据系统)
├── 03_brain_engines.md                        (多引擎分析)
├── 04_factor_system.md                        (因子系统)
├── 05_signal_system.md                        (信号系统)
├── 06_backtest_matching.md                    (回测撮合)
├── 07_risk_live_readiness.md                  (风控与实盘就绪)
└── FINAL_ACCEPTANCE_REPORT_20261124.md        (最终验收报告)
```

---

## 五、风险与注意事项

1. **文档漂移**：部分历史文档可能已过时（如AGENTS.md中标注的"已过期"快照表），以当前代码为准
2. **测试真实性**：需在当前工作树实际运行测试，不能依赖文档中的历史测试结果
3. **数据依赖**：部分测试依赖本地数据湖（gitignored），CI环境会跳过这些测试
4. **复杂度**：项目规模大（230个源文件，56K+ LOC），需要系统性方法避免遗漏
5. **A股特殊性**：所有分析必须考虑A股市场的特殊规则和约束

---

## 六、启动条件

在开始执行分析前，确认：
- [ ] 工作树干净（`git status --short` 无输出）
- [ ] 已阅读 `AGENTS.md` 和 `CLAUDE.md`
- [ ] 已阅读 `docs/ANALYSIS_PROMPT_PLAYBOOK.md`
- [ ] 理解10条编码规则（TDD、ruff清洁、不伪造结果等）
- [ ] 准备好文档输出目录 `docs/analysis/`

---

**计划制定时间**：2026-11-24
**计划版本**：v1.0
**预计完成时间**：2026-11-27 至 2026-11-29
