# R1-1A: Data I/O Audit

> 审计员: R1-Data I/O Auditor  
> 审计时间: 2026-06-06  
> 审计范围: `src/uniquant/data/` 核心 5 文件  
> 审计文件: data_pipeline_service.py, data_adjuster.py, data_cleaner.py, data_validator.py, storage_manager.py

---

## 发现

### [CRITICAL] DataPipelineService.process() 类型错误 — validate() 返回 bool 赋给 df，下游必崩

- 文件: `src/uniquant/data/data_pipeline_service.py:19`
- 代码片段:
  ```python
  def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
      df = self.cleaner.clean_stock_daily(df)       # 返回 DataFrame ✓
      df = self.validator.validate(df)               # 返回 bool！✗
      df = self.adjuster.apply_adjustment(symbol, df, method=adjust)  # df 现在是 bool
      return df
  ```
- 问题描述: `DataValidator.validate()` 的返回类型声明为 `-> bool`（`data_validator.py:11`），实际返回 `True` 或 `False`。但 `data_pipeline_service.py:19` 将其返回值赋给 `df`，随后第 20 行将 `df`（此时为 `bool`）传给 `apply_adjustment()`。`apply_adjustment()` 第 164 行执行 `df_raw.empty`，而 `bool` 对象没有 `.empty` 属性，运行时必抛 `AttributeError: 'bool' object has no attribute 'empty'`。无论 validate 返回 True 还是 False，流程均崩溃。
- 影响: **DataPipelineService.process() 完全不可用**。`DataFetcher.get_price()`（`data_fetcher.py:112`）调用 `self.pipeline.process()`，整个数据获取链路在 clean -> validate -> adjust 流程中崩溃。对比其他调用方均正确使用 `if not self.validator.validate(df):` 作为条件判断（`stock_data_updater.py:28`、`stock_data_updater.py:92`、`tdx_updater.py:297`、`tdx_updater.py:391`），唯独 `data_pipeline_service.py` 错误地将 bool 当 DataFrame 使用。
- 修复建议:
  ```python
  def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
      df = self.cleaner.clean_stock_daily(df)
      if not self.validator.validate(df):
          logger.error(f"数据验证失败 {symbol}，返回空 DataFrame")
          return pd.DataFrame()
      df = self.adjuster.apply_adjustment(symbol, df, method=adjust)
      return df
  ```

---

### [HIGH] DataValidator.validate() 对输入 DataFrame 有隐式副作用（Mutation）

- 文件: `src/uniquant/data/pipeline/data_validator.py:28-62`
- 代码片段:
  ```python
  def validate(self, df: pd.DataFrame) -> bool:   # 声明返回 bool
      # 第 31-33 行: 原地交换 high/low
      df.loc[mask_error, ["high", "low"]] = df.loc[mask_error, ["low", "high"]].values
      # 第 53 行: 原地修复 high
      df["high"] = df[["high", "open", "close"]].max(axis=1)
      # 第 57 行: 原地修复 low
      df["low"] = df[["low", "open", "close"]].min(axis=1)
      # 第 61-62 行: 原地转换 date 类型 + 排序
      df["date"] = pd.to_datetime(df["date"])
      df = df.sort_values("date")
  ```
- 问题描述: `validate()` 声明返回 `bool`，但函数体内对输入 `df` 执行了 5 处原地修改：(1) swap high/low（28-33行），(2) 修复 high（53行），(3) 修复 low（57行），(4) 转换 date 类型（61行），(5) 排序（62行）。这是典型的"声称纯检查，实际有副作用"反模式。虽然其他调用方（`stock_data_updater.py`、`tdx_updater.py`）将其返回值用作条件判断，但调用方不会意识到 df 已被修改。
- 影响: (1) 调用方的 df 被意外修改，违反最小惊讶原则；(2) 与 DataCleaner 中的 OHLC 修复逻辑重复（`data_cleaner.py:32-40` 也做了同样的修复），导致同一修复逻辑被执行两次，结果可能不一致；(3) validate 的修复逻辑在 Cleaner 之后执行，如果 Cleaner 已修复，Validator 再修复是冗余的。
- 修复建议: DataValidator 应为纯函数，仅返回 bool，不修改输入。修复逻辑统一放在 DataCleaner 中：
  ```python
  def validate(self, df: pd.DataFrame) -> bool:
      df_check = df.copy()  # 仅用于检查，不修改原 df
      # ... 所有检查逻辑 ...
      return is_valid
  ```

---

### [HIGH] DataValidator 日志计数 Bug — `~series.sum()` 产生负数（Bitwise NOT）

- 文件: `src/uniquant/data/pipeline/data_validator.py:52,56`
- 代码片段:
  ```python
  high_validate = (df["high"] >= df["open"]) & (df["high"] >= df["close"])
  if not high_validate.all():
      logger.warning(f"发现 {~high_validate.sum()} 条记录 High < Open/Close")
  # ...
  low_validate = (df["low"] <= df["open"]) & (df["low"] <= df["close"])
  if not low_validate.all():
      logger.warning(f"发现 {~low_validate.sum()} 条记录 Low > Open/Close")
  ```
- 问题描述: `high_validate.sum()` 返回整数（True 的数量），`~` 运算符对整数执行**按位取反**，而非逻辑取反。Python 定义 `~x = -(x+1)`。实测验证：100 行数据中 98 行通过验证时，`high_validate.sum()` = 98，`~98` = `-99`。日志将输出 "发现 -99 条记录 High < Open/Close"，完全错误。意图是输出违反约束的行数，应为 `(~high_validate).sum()` 或 `len(df) - high_validate.sum()`。
- 影响: 日志信息严重误导，可能掩盖真实的 OHLC 数据质量问题。调试时无法通过日志判断异常条数。如果后续有人依赖日志计数做监控告警，会完全失效。
- 修复建议:
  ```python
  n_violations = (~high_validate).sum()   # 对 Series 取反，再 sum
  # 或
  n_violations = len(df) - high_validate.sum()
  ```

---

### [MEDIUM] DataCleaner.clean() 未拷贝输入 DataFrame — 原地修改调用方数据

- 文件: `src/uniquant/data/pipeline/data_cleaner.py:11-57`
- 代码片段:
  ```python
  def clean(self, df: pd.DataFrame) -> pd.DataFrame:
      if df.empty:
          return df           # 空 DataFrame 直接返回（OK）
      # 第 20 行: 原地修改列名
      df.columns = [col.lower() for col in df.columns]
      # 第 27 行: 原地修改列值
      df[col] = pd.to_numeric(df[col], errors="coerce")
      # 第 35-36 行: 原地修改 high/low
      df["high"] = df[["open", "close", "high"]].max(axis=1)
      df["low"] = df[["open", "close", "low"]].min(axis=1)
  ```
- 问题描述: `clean()` 方法没有在开头调用 `df = df.copy()`，所有修改（列名小写化、类型转换、OHLC 修复）均直接作用于传入的 DataFrame 对象。调用方持有的原始 DataFrame 会被意外修改。对比 `data_adjuster.py:182` 正确地执行了 `df_raw = df_raw.copy()`。
- 影响: (1) 调用方的原始数据被不可逆修改（列名被小写化、数值被 coerce）；(2) 如果调用方在 clean 之后还想使用原始数据（如日志、对比、重试），数据已被污染；(3) `stock_data_updater.py:90` 调用 `self.data_cleaner.clean(df_new)` 后 df_new 被原地修改，可能导致后续逻辑出现意外行为。
- 修复建议: 在 `clean()` 方法开头添加 `df = df.copy()`：
  ```python
  def clean(self, df: pd.DataFrame) -> pd.DataFrame:
      if df.empty:
          return df
      df = df.copy()
      ...
  ```

---

### [MEDIUM] DataCleaner 对价格列缺少 NaN 防护

- 文件: `src/uniquant/data/pipeline/data_cleaner.py:23-29,43`
- 代码片段:
  ```python
  price_cols = {"open", "high", "low", "close"}
  numeric_cols = ["open", "high", "low", "close", "volume"]
  for col in numeric_cols:
      if col in df.columns:
          df[col] = pd.to_numeric(df[col], errors="coerce")
          if col not in price_cols:        # 仅 volume 做 fillna(0)
              df[col] = df[col].fillna(0)
  # ...
  df = df.dropna(subset=["date", "close"])  # 仅 dropna close
  ```
- 问题描述: `pd.to_numeric(errors="coerce")` 会将非数字值转为 NaN。对 volume 列有 `fillna(0)` 防护，对 close 列有 `dropna` 兜底，但 **open、high、low 三个价格列没有任何 NaN 处理**。如果源数据中 open/high/low 包含脏值（如空字符串、异常字符），这些列将保留 NaN。虽然 `data_validator.py:48-49` 的比较检查会在 NaN 时返回 False 并触发修复，但这依赖于 validator 被调用的时机。
- 影响: NaN 价格传播到下游所有引擎：CZSC 缠论计算、Wyckoff 形态识别、LPPL 泡沫检测、复权因子计算等均会因 NaN 产生错误结果或崩溃。`data_validator.py:48-49` 的 `high >= open` 检查在 NaN 时返回 False（NaN 的比较结果为 False），会触发不必要的修复逻辑，掩盖数据质量问题。
- 修复建议: 在 dropna(close) 之后，对 open/high/low 也做 ffill+bfill 兜底：
  ```python
  for col in ["open", "high", "low"]:
      if col in df.columns:
          df[col] = df[col].ffill().bfill()
  ```

---

### [MEDIUM] DataAdjuster.apply_adjustment QFQ 路径 — latest_factor 正确但缺少防御性文档

- 文件: `src/uniquant/data/pipeline/data_adjuster.py:246-255`
- 代码片段:
  ```python
  elif method == "qfq":
      # QFQ = Price * Factor / LatestFactor
      # Use the factor as-of the last date in df_raw (point-in-time), not the
      # absolute latest factor which would leak future dividend events into history.
      latest_factor = df_merged["factor"].iloc[-1]
      if latest_factor == 0:
          logger.error(f"最新因子为0，无法计算前复权: {symbol}")
          return df_raw
      qfq_multiplier = df_merged["factor"] / latest_factor
  ```
- 问题描述: 经审计确认，此处的实现**不存在未来数据泄露**。审计逻辑链：(1) `merge_asof(..., direction="backward")`（第 202-207 行）确保每个交易日获得的是该日及之前最近的因子值；(2) `cutoff_date` 截断（第 214-218 行）在 `latest_factor` 计算之前执行；(3) `latest_factor` 取自截断后 df_merged 的最后一行，即数据中最后一个交易日对应的因子，这是正确的 point-in-time 行为。`get_adjusted_data()`（第 281-308 行）调用时传入 `cutoff_date=end_date`，进一步限制时间窗口。
- 修正: 代码设计是正确的。但建议在 `apply_adjustment()` 的 docstring 中明确说明 QFQ 的 point-in-time 保证机制，避免后续审计者再次误判。
- 影响: 无数据泄露风险。仅缺少防御性文档说明。

---

### [MEDIUM] DataCleaner 与 DataValidator 存在重复的 OHLC 修复逻辑

- 文件: `src/uniquant/data/pipeline/data_cleaner.py:32-40` + `data_validator.py:28-57`
- 代码片段:
  ```python
  # DataCleaner (第 35-36 行):
  df["high"] = df[["open", "close", "high"]].max(axis=1)
  df["low"] = df[["open", "close", "low"]].min(axis=1)

  # DataValidator (第 31-33, 53, 57 行):
  df.loc[mask_error, ["high", "low"]] = df.loc[mask_error, ["low", "high"]].values
  df["high"] = df[["high", "open", "close"]].max(axis=1)
  df["low"] = df[["low", "open", "close"]].min(axis=1)
  ```
- 问题描述: DataCleaner 和 DataValidator 都实现了 OHLC 一致性修复（确保 high >= max(open, close), low <= min(open, close)）。在 `DataPipelineService.process()` 的流程中，Cleaner 先执行，Validator 后执行，导致同一修复逻辑被执行两次。
- 影响: (1) 性能浪费；(2) 两处修复的实现细节不同（Cleaner 用 `max(axis=1)`，Validator 先 swap 再 `max(axis=1)`），可能导致边界情况下的不同行为；(3) 违反单一职责原则，维护困难。
- 修复建议: OHLC 一致性修复统一放在 DataCleaner 中，DataValidator 仅做只读验证。

---

### [MEDIUM] StorageManager.read_local_raw 尝试 6 种文件名格式 — I/O 放大

- 文件: `src/uniquant/data/lake/storage_manager.py:251-281`
- 代码片段:
  ```python
  possible_symbols = [
      standard_symbol,
      f"{clean_symbol}.SH",
      f"{clean_symbol}.SZ",
      f"{clean_symbol}.BJ",
      clean_symbol,
      symbol,
  ]
  seen = set()
  for test_symbol in possible_symbols:
      if test_symbol in seen:
          continue
      seen.add(test_symbol)
      file_path = self.daily_dir / f"{test_symbol}.parquet"
      df = self.read_parquet(str(file_path))
      if not df.empty:
          return df
  ```
- 问题描述: 每次读取原始数据时，依次尝试 6 种文件名格式，每次尝试都调用 `read_parquet()`，即使文件不存在也会构造 Path 对象并执行 `file_path_obj.exists()` 检查。最坏情况下 6 倍 I/O 开销。`read_local_factor()`（第 283-313 行）存在完全相同的模式。
- 影响: 全市场扫描 5000 只股票时，若大部分股票不在标准路径，I/O 放大效应显著。在批量更新场景下（`batch_read_data`），每次调用都可能触发最多 6 次文件系统检查。
- 修复建议: 在 `__init__` 时扫描 `daily_dir` 构建 `symbol -> file_path` 索引映射，后续读取直接查表：
  ```python
  def __init__(self, data_dir):
      # ... existing code ...
      self._symbol_index = self._build_symbol_index()

  def _build_symbol_index(self):
      index = {}
      for f in self.daily_dir.glob("*.parquet"):
          index[f.stem] = f
      return index
  ```

---

### [LOW] DataPipelineService 创建独立 StorageManager — 与 DataFetcher 状态不共享

- 文件: `src/uniquant/data/data_pipeline_service.py:15`
- 代码片段:
  ```python
  class DataPipelineService:
      def __init__(self, data_dir: str = "./data"):
          self.cleaner = DataCleaner()
          self.validator = DataValidator()
          self.adjuster = DataAdjuster(StorageManager(data_dir))  # 新建 StorageManager
  ```
- 问题描述: `DataPipelineService` 在构造函数中创建了独立的 `StorageManager` 实例，而 `DataFetcher`（`data_fetcher.py:67`）也创建了自己的 `StorageManager`。两者指向同一目录但实例不同。`StorageManager.__init__` 中执行 6 次 `mkdir`（第 41-46 行）和 1 次 `_load_all_stock_codes`（第 48 行），导致不必要的 I/O 和内存开销。
- 影响: (1) 每次创建 `DataPipelineService` 都会创建新的 `StorageManager`，重复加载股票代码列表；(2) 两个 StorageManager 实例的 `all_stock_codes` 集合独立，修改一个不会影响另一个。
- 修复建议: 让 `DataPipelineService` 接受外部传入的 `StorageManager`，或与 `DataFetcher` 共享同一实例。

---

### [LOW] data_aligner.py 使用已弃用的 `fillna(method="bfill")` 语法

- 文件: `src/uniquant/data/pipeline/data_aligner.py:96`
- 代码片段:
  ```python
  merged[col] = merged[col].ffill().fillna(method="bfill")
  ```
- 问题描述: `Series.fillna(method=...)` 在 pandas 2.1+ 中已标记为 FutureWarning，将在未来版本中移除。应使用 `bfill()` 替代。
- 影响: 当前产生 FutureWarning，未来 pandas 版本升级后将抛异常。
- 修复建议: `merged[col] = merged[col].ffill().bfill()`

---

### [LOW] StorageManager 写入方法存在重复的原子写入模式

- 文件: `src/uniquant/data/lake/storage_manager.py:315-355, 523-545`
- 代码片段:
  ```python
  # save_data (第 315-334 行)
  def save_data(self, symbol, df):
      temp_path = file_path.with_suffix(".tmp")
      self.write_parquet(str(temp_path), df, overwrite=True)
      file_path.unlink()
      temp_path.rename(file_path)

  # write_data (第 523-545 行)
  def write_data(self, symbol, df, data_type="daily"):
      temp_path = file_path.with_suffix(".tmp")
      self.write_parquet(str(temp_path), df, overwrite=True)
      file_path.unlink()
      temp_path.rename(file_path)
  ```
- 问题描述: `save_data()`、`save_factor()`、`write_data()` 三个方法各自实现了几乎相同的原子写入逻辑（写临时文件 -> 删除原文件 -> 重命名），但 `save_data` 和 `save_factor` 不通过 `write_data`，各自独立实现。
- 影响: 维护困难，任何原子写入逻辑的 bug 修复需要同步修改三处。且 `save_data` 和 `write_data` 的 `data_type="daily"` 路径相同，存在功能重叠。
- 修复建议: 将原子写入提取为 `_atomic_write(file_path, df)` 私有方法，其他方法统一调用。

---

### [LOW] StorageManager._normalize_stock_code 对非标准前缀的兜底逻辑过于宽泛

- 文件: `src/uniquant/data/lake/storage_manager.py:206-213`
- 代码片段:
  ```python
  if clean_code.startswith("6"):
      return f"{clean_code}.SH"
  elif clean_code.startswith(("00", "30")):
      return f"{clean_code}.SZ"
  elif clean_code.startswith(("83", "87", "43")):
      return f"{clean_code}.BJ"
  return f"{clean_code}.SH"   # 兜底: 所有未知代码默认 .SH
  ```
- 问题描述: 当股票代码不匹配任何已知前缀时，默认返回 `.SH`（沪市）后缀。这意味着任何无法识别的代码都会被当作沪市股票处理。
- 影响: 新上市的证券类型（如北交所新号段 82xxxx、430xxx 扩展号段）可能被错误归类，导致读取不到数据或读取错误数据。
- 修复建议: 对无法识别的代码返回空字符串或 None，并在调用方处理 fallback 逻辑，而非默认归入沪市。

---

### [LOW] StorageManager.read_parquet 的 @handle_errors 装饰器与内部 try-except 重复

- 文件: `src/uniquant/data/lake/storage_manager.py:90-113`
- 代码片段:
  ```python
  @handle_errors(
      IOError, OSError, DataStorageError,
      default_return=pd.DataFrame(), log_level=logging.ERROR,
  )
  def read_parquet(self, file_path: str, normalize: bool = True) -> pd.DataFrame:
      # ...
      try:
          df = pd.read_parquet(file_path)
          # ...
          return df
      except Exception as e:
          logger.error(f"读取数据从 {file_path} 失败: {e}")
          return pd.DataFrame()
  ```
- 问题描述: `read_parquet` 同时使用了 `@handle_errors` 装饰器和内部 `try-except Exception`。内部的 `except Exception` 已经捕获了所有异常并返回空 DataFrame，导致 `@handle_errors` 永远不会触发。装饰器成为死代码。
- 影响: 装饰器增加的认知负担和执行开销无实际效果。如果未来有人移除内部 try-except，装饰器才会生效，但当前行为不明确。
- 修复建议: 移除 `@handle_errors` 装饰器，保留内部 try-except（更精确的控制），或将内部 try-except 精简为仅处理特定异常。

---

## 审计结论

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| CRITICAL | 1 | DataPipelineService.process() 类型错误，整个 pipeline 崩溃 |
| HIGH | 2 | validate() 隐式副作用；日志计数 bitwise NOT bug |
| MEDIUM | 4 | Cleaner 不拷贝输入；价格列 NaN 防护缺失；OHLC 修复重复；I/O 放大 |
| LOW | 4 | 独立 StorageManager；弃用 API；原子写入重复；装饰器死代码 |

**总结**: `src/uniquant/data/` 层存在 1 个 CRITICAL 级别的运行时崩溃 bug（DataPipelineService.process() 类型不匹配），2 个 HIGH 级别的设计缺陷（validate 副作用 + 日志 bug），以及 4 个 MEDIUM 级别的数据质量和代码质量问题。CRITICAL 问题导致整个数据处理流水线在 clean -> validate -> adjust 链路中无法正常运行，必须立即修复。

**QFQ 未来数据泄露审计结论**: data_adjuster.py:250 的 `latest_factor` **不存在未来数据泄露**。`merge_asof(direction="backward")` + `cutoff_date` 截断保证了 point-in-time 语义正确。
