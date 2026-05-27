# TDX 迁移指南

## 何时使用
从 TDX 项目迁移模块时；执行 Phase 1B/1C/1D/1E 时；适配 mootdx 数据源时。

## TDX 项目信息
- **路径**: `/home/james/Documents/Project/TDX/src/`
- **文件数**: 145 个 Python 源文件
- **结构概览**: 包含 brain、data、hands、risk、services、shared、ui 等完整模块

## 迁移文件映射表

### Phase 1B: Data 全层迁移
| TDX 路径 | UniQuant 目标路径 | 文件数 | 优先级 |
|----------|------------------|--------|--------|
| `data/sources/base.py` | `data/sources/base.py` | 1 | P0 |
| `data/sources/protocols.py` | `data/sources/protocols.py` | 1 | P0 |
| `data/utils/normalizer.py` | `data/utils/normalizer.py` | 1 | P0 |
| `data/sources/tdx.py` | `data/sources/tdx.py` | 1 | P0 |
| `data/sources/baostock.py` | `data/sources/baostock.py` | 1 | P0 |
| `data/sources/sina.py` | `data/sources/sina.py` | 1 | P0 |
| `data/sources/tencent.py` | `data/sources/tencent.py` | 1 | P0 |
| `data/sources/ths.py` | `data/sources/ths.py` | 1 | P0 |
| `data/sources/eastmoney.py` | `data/sources/eastmoney.py` | 1 | P0 |
| `data/sources/realtime_bridge.py` | `data/sources/realtime_bridge.py` | 1 | P0 |
| `data/managers/source_router.py` | `data/managers/source_router.py` | 1 | P0 |
| `data/managers/standard_adapter.py` | `data/managers/standard_adapter.py` | 1 | P0 |
| `data/managers/stock_metadata_manager.py` | `data/managers/stock_metadata_manager.py` | 1 | P0 |
| `data/managers/trade_calendar_manager.py` | `data/managers/trade_calendar_manager.py` | 1 | P0 |
| `data/managers/adjust_factor_manager.py` | `data/managers/adjust_factor_manager.py` | 1 | P0 |
| `data/managers/factor_manager.py` | `data/managers/factor_manager.py` | 1 | P0 |
| `data/managers/tdx_updater.py` | `data/managers/tdx_updater.py` | 1 | P0 |
| `data/managers/stock_data_updater.py` | `data/managers/stock_data_updater.py` | 1 | P0 |
| `data/managers/market_data_coordinator.py` | `data/managers/market_data_coordinator.py` | 1 | P0 |
| `data/managers/cache_manager.py` | `data/managers/cache_manager.py` | 1 | P0 |
| `data/managers/baostock_cache_manager.py` | `data/managers/baostock_cache_manager.py` | 1 | P0 |
| `data/managers/data_normalizer.py` | `data/managers/data_normalizer.py` | 1 | P0 |
| `data/pipeline/data_adjuster.py` | `data/pipeline/data_adjuster.py` | 1 | P0 |
| `data/pipeline/data_cleaner.py` | `data/pipeline/data_cleaner.py` | 1 | P0 |
| `data/pipeline/data_validator.py` | `data/pipeline/data_validator.py` | 1 | P0 |
| `data/parsers/tdx_parser.py` | `data/parsers/tdx_parser.py` | 1 | P0 |
| `data/services/data_importer.py` | `data/services/data_importer.py` | 1 | P0 |
| `data/services/import_1min.py` | `data/services/import_1min.py` | 1 | P0 |
| `data/services/import_5min.py` | `data/services/import_5min.py` | 1 | P0 |
| `data/services/import_financial.py` | `data/services/import_financial.py` | 1 | P0 |
| `data/services/import_index.py` | `data/services/import_index.py` | 1 | P0 |
| `data/services/lppl_data_service.py` | `data/services/lppl_data_service.py` | 1 | P0 |
| `data/lake/storage_manager.py` | `data/lake/storage_manager.py` | 1 | P0 |
| `data/data_fetcher.py` | `data/data_fetcher.py` | 1 | P0 |
| `data/data_ingestion_service.py` | `data/data_ingestion_service.py` | 1 | P0 |
| `data/data_pipeline_service.py` | `data/data_pipeline_service.py` | 1 | P0 |
| `data/__init__.py` | `data/__init__.py` | 1 | P0 |
| `data/all_stock_codes.csv` | `data/all_stock_codes.csv` | 1 | P0 |
| `data/stock_list.csv` | `data/stock_list.csv` | 1 | P0 |

### Phase 2: mootdx 适配 (新建文件)
| TDX 路径 | UniQuant 目标路径 | 文件数 | 优先级 |
|----------|------------------|--------|--------|
| 新建 | `data/sources/mootdx_local.py` | 1 | P0 |
| 新建 | `data/sources/mootdx_online.py` | 1 | P0 |
| 新建 | `data/managers/mootdx_factor_manager.py` | 1 | P0 |
| 新建 | `data/scripts/sync_daily_mootdx.py` | 1 | P1 |
| 新建 | `data/scripts/sync_minute_mootdx.py` | 1 | P1 |
| 新建 | `data/scripts/sync_financial_mootdx.py` | 1 | P1 |
| 新建 | `data/scripts/sync_factors_mootdx.py` | 1 | P1 |

## 迁移通用步骤
1. 拷贝文件
2. 修改 import 路径（alpha_tactician → uniquant）
3. 适配 shared 依赖（用 shared 的常量/异常/配置）
4. 更新目标包 `__init__.py`
5. 验证导入

## Import 路径替换规则
| TDX 路径 | UniQuant 路径 |
|----------|---------------|
| `from src.shared.*` | `from ...shared.*` |
| `from src.brain.*` | `from ...brain.*` |
| `from src.data.*` | `from ...data.*` |
| `from src.hands.*` | `from ...hands.*` |
| `from src.risk.*` | `from ...risk.*` |
| `from src.services.*` | `from ...services.*` |
| `from src.ui.*` | `from ...ui.*` |

## Phase 1B: Data 全层迁移
### 具体文件列表
1. **数据源协议和工具** (3个文件)
   - `data/sources/base.py` (78行)
   - `data/sources/protocols.py` (172行)
   - `data/utils/normalizer.py` (~200行)

2. **数据源实现** (7个文件)
   - `data/sources/tdx.py` (177行)
   - `data/sources/baostock.py` (461行)
   - `data/sources/sina.py` (607行)
   - `data/sources/tencent.py` (367行)
   - `data/sources/ths.py` (620行)
   - `data/sources/eastmoney.py` (1095行)
   - `data/sources/realtime_bridge.py` (425行)

3. **数据管理器** (12个文件)
   - `data/managers/source_router.py` (246行)
   - `data/managers/standard_adapter.py` (94行)
   - `data/managers/stock_metadata_manager.py` (323行)
   - `data/managers/trade_calendar_manager.py` (159行)
   - `data/managers/adjust_factor_manager.py` (173行)
   - `data/managers/factor_manager.py` (454行)
   - `data/managers/tdx_updater.py` (645行)
   - `data/managers/stock_data_updater.py` (148行)
   - `data/managers/market_data_coordinator.py` (99行)
   - `data/managers/cache_manager.py` (68行)
   - `data/managers/baostock_cache_manager.py` (143行)
   - `data/managers/data_normalizer.py` (27行)

4. **数据管道** (3个文件)
   - `data/pipeline/data_adjuster.py`
   - `data/pipeline/data_cleaner.py`
   - `data/pipeline/data_validator.py`

5. **TDX 二进制解析器** (1个文件)
   - `data/parsers/tdx_parser.py` (561行)

6. **数据导入服务** (6个文件)
   - `data/services/data_importer.py` (709行)
   - `data/services/import_1min.py` (303行)
   - `data/services/import_5min.py` (303行)
   - `data/services/import_financial.py` (433行)
   - `data/services/import_index.py` (380行)
   - `data/services/lppl_data_service.py` (252行)

7. **存储层** (1个文件)
   - `data/lake/storage_manager.py` (592行)

8. **数据层核心** (4个文件)
   - `data/data_fetcher.py` (268行)
   - `data/data_ingestion_service.py` (48行)
   - `data/data_pipeline_service.py` (22行)
   - `data/__init__.py` (57行)

9. **数据文件** (2个文件)
   - `data/all_stock_codes.csv`
   - `data/stock_list.csv`

### 迁移步骤
1. 创建 UniQuant 数据目录结构
2. 按顺序复制上述文件
3. 对每个文件执行 import 路径替换
4. 更新 `data/__init__.py` 导入新模块
5. 验证导入：`python -c "from uniquant.data.data_fetcher import DataFetcher; from uniquant.data.lake.storage_manager import StorageManager"`

### 验收标准
- 所有数据层模块可正常导入
- DataFetcher 能初始化并列出数据源
- StorageManager 能读写 Parquet 文件

## Phase 2: mootdx 适配
### 新建文件清单
1. **mootdx 离线数据源** (~100行)
   - `data/sources/mootdx_local.py`
   - 使用 `mootdx.reader.Reader` 读取本地 TDX 数据

2. **mootdx 在线数据源** (~80行)
   - `data/sources/mootdx_online.py`
   - 使用 `mootdx.quotes.Quotes` 获取实时数据

3. **mootdx 因子管理器** (~120行)
   - `data/managers/mootdx_factor_manager.py`
   - 使用 `mootdx.utils.factor.fq_factor` 下载复权因子

4. **同步脚本** (4个文件，各80-120行)
   - `data/scripts/sync_daily_mootdx.py`
   - `data/scripts/sync_minute_mootdx.py`
   - `data/scripts/sync_financial_mootdx.py`
   - `data/scripts/sync_factors_mootdx.py`

### mootdx API 用法
```python
# 离线读取
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir='/path/to/tdx')
daily_data = reader.daily(symbol='600519')

# 在线获取
from mootdx.quotes import Quotes
client = Quotes.factory(market='std', heartbeat=True)
realtime = client.quotes(symbol=['600519'])

# 复权因子
from mootdx.utils.factor import fq_factor
factor = fq_factor('600519', 'qfq')
```

### StorageManager 扩展
在 `data/lake/storage_manager.py` 中新增两个方法：
1. `synthesize_weekly(symbol)` - 日线合成周线
2. `synthesize_monthly(symbol)` - 日线合成月线

## 常见陷阱
- **TDX 的常量定义可能与 shared/constants.py 冲突**：迁移前比较两个项目的常量定义，合并到 UniQuant 的 shared/constants.py
- **TDX 的异常类需要合并到 shared/exceptions.py**：检查 TDX 的异常类，确保不重复定义
- **TDX 的配置路径可能不同**：TDX 使用 `src.*` 绝对导入，UniQuant 使用相对导入，需要批量替换
- **mootdx 版本兼容性**：锁定 mootdx 版本 `~0.11.7`，避免 API 变更
- **缺少依赖**：确保 pyproject.toml 包含 `pybreaker>=1.0.0` 和 `tenacity>=8.0.0`

## 需求 vs 现状对标
| 需求项 | 当前状态 | 所需文件数 | 工作量估计 | 优先级 |
|--------|---------|-----------|-----------|--------|
| **mootdx 作为数据基座** | 🔴 0 行使用代码 | 3 文件新建 | ~2h | **P0** |
| **本地数据湖 (1min/5min/daily)** | 🔴 不存在 | 40+ 文件迁移 | ~1.5h | **P0** |
| **日线→周线/月线合成** | 🔴 不存在 | 扩展 StorageManager | ~0.5h | **P1** |
| **通达信财务数据** | 🔴 不存在 | 6 文件迁移 | ~0.5h | **P1** |
| **mootdx 复权因子** | 🔴 不存在 | 1 文件新建 | ~0.5h | **P1** |
| **数据同步脚本** | 🔴 不存在 | 4 脚本新建 | ~0.5h | **P1** |
| **CZSC 缠论分析** | ✅ 可用 | 0 | 0 | **已就绪** |
| **FSM 状态机** | ⚠️ 需修复导入 | 0 | Phase 0.6 | **已就绪** |
| **LPPL 泡沫检测** | ⚠️ 需修复导入 | 6 文件补充 | Phase 0.2 + 1D | **P2** |
| **NTF 国家队因子** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **Regime 市场状态** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **技术指标库** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **仓位管理 (PositionSizer)** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **组合优化** | ❌ 不存在 | 1 文件迁移 | ~10min | **P2** |
| **回测引擎** | ❌ 不存在 | 19+ 文件迁移 | ~30min | **P2** |
| **内置策略** | ❌ 不存在 | 5+ 文件迁移 | ~15min | **P2** |