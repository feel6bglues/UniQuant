# AGENTS.md - UniQuant Project Control Context

> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-06-12. Institutional closure review completed — P0-3/P0-4 Closed, P0-2/P0-5 Partially closed, P0-1 Open. See `docs/analysis/institutional/17_institutional_closure_review_report.md` for full status matrix. This file is the first local context source for Codex-style agents working in this repository.

---

## Current State

UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot from 2026-06-12 (post-institutional-audit, post-Phase-0~3):

| Metric | Current value |
|---|---:|
| Python files under `src/uniquant/` | 269 |
| Python LOC under `src/uniquant/` | 59,441 |
| Test files under `tests/` | 90 |
| Approximate test functions | 1,034 |

Phases 0-3 (typed contract migration, SignalArbitrator, 6-engine migration) complete — 1034 tests pass, baseline 100% consistent.

---

## Control Documents

Read these first:

| File | Purpose |
|---|---|
| `AGENTS.md` | First project control context. |
| `docs/index.md` | Documentation entry point and state boundary. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Direct-call prompt playbook for staged system analysis. |
| `pyproject.toml` | Real package metadata, dependencies, pytest config. Use root file, not docs copies. |
| `config/config.yaml` | Main runtime configuration. |
| `src/uniquant/shared/interfaces.py` | Typed cross-layer contracts including `TradingSignal` and protocols. |
| `src/uniquant/services/service_container.py` | DAG dependency injection and service initialization. |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker analysis orchestrator. |
| `src/uniquant/services/research_pipeline.py` | End-to-end research pipeline. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy analysis engine factory. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters. |
| `src/uniquant/signal/arbitrator.py` | Sell-priority signal arbitration with confidence-based rules. |
| `src/uniquant/shared/time_provider.py` | RealTimeProvider / FrozenTimeProvider for testable time. |
| `src/uniquant/shared/event_types.py` | Event/Command base and domain events. |
| `src/uniquant/shared/factor_governance.py` | FactorManifest / FactorRegistry with admission gate. |
| `src/uniquant/shared/config_models.py` | RefactoringConfig / FeatureFlags for staged migration. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed signal-driven backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized A-share matching engine. |

Historical architecture and migration documents under `docs/` are useful background, but many still describe target state or pre-remediation gaps. Prefer current source code and the control documents above.

---

## Layer Responsibilities

| Layer | Path | Files | Responsibility |
|---|---|---:|---|
| `shared` | `src/uniquant/shared/` | 41 | Protocols, constants, config, exceptions, cache, logging, A-share rules, costs, slippage, price collars, time_provider, event_types, factor_governance, config_models. |
| `data` | `src/uniquant/data/` | 65 | Multi-source data ingestion, TDX/local/online sources, data lake, managers, parsers, cleaners, validators, adjusters. |
| `brain` | `src/uniquant/brain/` | 74 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 7 | Standard signal models, adapters, normalization, aggregation, quality checks. |
| `hands` | `src/uniquant/hands/` | 34 | Backtesting, matching, portfolio engine, strategy framework, reports, robustness and sensitivity tools. |
| `risk` | `src/uniquant/risk/` | 7 | Position sizing, drawdown, EVT, historical risk, structural risk, portfolio optimization. |
| `services` | `src/uniquant/services/` | 31 | DAG service container, analysis orchestration, data service, cache coordination, reports, scan, health, research pipeline. |
| `ui` | `src/uniquant/ui/` | 8 | Streamlit dashboard, health check, UI manager logic, LPPL visualization. |

---

## Core Runtime Flow

Single ticker research path:

1. `ServiceContainer.initialize()` constructs data, cache, analysis, signal, backtest, and research pipeline services.
2. `DataService.fetch_for_brain()` returns `data_pack` with stock data and metadata.
3. `AnalysisService.run_ticker_analysis()` runs regime, LPPL, NTF, CZSC, Wyckoff, alpha, and derived indicator logic.
4. `DecisionBrain` produces the final decision payload.
5. `TradingSignalCollector` converts engine outputs into typed `TradingSignal` objects.
6. `UnifiedBacktestEngine.run()` executes signals against K-line data using A-share constraints.
7. `PipelineResult` returns `data_pack`, decision, signals, and `BacktestResult`.

Key files:

| Concern | File |
|---|---|
| Service DAG | `src/uniquant/services/service_container.py` |
| Analysis orchestration | `src/uniquant/services/analysis_service_v2.py` |
| Pipeline orchestration | `src/uniquant/services/research_pipeline.py` |
| Engine lazy loading | `src/uniquant/services/analysis/engine_factory.py` |
| Signal conversion | `src/uniquant/signal/adapters.py` |
| Signal arbitration | `src/uniquant/signal/arbitrator.py` |
| Factor governance | `src/uniquant/shared/factor_governance.py` |
| Feature flags | `src/uniquant/shared/config_models.py` |
| Time provider | `src/uniquant/shared/time_provider.py` |
| Backtest execution | `src/uniquant/hands/backtest/unified_engine.py` |
| Vectorized matching | `src/uniquant/hands/backtest/unified_matching_engine.py` |

---

## A-Share Rules To Preserve

| Rule | Current source |
|---|---|
| Main board limit up/down | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| STAR/GEM limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| Beijing Stock Exchange rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| ST stock limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| T+1 sell restriction | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/hands/backtest/unified_matching_engine.py` |
| Commission, stamp duty, transfer fee | `src/uniquant/shared/cost_model.py` |
| Slippage | `src/uniquant/shared/slippage_model.py`, matching engines |
| Price collar | `src/uniquant/shared/price_collar.py` |
| Lot size | `src/uniquant/shared/market_rules.py` |

Any change touching these rules requires focused tests and explicit review.

---

## High-Risk Files

| File | Why it is risky |
|---|---|
| `src/uniquant/services/__init__.py` | Lazy import contract for service package. |
| `src/uniquant/shared/interfaces.py` | Cross-layer typed contracts and protocol boundaries. |
| `src/uniquant/shared/constants/__init__.py` | Aggregated constants export used broadly. |
| `src/uniquant/services/service_container.py` | Runtime dependency graph and service lifetime. |
| `src/uniquant/services/analysis_service_v2.py` | Main analysis workflow and failure defaults. |
| `src/uniquant/services/analysis/engine_factory.py` | Engine registration and lazy import behavior. |
| `src/uniquant/data/sources/tdx.py` | TDX source path used across data workflows. |
| `src/uniquant/data/pipeline/data_validator.py` | OHLC data correctness guardrail. |
| `src/uniquant/signal/adapters.py` | Converts heterogeneous engine outputs into executable signals. |
| `src/uniquant/hands/backtest/unified_engine.py` | User-facing typed backtest behavior. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | A-share execution constraints in vectorized matching. |
| `config/config.yaml` | Global runtime behavior. |

---

## Phase 0-3 Completion Status

All phases verified: **1034 tests pass, baseline 100% consistent**. No regressions.

| Phase | Scope | Status | Key deliverables |
|---|---|---|---|
| **0** | LPPL SELL priority, baseline tooling | ✓ | `unified_engine.py` SELL-before-BUY fix, `golden_20/100.txt`, `scripts/capture_baseline.py` + `compare_baseline.py` |
| **1.1–1.2** | BacktestResult metadata, typed contracts | ✓ | `BacktestResult.metadata`, `RealTimeProvider`, `FrozenTimeProvider`, domain events, `FactorManifest`/`FactorRegistry` |
| **1.4** | Feature flags, config models | ✓ | `RefactoringConfig`, `FeatureFlags`, `config.yaml` refactoring section, `ServiceContainer` DI |
| **2** | SignalArbitrator, TimeProvider adoption | ✓ | `SignalArbitrator` (sell-priority, confidence-based), 7 tests, pipeline integration, `FactorRegistry` admission gate |
| **3** | 6-engine typed output migration | ✓ | `RegimeOutput`, `LPPLOutput`, `NtfOutput`, `CZSCOutput`, `WyckoffOutput`, `AlphaOutput`, `DecisionOutput`, `MarketSignalContext` direct pass |

**Design**: All typed outputs coexist with legacy `Dict[str, Any]` keys for backward compatibility. Feature flags in `RefactoringConfig` default OFF.

---

## Working Rules For Agents

- Start with current source code, not historical docs.
- Before meaningful multi-file work, create a short plan.
- Prefer narrow analysis and narrow edits.
- Do not revert user or prior-agent changes.
- Treat the working tree as possibly dirty. Inspect `git status --short` before edits.
- Use `rg` and `rg --files` for searches.
- Use `apply_patch` for manual file edits.
- For code changes, follow TDD where practical: identify failing path, add/update tests, implement, verify.
- For sensitive paths, review auth, data validation, injection risk, secrets, and error leakage.
- After meaningful changes, review the diff and record verification performed.

---

## Common Commands

```bash
# Install all optional extras
pip install -e ".[all]"

# Full test suite
pytest tests/ -q

# Baseline verification
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py

# Engine factory smoke tests
pytest tests/test_engine_factory.py -xvs

# Eight-layer import smoke
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# Config smoke
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# Service container smoke
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"

# Lint source
ruff check src/uniquant/

# Dashboard
streamlit run src/uniquant/ui/dashboard.py
```

Do not claim test results are current unless the command was run in the current working tree.

---

## Analysis Workflow

For systematic system analysis, use:

`docs/ANALYSIS_PROMPT_PLAYBOOK.md`

It defines stages 0-7:

0. Global architecture
1. Services orchestration
2. Data system
3. Brain engines
4. Factor system
5. Signal system
6. Backtest and matching
7. Risk and live-readiness

Each stage requires a plan, concrete artifacts, checkpoint context, and verification checklist.

---

## Known Gaps (Post-Phase 5) — Full Plan in `docs/GAP_REMEDIATION_PLAN.md`

> **2026-06-12 update**: G-1 through G-4 have all been closed and verified in the institutional closure review. The gap table below is retained as historical reference. See `docs/analysis/institutional/17_institutional_closure_review_report.md` §Phase 6 Gap Review for the verified closure evidence.

| ID | Gap | Priority | Status (2026-06-12) | Scope |
|---|---|---|---|---|
| G-1 | `TimeProvider` only deployed in 2 files; ~120 direct clock calls remain (`datetime.now`, `pd.Timestamp.now`, `time.time`) in 6 layers | P2 | ✅ **Closed** — 0 `pd.Timestamp.now`, 2 guarded `datetime.now`, 36 `time.time` for rate limiting | all layers |
| G-2 | Two `FactorRegistry` classes (shared/ governance with 0 users, brain/ de facto with 16 imports); admission gate is dead code | P1 | ✅ **Closed** — shared/ has deprecation warning; brain/ has `check_access()` + `set_mode()` + `FactorAccessLevel` | `shared/`, `brain/` |
| G-3 | Phase 0 deliverables (SELL priority, baseline scripts, golden lists, parquet data) exist only in working tree, never committed | **P0** | ✅ **Closed** — all files committed across 22-commit sequence | — |
| G-4 | EventBus is sync-only; no async variant blocks hot-path scaling | P2 | ✅ **Closed** — `AsyncEventBus` + `ThreadPoolExecutor` deployed; 9 async + 10 sync + 6 integration tests pass | `shared/` |

### Quick Start For New Tasks

| If working on... | Read this first | And be aware of |
|---|---|---|
| Time-dependent code | `shared/time_provider.py` + GAP_REMEDIATION_PLAN.md §G-1 | Layers still use raw `datetime.now()` |
| Factor registration/access | `brain/factors/registry.py` (actual) NOT `shared/factor_governance.py` (dead code) | GAP_REMEDIATION_PLAN.md §G-2 — governance is being merged into brain/ |
| Baseline/regression testing | `scripts/capture_baseline.py` + `compare_baseline.py` | GAP_REMEDIATION_PLAN.md §G-3 — Phase 0 is uncommitted |
| Event-driven features | `shared/event_bus.py` (sync) | GAP_REMEDIATION_PLAN.md §G-4 — async variant pending |
