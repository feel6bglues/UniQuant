# Phase 4 — 数据管道可靠性审计

> 日期: 2026-06-30 | 方法: 全层代码审查 + 数据流追踪 + 错误处理分析

---

## 报告摘要

数据层是项目最大的单层 (65 文件, 12个数据源/管理器/管道组件)。整体架构设计良好,
容错机制和断路器模式有效。发现两个中等风险问题 (重复验证路径, DataIngestionService 僵尸代码)
和若干低风险问题 (缓存一致性, 列名标准化重复)。

**信任评级: B+** (核心数据流可靠, 但存在轻度架构碎片化)

---

## 数据流架构

```
Source Router ─→ StandardAdapter ─→ Cleaner ─→ Validator ─→ Adjuster ─→ StorageManager
   │                 │
   ├ TDX             ├ 列名标准化
   ├ Baostock        ├ 类型转换
   ├ Sina            └ 缺失值填充
   ├ Tencent
   └ THS
```

**数据获取路径**:
1. `DataFetcher.get_price(symbol)` → 检查 LRU 缓存 (5000 条目)
2. 缓存未命中 → `SourceRouter.fetch_with_fallback()` (5 源循环+重试)
3. 返回原始数据 → `DataPipelineService.process()` (Cleaner → Validator → Adjuster)
4. 写回 LRU 缓存并返回

**辅助路径**:
- `DataFetcher.fetch_stocks_daily()`: ThreadPoolExecutor (max 16 workers) 批量获取
- `SourceRouter.fetch_data_with_race()`: 竞速模式, 从多个健康源并发获取, 取最快

---

## 组件审计

### DataFetcher
| 检查项 | 状态 | 备注 |
|---|---|---|
| 源初始化容错 | ✅ | 单个源失败不阻塞其他源 |
| LRU 缓存 (5000 条目) | ✅ | 使用 OrderedDict, 到期弹出 |
| 缺省 DataFrame 返回 | ✅ | 失败返回 `pd.DataFrame()` |
| 错误装饰器 | ✅ | `@handle_errors` 在 `fetch_history()` 上 |
| `fetch_for_brain()` | ✅ | 兼容 brain 层接口 |

### SourceRouter
| 检查项 | 状态 | 备注 |
|---|---|---|
| 5 源故障转移 | ✅ | 串行尝试 + 每源 2 次重试 |
| 电路断路器 | ✅ | `pybreaker.CircuitBreakerError` 捕获 |
| 健康状态过期 (5 min) | ✅ | `check_source_health()` 自动重置 |
| 超时控制 | ✅ | `_fetch_with_timeout()` + `SOCKET_TIMEOUT` |
| 竞速模式 | ✅ | `fetch_data_with_race()` 并发取最快 |
| 数据完整性验证 | ✅ | 必要列 + datetime 类型 + 非空检查 |

### DataPipelineService
| 检查项 | 状态 | 备注 |
|---|---|---|
| Cleaner → Validator → Adjuster | ✅ | 管线顺序正确 |
| 验证失败不阻塞 | ✅ | 跳过复权继续返回 |

### DataCleaner
| 检查项 | 状态 | 备注 |
|---|---|---|
| 列名小写化 | ✅ | `df.columns = [col.lower() for col in df.columns]` |
| 数值类型强制 | ✅ | `pd.to_numeric(errors="coerce")` |
| OHLC 一致性修复 | ✅ | high=max(open,close,high), low=min(open,close,low) |
| 价格 NaN ffill/bfill | ✅ | 前后填充兜底 |
| 去重 (keep last) | ✅ | `drop_duplicates(subset=["date"], keep="last")` |
| 成交额自动生成 | ✅ | `close * volume` 兜底 |

### DataValidator
| 检查项 | 状态 | 备注 |
|---|---|---|
| 必要列检查 | ✅ | date/code/open/high/low/close/volume/amount |
| High < Low 自动修复 | ✅ | 交换 high/low 值 |
| 价格逻辑自动修复 | ✅ | high=max(open,close), low=min(open,close) |
| 成交额零值警告 | ✅ | 仅警告, 不阻塞 |
| 异常值检测 (>99% 跌幅) | ✅ | 仅警告 |
| 日期间隔 >14 天警告 | ✅ | 仅警告 |
| 复权状态检测 | ⚠️ | 缺少 adjustflag 列时仅警告, 但非所有源都提供此列 |

### DataAligner
| 检查项 | 状态 | 备注 |
|---|---|---|
| 交易日历对齐 | ✅ | `TradeCalendarManager` 生成完整日历 |
| IPO 前数据截断 | ✅ | 使用 `StockMetadataManager.ipo_date` |
| 退市后数据截断 | ✅ | 使用 `StockMetadataManager.delist_date` |
| 停牌日 ffill 价格 | ✅ | 仅 ffill (不 bfill 前导缺口, 防未来泄露) |
| 停牌日 volume/amount=0 | ✅ | `.fillna(0.0)` |
| 前视偏差防护 | ✅ | 明确注释: Do not bfill leading gaps |

### DataAdjuster
| 检查项 | 状态 | 备注 |
|---|---|---|
| QFQ 前复权 | ✅ | 标准复权算法 |
| 股票代码范围验证 | ✅ | 沪市 60/68, 深市 00/30 |
| 本地 TDX 数据读取 | ✅ | 通过 StorageManager |
| 复权因子计算 | ✅ | 基于除权除息数据 |

### StorageManager
| 检查项 | 状态 | 备注 |
|---|---|---|
| 目录自动创建 | ✅ | `mkdir(parents=True, exist_ok=True)` |
| Parquet 写入 | ✅ | `write_parquet()` |
| 路径遍历防护 | ✅ | `resolve()` 比较确保写入路径在 data_dir 内 |
| 文件锁 | ✅ | `filelock.FileLock` |
| 错误装饰器 | ✅ | `@handle_errors` |

---

## 发现

### 1. DataIngestionService 僵尸代码 (低风险) ✅ 已解决
`data_ingestion_service.py` (17 行) 曾是一个纯透传委托。该文件及
`DataFetcher` 中对其的所有引用已在 commit `bc6337bc` 中被删除。
`DataFetcher.get_price()` 现在直接调用 `source_router.fetch_with_fallback()`。
降级路径消失，数据获取管线减少一层间接调用。

### 2. 两个独立验证路径 (低风险)
`SourceRouter._validate_data_integrity()` 和 `DataValidator.validate()`
是两套独立的数据验证系统:
- SourceRouter: 检查列存在 + datetime 类型 + 非空 (82-98 行)
- DataValidator: 检查列存在 + OHLC 关系 + 异常值 + 日期连续性 (11-80 行)

两者不冲突但功能重叠。SourceRouter 的验证在 clean 之前执行,
DataValidator 在 clean 之后执行, 顺序正确。

### 3. `all_stock_codes.csv` vs `stock_list.csv` 分歧 (低风险)
`data/all_stock_codes.csv` (Phase 1 再生: 5536 stocks) 和
`data/stock_list.csv` 是两个独立的股票列表文件。
`StorageManager._load_all_stock_codes()` 读取前者,
而 `data_fetcher.py` 中某些方法读取后者 (如日志中的 `股票列表文件不存在: data/stock_list.csv`)。
来源不一致可能导致股票编录差异。

### 4. 缓存与持久化一致性 (低风险)
DataFetcher 的 LRU 缓存 (5000 条目) 只缓存 `get_price()` 结果,
但 StorageManager 的 parquet 文件写入独立发生。如果缓存过期条目和文件系统内容不同步,
`get_price()` 可能返回过期数据 (max 5000 次 `get_price` 调用后会清除)。
对批处理场景影响有限, 但长时间运行进程需要注意。

### 5. 源初始化静默失败 (观察)
`DataFetcher.__init__()` 中源初始化失败仅记录 warning 并继续:
```python
try:
    self.data_sources.append(source_cls())
except FETCHER_INIT_RECOVERABLE_ERRORS as e:
    logger.warning(f"数据源 {source_name} 初始化失败，跳过: {e}")
```
设计意图合理, 但在所有源都失败时, DataFetcher 仍会成功初始化,
但所有后续数据获取会静默返回空 DataFrame。

---

## 信任评级: B+

| 维度 | 评分 | 理由 |
|---|---|---|
| 多源故障转移 | A | 5 源 + 断路器 + 竞速 + 健康状态 |
| 数据清洗/验证 | A | OHLC 修复, NaN 处理, 去重, 异常检测 |
| 复权正确性 | A | 标准 QFQ 算法 |
| 日历对齐/停牌处理 | A | ffill 价格 + volume=0 + IPO/退市边界 |
| 缓存机制 | B+ | LRU 大小合理但无持久化校验 |
| 架构一致性 | B | 两个验证路径, DataIngestionService 僵尸, 两个股票列表 |
