# WS15 — Refactoring Roadmap

Generated: 2026-06-10  
Ordered execution plan for all refactoring phases defined in WS14.

---

## 1. Roadmap Overview

```
Phase 1 (Foundation)          Phase 2 (Data Layer)         Phase 3 (Signal/Factor)      Phase 4 (Event/Observability)   Phase 5 (Config/Health)
   Sprint A                     Sprint B                      Sprint C                      Sprint D                         Sprint D/E
   ┌──────────────┐            ┌──────────────┐             ┌──────────────┐              ┌──────────────┐                 ┌──────────────┐
   │ ResearchData  │───→        │ DataService  │───→          │ SignalArb    │───→          │ EventBus     │───→             │ ConfigModels │
   │ Pack          │            │ migration    │              │ itrator      │              │              │                 │              │
   │ Decision      │            │ Engine       │              │ FactorGate   │              │ Observability│                 │ HealthService│
   │ Output        │            │ refactor     │              │              │              │ OTel bridge  │                 │ Secrets      │
   │ CandidateSig  │            │              │              │              │              │              │                 │              │
   │ Event/Command │            │              │              │              │              │              │                 │              │
   │ Factor        │            │              │              │              │              │              │                 │              │
   │ Manifest      │            │              │              │              │              │              │                 │              │
   └──────┬───────┘            └──────┬───────┘             └──────┬───────┘              └──────┬───────┘                 └──────┬───────┘
          │                          │                            │                            │                               │
          │     parallel safe ───────┤                            │     parallel safe ─────────┤                               │
          │                          │                            │                            │                               │
          └─────────► Blocking ◄─────┘                            └──────────► Blocking ◄──────┘                               │
                                                                                                                                │
                                                                  parallel safe ────────────────────────────────────────────────┘
```

---

## 2. Phase 1 — Foundation (Sprint A)

**Goal**: Define typed contracts without modifying any runtime behavior.

**Effort**: ~2 days (one developer)

| Step | Task | Files | Tests | Risk |
|---|---|---|---|---|
| 1.1 | Add `ResearchDataPack` to `shared/interfaces.py` | `shared/interfaces.py` | `test_research_data_pack.py` | Low |
| 1.2 | Add `DecisionOutput` to `shared/interfaces.py` | `shared/interfaces.py` | `test_decision_output.py` | Low |
| 1.3 | Add `CandidateSignal` to `shared/interfaces.py` | `shared/interfaces.py` | `test_candidate_signal.py` | Low |
| 1.4 | Create `shared/event_types.py` with `Event`, `Command` | `shared/event_types.py` (new) | `test_event_types.py` | Low |
| 1.5 | Create `shared/factor_governance.py` with `FactorManifest` | `shared/factor_governance.py` (new) | `test_factor_manifest.py` | Low |

**Verification**:
```bash
pytest tests/ -q                                          # All existing tests pass
python3 -c "from uniquant.shared.interfaces import *"       # No import error
```

**Exit criteria**: All 5 type definitions exist with 95%+ test coverage. No existing code modified.

---

## 3. Phase 2 — Data Layer Migration (Sprint B)

**Goal**: Replace `data_pack: Dict[str, Any]` with `ResearchDataPack` across data, brain, and services layers.

**Effort**: ~2 weeks (one developer)

| Step | Task | Files | Tests | Risk | Rollback |
|---|---|---|---|---|---|
| 2.1 | Add `config.refactoring.use_research_data_pack: bool` | `config/config.yaml` | — | Low | Remove flag |
| 2.2 | Implement `DataService._build_research_data_pack()` | `data/data_service.py` | `test_data_service_typed.py` | Medium | `use_research_data_pack=false` |
| 2.3 | Add `ResearchDataPack.validate()` in DataService pipeline | `data/data_service.py` | — | Medium | Same flag |
| 2.4 | Update `AnalysisService_v2` to accept `ResearchDataPack` | `services/analysis_service_v2.py` | Integration tests | **High** | Same flag |
| 2.5 | Engine refactor batch 1: Regime, LPPL, NTF | `brain/regime/`, `brain/lppl/`, `brain/ntf/` | `test_backtest_regression.py` | **High** | Same flag |
| 2.6 | Engine refactor batch 2: CZSC, Wyckoff | `brain/czsc/`, `brain/wyckoff/` | `test_backtest_regression.py` | **High** | Same flag |
| 2.7 | Engine refactor batch 3: FSM, Alpha, Indicator, Screener | `brain/fsm/`, `brain/alpha/`, `brain/indicators/`, `brain/screener/` | `test_backtest_regression.py` | **High** | Same flag |
| 2.8 | Update `DecisionBrain.make_decision()` to return `DecisionOutput` | `brain/fsm/fsm.py` | `test_decision_output.py` | **High** | Same flag |
| 2.9 | Update adapters to use `DecisionOutput` | `signal/adapters.py` | `test_signal_pipeline.py` | Medium | Same flag |
| 2.10 | Remove backward-compat `data_pack` property | `shared/interfaces.py` | Regression suite | Medium | — |
| 2.11 | Remove `_build_data_pack()` deprecated method | `data/data_service.py` | — | Low | — |
| 2.12 | P0 find-and-fix: replace 430+ `Dict[str, Any]` sites | Across entire `src/uniquant/` | CI grep check | Medium | Manual revert |

**Wyckoff optimization (from WS8)**:
```python
# In brain/wyckoff/analyzer.py, refactor the main loop
# Current: 1457 LOC, nested for-loops, iterrows
# Target: vectorized NumPy/Pandas, batch processing, 800-1000 LOC
```

**Verification**:
```bash
pytest tests/ -q                                                         # Full suite
pytest tests/integration/test_data_service_typed.py                      # Typed pack round-trip
pytest tests/integration/test_backtest_regression.py                     # Results unchanged
python3 -c "from uniquant.shared.config_loader import get_config; c=get_config(); assert not c.get('refactoring.use_research_data_pack')"  # Old path still works
rg "Dict\[str, Any\]" src/uniquant/ | wc -l                              # Should be < 50
```

**Exit criteria**: `ResearchDataPack` flows from DataService through all 9 engines. Backtest results identical. Old `data_pack` path removed. `Dict[str,Any]` count < 50.

---

## 4. Phase 3 — Signal & Factor Governance (Sprint C)

**Goal**: Implement signal arbitration and factor admission governance.

**Effort**: ~1 week (one developer)

| Step | Task | Files | Tests | Risk | Rollback |
|---|---|---|---|---|---|
| 3.1 | Create `signal/arbitrator.py` with `SignalArbitrator` | `signal/arbitrator.py` (new) | `test_arbitrator.py` | Medium | `use_signal_arbitration=false` |
| 3.2 | Wire `SignalArbitrator` into `TradingSignalCollector` | `signal/adapters.py` | `test_signal_pipeline.py` | Medium | Same flag |
| 3.3 | Add `FactorAdmissionGate` to `shared/factor_governance.py` | `shared/factor_governance.py` | `test_factor_admission_gate.py` | Medium | `factor_gate_mode=warn` |
| 3.4 | Integrate `FactorAdmissionGate` into alpha/indicator registration | `brain/alpha/alpha_provider.py`, `brain/indicators/` | Integration tests | Medium | Same flag |
| 3.5 | Add `pd.Timestamp.now()` freeze utility in shared layer | `shared/time_utils.py` (new) | Unit tests | Low | — |
| 3.6 | Replace `pd.Timestamp.now()` with frozen timestamp in DecisionBrain | `brain/fsm/fsm.py`, `services/`, `signal/` | Regression tests | Medium | Manual revert |

**Signal arbitration logic**:
```python
# Priority order in SignalArbitrator.arbitrate()
def arbitrate(self, candidates: Sequence[CandidateSignal]) -> TradingSignal:
    # 1. Risk veto: any candidate with risk_score > threshold → HOLD
    # 2. DecisionBrain/FSM weighted vote (configurable weight, default 0.5)
    # 3. Weighted average of remaining candidates
    # 4. default_shares computed by PositionSizer, not by adapters
```

**Verification**:
```bash
pytest tests/signal/test_arbitrator.py -xvs                              # Arbitration logic
pytest tests/integration/test_signal_pipeline.py -xvs                    # Full pipeline
pytest tests/ -q                                                         # No regressions
python3 -c "from uniquant.signal.arbitrator import SignalArbitrator; a=SignalArbitrator(); print('OK')"
```

**Exit criteria**: `SignalArbitrator` active by default. `FactorAdmissionGate` warns on non-conforming factors. `pd.Timestamp.now()` + `datetime.now()` combined count < 10.

---

## 5. Phase 4 — Event Bus & Observability (Sprint D)

**Goal**: Add event bus, metrics, and OTel compatibility.

**Effort**: ~1 week (one developer)

| Step | Task | Files | Tests | Risk | Rollback |
|---|---|---|---|---|---|
| 4.1 | Implement sync `EventBus` | `shared/event_bus.py` (new) | `test_event_bus.py` | Low | `enable_event_bus=false` |
| 4.2 | Add async `EventBus` variant (optional) | `shared/event_bus.py` | — | Low | — |
| 4.3 | Wire `EventBus` into `ResearchPipeline.run_batch()` | `services/research_pipeline.py` | `test_event_bus_integration.py` | Low | Same flag |
| 4.4 | Wire `EventBus` into `DataService.fetch_data()` | `data/data_service.py` | — | Low | Same flag |
| 4.5 | Implement `MetricsRecorder` | `shared/observability.py` (new) | `test_observability.py` | Low | `enable_metrics=false` |
| 4.6 | Trace `AnalysisService_v2.run_ticker_analysis()` | `services/analysis_service_v2.py` | — | Low | Same flag |
| 4.7 | Add OTel adapter bridge | `shared/otel_adapter.py` (new) | — | Low | — |

**Verification**:
```bash
pytest tests/shared/test_event_bus.py -xvs                              # Event bus unit tests
pytest tests/integration/test_event_bus_integration.py -xvs             # Integration
pytest tests/ -q                                                         # No regressions
```

**Exit criteria**: EventBus publishes data/signal/result events. MetricsRecorder tracks key observability points. OTel adapter interface defined.

---

## 6. Phase 5 — Config & Health Hardening (Sprint D/E)

**Goal**: Typed config, data-feed health, secrets management.

**Effort**: ~3 days (one developer)

| Step | Task | Files | Tests | Risk | Rollback |
|---|---|---|---|---|---|
| 5.1 | Create `pydantic-settings` models for critical config sections | `shared/config_models.py` (new) | `test_config_models.py` | Low | Advisory only |
| 5.2 | Implement `ConfigValidator` to warn on raw-vs-typed mismatch | `shared/config_validator.py` (new) | — | Low | Remove from init |
| 5.3 | Add data-feed health check to `HealthService` | `services/health_service.py` | Integration tests | Low | — |
| 5.4 | Add cache health check to `HealthService` | `services/health_service.py` | — | Low | — |
| 5.5 | Add env-var secret injection to `config_loader.py` | `shared/config_loader.py` | — | Low | — |

**Verification**:
```bash
pytest tests/shared/test_config_models.py -xvs                           # Config validation
python3 -c "from uniquant.services import HealthService; ..."            # Health checks work
```

**Exit criteria**: Config validation warns on drift. HealthService checks data/cache sources. Secrets loadable from env vars.

---

## 7. P0 Resolution Timeline

| P0 | Description | Phase | Earliest Sprint | Verification |
|---|---|---|---|---|
| P0-1 | `data_pack` schema → `ResearchDataPack` | Phase 2 | Sprint B | `rg "data_pack" src/uniquant/` → only typed refs |
| P0-2 | `pd.Timestamp.now()` → frozen timestamp | Phase 2 | Sprint B | `rg "(pd\\.Timestamp|datetime(\\.datetime)?)\\.now\\(" src/uniquant/` < 10 |
| P0-3 | Backtest integrity controls | Phase 2 (engine refactor) | Sprint B | Regression tests pass |
| P0-4 | Signal arbitration | Phase 2 (arbitrator, 提前) | Sprint B | `SignalArbitrator` active, no signal bypass |
| P0-5 | Factor admission governance | Phase 2 (gate, 提前) | Sprint B | `FactorAdmissionGate` checks all new factors |

---

## 8. Effort Summary

| Phase | Sprint | Days | Risk | Parallelizable |
|---|---|---|---|---|
| Phase 1: Foundation | A | 2 | Low | With phases 2–5 |
| Phase 2: Data Layer | B | 10 | **High** | With phases 4–5 |
| Phase 3: Signal/Factor | C | 5 | Medium | With phase 5 |
| Phase 4: Event/Observability | D | 5 | Low | With phases 2–3, 5 |
| Phase 5: Config/Health | D/E | 3 | Low | With phases 2–4 |
| **Total** | **A–E** | **25** | — | — |

---

## 9. Dependency & Parallelism Rules

1. **Phase 1 must complete before Phase 2 or Phase 3** (contracts needed).
2. **Phase 2 must complete before Phase 3** (typed DecisionOutput needed for CandidateSignal).
3. **Phase 4 can start any time after Phase 1** (Event types defined).
4. **Phase 5 can start any time** (independent of other phases).
5. **Phase 2 engines can be refactored in parallel batches** (batch 1/2/3 parallel-safe).
6. **Wyckoff optimization (Phase 2) is independent of engine refactoring** — can be parallel.

Recommended parallel execution:
```
Week 1:  Phase 1 (dev A) + Phase 5 (dev B)
Week 2:  Phase 2 (dev A, full-time)
Week 3:  Phase 2 continues (dev A) + Phase 4 starts (dev B)
Week 4:  Phase 3 (dev A) + Phase 4 finishes (dev B)
Week 5:  Phase 3 finishes (dev A) + Phase 5 finishes (dev B)
```

---

## 10. Post-Roadmap Items (Deferred)

These are explicitly out of scope for the current refactoring but documented for future:

| Item | Reference | When |
|---|---|---|
| BrokerAdapter implementation | WS13 §4 | Production scope |
| Order state machine + persistence | WS13 | Production scope |
| HistoricalSignalRunner implementation | WS4 | After Phase 3 |
| Async EventBus | WS12 | After Phase 4 |
| Full OTel export | WS11 | After Phase 4 |
| Live HA/DR | WS13 | Production scope |
| Live position reconciliation | WS13 | Production scope |

---

## 11. Risk Mitigation Per Sprint

| Sprint | Top risk | Mitigation |
|---|---|---|
| A | None (new types only) | — |
| B | Engine refactor breaks existing analysis | Config gate + regression suite + rollback flag |
| B | Wyckoff optimization changes behavior | Compare output before/after on 100 random symbols |
| C | Signal arbitration changes backtest results | Compare old (first-non-hold) vs new (arbitrated) on historical batch |
| C | `pd.Timestamp.now()` replacement misses global impact | Grep before commit, freeze in shared utility |
| D | EventBus adds latency to hot paths | Sync-only for Phase 4; benchmark after; async in follow-up |
| E | Config model mismatch | Advisory warnings only; no enforced migration |
