# 子代理独立复核：数据流转模块 N2N 深度分析

> **复核日期**：2026-11-24
> **复核基线**：`b1d2415`（当前 HEAD，docs-only 提交）
> **分析范围**：`src/uniquant/data/`（40 文件，7,808 行）＋ 消费侧 `services/data_service.py`、`services/data_access_service.py`
> **方法**：Name-to-Name 节点级独立审查（未先读既有报告，先独立取证，后交叉复核）
> **对比基线**：既有 Claude 单代理报告 `docs/analysis/n2n/01_data_flow_n2n.md`（基线 `434aab1`，第 25 轮）
> **复核人**：独立代码审查子代理（SenseNova 6.8 Flash Lite）

---

## 1. 执行摘要

- **规模**：`src/uniquant/data/` 40 文件 7,808 行；消费侧 `data_service.py`(655) + `data_access_service.py`(354) + `data_quality_service.py`(347)。
- **核心契约**：9 列冻结契约 `GET_PRICE_LAKE_COLUMNS`（`data_fetcher.py:41-51`，`amount` 在 `volume` 前）经湖实测逐位吻合（随机 8 个湖文件列序/dtype/`reserved` 全对；`date`=datetime64[ns]）。
- **健康度评级**：**B-（部分可信）**。契约治理（9 列 / C3 禁 bfill / R2 写湖护栏 / 复权因子非法值 raise）真实有效且经实测核对；但**运行时数据路径存在 3 处 HIGH**（调整状态不一致、验证器无调用方、新鲜度门禁未进运行时），其中 **2 处为既有报告遗漏**。
- **问题计数**：CRITICAL **0** · HIGH **3** · MEDIUM **4** · LOW **3**（共 10）。
- **与既有报告分歧**：既有报告 3 项（M1/L1/L2）+ 自评"原子写全覆盖 ✅"；本复核**新增 5 项**（H1 调整不一致 / H2 验证器死调用 / M1 原子写覆盖不全 / M2 自校准静默 no-op / M3 同步脚本裸卷耦合），**上调 2 项**（FreshnessValidator M1→HIGH、在线静默返回 LOW→MEDIUM），并确认既有报告 §5.2"第 25 轮已修复"表述**不成立**（434aab1 未触及 freshness_validator / storage_manager）。

---

## 2. N2N 五问逐节点答案

> 节点定义（按任务给定关键路径）：`sources → parser → cleaner → validator → adjuster → atomic_write → lake → fetcher → data_service → analysis_service`。
> 以下"Q1 名称定义 / Q2 名称映射 / Q3 名称传播 / Q4 名称变异 / Q5 名称治理"以**列名与量纲**为主线（任务口径）。

### 节点 A：数据源（`sources/`）

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | `tdxdata_online` 输出列契约自定：`DAILY_COLUMNS=[date,open,high,low,close,volume,amount,code]`(8 列，无 reserved)、`MINUTE_COLUMNS=[datetime,...]`、`REALTIME_COLUMNS=[code,market,last,series_points,compressed]`；`mootdx_local` **无显式输出契约**，依赖 reader 输出 + `normalize_mootdx_columns`。 | `tdxdata_online.py:41,100,106`；`mootdx_local.py:74,179-183` |
| Q2 映射 | `datetime→date`(rename)、`vol→volume`(×100 转股，日线)；分钟线 vol 已是股**不换算**；mootdx 走 `normalize_mootdx_columns`(`datetime→date`,`vol→volume`，目标列已存在不覆盖)。 | `tdxdata_online.py:210-211,256-257,98`；`normalizer.py:80-92` |
| Q3 传播 | 源输出 **8 列**（无 reserved），9 列契约仅在下游 `_normalize_price_frame` 的 `reindex` 补齐。 | `tdxdata_online.py:41`；`data_fetcher.py:358` |
| Q4 变异 | 日线 `vol×100`（手→股）；分钟线保持股；`fetch_real_time` 只输出 `last`（不解析 prev_close/open、不伪造 high/low，Rule 4）。 | `tdxdata_online.py:211,257,275-307` |
| Q5 治理 | `base.py:24-29` `name` 属性 = 类名去 `Source` 后缀；`get_capabilities()` 能力矩阵。**主机默认硬编码 `101.35.121.35`**（单点，无冗余评估）。 | `base.py:24-29`；`tdxdata_online.py:13-14,112-130` |

### 节点 B：解析器（`parsers/tdx_parser.py`）

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | `.day` 解析输出 8 列 `[date,open,high,low,close,amount,volume,reserved]`（非 9 列，无 code）；gbbq 输出冻结 8 列契约 `_GBBQ_TARGET_COLS`。 | `tdx_parser.py:190-192,60-70` |
| Q2 映射 | gbbq 拼音主映射 + 中文兼容别名合并 `_GBBQ_COLUMN_MAPPING`；`date` 归一为 **int YYYYMMDD**。 | `tdx_parser.py:34-58,76-92,126-133` |
| Q3 传播 | gbbq 列序冻结 `_enforce_gbbq_contract`（缺列 raise，函数尾统一出口）。 | `tdx_parser.py:95-100` |
| Q4 变异 | `.day` 价格按代码前缀除 10000/1000/100；`code` 补零 6 位；date 转 datetime64；dropna。 | `tdx_parser.py:209-226,123-124` |
| Q5 治理 | `.day` 非 32 倍数 → warning 但继续（截断到完整记录边界）；gbbq 解析失败返回空表不 raise（见 M4 同类）。 | `tdx_parser.py:172-183,280-287` |

### 节点 C：清洗（`pipeline/data_cleaner.py`）

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | 输入契约 `_assert_input_contract`：必需 `date,close,amount,volume`；**禁止 vol/volume 双 schema**（有 vol 无 volume → raise）。 | `data_cleaner.py:88-114` |
| Q2 映射 | 列名小写化；`vol→volume` **不做**（有 vol 无 volume 直接 raise，强制上游统一）。 | `data_cleaner.py:22,105-110` |
| Q3 传播 | 输出保留清洗后帧 + `attrs["cleaner_repaired"]` 审计标记（不加新列，C4）。 | `data_cleaner.py:82` |
| Q4 变异 | 拷贝后改列名；`open/high/low` **仅 ffill**（C3 禁 bfill）；`close` NaN 先 dropna；`amount` NaN 原样保留；OHLC 一致性修复；按 date 去重保序。 | `data_cleaner.py:17,47,52-54,39-44,56,58-76` |
| Q5 治理 | C3 红线（禁 bfill）仅在 `data_cleaner.py:51-54` 注释与 ffill 代码处体现，**无机器断言**（无测试在 bfill 路径上 fail-closed，仅 `test_data_cleaner_contract.py` 覆盖）。 | `data_cleaner.py:51-54` |

### 节点 D：验证（`pipeline/data_validator.py`）—— **死节点**

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | 只读门禁：必需 8 列 `[date,code,open,high,low,close,volume,amount]`；核心数值非空；High<Low / High<Open,Close / Low>Open,Close 硬阻断；volume<0 阻断。 | `data_validator.py:26-61` |
| Q2 映射 | 无（纯只读）。 | `data_validator.py:17-18` |
| Q3 传播 | **无运行时调用方**：全仓 `rg` 仅 `data_pipeline_service.py:29`（`DataPipelineService.process`）调用 `.validate`，而 `DataPipelineService` 在 src/scripts/tests **零调用**。 | `data_pipeline_service.py:27-40`（唯一调用点，无消费者）；`rg` 全库无其他引用 |
| Q4 变异 | 无（只读，不修改输入）。 | `data_validator.py:12-14` |
| Q5 治理 | 设计原则"严格返回 False 阻断落盘"**未在运行时生效**——真实写湖路径 `fetch_and_save_dataset` 只 clean + R2 断言，**不调用 validate**。 | `data_access_service.py:145-157`（写湖前无 validate）；`data_fetcher.py` 全链无 validate |

### 节点 E：复权（`corporate_action.py`）

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | `adjust()` 只改 OHLC（`price_cols`），`volume` 不动，新增 `adj_factor` 列。 | `corporate_action.py:148,176-180` |
| Q2 映射 | `qfq_ratio=factor/latest_factor`；`hfq_ratio=factor`。 | `corporate_action.py:132-134` |
| Q3 传播 | 因子来自 `SmartFactorCalculatorV15`；缺失 gbbq 基线 `GbbqBaselineMissingError`（硬失败）。 | `corporate_action.py:28-39,67-72` |
| Q4 变异 | OHLC×ratio（float64）；因子非正/非有限 → **raise**（禁静默单位矩阵）。 | `corporate_action.py:123-130,176-178` |
| Q5 治理 | D2 同源裁决：基线缺失/空 → 硬失败；因子非法 → raise。**强治理，真实有效**。 | `corporate_action.py:61-72,121-130` |

### 节点 F：原子写（`lake/storage_manager.py`）—— **覆盖不全**

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | `write_parquet`：路径遍历校验(`is_relative_to`) → FileLock → tmp+`os.replace` → 失败 unlink tmp。 | `storage_manager.py:118-163` |
| Q2 映射 | 空 df → False；已存在且 !overwrite → False。 | `storage_manager.py:122-124,144-146` |
| Q3 传播 | `write_data`(overwrite=True) 委托 `write_parquet`；`data_access_service` 写湖走此链。 | `storage_manager.py:484-489`；`data_access_service.py:150-152` |
| Q4 变异 | 无（写入不修改 df）。 | — |
| Q5 治理 | **原子写未覆盖全部写入路径**：5 处直写 `to_parquet` 绕过 tmp+replace，含 gbbq.parquet 基线（复权依赖）。 | `tdx_parser.py:391,405,432`；`import_financial.py:352`；`smart_factor_calculator.py:239`（直写）；`storage_manager.py:150-153`（唯一原子化） |

### 节点 G：湖读取与标准化（`data_fetcher.py`）

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | 返回契约 `GET_PRICE_RETURN_CONTRACT`（9 列 + adjusted 10 列；date dtype；升序去重；volume=股/amount=元；sources 三元组；write_back=never）。 | `data_fetcher.py:54-68` |
| Q2 映射 | `_normalize_price_frame`：date→datetime64、升序、去重、`reindex(GET_PRICE_LAKE_COLUMNS)`（缺失 reserved 补 NaN）。 | `data_fetcher.py:344-359` |
| Q3 传播 | `_read_raw_price`：湖→本地 mootdx→在线 tdxdata 三级；`_apply_adjustment` 仅 qfq/hfq 触发复权。 | `data_fetcher.py:259-269,361-373` |
| Q4 变异 | 本地兜底 `harmonize_local_volume_unit`：`amount/(close*volume)` 中位 ∈ `[60,160]` → ×100；**<5 有效行静默跳过**。 | `data_fetcher.py:98-125,113-114` |
| Q5 治理 | 湖为 raw SSOT（R2 护栏禁复权落湖）；`write_back=never`（fetcher 只读不写湖）。 | `data_access_service.py:167-208`；`data_fetcher.py:67` |

### 节点 H：数据服务与大脑（`services/data_service.py` + `data_access_service.py`）—— **H1 调整不一致**

| 问 | 答案 | 证据 |
|---|---|---|
| Q1 定义 | `fetch_for_brain` 返回 `{stock, bench, etf}`；`ResearchDataPack.from_dict` 类型化。 | `data_service.py:456-466,468-483` |
| Q2 映射 | `bench` 显式 `sh000300`(index)，`etf` 显式 510300。 | `data_service.py:462-465` |
| Q3 传播 | `AnalysisService.run_ticker_analysis` 消费 `data_service.fetch_for_brain`。 | `analysis_service_v2.py:328`；`health_service.py:246` |
| Q4 变异 | **`load_data_with_fallback` 对同一 symbol 产出两种复权状态**：湖命中→返回**原始价**（`data_access_service.py:214-217`）；湖 miss→`adjust="qfq"`（`data_access_service.py:238`）返回**前复权价**。 | `data_access_service.py:214-217` vs `238-244` |
| Q5 治理 | 注释声明"stock 显式走 qfq（研究/展示口径）"与湖命中分支（raw）**自相矛盾**；湖为 raw SSOT（R2）故湖命中必 raw。 | `data_access_service.py:235-237`；`167-208` |

---

## 3. 端到端数据流路径（≥3 条，含异常路径）

### 路径 1（正常·湖命中·大脑取数）
```
AnalysisService.run_ticker_analysis (analysis_service_v2.py:328)
  → DataService.fetch_for_brain (data_service.py:456)
    → load_data_with_fallback(symbol,"stock") (data_access_service.py:210)
      → lake.read_data (data_access_service.py:214)  [湖命中, 返回 raw 9列]
      → _clone_dataframe (data_access_service.py:217)  [无复权, 无清洗]
  → stock = RAW 原始价 9 列  → AnalysisService
```
- 9 列契约保持 ✅；`date` datetime64 ✅；但**未复权、未二次清洗**。

### 路径 2（正常·湖 miss→本地兜底）
```
DataFetcher.get_price(symbol,"qfq") (data_fetcher.py:211)
  → _read_raw_price (data_fetcher.py:259)
    → _read_lake → miss (data_fetcher.py:271)
    → _fetch_local_fallback (data_fetcher.py:292)
      → MootdxLocalSource.fetch_daily (mootdx_local.py:52) [volume=手]
      → harmonize_local_volume_unit (data_fetcher.py:312) [ratio∈[60,160]→×100]
    → _normalize_price_frame (data_fetcher.py:344) [reindex 补 reserved=NaN, 9列]
    → _apply_adjustment qfq (data_fetcher.py:255,361) [OHLC×ratio + adj_factor]
  → 10 列前复权
```

### 路径 3（正常·湖+本地双 miss→在线兜底）
```
DataFetcher.get_price (data_fetcher.py:211)
  → _fetch_online_fallback (data_fetcher.py:314)
    → TdxDataOnlineSource.fetch_daily (tdxdata_online.py:198)
      → _fetch_all_daily_rows (tdxdata_online.py:188) [翻页 800×30]
      → df["volume"]=df["vol"]*100 (tdxdata_online.py:211) [手→股]
      → df[DAILY_COLUMNS] (8列) (tdxdata_online.py:214)
    → _normalize_price_frame (data_fetcher.py:344) [补 reserved]
    → _apply_adjustment qfq (data_fetcher.py:361)
  → 10 列前复权
```

### 路径 4（异常·写崩溃恢复）—— 已覆盖主湖路径
```
StorageManager.write_parquet (storage_manager.py:118)
  → FileLock(lock_path) (storage_manager.py:149)
  → df.to_parquet(tmp_path) (storage_manager.py:152)  [tmp = .{name}.tmp.{pid}]
  → os.replace(tmp, target) (storage_manager.py:153)  [原子替换]
  → 异常: unlink(tmp) (storage_manager.py:156-163)
```
- **主湖路径原子化 ✅**；但**写崩溃恢复未覆盖全部写入路径**（见 M1）。硬 kill 残留 `.tmp` 无启动清扫（L3）。

### 路径 5（异常·空数据/NaN/量纲）
```
get_price 三源全 miss → _empty_price_frame(adjust) (data_fetcher.py:376-384)  [带契约列空表]
DataCleaner.clean: amount NaN 原样保留 + warning (data_cleaner.py:39-44)
harmonize_local_volume_unit: valid<5 → return df 原样 (data_fetcher.py:113-114)  [静默 no-op, M2]
```

### 路径 6（异常·**调整状态不一致**）—— 本复核核心发现
```
湖命中:   stock = RAW 9列        (data_access_service.py:214-217)
湖 miss:  stock = QFQ 10列       (data_access_service.py:238-244)
→ 同一 symbol 两次运行（先湖 miss 后湖补齐）信号量纲/比例不同，信号不可比。
```

---

## 4. 问题清单（分级 + 证据）

### CRITICAL — 0

### HIGH — 3

**H1｜`load_data_with_fallback` 调整状态不一致（大脑取数）**
- **位置**：`services/data_access_service.py:214-217`（湖命中返回 raw）vs `:238-244`（湖 miss 走 `adjust="qfq"` 返回前复权）。
- **证据**：湖为 raw SSOT（R2 护栏 `:167-208` 禁复权落湖；湖实测 schema 为原始价）；同一函数对同一 symbol 因湖存在与否返回**两种复权状态**。注释 `:235-237` 自称"研究/展示口径=qfq"，与湖命中分支（raw）自相矛盾。`AnalysisService`(`analysis_service_v2.py:328`) 直接消费。
- **影响**：同一标的在"湖未入库时"（如新股、刚被清扫）信号基于前复权价，"入库后"信号基于原始价；量纲/比例不同，信号/因子/回测不可比。违反单一数据口径原则。
- **修复建议**：统一口径——湖命中分支也经 `_apply_adjustment`（若研究/展示要 qfq），或 fallback 分支显式 `adjust=""`（与湖一致 raw）；二者择一，加回归测试断言两分支输出量纲一致。

**H2｜`DataValidator.validate` 无运行时调用方（只读门禁死代码）**
- **位置**：`data/pipeline/data_validator.py`（定义）＋唯一调用 `data_pipeline_service.py:29`（`DataPipelineService.process`，该 `process` 在 src/ 运行时从未被调用）。
- **证据**：`rg "DataValidator|\.validate\(" src/` 仅命中 `data_pipeline_service.py:29`（`DataPipelineService.process`）；`DataPipelineService.process` 在 `src/` **从未被调用**（`rg ".process\(" src/uniquant/services/ src/uniquant/data/` 仅命中 `financial_bridge.process`/`factor_composer.process`，非同对象）。`DataPipelineService` 仅经懒加载工厂 `data/__init__.py:51-53`（`get_data_service("DataPipeline")`）暴露，而该工厂路径**在 src/ 运行时从未被请求**（`rg "get_data_service|DataPipeline\(" src/` 无命中）；仅测试 `tests/data/test_market_coordinator_and_pipeline.py:20,219` 实例化。真实写湖路径 `data_access_service.fetch_and_save_dataset`(`:145-157`) 只 `clean_stock_daily` + `_assert_unadjusted_for_lake`，**从不 validate**。
- **影响**：`High<Low`、`High<Open/Close`、`volume<0`、核心列 NaN 等只读硬阻断在运行时**不生效**；破损帧可经 cleaner 修复后直接落湖，无独立门禁复核（cleaner 是"修复器"，validator 才是"裁判"，裁判未上场）。
- **修复建议**：在 `fetch_and_save_dataset`/`rebuild_cache`/`load_data_with_fallback` 写湖前插入 `validator.validate(cleaned_df)`，False 则阻断落盘；或删除 `DataPipelineService` 死壳并明确 validator 的运行时接线。补一条"写湖必经 validate"的集成测试。

**H3｜FreshnessValidator 未进运行时路径（SLA 有名无实）**
- **位置**：`lake/freshness_validator.py`（定义）+ 仅 `scripts/maintenance/check_freshness_sla.py:102`、`run_n2n_verification.py:183` 调用。
- **证据**：`validate_freshness` 全仓仅 2 个脚本调用；`health_service.py:383` 的 `data_freshness` 走的是另一套 `_last_fetch_time`（内存，非磁盘 SLA），**不调 FreshnessValidator**；`StorageManager` 集成(`:105`)存在但运行时无人触发。基线 `b1d2415` 为 docs-only，未修复；`434aab1`（第 25 轮）也未触及 `freshness_validator.py`/`storage_manager.py`（`git show --stat 434aab1` 无相关文件）。
- **影响**：数据湖滞后时系统照常取数/交易，两级 SLA 门禁等于没有。与 Rule 4（Fail-Closed）矛盾。
- **修复建议**：在 `DataService.fetch_for_brain` 或 `ServiceContainer.initialize` 注入 `validate_freshness`（告警或阻断）；把 `check_freshness_sla.py` 的 crontab 巡检结果回传运行时共享状态。

### MEDIUM — 4

**M1｜原子写覆盖不全（含复权基线 gbbq.parquet）**
- **位置**：`data/parsers/tdx_parser.py:391,405,432`（`save_gbbq_data`/`save_stock_gbbq_data`/`save_gbbq_to_fq` 直写 `to_parquet`）；`data/services/import_financial.py:352`；`data/utils/smart_factor_calculator.py:239`。
- **证据**：`rg "to_parquet" src/uniquant/data/` 共 9 处，其中仅 4 处（`storage_manager.py:152`、`futures_storage_manager.py:565`、`total_return_benchmark.py:103`、`delisted_ingestor.py:198`）配 `os.replace`；**5 处直写无原子化**。`save_gbbq_to_fq`(`:432`) 写入 `data/fq/gbbq.parquet`——这是 `CorporateActionAdjuster` 的**复权基线**，中途崩溃即损坏/截断，`load_events` 将硬失败（`corporate_action.py:67-72`），基线文件本身非原子保护。
- **影响**：gbbq 基线、财务数据、因子数据的写崩溃恢复缺口；主湖路径（StorageManager）已原子化但**并非全部写入路径**。
- **修复建议**：把 5 处直写统一收敛到 `StorageManager.write_parquet` 的 tmp+`os.replace` 模式（或独立原子写工具），补崩溃仿真测试覆盖 gbbq/import_financial。

**M2｜量纲自校准静默 no-op（<5 有效行）**
- **位置**：`data_fetcher.py:113-114`。
- **证据**：`valid = df[(close>0)&(volume>0)&(amount>0)]; if len(valid) < 5: return df`——样本不足 5 时**静默返回**，不做任何量纲判断。若本地兜底返回手单位（ratio≈100）但有效行 <5（新股/停牌密集段），volume 以**手**进入下游 9 列契约，违反 `volume_unit="shares"`。
- **影响**：局部量纲错判，下游 `amount/(close*volume)` 因子被污染；无告警、无对账。
- **修复建议**：`len(valid)<5` 时至少 `logger.warning` 并标记 attrs；或改为"非空即按全表 ratio 粗判 + 样本不足时 fail-closed 返回空表"。补一条 <5 行手单位帧的回归测试。

**M3｜同步脚本裸卷耦合（湖 volume 未校准，依赖 .day 原始字段为股）**
- **位置**：`scripts/maintenance/sync_local_tdx_day.py:186`、`scripts/maintenance/sync_online_daily.py:95`（`"volume": int(r[6])` 直写原始字段，不经 `harmonize_local_volume_unit`）。
- **证据**：湖实测 `amount/(close*volume)` 中位 ≈ 1.0（8 样本 0.9987~1.0009），当前一致性成立；但该一致性**隐含依赖**"TDX .day volume 字段=股"这一未声明假设——若某 TDX 版本 .day volume 为手，湖将被静默写入手单位，而 `GET_PRICE_RETURN_CONTRACT` 仍宣称 volume=股，且 `data_fetcher` 对湖路径**不校准**（`harmonize_local_volume_unit` 仅用于本地兜底，`data_fetcher.py:312`）。
- **影响**：潜在量纲系统性漂移（湖 vs 契约），当前未触发（实测 ratio≈1），属**潜伏**。
- **修复建议**：在同步脚本写湖前调用 `harmonize_local_volume_unit`（或等效断言），并把"湖 volume 单位"写入 `GET_PRICE_RETURN_CONTRACT` 的实测锚点文档；加一条同步后湖 ratio 落在 `[0.9,1.1]` 的断言。

**M4｜在线源异常静默返回空表（Fail-Open）**
- **位置**：`sources/tdxdata_online.py:221-223`（`fetch_daily` 异常 → `logger.error` + 空表）；同源 `fetch_minute:271`、`fetch_real_time:305`、`fetch_xdxr:369`。
- **证据**：调用方 `_fetch_online_fallback`(`data_fetcher.py:333-342`) 无法区分"无数据"与"网络故障"——基础设施故障被伪装成"该股票没数据"，最终落入 `_empty_price_frame` 空表分支（`data_fetcher.py:246-248`），系统照常继续。与 Rule 4（Fail-Closed）矛盾。
- **影响**：网络故障时静默产出空表，大脑收到空数据而非显式失败；对"在线第三跳"这一新增通道，故障不可观测。
- **修复建议**：区分异常类型（网络超时/连接失败 vs 无数据）并上抛或打错误标记；至少让 `fetch_daily` 返回带 `source_error` 标记的帧或在 `_fetch_online_fallback` 记录 `stale` 状态。

### LOW — 3

**L1｜契约列序文档自相矛盾**
- **位置**：既有报告 §1.1:35 与 §7.4/L1:783-786——两侧贴出的列序**完全相同**（`amount` 在 `volume` 前），却把"文档与代码不一致"当问题并给出与代码一致的"错误"列序。实际代码 `data_fetcher.py:41-51` 为 `date/open/high/low/close/amount/volume/reserved/code`（amount 在 volume 前），与湖实测一致。
- **影响**：仅文档；运行时 `reindex` 按列名，不受影响。
- **修复建议**：删除既有报告 §1.1:35-36 的"不一致"叙述（实为文档自相矛盾），或统一以代码为准。

**L2｜在线源默认主机硬编码（单点）**
- **位置**：`tdxdata_online.py:13-14,129`（默认 `TdxClient()` 走硬编码 `101.35.121.35`；配置注入仅当 `host` 非空，`data_fetcher.py:184-196`）。
- **影响**：单点可用性；无备用节点、无出网故障降级预案（与 `check_freshness_sla` 的 `online://tdxdata` 重锚 `freshness_validator.py:120-137` 形成对照）。
- **修复建议**：默认主机改配置驱动（`config/data_sources` 已预留）；加主机可用性探测与备用节点回退。

**L3｜硬 kill 残留 `.tmp` 无启动清扫**
- **位置**：`storage_manager.py:150-153`（tmp 清理仅在异常 `:156-163`）；`futures_storage_manager.py:565`、`total_return_benchmark.py:101`、`delisted_ingestor.py:197` 同模式。
- **证据**：`os.replace` 前的硬 kill（SIGKILL）会在 `data/lake/**` 残留 `.{name}.tmp.{pid}`；无启动/扫描侧清理逻辑。
- **影响**：残留 tmp 占用磁盘且易被误当数据文件（若 glob `*.parquet` 不匹配 `*.tmp.*` 则影响有限）；不影响数据正确性（主文件无损），属卫生问题。
- **修复建议**：`StorageManager.__init__` 或启动钩子对 `data/lake/**/.tmp.*` 做一次清扫。

---

## 5. 交叉复核矩阵（vs 既有报告 `01_data_flow_n2n.md`，基线 434aab1）

| 既有结论 | 既有位置 | 本复核判定 | 说明（双方证据） |
|---|---|---|---|
| 9 列契约 `amount` 在 `volume` 前 | §1.1 | **一致** | 代码 `data_fetcher.py:41-51`；湖实测 8 样本列序/dtype 全对；`_normalize_price_frame` `reindex`(`:358`) 强制执行。 |
| C3 红线禁 bfill（仅 ffill open/high/low） | §4.1 | **一致** | `data_cleaner.py:52-54`；`close` NaN 先 dropna(`:47`)；`amount` NaN 保留(`:39-44`)。 |
| 量纲自校准 `[60,160]` | §2.4 | **一致**（补充 M2） | `data_fetcher.py:74,98-125`；既有报告漏掉 `<5 有效行静默 no-op`（M2 新增）。 |
| 原子写机制 ✅ | §4.4 | **分歧（上调）** | 既有报告只审 `StorageManager.write_parquet` 并下"✅ 原子写机制"结论；**未审计全部写入路径**——5 处直写 `to_parquet` 绕过原子化（M1），含复权基线 `tdx_parser.py:432`。 |
| FreshnessValidator"第 25 轮已修复" | §5.2/§9 | **分歧（已修复不成立）** | `git show --stat 434aab1` 无 `freshness_validator.py`/`storage_manager.py`；`b1d2415` docs-only。运行时路径（`fetch_for_brain`/`HealthService._get_system_metrics`）均不调 `validate_freshness`（`health_service.py:383` 用 `_last_fetch_time`）。既有报告自承"仅运维巡检"——"已修复"表述误导。 |
| M1 FreshnessValidator 运行时未集成（MEDIUM） | §7.3 | **一致（上调 HIGH）** | 独立专家评审亦上调为 HIGH（H1）；本复核同意：门禁不在运行时=滞后照常交易，违反 Rule 4。 |
| L1 契约列序文档不一致（LOW） | §7.4 | **一致（自相矛盾）** | 既有报告 §1.1:35 与 §7.4:783-786 两侧列序**完全相同**——实为报告自相矛盾，非代码问题。 |
| L2 在线源静默空表（LOW） | §7.4 | **一致（上调 MEDIUM）** | 独立专家评审上调 MEDIUM（M1）；本复核同意 Fail-Open 违反 Rule 4。 |
| DataValidator 只读门禁设计 | §4.3 | **分歧（遗漏关键事实）** | 既有报告讨论 validator 设计（NaN 绕过封堵、OHLC 硬阻断），但**未指出其无运行时调用方**（仅 `data_pipeline_service.py:29`，`DataPipelineService` 零消费者）——H2 为既有报告遗漏。 |
| 大脑取数路径 | §6.1-6.3 | **分歧（遗漏调整不一致）** | 既有报告 3 条路径各自完整，但未横比湖命中 vs 湖 miss 的**复权状态**——H1（`data_access_service.py:214-217` vs `:238-244`）为既有报告遗漏。 |
| 独立专家评审 H2（三级降级单点+硬编码主机） | 评审意见 | **一致（降为 LOW 部分）** | 本复核将"硬编码主机"单列为 L2（配置可注入），"三级降级串行延迟未测"未复现（无实测数据，不虚构）；同意其架构关注，但未将主机硬编码单列为 HIGH（已有配置注入通道 `data_fetcher.py:184-196`）。 |

**与既有报告的总差异**：新增 5 项（H1/H2/M1/M2/M3），上调 2 项（H3=M1、M4=L2），确认既有报告"已修复/原子写全覆盖"2 处表述不成立，确认既有报告自相矛盾 1 处（L1）。既有报告的 3 项结论（9 列/C3/R2 护栏）**均复核为真**。

---

## 6. 结论与建议

### 6.1 健康度评级：**B-（部分可信）**

**真实有效**（经实测核对）：
- 9 列冻结契约 + `reindex` 强制（`data_fetcher.py:41-51,358`；湖实测吻合）
- C3 红线禁 bfill / amount NaN 禁兜底（`data_cleaner.py:52-54,39-44`）
- R2 写湖护栏三规则（`data_access_service.py:167-208`）
- 复权因子非法值 raise + gbbq 基线硬失败（`corporate_action.py:67-72,123-130`）
- 主湖路径原子写（`storage_manager.py:148-163`）

**风险敞口**（运行时数据路径）：
- 大脑取数复权状态不一致（H1，新增）
- 只读验证器无运行时调用（H2，新增）
- 新鲜度 SLA 未进运行时（H3）
- 原子写/量纲自校准/裸卷耦合/在线 Fail-Open（M1-M4）

### 6.2 修复优先级

| 优先级 | 问题 | 建议动作 |
|---|---|---|
| P0 | H1 调整不一致 | 统一 `load_data_with_fallback` 两分支复权口径；回归断言两分支量纲一致 |
| P0 | H2 validator 死调用 | 写湖前强制 `validate`，False 阻断；删 `DataPipelineService` 死壳或明确接线 |
| P1 | H3 freshness 未运行时 | `fetch_for_brain`/容器初始化注入 SLA 检查（告警或阻断） |
| P1 | M1 原子写覆盖不全 | 5 处直写收敛到 `write_parquet` tmp+replace；含 gbbq 基线 |
| P2 | M2 自校准 no-op | <5 行时 warning + attrs 标记；或 fail-closed |
| P2 | M3 裸卷耦合 | 同步脚本写湖前校准 + 湖 ratio 断言 |
| P2 | M4 在线 Fail-Open | 区分网络故障/无数据，打错误标记 |
| P3 | L1-L3 | 文档列序纠正 / 主机配置驱动 + 备用节点 / tmp 启动清扫 |

### 6.3 复核独立性声明
本报告**先独立取证**（未读既有报告前完成 5 问取证、湖 schema 实测、调用方 `rg`、git 历史核查），**后交叉复核**。所有 `file:line` 引用均直接来自当前工作树（`b1d2415`）。湖 schema 与量纲结论为**实测**（`python3` 读 `data/lake/quotes/daily/*.parquet`），非文档转述。

---

**复核人**：独立代码审查子代理（SenseNova 6.8 Flash Lite）
**复核时间**：2026-11-24
**代码基线**：`b1d2415`（当前 HEAD）
**既有报告基线**：`434aab1`（第 25 轮）
