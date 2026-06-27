# Institutional Research Audit Index

Generated: 2026-06-10 (All Workstreams Complete — Sprints 0–4 Finished)

Update 2026-06-12: A closure-review work plan has been added for post-implementation status reconciliation. Use `16_institutional_closure_review_plan.md` before rerunning any full institutional audit.

Basis: `docs/ANALYSIS_PROMPT_PLAYBOOK.md`, `docs/analysis/09_institutional_research_audit_workbreakdown.md`, and the user's UniQuant Institutional Refactoring Protocol v3.0.

## Mission

Build an evidence-bound institutional architecture review process for UniQuant as a quantitative research platform first.

Current scope:

```text
Institutional Research Platform Review
Architecture Discovery
Data Lineage Audit
Backtest Integrity Audit
Interface and Adapter Audit
Performance and Configuration Audit
Risk Governance for Research
Refactoring Blueprint and Test Matrix
```

Deferred scope:

```text
Production Trading Readiness Blueprint
Broker/OMS/live execution integration
High availability
Disaster recovery
Live operational runbooks
```

## Scope Boundary

The current goal is not live automated trading. Therefore:

- `Research`, `Signal`, `Portfolio`, `Execution`, `Risk`, and `Infrastructure` are current audit layers.
- `Broker` is marked as absent/deferred until source evidence shows a live broker integration.
- Production readiness is a blueprint and gap report, not an implementation mandate.

## Artifact Map

| Workstream | Artifact | Status |
|---|---|---|
| Master Plan | `00_master_work_plan.md` | Created |
| WS0 Protocol Control | `FINDING_TEMPLATE.md` | Created |
| WS0 Protocol Control | `FINDINGS_INDEX.md` | Created |
| WS0 Protocol Control | `IMPLEMENTATION_ENTRY_CRITERIA.md` | Created |
| WS0 Protocol Control | `index.md` | Created |
| WS1 Architecture Discovery | `01_architecture_discovery.md` | Created |
| WS2 Data Lineage Audit | `02_data_lineage_audit.md` | Completed |
| WS3 Backtest Integrity Audit | `03_backtest_integrity_audit.md` | Completed |
| WS3b Matching Engine Audit | ✅ 合并至 `03_backtest_integrity_audit.md` | Included in WS3 |
| WS4 Historical Signal Series | `04_historical_signal_series_blueprint.md` | Completed |
| WS5 Interface Contract Audit | `05_interface_contract_audit.md` | Completed |
| WS6 Adapter Blueprint | `06_adapter_blueprint.md` | Completed |
| WS7 Factor Admission Governance | `07_factor_admission_governance.md` | Completed |
| WS8 Performance Autopsy | `08_performance_autopsy.md` | Completed |
| WS9 Configuration Governance | `09_configuration_governance.md` | Completed |
| WS10 Research Risk Governance | `10_research_risk_governance.md` | Completed |
| WS11 Observability Blueprint | `11_observability_blueprint.md` | Completed |
| WS12 Event Architecture Blueprint | `12_event_architecture_blueprint.md` | Completed |
| WS13 Production Readiness Report | `13_production_readiness_report.md` | Completed |
| WS14 TDD Refactoring Design | `14_tdd_refactoring_design.md` | Completed |
| WS15 Refactoring Roadmap | `15_refactoring_roadmap.md` | Completed |
| Closure Review Plan | `16_institutional_closure_review_plan.md` | Created |
| Closure Review Report | `17_institutional_closure_review_report.md` | Completed — P0-3/P0-4 Closed, P0-2/P0-5 Partially closed, P0-1 Open |
| Final Consolidated Report | `99_final_institutional_audit_report.md` | Completed |
| Execution Plan Recommendation | `EXECUTION_PLAN_RECOMMENDATION.md` | Completed |
| Implementation Task Cards | `IMPLEMENTATION_PLAN_TASK_CARDS.md` | Completed |

## Post-Implementation Closure Review

After Phase 0-5 implementation work, do not repeat WS1-WS15 by default. First run the closure-review process:

1. Use `16_institutional_closure_review_plan.md` to reconcile source code, tests, baselines, `FINDINGS_INDEX.md`, and `docs/GAP_REMEDIATION_PLAN.md`.
2. Consult `17_institutional_closure_review_report.md` for the current P0/P1 closure status and verification evidence (completed 2026-06-12).
3. Update `FINDINGS_INDEX.md` only for status changes and closure evidence. Do not renumber historical findings.
4. Keep live-trading findings as `Deferred live` unless Broker/OMS/order-state implementation becomes scope.

## Execution Order

Before implementation starts, use:

1. `FINDINGS_INDEX.md` to map proposed code work to audit findings.
2. `IMPLEMENTATION_ENTRY_CRITERIA.md` to confirm phase entry gates, tests, rollback, and verification commands.

### Sprint 1 - Evidence Baseline

1. WS1 Architecture Discovery.
2. WS2 Data Lineage Audit.
3. WS3 Backtest Integrity Audit.
4. WS4 Historical Signal Series Blueprint.

Exit criteria:

- Current architecture graph exists.
- Core data objects have source -> transformation -> consumer lineage.
- Backtest cheating risks are classified.
- Historical signal timestamp gap has a target design.

### Sprint 2 - Contract and Adapter Discipline

1. WS5 Interface Contract Audit.
2. WS6 Adapter Blueprint.
3. WS7 Factor Admission Governance.
4. WS10 Research Risk Governance.

Exit criteria:

- Typed contracts are separated from dict compatibility.
- Brain -> Signal -> Portfolio -> Execution handoff is designed.
- Research risk controls are not bypassed by adapter defaults.
- Factor admission has IC/OOS/PBO/cost-aware gates.

### Sprint 3 - Platform Maturity

1. WS8 Performance Autopsy.
2. WS9 Configuration Governance.
3. WS11 Observability Blueprint.
4. WS12 Event Architecture Blueprint.

Exit criteria:

- CPU/memory/vectorization hotspots are ranked.
- Magic numbers and hardcoded paths are cataloged.
- Experiment lineage and signal-to-trade tracing have a target schema.
- Event migration boundaries are explicit.

### Sprint 4 - Production Blueprint and Roadmap

1. WS13 Production Readiness Report.
2. WS14 TDD Refactoring Design.
3. WS15 Refactoring Roadmap.

Exit criteria:

- Production trading gaps are documented without implying current readiness.
- Target architecture, contracts, migration strategy, test matrix, and sprint roadmap are complete.
- All 15 workstreams have artifacts.
- P0 findings are resolved (at least in design) or have migration paths.

## Institutional Quality Bar

Every recommendation must be:

```text
testable
verifiable
observable
extensible
rollback-aware
deployable
```

Every unresolved claim must be marked:

```text
INSUFFICIENT EVIDENCE
```
