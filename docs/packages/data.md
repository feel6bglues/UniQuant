# data -- 数据层

> **状态:** 🔴 待迁移 | **当前文件:** 0/40+ | **迁移阶段:** Phase 1B

data 包是 UniQuant 的数据基础设施，约 14K LOC，包含 8 个子包：

| 子包 | 职责 |
|------|------|
| `sources` | 数据源基类、协议定义、具体数据源实现 |
| `managers` | 数据源路由、标准适配器、元数据/日历/复权因子管理 |
| `pipeline` | 数据验证、清洗、复权调整 |
| `lake` | Parquet + Snappy 存储管理 |
| `services` | 数据导入服务（日线/分钟/指数/财务） |
| `parsers` | TDX 数据解析器 |
| `utils` | AkShare 封装、JS 执行器、列名标准化、智能因子计算 |
| `sources/realtime_bridge.py` | 实时行情桥接引擎 |

公开导出（延迟导入，避免循环依赖）：

```python
__all__ = ["DataFetcher", "DataLake", "DataPipeline", "LPPLDataService"]
```

其中 `DataLake` 和 `DataPipeline` 已弃用，分别由 `StorageManager` 和 `DataFetcher` 替代。

---

## 数据源架构

### DataSource 抽象基类

**`DataSource`**（`sources/base.py`）定义所有数据源的最小接口：

```python
class DataSource(ABC):
    @property
    def name(self) -> str: ...

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_market_cap(self, symbol: str) -> float: ...
```

### 能力协议

`sources/protocols.py` 使用 Python `Protocol` 定义数据源的可选能力。数据源按需实现以下协议：

| 协议 | 方法 | 说明 |
|------|------|------|
| `HasBasicInfo` | `fetch_basic_info(symbol)` | 股票基本信息 |
| `HasFundFlow` | `fetch_fund_flow(symbol)` | 资金流数据 |
| `HasIndustryList` | `fetch_industry_list()` | 行业列表 |
| `HasConceptList` | `fetch_concept_list()` | 概念列表 |
| `HasSectorFundFlow` | `fetch_sector_fund_flow()` | 板块资金流 |
| `HasHotRanking` | `fetch_hot_ranking()` | 热门排名 |
| `HasMinuteData` | `fetch_minute_data(symbol, period, ...)` | 分钟级 K 线 |
| `HasDragonTiger` | `fetch_dragon_tiger_list(symbol, ...)` | 龙虎榜 |
| `HasTickData` | `fetch_tick_data(symbol)` | 逐笔成交 |

### 具体数据源

| 数据源类 | 文件 | 说明 |
|----------|------|------|
| `TdxSource` | `sources/tdx.py` | 通达信本地数据（最快，优先级最高） |
| `BaostockSource` | `sources/baostock.py` | BaoStock 开源接口 |
| `SinaSource` | `sources/sina.py` | 新浪财经 |
| `TencentSource` | `sources/tencent.py` | 腾讯股票 |
| `ThsSource` | `sources/ths.py` | 同花顺 |
| `EastmoneySource` | `sources/eastmoney.py` | 东方财富（可选） |

### SourceRouter -- 数据源路由中心

**`SourceRouter`**（`managers/source_router.py`）负责多数据源故障转移和竞速模式。

```python
SourceRouter(adapters: Sequence[DataSourceAdapter])
```

#### `fetch_data(symbol: str, start_date: str, max_retries=2) -> pd.DataFrame`

按优先级顺序尝试各数据源，单个源失败时自动切换到下一个。

- 每个数据源最多重试 `max_retries` 次。
- 带超时控制：`_fetch_with_timeout()` 使用 `ThreadPoolExecutor` 和 `NetworkConstants.SOCKET_TIMEOUT`。
- 数据完整性校验：`_validate_data_integrity()` 检查必要列（`date, open, high, low, close, volume`）、日期类型、数据量。
- 健康状态管理：失败的数据源标记为 `unavailable`，5 分钟后自动恢复。

#### `fetch_data_with_race(symbol: str, start_date: str) -> pd.DataFrame`

竞速模式：同时请求多个健康数据源，谁快用谁。使用 `concurrent.futures.ThreadPoolExecutor` 并发，最多 3 个线程。

#### 健康状态

| 方法 | 说明 |
|------|------|
| `check_source_health(source_index)` | 检查数据源状态 |
| `update_source_health(source_index, status)` | 更新状态 |
| `get_source_health_report()` | 健康报告（总数/可用数/详情） |
| `get_healthy_sources_count()` | 健康数据源计数 |

### StandardAdapter

**`StandardAdapter`**（`managers/standard_adapter.py`）将各数据源统一适配为 `DataSourceAdapter` 接口，供 `SourceRouter` 使用。

---

## DataFetcher 数据获取器

**`DataFetcher`**（`data_fetcher.py`）-- 数据层的总指挥，协调数据源、管道、存储和各管理器。

```python
DataFetcher(data_dir: str = "./data")
```

### 容错初始化

初始化时逐个尝试创建数据源实例（`TdxSource, BaostockSource, SinaSource, ThsSource, TencentSource`），单个失败不影响其他源。失败的数据源会被跳过并记录告警。

### 初始化组件

| 组件 | 类 | 职责 |
|------|------|------|
| `storage_manager` | `StorageManager` | Parquet 文件读写 |
| `data_sources` | `List[DataSource]` | 活跃数据源列表 |
| `adapters` | `List[StandardAdapter]` | 数据源适配器 |
| `source_router` | `SourceRouter` | 数据源路由 |
| `data_cleaner` | `DataCleaner` | 数据清洗 |
| `data_validator` | `DataValidator` | 数据验证 |
| `data_adjuster` | `DataAdjuster` | 前/后复权 |
| `metadata_manager` | `StockMetadataManager` | 股票元数据 |
| `calendar_manager` | `TradeCalendarManager` | 交易日历 |
| `adjust_factor_manager` | `AdjustFactorManager` | 复权因子 |
| `market_coordinator` | `MarketDataCoordinator` | 指数/ETF/行业数据 |
| `stock_updater` | `StockDataUpdater` | 增量更新 |

### 主要方法

#### 行情数据获取

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_price` | `(symbol, adjust="")` | 获取个股数据，支持 `qfq`/`hfq` 复权。带 `@lru_cache(maxsize=200)` |
| `fetch_stock_daily` | `(symbol, start_date, end_date, adjust="qfq")` | 个股日线（按日期范围筛选） |
| `fetch_stocks_daily` | `(symbols, start_date, end_date)` | 批量获取多股日线 |
| `fetch_index_daily` | `(symbol, start_date, end_date)` | 指数日线（委托 `MarketDataCoordinator`） |
| `fetch_etf_daily_robust` | `(symbol, start_date, end_date)` | 多源 ETF 数据 |
| `fetch_sector_daily` | `(sector_name, start_date, end_date)` | 行业板块指数日线 |
| `fetch_history` | `(symbol, start_date, end_date)` | 通用入口：自动识别指数/个股 |
| `fetch_for_brain` | `(symbol)` | 为 brain 模块准备数据包 |

#### 元数据与日历

| 方法 | 说明 |
|------|------|
| `fetch_all_stock_codes(force_update)` | 全量股票代码和名称 |
| `fetch_stock_info()` | 股票代码->名称映射 |
| `is_valid_symbol(symbol)` | 验证股票代码有效性 |
| `validate_symbols(symbols)` | 批量验证 |
| `generate_trade_calendar(year)` | 生成交易日历 |
| `is_trading_day(date)` | 判断是否为交易日 |
| `get_trade_calendar(start, end)` | 获取日期范围内的交易日历 |

#### 复权因子

| 方法 | 说明 |
|------|------|
| `get_adjust_factors(symbol, gbbq_path)` | 获取复权因子 |
| `convert_gbbq_to_fq(gbbq_path)` | 通达信 gbbq 文件转复权因子 |

#### 数据维护

| 方法 | 说明 |
|------|------|
| `update_all(symbols)` | 批量增量更新 |
| `clean_data(symbol)` | 清理重建数据 |
| `get_source_health_report()` | 数据源健康报告 |

### 数据获取流程

```
get_price(symbol, adjust)
  -> storage_manager.read_local_raw(symbol)       # 读本地缓存
  -> _needs_update(df)?                            # 检查是否需要更新
     -> stock_updater.update_stock(symbol, df_old) # 增量更新
  -> data_adjuster.apply_adjustment(symbol, df, method)  # 复权
  -> return df
```

---

## 数据管道

### DataValidator -- 数据验证器

**`DataValidator`**（`pipeline/data_validator.py`）执行多层验证：

1. **必要列检查**: `date, code, open, high, low, close, volume, amount`。
2. **智能修复**: 如果 `High < Low`，自动交换。
3. **严格校验**: 修复后再次验证 `High >= Low`。
4. **异常值过滤**: 检测跌幅超过 99% 的异常记录。
5. **价格逻辑**: 确保 `High >= Open/Close`，`Low <= Open/Close`；不满足时自动修复。
6. **日期连续性**: 超过 14 天的间隔记录告警（股市周末/节假日休市属正常）。

```python
validator = DataValidator()
is_valid = validator.validate(df)  # -> bool
```

### DataCleaner -- 数据清洗器

**`DataCleaner`**（`pipeline/data_cleaner.py`）执行清洗流水线：

1. **列名标准化**: 所有列名转小写。
2. **类型转换**: `open, high, low, close, volume` 转为数值类型，无效值填 0。
3. **停牌处理**: `volume` 缺失值填 0。
4. **缺失/重复**: 删除缺少 `date` 或 `close` 的行；按日期去重（保留最后一条）。
5. **成交额补全**: 如无 `amount` 列，用 `close * volume` 计算。
6. **排序重建索引**: 按日期排序并重置索引。

```python
cleaner = DataCleaner()
df_clean = cleaner.clean(df)  # -> pd.DataFrame
```

### DataAdjuster -- 复权调整器

**`DataAdjuster`**（`pipeline/data_adjuster.py`）支持前复权（`qfq`）和后复权（`hfq`）。从 `StorageManager` 读取复权因子数据，对 OHLC 价格进行调整。

---

## 存储层

### StorageManager -- 存储管理器

**`StorageManager`**（`lake/storage_manager.py`）负责所有文件系统操作。

```python
StorageManager(data_dir: str = "./data")
```

### 目录结构

```
{data_dir}/
  lake/
    quotes/
      daily/          # 日线 Parquet 文件
      1mins/          # 1分钟 K 线
      5mins/          # 5分钟 K 线
    index/            # 指数数据
  factors/            # 复权因子
  state/              # FSM 状态持久化
  all_stock_codes.csv # 全量股票代码
```

### 存储格式

- 格式：Apache Parquet
- 压缩：Snappy（`df.to_parquet(path, compression="snappy")`）
- 并发安全：所有写操作使用 `filelock.FileLock`
- 原子写入：先写 `.tmp` 文件，再原子 `rename`

### 核心方法

| 方法 | 说明 |
|------|------|
| `write_parquet(file_path, df, overwrite)` | 写入 Parquet 文件（带 FileLock） |
| `read_parquet(file_path, normalize=True)` | 读取 Parquet 文件（可选列名标准化） |
| `read_local_raw(symbol)` | 读取本地原始日线数据（自动尝试多种代码格式） |
| `read_local_factor(symbol)` | 读取本地复权因子数据 |
| `save_data(symbol, df)` | 原子写入日线数据 |
| `save_factor(symbol, df)` | 原子写入复权因子 |
| `read_data(symbol, data_type)` | 通用读取（支持 daily/factor/index/1mins/5mins） |
| `write_data(symbol, df, data_type)` | 通用写入 |
| `batch_read_data(symbols, data_type)` | 批量读取 |
| `get_symbols()` | 获取所有已存储的股票代码 |
| `get_stock_metadata(code)` | 获取股票元数据 |

### 股票代码标准化

`_normalize_stock_code()` 将各种输入格式统一为 `XXXXXX.SH/SZ/BJ`：

| 输入格式 | 标准化结果 |
|----------|-----------|
| `sh.600000` | `600000.SH` |
| `sz.000001` | `000001.SZ` |
| `600000.SH` | `600000.SH`（已标准化） |
| `600000` | `600000.SH`（根据前缀推断） |
| `00XXXX` / `30XXXX` | `XXXXXX.SZ` |
| `83XXXX` / `87XXXX` / `43XXXX` | `XXXXXX.BJ` |

---

## 数据管理器

`managers` 子包包含多个专职管理器：

| 管理器 | 文件 | 职责 |
|--------|------|------|
| `SourceRouter` | `source_router.py` | 数据源路由与故障转移（详见上文） |
| `StandardAdapter` | `standard_adapter.py` | 数据源接口适配 |
| `StockMetadataManager` | `stock_metadata_manager.py` | 股票元数据（名称/板块/上市日期/退市日期/类型/状态） |
| `TradeCalendarManager` | `trade_calendar_manager.py` | 交易日历生成与查询 |
| `AdjustFactorManager` | `adjust_factor_manager.py` | 复权因子管理（含通达信 gbbq 转换） |
| `MarketDataCoordinator` | `market_data_coordinator.py` | 指数/ETF/行业板块数据获取 |
| `StockDataUpdater` | `stock_data_updater.py` | 增量数据更新 |
| `BaostockCacheManager` | `baostock_cache_manager.py` | BaoStock 连接缓存 |
| `CacheManager` | `cache_manager.py` | 通用缓存管理 |
| `DataNormalizer` | `data_normalizer.py` | 数据标准化 |
| `FactorManager` | `factor_manager.py` | 复权因子文件管理 |
| `TdxUpdater` | `tdx_updater.py` | 通达信数据更新 |

### MarketDataCoordinator

**`MarketDataCoordinator`** 封装指数、ETF、行业数据获取：

```python
MarketDataCoordinator(data_fetcher)
```

| 方法 | 说明 |
|------|------|
| `fetch_index_daily(symbol, start_date, end_date)` | 通过 AkShare 获取指数日线 |
| `fetch_etf_daily_robust(symbol, start_date, end_date)` | ETF 日线（委托 DataFetcher） |
| `fetch_industry_concept_data()` | 行业概念数据 |
| `fetch_sector_daily(sector_name, start_date, end_date)` | 行业板块指数日线（内置行业->指数代码映射） |

内置行业映射表涵盖：金融、医药、能源、材料、工业、可选消费、主要消费、信息技术、电信业务、公用事业及其沪深 300 细分指数。

---

## 数据服务

`services` 子包提供各类数据导入服务：

| 服务 | 文件 | 职责 |
|------|------|------|
| `DataImporter` | `data_importer.py` | CSV/TDX 数据导入为 Parquet |
| `LPPLDataService` | `lppl_data_service.py` | LPPL 分析所需数据准备 |
| -- | `import_financial.py` | 财务数据导入 |
| -- | `import_index.py` | 指数数据导入 |
| -- | `import_1min.py` | 1 分钟 K 线导入 |
| -- | `import_5min.py` | 5 分钟 K 线导入 |

### DataImporter

**`DataImporter`** -- 将通达信 TDX 本地文件和 CSV 数据转换为系统可用的 Parquet 格式。

```python
DataImporter(data_dir="./data", tdx_path=None)
```

| 组件 | 说明 |
|------|------|
| `storage_manager` | Parquet 读写 |
| `data_adjuster` | 复权调整 |
| `tdx_parser` | TDX 二进制文件解析（`TDXParser`） |
| `file_fingerprints` | 文件指纹记录，支持增量更新 |
| `fingerprint_lock` | 线程锁，解决并发访问 |

支持通达信 `vipdoc` 目录下的日线、分钟线数据解析和 `gbbq` 除权除息数据转换。

---

## 实时数据

### RealtimeBridge -- 实时行情桥接引擎

**`RealtimeBridge`**（`sources/realtime_bridge.py`）为日后分时级盘中探测铺路，提供 WebSocket 轻量级桥接。

```python
bridge = RealtimeBridge(
    data_source=None,           # DataSourceAdapter 实例，默认 MockDataSource
    auto_reconnect=True,        # 自动重连
    reconnect_interval=5.0,     # 重连间隔（秒）
)
```

### 数据结构

**`TickData`** -- Tick 数据：

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | str | 股票代码 |
| `timestamp` | datetime | 时间戳 |
| `price` | float | 当前价 |
| `volume` | int | 成交量 |
| `turnover` | float | 成交额 |
| `bid_price` / `bid_volume` | float / int | 买一价/量 |
| `ask_price` / `ask_volume` | float / int | 卖一价/量 |
| `open` / `high` / `low` / `pre_close` | float | OHLC + 前收盘 |

**`KlineData`** -- K 线数据：`symbol, timestamp, interval, open, high, low, close, volume, turnover`。

### 连接状态

**`ConnectionState`** 枚举：`DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `ERROR`。

### 使用方式

```python
bridge = RealtimeBridge()
bridge.subscribe("600000.SH", on_tick_callback)
bridge.on_tick(global_tick_handler)
bridge.on_error(error_handler)
bridge.start()   # 在守护线程中启动异步事件循环
# ...
bridge.stop()
```

**`RealtimeBridgeBuilder`** 提供链式构建：

```python
bridge = (
    RealtimeBridgeBuilder()
    .with_data_source(my_source)
    .with_auto_reconnect(True, interval=3.0)
    .on_tick(handler)
    .build()
)
```

### DataSourceAdapter 基类

自定义数据源需实现 `DataSourceAdapter` 抽象类：

| 方法 | 说明 |
|------|------|
| `connect()` | 建立连接 |
| `disconnect()` | 断开连接 |
| `subscribe(symbols)` | 订阅 |
| `unsubscribe(symbols)` | 取消订阅 |
| `get_tick(symbol)` | 获取最新 Tick |

内置 `MockDataSource` 用于测试。

---

## 工具模块

`utils` 子包提供数据层辅助工具：

| 模块 | 说明 |
|------|------|
| `akshare_wrapper.py` | AkShare 库的封装（指数日线获取等） |
| `akshare_market_service.py` | AkShare 市场数据服务 |
| `akshare_reference_service.py` | AkShare 参考数据服务 |
| `js_executor.py` | JavaScript 执行器（用于部分数据源的加密解密） |
| `normalizer.py` | 列名标准化（`normalize_column_names` 函数） |
| `smart_factor_calculator.py` | 智能因子计算器 |
| `request_utils.py` | HTTP 请求工具 |

### normalizer -- 列名标准化

`normalize_column_names(df)` 函数将各数据源的中/英文列名映射为统一标准名：

```python
from uniquant.data.utils.normalizer import normalize_column_names
df = normalize_column_names(df)
```

内部调用 `DataSourceConstants` 中定义的别名列表进行映射。

---

## 字段映射

`DataSourceConstants`（`shared/constants/data.py`）定义了所有字段名别名映射：

| 标准字段 | 别名列表 |
|----------|----------|
| `date` | 日期, date, trade_date, 交易日期, 时间, time, dividOperateDate |
| `open` | 开盘, open, 开盘价 |
| `close` | 收盘, close, 收盘价, price |
| `high` | 最高, high, 最高价 |
| `low` | 最低, low, 最低价 |
| `volume` | 成交量, volume, vol, trading_volume |
| `amount` | 成交额, amount, turnover, trading_amount |
| `change_rate` | pct_change, pctChg, 涨跌幅, change_rate, change_pct |
| `change_amount` | 涨跌额, price_change, change_amount |
| `preclose` | preclose, pre_close, prev_close, 前收盘, 昨收 |
| `qfq_factor` | qfq_factor, foreAdjustFactor, 前复权因子 |
| `hfq_factor` | hfq_factor, backAdjustFactor, 后复权因子 |

### 单位转换

不同数据源的成交量和成交额单位不同，`DataSourceConstants` 定义了转换系数：

| 数据源 | 成交量单位 | 成交额单位 |
|--------|-----------|-----------|
| eastmoney | 手（x100 -> 股） | 元 |
| tencent | 股 | 元 |
| sina | 股 | 元 |
| ths | 股 | 元 |
| baostock | 股 | 元 |
| stock（通达信） | 万股（x10000 -> 股） | 万元（x10000 -> 元） |

### 股票代码前缀

| 前缀 | 含义 |
|------|------|
| `000`, `399`, `880` | 指数代码 |
| `6`, `5` | 上海股票 |
| `0`, `3` | 深圳股票 |
