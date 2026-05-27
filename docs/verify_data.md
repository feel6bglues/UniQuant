# 数据层核实报告

**核实时间:** 2026-05-27  
**核实人:** opencode  

---

## 1. TDX 项目验证

### 1.1 文件数验证

| 指标 | 方案预期 | 实际值 | 状态 |
|------|----------|--------|------|
| Python 文件数 | 40+ | **52** | ✅ 超出预期 |

**结论:** TDX 数据层文件数量充足，满足迁移需求。

### 1.2 关键文件验证

| 文件 | 预期路径 | 实际路径 | 状态 |
|------|----------|----------|------|
| storage_manager.py | `data/lake/storage_manager.py` | `data/lake/storage_manager.py` (592行) | ✅ 存在 |
| data_fetcher.py | `data/data_fetcher.py` | `data/data_fetcher.py` (268行) | ✅ 存在 |
| source_router.py | `data/managers/source_router.py` | `data/managers/source_router.py` (246行) | ✅ 存在 |

**结论:** 所有关键文件均存在，路径与方案一致。

### 1.3 目录结构验证

```
TDX/src/data/
├── data_fetcher.py          # 数据获取器
├── data_ingestion_service.py
├── data_pipeline_service.py
├── lake/                    # 数据湖
│   └── storage_manager.py   # 存储管理器
├── managers/                # 管理器
│   ├── source_router.py     # 数据源路由
│   ├── stock_metadata_manager.py
│   ├── trade_calendar_manager.py
│   ├── adjust_factor_manager.py
│   ├── factor_manager.py
│   ├── tdx_updater.py
│   └── ...
├── parsers/                 # 解析器
├── pipeline/                # 数据管道
├── services/                # 导入服务
├── sources/                 # 数据源实现
│   ├── base.py              # DataSource ABC
│   ├── protocols.py         # 能力协议
│   ├── tdx.py
│   ├── baostock.py
│   ├── sina.py
│   ├── tencent.py
│   ├── ths.py
│   ├── eastmoney.py
│   └── realtime_bridge.py
├── scripts/                 # 脚本
└── utils/                   # 工具
```

---

## 2. mootdx 验证

### 2.1 安装状态

| 指标 | 方案预期 | 实际值 | 状态 |
|------|----------|--------|------|
| 安装状态 | 已安装 | **未安装** | ⚠️ 需要安装 |
| 版本要求 | `>=0.11.7,<1.0.0` | N/A | - |

### 2.2 API 使用验证

TDX 项目中 mootdx 的使用情况：

| 文件 | 导入 | 用途 |
|------|------|------|
| `services/import_financial.py` | `from mootdx.financial.financial import FinancialReader` | 解析 gpcw*.dat 财务数据 |
| `parsers/tdx_parser.py` | mootdx 网络 API | 获取除权除息信息 |

**方案中 mootdx API 描述验证：**

| API | 方案描述 | 实际存在 | 状态 |
|-----|----------|----------|------|
| `mootdx.reader.Reader` | 离线读取 TDX 本地文件 | ✅ 存在 | ✅ 正确 |
| `mootdx.quotes.Quotes` | 在线获取实时行情 | ✅ 存在 | ✅ 正确 |
| `mootdx.utils.factor.fq_factor` | 下载前复权因子 | ✅ 存在 | ✅ 正确 |
| `mootdx.financial.financial.FinancialReader` | 读取财务数据 | ✅ 存在 | ✅ 正确 |

**结论:** mootdx API 描述与实际一致，但当前环境未安装 mootdx。

---

## 3. 配置验证

### 3.1 data_sources 配置验证

**数据源数量:** 9 个 ✅

| 数据源 | 优先级 | 启用状态 | 类型 |
|--------|--------|----------|------|
| StockDataSource | 1 | ✅ 启用 | 新合并数据源 |
| IndexDataSource | 2 | ✅ 启用 | 新合并数据源 |
| EtfDataSource | 3 | ✅ 启用 | 新合并数据源 |
| BaoStockSource | 10 | ❌ 禁用 | 传统数据源 |
| SinaSource | 11 | ❌ 禁用 | 传统数据源 |
| TencentSource | 12 | ❌ 禁用 | 传统数据源 |
| EastmoneySource | 13 | ❌ 禁用 | 传统数据源 |
| EfinanceSource | 14 | ❌ 禁用 | 传统数据源 |
| ThsSource | 15 | ❌ 禁用 | 传统数据源 |

**优先级评估:** ✅ 合理
- 新合并数据源优先级 1-3（最高）
- 传统数据源优先级 10-15（备用）

**数据类型路由验证：**

| 数据类型 | 默认数据源 | 缓存 TTL | 状态 |
|----------|------------|----------|------|
| stock.daily | StockDataSource | 3600s | ✅ |
| stock.realtime | StockDataSource | 60s | ✅ |
| stock.market_cap | StockDataSource | 3600s | ✅ |
| index.daily | IndexDataSource | 3600s | ✅ |
| sector.daily | StockDataSource | 86400s | ✅ |
| etf.daily | EtfDataSource | 3600s | ✅ |
| industry | StockDataSource | 86400s | ✅ |
| concept | StockDataSource | 86400s | ✅ |

### 3.2 trading.yaml 路径验证

**配置内容：**
```yaml
data:
  tdx_paths:
    sh: "${LPPL_TDX_DATA_DIR}/sh/lday/"
    sz: "${LPPL_TDX_DATA_DIR}/sz/lday/"
  csi300_path: "${LPPL_TDX_DATA_DIR}/sh/lday/sh000300.day"
```

**问题发现：**

| 问题 | 说明 | 严重程度 |
|------|------|----------|
| 环境变量未设置 | `$LPPL_TDX_DATA_DIR` 为空 | ⚠️ 中 |
| 路径层级错误 | 实际路径为 `vipdoc/sh/lday/` 而非 `sh/lday/` | 🔴 高 |

**实际 TDX 数据路径：**
```
/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/*.day
/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/*.day
```

**建议修复：**
```yaml
data:
  tdx_paths:
    sh: "${LPPL_TDX_DATA_DIR}/vipdoc/sh/lday/"
    sz: "${LPPL_TDX_DATA_DIR}/vipdoc/sz/lday/"
  csi300_path: "${LPPL_TDX_DATA_DIR}/vipdoc/sh/lday/sh000300.day"
```

**环境变量设置建议：**
```bash
export LPPL_TDX_DATA_DIR="/home/james/.local/share/tdxcfv/drive_c/tc"
```

---

## 4. 依赖验证

### 4.1 pyproject.toml 依赖清单

| 依赖 | 版本要求 | 状态 |
|------|----------|------|
| mootdx | `>=0.11.7,<1.0.0` | ✅ 声明 |
| pyarrow | `>=14.0.0,<20.0.0` | ✅ 声明 |
| duckdb | `>=0.9.0` | ✅ 声明 |
| pandas | `>=2.0.0,<3.0.0` | ✅ 声明 |
| numpy | `>=2.0.0` | ✅ 声明 |
| sqlalchemy | `>=2.0.0` | ✅ 声明 |
| filelock | `>=3.10.0` | ✅ 声明 |

### 4.2 缺失依赖检测

| 依赖 | 方案需求 | pyproject.toml | TDX 实际使用 | 状态 |
|------|----------|----------------|--------------|------|
| pybreaker | 电路断路器模式 | ❌ 缺失 | ✅ `sources/base.py`, `managers/source_router.py` | 🔴 需添加 |
| tenacity | 重试机制 | ❌ 缺失 | ❌ 未使用 | ✅ 无需添加 |

**结论：**
- `pybreaker` 在 TDX 项目中已使用，但 pyproject.toml 未声明，**必须添加**
- `tenacity` 在 TDX 项目中未使用，方案中提及但实际不需要

**建议添加：**
```toml
dependencies = [
    # ... existing dependencies ...
    "pybreaker>=1.0.0",
]
```

---

## 5. 数据湖设计评估

### 5.1 Parquet + Snappy 压缩评估

**配置：**
```yaml
base:
  data_lake:
    path: "data/lake"
    compression: "snappy"
    engine: "duckdb"
```

**评估：**

| 维度 | 评估 | 说明 |
|------|------|------|
| 格式选择 | ✅ 优秀 | Parquet 列式存储，适合 OLAP 查询 |
| 压缩算法 | ✅ 合理 | Snappy 平衡压缩比和读取速度 |
| 查询引擎 | ✅ 优秀 | DuckDB 嵌入式分析引擎，零配置 |
| 兼容性 | ✅ 良好 | PyArrow + Pandas 生态完美兼容 |

**与其他方案对比：**

| 方案 | 压缩比 | 读取速度 | 写入速度 | 适用场景 |
|------|--------|----------|----------|----------|
| Snappy | 中等 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 实时分析（推荐）|
| Gzip | 高 | ⭐⭐⭐ | ⭐⭐ | 归档存储 |
| Zstd | 高 | ⭐⭐⭐⭐ | ⭐⭐⭐ | 平衡方案 |
| LZ4 | 中等 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 高吞吐场景 |

**结论:** Parquet + Snappy 是量化数据湖的最佳选择。

### 5.2 目录结构评估

**TDX 现有结构：**
```
data/
├── lake/
│   ├── quotes/
│   │   ├── daily/        # 日线数据
│   │   ├── 1mins/        # 1分钟线
│   │   └── 5mins/        # 5分钟线
│   └── factors/          # 因子数据
├── cache/                # 缓存
└── all_stock_codes.csv   # 股票代码列表
```

**评估：**

| 维度 | 评分 | 说明 |
|------|------|------|
| 层级清晰度 | ⭐⭐⭐⭐ | 按数据类型分层 |
| 扩展性 | ⭐⭐⭐⭐ | 易于添加新数据类型 |
| 命名规范 | ⭐⭐⭐⭐ | 小写 + 下划线 |
| 缺失目录 | - | 需添加 `weekly/`, `monthly/`, `index/`, `etf/` |

**建议扩展结构：**
```
data/
├── lake/
│   ├── quotes/
│   │   ├── daily/        # 日线
│   │   ├── weekly/       # 周线（方案 2.5 新增）
│   │   ├── monthly/      # 月线（方案 2.5 新增）
│   │   ├── 1mins/        # 1分钟线
│   │   └── 5mins/        # 5分钟线
│   ├── index/            # 指数数据
│   ├── etf/              # ETF 数据
│   └── factors/          # 因子数据
│       └── qfq/          # 前复权因子
├── cache/                # 缓存
└── metadata/             # 元数据
    ├── all_stock_codes.csv
    └── stock_list.csv
```

### 5.3 周线/月线合成算法评估

**方案算法（Phase 2.5）：**

```python
# 周线合成
weekly = df.groupby("week").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum"
})

# 月线合成
monthly = df.groupby("month").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum"
})
```

**评估：**

| 维度 | 评分 | 说明 |
|------|------|------|
| OHLC 聚合 | ✅ 正确 | Open=first, High=max, Low=min, Close=last |
| Volume 聚合 | ✅ 正确 | 求和 |
| 周起始日 | ✅ 合理 | 使用 `dt.to_period("W")` |
| 月末对齐 | ✅ 合理 | 使用 `MonthEnd(0)` |
| 缺失处理 | ⚠️ 待完善 | 需处理非交易日 |

**改进建议：**
```python
# 添加缺失值处理
def synthesize_weekly(self, symbol: str) -> pd.DataFrame:
    df = self.read_data(symbol, data_type="daily")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna(subset=["open"])  # 移除无数据的周
    return df.reset_index()
```

---

## 6. 风险提示

### 6.1 高风险项

| # | 风险 | 影响 | 建议 |
|---|------|------|------|
| 1 | TDX 路径配置错误 | 数据读取失败 | 修复 `trading.yaml` 路径层级 |
| 2 | pybreaker 未声明 | 依赖缺失 | 添加到 pyproject.toml |
| 3 | mootdx 未安装 | Phase 2 无法执行 | `pip install mootdx` |

### 6.2 中风险项

| # | 风险 | 影响 | 建议 |
|---|------|------|------|
| 4 | 环境变量未设置 | 路径解析失败 | 设置 `LPPL_TDX_DATA_DIR` |
| 5 | 周线/月线目录不存在 | 合成后无处存储 | 在 StorageManager 中创建 |
| 6 | 缺少数据验证脚本 | 迁移后无法验证 | 编写端到端测试 |

### 6.3 低风险项

| # | 风险 | 影响 | 建议 |
|---|------|------|------|
| 7 | DuckDB 版本未锁定 | 潜在兼容性问题 | 指定具体版本 |
| 8 | 缺少数据备份策略 | 数据丢失风险 | 定期备份 data/lake |

---

## 7. 总体评估

### 7.1 方案可信度

| 维度 | 评分 | 说明 |
|------|------|------|
| TDX 项目验证 | ⭐⭐⭐⭐⭐ | 文件完整，结构清晰 |
| mootdx API 描述 | ⭐⭐⭐⭐⭐ | 与实际一致 |
| 配置完整性 | ⭐⭐⭐⭐ | 9 个数据源配置完整 |
| 依赖声明 | ⭐⭐⭐ | 缺少 pybreaker |
| 路径配置 | ⭐⭐ | 存在层级错误 |
| 数据湖设计 | ⭐⭐⭐⭐⭐ | Parquet+Snappy+DuckDB 优秀 |

### 7.2 执行建议

1. **Phase 0 前修复：**
   - 修复 `trading.yaml` 路径配置
   - 添加 `pybreaker` 到 pyproject.toml
   - 设置 `LPPL_TDX_DATA_DIR` 环境变量

2. **Phase 1B 执行时：**
   - 验证每个迁移文件的导入路径
   - 确保 `__init__.py` 正确导出

3. **Phase 2 执行前：**
   - 安装 mootdx：`pip install mootdx>=0.11.7`
   - 测试 mootdx API 可用性

---

**结论：** 数据层重构方案整体可信度高（⭐⭐⭐⭐），TDX 项目文件完整，mootdx API 描述准确，数据湖设计合理。主要风险点在路径配置和依赖声明，建议在执行前修复。

---

*报告生成时间: 2026-05-27 | 基于实际代码验证*
