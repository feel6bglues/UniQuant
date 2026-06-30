# Stage 1 — services 层编排分析

> 生成日期: 2026-06-29
> 基于当前工作树 (commit c1e0eb1)
> 方法: 完整读取 service_container.py, analysis_service_v2.py, research_pipeline.py, engine_factory.py, data_service.py

---

## 1. 服务依赖拓扑图

```
ServiceContainer.initialize()
 │
 ├─ 1. ConfigValidator(config)      ← 配置校验
 ├─ 2. StorageManager()             ← 数据湖底层
 ├─ 3. TradeCalendarManager()       ← 交易日历
 ├─ 4. CacheCoordinator()           ← 缓存协调器
 ├─ 5. DataService(storage)         ← 数据门面 (依赖 2,3,4)
 │      └─ attach_market_cache(MarketLevelCache)
 ├─ 6. RealTimeProvider()           ← 时间提供器
 ├─ 7. AnalysisEngineFactory(data_svc)  ← 引擎工厂 (初始 orc=data_svc)
 ├─ 8. MarketLevelCache()           ← 市场级缓存
 ├─ 9. AnalysisService(data_svc, engine_factory, market_cache)
 │      └─ engine_factory.bind_orchestrator(analysis_svc)
 ├─10. UnifiedBacktestEngine()      ← 回测引擎
 ├─11. TradingSignalCollector(registry) ← 信号收集器
 ├─12. SignalArbitrator (特性开关)   ← 信号仲裁器 (可选)
 ├─13. FactorRegistry.set_mode()    ← 因子准入 (特性开关)
 ├─14. PositionSizer (可选)          ← 仓位计算器
 └─15. UnifiedResearchPipeline(analysis, backtest, collector, arbitrator, sizer, time_provider, max_workers)
       └─ 注册为 "research_pipeline"
```

**容器注册的服务键:**
- `storage`, `calendar`, `cache`, `data_service`, `time_provider`
- `engine_factory`, `market_cache`, `analysis_service`
- `backtest_engine`, `signal_collector`, `arbitrator`, `research_pipeline`

共 12 个服务键, DAG 零循环依赖 ✅

---

## 2. 单票分析流程图 (AnalysisService)

```
run_ticker_analysis(ticker, trace_id)
 │
 ├─ Step 1: _prepare_data(ticker)
 │    ├─ 特征标记 use_research_data_pack?
 │    │   ├─ true  → data_service.fetch_research_pack(ticker) → ResearchDataPack
 │    │   └─ false → data_service.fetch_for_brain(ticker)     → Dict[str, Any]
 │    ├─ stock_df 为 None/empty → 返回 None → 返回失败结果
 │    └─ 返回 data_pack (Union type)
 │
 ├─ Step 2: _run_engines(ticker, data_pack)  ← 顺序执行 7 个引擎
 │    ├─ _run_regime()     → MarketLevelCache 缓存市场级别 → RegimeOutput
 │    ├─ _run_lppl()       → LPPL 泡沫检测 → LPPLOutput
 │    ├─ _run_ntf()        → MarketLevelCache 缓存 NTF → NtfOutput
 │    ├─ _run_czsc()       → CZSC 缠论 → CZSCOutput
 │    ├─ _run_wyckoff()    → Wyckoff 威科夫 → WyckoffOutput
 │    ├─ _run_alpha()      → Alpha 分离度 → AlphaOutput
 │    └─ _calculate_derived() → MA 状态 + ATR 止损
 │
 ├─ (每个引擎完成后发布 EngineCompleted 事件)
 │
 ├─ Step 3: _make_decision(ticker, data_pack)
 │    ├─ MarketSignalContext.from_dict(data_pack)  ← 构建上下文字典
 │    ├─ DecisionBrain.make_decision(ctx)           ← 最终决策
 │    └─ DecisionOutput.from_dict(raw)              ← 类型化解包
 │
 └─ 返回 TickerAnalysisResult
```

**引擎执行顺序**: regime → lppl → ntf → czsc → wyckoff → alpha → derived

**特征标记控制**:
- `use_research_data_pack: false` — DictPackWriter 写入 (当前默认)
- `factor_gate: "block"` — FactorRegistry 阻止未注册因子

---

## 3. 研究流水线流程图 (UnifiedResearchPipeline)

```
run(symbol)
 │
 ├─ Step 1-2: analysis_service.run_ticker_analysis()
 │    → TickerAnalysisResult
 │
 ├─ (检查 success, 失败直接返回 PipelineResult)
 │
 ├─ Step 3: 信号收集
 │    ├─ _merge_decision_for_collection(data_pack, decision)
 │    ├─ TradingSignalCollector.collect(pack, timestamp, bar_date, shares)
 │    └─ 信号仲裁 (如启用):
 │         ├─ _signals_to_candidates() → List[CandidateSignal]
 │         └─ arbitrator.arbitrate_candidates(candidates, decision, context, sizer)
 │
 ├─ Step 4: 回测
 │    ├─ stock_df = data_pack.stock_df 或 data_pack["stock"]
 │    ├─ UnifiedBacktestEngine.run(df, signals, symbol, name)
 │    └─ → BacktestResult
 │
 └─ 返回 PipelineResult (含 data_pack, decision, signals, backtest, metrics)
```

**run_batch(symbols):**
```
 ├─ checkpoint 检查: 已完成的跳过
 ├─ ThreadPoolExecutor(max_workers) 并行
 │    └─ 每个 symbol 调用 run()
 ├─ 原子 checkpoint: 每个完成后写入 {symbol}.json
 └─ 按输入顺序返回结果 (result_map)
```

---

## 4. 引擎工厂注册清单 (AnalysisEngineFactory)

| 属性 | 引擎类 | 模块路径 | 初始化方式 |
|------|--------|---------|-----------|
| `.fsm` | `FsmAnalysisEngine` | `..analysis.fsm_analysis_engine` | lazy import |
| `.czsc` | `CzscAnalysisEngine` | `..analysis.czsc_analysis_engine` | lazy import |
| `.lppl` | `LpplAnalysisEngine` | `..analysis.lppl_analysis_engine` | lazy import |
| `.regime` | `RegimeAnalysisEngine` | `..analysis.regime_analysis_engine` | lazy import |
| `.ntf` | `NtfAnalysisEngine` | `..analysis.ntf_analysis_engine` | lazy import |
| `.macro` | `MacroAnalysisEngine` | `..analysis.macro_analysis_engine` | lazy import |
| `.report` | `ReportGeneratorEngine` | `..analysis.report_generator_engine` | lazy import |
| `.wyckoff` | `WyckoffAnalysisEngine` | `..analysis.wyckoff_analysis_engine` | lazy import |
| `.brain` | `DecisionBrain` | (直接 import) brain.fsm | direct import |

共 9 个 engine 注册: fsm, czsc, lppl, regime, ntf, macro, report, brain, wyckoff

**关键设计**:
- 工厂在 `AnalysisService` 创建前就已创建 (初始 orchestrator = DataService)
- `bind_orchestrator(analysis_svc)` 在服务创建后重定向
- 双检锁 + RLock 保证线程安全
- 失败时抛出 `RuntimeError`

---

## 5. 服务详细分析

### 5.1 ServiceContainer

- 单例模式 (`_instance` + `_lock`)
- 工厂注册: `register_factory()` 用于延迟创建
- 直接注册: `register()` 用于已创建实例
- `get()` 自动调用工厂方法一次
- `reset()`/`clear()` 用于测试

**初始化顺序的隐含假设**:
1. DataService 必须在 AnalysisService 之前创建
2. EngineFactory 初始拿到 DataService, 后绑定 AnalysisService
3. MarketLevelCache 必须在 DataService.attach_market_cache() 之前创建

### 5.2 AnalysisService

- 1642 行 → ~300 行重构完成 ✅
- 依赖 DataService (数据获取), EngineFactory (引擎), MarketLevelCache (缓存)
- 所有引擎运行在 `try/except RECOVERABLE_ERRORS` 内
- 每个引擎失败时写入默认值 + engine_status 标记

**pack_writer 双写策略**:
- DictPackWriter: 写 Dict[str, Any]
- RDPackWriter: 写 ResearchDataPack
- 根据 data_pack 类型自动选择

### 5.3 UnifiedResearchPipeline

- 4 步编排: 分析 → 收集 → 仲裁 → 回测
- 每步发布事件 (如果 event_bus 启用)
- 信号仲裁由 `signal_arbitration` 特性开关控制
- Batch 模式: ThreadPoolExecutor + 原子 JSON checkpoint
- `_save_batch_checkpoint` 使用原子文件交换 (tmp + os.replace)

**checkpoint 内容**: decision, signals, backtest (不保存原始 K 线 data_pack)

### 5.4 DataService (门面)

- 协调: CacheCoordinator, DataQualityService, StockQueryService, DataAccessService
- `fetch_for_brain(ticker)` → Dict[str, Any]
- `fetch_research_pack(ticker)` → ResearchDataPack (默认不启用)

---

## 6. 失败路径和默认值

| 失败点 | 行为 | 默认值 |
|--------|------|--------|
| `_prepare_data`: 数据不足 | 返回 None | `TickerAnalysisResult(success=False, error="数据不足")` |
| `_run_regime`: 指数数据不可用 | `RegimeOutput(regime="UNKNOWN")` | 标记 `DATA_UNAVAILABLE` |
| `_run_lppl`: 分析失败 | `LPPLOutput(risk_level="ENGINE_FAILED")` | 标记 `ENGINE_FAILED` |
| `_run_czsc`: 失败 | `CZSCOutput()` (全默认) | 不标记状态 |
| `_run_wyckoff`: 失败 | `WyckoffOutput()` (全默认) | 不标记状态 |
| `_run_alpha`: 无对标数据 | `AlphaOutput(score=0.0)` | 静默返回 |
| `_run_ntf`: 失败 | `NtfOutput(side="NONE")` | 静默返回 |
| `_create_decision`: 失败 | 返回 None | `TickerAnalysisResult(success=False, error="决策失败")` |
| Pipeline: 无 K 线数据 | 直接返回失败 | `error="K线数据为空"` |
| Pipeline batch: 单标失败 | 返回单个失败 result | 不影响其他标的 |
| Arbitrator 初始化失败 | 禁用仲裁器 | `arbitrator = None` |
| PositionSizer 初始化失败 | 禁用 sizer | `sizer = None` |
| FactorRegistry gate 失败 | 保持默认模式 | 仅 debug 日志 |

---

## 7. 接口漂移和隐式耦合

| 问题 | 位置 | 风险 |
|------|------|------|
| `_get_cached_result` 调用 `data_service._get_cached()` (私有方法) | `analysis_service_v2.py:134` | 耦合到 DataService 内部实现 |
| `_set_cached_result` 调用 `data_service._set_cache()` (私有方法) | `analysis_service_v2.py:146` | 同上 |
| `EngineFactory` 初始 orc=DataService, 后改为 AnalysisService | `service_container.py:86,96` | 切换期可能产生不一致 |
| `_signals_to_candidates()` 使用字符串拆分解析 source | `research_pipeline.py:199` | 脆弱解析, 依赖 reason 格式约定 |
| `_merge_decision_for_collection()` 硬编码字段名 | `research_pipeline.py:399` | 与 DecisionBrain 输出耦合 |
| DataService 门面要求 fetcher/storage/cleaner 但全部可选 | `data_service.py` | 运行时可能 NPE |

---

## 8. 风险与改进建议

| ID | 风险 | 严重度 | 建议 |
|----|------|--------|------|
| S1 | 引擎全部串行执行, 无并行 | 中 | regime/ntf 已缓存, 但 lppl/czsc/wyckoff/alpha 可并行 |
| S2 | 私有方法耦合 (见 §7) | 中 | DataService 应暴露公共缓存接口 |
| S3 | ResearchDataPack 默认关闭 | 低 | 可逐步开启 typed path |
| S4 | EngineFactory 双阶段绑定 | 低 | 改为 AnalysisService 直接创建工厂 |
| S5 | SignalArbitrator 失败时完全禁用 | 低 | 改为降级模式而非完全关闭 |
| S6 | checkpoint 不存 data_pack | 低 | 恢复时 data_pack 为空, 不影响信号和回测 |

---

## 校验清单 (Stage 1)

- [x] 能解释 ServiceContainer.initialize() 每一步 (15 步 DAG)
- [x] 能解释 run_ticker_analysis 的输入输出 (ticker → TickerAnalysisResult)
- [x] 说明 engine_factory 何时 bind orchestrator (创建后)
- [x] 识别缓存、数据服务、分析服务之间的边界
- [x] 列出 9 个引擎注册清单
- [x] 列出 13 个失败路径及其行为
- [x] 识别 6 个接口漂移/隐式耦合点
