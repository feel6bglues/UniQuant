# 3 轮红蓝对抗分析报告 — v6 工作计划

> **生成**: 2026-07-13 | **方法**: 逐源代码核实 + 推理链验证 + 跨文档交叉检查
> **目标文档**: `docs/remediation/v6_work_plan_verified.md`
> **总声明数**: 42 | **RED (错误)**: 9 | **YELLOW (需修正)**: 5 | **GREEN (正确)**: 28

---

## Round 1: 表面声明核实 (文件路径、行号、存在性)

### 方法

逐一对计划中所有文件路径、行号引用、存在性声明进行 `ls` / `sed -n` / `wc -l` 验证。

### 结果: 12 声明 → 3 RED

| # | 声明 | 文件:行 | 判决 | 证据 |
|:-:|:-----|:--------|:----:|:-----|
| 1 | `cost_model.py:48` 存在 | `cost_model.py:48` | ✅ | `def _has_transfer_fee(symbol: str) -> bool:` |
| 2 | `matching_engine.py:186` 存在 | `matching_engine.py:186` | ✅ | `sh_mask = np.array([s.startswith("60") ...` |
| 3 | `matching_engine.py:275` 存在 | `matching_engine.py:275` | ✅ | 同上 |
| 4 | `backtest.py:167` 非过户费 | `backtest.py:167` | ✅ | 前缀含深市代码, CSI300 筛选 |
| 5 | `manager_logic.py:343` as e + exc_info | `manager_logic.py:344` | ✅ | `logger.critical(..., exc_info=True)` |
| 6 | `lppl_visualizer.py:27,39` exc_info | `lppl_visualizer.py:28,40` | ✅ | `logger.warning(..., exc_info=True)` |
| 7 | **`optimal_params.py` 142 LOC** | `optimal_params.py` | ❌ **RED** | 实际 **488 LOC** (+243%) |
| 8 | **`update_daily_incremental.py` 351 LOC** | `update_daily_incremental.py` | ❌ **RED** | 实际 **532 LOC** (+52%) |
| 9 | **`tdx_updater.py` 379 LOC** | `tdx_updater.py` | ❌ **RED** | 实际 **644 LOC** (+70%) |
| 10 | `Z_tdd_redblue.md:165` "242 LOC" | line 165 | ✅ | 内容确为 "242 LOC" |
| 11 | `Z_tdd_redblue.md:55` "4 protocols" | line 55 | ✅ | 内容确为 "4 protocols" |
| 12 | `Z_tdd_redblue.md:69` "7 数据源" | line 69 | ✅ | 内容确为 "7 数据源" |

### Round 1 结论

**3 项 LOC 值严重错误** — 全部从 v5 修复清单继承未重新验证。optimal_params.py 偏差 243%，将导致 Batch 4 工时低估 2-3x。

---

## Round 2: 深层逻辑核实 (推理链是否成立)

### 方法

对计划的核心推理链逐环节验证: (1) 过户费 DRY 的"2 处实现"声明; (2) coverage 提升至 55% 的承诺; (3) Wyckoff 架构图的依赖关系准确性。

### 结果: 14 声明 → 4 RED + 2 YELLOW

#### 2.1 过户费 DRY 推理链

| # | 声明 | 判决 | 证据 |
|:-:|:-----|:----:|:-----|
| 13 | "2 处过户费实现" | ❌ **RED** | **实际 4 处**: (1) `cost_model.py:48` 定义 + line 61,147,153 调用; (2) `unified_engine.py:34` 导入 + line 593 调用 — **计划漏计此引擎层**; (3) `matching_engine.py:186` 买方向量; (4) `matching_engine.py:275` 卖方向量 |
| 14 | "backtest.py:167 非过户费" | ✅ | CSI300 股票池筛选, 前缀含 `000,001,002,...` 深市代码 |
| 15 | "向量化/标量签名不兼容" | ✅ | cost_model: `str→bool`, matching_engine: `np.array→np.array` |
| 16 | "WONTFIX 合理" | ⚠️ **YELLOW** | 虽然签名不兼容, 但 `unified_engine.py:593` 也用了 `_has_transfer_fee`, 它是标量版。matching_engine 的 buy/sell 也可用逐元素调用标量版。不是必须 WONTFIX, 有统一可能 |

**关键纠正**: 计划称 "2 处实现, 签名不兼容→WONTFIX", 但实际 **4 处**且 `unified_engine.py` 的标量版证明逐元素调用可行。matching_engine 也可改用 `np.vectorize(_has_transfer_fee)(symbols)`。WONTFIX 结论仍合理但理由不完整。

#### 2.2 Coverage 提升推理链

| # | 声明 | 判决 | 证据 |
|:-:|:-----|:----:|:-----|
| 17 | "45 文件 3,791 LOC 零覆盖" | ✅ | AGENTS.md 确认 |
| 18 | "Batch 1-4 覆盖 ~50% 文件" | ⚠️ **YELLOW** | 实际: 8 data scripts 1,957 LOC (计划说 1,270, +54%), 冒烟测试覆盖极低 |
| 19 | "coverage 从 52.74% 升到 55%" | ❌ **RED** | **实际估计 54.2-54.8%**: 可有效覆盖的仅 brain/LPPL (531) + hands/strategies (347) + shared (192) = ~1,070 LOC, 占未覆盖 28,500 的 3.8% → +0.8-1.5%. data scripts (1,957) + tdx_updater (644) + eastmoney (488) = 3,089 LOC 几乎无覆盖收益. 55% 门禁可能无法达成 |
| 20 | "def test_scripts_import() 充分" | ❌ **RED** | `import` + `callable(main)` 对 532 LOC 的 update_daily_incremental.py 覆盖率贡献 ≈0%. 需要对主要分支加断言 |

#### 2.3 Wyckoff 架构关系推理链

| # | 声明 | 判决 | 证据 |
|:-:|:-----|:----:|:-----|
| 21 | "18 非 __init__ 文件, 7,133 LOC" | ✅ | `find ... -exec wc -l` 确认 |
| 22 | "engine.py 依赖 analysis, state, events, rules" | ❌ **RED** | 遗漏 4 个: `classifiers` (line 35), `pnf` (line 70), `phase_analysis` (line 71), `indicators` (line 72). 实际依赖 **8 个** Wyckoff 子模块 + 1 个外部 |
| 23 | "fusion_engine.py 仅依赖 models" | ✅ | `fusion_engine.py` import 仅指向 `models` |
| 24 | "AGENTS.md 仅提 4 Wyckoff 文件" | ✅ | AGENTS.md #49 列 4 文件, 层表无子模块 |
| 25 | "4h 架构重写" | ⚠️ **YELLOW** | 基于 18 文件 + 8 条依赖关系 + 更新 3 文档, 4h 合理但依赖关系复杂度被低估 |
| 26 | "ASCII 架构图足够" | ✅ | 对文档目的足够 |

### Round 2 结论

**4 RED**: 过户费计 2 实 4、coverage 55% 不可达、脚本测试策略无效、Wyckoff 依赖遗漏 4 个。
**2 YELLOW**: 过户费 WONTFIX 理由不完整、Batch 4 optimal_params 工时低估。

---

## Round 3: 跨文档一致性 + 边缘案例

### 方法

(1) 交叉检查计划中数字与全文档集的一致性; (2) 挖掘边界条件: 目录存在性、LOC 累计值、incremental 测试策略可执行性。

### 结果: 16 声明 → 2 RED + 3 YELLOW

#### 3.1 跨文档一致性

| # | 声明 | 判决 | 证据 |
|:-:|:-----|:----:|:-----|
| 27 | "AGENTS.md 覆盖率 52.74%" | ✅ | AGENTS.md:34 确为 52.74% |
| 28 | "B-2 #6 死代码 2,225→2,217" | ✅ | `find .../archive/*.py wc -l` = 2,217 |
| 29 | "Z_tdd_redblue.md 含 4 项过期" | ✅ | 4 项全部确认 |
| 30 | "Z_redblue_comprehensive.md 含过期死代码" | ✅ | line 35,304,331,344 有 "2,225" |
| 31 | "v5_work_list.md 含过期死代码" | ✅ | line 149,222 有 "2,225" |
| 32 | "Wyckoff 文档重写影响 3 文档" | ✅ | AGENTS.md + I_live_system_map.md + wyckoff_research_report.md |

#### 3.2 边缘案例

| # | 声明 | 判决 | 证据 |
|:-:|:-----|:----:|:-----|
| 33 | "新建 test_scripts_smoke.py" | ⚠️ **YELLOW** | `tests/data/` 目录不存在, 计划未提及需 `mkdir -p` |
| 34 | "新建 test_computation_regression.py" | ⚠️ **YELLOW** | `tests/brain/lppl/` 目录不存在 |
| 35 | "新建 test_strategy_boundaries.py" | ⚠️ **YELLOW** | `tests/hands/strategies/` 目录不存在 |
| 36 | "8 data scripts = 1,270 LOC" | ❌ **RED** | 实际 **1,957 LOC** (+54%). 批量测试工时需从 30m 调到 45m |
| 37 | "coverage 门禁 55%" | ❌ **RED** | 基于 1,070 LOC 有效覆盖估算, 仅达 54.5%. 门禁应设 **54%** |
| 38 | ".coverage 数据时效" | ✅ | 2026-07-10, 旧但可接受作为基线 |
| 39 | "A-1 交叉引用注释无风险" | ✅ | 纯注释修改, 无功能影响 |
| 40 | "B-1 全局扫描命令可用" | ✅ | `grep -rn` 命令路径均存在 |
| 41 | "C-1 18 文件清单完整" | ✅ | 与 `ls` 输出一致 |
| 42 | "D-6 覆盖率验证命令正确" | ✅ | `pytest --cov=src/uniquant/ --cov-report=term-missing` 语法正确 |

### Round 3 结论

**2 RED**: data scripts LOC 偏差 54%, coverage 门禁需降到 54%。
**3 YELLOW**: 3 个新建测试目录不存在, 需增加 `mkdir` 步骤。

---

## 最终评分

| 维度 | 得分 | 说明 |
|:-----|:----:|:------|
| 文件路径准确性 | 12/12 ✅ | 全部存在 |
| 行号准确性 | 9/9 ✅ | 全部匹配 |
| **LOC 准确性** | **1/4 ❌** | **3/4 偏差 >50%, 从 v5 继承未验** |
| 推理链完整性 | 6/8 ⚠️ | 过户费计漏、Wyckoff 依赖计漏 |
| 覆盖率预测 | 0/2 ❌ | 55% 不可达 |
| 跨文档一致性 | 6/6 ✅ | 过期引用全部确认 |
| 边缘案例覆盖 | 2/5 ⚠️ | 缺目录创建、LOC 偏差、门禁过高 |

**综合: 57% GREEN, 24% YELLOW, 19% RED**

---

## 要求修正清单 (计划输出前必须修正)

### MUST FIX (4 项 — 直接影响执行)

| # | 位置 | 错误 | 修正 |
|:-:|:-----|:-----|:-----|
| 1 | D-5 Batch 4 | optimal_params.py 142 LOC | → **488 LOC**, 工时 1h → **2h** |
| 2 | D-2 Batch 1 说明 | data scripts "1,270 LOC" | → **1,957 LOC**, 工时 30m → **45m** |
| 3 | D-6 验收门禁 | coverage 55% | → **54%** (实际可达 ~54.5%) |
| 4 | D-2~D-4 新建测试 | 目录不存在 | 加 "`mkdir -p tests/data/ tests/brain/lppl/ tests/hands/strategies/`" |

### SHOULD FIX (5 项 — 改进计划质量)

| # | 位置 | 问题 | 修正 |
|:-:|:-----|:-----|:-----|
| 5 | A-1 过户费 | "2 处" → 实际 4 处 | 更新说明: cost_model + unified_engine + matching_engine buy/sell |
| 6 | A-1 过户费 WONTFIX | 理由仅签名单一 | 补充: "unified_engine 行 593 标量版证明 vectorize 可行, 但引入 np.vectorize 可能降低大订单性能, WONTFIX 合理" |
| 7 | C-2 Step 2 架构图 | 仅 4 依赖 → 实际 8 | 补充 classifiers, pnf, phase_analysis, indicators |
| 8 | D-2 测试策略 | `import` + `callable(main)` 覆盖率≈0 | 加对核心路径断言: `update_daily_incremental.main` 需 mock 验证流程分支 |
| 9 | D 验收门禁 | 无 `mkdir` 步骤 | 加在工作流 D 入口: "`mkdir -p tests/data/ tests/brain/lppl/ tests/hands/strategies/`" |

---

## 根因: 为什么计划会有这些错误?

| 错误类型 | 根因 | 占比 |
|:---------|:-----|:----:|
| LOC 值继承旧报告未验证 | 从 v5_remediation_work_list 直接复制数字, 跳过 `wc -l` | 75% |
| 推理链简化遗漏 | 过户费只数了 cost_model + matching_engine, 忘计 unified_engine | 15% |
| 覆盖率估算凭直觉 | 未做精确计算: 有效增量 1,070 LOC / 未覆盖 28,500 LOC | 10% |

**经验教训**: 计划中的任何数字都必须重新 `wc -l` 或 `grep -c` 验证, 不得继承旧报告。

---

## 计划修复后最终状态估算

| 工作流 | 原始工时 | 修正后工时 | 偏差原因 |
|:-------|:-------:|:---------:|:---------|
| A (WONTFIX) | 30m | 30m | 不变 |
| B (文档批量) | 1.5h | 1.5h | 不变 |
| C (Wyckoff 架构) | 4h | 5h | +1h 补充 4 个遗漏依赖的文档 |
| D Batch 1 | 30m | 45m | +15m scripts LOC 1,270→1,957 |
| D Batch 2 | 2h | 2h | 不变 |
| D Batch 3 | 4h | 4h | 不变 |
| D Batch 4 | 1h | **2h** | +1h optimal_params 142→488 |

**总工时调整**: 12h → **14h** (+2h, +17%)
**覆盖率门禁**: 55% → **54%** (-1pp)
**新建目录**: 增加 `mkdir -p` 步骤

---

*3 轮对抗分析完成。42 声明验证: 28 GREEN, 10 YELLOW, 4 RED。9 项修正要求输出前必须执行。*