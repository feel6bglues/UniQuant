# Institutional Findings Index

Generated: 2026-06-10

Purpose: provide a governance index for the institutional audit findings so that the final report, workstream artifacts, and future implementation work can be traced through a single control document.

This file is an index. The source of truth for the evidence, impact, recommendation, migration cost, and verification detail remains each owning workstream artifact.

## 1. Scope And Counting Rules

The audit has two counting layers:

| Layer | Meaning | Current count | Source |
|---|---|---:|---|
| Consolidated findings | Deduplicated final-report issues used for program governance | 91 | `99_final_institutional_audit_report.md` |
| Explicit workstream headings | Raw `### Finding WSx-yyy` entries, including duplicates, GREEN controls, Info entries, and live-scope gaps | 125 | WS1-WS13 artifacts |

The two counts are intentionally different. The final report consolidates repeated issues across workstreams. This index tracks both:

- Use Section 2 for execution governance of the highest-risk P0/P1 issues.
- Use Section 3 for full raw-workstream inventory coverage.
- Use the owning WS document to close any individual finding.

## 2. P0 Execution Board

Status meanings:

- `Design complete`: audit, target design, migration path, and verification plan exist.
- `Implementation pending`: no runtime/source code change has been made by the audit docs.
- `Deferred live`: relevant only if live automated trading becomes scope.

| Consolidated ID | Theme | Underlying findings | Target phase | Status | Closure evidence required |
|---|---|---|---|---|---|---|
| P0-1 | `data_pack: Dict[str, Any]` crosses data, brain, signal, and hands layers | WS1-002, WS2-001, WS2-002, WS5-002 | Phase 2 | Open (no runtime wiring) | `ResearchDataPack` contract tests; DataService typed-pack integration; engine regression suite; grep budget for `Dict[str, Any]` |
| P0-2 | Runtime timestamp injection blocks reproducible historical signal series | WS1-003, WS2-004, WS3-002, WS4 blueprint, WS5-009 | Phase 2 | Partially closed (TimeProvider injected in key paths; 38 remaining low-risk calls) | frozen/as-of timestamp utility; historical signal tests; `pd.Timestamp.now(` + `datetime.now(` combined count < 10 |
| P0-3 | Backtest integrity still depends on manual controls for survivorship/selection and engine divergence | WS3-003, WS3-008, WS3-015, WS10-007, WS10-008 | Phase 2 | Closed | SELL priority fix; `BacktestResult.metadata`; survivorship warning; baseline scripts; bias-prevention tests (9 pass); survivorship tests (3 pass) |
| P0-4 | Signal collection is not arbitration; first non-HOLD behavior can control result | WS1-004, WS1-005, WS1-009, WS6-001, WS6-003, WS6-006, WS10-001 | Phase 2 | Closed | `SignalArbitrator` in pipeline (arbitrate line 200); `arbitrate_candidates()` with WS14 chain; 15 unit tests pass; risk veto/force exit tested |
| P0-5 | Factor admission is not governed by IC/OOS/PBO/cost-aware gates | WS7-001, WS7-005, WS7-007, WS7-008, WS7-009, WS7-010, WS9-011 | Phase 2 | Partially closed (gate defined but off; dual registry G-2 still open) | `FactorAdmissionGate` tests; factor manifest validation; warn/block mode rollout; admission logs |

## 3. P1 Execution Board

These are the final report's eight P1 items, mapped to the workstream findings that provide evidence or design context.

| Consolidated ID | Theme | Underlying findings | Target phase | Status | Closure evidence required |
|---|---|---|---|---|---|---|
| P1-1 | Wyckoff analyzer is the largest CPU hotspot | WS8-001 | Phase 2 | Open (12 files, 5158 LOC, no caching/perf work) | before/after benchmark; output equivalence on representative symbols; performance budget met |
| P1-2 | `ScanService` batch execution lacks scalable parallel/checkpoint behavior | WS8-009, WS13-005, WS10-007, WS10-008 | Phase 2 | Open (single-threaded, no concurrency/checkpoint) | benchmark; checkpoint/restart test; point-in-time universe warning or guard |
| P1-3 | Deprecated `PortfolioEngine`/simulation portfolio path still carries untyped trade records | WS2-007, WS2-009, WS3-016, WS5-007, WS10-006 | Phase 3 | Partially closed (deprecated + services isolated; List[Dict] residuals remain) | canonical `TradeRecord` use; portfolio/backtest regression tests |
| P1-4 | A-share limit/tradability rule surface needs stronger testable governance | WS3-007, WS3-008, WS3-011, WS3-012 | Phase 2 | Closed (limit_checker 30 tests pass; price_collar + cost + slippage + market_rules all exist) | limit-up/down, suspension, lot-size, and price-collar tests |
| P1-5 | Long batch jobs have no robust checkpoint/restart semantics | WS13-005, WS12-006 | Phase 2/4 | Open (only baseline scripts have _save_intermediate; no services/experiments support) | restart-from-checkpoint simulation; partial result persistence |
| P1-6 | `MarketSignalContext` is typed but orphaned; `make_decision()` still accepts raw dicts | WS2-010, WS5-008, WS5-009 | Phase 3 | Closed (fully integrated: analysis_service → fsm → arbitrator; dict path is backward compat) | `MarketSignalContext` adoption tests; DecisionBrain contract tests |
| P1-7 | Retry/error-handling patterns overlap and are not governed as one failure taxonomy | WS11-009, WS13-003, WS13-004 | Phase 5 | Open (retry_decorator.py + error_handling.py have duplicate retry_on_exception/retry) | error taxonomy tests; retry policy audit; failure classification in logs |
| P1-8 | Config/secrets boundary is absent or weak | WS9-003, WS9-004, WS9-005, WS9-006, WS9-010 | Phase 5 | Partially closed (no static token; UNIQUANT_ env prefix works; no dedicated secrets test) | typed config validation; env overlay tests; no static secret values in committed config |

## 4. Raw Workstream Inventory

This table covers every explicit `### Finding WSx-yyy` heading in the current workstream artifacts.

| WS | Artifact | Explicit findings | Severity distribution | Target phase/status |
|---|---|---:|---|---|
| WS1 | `01_architecture_discovery.md` | 10 | P0=3, P1=6, P2=1 | Phase 1-3; broker item deferred |
| WS2 | `02_data_lineage_audit.md` | 10 | P0=3, P1=3, P2=4 | Phase 2-3 |
| WS3 | `03_backtest_integrity_audit.md` | 16 | P0=1, P1=3, P2=6, GREEN=4, Info=2 | Phase 2-3; GREEN controls retained |
| WS4 | `04_historical_signal_series_blueprint.md` | 0 explicit `Finding` headings | Blueprint for WS1-003/WS2-004/WS3-002 | Phase 3 or post-Phase 3 |
| WS5 | `05_interface_contract_audit.md` | 14 | P0=2, P1=3, P2=7, GREEN=2 | Phase 1-3 |
| WS6 | `06_adapter_blueprint.md` | 6 | P0=1, P1=5 | Phase 3 |
| WS7 | `07_factor_admission_governance.md` | 10 | P1=9, P2=1 | Phase 3 |
| WS8 | `08_performance_autopsy.md` | 11 | P1=1, P2=8, GREEN=1, Info=1 | Phase 2-4 |
| WS9 | `09_configuration_governance.md` | 11 | P1=7, P2=4 | Phase 5 |
| WS10 | `10_research_risk_governance.md` | 10 | P1=5, P2=4, GREEN=1 | Phase 3; live risk deferred |
| WS11 | `11_observability_blueprint.md` | 9 | P1=4, P2=5 | Phase 4-5 |
| WS12 | `12_event_architecture_blueprint.md` | 9 | P1=5, P2=4 | Phase 4; live eventing deferred |
| WS13 | `13_production_readiness_report.md` | 9 | P0=2, P1=2, P2=3, Info=2 | Research gaps Phase 4-5; live P0 deferred |

## 5. Raw Finding ID Ranges

| WS | Raw ID range | Closure owner |
|---|---|---|
| WS1 | WS1-001 through WS1-010 | Architecture owner |
| WS2 | WS2-001 through WS2-010 | Data contract owner |
| WS3 | WS3-001 through WS3-016 | Backtest/matching owner |
| WS4 | Blueprint only; no raw `Finding` IDs | Historical signal owner |
| WS5 | WS5-002 through WS5-015 | Shared contract owner |
| WS6 | WS6-001 through WS6-006 | Signal/adapters owner |
| WS7 | WS7-001 through WS7-010 | Factor governance owner |
| WS8 | WS8-001 through WS8-011 | Performance owner |
| WS9 | WS9-001 through WS9-011 | Config owner |
| WS10 | WS10-001 through WS10-010 | Research risk owner |
| WS11 | WS11-001 through WS11-009 | Observability owner |
| WS12 | WS12-001 through WS12-009 | Event architecture owner |
| WS13 | WS13-001 through WS13-009 | Production-readiness owner |

Note: WS5 starts at WS5-002 in the current artifact. Do not renumber historical findings unless a deliberate audit migration is performed.

## 6. Closure Rules

A finding can move from `Design complete, implementation pending` to `Closed` only when all of the following exist:

1. A code/config/doc change or an explicit no-change decision.
2. A verification method from the owning WS artifact.
3. A test, static check, benchmark, replay, or manual audit result.
4. A rollback or containment path for behavior-changing work.
5. A link back to the implementing commit or local change set.

Live-trading findings can only move to `Closed` if live trading becomes scope and broker/OMS/order-state evidence exists. Until then, they remain `Deferred live`.

## 7. Update Procedure

When implementation starts:

1. Update the relevant P0/P1 row in this file.
2. Update the owning WS artifact only if evidence or recommendation changes.
3. Update `99_final_institutional_audit_report.md` only at phase boundaries.
4. Do not change historical finding IDs.
5. If a raw finding is split into multiple implementation tasks, add sub-task IDs in the implementation tracker rather than renumbering the audit finding.
