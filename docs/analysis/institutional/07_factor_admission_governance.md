# WS7 — Factor Admission Governance

Generated: 2026-06-10

Scope: Define the institutional factor admission process for UniQuant. A factor must pass schema, look-ahead, IC/IR, walk-forward OOS, PBO, redundancy, tradability, risk, and cost-aware gates before it can influence `CandidateSignal(source="factor")`, composite weights, or production research reports.

This is a design/audit artifact only. No source code changes are made here.

## 1. Objective

Convert the current factor research toolkit into a governed admission process:

```text
candidate factor
  -> schema gate
  -> calculation safety gate
  -> look-ahead gate
  -> in-sample IC/IR gate
  -> walk-forward OOS gate
  -> PBO / overfit gate
  -> redundancy gate
  -> A-share tradability gate
  -> cost-aware backtest gate
  -> admission report
  -> admitted factor registry
```

Only admitted factors may feed:

- `FactorComposer` production weights.
- `CandidateSignal(source="factor")` in WS6.
- Research reports labeled as institutionally validated.

## 2. Current Factor System

Current components:

| Component | Current capability | Evidence |
|---|---|---|
| `FactorRegistry` | Thread-safe singleton, stores `FactorInfo`, applies `config/factors.yaml` overrides | `src/uniquant/brain/factors/registry.py:16-25`, `src/uniquant/brain/factors/registry.py:54-95` |
| `FactorComposer` | Computes enabled factors, z-score normalizes, orthogonalizes, builds `composite_score` | `src/uniquant/brain/factors/composer.py:82-136`, `src/uniquant/brain/factors/composer.py:206-232` |
| `FactorAnalyzer` | Computes Rank IC/ICIR, blocks LIVE mode for forward returns | `src/uniquant/brain/factors/analyzer.py:243-360`, `src/uniquant/brain/factors/analyzer.py:283-288` |
| `check_lookahead_leakage()` | Future perturbation invariance test | `src/uniquant/brain/factors/analyzer.py:25-84` |
| `WalkForwardFactorPipeline` | Temporal train/test split, OOS composite IC, weight stability | `src/uniquant/brain/factors/walk_forward_pipeline.py:62-78`, `src/uniquant/brain/factors/walk_forward_pipeline.py:153-228` |
| Auto-mined generator | Genetic factor miner with stated Reaper rule: `PBO < 0.2` and `OOS IC > 0.03` | `src/uniquant/brain/factors/auto_mined/generator.py:1-14` |
| Config | Enables/weights factors in `config/factors.yaml` | `config/factors.yaml:1-15` |

Current gap:

```text
The tools exist, but there is no single admission object, report, or registry state
that says: this factor passed all institutional gates and may enter execution-facing
research workflows.
```

## 3. Admission Findings

### Finding WS7-001 — No canonical factor admission gate exists (P1)

Evidence:

- `FactorRegistry.register()` accepts factor name, compute function, category, weight, description; it has no admission status, report id, universe, IC/OOS/PBO metrics, or validation timestamp (`src/uniquant/brain/factors/registry.py:54-95`).
- `FactorInfo` has only `ic_ir_history: Optional[List[float]]`, not a structured admission record (`src/uniquant/brain/factors/registry.py:16-25`).
- `config/factors.yaml` can enable and weight a factor without referencing an admission report (`config/factors.yaml:1-15`).

Impact:

- A factor can be enabled because it is registered/configured, not because it passed institutional validation.
- Research users may mistake registration for admission.

Risk Level: P1

Recommendation:

- Add a `FactorAdmissionReport` target contract.
- Add `admission_status` to factor metadata: `candidate`, `admitted`, `rejected`, `quarantined`, `deprecated`.
- Require report id and timestamp before a factor can be enabled for production research.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS7-002 — `pe_ttm` config drift creates false activation risk (P1)

Evidence:

- `config/factors.yaml` enables `pe_ttm` as fundamental factor (`config/factors.yaml:12-15`).
- Stage 4 found `pe_ttm` is configured but not registered by current `custom_factors.py`.
- `FactorRegistry.get_enabled()` only returns registered factors (`src/uniquant/brain/factors/registry.py:105-109`).

Impact:

- Config suggests a factor is active while runtime registry may not contain it.
- Fundamental factor coverage can be overstated in reports.

Risk Level: P1

Recommendation:

- Add config-vs-registry validation: every configured enabled factor must exist in `FactorRegistry`.
- Missing configured factors should fail the admission report or mark the factor as `MISSING_REGISTRATION`.

Migration Cost: Low

Priority: Sprint 2

### Finding WS7-003 — Walk-forward `factor_func` path has a real integration mismatch (P1)

Evidence:

- `WalkForwardFactorPipeline.run(..., factor_func=None)` calls `check_lookahead_leakage()` when `factor_func` is provided (`src/uniquant/brain/factors/walk_forward_pipeline.py:126-132`).
- It then calls `self.analyzer.compute_ic_ir(..., factor_func=factor_func)` (`src/uniquant/brain/factors/walk_forward_pipeline.py:134-143`).
- `FactorAnalyzer.compute_ic_ir()` has no `factor_func` parameter (`src/uniquant/brain/factors/analyzer.py:243-253`).

Impact:

- The direct candidate-factor path that should enforce look-ahead checking can fail at runtime.
- Admission cannot rely on this path until it is fixed or avoided.

Risk Level: P1

Recommendation:

- In the target design, admission must first materialize candidate factor columns, then call `compute_ic_ir()` on those columns.
- Add a contract test for `WalkForwardFactorPipeline.run(factor_func=...)`.

Migration Cost: Low

Priority: Sprint 2

### Finding WS7-004 — IC/IR live-mode guard is strong but admission must label it offline-only (P2)

Evidence:

- `FactorAnalyzer.compute_ic_ir()` raises in `AnalysisMode.LIVE` because it uses future returns (`src/uniquant/brain/factors/analyzer.py:283-288`).
- Forward returns are generated with grouped negative shift (`src/uniquant/brain/factors/analyzer.py:297-302`).

Impact:

- IC/IR is valid for offline labeling, but unsafe if accidentally used as live signal generation.

Risk Level: P2

Recommendation:

- Every admission report must include `evaluation_mode="backtest/offline"` and `live_safe=False` for forward-return metrics.
- Factor value computation can be live-safe; factor efficacy labeling is not.

Migration Cost: Low

Priority: Sprint 2

### Finding WS7-005 — PBO exists as concept but not as enforced pipeline gate (P1)

Evidence:

- Auto-mined generator docstring states Reaper rule: `PBO < 0.2 ∧ OOS IC > 0.03` (`src/uniquant/brain/factors/auto_mined/generator.py:8-10`).
- Stage 4 found PBO is implemented in experiment scripts rather than formalized as an admission gate.

Impact:

- Auto-mined or hand-picked factors can pass informal review without a reproducible overfit score.

Risk Level: P1

Recommendation:

- Add PBO to `FactorAdmissionReport`.
- Require PBO below threshold before `admission_status="admitted"`.
- Use `PBO < 0.2` as initial institutional threshold unless changed by config.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS7-006 — Weight semantics are inconsistent across Composer and WalkForward (P1)

Evidence:

- `FactorComposer._resolve_weights()` uses signed ICIR when available (`src/uniquant/brain/factors/composer.py:151-174`).
- `WalkForwardFactorPipeline._compute_weights()` uses absolute ICIR (`src/uniquant/brain/factors/walk_forward_pipeline.py:80-103`).

Impact:

- The same factor can receive different sign/weight treatment in production composition vs walk-forward evaluation.
- A negative-premium factor might be inverted in one path but not another.

Risk Level: P1

Recommendation:

- Factor manifest must include `direction_policy`:
  - `higher_is_better`
  - `lower_is_better`
  - `signed_ic`
  - `absolute_ic_with_declared_direction`
- Choose one default policy and enforce it in both Composer and WalkForward.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS7-007 — Factor metadata lacks required columns, lookback, direction, and live-safety fields (P1)

Evidence:

- `FactorInfo` includes name, category, compute function, default weight, enabled, description, optional history only (`src/uniquant/brain/factors/registry.py:16-25`).
- Individual factor functions encode assumptions in comments or local checks; no registry-level manifest enforces them.

Impact:

- Admission cannot automatically validate whether input data satisfies factor requirements.
- Live-safe status and lookback warmup are implicit.

Risk Level: P1

Recommendation:

- Add `FactorManifest` target contract with:
  - `required_columns`
  - `lookback_bars`
  - `category`
  - `direction_policy`
  - `live_safe_compute`
  - `requires_neutralization`
  - `min_history_days`
  - `tradability_filters_required`

Migration Cost: Medium

Priority: Sprint 2

### Finding WS7-008 — A-share tradability is not part of factor admission (P1)

Evidence:

- Stage 3 found backtest/matching handles T+1, limits, suspension, costs, and slippage in execution.
- Factor IC/OOS evaluation in `FactorAnalyzer` uses cross-sectional forward returns, not tradability-adjusted returns (`src/uniquant/brain/factors/analyzer.py:297-329`).
- `WalkForwardFactorPipeline` evaluates `composite_score` OOS IC, not cost/tradability-adjusted portfolio return (`src/uniquant/brain/factors/walk_forward_pipeline.py:185-198`).

Impact:

- A factor can look strong statistically but fail after limit-up/down, suspension, ST, liquidity, lot size, T+1, and cost constraints.

Risk Level: P1

Recommendation:

- Admission must include a tradability/cost-aware gate after IC/OOS:
  - remove or flag suspended bars
  - exclude ST or evaluate separately
  - apply limit-up/down feasibility
  - apply volume/liquidity thresholds
  - run cost-aware factor portfolio backtest

Migration Cost: High

Priority: Sprint 2 design, Sprint 3 implementation

### Finding WS7-009 — Auto-mined factors are transitional and should remain quarantined (P1)

Evidence:

- Current worktree shows many old `auto_mined` factor files deleted and new `factor_001.py` to `factor_025.py` files untracked.
- `auto_mined/generator.py` exposes a new controlled mining framework with complexity limits and Reaper criteria (`src/uniquant/brain/factors/auto_mined/generator.py:1-14`).

Impact:

- The auto-mined factor set is not in a stable admitted state.
- Accidentally enabling generated factors before reports exist can reintroduce overfitting risk.

Risk Level: P1

Recommendation:

- Mark all auto-mined factors as `candidate` or `quarantined` until each has a report id and passes admission gates.
- Do not include auto-mined factors in production composite score by default.

Migration Cost: Low

Priority: Sprint 2

### Finding WS7-010 — Factor signals must enter WS6 as evidence, not direct execution (P1)

Evidence:

- WS6 defines `CandidateSignal(source="factor")` and states factor admission status should be metadata, not direct execution permission.
- WS10 defines SignalArbitrator as the risk gate where PositionSizer, veto rules, and default_shares governance converge.

Impact:

- Even admitted factors should not bypass DecisionBrain/risk governance.
- Factor output should contribute evidence and confidence, not direct order size.

Risk Level: P1

Recommendation:

- Define `FactorSignalAdapter` target:
  - accepted input: admitted `FactorAdmissionReport` + current factor values
  - output: `CandidateSignal(source="factor", suggested_shares=0)`
  - execution quantity: always provided by `SignalArbitrator` + risk sizing

Migration Cost: Low

Priority: Sprint 2

## 4. Target Contracts

### 4.1 `FactorManifest`

```python
@dataclass
class FactorManifest:
    name: str
    category: str
    required_columns: list[str]
    lookback_bars: int
    direction_policy: str  # higher_is_better | lower_is_better | signed_ic | absolute_ic_with_declared_direction
    live_safe_compute: bool
    requires_neutralization: bool = False
    min_history_days: int = 252
    tradability_filters_required: bool = True
    description: str = ""
```

### 4.2 `FactorAdmissionReport`

```python
@dataclass
class FactorAdmissionReport:
    factor_name: str
    factor_version: str
    factor_hash: str
    admission_status: str  # candidate | admitted | rejected | quarantined | deprecated
    generated_at: datetime
    data_source: str
    universe: str
    start_date: str
    end_date: str
    manifest: FactorManifest

    # Safety
    schema_passed: bool
    calculation_safety_passed: bool
    lookahead_passed: bool
    live_safe_compute: bool

    # IC / OOS
    ic_mean_by_horizon: dict[int, float]
    icir_by_horizon: dict[int, float]
    ic_positive_ratio_by_horizon: dict[int, float]
    oos_ic_mean: float
    oos_icir: float
    weight_stability: dict[str, float]

    # Overfit / redundancy
    pbo: float
    max_correlation_to_admitted: float
    redundancy_passed: bool

    # Tradability / cost
    tradability_passed: bool
    cost_adjusted_return: float
    turnover: float
    max_drawdown: float

    # Final
    passed_gates: list[str]
    failed_gates: list[str]
    warnings: list[str]
```

### 4.3 `FactorAdmissionGate`

```python
class FactorAdmissionGate:
    def evaluate(
        self,
        factor_func: Callable,
        manifest: FactorManifest,
        data: pd.DataFrame,
        admitted_factors: list[FactorAdmissionReport],
        config: FactorAdmissionConfig,
    ) -> FactorAdmissionReport:
        ...
```

## 5. Initial Gate Thresholds

These are starting thresholds. They should move to config before implementation.

| Gate | Initial threshold | Notes |
|---|---:|---|
| Minimum train days | 504 | About 2 trading years |
| Minimum test days | 63 | About 1 quarter |
| Minimum symbols | 300 | Avoid tiny hand-picked universe |
| Abs in-sample IC mean | >= 0.015 | Screening threshold only |
| In-sample ICIR | >= 0.20 | Weak but useful initial gate |
| IC positive ratio | >= 0.52 | Avoid random sign |
| OOS IC mean | >= 0.01 | Must survive OOS |
| OOS ICIR | >= 0.10 | Stability gate |
| Auto-mined OOS IC | >= 0.03 | From generator Reaper rule |
| PBO | < 0.20 | From generator Reaper rule |
| Max correlation to admitted factors | < 0.80 | Redundancy gate |
| Cost-adjusted return | > 0 | Must survive costs |
| Max drawdown | below configured risk limit | Coordinate with WS10 |

## 6. Admission Workflow

```text
1. Candidate registration
   - factor function
   - FactorManifest
   - version/hash

2. Schema gate
   - required columns present
   - lookback warmup valid
   - output length equals input length

3. Calculation safety gate
   - no Inf
   - NaN only in allowed warmup range
   - no cross-symbol contamination

4. Look-ahead gate
   - check_lookahead_leakage()
   - strict temporal split

5. In-sample IC/IR gate
   - FactorAnalyzer.compute_ic_ir()
   - multiple horizons: 1/5/20

6. Walk-forward OOS gate
   - WalkForwardFactorPipeline
   - OOS IC mean / ICIR / weight stability

7. PBO / overfit gate
   - combinatorial or random-combo PBO
   - must be below threshold

8. Redundancy gate
   - correlation against admitted factors
   - reject/merge redundant factors

9. A-share tradability gate
   - ST/suspension/limit/liquidity filters
   - point-in-time universe when available

10. Cost-aware backtest gate
   - commission, stamp duty, transfer fee, slippage, lot size, T+1

11. Admission decision
   - write FactorAdmissionReport
   - admitted factors may enter FactorComposer/FactorSignalAdapter
```

## 7. Integration With WS6 and WS10

### Factor to Signal path

```text
Admitted factor values
  -> FactorSignalAdapter
  -> CandidateSignal(source="factor", suggested_shares=0)
  -> SignalArbitrator
  -> risk sizing gate
  -> final TradingSignal
```

Rules:

- Factor candidates never carry executable quantity.
- Factor admission status must be present in `CandidateSignal.metadata`.
- `SignalArbitrator` rejects factor-origin BUY candidates if:
  - factor is not admitted,
  - risk veto is active,
  - PositionSizer rejects or returns zero shares,
  - survivorship/tradability warning is hard-fail.

### Risk governance handoff

WS10 controls must be checked before factor evidence can become an executable trade:

- Position sizing gate.
- Single-name concentration.
- Drawdown circuit breaker.
- Survivorship/selection warnings.
- `default_shares` governance.

## 8. Migration Strategy

| Step | Change | Scope | Risk |
|---|---|---|---|
| 1 | Add factor admission report schema in docs | Docs only | Low |
| 2 | Add config-vs-registry validation proposal | Design | Low |
| 3 | Create `FactorManifest` for existing manual factors | New metadata | Medium |
| 4 | Fix `WalkForwardFactorPipeline.run(factor_func=...)` path | Code later | Low |
| 5 | Create `FactorAdmissionGate` and report writer | New code later | Medium |
| 6 | Quarantine auto-mined factors by default | Config/registry later | Low |
| 7 | Add `FactorSignalAdapter` into WS6 candidate flow | Adapter later | Medium |
| 8 | Require admission report before enabling production factor weights | Governance later | Medium |

Rollback:

- Existing `FactorRegistry` and `FactorComposer` remain usable.
- Admission gate starts as report-only.
- Production enablement is config-gated after reports are stable.

## 9. Test Matrix

### Unit tests

| Test | Assertion |
|---|---|
| `test_factor_manifest_required_columns` | Missing required columns fails schema gate |
| `test_factor_output_length_guard` | Output length mismatch fails admission |
| `test_factor_no_inf` | Inf output fails safety gate |
| `test_factor_nan_warmup_allowed_only` | NaN outside warmup fails |
| `test_factor_live_ic_rejected` | `compute_ic_ir(mode=LIVE)` raises |
| `test_config_factor_must_register` | Enabled config factor missing from registry fails validation |

### Integration tests

| Test | Assertion |
|---|---|
| `test_walk_forward_factor_func_real_path` | `factor_func` admission path does not raise unexpected `TypeError` |
| `test_factor_admission_report_serializable` | Admission report can be saved/reloaded |
| `test_factor_signal_adapter_requires_admitted_factor` | Rejected/quarantined factor cannot emit execution candidate |
| `test_factor_candidate_has_zero_suggested_shares` | Factor candidates do not bypass risk sizing |
| `test_factor_candidate_arbitrator_risk_gate` | Factor BUY evidence is blocked by FORCE_WAIT |

### Bias and robustness tests

| Test | Assertion |
|---|---|
| `test_lookahead_perturbation_detects_future_dependency` | Future-dependent factor fails |
| `test_walk_forward_train_test_no_overlap` | Train dates are strictly before test dates |
| `test_pbo_threshold_blocks_overfit_factor` | High-PBO factor is rejected |
| `test_redundant_factor_rejected` | High-correlation factor fails redundancy gate |
| `test_cost_aware_gate_blocks_untradable_factor` | Positive IC but negative cost-adjusted result is rejected |

## 10. Admission Status Semantics

| Status | Meaning | May enter FactorComposer? | May emit CandidateSignal? |
|---|---|---:|---:|
| `candidate` | Registered for research evaluation only | No | No |
| `admitted` | Passed all required gates | Yes | Yes, as evidence only |
| `rejected` | Failed required gate | No | No |
| `quarantined` | Unstable, auto-mined, or missing report | No | No |
| `deprecated` | Previously admitted but retired | No | No |

## 11. Sprint 2 Completion Criteria

WS7 is complete when:

- [x] Factor admission gates are defined.
- [x] IC/IR, OOS, PBO, redundancy, tradability, and cost-aware requirements are explicit.
- [x] Factor signal integration with WS6 `SignalArbitrator` is defined.
- [x] Risk governance handoff to WS10 is defined.
- [x] Auto-mined factors are classified as non-admitted until reports exist.
- [x] Test matrix exists for future implementation.

## 12. Verification Checklist

- [x] Audited current factor registry and config drift.
- [x] Audited FactorAnalyzer live-mode guard and forward-return labeling.
- [x] Audited WalkForwardFactorPipeline train/test split and `factor_func` mismatch.
- [x] Audited weight policy inconsistency between Composer and WalkForward.
- [x] Defined `FactorManifest`.
- [x] Defined `FactorAdmissionReport`.
- [x] Defined initial gate thresholds.
- [x] Defined integration with `CandidateSignal(source="factor")`.
- [x] Defined tests and migration strategy.

