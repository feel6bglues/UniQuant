# 数据源接入指南

本文档介绍 UniQuant 支持的数据源、数据源架构、配置方式、字段归一化机制以及如何扩展新的数据源。

---

## 支持的数据源

UniQuant 内置支持以下数据源，每个数据源的能力范围和安装方式各有不同：

| 数据源 | 日线 | 实时 | 市值 | 资金流 | 行业/概念 | 分钟线 | 龙虎榜 | 安装命令 |
|--------|------|------|------|--------|-----------|--------|--------|----------|
| TDX (通达信) | 是 | 否 | 否 | 否 | 否 | 否 | 否 | `pip install uniquant[tdx]` |
| AkShare (Sina/Eastmoney 等) | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 已含在基础依赖中 |
| BaoStock | 是 | 否 | 是 | 否 | 否 | 是 | 否 | `pip install uniquant[baostock]` |
| Sina | 是 | 是 | 是 | 否 | 否 | 是 | 否 | 已含在基础依赖中 |
| Tencent | 是 | 是 | 否 | 否 | 否 | 否 | 否 | 已含在基础依赖中 |
| THS (同花顺) | 是 | 是 | 否 | 否 | 否 | 否 | 否 | 已含在基础依赖中 |
| Eastmoney (东方财富) | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 已含在基础依赖中 |

> **说明**: 运行时的数据源由 `DataFetcher` 硬编码初始化（见 `src/uniquant/data/data_fetcher.py`），依次尝试 TDX → BaoStock → Sina → Tencent → THS → Eastmoney，直到首个成功的数据源。配置文件 `config.yaml` 中的 `data_sources.sources` 区块定义了合并型 `StockDataSource`/`IndexDataSource`/`EtfDataSource` 的蓝图，但该路由尚未接入当前运行时 `DataFetcher`。扩展新数据源仍需修改 `DataFetcher` 初始化代码，详见 §添加新数据源。

---

## 数据源架构

UniQuant 的数据源层采用分层设计：**基类 -> 能力协议 -> 适配器 -> 路由器**。

### DataSource 抽象基类

所有数据源必须继承 `DataSource` 并实现以下三个核心方法：

```python
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

class DataSource(ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Source", "")

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线数据"""
        pass

    @abstractmethod
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """获取实时数据"""
        pass

    @abstractmethod
    def fetch_market_cap(self, symbol: str) -> float:
        """获取市值"""
        pass
```

文件位置: `src/uniquant/data/sources/base.py`

### 能力协议 (Capability Protocols)

除了基类定义的核心方法，数据源可以选择性地实现以下能力协议（`Protocol`），以声明额外功能。SourceRouter 通过 `isinstance` 检查来判断某个数据源是否具备特定能力。

| 协议名称 | 方法 | 说明 |
|----------|------|------|
| `HasBasicInfo` | `fetch_basic_info(symbol)` | 股票基本信息 |
| `HasFundFlow` | `fetch_fund_flow(symbol)` | 个股资金流 |
| `HasIndustryList` | `fetch_industry_list()` | 行业列表 |
| `HasConceptList` | `fetch_concept_list()` | 概念列表 |
| `HasSectorFundFlow` | `fetch_sector_fund_flow()` | 板块资金流 |
| `HasHotRanking` | `fetch_hot_ranking()` | 热门排名 |
| `HasMinuteData` | `fetch_minute_data(symbol, period, start_date, end_date, adjust)` | 分钟K线 |
| `HasDragonTiger` | `fetch_dragon_tiger_list(symbol, start_date, end_date)` | 龙虎榜数据 |
| `HasTickData` | `fetch_tick_data(symbol)` | 逐笔成交数据 |

文件位置: `src/uniquant/data/sources/protocols.py`

### StandardAdapter

`StandardAdapter` 是连接 `DataSource` 实例与 `SourceRouter` 的桥梁。它负责：

1. 调用具体数据源的 `fetch_daily()` 获取原始数据
2. 兼容旧版数据源的 `get_data()` 接口
3. 调用 `_standardize_data()` 对列名进行归一化处理

```python
class StandardAdapter(DataSourceAdapter):
    def __init__(self, data_source):
        self.data_source = data_source

    def fetch(self, symbol: str, start_date: str) -> pd.DataFrame:
        end_date = datetime.now().strftime("%Y%m%d")
        raw_data = self.data_source.fetch_daily(symbol, start_date, end_date)
        if raw_data.empty:
            return pd.DataFrame()
        return self._standardize_data(raw_data)
```

文件位置: `src/uniquant/data/managers/standard_adapter.py`

### SourceRouter (数据源路由器)

`SourceRouter` 是数据获取的核心调度器。它管理多个 `DataSourceAdapter` 实例，按优先级顺序尝试获取数据，实现自动故障转移：

- **按优先级遍历**: 按 adapter 列表顺序依次尝试
- **健康检查**: 维护每个数据源的健康状态缓存，跳过不可用的数据源
- **重试与超时**: 每个数据源最多重试 `max_retries` 次，每次请求有超时控制
- **数据完整性验证**: 获取到数据后进行完整性校验
- **指数退避**: 超时错误使用更长延迟，其他错误使用标准延迟

```python
class SourceRouter:
    def __init__(self, adapters: Sequence[DataSourceAdapter]):
        self.adapters = adapters
        self.max_workers = min(3, len(adapters))

    def fetch_data(self, symbol, start_date, max_retries=2) -> pd.DataFrame:
        for i, adapter in enumerate(self.adapters):
            health_status = self.check_source_health(i)
            if health_status != "available":
                continue
            for retry in range(max_retries + 1):
                df = self._fetch_with_timeout(adapter, symbol, start_date, timeout=...)
                if not df.empty and self._validate_data_integrity(df):
                    return df
        return pd.DataFrame()  # 所有数据源均失败
```

文件位置: `src/uniquant/data/managers/source_router.py`

---

## 配置数据源

数据源在 `config/config.yaml` 的 `data_sources` 段中配置。每个数据源包含以下属性：

```yaml
data_sources:
  sources:
    StockDataSource:
      class: data.sources.stock_sources.StockDataSource
      priority: 1          # 优先级 (数字越小越优先)
      timeout: 10          # 单次请求超时(秒)
      enabled: true        # 是否启用
      config:
        retry_times: 3     # 重试次数
        retry_delay: 1.0   # 重试延迟(秒)

    BaoStockSource:
      class: data.sources.baostock.BaostockSource
      priority: 10
      timeout: 10
      enabled: false       # 默认禁用
      config:
        retry_times: 3
        retry_delay: 1.0
```

### 关键配置项

- **priority**: 决定 SourceRouter 的尝试顺序。数字越小，优先级越高。
- **timeout**: 单次数据获取请求的超时时间（秒）。
- **enabled**: 设为 `false` 可禁用该数据源而不删除配置。
- **config.retry_times**: 该数据源的最大重试次数。
- **config.retry_delay**: 重试之间的初始延迟时间（秒）。

### 数据类型路由

`data_sources.data_types` 段定义了不同数据类型（stock、index、sector、etf）应使用哪些数据源：

```yaml
data_sources:
  data_types:
    stock:
      daily:
        supported_sources: [StockDataSource]
        default_source: StockDataSource
        cache_ttl: 3600
      realtime:
        supported_sources: [StockDataSource]
        default_source: StockDataSource
        cache_ttl: 60
    index:
      daily:
        supported_sources: [IndexDataSource]
        default_source: IndexDataSource
        cache_ttl: 3600
```

---

## 字段归一化

不同数据源返回的 DataFrame 列名各不相同。UniQuant 通过 `DataSourceConstants` 定义的列名映射表进行统一归一化，确保下游模块始终使用一致的列名。

### 列名映射表

| 标准字段 | 可识别的别名 |
|----------|-------------|
| `date` | 日期, date, trade_date, 交易日期, 时间, time, dividOperateDate |
| `open` | 开盘, open, 开盘价 |
| `close` | 收盘, close, 收盘价, price |
| `high` | 最高, high, 最高价 |
| `low` | 最低, low, 最低价 |
| `volume` | 成交量, volume, vol, trading_volume |
| `amount` | 成交额, amount, turnover, trading_amount |
| `pct_change` | pct_change, pctChg, 涨跌幅, change_rate, change_pct |
| `preclose` | preclose, pre_close, prev_close, 前收盘, 昨收 |

### 单位转换

不同数据源的成交量和成交额单位不同，`DataSourceConstants` 定义了各数据源的转换系数：

```python
VOLUME_UNITS = {
    "eastmoney": 100,   # 手 -> 股 (1手 = 100股)
    "tencent": 1,       # 股 -> 股
    "sina": 1,          # 股 -> 股
    "ths": 1,           # 股 -> 股
    "baostock": 1,      # 股 -> 股
    "stock": 10000,     # 万股 -> 股
}

AMOUNT_UNITS = {
    "eastmoney": 1,     # 元 -> 元
    "tencent": 1,       # 元 -> 元
    "sina": 1,          # 元 -> 元
    "ths": 1,           # 元 -> 元
    "baostock": 1,      # 元 -> 元
    "stock": 10000,     # 万元 -> 元
}
```

归一化处理由 `StandardAdapter._standardize_data()` 和 `data.utils.normalizer.normalize_column_names()` 共同完成。

---

## 增量更新

### StockDataUpdater

`StockDataUpdater` 负责日常的增量数据更新。它封装了以下流程：

1. **判断是否需要更新**: `needs_update()` 方法检查现有数据的最新日期，与当前日期比较
2. **数据获取**: 通过 SourceRouter 从配置好的数据源获取增量数据
3. **数据清洗**: 调用 DataCleaner 清洗脏数据
4. **数据验证**: 调用 DataValidator 校验数据完整性
5. **复权处理**: 调用 DataAdjuster 进行复权因子调整
6. **存储**: 合并增量数据到本地存储

文件位置: `src/uniquant/data/managers/stock_data_updater.py`

### 更新脚本

项目提供了多个更新脚本：

| 脚本 | 说明 |
|------|------|
| `src/uniquant/data/scripts/update_daily_incremental.py` | 增量更新日线数据 |
| `src/uniquant/data/scripts/update_daily_data_akshare.py` | 通过 AkShare 更新日线数据 |
| `src/uniquant/data/scripts/download_baostock_pro.py` | 使用 BaoStock 批量下载数据 |
| `src/uniquant/data/scripts/download_baostock_factors.py` | 下载 BaoStock 因子数据 |

---

## 添加新数据源

按以下步骤添加新的数据源。

### 第 1 步: 实现 DataSource 基类

在 `src/uniquant/data/sources/` 下创建新文件，例如 `my_source.py`：

```python
from typing import Optional
import pandas as pd
from .base import DataSource
from ...shared.retry_decorator import retry

class MySource(DataSource):
    @property
    def name(self) -> str:
        return "mysource"

    @retry(max_retries=3, delay=1.0, backoff=2.0)
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        # 实现日线数据获取逻辑
        # 返回包含 date, open, high, low, close, volume, amount 列的 DataFrame
        ...

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        # 实现实时数据获取，如不支持可返回空 DataFrame
        return pd.DataFrame()

    def fetch_market_cap(self, symbol: str) -> float:
        # 实现市值获取，如不支持可返回 0.0
        return 0.0
```

### 第 2 步: (可选) 实现能力协议

如果新数据源支持资金流、行业列表等额外能力，可以实现对应的协议：

```python
from .protocols import HasFundFlow, HasIndustryList

class MySource(DataSource):
    # ... 基类方法 ...

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """实现 HasFundFlow 协议"""
        ...

    def fetch_industry_list(self) -> pd.DataFrame:
        """实现 HasIndustryList 协议"""
        ...
```

### 第 3 步: 在 config.yaml 中注册

```yaml
data_sources:
  sources:
    MySource:
      class: data.sources.my_source.MySource
      priority: 20
      timeout: 10
      enabled: true
      config:
        retry_times: 3
        retry_delay: 1.0
```

### 第 4 步: (可选) 配置重试策略

在 `RetryConfig.DATA_SOURCE_CONFIGS` 中为新数据源添加专属重试配置：

```python
DATA_SOURCE_CONFIGS = {
    "mysource": {"max_retries": 3, "delay": 1.0, "backoff": 2.0},
    # ...
}
```

---

## 容错与重试

### 容错初始化

数据获取器在初始化时采用容错模式。即使某些数据源无法正常初始化（例如缺少依赖库、网络不通等），系统也不会崩溃，而是跳过该数据源，使用其余可用数据源继续工作。

### RetryConfig (重试配置)

`RetryConfig` 类提供了统一的重试参数管理：

```python
class RetryConfig:
    # 默认配置
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_DELAY = 1.0
    DEFAULT_BACKOFF = 2.0
    DEFAULT_MAX_DELAY = 60.0

    # 数据源特定配置
    DATA_SOURCE_CONFIGS = {
        "eastmoney": {"max_retries": 3, "delay": 1.0, "backoff": 2.0},
        "sina":      {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
        "tencent":   {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
    }

    @classmethod
    def get_config(cls, source: str) -> dict:
        """获取特定数据源的重试配置"""
        return cls.DATA_SOURCE_CONFIGS.get(source, {
            "max_retries": cls.DEFAULT_MAX_RETRIES,
            "delay": cls.DEFAULT_DELAY,
            "backoff": cls.DEFAULT_BACKOFF,
        })
```

### retry 装饰器

`retry` 装饰器提供指数退避重试机制：

- **max_retries**: 最大重试次数
- **delay**: 初始延迟（秒）
- **backoff**: 退避因子，每次重试后延迟乘以该因子
- **max_delay**: 延迟上限
- **exceptions**: 需要重试的异常类型元组
- **on_retry / on_failure**: 可选的回调函数

`retry_with_fallback` 变体在所有重试失败后返回降级值而非抛出异常，适用于非关键路径。

### 故障转移链

SourceRouter 的故障转移流程如下：

1. 按优先级顺序尝试每个数据源
2. 检查数据源健康状态，跳过已标记为不可用的数据源
3. 对每个数据源执行最多 `max_retries` 次重试
4. 超时时使用更长的延迟（`min(2 * (retry + 1), 10)` 秒）
5. 其他错误使用标准延迟（`min(1 * (retry + 1), 5)` 秒）
6. 重试全部失败后，将该数据源标记为 "unavailable"，转向下一个数据源
7. 所有数据源均失败时返回空 DataFrame

---

## 实时数据

### RealtimeBridge 概述

`RealtimeBridge` 是实时行情桥接引擎，为未来支持分时级别盘中探测提供基础架构。它基于 WebSocket 实现轻量级的实时行情订阅和推送。

**核心数据结构**:

- `TickData`: 逐笔行情数据，包含价格、成交量、成交额、买卖盘口等字段
- `KlineData`: K线数据，支持 1m/5m/15m/30m/60m/D 等周期
- `ConnectionState`: 连接状态枚举（DISCONNECTED、CONNECTING、CONNECTED、RECONNECTING、ERROR）

**基本用法**:

```python
from uniquant.data.sources.realtime_bridge import RealtimeBridge

bridge = RealtimeBridge()
bridge.subscribe("600000.SH", on_tick_callback)
bridge.start()
```

文件位置: `src/uniquant/data/sources/realtime_bridge.py`

> **注意**: RealtimeBridge 目前处于预览阶段，主要用于架构预留。生产环境的实时行情获取仍建议使用各数据源的 `fetch_real_time()` 方法。
