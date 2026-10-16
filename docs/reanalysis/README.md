> ⚠️ **历史快照（point-in-time audit）** — 本文档记录的是**撰写时点**的工作树状态。其中的文件数 / LOC / 测试数 / 覆盖率 / 死代码清单 / "已修复" 声明**均可能已失效**，且已知与当前实测口径不符。
> **请勿**将其作为当前状态的依据。当前真相源见 [`docs/index.md`](../index.md)、[`AGENTS.md`](../../AGENTS.md) 与 [`docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`](../analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md)。

# docs/reanalysis/ — 历史审计快照索引

本目录是 UniQuant 早期**只读审计活动**的产物归档，全部为 **point-in-time 快照**，**已被当前实现取代**：

- **Phases 0-9 基线重分析运动**（2026-06-30 起）：基线审计、工作树差异、8 引擎正确性、回测信任、数据管道、信号系统、工程健康、生产就绪、治理、路线图。
- **v2.0 深度审计 A-K 运动**（2026-07-06 起）：代码质量、测试质量、数据质量、引擎运行时行为、回测信任扩展、信号审计、性能、安全、可观测性、评分卡，及配套红蓝核实 / live system map。
- **Z_\* 调查 / 红蓝对抗 / walk-forward 系列**（2026-07-06 ~ 2026-07-24）：逐文件排查、红蓝对抗、LPPL/Wyckoff/参数扫描/信号链的验证与重新设计。

这些文档在撰写时对当时的代码库是准确的，但随后经历了多轮修复、简化、数据源迁移与全仓清理（如 `src/` 物理删除、`docs/archive/` 归并）。**任何数字与结论都不得作为当前状态的依据。** 当前唯一真相源是 `docs/index.md`、`AGENTS.md` 与 2026-10-16 实测评估报告。

> 归档动机与措辞对标的先例：`docs/archive/INDEX.md`。

## 文件清单

### Phases 0-9（2026-06-30 基线运动）

| 文件 | 说明 | 日期 |
|---|---|---|
| `00_baseline_audit.md` | Phase 0 — 基线审计：测试/lint/import 基线与项目规模 | 2026-06-30 |
| `01_worktree_diff_analysis.md` | Phase 1 — 工作树差异 + stash 分析，46 文件提交归类 | 2026-06-30 |
| `02_engine_correctness_audit.md` | Phase 2 — 8 引擎正确性评级（A-） | 2026-06-30 |
| `03_backtest_trust_audit.md` | Phase 3 — 回测信任度，7 条 A 股防线核验（A-） | 2026-06-30 |
| `04_data_pipeline_reliability.md` | Phase 4 — 数据管道可靠性（多源路由 + 流水线，B+） | 2026-06-30 |
| `05_signal_system_audit.md` | Phase 5 — 信号系统（适配器 + 仲裁器，A） | 2026-06-30 |
| `06_engineering_health.md` | Phase 6 — 工程健康度（lint/TODO/导入，A-） | 2026-06-30 / 07-09 |
| `07_production_readiness.md` | Phase 7 — 生产就绪度（安全/配置/错误处理，B+） | 2026-06-30 |
| `08_governance_testing.md` | Phase 8 — 治理与测试结构 / CI 就绪度（B+） | 2026-06-30 / 07-09 |
| `09_final_roadmap.md` | Phase 9 — 最终建议路线图（P0-P3） | 2026-07-06 / 07-09 |

### v2.0 深度审计 A-K（2026-07-06）

| 文件 | 说明 | 日期 |
|---|---|---|
| `A0_doc_health_scan.md` | 文档健康度扫描：量化文档与代码偏差（只出数字） | 2026-07-01 |
| `A_code_quality.md` | Phase A — 代码质量深度审计（重复/复杂度/死代码，Fair） | 2026-07-06 |
| `B_test_quality.md` | Phase B — 测试质量（mutmut 基线失效、覆盖率缺口） | 2026-07-06 |
| `C_data_quality.md` | Phase C — 数据质量与可靠性（数据湖/复权/日历/缓存，B+） | 2026-07-06 |
| `D_engine_behavior.md` | Phase D — 引擎运行时行为（插桩/故障注入/全量采样，B+） | 2026-07-06 |
| `E_backtest_trust.md` | Phase E — 回测信任度扩展（7 线 PASS） | 2026-07-06 |
| `F_signal_audit.md` | Phase F — 信号系统行为审计（A-） | 2026-07-06 |
| `G_performance.md` | Phase G — 性能与可扩展性（约 64 MB/s，A-） | 2026-07-06 |
| `H_security.md` | Phase H — 安全审计（B+） | 2026-07-06 |
| `I_observability.md` | Phase I — 可观测性与运维审计 | 2026-07-06 |
| `J_scorecard.md` | Phase J — 生产就绪度评分卡（3.29/5.0 — B） | 2026-07-06 / 07-09 |
| `B_delta_20260701.md` | Phase 2 增量验证：`bc6337bc` 后工作树变化 | 2026-07-01 |
| `C_consolidated_issues.md` | Phase 3 问题整合：6 个分析纪元 + worktree delta | 2026-07-01 |
| `cross-cutting-notes-A-C.md` | Phase A ↔ C 交叉发现交换（供 Wave 2） | 2026-07-06 |
| `D_recommended_gates.md` | Phase 4 建议门禁清单（基于 Phase 0-3） | 2026-07-01 |
| `E_red_blue_analysis.md` | 红蓝对抗：文档宣称 vs 源码现实（22 议题） | 2026-07-09 |
| `F_verified_task_list.md` | 红蓝核实后的任务清单 | 2026-07-09 |
| `G_four_role_assessment.md` | 多角色评估：作为研究平台的 UniQuant | 2026-07-09 |
| `H_multi_round_trace_analysis.md` | 多轮深链追踪：P0-P1 全路径验证（12 数据流 / 8 文件） | 2026-07-09 |
| `I_live_system_map.md` | 活体系统地图（7 层逐文件源码审计修正版） | 2026-07-09 |
| `J_remediation_task_list.md` | 修复任务清单（基于 7 层逐文件审计） | 2026-07-09 |

### Z_\* 调查 / 红蓝对抗 / walk-forward 系列（2026-07-06 ~ 2026-07-24）

| 文件 | 说明 | 日期 |
|---|---|---|
| `Z_reanalysis_plan_v2.md` | 全面重分析计划 v2.0 | 2026-07-06 |
| `Z_redblue_parallel_plan.md` | 并行/串行任务清单红蓝对抗 | 2026-07-06 |
| `Z_final_task_list.md` | 重分析 v2.0 最终任务清单（红蓝修正后） | 2026-07-06 |
| `Z_remediation_worksheet_red_blue_analysis.md` | v2 修复工作表红蓝评估（31 项 / 47h） | 2026-07-07 |
| `Z_final_synthesis_20260709.md` | 7 轮综合诊断报告 | 2026-07-09 |
| `Z_7round_conversation_summary.md` | 7 轮分析对话完整总结 | 2026-07-09 |
| `Z_redblue_comprehensive_report_20260710.md` | 综合红蓝对抗最终报告（v5 修复后） | 2026-07-10 |
| `Z_tdd_redblue_consolidated_report_20260710.md` | 红蓝 + TDD 综合评估（五层并行） | 2026-07-10 |
| `Z_investigation_report_20260710.md` | 五轮多重源码排查 + 红蓝核实 | 2026-07-10 |
| `Z_red_blue_20260713_final.md` | 红蓝 + TDD 全面评估（六路并行） | 2026-07-13 |
| `Z_lppl_wyckoff_standard_vs_implementation_comparison_20260724.md` | LPPL & Wyckoff 标准理论 vs 本项目实现对比 | 2026-07-24 |
| `Z_red_blue_lppl_wyckoff_20260724.md` | LPPL & Wyckoff 预测失效根因红蓝对抗 | 2026-07-24 |
| `Z_red_blue_plan_verification_final_20260724.md` | 实施计划红蓝验证 — 最终裁决 | 2026-07-24 |
| `Z_red_blue_plan_verification_round1_lppl_index_20260724.md` | 计划验证 R1：LPPL 指数方案 | 2026-07-24 |
| `Z_red_blue_plan_verification_round2_wyckoff_20260724.md` | 计划验证 R2：Wyckoff A-E 状态机 | 2026-07-24 |
| `Z_red_blue_plan_verification_round3_pnf_signal_20260724.md` | 计划验证 R3：P&F + 九项测试 + 信号链 | 2026-07-24 |
| `Z_red_blue_reimplementation_final_20260724.md` | 重新设计最终裁决 + 实施路线图 | 2026-07-24 |
| `Z_red_blue_reimplementation_round1_lppl_20260724.md` | 重新设计 R1：LPPL | 2026-07-24 |
| `Z_red_blue_reimplementation_round2_wyckoff_20260724.md` | 重新设计 R2：Wyckoff | 2026-07-24 |
| `Z_red_blue_reimplementation_round3_signalchain_20260724.md` | 重新设计 R3：信号链 + 工程整合 | 2026-07-24 |
| `Z_param_sweep_v1_redblue_round1_20260724.md` | 参数扫描脚本 v1 红蓝 R1（正确性 / 效率） | 2026-07-24 |
| `Z_param_sweep_v1_redblue_round2_stats_20260724.md` | 参数扫描 v1 红蓝 R2（统计方法论） | 2026-07-24 |
| `Z_param_sweep_v1_redblue_round3_optimization_20260724.md` | 参数扫描 v1 红蓝 R3（优化方案） | 2026-07-24 |
| `Z_param_sweep_v2_analysis_report_20260724.md` | 参数敏感性扫描 v2 分析报告 | 2026-07-24 |
| `Z_theory_practice_proposal_20260724.md` | 理论与实际结合 — 建议方案 | 2026-07-24 |
| `Z_walk_forward_theoretical_foundation_20260724.md` | walk-forward 判定有效性的理论 + 代码 + A 股三层证据 | 2026-07-24 |

### Other

| 文件 | 说明 | 日期 |
|---|---|---|
| `wyckoff_architecture.md` | Wyckoff 子包架构（18 源文件 / 7,133 LOC，占 `brain/` 44%） | 2026-07-14 |
| `Wyckoff_LPPL_Factor_Pipeline_Verification_Report.md` | Wyckoff / LPPL / Factor 4 阶段管线可靠性验证 | 2026-07-23 |

## 已知失效口径

以下数字均**出现在本目录文档正文中**，且已与当前实测口径不符（当前值为 2026-10-16 实测）：

| 失效断言（文档原文） | 出处示例 | 当前实测值 |
|---|---|---|
| Python 源文件 **252 / 254 / 256** | `00_baseline_audit.md`（252）、`H_security.md`（254）、`E_red_blue_analysis.md` / `I_live_system_map.md`（256） | **236** |
| 源码 LOC **62,549 / 62,559 / 62,518** | `Z_investigation_report_20260710.md`、`Z_red_blue_20260713_final.md`、`J_remediation_task_list.md` | **59,594** |
| 测试函数 **1,606 / 1,641 / 1,666 / 1,673 / 1,674**；测试文件 **127 / 128** | `E_red_blue_analysis.md`、`Z_redblue_comprehensive_report_20260710.md`、`I_live_system_map.md`、`J_remediation_task_list.md` | **2,359 测试函数 / 194 测试文件** |
| 测试通过 **1,666 / 1,673 / 1,678** | `G_four_role_assessment.md`、`Z_redblue_comprehensive_report_20260710.md` | **2,596 passed / 2 skipped** |
| 全包覆盖率 **50.77% / 52.66% / 52.68%** | `C_consolidated_issues.md`、`Z_tdd_redblue_consolidated_report_20260710.md`、`Z_red_blue_20260713_final.md` | **70.55%**（`ui/` 除外） |
| 零覆盖文件 **45 文件 / 3,791 LOC** | `Z_tdd_redblue_consolidated_report_20260710.md`、`Z_redblue_comprehensive_report_20260710.md` | 已无此口径；当前最弱层为 `data/` **53.9%** |
| 死代码库存 **~1,928 / ~2,217 / ~2,225 / ~2,266 / ~2,298 LOC** | `A_code_quality.md`、`Z_red_blue_20260713_final.md`、`I_live_system_map.md` | **0**（archive/ 目录已物理删除） |
| 死代码模块名（`factor_governance.py`、`portfolio_engine.py` 等） | `Z_red_blue_20260713_final.md` | 相关死模块已物理移除，请勿据本文档重新引入 |
| "已修复 / FIXED" 声明 | 遍布 `F_verified_task_list.md`、`Z_redblue_comprehensive_report_20260710.md` 等 | 部分修复在后续重构/迁移中回归或改写，**不可视为当前状态** |
| 数据源 / 引擎模块清单 | `I_live_system_map.md`、`wyckoff_architecture.md` | 数据源收敛迁移与全仓清理已改变模块边界（如 `sources/tdx.py` 已删除） |

> 注：文档中的 `93% coverage` 指标仅指当时 **`signal/db.py` 单文件**，不代表全包覆盖率；引用时勿与全包口径混淆。
