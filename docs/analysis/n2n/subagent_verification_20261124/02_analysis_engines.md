# 02 分析引擎模块 — 独立 N2N 深度分析（子代理复核报告）

> **复核人**：独立子代理（SenseNova 6.8 Flash Lite，`sensenova-6.8-flash-lite`）
> **复核日期**：2026-11-24
> **代码基线**：`b1d2415`（工作树，`git rev-parse HEAD` = `b1d24157a35b6885edfb64ea52aac70239a09528`）
> **分析范围**：`src/uniquant/brain/`（73 文件 / 20,917 行，实测与 AGENTS.md 分毫不差）
> **方法论**：独立 Name-to-Name（N2N）逐节点审查，先独立取证后交叉复核既有报告
> **纪律**：Rule 3（不虚构结果）/ Rule 4（不伪造输入）/ Rule 8（手术式改动，本报告只读不改码）

---

## ① 执行摘要

对 `src/uniquant/brain/` 全部 10 个子引擎 + 服务层 N2N 接线做了独立逐节点审查，追踪了 3 条端到端路径（含 1 条异常路径）。核心结论：

**健康度评级：B-（条件通过，必须先修复 CRITICAL/HIGH 后才能放行生产）**

| 级别 | 数量 | 代表问题 |
|---:|---:|---|
| CRITICAL | 1 | C1：`pre_close` 在 N2N 生产路径**从不写入** `MarketSignalContext` → FSM 熔断与涨跌停检查成为**死代码** |
| HIGH | 2 | H1：LPPL `diagnostic_only=True` 只门控采集器路径，**DecisionBrain 路径仍按 LPPL Danger 强平**；H2：工厂创建的 `DecisionBrain()` 无 `evt_risk`/`sizer` → 仓位与风控被绕过 |
| MEDIUM | 5 | M1–M5（见 §④）：`czsc_bottom` 不传播、前视防护不一致、Regime 缓存口径、`run_fsm_analysis` 死路径陷阱、HOLD 不否决 BUY 候选 |
| LOW | 6 | L1–L6（见 §④）：FactorRegistry 懒加载桩、门控默认 WARN、LPPL R² 双口径、FSM 状态文件共享、structural_adjust 默认关、NTF/Regime 共 `_date` |

**最重要的独立发现（既有报告全部遗漏）**：
- **C1（CRITICAL）**：`pre_close` 在整个 `services/`+`brain/` 层只被 `fsm.py` **读取**，**从无任何写入**。因此 `ctx.pre_close` 恒为 `0.0`，`fsm.py:338`（跌停卖）、`fsm.py:392`（涨跌停买）、`fsm.py:578`（熔断 daily_return）的 `if ctx.price > 0 and ctx.pre_close > 0:` 守卫恒为假 → **熔断与涨跌停保护在生产路径完全失效**。回测路径 `unified_models.py:186` 却会 `df["close"].shift(1)` 生成 `pre_close`，故**回测有涨跌停/熔断、实盘决策无**——正是 N2N 要抓的回测-实盘分裂。
- **H1（HIGH）**：`adapters.py:545` 用 `LPPLAdapter(diagnostic_only=True)` 只让**采集器**不产 SELL；但 `DecisionBrain.make_decision` 读 `ctx.risk=="Danger"` 后 `fsm.py:302` 直接 `FORCE_EXIT`、`fsm.py:327` 追加 `LPPL_DANGER` 卖出条件，且仲裁器 `arbitrator.py` Priority-1 把 `FORCE_EXIT` 转成 SELL。**"LPPL 降为遥测"只完成一半**。
- **H2（HIGH）**：`engine_factory.py:88` 用 `DecisionBrain()`（无参）创建，`evt_risk=None`、`sizer=None`；`_execute_buy`（`fsm.py:414-439`）因此恒走 `{"建议仓位": 100}` 与 `risk_scaler=1.0` 兜底 → **生产路径仓位恒 100 股、无 EVT 风控**。

---

## ② N2N 五问逐节点答案

N2N 关键路径（实际接线，与委托书声明的拓扑核对）：
```
DataService.fetch_research_pack (ResearchDataPack)
→ AnalysisService._prepare_data (analysis_service_v2.py:314)
→ AnalysisService._run_engines: _run_regime/_run_lppl/_run_ntf/_run_czsc/_run_wyckoff/_run_alpha/_calculate_derived
→ AnalysisService._make_decision (analysis_service_v2.py:610) → MarketSignalContext.from_dict → DecisionBrain.make_decision
→ TradingSignalCollector.collect (research_pipeline.py:351)
→ SignalArbitrator.arbitrate_candidates (research_pipeline.py:373)
```

> ⚠️ 委托书描述的 `AnalysisEngineFactory.create(engine_name)` **不存在**（`engine_factory.py` 只有 `_lazy_init` + 属性，无 `create` 方法）；引擎通过 `self._factory.<engine>` 属性（`analysis_service_v2.py:110-136`）或 `_run_engines` 内直连（Regime/NTF 用 `RegimeDetector`/`NTFEngine`）实例化。

### Q1 定义（命名与契约）——逐节点

| 节点 | 契约/命名 | 证据 | 裁决 |
|---|---|---|---|
| 1. DataService | `ResearchDataPack`（类型化包）`symbol, stock_df, regime: RegimeOutput, lppl, ntf, czsc, wyckoff, alpha, factors, metadata` | `interfaces.py:210-258` | ✅ 清晰；`to_dict()` 把 `regime` 等**对象**放入平铺键，依赖 `metadata` 覆盖，见 Q2 |
| 2. 引擎工厂 | 7 个引擎属性（fsm/czsc/lppl/regime/ntf/macro/report/brain/wyckoff）；**无 `create()`** | `engine_factory.py:53-99` | ⚠️ 命名与委托书不符；`factory.regime`/`factory.ntf` 属性**未被 `_run_engines` 使用**（Regime/NTF 在服务层直连实例化） |
| 3. 引擎输出 | `RegimeOutput/LPPLOutput/CZSCOutput/NtfOutput/WyckoffOutput/AlphaOutput`（dataclass） | `interfaces.py:294-542` | ✅ 强类型输出契约明确；`WyckoffOutput` 44 字段 |
| 4. DecisionBrain | `make_decision(data_packet: Union[dict, MarketSignalContext])` | `fsm.py:547` | ✅ 类型化输入；但 `from_dict` 只认平铺键，见 Q2 |
| 5. 采集器 | `TradingSignalCollector.collect(data_pack)` + 8 适配器注册 | `adapters.py:561-679, 540-554` | ✅ 注册表含 8 引擎：lppl/czsc/wyckoff/fsm/regime/ntf/alpha_score/ma_status/qar |

### Q2 映射（数据流转映射）——逐节点

| 节点 | 映射方式 | 证据 | 问题 |
|---|---|---|---|
| 1→2 | `fetch_research_pack` → `ResearchDataPack.from_dict(raw, symbol)`；`raw={"stock","bench","etf"}` | `data_service.py:468-483` | ✅ `stock_df=data.get("stock")`，`index_df=data.get("index") or data.get("bench")` |
| 2→3 | `_run_regime` 写 `metadata["regime"]=str(regime)`；`_run_lppl` 写 `metadata["risk"]=risk_level`；`_run_czsc` 写 `metadata["is_3rd_buy"]/["bi_count"]`；`_run_wyckoff` 写 `metadata["wyckoff_*"]` | `analysis_service_v2.py:417-422,440,497-503,516-526`；`pack_writer.py:104-156` | ⚠️ **`czsc_bottom` 从不写入 metadata/flat**（见 M1）；**`pre_close` 从不写入**（见 C1） |
| 3→4 | `_make_decision`：`dict_pack=to_dict()` + `dict_pack.update(metadata)` → `MarketSignalContext.from_dict(dict_pack)` | `analysis_service_v2.py:616-621` | ⚠️ 依赖 metadata 覆盖 to_dict 的对象键；**`price` 来自 `_calculate_derived` metadata**（`analysis_service_v2.py:587-591`）✓ |
| 4 内部 | `_calculate_score`/`_check_sell_conditions`/`_check_buy_blockers` 读 ctx 字段 | `fsm.py:308-408` | ⚠️ `ctx.pre_close=0` 使涨跌停/熔断守卫恒假（C1）；`ctx.czsc_bottom=None` 使 sizer 拿 None（M1） |
| 4→5 | `_merge_decision_for_collection`：`to_dict()+metadata+decision` | `research_pipeline.py:569-605` | ✅ 把 `action/final_decision/shares/confidence/reason/price` 合并进采集包 |
| 5→6 | `_extract_*` 逐引擎取字段 → `AdapterRegistry` | `adapters.py:681-715` | ⚠️ Wyckoff 44 字段仅 8 个被适配器消费（见 §"Wyckoff 字段浪费"） |

### Q3 传播（依赖链追踪）——逐节点

- **Regime→决策**：`_run_regime` 写 `metadata["regime"]`（大写字符串 `NORMAL/STRESSED/FROZEN/UNKNOWN`，`regime_detector.py:19-23`）→ `ctx.regime` → `_check_veto_conditions` FROZEN→FORCE_WAIT、`_check_sell_conditions` STRESSED→REGIME_RISK。✅ 传播完整（大小写匹配 `MarketRegime`，`interfaces.py:12-17`）。
- **LPPL→决策**：`metadata["risk"]=risk_level`（`pack_writer.py:113`）→ `ctx.risk` → `fsm.py:302` FORCE_EXIT / `fsm.py:327` LPPL_DANGER。⚠️ **与采集器的 `diagnostic_only=True` 相悖**（H1）。
- **CZSC→决策**：`metadata["is_3rd_buy"]` → `ctx.is_3rd_buy` → `_calculate_score` +`FSM_SCORE_CZSC`（`fsm.py:311-312`）。✅ 传播完整。
- **Wyckoff→信号**：仅经 `TradingSignalCollector`（`adapters.py:619-625`），**DecisionBrain 完全不消费 wyckoff 字段**（`fsm.py` 无 wyckoff 引用）。✅ 叙事+信号双轨，方向仅来自 `wyckoff_direction` gate。
- **Alpha→决策**：`metadata["alpha_score"]` → `ctx.alpha_score` → 得分/卖出/买入阻断。✅ 传播完整。
- **NTF→决策**：`metadata["ntf_side"]` → `ctx.ntf_side` → `fsm.py:302`（`ntf_side!=SUPPORT` 才 FORCE_EXIT）。✅ 传播完整。

### Q4 变异（边界条件与异常）——逐节点

- **空数据**：`_prepare_data` 返回 `None`（stock_df empty/None）→ `run_ticker_analysis` 返回 `success=False, error="数据不足"`（`analysis_service_v2.py:279-285`）。✅ Fail-Closed。
- **引擎失败**：`_run_regime` 捕获 `RECOVERABLE_ERRORS` → `mark_engine_status("regime","ENGINE_FAILED")`（`analysis_service_v2.py:425-429`）；`_make_decision` 中 `_risk_engine_blockers` 把 `engine_status["regime"]=ENGINE_FAILED` → FORCE_WAIT（`fsm.py:253-269`）。✅ Fail-Closed。
- **置信度不足**：Wyckoff `direction∉{做多,买入,轻仓试探}` 或 `confidence<0.40` → 返回 None（`adapters.py:224-225`）；LPPL `confidence<0.05` → None（`adapters.py:104-105`）；CZSC `!is_3rd_buy and bi_count==0` → None（`adapters.py:160-161`）。✅ 无信号产出。
- **⚠️ 前视偏差异常**：`FSM.infer_state` 的 `iloc[:-1]`（`fsm.py:102`）**不在 N2N 路径**；N2N 用 `_calculate_derived` 全量 `.iloc[-1]`（M2）。

### Q5 治理（可观测性/可测试性）——逐节点

- 引擎状态：`mark_engine_status` 写 `metadata["engine_status"]`（`pack_writer.py:163-171`）→ `DecisionOutput.engine_status`（`interfaces.py:274`）→ `_risk_engine_blockers` 消费。✅
- 事件总线：`EngineCompleted`/`SignalsCollected`/`DecisionProduced` 发布（`analysis_service_v2.py:358-388`，`research_pipeline.py:358-389`）。✅
- 测试覆盖：`brain` 层 82.66%（CI，AGENTS.md 快照）；但 **`run_fsm_analysis` 无调用方（死路径）**，`FsmAnalysisEngine` 未进 N2N。
- ⚠️ `FactorRegistry._ensure_loaded` 为**空桩**（`registry.py:56-61`），与"Lazy-load custom factors"注释不符（L1）。

---

## ③ 端到端路径追踪（≥3 条，含 1 条异常）

### 路径 A（典型·多头共振 → BUY）
```
fetch_research_pack("600519") → ResearchDataPack
→ _prepare_data → _run_regime(NORMAL) + _run_lppl(Safe) + _run_ntf(SUPPORT) + _run_czsc(is_3rd_buy=True) + _run_wyckoff(做多,conf=0.55) + _run_alpha(+0.7) + _calculate_derived(ma="MA20 > MA60")
→ _make_decision: dict_pack=to_dict()+metadata → ctx(regime=NORMAL, risk="Safe", is_3rd_buy=True, alpha=0.7, ma_status="MA20 > MA60", price, atr_stop, returns)
→ make_decision: score=+CZSC+TREND+ALPHA=…；_check_veto:无；_check_sell:无；_determine_target_state→SIGNAL/MONITOR；_check_buy_blockers:无；_execute_buy
→ FSMAdapter(_ACTION_MAP) → TradingSignal(BUY, shares=决策shares)
→ collector.collect：CZSC BUY + Wyckoff BUY + alpha BUY 候选
→ arbitrate_candidates：decision_output.action=BUY & shares>0 → Priority-1 BUY（decision_brain）
```
**裁决**：路径完整、类型映射正确。**⚠️ 但 `_execute_buy` 的 `shares` 恒为 100（evt_risk/sizer=None，H2），且 `pre_close=0` 使涨跌停/熔断守卫跳过（C1）。**

### 路径 B（避险·LPPL Danger → 分歧）
```
_run_lppl → risk_level="Danger" → metadata["risk"]="Danger"
→ ctx.risk="Danger"
→ 采集器路径：LPPLAdapter(diagnostic_only=True) → action="HOLD"（adapters.py:116，不产 SELL）
→ DecisionBrain路径：_check_veto_conditions ctx.risk=="Danger" 且 ntf!=SUPPORT → FORCE_EXIT（fsm.py:302）
→ arbitrator Priority-1：FORCE_EXIT → TradingSignal(SELL)（arbitrator.py）
```
**裁决**：⚠️ **同一 LPPL Danger 在两条路径给出相反结论**（HOLD vs SELL）。这是 H1 的实证路径——"LPPL 已被 MC 证伪 → 遥测"只在采集器侧生效，DecisionBrain 仍强制平仓。

### 路径 C（异常·空数据 / 引擎失败 → Fail-Closed）
```
(a) 空数据：_prepare_data 因 stock_df empty → return None → TickerAnalysisResult(success=False, error="数据不足")，signals=[]（analysis_service_v2.py:279-285）
(b) 引擎失败：_run_regime 抛错 → mark_engine_status("regime","ENGINE_FAILED") → _risk_engine_blockers: "REGIME_UNKNOWN" blocker → make_decision 返回 FORCE_WAIT（fsm.py:294-301）→ arbitrator Priority-1 FORCE_WAIT → HOLD（不交易）
(c) 置信度不足：Wyckoff direction="空仓观望"/conf<0.40 → adapt 返回 None → 无 Wyckoff 信号（adapters.py:224）
```
**裁决**：✅ 异常路径 Fail-Closed（不产信号、阻断交易、显式状态标记）。与 Rule 4 一致。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### CRITICAL

**C1 — `pre_close` 从不写入 `MarketSignalContext` → FSM 熔断与涨跌停检查在生产路径成死代码**
- 证据：`fsm.py:338`、`fsm.py:392`、`fsm.py:578` 三处 `if ctx.price > 0 and ctx.pre_close > 0:`；`ctx.pre_close` 由 `MarketSignalContext.from_dict` 读 `data.get("pre_close", 0.0)`（`interfaces.py:110`）；但整个 `services/`+`brain/` 层**无任何** `pre_close` 写入（`grep -rn "pre_close" src/uniquant/services/ src/uniquant/brain/` 仅命中 fsm.py 的读取；`pack_writer.py` 不写 `pre_close`；`_calculate_derived` 只写 `price/atr_stop/returns/ma_status`，`analysis_service_v2.py:581-604`）。
- 后果：`ctx.pre_close` 恒 `0.0` → 三处守卫恒假 → **`LIMIT_DOWN` 卖出阻断、`LIMIT_UP` 买入阻断、`CIRCUIT_BREAK` 熔断态全部不触发**。回测路径 `unified_models.py:186` 却用 `df["close"].shift(1)` 生成 `pre_close` → **回测有涨跌停/熔断，实盘决策无**（回测-实盘分裂，N2N 最该抓的类）。
- 修复建议：在 `_calculate_derived`（`analysis_service_v2.py:586-604`）或 `_make_decision` 中，从 `stock_df` 计算 `pre_close = stock_df["close"].shift(1).iloc[-1]`（或用 `open`/昨收列），写入 `metadata["pre_close"]`；并在 `MarketSignalContext` 构造路径确保传递。**修复后须补 `pre_close` 传播的定向测试**。

### HIGH

**H1 — LPPL `diagnostic_only=True` 只门控采集器路径；DecisionBrain 仍按 LPPL Danger 强平**
- 证据：`adapters.py:545` `register("lppl", LPPLAdapter(diagnostic_only=True))`；`adapters.py:111-116` `is_diagnostic` 时 `action="HOLD"`（不产 SELL）；但 `fsm.py:302` `if ctx.risk=="Danger" and ctx.ntf_side.value!="SUPPORT": return FORCE_EXIT`、`fsm.py:327` `if ctx.risk=="Danger": sell_conditions.append("LPPL_DANGER")`；`pack_writer.py:113` 把 `risk_level` 写进 `metadata["risk"]` → `ctx.risk`；仲裁器 `arbitrator.py` Priority-1 `FORCE_EXIT → TradingSignal(SELL)`。
- 后果："LPPL 已被 MC 证伪（零预测力）→ 降为遥测"（`adapters.py:71-75` 注释声称）**只完成一半**：采集器侧不产 SELL，但 DecisionBrain 侧仍把 LPPL Danger 转成强制平仓。两套并行决策体系在 LPPL 上**互相矛盾**。
- 修复建议：① 在 `DecisionBrain` 引入 `lppl_diagnostic_only` 配置门（默认 True），`_check_veto_conditions`/`_check_sell_conditions` 仅在非 diagnostic 时读 `ctx.risk=="Danger"`；或 ② 移除 `metadata["risk"]` 对 `ctx.risk` 的传播（LPPL 只作为遥测 metadata），明确由 EVT/宏观引擎承担 `risk`。并补一条**红蓝测试**：LPPL Danger + `diagnostic_only=True` 时 DecisionBrain 不得产 SELL。

**H2 — 工厂创建的 `DecisionBrain()` 无 `evt_risk`/`sizer` → 仓位恒 100 股、EVT 风控被绕过**
- 证据：`engine_factory.py:88` `self._engines["brain"] = DecisionBrain()`（无参）；`fsm.py:191-214` `__init__` 默认 `evt_risk=None, sizer=None`；`fsm.py:414-439` `_execute_buy`：`self.evt_risk.calculate_metrics(...) if self.evt_risk is not None else {}`、`self.sizer.calculate_shares(...) if self.sizer is not None else {"建议仓位": 100}`。
- 后果：N2N 生产路径（`_make_decision` → `self.brain` = `_factory.brain` = 无参 `DecisionBrain()`）中，`risk_level` 恒 "LOW"、`final_shares` 恒 `100 * 1.0`。**仓位决策与 EVT 风险等级在实盘路径被旁路**，仅死代码 `fsm_analysis_engine.py:75-82` 才注入 `evt_risk/sizer`（而该方法无调用方）。
- 修复建议：在 `AnalysisService.__init__`/`_make_decision` 中构造 `DecisionBrain(evt_risk=self.evt_risk, sizer=self.sizer)`（或由容器注入 `EVTRisk`/`PositionSizer`），并确认 `evt_risk`/`sizer` 非 None。补一个断言测试。

### MEDIUM

**M1 — `czsc_bottom` 计算后从不传播 → `sizer.calculate_shares(czsc_bottom=None)` 恒为 None**
- 证据：`czsc_analysis_engine.py:79` 计算 `bottom=signals.get("czsc_bottom_price")` 存入 `CZSCOutput.bottom`；但 `pack_writer.py:44-47`（Dict）与 `pack_writer.py:124-127`（RDP）只写 `is_3rd_buy/bi_count`，**不写 `czsc_bottom`**；`fsm.py:432` `sizer.calculate_shares(czsc_bottom=ctx.czsc_bottom)`。
- 后果：仓位计算器拿不到缠论底部价（若 sizer 依赖它，止损/仓位偏保守或出错）。
- 修复建议：在 `write_czsc` 增加 `data_pack["czsc_bottom"]/metadata["czsc_bottom"]=output.bottom`。

**M2 — 前视防护不一致：`FSM.infer_state` 的 `iloc[:-1]` 不在 N2N 路径；其余引擎全用 `.iloc[-1]`**
- 证据：`fsm.py:100-102`（`infer_state` 盘中模式 `df.iloc[:-1]`）；但 N2N 路径只走 `DecisionBrain.make_decision`（`_make_decision`，`analysis_service_v2.py:622`），`infer_state` **无调用方**；N2N 的 MA 状态来自 `_calculate_derived` 用 `calc_ma(stock_df).iloc[-1]`（`analysis_service_v2.py:571-577`）；CZSC `czsc_engine.py:74`、Wyckoff `engine.py:292`、LPPL `engine.py:516`、NTF `ntf_engine.py:66-72` 全用 `.iloc[-1]`。
- 后果：EOD 场景无碍（最后一根为已收盘日线），但若在**盘中**用不完整当日 K 线跑 N2N，则所有引擎（除未接线的 `infer_state`）都引入前视。且 `is_intraday` 模式在 N2N 路径完全未接线。
- 修复建议：要么在 N2N 路径显式接线 `is_intraday` 分支（用 `df.iloc[:-1]` 计算指标、`iloc[-1]` 作当前价），要么在 `_run_engines` 前明确丢弃未收盘 K 线；并在文档标注 EOD/盘中口径。

**M3 — Regime 市场级缓存为"按日历日"而非严格 24h TTL；`get_or_compute_regime` 持锁计算**
- 证据：`market_cache.py:73` `if self._date == self._today()`（日历日，非 24h）；`market_cache.py:72-78` `compute_fn()` 在 `with self._lock:` 内执行（锁内计算）。
- 后果：① 非严格 24h（周末/盘中刷新到次日才失效，且当日盘中剧烈变化不刷新）；② 批量多线程场景首次计算会串行持锁。
- 修复建议：可接受（日频 regime 语义合理），但建议标注"日频缓存非 24h TTL"并在批量场景把 `compute_fn` 移出锁（用 double-checked locking）。

**M4 — `run_fsm_analysis` 用与 `MarketSignalContext.from_dict` 不兼容的 dict 调用 `make_decision`（静默错判陷阱，死路径）**
- 证据：`fsm_analysis_engine.py:85-93` `data_pack={"stock": df, "bench": None, "sector": None, "etf": None}` → `make_decision(data_pack)` → `MarketSignalContext.from_dict(data_pack)`（`fsm.py:562`）→ 所有字段取默认值（regime=NORMAL, price=0, alpha=0, ma_status=None…）→ 恒 `STAY_CURRENT_STATE/HOLD`。
- 后果：**无任何调用方**（`grep -rn "run_fsm_analysis" src/uniquant/` 仅命中定义），故当前不造成生产错误；但一旦被调用即静默产出"持币观望"错判，且 `FsmAnalysisEngine`/`factory.fsm` 均未进 N2N `_run_engines`。
- 修复建议：删除 `run_fsm_analysis` 死方法（或改为构造合法 `MarketSignalContext`），并在 N2N `_run_engines` 明确 FSM 由 `_make_decision` 承担。

**M5 — DecisionBrain "HOLD" 不是仲裁否决 → CZSC/Wyckoff BUY 候选仍可执行**
- 证据：`arbitrator.py` Priority-1 只处理 `FORCE_WAIT/CIRCUIT_BREAK/FORCE_EXIT/BUY`；`action=="HOLD"` 落到 Priority-3（candidates）；`fsm.py:399-407` 买入阻断返回 `"HOLD"`（含 `LIMIT_UP/STOP_LOSS_TOO_WIDE/ALPHA_TOO_WEAK`）。
- 后果：当 DecisionBrain 因 `LIMIT_UP`/`STOP_LOSS_TOO_WIDE` 判 `HOLD` 时，若存在 Wyckoff/CZSC BUY 候选，仲裁器仍可能产出 BUY（绕过 FSM 的买入阻断）。
- 修复建议：在 `arbitrate_candidates` Priority-1 增加 `if decision_output.action=="HOLD"` 且携带 `buy_blockers` 时否决候选 BUY；或让 FSM 阻断以 `FORCE_WAIT`（而非 `HOLD`）返回。

### LOW

- **L1**：`FactorRegistry._ensure_loaded`（`registry.py:56-61`）为空桩——注释称"Lazy-load custom factors on first query"但函数体只置 `_loaded=True`，不导入任何因子。因子实际靠 `factors/__init__.py:11` `from . import custom_factors` 的**导入副作用**注册。若直接 `from uniquant.brain.factors.registry import FactorRegistry` 而不经包 `__init__`，`get_all()` 返回空。**建议**：删除误导桩或让 `_ensure_loaded` 真正 `import custom_factors/fundamental_factors/chip_factors`。
- **L2**：FactorRegistry 访问门控默认 `WARN`（`registry.py:47`），生产配置无 `set_mode(BLOCK)` → `check_access` 只记日志**永不阻断**未注册因子（`registry.py:175-184`）。**建议**：默认 `WARN` 保留，但文档标注 BLOCK 为 opt-in；或对核心因子访问强制 BLOCK。
- **L3**：LPPL 双路径 R² 口径不一致（`engine.py:527-536` 注释：`detect_bubble` 3-param variable projection vs `scan_all_windows` 7-param）→ 不可直接比较。**与既有报告 L1 一致**。
- **L4**：FSM 状态文件 `_STATE_FILE_NAME="fsm_state.json"` 硬编码（`fsm.py:189`），多实例共享同一文件。**与既有报告 L2 一致**。
- **L5**：Wyckoff `structural_adjust_enabled` 默认 False（`engine.py:179`，P0-5 有意设计，保留 `structural_score` 叙事回填）。**与既有报告 L3 一致**（确认是设计意图，无需修）。
- **L6**：`_market_cache.set_ntf`/`get_ntf` 与 regime 共用同一 `_date` 字段（`market_cache.py:88-92`）——轻微耦合，非正确性 bug（两者同日刷新语义一致）。

---

## ⑤ 交叉复核矩阵（vs 既有 Claude 报告 `docs/analysis/n2n/02_analysis_engines_n2n.md`，基线 434aab1）

| 既有结论 | 我方独立复核 | 判定 | 说明 |
|---|---|---|---|
| §0.2 双栈边界隔离（生产 `calculator.py` / 研究 `fitting_optimizer.py`） | 确认 `lppl_analysis_engine.py:26-37` 经 `LPPLEngine`（`brain/lppl/engine.py:482`）走 `calculator.fit()`；`fitting_optimizer.py` 为离线研究 | **一致** | 生产/研究双栈属实 |
| §1.1 LPPL 参数边界 m∈(0.1,0.9)/w∈(6,13)/\|c\|≥0.01/0.1 | `calculator.py:97-103` 配置读取 | **一致** | 边界来源=Sornette 经验约束 |
| §2.1 LPPL 生产栈 L-BFGS-B + DE 降级 + 3-param variable projection | `engine.py:527-536` `calculator.fit()` | **一致** | |
| §2.3 FSM Veto-Scoring 架构 | `fsm.py:287-408` Veto→熔断→得分→卖出优先→状态转换→买入阻断 | **一致** | 机制描述准确 |
| §2.4 Wyckoff Step 0-5 流水线 | `engine.py:254-408`（BC/TR→Phase→Effort→PhaseC→反事实→RR→计划） | **一致** | |
| §7.4 **L1** LPPL 双路径 R² 口径不一致（LOW） | 我方 **L3** | **一致** | 双方均确认（`engine.py:527-536`） |
| §7.4 **L2** FSM 状态文件硬编码（LOW） | 我方 **L4** | **一致** | 双方均确认（`fsm.py:189`） |
| §7.4 **L3** Wyckoff structural_adjust 默认关（LOW） | 我方 **L5** | **一致** | 确认有意设计 |
| §7.1-7.3 CRITICAL/HIGH/MEDIUM **= 无** | 我方 **C1（CRITICAL）/H1/H2（HIGH）/M1-M5（MEDIUM）** | **分歧（遗漏）** | ⚠️ 既有报告给"零中高缺陷+全优秀"，但**漏了 C1（pre_close 死代码）/H1（LPPL 双路径矛盾）/H2（无 sizer/risk）**——均为我独立取证 |
| §9.1 全部 7 引擎"✅ 优秀" | 我方：仅 LPPL/CZSC/Wyckoff/FSM 机制被既有报告正文审查；**NTF 写"待详细审查"**；Factors/Regime/Alpha/Indicators/Screener 无正文却盖"优秀" | **分歧（夸大覆盖）** | 认同既有独立第三方评审的 H1——"未审查却下优秀" |
| §9.1 含 `brain/factors/`（walk_forward_pipeline/forensics） | 既有报告未审 OOS/walk-forward/PBO；我方确认 `factors/` 有 `walk_forward_pipeline.py`(344 行)、`forensics/`（ohlson/winberry/z_cnmm）但**未纳入本报告正文** | **分歧（缺项）** | 认同既有第三方评审的 H2（回避过拟合门禁审查） |
| 独立评审 M3（"LPPL 已被 MC 证伪 93% GBM"零方法论） | 我方在 `adapters.py:71-75` 见"已被 Monte-Carlo 证伪（93% GBM 噪声即可拟合 R²>0.3）"注释，但**未见 MC 实现/零假设**；`brain/lppl/` 无 MC 模块 | **分歧（方法缺）** | 该定论无实现锚点，需标注"对照 forensics/" |
| 独立评审 M2（R² 在 log 还是价格尺度） | `engine.py:560` `log_train=np.log(prices)` → R² 在**对数价格**尺度算，但既有报告 §6.1 给 `r_squared:0.85` 未标注尺度 | **分歧（尺度未标）** | 需在报告标注 log 尺度 |

**交叉复核结论**：既有报告对 4 个子引擎的机制描述**真实可复现**（与源码吻合），但其**结论层（"零中高缺陷+全优秀"）与我方独立发现严重不符**——C1/H1/H2 均为既有报告遗漏的真实缺陷。既有报告的 3 个 LOW 全部确认；既有报告自带的"未审查却下优秀/回避过拟合"批评（由独立第三方评审提出）我**完全认同**。

---

## ⑥ 结论与建议

1. **健康度 B-（条件通过）**：`brain/` 模块契约清晰、引擎输出强类型化、异常路径 Fail-Closed 达标（Rule 4）。但存在 **1 CRITICAL + 2 HIGH**，均集中在**服务层接线**（`analysis_service_v2.py`/`engine_factory.py`/`pack_writer.py`）与 **DecisionBrain 消费侧**（`fsm.py`），而非引擎数学本身。
2. **C1（CRITICAL）必须最先修**：`pre_close` 不传播导致实盘 FSM 熔断/涨跌停保护全失效，且与回测路径（`unified_models.py:186` 会算 `pre_close`）分裂。这是 N2N 最该抓的"回测-实盘不一致"。
3. **H1/H2 必须在本轮修**：LPPL 遥测降级只完成一半（DecisionBrain 仍强平）；生产 `DecisionBrain` 无风险引擎/仓位计算器。二者都让"决策路径"与"信号路径"脱节。
4. **M1-M5 建议下轮处理**：字段传播（czsc_bottom）、前视口径统一、Regime 缓存语义、死路径清理、HOLD 否决。
5. **对既有报告的处置**：其机制描述保留（可复现），但其"零中高缺陷/全优秀"结论**应标注为存疑并附我方 C1/H1/H2**；且既有报告自身被第三方评审指出的"只审 4/10 却评全部优秀 / 回避 OOS"两项**成立**，应作为既有报告修订项。

**证据完整性声明**：本报告所有 `file:line` 引用均在本工作树（HEAD `b1d2415`）实测核对；未引用任何未被源码支持的数值；未查看/引用任何既有报告结论作为我方发现依据（我方发现均源自独立读码取证）。
