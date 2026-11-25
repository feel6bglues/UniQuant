# 子代理独立复核：信号生成模块 N2N 深度分析（03_signal_generation）

> **复核人**：独立代码审查子代理（SensenNova 6.8 Flash Lite）
> **复核基线**：`b1d2415`（HEAD，2026-11-24）
> **被复核报告**：`docs/analysis/n2n/03_signal_generation_n2n.md`（Claude，基线 `434aab1`）
> **分析范围**：`src/uniquant/signal/`（`adapters.py` 715 行 + `arbitrator.py` 427 行 + `__init__.py` 52 行 = 1,194 行）
> **纪律**：独立分析先行（未读既有报告前完成全部代码取证）；结论仅以 `file:line` 证据为准；禁止虚构。

---

## ① 执行摘要

对 `src/uniquant/signal/` 三文件逐节点追踪后，**本模块整体健康度评级：B+（良好，有实质行为缺陷）**。

- **已核实为真**：9 个适配器存在且职责清晰；FSM action 映射 10→3 无冲突；Wyckoff 恒不产 SELL-as-entry；Regime 从不产 SELL；ENGINE_PRIORITY 数值与注释一致（`qar=3` 在 `fsm=1` 与 `czsc=2` 之间）；Sell-Priority 在 `arbitrate()` 中生效；Wyckoff 置信门槛 0.40 来自 config 可配置。
- **与既有 Claude 报告的最大分歧**：Claude 报告判定 **0 CRITICAL / 0 HIGH**（§7.1/§7.2 "无"），并称 Sell-Priority 为"✅ SELL 始终优先于 BUY"。**独立复核发现 1 项 HIGH**：主流水线实际走的是 `arbitrate_candidates()`（`research_pipeline.py:373`），其 **Priority 1（DecisionOutput BUY，`arbitrator.py:328-341`）在 Priority 2（SELL-over-BUY，`arbitrator.py:344`）之前短路**——当 DecisionBrain 给出 `BUY` 时，任何引擎的候选 `SELL` 都会被无条件覆盖，**Sell-Priority 不变量在真实生产路径上被违反**（已实测复现：`decision=BUY + candidate SELL(0.9) → 最终 BUY`）。
- **新增 6 项既有报告未覆盖的问题**（HIGH×1 / MEDIUM×5），详见④。其中最关键三点：
  1. **QARAdapter 已注册但从未被 `TradingSignalCollector.collect()` 调用**（`collect()` 内无 `qar` 分支，`adapters.py:600-670`）——QAR 信号并不走标准 collect→仲裁链，而是由 `scripts/canslim/daily_signal_qar.py:202-216` 旁路直构 `TradingSignal` 并内联重算置信公式，存在漂移风险。
  2. **`arbitrate()` 的 Rule 3（引擎优先级）是不可达死代码**：Rule 2 的 `for action in ("BUY","SELL")` 循环（`arbitrator.py:225`）对任何非空 actionable 必返回，Rule 3（`arbitrator.py:238`）永不执行；且 `sell_priority=False` 时 Rule 2 先查 `"BUY"`，使 **SELL 永远输给任意 BUY**（实测：BUY 0.2 vs SELL 0.9 → BUY），与测试注释"highest confidence wins"不符。
  3. **主流水线仲裁路径（`arbitrate_candidates`）根本没有质量门**（无 `quality_threshold` 引用），且 `sell_priority` 标志在该路径被忽略（仅出现于日志字符串）——与 `arbitrate()` 路径行为不对称。

**计数**：CRITICAL 0 · HIGH 1 · MEDIUM 6 · LOW 3（共 10 条）。

---

## ② 五问逐节点答案

N2N 关键路径实测为（与任务描述略有出入，见 Q1）：

```
EngineOutput (brain) / analysis.decision
  → _merge_decision_for_collection (research_pipeline.py:342, 569-606)
  → TradingSignalCollector.collect() (adapters.py:577-679) → List[TradingSignal]
  → _signals_to_candidates (research_pipeline.py:249-262) → List[CandidateSignal]
  → (feature_flags.signal_arbitration) SignalArbitrator.arbitrate_candidates (research_pipeline.py:368-379)
  → UnifiedBacktestEngine.run(signals) (research_pipeline.py:411, unified_engine.py:149)
```

> **注意**：任务描述中的 `SignalAggregator.aggregate() → AggregatedSignal` **不存在**（仅 `adapters.py`/`arbitrator.py`/`__init__.py`；无 `aggregator.py`、无 `SignalAggregator`/`AggregatedSignal` 符号）。"聚合"节点实际由 `collect()` + `_signals_to_candidates()` 承担。

### Q1 定义（Name 定义与契约）

| 节点 | 定义 | 证据 |
|---|---|---|
| EngineAdapter 抽象契约 | `adapt(raw_output: Dict, symbol, timestamp=None, default_shares=100) -> Optional[TradingSignal]` | `adapters.py:37-59` |
| 9 适配器 | LPPL/CZSC/Wyckoff/FSM/Regime/NTF/AlphaScore/MAStatus/QAR | `adapters.py:66,143,180,251,300,341,389,425,461` |
| TradingSignal 契约 | `action:str`(BUY/SELL/HOLD) `reason` `confidence` `shares:int=0` `symbol` `price:float=0.0` `timestamp` `metadata` | `interfaces.py:148-206` |
| CandidateSignal 契约 | `source` `action` `confidence` `direction` `strength` `price_target?` `stop_loss?` | `interfaces.py:44-58` |
| DecisionOutput 契约 | `action` `reason` `confidence` `shares:int=0` `price` `regime` `score` | `interfaces.py:262-289` |

**结论**：契约字段一致，`TradingSignal` 的 8 字段与各适配器构造完全吻合。**唯一契约缺口**：`source_engine` 未进 `metadata`（仲裁引擎只能从 `reason` 子串反推，见 M1/④-H2）。

### Q2 映射（数据流转映射）

| 适配器 | action 映射 | 证据 | 核查结论 |
|---|---|---|---|
| LPPL | Danger→HOLD(diagnostic)/SELL(非diagnostic)；Warning/Safe→HOLD；conf<0.05→None | `adapters.py:104-120` | ✅ 默认遥测（`diagnostic_only=True`），不产强平 |
| CZSC | is_3rd_buy→BUY；!is_3rd_buy且bi_count>0→HOLD；都0→None | `adapters.py:160-166` | ✅ conf=`min(0.5+bi*0.05,0.9)`（**min-cap 存在**，Claude 报告表漏记） |
| Wyckoff | direction∈{做多,买入,轻仓试探} 且 conf≥gate→BUY；否则 None | `adapters.py:193,220-224` | ✅ **恒不产 SELL-as-entry**；gate 0.40 来自 config |
| FSM | BUY←BUY/ADD/EXECUTE_BUY；SELL←SELL/EXECUTE_SELL/FORCE_EXIT；HOLD←HOLD/FORCE_WAIT/CIRCUIT_BREAK/STAY_CURRENT_STATE | `adapters.py:258-269,281` | ✅ 无冲突；未知 action→HOLD（安全降级） |
| Regime | FROZEN/STRESSED→HOLD；NORMAL→None | `adapters.py:318-325` | ✅ **从不产 SELL**（符合设计）；但 HOLD 在候选阶段被滤除（见④-L3） |
| NTF | SUPPORT→HOLD；RESISTANCE∧intensity≥0.6→SELL；否则 None | `adapters.py:358-381` | ✅ **intensity 0.6 为硬编码**（非 config，见④-M6） |
| AlphaScore | score>0.6→BUY；0<score<0.3→SELL；否则 None | `adapters.py:403-409` | ✅ conf=`abs(score-0.5)*2` |
| MAStatus | ">"→BUY；"<="→SELL；否则 None | `adapters.py:439-445` | ⚠️ conf=0.3 **常数**参与 argmax（见④-L2） |
| QAR | is_compliant=False→None；weight>0→BUY；weight<0→SELL；weight=0→None | `adapters.py:475-488` | ⚠️ conf=`min(0.5+weight*10,0.95)`（BUY）/0.8（SELL）；**但 adapter 未被 collect() 调用**（见④-M2） |

**结论**：9 适配器 action 映射规则**无互相冲突**（各引擎产出的 BUY/SELL/HOLD 语义一致）。FSM 的 `_ACTION_MAP` 与 `TradingSignal.from_dict` 的 `action_map`（`interfaces.py:169-177`）完全对齐。

### Q3 传播（依赖链追踪）

| 传播边 | 证据 | 备注 |
|---|---|---|
| data_pack → collect() | `research_pipeline.py:342-356` | `_merge_decision_for_collection` 把 `decision` 的 action/final_decision/shares/confidence/reason/price 并入 `collector_pack` |
| collect() → List[TradingSignal] | `adapters.py:577-679` | 逐引擎 `_extract_*` + `adapter.adapt`，None 过滤 |
| List[TradingSignal] → List[CandidateSignal] | `research_pipeline.py:369` → `_signals_to_candidates` `:249-262` | **仅保留 BUY/SELL**（`:261`），HOLD 全被滤除 |
| candidates → arbitrate_candidates | `research_pipeline.py:368-379` | `decision_output=DecisionOutput.from_dict(analysis.decision)`；`sizer=self._sizer` |
| 仲裁 → backtest.run(signals) | `research_pipeline.py:411-416` | `signals` 为仲裁后列表（0/1 个） |
| signal → 挂单 → 成交 | `unified_engine.py:326-387` | 按日分组 `index_signals_by_date`（`unified_models.py:195-204`）；BUY 仅 `position==0`，SELL 仅 `position>0` |

**关键传播事实**：
- **`arbitrate_candidates` 是主流水线活路径**（`research_pipeline.py:373`）；`arbitrate()` 仅被 QAR 日脚本（`daily_signal_qar.py:216`）、测试与 N2N 验证（`run_n2n_verification.py:228`）使用。Claude 报告 §0/§3.1 称"实际流程：collect()→arbitrate()"**不精确**。
- **Regime HOLD 在 `_signals_to_candidates` 被滤除**（`:261`），因此 Regime 信号节点在候选仲裁路径上**惰性**——regime 风控实际经 FSM `_check_veto_conditions`（`fsm.py:289` FROZEN→FORCE_WAIT）间接生效。
- **QAR 信号不经过 collect()**（无 `qar` 分支），故 QAR 不进 `_signals_to_candidates`——QAR 是旁路（`daily_signal_qar.py`）。

### Q4 变异（边界与异常）

| 变异场景 | 行为 | 证据 | 判定 |
|---|---|---|---|
| KillSwitch 触发 | `arbitrate()` 返回 []；`arbitrate_candidates` 返回 []+veto_chain | `arbitrator.py:117-119,298-304` | ✅ Fail-Closed |
| 无 actionable（全 HOLD） | `_pick_winner` 返回 None | `arbitrator.py:165-169` | ✅ |
| 单信号 | 直接透传 | `arbitrator.py:195-201` | ✅ |
| 多引擎同向 | 取最高 confidence | `arbitrator.py:220-235` | ⚠️ confidence 跨引擎不可比（见④-H1/M4） |
| 多引擎反向（SELL vs BUY） | `arbitrate()`：SELL 优先；**`arbitrate_candidates`：仅当 DecisionOutput 非 BUY 时 SELL 才优先** | `arbitrator.py:204-218` vs `:328-344` | ❌ **违反 Sell-Priority**（④-H1） |
| 信号过期 | `max_signal_age_seconds>0` 才检查，默认 0=禁用 | `arbitrator.py:44-45,125-132` | ✅ 回测安全 |
| 质量门 | 仅 `arbitrate()` Rule 0；**`arbitrate_candidates` 无** | `arbitrator.py:171-187` vs `arbitrate_candidates` | ❌ 不对称（④-M4/M5） |
| 仲裁开关关闭 | `self._arbitrator is None` → `signals` 原样传给引擎 | `service_container.py:161-168`；`research_pipeline.py:368` | ⚠️ 降级=无冲突消解，引擎按位置门+首序取（④-M3） |
| non-FSM BUY 无 sizer | 拒签→HOLD（fail-closed） | `arbitrator.py:386-392` | ✅ |

### Q5 治理（可观测性与可测试性）

| 治理面 | 证据 | 判定 |
|---|---|---|
| ArbitrationLog（symbol/date/action/conf/conflicts/rejections） | `arbitrator.py:48-58,96-98` | ✅ 返回副本（不可变） |
| ArbitrationReport（veto_chain/rejected） | `arbitrator.py:61-71`；pipeline 记日志 `research_pipeline.py:380-385` | ✅ |
| perf_section("adapter.collect"/"pipeline.arbitrate") | `adapters.py:596`；`research_pipeline.py:367` | ✅ |
| KillSwitch reason 入 veto_chain | `arbitrator.py:302-304` | ✅ |
| 测试覆盖 | `tests/signal/test_arbitrator.py`（32 例）+`test_adapters.py`（90 例，本机全绿） | ✅ |

---

## ③ 端到端路径追踪（≥3 条，含 1 条异常）

### 路径 A：Wyckoff 方向入场 → BUY（正常单引擎）
```
WyckoffOutput{phase:"SPRING", direction:"做多", confidence:0.75}
  → _extract_wyckoff (adapters.py:702-715)
  → WyckoffAdapter.adapt (adapters.py:195-244)：direction∈白名单 ✓ conf 0.75≥0.40 ✓
  → TradingSignal(BUY, conf=0.75, shares=100)
  → _signals_to_candidates (research_pipeline.py:249) source="wyckoff"(reason前缀) 
  → arbitrate_candidates：decision_output=FSM(非BUY) → Priority2 无SELL → Priority3 non-FSM BUY → sizer 定股
  → backtest BUY（position==0 → 挂单 → 次日集合竞价成交）
```
**异常注入**：若 `sizer=None`（`bootstrap.create_research_pipeline` 默认，`bootstrap.py:110`），non-FSM BUY 被拒签→HOLD（`arbitrator.py:386-392`）。Claude 报告 §3.3 标为"✅ fail-closed"，**正确**。

### 路径 B：多引擎冲突（异常）——DecisionBrain BUY vs NTF/MAStatus SELL
```
FSM decision = {action:"BUY", shares:200, confidence:0.8}     # DecisionBrain
NTFOutput{ntf_side:"RESISTANCE", ntf_intensity:0.85}          # → NTFAdapter → TradingSignal(SELL, conf=0.85)
  → collect() → [FSM BUY, NTF SELL]
  → _signals_to_candidates → [cand(FSM BUY), cand(NTF SELL)]
  → arbitrate_candidates(decision_output=DecisionOutput(action="BUY", shares=200))
    → Priority 1 (arbitrator.py:328-341)：decision_output.action=="BUY" ∧ shares>0 → 返回 BUY ←【SELL 被覆盖】
    ❌ NTF SELL(0.85) 未参与竞价，Sell-Priority 失效
```
**实测复现**：`decision=BUY shares=200` + `candidate SELL(0.9)` → 最终 `BUY`（veto=`decision_output=BUY shares=200`）；移除 decision 后同输入 → `SELL`。**这证明 Sell-Priority 仅在 DecisionOutput 非 BUY 时成立**。

### 路径 C：仲裁开关关闭（异常降级）
```
feature_flags.signal_arbitration=false 或 service_container._make_arbitrator 抛错
  → arbitrator=None (service_container.py:166-168)
  → research_pipeline.run() :368 跳过仲裁，signals 原样(可含多 BUY/SELL)
  → UnifiedBacktestEngine.run(signals) (unified_engine.py:149)
    → _index_signals_by_date (unified_models.py:195) 同日分组
    → 引擎顺序：LPPL-SELL(:338) → BUY(position==0, :350) → SELL(position>0, :377)
    → 冲突日取【列表中首个 BUY】(若空仓) 或【首个 SELL】(若持仓)
```
**判定**：降级路径**无 Sell-Priority、无置信度比较、无引擎优先级**——完全依赖信号在 `collect()` 中的固定插入顺序（lppl→czsc→wyckoff→fsm→regime→ntf→alpha→ma）与持仓状态门控。属**有序但非语义**的退化，且 `signal_arbitration` 默认值在 `config_models.py:10` 为 `False`、在 `config_schema.py:83` 为 `True`（两套 `FeatureFlags` 默认值相反，见④-L1）；实际 `config.yaml:362` 已设 `true`，故生产默认开启，但任何配置文件缺失即回落为"无仲裁"。

### 路径 D：LPPL 遥测（无交易）
```
LPPLOutput{risk_level:"Danger", confidence:0.85, r_squared:0.35, out_of_sample_r_squared:0.20}
  → LPPLAdapter.adapt (adapters.py:92-136)：diagnostic_only=True(默认) → action="HOLD"
  → TradingSignal(HOLD, conf=0.85, shares=0) → _signals_to_candidates 滤除(:261) → 无候选 → 无交易
```
**判定**：LPPL 只作遥测，不产强平——与 `run_n2n_verification.py`/Claude 报告 §6.4 一致。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### CRITICAL（0）
无。所有问题均为局部行为缺陷，无数据完整性/资金安全级崩溃；KillSwitch 与 Fail-Closed 防线完好。

### HIGH（1）

**H1（行为正确性）— Sell-Priority 不变量在 `arbitrate_candidates`（主流水线活路径）被 DecisionOutput BUY 短路**
- 位置：`arbitrator.py:328-341`（Priority 1 BUY 分支）在 `arbitrator.py:344`（Priority 2 SELL-over-BUY）之前返回。
- 证据：`arbitrate_candidates` 的 Priority 1 对 `decision_output.action=="BUY" ∧ shares>0` 直接 `return [TradingSignal(BUY)]`，未检查任何候选 SELL。实测：`DecisionOutput(action="BUY", shares=200)` + `CandidateSignal(NTF SELL conf=0.9)` → 最终 `BUY`（veto=`decision_output=BUY shares=200`）；去掉 decision 后同一输入 → `SELL`。
- 与文档矛盾：本文件 docstring（`arbitrator.py:4-5`）声明"SELL 始终优先于 BUY"；`run_n2n_verification.py:227-231`（Track 2）亦断言 Sell-Priority——但该验证走的是 `arbitrate()`（`run_n2n_verification.py:228`），**未覆盖主流水线的 `arbitrate_candidates`**。
- 影响：当 DecisionBrain 判定 BUY 而任一独立引擎（NTF/MAStatus/QAR/Wyckoff 风控层）给出 SELL 时，SELL 被静默丢弃 → 可能在高风险日保留多头。这是**风控层失效**。
- 修复建议：在 Priority 1 的 `BUY+shares>0` 分支前，先扫描候选 SELL；若存在 `SELL` 且 `sell_priority` 开启，应转入 Priority 2（SELL 优先）或至少记录 veto_chain 告警。同时让 `run_n2n_verification.py` Track 2 增加一条"decision=BUY + candidate SELL"断言以覆盖活路径。

### MEDIUM（6）

**M1 — `_get_engine_priority` 从 reason 子串反推引擎名，脆弱且易误匹配**
- 位置：`arbitrator.py:264-270`；调用点 `arbitrator.py:259`。
- 证据：`engine in reason_lower` 子串匹配；例 `"sizer approved: wyckoff"`→`wyckoff`(4)，`"decision_brain"`→99。Claude 报告 M1 同判（**一致**）。
- 影响：`_by_engine_priority` 结果不可靠。但注意（见 H2）该函数在 `arbitrate()` 中已不可达，故当前仅理论风险。
- 修复建议：把 `source_engine` 写入 `TradingSignal.metadata`（适配器侧），`_by_engine_priority` 改用 `metadata.get("source_engine")`。

**M2 — QARAdapter 已注册但从未被 `TradingSignalCollector.collect()` 调用**
- 位置：`adapters.py:553`（注册 `"qar"`）；`adapters.py:600-670`（collect 分支列表**无 qar**）。
- 证据：`collect()` 仅处理 lppl/czsc/wyckoff/fsm/regime/ntf/alpha_score/ma_status 八个分支，`"qar"` 从未被 `self._registry.get("qar")` 取用。QAR 信号实际由 `scripts/canslim/daily_signal_qar.py:202-216` 直构 `TradingSignal`（非经 QARAdapter），且其置信公式 `min(0.5+weight_val*10,0.95)`（`:206`）**内联复制**了 `QARAdapter` 逻辑（`adapters.py:482`）。
- 影响：QARAdapter 是"孤立契约"——其行为变更不会传导至生产 QAR 信号；两处公式若漂移即静默分叉。Claude 报告未覆盖。
- 修复建议：让 `daily_signal_qar.py` 复用 `QARAdapter.adapt()`（或至少从 adapter 导出公式常量）；若 QAR 应走标准链，为 `collect()` 增加 qar 分支。

**M3 — 仲裁开关关闭的降级路径无任何冲突消解语义**
- 位置：`research_pipeline.py:368`（`if self._arbitrator is not None` 才仲裁）；`unified_engine.py:350-387`（引擎首序取用）。
- 证据：arbitrator=None 时 `signals` 原样传引擎；引擎按 `collect()` 固定顺序取首个 BUY（空仓）或首个 SELL（持仓），无 Sell-Priority/confidence/engine-priority。
- 影响：依赖调用方保证 `signal_arbitration=true`；配置缺失即退化为无序决策。Claude 报告未覆盖（其 §0 假设仲裁恒启用）。
- 修复建议：仲裁关闭时记录 WARN 并至少按 confidence 排序（或在 pipeline 层兜底一次简单 SELL-priority 过滤）。

**M4 — 主流水线路径（`arbitrate_candidates`）缺失质量门（OOS R²）**
- 位置：`arbitrate_candidates`（`arbitrator.py:272-424`）无 `quality_threshold` 引用；仅 `arbitrate()`/`_pick_winner`（`arbitrator.py:171-187`）有。
- 证据：`inspect` 确认 `arbitrate_candidates` 源码不含 `quality_threshold`。
- 影响：生产主链的 SELL 不再经 OOS 质量把关；且 `_pick_winner` 的质量门因默认 `oos_r2=1.0`（`arbitrator.py:176`，"缺数据=满分"）且仅拦 SELL（`:176`）、而唯一携带 OOS 元数据的 LPPL 现已恒产 HOLD（`adapters.py:111-116`）——**该质量门在实践中几乎从不触发**，属死代码。
- 修复建议：把质量门前置到 `arbitrate_candidates`，且对"缺失 OOS 元数据"默认 fail-closed（拒绝）而非放行，以符合 Rule 4。Claude 报告把此评为"✅ 边界条件处理"，**实为缺陷**。

**M5 — `arbitrate_candidates` 忽略 `sell_priority` 标志**
- 位置：`arbitrator.py:344`（`if sell_candidates:` 无 `self._sell_priority` 守卫）。
- 证据：`inspect` 显示 `sell_priority` 在 `arbitrate_candidates` 中仅出现于日志字符串（`:350`），非守卫；而 `_pick_winner` 有守卫（`:204`）。
- 影响：`SignalArbitrator(sell_priority=False)` 在两条路径行为不一致；主链仍强制 SELL-over-BUY。Claude 报告未覆盖。
- 修复建议：`arbitrate_candidates` 在 Priority 2 前检查 `self._sell_priority`，与 `_pick_winner` 对齐。

**M6 — 置信门槛可配置性不一致（Wyckoff 可配 / NTF 硬编码）**
- 位置：`adapters.py:222`（Wyckoff gate 来自 config `wyckoff.confidence_gate`，实测解析=0.4，`config.yaml:401`）；`adapters.py:371`（NTF `intensity >= 0.6` 硬编码）。
- 证据：config 实测 `c.get('wyckoff.confidence_gate')=0.4`、`direction_gate_enabled=True`；NTF 0.6 无 config 键（`config.yaml` 无 `ntf.intensity_threshold`）。
- 影响：NTF 阈值需改码才能校准；且 `0.6/0.3/0.05/0.40` 等均为无文献依据 magic number（与专家评审 M4 一致）。
- 修复建议：将 NTF 阈值提入 config（如 `ntf.sell_intensity_threshold`），统一阈值治理。

### LOW（3）

**L1 — 两套 `FeatureFlags.signal_arbitration` 默认值相反**
- 位置：`config_models.py:10,24`（默认 `False`）vs `config_schema.py:83,93`（默认 `True`）。
- 证据：`service_container.py:161` 读取的是 `config_models.load_refactoring_config()`（默认 False）；`config.yaml:362` 覆盖为 true 才开启。两文件语义漂移。
- 影响：仅当 `config.yaml` 缺失/被删时仲裁默认关闭，属防御性隐患。Claude 报告未覆盖。

**L2 — MAStatusAdapter confidence=0.3 常数参与 argmax**
- 位置：`adapters.py:449`。
- 影响：MAStatus 同向信号恒输给任何 conf>0.3 的其它引擎，实际几乎从不胜出；且该常数无标定依据。与专家评审 L-B 一致。

**L3 — RegimeAdapter 信号在候选阶段被滤除（节点惰性）**
- 位置：`adapters.py:318-334`（仅 HOLD/None）；`research_pipeline.py:261`（候选仅 BUY/SELL）。
- 影响：Regime 的 FROZEN/STRESSED→HOLD 永不进入仲裁，Regime 风控仅经 FSM `_check_veto_conditions`（`fsm.py:289`）间接生效。属设计意图（与 Claude 报告 L2 一致），但应在文档标注"Regime 信号节点在候选仲裁链上为惰性"。

---

## ⑤ 交叉复核矩阵（对既有 Claude 报告 `docs/analysis/n2n/03_signal_generation_n2n.md`）

| 既有报告结论 | 位置(基线434aab1) | 独立复核判定 | 双方证据 |
|---|---|---|---|
| §0 工作流文档过时：`aggregator.py`/`SignalAggregator` 不存在 | `:10-31` | **一致**（但需补强） | 本复核确认无 `aggregator.py`、无 `SignalAggregator`/`AggregatedSignal`；**补强**：该报告称"实际流程 collect()→arbitrate()"，主流水线实为 `collect()`→**`arbitrate_candidates`**（`research_pipeline.py:373`），`arbitrate()` 仅 QAR 日脚本/测试用 |
| §0 差异严重程度 LOW | `:31` | **一致**（文档过时，无运行时影响） | 一致 |
| §1.2 适配器职责矩阵 | `:91-103` | **部分一致**（摘录不精确） | QAR 写 `0.5+weight×10`、CZSC 写 `0.5+bi_count×0.05`，**均漏 min-cap**（实际 `adapters.py:482/163` 有 `min(...,0.95/0.9)`）——与专家评审 L-A 一致 |
| §2.2 FSM action 映射（BUY←BUY/ADD/EXECUTE_BUY；SELL←SELL/EXECUTE_SELL/FORCE_EXIT） | `:201-243` | **一致** | 本复核确认 `adapters.py:258-269` 无冲突 |
| §2.3 Wyckoff 恒不产 SELL-as-entry | `:245-298` | **一致** | `adapters.py:190-191,224` 非入场方向→None，仅产 BUY |
| §2.4 NTF intensity≥0.6 | `:299-338` | **一致**（但未标注硬编码） | `adapters.py:371`；本复核补强 M6（0.6 非 config） |
| §3.1 传播链 collect()→arbitrate()→run() | `:341-383` | **分歧（路径不精确）** | 报告称 `arbitrate()`；本复核证据：主链 `arbitrate_candidates`（`research_pipeline.py:373`），`arbitrate()` 仅 QAR/测试（`daily_signal_qar.py:216`、`run_n2n_verification.py:228`） |
| §3.3 non-FSM BUY 需 sizer，无 sizer→HOLD（fail-closed） | `:408-455` | **一致** | `arbitrator.py:385-392`；本复核确认 |
| §4.1 质量门默认 OOS R²=1.0 "✅ 边界条件处理" | `:460-493` | **分歧（缺陷被误标为正面）** | 报告称"默认 1.0 不拒绝"为正确；本复核：`arbitrator.py:176` 缺数据=满分放行，与 Rule 4（fail-closed）冲突，且该门仅拦 SELL、唯一携 OOS 元数据的 LPPL 已恒产 HOLD → **实践中几乎不触发（死代码）**；且主链 `arbitrate_candidates` 无此门（M4） |
| §4.2 Sell-Priority "✅ SELL 始终优先于 BUY" | `:495-521` | **分歧（仅 `arbitrate()` 成立）** | `arbitrator.py:204-218` 在 `arbitrate()` 中成立；但主链 `arbitrate_candidates` Priority1 BUY 先短路（`:328-341`），SELL 不变量被违反（H1，已实测复现） |
| §4.3 DecisionOutput 硬约束 "✅ 优先于所有候选信号" | `:522-562` | **分歧（与 §4.2 自相矛盾）** | 报告 §4.3 称 DecisionOutput BUY 优先，与其 §4.2"SELL 始终优先"矛盾；本复核证实 BUY 短路 SELL（H1） |
| §4.4 ENGINE_PRIORITY（fsm=1 最高，lppl=99 最低） | `:564-611` | **一致（数值）但补强** | `arbitrator.py:32-42` 数值吻合（含 `qar=3`）；但报告未发现 **Rule 3 不可达**：Rule 2 `for ("BUY","SELL")`（`:225`）对任意非空 actionable 必返回 → Rule 3（`:238`）死代码，且 `sell_priority=False` 时 BUY 先查使 SELL 恒输（实测：BUY0.2 vs SELL0.9→BUY） |
| §4.4 M1 Engine Priority 匹配脆弱（MEDIUM） | `:612-616` | **一致**（且我补强为不可达死代码） | `arbitrator.py:264-270` reason 子串匹配；报告修复建议（metadata `source_engine`）合理，本复核采纳 |
| §4.5 信号过期默认禁用 | `:617-640` | **一致** | `arbitrator.py:44-45,125-132` |
| §5 可观测性（ArbitrationLog/Report/perf） | `:644-718` | **一致** | 本复核确认全部存在且返回副本 |
| §6 四条典型路径 | `:722-821` | **部分一致** | 路径 1/3/4 与代码吻合；**路径 2（FSM FORCE_EXIT + Wyckoff BUY 冲突）**：报告经 `arbitrate()` 得 SELL；但主链 `arbitrate_candidates` 会把该 FORCE_EXIT 经 `DecisionOutput`（`:320-326`）转 SELL——结论一致，路径不同 |
| §7.1 CRITICAL 无 / §7.2 HIGH 无 | `:827-833` | **分歧** | 本复核发现 **H1（HIGH）**：主链 Sell-Priority 被 DecisionOutput BUY 短路 |
| §7.3 M1（唯一 MEDIUM） | `:837-865` | **一致**（但非唯一 MEDIUM） | 本复核另有 M2~M6 共 6 项 MEDIUM，报告未覆盖 |
| §7.4 L2 RegimeAdapter 从不产 SELL（LOW，设计意图） | `:876-881` | **一致**（补强 L3） | 本复核补强：Regime HOLD 在候选链被滤除（`research_pipeline.py:261`），节点惰性 |
| §8.3 仲裁规则澄清（两条路径） | `:904-913` | **一致**（结构）但补强 | 报告正确区分 `arbitrate()` vs `arbitrate_candidates()`；本复核补强：`arbitrate_candidates` 无质量门、忽略 `sell_priority`、DecisionOutput BUY 短路 SELL（H1/M4/M5） |
| §9 健康度"优秀" | `:917-935` | **分歧（降为 B+）** | 报告未发现 H1 与 M2~M6；本复核评级 B+（良好，有实质行为缺陷） |

**交叉复核汇总**：一致 12 项 · 分歧 6 项（§3.1 路径不精确 / §4.1 质量门误标正面 / §4.2-4.3 自相矛盾 / §7.1-7.2 漏判 HIGH / §9 健康度高估）· 已修复 0 项（代码基线一致，无修复可确认）· 仍遗留 10 项（H1+M1~M6+L1~L3）。

---

## ⑥ 结论与建议

**健康度**：B+（良好，有实质行为缺陷）。适配器层设计优秀、契约一致、Fail-Closed 防线完好；缺陷集中在**仲裁层的活路径语义**。

**必须处置（按优先级）**：
1. **H1（HIGH，P0）**：修复 `arbitrate_candidates` 的 DecisionOutput BUY 短路 SELL 问题——在 Priority 1 BUY 分支前对候选 SELL 做 Sell-Priority 检查（`arbitrator.py:328-341` 前）。这是唯一影响风控有效性的行为缺陷。
2. **M4（MEDIUM，P1）**：为主链 `arbitrate_candidates` 引入质量门，且缺 OOS 元数据默认 fail-closed（符合 Rule 4）；移除/改造 `_pick_winner` 的"缺数据=满分"默认（`arbitrator.py:176`）。
3. **M2（MEDIUM，P1）**：消除 QARAdapter 与 `daily_signal_qar.py` 的公式内联复制（`adapters.py:482` vs `:206`）；如需 QAR 走标准链，为 `collect()` 补 qar 分支。
4. **M1/M3/M5/M6（MEDIUM，P2）**：`source_engine` 入 metadata（弃 reason 子串）；仲裁关闭时记录 WARN 并兜底排序；`arbitrate_candidates` 尊重 `sell_priority`；NTF 阈值提入 config。
5. **L1~L3（LOW，P3）**：统一 `FeatureFlags` 默认值；标注 MAStatus 常数置信度局限；文档标注 Regime 节点惰性。

**建议同步**：`run_n2n_verification.py` Track 2 增加"decision=BUY + candidate SELL"断言，使 N2N 验证覆盖**活路径**（当前仅验 `arbitrate()`），避免 H1 长期逃逸。

---

**复核人声明**：本报告为独立分析，所有 `file:line` 证据取自基线 `b1d2415` 工作树；关键行为结论（H1、H2/Rule3 死代码、M4/M5 不对称、M6 硬编码、discover 键错配、质量门死代码）均经本机 Python 实测复现；与既有报告的分歧仅源于分析方法差异（代码基线 `434aab1→b1d2415` 间 `src/uniquant/signal/` 无变更，`git diff` 为空），非代码漂移所致。
