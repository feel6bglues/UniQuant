# 跨模块集成 N2N 独立子代理验证报告

> **分析日期**：2026-11-24
> **代码基线**：`b1d2415`（HEAD，验证当日）
> **分析方法**：独立子代理逐节点追踪（未参考既有报告即先独立分析，后做交叉复核）
> **范围**：数据湖→分析→信号→仲裁→回测→风控→执行/对账 跨模块契约一致性
> **纪律**：Rule 3（不虚构结果）· Rule 4（缺失输入显式失败）· 独立于既有报告结论

---

## ① 执行摘要

本报告对 UniQuant 跨模块集成做了独立 N2N 逐节点追踪，覆盖 3 条端到端路径（Wyckoff
SPRING→BUY、QAR BUY vs Wyckoff SELL 冲突、KillSwitch 熔断）与全部跨边界契约核查。

**健康度评级：B（可用，有 2 处需治理的跨模块契约漂移 + 若干 LOW 项）。**

问题计数（独立发现）：

| 级别 | 数量 | 核心问题 |
|------|-----:|----------|
| CRITICAL | 0 | 无 |
| HIGH | 1 | F8：`FeatureFlags` 双模型默认值/字段集冲突（config_models vs config_schema） |
| MEDIUM | 4 | F1 探针前提过时；F2 EngineOutput 公共字段无 `reason`；F4 探针 2 "Wyckoff SELL" 不可表示；F9 仲裁器双装配路径分流 |
| LOW | 4 | F3 wyckoff_structural_score 恒 0；F6 source 解析脆弱+分仓回退；F10 降级路径未测；F13 checkpoint 丢 data_pack |

**与既有报告（`docs/analysis/n2n/09_cross_module_integration.md`，基线 434aab1）交叉复核：**
既有报告的 M1（LPPL SELL 优先级）**方向成立但代码证据系虚构**（已独立核实：真实代码在
`unified_engine.py:339-348` 的 `sig.reason` 含 "lppl" 特判，非其引用的 `priority=0`）；
既有报告的 `ENGINE_PRIORITY` 表 **方向颠倒**（报告 LPPL=1 最高，实际 `arbitrator.py:32-42`
`lppl:99` 最低、`fsm:1` 最高）；H1（数据入口不一致）、服务清单 "13 服务"、M2/L2（简化版
信号）、L1（文档文件名）在 HEAD 均**仍遗留**。详见 §6。

---

## ② 五问逐节点答案

### Q1 定义：跨模块契约是什么、在哪里定义？

契约分散在 `shared/interfaces.py`（typed 契约 + protocols）与各模块的常量/数据类中，
**没有单一契约注册表**。

| 契约 | 定义位置 | 关键字段 |
|------|----------|----------|
| `TradingSignal` | `shared/interfaces.py:148-206` | `action/reason/confidence/shares/symbol/price/timestamp/metadata` |
| `ResearchDataPack` | `shared/interfaces.py:210-258` | `symbol/stock_df/index_df/regime/lppl/ntf/czsc/wyckoff/alpha/factors/metadata` |
| `PipelineResult` | `services/research_pipeline.py:80-105` | `symbol/data_pack/decision/signals/backtest/success/error/trace_id/metrics` |
| `BacktestResult` | `hands/backtest/unified_models.py:53-100` | `trades/equity_curve/daily_returns/initial_capital/final_cash/metadata/benchmark_return` + `total_trades/total_return/sharpe/max_drawdown/win_rate`（property） |
| 日线 9 列湖契约 | `data/data_fetcher.py:41-51` | `date/open/high/low/close/amount/volume/reserved/code` |
| 5 分钟 8 列契约 | `data/sources/tdxdata_online.py:100` | `datetime/open/high/low/close/volume/amount/code` |
| `FeatureFlags` | `shared/config_models.py:7-32` **与** `shared/config_schema.py:81-99`（两份！） | `signal_arbitration/factor_gate/event_bus/use_research_data_pack/...` |
| `EngineOutput` 公共字段 | **不存在统一类型** — 引擎返回裸 `Dict` | 各引擎 keys 不一致（见 F2） |

**发现 F8（HIGH）**：`FeatureFlags` 存在**两个互不一致的模型**：
- `config_models.py:10-12`：`signal_arbitration=False`、`factor_gate="off"`、`event_bus=False`，字段含 `typed_contracts`、`engine_migration`。
- `config_schema.py:83-84`：`signal_arbitration=True`、`factor_gate="block"`、`event_bus=True`，字段**无** `typed_contracts`/`engine_migration`。
- 运行时消费方（`service_container.py:158`、`analysis_service_v2.py:39`）都走 `config_models`；`config_schema` 仅作为另一套校验模型导出（`shared/__init__.py:31`）。
- 因 `config/config.yaml:362-376` 显式给出全部值，当前无活动 bug；但**当 feature_flags 键缺失时**，运行时默认 `signal_arbitration=False`/`factor_gate="off"`，而 schema 默认 `factor_gate="block"`、`config_validator.py:127` 默认 `"off"`——三者默认口径漂移，属跨模块契约风险。

### Q2 映射：契约如何在边界间映射（有无丢失）？

| 边界 | 映射 | 丢失/变异 |
|------|------|-----------|
| 湖 9 列 → `ResearchDataPack.stock_df` | `fetch_research_pack`（`data_service.py:468`）→ `from_dict` 原样承接 `raw["stock"]` | **无丢失**（`fetch_for_brain:459` 直取湖 df） |
| `stock_df` → 回测 | `prepare_backtest_dataframe`（`unified_models.py:177-192`）仅校验 `date/open/high/low/close/volume`，**补** `pre_close`/`avg_daily_volume` | 9 列契约保留；`reserved` 列随 df 透传，未删 |
| `WyckoffOutput` → `data_pack`（RDP） | `RDPackWriter.write_wyckoff`（`pack_writer.py:130-156`）把扁平键写入 `metadata`，typed 对象写 `data_pack.wyckoff` | **P0-3 刻意只展平 wyckoff 键**（防 LPPL 阈值复活），非丢失 |
| `data_pack` → `MarketSignalContext` | `_make_decision`（`analysis_service_v2.py:616-618`）`to_dict()` 后 `update(metadata)`，metadata 扁平键**覆盖** typed 对象键 | **无丢失**（RDP 路径靠 metadata 承载扁平字符串/数值键，`from_dict` 才取得到 `regime="NORMAL"`/`ntf_side`/`alpha_score`） |
| `data_pack` → `TradingSignalCollector` | `_merge_decision_for_collection`（`research_pipeline.py:569-606`）同 `to_dict()`+`update(metadata)` | **无丢失**（`wyckoff_phase/direction/confidence`、`alpha_score`、`ntf_side` 均在 metadata） |
| `TradingSignal` → `UnifiedBacktestEngine` | `_index_signals_by_date`（`unified_models.py:195-204`）按 `sig.timestamp` 键日 | 回测只消费 `action/shares/reason`；**`confidence` 在回测边界被丢弃**（仅元信息，可接受） |
| 引擎输出 → `TradingSignal` | 各 Adapter `.adapt()` | **见 F2/F4** |

**F2（MEDIUM）**：`EngineOutput` 公共字段不统一。Wyckoff 引擎输出
（`wyckoff/analysis.py:477-488`）含 `action`/`confidence` 但**无 `reason`**；`_extract_wyckoff`
（`adapters.py:702-715`）也不取 `reason`。且 WyckoffAdapter 在 `adapt()` 里**忽略引擎算出的
`action`**，改由 `wyckoff_direction`+`confidence_gate` 重导（`adapters.py:224-225`）——引擎与
适配器各自独立判 BUY。两者同读 `wyckoff.confidence_gate`（引擎 `engine.py:704`，适配器
`adapters.py:222`）且同关键词集（`{"做多","买入","轻仓试探"}`），**当前不漂移**；但属双源
真相 + DRY 隐患，若一方改配置键名即静默分歧。

**F3（LOW）**：`_extract_wyckoff`（`adapters.py:702-715`）未透传 `structural_score`，而
`WyckoffAdapter.adapt` 元数据写 `wyckoff_structural_score`（`adapters.py:242`）——**恒为 0.0**，
属标注面字段丢失（仅元数据，不影响方向）。

### Q3 传播：字段/状态如何跨节点传播（有无中断）？

- **`feature_flags.signal_arbitration` 传播链**：`config.yaml:362`（true）→ `load_refactoring_config`
  （`config_models.py:69`）→ `service_container.py:158-165` `_make_arbitrator`（true 则装配
  `SignalArbitrator`，false/异常则返回 None）。**但**：`bootstrap.py:81-93`
  `create_signal_arbitrator` 是**另一条装配路径**，不检查 flag、恒构造。见 F9。
- **`feature_flags.factor_gate` 传播链**：`config.yaml:364`（"block"）→ `service_container.py:174-183`
  → `FactorRegistry.set_mode(FactorAccessLevel("block"))`。与 `config_validator.py:127` 校验
  （off|warn|block）一致。✓
- **信号传播**：`TradingSignalCollector.collect` → `arbitrate_candidates`（管线路径，
  `research_pipeline.py:373`）→ `UnifiedBacktestEngine.run`（`research_pipeline.py:411`）。
- **中断点**：`arbitrate_candidates` 的 Priority 1（`arbitrator.py:312-341`）在
  `decision_output.action=="BUY" and shares>0` 时**短路全部候选**（直接返回 decision_brain 的
  BUY），Wyckoff/QAR 候选被整体覆盖——属设计意图（DecisionBrain 硬约束），但**使探针 2 的
  冲突仲裁在"决策层已给 BUY"时根本不进入 Sell-Priority 分支**。

### Q4 变异：跨节点是否存在语义/值变异？

- **方向变异**：Wyckoff 引擎输出 `action` 与适配器重导的 `action` 同源同参（见 F2），当前一致。
- **`reason` 变异**：各引擎 `reason` 文本形态不一；`_signals_to_candidates`
  （`research_pipeline.py:257`）以 `reason.split(":")[0].split(" ")[0].lower()` 推 `source`——对
  `reason="QAR_TOP_WEIGHT"` 得 `source="qar_top_weight"`（≠"qar"），在 `arbitrate_candidates`
  中被归入 non-FSM BUY（`arbitrator.py:365`），需 sizer 才能放行；而 `daily_signal_qar.py:216`
  走的是 `arbitrate()`（列表路径），无此影响。见 F6。
- **KillSwitch 变异**：`arbitrate()`（`arbitrator.py:117-119`）与 `arbitrate_candidates`
  （`arbitrator.py:298-304`）在 `get_kill_switch().is_killed` 时均返回空信号列表——Fail-Closed ✓。

### Q5 治理：跨模块契约是否有守卫/测试？

- 9 列契约：`data_fetcher.py:38-51` 冻结注释 + `GET_PRICE_RETURN_CONTRACT`；但**无运行时校验器**
  在每层强制（引擎各自 `_validate_input` 只查子集列）。
- `feature_flags.factor_gate`：有测试（`test_service_container.py:6-27`、`test_config_validator.py`）。
- `feature_flags.signal_arbitration`：**降级路径（flag=False→arbitrator=None→管线旁路仲裁）无测试**
  （见 F10）。
- `FeatureFlags` 双模型：**无一致性测试**（F8）。

---

## ③ 端到端路径追踪（≥3 条，含 1 条异常）

### 路径 A（探针 1）：Wyckoff SPRING → BUY（正常路径）

```
data/lake/quotes/daily/600519.SH.parquet  (9 列)
  → DataService.fetch_research_pack("600519.SH")   [data_service.py:468]
  → ResearchDataPack.stock_df (9 列保留)           [interfaces.py:210]
  → AnalysisService._run_wyckoff                   [analysis_service_v2.py:508]
  → WyckoffAnalysisEngine.run_wyckoff_analysis     [wyckoff_analysis_engine.py:198]
  → WyckoffOutput(direction=..., confidence=...)   [wyckoff_analysis_engine.py:162-167]
  → RDPackWriter.write_wyckoff (扁平键入 metadata) [pack_writer.py:130-156]
  → _merge_decision_for_collection                 [research_pipeline.py:569]
  → TradingSignalCollector._extract_wyckoff        [adapters.py:702-715]
  → WyckoffAdapter.adapt → TradingSignal(action="BUY")  [adapters.py:195-244]
  → SignalArbitrator.arbitrate_candidates          [research_pipeline.py:373]
  → UnifiedBacktestEngine.run (七防线 A-G)         [unified_engine.py:149-441]
  → BacktestResult
```
**结论**：链路完整；但**"SPRING→BUY" 前提过时**（见 F1）。实际 BUY 由 `direction∈{做多,买入,轻仓试探}`
∧ `confidence≥0.40` 驱动（`analysis.py:453-462`、`adapters.py:224`），`spring` 仅作标注
（`adapters.py:238` metadata）。七防线逐一核验：T+1（`unified_engine.py:254`）、涨跌停（`:548/:630`）、
停牌（`:216`）、资金（`:571/:583`）、非对称成本（`:596/:643`）、滑点（`:553/:635`）、整手（`:560`）✓。

### 路径 B（探针 2）：QAR BUY vs Wyckoff SELL 冲突 → 期指分仓 → 对账（异常/冲突路径）

```
QARAdapter.adapt({weight:0.05}) → TradingSignal(BUY, conf=0.95)   [adapters.py:468-501]
  + 注入 TradingSignal(SELL, conf=0.80, metadata={strategy:"WYCKOFF"})  ← 合成信号
  → SignalArbitrator(arbitrate/sell_priority)  Sell-Priority → SELL 获胜  [arbitrator.py:203-218 / 344-361]
  → InstitutionalExecutionOrchestrator 75/25-IH                     [institutional_execution_orchestrator.py:40-44]
  → allocate_capital: 75% 多头 / 25% 现金 / -75% 期指               [orchestrator.py:153-168]
  → plan_futures_hedging_structure → design_multi_pb_hedging_allocation (3 PB, ≤1200 手)  [cffex_engine.py:211-284]
  → daily_signal_qar.py 写 "futures_hedging_orders": hedge_structure  [daily_signal_qar.py:230]
  → reconcile_qar.py::reconcile_futures_hedging                     [reconcile_qar.py:261-311]
```
**结论**：`total_short_contracts_needed`/`accounts` 字段对接**无缝**（见 F5，PASS）。但
**"Wyckoff SELL conf=0.80" 不可由真实适配器产生**（见 F4）——该冲突路径在**生产配置下不存在**，
仅 N2N 验证脚本以合成信号注入（`run_n2n_verification.py:220-222`）。

### 路径 C（探针 3）：KillSwitch → 全局熔断（异常路径）

```
AssetManager.stop_trading(reason) → get_kill_switch().kill(reason)
  → DiskStateStore 持久化 (Fail-Closed)
  → SignalArbitrator.arbitrate → is_killed → 返回 []          [arbitrator.py:117-119]
  → arbitrate_candidates → is_killed → 返回 [], veto_chain    [arbitrator.py:298-304]
  → PreTradeComplianceEngine.check_order → OrderRejected("KILL_SWITCH_ACTIVE")
```
**结论**：Fail-Closed 守卫在仲裁层与合规层双保险，`test_production_kill_switch.py` 覆盖 ✓。

### 路径 D（异常：数据缺失 → 显式失败）

`reconcile_qar.py::resolve_market_prices`（`:174-177`）：标的数据湖缺价时
`raise FileNotFoundError`（**严禁伪造 50.0 兜底**，Rule 4 Fail-Closed）✓。
`daily_signal_qar.py:113-121`：000300.SH 期指基准缺失 → `raise FileNotFoundError`（**严禁伪造
4000.0 兜底**）✓。两处均满足 Rule 4。

---

## ④ 契约一致性矩阵

| 契约 | 生产方 | 消费方 | 一致性 | 证据 |
|------|--------|--------|--------|------|
| `TradingSignal`（signal→backtest） | adapters/arbitrator | `unified_engine.run` | ✅ 一致 | `action/shares/reason` 同构；`confidence` 回测侧弃用（元信息） |
| `TradingSignal`（signal→risk/execution） | arbitrator | daily_signal_qar 写盘 | ⚠️ 部分 | `to_dict()` 序列化 8 字段，`from_dict` 回读兼容；`metadata` 保留 |
| `ResearchDataPack` 9 列契约 | data_service | 引擎/管线 | ✅ 无丢失 | `fetch_for_brain` 直取湖 df；`prepare_backtest_dataframe` 只补列不删列 |
| `EngineOutput` 公共字段 | 各引擎 Dict | 各 Adapter | ❌ 不统一 | Wyckoff 无 `reason`（`analysis.py:477`）；Adapter 忽略引擎 `action` |
| `PipelineResult` | 管线 | result_store/AnalysisRecord | ✅ 一致 | `total_return/mdd/sharpe` 由 `BacktestResult` property 派生（`unified_models.py:60-100`）；UI 不直消费 PipelineResult |
| `feature_flags.signal_arbitration` | config.yaml | service_container/bootstrap | ⚠️ 双路径 | `config_models` 门控 vs `bootstrap` 恒构造（F9） |
| `feature_flags.factor_gate` | config.yaml | service_container→FactorRegistry | ✅ 一致 | `config_validator` 校验 off/warn/block 同口径 |
| `FeatureFlags` 模型 | config_models vs config_schema | — | ❌ 漂移 | 默认值/字段集冲突（F8） |
| 期指分仓↔对账 | orchestrator.plan_futures_hedging_structure | reconcile_futures_hedging | ✅ 无缝 | `total_short_contracts_needed`→`target_contracts`；`accounts`→`{account_id:{contracts}}`；`unit_value_rmb`→`unit_contract_value` |

---

## ⑤ 问题清单（分级 + 证据 + 修复建议）

### HIGH

**F8 — `FeatureFlags` 双模型默认值与字段集冲突**
- 证据：`shared/config_models.py:10-12`（`signal_arbitration=False`,`factor_gate="off"`,`event_bus=False`，含 `typed_contracts`/`engine_migration`）vs `shared/config_schema.py:83-88`（`signal_arbitration=True`,`factor_gate="block"`,`event_bus=True`，**无** `typed_contracts`/`engine_migration`）。运行时消费方 `service_container.py:158`、`analysis_service_v2.py:39` 均走 `config_models`；`config_schema` 经 `shared/__init__.py:31` 导出为另一套 `AppConfig`。`config_validator.py:127` 默认 `"off"` 与 `config_schema:84` 默认 `"block"` 又互异。
- 影响：`feature_flags` 键缺失时，运行时默认**关闭**仲裁/因子门，而 schema 默认**开启**，验证与运行口径漂移；两模型字段集不同（`typed_contracts`/`engine_migration` 仅其一有）。
- 修复：统一为单一权威 `FeatureFlags`（建议以运行时 `config_models` 为准，或让 `config_schema` 委托 `config_models`），并为"键缺失→默认值"写一致性测试。

### MEDIUM

**F1 — 探针 1 "Wyckoff SPRING→BUY" 前提过时**
- 证据：`wyckoff/analysis.py:453-462`（P0-6/P0-7：仅 `direction∈{做多,买入,轻仓试探}`∧`confidence≥gate` 产 BUY）；`adapters.py:190`（"恒不产 SELL-as-entry"）；`adapters.py:224`（spring 不参与方向判定）。
- 影响：以 "SPRING→BUY" 为探针的 N2N 链路描述与实际 P0 后实现不符，无法按描述追踪；SPRING 现仅作标注。
- 修复：更新探针定义为 "direction gate→BUY"，并在 N2N 文档中标注 P0 语义变更。

**F2 — `EngineOutput` 公共字段（action/confidence/reason）跨引擎不统一**
- 证据：`wyckoff/analysis.py:477-488` 输出无 `reason`；`adapters.py:224-225` 忽略引擎 `action` 重导；`adapters.py:702-715` `_extract_wyckoff` 不取 `reason`。对比 `LPPLAdapter`（`adapters.py:123-126`）以 `risk`/`confidence` 自建 reason。
- 影响：无统一 `EngineOutput` 类型；各引擎对同一"决策三字段"的命名/携带不一致，跨引擎 diff 困难，且 Wyckoff 存在引擎/适配器双源判 BUY。
- 修复：引入统一 `EngineOutput` 数据类（`action/confidence/reason`），Wyckoff 引擎输出补 `reason`，并让 Adapter 优先消费引擎 `action`（同参同源）。

**F4 — 探针 2 "Wyckoff SELL conf=0.80" 不可表示（N2N 验证保真度缺口）**
- 证据：`adapters.py:190`（Wyckoff 恒不产 SELL）；`wyckoff/analysis.py:454`（恒不产 SELL）；`scripts/maintenance/run_n2n_verification.py:220-222`（以**合成** `TradingSignal(SELL, metadata={strategy:"WYCKOFF"})` 注入）。
- 影响：N2N Track 2 验证了 Sell-Priority 规则本身，但**未证明**真实 Wyckoff SELL 能到达仲裁器（它不能）——探针与生产语义脱节。
- 修复：改用可真实产生的冲突（如 NTF RESISTANCE SELL `adapters.py:370-380` 或 QAR weight<0 SELL `adapters.py:483`）作为 Sell-Priority 探针；或在报告中明示该信号为合成探针。

**F9 — 信号仲裁器双装配路径分流**
- 证据：`service_container.py:155-168`（`_make_arbitrator` 检查 `signal_arbitration` flag）vs `bootstrap.py:81-93`（`create_signal_arbitrator` 恒构造，不检查 flag）。
- 影响：`bootstrap` 路径绕过 feature flag 治理，两套装配口径不一；`run_n2n_verification.py:227` 恰用 `bootstrap.create_signal_arbitrator`。
- 修复：让 `create_signal_arbitrator` 也经 flag 门控，或统一单一装配入口。

### LOW

**F3 — `wyckoff_structural_score` 恒为 0.0**
- 证据：`adapters.py:702-715`（`_extract_wyckoff` 未透传 `structural_score`）+ `adapters.py:242`（元数据写 `wyckoff_structural_score`）。
- 影响：标注面字段丢失（不影响方向/风控）。修复：`_extract_wyckoff` 补 `structural_score`。

**F6 — `_signals_to_candidates` source 解析脆弱 + 对账分仓回退静默**
- 证据：`research_pipeline.py:257`（`reason.split(":")[0].split(" ")[0].lower()`；`QAR_TOP_WEIGHT`→`qar_top_weight`≠`qar`，被 `arbitrator.py:365` 归 non-FSM）；`reconcile_qar.py:291`（账户名不匹配时 `actual_contracts // 3` 静默回退）。
- 影响：管线路径下 QAR BUY 可能被误判需 sizer；对账在账户名错位时静默均分，掩盖真实分仓。
- 修复：`CandidateSignal.source` 改由显式字段注入而非 reason 解析；对账账户名不匹配时 `Fail-Closed` 报错而非均分。

**F10 — `signal_arbitration=False` 降级路径无测试**
- 证据：`tests/` 全仓 `grep signal_arbitration` 仅命中 `test_e2e_integration_qa.py:860`（行为测试）与 `test_signal_arbitrator.py:54`（行为测试），**无** flag=False→arbitrator=None→管线旁路的降级用例；对比 `factor_gate` 有 `test_service_container.py:6-27`。
- 影响：开关关闭时旁路仲裁的行为无回归保护。
- 修复：补一条容器/管线级测试：`signal_arbitration=False` → `_make_arbitrator` 返回 None → 管线把原始信号直送回测。

**F13 — checkpoint 恢复丢 data_pack**
- 证据：`research_pipeline.py:221`（`_result_from_checkpoint_dict` 设 `data_pack={}`）；`:479-480` 自述"Checkpoint 恢复后 data_pack 为空字典"。
- 影响：断点续跑无法复用 K 线，只能从 decision/signals/backtest 继续（设计取舍，但应文档化）。
- 修复：维持现状并在文档明示（已自述），或 checkpoint 存 `symbol` 以便恢复时重拉。

---

## ⑥ 交叉复核矩阵（vs 既有报告 `docs/analysis/n2n/09_cross_module_integration.md`，基线 434aab1）

| 既有结论 | 级别（既有） | 我的独立复核 | 裁定 | 双方证据 |
|----------|:---:|------|:---:|----------|
| M1：LPPL SELL 优先级遗留（`unified_engine.py:337-348`） | MEDIUM | 行为方向**成立**，但**代码证据系虚构** | **仍遗留（证据需重述）** | 既有引 `if engine=="LPPL" and direction=="SELL": priority=0`。独立核实：该文件无 `priority` 变量；真实代码为 `unified_engine.py:339-348` 的 `sig.action=="SELL" and "lppl" in sig.reason.lower()` 特判建 SELL 挂单，**绕过统一仲裁**。即"LPPL SELL 在回测被特殊处理"方向对，但位置/代码要重定位。注：默认配置 LPPLAdapter `diagnostic_only=True`（`adapters.py:111`），该特判实际少触发。 |
| `ENGINE_PRIORITY` 表（§1.2，LPPL=1 最高…QAR=9） | — | **方向颠倒** | **分歧（既有事实错误）** | 既有表 `LPPL:1(最高)`。独立核实 `arbitrator.py:32-42`：`lppl:99(最低)`, `fsm:1(最高)`, `czsc:2`, `qar:3`, `wyckoff:4`, `regime:5`, `ntf:6`, `alpha_score:7`, `ma_status:8`。键为小写；LPPL 因 MC 证伪降为遥测层。 |
| H1：数据入口 `fetch_history()` vs `get_price()` | HIGH | 描述不准确 | **仍遗留（描述性）** | `data_fetcher.py:493` 确有 `fetch_history`；brain 实际入口是 `DataService.fetch_for_brain`（`data_service.py:456`）/`fetch_research_pack`（`:468`）→ `get_price`。既有报告 §1.1/§2.1 以 `fetch_history` 为入口，非真实链路。 |
| "13 服务 + PortfolioService/RiskEngine" DAG（§0.1） | MEDIUM | 服务清单不实 | **仍遗留（事实错误）** | 独立核实 `service_container.py` `initialize()` 注册 **12** 功能服务：storage/calendar/cache/time_provider/engine_factory/market_cache/analysis_service/backtest_engine/signal_collector/arbitrator/research_pipeline；**无** PortfolioService/RiskEngine。 |
| M2/L2：`enrich_lake_data` 简化版信号 | MEDIUM（评审）/LOW（报告） | 确认 | **仍遗留** | `ui/manager_logic.py:156-169`：`close>open→BUY`、`close>high*0.9→3rd_BUY`，非真实引擎输出；展示为 `signal`/`czsc_stat` 列（`:170/:175`）。 |
| L1：`degrees_of_freedom_ledger.py` 文件名 | LOW | 确认 | **仍遗留** | 实际文件 `src/uniquant/research/ledger/degrees_of_freedom.py`（工作流文档命名错误）。 |
| 9 列契约一致（§4.1 WF1→WF2） | ✅ | 确认 | **一致（PASS）** | `data_fetcher.py:41-51` 冻结；`fetch_for_brain` 直取湖 df 保留 9 列。 |
| 9 适配器统一转换（§4.1 WF2→WF3） | ✅ | 确认 | **一致（PASS）** | `create_default_registry`（`adapters.py:540-554`）注册 9 个：lppl/czsc/wyckoff/fsm/regime/ntf/alpha_score/ma_status/qar。 |
| KillSwitch Fail-Closed + DiskStateStore（§1.4/§2.3） | ✅ | 确认 | **一致（PASS）** | `arbitrator.py:117-119/298-304`；`test_production_kill_switch.py`。 |

> 复核结论：既有报告的 **M1 代码证据系虚构**（独立第三方评审已指出，本次独立复核再次证实），
> **ENGINE_PRIORITY 方向颠倒**（报告与实现相反），服务清单/数据入口描述不实。这些是既有报告
> 的**事实性缺陷**，非本次可修复的代码问题。其余 LOW/MEDIUM 项在 HEAD 均仍遗留。

---

## ⑦ 结论与建议

### 结论
- **跨模块契约总体健康**：9 列湖契约、`TradingSignal` 边界、`PipelineResult`→`BacktestResult`
  派生、期指分仓↔对账字段、KillSwitch Fail-Closed 均无缝/一致。
- **2 处需治理的契约漂移**：`FeatureFlags` 双模型（F8，HIGH）与仲裁器双装配路径（F9，MEDIUM）。
- **N2N 验证保真度缺口**：探针 1 前提过时（F1）、探针 2 "Wyckoff SELL" 不可表示（F4）——验证
  脚本验证了规则本身，但两个探针与生产语义脱节，需重定义探针或明示合成信号。
- **既有报告事实缺陷**：M1 虚构代码、ENGINE_PRIORITY 方向颠倒、服务清单/入口不实——建议
  对 `docs/analysis/n2n/` 全 10 份报告做一轮代码证据复核（本报告即跨模块一份）。

### 建议（按优先级）
1. **P1**：统一 `FeatureFlags` 单一权威模型 + 键缺失默认值一致性测试（F8）。
2. **P1**：修正 N2N 探针定义（F1/F4）并给验证脚本加真实 SELL 冲突源（F4）。
3. **P2**：统一仲裁器装配入口（F9）；补 `signal_arbitration=False` 降级测试（F10）。
4. **P2**：引入统一 `EngineOutput`（action/confidence/reason）（F2）。
5. **P3**：修复 F3/F6/F13 与既有报告事实性缺陷（M1 重述、ENGINE_PRIORITY 表、服务清单、入口）。

### 验证声明
- 本报告所有 `file:line` 均于 HEAD `b1d2415` 实际读取核实；未虚构任何代码/行号。
- 未运行全量测试（超出本子代理范围）；`file:line` 证据全部来自静态阅读。

---

**分析人**：独立子代理（N2N 跨模块集成）· 基线 `b1d2415` · 2026-11-24
