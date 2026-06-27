# Review: OPTIMIZATION_BACKTEST_ENGINE.md

> Reviewed: 2026-05-31 | Reviewer: automated code analysis against source truth

---

## 1. Summary

**Score: 6.5 / 10**

The document identifies some genuine issues but is **overly alarmist** about others, contains **code that would not work in critical paths**, and **misses several real bugs** in the source. It reads like an LLM generated it from a high-level understanding of the codebase without running or testing the proposed changes.

| Category | Grade | Reason |
|----------|-------|--------|
| Problem identification | 7/10 | Lot sizing problem is real; T+1 and limit-check problems are overstated |
| Code accuracy | 5/10 | Proposed T+1 "vectorized" code is actually a Python loop with CSV I/O per row |
| Line numbers | 9/10 | Minor off-by-few errors (within ~3 lines) |
| Omissions | 4/10 | Misses real `engine.py` commission recalculation bug, ST detection gap |
| Compilation feasibility | 6/10 | Most code compiles, but T+1 fix has severe performance flaws |
| Trading domain accuracy | 7/10 | Seal detection heuristic is naive for real A-share trading |

---

## 2. Verified Claims (What the Document Got Right)

### 2.1 Hardcoded lot size — ✅ CORRECT, critical bug

**Claim:** All three engines hardcode `// 100 * 100`, but 科创板 uses 200 shares.

**Source evidence:**
- `engine.py:184`: `shares = (shares // 100) * 100`
- `unified_matching_engine.py:117`: `... // 100 * 100`
- `portfolio_engine.py:116`: `... // 100 * 100`
- `market_rules.py:28`: `BoardType.STAR: BoardRule(lot_size=200, ...)`

**Verdict:** 100% correct. This is a real bug affecting all 科创板 stocks (688xxx, 689xxx).

### 2.2 Transfer fee missing from FillResult — ✅ CORRECT

**Claim:** `FillResult` lacks independent `transfer_fees` field.

**Source evidence:**
- `unified_matching_engine.py:19-29`: `FillResult` has no `transfer_fees` field.
- `unified_matching_engine.py:111`: transfer fees are **calculated** as `values * TRANSFER_FEE_PCT` but never stored.
- `unified_matching_engine.py:179`: Same in `fill_sell`.
- `portfolio_engine.py:182`: `net_value` calculation omits transfer fees entirely.
- `cost_model.py:30`: `TRANSFER_FEE_PCT = 0.00001` is correctly defined.

**Verdict:** Correct. Transfer fees are calculated then discarded. This causes a systematic under-estimation of costs in `portfolio_engine.py`.

### 2.3 No stop loss in backtest engine — ✅ CORRECT

**Claim:** `engine.py` has no stop loss protection.

**Source evidence:** Entire `engine.py` lacks any stop loss logic. Only `sizer.py:130-138` implements CZSC geometry stop calculation, but this is not wired into the backtest engine.

**Verdict:** Correct, though the proposed fix has issues (see §4.4).

### 2.4 Line numbers — ✅ MOSTLY ACCURATE

| Doc claims | Actual | Error |
|-----------|--------|-------|
| `engine.py:184` | `engine.py:184` | Exact ✓ |
| `engine.py:143-154` | `engine.py:143-156` | Off by 2 lines, minor |
| `unified_matching_engine.py:155-168` | `unified_matching_engine.py:158-171` | Off by 3 lines |
| `unified_matching_engine.py:115-117` | `unified_matching_engine.py:115-119` | Minor |
| `unified_matching_engine.py:111` | `unified_matching_engine.py:111` | Exact ✓ |
| `unified_matching_engine.py:179` | `unified_matching_engine.py:179` | Exact ✓ |
| `portfolio_engine.py:116` | `portfolio_engine.py:116` | Exact ✓ |
| `portfolio_engine.py:182` | `portfolio_engine.py:182` | Exact ✓ |
| `cost_model.py:30` | `cost_model.py:30` | Exact ✓ |

---

## 3. Errors Found

### 3.1 Problem 1 (T+1): The "bug" is overblown — the current code actually works for the weekend case described 🔴

**Document claims:**
> 在遇到周末+节假日组合时会误判（例如周五买入，下周一卖出，日历日差=3，应为1个交易日）

**Verification against `unified_matching_engine.py:158-171`:**

```python
buy_ord = np.array([pd.Timestamp(b).toordinal() ...])
cur_ord = np.array([pd.Timestamp(t).toordinal() ...])
t1_violation = (cur_ord - buy_ord < 1) & (buy_ord > 0)
```

Friday→Monday: `buy_ord` = Friday ordinal, `cur_ord` = Monday ordinal. Difference = 3. `3 < 1` → **False** (not a violation). Then the loop checks `is_trading_day()` on both dates — both pass. Result: sell is **allowed**.

**This is CORRECT for T+1.** The code accidentally works here because the `< 1` check is equivalent to a "same calendar day" check, and since you can never trade on consecutive calendar days in A-shares (no Saturday/Sunday trading), the calendar-day check happens to produce the right answer. The code is fragile, not buggy.

**Real risk:** The check would break if there were ever Saturday trading (e.g., 调休工作日 `_CN_SPECIAL_WORKDAYS`). The `is_trading_day` guard in the loop prevents most failures, but the approach is still fragile.

**Correction:** The document should frame this as a **robustness improvement** rather than a **bug fix**.

### 3.2 Document Problem 3: Limit check "only returns bool" — misleading 🔴

**Document claims:**
> `engine.py:143-154` 的 `_check_limit_constraint` 只返回 `bool`

**This is true** for the specific function signature. But the document ignores that `limit_checker.py:15-25` already defines a rich `LimitStatus` dataclass with 8 fields (`is_limit_up`, `is_limit_down`, `can_buy`, `can_sell`, `board_type`, `up_limit_price`, `down_limit_price`, `price_ratio`). The caller in `engine.py` just discards this information.

The document proposes a new `LimitCheckResult` dataclass that largely duplicates the existing `LimitStatus` from `limit_checker.py`. This is code duplication.

**Correction:** Instead of creating `LimitCheckResult`, the fix should refactor `_check_limit_constraint` to return the existing `LimitStatus` object directly, adding seal-detection logic to `LimitStatus` or as a separate utility.

### 3.3 Proposed T+1 "vectorized" code is NOT vectorized — it's a for loop with CSV I/O 🔴

**Document:**

```python
def _check_t1_vectorized(self, buy_dates, current_dates) -> np.ndarray:
    t1_violation = np.ones(n, dtype=bool)
    for i in range(n):  # <-- Python for loop!
        ...
        trading_days = self.trade_calendar.get_trade_calendar(
            start_date=b_ts.strftime("%Y-%m-%d"),
            end_date=c_ts.strftime("%Y-%m-%d"),
        )
        ...
```

**Problems:**
1. The method is named `_check_t1_vectorized` but uses a Python `for` loop — the name is misleading.
2. **Critically:** `self.trade_calendar.get_trade_calendar()` reads CSV files from disk (see `trade_calendar_manager.py:126-151`). Calling this **once per bar per symbol** would be catastrophically slow — O(1000×) slower than the current implementation.
3. The performance table in §4.1 claims 5ms for 1000 symbols, but the proposed code would take **seconds** due to repeated CSV I/O.

### 3.4 Document's T+1 fix and the existing `engine.py` are the same approach 🟡

The document proposes fixing `unified_matching_engine.py` T+1 using trade calendar queries. But `engine.py:116-141` **already implements the exact same pattern**:

```python
def _check_t1_constraint(self, buy_date, current_date) -> bool:
    trading_days = self.trade_calendar.get_trade_calendar(
        start_date=buy_date.strftime("%Y-%m-%d"),
        end_date=current_date.strftime("%Y-%m-%d")
    )
    trade_dates = trading_days['trade_date'].values
    buy_idx = np.where(trade_dates == pd.Timestamp(buy_date))[0]
    current_idx = np.where(trade_dates == pd.Timestamp(current_date))[0]
    return bool(current_idx[0] - buy_idx[0] >= 1)
```

The document doesn't credit this existing implementation and presents the approach as novel.

### 3.5 Document says `portfolio_engine.py:182` "未将过户费从 commission 中分离" — misleading 🟡

The actual code at line 182 is:

```python
net_value = float(fill.exec_prices[i] * fill.executed_shares[i] - fill.commissions[i] - fill.stamp_duties[i])
```

Transfer fees are **not subtracted at all** (not conflated with commission). The document's phrasing implies they're incorrectly grouped into commission, when in fact they're simply **missing** from the calculation entirely. The fee structure for `fill_buy` includes it in total costs, but `batch_close_positions` (a sell operation) omits transfer fees from the net value calculation.

### 3.6 Test: `test_no_volume_data_skip_seal_check` has incorrect assertion 🟡

```python
assert "is_sealed_up" not in result or result.get("is_sealed_up", np.array([False]))[0] == False
```

When `volumes` and `avg_daily_volumes` are not passed (both `None`), the proposed `compute_limit_status_vectorized` code still returns `is_sealed_up` and `is_sealed_down` in the dict (initialized to `np.zeros(n, dtype=bool)`), because the dict is built unconditionally. So `is_sealed_up` WILL be in the result (as all `False`), and the `"is_sealed_up" not in result` branch would fail. The assertion is self-contradictory.

---

## 4. Omissions (Bugs the Document Missed)

### 4.1 🔴 `engine.py:182-184` — Commission not recalculated after share adjustment

```python
if total_cost > self.cash:
    shares = int((self.cash - commission) / exec_price)   # line 183
    shares = (shares // 100) * 100                         # line 184
    if shares <= 0:
        return None
    value = exec_price * shares                            # line 187
    total_cost = value + commission                        # line 188 — BUG
```

`commission` on line 188 is still the original value from line 179 (`max(value_original * rate, min_commission)`). After shares are reduced, `commission` should be recalculated with the new `value`. This causes the transaction cost to be systematically **overstated** when cash constraints trigger share reduction.

Compare with `unified_matching_engine.py:122-125` which **does** recalculate:
```python
values = exec_prices * shares_adj
commissions = np.maximum(values * self.commission_rate, self.min_commission)
```

### 4.2 🔴 `engine.py:191` — `position_cost` averaging uses un-updated `position`

```python
avg_cost = (self.position_cost * self.position + value) / (self.position + shares)
self.position += shares
self.position_cost = avg_cost
```

This is actually correct — `self.position` is used before incrementing. No bug here. (Verified.)

### 4.3 🟡 `market_rules.py:34-48` — `detect_board` cannot detect ST stocks

```python
def detect_board(symbol: str) -> BoardType:
    # Only checks exchange suffixes and code prefixes
    # NO ST detection despite BoardType.ST existing in BOARD_RULES
```

`BoardType.ST` is defined and mapped to `lot_size=100`, `price_limit_pct=0.05` at line 30, but `detect_board` never returns it. This means:
- ST stocks like `*ST康美` (600518.SH) are classified as `MAIN_SH` (10% limit instead of 5%)
- The `lot_size` fix doesn't help ST stocks since they happen to use 100 shares

Note: `limit_checker.py:get_board_type` does handle ST via the optional `name` parameter, but `market_rules.py:detect_board` does not. This is an inconsistency in the codebase.

### 4.4 🟡 `BoardRule.round_lot()` exists but is never used

`market_rules.py:20-21`:
```python
def round_lot(self, shares: int) -> int:
    return (shares // self.lot_size) * self.lot_size
```

This is the correct way to do lot rounding. The document's proposed fix uses `lot_size` directly but doesn't leverage `round_lot()`. The proposed fix should use `rule.round_lot(shares)` instead of `(shares // lot_size) * lot_size`.

### 4.5 🟡 Proposed stop loss integration changes `run_backtest` signature

The proposed integration (document §2.4) adds `stop_loss_config: Optional[StopLossConfig]` to `run_backtest(...)`. The `@handle_errors` decorator wraps this method, and changing the signature of a decorated function with `default_return=BacktestResult()` could cause subtle issues. The document doesn't address this.

### 4.6 🟡 `BacktestEngine` has a `_check_t1_constraint` that already works correctly

`engine.py:116-141` already implements T+1 check using `trade_calendar.get_trade_calendar()`. The document focuses exclusively on `unified_matching_engine.py` and ignores that `engine.py` has a working implementation. The proposed fix for `unified_matching_engine.py` should align with `engine.py`'s approach.

---

## 5. Practical Trading Insights

### 5.1 Seal detection heuristic is naive

The proposed seal detection uses `volume < avg_daily_volume * 0.01`. In real A-share trading:

- A stock that gaps up at open and stays at 涨停 with normal volume (volume > 1% of avg) may still be **unbuyable** because the order book has no sell orders at the limit price. The heuristic would say "broken board" (false negative).
- A stock at 涨停 with volume < 1% of avg might still be buyable if there's a hidden order queue. The heuristic would say "sealed" (false positive).
- **Real seal detection requires order book data** (level-2), which the backtest engine doesn't have. Any volume-based heuristic should be documented as a rough approximation.

### 5.2 T+1 edge case: 调休工作日

China has special workdays (调休) where Saturday/Sunday are trading days. The trade calendar handles these via `_CN_SPECIAL_WORKDAYS` (line 42-52 in `trade_calendar_manager.py`). Example: `2024-02-04` (Sunday) is a trading day. The current `toordinal()` approach would correctly treat this as a violation for same-day, but the proposed fix using `is_trading_day` + trading index is more robust.

### 5.3 Minimum commission trap

A-share minimum commission is ¥5 per trade. Both `engine.py:74` and `unified_matching_engine.py:110` handle this correctly. But the document's proposed `StopLossManager` integration calls `execute_sell` for small positions where the commission might be artificially ¥5 even for tiny sells, producing unrealistic backtest results for position sizing below ~¥16,667 (¥5 / 0.03%).

### 5.4 Transfer fee reality check

`TRANSFER_FEE_PCT = 0.00001` (万0.1) means on a ¥10,000 trade, the fee is ¥0.10 — essentially noise. For most backtests, this is within slippage noise. However, for high-frequency strategies (thousands of trades), it compounds. The document correctly identifies the accounting issue even if the practical impact is small.

---

## 6. Code Quality Review of Proposed Fixes

### 6.1 T+1 fix (`_check_t1_vectorized`) — DO NOT MERGE AS WRITTEN

| Issue | Severity | Details |
|-------|----------|---------|
| Misleading name | 🟡 | Called "vectorized" but uses Python `for` loop |
| CSV I/O per row | 🔴 | `get_trade_calendar()` reads disk, called in loop = O(n) disk reads |
| Monolithic | 🟡 | 40 lines for a simple logic check; should be ~15 lines |

**Recommendation:** The documented cache optimization (pre-computing `_trading_days_set`) is not optional — it's **mandatory** for this approach. Without it, the proposed code is orders of magnitude slower than the current implementation.

### 6.2 Lot sizing fix — GOOD, MERGE AS-IS

Simple, correct, well-structured. Use `BoardRule.round_lot()` instead of `// lot_size * lot_size` for consistency.

### 6.3 Limit check enhancement — MEDIUM QUALITY

| Issue | Details |
|-------|---------|
| Duplicates `LimitStatus` | Creates new `LimitCheckResult` instead of extending or returning `LimitStatus` |
| Missing import | `@dataclass` needs `from dataclasses import dataclass` in `engine.py` (not shown in diff) |

**Recommendation:** Return the existing `LimitStatus` directly from `limit_checker.py`, adding `can_buy`/`can_sell` fields if needed, rather than creating a parallel dataclass.

### 6.4 StopLossManager — GOOD, BUT LARGE

The `StopLossManager` is well-architected with:
- Clean separation of config, state, and logic
- Proper `dataclass` usage
- Good logging
- Testable design

Issues:
- Duplicates stop-loss calculation logic from `sizer.py:130-138` (CZSC geometry)
- Does not import or reference `PositionSizer` despite claiming to integrate with it
- The `run_backtest` integration modifies the method signature, potentially breaking the `@handle_errors` decorator behavior

### 6.5 Transfer fee in FillResult — GOOD, MERGE

Simple field addition, backward-compatible if defaulted. The document's proposed code correctly adds the field. No issues.

---

## 7. Recommendation

### Phase ordering (revised):

| Priority | Task | Risk | Effort | Suggested order |
|----------|------|------|--------|-----------------|
| 1 | **Lot sizing fix** (round via `BoardRule.round_lot()`) | 🟢 Low | 30 min | Phase 1 |
| 2 | **Transfer fee in FillResult** | 🟢 Low | 30 min | Phase 1 |
| 3 | **engine.py commission recalculation bug** (§4.1 above) | 🟢 Low | 15 min | Phase 1 |
| 4 | **T+1 robustness** with caching | 🟡 Medium | 2 days | Phase 2 |
| 5 | **Stop loss integration** | 🟡 Medium | 3 days | Phase 3 |
| 6 | **ST detection in `market_rules.detect_board`** | 🟢 Low | 30 min | Phase 1 |
| 7 | **Seal detection heuristic** | 🟡 Medium | 1 day | Phase 4 |

### Key changes to the document before proceeding:

1. **Rewrite T+1 section**: Remove "bug" framing; frame as robustness improvement. Delete the `_check_t1_vectorized` code and replace with a cache-first approach. Use `engine.py`'s existing implementation as the reference pattern.

2. **Merge `LimitCheckResult` with `LimitStatus`**: Don't create a parallel dataclass. Extend the existing one.

3. **Add commission recalculation bug** to problem list (as a 🔴 issue).

4. **Add `ST detection` gap** to problem list.

5. **Fix test assertion** in `test_no_volume_data_skip_seal_check`.

6. **Add performance benchmark requirement** for T+1 fix before merging.

### Overall Go/No-Go:

**Proceed with caution (conditional YES).** Phases 1 and priority items 3 and 6 should be done first (low risk, high value). Phase 2 (T+1) needs a complete rewrite of the proposed code. Phase 4 (stop loss) needs de-duplication with `sizer.py` and signature compatibility verification.

---

*Review generated: 2026-05-31 | Based on direct source code evidence*
