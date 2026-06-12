# WS1 - Architecture Discovery

Generated: 2026-06-09

Scope: Current UniQuant source code as a research platform. Source code is authoritative; historical docs are background only.

## 1. Objective

Discover the current system topology, map it to institutional target layers, and identify coupling risks before any refactoring design.

This report is not a code-change plan. It is an evidence baseline for later data lineage, contract, adapter, backtest, risk, and refactoring workstreams.

## 2. Current Module Topology

Current source scan shows eight runtime packages under `src/uniquant/`:

| Module | File count observed | Current responsibility | Institutional layer mapping |
|---|---:|---|---|
| `shared` | 37 | Cross-layer dataclasses, protocols, constants, exceptions, logging, cache, A-share market rules, costs, slippage, limits. | Infrastructure + Contracts |
| `data` | 65 | Data ingestion, data lake, source routing, parsers, cleaners, validators, adjusters, import/update tools. | Data Platform + Infrastructure |
| `brain` | 74 | Research engines, factors, FSM/DecisionBrain, LPPL, CZSC, NTF, regime, Wyckoff, indicators, screener. | Research |
| `signal` | 7 | Signal models, normalization, adapters, aggregation, quality, storage. | Signal |
| `hands` | 34 | Backtest engines, matching, portfolio engine, strategies, reports, robustness and overfitting tools. | Portfolio + Execution Simulation |
| `risk` | 7 | Position sizing, drawdown, EVT, historical risk, structural risk, optimization. | Risk |
| `services` | 31 | Composition root, orchestration, data service, analysis service, pipeline, scan, portfolio, health, reports. | Application Orchestration |
| `ui` | 8 | Streamlit dashboard and UI-facing manager services. | Presentation |

Evidence:

- `ServiceContainer.initialize()` registers storage, calendar, cache, data service, engine factory, market cache, analysis service, backtest engine, signal collector, and research pipeline (`src/uniquant/services/service_container.py:74-127`).
- `DataService.fetch_for_brain()` creates the research data pack with `stock`, `bench`, and `etf` (`src/uniquant/services/data_service.py:397-407`).
- `AnalysisService.run_ticker_analysis()` orchestrates data preparation, engine execution, and DecisionBrain decision (`src/uniquant/services/analysis_service_v2.py:240-287`).
- `UnifiedResearchPipeline.run()` connects analysis, signal collection, and backtest (`src/uniquant/services/research_pipeline.py:95-173`).
- `TradingSignal` is the typed Brain -> Hands bridge (`src/uniquant/shared/interfaces.py:127-169`).
- `UnifiedBacktestEngine.run()` accepts `List[TradingSignal]` and K-line data (`src/uniquant/hands/backtest/unified_engine.py:118-124`).

## 3. Current Architecture Map

```text
shared
  -> data
      -> DataService
          -> AnalysisEngineFactory
              -> brain engines
          -> AnalysisService
              -> DecisionBrain
              -> data_pack mutations
          -> TradingSignalCollector
              -> signal adapters
          -> UnifiedBacktestEngine
              -> BacktestResult
          -> UnifiedResearchPipeline
              -> PipelineResult
ui
  -> services
```

The system is not a pure layer stack. It is service-orchestrated:

```text
services
  ├── imports data for DataService
  ├── imports brain through analysis adapters/factory
  ├── imports signal adapters for TradingSignal collection
  ├── imports hands/backtest for simulation
  └── exposes pipeline/services to ui
```

This is acceptable as a composition-root pattern if lower layers do not depend back on `services`.

## 4. Institutional Layer Overlay

| Institutional layer | Current source evidence | Status |
|---|---|---|
| Research | `brain/*`, `services/analysis_service_v2.py`, `services/analysis/*` | Present |
| Signal | `shared.interfaces.TradingSignal`, `signal/adapters.py`, `signal/models.py`, `signal/normalizer.py` | Present but split between two signal models |
| Portfolio | `hands/backtest/portfolio_engine.py`, `services/portfolio_service.py`, `risk/portfolio_optimizer.py` | Present for research/backtest; not live OMS |
| Execution | `hands/backtest/unified_engine.py`, `hands/backtest/unified_matching_engine.py` | Present as simulated execution |
| Risk | `risk/*`, `shared.interfaces.PositionSizerProtocol`, `brain/fsm` optional risk/sizer dependencies | Present, partially integrated |
| Broker | No broker/order gateway file identified in current WS1 scan | Absent/deferred |
| Infrastructure | `shared/*`, `data/lake/*`, `services/service_container.py`, cache/logging/config utilities | Present |

Broker status:

```text
INSUFFICIENT EVIDENCE for live Broker Layer implementation.
```

No current WS1 evidence shows live broker APIs, OMS state reconciliation, live order routing, or broker recovery. Treat broker/live production readiness as WS13 blueprint scope.

## 5. Dependency Graph

Current runtime path:

```text
ServiceContainer
  ├── StorageManager
  ├── TradeCalendarManager
  ├── CacheCoordinator
  ├── DataService
  │   ├── DataFetcher
  │   ├── StorageManager
  │   ├── DataCleaner
  │   ├── DataAccessService
  │   ├── DataQualityService
  │   └── StockQueryService
  ├── AnalysisEngineFactory
  │   ├── FsmAnalysisEngine
  │   ├── CzscAnalysisEngine
  │   ├── LpplAnalysisEngine
  │   ├── RegimeAnalysisEngine
  │   ├── NtfAnalysisEngine
  │   ├── MacroAnalysisEngine
  │   ├── ReportGeneratorEngine
  │   └── DecisionBrain
  ├── MarketLevelCache
  ├── AnalysisService
  │   ├── DataService
  │   ├── AnalysisEngineFactory
  │   ├── MarketLevelCache
  │   └── DecisionBrain
  ├── TradingSignalCollector
  │   ├── LPPLAdapter
  │   ├── CZSCAdapter
  │   ├── WyckoffAdapter
  │   ├── FSMAdapter
  │   ├── RegimeAdapter
  │   ├── NTFAdapter
  │   ├── AlphaScoreAdapter
  │   └── MAStatusAdapter
  ├── UnifiedBacktestEngine
  │   ├── TradingSignal
  │   ├── TradeCalendarManager
  │   ├── market rules
  │   ├── cost model
  │   └── limit checker
  └── UnifiedResearchPipeline
      ├── AnalysisService
      ├── TradingSignalCollector
      └── UnifiedBacktestEngine
```

Important lower-layer exceptions found in import scan:

- `hands/backtest/unified_engine.py` imports `data.managers.trade_calendar_manager.TradeCalendarManager` (`src/uniquant/hands/backtest/unified_engine.py:39`).
- `hands/backtest/unified_matching_engine.py` also imports and default-constructs `TradeCalendarManager` (`src/uniquant/hands/backtest/unified_matching_engine.py:17`, `src/uniquant/hands/backtest/unified_matching_engine.py:41-52`).
- `shared/di_container.py` imports `services.service_container`, which is a reverse dependency from `shared` into `services` (`src/uniquant/shared/di_container.py:12-14`).
- Several `brain` modules optionally import `data` or `risk`; e.g. `brain/fsm/fsm.py` imports risk components lazily, and LPPL/NTF paths can import data fetchers.

These exceptions are not automatically defects, but they are boundary risks that WS5/WS12 should classify.

## 6. Module Boundary Findings

### Finding WS1-001 - Services is the real composition root

Evidence:

- `ServiceContainer.initialize()` constructs and registers the runtime DAG (`src/uniquant/services/service_container.py:74-127`).
- `services/__init__.py` uses `__getattr__` lazy imports for public service exports (`src/uniquant/services/__init__.py:16-43`).

Impact:

- Architecture changes should start at service composition boundaries, not inside individual engines.
- If service registration drifts, UI, CLI, tests, and pipeline behavior can break together.

Risk Level: P1

Recommendation:

- Treat `ServiceContainer` and `UnifiedResearchPipeline` as formal application-layer contracts.
- Add an architecture contract test that asserts registered service names, no early engine initialization, and successful lazy import of public services.

Migration Cost: Low

Priority: Sprint 1

### Finding WS1-002 - `data_pack` is a mutable cross-layer contract

Evidence:

- `DataService.fetch_for_brain()` returns a dict with `stock`, `bench`, `etf` (`src/uniquant/services/data_service.py:397-407`).
- `AnalysisService` mutates the same dict with trace id, regime, LPPL, NTF, CZSC, Wyckoff, alpha, derived fields, symbol, and market (`src/uniquant/services/analysis_service_v2.py:235-320`).
- `TradingSignalCollector.collect()` reads the same dict to create executable signals (`src/uniquant/signal/adapters.py:434-525`).
- `UnifiedResearchPipeline._merge_decision_for_collection()` shallow-copies and injects decision fields into the collector pack (`src/uniquant/services/research_pipeline.py:210-237`).

Impact:

- Field drift can change research decisions, signal generation, or backtest inputs without a type error.
- This is the main data lineage and contract audit target.

Risk Level: P0

Recommendation:

- Define a typed `ResearchDataPack` or schema boundary in WS2/WS5.
- Keep dict compatibility adapters temporarily, but add schema validation before signal collection and before backtest.

Migration Cost: Medium

Priority: Sprint 1

### Finding WS1-003 - Signal timestamp generation blocks historical research validity

Evidence:

- `UnifiedResearchPipeline.run()` assigns `timestamp = pd.Timestamp.now()` before collecting signals (`src/uniquant/services/research_pipeline.py:133-136`).
- `UnifiedBacktestEngine._index_signals_by_date()` groups signals by their timestamp date (`src/uniquant/hands/backtest/unified_engine.py:288-300`).
- Backtest only consumes signals whose timestamp date matches a K-line date (`src/uniquant/hands/backtest/unified_engine.py:241-258`).

Impact:

- A one-shot current timestamp is not a historical signal series.
- This can produce no trades or misleading trades when the K-line data range does not include the current system date.

Risk Level: P0

Recommendation:

- Create WS4 `HistoricalSignalRunner` design: generate as-of signals per historical bar, stamp each signal with the bar date, and feed the resulting series into `UnifiedBacktestEngine`.

Migration Cost: Medium

Priority: Sprint 1

### Finding WS1-004 - Adapter collection can emit conflicting signals

Evidence:

- `TradingSignalCollector.collect()` appends outputs from LPPL, CZSC, Wyckoff, FSM, Regime, NTF, AlphaScore, and MAStatus sequentially (`src/uniquant/signal/adapters.py:453-525`).
- `UnifiedBacktestEngine.run()` processes daily signals in list order and stops at the first actionable BUY or SELL (`src/uniquant/hands/backtest/unified_engine.py:241-258`).

Impact:

- Risk HOLD or regime HOLD can coexist with later BUY signals; execution depends on collection and engine processing order.
- Signal priority is implicit rather than contractually governed.

Risk Level: P1

Recommendation:

- WS6 should define an explicit signal arbitration contract with priority, veto behavior, and audit trace.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS1-005 - NTF vocabulary mismatch is visible at the contract boundary

Evidence:

- `NtfSide` defines `SUPPORT` and `RESISTANCE` (`src/uniquant/shared/interfaces.py:18-23`).
- `NTFAdapter` maps only `LONG` to BUY and `SHORT` to SELL, otherwise HOLD (`src/uniquant/signal/adapters.py:297-302`).

Impact:

- NTF outputs using institutional/support-resistance vocabulary may never become actionable signals.

Risk Level: P1

Recommendation:

- WS5 should standardize NTF side vocabulary and add adapter contract tests for `SUPPORT`, `RESISTANCE`, `LONG`, and `SHORT` compatibility or explicit rejection.

Migration Cost: Low

Priority: Sprint 2

### Finding WS1-006 - Engine factory rebinding is intentional but brittle

Evidence:

- `ServiceContainer` creates `AnalysisEngineFactory(orchestrator=data_svc)` before `AnalysisService` exists (`src/uniquant/services/service_container.py:93-100`).
- `AnalysisService.__init__()` calls `engine_factory.bind_orchestrator(self)` if the factory exists (`src/uniquant/services/analysis_service_v2.py:81-96`).
- `AnalysisEngineFactory.bind_orchestrator()` clears cached engines on orchestrator change (`src/uniquant/services/analysis/engine_factory.py:20-32`).

Impact:

- If any engine is accessed before rebinding, it can be initialized against the wrong orchestrator and then cleared.
- Current design is workable but must be tested as a lifecycle contract.

Risk Level: P1

Recommendation:

- Add or preserve tests proving no production path accesses factory engines before `AnalysisService` rebind, and that rebind clears stale engines.

Migration Cost: Low

Priority: Sprint 1

### Finding WS1-007 - Backtest execution imports data calendar directly

Evidence:

- `UnifiedBacktestEngine` imports `TradeCalendarManager` from the data layer (`src/uniquant/hands/backtest/unified_engine.py:39`) and creates one if none is injected (`src/uniquant/hands/backtest/unified_engine.py:98-112`).

Impact:

- Execution simulation depends directly on data-layer calendar implementation.
- This makes deterministic tests and future event-driven execution harder unless calendar is treated as an infrastructure contract.

Risk Level: P2

Recommendation:

- WS5 should extract a `TradingCalendarProtocol`; backtest can keep default construction but tests and orchestration should inject the protocol.

Migration Cost: Low

Priority: Sprint 2

### Finding WS1-008 - `shared` has a reverse dependency into `services`

Evidence:

- `src/uniquant/shared/di_container.py` is marked deprecated but still imports `ServiceContainer` from `..services.service_container` for backward compatibility (`src/uniquant/shared/di_container.py:1-14`).

Impact:

- `shared` is expected to be the bottom layer. A reverse dependency into `services` can create hidden import cycles and blur infrastructure vs application boundaries.

Risk Level: P1

Recommendation:

- WS5 should inspect `shared/di_container.py` and decide whether to move the lazy service proxy out of `shared` or document it as a compatibility shim with import smoke tests.

Migration Cost: Low to Medium

Priority: Sprint 2

### Finding WS1-009 - Two signal abstractions appear to coexist

Evidence:

- `TradingSignal` is defined in `shared/interfaces.py` and is used by `UnifiedResearchPipeline` and `UnifiedBacktestEngine` (`src/uniquant/shared/interfaces.py:127-169`; `src/uniquant/services/research_pipeline.py:24-28`; `src/uniquant/hands/backtest/unified_engine.py:35`).
- Separate signal package files exist: `signal/models.py`, `signal/normalizer.py`, `signal/aggregator.py`, `signal/db.py`.

Impact:

- The executable signal contract may diverge from the research signal model and persistence model.

Risk Level: P1

Recommendation:

- WS5 should produce a signal contract matrix identifying which signal type is canonical for research, storage, aggregation, and execution.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS1-010 - Production Broker layer is absent from the current architecture

Evidence:

- WS1 scan found simulation execution under `hands/backtest/*`, portfolio/risk services, and signal storage, but no current broker gateway or live order management source file.

Impact:

- The system should not be described as live automated trading ready.
- Order risk, broker recovery, OMS state reconciliation, HA, RPO/RTO, and disaster recovery remain blueprint topics.

Risk Level: P2 for current research scope; P0 if live trading is attempted.

Recommendation:

- Keep Broker, OMS, live execution, HA, and DR under WS13 Production Readiness Placeholder until source evidence and tests exist.

Migration Cost: High

Priority: Sprint 4

## 7. God Object / God Service Review

Current status:

- Historical comment in `AnalysisService` says it was reduced from a 1642-line God Object to a smaller orchestrator (`src/uniquant/services/analysis_service_v2.py:1-13`).
- Current `AnalysisService` still orchestrates data preparation, engine execution, defaults, precision compatibility, and decision dispatch (`src/uniquant/services/analysis_service_v2.py:65-320`).
- `DataService` is explicitly a facade and coordinates fetcher, storage, cleaner, cache, quality, stock query, and access service (`src/uniquant/services/data_service.py:35-91`).

Assessment:

- `AnalysisService` is no longer obviously a God Object, but it remains a high-centrality orchestrator.
- `DataService` is a facade by design; acceptable if downstream services own real responsibilities and the facade does not accumulate business rules.

Required follow-up:

- WS2 must verify `DataService` data lineage responsibilities.
- WS5 must verify interfaces between services rather than concrete service coupling.

## 8. Circular Dependency / Hidden Coupling Review

Confirmed:

- No direct source-level cycle was proven in this pass.
- The runtime composition root is acyclic in `ServiceContainer.initialize()`.

Potential hidden coupling:

| Coupling | Evidence | Risk |
|---|---|---|
| `data_pack` fields | Mutated and consumed across data, services, brain, signal, hands | P0 |
| Factory orchestrator rebind | Factory created with `DataService`, rebound to `AnalysisService` | P1 |
| Signal ordering | Collector append order controls first actionable signal in backtest | P1 |
| Shared -> services proxy | `shared/di_container.py` imports services (`src/uniquant/shared/di_container.py:12-14`) | P1 |
| Calendar in execution | Backtest constructs data-layer `TradeCalendarManager` by default | P2 |

Temporal coupling:

- `ServiceContainer.initialize()` must create services in the documented order (`src/uniquant/services/service_container.py:74-127`).
- `AnalysisEngineFactory` must be rebound before engine access (`src/uniquant/services/analysis/engine_factory.py:20-32`).
- `UnifiedBacktestEngine` requires signal timestamps to match historical K-line dates (`src/uniquant/hands/backtest/unified_engine.py:288-300`).

## 9. Target Architecture Direction

Near-term research-platform target:

```text
Data Platform
  -> ResearchDataPack schema
  -> Research Engines
  -> Signal Intent schema
  -> Signal Arbitration
  -> Portfolio/Position Sizing
  -> Simulated Execution
  -> BacktestResult + Experiment Trace
```

Future production-trading target:

```text
Research
  -> Signal
  -> Portfolio
  -> Execution Command
  -> Risk Gate
  -> Broker Adapter
  -> Order/Trade/Position Reconciliation
  -> Observability + Recovery
```

Research layer must not depend on execution implementation. Execution must consume typed intent/command objects, not raw engine dictionaries.

## 10. Next Workstreams

Immediate next artifacts:

1. `02_data_lineage_audit.md`
   - Trace `MarketData`, `DataFrame`, `Factor`, `Signal`, `TradingSignal`, `Order`, `Trade`, `Position`, `Portfolio`.
   - Identify `Any` and dict contract pollution.

2. `03_backtest_integrity_audit.md`
   - Verify `Signal(T) -> Execution(T+1)`.
   - Audit look-ahead, survivorship, selection, data snooping, corporate action, A-share constraints.

3. `04_historical_signal_series_blueprint.md`
   - Design the as-of signal generation runner that fixes one-shot timestamp behavior.

## 11. Verification Checklist

- [x] Mapped current modules to institutional target layers.
- [x] Marked Broker Layer as absent/deferred.
- [x] Produced architecture dependency graph.
- [x] Identified God Service candidates and high-centrality services.
- [x] Identified hidden coupling and temporal coupling.
- [x] Produced at least 10 risk/coupling findings with evidence, impact, risk, recommendation, migration cost, and priority.
- [x] Did not modify source code.
- [x] Did not run tests; this is a documentation/audit artifact pass.
