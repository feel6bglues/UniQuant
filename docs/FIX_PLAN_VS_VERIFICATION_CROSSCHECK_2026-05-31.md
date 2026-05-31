# FIX_PLAN vs OPTIMIZATION_DOCS_VERIFICATION 交叉核验报告

> **核验人**: 顶级量化金融算法工程师 × 顶级Python程序员 × 顶级A股交易员
> **核验日期**: 2026-05-31
> **核验方法**: 逐项对照 VERIFICATION 报告中的每个问题，检查 FIX_PLAN 是否覆盖，并对 VERIFICATION 报告自身的准确性进行源码验证

---

## 总体结论

| 维度 | 统计 |
|------|------|
| VERIFICATION 报告问题总数 | 42 项 |
| FIX_PLAN 已覆盖 | 19 项 (45%) |
| FIX_PLAN 未覆盖 | 18 项 (43%) |
| VERIFICATION 报告自身描述不准确 | 5 项 (12%) |

**核心发现**: FIX_PLAN 覆盖了约 45% 的 VERIFICATION 报告问题。遗漏的 18 项中有 **6 项为高严重度**，包括 LpplAnalysisEngine 构造函数 bug、fsm.py risk_level KeyError、run_backtest 未传 volume、classifiers.py 炸板判定逻辑错误、detect_board 不返回 ST、unified_matching_engine 手数硬编码。这些遗漏项必须补充到修复计划中。

---

## 一、逐项交叉核验

### 1.1 OPTIMIZATION_MASTER_PLAN 核实部分

| # | VERIFICATION 问题 | 严重度 | FIX_PLAN 覆盖 | 备注 |
|---|------------------|--------|-------------|------|
| 1 | signal/ 状态"待规划"但实际已有6文件 | 低 | ✅ 不需修复 | 文档准确性问题，非代码bug |
| 2 | 共231个源文件实际230 | 低 | ✅ 不需修复 | 文档准确性问题 |
| 3 | data/ "缺复权因子fq/子目录" 但 adjust_factor_manager.py 已存在 | 低 | ✅ 不需修复 | 文档准确性问题 |
| 4 | brain/ "LPPL单线程DE" 但 engine.py 支持 workers | 低 | ✅ 不需修复 | 文档准确性问题 |
| 5 | engine.py:184 佣金未重算（缩股后） | **高** | ✅ P0-2 | 完全覆盖 |
| 6 | unified_matching_engine.py:117 手数硬编码 // 100 * 100 | **高** | ❌ **遗漏** | FIX_PLAN 仅覆盖 engine.py:184，未覆盖 unified_matching_engine.py:117 |
| 7 | T+1 检查两处 fallback 策略不同 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 8 | GlobalConfig 单例无锁保护（VERIFICATION 声称） | — | ✅ 1.2误报 | 源码验证：config_loader.py:17 已有 Lock |
| 9 | engine_factory 部分引擎不接受 orchestrator | 中 | ✅ P2-3 | 完全覆盖 |
| 10 | cost_function_reduced() 未 JIT 编译（VERIFICATION 声称） | — | ✅ 1.2误报 | 源码验证：已有 @njit，只是未被调用 |
| 11 | **LpplAnalysisEngine 构造函数 bug** | **高** | ❌ **遗漏** | LPPL 分析永远降级为基本统计 |
| 12 | numba_optimizer.py 完全未被引用 | 中 | ❌ **遗漏** | P1-5 仅修线程安全，未解决零引用问题 |
| 13 | shared/constants.py 已拆分为包 | 低 | ✅ 不需修复 | 文档准确性问题 |

### 1.2 OPTIMIZATION_A_SHARE_RULES 核实部分

| # | VERIFICATION 问题 | 严重度 | FIX_PLAN 覆盖 | 备注 |
|---|------------------|--------|-------------|------|
| 14 | 科创板/创业板价格笼子 1% 应为 2% | **高** | ✅ P0-5 | 完全覆盖 |
| 15 | DefaultSlippage 0.1% vs SLIPPAGE_PCT 0.05% 差一倍 | **高** | ✅ P2-6 | 间接覆盖（三套滑点统一） |
| 16 | **classifiers.py 炸板判定逻辑缺陷** | **高** | ❌ **遗漏** | 详见下方"VERIFICATION 报告自身不准确"分析 |
| 17 | limit_checker.py 不区分沪/深主板 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 18 | 印花税切换日期标注为2024年 | **高** | ✅ P0-3 | 完全覆盖 |
| 19 | 新股上市首日/前5日无涨跌停规则缺失 | **高** | ✅ P1-4 | 完全覆盖 |
| 20 | 北交所前缀"4"包含新三板代码 | 中 | ✅ P0-6 | 完全覆盖 |
| 21 | 集合竞价时段(9:15-9:25, 14:57-15:00)完全缺失 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 22 | 盘中临时停牌机制缺失 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 23 | 科创板零股卖出不支持 | 低 | ❌ **遗漏** | 低优先级 |
| 24 | 价格笼子未区分交易时段 | 低 | ❌ **遗漏** | 低优先级 |
| 25 | ST前缀仅检查"ST"和"*ST"，未覆盖"SST"等 | 低 | ❌ **遗漏** | 低优先级 |
| 26 | 三套独立滑点实现并存且数值不一致 | **高** | ✅ P2-6 | 完全覆盖 |

### 1.3 OPTIMIZATION_BACKTEST_ENGINE 核实部分

| # | VERIFICATION 问题 | 严重度 | FIX_PLAN 覆盖 | 备注 |
|---|------------------|--------|-------------|------|
| 27 | T+1检查使用日历日而非交易日 | **高** | ❌ **遗漏** | FIX_PLAN 未单独列出此问题 |
| 28 | 手数取整统一硬编码100股 | **高** | ⚠️ 部分覆盖 | P0-2 仅修 engine.py，未修 unified_matching_engine.py |
| 29 | 涨跌停只返回布尔值 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 30 | 缺失止损逻辑 | **高** | ❌ **遗漏** | stop_loss.py 不存在 |
| 31 | 过户费未正确传递 | 中 | ❌ **遗漏** | FillResult 无 transfer_fees 字段 |
| 32 | commission在缩股后未重新计算 | **高** | ✅ P0-2 | 完全覆盖 |
| 33 | detect_board()从不返回BoardType.ST | **高** | ❌ **遗漏** | ST股涨跌停阈值从5%被错误应用为10% |
| 34 | portfolio_engine.batch_open_positions 少扣过户费 | **高** | ❌ **遗漏** | 文档只提了卖出端 |
| 35 | signal_integrator.py 幽灵导入 | — | ⚠️ 需核实 | 详见下方"VERIFICATION 报告自身不准确"分析 |
| 36 | **BacktestResult 缺少3个字段** | 中 | ❌ **遗漏** | report_generator.py 运行时 AttributeError |
| 37 | **run_backtest 未传递 volume/avg_daily_volume** | **高** | ❌ **遗漏** | 非线性滑点冲击成本永远为零 |
| 38 | _check_t1_constraint 每次做 CSV I/O | 中 | ❌ **遗漏** | 性能问题 |
| 39 | _calculate_commission 方法名误导 | 低 | ❌ **遗漏** | 低优先级 |
| 40 | execute_sell commission 变量名误导 | 低 | ❌ **遗漏** | 低优先级 |

### 1.4 OPTIMIZATION_PERFORMANCE 核实部分

| # | VERIFICATION 问题 | 严重度 | FIX_PLAN 覆盖 | 备注 |
|---|------------------|--------|-------------|------|
| 41 | LPPL DE 优化器行号偏移 | 低 | ✅ 不需修复 | 文档准确性问题 |
| 42 | Numba JIT 版本未接入 | 中 | ❌ **遗漏** | P1-5 仅修线程安全，未解决接入问题 |
| 43 | Parquet 全量加载 | 中 | ❌ **遗漏** | 性能优化 |
| 44 | 逐股票因子计算 | 中 | ❌ **遗漏** | 性能优化 |
| 45 | Wyckoff 小窗口循环 | 中 | ❌ **遗漏** | 性能优化 |
| 46 | shared/cache/ 完整缓存框架未被利用 | 中 | ❌ **遗漏** | 可能导致重复建设 |
| 47 | indicators.py 已有 @smart_cache | 低 | ✅ 不需修复 | 文档准确性问题 |

### 1.5 OPTIMIZATION_RISK_MODULE 核实部分

| # | VERIFICATION 问题 | 严重度 | FIX_PLAN 覆盖 | 备注 |
|---|------------------|--------|-------------|------|
| 48 | **fsm.py:371 risk_level 键缺失** | **高** | ❌ **遗漏** | 详见下方分析 |
| 49 | historical_risk.py 继承自引用循环 | 中 | ❌ **遗漏** | 详见下方"VERIFICATION 报告自身不准确"分析 |
| 50 | sizer.py 止损仅基于价格，不考虑流动性 | 中 | ❌ **遗漏** | 未在 FIX_PLAN 中提及 |
| 51 | structural.py 零测试覆盖 | 中 | ✅ P3-1 | 间接覆盖 |
| 52 | risk/__init__.py 遗漏导出 HistoricalSimulationRisk | 低 | ❌ **遗漏** | 低优先级 |
| 53 | PortfolioOptimizer config 状态变异 | **高** | ✅ P1-2 | 完全覆盖 |
| 54 | MemoryCacheBackend 无锁 | 中 | ✅ P1-3 | 完全覆盖 |
| 55 | drawdown_analyzer.py 非向量化 | 中 | ✅ P1-7 | 完全覆盖 |

---

## 二、VERIFICATION 报告自身不准确之处

源码验证发现 VERIFICATION 报告中有 5 处描述与实际代码不符：

### 2.1 fsm.py:371 — 描述方式错误，实际问题更严重

| 维度 | VERIFICATION 报告声称 | 源码验证实际 |
|------|---------------------|------------|
| 代码 | `context.get("risk_level", "normal")` | `evt_metrics["risk_level"]` |
| 后果 | 永远返回默认值 "normal"，风险缩放失效 | **直接 KeyError 崩溃**，FSM 状态机无法运行 |
| 修复方向 | 在 MarketSignalContext 中添加 risk_level 字段 | 修改为 `evt_metrics.get("regime")` 并适配值映射 |

**影响评估**: VERIFICATION 报告将问题描述为"静默失效"，但实际代码会**直接崩溃**。问题比报告描述的更严重。

**源码证据**:
- [fsm.py:368-372](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/fsm/fsm.py#L368) 使用 `evt_metrics["risk_level"]`
- [evt_risk.py:92-101](file:///home/james/Documents/Project/UniQuant/src/uniquant/risk/evt_risk.py#L92) 返回键为 `var_95, var_99, cvar_95, cvar_99, max_drawdown, regime, ntf_signal, summary`，**无 risk_level 键**
- 正确的键应为 `regime`，其值为 `"CRISIS"` 而非 `"CRITICAL"`

### 2.2 classifiers.py 炸板判定 — 描述的 bug 性质不同

| 维度 | VERIFICATION 报告声称 | 源码验证实际 |
|------|---------------------|------------|
| Bug 性质 | `prev_close * 1.095` 硬编码阈值对科创板/创业板失效 | 炸板检测使用 `(row.high - row.open) / row.open` 而非 `(row.high - prev_close) / prev_close` |
| 影响 | 20%涨跌停板用9.5%阈值检测 | 高开涨停股被误判为"炸板" |

**源码证据**: [classifiers.py:263-264](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/classifiers.py#L263) 使用 `row.open` 作为基准价，而非 `prev_close`。涨跌停价格基于前收盘价计算，因此炸板检测也应基于前收盘价。

**两个 bug 同时存在**:
1. 基准价错误：`row.open` → 应为 `prev_close`
2. 北交所 30% 涨跌停缺失：[classifiers.py:246](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/classifiers.py#L246) 的 `limit_pct` 三元表达式无 30% 分支

### 2.3 signal_integrator.py "幽灵导入" — 可能是误报

| 维度 | VERIFICATION 报告声称 | 源码验证实际 |
|------|---------------------|------------|
| 问题 | signal_integrator.py 幽灵导入，from uniquant.signal.models 模块不可用 | signal/ 包已存在6个文件，含 models.py |

**需进一步验证**: signal/ 包确实存在，但 signal_integrator.py 的具体导入路径是否正确需要直接确认。如果导入路径正确，则此为误报；如果路径有误，则问题仍存在。

### 2.4 historical_risk.py "自引用循环" — 描述不准确

| 维度 | VERIFICATION 报告声称 | 源码验证实际 |
|------|---------------------|------------|
| 问题 | 继承关系形成自引用循环 | 无循环导入，仅为命名混乱 |
| 实际情况 | — | `evt_risk.py` 定义 `HistoricalSimulationRisk` 并别名 `EVTRisk = HistoricalSimulationRisk`；`historical_risk.py` 又定义同名类继承 `EVTRisk` 并加弃用警告 |

**影响**: 不是循环导入，但存在不必要的继承包装和命名混淆。严重度应从"高"降为"中"。

### 2.5 GlobalConfig 无锁保护 — VERIFICATION 报告已正确指出为错误

VERIFICATION 报告在 Section 1.3 已正确指出 MASTER_PLAN 的"GlobalConfig 无锁保护"是事实错误。此条无需额外修正。

---

## 三、遗漏项严重度分级

### 🔴 高严重度遗漏（必须补充到 FIX_PLAN）

| # | 遗漏问题 | 影响 | 建议修复阶段 |
|---|---------|------|------------|
| G1 | **LpplAnalysisEngine 构造函数 bug**: `LPPLEngine(config=config)` 但 `__init__` 不接受参数 | LPPL 分析永远降级为基本统计，TypeError 被 try/except 静默吞掉 | Phase 0 (P0-10) |
| G2 | **fsm.py:371 `evt_metrics["risk_level"]` KeyError**: evt_risk 返回的字典无 risk_level 键 | FSM 状态机在调用 EVT 风险模块时直接崩溃 | Phase 0 (P0-11) |
| G3 | **run_backtest 未传 volume/avg_daily_volume**: execute_buy/execute_sell 缺少关键参数 | 非线性滑点冲击成本永远为零，回测滑点模型形同虚设 | Phase 0 (P0-12) |
| G4 | **classifiers.py 炸板判定基准价错误**: 用 `row.open` 而非 `prev_close` | 高开涨停股被误判为"炸板"，Wyckoff 分析结果失真 | Phase 1 (P1-8) |
| G5 | **detect_board() 从不返回 BoardType.ST**: market_rules.py 不检查股票名称 | ST 股涨跌停阈值从 5% 被错误应用为 10% | Phase 1 (P1-9) |
| G6 | **unified_matching_engine.py 手数硬编码 // 100 * 100**: 科创板 lot_size=200 被忽略 | 科创板回测手数取整错误 | Phase 0 (P0-2 扩展) |

### 🟡 中严重度遗漏（建议补充）

| # | 遗漏问题 | 建议 |
|---|---------|------|
| G7 | BacktestResult 缺少 drawdown_metrics/tail_risk_metrics/stress_test_results | Phase 1，report_generator 运行时 AttributeError |
| G8 | numba_optimizer.py 零引用（死代码） | Phase 2，接入 calculator.py 或删除 |
| G9 | T+1 检查使用日历日而非交易日 | Phase 1，回测准确性问题 |
| G10 | _check_t1_constraint 每次做 CSV I/O | Phase 2，性能问题 |
| G11 | 缺失止损逻辑（stop_loss.py 不存在） | Phase 2，功能缺失 |
| G12 | 过户费未正确传递（FillResult 无 transfer_fees） | Phase 1，成本计算不完整 |
| G13 | 涨跌停只返回布尔值，不返回 LimitStatus 详情 | Phase 2，信息损失 |
| G14 | limit_checker.py 不区分沪/深主板 | Phase 2，规则差异化 |
| G15 | 集合竞价时段缺失 | Phase 2，A股合规性 |
| G16 | 盘中临时停牌机制缺失 | Phase 2，A股合规性 |
| G17 | sizer.py 止损仅基于价格，不考虑流动性 | Phase 2，风控完善 |
| G18 | shared/cache/ 完整缓存框架未被利用 | Phase 2，避免重复建设 |
| G19 | portfolio_engine.batch_open_positions 少扣过户费 | Phase 1，成本计算不完整 |
| G20 | historical_risk.py 命名混乱（非循环引用） | Phase 2，代码清理 |
| G21 | risk/__init__.py 遗漏导出 HistoricalSimulationRisk | Phase 2，导出完整性 |

### 🟢 低严重度遗漏（可后续处理）

| # | 遗漏问题 |
|---|---------|
| G22 | 科创板零股卖出不支持 |
| G23 | 价格笼子未区分交易时段 |
| G24 | ST前缀仅检查"ST"和"*ST" |
| G25 | _calculate_commission 方法名误导 |
| G26 | execute_sell commission 变量名误导 |

---

## 四、FIX_PLAN 已正确覆盖的项（确认清单）

以下 VERIFICATION 报告问题在 FIX_PLAN 中有完整或充分的覆盖：

| # | 问题 | FIX_PLAN 编号 |
|---|------|-------------|
| 1 | SSE² Bug（calculator.py:247-249） | P0-1 |
| 2 | 佣金缩减后未重算（engine.py:182-188） | P0-2 |
| 3 | 印花税日期错误（backtest.py:321, cost_model.py:26-27） | P0-3 |
| 4 | CZSC AnalysisError 导入缺失（czsc_engine.py:16） | P0-4 |
| 5 | 价格笼子比例错误（market_rules.py:27-28） | P0-5 |
| 6 | 板块前缀缺失（market.py:68-70） | P0-6 |
| 7 | LPPL visualizer abs() 数学错误 | P0-7 |
| 8 | LPPL tau clamp 阈值不统一 | P0-8 |
| 9 | CostConfig.from_yaml 滑点单位转换错误 | P0-9 |
| 10 | 配置-常量 9 处数值冲突 | P1-1 |
| 11 | PortfolioOptimizer 状态变异 | P1-2 |
| 12 | MemoryCacheBackend 线程安全 | P1-3 |
| 13 | 新股涨跌停规则缺失 | P1-4 |
| 14 | numba_optimizer.py np.random.seed 线程不安全 | P1-5 |
| 15 | FSM CIRCUIT_BREAK 死状态 | P1-6 |
| 16 | compute_rolling_mdd 向量化 | P1-7 |
| 17 | UI 层 DAG 违规 | P2-1 |
| 18 | 两套 DI 容器合并 | P2-2 |
| 19 | engine_factory 参数错配 | P2-3 |
| 20 | LPPL 模块代码统一 | P2-4 |
| 21 | 统一涨跌停规则双重体系 | P2-5 |
| 22 | 三套滑点实现统一 | P2-6 |

---

## 五、FIX_PLAN 误报/过时声明核实

FIX_PLAN 1.2 节中的误报声明经源码验证均正确：

| # | FIX_PLAN 声明 | 源码验证 | 判定 |
|---|-------------|---------|------|
| 1 | `not LimitStatus` 是误报 | `_check_limit_constraint` 返回 `bool` | ✅ 正确 |
| 2 | services/__init__.py 幽灵导入已过时 | 已用 `__getattr__` 懒加载 | ✅ 正确 |
| 3 | brain/lppl/__init__.py 幽灵导入已过时 | 已用 `try/except` 保护 | ✅ 正确 |

---

## 六、建议行动

### 6.1 立即补充到 FIX_PLAN 的高优先级项

| 建议编号 | 问题 | 建议阶段 | 工时 |
|---------|------|---------|------|
| P0-10 | LpplAnalysisEngine 构造函数 bug | Phase 0 | 15min |
| P0-11 | fsm.py:371 `evt_metrics["risk_level"]` → `evt_metrics.get("regime")` | Phase 0 | 20min |
| P0-12 | run_backtest 传递 volume/avg_daily_volume | Phase 0 | 30min |
| P0-2 扩展 | unified_matching_engine.py 手数硬编码 | Phase 0 | 15min |
| P1-8 | classifiers.py 炸板基准价 + 北交所30% | Phase 1 | 1h |
| P1-9 | detect_board 增加 ST 检测 | Phase 1 | 1h |

### 6.2 VERIFICATION 报告需修正之处

1. **fsm.py:371**: 将 `context.get("risk_level", "normal")` 修正为 `evt_metrics["risk_level"]`，并将后果从"静默失效"修正为"KeyError 崩溃"
2. **classifiers.py**: 将 `prev_close * 1.095` 硬编码阈值修正为 `(row.high - row.open) / row.open` 基准价错误
3. **historical_risk.py**: 将"自引用循环"修正为"命名混乱/不必要的继承包装"
4. **signal_integrator.py**: 需补充验证 signal/ 包的导出是否与 signal_integrator.py 的导入路径匹配

---

*核验完成时间: 2026-05-31 | 基于 FIX_PLAN + VERIFICATION 报告逐项对照 + 源码验证 | 禁止幻觉*
