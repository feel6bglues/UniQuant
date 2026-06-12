# UniQuant Institutional Refactoring Protocol Work Plan

Generated: 2026-06-10 (All 15 workstreams complete; Sprints 0–4 finished)

Purpose: Convert the UniQuant Institutional Refactoring Protocol v3.0 into a complete, project-specific execution checklist for this repository.

Scope decision:

```text
Current execution target:
  Institutional quantitative research platform.

Current non-target:
  Live automated trading implementation.

Required treatment of live trading:
  Produce broker/live/HA/DR blueprints and gap reports only.
```

Evidence standard:

- Every conclusion must cite current source code, config, tests, generated analysis artifacts, or command output.
- If evidence is missing, mark `INSUFFICIENT EVIDENCE`.
- No refactoring or source modification is allowed until the relevant audit artifact, target contract, migration strategy, and test matrix exist.

## 1. Master Deliverable Checklist

| Protocol deliverable | UniQuant artifact | Status | Scope |
|---|---|---|---|
| 1. Current Architecture Report | `01_architecture_discovery.md` | Completed | Current |
| 2. Dependency Graph | `01_architecture_discovery.md` | Completed | Current |
| 3. Data Lineage Report | `02_data_lineage_audit.md` | Completed | Current |
| 4. Interface Contract Report | `05_interface_contract_audit.md` | Completed | Current |
| 5. Adapter Blueprint | `06_adapter_blueprint.md` | Completed | Current |
| 6. Backtest Integrity Report | `03_backtest_integrity_audit.md` | Completed | Current |
| 7. Matching Engine Audit | `03_backtest_integrity_audit.md` (included) | Completed | Current |
| 8. Historical Signal Series | `04_historical_signal_series_blueprint.md` | Completed | Current |
| 9. Risk Governance Matrix | `10_research_risk_governance.md` | Completed | Current + Deferred live |
| 10. Performance Autopsy | `08_performance_autopsy.md` | Completed | Current |
| 11. Event Architecture Audit | `12_event_architecture_blueprint.md` | Completed | Blueprint |
| 12. Configuration Governance Report | `09_configuration_governance.md` | Completed | Current |
| 13. Observability Blueprint | `11_observability_blueprint.md` | Completed | Current + Blueprint |
| 14. Production Readiness Report | `13_production_readiness_report.md` | Completed | Deferred live |
| 15. Target Architecture Blueprint | `14_tdd_refactoring_design.md` | Completed | Current + Blueprint |
| 16. Migration Strategy | `14_tdd_refactoring_design.md` | Completed | Current |
| 17. Test Matrix | `14_tdd_refactoring_design.md` | Completed | Current |
| 18. Refactoring Roadmap | `15_refactoring_roadmap.md` | Completed | Current |

Additional control artifacts created after the initial audit close:

| Control artifact | Purpose | Status |
|---|---|---|
| `FINDINGS_INDEX.md` | Maps consolidated P0/P1 issues and raw workstream findings to phases, status, and closure evidence | Completed |
| `IMPLEMENTATION_ENTRY_CRITERIA.md` | Defines gates required before implementation starts | Completed |

## 1.1 Closure Status

The detailed `[ ]` items below were the original execution checklist for each work package. They are retained as audit trail, but the authoritative current completion status is the artifact map in `index.md` and the consolidated summary in `99_final_institutional_audit_report.md`.

Optional closure checks requested after all workstreams:

| Closure item | Current status | Evidence |
|---|---|---|
| Import-direction / architecture contract test proposal | Covered as design, not implemented | `01_architecture_discovery.md` recommends architecture contract tests; `14_tdd_refactoring_design.md` and `15_refactoring_roadmap.md` place contract tests in Phase 1/2 |
| Signal arbitration test plan | Covered as design, not implemented | `06_adapter_blueprint.md`, `10_research_risk_governance.md`, `14_tdd_refactoring_design.md`, and `15_refactoring_roadmap.md` define `SignalArbitrator` tests and rollout gates |
| Final integration report | Completed | `99_final_institutional_audit_report.md` consolidates WS0-WS15, P0/P1 findings, scope boundaries, and roadmap |

These checks remain source-code work only if the project proceeds from audit/planning into implementation.

## 2. Execution Rules

- [ ] Start each work package by reading current source files listed in that package.
- [ ] Record all findings using `FINDING_TEMPLATE.md`.
- [ ] Separate evidence from inference.
- [ ] Separate research-platform requirements from live-trading requirements.
- [ ] Do not treat broker/order/HA/DR work as implemented unless source evidence exists.
- [ ] Do not use old migration docs as current truth unless verified against source.
- [ ] Do not modify source code during audit phases.
- [ ] Before any future code change, create or update tests first where practical.

## 3. Sprint Structure

### Sprint 0 - Protocol Control

Goal: Make the audit repeatable and evidence-bound.

Checklist:

- [x] Create institutional audit directory.
- [x] Create finding template.
- [x] Create institutional index.
- [x] Create master work plan.
- [x] Add consolidated final report shell after WS1-WS14 are complete.

Artifacts:

- `docs/analysis/institutional/FINDING_TEMPLATE.md`
- `docs/analysis/institutional/index.md`
- `docs/analysis/institutional/00_master_work_plan.md`
- ✅ `docs/analysis/institutional/99_final_institutional_audit_report.md`

Acceptance:

- Every workstream has a target artifact and verification gate.
- Every finding has evidence, impact, risk, recommendation, migration cost, priority, and verification.

## 4. Phase 1 - Architecture Discovery

Goal: Identify real topology, dependency direction, hidden coupling, circular dependency risk, and target institutional layer mapping.

Current UniQuant evidence entry points:

- `src/uniquant/services/service_container.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/analysis/engine_factory.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/shared/di_container.py`

Checklist:

- [x] Map current modules: `shared`, `data`, `brain`, `signal`, `hands`, `risk`, `services`, `ui`.
- [x] Overlay target layers: Research, Signal, Portfolio, Execution, Risk, Broker, Infrastructure.
- [x] Mark Broker as absent/deferred unless evidence appears.
- [x] Produce dependency graph.
- [x] Identify God Object/God Service candidates.
- [x] Identify hidden coupling and temporal coupling.
- [ ] Produce import-direction contract tests proposal.
- [ ] Decide whether `shared/di_container.py` remains a compatibility shim or moves out of `shared`.

Artifact:

- `docs/analysis/institutional/01_architecture_discovery.md`

Acceptance:

- At least 10 project-specific architecture findings.
- Broker layer status is explicit.
- No unsupported dependency claims.

## 5. Phase 2 - Data Lineage Audit

Goal: Trace core data objects by shape, contract, transformation, and consumer. Do not audit strategy logic here.

Objects:

- `MarketData`
- `DataFrame`
- `Factor`
- `Signal`
- `TradingSignal`
- `Order`
- `Trade`
- `Position`
- `Portfolio`

Current UniQuant evidence entry points:

- `src/uniquant/services/data_service.py`
- `src/uniquant/data/data_fetcher.py`
- `src/uniquant/data/lake/storage_manager.py`
- `src/uniquant/data/managers/source_router.py`
- `src/uniquant/data/pipeline/data_cleaner.py`
- `src/uniquant/data/pipeline/data_validator.py`
- `src/uniquant/data/pipeline/data_adjuster.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`

Checklist:

- [x] Trace raw source data to data lake.
- [x] Trace data lake read path to `DataService.fetch_for_brain()`.
- [x] Document `data_pack` producer fields: `stock`, `bench`, `etf`.
- [x] Document all `data_pack` mutation points in `AnalysisService`.
- [x] Trace factor inputs and factor output shapes.
- [x] Trace DecisionBrain output into `TradingSignalCollector`.
- [x] Trace `TradingSignal` into backtest pending orders and `TradeRecord`.
- [x] Trace `TradeRecord` into `BacktestResult`.
- [x] Trace portfolio objects in `portfolio_engine.py` and `portfolio_service.py`.
- [x] Identify `Any` pollution.
- [x] Identify `Dict[str, Any]` pollution.
- [x] Identify schema drift and implicit dict keys.
- [x] Mark missing schemas as `INSUFFICIENT EVIDENCE`.

Artifact:

- `docs/analysis/institutional/02_data_lineage_audit.md`

Acceptance:

- Source -> Transformation -> Consumer table for every core object.
- Contract break risks ranked P0/P1/P2.
- Clear recommendation for typed `ResearchDataPack` or equivalent schema.

## 6. Phase 3 - Interface Contract Audit

Goal: Extract current explicit and implicit interfaces, then classify contract violations.

Current UniQuant evidence entry points:

- `src/uniquant/shared/interfaces.py`
- `src/uniquant/data/sources/base.py`
- `src/uniquant/data/sources/protocols.py`
- `src/uniquant/data/managers/standard_adapter.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/signal/models.py`
- `src/uniquant/signal/normalizer.py`
- `src/uniquant/hands/backtest/engine.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/services/analysis/*.py`

Checklist:

- [ ] Extract all `Protocol` definitions.
- [ ] Extract all `ABC` and abstract methods.
- [ ] Extract service constructor contracts.
- [ ] Extract `TradingSignal` contract.
- [ ] Compare `TradingSignal` with `signal.models.Signal`.
- [ ] Audit `MarketSignalContext` usage vs raw dict usage.
- [ ] Identify fat interfaces.
- [ ] Identify LSP violations.
- [ ] Identify ISP violations.
- [ ] Identify hidden service dependencies.
- [ ] Define current interface matrix.
- [ ] Define target interface matrix.

Artifact:

- `docs/analysis/institutional/05_interface_contract_audit.md`

Acceptance:

- Contract matrix includes Research, Signal, Portfolio, Execution, Risk, Data, Infrastructure.
- Every contract violation has a migration path and test type.

## 7. Phase 4 - Adapter Analysis

Goal: Find and design missing adapters between research outputs and executable research/backtest objects.

Current UniQuant evidence entry points:

- `src/uniquant/signal/adapters.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/risk/sizer.py`
- `src/uniquant/services/portfolio_service.py`

Checklist:

- [ ] Map Brain outputs to `TradingSignal`.
- [ ] Audit adapter input keys and output actions.
- [ ] Audit NTF vocabulary mismatch: `SUPPORT/RESISTANCE` vs `LONG/SHORT`.
- [ ] Audit signal conflict behavior across LPPL/CZSC/Wyckoff/FSM/Regime/NTF/Alpha/MA.
- [ ] Design `SignalAdapter` target contract.
- [ ] Design `SignalArbitrator` or equivalent veto/priority layer.
- [ ] Design `PortfolioAdapter` target contract.
- [ ] Design `ExecutionAdapter` target contract for simulated execution.
- [ ] Keep Research layer independent from Execution implementation.
- [ ] Define adapter contract tests.

Artifact:

- `docs/analysis/institutional/06_adapter_blueprint.md`

Acceptance:

- Brain -> Signal -> Portfolio -> Execution boundaries are explicit.
- Risk veto and HOLD semantics cannot be bypassed by lower-priority BUY signals.
- Dependency Inversion Principle is satisfied in the target design.

## 8. Phase 5 - Backtest Integrity Audit

Goal: Identify every research backtest cheating risk.

Current UniQuant evidence entry points:

- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/hands/backtest/engine.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/walk_forward_pipeline.py`
- `src/uniquant/data/pipeline/data_adjuster.py`
- `tests/test_lookahead_bias.py`
- `tests/test_t1_constraint_boundary.py`
- `tests/test_unified_matching.py`

Checklist:

- [x] Verify `Signal(T) -> Execution(T+1)` in unified engine.
- [x] Verify same-bar execution is impossible or explicitly marked.
- [x] Audit one-shot `pd.Timestamp.now()` signal timestamp issue.
- [x] Audit factor forward-return calculation.
- [x] Audit live-mode vs research-mode separation.
- [x] Audit walk-forward train/validation/test boundaries.
- [x] Audit survivorship bias: delisted/suspended/ST stocks.
- [x] Audit selection bias: future-known universe risk.
- [x] Audit data snooping controls.
- [x] Audit corporate action handling: dividends, splits, rights issues, adjustment factors.
- [x] Audit cost, slippage, T+1, limit-up/down, suspension, lot size.
- [x] Document implemented controls vs missing controls.

Artifact:

- `docs/analysis/institutional/03_backtest_integrity_audit.md`

Acceptance:

- Backtest integrity report includes every bias class.
- Each bias has evidence status, impact, risk, recommendation, migration cost, priority.

## 9. Phase 6 - Matching Engine Audit (Completed: included in WS3)

Goal: Audit simulated execution realism and A-share constraints.

Current UniQuant evidence entry points:

- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/shared/limit_checker.py`

Checklist:

- [x] Verify limit-up buy rejection.
- [x] Verify limit-down sell rejection.
- [x] Verify one-word board handling where applicable.
- [x] Verify suspension and `volume=0` rejection in both single-symbol and vectorized paths.
- [x] Verify volume/liquidity constraints.
- [x] Verify partial-fill support or explicitly mark absent.
- [x] Verify lot-size rounding.
- [x] Verify commission, stamp duty, transfer fee, and slippage consistency.
- [x] Compare `UnifiedBacktestEngine` vs `UnifiedMatchingEngine` behavior.
- [x] Define unification plan if behavior diverges.

Artifact options:

- Append to `03_backtest_integrity_audit.md`, or create `03b_matching_engine_audit.md`.

Acceptance:

- Single-symbol and vectorized execution differences are documented.
- A-share matching constraints have test coverage recommendations.

## 10. Phase 7 - Risk Governance Audit

Goal: Build research-platform risk governance now and live-trading risk blueprint later.

Current UniQuant evidence entry points:

- `src/uniquant/risk/sizer.py`
- `src/uniquant/risk/drawdown_analyzer.py`
- `src/uniquant/risk/evt_risk.py`
- `src/uniquant/risk/historical_risk.py`
- `src/uniquant/risk/portfolio_optimizer.py`
- `src/uniquant/risk/structural.py`
- `src/uniquant/brain/fsm/fsm.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/services/portfolio_service.py`

Checklist:

- [ ] Audit position sizing authority.
- [ ] Identify where `default_shares` bypasses risk sizing.
- [ ] Audit single-name concentration controls.
- [ ] Audit industry concentration controls.
- [ ] Audit leverage controls.
- [ ] Audit drawdown limits.
- [ ] Audit risk veto propagation into signal arbitration.
- [ ] Audit duplicate signal/order prevention for research simulation.
- [ ] Mark live order risk as deferred unless evidence exists.
- [ ] Produce research risk governance matrix.
- [ ] Produce deferred live risk governance matrix for OMS/broker/order recovery.

Artifact:

- `docs/analysis/institutional/10_research_risk_governance.md`

Acceptance:

- Risk controls cannot be bypassed in the target design.
- Live order risk is not mixed with current research scope.

## 11. Phase 8 - Performance Autopsy

Goal: Identify CPU, memory, vectorization, complexity, and latency risks.

Current UniQuant evidence entry points:

- `src/uniquant/brain/`
- `src/uniquant/data/`
- `src/uniquant/hands/backtest/`
- `src/uniquant/services/`
- `src/uniquant/shared/perf.py`
- Performance-sensitive search patterns: `for`, `apply(`, `iterrows`, `concat`, `merge`, `copy(`, `deepcopy`, nested loops.

Checklist:

- [ ] Scan CPU hotspots.
- [ ] Scan memory explosion risks.
- [ ] Score vectorization usage for Pandas/NumPy/Polars.
- [ ] Estimate complexity for top paths.
- [ ] Audit factor computation performance.
- [ ] Audit backtest/matching performance.
- [ ] Audit data loading and cache performance.
- [ ] Define latency budgets for research path, scan path, signal generation, and simulated execution.
- [ ] Separate research throughput from live latency.

Artifact:

- `docs/analysis/institutional/08_performance_autopsy.md`

Acceptance:

- Top CPU/memory risks are ranked with exact file/function evidence.
- Performance recommendations include benchmark or profiling verification.

## 12. Phase 9 - Event Driven Audit

Goal: Determine how UniQuant should evolve toward unified Research/Backtest/Paper/Live event architecture.

Current UniQuant evidence entry points:

- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/service_container.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/signal/db.py`
- `src/uniquant/services/scan_service.py`
- `src/uniquant/ui/dashboard.py`

Checklist:

- [ ] Identify current command-style APIs.
- [ ] Identify current query-style APIs.
- [ ] Identify event-like records: signal, trade, result, health, report.
- [ ] Identify synchronous coupling.
- [ ] Identify async/event gaps.
- [ ] Define target event types: `MarketDataEvent`, `SignalEvent`, `PortfolioTargetEvent`, `OrderIntentEvent`, `FillEvent`, `RiskEvent`, `ExperimentEvent`.
- [ ] Define event store or audit log requirements.
- [ ] Define migration plan from function-call pipeline to event-compatible pipeline.
- [ ] Keep event architecture as blueprint unless user requests implementation.

Artifact:

- `docs/analysis/institutional/12_event_architecture_blueprint.md`

Acceptance:

- Target event model supports research, backtest, paper trading, and live trading without forcing current live implementation.

## 13. Phase 10 - Configuration Governance

Goal: Identify magic numbers, hardcoded paths, hardcoded symbols, hardcoded brokers, and secrets/config boundaries.

Current UniQuant evidence entry points:

- `config/config.yaml`
- `pyproject.toml`
- `src/uniquant/shared/config_loader.py`
- `src/uniquant/shared/constants/`
- `src/uniquant/shared/env_config.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/hands/backtest/*.py`

Checklist:

- [ ] Scan hardcoded paths.
- [ ] Scan hardcoded symbols such as benchmark/index defaults.
- [ ] Scan magic numbers in risk, signals, adapters, matching, costs, data windows.
- [ ] Scan hardcoded data source names.
- [ ] Scan secrets or credential handling.
- [ ] Define Environment Layer.
- [ ] Define Config Layer.
- [ ] Define Secrets Layer.
- [ ] Define test config and deterministic research config.
- [ ] Define migration plan for constants into config where appropriate.

Artifact:

- `docs/analysis/institutional/09_configuration_governance.md`

Acceptance:

- Config governance report distinguishes constants, runtime config, environment variables, and secrets.

## 14. Phase 11 - Observability Audit

Goal: Create an OpenTelemetry-compatible observability blueprint for research lineage and future production.

Current UniQuant evidence entry points:

- `src/uniquant/shared/logger_factory.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/health_service.py`
- `src/uniquant/services/data_quality_service.py`
- `src/uniquant/signal/db.py`
- `src/uniquant/hands/backtest/result.py`

Checklist:

- [ ] Audit current logging structure.
- [ ] Audit trace id propagation.
- [ ] Audit experiment id availability.
- [ ] Audit signal -> order -> trade traceability in backtest.
- [ ] Define metrics: PnL, drawdown, fill rate, rejection rate, latency, data quality, cache hit rate.
- [ ] Define traces: data load, engine run, decision, signal collection, risk gate, matching, result.
- [ ] Define OpenTelemetry-compatible span names and attributes.
- [ ] Define local research audit trail before production observability.

Artifact:

- `docs/analysis/institutional/11_observability_blueprint.md`

Acceptance:

- A result can be traced from data snapshot to signal to simulated trade to report in the target design.

## 15. Phase 12 - Production Readiness Review

Goal: Score production readiness honestly without implying live trading is currently supported.

Current UniQuant evidence entry points:

- `src/uniquant/services/health_service.py`
- `src/uniquant/services/service_container.py`
- `src/uniquant/data/sources/`
- `src/uniquant/shared/retry_decorator.py`
- `src/uniquant/shared/error_handling.py`
- `config/config.yaml`

Checklist:

- [ ] Verify live broker layer evidence.
- [ ] If absent, mark Broker as `INSUFFICIENT EVIDENCE`.
- [ ] Audit data feed failure handling.
- [ ] Audit cache/storage failure handling.
- [ ] Audit crash recovery evidence.
- [ ] Audit position recovery evidence.
- [ ] Audit order recovery evidence.
- [ ] Audit HA evidence.
- [ ] Audit RPO/RTO evidence.
- [ ] Score production readiness separately from research readiness.

Artifact:

- `docs/analysis/institutional/13_production_readiness_report.md`

Acceptance:

- Production readiness score is evidence-bound.
- Missing live components are not treated as implementation tasks unless user changes scope.

## 16. Phase 13 - TDD Refactoring Design

Goal: Produce target architecture, target contracts, migration strategy, test matrix, and roadmap before coding.

Inputs:

- All WS1-WS13 artifacts.
- Existing test suite under `tests/`.
- Current P0/P1 findings.

Checklist:

- [ ] Define Target Architecture.
- [ ] Define Target Contracts.
- [ ] Define Migration Strategy.
- [ ] Define Test Matrix.
- [ ] Define Refactoring Roadmap.
- [ ] Define rollback plan for each migration step.
- [ ] Define compatibility shims.
- [ ] Define feature flags or config gates if needed.
- [ ] Define measurable exit criteria per sprint.

Required test matrix:

- [ ] Unit tests.
- [ ] Integration tests.
- [ ] Contract tests.
- [ ] Simulation tests.
- [ ] Backtest tests.
- [ ] Performance tests.
- [ ] Data lineage/schema tests.
- [ ] Bias prevention tests.
- [ ] Observability trace tests.

Artifacts:

- `docs/analysis/institutional/14_tdd_refactoring_design.md`
- `docs/analysis/institutional/15_refactoring_roadmap.md`

Acceptance:

- No source code refactor starts until this phase is complete.
- Every P0/P1 change has tests and rollback path.

## 17. Project-Specific P0 Execution Queue

These are the highest-priority project findings already visible from current analysis.

| Priority | Work item | Why it matters | Required artifact before code |
|---|---|---|---|
| P0-1 | `data_pack` schema and lineage | Mutable dict crosses data, analysis, signal, and backtest layers. | `02_data_lineage_audit.md`, `05_interface_contract_audit.md` |
| P0-2 | Historical signal series | Current pipeline uses `pd.Timestamp.now()` for signal timestamps. | `04_historical_signal_series_blueprint.md`, `14_tdd_refactoring_design.md` |
| P0-3 | Backtest integrity audit | Research platform credibility depends on bias controls. | `03_backtest_integrity_audit.md` |
| P0-4 | Signal arbitration and risk veto | Multiple adapters can emit conflicting signals. | `06_adapter_blueprint.md`, `10_research_risk_governance.md` |
| P0-5 | Factor admission governance | Auto/mined factors require IC/OOS/PBO/cost-aware gates. | `07_factor_admission_governance.md` |

## 18. Recommended Sprint Roadmap

### Sprint 1 - Trustworthy Research Baseline

- [x] Complete WS2 Data Lineage Audit.
- [x] Complete WS3 Backtest Integrity Audit.
- [x] Complete WS4 Historical Signal Series Blueprint.
- [x] Define initial schema for `ResearchDataPack` (in WS2 §7).
- [ ] Define tests required for timestamp correctness and no same-bar execution (deferred to WS14).

Exit:

- Research results can be judged for data-contract and backtest-integrity risk.

### Sprint 2 - Contract and Risk Discipline

- [x] Complete WS5 Interface Contract Audit.
- [x] Complete WS6 Adapter Blueprint.
- [x] Complete WS7 Factor Admission Governance.
- [x] Complete WS10 Research Risk Governance.
- [ ] Define signal arbitration and risk veto tests.

Exit:

- Brain outputs, signals, portfolio sizing, and simulated execution have target contracts.

### Sprint 3 - Platform Engineering Maturity

- [x] Complete WS8 Performance Autopsy.
- [x] Complete WS9 Configuration Governance.
- [x] Complete WS11 Observability Blueprint.
- [x] Complete WS12 Event Architecture Blueprint.

Exit:

- Scaling, reproducibility, configuration, tracing, and event migration risks are ranked.

### Sprint 4 - Refactoring Design and Production Gap Report

- [x] Complete WS13 Production Readiness Report.
- [x] Complete WS14 TDD Refactoring Design.
- [x] Complete WS15 Refactoring Roadmap.
- [x] Create final consolidated institutional audit report.

Exit:

- The project has a complete production-grade refactoring design without pretending live trading is already implemented.

## 19. Commands To Support The Audit

Use these as evidence-gathering commands. Do not treat output as current unless run in the active working tree.

```bash
git status --short
rg --files src/uniquant tests config docs/analysis
rg -n "class .*Service|class .*Engine|class .*Pipeline|Protocol|ABC|abstractmethod" src/uniquant
rg -n "Dict\\[str, Any\\]|dict\\[str, Any\\]|Any|data_pack" src/uniquant
rg -n "pd\\.Timestamp\\.now\\(|datetime\\.now\\(|date\\.today\\(" src/uniquant
rg -n "iterrows|apply\\(|concat\\(|merge\\(|copy\\(|deepcopy|for .* in" src/uniquant
rg -n "broker|order|OMS|gateway|live|paper|account|position|fill" src/uniquant tests config
rg -n "lookahead|look-ahead|survivorship|delist|suspend|ST|adjust|qfq|hfq|split|dividend" src/uniquant tests config
```

## 20. Definition Of Done

The super prompt is fully implemented for UniQuant when:

- [x] All 18 final deliverables exist.
- [x] Every finding has Evidence, Impact, Risk Level, Recommendation, Migration Cost, Priority, and Verification.
- [ ] Every `INSUFFICIENT EVIDENCE` item is either closed by evidence or explicitly accepted as a known gap.
- [x] Research-platform scope and live-trading scope remain separate.
- [x] P0/P1 recommendations have tests or verification plans.
- [x] Target architecture and target contracts are documented.
- [x] Migration strategy is staged, rollback-aware, and deployable.
- [x] Final roadmap is ordered by research trustworthiness first, production trading later.
