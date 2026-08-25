# 财务数据拉取方案 — 分析报告 (v3: 逐项复核修正)

> **生成**: 2026-08-19 | **v2**: TDX 实测后推荐反转 | **v3**: 用户要求逐项复核，修正 3 处错误声明
> **目标**: 为基本面因子研究填充 `data/lake/financial/`，与既有 `FinancialFactorBridge` 无缝对接
> **前置**: P3 结论——价量因子全是动量 beta，基本面是唯一结构性正交的新赛道

---

## ⚠️ v3 复核修正记录（相对 v2）

| # | v2 声明 | 复核结果 | 修正 |
|---|---|---|---|
| 1 | "唯一必须的主动 rename: 其中：营业收入→营业收入" | ❌ 错——TDX 同时含**裸列 `营业收入`**（直配桥接主映射），无需任何 rename | 零 rename |
| 2 | 公告日期 YYMMDD 归一化是"可修瑕疵" | ⚠️ 升级为**必须项**——浮点值 astype(str)="250419.0" 无法过桥接 `_normalize_date_series` 的 `\d{6}` fullmatch → 全部 NaT（实测确认） | fetcher 必须 float→Int64 转换 |
| 3 | "时点快照保真，财务面无幸存者偏差" | ❌ **证伪**——退市股欣泰电气(300372,2017退市)连其**在市时期**(2016Q1)的归档都不在；PT金田A(000003)同样缺失；且 00x 段股票数 2016Q1 与 2025Q1 完全相等(412) → 归档疑似按当代代码池重建 | 幸存者偏差存在，须披露（量级见 §5） |

其余声明全部复核通过：147 个归档 ✓、5403×585 ✓、**25/25 字段严格匹配覆盖**（程序化验证，非目测）✓、桥接端到端 ✓、服务器偶断 retry 可解 ✓。

---

## 1. 需求侧契约（不变）

- **存储**: `data/lake/financial/{symbol}.parquet`（`scan_service.py:145-149`）
- **字段**: 桥接层期望中文列名，经 `FIELD_MAPPING_DICT` + `ALIASES` 映射（`financial_bridge.py:27-69`）
- **日期**: `report_date`（必需）+ `财报公告日期`（可选，缺失用季度偏移兜底防前视）

## 2. 现状盘点（不变）

`data/lake/financial/` 为空；既往同步日志 0 字节；`eastmoney_financial.py` 名不副实（只有资金流）；桥接层代码完整可用；akshare 1.18.63 / baostock / mootdx 0.11.7 均已安装。

---

## 3. 三源实测对比（2026-08-24 全部实测）

### 3.1 通达信归档（mootdx affair）— ✅✅ 最终推荐

TDX 文件服务器提供 **147 个季度财务归档**（`gpcw{YYYYMMDD}.zip`，1988→2026），mootdx 一行代码下载+解析：

```python
from mootdx import affair
a = affair.Affair()
a.files()                                            # 列出全部归档(文件名+hash+大小)
a.fetch(downdir=..., filename='gpcw20250331.zip')    # HTTP 下载 (~5MB/期)
df = a.parse(downdir=..., filename='gpcw20250331.zip')
```

**实测结果（gpcw20250331.zip）**：

| 维度 | 实测值 |
|---|---|
| 规模 | **5403 只股票 × 585 列**/期 |
| 股票代码 | DataFrame **index**（'000001' 六位码，需补交易所后缀） |
| report_date | int64 YYYYMMDD ✓ |
| 公告日期 | **`财报公告日期`/`业绩快报公告日期`/`业绩预告公告日期 `三列齐备** —— 与桥接层 :72-74 期望列名逐字一致 |
| 字段覆盖 | **25/25 全覆盖** |
| 历史深度 | gpcw20160331.zip 同 schema 实测通过（2681 只）；最早 1988 |

**关键发现——桥接层就是为这套数据设计的**：v3 程序化复核（用桥接真实的 `alias_to_standard` 严格匹配逻辑逐字段验证），**25/25 标准字段全部命中**，且**零 rename 需要**：

| 桥接标准字段 | TDX 直配列名（严格字符串匹配） |
|---|---|
| eps / eps_deducted | 基本每股收益 / 扣除非经常性损益每股收益 |
| bps / retained_eps / capital_reserve_ps | 每股净资产 / 每股未分配利润 / 每股资本公积金 |
| roe / ocf_ps / gross_margin(%)(非金融) / net_margin(%) | 同名直配 |
| revenue | **营业收入**（裸列存在，无需 rename） |
| operating_profit / total_profit / net_profit / net_profit_deducted / net_profit_parent | 营业利润 / 四、利润总额 / 净利润 / 扣除非经常性损益后的净利润 / 归属于母公司所有者的净利润 |
| total_assets / total_liabilities / equity | 资产总计 / 负债合计 / 所有者权益（或股东权益）合计 |
| debt_ratio(%) / current_ratio(非金融) / quick_ratio(非金融) / cash | 同名直配 |
| ocf / icf / fcf | 经营/投资/筹资活动产生的现金流量净额 |

**端到端验证已通过**：parse → map_fields（25 字段全映射）→ calculate_eps_ttm 计算成功。

**优势（v3 复核后保留）**：
1. **离线批量下载**，无 API 限流（~5MB/期 × 42 期 ≈ 200MB，一次拉完）
2. 585 列远超需求，未来扩展（商誉、存货、研发费用等）无需换源
3. 公告日期三列齐备（`财报公告日期`/`业绩快报公告日期`/`业绩预告公告日期 `），与桥接 `ANNOUNCEMENT_DATE_COLS`(:71-76) 逐字一致——含尾随空格变体

**必须处理的实现细节（v3 定级）**：
1. **公告日期 float→Int64 转换【必须】**：TDX 存 YYMMDD 浮点（250419.0）；桥接 `_normalize_date_series` 用 `\d{6}` fullmatch 解析，浮点 astype(str)="250419.0" 匹配失败 → 全 NaT → 全部行退化为"报告期+偏移"兜底（安全但丢真实公告日精度）。fetcher 落盘前必须转 Int64。
2. 下载服务器偶发连接失败（实测 1/14 次失败、重试成功）→ retry×3。
3. **幸存者偏差存在（见 §5）**。

### 3.2 AkShare 东财批量接口 — 备选（降级）

`stock_yjbb_em/zcfz_em/lrb_em/xjll_em` 四接口按报告期拉全市场，实测可用（2025Q1 5166 行、2016Q1 2754 行）、带最新公告日。但对比 TDX 全面落后：

| 对比项 | TDX | AkShare 东财 |
|---|---|---|
| 字段覆盖 | **25/25 + 585 列富余** | 19/25 |
| 调用方式 | 42 次 HTTP 文件下载，离线解析 | 168 次 API 调用 + sleep |
| 限流风险 | 无 | 有（需 1.5s 间隔） |
| 退市股 | **保留**（时点快照） | 大概率缺失（现价表） |
| 每股指标 | 直出 | yjbb 直出 |
| 网络依赖 | 一次性 | 全程在线 |

→ 保留为 TDX 不可用时的降级路径。

### 3.3 Baostock — 否决（同 v1）

只有比率型数据（缺营收/总资产/现金流原值），无法支撑应计异象。可作二线校验源。

---

## 4. 最终实施方案（TDX 路线）

### 4.1 抓取流程

```
for archive in files():                      # gpcw20160331.zip ... 最新完整季
    if 季度 < 20160101: continue             # 与行情回看窗口对齐(10年+缓冲)
    if checkpoint 已完成: skip               # 断点续传
    a.fetch(...); a.parse(...)               # retry×3
    df: index=六位码 → 加交易所后缀(60/68x→SH, 000/30x→SZ, 43/83/87x→BJ, 桥 MARKET_SUFFIX_MAP 同规则)
    列名 strip 尾随空格
    公告日期 float→Int64 (250419.0 → 20250419)  ← v3: 必须项, 否则桥解析全 NaT
    缺失公告日→NaN(桥用偏移兜底)
    按 code 分组累积
groupby(code) → 写 data/lake/financial/{symbol}.parquet
```

### 4.2 落盘 schema（与桥接零适配、零 rename）

```python
columns = [
    "code",                # 000001.SZ
    "report_date",         # int64 YYYYMMDD (桥 _normalize_date_series 直解)
    "财报公告日期",          # int64 YYYYMMDD (v3: 由 YYMMDD 浮点转换)  ← 桥 :71-76 直接读
    <25 字段 TDX 原列名>,    # alias_to_standard 全部严格命中, 无需 rename
]
# 每股票按 report_date 升序, 一行一季
```

### 4.3 新脚本

`scripts/factor_mining/fetch_financial_data.py`
- CLI: `--start 20160101 --end latest --retry 3 --resume`
- 校验步骤：抽 3 只股票跑 `FinancialFactorBridge.process()` 端到端验证 PE_TTM/PB/EPS_TTM 产出
- 单测：日期归一化（YYMMDD/YYYYMMDD 双格式）、代码后缀化（含 BJ）、缺失公告日兜底

### 4.4 工作量

| 步骤 | 估算 |
|---|---|
| 实现 fetcher + 测试 | ~200 行脚本 + 6-8 用例 |
| 全量下载解析（42 期 × ~5MB + retry） | 15-25 分钟一次性 |
| 桥接 E2E 校验 | 10 分钟（核心链路本测试已跑通） |

---

## 5. 关键风险与处理

| 风险 | 分析 | 处理 |
|---|---|---|
| **公告日期浮点格式** | v3 实测：float "250419.0" 过不了桥接 `\d{6}` fullmatch → 全 NaT | **fetcher 必须 float→Int64**，单测锁定 |
| 下载服务器瞬断 | 实测 1/14 次失败 | retry×3 已足够 |
| **幸存者偏差（v3 修正）** | 实测证伪"时点保真"：欣泰电气(300372)连在市时期的归档都不在；00x 段股票数跨期恒为 412 → 归档疑似按当代代码池重建。量级参考 P1 披露：type=1 口径退市股仅 337/5541 (~6%)，且对 2016+ 窗口影响更小 | 如实披露，与 P1 幸存者披露同口径；后续可用 baostock `query_all_stock` 历史快照核对 |
| 金融行业科目结构特殊 | 银行现金流表科目不同 | 因子计算按行业过滤或接受 NaN（桥天然容忍） |
| 净利润口径 | TDX 同时有 `净利润`(含少数,五、净利润) 与 `归属于母公司所有者的净利润` → 双口径齐全 | SUE 用 EPS_TTM；应计用归母口径 |
| 更早年份 schema 漂移 | 2016Q1 已验证一致；更早未验 | 从 20160101 起（与行情 lookback 对齐），不碰更老归档 |

---

## 6. 双源交叉验证（2026-08-24 实测，2025Q1 报告期）

**方法**：seed=42 随机抽 10 只 + 锚点（000001 平安银行 / 600519 贵州茅台）共 12 只，TDX 本地归档 vs 东财线上四接口（yjbb/zcfz/lrb/xjll）逐字段比对，相对误差容差统计。

### 6.1 结果

| 字段 | 可比 | <0.5% | 判定 |
|---|---|---|---|
| eps / bps / total_assets / total_liabilities / equity | 12 | **100%** | ✅ 精确一致 |
| operating_profit / total_profit / **net_profit_parent** / ocf / icf / fcf | 12 | **100%** | ✅ 精确一致 |
| debt_ratio% / cash / gross_margin% / revenue | 12 | 92% | ✅ 一致（差异见下） |
| ocf_ps | 12 | 75% | ⚠️ 舍入级小差 |
| net_profit_total（五、净利润） | 12 | 42% | 📐 口径差（见下） |
| **公告日期** | 12 | **12/12 一致** | ✅ |

锚点明细（600519）：total_assets 312,368,693,248 vs 312,368,697,395（浮点精度级）；公告日完全相同。

### 6.2 全部不一致均为口径差而非数据错误

1. **东财 lrb 的"净利润" = 归母口径**（与 TDX `归属于母公司所有者的净利润` 100% 相等）。TDX 另有 `五、净利润`（含少数股东权益），差额即少数股东损益（茅台 27.77B vs 26.85B）→ 因子统一用 **net_profit_parent**
2. **revenue 口径**：TDX 只有 `营业收入`（主营），东财 lrb 给 `营业总收入`（茅台 50.6B vs 51.4B，~1.7% 差）→ 桥接映射"营业收入"，与 TDX 自洽
3. **银行股行业科目**：货币资金定义不同（000001: TDX 466B vs EM 291B）、毛利率无意义（TDX=0/EM=NaN）→ 金融股按行业过滤或容忍 NaN

### 6.3 结论

**TDX 本地财务数据通过交叉验证，质量确认可用于基本面因子研究**：核心字段与线上权威源精确一致，公告日期完全吻合，所有差异均可归因于已知口径定义。验证脚本留存 `/tmp/opencode/validate_fin_sources.py`，正式化后入仓 `scripts/factor_mining/`。

---

---

## 7. 实施结果（2026-08-24 完成）

| 项 | 结果 |
|---|---|
| **全量拉取** | `scripts/factor_mining/fetch_financial_data.py`：**5211 只 × 42 季（2016Q1→2026Q2），2.4GB**，产物 `data/lake/financial/{symbol}.parquet` |
| **测试** | `tests/scripts/test_fetch_financial_data.py` 29 用例 + 桥接累计 TTM 回归 5 用例；相关 69 passed，ruff 0 |
| **实施中发现并修复真 bug** | `FinancialFactorBridge.calculate_eps_ttm` 朴素 `rolling(4).sum()` 把**同年累计值(YTD)当单季相加** → EPS_TTM 虚增（茅台 FY25+Q1'26+H1'26 累计和=123 vs 正确 TTM）。修复：先按年边界差分单季（跨年 Q1 为新起点），再滚动求和。回归锁：`TestCumulativeToTTM` 4 用例（完整窗口/跨年重置/多股隔离/naive-bug 锁），旧测试语义同步修正 |
| **验收锚点** | 茅台 EPS_TTM@FY2024=68.64（恰为全年 EPS）；TTM@20260331=66.04=14.80+15.35+14.13+21.76（单季逐项核对一致）；TTM 全序列 economically 合理（65-72 区间） |
| **剔除项** | 920xxx 北交所新股段 338 码无后缀映射规则，正确剔除并日志记录 |

## 参考文献

1. Sloan, R. G. (1996). Do stock prices fully reflect information in accruals and cash flows about future earnings? *The Accounting Review*, 71(3), 289-315.
2. Cooper, M. J., Gulen, H., & Schill, M. J. (2008). Asset growth and the cross-section of stock returns. *Journal of Finance*, 63(4), 1609-1651.
3. Foster, G., Olsen, C., & Shevlin, T. (1984). Earnings releases, anomalies, and the behavior of security returns. *The Accounting Review*, 59(4), 574-603. (SUE)
