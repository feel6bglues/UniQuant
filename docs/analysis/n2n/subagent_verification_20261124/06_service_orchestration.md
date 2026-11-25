# 服务编排模块 N2N 独立复核报告（Subagent 验证 2026-11-24）

> **报告类型**：独立第三方子代理复核（先独立分析、后交叉比对）
> **分析基线**：git HEAD `b1d2415`（模块现状）
> **既有报告基线**：`docs/analysis/n2n/06_service_orchestration_n2n.md`（Claude，commit `434aab1`）
> **分析范围**：`src/uniquant/services/`（28 文件，8,554 行）
> **纪律**：Rule 3（不虚构）、Rule 4（禁止伪造/缺失必须显式失败）、Rule 8（外科手术式）、Rule 10（文档不漂移）

---

## ① 执行摘要

服务编排模块整体健康度评级：**B（基本可信，存在 3 项 HIGH 级结构性缺口）**。

- **无 CRITICAL**：未发现数据伪造、崩溃级、越权类缺陷。
- **3 × HIGH**：H1 `ServiceContainer.get()` 懒加载无锁（通用入口，并发首取可产生重复/覆盖实例）；H2 6 个流水线生命周期事件 + EngineCompleted 在默认容器装配下**完全不生效**（容器从不传 `event_bus`，且全仓库**零订阅者**）；H3 `run_batch` 的 `seed` 形参是死参数（接受但不传播，破坏批次可复现，直接违背 AGENTS.md 第 24 轮「seed 可复现」纪律）。
- **8 × MEDIUM**：EngineCompleted 恒报 "OK"（引擎失败仍报成功）、`fetch_research_pack` 吞异常掩真因、`initialize()` 无原子回滚（`_initialized` 仅末尾置位）、无 shutdown 生命周期、HealthService 绕过容器、FSM 引擎注册但从不被编排、配置校验仅告警不 Fail-Fast（注：此非 Rule 4 违规，是 Fail-Fast 关切）、「13 服务注册」计数不实（实为 12 个 `register_factory`）。
- **7 × LOW**：空决策 `{}` 被当作成功、模块 docstring「零循环依赖」与 bind_orchestrator 2-环矛盾、`set_ntf` 日期逻辑不一致、`brain` 绕过 `_lazy_init`、benchmark 代码不统一、bootstrap 测试门槛(0.5s)与 docstring(<50ms)不符、既有报告事件顺序记载错误。

**对既有报告的核心分歧**：
1. 既有报告把「6 生命周期事件」评为 ✅ 优秀（§9.1），但事件在默认装配下**从不发布且无消费者**——这是既有报告的最大盲区。
2. 既有报告「13 个服务注册」（§8.1#1）计数不实——实为 12 个 `register_factory` 调用；「factor_gate」是配置副作用（`FactorRegistry.set_mode`），并非注册的服务。
3. 既有报告把 `ServiceContainer.get()` 无锁标为 MEDIUM（§7.3-M1），独立评审已升级为 HIGH（H1），本复核确认**应为 HIGH**。
4. 既有报告 §3.2 事件顺序「RunStarted→DataLoaded→[EngineCompleted×7]→…」有误——`EngineCompleted×7` 在 `run_ticker_analysis` 内发布，先于 `DataLoaded`（其在 `run_ticker_analysis` 返回后才发布）。

> 证据均来自当前工作树（`b1d2415`）实测读码；所有引用精确到 `file:line`。测试计数未经本次运行，故本报告**不**声称任何测试通过（Rule 3）。

---

## ② 五问逐节点答案（N2N）

### 节点 N1：`ServiceContainer.initialize()` / `get()`（DI 容器）

- **Q1 定义**：`ServiceContainer`（`service_container.py:32`）单例双检锁（`:42-48`）；`initialize()`（`:77-215`）注册 **12 个**工厂（见 ④-M8 计数异议），`_initialized` 仅在第 214 行末尾置位。`get(name)`（`:60-63`）在工厂未实例化时懒调用 `self._factories[name](self)`。
- **Q2 映射**：`initialize()` 分 7 步——(1) 核心数据层 storage/calendar/cache/data_service/time_provider（`:98-105`）；(2) engine_factory/market_cache（`:122-123`）；(3) analysis_service（`:139`，含 `bind_orchestrator` `:135-136`）；(4) backtest_engine/signal_collector（`:152-153`）；(5) arbitrator（`:170`）；(6) factor_gate 副作用（`:172-185`）；(7) research_pipeline（`:212`）。
- **Q3 传播**：`bind_orchestrator(asvc)` 在 AnalysisService 构造后回绑，把 engine_factory 的 orchestrator 从 `data_service` 升级为 `analysis_service`（`:135-136` + `engine_factory.py:23-34`），并 `_engines.clear()` 强制重懒加载。**注意**：这构成 AnalysisService ↔ AnalysisEngineFactory 的 **2-环**，靠 `bind_orchestrator` 后绑定破解——「零循环依赖」docstring 声明（`service_container.py:15`）不精确（见 ④-L2）。
- **Q4 变异**：`get()` 懒加载**无锁**（`:60-63`），与 `instance()` 双检锁（`:42-48`）不一致——并发首取可重复/覆盖实例（见 ④-H1）。`initialize()` 无原子回滚（见 ④-M3）。配置校验仅告警（见 ④-M7）。
- **Q5 治理**：三类注册表 `_services`/`_factories`/`_registrations`；`has/reset/clear`（`:65-75`）。**无 shutdown 生命周期**（见 ④-M4）。

### 节点 N2：`AnalysisService.run_ticker_analysis()`（纯编排器）

- **Q1 定义**：`run_ticker_analysis(ticker, trace_id=None) -> TickerAnalysisResult`（`analysis_service_v2.py:263-310`）。**注意**：实际签名**没有 `analysis_df` 形参**——任务书描述的路径 `run_ticker_analysis(ticker, analysis_df)` 与代码不符；`TickerAnalysisResult`（`:59-68`）含 symbol/data_pack/decision/signals/success/error/trace_id。
- **Q2 映射**：三步——(1) `_prepare_data(ticker)`（`:314-347`，委托 DataService）；(2) `_run_engines(ticker, data_pack)`（`:351-396`，跑 regime/lppl/ntf/czsc/wyckoff/alpha/derived 共 **7 步**）；(3) `_make_decision(ticker, data_pack)`（`:610-629`，`self.brain.make_decision(ctx)`）。
- **Q3 传播**：数据不足/引擎失败/决策失败均返回 `success=False`（`:279-301`）不抛异常——**fail-closed 但带显式 reason**，符合 Rule 4 精神。引擎失败经各 `_run_*` 内部 catch 写 `ENGINE_FAILED` 标记（`:425-429` 等）后**不向上抛**，`_run_engines` 仍返回 True——降级而非中止（见 ④-M1 事件谎报问题）。
- **Q4 变异**：`_make_decision` 空 dict `{}` 被当作成功（`:626` 返回 `{}`，`:296-301` 判 `is None` 才失败）——空决策 `success=True`（见 ④-L1）。`raw["decision_output"]=...`（`:624`）就地改写 brain 返回 dict（Rule 5 张力，但 `raw` 通常为新构造，影响有限）。
- **Q5 治理**：`_attach_trace_id`（`:254-261`）注入 trace_id；`perf_section`（`:355` 等）按引擎计时段；`_mark_engine_status`（`:238-252`）落 engine_status/engine_errors。

### 节点 N3：`AnalysisEngineFactory`（引擎工厂，9 引擎注册）

- **Q1 定义**：`AnalysisEngineFactory`（`engine_factory.py:17-21`）持 `_engines` dict + `_lock = threading.RLock()`；**无 `create_all()`**——任务书路径 `create_all() -> Dict[engine_name, EngineOutput]` **不存在**，实际是 9 个 `@property` 懒加载 + AnalysisService 的 `_run_engines` 逐一调用。
- **Q2 映射**：9 个属性 `fsm/czsc/lppl/regime/ntf/macro/report/brain/wyckoff`（`:53-99`）。`fsm`（`:54-55`）与 `macro`（`:73-75`）、`report`（`:77-79`）**不在 `_run_engines` 编排内**（见 ④-M6）。`brain` 特殊导入（`:81-95`）。
- **Q3 传播**：`_lazy_init`（`:36-51`）双检锁 + `importlib` 动态导入；失败抛 `RuntimeError`（`:46-50`）不静默。
- **Q4 变异**：`_lazy_init` 与 `brain` 均用 RLock 双检——**线程安全成立**（与容器 `get()` 形成对比）。`bind_orchestrator` 清空 `_engines`（`:34`）强制重载。
- **Q5 治理**：引擎名单在 `:13-14` 注释声明需与 `docs/index.md §Runtime Modules` 同步（Rule 10 张力，属文档维护项）。

### 节点 N4：`DecisionBrain.make_decision()`（跨模块契约，brain 层）

- **Q1 定义**：`make_decision(data_packet: Union[dict, MarketSignalContext]) -> Dict[str, Any]`（`brain/fsm/fsm.py:547-549`）。
- **Q2 映射**：AnalysisService 传 `MarketSignalContext.from_dict(...)`（`analysis_service_v2.py:619-621`）；brain 内 `isinstance(data_packet, MarketSignalContext)` 分支复用（`fsm.py:559-562`）。`MarketSignalContext.from_dict`（`interfaces.py:91-120`）做 regime/ntf 枚举安全回退。
- **Q3 传播**：跨股票 symbol 变化时重置 FSM 状态（`fsm.py:564-568`）——多标的连续分析的关键状态隔离。veto 分支提前返回（`:573-575`）。
- **Q4 变异**：输入为 dict 时内部 `from_dict` 转换（`fsm.py:562`），兼容旧路径。
- **Q5 治理**：无事件发布（brain 层纯函数式决策）。

### 节点 N5：`TradingSignalCollector.collect()`（signal 层契约）

- **Q1 定义**：`collect(data_pack, timestamp=None, bar_date=None, default_shares=100) -> List[TradingSignal]`（`signal/adapters.py:577-583`）。
- **Q2 映射**：从 data_pack 提取 lppl/czsc 等子结果经 registry adapter 适配（`:600-611`）；流水线传入 `bar_date`（最近 K 线日）优先于 `timestamp`（`research_pipeline.py:345-356`）。
- **Q3 传播**：Pipeline 在 `run_ticker_analysis` 后显式调用 collect（`research_pipeline.py:341-356`），并把 `DecisionProduced` 事件发布在其后（`:358-364`）。
- **Q4 变异**：空 data_pack 返回空列表；无 BUY/SELL 时信号为空，仍进入回测（引擎对空信号安全，见 unified_engine `run` 空 signal_map 处理）。
- **Q5 治理**：`_merge_decision_for_collection`（`research_pipeline.py:568-606`）把 decision 键（action/shares/confidence/reason/price/final_score/score）安全合并进 collector_pack。

### 节点 N6：`SignalArbitrator`（特性开关控制）

- **Q1 定义**：容器工厂 `_make_arbitrator`（`service_container.py:156-170`）读取 `feature_flags.signal_arbitration`，开启才实例化 `SignalArbitrator`，否则返回 `None`。
- **Q2 映射**：Pipeline 第 3b 步 `if self._arbitrator is not None:`（`research_pipeline.py:368-385`）——仲裁仅在开关开启且服务存在时执行。
- **Q3 传播**：`signal_arbitration` 配置在 `initialize()` 时一次性读取并决定服务是否注册（`service_container.py:161`）；`factor_gate` 同理在 `:177` 决定 `FactorRegistry.set_mode`（`brain/factors/registry.py`）。
- **Q4 变异**：配置加载失败→`logger.debug`+返回 None（`:166-168`）——**注意这是治理开关失效被降为 debug 静默**（与「配置失败必须可见」存在张力，见 ④-M7）；仲裁器禁用时信号原样通过（`:368` 跳过）。
- **Q5 治理**：无。

### 节点 N7：`UnifiedBacktestEngine.run()`（hands 层契约）

- **Q1 定义**：`run(df, signals, symbol="", name=None, benchmark_returns=None) -> BacktestResult`（`hands/backtest/unified_engine.py:149-156`）。
- **Q2 映射**：Pipeline 第 4 步以 `df=stock_df, signals=signals, symbol=symbol, name=name` 调用（`research_pipeline.py:410-416`）；空信号→空 trades（unified_engine `signal_map` 空）。
- **Q3 传播**：`BacktestCompleted` 事件在回测后发布（`research_pipeline.py:418-424`）；结果经 `_persist_result`（`:443-444`）写 `ResultStore`。
- **Q4 变异**：K 线为空在回测前拦截（`research_pipeline.py:393-408`，返回 `success=False`「K线数据为空」）。
- **Q5 治理**：`_compute_backtest_sharpe/mdd`（`:610-627`）仅持久化用；`_persist_result` 捕获 OSError/KeyError/TypeError 告警（`:649-650`）。

---

## ③ 端到端路径追踪（≥3 条，含异常）

### 路径 P1（正常）：单标的完整流水线

```
UnifiedResearchPipeline.run("000001.SZ")            research_pipeline.py:273
 ├─ bus.publish(RunStarted(symbol, trace_id))       :306
 ├─ analysis = self._analysis.run_ticker_analysis(...) :310-312
 │    ├─ _prepare_data → fetch_research_pack/fetch_for_brain :314-347
 │    ├─ _run_engines(regime→lppl→ntf→czsc→wyckoff→alpha→derived) :351-396
 │    │    └─ EngineCompleted×7 (status 恒 "OK")   :358,363,368,373,378,383,388
 │    └─ _make_decision → DecisionBrain.make_decision(ctx) :610-629
 ├─ bus.publish(DataLoaded)                         :320
 ├─ collector.collect(collector_pack, bar_date)      :341-356
 ├─ bus.publish(DecisionProduced)                    :360-364
 ├─ [optional] arbitrator.arbitrate_candidates(...)  :368-385
 ├─ bus.publish(SignalsCollected)                    :389
 ├─ engine.run(df, signals, symbol, name)            :410-416
 ├─ bus.publish(BacktestCompleted)                   :418-424
 ├─ _persist_result(result)                          :443-444
 ├─ bus.publish(RunCompleted(success=True))          :446-453
 └─ return PipelineResult                            :455
```
**证据链完整性**：节点全部连通，跨模块契约（MarketSignalContext/TradingSignal/BacktestResult）在 `interfaces.py`/`adapters.py`/`unified_engine.py` 均有定义。**但**：默认容器下 `self._event_bus is None`，上述全部 `bus.publish` 都不执行（见 ④-H2）。

### 路径 P2（异常-引擎失败降级）：单引擎失败不中止整链

```
_run_engines → _run_regime(...)                     analysis_service_v2.py:401-429
 └─ RegimeDetector 读取 HS300 指数数据
      ├─ df None/empty → ("UNKNOWN", {})             :411-412
      └─ 异常 → RegimeOutput(regime="UNKNOWN") + ENGINE_FAILED :425-429
 ├─ 后续引擎照常执行（lppl/ntf/czsc/wyckoff/alpha/derived 各自独立 try/catch） :360-388
 └─ _run_engines 返回 True                          :396
```
**结论**：单引擎失败被**隔离**（per-engine `ENGINE_FAILED` 标记），不阻断其余引擎与决策——**降级设计正确**。**但** `EngineCompleted(..., "OK")` 恒报 OK（`:358` 等），失败被事件谎报为成功（见 ④-M1）。

### 路径 P3（异常-数据不足 fail-closed）：缺失输入显式失败

```
run_ticker_analysis → _prepare_data                 analysis_service_v2.py:278-285, 314-347
 ├─ stock_df None / empty → logger.error + return None :338-343
 └─ return None → TickerAnalysisResult(success=False, error="数据不足") :279-285
Pipeline.run → analysis.success False → DataLoaded(success=False) → RunCompleted(success=False) :322-337
```
**结论**：缺失输入 → `success=False` + 显式 error——**Rule 4 合规（fail-closed，无 linspace/伪造兜底）**。符合 AGENTS.md 第 25 轮「100% 杜绝伪造假数据漏洞」口径。

### 路径 P4（异常-未初始化/缓存失效）：容器懒加载与缓存跨日失效

```
ServiceContainer.get("research_pipeline")           service_container.py:60-63
 └─ _make_research_pipeline(container)               :188-212
      ├─ analysis_service = c.get("analysis_service") :203（触发整链懒装配）
      ├─ arbitrator = c.get("arbitrator")            :206（受 signal_arbitration 开关）
      └─ UnifiedResearchPipeline(...)                :202-210
MarketLevelCache.get_or_compute_regime               market_cache.py:61-80
 └─ self._date == self._today() 才命中；跨日 → 重算（TOCTOU-safe） :72-78
```
**结论**：容器懒装配链路单向；缓存跨日自动失效重算——**设计正确**。**但** `get()` 无锁（见 ④-H1），且容器不传 `event_bus`（见 ④-H2）。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### CRITICAL
无。

### HIGH

#### H1 — `ServiceContainer.get()` 懒加载无锁（通用入口并发首取）
- **证据**：`service_container.py:60-63` 的 `if name in self._factories and name not in self._services: self._services[name] = self._factories[name](self)` 无任何锁；对比 `instance()` 双检锁（`:42-48`）与 `engine_factory._lazy_init` RLock（`engine_factory.py:36-51`）。
- **影响**：`get()` 是所有服务（含有状态的回测引擎/信号收集器/DataService）的唯一取用入口。多线程首次并发取用同一未实例化服务 → 工厂被多次调用、多个实例创建、后写覆盖先写，**已持有旧实例的调用方与后续取用方拿到不同对象**——对有状态组件是数据正确性问题，不止「破坏单例语义」。
- **当前是否触发**：`run_batch`（`research_pipeline.py:457-552`）在 `ThreadPoolExecutor` 中只调 `self.run()`，不调 `container.get()`，且流水线对象在池外已装配——故**当前单入口下是潜在缺陷（latent）而非已触发**。但这是通用公共入口，任何未来并行入口都会激活。
- **修复建议**：改为双检锁（与 `instance()` 一致）：
  ```python
  def get(self, name: str) -> Any:
      if name in self._factories and name not in self._services:
          with self._lock:
              if name not in self._services:
                  self._services[name] = self._factories[name](self)
      return self._services.get(name)
  ```
- **定级说明**：既有报告标 MEDIUM（M1），本复核与报告内独立评审一致，**升级为 HIGH**（通用入口 + 有状态组件正确性）。

#### H2 — 6 生命周期事件 + EngineCompleted 在默认容器装配下完全不生效
- **证据**：
  - 容器 `_make_analysis_svc`（`service_container.py:126-137`）**不传 `event_bus`** → `AnalysisService._event_bus=None`（`analysis_service_v2.py:100`）→ `_run_engines` 里 `if bus is not None:` 全为假（`:357` 等）→ **EngineCompleted 从不发布**。
  - 容器 `_make_research_pipeline`（`service_container.py:188-212`）**不传 `event_bus`** → `UnifiedResearchPipeline._event_bus=None`（`research_pipeline.py:147`）→ 6 事件 `if bus is not None:` 全为假（`:304,314,334,358,387,405,418,446`）→ **6 事件从不发布**。
  - 全仓库 `src/` **零处 `.subscribe(` 调用**（仅 `event_bus.py:19` 定义）；`EventBus.publish` 遍历空订阅者（`:31`）空操作。
  - `FeatureFlags.event_bus/async_event_bus`（`config_models.py:14,16,28,30`）在 `services/` 内**无任何消费**（grep 仅 `config_loader/schema` 读取）。
- **影响**：可观测性/生命周期骨架（RunStarted/DataLoaded/DecisionProduced/SignalsCollected/BacktestCompleted/RunCompleted + EngineCompleted）在**生产装配下是死代码**——任何依赖这些事件的消费者（监控、审计、持久化钩子）收不到任何信号。既有报告 §9.1 却评「生命周期管理 ✅ 优秀」，**严重高估**。
- **修复建议**：(1) 容器内实例化一个 `EventBus`（或按 `async_event_bus` 选 `AsyncEventBus`）并注入 analysis_service/research_pipeline；(2) 注册至少一个消费者（如指标采集/审计持久化）使事件真正生效；(3) 让 `event_bus` 特性开关真正驱动装配（当前开关是死配置）。

#### H3 — `run_batch` 的 `seed` 形参是死参数（破坏批次可复现）
- **证据**：`run_batch(..., seed: Optional[int] = None, ...)`（`research_pipeline.py:462`）声明了 `seed`，但函数体**从不引用**（`grep` 全文仅在签名出现）；`_run_single` 调用 `self.run(..., seed=None, ...)`（`:514`）**硬编码 seed=None**；`run()` 内 `if seed is not None: np.random.seed(seed)`（`:293-295`）被跳过。
- **影响**：`run_batch(seed=42)` 期望可复现，实际每次随机——**直接违背 AGENTS.md 第 24 轮「seed=42 可复现」验收纪律**；任何依赖随机性的回测/抽样在批量下不可复现。
- **修复建议**：把 `seed` 传入 `_run_single` 再传 `self.run(seed=seed)`；或若批次刻意不用 seed，删除该形参并加注释（避免死接口误导）。

### MEDIUM

#### M1 — `EngineCompleted` 恒报 `status="OK"`，引擎失败仍报成功
- **证据**：`_run_engines` 内 `bus.publish(EngineCompleted("regime", ticker, "OK"))`（`analysis_service_v2.py:358`，lppl/ntf/czsc/wyckoff/alpha/derived 同理 `:363,368,373,378,383,388`）——但各 `_run_*` 在内部 catch 异常并写 `ENGINE_FAILED`（如 `:425-429`）**不向上抛**，`_run_engines` 无感知，故 `publish` 恒以 "OK" 触发。
- **影响**：事件总线把失败谎报为成功；任何按 `EngineCompleted.status` 做健康判断的消费者会被误导。
- **修复建议**：各 `_run_*` 返回实际状态（或让 `_run_engines` 在引擎失败时发布 `EngineCompleted(..., "FAILED")`），使事件与 `engine_status` 标记一致。

#### M2 — `fetch_research_pack` 吞掉全部异常，掩真因
- **证据**：`fetch_research_pack`（`data_service.py:468-484`）`except Exception: logger.exception(...); return ResearchDataPack(symbol=symbol)`（`:472-474`）——真实错误被吞，返回空 pack；下游 `_prepare_data` 只见空 stock_df，报泛化「数据不足」（`analysis_service_v2.py:333-343`）。
- **影响**：真实失败原因（如 DataStorageError/网络）被降级为「数据不足」，违背「Never silently swallow errors」（harness AGENTS.md）。
- **修复建议**：区分「确无数据」与「取数异常」——异常时记录并向上传播（或至少把原因写入返回的 pack metadata），而非一律返回空 pack。

#### M3 — `initialize()` 无原子回滚（`_initialized` 仅末尾置位）
- **证据**：`_initialized = True` 仅 `service_container.py:214`（末行）；`initialize()` 主体（`:87-212`）无 try/except/回滚。`get_config()`（`:87`）/`ConfigValidator.validate_all()`（`:89`）/任一 `register_factory` 抛错 → 已注册的工厂残留 `_factories`，`_initialized` 仍 `False`，下次 `initialize()` 重跑并覆盖（`register_factory` 对重名只 `logger.warning`，`:55-56`）。
- **影响**：部分初始化失败后容器处于**半装配**状态，重试可能产生不一致/重复注册；无失败隔离。
- **修复建议**：`initialize()` 包 try/except，失败时回滚 `_factories/_services/_registrations` 并置 `_initialized=False`（或记录明确「初始化失败」状态）。

#### M4 — 无 shutdown/销毁生命周期
- **证据**：`src/uniquant/services/` 全目录**无** `def shutdown/close/dispose/destroy`（grep 仅 `shared/event_bus.py:71 AsyncEventBus.shutdown`）。容器有 `initialize()`/`reset()`/`clear()`（`:77,68,72`），无对应销毁。
- **影响**：持有连接（TdxClient）/文件锁（StorageManager FileLock）的服务无优雅关闭路径，重启/热部署存在资源泄漏风险。
- **修复建议**：为容器加 `shutdown()`，按逆序销毁持有资源服务；或在文档明确服务无需手动释放。

#### M5 — `HealthService` 绕过 DI 容器（第二套装配路径）
- **证据**：`HealthService.__init__`（`health_service.py:37-46`）直接 `DataService()`、`AnalysisService(data_service=self.data_service)`、`DecisionBrain(evt_risk=..., sizer=...)`——**不经容器**，无 `engine_factory`（无 `bind_orchestrator`）、无 `attach_market_cache`、无 `event_bus`。
- **影响**：容器装配与 HealthService 装配可能**分叉**（特性开关/缓存/事件在 HealthService 路径全部缺失），健康检查结果不能代表真实生产装配。
- **修复建议**：HealthService 改为经 `ServiceContainer.get(...)` 取用服务，或至少显式注入同一组依赖，消除双路径。

#### M6 — FSM 引擎注册但从不被编排（死注册）
- **证据**：`engine_factory.py:54-55` 注册 `fsm` 属性，但 `AnalysisService._run_engines`（`analysis_service_v2.py:351-396`）**只跑 regime/lppl/ntf/czsc/wyckoff/alpha/derived，无 `_run_fsm`**；`fsm_analysis_engine.py` 的 `run_fsm_analysis` 无任何调用方。
- **影响**：FSM 引擎是注册表里的**死节点**；若其承载决策逻辑则未生效。需确认是否为刻意退役（若是，应从工厂移除并同步 `docs/index.md`，Rule 10）。
- **修复建议**：要么将 `fsm` 接入 `_run_engines`，要么从工厂/文档移除该注册（避免「9 引擎注册 vs 7 步编排」的契约漂移）。

#### M7 — 配置校验失败仅告警不 Fail-Fast
- **证据**：`service_container.py:88-95` `if validation_errors: logger.warning(...)`，不阻断启动。
- **影响**：配置错误（含特性开关未生效、参数错误）运行时才暴露，违背 Fail-Fast 精神。
- **定级说明**：既有报告标 MEDIUM 并援引「Rule 4 冲突」（`06_service_orchestration_n2n.md:762`）——**本复核认为该 Rule 4 援引不准确**：CLAUDE.md Rule 4（`CLAUDE.md:39-44`）针对的是**数据门禁/裁决代码**（"No fabrication of inputs to satisfy a gate"），**不是配置校验**。配置校验属 Fail-Fast 关切，非 Rule 4 范畴。**保留 MEDIUM，但纠正引用**。
- **修复建议**：对致命配置错误改为 `logger.error` + 可配置地 `raise`；或至少把告警提升为错误级以进入监控。

#### M8 — 「13 服务注册」计数不实（实为 12）
- **证据**：`service_container.py` 实际 `register_factory(` 调用点为 **12** 个（`:98,99,100,101,105,122,123,139,152,153,170,212`）：storage/calendar/cache/data_service/time_provider/engine_factory/market_cache/analysis_service/backtest_engine/signal_collector/arbitrator/research_pipeline。既有报告 §8.1#1（`06_service_orchestration_n2n.md:805`）与独立评审（`:862`）均称「13 个」——**把 `factor_gate`（`service_container.py:172-185`，实为 `FactorRegistry.set_mode` 配置副作用，非 `register_factory`）误计为第 13 个服务**。
- **影响**：文档/契约计数错误（Rule 10 文档漂移）；若下游按「13 服务」断言将失配。
- **修复建议**：改为「12 个注册服务 + 1 项因子准入配置副作用」；修正既有报告与 `AGENTS.md`/`docs/index.md` 相应计数。

### LOW

#### L1 — 空决策 `{}` 被当作成功
- **证据**：`_make_decision`（`analysis_service_v2.py:610-629`）`if raw:` 包裹 `return raw`，但 `:626` 无条件 `return raw`；当 `raw == {}` 时 `_make_decision` 返回 `{}`，`run_ticker_analysis:296-301` 判 `if decision is None:` 为假 → `success=True, decision={}`。
- **影响**：brain 返回空决策被当作成功，下游信号收集拿到空 decision，可能静默产生零信号成功结果。
- **修复建议**：`_make_decision` 对空 `raw` 显式返回 `None`；或 `run_ticker_analysis` 对空决策判失败。

#### L2 — 模块 docstring「零循环依赖」与 bind_orchestrator 2-环矛盾
- **证据**：`service_container.py:15` 声称「零循环依赖（DAG）」，但 `analysis_service` 工厂内 `engine_factory` 持 `analysis_service`（`bind_orchestrator`，`:135-136`）而 `analysis_service` 又持 `engine_factory`（`:104-106`）——构成 **2-环**，靠后绑定破解。
- **影响**：语义声明与实现不符；读者误以为无环，实际存在被延迟破解的环。
- **修复建议**：把 docstring 改为「容器注册层为 DAG；engine_factory↔analysis_service 的对象环由 bind_orchestrator 后绑定破解」。

#### L3 — `MarketLevelCache.set_ntf` 日期逻辑与 `set_regime` 不一致
- **证据**：`set_ntf`（`market_cache.py:88-93`）仅在 `self._date is None` 时设日期；`set_regime`（`:54-58`）总是设。跨日只调 `set_ntf` 时 `_date` 不更新，`get_ntf`（`:82-86`）返回 None——行为正确但逻辑不一致。
- **修复建议**：`set_ntf` 统一 `self._date = self._today()`。

#### L4 — `AnalysisEngineFactory.brain` 绕过 `_lazy_init`
- **证据**：`engine_factory.py:81-95` 直接 `from ...brain.fsm import DecisionBrain`，未走 `_lazy_init`（`:36-51`）——两套懒加载路径。
- **影响**：维护成本、失败处理不一致（brain 手动 try/except，其余走 `_lazy_init`）。
- **修复建议**：把 `brain` 纳入 `_lazy_init` 统一（或明确注释差异原因）。

#### L5 — benchmark 代码不统一（`fetch_for_brain` vs `_run_alpha`）
- **证据**：`fetch_for_brain` 用 `"sh000300"`（`data_service.py:463`）；`_run_alpha` 直读 `"000300.SH"`（`analysis_service_v2.py:542`）；且前者经 fallback 源取数、后者直读湖。
- **影响**：同一基准两种编码/两种来源，可能产生数据口径不一致。
- **修复建议**：统一基准编码与读取路径（如都走湖 `read_data("000300.SH","index")`）。

#### L6 — bootstrap 测试门槛与 docstring 目标不符
- **证据**：`bootstrap.py:6` docstring「启动耗时 < 50ms」；但测试 `test_bootstrap_instantiation_is_fast` 断言 `duration < 0.5`（`tests/services/test_bootstrap.py:37`，500ms）。AGENTS.md 第 25 轮称「实测 36~42 ms」——**门禁(0.5s)与声明目标(<50ms)差 10 倍**。
- **影响**：<50ms 目标是声明非门禁；若回归到 200ms 测试仍绿但目标失效。
- **修复建议**：把测试门槛收紧至与目标一致（如 `< 0.05`），或在 docstring 说明「目标 <50ms，门禁宽松为 <500ms」以避免误导。

#### L7 — 既有报告事件顺序记载错误（交叉复核项）
- **证据**：既有报告 §3.2（`06_service_orchestration_n2n.md:372`）载「RunStarted → DataLoaded → [EngineCompleted × 7] → DecisionProduced → …」；**实际**：`EngineCompleted×7` 在 `run_ticker_analysis` 内发布（`analysis_service_v2.py:358-388`，先于 `DataLoaded`），`DataLoaded` 在 `run_ticker_analysis` 返回后发布（`research_pipeline.py:314-320`）。
- **影响**：文档记载的事件拓扑与代码不符（Rule 10）。
- **修复建议**：改为「RunStarted → [EngineCompleted×7] → DataLoaded → DecisionProduced → SignalsCollected → BacktestCompleted → RunCompleted」。

---

## ⑤ 交叉复核矩阵（vs 既有 Claude 报告 `06_service_orchestration_n2n.md`）

| 既有报告结论 | 位置 | 本复核判定 | 双方证据/说明 |
|---|---|---|---|
| 13 个服务注册 ✅ | §8.1#1 `:805` | **分歧** | 实为 12 个 `register_factory`；`factor_gate` 是配置副作用（`service_container.py:172-185`），非服务。见 M8。 |
| DAG 严格单向无循环 ✅ | §8.1#2 `:806` | **部分一致/分歧** | 容器注册层确实无环且 `bind_orchestrator` 破解 2-环（一致）；但 docstring「零循环依赖」（`:15`）与对象图实际 2-环矛盾（不精确）。见 L2。 |
| bind_orchestrator 循环依赖解决 ✅ | §8.1#3 `:807` | **一致** | `service_container.py:135-136` + `engine_factory.py:23-34` 机制真实、正确（后绑定 + `_engines.clear()` 强制重载）。 |
| 6 生命周期事件发布顺序 ✅ | §8.1#4 `:808` | **分歧（严重）** | 顺序有误（EngineCompleted 先于 DataLoaded，见 L7）；且**事件在默认装配下从不发布、全仓库零订阅者**（见 H2）。§9.1「优秀」严重高估。 |
| 特性开关配置加载 ✅ | §8.1#5 `:809` | **部分一致** | `signal_arbitration`/`factor_gate` 加载正确（一致）；但 `event_bus`/`async_event_bus` 开关（`config_models.py:14,16,28,30`）是**死配置**，无人消费（分歧，报告未提）。 |
| 懒加载（RLock 双检）✅ 部分确认 | §8.1#6 `:810` | **一致** | 引擎工厂 RLock 双检成立（`engine_factory.py:36-51,81-95`）；`get()` 无锁成立（`service_container.py:60-63`）。 |
| get() 无锁（MEDIUM） | §7.3-M1 `:741` | **一致（升级为 HIGH）** | 与独立评审 H1 一致；因 `get()` 为全部服务唯一入口 + 有状态组件，判 HIGH（latent）。见 H1。 |
| ConfigValidator 仅告警（MEDIUM） | §7.3-M2 `:757` | **一致（纠正引用）** | 存在性一致；但「Rule 4 冲突」援引不准——Rule 4 是数据门禁条款，配置校验属 Fail-Fast。见 M7。 |
| MarketLevelCache.set_ntf 日期不一致（LOW） | §7.4-L1 `:778` | **一致** | `market_cache.py:88-93` 仅在 `_date is None` 时设日期，与 `set_regime` 不一致。见 L3。 |
| brain 绕过 _lazy_init（LOW） | §7.4-L2 `:792` | **一致** | `engine_factory.py:81-95` 两套懒加载路径。见 L4。 |
| 独立评审 H1：get() 无锁应判 HIGH | `:868-869` | **一致** | 与 H1 同判；补充「latent（当前单入口未触发）」限定。 |
| 独立评审 H2：失败传播/启动顺序 | `:871-872` | **一致（降为 MEDIUM）** | `initialize()` 无原子回滚、`_initialized` 末尾置位属实（见 M3）；特性开关失败降级为 debug 静默（见 M7）。 |
| 独立评审 M2：无 shutdown | `:876` | **一致** | `services/` 无 shutdown/close（见 M4）。 |
| **报告未覆盖**：事件总线不接线/零订阅者 | — | **新增（HIGH）** | H2：容器从不传 `event_bus` + 全仓库零 `.subscribe(`。 |
| **报告未覆盖**：run_batch seed 死参数 | — | **新增（HIGH）** | H3：`research_pipeline.py:462,514`。 |
| **报告未覆盖**：EngineCompleted 恒报 OK | — | **新增（MEDIUM）** | M1：`analysis_service_v2.py:358` 等。 |
| **报告未覆盖**：fetch_research_pack 吞异常 | — | **新增（MEDIUM）** | M2：`data_service.py:468-474`。 |
| **报告未覆盖**：HealthService 绕容器 | — | **新增（MEDIUM）** | M5：`health_service.py:37-46`。 |
| **报告未覆盖**：FSM 注册但不编排 | — | **新增（MEDIUM）** | M6：`engine_factory.py:54-55` vs `analysis_service_v2.py:351-396`。 |

**复核结论**：既有报告对「机制描述」高度准确（bind_orchestrator、MarketLevelCache TOCTOU、_lazy_init 双检、原子 checkpoint 写、特性开关降级均属实），但存在 **1 处严重高估**（6 事件「优秀」实为不生效）、**2 处计数/顺序不准**（13 服务、事件顺序）、**3 处定级偏保守**（get() 无锁 MEDIUM→HIGH；评审已纠偏）。其自我结论「部分可信」（`:857`）总体成立，本复核进一步指出其**最大盲区是事件总线在整个生产装配下是死代码**。

---

## ⑥ 结论与建议

### 健康度评级
**B（基本可信，存在 3 项 HIGH 结构性缺口）**。
- 依赖治理：✅ 容器注册层 DAG 清晰，`bind_orchestrator` 正确破解对象环（但 docstring「零循环」需修正）。
- 降级/fail-closed：✅ 单引擎失败隔离、缺失输入显式失败——符合 Rule 4。
- 线程安全：⚠️ 引擎工厂/缓存安全，**容器 `get()` 无锁（H1）**。
- 生命周期/可观测性：⚠️ **事件骨架不生效（H2）**、无 shutdown（M4）。
- 可复现性：⚠️ **批次 seed 失效（H3）**，违背第 24 轮纪律。
- 文档：⚠️ 计数（13 vs 12）、事件顺序、<50ms vs 0.5s 等漂移（M8/L2/L6/L7）。

### 修复优先级
1. **P0**：H1 `get()` 加双检锁（一行，通用正确性）。
2. **P0**：H2 容器接线真实 `EventBus` + 至少一个消费者（或移除事件骨架避免误导）。
3. **P1**：H3 修复 `run_batch` seed 传播（或删死参数）。
4. **P1**：M1 事件状态与 `engine_status` 对齐；M2 不吞异常；M3 原子初始化。
5. **P2**：M4 shutdown；M5 HealthService 走容器；M6 处理 FSM 死注册；M7 配置 Fail-Fast 定级。
6. **P2**：M8 修正「13 服务」计数；L2/L6/L7 修正文档漂移（Rule 10）。
7. **P3**：L1/L3/L4/L5 一致性清理。

### 需人工确认
- FSM 引擎是否为刻意退役（若是，从工厂/文档移除，M6）。
- `fetch_research_pack` 吞异常是刻意降级还是缺陷（M2）。
- 事件总线是否已有计划中的消费者（若在 UI/监控层，H2 定级可下调，但当前 `services/` 内确无消费者）。

---

**复核人**：独立子代理（SenseNova 6.8 Flash Lite / 商汤日日新）  
**复核日期**：2026-11-24  
**分析基线**：git `b1d2415`（当前工作树）  
**纪律合规**：Rule 3（不虚构计数，未运行测试故不声称通过）、Rule 4（fail-closed 核验）、Rule 8（未改动任何源码，纯审查）、Rule 10（本报告为新增独立复核，不改既有文档结论）  
**方法**：先独立读码（未阅既有报告）→ 后交叉比对 → 逐条标注一致/分歧。
