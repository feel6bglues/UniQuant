# UniQuant Step 5 前置门: D5 约束 5 — TDX 代码表字段等价性核验与架构定论报告

> **文档标识**：`UNIQUANT-ARCH-20261013-D5-METADATA-VERIFICATION`  
> **报告类型**：数据源迁移 Step 5 前置门（D5 约束 5）专项核验与架构裁决审计报告  
> **审计日期**：2026-10-13  
> **执行环境**：Linux 6.8 / Python 3.12 / mootdx 0.11.7 / pytdx 1.72 / Wine 通达信 6.1GB 底座  
> **关联规范**：`docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md`（§2.8, §D5, 约束 5）、`AGENTS.md`  
> **实测存证**：`scripts/maintenance/verify_tdx_stock_metadata.py` → `results/migration/step5_d5_metadata_verification.json`  
> **门禁状态**：**APPROVED_AND_CLOSED（核验完成，架构裁决生效，D5 约束 5 正式关单）**

---

## 摘要与架构决策总览 (Executive Summary)

依据 `docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md` D5 约束 5 的预注册条款：
> *"TDX 代码表字段等价性（ipoDate/outDate/type/status）专项核验为 Step 5 前置门，未过门不得裁剪任何在线依赖。"*

在 Step 4 中，系统已成功将 baostock 生产链从通用数据源中解耦，独立出私有受管客户端 `src/uniquant/data/managers/_baostock_client.py`，并将 `data/all_stock_codes.csv` 确立为全系统唯一的单副本主数据真相源（SSOT，8,879 行，含 1,176 只历史退市证券）。

本项工作通过编写并实跑自动化核验脚本 [`scripts/maintenance/verify_tdx_stock_metadata.py`](file:///home/james/Documents/Project/UniQuant/scripts/maintenance/verify_tdx_stock_metadata.py)，对通达信本地资产（Wine 目录 `hq_cache/{shs,szs,bjs}.tnf`、`hq_cache/base.dbf`、`vipdoc/**/*.day`、`mootdx.reader.Reader`）及远程行情服务（`pytdx.hq.TdxHq_API`、`mootdx.quotes.Quotes`）进行了穿透式实测与逐字段比对。

### 核心结论与架构裁决

| 检验维度 | 实测结果 | 对下游量化系统影响 | 架构裁决 |
| :--- | :--- | :--- | :--- |
| **退市日 `outDate`** | **全系完全缺失 (0/7)**<br>TDX 本地与网络代码表均无此字段 | `StockMetadataManager.get_delist_date` 恒返回 `None`；退市股被误认存续 | ❌ **TDX 无法作为主数据替代源** |
| **退市证券历史留存** | **物理剔除**<br>600001、600002、600069、600074 查无此股 | 无法识别已退市股票的历史存在，横截面选股全盘产生**幸存者偏差** | ❌ **违背量化研究最核心反偏差纪律** |
| **上市日 `ipoDate`** | **严重缺失**<br>代码表接口无此列（仅本地 base.dbf 存存续股 `SSDATE`） | 无法精准判定历史某截面标的是否已上市 | ❌ **代码表接口不可用** |
| **证券类型 `type` / 状态 `status`** | **完全缺失**<br>全市场 5.2 万标的混编，无分类标识 | 股票、指数、转债、ETF 混淆，无法自动抽取 A 股股票池 | ❌ **元数据语义不完整** |
| **统一引擎退市防线** | **防线被击穿**<br>`UnifiedBacktestEngine` 退市警告静默失效 | 回测退市股票时 `survivorship_warning` 为空，研究员无法感知幸存者偏差 | ❌ **系统性风险不可接受** |

### 架构决定定论

1. **定论 1（永久保留主数据生产者）**：正式将 `src/uniquant/data/managers/_baostock_client.py` 定位为**UniQuant 受管的离线/本地证券主数据同步生产模块**。
2. **定论 2（关闭裁剪待办）**：关闭迁移计划中关于"裁剪 baostock 离线生产链"的待办事项（标记为 `CLOSED / WONTFIX: ARCHITECTURALLY PRESERVED`）。
3. **定论 3（数据契约冻结）**：维持 `data/all_stock_codes.csv`（单副本，UTF-8-BOM，8,879 行）为全系统证券主数据 SSOT。
4. **定论 4（前置门关单）**：D5 约束 5 正式核准并关单，Step 5 获准开展后续工作。

---

## 一、 主数据 SSOT 基准契约 (`data/all_stock_codes.csv`)

现有主数据文件位于 [`data/all_stock_codes.csv`](file:///home/james/Documents/Project/UniQuant/data/all_stock_codes.csv)，由 `baostock_cache_manager.py` 通过 `_baostock_client.py::fetch_stock_list` 同步产出。

### 1.1 数据结构与统计

* **文件规模**：8,879 行（表头 + 8,878 数据行）；
* **字段契约（7 列）**：`code, name, 代码, ipoDate, outDate, type, status`；
* **存续状态分布**：
  * 在市标的 (`status=1`)：**7,702** 只；
  * 已退市标的 (`status=0`)：**1,176** 只（其中 A 股股票 **337** 只、基金/ETF **818** 只、指数 **21** 只）；
* **类型分布 (`type`)**：
  * `1`（股票）：**5,541** 只；
  * `5`（基金/ETF）：**1,622** 只；
  * `4`（可转债）：**1,119** 只；
  * `2`（指数）：**596** 只；
* **日期覆盖率**：`ipoDate` 非空覆盖率 **100%**；已退市标的 `outDate` 非空覆盖率 **100%**。

### 1.2 典型样本数据

```csv
code,name,代码,ipoDate,outDate,type,status
sh.600519,贵州茅台,600519,2001-08-27,,1,1
sh.600001,邯郸钢铁,600001,1998-01-22,2009-12-29,1,0
sh.600002,齐鲁石化,600002,1998-04-08,2006-04-24,1,0
sh.600069,退市银鸽,600069,1997-04-30,2020-08-27,1,0
sh.600074,退市保千,600074,1997-06-23,2020-06-02,1,0
```

---

## 二、 通达信本地接口与文件结构实测

针对本地通达信安装目录（`/home/james/.local/share/tdxcfv/drive_c/tc/`）进行了底层二进制与数据库解析：

### 2.1 本地代码表缓存 `hq_cache/{shs,szs,bjs}.tnf`

通达信本地缓存了 `shs.tnf`（9.9MB）、`szs.tnf`（8.7MB）与 `bjs.tnf`（139KB）。
经逆向解析二进制结构：
* **文件头**：50 字节（包含同步行情的服务器 IP 地址，如 `118.25.98.114`）；
* **记录结构**：固定 **360 字节** / 记录；
* **字段提取**：
  * `offset 0..8`：证券代码（如 `600519`，ASCII）；
  * `offset 31..62`：证券简称（如 `贵州茅台`，GBK）；
  * `offset 76..79`：小数点位数（`decimal_point`，uint32，通常为 2）；
  * `offset 80..83` / `276..279`：交易单位 / 昨收价；
  * `offset 329..344`：拼音简称（如 `GZMT`，ASCII）；
  * 其余字节：均为零填充或内部行情标记。
* **标的容量**：沪市 27,611 只、深市 24,430 只、北交所约 300 只；
* **致命缺陷**：
  * ❌ **完全无 `ipoDate` / `outDate` / `status` / `type`** 字段；
  * ❌ **已退市标的被物理清洗**：实测检索 600001、600002、600069、600074，结果全部为 `NOT FOUND`（0 命中）。

### 2.2 本地 F10 财务/股本基础库 `hq_cache/base.dbf`

`T0002/hq_cache/base.dbf`（56.6 MB）为 DBase III 格式数据库，包含 117,709 条历史记录。
经解析其表头与 40 个字段定义：
* **包含字段**：
  `SC, GPDM, GXRQ, ZGB, GJG, FQRFRG, FRG, BG, HG, LTAG, ZGG, ZPG, ZZC, LDZC, GDZC, WXZC, CQTZ, LDFZ, CQFZ, ZBGJJ, JZC, ZYSY, ZYLY, QTLY, YYLY, TZSY, BTSY, YYWSZ, SNSYTZ, LYZE, SHLY, JLY, WFPLY, TZMGJZ, DY, HY, ZBNB, SSDATE, MODIDATE, GDRS`
* **实测分析**：
  1. 包含 `SSDATE`（上市日期，如 `19910403`）；
  2. ❌ **完全无 `outDate`**（40 个字段无任何退市日期相关字段）；
  3. ❌ **完全无 `name`**（仅有 6 位代码 `GPDM`，无证券中文简称）；
  4. ❌ **完全无 `status` 与 `type`**；
  5. ❌ **退市股记录已被清除**：实测在 117,709 条记录中全表检索 600001、600002、600069、600074，结果全部为 0 记录。

### 2.3 日线文件 `vipdoc/**/*.day` 与 mootdx 本地组件

* **日线文件**：每条 Bar 为固定 32 字节（`date, open, high, low, close, amount, volume, reserved`），完全不包含任何标的元数据；
* **`mootdx.reader.Reader.factory`**：仅提供 `['block', 'block_new', 'daily', 'find_path', 'fzline', 'minute', 'tdxdir']`，无主数据代码表读取接口，`block()` / `block_new()` 仅返回空板块或分类列表。

---

## 三、 通达信远程行情接口实测 (pytdx & mootdx Quotes)

通过实测连接通达信行情主站服务器（`180.153.18.170:7709`）：

### 3.1 `pytdx.hq.TdxHq_API.get_security_list`

* **返回字段**：`['code', 'volunit', 'decimal_point', 'name', 'pre_close']`；
* **样本记录**：
  ```python
  OrderedDict({'code': '600000', 'volunit': 100, 'decimal_point': 2, 'name': '浦发银行', 'pre_close': 424.045})
  ```
* **分析**：纯粹为前端行情看盘服务的代码与昨收表，无任何生命周期信息。

### 3.2 `mootdx.quotes.Quotes.stocks` / `stock_all`

* **返回结构**：全市场 52,051 条记录（混合深市、沪市所有品种）；
* **返回列**：`['code', 'volunit', 'decimal_point', 'name', 'pre_close']`；
* **退市股检验**：
  * `600001`（邯郸钢铁）：`NOT FOUND`
  * `600002`（齐鲁石化）：`NOT FOUND`
  * `600069`（退市银鸽）：`NOT FOUND`
  * `600074`（退市保千）：`NOT FOUND`
  * 证明通达信远程服务器不会向客户端下发任何已退市股票。

### 3.3 F10 财务接口 `client.finance(symbol)`

* **字段分析**：包含 37 列，含 `ipo_date`（上市日期）；
* **退市信息**：❌ 无 `outDate`，无 `status`；
* **退市股查询**：对 `600001` 查询返回**全 0 空记录**（`code=''`，全字段 0.0）；
* **性能与工程评估**：全市场 5,000+ 标的需单只逐次发起网络请求，耗时 >300s，且因退市股直接返回空数据，根本无法恢复退市信息。

---

## 四、 字段级等价性对比矩阵 (Field Equivalence Matrix)

| 主数据字段 | 业务含义与用途 | Baseline (`all_stock_codes.csv`) | TDX 本地缓存 (`.tnf`) | TDX 本地 F10 (`base.dbf`) | TDX 远程接口 (`stocks`) | 等价性裁决 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **`code`** | 统一标的标识 (含前缀) | ✅ `sh.600519` | ⚠️ 6位数字 (`600519`) | ⚠️ 6位数字 (`GPDM`) | ⚠️ 6位数字 (`code`) | **等价** (需规则补前缀) |
| **`name`** | 证券中文简称 | ✅ `贵州茅台` | ✅ `贵州茅台` | ❌ **无名称列** | ✅ `贵州茅台` | **部分支持** (dbf 缺失) |
| **`代码`** | 6位纯数字代码 | ✅ `600519` | ✅ `600519` | ✅ `600519` | ✅ `600519` | **等价** |
| **`ipoDate`** | 上市日期 (YYYY-MM-DD) | ✅ **100% 覆盖** | ❌ **完全缺失** | ⚠️ `SSDATE` (仅限存续股) | ❌ **完全缺失** | ❌ **不具备等价性** |
| **`outDate`** | 退市日期 (YYYY-MM-DD) | ✅ **100% 退市股覆盖** | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **致命缺失** |
| **`type`** | 证券品种类型枚举 | ✅ `1=股票, 2=指数...` | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **不具备等价性** |
| **`status`** | 存续状态 (1=上市, 0=退市) | ✅ `1` / `0` | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **完全缺失** | ❌ **致命缺失** |
| **退市股集合** | 包含历史退市证券 | ✅ **1,176 只** | ❌ **0 只 (全被物理清洗)** | ❌ **0 只 (全被物理清洗)** | ❌ **0 只 (接口不下发)** | ❌ **不可作为主数据** |

---

## 五、 幸存者偏差防线冲击实测 (Simulation of Defense Breach)

在量化投资研究与回测系统中，**幸存者偏差（Survivorship Bias）是足以彻底摧毁策略实盘表现的致命错误**。UniQuant 设计了多重退市守卫机制，强依赖主数据的 `outDate` 与 `ipoDate`：

### 5.1 守卫依赖链条

1. **`StockMetadataManager`**：
   * `get_delist_date(symbol)`：读取 `meta.delist_date`；
   * `is_delisted(code, as_of)`：断言 `info.delist_date <= check_date`；
   * `get_active_stocks(as_of)`：过滤 `not meta.delist_date or meta.delist_date > check_date`。
2. **`UnifiedBacktestEngine`（`:538-550`）**：
   ```python
   # Survivorship bias check (conditional — only if delist data available)
   survivorship_warning = ""
   try:
       mgr = StockMetadataManager()
       delist_date = mgr.get_delist_date(symbol) if hasattr(mgr, 'get_delist_date') else None
       if delist_date is not None:
           last_bar = pd.to_datetime(df["date"].iloc[-1]) if len(df) else None
           if last_bar is not None and pd.to_datetime(delist_date) <= last_bar:
               survivorship_warning = (
                   f"Symbol delisted {delist_date}; "
                   f"backtest extends to {last_bar.date()}"
               )
   except (OSError, KeyError, TypeError):
       pass
   ```

### 5.2 模拟冲击实验对比

以真实退市股票 **`600069.SH`（退市银鸽，退市日 2020-08-27）** 回测跨越退市日（2020-08-01 ~ 2020-09-01）进行实测：

* **现状（Baseline 源）**：
  * `delist_date` 解析结果：`2020-08-27`；
  * `is_delisted(as_of=2021-01-01)`：`True`；
  * `UnifiedBacktestEngine` 输出：
    ```text
    survivorship_warning = "Symbol delisted 2020-08-27; backtest extends to 2020-09-01"
    ```
    ✅ **守卫成功拦截并告警**。

* **若替换为 TDX 代码表**：
  * `delist_date` 解析结果：`None`；
  * `is_delisted(as_of=2021-01-01)`：`False`；
  * `UnifiedBacktestEngine` 输出：
    ```text
    survivorship_warning = ""
    ```
    ❌ **守卫完全静默失效！系统将退市标的当作永续存续标的，回测与全截面选股全面遭受幸存者偏差污染**。

---

## 六、 架构定论与落地执行 (Architectural Verdict & Action Items)

基于上述穿透式实测数据与金融工程防线验证，特作出以下架构终审定论：

### 6.1 裁决决议

1. **否决“使用 TDX 代码表替代主数据源”的提议**：
   TDX 代码表属于面向看盘行情的快照切片，不属于金融工程级主数据（Master Reference Data）。它缺失退市日期、上市日期与品种分类，且物理排除了退市证券，在数学与逻辑上无法承担 UniQuant 研究底座的主数据职责。
2. **正式批准保留 `src/uniquant/data/managers/_baostock_client.py`**：
   Step 4 中实现的解耦方案（内联登录/登出/拉取代码表/拉取日历四能力，脱离 `DataSource` 继承链）是正确且完备的架构形态。该模块作为 UniQuant 受管的**离线/本地主数据同步生产器**予以永久保留。
3. **冻结 `data/all_stock_codes.csv` 为全系统唯一真相源 (SSOT)**：
   继续遵守 D5 约束 1 与约束 2，保持单副本（8,879 行，UTF-8-BOM）并实施缺失抛错（R-5 硬失败）。
4. **关闭迁移计划遗留待办**：
   在 `docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md` 中，将“待 TDX 字段等价性过门后裁剪 baostock 离线生产链”的待办正式注销并标为 `CLOSED / WONTFIX (ARCHITECTURALLY PRESERVED)`。

### 6.2 交付物清单与对账索引

1. **自动化核验工具**：
   [`scripts/maintenance/verify_tdx_stock_metadata.py`](file:///home/james/Documents/Project/UniQuant/scripts/maintenance/verify_tdx_stock_metadata.py)
   * 支持全自动化实跑与 CLI 选项（`--baseline`, `--tdx-dir`, `--output`, `--no-remote`）；
   * 通过 `ruff check` 代码规范检查（0 warnings / 0 errors）。
2. **核验证据归档**：
   [`results/migration/step5_d5_metadata_verification.json`](file:///home/james/Documents/Project/UniQuant/results/migration/step5_d5_metadata_verification.json)
   * 包含全量基准统计、本地 .tnf / .dbf 二进制解析结构、远程 API 实测结果、守卫破坏测试数据及裁决元数据。
3. **前置门状态变更**：
   **Step 5 前置门 D5 约束 5：VERIFIED & PASSED（核验完成，前置条件解除，正式关单）**。
