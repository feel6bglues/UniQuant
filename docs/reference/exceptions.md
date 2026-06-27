# 异常体系参考

本文档为 UniQuant 系统中所有异常类的完整参考。异常定义集中于 `src/uniquant/shared/exceptions.py`。原有的 `errors.py` 兼容别名模块已移除。

---

## 异常层次树

```
Exception
  └── AlphaTacticianError                  # 系统基础异常类
        ├── DataError                      # 数据相关错误
        │     ├── DataFetchError           #   数据获取错误
        │     ├── DataValidationError      #   数据验证错误
        │     ├── DataStorageError         #   数据存储错误
        │     │     └── DatabaseConnectionError  # 数据库连接错误
        │     ├── DataAccessError          #   数据访问错误
        │     └── CacheError              #   缓存相关错误
        │
        ├── AnalysisError                  # 分析相关错误
        │     ├── LPPLFitError            #   LPPL 模型拟合错误
        │     ├── CZSCEngineError         #   缠论引擎错误
        │     └── EngineError             #   引擎错误
        │
        ├── RiskError                      # 风险管理相关错误
        │     ├── PositionSizingError     #   仓位计算错误
        │     ├── EVTRiskError            #   极值风险计算错误
        │     └── RiskCalculationError    #   风险计算错误
        │
        ├── ServiceError                   # 服务层错误
        │     ├── AnalysisServiceError    #   分析服务错误
        │     ├── DataServiceError        #   数据服务错误
        │     ├── PortfolioServiceError   #   组合服务错误
        │     └── DependencyError         #   依赖项错误
        │
        ├── UIError                        # UI 相关错误
        │     ├── DashboardError          #   仪表盘错误
        │     └── VisualizationError      #   可视化错误
        │
        ├── LPPLException                  # LPPL 独立异常
        │     ├── DataNotFoundError       #   数据未找到
        │     └── ComputationError        #   计算错误
        │
        ├── WyckoffError                   # Wyckoff 异常
        │     ├── BCNotFoundError         #   BC (Buying Climax) 未找到
        │     ├── InvalidInputDataError   #   输入数据无效
        │     ├── ImageProcessingError    #   图像处理错误
        │     ├── FusionConflictError     #   融合冲突错误
        │     └── RuleEngineError         #   规则引擎错误
        │
        ├── ConfigurationError             # 配置错误
        ├── OperationTimeoutError          # 操作超时错误
        ├── ValidationError                # 验证错误
        └── BacktestError                  # 回测相关错误
```

---

## DataError 分支

数据处理全链路的异常覆盖，从获取、验证、存储到访问和缓存。

### AlphaTacticianError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:1` |
| 父类 | `Exception` |
| 说明 | 系统基础异常类，所有 UniQuant 自定义异常的根类 |

### DataError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:5` |
| 父类 | `AlphaTacticianError` |
| 说明 | 数据相关错误的基类 |

### DataFetchError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:9` |
| 父类 | `DataError` |
| 说明 | 数据获取错误，包括网络请求失败、API 调用失败等场景 |

### DataValidationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:13` |
| 父类 | `DataError` |
| 说明 | 数据验证错误，数据格式不正确或完整性检查未通过时抛出 |

### DataStorageError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:17` |
| 父类 | `DataError` |
| 说明 | 数据存储错误，文件 I/O 或数据库操作失败时抛出 |

### DatabaseConnectionError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:21` |
| 父类 | `DataStorageError` |
| 说明 | 数据库连接错误 |

### DataAccessError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:25` |
| 父类 | `DataError` |
| 说明 | 数据访问错误 |

### CacheError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:29` |
| 父类 | `DataError` |
| 说明 | 缓存相关错误 |

---

## AnalysisError 分支

分析引擎相关的异常，涵盖 LPPL 拟合、缠论引擎和通用引擎错误。

### AnalysisError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:33` |
| 父类 | `AlphaTacticianError` |
| 说明 | 分析相关错误的基类 |

### LPPLFitError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:37` |
| 父类 | `AnalysisError` |
| 说明 | LPPL 模型拟合错误，优化器收敛失败或参数越界时抛出 |

### CZSCEngineError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:41` |
| 父类 | `AnalysisError` |
| 说明 | 缠论引擎错误 |

### EngineError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:45` |
| 父类 | `AnalysisError` |
| 说明 | 通用引擎错误 |

---

## RiskError 分支

风险管理模块的异常。

### RiskError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:49` |
| 父类 | `AlphaTacticianError` |
| 说明 | 风险管理相关错误的基类 |

### PositionSizingError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:53` |
| 父类 | `RiskError` |
| 说明 | 仓位计算错误 |

### EVTRiskError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:57` |
| 父类 | `RiskError` |
| 说明 | 极值理论（EVT）风险计算错误 |

### RiskCalculationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:61` |
| 父类 | `RiskError` |
| 说明 | 风险计算错误 |

---

## ServiceError 分支

服务层异常。

### ServiceError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:65` |
| 父类 | `AlphaTacticianError` |
| 说明 | 服务层错误的基类 |

### AnalysisServiceError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:69` |
| 父类 | `ServiceError` |
| 说明 | 分析服务错误 |

### DataServiceError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:73` |
| 父类 | `ServiceError` |
| 说明 | 数据服务错误 |

### PortfolioServiceError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:77` |
| 父类 | `ServiceError` |
| 说明 | 组合服务错误 |

### DependencyError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:101` |
| 父类 | `ServiceError` |
| 说明 | 依赖项错误 |

---

## UIError 分支

用户界面相关异常。

### UIError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:81` |
| 父类 | `AlphaTacticianError` |
| 说明 | UI 相关错误的基类 |

### DashboardError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:85` |
| 父类 | `UIError` |
| 说明 | 仪表盘错误 |

### VisualizationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:89` |
| 父类 | `UIError` |
| 说明 | 可视化错误 |

---

## 独立异常

不属于以上分支树、直接继承自 `AlphaTacticianError` 的异常。

### ConfigurationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:93` |
| 父类 | `AlphaTacticianError` |
| 说明 | 配置错误，配置文件格式错误或缺少必要配置项时抛出 |

### OperationTimeoutError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:97` |
| 父类 | `AlphaTacticianError` |
| 说明 | 操作超时错误 |

### ValidationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:105` |
| 父类 | `AlphaTacticianError` |
| 说明 | 通用验证错误 |

### BacktestError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:109` |
| 父类 | `AlphaTacticianError` |
| 说明 | 回测相关错误 |

---

## LPPL 异常

来自 LPPL 独立模块的异常，统一归入 `AlphaTacticianError` 层次体系。

### LPPLException

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:114` |
| 父类 | `AlphaTacticianError` |
| 说明 | LPPL 模块基础异常 |

### DataNotFoundError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:115` |
| 父类 | `LPPLException` |
| 说明 | 所需数据未找到 |

### ComputationError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:116` |
| 父类 | `LPPLException` |
| 说明 | 计算过程错误 |

---

## Wyckoff 异常

Wyckoff 分析模块的异常，覆盖 BC 检测、输入验证、图像处理、融合引擎和规则引擎。

### WyckoffError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:118` |
| 父类 | `AlphaTacticianError` |
| 说明 | Wyckoff 模块基础异常 |

### BCNotFoundError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:119` |
| 父类 | `WyckoffError` |
| 说明 | Buying Climax（卖出高潮）未在数据中找到 |

### InvalidInputDataError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:120` |
| 父类 | `WyckoffError` |
| 说明 | 输入数据无效，格式或内容不满足 Wyckoff 分析要求 |

### ImageProcessingError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:121` |
| 父类 | `WyckoffError` |
| 说明 | 图像处理错误，Wyckoff 图表生成或处理失败时抛出 |

### FusionConflictError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:122` |
| 父类 | `WyckoffError` |
| 说明 | 融合冲突错误，多信号源融合时出现矛盾 |

### RuleEngineError

| 属性 | 说明 |
|------|------|
| 定义位置 | `src/uniquant/shared/exceptions.py:123` |
| 父类 | `WyckoffError` |
| 说明 | 规则引擎错误 |

---

## 已移除的向后兼容别名

原有的 errors.py 兼容模块已移除。旧别名映射：

| 旧名称 | 实际映射 |
|--------|----------|
| `AlphaError` | `AlphaTacticianError` |
| `DataError` | `DataFetchError` |
| `EngineError` | `EngineError` |

> 所有异常统一从 `src/uniquant/shared/exceptions.py` 导入。

---

## LPPL 核心模块附加常量

`src/uniquant/brain/lppl/core.py` 中定义了以下与异常处理相关的辅助类型（非异常类，但用于拟合失败追踪）：

### LPPL_RMSE_THRESHOLD

| 属性 | 说明 |
|------|------|
| 类型 | `float` |
| 值 | `10.0` |
| 说明 | LPPL 拟合 RMSE 拒绝阈值 |

### FitFailureReason

拟合失败原因的字面量类型（`Literal`），可能的值：

| 值 | 说明 |
|------|------|
| `"insufficient_data"` | 数据量不足 |
| `"non_positive_price"` | 存在非正价格 |
| `"nan_or_inf"` | 存在 NaN 或无穷值 |
| `"constant_price"` | 价格无变化（常数价格） |
| `"optimizer_failed"` | 优化器失败 |
| `"numeric_error"` | 数值计算错误 |

### track_fit_failure 函数

```python
def track_fit_failure(
    reason: FitFailureReason,
    stats: Optional[FitFailureStats] = None,
    context: str = ""
) -> None
```

追踪拟合失败事件，将失败原因计数写入 `stats` 字典并记录调试日志。

---

## 使用示例

### 基本异常处理

```python
from uniquant.shared.exceptions import DataFetchError, DataValidationError

try:
    data = fetch_stock_data("000001.SZ")
except DataFetchError as e:
    logger.error(f"数据获取失败: {e}")
except DataValidationError as e:
    logger.error(f"数据验证失败: {e}")
```

### 使用 handle_errors 装饰器

`handle_errors` 装饰器定义在 `src/uniquant/shared/error_handling.py` 中，提供统一的错误捕获、日志记录和默认返回值机制。

```python
import logging
from uniquant.shared.error_handling import handle_errors
from uniquant.shared.exceptions import DataFetchError, CacheError

@handle_errors(
    DataFetchError, CacheError,
    default_return=None,
    log_level=logging.ERROR,
    reraise=False,
    error_type="data_fetch",
)
def get_stock_price(symbol: str):
    """获取股票价格，出错时返回 None"""
    ...
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `*expected_exceptions` | `Type[Exception]` | (必填) | 预期捕获的异常类型（可变参数） |
| `default_return` | `Any` | `None` | 异常发生时的默认返回值 |
| `log_level` | `int` | `logging.ERROR` | 日志级别 |
| `reraise` | `bool` | `False` | 是否重新抛出异常 |
| `error_type` | `str` | `"unknown"` | 错误类型标识（用于统计） |
| `context` | `Optional[Dict]` | `None` | 附加上下文信息 |

**处理逻辑：**

1. 首先尝试匹配 `expected_exceptions` 中指定的异常类型
2. 然后匹配所有 `AlphaTacticianError` 子类
3. 最后兜底捕获所有未预期的 `Exception`
4. 每次捕获都会更新线程安全的错误统计，并记录包含函数名、参数和上下文的详细日志
5. 根据 `reraise` 参数决定是重新抛出还是返回 `default_return`

### 使用 retry_on_exception 装饰器

```python
from uniquant.shared.error_handling import retry_on_exception
from uniquant.shared.exceptions import DataFetchError

@retry_on_exception(
    max_retries=3,
    backoff=2.0,
    retry_exceptions=(DataFetchError, ConnectionError),
    jitter=True,
    max_wait_time=30.0,
)
def fetch_with_retry(url: str):
    """带自动重试的数据获取"""
    ...
```

### 使用专用装饰器

系统还提供了面向特定场景的便捷装饰器：

```python
from uniquant.shared.error_handling import (
    handle_network_errors,
    handle_file_errors,
    handle_data_errors,
    handle_api_errors,
)

# 网络操作 - 自动捕获 requests/urllib3 异常并重试
@handle_network_errors(default_return=None, max_retries=3)
def download_data(url):
    ...

# 文件操作 - 自动捕获 FileNotFoundError/PermissionError 等
@handle_file_errors(default_return=None)
def read_config(path):
    ...

# 数据处理 - 自动捕获 pandas/ValueError/TypeError/KeyError
@handle_data_errors(default_return=None)
def process_dataframe(df):
    ...

# API 调用 - 自动捕获 requests 异常并重试
@handle_api_errors(default_return=None, max_retries=3)
def call_api(endpoint):
    ...
```

### 使用上下文装饰器

```python
from uniquant.shared.error_handling import with_context

@with_context({"module": "risk", "operation": "var_calculation"})
def calculate_var(returns):
    """附加上下文信息的错误处理，异常会被重新抛出"""
    ...
```

### 使用输入验证装饰器

```python
from uniquant.shared.error_handling import validate_inputs

@validate_inputs(
    symbol=lambda s: isinstance(s, str) and len(s) > 0,
    days=lambda d: isinstance(d, int) and d > 0,
)
def analyze_stock(symbol: str, days: int = 30):
    """自动验证输入参数，不满足条件时抛出 ValueError"""
    ...
```

### 错误统计查询

```python
from uniquant.shared.error_handling import get_error_stats, reset_error_stats

# 获取所有函数的错误统计
stats = get_error_stats()
# 返回格式: {"function_name": {"error_type": count, ...}, ...}

# 重置统计
reset_error_stats()
```

### 捕获 Wyckoff 异常

```python
from uniquant.shared.exceptions import WyckoffError, BCNotFoundError

try:
    result = wyckoff_engine.analyze(data)
except BCNotFoundError:
    logger.warning("未找到 Buying Climax，跳过 Wyckoff 分析")
except WyckoffError as e:
    logger.error(f"Wyckoff 分析失败: {e}")
```

### 捕获 LPPL 异常

```python
from uniquant.shared.exceptions import LPPLException, DataNotFoundError, ComputationError

try:
    bubble_result = lppl_engine.detect(symbol)
except DataNotFoundError:
    logger.warning("LPPL 分析所需数据不足")
except ComputationError as e:
    logger.error(f"LPPL 计算错误: {e}")
except LPPLException as e:
    logger.error(f"LPPL 异常: {e}")
```
