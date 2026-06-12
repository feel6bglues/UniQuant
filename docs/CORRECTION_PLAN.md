# Correction Plan (Verified)

> File: `docs/CORRECTION_PLAN.md`
> Purpose: Prioritized corrections for verified gaps between institutional design documents
> and current code, cross-referenced to original design intent (WS14, WS7, WS12).
>
> **STATUS**: Verified against actual source code on 2026-06-11.

---

## How to read this

Each item maps:

  **Gap (M-#)** → **Original design intent** → **Correction** → **Files** → **Verification**

| Label | Effort | Impact |
|-------|--------|--------|
| **P0** | 1–2 hrs | High |
| **P1** | 2–4 hrs | High |
| **P2** | 4–8 hrs | Medium |
| **P3** | 8+ hrs | Medium/Low |

---

## Phase A — Quick Wins (P0)

### A.1 LPPL specificity check (M-5) — VERIFIED

**Gap** (`unified_engine.py:246-252`):
The SELL-priority loop dispatches on `sig.action == "SELL"` with no source-engine filter.
A Wyckoff SELL, NTF SELL, or Alpha SELL is treated identically to an LPPL SELL, even though
the LPPL SELL-priority rule (Phase 0) was specifically documented for LPPL's limit-up pattern.

Actual code at `src/uniquant/hands/backtest/unified_engine.py:242-260`:
```python
# 规则: SELL 优先于 BUY (LPPL SELL 不可被同日 BUY 覆盖)
day_signals = signal_map.get(date_key, [])
for sig in day_signals:
    if sig.action == "SELL" and position > 0 and pending_order is None:
        pending_order = {
            "action": "SELL",
            "shares": position,
            "reason": sig.reason,
        }
        break
    elif sig.action == "BUY" and position == 0 and pending_order is None:
        shares = sig.shares if sig.shares > 0 else 100
        pending_order = {
            "action": "BUY",
            "shares": shares,
            "reason": sig.reason,
        }
        break
```

**Design intent** (WS14 §3.2.2 → unified_engine.py):
The LPPL SELL-priority was specifically for LPPL's limit-up detection pattern. The Phase-0
fix was meant to gate on `signal.reason` containing `"lppl"`.

**Correction** — Add source-engine filter to the `SELL` branch:

```python
if (sig.action == "SELL" and position > 0 and pending_order is None
        and sig.reason and "lppl" in sig.reason.lower()):
```

**Verification**: `pytest tests/ -q` — baseline comparison unchanged for LPPL SELL cases.
Non-LPPL SELL signals no longer preempt BUY signals of the same day.

---

### A.2 BacktestResult metadata population (M-3) — VERIFIED

**Gap**: `BacktestResult.metadata` is defined as `dict` (with `field(default_factory=dict)`) at
`unified_engine.py:72` and `result.py:62`, but zero of 8 call sites pass `metadata=` — it is
always an empty dict `{}`.

Key return path at `unified_engine.py:262-268`:
```python
return BacktestResult(
    trades=trades,
    equity_curve=equity_curve,
    daily_returns=daily_returns,
    initial_capital=self.initial_capital,
    final_cash=cash,
)
```

**Note**: `PipelineResult` already passes `symbol=symbol` through — no correction needed there.

**Design intent** (WS14 §1.1, §10):
`BacktestResult.metadata` should carry `symbol`, `engine`, `start_date`, `end_date`, etc.

**Correction** — Populate metadata at `unified_engine.py:268`:

```python
return BacktestResult(
    trades=trades,
    equity_curve=equity_curve,
    daily_returns=daily_returns,
    initial_capital=self.initial_capital,
    final_cash=cash,
    metadata={
        "symbol": self.symbol if hasattr(self, "symbol") else "",
        "engine": "unified",
        "start_date": str(df.index[0].date()) if len(df) else "",
        "end_date": str(df.index[-1].date()) if len(df) else "",
        "signal_count": len(signals),
    },
)
```

**Verification**: `pytest tests/ -q`, add assertion `result.metadata` is non-empty in existing tests.

---

### A.3 Replace `date.today()` with TimeProvider (M-10) — VERIFIED

**Gap**: 4 sites in 2 files use raw `date.today()` instead of `TimeProvider`. The plan
previously cited non-existent files in `shared/constants/`. Actual sites:

| # | File | Line | Code |
|---|------|------|------|
| 1 | `src/uniquant/services/market_cache.py` | 102 | `date.today().isoformat()` |
| 2 | `src/uniquant/data/managers/stock_metadata_manager.py` | 259 | `check_date = as_of or date.today()` |
| 3 | same file | 277 | `check_date = as_of or date.today()` |
| 4 | same file | 317 | `check_date = as_of or date.today()` |

**Design intent** (WS14 Risk Assessment §7, WS3 §2):
All time-dependent code must use `RealTimeProvider` / `FrozenTimeProvider` so backtests
freeze time deterministically.

**Correction** — Replace all 4 sites:

```python
from uniquant.shared.time_provider import get_time_provider
today = get_time_provider().today()
```

**Verification**: `pytest tests/ -q`. Each file has low test coverage — verify manually.

---

### A.4 Signal timestamp from K-line bar date (M-4) — VERIFIED

**Gap**: Signal timestamps at `research_pipeline.py:177` use `self._time_provider.now()` (wall
clock) instead of the K-line bar's date. This causes backtest signal timestamps to drift
per-run when using `RealTimeProvider`.

The timestamp chain:
1. `research_pipeline.py:177`: `timestamp = self._time_provider.now()`
2. `adapters.py:451` (`collect()`): passes `timestamp` param to each adapter
3. Each adapter (e.g. `LPPLAdapter` at line 91): `TradingSignal(..., timestamp=timestamp)`

**Design intent** (WS14 §3 — DecisionOutput.timestamp):
Timestamp should reflect the data bar's time, not wall clock.

**Correction** — Accept an explicit `bar_date` in `collect()`:

File: `src/uniquant/signal/adapters.py`:
```python
def collect(self, data_pack, timestamp=None, bar_date=None, default_shares=100):
    ...
    ts = bar_date if bar_date is not None else timestamp
```

File: `src/uniquant/services/research_pipeline.py` — extract `bar_date` from data_pack's
K-line DataFrame (last row's date) and pass to `collect()`.

**Verification**: `pytest tests/ -q`. Signal timestamps match the bar date in test fixtures.

---

## Phase B — Missing Type Contracts (P1)

### B.1 CandidateSignal dataclass (M-1) — VERIFIED

**Gap**: `CandidateSignal` does not exist anywhere in the codebase (0 grep matches).
The design specifies it (WS14 §2.3) as the typed per-engine signal input to `SignalArbitrator`.

**Design intent** (WS14 §2.3):
```python
@dataclass(frozen=True)
class CandidateSignal:
    source: str       # "regime" | "lppl" | "ntf" | "czsc" | "wyckoff" | "alpha" | "indicator"
    action: str       # "BUY" | "SELL" | "HOLD" | "CLOSE"
    confidence: float  # 0.0–1.0
    direction: int     # 1, -1, 0
    strength: float    # 0.0–1.0
    price_target: float | None = None
    stop_loss: float | None = None
    time_horizon: str | None = None  # "short" | "medium" | "long"
    metadata: dict = field(default_factory=dict)
```

**Correction**:
1. Add `CandidateSignal` to `src/uniquant/shared/interfaces.py`
2. The current `SignalArbitrator.arbitrate()` takes `List[TradingSignal]` — add an overload
   accepting `List[CandidateSignal]` with conversion via existing adapters
3. Add unit tests: `tests/shared/test_candidate_signal.py` (file does not exist)

**Verification**: `pytest tests/shared/test_candidate_signal.py -xvs`, no tested behavior changes.

---

### B.2 FactorAdmissionGate.evaluate() (M-2) — VERIFIED

**Gap**: `shared/factor_governance.py` is a 36-line deprecated shim that re-exports
`brain.factors.registry.FactorRegistry` and issues `DeprecationWarning`. The `FactorAdmissionGate`
class from WS14 §2.5 / WS7 §3 was never implemented.

**Design intent** (WS14 §2.5, WS7 §3):
```python
class FactorAdmissionGate:
    def check_admission(self, manifest: FactorManifest) -> AdmissionResult:
        """Run admission checks: naming, doc, time-series, IC, correlation."""

@dataclass
class AdmissionResult:
    passed: bool
    checks: dict[str, CheckResult]
    summary: str
```

Start in `"warn"` mode (WS14 §7 Risk Assessment).

**Correction**:
1. Implement `FactorAdmissionGate` in `src/uniquant/shared/factor_governance.py`:
   - `check_admission(manifest)` → `AdmissionResult`
   - Checks: naming convention, documentation presence, parameter validation
   - Start in `"warn"` mode (config-driven: `factor_gate_mode`)
2. Add `AdmissionResult` dataclass
3. Wire into `brain/factors/registry.py` to gate registration
4. Add tests: `tests/shared/test_factor_admission_gate.py` (file does not exist)

**Verification**: `pytest tests/shared/test_factor_admission_gate.py -xvs`, existing factor
registration continues with warnings.

---

### B.3 Domain event emission (M-11) — VERIFIED

**Gap**: `EngineCompleted` and `SignalGenerated` event types ARE defined in
`event_types.py:101` and `event_types.py:48` respectively, but they are NEVER instantiated
or emitted outside `research_pipeline.py`.

Current event emission coverage (only in `research_pipeline.py`):
- `RunStarted`, `DataLoaded`, `RunCompleted` — published
- `DecisionProduced`, `SignalsCollected`, `BacktestCompletedEvent` — published
- `EngineCompleted` — **never published** (zero uses)
- `SignalGenerated` — **never published** (zero uses)
- `analysis_service_v2.py` — **no event emission at all** (no EventBus import)
- `adapters.py` — **no event emission at all** (no EventBus import)

**Design intent** (WS14 §2.6, WS12 §3):
Events at lifecycle points: `data_updated`, `signal_generated`, `trade_executed`.

**Correction**:
1. Wire `EventBus` into `services/analysis_service_v2.py` — emit `EngineCompleted` after each
   engine run (6 engine calls, plus indicator and alpha passes)
2. Wire `EventBus` into `signal/adapters.py` — emit `SignalGenerated` after signal collection
3. Add integration tests for event emission

**Verification**: `pytest tests/ -q`. Event listeners verify correct topics and payloads.

---

## Phase C — Feature Flag Activation (P1–P2)

### C.1 Activate signal_arbitration flag (M-8a) — VERIFIED

**Gap**: Config key `signal_arbitration` is `false` at `config/config.yaml:415`.
The plan previously referenced the non-existent key `use_signal_arbitration`.

```yaml
refactoring:
  feature_flags:
    signal_arbitration: false    # actual key (not "use_signal_arbitration")
```

**Design intent** (WS14 §10): "SignalArbitrator active: Default ON" with backtest results
matching pre-migration within float64 tolerance.

**Correction**:
1. Toggle `signal_arbitration: true` in `config/config.yaml:415`
2. Run full test suite — verify `python3 scripts/compare_baseline.py` matches 100%
3. If baseline diverges, keep `false` and document the delta

**Verification**: `python3 scripts/compare_baseline.py` shows 100% match.

---

### C.2 Activate event_bus flag (M-8b) — VERIFIED

**Gap**: Config key `event_bus` is `false` at `config/config.yaml:426`.
The plan previously referenced the non-existent key `enable_event_bus`.

```yaml
refactoring:
  feature_flags:
    event_bus: false    # actual key (not "enable_event_bus")
```

**Design intent** (WS14 §4): EventBus is additive — no regression risk.

**Correction**:
1. Toggle `event_bus: true` in `config/config.yaml:426`
2. Ensure no performance regression in pipeline (benchmark before/after)

**Verification**: `pytest tests/ -q`, no timeout or hang.

---

## Phase D — Infrastructure (P2)

### D.1 mypy configuration (M-7) — VERIFIED

**Gap**: No `[tool.mypy]` section in `pyproject.toml` (mypy is listed as dev dependency
at `pyproject.toml:43` but never configured). 466 `Dict[str, Any]` sites imply many type errors.

**Correction**:
1. Add to `pyproject.toml`:
   ```toml
   [tool.mypy]
   strict = false
   ignore_missing_imports = true
   disallow_untyped_defs = false
   exclude = ["tests/", "scripts/"]
   ```
2. Run `mypy src/uniquant/` to establish baseline
3. Fix top-10 module errors in `shared/` and `signal/` layers

**Verification**: `mypy src/uniquant/` error count decreases from baseline.

---

### D.2 Dict[str, Any] reduction pass (M-9) — VERIFIED

**Gap**: **466** `Dict[str, Any]` sites across `src/uniquant/`. The plan previously cited ~430.

**Design intent** (WS14 §10): "All 430+ Dict[str, Any] replaced: < 50 remain".

**Correction**:
1. Establish baseline: `rg "Dict\[str, Any\]" src/uniquant/ | wc -l`
2. Each sprint, replace 50-80 sites:
   - Priority 1: `brain/` engine return types (replace with existing typed dataclasses)
   - Priority 2: `services/` internal dicts (typed config/settings objects)
   - Priority 3: `data/` internal dicts (typed data containers)
3. Config-gate each migration per WS14 §3

**Verification**: Count decreases each sprint. Target: < 50.

---

## Phase E — Test Closure (P1–P2)

### E.1 Missing test files from test matrix (M-6) — VERIFIED

**Gap**: 6 of 7 test files from WS14 §4 test matrix do not exist. The plan previously cited
7 — `test_arbitrator.py` exists at `tests/signal/test_arbitrator.py` (187 lines, 12+ tests).

Missing files:

| # | File | Exists? | What to test |
|---|------|---------|-------------|
| 1 | `tests/shared/test_research_data_pack.py` | NO | `ResearchDataPack` creation, validation, backward compat |
| 2 | `tests/shared/test_decision_output.py` | NO | `DecisionOutput` creation, immutability, default timestamp |
| 3 | `tests/shared/test_candidate_signal.py` | NO | `CandidateSignal` creation, field constraints (after B.1) |
| 4 | `tests/shared/test_event_types.py` | NO | `Event`/`Command` creation, UUID, all domain event types |
| 5 | `tests/shared/test_factor_manifest.py` | NO | `FactorManifest` creation, validation, category |
| 6 | `tests/shared/test_factor_admission_gate.py` | NO | Admission checks, warn mode (after B.2) |
| — | `tests/signal/test_arbitrator.py` | YES | Already exists, do not recreate |

**Verification**: Each created file: `pytest <file> -xvs` passes.

---

## Execution Order (Recommended)

```
Week 1:  A.1, A.2, A.4       (Quick Wins — parallel)
         A.3, E.1 (1-2)       (Mechanical + test foundation)

Week 2:  B.1, B.3, E.1 (3-4) (Contracts + event wiring + tests)
         D.1                  (mypy baseline)

Week 3:  B.2, E.1 (5-6)      (FactorAdmissionGate + tests)
         C.1                  (signal_arbitration activation)

Week 4:  C.2, D.2 (sprint 1) (EventBus activation + Dict reduction)

Ongoing: D.2 (each sprint)    (Dict[str,Any] reduction toward <50)
```

---

## Rollback Criteria

| Item | Rollback trigger | Mechanism |
|------|-----------------|-----------|
| A.1 | Pipeline tests fail | Revert the `"lppl" in sig.reason.lower()` check |
| A.2 | `result.metadata` asserts fail | Revert populating `metadata=` in return |
| A.3 | Time-sensitive tests break | Revert each file independently |
| A.4 | Signal timestamp asserts fail | Revert `bar_date` parameter in `collect()` |
| B.1 | Type check errors cascade | Remove `CandidateSignal` from interfaces.py |
| B.2 | Factor registration blocked | Set `factor_gate_mode: "off"` |
| B.3 | Event emissions cause regressions | Remove EventBus wiring from services |
| C.1 | Baseline diverges > tolerance | Toggle `signal_arbitration: false` |
| C.2 | Performance regression > 10% | Toggle `event_bus: false` |

---

## Dependency Graph

```
A.1 ──→ (independent)
A.2 ──→ (independent)
A.3 ──→ (independent)
A.4 ──→ (independent)
 │
 ├──→ B.1 ──→ E.1 (test_candidate_signal)
 │           └──→ C.1 (requires CandidateSignal for arbitrator typed overload)
 │
 ├──→ B.2 ──→ E.1 (test_factor_admission_gate)
 │
 └──→ B.3 ──→ E.1 (test_event_types)
             └──→ C.2 (requires event wiring for bus activation)
```

Independent items can be parallelized. B.1 and B.2 are independent.
