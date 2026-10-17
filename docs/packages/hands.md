# hands -- 回测与策略

> **状态:** ✅ 已就绪 | **当前文件:** 22 | **说明:** UnifiedBacktestEngine 是当前主力回测引擎

`uniquant.hands` 模块是 UniQuant 的策略执行与回测子系统。该模块提供统一回测引擎、统一撮合引擎、函数式策略框架及内置策略，并包含回测分析工具（Monte Carlo 模拟、过拟合检测、稳健性检查、敏感性分析）。

> **2026-10-17（第八轮）**：`hands/backtest/report_generator.py`、`hands/backtest/benchmark.py`、`hands/backtest/trade_analysis/`（零引用）与类式（backtrader）策略子集（`strategies/base.py` + 5 个 `*_strategy.py`）已物理删除。旧 `BacktestEngine`（`hands/backtest/engine.py`）与 `PortfolioEngine`（`hands/backtest/portfolio_engine.py`）为更早已删除的历史条目，本页保留归档说明。

模块通过 `__init__.py` 延迟导入 `Reporter`、`ResultsManager` 和 `strategies`，避免循环依赖。

---

## ~~BacktestEngine 回测引擎~~（历史条目，已删除）

> **⚠️ 已删除**: `BacktestEngine`（原位于 `hands.backtest.engine`）已在早期清理轮次中物理删除（连同 `PortfolioEngine`、`SignalBacktestIntegrator`）。请直接使用 [`UnifiedBacktestEngine`](https://github.com/uniquant/uniquant/blob/main/src/uniquant/hands/backtest/unified_engine.py)。本章节保留为归档说明。

---

## UnifiedMatchingEngine 统一撮合引擎

`UnifiedMatchingEngine` 位于 `hands.backtest.unified_matching_engine`，是全系统强制使用的撮合核心，`UnifiedBacktestEngine` 通过它执行交易。

### 设计特点

- **向量化 NumPy**：所有计算基于 NumPy 数组批量处理，支持多资产同时撮合。
- **T+1 强制执行**：卖出时校验 `buy_dates` 与 `timestamps` 之间的交易日间隔，不足 1 个交易日的卖出被拒绝。同时调用 `TradeCalendarManager.is_trading_day()` 验证日期有效性。
- **板级涨跌停检查**：`compute_limit_status_vectorized` 根据 `MarketConstants.LIMIT_RATIO` 和 `get_board_type(symbol)` 判断每只股票所属板块（主板/创业板/科创板/北交所），分别适用不同涨跌停比例。买入时拒绝涨停股，卖出时拒绝跌停股。
- **非线性滑点模型**：`compute_execution_prices` 基于成交量占比计算冲击成本 `impact = min(0.001 * sqrt(vol_ratio), 0.02)`，叠加基础滑点 `slippage_rate`。
- **交易成本**：买入收取佣金（不低于 `min_commission`）；卖出额外收取印花税（`stamp_duty_rate`）。

## UnifiedBacktestEngine 统一回测引擎

> **推荐使用**: `UnifiedBacktestEngine` 位于 `hands.backtest.unified_engine`，是当前主力回测引擎，支持类型化 `TradingSignal` 输入、A股 SELL 优先逻辑、`BacktestResult.metadata` 扩展。

`UnifiedBacktestEngine` 取代了旧的 `BacktestEngine`，提供更严格的类型安全和 A 股规则执行：

```python
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.shared.interfaces import TradingSignal

engine = UnifiedBacktestEngine(initial_capital=100000.0)
result = engine.run(
    df=df,
    signals=[TradingSignal(action="BUY", ...)],
    symbol="600036",
)
```

### FillResult 数据类

```python
@dataclass
class FillResult:
    executed_shares: np.ndarray    # 实际成交股数
    exec_prices: np.ndarray        # 执行价格（含滑点）
    commissions: np.ndarray        # 佣金
    stamp_duties: np.ndarray       # 印花税
    slippages: np.ndarray          # 滑点金额
    rejected_mask: np.ndarray      # 拒绝标记（bool）
    t1_violation_mask: np.ndarray  # T+1违规标记
    limit_violation_mask: np.ndarray  # 涨跌停违规标记
    cash_shortfall_mask: np.ndarray   # 资金不足标记
```

### 核心方法

| 方法 | 说明 |
|------|------|
| `fill_buy(prices, shares_requested, cash_available, pre_closes, symbols, timestamps, volumes, avg_daily_volumes)` | 批量买入撮合。检查涨停限制、计算执行价格、处理资金不足时的股数调整。 |
| `fill_sell(prices, shares_requested, positions_held, position_costs, pre_closes, symbols, timestamps, buy_dates, volumes, avg_daily_volumes)` | 批量卖出撮合。检查跌停限制、T+1 约束、计算印花税。 |
| `compute_limit_status_vectorized(prices, pre_closes, symbols)` | 向量化涨跌停状态判定，返回 `is_limit_up` 和 `is_limit_down` 布尔数组。 |
| `compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy)` | 计算含滑点和冲击成本的执行价格。 |

---

## ~~PortfolioEngine 组合回测引擎~~（历史条目，已删除）

> **⚠️ 已删除**: `PortfolioEngine`（原位于 `hands.backtest.portfolio_engine`）已在早期清理轮次中物理删除。多标的组合回测现通过 `UnifiedBacktestEngine` 在外层循环 + `UnifiedMatchingEngine` 批量撮合实现。本章节保留为归档说明。
>
> 历史上的 `PortfolioEngine` 能力（`max_positions` 最大持仓限制、`batch_open_positions`/`batch_close_positions` 批量开平仓、`_pending_signals` T+1 信号延迟队列、`Position` 数据类、`calculate_metrics` 组合绩效指标）均已在删除该引擎时随测试一并移除。

---

## 策略框架

### STRATEGY_MAP 注册表

位于 `hands.strategies.registry`，定义了策略名称到函数的映射：

```python
STRATEGY_MAP = {
    "wyckoff": trade_wyckoff,
    "ma_atr": trade_ma,
    "ma_cross": trade_ma,
    "reversal": trade_str_reversal,
    "str_reversal": trade_str_reversal,
    "regime": trade_regime,
}
```

### ~~BaseStrategy 基类~~（2026-10-17 第八轮删除）

原位于 `hands.strategies.base`，以 `backtrader` 为可选依赖（未安装时退化为 Mock）。

**已剪除**：`backtrader` 既未声明于 `pyproject.toml` 的任何依赖集、也从未安装 → `HAS_BACKTRADER` 恒为 `False`，`if HAS_BACKTRADER:` 的真实分支在 CI 与开发机上**永久不可达**；生产/研究链路无消费者。连同 `fsm_strategy` / `ma_atr_strategy` / `regime_strategy` / `reversal_strategy` / `wyckoff_strategy` 一并物理删除。类式策略的功能对应物是本页的**函数式策略注册表 `STRATEGY_MAP`**。

### ~~StrategyResult 数据类~~（2026-10-17 第八轮删除）

原定义于 `hands/strategies/base.py`（`@dataclass class StrategyResult: ret/days/exit_reason/entry_price/exit_price`），随类式（backtrader）策略子集一并物理删除。函数式策略直接返回 `{"ret": float, "days": int}` 字典（见下「策略协议」）。

### 策略协议

所有注册在 `STRATEGY_MAP` 中的策略函数遵循统一签名：

```python
def trade_xxx(
    df: pd.DataFrame,
    as_of_date: str,
    cost_buy: Optional[float] = None,
    cost_sell: Optional[float] = None,
    csi: pd.DataFrame = None,
    mode: str = "backtest",
    **kwargs,
) -> Optional[Dict]
```

返回 `{"ret": float, "days": int}` 或 `None`（无交易信号）。所有策略在结果中扣除交易成本 `(cost_buy + cost_sell) * 100`。

---

## 内置策略

### MA Cross (trade_ma)

位于 `hands.strategies.ma_cross`，注册名 `"ma_cross"` / `"ma_atr"`。

- **买入条件**：5 日均线从下方上穿 20 日均线（前一期 MA5 <= MA20，当期 MA5 > MA20）。
- **卖出条件**：持仓后，5 日均线从上方下穿 20 日均线，或最长持有 120 日。
- **参数**：回看 30 根 K 线，MA 快线 5 日，MA 慢线 20 日。
- **执行**：信号日次日以开盘价入场。

### Wyckoff (trade_wyckoff)

位于 `hands.strategies.wyckoff`，注册名 `"wyckoff"`。

- **依赖**：调用 `WyckoffEngine.analyze()` 进行多时间框架 Wyckoff 分析，读取 `config/trading.yaml` 中的参数。
- **买入条件**：Wyckoff 信号类型非 `"no_signal"`，交易方向非 `"空仓观望"`，信号置信度 >= 配置的最低阈值（默认 B 级），且不在熊市状态。Spring 信号需验证距信号日已过 3 个交易日。
- **卖出逻辑**（多阶段退出）：
  - 止损：价格触及 `stop_loss`（Wyckoff 报告提供或默认 entry * 0.93）
  - 目标止盈：30 日内触及 `first_target` 或 `entry + 2*ATR`，半仓止盈
  - 追踪止损：超过 30 日后启用 `peak - atr_mult * ATR` 的追踪止损
  - 时间止损：超过 `ts_d` 天（因市场状态而异）
  - 最大持有：`mh` 天（因市场状态而异）
- **Regime 自适应**：根据 `get_regime()` 返回的市场状态（bull/bear/range/unknown）调整 ATR 倍数、时间止损天数和最大持有天数。

### Regime (trade_regime)

位于 `hands.strategies.regime`，注册名 `"regime"`。

- **买入条件**：仅在 `get_regime()` 判定为 `"bull"` 市场时交易，且至少有 5 根历史 K 线。
- **卖出条件**：固定持有 20 个交易日后以收盘价退出。
- **市场状态判定** `get_regime(csi, d)`：
  - bull: `close > MA120 * 1.02` 且 `MA60 > MA120`
  - bear: `close < MA120 * 0.98`
  - range: 其他情况

### Reversal (trade_str_reversal)

位于 `hands.strategies.str_reversal`，注册名 `"reversal"` / `"str_reversal"`。

- **买入条件**：过去 5 日累计跌幅超过 -5%（均值回归信号）。
- **卖出逻辑**：以次日开盘价入场，设置 ATR 倍数（2.0）的止盈和止损，最长持有 5 日。
- **参数**：回看 10 根 K 线判断反转信号，ATR 窗口 14 日。

### ~~FSM (FSMStrategy)~~（2026-10-17 第八轮删除）

原位于 `hands.strategies.fsm_strategy`，基于 `backtrader` 框架实现。**已随类式（backtrader）策略子集一并物理删除**（理由见「~~BaseStrategy 基类~~」）。

---

## 回测分析工具

### ~~TradeAnalyzer 交易分析器~~（2026-10-17 第八轮删除）

原位于 `hands.backtest.trade_analysis.analyzer`（连同 `trade_analysis/statistics.py` 整包）。**已剪除**：AST 核验在 `src/` + `tests/` + `scripts/` 中**零引用**（同批删除的还有 `hands.backtest.report_generator` 与 `hands.backtest.benchmark`）——其职责已由**在线的** `services/analysis/report_generator_engine.py` + `hands/results_manager.py` + `hands/reporter.py` 承接。

### BacktestResult 回测结果

位于 `hands.backtest.result`，是回测结果的核心数据类。

主要字段：`initial_capital`、`final_capital`、`total_return`、`annualized_return`、`max_drawdown`、`sharpe_ratio`、`win_rate`、`profit_factor`、`total_trades`、`winning_trades`、`losing_trades`、`avg_win`、`avg_loss`、`drawdown_metrics`、`tail_risk_metrics`、`stress_test_results`。

关键方法：
- `calculate_metrics()`：计算所有绩效指标，调用 `DrawdownAnalyzer.analyze_drawdown()` 和 `analyze_tail_risk()`。
- `run_stress_scenarios(scenario_names)`：运行压力情景测试（2015 股灾、2016 熔断、2018 熊市、2020 新冠、2024 微盘股踩踏）。
- `generate_report()`：生成文本格式的回测报告。
- `to_dict()` / `to_dataframe()`：序列化为字典或 DataFrame。

### MonteCarloSimulator Monte Carlo 模拟器

位于 `hands.backtest.monte_carlo`，提供策略统计显著性检验。

| 方法 | 说明 |
|------|------|
| `run_shuffle(returns)` | 随机排列 Monte Carlo：对收益率序列随机打乱，比较观察到的 Sharpe 与模拟分布，计算 p-value 和置信区间。 |
| `run_bootstrap(equity_curve)` | Bootstrap 重采样：对权益曲线的日收益率有放回抽样，评估最终权益的分布和置信区间。 |
| `get_confidence_intervals(simulations)` | 从模拟结果数组提取 90%/95%/99% 置信区间。 |

构造参数：`n_simulations=1000`、`confidence_level=0.95`。

### OverfittingDetector 过拟合检测器

位于 `hands.backtest.overfitting_detector`，实现 Bailey & Lopez de Prado 的过拟合检测方法。

| 方法 | 说明 |
|------|------|
| `deflated_sharpe_ratio(observed_sharpe, n_trials, num_observations, skewness, kurtosis)` | 计算 Deflated Sharpe Ratio (DSR)，对多重测试进行校正。DSR > 0 表示统计显著。 |
| `mdd_p_value(max_drawdown, n_observations)` | 最大回撤统计显著性 p-value，基于 Magdon-Ismail & Atiya (2004) 的近似方法。 |
| `num_trials_metric(n_parameters, n_configs)` | 估计有效试验次数，考虑参数数量和配置组合。 |
| `probability_of_backtest_overfitting(strategy_returns, n_partitions=10, embargo=5)` | 计算回测过拟合概率 PBO。使用 purged K-fold 交叉验证，保持时间顺序，输出 PBO 值（> 0.5 视为过拟合）。 |

辅助方法 `purged_kfold(n, k, embargo)` 实现带清洗期的时序 K-fold 分割。

### RobustnessChecker 稳健性检查器

位于 `hands.backtest.robustness_checker`，评估策略在不同条件下的稳健性。

| 方法 | 说明 |
|------|------|
| `check_market_regime_stability(strategy_returns, market_regime)` | 检查策略在不同市场状态（bull/bear/sideways）下 Sharpe 比率的一致性，输出 `stability_score`（各 regime Sharpe 标准差）。 |
| `check_parameter_sensitivity(strategy_fn, param_grid, base_params)` | 参数敏感性检查：遍历参数网格，计算每个参数的敏感性指标，识别最敏感参数。 |
| `check_subperiod_consistency(strategy_returns, n_splits=4)` | 子区间一致性：将收益率序列分为 n 段，比较各段 Sharpe 比率，计算 `consistency_ratio`（正 Sharpe 子区间占比）。 |
| `check_transaction_cost_sensitivity(strategy_returns, cost_levels)` | 交易成本敏感性：在不同成本水平下评估 Sharpe 衰减和盈亏平衡成本。 |

### SensitivityAnalyzer 敏感性分析器

位于 `hands.backtest.sensitivity_analyzer`，提供细粒度参数敏感性分析。

| 方法 | 说明 |
|------|------|
| `one_at_a_time(base_params, param_ranges, strategy_fn, metric_name)` | OAT 分析：每次改变一个参数，记录绩效变化（delta 和 delta_pct），返回 DataFrame。 |
| `tornado_plot_data(sensitivities, metric_col)` | 龙卷风图数据：汇总每个参数的影响范围（min/max/range），按影响大小排序。 |
| `correlation_analysis(param_values, metric_values)` | 参数-绩效相关性分析：计算 Pearson 和 Spearman 相关系数。 |

---

## 报告与结果管理

### ResultsManager

通过 `hands.__init__` 延迟导入自 `hands.results_manager`，负责回测结果的持久化存储和检索。

### Reporter

通过 `hands.__init__` 延迟导入自 `hands.reporter`，负责生成可视化回测报告。

`BacktestResult.generate_report()` 提供内置的文本报告生成功能，输出包含回测区间、初始/最终资金、收益指标（总收益率、年化收益率、最大回撤、Sharpe 比率）和交易统计（总交易次数、胜率、盈亏比、平均盈亏）的格式化报告。
