# Phase E — 回测信任度扩展审计报告

> 日期: 2026-07-06
> 审计范围: `src/uniquant/hands/backtest/` + `src/uniquant/shared/slippage_model.py` + `src/uniquant/shared/cost_model.py` + `src/uniquant/shared/limit_checker.py`

---

## 总结

**回测信任度评分: B+**

7 条防线状态:
| 防线 | 状态 | 备注 |
|---|---|---|
| A. T+1 铁律 | PASS | 双保险 (引擎 + 撮合), 交易日序号差 + 自然日 + 下一个交易日三重检查 |
| B. 涨跌停拦截 | PASS | 覆盖所有板块, 含 IPO 特殊规则, 比例 + 舍入价格双重保障 |
| C. 停牌拦截 | PASS | volume=0 拒绝成交 |
| D. 资金不透支 | PASS | 实时 cash_available 全局扣减, 自动减量 |
| E. 非对称成本 | PASS | 印花税仅卖方, 日期感知 2023-08-28 阈值, 最低佣金 5 元 |
| F. 滑点方向 | PASS | 买高卖低, 使用交易量 (trade_volume) 而非日均量 |
| G. 整手取整 | PASS | A股 100 股为一手, 逐板块 lot_size |

扩展审计评分:
| 子项 | 评级 | 关键发现 |
|---|---|---|
| E1 完全复制 | A | 完全确定性; `compare()` 方法可用; Monte Carlo 独立且有种子 |
| E2 信号时间偏移 | A | T 日信号 → T+1 日 Open 成交, 挂单机制正确 |
| E3 滑点敏感性 | B+ | 基础 + 冲击双分量; 环境变量可配; 但未做敏感性扫描 |
| E4 费用敏感性 | B+ | CostConfig 完整 (env/yaml/默认); 未做敏感性扫描 |
| E5 组合 vs 单票 | B | PortfolioEngine 已弃用且与 UnifiedBacktestEngine 路径不一致 |
| E6 T+1 约束 | A | 三重检查; 向量化实现; 引擎 + 撮合双保险 |
| E7 涨跌停成交率 | A | 完整覆盖所有板块 + IPO 特殊规则 |
| E8 基准对比 | B | BenchmarkComparator 独立存在但未集成到引擎输出 |

---

## E1 完全复制回测

**评级: A**

**确定性检查**: `unified_engine.py` 和 `unified_matching_engine.py` 中均无 `random`/`seed`/`shuffle`/`hash` 调用。回测执行路径完全确定性——给定相同输入始终产生相同输出。

**Monte Carlo 模块**: `monte_carlo.py` 使用 `np.random.default_rng(seed)` 且默认种子为 42, 但该模块是独立分析工具, 不参与主线回测流水线。

**旧引擎**: `engine.py` 的 `BacktestEngine` 构造函数接受 `monte_carlo_seed` 参数, 但该引擎已标记为 DEPRECATED, 使用者应迁移到 `UnifiedBacktestEngine`。

**结果比较**: `BacktestResult.compare()` 方法 (`unified_engine.py:120`) 提供结构化的差值字典比较, 支持参数敏感性分析。

**结论**: 主线回测完全确定性, 可复现。无哈希排序或随机化问题。

---

## E2 信号时间偏移

**评级: A**

**信号调度**: `UnifiedBacktestEngine.run()` 使用 `pending_order` 延迟执行机制:
1. 第 T 日 Step 3 收集信号 → 生成挂单 (`pending_order`)
2. 第 T+1 日 Step 1 以 Open 价执行挂单 (T+1 延迟)

**索引**: `_index_signals_by_date()` 按 `sig.timestamp` 的日期字符串索引信号, 时间戳为 `Optional`, 缺失时归入 "unknown" 键。

**执行顺序**: 同天多信号仲裁优先级: LPPL SELL > BUY > 非 LPPL SELL (`unified_engine.py:311-344`)。

**交易日历**: `TradeCalendarManager` 用于跳过非交易日, 非交易日也更新权益曲线。

**风险**: 非交易日也计入权益曲线和日收益率, 这可能略微拉低夏普比率, 但属于保守稳健做法。

---

## E3 滑点敏感性分析

**评级: B+**

**模型**: 两个滑点模型并存:
- `DefaultSlippage`: 固定 `SLIPPAGE_PCT` (0.05%)
- `DynamicSlippage`: 基于流动性 + ATR + 市场冲击 + 时间溢价, 输出范围 0.01%-0.5%

**引擎使用**: 
- `UnifiedBacktestEngine._calc_slippage()`: `base_slippage` (0.05%) + `impact_slippage` (0.001 * sqrt(volume_ratio), 上限 2%)
- `UnifiedMatchingEngine.compute_execution_prices()`: 相同逻辑, 向量化
- 关键修复: 使用 `trade_volume` (本次交易量) 而非 `daily_volume` (当日总成交量) (`unified_engine.py:520-522`)

**可配置性**: `slippage_rate` 通过构造函数参数传入, 默认值为 `SLIPPAGE_PCT` (0.0005)。`CostConfig` 支持 env 和 YAML 覆盖。

**缺口**: 无滑点敏感性扫描工具。`sensitivity_analyzer.py` 存在但未覆盖滑点参数的敏感性分析。

---

## E4 费用敏感性分析

**评级: B+**

**单真相源**: `cost_model.py` 是 A 股交易费用的唯一事实来源。所有引擎从该模块导入常量。

**参数默认值**:
| 参数 | 值 | 说明 |
|---|---|---|
| COMMISSION_PCT | 0.0003 (万3) | 券商佣金 |
| STAMP_TAX_PCT | 0.0005 (万5) | 2023-08-28 起 |
| STAMP_TAX_PCT_OLD | 0.001 (千1) | 2023-08-28 前 |
| MIN_COMMISSION | 5.0 | 单笔最低佣金 |
| SLIPPAGE_PCT | 0.0005 (万5) | 滑点 |
| TRANSFER_FEE_PCT | 0.00001 (万0.1) | 过户费 (沪市收) |

**日期感知**: `get_stamp_tax_pct()` 根据交易日期自动选择新旧税率 (`_STAMP_TAX_CUTOFF = 2023-08-28`)。

**可配置性**: `CostConfig` 支持 `from_env()` 和 `from_yaml()` 加载, 覆盖渠道完善。

**过户费**: 仅沪市股票 (60xxxx) 收费, `_has_transfer_fee()` 实现。

**缺口**: 与滑点一样, 无敏感性扫描工具来评估费用参数变化对回测结果的影响。

---

## E5 组合回测 vs 单票累加

**评级: B**

**PortfolioEngine**: 已标记为 DEPRECATED, 提示使用 `UnifiedBacktestEngine`。但 `PortfolioEngine` 不委托给 `UnifiedBacktestEngine`——它使用自己的 `run()` 方法, 接受 `pd.DataFrame` 信号而非 `List[TradingSignal]`。

**匹配引擎**: `PortfolioEngine` 内部使用 `UnifiedMatchingEngine` 进行向量化买卖, 共享 T+1、涨跌停、费用等约束。

**核心差异**:
- `UnifiedBacktestEngine`: 单票, `List[TradingSignal]`, 信号→挂单→延迟执行
- `PortfolioEngine`: 多票, `pd.DataFrame`, 日级批次执行, 信号在 T 日收盘后处理, 次日执行

**位置限制**: `max_positions` 控制组合大小, `sizing_fraction` 控制资金分配比例。

**风险**: 两个引擎的执行路径不一致, 单票累加结果不一定等于组合回测结果:
1. 信号格式不同 (typed vs DataFrame)
2. 执行时机不同 (延迟 vs 批次)
3. 资金分配逻辑不同 (全仓 vs 分仓)

**建议**: 如果 PortfolioEngine 仍在使用, 应将其迁移到 `UnifiedBacktestEngine` 的 `run_batch()` 模式, 或统一执行路径。

---

## E6 T+1 约束测试

**评级: A**

**三重检查**:

1. **UnifiedBacktestEngine 引擎层** (`unified_engine.py:426-440`):
   - `_check_t1()`: 自然日序数差 >= 1 + 下一个交易日检查
   - 在 `_execute_sell` 被调用前, `run()` 方法中 `pending_order` 执行时检查 (`unified_engine.py:274-276`)

2. **UnifiedMatchingEngine 撮合层** (`unified_matching_engine.py:220-235`):
   - `fill_sell()` 中向量化 T+1 违规检测
   - 检查: 交易日有效性 → 自然日序数 → 下一个交易日
   - 违规标记到 `t1_violation_mask`, 拒绝成交

3. **旧引擎 BacktestEngine** (`engine.py:157-158`):
   - `_check_t1_constraint()`: 使用预加载交易日序号数组 + searchsorted
   - 已弃用但功能完整

**实现细节**: `_next_trading_day()` 使用 `TradeCalendarManager.is_trading_day()` 循环查找, 最多 10 天。

**买日期**: `buy_date` 在买入成交时设置 (`unified_engine.py:270`), 仓位清空时重置为 None (`unified_engine.py:297`)。

---

## E7 涨跌停成交率

**评级: A**

**双路径实现**:

1. **单票检查** (`limit_checker.py`):
   - `check_limit_status()`: 前收盘价 → 价格比例 → 板块涨跌停阈值
   - `validate_trade_action()`: 涨停不买/跌停不卖
   - 覆盖 ST 股 (名称识别), 科创板/创业板 (前 5 日无限制), 北交所 (首日无限制), 主板 (首日 +44%/-36%)
   - 舍入价格双重保障 (`_round_limit_price` + 比例 + PRICE_TOLERANCE)

2. **向量化检查** (`unified_matching_engine.py:88-138`):
   - `compute_limit_status_vectorized()`: 快速路径 (无 name/tdl) 全向量化
   - 慢速路径: 逐元素处理 ST 名称和 IPO 特殊规则
   - 覆盖板块: main, st, sci_tech, gem, beijing

3. **引擎层** (`unified_engine.py:455-482`):
   - `_check_limit()`: 简单比例检查, 买卖方向感知
   - 在 `_execute_buy` 和 `_execute_sell` 中调用

**限制**: 涨跌停成交率指涨停/跌停状态下无法买卖, 而非涨停/跌停价上的成交概率。引擎假设涨停/跌停时完全无法成交, 这是合理的保守假设。

---

## E8 基准对比

**评级: B**

**BenchmarkComparator** (`benchmark.py`):
- `compare()`: Alpha, Beta, 跟踪误差, 信息比率, 超额收益, 相关性
- `calculate_alpha_beta()`: CAPM 模型, 日频回归
- `information_ratio()`: 年化信息比率
- `_tracking_error()`: 年化跟踪误差

**集成状态**: `BenchmarkComparator` 未集成到 `UnifiedBacktestEngine.run()` 的输出中。`BacktestResult.metadata` 不包含基准对比指标。使用者需要手动调用 `BenchmarkComparator.compare()`。

**默认基准**: `^GSPC` (标普 500) 作为基准, 这对 A 股策略不合理。A 股策略应使用沪深 300 (000300.SH) 或中证 500 等。

**缺口**: 
1. 引擎输出缺少基准对比
2. 默认基准不适合 A 股
3. 无内置基准数据获取逻辑

---

## 综合发现

### 已完成 (PASS)
- 7 条防线全部实现, 在引擎和撮合层双保险
- 确定性回测: 无随机性, 可完全复现
- T+1 约束: 三重检查, 向量化
- 涨跌停: 覆盖所有板块 + IPO 特殊规则
- 费用模型: 完整, 日期感知, 多源配置

### 待改进 (PARTIAL)
- **滑点敏感性**: 有滑点模型但无自动化敏感性扫描 (E3)
- **费用敏感性**: 有费用模型但无自动化敏感性扫描 (E4)
- **组合一致性**: PortfolioEngine 与 UnifiedBacktestEngine 路径不一致 (E5)
- **基准集成**: BenchmarkComparator 未集成到引擎输出, 默认基准不适合 A 股 (E8)

### 建议优先级
1. P0: 确认 PortfolioEngine 是否仍有使用者, 统一执行路径
2. P1: 将 BenchmarkComparator 集成到 BacktestResult, 默认基准改为沪深 300
3. P2: 为滑点和费用参数添加敏感性扫描工具
4. P3: 使用 `sensitivity_analyzer.py` 框架扩展覆盖滑点和费用参数

---

## ANALYSIS COMPLETE