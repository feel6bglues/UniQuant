# FULL AUDIT 20260922 — 00 MASTER

> 模式：READ-ONLY 分析 | 基线 SHA：`ddd678a` | 提示词：v2.1（`PROMPT_ADVERSARY_20260922.md`）
> 页眉声明：本目录产物为 FULL_AUDIT 专用，**非** `ANALYSIS_PROMPT_PLAYBOOK` 阶段 0–7 产物。
> 状态：**B1–B5 已执行**（§8–§12 批摘要）。**WBS 46/46 完成**（P0 15 + P1 21 + P2 10）；E3 为 BLOCKED 协议关闭。定稿模式：收尾裁决/拟修改清单见 §12。

---

## 0. 总量预估（BR-1，须先于开跑确认）

| 项 | 估值 | 约束 | 满足? |
|----|-----:|------|:-----:|
| WBS 总行数 | **46** | 预估区间 40–50 | ✅ |
| P0 | **15** | ≤15 | ✅ |
| P1 | 21 | — | — |
| P2 | 10 | 可砍 | — |
| 批次数 | **5** | ≤5 | ✅ |
| 每批 P0 | ≤5 | ≤5 | ✅ |
| 每域假设数 | 5–7 | ≤12 | ✅ |
| 重叠 AGENTS 域 | 因子/回测部分行 | 只出增量核验表 ≤15 行 | ✅ |

### 分批计划（每批结束输出：批 ID、命令摘要、变更文件列表）

| 批 | P0 ID | 顺带 P1/P2 | 主落盘 |
|----|-------|------------|--------|
| **B1** | E1,E2,A1,A2,S3 | P1×3 | ✅ `06_engineering_domain.md` 起 + `01_`/`04_` 初稿 |
| **B2** | D1,D2,S1,S2,B1 | P1×5 | ✅ `02_`/`04_`/`05_` 主体 |
| **B3** | B2,F1,F2,L1,L2 | P1×5 | ✅ `03_`/`05_`/`07_` 主体 |
| **B4** | —（P0 已完） | P1×9+ | ✅ 补洞 A3/A4/S6/F3/L3-L6/E3-E5 + E6/E7/F4/F6/S7 顺带 |
| **B5** | — | P2×10 + 收尾 | ✅ A5/D6/B6 + 定稿 + §6 验证回路 + §12 批摘要 |

**Tier-B 预声明（默认不复跑，除非你入批清单）**：五门 IC/PBO 全量、GP 挖掘、regime 26 因子、fundamental 1993s、Wyckoff 5 窗全量扫描、P8/P10/P13 组合回测全量。仅核验**产物在位 + 脚本可导入 + config 一致**。

---

## 1. WBS 状态表

| ID | 分析域 | 具体问题（可证伪） | 输入文件 | 方法 | 输出物路径 | 验收标准(DoD) | 优先级 | 依赖 | 状态 |
|----|--------|-------------------|----------|------|------------|---------------|--------|------|------|
| E1 | 工程健康 | 本会话全量 `pytest`/`ruff`/coverage 是否 0 fail·0 lint·coverage 有数？ | `tests/`, `src/`, `scripts/`, `pyproject.toml` | Tier-A 实跑；失败走 BLOCKED 协议 | `06_engineering_domain.md` §实测 + 附录 | `pytest tests/ -q` 与 `ruff check src/ tests/ scripts/` **本次会话输出**入附录；退出码与计数原文粘贴 | P0 | — | **B1 完成**（ruff exit1/18；pytest exit1/**16 FAILED** 已入附录+根因四家族；coverage BLOCKED 无工具） |
| E2 | 工程健康 | py 文件数/测试数/LOC 与 AGENTS、index、live_map 三方是否一致？差异归因？ | `src/uniquant/**`, `tests/**`, `AGENTS.md`, `docs/index.md`, `I_live_system_map.md` | 实数扫描 vs 三文档声明；冲突裁决 | `06_…md` §对账 + `00` 冲突裁决 | 产出三方对照表（声明/实测/差值）；每差异有 file:line 或命令输出；不一致项 ≥1 条须进裁决 | P0 | E1 | **B1 完成** |
| A1 | 架构分层 | 八层声明与真实 import DAG 是否一致（core import smoke + 层文件计数）？ | `src/uniquant/{shared,data,brain,signal,hands,risk,services,ui}`, `interfaces.py`, `service_container.py` | 八层 import 冒烟；层文件计数；service DAG 源码阅读 | `01_architecture_domain.md` | `python3 -c "import …八层"` 成功输出入文；每层文件数实测表；DAG 依赖边与 live_map 图差异 ≤ 可解释清单 | P0 | E1 | **B1 完成** |
| A2 | 架构分层 | 已宣告归档/死代码是否仍存在、仍被引用？（price_collar / legacy / quality / DynamicSlippage） | `signal/quality.py`, `shared/slippage_model.py`, rg 全 src；历史路径 `shared/archive/*`、`services/archive/*` | Glob+rg 引用计数；与 live_map 死码表对账 | `01_…§死码` + 冲突裁决 | 每个宣告项：存在?/生产引用数?/结论与 live_map 一致或裁决；**已知线索（预核，须复证）**：price_collar 与 analysis_service_legacy **全仓 0 文件** | P0 | A1 | **B1 完成** |
| S3 | 信号与执行 | AGENTS「Wyckoff bare except 已 FIXED」与源码是否一致？（预核见 engine.py:255 等仍 `except Exception:`） | `src/uniquant/brain/wyckoff/engine.py`, AGENTS P0-09 段 | rg 实测 + 行级阅读；历史对账 | `04_signal_domain.md` §冲突裁决 | 列出全部 bare/宽 except 的 `file:line @ ddd678a`；与 AGENTS「FIXED」声明对照表；冲突必入裁决 | P0 | — | **B1 完成（冲突 C4）** |
| D1 | 数据链路 | 日线湖规模/可读性是否支持「净化全市场」宣称？ | `data/lake/quotes/daily/`, `archive_index/`, loader | 目录计数 + 抽样 `read_parquet` + 指数是否仍混入 | `02_data_domain.md` | 文件数实测；抽样 N≥5 可读；000xxx.SH/399xxx.SZ 在 daily 根目录计数写明；失败 BLOCKED | P0 | E1 | **B2 完成**（5755 可读 5/5；archive_index **不存在**；daily 残留指数 554；冲突 C5） |
| D2 | 数据链路 | 财务/派现/分钟三湖是否存在且 schema 可用（不重拉）？ | `data/lake/financial/`, `dividend/`, `minutedaily/` | 计数+抽样列名；对 AGENTS 5211/5123 宣称增量核验 | `02_…§三湖` | 各湖文件数+抽样 columns 列表；与 AGENTS 数字差值表；**Tier-B 不重拉** | P0 | D1 | **B2 完成**（5211/5123/5186+492 全一致，schema 入表） |
| S1 | 信号与执行 | Wyckoff P0-1…7（direction 门/置信 0.40/恒不 SELL-as-entry/RDP 展平）是否仍在位？ | `engine.py`, `signal/adapters.py`, `signal/normalizer.py`, `pack_writer`/`research_pipeline`, `config/config.yaml` | 源码特征检查 + config 键值；已有测试文件存在性 | `04_…§P0密封` | 每项 P0-1…7：在位/失效 + file:line；`confidence_gate: 0.40` 等 config 实测；对照 `tests/test_wyckoff_p0_direction.py` 存在 | P0 | S3 | **B2 完成（7/7 在位）** |
| S2 | 信号与执行 | AlphaScore `score=0.0→SELL` 修复是否仍在位？arbitrator 卖优先是否在位？ | `adapters.py:400` 附近, `arbitrator.py` | 源码断言式阅读 + 相关测试 | `04_…§适配器` | `0 < score < 0.3` 或等价防护 file:line；arbitrator 卖优先/超时键实测；对应测试文件列出 | P0 | S1 | **B2 完成（均在位）** |
| B1 | 回测可信度 | 匹配引擎 A 股约束（T+1/涨跌停/印花/佣金/滑点）是否仍全部生效且有测？ | `unified_matching_engine.py`, `unified_engine.py`, `cost_model.py`, `market_rules.py`, `limit_checker.py`, `tests/` | 源码+测试交叉；**不重跑全量回测** | `05_backtest_domain.md` | 每约束：实现 file:line + 测试文件 + 是否默认开启；缺测项列出 | P0 | E1 | **B2 完成**（9 约束全默认开；缺 `test_unified_engine.py`） |
| B2 | 回测可信度 | H-A hmap 5 日鞍律修复与 `ha_rotation_sim` 是否仍在位？（AGENTS D+13） | `scripts/canslim/ha_unified_adapter.py`, `ha_rotation_sim.py`, `tests/scripts/test_ha_engineering.py` | 源码逻辑核验 + 回归测试存在/可单跑 | `05_…§H-A引擎` | 鞍律关键行 file:line；2 个鞍律回归测试 ID；**允许**仅跑 `test_ha_engineering.py`（非全量回测） | P0 | B1 | **B3 完成**（carried@123,140 + REBALANCE_EVERY=5@51；2 鞍律测试 ID + rotation 358 LOC；未单跑 ha 工程测） |
| F1 | 因子与策略 | H-A 条件 illiq 主线：产物/脚本/config/预注册是否四件套在位且与 AGENTS 数字一致（**增量核验**）？ | `results/factor_mining/{conditional_validation,portfolio_validation_ha,capacity_validation,ha_unified_adapter}.json`, `run_portfolio_validation.py`, `daily_signal_ha.py`, 预注册 md | JSON 键读取 vs AGENTS 宣称；不复跑组合 | `03_factors_domain.md` §增量核验表 | ≤15 行增量表；每行：AGENTS 断言 \| 产物实测值 \| 一致? \| file/键路径；P8 +15.82/1.33 等核心数有 JSON 出处或标丢失 | P0 | D1 | **B3 完成**（15 行表；P8/H-A/capacity 核心数全中；rotation 口径≈差） |
| F2 | 因子与策略 | bp 五门幸存 + P15「可交易无增量」裁决产物是否在位？fwd5 修正模块是否仍在？ | `bp_ha_*.json`, `fundamental_factor_test.json`, `five_gate` 模块, `test_fwd5_regression.py` | 产物+模块+测试存在性；**不复跑五门** | `03_…§bp/P15` | 增量表行；`five_gate`/fwd5 回归测试文件在位；P15 结论文档路径有效 | P0 | F1 | **B3 完成**（bp 0.0558/1.93/0.166 ✓；five_gate+4 测试在位；**C6** P15 数字漂移、**C7** P14 脚本名漂移） |
| L1 | 实盘就绪 | `daily_signal_ha` + `reconcile_ha` 入口是否可导入、CLI `--help`/干跑是否通？（不产真实下单） | `scripts/canslim/daily_signal_ha.py`, `reconcile_ha.py` | import + `--help` + 最小 dry-run（若安全） | `07_live_readiness_domain.md` | 两脚本 import 成功；`--help` 退出码 0 输出入附录；若需数据导致 BLOCKED 则记录 | P0 | E1,B2 | **B3 完成**（import OK、--help exit0、py_compile 0） |
| L2 | 实盘就绪 | 容量/ADV 地板结论对应产物与代码（capacity_validation、ADV 过滤）是否在位一致？ | `capacity_validation.json`, `ha_unified_adapter.py` ADV 段, P10 文档 | JSON vs AGENTS 宣称；代码常量 | `07_…§容量` | 增量表；ADV≥2000 万地板在代码中的 file:line；JSON 关键字段读出 | P0 | F1 | **B3 完成**（4943/+9.98/28.5亿/10% 全中；`amount_floor`@91,94 默认 None） |
| A3 | 架构分层 | ServiceContainer 是否唯一编排入口？legacy/FSM v2 半死状态是否与文档一致？ | `service_container.py`, `analysis_service_v2.py`, `fsm_analysis_engine.py` | 调用图 rg；v2 路径是否触达 FSM | `01_…§编排` | 调用关系表；FSM「不在 v2」有 file:line 反证或证实 | P1 | A1 | **B4 完成**（v2 无 FSM；factory@54 懒加载；instance 消费者 dashboard/di_container） |
| A4 | 架构分层 | 近期未入档提交（qtr-os×4 + blueprint）是否引入新层/新模块/改信号回测路径？ | `git log ddd678a` 起 5 commit, `git show --stat` | 提交 diff 统计 + 新文件清单 vs 八层 | `01_…§未入档提交` + 冲突裁决 | 5 commit 各：触及层、新文件、是否动 signal/hands/risk；AGENTS 未收录事实写明 | P1 | A1 | **B4 完成**（HEAD=ddd678a；4b212f9+0114959+ddd678a 动 signal/hands；research/ 新包） |
| D3 | 数据链路 | DataFetcher→pipeline active 路径是否仍成立？验证/复权/日历是否在链上？ | `data_fetcher.py`, `data_pipeline_service.py`, validators, `trade_calendar_manager.py` | 源码 import+调用点；与 live_map Path1 对账 | `02_…§主链` | 调用链 file:line；断链点列表 | P1 | D1 | **B2 完成**（pipeline 在 `data/` 非 `services/`；无断链） |
| D4 | 数据链路 | PIT/as-of 截断与财务 merge_asof 合同是否仍被 loader/bridge 实现？ | `data_loader.py`, `financial_bridge.py`, `merge_financial_metrics` | 源码+测试存在性 | `02_…§PIT` | 关键函数 file:line；相关测试列表 | P1 | D2 | **B2 完成**（as_of@122-123、merge_financial_metrics@142） |
| D5 | 数据链路 | 指数净化（P0）是否仍有效——`load_symbols("all")` 过滤在位？ | loader/`wyckoff_full_scan._is_index`, `daily/` 抽样 | 源码 + 计数复证 | `02_…§净化` | 过滤函数 file:line；daily 根目录指数文件计数 | P1 | D1 | **B2 完成**（过滤在位；物理归档失败 C5） |
| S4 | 信号与执行 | SignalArbitrator 默认 `max_age` 是否仍 0（backtest-aware 未启用）？卖优先测试在位？ | `arbitrator.py`, `tests/` | 源码+测试 | `04_…§仲裁` | DEFAULT_MAX 值 file:line；测试 ID | P1 | S2 | **B2 完成**（0.0；test_signal_arbitrator+signal/test_arbitrator） |
| S5 | 信号与执行 | RDP「仅展平 wyckoff 键」与 `factor_gate: block` 是否仍配置/实现？ | `pack_writer`/`research_pipeline`, `config.yaml` | 源码+config | `04_…§RDP` | 实现行 file:line；config 实测值 | P1 | S1 | **B2 完成**（pack_writer 白名单在位；collector 全量 metadata 边界 M 级备注） |
| S6 | 信号与执行 | 8 适配器注册完整且无已知反转映射残留？ | `adapters.py`, `signal/__init__.py` | 注册表枚举 vs live_map「8 adapters」 | `04_…§适配器清单` | 适配器名列表；与 live_map 差异 | P1 | S2 | **B4 完成**（8/8 @491-498 = live_map:47 ✓） |
| B3 | 回测可信度 | 成本口径三套（研究 15bp / 引擎万三+印花+千一 / 文档）是否一致或已声明差异？ | `cost_model.py`, `run_portfolio_validation.py` docstring, matching engine | 三处数字对账 | `05_…§成本口径` | 对照表：场景 \| 口径 \| file:line；不一致是否已有文档声明 | P1 | B1 | **B3 完成**（三套已声明；「千一滑点」vs 万5 常量 → **C9**） |
| B4 | 回测可信度 | LPPL「零预测力终结」结论的入口产物是否仍在（只引用不复跑）？ | `scripts/output/walk_forward_definitive_report.json` 等 | 存在性+键抽查 | `05_…§历史终结` | 路径 exists；标「未复跑，沿用」 | P1 | — | **B3 完成**（**MISSING** `scripts/output/` 不存在 → **C8**；沿用 AGENTS 2026-07-23 结论） |
| B5 | 回测可信度 | 滑点默认路径：DynamicSlippage 是否仍死、常数滑点是否唯一生效？ | `slippage_model.py`, matching engine slippage 段 | 引用计数+调用点 | `05_…§滑点` | DynamicSlippage 实例化点数；生产滑点公式 file:line | P1 | B1 | **B3 完成**（全 src 引用=1 仅类定义；常数 SLIPPAGE_PCT 唯一生效） |
| F3 | 因子与策略 | 因子注册表规模/category 与 AGENTS「P12 后终结挖掘」是否一致？注册数实测？ | `registry.py`, `custom_factors.py`, factors.yaml | 实测注册数+列表 | `03_…§注册表` | 注册数+名单；与 AGENTS 声明对照 | P1 | F1 | **B4 完成**（入口 `custom_factors.register_all@687` 自动@988；**39**=tech10/custom16/fund13） |
| F4 | 因子与策略 | five_gate/fwd5 官方口径与 19+4 回归测试是否在位可跑（允许单文件 pytest）？ | `five_gate.py`, `test_p14_*`, `test_fwd5_regression.py` | 存在性+**允许** `pytest tests/test_fwd5_regression.py -q` | `03_…§fwd5` | 测试文件列表；单测退出码（若跑） | P1 | F2 | **B4 完成**（存在性 B3 + **pytest 4 passed EXIT=0**） |
| F5 | 因子与策略 | 预注册文档与 results JSON 键对齐抽查（每赛道 ≥1 条）？ | P3/P8/P11/P12/P14/P15 预注册 md + json | 抽查对齐 | `03_…§预注册对齐` | 抽查表 5+ 行 | P1 | F1 | **B3 完成**（5 赛道预注册 exists + 键对齐表；P15 数值漂移并入 C6） |
| L3 | 实盘就绪 | `live_vs_backtest_differences.md` 15 差距是否仍与代码一致（抽 5 条）？ | 该文档 + matching/engine | 抽样证伪 | `07_…§live差异` | 5 条：文档断言 \| 代码现状 \| 一致? | P1 | B1 | **B4 完成**（5/5 抽样表；SZ 过户仍 SH-only → 文档 2.3 自证 bug 仍在） |
| L4 | 实盘就绪 | 配置/代码是否无明文密钥；secret_manager 是否接线？ | `config/`, `secret_manager.py`, `connect.cfg`, rg 密钥模式 | 只读扫描 | `07_…§安全` | 高危命中列表（可打码）；接线结论 | P1 | — | **B4 完成**（密钥 0 命中；connect.cfg 不存在；secret_manager 仅 export 未接容器） |
| L5 | 实盘就绪 | 可观测性：prometheus/observability/kill_switch 是否实现且被容器接线？ | `prometheus_metrics.py`, `observability.py`, `kill_switch.py`, `service_container.py` | 源码+接线 | `07_…§可观测` | 每组件：实现+接线 file:line 或未接线 | P1 | A1 | **B4 完成**（三实现在位；kill_switch→arbitrator/health/manager；**container 未引用**） |
| L6 | 实盘就绪 | kill_switch/风控 sizer 是否在信号→仓位路径上？ | `kill_switch.py`, `risk/sizer.py`, backtest/portfolio 路径 | 调用链 | `07_…§风控链` | 调用链或「不在路径」证明 | P1 | L5 | **B4 完成**（kill_switch 在 arbitrator 信号路径；PositionSizer 在 container+arbitrator → **在路径**） |
| E3 | 工程健康 | 0% 覆盖文件清单是否仍成立（重测或抽测）？ | coverage 配置, `tests/` | **Tier-A**：E1 coverage 报告解析；不重跑则标注 | `06_…§覆盖` | 文件级 0% 列表 top20；来源=本会话 coverage 或「未复跑沿用」 | P1 | E1 | **B4 完成（BLOCKED）**（coverage/pytest_cov 模块仍缺；沿用 57.88%） |
| E4 | 工程健康 | 死代码 LOC 是否仍 ~2.2k（quality/ DynamicSlippage 等）？ | 死码候选文件 | 行数实测+引用计数 | `06_…§死码` | 候选表 LOC 实测；总和 vs AGENTS | P1 | A2 | **B4 完成**（quality 297 / slippage 47 / fsm 247 / config_models 71 / di 42；archive 0；所列和 <2.2k → 裁决口径） |
| E5 | 工程健康 | CI 三 workflow 是否仍存在且路径有效？ | `.github/workflows/*.yml` | 存在+关键步骤关键字 | `06_…§CI` | 3 文件步骤摘要 | P1 | — | **B4 完成**（test/benchmark/security-audit 3 在位；lint+pytest+pip-audit） |
| A5 | 架构分层 | index.md / live_map / AGENTS 架构数字漂移汇总（权威序 BR-5 应用演示） | 三文档 + 实测 E2/A1 | 冲突裁决样例 | `00` 冲突裁决 § | ≥3 条裁决范例含权威序推理 | P2 | E2,A1 | **B5 完成**（§4 三条范例：文件数/层文件数/测试数） |
| D6 | 数据链路 | 根目录实验残留 py 与 data 关系（只盘点不删） | 根目录 `*analysis*.py` 等 | 列表+是否 import 自 src | `02_…§杂项` | 清单表 | P2 | — | **B5 完成**（9 根目录 py；8/9 import uniquant；只盘点） |
| F6 | 因子与策略 | results/factor_mining 文件清单 vs AGENTS 引用完整性 | `results/factor_mining/`, AGENTS | 存在性矩阵 | `03_…§产物矩阵` | 被引用产物 exists 表 | P2 | F1 | **B4 完成**（dir 23 文件；抽 14 引用 JSON 全 OK） |
| S7 | 信号与执行 | `signal/quality.py` DEPRECATED 死码复证 | `quality.py` | 引用计数 | `04_…§quality` | 调用数+LOC | P2 | S6 | **B4 完成**（297 LOC；ext_refs=5 偏 tests；生产零消费 → 半死维持） |
| B6 | 回测可信度 | golden/baseline 捕获脚本是否仍可用 | `scripts/capture_baseline.py`, `compare_baseline.py`, `tests/benchmark/` | exists+py_compile | `05_…§baseline` | 状态表 | P2 | — | **B5 完成**（2 脚本 compile_ok；golden_20/100+baseline_v0 parquet 在位） |
| E6 | 工程健康 | ruff 配置 per-file-ignores 与 CI lint 范围是否仍覆盖 src/tests/scripts | `pyproject.toml`, `test.yml` | 读配置 | `06_…§lint配置` | 配置实测值 | P2 | E1 | **B4 完成**（`pyproject:57-59` scripts E402；CI `ruff check src tests scripts`@test.yml:30） |
| E7 | 工程健康 | 会话开始/结束 git status 快照（只读纪律证明） | `git status` | 快照 | `00` §纪律 | 首尾 status 粘贴；无 tracked 修改 | P2 | — | **B4+B5 完成**（首/中/尾均 3 untracked 白名单 / TRACKED=0） |

**统计**：P0=15（E1,E2,A1,A2,S3,D1,D2,S1,S2,B1,B2,F1,F2,L1,L2）｜P1=21｜P2=10｜合计 46。**状态：46/46 全部完成**（E3 以 BLOCKED 关闭）。

---

## 2. 执行摘要（B3 后滚动）

**B1** 五 P0 → `01_`/`04_`/`06_`。Tier-A：ruff 18 exit1；pytest **exit1 / 16 FAILED**（四家族）；八层 import 8/8；C3 归档叙事失效；C4 P0-09 假 FIXED；coverage BLOCKED。

**B2** 五 P0 + 顺带 P1×5 → `02_`/`04_`/`05_`。D1 日线 5755 可读但 **archive_index 不存在、daily 残留 554 指数（C5）**；D2 三湖 5211/5123/5186 与 AGENTS 精确一致；S1 **P0-1…7 7/7 在位**；S2 AlphaScore+arbitrator 卖优先在位；B1 九约束默认开、缺 `test_unified_engine.py`；D3-D5/S4/S5 P1 收口。

**B3** 五 P0 + 顺带 P1×5（B3成本/B4 LPPL/B5滑点/F4 fwd5/F5 预注册）→ **新增** `03_factors_domain.md`/`07_live_readiness_domain.md`，**更新** `05_`（鞍律+成本+LPPL+滑点）。F1 十五行表：P8 +15.82/1.33、H-A PASS、capacity 28.5 亿 **全中**；F2 bp 五门键中、**C6** P15 数字漂移、**C7** 脚本名；L1 两入口 import+help 绿；L2 capacity+`amount_floor` 在位；B2 鞍律 carried 在位；**C8** LPPL 产物丢失、**C9** 千一滑点文字冲突。**P0 进度 15/15**。

**B4** 无剩余 P0；P1 补洞 A3/A4/S6/F3/L3-L6/E3-E5 + 顺带 E6/E7/F4/F6/S7（§11）。A3 FSM 不在 v2；A4 HEAD=ddd678a、5 commit 中 3 动 src（signal/hands）；S6 8/8；F3 **39 因子**入口探明；F4 pytest 4 passed；L3 5/5 抽样（SZ 过户 bug 仍在）；L4 密钥 0；L5/L6 kill_switch+sizer **在路径**但 container 未接可观测；E3 BLOCKED；E4 死码口径收窄；E5 三 CI 在位；E6/E7 达标。**P1 主体完成**。

**B5** 收尾：A5 三方漂移 ≥3 条权威序裁演示例入 §4；D6 根目录 **9** 实验 py 盘点入 `02_`；B6 baseline 脚本+golden 在位 `py_compile` OK 入 `05_`；单文件 pytest P14 **EXIT=0**、bp **EXIT=0**；§6 验证回路定稿；**WBS 46/46 完成**（§12）。

## 3. Top-10 风险（滚动，B1–B3 贡献）

排序键（BR-15）：`资金影响(1-5) × 可信度破坏(1-5) × 频率(1-3)`，并列 P0 优先。

| # | 风险 | 分值(资金×可信×频率) | 源 |
|---|------|----------------------|-----|
| 1a | DataValidator auto-fix 10 失败（防线绿区可能已红） | 4×5×5=100 | C2a |
| 1 | 全量测试 16 失败 vs 历史 0 failed（根因已定位） | 3×5×5=75 | E1/C2 |
| 13 | **C6** P15 组合数 JSON≠AGENTS（9.52/0.92 vs 8.91/0.867），控制文档绩效错报 | 4×5×3=60 | F2/C6 |
| 1b | TTM 口径 4 失败 | 3×4×4=48 | C2b |
| 3 | Wyckoff 异常处理文档假 FIXED | 3×4×3=36 | S3/C4 |
| 12 | unified_engine 主路径无专测 test_unified_engine | 3×3×4=36 | B1 |
| 14 | **C8** LPPL 终结报告路径失效，关键负结论不可复核 | 2×5×3=30 | B4/C8 |
| 11 | 指数物理归档失败，绕过 get_symbols 即吸入 554 指数 | 2×5×3=30 | D1/C5 |
| 6 | coverage 不可复证 | 2×3×5=30 | E3 |
| 8 | CLAUDE.md 缺失（前置） | 2×3×5=30 | C0 |
| 15 | **C9** 成本三套（15bp/万5滑/千1滑）跨报告夏普不可比 | 3×4×4=48 | B3/C9 |
| 2 | CI ruff scripts 必红 | 2×4×5=40 | E1 |
| 4 | 控制文档指标全面漂移 | 1×5×5=25 | E2 |
| 5 | archive 死码路径不存在 | 1×4×5=20 | A2/C3 |
| 9 | 未入档 5 commit 改执行路径 | 3×3×2=18 | A4 |
| 7 | research/ 未入层职责 | 2×3×3=18 | A4 |
| 10 | pytest_cov/coverage 环境缺口 | 1×3×5=15 | E1 |

## 4. 冲突裁决

权威序：源码@ddd678a > AGENTS 最新段 > live_map > index > 其他。随批追加；每条仅记一次（B3 收口合并版）。

| # | 冲突 | 权威侧 | 裁决 | 证据 |
|---|------|--------|------|------|
| C0 | 必读 `CLAUDE.md` 不存在 | 实测 | 降级：AGENTS 头部规则段 + index Install 段；不虚构已读 | glob=0 |
| C1 | 三方指标 256/252 vs 264 | 源码@ddd678a | 文档皆旧，以 264/64438/2204 为准 | E2 表 |
| C2 | 2303 passed/0 fail vs 16 FAILED | 本会话 pytest | **历史 0 failed 不再成立**；根因四家族：DataValidator auto-fix×10、TTM×4、HA 算术×1、财务 fixture×1 | E1 FAILED 清单+根因表 |
| C3 | live_map archived 路径 | 文件系统 | 文件已删除而非归档；quality/fsm 半死仍在树 | A2 |
| C4 | P0-09 Wyckoff except FIXED | 源码 | **不成立**：仍有 5×except Exception @255,266,279,289,2153；P0-08 仍成立 | S3 |
| C5 | P0 指数物理归档 archive_index | 文件系统 | **不成立**：`archive_index/` 不存在；daily 根仍 554 指数（000*.SH=200+399*.SZ=354）；净化=读取层 `get_symbols(exclude_indices=True)` 过滤 | D1 |
| C6 | AGENTS P15 bp 组合 +9.52%/0.92/−10.63 vs JSON +8.91%/0.867/−11.33；夏普差 −0.41 vs −0.463 | **JSON@ddd678a** | 以 `bp_ha_portfolio.json` 为准（STRAT_A_cond_bp=0.0891/0.867/−0.1133、Q4=−0.463）；AGENTS 数字降级「待对账」（收尾拟修改清单）；方向结论（bp 弱于 illiq）不变 | `bp_ha_portfolio.json` `.strategies.STRAT_A_cond_bp` / `.verdict.Q4` |
| C7 | AGENTS P14 脚本名 `run_p14_cash_fcf_dy_test.py` | 文件系统 | **不存在**；实名 `scripts/factor_mining/run_cash_fcf_dy_test.py`（路径漂移，功能在位）；另 rotation 7.64 vs AGENTS 7.43 微差 M 级并入本条备注 | pathlib glob |
| C8 | 引用 `scripts/output/walk_forward_definitive_report.json` | 文件系统 | **路径失效**（`scripts/output/` 目录不存在）；结论沿用 Tier-B AGENTS:2026-07-23「未复跑」，产物不可本树复核 | pathlib `**/*walk_forward_definitive*` = 0 |
| C9 | 「千一滑点」文字 vs `SLIPPAGE_PCT=0.0005`（万5） | 源码常量 `cost_model.py:33` | 权威=常量**万5**；三套成本（研究 15bp / 引擎万5滑 / rotation 千1 叙述）各自已 docstring 声明（M 级非静默）；AGENTS/rotation 注释文字待改（批准后） | `cost_model.py:33` vs AGENTS/`ha_rotation_sim.py:16` / `run_portfolio_validation:50` |

### A5 权威序裁决范例（BR-5 演示，≥3 条）

| # | 漂移项 | index/live_map 声明 | AGENTS 声明 | 本会话实测 | 权威序推理 | 裁决 |
|---|--------|---------------------|-------------|------------|------------|------|
| A5-1 | src py 文件数 | **256**（index:5, live_map:233） | **252**（快照表:71） | **264** | 源码@ddd678a 实扫 > 一切文档日期戳 | 三方皆旧；**以 264 为准**（C1 细化） |
| A5-2 | shared 层文件数 | **44**（live_map:17 ✅Match 当时） | AGENTS 层表 44 | **48** | 源码 > live_map 2026-07-09 快照 | live_map 层表过期；A1 表 48 为准 |
| A5-3 | 测试通过数 | 1,673 pass（live_map:5） | 2,051→**2,303/0 fail**（P12 段） | **16 FAILED exit1** | 本会话 pytest 输出 > 历史声明 | **C2**：0 failed 不再成立 |
| A5-4 | coverage | — | 57.88% | BLOCKED（无模块） | 工具缺失无法推翻 | Tier-B 沿用 57.88% 标注不可复证 |

**模式**：凡「计数类」断言一律实测覆盖；凡「绩效/结论类」有 JSON 键的以 JSON 为准（C6）；历史 passed 叙事不得覆盖本会话失败输出（C2）。

## 5. Tier-B 沿用表

| 指标 | 值 | 来源 | 日期 | 复跑? |
|------|----|------|------|-------|
| coverage | 57.88% | AGENTS | 2026-08-05 | 否（无 coverage 模块） |
| 财务湖 5211 | 文件数实测=5211 | **本会话 D2** | 2026-09-22 | 是（文件计数） |
| 派现 5123 / 分钟 5186+492 | 同左 | **本会话 D2** | 2026-09-22 | 是（文件计数） |
| P8 +15.82/1.33 | JSON 精确一致 | portfolio_validation_ha | 2026-08-25 | **是（B3 键读，未跑组合）** |
| 五门 bp IC 0.0558/ICIR 1.93/PBO 0.166 | JSON 键一致 | fundamental_factor_test | 2026-08-26 | **是（B3 键读，未跑五门）** |
| P15 +9.52/0.92 | **≠ JSON**（C6） | AGENTS vs bp_ha_portfolio | 2026-08-28 | 权威=JSON 8.91/0.867 |
| capacity 28.5 亿×10% | JSON 键一致 | capacity_validation | 2026-08-25 | **是（B3 键读）** |

## 6. 验证回路附录（B5 定稿）

| 回路 | 命令 | 结果 | 日期 |
|------|------|------|------|
| 全量 ruff | `ruff check src/ tests/ scripts/` | **18 errors, exit 1**（全 `scripts/wyckoff_multitf/v9_*`） | B1 |
| 全量 pytest | `pytest tests/ -q --tb=no` | **exit 1, 16 FAILED**（原文 `/tmp/opencode/pytest_b1_full.txt`）；四家族根因已定位 | B1 |
| 八层 import | `import shared…ui` | **8/8 OK** | B1 |
| bare/宽 except | `rg except` | bare **0** / `except Exception:` **34** | B1 |
| fwd5 回归 | `pytest tests/test_fwd5_regression.py -q` | **4 passed, EXIT=0** | B4 |
| P14 单文件 | `pytest tests/test_p14_cash_fcf_dy.py -q` | **EXIT=0**（dots≈19，参数化≥AST 17） | B5 |
| bp 组合单文件 | `pytest tests/test_bp_ha_portfolio.py -q` | **6 passed, EXIT=0** | B5 |
| baseline 脚本 | `py_compile capture/compare_baseline.py` | **compile_ok ×2** | B5 |
| coverage | `import coverage` | **FAIL → BLOCKED**，沿用 57.88% | B1/B4 |
| READ-ONLY 纪律 | `git status` 首/中/尾 | **TRACKED=0**；仅 3 白名单 untracked | 全程 |

**未复跑（Tier-B 预声明维持）**：五门 IC/PBO 全量、GP 挖掘、regime 26 因子、fundamental 1993s、Wyckoff 5 窗、P8/P10/P13 组合全量。

## 7. 每批变更文件列表

| 批 | 变更 |
|----|------|
| 预 | PROMPT_ADVERSARY_20260922.md, 00_MASTER.md |
| B1 | **新增** 01_architecture_domain.md, 04_signal_domain.md, 06_engineering_domain.md；**更新** 00_MASTER.md；无源码/config/AGENTS 变更 |
| B2 | **新增** 02_data_domain.md, 05_backtest_domain.md；**更新** 04_signal_domain.md（S1/S2/S4/S5 收口）、00_MASTER.md；无源码/config/AGENTS 变更 |
| B3 | **新增** 03_factors_domain.md, 07_live_readiness_domain.md；**更新** 05_backtest_domain.md（鞍律/成本/LPPL/滑点）、00_MASTER.md（状态行、WBS B2/F1/F2/L1/L2/B3/B4/B5/F4/F5、冲突 C6-C9、§2/§3/§7/§10）；无源码/config/AGENTS/数据变更 |
| B4 | **更新** 00_MASTER.md（状态行、WBS A3/A4/S6/F3/F4/F6/S7/L3-L6/E3-E7、§2、§7、§11）、01_（A3/A4 收口）、03_（F3/F4/F6）、04_（S6/S7）、06_（E3-E7）、07_（L3-L6）；**无新增域文件**；无源码/config/AGENTS/数据变更 |
| B5 | **更新** 00_MASTER.md（状态行、WBS A5/D6/B6、§2、§4 A5 范例、§6 验证回路、§7、§12）、02_（D6 根目录清单）、05_（B6 baseline）；无新增域文件；无源码/config/AGENTS/数据变更 |

## 8. B1 批摘要（DoD：批 ID / 命令摘要 / 变更文件列表）

- **批 ID**：B1（P0 = E1, E2, A1, A2, S3）
- **命令摘要**：`ruff check` 18 errors exit1（全 v9_*）；`pytest tests/ -q --tb=no` exit1 **16 FAILED**（原文 `/tmp/opencode/pytest_b1_full.txt`）；根因定向复跑 `--tb=line` 定位四家族；八层 import 8/8 OK；pathlib 扫 264/64438/172/2204；`rg` 裸 except=0 / `except Exception:`=34。
- **变更文件列表**：新增 `01_architecture_domain.md`、`04_signal_domain.md`、`06_engineering_domain.md`；更新 `00_MASTER.md`。**无源码/config/AGENTS 变更**（READ-ONLY 纪律保持）。
- **冲突新增**：C2 细化（16 FAILED 四家族根因）；C3/C4 维持。
- **状态**：B1 **完成**。

## 9. B2 批摘要（DoD：批 ID / 命令摘要 / 变更文件列表）

- **批 ID**：B2（P0 = D1, D2, S1, S2, B1回测；顺带 P1 = D3, D4, D5, S4, S5 — 实取 5 项，因 S4/S5 与 S1/S2 同锚点）
- **命令摘要**（每命令仅跑一次）：
  - D1/D2：pathlib+pyarrow 扫 lake → daily **5755**、`archive_index` **False**、000*.SH=**200** / 399*.SZ=**354**；抽样 read 5/5 OK（9 列 OHLC…）；financial **5211**（577 列中文 schema）、dividend **5123**、minutedaily **5186** + `quotes/minutedaily_full` **492**。
  - S1/S2/S5：定向读 engine/adapters/normalizer/pack_writer/arbitrator/config → P0-1…7 全在位；`0<score<0.3`@400；`sell_priority=True`@81、`DEFAULT_MAX=0.0`@40；config 8 键实测；`test_wyckoff_p0_direction.py` 9 IDs。
  - B1 回测：五源+测试交叉 → T+1/涨跌停/印花/佣金/滑点/过户/整手 **9 约束默认开**；测试 matching14+unified21+limit30+cost19；**缺 `test_unified_engine.py`**。
  - D3/D4/D5：pipeline 实路径 `data/data_pipeline_service.py`（非 services）；`load_universe as_of`@122；`merge_financial_metrics`@142；`get_symbols(exclude_indices=True)`@407；`_is_index`@49。
- **变更文件列表**：**新增** `02_data_domain.md`、`05_backtest_domain.md`；**更新** `04_signal_domain.md`（S1 七项勾选+ S2/S4/S5 收口）、`00_MASTER.md`（WBS 状态 D1-D5/S1/S2/S4/S5/B1、冲突 C5、§7/§9）。**无源码/config/AGENTS/数据变更**。
- **冲突新增**：**C5**（archive_index 缺失 + 554 指数仍在 daily，归档叙事假，过滤在位）。
- **状态**：B2 **完成**。

## 10. B3 批摘要（DoD：批 ID / 命令摘要 / 变更文件列表）

- **批 ID**：B3（P0 = B2鞍律, F1, F2, L1, L2；顺带 P1 = B3成本, B4 LPPL, B5滑点, F4 fwd5, F5预注册 — 实取 5 项）
- **命令摘要**（每命令仅跑一次）：
  - **B2鞍律**：源码读 `ha_unified_adapter.py` → `TOP_N=30`@50 / `REBALANCE_EVERY=5`@51 / `carried=hmap.get(dates[ti-1])`@123 / `hmap[dt]=carried`@140；`ha_rotation_sim.py` 358 LOC、`engine_params` 万3/万5印花/最低5 @60-63；`test_ha_engineering.py` **16** tests 含 2 鞍律 ID + 1 引擎算术 ID。
  - **F1**：JSON 键 → `conditional_validation` H-A **PASS**；`portfolio_validation_ha` STRAT-A **0.1582/1.331/−0.1288**、CTRL-B/C、Q2b 0.682/Q3 0.727；`capacity_validation` FULL 0.0998/0.933/−0.2215、floor 0.776/−0.128、`held_adv_sum_median_yi=28.5`、`participation=0.1`、F1/F2 verdict False；`ha_unified_adapter` `n_ever_held=385`；rotation 0.0764/0.6811/−0.1281（≈AGENTS 7.43 → 口径差）。→ `03_` 15 行增量表。
  - **F2**：`fundamental_factor_test.json` bp `0.0558/1.9328/0.1655` 三门 true；`bp_ha_unified` scaled_30 `0.0495/0.5184` 中；**`bp_ha_portfolio` STRAT_A 0.0891/0.867/−0.1133 ≠ AGENTS 9.52/0.92 → C6**、Q4 −0.463 vs −0.41 并入 C6；`five_gate.py` LOC=228、`correct_fwd5`@36；`test_fwd5_regression` **4** / `test_p14_cash_fcf_dy` **17** / `test_bp_ha_portfolio` **6**；脚本实名 `run_cash_fcf_dy_test.py` → **C7**；`results/**/five*` = 0。
  - **L1**：两脚本 import OK；`--help` exit 0（daily: `--as-of`；reconcile: `--signal/--prev-signal/--positions/--prices/--drift-tol-pp`）；5 文件 py_compile 0；`AMOUNT_FLOOR=None`@daily_signal:25。
  - **L2**：capacity 键全中 AGENTS P10；`amount_floor` 参数@ha_unified_adapter:91,94、过滤@110-115、主调用@230 未传 → 默认无地板。
  - **P1×5**：B3 `COST_ONE_SIDE=0.0015`@run_portfolio_validation:15,50（15bp 已 docstring 声明）+「千一」文字 vs 万5 → **C9**；B4 `scripts/output/walk_forward_definitive_report.json` **False / 目录不存在** → **C8**；B5 `DynamicSlippage` 全 src 仅 `slippage_model.py:23` 类定义 → 零实例化；F4 在位未单跑 pytest；F5 五赛道预注册 md 全 exists + 键级对齐 ≥5 行。
  - **F3 预采**：`registry.register_all` 从 `uniquant.brain.factors` **ImportError** → 正确入口待 B4 探明。
- **变更文件列表**：**新增** `03_factors_domain.md`、`07_live_readiness_domain.md`；**更新** `05_backtest_domain.md`（去重、鞍律/成本三套/B4/B5 + 对账 + 风险）、`00_MASTER.md`（WBS 15 P0 全绿 + B3/B4/B5/F4/F5、冲突 C6-C9、§2/§3/§7/§10、状态行）。**无源码/config/AGENTS/数据变更**（READ-ONLY 保持）。
- **冲突新增**：**C6**（P15 数字 9.52→8.91）、**C7**（P14 脚本更名）、**C8**（LPPL 产物丢失）、**C9**（千一滑点文字）。
- **P0 进度**：**15/15 全部完成**（E1,E2,A1,A2,S3,D1,D2,S1,S2,B1,B2,F1,F2,L1,L2）。
- **状态**：B3 **完成**。下一步 **B4**（无剩余 P0；P1×9 补洞：A3/A4/S6/F3/L3-L6/E3-E5 + 冲突汇总 + E7 首尾 git status；**非** 全量 Tier-B 复跑）。

## 11. B4 批摘要（DoD：批 ID / 命令摘要 / 变更文件列表）

- **批 ID**：B4（P1 补洞 = A3, A4, S6, F3, L3, L4, L5, L6, E3, E4, E5；顺带 = E6, E7, F4 补跑, F6, S7 — 实取 15 项）
- **命令摘要**（每命令仅跑一次；一条超长组合曾被中止后已拆短重跑）：
  - **A3**：`rg fsm|FSM analysis_service_v2 engine_factory` → v2 **0 命中**；`engine_factory.py:54-55` 懒加载 `FsmAnalysisEngine`；`ServiceContainer.instance` 仅 `ui/dashboard.py:631-634` + `shared/di_container.py:31`。
  - **A4**：`git log ddd678a..HEAD` **空**（HEAD=基线）；5 commit=`68bf789`(docs only)/`4b212f9`(**research/ 新包**+hands+adapters)/`e1877ea`(research/ledger)/`0114959`(composer+pnf+**adapters**)/`ddd678a`(financial_bridge+data+**unified_engine**) → 3/5 动 src 且 signal/hands 被改 → AGENTS 未完整收录。
  - **S6**：`create_default_registry` 8 适配器 lppl/czsc/wyckoff/fsm/regime/ntf/alpha_score/ma_status @ `adapters.py:491-498` = live_map:47 ✓。
  - **F3**：正确入口 `custom_factors.register_all@687`（模块 `:988` 自动调用）；`list_factors()`=**39**（technical 10 / custom 16 / fundamental 13）全 enabled；registry/包 `__init__` 不导出 register_all（B3 ImportError 复证）。
  - **F4**：`pytest tests/test_fwd5_regression.py -q` → **4 passed, EXIT=0**。
  - **L3**：`live_vs_backtest_differences.md` 420 行抽 5 条：1.1 开盘成交@`unified_engine:309` ✓、1.3 部分成交未建模 ✓、1.4 封单未建模 ✓、2.3 深市过户 **仍 SH-only**@matching:207 ✓（文档自判 bug 在）、2.4 DynamicSlippage 类在未接 ✓ → **5/5 文档与代码一致**。
  - **L4**：密钥模式 rg **0 命中**；`config/connect.cfg` **不存在**；`secret_manager.py` 存在且 shared/__init__ 导出，**无生产消费者**（仅 export）。
  - **L5/L6**：三实现文件在；kill_switch 接 `health_service`/`manager_logic`/**`arbitrator:21,112,292`**；PositionSizer 接 `service_container:21,166` + `arbitrator:19,271,357` → **sizer+kill_switch 在信号路径**；`service_container` **不引用** prometheus/observability/kill_switch（容器未接线，组件在旁路服务中接）。
  - **E3**：`import coverage`/`pytest_cov` 仍失败 → **BLOCKED**，Tier-B 沿用 57.88%。
  - **E4**：实测 LOC quality 297(ext_refs=5)/slippage_model 47(ref=1)/fsm 247/config_models 71/di_container 42(ref=0)；price_collar、factor_governance、analysis_service_legacy **MISSING**；archive 目录 0 → 所列和≈784 **< AGENTS ~2.2k**（历史含已删 1,651 legacy 等 → 裁决：AGENTS 死码口径含已删文件，树内半死码收窄）。
  - **E5**：3 workflow 在位——`test.yml`(ruff+pytest+pip-audit)、`benchmark.yml`、`security-audit.yml`。
  - **E6**：`pyproject.toml:57` `[tool.ruff.lint.per-file-ignores]` 在；`test.yml:30` `ruff check src/uniquant/ tests/ scripts/` ✓。
  - **E7 首尾**：`git status` 首尾均 3 untracked（FULL_AUDIT/ + PROMPT_ADVERSARY + prompt v2）、**TRACKED=0**。
  - **F6**：`results/factor_mining/` 23 文件；AGENTS 抽查 14 JSON 全 exists（B1–B3 已核键 + 本批清单）。
  - **S7**：`quality.py` 297 LOC、生产路径无 SignalQuality 消费（tests 有）→ DEPRECATED 半死维持。
- **变更文件列表**：**更新** `00_MASTER.md`、`01_architecture_domain.md`、`03_factors_domain.md`、`04_signal_domain.md`、`06_engineering_domain.md`、`07_live_readiness_domain.md`。**无新增域文件**；**无源码/config/AGENTS/数据变更**（READ-ONLY，E7 TRACKED=0）。
- **冲突新增**：无（C0–C9 维持；E4 死码口径差并入风险 M3 备注，不新开 C 号）。
- **状态**：B4 **完成**。下一步 **B5**（P2×10：A5/D6/B6 收尾 + 定稿 + 验证回路 + 可选单文件 pytest 补跑）。

---

## 12. B5 批摘要（DoD：批 ID / 命令摘要 / 变更文件列表）— 收尾定稿

- **批 ID**：B5（P2 = A5, D6, B6 + 收尾定稿 + 验证回路；E6/E7/F6/S7 已于 B4 完成）
- **命令摘要**（每命令仅跑一次）：
  - **A5**：`rg` 抽 index:5/16、live_map:3/5/17/28/233、AGENTS:71/76/78/172 → 三方数字表；与 E2/A1 实测对照 → §4 **A5-1…A5-4** 四条权威序裁演示例（≥3 DoD ✓）。
  - **D6**：pathlib+ast 扫根目录 `*.py`（非 setup/conftest）→ **9 个**；8/9 含 `uniquant` import + `sys.path` 引导；`factor_analysis_only.py` 无 uniquant（本地分析）；LOC 434–1183；**只盘点不删** → `02_` §杂项。
  - **B6**：`capture_baseline.py`/`compare_baseline.py` exists+**py_compile OK**；`golden_20/100.txt` + `baseline_v0*.parquet` + `golden_500.txt` 在位；docstring CLI 自证 → `05_` §baseline。
  - **单文件 pytest（WBS 允许）**：`test_p14_cash_fcf_dy.py` **EXIT=0**；`test_bp_ha_portfolio.py` **6 passed EXIT=0**。
  - **E7 尾快照**：`git status` TRACKED=0（与 B4 首一致）。
- **变更文件列表**：**更新** `00_MASTER.md`（状态行 WBS 46/46、§2 B5 段、§4 A5 范例、§6 验证回路定稿、§7 B5 行、§12）、`02_data_domain.md`（D6）、`05_backtest_domain.md`（B6）。**无新增域文件**；**无源码/config/AGENTS/数据变更**。
- **拟修改清单（批准后执行，本审计不改）**：
  1. AGENTS/index/live_map 指标刷新 → 264/64438/2204 + 16 FAILED 口径（C1/C2）
  2. AGENTS P15 数字 → JSON 8.91/0.867（C6）
  3. AGENTS P14 脚本路径 → `run_cash_fcf_dy_test.py`（C7）
  4. AGENTS/live_map P0-09 →「5 宽 except fail-open / 0 bare」（C4）
  5. AGENTS P0 归档叙事 →「读取层过滤，archive_index 未落地」（C5）
  6. 统一滑点文字 → 万5 常量（C9）
  7. A4：五提交摘要入 AGENTS Recent Work
  8. LPPL 终结报告引用改为「已丢失，结论沿用」（C8）
- **状态**：B5 **完成**。**WBS 46/46；FULL_AUDIT 20260922 定稿。**下一步：用户审阅本目录 + 决定是否执行拟修改清单 / 修 16 FAILED。

---

**（B5 批摘要已输出；审计定稿；每命令只跑一次；READ-ONLY TRACKED=0。）**
