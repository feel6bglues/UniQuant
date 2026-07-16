# v6 遗留项目根因分析

> **生成**: 2026-07-13 | **基于**: 逐文件源代码核实 + 执行轨迹回溯
> **范围**: 8 项已执行修复的阻断因素复盘 + 7 项遗留修复的根因分析

---

## 第 1 章: 执行总览

| 阶段 | 计划 | 已执行 | 遗留 | 执行率 |
|:-----|:----:|:------:|:----:|:-----:|
| R0 (关键修复) | 4 | 4 | 0 | **100%** |
| R1 (工程健康) | 8 | 3 | 5 | 37.5% |
| R2 (文档对齐) | 4 | 1 | 3 | 25% |
| R3 (测试补全) | 3 | 1 | 2 | 33% |
| **总计** | **19** | **9** | **10** | **47%** |

> 注: 原 v6 清单 15 项, 执行中拆解为 19 子项。9 项已完成, 10 项遗留。

---

## 第 2 章: 已执行项的阻断因素复盘

### 2.1 R0-N02: `factor_governance.py` 归档

| 维度 | 内容 |
|:-----|:------|
| **预期** | 5m: 直接 mv 到 archive/ |
| **实际耗时** | **15m** (3x 预期) |
| **阻断事件** | (1) 文件含相对导入 `from ..brain.factors.registry` → 移动后包路径改变, ModuleNotFoundError; (2) 涉及 2 个测试文件需更新导入路径; (3) archive/ 缺 `__init__.py` |
| **根因** | 相对导入 + 缺少 archive 包初始化 + 测试耦合 |
| **经验** | 归档含相对导入的文件必须重构为绝对导入; 需同步扫描 `grep -rn` 外部引用 |

### 2.2 R0-N03: `portfolio_engine.py` 归档

| 维度 | 内容 |
|:-----|:------|
| **预期** | 10m |
| **实际耗时** | **20m** (2x 预期) |
| **阻断事件** | (1) 5 个相对导入全部需转绝对导入; (2) 4 个测试文件需更新 (test_portfolio_engine_v2.py + test_e2e_integration_qa.py 3 处); (3) 1 个 import chain 测试 `test_e2e_integration_qa.py:92`; (4) 需新建 `hands/backtest/archive/__init__.py` |
| **根因** | 相对导入多 (5处) + 测试覆盖广 (5个测试点) + archive 目录不完整 |
| **经验** | 多测试点文件归档需系统性扫描所有引用, 含 import chain 测试 |

### 2.3 R0-N04: `signal/__init__.py` 导出补全

| 维度 | 内容 |
|:-----|:------|
| **预期** | 5m |
| **实际耗时** | **3m** (预期内) |
| **阻断事件** | 无。仅需读 `adapters.py` 确认 3 个类存在, 添加导入 + `__all__` |
| **根因** | 独立文件, 无相对导入问题, 无测试依赖 |
| **经验** | 纯 `__all__` 补全是零风险操作 |

### 2.4 R1-N04: `arbitrator.py:385` bare except 加 logging

| 维度 | 内容 |
|:-----|:------|
| **预期** | 2m |
| **实际耗时** | **2m** (预期内) |
| **阻断事件** | 无。`logger` 已在文件头初始化, 仅需改 1 行 |
| **根因** | 独立文件, 零测试依赖 |
| **经验** | 已有 logger 的 bare except 修复是零风险操作 |

### 2.5 R3-N03: `lppl_visualizer.py:27,39` — WONTFIX 确认

| 维度 | 内容 |
|:-----|:------|
| **预期** | 5m |
| **实际耗时** | **2m** (读代码确认) |
| **阻断事件** | 无。代码已有 `logger.warning(..., exc_info=True)`, 属可接受的 UI 层防御编程 |
| **根因** | Streamlit UI 层设计上使用宽 except 防止崩溃 |
| **经验** | 提前确认现有代码状态可避免不必要修改 |

---

## 第 3 章: 10 项遗留修复根因分析

---

### 遗留项 1: R1-06 过户费 DRY 统一 — 阻塞原因: 向量化/标量签名不兼容

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 3 处重复, 需统一至 cost_model 单点, 30m |
| **源代码核实** | **实际只有 2 处重复, 且向量化签名不兼容**: (1) `cost_model.py:48` `_has_transfer_fee(symbol: str) -> bool` 标量, (2) `unified_matching_engine.py:186` `np.array([s.startswith("60") for s in symbols])` 向量化。`strategies/backtest.py:167` 的 `startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302"))` **非过户费检查** — 是股票代码有效性过滤器, 用于 CSI300 成分股筛选, 包含深市代码 |
| **阻塞根因** | **语义差异**: cost_model 和 matching_engine 的 `startswith("60")` 是过户费检查 (仅沪市), 但 backtest.py 的前缀列表涵盖沪深两市, 用于完全不同的目的。**API 签名不兼容**: cost_model 用标量 `str -> bool`, matching_engine 用 `np.array -> np.array`。要统一需: (1) 给 `_has_transfer_fee` 增加向量化重载, (2) 或让 matching_engine 导入并逐元素调用标量版。前者增加复杂度, 后者降低性能 |
| **风险评估** | **修改有风险**: 过户费是 A 股防线之一, 错误修改会导致回测成本计算错误。当前两种实现逻辑一致 (`60xxx` = 沪市 = 收费), 无功能性 bug |
| **建议路径** | 方案 A (5m) — 添加注释说明两个实现位置, 不做代码修改。方案 B (1h) — 在 cost_model 中增加 `_has_transfer_fee_batch(symbols) -> np.ndarray`, 让 matching_engine 导入使用。推荐方案 A |
| **优先级** | LOW — 无功能性 bug, 仅为 DRY 原则 |

---

### 遗留项 2: R3-N01 45 文件零覆盖 — 阻塞原因: 规模大且需基建准备

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | ~16h (45 文件 × 20m/文件) |
| **源代码核实** | 45 文件, 3,791 LOC, 分层: data/ 17 文件 2,264 LOC (含 tdx_updater 379, update_daily_incremental 351, eastmoney 全系 4 文件 488, 脚本 8 文件 1,270); brain/LPPL 6 文件 531 LOC (computation 242, multifit 106, cluster 68); hands/strategies 6 文件 347 LOC; shared 6 文件 192 LOC; services 3 文件 35 LOC; ui 7 文件 ~1,228 LOC (覆盖率排除) |
| **阻塞根因** | **三重制约**: (1) 数据层脚本依赖网络/数据库, 需 mock 基础设施 — 需新建 conftest.py 和 fixture 工厂; (2) 16h 连续投入在当前工程周期中不可行 — 需拆分为 4+ 个 batch 分阶段执行; (3) brain/LPPL computation.py (242 LOC) 是数值拟合核心, 需要构造已知解的测试数据, 非简单冒烟测试 |
| **风险评估** | **高**: 数据管道无测试覆盖意味着 CI 无法捕获数据读取/转换回归 bug。LPPL 核心算法无测试意味着拟合质量退化不可检测 |
| **建议路径** | Batch 1 (30m) — data/scripts 冒烟测试 (验证 init 不抛异常); Batch 2 (2h) — brain/LPPL 已知解回归测试; Batch 3 (4h) — hands/strategies 策略边界测试; Batch 4 (1h) — shared/optimal_params + others. 总计 ~8h (减半估算) |
| **优先级** | **HIGH** — 最大测试缺口 |

---

### 遗留项 3: R3-N02 manager_logic.py 6 处 `except Exception` — 阻塞原因: 已是最佳实践模式

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 6 处裸 except, 需窄化, 30m |
| **源代码核实** | **全部 6 处已有 `as e` 和 `logger.*(..., exc_info=True)`**。且模式是: 先捕获具体类型 `(RuntimeError, IOError, KeyError)`, 再用 `except Exception as e:` 兜底。这是**正确的防御编程模式** (narrow-first, broad-last)。行 343 是 FSM 分析兜底, 行 444-484 是 Streamlit 回调保护 |
| **阻塞根因** | **误诊**: 实际代码质量好于文档声称。无法进一步改进 (窄化会漏捕获, 加 logging 已有, exc_info 已有) |
| **风险评估** | 无 — 现有代码已是最佳实践 |
| **建议路径** | WONTFIX — 更新文档反映实际代码状态 |
| **优先级** | **LOW (已满足)** |

---

### 遗留项 4: R1-N01 Wyckoff 复杂度文档 40→45 — 阻塞原因: 度量工具不一致

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 文档称 40, radon 显示 53, 自定义 AST 显示 45 |
| **源代码核实** | `_step5_trading_plan` 在 `brain/wyckoff/engine.py`。不同工具给出不同值: radon (McCabe) = 53, 自定义 AST = 45, 项目文档 = 40。差异来源: radon 计入 `elif` 和 `and/or` 分支, 部分 AST 实现不计数 |
| **阻塞根因** | **无标准度量工具**: 项目未指定使用的复杂度工具。AGENTS.md 已使用"自定义 AST 45"。要最终确定需要: (1) 统一选择 radon 作为项目标准, (2) 更新所有文档为 53, (3) 决策是否重构拆分 (从 53 降到 20) |
| **风险评估** | **低** — 复杂度值本身不影响功能, 仅影响健康度评估 |
| **建议路径** | 统一 radon 作为项目复杂度标准, 更新所有文档为 53。重构拆分是独立 P2 任务 |
| **优先级** | LOW |

---

### 遗留项 5: R1-N07 Alpha score=0.0 位置 2→3 — 阻塞原因: 文档批量同步耗时

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 文档说 2 处 (543,552), 实际 3 处 (含 535), 需 2m |
| **源代码核实** | `analysis_service_v2.py:535,543,552` 三处均已确认。`F_verified_task_list.md` 和 `E_red_blue_analysis.md` 已正确列出 3 处, 但 `Z_tdd_redblue_consolidated_report_20260710.md` 仍写 "lines 543, 552" (2 处) |
| **阻塞根因** | **文档数量多**: 20+ 文档文件需要逐个 grep 检查, 再逐个修正。虽然每处修只需 1m, 但扫描 + 确认 + 修改的序列化开销 ~20m |
| **建议路径** | 用 `grep -rn "lines 543.*552\|score=0.0.*543" docs/` 定位所有过期引用, 批量 sed 修正 |
| **优先级** | LOW — 无功能影响 |

---

### 遗留项 6: R1-N02 数据源 7→8 — 阻塞原因: 多文档历史遗留

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 8 DataSource 子类 (非 7), 需更新所有文档 |
| **源代码核实** | 8 个子类: BaostockSource, EastmoneySource, MootdxLocalSource, MootdxOnlineSource, SinaSource, TdxSource, TencentSource, ThsSource。MootdxLocal + MootdxOnline 在 `architecture.md` 中被合并计数为 1 ("mootdx 有 2 实现") |
| **阻塞根因** | 架构文档的计数方法不同 (按"数据源类型"而非"DataSource 子类"). 将 mootdx 的 2 个实现合并计数为 1 种"mootdx 数据源"有合理依据。需要统一计数规则再更新 |
| **建议路径** | 决策: 按"数据源类型"(7 种) 还是按"子类"(8 个)。推荐统一为"8 个 DataSource 子类", 将 mootdx 拆为 2 个独立计数 |
| **优先级** | LOW — 语义差异, 无功能影响 |

---

### 遗留项 7: R1-N08 Wyckoff 4 文件 1,135→1,154 LOC — 阻塞原因: 无更新触发器

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 文档 1,135, 实际 1,154, 差 19 LOC (1.7%), 需 2m |
| **源代码核实** | `analysis.py:322 + state.py:296 + events.py:517 + constants.py:19 = 1,154` |
| **阻塞根因** | **无自动化验证**: 文档 LOC 值被硬编码在 AGENTS.md 和报告文件中, 每次代码修改都会漂移, 但无 CI 门禁捕获 |
| **建议路径** | 添加到 CI 门禁: `docs/reanalysis/I_live_system_map.md` 中文件级 LOC 自动验证。现在修了下次改代码还会漂移 |
| **优先级** | LOW — 1.7% 偏差可忽略 |

---

### 遗留项 8: R2-N01 死代码库存全量更新 — 阻塞原因: 已部分完成, 剩余全量扫描

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 新发现 532 LOC, 需更新死代码库存 |
| **源代码核实** | AGENTS.md 已更新为 "Archived files = 6 (2,217 LOC)"。但 `I_live_system_map.md`、`J_scorecard.md`、`A_code_quality.md` 等仍引用旧值 ~2,225 LOC |
| **阻塞根因** | 多个文档文件需同步更新。AGENTS.md 已更新 (关键入口), 其余报告文件是历史快照, 更新优先级低 |
| **建议路径** | 更新 `I_live_system_map.md` 死代码表, 其余历史报告可标注 "superseded by v6" |
| **优先级** | LOW (关键入口已更新) |

---

### 遗留项 9: R2-N02 Wyckoff 文档覆盖 4/18 文件 — 阻塞原因: 架构文档重写

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | Wyckoff 有 18 个非 __init__ 文件 (7,133 LOC), 文档仅提 4 个 |
| **源代码核实** | 确凿。Wyckoff 是 brain 层最大子包 (44%), 含 engine 1,616 LOC、models 820 LOC、phase_analysis 506 LOC、fusion_engine 469 LOC 等 |
| **阻塞根因** | 这不是 5m 的文档修正, 而是一次架构文档的重写。需要: (1) 理解 18 个文件的职责, (2) 绘制子模块关系图, (3) 更新所有引用 Wyckoff 架构的文档。估算 2-4h |
| **建议路径** | 推迟到专门的文档 sprint, 与 `docs/analysis/wyckoff_research_report.md` 对齐 |
| **优先级** | LOW — 不影响功能, 仅影响新开发者上手速度 |

---

### 遗留项 10: R2-N03 interfaces.py 协议 4→5 — 阻塞原因: 同 R1-N07 (文档批量同步)

| 字段 | 内容 |
|:----|:------|
| **v6 声称** | 文档称 4 protocols, 实际 interfaces.py 有 5 个 (含 CalculationPluginProtocol) |
| **源代码核实** | `interfaces.py:466,487,507,538,559` — DataFetcherProtocol, RiskAssessmentProtocol, PositionSizerProtocol, AnalysisEngineProtocol, CalculationPluginProtocol。+ TimeProvider 在 `time_provider.py:24` (共用 6 个) |
| **阻塞根因** | 同 R1-N07 — 批量文档同步的序列化开销 |
| **建议路径** | 与 R1-N07 一起在文档 sprint 中批量处理 |
| **优先级** | LOW |

---

## 第 4 章: 遗留项分层汇总

| 层级 | 遗留项 | 阻塞类型 | 真实工时 | 可并行? |
|:-----|:-------|:---------|:-------:|:-------:|
| **不需要改 (WONTFIX)** | R3-N02 (manager_logic except), R1-06 (过户费DRY) | 误诊/签名不兼容 | 0 | — |
| **已部分完成** | R2-N01 (死代码库存) | AGENTS.md 已更新, 历史报告待同步 | 15m | ✅ |
| **纯文档批量更新** | R1-N07 (alpha位置), R1-N02 (8数据源), R1-N08 (1,154 LOC), R2-N03 (5协议), R1-N01 (复杂度工具) | 20+ 文档文件需同步, 序列化扫描开销 | 1.5h 一次性 | ✅ 可合并 |
| **架构文档重写** | R2-N02 (Wyckoff 18文件) | 需理解 + 绘图 + 对齐, 非简单数字修改 | 2-4h | ❌ 需独立 sprint |
| **大规模测试工程** | R3-N01 (45文件0覆盖) | 依赖 mock 基础设施 + 已知解构造 + 多 batch 串行 | ~8h | ⚠️ 可拆 4 batch |

**净工作量**: WONTFIX(0) + 已部分完成(15m) + 文档批量(1.5h) + 架构重写(2-4h) + 测试工程(~8h) = **~12-14h 总遗留**

---

## 第 5 章: 关键经验教训

### 5.1 3 项误诊 (应避免重犯)

| 项 | v6 声称 | 实际代码状态 |
|:---|:--------|:------------|
| R1-06 (过户费 3 处) | 3 处重复, 需统一 | 2 处过户费 (语义一致) + 1 处股票过滤器 (不同语义) |
| R3-N02 (manager_logic 裸 except) | 6 处裸捕获 | 全部已有 `as e` + `exc_info=True`, 且 narrow-first 模式 |
| R3-N03 (lppl_visualizer bare except) | 丢弃异常上下文 | 已有 `exc_info=True` |

**原因**: 未在分析阶段逐行读取每个 except 处理器的完整上下文 (arg, logging 调用, exc_info 参数)。

### 5.2 3 项低估 (未来需调整估算因子)

| 项 | 估算 | 实际 | 偏差 | 原因 |
|:---|:----:|:----:|:----:|:-----|
| factor_governance 归档 | 5m | 15m | 3x | 未预判相对导入 + 测试更新 |
| portfolio_engine 归档 | 10m | 20m | 2x | 未预判 import chain 测试 |
| 文档批量更新 | 2m/项 | 20m | 10x | 未计入 20+ 文档的扫描开销 |

### 5.3 无阻塞但需串行的项

| 项 | 串行原因 |
|:---|:---------|
| R3-N01 Batch 1→4 | 每个 batch 产出需通过 pytest 才进入下一个 |
| R2-N02 Wyckoff 文档重构 | 需先读 18 个文件 → 绘制关系图 → 更新文档 |

---

## 第 6 章: 执行建议路径

```
Phase W (0h) ─ WONTFIX 确认
  R3-N02 → 关闭 (已有 as e + exc_info)
  R1-06  → 关闭 (向量化签名不兼容, 无功能性bug)

Phase D (1.5h) ─ 文档批量 sprint
  Step 1: grep 扫描全部文档中过期引用        [15m]
  Step 2: 批量修正 5 项数字 (alpha位置/DataSource/LOC/协议/复杂度)  [30m]
  Step 3: 更新 I_live_system_map.md 死代码表  [15m]
  Step 4: 在 CI 中加入 LOC/复杂度验证门禁     [30m]

Phase W2 (2-4h) ─ Wyckoff 架构文档 sprint
  Step 1: 读 18 个文件, 提取职责             [1h]
  Step 2: 绘制子模块关系图                    [1h]
  Step 3: 更新 docs/ 中所有 Wyckoff 引用      [1-2h]

Phase T (~8h) ─ 测试补全 sprint
  Batch 1: data/scripts 冒烟测试             [30m]
  Batch 2: brain/LPPL 已知解回归测试          [2h]
  Batch 3: hands/strategies 边界测试         [4h]
  Batch 4: shared/optimal_params 参数测试    [1h]
```

---

## 总结

10 项遗留中:
- **3 项 WONTFIX**: 误诊, 代码已好于声称 (manager_logic, lppl_visualizer) 或有合理工程理由 (过户费 DRY)
- **5 项纯文档**: 仅需批量同步, ~1.5h (alpha位置, 数据源, LOC, 协议, 复杂度)
- **1 项架构文档**: 需独立 sprint 2-4h (Wyckoff 子模块)
- **1 项大规模测试**: ~8h (45 文件零覆盖)

**净有效遗留**: 1 项工程 (测试补全 ~8h) + 1 项架构 (文档重写 2-4h) + 1 项杂项 (文档批量 ~1.5h) = **~12-14h**

阻塞类型分布: 误诊 30% | 签名不兼容 10% | 规模过大 30% | 文档批量开销 30%