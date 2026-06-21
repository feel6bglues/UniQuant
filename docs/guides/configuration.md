# 配置指南

本文档详细介绍 UniQuant 的配置体系，包括配置文件结构、加载机制、环境变量覆盖以及最佳实践。

---

## 配置文件概览

UniQuant 使用多个 YAML 配置文件，按职责划分：

| 文件 | 路径 | 说明 |
|------|------|------|
| `config.yaml` | `config/config.yaml` | 主配置文件，包含基础设置、缓存、网络、数据源、技术指标、LPPL 模型、市场、风险、Brain 等全部核心配置 |
| `trading.yaml` | `config/trading.yaml` | 交易策略与执行配置，包含数据路径、策略参数、风控规则、执行参数 |
| `factors.yaml` | `config/factors.yaml` | 因子定义，包含因子名称、权重、类别和启用状态 |
| `optimal_params.yaml` | `config/optimal_params.yaml` | 经调优的 LPPL 模型参数，包含每个指数的个性化参数和窗口集定义 |

---

## GlobalConfig 加载机制

`GlobalConfig` 是 UniQuant 的配置中心，采用 **单例模式 + 线程安全** 设计。

### 单例与线程安全

```python
class GlobalConfig:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._load_config()
        return cls._instance
```

使用双重检查锁（Double-Checked Locking）确保在多线程环境下只创建一个实例。

### YAML 加载顺序

1. **优先尝试统一配置文件**: 如果 `config/config.yaml` 存在，将其作为主配置直接加载（无命名空间前缀）
2. **回退到分散配置文件**: 如果不存在统一配置文件，则依次加载 `settings.yaml`、`markets.yaml`、`brain.yaml`、`data_sources.yaml`、`cache.yaml`、`czsc.yaml`、`indicators.yaml`、`indices.yaml`、`lppl.yaml`、`network.yaml`，每个文件加载到对应的命名空间下
3. **追加加载额外配置**: 无论采用哪种方式，都会额外加载 `trading.yaml`（命名空间 `trading`）和 `factors.yaml`（命名空间 `factors`）

### 点表示法访问

通过 `get()` 方法使用点号分隔的路径访问配置值：

```python
from uniquant.shared.config_loader import get_config

config = get_config()

# 获取通达信路径
tdx_path = config.get("base.tdx.path")

# 获取网络超时，带默认值
timeout = config.get("network.timeout.default", 30)

# 获取 LPPL 优化器最大迭代次数
max_iter = config.get("lppl.optimizer.max_iter", 500)
```

### 配置验证

加载完成后自动执行验证，检查以下必要段：

- `base`: 必须包含 `data_lake.path` 和 `data_lake.engine`
- `cache`: 必须包含 `global.enabled`、`global.path`、`ttl.stock_data`、`ttl.realtime_data`
- `network`: 必须包含 `timeout.default`
- `data_sources`: 必须包含 `sources`

`brain`、`lppl`、`risk` 段为可选验证，缺失时仅发出警告。

### 便捷属性

`GlobalConfig` 提供以下便捷属性：

```python
config.ROOT_DIR    # 项目根目录 (Path)
config.DATA_DIR    # 数据目录 (Path)
config.LAKE_DIR    # 数据湖目录 (Path)
config.LOG_DIR     # 日志目录 (Path, 自动创建)
config.CACHE_DIR   # 缓存目录 (Path, 自动创建)
```

文件位置: `src/uniquant/shared/config_loader.py`

---

## config.yaml 详解

`config.yaml` 是 UniQuant 的主配置文件，包含以下主要段：

### base (基础配置)

```yaml
base:
  data_lake:
    path: "data/lake"         # 数据湖存储路径
    compression: "snappy"     # Parquet 压缩方式
    engine: "duckdb"          # 查询引擎
  logging:
    level: "INFO"             # 日志级别
  tdx:
    path: "/path/to/tdx"     # 通达信安装目录
```

### cache (缓存配置)

```yaml
cache:
  global:
    enabled: true             # 是否启用缓存
    path: "data/cache"        # 缓存目录
    max_age: 7                # 最大保存天数
    batch_size: 5             # 批量处理大小
  ttl:
    stock_data: 3600          # 股票数据 TTL (秒)
    index_data: 3600          # 指数数据 TTL (秒)
    realtime_data: 60         # 实时数据 TTL (秒)
    market_cap: 300           # 市值数据 TTL (秒)
    stock_info: 86400         # 股票信息 TTL (秒)
    industry_data: 3600       # 行业数据 TTL (秒)
    concept_data: 3600        # 概念数据 TTL (秒)
    lppl_result: 1800         # LPPL 计算结果 TTL (秒)
  limits:
    max_entries: 1000         # 最大缓存条目数
    max_memory_mb: 100        # 最大内存使用 (MB)
  cleanup:
    enabled: true             # 自动清理
    interval: 300             # 清理间隔 (秒)
    expired_only: true        # 仅清理过期条目
```

### network (网络配置)

```yaml
network:
  timeout:
    default: 30               # 默认超时
    connect: 10               # 连接超时
    read: 30                  # 读取超时
    realtime: 10              # 实时数据超时
    historical: 60            # 历史数据超时
  retry:
    max_retries: 3            # 最大重试次数
    retry_delay: 1.0          # 重试延迟 (秒)
    backoff_factor: 2.0       # 指数退避因子
    max_delay: 60.0           # 最大延迟 (秒)
  rate_limit:
    requests_per_second: 5    # 每秒请求数
    burst_size: 10            # 突发请求数
    min_interval: 0.2         # 最小请求间隔 (秒)
  sources:                    # 数据源特定网络配置
    eastmoney:
      base_url: "https://push2.eastmoney.com"
      timeout: 30
      retry: 3
      rate_limit: 5
    sina:
      base_url: "https://hq.sinajs.cn"
      timeout: 10
```

### data_sources (数据源配置)

参见 [数据源接入指南](data_sources.md) 中的"配置数据源"章节。

### indicators (技术指标配置)

```yaml
indicators:
  ma:
    windows: [20, 60, 120]    # 均线窗口
  atr:
    period: 14                # ATR 周期
    multiplier: 2.0           # ATR 乘数
  macd:
    fast: 12                  # 快线周期
    slow: 26                  # 慢线周期
    signal: 9                 # 信号线周期
  rsi:
    period: 14                # RSI 周期
```

### czsc (缠论配置)

```yaml
czsc:
  bi_params:
    min_bi_len: 5             # 最小笔长度 (K线根数)
    include_handling: true    # 包含处理
    fractal_strict: true      # 严格分型
  buy_points:
    3rd_buy:
      pivot_break: true       # 中枢突破
      pullback_limit: 0.1     # 回踩幅度限制
```

### lppl (LPPL 泡沫检测模型配置)

```yaml
lppl:
  m_min: 0.1                  # Sornette 缩放指数下限
  m_max: 0.9                  # Sornette 缩放指数上限
  w_min: 6.0                  # 角频率下限
  w_max: 13.0                 # 角频率上限
  optimizer:
    max_iter: 500             # 差分进化最大迭代次数
    popsize: 10               # 粒子群规模
    tolerance: 0.01           # 收敛容差
    workers: 1                # 并行工作线程 (必须为 1)
  risk_levels:
    danger_days: 10           # <10 天为 Danger
    warning_days: 20          # <20 天为 Warning
    safe_days: 30             # >=30 天为 Safe
```

### markets (市场配置)

定义 ETF 列表、基准指数和主要指数。

### risk (风险配置)

```yaml
risk:
  default_risk_pct: 0.1       # 默认风险比例 (10%)
  circuit_break_pct: 0.15     # 熔断比例 (15%)
```

### brain (核心逻辑配置)

```yaml
brain:
  alpha_decoupler:
    benchmark_thresholds:
      large_cap: 50000000000  # 大盘基准阈值 (500亿)
      mid_cap: 10000000000    # 中盘基准阈值 (100亿)
    window: 20
  ntf:
    volume_ratio_threshold: 2.0  # 成交量脉冲阈值
    window: 5
  regime:
    entropy_threshold: 0.2    # 熵值阈值
    turnover_z_limit: 3.0     # 成交量 Z-Score 限制
    min_data_points: 30       # 最小数据点数
  fsm:
    ma_short: 20              # 短期均线
    ma_long: 60               # 长期均线
```

---

## trading.yaml 详解

`trading.yaml` 定义交易策略、风控规则和执行参数。

### data (数据路径)

```yaml
data:
  tdx_paths:
    sh: "${LPPL_TDX_DATA_DIR}/sh/lday/"  # 上海日线数据路径
    sz: "${LPPL_TDX_DATA_DIR}/sz/lday/"  # 深圳日线数据路径
  db_path: "data/trading.db"              # 交易数据库路径
  csi300_path: "${LPPL_TDX_DATA_DIR}/sh/lday/sh000300.day"
```

> **注意**: `${LPPL_TDX_DATA_DIR}` 会被解析为环境变量 `LPPL_TDX_DATA_DIR` 的值。

### strategies (策略配置)

每个策略包含 `enabled`、`weight`、特有参数等：

```yaml
strategies:
  wyckoff:
    enabled: true
    lookback_days: 400        # 回溯天数
    weight: 0.30              # 策略权重
    score_threshold: 0.45     # 分数阈值
    min_confidence_level: "B" # 最低置信度级别
  ma_atr:
    enabled: true
    fast_period: 5
    slow_period: 20
    atr_period: 20
    weight: 0.35
  reversal:
    enabled: true
    lookback_days: 5
    threshold_pct: 5.0        # 触发阈值 (%)
    hold_days: 5              # 持仓天数
    take_profit_pct: 4.0      # 止盈 (%)
    stop_loss_pct: 4.0        # 止损 (%)
    weight: 0.20
  regime:
    enabled: true
    weight: 0.15
```

### risk (风控规则)

```yaml
risk:
  max_positions: 30           # 最大持仓数
  max_single_stock_pct: 5.0   # 单只股票最大占比 (%)
  max_single_sector_pct: 20.0 # 单行业最大占比 (%)
  max_drawdown_pct: 15.0      # 最大回撤预警 (%)
  max_drawdown_stop_pct: 25.0 # 最大回撤止损 (%)
  consecutive_losses: 5       # 连续亏损次数限制
  var_confidence: 0.95        # VaR 置信度
  max_daily_var_pct: 2.0      # 日 VaR 限制 (%)
```

### execution (执行参数)

```yaml
execution:
  broker: "simulator"         # 券商/模拟器
  order_timeout_minutes: 30   # 订单超时 (分钟)
  slippage_pct: 0.1           # 滑点 (%)
  initial_capital: 100000.0   # 初始资金 (元)
  buy_fee_pct: 0.0003         # 买入手续费率 (万3)
  sell_fee_pct: 0.0003        # 卖出手续费率 (万3)
  min_commission: 5.0         # 最低佣金 (元)
```

---

## factors.yaml 详解

因子配置文件定义了量化因子的属性。每个因子包含以下字段：

```yaml
factors:
  momentum_20d:
    enabled: true             # 是否启用
    weight: 1.2               # 因子权重
    category: technical       # 因子类别 (technical / fundamental)

  turnover_momentum_20d:
    enabled: true
    weight: 0.85
    category: technical

  pe_ttm:
    enabled: true
    weight: 0.7
    category: fundamental
```

- **enabled**: 控制因子是否参与计算
- **weight**: 因子在组合评分中的权重，数值越大影响越大
- **category**: 因子分类，支持 `technical`（技术面）和 `fundamental`（基本面）

---

## 环境变量

UniQuant 使用多个环境变量来控制运行时行为。

### 并行库线程控制

`env_config.py` 模块在启动时自动设置以下环境变量，防止在多进程环境中底层并行库创建过多线程导致进程炸弹：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `OMP_NUM_THREADS` | `1` | OpenMP 线程数 |
| `MKL_NUM_THREADS` | `1` | Intel MKL 线程数 |
| `OPENBLAS_NUM_THREADS` | `1` | OpenBLAS 线程数 |
| `BLIS_NUM_THREADS` | `1` | BLIS 线程数 |
| `VECLIB_MAXIMUM_THREADS` | `1` | macOS vecLib 线程数 |
| `NUMEXPR_NUM_THREADS` | `1` | NumExpr 线程数 |
| `LPPL_DISABLE_PARALLEL` | `1` | 禁用 LPPL 并行计算 |

这些变量使用 `os.environ.setdefault()` 设置，如果用户已显式设置则不会覆盖。

### 交易成本覆盖

`CostConfig.from_env()` 支持通过环境变量覆盖交易成本参数：

| 环境变量 | 对应字段 | 默认值 | 说明 |
|----------|----------|--------|------|
| `LPPL_COST_BUY_FEE` | `buy_fee_pct` | 0.0003 | 买入手续费率 (万3) |
| `LPPL_COST_SELL_FEE` | `sell_fee_pct` | 0.0003 | 卖出手续费率 (万3) |
| `LPPL_COST_STAMP_TAX` | `stamp_tax_pct` | 0.0005 | 印花税率 (万5, 2024+) |
| `LPPL_COST_SLIPPAGE` | `slippage_pct` | 0.0005 | 滑点率 (万5) |
| `LPPL_COST_MIN_COMMISSION` | `min_commission` | 5.0 | 单笔最低佣金 (元) |

### 数据路径

| 环境变量 | 说明 |
|----------|------|
| `LPPL_TDX_DATA_DIR` | 通达信数据目录，用于 `trading.yaml` 中的路径解析 |

---

## 常量 vs 配置

UniQuant 中存在两种参数管理方式：`shared/constants/` 子包中的常量和 `config.yaml` 中的配置项。它们的适用场景不同：

### 何时使用 shared/constants/

- **不应在运行时变化**的值: 市场交易时间、交易所代码、指数代码等
- **系统级约束**: 数据验证范围（最小价格、最大成交量）、精度控制（小数位数）
- **枚举和映射**: 板块前缀、涨跌停比例、缓存策略名称
- **代码中需要类型安全引用**的值: 通过类常量引用，IDE 可以提供自动补全和类型检查

### 何时使用 config.yaml

- **可能需要调优**的参数: 策略权重、指标周期、缓存 TTL
- **环境相关**的设置: 数据目录路径、日志级别、网络超时
- **需要热加载**（未来）或**不同部署环境**间可能不同的值
- **用户可能需要自定义**的设置: 数据源优先级、启用/禁用开关

---

## 配置最佳实践

### 覆盖层次

UniQuant 的配置存在以下覆盖层次（从低到高优先级）：

```
shared/constants/ (最低优先级, 编译时确定)
    |
config.yaml / trading.yaml / factors.yaml (运行时加载)
    |
环境变量 (最高优先级, 运行时覆盖)
```

高优先级的值会覆盖低优先级的值。例如：

- `shared/constants/market.py` 中 `COMMISSION_PCT = 0.0003`
- `trading.yaml` 中 `buy_fee_pct: 0.0003` (可设为不同值)
- 环境变量 `LPPL_COST_BUY_FEE=0.0002` 会覆盖以上两者

### 建议

1. **不要修改 shared/constants/**: 常量子包中的值经过精心设定，直接修改可能导致系统行为异常。如需调整，优先通过 config.yaml 或环境变量覆盖。

2. **使用 get_config() 获取配置**: 始终通过 `get_config()` 函数获取全局配置实例，确保单例一致性。

   ```python
   from uniquant.shared.config_loader import get_config
   config = get_config()
   value = config.get("section.subsection.key", default_value)
   ```

3. **提供合理的默认值**: 调用 `config.get()` 时务必提供 `default` 参数，以防配置文件缺少某项。

4. **环境变量用于部署差异**: 将开发环境和生产环境之间的差异通过环境变量管理，而非维护多份配置文件。

5. **敏感信息不入 YAML**: API 密钥、数据库密码等敏感信息应通过环境变量传入，不要写入配置文件。

6. **配置验证**: `GlobalConfig` 在加载后自动验证必要配置段。如果添加了新的必要配置，应在 `validate_config()` 中增加对应的验证逻辑。
