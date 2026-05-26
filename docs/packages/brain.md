# brain -- 信号生成引擎

> **状态:** ⚠️ 部分可用 | **当前文件:** 5/30+ | **可用子包:** czsc, fsm, lppl (部分)

brain 包是 UniQuant 的分析决策核心，约 12K LOC，包含 10 个子包：

| 子包 | 职责 |
|------|------|
| `czsc` | 缠中说禅技术分析 |
| `fsm` | 有限状态机 + 总控决策 |
| `lppl` | LPPL 泡沫检测 |
| `wyckoff` | 威科夫量价分析 |
| `ntf` | 国家队因子（大单脉冲检测） |
| `regime` | 市场流动性状态检测 |
| `alpha_decoupler` | 基准路由与超额收益解耦 |
| `factors` | 因子注册/分析/合成/Walk-Forward |
| `indicators` | 通用技术指标库 |
| `screener` | 全市场扫描器 |

公开导出（`__init__.py`）：

```python
from .czsc import CZSCEngine, CZSCSignalType, CZSCAnalysisError
from .ntf import NTFEngine
from .fsm import FSM, FSMState
from .regime import RegimeDetector, Regime, RegimeDetectionError
from .indicators import Indicators, IndicatorError
from .screener import StockScreener, ScreenerConfig
from .alpha_decoupler import AlphaDecoupler
from . import factors
from . import lppl
```

---

## CZSC 缠中说禅引擎

### 核心类

**`CZSCEngine`** -- 缠论分析引擎，封装 `czsc` 第三方库，提供增量更新和批量分析两种模式。

### 信号类型

**`CZSCSignalType`** 枚举定义六种买卖信号：

| 枚举值 | 中文 | 英文映射 |
|--------|------|----------|
| `FIRST_BUY` | 一买 | `1st_BUY` |
| `FIRST_SELL` | 一卖 | `1st_SELL` |
| `SECOND_BUY` | 二买 | `2nd_BUY` |
| `SECOND_SELL` | 二卖 | `2nd_SELL` |
| `THIRD_BUY` | 三买 | `3rd_BUY` |
| `THIRD_SELL` | 三卖 | `3rd_SELL` |
| `UNKNOWN` | 未知 | -- |

`CZSCSignalType.from_signal_value(value)` 可从信号字符串自动解析为枚举类型，同时支持中文和英文格式。

### 主要方法

#### `update_and_get_signals(df_latest_row: pd.Series) -> Dict[str, Any]`

增量更新模式。每次传入最新一行 K 线数据，内部维护 `CZSC` 分析器实例。

- **输入**: `pd.Series`，必须包含 `date, open, close, high, low` 以及 `volume` 或 `vol` 列。
- **输出**: `{"is_3rd_buy": bool, "bi_count": int, "error": str | None}`

#### `get_czsc_signals(df: pd.DataFrame) -> Dict[str, Any]`

批量分析模式。传入完整 DataFrame，一次性构建分析器。

- **输入**: `pd.DataFrame`，最少需要 `DataValidationConstants.MIN_DATA_POINTS` 行，必须包含 `date, open, close, high, low, volume` 列。
- **输出**: 完整分析结果字典，包含以下关键字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `bi_count` | int | 笔的数量 |
| `last_bi_direction` | int | 最后一笔方向（1向上，-1向下） |
| `is_3rd_buy` | bool | 是否为第三类买点 |
| `czsc_signal` | str | `"3rd_BUY"` 或 `"NONE"` |
| `bottom_fractal` | float | 底部分形价格 |
| `czsc_bottom_price` | float | 缠论底部价格 |
| `signals` | Dict | 原始信号字典 |
| `geometry_desc` | str | 几何结构描述 |
| `analysis_coverage` | float | 分析覆盖率 |

### 内部优化

- `_prepare_bar_list()` 使用向量化掩码（`nan_mask & positive_mask & logic_mask`）批量过滤无效 K 线，避免逐行验证。
- 当 `HAS_CZSC_SIGNALS` 为 True 时，优先调用 `czsc.signals.cxt_third_buy_V230228()` 函数检测三买信号。

### 配置

- `MIN_DATA_POINTS`: 从 `DataValidationConstants.MIN_DATA_POINTS` 读取。
- `REQUIRED_COLUMNS`: `{"date", "open", "close", "high", "low"}`。
- `VOLUME_COLUMNS`: 兼容 `"volume"` 和 `"vol"` 两种列名。

---

## FSM 有限状态机

### 状态定义

**`FSMState`** 枚举定义 7 种状态：

| 状态 | 含义 |
|------|------|
| `IDLE` | 横盘或下行趋势，无明确买入信号 |
| `SIGNAL` | 股价突破 MA60，发出买入信号 |
| `PROBE` | 股价突破 MA60 后缩量回踩 MA20 且未跌破 |
| `MONITOR` | 明确上升趋势，MA20 > MA60，适合持有 |
| `PYRAMID` | 持续上涨，可考虑加仓 |
| `EXIT` | 跌破关键均线，应考虑平仓 |
| `CIRCUIT_BREAK` | 极端波动，触发熔断机制 |

### 合法状态转换

```
IDLE       -> SIGNAL, PROBE
SIGNAL     -> PROBE, IDLE
PROBE      -> MONITOR, IDLE, EXIT
MONITOR    -> PYRAMID, EXIT, IDLE
PYRAMID    -> MONITOR, EXIT
EXIT       -> IDLE
CIRCUIT_BREAK -> IDLE
```

### FSM 类

**`FSM`** -- 状态推断模块，根据均线关系判断当前市场状态。

```python
FSM(ma_short=20, ma_long=60, is_intraday=False)
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ma_short` | `IndicatorThresholds.FSM_MA_SHORT` (20) | 短期均线周期 |
| `ma_long` | `IndicatorThresholds.FSM_MA_LONG` (60) | 长期均线周期 |
| `is_intraday` | `False` | 盘中模式（排除当日未确定 K 线，避免前视偏差） |

#### `infer_state(df: pd.DataFrame) -> Dict[str, Any]`

推断当前市场状态。

- **输入**: DataFrame，必须包含 `close, high, low, open` 列。
- **输出**: 包含 `state`（FSMState 枚举）、`state_name`、`state_desc`、`transition_reason`、`ma_status`、`fsm_state` 的字典。

盘中模式与盘后模式的区别：盘中模式使用 `df.iloc[:-1]` 计算均线（排除当前未确定 K 线），用当前实时价格做比较；盘后模式使用全部数据。

### DecisionBrain 类

**`DecisionBrain`** -- 总控执行模块，采用"Veto-Scoring"（否决-加权）架构，整合各引擎信号做出最终买卖决策。

```python
DecisionBrain(
    evt_risk=None,          # RiskAssessmentProtocol 实例
    sizer=None,             # PositionSizerProtocol 实例
    persist_state=True,     # 是否持久化状态到磁盘
    state_file=None,        # 自定义状态文件路径
)
```

#### `make_decision(data_packet: Union[dict, MarketSignalContext]) -> Dict[str, Any]`

核心决策方法，执行流程：

1. **否决检查** (`_check_veto_conditions`): FROZEN 市场强制等待，Danger 风险强制退出。
2. **综合评分** (`_calculate_score`): 缠论三买 +30、趋势 MA20>MA60 +20、Alpha >阈值 +15、NTF 支撑 +10。
3. **卖出检查** (`_check_sell_conditions`): LPPL 危险、均线反转、Alpha 弱、Regime 风险。
4. **状态转换** (`_determine_target_state`): 根据得分阈值决定目标状态。
5. **买入阻断** (`_check_buy_blockers`): LPPL 危险、市场冻结、Alpha 过弱、涨跌停。
6. **执行买入** (`_execute_buy`): 结合 EVT 风险和仓位计算器。

状态持久化：使用 `FileLock` + JSON 文件，支持程序重启后恢复状态。状态文件路径为 `{ROOT_DIR}/data/state/fsm_state.json`。

---

## LPPL 泡沫检测

LPPL 子包（`brain.lppl`）包含多个模块：

| 模块 | 职责 |
|------|------|
| `engine.py` | LPPLEngine + 拟合/扫描/峰值分析/集成函数 |
| `calculator.py` | LPPLCalculator -- 核心拟合逻辑 |
| `core.py` | Numba 加速算子（`cost_function`, `lppl_func`） |
| `cluster.py` | 崩溃时间聚类 |
| `computation.py` | 计算辅助 |
| `data_manager.py` | LPPL 数据管理 |
| `multifit.py` | 多窗口拟合 |
| `regime.py` | 泡沫状态检测 |
| `visualizer.py` | 可视化 |

### LPPLEngine 类

**`LPPLEngine`** -- LPPL 分析引擎入口。

```python
engine = LPPLEngine()
```

#### 主要方法

| 方法 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `scan_all_windows(df)` | DataFrame | `List[Dict]` | 并行扫描所有窗口（`LPPLConstants.WINDOWS_ALL`） |
| `detect_bubble(df, column="close")` | DataFrame | Dict | 单窗口泡沫检测 |
| `detect_bubble_confidence(df, column="close")` | DataFrame | Dict | 多窗口投票，返回置信度 |
| `calculate_tc_days(df, column="close")` | DataFrame | float | 距临界点天数 |
| `calc_structural_risk_matrix(indices_data)` | `Dict[str, DataFrame]` | Dict | 多指数结构性风险矩阵 |

`detect_bubble_confidence` 使用 `LPPLConstants.WINDOWS_LIST` 中的多个窗口分别拟合，统计 Danger 投票比例：
- `confidence >= CONFIDENCE_THRESHOLD` -> `"Danger"`
- `confidence > CONFIDENCE_WARNING` -> `"Warning"`
- 否则 -> `"Safe"`

### LPPLCalculator 类

**`LPPLCalculator`** -- 核心 LPPL 模型拟合器。

```python
calculator = LPPLCalculator()
```

使用差分进化算法（`scipy.optimize.differential_evolution`）求解 LPPL 模型七参数 `(tc, m, w, a, b, c, phi)`。采用变量投影法降维：非线性参数 `[tc, m, w]` 用 DE 优化，线性参数 `[a, b, c1, c2]` 用最小二乘直接求解。

#### `fit(df: pd.DataFrame, column: str = "close") -> Dict[str, Any]`

- **Sornette 约束**: `m_min < m < m_max`, `w_min < w < w_max`, `b < 0`, `|c| > c_min_abs`
- **风险等级**: `days_to_tc < danger_days` -> Danger; `< warning_days` -> Warning; 否则 Safe
- **泡沫判定**: 满足 Sornette 约束 + `b < 0` + `|c| > c_abs_for_bubble` + `confidence > confidence_threshold`

输出字段：`is_bubble`, `tc`, `days_to_tc`, `confidence`, `risk_level`, `model_params`, `market_metrics`。

#### `fit_single_window(close_prices: np.ndarray) -> Optional[Dict]`

对单一时间窗口拟合，带 LRU 缓存（`hashlib.sha256` 键，最大 128 条）。

### 配置类

**`LPPLConfig`** 数据类控制所有参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `window_range` | `[40, 60, 80]` | 扫描窗口列表 |
| `optimizer` | `"de"` | 优化器（`de` / `lbfgsb`） |
| `maxiter` | `100` | 最大迭代次数 |
| `m_bounds` | `(0.1, 0.9)` | Sornette m 参数范围 |
| `w_bounds` | `(5, 18)` | Sornette w 参数范围 |
| `r2_threshold` | `0.5` | R-squared 阈值 |
| `danger_days` | `5` | 危险天数阈值 |
| `warning_days` | `12` | 警告天数阈值 |
| `watch_days` | `25` | 观察天数阈值 |
| `consensus_threshold` | `0.5` | 集成共识度阈值 |
| `n_workers` | `-1` | 并行工作线程数 |

### 风险等级分类

`classify_top_phase(days_left, r2, config)` 返回四级风险：

- `"danger"`: `days_left < danger_days` 且 `r2 >= danger_r2_threshold`
- `"warning"`: `days_left < warning_days` 且 `r2 >= warning_r2_threshold`
- `"watch"`: `days_left < watch_days` 且 `r2 >= watch_r2_threshold`
- `"none"`: 其他情况

### 集成分析

`process_single_day_ensemble()` 对单个交易日执行系综集成：

1. 扫描所有窗口，硬过滤（R-squared > 阈值 + Sornette 约束）。
2. 共识度验证：`valid_n / total_windows >= consensus_threshold`。
3. 崩溃时间聚类分析：计算 `tc_std`。
4. 方向共识：正向（`b < 0, |c| > 0.01`）与负向拟合的比例。
5. 信号强度：`consensus_rate * (1.0 / (tc_std + 1.0))`。

---

## Wyckoff 分析

### WyckoffEngine 类

**`WyckoffEngine`** -- v3.0 威科夫分析引擎，严格按九步流程执行。

```python
WyckoffEngine(
    lookback_days=120,
    weekly_lookback=180,
    monthly_lookback=120,
    is_st=False,
)
```

#### `analyze(df, symbol, period="日线", multi_timeframe=False, image_evidence=None) -> WyckoffReport`

主入口方法。当 `multi_timeframe=True` 且 `period="日线"` 时，自动进行日/周/月三周期分析。

### 九步分析流程

| 步骤 | 方法 | 功能 |
|------|------|------|
| Step 0 | `_step0_bc_tr_scan()` | BC/SC 定位扫描，确定 TR 上下边界 |
| Step 1 | `_step1_phase_determine()` | 大局观与阶段判定 |
| Step 2 | `_step2_effort_result()` | 努力与结果分析（含跳空缺口检测） |
| Step 3 | `_step3_phase_c_t1()` | Spring/UTAD 检测 + T+1 风险 |
| Step 3.5 | `_step35_counterfactual()` | 反事实压力测试 |
| Step 4 | `_step4_risk_reward()` | 盈亏比投影 |
| 置信度 | `_calc_confidence()` | 5 条件置信度矩阵 |
| Step 5 | `_step5_trading_plan()` | 交易计划生成 |
| 铁律 | `_apply_a_stock_rules()` | A 股铁律检查（Markdown 禁做多等） |

### 阶段（Phase）

**`WyckoffPhase`** 枚举定义五个阶段：

| 阶段 | 说明 |
|------|------|
| `ACCUMULATION` | 吸筹阶段，含 Phase A/B/C/D/E 细分 |
| `DISTRIBUTION` | 派发阶段，含子阶段细分 |
| `MARKUP` | 上涨阶段 |
| `MARKDOWN` | 下跌阶段 |
| `UNKNOWN` | 不确定阶段，含多种候选子状态 |

### 关键事件检测

- **Spring**: 价格刺穿 TR 下边界后快速收回。Spring 质量分级：一级（放量确认）、二级（缩量待确认）。
- **UTAD (Upthrust After Distribution)**: 价格刺穿 TR 上边界 2% 后收回。
- **LPS (Last Point of Support)**: Spring 后续 K 线验证，通过 `rule6_spring_validation()` 确认。
- **SOS (Sign of Strength)**: 价格突破 TR 上边界 95% 且量能配合。

### 多周期分析

当 `multi_timeframe=True` 时：
1. 日线数据重采样为周线和月线。
2. 分别对日/周/月执行 `_analyze_single()`。
3. 通过 `_merge_multitimeframe_reports()` 合并报告。

### 置信度等级

`_calc_confidence()` 基于 5 个条件评估：

1. BC 是否定位
2. Spring + LPS 是否验证
3. 反事实检验是否通过
4. 盈亏比是否 >= 2.5
5. 多周期是否一致

置信度分为 A/B/C 三级，对应不同仓位建议（标准仓/半仓/试仓）。

### 输出

返回 `WyckoffReport` 数据类，包含：`structure`（WyckoffStructure）、`signal`（WyckoffSignal）、`risk_reward`（RiskRewardProjection）、`trading_plan`（TradingPlan）、`limit_moves`、`stress_tests`、`chip_analysis` 等。

---

## NTF 引擎

### NTFEngine 类

**`NTFEngine`** -- 国家队因子引擎，监控大型 ETF 的脉冲式成交量异常，识别国家队干预行为。

```python
NTFEngine(volume_ratio_threshold=None)
```

监控标的：510300（沪深300 ETF）、510050（上证50 ETF）、563300（中证2000 ETF）。

#### `detect_intervention(etf_df: pd.DataFrame, window=None) -> Dict[str, Any]`

- **输入**: ETF 日线数据，需包含 `close` 和 `volume`/`vol` 列，至少 20 行。
- **检测逻辑**:
  1. 计算成交量比：`curr_volume / mean_volume`，超过 `volume_ratio_threshold` 为脉冲信号。
  2. 计算价格分位数：当前价格在近 20 天的百分位位置。
  3. 综合判定方向：
     - `price_percentile < panic_threshold` -> `SUPPORT`（护盘买入）
     - `price_percentile > heat_threshold` -> `RESISTANCE`（降温卖出）
     - 其他 -> `LIQUIDITY_PULSE`（方向不明）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `volume_ratio_threshold` | `NTFConstants.VOLUME_RATIO_THRESHOLD` | 成交量脉冲阈值 |
| `heat_threshold` | `NTFConstants.HEAT_THRESHOLD` | 市场过热分位阈值 |
| `panic_threshold` | `NTFConstants.PANIC_THRESHOLD` | 恐慌分位阈值 |
| `window` | `NTFConstants.WINDOW` | 成交量均值窗口 |

#### `scan_for_giants(market_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict]`

批量扫描所有关键 ETF。

---

## Regime 市场状态检测

### RegimeDetector 类

**`RegimeDetector`** -- 流动性状态检测器，识别市场"相变"以防止在流动性枯竭时交易。

```python
RegimeDetector(
    entropy_threshold=None,
    turnover_z_limit=None,
    min_data_points=None,
)
```

### 三种市场状态

**`Regime`** 枚举：

| 状态 | 说明 | 触发条件 |
|------|------|----------|
| `NORMAL` | 流动性充裕 | 默认状态 |
| `STRESSED` | 波动异常 | 成交量 Z-Score 绝对值超过阈值 |
| `FROZEN` | 流动性枯竭 | 熵值分位数低于阈值 |
| `UNKNOWN` | 数据不足 | 分析异常时返回 |

#### `detect(df: pd.DataFrame) -> Regime`

- **检测逻辑**:
  1. 计算 Shannon 熵的滑动窗口分位数。
  2. 计算成交量 Z-Score。
  3. 熵值分位数 < `ENTROPY_PERCENTILE_THRESHOLD` -> FROZEN。
  4. Z-Score 绝对值 > `TURNOVER_Z_SCORE_THRESHOLD` -> STRESSED。
  5. 否则 -> NORMAL。

#### `get_summary(df: pd.DataFrame) -> Dict[str, Any]`

返回详细指标：`regime`、`entropy`、`turnover_z`、`is_safe`。

---

## Alpha 解耦器

### AlphaDecoupler 类

**`AlphaDecoupler`** -- 超额收益解耦器，分离 Beta 收益，寻找真正具有 Alpha 的标的。

所有方法均为 `@staticmethod`。

#### `get_benchmark(market_cap: float) -> str`

根据市值路由到合适的基准指数：

| 市值范围 | 基准指数 |
|----------|----------|
| > 800 亿 | 000300.SH（沪深300） |
| 200-800 亿 | 000905.SH（中证500） |
| 50-200 亿 | 000852.SH（中证1000） |
| < 50 亿 | 932000.CSI（中证2000） |

阈值可通过配置 `brain.alpha_decoupler.benchmark_thresholds` 自定义。

#### `calc_rs_slope(stock_df, bench_df, window=20) -> float`

计算相对强度斜率（RS Slope）。

- **逻辑**: 先分别计算各自收益率再 merge（避免停牌复牌脉冲噪音），计算收益率差的累积 RS 曲线，对最近 `window` 天做线性拟合，返回斜率 * 100。
- **输入**: stock_df / bench_df 均需包含 `date`, `close` 列。

#### `calc_benchmark_corr(stock_df, bench_df, window=20) -> float`

计算与基准的相关性系数。

#### `get_alpha_score(stock_df, bench_df, sector_df=None) -> float`

行业中性 Alpha 得分。双重走强：个股不仅强于大盘，还要强于所属板块。返回 `slope_vs_bench + slope_vs_sector`。

#### `get_alpha_features(stock_df, bench_df, window=20) -> Dict`

一次获取所有 Alpha 特征：`rs_slope` 和 `benchmark_corr`。

---

## 因子系统

因子系统由四个核心组件构成，位于 `brain.factors` 子包。

### FactorRegistry -- 因子注册中心

**`FactorRegistry`** -- 全局单例，线程安全（`threading.Lock`）。

```python
FactorRegistry.register(
    name="momentum_20d",
    compute_func=lambda df: df["close"].pct_change(20),
    category="technical",   # technical / fundamental / alternative / custom
    default_weight=1.0,
    description="20日动量因子",
)
```

| 方法 | 说明 |
|------|------|
| `register(name, compute_func, category, default_weight, description)` | 注册因子 |
| `get_all()` | 获取所有因子 |
| `get_enabled()` | 获取启用的因子 |
| `get_factor(name)` | 获取指定因子 |
| `enable(name)` / `disable(name)` | 启用/禁用因子 |
| `list_factors()` | 列出因子名称和描述 |

**`FactorInfo`** 数据类：`name`, `category`, `compute_func`, `default_weight`, `enabled`, `description`, `ic_ir_history`。

### FactorAnalyzer -- 因子分析器

**`FactorAnalyzer`** -- 计算因子有效性指标 IC/IR。

#### `compute_ic_ir(df, factor_cols, holding_periods=[1,5,20], date_col, code_col, price_col, mode="backtest", test_size=0.0) -> Dict[str, Dict[int, FactorICResult]]`

- 使用 Spearman 秩相关计算 Rank IC。
- 向量化优化：批量计算所有远期收益，避免重复计算。
- `mode="live"` 时抛出 `ValueError`，防止前视偏差。
- `test_size > 0` 时启用 temporal split，检测过拟合（IC 差值 > 0.1 时告警）。

**`FactorICResult`** 数据类：`factor_name`, `ic_mean`, `ic_std`, `icir`, `ic_positive_ratio`, `ic_t_stat`, `n_periods`, `test_ic_mean`, `test_icir`。

#### 其他方法

| 方法 | 说明 |
|------|------|
| `compute_rank_ic(factor_values, forward_returns)` | 单次 Rank IC |
| `compute_factor_correlation(df, factor_cols, method)` | 因子相关性矩阵 |
| `get_top_factors(metric, top_n, min_periods)` | 获取最优因子列表 |
| `generate_report(results)` | 生成分析报告 |

### FactorComposer -- 因子合成器

**`FactorComposer`** -- 多因子合成，支持 Z-Score 标准化、对称正交化（`F_orth = F @ (F.T @ F)^{-1/2}`）、IC 加权。

```python
FactorComposer(orthogonalize=True)
```

#### `compose_scores(df, ic_weights=None, factor_cols=None, date_col="date") -> pd.DataFrame`

输出包含 `composite_score` 和标准化因子列的 DataFrame。

#### `process(df, factor_cols, ic_results, date_col, expanding=False) -> Tuple[DataFrame, Dict[str, float]]`

兼容性入口。`expanding=True` 时使用展开窗口 Walk-Forward 方式计算权重。

### WalkForwardFactorPipeline -- 样本外扫描流水线

**`WalkForwardFactorPipeline`** -- 严格切断训练/测试泄漏。

```python
WalkForwardFactorPipeline(
    train_window=504,    # 训练窗口（交易日）
    test_window=63,      # 测试窗口（交易日）
    min_train_days=252,  # 最小训练天数
    weight_method="rank_icir",
)
```

#### `run(df, factor_cols, date_col, code_col, price_col) -> WalkForwardResult`

滚动前进：训练窗口计算 IC/IR 确定权重 -> 测试窗口用训练权重打分 -> 永不使用未来数据。

输出 `WalkForwardResult`：`windows` 列表、`final_weights`、`oos_ic_mean`、`oos_icir`、`weight_stability`。

详细使用指南请参见 [guides/factors.md](../guides/factors.md)。

---

## 技术指标

### Indicators 类

**`Indicators`** -- 静态方法集合，所有方法均带 `@smart_cache` 缓存装饰器。

| 方法 | 签名 | 说明 |
|------|------|------|
| `calc_ma` | `(df, window, column="close")` | 简单移动平均 |
| `calc_ema` | `(df, window, column="close")` | 指数移动平均 |
| `calc_atr` | `(df, window=ATR_PERIOD)` | 平均真实波幅 |
| `calc_bollinger` | `(df, window=BOLLINGER_PERIOD, num_std=2.0)` | 布林带（上/中/下轨） |
| `calc_macd` | `(df, fast=12, slow=26, signal=9)` | MACD（macd/signal/hist） |
| `calc_rsi` | `(df, window=RSI_PERIOD)` | Wilder's RSI |
| `calc_market_entropy` | `(df, window=ENTROPY_WINDOW, bins=10)` | Shannon 熵（stride_tricks 向量化优化） |
| `calc_turnover_z` | `(df, window=TURNOVER_Z_PERIOD)` | 换手率/成交量 Z-Score |
| `calc_vol_ratio` | `(df, window=VOLUME_MA_PERIOD)` | 成交量比率 |
| `calculate_all_indicators` | `(df)` | 一次计算全部指标 |

所有 rolling 计算均使用 `min_periods` 参数（`max(window * 0.5, min_val)`），兼容次新股和停牌股。

成交量列兼容 `volume` 和 `vol` 两种列名。

---

## 全市场扫描器

### StockScreener 类

**`StockScreener`** -- 基于 `composite_score` 生成 Top/Bottom 榜单并验证技术信号。

```python
StockScreener(config=ScreenerConfig())
```

**`ScreenerConfig`** 数据类：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `top_n` | 50 | Top 榜单数量 |
| `bottom_n` | 50 | Bottom 榜单数量 |
| `sector_top_n` | 3 | 每个行业 Top 数量 |
| `min_data_points` | 60 | 最小数据点数要求 |

#### 主要方法

| 方法 | 说明 |
|------|------|
| `generate_top_bottom(df, score_col, code_col, date_col)` | 生成 Top/Bottom 榜单 |
| `generate_tech_signals(stocks_df, daily_data, code_col)` | 技术信号验证（MA 金叉/死叉、RSI 状态、MACD、趋势） |
| `generate_sector_top(df, sector_col, ...)` | 分行业 Top 股票 |
| `generate_market_risk_summary(daily_data)` | 全市场风险指标汇总（年化收益/波动/Sharpe/最大回撤） |
| `format_top_table(top_df, ...)` | 格式化为 Markdown 表格 |
| `format_risk_summary_table(summary)` | 格式化风险汇总为 Markdown |

技术信号验证输出四个维度：`ma_signal`（GOLDEN_CROSS / DEATH_CROSS / BULLISH_ALIGN / BEARISH_ALIGN）、`rsi_state`（OVERBOUGHT / OVERSOLD / BULLISH / BEARISH）、`macd_signal`（BULLISH / BEARISH）、`trend`（STRONG_UP / UP / STRONG_DOWN / DOWN / SIDEWAYS）。
