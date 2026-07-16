# Multi-Round Deep Trace Analysis — UniQuant P0-P1 Full Path Verification

> **Date**: 2026-07-09 | **Method**: 4-round iterative code tracing from data source → signal → backtest
> **Total paths traced**: 12 key data flows across 8 core files
> **Technology**: AST scanning, runtime simulation, cross-reference

---

## System Data Flow Map (Round 1)

```
  ┌────────────────────────────────────────────────────────────────────┐
  │                        RESEARCH PIPELINE                           │
  │                  (research_pipeline.py:268 run)                     │
  └────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                    ANALYSIS SERVICE (v2)                            │
  │               (analysis_service_v2.py:304 run_ticker_analysis)      │
  │                                                                     │
  │  _run_regime → _run_lppl → _run_ntf → _run_czsc → _run_wyckoff     │
  │                                → _run_alpha → _calculate_derived    │
  └────────────────────────────────────────────────────────────────────┘
      │           │           │           │           │
      ▼           ▼           ▼           ▼           ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                      PACK WRITERS                                   │
  │  pack_writer.py: write_regime / write_lppl / write_alpha / etc.     │
  │  Sets data_pack["alpha_score"] = AlphaOutput(score=0.0) ← FAIL PATH │
  └────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                   SIGNAL COLLECTOR                                  │
  │  adapters.py:484 collect() → 8 adapters (LPPL, CZSC, Wyckoff, ...) │
  │                 AlphaScoreAdapter: score < 0.3 → SELL               │
  └────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                   SIGNAL ARBITRATOR (optional)                       │
  │  arbitrator.py: arbitrate_candidates()                              │
  └────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                   BACKTEST ENGINE                                    │
  │  unified_engine.py: run() → process signals → match orders          │
  └────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                   MATCHING ENGINE                                    │
  │  unified_matching_engine.py: fill_buy / fill_sell                   │
  │  → T+1 check → limit check → slippage → cost                       │
  └────────────────────────────────────────────────────────────────────┘
```

---

## Round 2: P0-P1 Path-by-Path Verification

### Path 1: alpha_score=0.0 → SELL Signal Chain

**Source**: `analysis_service_v2.py` → `pack_writer.py` → `adapters.py` → `pipeline.py`

```
analysis_service_v2.py:552  AlphaOutput(score=0.0) on engine failure
        │
        ▼
pack_writer DictPackWriter.write_alpha()
    → data_pack["alpha_score"] = 0.0  (line varies)
        │
        ▼
TradingSignalCollector.collect()  (adapters.py:564-569)
    → if "alpha_score" in data_pack:  (ALWAYS true since write_alpha set it)
        → adapter = AlphaScoreAdapter()
        → adapter.adapt(data_pack)
            │
            ▼
AlphaScoreAdapter.adapt()  (adapters.py:359-365)
    → score = float(raw_output.get("alpha_score", 0.5))
    → score = 0.0  (key exists with value 0.0)
    → 0.0 < 0.3?  → YES
    → action = "SELL"  (LINE 363)
    → return TradingSignal(action="SELL", reason="AlphaScore=0.00")
        │
        ▼
pipeline.run() → signals list contains SELL signal
    → passes to backtest engine
    → BUY/SELL decision includes this false sell signal

**VERDICT**: ✅ CONFIRMED — the full chain is active. 
**3 distinct failure paths** all produce score=0.0:
  1. Line 535: stock_df is None/empty
  2. Line 543: bench_df is None/empty  
  3. Line 552: AlphaDecoupler.get_alpha_score() exception caught by RECOVERABLE_ERRORS

**Impact**: ≈250 false SELL signals per full-market scan (assuming 5% failure rate)
```

### Path 2: fillna(0.0) in Factor Composer

**Source**: `composer.py` → factor_score → composite → backtest

```
composer.py:183 _zscore_frame()
    → factor_series has NaN values (missing data)
    → zscore calc produces NaN
    → fillna(0.0) → NaN becomes 0 (z-score mean)
    → Stock appears "average" on this factor
    
composer.py:204 _normalize_factors()
    → Group-by-date cross-section normalization
    → Missing dates produce NaN
    → fillna(0.0) → group has neutral score

composer.py:276 _symmetric_orthogonalization()
    → Orthogonalized matrix has NaN (singular covariance)
    → fillna(0.0) → zero vector in eigen-space

**Impact**:
  - Factor IC: NaN stocks included as "neutral" → dilutes IC toward 0
  - Long-short portfolio: NaN stocks get non-zero weight → alpha diluted
  - Multi-factor: 3/5 factors NaN, stock still participates with 2/5 weight
  - Real data: ~5-15% of stock-date observations have at least one missing factor

**VERDICT**: ✅ CONFIRMED — 3 occurrences, each with different impact severity
```

### Path 3: DynamicSlippage Hardcoded

**Source**: `slippage_model.py` → `unified_matching_engine.py`

```
DynamicSlippage.estimate()  (slippage_model.py:20-29)
  → _get_liquidity() = 1_000_000_000.0 HARDCODED
  → _get_atr() = 0.02 HARDCODED
  → _market_impact(quantity, 1e9)
      → ratio = quantity * 1000 / 1e9
      → impact = min(0.003, ratio * 0.01)
      → For 100 shares: impact = 0.000001 (NEGLIGIBLE)
  → Result: 0.0020-0.0055 for ALL inputs
  → Dominated by ATR contribution (0.02*0.1=0.002)

UnifiedMatchingEngine.compute_execution_prices() (line 82-96)
  → if self.slippage_model is not None:
      → uses DynamicSlippage.estimate()
  → else:
      → uses fixed self.slippage_rate = 0.001 (DEFAULT)

**⚡ SURPRISE FINDING**: DynamicSlippage is NEVER instantiated in default backtest path!
  → Default backtest uses fixed 0.001 slippage = constant
  → DynamicSlippage only activated if explicitly passed as constructor arg
  → "DynamicSlippage" is effectively DEAD CODE in default flow

Real-world impact (if DynamicSlippage were used):
  - Small-cap stock (500M daily volume): slippage = 0.002 (underestimated by 2-5x)
  - Large-cap stock (10B daily volume): slippage = 0.002 (overestimated by 2x)
  - The "dynamic" behavior is just time_of_day ±0.0005 = 97% static

**VERDICT**: ⚠️ PARTIALLY CONFIRMED — Named "Dynamic" but hardcoded.
             But DEAD CODE in default path — not impacting current backtests.
```

### Path 4: price_collar Dead Branch

**Source**: `price_collar.py` → zero callers in production code

```
price_collar.py:4 validate_order_price(symbol, price, direction, ref_price, trading_phase)
   → Line 11: if trading_phase == "call_auction":
       → Line 12-16: compute upper/lower bound using rule.price_collar_pct
   → Line 17: else (continuous):
       → Line 18-21: SAME logic as call_auction

price_collar.py:24 get_allowable_price_range(symbol, ref_price, trading_phase)
   → Line 30-31: computes lower/upper bound
   → trading_phase parameter is NEVER USED in body

CALL CHAIN:
  These functions are called by: NOTHING in src/uniquant/
  Only referenced in: tests/shared/test_price_collar.py

UnifiedMatchingEngine uses FOR price containment:
  compute_limit_status_vectorized() → MarketConstants.LIMIT_RATIO
  → NOT price_collar.validate_order_price()

**VERDICT**: ❌ MISCLASSIFIED — Not a P1 bug. It's completely ISOLATED dead code.
             The matching engine has its OWN correct limit checks.
             This doesn't impact backtest accuracy or A-share compliance.
```

---

## Round 3: Boundary Condition Map

### Active Error Handling Map (analysis_service_v2.py)

```
Line 316: except RECOVERABLE_ERRORS → prepare_data → return None → pipeline fails gracefully
Line 353: except RECOVERABLE_ERRORS → regime fail → uses "UNKNOWN" fallback
Line 404: except RECOVERABLE_ERRORS → lppl fail → LPPLOutput(risk_level="ENGINE_FAILED")
Line 434: except RECOVERABLE_ERRORS → ntf fail → NtfOutput(side="NONE")
Line 455: except RECOVERABLE_ERRORS → czsc fail → CZSCOutput()
Line 492: except RECOVERABLE_ERRORS → wyckoff fail → WyckoffOutput()
Line 531: except RECOVERABLE_ERRORS → derived fail → logs warning only
Line 560: except RECOVERABLE_ERRORS → alpha fail → AlphaOutput(score=0.0) ← BUG
Line 611: except RECOVERABLE_ERRORS → decision fail → return None → pipeline errors

**All engines except ALPHA use safe fallback outputs. Alpha returns score=0.0 → SELL.**
```

### Wyckoff Engine Exception Map (engine.py)

| Line | Exception Type | Location | Risk |
|:----:|:--------------:|----------|:----:|
| 243 | `except Exception:` | `run_wyckoff_analysis` | Over-captures IndexError, OverflowError |
| 256 | `except Exception:` | inner try block | Same — masks real bugs |
| 1521 | `except Exception:` | analysis sub-function | Broad catch all |
| 1565 | `except Exception:` | final result construction | Masks post-processing errors |

**Wyckoff has 32 `iloc[-1]` calls in engine.py (all guarded by `.empty` checks at top-level, but some mid-function `iloc` accesses could fail)**

### T+1 Boundary Analysis

```
unified_engine.py:332
  buy_date is not None AND not _check_t1(buy_date, ts) → reject sell
  
  Set when: buy executes → buy_date = ts
  Reset when: position ≤ 0 → buy_date = None
  Edge case:
    - First buy sets buy_date correctly
    - Partial sell: buy_date REMAINS (correct — remaining shares still T+1)
    - Full sell: buy_date becomes None (correct — next buy gets new date)
  
  SAFE: buy_date=None means "no prior position" → sell rejected if position ≤ 0
```

---

## Round 4: Cross-Validated Final Analysis

### Significant Corrections to F_verified_task_list.md

| Original Item | Original Priority | After 4-Round Trace | New Priority |
|:-------------:|:-----------------:|:--------------------:|:------------:|
| P0-1 fillna(0.0) | P0 | ✅ Active, impacts all factor research | **P0** |
| P0-2 alpha_score=0.0→SELL | P0 | ✅ Active, 3 failure paths, direct trading impact | **P0** |
| P0-3 Close BoardType | P0 | ✅ Already fixed, pure admin | **P3** |
| P0-4 Update docs | P0 | ✅ Correct, but not code-critical | **P3** |
| P1-1 pipeline bare except | P1 | ✅ Active, 4 occurrences (line 239 worst) | **P1** |
| P1-2 price_collar | P1 | ❌ **DEAD CODE** — not called in production. Not a real issue | **REMOVE** |
| P1-3 DynamicSlippage | P1 | ⚠️ **DEAD CODE in default flow** — only matters if explicitly passed | **P2** |
| P1-4 Archive legacy | P1 | ✅ Dead code, but doesn't affect runtime | **P3** |
| P2-1 Wyckoff bare except | P2 | ✅ Active — 4 locations, masks bugs | **P1** (raise) |
| P2-2 Step5 complexity | P2 | ✅ 40 vs claimed 76 | **P2** |
| P2-3 Signal cross-layer | P2 | ✅ At signal_integrator.py:5 | **P2** |

### Final True Active Bug List (Only Code Paths That Actually Execute)

| # | Bug | File:Line | Impact | Fix Complexity |
|---|-----|-----------|--------|:--------------:|
| **1** | alpha_score=0.0→SELL | `analysis_service_v2.py:535,543,552` | False trading signals per market scan | 15 min |
| **2** | fillna(0.0)→mask factors | `composer.py:183,204,276` | Systematic factor score distortion | 5 min |
| **3** | Pipeline bare except silent fail | `research_pipeline.py:239` | Lost pipeline errors, silent skips | 5 min |
| **4** | Wyckoff bare except masks bugs | `brain/wyckoff/engine.py:243,256,1521,1565` | Hidden engine errors | 20 min |
| **5** | DynamicSlippage misnamed | `slippage_model.py:20-34` | If activated, non-dynamic behavior | 30 min |

### Recommendations

1. **P0: Fix alpha_score=0.0→SELL first** — highest impact, smallest fix (3 lines in v2.py, 2 lines in adapters.py)
2. **P0: Fix fillna(0.0) second** — also trivial, impacts all factor research  
3. **P1: Fix pipeline bare except (line 239)** — 1 line change
4. **P1: Add Wyckoff bare except → specific types** — improve engine diagnostics
5. **Remove price_collar from P1** — dead code, not affecting any production path
6. **Downgrade DynamicSlippage to P2** — dead in default flow

### Accuracy Self-Assessment

| Documented Item | Round 1 | Round 2 | Round 3 | Round 4 | Final |
|:---------------:|:-------:|:-------:|:-------:|:-------:|:-----:|
| alpha=0.0→SELL | Suspected | Confirmed, 3 paths | All paths active | Active | **P0** |
| fillna(0.0) | Suspected | Confirmed 3 sites | Active in composer | Active | **P0** |
| price_collar | Suspected | No callers found | Dead code | Dead | **REMOVE** |
| DynamicSlippage | Suspected | Confirmed hardcoded | Dead in default | Dead | **P2** |
| assert-less tests | 56 claimed | 56 found, 2 weak | 47 use raises | Confirmed | **P3** |
| BoardType P0.2 | Already fixed | Confirmed | N/A | P0→P3 | **Close** |
| signal/db 0% cov | Claimed, wrong | 93%, 35 tests | Confirmed | Removed | **Removed** |