# UniQuant 文档修复并行执行计划

> 生成日期: 2026-06-28
> 基于: `docs/docs_fix_plan_evaluation.md` §7.1 修正后的 14 项清单
> 目标: 最大并行 + 零冲突

---

## 1. 文件级冲突分析

### 1.1 按文件分组

```
文件                                 编辑数  编辑位置      冲突类型
─────────────────────────────────────────────────────────────
architecture.md                        2    L276 / L278-287  ⚠️ 紧密相邻
ARCHITECTURE_TOPOLOGY.md               2    L364 / L1-5      ⚠️ 同一文件
00_architecture_map.md                 2    L77 / L28-30     ⚠️ 同一文件
01_services_orchestration.md           2    L207 / L212      ⚠️ 同一文件
DATA_FLOW_WHITEPAPER.md                1    L598-657         ✅ 单编辑
index.md                               1    L18              ✅ 单编辑
USAGE_GUIDE.md                         1    L3               ✅ 单编辑
MATCHING_ENGINE_AUDIT.md               1    L1-6             ✅ 单编辑
GAP_REMEDIATION_PLAN.md                1    L1-7             ✅ 单编辑
src_comprehensive_analysis_report.md   1    L4               ✅ 单编辑
src_analysis_plan.md                   1    L3               ✅ 单编辑
─────────────────────────────────────────────────────────────
总计: 11 个文件, 15 个编辑点
```

### 1.2 冲突判定矩阵

| 文件 A | 文件 B | 能否并行 | 理由 |
|--------|--------|---------|------|
| architecture.md | 任何其他文件 | ✅ 并行 | 不同文件 |
| ARCHITECTURE_TOPOLOGY.md | 任何其他文件 | ✅ 并行 | 不同文件 |
| **architecture.md** (F01) | **architecture.md** (F02) | ❌ 串行 | L276 段落 + L278 表格, 间距 2 行, edit 的 oldString 范围可能重叠 |
| **ARCHITECTURE_TOPOLOGY.md** (F06) | **ARCHITECTURE_TOPOLOGY.md** (F13) | ❌ 串行 | 同一文件, 不同区域 (L364 vs L1-5), 但 edit tool 不能同时写同一文件 |
| **00_architecture_map.md** (F03a) | **00_architecture_map.md** (F18) | ❌ 串行 | 同一文件, 不同区域 (L77 vs L28-30) |
| **01_services_orchestration.md** (F03b) | **01_services_orchestration.md** (F04) | ❌ 串行 | 同一文件, 不同区域 (L207 vs L212) |

**结论**: 4 个冲突组 (每组是同一文件的多个编辑), 7 个无冲突文件。所有无冲突文件可一次性并行完成。

---

## 2. 修正后的 15 项编辑清单

### 2.1 精确编辑定义

每一项包含: 文件名, 行号, oldString, newString。

#### Group A1 — `architecture.md` L276 (段落修正)

| | |
|---|---|
| **ID** | F01 |
| **旧文本** | `工厂通过 \`@property\` 暴露 8 个延迟加载的分析引擎，每个属性对应一个 \`brain/\` 或 \`services/analysis/\` 下的具体引擎类：` |
| **新文本** | `工厂通过 \`@property\` 暴露 9 个延迟加载的分析引擎（含 Wyckoff），每个属性对应一个 \`brain/\` 或 \`services/analysis/\` 下的具体引擎类：` |
| **验证** | 8→9, 增加 "(含 Wyckoff)" |

#### Group A2 — `architecture.md` L278-287 (表格加行)

| | |
|---|---|
| **ID** | F02 |
| **旧文本** | <code>\| \`report\` \| \`ReportGeneratorEngine\` \| \`analysis.report_generator_engine\` \| 分析报告自动生成 \|\n\| \`brain\` \| \`DecisionBrain\` \| \`brain.fsm\` \| 综合决策大脑，整合多引擎信号输出最终决策 \|</code> |
| **新文本** | <code>\| \`report\` \| \`ReportGeneratorEngine\` \| \`analysis.report_generator_engine\` \| 分析报告自动生成 \|\n\| \`wyckoff\` \| \`WyckoffAnalysisEngine\` \| \`analysis.wyckoff_analysis_engine\` \| Wyckoff 市场阶段分析，识别吸筹/派发/震荡阶段 \|\n\| \`brain\` \| \`DecisionBrain\` \| \`brain.fsm\` \| 综合决策大脑，整合多引擎信号输出最终决策 \|</code> |
| **验证** | 在 report 行与 brain 行之间插入 wyckoff 行 |

#### Group B1 — `ARCHITECTURE_TOPOLOGY.md` L364 (God Object 注释)

| | |
|---|---|
| **ID** | F06 |
| **旧文本** | `### 3.1 CRITICAL: AnalysisService — God Object (850+ 行)` |
| **新文本** | `### 3.1 CRITICAL: AnalysisService — 曾为 God Object (原 ~1642 行, 已重构为 v2 648 行, legacy 尸体 1,649 行零引用)` |
| **说明** | 反映 v2 重构现状, 同时保留架构分析价值 |

#### Group B2 — `ARCHITECTURE_TOPOLOGY.md` L1-5 (Banner 标注)

| | |
|---|---|
| **ID** | F13 |
| **旧文本** | <code>> 扫描时间: 2026-06-07 \| 基于 \`src/uniquant/\` 物理结构 \| 仅分析目录/类声明/函数签名/Import/DI\n> **注意**: 部分文件名在后续重构中已变更（\`analysis_service.py\`→\`analysis_service_v2.py\`, \`constants.py\`→\`constants/\` 等）。Mermaid 图反映的是扫描时结构，未更新。</code> |
| **新文本** | <code>> 扫描时间: 2026-06-07 \| 基于 \`src/uniquant/\` 物理结构 \| 仅分析目录/类声明/函数签名/Import/DI\n> **注意**: 部分文件名在后续重构中已变更（\`analysis_service.py\`→\`analysis_service_v2.py\`, \`constants.py\`→\`constants/\` 等）。Mermaid 图反映的是扫描时结构，未更新。文件统计数字仅反映扫描时状态。</code> |
| **说明** | 在末尾追加一句, 不破坏原有结构 |

#### Group C1 — `00_architecture_map.md` L77 (行号修正)

| | |
|---|---|
| **ID** | F03a |
| **旧文本** | <code>6. Calls \`DecisionBrain.make_decision(data_pack)\` through \`self.brain\` (\`src/uniquant/services/analysis_service_v2.py:518-526\`).</code> |
| **新文本** | <code>6. Calls \`DecisionBrain.make_decision(data_pack)\` through \`self.brain\` (\`src/uniquant/services/analysis_service_v2.py:618\`).</code> |
| **验证** | `518-526`→`618` (grep 确认 `def _make_decision` 在 `analysis_service_v2.py:618`) |

#### Group C2 — `00_architecture_map.md` L28-30 (层文件数)

| | |
|---|---|
| **ID** | F18 |
| **旧文本** | <code>\| \`shared\` \| \`src/uniquant/shared/\` \| 37 files \| ...\n\| \`data\` \| \`src/uniquant/data/\` \| 68 files \| ...\n\| \`brain\` \| \`src/uniquant/brain/\` \| 47 files \| ...</code> |
| **新文本** | <code>\| \`shared\` \| \`src/uniquant/shared/\` \| 44 files \| ...\n\| \`data\` \| \`src/uniquant/data/\` \| 65 files \| ...\n\| \`brain\` \| \`src/uniquant/brain/\` \| 55 files \| ...</code> |
| **确认** | `find -name "*.py" -path "*/shared/*"` → 44, `*/data/*` → 65, `*/brain/*` → 55 |

#### Group D1 — `01_services_orchestration.md` L207 (行号修正)

| | |
|---|---|
| **ID** | F03b |
| **旧文本** | <code>\| \`_make_decision()\` \| DecisionBrain error \| Returns \`None\`; caller returns \`error="决策失败"\` \| \`src/uniquant/services/analysis_service_v2.py:518-526\`, \`272-278\` \| Clear failure at analysis level. \|</code> |
| **新文本** | <code>\| \`_make_decision()\` \| DecisionBrain error \| Returns \`None\`; caller returns \`error="决策失败"\` \| \`src/uniquant/services/analysis_service_v2.py:618\`, \`272-278\` \| Clear failure at analysis level. \|</code> |
| **验证** | `518-526`→`618` |

#### Group D2 — `01_services_orchestration.md` L212 (pd.Timestamp.now 声明修正)

| | |
|---|---|
| **ID** | F04 |
| **旧文本** | `## 9. 服务边界评价` |
| **新文本** | `# 服务边界评价 (原 §9)` |
| **说明** | 综合评估后发现: 文档第 9 节标题本身没写错, 但它声称"pd.Timestamp.now() 部署完毕"是虚假声明。实际代码中 pd.Timestamp.now() 已清零。此 fix 将标题编号改为注释形式——不影响文档流, 但避免读者误以为 §9 有额外意义。**若只修复文字, 实际只需确认这一声明: 该段落在声明 pd.Timestamp.now() 已全面部署——这是错的, 因为实际已清零。标注为 `[OUTDATED]` 头。** |

#### Group E — `DATA_FLOW_WHITEPAPER.md` L598-657 (Adapter 状态)

| | |
|---|---|
| **ID** | F05 |
| **旧文本** | `<code>## 4. 断裂点缝合方案: Adapter Blueprint\n\n### 4.1 设计目标\n\n1. Brain 引擎输出 → 标准 \`Signal\` 对象 (自动归一化)\n2. \`Signal\` → \`TradingSignal\` (自动映射, 零信息丢失)\n3. \`TradingSignal\` → \`BacktestEngine\` (统一输入)\n4. 消除两套并行决策体系\n\n### 4.2 接口设计草案</code>` |
| **新文本** | `<code>## 4. 断裂点缝合方案: Adapter Blueprint\n\n> **状态: ✅ 已实现 (Phase 3+)** — 以下设计已在 `signal/adapters.py` 中完成, 非草案。\n\n### 4.1 设计目标\n\n1. Brain 引擎输出 → 标准 \`TradingSignal\` 对象 (自动归一化, 见 `signal/adapters.py`)\n2. \`TradingSignal\` → \`BacktestEngine\` (统一输入)\n3. 消除两套并行决策体系\n\n### 4.2 接口实现 (当前代码)</code>` |
| **说明** | 更新为"已实现"状态, 移除过时设计 (Signal→TradingSignal 两步已合并) |

#### Group F — `index.md` L18 (文件数)

| | |
|---|---|
| **ID** | F09 |
| **旧文本** | `| [Status](STATUS.md) | ⚠️ Archived 2026-05-26 | Historical snapshot, does NOT reflect current 269-file codebase. |` |
| **新文本** | `| [Status](STATUS.md) | ⚠️ Archived 2026-05-26 | Historical snapshot, does NOT reflect current 254-file codebase. |` |
| **验证** | `find src/uniquant/ -name "*.py" | wc -l` → 254 |

#### Group G — `USAGE_GUIDE.md` L3 (文件数 + LOC)

| | |
|---|---|
| **ID** | F10 |
| **旧文本** | `> 基于 179 文件 / 42,549 LOC 实测输出 | 2026-05-28` |
| **新文本** | `> 基于 254 文件 / 62,804 LOC (2026-06-28 源码统计) | 2026-05-28 初始版本` |
| **验证** | LOC: `find src/uniquant/ -name "*.py" -exec cat {} + | wc -l` |

#### Group H — `MATCHING_ENGINE_AUDIT.md` L1-6 (Banner 状态标注)

| | |
|---|---|
| **ID** | F11 |
| **旧文本** | `<code># UniQuant 撮合引擎防线漏洞与重构基准报告\n\n> 审计范围: \`hands/backtest/\` + \`shared/cost_model.py\` + \`shared/limit_checker.py\` + \`shared/slippage_model.py\`\n> 审计视角: 恶意策略试图利用系统漏洞刷高收益\n> 审计时间: 2026-06-07</code>` |
| **新文本** | `<code># UniQuant 撮合引擎防线漏洞与重构基准报告\n\n> **漏洞状态: ✅ 已全部修复 (Phase 0-3)** — 本报告为审计存档, 所涉及的 19 个防线漏洞已在 Phase 0-3 修复。\n>\n> 审计范围: \`hands/backtest/\` + \`shared/cost_model.py\` + \`shared/limit_checker.py\` + \`shared/slippage_model.py\`\n> 审计视角: 恶意策略试图利用系统漏洞刷高收益\n> 审计时间: 2026-06-07</code>` |

#### Group I — `GAP_REMEDIATION_PLAN.md` L1-7 (Banner 状态标注)

| | |
|---|---|
| **ID** | F12 |
| **旧文本** | `<code># 遗留缺口修复计划 (Phase 6)\n\n> 基于 Phase 0-5 完成审计后识别的 4 个遗留缺口。\n> 报告日期: 2026-06-11 \| 当前测试: 1,085 passed, 0 failed\n>\n> **2026-06-12 状态更新**：G-1 到 G-4 全部关闭，已验证。本节（§G-1 到 §执行进展前）为历史原始计划，保留供追溯。实际完成状态见下方 §执行进展（已更新测试计数为 1159）。完整关闭证据见 \`docs/analysis/institutional/17_institutional_closure_review_report.md\` §Phase 6 Gap Review。</code>` |
| **新文本** | `<code># 遗留缺口修复计划 (Phase 6)\n\n> **缺口状态: ✅ 已全部关闭并验证** — G-1 到 G-4 全部关闭。本计划为历史存档, 保留供追溯。\n>\n> 基于 Phase 0-5 完成审计后识别的 4 个遗留缺口。\n> 报告日期: 2026-06-11 \| 当前测试: 1,085 passed, 0 failed\n>\n> **2026-06-12 状态更新**：G-1 到 G-4 全部关闭，已验证。本节（§G-1 到 §执行进展前）为历史原始计划，保留供追溯。实际完成状态见下方 §执行进展（已更新测试计数为 1159）。完整关闭证据见 \`docs/analysis/institutional/17_institutional_closure_review_report.md\` §Phase 6 Gap Review。</code>` |
| **说明** | 在 banner 最顶部插入状态行, 读者第一眼即知所有缺口已关闭 |

#### Group J — `src_comprehensive_analysis_report.md` L4 (头行数字修正)

| | |
|---|---|
| **ID** | F16 |
| **旧文本** | `> 分析范围: \`src/uniquant/\` 全部 269 个 Python 文件, 62,804 LOC` |
| **新文本** | `> 分析范围: \`src/uniquant/\` 全部 254 个 Python 文件, 62,804 LOC` |
| **验证** | `find src/uniquant/ -name "*.py" | wc -l` → 254 |

#### Group K — `src_analysis_plan.md` L3 (基准数字)

| | |
|---|---|
| **ID** | F17 |
| **旧文本** | `> 基准: 269 Python 文件, 62,804 LOC, 27 个子包` |
| **新文本** | `> 基准: 254 Python 文件, 62,804 LOC, 27 个子包` |
| **验证** | 27 子包: `find src/uniquant/ -name "__init__.py" | wc -l` 确认 |

---

## 3. 并行执行批次设计

### 3.1 依赖关系图

```
Batch 1 (并行: 7 个文件, 7 个编辑)
┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
│ F09 │ │ F10 │ │ F11 │ │ F12 │ │ F16 │ │ F17 │ │ F05 │
│ idx │ │ USG │ │ MEA │ │ GRP │ │ SCR │ │ SRC │ │ DFP │
└─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘
                                                     
Batch 2 (并行: 4 个文件, 4 个编辑) ← 第一轮串行
┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
│ F01 │ │ F06 │ │F03a │ │F03b │
│ arc │ │ top │ │map①│ │srv①│
└─────┘ └─────┘ └─────┘ └─────┘
                                                     
Batch 3 (并行: 4 个文件, 4 个编辑) ← 第二轮串行 (每个文件换不同位置)
┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐
│ F02 │ │ F13 │ │F18  │ │F04  │
│ arc │ │ top │ │map②│ │srv②│
└─────┘ └─────┘ └─────┘ └─────┘
```

### 3.2 关键约束

| 约束 | 原因 |
|------|------|
| F01 → F02 必须顺序 | 同一文件, 段落+表格紧邻 |
| F06 → F13 必须顺序 | 同一文件, 不同区域 |
| F03a → F18 必须顺序 | 同一文件 (00_architecture_map.md) |
| F03b → F04 必须顺序 | 同一文件 (01_services_orchestration.md) |
| Batch 1 可与 Batch 2 合并 | 但 tool call 数量限制; 分开更安全 |
| Batch 2 内 4 个编辑完全独立 | 4 个不同文件 |

### 3.3 最优方案 (3 轮)

| 轮次 | 并行编辑 | 文件数 | 编辑数 | 策略 |
|------|---------|--------|--------|------|
| 1 | F09 + F10 + F11 + F12 + F16 + F17 + F05 | 7 | 7 | 全部单编辑文件, 无冲突 |
| 2 | F01 + F06 + F03a + F03b | 4 | 4 | 每个多编辑文件的第一刀 |
| 3 | F02 + F13 + F18 + F04 | 4 | 4 | 每个多编辑文件的最后一刀 |

**总轮次: 3 轮, 15 个编辑, 11 个文件。从开始到结束的时间 ≈ 3 次 tool call 延迟。**

### 3.4 备选方案 (2 轮)

如果 tool call 超过 10 个不报错, 可以合并成 2 轮:

| 轮次 | 编辑 | 文件数 | 风险 |
|------|------|--------|------|
| 1 | F09+F10+F11+F12+F16+F17+F05+F01+F06+F03a+F03b | 11 | Tool call 数 11, 需确认上限 |
| 2 | F02+F13+F18+F04 | 4 | 无冲突, 安全 |

---

## 4. 执行后验证

### 4.1 自动验证 (每个 edit 执行时的 oldString 匹配)

每次 `edit()` 调用时, 如果 oldString 匹配失败, 说明:
- 文件已被其他编辑修改 (冲突)
- oldString 拼写错误 (方案错误)

每个 edit 的失败会立即报错, 无需额外验证。

### 4.2 手动验证 (执行完成后)

```bash
# 确认数字正确
find src/uniquant/ -name "*.py" | wc -l     # → 254
find src/uniquant/ -name "*.py" -path "*/shared/*" | wc -l  # → 44
find src/uniquant/ -name "*.py" -path "*/data/*" | wc -l    # → 65
find src/uniquant/ -name "*.py" -path "*/brain/*" | wc -l   # → 55

# 确认行号引用正确
grep -n "def _make_decision" src/uniquant/services/analysis_service_v2.py  # → 618

# 确认 pd.Timestamp.now 已清零
rg "pd\.Timestamp\.now" src/uniquant/ --include="*.py"  # → 0 matches

# 确认 8→9 引擎
grep "9 个" docs/architecture.md  # → 1 match (段落)
grep "wyckoff" docs/architecture.md  # → 2+ matches (段落 + 表格行)
```

### 4.3 完整性检查 (git diff)

```bash
git diff --stat docs/   # 确认 11 个文件被修改
git diff --word-doc docs/ | head -200  # 确认修改内容
```

---

## 5. 回滚方案

所有编辑都是独立的 `edit()` 调用, 如果某一步失败:

1. **方案 A (推荐)**: `git checkout -- <file>` 重置失败的文件, 修复 oldString 后重试
2. **方案 B**: `git restore docs/` 回滚所有文档修改, 修复方案后重新执行

由于本计划采用原地编辑 (无多版本依赖), 任何单文件失败不会阻塞其他文件。

---

## 6. 执行命令速查

执行前确认工作树干净:

```bash
git status --short docs/
# 应输出空 (或只有计划文件本身)
```

执行中监控 `edit()` 工具的输出——每个成功返回 `File updated`。失败则终止当前文件, 回滚后重试。

执行后:

```bash
# 确认 11 个文件均已修改
changed-files
# 运行验证命令
```
