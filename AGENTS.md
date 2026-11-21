# AGENTS.md - UniQuant Project Control Context

> ⚠️ **MUST READ FIRST** — Read `CLAUDE.md` in the project root before any other file. It contains the 10 coding rules that govern all code generation in this project (note: the originally-referenced file was never committed; the current `CLAUDE.md` is an honest, source-cited consolidation of the rules that do exist — see its header). Every edit, test, and commit must follow those rules. Treat them as non-negotiable.
>
> UniQuant: A-share quantitative research and trading platform.
>
> 📦 **历史日志已归档（2026-11-21 瘦身重组）**：本文档只保留**最近 2 轮**变更块与常青控制节。
> 第 22 轮及更早的全部轮次块见 `docs/archive/AGENTS_CHANGELOG_ROUNDS.md`；
> 2026-06~09 的历史 `Recent Work` 研究纪事见 `docs/archive/AGENTS_RECENT_WORK_2026H2.md`。
> 全部轮次的一行索引与轮次→提交映射见下方 Round Log Index；维护分流规则见文末"文档维护规则"。

> **Updated 2026-11-21 (第二十四轮：上云通道随机抽样三方对账全绿 + 两个真缺陷回退修正；纪律=seed 可复现+三类差异如实分类+伪回归回退)**:
> **(1) 三方对账框架落地（`scripts/maintenance/verify_cloud_channels_random.py`）**：seed=42 从 SSOT (status=1 ∧ type=1, 剔债券/ETF, 沪深 12 只) 随机抽样，7 轨道 × 双基线（本地 TDX + 其他在线源 akshare/baostock/旧协议 mootdx xdxr）可复现对账，结果 JSON 入 `results/migration/` 并纳 evidence manifest。经 6 轮迭代修复（抽样误含债券/ETF、形参名错、全历史×3 重复拉取超时→窗口收敛+预取复用、轨道原子构造改逐轨容错、_parse_gpcw_file 包装层误 SKIP→直读 Financial.parse 数值矩阵）。
> **(2) 终跑全绿（12 标的 × 7 轨道, 总体 PASS）**：**A1** 上云日线 vs 本地湖 12/12 逐位（OHLC/amount 0 差）；**A2** vs akshare 不复权 12/12；**A3** vs baostock 不复权 12/12；**B** 5 分钟聚合一致性 12/12（48 根/日重构日线 OHLC 精确 + amount rel ~3e-8）；**C** xdxr 双在线栈（tdxdata=旧协议 mootdx=官方 gbbq）12/12 且官方 ⊇ Wine；**D** 财务同报告期数值矩阵 12/12（581/584 列逐位一致）；**E** snap last vs 在线日线收盘 12/12。
> **(3) 三个数据事实发现（如实分类, 非错误）**：① **服务器日 K 成交量精度=手**（mod100 恒 0, 与本地 .day/akshare 的精确股差 ≤100 股=1 手粒度, OHLC/amount 逐位一致）——600959/601319 恒差恰好 100; ② **科创板盘后固定价格交易**计入日线不入 5 分钟序列（688357 open 差 0.13/low 差 0.02/vol+50, 68 前缀结构容差 0.20 元文档化）; ③ **财务字段 vintage 重述**（官方 20260331 重发, pos363 比率类 2.34→2.38, 603203/688151 各 1 字段; 本地 Wine 文件为 584 字段旧布局 vs 官网 658 新布局, mootdx 0.11.7 zh 名单只匹配新布局→本地文件用当前库已无法解析——本地 Wine 财务通道退化又一铁证）。
> **(4) ⚠️ 一个真缺陷回退修正（伪回归）**：第二十三轮 `fetch_real_time` 的 "prices[0]=昨收/[1]=今开" 语义系**基于茅台单标的外推**——随机抽样暴露 600959 prices[0]=**89088.477 垃圾值**（昨收实为 3.02）→ 语义不普适，**已回退**：`fetch_real_time` 只输出全样本可验证的 `last`（12/12 抽样与在线日线收盘逐位一致），不解析 prev_close/open，不伪造 high/low（Rule 4）。测试同步修正（`tdxdata_online` 26 用例）。
> **(5) 运营发现：本地湖日线 L1 停摆**——湖最新日期 2026-11-17（停摆 2 个交易日），而在线通道已有 11-20 完整数据 → 上云第三跳的价值实证（`fetch_price` 现可自动补齐），湖过期已记入对账 finding。
> **(6) 门禁与入档**：定向 78 passed（tdxdata_online 26 + get_price_online_fallback 11 + price contract + gbbq/financial sync）；`ruff check src/ tests/ scripts/` **All checks passed!**；`evidence_manifest.py verify` no drift（含新增对账 JSON 入账本）；结果存证 `results/migration/cloud_channel_random_verification.json`（seed=42 可复现）。
> **(7) 已知边界**：① E 轨道 cross_api 容差 0.05 元（snap.last 语义="最新成交价"含盘后大宗, 与日线收盘语义不同, 600276 差 0.03 如实保留明细）；② 北交所标的未纳入抽样（在线市场码支持未验证）；③ 旧协议 mootdx xdxr 为唯一存活旧栈对照, 其自身无独立权威性；④ 验证脚本为开发机验收工具（需湖+本地 TDX+真网），CI 不运行。
>
> **Updated 2026-11-21 (第二十三轮：三项收尾接线 —— gbbq 写通道真实替换 + 分钟线在线接入 + snap 实时解析；纪律=全量实测+无损失守卫+不伪造极值)**:
> **(1) 侦察定案（三项实现的事实基础）**：① snap `prices` 为**抽样序列**（茅台一个交易日仅 62 点）：prices[0]=昨收 1460.21、prices[1]=今开 1450.89（与日线逐位一致），但序列 max=1485.75 ≠ 真实 high 1489.09、min=1426.00 ≠ 真实 low 1423.9 → **极值不可导出，实现只解析可验证锚点，不伪造 high/low**；② **分钟线 vol 已是股**（amount/(close*vol)=1.00，与日线的手×100 不同，量纲跨 category 不一致）→ fetch_minute 不做缩放；③ gbbq 消费者 `corporate_action.py` **严格过滤 category==1**；本地 parquet dtypes 锁定（code=object 6位/int64 日期/float64 值）。
> **(2) gbbq 写通道真实接线（`scripts/maintenance/sync_online_gbbq.py`）**：官方 `download_gbbq` → `decrypt_records` → **合并式写策略**（官方 cat1 全量替换本地 cat1【更精确 float64 + 新事件】+ 本地非 cat1 股本变更元数据 130,858 行原样保留【官方解码非 cat1 置零无信息量】）→ **无损失守卫**（写前断言旧表每一 (code,date,category) 键都在新表，fail-closed 绝不半写）+ 官方 cat1 ⊇ 本地 cat1 超集守卫 → 原子写（tmp+os.replace）+ `.bak` 备份。**真实替换完成**：`data/fq/gbbq.parquet` 194,983 → **200,377 行**（cat1 64,125→69,520，新增 5,395 事件），旧键 100% 保留（守卫实测 True），锚点 000001/19900301 rights_price=3.56 无损。**消费者冒烟 210 passed / 0 failed**（corporate_action qfq 钉带 0.1471、CSI300 109 例冒烟、price contract 全链路对替换无感——qfq 因子扰动 ~1e-7 级远低于钉带容差）。沙盒先行：/tmp 全量重建 69,520 条锚点逐位精确后才真实写。
> **(3) 分钟线在线接入（`TdxDataOnlineSource.fetch_minute`）**：频率映射 1min→7/5min→0/15min→1/30min→2/60min→3，未知频率 `ValueError` fail-fast；翻页语义与日线一致（800/页，MAX_PAGES=30）；**vol 仅改名不缩放**（已是股）；`--start_dt/--end_dt` 区间过滤。真网验收：5min 增量 48 根/日、**全深度 10,224 根回溯 2026-01-05（约 10.5 个月，修正第二十二轮"约 2 个月"的低估——此前只翻 2 页）**、1min 恰一个交易日 240 根、60min 深市 12 根全通。在线深度语义：**够近期增量，历史分钟归档仍需湖快照**（湖 1mins/5mins 目录为空的重建路径留待后续）。
> **(4) snap 实时解析（`fetch_real_time` 升级）**：透传原始 dict → 解析为结构化列 `[code, market, last, prev_close, open, series_points, compressed]`，三锚点真网对账逐位一致（昨收/今开/last=日线 1460.21/1450.89/1485.75）；**明确不输出 high/low**（抽样序列极值不完整，伪造即违反 Rule 4）；market 字段新协议语义未定 → 原样透传不解释。
> **(5) 测试与门禁（本工作树）**：新增 gbbq 同步 10 用例（纪元过滤/字段映射/dtypes 锁定/合并保留与覆盖/去重排序/无损失守卫/原子写+.bak/超集违约 fail-closed/空表拒绝）+ 分钟 4 用例 + snap 解析 3 用例（含短序列容错），`tdxdata_online` 累计 26 用例；**广域回归 data+get_price+scripts 三域 993 passed / 0 failed**；`ruff check src/ tests/ scripts/` **All checks passed!**。
> **(6) 已知边界**：① snap 无全市场扫描（单标的）；② 分钟在线增量接线为源级能力（`fetch_minute`），湖级分钟同步脚本（1mins/5mins 空目录重建）留待下轮；③ gbbq `.bak` 为唯一回滚保险（数据文件不入 git）；④ 历史逐季财务与 gbbq 官方 HTTP 通道均依赖 tdx.com.cn/tdxfin 可用性，无 SLA 承诺。
>
## Round Log Index（轮次日志索引）

> 顺序与上文/归档块一致（新→旧）。第 23、24 轮块保留于上文；其余块全文在
> `docs/archive/AGENTS_CHANGELOG_ROUNDS.md`。哈希为 `git log -- AGENTS.md` 可映射的主提交
> （部分轮次为合并提交；轮次纪元前的 dated 块不逐一映射哈希）。第十八轮无独立块（并入相邻记录）。

- **第 24 轮**（2026-11-21）：上云通道随机抽样三方对账全绿 + 两个真缺陷回退修正；纪律=seed 可复现+三类差异如实分类+伪回归回退 — 保留于上文
- **第 23 轮**（2026-11-21）：三项收尾接线 —— gbbq 写通道真实替换 + 分钟线在线接入 + snap 实时解析；纪律=全量实测+无损失守卫+不伪造极值 — `ba973fe`
- **第 22 轮**（2026-11-21）：历史财务数据在线通道接入 —— mootdx.affair 官方 HTTP 分发 + 生产导入链直通；纪律=全量实测+沙盒验收+幂等 — `2722e19`
- **第 21 轮**（2026-11-21）：tdxdata 在线通道三项建议全部落地 —— gbbq↔xdxr 锚点对账 + 官方 gbbq 源验证 + get_price 在线第三跳接线；纪律=全量实测+按消费范围对账 — `7305cc6`（20~21 合并提交）
- **第 20 轮**（2026-11-20）：mootdx 在线通道替代落地 —— tdxdata 新协议源接线并端到端调通；纪律=全量实测+冻结契约不动 — `7305cc6`（20~21 合并提交）
- **第 19 轮**（2026-11-02）：纯多头动态空仓研究体系与全量四象限法医重估落盘 + 个人投资者日终全链路与多大脑诊断闭环；纪律=全量实测+按环境三口径报告 — `c486e83`
- **第 17 轮**（2026-10-26）：代码冗余全面物理清剪 + 260MB废弃实验归档 + Round 17 死代码守卫闭环；纪律=全量实测+按环境三口径报告 — `f9a1ce5`（14~17 合并提交）
- **第 16 轮**（2026-10-26）：全市场 4,643 标的大规模长周期 Dynamic PIT 滚动实测与 DuckDB/Polars 跨截面关联性能加速闭环；纪律=全量实测+按环境三口径报告 — `f9a1ce5`（14~17 合并提交）
- **第 15 轮**（2026-10-26）：全仓多线程多 Subagent 并行解耦 + Rule 9 核心代码超标文件全面清零 + Dynamic PIT 股票池回测闭环；纪律=全量实测+按环境三口径报告 — `f9a1ce5`（14~17 合并提交）
- **第 14 轮**（2026-10-26）：单一数据源深度闭环与核心模块瘦身；纪律=全量实测+按环境三口径报告 — `f9a1ce5`（14~17 合并提交）
- **第 13 轮**（2026-10-24）：实盘风控与对账监控器 Task 4.2 落地 + 对账表 12 轨全覆盖与口径澄清；纪律=全量实测+按环境三口径报告 — `67cf31a`
- **第 11 轮**（2026-10-24）：独立法医审计全项核实与 P0/P1 全链路闭环整改 + 指标真实回归与定性去漂移；纪律=每项都有证据+定向测试+裁决 — `7b51635`
- **第 12 轮**（2026-10-24）：远程 CI 红灯根因全面清剿 —— 第十/十一轮"质量门禁全绿"声明证伪与三处存量缺陷修复；纪律=全量实测+按环境三口径报告 — `d912a6e`
- **第 10 轮**（2026-10-24）：QAR 策略法医审计与底层数理去伪 + 5 项 P0/P1 关键加固 + Phase 1 数理去伪与因果阿尔法纯化闭环；纪律=每项都有证据+定向测试+裁决 — `0c2f604`
- **第 9 轮**（2026-10-17）：`brain/` 死簇剪除 + 层覆盖率 69.13%→82.66%（CI）/71.94%→85.52%（dev）+ 发现"覆盖率工具的盲区"并诚实回收；纪律=每项都有证据+定… — `3292000`
- **第 8 轮**（2026-10-17）：`hands/` 死簇剪除 + 层覆盖率 64.19%→99.81% + 两个真 bug（其中一个曾被既有测试"钉死"成伪回归）；纪律=每项都有证据+定向测试+裁决 — `6790fc6`
- **第 7 轮**（2026-10-17）：生产孤岛剪除 + `services/` 层覆盖率补测 + 一个只在 CI 解释器暴露的日志格式化真 bug；纪律=每项都有证据+定向测试+裁决 — `ae6e0a8`
- **第 6 轮**（2026-10-16）：§7.4 十项疑似问题逐条处置 —— 8 修 / 2 书面不修；纪律=每项都有定向测试+理由+裁决 — `1e161c7`
- **第 5 轮**（2026-10-16）：CI 收集期中断真凶修复 —— 硬编码开发机兄弟仓路径；纪律=只动测试与 CI — `a434d68`
- **第 4 轮**（2026-10-16）：CI 真绿化 —— 本地数据湖/GBBQ 依赖声明式跳过；纪律=只动测试与文档 — `7de0d83`
- **第 3 轮**（2026-10-16）：数据层补测 53.9%→94.2% + 历史文档漂移根治 + 潜在缺陷修复 + 覆盖率门 68→74 — `3cf39ac`
- **第 2 轮**（2026-10-16）：P1 落地：科研控制平面接入生产因子链 + 文档漂移根治 + CI 覆盖率门 + 证据链可复现 — `95571d0`
- **第 1 轮**（2026-10-16）：简化后全栈评估落地：四阶门禁诚实化 + CI 归零 + 过户费全市场统一 + LPPL 降为遥测 + H-A ADV 地板对齐 — `037063e`
- （轮次纪元前 2026-10-13）：数据源迁移后全仓大清理落地完成：39个废弃生产模块/脚本彻底剪除，66 文件净削减 -9,581 行，2,530 项全量回归 100% 绿 — 归档
- （轮次纪元前 2026-10-13）：Step5 收口完成：4 个 gbbq 旁路通道剪除 + D5 TDX 字段等价性核验关单 + 两级排程 SLA 闭环 + 全量 A 股 5000+ 股票 QFQ 官方对账闭环 — 归档
- （轮次纪元前 2026-10-13）：Step4 剪枝完成：baostock 解耦 + 12 死源/死组件全删 -3,609 行 — 归档
- （轮次纪元前 2026-10-12）：Step3 get_price 湖优先重构 + DataCleaner 去幻影 + config 五源收缩 — 归档
- （轮次纪元前 2026-10-12）：Step2 复权单轨收口 + Bug3 修复 + gbbq resync — 归档
- （轮次纪元前 2026-10-12）：数据源收敛评估 + 迁移计划 + Step0/Step1 施工 — 归档
- （轮次纪元前 2026-08-28）：D+15 灭因归因定稿 + bp 进 H-A 组合层验证立项 — 归档
- （轮次纪元前 2026-08-28）：P14 外部现金流价值研究裁决 + D+15 fwd5 错位 bug 重大修正 — 归档
- （轮次纪元前 2026-08-26）：P13 H-A 工程化三件套 + D+13 引擎对账重大修正 — 归档
- （轮次纪元前 2026-08-26）：P12 尾部风险+筹码因子: 0/7 幸存 → 因子挖掘正式终结)**: 第四轮独立证伪闭环。**Batch A 尾部风险×4 (纯价格)**: `cvar_95_60d/ma… — 归档
- （轮次纪元前 2026-08-26）：P11 基本面价值/质量因子: 方向 7/7 全对但五门 0 幸存 + TDX 双口径 TTM 真 bug 防线 — 归档
- （轮次纪元前 2026-08-25）：P10/D+10 容量验证 + 工程化落地 — 归档
- （轮次纪元前 2026-08-25）：P9 隔夜/日内因子: 短窗口 OOS 全败 + 日内动量反向发现 — 归档
- （轮次纪元前 2026-08-25）：P8/D+9 组合层验证: H-A 可交易性确认 — 归档
- （轮次纪元前 2026-08-25）：P7 条件信号定向验证: H-A 幸存 — 归档
- （轮次纪元前 2026-08-25）：P6 Regime 条件化诊断: 条件信号存在)**: 按"②regime 分层→①隔夜因子"组合推进第一步。`run_regime_conditional_ic.py`（预注… — 归档
- （轮次纪元前 2026-08-25）：P5 CANSLIM D+4 生死判定: 路线终止 + 成长陷阱实证 — 归档
- （轮次纪元前 2026-08-24）：P4 财务数据底座落地 — 归档
- （轮次纪元前 2026-08-19）：因子挖掘 P1 baseline + P2 GP 全量 + P3 逻辑因子 — 归档
- （轮次纪元前 2026-08-18）：因子挖掘功能核查 — 归档
- （轮次纪元前 2026-08-18）：P0 数据净化 + 进程池入仓 — 归档
- （轮次纪元前 2026-08-18）：全量重跑暴露下游裸前缀缺陷 + T1 基线修正 — 归档
- （轮次纪元前 2026-08-18）：P1 幸存者偏置定量披露 + 开放项#2 box 核验 — 归档
- （轮次纪元前 2026-08-18）：TRIAD-VSA 量价结构标注器 — 归档
- （轮次纪元前 2026-08-18）：全量 5 窗重跑 + structural_score 非确定性根因修复 — 归档
- （轮次纪元前 2026-08-14）：P0+P1 全量回归核验完成 + bias200 标注缺陷修复 — 归档
- （轮次纪元前 2026-08-12）：Wyckoff P0 信号链根除实施完成 + 验收 PASS)**: 按 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` §5/§8… — 归档

## Current State
> ⚠️ **本快照已过期（截至 2026-10-23，约第九轮口径）**：其后第十~二十四轮的实测指标见下方最近 2 轮更新块与
> `docs/archive/AGENTS_CHANGELOG_ROUNDS.md`。下表仅作历史基线参考，**不得当作当前状态引用**。


UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot (**2026-10-23**, live measurement after the post-simplification P0/P1/P2 remediation + 第三轮数据层补测 / 文档漂移根治 + 第四轮 CI 数据湖依赖收口 + 第五轮 CI 收集期中断修复 + 第六轮 §7.4 十项处置 + 第七轮生产孤岛剪除 / `services/` 补测 + 第八轮 `hands/` 死簇剪除 / 层覆盖率抬升 + 第九轮 `brain/` 死簇剪除 / 层覆盖率抬升 + **第十轮 QAR 策略法医审计去伪与底层数理求真 + P0/P1 关键加固与安全守卫覆盖**):

| Metric | Current value |
|---:|---:|
| Python files under `src/uniquant/` (active) | 219 |
| Python active LOC under `src/uniquant/` | 56,386 |
| Declared runtime layers | 8 (`shared → data → brain/risk/signal → hands → services → ui`) + `research/` control plane |
| Test files under `tests/` | 231 (tracked 227; `tests/archive/` 4 个 gitignored 不入库) |
| Test functions | 3,490 (tracked 3,442；`tests/archive/` 48) |
| Tests passing (dev machine **with** the gitignored data lake + undeclared `czsc`) | 3,964 passed / 0 skipped / 0 failed (collected 3,964) |
| Tests passing (**true CI**: dependency set = `pip install -e ".[all,dev]"`, i.e. **no** `czsc`; **no** data lake / no TDX / **no dev sibling repo**) | 3,778 passed / **163 skipped** / 0 failed / 0 error (collected 3,941) |
| Tests passing (CI data env but full local deps, incl. `czsc`) | 3,815 passed / 149 skipped / 0 failed / 0 error (collected 3,964) |
| Ruff issues | 0 (src + tests + scripts) |
| Test coverage — dev machine (whole package, `ui/` omitted) | **87.33%** (24,880 statements / 3,152 missed) |
| Test coverage — **true CI** (real-data tests skip **and** no `czsc`) | **86.04%** (24,880 statements / 3,474 missed) — coverage floor `--cov-fail-under=84` (**margin +2.04 pt**) |
| Layer coverage, true CI (weakest first) | `risk` **73.14%** · `services` **79.34%** · `brain` 82.66% · `shared` 87.66% · `signal` 91.06% · `data` 92.95% · `research` 94.32% · `hands` **99.81%** |
| `except Exception:` total (src) | 145 |
| `except:` (bare) total | 0 |
| Archived / dead code | 0 (physically removed — no `archive/` dirs remain) |

> **Historical snapshot (2026-07-13, post-v6 TDD-Red-Blue)** — retained for traceability only: 252 files / 61,889 LOC / 144 test files / 1,934 test functions / 2,051 passing (22 skipped) / coverage 57.88% / 6 archived files (2,217 LOC) / `except Exception:` 231 / 35 files at 0% coverage. **All of these are superseded** by the live table above; see `docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md` for the measured basis and `docs/index.md` for the documentation state boundary.

Comprehensive re-analysis complete (Phases 0-9): full baseline audit, worktree diff, 8-engine correctness audit, 7-line backtest trust audit, data pipeline reliability, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for full reports.

Phase A-K v2.0 deep audit (2026-07-06): code quality (Fair, 116 duplicates, Wyckoff complexity 40), test quality (mutmut baseline broken), data reliability (B+, 5934/5934 100% readable), engine runtime behavior (B+, 2 critical bugs FSM+Wyckoff), backtest trust (B+, 7/7 lines PASS), signal audit (A-, signal/db.py 93% coverage), performance (A-, 64.4 MB/s), security (B+), observability (2/5, metrics F). Overall scorecard: **3.29/5.0 — B (conditional ready)**. See `docs/reanalysis/` for all 15 reports.

**Corrections from live system map (2026-07-09)**: Wyckoff complexity 76→40 (class max function); signal/db.py coverage 0%→93% (35 tests); eastmoney LOC 1,094→3 (refactored to 4 files). See `I_live_system_map.md`.

5 pre-existing test failures resolved (bc6337bc). 0 ruff issues, 0 pre-existing failures.

## Control Documents

Read these first:

| File | Purpose |
|---|---|---|
| `AGENTS.md` | First project control context. Reorganized 2026-11-21: keeps latest 2 round blocks + evergreen sections; rounds 1-22 changelog archived to `docs/archive/AGENTS_CHANGELOG_ROUNDS.md`, 2026-06~09 work logs archived to `docs/archive/AGENTS_RECENT_WORK_2026H2.md`. |
| `docs/reanalysis/I_live_system_map.md` | Live system map (2026-07-09): corrected metrics, dead code inventory, ranked active bugs, data path heat map. |
| `docs/index.md` | Documentation entry point and state boundary. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Direct-call prompt playbook for staged system analysis. |
| `docs/remediation/FULL_STOCK_TEST_PLAN.md` | Full stock test plan (canary/medium/full staging). |
| `pyproject.toml` | Real package metadata, dependencies, pytest config. Use root file, not docs copies. |
| `config/config.yaml` | Main runtime configuration. |
| `src/uniquant/shared/interfaces.py` | Typed cross-layer contracts including `TradingSignal`, `ResearchDataPack`, `RegimeOutput`, `LPPLOutput`, `CZSCOutput`, `NtfOutput`, `WyckoffOutput`, `AlphaOutput`, and protocols. |
| `src/uniquant/services/service_container.py` | DAG dependency injection and service initialization. |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker analysis orchestrator. |
| `src/uniquant/services/research_pipeline.py` | End-to-end research pipeline. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy analysis engine factory. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters. |
| `src/uniquant/signal/arbitrator.py` | Sell-priority signal arbitration with confidence-based rules. |
| `src/uniquant/shared/time_provider.py` | RealTimeProvider / FrozenTimeProvider for testable time. |
| `docs/analysis/wyckoff_research_report.md` | Wyckoff WSO+WSS+Resonance — 7-phase empirical research report on 22,148 A-share observations. All findings traceable to Phase I–VII run output. |
| `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` | **Wyckoff 深入再研究定稿 (2026-08-12)** — 对 08-12 正确实现方案的 5 窗跨 regime 实证复核（F7 五窗无同号显著、T1 5/5 PASS、T3 1/4 FAIL、T4 漂移红线→P1-1 撤回、T5 过度→P1-11 默认关）、四轮红蓝裁决、修订版 P0/P1/P2 与 config 变更清单。实施 P0 前必读（与 Correct Implementation 两份对照）。**⚠️ 2026-08-18 更新**：`results/wyckoff_xs*/wyckoff_scan_all.csv` 已重跑为 39 列确定性版本（修复 WSS EMA 漂移 + 消除线程池竞态），旧 25 列 CSV 备份于 `/tmp/opencode/wyckoff_fix/old_scans/`。**⚠️ 2026-08-18 (P0) 更新**：净化 554 指数后 5 窗重扫为 **5201 只×39 列**（`all` 池 5755→5201），旧 5755 行 CSV 备份于 `/tmp/opencode/wyckoff_fix/old_scans_p0/`。**⚠️ 2026-08-18 (下游缺陷修正) 更新**：T1 n_buy 正式基线修正为 **86/27/69/174/123**（此前 82/23/66/166/118 受下游裸前缀误杀影响偏低），clean 池 n 5174/5185/5178/5133/5084。 |
| `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` | **Wyckoff 正确实现方案定稿 (2026-08-12)** — 引擎目标态=叙事+风控层；P0 信号链根除（direction 透传/adapter direction 优先/RDP 仅展平 wyckoff 键/置信门槛 0.40/关 structural_adjust/SELL-as-entry 禁）、P1 标注增强 12 项、P2 验证门 5 项、8 项明确不做。实施 P0 前必读。 |
| `docs/reanalysis/` | 10 comprehensive re-analysis reports (Phases 0-9) covering baseline, worktree, engines, backtest trust, data pipeline, signals, engineering health, production readiness, governance, and final roadmap. |
| `docs/reanalysis/Z_investigation_report_20260710.md` | 5-round multi-pass source code investigation (2026-07-10, updated w/ red-blue corrections) — verified 256 files, 17/17 fixes, 15 residual except patterns, research_pipeline thread safety, 51 new tests, 4 dead code files archived |
| `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md` | Comprehensive TDD red-blue adversarial analysis (2026-07-10) — 74 doc claims verified (87% accuracy), 224 except Exception mapped by layer, dead code corrected to ~2,225 LOC, 45 files at 0% coverage (3,791 LOC), 1 truly weak test |
| `docs/remediation/v5_remediation_work_list_20260710.md` | Verified remediation work list (2026-07-10) — all 11 P0 fixes confirmed FIXED, 14 remaining items ranked R0-R3 with file:line evidence, zero hallucination gate |
| `docs/remediation/red_blue_remediation_plan.md` | Red-blue remediation execution plan: Phase 0 (P0-01 through P0-10 core bugs), Phase 1 (P1-01 through P1-07 engineering health), Phase 2 (documentation + portfolio research). |
| `src/uniquant/shared/event_types.py` | Event/Command base and domain events. |
| `src/uniquant/brain/factors/registry.py` | FactorRegistry with access gate (replaced the removed `shared/factor_governance.py`). |
| `src/uniquant/shared/config_models.py` | RefactoringConfig / FeatureFlags for staged migration. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed signal-driven backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized A-share matching engine. |
| `scripts/staged_full_scan.py` | Staged full-stock pipeline scan (canary/medium/full stages). |

Historical architecture and migration documents under `docs/` are useful background, but many still describe target state or pre-remediation gaps. Prefer current source code and the control documents above.

---

## Layer Responsibilities

| Layer | Path | Files | Responsibility |
|---|---:|---:|---:|
| `shared` | `src/uniquant/shared/` | 42 | Protocols/contracts, constants, config (+loader/validator/schema), exceptions, cache, logging, A-share rules (`limit_checker`/`market_rules`), `cost_model`, `slippage_model`, `time_provider`, `event_bus`/`event_types`, `kill_switch`, `result_store`, `secret_manager`, DI container. |
| `data` | `src/uniquant/data/` | 32 | Lake-first single-source ingestion (mootdx local/online), corporate-action adjustment (single track `CorporateActionAdjuster`), gbbq/main-data managers, parsers, cleaners, validators, GBBQ/calendar writers. |
| `brain` | `src/uniquant/brain/` | 60 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 8 | Standard signal models, adapters, normalization, aggregation, arbitration, quality checks. |
| `hands` | `src/uniquant/hands/` | 22 | Backtesting, A-share matching, function-based strategy registry (`STRATEGY_MAP`), reports, robustness and sensitivity tools (CFFEX cross-asset/TWAP/SAGA included). |
| `risk` | `src/uniquant/risk/` | 8 | Position sizing, drawdown, EVT, structural risk, portfolio optimizer, sparse convex optimizer, compliance engine. |
| `services` | `src/uniquant/services/` | 26 | DAG service container, analysis orchestration, data service, cache coordination/market cache, reports, scan, health, validation, research pipeline. |
| `research` | `src/uniquant/research/` | 12 | Scientific control plane: alpha tier gates (four-tier `alpha_tier_engine`), strategy sandboxes, degrees-of-freedom ledger (trials → BH-FDR / alpha-wealth). |
| `ui` | `src/uniquant/ui/` | 8 | Streamlit dashboard, health check, UI manager logic, LPPL visualization. |

---

## Core Runtime Flow

Single ticker research path:

1. `ServiceContainer.initialize()` constructs data, cache, analysis, signal, backtest, and research pipeline services.
2. `DataService.fetch_for_brain()` returns `data_pack` with stock data and metadata.
3. `AnalysisService.run_ticker_analysis()` runs regime, LPPL, NTF, CZSC, Wyckoff, alpha, and derived indicator logic.
4. `DecisionBrain` produces the final decision payload.
5. `TradingSignalCollector` converts engine outputs into typed `TradingSignal` objects.
6. `UnifiedBacktestEngine.run()` executes signals against K-line data using A-share constraints.
7. `PipelineResult` returns `data_pack`, decision, signals, and `BacktestResult`.

Key files:

| Concern | File |
|---|---|
| Service DAG | `src/uniquant/services/service_container.py` |
| Analysis orchestration | `src/uniquant/services/analysis_service_v2.py` |
| Pipeline orchestration | `src/uniquant/services/research_pipeline.py` |
| Engine lazy loading | `src/uniquant/services/analysis/engine_factory.py` |
| Signal conversion | `src/uniquant/signal/adapters.py` |
| Signal arbitration | `src/uniquant/signal/arbitrator.py` |
| Factor governance | `src/uniquant/brain/factors/registry.py` |
| Feature flags | `src/uniquant/shared/config_models.py` |
| Time provider | `src/uniquant/shared/time_provider.py` |
| Backtest execution | `src/uniquant/hands/backtest/unified_engine.py` |
| Vectorized matching | `src/uniquant/hands/backtest/unified_matching_engine.py` |

---

## A-Share Rules To Preserve

| Rule | Current source |
|---|---|
| Main board limit up/down | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| STAR/GEM limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| Beijing Stock Exchange rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| ST stock limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| T+1 sell restriction | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/hands/backtest/unified_matching_engine.py` |
| Commission, stamp duty, transfer fee | `src/uniquant/shared/cost_model.py` |
| Slippage | `src/uniquant/shared/slippage_model.py`, matching engines |
| Price collar | `src/uniquant/shared/market_rules.py` (`BoardRule.price_collar_pct`) |
| Lot size | `src/uniquant/shared/market_rules.py` |

Any change touching these rules requires focused tests and explicit review.

---

## High-Risk Files

| File | Why it is risky |
|---|---|
| `src/uniquant/services/__init__.py` | Lazy import contract for service package. |
| `src/uniquant/shared/interfaces.py` | Cross-layer typed contracts and protocol boundaries. |
| `src/uniquant/shared/constants/__init__.py` | Aggregated constants export used broadly. |
| `src/uniquant/services/service_container.py` | Runtime dependency graph and service lifetime. |
| `src/uniquant/services/analysis_service_v2.py` | Main analysis workflow and failure defaults. |
| `src/uniquant/services/analysis/engine_factory.py` | Engine registration and lazy import behavior. |
| `src/uniquant/data/sources/mootdx_local.py` | Local TDX lake ingestion path used across data workflows (replaced the deleted `sources/tdx.py`). |
| `src/uniquant/data/pipeline/data_validator.py` | OHLC data correctness guardrail. |
| `src/uniquant/signal/adapters.py` | Converts heterogeneous engine outputs into executable signals. |
| `src/uniquant/hands/backtest/unified_engine.py` | User-facing typed backtest behavior. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | A-share execution constraints in vectorized matching. |
| `config/config.yaml` | Global runtime behavior. |

---

## Working Rules For Agents

- Start with current source code, not historical docs.
- Before meaningful multi-file work, create a short plan.
- Prefer narrow analysis and narrow edits.
- Do not revert user or prior-agent changes.
- Treat the working tree as possibly dirty. Inspect `git status --short` before edits.
- Use `rg` and `rg --files` for searches.
- Use `apply_patch` for manual file edits.
- For code changes, follow TDD where practical: identify failing path, add/update tests, implement, verify.
- For sensitive paths, review auth, data validation, injection risk, secrets, and error leakage.
- After meaningful changes, review the diff and record verification performed.
- **Sync docs with every change**: After any code modification (feature, refactor, bugfix), update the affected documentation under `docs/`. Round changelog blocks go to `docs/archive/AGENTS_CHANGELOG_ROUNDS.md` (newest at top); `AGENTS.md` keeps only the latest 2 round blocks + one index line each — never append new history sections to `AGENTS.md`. Treat documentation drift as a blocker, not a backlog item.

---

## Common Commands

```bash
# Install all optional extras
pip install -e ".[all]"

# Full test suite
pytest tests/ -q

# Baseline verification
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py

# Engine factory smoke tests
pytest tests/test_engine_factory.py -xvs

# Eight-layer import smoke
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# Config smoke
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# Service container smoke
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"

# Full stock pipeline scan (canary → medium → full)
python3 scripts/staged_full_scan.py --stage canary --max-workers 4
python3 scripts/staged_full_scan.py --stage medium --max-workers 4 --seed 42
python3 scripts/staged_full_scan.py --stage full --max-workers 4

# Lint source
ruff check src/uniquant/

# Dashboard
streamlit run src/uniquant/ui/dashboard.py

# Parameter sweep (v2, with resume support)
python3 scripts/param_sweep_v2.py --symbols golden_20 --resume
python3 scripts/param_sweep_v2.py --symbols golden_100 --lookback-days 252 --range-thresholds 0.20 0.30

# Parameter sweep (v1, legacy)
python3 scripts/param_sweep_v1.py
```

Do not claim test results are current unless the command was run in the current working tree.

---

## Analysis Workflow

For systematic system analysis, use:

`docs/ANALYSIS_PROMPT_PLAYBOOK.md`

It defines stages 0-7:

0. Global architecture
1. Services orchestration
2. Data system
3. Brain engines
4. Factor system
5. Signal system
6. Backtest and matching
7. Risk and live-readiness

Each stage requires a plan, concrete artifacts, checkpoint context, and verification checklist.

---

## 文档维护规则（Document Maintenance Rules, 2026-11-21）

- 新轮次完成时：轮次变更块**只**写入 `docs/archive/AGENTS_CHANGELOG_ROUNDS.md` 顶部；本文件滚动保留
  **最近 2 轮**块（更旧块迁入归档）并在 Round Log Index 补一行索引。
- **禁止**在 `AGENTS.md` 新增历史叙述节（`Recent Work` / 研究判定 / 阶段完成状态等）；此类内容一律进
  `docs/analysis/`、`docs/reanalysis/` 或归档文件。
- `Current State` 快照表仅在主动刷新口径时更新；平时保持原样，过期时在表头加"已过期"横幅。
- 本文件目标体量 ≤ 40KB；超出即触发一次归档瘦身。
