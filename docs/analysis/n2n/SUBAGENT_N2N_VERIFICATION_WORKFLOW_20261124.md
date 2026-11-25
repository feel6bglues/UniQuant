# UniQuant 子代理驱动 N2N 独立复核工作流

> **日期**：2026-11-24 · **状态**：执行中
> **代码基线**：`b1d2415`（含第 24~25 轮及后续文档补丁，晚于既有 Claude 报告基线 `434aab1`）
> **执行载体**：多子代理并行代码级审查（每代理一个模块/维度）
> **目的**：从 N2N（node-to-node 端到端）角度吃透系统，并对既有 Claude 单代理产出的
> `docs/analysis/n2n/0*.md` 报告执行**独立交叉复核**（对齐 AGENTS.md 反循环自证纪律）。

---

## 1. 方法论：N2N 五问模板

每个子代理对其模块必须逐节点回答五个核心问题（`file:line` 为证据）：

| # | 问题 | 含义 |
|---|------|------|
| **Q1 Name 定义** | 命名与契约 | 公开类/函数命名是否自解释？输入输出字段命名是否清晰？有无同名异义/同义反复？ |
| **Q2 Name 映射** | 数据流转映射 | 输入字段→内部处理逻辑映射；内部状态→输出字段映射；有无隐式转换/字段丢失？ |
| **Q3 Name 传播** | 依赖链追踪 | 本模块输出被哪些下游消费？下游如何用（字段级）？有无未文档化隐式契约？ |
| **Q4 Name 变异** | 边界与异常 | 空/NaN/超范围输入如何降级？除零/溢出/精度如何防？有无静默失败/错误掩盖？ |
| **Q5 Name 治理** | 可观测与可测 | 关键决策点有无日志？错误路径有无明确异常类型？测试是否覆盖边界/异常？ |

**约束（诚实门禁）**：所有结论必须给出 `file:line` 证据；禁止推测；禁止伪造；Rule 4 合规
（缺失输入必须显式失败而非静默填充）。

---

## 2. 九个子代理任务分解

| # | 子代理 | 模块 | 规模 | 交叉复核对象 | 产出物 |
|---|--------|------|------|--------------|--------|
| S1 | 数据流转 | `src/uniquant/data/` | 40 文件 / 7,808 行 | `01_data_flow_n2n.md` | `n2n/subagent_verification_20261124/01_data_flow.md` |
| S2 | 分析引擎 | `src/uniquant/brain/` | 73 文件 / 20,917 行 | `02_analysis_engines_n2n.md` | `.../02_analysis_engines.md` |
| S3 | 信号生成 | `src/uniquant/signal/` | 3 文件 / 1,194 行 | `03_signal_generation_n2n.md` | `.../03_signal_generation.md` |
| S4 | 回测撮合 | `src/uniquant/hands/backtest/` | ~20 文件 | `04_backtest_matching_n2n.md` | `.../04_backtest_matching.md` |
| S5 | 风控合规 | `src/uniquant/risk/` + `shared/kill_switch.py` | 5+1 文件 | `05_risk_compliance_n2n.md` | `.../05_risk_compliance.md` |
| S6 | 服务编排 | `src/uniquant/services/` | 28 文件 / 8,554 行 | `06_service_orchestration_n2n.md` | `.../06_service_orchestration.md` |
| S7 | 研究控制平面 | `src/uniquant/research/` | 12 文件 / 1,885 行 | `07_research_control_plane_n2n.md` | `.../07_research_control_plane.md` |
| S8 | UI 展示 | `src/uniquant/ui/` | 8 文件 / 3,400 行 | `08_ui_presentation_n2n.md` | `.../08_ui_presentation.md` |
| S9 | 跨模块集成 | 全链路 + `shared/interfaces.py` | 端到端 | `09_cross_module_integration.md` | `.../09_cross_module_integration.md` |

**S9 跨模块集成范围**：以典型信号（Wyckoff SPRING→BUY、QAR 冲突仲裁→SELL）为探针，
从数据湖 → 分析 → 信号 → 仲裁 → 回测 → 风控 → 执行/对账逐节点追踪，检查
`interfaces.py` 契约（`TradingSignal`/`ResearchDataPack`/`PipelineResult`/`EngineOutput`）
在跨模块边界是否字段一致、无丢失。

---

## 3. 执行顺序与并行策略

1. **批次 A（P0 核心，4 代理并行）**：S1 数据流转、S2 分析引擎、S3 信号生成、S4 回测撮合。
2. **批次 B（P1/P2 模块，4 代理并行）**：S5 风控合规、S6 服务编排、S7 研究控制平面、S8 UI 展示。
3. **批次 C（集成，1 代理）**：S9 跨模块集成（依赖批次 A/B 模块边界认知，可参考既有模块报告）。

批次 A/B 完成后启动 S9；S9 汇入后由主会话综合成最终报告。

---

## 4. 质量门禁（每个子代理必须满足）

- [ ] 模块核心文件逐文件审查，关键节点已读源码
- [ ] 五个 N2N 问题全部回答（有证据）
- [ ] 至少 3 条端到端数据流路径已追踪（含 1 条异常路径）
- [ ] 至少 2 个边界条件/异常路径已验证
- [ ] 所有结论精确到 `file:line`
- [ ] 发现按 CRITICAL/HIGH/MEDIUM/LOW 分级
- [ ] 与既有 Claude 报告交叉对比：标注「一致 / 分歧（附双方证据）/ 既有问题是否已修复」
- [ ] 给出可执行修复建议（如有问题）

---

## 5. 主会话综合产物

1. `docs/analysis/n2n/subagent_verification_20261124/N2N_SUBAGENT_COMPREHENSIVE_REPORT.md`
   —— 汇总 9 份子代理报告 + 独立复核矩阵（子代理裁决 vs 既有 Claude 裁决），
   给出最终健康度与行动项。
2. `docs/analysis/n2n/subagent_verification_20261124/VERIFICATION_MATRIX.md`
   —— 逐问题交叉核对表（问题、级别、双方证据、一致性结论、是否遗留）。

---

## 6. 与既有文档关系

| 文档 | 层级 | 本工作流关系 |
|------|------|--------------|
| `N2N_VERIFICATION_PLAN_20261122.md` | 系统级（六轨集成测试） | **互补**：那是系统级运行时验收，本工作流是代码级审查 |
| `N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md` | 工作流设计 | **参考**：既有工作流骨架 |
| `docs/analysis/n2n/0*.md`（Claude 单代理产出） | 模块级 | **复核对象**：本工作流以子代理独立重析并交叉核对 |
| `DEEP_VERIFICATION_9_REPORTS_20261124.md` | 系统级（声明验证 98.9%） | **参考**：事实基线 |

---

**创建人**：主会话（OpenCode/商量） · **方法**：多子代理并行 + 独立复核 · **预计产出**：9 份模块报告 + 2 份汇总
