# Institutional Research Audit Work Breakdown

Generated: 2026-06-09

Basis: UniQuant Institutional Refactoring Protocol v3.0, adapted for the current goal: an institutional-grade quantitative research platform, not live automated trading.

## 1. Scope Decision

The full protocol covers:

```text
Architecture Review
Production-Grade Refactoring Design
Risk Governance Validation
Performance Engineering
Event Architecture
Observability
Production Readiness
```

For UniQuant's current research-platform target, split it into two tracks:

```text
Track A - Institutional Research Platform Review
  Required now.

Track B - Production Trading Readiness Blueprint
  Deferred. Produce architecture placeholders only.
```

## 2. Evidence Standard

Every finding must include:

| Field | Meaning |
|---|---|
| Evidence | File, class, function, config, test, or command output. |
| Impact | What research, backtest, data, risk, or maintainability outcome is affected. |
| Risk Level | P0, P1, P2, or Info. |
| Recommendation | Specific action, not generic advice. |
| Migration Cost | Low, Medium, High. |
| Priority | Execution order. |

If evidence is missing, mark:

```text
INSUFFICIENT EVIDENCE
```

No unsupported claims.

## 3. Workstream Overview

| Workstream | Protocol Source | Current Scope | Priority |
|---|---|---|---|
| WS0 Protocol Control | Final deliverable governance | Define audit rules and artifact structure. | P0 |
| WS1 Architecture Discovery | Phase 1 | Discover current research architecture and dependency graph. | P0 |
| WS2 Data Lineage Audit | Phase 2 | Trace market data, DataFrames, factors, signals, trades, positions. | P0 |
| WS3 Backtest Integrity Audit | Phase 5 | Verify research backtest realism and bias controls. | P0 |
| WS4 Historical Signal Series | Added from UniQuant findings | Convert one-shot signal collection into historical signal generation. | P0 |
| WS5 Interface Contract Audit | Phase 3 | Audit protocols, ABCs, base classes, implicit dict contracts. | P1 |
| WS6 Adapter Blueprint | Phase 4 | Design Brain -> Signal -> Portfolio -> Backtest adapters. | P1 |
| WS7 Factor Admission Governance | Derived from Phase 2/5/13 | Institutionalize IC/OOS/PBO/cost-aware factor admission. | P1 |
| WS8 Performance Autopsy | Phase 8 | CPU, memory, vectorization, complexity, latency budget. | P1 |
| WS9 Configuration Governance | Phase 10 | Magic numbers, hardcoded symbols, config/secrets layering. | P1 |
| WS10 Risk Governance Research Scope | Phase 7 | Research/backtest risk governance, not broker/order risk. | P1 |
| WS11 Observability Blueprint | Phase 11 | Trace research experiment lineage and signal-to-trade audit trail. | P2 |
| WS12 Event Architecture Blueprint | Phase 9 | Design future event-driven architecture. | P2 |
| WS13 Production Readiness Placeholder | Phase 12 | Document live-trading gaps without implementing. | P2 |
| WS14 TDD Refactoring Design | Phase 13 | Target contracts, migration strategy, test matrix, roadmap. | P0/P1 |

## 4. P0 Work Breakdown

### WS0 - Protocol Control

Goal: Make the institutional audit process repeatable.

Tasks:

1. Create audit artifact directory.
2. Define finding template.
3. Define risk levels and migration cost scale.
4. Define final report index.

Deliverables:

- `docs/analysis/09_institutional_research_audit_workbreakdown.md`
- `docs/analysis/institutional/FINDING_TEMPLATE.md`
- `docs/analysis/institutional/index.md`

Acceptance:

- Every later report can use the same finding format.
- The audit distinguishes research-platform requirements from live-trading requirements.

### WS1 - Architecture Discovery

Goal: Establish current module topology and dependency direction.

Tasks:

1. Map current modules:
   - `shared`
   - `data`
   - `brain`
   - `signal`
   - `hands`
   - `risk`
   - `services`
   - `ui`
2. Overlay institutional target layers:
   - Research
   - Signal
   - Portfolio
   - Execution
   - Risk
   - Broker
   - Infrastructure
3. Identify missing or deferred layers.
4. Identify god services, hidden coupling, temporal coupling, circular dependencies.

Evidence sources:

- `src/uniquant/`
- `src/uniquant/services/service_container.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/shared/interfaces.py`

Deliverable:

- `docs/analysis/institutional/01_architecture_discovery.md`

Acceptance:

- Contains dependency graph.
- Clearly marks Broker Layer as deferred or absent.
- Identifies at least top 10 high-risk coupling points.

### WS2 - Data Lineage Audit

Goal: Trace data contracts and transformations without discussing strategy logic.

Objects to trace:

```text
MarketData
DataFrame
Factor
Signal
TradingSignal
Order
Trade
Position
Portfolio
```

Tasks:

1. Trace data from source to `data_pack`.
2. Trace `data_pack` fields into DecisionBrain.
3. Trace factors into composite score.
4. Trace Brain outputs into `TradingSignal`.
5. Trace `TradingSignal` into backtest trades.
6. Identify `Dict[str, Any]` pollution, `Any` pollution, schema drift, and implicit contracts.

Evidence sources:

- `src/uniquant/services/data_service.py`
- `src/uniquant/data/`
- `src/uniquant/brain/factors/`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`

Deliverable:

- `docs/analysis/institutional/02_data_lineage_audit.md`

Acceptance:

- Includes source -> transformation -> consumer tables.
- Identifies every major dict contract.
- Marks missing schema evidence as `INSUFFICIENT EVIDENCE`.

### WS3 - Backtest Integrity Audit

Goal: Identify all research backtest cheating risks.

Tasks:

1. Verify signal bar vs execution bar.
2. Audit look-ahead risk in factors, signals, and backtest.
3. Audit survivorship bias.
4. Audit selection bias from stock pools.
5. Audit data snooping boundaries.
6. Audit corporate action handling.
7. Audit trading constraints:
   - T+1
   - limit-up/down
   - suspension
   - costs
   - slippage
   - lot size

Evidence sources:

- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/walk_forward_pipeline.py`
- `src/uniquant/data/pipeline/data_adjuster.py`
- tests under `tests/test_unified_matching.py`, `tests/test_t1_constraint_boundary.py`, `tests/test_lookahead_bias.py`

Deliverable:

- `docs/analysis/institutional/03_backtest_integrity_audit.md`

Acceptance:

- Explicitly states whether `Signal(T) -> Execution(T+1)` is preserved.
- Lists all known bias classes and evidence status.
- Separates implemented controls from missing controls.

### WS4 - Historical Signal Series

Goal: Fix the research platform's most important validation gap: historical signal generation.

Tasks:

1. Design historical as-of signal generation.
2. Define `HistoricalSignalRunner` contract.
3. Define daily signal output schema.
4. Define integration with `UnifiedBacktestEngine`.
5. Define tests for timestamp correctness.

Target schema:

```text
date
symbol
action
confidence
shares
price
reason
source_policy
trace_id
```

Deliverables:

- `docs/analysis/institutional/04_historical_signal_series_blueprint.md`
- Contract proposal for `HistoricalSignalRunner`
- Test plan

Acceptance:

- No historical backtest depends on `pd.Timestamp.now()`.
- Signals are generated as-of each date.
- Final signal count and trade count are reproducible.

### WS14A - Refactoring Design Seed

Goal: Convert P0 findings into a refactoring design, without modifying code yet.

Tasks:

1. Define target research pipeline architecture.
2. Define target contracts:
   - Data contract
   - Analysis result contract
   - Signal intent contract
   - Historical signal contract
   - Backtest input contract
3. Define migration sequence.
4. Define test matrix.

Deliverable:

- `docs/analysis/institutional/14_tdd_refactoring_design.md` (原计划 `14a_research_refactoring_seed.md` 内容合并至此)

Acceptance:

- Migration can be executed sprint-by-sprint.
- Each contract has unit and integration test requirements.

## 5. P1 Work Breakdown

### WS5 - Interface Contract Audit

Goal: Extract and judge all protocols, ABCs, base classes, and implicit interfaces.

Tasks:

1. Inventory:
   - `Protocol`
   - `ABC`
   - base strategy classes
   - service interfaces
   - implicit dict contracts
2. Check ISP and LSP violations.
3. Identify fat interfaces and hidden dependencies.
4. Propose target contracts.

Deliverable:

- `docs/analysis/institutional/05_interface_contract_audit.md`

Acceptance:

- Contains current interface matrix.
- Contains contract violation report.
- Every proposed contract has owner layer and consumer layer.

### WS6 - Adapter Blueprint

Goal: Repair conceptual breaks between Research, Signal, Portfolio, and Backtest.

Tasks:

1. Audit current Brain -> TradingSignal adapters.
2. Identify missing adapter layers:
   - `SignalAdapter`
   - `PortfolioAdapter`
   - `ExecutionAdapter`
3. Design dependency inversion:
   - Research must not depend on Execution.
   - Signal must not encode portfolio state.
   - Backtest must consume executable signals/orders only.

Deliverable:

- `docs/analysis/institutional/06_adapter_blueprint.md`

Acceptance:

- Includes current missing adapter report.
- Includes target adapter blueprint.
- Defines final executable signal policy.

### WS7 - Factor Admission Governance

Goal: Turn factor scripts into institutional research governance.

Tasks:

1. Define factor metadata contract.
2. Define required no-lookahead tests.
3. Define IC/IR, OOS, walk-forward, PBO gates.
4. Define report template.
5. Define cost-aware factor portfolio test.

Deliverables:

- `docs/analysis/institutional/07_factor_admission_governance.md`
- `docs/templates/factor_admission_report.md` (计划模板文件，尚未创建)

Acceptance:

- Candidate factor can pass or fail through a deterministic workflow.
- All gates are reproducible from config.

### WS8 - Performance Autopsy

Goal: Identify research platform CPU, memory, vectorization, and complexity risks.

Tasks:

1. Search for:
   - `iterrows`
   - `apply`
   - nested loops
   - `copy`
   - `deepcopy`
   - `concat`
   - `merge`
2. Classify hotspots by layer.
3. Estimate complexity:
   - per symbol
   - per date
   - per factor
   - per universe
4. Identify memory explosion risks.
5. Assign vectorization score.

Deliverable:

- `docs/analysis/institutional/08_performance_autopsy.md`

Acceptance:

- Contains CPU hotspot table.
- Contains memory explosion report.
- Contains vectorization score by module.
- Contains top 10 optimization candidates.

### WS9 - Configuration Governance

Goal: Make research experiments reproducible and configurable.

Tasks:

1. Audit magic numbers.
2. Audit hardcoded symbols and dates.
3. Audit config ownership:
   - environment
   - research config
   - runtime config
   - secrets placeholder
4. Define experiment config schema.

Deliverable:

- `docs/analysis/institutional/09_configuration_governance.md`

Acceptance:

- Identifies hardcoded symbols/paths.
- Defines config layering.
- Defines experiment snapshot requirement.

### WS10 - Risk Governance Research Scope

Goal: Define risk governance for offline research and backtesting.

Tasks:

1. Audit `PositionSizer`.
2. Audit risk vetoes in DecisionBrain.
3. Audit whether non-FSM signals bypass sizing.
4. Audit portfolio risk tools.
5. Define research risk governance matrix.

Deliverable:

- `docs/analysis/institutional/10_research_risk_governance.md`

Acceptance:

- Separates research risk from broker/order risk.
- Defines which risk checks are required before research backtest.

## 6. P2 Work Breakdown

### WS11 - Observability Blueprint

Goal: Design traceability for research experiments.

Tasks:

1. Define trace id propagation:
   - data load
   - analysis
   - signal
   - backtest
   - report
2. Define structured logs.
3. Define research metrics:
   - data freshness
   - signal count
   - trade count
   - fill rate
   - drawdown
   - IC/OOS metrics
4. Define OpenTelemetry-compatible future shape.

Deliverable:

- `docs/analysis/institutional/11_observability_blueprint.md`

Acceptance:

- Every research output can be tied back to config, data, and code path.

### WS12 - Event Architecture Blueprint

Goal: Design future unification across research, backtest, paper, and live.

Tasks:

1. Identify current synchronous service calls.
2. Define target events:
   - `MarketDataLoaded`
   - `AnalysisCompleted`
   - `SignalGenerated`
   - `OrderSimulated`
   - `TradeFilled`
   - `RiskCheckFailed`
3. Define command/query split.
4. Define migration plan.

Deliverable:

- `docs/analysis/institutional/12_event_architecture_blueprint.md`

Acceptance:

- Clearly marks event-driven architecture as future blueprint, not current implementation.

### WS13 - Production Readiness Placeholder

Goal: Preserve live-trading requirements without making them current scope.

Tasks:

1. Document absent broker layer.
2. Document absent OMS/order state machine.
3. Document absent position reconciliation.
4. Document absent HA/DR/RPO/RTO.
5. Define future production readiness checklist.

Deliverable:

- `docs/analysis/institutional/13_production_readiness_report.md`

Acceptance:

- Every missing live feature is marked `DEFERRED`.
- No research-platform deliverable is blocked by broker automation.

## 7. Final Deliverable Mapping

| v3.0 Final Deliverable | UniQuant Research Adaptation |
|---|---|
| Current Architecture Report | WS1 |
| Dependency Graph | WS1 |
| Data Lineage Report | WS2 |
| Interface Contract Report | WS5 |
| Adapter Blueprint | WS6 |
| Backtest Integrity Report | WS3 |
| Matching Engine Audit | WS3 plus Stage 6 existing artifact |
| Risk Governance Matrix | WS10 |
| Performance Autopsy | WS8 |
| Event Architecture Audit | WS12 |
| Configuration Governance Report | WS9 |
| Observability Blueprint | WS11 |
| Production Readiness Report | WS13 placeholder |
| Target Architecture Blueprint | WS14A |
| Migration Strategy | WS14A |
| Test Matrix | WS14A |
| Refactoring Roadmap | WS14A |

## 8. Suggested Execution Order

```text
Sprint 1:
  WS0 Protocol Control
  WS1 Architecture Discovery
  WS2 Data Lineage Audit

Sprint 2:
  WS3 Backtest Integrity Audit
  WS4 Historical Signal Series Design
  WS14A Refactoring Design Seed

Sprint 3:
  WS5 Interface Contract Audit
  WS6 Adapter Blueprint
  WS9 Configuration Governance

Sprint 4:
  WS7 Factor Admission Governance
  WS8 Performance Autopsy
  WS10 Risk Governance Research Scope

Sprint 5:
  WS11 Observability Blueprint
  WS12 Event Architecture Blueprint
  WS13 Production Readiness Placeholder
```

## 9. Immediate Next Task

Start with WS0 and WS1.

Concrete next files to create:

```text
docs/analysis/institutional/index.md
docs/analysis/institutional/FINDING_TEMPLATE.md
docs/analysis/institutional/01_architecture_discovery.md
```

Immediate audit commands:

```bash
git status --short
rg --files src/uniquant
rg -n "class .*Service|class .*Engine|Protocol|ABC|Dict\\[str, Any\\]|Any" src/uniquant
rg -n "iterrows|apply\\(|concat\\(|merge\\(|copy\\(|deepcopy" src/uniquant
```

No source code should be modified during these audit workstreams unless a later implementation phase explicitly requests it.
