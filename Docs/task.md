# Task Checklist - UniQuant Refactoring

- `[x]` 1. Offline Data Lake Localization & Cleaners
  - `[x]` 1.1 Create `data_aligner.py` for trading calendar alignment (suspensions and delisting ffill).
  - `[x]` 1.2 Optimize `storage_manager.py` for PyArrow zero-copy and DuckDB mass loading.
  - `[x]` 1.3 Ensure `data_fetcher.py` uses strictly localized mootdx/pytdx sources and data aligner.
- `[x]` 2. Wyckoff & LPPL Optimization
  - `[x]` 2.1 Refactor `classifiers.py` and `engine.py` to support vectorized Wyckoff scans.
  - `[x]` 2.2 Create `numba_optimizer.py` containing custom Numba DE solver + OLS linear solver.
  - `[x]` 2.3 Refactor LPPL `calculator.py` to default to `_de_solve_numba`.
- `[x]` 3. Factor Study Pipeline Refactoring
  - `[x]` 3.1 Implement lookahead bias assertions in `analyzer.py`.
  - `[x]` 3.2 Refactor `walk_forward_pipeline.py` with IS/OOS temporal partition validation.
- `[x]` 4. System Validation
  - `[x]` 4.1 Write comprehensive tests for the Numba DE optimizer and Lookahead checks.
  - `[x]` 4.2 Run existing tests and verify correctness.
