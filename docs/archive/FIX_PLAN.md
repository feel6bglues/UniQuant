# UniQuant 修复计划 — 核准版

> 基于 2026-06-03 代码审计。按优先级分 4 个 Phase，每个 Phase 完成后验证导入链和核心测试。

---

## Phase 0 — 速赢修复（高风险低复杂度，2-4 天）

### 0.1 修复 `data_pipeline_service.py` 的断裂方法调用

- **文件**: `src/uniquant/data/data_pipeline_service.py:20`
- **问题**: `self.adjuster.adjust(df, symbol)` → `DataAdjuster` 无 `adjust()` 方法（正确名 `apply_adjustment()`）
- **修复**: 将调用改为 `self.adjuster.apply_adjustment(symbol, df, method="qfq")`，并让 `DataPipelineService` 感知 `adjust` 参数
- **风险**: 低 — 纯修复断裂路径，不影响其他调用方
- **验证**: `python -c "from uniquant.data.data_fetcher import DataFetcher; f = DataFetcher(); f.get_price('000001.SH')"`

### 0.2 透传 `adjust` 参数到 pipeline

- **文件**:
  - `src/uniquant/data/data_fetcher.py:101-115` — `get_price()` 调用 `self.pipeline.process()` 时未传 `adjust`
  - `src/uniquant/data/data_pipeline_service.py:17-21` — `process()` 签名需加 `adjust` 参数
- **修复**: `get_price(symbol, adjust)` → 传给 `pipeline.process(df, symbol, adjust)` → `adjuster.apply_adjustment(symbol, df, method=adjust)`
- **风险**: 低 — 新增参数，默认值向下兼容
- **验证**: 同上

### 0.3 修复 `COST_BUY/COST_SELL` 常量缺失过户费

- **文件**: `src/uniquant/shared/cost_model.py:35-36`
- **问题**: `COST_BUY = COMMISSION_PCT`（缺万0.1过户费），`COST_SELL = COMMISSION_PCT + STAMP_TAX_PCT`（缺万0.1过户费）
- **修复**:
  ```python
  COST_BUY = COMMISSION_PCT + TRANSFER_FEE_PCT         # 0.0003 + 0.00001 = 0.00031
  COST_SELL = COMMISSION_PCT + STAMP_TAX_PCT + TRANSFER_FEE_PCT  # 0.0003 + 0.0005 + 0.00001 = 0.00081
  ```
- **风险**: 低 — 模块级常量仅被 `strategies/backtest.py` 直接引用；回测引擎使用的 `CostConfig` 方法已正确
- **验证**: `pytest tests/ -xvs -k cost`；`python -c "from uniquant.shared.cost_model import COST_BUY, COST_SELL; print(COST_BUY, COST_SELL)"`

### 0.4 清理重复的文件/包对

- **文件**:
  - `src/uniquant/brain/indicators.py` vs `src/uniquant/brain/indicators/`（包）
  - `src/uniquant/brain/screener.py` vs `src/uniquant/brain/screener/`（包）
  - `src/uniquant/brain/alpha_decoupler.py` vs `src/uniquant/brain/alpha_decoupler/`（包）
- **问题**: 3 对重复，造成 `from ..indicators import Indicators` 等导入歧义（如 `brain/regime/regime_detector.py:13`）
- **修复**: 保留包版本，删除同名的 `.py` 单文件。检查所有内部引用并更新导入路径
- **风险**: 中 — 需 grep 全仓确认引用点；建议逐对删除并运行导入测试
- **验证**: `python -c "from uniquant.brain.indicators import Indicators"`；再跑 `ruff check src/uniquant/`

### 0.5 消除 `shared/di_container.py` 的 DAG 违规

- **文件**: `src/uniquant/shared/di_container.py:11`
- **问题**: `from ..services.service_container import ServiceContainer` — shared 层反向依赖 services 层
- **修复**: 文件已被文档字符串标记为 DEPRECATED。移除 `from ..services...` 导入（如该模块仍在使用则改为延迟导入 + `ImportError` fallback）
- **风险**: 低 — 已标记弃用；检查是否还有代码引用此模块
- **验证**: `python -c "import uniquant.shared; print('OK')"`

### 0.6 统一 `RISK_FREE_RATE` 单数据源

- **文件**:
  - `src/uniquant/shared/risk_constants.py:1` — `RISK_FREE_RATE = 0.02`（规范）
  - `src/uniquant/risk/portfolio_optimizer.py:28` — `risk_free_rate: float = 0.03`（硬编码不一致）
  - `src/uniquant/hands/strategies/backtest.py:33` — `RISK_FREE_RATE: float = 0.02`（多余副本）
- **修复**: `portfolio_optimizer.py:28` 改为 `risk_free_rate: float = 0.02`（从 `shared.risk_constants` 导入）；`backtest.py:33` 改为 `from uniquant.shared.cost_model import RISK_FREE_RATE`
- **风险**: 低 — 值接近，0.03→0.02 对夏普比率影响有限
- **验证**: `pytest tests/ -xvs -k optimizer` 或 `portfolio`

### 0.7 修复 `price_collar.py` 集合竞价价格范围

- **文件**: `src/uniquant/shared/price_collar.py:11-12,25-26`
- **问题**: 集合竞价时 `validate_order_price()` 返回 `True`（无检查），`get_allowable_price_range()` 返回 `(0, inf)`（无限制）
- **修复**: 在集合竞价期间应用实际板块涨跌停限制（调用 `get_board_rule(symbol)` 获取 `price_collar_pct`），而非完全无限制
- **风险**: 低 — 从无限制改为有限制，更接近实盘
- **验证**: `python -c "from uniquant.shared.price_collar import get_allowable_price_range; print(get_allowable_price_range('000001.SH', 10.0, 'call_auction'))"`

---

## Phase 1 — P0 回测路径修复（核心修复，3-5 天）

### 1.1 为 `strategies/backtest.py` 添加 T+1 约束 (P0-3)

- **文件**: `src/uniquant/hands/strategies/backtest.py`
- **问题**: `process_stock()` (L231-309) 和 `run_backtest()` (L312-482) 完全不检查 T+1。`BacktestEngine._check_t1_constraint()` (engine.py:122) 已实现但不被此路径使用
- **修复选择**: 两方案选一
  - **方案 A（推荐）**: 在 `strategies/backtest.py` 中直接集成 T+1 约束，通过 `TradeCalendarManager` 计算 `next_trading_day(buy_date)`，在策略结果返回的 `days` 字段上做下限约束（确保 `sell_date >= next_trading_day(buy_date)`）
  - **方案 B**: 将整个 `run_backtest()` 迁移到 `BacktestEngine`，工作量较大
- **细节**: `TradeCalendarManager` 已可用（`data/managers/trade_calendar_manager.py`）。在 `process_stock()` 中，当策略给出卖出信号时，检查当前日期是否 >= 买入日期下一个交易日。若不满足则跳过该信号
- **风险**: 中 — 回测结果会显著变差，这是正确的行为
- **验证**: 增加单元测试验证已知 T+1 场景

### 1.2 添加卖出侧跌停检查 (P0-4)

- **文件**: `src/uniquant/hands/strategies/backtest.py:289-293`
- **问题**: `process_stock()` 仅检查买入时的涨停/跌停（L289-293），完全没有卖出时的跌停检查
- **修复**: 在策略函数（如 `ma_cross.py:32-48`）或 `process_stock()` 中，确认卖出价格时调用 `is_limit_down()`
- **细节**: 具体位置取决于各策略函数的实现模式。最安全的方案是在返回卖出信号前，由策略函数自行检查跌停。`is_limit_down()` 已导入（backtest.py:20）但未被用于卖出
- **风险**: 中 — 回测卖出会被更保守地阻止，这是正确的
- **验证**: 测试连续跌停场景的正确拒绝

### 1.3 集成过拟合检测工具到回测流程 (P0-7)

- **文件**:
  - `src/uniquant/hands/backtest/engine.py:293-399` — `run_backtest()`
  - `src/uniquant/hands/backtest/overfitting_detector.py` — `OverfittingDetector`（DSR: L41, PBO: L118）
  - `src/uniquant/hands/backtest/robustness_checker.py` — `RobustnessChecker`
  - `src/uniquant/hands/backtest/monte_carlo.py` — `MonteCarloSimulator`
- **问题**: 三个检测/验证类均完整实现但完全孤儿化，`BacktestEngine` 和 `strategies/backtest.py` 均不调用
- **修复**: 在 `BacktestResult` 中添加可选字段 `overfitting_metrics`。`run_backtest()` 末尾调用 `OverfittingDetector.deflated_sharpe_ratio()` 和 `probability_of_backtest_overfitting()`（当数据充足时）。`run_walk_forward()` 末尾调用 `RobustnessChecker.check_parameter_sensitivity()`
- **风险**: 低 — 仅增加额外统计输出，不影响回测数值
- **验证**: `pytest tests/test_backtest_advanced.py -xvs`

### 1.4 连接 `optimal_params.yaml` 到验证工具 (P0-6)

- **文件**:
  - `config/optimal_params.yaml` — 8 标的 × 13-16 参数
  - `src/uniquant/shared/optimal_params.py` — loader 从未被任何模块导入
  - `src/uniquant/hands/backtest/overfitting_detector.py` — DSR/PBO 实现
- **问题**: 最优参数被 YAML 存储但从未经过 PBO/DSR/Walk-Forward 验证
- **修复**:
  1. 构建 `OptimalParamValidator` 类，接收参数集，依次运行 Walk-Forward 回测 → PBO → DSR → 参数敏感性分析
  2. 将结果显示为报告：DSR 显著性水平、PBO 概率、参数稳定性热图
  3. 可选：将 `optimal_params.py` 的 `load_optimal_config()` 集成到 `ServiceContainer` 的初始化链中
- **风险**: 中 — 新增模块不影响现有回测
- **验证**: 对某个标的参数集运行完整验证链，输出报告

---

## Phase 2 — 数据层修复（3-5 天）

### 2.1 幸存者偏差修复 (P0-2)

- **文件**:
  - `src/uniquant/data/sources/baostock.py:312-313` — `status == "1"` 过滤
  - `src/uniquant/data/services/import_financial.py:167-169` — 相同过滤
  - `src/uniquant/data/all_stock_codes.csv` — 0/7579 条退市股票
  - `src/uniquant/data/stock_list.csv` — 无 status 列
- **问题**: 退市股票在数据源层即被过滤，进入回测宇宙的全是幸存者
- **修复**:
  1. 在 `baostock.py` 中增加可选参数 `include_delisted=False`，默认向后兼容。回测专用的数据加载路径使用 `include_delisted=True`
  2. 在 `stock_list.csv` 中添加 `status` 列
  3. 在 `backtest.py:process_stock()` 中将退市标签（当前 L295-301 仅做 heuristic 标记）升级为真正的风险调整：退市股票的最后 N 天交易标记为 -100% 损失
- **风险**: 高 — 改变数据源返回内容可能影响下游；需逐步推进
- **验证**: 对比修复前后同一策略的回测结果，确认退市股票被纳入

### 2.2 修复 `financial_bridge.py` 的公告日期前视偏差 (P1-1)

- **文件**: `src/uniquant/brain/factors/financial_bridge.py:178-188`
- **问题**: `_get_effective_date_col()` 在没有公告日期列时返回 `"report_date"`（会计期间结束日），导致 1-4 个月的前视偏差；即使在有公告日期列时，L183 的 `.fillna(financial_df["report_date"])` 也造成相同问题
- **修复**:
  1. 当没有公告日期列时，将有效日期设置为 `report_date + offset`（按财报类型分别设置 1-4 个月延迟）：一季报+1m、半年报+2m、三季报+2m、年报+4m
  2. 公告日期列存在时，对缺失值使用上述偏移而非直接回退到 `report_date`
- **风险**: 中 — 影响 PE_TTM/PB 计算的时间对齐
- **验证**: 对比修复前后同一股票 2024 年的 PE_TTM 序列差异

### 2.3 向量化 `BacktestEngine.run_backtest()` (P0-5)

- **文件**: `src/uniquant/hands/backtest/engine.py:335-336`
- **问题**: `for idx in range(len(df)):` + `row = df.iloc[idx]` — 纯 Python 逐行遍历
- **修复**:
  1. 将 OHLCV 数据提取为 NumPy 数组（`dates = df["date"].values`, `opens = df["open"].values`, 等）
  2. 使用 `np.where` / 布尔索引替代逐行 if/else
  3. 信号生成仍保留逐行回调（策略逻辑难以向量化），但用 `.iat` 替代 `.iloc`
- **复杂度**: `run_backtest()` 核心逻辑在 L314-399。建议先做最小改动：将 `df.iloc[idx]` 替换为 `(opens[idx], highs[idx], lows[idx], closes[idx], volumes[idx])` 的 tuple 解构，显著减少 DataFrame 行访问开销
- **风险**: 中 — 核心回测逻辑改动需仔细测试确保结果一致
- **验证**: 对同一数据+策略运行修复前后，比对净值曲线完全一致

---

## Phase 3 — 工程完备性修复（2-3 天）

### 3.1 添加 `max_single_sector_pct` 执行 (P1-2)

- **文件**: `config/trading.yaml:41` 定义值；`src/uniquant/risk/` 或 `src/uniquant/hands/backtest/portfolio_engine.py` 执行
- **修复**: 在 `PortfolioEngine` 或 `PortfolioSizer.allocate()` 中添加行业集中度检查。从 YAML 读取 `max_single_sector_pct`，使用 `industry_provider.py` 获取股票行业分类，确保单行业暴露不超过限制
- **风险**: 低
- **验证**: 单元测试行业超限场景

### 3.2 为 `UnifiedMatchingEngine.fill_sell` 添加日期感知印花税 (P1-5)

- **文件**: `src/uniquant/hands/backtest/unified_matching_engine.py:37,190`
- **问题**: L37 `stamp_duty_rate: float = 0.0005` 固定值，L190 `stamp_duties = values * self.stamp_duty_rate` 永不切换
- **修复**: 使用 `cost_model.get_stamp_tax_pct(trade_date)` 替代固定常量。需要将 `timestamps` 参数传入印花税计算位置（L190 处已可获取 `timestamps` 参数）
- **风险**: 低 — 仅影响跨 2023-08-28 的回测
- **验证**: 对跨越 2023-08-28 的回测验证成本归因

### 3.3 为 `PositionSizer` 添加 Kelly Criterion 选项 (P1-3)

- **文件**: `src/uniquant/risk/sizer.py:77-79`
- **问题**: `risk_pct: float = 0.05` 固定分数，无基于胜率/赔率的凯利公式
- **修复**: 添加 `calculate_kelly(win_rate, avg_win, avg_loss)` 静态方法，提供 `kelly_fraction` 参数选项（使用 half-Kelly 作为保守默认）
- **风险**: 低 — 新增选项，不改变默认行为
- **验证**: `pytest tests/ -xvs -k sizer`

### 3.4 为 `PortfolioOptimizer` 添加协方差收缩 (P1-4)

- **文件**: `src/uniquant/risk/portfolio_optimizer.py:67`
- **问题**: `returns.cov().values` 原始样本协方差，高维低样本场景不稳定
- **修复**: 添加 `_shrink_covariance(returns)` 方法实现 Ledoit-Wolf 收缩（使用 `sklearn.covariance.LedoitWolf` 或纯 NumPy 实现），在 `_validate_inputs()` 中调用
- **风险**: 低 — 仅影响协方差估计精度
- **验证**: 对比收缩前后的特征值分布

### 3.5 统一两套 Regime 检测器 (P1-7)

- **文件**:
  - `src/uniquant/brain/regime/regime_detector.py` — 4 种流动性状态
  - `src/uniquant/brain/lppl/regime.py` — 5 种趋势状态
- **问题**: 两套完全不同的状态空间，输出不可互操作
- **修复**: 加适配层或统一枚举。推荐在 `shared/` 定义 `RegimeType` 枚举覆盖两套状态，两个检测器都返回 `RegimeType`。当前使用者各自继续使用各自的内部表示
- **风险**: 中 — 涉及多个消费方需同步更新
- **验证**: `from uniquant.shared.interfaces import RegimeType`

### 3.6 修复收盘集合竞价的沪深差异 (P1-13)

- **文件**: `src/uniquant/shared/constants/market.py:349-389`
- **问题**: `is_call_auction()` 统一使用 14:57-15:00 作为收盘集合竞价时段。深交所正确，上交所收盘集合竞价在 15:00（最后 3 分钟不接受报单）
- **修复**: 为 `is_call_auction()` 添加 `exchange` 参数（或使用 `symbol` 推导交易所）。上交所收盘集合竞价逻辑不同
- **风险**: 低
- **验证**: 分别测试 SH/SZ 标的的集合竞价时段判定

### 3.7 修复 15 处静默异常吞没 (P1-10)

- **文件**: 见审计报告 P1-10 清单（约 15 处真正静默的 `except Exception: pass`）
- **修复**: 对每处添加 `logger.warning(...)`，至少输出异常类型和消息
- **风险**: 低 — 新增日志不改变逻辑
- **验证**: `ruff check src/uniquant/ --select E722`

### 3.8 替换 20 处 `iterrows()` (P1-9)

- **文件**: 20 处分布见审计报告
- **修复**: 用 `itertuples()`（快 ~10×）、`apply()`、或纯向量化替代。非热路径可降级为 `itertuples()` 以最小改动
- **风险**: 低到中 — 需逐个确认非向量化不影响逻辑
- **验证**: 逐文件对比替换前后的输出 DataFrame 一致性

---

## Phase 4 — 验证与回归

### 4.1 导入链验证

```bash
python -c "import uniquant; import uniquant.shared; print('import OK')"
python -c "from uniquant.shared.cost_model import COST_BUY, COST_SELL, TRANSFER_FEE_PCT; print(COST_BUY, COST_SELL)"
python -c "from uniquant.hands.backtest.engine import BacktestEngine; print('engine OK')"
python -c "from uniquant.hands.backtest.overfitting_detector import OverfittingDetector; print('detector OK')"
```

### 4.2 核心测试

```bash
pytest tests/test_engine_factory.py -xvs
pytest tests/test_backtest_advanced.py -xvs
```

### 4.3 Lint

```bash
ruff check src/uniquant/
```

### 4.4 回归验证清单

| 检查项 | 命令 |
|--------|------|
| 模块加载 | `python -c "import uniquant"` |
| 配置加载 | `python -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"` |
| 成本模型 | `python -c "from uniquant.shared.cost_model import calculate_sharpe_ratio, get_stamp_tax_pct; print(get_stamp_tax_pct(__import__('datetime').date(2023,1,1)), get_stamp_tax_pct(__import__('datetime').date(2024,1,1)))"` |
| 涨跌停 | `python -c "from uniquant.shared.limit_checker import check_limit_status; print(check_limit_status(11.0, 10.0, '000001', 'Test'))"` |
| 回测引擎 | `python -c "from uniquant.hands.backtest.engine import BacktestEngine; e = BacktestEngine(); print('OK')"` |

---

## 依赖顺序

```
Phase 0 (速赢) ──────────────→ Phase 1 (回测核心) ──────→ Phase 2 (数据层) ──────→ Phase 3 (完备性) ──────→ Phase 4 (验证)
       │                              │                          │
       ├── 0.1 pipeline 断裂         ├── 1.1 T+1 约束           ├── 2.1 幸存者偏差
       ├── 0.2 adjust 透传           ├── 1.2 卖出跌停检查       ├── 2.2 financial_bridge
       ├── 0.3 COST 常量             ├── 1.3 过拟合集成         └── 2.3 向量化
       ├── 0.4 重复文件清理          └── 1.4 optimal_params
       ├── 0.5 DAG 违规
       ├── 0.6 RISK_FREE_RATE
       └── 0.7 price_collar
```

Phase 0 和 Phase 1 可部分并行（0.3/0.6 与 1.1/1.2 独立）。
Phase 2 依赖于 Phase 1 完成。
Phase 3 与 Phase 2 可并行。
