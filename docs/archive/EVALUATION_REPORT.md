# UniQuant 文档与代码综合评估报告

> **目标场景:** mootdx 数据基座 + 本地数据湖 + 通达信财务数据 + 策略分析与回测
>
> **生成日期:** 2026-05-26 (历史文档, v0.3 快照) | **当前版本**: v0.6.x (263 源文件, 76 测试文件)
>
> **文档版本:** v1.0

---

## 目录

1. [总体评估](#一总体评估)
2. [逐包差异分析](#二逐包差异分析)
3. [文档可信度评估](#三文档可信度评估)
4. [需求 vs 现状对标](#四需求-vs-现状对标)
5. [阻塞链分析](#五阻塞链分析)
6. [执行路径建议](#六执行路径建议)
7. [风险与建议](#七风险与建议)
8. [快速验证命令](#八快速验证命令)

---

## 一、总体评估

### 1.1 一句话结论

**文档描述的是 v2.0 目标架构（~160 文件, ~50K LOC），当前代码处于 v0.3 状态（44 文件, ~12.6K LOC）。完成度 ~28%。** 若要实现 mootdx 数据基座 + 本地数据湖 + 策略回测的全流程，需经历从 44 文件到 ~160 文件的系统迁移，核心工作量在 `data/` 全层（40+ 文件）和 `hands/回测`（19+ 文件）。

### 1.2 大盘对比

| 维度 | 文档描述 (目标状态) | 实际现状 | 缺口 |
|------|---------------------|----------|------|
| 源码文件数 | ~160+ 文件 | **44 文件** | **72% 缺失** |
| 源码行数 | ~50K LOC | ~12.6K LOC (wc -l 核实) | **~75% 缺失** |
| 测试文件数 | 65+ 文件 | **10 文件** (1 个可运行) | **~85% 缺失** |
| 测试用例数 | 532+ 通过 | **65 个测试函数 (10 个测试类)** | **~88% 缺失** |
| 包完整性 | 8 大包全覆盖 | **1 包完整 (shared/), 2 包不存在 (data/, signal/)** | **25% 完整** |
| import 链 | 全链可导入 | **`import uniquant.services` 崩溃** (顶层 `import uniquant` 成功但触及 services 即失败) | **Phase 0 阻塞** |

### 1.3 百分比完成度

```
shared/     ████████████████░░░░  79%  (23/29 文件)
services/   █████████░░░░░░░░░░░  46%  (11/24 文件)
brain/      ███░░░░░░░░░░░░░░░░░  17%  (5/30+ 文件)
ui/         █████░░░░░░░░░░░░░░░  25%  (2/8 文件)
risk/       ███░░░░░░░░░░░░░░░░░  14%  (1/7 文件)
hands/      █░░░░░░░░░░░░░░░░░░░   5%  (1/19+ 文件，空壳)
data/       ░░░░░░░░░░░░░░░░░░░░   0%  (0/40+ 文件)
signal/     ░░░░░░░░░░░░░░░░░░░░   0%  (0/6 文件)
----------------------------------------
整体        ██████░░░░░░░░░░░░░░  28%
```

---

## 二、逐包差异分析

### 2.1 data/ — 数据层（你的核心关注点）

**文档承诺:** 8 个子包, 40+ 文件, ~14K LOC
**实际存在:** **0 文件 (0%)** 🔴

这意味著整个数据基础设施完全不存在，包括：

| 功能 | 文档位置 | 实际 | 来源 | 行数 |
|------|---------|------|------|------|
| mootdx 离线数据源 | RESTRUCTURE_PLAN.md §2.1 | ❌ | 需新建 | ~100 |
| mootdx 在线数据源 | RESTRUCTURE_PLAN.md §2.2 | ❌ | 需新建 | ~80 |
| mootdx 复权因子管理器 | RESTRUCTURE_PLAN.md §2.3 | ❌ | 需新建 | ~120 |
| StorageManager (Parquet 湖) | packages/data.md lake/ | ❌ | 从 TDX 迁移 | ~592 |
| 分钟线存储 (1min/5min) | packages/data.md lake/ | ❌ | 从 TDX 迁移 | — |
| 日线→周线/月线合成 | RESTRUCTURE_PLAN.md §2.5 | ❌ | 需新建 | ~50 |
| 财务数据导入 | packages/data.md services/ | ❌ | 从 TDX 迁移 | ~433 |
| DataFetcher | packages/data.md 全局 | ❌ | 从 TDX 迁移 | ~268 |
| SourceRouter (多源路由) | packages/data.md managers/ | ❌ | 从 TDX 迁移 | ~246 |
| TDX 数据解析器 | packages/data.md parsers/ | ❌ | 从 TDX 迁移 | ~561 |
| 数据管道 (校验/清洗/复权) | packages/data.md pipeline/ | ❌ | 从 TDX 迁移 | ~300+ |
| 同步脚本 | RESTRUCTURE_PLAN.md §2.6 | ❌ | 需新建 | ~400 |

#### mootdx 集成现状

pyproject.toml 依赖声明: `mootdx>=0.11.7,<1.0.0` ✅

**但整个 43 个源文件中，零行 mootdx 使用代码：**
- `grep -r "mootdx" src/` → **0 结果**
- `grep -r "Reader" src/` → **0 相关结果**（无 `mootdx.reader.Reader`）
- `grep -r "Quotes" src/` → **0 相关结果**（无 `mootdx.quotes.Quotes`）

#### 关键依赖链（全部不存在）

```
mootdx 在线/离线数据源 (需新建)
  → SourceRouter 多源路由 + 故障转移 (从 TDX 迁移)
    → DataCleaner → DataValidator → DataAdjuster (从 TDX 迁移)
      → StorageManager Parquet 湖: daily/1mins/5mins/ (从 TDX 迁移)
        → DataFetcher 统一入口 (从 TDX 迁移)
          → services/DataService 上层门面 (从 TDX 迁移)
```

---

### 2.2 shared/ — 基础设施（较完整）

**文档承诺:** 29 个文件
**实际存在:** **23 个文件 (79%)** ✅

| 模块 | 状态 | 行数 | 说明 |
|------|------|------|------|
| constants.py | ✅ | 1139 | 超长单文件，内容完整 |
| exceptions.py | ✅ | — | 完整异常层次 ~40+ 子类 |
| config_loader.py | ✅ | — | GlobalConfig + 双重检查锁单例 |
| cache/ (4 文件) | ✅ | — | MemoryCacheBackend + DiskCacheBackend |
| logger_factory.py | ✅ | — | |
| interfaces.py | ✅ | — | Protocol 定义 |
| retry_decorator.py | ✅ | — | retry/retry_with_fallback |
| cost_model.py | ✅ | — | 佣金/印花税/滑点 SST |
| slippage_model.py | ✅ | — | DefaultSlippage + DynamicSlippage |
| limit_checker.py | ✅ | — | 主板 10%/科创 20%/北交所 30% |
| utils.py | ✅ | — | with_timeout/safe_execute 等 |
| analysis_result.py | ✅ | — | AnalysisResult + Builder |
| **缺失: parallel.py** | ❌ | — | 并行计算工具 |
| **缺失: market_rules.py** | ❌ | — | 需从 TDX 迁移 |
| **缺失: 4 个常量子模块** | ❌ | — | 可选拆分 (market/risk/data/performance) |

**对你需求的影响:** shared 包已基本就绪——配置加载、异常处理、缓存、重试、A 股规则检查等上层依赖可直接使用。这是你最稳固的基石。

---

### 2.3 brain/ — 分析引擎

**文档承诺:** 10 个子包, 30+ 文件
**实际存在:** **5 个文件 (17%)** 🟡

| 子包 | 你需要的功能 | 存在 | 行数 | 可立即使用？ |
|------|-------------|------|------|------------|
| `czsc/` | 缠论分析引擎 (笔/段/中枢) | ✅ 1 文件 | 623 | ✅ 依赖 `czsc` 第三方库 |
| `fsm/` | 有限状态机 + DecisionBrain | ✅ 1 文件 | 656 | ⚠️ 但`from ..indicators import Indicators` 失败 (Phase 0.6 修复) |
| `lppl/` | LPPL 泡沫检测 | ⚠️ 3/9 文件 | 992 | ⚠️ __init__.py 幽灵导入 7 个子模块 |
| `ntf/` | 国家队因子 (ETF 脉冲检测) | ❌ 0/1 | ~200 | 需从 TDX 迁移 |
| `regime/` | 市场状态检测 | ❌ 0/1 | ~250 | 需从 TDX 迁移 |
| `wyckoff/` | 威科夫量价分析 | ❌ 0/11 | ~1200 | **完全缺失**, 依赖多 |
| `alpha_decoupler/` | Alpha 解耦器 | ❌ 0/1 | ~350 | 需从 TDX 迁移 |
| `factors/` | 因子系统 (8 子文件) | ❌ 0/8 | ~1500 | 需从 TDX 迁移 |
| `indicators/` | 技术指标库 (10 方法) | ❌ 0/1 | ~404 | 需从 TDX 迁移 |
| `screener/` | 全市场扫描器 | ❌ 0/1 | ~400 | 需从 TDX 迁移 |

#### 对你需求的影响

- CZSC/FSM/LPPL 可直接用于策略信号生成（修复导入后）
- NTF/Regime/Indicators 迁移量小（~3 文件, ~850 行），**建议优先迁移**
- Factors 和 Wyckoff 迁移量大，可根据需要决定优先级
- **如果只用 CZSC/LPPL/FSM，brain 层可满足基本需求**

---

### 2.4 hands/ — 回测与策略（你的核心需求）

**文档承诺:** 19+ 文件 (backtest/ 12 + strategies/ 9)
**实际存在:** **1 个空壳文件 (5%)** 🔴

| 功能 | 文档描述 | 实际 | 来源 | 行数 |
|------|---------|------|------|------|
| BacktestEngine | 4 种回测模式 | ❌ 不存在 | 从 TDX 迁移 | ~521 |
| UnifiedMatchingEngine | T+1/涨跌停/滑点向量化 | ❌ 不存在 | 从 TDX 迁移 | ~300+ |
| PortfolioEngine | 组合回测 | ❌ 不存在 | 从 TDX 迁移 | ~300+ |
| MonteCarloSimulator | 统计显著性检验 | ❌ 不存在 | 从 TDX 迁移 | ~200 |
| OverfittingDetector | DSR/PBO 计算 | ❌ 不存在 | 从 TDX 迁移 | ~200 |
| RobustnessChecker | 稳健性检查 | ❌ 不存在 | 从 TDX 迁移 | ~200 |
| SensitivityAnalyzer | 参数敏感性 | ❌ 不存在 | 从 TDX 迁移 | ~200 |
| TradeAnalyzer | 交易分析 | ❌ 不存在 | 从 TDX 迁移 | ~200 |
| BaseStrategy (基类) | 策略基类 | ❌ 不存在 | 从 TDX 迁移 | ~147 |
| 5 个内置策略 | ma_cross/wyckoff/regime/reversal/fsm | ❌ 不存在 | 从 TDX 迁移 | ~300+ |
| Reporter/ResultsManager | 报告/结果管理 | ❌ 不存在 | 从 TDX 迁移 | ~512 |

**对你需求的影响:** **回测功能目前完全不可用。** hands/ 迁移是独立操作，拷贝 ~19 文件 + import 适配，估算 20-30 分钟。但需等待 data 层就绪（回测需要数据输入）。

---

### 2.5 services/ — 服务层

**文档承诺:** 24 个文件
**实际存在:** **11 个文件 (46%)** 🟡

| 关键问题 | 描述 | 严重性 | 修复方案 |
|---------|------|--------|---------|
| `__init__.py` 幽灵导入 | 导入 8 个不存在的模块 | 🔴 **导致 `import uniquant.services` 崩溃** (所有下游分析引擎不可用) | Phase 0.1: 删除幽灵导入 |
| `analysis/__init__.py` 幽灵导入 | 导入 signal_service + wyckoff | 🔴 | Phase 0.3: 删除幽灵导入 |
| `analysis_service.py` (1650 行) | 引用不存在的 DataService | 🟡 需 data 层就绪后才可测试 | Phase 1C |
| `engine_factory` 参数错配 | 传 `data_service` 给引擎, 引擎期望 `orchestrator` | 🔴 所有引擎无法初始化 | Phase 1A.9 |
| DataService/CacheCoordinator/ScanService | 8 个核心服务不存在 | 🔴 | Phase 1C |
| NTF/Regime 分析引擎适配器 | 引用不存在的 brain 模块 | 🟡 | Phase 1A.8 |

**对你需求的影响:** services/ 目前完全不可用。必须先执行 Phase 0 修复幽灵导入，然后等 data/ 层就绪后才能恢复。

---

### 2.6 signal/ — 信号系统

**文档承诺:** 6 个文件 (models, normalizer, aggregator, quality, db)
**实际存在:** **0 文件 (0%)** 🔴

这是一个相对小的包（~906 LOC），docs 描述完整，可直接参考 packages/signal.md 新建或从 TDX 迁入。

---

### 2.7 risk/ — 风险管理

**文档承诺:** 7 个文件
**实际存在:** **1 个文件 (14%)** 🔴

| 文件 | 状态 | 行数 | 来源 |
|------|------|------|------|
| drawdown_analyzer.py | ✅ 已就绪 | — | 原生，全向量化 NumPy |
| evt_risk.py | ❌ 缺失 | ~391 | 从 TDX 迁移 |
| sizer.py | ❌ 缺失 | ~269 | 从 TDX 迁移 |
| portfolio_optimizer.py | ❌ 缺失 | ~366 | 从 TDX 迁移 |
| structural.py | ❌ 缺失 | — | 从 TDX 迁移 |
| historical_risk.py | ❌ 缺失 | — | 兼容桩 |

**对你需求的影响:** DrawdownAnalyzer 可用。仓位计算、组合优化等迁移量小（~3 文件, ~1000 行），**建议优先迁移**，因为回测和策略都依赖仓位管理。

---

### 2.8 ui/ — 用户界面

**文档承诺:** 8 个文件
**实际存在:** **2 个文件 (25%)** 🔴

| 文件 | 状态 | 行数 | 说明 |
|------|------|------|------|
| dashboard.py | ✅ 存在 | 1518 | 但引用了不存在的 components |
| health_check.py | ✅ 可用 | — | 模块级健康检查 |

---

## 三、文档可信度评估

### 3.1 可信度等级

| 等级 | 含义 | 文件数 |
|------|------|--------|
| ✅ **完全可信** | 与代码一致，可直接作为开发参考 | **4** |
| ⚠️ **部分可信** | 架构设计合理，但文件/功能不完整 | **9** |
| ❌ **不可信** | 引用不存在的模块，代码示例无法运行 | **10** |

### 3.2 ✅ 完全可信（可与实际代码交叉验证）

| 文档 | LOC | 说明 |
|------|-----|------|
| `reference/constants.md` (950) | ⭐⭐⭐⭐⭐ | 直接从 constants.py 精确提取 |
| `reference/exceptions.md` (626) | ⭐⭐⭐⭐⭐ | 异常层次与 exceptions.py 完全一致 |
| `reference/a_share_constraints.md` (620) | ⭐⭐⭐⭐ | 基于 shared/ 已有代码，经 limit_checker 验证 |
| `packages/shared.md` (405) | ⭐⭐⭐⭐ | 与实际 23/29 文件高度匹配 |

### 3.3 ⚠️ 部分可信（设计方向正确，但实现不全）

| 文档 | LOC | 可信度 | 差距 |
|------|-----|--------|------|
| `architecture.md` (1047) | ⭐⭐⭐ | 四层架构是最佳设计参考，但描述目标状态 | |
| `packages/brain.md` (618) | ⭐⭐ | 10 子包结构准确，但仅 5/30 文件存在 | |
| `packages/services.md` (423) | ⭐⭐ | DAG 容器设计正确，10/24 文件存在 | |
| `packages/risk.md` (290) | ⭐⭐ | 架构正确，1/7 文件存在 | |
| `packages/ui.md` (309) | ⭐⭐ | 架构正确，2/8 文件存在 | |
| `RESTRUCTURE_PLAN.md` (1378) | ⭐⭐⭐⭐ | **最重要的执行文档**，Phase 0-4 路径清晰 | |
| `guides/configuration.md` (461) | ⭐⭐⭐⭐ | config_loader 已就绪，可实际使用 | |
| `STATUS.md` (99) | ⭐⭐⭐⭐ | 已更新为实际状态 | |
| `index.md` (118) | ⭐⭐⭐⭐ | 已更新为实际状态 | |

### 3.4 ❌ 不可信（代码示例无法运行）

| 文档 | LOC | 问题 |
|------|-----|------|
| `packages/data.md` (510) | 0/40+ 文件存在，整个包不存在 |
| `packages/hands.md` (329) | 1/19+ 文件存在，仅空壳 |
| `packages/signal.md` (238) | 0/6 文件存在，整个包不存在 |
| `guides/quickstart.md` (240) | 所有步骤引用的模块不存在 |
| `guides/backtest.md` (506) | BacktestEngine/UnifiedMatchingEngine 等全部不存在 |
| `guides/factors.md` (713) | FactorRegistry/Analyzer/Composer 等全部不存在 |
| `guides/strategies.md` (663) | BaseStrategy/5 个内置策略全部不存在 |
| `guides/data_sources.md` (434) | DataSource/SourceRouter 等全部不存在 |
| `development/testing.md` (381) | 声称 65+ 文件, 实际 10 文件, 仅 1 个可运行 |
| `development/project_structure.md` (543) | 文件清单基于目标状态，与实际严重不符 |

---

## 四、需求 vs 现状对标

### 4.1 你的目标 vs 实际差距

| 需求项 | 当前状态 | 所需文件数 | 工作量估计 | 优先级 |
|--------|---------|-----------|-----------|--------|
| **mootdx 作为数据基座** | 🔴 0 行使用代码 | 3 文件新建 | ~2h | **P0** |
| **本地数据湖 (1min/5min/daily)** | 🔴 不存在 | 40+ 文件迁移 | ~1.5h | **P0** |
| **日线→周线/月线合成** | 🔴 不存在 | 扩展 StorageManager | ~0.5h | **P1** |
| **通达信财务数据** | 🔴 不存在 | 6 文件迁移 | ~0.5h | **P1** |
| **mootdx 复权因子** | 🔴 不存在 | 1 文件新建 | ~0.5h | **P1** |
| **数据同步脚本** | 🔴 不存在 | 4 脚本新建 | ~0.5h | **P1** |
| **CZSC 缠论分析** | ✅ 可用 | 0 | 0 | **已就绪** |
| **FSM 状态机** | ⚠️ 需修复导入 | 0 | Phase 0.6 | **已就绪** |
| **LPPL 泡沫检测** | ⚠️ 需修复导入 | 6 文件补充 | Phase 0.2 + 1D | **P2** |
| **NTF 国家队因子** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **Regime 市场状态** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **技术指标库** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **仓位管理 (PositionSizer)** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **组合优化** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **回测引擎** | ❌ 不存在 | 19+ 文件迁移 | ~30min | **P2** |
| **内置策略** | ❌ 不存在 | 5+ 文件迁移 | ~15min | **P2** |

### 4.2 最小可行路径（MVP）

如果你只需要 mootdx 数据 + 简单回测，最小路径为：

```
Phase 0: 修复导入链 (0.5h)
  → 让 import uniquant 可工作

Phase 1B (精简版): 仅迁移核心 data 文件 (1h)
  → StorageManager, DataFetcher, SourceRouter, 数据管道
  → 不迁所有 7 个数据源，只迁 tdx_source 并新建 mootdx 源

Phase 2: mootdx 集成 (2.5h)
  → mootdx_local.py, mootdx_online.py
  → mootdx_factor_manager.py
  → StorageManager 周线/月线合成
  → 同步脚本

Phase 1E (精简版): 仅迁移核心回测 (0.5h)
  → BacktestEngine, UnifiedMatchingEngine, BacktestResult
  → 不迁 PortfolioEngine/MonteCarlo/策略

总计: ~4.5h
结果: 可用的 mootdx 数据湖 + 单资产回测
```

---

## 五、阻塞链分析

### 5.1 依赖关系图

```
                      ┌──────────────────────────┐
                      │  Phase 0: 修复导入链      │ ← 必须先执行
                      │  修复 services/__init__.py  │
                      │  修复 brain/lppl/__init__.py│
                      │  创建缺失 __init__.py       │
                      └────────────┬─────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    v              v              v
         ┌─────────────────┐  ┌──────────┐  ┌──────────┐
         │ Phase 1A: Shared │  │Phase 1B: │  │Phase 1D: │
         │ brain/indicators │  │data/ 全层│  │LPPL/Factors│
         │ risk/ 3 文件     │  │40+ 文件  │  │14 文件    │
         └────────┬────────┘  └─────┬────┘  └──────────┘
                  │                 │
                  v                 v
         ┌──────────────────────────────────┐
         │ Phase 2: mootdx 适配             │
         │ 3 文件新建 + StorageManager 扩展  │
         │ 4 同步脚本                       │
         └──────────────┬───────────────────┘
                        │
                        v
         ┌──────────────────────────────────┐
         │ Phase 1E: hands/ 回测迁移        │
         │ 19+ 文件 (backtest + strategies) │
         └──────────────────────────────────┘
```

### 5.2 5 大阻塞点

| # | 阻塞 | 影响面 | 修复方法 | 时间 |
|---|------|--------|---------|------|
| 1 | `services/__init__.py` 8 个幽灵导入 | **`import uniquant.services` 崩溃** (所有下游引擎不可用) | Phase 0.1: 删除导入 | 5min |
| 2 | `brain/lppl/__init__.py` 7 个幽灵导入 | LPPL 引擎无法使用 | Phase 0.2: 精简导入 | 5min |
| 3 | `brain/fsm/fsm.py` indicators 导入失败 | FSM/DecisionBrain 崩溃 | Phase 0.6: try/except fallback | 5min |
| 4 | `data/` 整个包不存在 | 无数据服务，无回测 | Phase 1B: 从 TDX 迁移 | 1.5h |
| 5 | `engine_factory` 参数错配 | 所有分析引擎无法初始化 | Phase 1A.9: 修复构造函数 | 10min |

---

## 六、执行路径建议

### 6.1 推荐执行顺序

```
Phase 0 (紧急修复)       [0.5h]  ← 立即执行
  └─ 恢复导入链，让 import 工作

Phase 1A (基础迁移)     [0.5h]  ← 立即执行
  └─ indicators, ntf, regime, alpha_decoupler
  └─ risk/sizer, evt_risk, portfolio_optimizer

Phase 1B (Data 全层)    [1.5h]  ← 你的核心关注
  └─ 40+ 文件从 TDX 迁移
  └─ StorageManager, DataFetcher, SourceRouter, 数据管道

Phase 2 (mootdx 适配)   [2.5h]  ← 你的核心关注
  └─ mootdx_local/online 数据源
  └─ mootdx_factor_manager
  └─ 周线/月线合成
  └─ 同步脚本

Phase 1C (Services)     [0.5h]
  └─ 8 个缺失服务迁移
  └─ 恢复完整 __init__.py

Phase 1E (回测)          [0.3h]  ← 你的核心关注
  └─ BacktestEngine, UnifiedMatchingEngine
  └─ 内置策略

Phase 1D (补全 brain)   [0.5h]
  └─ LPPL 子模块, 因子系统, screener

Phase 3 (验证)           [1.5h]
  └─ 迁入 68 测试文件, import 适配
  └─ pytest 通过率 > 80%

总计: ~8 小时
```

### 6.2 并行执行可能性

```
Phase 1A ──→ Phase 1D    (可并行，无依赖)
Phase 1B ──→ Phase 2     (串行：mootdx 依赖 data 层)
Phase 1B ──→ Phase 1E    (串行：回测依赖数据)
Phase 1C ──→ Phase 1E    (可并行，无直接依赖)
```

---

## 七、风险与建议

### 7.1 风险矩阵

| 风险 | 等级 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|---------|
| TDX 项目源码不可用 | 🔴 高 | 中 | 极大 (75% 迁移依赖 TDX) | 先验证 `/home/james/Documents/Project/TDX/` |
| 测试不通过 | 🟡 中 | 高 | 中 (9/10 测试导入失败) | 先修 Phase 0，再逐个修复 |
| mootdx API 变更 | 🟡 中 | 低 | 中 | 锁定版本 `~0.11.7` |
| 缺少 pybreaker/tenacity | 🟡 中 | 高 | 中 (SourceRouter 依赖) | 加入 pyproject.toml |
| 文档与代码差距继续扩大 | 🟡 中 | 高 | 低 | 每完成 Phase 更新文档 |
| wyckoff 迁移量过大 | 🟡 中 | 中 | 低 (11 文件 ~1200 行) | 可推迟到 Phase 1D 以后 |

### 7.2 建议

1. **立即执行 Phase 0** — 修复幽灵导入后才能真正评估 import 链健康状况
2. **先验证 TDX 源码** — 运行 `ls /home/james/Documents/Project/TDX/src/` 确认 145 文件可用
3. **优先建数据层 (Phase 1B + Phase 2)** — 这是所有需求的基础
4. **mootdx 适配与 TDX 迁移可部分并行** — 新建 mootdx 数据源不依赖 TDX
5. **guides/ 暂不可信** — 开发中不要参考 guides/ 的代码示例
6. **以 RESTRUCTURE_PLAN.md 为主要执行文档** — 这是最完整的执行计划
7. **每次迁移一个包后立即更新 package doc** — 防止文档差距扩大
8. **Wyckoff 暂缓** — 11 文件 ~1200 行，且无 import 依赖，可最后处理

---

## 八、快速验证命令

### Phase 验收标准

```bash
# Phase 0 验收: import 链修复
python -c "import uniquant; import uniquant.shared; import uniquant.brain.fsm; print('Phase 0 OK')"

# Phase 1A 验收: brain 基础层
python -c "
from uniquant.brain.indicators import Indicators
from uniquant.risk.evt_risk import EVTRisk
from uniquant.risk.sizer import PositionSizer
print('Phase 1A OK')
"

# Phase 1B 验收: data 层
python -c "
from uniquant.data.data_fetcher import DataFetcher
from uniquant.data.lake.storage_manager import StorageManager
print('Phase 1B OK')
"

# Phase 2 验收: mootdx 集成
python -c "
from mootdx.reader import Reader
r = Reader.factory(market='std', tdxdir='/path/to/tdx')
print(r.daily(symbol='600519').head())
print('Phase 2 OK')
"

# Phase 1C 验收: services 层
python -c "
from uniquant.services.data_service import DataService
from uniquant.services.scan_service import ScanPipeline
print('Phase 1C OK')
"

# Phase 1E 验收: 回测
python -c "
from uniquant.hands.backtest import BacktestEngine
from uniquant.hands.reporter import Reporter
print('Phase 1E OK')
"

# 最终验收
python -c "
import uniquant
from uniquant.data.data_fetcher import DataFetcher
from uniquant.services.analysis_service import AnalysisService
from uniquant.hands.backtest import BacktestEngine
from uniquant.brain.lppl import LPPLEngine
print('All modules OK')
"
pytest tests/ -v --tb=short
```

---

## 附录：文件清单

### A.1 当前存在文件 (44 文件)

```
src/uniquant/
├── __init__.py
├── brain/
│   ├── czsc/czsc_engine.py
│   ├── fsm/fsm.py
│   └── lppl/
│       ├── __init__.py
│       ├── engine.py
│       └── numba_optimizer.py
├── hands/
│   └── __init__.py
├── risk/
│   └── drawdown_analyzer.py
├── services/
│   ├── __init__.py
│   ├── analysis_service.py
│   ├── service_container.py
│   └── analysis/
│       ├── __init__.py
│       ├── czsc_analysis_engine.py
│       ├── engine_factory.py
│       ├── macro_service.py
│       ├── ntf_analysis_engine.py
│       ├── regime_analysis_engine.py
│       ├── report_generator_engine.py
│       └── technical_service.py
├── shared/
│   ├── __init__.py
│   ├── analysis_result.py
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── backends.py
│   │   ├── cache_factory.py
│   │   └── cache_interface.py
│   ├── config_loader.py
│   ├── constants.py
│   ├── cost_model.py
│   ├── di_container.py
│   ├── env_config.py
│   ├── error_handling.py
│   ├── errors.py
│   ├── exceptions.py
│   ├── import_state.py
│   ├── interfaces.py
│   ├── limit_checker.py
│   ├── limits.py
│   ├── logger_factory.py
│   ├── optimal_params.py
│   ├── retry_decorator.py
│   ├── slippage_model.py
│   └── utils.py
└── ui/
    ├── dashboard.py
    └── health_check.py
```

### A.2 需从 TDX 迁移的文件 (90+ 文件)

| 包 | 文件 | 行数 |
|----|------|------|
| `data/` | 40+ 文件 (StorageManager, DataFetcher, SourceRouter, 8 数据源, 12 管理器, 3 管道, 6 导入服务, TDX 解析器, 7 utils, 4 脚本) | ~14000 |
| `brain/` | 15+ 文件 (indicators, NTF, Regime, Factors x8, screener, Wyckoff x11, LPPL x6) | ~7000 |
| `hands/` | 19+ 文件 (BacktestEngine, UnifiedMatchingEngine, PortfolioEngine, MonteCarlo, OD, RC, SA, TradeAnalysis, 策略 x5, Reporter) | ~4700 |
| `services/` | 12 文件 (DataService, CacheCoordinator, ScanService, PortfolioService, 4 分析引擎适配器, 2 signal 服务) | ~3000 |
| `risk/` | 4 文件 (sizer, evt_risk, portfolio_optimizer, structural) | ~1300 |
| `shared/` | 6 文件 (market_rules, parallel, 4 常量子模块) | ~1000 |
| `signal/` | 6 文件 (models, normalizer, aggregator, quality, db) | ~900 |
| `ui/` | 5 文件 (components, lppl_visualizer, manager_logic, 2 服务) | ~1500 |
| `tests/` | 55+ 文件 | ~15000 |
| **总计** | **160+ 文件** | **~50000 LOC** |

---

*报告版本: v1.0 | 生成时间: 2026-05-26 | 基于 RESTRUCTURE_PLAN.md v3.1 和实际代码审计*
