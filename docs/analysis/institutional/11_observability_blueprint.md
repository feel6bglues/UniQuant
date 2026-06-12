# WS11 - Observability Blueprint

Generated: 2026-06-10

Scope: logging, metrics, tracing, run lineage, signal-to-trade observability, performance telemetry, and OpenTelemetry-compatible target design for the research-platform-first UniQuant scope.

## 1. Evidence Base

Inspected:

- `src/uniquant/shared/logger_factory.py`
- `src/uniquant/shared/perf.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/signal/models.py`
- `src/uniquant/signal/db.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/result.py`
- `src/uniquant/services/health_service.py`
- `pyproject.toml`

Commands used:

```text
rg -n "logging|get_logger|logger\.|metrics|trace|tracing|OpenTelemetry|otel|perf_section|perf_report|PipelineResult|metadata|Signal|Order|Trade|BacktestResult|report_id|run_id|correlation|uuid|json" src/uniquant config tests
rg -n "opentelemetry|prometheus|structlog|python-json-logger|loguru|metrics|trace_id|span_id|run_id" pyproject.toml src/uniquant tests
```

## 2. Current Observability Map

```text
Logging
 ├── shared/logger_factory.py
 │    ├── stdlib logging
 │    ├── root logger setup
 │    ├── stdout handler
 │    ├── RotatingFileHandler
 │    └── QueueHandler / QueueListener
 └── many modules call get_logger(...)

Performance
 └── shared/perf.py
      ├── perf_section(name)
      ├── perf_report()
      ├── perf_reset()
      └── gated by UNIQUANT_PERF

Tracing
 ├── research_pipeline.PipelineResult.trace_id
 ├── UnifiedResearchPipeline.run(trace_id=...)
 └── AnalysisService._attach_trace_id(data_pack, trace_id)

Metrics
 ├── HealthService.get_system_health()
 ├── HealthService._get_system_metrics()
 ├── SignalDatabase.get_statistics()
 ├── backtest result metrics
 └── risk/portfolio metrics in service outputs

Signal persistence
 └── signal/db.py
      ├── SignalRecord
      ├── metadata_json
      ├── parent_id
      └── source/type statistics
```

## 3. Current Status

| Area | Current status | Assessment |
|---|---|---|
| Module logging | Present | Broadly available |
| Async file logging | Present | Queue-based file handler |
| Structured JSON logs | Not found | Gap |
| Trace ID | Partial | Pipeline and analysis only |
| Span model | Not found | Gap |
| Metrics registry/export | Not found | Gap |
| Health endpoint data | Present | Internal dict, not exported standard |
| Perf counters | Present | Not integrated into production paths |
| Signal persistence | Present | Useful base for lineage |
| Order/trade lineage IDs | Not found | Gap |
| OpenTelemetry dependency | Not found | Gap |
| Prometheus dependency/exporter | Not found | Gap |

## 4. Findings

### Finding WS11-001 - Logging exists but is not structured or context-bound (P1)

Evidence:
- `src/uniquant/shared/logger_factory.py:49-64` loads logging level, format, directory, size, backup count, console, and file settings.
- `src/uniquant/shared/logger_factory.py:66-115` installs stdout and queue-backed rotating file handlers.
- `src/uniquant/shared/logger_factory.py:30` default format is a plain text string: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`.
- No JSON formatter, trace context filter, or structured logging adapter was found.

Impact:
- Logs cannot be reliably joined by `trace_id`, symbol, engine, signal ID, or config hash.
- Batch research failures across 5000 symbols are hard to aggregate.
- WS8 performance findings cannot be correlated to specific engines or run profiles.

Risk Level: P1

Recommendation:
- Add a `StructuredLogger` compatibility layer over stdlib logging.
- Add contextual fields: `trace_id`, `run_id`, `symbol`, `stage`, `engine`, `bar_time`, `config_hash`, and `analysis_mode`.
- Keep plain text as default for local compatibility; enable JSON logs through WS9 `observability.structured_logs`.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Unit test: log records include trace and symbol when context is set.
- Snapshot test: JSON log event is valid JSON and contains required institutional fields.
- Compatibility test: existing `get_logger()` callers still work.

### Finding WS11-002 - Trace ID starts in pipeline but does not cover signal/order/trade lineage (P1)

Evidence:
- `src/uniquant/services/research_pipeline.py:37-50` defines `PipelineResult.trace_id`.
- `src/uniquant/services/research_pipeline.py:95-115` accepts or creates a `trace_id` and passes it to `AnalysisService.run_ticker_analysis()`.
- `src/uniquant/services/analysis_service_v2.py:235-239` attaches `trace_id` to `data_pack` and `engine_status_meta`.
- `src/uniquant/shared/interfaces.py:127-142` `TradingSignal` has action, reason, confidence, shares, symbol, price, timestamp, but no `trace_id`, `signal_id`, `parent_id`, or `source`.
- `src/uniquant/hands/backtest/unified_engine.py:48-62` `TradeRecord` has trade fields but no `trace_id`, `order_id`, `signal_id`, or `decision_id`.

Impact:
- The platform cannot reconstruct `Data -> Engine -> CandidateSignal -> Decision -> TradingSignal -> Order -> Trade`.
- Risk vetoes and arbitration outcomes from WS6/WS10 would not be auditable end to end.
- Backtest fills cannot be traced back to the originating evidence and config snapshot.

Risk Level: P1

Recommendation:
- Introduce a lineage envelope:

```text
RunContext(run_id, trace_id, config_hash, analysis_mode, symbol, as_of)
EngineSpan(engine, start_ns, end_ns, status, error)
SignalLineage(signal_id, parent_ids, source, evidence_refs)
OrderLineage(order_id, signal_id, decision_id, risk_decision_id)
TradeLineage(trade_id, order_id, execution_bar, fill_reason)
```

- Add lineage fields to new WS6 adapter/arbitrator outputs before changing legacy `TradingSignal`.

Migration Cost: Medium

Priority: Sprint 3 / WS14

Verification:
- Contract test: every trade in a backtest can be traced to one signal or an explicit synthetic/manual source.
- Replay test: given `trade_id`, recover source engine, signal timestamp, execution timestamp, and config hash.

### Finding WS11-003 - `shared/perf.py` is usable but not connected to run artifacts (P2)

Evidence:
- `src/uniquant/shared/perf.py:9` gates instrumentation with `UNIQUANT_PERF`.
- `src/uniquant/shared/perf.py:15-24` implements `perf_section(name)`.
- `src/uniquant/shared/perf.py:27-35` returns calls, total ms, and average microseconds.
- WS8 found zero production usages of `perf_section()`.
- `src/uniquant/services/research_pipeline.py:37-50` `PipelineResult` does not include metadata or perf report.

Impact:
- Performance measurements are available only if manually wired.
- Institutional performance regressions cannot be compared across runs.
- Latency budget from WS8 cannot be enforced.

Risk Level: P2

Recommendation:
- Add `perf_section()` around pipeline stages and engine entry points.
- Attach `perf_report()` to `PipelineResult.metadata.observability.perf`.
- Normalize `UNIQUANT_PERF` into WS9 effective config.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: when instrumentation is enabled, `PipelineResult` includes per-stage call counts and durations.
- Benchmark test: Wyckoff, LPPL, signal collection, and backtest latency are emitted under stable metric names.

### Finding WS11-004 - Metrics are scattered dicts, not a governed metric catalog (P1)

Evidence:
- `src/uniquant/services/health_service.py:49-87` returns a health dict with `components`, `metrics`, and `recommendations`.
- `src/uniquant/services/health_service.py:290-306` provides system metrics such as uptime, health history size, config count, and cache size.
- `src/uniquant/signal/db.py:263-296` returns signal statistics by source/type and average confidence.
- `src/uniquant/hands/backtest/result.py:36-62` contains backtest and risk metric fields.
- No central metric registry, naming convention, exporter, or metric dimensions were found.

Impact:
- Dashboard, research reports, and future batch jobs can use inconsistent metric names.
- Metrics cannot be scraped or compared across runs without bespoke adapters.
- Alerting and regression thresholds cannot be standardized.

Risk Level: P1

Recommendation:
- Define a metric catalog with stable names and dimensions.
- Keep dict outputs as compatibility payloads but emit normalized metrics through a central `MetricsSink`.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Unit test: every emitted metric name is registered.
- Static review: no new ad hoc metric names in pipeline and backtest paths.
- Snapshot test: one pipeline run emits the required metrics set.

### Finding WS11-005 - Health service is useful but mixes checks, probes, and recommendations (P2)

Evidence:
- `src/uniquant/services/health_service.py:49-87` runs config, data, analysis, brain, risk, cache, data lake, and system checks.
- `src/uniquant/services/health_service.py:119-141` data health fetches real test data for stock `601339`.
- `src/uniquant/services/health_service.py:166-198` brain health runs `fetch_for_brain()` and `DecisionBrain.make_decision()`.
- `src/uniquant/services/health_service.py:322-360` creates recommendations based on config/data/cache/system state.

Impact:
- Health checks may be expensive and data-dependent.
- Readiness/liveness semantics are unclear.
- Batch observability should separate cheap liveness checks from expensive research probes.

Risk Level: P2

Recommendation:
- Split health checks:

```text
liveness: process and config loaded
readiness: required data/cache paths available
research_probe: optional synthetic or controlled-symbol end-to-end check
diagnostics: recommendations and expensive checks
```

Migration Cost: Medium

Priority: Sprint 3 / WS13

Verification:
- Unit test: liveness does not perform network/data fetch.
- Integration test: research probe is explicitly opt-in and has timeout budget.

### Finding WS11-006 - Signal persistence has lineage primitives but no run context (P2)

Evidence:
- `src/uniquant/signal/models.py:96-127` `Signal` includes `id`, `metadata`, and `parent_id`.
- `src/uniquant/signal/db.py:40-56` persists `id`, `symbol`, `source`, `timestamp`, `metadata_json`, and `parent_id`.
- `src/uniquant/signal/db.py:120-151` saves individual and batch signals.
- No `run_id`, `trace_id`, `config_hash`, `engine_version`, or `analysis_mode` fields were found in the signal model or database schema.

Impact:
- Persisted signals cannot be grouped by research run without relying on optional metadata conventions.
- Signal quality analysis cannot reliably compare different config versions or admission gates.
- Historical signal replay from WS4 lacks a durable lineage key.

Risk Level: P2

Recommendation:
- Add run context to signal metadata first, then consider schema columns after compatibility migration.
- Required signal lineage metadata:

```text
run_id
trace_id
config_hash
analysis_mode
engine_name
engine_version
bar_time
data_hash
```

Migration Cost: Medium

Priority: Sprint 3 / Sprint 4

Verification:
- Unit test: saved signal round-trips lineage metadata.
- Query test: retrieve all signals by `run_id` using metadata or future indexed column.

### Finding WS11-007 - Backtest result models diverge in metadata support (P1)

Evidence:
- `src/uniquant/hands/backtest/unified_engine.py:64-72` defines a local `BacktestResult` without metadata fields.
- `src/uniquant/hands/backtest/result.py:36-62` defines another `BacktestResult` with `metadata`.
- WS5 already identified BacktestResult unification as a contract issue.

Impact:
- Unified engine results cannot carry observability payloads without changing the local result model.
- Backtest integrity metadata, config hash, risk metrics, and perf report can be lost depending on engine path.
- WS11 cannot be closed until the canonical result type supports observability fields.

Risk Level: P1

Recommendation:
- Use one canonical `BacktestResult` with:

```text
metadata.observability
metadata.backtest_integrity
metadata.config_hash
metadata.lineage
metadata.risk
```

- Preserve old local fields through adapters until migration completes.

Migration Cost: Medium

Priority: Sprint 3 / WS14

Verification:
- Contract test: unified engine result includes metadata without breaking existing total_return/total_trades properties.
- Regression test: legacy report generation still works.

### Finding WS11-008 - OpenTelemetry compatibility is absent (P2)

Evidence:
- Search in `pyproject.toml`, `src/uniquant`, and `tests` found no `opentelemetry` dependency or API usage.
- Search found no `prometheus` dependency or exporter.
- `pyproject.toml:21` includes `loguru`, but current core logging path uses stdlib `logging` through `shared/logger_factory.py`.

Impact:
- Current observability is local-process only.
- Future production or distributed batch execution would require retrofitting tracing/metrics exporters.
- Institutional review cannot claim OTel compatibility today.

Risk Level: P2

Recommendation:
- Do not require OpenTelemetry runtime immediately.
- Design OTel-compatible names and context fields now.
- Add an optional exporter interface:

```text
TelemetrySink
 ├── InMemoryTelemetrySink
 ├── JsonlTelemetrySink
 └── OpenTelemetryTelemetrySink
```

Migration Cost: Medium

Priority: Sprint 4 unless needed for batch operations earlier

Verification:
- Unit test: telemetry events serialize to an OTel-compatible shape.
- Optional dependency test: OTel exporter is skipped when package is absent.

### Finding WS11-009 - Error observability lacks a structured failure taxonomy (P2)

Evidence:
- `src/uniquant/services/analysis_service_v2.py:228-233` records engine status and errors into `data_pack`.
- `src/uniquant/services/analysis_service_v2.py:256-278` returns failure results for missing data, engine failure, or decision failure.
- Many modules log errors with plain strings.
- No central error code taxonomy was found for data, engine, contract, risk, backtest, or observability failures.

Impact:
- Batch research cannot reliably summarize failure classes.
- Triage depends on parsing text logs.
- Risk governance needs structured veto/error reasons.

Risk Level: P2

Recommendation:
- Add stable failure categories:

```text
DATA_MISSING
DATA_SCHEMA_INVALID
ENGINE_EXCEPTION
CONTRACT_VIOLATION
RISK_VETO
BACKTEST_REJECTED_FILL
CONFIG_INVALID
PERF_BUDGET_EXCEEDED
```

Migration Cost: Low

Priority: Sprint 3 / WS14

Verification:
- Unit test: pipeline failure results carry a machine-readable error code.
- Batch scan test: failure summary groups by error code.

## 5. Target Observability Architecture

```text
RunContext
 ├── run_id
 ├── trace_id
 ├── config_hash
 ├── analysis_mode
 ├── symbol
 ├── benchmark_symbol
 ├── as_of
 └── feature_flags

Telemetry API
 ├── log_event(event_name, fields)
 ├── record_metric(name, value, dimensions)
 ├── start_span(name, attributes)
 └── attach_artifact(name, uri/hash)

Telemetry Sinks
 ├── InMemoryTelemetrySink        # tests
 ├── JsonlTelemetrySink           # local research
 ├── MetricsSnapshotSink          # report metadata
 └── OpenTelemetryTelemetrySink   # optional future exporter

Lineage
 ├── DataSnapshot
 ├── EngineSpan
 ├── CandidateSignal
 ├── ArbitrationReport
 ├── DecisionOutput
 ├── TradingSignal
 ├── OrderIntent
 ├── FillDecision
 └── TradeRecord
```

## 6. Target Trace Graph

```text
research.run
 ├── data.fetch_for_brain
 │    ├── data.load_stock
 │    ├── data.load_benchmark
 │    └── data.load_etf
 ├── engine.regime
 ├── engine.lppl
 ├── engine.ntf
 ├── engine.czsc
 ├── engine.wyckoff
 ├── engine.alpha
 ├── decision.make
 ├── signal.collect
 ├── signal.arbitrate
 │    └── risk.veto_or_size
 └── backtest.run
      ├── order.accept_or_reject
      ├── fill.execute_or_reject
      └── metrics.compute
```

## 7. Metric Catalog

### Research and pipeline metrics

| Metric | Type | Dimensions |
|---|---|---|
| `uniquant.pipeline.run.count` | counter | `status`, `analysis_mode` |
| `uniquant.pipeline.duration_ms` | histogram | `symbol`, `analysis_mode` |
| `uniquant.pipeline.error.count` | counter | `error_code`, `stage` |
| `uniquant.data.rows` | gauge | `symbol`, `data_type` |
| `uniquant.data.staleness_days` | gauge | `symbol`, `data_type` |

### Engine metrics

| Metric | Type | Dimensions |
|---|---|---|
| `uniquant.engine.duration_ms` | histogram | `engine`, `symbol`, `status` |
| `uniquant.engine.error.count` | counter | `engine`, `error_code` |
| `uniquant.engine.cache.hit.count` | counter | `engine` |
| `uniquant.engine.cache.miss.count` | counter | `engine` |

### Signal and risk metrics

| Metric | Type | Dimensions |
|---|---|---|
| `uniquant.signal.candidate.count` | counter | `source`, `action` |
| `uniquant.signal.final.count` | counter | `action` |
| `uniquant.signal.arbitration.veto.count` | counter | `reason` |
| `uniquant.risk.position_size.shares` | gauge | `symbol`, `method` |
| `uniquant.risk.drawdown.current` | gauge | `symbol` |

### Backtest metrics

| Metric | Type | Dimensions |
|---|---|---|
| `uniquant.backtest.trade.count` | counter | `symbol`, `action` |
| `uniquant.backtest.fill.reject.count` | counter | `reason` |
| `uniquant.backtest.total_return` | gauge | `symbol`, `strategy` |
| `uniquant.backtest.max_drawdown` | gauge | `symbol`, `strategy` |
| `uniquant.backtest.sharpe` | gauge | `symbol`, `strategy` |

### Performance metrics

| Metric | Type | Dimensions |
|---|---|---|
| `uniquant.perf.section.calls` | counter | `section` |
| `uniquant.perf.section.total_ms` | gauge | `section` |
| `uniquant.perf.section.avg_us` | gauge | `section` |
| `uniquant.batch.symbols_per_second` | gauge | `profile` |
| `uniquant.batch.memory_mb` | gauge | `profile` |

## 8. Required Event Fields

Every structured event should include:

```text
timestamp
level
event_name
trace_id
run_id
symbol
stage
config_hash
analysis_mode
message
```

Stage-specific fields:

```text
engine_name
signal_id
candidate_signal_id
arbitration_id
decision_id
order_id
trade_id
bar_time
execution_bar_time
error_code
latency_ms
```

## 9. Migration Plan

### Step 1 - Context and JSON events

- Add `RunContext` and contextual logging helpers.
- Keep existing logger API working.
- Add optional JSONL sink controlled by WS9 config.

### Step 2 - Perf integration

- Add `perf_section()` around pipeline, engine, signal collection, arbitration, and backtest stages.
- Attach `perf_report()` to result metadata.

### Step 3 - Lineage fields

- Add lineage metadata to CandidateSignal and arbitration outputs first.
- Add compatibility metadata to `TradingSignal` conversion without breaking existing call sites.
- Add trade/order lineage to canonical backtest result.

### Step 4 - Metrics sink

- Add metric catalog and in-memory sink.
- Export metrics snapshot into research result metadata.
- Defer Prometheus/OTel exporter until optional dependency is justified.

### Step 5 - OTel-compatible exporter

- Add optional exporter behind `observability.otlp_enabled`.
- Keep JSONL as the default research artifact format.

## 10. Test Matrix

| Test | Purpose | Priority |
|---|---|---|
| Structured log snapshot | Validate JSON event fields | P1 |
| Trace propagation | Ensure trace ID crosses data, engine, signal, backtest | P1 |
| Trade lineage replay | Resolve trade -> order -> signal -> engine -> data snapshot | P1 |
| Perf report metadata | Attach latency sections to pipeline output | P2 |
| Metric catalog validation | Reject unregistered metric names | P1 |
| Health liveness/readiness split | Prevent expensive liveness checks | P2 |
| Signal persistence lineage | Round-trip run metadata through signal DB | P2 |
| Backtest metadata contract | Canonical BacktestResult carries observability payload | P1 |
| OTel optional import | Exporter disabled cleanly when package absent | P2 |
| Redaction test | Config/secrets are redacted in logs and telemetry | P1 |

## 11. WS11 Handoff

WS11 feeds:

- WS12 Event Architecture: event names, command/query boundaries, and trace graph.
- WS13 Production Readiness: liveness/readiness/diagnostics split and telemetry export gaps.
- WS14 TDD Refactoring Design: `RunContext`, metric catalog, lineage contracts, and metadata tests.

Current WS11 status:

```text
Logging audit: complete
Metrics audit: complete
Tracing audit: complete
Signal-to-trade lineage gap: complete
OpenTelemetry compatibility blueprint: complete
Metric catalog: complete
Test matrix: complete
```
