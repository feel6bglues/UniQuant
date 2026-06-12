# Stage 6 - Backtest And Matching

Generated: 2026-06-09

Scope: `hands/backtest` execution realism, A-share matching constraints, signal-to-order timing, cost model, and single-symbol versus portfolio behavior. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0-5 artifacts and Stage 6 playbook requirements.
2. Analyze `UnifiedBacktestEngine` as the current typed single-symbol engine.
3. Analyze `UnifiedMatchingEngine` as the vectorized fill engine used by deprecated/portfolio paths.
4. Check A-share constraints: T+1, limit-up/down, suspension, cash, costs, slippage, lot size.
5. Compare single-symbol and portfolio paths.
6. Identify backtest bias risks and concrete improvements.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` through `05_signal_system.md` | Prior-stage context and signal handoff. |
| `src/uniquant/hands/backtest/unified_engine.py` | Current typed `TradingSignal` single-symbol backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized buy/sell fill engine. |
| `src/uniquant/hands/backtest/portfolio_engine.py` | Deprecated portfolio engine using `UnifiedMatchingEngine`. |
| `src/uniquant/hands/backtest/engine.py` | Deprecated old engine using `UnifiedMatchingEngine`. |
| `src/uniquant/shared/cost_model.py` | Canonical cost constants and date-aware stamp duty. |
| `src/uniquant/shared/market_rules.py` | Board detection, lot size, board limit metadata. |
| `src/uniquant/shared/limit_checker.py` | Limit-up/down status and IPO/ST handling helper. |
| `tests/test_unified_matching.py` | Unified engine defense tests. |
| `tests/test_t1_constraint_boundary.py` | Vectorized matching T+1 boundary tests. |

## 3. 回测流程图

Current single-symbol execution flow:

```text
List[TradingSignal] + stock_df
  -> _prepare_dataframe()
       require date/open/high/low/close/volume
       fill pre_close if absent
       fill avg_daily_volume if absent
  -> _index_signals_by_date()
       timestamp date -> list of signals
  -> for each K-line bar:
       skip non-trading day for execution
       execute previous pending order at today's open
          reject suspension volume=0
          BUY: limit-up check, slippage, lot rounding, cash check, costs
          SELL: T+1 check, limit-down check, slippage, costs, pnl
       update equity using close
       read today's signals
       create one pending order for next bar
  -> BacktestResult(trades, equity_curve, daily_returns, final_cash)
```

Evidence:

- Required fields and derived fields: `src/uniquant/hands/backtest/unified_engine.py:272-286`.
- Signal date index: `unified_engine.py:288-300`.
- Bar loop order: `unified_engine.py:157-258`.
- T-day signal, next-bar open execution: `unified_engine.py:173-230`, `241-258`.

## 4. 撮合规则表

| Rule | `UnifiedBacktestEngine` | `UnifiedMatchingEngine` |
|---|---|---|
| Input | `List[TradingSignal]` and one OHLCV DataFrame. | Arrays of prices, shares, cash/position, symbols, timestamps. |
| Execution time | Signal date D creates pending order; order executes next trading bar open. | Caller supplies execution arrays directly; no signal-delay semantics inside the fill method. |
| T+1 | Checked before sell when `buy_date` exists. | Checked in `fill_sell()` against `buy_dates` and `timestamps`. |
| Limit-up/down | `_check_limit()` rejects BUY at limit-up and SELL at limit-down. | `compute_limit_status_vectorized()` rejects limit-up buys and limit-down sells. |
| Suspension | Rejects pending order if execution bar `volume <= 0`. | No explicit rejected mask for `volume <= 0`; zero volume only reduces impact in slippage calculation. |
| Cash | BUY reduces requested shares if cash is insufficient; final cost cannot exceed cash. | `fill_buy()` adjusts shares for cash shortfall. |
| Lot size | BUY rounded down by board lot size. | BUY rounded by board lot size in cash-shortfall branch; requested shares are not always normalized when cash is sufficient. |
| Sell size | Sell capped by current position. | `shares_clamped = min(requested, positions_held)`. |
| Costs | Commission, transfer fee both sides; stamp duty sell side only. | Same categories; stamp duty sell side only. |
| Slippage | Buy price higher, sell price lower; impact capped. | Same direction with vectorized impact. |

Evidence:

- Single engine T+1 and limits: `unified_engine.py:204-230`, `335-362`.
- Single engine cash/lot/cost: `unified_engine.py:445-487`, `527-551`.
- Matching limits: `unified_matching_engine.py:79-138`.
- Matching buy fill: `unified_matching_engine.py:140-197`.
- Matching sell fill and T+1: `unified_matching_engine.py:199-263`.

## 5. A 股交易约束校验表

| Constraint | Current status | Evidence | Notes |
|---|---|---|---|
| T 日信号、T+1 open 成交 | Implemented in `UnifiedBacktestEngine`. | `unified_engine.py:173-230`, `241-258` | Signal timestamp must match a bar date; Stage 5 found pipeline currently uses `now()`. |
| T+1 sell restriction | Implemented in both engines. | `unified_engine.py:306-320`, `unified_matching_engine.py:220-235` | Matching tests cover same-day, weekend, holiday, empty calendar boundaries. |
| 涨停不买 | Implemented. | `unified_engine.py:358-359`, `unified_matching_engine.py:156-157` | Uses board ratios from `MarketConstants.LIMIT_RATIO`. |
| 跌停不卖 | Implemented. | `unified_engine.py:360-361`, `unified_matching_engine.py:217-218` | Single engine checks execution open against `pre_close`. |
| 停牌 volume=0 | Implemented in single engine. | `unified_engine.py:180-183` | Vectorized matching does not explicitly reject zero-volume fills. |
| 印花税只在卖出侧 | Implemented. | `unified_engine.py:482`, `529`; `unified_matching_engine.py:190`, `242-247` | Uses date-aware `get_stamp_tax_pct()`. |
| 资金不能透支 | Implemented for BUY. | `unified_engine.py:457-473`, `unified_matching_engine.py:166-197` | Single engine reduces shares; matching reports `cash_shortfall_mask`. |
| 整手 | Partially implemented. | `unified_engine.py:445-449`, `unified_matching_engine.py:167-178` | Single engine rounds every buy. Matching rounds only in cash-shortfall adjustment path. |
| ST/STAR/GEM/BJ limits | Partially implemented. | `limit_checker.py`, `unified_matching_engine.py:105-138` | Single engine uses `get_board_type(symbol, name)` but not IPO listing-day exceptions. |
| Price collar | Not clearly integrated in these execution paths. | `shared/price_collar.py` not observed in current engine flow. | Needs Stage 7/live readiness follow-up. |

## 6. 成交成本模型

Canonical constants are in `src/uniquant/shared/cost_model.py`:

| Cost | Current value / rule | Evidence |
|---|---|---|
| Commission | `0.0003`, minimum 5 CNY. | `cost_model.py:29-32` |
| Stamp duty | `0.0005` after 2023-08-28; old `0.001` before cutoff. Sell side only. | `cost_model.py:30-45` |
| Transfer fee | `0.00001`. | `cost_model.py:34` |
| Slippage | Base `0.0005`. | `cost_model.py:33` |

Single engine cost application:

- Buy: `value + commission + transfer_fee`; `stamp_duty=0.0` (`unified_engine.py:451-487`).
- Sell: `value - commission - stamp_duty - transfer_fee`; PnL uses net value minus cost basis (`unified_engine.py:527-551`).
- Slippage: buy fills above raw open, sell fills below raw open; impact uses `trade_volume / avg_daily_volume` capped at `0.02` (`unified_engine.py:384-409`).

Cost-model inconsistency:

`cost_model.calculate_total_cost()` and `CostConfig` apply transfer fee only when `_has_transfer_fee(symbol)` returns true, currently `symbol.startswith("60")` (`cost_model.py:48-62`, `144-153`). Both `UnifiedBacktestEngine` and `UnifiedMatchingEngine` always apply `TRANSFER_FEE_PCT` without checking exchange (`unified_engine.py:380-382`, `unified_matching_engine.py:163`, `248`). This is conservative for Shenzhen names but inconsistent with the declared cost helper.

## 7. 信号到订单到成交流程

Current single-symbol semantics:

1. `TradingSignal.timestamp` is reduced to `YYYY-MM-DD`.
2. On matching K-line date D, the engine reads all signals for D.
3. It creates at most one pending order:
   - first feasible BUY if flat;
   - first feasible SELL if holding.
4. That pending order executes at the next executable bar open.
5. If the next bar is non-trading day, no execution happens on that row.
6. If next execution bar has `volume <= 0`, the pending order is discarded.

Implications:

- A same-day BUY and SELL pair does not execute both; collection order and current position decide which pending order survives.
- If the signal is on the final K-line date, it has no next bar and never executes.
- If signal timestamp is missing, it maps to `"unknown"` and never executes.
- If the research pipeline uses `pd.Timestamp.now()` for historical data, signals often do not match historical bars.

## 8. 单票回测与组合回测差异

| Area | `UnifiedBacktestEngine` | `PortfolioEngine` / vectorized path |
|---|---|---|
| Status | Current typed engine. | Deprecated but still present and uses `UnifiedMatchingEngine`. |
| Signal input | `TradingSignal` list. | DataFrame/dict signals. |
| Delay | Built in: signal D -> next bar open. | `PortfolioEngine.run()` stores `_pending_signals` and executes on later loop date. |
| Suspension | Explicit `volume <= 0` rejection. | Volume dictionaries are built but current code does not clearly pass actual daily volume; matching has no explicit halt rejection. |
| Cash | Single-symbol cash state. | Portfolio splits cash per candidate via `self.cash / n`, then deducts actual fills. |
| Max positions | Not applicable. | Enforced by `max_positions`. |
| Execution core | Local helper methods. | `UnifiedMatchingEngine`. |

Evidence:

- Deprecated portfolio warning: `src/uniquant/hands/backtest/portfolio_engine.py:1-23`.
- Portfolio uses matching engine: `portfolio_engine.py:40-64`.
- Portfolio pending signal execution: `portfolio_engine.py` run loop around pending signals and batch open/close.

The architectural intent is clear, but "single source of truth" is incomplete because single-symbol engine implements local matching logic instead of delegating to `UnifiedMatchingEngine`.

## 9. 回测偏差风险

1. Pipeline timestamp risk: Stage 5 found `UnifiedResearchPipeline` stamps signals with `pd.Timestamp.now()`, so historical backtests can produce no trades or one-date-only trades.
2. Single-symbol backtest evaluates one final snapshot signal list, not a historically regenerated signal series across every bar.
3. Signal conflicts are resolved by list order and current position, not by an explicit execution policy.
4. Open-price next-day fills assume all queued orders can fill at open after only limit/volume checks; auction mechanics and partial fills are not modeled.
5. `volume > 0` allows any requested fill after cash/lot checks; there is no maximum participation cap beyond slippage impact.
6. Matching engine lacks explicit zero-volume halt rejection.
7. Transfer fee exchange logic is inconsistent between `cost_model` helper and unified engines.
8. Single engine does not model IPO first-days no-limit rules; vectorized matching has partial IPO logic.
9. Corporate actions, ex-rights adjustment consistency, and survivorship-bias controls depend on upstream data and are not enforced here.
10. Short-selling is not allowed by position checks, which is correct for common A-share cash trading, but sell intents while flat are silently ignored.

## 10. 改进建议

1. Generate historical signals per bar or per rebalance date before calling backtest; do not use `now()` for historical signal timestamps.
2. Add a `TradingSignal` aggregation/execution policy before backtest so each symbol/date has at most one authoritative action.
3. Move single-symbol fills onto `UnifiedMatchingEngine` or extract a common execution kernel to eliminate logic drift.
4. Align transfer fee behavior with `CostConfig` and symbol exchange rules.
5. Add explicit suspension rejection to `UnifiedMatchingEngine`.
6. Normalize buy shares to board lot size in all matching paths, not only cash-shortfall paths.
7. Add participation caps, partial fills, and liquidity rejection for large orders.
8. Add tests for pipeline timestamp-to-backtest behavior.
9. Add tests comparing single-engine and vectorized matching results on the same scenarios.
10. Decide whether IPO special limit rules are required in the single-symbol engine and implement consistently if yes.

## 11. 阶段结论

`UnifiedBacktestEngine` captures the core A-share mechanics needed for a conservative single-symbol research backtest: signal delay to next open, T+1 selling, limit-up/down rejection, suspension rejection, cash protection, sell-side stamp duty, slippage direction, and lot rounding.

The execution layer is not yet fully unified. `UnifiedMatchingEngine` is used by deprecated/portfolio paths and has stronger vectorized limit/IPO/T+1 machinery, but differs from the single engine on halt handling, lot normalization, and call semantics. The next remediation should be to make one matching kernel authoritative and ensure the signal layer provides timestamp-correct historical signals.

## 12. 校验清单

| Check | Status |
|---|---|
| T 日信号、T+1 open 成交逻辑 | Verified by code path: pending order executes next bar open. |
| 涨停不买、跌停不卖 | Verified in single and vectorized engines. |
| 印花税只在卖出侧 | Verified in single and vectorized engines. |
| 资金不能透支 | Verified: buy share reduction and final cash check. |
| 停牌 volume=0 | Verified in single engine; gap in vectorized matching noted. |
| 产物包含流程图、撮合规则、约束表、成本、信号流程、偏差、建议 | Done. |

## 13. 下一阶段输入

Stage 7 should analyze whether risk controls affect actual sizing, signals, and execution:

- `src/uniquant/risk/sizer.py`
- `src/uniquant/risk/drawdown_analyzer.py`
- `src/uniquant/risk/evt_risk.py`
- `src/uniquant/risk/historical_risk.py`
- `src/uniquant/risk/portfolio_optimizer.py`
- `src/uniquant/risk/structural.py`
- `src/uniquant/services/portfolio_service.py`
- `src/uniquant/services/health_service.py`
- `src/uniquant/ui/dashboard.py`
- Tests for sizer, drawdown, EVT, portfolio optimization, and health checks.

Key Stage 7 questions:

1. Does risk sizing feed into executable `TradingSignal.shares`, or is `default_shares` still dominant?
2. Are invalid stop-loss inputs conservative failures or silent defaults?
3. Does risk affect live/backtest orders after signal generation?
4. What is the minimum remediation list before real-money use?
