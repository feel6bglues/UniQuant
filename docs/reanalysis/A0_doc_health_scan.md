# Phase 0 — 文档健康度扫描

> 2026-07-01 | 量化问题，不做深入分析，只出数字。

---

## 总体指标

| 指标 | 数值 |
|---|---|
| `.md` 文件总数 | **260** |
| 文档总行数 | **98,128** |
| Python 代码行数 | 62,300 |
| **文档:代码比率** | **1.57 : 1** |
| 标记为 Current 的文档 | 31 |
| 标记为 ⚠️ Partial/Mixed/Archived | 40 |

---

## 五纪分析冗余

项目经历了至少 5 个独立的"全量分析"纪元，每纪元产出 10-71 个文档，覆盖相同子系统：

| 纪元 | 位置 | 文件数 | 行数 | 时间 |
|---|---|---|---|---|
| 早期分析 + 修复 | `docs/archive/` | 71 | 33,539 | 2026-05~06 |
| Phase 3 全局扫描 | `docs/archive/audit_logs/` | 27 | — | 2026-06 |
| Playbook 8 阶段 | `docs/analysis/` | 11 | 15,962 | 2026-06 |
| Institutional 审计 | `docs/analysis/institutional/` | 26 | 10,307 | 2026-06 |
| 重塑日志 | `docs/reshaping_logs/` | 38 | 3,316 | 2026-06 |
| 9 阶段再分析 | `docs/reanalysis/` | 10 | 1,418 | 2026-06-30 |
| 其他散落 | `docs/*.md` + 各子目录 | 77 | 33,586 | 混合 |

**核心问题**：6 个纪元，每个都对 engine/backtest/data/signal/factor/risk 做了完整分析，但**没有任何一个纪元被声明为 canonical truth**。

---

## 按子系统冗余深度

每个核心概念被引用的文档数（跨全部纪元）：

| 概念 | 覆盖它的文档数 |
|---|---|
| engine | **124** |
| regime/lppl/wyckoff/czsc/ntf | **126** |
| signal | **122** |
| risk | **114** |
| backtest | **105** |
| factor | **102** |
| data pipeline/validation | 58 |
| position sizing | 57 |

**核心结论**：每个引擎被提及 124 次，但只有 1 个 GitHub Actions CI 配置（刚加）。

---

## 文档-代码比例失真

| 层 | 代码 LOC | 覆盖它的文档数 | 比率 |
|---|---|---|---|
| `signal` | 2,668 | 186 | **14.3 docs / 100 LOC** |
| `risk` | 1,638 | 188 | **11.5 docs / 100 LOC** |
| `ui` | 3,363 | 190 | **5.6 docs / 100 LOC** |
| `services` | 9,744 | 147 | 1.5 |
| `brain` | 15,975 | 194 | 1.2 |
| `data` | 15,440 | 233 | 1.5 |

**结论**：`signal` 和 `risk` 代码量最少，但被最多文档覆盖（因为每纪元都按 8 层结构写报告）。

---

## 根目录过时散落文档

`docs/` 根目录 18 个 `.md` 中明确是**旧修复计划**的有 8 个 (44%)：

| 文件 | 行数 |
|---|---|
| `repair_plan_lppl_wyckoff.md` | 783 |
| `docs_fix_plan.md` | 504 |
| `docs_fix_plan_evaluation.md` | 386 |
| `docs_fix_execution_plan.md` | 311 |
| `repair_plan_phase6.md` | 190 |
| `repair_task_schedule.md` | 101 |
| `repair_task_schedule_phase4.md` | 91 |
| `repair_task_schedule_phase6.md` | 77 |

---

## 关键发现总结

| 发现 | 严重度 | 说明 |
|---|---|---|
| **分析瘫痪** | 🔴 | 6 个纪元 = 6 倍重复，实质产出 260 个 .md 而非代码修复 |
| **无单一事实源** | 🔴 | 要确认引擎正确性，读者需查阅 124 个相关文档 |
| **文档-代码比 1.57×** | 🟡 | 文档比代码多 57% |
| **56% 文档过期/警告** | 🟡 | 40/71 条目不是 Current |
| **8 个旧计划散落根目录** | 🟢 | 易清理 |

---

## 建议

**停止生产新分析文档。立即执行：文档瘦身 → 增量验证 → P0 冲刺。**
