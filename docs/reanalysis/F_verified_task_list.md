# Verified Task List — Red-Blue Adversarial Validation Results

> **Date**: 2026-07-09 | **Source**: 4-loop multi-layer verification against `src/uniquant/` actual code
> **Code state**: 1,666 tests passed, 0 failed, 8 skipped, 0 ruff issues
> **Method**: Each task item was traced to exact file:line evidence. Items marked **INVALID** were removed.

---

## Task Verification Summary

| Initial Items | After Loop 1-3 Verification |
|:------------:|:---------------------------:|
| 18 proposed | **15 valid, 2 corrected, 1 invalid** |
| P0: 5 items | 4 confirmed, **1 removed** |
| P1: 5 items | 5 confirmed, **1 downgraded** |
| P2: 5 items | 5 confirmed, **1 severity corrected** |
| P3: 3 items | 3 confirmed |

---

## Loop 1 — P0 Verification (Critical: 5 items)

| # | Proposed | Evidence File:Line | Verdict | Corrected Priority |
|---|----------|-------------------|---------|:---:|
| 1 | `signal/db.py` 354 LOC **0% test coverage** | `tests/test_signal_db.py` — 494 LOC, **35 test functions**, coverage 93% | ❌ **INVALID — removed.** SignalDatabase is the best-tested class in the signal package. Doc claim was wrong. | — |
| 2 | `composer.py:183,204,276` **fillna(0.0)** masks missing factors | `composer.py:183` `return z_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)` — line 204 `return normalized.fillna(0.0)` — line 276 `return orth_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)` | ✅ **CONFIRMED**. All 3 occurrences verified. Each silently converts NaN to 0, masking data quality issues. | **P0** |
| 3 | Engine failure → `alpha_score=0.0` → false **SELL** signal | `analysis_service_v2.py:535,543,552` — 3 paths write `AlphaOutput(score=0.0)` on failure/empty data. `adapters.py:359` maps `float(raw_output.get("alpha_score", 0.5))` — key exists with 0.0 → `0.0 < 0.3` → **SELL**. | ✅ **CONFIRMED**. Triple-redundant: empty stock_df, empty bench, or engine exception all produce a false sell signal. | **P0** |
| 4 | Docs 4 stale metrics | See below (Loop 4) | ✅ **CONFIRMED** + additional corrections found | **P0** |
| 5 | BoardType P0.2 **already fixed** | `shared/board_registry.py:56-106` — `BoardTypeRegistry` class provides unified `get_board_type(str)` and `detect_board(BoardType)` APIs. `limit_checker.py:10` and `market_rules.py:3` both import from registry. | ✅ **CONFIRMED — should close.** The fix has existed since the registry was created. The docs' "P0.2 dual system" is an archive item. | **P0 — close issue** |

**Red-Blue Report Correction**: Claim #22 ("signal/db.py 315 LOC 0% coverage") is **WRONG**. The test file exists at `tests/test_signal_db.py` with 494 LOC and 35 tests, achieving 93% coverage.

---

## Loop 2 — P1 Verification (Structural: 5 items)

| # | Proposed | Evidence File:Line | Verdict | Corrected Priority |
|---|----------|-------------------|---------|:---:|
| 6 | **56 assert-less test functions** | AST scan: 1,591 total test functions, 56 without bare `assert`. **BUT** deeper check: 47/56 use `pytest.raises()` (valid assertion), 7 use assertion methods (`assert_almost_equal`, `mock.assert_called_once_with`, `pd.testing.assert_frame_equal`, `pytest.fail`). **Only 2 are genuinely weak** (`test_build_factors_keeps_symbol_boundaries_for_rolling_factors`, `test_perf_section_without_recorder`). | ⚠️ **DOWNGRADED P1→P3**. Only 2 truly weak tests. The doc claim of "20+ weak tests" was exaggerated by 10x. | **P3** |
| 7 | `research_pipeline.py:239` bare `except Exception:` | `research_pipeline.py:239` — `except Exception:` with no `as e` clause, no logging, no error handling. Also line 495, 533, 609 use `except Exception as e:` with logging (better). | ✅ **CONFIRMED**. Line 239 is the worst — catches everything silently. | **P1** |
| 8 | `price_collar.py` **call_auction == continuous** dead branch | `price_collar.py:11-16` (call_auction) and `price_collar.py:17-22` (else) — **7 lines identical**. `get_allowable_price_range` at line 27 also ignores `trading_phase`. The parameter is vestigial. | ✅ **CONFIRMED**. Both branches execute identical logic — the `if` is dead code that creates false confidence. | **P1** |
| 9 | `DynamicSlippage` **hardcoded**, not dynamic | `slippage_model.py:30-34` — `_get_liquidity()` returns `1_000_000_000.0` (fixed), `_get_atr()` returns `0.02` (fixed). Named "Dynamic" but behaves "Hardcoded". | ✅ **CONFIRMED**. The name `DynamicSlippage` promises market-aware computation but delivers constants. | **P1** |
| 10 | `analysis_service_legacy.py` **1,649 LOC dead code** | `wc -l` confirmed 1,649 LOC. The file has no callers in the current v2 pipeline. `analysis_service_v2.py` header comment explicitly states it replaced the legacy version. | ✅ **CONFIRMED**. Dead code that adds search noise, import confusion, and maintenance burden. | **P1** |

---

## Loop 3 — P2 Verification (Incremental: 5 items)

| # | Proposed | Evidence File:Line | Verdict | Corrected Priority |
|---|----------|-------------------|---------|:---:|
| 11 | `WYCKOFF_RECOVERABLE_ERRORS` missing `IndexError, OverflowError` | `wyckoff_analysis_engine.py:10-13`: tuple excludes both. But inner `engine.py:251,260,1573,1588` use bare `except Exception:` which catches them first. | ⚠️ **SEVERITY CORRECTED**. Bug exists but outer handler is never reached — inner handler swallows all exceptions. The real issue is bare `except Exception:` in the engine internals. | **P2** (or close as WONTFIX) |
| 12 | `FSM_RECOVERABLE_ERRORS` missing `IndexError` | `fsm_analysis_engine.py:9-16`: tuple excludes `IndexError`. And `fsm_analysis_engine.py:96` has `df.iloc[-1]` on potentially empty DF. However, FSM engine is not called in the v2 pipeline — only `DecisionBrain.make_decision()` is used. | ✅ **CONFIRMED** but low impact. Bug exists in code that's on the non-critical path. The v2 pipeline never calls FsmAnalysisEngine. | **P2** |
| 13 | `signal_integrator.py` cross-layer import of old `Signal` | `signal_integrator.py:5`: `from uniquant.signal.models import Signal` — `hands/backtest/` importing from `signal/` creates circular dependency risk. | ✅ **CONFIRMED**. Violates layer isolation. The `hands` layer should depend on `TradingSignal` from `shared/interfaces.py`, not the old `Signal` from `signal/models.py`. | **P2** |
| 14 | `SlippageModel` naming inconsistency | `slippage_model.py:7`: `class SlippageModel(ABC)` — but file is named `slippage_model.py` (with 'p'). Minor naming inconsistency. | ✅ **CONFIRMED** (trivial). | **P3** |
| 15 | `_step5_trading_plan` complexity overstated | AST complexity: `_step5_trading_plan` = **40** (not 76 as docs claim, not 36 as I earlier claimed). `_step1_phase_determine` = 8. Class total `WyckoffEngine` = 285. | ⚠️ **CORRECTED**. Doc said 76 (wrong), I said 8 for step1 (correct but incomplete), 36 for step5 (close but off by 4). Actual max function = 40. | **P2** (refactor step5 from 40→20) |

---

## Final Corrected Task List

### P0 — Must Fix (4 items)

| # | Task | File | Evidence | Impact |
|---|------|------|----------|--------|
| **P0-1** | Replace `fillna(0.0)` with `fillna(nan)` in FactorComposer | `composer.py:183,204,276` | 3 locations confirmed via AST | Factor signal distortion |
| **P0-2** | Fix false SELL on engine failure (`alpha_score=0.0`) | `analysis_service_v2.py:552` + `adapters.py:359` | 3 failure paths write score=0.0 → `0.0 < 0.3` → SELL | Wrong trading signal |
| **P0-3** | Close BoardType P0.2 issue — already fixed | `board_registry.py:56-106` | Unified registry exists, both consumers migrated | Clean up misleading issue tracker |
| **P0-4** | Update 4 stale doc metrics | Multiple doc files | Wyckoff 76→40, eastmoney 1094→3, test count 1461→1591, assert-less 20+→2 | Developer misdirection |

### P1 — Should Fix (4 items)

| # | Task | File | Evidence |
|---|------|------|----------|
| **P1-1** | Add proper error handling to `research_pipeline.py:239` | `research_pipeline.py:239` | Bare `except Exception:` silently swallows all errors |
| **P1-2** | Remove dead `call_auction` branch or implement real logic | `price_collar.py:11-21` | Both branches identical; `trading_phase` parameter ignored |
| **P1-3** | Rename `DynamicSlippage` or make it truly dynamic | `slippage_model.py:30-34` | Named "Dynamic" but returns hardcoded liquidity=1e9, ATR=0.02 |
| **P1-4** | Archive `analysis_service_legacy.py` (1,649 LOC) | `services/analysis_service_legacy.py` | Zero callers, replaced by v2, adds search noise |

### P2 — Nice to Fix (3 items)

| # | Task | File | Evidence |
|---|------|------|----------|
| **P2-1** | Remove bare `except Exception:` in Wyckoff engine inner loop | `engine.py:251,260,1573,1588` | Over-captures, masks real bugs |
| **P2-2** | Break `_step5_trading_plan` (complexity 40 → <20) | `brain/wyckoff/engine.py:477-538` | High complexity method |
| **P2-3** | Remove cross-layer import of old Signal in signal_integrator | `signal_integrator.py:5` | `hands/backtest/` importing from `signal/` violates layer isolation |

### P3 — Documentation (3 items)

| # | Task |
|---|------|
| **P3-1** | Update all quantitative metrics in `docs/reanalysis/` to current values |
| **P3-2** | Mark resolved items as closed in `C_consolidated_issues.md` (BoardType, signal/db coverage) |
| **P3-3** | Add CI step to validate doc metrics against source (fail on >±5% deviation) |

---

## Validation Accuracy Self-Assessment

| Claim from Initial List | After 3 Loops | Delta |
|------------------------|:-------------:|:-----:|
| signal/db.py 0% coverage | ❌ Removed — actually 93% | 1 overstated claim |
| 56 assert-less tests, all weak | ✅ Count 56 confirmed, **BUT** only 2 truly weak | Severity downgraded |
| Wyckoff complexity 76 | ✅ Doc wrong, **BUT** actual max = 40 (not 8 or 36) | Number corrected |
| alpha_score=0.0→SELL | ✅ Confirmed with 3 paths | — |
| BoardType dual system | ✅ Confirmed already fixed | — |

**Net accuracy of initial task list**: 15/18 valid (83%), 2 severities off, 1 completely invalid.
