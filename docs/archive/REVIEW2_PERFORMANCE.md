# Performance Optimization Document — Second-Pass Review

> Reviewer: Senior quant engineer, code audit | Date: 2026-05-31
> Scope: `OPTIMIZATION_PERFORMANCE.md` v2 (corrected from v1 review)
> Input: v1 review (`REVIEW_PERFORMANCE.md`) + source code verification

---

## Summary

**Score: 7.5/10 — Significant improvement over v1. Most corrections are accurate, but one dangerous recommendation was introduced and several issues persist.**

v2 correctly addresses 8 of 9 v1 errors. The "零成本优化" section and architecture regression warning are welcome additions. However, v2 introduces a **critical new error** by recommending `workers=-1` without acknowledging the existing config explicitly warns against it (`config.yaml:311` — "必须为1，避免嵌套多进程死锁"). Performance numbers remain speculative despite the added disclaimer. The DE strategy mismatch (rand/1/bin vs best/1/bin) is still unacknowledged.

---

## V1 Correction Verification (9 items)

### ✅ V1-ERR-1: Wyckoff line 521 attribution — FIXED

**v1 problem:** Line 521 was claimed to be gap detection; actually "高位炸板遗迹" detection.

**v2 status:** Section 7.1 now correctly shows:
```python
# engine.py:521 (Step 2 高位炸板遗迹检测)
for row in recent_20.itertuples():
    pct = (row.close - row.open) / row.open if row.open > 0 else 0
    if pct > 0.09 and row.high > row.close * 1.02:
```
This matches `engine.py:521-526` exactly. **Fixed correctly.**

### ✅ V1-ERR-2: Gap detection uses iloc, not itertuples — FIXED

**v1 problem:** Gap detection was described as using `itertuples()`.

**v2 status:** Section 7.1 line 641 now says:
> `# engine.py:528-560 — 跳空缺口检测 (使用 iloc 索引, 非 itertuples)`

The code block at lines 642-645 correctly shows `iloc[i-1]`/`iloc[i]` pattern. **Fixed correctly.**

### ✅ V1-ERR-3: Speculative performance numbers — PARTIALLY FIXED

**v1 problem:** Numbers presented as facts with no profiling evidence.

**v2 status:** Line 175 now includes:
> ⚠️ 性能数据为估算值，未做实际 profiling 验证。实际加速比取决于数据长度(lppl窗口大小)和硬件平台。

However, the tables in Section 1 (line 22-28), Section 3.4 (lines 271-279), Section 5.4 (lines 500-506), and Section 7.3 (lines 696-700) still present numbers without "估算" or "待实测" labels. The disclaimer at line 175 only covers Section 2. **Partially fixed — disclaimer added but inconsistently applied.**

### ✅ V1-ERR-4: Workers parallelism overlooked — FIXED (but see NEW ERROR below)

**v1 problem:** Document didn't mention `workers=-1` config option.

**v2 status:** New section "零成本优化: 配置 workers=-1" added at lines 36-45. **However, this introduces a NEW error (see NEW-ERR-1 below).**

### ✅ V1-ERR-5: Numba mutation parameter mismatch — FIXED

**v1 problem:** `_fit_with_numba` passes `self.mutation` tuple incorrectly.

**v2 status:** Lines 122-123 now correctly unpack:
```python
mutation_min=self.mutation[0],
mutation_max=self.mutation[1],
```
This matches `_de_solve_numba(t, log_prices, bounds, popsize, maxiter, tol, mutation_min, mutation_max, recombination, seed)` at `numba_optimizer.py:176-187`. **Fixed correctly.**

### ✅ V1-ERR-6: seed=-1 sentinel — FIXED

**v1 problem:** Using `-1` as sentinel for "no seed" is non-Pythonic.

**v2 status:** Line 124 uses `seed=self.seed if self.seed >= 0 else -1`, and the comment at line 192 of `numba_optimizer.py` confirms `if seed >= 0: np.random.seed(seed)`. The sentinel works correctly. **Acceptable, documented.**

### ✅ V1-ERR-7: Numba/NumPy 2.x compatibility — FIXED

**v1 problem:** No mention of compatibility risk.

**v2 status:** Line 744 in risk table:
> Numba 对 NumPy 2.x 的兼容性尚未验证。如果 ABI 不兼容，JIT 编译可能静默失败。在 CI 中增加 Numba + NumPy 2.x 兼容性测试

**Fixed correctly.**

### ✅ V1-ERR-8: Architectural regression warning — FIXED

**v1 problem:** `compute_all_factors_batch` tight-couples data loading with factor computation.

**v2 status:** Line 359 now includes:
> ⚠️ This function couples data loading with factor computation, which is an architectural regression from the current pattern of pure DataFrame→Series factor functions. For production use, separate the data loading from batch computation.

**Fixed, though the warning's placement between code blocks is awkward.**

### ⚠️ V1-ERR-9: DE strategy mismatch — NOT FIXED

**v1 problem:** Numba DE uses `rand/1/bin` (random base vector) while scipy default is `best/1/bin` (best-so-far base vector). These converge differently, making the "5-15x" speedup claim an unfair comparison.

**v2 status:** No mention of this algorithmic difference anywhere in the document. Section 2.2 describes the Numba implementation but doesn't note the strategy difference. Section 2.4's performance comparison table still implies a direct apples-to-apples comparison.

**This should be documented. The Numba `rand/1/bin` is more exploratory (slower convergence per iteration but less likely to get stuck), while scipy's `best/1/bin` is more exploitative (faster convergence but more prone to local optima). The actual speedup depends on the problem landscape.**

---

## NEW Errors Introduced in v2

### 🔴 NEW-ERR-1: `workers=-1` recommendation contradicts existing config warning (CRITICAL)

**Claim (v2 lines 36-45):** Setting `lppl.optimizer.workers: -1` in config.yaml gives "4-8x 加速，零代码修改" and is the highest-priority optimization (P0).

**Actual config at `config/config.yaml:311`:**
```yaml
workers: 1             # 并行工作线程数 (必须为1，避免嵌套多进程死锁)
```

The existing config **explicitly warns** that workers must be 1 to avoid nested multiprocess deadlock. The v2 document completely ignores this warning.

**Why deadlock occurs:** `calculator.py` is called from analysis pipelines that may already run in a multiprocessing context (e.g., `engine.py` spawns workers via `ProcessPoolExecutor` for multi-stock analysis). Setting `workers=-1` inside `differential_evolution` causes scipy to spawn its own process pool, creating nested processes → deadlock on some platforms (especially Linux with `fork` start method).

**Evidence:** `engine.py:205-206` already uses a separate parallel mechanism:
```python
_DE_WORKERS = int(os.environ.get("UNIQUANT_DE_WORKERS", "-1"))
de_workers = _DE_WORKERS if _DE_WORKERS != -1 else max(1, (os.cpu_count() or 4) - 1)
```
The engine module uses `UNIQUANT_DE_WORKERS` env var and defaults to `cpu_count - 1`. This suggests the developer was aware of the deadlock issue and chose a safe approach for the engine but kept `calculator.py` at `workers=1` intentionally.

**Severity: CRITICAL.** If a user follows v2's P0 recommendation and sets `workers: -1`, they risk deadlocking their production pipeline. The document should:
1. Acknowledge the existing warning in config.yaml
2. Explain the deadlock risk
3. Recommend testing with `workers: -1` only in single-process contexts
4. Suggest `workers: 2` or `workers: 3` as safer alternatives if parallelism is needed

### 🟡 NEW-ERR-2: Line number for workers config is wrong

**Claim (v2 line 38):** "`calculator.py:35` 从配置读取 `self.workers = config.get(...)`"

**Actual code:**
- Line 35 is blank (end of `__init__`)
- Line 36 is `def _load_config(self):`
- Line 50 is `self.workers = config.get("lppl.optimizer.workers", LPPLConstants.WORKERS)`

The line number should be **50**, not 35.

**Severity: Low.** Minor inaccuracy, but undermines the "基于代码事实" claim.

### 🟡 NEW-ERR-3: "零成本优化" speedup claim is unsubstantiated

**Claim (v2 line 45):** `workers=-1` gives "4-8x 加速".

**Reality:** The speedup from parallelizing DE depends on:
- Number of CPU cores available
- Whether the calling context is already multiprocess (deadlock risk aside, nested parallelism adds overhead)
- Cost function evaluation time per call (~few μs for 200-point arrays)
- Process startup/teardown overhead per generation

For a cost function this cheap (4×4 linear solve per evaluation), the parallelization overhead may dominate, yielding **< 2x speedup** in practice. The "4-8x" claim has no basis.

**Severity: Medium.** Overstated claims mislead prioritization.

### 🟡 NEW-ERR-4: Performance tables lack per-table disclaimers

**v2 status:** The disclaimer at line 175 covers Section 2 only. Sections 3.4, 5.4, and 7.3 present numbers in tables without any indication they are estimates. A reader skimming the tables (which is how quant documents are consumed) will take the numbers at face value.

**Recommendation:** Add "(估算)" or "(待实测)" to each table cell containing a speculative number, or add a blanket disclaimer at the top of each table.

### 🟢 NEW-ERR-5: "手写 4×4 正规方程" description is imprecise

**Claim (v2 line 92):** `_reduced_cost_numba` uses "手写 4×4 正规方程，避免 `np.linalg.lstsq` 调用"

**Actual code (`numba_optimizer.py:70-91`):** The function manually accumulates the 4×4 Gram matrix (A) and right-hand side (rhs), then calls `np.linalg.solve(A, rhs)`. It's a manually-assembled normal equation system, but the actual solve still uses a NumPy function. "手写" (hand-written) is misleading — it's "手写矩阵组装 + np.linalg.solve", not a hand-written solver.

**Severity: Very low.** Just imprecise wording.

---

## Code Accuracy Verification

### Numba JIT code (Section 2.2) vs actual `numba_optimizer.py`

| Aspect | v2 Document Claim | Actual Code | Match? |
|--------|-------------------|-------------|--------|
| Decorator | `@njit(cache=True, fastmath=True)` | `@njit(cache=True, fastmath=True)` at lines 13, 100, 175 | ✅ |
| Function name | `_de_solve_numba` | `_de_solve_numba` at line 176 | ✅ |
| Parameters | `t, log_prices, bounds, popsize=15, maxiter=100, ...` | Exact match at lines 176-187 | ✅ |
| Cost function | `_reduced_cost_numba` | `_reduced_cost_numba` at line 14 | ✅ |
| Linear solver | `_solve_linear_parameters_numba` | `_solve_linear_parameters_numba` at line 101 | ✅ |
| Strategy | Not mentioned | `rand/1/bin` (r1 + F*(r2-r3)) at line 230 | ❌ Missing |
| Normal equations | "手写 4×4 正规方程" | Manual Gram matrix + `np.linalg.solve` | ⚠️ Imprecise |
| Line range | 176-264 | 176-264 | ✅ |

### Wyckoff code examples (Section 7) vs actual `engine.py`

| Location | v2 Code Block | Actual Code | Match? |
|----------|--------------|-------------|--------|
| Line 521 | `for row in recent_20.itertuples():` + 炸板检测 | Lines 521-526: exact match | ✅ |
| Lines 528-560 | `for i in range(1, len(recent_20)):` + `iloc[i-1]`/`iloc[i]` | Lines 532-561: exact match | ✅ |
| Line 600 | `for row in reversed(list(recent_20.itertuples())):` + Spring | Lines 600-630: exact match | ✅ |
| Line 639 | `for row in recent_5.itertuples():` + SOS | Lines 639-651: exact match | ✅ |
| Line 658 | `for row in recent_10.itertuples():` + UTAD | Lines 658-661: exact match | ✅ |

**All 5 Wyckoff code locations are now correctly attributed.** This is a complete fix from v1.

### `storage_manager.py` code (Section 3) vs actual

| Aspect | v2 Claim | Actual Code | Match? |
|--------|----------|-------------|--------|
| `read_parquet` line | 117 | 98 (`def read_parquet`), 107 (`pd.read_parquet`) | ⚠️ Close |
| `pd.read_parquet()` call | Line 117 | Line 107 | ❌ Wrong line |
| `batch_read_data` serial | Lines 430-436 | Lines 547-562 | ❌ Wrong lines |
| No `columns` parameter | Claimed | Confirmed — `read_parquet(self, file_path, normalize=True)` | ✅ |

### `custom_factors.py` (Section 4) vs actual

| Aspect | v2 Claim | Actual Code | Match? |
|--------|----------|-------------|--------|
| `compute_momentum_20d` | `df['close'].pct_change(20, fill_method=None)` | Line 11: exact match | ✅ |
| No batch interface | Claimed | Confirmed — all functions are single-DataFrame | ✅ |

### `calculator.py` workers config (Section 2 零成本优化) vs actual

| Aspect | v2 Claim | Actual Code | Match? |
|--------|----------|-------------|--------|
| Config key | `lppl.optimizer.workers` | Line 50: `config.get("lppl.optimizer.workers", LPPLConstants.WORKERS)` | ✅ |
| Line number | 35 | 50 | ❌ |
| Default value | Not stated | `LPPLConstants.WORKERS = 1` (`technical.py:130`) | ✅ |
| Passes to DE | `workers=self.workers` | Line 320: `workers=self.workers` | ✅ |
| Config warning | Not mentioned | `config.yaml:311`: "必须为1，避免嵌套多进程死锁" | ❌ Dangerous omission |

---

## Batch Factor `.where()` Fix Assessment

**v1 review (Error 3 in code quality):** `ma_long.replace(0, np.nan)` is wrong for prices — should use `.where()`.

**v2 status:** The batch functions in Section 4.2 use `.where()`:
- Line 344: `ma_short / ma_long.where(ma_long != 0, np.nan) - 1`
- Line 355: `gain / loss.where(loss != 0, np.nan)`

**However**, the existing single-stock functions in `custom_factors.py` still use `.replace(0, np.nan)`:
- Line 43: `ma20.replace(0, np.nan)`
- Line 52: `ma60.replace(0, np.nan)`
- Line 61: `vol20.replace(0, np.nan)`
- Line 71: `loss.replace(0, np.nan)`

**Assessment:** The v2 batch implementation is technically correct and an improvement over the existing code. But it creates an inconsistency: batch functions use `.where()`, single functions use `.replace()`. The document should note this discrepancy and recommend migrating the single-stock functions to `.where()` as well.

**Also note:** `.where(ma_long != 0, np.nan)` is equivalent to `.replace(0, np.nan)` when values are exactly 0, but `.where()` is more precise — it only replaces cells where the condition is False, while `.replace()` does value matching. For floating-point data, `.where()` is safer.

---

## Architecture Regression Note Accuracy

**v2 claim (line 359):** `compute_all_factors_batch` is an architectural regression because it couples data loading with factor computation.

**Assessment: Accurate.** The current design pattern is:
```python
# Current: pure function, takes DataFrame, returns Series
def compute_momentum_20d(df: pd.DataFrame) -> pd.Series:
    return df['close'].pct_change(20, fill_method=None)
```

The proposed `compute_all_factors_batch` breaks this by calling `storage.read_local_raw()` inside the function. This:
1. Creates a dependency on `StorageManager` in the factor module
2. Makes unit testing harder (can't test without a storage backend)
3. Violates the single-responsibility principle

**The warning is well-placed and accurate.** The recommended pattern is to separate data loading into a caller and pass the loaded data as matrices to pure batch functions.

---

## Missed Opportunities (from v1, still relevant)

| ID | Issue | v2 Status | Still Relevant? |
|----|-------|-----------|-----------------|
| M1 | `workers=-1` config exists | ⚠️ Addressed but dangerously | Yes — needs safe recommendation |
| M2 | `fit()` doesn't use cache | Referenced in appendix line 789 | Yes — not resolved |
| M3 | Numba/NumPy 2.x compat | ✅ Addressed in risk table | Done |
| M4 | Float64 hash for cache | Noted in appendix line 791 | Yes — not resolved |
| M5 | `@handle_errors` overhead | Not addressed | Yes — low priority |
| M6 | Memory-mapped Parquet | Not addressed | Minor |
| M7 | Wyckoff ATR iloc loop | Not addressed | Low priority |

---

## Practical Impact Re-assessment

| Rank | Optimization | v2 Claim | Realistic Assessment | Risk |
|------|-------------|----------|---------------------|------|
| P0 | Numba JIT activation | 5-15x | 5-15x (if strategy diff acceptable) | Medium — numerical equivalence unvalidated |
| P0 | `workers=-1` config | 4-8x, zero effort | **DANGEROUS** — existing warning says deadlock risk | **High** |
| P1 | Parquet column pruning | 3-5x I/O | 3-5x (well-understood, low risk) | Low |
| P1 | Parallel data loading | 4-8x | 3-6x (ThreadPoolExecutor) | Low |
| P2 | Batch factor computation | 15x | 10-15x (with memory risk) | Medium |
| P3 | LRU cache expansion | 2-3x | Low marginal value for SSD-backed data | Low |
| P3 | Wyckoff vectorization | 5x | Negligible at 20 rows | None |

**Revised priority:**
1. Numba JIT activation (validate numerical equivalence first)
2. Parquet column pruning (safe, well-understood)
3. Parallel data loading with ThreadPoolExecutor
4. Batch factor computation (with chunking)
5. Do NOT set `workers=-1` without testing for deadlocks in the actual calling context

---

## Final Verdict

| Dimension | v1 | v2 | Notes |
|-----------|-----|-----|-------|
| Factual accuracy | 6/10 | 8/10 | Most line numbers fixed; NEW-ERR-1 is critical |
| Code correctness | 5/10 | 7/10 | Numba integration code is now runnable; `.where()` fix is correct |
| Safety of recommendations | 7/10 | 6/10 | `workers=-1` recommendation is actively dangerous |
| Completeness | 6/10 | 8/10 | "零成本优化" and risk notes added |
| Practical value | 7/10 | 8/10 | Good roadmap, but priorities need adjustment |

**Overall: 7.5/10** (up from v1's 6/10)

### Must-Fix Before Using as Implementation Reference

1. **Remove or heavily caveat the `workers=-1` recommendation.** The config.yaml explicitly says "必须为1，避免嵌套多进程死锁". Recommending `workers=-1` without acknowledging this is irresponsible. At minimum, add: "⚠️ `config.yaml` 中 workers 当前设为 1 并注明'必须为1，避免嵌套多进程死锁'。修改前需确认调用链中无嵌套多进程。"
2. **Add per-table disclaimers** for speculative numbers in Sections 3.4, 5.4, and 7.3.
3. **Document the DE strategy difference** (rand/1/bin vs best/1/bin) in Section 2.2 or 2.4.
4. **Fix line number 35 → 50** in the "零成本优化" section.

---

*Generated from code audit against `calculator.py`, `numba_optimizer.py`, `storage_manager.py`, `custom_factors.py`, `engine.py`, `config.yaml`, `technical.py` as of 2026-05-31.*
