# Stage 0 - Global Architecture Map

Generated: 2026-06-09

Scope: Current source code and control documents only. Historical architecture and migration documents under `docs/` are treated as background unless confirmed by source.

## 1. 系统定位

UniQuant is a Python 3.12+ A-share quantitative research and trading platform. The current runtime system covers market data ingestion, data lake storage, data cleaning, multi-engine analysis, signal normalization, A-share constrained backtesting/matching, risk modules, service orchestration, reporting, and Streamlit UI.

Evidence:

- `pyproject.toml:1-28` defines package `uniquant`, Python `>=3.12`, and core dependencies including `pandas`, `numpy`, `scipy`, `pyarrow`, `duckdb`, `akshare`, `mootdx`, `streamlit`, and `plotly`.
- `config/config.yaml:4-21` defines the main data lake, logging, and TDX runtime paths.
- `AGENTS.md:10-23` and `docs/index.md:17-33` state the repository is past the old migration-target phase and that the eight runtime layers are present.
- Current source scan confirms top-level runtime packages under `src/uniquant/`: `shared`, `data`, `brain`, `signal`, `hands`, `risk`, `services`, `ui`.

Current dirty-worktree boundary:

- `git status --short` shows uncommitted changes in `AGENTS.md`, `docs/index.md`, reshaping logs, `src/uniquant/brain/factors/__init__.py`, `src/uniquant/brain/factors/custom_factors.py`, and `src/uniquant/hands/backtest/engine.py`.
- Many files under `src/uniquant/brain/factors/auto_mined/` are deleted in the working tree. Stage 4 must analyze the factor system from current files, not from old factor docs.
- `docs/ANALYSIS_PROMPT_PLAYBOOK.md` itself is untracked in this working tree but is the user-selected analysis control document.

## 2. 八层模块职责表

| Layer | Path | Current source scan | Primary responsibility | Current binding evidence |
|---|---|---:|---|---|
| `shared` | `src/uniquant/shared/` | 44 files | Cross-layer protocols, constants, exceptions, cache, logging, A-share market rules, cost/slippage/limit utilities. | `src/uniquant/shared/interfaces.py:41-169` defines `MarketSignalContext` and `TradingSignal`; `src/uniquant/hands/backtest/unified_engine.py:26-39` imports shared constants, cost model, limit checker, and market rules. |
| `data` | `src/uniquant/data/` | 65 files | Data ingestion, data lake, source routing, parsers, cleaners, validators, adjusters, access services. | `src/uniquant/services/data_service.py:35-91` implements a facade over `DataFetcher`, `StorageManager`, `DataCleaner`, cache, quality, and stock query services. |
| `brain` | `src/uniquant/brain/` | 55 files | Strategy and research engines: FSM/DecisionBrain, CZSC, LPPL, NTF, regime, Wyckoff, indicators, alpha decoupler, factors, screener. | `src/uniquant/services/analysis_service_v2.py:308-317` runs regime, LPPL, NTF, CZSC, Wyckoff, alpha, and derived indicators. |
| `signal` | `src/uniquant/signal/` | 7 files | Convert heterogeneous brain/decision outputs into standard `TradingSignal` objects. | `src/uniquant/signal/adapters.py:405-416` registers adapters for LPPL, CZSC, Wyckoff, FSM, regime, NTF, alpha score, and MA status. |
| `hands` | `src/uniquant/hands/` | 34 files | Backtesting, matching, portfolio and strategy execution, reports, robustness/tuning. | `src/uniquant/hands/backtest/unified_engine.py:88-124` defines `UnifiedBacktestEngine.run(df, signals, symbol, name)`. |
| `risk` | `src/uniquant/risk/` | 7 files | Position sizing, drawdown, EVT, historical/structural risk, portfolio optimization. | `src/uniquant/shared/interfaces.py:193-228` defines risk and position sizing protocols used as cross-layer contracts. |
| `services` | `src/uniquant/services/` | 31 files | Dependency injection, orchestration, data service, analysis service, research pipeline, cache coordination, reports, scans, health. | `src/uniquant/services/service_container.py:74-127` initializes and registers the DAG services. |
| `ui` | `src/uniquant/ui/` | 8 files | Streamlit dashboard, UI manager logic, health check, visualization. | `docs/index.md:35-47` lists UI as present; Stage 7 should inspect dashboard and live-readiness details. |

The intended dependency direction is:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Concrete orchestration, however, is service-centered: `services` imports lower layers and wires them together. Lower layers should not import `services` for runtime work unless specifically documented and tested.

## 3. 核心数据流和控制流

### Service Initialization DAG

`ServiceContainer.initialize()` is the top-level runtime composition point:

1. Creates `StorageManager`, `TradeCalendarManager`, and `CacheCoordinator` (`src/uniquant/services/service_container.py:78-83`).
2. Creates `DataService(storage_manager=storage)` and registers `storage`, `calendar`, `cache`, and `data_service` (`src/uniquant/services/service_container.py:85-91`).
3. Creates `AnalysisEngineFactory(orchestrator=data_svc)` and `MarketLevelCache`, then attaches the cache to `DataService` (`src/uniquant/services/service_container.py:93-100`).
4. Creates `AnalysisService(data_service, engine_factory, market_cache)`. Its constructor rebinds the factory orchestrator to the `AnalysisService` and clears any cached engines through `bind_orchestrator()` (`src/uniquant/services/analysis_service_v2.py:81-97`; `src/uniquant/services/analysis/engine_factory.py:20-32`).
5. Creates `UnifiedBacktestEngine` and `TradingSignalCollector(create_default_registry())` (`src/uniquant/services/service_container.py:102-117`).
6. Creates `UnifiedResearchPipeline(analysis_service, backtest_engine, signal_collector)` and registers `research_pipeline` (`src/uniquant/services/service_container.py:119-124`).

Text topology:

```text
StorageManager
  -> DataFetcher / DataService
  -> AnalysisEngineFactory + MarketLevelCache
  -> AnalysisService
  -> TradingSignalCollector
  -> UnifiedBacktestEngine
  -> UnifiedResearchPipeline
```

### Single Ticker Analysis Flow

`AnalysisService.run_ticker_analysis()` is the current single-ticker analysis orchestrator:

1. Generates or receives a trace id (`src/uniquant/services/analysis_service_v2.py:240-253`).
2. Calls `DataService.fetch_for_brain(ticker)` via `_prepare_data()` (`src/uniquant/services/analysis_service_v2.py:291-301`).
3. Rejects missing or empty `data_pack["stock"]` with `success=False` and error `"数据不足"` (`src/uniquant/services/analysis_service_v2.py:254-262`).
4. Runs engines in fixed order: regime, LPPL, NTF, CZSC, Wyckoff, alpha, derived indicators (`src/uniquant/services/analysis_service_v2.py:308-317`).
5. Adds `symbol` and `market="CN"` to `data_pack` (`src/uniquant/services/analysis_service_v2.py:319-320`).
6. Calls `DecisionBrain.make_decision(data_pack)` through `self.brain` (`src/uniquant/services/analysis_service_v2.py:618`).
7. Returns `TickerAnalysisResult`; its `signals` field remains empty because signals are filled at pipeline level (`src/uniquant/services/analysis_service_v2.py:280-286`).

`DataService.fetch_for_brain()` currently returns:

- `stock`: target stock K-line data.
- `bench`: HS300 benchmark from `sh000300`.
- `etf`: ETF data loaded through `_load_etf_data()`.

Evidence: `src/uniquant/services/data_service.py:397-407`.

### Research Pipeline Flow

`UnifiedResearchPipeline.run()` creates the end-to-end research/backtest result:

1. Calls `AnalysisService.run_ticker_analysis(symbol, trace_id)` (`src/uniquant/services/research_pipeline.py:112-116`).
2. On analysis failure, returns `PipelineResult(success=False)` with empty signals and empty `BacktestResult` (`src/uniquant/services/research_pipeline.py:116-126`).
3. Merges `DecisionBrain` output back into a collector pack (`src/uniquant/services/research_pipeline.py:128-136`, `210-237`).
4. Uses `TradingSignalCollector.collect()` to produce `List[TradingSignal]`.
5. Reads `data_pack["stock"]`; if empty, returns failure `"K线数据为空"` (`src/uniquant/services/research_pipeline.py:138-150`).
6. Calls `UnifiedBacktestEngine.run(df=stock_df, signals=signals, symbol=symbol, name=name)` (`src/uniquant/services/research_pipeline.py:152-157`).
7. Returns `PipelineResult` with `data_pack`, decision, signals, and `BacktestResult` (`src/uniquant/services/research_pipeline.py:165-173`).

### Signal and Backtest Boundary

`TradingSignal` is the typed bridge between brain outputs and hands/backtest:

- `src/uniquant/shared/interfaces.py:127-169` defines `TradingSignal(action, reason, confidence, shares, symbol, price, timestamp)` and maps legacy actions like `EXECUTE_BUY`, `EXECUTE_SELL`, `FORCE_EXIT`, and `CIRCUIT_BREAK`.
- `src/uniquant/signal/adapters.py:423-520` collects LPPL, CZSC, Wyckoff, FSM/DecisionBrain, regime, NTF, alpha score, and MA status signals from `data_pack`.
- `src/uniquant/hands/backtest/unified_engine.py:118-124` accepts `List[TradingSignal]` as its execution input.

`UnifiedBacktestEngine` enforces A-share execution constraints:

- T+1 pending-order execution and sell restriction: `src/uniquant/hands/backtest/unified_engine.py:173-230`, `306-320`.
- Required K-line columns and derived `pre_close`, `avg_daily_volume`: `src/uniquant/hands/backtest/unified_engine.py:272-286`.
- Cost/rule imports: `src/uniquant/hands/backtest/unified_engine.py:26-39`.
- Vectorized matching also includes limit, T+1, volume, commission, stamp duty, transfer fee, lot size, and slippage handling (`src/uniquant/hands/backtest/unified_matching_engine.py:145-261`).

## 4. 关键入口文件清单

| File | Role | Why it matters |
|---|---|---|
| `AGENTS.md` | Project control context | Defines current truth boundary, eight layers, high-risk files, and workflow rules. |
| `docs/index.md` | Documentation state boundary | Marks which docs are current and which package docs may be stale. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Staged analysis control | Defines stages 0-7, required artifacts, validation, and no-source-modification rule. |
| `pyproject.toml` | Package metadata | Defines Python version, dependencies, optional extras, and pytest settings. |
| `config/config.yaml` | Main runtime config | Defines data lake, cache, network, TDX, and source routing settings. |
| `src/uniquant/shared/interfaces.py` | Cross-layer contracts | Defines `MarketSignalContext`, `TradingSignal`, and protocols. |
| `src/uniquant/services/service_container.py` | Runtime DAG | Initializes and registers data, analysis, signal, backtest, and pipeline services. |
| `src/uniquant/services/data_service.py` | Data facade | Produces `data_pack` through `fetch_for_brain()`. |
| `src/uniquant/services/analysis_service_v2.py` | Single-ticker orchestrator | Runs engines and DecisionBrain; defines failure defaults. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy engine factory | Lazily imports engines and rebinds orchestrator after `AnalysisService` construction. |
| `src/uniquant/services/research_pipeline.py` | End-to-end pipeline | Connects analysis, signal collection, and backtest into `PipelineResult`. |
| `src/uniquant/signal/adapters.py` | Signal bridge | Converts engine and decision fields into `TradingSignal`. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed backtest engine | Executes `TradingSignal` against K-line data with A-share constraints. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized matching | Handles vectorized A-share execution constraints. |
| `src/uniquant/shared/limit_checker.py` | Limit rules | Used by backtest/matching to identify board and limit behavior. |
| `src/uniquant/shared/market_rules.py` | Market rules | Provides board lot size and rule metadata. |
| `src/uniquant/shared/cost_model.py` | Cost model | Defines commission, stamp tax, transfer fee, and slippage constants/functions. |
| `tests/test_engine_factory.py` | Engine factory tests | Stage 1 should use it to verify lazy factory behavior. |
| `tests/test_service_container.py` | Container tests | Verifies DI container singleton and initialization behavior. |
| `tests/test_e2e_pipeline.py` | Pipeline boundary tests | Exercises signal collector and backtest integration. |
| `tests/test_unified_matching.py` | Backtest/matching tests | Exercises A-share execution constraints and unified engine behavior. |

## 5. 高风险文件清单

| File | Risk | Stage to inspect deeply |
|---|---|---|
| `src/uniquant/services/__init__.py` | Public lazy import contract for services; import drift can break CLI/UI/test imports. | Stage 1 |
| `src/uniquant/shared/interfaces.py` | Cross-layer contract for `TradingSignal`, context, and protocols; changes can break brain, signal, backtest, and risk together. | Stages 1, 5, 6, 7 |
| `src/uniquant/shared/constants/__init__.py` | Aggregated constants used broadly; import/export mistakes become global runtime failures. | Stage 7 |
| `src/uniquant/services/service_container.py` | Service lifetime and dependency graph; wrong initialization order can create stale factory orchestrators or hidden coupling. | Stage 1 |
| `src/uniquant/services/data_service.py` | Data facade and `fetch_for_brain()` producer; malformed `data_pack` affects all engines. | Stage 2 |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker flow; default/failure values can create false signals or suppress real failures. | Stages 1, 3 |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy imports and `bind_orchestrator()` behavior; factory caches engines and clears them on orchestrator rebind. | Stage 1 |
| `src/uniquant/data/sources/tdx.py` | TDX path is central to local A-share data workflows. | Stage 2 |
| `src/uniquant/data/pipeline/data_validator.py` | OHLC correctness guardrail; failure here can contaminate backtests. | Stage 2 |
| `src/uniquant/signal/adapters.py` | Converts diverse engine outputs to executable signals; action mapping errors directly affect trades. | Stage 5 |
| `src/uniquant/hands/backtest/unified_engine.py` | User-facing signal-driven backtest; A-share rules and capital logic are high impact. | Stage 6 |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized execution constraints; any vectorization mismatch can create silent incorrect fills. | Stage 6 |
| `src/uniquant/shared/limit_checker.py` | Board and limit-up/down detection; errors distort execution feasibility. | Stage 6 |
| `src/uniquant/shared/market_rules.py` | Lot size and board rules; affects order sizing and limit rules. | Stage 6 |
| `config/config.yaml` | Global data/cache/network/source behavior; stale source classes or paths can break production runs. | Stages 2, 7 |

## 6. 当前架构优点

1. The runtime has a clear composition root. `ServiceContainer.initialize()` constructs data, engine factory, analysis service, signal collector, backtest engine, and research pipeline in one place (`src/uniquant/services/service_container.py:74-127`).
2. The main research path uses explicit typed result objects: `TickerAnalysisResult` (`src/uniquant/services/analysis_service_v2.py:49-58`) and `PipelineResult` (`src/uniquant/services/research_pipeline.py:37-50`).
3. The brain-to-hands boundary is normalized through `TradingSignal`, reducing action string mismatch risk (`src/uniquant/shared/interfaces.py:127-169`).
4. Signal conversion is centralized in `TradingSignalCollector` and adapter classes (`src/uniquant/signal/adapters.py:32-54`, `423-520`).
5. A-share execution rules are not left to strategy code; the backtest/matching layers enforce T+1, limit constraints, suspension/volume checks, costs, slippage, and lot sizing (`src/uniquant/hands/backtest/unified_engine.py:7-15`, `173-286`; `src/uniquant/hands/backtest/unified_matching_engine.py:145-261`).
6. Engine construction is lazy and isolated through `AnalysisEngineFactory`, reducing import-time cost and making engine initialization failures fail fast (`src/uniquant/services/analysis/engine_factory.py:33-48`).
7. The main docs now explicitly warn that historical package pages may be stale, reducing the chance of architecture decisions based on migration-era documents (`docs/index.md:93-124`).

## 7. 当前架构风险

1. `AnalysisEngineFactory` is first created with `DataService` as orchestrator and later rebound to `AnalysisService`. This is intentional and implemented through `bind_orchestrator()` (`src/uniquant/services/service_container.py:96-107`; `src/uniquant/services/analysis/engine_factory.py:20-32`), but Stage 1 must verify tests cover stale-engine clearing and adapter expectations.
2. `data_pack` remains a mutable dictionary across data, analysis, decision, signal, and pipeline layers. Although `MarketSignalContext` exists (`src/uniquant/shared/interfaces.py:41-124`), `AnalysisService` and `TradingSignalCollector` still use dict fields directly, so field drift is a real risk.
3. Failure defaults may affect trading behavior. Examples: LPPL failure sets `risk="ENGINE_FAILED"` and `bubble_confidence=1.0` (`src/uniquant/services/analysis_service_v2.py:378-396`); alpha failure sets `alpha_score=0.0` (`src/uniquant/services/analysis_service_v2.py:458-480`); CZSC/Wyckoff failures become neutral defaults (`src/uniquant/services/analysis_service_v2.py:430-456`). Stage 3 must classify which defaults are conservative versus signal-distorting.
4. `TradingSignalCollector.collect()` applies multiple adapters to the same `data_pack`, so conflicting BUY/SELL/HOLD signals can coexist before backtest selection (`src/uniquant/signal/adapters.py:450-520`). Stage 5 must inspect aggregation/priority behavior beyond collection.
5. `UnifiedBacktestEngine` indexes signals by `timestamp`; signals with no timestamp are grouped under `"unknown"` and will not naturally match a trading date (`src/uniquant/hands/backtest/unified_engine.py:288-300`). Stage 6 must verify intended behavior for pipeline-generated timestamps.
6. `config/config.yaml` still contains relative class paths like `data.sources.stock_sources.StockDataSource` (`config/config.yaml:109-121`) while runtime imports use package paths under `src/uniquant`; Stage 2 must verify source routing resolves these correctly.
7. The factor subsystem is currently in flux: many `brain/factors/auto_mined` files are deleted in the working tree. Stage 4 must avoid relying on historical factor audit reports without checking current source.
8. UI and live-readiness are only lightly covered in Stage 0. Stage 7 must inspect dashboard behavior, secrets/config handling, operational failure paths, and whether live trading is only simulated or executable.

## 8. 当前事实、历史文档、待验证假设

### 当前事实

- Eight runtime packages exist under `src/uniquant/`.
- `ServiceContainer.initialize()` registers `storage`, `calendar`, `cache`, `data_service`, `engine_factory`, `market_cache`, `analysis_service`, `backtest_engine`, `signal_collector`, and `research_pipeline`.
- `DataService.fetch_for_brain()` returns `stock`, `bench`, and `etf`.
- `AnalysisService.run_ticker_analysis()` is the current single-ticker orchestrator.
- `UnifiedResearchPipeline.run()` is the current end-to-end analysis/signal/backtest pipeline.
- `TradingSignal` is the typed bridge between signal and backtest.

### 历史文档不可直接信任

- Any document under `docs/packages/` that says `data`, `signal`, or `hands` is missing is stale according to `docs/index.md:93-124` and current source layout.
- Older audit or migration reports under `docs/` may describe target state, pre-remediation gaps, or old module locations. Use them only as background after checking source.
- Factor reports generated before the current `auto_mined` deletions cannot be treated as current Stage 4 evidence.

### 待验证假设

- Source routing in `config/config.yaml` still matches actual import paths and data source implementations.
- Engine defaults in `AnalysisService` are conservative for trading and do not create hidden false positives/negatives.
- Signal conflict resolution is deterministic and tested beyond simple collection.
- Backtest signal timestamps produced by pipeline are aligned with historical K-line dates or intentionally generate no historical trades.
- Service container initialization tests cover the current `engine_factory` rebind behavior.

## 9. Stage 1 输入清单

Stage 1 should start from this artifact and inspect:

- `src/uniquant/services/service_container.py`
- `src/uniquant/services/__init__.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis/engine_factory.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/signal/adapters.py`
- `tests/test_engine_factory.py`
- `tests/test_service_container.py`
- `tests/test_phase4_2_contracts.py`
- `tests/test_e2e_pipeline.py`

Questions for Stage 1:

1. Does `ServiceContainer.initialize()` have a fully acyclic and test-covered initialization order?
2. Does `AnalysisEngineFactory.bind_orchestrator()` always run before any engine is accessed in production?
3. Do analysis, data, cache, and market cache boundaries remain explicit?
4. Are failure paths in `run_ticker_analysis()` and `UnifiedResearchPipeline.run()` observable enough for batch runs and UI?
5. Are services imported lazily and safely through `src/uniquant/services/__init__.py`?

## 10. 校验清单

- [x] Covered all eight modules: `shared`, `data`, `brain`, `signal`, `hands`, `risk`, `services`, `ui`.
- [x] Explained the DAG direction and the concrete `ServiceContainer.initialize()` sequence.
- [x] Listed more than 10 key files and tied each to a runtime concern.
- [x] Clearly marked old docs under `docs/packages/` and historical audit/migration reports as not directly trustworthy.
- [x] Bound architecture conclusions to concrete files, classes, functions, config keys, or tests.
- [x] Did not modify source code.
- [x] Did not claim test results; no tests were run for Stage 0.

## 11. 阶段结论

The current UniQuant architecture is service-orchestrated rather than package-autonomous: lower layers provide capabilities, while `services` composes the runtime path from data to brain, signal, hands/backtest, and UI-facing pipeline results. The most important architecture boundary is the mutable `data_pack` plus `TradingSignal` bridge. The clearest near-term analysis risks are service factory rebinding, data_pack field drift, signal conflict behavior, and historical backtest timestamp alignment.

Stage 1 should now verify the services layer in detail, starting with the initialization topology, lazy import/rebind behavior, and failure paths.
