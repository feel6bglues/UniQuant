# 16 Docs Fix — 文档一致性修复

生成时间: 2026-06-28 18:30

## 触发条件

`docs/docs_fix_plan.md` 修复计划在执行前经过评估 (`docs/docs_fix_plan_evaluation.md`), 发现 3 处关键问题:

1. **F07/F08 误判**: "8 层"指架构层 (shared/data/brain/signal/risk/hands/services/ui), 非引擎数。原文本正确。
2. **F03 指向错误文件**: `518-526` 行号错误实际存在于 `00_architecture_map.md:77` 和 `01_services_orchestration.md:207`, 非 `architecture.md`。
3. **遗漏 3 处**: `src_comprehensive_analysis_report.md:4`, `src_analysis_plan.md:3`, `00_architecture_map.md:28-30`。

## 修复范围

### 已执行 (15 edits, 11 files, 3 轮并行)

| 文件 | 修改内容 | 类型 |
|------|---------|------|
| `architecture.md` | 引擎数 8→9, 加 wyckoff 表格行 | 数字/内容 |
| `ARCHITECTURE_TOPOLOGY.md` | God Object 注释更新 + banner 标注 | 内容 |
| `DATA_FLOW_WHITEPAPER.md` | Adapter "草案"→"已实现" | 状态 |
| `index.md` | 269→254 | 数字 |
| `USAGE_GUIDE.md` | 179→254, 42,549→62,804 | 数字 |
| `MATCHING_ENGINE_AUDIT.md` | 加漏洞状态 banner | 状态 |
| `GAP_REMEDIATION_PLAN.md` | 加缺口关闭 banner | 状态 |
| `00_architecture_map.md` | 层文件数 37→44/68→65/47→55, 行号 518→618 | 数字/行号 |
| `01_services_orchestration.md` | 行号 518→618, pd.Timestamp.now 加 G-1 说明 | 行号/内容 |
| `src_comprehensive_analysis_report.md` | header 269→254 | 数字 |
| `src_analysis_plan.md` | 基准 269→254 | 数字 |

### 明确排除

| 项 | 理由 |
|----|------|
| F07/F08 (whitepaper "8 层"修正) | "8 层"指架构层, 正确, 不改 |
| Wyckoff 索引文件 (R04) | 与 analysis/ 命名约定冲突 |
| verify_doc_paths.py 扩展 (F15) | 非文档修复, 独立工程任务 |
| Mermaid 图更新 | 重构成本 vs 收益不合算 |

### 验证

```
find src/uniquant/ -name "*.py" | wc -l             → 254
find .../shared/*.py | wc -l                        → 44
find .../data/*.py | wc -l                          → 65
find .../brain/*.py | wc -l                         → 55
grep "def _make_decision" analysis_service_v2.py    → 618
rg "pd\.Timestamp\.now" src/uniquant/               → 0 (production)
grep -c "9 个" docs/architecture.md                 → 1
grep -c "wyckoff" docs/architecture.md              → 4
```

### 状态

✅ 完成 — 11 个文件, 15 edits, 3 轮并行, 0 冲突, 全部验证通过。
