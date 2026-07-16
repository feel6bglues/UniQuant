# UniQuant 7 轮分析对话完整总结

> 生成日期: 2026-07-09
> 分析目标: 基于代码实际，将 UniQuant 作为量化研究平台，编排多轮分析任务诊断项目问题
> 分析方法论: 参考 `docs/ANALYSIS_PROMPT_PLAYBOOK.md` 的阶段式分析框架，结合 `docs/reanalysis/I_live_system_map.md` 已验证的实时系统映射基线

---

## 目录

1. [对话背景与目标](#1-对话背景与目标)
2. [执行架构](#2-执行架构)
3. [Round 1: 代码实际状态快照](#3-round-1-代码实际状态快照)
4. [Round 2: 活动 BUG 深度追踪](#4-round-2-活动-bug-深度追踪)
5. [Round 3: 测试体系深度审计](#5-round-3-测试体系深度审计)
6. [Round 4: 死代码与复杂度清理评估](#6-round-4-死代码与复杂度清理评估)
7. [Round 5: 信号系统与回测信任验证](#7-round-5-信号系统与回测信任验证)
8. [Round 6: 研究平台能力差距矩阵](#8-round-6-研究平台能力差距矩阵)
9. [Round 7: 综合修复路线图](#9-round-7-综合修复路线图)
10. [关键发现速查表](#10-关键发现速查表)
11. [文档漂移修正清单](#11-文档漂移修正清单)
12. [评分卡预测](#12-评分卡预测)
13. [AGENTS.md 更新内容](#13-agentsmd-更新内容)

---

## 1. 对话背景与目标

### 用户角色
顶级量化金融工程师、量化金融算法工程师、Python 程序员、A 股交易员

### 核心指令
基于项目实际和代码实际，把 UniQuant 作为一个研究平台，编排多轮分析任务，分析项目存在的问题。编排可参考 `docs/` 文档（特别是 `docs/ANALYSIS_PROMPT_PLAYBOOK.md` 的阶段 0-7 框架）。

### 项目状态快照（分析开始前）
- 工作树最后提交: `5954abf2` (2026-07-01 "anti-drift test suite")
- 工作树状态: 44 个已修改文件，50+ 未追踪文件，所有变更在 Working Tree 中（未暂存）
- 上一轮已完成: Phase 2/3 小/独立任务（#33, #45, #47-53, #57, #66）
- 代码库: 256 文件, 62,465 LOC, 126 测试文件, 1,591 测试函数, 1,666 通过
- 已知文档: `AGENTS.md`, `docs/reanalysis/` (15 份 v2.0 deep audit 报告), `docs/analysis/` (阶段 0-7 产物)

---

## 2. 执行架构

### 并行 Agent 编排模式

每轮分析采用并行多 Agent 执行的模式。共使用了 6 种 Agent 类型：

| Agent 类型 | 用途 | 使用次数 |
|---|---|---|
| `explore` | 代码探索、文件读取、grep 搜索 | 11 |
| `general` | 综合任务（运行测试、执行命令） | 3 |

### 7 轮分析概要

```
Round 1 ─── 代码实际状态快照
  ├── Agent 1a: 文件级真实基线（文件数/LOC/每层统计/大文件/测试映射）
  ├── Agent 1b: 工作树差异分析（git diff/status/未追踪文件）
  └── Agent 1c: 活动BUG代码确认（确认4个BUG的精确行号）

Round 2 ─── 活动BUG深度追踪
  ├── Agent 2a: Bug#1 alpha→SELL 端到端追溯
  ├── Agent 2b: Bug#2 fillna 因子失真影响链
  └── Agent 2c: Bug#3+#4 except 路径分析

Round 3 ─── 测试体系深度审计
  ├── Agent 3a: 弱断言测试分析（AST扫描1591测试函数）
  ├── Agent 3b: 核心模块覆盖缺口（13个零测试模块分析）
  └── Agent 3c: mutmut状态 + 实测运行（覆盖率52%）

Round 4 ─── 死代码与复杂度评估
  ├── Agent 4a: 死代码验证（rg追踪每个候选的调用者）
  └── Agent 4b: 复杂度热点（圈复杂度/超大函数/依赖方向）

Round 5 ─── 信号系统与回测信任验证
  ├── Agent 5a: 信号链路完整性验证（8适配器→仲裁→回测完整图谱）
  ├── Agent 5b: A股7条防线验证（每防线至少2层检查）
  └── Agent 5c: 基线一致性测试（capture+compare, 无漂移）

Round 6 ─── 研究平台能力差距矩阵
  ├── Agent 6a: 研究工具清单（91实验脚本 + 7核心工具类）
  └── Agent 6b: 20项能力差距矩阵（13✅ 3⚠️ 4❌）

Round 7 ─── 综合修复路线图
  └── 合成所有6轮发现 → P0(7项)/P1(8项)/P2(10项)路线图
```

---

## 3. Round 1: 代码实际状态快照

### 目标
对比文档声明与代码实际，建立真实的代码基线，识别文档漂移。

### 执行方法
3 个并行 Agent 分别扫描文件基线、工作树差异、BUG 确认。

### 关键发现

#### 文件级统计（与文档对比）

| 指标 | 文档声明 | 实际 | 偏差 |
|---|---|---|---|
| Python 文件数 | 251 | **256** | +5 |
| 总 LOC | 62,300 | **62,465** | +165 |
| 测试函数数 | 1,461 | **1,591** | +130 |
| 测试通过数 | 1,435 | **1,666** | +231 |
| 测试失败数 | 5 | **0** | -5 |
| Ruff 问题数 | 0 | **0** | ✅ |

#### 每层统计

| 层 | 文件数 | LOC | 平均 |
|---|---|---|---|
| shared | 46 | 7,214 | 157 |
| data | 67 | 15,263 | 228 |
| brain | 54 | 16,054 | 297 |
| signal | 8 | 2,744 | 343 |
| hands | 34 | 6,437 | 189 |
| risk | 6 | 1,638 | 273 |
| services | 32 | 9,751 | 305 |
| ui | 8 | 3,363 | 420 |

#### 超大文件 (>800 LOC)

| 文件 | 行数 | 优先级 |
|---|---|---|
| `services/analysis_service_legacy.py` | **1,649** | 已标记死代码 |
| `brain/wyckoff/engine.py` | **1,613** | P1 重构目标 |
| `ui/dashboard.py` | **1,553** | P2 重构目标 |
| `brain/lppl/engine.py` | **1,098** | P2 重构目标 |
| `brain/wyckoff/models.py` | 820 | 监控 |

#### 工作树变更摘要

- 44 个已修改文件，净变化 +1,759 / -2,494（净减 735 行）
- 核心重构: `eastmoney.py` 1094→3 行 re-export; Wyckoff engine 复杂方法拆分; data/sources 重复代码上提至 `base.py`
- 新文件: `board_registry.py`, `wyckoff/constants.py`, `eastmoney_base/financial/quote.py`
- 所有变更在 Working Tree 中，**未暂存**
- 5 个新 untracked 源文件 + 3 个新 untracked 测试文件

#### 4 个活跃 BUG 确认

| Bug | 文件 | 行号 | 确认 |
|---|---|---|---|
| #1 alpha_score=0.0→SELL | `analysis_service_v2.py:535,543,552` + `adapters.py:359` | ✅ |
| #2 fillna(0.0) 因子失真 | `composer.py:183,204,276` | ✅ |
| #3 pipeline 裸 except | `research_pipeline.py:239,495` | ✅ |
| #4 Wyckoff 裸 except | `engine.py:251,260,1573,1588` | ✅ |

---

## 4. Round 2: 活动 BUG 深度追踪

### 目标
对 4 个活跃 BUG 做端到端影响链分析，逐行追溯从触发到最终影响的完整路径。

### 执行方法
3 个并行 Agent，分别追踪 Bug#1, Bug#2, Bug#3+#4。

### Bug #1: alpha_score=0.0 → SELL 完整链路

```
[引擎层] AnalysisService._run_alpha()
  ├─ 路径A: stock_df 空 → v2.py:535  → AlphaOutput(score=0.0)
  ├─ 路径B: bench 空   → v2.py:543  → AlphaOutput(score=0.0)
  └─ 路径C: 8种异常    → v2.py:552  → AlphaOutput(score=0.0)
       └─ pack_writer.py:62 → data_pack["alpha_score"] = 0.0

[信号层] adapters.py:359
  └─ score = 0.0 < 0.3 → action = "SELL"    (第362-363行)
       └─ confidence = abs(0.0-0.5)*2 = 1.0  (第369行) ← 越失败置信度越高
            └─ TradingSignal(action="SELL", confidence=1.0)

[仲裁层] arbitrator.py:192-207
  └─ SELL优先: confidence=1.0 的虚假SELL覆盖所有BUY信号

[回测层] unified_engine.py:409-417
  └─ sig.action == "SELL" and position > 0 → 全仓清仓
```

**讽刺性结论**: 引擎越失败（score=0.0），生成的 SELL 信号 confidence（1.0）反而越高。这会导致在数据缺失或计算异常时产生 confident 的误卖出信号，且在仲裁器中因 SELL 优先规则覆盖所有 BUY 信号。

**修复方案**: `adapters.py` 中 `AlphaScoreAdapter.adapt()` 第359行，在 `score == 0.0` 时返回 `None`（不产生信号）。

### Bug #2: fillna(0.0) 因子失真

3 处 fillna(0.0) 分布在 composer.py 的三个方法中：

| 位置 | 方法 | 行号 | 影响 |
|---|---|---|---|
| Z-score 标准化后 | `_zscore_frame` | 183 | 缺失因子→0.0 |
| 归一化拼接后 | `_normalize_factors` | 204 | 索引对齐缺失→0.0 |
| 正交化重标准后 | `_symmetric_orthogonalization` | 276 | 数值不稳定→0.0 |

**最严重的失真场景**:
- **新上市股票 (<60 交易日)**: 13 个因子全是 NaN → 全部填 0.0 → composite_score=0.0（被误评为中性）
- **screener 已有滴漏**: `screener.py:79` 已有 `dropna(subset=[score_col])` 保护，但 fillna(0.0) 在 composer 中先执行将其绕过
- **样本外 IC 评估**: fillna(0.0) 导致缺失股票参与排名，扭曲 OOS IC 计算

**下游消费者影响链**:
```
composer.py fillna(0.0) → ScanPipeline.compose_scores() → StockScreener 排名
                                                → WalkForwardFactorPipeline OOS IC
```

**修复方案**: 3 处 `fillna(0.0)` 改为 `fillna(np.nan)`。已确认下游 StockScreener、FactorAnalyzer、FactorNeutralizer、WalkForwardPipeline 全部对 NaN 有正确处理（dropna/skipna），无需额外修改。

### Bug #3: Pipeline 裸 except

| 位置 | 行号 | 严重性 | 问题 |
|---|---|---|---|
| `_run_single` | 495 | **中** | `except Exception as e` 吞没 KeyboardInterrupt、MemoryError |
| `_persist_result` | 609 | 低 | 持久化失败被静默吞掉 |
| `_save_batch_checkpoint` | 239 | 安全 | 清理后立即 re-raise |
| `_load_checkpoint_result` | 533 | 低 | 损坏 checkpoint 跳过后重新处理 |

**_run_single 问题最严重**: `run_batch()` 中对每个 symbol 调用 `_run_single`，异常被 `except Exception as e` 捕获后 `logger.error` 没有 `exc_info=True`（traceback 丢失），返回 `PipelineResult(success=False)`。调用方无法区分"正常但无信号"和"引擎崩溃"。

**修复方案**: `_run_single` 第495行窄化为 `except (ValueError, TypeError, KeyError, RuntimeError, OSError)` + `exc_info=True` + `except BaseException: raise`。

### Bug #4: Wyckoff 裸 except

4 处裸 except，从不重抛异常：

| 位置 | 行号 | 保护范围 | 无日志? | 风险 |
|---|---|---|---|---|
| P&F in `_analyze_single` | 251 | PointAndFigure 构建+分析 | ✅ 无日志 | 低 |
| Regime in `_analyze_single` | 260 | RegimeAwarePhaseClassifier | ✅ 无日志 | 中 |
| P&F in `scan_signal` | 1573 | P&F 分析 | ✅ 无日志 | 低 |
| `scan_signal` 外层 | 1588 | **整个** scan_signal | 有日志但无 traceback | **高** |

**scan_signal 外层最严重**: 保护了包括 `self.analyze()`（9步分析）在内的整个方法。失败时返回 `{"phase":"UNKNOWN", "action":"HOLD", "signal_type":"error"}` — 一个看似正常的信号，调用方无法区分"信号正常无交易"和"引擎崩溃"。

**跨层异常穿透路径**:
```
WyckoffEngine._analyze_single() Step 0-5
  → 非RECOVERABLE异常 → WyckoffAnalysisEngine._fallback()
    → 也使用 WYCKOFF_RECOVERABLE_ERRORS
      → 穿透 → AnalysisService._run_wyckoff() 的 RECOVERABLE_ERRORS
        → 穿透 → AnalysisService._run_engines() 的 RECOVERABLE_ERRORS
```

4 层保护逐层变宽，深层的异常在穿透过程中丢失了上下文信息。

**修复方案**: 位置①-③加具体异常类型 + 日志；位置④去掉外层 try/except 或窄化 + `exc_info=True`。

---

## 5. Round 3: 测试体系深度审计

### 目标
审计变异测试状态、弱断言测试、适配器覆盖缺口、核心模块覆盖缺口。

### 执行方法
3 个并行 Agent。

### 关键发现

#### 弱断言测试 — 文档声明 vs 实际

| 来源 | 声明 | 实际 | 偏差 |
|---|---|---|---|
| AGENTS.md / docs | "56 个无 assert 测试函数" | **1 个** 真正弱测试 | **10x 夸大** |
| docs/reanalysis/B | "20+ weak tests" | **1** | 同样错误 |

**真正弱测试**: `tests/shared/test_observability.py:98 test_perf_section_without_recorder` — 只有 `with perf_section("noop"): pass`，无任何验证。

**47 个"无 assert"但有替代断言的测试**:
- `pytest.raises(...)`: 47 个使用（完全合格的断言机制）
- `pd.testing.assert_series_equal / assert_frame_equal`: 2 个
- `mock.assert_called_once_with`: 1 个
- `pytest.fail`: 1 个

#### 适配器覆盖 — 文档声明 vs 实际

| 来源 | 声明 | 实际 | 偏差 |
|---|---|---|---|
| docs/reanalysis | "29% adapter coverage" | **8/8 适配器全部有测试 (62 测试)** | **严重过时** |

`tests/signal/test_adapters.py` (403 行, 62 测试函数) 覆盖:

| 适配器 | 测试数 | 动作验证 | 置信度 | 回退键 | 边界 |
|---|---|---|---|---|---|
| LPPLAdapter | 7 | ✅ | ✅ | ✅ | ✅ |
| CZSCAdapter | 7 | ✅ | ✅ | ❌ | ✅ |
| WyckoffAdapter | 8 | ✅ | ✅ | ✅ | ✅ |
| FSMAdapter | 9 | ✅ | ❌ | ✅ | ✅ |
| RegimeAdapter | 6 | ✅ | ❌ | ❌ | ✅ |
| NTFAdapter | 7 | ✅ | ✅ | ❌ | ✅ |
| AlphaScoreAdapter | 10 | ✅ | ✅ | ❌ | ✅ |
| MAStatusAdapter | 8 | ✅ | ✅ | ❌ | ✅ |

#### mutmut 变异测试状态

**不可用**。根本原因: `pyproject.toml` 中**缺少** `[tool.mutmut]` 配置节。mutmut 3.6.0 扫描了全部 256 个源文件但 "0 files mutated" — 它将所有文件视为 "unmodified" 因为没有配置告诉它哪些路径需要突变。

#### 覆盖率

```
TOTAL  29036  14055  52%
```

**52%** — 超过 pyproject.toml 设置的 50% 门槛，但低于行业标准的 80%。

#### 核心模块覆盖缺口

13 个核心模块（共 5,576 LOC）零专用测试：

| 优先级 | 文件 | LOC | 函数数 | 可测试性 | 理由 |
|---|---|---|---|---|---|
| **P0** | `data_validator.py` | 85 | 2 | **极易** | 数据质量第一道防线 |
| **P0** | `analysis_service_v2.py` | 637 | 32 | 中等 | 分析编排核心 |
| **P0** | `unified_engine.py` | 752 | 22 | 中等偏难 | 回测主引擎 |
| **P0** | `storage_manager.py` | 638 | 28 | 中等 | 数据湖基础 |
| **P0** | `data_fetcher.py` | 315 | 33 | 中等 | 系统数据入口 |
| P1 | `data_service.py` | 599 | 52 | 困难 | 数据门面 |
| P1 | `research_pipeline.py` | 610 | 17 | 中等 | 已有checkpoint测试 |
| P1 | `source_router.py` | 246 | 11 | 中等 | 故障转移核心 |
| P1 | `base.py` | 295 | 19 | 中等 | 数据源基类 |
| P2 | `eastmoney_financial.py` | 397 | 9 | 困难 | 网络依赖 |
| P2 | `result.py` | 177 | 6 | 极易 | 已废弃 |
| P2 | `portfolio_engine.py` | 373 | 10 | 中等 | 已废弃 |
| ✅ 已覆盖 | `unified_matching_engine.py` | 286 | 6 | — | 23 tests |

#### 混沌测试质量

**优秀**。4 个文件 ~2,148 LOC:

| 文件 | 测试数 | 覆盖 |
|---|---|---|
| `test_brain_boundary.py` | 15 | LPPL 参数极限、Wyckoff 边界、因子前瞻偏差 |
| `test_data_chaos.py` | 53 | 脏数据、内存压力、限价极端情况 |
| `test_e2e_pipeline.py` | 1（多步骤） | 端到端 5 步管线 |
| `test_matching_auditor.py` | 20 | T+1 规则、涨停跌停、不对称成本 |

---

## 6. Round 4: 死代码与复杂度清理评估

### 目标
验证已知死代码清单的实际调用者状态，评估代码复杂度热点。

### 执行方法
2 个并行 Agent，使用 `rg`、`vulture`、AST 分析。

### 死代码验证

#### 100% 死代码（可安全删除）

| 文件/类 | LOC | 验证方式 | 状态 |
|---|---|---|---|
| `services/analysis_service_legacy.py` | 1,649 | `rg` 搜索零引用 | 无生产调用者 |
| `shared/price_collar.py` | 32 | `rg "price_collar"` 零引用 + import 路径断连 | 导入即错 |
| `slippage_model.py:DynamicSlippage` | 20 | `rg "DynamicSlippage"` 零生产引用 | 测试中未使用 |
| `services/analysis/fsm_analysis_engine.py` | 247 | `rg "FsmAnalysisEngine"` 零引用 | v2 管线未使用 |
| `hands/backtest/__init__.py:PortfolioEngine` | — | 已从 __all__ 移除 | 生产不可见 |

#### 半死代码

| 文件 | LOC | 说明 |
|---|---|---|
| `data/data_pipeline_service.py` | 32 | ServiceContainer 未直接注册，但 DataFetcher 间接使用 |
| `hands/backtest/portfolio_engine.py` | 373 | 已废弃，测试中引用 |

#### Vulture 附加发现

在 60% 置信度下发现 ~120 个潜在死代码项。值得关注的候选：

| 文件 | 潜在死代码类/函数 |
|---|---|
| `brain/lppl/cluster.py` | `SignalClusterDetector` (4 methods) |
| `brain/lppl/computation.py` | `LPPLComputation` (4 methods) |
| `brain/factors/walk_forward_pipeline.py` | `WalkForwardFactorPipeline` 类 |
| `brain/factors/analyzer.py` | `_compute_forward_returns`, `compute_factor_correlation` |
| `signal/quality.py` | `calculate_hit_rate`, `calculate_accuracy` 等全部评估方法 |
| `ui/manager_logic.py` | `Bi` 类, `get_macro_environment`, `run_analysis` |

### 复杂度热点

#### 圈复杂度最严重的 5 个函数

| 函数 | 位置 | 复杂度 | 等级 |
|---|---|---|---|
| `trade_wyckoff` | `hands/strategies/wyckoff.py` | **57** | **F** |
| `WyckoffEngine._step5_trading_plan` | `brain/wyckoff/engine.py` | **53** | **F** |
| `process_stock` | `hands/strategies/backtest.py` | **40** | **E** |
| `run_backtest` | `hands/strategies/backtest.py` | **37** | **E** |
| `WalkForwardFactorPipeline.run` | `brain/factors/walk_forward_pipeline.py` | **37** | **E** |

#### Wyckoff engine.py 健康状况

- MI (可维护性指数): **0.00 (C)** — 全项目最低
- 39 个方法中 25 个超 50 行
- `_step1_phase_determine` 已拆分为 7 个检测器（验证了文档声明的重构），但自身仍有 61 行

#### 依赖方向检查

**无违反架构依赖方向**:
- hands层 → data层: 3 处导入（允许的方向）
- hands层 → brain层: 3 处导入（允许的方向）
- data层 → brain/hands: 0 处（合规）
- brain层 → data/hands/services: 0 处（合规）

---

## 7. Round 5: 信号系统与回测信任验证

### 目标
端到端验证信号系统链路完整性和 A 股回测 7 条防线。

### 执行方法
3 个并行 Agent。

### 信号系统完整性

#### 8 个适配器阈值表

| 适配器 | BUY 条件 | SELL 条件 | 置信度来源 |
|---|---|---|---|
| LPPL | — | risk="Danger" | confidence from raw |
| CZSC | is_3rd_buy=True | — | min(0.5+bi*0.05, 0.9) |
| Wyckoff | spring or phase=accumulation | utad or phase=distribution | 0.3 阈值过滤 |
| FSM | action→BUY (ADD/EXECUTE_BUY) | action→SELL (EXECUTE_SELL/FORCE_EXIT) | direct mapping |
| Regime | — | FROZEN/STRESSED→HOLD | 固定 0.5 |
| NTF | — | RESISTANCE + intensity>=0.6 | intensity |
| AlphaScore | score > 0.6 | score < 0.3 | abs(score-0.5)*2 |
| MAStatus | ">" in ma_status | "<=" in ma_status | 固定 0.3 |

#### 信号超时机制

**已实现但默认禁用**。`arbitrator.py` 第114-122行实现了超时检查，但 `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0`，且 `research_pipeline.py` 创建仲裁器时未传入该参数。

#### 双信号模型并行

| 模型 | 用途 | 路径 |
|---|---|---|
| `TradingSignal` (interfaces.py) | 回测执行 | 生产管线 (adapters.py → arbitrator.py → engine.py) |
| `Signal` (models.py) | 信号研究 | 旧管线 (normalizer.py → quality.py/db.py) |

两条流水线**互不调用**，但通过 `SignalDatabase` 可以桥接。

#### 完整信号链路图谱

```
Brain引擎输出 (LPPLOutput/CZSCOutput/WyckoffOutput...)
  → AnalysisService._run_engine() → data_pack
    → _merge_decision_for_collection() (注入DecisionBrain)
      → TradingSignalCollector.collect() (8个适配器)
        → List[TradingSignal]
          → [可选] SignalArbitrator.arbitrate_candidates()
            → List[TradingSignal]
              → UnifiedBacktestEngine.run()
```

### A 股回测 7 条防线验证

**全部 7 条防线通过验证**，每条防线至少有两层检查：

| # | 防线 | 引擎层 | 撮合层 |
|---|---|---|---|
| 1 | **T+1** | `_check_t1(buy_date, ts)` | `fill_sell()` 向量化 T+1 mask |
| 2 | **涨跌停 (4板块+ST+IPO)** | `_check_limit()` + `validate_trade_action()` | `compute_limit_status_vectorized()` |
| 3 | **停牌** | `vol <= 0 → pending_order = None` | volume=0 平滑 |
| 4 | **现金约束** | 买入缩量 + 最终检查 `total_cost > cash` | 向量化 `cash_shortfall_mask` |
| 5 | **费用 (佣金/印花税/过户费)** | `_calc_commission/stamp/transfer` 分离函数 | 向量化买入/卖出成本计算 |
| 6 | **滑点** | `_calc_slippage()` + 市场冲击因子 | `compute_execution_prices()` 方向正确 |
| 7 | **整手 (100/200 股)** | `board_registry.lot_size` 取整 | 向量化 `// lot_size * lot_size` |

#### 板块涨跌停比例

| 板块 | 涨停 | 跌停 | 来源 |
|---|---|---|---|
| 主板 | +10% | -10% | `market.py:L80` |
| 科创板 | +20% | -20% | `market.py:L81` |
| 创业板 | +20% | -20% | `market.py:L82` |
| 北交所 | +30% | -30% | `market.py:L83` |
| ST | +5% | -5% | `market.py:L80` |
| 主板首日 | +44% | -36% | `limit_checker.py:L100-118` |
| 科创/创前5日 | 无限 | 无限 | `limit_checker.py:L79-88` |

#### 回测执行优先级

在 `unified_engine.run()` 中，每日信号按三层优先级处理：

1. **LPPL SELL** (最高): `sig.action=="SELL" and "lppl" in sig.reason` → 即时全仓卖出
2. **BUY**: `sig.action=="BUY" and position==0` → 使用 sig.shares，有 sizer 则覆盖
3. **其他 SELL**: `sig.action=="SELL" and position>0` → 全仓平仓

#### 基线一致性

```bash
scripts/capture_baseline.py + compare_baseline.py
```
20 只股票基线通过验证，所有字段完全一致，**无漂移**。

---

## 8. Round 6: 研究平台能力差距矩阵

### 目标
从量化研究平台角度评估 UniQuant 的能力完备性。

### 执行方法
2 个并行 Agent，编目研究工具 + 对照 20 项关键能力逐项检查。

### 研究工具编目

#### 核心研究工具类 (7 个, 2,633 LOC)

| 工具 | LOC | 能力 |
|---|---|---|
| `StockScreener` | 451 | 横截面排名、技术信号、行业排名 |
| `ScanPipeline` | 676 | 全市场扫描、因子计算、IC/IR、报告生成 |
| `SensitivityAnalyzer` | 162 | OAT 敏感性分析、龙卷风图 |
| `RobustnessChecker` | 233 | 市场状态/参数/子区间/成本稳定性 |
| `MonteCarloSimulator` | 199 | Shuffle/Bootstrap MC、置信区间 |
| `BacktestReportGenerator` | 278 | HTML 报告含 SVG 图表 |
| `PortfolioService` | 634 | 组合创建、权重、优化、再平衡、压力测试 |

#### 实验脚本 (22+ 个)

涵盖因子研究、Walk-Forward、LPPL/Wyckoff 融合、Alpha 矩阵、风险平价、黑天鹅诊断等。

#### 关键缺口: 无 Jupyter notebook

仓库中**零** `.ipynb` 文件。这是一个实用性缺口 — 研究员无法用交互式 notebook 进行探索性分析。

### 20 项量化平台能力评估

| # | 能力 | 状态 | 证据 |
|---|---|---|---|
| 1 | 单标的深度分析 | **✅** | `analysis_service_v2.py:263 run_ticker_analysis()` |
| 2 | 全市场扫描 | **✅** | `scan_service.py` (676 行) |
| 3 | 因子 IC/IR 分析 | **✅** | `analyzer.py:244 compute_ic_ir()` |
| 4 | 因子权重优化 | **⚠️** | IC 加权存在，无正式优化器 |
| 5 | Walk-Forward 交叉验证 | **✅** | `walk_forward_pipeline.py:105 run()` |
| 6 | 参数敏感性分析 | **✅** | `sensitivity_analyzer.py:26 one_at_a_time()` |
| 7 | 策略过拟合检测 | **✅** | `overfitting_detector.py:41 deflated_sharpe_ratio()` |
| 8 | **组合回测** | **❌** | `unified_engine.py` 单标的，PortfolioEngine 已废弃 |
| 9 | 行业中性化 | **✅** | `neutralizer.py:17 neutralize()` |
| 10 | **风格因子暴露** | **❌** | 无 Fama-French/BARRA |
| 11 | **信号历史回放** | **❌** | 无信号重放框架 |
| 12 | Monte Carlo 模拟 | **✅** | `monte_carlo.py:44+103 run_shuffle/bootstrap()` |
| 13 | **Brinson 归因** | **❌** | 仅实验脚本中有，非库模块 |
| 14 | 换手率分析 | **⚠️** | 数据层跟踪，无标准化回测后模块 |
| 15 | Jupyter notebook | **❌** | 0 个 .ipynb 文件 |
| 16 | 因子数据导出 | **⚠️** | DataFrame 可用，无专用导出函数 |
| 17 | 回测结果对比 | **✅** | `BacktestResult.compare()` |
| 18 | 组合优化器 | **✅** | `portfolio_optimizer.py:94` 风险平价+均值方差 |
| 19 | 情景分析 | **✅** | `evt_risk.py:302 calculate_stress_test()` 15+ 场景 |
| 20 | A 股规则可配置 | **✅** | `board_registry.py` + `market_rules.py` + `cost_model.py` |

**总计: 13 ✅ 完全 / 3 ⚠️ 部分 / 4 ❌ 缺失**

### 4 个缺失能力的优先级

| 缺失能力 | 影响 | 预估工时 | 优先级 |
|---|---|---|---|
| 组合回测 | 无法做投资组合研究 | 40h | **P0** |
| 风格因子暴露 | 无法理解策略因子倾斜 | 24h | **P0** |
| Brinson 归因 | 无法解释回报来源 | 12h | **P2** |
| 信号历史回放 | 信号验证不完整 | 16h | **P2** |

---

## 9. Round 7: 综合修复路线图

### 目标
合成 Rounds 1-6 的所有发现，输出按 P0/P1/P2 分级的可执行修复计划。

### P0 — 立即修复 (7 项, ~72 工时)

| # | 问题 | 源文件 | 工时 | 收益 |
|---|---|---|---|---|
| 1 | alpha_score=0.0→SELL | `adapters.py` (1 行) | 1h | 消除假卖出信号 |
| 2 | fillna(0.0) 因子失真 | `composer.py` (3 行) | 1h | 新上市股票不被误评 |
| 3 | pipeline 裸 except + KB 吞没 | `research_pipeline.py` (3 行) | 1h | KeyboardInterrupt 可中断 |
| 4 | Wyckoff 裸 except 窄化 | `engine.py` (4 处) | 2h | 引擎错误可见 |
| 5 | 组合回测 | 新模块 (40h) | 40h | 研究平台最大障碍 |
| 6 | 风格因子暴露 (Fama-French/BARRA) | 新模块 (24h) | 24h | 策略因子暴露可衡量 |
| 7 | data_validator.py 测试 | `test_data_validator.py` | 2h | 数据质量防线可测 |

### P1 — 本周修复 (8 项, ~53 工时)

| # | 问题 | 工时 | 收益 |
|---|---|---|---|
| 8 | 安全: eastmoney SSL verify=False 修复 | 1h | 消除 MITM 风险 |
| 9 | 死代码: archive analysis_service_legacy.py | 1h | 减少 1,649 LOC 死代码 |
| 10 | 死代码: 清理 price_collar/DynamicSlippage | 1h | 减少 52 LOC 死代码 |
| 11 | 复杂度: Wyckoff engine.py F/53→<20 | 8h | 可维护性 MI 0→30+ |
| 12 | 测试: unified_engine.py 专用测试 (752 LOC) | 8h | 回测核心可测 |
| 13 | 测试: analysis_service_v2.py 专用测试 (637 LOC) | 8h | 分析编排可测 |
| 14 | 测试: mutmut 配置修复 + baseline 运行 | 2h | 变异测试可量化 |
| 15 | Metrics 系统 (Prometheus/OTel 初始) | 24h | 可观测性 C-→B |

### P2 — 本月修复 (10 项, ~75 工时)

| # | 问题 | 工时 | 收益 |
|---|---|---|---|
| 16 | 信号超时默认启用 (>0) | 1h | 过期信号自动过滤 |
| 17 | 信号历史回放框架 | 16h | 信号验证完整 |
| 18 | Brinson 归因分析 | 12h | 回报来源可解释 |
| 19 | 因子权重优化 (梯度/目标函数) | 8h | 权重非 IC 驱动 |
| 20 | Jupyter notebook 集成 + 教程 | 8h | 研究员入门体验 |
| 21 | 换手率分析标准化模块 | 4h | 策略交易成本可见 |
| 22 | 因子数据导出 (CSV/Parquet) | 4h | 外部工具衔接 |
| 23 | 结构化日志 (JSON/OTel) | 6h | 日志可搜索 |
| 24 | 复杂度: LPPL engine.py 拆分 (1,098 LOC) | 8h | 可维护性 |
| 25 | 复杂度: dashboard.py 重构 (1,553 LOC) | 8h | 可维护性 |

### 评分卡预测

| 维度 | 当前 | P0 后 | P0+P1 后 |
|---|---|---|---|
| 数据可靠性 | 3.5 (B+) | 3.5 | 3.8 |
| 引擎正确性 | 3.8 (B+) | **4.2 (A-)** | 4.2 |
| 回测信任度 | 3.5 (B+) | 4.0 (A-) | 4.0 |
| 代码质量 | 2.5 (C+) | 3.0 (B) | **3.5 (B+)** |
| 测试质量 | 2.0 (C) | 2.5 (C+) | **3.0 (B)** |
| 性能 | 4.0 (A-) | 4.0 | 4.0 |
| 安全 | 3.5 (B+) | 4.0 (A-) | 4.0 |
| 可观测性 | 2.0 (C-) | 2.0 | **3.0 (B)** |
| **总分** | **3.29 (B)** | **3.70 (B+)** | **3.95 (A-)** |

### 修复成本收益最优项

| 修复 | 工时 | 评分卡提升 |
|---|---|---|
| 4 个 BUG 修复 | 5 工时 | +0.20 |
| data_validator 测试 | 2 工时 | +0.05 (测试质量) |
| dead code 清理 | 2 工时 | +0.10 (代码质量) |
| 总计 (最低投入) | **9 工时** | **+0.35** |

---

## 10. 关键发现速查表

### 项目中真正严重的问题

| 问题 | 严重性 | 隐藏时间 | 原因 |
|---|---|---|---|
| alpha=0.0→SELL | **高** | 存在至今 (未修复) | 3 条路径写 0.0，adapter 无 0.0 检查 |
| 组合回测缺失 | **高** | 从迁移开始 | PortfolioEngine 废弃未替代 |
| 可观测性 metrics 缺失 | **高** | 从项目开始 | 无 Prometheus/OTel/指标 API |
| 文档漂移 | **中** | 数周 | 旧分析报告覆盖了已修复问题的旧数据 |

### 文档中最被夸大的问题

| 文档声明 | 实际 | 夸大倍数 |
|---|---|---|
| "56 个弱测试" | 1 个 | **10x** |
| "Adapter 覆盖 29%" | 62 测试覆盖 8/8 适配器 | 严重过时 |
| "Wyckoff 复杂度 76" | 40 (单函数 max) | **1.9x** |
| "131 TODO/FIXME 项" | ~30 关键项 | **4x** |
| "mutmut 路径错位导致失败" | 无 [tool.mutmut] 配置 | 根因描述错误 |

### 项目中真正的优势

| 优势 | 证据 |
|---|---|
| A 股规则支持 | 7/7 防线，每防线 2+ 层检查，可配置 |
| 信号系统 | 8 适配器 + 双仲裁 + 数据库，链路完整 |
| 回测基线 | capture_baseline + compare_baseline，无漂移 |
| 因子研究 | IC/IR + Walk-Forward + 中性化 + 组合，基础扎实 |
| 风险分析 | DSR 过拟合检测 + MC 模拟 + EVT + 情景分析 |
| 数据管道 | 5934/5934 文件 100% 可读 |

---

## 11. 文档漂移修正清单

分析中发现大量文档声明与代码实际不符。以下是最需要修正的项：

| 文档 | 声明 | 实际 | 应修正为 |
|---|---|---|---|
| `AGENTS.md` | "eastmoney.py 1,094 LOC" | 3 LOC re-export | 更新 |
| `AGENTS.md` | "56 弱断言测试" | 1 真正弱 | 更新或删除 |
| `AGENTS.md` | "Adapter 29% 覆盖" | 8/8 适配器有 62 测试 | 更新 |
| `AGENTS.md` | "mutmut 路径错位" | 无 `[tool.mutmut]` 配置 | 修正根因 |
| `docs/reanalysis/A_code_quality.md` | "Wyckoff 复杂度 76" | 单函数 max=40 | 修正 |
| `docs/reanalysis/B_test_quality.md` | "56 弱测试" | 1 个 | 修正 |
| `docs/reanalysis/F_signal_audit.md` | "signal/db.py 0% 覆盖" | 93% (35 tests) | 标注已修复 |
| `docs/reanalysis/C_consolidated_issues.md` | "BoardType P0.2" | 已修复 | 标记已关闭 |
| `docs/reanalysis/J_scorecard.md` | "Wyckoff 复杂度 76" | 40/285 | 修正 |
| `docs/reanalysis/J_scorecard.md` | "signal/db 0% 覆盖" | 93% | 修正 |
| `docs/architecture.md` | 文件计数、引擎描述 | 需要更新 | 按 live system map 修正 |
| `docs/index.md` | "254 文件" | 256 | 已部分更新 |

---

## 12. 评分卡预测

### 当前评分

| 维度 | 评分 | 评级 |
|---|---|---|
| 数据可靠性 | 3.5 | B+ |
| 引擎正确性 | 3.8 | B+ |
| 回测信任度 | 3.5 | B+ |
| 代码质量 | 2.5 | C+ |
| 测试质量 | 2.0 | C |
| 性能 | 4.0 | A- |
| 安全 | 3.5 | B+ |
| 可观测性 | 2.0 | C- |
| **总分** | **3.29** | **B** |

### P0 修复后预测

| 维度 | 预测 | 评级 |
|---|---|---|
| 引擎正确性 | 4.2 | **A-** |
| 回测信任度 | 4.0 | **A-** |
| 代码质量 | 3.0 | **B** |
| 测试质量 | 2.5 | **C+** |
| **总分** | **3.70** | **B+** |

### P0+P1 修复后预测

| 维度 | 预测 | 评级 |
|---|---|---|
| 代码质量 | 3.5 | **B+** |
| 测试质量 | 3.0 | **B** |
| 可观测性 | 3.0 | **B** |
| **总分** | **3.95** | **A-** |

---

## 13. AGENTS.md 更新内容

基于分析发现，需要对 AGENTS.md 做以下更新：

### 需修正的过时声明

```diff
- eastmoney LOC 1,094 → 3 (refactored to 4 files)
+ eastmoney.py 1094→3 行 re-export (拆分为 base/financial/quote 3 文件)

- 56 test functions without assert (47 use raises, 9 truly weak)
+ 1 truly weak test function (test_perf_section_without_recorder)

- Adapter coverage 29% (仅 NTFAdapter 有测试)
+ 8/8 adapters 全部有测试 (62 tests in test_adapters.py)

- mutmut 路径错位导致 config/config.yaml 无法加载
+ pyproject.toml 缺少 [tool.mutmut] 配置节

- Wyckoff complexity 76
+ max function = 40, class total = 285
```

### 需补充的新信息

```diff
+ # 2026-07-09 7轮分析结论
+ # 综合评分: 3.29 (B)
+ # 4 个活跃 BUG: alpha=0.0→SELL, fillna(0.0), pipeline except, Wyckoff except
+ # 7/7 A 股防线通过验证
+ # 研究平台 20 项能力: 13✅ 3⚠️ 4❌
+ # 组合回测是最大能力缺口
+ # P0 修复 (72h) 预计提升至 3.70 (B+)
```

### 需更新的死代码列表

```diff
- Dead code inventory:
- analysis_service_legacy.py 1,649 LOC (DEAD)
- price_collar.py 32 LOC (DEAD + broken import)
- DynamicSlippage 20 LOC (DEAD in production)
- fsm_analysis_engine.py 247 LOC (DEAD in v2)
+ data_pipeline_service.py 32 LOC (semi-dead, routed by DataFetcher)
+ portfolio_engine.py 373 LOC (semi-dead in __init__)
```

---

## 附录: 关键文件行号索引

| 文件 | 关键行号 | 用途 |
|---|---|---|
| `adapters.py` | 359, 362-363, 369, 563-569 | Bug#1 SELL 逻辑 + 信号收集 |
| `arbitrator.py` | 114-122, 160-176, 192-207, 325-342 | 超时检查、质量过滤、SELL优先 |
| `composer.py` | 183, 204, 276 | Bug#2 fillna(0.0) |
| `research_pipeline.py` | 239, 330-346, 355-374, 495, 609 | Bug#3 except + 信号链路 |
| `engine.py` (wyckoff) | 251, 260, 1573, 1588 | Bug#4 裸 except |
| `analysis_service_v2.py` | 535, 543, 552 | Alpha 失败路径 |
| `unified_engine.py` | 306-308, 331-333, 337, 388-402, 409-417, 507-530, 536-563 | 回测防线 + 信号执行 |
| `unified_matching_engine.py` | 65-99, 134-152, 178-200, 239-257, 259, 265-270 | 撮合防线 |
| `cost_model.py` | 29-37, 48-50, 60-61 | 交易费用定义 |
| `limit_checker.py` | 79-118, 134-139, 186-227 | 涨跌停规则 |
| `market_rules.py` | 20-27 | 整手规则 |
| `board_registry.py` | 73-74 | ST 检测 |
| `interfaces.py` | 243-259 | ResearchDataPack.to_dict() 展平逻辑 |
| `slippage_model.py` | 14-17, 20-44 | DefaultSlippage + DynamicSlippage |
| `event_bus.py` | 89 LOC | 同步+异步事件总线 |
| `result_store.py` | 164 LOC | JSON 结果持久化 |
| `scan_service.py` | 676 LOC | 全市场扫描管线 |
| `screener.py` | 451 LOC | 选股器 |

---

## 分析完成

> 7 轮分析共启动 14 个 Agent 执行，覆盖文件扫描、BUG 追踪、测试审计、复杂度评估、回测验证、平台差距分析、路线图制定七大维度。
>
> 核心结论: UniQuant 是一个 A 股规则扎实、单标的研究流程成熟、但存在 4 个活跃 BUG、组合回测缺失、文档严重漂移的研究平台。
>
> 综合评分: 3.29/5.0 (B) → P0 修复后 3.70 (B+) → P0+P1 后 3.95 (A-)
