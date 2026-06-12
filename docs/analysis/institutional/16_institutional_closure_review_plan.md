# 机构审计复审工作计划

生成日期：2026-06-12  
适用范围：UniQuant 研究平台机构审计关闭复核  
前置基线：`docs/analysis/institutional/99_final_institutional_audit_report.md`、`FINDINGS_INDEX.md`、`IMPLEMENTATION_PLAN_TASK_CARDS.md`、`docs/GAP_REMEDIATION_PLAN.md`

---

## 1. 复审结论预设

本次工作不是重新执行 WS1-WS15 的全量机构审计，而是执行一次 **关闭审计 / 状态复核**。

原因：

- 原机构审计已经形成完整证据链、P0/P1 分级、目标架构、实施路线图和验证标准。
- 审计产物生成于 2026-06-10，之后源码与控制文档显示 Phase 0-3、Phase 5 以及部分 Phase 6 工作已经推进。
- 当前风险不在于缺少审计，而在于原发现状态仍停留在 `Design complete, implementation pending`，需要按当前源码重新判定 `Closed`、`Partially closed`、`Open` 或 `Deferred live`。

---

## 2. 复审目标

### 2.1 主目标

建立一份当前可信的机构审计状态边界，回答以下问题：

1. 原 5 个 P0 发现哪些已经被代码、测试和基线验证关闭。
2. 原 8 个 P1 发现哪些已经关闭、部分关闭或仍未开始。
3. Phase 0-5 实施是否确实满足原审计定义的关闭证据。
4. `docs/GAP_REMEDIATION_PLAN.md` 中 G-1 到 G-4 是否准确代表剩余高优先级缺口。
5. 是否存在由实施引入的新风险、新漂移或文档状态冲突。

### 2.2 非目标

本次复审不做以下事项：

- 不重跑 WS1-WS15 的完整人工审计。
- 不扩大到实盘交易、Broker、OMS、订单状态机、账户对账、高可用或灾备实施范围。
- 不把历史 finding ID 重新编号。
- 不把所有 `Dict[str, Any]` 或所有时钟调用都作为本次复审的实现任务。
- 不在复审阶段修改业务逻辑，除非另开明确实现任务。

---

## 3. 范围边界

### 3.1 当前范围

| 范围 | 说明 |
|---|---|
| 研究平台可信度 | 数据、信号、回测、因子、风险、配置、事件、可观测性 |
| P0/P1 关闭证据 | 以 `FINDINGS_INDEX.md` 为主控索引 |
| Phase 0-5 实施对照 | 以任务卡、源码、测试、baseline、配置为证据 |
| Phase 6 缺口复核 | 以 `docs/GAP_REMEDIATION_PLAN.md` 为起点 |
| 文档状态一致性 | AGENTS、docs/index、institutional 目录之间的状态同步 |

### 3.2 延后范围

| 范围 | 处理方式 |
|---|---|
| Broker/OMS/live execution | 保持 `Deferred live` |
| 生产高可用、灾备、实盘事故恢复 | 保持 `Deferred live` |
| 全量性能优化 | 只验证是否有明确剩余任务，不做实现 |
| 全库类型清理 | 只统计趋势和高风险调用点 |

---

## 4. 复审输入

### 4.1 控制文档

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | 当前项目控制状态、Phase 完成声明、工作规则 |
| `docs/index.md` | 当前文档状态边界 |
| `docs/GAP_REMEDIATION_PLAN.md` | Phase 6 遗留缺口来源 |
| `docs/analysis/institutional/index.md` | 原机构审计入口 |
| `docs/analysis/institutional/FINDINGS_INDEX.md` | P0/P1 状态主控索引 |
| `docs/analysis/institutional/IMPLEMENTATION_ENTRY_CRITERIA.md` | 关闭标准和验证门槛 |
| `docs/analysis/institutional/IMPLEMENTATION_PLAN_TASK_CARDS.md` | Phase 0-5 任务映射 |
| `docs/analysis/institutional/EXECUTION_PLAN_RECOMMENDATION.md` | 后续执行顺序与风险控制 |
| `docs/analysis/institutional/99_final_institutional_audit_report.md` | 原最终审计结论 |

### 4.2 源码重点文件

| 领域 | 文件 |
|---|---|
| Typed contracts | `src/uniquant/shared/interfaces.py` |
| TimeProvider | `src/uniquant/shared/time_provider.py` |
| Config flags | `src/uniquant/shared/config_models.py`, `config/config.yaml` |
| Service wiring | `src/uniquant/services/service_container.py`, `src/uniquant/services/research_pipeline.py` |
| Signal arbitration | `src/uniquant/signal/arbitrator.py`, `src/uniquant/signal/adapters.py` |
| Factor governance | `src/uniquant/shared/factor_governance.py`, `src/uniquant/brain/factors/registry.py` |
| Backtest behavior | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/hands/backtest/unified_matching_engine.py` |
| EventBus | `src/uniquant/shared/event_bus.py` |
| Health/observability | `src/uniquant/services/health_service.py`, `src/uniquant/shared/observability.py` |

### 4.3 测试与基线重点

| 领域 | 测试或产物 |
|---|---|
| Signal arbitration | `tests/signal/test_arbitrator.py` |
| TimeProvider | `tests/shared/test_time_provider.py` |
| Contracts | `tests/shared/test_*` 中与 interfaces/config/event/factor 相关测试 |
| EventBus | `tests/shared/test_event_bus.py`, `tests/shared/test_async_event_bus.py` |
| Backtest/lookahead | `tests/test_lookahead_bias.py`, `tests/integration/test_backtest_regression.py` |
| Baseline | `scripts/capture_baseline.py`, `scripts/compare_baseline.py`, `tests/benchmark/` |

---

## 5. 状态分类规则

每个 P0/P1 发现只能使用以下状态之一：

| 状态 | 定义 |
|---|---|
| `Closed` | 代码或明确 no-change 决策已落地，测试/静态检查/基线已验证，存在回滚或兼容路径 |
| `Partially closed` | 核心机制已存在，但覆盖范围、集成、验证或文档状态仍不完整 |
| `Open` | 仍停留在设计或待实现状态 |
| `Deferred live` | 只适用于实盘交易范围，当前研究平台不要求关闭 |
| `Superseded` | 原发现被后续架构决策替代，且替代决策有证据和风险说明 |

关闭一个发现必须满足：

1. 有对应源码、配置、文档或明确 no-change 证据。
2. 有至少一个验证命令或测试文件。
3. 验证是在当前工作树运行或有明确历史记录。
4. 影响范围和剩余风险已记录。
5. 若改变行为，有 feature flag、兼容路径或回滚说明。

---

## 6. 工作流总览

| 阶段 | 名称 | 目标 | 预计耗时 | 产物 |
|---|---|---|---:|---|
| R0 | 复审准备 | 冻结当前证据边界 | 0.5 天 | 工作树状态、文件清单、命令记录 |
| R1 | P0 关闭复核 | 对 5 个 P0 逐项判定 | 0.5-1 天 | P0 关闭矩阵 |
| R2 | P1 关闭复核 | 对 8 个 P1 逐项判定 | 0.5-1 天 | P1 关闭矩阵 |
| R3 | Phase 6 缺口复核 | 判断 G-1 到 G-4 是否准确、完整、优先级合理 | 0.5 天 | 遗留缺口确认表 |
| R4 | 验证执行 | 跑最小必要测试、统计和 smoke | 0.5-1 天 | 验证日志和失败说明 |
| R5 | 文档收敛 | 更新状态索引和复审报告 | 0.5 天 | 复审报告、索引更新建议 |

---

## 7. R0 - 复审准备

### 7.1 任务

1. 记录当前日期、分支、HEAD、工作树状态。
2. 记录 institutional 目录产物清单。
3. 读取当前控制文档，确认范围仍为研究平台。
4. 建立复审输出文件。

### 7.2 命令

```bash
git status --short
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
rg --files docs/analysis/institutional
sed -n '1,220p' AGENTS.md
sed -n '1,220p' docs/index.md
sed -n '1,260p' docs/GAP_REMEDIATION_PLAN.md
```

### 7.3 退出标准

- 当前工作树状态已记录。
- 若工作树不干净，明确哪些文件属于本次复审，哪些不能触碰。
- 复审报告草稿文件已创建。

---

## 8. R1 - P0 关闭复核

### 8.1 P0 复核矩阵

| ID | 原发现 | 复核问题 | 主要证据 | 最低验证 |
|---|---|---|---|---|
| P0-1 | `data_pack: Dict[str, Any]` 跨层隐式键 | `ResearchDataPack` 是否存在、是否接入关键路径、旧 dict 路径是否受控 | `interfaces.py`, `data_service.py`, `research_pipeline.py`, tests | `rg "ResearchDataPack" src/uniquant tests`; 相关 shared/integration tests |
| P0-2 | 实时时钟破坏历史可复现 | `TimeProvider` 是否定义、注入、覆盖核心研究路径；剩余 `now()` 是否已分类 | `time_provider.py`, `service_container.py`, `research_pipeline.py`, GAP G-1 | `rg "pd\\.Timestamp\\.now\\(|datetime\\.now\\(|time\\.time\\(" src/uniquant` |
| P0-3 | 回测完整性依赖手工偏差控制 | SELL 优先、metadata、baseline、lookahead/survivorship 控制是否有测试 | `unified_engine.py`, baseline scripts, backtest tests | `pytest tests/test_lookahead_bias.py -q`; baseline compare |
| P0-4 | 无确定性信号仲裁 | `SignalArbitrator` 是否存在、测试是否覆盖 sell priority/confidence/risk veto、pipeline 是否接入 | `signal/arbitrator.py`, `research_pipeline.py`, tests | `pytest tests/signal/test_arbitrator.py -q` |
| P0-5 | 因子准入缺失 | `FactorAdmissionGate` 是否存在，实际 `FactorRegistry` 是否接入准入，是否仍有双 registry 风险 | `factor_governance.py`, `brain/factors/registry.py`, GAP G-2 | `pytest tests/shared/test_factor_admission_gate.py tests/test_factor_registry.py -q` |

### 8.2 判定要求

每个 P0 必须形成一段结论：

```text
Status:
Evidence:
Verification:
Residual risk:
Next action:
```

### 8.3 P0 优先级建议

若验证资源有限，优先顺序为：

1. P0-4 信号仲裁。
2. P0-3 回测完整性。
3. P0-2 时间可复现性。
4. P0-5 因子准入。
5. P0-1 data_pack 类型化。

---

## 9. R2 - P1 关闭复核

### 9.1 P1 复核矩阵

| ID | 原发现 | 复核问题 | 主要证据 | 最低验证 |
|---|---|---|---|---|
| P1-1 | Wyckoff CPU 瓶颈 | 是否已有性能优化、缓存或边界控制；是否有基准 | `brain/wyckoff/`, perf tests | 统计热点文件、跑局部测试或记录未验证 |
| P1-2 | `ScanService` 单线程/无扩展 | 是否有并发、分批、checkpoint 或显式延后 | `scan_service.py`, scripts | 代码审阅 + 运行轻量 scan smoke |
| P1-3 | 旧 PortfolioEngine/未类型交易记录 | 是否仍被服务层使用；是否有 canonical trade record | `portfolio_service.py`, `hands/backtest/portfolio_engine.py` | `rg "PortfolioEngine|List\\[Dict\\[str, Any\\]\\]" src/uniquant` |
| P1-4 | A-share 规则治理不足 | limit/suspension/lot/price collar 是否有集中测试 | `limit_checker.py`, `market_rules.py`, matching engines | 相关 A-share tests |
| P1-5 | 长任务无 checkpoint/restart | baseline/scan 是否有中间产物或恢复机制 | scripts, services | 检查 checkpoint 代码和测试 |
| P1-6 | `MarketSignalContext` orphaned | 是否已传入 `DecisionBrain`，旧 raw dict 是否受控 | `interfaces.py`, `analysis_service_v2.py`, `fsm.py` | `rg "MarketSignalContext" src/uniquant tests` |
| P1-7 | retry/error handling 重叠 | 是否统一错误分类或仍保留双实现 | `retry_decorator.py`, `error_handling.py` | 代码审阅 + error tests |
| P1-8 | config/secrets 边界弱 | 静态 token 是否移除，env overlay 是否测试 | `config/config.yaml`, config loader/models | secret grep + config tests |

### 9.2 判定规则

- 对用户研究结果可信度有直接影响的 P1，不能只标记为 `Open`，必须给出下一步任务。
- 对工程成熟度类 P1，可标记为 `Partially closed`，但必须说明未关闭部分不会阻塞当前研究平台。

---

## 10. R3 - Phase 6 缺口复核

### 10.1 复核对象

| Gap | 当前说法 | 复核问题 | 期望输出 |
|---|---|---|---|
| G-1 | TimeProvider 只部署部分路径，仍有约 120 处直接时钟调用 | 统计是否准确；哪些调用是研究可复现风险，哪些是缓存/限流/性能计时 | 分层剩余清单 + 优先级 |
| G-2 | 两个 `FactorRegistry`，治理版死代码/弱接入 | 是否已反向合并；shared 版本是否应继续保留为兼容层 | 统一方案确认 |
| G-3 | Phase 0 交付物存在但未提交 | 当前 git 状态是否仍成立；baseline 文件是否应进入仓库 | 提交/不提交决策 |
| G-4 | EventBus sync-only | 是否已有 `AsyncEventBus`；测试和接入状态如何 | 关闭或补接入任务 |

### 10.2 命令

```bash
rg --stats "pd\\.Timestamp\\.now\\(|datetime\\.now\\(|datetime\\.datetime\\.now\\(|date\\.today\\(|time\\.time\\(" src/uniquant
rg --stats "class FactorRegistry|global_factor_registry|factor_governance|check_access" src/uniquant tests
rg --stats "AsyncEventBus|ThreadPoolExecutor|class EventBus|def publish" src/uniquant/shared/event_bus.py tests
git status --short
git ls-files tests/benchmark scripts/capture_baseline.py scripts/compare_baseline.py
```

### 10.3 输出要求

形成 `Phase 6 Gap Review` 表格：

```text
Gap:
Status:
Evidence:
Correction to GAP_REMEDIATION_PLAN:
Next action:
```

---

## 11. R4 - 验证执行计划

### 11.1 最小验证集

先执行低成本、高信号命令：

```bash
pytest tests/signal/test_arbitrator.py -q
pytest tests/shared/test_time_provider.py -q
pytest tests/shared/test_factor_manifest.py tests/shared/test_factor_admission_gate.py -q
pytest tests/shared/test_event_bus.py tests/shared/test_async_event_bus.py -q
pytest tests/test_lookahead_bias.py -q
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

### 11.2 扩展验证集

若最小验证集通过，再执行：

```bash
pytest tests/shared/ -q
pytest tests/integration/ -q
python3 scripts/compare_baseline.py
pytest tests/ -q
```

### 11.3 统计检查

```bash
rg --stats "Dict\\[str, Any\\]|dict\\[str, Any\\]" src/uniquant
rg --stats "pd\\.Timestamp\\.now\\(|datetime\\.now\\(|datetime\\.datetime\\.now\\(|date\\.today\\(|time\\.time\\(" src/uniquant
rg --stats "TODO|FIXME|INSUFFICIENT EVIDENCE" docs/analysis/institutional src/uniquant
```

### 11.4 失败处理

如果验证失败：

1. 记录失败命令、失败摘要、相关文件。
2. 判断是当前复审阻断、已知遗留缺口，还是环境/数据依赖。
3. 不在复审文档中声称该项关闭。
4. 若失败影响 P0 关闭结论，将状态降为 `Partially closed` 或 `Open`。

---

## 12. R5 - 文档收敛计划

### 12.1 新增复审报告

建议新增：

`docs/analysis/institutional/17_institutional_closure_review_report.md`

报告结构：

```markdown
# 机构审计关闭复审报告

生成日期：
源码基线：
验证摘要：

## Executive Summary
## P0 Closure Matrix
## P1 Closure Matrix
## Phase 6 Gap Review
## Verification Log
## New Risks Introduced Since Original Audit
## Documentation Drift
## Recommended Next Implementation Slice
## Appendix: Command Outputs
```

### 12.2 更新现有索引

在完成复审报告后更新：

| 文件 | 更新内容 |
|---|---|
| `docs/analysis/institutional/index.md` | 添加复审计划和复审报告入口 |
| `docs/analysis/institutional/FINDINGS_INDEX.md` | 只更新 P0/P1 状态，不改历史 finding ID |
| `docs/GAP_REMEDIATION_PLAN.md` | 若复审证明 G-1 到 G-4 状态变化，更新状态 |
| `docs/index.md` | 如复审成为新的状态边界，添加链接 |

### 12.3 不建议更新

除非证据或建议发生实质变化，否则不要修改：

- `99_final_institutional_audit_report.md`
- WS1-WS15 原始工作流文档
- `IMPLEMENTATION_PLAN_TASK_CARDS.md`

这些文件应保留为历史审计和计划证据。

---

## 13. 输出物清单

| 输出物 | 必需 | 文件 |
|---|---|---|
| 复审工作计划 | 是 | `16_institutional_closure_review_plan.md` |
| 复审报告 | 是 | `17_institutional_closure_review_report.md` |
| 命令验证记录 | 是 | 可放入复审报告附录 |
| P0/P1 状态更新 | 是 | `FINDINGS_INDEX.md` |
| Phase 6 缺口状态修正 | 条件性 | `docs/GAP_REMEDIATION_PLAN.md` |
| 总文档索引更新 | 条件性 | `docs/index.md` |

---

## 14. 复审通过标准

本次复审完成的最低标准：

1. 5 个 P0 均有当前状态、证据、验证和剩余风险。
2. 8 个 P1 均有当前状态、证据、验证或明确未验证说明。
3. G-1 到 G-4 均完成状态复核。
4. 至少最小验证集已运行，失败项有解释。
5. 文档状态不再互相冲突：原审计、实施状态、Phase 6 缺口之间有清晰边界。
6. 输出下一步可执行任务清单，按研究可信度风险排序。

---

## 15. 建议排期

| 日期 | 工作 |
|---|---|
| Day 1 上午 | R0 准备、证据冻结、P0 源码阅读 |
| Day 1 下午 | R1 P0 关闭复核、运行 P0 最小验证 |
| Day 2 上午 | R2 P1 关闭复核、R3 Phase 6 缺口复核 |
| Day 2 下午 | R4 扩展验证、R5 输出复审报告和索引更新 |

若全量测试或 baseline 比对耗时较长，可将 R4 扩展验证拆到 Day 3。

---

## 16. 风险与控制

| 风险 | 控制 |
|---|---|
| 原审计状态和当前源码状态不一致 | 以当前源码和可运行测试为准，历史文档作为追溯 |
| 复审演变成大规模实现任务 | 只记录任务，不在复审中改业务逻辑 |
| 测试依赖本地数据或网络导致失败 | 标记为环境/数据依赖，不声称通过 |
| P0 状态被过早关闭 | 必须同时具备代码证据和验证证据 |
| 文档被反复改写失去历史价值 | 原 WS 文档保持不可变，新增复审报告作为新边界 |

---

## 17. 推荐下一步

按本计划执行复审后，优先产出 `17_institutional_closure_review_report.md`。若复审确认当前剩余高风险集中在 Phase 6，则下一轮实现顺序建议为：

1. G-2 FactorRegistry 统一与实际准入接入。
2. G-1 TimeProvider 按层适配，优先 services/data/brain 中影响历史可复现的调用。
3. G-4 AsyncEventBus 接入或关闭说明。
4. G-3 Phase 0 交付物提交策略确认。
