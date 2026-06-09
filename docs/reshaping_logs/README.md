# Reshaping Logs State Index

日期: 2026-06-08

## 当前规则

本目录是本轮受控状态机审计与修复的唯一连续状态链。

阶段 4 及后续剩余风险修复应优先读取:

- `MASTER_REMEDIATION_PLAN.md`
- `docs/reshaping_logs/01_global_topology.md`
- `docs/reshaping_logs/02_deep_inspection.md`
- `docs/reshaping_logs/04_*.md`
- `docs/reshaping_logs/05_*.md`
- `docs/reshaping_logs/06_*.md`

`docs/` 下其他审计、评估、路线图和历史迁移报告只作为背景材料，不得直接作为当前代码状态依据。

## 当前已完成状态链

| 文件 | 状态 | 内容 |
|------|------|------|
| `01_global_topology.md` | 完成 | 全局拓扑、God Objects、并行体系 |
| `02_deep_inspection.md` | 完成 | 分段深度核查与 P0/P1/P2 风险原始证据 |
| `04_1_remediation.md` | 完成 | 数据流、异常、随机种子修复 |
| `04_2_remediation.md` | 完成 | 接口契约与信号转换修复 |
| `04_3_remediation.md` | 完成 | 被动风控防线修复 |
| `05_1_p1_cache_invalidation.md` | 完成 | 缓存失效广播 |
| `05_2_p1_backtest_compat.md` | 完成 | 新旧回测兼容边界 |
| `05_3_p1_data_entry_injection.md` | 完成 | 数据入口依赖注入 |
| `05_4_p1_god_object_containment.md` | 完成 | God Object 风险封装 |
| `05_5_p1_factor_diagnostics.md` | 完成 | 因子诊断透明化 |
| `05_6_p1_reproducibility.md` | 完成 | Monte Carlo/Bootstrap 可复现 |
| `05_7_p1_di_container_compat.md` | 完成 | DI 兼容层反向依赖收敛 |
| `05_8_full_regression.md` | 完成 | P0/P1 全量回归收口 |
| `06_1_p2_trace_id.md` | 完成 | TraceID 传播 |
| `06_2_p2_ui_risk_boundary.md` | 完成 | UI-risk 边界收敛 |
| `06_3_p2_docs_state_boundary.md` | 完成 | 文档状态源边界 |
| `06_4_p2_randomness_annotations.md` | 完成 | 网络/mock 随机标注 |
| `06_5_p2_final_closure.md` | 完成 | P2 收口与最终回归 |
| `07_1_lint_debt_cleanup.md` | 完成 | 全仓 ruff 历史债清理 |
| `08_final_handoff.md` | 完成 | 最终交付摘要 |

## 当前事实基线

- 当前源码以 `AGENTS.md` 和本目录日志为优先事实源。
- `data/`、`signal/`、`hands/` 等 8 个声明层均已存在。
- 原 `shared/constants.py` 已拆为 `src/uniquant/shared/constants/` 子包，并由 `__init__.py` 聚合导出。
- P0/P1 全量回归基线见 `05_8_full_regression.md`: `1020 passed, 7 skipped, 12 warnings, 0 failed`。

## 历史文档处理规则

- 任何声称 `data/` 或 `signal/` 缺失的文档均为历史状态。
- 任何声称常量仍集中在单文件 `shared/constants.py` 的文档均为历史状态。
- 任何声称分析引擎只有 9 个的文档均需对照当前 `engine_factory.py` 与 `AGENTS.md` 复核。
- 需要引用历史文档时，必须同时写明“历史背景，非当前状态”。
