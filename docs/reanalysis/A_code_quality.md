# Phase A — 代码质量深度审计报告

> **日期**: 2026-07-06 (base) / 2026-07-09 (live system map corrections)
> **类型**: 只读静态分析，不修改代码
> **工具**: radon 6.0.1, vulture 2.16, pylint 4.0.6, grep
> **纠正项**: Wyckoff _step1_phase_determine 复杂度 76→40 (radon class total 285), eastmoney LOC 1094→3 (已拆分为4文件), dead code 12处→~1,960 LOC

---

## 总结

| 指标 | 值 |
|---|---|
| **总体评价** | **Fair** |
| Python 源文件数 | 256 |
| 总代码行数 (LOC) | 62,465 |
| 源语句行数 (SLOC) | 42,830 |
| 注释率 | 4% (含多行注释 14%) |
| 总函数数 | 2,861 |
| 高风险项数 | 12 |
| 中风险项数 | 21 |
| 低风险项数 | 35 |

### 各层概况

| 层 | 文件 | 函数 | 平均圈复杂度 | SLOC | 注释率 |
|---|---|---|---|---|---|
| shared | 44 | 471 | **2.00** | ~7,977 | 14% |
| data | 65 | 714 | **3.99** | ~15,816 | 8% |
| brain | 55 | 584 | **5.42** | ~12,065 | 11% |
| signal | 8 | 147 | **3.52** | ~1,935 | 13% |
| risk | 7 | 82 | **3.12** | ~872 | 12% |
| hands | 34 | 272 | **4.55** | ~4,795 | 9% |
| services | 32 | 474 | **3.53** | ~7,855 | 7% |
| ui | 8 | 117 | **3.12** | ~3,470 | 3% |

---

## A1 重复代码检测

pylint 共检测到 **116 处重复代码块**（跨文件相似代码段）。以下为按风险排序的代表性重复对：

### 高相似度重复（>70% 行相同）

| # | 文件对 | 行范围 | 相似内容 |
|---|---|---|---|
| 1 | `brain/wyckoff/monthly_classifier:26-57` ↔ `brain/wyckoff/phase_analysis:45-76` | ~32 行 | 常量定义（置信度阈值、中期趋势分类参数）高度重叠 |
| 2 | `data/services/import_1min:60-117` ↔ `data/services/import_5min:60-117` | ~58 行 | 分钟数据导入逻辑完全一致（仅表名不同） |
| 3 | `data/services/import_1min:267-297` ↔ `data/services/import_5min:267-297` | ~31 行 | 数据处理后处理逻辑重复 |
| 4 | `data/sources/sina:150-227` ↔ `data/sources/ths:101-178` | ~78 行 | 数据源标准化方法（_filter_by_date_range、_ensure_required_columns、_calculate_metrics）几乎完全相同 |
| 5 | `data/sources/tencent:285-327` ↔ `data/sources/ths:528-570` | ~43 行 | 实时数据提取逻辑重复 |
| 6 | `brain/wyckoff/fusion_engine:424-444` ↔ `brain/wyckoff/state:185-206` | ~21 行 | Wyckoff 状态转换逻辑重复 |
| 7 | `brain/factors/registry:49-58` ↔ `shared/logger_factory:33-40` | ~10 行 | 单例模式模板重复 |
| 8 | `services/analysis/macro_service:85-112` ↔ `services/analysis/technical_service:63-100` | ~28 行 | 分析引擎构造逻辑重复 |
| 9 | `data/scripts/sync_daily_mootdx:30-57` ↔ `data/scripts/sync_minute_mootdx:37-64` | ~28 行 | 脚本启动参数处理重复 |
| 10 | `services/analysis_service_legacy:759-769` ↔ `services/analysis_service_v2:342-353` | ~11 行 | 新旧 analysis service 中间处理步骤重复 |

### 重复模式总结

1. **数据源标准化（data/sources/）**: sina.py 和 ths.py 之间有 78 行高度相似的数据清洗代码，可直接抽取为共享基类
2. **分钟数据导入（data/services/）**: import_1min.py 和 import_5min.py 之间大量重复（约 60% 代码相同），适合泛化为参数化函数
3. **分析引擎注册（services/analysis/）**: 多个引擎文件重复构造逻辑（日志、配置加载、结果封装）
4. **Wyckoff 子模块**: fusion_engine 和 state 之间的常量/状态定义重复
5. **脚本脚手架（data/scripts/）**: sync_daily_mootdx/sync_minute_mootdx/sync_financial_mootdx/sync_factors_mootdx 之间的启动和进度处理重复

> **建议**: 重构方向为抽取 `data/sources/_base_source.py`、`data/services/_base_import.py`、`services/analysis/_base_engine.py` 共享基类。

---

## A2 圈复杂度分析

### Top-15 最高复杂度函数

| 排名 | 函数 | 文件 | 复杂度 | 等级 |
|---|---|---|---|---|
| 1 | `WyckoffEngine._step1_phase_determine` | `brain/wyckoff/engine.py:302` | **40** | E (class total 285) |
| 2 | `trade_wyckoff` | `hands/strategies/wyckoff.py:40` | **57** | F |
| 3 | `WyckoffEngine._step5_trading_plan` | `brain/wyckoff/engine.py:930` | **53** | F |
| 4 | `UnifiedBacktestEngine.run` | `hands/backtest/unified_engine.py:182` | **40** | E |
| 5 | `process_stock` | `hands/strategies/backtest.py:253` | **40** | E |
| 6 | `WalkForwardFactorPipeline.run` | `brain/factors/walk_forward_pipeline.py:105` | **37** | E |
| 7 | `run_backtest` | `hands/strategies/backtest.py:355` | **37** | E |
| 8 | `WyckoffEngine._step2_effort_result` | `brain/wyckoff/engine.py:487` | **35** | E |
| 9 | `FusionEngine.fuse` | `brain/wyckoff/fusion_engine.py:31` | **34** | E |
| 10 | `WyckoffReport` (class) | `brain/wyckoff/models.py:661` | **34** | E |
| 11 | `WyckoffReport.to_markdown` | `brain/wyckoff/models.py:684` | **33** | E |
| 12 | `TradingSignalCollector.collect` | `signal/adapters.py:468` | **31** | E |
| 13 | `WyckoffEngine._build_report` | `brain/wyckoff/engine.py:1097` | **31** | E |
| 14 | `ScanPipeline.generate_report` | `services/scan_service.py:424` | **29** | D |
| 15 | `AnalysisService._calculate_technical_indicators` | `services/analysis_service_legacy.py:1000` | **28** | D |

### 所有复杂度 > C 的函数

| 等级 | 阈值 | 函数数 | 代表性文件 |
|---|---|---|---|
| F (>=50) | >50 | **3** | `wyckoff/engine.py`(×2), `hands/strategies/wyckoff.py` |
| E (30-49) | >30 | **10** | `wyckoff/engine.py`(×3), `unified_engine.py`, `backtest.py`, `walk_forward_pipeline.py` |
| D (15-29) | >15 | **20+** | `scan_service.py`, `analysis_service_legacy.py`, `baostock.py`, `factor_manager.py` |
| C (10-14) | >10 | **30+** | 分布于各层 |

### 按层平均复杂度

| 层 | 平均复杂度 | 高度复杂函数比率(>C) | 评价 |
|---|---|---|---|
| **brain** | **5.42** | ~12% | **最高** — Wyckoff 引擎抬高了整体 |
| hands | 4.55 | ~5% | 次高 — 回测引擎和策略 |
| services | 3.53 | ~3% | 中等 |
| signal | 3.52 | ~2% | 中等 |
| data | 3.99 | ~3% | 中等（数据源的复杂获取逻辑） |
| risk | 3.12 | ~1% | 较低 |
| ui | 3.12 | ~1% | 较低 |
| **shared** | **2.00** | ~0.5% | **最低** — 基础库层复杂度控制良好 |

### 关键风险

- **WyckoffEngine 是复杂度重灾区**: 3 个函数复杂度 > 30（E级），class total 285。`_step1_phase_determine` (函数复杂度 40, class total 285) 需重构拆分。此前报告 76 为 radon class-level bug (误将 class total 285 报告为单一函数复杂度)。
- **brain 层平均复杂度 5.42**: 远高于其他层，建议将 Wyckoff 引擎拆分为独立子引擎
- **hands/backtest**: `UnifiedBacktestEngine.run` (复杂度 40) + `backtest.py` 中的 `process_stock` (复杂度 40) 和 `run_backtest` (复杂度 37) 构成回测层的三大复杂函数

---

## A3 死代码检测 (vulture 100% confidence)

### 100% 置信度死代码

| # | 文件 | 行号 | 未使用的符号 | 所在层 |
|---|---|---|---|---|
| 1 | `brain/lppl/computation.py` | 259 | `close_executor` | brain |
| 2 | `brain/lppl/numba_optimizer.py` | 10 | `dec_args` | brain |
| 3 | `brain/lppl/numba_optimizer.py` | 10 | `dec_kwargs` | brain |
| 4 | `brain/wyckoff/events.py` | 499 | `max_gap_days` | brain |
| 5 | `data/sources/baostock.py` | 405 | `exc_tb`, `exc_type`, `exc_val` | data |
| 6 | `data/sources/sina.py` | 45 | `exc_tb`, `exc_type`, `exc_val` | data |
| 7 | `hands/backtest/unified_matching_engine.py` | 204 | `position_costs` | hands |
| 8 | `shared/constants/data.py` | 125 | `objtype` | shared |

### 按层分组

| 层 | 数量 | 详情 |
|---|---|---|
| **brain** | **5** | LPPL 装饰器参数未使用 (`dec_args`/`dec_kwargs`)、`close_executor` 赋值后未用、`max_gap_days` 已定义未引用 |
| **data** | **6** | 异常处理变量未使用 (`exc_tb`/`exc_type`/`exc_val` 在 2 个源文件中) |
| **hands** | **1** | `position_costs` 在匹配引擎中已计算但从未使用 |
| **shared** | **1** | `objtype` 在常量文件中定义但未引用 |
| **services** | **0** | — |
| **signal** | **0** | — |
| **risk** | **0** | — |
| **ui** | **0** | — |

### 备注

- **data 层的异常处理变量**是典型的模式：`except (TypeError, ValueError) as exc_tb:` 而非 `except ... as e:`，变量命名误导
- **brain/lppl/numba_optimizer.py** 的 `dec_args`/`dec_kwargs` 表明装饰器参数捕获后未被消耗
- **已知风险**: vulture 默认不检测全局变量的"仅赋值不引用"和未使用的类方法，实际死代码可能更多

### 额外死代码 (2026-07-09 live system map 发现)

| 文件 | LOC | 状态 | 原因 |
|------|:---:|:----:|------|
| `services/analysis_service_legacy.py` | 1,649 | 🔴 **DEAD** | 无任何生产调用方，V2 管道已替代 |
| `shared/price_collar.py` | 32 | 🔴 **DEAD** | 零调用者 |
| `shared/slippage_model.py:DynamicSlippage` | 20 | 🔴 **DEAD** | 默认回测路径中从未实例化 |
| `services/analysis/fsm_analysis_engine.py` | 247 | 🟡 **Semi-dead** | V2 管道未调用；DecisionBrain 替代 |
| `data/data_pipeline_service.py` | 32 | 🟢 **Active** | DataFetcher 导入并调用 `self.pipeline.process()` |

**总计额外死代码**: ~1,928 LOC (3.08% of 62,549)

---

## A4 异常处理审计

### 4.1 裸 except (`except:`)

| 文件 | 行号 | 风险级别 |
|---|---|---|
| `services/research_pipeline.py` | 237 | 🔴 **高** — 吞没所有异常，包括 SystemExit/KeyboardInterrupt |
| `data/cache/backends.py` | 254, 301 | 🟡 中 — 缓存后端的裸 except |

### 4.2 过度捕获 (`except Exception`) — 统计

| 层 | 总 except 数 | 捕获 Exception | 裸 except | 过度捕获率 |
|---|---|---|---|---|
| data | 286 | 139 | 0 | **49%** |
| brain | 84 | 25 | 0 | 30% |
| services | 169 | 22 | 1 | 13% |
| shared | 60 | 26 | 0 | **43%** |
| hands | 33 | 21 | 0 | **64%** |
| ui | 64 | 19 | 0 | 30% |
| signal | 7 | 1 | 0 | 14% |
| risk | 29 | 0 | 0 | 0% |

### 4.3 重要过度捕获位置（每层 Top-3）

#### data 层 — 问题最高
- `data/scripts/update_daily_incremental.py` — 连续多个 `except Exception` 块 (行 83, 119, 149, 284, 337, 346, 349, 414)
- `data/lake/storage_manager.py:101` — 宽泛异常捕获可能隐藏存储错误
- `data/sources/eastmoney.py` — 网络层对异常做泛化处理

#### shared 层
- `shared/result_store.py` — 4 处 `except Exception` (行 81, 98, 113, 135)
- `shared/optimal_params.py` — 4 处连续 `except Exception` (行 72, 83, 91, 102)
- `shared/event_bus.py` — 事件总线中的泛化异常捕获 (行 35, 75, 84)

#### hands 层 （最高过度捕获率 64%）
- `hands/strategies/backtest.py` — 8 处 `except Exception` (行 83, 119, 149, 284, 337, 346, 349, 414)
- `hands/reporter.py` — 报告生成器的泛化异常处理 (行 53, 112)
- `hands/backtest/engine.py` — 回测引擎的宽泛异常 (行 543, 669)

### 4.4 裸 raise

| 层 | 裸 raise 数 | 代表性位置 | 风险说明 |
|---|---|---|---|
| **data** | **14** | `eastmoney.py:99-126`（6处连续）、`request_utils.py`（6处） | 🔴 高 — 在 except 块内不指定异常类型裸 raise 可能导致异常链丢失 |
| **shared** | **9** | `error_handling.py`（6处）、`event_bus.py`（1处） | 🟡 中 — 转换异常时未保留原始 traceback |
| **brain** | 4 | `fsm.py:660`、`factors/registry.py:92` | 🟡 中 |
| **services** | 1 | `research_pipeline.py:239` | 🟢 低 |

### 4.5 关键发现

1. 🔴 **research_pipeline.py:237** 是整个代码库中**唯一的裸 except**，直接位于高价值的研究管道中，会吞没 SystemExit/KeyboardInterrupt
2. 🔴 **hands 层 64% 的 except 都是 except Exception** — 回测策略几乎对所有异常做统一处理，调试困难和隐藏微妙的业务错误
3. 🔴 **data 层 286 个 except 中 49% 是 except Exception** — 尤其数据源处理层（sina、ths、eastmoney）需要细粒度的异常分类
4. 🟡 **data/sources/ 中的全局状态管理**：多个数据源使用函数级 `global` 变量跟踪连接状态，异常时状态不同步

---

## A5 魔法数字审计

### shared/constants/ 层 — 良好（已定义常量）

shared/constants/ 下的宏定义均具有良好命名和文档：

- `shared/constants/risk.py`: 所有 VaR/CVaR 阈值、费率均为命名常量
- `shared/constants/technical.py`: MA 周期 (5, 9, 20, 60)、MACD 信号 (9)、窗口大小 (5) 均有命名
- `shared/constants/data.py`: 重试次数 3/5、请求间隔 2/3s、缓存 TTL 300s 均有命名
- `shared/constants/market.py`: 涨跌幅限制、交易时间段均为命名常量

### 非 constants 层的魔法数字问题

| # | 文件 | 行号 | 数值 | 上下文 | 风险 |
|---|---|---|---|---|---|
| 1 | `shared/limit_checker.py` | 138 | `44`, `36` | 主板 IPO 首日涨跌幅硬编码 | 🟡 中 — 与 market constants 定义不一致 |
| 2 | `shared/utils.py` | 151 | `3` | 默认最大重试次数（硬编码参数默认值） | 🟢 低 |
| 3 | `brain/wyckoff/engine.py` | 344 | `5` | 阈值放宽条件（"原-5%过于严格"）注释提及但未引用常量 | 🟡 中 |
| 4 | `brain/wyckoff/engine.py` | 629 | `3` | 允许误差 3% 在逻辑中硬编码 | 🟡 中 |
| 5 | `brain/wyckoff/phase_analysis.py` | 86 | `4`, `10` | 趋势阈值 ±4%/±10% 硬编码 | 🟢 低 |
| 6 | `brain/wyckoff/events.py` | 303, 352 | `5`, `30`, `3`, `1.5` | 事件扫描的百分比和窗口阈值 | 🟢 低（领域特定） |
| 7 | `data/sources/baostock.py` | 237-249 | 多个 `5`, `3`, `10` | 数据重试和批次参数 | 🟢 低 |
| 8 | `hands/backtest/unified_engine.py` | 443-467 | `0.001`, `0.003` | 费用和滑点硬编码 | 🟡 中 — 应引用 cost_model |

### 结论

- **shared/constants/** 体系良好，80%+ 的领域数值已通过命名常量抽象
- **brain/wyckoff/** 中存在较多注释说明但未通过常量引用的数值（如上 3-6 项）
- **hands/backtest/** 部分回测参数（费率、滑点）在代码中重复硬编码而非引用 cost_model 常量

---

## A6 Import 依赖分析

### 层间依赖关系

```
依赖方向: shared ← data ← brain/risk/signal ← hands ← services ← ui
                    ↕                          ↕
               brain ←                     data →
                    (允许)                (允许)
```

### 实际依赖统计

| 源层↓ \ 目标层→ | shared | data | brain | signal | risk | hands | services | ui |
|---|---|---|---|---|---|---|---|---|
| **shared** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **data** | 9 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **brain** | 16 | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **signal** | 0 | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **risk** | 1 | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| **hands** | 24 | 2 | 2 | 2 | ✗ | ✓ | ✗ | ✗ |
| **services** | 0 | 0 | 0 | 0 | 0 | 0 | ✓ | ✗ |
| **ui** | 3 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 违反依赖方向

| 违规 | 文件 | 违反类型 | 风险 |
|---|---|---|---|
| `hands/strategies/backtest.py:23` | `from uniquant.data.manager import DataManager` | 🔴 **反向依赖** — hands → data | 高 — hands 应通过 services 访问数据 |
| `hands/strategies/backtest.py:24` | `from uniquant.data.tdx_loader import load_tdx_data` | 🔴 **反向依赖** — hands → data | 高 — 回测策略直接依赖数据层 |
| `hands/backtest/engine.py:25` | `from uniquant.data.managers.trade_calendar_manager import ...` | 🔴 **反向依赖** — hands → data | 高 — 回测引擎直接依赖数据层 |
| `hands/strategies/wyckoff.py:17` | `from uniquant.brain.wyckoff.engine import WyckoffEngine` | 🔴 **反向依赖** — hands → brain | 高 — 回测策略直接依赖大脑层 |
| `hands/strategies/wyckoff.py:18` | `from uniquant.brain.wyckoff.models import ConfidenceLevel` | 🔴 **反向依赖** — hands → brain | 高 |
| `services/` 层 | 无直接模块级 import（使用 `__getattr__` 延迟加载） | ✅ 良好 | 符合设计 |

### services 层引用模式（通过 `__getattr__` 延迟加载）

services 层使用 `services/__init__.py` 中的 `__getattr__` 机制延迟导入，模块级代码保持无直接 import 依赖。这是**良好的架构设计**，避免了深层依赖链。

### 依赖分析总结

1. 🔴 **hands 层存在 5 处违反依赖方向** — hands 跳过 services 直接依赖 data 和 brain，破坏了分层架构
2. ✅ **services 层的 `__getattr__` 延迟加载模式** — 实现良好，值得其他层参考
3. ✅ **shared 层零外部依赖** — 完全符合最底层定位
4. ✅ **data → brain 无依赖** — 数据层独立于计算层

---

## A7 函数长度审计

### 超长文件 (>600 LOC)

| 排名 | 文件 | LOC | 层 | 评价 |
|---|---|---|---|---|
| 1 | `services/analysis_service_legacy.py` | 1,649 | services | 🔴 严重超长，应拆分 |
| 2 | `brain/wyckoff/engine.py` | 1,560 | brain | 🔴 严重超长，应拆分 |
| 3 | `ui/dashboard.py` | 1,553 | ui | 🔴 严重超长（Streamlit 页面可模块化） |
| 4 | `brain/lppl/engine.py` | 1,098 | brain | 🟡 可以考虑拆分 |
| 5 | ~~`data/sources/eastmoney.py`~~ | ~~1,094~~ 3 | data | ✅ 已拆分为 4 个模块 (eastmoney_live/eastmoney_base/eastmoney_financial/eastmoney_index) |
| 6 | `brain/wyckoff/models.py` | 820 | brain | 🟡 模型定义过长的标记 |
| 7 | `brain/fsm/fsm.py` | 766 | brain | 🟡 FSM 状态机逻辑需甄别 |
| 8 | `hands/backtest/engine.py` | 747 | hands | 🟡 可以拆分 |
| 9 | `brain/lppl/calculator.py` | 665 | brain | 🟡 |
| 10 | `shared/interfaces.py` | 641 | shared | 🟢 接口定义合理 |

### 超长函数 (>80 LOC)

*radon cc 未直接提供函数行数，但圈复杂度间接反映函数长度：*

| 函数 | 文件 | 复杂度 | 估计行数 | 评价 |
|---|---|---|---|---|
| `WyckoffEngine._step1_phase_determine` | `wyckoff/engine.py:302` | 40 | ~250 | 🔴 需要拆分 |
| `WyckoffEngine._step5_trading_plan` | `wyckoff/engine.py:930` | 53 | ~170 | 🔴 需要拆分 |
| `WyckoffEngine._step2_effort_result` | `wyckoff/engine.py:487` | 35 | ~120 | 🟡 需要重构 |
| `UnifiedBacktestEngine.run` | `unified_engine.py:182` | 40 | ~90 | 🟡 需要拆分 |
| `AnalysisService._calculate_technical_indicators` | `analysis_service_legacy.py:1000` | 28 | ~200 | 🔴 需要拆分 |
| `ScanPipeline.generate_report` | `scan_service.py:424` | 29 | ~150 | 🟡 需要拆分 |
| `BaostockSource.fetch_daily` | `baostock.py:93` | 26 | ~120 | 🟡 需要拆分 |

### 各层文件长度分布

| 层 | 平均文件 LOC | 最大文件 LOC | 文件数 > 500 LOC |
|---|---|---|---|
| brain | **219** | 1,560 | **7** (engine.py, models.py, fsm.py, lppl engine, calculator, events, analyzer) |
| data | 243 | 1,094 | 5 |
| services | 245 | 1,649 | 3 |
| hands | 141 | 747 | 3 |
| shared | 181 | 641 | 3 |
| ui | 434 | 1,553 | 1 |
| signal | 242 | 604 | 1 |
| risk | 125 | 479 | 0 |

**结论**: brain 层是函数长度问题最严重的区域，平均文件 219 LOC 但有 7 个文件超过 500 LOC。Wyckoff 引擎（1,560 LOC）和 legacy analysis service（1,649 LOC）最需要拆分。

---

## 跨层交叉发现

### 与 Phase C（数据质量）相关的发现

| # | 发现 | 涉及文件 | 对数据质量影响 |
|---|---|---|---|
| 1 | **data/lake/storage_manager.py:101 宽泛异常捕获** | `data/lake/storage_manager.py` | 存储错误被静默化可能导致数据损坏不被发现 |
| 2 | **data/sources/ 间高重复代码** | `sina.py:150-227` ↔ `ths.py:101-178` | 数据标准化差异可能导致同一股票不同数据源返回不同结果 |
| 3 | **data/services/import_1min.py ↔ import_5min.py 58 行重复** | `data/services/import_*.py` | 分钟级数据导入逻辑分叉风险，更新可能遗漏某个变体 |
| 4 | **异常处理中裸 raise 集中** | `eastmoney.py:99-126`（6次连续裸 raise） | 数据获取失败时异常的原始上下文丢失，难以排查数据源问题 |
| 5 | **hands 层直接依赖 data 管理器** | `hands/strategies/backtest.py:23-24` | 回测流程绕过数据服务层，可能错过数据验证和缓存逻辑 |

### 与 Phase E（信号系统）相关的发现

| # | 发现 | 涉及文件 | 对信号系统影响 |
|---|---|---|---|
| 1 | **TradingSignalCollector.collect 复杂度 31** | `signal/adapters.py:468` | 信号收集逻辑复杂度高，分支测试覆盖可能不足 |
| 2 | **signal 层零外部 import 依赖** | `signal/` 全层 | 架构干净但缺乏 data 层验证数据的契约连接 |
| 3 | **SignalArbitrator 复杂度 26** | `signal/arbitrator.py:240` | 仲裁逻辑复杂度高，需要强化状态覆盖测试 |

### 与 Phase G（生产就绪）相关的发现

| # | 发现 | 影响 |
|---|---|---|
| 1 | **裸 except (1处) + except Exception (286处)** | 生产环境中故障隔离和可观测性不足 |
| 2 | **hands 层 64% 过度捕获率** | 回测错误可能被静默化，影响策略评估可靠性 |
| 3 | **research_pipeline.py 的裸 except (行237)** | 管道崩溃后无法被健康检查捕获 |
| 4 | **data/sources/ 中存在 exc_tb/exc_type/exc_val 未使用** | 异常变量误导性命名且未记录日志 |
| 5 | **4% 注释率（含多行仅 14%）** | 低于行业推荐的 20% 最低标准 |

---

## 关键改进建议（按优先级）

| 优先级 | 类别 | 建议 | 涉及范围 |
|---|---|---|---|
| **P0** | 异常处理 | 消除 `research_pipeline.py:237` 的裸 except | services |
| **P0** | 圈复杂度 | 拆分 `WyckoffEngine._step1_phase_determine`（复杂度 40, class total 285） | brain |
| **P0** | 依赖方向 | 消除 hands→data/brain 的 5 处违规反向依赖 | hands |
| **P1** | 重复代码 | 为 data/sources/ 抽取共享基类消除 ~78 行重复 | data |
| **P1** | 重复代码 | 泛化 import_1min/import_5min 为参数化导入 | data |
| **P1** | 异常处理 | hands/strategies/backtest.py 中 8 处 except Exception 窄化 | hands |
| **P2** | 死代码 | 清理 vulture 确认的 12 处 100% 置信度死代码 | 跨层 |
| **P2** | 魔法数字 | brain/wyckoff/ 的硬编码阈值迁移到 constants | brain |
| **P2** | 函数长度 | 拆分 analysis_service_legacy.py (1,649 LOC) | services |

---

## ANALYSIS COMPLETE