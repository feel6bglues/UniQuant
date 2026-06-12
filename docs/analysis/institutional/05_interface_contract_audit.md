# WS5 — Interface Contract Audit

Generated: 2026-06-10

Scope: Extract every explicit and implicit interface in the codebase, classify contract violations, define current vs target contract matrix. This is Sprint 2's root artifact.

## 1. Current Protocol/ABC Inventory

### 1.1 `shared/interfaces.py`

| Contract | Type | Purpose | Usage status |
|---|---|---|---|
| `TradingSignal` | dataclass | Brain→Hands signal bridge | Active: pipeline + backtest |
| `MarketSignalContext` | dataclass | Typed decision input with `from_dict()`/`to_dict()` | **Orphaned**: not used in pipeline |
| `DataFetcherProtocol` | Protocol | Decouple Brain from DataFetcher | Active: used in LPPL/NTF paths |
| `RiskAssessmentProtocol` | Protocol | Decouple Brain from risk assessment | Active: used in DecisionBrain |
| `PositionSizerProtocol` | Protocol | Decouple Brain from position sizing | Active: used in DecisionBrain |
| `AnalysisEngineProtocol` | Protocol | Decouple AnalysisService from engines | Active: 8+ engine implementations |
| `CalculationPluginProtocol` | Protocol | Dynamic calculation plugins | Registered in global `calculation_registry` |
| `CalculationRegistry` | class | Plugin registry | Active but low usage |
| `MarketRegime` | Enum | Market state values | Active in MarketSignalContext, DecisionBrain |
| `NtfSide` | Enum | NTF behavior direction | Active in adapters |
| `RegimeType` | Enum | Unified regime type | Active in regime engine |

### 1.2 `data/sources/protocols.py` (capability protocols)

| Protocol | Purpose | Usage status |
|---|---|---|
| `HasBasicInfo` | Fetch stock basic info | Duck-typed capability marker |
| `HasFundFlow` | Fetch fund flow data | Duck-typed capability marker |
| `HasIndustryList` | Fetch industry list | Duck-typed capability marker |
| `HasConceptList` | Fetch concept list | Duck-typed capability marker |
| `HasSectorFundFlow` | Fetch sector fund flow | Duck-typed capability marker |
| `HasHotRanking` | Fetch hot ranking | Duck-typed capability marker |
| `HasMinuteData` | Fetch minute K-line | Duck-typed capability marker |
| `HasDragonTiger` | Fetch dragon-tiger list | Duck-typed capability marker |
| `HasTickData` | Fetch tick data | Duck-typed capability marker |

Note: These are structural subtype protocols with no formal `isinstance` checks. Used as documentation markers.

### 1.3 `data/sources/base.py`

| Contract | Type | Purpose |
|---|---|---|
| `DataSource` | ABC | Abstract base with `fetch_daily()`, `fetch_real_time()`, `fetch_market_cap()` |

### 1.4 `signal/adapters.py`

| Contract | Type | Adapters |
|---|---|---|
| `EngineAdapter` | ABC with `adapt()` | LPPL, CZSC, Wyckoff, FSM, Regime, NTF, AlphaScore, MAStatus |

### 1.5 `signal/normalizer.py`

| Contract | Type | Normalizers |
|---|---|---|
| `SignalNormalizer` | ABC with `normalize()` | LPPL, Wyckoff, Indicator, CZSC |

### 1.6 Engine abstractions (implicit, via `AnalysisEngineFactory`)

| Engine | File | Interface |
|---|---|---|
| FsmAnalysisEngine | `brain/fsm/fsm.py` | `run_fsm_analysis()` / implicit |
| CzscAnalysisEngine | `brain/czsc/` | `run_czsc_analysis()` / implicit |
| LpplAnalysisEngine | `brain/lppl/engine.py` | `run_lppl_analysis()` / implicit |
| RegimeAnalysisEngine | `brain/regime/` | `run_regime_analysis()` / implicit |
| NtfAnalysisEngine | `brain/ntf/` | `detect_intervention_from_data()` / implicit |
| WyckoffAnalysisEngine | `brain/wyckoff/` | `run_wyckoff_analysis()` / implicit |
| MacroAnalysisEngine | `brain/macro/` | `analyze_macro_health()` / implicit |
| ReportGeneratorEngine | `brain/report/` | `generate_report()` / implicit |
| DecisionBrain | `brain/fsm/fsm.py:179` | `make_decision()` — core orchestrator |

**Finding WS5-001: Engine interfaces are implicit — no formal ABC or Protocol beyond AnalysisEngineProtocol** (P1)

Evidence:
- `AnalysisEngineProtocol` (`interfaces.py`) defines only `analyze(data, **kwargs) -> Dict[str, Any]`.
- Actual engine signatures vary widely: `run_lppl_analysis(symbol, df)`, `run_czsc_analysis(symbol, df)`, `detect_intervention_from_data(fetcher, symbol, start_date, end_date)`.
- Engine factory creates each engine individually with specific method calls (`analysis_service_v2.py:308-320`).
- No engine exposes a uniform `analyze()` method matching the protocol.

Impact:
- `AnalysisEngineProtocol` is a dead contract — no engine actually implements it.
- Engine discovery and substitution requires knowing each engine's specific signature.
- New engines cannot be added without modifying `AnalysisService._run_engines()`.

Risk Level: P1

Recommendation:
- Either make `AnalysisEngineProtocol.analyze()` the canonical engine interface and wrap engines, or remove the protocol.
- Add a `Context = Dict[str, Any]` or typed `AnalysisContext` parameter to all engines.

Migration Cost: Medium

Priority: Sprint 2

### 1.7 Backtest contracts

| Contract | Type | File | Notes |
|---|---|---|---|
| `UnifiedBacktestEngine.run()` | method | `unified_engine.py:118-124` | The canonical backtest signature |
| `BacktestResult` (unified) | dataclass | `unified_engine.py:42-55` | Raw data: trades, equity_curve |
| `BacktestResult` (result.py) | dataclass | `result.py:16-42` | Pre-computed metrics |
| `TradeRecord` (unified) | dataclass | `unified_engine.py:28-40` | Typed execution record |
| `TradeRecord` (result.py) | dataclass | `result.py:8-17` | Same-ish but with `pnl_pct` |
| `PortfolioEngine.trades` | `List[Dict[str, Any]]` | `portfolio_engine.py:70` | Dict, not typed |

### 1.8 Service contracts (constructor injection)

| Service | Constructor params | Injected by |
|---|---|---|
| `DataService` | `fetcher`, `storage_manager`, `cleaner` | ServiceContainer |
| `AnalysisService` | `data_service`, `engine_factory`, `market_cache` | ServiceContainer |
| `TradingSignalCollector` | `registry` | Pipeline constructor |
| `UnifiedBacktestEngine` | `initial_capital`, `commission_rate`, `stamp_duty_rate`, `slippage_rate`, `min_commission`, `trade_calendar` | Pipeline constructor |
| `UnifiedResearchPipeline` | `analysis_service`, `backtest_engine`, `signal_collector` | ServiceContainer |

## 2. Contract Matrix — Current State

| Boundary | Input type | Output type | Formal contract? | Risk |
|---|---|---|---|---|
| DataService → AnalysisService | `symbol: str` | `data_pack: Dict[str, Any]` | Implicit dict keys | **P0** |
| AnalysisService → DecisionBrain | `data_pack: Dict[str, Any]` | `decision: Dict[str, Any]` | Implicit dict keys | **P0** |
| DecisionBrain → TradingSignalCollector | `decision: Dict[str, Any]` (via pipeline merge) | `collector_pack: Dict[str, Any]` | Implicit dict keys | **P0** |
| Adapters → Backtest | `TradingSignal` | `List[TradingSignal]` | Typed dataclass | OK |
| Backtest → Result | `TradingSignal + df` | `BacktestResult` (unified) | Typed dataclass | OK (but dual types) |
| Signal normalizer path | `Dict[str, Any]` | `Signal` (rich model) | Typed dataclass | **P1**: not connected |
| PortfolioEngine input | `Dict[str, float]` (signal dict) | `List[Dict]` (trade list) | No formal interface | **P2** |

## 3. Contract Findings

### Finding WS5-002 — `ResearchDataPack` must be the canonical cross-layer schema (P0)

Evidence:
- (From WS2) 30+ implicit keys written across 8 mutation points in `AnalysisService`.
- No typed schema exists. `MarketSignalContext` (typed dataclass in `interfaces.py`) is not used in the pipeline.
- `data_pack` crosses data → analysis → signal → backtest layers as `Dict[str, Any]`.

Target contract:

```python
@dataclass
class ResearchDataPack:
    stock: pd.DataFrame
    bench: pd.DataFrame
    etf: pd.DataFrame
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
    symbol: str = ""
    market: str = "CN"
    trace_id: str = ""
    engine_status: Dict[str, str] = field(default_factory=dict)
    engine_errors: Dict[str, str] = field(default_factory=dict)
```

Migration:
1. Add `to_dict()`/`from_dict()` for backward compatibility.
2. Add validation at `DataService.fetch_for_brain()` output.
3. Add validation at `TradingSignalCollector.collect()` input.
4. Remove dict path in Sprint 3 after all callers migrate.

Risk Level: P0

Recommendation: Adopt `ResearchDataPack` as the canonical contract for WS6 (adapter) and WS14 (refactoring).

Migration Cost: Medium

Priority: Sprint 2

### Finding WS5-003 — `DecisionOutput` must be a typed contract (P0)

Evidence:
- `DecisionBrain.make_decision()` returns `Dict[str, Any]` (`fsm.py:548-640`).
- Keys produced: `action`, `reason`, `regime`, `risk`, `bubble_confidence`, `ntf_side`, `ntf_intensity`, `is_3rd_buy`, `bi_count`, `alpha_score`, `final_decision`, `final_score`, `engine_status`, `engine_errors`, plus optional keys: `state`, `buy_blockers`, `sell_triggers`, `sell_limit_blocked`, `position_details`, `daily_return`, `shares`, `final_decision`.
- The **same** response dictionary is built by `_build_response()`, `_check_veto_conditions()`, `_check_sell_conditions()`, `_check_buy_blockers()`, and `_execute_buy()`.
- All callers in `pipeline._merge_decision_for_collection()` access dict keys with `.get()` and conditional existence checks (`research_pipeline.py:220-236`).

Impact:
- The decision boundary (Brain → Signal) is the second-highest-risk dict contract after `data_pack`.
- Signal generation silently degrades when decision keys are missing or renamed.

Risk Level: P0

Recommendation:

```python
@dataclass
class DecisionOutput:
    action: str  # "BUY" | "SELL" | "HOLD" | "FORCE_WAIT" | "FORCE_EXIT" | "CIRCUIT_BREAK" | "STAY_CURRENT_STATE" | "ADD"
    final_decision: str  # Canonical action after HOLD/Sell mapping
    reason: str = ""
    confidence: float = 0.0  # From final_score/100
    shares: int = 0
    price: float = 0.0
    state: str = "IDLE"
    # Diagnostic fields
    regime: str = "NORMAL"
    risk: str = "Safe"
    bubble_confidence: float = 0.0
    ntf_side: str = "NONE"
    ntf_intensity: float = 0.0
    is_3rd_buy: bool = False
    bi_count: int = 0
    alpha_score: float = 0.0
    final_score: int = 0
    buy_blockers: List[str] = field(default_factory=list)
    sell_triggers: List[str] = field(default_factory=list)
    position_details: Optional[Dict[str, Any]] = None
    engine_status: Dict[str, str] = field(default_factory=dict)
    engine_errors: Dict[str, str] = field(default_factory=dict)
```

Migration:
1. Add `DecisionBrain.make_decision()` → `DecisionOutput`.
2. Add `to_dict()` for backward compatibility with pipeline merge.
3. `_merge_decision_for_collection()` accepts `DecisionOutput` natively.

Risk Level: P0

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-004 — `TradingSignal` and `signal.models.Signal` are two parallel signal abstractions (P1)

| Dimension | `TradingSignal` | `signal.models.Signal` |
|---|---|---|
| Location | `shared/interfaces.py:127-169` | `signal/models.py` |
| Fields | `action`, `reason`, `confidence`, `shares`, `symbol`, `price`, `timestamp` | `signal_type` (27 enum), `source` (10 enum), `direction`, `strength` (enum), `confidence`, `timestamp`, `price`, `value`, `metadata`, `parent_id` |
| Used by | pipeline + backtest | normalizer + aggregator |
| Type safety | str-based `action` | 3 enums |
| Timestamp | Optional with `repr=False` | Default `datetime.now()` |

**Observation**: `TradingSignal` is the pipeline contract. `Signal` is richer but disconnected. They serve different purposes — `TradingSignal` is an execution intent (BUY/SELL/HOLD with shares), `Signal` is a research event (type/strength/direction metadata).

Target:

```python
# TradingSignal remains the execution intent.
# Signal remains the research metadata event.
# They are NOT the same abstraction. No unification needed.
# However: the adapter pipeline should produce BOTH:
#   - TradingSignal → backtest engine (execution)
#   - Signal → signal store / observability (metadata)
```

Actions:
1. Document that `TradingSignal` is the backtest execution contract.
2. Document that `Signal` is the research metadata/observability contract.
3. Add an optional `metadata: Dict[str, Any]` to `TradingSignal` for traceability.
4. Add a `from_trading_signal()` factory to `Signal` if signal store integration is needed.

Risk Level: P1

Recommendation: Keep both. Document separation. Connect them via a trace_id field.

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-005 — `BacktestResult` has two incompatible types (P2)

| Dimension | `unified_engine.py:BacktestResult` | `result.py:BacktestResult` |
|---|---|---|
| trades | `List[TradeRecord]` (unified) | `List[TradeRecord]` (result.py) |
| equity_curve | `List[float]` | `List[float]` |
| Returns | Computed via `@property` (`total_trades`, `total_return`) | Pre-computed via `calculate_metrics()` (sharpe, max_drawdown, win_rate, etc.) |
| `calculate_metrics()` | Not available | Available |
| Rich metadata | None | `drawdown_metrics`, `tail_risk_metrics`, `stress_test_results`, `overfitting_metrics`, `metadata` |

Target: Unify by moving the richer shape into `unified_engine.py`:

```python
@dataclass
class BacktestResult:
    trades: List[TradeRecord]
    equity_curve: List[float]
    daily_returns: List[float]
    initial_capital: float = 0.0
    final_cash: float = 0.0
    # Computed
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    # Optional extras
    metadata: Dict[str, Any] = field(default_factory=dict)
```

Keep `calculate_metrics()` as a method that populates computed fields.

Risk Level: P2

Recommendation: Unify both types. Deprecate `result.py:BacktestResult`.

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-006 — `TradeRecord` has almost the same shape in two places (P2)

| Field | `unified_engine.py:TradeRecord` | `result.py:TradeRecord` |
|---|---|---|
| `timestamp` | `datetime.datetime` | `datetime` |
| `action` | str | str |
| `price` | float | float |
| `shares` | int | int |
| `commission` | float | float |
| `slippage` | float | float |
| `pnl` | float (default 0) | float (default 0) |
| `pnl_pct` | missing | float (default 0) |
| `stamp_duty` | float (default 0) | missing |
| `transfer_fee` | float (default 0) | missing |
| `reason` | str (default "") | str (default "") |
| `symbol` | str | missing |
| `to_dict()` | missing | available |

Target: Single `TradeRecord` in `shared/interfaces.py` with all fields.

Risk Level: P2

Recommendation: Define canonical `TradeRecord` in `shared/interfaces.py`, import into both engine modules.

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-007 — `PortfolioEngine` trades are `List[Dict[str, Any]]` — untyped trades (P2)

Evidence:
- `PortfolioEngine.trades: List[Dict[str, Any]]` (`portfolio_engine.py:70`).
- `batch_open_positions()` appends dict with keys: `timestamp`, `symbol`, `action`, `price`, `shares`, `commission`, `slippage`.
- `batch_close_positions()` appends dict with additional keys: `stamp_duty`, `pnl`, `pnl_pct`.

Impact: PortfolioEngine trades cannot be queried by field, lack type safety, incompatible with `TradeRecord`.

Risk Level: P2

Recommendation: Migrate `PortfolioEngine.trades` to `List[TradeRecord]` using the canonical type.

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-008 — `MarketSignalContext` is typed but orphaned — should become the ResearchDataPack consumer (P1)

Evidence:
- `MarketSignalContext` (`interfaces.py:44-89`) typed dataclass with 20 fields, `from_dict()` and `to_dict()`.
- Documented purpose: "用于 DecisionBrain.make_decision() 的类型化输入，替代无类型的 dict 参数".
- `DecisionBrain.make_decision()` accepts `Union[dict, MarketSignalContext]` (`fsm.py:548`).
- **No caller passes `MarketSignalContext`.** AnalysisService always passes `data_pack: Dict[str, Any]`.

Impact:
- A typed schema ready for the decision boundary exists but is not used.
- This is the simplest contract fix available — just pass typed object instead of dict.

Risk Level: P1

Recommendation:
- Adopt `MarketSignalContext` as the `DecisionBrain.make_decision()` input (it already accepts it).
- Connect it via `ResearchDataPack.to_market_signal_context()` or directly construct from `ResearchDataPack` fields.
- Remove the dict path from `make_decision()` in Sprint 3.

Migration Cost: Low

Priority: Sprint 2

### Finding WS5-009 — `MarketSignalContext` needs three additional fields for historical signal series (P2)

Evidence:
- WS4 design requires two modes: `approximate_research` and `strict_point_in_time`.
- `MarketSignalContext` does not currently have a mode flag or bar_index.

Recommendation: Add to `MarketSignalContext`:
```python
analysis_mode: str = "approximate_research"  # "approximate_research" | "strict_point_in_time"
bar_index: int = -1  # -1 = most recent bar
```

Risk Level: P2

Priority: Sprint 2

### Finding WS5-010 — `DataFetcherProtocol` is used by LPPL/NTF paths — correct (GREEN)

Evidence:
- `DataFetcherProtocol` defines `fetch_history(symbol, start_date, end_date, adjust, period)`.
- Used in `brain/lppl/engine.py` and `brain/ntf/ntf_engine.py` for data access.
- Decouples Brain from concrete DataFetcher implementation.

Risk Level: GREEN

### Finding WS5-011 — `PositionSizerProtocol` is used by DecisionBrain — correct (GREEN)

Evidence:
- `PositionSizerProtocol` defines `calculate_shares(price, stop_loss, czsc_bottom, market, symbol) -> Dict[str, Any]`.
- DecisionBrain calls `self.sizer.calculate_shares()` in `_execute_buy()`.
- Note: returns `Dict[str, Any]` — P2 improvement to typed return.

Risk Level: GREEN (return type P2)

### Finding WS5-012 — `RiskAssessmentProtocol` is used by DecisionBrain — correct (GREEN)

Evidence:
- `RiskAssessmentProtocol` defines `calculate_metrics(returns) -> Dict[str, Any]`.
- DecisionBrain calls `self.evt_risk.calculate_metrics(ctx.returns)` in `_execute_buy()`.
- Same `Dict[str, Any]` return issue as PositionSizer.

Risk Level: GREEN (return type P2)

### Finding WS5-013 — `DataSource` ABC is used by 4+ source implementations — correct (GREEN)

Evidence:
- `DataSource` ABC (`data/sources/base.py`) defines `fetch_daily()`, `fetch_real_time()`, `fetch_market_cap()`.
- Implementations: `SinaSource`, `TencentSource`, `EastMoneySource`, `BaoStockSource`, `TDXSource`.
- All implement the required abstract methods.

Risk Level: GREEN

### Finding WS5-014 — ServiceContainer registration is implicit — no formal contract (P2)

Evidence:
- `ServiceContainer.register(name, service)` accepts any `Any` (`service_container.py:36-38`).
- No type checking or interface validation at registration time.
- Services are accessed by string name: `self._services[name]`.

Impact:
- A misregistered service (wrong type, missing interface) only fails at first use, not at registration time.

Risk Level: P2

Recommendation:
- Add typed registration methods: `register_data_service()`, `register_analysis_service()`, etc.
- Or use `Protocol`-based validation in `get()`.

Migration Cost: Low

Priority: Sprint 3

### Finding WS5-015 — `EngineAdapter` ABC is the correct pattern — migrate other engine boundaries to match (P1)

Evidence:
- `EngineAdapter` (`adapters.py:21-35`) defines `adapt(raw_output, symbol, timestamp, default_shares) -> Optional[TradingSignal]`.
- 8 adapter implementations exist.
- This is the cleanest contract in the codebase.

Recommendation:
- Use `EngineAdapter` as the model for other engine boundaries.
- Apply the same pattern to `SignalNormalizer` (already similar) and engine interfaces.

Risk Level: P1 (positive finding)

Priority: Sprint 2

## 4. Target Contract Matrix

| Boundary | Current | Target | Sprint |
|---|---|---|---|
| DataService → AnalysisService | `Dict[str, Any]` | `ResearchDataPack` | 2 |
| AnalysisService → DecisionBrain | `Dict[str, Any]` | `ResearchDataPack` → `MarketSignalContext` | 2 |
| DecisionBrain → Pipeline/Signal | `Dict[str, Any]` | `DecisionOutput` (typed) | 2 |
| Pipeline → TradingSignalCollector | `Dict[str, Any]` | `ResearchDataPack` + `DecisionOutput` | 2 |
| Adapters → Backtest | `TradingSignal` | `TradingSignal` (keep) | 2 |
| Backtest → Result | `BacktestResult` (unified) | `BacktestResult` (unified + metrics) | 2 |
| PortfolioEngine trades | `List[Dict]` | `List[TradeRecord]` | 2 |
| Pipeline → Signal store | Not connected | `TradingSignal` + metadata → `Signal` | 3 |
| Engine → Factory | Implicit per-engine | `AnalysisEngineProtocol.analyze()` | 2 |

## 5. Contract Violation Summary

| Violation type | Count | Examples |
|---|---|---|
| Dict boundary (P0) | 3 | `data_pack`, `decision`, `collector_pack` merge |
| Dict boundary (P1-P2) | 3 | `PortfolioEngine.trades`, `PositionSizer` return, `RiskAssessment` return |
| Dead typed contract | 1 | `MarketSignalContext` |
| Dual type | 2 | `BacktestResult`, `TradeRecord` |
| Dead protocol | 1 | `AnalysisEngineProtocol.analyze()` |
| Implicit registration | 1 | `ServiceContainer` |
| Missing mode field | 1 | `MarketSignalContext` missing analysis_mode |

## 6. Migration Path

### Step 1 — Define canonical types in `shared/interfaces.py` (Sprint 2)

```
shared/interfaces.py:
  - ResearchDataPack (new)
  - DecisionOutput (new)
  - MarketSignalContext (add analysis_mode, bar_index)
  - TradingSignal (keep, add metadata field)
  - TradeRecord (canonical, merge from both engines)
  - BacktestResult (canonical, unified)
  - EngineAdapter (move from adapters.py or re-export)
```

### Step 2 — Add dict compatibility (Sprint 2)

Every new type gets `to_dict()` and `from_dict()`. Old pipeline continues with dicts.

### Step 3 — Wire MarketSignalContext into DecisionBrain (Sprint 2)

```python
# In AnalysisService._make_decision():
ctx = MarketSignalContext.from_dict(data_pack)
return self.brain.make_decision(ctx)
# DecisionBrain.make_decision() already accepts MarketSignalContext
```

### Step 4 — Wire ResearchDataPack into fetch_for_brain (Sprint 2-3)

```python
# DataService (new method):
def fetch_for_brain_typed(self, symbol: str) -> ResearchDataPack: ...
# With dict backward compat:
def fetch_for_brain(self, symbol: str) -> Dict[str, Any]:
    return self.fetch_for_brain_typed(symbol).to_dict()
```

### Step 5 — Connect TradingSignal → Signal for observability (Sprint 3)

### Step 6 — Remove dict paths (Sprint 3-4)

## 7. WS4 Cross-Reference: Two Modes

As flagged in WS4, the `HistoricalSignalRunner` needs two modes. The interface contract must support both:

```python
@dataclass
class ResearchDataPack:
    ...
    analysis_mode: str = "approximate_research"
    # "approximate_research": full-frame engine results reused (fast, moderate leakage risk)
    # "strict_point_in_time": per-bar engine computation (slow, fully correct)
```

`DecisionOutput` should also propagate the mode:

```python
@dataclass
class DecisionOutput:
    ...
    analysis_mode: str = "approximate_research"
    bar_index: int = -1
```

This ensures every research artifact is self-describing about its point-in-time correctness.

## 8. Verification Checklist

- [x] Extracted all `Protocol` definitions (7 in interfaces.py, 8 in protocols.py).
- [x] Extracted all `ABC` and abstract methods (DataSource, EngineAdapter, SignalNormalizer).
- [x] Extracted service constructor contracts (4 services in ServiceContainer).
- [x] Extracted `TradingSignal` contract.
- [x] Compared `TradingSignal` with `signal.models.Signal` (P1: not unified, but OK as different abstractions).
- [x] Audited `MarketSignalContext` usage vs raw dict usage (P1: orphaned).
- [x] Identified fat interfaces (PositionSizerProtocol returns Dict[str, Any]).
- [x] Identified LSP violations (AnalysisEngineProtocol.analyze() not implemented by engines).
- [x] Identified ISP violations (none found).
- [x] Identified hidden service dependencies (ServiceContainer registration is untyped).
- [x] Defined current interface matrix (§2).
- [x] Defined target interface matrix (§4).
- [x] Specified two modes (approximate_research / strict_point_in_time) from WS4.