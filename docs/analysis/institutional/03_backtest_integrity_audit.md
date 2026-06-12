# WS3 — Backtest Integrity Audit

Generated: 2026-06-10

Scope: Identify every research backtest cheating risk in `UnifiedBacktestEngine`, `UnifiedMatchingEngine`, `BacktestEngine` (legacy), `PortfolioEngine`, `FactorAnalyzer`, and `WalkForwardFactorPipeline`.

## 1. Signal Timeline Integrity

### Finding WS3-001 — Signal(T) → Execution(T+1) is enforced (GREEN)

Evidence:
- `UnifiedBacktestEngine.run()` executes `pending_order` at `opens[idx]` on the NEXT bar after signal collection (`unified_engine.py:147-192`).
- Signal is collected at bar `idx` end (`unified_engine.py:230-258`), order is placed for `idx+1` open.
- `BacktestEngine.run_backtest()` (legacy) uses the same pattern: signal at `idx`, execution at `idx+1` open (`engine.py:461-505`).

Impact:
- Same-bar execution is impossible in both engines. This is the correct behavior for A-share research backtesting.

Risk Level: Info

Recommendation:
- Add a contract test proving that signal timestamp `T` produces execution at bar `T+1` open with at least one test data row.

Migration Cost: Low

Verification: Create test with known signal → verify trade timestamp is next bar's open date.

### Finding WS3-002 — Signal timestamp uses `pd.Timestamp.now()` causing signal/K-line date mismatch (P0)

Evidence:
- `UnifiedResearchPipeline.run()` line 133: `timestamp = pd.Timestamp.now()`.
- `_index_signals_by_date()` groups by signal date and only matches if K-line date == signal date (`unified_engine.py:288-300`).
- If system date is not in K-line range, zero signals are consumed.

Impact:
- Historical backtest results are non-deterministic — they depend on the system clock at pipeline run time.
- A backtest run on Monday can produce different results from the same pipeline run on Tuesday.

Risk Level: P0

Recommendation:
- (Covered in WS4) Generate as-of timestamps per historical bar instead of using `pd.Timestamp.now()`.

Migration Cost: Medium

Verification: Pipeline integration test with fixed data range and known system date outside the range must produce zero trades.

## 2. Bias Controls

### Finding WS3-003 — Survivorship bias is partially addressed but not enforced in the pipeline (P1)

Evidence:
- `baostock.py:fetch_stock_list()` supports `include_delisted=True` (default) — raw source provides delisted stocks (`baostock.py:281-314`).
- `stock_metadata_manager.py` tracks `delist_date` and has `is_delisted()` method (`stock_metadata_manager.py:244-260`).
- `data_aligner.py` truncates data to delist_date for delisted stocks (`data_aligner.py:47-53`).
- `scan_service.py` has `exclude_delisted: bool = False` (default includes delisted).
- `strategies/backtest.py` has an ad-hoc survivorship penalty but this is not in the main pipeline.

**However:**
- `UnifiedResearchPipeline.run()` does NOT check whether the input symbol is delisted or suspended.
- There is no survivorship bias flag in `BacktestResult`.
- The pipeline works with single symbols — survivorship bias is more relevant at the universe selection level.

Impact:
- If the research workflow uses a today's database snapshot (which only contains surviving stocks), backtests will overestimate performance because delisted stocks (which tend to underperform) are excluded.
- The building blocks exist (delist_date tracking, `include_delisted` flag) but are not wired into `UnifiedResearchPipeline`.

Risk Level: P1

Recommendation:
- Add a `survivorship_warning` to `BacktestResult.metadata` when the symbol's delist_date is within the data range.
- For universe-level research (scan service), verify that `exclude_delisted=False` is used.
- Add documentation that survivorship bias is the user's responsibility at the universe construction level.

Migration Cost: Low

Priority: Sprint 2

### Finding WS3-004 — Selection bias / future-known universe risk is not addressed (P2)

Evidence:
- `UnifiedResearchPipeline` and `UnifiedBacktestEngine` accept single symbols — they have no universe membership concept.
- `PortfolioEngine` accepts signals as-is — no universe roll date or index membership history check.
- No evidence of point-in-time index constituent lists being used.

Impact:
- If a user backtests a stock that was only recently listed, the backtest will use data from before the listing date, which is impossible for a live strategy.
- If a user backtests only stocks that exist today (surviving + recently listed), the sample will be biased toward recent IPOs.

Risk Level: P2

Recommendation:
- Add a `listing_date` check in the pipeline — warn if the data start date is before the listing date.
- Document that universe composition must be point-in-time for institutional research.

Migration Cost: Low

Priority: Sprint 3

### Finding WS3-005 — Data snooping controls: Walk-forward and overfitting detector exist (GREEN)

Evidence:
- `WalkForwardFactorPipeline` implements strict train/test splits with an embargo period (`walk_forward_pipeline.py:1-40`).
- `BacktestEngine.run_walk_forward()` supports embargo parameter (`engine.py:595-670`).
- `BacktestEngine.run_backtest()` runs Monte Carlo simulation and OverfittingDetector (`engine.py:527-600`).
- `FactorAnalyzer.check_lookahead_leakage()` uses future perturbation invariance (`analyzer.py:25-78`).
- `UnifiedBacktestEngine` does NOT have Monte Carlo or overfitting detection built-in.

Impact:
- The new `UnifiedBacktestEngine` is simpler but lacks the overfitting detection that `BacktestEngine` (legacy) has.
- Users migrating to the new engine lose Monte Carlo simulation and DSR calculation unless re-implemented externally.

Risk Level: P2

Recommendation:
- Add optional `MonteCarloSimulator` and `OverfittingDetector` integration to `UnifiedBacktestEngine`.
- Or provide a post-processing utility that takes `BacktestResult` and computes overfitting metrics.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS3-006 — Factor forward-return calculation has explicit lookahead guard (GREEN)

Evidence:
- `FactorAnalyzer._compute_forward_returns()` uses `shift(-holding_period)` which is inherently lookahead (`analyzer.py:148`).
- Method raises `ValueError` when `mode="live"` (`analyzer.py:154-158`).
- `compute_ic_ir()` also raises when `mode=AnalysisMode.LIVE` (`analyzer.py:232-237`).
- Future-date check against `pd.Timestamp.now()` at line 172 (`analyzer.py:172`).

Impact:
- Factor IC/IR computation is correctly gated — it can only be used for offline analysis, not live trading decisions.
- This is the correct design for a research platform.

Risk Level: Info

Recommendation:
- Add a contract test verifying `mode="live"` raises `ValueError`.

Migration Cost: Low

## 3. A-Share Market Rules

### Finding WS3-007 — Limit-up/down enforcement is present in both engines (GREEN)

Evidence:
- `UnifiedBacktestEngine._check_limit()` uses `get_board_type()` with board-specific limit ratios + `PRICE_TOLERANCE` (`unified_engine.py:321-341`).
- `UnifiedBacktestEngine._execute_buy()` and `_execute_sell()` call `_check_limit()` before execution (`unified_engine.py:376`, `unified_engine.py:471`).
- `UnifiedMatchingEngine.compute_limit_status_vectorized()` has a full vectorized implementation with:
  - Board type detection via `get_board_type()` (`unified_matching_engine.py:82-120`).
  - ST name detection (`unified_matching_engine.py:112-115`).
  - IPO special rules (main board day 1: ±44%/36%, sci_tech/gem: first 5 days no limit, beijing: day 1 no limit) (`unified_matching_engine.py:118-130`).
  - Tolerance-based boundary detection (`unified_matching_engine.py:132-138`).
- `limit_checker.py` provides standalone `check_limit_status()` with full board-type support and IPO rules.

Impact:
- Limit-up buy rejection and limit-down sell rejection are enforced in both single-symbol (unified_engine) and vectorized (matching_engine) paths.
- ST stocks, IPO special periods, and all board types are handled.

Risk Level: GREEN — adequate control

### Finding WS3-008 — Suspension (volume=0) rejection (GREEN in unified engine, WARNING in PortfolioEngine)

Evidence:
- `UnifiedBacktestEngine.run()`: `if vol <= 0: pending_order = None` — rejects suspension at execution (`unified_engine.py:155-157`).
- `UnifiedMatchingEngine.fill_buy()`: limit_rejected does not include `volume=0` — relies on caller.
- `PortfolioEngine.batch_open_positions()`: does NOT check volume=0 before calling `fill_buy()` (`portfolio_engine.py:163-201`).
- `PortfolioEngine.batch_close_positions()`: does NOT check volume=0 before calling `fill_sell()` (`portfolio_engine.py:209-246`).
- `PortfolioEngine.run()`: passes volumes as `shares` to matching, not as raw volume — the vol param is `shares_requested` not the bar's volume.

Impact:
- `UnifiedBacktestEngine` stops trading during suspension (correct).
- `PortfolioEngine` may execute trades during suspension days (incorrect).

Risk Level: P1 (PortfolioEngine)

Recommendation:
- Add volume=0 and suspension check to `PortfolioEngine.batch_open_positions()` and `batch_close_positions()` before calling matching engine.

Migration Cost: Low

Priority: Sprint 2

### Finding WS3-009 — T+1 sell restriction is enforced in all engines (GREEN)

Evidence:
- `UnifiedBacktestEngine._check_t1()` checks ordinal difference >= 1 and verifies next trading day (`unified_engine.py:300-315`).
- `UnifiedMatchingEngine.fill_sell()` computes `t1_violation_mask` per order with `_next_trading_day()` check (`unified_matching_engine.py:145-160`).
- `BacktestEngine._check_t1_constraint()` uses trade calendar ordinal index (`engine.py:225-246`).
- `PortfolioEngine` uses `UnifiedMatchingEngine.fill_sell()` which enforces T+1 internally.

Impact:
- T+1 constraint is enforced at the execution level in both single-symbol and vectorized paths.
- Sell orders on the same or next calendar day (before next trading day) are rejected.

Risk Level: GREEN — adequate control

### Finding WS3-010 — Commission, stamp duty, transfer fee, and slippage (GREEN)

Evidence:
- `cost_model.py`: single source of truth with date-aware stamp tax (pre/post 2023-08-28) (`cost_model.py:34-47`).
- `UnifiedBacktestEngine`: uses cost model constants directly (`unified_engine.py:17-22`, `unified_engine.py:345-355`).
- `UnifiedMatchingEngine.fill_sell()`: calculates stamp duty with date-aware rates via `get_stamp_tax_pct()` (`unified_matching_engine.py:170-175`).
- `UnifiedBacktestEngine._calc_slippage()`: nonlinear model using `trade_volume / avg_daily_volume ** 0.5` (`unified_engine.py:362-378`).
- `UnifiedMatchingEngine.compute_execution_prices()`: vectorized nonlinear slippage (`unified_matching_engine.py:38-49`).
- `cost_model.py` also has `CostConfig` dataclass supporting env var and YAML overrides.

Impact:
- Asymmetric costs (sell-side stamp duty), date-aware stamp rates, minimum commission, and volume-dependent slippage are consistently applied.
- No cost difference between engines for identical inputs.

Risk Level: GREEN — adequate control

### Finding WS3-011 — Lot-size rounding (GREEN)

Evidence:
- `UnifiedBacktestEngine._execute_buy()`: `shares = (shares_requested // lot_size) * lot_size` (`unified_engine.py:392`).
- `UnifiedMatchingEngine.fill_buy()`: vectorized lot-size rounding (`unified_matching_engine.py:82-85`).
- `market_rules.py`: per-board lot sizes (main/gem/beijing: 100, STAR: 200, ST: 100) (`market_rules.py:27-33`).
- `PortfolioEngine.batch_open_positions()`: `// 100 * 100` hardcoded (`portfolio_engine.py:173`).

Impact:
- Lot-size rounding is correct in all paths. `PortfolioEngine` hardcodes 100 instead of using `get_board_rule()` — minor inconsistency.

Risk Level: P2 (PortfolioEngine hardcoded lot size)

Recommendation:
- Change `PortfolioEngine.batch_open_positions()` to use `get_board_rule(symbol).lot_size` instead of hardcoded 100.

Migration Cost: Low

Priority: Sprint 3

### Finding WS3-012 — Price collar exists but is not integrated into execution engines (P2)

Evidence:
- `price_collar.py`: `validate_order_price()` and `get_allowable_price_range()` exist with board-specific collar percentages (`price_collar.py:1-30`).
- `market_rules.py`: `BoardRule.price_collar_pct` ranges from 1% (ST) to 5% (Beijing) (`market_rules.py:31`).
- **Neither `UnifiedBacktestEngine` nor `UnifiedMatchingEngine` calls `validate_order_price()`.**

Impact:
- Execution price is limited by limit up/down (which is correct) but NOT by the narrower price collar used in live exchange call auction/continuous trading.
- In practice, slippage-adjusted prices could theoretically exceed the collar if slippage pushes price beyond collar but within limit bounds.
- This is a realism gap for institutional-grade backtesting.

Risk Level: P2

Recommendation:
- Add price collar check after slippage calculation in `UnifiedBacktestEngine._execute_buy()` and `_execute_sell()`.
- Add collar check to `UnifiedMatchingEngine.compute_execution_prices()`.

Migration Cost: Low

Priority: Sprint 3

## 4. Corporate Actions

### Finding WS3-013 — Forward/backward adjustment factors computed from TDX gbbq data (GREEN)

Evidence:
- `DataAdjuster` computes qfq/hfq adjustment factors from local TDX gbbq (除权除息) data (`data_adjuster.py:35-220`).
- `DataAdjuster.apply_adjustment()` uses `pd.merge_asof` with factor column, supports `cutoff_date` parameter to prevent future dividend leakage (`data_adjuster.py:120-230`).
- `cutoff_date` parameter truncates factor application to prevent future ex-dividend events from leaking into historical prices.
- QFQ/HFQ methods are applied through `get_adjusted_data()` interface.

Impact:
- Adjustment factors are correctly computed and applied. The `cutoff_date` parameter is the key control against future dividend leakage.

Risk Level: GREEN — adequate control

### Finding WS3-014 — Data service returns adjusted data; no raw/unadjusted path in pipeline (P2)

Evidence:
- `DataService.fetch_for_brain()` calls `_load_data_with_fallback()` which defaults to adjusted data (`data_service.py:403-411`).
- The pipeline does not distinguish between adjusted and unadjusted price data.
- Analysis engines (LPPL, CZSC, Wyckoff, etc.) use adjusted close prices without awareness of the adjustment basis.

Impact:
- This is normal for research platforms (always use forward-adjusted data). But any strategy that trades based on price levels near ex-dividend dates could be affected by adjustment artifacts.
- QFQ adjustments can produce negative prices for very old data, which crashes `_check_limit()` ratio calculations.

Risk Level: P2

Recommendation:
- Document that the pipeline uses QFQ (forward-adjusted) data by default.
- Add a check for negative/zero prices after adjustment application.

Migration Cost: Low

Priority: Sprint 3

## 5. Engine Divergence

### Finding WS3-015 — `UnifiedBacktestEngine` and `BacktestEngine` (legacy) behavior divergence (P1)

Evidence:
- `BacktestEngine` (legacy): uses `result.py:BacktestResult` (richer: sharpe, drawdown, win_rate, etc. pre-computed).
- `UnifiedBacktestEngine`: uses local `BacktestResult` (raw data only: trades, equity_curve, daily_returns).
- `BacktestEngine` runs Monte Carlo and overfitting checks; `UnifiedBacktestEngine` does not.
- `BacktestEngine.roll_backtest()` and `run_walk_forward()` exist; `UnifiedBacktestEngine` has no multi-window support.
- `BacktestEngine` uses `UnifiedMatchingEngine` for execution; `UnifiedBacktestEngine` has inline execution.

Impact:
- Users told to migrate from `BacktestEngine` to `UnifiedBacktestEngine` lose:
  - Richer `BacktestResult` with pre-computed metrics
  - Built-in Monte Carlo and overfitting detection
  - Rolling/walk-forward support
- Results from the two engines are NOT directly comparable for the same input.

Risk Level: P1

Recommendation:
- Add `calculate_metrics()` to `UnifiedBacktestEngine`'s `BacktestResult`.
- Add optional Monte Carlo and overfitting detection to `UnifiedBacktestEngine`.
- Add a parity test that verifies both engines produce equivalent `TradeRecord` sequences for identical `TradingSignal` input.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS3-016 — `PortfolioEngine` vs `UnifiedBacktestEngine` behavior divergence (P2)

Evidence:
- `PortfolioEngine` uses `UnifiedMatchingEngine` for execution (vectorized, per symbol).
- `UnifiedBacktestEngine` has inline execution (sequential, single symbol).
- `PortfolioEngine` trades are `List[Dict[str, Any]]`, `UnifiedEngine` trades are `List[TradeRecord]`.
- `PortfolioEngine` lacks suspension/volume=0 check (Finding WS3-008).
- `PortfolioEngine` hardcodes lot size 100 (Finding WS3-011).

Impact:
- Multi-symbol backtest results (PortfolioEngine) are not directly comparable to single-symbol results (UnifiedBacktestEngine) due to different execution paths.

Risk Level: P2

Recommendation:
- Deprecate `PortfolioEngine` formally or align it with `UnifiedBacktestEngine`.

Migration Cost: Medium

Priority: Sprint 3

## 6. Control Summary

| Control | UnifiedEngine | MatchingEngine | PortfolioEngine | LegacyEngine | Status |
|---|---|---|---|---|---|
| Signal(T)→Execution(T+1) | ✅ | N/A | ✅ (via matching) | ✅ | GREEN |
| Same-bar prevention | ✅ | N/A | ✅ | ✅ | GREEN |
| Limit-up buy reject | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| Limit-down sell reject | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| IPO special rules | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| ST detection | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| Suspension (vol=0) | ✅ | ❌ (caller) | ❌ | ✅ | WARNING |
| T+1 sell restrict | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| Lot-size rounding | ✅ | ✅ | ⚠️ (hardcoded) | ✅ | WARNING |
| Commission | ✅ | ✅ | ✅ | ✅ | GREEN |
| Stamp duty (date-aware) | ✅ | ✅ | ✅ | ✅ | GREEN |
| Transfer fee | ⚠️ (ignores SH/SZ) | ⚠️ (ignores SH/SZ) | ⚠️ | ⚠️ | P2 |
| Slippage (nonlinear) | ✅ | ✅ | ✅ (via matching) | ✅ | GREEN |
| Price collar | ❌ | ❌ | ❌ | ❌ | MISSING |
| Forward-return guard | N/A | N/A | N/A | N/A | GREEN |
| Walk-forward embargo | N/A | N/A | N/A | ✅ | GREEN |
| MC/overfitting | ❌ | N/A | ❌ | ✅ | MISSING |
| Survivorship bias check | ❌ | N/A | ❌ | ⚠️ (partial) | MISSING |

## 7. Key Recommendations

1. **Sprint 2**: Add suspension check and lot-size fix to `PortfolioEngine`.
2. **Sprint 2**: Add parity test between `UnifiedBacktestEngine` and `BacktestEngine`.
3. **Sprint 2**: Add survivorship bias flag to `BacktestResult.metadata`.
4. **Sprint 3**: Add price collar validation to both engines.
5. **Sprint 3**: Add Monte Carlo/overfitting to `UnifiedBacktestEngine`.
6. **Sprint 3**: Add SH/SZ transfer fee distinction to `UnifiedBacktestEngine`.

## 8. Verification Checklist

- [x] Verified Signal(T)→Execution(T+1) in unified engine (line-by-line).
- [x] Verified same-bar execution is impossible (pending_order pattern).
- [x] Audit one-shot `pd.Timestamp.now()` issue (P0, covered in WS2/WS4).
- [x] Audit factor forward-return calculation (guarded with mode="live" check).
- [x] Audit walk-forward train/test boundaries (embargo parameter exists).
- [x] Audit survivorship bias (partial — data infrastructure supports it, pipeline does not enforce it).
- [x] Audit selection bias (no universe roll, listing date check missing).
- [x] Audit data snooping controls (Monte Carlo + overfitting in legacy engine only).
- [x] Audit corporate action handling (qfq/hfq with cutoff_date is correct).
- [x] Audit limit-up/down, T+1, suspension, lot size, cost, slippage (mostly GREEN).
- [x] Audited engine behavior divergence (Legacy vs Unified vs Portfolio).
- [x] Documented implemented controls vs missing controls.