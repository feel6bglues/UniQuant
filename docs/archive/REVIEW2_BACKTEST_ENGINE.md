# Review 2: OPTIMIZATION_BACKTEST_ENGINE.md (v1.0 corrected)

> Reviewed: 2026-05-31 | Second-pass review against source code truth
> Input: `OPTIMIZATION_BACKTEST_ENGINE.md` (corrected), `REVIEW_BACKTEST_ENGINE.md` (v1 review)

---

## 1. V1 Correction Verification

All 7 items from the v1 review were addressed:

| # | V1 Issue | Status | Notes |
|---|----------|--------|-------|
| 1 | T+1 framed as "bug" instead of robustness improvement | ✅ Fixed | Lines 30-34: "应定位为健壮性改进，而非 bug 修复" |
| 2 | T+1 "vectorized" code had CSV I/O per row | ✅ Fixed | New `_ensure_trading_days_cached` loads once, `_check_t1_trade_calendar` uses in-memory `np.searchsorted` |
| 3 | Duplicate `LimitCheckResult` instead of reusing `LimitStatus` | ✅ Fixed | Lines 250-251: "复用 LimitStatus", no new dataclass |
| 4 | Commission recalculation bug missing from problem list | ✅ Fixed | Line 17: Problem #6 added |
| 5 | ST detection gap missing from problem list | ✅ Fixed | Line 18: Problem #7 added |
| 6 | Test assertion self-contradictory | ✅ Fixed | Line 852: `assert result["is_sealed_up"][0] == False` |
| 7 | Should use `BoardRule.round_lot()` | ✅ Fixed | Line 164: `rule.round_lot(shares)` |

**Corrections applied correctly: 7/7**

---

## 2. T+1 Cache-First Approach — Detailed Analysis

### 2.1 Does `np.searchsorted` work correctly?

**Yes, with a caveat.** The code at lines 100-112:

```python
if b_ord not in self._trading_day_set:
    result[i] = True; continue       # reject non-trading day
if c_ord not in self._trading_day_set:
    result[i] = True; continue       # reject non-trading day

b_idx = int(np.searchsorted(ords, b_ord))
c_idx = int(np.searchsorted(ords, c_ord))
result[i] = (c_idx - b_idx) < 1
```

The guard at lines 100-105 ensures both dates are in `_trading_day_set` before `searchsorted` runs. Since `ords` is `sorted(ords_from_set)`, and both `b_ord` and `c_ord` are confirmed members of the set, `searchsorted` returns the **exact index** (not an insertion point). This is correct.

**Edge case — same-day buy+sell:**
- `b_idx == c_idx` → `0 < 1` → `True` (violation) ✅

**Edge case — Friday buy, Monday sell (weekend gap):**
- Friday is at index `k`, Monday at index `k+1` → `1 < 1` → `False` (allowed) ✅

**Edge case — pre-holiday buy, post-holiday sell:**
- If there are no trading days between them, they are adjacent in `ords` → same as weekend case ✅

**Edge case — 调休工作日 (Saturday/Sunday as trading day):**
- `2024-02-04` (Sunday) is in `_CN_SPECIAL_WORKDAYS` (trade_calendar_manager.py:43)
- If the trade calendar CSV includes it, it will be in `_trading_day_set` and `ords`
- `searchsorted` handles it correctly ✅

### 2.2 Is `_check_t1_trade_calendar` actually vectorized?

**No.** The method uses a Python `for i in range(n)` loop (line 91). This is NOT vectorized despite the method name.

However, the **performance characteristics are acceptable** because:
- The cache loads once: O(1) I/O after first call
- Each iteration: O(1) set lookup + O(log n) searchsorted
- Total: O(n log n) per batch, all in-memory

The v1 review's core complaint (CSV I/O per row) is fully resolved. The remaining Python loop is a minor stylistic issue, not a performance problem.

**Recommendation:** Rename to `_check_t1_cached` to avoid the "vectorized" misnomer.

### 2.3 Does it handle weekends/holidays correctly?

**Yes.** The `_ensure_trading_days_cached` method loads the **complete** trading calendar (2000-2030) from CSV into a set and sorted array. The calendar comes from `get_trade_calendar()` which reads from `trade_calendar_{year}.csv` files. These CSVs are generated from Baostock and contain only actual trading days.

- Weekends: Not in the CSV → not in `_trading_day_set` → rejected at line 100-104 ✅
- Holidays: Not in the CSV → same treatment ✅
- 调休工作日: In the CSV (if generated correctly) → in the set → handled ✅

**One concern:** The cache range is hardcoded to "2000-01-01" to "2030-12-31" (line 68). If the backtest uses dates outside this range, the cache won't cover them. This is unlikely in practice but should be documented.

---

## 3. Commission Recalculation Bug — Is the Description Accurate?

**Source at engine.py:182-188:**
```python
if total_cost > self.cash:
    shares = int((self.cash - commission) / exec_price)   # line 183
    shares = (shares // 100) * 100                         # line 184
    if shares <= 0:
        return None
    value = exec_price * shares                            # line 187
    total_cost = value + commission                        # line 188 — BUG
```

**The bug is correctly described.** `commission` on line 188 is still the value from line 179 (`max(value * rate, min_commission)`), computed with the **original** share count. After shares are reduced:

1. `value` decreases (fewer shares × same price)
2. `commission` should decrease (it's proportional to value, subject to minimum)
3. But `commission` is NOT recalculated → `total_cost` is overstated
4. This overstatement forces shares even lower than necessary

**Compare with unified_matching_engine.py:122-125** which correctly recalculates:
```python
values = exec_prices * shares_adj
commissions = np.maximum(values * self.commission_rate, self.min_commission)
transfer_fees = values * TRANSFER_FEE_PCT
```

**Additional sub-bug at line 183:** The formula `int((self.cash - commission) / exec_price)` uses the OLD commission. If commission were recalculated, this formula would need to solve for `shares` in:
```
cash >= exec_price * shares + max(exec_price * shares * rate, min_commission)
```
This is a chicken-and-egg problem (commission depends on shares, shares depend on commission). The unified_matching_engine solves it by computing `cash_available - commissions - transfer_fees` with the **original** commissions, then recalculating after adjustment. This is an approximation but better than engine.py's approach.

**Severity: 🔴 High** — causes systematic over-reduction of shares when cash-constrained, affecting backtest accuracy.

---

## 4. `round_lot()` Usage — Does `BoardRule` Have This Method?

**Yes.** `market_rules.py:20-21`:
```python
def round_lot(self, shares: int) -> int:
    return (shares // self.lot_size) * self.lot_size
```

The method exists, is public, and works correctly:
- `BoardRule(lot_size=100).round_lot(150)` → `100` ✅
- `BoardRule(lot_size=200).round_lot(250)` → `200` ✅
- `BoardRule(lot_size=200).round_lot(150)` → `0` ✅

The document correctly uses `rule.round_lot(shares)` at line 164. The test at lines 760-773 correctly validates the behavior.

**Note:** The fallback `(shares // 100) * 100` at line 164 handles the case where `get_board_rule()` fails (e.g., unknown symbol format). This is defensive and correct.

---

## 5. LimitStatus Integration — Does It Work?

**Yes.** `limit_checker.py` defines:

```python
@dataclass
class LimitStatus:
    is_limit_up: bool
    is_limit_down: bool
    can_buy: bool          # ← exists at line 20
    can_sell: bool         # ← exists at line 21
    board_type: str
    up_limit_price: float
    down_limit_price: float
    price_ratio: float
```

The document's proposed `_check_limit_constraint` (lines 253-292) returns `LimitStatus` and mutates `can_buy`/`can_sell` for sealed boards. This works because:

1. `check_limit_status()` at line 272 returns a fresh `LimitStatus`
2. The function sets `can_buy = not is_limit_up` (limit_checker.py:123)
3. The seal detection overrides `can_buy = False` only when sealed (line 280)
4. The caller checks `limit_status.can_buy` instead of `limit_status.is_limit_up`

**Design concern:** The mutation pattern (modifying a returned object's fields) is a side-effect pattern. A cleaner approach would be to return a new `LimitStatus` with the overridden values. But functionally, this works correctly.

**Compatibility check:** The current engine.py:151-155 uses:
```python
if action == "BUY" and limit_status.is_limit_up:
    return False
```
The proposed change would use `limit_status.can_buy` instead. This is a behavioral change: the current code always blocks limit-up buys; the proposed code blocks only sealed limit-up buys. This is intentional (炸板 should allow buying) but should be clearly documented as a **behavioral change**, not just a refactor.

---

## 6. ST Detection Gap — Is This Really a Bug?

**Yes, confirmed.** `market_rules.py:detect_board()` at lines 34-48:

```python
def detect_board(symbol: str) -> BoardType:
    upper = symbol.upper()
    if upper.endswith(".BJ"):
        return BoardType.BEIJING
    if upper.endswith(".SH"):
        code = upper.replace(".SH", "")
        if code.startswith(("688", "689")):
            return BoardType.STAR
        return BoardType.MAIN_SH
    if upper.endswith(".SZ"):
        code = upper.replace(".SZ", "")
        if code.startswith(("300", "301")):
            return BoardType.GEM
        return BoardType.MAIN_SZ
    raise ValueError(...)
```

This function **never returns `BoardType.ST`** despite `BOARD_RULES` having an ST entry at line 30.

Meanwhile, `limit_checker.py:get_board_type()` at line 28 accepts an optional `name` parameter and checks for ST prefixes:
```python
if name:
    name_upper = name.upper()
    for st_prefix in MarketConstants.BOARD_PREFIX["st"]:
        if name_upper.startswith(st_prefix):
            return "st"
```

**Impact:**
- `market_rules.py` ST stocks get `lot_size=100` (happens to be correct) but `price_limit_pct=0.10` (wrong, should be 0.05)
- `limit_checker.py` ST stocks get correct 5% limit only when `name` is passed
- The `unified_matching_engine.py` uses `get_board_type()` from limit_checker, which **does** handle ST when name is available
- The `engine.py` uses `check_limit_status()` which delegates to `get_board_type()` with optional name

**The gap is real** but partially mitigated by `limit_checker.py`'s separate ST detection path. The inconsistency between `market_rules.detect_board` (no ST) and `limit_checker.get_board_type` (has ST with name) is the actual bug.

**Fix:** Add optional `name` parameter to `detect_board()` and check for ST prefixes, or document that ST detection requires the name parameter.

---

## 7. New Issues Introduced by Corrections

### 7.1 🟡 Behavioral change in limit check not clearly documented

The proposed `_check_limit_constraint` (§2.3) changes the semantics:
- **Before:** All limit-up buys are blocked
- **After:** Only sealed limit-up buys are blocked; 炸板 buys are allowed

This is a **feature change**, not a bug fix. It should be flagged as opt-in behavior, not silently replacing the current logic.

### 7.2 🟡 Seal detection threshold edge case

At line 276:
```python
seal_threshold = avg_daily_volume * 0.01 if avg_daily_volume > 0 else 0
is_sealed = volume <= seal_threshold and seal_threshold > 0
```

When `avg_daily_volume == 0`: `seal_threshold = 0`, `seal_threshold > 0` is False → `is_sealed = False`. This is correct (conservative: don't seal when data is missing).

When `avg_daily_volume > 0` but `volume == 0`: `is_sealed = True`. This is correct (zero volume at limit price = sealed).

**No bug here**, but the test suite should explicitly test the `volume == 0` case.

### 7.3 🟡 `_check_t1_trade_calendar` method name misleading

The method uses a Python `for` loop (line 91). Calling it "trade_calendar" based is accurate, but the v1 review flagged `_check_t1_vectorized` as misleading. The corrected version avoids "vectorized" in the name, but the method signature comment at line 79 says "基于缓存的交易日历计算 T+1" which is accurate.

**Minor issue only.** The caching is the real fix; the loop is acceptable.

### 7.4 🟢 Transfer fee in FillResult — clean addition

The proposed addition of `transfer_fees` field to `FillResult` (§2.5) is clean and backward-compatible if given a default value. The `portfolio_engine.py` fix at line 182 to subtract transfer fees from `net_value` is correct.

However, `portfolio_engine.py:134` (buy path) also misses transfer fees:
```python
cost = float(fill.exec_prices[i] * fill.executed_shares[i] + fill.commissions[i])
# Missing: + fill.transfer_fees[i]
```
This causes `self.cash` to be **over-deducted** on buys (transfer fees are included in `total_costs` by the matching engine but not subtracted from cash by portfolio_engine). The document's §2.5 only addresses the sell path (`batch_close_positions` line 182) but not this buy path. Both need fixing.

---

## 8. Comparison with engine.py's Existing T+1 Implementation

`engine.py:116-141` already has a working T+1 check:

```python
def _check_t1_constraint(self, buy_date, current_date) -> bool:
    if buy_date is None:
        return True
    if not self.trade_calendar.is_trading_day(current_date):
        return False
    trading_days = self.trade_calendar.get_trade_calendar(
        start_date=buy_date.strftime("%Y-%m-%d"),
        end_date=current_date.strftime("%Y-%m-%d")
    )
    trade_dates = trading_days['trade_date'].values
    buy_idx = np.where(trade_dates == pd.Timestamp(buy_date))[0]
    current_idx = np.where(trade_dates == pd.Timestamp(current_date))[0]
    return bool(current_idx[0] - buy_idx[0] >= 1)
```

**This implementation has the same CSV I/O problem** (reads calendar per call) but is called only once per sell (not per bar per symbol), so it's acceptable for `engine.py`'s single-stock backtest.

The document's cache-first approach for `unified_matching_engine.py` is the right solution for batch operations. The two implementations should be documented as **complementary** (scalar vs batch) rather than one replacing the other.

---

## 9. Final Score

| Category | V1 Score | V2 Score | Change | Notes |
|----------|----------|----------|--------|-------|
| V1 corrections applied | N/A | 10/10 | — | All 7 items fixed |
| Problem identification | 7/10 | 8/10 | +1 | Commission bug and ST gap now included |
| Code accuracy | 5/10 | 8/10 | +3 | T+1 cache approach is correct; searchsorted verified |
| Line numbers | 9/10 | 9/10 | 0 | Unchanged |
| Omissions | 4/10 | 7/10 | +3 | Most gaps filled; portfolio_engine buy-side transfer fee still missed |
| Compilation feasibility | 6/10 | 8/10 | +2 | Cache-first code would compile and run |
| Trading domain accuracy | 7/10 | 8/10 | +1 | Seal detection is a reasonable heuristic |
| Behavioral clarity | N/A | 7/10 | — | Limit check behavioral change needs documentation |

**Overall: 8 / 10**

The corrected document is a significant improvement. The T+1 cache-first approach is technically sound, the commission bug and ST detection gap are correctly identified, and the `LimitStatus` reuse eliminates code duplication. The remaining issues are minor (method naming, behavioral documentation, one missed transfer fee location in portfolio_engine buy path).

---

## 10. Recommended Next Steps

| Priority | Action | Effort |
|----------|--------|--------|
| P0 | Implement lot sizing fix (`round_lot()`) | 30 min |
| P0 | Add `transfer_fees` field to `FillResult` | 30 min |
| P0 | Fix engine.py commission recalculation (lines 182-188) | 15 min |
| P1 | Implement T+1 cache-first approach in unified_matching_engine | 2 hours |
| P1 | Fix `market_rules.detect_board()` ST detection gap | 30 min |
| P2 | Add seal detection to limit check (opt-in flag) | 1 day |
| P2 | Implement StopLossManager | 3 days |
| P3 | Add transfer fee to portfolio_engine buy path (line 134) | 5 min |

---

*Review generated: 2026-05-31 | Based on direct source code analysis of 8 files*
