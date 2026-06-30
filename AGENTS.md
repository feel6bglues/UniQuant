# AGENTS.md - UniQuant Project Control Context

> ⚠️ **MUST READ FIRST** — Read `CLAUDE.md` in the project root before any other file. It contains the 10 coding rules that govern all code generation in this project. Every edit, test, and commit must follow those rules. Treat them as non-negotiable.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-06-30. Comprehensive re-analysis (Phases 0-9) completed — baseline audit, worktree diff, engine correctness, backtest trust, data pipeline, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for 10 reports covering all phases. This file is the first local source context for agents working in this repository.

---

## Current State

UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot from 2026-06-30 (post-0-9-reanalysis):

| Metric | Current value |
|---:|---:|
| Python files under `src/uniquant/` | 254 |
| Python LOC under `src/uniquant/` | 62,389 |
| Test files under `tests/` | 120 |
| Approximate test functions | 1,435 |

Comprehensive re-analysis complete (Phases 0-9): full baseline audit, worktree diff, 8-engine correctness audit, 7-line backtest trust audit, data pipeline reliability, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for full reports.

5 pre-existing test failures unchanged (survivorship_warning + unified_matching). 29 ruff issues (20 auto-fixable).

---

## Control Documents

Read these first:

| File | Purpose |
|---|---|---|
| `AGENTS.md` | First project control context. |
| `docs/index.md` | Documentation entry point and state boundary. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Direct-call prompt playbook for staged system analysis. |
| `docs/remediation/FULL_STOCK_TEST_PLAN.md` | Full stock test plan (canary/medium/full staging). |
| `pyproject.toml` | Real package metadata, dependencies, pytest config. Use root file, not docs copies. |
| `config/config.yaml` | Main runtime configuration. |
| `src/uniquant/shared/interfaces.py` | Typed cross-layer contracts including `TradingSignal`, `ResearchDataPack`, `RegimeOutput`, `LPPLOutput`, `CZSCOutput`, `NtfOutput`, `WyckoffOutput`, `AlphaOutput`, and protocols. |
| `src/uniquant/services/service_container.py` | DAG dependency injection and service initialization. |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker analysis orchestrator. |
| `src/uniquant/services/research_pipeline.py` | End-to-end research pipeline. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy analysis engine factory. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters. |
| `src/uniquant/signal/arbitrator.py` | Sell-priority signal arbitration with confidence-based rules. |
| `src/uniquant/shared/time_provider.py` | RealTimeProvider / FrozenTimeProvider for testable time. |
| `docs/analysis/wyckoff_research_report.md` | Wyckoff WSO+WSS+Resonance — 7-phase empirical research report on 22,148 A-share observations. All findings traceable to Phase I–VII run output. |
| `docs/reanalysis/` | 10 comprehensive re-analysis reports (Phases 0-9) covering baseline, worktree, engines, backtest trust, data pipeline, signals, engineering health, production readiness, governance, and final roadmap. |
| `src/uniquant/shared/event_types.py` | Event/Command base and domain events. |
| `src/uniquant/shared/factor_governance.py` | FactorManifest / FactorRegistry with admission gate. |
| `src/uniquant/shared/config_models.py` | RefactoringConfig / FeatureFlags for staged migration. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed signal-driven backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized A-share matching engine. |
| `scripts/staged_full_scan.py` | Staged full-stock pipeline scan (canary/medium/full stages). |

Historical architecture and migration documents under `docs/` are useful background, but many still describe target state or pre-remediation gaps. Prefer current source code and the control documents above.

---

## Layer Responsibilities

| Layer | Path | Files | Responsibility |
|---|---|---:|---|
| `shared` | `src/uniquant/shared/` | 44 | Protocols, constants, config, exceptions, cache, logging, A-share rules, costs, slippage, price collars, time_provider, event_types, factor_governance, config_models. |
| `data` | `src/uniquant/data/` | 65 | Multi-source data ingestion, TDX/local/online sources, data lake, managers, parsers, cleaners, validators, adjusters. |
| `brain` | `src/uniquant/brain/` | 55 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 8 | Standard signal models, adapters, normalization, aggregation, quality checks. |
| `hands` | `src/uniquant/hands/` | 34 | Backtesting, matching, portfolio engine, strategy framework, reports, robustness and sensitivity tools. |
| `risk` | `src/uniquant/risk/` | 7 | Position sizing, drawdown, EVT, historical risk, structural risk, portfolio optimization. |
| `services` | `src/uniquant/services/` | 32 | DAG service container, analysis orchestration, data service, cache coordination, reports, scan, health, research pipeline. |
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

## Phase 0-6 Completion Status

All phases verified: **1426 tests pass, baseline 100% consistent**. 5 pre-existing failures in survivorship_warning + unified_matching.

| Phase | Scope | Status | Key deliverables |
|---|---|---|---|---|
| **0** | LPPL SELL priority, baseline tooling | ✓ | `unified_engine.py` SELL-before-BUY fix, `tests/benchmark/golden_20.txt`/`golden_100.txt`, `scripts/capture_baseline.py` + `compare_baseline.py` |
| **1.1–1.2** | BacktestResult metadata, typed contracts | ✓ | `BacktestResult.metadata`, `RealTimeProvider`, `FrozenTimeProvider`, domain events, `FactorManifest`/`FactorRegistry` |
| **1.4** | Feature flags, config models | ✓ | `RefactoringConfig`, `FeatureFlags`, `config.yaml` refactoring section, `ServiceContainer` DI |
| **2** | SignalArbitrator, TimeProvider adoption | ✓ | `SignalArbitrator` (sell-priority, confidence-based), 7 tests, pipeline integration, `FactorRegistry` admission gate |
| **3** | 6-engine typed output migration | ✓ | `RegimeOutput`, `LPPLOutput`, `NtfOutput`, `CZSCOutput`, `WyckoffOutput`, `AlphaOutput`, `DecisionOutput`, `MarketSignalContext` direct pass |
| **4** | Pipeline typing, engine output typing, batch parallelization | ✓ | `ResearchDataPack` + feature flag in pipeline & analysis & data services; 4 engines return typed outputs; `run_batch()` ThreadPoolExecutor + atomic checkpoint; `factor_gate: "block"` |
| **5** | Remediation — 7 threads (A–G) via TDD | ✓ | `use_research_data_pack` default flipped to `true`; Wyckoff 12 failures fixed; TradeCalendar AkShare auto-update; ResultStore persistence; DataFetcher single entry; BacktestResult.compare(); dead code cleanup; **Full stock test: 5934/5934 success (100%)** |
| **6** | Regime reliability — fail-open fix, dead code, TOCTOU | ✓ | `RegimeDetector.detect()` fail-open hardened (entropy/turnover NaN → UNKNOWN); `_validate_input_data()` wired; `_check_sell_conditions` FROZEN dead code removed; `MarketLevelCache.get_or_compute_regime()` TOCTOU fix; 16 new tests |

**Design**: All typed outputs coexist with legacy `Dict[str, Any]` keys for backward compatibility. Feature flags default ON for `use_research_data_pack` (flipped Phase 5 Thread A). `factor_gate: "block"` prevents unregistered factors.

## Re-analysis (2026-06-30)

Comprehensive 9-phase re-analysis completed. Reports in `docs/reanalysis/`:

| Report | Phase | Trust Rating |
|---|---|---|
| `00_baseline_audit.md` | Baseline test/lint/import audit | ✅ 1426/1431 pass |
| `01_worktree_diff_analysis.md` | Worktree diff + stash analysis | 46-file commit classified |
| `02_engine_correctness_audit.md` | 8 engines graded | A- |
| `03_backtest_trust_audit.md` | 7 A-share defense lines verified | A- |
| `04_data_pipeline_reliability.md` | 5-source routing + pipeline | B+ |
| `05_signal_system_audit.md` | 8 adapters + arbitrator | A |
| `06_engineering_health.md` | Lint, TODOs, imports | A- |
| `07_production_readiness.md` | Security, config, observability | B+ |
| `08_governance_testing.md` | Test structure, CI gaps | B+ |
| `09_final_roadmap.md` | Priority roadmap P0-P3 | — |

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
- **Sync docs with every change**: After any code modification (feature, refactor, bugfix), update `AGENTS.md` and all affected documentation under `docs/`. At minimum refresh file counts, LOC, test counts, and phase status. Treat documentation drift as a blocker, not a backlog item.

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

# Full stock pipeline scan (canary → medium → full)
python3 scripts/staged_full_scan.py --stage canary --max-workers 4
python3 scripts/staged_full_scan.py --stage medium --max-workers 4 --seed 42
python3 scripts/staged_full_scan.py --stage full --max-workers 4

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

> **2026-06-12 update**: G-1 through G-4 have all been closed and verified in the institutional closure review. See `docs/analysis/institutional/17_institutional_closure_review_report.md` §Phase 6 Gap Review for the verified closure evidence.

### Quick Start For New Tasks

| If working on... | Read this first | And be aware of |
|---|---|---|
| Time-dependent code | `shared/time_provider.py` | 2 guarded `datetime.now()` remain in `time_provider.py` FrozenTimeProvider fallback |
| Factor registration/access | `brain/factors/registry.py` (actual) NOT `shared/factor_governance.py` (dead code) | shared/ deprecated with warning |
| Baseline/regression testing | `scripts/capture_baseline.py` + `compare_baseline.py` | Phase 0 all committed |
| Event-driven features | `shared/event_bus.py` (sync) + `shared/event_bus.py` (async) | AsyncEventBus deployed with 9 tests |
| Pipeline typing / data pack | `shared/interfaces.py` `ResearchDataPack` + `services/analysis_service_v2.py` dual-path | Feature flag `use_research_data_pack: true` default (flipped Phase 5); `to_dict()` flattens `metadata` for signal collector |
| Engine output typing | `shared/interfaces.py` (LPPLOutput/CZSCOutput/NtfOutput/WyckoffOutput) + engine files in `services/analysis/` | 4 engines return typed outputs; field annotations in ResearchDataPack are forward references |
| Batch research | `services/research_pipeline.py` `run_batch()` | ThreadPoolExecutor + atomic checkpoint; input order preserved via result map |
| Research result persistence | `shared/result_store.py` + `services/research_pipeline.py` | JSON file store under `results/{date}/{symbol}.json`; ResultStore.save() called after each successful run() |
| TradeCalendar | `data/managers/trade_calendar_manager.py` | AkShare auto-update with stale cache check (>180 days); hardcoded 2024-2026 fallback |
| BacktestResult compare | `hands/backtest/unified_engine.py` `BacktestResult.compare()` | Returns diff dict for parameter sensitivity analysis |
| Full stock scan | `scripts/staged_full_scan.py` + `docs/remediation/FULL_STOCK_TEST_PLAN.md` | 3-stage scan (canary→medium→full); `--stage canary|medium|full`; checkpoint resume; per-engine breakdown; error classification |
| Regime detection safety | `brain/regime/regime_detector.py` fail-open paths | Phase 6: entropy/turnover NaN → UNKNOWN (was NORMAL); `_validate_input_data()` wired into `detect()` |
| Market cache TOCTOU | `services/market_cache.py` `get_or_compute_regime()` | Phase 6: atomic get-or-compute prevents parallel recompute in batch mode |
| FSM dead code | `brain/fsm/fsm.py` `_check_sell_conditions()` | Phase 6: FROZEN removed (unreachable — veto fires first); STRESSED only |
