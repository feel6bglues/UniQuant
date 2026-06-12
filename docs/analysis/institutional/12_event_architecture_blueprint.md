# WS12 - Event Architecture Blueprint

Generated: 2026-06-10

Scope: current orchestration style, event/command/query boundaries, synchronous and asynchronous coupling, migration path for unifying research, backtest, batch scan, paper trading, and future live trading without prematurely rewriting the platform.

## 1. Evidence Base

Inspected:

- `src/uniquant/services/service_container.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/services/scan_service.py`
- `src/uniquant/data/managers/source_router.py`
- `src/uniquant/data/data_fetcher.py`
- `src/uniquant/data/sources/realtime_bridge.py`

Commands used:

```text
rg -n "class .*Event|Event\(|Command|Query|Queue|queue|publish|subscribe|dispatch|handler|orchestrat|pipeline|ServiceContainer|initialize|DAG|dependency|run_batch|scan|async|await|ThreadPool|ProcessPool|Parallel|delayed|TradingSignalCollector|UnifiedResearchPipeline|BacktestEngine|DataService|AnalysisService" src/uniquant tests config
rg -n "Event|Command|Query|publish|subscribe|dispatch|Queue|asyncio|RealtimeBridge|TickData" src/uniquant/data/sources/realtime_bridge.py src/uniquant
```

## 2. Current Event Architecture

Current core flow is synchronous orchestration:

```text
ServiceContainer.initialize()
 └── UnifiedResearchPipeline.run(symbol)
      ├── AnalysisService.run_ticker_analysis(symbol)
      │    ├── DataService.fetch_for_brain(symbol)
      │    ├── AnalysisEngineFactory engines
      │    └── DecisionBrain
      ├── TradingSignalCollector.collect(data_pack)
      └── UnifiedBacktestEngine.run(df, signals)
```

Current batch scan flow is also synchronous:

```text
ScanPipeline.run()
 ├── load_data()
 ├── build_factors()
 ├── analyze_factors()
 ├── compose_scores()
 └── generate_report()
```

Current realtime callback island:

```text
RealtimeBridge
 ├── async connect loop
 ├── async tick loop
 ├── subscribe(symbol, callback)
 ├── on_tick(callback)
 └── callback(tick)
```

No unified event bus, command bus, query bus, event store, or durable event envelope was found.

## 3. Current Suitability

| Mode | Current suitability | Reason |
|---|---|---|
| Research | Good | Synchronous run is simple and debuggable |
| Backtest | Good for single-symbol | Unified engine consumes typed signals |
| Historical signal generation | Partial | WS4 needs event-like bar lineage |
| Batch scan | Partial | Sequential orchestration is expensive |
| Paper trading | Not ready | No command/event boundary for order lifecycle |
| Live trading | Deferred | Broker/OMS absent in current scope |

## 4. Findings

### Finding WS12-001 - No explicit Event/Command/Query model exists (P1)

Evidence:
- Search found no core `Event`, `Command`, `Query`, `EventBus`, `CommandBus`, or `QueryBus` abstraction in current source.
- `src/uniquant/services/research_pipeline.py:95-173` directly invokes analysis, signal collection, and backtest.
- `src/uniquant/services/scan_service.py:470-516` directly invokes load, factor build, factor analysis, score composition, and report generation.

Impact:
- Research runs are reproducible only through direct call outputs, not through a durable event stream.
- It is difficult to replay only one stage, compare decisions, or audit state transitions.
- Paper/live trading cannot share a governed lifecycle with research/backtest without adding boundaries later.

Risk Level: P1

Recommendation:
- Define event contracts first; keep execution synchronous initially.
- Add event emission at stage boundaries without changing behavior.

Migration Cost: Medium

Priority: Sprint 3 / WS14

Verification:
- Contract test: `RunResearchCommand` produces ordered stage events in synchronous mode.
- Replay test: emitted events reconstruct run status and key outputs.

### Finding WS12-002 - ServiceContainer is a useful DAG, not an event architecture (P2)

Evidence:
- `src/uniquant/services/service_container.py:1-17` documents a DAG topology.
- `src/uniquant/services/service_container.py:74-127` constructs and registers storage, calendar, cache, data service, engine factory, market cache, analysis service, backtest engine, signal collector, and research pipeline.
- `ServiceContainer` exposes `register`, `register_factory`, and `get`, but no publish/subscribe or command dispatch interface.

Impact:
- Dependency construction is disciplined, but runtime interactions remain tightly orchestrated by direct method calls.
- Event migration should build on this container instead of replacing it.

Risk Level: P2

Recommendation:
- Register an `EventRecorder` and optional `CommandDispatcher` in `ServiceContainer`.
- Keep service construction as-is; inject event recorder into pipeline and engines through constructors.

Migration Cost: Low

Priority: Sprint 3 / WS14

Verification:
- Unit test: container initializes with `event_recorder` when feature flag is enabled.
- Regression test: container initializes unchanged when event recording is disabled.

### Finding WS12-003 - Research pipeline has clear stage boundaries but no stage events (P1)

Evidence:
- `src/uniquant/services/research_pipeline.py:114-157` has explicit steps: analysis, signal collection, and backtest.
- `src/uniquant/services/research_pipeline.py:112` creates or accepts `trace_id`.
- `src/uniquant/services/research_pipeline.py:159-163` logs final summary but does not emit machine-readable stage events.

Impact:
- This is the highest-ROI place to add event capture.
- Without events, WS11 lineage remains metadata-only and not a replayable timeline.

Risk Level: P1

Recommendation:
- Emit stage events:

```text
ResearchRunStarted
DataPackPrepared
EngineAnalysisCompleted
DecisionProduced
SignalsCollected
BacktestCompleted
ResearchRunCompleted
ResearchRunFailed
```

- Include `trace_id`, `run_id`, `symbol`, `stage`, `config_hash`, and timing fields.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: successful run emits ordered stage events.
- Unit test: failure in analysis emits `ResearchRunFailed` with error code.

### Finding WS12-004 - TradingSignalCollector is collection, not an event boundary (P1)

Evidence:
- `src/uniquant/signal/adapters.py:434-525` iterates over LPPL, CZSC, Wyckoff, FSM, Regime, NTF, AlphaScore, and MA status outputs, appending `TradingSignal` objects.
- WS6 identified the need for `CandidateSignal`, `SignalArbitrator`, and `ArbitrationReport`.
- The current collector does not emit candidate-created, candidate-rejected, arbitration, or risk-veto events.

Impact:
- Signal conflicts and veto decisions cannot be audited as a sequence.
- Risk governance from WS10 cannot prove why a BUY/SELL/HOLD emerged.

Risk Level: P1

Recommendation:
- Treat adapters as event-producing boundaries:

```text
CandidateSignalCreated
CandidateSignalRejected
SignalConflictDetected
RiskVetoApplied
SignalArbitrated
TradingSignalIssued
```

- Keep `TradingSignalCollector.collect()` as compatibility wrapper while adding WS6 arbitrator path behind a feature flag.

Migration Cost: Medium

Priority: Sprint 3 / Sprint 4

Verification:
- Contract test: every candidate has source, reason, confidence, timestamp, and trace ID.
- Arbitration test: veto events precede final signal event.

### Finding WS12-005 - Backtest engine has implicit order/fill events but drops them after execution (P1)

Evidence:
- `src/uniquant/hands/backtest/unified_engine.py:155` uses an in-memory `pending_order` dict.
- `src/uniquant/hands/backtest/unified_engine.py:173-230` executes or rejects pending order logic for T+1, suspension, BUY, and SELL.
- `src/uniquant/hands/backtest/unified_engine.py:241-258` creates pending orders from day signals.
- Only executed trades are returned in `BacktestResult`; rejected fills and pending order decisions are not captured as structured records.

Impact:
- Matching-engine audit cannot fully reconstruct why a signal did not trade.
- Risk and liquidity constraints need explicit rejection events.
- Future paper/live migration needs an order lifecycle before broker integration.

Risk Level: P1

Recommendation:
- Add order/fill event records:

```text
OrderIntentCreated
OrderAccepted
OrderRejected
FillAttempted
FillRejected
TradeFilled
PositionUpdated
EquityUpdated
```

- Attach the event list to canonical `BacktestResult.metadata.events` first.

Migration Cost: Medium

Priority: Sprint 3 / WS14

Verification:
- Backtest test: suspended bar emits `FillRejected(reason=SUSPENDED)` and no trade.
- Backtest test: successful fill links `trade_id -> order_id -> signal_id`.

### Finding WS12-006 - Batch scan is a pipeline, not a job/event system (P2)

Evidence:
- `src/uniquant/services/scan_service.py:112-143` loads data in one stage.
- `src/uniquant/services/scan_service.py:145-185` builds factors.
- `src/uniquant/services/scan_service.py:207-244` analyzes factors.
- `src/uniquant/services/scan_service.py:246-284` composes scores.
- `src/uniquant/services/scan_service.py:470-516` runs the full flow and returns a summary dict.
- WS8 identified scan service single-threaded behavior as a performance issue for 5000 symbols.

Impact:
- Long scans lack resumable job state.
- Failures in one stage can require rerunning prior expensive stages.
- Progress reporting and partial results are hard to standardize.

Risk Level: P2

Recommendation:
- Introduce scan job events:

```text
ScanJobStarted
DataLoadProgress
FactorBuildProgress
FactorAnalysisCompleted
ScoreCompositionCompleted
ReportGenerated
ScanJobCompleted
ScanJobFailed
```

- Keep execution synchronous until job state, config hash, and artifact paths are captured.

Migration Cost: Medium

Priority: Sprint 3 / Sprint 4

Verification:
- Unit test: scan run emits progress events even in lightweight mode.
- Resume design review: stage artifacts can be reloaded from event metadata.

### Finding WS12-007 - RealtimeBridge is callback-driven and isolated from research/backtest contracts (P2)

Evidence:
- `src/uniquant/data/sources/realtime_bridge.py:37-53` defines `TickData`.
- `src/uniquant/data/sources/realtime_bridge.py:101-127` defines async data-source methods.
- `src/uniquant/data/sources/realtime_bridge.py:172-204` stores callback lists and an event loop/thread.
- `src/uniquant/data/sources/realtime_bridge.py:305-329` polls ticks and directly invokes callbacks.
- No integration was found with `UnifiedResearchPipeline`, `TradingSignalCollector`, or `UnifiedBacktestEngine`.

Impact:
- The realtime path cannot be used to prove unified research/backtest/paper/live semantics.
- Callback errors are logged, but tick events are not durable or traceable.
- Live readiness remains deferred.

Risk Level: P2

Recommendation:
- Treat `RealtimeBridge` as a future event source adapter, not the core event bus.
- Convert ticks to `MarketDataReceived` events at the boundary.
- Do not connect it to trading actions until WS13/production scope.

Migration Cost: Medium

Priority: WS13 or later

Verification:
- Unit test: tick callback can be adapted into `MarketDataReceived` event.
- Scope test: research platform default config keeps realtime disabled.

### Finding WS12-008 - Data source concurrency is local and not governed by event backpressure (P2)

Evidence:
- `src/uniquant/data/managers/source_router.py:100-110` uses `ThreadPoolExecutor(max_workers=1)` for fetch timeout control.
- `src/uniquant/data/managers/source_router.py:142-164` races healthy data-source adapters in a thread pool.
- `src/uniquant/data/data_fetcher.py:191-209` uses `ThreadPoolExecutor` for multi-symbol daily fetch.
- No queue, backpressure, cancellation, or event-level retry policy was found.

Impact:
- Concurrency behavior is implementation-local.
- Batch mode can grow in complexity without a shared job control model.
- Future async migration would risk mixing threads, callbacks, and event loops without a single policy.

Risk Level: P2

Recommendation:
- Keep local concurrency for now.
- Add event records for fetch attempts, retries, failures, and selected source.
- Later introduce a bounded job queue only for batch scan or data ingestion.

Migration Cost: Medium

Priority: Sprint 4

Verification:
- Unit test: fetch failure emits data-source failure event with source name and retry count.
- Batch test: configured worker limits are reflected in job metadata.

### Finding WS12-009 - Event migration must not imply live trading readiness (P1)

Evidence:
- Current architecture includes research, signal, risk, hands/backtest, services, and UI layers.
- No live broker/OMS integration was found in the inspected orchestration path.
- RealtimeBridge exists but is a data callback bridge, not a broker/execution lifecycle.

Impact:
- A generic event-driven architecture could be misread as production-trading readiness.
- Live trading needs broker state reconciliation, idempotency, order state machines, kill switches, and recovery that are out of current implementation scope.

Risk Level: P1

Recommendation:
- Scope WS12 as research/backtest event recording and migration blueprint.
- Mark broker/live execution events as target contracts only.
- Defer live execution commands to WS13 production readiness.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Documentation review: event blueprint clearly labels live trading events as deferred.
- Config test: live/paper event handlers are disabled by default.

## 5. Target Command/Event/Query Model

### Commands

Commands request work and should be idempotent where possible.

```text
RunResearchCommand
GenerateHistoricalSignalsCommand
RunBacktestCommand
RunBatchScanCommand
RunFactorAdmissionCommand
RunRiskReviewCommand
```

Deferred production commands:

```text
SubmitOrderCommand
CancelOrderCommand
SyncBrokerStateCommand
TriggerKillSwitchCommand
```

### Events

Events state what happened.

```text
ResearchRunStarted
DataPackPrepared
DataValidationFailed
EngineStarted
EngineCompleted
EngineFailed
CandidateSignalCreated
SignalConflictDetected
RiskVetoApplied
SignalArbitrated
TradingSignalIssued
OrderIntentCreated
OrderRejected
FillAttempted
FillRejected
TradeFilled
PositionUpdated
BacktestCompleted
ResearchRunCompleted
ResearchRunFailed
```

Batch/factor events:

```text
ScanJobStarted
ScanProgressUpdated
FactorComputed
FactorAdmissionEvaluated
FactorQuarantined
ReportGenerated
ScanJobCompleted
```

Deferred production events:

```text
BrokerConnected
BrokerDisconnected
OrderSubmitted
OrderAcceptedByBroker
OrderRejectedByBroker
OrderPartiallyFilled
OrderFilled
OrderCancelled
BrokerStateReconciled
KillSwitchActivated
```

### Queries

Queries return state without changing it.

```text
GetRunStatusQuery
GetRunEventsQuery
GetDataSnapshotQuery
GetSignalLineageQuery
GetBacktestResultQuery
GetFactorAdmissionReportQuery
GetRiskStateQuery
```

Deferred production queries:

```text
GetBrokerPositionsQuery
GetOpenOrdersQuery
GetExecutionLatencyQuery
```

## 6. Event Envelope

Every event should use one envelope:

```text
event_id
event_type
event_version
occurred_at
run_id
trace_id
correlation_id
causation_id
symbol
stage
source_component
config_hash
analysis_mode
payload
```

Rules:

- `correlation_id` groups a full research/backtest run.
- `causation_id` points to the command or prior event that caused the event.
- Payloads must be schema-versioned.
- Events must be append-only.
- Research/backtest events can be stored as JSONL artifacts before any database/event-store work.

## 7. Target Research Event Flow

```text
RunResearchCommand
 ↓
ResearchRunStarted
 ↓
DataPackPrepared
 ↓
EngineStarted / EngineCompleted per engine
 ↓
DecisionProduced
 ↓
CandidateSignalCreated per source
 ↓
SignalArbitrated
 ↓
TradingSignalIssued
 ↓
OrderIntentCreated
 ↓
FillAttempted
 ↓
TradeFilled or FillRejected
 ↓
BacktestCompleted
 ↓
ResearchRunCompleted
```

## 8. Migration Plan

### Step 1 - Event recording sidecar

- Add an in-memory and JSONL `EventRecorder`.
- Inject it into `UnifiedResearchPipeline` behind a default-off WS9 feature flag.
- Emit events without changing control flow.

### Step 2 - Stage boundary events

- Add events for data, engine, decision, signal, arbitration, and backtest boundaries.
- Attach event artifact path and event count to `PipelineResult.metadata`.

### Step 3 - Lineage integration

- Align event IDs with WS11 lineage fields.
- Add `signal_id`, `order_id`, and `trade_id` to payloads.

### Step 4 - Command dispatcher

- Wrap top-level entry points with command handlers.
- Keep handlers synchronous initially:

```text
RunResearchCommandHandler.handle(command) -> PipelineResult
RunBacktestCommandHandler.handle(command) -> BacktestResult
RunBatchScanCommandHandler.handle(command) -> ScanResult
```

### Step 5 - Optional async/job mode

- Only after events and commands are stable, add bounded job execution for batch scan and historical signal generation.
- Do not use event-driven execution for live trading until WS13 gaps are closed.

## 9. Test Matrix

| Test | Purpose | Priority |
|---|---|---|
| Event envelope schema | Validate required event fields | P1 |
| Research event order | Ensure deterministic sequence in sync mode | P1 |
| Failure event path | Emit failed event with error code and stage | P1 |
| Signal lineage event path | Candidate -> arbitration -> final signal | P1 |
| Backtest fill rejection events | Capture non-trade reasons | P1 |
| JSONL event artifact | Persist append-only run timeline | P1 |
| Command idempotency | Re-running command with same ID is controlled | P2 |
| Query read model | Reconstruct run status from events | P2 |
| Realtime bridge adapter | Convert tick to `MarketDataReceived` event without trading | P2 |
| Live scope guard | Broker commands disabled by default | P1 |

## 10. WS12 Handoff

WS12 feeds:

- WS11 Observability: event envelope becomes trace/log/metric correlation base.
- WS13 Production Readiness: broker/live events remain deferred gap contracts.
- WS14 TDD Refactoring Design: event recorder, command handlers, event schema tests, and staged rollout flags.

Current WS12 status:

```text
Current event architecture: complete
Command/Event/Query boundaries: complete
Synchronous coupling audit: complete
Async/callback audit: complete
Event-driven migration plan: complete
Test matrix: complete
Live scope boundary: complete
```
