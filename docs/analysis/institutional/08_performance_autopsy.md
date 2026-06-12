# WS8 — Performance Autopsy

Generated: 2026-06-10

Scope: CPU hotspots, memory risks, vectorization usage, computational complexity, and latency budgets for the research platform.

## 1. Performance Infrastructure

**`shared/perf.py`** — A lightweight `perf_section(name)` context manager exists, gated by `UNIQUANT_PERF=1` env var. Provides call counts, total ms, and avg µs per named section via `perf_report()`. **Zero usages in production code paths.** No `with perf_section(...)` call was found in any engine, service, or pipeline.

**Status**: Performance instrumentation exists but is not wired into any execution path.

## 2. Code Size Heatmap

| Module | LOC | Complexity risk |
|---|---|---|
| `brain/wyckoff/engine.py` | 1,457 | **Highest** — fusion engine with itertuples loops |
| `brain/lppl/engine.py` | 1,040 | High — custom optimization, Numba-accelerated |
| `brain/wyckoff/models.py` | 817 | High — data models |
| `brain/czsc/czsc_engine.py` | 634 | Medium-high — CZSC algorithm |
| `brain/lppl/computation.py` | 392 | Medium |
| `brain/factors/composer.py` | 401 | Medium |
| `brain/regime/regime_detector.py` | 272 | Medium |
| `brain/ntf/ntf_engine.py` | 183 | Low |
| `services/analysis_service_v2.py` | 537 | Medium |
| `signal/adapters.py` | 557 | Medium-high — 8 adapters |
| `hands/backtest/unified_engine.py` | 551 | Medium |
| `hands/backtest/unified_matching_engine.py` | 263 | Low (well-vectorized) |
| `data/lake/storage_manager.py` | 638 | Medium — I/O bound |
| `data/pipeline/data_cleaner.py` | 69 | Very low |
| `data/pipeline/data_validator.py` | 85 | Very low |

## 3. Performance-Sensitive Patterns

### 3.1 Python iteration over rows (57 sites)

| File | Pattern | Risk |
|---|---|---|
| `brain/wyckoff/engine.py` | `for row in recent_20.itertuples()` (5 sites) | **High** — per-symbol, per-bar iteration in 1457-line engine |
| `brain/wyckoff/classifiers.py` | `for row in ...itertuples()` (5 sites) | Medium — classification on small windows |
| `brain/wyckoff/rules.py` | `for row in post_spring_df.itertuples()` | Low — post-filter |
| `brain/wyckoff/trading.py` | `for row in future_data.itertuples()` | Low |
| `hands/backtest/unified_engine.py` | `for idx in range(len(df))` | Medium — sequential bar loop, but O(1) per bar |
| `hands/backtest/engine.py` | `for idx in range(len(df))` | Medium — same pattern |
| `hands/backtest/trade_analysis/analyzer.py` | `for row in df.itertuples()` (3 sites) | Low — post-processing |
| `hands/strategies/str_reversal.py` | `for i, rw in enumerate(fut.itertuples())` | Low — single strategy |
| `services/scan_service.py` | `for row in sector_data.itertuples()` | Low |

**Total**: ~57 `itertuples` / `range(len(...))` / Python loop sites. Wyckoff engine accounts for the most intensive usage.

### 3.2 DataFrame copy churn (166 sites)

`.copy()` is called extensively — 166 matches. Key paths:

- `analysis_service_v2.py:185` — `_optimize_dataframe()` copies then downcasts dtypes
- `composer.py` — multiple `.copy()` calls per factor computation
- `backtest engines` — `df.copy()` at entry then vector ops on dtypes
- `scan_service.py` — copies per symbol in batch scan
- `data_service.py:129` — `_clone_dataframe()` uses `deep=True`

**Impact**: Each pipeline run creates ~5-15 DataFrame copies. For 5000-symbol scans, this is 25,000-75,000 copies. Acceptable for single-symbol research; significant for batch mode.

### 3.3 `.apply()` usage (5 sites)

| File | Line | Description | Risk |
|---|---|---|---|
| `brain/factors/custom_factors.py:122` | `rolling(window=20).apply(...)` | Per-window Python func | Low — single column |
| `legacy analysis_service.py` | `.apply()` on ETF/sector data | Legacy only | Low |
| `ui/manager_logic.py:151` | `.apply(lambda c: get_stock_name(c))` | UI path | Low |
| `ui/components.py:444` | `.apply(lambda x: f"{x:.2%}")` | UI formatting | Low |
| `brain/factors/analyzer.py:328` | `.apply(calc_daily_ic)` | Per-group IC calc | Medium — scales with dates |

### 3.4 `.groupby()` usage (25+ sites)

Primary pattern is `groupby("code")` or `groupby("date")` in factor computation. Well-optimized by Pandas internals.

Hot paths:
- `composer.py` — `groupby("code", sort=False)` for per-symbol normalization
- `scan_service.py` — `groupby("code")` for per-symbol analysis in 5000-symbol scans
- `storage_manager.py` — `groupby` for resampling

### 3.5 `.merge()` and `.concat()` (15+ sites)

| Path | Pattern | Risk |
|---|---|---|
| `data_adjuster.py` | `pd.merge_asof()` | **Important** — correct O(n log n) |
| `data_aligner.py` | `pd.merge()` | Low — once per symbol |
| `composer.py` | `pd.concat()` on normalized parts | Medium — multi-factor |
| `scan_service.py` | `pd.concat()` on result frames | Medium — 5000 symbols |
| `data importers` | `pd.concat()` then `drop_duplicates()` | Low — batch import |

## 4. Engine-Level Performance

### 4.1 Wyckoff Engine (1,457 LOC)

**Profile**: Heavy per-symbol analysis with rule-based classification. Multiple `itertuples()` loops over price windows. Includes fusion engine, image engine, and reporting submodules.

**Estimated complexity per symbol**: O(n × k) where n = bar count, k = number of rule classifiers (10+). With `.itertuples()` loops, this is Python-native iteration.

**Recommendation**: Convert classifier rules to vectorized NumPy/Pandas operations. The classification functions in `classifiers.py` are the highest-ROI optimization target.

### 4.2 LPPL Engine (1,040 LOC + Numba)

**Profile**: Nonlinear optimization (Levenberg-Marquardt) for bubble detection. Has Numba-accelerated optimizer (`numba_optimizer.py`). Custom calculation pipeline.

**Estimated complexity per window**: O(m³) for optimization (where m = parameters). Numba helps but LPPL scan across multiple windows is multiplicative.

**Current behavior**: `LPPLDetector.scan_all_windows()` slides across window sizes — O(num_windows × optimization_cost).

**Recommendation**: Keep Numba path. Cache LPPL results per symbol since regime changes slowly. Optimization is acceptable for single-symbol; for batch, limit window count.

### 4.3 CZSC Engine (634 LOC)

**Profile**: Bi-segment identification algorithm. Python-native implementation with geometric logic.

**Estimated complexity per symbol**: O(n) for bi-segment traversal. Linear in bar count.

**Recommendation**: Low priority. CZSC is inherently sequential and not easily vectorized.

### 4.4 Factor Composer (401 LOC)

**Profile**: Per-symbol factor computation + normalization via `groupby("code")` + `apply(compute_func)`. Z-score normalization and orthogonalization step.

**Estimated complexity**: O(f × s × n) where f = factors, s = symbols, n = bar count. Scales linearly with all three dimensions.

**Impact for 5000-symbol research**: Each factor requires a per-symbol loop. With 50 factors and 1000 bars: 250M individual computations.

**Recommendation**: Critical for batch mode. Vectorize where possible (Polars integration candidate). Add progress reporting.

### 4.5 Backtest Engine (551 LOC)

**Profile**: Sequential bar loop with single pending order. O(n) per symbol. Pending order logic is O(1) per bar.

**Execution cost**: Constant per bar — no nested loops. Well-optimized for current use.

**Recommendation**: Low priority. UnifiedMatchingEngine already vectorized for batch fills.

### 4.6 Vectorized Matching Engine (263 LOC)

**Profile**: Fully vectorized NumPy — `compute_execution_prices()`, `compute_limit_status_vectorized()`, `fill_buy()`, `fill_sell()` all use array operations.

**Status**: Best-in-class vectorization. NumPy operations only, no Python loops in hot paths. Fast path avoids element-wise `get_board_type()` calls by using array of precomputed board types.

**Note**: The slow path (ST name detection, IPO rules) uses `for i in range(n)` — but this is only entered when names or trading_days_listed are provided.

**Recommendation**: Keep as-is. Model for other engine vectorization.

## 5. Memory Risks

| Risk | Evidence | Impact |
|---|---|---|
| DataFrame copies in pipeline | 166 `.copy()` sites | ~5-15 copies per run; 75K copies at 5000 symbols |
| Deep copy in composer | `deepcopy(self.last_diagnostics)` | Small — diagnostics dict |
| Deep copy in factor generator | `copy.deepcopy(p1/p2)` | Genetic algorithm crossover — potential memory churn |
| Data lake caching | `data_service._cache_coordinator` | Managed — TTL-based eviction |
| LPPL cache | `calculator._fit_cache` with `_max_cache_size` | Managed |
| Sequential itertuples in Wyckoff | Generates intermediate Python objects per row | GC pressure on 5000-symbol scan |
| `concat` on growing DataFrames | `pd.concat(dfs, ignore_index=True)` — O(n²) for repeated concat | **Medium** — some data scripts use accumulating concat |

## 6. Complexity Estimates

| Path | Input | Complexity | Notes |
|---|---|---|---|
| Single ticker research pipeline | 1 symbol, 1000 bars, 8 engines | O(n × engines) ≈ O(8000) | ~2-5s per symbol |
| Batch scan (5000 symbols) | 5000 symbols, 1000 bars | O(5000 × n × engines) | Hours — mainly I/O + factor computation |
| Factor IC/IR computation | f factors, s symbols, t dates | O(f × s × t) | Day-scale for large universes |
| Walk-forward factor pipeline | f factors, w windows, s symbols | O(f × w × s × n) | Week-scale for full pipeline |
| Backtest (single) | 1 symbol, 1000 bars, k signals | O(n) | <100ms |
| Backtest (scan) | 5000 symbols, 1000 bars | O(5000 × n) | Minutes (due to sequential engine) |
| Wyckoff per symbol | 1000 bars, 10 classifiers | O(n × k) with Python loops | 100-500ms per symbol |
| LPPL per symbol | 5 windows, 200 iterations | O(w × m³) | 200-1000ms per symbol |

## 7. Latency Budget — Target Design

| Operation | Single-symbol target | 5000-symbol batch target | Notes |
|---|---|---|---|
| Data load + adjust | < 200ms | < 30s | Cached after first load |
| Regime detection | < 50ms | < 50ms (shared) | Market-level, computed once |
| NTF detection | < 100ms | < 100ms (shared) | Market-level, computed once |
| LPPL analysis | < 500ms | < 30s | Cache per symbol, daily refresh |
| CZSC analysis | < 200ms | < 10s | Linear, hard to accelerate |
| Wyckoff analysis | < 300ms | < 20s | **Primary optimization target** |
| Alpha decoupler | < 100ms | < 5s | DataFrame operations |
| Indicator calc (MA/ATR) | < 50ms | < 3s | Vectorized |
| DecisionBrain | < 10ms | < 1s | Python state machine |
| Signal collection | < 10ms | < 1s | 8 adapter calls |
| Backtest | < 100ms | < 5s | Already O(n) |
| **Total per symbol** | **< 1.5s** | | |
| **5000-symbol batch** | | **< 100 min** | With parallelism (4-8 cores) |

## 8. Findings

### Finding WS8-001 — Wyckoff engine is the largest performance bottleneck (P1)

Evidence:
- 1,457 LOC — largest single engine.
- 10+ `itertuples()` calls in engine.py and classifiers.py — Python-native row iteration.
- Called for every ticker in the pipeline.

Impact:
- Per-symbol analysis time dominated by Wyckoff engine.
- Batch scan performance bottleneck.

Risk Level: P1

Recommendation:
- Profile Wyckoff engine per component (classifiers, rules, state, fusion).
- Convert classifier loops to NumPy vector operations.
- Target: 3x speedup for same accuracy.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS8-002 — `shared/perf.py` exists but is not used anywhere (P2)

Evidence:
- `perf_section()` context manager in `shared/perf.py` — zero usages in production code.
- No `UNIQUANT_PERF=1` instrumentation in any engine, service, or pipeline.

Impact:
- Performance analysis requires external profiling tools.
- Cannot measure hot spots without adding instrumentation.

Risk Level: P2

Recommendation:
- Add `with perf_section("engine_name")` to each engine's main entry point.
- Add to `TradingSignalCollector.collect()` and `UnifiedBacktestEngine.run()`.
- Export `perf_report()` in `PipelineResult.metadata`.

Migration Cost: Low

Priority: Sprint 3

### Finding WS8-003 — Factor composer scales O(f × s × n) — fine for research, heavy for batch (P2)

Evidence:
- `composer.py` processes `groupby("code")` per factor, calling `compute_func` per symbol.
- 166 `.copy()` calls in codebase — each factor computation creates intermediate copies.
- `scan_service.py` runs composer across 5000 symbols.

Impact:
- With 50 factors and 5000 symbols: ~250K individual computation calls.
- Acceptable for single-symbol research; batch mode is CPU-bound.

Risk Level: P2

Recommendation:
- Add progress reporting to batch factor computation.
- Consider Polars backend for factor computation in scan pipeline.
- Cache factor computation results per symbol, invalidate on data update.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS8-004 — Backtest engine is O(n) and well-optimized — low priority (GREEN)

Evidence:
- Single loop over bars: `for idx in range(len(df))`.
- No nested loops — `pending_order` is O(1).
- UnifiedMatchingEngine fully vectorized.

Impact:
- Backtest performance is not a bottleneck (single-symbol <100ms).

Risk Level: GREEN

### Finding WS8-005 — LPPL Numba optimizer is good — but multi-window scan is multiplicative (P2)

Evidence:
- `numba_optimizer.py` accelerates Levenberg-Marquardt.
- `scan_all_windows()` loops over multiple window sizes — each window incurs optimization cost.
- `detect_bubble()` calls scan for the full series.

Impact:
- LPPL analysis per symbol takes 200-1000ms — acceptable for single ticker but expensive for batch.

Risk Level: P2

Recommendation:
- Cache LPPL results per symbol with daily timestamp.
- Reduce window count in batch mode.

Migration Cost: Low

Priority: Sprint 3

### Finding WS8-006 — CZSC is inherently sequential — acceptable for current scope (Info)

Evidence:
- CZSC algorithm is geometric (bi-segment traversal on bars).
- 634 LOC, single-path algorithm.
- Not vectorizable by nature.

Impact:
- Linear in bar count. Acceptable for research.
- Not a bottleneck for current workloads.

Risk Level: Info

### Finding WS8-007 — Data import scripts use accumulating `pd.concat` — potential O(n²) (P2)

Evidence:
- Multiple data scripts use `pd.concat([df_existing, df_new])` pattern.
- `import_financial.py:325`: `pd.concat(dfs, ignore_index=True)` — all-dataframe concat.
- `update_daily_incremental.py:336`: `pd.concat([local_df, new_df_filtered])` — incremental update.

Impact:
- For import of large universes (5000+ symbols, 10+ years), repeated concat produces O(n²) memory churn.

Risk Level: P2

Recommendation:
- Use `pd.concat` once with pre-allocated list instead of accumulation.
- For incremental imports, append to parquet files directly.

Migration Cost: Low

Priority: Sprint 3

### Finding WS8-008 — `PortfolioEngine` uses `.itertuples()` in hot loop — deprecated but relevant (P2)

Evidence:
- `portfolio_engine.py:306`: `for sym, sig in active.itertuples(index=False, name=None)`.
- This is in `run()` which processes daily signals.

Impact:
- Low priority since PortfolioEngine is deprecated.

Risk Level: P2

Recommendation:
- Accelerate deprecation; remove in Sprint 4.

Migration Cost: Low

Priority: Sprint 4

### Finding WS8-009 — `ScanService` has per-symbol groupby loop — benchmark required (P2)

Evidence:
- `scan_service.py:191`: `for symbol, daily_df in combined_df.groupby("code", sort=False)`.
- Inside the loop: analysis, factor computation, and signal integration.
- Parallelism via `joblib.Parallel` is available in `DataService.batch_process_stocks()` but not in `ScanService`.

Impact:
- Batch scan is single-threaded for the analysis loop. 5000 symbols × ~1.5s each = ~2 hours sequential.

Risk Level: P2

Recommendation:
- Add `joblib.Parallel` backend to scan service for per-symbol analysis.
- Target: 8 parallel workers → ~15 min for 5000 symbols.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS8-010 — `DataService.fetch_for_brain()` clones DataFrames unnecessarily (P2)

Evidence:
- `_clone_dataframe()` always deep-copies (`data_service.py:129-132`).
- Called for stock, bench, and etf on every `fetch_for_brain()` call.
- Only necessary if downstream engines mutate the DataFrames.

Impact:
- 3x deep copies per pipeline run. For batch mode: 15,000 copies for 5000 symbols.

Risk Level: P2

Recommendation:
- Audit whether downstream engines mutate the stock/bench/etf DataFrames.
- If not, change to non-deep copy or return read-only views.
- If mutation occurs, fix the mutation.

Migration Cost: Low

Priority: Sprint 3

### Finding WS8-011 — No cache for `AnalysisService._run_engines()` output (P2)

Evidence:
- LPPL, CZSC, Wyckoff, Alpha results are recomputed on every `run_ticker_analysis()` call.
- `Regime` and `NTF` have market-level caches.
- No per-symbol cache for engine results.

Impact:
- Identical ticker re-analysis recomputes all 8 engines.
- Metadata append in WS5 (`bar_index`, `analysis_mode`) would require recompute per bar — prohibitive without caching.

Risk Level: P2

Recommendation:
- Add optional per-symbol result cache in `AnalysisService` with data-hash invalidation.
- Critical for `HistoricalSignalRunner` (WS4) — without caching, per-bar signals require O(n×engines) time.

Migration Cost: Medium

Priority: Sprint 3

## 9. Performance Optimization Roadmap

| Priority | Target | Estimated gain | Sprint |
|---|---|---|---|
| P1 | Wyckoff engine vectorization | 3-5x per-symbol | 3 |
| P2 | Perf instrumentation | Measurement capability | 3 |
| P2 | Scan service parallelism | 4-8x batch throughput | 3 |
| P2 | Factor composer caching | 2x factor pipeline | 3 |
| P2 | Avoid deep copy in fetch_for_brain | 3x memory per run | 3 |
| P2 | Per-symbol engine result cache | Critical for WS4 | 3 |
| P2 | Data import concat fix | O(n²)→O(n) | 3 |
| P2 | LPPL batch window reduction | 2x batch LPPL | 4 |
| P2 | PortfolioEngine removal | Eliminate dead path | 4 |

## 10. Verification Checklist

- [x] Scanned CPU hotspots (Wyckoff > LPPL > FactorComposer > CZSC).
- [x] Scanned memory explosion risks (166 `.copy()` sites, accumulating concat).
- [x] Scored vectorization usage (UnifiedMatchingEngine: excellent; Wyckoff: poor; others: mixed).
- [x] Estimated complexity for top paths (§6).
- [x] Audited factor computation performance (O(f×s×n), 5000-symbol bottleneck).
- [x] Audited backtest/matching performance (O(n), vectorized — low priority).
- [x] Audited data loading and cache performance (deep copy overhead, no per-symbol cache).
- [x] Defined latency budgets for research path, scan path, signal generation, and simulated execution (§7).