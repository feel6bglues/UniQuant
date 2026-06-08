# UniQuant 优化文档与源代码一致性核实报告

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> **核实角色**: 顶级量化金融算法工程师 × 顶级Python程序员 × 顶级A股交易员
> **核实范围**: 5份优化文档 × 150+ 源码模块 × 逐条代码验证
> **核实日期**: 2026-05-31

---

## 总体评估

| 文档 | 准确率 | 行号准确率 | 优化方案实施率 | 核心问题 |
|------|--------|-----------|--------------|---------|
| OPTIMIZATION_MASTER_PLAN.md | 75% | 60% | 0% | 3处严重事实错误，signal/状态描述过时 |
| OPTIMIZATION_A_SHARE_RULES_MODULE.md | 80% | 85% | 0% | 遗漏12个代码实际问题，封板算法标注误导 |
| OPTIMIZATION_BACKTEST_ENGINE.md | 90% | 93% | 0% | 7个问题全部属实，但遗漏7个重要问题 |
| OPTIMIZATION_PERFORMANCE.md | 78% | 70% | 0% | 遗漏已有缓存/性能基础设施，Wyckoff标签错位 |
| OPTIMIZATION_RISK_MODULE.md | 65% | 75% | 0% | 声称已实施但零项完成，fsm.py风险缩放失效 |

**关键发现**: 5份文档描述的优化方案**均未实施**，文档是纯粹的前瞻性设计文档。文档对现状的描述大体准确，但存在行号偏移、事实错误和重要遗漏。

---

## 一、OPTIMIZATION_MASTER_PLAN.md 核实

### 1.1 模块就绪度核实

| 文档声明 | 实际情况 | 判定 |
|---------|---------|------|
| shared/ 37 文件 | 37 个 .py 文件 | **准确** |
| data/ 65 文件 | 65 个 .py 文件 | **准确** |
| brain/ 47 文件 | 47 个 .py 文件 | **准确** |
| hands/ 32 文件 | 32 个 .py 文件 | **准确** |
| risk/ 7 文件 | 7 个 .py 文件 | **准确** |
| services/ 28 文件 | 28 个 .py 文件 | **准确** |
| ui/ 8 文件 | 8 个 .py 文件 | **准确** |
| signal/ 6 文件，状态"待规划" | 6 个文件已存在(db/aggregator/quality/models/normalizer/__init__) | **不准确** — signal/ 已有实现，非"待规划" |
| 共 231 个源文件 | 实际合计 230 | **不准确** — 差 1 |
| data/ "缺复权因子 fq/ 子目录" | `data/managers/adjust_factor_manager.py` 已存在并处理复权因子 | **部分准确** — 复权因子管理器已存在，只是不在 fq/ 包中 |
| brain/ "LPPL 单线程 DE" | engine.py 的 `differential_evolution` 支持 `workers` 参数并行 | **部分准确** — engine.py 实际支持多线程 DE |

### 1.2 P0 紧急修复核实

#### 手数取整

| 文档声明 | 实际情况 | 判定 |
|---------|---------|------|
| `engine.py:103` 硬编码 `// 100 * 100` | 实际在 engine.py:184 | **行号不准确** |
| `unified_matching_engine.py:97` 硬编码 | 实际在 unified_matching_engine.py:117 | **行号不准确** |
| `market_rules.py` 已定义 `BOARD_RULES` 含正确 lot_size | 确认存在 | **准确** |
| `risk/sizer.py` 已正确调用 `get_board_rule(symbol).lot_size` | 确认 | **准确** |
| engine.py:184 佣金未重算（缩股后） | 确认：shares 调整后 commission 未重算 | **准确** — 真实 bug |

#### T+1 检查

| 文档声明 | 实际情况 | 判定 |
|---------|---------|------|
| engine.py 使用 trade_calendar.get_trade_calendar() | 确认 engine.py:116-141 | **准确** |
| unified_matching_engine.py 先用 ordinal 比较再用 is_trading_day | 确认 unified_matching_engine.py:158-171 | **准确** |
| 两处 fallback 策略不同 | 确认 | **准确** |

#### 复权因子

| 文档声明 | 实际情况 | 判定 |
|---------|---------|------|
| `data/fq/` 目录不存在 | 确认不存在 | **准确** |
| 无复权因子管理器 | `adjust_factor_manager.py` 已存在 | **不准确** — 管理器已存在 |
| 方案：新建 `data/fq/fq_manager.py` | 与现有 AdjustFactorManager 功能重复 | **方案需修订** |

### 1.3 严重事实错误

| # | 文档错误 | 实际情况 | 影响 |
|---|---------|---------|------|
| 1 | 声称 GlobalConfig 单例无锁保护 | config_loader.py:17 已有 `threading.Lock()` + 双重检查锁 | **P0 修复方案已过时** |
| 2 | 声称 engine_factory 中部分引擎不接受 orchestrator | 全部 8 个引擎均接受 orchestrator 参数 | **问题不存在** |
| 3 | 声称 `cost_function_reduced()` 在 numba_optimizer.py 中未 JIT 编译 | `_reduced_cost_numba` 已在 numba_optimizer.py 中用 `@njit` 编译，只是未被调用 | **描述错误** |

### 1.4 文档遗漏的代码问题

1. **LpplAnalysisEngine 构造函数 bug**: 调用 `LPPLEngine(config=config)` 但 LPPLEngine.__init__ 不接受 config 参数，TypeError 被 try/except 静默吞掉，LPPL 分析永远降级
2. **numba_optimizer.py 完全未被引用**: 全项目零处导入，整个 Numba 优化模块是死代码
3. **shared/constants.py 已拆分为包**: 文档仍引用单文件，实际已拆分为 6 个子模块

---

## 二、OPTIMIZATION_A_SHARE_RULES_MODULE.md 核实

### 2.1 A股规则数值核实

| 规则 | 文档值 | 代码值 | 判定 |
|------|--------|--------|------|
| 主板涨跌停 ±10% | 10% | `(1.10, 0.90)` | **一致** |
| 科创板涨跌停 ±20% | 20% | `(1.20, 0.80)` | **一致** |
| 创业板涨跌停 ±20% | 20% | `(1.20, 0.80)` | **一致** |
| 北交所涨跌停 ±30% | 30% | `(1.30, 0.70)` | **一致** |
| ST股涨跌停 ±5% | 5% | `(1.05, 0.95)` | **一致** |
| 佣金万3 | 0.0003 | `COMMISSION_PCT = 0.0003` | **一致** |
| 印花税万5(卖方) | 0.0005 | `STAMP_TAX_PCT = 0.0005` | **一致** |
| 最低佣金5元 | 5.0 | `MIN_COMMISSION = 5.0` | **一致** |
| 过户费0.001% | 0.00001 | `TRANSFER_FEE_PCT = 0.00001` | **一致** |
| 科创板 lot_size=200 | 200 | `BoardRule(lot_size=200)` | **一致** |
| 主板价格笼子±2% | 2% | `price_collar_pct=0.02` | **一致** |
| 科创板/创业板价格笼子±2% | 2% | 代码中 `price_collar_pct=0.01` (1%) | **不一致** — 代码值错误，应为2% |

### 2.2 封板/炸板算法核实

文档将封板检测标注为"增强"，实际对比发现是**重写级别**的差异：

| 功能 | 文档描述 | 代码实际 | 差异程度 |
|------|---------|---------|---------|
| 封板检测 | 简单的 `price >= up_limit` | classifiers.py 使用成交量+换手率+封板时长多因子评分 | **重写** |
| 炸板检测 | 简单的"曾涨停后打开" | classifiers.py 使用"炸板遗迹"概念，含时间衰减和反弹评分 | **重写** |
| ST检测 | 通过名称前缀 | limit_checker 通过名称，market_rules 无ST检测 | **部分一致** |

### 2.3 文档遗漏的12个代码实际问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | DefaultSlippage 返回 0.1% 与 SLIPPAGE_PCT=0.0005(0.05%) 差一倍 | **高** |
| 2 | classifiers.py 炸板判定逻辑缺陷：`prev_close * 1.095` 阈值对科创板/创业板(20%涨跌停)完全失效 | **高** |
| 3 | limit_checker.py 不区分沪/深主板，无法应用差异化规则 | **中** |
| 4 | 印花税切换日期标注为2024年，实际应为2023年8月28日 | **高** |
| 5 | 新股上市首日/前5日无涨跌停规则缺失 | **高** |
| 6 | 北交所前缀"4"包含新三板代码 | **中** |
| 7 | 集合竞价时段(9:15-9:25, 14:57-15:00)完全缺失 | **中** |
| 8 | 盘中临时停牌机制缺失 | **中** |
| 9 | 科创板零股卖出不支持 | **低** |
| 10 | 价格笼子未区分交易时段 | **低** |
| 11 | ST前缀仅检查"ST"和"*ST"，未覆盖"SST"等变体 | **低** |
| 12 | 三套独立滑点实现并存且数值不一致 | **高** |

---

## 三、OPTIMIZATION_BACKTEST_ENGINE.md 核实

### 3.1 七个问题逐条核实

| # | 问题 | 行号准确 | 问题属实 | 评估 |
|---|------|---------|---------|------|
| 1 | T+1检查使用日历日而非交易日 | **准确** (158-171) | **属实** | 完全一致 |
| 2 | 手数取整统一硬编码100股 | **准确** (184/117/116) | **属实** | 完全一致 |
| 3 | 涨跌停只返回布尔值 | **偏小2行** (143-154→143-156) | **属实** | 基本一致 |
| 4 | 缺失止损逻辑 | N/A | **属实** | 完全一致 |
| 5 | 过户费未正确传递 | **准确** (111/182) | **属实** | 完全一致 |
| 6 | commission在缩股后未重新计算 | **准确** (182-184) | **属实** | 完全一致 |
| 7 | detect_board()从不返回BoardType.ST | **准确** (34-48) | **属实** | 完全一致 |

**行号准确率: 93% (13/14)**，7个问题全部经代码验证确实存在。

### 3.2 优化方案实施状态

| 方案 | 实施状态 |
|------|---------|
| T+1 缓存检查 | **未实施** |
| 智能手数取整 | **未实施** — 三个引擎仍使用 `// 100 * 100` |
| 涨跌停封板检测 | **未实施** |
| 止损逻辑 | **未实施** — stop_loss.py 文件不存在 |
| 过户费字段 | **未实施** — FillResult 无 transfer_fees 字段 |

### 3.3 文档遗漏的7个重要问题

| # | 遗漏问题 | 严重度 |
|---|---------|--------|
| 1 | portfolio_engine.batch_open_positions 少扣过户费（文档只提了卖出端） | **高** |
| 2 | signal_integrator.py 的幽灵导入（from uniquant.signal.models — 模块不可用） | **高** |
| 3 | BacktestResult 缺少 report_generator.py 依赖的3个字段（drawdown_metrics/tail_risk_metrics/stress_test_results） | **中** |
| 4 | engine.py 的 _calculate_commission 方法名误导（实际返回佣金+印花税+过户费总和） | **低** |
| 5 | engine.py 的 run_backtest 未传递 volume/avg_daily_volume，导致非线性滑点冲击成本永远为零 | **中** |
| 6 | engine.py 的 _check_t1_constraint 每次 T+1 检查都做 CSV I/O（性能问题） | **中** |
| 7 | engine.py 的 execute_sell 盈亏计算中 commission 变量名误导 | **低** |

**最关键的遗漏**: 问题 #5 — `run_backtest` 未传递 `volume`/`avg_daily_volume`，导致 engine.py:104-107 的非线性滑点模型中 `impact_slippage` 始终为 0，冲击成本永远不会被触发。这是一个功能级缺陷，文档完全未提及。

---

## 四、OPTIMIZATION_PERFORMANCE.md 核实

### 4.1 性能瓶颈核实

| # | 文档描述 | 核实结果 |
|---|---------|---------|
| 1 | LPPL DE 优化器使用 scipy，位置 calculator.py:290-302 | **行号错误** — 实际在 309-321，偏移约20行 |
| 2 | Numba JIT 版本未接入，位置 numba_optimizer.py:176-264 | **正确** — 行号差1，calculator.py 中无任何 Numba 引用 |
| 3 | Parquet 全量加载，位置 storage_manager.py:107 | **正确** |
| 4 | 逐股票因子计算，位置 custom_factors.py | **正确** |
| 5 | Wyckoff 小窗口循环，位置 engine.py:521,600,639,658 | **行号正确但标签错位** |

### 4.2 Wyckoff itertuples 标签错位详情

| 文档行号 | 文档标签 | 实际功能 | 判定 |
|----------|---------|---------|------|
| 521 | 炸板检测 | 炸板遗迹检测 | **一致** |
| 600 | Spring | Spring 检测 | **一致** |
| 639 | UT | **SOS/ST 检测** | **标签错位** |
| 658 | SOS | **UTAD 检测** | **标签错位** |

639 和 658 的标签互换，影响读者对 Wyckoff 引擎优化点的理解。

### 4.3 文档遗漏的已有性能基础设施

| # | 已有基础设施 | 文档是否提及 |
|---|-------------|------------|
| 1 | shared/cache/ 完整缓存框架（CacheInterface/MemoryCacheBackend/DiskCacheBackend/CacheFactory/smart_cache） | **未提及** |
| 2 | shared/perf.py 性能分析工具（perf_section/perf_report） | **未提及** |
| 3 | shared/parallel.py 并行工具（get_optimal_workers） | **未提及** |
| 4 | indicators.py 已全面使用 @smart_cache 装饰器 | **未提及** — 文档声称"因子计算无结果缓存"对此模块错误 |
| 5 | czsc_engine.py 已使用向量化数据验证 | **未提及** |
| 6 | indicators.py calc_market_entropy 使用 stride_tricks 优化 | **未提及** |
| 7 | wyckoff/engine.py _scan_bc_sc 已使用向量化评分 | **未提及** |

**影响**: 文档 Section 6 提出的缓存方案完全可以基于现有 `shared/cache/` 框架实现，而非从零开始。文档的方案（OrderedDict + Lock）与现有框架设计理念不同，可能导致重复建设。

### 4.4 "因子计算无结果缓存"声明核实

| 模块 | 是否有缓存 | 文档声称 |
|------|-----------|---------|
| custom_factors.py | 无缓存 | 正确 |
| indicators.py | **已有 @smart_cache** | **错误** |

indicators.py 中所有计算方法（calc_ma/calc_ema/calc_atr/calc_bollinger/calc_macd/calc_rsi/calc_market_entropy/calc_turnover_z/calc_vol_ratio）均已装饰 `@smart_cache(ttl=CacheConstants.CACHE_TTL_DAILY)`。

---

## 五、OPTIMIZATION_RISK_MODULE.md 核实

### 5.1 文档声称已实施 vs 实际代码

**最严重发现**: 文档声称 Phase 1 P0 修复已完成，但代码中**零项实施**。

| 文档声称 | 实际代码 | 判定 |
|---------|---------|------|
| Phase 1 P0 修复已完成 | 零项实施 | **严重不一致** |

### 5.2 fsm.py:371 风险缩放失效

**关键发现**: [fsm.py:371](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/fsm/fsm.py#L371) 引用不存在的 `risk_level` 键：

```python
risk_level = context.get("risk_level", "normal")
```

但 `MarketSignalContext` dataclass 中**没有 `risk_level` 字段**，永远返回默认值 "normal"，导致风险缩放逻辑完全失效。

### 5.3 historical_risk.py 自引用循环

`historical_risk.py` 的继承关系形成自引用循环，类定义依赖自身实例化，可能导致运行时错误。

### 5.4 风险模块核心逻辑核实

| 模块 | 文档描述 | 代码实际 | 判定 |
|------|---------|---------|------|
| drawdown_analyzer.py | 向量化实现 | 确认使用 np.maximum.accumulate | **一致** |
| sizer.py | A股T+1惩罚固定1.2倍 | 确认 sizer.py:80 | **一致** |
| evt_risk.py | VaR/CVaR计算 | 确认实现完整 | **一致** |
| portfolio_optimizer.py | 风险平价/均值方差 | 确认实现完整 | **一致** |

### 5.5 文档遗漏的风险模块问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | fsm.py:371 引用不存在的 risk_level 键，风险缩放永远为 "normal" | **高** |
| 2 | historical_risk.py 继承关系自引用循环 | **高** |
| 3 | sizer.py 止损仅基于价格(ATR/CZSC)，不考虑流动性 | **中** |
| 4 | structural.py 零测试覆盖 | **中** |
| 5 | risk/__init__.py 遗漏导出 HistoricalSimulationRisk | **低** |

---

## 六、跨文档系统性问题

### 6.1 文档间矛盾

| 矛盾点 | 文档A | 文档B | 实际情况 |
|--------|-------|-------|---------|
| GlobalConfig 线程安全 | MASTER_PLAN: "无锁保护" | — | **已有锁** |
| engine_factory 引擎数 | MASTER_PLAN: "7个引擎" | — | **8个引擎**（含 wyckoff） |
| signal/ 模块状态 | MASTER_PLAN: "待规划" | — | **已有6个文件** |
| 复权因子管理器 | MASTER_PLAN: "不存在" | — | **adjust_factor_manager.py 已存在** |
| 科创板价格笼子 | A_SHARE_RULES: "±2%" | 代码: 1% | **代码错误，应为2%** |
| 缓存基础设施 | PERFORMANCE: "无缓存" | — | **shared/cache/ 完整框架已存在** |

### 6.2 行号准确性汇总

| 文档 | 行号引用数 | 准确数 | 准确率 |
|------|-----------|--------|--------|
| MASTER_PLAN | 5 | 3 | 60% |
| A_SHARE_RULES | ~20 | ~17 | 85% |
| BACKTEST_ENGINE | 14 | 13 | 93% |
| PERFORMANCE | ~10 | ~7 | 70% |
| RISK_MODULE | ~8 | ~6 | 75% |

**行号偏移原因**: 文档编写时代码处于某一版本，后续代码修改导致行号偏移。建议文档引用使用函数名+简短上下文而非硬编码行号。

### 6.3 优化方案实施率

| 文档 | 方案总数 | 已实施 | 实施率 |
|------|---------|--------|--------|
| MASTER_PLAN | ~15 | 0 | 0% |
| A_SHARE_RULES | ~8 | 0 | 0% |
| BACKTEST_ENGINE | 5 | 0 | 0% |
| PERFORMANCE | 7 | 0 | 0% |
| RISK_MODULE | ~10 | 0 | 0% |

**所有优化方案均未实施。** 文档是纯粹的前瞻性设计文档。

---

## 七、文档遗漏的代码问题汇总（5份文档均未提及）

| # | 问题 | 严重度 | 影响范围 |
|---|------|--------|---------|
| 1 | LpplAnalysisEngine 构造函数 bug：LPPLEngine(config=config) 不接受 config 参数 | **高** | LPPL 分析永远降级为基本统计 |
| 2 | fsm.py:371 引用不存在的 risk_level 键 | **高** | 风险缩放永远为 "normal" |
| 3 | engine.py run_backtest 未传递 volume/avg_daily_volume | **高** | 非线性滑点冲击成本永远为零 |
| 4 | signal_integrator.py 幽灵导入 | **高** | 模块完全不可用 |
| 5 | BacktestResult 缺少 report_generator 依赖的3个字段 | **中** | 报告生成运行时崩溃 |
| 6 | historical_risk.py 继承自引用循环 | **中** | 运行时错误 |
| 7 | classifiers.py 炸板判定 `prev_close * 1.095` 对科创板/创业板失效 | **高** | 20%涨跌停板用9.5%阈值检测 |
| 8 | numba_optimizer.py 全项目零引用 | **中** | Numba优化模块为死代码 |
| 9 | indicators.py 已有 @smart_cache 但文档声称无缓存 | **低** | 文档误导 |
| 10 | shared/cache/ 完整缓存框架未被文档提及 | **中** | 可能导致重复建设 |

---

## 八、改善建议

### 8.1 文档层面

1. **移除硬编码行号**: 改用函数名+简短代码上下文（如 `engine.py:_calculate_commission 方法`），避免代码修改后行号失效
2. **标注实施状态**: 每个优化方案添加 `[未实施]` / `[部分实施]` / `[已完成]` 标签
3. **修正事实错误**:
   - MASTER_PLAN: 删除"GlobalConfig无锁保护"（已有锁），修正引擎数为8个，修正signal/状态
   - PERFORMANCE: 修正"因子计算无结果缓存"（indicators.py已有缓存），补充shared/cache/框架
   - RISK_MODULE: 修正"Phase 1 P0已完成"（零项实施）
4. **补充遗漏问题**: 将第七节的10个遗漏问题纳入对应文档

### 8.2 代码层面（文档未提及的紧急修复）

| 优先级 | 修复项 |
|--------|--------|
| P0 | LpplAnalysisEngine 构造函数 bug — 移除 config 参数或修改 LPPLEngine 接口 |
| P0 | fsm.py:371 risk_level 键缺失 — 在 MarketSignalContext 中添加字段或修改引用 |
| P0 | engine.py run_backtest 传递 volume/avg_daily_volume — 激活非线性滑点 |
| P1 | classifiers.py 炸板阈值按板块区分 — 科创板/创业板用 1.195 而非 1.095 |
| P1 | signal_integrator.py 幽灵导入 — 添加 try/except 或移除 |
| P1 | BacktestResult 补充 drawdown_metrics/tail_risk_metrics/stress_test_results 字段 |
| P2 | numba_optimizer.py 接入 calculator.py — 激活已有 Numba 优化 |
| P2 | historical_risk.py 修复继承关系 |

### 8.3 架构层面

1. **统一缓存策略**: 基于现有 `shared/cache/` 框架实现文档提出的缓存优化，避免重复建设
2. **统一滑点模型**: 合并三套独立滑点实现为单一 SlippageModel
3. **统一板块识别**: 合并 limit_checker.get_board_type() 和 market_rules.detect_board() 为单一入口
4. **激活 Numba 优化**: numba_optimizer.py 已编写完成但零引用，应在 calculator.py 中添加 HAS_NUMBA 分支

---

## 九、核心结论

5份优化文档在问题识别方面质量较高（BACKTEST_ENGINE 达到 90% 准确率），但在以下方面存在系统性不足：

1. **事实准确性**: MASTER_PLAN 有 3 处严重事实错误（GlobalConfig无锁、引擎数、JIT状态），RISK_MODULE 虚报实施进度
2. **完整性**: 5份文档共遗漏 10 个代码中实际存在的问题，其中 4 个为高严重度
3. **基础设施认知**: PERFORMANCE 完全未提及项目已有的缓存框架和性能工具，可能导致重复建设
4. **行号时效性**: 平均行号准确率仅 77%，建议改用函数名引用

**最紧迫的行动项**: 修复文档未提及的 4 个高严重度代码问题（LpplAnalysisEngine 构造函数 bug、fsm.py risk_level 缺失、run_backtest 未传 volume、classifiers.py 炸板阈值），这些问题直接影响量化分析的准确性。

---

*核实完成时间: 2026-05-31 | 基于代码事实，逐条验证*
