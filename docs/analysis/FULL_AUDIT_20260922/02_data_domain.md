# 02 数据链路域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook 阶段产物 | SHA `ddd678a` | 批 B2=D1-D5；批 B5=D6

## 结论（3 句内）

日线湖 **5755 parquet 全可读抽样 5/5 PASS**，但 **`archive_index/` 不存在且 daily 根目录仍混入 554 指数文件（000*.SH=200 + 399*.SZ=354）**——AGENTS「P0 已归档净化」的**物理归档不成立**，净化仅发生在 `get_symbols(exclude_indices=True)` 读取层。财务/派现/分钟三湖文件数与 AGENTS 宣称**精确一致**（5211/5123/5186），schema 可用。主链 DataFetcher→pipeline、PIT as_of 截断、merge_asof 财务合同均在位。

## 证据（file:line @ ddd678a）

### D1 日线湖规模 / 可读性 / 指数净化（P0）

| 项 | 实测 | AGENTS 宣称 | 一致? |
|----|------|-------------|:-----:|
| `data/lake/quotes/daily/*.parquet` | **5755** | P0 后扫描池 5201（=5755−554） | 文件数=净化前全量 ✓；池过滤在读取层 |
| `archive_index/` | **不存在**（`Path.exists()==False`） | 「已归档 554 指数文件到 archive_index/」 | **❌ 冲突 C5** |
| daily 根 000*.SH | **200** | 198（AGENTS 归档数） | 残留 +2 |
| daily 根 399*.SZ | **354** | 354 | 数字吻合=**未移走** |
| 指数合计残留 | **554** | 应已移出 daily | **物理未归档** |
| 抽样 read_parquet | 600519/000001.SZ/300750/688981/000300 **5/5 OK** | 可读 | ✓ |
| 抽样 schema | 9 列：`date,open,high,low,close,amount,volume,reserved`（+1） | — | ✓ |
| 抽样 rows | 5967 / 8416 / 1970 / 1454 / 5234 | — | ✓ |

**读取层净化（实际生效点）**：

- `storage_manager.py:407-419` `get_symbols(exclude_indices: bool = True)` 默认剔除；`418-419` 调 `is_index_symbol(s)`。
- 注释 `:411-412` 自证「2026-08-18 P0 净化: daily/ 曾混入 554 指数文件」——与残留计数 200+354=554 **精确吻合**。
- `wyckoff_full_scan.py:49-56` `_is_index`：SH+000 / SZ+399 符号级；`:61-62` `_scan_filter` 剔指数+ETF；`:109` `load_symbols` 过滤分支。

**裁决（C5）**：AGENTS「指数已**归档**到 archive_index/」不成立（目录不存在，文件仍在 daily）。**净化语义实际为「读取时过滤」而非「物理迁移」**；权威侧=源码/文件系统。功能上 `get_symbols()` 默认仍正确排除指数 → 扫描池宣称 5201 **读取层可成立**，但归档叙事误导。

### D2 财务 / 派现 / 分钟三湖（P0）

| 湖 | 路径 | parquet 数 | AGENTS | 差值 | 抽样 schema |
|----|------|----------:|-------:|-----:|-------------|
| 财务 | `data/lake/financial/` | **5211** | 5211 | **0** | sample 301070.SZ: 25 rows × **577 cols**；`code,report_date,基本每股收益,…` |
| 派现 | `data/lake/dividend/` | **5123** | 5123 | **0** | 4 rows × 4 cols：`code,year,ex_date,dps` |
| 分钟（主） | `data/lake/minutedaily/` | **5186** | 5186（B 路本地） | **0** | 71 rows × 9：`date,open_px,close_px,amount,volume,n_bars,on,intra,last30_share` |
| 分钟（镜像） | `data/lake/quotes/minutedaily/` | 5186 | — | — | 同主湖 |
| 分钟（A 路拼接） | `data/lake/quotes/minutedaily_full/` | **492** | 492/500 服务器拉取 | **0** | — |

其他 lake 顶层：`factors/`, `futures/`, `index/`, `quotes/{1mins,5mins,monthly,weekly}` 在位。

**Tier-B**：不重拉；文件数+抽样 columns 已满足 DoD。

### D3 DataFetcher→pipeline 主链（P1）

| 节点 | 存在 | 证据 |
|------|:----:|------|
| `src/uniquant/data/data_fetcher.py` | ✓ | `:236-237` `get_symbols` → `storage_manager.get_symbols()` |
| `src/uniquant/data/data_pipeline_service.py` | ✓ | **实际在 `data/` 层非 `services/`**（`services/` 下不存在） |
| `data_validator.py` | ✓ | `src/uniquant/data/pipeline/data_validator.py` |
| `trade_calendar_manager.py` | ✓ | `src/uniquant/data/managers/trade_calendar_manager.py` |
| live_map Path1 对账 | — | A2 已记 `data_fetcher.py:126` 调 `process` ✓ |

**断链点**：无（P0 范围内）；`services/data_pipeline_service` 旧路径**不存在**属文档路径漂移，非运行断链。

### D4 PIT / as_of 截断与财务 merge_asof（P1）

| 合同 | file:line | 状态 |
|------|-----------|------|
| `load_universe(as_of=)` 截断 | `scripts/factor_mining/data_loader.py:43-66,122-123` | **在位**（`cutoff=pd.to_datetime(as_of)`） |
| `_load_one` 应用截断 | `:108-123` | 在位 |
| `merge_financial_metrics` | `:142-185` | **在位**（逐股财务 + merge_asof 语义，注释 P11 2026-08-26） |
| `financial_bridge.py` | `src/uniquant/brain/factors/financial_bridge.py` | 存在（PIT merge_asof 消费者，B3/F 批深核） |
| 相关测试 | `tests/scripts/test_factor_mining_data_loader.py` 等 | 存在（B1 已见 fixture 1 FAILED 家族） |

### D5 指数净化过滤（P1）

| 入口 | file:line | 默认行为 |
|------|-----------|----------|
| `StorageManager.get_symbols` | `storage_manager.py:407-419` | `exclude_indices=True` **默认开** |
| `wyckoff_full_scan._is_index` | `:49-56` | 符号级 SH000/SZ399 |
| `wyckoff_experiments/_symbols.py` | 存在 | 下游共享（B1 A2 同源） |
| daily 根指数文件计数 | 实测 | **554 仍在**（见 D1/C5） |

**判定**：净化**逻辑在位且为默认**；**物理归档失败/未执行**（C5）。

### D6 根目录实验残留 py（P2，B5 完成；只盘点不删）

| 文件 | LOC | import uniquant | sys.path 引导 | 备注 |
|------|----:|:---------------:|:-------------:|------|
| research_experiment.py | 1183 | ✓ | ✓ | 最大残留 |
| deep_analysis_experiment.py | 990 | ✓ | ✓ | |
| full_analysis_experiment.py | 820 | ✓ | ✓ | |
| full_multi_model_analysis.py | 802 | ✓ | ✓ | |
| deep_analysis_v2.py | 703 | ✓ | ✓ | |
| full_a_stock_analysis.py | 709 | ✓ | ✓ | |
| full_a_stock_analysis_optimized.py | 580 | ✓ | ✓ | |
| full_analysis_final.py | 484 | ✓ | ✓ | |
| factor_analysis_only.py | 434 | **✗** | ✓ | 纯本地/第三方，无 src 依赖 |

- 根目录非标准入口 `*.py` 共 **9**（已排除 setup/conftest，若无）。
- **8/9** 经 `sys.path` + `uniquant` 依赖 src → 研究实验入口残留，**非**数据湖写入方。
- 与 `data/` 关系：**只读消费**（未见向 `data/lake` 写入的批量路径在本批抽查中）；完整 import 图未全量 AST（M 级边界披露）。
- **DoD**：清单表 ✓；**只盘点不删** ✓。

## 与历史对账

| AGENTS 历史 | 实测 | 裁决 |
|-------------|------|------|
| 归档 554 指数到 archive_index/ | 目录不存在；554 仍在 daily | **C5：归档不成立，过滤在位** |
| 财务 5211 | 5211 | ✓ |
| 派现 5123 | 5123 | ✓ |
| 分钟 5186 + A 路 492 | 5186 + 492 | ✓ |
| 扫描池 5201 | 文件 5755、过滤后理论 5201 | 读取层一致；需 `get_symbols()` 计数复证时可 Tier-A 补跑 |

## 风险分级

| 级 | 项 |
|----|-----|
| **H** | C5：归档叙事假——任何绕过 `exclude_indices` 的路径（`get_symbols(False)`/裸 glob）会重新吸入 554 指数 |
| M | daily 与 archive 双份预期 vs 现状单份，运维/审计误导 |
| L | `data_pipeline_service` 文档路径写 services/ 实为 data/ |

## 建议动作

1. 修正 AGENTS P0 段：改为「读取层默认过滤 554 指数；archive_index 未落地」— DoD：rg「archive_index」与 `Path.exists` 一致（批准后改 AGENTS）。
2. 可选物理归档或删除 daily 指数文件 — **拟修改清单**，本审计不执行。
3. 裸 glob 消费者审计（凡 `daily_dir.glob` 未调 `_is_index` 者列清单）— DoD：rg 命中表。

## 本批变更

B2=D1-D5 / B5=D6；仅本 FULL_AUDIT 文档；**无源码/config/数据变更**。
