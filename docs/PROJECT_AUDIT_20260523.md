# UniQuant Project Audit

Date: 2026-05-23  
Scope: read-only project audit covering architecture, quantitative research/backtesting logic, risk controls, data flow, configuration, imports, and test quality.

## Executive Summary

UniQuant already has the shape of a broad quantitative research and trading platform. It includes a data lake, data services, factor calculation, signal scanning, technical/structure analysis engines, risk modules, single-asset backtesting, portfolio backtesting, reporting, and a Streamlit UI.

The project should currently be treated as a research platform and refactoring-stage prototype, not a production-grade trading/backtesting platform. The main risks are not missing features. The main risks are unstable project contracts:

- Import paths and test environment are fragile.
- Configuration files exist but are not all loaded by the main config loader.
- Backtest execution semantics are inconsistent and optimistic.
- Offline labeling/evaluation functions can be mistaken for live trading strategies.
- Factor weighting can leak full-sample future information into same-sample scoring.
- Tests are numerous but several high-risk areas lack strict invariant or accounting-level assertions.

The highest leverage next step is stabilizing package/test/runtime contracts before adding new strategies.

## Current System Shape

Primary layers:

- UI layer: `src/uniquant/ui/dashboard.py`, `src/uniquant/ui/manager_logic.py`
- Service layer: `src/uniquant/services/data_service.py`, `src/uniquant/services/analysis_service.py`, `src/uniquant/services/scan_service.py`
- Domain engines: `src/uniquant/brain/*`, `src/uniquant/hands/*`, `src/uniquant/risk/*`, `src/uniquant/signal/*`
- Data layer: `src/uniquant/data/lake/storage_manager.py`, `src/uniquant/data/services/*`, `src/uniquant/data/managers/*`
- Scripts: `scripts/run_market_scan.py`, `scripts/verify_import.py`, `scripts/rebuild_financial_lake.py`, `scripts/download_etf_data.py`

Main data/research flow:

1. Raw or external data is fetched through `DataFetcher`, source adapters, or import scripts.
2. `StorageManager` persists data into the local data lake under `data/lake`.
3. `DataService` coordinates storage, cache, cleaner, quality checks, and query service.
4. `ScanPipeline` loads daily and financial data, computes factors, analyzes IC/IR, composes scores, and screens symbols.
5. `AnalysisService` orchestrates FSM, CZSC, LPPL, NTF, regime, macro, and report generation.
6. `hands/backtest` and `hands/strategies` provide multiple backtesting and strategy evaluation paths.

## Strengths

- Broad module coverage across data, factors, signals, risk, backtesting, reporting, and UI.
- Single-asset `BacktestEngine` includes key A-share concepts: commission, stamp duty, minimum commission, slippage, T+1, and limit-up/limit-down checks.
- Factor infrastructure includes registry, factor composition, Rank IC, ICIR, IC positive ratio, and t-stat reporting.
- Risk modules include VaR/CVaR, max drawdown, position sizing, and portfolio optimization.
- There are many regression tests covering data services, factors, backtest basics, validation, risk, and reporting paths.
- Some explicit lookahead defenses already exist, especially in `FactorAnalyzer.compute_ic_ir(mode="live")`.

## P0 Issues

### 1. Package Import And Test Environment Are Fragile

Files:

- `pyproject.toml`
- `tests/conftest.py`
- `tests/test_czsc_engine.py`
- `tests/test_ntf_engine.py`
- `tests/test_regime_detector.py`
- `src/uniquant/brain/czsc/czsc_engine.py`
- `src/uniquant/brain/ntf/ntf_engine.py`
- `src/uniquant/brain/regime/regime_detector.py`

Problem:

The project uses a `src` layout, but `tests/conftest.py` only inserts the repository root into `sys.path`. In an uninstalled or clean environment, `import uniquant` can fail. I verified this locally with `.venv/bin/python`: `uniquant` was not importable. The local virtual environment also lacks `pytest`, so test collection could not be executed.

There is also a compatibility mismatch. Several tests and likely external code import old paths such as:

- `uniquant.brain.czsc_engine`
- `uniquant.brain.ntf_engine`
- `uniquant.brain.regime_detector`

The actual modules are now located under:

- `uniquant.brain.czsc.czsc_engine`
- `uniquant.brain.ntf.ntf_engine`
- `uniquant.brain.regime.regime_detector`

`src/uniquant/brain/__init__.py` re-exports classes, but re-exporting does not make old module paths importable.

Impact:

- Tests may fail at collection in clean environments.
- Monkeypatches can target the wrong module path.
- Local script behavior can differ from installed package behavior.
- CI cannot be trusted until import and collection are made deterministic.

Recommendations:

- Add `pythonpath = ["src"]` to pytest configuration or require `pip install -e .` before tests.
- Add compatibility shim modules if old paths must remain supported:
  - `src/uniquant/brain/czsc_engine.py`
  - `src/uniquant/brain/ntf_engine.py`
  - `src/uniquant/brain/regime_detector.py`
- Replace `src.*` monkeypatch/import paths in tests with `uniquant.*`.
- Add a clean-environment CI gate: `python -m pytest --collect-only -q`.

### 2. Backtest Execution Uses Same-Bar Signal And Same-Bar Close Fill

File:

- `src/uniquant/hands/backtest/engine.py`

Problem:

`BacktestEngine.run_backtest` calls `signal_generator(df, idx, context)` and can immediately execute using the same row's `close`. If the signal uses current `close`, `high`, `low`, or indicators that include the current close, this becomes "observe close, then trade at that same close."

Impact:

- Results can be materially over-optimistic.
- Signals that are only known after market close become executed at an impossible price.
- The system can report a valid-looking backtest that is not actually tradeable.

Recommendations:

- Standardize execution as signal day `t`, execution day `t+1` open or next available executable price.
- Alternatively, force signal generators to receive only data through `idx - 1`.
- Add explicit execution mode names, for example `close_to_next_open`, `open_to_close`, `same_bar_research_only`.
- Make same-bar execution opt-in and label it as research-only.

### 3. Portfolio Backtest Omits A-Share Trading Constraints

File:

- `src/uniquant/hands/backtest/portfolio_engine.py`

Problem:

Portfolio backtest uses same-date signals and prices, and does not apply the same constraints as the single-asset engine:

- T+1
- limit-up/limit-down constraints
- suspension/zero-volume handling
- stamp duty
- minimum commission
- nonlinear/volume-aware slippage
- partial fill or liquidity constraints

Impact:

- Portfolio backtest is not comparable with single-asset backtest.
- Portfolio performance will likely be optimistic.
- Risk and capacity estimates are unreliable.

Recommendations:

- Reuse one common execution simulator for both single-asset and portfolio backtests.
- Centralize cost, slippage, T+1, limit, suspension, and lot-size logic.
- Add portfolio-level accounting tests for cash, positions, PnL, costs, and final equity.

### 4. Offline Strategy Evaluation Functions Can Be Misused As Live Strategies

Files:

- `src/uniquant/hands/strategies/ma_cross.py`
- `src/uniquant/hands/strategies/str_reversal.py`
- `src/uniquant/hands/strategies/wyckoff.py`

Problem:

Several `trade_*` functions inspect data after `as_of_date` to determine future return, exit, or outcome. This is acceptable for offline labeling or performance attribution, but not for signal generation or real-time strategy logic.

Impact:

- The function name suggests tradeability, while implementation uses future windows.
- Future leakage can enter downstream strategy selection or reporting if these functions are reused incorrectly.

Recommendations:

- Rename these functions or wrap them as `evaluate_*`, `label_*`, or `research_*`.
- Create separate live-safe `generate_signal_*` functions.
- Add tests that verify live-safe functions cannot access future rows.

### 5. Factor Weighting Can Leak Full-Sample Information

Files:

- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/composer.py`
- `src/uniquant/services/scan_service.py`

Problem:

`FactorAnalyzer.compute_ic_ir` computes forward returns using negative shift. This is valid for offline factor research. However, `ScanPipeline` can analyze factors and then use the resulting full-sample IC/IR through `FactorComposer` to score the same dataset.

Impact:

- Factor weights can be chosen using future returns from the same sample being scored.
- Scan rankings can look stronger than they would be in true out-of-sample deployment.

Recommendations:

- Force factor weighting to be fit only on a training window.
- Apply weights only to later test/live windows.
- Add a walk-forward factor pipeline:
  - fit weights on `[t0, t1]`
  - score on `(t1, t2]`
  - roll forward
- Make `mode="live"` the default in production-facing code paths.

## P1 Issues

### 6. Configuration Files Exist But Are Not All Loaded

Files:

- `src/uniquant/shared/config_loader.py`
- `config/config.yaml`
- `config/trading.yaml`
- `config/factors.yaml`
- `config/optimal_params.yaml`

Problem:

`GlobalConfig` loads `config/config.yaml` if present. When this file exists, the loader does not load other config files such as `trading.yaml`, `factors.yaml`, or `optimal_params.yaml`.

Impact:

- Maintainers can edit config files that appear valid but are not used.
- Trading parameters can diverge from runtime behavior.
- Bugs become hard to diagnose because configuration source of truth is unclear.

Recommendations:

- Define a single explicit config loading policy:
  - either one authoritative `config.yaml`
  - or load all known config files with deterministic merge order
- Emit startup diagnostics listing loaded config files.
- Add a test that asserts `trading`, `factors`, and `optimal_params` are loaded or intentionally ignored.

### 7. AnalysisService Is Over-Coupled

File:

- `src/uniquant/services/analysis_service.py`

Problem:

`AnalysisService` directly holds `DataService`, lazily imports `Reporter`, `EVTRisk`, `PositionSizer`, `DecisionBrain`, and constructs multiple analysis engines in its initializer.

Impact:

- The service is hard to test without extensive mocks.
- Initialization can fail because of optional dependencies unrelated to the requested analysis.
- Changes in one engine can break the whole analysis service.

Recommendations:

- Split orchestration from engine construction.
- Inject engines through a factory or registry.
- Initialize optional engines lazily only when the corresponding method is called.
- Add integration tests for real `DataService -> AnalysisService -> engine -> report` contracts.

### 8. DataService Has Too Many Responsibilities

Files:

- `src/uniquant/services/data_service.py`
- `src/uniquant/services/data_access_service.py`
- `src/uniquant/data/lake/storage_manager.py`

Problem:

`DataService` coordinates fetching, storage, cache, cleaning, quality checks, stock query, ETF list, and lake access. `DataAccessService` also wraps parts of access/fallback behavior. Multiple modules know how to construct data lake paths.

Impact:

- Responsibility boundaries are unclear.
- Two services can become capable of doing the same thing differently.
- Path/schema changes are risky because directory knowledge is duplicated.

Recommendations:

- Make `StorageManager` the single source of truth for lake layout.
- Keep `DataService` as a thin facade or split into explicit services:
  - `MarketDataReader`
  - `MarketDataWriter`
  - `ReferenceDataService`
  - `DataQualityService`
  - `CacheService`
- Add schema tests for daily, minute, factor, and financial lake records.

### 9. Survivorship Bias Remains In Batch Strategy Backtest

File:

- `src/uniquant/hands/strategies/backtest.py`

Problem:

The batch strategy backtest has an explicit warning that the universe is today's stock list, not a historical universe. Historical CSI300 constituent snapshots are attempted, but fallback behavior still permits survivorship bias.

Impact:

- Backtest universe may exclude delisted or historically failed stocks.
- Strategy results can be materially inflated.

Recommendations:

- Require as-of universe snapshots for any historical index/universe backtest.
- If historical constituent data is missing, fail closed rather than fallback to today's list.
- Record universe source and coverage in every result artifact.

### 10. Batch Strategy Backtest Has Incomplete Execution Modeling

File:

- `src/uniquant/hands/strategies/backtest.py`

Problem:

Batch strategy backtest applies percentage costs and checks entry-day limits, but does not model full position sizing, minimum commission, partial fills, T+1 exits, or exit-day limit-down constraints consistently.

Impact:

- Returns are useful as rough research labels, not executable portfolio simulation.
- Cost drag for small trades can be understated.
- Exit risk is understated in limit-down or suspended conditions.

Recommendations:

- Route batch strategy results through the same execution simulator as portfolio backtests.
- If kept as research-only, rename and document it clearly.

### 11. Overfitting Detection Uses Random Shuffle Rather Than Time-Series Purging

File:

- `src/uniquant/hands/backtest/overfitting_detector.py`

Problem:

PBO partitioning uses random shuffle, not purged/embargoed time-series splits.

Impact:

- Leakage can remain for autocorrelated signals and overlapping holding windows.
- Overfitting risk may be understated.

Recommendations:

- Implement purged K-fold or combinatorial purged cross-validation.
- Add embargo periods based on maximum holding period.
- Report parameter stability across chronological windows.

### 12. EVTRisk Name Does Not Match Implementation

File:

- `src/uniquant/risk/evt_risk.py`

Problem:

`HistoricalSimulationRisk` is described as EVT in places but uses historical percentile VaR/CVaR, not true Extreme Value Theory with GPD tail fitting.

Impact:

- Risk reports may overstate methodological sophistication.
- Users may assume tail extrapolation that is not being performed.

Recommendations:

- Rename user-facing references to historical simulation risk, or implement a true EVT/GPD estimator.
- Add tests for tail behavior and compare against known synthetic distributions.

### 13. Position Sizing Is Useful But Simplified

File:

- `src/uniquant/risk/sizer.py`

Observation:

`PositionSizer` supports risk-per-share sizing, lot size, T+1 penalty, and capital cap. It is a good foundation.

Limitations:

- HK lot size is hardcoded.
- Stop loss validation is strict and good, but broader execution constraints are not integrated.
- It does not account for liquidity, volatility regime, correlation, or portfolio exposure.

Recommendations:

- Integrate with portfolio-level exposure and liquidity constraints.
- Make market lot rules configurable.
- Add tests for extreme price, tiny capital, invalid stop, and lot rounding.

### 14. Portfolio Optimizer Needs Stronger Production Guards

File:

- `src/uniquant/risk/portfolio_optimizer.py`

Problem:

Mean-variance and risk parity optimization are implemented, but production robustness needs more guards.

Risks:

- Covariance instability.
- No shrinkage estimator.
- No turnover penalty.
- No sector/industry constraints.
- Expected returns default to in-sample mean annualization.

Recommendations:

- Add covariance shrinkage or robust covariance options.
- Add turnover and max-change constraints.
- Support sector constraints.
- Separate historical expected returns from forecast expected returns.
- Add tests for singular covariance and highly collinear assets.

## P2 Issues

### 15. Tests Are Numerous But Some Assertions Are Too Weak

Files:

- `tests/test_backtest_engine.py`
- `tests/test_validation_service.py`
- `tests/test_evt_risk.py`
- `tests/test_data_*`
- `tests/test_analysis_*`

Problem:

Many tests verify that objects exist, results are returned, or fallback behavior does not crash. Fewer tests verify exact financial accounting, mathematical properties, or schema invariants.

Examples:

- Backtest tests should assert exact cash, equity, cost, slippage, PnL, and position state.
- Validation tests should assert exact accepted/rejected fields and edge cases.
- Risk tests should assert monotonicity and tail properties.

Recommendations:

- Add accounting-level tests for all execution engines.
- Add property tests for risk metrics.
- Tighten validation tests to assert exact fields and error behavior.

### 16. DataValidator May Mutate Inputs

File:

- `src/uniquant/data/pipeline/data_validator.py`

Problem:

Static audit indicates validation can mutate input data by fixing high/low, converting dates, or sorting local data.

Impact:

- Callers may not expect validation to be destructive.
- Bugs can be masked by automatic repair.

Recommendations:

- Decide whether validators are pure validators or repairers.
- If repair is needed, split into `validate` and `repair`.
- Add tests for mutation behavior.

### 17. Optional Dependencies And Local Data Cause Coverage Instability

Files:

- `tests/test_hands_strategies.py`
- `tests/test_field_mapping.py`

Problem:

Some tests skip based on optional dependencies or local data directories.

Impact:

- Core behavior may not be covered in CI.
- Local machine state changes coverage.

Recommendations:

- Separate unit, integration, and local-data profiles.
- Keep core tests independent of local data and optional services.

## Quantitative Correctness Priorities

### Execution Semantics

Required standard:

- Signals generated at time `t` may only use data available at `t`.
- Orders execute at `t+1` or later using executable prices.
- A-share T+1, lot size, limit-up/down, suspension, minimum commission, stamp duty, and slippage must be applied consistently.

Immediate tasks:

- Create one execution simulator used by both single-asset and portfolio engines.
- Add a mode flag for research-only same-bar testing.
- Record execution assumptions in every backtest result.

### Factor Research

Required standard:

- Forward returns are allowed only in offline research.
- IC/IR and factor weights must be estimated on training windows.
- Scores and rankings must be evaluated out of sample.

Immediate tasks:

- Add `WalkForwardFactorPipeline`.
- Make production scan reject full-sample `ic_results`.
- Add rolling IC stability and turnover/capacity reporting.

### Universe Construction

Required standard:

- Historical backtests must use as-of constituent/universe snapshots.
- Missing historical universe data should fail closed unless explicitly running exploratory mode.

Immediate tasks:

- Add `UniverseProvider` abstraction.
- Persist universe metadata into backtest reports.
- Add tests for delisted symbols and changing index membership.

### Risk

Required standard:

- Risk metrics must be mathematically tested and clearly named.
- Historical simulation and EVT/GPD should not be conflated.

Immediate tasks:

- Rename `EVTRisk` usage or implement true EVT.
- Add tests for NaN/Inf, all-zero returns, one extreme loss, confidence boundaries, CVaR/VaR monotonicity, and cache consistency.

## Engineering Remediation Roadmap

### Phase 0: Stabilize The Project Contract

Goal: make the project importable and tests collectable in a clean environment.

Tasks:

- Add `pythonpath = ["src"]` to pytest config or document mandatory editable install.
- Install dev dependencies or add a reproducible setup script.
- Add compatibility shim modules for old imports or update all call sites.
- Remove `src.*` patch/import paths from tests.
- Add `pytest --collect-only -q` to CI or local verification script.

Exit criteria:

- `python -m pytest --collect-only -q` passes from a clean checkout.
- `import uniquant` works without manual path hacks after documented setup.

### Phase 1: Fix Backtest Semantics

Goal: make reported backtest results closer to executable trading.

Tasks:

- Define canonical signal and execution timing.
- Execute `t` signals at `t+1 open` by default.
- Centralize execution constraints.
- Bring portfolio backtest to parity with single-asset engine.
- Rename research-only strategy evaluators.

Exit criteria:

- Single and portfolio engines share execution assumptions.
- Accounting-level tests cover fees, slippage, PnL, T+1, limits, lot sizes, and cash conservation.

### Phase 2: Clean Config And Service Boundaries

Goal: reduce runtime ambiguity.

Tasks:

- Decide whether config is single-file or multi-file.
- Emit loaded config files at startup.
- Split `AnalysisService` engine creation from orchestration.
- Make `StorageManager` the only lake layout authority.

Exit criteria:

- Every config file in `config/` is either loaded or explicitly documented as inactive.
- Data lake paths are centrally defined.

### Phase 3: Harden Quant Research

Goal: prevent leakage and overfitting.

Tasks:

- Implement walk-forward factor weighting.
- Add purged/embargoed validation for strategies.
- Add historical universe provider.
- Add rolling stability and sample-out reports.

Exit criteria:

- Production scans do not use full-sample forward-return IC to score the same sample.
- Backtest reports include universe, execution, cost, and validation assumptions.

### Phase 4: Tighten Tests And Quality Gates

Goal: make regressions detectable.

Tasks:

- Add accounting-level backtest tests.
- Add data quality invariants.
- Add risk property tests.
- Add end-to-end contract tests from `DataService` to `AnalysisService` to report/result.
- Split test markers into `unit`, `integration`, `local_data`, and `optional_dependency`.

Exit criteria:

- Core tests run without network or local market data.
- Integration tests are explicit and separately invokable.

## Verification Status

Commands attempted:

- `rg --files`
- `git status --short`
- static reads of key modules and configs
- `.venv/bin/python` import checks
- `.venv/bin/python -m pytest --collect-only -q`

Observed:

- The working tree is dirty with many untracked or modified project files.
- `.venv/bin/python` exists.
- `python` command is not available.
- `.venv/bin/python -m pytest --collect-only -q` failed because `pytest` is not installed.
- Direct `uniquant` imports failed before package installation/path setup.

No code files were modified during the audit. This report is the only file created by this follow-up step.

## Bottom Line

UniQuant has substantial functionality and a promising domain model, but the immediate engineering priority is not adding more indicators or strategies. The system needs hard runtime contracts first: importability, config loading, deterministic test collection, unified execution semantics, and strict separation between research labels and tradeable signals.

After those are fixed, the project can become a credible quant research and backtesting platform. Without those fixes, reported strategy performance should be treated as exploratory only.
