# UniQuant 受控状态机审计与修复总报告

日期: 2026-06-09

关联提交: `91c2b06 remediate architecture risks and clear lint debt`

## 1. 报告范围

本报告汇总本轮“受控状态机”工作中的全部主要分析、修复、验证和剩余风险确认。详细阶段日志仍以 `docs/reshaping_logs/` 为准，本文件用于给后续维护者快速还原本轮工作的完整闭环。

本轮工作覆盖:

- 阶段 1: 全局拓扑扫描。
- 阶段 2: 数据、算法、撮合风控、异常和可复现性的分段深度核查。
- 阶段 3: P0/P1/P2 风险聚合与修复计划生成。
- 阶段 4: P0/P1 主修复。
- 后续迭代: P2 工程风险闭环、全仓 lint 历史债清理、提交。
- 追加确认: 剩余未完成项真实性核查。

## 2. 状态机产物索引

本轮所有阶段均已落盘。核心状态链如下:

| 文件 | 内容 |
|------|------|
| `docs/reshaping_logs/01_global_topology.md` | 全局拓扑、依赖方向、God Object、并行体系 |
| `docs/reshaping_logs/02_deep_inspection.md` | 四个防区的白盒核查原始证据 |
| `MASTER_REMEDIATION_PLAN.md` | P0/P1/P2 风险聚合和阶段 4 修复依据 |
| `docs/reshaping_logs/04_1_remediation.md` | 数据流、异常捕获、随机种子修复 |
| `docs/reshaping_logs/04_2_remediation.md` | 接口契约与标准信号转换修复 |
| `docs/reshaping_logs/04_3_remediation.md` | 被动风控防线修复 |
| `docs/reshaping_logs/05_1_p1_cache_invalidation.md` | 多层缓存失效广播 |
| `docs/reshaping_logs/05_2_p1_backtest_compat.md` | 旧回测入口复用统一撮合规则 |
| `docs/reshaping_logs/05_3_p1_data_entry_injection.md` | 数据入口依赖注入收敛 |
| `docs/reshaping_logs/05_4_p1_god_object_containment.md` | God Object 边界封装 |
| `docs/reshaping_logs/05_5_p1_factor_diagnostics.md` | 因子诊断透明化 |
| `docs/reshaping_logs/05_6_p1_reproducibility.md` | Monte Carlo/Bootstrap 可复现 |
| `docs/reshaping_logs/05_7_p1_di_container_compat.md` | DI 兼容层反向依赖收敛 |
| `docs/reshaping_logs/05_8_full_regression.md` | P0/P1 全量回归 |
| `docs/reshaping_logs/06_1_p2_trace_id.md` | TraceID 传播 |
| `docs/reshaping_logs/06_2_p2_ui_risk_boundary.md` | UI-risk 调用边界 |
| `docs/reshaping_logs/06_3_p2_docs_state_boundary.md` | 文档状态源边界 |
| `docs/reshaping_logs/06_4_p2_randomness_annotations.md` | 网络/mock 随机标注 |
| `docs/reshaping_logs/06_5_p2_final_closure.md` | P2 收口与最终回归 |
| `docs/reshaping_logs/07_1_lint_debt_cleanup.md` | 全仓 ruff 历史债清理 |
| `docs/reshaping_logs/08_final_handoff.md` | 最终交接摘要 |

## 3. 阶段 1: 全局拓扑分析结论

### 3.1 当前架构事实

项目当前为 8 个主要层级:

- `shared`: 公共接口、常量、配置、异常、缓存、成本/滑点、限价规则。
- `data`: 多数据源、数据湖、pipeline、fetcher、parser、数据服务。
- `brain`: CZSC、FSM、LPPL、Wyckoff、因子、Regime、NTF 等算法层。
- `signal`: 统一信号模型、adapter、归一化、聚合和质量模块。
- `risk`: 回撤、EVT、历史风险、组合优化、仓位和结构风险。
- `hands`: 回测、撮合、组合引擎、策略、调参。
- `services`: DI 容器、分析服务、工厂、业务服务编排。
- `ui`: Streamlit dashboard 和 manager 层。

期望依赖方向是:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

实际发现的问题集中在:

- 服务层兼容入口仍保留旧依赖形态。
- 旧回测入口和统一撮合入口并行。
- 数据访问存在多轨入口。
- 大对象文件聚合多个职责，降低可测试性。
- 部分容错路径会返回默认值，掩盖失败。

### 3.2 God Object 候选

| 文件 | 规模 | 结论 |
|------|------|------|
| `src/uniquant/services/analysis_service_legacy.py` | 约 1648 行 | 旧分析服务 God Object，缓存、采样、验证、引擎调用、报告混合 |
| `src/uniquant/ui/dashboard.py` | 1526 行 | UI God Object，页面、数据加载、错误处理、业务调用集中 |
| `src/uniquant/brain/wyckoff/engine.py` | 1457 行 | Wyckoff 算法 God Object |
| `src/uniquant/data/sources/eastmoney.py` | 1094 行 | 数据源 God Object，网络、解析、字段映射、容错集中 |
| `src/uniquant/brain/lppl/engine.py` | 1040 行 | LPPL 扫窗、拟合、风险输出职责集中 |
| `src/uniquant/brain/fsm/fsm.py` | 765 行 | FSM 状态、决策、执行边界混合 |

本轮没有对上述大对象进行大规模拆分。原因是这些文件仍连接多个测试和生产路径，直接手术会制造高回归风险。本轮采取的策略是先通过 adapter、typed result、依赖注入、边界封装、诊断输出降低风险，为后续拆分建立保护网。

### 3.3 并行和冗余体系

发现的主要并行体系:

- 新旧分析服务并行: `analysis_service_legacy.py`、`analysis_service_v2.py`、`services/analysis/*`。
- 新旧回测入口并行: 旧 `hands/backtest/engine.py` 与统一撮合/组合引擎。
- 数据入口多轨: `DataFetcher`、`DataService`、数据湖、旧服务内部直接实例化。
- 信号表达多轨: 字典式 engine result 与标准 `TradingSignal` 并行。
- 文档状态多轨: 早期迁移文档与当前实测源码状态冲突。

## 4. 阶段 2: 分段深度核查结论

### 4.1 队列 A: 数据与基础设施

重点核查:

- 数据清洗、对齐、pipeline。
- `.shift(-1)` 前视偏差风险。
- 缓存是否支持统一失效。
- 多数据入口是否共享状态。

主要结论:

- 数据对齐存在潜在前视偏差风险，需要明确区分“预测目标”与“特征对齐”。
- 多层缓存缺少统一失效广播，可能造成服务层、数据层、数据湖缓存状态不一致。
- 部分旧服务内部直接创建数据入口对象，绕过注入对象，造成测试/生产路径分叉。

### 4.2 队列 B: 核心算法与因子

重点核查:

- 因子组合计算。
- 正交化和共线性处理。
- FSM/Wyckoff/LPPL 等引擎是否可能长期输出默认状态。
- 引擎失败时是否被误解释为低风险或低信号。

主要结论:

- 因子计算失败和正交化失败以前只记录日志，调用方无法结构化判断 composite 是否降级。
- 部分引擎失败 fallback 会输出 `Safe`、`unknown`、`0.0` 等默认结果，上层可能误判为有效分析。
- FSM 最终决策没有稳定进入统一标准信号收集，存在信号断链。

### 4.3 队列 C: 撮合与风控

重点核查:

- 连续涨跌停、停牌、资金透支等极端路径。
- 旧回测入口是否遵守统一撮合规则。
- 成本、T+1、现金扣减、止损保护。

主要结论:

- 旧回测入口和统一撮合入口存在行为漂移风险。
- 被动风控防线需要在流水线层提供 fail-closed 保护，不能只依赖策略主动止损。
- 统一撮合路径已经是更可信的规则承载点，应让旧入口复用统一撮合结果。

### 4.4 队列 D: 异常处理与可复现性

重点核查:

- `@handle_errors`、`try/except`、`pass`、`continue`。
- 未注入 seed 的 `np.random.*` 和 `random.*`。
- 网络/mock 随机与研究随机是否混淆。

主要结论:

- 风险和分析失败不能继续输出“看起来可用”的 BUY/低风险默认结果。
- 宏观无真实收益数据时不能生成未注入 seed 的随机收益 fallback。
- Monte Carlo/Bootstrap 默认路径必须可复现。
- 网络退避、User-Agent 轮换、mock tick 这类非研究随机需要边界标注，而不是强行 seed 化。

## 5. 阶段 3: Master Remediation Plan 聚合

`MASTER_REMEDIATION_PLAN.md` 将问题分为:

### 5.1 P0 致命级

- 数据对齐前视偏差。
- 分析服务依赖契约断裂。
- FSM 决策未进入统一信号收集。
- 风险引擎异常被默认结果掩盖。
- 宏观无数据时随机收益 fallback。
- 因子配置失败不可观测。

### 5.2 P1 架构级

- 多层缓存无统一失效广播。
- 新旧回测/撮合体系并行。
- 数据入口多轨导致状态不共享。
- God Objects 阻碍可测试性。
- 因子合成降级不透明。
- Monte Carlo/Bootstrap 默认不可复现。
- 兼容 DI 容器反向依赖。

### 5.3 P2 工程级

- 日志追踪缺乏统一 TraceID。
- UI 层越过 services 直接调用 risk。
- 文档/历史审计过多且状态不一致。
- 网络退避和模拟数据随机未统一标注。
- 全仓 ruff 历史债。

## 6. 阶段 4 和后续修复明细

### 6.1 数据流、异常、随机种子

主要修改:

- 修复数据对齐前视偏差边界，区分目标生成和特征对齐。
- 宏观真实收益为空时不再生成随机替代收益，默认 fail-closed。
- mock 宏观路径保留显式 `mock` 和 `seed` 参数。
- 分析或风险失败时避免被默认为安全状态。
- Monte Carlo/Bootstrap 引入默认可复现 seed/RNG 机制。

代表性文件:

- `src/uniquant/data/pipeline/data_aligner.py`
- `src/uniquant/services/analysis/macro_analysis_engine.py`
- `src/uniquant/services/analysis/macro_service.py`
- `src/uniquant/hands/backtest/monte_carlo.py`
- `src/uniquant/hands/strategies/backtest.py`

新增/扩展测试:

- `tests/test_phase4_1_remediation.py`
- `tests/test_p1_reproducibility.py`

### 6.2 接口契约和标准信号转换

主要修改:

- 修复分析引擎工厂依赖契约。
- 统一字典式分析结果到强类型 `TradingSignal` 的转换路径。
- FSM 最终决策进入 `TradingSignalCollector`。
- Wyckoff、LPPL、FSM 等 adapter 输出状态更明确。

代表性文件:

- `src/uniquant/services/analysis/engine_factory.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/signal/__init__.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/research_pipeline.py`

新增/扩展测试:

- `tests/test_phase4_2_contracts.py`
- `tests/test_macro_and_scan_regressions.py`
- `tests/test_analysis_engines.py`

### 6.3 被动风控防线

主要修改:

- 在流水线和服务边界加入被动风险保护。
- 风险分析失败时 fail-closed，而不是继续输出 BUY。
- 组合分析服务增加可复用 risk 边界能力。
- 成本模型和结构风险路径做安全性修正。

代表性文件:

- `src/uniquant/services/portfolio_service.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/risk/structural.py`
- `src/uniquant/shared/cost_model.py`
- `src/uniquant/ui/manager_logic.py`

新增/扩展测试:

- `tests/test_phase4_3_risk_guardrails.py`
- `tests/test_manager_portfolio_analytics_service.py`

### 6.4 缓存失效广播

主要修改:

- 数据服务、fetcher、数据湖之间增加统一失效传播。
- 缓存清理不再只清理单层对象。
- DI 容器缓存关系增加可测试约束。

代表性文件:

- `src/uniquant/data/data_fetcher.py`
- `src/uniquant/data/data_pipeline_service.py`
- `src/uniquant/data/lake/storage_manager.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/shared/di_container.py`

新增/扩展测试:

- `tests/test_p1_cache_invalidation.py`
- `tests/test_di_container_and_cache.py`

### 6.5 新旧回测入口兼容

主要修改:

- 旧 `BacktestEngine` 复用统一撮合规则，降低 A 股约束漂移风险。
- 旧入口覆盖涨跌停、T+1、成本、成交现金扣减等关键行为。
- 避免新旧回测体系在关键执行规则上给出不一致结果。

代表性文件:

- `src/uniquant/hands/backtest/engine.py`
- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`

新增/扩展测试:

- `tests/test_p1_backtest_compat.py`
- `tests/test_backtest_engine.py`
- `tests/test_unified_matching.py`

### 6.6 数据入口依赖注入

主要修改:

- `analysis_service_legacy.py` 内部不再直接创建新的 `DataFetcher()` 或 `StorageManager()`。
- 旧服务改用注入的 `DataService.fetcher` 和 `DataService.lake`。
- 注入对象缺失时显式抛错，避免创建第二套隐藏状态。

代表性文件:

- `src/uniquant/services/analysis_service_legacy.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/data/services/__init__.py`

新增/扩展测试:

- `tests/test_p1_data_entry_injection.py`

### 6.7 God Object containment

主要修改:

- 本轮不拆分大文件。
- 通过入口收敛、adapter、typed result、依赖注入和测试保护降低风险。
- 为后续拆分建立保护网。

保留未拆分对象:

- `src/uniquant/services/analysis_service_legacy.py`
- `src/uniquant/ui/dashboard.py`
- `src/uniquant/data/sources/eastmoney.py`
- `src/uniquant/brain/wyckoff/engine.py`
- `src/uniquant/brain/lppl/engine.py`
- `src/uniquant/brain/fsm/fsm.py`

### 6.8 因子 diagnostics

主要修改:

- `FactorComposer` 增加 `last_diagnostics`。
- 新增 `get_last_diagnostics()`。
- `compute_all_factors(..., return_diagnostics=True)` 可返回 `(factor_df, diagnostics)`。
- `compose_scores(..., return_diagnostics=True)` 可返回 `(result_df, diagnostics)`。
- `process(..., return_diagnostics=True)` 可返回 `(result_df, weights, diagnostics)`。
- 默认返回值保持兼容。

diagnostics 包含:

- `requested_factors`
- `computed_factors`
- `used_factors`
- `missing_requested_factors`
- `failed_factors`
- `orthogonalization_attempted`
- `orthogonalization_failed`
- `orthogonalization_error`
- `composite_status`
- `composite_usable`

代表性文件:

- `src/uniquant/brain/factors/composer.py`
- `src/uniquant/brain/factors/registry.py`

新增/扩展测试:

- `tests/test_factor_composer.py`
- `tests/test_factor_registry.py`

当前剩余边界:

- diagnostics 已在 composer 层可取。
- scan/report 层尚未把 diagnostics 写入最终研究报告。

### 6.9 TraceID 传播

主要修改:

- 服务和 UI 管理路径增加 TraceID 传播能力。
- 降低跨服务分析、报告和 UI 调用时定位问题的成本。

代表性文件:

- `src/uniquant/shared/logger_factory.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/ui/manager_logic.py`

### 6.10 UI-risk 边界收敛

主要修改:

- UI manager 不再直接绕过服务层调用 risk 细节。
- 新增/调整组合分析服务作为边界。

代表性文件:

- `src/uniquant/services/portfolio_service.py`
- `src/uniquant/ui/manager_portfolio_analytics_service.py`
- `src/uniquant/ui/manager_logic.py`

新增/扩展测试:

- `tests/test_manager_portfolio_analytics_service.py`

### 6.11 文档状态源边界

主要修改:

- `docs/index.md`、`docs/STATUS.md` 标注早期迁移文档是历史快照。
- 明确当前事实源优先级: 根目录 `AGENTS.md`、`MASTER_REMEDIATION_PLAN.md`、`docs/reshaping_logs/README.md`。
- 避免后续维护误信旧文档中“data/signal 缺失”等过时结论。

代表性文件:

- `docs/index.md`
- `docs/STATUS.md`
- `docs/reshaping_logs/README.md`

### 6.12 网络/mock 随机标注

主要修改:

- 引入统一源码标记 `NON_RESEARCH_RANDOMNESS`。
- 对网络退避、User-Agent 轮换、数据源限速、mock tick 等非研究随机加边界注释。
- 不改变这些随机行为，不强制 seed 化。

代表性文件:

- `src/uniquant/shared/error_handling.py`
- `src/uniquant/data/utils/request_utils.py`
- `src/uniquant/data/utils/akshare_wrapper.py`
- `src/uniquant/data/utils/js_executor.py`
- `src/uniquant/data/sources/eastmoney.py`
- `src/uniquant/data/sources/sina.py`
- `src/uniquant/data/sources/tencent.py`
- `src/uniquant/data/sources/realtime_bridge.py`
- `src/uniquant/data/scripts/update_daily_data_akshare.py`
- `src/uniquant/data/scripts/update_daily_incremental.py`

新增测试:

- `tests/test_p2_randomness_annotations.py`

### 6.13 全仓 lint 历史债清理

主要修改:

- 执行安全自动修复: `python3 -m ruff check src/uniquant tests --fix`。
- 未使用 `ruff --unsafe-fixes`。
- 手工修复剩余 lint 项，包括未使用 import、未使用局部变量、模块级 import 顺序、单行多语句、无占位 f-string、重复测试函数名、布尔比较写法。
- `tests/chaos/test_data_chaos.py` 保留路径注入语义，仅对相关 import 加 `# noqa: E402`。
- `tests/test_cvar_empty_tail.py` 的重复测试函数名改为唯一名称，两个原本被覆盖的测试开始实际执行。

验证结果:

- `python3 -m ruff check src/uniquant tests` 通过。
- 测试总通过数从 1024 增至 1026。

## 7. 关键新增测试文件

| 测试文件 | 覆盖目标 |
|----------|----------|
| `tests/test_phase4_1_remediation.py` | 数据流、异常、宏观随机 fallback、基础 fail-closed |
| `tests/test_phase4_2_contracts.py` | 接口契约、标准信号转换、FSM 信号接入 |
| `tests/test_phase4_3_risk_guardrails.py` | 被动风控防线 |
| `tests/test_p1_cache_invalidation.py` | 缓存失效广播 |
| `tests/test_p1_backtest_compat.py` | 旧回测入口兼容统一撮合规则 |
| `tests/test_p1_data_entry_injection.py` | 数据入口注入与 legacy containment |
| `tests/test_p1_reproducibility.py` | Monte Carlo/Bootstrap 可复现 |
| `tests/test_p2_randomness_annotations.py` | 网络/mock 随机边界标注 |
| `tests/test_di_container_and_cache.py` | DI 容器与缓存关系 |
| `tests/test_manager_portfolio_analytics_service.py` | UI-risk 服务边界 |

## 8. 最终验证

提交前最终门禁:

```bash
python3 -m ruff check src/uniquant tests
git diff --check
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
python3 -m pytest tests/ -q
```

结果:

- `python3 -m ruff check src/uniquant tests` -> All checks passed。
- `git diff --check` -> 通过。
- 8 层导入 -> `imports OK`。
- `python3 -m pytest tests/ -q` -> `1026 passed, 7 skipped, 12 warnings`。

提交后状态:

- 最新提交: `91c2b06 remediate architecture risks and clear lint debt`。
- 提交后曾确认 `git status --short` 输出为空。

## 9. 提交影响概览

提交 `91c2b06` 统计:

- 125 个文件变更。
- 5560 行新增。
- 446 行删除。
- 新增完整阶段日志、P0/P1/P2 测试、P2 随机标注测试。

主要变更类别:

- 文档和状态日志: `docs/`, `docs/reshaping_logs/`, `MASTER_REMEDIATION_PLAN.md`。
- 实验/审计脚本: `experiments/2026-06-08_lookahead_ab/run_lookahead_ab.py`。
- 因子和算法: `src/uniquant/brain/**`。
- 数据层和数据源: `src/uniquant/data/**`。
- 回测和撮合: `src/uniquant/hands/**`。
- 风险和成本: `src/uniquant/risk/**`, `src/uniquant/shared/cost_model.py`。
- 服务层和 DI: `src/uniquant/services/**`, `src/uniquant/shared/di_container.py`。
- 信号层: `src/uniquant/signal/**`。
- UI manager: `src/uniquant/ui/**`。
- 测试: `tests/**`。

## 10. 剩余未完成项确认

用户追加要求确认的“未完成项”结论如下:

| 项目 | 判断 | 说明 |
|------|------|------|
| `analysis_service_legacy.py` 拆分解耦 | 属实 | 仍是约 1648 行旧 God Object；本轮只做 entry containment |
| `ui/dashboard.py` 拆分 | 属实 | 仍是 1526 行 UI God Object；本轮只做 risk 调用收敛 |
| `eastmoney.py` / Wyckoff / LPPL / FSM God Object 拆分 | 属实 | 大对象仍存在；策略是先用 adapter/typed result/DI 降风险再拆 |
| 因子 diagnostics 写入研究报告 | 属实 | diagnostics 已在 composer 层实现，scan/report 层尚未消费 |
| 非 lint 风险: 数据源退避随机、mock tick 随机 | 表述需修正 | P2-4 已用 `NON_RESEARCH_RANDOMNESS` 标注并测试闭环，只是保留原行为、未强制 seed |

准确的后续迭代表述:

> 剩余未完成项主要是大对象结构拆分和 diagnostics 向最终报告链路透传。网络/mock 随机不是未闭环风险，而是已标注为非研究随机并保留原行为。

## 11. 建议后续迭代顺序

### 11.1 优先级 1: diagnostics 进入最终报告

原因:

- 改动边界较小。
- 已有 `FactorComposer` diagnostics 和测试保护。
- 可提升研究结果可审计性。

建议动作:

- 在 scan/research pipeline 层消费 `return_diagnostics=True`。
- 将 `composite_status`、失败因子、正交化状态写入报告元数据。
- 增加报告层回归测试。

### 11.2 优先级 2: `analysis_service_legacy.py` 分阶段剥离

原因:

- 当前仍是最大服务层历史债。
- 但已有数据入口 containment 和 v2/service analysis 层作为承接基础。

建议动作:

- 先抽报告保存、缓存、数据优化、engine 调用四类纯 helper。
- 每抽一类先补测试，再迁移调用。
- 保留 legacy 外部 API，内部逐步委托到 v2 或 services/analysis。

### 11.3 优先级 3: `ui/dashboard.py` 拆分

原因:

- UI God Object 仍影响可维护性。
- 但拆分风险主要是界面回归，不应和算法修复混在一个提交。

建议动作:

- 按页面/组件/数据加载/动作 handler 分离。
- 先保护 manager/service 边界测试，再拆 Streamlit 页面。

### 11.4 优先级 4: EastMoney/Wyckoff/LPPL/FSM 拆分

原因:

- 这些是算法和数据源核心路径。
- 拆分必须以行为保持为第一原则。

建议动作:

- EastMoney 按 request、parse、field mapping、retry/backoff 分层。
- Wyckoff 按 phase classifier、volume analyzer、signal combiner 分层。
- LPPL 按 window generation、fit, risk classification、result formatting 分层。
- FSM 按 state transition、decision policy、execution constraints 分层。

## 12. 当前事实基线

截至本报告:

- P0/P1/P2 当前计划内风险均已完成修复或边界收敛。
- 全仓 lint 已通过。
- 全量测试已通过。
- 已提交: `91c2b06 remediate architecture risks and clear lint debt`。
- 仍未完成的是后续架构拆分和报告链路增强，不是当前提交的阻塞项。

