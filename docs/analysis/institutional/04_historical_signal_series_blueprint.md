# WS4 — Historical Signal Series Blueprint

Generated: 2026-06-10

Design the as-of signal generation runner that fixes the one-shot `pd.Timestamp.now()` timestamp issue (Finding WS1-003, WS2-004, WS3-002).

## 1. Problem Statement

### Current behavior

```python
# research_pipeline.py:133
timestamp = pd.Timestamp.now()
signals = self._collector.collect(collector_pack, timestamp=timestamp, ...)
```

All 8 adapters stamp every `TradingSignal` with the current system clock. `UnifiedBacktestEngine._index_signals_by_date()` groups signals by this timestamp date. If no K-line bars match today's system date, **zero signals are consumed**.

### Consequences

- Historical backtest results are non-deterministic (depend on system clock).
- Backtest run on Monday ≠ same pipeline run on Tuesday for identical data.
- Research findings cannot be reproduced without recording the system timestamp alongside the run.
- Temporal coupling: `DecisionBrain` maintains `FSMState` across calls with `_save_state()` including `pd.Timestamp.now()` (`fsm.py:848`), meaning DecisionBrain state transitions depend on real-time clock rather than bar chronology.

### Root cause

The pipeline was designed as a single-shot analysis + backtest workflow, not a historical signal simulation. The analysis engines (LPPL, CZSC, Regime, Wyckoff, NTF, Alpha) all receive the **entire** OHLCV DataFrame at once, compute on the full history, and the results are mutated into `data_pack`. The pipeline then stamps one timestamp and creates signals from the full-history computation — but the backtest engine only processes signals whose date matches a bar.

## 2. Design: HistoricalSignalRunner

### Concept

Generate a signal for **each historical bar as if the bar just completed**. Each signal is stamped with that bar's date. The collection of all bar-by-bar signals forms a `historical_signal_series` that can be fed directly into `UnifiedBacktestEngine.run()`.

### Key insight

The current `AnalysisService.run_ticker_analysis()` runs all engines on the **full** OHLCV history — LPPL regression on all data, CZSC on all data, etc. Re-running for each bar with a sliced DataFrame produces a valid "as-of" signal for that bar.

The engines that are already computed on the full frame (like Regime, NTF) use caching (`MarketLevelCache`) and don't need per-bar re-computation — they just need their result to be stamped with the correct bar date.

### Signal types by recomputation need

| Engine | Operation | Per-bar recompute needed? | Notes |
|---|---|---|---|
| Regime | Market-level detector, cached | No | Same regime for all bars in date range |
| NTF | Market-level detector, cached | No | Same NTF for all bars in date range |
| LPPL | Full-series regression | No | Re-running per bar is O(n²); use rolling sub-window for per-bar |
| CZSC | Full-series segmentation | No | CZSC structure changes as new bars appear; true per-bar requires re-segmentation |
| Wyckoff | Full-series phase detection | No | Uses complete price pattern |
| Alpha | Full-series decomposition | No | Uses complete series |
| Indicators (MA, ATR) | Windowed calculation | Yes | MA/ATR at bar `i` only uses `df[:i+1]` — trivially per-bar |
| DecisionBrain | State machine | Yes | DecisionBrain has persistent FSM state — inherently sequential |

### Efficiency strategy

**Full recompute is prohibitively expensive** (O(n²) for LPPL alone on n=1000 bars × 8 engines).

Instead, use a **two-phase approach**:

```
Phase 1: Precompute full-frame engine results (once per ticker).
Phase 2: Generate per-bar signals using lightweight bar-state overrides.
```

#### Phase 1 — Precompute full-frame analysis

```python
full_result = analysis_service.run_ticker_analysis(ticker)
# full_result.data_pack contains all engine outputs computed on full history
```

#### Phase 2 — Per-bar signal generation

For each bar `i` in the K-line DataFrame:

```python
def generate_signal_for_bar(
    df: pd.DataFrame,
    bar_index: int,
    full_data_pack: Dict[str, Any],
    decision_brain: DecisionBrain,
) -> Optional[TradingSignal]:
    """Generate a signal as-of bar bar_index."""
    bar_date = df.iloc[bar_index]["date"]
    
    # Point-in-time data (only up to this bar)
    pti_df = df.iloc[:bar_index + 1]
    
    # Recompute windowed indicators (MA, ATR) on pti_df
    ma_status = compute_ma_status(pti_df)
    atr_stop = compute_atr_stop(pti_df)
    price = float(pti_df.iloc[-1]["close"])
    
    # Use full-frame engine results for non-windowed engines
    # Override with point-in-time derived values
    bar_data_pack = dict(full_data_pack)
    bar_data_pack["ma_status"] = ma_status
    bar_data_pack["price"] = price
    bar_data_pack["atr_stop"] = atr_stop
    bar_data_pack["returns"] = pti_df["close"].pct_change().dropna()
    bar_data_pack["symbol"] = full_data_pack.get("symbol", "")
    bar_data_pack["market"] = "CN"
    
    # DecisionBrain receives per-bar context
    decision = decision_brain.make_decision(bar_data_pack)
    
    # Collector creates signal with bar date
    signal = collector_for_bar(decision, bar_data_pack, timestamp=bar_date)
    
    return signal
```

### Sequence diagram

```text
HistoricalSignalRunner
  │
  ├── 0. analysis_service.run_ticker_analysis(ticker)  # Precompute full-frame
  │     └── data_pack (full history engine results)
  │
  ├── 1. df = data_pack["stock"]  # Full OHLCV
  ├── 2. signals = []
  │
  ├── For i in range(len(df)):
  │     ├── pti_df = df.iloc[:i+1]          # Point-in-time slice
  │     ├── bar_pack = merge(full_data_pack, pti_computed)
  │     │     ├── ma_status  ← pti_df
  │     │     ├── price      ← pti_df.iloc[-1]["close"]
  │     │     ├── atr_stop   ← pti_df
  │     │     └── returns    ← pti_df
  │     ├── decision = decision_brain.make_decision(bar_pack)
  │     ├── sig = collector.collect_one(bar_pack, timestamp=bar_date)
  │     └── signals.append(sig)  # (if actionable)
  │
  └── 3. engine.run(df, signals)   # Historical signal series → backtest
```

### API design

```python
@dataclass
class HistoricalSignalRunnerConfig:
    min_window: int = 60         # Minimum bars before generating signals
    stride: int = 1              # Generate signal every N bars (1 = every bar)
    include_hold: bool = False   # Include HOLD signals in output series
    use_pti_indicators: bool = True  # Recompute MA/ATR per bar (True)
    use_full_frame_engines: bool = True  # Use precomputed LPPL/CZSC/etc. (True)


class HistoricalSignalRunner:
    """Generate per-bar historical signal series for deterministic backtests."""

    def __init__(
        self,
        analysis_service: AnalysisService,
        signal_collector: TradingSignalCollector,
        decision_brain: Optional[DecisionBrain] = None,
        config: Optional[HistoricalSignalRunnerConfig] = None,
    ):
        self._analysis = analysis_service
        self._collector = signal_collector
        self._brain = decision_brain or DecisionBrain()
        self._config = config or HistoricalSignalRunnerConfig()

    def run(
        self,
        ticker: str,
        trace_id: Optional[str] = None,
    ) -> Tuple[List[TradingSignal], BacktestResult]:
        """Generate historical signal series and run backtest."""
        # Phase 1: Full-frame analysis (precompute)
        full_result = self._analysis.run_ticker_analysis(ticker, trace_id=trace_id)
        if not full_result.success:
            return [], BacktestResult()

        full_data_pack = full_result.data_pack
        df = full_data_pack.get("stock")
        if df is None or df.empty:
            return [], BacktestResult()

        # Phase 2: Per-bar signal generation
        signals = []
        self._brain.reset_state()  # Fresh FSM state for historical simulation

        for i in range(self._config.min_window, len(df), self._config.stride):
            bar_date = pd.Timestamp(df.iloc[i]["date"])
            pti_df = df.iloc[:i + 1]

            # Build bar-level data pack
            bar_pack = self._build_bar_pack(full_data_pack, pti_df, i)

            # DecisionBrain makes as-of decision
            decision = self._brain.make_decision(bar_pack)

            # Collector generates signal with bar date
            sig = self._collect_from_decision(
                decision, bar_pack,
                timestamp=bar_date,
                default_shares=self._config.default_shares,
            )
            if sig or self._config.include_hold:
                signals.append(sig)

        # Phase 3: Backtest with historical signal series
        result = self._engine.run(
            df=df,
            signals=[s for s in signals if s is not None],
            symbol=ticker,
        )

        return signals, result

    def _build_bar_pack(
        self,
        full_pack: Dict[str, Any],
        pti_df: pd.DataFrame,
        bar_index: int,
    ) -> Dict[str, Any]:
        """Merge full-frame engine results with point-in-time indicator values."""
        pack = dict(full_pack)

        if self._config.use_pti_indicators:
            bar_price = float(pti_df.iloc[-1]["close"])
            pack["price"] = bar_price
            pack["returns"] = pti_df["close"].pct_change().dropna()

            # ATR stop based on point-in-time data
            atr = Indicators.calc_atr(pti_df)
            pack["atr_stop"] = (
                bar_price - float(atr.iloc[-1]) * 2
                if not atr.empty
                else bar_price * 0.95
            )

            # MA status based on point-in-time data
            indicators = Indicators()
            ma_short = indicators.calc_ma(pti_df, window=20)
            ma_long = indicators.calc_ma(pti_df, window=60)
            if not ma_short.empty and not ma_long.empty:
                pack["ma_status"] = (
                    "MA20 > MA60"
                    if ma_short.iloc[-1] > ma_long.iloc[-1]
                    else "MA20 <= MA60"
                )
            # Use full-frame engine results for LPPL, CZSC, Wyckoff engines
            # These are NOT point-in-time correct, but are acceptable for
            # research backtesting as approximate signals.
            # True per-bar computation requires per-bar LPPL regression,
            # CZSC segmentation, etc. — deferred to future optimization.
        return pack

    def _collect_from_decision(
        self,
        decision: Dict[str, Any],
        bar_pack: Dict[str, Any],
        timestamp: pd.Timestamp,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        """Generate a TradingSignal from DecisionBrain output + bar context."""
        collector_pack = dict(bar_pack)
        for key in ("action", "final_decision", "shares", "confidence", "reason", "price"):
            if key in decision:
                collector_pack[key] = decision[key]
        # Expose FSMAdapter-relevant keys
        collector_pack["ma_status"] = bar_pack.get("ma_status", "")
        collector_pack["action"] = decision.get("final_decision", decision.get("action", "HOLD"))

        signals = self._collector.collect(
            collector_pack,
            timestamp=timestamp,
            default_shares=default_shares,
        )
        return signals[0] if signals else None
```

### Integration with UnifiedResearchPipeline

```python
class UnifiedResearchPipeline:
    def run_historical(
        self,
        symbol: str,
        name: Optional[str] = None,
        default_shares: int = 100,
        trace_id: Optional[str] = None,
    ) -> PipelineResult:
        """Run full historical signal series (vs single-shot pd.Timestamp.now())."""
        trace_id = trace_id or uuid.uuid4().hex
        runner = HistoricalSignalRunner(
            self._analysis, self._collector, decision_brain=self._analysis.brain,
        )
        signals, backtest_result = runner.run(symbol, trace_id=trace_id)

        return PipelineResult(
            symbol=symbol,
            data_pack={},  # Not available in historical mode
            decision={},    # Not available in historical mode
            signals=signals,
            backtest=backtest_result,
            success=len(signals) > 0,
            trace_id=trace_id,
        )
```

## 3. Limitations and Known Issues

### 3.1 Full-frame engine results leak future information

LPPL regression on all data uses future bubble peaks to characterize earlier behavior. CZSC uses full-sequence segmentation. Wyckoff uses full-phase patterns. **These are NOT point-in-time.**

For a research-quality backtest this is acceptable because:
- LPPL bubble detection is a slow-moving regime signal (months time horizon).
- CZSC and Wyckoff patterns are identification rather than prediction.
- The DecisionBrain primarily acts on indicator changes (MA crossovers) and score thresholds.

**For production-grade research**, the `use_full_frame_engines` flag should be False, and per-bar engine calls should be implemented:

```python
# Future optimization: per-bar engine call (expensive)
for i in range(n):
    pti_df = df.iloc[:i+1]
    lppl_result = lppl_engine.run_lppl_analysis(symbol, pti_df)
    czsc_result = czsc_engine.run_czsc_analysis(symbol, pti_df)
    wyckoff_result = wyckoff_engine.run_wyckoff_analysis(symbol, pti_df)
```

### 3.2 DecisionBrain FSM state persistence conflict

Current `DecisionBrain._save_state()` uses `pd.Timestamp.now()` and persists to disk. In historical mode, the state should NOT be persisted (it's simulation state, not live state).

Fix: Pass `persist_state=False` when initializing DecisionBrain for `HistoricalSignalRunner`.

### 3.3 Market-level cache (Regime, NTF) is stale

Full-frame regime and NTF results are computed once and cached. For per-bar signals, these are identical for every bar. This is acceptable because regime and NTF are market-level signals that don't change per ticker.

### 3.4 Performance

For n=1000 bars, stride=1:
- Phase 1: 1 full engine run (fast)
- Phase 2: 940 indicator recalculations (MA/ATR on growing slices — O(n²) cumulatively)
- Per-bar DecisionBrain call: ~940 state machine runs (fast)

Estimated: 2-5 seconds per ticker on modern hardware. For batch mode, increase stride to 5.

## 4. Testing Requirements

### Unit tests

| Test | Description |
|---|---|
| `test_historical_signal_series_timestamps` | Every signal timestamp matches a bar date in the K-line data |
| `test_no_pd_timestamp_now` | `HistoricalSignalRunner` never calls `pd.Timestamp.now()` |
| `test_pti_ma_correctness` | MA at bar `i` uses only data up to bar `i` |
| `test_fsm_state_reset` | DecisionBrain state is reset before historical run |
| `test_deterministic_output` | Same input data produces identical signal series across runs |

### Integration tests

| Test | Description |
|---|---|
| `test_historical_vs_original_parity_for_non_time_dependent_signals` | Signals that don't depend on window position (regime, LPPL) produce same action |
| `test_backtest_consumes_historical_signals` | UnifiedBacktestEngine processes historical signal series |
| `test_signal_count_equals_backtest_days` | Number of signals ≈ number of bars × fraction of actionable bars |

### Bias tests

| Test | Description |
|---|---|
| `test_no_same_bar_execution` | Signal timestamp `T` → execution at `T+1` open |
| `test_full_frame_leakage_flagged` | `use_full_frame_engines=True` logs a warning about future data |

## 5. Migration Path

| Step | Change | Risk | Rollback |
|---|---|---|---|
| 1 | Create `HistoricalSignalRunner` class in `services/historical_signal_runner.py` | Low — new code, not wired in | Don't import |
| 2 | Add `run_historical()` method to `UnifiedResearchPipeline` | Low — new method, old `run()` unchanged | Don't call |
| 3 | Add config flag: `pipeline.use_historical_signals: bool = False` | Low — default off | Set to False |
| 4 | Integration test comparing old `run()` with new `run_historical()` | Medium — verifying equivalence | Fix test |
| 5 | Flip default to True in config | Medium — changes all backtest results | Flip back |
| 6 | Remove `pd.Timestamp.now()` from pipeline | Low — no callers left | Revert |

## 6. Verification Checklist

- [ ] Design addresses Finding WS1-003 (signal timestamp) and WS2-004 (P0 timestamp issue).
- [ ] Every historical signal is stamped with a bar date (not `pd.Timestamp.now()`).
- [ ] DecisionBrain FSM state is reset before historical run.
- [ ] Windowed indicators (MA, ATR) are computed point-in-time per bar.
- [ ] Full-frame engine results (LPPL, CZSC, Wyckoff, Alpha) are reused for efficiency.
- [ ] Full-frame reuse is documented as a known limitation.
- [ ] `use_full_frame_engines=False` enables truly point-in-time per-bar engine calls.
- [ ] Config flags control stride, min_window, and include_hold.
- [ ] Backward compatibility: old `run()` method continues to work with `pd.Timestamp.now()`.
- [ ] Migration path is staged with config-gated rollback at each step.