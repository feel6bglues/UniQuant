# Stage 1 - Services Orchestration

Generated: 2026-06-09

Scope: Services-layer orchestration only. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0 artifact and services control files.
2. Map `ServiceContainer.initialize()` registration and initialization order.
3. Trace `AnalysisService.run_ticker_analysis()` input, output, and failure branches.
4. Trace `AnalysisEngineFactory` lazy loading and orchestrator rebinding.
5. Trace `UnifiedResearchPipeline.run()` from analysis to signal collection to backtest.
6. Check tests for service topology, factory contract, pipeline contract, and known gaps.

## 2. 已阅读文件

| File | Purpose in this stage |
|---|---|
| `docs/analysis/00_architecture_map.md` | Stage 0 architecture baseline and Stage 1 input. |
| `src/uniquant/services/service_container.py` | DI composition root and service registration. |
| `src/uniquant/services/__init__.py` | Lazy import contract for public services package. |
| `src/uniquant/services/data_service.py` | Data facade and `fetch_for_brain()` producer. |
| `src/uniquant/services/data_access_service.py` | Data lake/source fallback paths used by `DataService`. |
| `src/uniquant/services/analysis_service_v2.py` | Single-ticker analysis orchestrator. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy engine factory and orchestrator rebinding. |
| `src/uniquant/services/research_pipeline.py` | End-to-end analysis/signal/backtest pipeline. |
| `src/uniquant/services/market_cache.py` | Shared market-level regime/NTF/benchmark cache. |
| `src/uniquant/signal/adapters.py` | `TradingSignalCollector` used by pipeline. |
| `src/uniquant/hands/backtest/unified_engine.py` | Backtest engine called by pipeline. |
| `tests/test_engine_factory.py` | Lazy engine factory tests. |
| `tests/test_service_container.py` | Service container basic registration/topology tests. |
| `tests/test_phase4_2_contracts.py` | Factory rebind, pipeline decision-to-signal, trace id tests. |
| `tests/test_e2e_pipeline.py` | Collector-to-backtest and cache behavior tests. |
| `tests/test_e2e_integration_qa.py` | Real container initialization smoke path. |
| `tests/test_di_container_and_cache.py` | Import side-effect and cache/DI regression coverage. |

## 3. 服务依赖拓扑图

`ServiceContainer.initialize()` is the concrete composition root (`src/uniquant/services/service_container.py:74-127`).

```text
ServiceContainer
  ├─ StorageManager
  ├─ TradeCalendarManager
  ├─ CacheCoordinator
  ├─ DataService(storage_manager=StorageManager)
  │    ├─ DataFetcher
  │    ├─ DataCleaner
  │    ├─ DataQualityService
  │    ├─ StockQueryService
  │    └─ DataAccessService
  ├─ AnalysisEngineFactory(orchestrator=DataService)
  ├─ MarketLevelCache
  │    └─ attached to DataService
  ├─ AnalysisService(data_service, engine_factory, market_cache)
  │    └─ engine_factory.bind_orchestrator(AnalysisService)
  ├─ UnifiedBacktestEngine
  ├─ TradingSignalCollector(default adapter registry)
  └─ UnifiedResearchPipeline(analysis_service, backtest_engine, signal_collector)
```

Registered services:

| Registration key | Constructed object | Evidence |
|---|---|---|
| `storage` | `StorageManager()` | `src/uniquant/services/service_container.py:81-88` |
| `calendar` | `TradeCalendarManager()` | `src/uniquant/services/service_container.py:82-89` |
| `cache` | `CacheCoordinator()` | `src/uniquant/services/service_container.py:83-90` |
| `data_service` | `DataService(storage_manager=storage)` | `src/uniquant/services/service_container.py:85-91` |
| `engine_factory` | `AnalysisEngineFactory(orchestrator=data_svc)` | `src/uniquant/services/service_container.py:93-99` |
| `market_cache` | `MarketLevelCache()` | `src/uniquant/services/service_container.py:94-100` |
| `analysis_service` | `AnalysisService(data_svc, engine_factory, market_cache)` | `src/uniquant/services/service_container.py:102-112` |
| `backtest_engine` | `UnifiedBacktestEngine()` | `src/uniquant/services/service_container.py:114-116` |
| `signal_collector` | `TradingSignalCollector(create_default_registry())` | `src/uniquant/services/service_container.py:105-117` |
| `research_pipeline` | `UnifiedResearchPipeline(...)` | `src/uniquant/services/service_container.py:119-124` |

The topology is intended to be acyclic. `AnalysisService` imports `DataService` and receives it by constructor injection (`src/uniquant/services/analysis_service_v2.py:81-97`). Data access remains behind `DataService`/`DataAccessService`; brain adapters should use the service contract exposed by `AnalysisService`, not construct their own services.

## 4. 单票分析流程图

`AnalysisService.run_ticker_analysis(ticker, trace_id=None)` returns `TickerAnalysisResult` (`src/uniquant/services/analysis_service_v2.py:240-287`).

```text
run_ticker_analysis(symbol)
  -> create/accept trace_id
  -> _prepare_data(symbol)
       -> DataService.fetch_for_brain(symbol)
       -> require data_pack["stock"] exists and is non-empty
  -> attach trace_id to data_pack
  -> _run_engines(symbol, data_pack)
       -> _run_regime
       -> _run_lppl
       -> _run_ntf
       -> _run_czsc
       -> _run_wyckoff
       -> _run_alpha
       -> _calculate_derived
       -> set symbol and market="CN"
  -> _make_decision(symbol, data_pack)
       -> DecisionBrain.make_decision(data_pack)
  -> TickerAnalysisResult(symbol, data_pack, decision, signals=[], success=True)
```

Input:

- `ticker: str`
- Optional `trace_id: str`

Output:

- `TickerAnalysisResult.symbol`
- `TickerAnalysisResult.data_pack`
- `TickerAnalysisResult.decision`
- `TickerAnalysisResult.signals`, intentionally empty at this layer
- `TickerAnalysisResult.success`
- `TickerAnalysisResult.error`
- `TickerAnalysisResult.trace_id`

`DataService.fetch_for_brain()` produces `stock`, `bench`, and `etf` (`src/uniquant/services/data_service.py:397-407`). `DataAccessService.load_data_with_fallback()` first reads the lake, then tries alternate index symbols for index data, then falls back to `fetcher.get_price()`, cleans, writes to the lake, and returns a clone (`src/uniquant/services/data_access_service.py:130-177`).

## 5. 研究流水线流程图

`UnifiedResearchPipeline.run(symbol, name=None, default_shares=100, trace_id=None)` returns `PipelineResult` (`src/uniquant/services/research_pipeline.py:95-173`).

```text
UnifiedResearchPipeline.run(symbol)
  -> trace_id
  -> AnalysisService.run_ticker_analysis(symbol, trace_id)
  -> if analysis failed:
       PipelineResult(success=False, signals=[], BacktestResult())
  -> _merge_decision_for_collection(data_pack, decision)
       copies final_decision/action/shares/confidence/reason/price
       derives confidence from final_score or score when needed
  -> TradingSignalCollector.collect(collector_pack, timestamp=now, default_shares)
  -> require data_pack["stock"] non-empty
  -> UnifiedBacktestEngine.run(df=stock, signals=signals, symbol=symbol, name=name)
  -> PipelineResult(success=True, data_pack, decision, signals, backtest)
```

Key boundary:

- `AnalysisService` produces analysis facts and `DecisionBrain` decision.
- `TradingSignalCollector` turns those facts into executable `TradingSignal` objects.
- `UnifiedBacktestEngine` consumes only K-line data plus `List[TradingSignal]`.

The pipeline used `pd.Timestamp.now()` for collected signal timestamps (`src/uniquant/services/research_pipeline.py:133-136`). **G-1 (2026-06-12) resolved this** — `pd.Timestamp.now()` replaced with `get_time_provider().now()` (`TimeProvider`), achieving 0 production calls.

## 6. 引擎工厂注册清单

`AnalysisEngineFactory` lazily imports engine adapters and caches instances (`src/uniquant/services/analysis/engine_factory.py:33-48`).

| Factory property | Engine name | Module path | Class | Evidence |
|---|---|---|---|---|
| `fsm` | `fsm` | `..analysis.fsm_analysis_engine` | `FsmAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:50-52` |
| `czsc` | `czsc` | `..analysis.czsc_analysis_engine` | `CzscAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:54-56` |
| `lppl` | `lppl` | `..analysis.lppl_analysis_engine` | `LpplAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:58-60` |
| `regime` | `regime` | `..analysis.regime_analysis_engine` | `RegimeAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:62-64` |
| `ntf` | `ntf` | `..analysis.ntf_analysis_engine` | `NtfAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:66-68` |
| `macro` | `macro` | `..analysis.macro_analysis_engine` | `MacroAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:70-72` |
| `report` | `report` | `..analysis.report_generator_engine` | `ReportGeneratorEngine` | `src/uniquant/services/analysis/engine_factory.py:74-76` |
| `brain` | `brain` | direct import | `DecisionBrain` | `src/uniquant/services/analysis/engine_factory.py:78-92` |
| `wyckoff` | `wyckoff` | `..analysis.wyckoff_analysis_engine` | `WyckoffAnalysisEngine` | `src/uniquant/services/analysis/engine_factory.py:94-96` |

Rebind behavior:

- The container creates the factory before `AnalysisService` exists, with `orchestrator=data_svc` (`src/uniquant/services/service_container.py:96`).
- `AnalysisService.__init__()` calls `engine_factory.bind_orchestrator(self)` if the factory supports it (`src/uniquant/services/analysis_service_v2.py:92-96`).
- `bind_orchestrator()` replaces `_orchestrator` and clears `_engines` (`src/uniquant/services/analysis/engine_factory.py:20-32`).
- `tests/test_phase4_2_contracts.py:72-91` verifies the factory orchestrator becomes the `AnalysisService` and that lazy-created `fsm_engine.orchestrator is analysis`.

## 7. 服务公共导入契约

`src/uniquant/services/__init__.py` exposes services through module-level `__getattr__()` to avoid import-time dependency chains (`src/uniquant/services/__init__.py:1-43`).

Current exported names:

- `CacheCoordinator`
- `DataService`
- `HealthService`
- `PortfolioService`
- `ScanPipeline`
- `StockQueryService`
- `ValidationService`
- `AnalysisService`
- `ServiceContainer`
- `DataAccessService`
- `DataQualityService`
- `MarketRegimeService`
- `ReportService`
- `SignalGenerationService`

Risk: if a public service is renamed or moved, import failures are converted to `AttributeError` with a dependency-not-installed message (`src/uniquant/services/__init__.py:35-41`). This is good for lazy import isolation but can hide real internal import regressions unless tests import all public service names.

## 8. 失败路径和默认值

| Path | Trigger | Behavior | Evidence | Risk |
|---|---|---|---|---|
| `AnalysisService._prepare_data()` | `fetch_for_brain()` returns no pack, no `stock`, empty `stock`, or recoverable exception | Returns `None`; caller returns `TickerAnalysisResult(success=False, error="数据不足")` | `src/uniquant/services/analysis_service_v2.py:254-262`, `291-304` | Clear failure, but root cause can be reduced to generic error. |
| `_run_engines()` outer wrapper | Any recoverable exception escapes a sub-engine wrapper | Returns `False`; caller returns `error="引擎分析失败"` | `src/uniquant/services/analysis_service_v2.py:308-324` | Most sub-engine errors are swallowed into defaults, so this branch may underrepresent partial failures. |
| `_run_regime()` | HS300 missing | Sets `regime="UNKNOWN"`, entropy/turnover zero, engine status `DATA_UNAVAILABLE` | `src/uniquant/services/analysis_service_v2.py:339-356` | Conservative but can make market filter ineffective. |
| `_run_lppl()` | LPPL result missing success/risk level or exception | Sets `risk="ENGINE_FAILED"` and `bubble_confidence=1.0`; engine status failed | `src/uniquant/services/analysis_service_v2.py:371-396` | Conservative if downstream treats it as high risk, dangerous if adapters do not recognize `ENGINE_FAILED`. |
| `_run_ntf()` | NTF failure | Sets `ntf_side="NONE"`, `ntf_intensity=0.0` | `src/uniquant/services/analysis_service_v2.py:398-428` | Failure becomes no intervention signal. |
| `_run_czsc()` | CZSC failure | Sets `is_3rd_buy=False`, `bi_count=0` | `src/uniquant/services/analysis_service_v2.py:430-441` | Failure becomes no CZSC signal. |
| `_run_wyckoff()` | Wyckoff failure | Sets phase `unknown`, confidence `0.0` | `src/uniquant/services/analysis_service_v2.py:443-456` | Failure becomes no Wyckoff signal. |
| `_run_alpha()` | Missing stock/benchmark or failure | Sets `alpha_score=0.0` | `src/uniquant/services/analysis_service_v2.py:458-480` | In `AlphaScoreAdapter`, score `<0.3` maps to SELL (`src/uniquant/signal/adapters.py:317-346`), so missing benchmark can become a bearish executable signal. This is high priority for Stage 5. |
| `_make_decision()` | DecisionBrain error | Returns `None`; caller returns `error="决策失败"` | `src/uniquant/services/analysis_service_v2.py:618`, `272-278` | Clear failure at analysis level. |
| `UnifiedResearchPipeline.run()` | Analysis failed | Returns failed `PipelineResult` with empty signals/backtest | `src/uniquant/services/research_pipeline.py:114-126` | Good boundary. |
| `UnifiedResearchPipeline.run()` | `data_pack["stock"]` empty after signal collection | Returns failed `PipelineResult` with signals and empty backtest | `src/uniquant/services/research_pipeline.py:138-150` | Signals can exist without executable K-line data. |
| `run_batch()` | Per-symbol exception | Appends failed `PipelineResult(error=str(e))` | `src/uniquant/services/research_pipeline.py:175-208` | Batch continues, but no trace id is attached on exception branch. |

## 9. 服务边界评价

### Data and Cache Boundary

`DataService` owns data fetching, cleaning, lake access, stock query, quality service, and shared cache facade (`src/uniquant/services/data_service.py:35-91`). `AnalysisService` accesses data through `data_service.fetch_for_brain()` and selected data-service/lake methods; it no longer owns low-level data fetching (`src/uniquant/services/analysis_service_v2.py:65-79`, `291-301`).

`MarketLevelCache` is separate from the general `CacheCoordinator`. It stores market-level regime, NTF, and benchmark state under a simple date guard (`src/uniquant/services/market_cache.py:22-102`). `DataService.invalidate_symbol_cache()` clears market cache for index updates (`src/uniquant/services/data_service.py:165-185`).

Risk: `MarketLevelCache` uses one `_date` for regime and NTF. `set_ntf()` does not update `_date` if `_date` already exists (`src/uniquant/services/market_cache.py:67-72`), so interactions between regime and NTF cache freshness should be inspected if intraday refresh semantics matter.

### Analysis and Engine Boundary

The service-level engine adapters expect an orchestrator that provides cache helpers, data service, precision helpers, and sometimes `brain`, `evt_risk`, and `sizer`. Example: `FsmAnalysisEngine` calls `_generate_cache_key`, `_get_cached_result`, `data_service.lake`, `_optimize_dataframe`, `_sample_data`, `brain`, `evt_risk`, `sizer`, and `ensure_precision_consistency` (`src/uniquant/services/analysis/fsm_analysis_engine.py:40-120`). This explains why factory rebinding to `AnalysisService` is required.

### Signal and Backtest Boundary

The pipeline does not choose a single final signal. It merges decision fields into a copy of `data_pack` and lets `TradingSignalCollector` collect all eligible adapter outputs (`src/uniquant/services/research_pipeline.py:210-237`; `src/uniquant/signal/adapters.py:450-520`). `UnifiedBacktestEngine` then processes dated signals sequentially and only creates one pending order per day when position conditions permit (`src/uniquant/hands/backtest/unified_engine.py:241-258`).

This boundary is clean but not fully policy-complete: conflict ordering and priority are implicit in collector order, not explicit in a service-level signal arbitration policy.

## 10. 测试覆盖观察

Covered:

- Lazy factory delayed init, cached access, and import failure isolation: `tests/test_engine_factory.py:42-76`.
- Factory rebind contract and required `AnalysisService` adapter methods: `tests/test_phase4_2_contracts.py:72-91`.
- Pipeline converts FSM decision into standard `TradingSignal`: `tests/test_phase4_2_contracts.py:94-116`.
- Trace id propagation in analysis result: `tests/test_phase4_2_contracts.py:119-142`.
- Collector to engine E2E behavior with mock data: `tests/test_e2e_pipeline.py:96-172`.
- Real `ServiceContainer.initialize()` smoke path for storage and engine factory: `tests/test_e2e_integration_qa.py:149-167`.

Gaps:

- `tests/test_service_container.py:44-65` only asserts early registrations through `engine_factory`; it does not assert `analysis_service`, `backtest_engine`, `signal_collector`, or `research_pipeline`.
- No Stage 1 evidence that all public names in `src/uniquant/services/__init__.py` are imported in one test.
- [OUTDATED: resolved by G-1 TimeProvider] No explicit service-level test that pipeline-generated `pd.Timestamp.now()` signals produce expected behavior on historical data.
- No explicit test that alpha failure/missing benchmark does not create an unintended SELL signal.
- No test in this stage was run in the current working tree, so these are coverage observations from source reading only.

## 11. 关键发现

1. The services layer has a real composition root and mostly explicit dependency injection through `ServiceContainer.initialize()`.
2. The most important contract in the services layer is not a class; it is the mutable `data_pack` schema passed from `DataService` to `AnalysisService`, `DecisionBrain`, `TradingSignalCollector`, and `UnifiedResearchPipeline`.
3. `AnalysisEngineFactory` rebinding is deliberate and currently covered by `tests/test_phase4_2_contracts.py`.
4. `AnalysisService.run_ticker_analysis()` handles full-analysis failure, but individual engine failures often become default fields inside `data_pack`.
5. `UnifiedResearchPipeline.run()` cleanly separates analysis failure, signal collection, empty K-line failure, and backtest execution.
6. Signal arbitration is implicit. Multiple adapters can emit contradictory signals from the same `data_pack`; collector order and backtest position state determine what eventually trades.
7. Pipeline-generated signals use current time by default, which is likely correct for live/current analysis but problematic for historical backtests unless timestamp injection is used.

## 12. 风险与改进建议

| Priority | Risk | Concrete improvement |
|---|---|---|
| High | `alpha_score=0.0` on alpha failure can be mapped to SELL by `AlphaScoreAdapter`. | Stage 5 should decide whether missing/failed alpha should produce no signal instead of bearish signal; add a regression test around missing benchmark. |
| High | Pipeline signal timestamp defaults to now, so historical stock data may receive no trades. | Stage 6 should distinguish live/current pipeline mode from historical pipeline mode and add a timestamp policy or signal alignment option. |
| Medium | Service container tests do not assert all registered services. | Add assertions for `analysis_service`, `market_cache`, `backtest_engine`, `signal_collector`, and `research_pipeline`. |
| Medium | `data_pack` schema is implicit and mutable. | Stage 3/5 should produce a field-source table and consider using `MarketSignalContext` at service boundaries where practical. |
| Medium | Signal conflict resolution is implicit. | Stage 5 should inspect or design explicit signal aggregation/priority policy. |
| Medium | `MarketLevelCache` shares one date across regime and NTF. | Stage 1 follow-up or Stage 2/3 should verify freshness semantics and consider per-cache timestamps. |
| Low | `ServiceContainer.reset()` clears `_services` but not `_factories` or `_registrations` (`src/uniquant/services/service_container.py:65-68`). | Confirm intended semantics; if reset is expected to preserve factories, document it. If not, align tests and implementation. |
| Low | `services.__init__` converts `ImportError` to generic `AttributeError`. | Add import smoke tests for every exported service name to catch internal import regressions. |

## 13. 校验清单

- [x] Explained every major `ServiceContainer.initialize()` step.
- [x] Explained `run_ticker_analysis()` input, output, success path, and failure path.
- [x] Explained when `AnalysisEngineFactory.bind_orchestrator()` runs and why it matters.
- [x] Identified service registrations and engine factory registrations.
- [x] Explained cache, data service, analysis service, signal collector, and backtest boundaries.
- [x] Identified failure defaults and high-risk default-to-signal behavior.
- [x] Bound findings to concrete files, functions, lines, and tests.
- [x] Did not modify source code.
- [x] Did not claim tests passed; no test command was run.

## 14. 下一阶段输入

Stage 2 should inspect the data system using this services boundary:

- `src/uniquant/services/data_service.py`
- `src/uniquant/services/data_access_service.py`
- `src/uniquant/data/data_fetcher.py`
- `src/uniquant/data/lake/storage_manager.py`
- `src/uniquant/data/pipeline/data_cleaner.py`
- `src/uniquant/data/pipeline/data_validator.py`
- `src/uniquant/data/pipeline/data_adjuster.py`
- `src/uniquant/data/managers/source_router.py`
- `src/uniquant/data/managers/market_data_coordinator.py`
- `src/uniquant/data/sources/`
- `config/config.yaml`
- `tests/test_data_access_service.py`
- `tests/test_data_and_stock_query_regressions.py`
- `tests/test_validation_service.py`
- `tests/test_lookahead_bias.py`

Stage 2 should answer:

1. Exactly how do `stock`, `bench`, and `etf` frames enter `data_pack`?
2. Which data types are read from lake only, which fall back to source, and which are persisted?
3. Which OHLCV fields are guaranteed before brain/backtest consumption?
4. How are empty data, source failure, wrong symbols, and stale caches handled?
5. Are future-data and lookahead-bias defenses present in the data path?

## 15. 阶段结论

The services layer is coherent and centered on `ServiceContainer`, `AnalysisService`, `AnalysisEngineFactory`, and `UnifiedResearchPipeline`. Its main design strength is explicit orchestration with typed result objects and a normalized `TradingSignal` bridge. The main architectural weaknesses are implicit `data_pack` schema, default values that can become executable signals, implicit signal conflict policy, and timestamp assumptions in the pipeline-to-backtest path.
