# UniQuant 系统审判验证方案

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

生成日期: 2026-06-05  
适用范围: 中国 A 股量化分析、因子研究、回测撮合、组合回测、风控与数据管道  
基准原则: 以当前源码事实为准，不采用过期架构文档中关于 `data/`、`signal/`、`hands/` 不存在的旧状态描述。

## 1. 验证目标

本方案用于执行 UniQuant 的 System Judgment 验证，重点识别会导致实盘亏损、回测虚高或研究结论失效的缺陷。

四个审判维度:

1. 未来函数与幸存者偏差: 严查 `shift(-N)`、当日收盘成交、全样本复权因子、财务公告提前可见、退市/ST 样本缺失。
2. A 股微观结构拟真: 验证 T+1、涨跌停无法成交、ST/科创/创业/北交所涨跌幅、印花税、佣金、过户费、滑点和冲击成本。
3. 工程架构与性能: 检查主路径是否有 `iterrows()`、重复 DataFrame copy、逐行 I/O、循环依赖和全市场数据内存爆炸风险。
4. 策略过拟合与风控: 验证 walk-forward、deflated Sharpe、尾部风险、连续跌停无法卖出的真实暴露。

## 2. 分模块读取与分析计划

### 2.1 回测撮合与交易约束

核心文件:

- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/hands/backtest/engine.py`
- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/shared/limit_checker.py`
- `src/uniquant/shared/cost_model.py`
- `src/uniquant/shared/market_rules.py`
- `src/uniquant/data/managers/trade_calendar_manager.py`

检查点:

- 所有回测路径是否强制走 `UnifiedMatchingEngine`，是否存在绕行成本、滑点和交易约束的旧执行路径。
- 买入涨停、卖出跌停是否真正阻断成交，不能只返回 `rejected_mask=True` 但仍保留非零 `executed_shares`。
- T+1 是否基于交易日历判断，不能用自然日。
- 交易成本是否进入真实现金流:
  - 买入: `cash_out = shares * exec_price + commission + transfer_fee`
  - 卖出: `cash_in = shares * exec_price - commission - stamp_tax - transfer_fee`
- 最低佣金缩股后是否重新计算。
- 滑点和冲击成本是否使用订单量占 ADV，而不是用全日成交量误代订单量。
- ST、科创板、创业板、北交所的涨跌幅规则是否由统一入口识别。

初步高风险位置:

- `UnifiedMatchingEngine.fill_buy()` 计算了 `transfer_fees`，但 `FillResult` 未返回过户费字段。
- `PortfolioEngine.batch_open_positions()` 当前扣现金疑似只扣 `成交额 + commission`，需要验证是否漏扣过户费。
- `PortfolioEngine.batch_close_positions()` 当前卖出净额疑似只扣 `commission + stamp_duty`，需要验证是否漏扣过户费。
- `BacktestEngine` 仍有独立的成本和滑点执行逻辑，需要判断是兼容层还是实盘可用路径。

### 2.2 未来函数、复权与数据点时一致性

核心文件:

- `src/uniquant/data/pipeline/data_adjuster.py`
- `src/uniquant/data/pipeline/data_aligner.py`
- `src/uniquant/data/pipeline/data_validator.py`
- `src/uniquant/data/managers/factor_manager.py`
- `src/uniquant/data/managers/adjust_factor_manager.py`
- `src/uniquant/data/services/import_financial.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/financial_bridge.py`
- `src/uniquant/brain/factors/custom_factors.py`
- `src/uniquant/brain/factors/auto_mined/*.py`

检查点:

- 前复权是否只使用回测截面当时可知的复权因子。
- 财务数据是否按公告日进入特征，不得按报告期末提前进入。
- 因子 IC 的 `shift(-N)` 是否只用于离线标签生成。
- live 模式是否拒绝任何远期收益、未来时间戳和全样本归一化。
- 股票池是否保留退市、ST、暂停上市、长期停牌样本。
- 行业、市值、中性化特征是否点时一致，不能使用未来行业分类或未来市值。

必须满足:

```text
feature_time <= decision_time < execution_time
label_time > decision_time
financial_announce_date <= decision_time
adjust_factor_effective_date <= decision_time
```

### 2.3 组合回测、信号延迟、仓位与风控

核心文件:

- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/hands/backtest/overfitting_detector.py`
- `src/uniquant/hands/backtest/robustness_checker.py`
- `src/uniquant/hands/backtest/monte_carlo.py`
- `src/uniquant/hands/strategies/*.py`
- `src/uniquant/risk/sizer.py`
- `src/uniquant/risk/evt_risk.py`
- `src/uniquant/risk/portfolio_optimizer.py`
- `src/uniquant/risk/historical_risk.py`

检查点:

- 信号日和成交日必须错开，不能当天收盘信号当天收盘成交。
- 多标的调仓必须按当日可交易股票集执行。
- 跌停无法卖出时，仓位和风险暴露必须继续保留。
- 仓位模型必须考虑 T+1、涨跌停、最小交易单位和流动性容量。
- 风控必须能在撮合前改变订单，而不只是事后统计指标。
- 组合收益指标应扣除交易成本后再计算。

超额收益信息比率应按成本后收益计算:

```text
IR = E[R_p - R_b - C_transaction] / std(R_p - R_b)
```

其中:

```text
C_transaction = commission_buy + commission_sell + stamp_tax_sell
              + transfer_fee_buy + transfer_fee_sell + slippage + market_impact
```

### 2.4 性能与架构依赖

核心文件:

- `src/uniquant/services/service_container.py`
- `src/uniquant/services/analysis/engine_factory.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/data/lake/storage_manager.py`
- `src/uniquant/shared/cache/*`

检查点:

- 主回测路径不得使用 `DataFrame.iterrows()`。
- 大规模面板计算应优先使用向量化、NumPy、Numba、DuckDB、PyArrow 或分区读取。
- 服务层必须遵循 DAG: `shared -> data -> brain/risk/signal -> hands -> services -> ui`。
- `shared` 层不得反向依赖 `services`、`hands`、`ui`。
- 数据湖必须支持列裁剪、日期切片、按 symbol/date 分区。
- 缓存不得污染点时数据，尤其不能把未来截面缓存给历史回测。

## 3. 命令级验证计划

### 3.1 导入链与基础完整性

```bash
python -c "import uniquant; import uniquant.shared; import uniquant.data; import uniquant.hands; print('import OK')"
python -c "from uniquant.hands.backtest import BacktestEngine, PortfolioEngine; print('backtest OK')"
pytest tests/test_import_state.py tests/test_engine_factory.py -q
```

通过标准:

- 所有导入命令返回 0。
- 不允许出现 `ImportError`、`ModuleNotFoundError` 或循环导入。
- `engine_factory` 测试通过。

### 3.2 A 股微观结构单元验证

```bash
pytest tests/test_limit_checker.py tests/test_matching_engine.py tests/test_t1_constraint_boundary.py -q
pytest tests/test_backtest_engine.py tests/test_backtest_advanced.py tests/test_portfolio_engine_v2.py -q
```

必须覆盖:

- 主板 10%、科创/创业 20%、北交所 30%、ST 5%。
- 涨停买入拒单: `rejected_mask=True` 且 `executed_shares=0`。
- 跌停卖出拒单: `rejected_mask=True` 且 `executed_shares=0`。
- T+0 卖出拒绝。
- 周五买入、下周一卖出允许。
- 非交易日卖出拒绝。
- 交易日历缺失时保守拒绝。
- 2023-08-28 前后印花税率切换正确。
- 买入、卖出均扣过户费。

### 3.3 未来函数与复权验证

```bash
pytest tests/test_lookahead_bias.py tests/test_factor_analyzer.py tests/test_financial_bridge.py -q
pytest tests/test_data_chaos_qa.py tests/test_field_mapping.py tests/test_build_financial_v2.py -q
```

必须覆盖:

- `FactorAnalyzer.compute_ic_ir(..., mode=AnalysisMode.LIVE)` 拒绝远期收益标签。
- `_compute_forward_returns(..., mode="live")` 拒绝负 shift。
- 未来时间戳必须拒绝。
- qfq 截断样本结果不得使用截断后发生的除权事件。
- 财务因子必须按公告日滞后进入。
- 股票池生成不得只使用当前仍上市股票。

### 3.4 策略过拟合与风控验证

```bash
pytest tests/test_walk_forward_pipeline.py tests/test_evt_risk.py tests/test_portfolio_optimizer.py -q
pytest tests/test_sizer.py tests/test_drawdown_analyzer.py tests/test_cvar_empty_tail.py -q
```

必须覆盖:

- walk-forward 训练窗口和测试窗口严格分离。
- 参数选择不能使用测试窗口收益。
- Deflated Sharpe Ratio 在交易样本足够时计算。
- CVaR、EVT、最大回撤在极端收益序列下不返回 NaN 或 inf。
- 连续跌停导致无法卖出的仓位不得被风控模块直接消失。

### 3.5 性能与静态质量验证

```bash
ruff check src/uniquant
pytest tests/test_czsc_bar_list_vectorization.py tests/test_macro_and_scan_regressions.py -q
rg -n "iterrows\\(|shift\\(-|groupby\\(.*\\)\\.apply|pd\\.concat\\(" src/uniquant tests
```

性能基准建议:

- 合成 5000 只股票、2500 个交易日、OHLCV + signal 面板。
- 组合日频回测核心路径应控制在秒级到低分钟级。
- 主路径不得出现 `iterrows()`。
- `groupby.apply()` 只能用于研究分析或小样本路径，不能进入全市场生产回测主循环。

## 4. P0/P1 验证任务清单

### P0-1 现金流正确性审判

目标: 验证交易现金流完整扣费，尤其是组合回测的过户费。

文件:

- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/shared/cost_model.py`

验收:

- 买入现金扣减等于 `value + commission + transfer_fee`。
- 卖出现金增加等于 `value - commission - stamp_duty - transfer_fee`。
- PnL 使用净成交额计算。
- 测试覆盖买入和卖出两侧过户费。

### P0-2 拒单成交一致性审判

目标: 所有被拒订单必须零成交。

验收:

- 涨停买入: `rejected_mask=True`、`limit_violation_mask=True`、`executed_shares=0`。
- 跌停卖出: `rejected_mask=True`、`limit_violation_mask=True`、`executed_shares=0`。
- T+1 违规卖出: `t1_violation_mask=True`、`executed_shares=0`。
- 现金不足无法满足最小交易单位: `executed_shares=0`。

### P0-3 信号成交时间审判

目标: 禁止当日收盘信号当日成交。

验收:

- 单标的回测: `idx` 生成信号，只能 `idx+1` 或之后成交。
- 组合回测: 当日 signal 进入 `_pending_signals`，下一交易日撮合。
- 最后一日信号不得在同一最后日期强制成交，除非明确建模为收盘前可见信号。

### P1-1 复权点时一致性审判

目标: qfq/hfq 不泄露未来除权事件。

验收:

- 对同一股票，截断到日期 T 的 qfq 结果不得依赖 T 之后因子。
- `merge_asof(..., direction="backward")` 后仍需确认 factor 表本身不含未来计算污染。
- 保存因子时必须记录 `effective_date` 或等价字段。

### P1-2 财务数据点时一致性审判

目标: 财务特征按公告日可见，不按报告期末提前可见。

验收:

- 每个财务特征必须满足 `announce_date <= decision_date`。
- 若缺公告日，应使用保守滞后规则，不得默认报告期末可用。
- 测试覆盖年报、季报、修正公告和缺失公告日。

### P1-3 幸存者偏差审判

目标: 股票池保留历史真实可交易样本。

验收:

- 股票池包含退市股票历史区间。
- ST 状态按历史日期切换，不按当前名称回填全历史。
- 停牌日不可成交，但持仓净值应保留。
- 新股上市未满 N 日样本可按策略规则过滤，但必须显式记录。

### P1-4 性能主路径审判

目标: 全市场回测不被 Pandas 逐行循环击穿。

验收:

- 主撮合层使用 NumPy 数组批量处理。
- 组合回测信号处理不能长期保留 `iterrows()`。
- 数据读取支持日期和列裁剪。
- 合成大面板性能测试纳入 CI 或 nightly。

## 5. 必须执行的 A 股历史压力测试

### 5.1 2015 股灾与千股跌停

区间: 2015-06-15 至 2015-08-26

验证目标:

- 连续跌停无法卖出。
- 杠杆去化导致流动性冲击扩大。
- 策略不得假设止损一定能成交。
- 最大回撤、CVaR、尾部损失应显著恶化。

### 5.2 2018 去杠杆熊市

区间: 2018-01-29 至 2018-10-19

验证目标:

- 趋势因子和小盘因子在长期熊市中的失效。
- 换手成本对高频调仓策略的侵蚀。
- 行业中性和市值中性是否稳定。

### 5.3 2024 年初微盘流动性枯竭

区间: 2024-01-22 至 2024-02-08

验证目标:

- 微盘股连续跌停、盘口无量、无法卖出的仓位冻结。
- 风控是否提前限制小成交额股票容量。
- 冲击成本是否随成交量占比非线性上升。
- 组合回撤不能通过虚假成交被低估。

## 6. 最终交付标准

完成验证后，应输出 System Judgment 报告，结构如下:

1. 致命缺陷清单: P0/P1 缺陷、文件、行号、触发条件、资金后果。
2. A 股特异性校准: T+1、涨跌停、费用、滑点、冲击成本、停牌、ST、退市修正公式。
3. 架构重构与性能压榨代码: 提供最小正确补丁或重构方案，保持无循环依赖。
4. 极端行情压力测试建议: 给出场景、样本区间、预期指标变化和失败阈值。

整体判定规则:

- 存在现金流漏扣、未来函数、同日信号同日成交、退市样本缺失中的任一项，系统不得进入实盘。
- 存在涨跌停/T+1 拟真缺陷，所有回测收益指标只能标记为研究草稿。
- 存在主路径 `iterrows()` 或全量内存扫描，系统不得执行全市场十年级别回测。
