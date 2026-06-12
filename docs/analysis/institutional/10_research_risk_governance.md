# WS10 — Research Risk Governance

Generated: 2026-06-10

Scope: Define the risk governance matrix for the institutional research platform. Position sizing, concentration, drawdown, `default_shares` bypass, survivorship warnings, and veto propagation into signal arbitration (building on WS6).

## 1. Current Risk Infrastructure

### 1.1 Position sizing

| Component | File | Key method | Returns |
|---|---|---|---|
| `PositionSizer` | `risk/sizer.py:50` | `calculate_shares(price, stop_loss, market, czsc_bottom, atr_stop, symbol)` | `Dict[str, Any]` with Chinese keys: `建议仓位`, `修正仓位`, `执行止损`, `资金占用`, `是否触发熔断` |
| `VolumeLimitSizer` | `risk/sizer.py:211` | `cap_shares(target_shares, daily_volume, price)` | Dict with `actual_shares`, `cash_drag`, `fill_rate`, `capped` |
| `InverseVolatilitySizer` | `risk/sizer.py:285` | `compute_weights(volatilities, symbols)` | `Dict[str, float]` weights |
| `PortfolioSizer` | `risk/sizer.py:390` | `allocate(signals, portfolio_equity, daily_pnl)` | `PortfolioAllocation` with max_total_risk, max_single, max_daily_loss, sector limit |

### 1.2 Risk measurement

| Component | File | Key method | Returns |
|---|---|---|---|
| `HistoricalSimulationRisk` (aka EVTRisk) | `risk/evt_risk.py` | `calculate_metrics(returns)` | `var_95`, `var_99`, `cvar_95`, `cvar_99`, `max_drawdown`, `regime`, `ntf_signal` |
| `DrawdownAnalyzer` | `risk/drawdown_analyzer.py` | `analyze_drawdown(equity)`, `analyze_tail_risk(returns)`, `stress_scenario(equity, name)` | Typed dataclasses: `DrawdownMetrics`, `TailRiskMetrics`, `StressTestResult` |
| `StructuralRiskManager` | `risk/structural.py` | `get_macro_conclusion(overall_risk)` | String |
| `PortfolioService` | `services/portfolio_service.py` | `calculate_position()`, `rebalance()`, `analyze_portfolio()` | Dicts with Decimal precision |

### 1.3 Risk integration in decision pipeline

| Integration point | Evidence | Status |
|---|---|---|
| DecisionBrain veto | `_check_veto_conditions()` — FORCE_WAIT on FROZEN, FORCE_EXIT on Danger without NTF support | Exists |
| DecisionBrain buy blockers | `_check_buy_blockers()` — LPPL danger, frozen market, risk engine failure, stop-loss issues, weak alpha, limit-up/down | Exists |
| DecisionBrain calls PositionSizer | `_execute_buy()` calls `self.sizer.calculate_shares()` with risk scaler from EVT risk | Exists |
| DecisionBrain calls EVT risk | `_execute_buy()` calls `self.evt_risk.calculate_metrics(ctx.returns)` | Exists |
| Non-FSM adapter default_shares | CZSC/Wyckoff/NTF/Alpha/MA adapters use `default_shares` without risk sizing | **Gap** (WS6-006) |

## 2. Findings

### Finding WS10-001 — `default_shares` bypasses PositionSizer for non-FSM adapters (P1)

Evidence:
- WS6-006 documented this in the adapter blueprint.
- 5 of 8 adapters (CZSC, Wyckoff, NTF, AlphaScore, MAStatus) use `default_shares` parameter for BUY quantity (`adapters.py:127-135, 180-188, 302-310, 338-346, 374-382`).
- `DecisionBrain._execute_buy()` calls `PositionSizer.calculate_shares()` and applies risk scaler (`fsm.py:419-450`).
- `SignalArbitrator` target (WS6) requires BUY size from `DecisionOutput.shares` or a `PositionSizer` gate.

Impact:
- Lower-level indicator BUY signals can execute with arbitrary quantity, bypassing risk sizing.
- Even in the current pipeline (where FSMAdapter runs first), a non-FSM BUY can be consumed by the backtest if FSM output is HOLD.

Risk Level: P1

Recommendation:
- The `SignalArbitrator` target (WS6) must reject BUY candidates without risk-sized shares.
- `PositionSizer` must be available as a gate in the arbitration step, not just in `DecisionBrain`.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS10-002 — PositionSizer returns Chinese-keyed Dict — cannot be validated at the type level (P2)

Evidence:
- `PositionSizer.calculate_shares()` returns dict keys: `建议动作`, `入场区间`, `几何止损`, `ATR止损`, `执行止损`, `风险敞口`, `建议仓位`, `资金占用`, `是否触发熔断`, `修正仓位` (`sizer.py:148-190`).
- `PositionSizerProtocol` defines `calculate_shares()` return as `Dict[str, Any]` (`interfaces.py:100-123`).
- `DecisionBrain._execute_buy()` accesses keys `建议仓位` and maps to `final_shares` (`fsm.py:440-445`).

Impact:
- Type system cannot detect key name changes.
- English-chinese key mixing increases cognitive load at the governance boundary.

Risk Level: P2

Recommendation:
- Add English aliases to `PositionSizer` return: `suggested_shares`, `entry_zone`, `geo_stop`, `atr_stop`, `execution_stop`, `risk_exposure`, `circuit_break_triggered`, `adjusted_shares`.
- Keep Chinese keys for backward compatibility. Deprecate in Sprint 3.

Migration Cost: Low

Priority: Sprint 2

### Finding WS10-003 — No single-name concentration enforcement in research pipeline (P1)

Evidence:
- `PortfolioSizer._max_single = 0.10` (10% max single position) exists in `sizer.py:390-393`.
- `PortfolioSizer.allocate()` enforces this: `if sig.notional > max_notional: sig.notional = max_notional` (`sizer.py:409-412`).
- **However**: `PortfolioSizer` is NOT wired into the pipeline. `UnifiedResearchPipeline` (single-symbol) and `UnifiedBacktestEngine` have no single-name concentration check.
- `PositionSizer.calculate_shares()` has no `max_position_pct` parameter — it sizes relative to `self.capital` only.
- `PortfolioService.calculate_position()` validates position pct between 0% and 100% but does not enforce single-name cap.

Impact:
- A single-symbol backtest can allocate 100% of capital to one stock.
- For multi-symbol research, concentration is not enforced unless `PortfolioSizer` is explicitly used.

Risk Level: P1

Recommendation:
- Add `max_position_pct: float = 0.10` (configurable) to `PositionSizer`.
- In `calculate_shares()`, cap `suggested_shares` so that `total_value <= capital * max_position_pct`.
- Document that single-symbol backtest users must set this external to the pipeline.

Migration Cost: Low

Priority: Sprint 2

### Finding WS10-004 — No sector concentration enforcement — code exists but is incomplete (P2)

Evidence:
- `PortfolioSizer.__init__` has `_max_single_sector_pct = 0.20` parameter (`sizer.py:392`).
- `PortfolioSizer.allocate()` has a TODO comment: `# TODO: Enforce max_single_sector_pct using industry classification` (`sizer.py:405`).
- The allocation method does not enforce sector concentration.

Impact:
- Multi-symbol research can over-allocate to a single sector, producing backtest results that are not representative of diversified research.

Risk Level: P2

Recommendation:
- Implement sector concentration check in `PortfolioSizer.allocate()` using `DataService.get_industry_data()` or a symbol→sector mapping.
- Until implemented, document as known gap.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS10-005 — Drawdown limits exist in DrawdownAnalyzer but no stop-loss in pipeline execution (P1)

Evidence:
- `DrawdownAnalyzer.analyze_drawdown()` computes comprehensive drawdown metrics (`drawdown_analyzer.py:75-114`).
- `DecisionBrain._check_veto_conditions()` does NOT check drawdown limits.
- `UnifiedBacktestEngine` does NOT stop or reduce position when drawdown exceeds threshold.
- `UnifiedResearchPipeline` returns `BacktestResult` with drawdown data but does not gate execution on it.

Impact:
- A backtest can continue trading into a deep drawdown without any risk intervention.
- Live trading would require circuit breakers; research backtesting should at least report drawdown events.

Risk Level: P1

Recommendation:
- Add configurable `max_drawdown_pct` to `UnifiedBacktestEngine`.
- When equity curve drawdown exceeds threshold, set `pending_order = None` and log warning.
- Add drawdown check to `DecisionBrain._check_veto_conditions()` when `ctx.returns` is available.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS10-006 — `PortfolioEngine` has no risk controls (P2)

Evidence:
- `PortfolioEngine.batch_open_positions()` accepts `signals: Dict[str, float]` — positive = BUY — and allocates `sizing_fraction * cash / n` per symbol (`portfolio_engine.py:163-201`).
- No `PositionSizer` call. No concentration check. No drawdown check.
- `PortfolioEngine.batch_close_positions()` has no stop-loss logic — sells are driven by signal sign only.
- Deprecated but still functional.

Impact:
- Multi-symbol PortfolioEngine backtests have zero risk governance.

Risk Level: P2

Recommendation:
- Deprecate `PortfolioEngine` explicitly. Remove in Sprint 4.
- All multi-symbol research should use `PortfolioSizer` + `UnifiedMatchingEngine` directly.

Migration Cost: Low

Priority: Sprint 3

### Finding WS10-007 — Survivorship bias warning is missing from pipeline outputs (P1)

Evidence:
- Data infrastructure supports delist_date tracking (`stock_metadata_manager.py:244-260`).
- `DataService.fetch_for_brain()` does not check if the symbol is delisted or was not listed at the start of the data range.
- `BacktestResult` has no `survivorship_warning` field.
- `UnifiedResearchPipeline` does not emit survivorship/selection bias warnings.

Impact:
- Users running today's stock list against 5-year historical data may unknowingly backtest survivor-biased universes.

Risk Level: P1

Recommendation:
- In `UnifiedResearchPipeline.run()`, check the symbol's listing/delist dates against the K-line date range.
- Add `metadata["survivorship_warning"]` to `BacktestResult` when the symbol was delisted within the range or was not listed at the range start.
- For the scan pipeline (`ScanService`), add `exclude_delisted=False` verification.

Migration Cost: Low

Priority: Sprint 2

### Finding WS10-008 — Selection bias / future-known universe risk — no point-in-time universe (P2)

Evidence:
- No evidence of point-in-time index constituent lists.
- `ScanService` scans symbols from today's stock list.
- No IPO date check in `DataService.fetch_for_brain()`.

Impact:
- Backtesting stocks that did not exist at the start of the data range produces inflated returns (newer stocks tend to outperform).

Risk Level: P2

Recommendation:
- Add `listing_date` to `DataService.fetch_for_brain()` return metadata.
- Add warning in `PipelineResult` when data range starts before listing date.

Migration Cost: Low

Priority: Sprint 3

### Finding WS10-009 — `HistoricalSimulationRisk` / `EVTRisk` is well-structured but only called from DecisionBrain (P1)

Evidence:
- `EVTRisk.calculate_metrics()` computes VaR(95%), VaR(99%), CVaR(95%), CVaR(99%), max_drawdown, regime detection, and NTF signal (`evt_risk.py:91-148`).
- Called only from `DecisionBrain._execute_buy()` (`fsm.py:425-426`).
- If `DecisionBrain` output is HOLD or vetoed, or if `ctx.returns` is missing/empty, EVT risk is never computed.
- The risk metrics are not recorded in `BacktestResult`.

Impact:
- Backtest reports do not include risk metrics.
- Risk computation is gated on BUY execution, not computed per-bar.

Risk Level: P1

Recommendation:
- Add optional `risk_metrics` field to `BacktestResult.metadata`.
- In `UnifiedBacktestEngine.run()`, compute EVT risk metrics at end of backtest and attach to result.
- In `DecisionBrain._make_decision()`, compute EVT risk even when the decision is HOLD.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS10-010 — Live order risk is properly deferred — no live broker evidence (GREEN)

Evidence:
- No broker/OMS/live order management source files found.
- `risk/` modules all operate on research data (returns, equity curves).
- `PositionSizer.capital` is a fixed parameter, not reconciled with any live account.
- `PortfolioService.rebalance()` is a research simulation method.

Impact:
- Current scope (research platform) is correctly separated from live trading risk.
- Live order risk, position reconciliation, broker failover, and disaster recovery remain deferred.

Risk Level: GREEN

Recommendation:
- Maintain separation. WS13 will document live trading gaps.

Priority: Sprint 4

## 3. Risk Governance Matrix — Target State

| Control | Current status | Target | Sprint |
|---|---|---|---|
| Position sizing gate | Only in DecisionBrain | Also in SignalArbitrator | 2 |
| Single-name concentration | Not in pipeline | PositionSizer cap + BacktestResult warning | 2 |
| Sector concentration | Code exists, not implemented | PortfolioSizer + industry mapping | 3 |
| Drawdown circuit breaker | Not in pipeline | UnifiedBacktestEngine + DecisionBrain | 2 |
| `default_shares` bypass | 5 adapters use it | Arbitrator rejects non-risk-sized BUY | 2 |
| Survivorship warning | Data infra exists | PipelineResult.metadata.warning | 2 |
| Selection bias / IPO check | Not implemented | PipelineResult.metadata.warning | 3 |
| Risk metrics in backtest | Not recorded | BacktestResult.metadata.risk_metrics | 2 |
| Live order risk | Properly deferred | WS13 blueprint | 4 |
| PortfolioEngine risk | None | Deprecate → remove | 3 |

## 4. Integration with WS6 SignalArbitrator

The `SignalArbitrator` (designed in WS6) must enforce risk governance at the arbitration step:

```python
# Pseudocode for risk gate in arbitration:
class SignalArbitrator:
    def arbitrate(
        self,
        candidates: List[CandidateSignal],
        decision_output: DecisionOutput,
        sizer: PositionSizer,
        ctx: MarketSignalContext,
    ) -> ArbitrationReport:
        # Step 1: Veto check (highest priority)
        if decision_output.final_decision in ("FORCE_WAIT", "CIRCUIT_BREAK"):
            return HOLD with veto_reason
        if decision_output.final_decision == "FORCE_EXIT":
            return SELL with exit_reason

        # Step 2: DecisionBrain is authoritative for execution
        if decision_output.final_decision == "BUY" and decision_output.shares > 0:
            return BUY with risk_sized_shares

        # Step 3: Non-FSM BUY candidates require PositionSizer
        for c in candidates:
            if c.action == "BUY" and c.source != "fsm":
                sized = sizer.calculate_shares(
                    price=c.price,
                    stop_loss=ctx.atr_stop,
                    market=ctx.market,
                    symbol=c.symbol,
                )
                if sized["建议仓位"] > 0:
                    return BUY with sized_shares

        # Step 4: Default to HOLD
        return HOLD
```

## 5. Default Shares Governance Rule

In the target `SignalArbitrator`:

```text
RULE: No BUY candidate may create an executable TradingSignal
      unless its share quantity comes from one of:
        1. DecisionOutput.shares (from DecisionBrain + PositionSizer)
        2. PositionSizer.calculate_shares() called at arbitration time
        3. A PortfolioSizer allocation step

      Candidates using default_shares are treated as evidence/intent
      only — they do not produce executable quantity.
```

## 6. Verification Checklist

- [x] Audited position sizing authority: `PositionSizer` is the canonical source, but only called from `DecisionBrain`.
- [x] Identified `default_shares` bypass: 5 adapters with default_shares (P1).
- [x] Audited single-name concentration: `PortfolioSizer` has cap but not wired into pipeline (P1).
- [x] Audited industry concentration: code exists but `TODO: not implemented` comment (P2).
- [x] Audited leverage controls: `PortfolioService` validates 0-100% but no margin/leverage.
- [x] Audited drawdown limits: `DrawdownAnalyzer` exists but not integrated into execution (P1).
- [x] Audited risk veto propagation into signal arbitration: WS6 defines SignalArbitrator veto gate.
- [x] Audited duplicate signal/order prevention: research simulation only (live is deferred).
- [x] Marked live order risk as deferred (GREEN — no broker evidence).
- [x] Produced research risk governance matrix (§3) with target state per control.
- [x] Deferred live risk governance matrix to WS13 Production Readiness report.