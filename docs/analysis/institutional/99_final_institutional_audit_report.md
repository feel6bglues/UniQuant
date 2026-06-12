# UniQuant 机构化审计最终报告

生成日期：2026-06-10  
基线：Sprints 0–4，15 个工作流全部完成

---

## 1. 审计范围

本报告覆盖 UniQuant 量化研究平台的全部 8 层（shared → data → brain → signal → risk → hands → services → ui），审计过程未对源码做实现性修改（当前工作树存在审计之前的未提交修改）。

**研究平台范围（当前）**：所有 15 个工作流均已完成审计。  
**生产交易范围（已推迟）**：已记录蓝图和差距，未实施。

---

## 2. 关键发现汇总

### P0 关键问题（5 项）

| ID | 发现 | 影响范围 | 解决阶段 | 严重程度 |
|---|---|---|---|---|
| P0-1 | `data_pack: Dict[str, Any]` 跨越 4 层，30+ 隐式键 | data → brain → signal → hands | 第 2 阶段 → `ResearchDataPack` | **每个数据包都可能存在静默损坏风险** |
| P0-2 | `pd.Timestamp.now()` 在批量扫描中注入实时时间戳。严格匹配 42 处，扩大到 `Timestamp.now()` / `datetime.now()` 共 126 处 | brain， services， signal | 第 3 阶段 → 冻结时间戳工具 | **历史信号时间戳无法复现** |
| P0-3 | 回测偏差控制通过 16 项检查，但确认偏差和选择偏差仍为手动 | hands/backtest | 第 2 阶段 → 引擎重构 | **研究可信度风险** |
| P0-4 | 无信号仲裁；8 个适配器中的第一个非 HOLD 获胜 | signal/adapters.py | 第 3 阶段 → `SignalArbitrator` | **回测结果取决于引擎加载顺序** |
| P0-5 | 因子注册无准入条件（无 IC、OOS、PBO 检查） | brain/alpha/， brain/indicators/ | 第 3 阶段 → `FactorAdmissionGate` | **无效因子可能进入生产流程（在研究中已是活跃问题）** |

### P1 关键问题（8 项）

| ID | 发现 | 工作量评估 | 阶段 |
|---|---|---|---|
| P1-1 | Wyckoff 分析器：1457 行代码，嵌套循环，跨度为 5000 个周期 → 表现为 CPU 瓶颈 | 3 天 | 第 2 阶段 |
| P1-2 | `ScanService` 是单线程的，逐个周期执行，跨度为 5000 个周期 → 执行时间为 2 小时 | 1 天 | 第 2 阶段 |
| P1-3 | `PortfolioEngine` 已弃用，但 `PortfolioService` 仍在使用；交易记录是 `List[Dict[str,Any]]` | 2 天 | 第 3 阶段 |
| P1-4 | `LimitChecker` 是一个函数，不是一个可测试的类；北交所规则硬编码 | 1 天 | 第 2 阶段 |
| P1-5 | 无批量处理检查点；周期 3000 后的崩溃会丢失整个 5000 个周期的扫描 | 1 天 | 第 2 阶段 |
| P1-6 | `MarketSignalContext` 已定义类型但未使用；`make_decision()` 接受任意字典 | 1 天 | 第 3 阶段 |
| P1-7 | `shared/retry_decorator.py` 和 `shared/error_handling.py` 实现重叠 | 1 天 | 第 5 阶段 |
| P1-8 | `config/config.yaml` 包含静态 Token（无密钥注入） | 0.5 天 | 第 5 阶段 |

---

## 3. 按层级统计的发现

| 层级 | 文件数 | 代码行数 | 发现数 | 关键发现 |
|---|---|---|---|---|
| shared | 37 | ~5,800 | 12 | 跨层级合约，配置，重试 |
| data | 65 | ~15,500 | 15 | 数据血缘，数据包模式，数据源弹性 |
| brain | 74 | ~15,100 | 18 | Wyckoff 瓶颈，因子注册，引擎输出 |
| signal | 7 | ~2,200 | 8 | 仲裁，适配器，正常化 |
| risk | 7 | ~1,700 | 6 | 头寸规模，集中度，回撤 |
| hands | 34 | ~6,200 | 16 | 回测完整性，匹配引擎 |
| services | 31 | ~8,900 | 14 | 扫描性能，服务编排，观察能力 |
| ui | 8 | ~3,300 | 2 | 仪表盘健康检查 |
| **总计** | **~264** | **~58,700** | **91** | — |

---

## 4. 目标架构（来自 WS14）

```
config.yaml → ServiceContainer → DataService → AnalysisService_v2 ──→ DecisionBrain
                                              │                          │
                                              ↓                          ↓
                                        ResearchDataPack          DecisionOutput
                                              │                          │
                                              └──→ 9 engines             ├──→ SignalArbitrator
                                                   (typed inputs)       │       ↓
                                                                         │  CandidateSignal[]
                                                                         │       ↓
                                                                         │  TradingSignalCollector
                                                                         │       ↓
                                                                         │  TradingSignal[]
                                                                         │
                                               EventBus ──→ UnifiedBacktestEngine
                                                        └──→ MetricsRecorder
                                                        └──→ FactorAdmissionGate
```

---

## 5. 迁移路线图（来自 WS15）

| 阶段 | 冲刺周期 | 持续时间 | 风险 | 并行 |
|---|---|---|---|---|
| 第 1 阶段：基础类型 | A | 2 天 | 低 | 与第 2–5 阶段 |
| 第 2 阶段：数据层 | B | 10 天 | **高** | 与第 4–5 阶段 |
| 第 3 阶段：信号/因子 | C | 5 天 | 中 | 与第 5 阶段 |
| 第 4 阶段：事件/观察能力 | D | 5 天 | 低 | 与第 2–3、5 阶段 |
| 第 5 阶段：配置/健康 | D/E | 3 天 | 低 | 与第 2–4 阶段 |
| **总计** | **A–E** | **25 天** | — | — |

P0 解决时间线：
- **第 2 阶段（冲刺周期 B）**：P0-1（ResearchDataPack），P0-3（引擎重构）
- **第 3 阶段（冲刺周期 C）**：P0-2（时间戳冻结），P0-4（SignalArbitrator），P0-5（FactorGate）

---

## 6. 按证据状态统计的发现

| 状态 | 统计 | 备注 |
|---|---|---|
| ✅ 充分证据 | 79 | 通过源代码、配置或测试输出验证 |
| ⚠️ 证据不足 | 12 | 主要为生产交易领域（经纪商、OMS、HA、DR） |
| ❌ 无证据 | 3 | 经纪商集成，订单状态机，实时事故恢复 |

所有标记为 `INSUFFICIENT EVIDENCE` 的发现均已明确记录为已知差距，对当前研究范围无影响。

---

## 7. 定义清单完成情况

| 条件 | 状态 |
|---|---|
| 所有 18 个最终交付物已存在 | ✅ |
| 每个发现都有证据、影响、风险等级、建议、迁移成本、优先级和验证信息 | ✅ |
| 每个 `INSUFFICIENT EVIDENCE` 条目要么有证据，要么被明确接受为已知差距 | ✅ |
| 研究平台范围与实盘交易范围保持分离 | ✅ |
| P0/P1 建议有测试或验证计划 | ✅ |
| 目标架构和目标合约已完成文档记录 | ✅ |
| 迁移策略已分阶段、可回滚且可部署 | ✅ |
| 最终路线图已按研究可信度优先排序 | ✅ |

---

## 8. 已推迟到生产范围的项目

以下内容已明确标记为超出当前研究审计范围，需具备实盘交易实施能力后另行处理：

1. **经纪商适配器** — 不存在任何 Broker/OMS/Gateway 类
2. **订单状态机** — 订单状态、成交对账、订单持久化
3. **头寸对账** — 未对接外部账户
4. **高可用性** — 单进程架构，无副本
5. **灾难恢复 / RPO / RTO** — 未定义指标
6. **实时事故恢复** — 除 DecisionBrain FSM 状态外无进程级恢复
7. **完整 OTel 导出** — WS11 定义了接口，未实现
8. **实时限流** — 目前仅逐数据源进行

---

## 9. 交付物列表

| WS | 项目 | 文件 | 核心产出 |
|---|---|---|---|
| 0 | 控制 | `FINDING_TEMPLATE.md`， `index.md`， `00_master_work_plan.md` | 可重复审计框架 |
| 0b | 发现索引 | `FINDINGS_INDEX.md` | P0/P1 执行看板、原始 finding 库存、关闭规则 |
| 0c | 实施准入 | `IMPLEMENTATION_ENTRY_CRITERIA.md` | 进入代码实现前的阶段门槛、测试、回滚和停止条件 |
| 1 | 架构 | `01_architecture_discovery.md` | 8 层映射，依赖关系图，God Object 识别 |
| 2 | 数据血缘 | `02_data_lineage_audit.md` | 10 项发现，data_pack 模式设计（§7） |
| 3 | 回测 | `03_backtest_integrity_audit.md` | 16 项发现，16 项控制摘要表 |
| 4 | 历史信号 | `04_historical_signal_series_blueprint.md` | 两阶段 HistoricalSignalRunner |
| 5 | 接口合约 | `05_interface_contract_audit.md` | 15 项发现，目标合约矩阵 |
| 6 | 适配器 | `06_adapter_blueprint.md` | CandidateSignal/SignalArbitrator/PortfolioAdapter |
| 7 | 因子准入 | `07_factor_admission_governance.md` | FactorManifest，FactorAdmissionGate，10 项检查 |
| 8 | 性能 | `08_performance_autopsy.md` | 11 项发现，Wyckoff 瓶颈，延迟预算 |
| 9 | 配置 | `09_configuration_governance.md` | 11 项关于配置漂移、密钥、特性标志的发现 |
| 10 | 研究风险 | `10_research_risk_governance.md` | 10 项发现，11 项控制治理矩阵 |
| 11 | 可观测性 | `11_observability_blueprint.md` | 9 项关于 OTel 兼容性差距的发现 |
| 12 | 事件架构 | `12_event_architecture_blueprint.md` | 9 项发现，Event/Command/Query 模型 |
| 13 | 生产就绪度 | `13_production_readiness_report.md` | 经纪商差距、高可用性/灾难恢复、数据源、缓存、事故恢复 |
| 14 | TDD 重建设计 | `14_tdd_refactoring_design.md` | 目标架构、合约、迁移、测试矩阵 |
| 15 | 重建路线图 | `15_refactoring_roadmap.md` | 有序执行计划、工作量、P0 时间线 |

**总计**：15 个工作流，91 项发现，5 个 P0 项目，8 个 P1 项目，25 天重建工作量。

---

## 10. 后续路径

1. **实施阶段（可选）**：按照 WS15 路线图 Phase 1 开始，以 TDD 方式先实现合约测试与类型定义，再推进后续阶段。
   - 进入实施前先使用 `FINDINGS_INDEX.md` 和 `IMPLEMENTATION_ENTRY_CRITERIA.md` 建立任务追踪、测试计划和回滚路径。
2. **完整 OTel 导出**：在 WS11 定义的接口基础上实现。
3. **生产范围**：当实盘交易成为目标时，从 WS13 差距 + WS6 蓝图开始。
4. **文档翻译**：按需将关键文档翻译为中文。

---

## 11. 收尾检查项

审计产生的文档本身未对源码做实现性修改。以下 3 项原主计划遗留检查的状态：

| 检查项 | 状态 | 结论 |
|---|---|---|
| 合约测试 | ✅ 已形成测试设计，未实现源码测试 | `14_tdd_refactoring_design.md` 与 `15_refactoring_roadmap.md` 已定义 Phase 1/2 合约测试；实施阶段再落地 |
| 信号仲裁测试 | ✅ 已形成测试设计，未实现源码测试 | `06_adapter_blueprint.md`、`10_research_risk_governance.md`、`14_tdd_refactoring_design.md`、`15_refactoring_roadmap.md` 已定义 `SignalArbitrator` 单元、集成和回归测试 |
| 最终整合报告 | ✅ 已完成 | 本文件即最终整合报告，覆盖 WS0-WS15、P0/P1、范围边界、目标架构、迁移路线图 |

当前审计/规划阶段已闭环。后续若进入实现阶段，应从 WS15 Phase 1 开始，以 TDD 方式先实现合约测试与类型定义。
