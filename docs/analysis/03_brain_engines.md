# Stage 3 - Brain Engines

Generated: 2026-06-09

Scope: Brain-layer engines and their service orchestration through `AnalysisService.run_ticker_analysis()`. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0-2 artifacts.
2. Trace `AnalysisService._run_engines()` as the current main engine path.
3. Inspect service adapters under `src/uniquant/services/analysis/`.
4. Inspect core brain implementations under `src/uniquant/brain/`.
5. Build engine input/output and `data_pack` field-source tables.
6. Analyze `DecisionBrain` veto, scoring, state, and action behavior.
7. Identify A-share suitability and signal conflict risks.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` | Architecture baseline. |
| `docs/analysis/01_services_orchestration.md` | Services orchestration baseline. |
| `docs/analysis/02_data_system.md` | Data system baseline. |
| `src/uniquant/services/analysis_service_v2.py` | Current main brain orchestration path. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy engine factory. |
| `src/uniquant/services/analysis/fsm_analysis_engine.py` | FSM service adapter. |
| `src/uniquant/services/analysis/czsc_analysis_engine.py` | CZSC service adapter. |
| `src/uniquant/services/analysis/lppl_analysis_engine.py` | LPPL service adapter. |
| `src/uniquant/services/analysis/ntf_analysis_engine.py` | NTF service adapter. |
| `src/uniquant/services/analysis/regime_analysis_engine.py` | Regime service adapter. |
| `src/uniquant/services/analysis/wyckoff_analysis_engine.py` | Wyckoff service adapter. |
| `src/uniquant/brain/fsm/fsm.py` | `FSM` and `DecisionBrain`. |
| `src/uniquant/brain/czsc/czsc_engine.py` | CZSC engine. |
| `src/uniquant/brain/lppl/engine.py` | LPPL engine. |
| `src/uniquant/brain/ntf/ntf_engine.py` | National Team Factor engine. |
| `src/uniquant/brain/regime/regime_detector.py` | Regime detector. |
| `src/uniquant/brain/wyckoff/engine.py` | Wyckoff engine. |
| `src/uniquant/brain/alpha_decoupler/alpha_decoupler.py` | Alpha relative-strength engine. |
| `src/uniquant/brain/indicators/indicators.py` | Shared technical indicators. |
| Relevant tests under `tests/test_analysis_engines.py`, `tests/test_czsc_engine.py`, `tests/test_regime_detector.py`, `tests/test_ntf_engine.py`, `tests/test_alpha_decoupler.py`, `tests/test_wyckoff.py`, and regression tests. |

## 3. 引擎清单

| Engine | Current main-chain call | Business meaning | Core input | Main output into `data_pack` |
|---|---|---|---|---|
| Regime | `AnalysisService._run_regime()` | Market liquidity/stress regime using HS300 entropy and turnover Z-score. | HS300 index frame from lake. | `regime`, `entropy`, `turnover_z`, `engine_status.regime`. |
| LPPL | `AnalysisService._run_lppl()` | Bubble/crash structural risk detection. | Target stock OHLC close series. | `risk`, `bubble_confidence`, `engine_status.lppl`. |
| NTF | `AnalysisService._run_ntf()` | National-team/policy intervention proxy using 510300 ETF volume pulse. | ETF history via injected `DataFetcher`. | `ntf_side`, `ntf_intensity`, `ntf_action`. |
| CZSC | `AnalysisService._run_czsc()` | Chan-theory structure, especially third-buy signal and stroke count. | Target stock OHLCV frame. | `is_3rd_buy`, `bi_count`. |
| Wyckoff | `AnalysisService._run_wyckoff()` | Accumulation/distribution phase and spring/UTAD structure. | Target stock OHLCV frame. | `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad`. |
| Alpha | `AnalysisService._run_alpha()` | Relative strength versus benchmark and sector/index. | Target stock, HS300, CSI500 frames. | `alpha_score`. |
| Indicators | `AnalysisService._calculate_derived()` | Derived trend, price, ATR stop, returns. | Target stock OHLC frame. | `ma_status`, `price`, `atr_stop`, `returns`. |
| FSM / DecisionBrain | `AnalysisService._make_decision()` | Veto-scoring state machine and final trading action. | Full `data_pack`. | `decision` object returned in `TickerAnalysisResult`. |

Evidence: `src/uniquant/services/analysis_service_v2.py:308-317`, `326-526`.

## 4. 输入输出字段表

| Engine | Required/expected fields | Output fields | Failure defaults in main chain |
|---|---|---|---|
| Regime | Lake index `000300.SH`/HS300 with `close`, `volume`. | `regime`, `entropy`, `turnover_z`. | Missing HS300 -> `regime="UNKNOWN"`, `entropy=0.0`, `turnover_z=0.0`, status `DATA_UNAVAILABLE`; exception -> status `ENGINE_FAILED`. |
| LPPL | `data_pack["stock"]`, especially `close`. | `risk` from `risk_level`, `bubble_confidence`. | Invalid/missing result or exception -> `risk="ENGINE_FAILED"`, `bubble_confidence=1.0`. |
| NTF | `data_service.fetcher`, ETF symbol `510300.SH`, recent 3 months. | `ntf_side`, `ntf_intensity`, `ntf_action`. | Exception -> `ntf_side="NONE"`, `ntf_intensity=0.0`. |
| CZSC | `stock` with `date`, `open`, `close`, `high`, `low`, volume/vol. | `is_3rd_buy`, `bi_count`. | Exception -> `is_3rd_buy=False`, `bi_count=0`. |
| Wyckoff | `stock` with OHLCV. | `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad`. | Exception -> `wyckoff_phase="unknown"`, `wyckoff_confidence=0.0`. |
| Alpha | `stock`, lake `000300.SH` index, lake `000905.SH` index. | `alpha_score`. | Missing stock/benchmark or exception -> `alpha_score=0.0`. |
| Indicators | `stock` with `close`, `high`, `low`. | `ma_status`, `price`, `atr_stop`, `returns`. | Exceptions are logged; fields may be absent or partially present. |
| DecisionBrain | `MarketSignalContext.from_dict(data_pack)` fields. | `action`, `reason`, `final_decision`, `final_score`, blockers/triggers, shares, state. | Decorator default can return `{"action": "ERROR", "reason": "决策执行失败"}` if unhandled. |

Evidence:

- Regime path: `src/uniquant/services/analysis_service_v2.py:326-369`; core detector summary returns `regime`, `entropy`, `turnover_z`, `is_safe` at `src/uniquant/brain/regime/regime_detector.py:191-216`.
- LPPL path: `src/uniquant/services/analysis_service_v2.py:371-396`; LPPL risk output at `src/uniquant/brain/lppl/engine.py:988-1011`.
- NTF path: `src/uniquant/services/analysis_service_v2.py:398-428`; NTF output at `src/uniquant/brain/ntf/ntf_engine.py:48-113`.
- CZSC path: `src/uniquant/services/analysis_service_v2.py:430-441`; CZSC output at `src/uniquant/brain/czsc/czsc_engine.py:415-432`, `472-510`.
- Wyckoff path: `src/uniquant/services/analysis_service_v2.py:443-456`; simplified scan output at `src/uniquant/brain/wyckoff/engine.py:1388-1457`.
- Alpha path: `src/uniquant/services/analysis_service_v2.py:458-480`; alpha score at `src/uniquant/brain/alpha_decoupler/alpha_decoupler.py:199-270`.
- Derived fields: `src/uniquant/services/analysis_service_v2.py:482-515`.

## 5. `data_pack` 字段来源表

| Field | Producer | Consumer |
|---|---|---|
| `stock` | `DataService.fetch_for_brain()` | All price-based engines, derived indicators, pipeline backtest. |
| `bench` | `DataService.fetch_for_brain()` | Not directly used by current `_run_alpha()`; alpha rereads lake indices. |
| `etf` | `DataService.fetch_for_brain()` | Not directly used by current `_run_ntf()`; NTF fetches ETF through fetcher. |
| `trace_id` | `AnalysisService._attach_trace_id()` | Result tracing and status metadata. |
| `engine_status` / `engine_errors` | `_mark_engine_status()` in selected engine paths | `DecisionBrain._risk_engine_blockers()`, diagnostics. |
| `regime` | `_run_regime()` | `DecisionBrain`, `RegimeAdapter`. |
| `entropy`, `turnover_z` | `_run_regime()` | Diagnostics/UI/context. |
| `risk`, `bubble_confidence` | `_run_lppl()` | `DecisionBrain`, `LPPLAdapter`. |
| `ntf_side`, `ntf_intensity`, `ntf_action` | `_run_ntf()` | `DecisionBrain`, `NTFAdapter`. |
| `is_3rd_buy`, `bi_count` | `_run_czsc()` | `DecisionBrain`, `CZSCAdapter`. |
| `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad` | `_run_wyckoff()` | `WyckoffAdapter`; not directly used by `DecisionBrain` scoring. |
| `alpha_score` | `_run_alpha()` | `DecisionBrain`, `AlphaScoreAdapter`. |
| `ma_status`, `price`, `atr_stop`, `returns` | `_calculate_derived()` | `DecisionBrain`, `MAStatusAdapter`, position sizing/risk. |
| `symbol`, `market` | `_run_engines()` | `DecisionBrain`, signal adapters, pipeline. |

## 6. DecisionBrain 决策流程

`DecisionBrain.make_decision()` converts dict input into `MarketSignalContext` (`src/uniquant/brain/fsm/fsm.py:548-564`).

Flow:

```text
data_pack -> MarketSignalContext
  -> reset FSM state if symbol changed
  -> veto checks
       FROZEN -> FORCE_WAIT
       risk engine unavailable -> FORCE_WAIT
       LPPL Danger without NTF SUPPORT -> FORCE_EXIT
  -> circuit-break check using price/pre_close
  -> score:
       CZSC third-buy
       MA20 > MA60
       alpha_score threshold
       NTF SUPPORT
  -> sell conditions:
       LPPL Danger
       MA reversal
       weak alpha
       FROZEN/STRESSED regime
       limit-down block handling
  -> target FSM state transition
  -> buy blockers:
       LPPL Danger
       market frozen
       risk engine blockers
       missing/invalid stop loss
       weak alpha
       limit-up/down constraints
  -> BUY/ADD/SELL/HOLD/STAY_CURRENT_STATE/CIRCUIT_BREAK
```

Evidence:

- Response fields: `src/uniquant/brain/fsm/fsm.py:230-256`.
- Veto and risk blockers: `src/uniquant/brain/fsm/fsm.py:258-315`.
- Scoring: `src/uniquant/brain/fsm/fsm.py:317-328`.
- Sell conditions: `src/uniquant/brain/fsm/fsm.py:330-366`.
- Buy blockers and limit checks: `src/uniquant/brain/fsm/fsm.py:385-417`.
- Buy execution and position sizing: `src/uniquant/brain/fsm/fsm.py:419-457`.
- Main state logic: `src/uniquant/brain/fsm/fsm.py:548-659`.

Important: `MarketSignalContext.from_dict()` defaults `pre_close` to `0.0` (`src/uniquant/shared/interfaces.py:79-100`). `AnalysisService._calculate_derived()` sets `price` but does not set `pre_close` (`src/uniquant/services/analysis_service_v2.py:503-512`). As a result, DecisionBrain limit-up/limit-down and circuit-break checks may be inactive in the current main chain unless another producer supplies `pre_close`.

## 7. A 股适用性评价

| Engine | A-share suitability | Notes |
|---|---|---|
| Regime | High as market risk filter if HS300 data is fresh. | Uses entropy and turnover/volume; useful for liquidity/stress veto. Missing HS300 becomes `UNKNOWN`, which DecisionBrain blocks via risk blockers. |
| LPPL | Useful as structural top/crash risk filter, not a standalone buy signal. | Current failure default is intentionally conservative through `ENGINE_FAILED`; DecisionBrain treats failed risk engine as blocker. |
| NTF | A-share specific policy/liquidity context. | Uses 510300 ETF proxy and SUPPORT/RESISTANCE semantics. Current main chain fetches data directly through fetcher instead of using `data_pack["etf"]`. |
| CZSC | A-share technical signal fit is high because Chan theory is commonly used in this market. | Third-buy signal contributes to score and can emit BUY via adapter. Requires enough valid bars. |
| Wyckoff | Useful for accumulation/distribution interpretation. | Current DecisionBrain does not score Wyckoff directly; it only influences signal collector through adapter. |
| Alpha | Useful for relative strength and beta/sector decoupling. | Missing benchmark maps to `alpha_score=0.0`, which can be a sell signal in signal adapter; this needs correction/verification. |
| Indicators | Necessary support layer. | MA trend, ATR stop, and returns drive scoring, stop-loss blockers, and position sizing. |
| DecisionBrain | Strong A-share awareness via state, risk vetoes, limit checks, T+1 delegated to backtest. | In current data path `pre_close` may not be present, reducing price-limit/circuit-break effectiveness at decision time. |

## 8. 信号冲突风险

Current pipeline can produce multiple signals from the same analysis output:

- `DecisionBrain` can return `FORCE_WAIT`, `FORCE_EXIT`, `BUY`, `ADD`, `SELL`, `STAY_CURRENT_STATE`, or `CIRCUIT_BREAK`.
- `TradingSignalCollector` separately adapts LPPL, CZSC, Wyckoff, FSM, Regime, NTF, AlphaScore, and MA status.
- Wyckoff/MA/Alpha adapters can produce BUY/SELL even when DecisionBrain is HOLD-like.

Concrete conflict examples:

1. `risk="ENGINE_FAILED"` causes `DecisionBrain` to `FORCE_WAIT`, but `LPPLAdapter` sees neither `Danger` nor `Warning` and returns HOLD if confidence is high enough.
2. `_run_alpha()` failure sets `alpha_score=0.0`; `DecisionBrain` may block buy or sell on weak alpha, and `AlphaScoreAdapter` maps `<0.3` to SELL.
3. `ma_status="MA20 <= MA60"` can trigger DecisionBrain sell conditions and separately produce a SELL from `MAStatusAdapter`.
4. Wyckoff accumulation/spring can emit BUY through `WyckoffAdapter`, while Regime/LPPL/DecisionBrain may block risk.

Stage 5 must inspect signal aggregation and decide whether DecisionBrain should be authoritative, whether risk vetoes should suppress other adapter signals, and whether missing engine data should emit no signal.

## 9. 关键发现

1. The actual main chain does not simply call every service adapter. `AnalysisService` directly implements Regime, NTF, Alpha, and derived-indicator logic while using factory-backed LPPL, CZSC, Wyckoff, and DecisionBrain.
2. `data_pack` is the effective brain bus; its schema is still implicit and partly duplicated with `MarketSignalContext`.
3. Regime and LPPL failures are treated as critical risk blockers by `DecisionBrain`, which is conservative.
4. Alpha failure is not conservative in the signal layer because `alpha_score=0.0` can become SELL.
5. Wyckoff is currently signal-layer relevant but not DecisionBrain-score relevant.
6. `pre_close` is part of `MarketSignalContext` but not set by the main derived-indicator path, so DecisionBrain-level A-share limit/circuit checks may not fire.
7. State persistence in `DecisionBrain` writes to `data/state/fsm_state.json` unless disabled or overridden (`src/uniquant/brain/fsm/fsm.py:689-750`), so multi-symbol or test runs must manage state carefully.

## 10. 风险与改进建议

| Priority | Risk | Recommendation |
|---|---|---|
| High | `alpha_score=0.0` on missing benchmark/failure can become SELL. | Treat missing alpha as unavailable/neutral in adapters, or add `engine_status.alpha` and suppress alpha signal on failure. |
| High | `pre_close` not populated in main `data_pack`. | Populate from latest stock row or prior close in `_calculate_derived()` so DecisionBrain limit/circuit logic works. |
| High | Signal conflict policy is implicit. | Stage 5 should define authority/priority, likely making DecisionBrain/risk vetoes suppress lower-level technical signals. |
| Medium | `bench` and `etf` from `fetch_for_brain()` are not reused by current Alpha/NTF paths. | Reuse `data_pack["bench"]`/`["etf"]` or document why engines reread/refetch. |
| Medium | Wyckoff is not included in DecisionBrain scoring despite being collected as signal. | Decide whether Wyckoff should remain advisory or contribute to scoring. |
| Medium | Service adapter fallback outputs can differ from main-chain defaults. | Keep main-chain field contract tests to avoid drift. |
| Low | FSM state persistence can leak context across runs if not reset. | Use per-symbol state files or disable persistence for batch research/backtests. |

## 11. 校验清单

- [x] Covered FSM, CZSC, LPPL, NTF, Regime, Wyckoff, Alpha, and Indicators.
- [x] Explained each engine business meaning.
- [x] Built input/output and `data_pack` field-source tables.
- [x] Explained `DecisionBrain` decision flow.
- [x] Evaluated A-share suitability.
- [x] Identified signal conflict risks.
- [x] Explained failure defaults and trade/risk implications.
- [x] Bound conclusions to concrete files, functions, and tests.
- [x] Did not modify source code.
- [x] Did not claim tests passed; no test command was run.

## 12. 下一阶段输入

Stage 4 should analyze the factor system with special care because the working tree currently deletes many `brain/factors/auto_mined` files. Start with:

- `src/uniquant/brain/factors/__init__.py`
- `src/uniquant/brain/factors/custom_factors.py`
- `src/uniquant/brain/factors/registry.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/composer.py`
- `src/uniquant/brain/factors/neutralizer.py`
- `src/uniquant/brain/factors/financial_bridge.py`
- `src/uniquant/brain/factors/walk_forward_pipeline.py`
- `experiments/run_factor_ic_evaluation.py`
- `experiments/run_full_factor_matrix_eval.py`
- `experiments/run_real_data_ic.py`
- `tests/test_factor_analyzer.py`
- `tests/test_factor_registry.py`
- `tests/test_custom_factors.py`
- `tests/test_factor_div_zero_defense.py`
- `tests/test_walk_forward_pipeline.py`

## 13. 阶段结论

The brain layer is broad and mostly functional, but its operational contract is the mutable `data_pack` assembled by `AnalysisService`. The risk filters are conservative for Regime/LPPL failures, but Alpha and technical adapter outputs can still become executable signals without a global arbitration policy. Before trusting live or backtest decisions, Stage 5 and Stage 6 must verify signal priority, missing-engine semantics, timestamp alignment, and A-share price-limit behavior.
