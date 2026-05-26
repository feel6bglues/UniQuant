# shared -- 公共基础设施

> **状态:** ✅ 基本完整 | **当前文件:** 23/29 | **缺失:** parallel, market_rules, 4 个常量子模块

`uniquant.shared` 是整个 UniQuant 系统的底层支撑包，约 5.2K LOC。所有上层模块（brain、data、risk、signal、services、ui）均依赖此包提供的常量定义、异常体系、错误处理、重试机制、缓存系统、配置管理、成本/滑点模型、涨跌停检查以及日志工厂等基础能力。

主要导出（`__init__.py`）：

- 常量类：`MarketCapThresholds`、`TimeWindows`、`IndicatorThresholds`、`RiskThresholds`、`DataValidationConstants`、`PrecisionConstants`、`PerformanceConstants`、`MarketConstants`
- 日志：`get_logger`、`setup_logger`、`LoggerFactory`
- 重试：`retry`、`retry_with_fallback`、`RetryConfig`
- 分析结果：`AnalysisResult`、`AnalysisResultBuilder`、`AnalysisStatus`
- 工具函数：`with_timeout`、`safe_execute`、`fetch_with_timeout`、`normalize_dataframe`、`retry_on_failure`

---

## 常量体系

常量统一定义在 `constants.py`（约 1135 行），按功能领域划分为多个类：

| 常量类 | 用途 |
|--------|------|
| `DateConstants` | 日期格式与默认起始日期 |
| `AnalysisServiceConstants` | 分析服务参数：缓存大小、默认 VaR/CVaR/MDD、MA 窗口、信号阈值等 |
| `TimeConstants` | 时间跨度：年/月/季度天数 |
| `MarketConstants` | 市场代码（CN/HK/US）、交易所、主要指数代码与名称、板块前缀、涨跌停比例 |
| `MarketCapThresholds` | 市值分级阈值（亿元）：大盘 1000、中盘 300、小盘 50、微盘 10 |
| `TimeWindows` | 分析窗口：SHORT_TERM(20)、MEDIUM_TERM(60)、LONG_TERM(120)、VERY_LONG_TERM(252)；波动率/趋势/状态/宏观窗口 |
| `IndicatorThresholds` | RSI/MACD/布林带/ATR 等技术指标阈值与周期参数 |
| `RiskThresholds` | 风险控制阈值：日 VaR 限制、最大回撤限制、仓位限制、波动率限制 |
| `RiskCalculationConstants` | VaR/CVaR/波动率/夏普比率阈值分级，压力测试场景（CRASH/RATE_HIKE/RECESSION） |
| `DataValidationConstants` | 数据校验：价格/成交量范围、日涨跌幅限制、最小数据点数、最大缺失比例 |
| `PrecisionConstants` | 精度控制：价格 2 位、收益率 4 位、浮点容差 1e-6 |
| `PerformanceConstants` | 性能参数：缓存 TTL、批量大小、最大工作线程、超时配置 |
| `NetworkConstants` | 网络配置：超时（DEFAULT/SHORT/MEDIUM/LONG）、重试（MAX_RETRIES=3、退避因子 2.0、抖动范围）、Sina API 配置 |
| `MarketHours` | A 股交易时段：上午 9:30-11:30、下午 13:00-15:00；提供 `is_market_open()` / `get_market_status()` / `next_open_time()` |
| `WindowConfig` | LPPL 扫描窗口配置 dataclass（short/medium/long windows） |
| `ResultsConstants` | 输出目录名称常量 |

完整字段参考请见 [reference/constants.md](../reference/constants.md)。

---

## 异常体系

所有自定义异常继承自 `AlphaTacticianError`，定义在 `exceptions.py`。层次结构如下：

```
AlphaTacticianError
├── DataError
│   ├── DataFetchError          # 网络请求/API调用失败
│   ├── DataValidationError     # 数据格式/完整性检查失败
│   ├── DataStorageError
│   │   └── DatabaseConnectionError
│   ├── DataAccessError
│   └── CacheError
├── AnalysisError
│   ├── LPPLFitError            # LPPL模型拟合错误
│   ├── CZSCEngineError         # 缠论引擎错误
│   └── EngineError
├── RiskError
│   ├── PositionSizingError     # 仓位计算错误
│   ├── EVTRiskError            # 极值风险计算错误
│   └── RiskCalculationError
├── ServiceError
│   ├── AnalysisServiceError
│   ├── DataServiceError
│   ├── PortfolioServiceError
│   └── DependencyError
├── UIError
│   ├── DashboardError
│   └── VisualizationError
├── ConfigurationError
├── OperationTimeoutError
├── ValidationError
├── BacktestError
├── LPPLException
│   ├── DataNotFoundError
│   └── ComputationError
└── WyckoffError
    ├── BCNotFoundError
    ├── InvalidInputDataError
    ├── ImageProcessingError
    ├── FusionConflictError
    └── RuleEngineError
```

完整说明请见 [reference/exceptions.md](../reference/exceptions.md)。

---

## 错误处理装饰器

`error_handling.py` 提供统一的错误处理基础设施，核心是 `handle_errors()` 通用装饰器以及多个专用装饰器。

### handle_errors()

```python
@handle_errors(
    *expected_exceptions,
    default_return=None,
    log_level=logging.ERROR,
    reraise=False,
    error_type="unknown",
    context=None,
)
```

工作流程：
1. 捕获 `expected_exceptions` 中声明的异常类型，记录日志并返回 `default_return`
2. 捕获 `AlphaTacticianError` 体系内的异常，同样记录并返回默认值
3. 捕获所有其他未预期异常，以 ERROR 级别记录完整 traceback
4. 如果 `reraise=True`，在记录日志后重新抛出异常
5. 日志中自动过滤敏感参数（password、token）

### 专用装饰器

| 装饰器 | 目标异常 | 附加能力 |
|--------|----------|----------|
| `handle_network_errors(default_return, max_retries)` | `requests.RequestException`, `ConnectionError`, `TimeoutError` | 自动重试 |
| `handle_file_errors(default_return)` | `FileNotFoundError`, `PermissionError`, `IOError` | -- |
| `handle_data_errors(default_return)` | `pd.errors.EmptyDataError`, `ValueError`, `TypeError`, `KeyError` | -- |
| `handle_api_errors(default_return, max_retries)` | `requests.RequestException`, `ValueError`, `KeyError` | 自动重试 |
| `with_context(context)` | 所有异常 | 附加上下文信息后 reraise |
| `validate_inputs(**validators)` | -- | 函数参数校验 |

### 线程安全错误统计

模块维护全局错误计数器 `_error_stats`，受 `threading.Lock` 保护：

- `_update_error_stats(func_name, error_type)` -- 每次异常时更新
- `get_error_stats()` -- 返回统计信息的深拷贝
- `reset_error_stats()` -- 重置所有计数

---

## 重试机制

`retry_decorator.py` 提供独立的重试逻辑，替代 `error_handling.py` 中已废弃的 `retry_on_exception()`。

### retry()

```python
@retry(
    max_retries=3,
    delay=1.0,
    backoff=2.0,
    max_delay=None,
    exceptions=(Exception,),
    on_retry=None,      # Callable[[Exception, int], None]
    on_failure=None,     # Callable[[Exception], None]
)
```

支持指数退避（delay *= backoff），可选最大延迟上限。提供 `on_retry` 和 `on_failure` 回调钩子。

### retry_with_fallback()

```python
@retry_with_fallback(
    fallback_value=[],
    max_retries=3,
    delay=1.0,
    backoff=2.0,
    exceptions=(Exception,),
)
```

所有重试耗尽后返回 `fallback_value` 而非抛出异常，适用于非关键路径的降级场景。

### RetryConfig

```python
RetryConfig.DEFAULT_MAX_RETRIES = 3
RetryConfig.DEFAULT_DELAY = 1.0
RetryConfig.DEFAULT_BACKOFF = 2.0
RetryConfig.DEFAULT_MAX_DELAY = 60.0

RetryConfig.DATA_SOURCE_CONFIGS = {
    "eastmoney": {"max_retries": 3, "delay": 1.0, "backoff": 2.0},
    "sina":      {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
    "tencent":   {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
}
```

通过 `RetryConfig.get_config(source)` 获取数据源专属重试参数。

---

## 缓存系统

缓存位于 `shared/cache/` 子包，采用接口-实现分离设计。

### CacheInterface (ABC)

定义于 `cache_interface.py`，声明 7 个抽象方法：

| 方法 | 说明 |
|------|------|
| `get(key)` | 获取缓存，过期返回 None |
| `set(key, value, ttl=3600)` | 写入缓存 |
| `delete(key)` | 删除单条 |
| `clear(pattern=None)` | 按模式或全部清空 |
| `get_stats()` | 统计信息（hits/misses/size） |
| `reset_stats()` | 重置统计 |
| `cleanup()` | 清理过期条目 |

### MemoryCacheBackend

内存字典缓存，支持 LRU 淘汰策略：

- 构造参数：`max_size`（默认 100）
- TTL 基于条目创建时间戳
- 达到 `max_size` 时自动淘汰最旧访问的条目（`_evict_oldest()`）
- 跳过 `None` 值和空 DataFrame 的写入
- 统计命中率：`hits / (hits + misses) * 100`

### DiskCacheBackend

基于 `joblib` 的磁盘持久化缓存：

- 构造参数：`cache_dir`（默认 `data/cache`）、`max_cache_age`（默认 7 天）、`max_cache_size`（默认 500MB）
- 使用 `joblib.dump(compress=3)` 压缩存储
- 文件锁：可选依赖 `filelock`，为并发访问提供保护
- 两阶段清理：先删过期文件，再按大小限制删除最旧文件（保留 80% 容量缓冲）
- 缓存键清洗：移除文件系统非法字符，过长键使用 MD5 哈希截断

### CacheFactory

通过工厂方法创建缓存实例，根据配置选择内存或磁盘后端。

---

## 配置管理

`config_loader.py` 提供 `GlobalConfig` 单例，使用双重检查锁（`threading.Lock`）保证线程安全。

### 加载流程

1. 优先加载 `config/config.yaml` 统一配置文件
2. 若不存在，逐个加载 `settings.yaml`、`markets.yaml`、`brain.yaml`、`data_sources.yaml`、`cache.yaml`、`czsc.yaml`、`indicators.yaml`、`indices.yaml`、`lppl.yaml`、`network.yaml`
3. 附加加载 `trading.yaml`、`factors.yaml`
4. 加载完成后执行 `validate_config()` 验证必要节点

### 访问方式

```python
from uniquant.shared.config_loader import get_config
config = get_config()

# dot-notation 访问
value = config.get("settings.data_lake.path", default="data/lake")
```

### 内置属性

| 属性 | 说明 |
|------|------|
| `ROOT_DIR` | 项目根目录 |
| `DATA_DIR` | 数据目录 |
| `LAKE_DIR` | 数据湖目录 |
| `LOG_DIR` | 日志目录（自动创建） |
| `CACHE_DIR` | 缓存目录（自动创建） |

### 配置校验

`validate_config()` 检查必需节点（base、cache、network、data_sources），并对 brain、risk、lppl 等可选节点发出警告。

---

## 成本模型

`cost_model.py` 是交易成本的唯一真实来源（Single Source of Truth）。所有回测引擎、模拟器和策略必须从此处导入。

### 模块级常量

| 常量 | 值 | 说明 |
|------|----|------|
| `COMMISSION_PCT` | 0.0003 | 佣金率（万3） |
| `STAMP_TAX_PCT` | 0.0005 | 印花税（万5，2024+ 新标准） |
| `STAMP_TAX_PCT_OLD` | 0.001 | 印花税（千1，2024 前旧标准） |
| `MIN_COMMISSION` | 5.0 | 单笔最低佣金 5 元 |
| `SLIPPAGE_PCT` | 0.0005 | 滑点（万5） |
| `COST_BUY` | 0.0003 | 买入成本 = 佣金 |
| `COST_SELL` | 0.0008 | 卖出成本 = 佣金 + 印花税 |

### CostConfig dataclass

```python
@dataclass
class CostConfig:
    buy_fee_pct: float = COMMISSION_PCT
    sell_fee_pct: float = COMMISSION_PCT
    stamp_tax_pct: float = STAMP_TAX_PCT
    slippage_pct: float = SLIPPAGE_PCT
    min_commission: float = MIN_COMMISSION
```

支持两种覆盖方式：
- `CostConfig.from_env()` -- 通过 `LPPL_COST_*` 环境变量覆盖
- `CostConfig.from_yaml(yaml_path)` -- 从 `trading.yaml` 的 `execution` 节读取

属性 `cost_buy` 返回买入费率，`cost_sell` 返回卖出费率（佣金+印花税）。

---

## 滑点模型

`slippage_model.py` 定义滑点估算的抽象基类和两个实现。

### SlippageModel (ABC)

```python
class SlippageModel(ABC):
    @abstractmethod
    def estimate(self, symbol, quantity, direction, price, timestamp) -> float:
        ...
```

### DefaultSlippage

固定滑点模型，始终返回 `0.001`（0.1%）。

### DynamicSlippage

基于流动性和波动率的动态滑点模型：

```
raw = market_impact(quantity, liquidity) + atr * 0.1 + time_premium
slippage = clamp(raw, 0.0001, 0.005)
```

- `_market_impact()` -- 基于成交量占流动性比例计算市场冲击
- `_time_decay()` -- 开盘/收盘半小时增加 0.05% 时间溢价（分钟范围 570-600、870-900）
- 默认流动性 10 亿，默认 ATR 2%

---

## 涨跌停检查

`limit_checker.py` 实现 A 股特有的涨跌停微观结构防御。

### 板块分类

`get_board_type(symbol, name=None)` 根据股票代码前缀和名称识别板块：

| 板块 | 代码前缀 | 涨跌停幅度 |
|------|----------|------------|
| `st` | 名称含 ST/*ST | +/-5% |
| `sci_tech` | 688 | +/-20% |
| `gem` | 300, 301 | +/-20% |
| `beijing` | 8, 4 | +/-30% |
| `main` | 600, 601, 603, 605, 000, 001, 002 | +/-10% |

ST 股优先级最高（先检查名称）。

### 核心函数

`check_limit_status(current_price, pre_close, symbol, name, board_type)` 返回 `LimitStatus` dataclass：

```python
@dataclass
class LimitStatus:
    is_limit_up: bool       # 是否涨停
    is_limit_down: bool     # 是否跌停
    can_buy: bool           # 涨停时不可买入
    can_sell: bool          # 跌停时不可卖出
    board_type: str         # 板块类型
    up_limit_price: float   # 涨停价
    down_limit_price: float # 跌停价
    price_ratio: float      # 当前价/前收盘价
```

使用 `MarketConstants.PRICE_TOLERANCE`（0.001）作为浮点精度容差。

### 辅助函数

- `check_limit_status_dict()` -- 返回字典格式，兼容旧代码
- `validate_trade_action(action, current_price, pre_close, symbol, name)` -- 验证 BUY/SELL/ADD 交易动作是否可行

---

## 其他工具

### logger_factory

`LoggerFactory` 提供统一的日志创建入口。`get_logger(name)` 和 `setup_logger()` 是最常用的函数，确保全系统日志格式一致。

### parallel

`parallel.py` 封装并行执行工具，简化多线程/多进程场景。

### import_state

`import_state.py` 管理模块导入状态，避免循环导入和重复初始化。

### analysis_result

`AnalysisResult` dataclass 及 `AnalysisResultBuilder` 构建器模式，提供标准化的分析结果容器。`AnalysisStatus` 枚举表示分析状态（成功/失败/部分成功等）。

### di_container

`DIContainer` 是一个已废弃（deprecated）的简易依赖注入容器，提供 `register()` / `register_factory()` / `get()` / `has()` / `reset()` / `clear()` 方法。新代码应使用 `ServiceContainer.instance()` 替代。

模块级实例 `container = DIContainer()` 仍可用于向后兼容。
