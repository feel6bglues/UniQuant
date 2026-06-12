# Implementation Entry Criteria

Generated: 2026-06-10

Purpose: define the minimum gates that must be satisfied before moving from institutional audit/planning into runtime source-code implementation.

This document applies to any future code work based on `15_refactoring_roadmap.md`.

## 1. Non-Negotiable Entry Gates

No implementation phase may start until all gates below are satisfied.

| Gate | Requirement | Evidence |
|---|---|---|
| Scope gate | Confirm the target is research-platform hardening, not live automated trading | Current task statement or planning note |
| Source baseline gate | Capture current `git status --short` and do not overwrite unrelated dirty worktree changes | Command output in implementation notes |
| Finding traceability gate | Map the implementation task to one or more IDs in `FINDINGS_INDEX.md` | Task/PR description |
| Test-first gate | Add or update tests before behavior-changing implementation where practical | Test file reference |
| Feature-flag gate | Any cross-layer behavior change must have a config gate or compatibility path | Config key or explicit exception |
| Rollback gate | Define how to revert or disable the change without broad source rollback | Rollback note |
| Verification gate | Define exact commands required to prove the change | Command list |
| Documentation gate | Identify which audit artifact must be updated if implementation changes the evidence | Artifact list |

## 2. Definition Of Ready For A Code Task

A code task is ready only if it has:

1. One primary owner artifact from WS1-WS15.
2. One or more finding IDs from `FINDINGS_INDEX.md`.
3. A target phase from `15_refactoring_roadmap.md`.
4. A test plan with unit and integration coverage where applicable.
5. A regression-risk statement.
6. A rollback path.
7. A decision on whether the old path remains temporarily supported.

If any item is missing, the task remains in planning.

## 3. Phase Entry Criteria

### Phase 1 - Foundation Contracts

May start when:

- `FINDINGS_INDEX.md` maps the relevant P0/P1 findings.
- New types are additive and do not change runtime behavior.
- Tests are planned for `ResearchDataPack`, `DecisionOutput`, `CandidateSignal`, event types, and factor manifest types.

Required verification:

```bash
pytest tests/shared/ -q
python3 -c "from uniquant.shared.interfaces import TradingSignal; print('interfaces OK')"
```

Exit condition:

- Foundation types exist.
- Existing imports still work.
- No production behavior changes are introduced.

### Phase 2 - Data Layer Migration

May start when:

- Phase 1 foundation contracts exist and pass tests.
- `config.refactoring.use_research_data_pack` or equivalent compatibility gate is defined.
- Baseline regression results are captured for representative research/backtest flows.

Required verification:

```bash
pytest tests/integration/test_data_service_typed.py -q
pytest tests/integration/test_backtest_regression.py -q
pytest tests/ -q
rg "Dict\\[str, Any\\]|dict\\[str, Any\\]" src/uniquant
```

Exit condition:

- `ResearchDataPack` flows through DataService and target engines.
- Backtest regression is unchanged within agreed tolerance.
- Old dict path is either removed or explicitly gated.

### Phase 3 - Signal And Factor Governance

May start when:

- Phase 2 provides typed decision/data contracts or a compatibility adapter.
- `SignalArbitrator` behavior is specified by tests before integration.
- `FactorAdmissionGate` starts in warn mode unless a stricter rollout is approved.

Required verification:

```bash
pytest tests/signal/test_arbitrator.py -q
pytest tests/integration/test_signal_pipeline.py -q
pytest tests/shared/test_factor_admission_gate.py -q
pytest tests/ -q
```

Exit condition:

- Signal arbitration is deterministic and auditable.
- Risk veto cannot be bypassed by adapter defaults.
- Factor admission results are persisted or logged.

### Phase 4 - Event And Observability

May start when:

- Event types from Phase 1 exist.
- Hot-path latency budget is documented before instrumentation.
- EventBus integration is additive and listeners can be disabled.

Required verification:

```bash
pytest tests/shared/test_event_bus.py -q
pytest tests/integration/test_event_bus_integration.py -q
pytest tests/shared/test_observability.py -q
```

Exit condition:

- Data, signal, backtest, and result events are traceable.
- Metrics naming is stable.
- OTel bridge remains optional.

### Phase 5 - Config And Health Hardening

May start when:

- Current config behavior is captured.
- Typed config models are advisory first.
- Secrets migration avoids committing real credentials.

Required verification:

```bash
pytest tests/shared/test_config_models.py -q
python3 -c "from uniquant.shared.config_loader import get_config; print(get_config() is not None)"
```

Exit condition:

- Config validation warns on drift.
- Env override/secrets behavior is tested.
- Health checks distinguish research health from production trading readiness.

## 4. P0-Specific Entry Criteria

| P0 | Before implementation starts | Must not happen |
|---|---|---|
| P0-1 `ResearchDataPack` | Add contract tests and a compatibility flag | Big-bang removal of dict path without regression tests |
| P0-2 timestamp freeze | Add historical timestamp tests with fixed bar dates | Replacing all `now()` calls mechanically without classifying runtime-vs-research use |
| P0-3 backtest integrity | Capture baseline backtest outputs and known bias controls | Changing engine behavior without old-vs-new comparison |
| P0-4 signal arbitration | Encode arbitration/risk-veto rules as tests first | Letting adapters emit executable quantities without PositionSizer |
| P0-5 factor admission | Start in warn mode with manifest validation | Blocking existing factors before migration impact is known |

## 5. Definition Of Done For Implementation Tasks

A task is done only when:

1. Tests added or updated.
2. Relevant verification commands run in the current working tree.
3. Diff reviewed for unrelated changes.
4. Feature flag or compatibility path documented.
5. Rollback path documented.
6. `FINDINGS_INDEX.md` status updated if a finding is closed or materially advanced.
7. Owning WS artifact updated only if the evidence or recommendation changed.

## 6. Stop Conditions

Stop implementation and return to design if any of these occurs:

- A source finding cannot be tied to a current file or test.
- A planned compatibility flag cannot be introduced safely.
- Baseline tests fail before the change and the failure is unrelated to the task.
- A live-trading assumption is required to complete a research-platform task.
- Existing user or prior-agent work would need to be reverted.

## 7. Recommended First Implementation Slice

The first implementation slice should be Phase 1 only:

1. Add additive contract types.
2. Add unit tests for those types.
3. Run shared-layer tests and import smoke checks.
4. Do not wire the new contracts into runtime services until Phase 1 passes.

This keeps the first implementation step reviewable, reversible, and independent of the high-risk engine migration.
