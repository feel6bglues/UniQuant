# Change Log - UniQuant Refactoring

## [2026-05-24]

### Added
- [data_aligner.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/pipeline/data_aligner.py): Added calendar-based suspension/delisting alignment logic.
- [numba_optimizer.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/lppl/numba_optimizer.py): JIT-compiled Differential Evolution (DE) optimizer and OLS linear solver.
- [test_refactoring_validation.py](file:///home/james/Documents/Project/UniQuant/tests/test_refactoring_validation.py): New unit tests for all refactored modules.

### Modified
- [data_fetcher.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/data_fetcher.py): Integrated DataAligner before performing price adjustments.
- [storage_manager.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py): Upgraded PyArrow configuration to attempt zero-copy extraction.
- [engine.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/wyckoff/engine.py): Vectorized Wyckoff peaks scan, added sigmoid-mapped probabilistic confidence tags.
- [calculator.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/lppl/calculator.py): Replaced scipy DE calculations with numba_optimizer.
- [analyzer.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/analyzer.py): Added LookaheadBiasError and check_lookahead_leakage for strict leakage checking.
- [walk_forward_pipeline.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/walk_forward_pipeline.py): Added OOS Rank IC scoring on out-of-sample segments and dynamic leakage checks.
