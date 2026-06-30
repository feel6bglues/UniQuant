# Stage 2 — 数据系统深度分析

> **日期**: 2026-06-29 | **状态**: ✅ 完成
> **范围**: `src/uniquant/data/` (56 Python 文件, 15,519 LOC)
> **子模块**: sources(10+1), managers(12), pipeline(4), services(5+1), scripts(7), utils(6+1), lake(1), parsers(1)

---

## 1. 总览

### 架构图

```
                 ┌─────────────────────────────────┐
                 │          DataFetcher             │
                 │  (系统的大脑和总指挥)              │
                 └──────┬────────────────────┬──────┘
                        │                    │
              ┌─────────▼──────┐   ┌─────────▼──────────┐
              │  SourceRouter  │   │   DataPipeline      │
              │  (故障转移/    │   │  (清洗→校验→复权)    │
              │   竞速模式)    │   │                     │
              └─────────┬──────┘   └──────────┬──────────┘
                        │                     │
              ┌─────────▼──────┐   ┌──────────▼──────────┐
              │  5 Adapters    │   │    StorageManager    │
              │  (Standard)    │   │   (Parquet 数据湖)    │
              └─────────┬──────┘   └─────────────────────┘
                        │
         ┌──────────────┼──────────────┬──────────────┐
         ▼              ▼              ▼              ▼
     Baostock     SinaSource     TencentSource    TdxSource
     (在线)        (在线)          (在线)           (本地通达信)
                              ThsSource
                              (在线)
```

### 核心数据流

```
请求: fetch_stock_daily("600000.SH", "2020-01-01", "2024-12-31", adjust="qfq")
  │
  ├─ 1. DataFetcher.get_price(symbol, adjust)
  │     ├─ 检查 _price_cache (OrderedDict LRU, max=5000)
  │     └─ 缓存未命中 → 继续
  │
  ├─ 2. DataIngestionService.fetch_price(symbol, source="auto")
  │     ├─ SourceRouter (5 数据源故障转移)
  │     │   ├─ 顺序模式: Tdx→Baostock→Sina→Ths→Tencent
  │     │   ├─ 竞速模式: 同时请求多个, 取最快
  │     │   ├─ CircuitBreaker: 5次失败→熔断30秒
  │     │   ├─ 健康追踪: 5分钟超时→自动恢复
  │     │   └─ 超时: SOCKET_TIMEOUT=30s, 重试后退避
  │     └─ StandardAdapter._standardize_data()
  │         └─ normalizer.normalize_column_names()  (20+ 列名映射)
  │
  ├─ 3. DataPipeline.process(df, symbol, adjust)
  │     ├─ DataCleaner.clean()
  │     │   ├─ 列名小写化
  │     │   ├─ 类型转换 (numeric coercion)
  │     │   ├─ OHLC 一致性修复 (high≥max(open,close), low≤min(open,close))
  │     │   ├─ 缺失值处理 (ffill+bfill)
  │     │   ├─ 去重 (keep last)
  │     │   └─ amount 补全
  │     │
  │     ├─ DataValidator.validate()
  │     │   ├─ 8 列存在性检查
  │     │   ├─ High<Low 修复 + 验证
  │     │   ├─ Open/Close vs High/Low 一致性
  │     │   ├─ 成交额基础校验
  │     │   ├─ 异常值检测 (>99% 跌幅)
  │     │   ├─ 日期连续性 (>14 天警告)
  │     │   └─ 复权状态检查 (adjustflag)
  │     │
  │     └─ DataAdjuster.apply_adjustment(symbol, df, method="qfq"|"hfq")
  │         ├─ 1. 读取本地因子表 (parquet)
  │         ├─ 2. merge_asof (backward direction)
  │         ├─ 3. ffill + fillna(1.0) for 缺失因子
  │         ├─ 4. cutoff_date 防止未来除权泄露
  │         ├─ 5. HFQ: price * factor
  │         ├─ 6. QFQ: price * factor / latest_factor
  │         ├─ 7. 成交量: volume / factor (HFQ) or volume / qfq_multiplier (QFQ)
  │         ├─ 8. clip(clip(lower=0.001, upper=100000)) 价格异常防护
  │         └─ 9. clip(clip(lower=0, upper=10000000000)) 成交量异常防护
  │
  ├─ 4. 缓存结果到 _price_cache
  │
  └─ 5. 返回 pd.DataFrame
```

---

## 2. 文件清单

| 子包 | 文件 | LOC | 职责 | 状态 |
|------|------|-----|------|------|
| Root | `data_fetcher.py` | 314 | **系统总指挥** — 数据获取+缓存+协调 | ✅ |
| Root | `data_ingestion_service.py` | 48 | 简化版 DataFetcher (self-contained) | ⚠️ 冗余 |
| Root | `data_pipeline_service.py` | 32 | 管道封装 (clean→validate→adjust) | ✅ |
| Root | `manager.py` | 12 | ~~历史遗留 Facade~~ | ⚠️ 简单包装 |
| Root | `tdx_loader.py` | 18 | ~~历史遗留 TDX 加载器~~ | ⚠️ 简单包装 |
| Root | `__init__.py` | 58 | `__getattr__` 延迟导入契约 | ✅ |
| | | | | |
| **sources/** | `base.py` | 78 | `DataSource` 抽象基类 | ✅ |
| | `protocols.py` | 172 | 8 个能力协议 (Protocol) | ✅ |
| | `baostock.py` | 463 | BaoStock 在线源 (日线/周线/月线/5min/15min/30min/60min) | ✅ |
| | `tdx.py` | 177 | 通达信本地源 (.day 二进制文件) | ✅ |
| | `sina.py` | 609 | 新浪在线源 (日线/分钟/实时/龙虎榜) | ✅ |
| | `tencent.py` | 368 | 腾讯在线源 (日线/实时/复权因子) | ✅ |
| | `ths.py` | 620 | 同花顺在线源 (日线/实时/资金流/板块) | ✅ |
| | `eastmoney.py` | 1094 | 东方财富在线源 (财务/行业/概念/龙虎榜) | ✅ |
| | `realtime_bridge.py` | 428 | **实时行情桥接** (WebSocket 预备) | 🚧 脚手架 |
| | `mootdx_local.py` | 166 | mootdx 本地源 | ✅ |
| | `mootdx_online.py` | 149 | mootdx 在线源 | ✅ |
| | | | | |
| **managers/** | `source_router.py` | 246 | **路由中心** — 故障转移 + 竞速模式 + 熔断 | ✅ |
| | `standard_adapter.py` | 92 | **标准化适配器** — 20+ 列名映射 | ✅ |
| | `stock_metadata_manager.py` | 324 | 股票元数据 (名称/市场/板块/IPO/退市) | ✅ |
| | `trade_calendar_manager.py` | 194 | 交易日历 (硬编码 2024-2026 假期) | ⚠️ 需年度更新 |
| | `adjust_factor_manager.py` | 173 | 复权因子管理 | ✅ |
| | `factor_manager.py` | 452 | 因子管理器 (存储/指纹/增量更新) | ✅ |
| | `mootdx_factor_manager.py` | 246 | mootdx 因子管理器 | ✅ |
| | `market_data_coordinator.py` | 99 | 市场数据协调 (指数/ETF/行业/概念) | ✅ |
| | `stock_data_updater.py` | 149 | 股票数据增量更新 | ✅ |
| | `tdx_updater.py` | 644 | TDX 数据更新 (日线/周线/月线/5min/gbbq) | ✅ |
| | `cache_manager.py` | 64 | 缓存管理器 | ✅ |
| | `data_normalizer.py` | 27 | 数据标准化 | ✅ |
| | `baostock_cache_manager.py` | 144 | BaoStock 缓存管理 | ✅ |
| | | | | |
| **pipeline/** | `data_cleaner.py` | 69 | 数据清洗 (6 步) | ✅ |
| | `data_validator.py` | 85 | 数据验证 (7 步 + 自动修复) | ✅ |
| | `data_adjuster.py` | 308 | **复权核心** (向量化 QFQ/HFQ) | ✅ |
| | `data_aligner.py` | 98 | 数据对齐 | ✅ |
| | | | | |
| **services/** | `data_importer.py` | 662 | **数据导入器** (历史/增量/检查) | ✅ |
| | `import_1min.py` | 297 | 1 分钟数据导入 | ✅ |
| | `import_5min.py` | 297 | 5 分钟数据导入 | ✅ |
| | `import_financial.py` | 430 | 财务数据导入 | ✅ |
| | `import_index.py` | 379 | 指数数据导入 | ✅ |
| | `lppl_data_service.py` | 252 | LPPL 数据服务 | ✅ |
| | | | | |
| **lake/** | `storage_manager.py` | 638 | **数据湖** — Parquet 文件系统 | ✅ |
| | | | | |
| **parsers/** | `tdx_parser.py` | 445 | TDX .day/gbbq 二进制解析 | ✅ |
| | | | | |
| **utils/** | `normalizer.py` | 294 | 20+ 列名标准化映射 | ✅ |
| | `akshare_wrapper.py` | 340 | AkShare 包装器 (重试/UA 轮换) | ✅ |
| | `akshare_market_service.py` | 177 | AkShare 行情服务 | ✅ |
| | `akshare_reference_service.py` | 81 | AkShare 参考服务 | ✅ |
| | `smart_factor_calculator.py` | 327 | GBBQ 复权因子计算 (V15 纯净) | ✅ |
| | `js_executor.py` | 347 | JS 执行器 (同花顺加密接口) | ✅ |
| | `request_utils.py` | 288 | 请求工具 (限速/重试/UA) | ✅ |
| | | | | |
| **scripts/** | 7 个脚本 | 1,798 | 数据下载/同步/更新/导入 | ✅ |

---

## 3. 数据源详情

| 数据源 | 类型 | 日线 | 分钟 | 实时 | 其他特色 |
|--------|------|------|------|------|----------|
| **TDX** | 本地 | .day 文件 | — | — | 最快；依赖本地通达信安装 |
| **BaoStock** | 在线 | ✅ | 5/15/30/60m | — | 前/后/不复权；高数据质量 |
| **Sina** | 在线 | ✅ | ✅ | ✅ | 龙虎榜；请求限速 500ms |
| **Tencent** | 在线 | ✅ | — | ✅ | 复权因子 |
| **THS** | 在线 | ✅ | — | ✅ | 资金流、板块资金流 |
| **EastMoney** | 在线 | — | — | — | 财务数据、行业概念、龙虎榜 |
| **mootdx** | 本地 | ✅ | ✅ | — | 通达信替代解析 |
| **RealtimeBridge** | — | — | — | (预备) | WebSocket 异步，TickData 模型 |

### 竞速模式与故障转移

```python
SourceRouter:
  fetch_data():    顺序尝试: Tdx→Baostock→Sina→Ths→Tencent
                   每个源重试 2 次, 退避策略
                   失败标记 "unavailable", 5 分钟自动恢复
  fetch_data_with_race(): 同时请求最多 3 个健康源, 取最快结果
```

---

## 4. StorageManager 数据湖

### 目录结构

```
{data_dir}/
├── lake/
│   ├── quotes/
│   │   ├── daily/       # {symbol}.parquet (日线)
│   │   ├── weekly/      # {symbol}.parquet (周线, 日线合成)
│   │   ├── monthly/     # {symbol}.parquet (月线, 日线合成)
│   │   ├── 1mins/       # {symbol}.parquet
│   │   └── 5mins/       # {symbol}.parquet
│   └── index/           # {symbol}.parquet (指数)
├── factors/             # {symbol}.parquet (复权因子)
├── fq/                  # gbbq.parquet (除权除息原始数据)
├── all_stock_codes.csv  # 全量股票代码清单
├── stock_list.csv       # 股票列表 (含名称/市场/板块/vol_unit)
└── trade_calendar.csv   # 交易日历
```

### 关键特性

| 特性 | 实现 |
|------|------|
| **读写** | `write_parquet`/`read_parquet` (snappy 压缩) |
| **原子写入** | `.tmp` → rename → 覆盖 |
| **并发控制** | `FileLock` (第三方锁文件) |
| **路径安全** | `resolve()` 检查路径是否在 data_dir 内 |
| **代码标准化** | `_normalize_stock_code()`: 统一 XXXXXX.SH/SZ/BJ |
| **周线合成** | groupby year+week, OHLC 聚合规则 |
| **月线合成** | groupby year+month, OHLC 聚合规则 |
| **新鲜度检测** | `validate_freshness(max_lag_days=7)`: mtime 检查 |

---

## 5. 复权系统 (DataAdjuster + FactorManager)

### 复权因子计算流程

```
TDX gbbq 文件 → GBBQProcessorV15 清洗 → SmartFactorCalculator 计算
  ├─ V15 纯净过滤: category==1, date<=today, 列名标准化
  ├─ cash/split/rights 归一化 (/10)
  └─ → factor / n 累积因子 (HFQ: Start=1.0, Split→Factor increases)
```

### 复权执行

```python
pd.merge_asof(df_raw, df_factor, on="date", direction="backward")
df_merged["factor"].ffill().fillna(1.0)

if method == "hfq":
    price *= factor
    volume /= factor
elif method == "qfq":
    multiplier = factor / latest_factor
    price *= multiplier
    volume /= multiplier

价格: clip(0.001, 100000)
成交量: clip(0, 10000000000)
```

### 安全措施

- **cutoff_date**: 防止未来除权事件泄露到过去
- **因子值检查**: 异常范围 (≤0, >1,000,000, <0.000001)
- **股票代码过滤**: 仅处理 `60xx/68xx/00xx/30xx`

---

## 6. 缓存系统

| 缓存层级 | 类型 | 大小 | 失效策略 |
|----------|------|------|----------|
| **Memory (DataFetcher)** | `OrderedDict` LRU | 5,000 条 | `clear_price_cache(symbol, adjust)` |
| **Parquet (StorageManager)** | 磁盘文件 | — | mtime 新鲜度检查 |
| **TDX file cache** | `dict` in TdxSource | — | per (symbol,start,end) key |
| **Factor fingerprints** | JSON 文件 | — | 增量更新检测 |

---

## 7. 实时行情桥接 (RealtimeBridge)

### 当前状态: 🚧 脚手架

```python
class RealtimeBridge:
    subscribe(symbol, callback)    # 订阅某股票 tick
    unsubscribe(symbol)            # 取消订阅
    start()                        # 启动事件循环
    stop()                         # 停止事件循环
    get_snapshot(symbol) → TickData # 实时快照

@dataclass
class TickData:
    symbol, timestamp, price, volume, turnover
    bid_price/volume, ask_price/volume
    open, high, low, pre_close
```

- 支持 WebSocket (`start_websocket` 方法)
- 支持 MockDataSource (演示模式)
- 支持多路策略 (`MultiLeggedStrategy` 容器)
- MockTickProvider (随机 tick 生成, 用于测试)
- **未集成**: 未连接到任何真实 WebSocket 数据源

---

## 8. 关键观察

### 架构风险

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R2-1 | **DataFetcher + DataIngestionService 功能重复**: 两者都做 fetch+route+standardize, 但 DataFetcher 更丰富 (pipeline/缓存/协调器), DataIngestionService 是独立精简版 | `data_fetcher.py:44` vs `data_ingestion_service.py:12` | 数据获取入口有两条可能路径, 行为差异 |
| R2-2 | **DataCleaner 和 DataValidator 有重叠修复逻辑**: cleaner 修 OHLC 一致性, validator 也修 OHLC 一致性, 但修复规则略有不同 | `cleaner.py:32-38` vs `validator.py:29-48` | 相同输入可能产生不同输出 |
| R2-3 | **TradeCalendarManager 硬编码假期**: 2024-2026 年假期写死在源码中, 无自动更新机制 | `trade_calendar_manager.py:11-68` | 2027 年起 T+1 检查失效 |
| R2-4 | **价格缓存无持久化**: 内存缓存重启即失效, 热启动性能差 | `data_fetcher.py:163-178` | 重启后需重新请求所有数据 |
| R2-5 | **实时桥接未集成**: RealtimeBridge 仅脚手架, 无真实 WebSocket 连接 | `realtime_bridge.py` | 实盘就绪度低 |
| R2-6 | **OHLC 自动修复无审计**: Cleaner 和 Validator 静默修复异常数据, 无修复日志持久化 | `cleaner.py`, `validator.py` | 数据质量降级不可追溯 |
| R2-7 | **SourceRouter 的竞速模式并行数 3**: 写死在 `max_workers = min(3, len(adapters))` | `source_router.py:19` | 与 SourceRouter 故障转移配置不一致 (5 源在线) |
| R2-8 | **复权因子路径依赖: TDX gbbq 是第一入口**: 只有 TDX 有 gbbq 数据, 其他源 (Baostock 等) 虽提供调整因子但无自洽计算 | `data_adjuster.py:55-151` | 无 TDX 环境则复权系统无法运行 |

### 设计亮点

| # | 亮点 | 位置 |
|---|------|------|
| S2-1 | **故障转移 + 竞速模式双策略**: `fetch_data` 顺序重试, `fetch_data_with_race` 并发竞速 | `source_router.py` |
| S2-2 | **熔断器 (CircuitBreaker)**: 5 次失败熔断 30 秒, 保护上游 | `sources/base.py:15-25` |
| S2-3 | **原子写入 + 锁 + 路径安全**: FileLock + tmp rename + resolve() 检查 | `storage_manager.py:65-95` |
| S2-4 | **merge_asof 向量化复权**: 使用 pandas merge_asof 而非逐行操作 | `data_adjuster.py:160` |
| S2-5 | **cutoff_date 防未来除权泄露**: 限制复权到指定日期, 无 lookahead | `data_adjuster.py:180-184` |
| S2-6 | **因子值异常防护**: ≤0, >1e6, <1e-6 时降级返回原始数据 | `data_adjuster.py:192-200` |
| S2-7 | **Protocols 能力模式**: 8 个 Protocol 接口自由组合数据源能力 | `sources/protocols.py` |
| S2-8 | **20+ 列名标准化映射**: 统一各源不同的中文/英文/缩写列名 | `utils/normalizer.py`, `shared/constants.py` |
| S2-9 | **7 个增量更新脚本**: 独立运维的数据加载与更新管道 | `scripts/*.py` |
| S2-10 | **JS 执行器**: 支持同花顺加密接口的 JS 逆向 | `utils/js_executor.py` |

### 测试覆盖

| 测试 | 函数数 | 覆盖内容 |
|------|--------|----------|
| `test_data_fetcher_init_fault_tolerance.py` | 12+ | DataFetcher 初始化容错、SourceRouter 空适配器 |
| `test_data_access_service.py` | 3 | 缓存优先、指数别名、写入清洗 |
| `test_data_chaos_qa.py` | ~10 | 混沌测试 (空数据/异常/并发) |
| `test_data_and_stock_query_regressions.py` | 2 | 回退空值、ETF 错误 |
| `test_p1_data_entry_injection.py` | 2 | DI 注入 StorageManager |
| `test_p1_cache_invalidation.py` | 1 | 缓存清除 |
| `test_refactoring_validation.py` | 1 | DataAligner |
| `test_phase4_1_remediation.py` | 1 | DataAligner 不回填停牌前价格 |
| `test_realtime_bridge.py` | ~30 | RealtimeBridge 单元测试 |

---

## 9. 建议

### P1
1. **R2-1 (重复入口)**: 合并 DataFetcher 和 DataIngestionService — DataIngestionService 应委托给 DataFetcher
2. **R2-3 (硬编码假期)**: TradeCalendarManager 添加自动从网络更新假期机制, 或从 BaoStock/AkShare 自动获取

### P2
3. **R2-2 (重复修复)**: 统一 DataCleaner 和 DataValidator 的 OHLC 修复逻辑至一个共享方法
4. **R2-4 (缓存持久化)**: 添加可选的磁盘缓存层 (sqlite/parquet) 辅助内存缓存
5. **R2-6 (修复审计)**: Cleaner/Validator 添加修复日志持久化 (结构化日志)

### P3
6. **R2-5 (实时桥接)**: 连接真实 WebSocket 数据源 (如 Sina 或 EastMoney 实时推送)
7. **R2-7 (竞速配置)**: 将竞速并行数提取为可配置参数
8. **R2-8 (复权源)**: 添加 Baostock 调整因子作为 TDX gbbq 的后备

---

## 10. 验证清单

- [x] 读取 `data_fetcher.py` (314 LOC, 完整 fetch→pipeline→cache 流程)
- [x] 读取 `data_ingestion_service.py` (48 LOC, 精简版)
- [x] 读取 `data_pipeline_service.py` (32 LOC, clean→validate→adjust 封装)
- [x] 读取 `sources/base.py` (DataSource ABC)
- [x] 读取 `sources/protocols.py` (8 个 Protocol)
- [x] 读取 `sources/tdx.py` (177 LOC, .day 解析)
- [x] 读取 `sources/sina.py` (609 LOC, 限速/重试/UA)
- [x] 读取 `sources/baostock.py` (463 LOC, login→fetch→logout)
- [x] 读取 `sources/realtime_bridge.py` (428 LOC, WebSocket 脚手架)
- [x] 读取 `sources/eastmoney.py` (1094 LOC, 最大文件)
- [x] 读取 `managers/source_router.py` (246 LOC, 故障转移+竞速+熔断)
- [x] 读取 `managers/standard_adapter.py` (92 LOC, 20+ 列名映射)
- [x] 读取 `managers/trade_calendar_manager.py` (194 LOC, 硬编码假期)
- [x] 读取 `managers/stock_metadata_manager.py` (324 LOC, IPO/退市)
- [x] 读取 `managers/market_data_coordinator.py` (99 LOC, 指数/ETF/行业)
- [x] 读取 `managers/factor_manager.py` (452 LOC, 因子管理)
- [x] 读取 `pipeline/data_cleaner.py` (69 LOC, 6 步清洗)
- [x] 读取 `pipeline/data_validator.py` (85 LOC, 7 步验证+自动修复)
- [x] 读取 `pipeline/data_adjuster.py` (308 LOC, 复权核心)
- [x] 读取 `lake/storage_manager.py` (638 LOC, Parquet 数据湖)
- [x] 读取 `parsers/tdx_parser.py` (445 LOC, 二进制解析)
- [x] 读取 `utils/normalizer.py` (294 LOC, 列名映射)
- [x] 读取 `utils/akshare_wrapper.py` (340 LOC, UA 轮换/重试)
- [x] 读取 `utils/smart_factor_calculator.py` (327 LOC, GBBQ V15)
- [x] 读取 `utils/js_executor.py` (347 LOC, JS 逆向)
- [x] 检查数据层测试覆盖 (9 个测试文件)
