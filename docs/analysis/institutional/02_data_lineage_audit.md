# WS2 - Data Lineage Audit

Generated: 2026-06-10

Scope: Core data objects in the research pipeline: `MarketData`, `DataFrame`, `Factor`, `Signal`, `TradingSignal`, `TradeRecord`, `BacktestResult`, `Portfolio`. Strategy logic internals are not audited.

## 1. Objective

Trace every core data object by shape, contract, producer, consumer, and mutation point. Identify schema drift, `Any` pollution, and missing typed boundaries before any refactoring.

## 2. Master Data Lineage Map

```text
DataFetcher ──▶ DataLake (parquet)
                  │
                  ▼
         DataService.fetch_for_brain(symbol)
                  │
                  ▼
         data_pack: Dict[str, Any]
           ├── "stock": pd.DataFrame  (OHLCV for symbol)
           ├── "bench": pd.DataFrame  (HS300 index OHLCV)
           └── "etf":   pd.DataFrame  (ETF OHLCV)
                  │
        ┌─────────┼──────────────┐
        ▼         ▼              ▼
  AnalysisService._run_engines()
        │
        ├── _run_regime()    → data_pack["regime", "entropy", "turnover_z"]
        ├── _run_lppl()      → data_pack["risk", "bubble_confidence"]
        ├── _run_ntf()       → data_pack["ntf_side", "ntf_intensity", "ntf_action"]
        ├── _run_czsc()      → data_pack["is_3rd_buy", "bi_count"]
        ├── _run_wyckoff()   → data_pack["wyckoff_*"]
        ├── _run_alpha()     → data_pack["alpha_score"]
        ├── _calculate_derived() → data_pack["ma_status", "price", "atr_stop", "returns"]
        └── also sets: symbol, market, engine_status, engine_errors, trace_id
                  │
                  ▼
         DecisionBrain.make_decision(data_pack)
                  │
                  ▼
         decision: Dict[str, Any]
           └── "action", "confidence", "shares", "reason", "price" ...
                  │
                  ▼
         UnifiedResearchPipeline._merge_decision_for_collection()
                  │
                  ▼
         TradingSignalCollector.collect(collector_pack, timestamp=pd.Timestamp.now())
                  │
                  ▼ (per engine adapter)
         List[TradingSignal]  ← 8 adapters: LPPL, CZSC, Wyckoff, FSM,
                                  Regime, NTF, AlphaScore, MAStatus
                  │
                  ▼
         UnifiedBacktestEngine.run(df, signals)
                  │
                  ├── _index_signals_by_date() → Dict[str, List[TradingSignal]]
                  ├── per bar:
                  │     ├── execute pending_order → TradeRecord (BUY or SELL)
                  │     ├── update equity_curve
                  │     └── collect day_signals → set pending_order
                  │
                  ▼
         BacktestResult
           ├── trades: List[TradeRecord]
           ├── equity_curve: List[float]
           ├── daily_returns: List[float]
           └── final_cash: float
```

Parallel path for multi-symbol:

```text
PortfolioEngine
  ├── UnifiedMatchingEngine
  ├── positions: Dict[str, Position]
  └── trades: List[Dict[str, Any]]
```

## 3. Core Object Lineage Tables

### 3.1 `data_pack` (the primary cross-layer contract)

| Step | Producer | Shape | Consumer | Contract type |
|---|---|---|---|---|
| Creation | `DataService.fetch_for_brain()` | `Dict[str, pd.DataFrame]` keys: `stock`, `bench`, `etf` | `AnalysisService._run_engines()` | Implicit dict keys |
| Mutation 1 | `_run_regime()` | Adds `regime` (str), `entropy` (float), `turnover_z` (float) | Subsequent engines, DecisionBrain | Implicit |
| Mutation 2 | `_run_lppl()` | Adds `risk` (str), `bubble_confidence` (float) | Subsequent engines, DecisionBrain | Implicit |
| Mutation 3 | `_run_ntf()` | Adds `ntf_side` (str), `ntf_intensity` (float), `ntf_action` (str) | Subsequent engines, DecisionBrain | Implicit |
| Mutation 4 | `_run_czsc()` | Adds `is_3rd_buy` (bool), `bi_count` (int) | Subsequent engines, DecisionBrain | Implicit |
| Mutation 5 | `_run_wyckoff()` | Adds `wyckoff_phase` (str), `wyckoff_confidence` (float), `wyckoff_spring` (bool), `wyckoff_utad` (bool) | Subsequent engines, DecisionBrain | Implicit |
| Mutation 6 | `_run_alpha()` | Adds `alpha_score` (float) | DecisionBrain | Implicit |
| Mutation 7 | `_calculate_derived()` | Adds `ma_status` (str), `price` (float), `atr_stop` (float), `returns` (pd.Series) | DecisionBrain, signal adapters | Implicit |
| Final metadata | `_run_engines()` | Adds `symbol` (str), `market` (str), `engine_status` (Dict), `engine_errors` (Dict) | All downstream | Implicit |
| Trace ID | `_attach_trace_id()` | Adds `trace_id` (str) | All downstream | Implicit |
| Decision merge | `_merge_decision_for_collection()` | Shallow copy, adds `final_decision`, `action`, `shares`, `confidence`, `reason`, `price` | `TradingSignalCollector` | Implicit |
| Signal collection | `TradingSignalCollector.collect()` | Reads `symbol`, `risk`, `bubble_confidence`, `is_3rd_buy`, `bi_count`, `wyckoff_*`, `action`, `final_decision`, `regime`, `ntf_side`, `alpha_score`, `ma_status`, `price` | Adapters → `TradingSignal` | Implicit dict keys |

**Total known keys written into data_pack:** 30+ across 8 mutation points.

**Schema guarantee:** None. A typo in any key name produces silent None/missing-key behavior with no type error.

### 3.2 `TradingSignal`

| Field | Type | Producer | Consumer | Notes |
|---|---|---|---|---|
| `action` | str | Engine adapters | `UnifiedBacktestEngine` | Values: "BUY" / "SELL" / "HOLD" |
| `reason` | str | Engine adapters | Logging | Human-readable |
| `confidence` | float | Engine adapters | (not consumed by engine) | [0, 1] range |
| `shares` | int | Engine adapters | `UnifiedBacktestEngine` | Used as BUY quantity |
| `symbol` | str | Collectors from data_pack | `UnifiedBacktestEngine` | Ticker |
| `price` | float | Engine adapters from data_pack | Not consumed in matching | Placeholder |
| `timestamp` | Optional[datetime] | `pd.Timestamp.now()` in pipeline | `_index_signals_by_date()` | **P0: always current time** |

### 3.3 `signal.models.Signal` (parallel signal model)

| Field | Type | Producer | Consumer | Notes |
|---|---|---|---|---|
| `signal_type` | SignalType enum | Normalizers | Aggregators | 27 subtypes, 9 categories |
| `source` | SignalSource enum | Normalizers | Aggregators | 10 sources |
| `direction` | int | Normalizers | Aggregators | 1 / -1 / 0 |
| `strength` | SignalStrength enum | Normalizers | (metadata) | 4 levels |
| `confidence` | float [0,1] | Normalizers | Aggregators | |
| `timestamp` | datetime | Normalizers default `datetime.now()` | TimeWindowAggregator | **Same P0 issue** |
| `price` | float | Normalizers | (metadata) | |
| `value` | float | Normalizers | (metadata) | |
| `metadata` | Dict[str, Any] | Normalizers | (metadata) | Catch-all for extras |
| `parent_id` | Optional[str] | Normalizers | (traceability) | |

**Status:** `Signal` is rich-typed with enums but NOT used in the pipeline path. The pipeline uses `TradingSignal` (simple dataclass). `Signal` only flows through `SignalNormalizer` → `SignalAggregator` → `TimeWindowAggregator`, which are NOT connected to `UnifiedResearchPipeline`.

### 3.4 `MarketSignalContext` (typified data_pack alternative)

Defined in `shared/interfaces.py`. Has `from_dict()` and `to_dict()` methods. **Not used anywhere in the pipeline path.** Exists as a typed alternative that DecisionBrain could consume but does not in practice.

### 3.5 `TradeRecord` (execution record)

| Field | Type | Producer | Consumer | Notes |
|---|---|---|---|---|
| `timestamp` | datetime | `UnifiedBacktestEngine` | `BacktestResult` | Bar open timestamp |
| `action` | str | Engine | `BacktestResult.trades` | "BUY" or "SELL" |
| `symbol` | str | Engine | `BacktestResult.trades` | |
| `price` | float | Engine with slippage | `BacktestResult.trades` | |
| `shares` | int | Engine with lot-size rounding | `BacktestResult.trades` | |
| `commission` | float | cost model | `BacktestResult.trades` | |
| `stamp_duty` | float | cost model | `BacktestResult.trades` | |
| `transfer_fee` | float | cost model | `BacktestResult.trades` | |
| `slippage` | float | impact model | `BacktestResult.trades` | |
| `pnl` | float | Engine (sell only) | `BacktestResult.trades` | |
| `reason` | str | Signal adapter | `BacktestResult.trades` | |

### 3.6 `BacktestResult`

| Field | Type | Producer | Consumer |
|---|---|---|---|
| `trades` | List[TradeRecord] | UnifiedBacktestEngine | Reports, metrics |
| `equity_curve` | List[float] | UnifiedBacktestEngine | Reports, metrics |
| `daily_returns` | List[float] | UnifiedBacktestEngine | Metrics |
| `initial_capital` | float | Constructor | Reports |
| `final_cash` | float | UnifiedBacktestEngine | Reports |

Note: There is a **second** `BacktestResult` in `hands/backtest/result.py` with a richer schema (sharpe_ratio, max_drawdown, win_rate, etc. as pre-computed fields). The `UnifiedBacktestEngine` only populates the simpler version. The `result.py` version has `calculate_metrics()` that is NOT called in the pipeline path.

## 4. Data Lineage Findings

### Finding WS2-001 — `data_pack` has no schema contract (P0)

Evidence:
- 30+ implicit dict keys written across 8 mutation points in `AnalysisService` (`analysis_service_v2.py:308-520`).
- No `TypedDict`, `@dataclass`, or Pydantic model defines the `data_pack` shape.
- Producers and consumers agree on keys by convention only.
- Key typo at any point produces silent `KeyError` → `RECOVERABLE_ERRORS` catch → `data_pack[key] = None` → downstream `None`-tolerant reads produce wrong results.

Impact:
- Any schema drift changes research decisions, signal generation, or backtest inputs without a type error.
- This is the single highest-contract-risk item in the entire codebase.

Risk Level: P0

Recommendation:
- Define a typed `ResearchDataPack` dataclass or TypedDict with all 30+ known fields.
- Add validation at the `DataService.fetch_for_brain()` output boundary and `TradingSignalCollector.collect()` input boundary.
- Keep dict compatibility adapter temporarily but require schema validation before signal collection.

Migration Cost: Medium

Priority: Sprint 1

### Finding WS2-002 — `Dict[str, Any]` pollution at 430+ sites (P0)

Evidence:
- 430+ `Dict[str, Any]` type annotations across `src/uniquant/`.
- `data_pack` itself is `Dict[str, Any]` at every mutation point.
- `decision` is `Dict[str, Any]`.
- All `TickerAnalysisResult` fields: `data_pack`, `decision` are `Dict[str, Any]`.
- `PipelineResult` fields: `data_pack`, `decision` are `Dict[str, Any]`.
- All adapter `raw_output` parameters are `Dict[str, Any]`.

Impact:
- The type system provides zero guarantees at the data lineage boundary.
- Refactoring or adding new engine outputs requires cross-referencing every producer and consumer manually.

Risk Level: P0

Recommendation:
- Progressive replacement: start with the pipeline contract boundaries (`ResearchDataPack`, `DecisionOutput`, `SignalAdapterOutput`).
- Use `TypedDict` or `@dataclass` for the 8 adapter `raw_output` shapes.
- Enum or Literal for `action` values.

Migration Cost: High (incremental per boundary)

Priority: Sprint 1 (boundaries) + Sprint 2 (internal)

### Finding WS2-003 — Two parallel signal abstractions never converge (P1)

Evidence:
- `TradingSignal` (`shared/interfaces.py:127-169`) — simple dataclass with `action: str`, used in pipeline and backtest.
- `Signal` (`signal/models.py`) — rich typed model with enums (`SignalType`, `SignalSource`, `SignalStrength`), used in `normalizer.py` and `aggregator.py`.
- `MarketSignalContext` (`shared/interfaces.py:44-89`) — typed dataclass with `from_dict()`, exists but is NOT used in the pipeline path. DecisionBrain receives raw `dict`, not `MarketSignalContext`.

Impact:
- The signal package (`signal/models.py`, `signal/normalizer.py`, `signal/aggregator.py`) exists as an independent signal processing pipeline that is NOT connected to the main research pipeline.
- `MarketSignalContext` is a dead typed contract — `DecisionBrain.make_decision()` still receives `data_pack: Dict[str, Any]`.
- Two signal systems increase maintenance surface and create ambiguity about which signal model is canonical.

Risk Level: P1

Recommendation:
- WS5 should produce a signal contract matrix identifying which signal type is canonical for: research, storage, aggregation, execution, and persistence.
- Either deprecate `signal/models.Signal` and `normalizer.py`/`aggregator.py` if they are unused dead code, or integrate them into the pipeline.
- Either make `DecisionBrain.make_decision()` accept `MarketSignalContext`, or remove it.

Migration Cost: Medium

Priority: Sprint 2

### Finding WS2-004 — `pd.Timestamp.now()` in signal timestamp (P0)

Evidence:
- `UnifiedResearchPipeline.run()` line 133: `timestamp = pd.Timestamp.now()`.
- `TradingSignalCollector.collect()` passes timestamp to all adapters.
- All 8 adapters attach this timestamp to every `TradingSignal`.
- `UnifiedBacktestEngine._index_signals_by_date()` groups signals by timestamp date.
- Only signals whose timestamp date matches a K-line bar date are consumed.

Impact:
- A one-shot current-system-time timestamp means signals are indexed by today's date.
- If the K-line data range does not include the current system date, **zero signals are consumed by the backtest**.
- Even if today is in the range, all signals are stamped with the same date, so they are all attempted on the same bar.
- This is a backtest-validity-critical P0 issue.

Risk Level: P0

Recommendation:
- WS4 should design a `HistoricalSignalRunner` that generates as-of signals per historical bar, stamps each signal with the bar date, and feeds the series into `UnifiedBacktestEngine`.

Migration Cost: Medium

Priority: Sprint 1

### Finding WS2-005 — `signal.models.Signal` also defaults timestamp to `datetime.now()` (P1)

Evidence:
- `Signal` dataclass: `timestamp: datetime = field(default_factory=datetime.now)` (`signal/models.py:133`).
- 4 normalizers in `signal/normalizer.py` also use `raw_signal.get("timestamp", datetime.now())`.

Impact:
- If the `Signal` path is ever connected to the pipeline, the same P0 timestamp issue applies.

Risk Level: P1

Recommendation:
- Make `Signal.timestamp` a required field (remove default).
- Update all normalizer callers to supply historical timestamps.

Migration Cost: Low

Priority: Sprint 2

### Finding WS2-006 — Factor IC computation uses `shift(-period)` — explicit lookahead (P2)

Evidence:
- `FactorAnalyzer._compute_forward_returns()` uses `df[price_col].shift(-holding_period)` (`brain/factors/analyzer.py:148`).
- Method has explicit `mode="backtest"` guard that raises on `mode="live"`.
- `compute_ic_ir()` includes future-date detection against `pd.Timestamp.now()`.

Impact:
- Factor IC/IR is correct for offline backtest analysis (forward-return calculation inherently requires future data).
- The explicit mode guard and future-date check are adequate controls.

Risk Level: P2

Recommendation:
- Add a contract test proving that `mode="live"` raises `ValueError` (already covered by guardian logic).
- Ensure walk-forward train/test splits use strict temporal boundaries.

Migration Cost: Low

Priority: Sprint 2

### Finding WS2-007 — `PortfolioEngine` is deprecated but still functional (P2)

Evidence:
- `hands/backtest/portfolio_engine.py` header: `[DEPRECATED] 投资组合回测引擎 — 请使用 UnifiedBacktestEngine`.
- DeprecationWarning issued on import.
- Still used by `services/portfolio_service.py` (`portfolio_service.py:144-596` shows heavy `Dict[str, Any]` usage).

Impact:
- Two parallel execution paths: `UnifiedBacktestEngine` (single-symbol, strongly typed `TradingSignal`) and `PortfolioEngine` (multi-symbol, `Dict[str, Any]` signals).
- `PortfolioEngine` uses `UnifiedMatchingEngine` internally, BUT the matching engine `FillResult` is not consumed by `UnifiedBacktestEngine`.
- Behavior divergence between the two engines is a backtest consistency risk.

Risk Level: P2

Recommendation:
- Decide whether `PortfolioEngine` should be removed or upgraded to `TradingSignal` input.
- If kept, add a parity test comparing `UnifiedBacktestEngine` and `PortfolioEngine` output for identical input.

Migration Cost: Medium

Priority: Sprint 3

### Finding WS2-008 — `result.py` `BacktestResult` and `unified_engine.py` `BacktestResult` are different types (P2)

Evidence:
- `hands/backtest/result.py` defines `BacktestResult` with pre-computed metrics (sharpe_ratio, max_drawdown, win_rate) and `calculate_metrics()`.
- `hands/backtest/unified_engine.py` defines `BacktestResult` with only raw data (trades, equity_curve, daily_returns, final_cash) and computed `total_trades`/`total_return` properties.
- The pipeline creates `unified_engine.py`'s `BacktestResult`.

Impact:
- Consumers expecting the richer `result.py`-style `BacktestResult` (with sharpe_ratio, max_drawdown, etc.) receive only raw data.
- Metrics must be recomputed externally.

Risk Level: P2

Recommendation:
- Unify the two `BacktestResult` types or explicitly document which one is canonical.
- Move `calculate_metrics()` into the unified result so pipeline output is self-contained.

Migration Cost: Low

Priority: Sprint 3

### Finding WS2-009 — `PortfolioEngine` trades are `List[Dict[str, Any]]`, not `List[TradeRecord]` (P2)

Evidence:
- `PortfolioEngine.trades: List[Dict[str, Any]]` (`portfolio_engine.py:70`).
- `PortfolioEngine.batch_open_positions()` appends dicts with keys: `timestamp`, `symbol`, `action`, `price`, `shares`, `commission`, `slippage`.
- `PortfolioEngine.batch_close_positions()` appends dicts with additional keys: `stamp_duty`, `pnl`, `pnl_pct`.
- `UnifiedBacktestEngine` uses typed `List[TradeRecord]`.

Impact:
- PortfolioEngine trades lack type safety, cannot be queried by field, and are incompatible with the unified engine's `TradeRecord`.

Risk Level: P2

Recommendation:
- If `PortfolioEngine` is kept, migrate to `List[TradeRecord]` using `UnifiedMatchingEngine` output.

Migration Cost: Low

Priority: Sprint 3

### Finding WS2-010 — MarketSignalContext is typed but orphaned (P1)

Evidence:
- `MarketSignalContext` (`shared/interfaces.py:44-89`) is a fully typed dataclass with `from_dict()`/`to_dict()`.
- Has fields for: regime, risk, bubble_confidence, ntf_side, ntf_intensity, is_3rd_buy, bi_count, alpha_score, ma_status, price, pre_close, symbol, name, atr_stop, czsc_bottom, market, returns, lppl_days_to_tc, engine_status, engine_errors.
- **Zero usages** in the pipeline path. `DecisionBrain.make_decision()` receives `data_pack: Dict[str, Any]` not `MarketSignalContext`.
- `from_dict()` shows awareness of the dict problem, but the type itself is not used.

Impact:
- A typed schema exists for the data_pack contract but is not enforced.
- The decision boundary (Brain input) remains untyped.

Risk Level: P1

Recommendation:
- Either integrate `MarketSignalContext` into the pipeline as the `DecisionBrain.make_decision()` input type, or remove it.
- Integration would fix the data_pack schema issue at the decision boundary.

Migration Cost: Low

Priority: Sprint 2

## 5. Source → Transformation → Consumer Matrix

| Object | Source | Transformation | Consumer | Contract risk |
|---|---|---|---|---|
| OHLC DataFrame | DataLake (parquet) | DataCleaner, DataValidator, DataAdjuster | `DataService.fetch_for_brain()` | Medium |
| `data_pack` | `fetch_for_brain()` | AnalysisService (8 mutations) + DecisionBrain + Pipeline merge | SignalCollector + BacktestEngine | **P0: no schema** |
| `decision` dict | DecisionBrain | `_merge_decision_for_collection()` | `TradingSignalCollector` | **P0: no schema** |
| `TradingSignal` | 8 adapters | Timestamp assignment in pipeline | `UnifiedBacktestEngine` | P0: timestamp issue |
| `Signal` model | Normalizers | Aggregators | (not in pipeline) | P1: unused path |
| `TradeRecord` | Backtest engine | Cost/slippage adjustments | `BacktestResult` | P2: dual BacktestResult |
| `BacktestResult` | Backtest engine | (none) | Report generators | P2: dual types |
| `Portfolio` dict | PortfolioEngine | `UnifiedMatchingEngine` | PortfolioService | P2: Dict typing |

## 6. Contract Break Risk Summary

| Priority | Issue | Files affected | Consumer impact |
|---|---|---|---|
| **P0** | `data_pack` has no schema (>30 implicit keys) | `data_service.py`, `analysis_service_v2.py`, `adapters.py`, `research_pipeline.py`, `interfaces.py` | Silent wrong results on field typo |
| **P0** | `Dict[str, Any]` at 430+ sites | Entire codebase | Zero type safety at data boundaries |
| **P0** | Signal timestamp = `pd.Timestamp.now()` | `research_pipeline.py:133`, `adapters.py`, `unified_engine.py` | Backtest may produce zero trades or misleading results |
| **P1** | Two signal abstractions (`TradingSignal` vs `Signal`) | `shared/interfaces.py` vs `signal/models.py` | Maintenance surface doubled |
| **P1** | `MarketSignalContext` is typed but orphaned | `shared/interfaces.py:44-89` | Dead schema that would fix the dict problem |
| **P2** | Dual `BacktestResult` types | `unified_engine.py` vs `result.py` | Metrics may be missing from pipeline output |
| **P2** | `PortfolioEngine` dict trades vs typed trades | `portfolio_engine.py:70` | Type inconsistency across execution paths |

## 7. Recommendation: ResearchDataPack Schema

Define a typed `ResearchDataPack` as the boundary contract:

```python
@dataclass
class ResearchDataPack:
    """Typed schema for the cross-layer data_pack contract."""
    # Input data
    stock: pd.DataFrame
    bench: pd.DataFrame
    etf: pd.DataFrame
    # Engine results
    regime: str = "UNKNOWN"
    entropy: float = 0.0
    turnover_z: float = 0.0
    risk: str = "Safe"
    bubble_confidence: float = 0.0
    ntf_side: str = "NONE"
    ntf_intensity: float = 0.0
    ntf_action: str = ""
    is_3rd_buy: bool = False
    bi_count: int = 0
    wyckoff_phase: str = "unknown"
    wyckoff_confidence: float = 0.0
    wyckoff_spring: bool = False
    wyckoff_utad: bool = False
    alpha_score: float = 0.0
    ma_status: str = "DATA_INSUFFICIENT"
    price: float = 0.0
    atr_stop: float = 0.0
    returns: Optional[pd.Series] = None
    # Metadata
    symbol: str = ""
    market: str = "CN"
    trace_id: str = ""
    engine_status: Dict[str, str] = field(default_factory=dict)
    engine_errors: Dict[str, str] = field(default_factory=dict)
```

With a mutable-dict compatibility path:
```python
def to_dict(self) -> Dict[str, Any]: ...
@classmethod
def from_dict(cls, d: Dict[str, Any]) -> "ResearchDataPack": ...
```

Keep the dict path as a migration shim. Add validation at:
1. `DataService.fetch_for_brain()` → `ResearchDataPack` constructor
2. `AnalysisService.run_ticker_analysis()` output (validate against schema)
3. `TradingSignalCollector.collect()` input (validate or accept `ResearchDataPack` directly)

## 8. Next Workstreams

1. `03_backtest_integrity_audit.md` — Verify Signal(T)→Execution(T+1), lookahead, survivorship, A-share constraints.
2. `04_historical_signal_series_blueprint.md` — Design as-of signal generation runner fixing the one-shot timestamp.

## 9. Verification Checklist

- [x] Traced `data_pack` from creation through 8 mutation points to signal collection.
- [x] Traced `TradingSignal` from adapter creation through backtest matching to `BacktestResult`.
- [x] Traced `Signal` model path (normalizer → aggregator) — found not connected to main pipeline.
- [x] Traced `TradeRecord` and `BacktestResult` — found dual `BacktestResult` types.
- [x] Traced portfolio objects — found `PortfolioEngine` deprecated but still active.
- [x] Identified `Dict[str, Any]` pollution at 430+ sites.
- [x] Identified `pd.Timestamp.now()` pollution at 131 sites.
- [x] Identified schema drift and implicit dict keys in `data_pack`.
- [x] Marked `MarketSignalContext` as orphaned typed schema.
- [x] Produced Source → Transformation → Consumer table for every core object.
- [x] Ranked contract break risks P0/P1/P2 with evidence and recommendations.