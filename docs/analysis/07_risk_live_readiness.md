# Stage 7 - Risk And Live Readiness

Generated: 2026-06-09

Scope: risk sizing, risk metrics, portfolio optimization, risk-control closure, and live-readiness. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0-6 artifacts and Stage 7 playbook requirements.
2. Analyze `PositionSizer` and `PortfolioSizer`.
3. Inspect drawdown, historical risk, tail risk, structural risk, and portfolio optimization modules.
4. Trace risk usage in `DecisionBrain`, services, UI, signal, and backtest.
5. Score live-readiness and produce P0/P1/P2 remediation plan.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` through `06_backtest_matching.md` | Prior-stage architecture, data, brain, factor, signal, and execution findings. |
| `src/uniquant/risk/sizer.py` | Position sizing, Kelly, T+1 penalty, CZSC/ATR stop logic. |
| `src/uniquant/risk/drawdown_analyzer.py` | Drawdown, tail risk, stress scenarios. |
| `src/uniquant/risk/evt_risk.py` | Historical simulation VaR/CVaR, regime, stress tests. |
| `src/uniquant/risk/historical_risk.py` | Compatibility wrapper around risk implementation. |
| `src/uniquant/risk/portfolio_optimizer.py` | Risk parity and mean-variance optimization. |
| `src/uniquant/risk/structural.py` | Structural risk reporting context. |
| `src/uniquant/brain/fsm/fsm.py` | DecisionBrain risk vetoes and sizing usage. |
| `src/uniquant/services/portfolio_service.py` | Portfolio facade and fallback sizing. |
| `src/uniquant/services/health_service.py` | Health checks for data, analysis, brain, and risk. |
| `src/uniquant/ui/dashboard.py` | UI position-size display. |
| `src/uniquant/ui/manager_logic.py` | UI manager facade to portfolio service. |
| `tests/test_sizer.py`, `tests/test_drawdown_analyzer.py`, `tests/test_evt_risk.py`, `tests/test_portfolio_optimizer.py`, `tests/test_phase4_3_risk_guardrails.py` | Risk-related test coverage references. |

## 3. 仓位 Sizing 机制

`PositionSizer` is the primary risk sizing module.

Formula:

```text
final_stop = max(atr_stop or stop_loss, czsc_bottom if higher)
risk_per_share = price - final_stop
effective_risk_pct = risk_pct * kelly_fraction, if kelly_fraction is set
max_loss_allowed = capital * effective_risk_pct
shares_raw = max_loss_allowed / (risk_per_share * market_penalty)
shares = floor(shares_raw / lot_size) * lot_size
if shares * price > capital:
    adjusted_shares = floor(capital / (price * lot_size)) * lot_size
```

Key points:

| Mechanism | Behavior | Evidence |
|---|---|---|
| `risk_pct` | Defaults to `0.05`; controls maximum capital-at-risk. | `src/uniquant/risk/sizer.py:77-82`, `158-161` |
| `kelly_fraction` | Optional multiplier on `risk_pct`; `calculate_kelly()` clamps to `[0, 1]`. | `sizer.py:84-93`, `158-161` |
| T+1 penalty | CN market uses `1.2`, US/HK use `1.0`; higher penalty lowers shares. | `sizer.py:82`, `158-165` |
| ATR/CZSC stop | Uses the higher stop as more conservative final stop. | `sizer.py:143-150` |
| Invalid stop | If final stop is at or above entry price, raises `InvalidStopLossError`. | `sizer.py:63-68`, `152-156` |
| Lot size | CN uses board lot size from `market_rules`; fallback 100. | `sizer.py:95-105`, `167-170` |
| Capital circuit break | If position notional exceeds capital, caps to capital-based shares. | `sizer.py:176-185` |

`PortfolioSizer` adds portfolio-level caps: max total risk, max single position, daily loss stop, and a TODO for sector cap enforcement (`sizer.py:248-284`).

## 4. 风控模块清单

| Module | Capability | Current maturity |
|---|---|---|
| `PositionSizer` | Single-position risk sizing with T+1 penalty, stop validation, lot rounding. | Strong local logic. |
| `PortfolioSizer` | Caps max total risk, max single notional, daily loss. | Useful but not visibly wired into main pipeline. |
| `DrawdownAnalyzer` | MDD, drawdown duration, Calmar, rolling MDD, ulcer index, tail risk, stress scenarios. | Good post-trade analytics. |
| `HistoricalSimulationRisk` / `EVTRisk` alias | VaR/CVaR by historical percentiles, volatility regime, max drawdown, risk signal, stress tests. | Useful but naming says EVT while doc notes it is not true GPD EVT. |
| `PortfolioOptimizer` | Risk parity and mean-variance optimization with covariance shrinkage. | Research/portfolio tool; not connected to execution allocation by default. |
| `StructuralRiskManager` | Formats macro risk matrix and report context. | Reporting/context helper. |
| `PortfolioService` | Portfolio weights, position calculation facade, fallback sizing, risk metrics and optimization wrappers. | Service-level tool; fallback sizing is simpler than `PositionSizer`. |
| `HealthService` | Component health checks for config, data, analysis, brain, risk, cache, data lake, system. | Monitoring helper, but some checks appear stale. |

Evidence:

- Drawdown metrics and stress scenarios: `src/uniquant/risk/drawdown_analyzer.py:19-196`.
- Historical risk metrics: `src/uniquant/risk/evt_risk.py:24-115`, `131-212`.
- Portfolio optimization config and risk parity: `src/uniquant/risk/portfolio_optimizer.py:83-249`.
- Structural risk context: `src/uniquant/risk/structural.py:9-106`.

## 5. 风控闭环分析

Current risk closure by path:

```text
AnalysisService -> DecisionBrain
  -> risk vetoes: regime/LPPL/macro unavailable, FROZEN, LPPL Danger
  -> stop-loss blockers: missing/invalid/too-wide ATR stop
  -> sell triggers: LPPL danger, MA reversal, weak alpha, regime risk
  -> buy sizing: HistoricalSimulationRisk regime + PositionSizer shares
  -> decision dict with shares and position_details
  -> TradingSignalCollector FSMAdapter can convert shares into TradingSignal
  -> UnifiedBacktestEngine uses signal.shares for BUY
```

Evidence:

- Risk engine blockers: `src/uniquant/brain/fsm/fsm.py:258-278`.
- Stop-loss blockers: `fsm.py:280-294`.
- Vetoes: `fsm.py:296-315`.
- Sell conditions: `fsm.py:330-366`.
- Buy blockers: `fsm.py:385-417`.
- EVT metrics and sizer call: `fsm.py:419-450`.

The closure is partial:

1. If `DecisionBrain` returns a BUY with `shares`, the FSM adapter preserves those shares.
2. If `DecisionBrain` cannot calculate sizing because returns are missing, it can still return BUY without shares (`fsm.py:451-457`); Stage 5 showed adapters/backtest may then fall back to default shares.
3. Other adapters can emit independent BUY signals with `default_shares`, bypassing `PositionSizer`.
4. Stage 5 found risk veto HOLD signals do not suppress later BUY signals in the current collector/backtest flow.
5. Stage 6 found execution enforces cash/lot/T+1/limits, but it does not know whether the order came from risk-sized DecisionBrain or a default adapter signal.

## 6. 服务和 UI 接入

| Path | Current behavior | Readiness note |
|---|---|---|
| `DecisionBrain` | Instantiates default `HistoricalSimulationRisk` and `PositionSizer` when not injected. | Good for standalone analysis, but dependency config is implicit. |
| `PortfolioService.calculate_position_size()` | Delegates to injected `risk_service` if present; otherwise uses fallback formula and 100-share CN rounding. | Fallback does not apply T+1 penalty or invalid-stop exception semantics. |
| Dashboard trading plan | Calls `asset_mgr.calculate_position_size()` and displays T+1 warning. | UI planning only; not order-execution integration. |
| `HealthService` | Instantiates data, analysis, risk, sizer, DecisionBrain and runs checks. | Monitoring is broad, but risk check expects `"var_q"` even metrics use `"var_95"`/`"var_99"`, so health status may be misleading. |
| Backtest engine | Enforces execution constraints but does not calculate risk sizing. | Correct separation, but input signals must already be risk-sized. |

Evidence:

- Portfolio fallback sizing: `src/uniquant/services/portfolio_service.py:156-186`.
- Health service construction and checks: `src/uniquant/services/health_service.py:35-68`, `200-219`.
- UI position sizing display: `src/uniquant/ui/dashboard.py:680-709`.

## 7. 实盘可用性评分

Score: **45 / 100 for real-money readiness**.

| Area | Score | Rationale |
|---|---:|---|
| Architecture | 7/10 | Clear layer separation and service orchestration. |
| Data correctness | 5/10 | Data lake and validators exist, but Stage 2 found source/config drift and field consistency risks. |
| Brain decisions | 6/10 | Multi-engine veto-scoring exists, but `pre_close` and missing alpha/failure semantics need correction. |
| Factor research | 5/10 | IC/OOS tools exist; production admission gates are incomplete. |
| Signal execution policy | 3/10 | Current collector is additive and can bypass risk vetoes. |
| Backtest execution | 7/10 | Single-symbol A-share mechanics are strong; vectorized/portfolio differences remain. |
| Risk sizing | 6/10 | `PositionSizer` is solid, but not consistently authoritative across all executable signals. |
| Monitoring/live ops | 2/10 | Health checks exist, but no live order gateway, kill switch, broker reconciliation, or operational runbook was identified. |
| Overall | 45/100 | Research-grade platform with meaningful guardrails; not live-trading ready. |

## 8. 高风险缺口

1. Signal risk veto bypass: lower-level adapters can emit BUY even when DecisionBrain risk output is HOLD/FORCE_WAIT.
2. Default-share bypass: non-FSM adapter signals use `default_shares`, bypassing `PositionSizer`.
3. Historical backtest timestamp bug: pipeline signals use `now()` instead of historical bar dates.
4. Missing/failed alpha and risk data can become executable bearish/bullish semantics instead of no-signal diagnostics.
5. `pre_close` may be absent in the main decision context, weakening limit/circuit checks before execution.
6. Risk sizing and portfolio optimization are not unified into one execution allocation policy.
7. `PortfolioService` fallback sizing differs from `PositionSizer`, so UI/service sizing can disagree with DecisionBrain sizing.
8. `HealthService` risk check appears to look for a non-existent `var_q` field.
9. No broker/order-management layer, kill switch, live position reconciliation, or latency/staleness control was observed.
10. No final production admission gate tying data quality, signal aggregation, risk sizing, and execution constraints into one pass/fail decision.

## 9. P0/P1/P2 整改计划

### P0 - Before Any Real-Money Use

1. Add deterministic executable-signal aggregation: risk vetoes must suppress BUYs; final output must be one action per symbol/date.
2. Make `PositionSizer` authoritative for all BUY signals; disallow default-share executable BUY unless explicitly marked as manual/test.
3. Fix historical signal timestamp generation so backtests use bar dates and regenerate signals through time.
4. Fix `pre_close` propagation into `MarketSignalContext` before DecisionBrain limit checks.
5. Normalize missing engine outputs: failed/missing alpha/factor/regime data should produce diagnostics or HOLD, not SELL/BUY intent.
6. Add a live-trading guard module with kill switch, stale-data rejection, max order notional, max daily loss, and manual confirmation mode.

### P1 - Production Research Reliability

1. Convert factor admission, signal aggregation, risk sizing, and execution checks into a single pipeline report.
2. Unify single-symbol and vectorized matching kernels.
3. Align `PortfolioService` sizing with `PositionSizer`.
4. Add broad A-share universe backtests with survivorship, ST, suspension, limit, and delisting handling.
5. Add signal/risk/execution integration tests for risk-veto scenarios.
6. Fix health-check field drift and add alerts for stale data, empty data, failed engines, and cache pollution.

### P2 - Live Operations And Scale

1. Add broker adapter abstraction and paper-trading mode.
2. Add order state machine: submitted, accepted, partial, filled, rejected, canceled.
3. Add portfolio-level optimizer-to-order allocator with sector/industry caps.
4. Add monitoring dashboards for exposure, VaR/CVaR, drawdown, pending orders, rejected orders, and data freshness.
5. Add daily post-trade reconciliation and audit logs.
6. Add runbooks for market halt, data outage, broker outage, and emergency liquidation.

## 10. 实盘前检查清单

| Check | Required status before live |
|---|---|
| Data freshness | Latest bar/date verified for each symbol and benchmark. |
| Data schema | `date/open/high/low/close/volume/pre_close` present and validated. |
| Signal aggregation | Exactly one final executable intent per symbol/date. |
| Risk veto | Regime/LPPL/macro failures block new BUYs. |
| Position sizing | All BUYs use `PositionSizer` or approved portfolio allocator. |
| Stop loss | Missing/invalid/wide stop blocks new BUYs. |
| A-share tradability | ST, suspension, limit-up/down, lot size, T+1, cash all enforced before order creation. |
| Cost model | Commission, stamp duty, transfer fee, slippage match broker/account assumptions. |
| Exposure caps | Per-order, per-symbol, portfolio, sector, daily loss caps enforced. |
| Monitoring | Health checks, alerts, stale-data detection, and kill switch active. |
| Reconciliation | Broker positions/cash/orders reconciled with internal state. |
| Audit | Every final order has trace id, contributing signals, risk decision, and execution result. |

## 11. 最终系统功能总结

UniQuant currently provides:

- Eight-layer Python architecture for A-share quantitative research.
- Service container and research pipeline orchestration.
- Data service, data lake, source routing, validation, and adjustment components.
- Multi-engine brain analysis: regime, LPPL, NTF, CZSC, Wyckoff, alpha, indicators, DecisionBrain.
- Factor registry, factor computation, IC/IR analysis, OOS walk-forward framework, and factor composition.
- Signal adapters from Brain outputs to `TradingSignal`.
- Single-symbol typed backtest with major A-share mechanics.
- Vectorized matching engine for batch/portfolio paths.
- Risk sizing, drawdown/tail risk analytics, historical VaR/CVaR, structural risk context, and portfolio optimization tools.
- Streamlit dashboard and health-service scaffolding.

Current maturity: **research and offline validation platform**, not yet an automated live trading system.

## 12. 阶段结论

The risk layer has meaningful components and DecisionBrain partially consumes them. The strongest part is `PositionSizer`: it includes `risk_pct`, optional Kelly scaling, CN T+1 penalty, CZSC/ATR stop selection, invalid-stop exception handling, and lot rounding.

The live-readiness gap is integration, not absence of risk math. Risk sizing must become the only path to executable BUY size, risk vetoes must become authoritative in signal aggregation, and execution must be driven by timestamp-correct historical/live signals with operational controls.

## 13. 校验清单

| Check | Status |
|---|---|
| 说明 `risk_pct`、`kelly_fraction`、T+1 penalty | Done in sizing section. |
| 检查止损无效时异常处理 | Done: `InvalidStopLossError` documented. |
| 说明风控是否影响实际下单或回测 | Done: partial DecisionBrain path, bypass risks, and backtest dependency on signal shares documented. |
| 形成实盘前检查清单 | Done. |
| 包含 P0/P1/P2 整改计划 | Done. |
| 最终系统功能总结 | Done. |

## 14. 最终验收输入

All stage artifacts now exist:

- `docs/analysis/00_architecture_map.md`
- `docs/analysis/01_services_orchestration.md`
- `docs/analysis/02_data_system.md`
- `docs/analysis/03_brain_engines.md`
- `docs/analysis/04_factor_system.md`
- `docs/analysis/05_signal_system.md`
- `docs/analysis/06_backtest_matching.md`
- `docs/analysis/07_risk_live_readiness.md`

Recommended final acceptance step: review these eight artifacts for consistency and produce a concise project remediation roadmap. No tests were run during these analysis stages.
