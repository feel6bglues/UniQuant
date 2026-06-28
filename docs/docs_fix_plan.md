# UniQuant 文档系统修复计划

> 生成日期: 2026-06-28
> 目标: 基于源码事实修复 docs/ 目录全部 229 个文件的已知缺陷
> 方法: 分布式并行/串行任务 DAG, 每个任务绑定到具体文件:行号
> 原则: need-to-do basis — 只修复影响正确性和可用性的问题, 不重构文档结构

---

## 目录

1. [问题分类](#1-问题分类)
2. [依赖关系图](#2-依赖关系图)
3. [Phase 1 — 核心文档修补 (并行)](#3-phase-1--核心文档修补-并行)
4. [Phase 2 — 元数据对齐 (并行)](#4-phase-2--元数据对齐-并行)
5. [Phase 3 — 状态标注更新 (并行)](#5-phase-3--状态标注更新-并行)
6. [Phase 4 — 深层内容修复 (串行依赖)](#6-phase-4--深层内容修复-串行依赖)
7. [Phase 5 — 存档层清理 (可选)](#7-phase-5--存档层清理-可选)
8. [Phase 6 — 验证循环](#8-phase-6--验证循环)
9. [完整任务清单](#9-完整任务清单)
10. [不采取行动的理论依据](#10-不采取行动的理论依据)

---

## 1. 问题分类

| 类别 | 严重度 | 数量 | 修复方式 | 等价工作量 |
|------|--------|------|---------|-----------|
| A: 错误数字 (文件数/LOC) | ⚪ LOW | 9 处 | 查找替换 | ~2 分钟 |
| B: 错误引擎数 (8→9) | 🟡 MEDIUM | 2 处 | 插入一行 | ~5 分钟 |
| C: 错误状态断言 | 🟡 MEDIUM | 2 处 | 编辑声明 | ~15 分钟 |
| D: 缺少状态标注 | ⚪ LOW | 4 处 | 添加 banner | ~10 分钟 |
| E: 错误行号引用 | 🟡 MEDIUM | 1 处 | 更新行号 | ~5 分钟 |
| F: 错误代码断言 | 🔴 HIGH | 1 处 | 编辑内容 | ~10 分钟 |
| G: Adapter 状态过时 | 🟡 MEDIUM | 1 处 | 编辑章节 | ~20 分钟 |
| H: 存档冗余 | ⚪ LOW | archive/ | 索引化 | ~60 分钟 |
| I: Wyckoff 12→4 合并 | ⚪ LOW | 12 文件 | 新建链接 | ~30 分钟 |

**总计确定性工作**: 约 17 个文件修改, 含 9 处数字修复 + 5 处状态标注 + 3 处内容更新。

---

## 2. 依赖关系图

```
Phase 1 (核心修补, 7 项全并行)         Phase 2 (元数据, 2 项全并行)        Phase 3 (状态标注, 4 项全并行)
┌─────────────────────────┐        ┌─────────────────────────┐        ┌─────────────────────────┐
│ 1.1 architecture.md     │        │ 2.1 index.md:18         │        │ 3.1 MATCHING_ENGINE     │
│    引擎表 + wyckoff     │        │    269→254             │        │    + 当前状态 banner    │
│ 1.2 ARCHITECTURE_       │        │ 2.2 USAGE_GUIDE.md:3   │        │ 3.2 GAP_REMEDIATION     │
│    TOPOLOGY.md 引擎     │        │    179→254, 42K→62K    │        │    历史参考 banner      │
│    表 + wyckoff         │        └──────────┬──────────────┘        │ 3.3 ARCHITECTURE_        │
│ 1.3 architecture.md     │                   │                       │    TOPOLOGY.md           │
│    make_decision 行号   │                   │                       │    扫描状态 banner       │
│ 1.4 analysis/01         │                   │                       │ 3.4 whitepaper/ 各文件   │
│    pd.Timestamp.now()   │                   │                       │    快照日期更新          │
│ 1.5 DATA_FLOW §4        │                   │                       └──────────┬──────────────┘
│    Adapter 状态更新     │                   │                                  │
│ 1.6 ARCHITECTURE_       │                   │                                  │
│    TOPOLOGY.md §3.1     │                   │                                  │
│    God Object 附加注释  │                   │                                  │
│ 1.7 whitepaper/ 各文件  │                   │                                  │
│    引擎数 8→9           │                   │                                  │
└──────────┬──────────────┘                   │                                  │
           │                                  │                                  │
           └──────────────┬───────────────────┴──────────────────┬───────────────┘
                          │                                      │
                          ▼                                      ▼
                  Phase 4 (深层修复，串行)           Phase 5 (存档层，可选)
          ┌────────────────────────────┐    ┌────────────────────────────┐
          │ 4.1 → 4.2 → 4.3 → 4.4    │    │ 5.1 archive/INDEX.md       │
          │ (串行, 每步依赖上一步产出) │    │     更新 → 配置时间戳      │
          └────────────┬───────────────┘    │ 5.2 移入 archive/ 文件     │
                       │                    └────────────────────────────┘
                       ▼
                  Phase 6: 验证循环
          ┌────────────────────────────┐
          │ verify_doc_paths.py 扩展   │
          │ pytest 文档路径验证测试    │
          └────────────────────────────┘
```

**关键**: Phase 1-3 完全并行, 无交叉依赖。Phase 4 内部串行。Phase 5 独立可选。Phase 6 是所有修改的最终验证。

---

## 3. Phase 1 — 核心文档修补 (完全并行, 7 项)

### 3.1 Task: `architecture.md` — 引擎表加 wyckoff

**文件**: `docs/architecture.md:276-287`

**当前**:
```
工厂通过 @property 暴露 8 个延迟加载的分析引擎, 每个属性对应一个 brain/ 或 services/analysis/ 下的具体引擎类:

| fsm      | FsmAnalysisEngine       | analysis.fsm_analysis_engine       | 有限状态机分析 |
| czsc     | CzscAnalysisEngine      | analysis.czsc_analysis_engine      | 缠中说禅分析 |
| lppl     | LpplAnalysisEngine      | analysis.lppl_analysis_engine      | 对数周期幂律模型 |
| regime   | RegimeAnalysisEngine    | analysis.regime_analysis_engine    | 市场状态检测 |
| ntf      | NtfAnalysisEngine       | analysis.ntf_analysis_engine       | 国家队资金追踪 |
| macro    | MacroAnalysisEngine     | analysis.macro_analysis_engine     | 宏观经济分析引擎 |
| report   | ReportGeneratorEngine   | analysis.report_generator_engine   | 分析报告自动生成 |
| brain    | DecisionBrain           | brain.fsm                         | 综合决策大脑 |
```

**修复**: 标题改 "8 个" → "9 个", 表格插入 wyckoff 行:

```
| wyckoff  | WyckoffAnalysisEngine   | analysis.wyckoff_analysis_engine   | 威科夫量价分析 |
```

**源码依据**: `services/analysis/engine_factory.py:98-99`:
```python
def wyckoff(self):
    return self._lazy_init("wyckoff", "..analysis.wyckoff_analysis_engine", "WyckoffAnalysisEngine")
```

**依赖**: 无, 可独立执行。

---

### 3.2 Task: `ARCHITECTURE_TOPOLOGY.md` — 引擎数对齐

**文件**: `docs/ARCHITECTURE_TOPOLOGY.md` (行号待定位 8 引擎声称)

**检查**: 该文档在 banner 中标注为 2026-06-07 扫描, 多处内容已不是当前状态。Mermaid 图 (line 119-127) 已包含 wyckoff 引擎 (`SVC_WYCK`), 但 line 71 的 `services 服务层 18 文件` 不匹配当前 31 文件。

**修复**: 添加状态 banner 更新, 覆盖 18→31 文件数。

**实际上**: 该文档是历史扫描产物, 完整更新文档统计需要重跑扫描, 属于超出需要范围的工程工作。**最优方案**: 仅添加 banner 说明。

**源码依据**: `src/uniquant/services/` 实际 32 个 Python 文件 (见 src 分析报告 §8)。

**依赖**: 无。

---

### 3.3 Task: `architecture.md` — `_make_decision` 行号修正

**文件**: `docs/architecture.md` (引用 `analysis_service_v2.py:518-526` 处)

**问题**: 文档声称 `analysis_service_v2.py:518-526` 调用 `DecisionBrain.make_decision()`。实际 `analysis_service_v2.py:518-537` 是 `_run_wyckoff()`, `_make_decision()` 在 `~630` 行。

**修复**: 更新代码引用行号 `518-526` → `~630`。

**源码依据**: `src/uniquant/services/analysis_service_v2.py:518-537` 为 `_run_wyckoff()`, `627-640` 为 `_make_decision()`。

**依赖**: 无。

---

### 3.4 Task: `analysis/01_services_orchestration.md` — `pd.Timestamp.now()` 声明更新

**文件**: `docs/analysis/01_services_orchestration.md:212`

**当前**: "✅ 管道信号时间戳使用 `pd.Timestamp.now()` 导致历史回测可能无交易"

**问题**: `pd.Timestamp.now()` 在生产代码中 **0 次调用**。G-1 修复 (2026-06-12) 已完全消除此模式。

**修复**: 改为 "⚠️ 管道信号时间戳原使用 `pd.Timestamp.now()`——2026-06-12 前。G-1 修复后已全部替换为 `get_time_provider().now()`, 当前 0 处直接调用。"

**源码依据**: `src/uniquant/` 全局 grep `pd.Timestamp.now()` 结果: 0 匹配。`get_time_provider().now()` 出现 100+ 处。

**依赖**: 无。

---

### 3.5 Task: `DATA_FLOW_WHITEPAPER.md` — §4 Adapter Blueprint 状态更新

**文件**: `docs/DATA_FLOW_WHITEPAPER.md:598-657`

**当前**: §4.2 以接口设计草案形式呈现, 使用 `EngineOutputAdapter` ABC 名称和 `Signal` 模型。

**事实**: 实际实现:
- 基类名: `EngineAdapter` (非 `EngineOutputAdapter`)
- 输出类型: `TradingSignal` (非 `Signal`)
- 9 个类: `EngineAdapter` ABC + `LPPLAdapter` + `CZSCAdapter` + `WyckoffAdapter` + `FSMAdapter` + `RegimeAdapter` + `NTFAdapter` + `AlphaScoreAdapter` + `MAStatusAdapter`
- 已接入: `AdapterRegistry` + `TradingSignalCollector` + `research_pipeline.py`

**修复**: 在 §4 开头添加状态框:
```
> **2026-06-28 更新**: Adapter Blueprint 已完整实现。实际实现使用 `EngineAdapter` (ABC) 基类名 (非 `EngineOutputAdapter`), 输出 `TradingSignal` (非 `Signal`), 9 个类通过 `TradingSignalCollector` 接入 `research_pipeline`。以下接口草案作为设计参考保留。
```

**源码依据**: `src/uniquant/signal/adapters.py:35-604` — 完整实现确认为 9 个类 + 注册表 + 收集器 + pipeline 集成。

**依赖**: 无。

---

### 3.6 Task: `ARCHITECTURE_TOPOLOGY.md:364` — God Object 注释

**文件**: `docs/ARCHITECTURE_TOPOLOGY.md:364`

**当前**: "CRITICAL: AnalysisService — God Object (850+ 行)"

**问题**: 原 `analysis_service.py` 1642 行确实是 God Object, 但 refactored 的 `analysis_service_v2.py` 是 648 行, 且 legacy 1,649 行尸体代码零引用。

**修复**: 改为 `"CRITICAL: AnalysisService — God Object (原 1642 行, 已重构为 v2 648 行, legacy 尸体仍保留 1,649 行零引用)"`

**源码依据**: `src/uniquant/services/analysis_service_v2.py` (648 LOC), `src/uniquant/services/analysis_service_legacy.py` (1,649 LOC, 零引用由 grep 确认)。

**依赖**: 无。

---

### 3.7 Task: `whitepaper/ARCHITECTURE_WHITEPAPER.md` + `DEPLOYMENT_GUIDE.md` — 引擎数 8→9

**文件 1**: `docs/whitepaper/ARCHITECTURE_WHITEPAPER.md:3`
**当前**: `"8 层全部就绪"`
**修复**: 改为 `"8 层 9 引擎全部就绪"`。

**文件 2**: `docs/whitepaper/DEPLOYMENT_GUIDE.md:12`
**当前**: `"8 层全部就绪"`
**修复**: 同上。

**依赖**: 无。

---

## 4. Phase 2 — 元数据对齐 (2 项, 完全并行)

### 4.1 Task: `index.md:18` — 文件数更新

**文件**: `docs/index.md:18`
**当前**: `"does NOT reflect current 269-file codebase"`
**修复**: `"does NOT reflect current 254-file codebase"`

**源码依据**: `src/uniquant/` 实际 254 个 Python 文件 (src 分析报告 §1.2)。

**注意**: 此文件引用的是 `STATUS.md` 的存档状态, STATUS.md 本身是 archive 文件不应修改。只需更新 index.md 中描述当前代码库的文件数。

**依赖**: 无。

---

### 4.2 Task: `USAGE_GUIDE.md:3` — LOC 更新

**文件**: `docs/USAGE_GUIDE.md:3`
**当前**: `"基于 179 文件 / 42,549 LOC 实测输出 | 2026-05-28"`
**修复**: `"基于 254 文件 / 62,804 LOC 实测输出 | 2026-05-28 (源码已增长, 文档待同步更新)"`

**源码依据**: `src/uniquant/` 实际 254 个文件, 62,804 LOC。

**依赖**: 无。

---

## 5. Phase 3 — 状态标注更新 (4 项, 完全并行)

### 5.1 Task: `MATCHING_ENGINE_AUDIT.md` — 添加当前状态横幅

**文件**: `docs/MATCHING_ENGINE_AUDIT.md`

**问题**: 此文档是 2026-06-07 审计, 部分漏洞已修复。文档无当前状态标注。

**修复**: 在已有 banner 行后添加:
```
> **⚠️ 2026-06-28 状态更新**: 此审计基于 2026-06-07 代码。Phase 0-6 已完成, unified_engine 已部署。漏洞状态请参照当前测试和 unified_engine.py。
```

**源码依据**: `MATCHING_ENGINE_AUDIT.md:561` 描述的是 `BacktestEngine` (legacy, 747 LOC), 当前生产使用 `UnifiedBacktestEngine` (unified_engine.py, 604 LOC)。

**依赖**: 无。

---

### 5.2 Task: `GAP_REMEDIATION_PLAN.md` — 添加历史参考标注

**文件**: `docs/GAP_REMEDIATION_PLAN.md`

**问题**: G-1~G-4 已于 2026-06-12 全部关闭, 但文档无当前状态标注。

**修复**: 在 banner 中添加一行:
```
> **⚠️ 2026-06-12 后**: 四个缺口 (G-1~G-4) 全部关闭并经验证。此文档作为历史参考保留。
```

**源码依据**: G-1 TimeProvider 已使用 (`time_provider.py`), 0 `pd.Timestamp.now()`; G-2 FactorRegistry brain/ 16 引用; G-3 基线脚本存在; G-4 AsyncEventBus 存在。

**依赖**: 无。

---

### 5.3 Task: `ARCHITECTURE_TOPOLOGY.md` — 扫描状态标注

**文件**: `docs/ARCHITECTURE_TOPOLOGY.md:1-5`

**当前 banner**: "扫描时间: 2026-06-07 | 仅分析目录/类声明/函数签名/Import/DI"

**修复**: 添加一行:
```
> **⚠️ 文件统计已过时**: 扫描时基于 159 个文件, 当前 254 个文件。此文档保留作为架构拓扑分析参考, 文件数/行数应以最新扫描为准。
```

**依赖**: 无。

---

### 5.4 Task: `whitepaper/` 各文件 — 快照日期标注

**文件 1**: `docs/whitepaper/ARCHITECTURE_WHITEPAPER.md:3`
**当前**: `"源码快照: 2026-06-01"` + `"269 文件, ~59,441 LOC"`
**修复**: `"源码快照: 2026-06-01 (文件数/引擎数已增长, 参见 src 分析报告)"`

**文件 2**: `docs/whitepaper/DEPLOYMENT_GUIDE.md:12` — 同上模式。

**依赖**: 无。

---

## 6. Phase 4 — 深层内容修复 (部分串行)

### 6.1 Task: `ARCHITECTURE_TOPOLOGY.md` — 全文文件统计表更新

**文件**: `docs/ARCHITECTURE_TOPOLOGY.md` (多处分布)

**检查发现**:
- Line 13: `"shared<br/>23 文件"` → 44
- Line 71: services 层文件数 (估算)
- Line 248: `"8 个"` DataSource 实现者 → 8 (确认正确)

**修复**: Mermaid 图中文件数和各层文件数需要与当前源码一致。

**注意**: 此任务需要重新运行 Mermaid 图中的文件统计, 可能影响显示布局。**从 need-to-do 角度**, Mermaid 图的美观性不是阻塞性缺陷, 只需更新标注即可。

**实质最小修复**: 在现有 banner 中添加文件统计已过时的标注 (已在 Phase 3 中覆盖)。

**依赖**: Phase 3.3 完成后。

---

### 6.2 Task: `DATA_FLOW_WHITEPAPER.md` — 2 处代码示例更新

**文件**: `docs/DATA_FLOW_WHITEPAPER.md`

**问题 1** (line 636): `EngineOutputAdapter.adapt()` 的 timestamp 参数文档说 "默认 datetime.now()"——实际情况通过 `TradingSignalCollector` 接收 `bar_date` 参数, 使用 `get_time_provider()` 时间。

**修复**: 更新注释, `datetime.now()` → `get_time_provider().now()`。

**问题 2** (line 628): 基类名 `EngineOutputAdapter` → 实际 `EngineAdapter`。

**问题 3** (line 629): 返回类型 `Optional[Signal]` → 实际 `Optional[TradingSignal]`。

**修复**: 在 §4 整体状态框更新 (已在 3.5 中覆盖), 代码示例保留作为设计参考。

**依赖**: Phase 1.5 完成后。

---

### 6.3 Task: `docs/archive/` 状态串联

**文件**: `docs/archive/INDEX.md`

**问题**: `archive/INDEX.md` 是否反映了当前存档内容的最优入口点?

**检查**: 如果 INDEX.md 存在且准确, 无需修改——存档文件被定义为历史参考, 不需要保持当前事实。

**处理**: 只验证 INDEX.md 的内容是否与其目的匹配, 不修改存档内文件本身 (它们被声明为历史快照)。

**依赖**: 无。

---

### 6.4 Task: `analysis/` 阶段文档 — `pd.Timestamp.now()` 声明扫描

**检查**: 除 `01_services_orchestration.md` 外, 其他 `analysis/` 文件是否也有类似过时声明。

**方法**: grep `pd\.Timestamp\.now\(\)` across `docs/analysis/`.

**修复**: 如果发现其他文件, 统一添加 G-1 关闭时间线标注。

**依赖**: Phase 1.4 完成后, 作为扫描检查。

---

## 7. Phase 5 — 存档层清理 (可选, 非阻塞性)

### 7.1 Task: archive/ 索引化

**当前**: archive/ 包含 >96 个文件, 39.3% 的文档量。

**处理**: 如果 `archive/INDEX.md` 已存在且准确, 无需修改。如果缺失, 创建索引。

**决策**: 从 `docs/analysis/comprehensive_docs_analysis_report.md` §7.2 可知 archive/ 内容已有时间线整理——这已足够。**不作为必须修复**。

### 7.2 Task: Wyckoff 12 文件合并

**当前**: `docs/analysis/` 下 12 个 wyckoff 文件 (research_report, design_vs_implementation_gap_analysis, correction_plan, multitf_v3, multitf_verification_plan, step_verification, backtest_report, practical_implementation_roadmap, verification_design, verification_final_plan, session_report, feature_worklist)。

**处理**: 创建索引文件 `docs/analysis/wyckoff/README.md` 并列出各文件的用途和当前状态。**不作为合并**——12 个文件是独立分析产物, 合并会破坏引用。

**决策**: 仅添加索引, 不合并文件。**不作为必须修复**。

---

## 8. Phase 6 — 验证循环

### 8.1 Task: 扩展 `scripts/verify_doc_paths.py`

**当前**: 脚本检查文档中引用的文件路径是否存在。

**扩展**: 增加:
1. 检查行号引用是否在当前代码行范围内
2. 检查文档中声称的文件数 (`\d+ 文件`) 是否符合当前 `find src/uniquant/ -name '*.py' | wc -l`
3. 检查文档中声称的 LOC (`\d+,?\d* LOC`) 是否符合当前 `find src/uniquant/ -name '*.py' -exec cat {} + | wc -l`
4. 检查 `8 个引擎` 模式——应更新为 `9 个引擎` 或使用代码推导

**依赖**: Phase 1-4 全部完成后。

### 8.2 Task: 修改后验证

```
1. 对每个修改的文件: 手动阅读确认语义正确
2. 对数字修复: 运行 verify_doc_paths.py 扩展版
3. 对引擎数修复: git diff 确认 wyckoff 行已插入
4. 对状态标注: 阅读 banner 确保格式一致
```

---

## 9. 完整任务清单

### 9.1 必须修复 (按 Phase 分组)

| ID | Phase | 文件 | 行 | 当前内容 | 修复内容 | 工作量 |
|----|-------|------|----|---------|---------|--------|
| F01 | 1.1 | `architecture.md` | 276 | "8 个延迟加载的分析引擎" | "9 个延迟加载的分析引擎" | ~2min |
| F02 | 1.1 | `architecture.md` | 276-287 | 引擎表缺 wyckoff | 插入 wyckoff 行 | ~3min |
| F03 | 1.3 | `architecture.md` | *引用行* | `analysis_service_v2.py:518-526` | `analysis_service_v2.py:~630` | ~2min |
| F04 | 1.4 | `analysis/01_services_orchestration.md` | 212 | "✅ 管道信号时间戳使用 `pd.Timestamp.now()`" | "⚠️ 原使用 pd.Timestamp.now()——G-1 已替换为 get_time_provider().now()" | ~5min |
| F05 | 1.5 | `DATA_FLOW_WHITEPAPER.md` | 598-600 | "Adapter Blueprint" 作为"设计草案" | 添加已实现状态框 | ~10min |
| F06 | 1.6 | `ARCHITECTURE_TOPOLOGY.md` | 364 | "God Object (850+ 行)" | "God Object (原 1642, v2 648)" | ~2min |
| F07 | 1.7 | `whitepaper/ARCHITECTURE_WHITEPAPER.md` | 3 | "8 层" | "8 层 9 引擎" | ~1min |
| F08 | 1.7 | `whitepaper/DEPLOYMENT_GUIDE.md` | 12 | "8 层" | "8 层 9 引擎" | ~1min |
| F09 | 2.1 | `index.md` | 18 | "269-file codebase" | "254-file codebase" | ~1min |
| F10 | 2.2 | `USAGE_GUIDE.md` | 3 | "179 文件 / 42,549 LOC" | "254 文件 / 62,804 LOC" | ~1min |
| F11 | 3.1 | `MATCHING_ENGINE_AUDIT.md` | *banner* | 无当前状态标注 | 添加当前状态 banner | ~3min |
| F12 | 3.2 | `GAP_REMEDIATION_PLAN.md` | *banner* | 无关闭状态标注 | 添加缺口关闭 banner | ~3min |
| F13 | 3.3 | `ARCHITECTURE_TOPOLOGY.md` | 1-5 | 扫描日期标注 | 添加文件统计过时标注 | ~2min |
| F14 | 3.4 | `whitepaper/ARCHITECTURE_WHITEPAPER.md` | 3 | "269 文件, ~59,441 LOC" | 添加快照日期说明 | ~1min |
| F15 | 6.1 | `scripts/verify_doc_paths.py` | *新增* | 文件路径验证 | 文件数/LOC 自验证 | ~30min |

**总计工作量**: ~15 分钟修改 + ~30 分钟验证脚本扩展 = ~45 分钟。

### 9.2 推荐修复 (非阻塞, 但建议执行)

| ID | Phase | 文件 | 描述 | 工作量 |
|----|-------|------|------|--------|
| R01 | 6.2 | `DATA_FLOW_WHITEPAPER.md` | 代码示例中 `datetime.now()`→`get_time_provider().now()` | ~2min |
| R02 | 6.2 | `DATA_FLOW_WHITEPAPER.md` | `EngineOutputAdapter`→`EngineAdapter` 注释更新 | ~2min |
| R03 | 6.4 | `analysis/` 其他文件 | 扫描 `pd.Timestamp.now()` 引用并添加时间线标注 | ~5min |
| R04 | 5.2 | `docs/analysis/wyckoff/README.md` | 创建 Wyckoff 文档索引 | ~15min |

### 9.3 不修复 (理由)

| 文件 | 问题 | 不修复理由 |
|------|------|-----------|
| `archive/*` | 大量 V1/V2/V3 重复 | 文件已声明为历史存档, 内容重复是审计迭代的正常产物 |
| `analysis/institutional/*` (21 文件) | 与 analysis/ 顶层不交叉引用 | 制度审计是完工状态, 修改会破坏完整性 |
| `reshaping_logs/*` (38 文件) | 线性状态日志, 与 analysis/ 不交叉引用 | 重塑日志是演化记录, 不可变, 不应修改 |
| `architecure.md` 附录路径树 | 使用旧模块路径 | 文档自身 banner 已声明路径过时 |
| `ARCHITECTURE_TOPOLOGY.md` Mermaid 图 | 文件数 (23/18) 过时 | 图重新布局需要大量手工工作, 且 banner 已声明 |
| `packages/*` (8 文件) | 自知可能过时 | 文档自身声明可能过时, 且包结构未本质变化 |
| `reference/*` (5 文件) | A 股规则/常量/异常 | 这些是参考手册, 内容准确度已经验证 |

---

## 10. 不采取行动的理论依据

以下修改被明确排除, 并给出理由:

| 建议 | 排除理由 |
|------|---------|
| 合并 archive/ 文件 | archive/ 被定义为历史存档, 内容保留原始的审计迭代是项目演化记录的一部分 |
| 重写 Mermaid 图 | 需要重新扫描全部 254 个文件的 import 关系, 工作量远大于收益 |
| 统一 reshaping_logs 和 analysis 引用 | 两套体系各自独立完成, 交叉引用会增加维护负担而非价值 |
| 创建术语表 | 核心概念已在多个文档中描述, 增加 Glossary 会引入第四个来源 |
| 删除死文档 | 任何删除是破坏性变更, 可能被工具或开发者引用——存档是最好的形式 |
| 自动化数字验证 CI | 需要在 CI/CD 中集成, 超出 docs-only 修复的范围 |

---

## 11. 执行顺序建议

```
Start → F09 + F10 (1min 数字修复, 并行)
       → F01 + F02 + F07 + F08 (1min 引擎数, 并行)
       → F03 + F04 (5min 内容修复, 并行)
       → F05 + F06 (10min 架构文档, 并行)
       → F11 + F12 + F13 + F14 (3min 状态标注, 并行)
       → R01 + R02 + R03 (5min 推荐修复, 并行)
       → R04 (15min 可选)
       → F15 (30min 验证脚本)
       → 结束
```

**总执行时间估计**: ~45 分钟 (含验证脚本扩展)
**无冲突可能**: 15 个必须修复分布在 12 个不同文件, 无交叉修改。

---

*本计划基于对 docs/ 目录 229 个文件的系统分析和 254 个源码文件的交叉验证。每个修复任务都满足 need-to-do 原则: 只修复影响正确性、可用性和可维护性的问题。所有非必要的重构、合并、重写已被明确排除。*
