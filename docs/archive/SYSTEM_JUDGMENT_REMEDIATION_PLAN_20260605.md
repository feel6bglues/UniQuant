# UniQuant 系统审判整改计划

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

生成日期: 2026-06-05  
依据文档: `docs/SYSTEM_JUDGMENT_REPORT_20260605.md`  
核验基准: 当前源码实际状态，重点核验 `hands/backtest`、`brain/factors`、`data/pipeline`、`shared/limit_checker`。

## 0. 核验结论摘要

`SYSTEM_JUDGMENT_REPORT_20260605.md` 的核心风险方向成立，但测试统计和部分 A 股规则描述需要修正后再进入整改执行。

已由源码核验成立的问题:

- `PortfolioEngine` 买卖现金流漏扣过户费。
- `FillResult` 不返回 `transfer_fees`，导致统一撮合层计算出的过户费无法传递给组合引擎。
- `UnifiedMatchingEngine.fill_buy()` 涨停拒单时 `rejected_mask=True`，但 `executed_shares` 未强制归零。
- `FactorAnalyzer.compute_ic_ir()` 只接受 `AnalysisMode`，测试和潜在调用方传字符串会触发 `TypeError`。
- `PortfolioEngine.run()` 主循环使用 `iterrows()`。
- `PortfolioEngine.run()` 末尾会用最后一个日期撮合 pending 信号，存在最后一日同日成交。
- `PortfolioEngine` 传入撮合层的 `volumes` 来自市场成交量 `volume_data`，不是订单量，组合回测冲击成本口径错误。
- `DataAdjuster.get_adjusted_data(start_date, end_date, adjust)` 读取全量 raw 后未按起止日期裁剪，qfq 的 `latest_factor` 可能使用全量最后一日因子。
- `UnifiedMatchingEngine.compute_limit_status_vectorized()` 未接入 `name` 或 `trading_days_listed`，因此 ST 和 IPO 特殊规则在统一撮合层不完整。

需要修正报告描述的问题:

- `test_matching_engine.py` 在普通 `pytest` 下因 `from src...` 可能导入失败；加 `PYTHONPATH=.` 后当前通过。
- `test_limit_checker.py` 当前为 30 passed，不是报告中的 23 passed。
- `test_portfolio_engine_v2.py` 当前为 15 passed，不是报告中的 19 passed。
- `limit_checker.check_limit_status()` 已支持主板 IPO 首日和科创/创业 IPO 前 5 日规则，但统一撮合层未接入。
- 退市机制不是完全缺失，`StockMetadataManager` 与 `DataAligner` 已有部分支持；风险在默认研究路径倾向排除退市样本。

## 1. 整改原则

1. 先修资金曲线污染，再修研究结论污染，再修性能和覆盖率。
2. 统一撮合层是唯一真实成交语义入口，组合引擎不得绕过其成本字段。
3. 所有拒单结果必须满足 `rejected_mask=True => executed_shares=0`。
4. 所有点时数据必须满足 `feature_time <= decision_time < execution_time`。
5. 所有计划项必须有源码位置、测试用例和验收标准。

## 2. P0 整改项

### P0-1 修复组合回测过户费漏扣

源码依据:

- `src/uniquant/hands/backtest/unified_matching_engine.py`
  - `FillResult` 当前字段缺少 `transfer_fees`。
  - `fill_buy()` 已计算 `transfer_fees`，但未返回。
  - `fill_sell()` 已计算 `transfer_fees`，但未返回。
- `src/uniquant/hands/backtest/portfolio_engine.py`
  - `batch_open_positions()` 现金扣减只使用 `成交额 + commissions`。
  - `batch_close_positions()` 现金增加只使用 `成交额 - commissions - stamp_duties`。

修复方案:

1. 给 `FillResult` 增加字段:

```python
transfer_fees: np.ndarray
```

2. `fill_buy()` 返回 `transfer_fees=transfer_fees`。
3. `fill_sell()` 返回 `transfer_fees=transfer_fees`。
4. `PortfolioEngine.batch_open_positions()` 改为:

```python
cost = float(
    fill.exec_prices[i] * fill.executed_shares[i]
    + fill.commissions[i]
    + fill.transfer_fees[i]
)
```

5. `PortfolioEngine.batch_close_positions()` 改为:

```python
net_value = float(
    fill.exec_prices[i] * fill.executed_shares[i]
    - fill.commissions[i]
    - fill.stamp_duties[i]
    - fill.transfer_fees[i]
)
```

测试计划:

- 更新 `tests/test_matching_engine.py`，断言 `FillResult` 有 `transfer_fees` 且买卖两侧均为正。
- 更新 `tests/test_portfolio_engine_v2.py` 的 mock `FillResult`，增加 `transfer_fees`。
- 新增组合现金流精确测试:
  - 买入后现金等于 `initial - value - commission - transfer_fee`。
  - 卖出后现金等于 `cash_before + value - commission - stamp_duty - transfer_fee`。

验收命令:

```bash
PYTHONPATH=. pytest tests/test_matching_engine.py tests/test_portfolio_engine_v2.py -q
```

验收标准:

- 所有测试通过。
- 任意买卖成交记录可追溯佣金、印花税、过户费、滑点。

### P0-2 修复最后一日 pending 信号同日成交

源码依据:

- `PortfolioEngine.run()` 日内循环中，当日信号先进入 `_pending_signals`。
- 循环结束后，当前实现用 `last_date` 对剩余 pending 信号再次撮合，导致最后一日信号同日成交。

修复方案:

1. 删除循环结束后的最后一日强制撮合逻辑，或改为显式配置项:

```python
execute_final_pending: bool = False
```

默认必须为 `False`。

2. 如果业务确实需要结尾强平，必须建模为独立的清算模式，不得复用普通信号撮合路径。

测试计划:

- 新增 `test_portfolio_engine_does_not_execute_last_day_signal()`:
  - 最后一日出现买入信号。
  - 回测结束后不得创建仓位。
  - `_pending_signals` 可清空，但必须记录 dropped/expired 计数或 metadata。

验收命令:

```bash
pytest tests/test_portfolio_engine_v2.py -q
```

验收标准:

- 最后一日信号不产生同日成交。
- 既有“上一日信号下一日成交”逻辑保持不变。

### P0-3 修复组合冲击成本口径

源码依据:

- `UnifiedMatchingEngine.compute_execution_prices()` 以 `volumes / avg_daily_volumes` 计算冲击成本。
- `PortfolioEngine.run()` 当前传入的 `volumes` 来自 `volume_data.loc[date, sym]`，这是市场成交量，不是订单量。

修复方案:

1. 在 `PortfolioEngine.batch_open_positions()` 中用订单股数 `sh_arr` 作为 `order_volumes` 传给 `fill_buy()`。
2. 在 `PortfolioEngine.batch_close_positions()` 中用 `pos_arr` 或实际卖出请求数量作为 `order_volumes` 传给 `fill_sell()`。
3. 保留市场成交量/ADV 数据仅用于容量检查和 ADV 分母，不再作为订单量。
4. 将参数命名澄清:

```python
order_volumes: np.ndarray
avg_daily_volumes: np.ndarray
```

测试计划:

- 构造 `shares_per_trade=100`、`volume_data=1_000_000`、`ADV=1_000_000`。
- 断言冲击成本使用 `100 / 1_000_000`，不是 `1_000_000 / 1_000_000`。

验收命令:

```bash
PYTHONPATH=. pytest tests/test_matching_engine.py tests/test_portfolio_engine_v2.py -q
```

验收标准:

- 组合回测冲击成本由订单量决定。
- 大市成交量不能人为放大单个订单冲击成本。

## 3. P1 整改项

### P1-1 修复 `fill_buy()` 拒单成交语义

源码依据:

- `UnifiedMatchingEngine.fill_buy()` 当前返回 `executed_shares=shares_adj`。
- `rejected_mask=limit_rejected | (shares_adj <= 0)`。
- 当涨停拒单且现金充足时，`executed_shares` 仍可非零。

修复方案:

在重算费用前先归零拒单数量:

```python
shares_adj = np.where(limit_rejected, 0, shares_adj)
```

测试计划:

- 更新 `test_limit_up_rejection()`:

```python
assert fill.executed_shares[0] == 0
```

验收命令:

```bash
PYTHONPATH=. pytest tests/test_matching_engine.py -q
```

验收标准:

- `rejected_mask=True` 的买单零成交。
- 卖单已有同等语义，保持不变。

### P1-2 修复 `FactorAnalyzer.compute_ic_ir()` mode API

源码依据:

- `compute_ic_ir()` 签名标注 `mode: AnalysisMode`。
- 测试和常见调用传入 `"backtest"` / `"live"`。
- 当前字符串 mode 在类型检查处抛 `TypeError`。

修复方案:

1. 接受字符串并转换:

```python
if isinstance(mode, str):
    mode = AnalysisMode.from_config(mode)
elif not isinstance(mode, AnalysisMode):
    raise TypeError(...)
```

2. 类型标注改为:

```python
mode: AnalysisMode | str = AnalysisMode.BACKTEST
```

测试计划:

- 保留当前 `tests/test_lookahead_bias.py`。
- 增加非法字符串测试，如 `mode="prod"` 必须 `ValueError`。

验收命令:

```bash
pytest tests/test_lookahead_bias.py tests/test_factor_analyzer.py -q
```

验收标准:

- `mode="live"` 抛 `ValueError`，不是 `TypeError`。
- `mode="backtest"` 正常返回 IC/IR。

### P1-3 修复 qfq 截止日期和 `get_adjusted_data()` 裁剪

源码依据:

- `DataAdjuster.apply_adjustment()` 使用 `latest_factor = df_merged["factor"].iloc[-1]`。
- `get_adjusted_data(start_date, end_date, adjust)` 读取全量 raw 后未按 `start_date/end_date` 裁剪。

修复方案:

1. `get_adjusted_data()` 读取 raw 后立即按日期裁剪:

```python
df_raw["date"] = pd.to_datetime(df_raw["date"])
df_raw = df_raw[
    (df_raw["date"] >= pd.Timestamp(start_date))
    & (df_raw["date"] <= pd.Timestamp(end_date))
].copy()
```

2. `apply_adjustment()` 增加 `cutoff_date` 参数:

```python
def apply_adjustment(..., cutoff_date: str | pd.Timestamp | None = None) -> pd.DataFrame:
```

3. qfq 计算 `latest_factor` 前按 `cutoff_date` 或 `df_raw["date"].max()` 截断。

测试计划:

- 构造 raw 到 2024-01-10，factor 到 2024-02-01。
- 调 `get_adjusted_data(..., end_date="2024-01-10", adjust="qfq")`。
- 断言 qfq 不使用 2024-02-01 的 factor。

验收命令:

```bash
pytest tests/test_data_chaos_qa.py tests/test_field_mapping.py -q
```

建议新增:

```bash
pytest tests/test_data_adjuster_point_in_time.py -q
```

验收标准:

- 截断样本 qfq 与未来除权事件无关。
- 返回数据严格在 `start_date/end_date` 范围内。

### P1-4 统一撮合层接入 ST 和 IPO 元数据

源码依据:

- `limit_checker.check_limit_status()` 支持 `name` 和 `trading_days_listed`。
- `UnifiedMatchingEngine.compute_limit_status_vectorized()` 只接收 `symbols`，无法识别历史 ST 名称和 IPO 交易日数。

修复方案:

1. `compute_limit_status_vectorized()` 增加可选参数:

```python
names: np.ndarray | None = None
trading_days_listed: np.ndarray | None = None
```

2. 对少量板块规则可保留向量化；对 ST/IPO 特例用预计算数组或最小 Python 循环。
3. `fill_buy()` / `fill_sell()` 参数透传 `names` 和 `trading_days_listed`。
4. `PortfolioEngine` 从元数据或输入 price panel 中读取历史 `name`/`is_st`/`trading_days_listed`。

测试计划:

- ST 股票名 `*STxxx`，pre_close=10，price=10.5 应判涨停。
- 主板 IPO 首日 pre_close=10，price=11 不应按普通 10% 涨停拒单，应按 +44% 规则允许。
- 科创/创业 IPO 前 5 日不应用 20% 限制。

验收命令:

```bash
pytest tests/test_limit_checker.py -q
PYTHONPATH=. pytest tests/test_matching_engine.py -q
```

验收标准:

- 基础 `limit_checker` 和统一撮合层规则一致。
- 未提供 ST/IPO 元数据时必须保守记录 warning 或 metadata，不得静默假设主板普通股。

### P1-5 幸存者偏差默认路径整改

源码依据:

- `StockMetadataManager` 已支持 `delist_date`、`is_delisted(as_of)`、`get_active_stocks(as_of)`。
- `DataAligner` 已按 IPO/退市日期对齐。
- 但 `BaoStockSource.fetch_stock_list()` 默认 `include_delisted=False`。
- `ScanConfig.exclude_delisted` 默认 `True`。

修复方案:

1. 区分 live 与 research/backtest 股票池:
   - live 默认排除退市。
   - historical backtest 默认必须包含历史曾可交易股票。
2. 在扫描和回测配置中显式增加:

```python
universe_mode: Literal["live_active", "historical_point_in_time"]
```

3. 历史回测按 `as_of` 生成股票池，不得用当前活跃列表回填历史。
4. 报告中所有因子 IC 和回测结果必须记录 universe 配置。

测试计划:

- 构造一只 2020 退市股票。
- 2019 as_of 应进入股票池，2021 as_of 不进入。
- live 模式不包含退市，historical 模式在退市前包含。

验收标准:

- 历史股票池点时一致。
- 默认研究配置不再静默排除退市样本。

## 4. P2 改善项

### P2-1 消除组合主路径 `iterrows()`

源码依据:

- `PortfolioEngine.run()` 对每日信号使用 `day_signals.iterrows()`。

修复方案:

1. 用列裁剪 + boolean mask + NumPy arrays 替代逐行 Series。
2. 先做最小替换:

```python
active = day_signals.loc[day_signals[signal_column] != 0, [symbol_column, signal_column]]
for sym, sig in active.itertuples(index=False, name=None):
    ...
```

3. 后续优化为按日期预分组:

```python
for date, day_signals in signals.groupby(date_column, sort=True):
    ...
```

4. 大规模版本应直接使用 ndarray/records，避免每日 DataFrame 切片。

测试计划:

- 现有组合测试保持通过。
- 新增性能 smoke test: 1000 symbols x 250 dates 不超过约定阈值。

验收标准:

- 主路径无 `iterrows()`。
- 性能测试记录在 CI 或 nightly。

### P2-2 测试导入路径规范化

源码依据:

- `tests/test_matching_engine.py` 使用 `from src.uniquant...`。
- 普通 `pytest tests/test_matching_engine.py` 可能失败。

修复方案:

统一测试导入为:

```python
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine, FillResult
```

验收命令:

```bash
pytest tests/test_matching_engine.py -q
```

验收标准:

- 不依赖 `PYTHONPATH=.` 的 `src` namespace hack。

### P2-3 报告测试表重跑与修订

源码依据:

- 当前报告测试统计与实际不一致。

修复方案:

1. 修复 P0/P1 后重跑以下命令:

```bash
pytest tests/test_lookahead_bias.py -q
pytest tests/test_limit_checker.py -q
pytest tests/test_portfolio_engine_v2.py -q
pytest tests/test_matching_engine.py tests/test_t1_constraint_boundary.py -q
pytest tests/test_data_chaos_qa.py tests/test_engine_factory.py -q
```

2. 将真实测试结果回写 `SYSTEM_JUDGMENT_REPORT_20260605.md`。

验收标准:

- 报告中的测试数量、失败原因、环境前提与命令输出一致。

## 5. 执行顺序

建议按以下顺序执行，避免 API 字段变更造成测试大量连锁失败:

1. P2-2 修正测试导入路径。
2. P0-1 增加 `transfer_fees` 字段并修复组合现金流。
3. P1-1 修复 `fill_buy()` 拒单零成交。
4. P0-3 修复组合冲击成本订单量口径。
5. P0-2 修复最后一日 pending 同日成交。
6. P1-2 修复 `FactorAnalyzer` mode 字符串兼容。
7. P1-3 修复复权 cutoff 和日期裁剪。
8. P1-4 接入 ST/IPO 元数据到统一撮合层。
9. P1-5 修复历史股票池默认幸存者偏差。
10. P2-1 消除组合主路径 `iterrows()`。
11. P2-3 重跑测试并修订审判报告。

## 6. 最小验收门槛

完成 P0/P1 后，至少必须通过:

```bash
pytest tests/test_lookahead_bias.py -q
pytest tests/test_limit_checker.py -q
pytest tests/test_portfolio_engine_v2.py -q
pytest tests/test_matching_engine.py tests/test_t1_constraint_boundary.py -q
```

并新增或更新测试覆盖:

- 组合引擎买卖过户费现金流。
- 涨停买入 `executed_shares == 0`。
- 组合引擎最后一日信号不成交。
- 组合冲击成本使用订单量。
- qfq 不使用 cutoff 之后的复权因子。
- ST 和 IPO 规则进入统一撮合层。
- 历史股票池包含退市前样本。

## 7. 风险提示

- `FillResult` 增加字段会影响所有测试 mock，必须同步更新。
- 复权裁剪会改变历史回测结果，这是预期变化；旧结果如果更优，优先视为被未来因子污染。
- ST/IPO 元数据接入后，未提供 name/listed-days 的调用方需要明确降级策略。
- 移除最后一日 pending 撮合后，部分短样本测试的成交数量会下降，这是修正 look-ahead 的正常后果。
- 幸存者偏差修复会降低历史收益指标，尤其影响小盘、壳价值、困境反转类策略。
