# 全量 Wyckoff 扫描报告 (2026-08-02)

## 概述

对净化后的 A股全量池执行 Wyckoff 多周期分析，生成市场级相位/置信度/相对强弱分布，并筛选出研究候选池。

- 扫描脚本：`scripts/wyckoff_full_scan.py`
- 数据截至：2026-07-31
- 结果文件：`results/wyckoff_full/wyckoff_scan_all.csv` / `.json`
- 候选池：`results/wyckoff_full/candidates.csv`

## 数据净化

扫描前发现并归档 **552 个指数文件**（198 个 000xxx.SH 上证指数 + 354 个 399xxx.SZ 深证指数）到 `data/lake/quotes/daily/archive_index/`（含 .bak/.tmp.lock 伴生共 2656 文件）。

- `get_symbols()` 只扫 `daily/` 根目录 `*.parquet`，归档到子目录天然排除
- 保留基准 `000300.SH` / `000905.SH` 原位（作为 RS 相对强弱基准）
- close>1000 余下 9 只全为真实高价股（600519 茅台 2601、688256 寒武纪 1868、300308 中际旭创 1382 等）
- 保留 137 个 ETF/B股/LOF 标的（159/160/161/16x 段），研究可独立筛选

## 扫描结果（5374 只成功）

### 相位分布

| 相位 | 数量 | 占比 |
|---|---|---|
| distribution | 2466 | 45.9% |
| accumulation | 1352 | 25.2% |
| markdown | 777 | 14.5% |
| unknown | 608 | 11.3% |
| markup | 171 | 3.2% |

### 置信度分布

| 置信度 | 数量 |
|---|---|
| D | 4482 |
| C | 791 |
| B | 101 |

### 相对强弱四分类

| RS | 数量 |
|---|---|
| systemic_decline | 3444 |
| follower | 1138 |
| leader | 765 |
| weak_independent | 11 |
| None | 16 |

### 复权状态

| 状态 | 数量 |
|---|---|
| pre_adjusted | 4766 |
| raw | 592 |
| unknown | 16 |

### 信号类型触发（1208 只触发）

| 信号 | 数量 |
|---|---|
| distribution | 326 |
| accumulation | 227 |
| markdown | 175 |
| utad | 152 |
| spring | 66 |
| markup | 62 |
| sos_candidate | 44 |

### 结构评分

p50=60.03, p75=60.88, p90=61.93

## 候选池（306 只）

筛选条件：A股个股（排除 ETF/B股/LOF）+ 置信度 C级+ & 结构评分≥60 & phase∈{accumulation, distribution}

| 维度 | 分布 |
|---|---|
| 相位 | accumulation 170 / distribution 136 |
| 置信度 | C 273 / B 33 |
| RS | systemic_decline 143 / follower 100 / leader 63 |

Top 候选：
- 601865.SH (accumulation / B / 61.93 / leader)
- 002753.SZ (distribution / B / 61.41 / leader)
- 001286.SZ (distribution / B / 61.17 / systemic_decline)

## 验证

- golden_20 冒烟：20/20 成功 2.1s，RS 四分类与复权状态正常
- 抽样 10 只核验相位/置信度/结构评分与原始行情一致
- 47 (wyckoff_engine + analysis_service_v2) + 62 (classic_wyckoff) 测试 passed
- ruff clean（新增文件）
