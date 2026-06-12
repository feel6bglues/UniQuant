# WS14 — TDD Refactoring Design

Generated: 2026-06-10  
Convergence of WS1–WS13 findings into target architecture, migration strategy, test matrix, and refactoring roadmap.

---

## 1. Target Architecture

### 1.1 Current Architecture (Simplified)

```
config.yaml → ServiceContainer → DataService → AnalysisService_v2 → DecisionBrain
                                                                          ↓
                                                              SignalAdapter[] → TradingSignalCollector
                                                                                      ↓
                                                                           UnifiedBacktestEngine
```

Key problems:
- `data_pack: Dict[str, Any]` crosses 4 layers with 30+ implicit keys (WS2, WS5)
- No typed contracts between layers (WS5)
- No signal arbitration (WS6)
- Ad-hoc factor registration (WS7)
- No event bus (WS12)

### 1.2 Target Architecture (Phase 4)

```
config.yaml → ServiceContainer → DataService → AnalysisService_v2 ──→ DecisionBrain
                                              │                          │
                                              ↓                          ↓
                                        ResearchDataPack          DecisionOutput
                                              │                          │
                                              ├──→ AnalysisService_v2    ├──→ SignalArbitrator
                                              │       (typed outputs)    │       ↓
                                              └──→ DataPackSchema        │  CandidateSignal[]
                                                  (validation)           │       ↓
                                                                         │  TradingSignalCollector
                                                                         │       ↓
                                                                         │  TradingSignal[]
                                                                         │
                                    ┌────────────────────────────────────┘
                                    ↓
                              EventBus ──→ UnifiedBacktestEngine (research)
                                       │   └──→ UnifiedMatchingEngine
                                       │   └──→ PortfolioEngine
                                       │   └──→ PositionSizer
                                       │
                                       │   ResearchDataStore (research)
                                       │   └──→ BacktestResult
                                       │   └──→ PerformanceReport
                                       │
                                       │   ObservabilityAdapter (blueprint)
                                       │   └──→ MetricsRecorder
                                       │   └──→ Tracer
                                       │
                                       │   ConfigStore (typed config)
                                       │   └──→ pydantic.Settings models
                                       │
                                       │   FactorRegistry (typed factors)
                                       │   └──→ FactorManifest
                                       │   └──→ FactorAdmissionGate
```

---

## 2. Target Contracts

### 2.1 ResearchDataPack (replaces Dict[str, Any])

Based on WS2 §7 and WS5 §4.2:

```python
# src/uniquant/shared/interfaces.py (additions)

@dataclass(frozen=True)
class ResearchDataPack:
    """Typed research data pack — replaces data_pack Dict[str,Any]."""

    code: str
    name: str
    market: str  # "SH" | "SZ" | "BJ"
    date: pd.Timestamp

    # OHLC data
    daily: pd.DataFrame    # Columns: open, high, low, close, volume, amount
    weekly: pd.DataFrame | None = None
    monthly: pd.DataFrame | None = None
    min5: pd.DataFrame | None = None   # 5-minute bars
    min1: pd.DataFrame | None = None   # 1-minute bars (if available)

    # Adjusted data
    daily_hfq: pd.DataFrame | None = None  # 后复权
    daily_qfq: pd.DataFrame | None = None  # 前复权

    # Fundamentals
    fundamentals: pd.DataFrame | None = None

    # Metadata
    is_st: bool = False
    is_suspended: bool = False
    limit_up: float | None = None
    limit_down: float | None = None
    total_shares: int = 0
   流通_shares: int = 0

    # Financial data (optional)
    financials: dict | None = None

    # Derived
    indicators: dict | None = None  # Pre-computed indicators

    def validate(self) -> bool:
        """Validate required fields."""
        required_cols = {"open", "high", "low", "close", "volume"}
        if self.daily is None:
            return False
        return required_cols.issubset(self.daily.columns)
```

### 2.2 DecisionOutput (replaces DecisionBrain Dict[str, Any] returns)

Based on WS5 §4.3:

```python
@dataclass(frozen=True)
class DecisionOutput:
    """Typed decision from DecisionBrain — replaces dict returns."""

    action: str  # "BUY" | "SELL" | "HOLD" | "CLOSE"
    confidence: float  # 0.0–1.0
    reason: str
    signal_direction: int  # 1 = buy, -1 = sell, 0 = hold
    strength: float  # 0.0–1.0
    risk_score: float = 0.0  # 0.0 = no risk, 1.0 = max risk
    metadata: dict = field(default_factory=dict)  # Engine-specific metadata (opaque)
    timestamp: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now(tz="Asia/Shanghai"))
```

### 2.3 CandidateSignal (for arbitration)

Based on WS6 §4.2:

```python
@dataclass(frozen=True)
class CandidateSignal:
    """Engine output normalized for arbitration."""

    source: str  # "regime" | "lppl" | "ntf" | "czsc" | "wyckoff" | "alpha" | "indicator"
    action: str  # "BUY" | "SELL" | "HOLD" | "CLOSE"
    confidence: float  # 0.0–1.0
    direction: int  # 1, -1, 0
    strength: float  # 0.0–1.0
    price_target: float | None = None
    stop_loss: float | None = None
    time_horizon: str | None = None  # "short" | "medium" | "long"
    metadata: dict = field(default_factory=dict)
```

### 2.4 SignalArbitrator (new service)

```python
class SignalArbitrator:
    """Arbitrates multiple CandidateSignal into a single TradingSignal."""

    def __init__(
        self,
        veto_engines: list[str] | None = None,
        weight_overrides: dict[str, float] | None = None,
    ):
        self.veto_engines = veto_engines or ["risk"]
        self.weights: dict[str, float] = weight_overrides or {}

    def arbitrate(self, candidates: Sequence[CandidateSignal]) -> TradingSignal:
        """Arbitrate candidates into single TradingSignal.

        Process: veto → DecisionBrain/FSM (weighted) → weighted average → default_shares
        """
        ...
```

### 2.5 FactorManifest & FactorAdmissionGate (for factor governance)

Based on WS7 §3:

```python
@dataclass(frozen=True)
class FactorManifest:
    """Structured factor metadata for registration."""

    name: str
    category: str  # "momentum" | "volatility" | "value" | "quality" | "growth" | "liquidity"
    engine: str  # "alpha" | "indicator" | "custom"
    parameters: dict[str, Any]
    description: str
    version: str
    author: str = ""
    created_at: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now())
    tags: list[str] = field(default_factory=list)


class FactorAdmissionGate:
    """Governs factor registration with admission criteria."""

    def check_admission(self, manifest: FactorManifest) -> AdmissionResult:
        """Run admission checks: naming, doc, time-series, IC, correlation."""
        ...


@dataclass
class AdmissionResult:
    passed: bool
    checks: dict[str, CheckResult]  # check_name → result
    summary: str
```

### 2.6 Event types (for event bus)

Based on WS12 §3:

```python
@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str  # "data_updated" | "signal_generated" | "trade_executed" | ...
    timestamp: pd.Timestamp
    source: str
    payload: dict
    correlation_id: str = ""


@dataclass(frozen=True)
class Command:
    command_id: str
    command_type: str  # "run_analysis" | "submit_order" | "cancel_order" | ...
    timestamp: pd.Timestamp
    payload: dict
    reply_to: str | None = None
```

---

## 3. Migration Strategy

### Phase 1 — Foundation (Sprint A)

| # | Step | Files affected | Risk | Dependencies |
|---|---|---|---|---|
| 1.1 | Define `ResearchDataPack` in `shared/interfaces.py` | `shared/interfaces.py` | Low | None |
| 1.2 | Implement `ResearchDataPack.validate()` | `shared/interfaces.py` | Low | 1.1 |
| 1.3 | Define `DecisionOutput` in `shared/interfaces.py` | `shared/interfaces.py` | Low | None |
| 1.4 | Define `CandidateSignal` in `shared/interfaces.py` | `shared/interfaces.py` | Low | None |
| 1.5 | Define `FactorManifest` & `FactorAdmissionGate` in new file | `shared/factor_governance.py` | Low | None |
| 1.6 | Define `Event` & `Command` types in new file | `shared/event_types.py` | Low | None |
| 1.7 | Add unit tests for all new types | `tests/` | Low | 1.1–1.6 |

**Verification**: `pytest tests/ -q`, no source changes beyond shared layer.

### Phase 2 — Data Layer Migration (Sprint B)

| # | Step | Files affected | Risk | Dependencies |
|---|---|---|---|---|
| 2.1 | Change `DataService.fetch_for_brain()` return to `ResearchDataPack` | `data/data_service.py` | **High** | 1.1–1.2 |
| 2.2 | Update `DataService._build_data_pack()` → `_build_research_data_pack()` | `data/data_service.py` | Medium | 2.1 |
| 2.3 | Update `AnalysisService_v2.run_ticker_analysis()` input param | `services/analysis_service_v2.py` | **High** | 2.1 |
| 2.4 | Update all engine inputs from `data_pack` → `ResearchDataPack` | `brain/*.py` (9 engines) | **High** | 2.3 |
| 2.5 | Add backward-compat property: `data_pack` returns `asdict(self)` | `shared/interfaces.py` | Low | 2.1 |
| 2.6 | Add `ResearchDataPack` validation in `DataService._validate_data()` | `data/data_service.py` | Medium | 2.1 |

**Rollback**: Keep `_build_data_pack()` as deprecated method; toggle via config flag `use_research_data_pack: bool`.

**Rollback plan**:
```python
# In ServiceContainer, config-driven feature flag
self._use_typed_pack = config.get("refactoring.use_research_data_pack", False)

if self._use_typed_pack:
    data_pack = data_service.fetch_typed_pack(code)
else:
    data_pack = data_service.fetch_for_brain(code)
```

### Phase 3 — Signal & Factor Governance (Sprint C)

| # | Step | Files affected | Risk | Dependencies |
|---|---|---|---|---|
| 3.1 | Implement `SignalArbitrator` | `signal/arbitrator.py` (new) | **High** | 1.3–1.4 |
| 3.2 | Modify `TradingSignalCollector` to use `SignalArbitrator` | `signal/adapters.py` | **High** | 3.1 |
| 3.3 | Implement `FactorAdmissionGate` | `shared/factor_governance.py` | Medium | 1.5 |
| 3.4 | Integrate `FactorAdmissionGate` into alpha/indicator registration | `brain/alpha/`, `brain/indicators/` | Medium | 3.3 |
| 3.5 | Add arbitration unit tests | `tests/test_arbitrator.py` | Low | 3.1–3.2 |
| 3.6 | Add factor admission tests | `tests/test_factor_governance.py` | Low | 3.3–3.4 |

**Rollback**: Config flag `use_signal_arbitration: bool` — when False, fall back to first-non-hold signal (current behavior).

### Phase 4 — Event Bus & Observability (Sprint D)

| # | Step | Files affected | Risk | Dependencies |
|---|---|---|---|---|
| 4.1 | Implement `EventBus` (sync first, async later) | `shared/event_bus.py` (new) | Medium | 1.6 |
| 4.2 | Integrate `EventBus` into key service lifecycle points | `services/`, `brain/`, `data/` | Medium | 4.1 |
| 4.3 | Implement `MetricsRecorder` | `shared/observability.py` (new) | Medium | 1.6 |
| 4.4 | Trace `AnalysisService_v2.run_ticker_analysis()` | `services/analysis_service_v2.py` | Low | 4.3 |
| 4.5 | Add OTel adapter bridge (WS11 interface) | `shared/otel_adapter.py` (new) | Low | 4.3 |
| 4.6 | Event bus unit + integration tests | `tests/test_event_bus.py` | Low | 4.1–4.2 |

**Rollback**: EventBus is additive — old code paths continue unchanged without listeners.

### Phase 5 — Config & Health Hardening (Sprint D/E)

| # | Step | Files affected | Risk | Dependencies |
|---|---|---|---|---|
| 5.1 | Introduce `pydantic-settings` model for critical sections | `shared/config_models.py` (new) | Medium | None |
| 5.2 | Add validation bridge: `ConfigValidator` that compares raw vs typed | `shared/config_validator.py` (new) | Low | 5.1 |
| 5.3 | Add data-feed health monitoring to `HealthService` | `services/health_service.py` | Low | None |
| 5.4 | Add cache health check to `HealthService` | `services/health_service.py` | Low | None |
| 5.5 | Add secrets injection (env var overlay) | `shared/config_loader.py` | Low | None |

**Rollback**: Config models are advisory — no enforced migration.

---

## 4. Test Matrix

### 4.1 Unit Tests (phase 1–2)

| Test file | Tests | Phase |
|---|---|---|
| `tests/shared/test_research_data_pack.py` | `ResearchDataPack` creation, validation, field access, backward compat | 1 |
| `tests/shared/test_decision_output.py` | `DecisionOutput` creation, immutability, default timestamp | 1 |
| `tests/shared/test_candidate_signal.py` | `CandidateSignal` creation, field constraints | 1 |
| `tests/shared/test_event_types.py` | `Event`, `Command` creation, UUID generation, comparison | 1 |
| `tests/shared/test_factor_manifest.py` | `FactorManifest` creation, validation, category enum | 1 |

### 4.2 Unit Tests (phase 3)

| Test file | Tests | Phase |
|---|---|---|
| `tests/signal/test_arbitrator.py` | Veto logic, weighted average, default_shares (non-FSM), edge cases | 3 |
| `tests/shared/test_factor_admission_gate.py` | Naming check, doc check, time-series check, IC check, correlation check | 3 |
| `tests/signal/test_trading_signal_collector_final.py` | Integration with arbitrator, backwards compat | 3 |

### 4.3 Unit Tests (phase 4)

| Test file | Tests | Phase |
|---|---|---|
| `tests/shared/test_event_bus.py` | Publish-subscribe, error isolation, async mode, ordering | 4 |
| `tests/shared/test_observability.py` | `MetricsRecorder`, trace recording, OTel adapter | 4 |

### 4.4 Integration Tests

| Test file | Tests | Phase |
|---|---|---|
| `tests/integration/test_data_service_typed.py` | `ResearchDataPack` round-trip: data sources → typed pack → engine input | 2 |
| `tests/integration/test_signal_pipeline.py` | Full pipeline: engines → adapters → arbitrator → TradingSignal | 3 |
| `tests/integration/test_event_bus_integration.py` | EventBus wired into ResearchPipeline | 4 |

### 4.5 Regression Tests

| Test file | Tests | Phase |
|---|---|---|
| `tests/integration/test_backtest_regression.py` | Existing backtest results unchanged after migration | 2, 3 |
| `tests/integration/test_analysis_regression.py` | Existing analysis results unchanged | 2, 3 |

### 4.6 Coverage Target

| Layer | Current | Target | Phase |
|---|---|---|---|
| `shared/interfaces.py` | ~40% | 90%+ | 1 |
| `shared/` (new files) | — | 95%+ | 1–4 |
| `data/data_service.py` | ~60% | 85%+ | 2 |
| `services/analysis_service_v2.py` | ~55% | 85%+ | 2 |
| `signal/` | ~70% | 90%+ | 3 |
| `brain/` engines | ~50% | 80%+ | 2 |

---

## 5. Test-Driven Refactoring Workflow

For each step in the migration:

1. **RED**: Write tests for the new contract/interface
2. **GREEN**: Implement the new contract in a parallel path (config-gated)
3. **REFACTOR**: Remove old path, promote new path to default, delete config gate
4. **VERIFY**: Run full test suite, compare coverage

### Example: ResearchDataPack migration

```
RED:   test_research_data_pack.py               # Tests for ResearchDataPack
GREEN: DataService._build_research_data_pack()   # New path, config-gated
       ResearchDataPack class + validate()
REFACTOR: Remove _build_data_pack()
          Rename _build_research_data_pack() → _build_data_pack()
          Remove config gate
VERIFY: pytest tests/integration/test_data_service_typed.py
        pytest tests/ -q
```

---

## 6. Dependency Graph

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5
                 │            │            │
                 ↓            ↓            ↓
           Engine refactor  Arbitrator   EventBus
           (brain/*.py)     Adapters     Observability
                            FactorGate  OTel
```

Cyclical dependencies to resolve:
- Phase 2 (engine refactor) requires Phase 1 contracts → Phase 2 blocked on Phase 1.
- Phase 3 (arbitration) requires Phase 2 (typed DecisionOutput is input) → Phase 3 blocked on Phase 2.
- Phase 4 (event bus) is independent — can run in parallel with Phase 2/3.
- Phase 5 (config/health) is independent — can run in parallel with Phase 2/3/4.

Parallel-safe groups: {Phase 1 alone}, {Phase 2 + Phase 4 + Phase 5}, {Phase 3 + Phase 5}.

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Engine refactor (Phase 2) breaks existing analysis | **Medium** | **High** | Config gate + regression tests + rollback plan |
| Signal arbitration changes backtest results | **Medium** | **High** | Config gate to use old (first-non-hold) behavior; compare results |
| `pd.Timestamp.now()` injection causes test flakiness | **High** | **Medium** | Replace with `datetime.now(tz=ASIA_SH)` in interface layer; freeze in tests |
| EventBus adds latency to hot paths | **Low** | **Low** | Sync bus for now; async in follow-up; benchmark first |
| Factor admission gate blocks existing valid factors | **Medium** | **Medium** | Admission warnings, not blocks, for first release; strict mode in follow-up |
| `Dict[str, Any]` sites missed in migration | **High** | **Medium** | Automated grep check in CI (`rg "Dict\[str, Any\]" src/uniquant/`) |

---

## 8. Rollback Plan Summary

| Component | Rollback mechanism | Trigger |
|---|---|---|
| ResearchDataPack | `config.refactoring.use_research_data_pack = false` | Regression test failure |
| DecisionOutput | Same config flag | Engine pipeline failure |
| Signal arbitration | `config.refactoring.use_signal_arbitration = false` | Backtest result drift > 1% |
| Factor admission | `config.refactoring.factor_gate_mode = "warn"` (instead of "block") | Existing factor registration failure |
| EventBus | `config.refactoring.enable_event_bus = false` | Performance regression > 10% |
| Observability | `config.refactoring.enable_metrics = false` | None — additive only |

---

## 9. WS1–WS13 Finding Resolution Map

| WS | Key finding | Resolution | Phase |
|---|---|---|---|
| WS2 | `data_pack: Dict[str, Any]` | `ResearchDataPack` replaces it | 2 |
| WS3 | No timestamp freeze in backtests | `DecisionOutput.timestamp` standardized | 1 |
| WS4 | No historical signal series | SignalRunner defined (separate scope) | Post-P4 |
| WS5 | No typed cross-layer contracts | Phase 1 contracts | 1 |
| WS6 | No signal arbitration | `SignalArbitrator` | 3 |
| WS7 | No factor governance | `FactorAdmissionGate` | 3 |
| WS8 | Wyckoff bottleneck | Optimize in Phase 2 refactor | 2 |
| WS9 | Config drift | `pydantic-settings` models | 5 |
| WS10 | Research risk gaps | DecisionBrain already handles veto | 3 |
| WS11 | No observability | `MetricsRecorder` + OTel adapter | 4 |
| WS12 | No event architecture | `EventBus` | 4 |
| WS13 | No broker/HA/DR | Deferred to production scope | — |

---

## 10. Success Criteria

| Criterion | Target | Verification |
|---|---|---|
| All 430+ `Dict[str, Any]` replaced | < 50 remain | `rg "Dict\[str, Any\]" src/uniquant/` |
| `ResearchDataPack` used in all engines | 9/9 engines | `rg "data_pack" brain/` → zero non-pack refs |
| `SignalArbitrator` active | Default ON | `config.refactoring.use_signal_arbitration = true` |
| Test coverage > 80% | All layers | `pytest --cov=src/uniquant/` |
| Backtest results match pre-migration | Identical within float64 tolerance | Nightly regression suite |
| `FactorAdmissionGate` covers all new factors | 100% of new registrations | Admission log per registration |
