# Stage 5 - Signal System

Generated: 2026-06-09

Scope: Brain output to `TradingSignal`, signal collection, conflict handling, timestamp semantics, and A-share live-readiness. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0-4 artifacts and Stage 5 playbook requirements.
2. Inspect `TradingSignal` in `shared.interfaces`.
3. Inspect all `EngineAdapter` mappings in `signal.adapters`.
4. Trace `TradingSignalCollector` into `UnifiedResearchPipeline`.
5. Inspect generic `signal.models`, `normalizer`, `aggregator`, and `quality` boundaries.
6. Trace how `UnifiedBacktestEngine` indexes timestamps and executes signals.
7. Propose deterministic A-share signal priority and validation rules.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` | Architecture baseline. |
| `docs/analysis/01_services_orchestration.md` | Service orchestration baseline. |
| `docs/analysis/02_data_system.md` | Data-system baseline. |
| `docs/analysis/03_brain_engines.md` | Brain engine outputs and conflict handoff. |
| `docs/analysis/04_factor_system.md` | Factor output and future `composite_score` handoff. |
| `src/uniquant/shared/interfaces.py` | Actual `TradingSignal` contract. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters and collector. |
| `src/uniquant/signal/models.py` | Generic signal model, source, type, strength, consensus. |
| `src/uniquant/signal/normalizer.py` | Generic raw signal to `Signal` normalizers. |
| `src/uniquant/signal/aggregator.py` | Generic multi-signal aggregation algorithms. |
| `src/uniquant/signal/quality.py` | Post-hoc signal quality metrics. |
| `src/uniquant/services/research_pipeline.py` | Pipeline collection and backtest handoff. |
| `src/uniquant/hands/backtest/unified_engine.py` | `TradingSignal` timestamp indexing and execution. |
| `tests/test_signal.py` | Generic `Signal`/normalizer/aggregator/quality tests. |
| `tests/test_e2e_pipeline.py` | Collector to backtest integration tests. |
| `tests/test_phase4_2_contracts.py` | Pipeline contract test for FSM decision signal. |

## 3. TradingSignal 字段说明

The execution path uses `src/uniquant/shared/interfaces.py::TradingSignal`, not `src/uniquant/signal/models.py::Signal`.

| Field | Type | Meaning | Current risk |
|---|---|---|---|
| `action` | `str` | Executable action: expected `BUY`, `SELL`, `HOLD`. | No enum validation; unknown strings can pass until ignored downstream. |
| `reason` | `str` | Human-readable explanation. | No source/priority metadata, so audit trail is weak when multiple signals conflict. |
| `confidence` | `float` | Adapter-specific confidence, intended `[0, 1]`. | Not clamped in `TradingSignal`; adapter formulas are inconsistent. |
| `shares` | `int` | Requested trade size. | Defaults vary; sell signals often set `default_shares` but backtest sells full position anyway. |
| `symbol` | `str` | Security code. | Collector uses `data_pack["symbol"]`; empty symbol is allowed. |
| `price` | `float` | Signal reference price. | Backtest executes next open and does not use signal price for fill. |
| `timestamp` | optional datetime | Date/time used by backtest to locate the signal bar. | Critical: missing timestamp maps to `"unknown"` and never matches K-line dates. |

Evidence: `src/uniquant/shared/interfaces.py:127-169`.

`TradingSignal.from_dict()` maps old action names to executable actions: `ADD`/`EXECUTE_BUY` -> `BUY`, `FORCE_EXIT`/`EXECUTE_SELL` -> `SELL`, and risk-wait states -> `HOLD` (`interfaces.py:143-169`).

## 4. 两套信号模型边界

There are currently two signal abstractions:

| Model | Path | Role | Used by current pipeline? |
|---|---|---|---|
| `TradingSignal` | `shared.interfaces` | Brain-to-Hands execution contract. | Yes: `TradingSignalCollector` and `UnifiedBacktestEngine`. |
| `Signal` / `AggregatedSignal` | `signal.models` | Richer research/quality/aggregation model with source/type/direction/strength. | Not in current research pipeline execution path. |

`SignalAggregator` supports weighted average, majority vote, max confidence, and consensus threshold (`signal/aggregator.py:26-31`, `102-122`), but these operate on `Signal`, not `TradingSignal`. `UnifiedResearchPipeline.run()` sends the raw list from `TradingSignalCollector` directly to `UnifiedBacktestEngine` without calling `SignalAggregator` (`research_pipeline.py:128-157`).

## 5. 引擎输出到信号的映射表

| Source | Adapter | Input fields | Output rule | Evidence |
|---|---|---|---|---|
| LPPL | `LPPLAdapter` | `risk`/`risk_level`, `bubble_confidence`/`confidence` | `Danger` -> SELL; `Warning`/other -> HOLD; confidence `<0.05` -> None. | `adapters.py:61-98` |
| CZSC | `CZSCAdapter` | `is_3rd_buy`, `bi_count` | third-buy -> BUY; non-third-buy with stroke count -> HOLD; no evidence -> None. | `adapters.py:105-135` |
| Wyckoff | `WyckoffAdapter` | `wyckoff_phase`, `wyckoff_confidence`, `spring`, `utad` | accumulation/spring -> BUY; distribution/UTAD -> SELL; low confidence/unknown -> None. | `adapters.py:142-188` |
| FSM / DecisionBrain | `FSMAdapter` | `final_decision` or `action`, `shares`, `confidence`, `reason` | Maps DecisionBrain action directly into BUY/SELL/HOLD. | `adapters.py:195-237` |
| Regime | `RegimeAdapter` | `regime` | `FROZEN`/`STRESSED` -> HOLD; `NORMAL` -> None. | `adapters.py:244-276` |
| NTF | `NTFAdapter` | `ntf_side`, `ntf_intensity` | `LONG` -> BUY; `SHORT` -> SELL; other non-NONE -> HOLD; intensity `<0.3` -> None. | `adapters.py:283-310` |
| Alpha | `AlphaScoreAdapter` | `alpha_score` | `>0.6` -> BUY; `<0.3` -> SELL; else None. | `adapters.py:317-346` |
| MA | `MAStatusAdapter` | `ma_status` | contains `>` -> BUY; contains `<=` -> SELL; else None. | `adapters.py:353-382` |

Important NTF mismatch: `MarketSignalContext.NtfSide` defines `NONE`, `SUPPORT`, and `RESISTANCE` (`shared/interfaces.py:18-22`), and Stage 3 found `DecisionBrain` scores `SUPPORT`. `NTFAdapter` expects `LONG`/`SHORT` (`adapters.py:297-302`). Therefore current `ntf_side="SUPPORT"` with high intensity produces a HOLD signal, not BUY.

## 6. 信号收集流程

Current executable pipeline:

```text
AnalysisService.run_ticker_analysis(symbol)
  -> TickerAnalysisResult(data_pack, decision)
  -> UnifiedResearchPipeline._merge_decision_for_collection()
  -> TradingSignalCollector.collect(collector_pack, timestamp=now)
       LPPL
       CZSC
       Wyckoff
       FSM / DecisionBrain
       Regime
       NTF
       AlphaScore
       MAStatus
  -> List[TradingSignal]
  -> UnifiedBacktestEngine.run(stock_df, signals)
```

Evidence:

- Pipeline collection and timestamp assignment: `src/uniquant/services/research_pipeline.py:128-136`.
- Backtest handoff: `src/uniquant/services/research_pipeline.py:138-157`.
- Decision merge behavior: `src/uniquant/services/research_pipeline.py:210-237`.
- Collector adapter order: `src/uniquant/signal/adapters.py:453-525`.

The collector appends every non-None adapter output. It does not aggregate, suppress, sort by priority, deduplicate, or enforce DecisionBrain risk vetoes.

## 7. 回测时间戳与 T+1 影响

`UnifiedBacktestEngine` indexes signals by `sig.timestamp.strftime("%Y-%m-%d")`; missing timestamps are assigned key `"unknown"` (`unified_engine.py:288-300`). During the daily loop, only signals whose date key equals the K-line date are considered (`unified_engine.py:241-258`).

Execution timing:

1. Signal on date D is collected during Step 3 of the D bar.
2. It becomes a pending order.
3. The order executes at the next trading bar open, D+1, before equity update (`unified_engine.py:173-230`).
4. T+1 sell restriction is checked against `buy_date` (`unified_engine.py:204-228`, `306-315`).

Current pipeline risk:

`UnifiedResearchPipeline.run()` sets every collected signal timestamp to `pd.Timestamp.now()` (`research_pipeline.py:133-136`). For historical `stock_df`, this usually does not match any historical K-line date, so the backtest may produce zero trades even when signals exist. If the K-line data includes today's date, all engine signals are placed on one date only, which still does not represent a historical signal series.

Tests show the intended backtest behavior by manually using a K-line date as timestamp before running the engine (`tests/test_e2e_pipeline.py`). That validates the engine contract, but not the pipeline default timestamp for historical research.

## 8. 信号冲突案例

Current collector can emit conflicting signals for one `data_pack`:

| Case | Example outputs | Current behavior | Risk |
|---|---|---|---|
| Risk veto vs buy signal | DecisionBrain `FORCE_WAIT` -> HOLD, CZSC third-buy -> BUY, MA bull -> BUY | Collector returns all; backtest loops in collection order and may buy if position is zero. | Risk veto may not suppress lower-level BUY. |
| LPPL danger vs trend buy | LPPL `Danger` -> SELL, CZSC third-buy -> BUY, MA bull -> BUY | If not holding, SELL is ignored and later BUY can create pending order. | Structural crash risk can be bypassed in flat state. |
| Alpha failure as sell | Alpha engine failure can set `alpha_score=0.0`; adapter maps `<0.3` to SELL. | Collector emits SELL even if the value means missing/failure rather than bearish alpha. | Missing data becomes bearish executable intent. |
| Regime stressed vs technical buy | Regime `STRESSED` -> HOLD, MA bull -> BUY. | HOLD does not block BUY. | Market stress warning is advisory only. |
| NTF support lost | `ntf_side="SUPPORT"` with high intensity. | Adapter returns HOLD because it expects `LONG`. | A-share policy support signal is not reflected as BUY. |
| Same-day BUY and SELL | Wyckoff distribution -> SELL, MA bull -> BUY, Alpha high -> BUY. | Backtest accepts first feasible action by list order and current position. | Outcome depends on adapter order, not policy. |

The backtest processing order matters: it scans day signals and breaks after the first feasible BUY or SELL (`unified_engine.py:241-258`). Because collector order is LPPL, CZSC, Wyckoff, FSM, Regime, NTF, Alpha, MA (`adapters.py:453-525`), adapter ordering can change execution.

## 9. 当前问题

1. There is no deterministic `TradingSignal` aggregation step in the executable pipeline.
2. `SignalAggregator` is not wired into `UnifiedResearchPipeline`, and it targets `Signal`, not `TradingSignal`.
3. Risk veto signals are represented as HOLD, but HOLD does not block later BUY signals in `UnifiedBacktestEngine`.
4. NTF enum semantics are inconsistent: `SUPPORT`/`RESISTANCE` vs `LONG`/`SHORT`.
5. Missing or failed alpha can become SELL through `alpha_score=0.0`.
6. Signal timestamp defaults to `now()`, which is unsuitable for historical backtests.
7. `TradingSignal` lacks source, priority, blocker/veto flag, expiry, bar date, generated-at, and validity metadata.
8. Confidence is not calibrated across adapters: LPPL uses bubble confidence, CZSC uses stroke count formula, MA is fixed 0.3, alpha uses distance from 0.5.
9. Signal price is recorded but not used for fill, slippage, or stale-signal checks.
10. No current rule prevents BUY at limit-up or SELL at limit-down at signal stage; only backtest execution checks price limits.

## 10. 推荐信号优先级和聚合规则

Recommended deterministic A-share policy for executable `TradingSignal`:

```text
Input: raw adapter outputs + engine_status + current position context

1. Hard blockers:
   - engine_status risk engine failed or data unavailable
   - regime FROZEN
   - LPPL Danger without NTF SUPPORT
   - suspended / zero volume / invalid price / stale timestamp
   - limit-up for BUY, limit-down for SELL

2. Forced exits:
   - LPPL Danger
   - DecisionBrain FORCE_EXIT
   - position risk stop / ATR stop breach

3. Authoritative decision:
   - DecisionBrain BUY/ADD/SELL/HOLD after blockers.

4. Confirming signals:
   - CZSC, Wyckoff, NTF, Alpha, MA, admitted factor composite.
   - These can increase/decrease confidence and position size only if not blocked.

5. Final output:
   - At most one executable TradingSignal per symbol per bar.
   - If blocked: emit HOLD/no-trade with blocker reason, not BUY/SELL.
   - If conflicting and no forced exit: HOLD unless DecisionBrain authorizes action.
```

Concrete priority table:

| Priority | Source | Effect |
|---:|---|---|
| 100 | Suspension/limit/invalid data | Blocks execution side. |
| 90 | Regime FROZEN / risk engine failed | Blocks new BUY; may allow risk-reducing SELL if tradable. |
| 80 | LPPL Danger / DecisionBrain FORCE_EXIT | Force SELL if holding and sellable; otherwise HOLD. |
| 70 | DecisionBrain BUY/ADD/SELL | Primary executable action. |
| 50 | NTF SUPPORT/RESISTANCE | Macro/policy modifier; can confirm or reduce action. |
| 40 | CZSC / Wyckoff | Technical structure confirmation. |
| 30 | Alpha / factor composite | Ranking/strength modifier. |
| 20 | MA status | Low-priority trend filter, not standalone execution. |

Implementation direction:

- Add a `TradingSignalDecision` or `ExecutableSignal` layer with source contributions and blocker reasons.
- Convert adapter outputs into internal scored intents first; then emit one `TradingSignal`.
- Preserve all raw adapter signals in diagnostics for reports.
- Make `DecisionBrain` risk vetoes authoritative for executable BUY suppression.

## 11. 实盘信号校验标准

Before a signal can be submitted to backtest/live execution:

| Check | Requirement |
|---|---|
| Action | Must be one of `BUY`, `SELL`, `HOLD`; unknown action rejected. |
| Symbol | Must be non-empty and match data symbol. |
| Timestamp | Must map to a valid trading bar; no future timestamp for backtest; no stale timestamp for live. |
| Price context | `price`, `pre_close`, and trade-date OHLC must be valid positive numbers. |
| Tradability | Reject BUY on limit-up, SELL on limit-down, and all trades on suspension/zero volume. |
| Position context | SELL requires position; BUY requires no conflicting hard blocker and enough cash after lot rounding. |
| T+1 | SELL must satisfy A-share T+1 unless position was held before the simulation start. |
| Shares | BUY shares must be positive and roundable to board lot size; SELL size capped by position. |
| Confidence | Must be calibrated or source-specific; low-confidence signals should not become executable alone. |
| Source audit | Final signal must record contributing sources, blocked sources, and final rule path. |
| Missing data | Missing/failure values must produce no-signal/HOLD diagnostics, not bearish intent. |

## 12. 阶段结论

The signal layer has a useful bridge from heterogeneous Brain outputs to a shared `TradingSignal`, and the backtest engine has a clear typed input. The main architectural gap is that executable `TradingSignal` collection is additive, not decisional. Multiple contradictory signals are passed downstream, while backtest execution resolves them implicitly by order and position state.

For A-share live-readiness, the project needs a deterministic executable-signal policy: risk vetoes first, forced exits second, DecisionBrain as the primary action source, and other adapters as confidence modifiers rather than independent executable orders.

## 13. 校验清单

| Check | Status |
|---|---|
| 覆盖 LPPL、CZSC、Wyckoff、FSM、Regime、NTF、Alpha、MA | Done in mapping table. |
| 指出多个 BUY/SELL 同时出现的风险 | Done with concrete conflict cases and adapter-order risk. |
| 检查 timestamp 对回测 T+1 的影响 | Done: timestamp date matching, pending next-open execution, T+1 boundary described. |
| 给出确定性聚合规则 | Done: priority table and final single-signal policy proposed. |
| 结论绑定到具体文件/函数 | Done with file and line references. |

## 14. 下一阶段输入

Stage 6 should inspect whether backtest and matching enforce the A-share execution assumptions that the signal layer should depend on:

- `src/uniquant/hands/backtest/unified_engine.py`
- `src/uniquant/hands/backtest/unified_matching_engine.py`
- `src/uniquant/hands/backtest/portfolio_engine.py`
- `src/uniquant/hands/backtest/result.py`
- `src/uniquant/hands/strategies/`
- `src/uniquant/shared/cost_model.py`
- `src/uniquant/shared/limit_checker.py`
- `src/uniquant/shared/price_collar.py`
- `src/uniquant/shared/market_rules.py`
- `tests/test_unified_matching.py`
- `tests/test_t1_constraint_boundary.py`
- `tests/test_matching_engine.py`

Key Stage 6 questions:

1. Do both backtest engines consistently enforce T+1, limit-up/down, suspension, lot size, cash, slippage, commission, stamp duty, and transfer fee?
2. Does signal date D always execute on D+1 open, and is this consistent across single-symbol and portfolio engines?
3. How are multiple same-day signals handled in vectorized matching versus unified engine?
4. Can the execution layer distinguish "risk-reducing sell" from ordinary sell under stressed market conditions?
