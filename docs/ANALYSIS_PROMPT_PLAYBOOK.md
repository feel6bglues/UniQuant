# UniQuant Analysis Prompt Playbook

> Direct-call prompts for staged UniQuant system analysis.
>
> Use this file when you want an agent to analyze the system from architecture through live-readiness with checkpoints, artifacts, and validation.

---

## How To Use

Start with the control prompt, then run stages 0 through 7. Each stage is self-contained and can be resumed after interruption.

Expected artifact directory:

`docs/analysis/`

Before running any stage, the agent must read:

- `AGENTS.md`
- `docs/index.md`
- `pyproject.toml`
- current `git status --short`

The agent must not modify source code unless explicitly asked. Stage artifacts may be written under `docs/analysis/`.

---

## Control Prompt

```text
你是顶尖量化金融系统架构师、顶尖 Python 程序员、顶尖中国 A 股交易员。你正在分析 UniQuant 项目。

工作规则：
1. 先阅读当前代码和控制文档，不要依赖旧迁移期文档下结论。
2. 每个阶段开始前，先输出本阶段计划。
3. 每个阶段结束时，必须输出：
   - 阶段结论
   - 已阅读文件
   - 关键发现
   - 风险点
   - 已生成或应生成的产物
   - 校验清单
   - 下一阶段输入
4. 中途可以断点。断点时必须输出“续做上下文”，包含：
   - 当前阶段
   - 已完成内容
   - 未完成内容
   - 下一步应读文件
   - 已确认事实
   - 待验证假设
5. 不修改代码，除非我明确要求。
6. 所有结论必须绑定到具体文件、类、函数、配置项或测试。
7. 不允许泛泛而谈；所有建议都要能落地。
8. 不要声称测试通过，除非本轮实际运行过对应命令。

先读取：
- AGENTS.md
- docs/index.md
- pyproject.toml
- git status --short

然后等待我指定阶段，或从阶段 0 开始。
```

---

## Stage 0 - Global Architecture

```text
执行阶段 0：UniQuant 全局架构识别。

目标：
建立系统总览，识别模块边界、依赖方向、核心业务链路和控制文档状态。

计划要求：
1. 阅读 AGENTS.md、docs/index.md、pyproject.toml、config/config.yaml。
2. 扫描 src/uniquant/ 目录结构。
3. 识别 shared、data、brain、signal、hands、risk、services、ui 八层职责。
4. 找出核心入口文件和高风险文件。
5. 区分当前事实、历史文档、待验证假设。

重点文件：
- AGENTS.md
- docs/index.md
- pyproject.toml
- config/config.yaml
- src/uniquant/shared/interfaces.py
- src/uniquant/services/service_container.py
- src/uniquant/services/analysis_service_v2.py
- src/uniquant/services/research_pipeline.py

产物：
- docs/analysis/00_architecture_map.md

产物必须包含：
1. 系统定位
2. 八层模块职责表
3. 核心数据流和控制流
4. 关键入口文件清单
5. 高风险文件清单
6. 当前架构优点
7. 当前架构风险
8. 阶段 1 输入清单

校验：
1. 是否覆盖八层模块。
2. 是否说明 DAG 依赖方向。
3. 是否列出至少 10 个关键文件。
4. 是否明确哪些旧文档不可直接信任。
5. 是否把结论绑定到具体文件。
```

---

## Stage 1 - Services Orchestration

```text
执行阶段 1：services 层编排分析。

目标：
分析 UniQuant 如何通过服务层组织数据、引擎、信号、回测和研究流水线。

计划要求：
1. 读取阶段 0 产物。
2. 画出 ServiceContainer 初始化顺序。
3. 分析 AnalysisService.run_ticker_analysis 的完整流程。
4. 分析 AnalysisEngineFactory 的懒加载机制。
5. 分析 UnifiedResearchPipeline 如何串联分析、信号和回测。
6. 检查循环依赖、隐式耦合、接口漂移和失败路径。

重点文件：
- src/uniquant/services/service_container.py
- src/uniquant/services/analysis_service_v2.py
- src/uniquant/services/research_pipeline.py
- src/uniquant/services/analysis/engine_factory.py
- src/uniquant/services/__init__.py
- tests/test_engine_factory.py

产物：
- docs/analysis/01_services_orchestration.md

产物必须包含：
1. 服务依赖拓扑图
2. 单票分析流程图
3. 研究流水线流程图
4. 服务注册表
5. 引擎工厂注册清单
6. 失败路径和默认值
7. 风险与改进建议

校验：
1. 是否能解释 ServiceContainer.initialize 每一步。
2. 是否能解释 run_ticker_analysis 的输入输出。
3. 是否说明 engine_factory 何时 bind orchestrator。
4. 是否识别缓存、数据服务、分析服务之间的边界。
```

---

## Stage 2 - Data System

```text
执行阶段 2：data 层数据系统分析。

目标：
理解 A 股数据接入、数据湖、缓存、清洗、校验、复权和更新机制。

计划要求：
1. 读取阶段 0 和阶段 1 产物。
2. 梳理所有数据源和 source routing。
3. 分析 fetch_for_brain 如何生成 data_pack。
4. 分析数据清洗、校验、复权、对齐流程。
5. 分析数据湖存储结构和读取方式。
6. 审计缺失数据、错价、未来数据、缓存污染和字段不一致风险。

重点文件：
- src/uniquant/data/data_fetcher.py
- src/uniquant/services/data_service.py
- src/uniquant/data/lake/storage_manager.py
- src/uniquant/data/pipeline/data_cleaner.py
- src/uniquant/data/pipeline/data_validator.py
- src/uniquant/data/pipeline/data_adjuster.py
- src/uniquant/data/managers/source_router.py
- src/uniquant/data/managers/market_data_coordinator.py
- src/uniquant/data/sources/
- config/config.yaml

产物：
- docs/analysis/02_data_system.md

产物必须包含：
1. 数据源矩阵
2. 数据流入流程
3. 数据清洗校验流程
4. 数据湖读写机制
5. A 股字段要求表
6. fetch_for_brain 输出结构
7. 数据质量风险清单
8. 数据系统改进建议

校验：
1. 是否说明股票、指数、ETF、行业数据路径。
2. 是否说明数据为空、数据源失败时的行为。
3. 是否检查 date/open/high/low/close/volume/pre_close 等字段。
4. 是否说明哪些数据可用于回测，哪些只适合展示或研究。
```

---

## Stage 3 - Brain Engines

```text
执行阶段 3：brain 层多引擎分析。

目标：
理解每个分析引擎的策略含义、输入输出、信号解释和 A 股适用性。

计划要求：
1. 读取阶段 0-2 产物。
2. 对每个引擎建立输入、处理、输出表。
3. 分析每个引擎如何写入 data_pack。
4. 分析 DecisionBrain 如何综合各类信息。
5. 区分交易信号、风险过滤器、市场环境判断。
6. 检查多引擎之间的信号冲突。

重点文件：
- src/uniquant/brain/fsm/
- src/uniquant/brain/czsc/
- src/uniquant/brain/lppl/
- src/uniquant/brain/ntf/
- src/uniquant/brain/regime/
- src/uniquant/brain/wyckoff/
- src/uniquant/brain/alpha_decoupler/
- src/uniquant/brain/indicators/
- src/uniquant/services/analysis/*_analysis_engine.py
- src/uniquant/services/analysis_service_v2.py

产物：
- docs/analysis/03_brain_engines.md

产物必须包含：
1. 引擎清单
2. 每个引擎的业务含义
3. 输入输出字段表
4. data_pack 字段来源表
5. DecisionBrain 决策流程
6. A 股适用性评价
7. 信号冲突风险

校验：
1. 是否覆盖 FSM、CZSC、LPPL、NTF、Regime、Wyckoff、Alpha、Indicators。
2. 是否说明每个引擎失败时默认值。
3. 是否说明哪些输出适合买入、卖出、观望、风控。
4. 是否绑定具体文件和函数。
```

---

## Stage 4 - Factor System

```text
执行阶段 4：因子系统分析。

目标：
分析因子注册、计算、评价、组合、样本外验证和未来函数防护。

计划要求：
1. 读取阶段 0-3 产物。
2. 分析 FactorRegistry 如何注册、启用、禁用和加权。
3. 分析 FactorAnalyzer 如何计算 Rank IC、ICIR、持有期收益。
4. 分析未来函数检测机制。
5. 分析因子组合、权重、行业中性化、滚动验证。
6. 从 A 股横截面选股角度评价因子系统。

重点文件：
- src/uniquant/brain/factors/registry.py
- src/uniquant/brain/factors/analyzer.py
- src/uniquant/brain/factors/custom_factors.py
- src/uniquant/brain/factors/composer.py
- src/uniquant/brain/factors/neutralizer.py
- src/uniquant/brain/factors/walk_forward_pipeline.py
- config/factors.yaml
- experiments/run_factor_ic_evaluation.py
- experiments/run_walk_forward_pipeline.py
- experiments/run_real_data_ic.py

产物：
- docs/analysis/04_factor_system.md

产物必须包含：
1. 因子注册机制
2. 因子计算流程
3. IC/IR 分析流程
4. 未来函数防护机制
5. 因子上线标准
6. 当前因子体系风险
7. 从研究到实盘的改进路线

校验：
1. 是否区分 backtest mode 和 live mode。
2. 是否说明 negative shift 的风险。
3. 是否说明样本内、样本外、滚动验证。
4. 是否提出可执行的因子准入标准。
```

---

## Stage 5 - Signal System

```text
执行阶段 5：signal 层分析。

目标：
理解 Brain 输出如何转换为统一 TradingSignal，并分析多信号冲突、优先级和实盘适配问题。

计划要求：
1. 读取阶段 0-4 产物。
2. 分析 TradingSignal 数据结构。
3. 分析各 EngineAdapter 的映射规则。
4. 分析 TradingSignalCollector 如何从 data_pack 收集信号。
5. 检查 BUY、SELL、HOLD 冲突处理。
6. 检查 confidence、shares、price、timestamp 是否合理。
7. 设计一个更适合 A 股实盘的信号聚合方案。

重点文件：
- src/uniquant/shared/interfaces.py
- src/uniquant/signal/adapters.py
- src/uniquant/signal/aggregator.py
- src/uniquant/signal/normalizer.py
- src/uniquant/signal/quality.py
- src/uniquant/services/research_pipeline.py

产物：
- docs/analysis/05_signal_system.md

产物必须包含：
1. TradingSignal 字段说明
2. 引擎输出到信号的映射表
3. 信号收集流程
4. 信号冲突案例
5. 当前问题
6. 推荐信号优先级和聚合规则
7. 实盘信号校验标准

校验：
1. 是否覆盖 LPPL、CZSC、Wyckoff、FSM、Regime、NTF、Alpha、MA。
2. 是否指出多个 BUY/SELL 同时出现时的风险。
3. 是否检查 timestamp 对回测 T+1 的影响。
4. 是否给出确定性聚合规则。
```

---

## Stage 6 - Backtest And Matching

```text
执行阶段 6：hands 回测与撮合分析。

目标：
分析回测真实性，重点检查 A 股 T+1、涨跌停、停牌、滑点、佣金、印花税、整手和现金约束。

计划要求：
1. 读取阶段 0-5 产物。
2. 分析 UnifiedBacktestEngine 的单标的回测流程。
3. 分析 UnifiedMatchingEngine 的向量化撮合规则。
4. 检查 T+1、涨跌停、停牌、现金、成本、滑点、整手是否生效。
5. 分析信号时间和成交时间是否合理。
6. 分析单票回测与组合回测差异。
7. 从真实 A 股交易角度列出偏差。

重点文件：
- src/uniquant/hands/backtest/unified_engine.py
- src/uniquant/hands/backtest/unified_matching_engine.py
- src/uniquant/hands/backtest/portfolio_engine.py
- src/uniquant/hands/backtest/result.py
- src/uniquant/hands/strategies/
- src/uniquant/shared/cost_model.py
- src/uniquant/shared/limit_checker.py
- src/uniquant/shared/price_collar.py
- src/uniquant/shared/market_rules.py

产物：
- docs/analysis/06_backtest_matching.md

产物必须包含：
1. 回测流程图
2. 撮合规则表
3. A 股交易约束校验表
4. 成交成本模型
5. 信号到订单到成交流程
6. 回测偏差风险
7. 改进建议

校验：
1. 是否验证 T 日信号、T+1 open 成交逻辑。
2. 是否验证涨停不买、跌停不卖。
3. 是否验证印花税只在卖出侧。
4. 是否验证资金不能透支。
5. 是否检查停牌 volume=0。
```

---

## Stage 7 - Risk And Live Readiness

```text
执行阶段 7：risk 层和系统实盘可用性审计。

目标：
分析仓位管理、风险度量、组合优化、回撤控制，并形成系统实盘前整改清单。

计划要求：
1. 读取阶段 0-6 产物。
2. 分析 PositionSizer 仓位计算逻辑。
3. 分析止损、ATR、CZSC 底分型、T+1 penalty 如何影响仓位。
4. 分析风险指标：回撤、历史风险、EVT、组合优化。
5. 检查风控是否真正接入信号、回测和服务层。
6. 审计实盘前缺口：数据、信号、风控、执行、监控。
7. 给出优先级排序的整改路线。

重点文件：
- src/uniquant/risk/sizer.py
- src/uniquant/risk/drawdown_analyzer.py
- src/uniquant/risk/evt_risk.py
- src/uniquant/risk/historical_risk.py
- src/uniquant/risk/portfolio_optimizer.py
- src/uniquant/risk/structural.py
- src/uniquant/services/portfolio_service.py
- src/uniquant/services/health_service.py
- src/uniquant/ui/dashboard.py

产物：
- docs/analysis/07_risk_live_readiness.md

产物必须包含：
1. 仓位 sizing 机制
2. 风控模块清单
3. 风控闭环分析
4. 实盘可用性评分
5. 高风险缺口
6. P0/P1/P2 整改计划
7. 最终系统功能总结

校验：
1. 是否说明 risk_pct、kelly_fraction、T+1 penalty。
2. 是否检查止损无效时的异常处理。
3. 是否说明风控是否影响实际下单或回测。
4. 是否形成实盘前检查清单。
```

---

## Resume Prompt

```text
继续 UniQuant 系统分析。

当前已有阶段产物：
- docs/analysis/00_architecture_map.md
- docs/analysis/01_services_orchestration.md
- 按实际已有文件填写

请先读取：
- AGENTS.md
- docs/index.md
- docs/ANALYSIS_PROMPT_PLAYBOOK.md
- 已有阶段产物
- git status --short

然后继续执行阶段 X。

要求：
1. 不重复已经完成的结论。
2. 先输出续做计划。
3. 明确本轮要补哪些文件、验证哪些假设。
4. 结束时更新阶段产物。
5. 输出新的断点上下文和下一阶段输入。
```

---

## Final Acceptance Prompt

```text
请对阶段 0-7 的所有分析产物做最终验收。

要求：
1. 检查每个阶段产物是否完整。
2. 检查结论是否绑定具体代码文件。
3. 检查是否存在互相矛盾的判断。
4. 检查是否覆盖：
   - 架构
   - 数据
   - 多引擎分析
   - 因子
   - 信号
   - 回测撮合
   - 风控
   - 实盘可用性
5. 输出最终报告：
   - 系统功能总览
   - 已具备能力
   - 核心风险
   - P0/P1/P2 整改计划
   - 下一步开发建议
6. 不要声称测试通过，除非本轮实际运行过对应验证命令。
```
