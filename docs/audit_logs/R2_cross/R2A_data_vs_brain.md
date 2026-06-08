# R2-A: Data vs. Brain/Factor Cross-Validation Report

> 审计员: R2-A 交叉审计员
> 审计时间: 2026-06-06
> 对抗组: Data 层 ↔ Brain/Factor 层
> 审计目标: Data 层输出能否无缝喂入 FactorPipeline；跨域契约是否一致

---

## 数据流拓扑分析

```
                    ┌─────────────────────────────────────┐
                    │         实际运行路径 (ScanPipeline)    │
                    │                                     │
  StorageManager ──►│  batch_read_data()                  │
  (parquet files)   │    ↓                                │
                    │  df['code'] = symbol  ← 手动添加     │
                    │    ↓                                │
                    │  FactorComposer.compute_all_factors()│
                    │  FactorAnalyzer.compute_ic_ir()      │
                    │                                     │
                    │  ★ 绕过 DataPipelineService          │
                    └─────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │       未接入路径 (WalkForwardPipeline) │
                    │                                     │
  DataFetcher ─────►│  get_price()                        │
  .get_price()      │    ↓                                │
                    │  DataPipelineService.process()       │
                    │    cleaner.clean()  → DataFrame ✓   │
                    │    validator.validate() → bool ✗     │
                    │    adjuster.apply_adjustment()       │
                    │    ↓                                 │
                    │  ★ process() 在此崩溃，永远无法到达   │
                    │    WalkForwardFactorPipeline.run()    │
                    └─────────────────────────────────────┘
```

**关键事实**: `WalkForwardFactorPipeline` 在整个代码库中**仅定义、未被任何模块导入或调用**。实际的因子分析通过 `ScanPipeline` 完成，后者直接从 `StorageManager` 读取 parquet 数据，绕过 `DataPipelineService`。

---

## 发现

### [CRITICAL-1] DataPipelineService.process() 类型错误 — 整条 Data → Factor 通路断裂

- **来源**: R1-1A CRITICAL + R1-1D
- **涉及文件**:
  - `data_pipeline_service.py:17-21` (崩溃源)
  - `data_validator.py:11,76` (返回 bool)
  - `data_adjuster.py:164` (崩溃点)
  - `walk_forward_pipeline.py:114-118` (假设接收 DataFrame)

- **崩溃链路**:
  ```
  DataPipelineService.process(df, symbol, adjust="qfq")
    │
    ├─ L18: df = self.cleaner.clean_stock_daily(df)
    │        → 返回 DataFrame ✓, 但原地修改了调用方的 df
    │
    ├─ L19: df = self.validator.validate(df)
    │        → validate() 原地修改 df (swap high/low, 修复 OHLC, 转换 date 类型)
    │        → 然后返回 bool (True/False)
    │        → df 变量被绑定为 bool ← 类型错误根源
    │
    └─ L20: df = self.adjuster.apply_adjustment(symbol, df, method=adjust)
             → df 是 bool
             → L164: `if df_raw.empty` → AttributeError: 'bool' object has no attribute 'empty'
             → ★ 进程崩溃
  ```

- **修正后的精确影响分析**:
  R1-1A 报告称"FactorPipeline 收到 True"——这是**不精确的**。实际情况:
  1. 当 `adjust="qfq"` (默认)时，`apply_adjustment()` 在 L164 检查 `df_raw.empty`，bool 没有 `.empty` 属性 → **AttributeError 崩溃**，`process()` 无法返回
  2. 当 `adjust` 不是 "qfq"/"hfq" 时 (如 `adjust=""`)，`apply_adjustment()` 在 L164 的 `method not in ["qfq", "hfq"]` 为 True → 直接返回 `df_raw` (bool)，`process()` 返回 bool → **不崩溃但返回类型错误**
  3. 无论哪种情况，`WalkForwardFactorPipeline.run()` 都无法正常接收数据

- **对 WalkForwardFactorPipeline 的具体影响**:
  若通过某路径将 bool 传入 `run()`:
  - `-O` 模式: L114-116 的 assert 被跳过，L118 `df.sort_values(...)` 崩溃 → `AttributeError: 'bool' object has no attribute 'sort_values'`
  - 正常模式: L114 `assert date_col in df.columns` → `AttributeError: 'bool' object has no attribute 'columns'`

- **严重性**: **CRITICAL** — 但当前影响有限，因为 `WalkForwardFactorPipeline` 未被接入。实际的 `ScanPipeline` 绕过了此路径。

- **修复**: Phase 0.1 — 修复 `data_pipeline_service.py:17-21`

---

### [CRITICAL-2] validate() 隐式副作用 — 即使不崩溃，输入 df 也被污染

- **来源**: R1-1A HIGH
- **涉及文件**: `data_validator.py:28-62`

- **原地修改清单**:

  | 行号 | 操作 | 影响 |
  |------|------|------|
  | 31-33 | `df.loc[mask_error, ["high", "low"]] = ...` | 原地交换 high/low |
  | 53 | `df["high"] = df[["high", "open", "close"]].max(axis=1)` | 原地修复 high |
  | 57 | `df["low"] = df[["low", "open", "close"]].min(axis=1)` | 原地修复 low |
  | 61 | `df["date"] = pd.to_datetime(df["date"])` | 原地转换 date 类型 |
  | 62 | `df = df.sort_values("date")` | 重绑定本地变量 |

- **跨域影响**: `validate()` 返回 bool，但**在返回前已修改了输入 DataFrame**。在 `process()` 中:
  ```python
  df = self.cleaner.clean_stock_daily(df)  # df 是 DataFrame
  df = self.validator.validate(df)          # df 被原地修改后，变量绑定到 bool
  ```
  调用方持有的原始 DataFrame 对象已被 validate 修改（OHLC 修复、date 转换、排序），但 `process()` 的返回值是 bool。如果调用方在异常处理中继续使用原始 df，数据处于**部分处理的不一致状态**（cleaned + validated + sorted，但未 adjusted）。

- **与 DataCleaner 的 OHLC 修复重复**: DataCleaner L35-36 和 DataValidator L53+L57 执行相同的修复。在 process() 中先 Cleaner 后 Validator，同一修复逻辑被执行两次，结果应一致但增加了不必要的开销。

- **严重性**: **CRITICAL** — 静默数据污染 + 逻辑重复

- **修复**: validate() 应为纯函数，仅返回 bool，不修改输入 df。OHLC 修复统一放在 DataCleaner 中。

---

### [HIGH-1] "code" 列跨域契约不一致

- **来源**: R1-1A + R1-1D
- **涉及文件**:
  - `data_cleaner.py:11-57` (不添加 "code" 列)
  - `data_validator.py:20` (要求 "code" 列)
  - `walk_forward_pipeline.py:110,115` (要求 "code" 列)
  - `composer.py:34` (可选使用 "code" 列)
  - `scan_service.py:160` (手动添加 "code" 列)

- **各组件对 "code" 列的契约**:

  | 组件 | 对 "code" 列的行为 | 契约 |
  |------|-------------------|------|
  | DataCleaner.clean() | 不添加，不检查 | **不保证** |
  | DataValidator.validate() | L20 检查 required_cols 包含 "code"，缺失则返回 False | **强要求** |
  | DataPipelineService.process() | 依赖 validator 检查，但错误处理是返回 bool | **间接要求** |
  | ScanPipeline.build_factors() | L160: `df['code'] = symbol` 手动添加 | **自行保证** |
  | WalkForwardFactorPipeline.run() | L115: `assert code_col in df.columns` | **强要求** |
  | FactorComposer._iter_groups() | L34: `if "code" in df.columns`，缺失则单组处理 | **可选** |

- **分析**:
  1. **ScanPipeline 路径**: 直接从 StorageManager 读取 parquet，手动添加 `code` 列。DataCleaner 不参与此路径。**契约由调用方满足**。
  2. **WalkForwardFactorPipeline 路径**: 要求 `code` 列存在（L115 assert）。若通过 DataFetcher.get_price() 获取数据，DataPipelineService.process() 在 validator 阶段会因缺少 "code" 列返回 False (bool)，导致后续崩溃。**契约无法由 Data 层满足**。
  3. **StorageManager 输出**: parquet 文件中的列名取决于写入方。`StockDataUpdater` 写入的数据是否包含 "code" 列取决于数据源（TDX 源通常包含）。

- **严重性**: **HIGH** — DataCleaner 与 FactorPipeline 之间缺少明确的 "code" 列契约

- **修复**: DataCleaner.clean() 应在处理完成后确保必要列存在（至少日志警告），或在 Data 层文档中明确声明输出 schema。

---

### [HIGH-2] DataCleaner 不拷贝输入 — 跨域引用污染

- **来源**: R1-1A MEDIUM
- **涉及文件**: `data_cleaner.py:11-57`

- **原地修改清单**:

  | 行号 | 操作 | 影响 |
  |------|------|------|
  | 20 | `df.columns = [col.lower() for col in df.columns]` | 列名被永久小写化 |
  | 27 | `df[col] = pd.to_numeric(df[col], errors="coerce")` | 列值被类型转换 |
  | 35-36 | `df["high"] = ...max`, `df["low"] = ...min` | OHLC 值被修复 |
  | 43 | `df = df.dropna(subset=["date", "close"])` | 行被删除 |
  | 44 | `df["date"] = pd.to_datetime(df["date"])` | date 类型转换 |
  | 45 | `df = df.drop_duplicates(...)` | 重复行被删除 |
  | 54 | `df = df.sort_values("date").reset_index(drop=True)` | 行序和索引改变 |

- **跨域污染场景**:

  场景 1: `StockDataUpdater` 调用路径
  ```python
  # stock_data_updater.py:90
  df_new = self.data_cleaner.clean(df_new)
  ```
  `df_new` 可能是从 `DataFetcher` 获取的 DataFrame 的同一对象引用。clean() 修改 df_new 的同时，DataFetcher 内部可能仍持有同一引用（除非 fetcher 做了 copy）。后续逻辑若依赖原始数据（如日志对比、重试），数据已被不可逆修改。

  场景 2: `DataService.rebuild_cache()` 调用路径
  ```python
  # data_service.py:169
  cleaned_data = self.cleaner.clean_stock_daily(source_data)
  # source_data 来自 self.fetcher.get_price(symbol)
  ```
  `source_data` 被 clean() 原地修改。如果 get_price() 缓存了 source_data 的引用，缓存中的数据也被修改。

  场景 3: `DataService.check_cache_consistency()` 调用路径
  ```python
  # data_service.py:149
  source_data = self.cleaner.clean_stock_daily(source_data)
  # source_data 来自 self.fetcher.get_price(symbol)
  ```
  同上，原始数据被污染。

- **对 FactorPipeline 的具体影响**:
  当前 ScanPipeline 在 `build_factors()` 中 L159 执行 `df = df.copy()`，自行防御了引用污染。但这是调用方的防御，不是 Data 层的保证。如果未来有人不 copy 就传入 FactorComposer，数据会被意外修改。

- **对比**: `data_adjuster.py:182` 正确执行 `df_raw = df_raw.copy()`。

- **严重性**: **HIGH** — 隐式副作用，违反最小惊讶原则，下游依赖方必须自行防御

- **修复**: `clean()` 方法开头添加 `df = df.copy()`

---

### [MEDIUM-1] 时间戳格式对齐 — 依赖 pd.to_datetime 隐式行为

- **来源**: R1-1A + R1-1D
- **涉及文件**:
  - `data_cleaner.py:44`: `df["date"] = pd.to_datetime(df["date"])`
  - `data_validator.py:61`: `df["date"] = pd.to_datetime(df["date"])`
  - `walk_forward_pipeline.py:67`: `pd.to_datetime(df[date_col].unique())`
  - `walk_forward_pipeline.py:142-143`: `pd.to_datetime(df[date_col])`

- **时区分析**:

  | 组件 | pd.to_datetime 调用 | 时区处理 |
  |------|-------------------|----------|
  | DataCleaner L44 | `pd.to_datetime(df["date"])` | 不指定 tz，结果取决于输入 |
  | DataValidator L61 | `pd.to_datetime(df["date"])` | 不指定 tz |
  | WalkForwardFactorPipeline L67 | `pd.to_datetime(df[date_col].unique())` | 不指定 tz |
  | WalkForwardFactorPipeline L142-143 | `pd.to_datetime(df[date_col])` | 不指定 tz |

  所有组件均使用 `pd.to_datetime()` 不指定时区。如果输入数据包含时区信息（如 `pd.Timestamp('2024-01-01', tz='Asia/Shanghai')`），`pd.to_datetime()` 会保留时区。

- **风险**: 在 pandas 2.0+ 中，naive timestamp 与 timezone-aware timestamp 的比较会抛出 `TypeError: Cannot compare tz-naive and tz-aware timestamps`。如果 TDX 或 Baostock 源返回 timezone-aware 日期，DataCleaner 不会剥离时区，WalkForwardFactorPipeline 的日期比较会崩溃。

- **当前安全度**: 中等。DataCleaner 在 L44 做了 `pd.to_datetime()`，如果源数据是字符串（TDX 常见格式 "2024-01-01"），结果是 naive。但如果源数据已经是 timezone-aware Timestamp，则保留时区。

- **严重性**: **MEDIUM** — 潜在的跨版本兼容性问题

- **修复**: 统一使用 `pd.to_datetime(df["date"]).dt.tz_localize(None)` 确保 naive timestamp。

---

### [MEDIUM-2] DataValidator 日志计数 Bug — bitwise NOT 产生负数

- **来源**: R1-1A HIGH
- **涉及文件**: `data_validator.py:52,56`

- **代码**:
  ```python
  logger.warning(f"发现 {~high_validate.sum()} 条记录 High < Open/Close")
  ```

- **分析**: `high_validate.sum()` 返回整数（True 的数量），`~` 运算符对整数执行按位取反（`~x = -(x+1)`），而非逻辑取反。100 行数据中 98 行通过验证时，日志输出 "发现 -99 条记录 High < Open/Close"。

- **跨域影响**: 此 bug 导致 Data 层的日志信息完全错误。如果 FactorPipeline 或监控系统依赖日志信息做数据质量告警，将完全失效。例如，当 Data 层报告 "发现 -99 条异常" 时，监控系统可能认为数据正常（负数 < 阈值）。

- **严重性**: **MEDIUM** — 日志误导，影响运维监控

- **修复**: `(~high_validate).sum()` 或 `len(df) - high_validate.sum()`

---

### [MEDIUM-3] WalkForwardFactorPipeline.run() 使用 assert 做输入验证 — 与 Data 层输出契约脱节

- **来源**: R1-1D 核查项 1
- **涉及文件**: `walk_forward_pipeline.py:114-116`

- **代码**:
  ```python
  assert date_col in df.columns, f"Missing date_col={date_col}"
  assert code_col in df.columns, f"Missing code_col={code_col}"
  assert price_col in df.columns, f"Missing price_col={price_col}"
  ```

- **跨域影响**: 这些 assert 是 FactorPipeline 对 Data 层输出的最后一道防线。但:
  1. 在 `python -O` 模式下，所有 6 处 assert 被完全绕过（R1-1D 核查项 1 已确认）
  2. Data 层没有文档化其输出 schema（哪些列保证存在、列名大小写、数据类型）
  3. DataCleaner 输出小写列名，但 assert 的 `date_col="date"` 恰好匹配小写。如果 Data 层未执行 clean（如直接从 parquet 读取），列名可能不匹配。

- **严重性**: **MEDIUM** — 防御性验证在 `-O` 模式下无效

- **修复**: assert → `if ... raise ValueError(...)`，并在 Data 层文档中明确输出 schema。

---

### [LOW-1] validate() 返回 bool 但 process() 无条件赋值 — 错误处理契约缺失

- **来源**: R1-1A CRITICAL
- **涉及文件**: `data_pipeline_service.py:19`

- **分析**: 对比其他调用方的正确用法:
  ```python
  # stock_data_updater.py:28 — 正确: 条件判断
  if not self.validator.validate(df):
      logger.error(f"数据验证失败 {symbol}")
      return pd.DataFrame()

  # data_pipeline_service.py:19 — 错误: 无条件赋值
  df = self.validator.validate(df)
  ```

  `process()` 的设计意图是将 validate 作为流水线的一环（类似 cleaner 和 adjuster），但 validate 返回 bool 而非 DataFrame。这是 API 契约的不一致: cleaner 和 adjuster 返回 DataFrame，validate 返回 bool。

- **严重性**: **LOW** — 单点错误，已有 R1-1A CRITICAL 覆盖

- **修复**: 修复 data_pipeline_service.py:17-21

---

### [LOW-2] WalkForwardFactorPipeline 未接入 — 与 Data 层无实际交互

- **来源**: 本轮审计新发现
- **涉及文件**: `walk_forward_pipeline.py` (全文件)

- **分析**: `WalkForwardFactorPipeline` 在整个代码库中**仅定义、未被导入、未被调用**:
  - `grep "WalkForwardFactorPipeline" src/` 仅命中定义处
  - 没有任何 `from ...walk_forward_pipeline import WalkForwardFactorPipeline`
  - 实际的因子分析通过 `ScanPipeline` → `FactorAnalyzer`/`FactorComposer` 完成

  这意味着本轮审计中 R1-1D 发现的所有问题（assert 绕过、factor_func 不存在、check_lookahead_leakage 未调用、half_life 未传入）目前**零运行时影响**，因为该模块从未被执行。

  但这些问题在未来接入时会成为真实 bug。

- **严重性**: **LOW** — 当前零影响，但技术债务

- **修复**: 接入前修复所有 R1-1D 发现

---

## 交叉验证矩阵

| Data 层输出 | FactorPipeline 输入要求 | 契约匹配 | 问题 |
|-------------|----------------------|---------|------|
| DataFrame 类型 | `df: pd.DataFrame` 参数 | **不匹配** | process() 返回 bool，整条通路崩溃 |
| 列名: 小写 (cleaner 已小写化) | `date_col="date"`, `code_col="code"`, `price_col="close"` | **部分匹配** | "code" 列不被 DataCleaner 保证 |
| date 列: naive Timestamp | `pd.to_datetime()` 比较 | **匹配** | 依赖源数据不含时区 |
| OHLC 列: float64 | IC/IR 计算需要数值 | **匹配** | to_numeric + coerce 保证 |
| volume/amount 列: float64 | 因子计算需要 | **匹配** | |
| code 列: 可能不存在 | assert code_col in df.columns | **不匹配** | Data 层不保证，ScanPipeline 自行添加 |
| DataFrame 引用 | 可变对象 | **危险** | DataCleaner 不 copy，下游引用被污染 |

---

## 修复优先级

| 优先级 | 发现 | 修复建议 | 工作量 |
|--------|------|---------|--------|
| P0 | CRITICAL-1: process() 类型错误 | 修复 data_pipeline_service.py:17-21，validate 返回值做条件判断 | S |
| P0 | CRITICAL-2: validate() 隐式副作用 | validate() 改为纯函数，仅返回 bool，不修改 df | M |
| P1 | HIGH-2: DataCleaner 不拷贝 | clean() 开头添加 df = df.copy() | S |
| P1 | HIGH-1: "code" 列契约 | Data 层文档化输出 schema，或 DataCleaner 添加列存在性检查 | S |
| P2 | MEDIUM-1: 时间戳时区 | 统一 dt.tz_localize(None) | S |
| P2 | MEDIUM-2: 日志 bitwise NOT | (~series).sum() | S |
| P2 | MEDIUM-3: assert 替换 | if ... raise ValueError | S |
| P3 | LOW-1/2: 已由 P0 覆盖 | 随 P0 一起修复 | - |

---

## 审计结论

| 严重性 | 数量 | 关键发现 |
|--------|------|----------|
| CRITICAL | 2 | process() 类型断裂; validate() 隐式污染 |
| HIGH | 2 | "code" 列契约缺失; DataCleaner 不拷贝 |
| MEDIUM | 3 | 时间戳时区; 日志 bitwise NOT; assert 无效 |
| LOW | 2 | 错误处理契约; WalkForwardPipeline 未接入 |
| **合计** | **9** | |

**核心结论**:

1. **Data → Factor 通路当前断裂** — `DataPipelineService.process()` 因 validate() 返回 bool 而崩溃。但这不影响实际运行，因为 `ScanPipeline` 绕过了此路径，直接从 StorageManager 读取数据并手动添加 `code` 列。

2. **"code" 列是跨域最大的隐性契约漏洞** — DataCleaner 不保证输出包含 "code" 列，DataValidator 要求但错误处理方式错误（返回 bool），FactorPipeline 强要求但依赖 assert（-O 模式下无效）。当前由 ScanPipeline 在 L160 手动 `df['code'] = symbol` 自行解决，但这不是 Data 层的保证。

3. **DataCleaner 不拷贝输入是跨域污染源** — 所有调用方（StockDataUpdater, DataService, DataPipelineService）都持有同一 DataFrame 引用，clean() 的原地修改会传播到所有引用方。ScanPipeline 的 `df = df.copy()` (L159) 是唯一一处防御性 copy。

4. **validate() 是最危险的组件** — 它声称是纯验证函数（返回 bool），但实际上执行了 5 处原地修改，且修改在异常路径上也不可逆。这违反了最小惊讶原则，是典型的"隐藏副作用"反模式。

---

*审计时间: 2026-06-06 | 审计员: R2-A Cross-Validator | 基于代码事实*
*对抗组: Data(I/O) ↔ Factor Pipeline | 发现: 9 项 (2 CRITICAL + 2 HIGH + 3 MEDIUM + 2 LOW)*
