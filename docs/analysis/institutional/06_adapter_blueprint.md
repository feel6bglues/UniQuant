# WS6 — Adapter Blueprint

Generated: 2026-06-10

Scope: Design the Brain -> Signal -> Portfolio -> Execution adapter architecture for UniQuant, using WS5 target contracts as prerequisites. This is a design artifact only; no source code changes are made here.

## 1. Objective

Resolve the current multi-adapter signal conflict problem, standardize NTF semantics, define deterministic `SignalArbitrator` behavior, and ensure risk vetoes cannot be bypassed by lower-priority BUY signals.

Primary inputs:

- `docs/analysis/institutional/02_data_lineage_audit.md`
- `docs/analysis/institutional/03_backtest_integrity_audit.md`
- `docs/analysis/institutional/04_historical_signal_series_blueprint.md`
- `docs/analysis/institutional/05_interface_contract_audit.md`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/brain/fsm/fsm.py`
- `src/uniquant/signal/aggregator.py`
- `src/uniquant/signal/models.py`

## 2. Current Adapter Chain

Current runtime chain:

```text
DataService.fetch_for_brain()
  -> data_pack: Dict[str, Any]
  -> AnalysisService._run_engines()
  -> DecisionBrain.make_decision(data_pack)
  -> decision: Dict[str, Any]
  -> UnifiedResearchPipeline._merge_decision_for_collection()
  -> collector_pack: Dict[str, Any]
  -> TradingSignalCollector.collect()
      -> LPPLAdapter
      -> CZSCAdapter
      -> WyckoffAdapter
      -> FSMAdapter
      -> RegimeAdapter
      -> NTFAdapter
      -> AlphaScoreAdapter
      -> MAStatusAdapter
  -> List[TradingSignal]
  -> UnifiedBacktestEngine.run()
```

Evidence:

- `TradingSignalCollector.collect()` appends signals from all adapters in fixed order (`src/uniquant/signal/adapters.py:434-525`).
- The current collector returns `List[TradingSignal]` directly; no arbitration step exists (`src/uniquant/signal/adapters.py:450-525`).
- `UnifiedBacktestEngine.run()` consumes daily signals in list order and stops after the first actionable BUY or SELL (`src/uniquant/hands/backtest/unified_engine.py:241-258`).

## 3. Current Adapter Matrix

| Adapter | Current input keys | Current output | Contract risk |
|---|---|---|---|
| `LPPLAdapter` | `risk_level`, `risk`, `confidence`, `bubble_confidence`, `price` | SELL on `Danger`, HOLD on `Warning`, HOLD otherwise | P1: HOLD can be ignored if later BUY appears |
| `CZSCAdapter` | `is_3rd_buy`, `bi_count`, `price` | BUY on third buy, HOLD otherwise | P1: BUY can bypass risk HOLD |
| `WyckoffAdapter` | `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad`, `price` | BUY/SELL/HOLD | P1: strategy signal, no veto semantics |
| `FSMAdapter` | `action`, `final_decision`, `shares`, `confidence`, `reason`, `price` | Maps DecisionBrain action to TradingSignal | P0/P1: should be authoritative but is just one adapter in list |
| `RegimeAdapter` | `regime` | HOLD on FROZEN/STRESSED | P1: veto-like HOLD lacks priority |
| `NTFAdapter` | `ntf_side`, `ntf_intensity`, `price` | BUY on LONG, SELL on SHORT, HOLD otherwise | P1: mismatches `SUPPORT`/`RESISTANCE` |
| `AlphaScoreAdapter` | `alpha_score`, `price` | BUY if > 0.6, SELL if < 0.3 | P1: can override risk intent via list order |
| `MAStatusAdapter` | `ma_status`, `price` | BUY on `>`, SELL on `<=` | P1: indicator signal, no risk awareness |

## 4. Findings

### Finding WS6-001 — Adapter collection is not arbitration (P0)

Evidence:

- `TradingSignalCollector.collect()` appends every adapter output and returns the list unchanged (`src/uniquant/signal/adapters.py:450-525`).
- `UnifiedBacktestEngine.run()` processes signals sequentially and breaks after first actionable BUY/SELL (`src/uniquant/hands/backtest/unified_engine.py:241-258`).

Impact:

- Execution intent depends on adapter append order.
- Risk-like HOLD signals from LPPL/Regime can coexist with later BUY signals.
- The system has multiple signal producers but no explicit policy for conflict resolution.

Risk Level: P0

Recommendation:

- Add a deterministic `SignalArbitrator` between `TradingSignalCollector` and `UnifiedBacktestEngine`.
- Collector should produce candidate intents; arbitrator should produce one final execution intent plus an audit trail.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS6-002 — DecisionBrain/FSM output should be authoritative for execution (P1)

Evidence:

- `DecisionBrain` implements veto/scoring architecture (`src/uniquant/brain/fsm/fsm.py:179-184`).
- `_check_veto_conditions()` returns `FORCE_WAIT` for frozen market or critical risk engine failure, and `FORCE_EXIT` for danger risk without policy support (`src/uniquant/brain/fsm/fsm.py:296-315`).
- `_check_buy_blockers()` blocks buy on LPPL danger, frozen market, failed critical engines, stop-loss issues, weak alpha, and limit-up/limit-down conditions (`src/uniquant/brain/fsm/fsm.py:385-417`).
- `FSMAdapter` maps `FORCE_WAIT` to HOLD, `FORCE_EXIT` to SELL, and `CIRCUIT_BREAK` to HOLD (`src/uniquant/signal/adapters.py:202-213`).

Impact:

- DecisionBrain already contains the highest-level risk and state logic, but the collector treats it as one peer adapter.
- Lower-level indicator adapters should not overrule DecisionBrain vetoes.

Risk Level: P1

Recommendation:

- Define `DecisionOutput` as the primary execution decision.
- Arbitrator policy: if `DecisionOutput.final_decision` is `FORCE_WAIT`, `CIRCUIT_BREAK`, or HOLD with `buy_blockers`, no BUY candidate may pass.
- If `DecisionOutput.final_decision` is `FORCE_EXIT`, SELL has highest priority unless execution constraints reject it.

Migration Cost: Low to Medium

Priority: Sprint 2

### Finding WS6-003 — NTF side vocabulary is inconsistent (P1)

Evidence:

- `NtfSide` enum defines `NONE`, `SUPPORT`, `RESISTANCE` (`src/uniquant/shared/interfaces.py:18-23`).
- `DecisionBrain` gives positive score when `ctx.ntf_side.value == "SUPPORT"` (`src/uniquant/brain/fsm/fsm.py:326-327`).
- `DecisionBrain` allows `risk == "Danger"` only if NTF side is `SUPPORT` (`src/uniquant/brain/fsm/fsm.py:311-314`).
- `NTFAdapter` maps only `LONG` to BUY and `SHORT` to SELL (`src/uniquant/signal/adapters.py:297-302`).

Impact:

- NTF `SUPPORT`/`RESISTANCE` values are recognized by DecisionBrain but not by the adapter.
- If the adapter is used independently, policy support may fail to become an actionable signal or diagnostic record.

Risk Level: P1

Recommendation:

- Canonicalize NTF side values:
  - `SUPPORT`: bullish/supportive policy context, maps to non-veto-positive context, not automatic BUY.
  - `RESISTANCE`: bearish/policy pressure context, maps to risk warning or SELL candidate only when intensity threshold is met.
  - `LONG` and `SHORT`: accepted as compatibility aliases only.
- Add adapter tests covering `SUPPORT`, `RESISTANCE`, `LONG`, `SHORT`, and `NONE`.

Migration Cost: Low

Priority: Sprint 2

### Finding WS6-004 — Existing `signal.aggregator` is research metadata aggregation, not execution arbitration (P1)

Evidence:

- `SignalAggregator.aggregate()` works on `signal.models.Signal`, not `TradingSignal` (`src/uniquant/signal/aggregator.py:102-122`).
- Aggregation methods include weighted average, majority vote, max confidence, and consensus threshold (`src/uniquant/signal/aggregator.py:26-31`).
- `TradingSignal` is the execution intent consumed by the backtest engine (`src/uniquant/shared/interfaces.py:127-169`).

Impact:

- Weighted-average research aggregation is useful for metadata and observability.
- It is not safe as an execution gate because risk vetoes must be absolute, not averaged.

Risk Level: P1

Recommendation:

- Keep `SignalAggregator` for research `Signal` objects.
- Add a separate `SignalArbitrator` for execution `TradingSignal` candidates.
- Never use weighted average to override `FORCE_WAIT`, `CIRCUIT_BREAK`, or `FORCE_EXIT`.

Migration Cost: Low

Priority: Sprint 2

### Finding WS6-005 — Adapter outputs lack explainable audit trail (P1)

Evidence:

- `TradingSignal` currently has `action`, `reason`, `confidence`, `shares`, `symbol`, `price`, `timestamp` only (`src/uniquant/shared/interfaces.py:127-141`).
- WS5 recommends adding metadata to `TradingSignal`.
- `TradingSignalCollector.collect()` discards adapter identity after appending the signal (`src/uniquant/signal/adapters.py:450-525`).

Impact:

- Backtest trades have reasons but not full signal provenance.
- It is difficult to explain why one candidate won over another.

Risk Level: P1

Recommendation:

- Target `TradingSignal.metadata` should include:
  - `source_adapter`
  - `raw_action`
  - `priority`
  - `veto`
  - `blockers`
  - `analysis_mode`
  - `bar_index`
  - `trace_id`
  - `arbitration_reason`

Migration Cost: Low

Priority: Sprint 2

### Finding WS6-006 — `default_shares` allows non-FSM BUY candidates to bypass risk sizing (P1)

Evidence:

- `CZSCAdapter`, `WyckoffAdapter`, `NTFAdapter`, `AlphaScoreAdapter`, and `MAStatusAdapter` use `default_shares` for BUY/SELL quantities (`src/uniquant/signal/adapters.py:127-135`, `src/uniquant/signal/adapters.py:180-188`, `src/uniquant/signal/adapters.py:302-310`, `src/uniquant/signal/adapters.py:338-346`, `src/uniquant/signal/adapters.py:374-382`).
- `DecisionBrain._execute_buy()` calls `PositionSizer.calculate_shares()` and returns risk-sized shares (`src/uniquant/brain/fsm/fsm.py:419-450`).

Impact:

- Lower-level indicator BUY signals can create executable quantity without risk sizing.

Risk Level: P1

Recommendation:

- Arbitrator must require BUY size from `DecisionOutput.shares` or a `PositionSizer` gate.
- Non-FSM adapter BUY candidates should be classified as evidence/intent, not executable order quantity.

Migration Cost: Medium

Priority: Sprint 2

## 5. Target Adapter Architecture

Target chain:

```text
ResearchDataPack
  -> MarketSignalContext
  -> DecisionBrain
  -> DecisionOutput
  -> AdapterRegistry
      -> CandidateSignal list
  -> SignalArbitrator
      -> final TradingSignal
      -> arbitration_report
  -> UnifiedBacktestEngine
```

Design principle:

```text
Adapters translate.
Arbitrator decides.
Risk vetoes dominate.
Execution receives exactly one final intent per symbol/date.
```

## 6. Target Types

### 6.1 `CandidateSignal`

```python
@dataclass
class CandidateSignal:
    source: str
    action: str  # BUY | SELL | HOLD | FORCE_WAIT | FORCE_EXIT | CIRCUIT_BREAK
    direction: int  # 1 bullish, -1 bearish, 0 neutral
    confidence: float
    reason: str
    symbol: str
    timestamp: datetime
    price: float = 0.0
    suggested_shares: int = 0
    veto: bool = False
    priority: int = 0
    blockers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Rules:

- Adapters produce `CandidateSignal`, not final execution `TradingSignal`.
- Compatibility path may still emit `TradingSignal`, but it should be converted into `CandidateSignal` before arbitration.

### 6.2 `ArbitrationReport`

```python
@dataclass
class ArbitrationReport:
    symbol: str
    timestamp: datetime
    final_action: str
    final_reason: str
    selected_source: str
    candidates: list[CandidateSignal]
    veto_sources: list[str] = field(default_factory=list)
    rejected_sources: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    analysis_mode: str = "approximate_research"
    bar_index: int = -1
```

### 6.3 `SignalArbitrator`

```python
class SignalArbitrator:
    def arbitrate(
        self,
        decision: DecisionOutput,
        candidates: list[CandidateSignal],
        context: MarketSignalContext,
    ) -> tuple[TradingSignal, ArbitrationReport]:
        ...
```

## 7. Arbitration Policy

Deterministic priority order:

| Priority | Condition | Final action | Rationale |
|---:|---|---|---|
| 1000 | `DecisionOutput.final_decision == "CIRCUIT_BREAK"` | HOLD | Circuit break blocks trading |
| 950 | `DecisionOutput.final_decision == "FORCE_WAIT"` | HOLD | Critical risk engine unavailable or frozen market |
| 900 | `DecisionOutput.final_decision == "FORCE_EXIT"` | SELL | Macro/risk forced exit |
| 850 | `DecisionOutput.buy_blockers` non-empty | HOLD | BUY must be blocked |
| 800 | `DecisionOutput.sell_triggers` non-empty and not sell-limit-blocked | SELL | DecisionBrain sell logic |
| 700 | `DecisionOutput.final_decision in {"BUY", "ADD"}` and shares > 0 | BUY | Risk-sized decision BUY |
| 600 | Strong SELL candidate from LPPL/Wyckoff/Alpha/MA | SELL | Secondary exit evidence |
| 500 | Strong BUY consensus from non-FSM candidates and risk allows | BUY | Optional, only if risk gate approves |
| 0 | No actionable evidence | HOLD | Default no-trade |

Hard rules:

- `FORCE_WAIT` and `CIRCUIT_BREAK` cannot be overridden by any BUY.
- BUY cannot be executable without risk-sized shares.
- Non-FSM BUY candidates require explicit risk gate approval.
- HOLD from Regime/LPPL is treated as veto only if it has veto metadata or maps to `FORCE_WAIT`.
- SELL may be blocked by limit-down execution constraints later; arbitrator should preserve intent and let execution reject if necessary.

## 8. NTF Semantic Standard

Canonical values:

| Incoming value | Canonical value | Direction | Execution semantics |
|---|---|---:|---|
| `NONE` | `NONE` | 0 | No candidate |
| `SUPPORT` | `SUPPORT` | +1 | Policy support; not automatic BUY |
| `RESISTANCE` | `RESISTANCE` | -1 | Policy resistance; risk warning / possible SELL candidate |
| `LONG` | `SUPPORT` | +1 | Compatibility alias |
| `SHORT` | `RESISTANCE` | -1 | Compatibility alias |

Adapter behavior:

- `SUPPORT` with high intensity becomes positive evidence candidate, not direct executable BUY.
- `RESISTANCE` with high intensity becomes risk/SELL evidence candidate.
- DecisionBrain remains authoritative for whether support can override danger risk.

## 9. Adapter Blueprint

### 9.1 `SignalAdapter`

```python
class SignalAdapter(Protocol):
    source: str

    def adapt(
        self,
        context: MarketSignalContext,
        decision: DecisionOutput,
        timestamp: datetime,
    ) -> list[CandidateSignal]:
        ...
```

### 9.2 Adapter responsibilities

| Adapter | Target responsibility | Must not do |
|---|---|---|
| LPPL | Emit risk/exit/veto evidence from bubble risk | Decide final BUY |
| CZSC | Emit structure BUY evidence | Size position |
| Wyckoff | Emit accumulation/distribution evidence | Override risk veto |
| FSM | Convert `DecisionOutput` into authoritative candidate | Compete as low-priority peer |
| Regime | Emit market-risk veto evidence | Produce direct BUY |
| NTF | Emit SUPPORT/RESISTANCE evidence | Treat SUPPORT as automatic BUY |
| AlphaScore | Emit alpha strength evidence | Override risk sizing |
| MAStatus | Emit trend evidence | Override forced exits |

### 9.3 PortfolioAdapter

```python
class PortfolioAdapter:
    def to_portfolio_target(
        self,
        signal: TradingSignal,
        portfolio_state: PortfolioState,
    ) -> PortfolioTarget:
        ...
```

Purpose:

- Convert final execution intent into target holdings.
- Enforce max single-name concentration, portfolio cash, and existing position awareness.
- Required before multi-symbol research moves beyond single-symbol backtests.

### 9.4 ExecutionAdapter

```python
class ExecutionAdapter:
    def to_order_intent(
        self,
        target: PortfolioTarget,
        market_rules: MarketRules,
    ) -> OrderIntent:
        ...
```

Purpose:

- Convert portfolio target into simulated order intent.
- Remains broker-agnostic in current research platform scope.
- Live broker adapter remains WS13 deferred scope.

## 10. Migration Strategy

| Step | Change | Compatibility | Risk |
|---|---|---|---|
| 1 | Add `CandidateSignal` and `ArbitrationReport` to target contract docs | No code | Low |
| 2 | Add `SignalArbitrator` class behind feature flag | Existing collector unchanged | Low |
| 3 | Wrap current `TradingSignal` outputs into `CandidateSignal` | Backward compatible | Medium |
| 4 | Add `TradingSignal.metadata` and `arbitration_report` persistence | Backward compatible if default dict | Low |
| 5 | Make `UnifiedResearchPipeline` use arbitrator before backtest | Feature flag default off | Medium |
| 6 | Turn arbitrator on for historical mode | Config-gated | Medium |
| 7 | Deprecate direct `List[TradingSignal]` collector output for execution | Keep for tests/tools | Medium |

Rollback:

- Keep current `TradingSignalCollector.collect()` as compatibility path.
- Gate new arbitration path with config:

```yaml
pipeline:
  signal_arbitration: false
```

## 11. Test Matrix

### Unit tests

| Test | Assertion |
|---|---|
| `test_force_wait_veto_blocks_buy` | `FORCE_WAIT` + CZSC BUY => final HOLD |
| `test_circuit_break_blocks_all` | `CIRCUIT_BREAK` + any BUY/SELL => final HOLD |
| `test_force_exit_wins_over_buy` | `FORCE_EXIT` + CZSC BUY => final SELL |
| `test_buy_requires_risk_sized_shares` | Non-FSM BUY with no sized shares cannot execute |
| `test_ntf_support_alias_long` | `LONG` normalizes to `SUPPORT` |
| `test_ntf_resistance_alias_short` | `SHORT` normalizes to `RESISTANCE` |
| `test_support_not_automatic_buy` | `SUPPORT` creates evidence but not executable BUY |
| `test_adapter_provenance_metadata` | Candidate contains source, priority, trace_id |

### Integration tests

| Test | Assertion |
|---|---|
| `test_collector_arbitrator_pipeline` | Collector candidates produce one final `TradingSignal` |
| `test_pipeline_arbitration_feature_flag_off` | Current behavior remains when flag is false |
| `test_pipeline_arbitration_feature_flag_on` | New behavior produces arbitration report |
| `test_historical_signal_runner_uses_arbitrator` | Historical mode stamps bar date and arbitrates per bar |
| `test_risk_veto_not_bypassed_by_adapter_buy` | LPPL/Regime veto blocks lower-level BUY |

### Contract tests

| Test | Assertion |
|---|---|
| `test_decision_output_to_fsm_candidate` | `DecisionOutput` converts to authoritative candidate |
| `test_research_data_pack_to_market_context` | Typed context supports adapter inputs |
| `test_candidate_to_trading_signal` | Final candidate converts to `TradingSignal` |
| `test_arbitration_report_serializable` | Report can be stored in signal metadata |

## 12. Sprint 2 Dependencies

WS6 feeds:

- WS10 Research Risk Governance:
  - risk veto priority
  - position sizing authority
  - concentration and drawdown gate placement

- WS7 Factor Admission Governance:
  - factor signals should enter as `CandidateSignal(source="factor")`
  - factor admission status should be metadata, not direct execution permission

- WS14 TDD Refactoring Design:
  - target contracts
  - migration sequence
  - tests and feature flags

## 13. Verification Checklist

- [x] Mapped current adapters and their input/output behavior.
- [x] Identified current collector-vs-arbitration gap.
- [x] Defined `SignalArbitrator` target design.
- [x] Defined deterministic arbitration priority.
- [x] Standardized NTF SUPPORT/RESISTANCE vs LONG/SHORT semantics.
- [x] Preserved `TradingSignal` as execution intent.
- [x] Preserved `Signal` as research metadata.
- [x] Separated research aggregation from execution arbitration.
- [x] Defined PortfolioAdapter and ExecutionAdapter blueprint.
- [x] Defined migration strategy and rollback feature flag.
- [x] Defined unit, integration, and contract test matrix.

