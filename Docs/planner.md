# UniQuant Refactoring and Optimization Planner

This plan outlines the refactoring strategy for the A-share quantitative research system (UniQuant) across three core pillars: Offline Data Lake (mootdx/pytdx localization), Wyckoff & LPPL Algorithm Engines, and Factor Pipeline.

---

## 1. Offline Data Lake (mootdx Localization)

### Goal
Completely decouple the system from real-time internet API calls (such as Akshare) during offline calculations, using local `pytdx`/`mootdx` data files. Optimize storage and load performance using Parquet and DuckDB with Zero-Copy memory mapping, and perform trade-calendar-based alignment for suspended/delisted stocks.

### Proposed Changes

#### [NEW] [data_aligner.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/pipeline/data_aligner.py)
Create a data alignment utility that matches raw daily bar records with the official trade calendar:
- Load the trade calendar for the stock's active period (from IPO date to delist date or the latest trading day).
- Reindex stock data using this list of calendar dates.
- For days with suspended trading: forward-fill prices (`open`, `high`, `low`, `close`) using the previous trading day's close, and set `volume` and `amount` to zero.
- For delisted stocks: stop filling data after the `delist_date` (acquired from `StockMetadataManager`).

#### [MODIFY] [storage_manager.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py)
Optimize storage management:
- Integrate PyArrow's `pq.read_table` with `memory_map=True` and `zero_copy_only=True` when transforming Arrow tables to Pandas DataFrames (with careful exception handling if zero-copy is impossible).
- Establish a global DuckDB connection pool to query partition/hive Parquet directories instead of loading multiple individual Parquet files, significantly speeding up large cross-sectional scans.
- Provide a DuckDB-backed vectorized bulk loader `load_symbols_asof` to load aligned bars for multiple tickers.

#### [MODIFY] [data_fetcher.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/data_fetcher.py)
Ensure that all data fetching operations prioritize the local data lake and restrict remote API access:
- If a ticker data query cannot be satisfied locally, trigger a structured logging warning and raise an offline mode constraint if network access is restricted.

---

## 2. Algorithm Engine Refactoring (Wyckoff & LPPL)

### Wyckoff Engine: Vectorized Scan and Probabilistic Labels

#### [MODIFY] [classifiers.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/classifiers.py) & [engine.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/engine.py)
Refactor manual, sequential looping structures into fully vectorized array operations using NumPy and Pandas:
- Convert BC (Buying Climax) and SC (Selling Climax) scoring into vectorized operations over rolling windows (e.g. rolling 30 and 60 days).
- Detect local extremas using array slice shifts or fast peak detectors rather than multi-pass itemized loops.
- Implement a probabilistic classification logic that translates Wyckoff structures (Spring, UTAD, BUEC) into continuous scores, transforming binary indicators into soft confidence metrics.

---

### LPPL Engine: High-Density Numba JIT DE Optimizer

#### [NEW] [numba_optimizer.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/lppl/numba_optimizer.py)
Implement a custom Differential Evolution (DE) solver compiled under Numba `@njit(nopython=True, cache=True, fastmath=True)`:
- Implement the DE population initialization, mutation, crossover, and selection logic entirely in Numba.
- The JIT compiler will optimize execution of the LPPL cost calculation (`_reduced_cost_numba`), avoiding all CPython call overhead during optimization.
- The solver will return the optimized non-linear parameters `[tc, m, w]`.
- Solve for linear parameters `[a, b, c, phi]` directly within the Numba environment via standard ordinary least squares (solving the normal equations using JIT-compiled matrix operations).

#### [MODIFY] [calculator.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/lppl/calculator.py)
Update the calculation driver to integrate the JIT-compiled optimizer:
- Replace the SciPy `differential_evolution` calls with `_de_solve_numba` by default.
- Keep SciPy as a fallback interface for test cases or validation purposes.

---

## 3. Factor Pipeline (Factor Pipeline)

### Goal
Provide a bulletproof factor testing pipeline, strictly preventing look-ahead bias via assertions and integrating a clean walk-forward validation framework.

### Proposed Changes

#### [MODIFY] [analyzer.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/analyzer.py)
Ensure zero look-ahead bias:
- Implement a rigid validation assertion: check that the factor values at time $t$ are derived solely from inputs where the timestamp is strictly less than or equal to $t$.
- Guard against negative shifts (e.g., using `shift(-N)`) in factor definitions. Raise a `LookaheadBiasError` if any such leakage occurs.
- Restrict negative shifts exclusively to the forward returns calculation, which must be clearly partitioned as targets rather than features.

#### [MODIFY] [walk_forward_pipeline.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/walk_forward_pipeline.py)
Enhance walk-forward cross-validation:
- Build a rolling window generator that splits data into strict In-Sample (IS) training segments and Out-of-Sample (OOS) testing segments.
- On each IS training segment, estimate factor IC/IR and optimize weights (e.g., via Rank IC/IR allocation).
- On the subsequent OOS testing segment, compose the multi-factor scores using the locked IS weights.
- Report rolling metrics (OOS IC mean, OOS IR, weight drift) to verify multi-factor stability and prevent overfitting.

---

## 4. Verification Plan

### Automated Tests
- Run `.venv/bin/pytest` with `PYTHONPATH=.` to ensure all existing tests pass after refactoring.
- Create new test cases specifically validating:
  - Custom Numba DE solver vs SciPy `differential_evolution` parameter convergence and execution times.
  - Verification of calendar alignment under stock suspension scenarios.
  - Zero leakage checks on factor calculations (verifying that look-ahead assertions are triggered appropriately).

### Manual Performance Checks
- Run a benchmark script on 100 stocks comparing the original LPPL scanning time with the Numba JIT DE version, targeting a 10x-50x speedup.
