# Test Run Log - 2026-06-05

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

## Context

Workspace: `/home/james/Documents/Project/UniQuant`

Interpreter: `.venv/bin/python`

Pytest: `.venv/bin/pytest`

Note: the worktree already contained many uncommitted changes before this test run. This log records observed test results only; no source code was changed for these runs.

## Run 1 - Full Test Collection

Command:

```bash
.venv/bin/pytest tests -q
```

Result: failed during collection.

Collection errors:

1. `tests/test_drawdown_analyzer.py`
   - Error: `ModuleNotFoundError: No module named 'src'`
   - Immediate reading: legacy `src.uniquant...` import path or pytest path configuration mismatch.

2. `tests/test_refactoring_validation.py`
   - Error: `ImportError: cannot import name 'check_lookahead_leakage' from 'uniquant.brain.factors.analyzer'`
   - Immediate reading: test expects `check_lookahead_leakage` and `LookaheadBiasError`, but current `analyzer.py` does not export them.

3. `tests/test_verify_tdx_import.py`
   - Error: `ModuleNotFoundError: No module named 'scripts'`
   - Immediate reading: script import path/package visibility issue during pytest collection.

## Run 2 - Full Suite Excluding Collection Blockers

Command:

```bash
.venv/bin/pytest tests -q \
  --ignore=tests/test_drawdown_analyzer.py \
  --ignore=tests/test_refactoring_validation.py \
  --ignore=tests/test_verify_tdx_import.py
```

Result:

- `936 passed`
- `8 failed`
- `6 skipped`
- `35 warnings`
- Duration: `33.27s`

Failures:

1. `tests/chaos/test_e2e_pipeline.py::test_e2e_pipeline`
   - Error: `UnifiedMatchingEngine.fill_buy() got an unexpected keyword argument 'volumes'`
   - Category: interface drift.

2. `tests/test_analysis_engines.py::TestLpplAnalysisEngine::test_run_lppl_analysis_none_df_reads_from_lake`
   - Error: expected `mock_orchestrator.data_service.lake.read_data` to be called once, called zero times.
   - Category: LPPL data-loading behavior drift.

3. `tests/test_analysis_engines.py::TestLpplAnalysisEngine::test_fallback_lppl_analysis`
   - Error: `LpplAnalysisEngine` has no attribute `_fallback_lppl_analysis`.
   - Category: missing compatibility method.

4. `tests/test_di_container_and_cache.py::TestDIContainer::test_register_get_reset_and_clear`
   - Error: `ServiceContainer` has no attribute `register_factory`.
   - Category: DI container API drift.

5. `tests/test_error_handling_additional.py::TestErrorHandlingHelpers::test_specialized_wrappers`
   - Error: `handle_network_errors(default_return=...)` re-raises `requests.RequestException` instead of returning default value.
   - Category: error-handling behavior regression.

6. `tests/test_lppl_engine_scan_windows.py::test_scan_all_windows_selects_best_result_per_bucket`
   - Error: expected 3 LPPL scan bucket results, got 4.
   - Category: LPPL window bucketing behavior drift.

7. `tests/test_offline_entry.py::test_offline_full_test_wrapper_compiles`
   - Error: missing `scripts/offline_full_test.py`.
   - Category: missing script artifact.

8. `tests/test_results_protocol.py::TestChiefReviewCompatibility::test_analyze_single_date_folder_supports_new_result_schema`
   - Error: missing `scripts/generate_chief_review.py`.
   - Category: missing script artifact.

## Current Triage

Priority order:

1. Fix collection errors first; without this, full CI cannot produce a stable total.
2. Fix interface drift in matching engine, DI container, and LPPL analysis compatibility.
3. Fix behavior regressions in error handling and LPPL scan bucketing.
4. Restore or update tests for missing script artifacts.

## Run 3 - Collection Blockers With `PYTHONPATH=.`

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_drawdown_analyzer.py \
  tests/test_refactoring_validation.py \
  tests/test_verify_tdx_import.py \
  -q
```

Result: failed during collection.

Observed change:

- The previous `src` and `scripts` import errors did not recur with `PYTHONPATH=.`.
- Remaining blocker is a real source/API gap:
  - `tests/test_refactoring_validation.py`
  - Error: `ImportError: cannot import name 'check_lookahead_leakage' from 'uniquant.brain.factors.analyzer'`

Additional observation:

- Importing this test group triggers package side effects: cache backend creation, AkShare initialization, factor registration, and Matplotlib cache/font setup.
- This is not a test assertion failure, but it is a startup/test-isolation smell.

## Run 4 - Path-Sensitive Tests With `PYTHONPATH=.`

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_drawdown_analyzer.py \
  tests/test_verify_tdx_import.py \
  -q
```

Result:

- `10 passed`
- Duration: `0.54s`

Conclusion:

- `tests/test_drawdown_analyzer.py` and `tests/test_verify_tdx_import.py` are not business failures when the repository root is on `PYTHONPATH`.
- The remaining collection blocker is isolated to `tests/test_refactoring_validation.py`, which expects missing analyzer API exports.

## Run 5 - Isolated Refactoring Validation Test

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_refactoring_validation.py -q
```

Result: failed during collection.

Failure:

- `tests/test_refactoring_validation.py`
- Error: `ImportError: cannot import name 'check_lookahead_leakage' from 'uniquant.brain.factors.analyzer'`

Required source API according to the test:

- `check_lookahead_leakage(df, factor_func, factor_cols)`
- `LookaheadBiasError`

Expected behavior from test body:

- A factor function using lagged data such as `close.shift(1)` should pass.
- A factor function using future data such as `close.shift(-1)` should raise `LookaheadBiasError` with message containing `Look-ahead bias detected in factor 'momentum'`.

## Run 6 - Parallel Capability Check

Commands:

```bash
.venv/bin/pytest --version
.venv/bin/python -c "import importlib.util; print(importlib.util.find_spec('xdist') is not None)"
nproc
```

Result:

- Pytest version: `pytest 9.0.3`
- `pytest-xdist`: not installed
- CPU cores: `16`

Execution choice:

- Since `pytest-xdist` is unavailable, tests were parallelized by launching independent pytest processes for separate groups.

## Run 7 - Minimal Reproduction Tests For Known Failures

These commands were run in parallel as independent pytest processes with `PYTHONPATH=.`.

### 7.1 E2E Pipeline

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/chaos/test_e2e_pipeline.py::test_e2e_pipeline -q
```

Result:

- `1 failed`
- Failure: Step 5, `UnifiedMatchingEngine.fill_buy() got an unexpected keyword argument 'volumes'`
- Stable classification: interface drift between chaos E2E test and matching engine API.

### 7.2 LPPL Analysis Engine

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_analysis_engines.py::TestLpplAnalysisEngine -q
```

Result:

- `2 passed`
- `2 failed`

Failures:

1. `test_run_lppl_analysis_none_df_reads_from_lake`
   - Expected `mock_orchestrator.data_service.lake.read_data` to be called once.
   - Actual call count: zero.

2. `test_fallback_lppl_analysis`
   - Error: `LpplAnalysisEngine` has no attribute `_fallback_lppl_analysis`.

Stable classification: LPPL analysis compatibility/API drift.

### 7.3 DI Container API

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_di_container_and_cache.py::TestDIContainer::test_register_get_reset_and_clear -q
```

Result:

- `1 failed`
- Failure: `ServiceContainer` has no attribute `register_factory`.
- Warning: `uniquant.shared.di_container` is deprecated and redirects toward `ServiceContainer`.

Stable classification: deprecated compatibility facade no longer satisfies test contract.

### 7.4 Error Handling Specialized Wrappers

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_error_handling_additional.py::TestErrorHandlingHelpers::test_specialized_wrappers -q
```

Result:

- `1 failed`
- Failure: `handle_network_errors(default_return="network", max_retries=1)` re-raises `requests.RequestException` instead of returning `"network"`.

Stable classification: error-handling behavior regression.

### 7.5 LPPL Scan Window Bucketing

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_lppl_engine_scan_windows.py -q
```

Result:

- `1 failed`
- Failure: expected `len(results) == 3`, actual `len(results) == 4`.

Stable classification: LPPL `scan_all_windows` no longer selects one best result per bucket, or test expectation is stale.

### 7.6 Script Compatibility Tests

Command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_offline_entry.py tests/test_results_protocol.py -q
```

Result:

- `3 passed`
- `2 failed`

Failures:

1. `tests/test_offline_entry.py::test_offline_full_test_wrapper_compiles`
   - Missing file: `scripts/offline_full_test.py`

2. `tests/test_results_protocol.py::TestChiefReviewCompatibility::test_analyze_single_date_folder_supports_new_result_schema`
   - Missing file: `scripts/generate_chief_review.py`

Stable classification: missing script artifacts or stale tests.

## Run 8 - Core Business Test Groups

These commands were run in parallel as independent pytest processes with `PYTHONPATH=.`.

### 8.1 A-share Matching And Limit Rules

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_matching_engine.py \
  tests/test_t1_constraint_boundary.py \
  tests/test_limit_checker.py \
  -q
```

Result:

- `47 passed`
- Duration: `0.35s`

### 8.2 Backtest Engines

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_backtest_engine.py \
  tests/test_portfolio_engine_v2.py \
  tests/test_backtest_advanced.py \
  -q
```

Result:

- `56 passed`
- `1 skipped`
- `1 warning`
- Duration: `1.53s`

Warning:

- NumPy/Pandas FutureWarning from `Series.swapaxes` path during `TestRobustnessChecker::test_subperiod_consistency`.

### 8.3 Factor And Lookahead Tests

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_factor_analyzer.py \
  tests/test_factor_registry.py \
  tests/test_custom_factors.py \
  tests/test_lookahead_bias.py \
  -q
```

Result:

- `26 passed`
- `1 failed`

Failure:

- `tests/test_custom_factors.py::test_custom_factor_registered`
- Error: `FactorRegistry.get_factor("turnover_momentum_20d")` returned `None`.

Stable classification: factor registration/import side effect missing for `turnover_momentum_20d` in this test path.

### 8.4 Data Chaos Tests

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_data_chaos_qa.py \
  tests/chaos/test_data_chaos.py \
  -q
```

Result:

- `97 passed`
- `25 warnings`
- Duration: `12.66s`

Warnings:

- `SettingWithCopyWarning` from `src/uniquant/data/pipeline/data_cleaner.py:44`.

## Updated Triage After Parallel Runs

Confirmed stable failures:

1. `test_refactoring_validation.py` collection blocker: missing `check_lookahead_leakage` and `LookaheadBiasError`.
2. Matching engine interface drift: `fill_buy(volumes=...)`.
3. LPPL analysis compatibility drift: missing lake read path and `_fallback_lppl_analysis`.
4. Deprecated DI container facade lacks `register_factory`.
5. Error-handling wrappers re-raise where tests expect default return.
6. LPPL scan window bucket selection returns 4 results instead of 3.
7. Missing scripts: `scripts/offline_full_test.py`, `scripts/generate_chief_review.py`.
8. Factor registry path does not register `turnover_momentum_20d` for `test_custom_factors.py`.

Green core areas from this run:

- A-share matching/limit/T+1 tests pass.
- Backtest engine groups pass except one skipped test.
- Data chaos tests pass, with warnings.
