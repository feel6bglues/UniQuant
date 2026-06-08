# R7 Performance Deep Analysis

> Generated: 2026-06-06 | Scope: 4 bottleneck hotspots across 4 modules
> Precision: line-level code audit with quantified I/O counts and loop iterations

---

## Executive Summary

| Bottleneck | Location | Severity | Root Cause | Estimated Impact (n=5000) |
|---|---|---|---|---|
| 6-format I/O probing | `storage_manager.py:251-281` | HIGH | Up to 5x redundant parquet reads per stock | 5x I/O latency on miss |
| board_mask recomputation | `unified_matching_engine.py:96-100` | HIGH | 5n Python calls to `get_board_type` instead of n | ~5x CPU overhead |
| Serial walk-forward windows | `walk_forward_pipeline.py:141-194` | HIGH | 100% parallelizable loops forced serial | O(W) serial, W windows |
| Stamp tax Python loop | `unified_matching_engine.py:240-243` | MEDIUM | Python for-loop vs numpy vectorized | ~50-100x slower than vectorized |

---

## 1. StorageManager.read_local_raw — 6-Format I/O Probing

**File**: `src/uniquant/data/lake/storage_manager.py:251-281`

### Code Under Analysis

```python
# Line 259-276
possible_symbols = [
    standard_symbol,        # e.g. "600000.SH"
    f"{clean_symbol}.SH",   # "600000.SH" (duplicate if standard was .SH)
    f"{clean_symbol}.SZ",   # "600000.SZ"
    f"{clean_symbol}.BJ",   # "600000.BJ"
    clean_symbol,           # "600000" (no suffix)
    symbol,                 # original input, e.g. "SH600000"
]

seen = set()
for test_symbol in possible_symbols:
    if test_symbol in seen:
        continue
    seen.add(test_symbol)
    file_path = self.daily_dir / f"{test_symbol}.parquet"
    df = self.read_parquet(str(file_path))   # <-- full parquet read attempt
    if not df.empty:
        return df
```

### I/O Count Analysis

`read_parquet` (line 97-113) performs TWO I/O operations per call:

1. **`Path.exists()` check** (line 101) — `stat()` syscall to check file existence
2. **`pd.read_parquet()`** (line 106) — full file deserialization if file exists

| Scenario | `possible_symbols` deduped count | stat() syscalls | pd.read_parquet() calls | Total I/O ops |
|---|---|---|---|---|
| Best case (1st match) | 6 entries, 1 hit on first | 1 | 1 | **2** |
| Typical case (2nd-3rd match) | 6 entries, hit after 2-3 misses | 3 | 3 | **6** |
| Worst case (no data) | 6 unique entries, all miss | 6 | 6 | **12** |

**Concrete scenario for a standard Shanghai stock** (`600000`):

1. `_get_stock_suffix("600000")` returns `.SH` (line 220-224, set lookup)
2. `standard_symbol = "600000.SH"`
3. Loop iteration 1: `"600000.SH"` — `exists()` → True → `pd.read_parquet()` → done
4. Result: **2 I/O ops** (optimal path)

**Concrete scenario for non-standard input** (`SH600000`):

1. `_get_stock_suffix("SH600000")` — after stripping, `clean_symbol = "600000"` → returns `.SH`
2. `standard_symbol = "600000.SH"`
3. Loop iteration 1: `"600000.SH"` — `exists()` → True → `pd.read_parquet()` → done
4. Result: **2 I/O ops** (still optimal because `_get_stock_suffix` normalizes)

**Worst-case scenario** (file does not exist for this stock):

1. Loop iterations 1-5: each calls `exists()` → False (no `pd.read_parquet`)
2. Loop iteration 6: `exists()` → False
3. Result: **6 stat() syscalls, 0 reads** — but the `seen` set only deduplicates across iterations, it does not prevent stat() calls

**Critical waste**: Even when the first attempt succeeds, `read_parquet` still performs an `exists()` check BEFORE reading. This means the correct path costs 1 stat + 1 read = 2 I/O ops. If the caller had already verified the file exists, this is 1 redundant syscall per call.

### Deeper Issue: `_get_stock_suffix` Redundant Work

`_get_stock_suffix` (lines 215-249) itself performs 1-3 set lookups in `self.all_stock_codes` to determine the suffix. Then `read_local_raw` builds `possible_symbols` which may re-test the same suffixes. For a stock starting with "6":

```
_get_stock_suffix: checks all_stock_codes for "600000.SH" → 1 set lookup
read_local_raw loop: tries "600000.SH" (correct), then "600000.SH" (deduplicated),
                     then "600000.SZ", "600000.BJ", "600000", original
```

The loop is a "belt and suspenders" approach that trades correctness for up to 5x I/O waste on a cache-miss path.

### Estimated Latency

| Component | Per-call latency (SSD) | Per-call latency (HDD/NFS) |
|---|---|---|
| `stat()` syscall | ~0.01ms | ~5-10ms |
| `pd.read_parquet()` (10MB file) | ~5-15ms | ~50-200ms |
| Full worst-case (6 attempts, all miss) | ~0.06ms (stat only) | ~30-60ms |
| Full worst-case (6 attempts, read at end) | ~30-90ms | ~300ms-1.2s |

For a backtest loading 5000 stocks with ~5% cache miss rate:
- **250 stocks × 6 stat() calls = 1500 extra syscalls**
- On NFS-backed data lake: **1500 × 5ms = 7.5 seconds** wasted

---

## 2. UnifiedMatchingEngine — board_mask 重复计算

**File**: `src/uniquant/hands/backtest/unified_matching_engine.py:79-101`

### Code Under Analysis

```python
# Lines 96-100 (fast path)
for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
    board_mask = np.array([get_board_type(s) == board_type for s in symbols])
    mask = board_mask & valid
    is_limit_up |= mask & (price_ratios >= up_r - tol)
    is_limit_down |= mask & (price_ratios <= down_r + tol)
```

### Call Count Analysis

`MarketConstants.LIMIT_RATIO` has **5 entries** (from `constants/market.py:77-83`):
- `"st"`: (1.05, 0.95)
- `"sci_tech"`: (1.20, 0.80)
- `"gem"`: (1.20, 0.80)
- `"beijing"`: (1.30, 0.70)
- `"main"`: (1.10, 0.90)

For n symbols (e.g., n=5000 for a full A-share universe):

| Metric | Current Implementation | Optimal Implementation |
|---|---|---|
| `get_board_type()` calls | **5n** (25,000) | **n** (5,000) |
| Python list comprehensions | 5 | 1 |
| `np.array()` allocations | 5 | 1 |
| String split operations | 5n | n |
| Prefix iteration (startswith) | ~8n (varies by board) | ~1.6n |

### `get_board_type` Internals (from `limit_checker.py:28-66`)

Each call to `get_board_type(symbol)` performs:

```python
def get_board_type(symbol: str, name: Optional[str] = None) -> str:
    code = symbol.split(".")[0] if "." in symbol else symbol  # string split
    # Then checks BOARD_PREFIX dicts:
    # "sci_tech": ["688", "689"] — 2 startswith checks
    # "gem": ["300", "301", "302"] — 3 startswith checks
    # "beijing": ["83", "87", "920"] — 3 startswith checks
    # "main": ["600", "601", "603", "605", "000", "001", "002"] — checked last
```

For a typical main-board stock (`600000.SH`):
- 1 string split
- 2 startswith checks (sci_tech) → miss
- 3 startswith checks (gem) → miss
- 3 startswith checks (beijing) → miss
- 1 string split result: starts with "6" → not in main prefixes yet...
- Actually the function falls through to `return "main"` at line 66

So per call: 1 split + 8 startswith operations. For 5n calls: **5n splits + 40n startswith**.

### Correct Approach

The symbol-to-board mapping is **invariant** across the LIMIT_RATIO loop. The correct implementation:

```python
# Pre-compute once: O(n)
board_types = np.array([get_board_type(s) for s in symbols])
for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
    board_mask = board_types == board_type  # O(n) numpy comparison
    mask = board_mask & valid
    is_limit_up |= mask & (price_ratios >= up_r - tol)
    is_limit_down |= mask & (price_ratios <= down_r + tol)
```

This reduces `get_board_type` calls from **5n** to **n** — an **80% reduction**.

### Secondary Issue: `get_board_rule` in buy path (line 165)

```python
lot_sizes = np.array([get_board_rule(s).lot_size for s in symbols], dtype=np.int64)
```

`get_board_rule` calls `detect_board` which does string operations. This is n calls per `fill_buy`. Could be cached or precomputed.

### Estimated Latency (n=5000)

| Operation | Current (5n) | Optimal (n) | Savings |
|---|---|---|---|
| `get_board_type` calls | 25,000 | 5,000 | 20,000 calls |
| String splits | 25,000 | 5,000 | 20,000 splits |
| `startswith` checks | ~200,000 | ~40,000 | ~160,000 checks |
| Python loop overhead | ~12ms | ~2.4ms | ~9.6ms |
| Total CPU time (est.) | ~15-25ms | ~3-5ms | **~12-20ms per call** |

Over a full backtest with 1000 trading days, called twice per day (buy + sell):
**1000 × 2 × 12ms = 24 seconds** of wasted CPU time.

---

## 3. WalkForwardFactorPipeline — Serial Window Traversal

**File**: `src/uniquant/brain/factors/walk_forward_pipeline.py:141-194`

### Code Under Analysis

```python
# Lines 141-194: serial window loop
for ts, te, ss, se in windows:
    train_df = df[(pd.to_datetime(df[date_col]) >= ts) & ...].copy()  # filter
    test_df = df[(pd.to_datetime(df[date_col]) >= ss) & ...].copy()   # filter

    ic_results = self.analyzer.compute_ic_ir(train_df, ...)  # EXPENSIVE

    weights = self._compute_weights(ic_results, factor_cols)  # cheap

    scored_df, _ = self.composer.process(test_df, ...)  # EXPENSIVE

    oos_ic_res = self.analyzer.compute_ic_ir(scored_df, ...)  # EXPENSIVE
```

### Window Count Analysis

From `_temporal_split` (lines 62-78):

```python
for start in range(train, n - test, test):
    windows.append(...)
```

With defaults `train_window=504, test_window=63`:

| Dataset duration | Total trading days (n) | Number of windows (W) |
|---|---|---|
| 3 years | ~756 | ~4 |
| 5 years | ~1260 | ~12 |
| 10 years | ~2520 | ~32 |
| 15 years | ~3780 | ~52 |

### Per-Window Computational Cost

Each window performs 3 expensive operations:

**Operation 1: `compute_ic_ir` on train_df** (lines 148-156)
- From `analyzer.py:243-380`:
  - `df.copy()` — O(n_train)
  - `sort_values([code_col, date_col])` — O(n_train × log(n_train))
  - For each factor × each holding_period (default 3 periods):
    - `groupby(code_col)[price_col].shift(-period)` — O(n_train)
    - `groupby(date_col).apply(calc_daily_ic)` — O(n_dates × n_stocks_per_date)
    - Each `calc_daily_ic` calls `compute_rank_ic` (Spearman correlation) — O(n_stocks_per_date)
  - Total: O(n_factors × n_periods × n_train × log(n_train))

**Operation 2: `composer.process` on test_df** (lines 164-169)
- From `composer.py:276-311`:
  - `compute_all_factors(df)` — iterates all registered factors, per-group computation
  - `_resolve_weights` — cheap dict lookup
  - `_build_composite_frame` → `_normalize_factors` → per-date z-score normalization
  - `_symmetric_orthogonalization` (if enabled) — eigenvalue decomposition O(k^3) per date
  - Total: O(n_factors × n_test × k^2) where k = number of factors

**Operation 3: `compute_ic_ir` on scored_df** (lines 172-180)
- Same as Operation 1 but on test data with single factor (`composite_score`)
- Total: O(n_periods × n_test × log(n_test))

### Parallelization Potential

**All 3 operations per window are independent** — no data flows from window i to window i+1:

| Dependency | Present? | Evidence |
|---|---|---|
| Window i reads from window i-1? | NO | Each window filters `df` independently |
| Window i writes to shared state? | NO | `window_results` is append-only list |
| `analyzer` state shared between windows? | YES (minor) | `self.results` overwritten each call (line 370-373), but only read after loop |
| `composer` state shared? | NO | Stateless computation |

**Parallelizable components per window**:
- The 3 `compute_ic_ir` / `composer.process` calls WITHIN a window could also be partially parallelized (OOS IC depends on `scored_df` from `composer.process`, but train IC and composer are independent).

### Parallelization Strategy

```
Window 0 ──────┬── compute_ic_ir(train) ──┐
               └── composer.process(test) ─┴── compute_ic_ir(oos)
Window 1 ──────┬── compute_ic_ir(train) ──┐
               └── composer.process(test) ─┴── compute_ic_ir(oos)
...
Window W-1 ────┬── compute_ic_ir(train) ──┐
               └── composer.process(test) ─┴── compute_ic_ir(oos)
```

- **Inter-window parallelism**: All W windows are embarrassingly parallel
- **Intra-window parallelism**: `compute_ic_ir(train)` and `composer.process(test)` are independent (within each window)

### Estimated Latency (5-year dataset, 5 factors, 3 holding periods)

| Component | Serial (current) | Parallel (8 cores) | Speedup |
|---|---|---|---|
| Window computation | W × T_window | T_window (CPU-bound) | ~W× (up to 8×) |
| Per-window T_window (est.) | ~2-5s | ~0.3-0.6s | ~8× |
| 12 windows total | ~24-60s | ~3-7.5s | **~8×** |
| 32 windows total | ~64-160s | ~8-20s | **~8×** |

### Additional Waste: Redundant `pd.to_datetime` Conversion

Lines 142-143:
```python
train_df = df[(pd.to_datetime(df[date_col]) >= ts) & (pd.to_datetime(df[date_col]) <= te)].copy()
test_df = df[(pd.to_datetime(df[date_col]) >= ss) & (pd.to_datetime(df[date_col]) <= se)].copy()
```

`pd.to_datetime(df[date_col])` is called **4 times per window** (twice for train, twice for test). For 12 windows: **48 redundant datetime conversions** of the full date column. The date column should be converted ONCE before the loop.

---

## 4. Stamp Tax — Python Loop vs Vectorized

**File**: `src/uniquant/hands/backtest/unified_matching_engine.py:240-243`

### Code Under Analysis

```python
# Lines 240-243 (fill_sell)
stamp_dates = pd.to_datetime(timestamps)                           # O(n) conversion
unique_dates = {d.date() for d in stamp_dates}                     # O(n) Python iteration
date_to_rate = {d: get_stamp_tax_pct(d) for d in unique_dates}    # O(U) where U=unique dates
stamp_duties = np.array([                                          # O(n) Python for-loop
    values[i] * date_to_rate[stamp_dates[i].date()]                # per-element dict lookup
    for i in range(n)
])
```

### Why This Is Slow

The stamp duty calculation has a **date-dependent rate** (line 43-44 of `cost_model.py`):

```python
_STAMP_TAX_CUTOFF = datetime.date(2023, 8, 28)

def get_stamp_tax_pct(trade_date: datetime.date) -> float:
    return STAMP_TAX_PCT if trade_date >= _STAMP_TAX_CUTOFF else STAMP_TAX_PCT_OLD
```

- Before 2023-08-28: `STAMP_TAX_PCT_OLD = 0.001` (千1)
- After 2023-08-28: `STAMP_TAX_PCT = 0.0005` (万5)

The current implementation uses a Python for-loop (line 243) to map each element to its rate via dict lookup.

### Python Loop Overhead Breakdown

For n=5000 stocks in a single sell batch:

| Operation | Per-element cost | Total (n=5000) |
|---|---|---|
| `stamp_dates[i].date()` | ~0.5μs (Timestamp.date() creation) | ~2.5ms |
| Dict lookup `date_to_rate[...]` | ~0.1μs | ~0.5ms |
| Float multiplication | ~0.05μs | ~0.25ms |
| `np.array()` construction | — | ~0.5ms |
| Python for-loop overhead | ~0.1μs/iter | ~0.5ms |
| **Total** | | **~4.25ms** |

### Vectorized Alternative

```python
# Step 1: Vectorized date conversion (already done)
stamp_dates = pd.to_datetime(timestamps)

# Step 2: Vectorized rate lookup (no Python loop)
cutoff = pd.Timestamp("2023-08-28")
rates = np.where(stamp_dates >= cutoff, STAMP_TAX_PCT, STAMP_TAX_PCT_OLD)

# Step 3: Vectorized multiplication
stamp_duties = values * rates
```

| Operation | Vectorized cost (n=5000) | Speedup vs Python |
|---|---|---|
| `np.where` comparison | ~0.02ms | ~125× |
| Float array multiply | ~0.01ms | ~25× |
| Total | **~0.03ms** | **~140×** |

### But Wait: Why the Complexity?

The code uses a dict lookup because `get_stamp_tax_pct` is a **function call** (line 242: `{d: get_stamp_tax_pct(d) for d in unique_dates}`). The function is scalar and date-aware. But in practice, A-share stamp tax changed exactly ONCE in history (2023-08-28). The entire date range collapses to at most **2 distinct rates**.

The dict comprehension on `unique_dates` is actually efficient for the rate computation itself (only U unique dates, typically 1 per day). The real waste is the **list comprehension on line 243** which iterates n elements in pure Python.

### Estimated Latency Impact

For a backtest with 1000 trading days, calling `fill_sell` once per day:

| Metric | Current (Python loop) | Vectorized | Savings |
|---|---|---|---|
| Per-call (n=5000) | ~4.25ms | ~0.03ms | ~4.22ms |
| Per-call (n=500, typical daily sell) | ~0.5ms | ~0.03ms | ~0.47ms |
| Full backtest (1000 days × n=500) | ~500ms | ~30ms | **~470ms** |

---

## Cross-Cutting Concerns

### Combined Impact on Full Backtest

Assuming: 5-year backtest, 5000 stocks, 1000 trading days, 5 factors, 3 holding periods, walk-forward with 12 windows.

| Bottleneck | Per-invocation waste | Invocations in backtest | Total waste |
|---|---|---|---|
| 6-format I/O probing | 0.06ms (stat-only miss) to 90ms (full read miss) | 5000 stocks × 1 init | ~0.3-450ms |
| board_mask recomputation | ~12-20ms | 2000 calls (buy+sell × 1000 days) | **~24-40s** |
| Serial walk-forward | ~24-60s total (12 windows) | 1 full run | **~24-60s** |
| Stamp tax Python loop | ~0.47ms | 1000 calls | **~0.47s** |
| **Total estimated waste** | | | **~48-100s** |

### Priority Ranking

1. **Walk-forward serial windows** — Highest absolute impact (24-60s), easiest to fix (add `concurrent.futures`)
2. **board_mask recomputation** — Second highest (24-40s), simple fix (pre-compute board_types array once)
3. **Stamp tax Python loop** — Moderate (0.47s), trivial fix (replace with `np.where`)
4. **6-format I/O probing** — Low absolute impact for SSD (~0.3ms), moderate for NFS (~450ms), but easy to fix (use `file_exists` cache or single canonical path)

### Quick Wins (Estimated Fix Complexity)

| Fix | Lines changed | Expected speedup |
|---|---|---|
| Pre-compute `board_types` once in `compute_limit_status_vectorized` | ~5 lines | 5× on limit checks |
| Vectorize stamp tax with `np.where` | ~3 lines | ~140× on stamp calc |
| Parallelize walk-forward with `ProcessPoolExecutor` | ~15 lines | Up to 8× (core-limited) |
| Cache `pd.to_datetime` before walk-forward loop | ~2 lines | ~48× less datetime conversion |
| Use `pathlib.Path.exists()` only (skip read) for probing | ~10 lines | Eliminates 80% of stat syscalls on miss |

---

## Appendix: Method-Level Performance Characteristics

### `is_trading_day` (trade_calendar_manager.py:103-124)

Each call in the T+1 hot loop:
1. `os.path.exists()` — stat syscall (line 107)
2. `pd.read_csv()` — full CSV parse if file exists (line 109) — **THIS IS CALLED PER ELEMENT IN THE T+1 LOOP**
3. `calendar['trade_date'].dt.strftime(...)` — vectorized but creates temporary series (line 113)
4. Fallback: set membership check in `_CN_HOLIDAYS` (line 121) — O(1) amortized

**Critical**: If `trade_calendar_{year}.csv` exists, every call to `is_trading_day` re-reads and re-parses the entire CSV file. The T+1 loop (lines 219-233) calls this 2× per element (buy date + current date), so for n=5000: **10,000 full CSV parses per sell batch**.

### `_next_trading_day` (unified_matching_engine.py:54-60)

```python
def _next_trading_day(self, date: pd.Timestamp) -> pd.Timestamp:
    d = date + pd.Timedelta(days=1)
    for _ in range(10):
        if self.trade_calendar.is_trading_day(d):
            return d
        d += pd.Timedelta(days=1)
```

Worst case: 10 iterations × 2 `is_trading_day` calls = 20 CSV reads. Called once per element in T+1 loop when the element reaches the `else` branch (line 231).

**Combined T+1 loop cost for n=5000**: Up to **30,000 CSV file parses** per sell batch — this is likely the single most expensive operation in the entire matching engine, dwarfing the board_mask issue.
