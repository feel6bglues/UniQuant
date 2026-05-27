# 配置与常量

## 何时使用
修改配置文件时；添加新常量时；理解 A 股约束时；调试配置加载问题时。

## GlobalConfig 机制

**文件**: `src/uniquant/shared/config_loader.py`

- **单例模式**：双重检查锁（`threading.Lock` + `__new__`）
- **加载优先级**：`config/config.yaml` 存在时加载统一配置；否则按命名空间加载分散 YAML（settings/markets/brain/data_sources/cache/czsc/indicators/indices/lppl/network）
- **dot-notation 访问**：`config.get("brain.fsm.ma_short", 20)`
- **必需配置段**：`base`, `cache`, `network`, `data_sources`（缺失时 `validate_config()` 返回 False）
- **延迟初始化**：`get_config()` 函数首次调用时创建实例

**便捷属性**：
| 属性 | 返回值 |
|------|--------|
| `ROOT_DIR` | 项目根目录（`Path`） |
| `DATA_DIR` | `base.data_lake.path`（默认 `data`） |
| `LAKE_DIR` | `base.data_lake.path`（默认 `data/lake`） |
| `LOG_DIR` | `cache.global.path`（默认 `logs`） |
| `CACHE_DIR` | `cache.global.path`（默认 `data/cache`） |

**默认值**（配置目录缺失时）：
```python
base.data_lake.path = "data/lake"
base.data_lake.engine = "duckdb"
cache.global.enabled = True
cache.global.path = "data/cache"
cache.ttl.stock_data = 3600
cache.ttl.realtime_data = 60
risk.default_risk_pct = 0.1
```

## config/config.yaml 结构

### base
```yaml
base:
  data_lake:
    path: "data/lake"
    compression: "snappy"
    engine: "duckdb"
  logging:
    level: "INFO"
    format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  tdx:
    path: "/home/james/.local/share/tdxcfv/drive_c/tc"  # 通达信路径
```

### cache
```yaml
cache:
  global:
    enabled: true
    path: "data/cache"
    max_age: 7        # 缓存最大保存天数
    batch_size: 5
  ttl:
    stock_data: 3600      # 股票数据 1小时
    index_data: 3600      # 指数数据 1小时
    realtime_data: 60     # 实时数据 1分钟
    market_cap: 300       # 市值数据 5分钟
    stock_info: 86400     # 股票信息 1天
    industry_data: 3600   # 行业数据 1小时
    concept_data: 3600    # 概念数据 1小时
    lppl_result: 1800     # LPPL结果 30分钟
  limits:
    max_entries: 1000
    max_memory_mb: 100
  performance:
    lazy_load: true
    preload_stocks: []
  cleanup:
    enabled: true
    interval: 300         # 清理间隔(秒)
    expired_only: true
```

### network
```yaml
network:
  timeout:
    default: 30
    connect: 10
    read: 30
    realtime: 10
    historical: 60
  retry:
    max_retries: 3
    retry_delay: 1.0
    backoff_factor: 2.0
    max_delay: 60.0
  rate_limit:
    requests_per_second: 5
    burst_size: 10
    min_interval: 0.2
  headers:
    User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    Accept: "*/*"
    Connection: "keep-alive"
    Cache-Control: "no-cache"
    Pragma: "no-cache"
  sources:
    eastmoney:
      base_url: "https://push2.eastmoney.com"
      timeout: 30
      retry: 3
      rate_limit: 5
    sina:
      base_url: "https://hq.sinajs.cn"
      timeout: 10
      retry: 3
      rate_limit: 10
    tencent:
      base_url: "https://qt.gtimg.cn"
      timeout: 10
      retry: 3
      rate_limit: 10
  connection_pool:
    max_connections: 100
    max_connections_per_host: 20
    keep_alive: true
    keep_alive_timeout: 30
  ssl:
    verify: true
    ca_bundle: null
    client_cert: null
    client_key: null
```

### data_sources
7 个数据源配置，3 个启用 + 6 个禁用：

| 数据源 | 类 | 优先级 | 启用 |
|--------|-----|--------|------|
| StockDataSource | `data.sources.stock_sources.StockDataSource` | 1 | ✅ |
| IndexDataSource | `data.sources.index_sources.IndexDataSource` | 2 | ✅ |
| EtfDataSource | `data.sources.etf_sources.EtfDataSource` | 3 | ✅ |
| BaoStockSource | `data.sources.baostock.BaostockSource` | 10 | ❌ |
| SinaSource | `data.sources.sina.SinaSource` | 11 | ❌ |
| TencentSource | `data.sources.tencent.TencentSource` | 12 | ❌ |
| EastmoneySource | `data.sources.eastmoney.EastmoneySource` | 13 | ❌ |
| EfinanceSource | `data.sources.efinance.EfinanceSource` | 14 | ❌ |
| ThsSource | `data.sources.ths.ThsSource` | 15 | ❌ |

数据类型映射：
- `stock.daily` / `stock.realtime` / `stock.market_cap` → StockDataSource
- `index.daily` → IndexDataSource
- `sector.daily` → StockDataSource
- `etf.daily` → EtfDataSource
- `industry` / `concept` → StockDataSource

### indicators
```yaml
indicators:
  ma:
    windows: [20, 60, 120]
  atr:
    period: 14
    multiplier: 2.0
  macd:
    fast: 12
    slow: 26
    signal: 9
  rsi:
    period: 14
```

### czsc（缠论）
```yaml
czsc:
  bi_params:
    min_bi_len: 5
    include_handling: true
    fractal_strict: true
  buy_points:
    3rd_buy:
      pivot_break: true
      pullback_limit: 0.1
```

### lppl（LPPL 泡沫检测）
```yaml
lppl:
  m_min: 0.1
  m_max: 0.9
  w_min: 6.0
  w_max: 13.0
  optimizer:
    max_iter: 500
    popsize: 10
    tolerance: 0.01
    mutation_min: 0.5
    mutation_max: 1.0
    recombination: 0.7
    seed: 42
    workers: 1          # 必须为1，避免嵌套多进程死锁
  data:
    min_data_points: 60
    tc_search_range: 50
    tc_future_range: 100
  bounds:
    tc_backward: 50
    tc_forward: 100
    a_multiplier: 1.1
    b_min: -20
    b_max: 20
    c_min: -20
    c_max: 20
    phi_max: 6.283185307
  constraints:
    m_range: [0.1, 0.9]
    w_range: [6, 13]
    b_sign: "negative"
    c_min_abs: 0.01
    c_abs_for_bubble: 0.1
  confidence:
    tc_weight: 0.4
    cost_weight: 0.4
    data_weight: 0.2
    data_reference: 200
    cost_scale: 0.1
  risk_levels:
    danger_days: 10
    warning_days: 20
    safe_days: 30
  bubble:
    confidence_threshold: 0.6
    b_sign: "negative"
  performance:
    cache_enabled: true
    cache_precision: 4
```

### markets
```yaml
markets:
  etfs:
    critical:
      "510300.SH": "CSI300 ETF"
      "510050.SH": "SSE50 ETF"
      "510500.SH": "CSI500 ETF"
      "512100.SH": "CSI1000 ETF"
      "563300.SH": "CSI2000 ETF"
    default_list:
      - "510300"
      - "510050"
      - "510500"
      - "159915"
      - "512880"
      - "512480"
      - "512010"
      - "512660"
      - "512690"
      - "518880"
  benchmarks:
    rules:
      large_cap: "000300.SH"
      mid_cap: "000905.SH"
      small_cap: "000852.SH"
    names:
      "000300.SH": "沪深300"
      "000905.SH": "中证500"
      "000852.SH": "中证1000"
      "000016.SH": "上证50"
  indices:
    - id: "000001.SH"
      name: "上证指数"
    - id: "000300.SH"
      name: "沪深300"
    - id: "000905.SH"
      name: "中证500"
    - id: "000852.SH"
      name: "中证1000"
    - id: "399006.SZ"
      name: "创业板指"
```

### risk
```yaml
risk:
  default_risk_pct: 0.1
  circuit_break_pct: 0.15
```

### brain（核心逻辑引擎）
```yaml
brain:
  alpha_decoupler:
    benchmark_thresholds:
      large_cap: 50000000000   # 50B
      mid_cap: 10000000000     # 10B
    window: 20
  ntf:
    volume_ratio_threshold: 2.0
    window: 5
  regime:
    entropy_threshold: 0.2
    turnover_z_limit: 3.0
    min_data_points: 30
  fsm:
    ma_short: 20
    ma_long: 60
```

## trading.yaml 结构

**文件**: `config/trading.yaml`

### data
```yaml
data:
  tdx_paths:
    sh: "${LPPL_TDX_DATA_DIR}/sh/lday/"    # 环境变量解析
    sz: "${LPPL_TDX_DATA_DIR}/sz/lday/"    # 环境变量解析
  db_path: "data/trading.db"
  csi300_path: "${LPPL_TDX_DATA_DIR}/sh/lday/sh000300.day"
```

### strategies
| 策略 | 启用 | 权重 | 关键参数 |
|------|------|------|----------|
| wyckoff | ✅ | 0.30 | lookback_days=400, weekly_lookback=120, monthly_lookback=40, score_threshold=0.45, min_confidence_level="B" |
| ma_atr | ✅ | 0.35 | fast_period=5, slow_period=20, atr_period=20 |
| reversal | ✅ | 0.20 | lookback_days=5, threshold_pct=5.0, hold_days=5, take_profit_pct=4.0, stop_loss_pct=4.0 |
| regime | ✅ | 0.15 | — |

### risk
```yaml
risk:
  max_positions: 30
  max_single_stock_pct: 5.0
  max_single_sector_pct: 20.0
  max_drawdown_pct: 15.0
  max_drawdown_stop_pct: 25.0
  consecutive_losses: 5
  var_confidence: 0.95
  max_daily_var_pct: 2.0
```

### execution
```yaml
execution:
  broker: "simulator"
  order_timeout_minutes: 30
  slippage_pct: 0.1
  initial_capital: 100000.0
  buy_fee_pct: 0.0003
  sell_fee_pct: 0.0003
  min_commission: 5.0
```

## factors.yaml 结构

**文件**: `config/factors.yaml`

| 因子 | 启用 | 权重 | 类别 |
|------|------|------|------|
| momentum_20d | ✅ | 1.2 | technical |
| turnover_momentum_20d | ✅ | 0.85 | technical |
| pe_ttm | ✅ | 0.7 | fundamental |

## optimal_params.yaml 结构

**文件**: `config/optimal_params.yaml`

```yaml
version: 1
defaults:
  optimizer: lbfgsb
  lookahead_days: 60
  drop_threshold: 0.10
  ma_window: 5
  max_peaks: 10
  signal_model: multi_factor_v1
  initial_position: 0.0
  positive_consensus_threshold: 0.25
  negative_consensus_threshold: 0.20
  rebound_days: 15
  trend_fast_ma: 20
  trend_slow_ma: 120
  trend_slope_window: 10
  atr_period: 14
  atr_ma_window: 60
  vol_breakout_mult: 1.05
  buy_volatility_cap: 1.05
  drawdown_confirm_threshold: 0.05
  buy_vote_threshold: 3
  sell_vote_threshold: 3
  buy_confirm_days: 2
  sell_confirm_days: 2
  cooldown_days: 15
  require_trend_recovery_for_buy: true
```

窗口集：`narrow_40_120`, `default_40_150`, `wide_30_180`

## A 股约束速查

**来源**: `MarketConstants`（`constants.py:100`）+ `limit_checker.py`

| 约束 | 值 | 来源 |
|------|-----|------|
| 主板涨跌停 | ±10%（比例 1.10/0.90） | `MarketConstants.LIMIT_RATIO["main"]` |
| 科创板涨跌停 | ±20%（比例 1.20/0.80） | `MarketConstants.LIMIT_RATIO["sci_tech"]` |
| 创业板涨跌停 | ±20%（比例 1.20/0.80） | `MarketConstants.LIMIT_RATIO["gem"]` |
| 北交所涨跌停 | ±30%（比例 1.30/0.70） | `MarketConstants.LIMIT_RATIO["beijing"]` |
| ST 股涨跌停 | ±5%（比例 1.05/0.95） | `MarketConstants.LIMIT_RATIO["st"]` |
| 价格容差 | 0.001（0.1%） | `MarketConstants.PRICE_TOLERANCE` |
| 印花税 | 0.05%（万5，仅卖出） | `cost_model.STAMP_TAX_PCT` |
| 佣金 | 0.03%（万3） | `cost_model.COMMISSION_PCT` |
| 最低佣金 | 5 元/笔 | `cost_model.MIN_COMMISSION` |
| 滑点 | 0.05%（万5） | `cost_model.SLIPPAGE_PCT` |
| 交易时段 | 9:30-11:30, 13:00-15:00 | `MarketHours` |
| 交易日 | 周一至周五 | `MarketHours.TRADING_DAYS` |

板块识别逻辑（`limit_checker.get_board_type`）：
1. ST 股优先（名称以 `ST` / `*ST` 开头）
2. 科创板（代码以 `688` 开头）
3. 创业板（代码以 `300` / `301` 开头）
4. 北交所（代码以 `8` / `4` 开头）
5. 主板（`600/601/603/605/000/001/002`）

## 常量类速查

**文件**: `src/uniquant/shared/constants.py`（1139 行，30 个类）

| 类名 | 用途 | 关键字段 |
|------|------|----------|
| `WindowConfig` | LPPL 窗口配置 | `all_windows=[100,150,200,250,300,400,500,600,750]`, `SHORT_MAX=200`, `MEDIUM_MAX=400` |
| `DateConstants` | 日期格式 | `DEFAULT_START_DATE="2000-01-01"`, `FORMAT_DASH`, `FORMAT_COMPACT` |
| `AnalysisServiceConstants` | 分析服务参数 | `MEMORY_CACHE_MAX_SIZE=1000`, `DEFAULT_VAR_95=0.05`, `STOP_LOSS_RATIO=0.95`, `TAKE_PROFIT_RATIO=1.10` |
| `TimeConstants` | 时间跨度 | `DAYS_1_YEAR=365`, `DAYS_MONTH=30`, `DAYS_QUARTER=90` |
| `MarketConstants` | 市场常量 | 交易所/指数代码/板块前缀/涨跌停比例/价格容差 |
| `MarketCapThresholds` | 市值分级 | `LARGE_CAP=1000亿`, `MID_CAP=300亿`, `SMALL_CAP=50亿`, `MICRO_CAP=10亿` |
| `TimeWindows` | 分析窗口 | `SHORT_TERM=20`, `MEDIUM_TERM=60`, `LONG_TERM=120`, `VERY_LONG_TERM=252` |
| `IndicatorThresholds` | 技术指标阈值 | RSI/MACD/布林带/MA/ATR/FSM 各项阈值 |
| `RiskThresholds` | 风险控制阈值 | `VAR_DAILY_LIMIT=0.02`, `MAX_DRAWDOWN_LIMIT=0.15`, `MAX_POSITION_PCT=0.95` |
| `RiskCalculationConstants` | 风险计算常量 | VaR/CVaR/波动率/夏普比率阈值，压力测试场景 |
| `DataValidationConstants` | 数据验证 | `MIN_PRICE=0.01`, `MAX_PRICE=10000`, `MIN_DATA_POINTS=30` |
| `PrecisionConstants` | 精度控制 | `PRICE_DECIMALS=2`, `RATE_DECIMALS=4`, `FLOAT_TOLERANCE=1e-6` |
| `PerformanceConstants` | 性能优化 | `DEFAULT_CACHE_TTL=300`, `BATCH_SIZE=100`, `MAX_WORKERS=4` |
| `NetworkConstants` | 网络常量 | 超时/重试/HTTP 状态码/Sina API 配置 |
| `CacheConstants` | 缓存常量 | TTL/缓存类型/缓存策略/数据服务 TTL |
| `PathConstants` | 路径常量 | `DATA_DIR`, `RAW_DIR`, `CLEAN_DIR`, `LAKE_DIR`, `REPORT_DIR`, `LOG_DIR` |
| `DataSourceConstants` | 数据源常量 | 重试配置/列名映射/单位转换/股票代码前缀 |
| `THSConstants` | 同花顺数据源 | `HISTORICAL_URL`, `REALTIME_API_URLS` |
| `DataLakeConstants` | 数据湖常量 | `DEFAULT_ROOT_PATH="data/lake"`, `QUARANTINE_PATH="data/quarantine"` |
| `UIConstants` | UI 显示 | `DASHBOARD_PORT=8504`, `REFRESH_INTERVAL_MS=10000` |
| `TestConstants` | 测试常量 | 各类测试阈值/超时/重试参数 |
| `ToolConstants` | 工具常量 | 代码质量阈值/架构检查/报告配置 |
| `DataServiceConstants` | 数据服务常量 | 缓存 TTL/数据质量评分/时效性得分 |
| `NTFConstants` | NTF 引擎 | `HEAT_THRESHOLD=0.8`, `PANIC_THRESHOLD=0.1`, `VOLUME_RATIO_THRESHOLD=2.0` |
| `LPPLConstants` | LPPL 泡沫检测 | 优化器/RMSE/数据/边界/约束/置信度/风险等级/窗口配置 |
| `RegimeConstants` | 市场状态检测 | `ENTROPY_PERCENTILE_THRESHOLD=0.1`, `TURNOVER_Z_SCORE_THRESHOLD=2.5` |
| `UATConstants` | UAT 测试 | `UAT_TEST_DAYS=365`, `UAT_TEST_COUNT=3` |
| `ResultsConstants` | 结果管理 | `MAX_RESULTS_PER_SYMBOL=30`, `CLEANUP_THRESHOLD_DAYS=30` |
| `BacktestConstants` | 回测引擎 | `DEFAULT_INITIAL_CAPITAL=100000`, `DEFAULT_COMMISSION_RATE=0.0003` |
| `MarketHours` | 市场时间 | 交易时段/交易日/`is_market_open()`/`get_next_open_time()`/`get_market_status()` |

**模块级常量**：
| 常量 | 值 | 用途 |
|------|-----|------|
| `ENABLE_NUMBA_JIT` | `True` | Numba JIT 优化开关 |
| `REQUIRED_COLUMNS` | `["open","high","low","close","volume"]` | 必需列名 |
| `M_BOUNDS` | `(0.1, 0.9)` | LPPL m 参数范围 |
| `W_BOUNDS` | `(6.0, 13.0)` | LPPL w 参数范围 |
| `RANDOM_SEED` | `42` | 随机种子 |
| `OUTPUT_DIR` | `"hands/reports"` | 输出目录 |
| `ENABLE_JOBLIB_PARALLEL` | `True` | Joblib 并行开关 |

**Wyckoff 常量**（模块级）：
| 常量 | 值 |
|------|-----|
| `SPRING_LOW_FACTOR` | 1.01 |
| `SPRING_CLOSE_FACTOR` | 1.0 |
| `MIN_RR_RATIO` | 2.5 |
| `MIN_WYCKOFF_DATA_ROWS` | 200 |
| `BC_LOOKBACK_WINDOW` | 20 |
| `SPRING_FREEZE_DAYS` | 3 |
| `WYCKOFF_OUTPUT_DIR` | `"data/state/wyckoff"` |
| `TR_MAX_RANGE_PCT` | 0.20 |
| `TR_MAX_SHORT_TREND` | 0.05 |

## 成本模型

**文件**: `src/uniquant/shared/cost_model.py`

### 模块级常量
| 常量 | 值 | 说明 |
|------|-----|------|
| `COMMISSION_PCT` | 0.0003 | 佣金万3 |
| `STAMP_TAX_PCT` | 0.0005 | 印花税万5（2024+） |
| `STAMP_TAX_PCT_OLD` | 0.001 | 印花税千1（2024 前） |
| `MIN_COMMISSION` | 5.0 | 单笔最低佣金 |
| `SLIPPAGE_PCT` | 0.0005 | 滑点万5 |
| `COST_BUY` | 0.0003 | 买入成本 = 佣金 |
| `COST_SELL` | 0.0008 | 卖出成本 = 佣金 + 印花税 |

### CostConfig 数据类
```python
@dataclass
class CostConfig:
    buy_fee_pct: float = 0.0003
    sell_fee_pct: float = 0.0003
    stamp_tax_pct: float = 0.0005
    slippage_pct: float = 0.0005
    min_commission: float = 5.0
```

**加载方式**：
- `CostConfig.from_env()` — 从环境变量覆盖
- `CostConfig.from_yaml()` — 从 `trading.yaml` 的 `execution` 段加载

**计算属性**：
- `cost_buy` = `buy_fee_pct`
- `cost_sell` = `sell_fee_pct + stamp_tax_pct`

## 环境变量覆盖

| 环境变量 | 覆盖字段 | 来源 |
|----------|----------|------|
| `LPPL_COST_BUY_FEE` | `CostConfig.buy_fee_pct` | `cost_model.py` |
| `LPPL_COST_SELL_FEE` | `CostConfig.sell_fee_pct` | `cost_model.py` |
| `LPPL_COST_STAMP_TAX` | `CostConfig.stamp_tax_pct` | `cost_model.py` |
| `LPPL_COST_SLIPPAGE` | `CostConfig.slippage_pct` | `cost_model.py` |
| `LPPL_COST_MIN_COMMISSION` | `CostConfig.min_commission` | `cost_model.py` |
| `LPPL_TDX_DATA_DIR` | `trading.yaml` 中的 TDX 路径 | `trading.yaml` |

`trading.yaml` 中使用 `${LPPL_TDX_DATA_DIR}` 语法引用环境变量，用于配置通达信数据目录路径。

## 涨跌停检查模块

**文件**: `src/uniquant/shared/limit_checker.py`

### LimitStatus 数据类
```python
@dataclass
class LimitStatus:
    is_limit_up: bool
    is_limit_down: bool
    can_buy: bool
    can_sell: bool
    board_type: str
    up_limit_price: float
    down_limit_price: float
    price_ratio: float
```

### 核心函数
| 函数 | 用途 |
|------|------|
| `get_board_type(symbol, name)` | 根据代码/名称识别板块类型 |
| `check_limit_status(current_price, pre_close, symbol, name, board_type)` | 检查涨跌停状态，返回 `LimitStatus` |
| `check_limit_status_dict(...)` | 同上，返回字典格式（兼容旧代码） |
| `validate_trade_action(action, current_price, pre_close, symbol, name)` | 验证交易动作可行性（BUY/SELL/ADD） |

涨停时 `can_buy=False`，跌停时 `can_sell=False`。
