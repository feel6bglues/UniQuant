# AGENTS.md - UniQuant Project Control Context

> ⚠️ **MUST READ FIRST** — Read `CLAUDE.md` in the project root before any other file. It contains the 10 coding rules that govern all code generation in this project. Every edit, test, and commit must follow those rules. Treat them as non-negotiable.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-07-13. **Updated 2026-07-13 (v6 修复执行)**: 6 路并行红蓝对抗 + TDD 全量分析完成 — 83 项声明核实 (88% 准确率), 15 项新发现修复。R0 代码修复: signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC 死代码跟踪)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。纠正 v5 虚假完成声明 (UI except 仍为 17 处, 非 2)。全部 1678 测试通过, 0 ruff。死代码库存更新至 ~2,819 LOC (含新发现)。剩余: R1-06 过户费 DRY 统一、R3-N01 45 零覆盖文件、45 files at 0% (3,791 LOC) — unchanged.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-07-06. Two re-analysis campaigns completed: (1) Phases 0-9 baseline (2026-06-30) covering baseline audit, worktree diff, engine correctness, backtest trust, data pipeline, signal system, engineering health, production readiness, governance, and final roadmap. (2) Phase A-K v2.0 deep audit (2026-07-06) covering code quality, test quality, data reliability, engine runtime behavior, backtest trust, signal audit, performance, security, observability, scorecard, and roadmap. **Updated 2026-07-09**: Live system map (I_live_system_map.md) documenting corrected metrics after 256-file verification sweep, dead code inventory (~1,960 LOC), ranked active bugs, and data path heat map. **Updated 2026-07-10**: 5-round multi-pass source code investigation completed. 256 files verified, 17/18 P0/P1 fixes confirmed (1 bare `except Exception:` remains at research_pipeline.py:244), 15 `except Exception` patterns narrowed, research_pipeline thread safety added, 51 new tests, 4 dead code files archived, dead code ~2,298 LOC. See `docs/reanalysis/Z_investigation_report_20260710.md`. **Updated 2026-07-10 (TDD Red-Blue)**: Comprehensive multi-pass TDD evaluation with 5-layer parallel red-blue adversarial analysis completed. 74 doc claims verified (87% accuracy, 55 Blue/8 Red/11 N/A). 0 bare `except:` across all layers. 224 total `except Exception:` mapped by layer. Dead code corrected to ~2,225 LOC (data_pipeline_service found ACTIVE, not semi-dead). 45 files at 0% coverage (3,791 LOC). 1 truly weak test. See `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md`. This file is the first local source context for agents working in this repository.

---

## Current State

UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot from 2026-07-13 (post-v6 TDD-Red-Blue):

| Metric | Current value |
|---:|---:|
| Python files under `src/uniquant/` (active) | 252 |
| Python active LOC under `src/uniquant/` | 60,351 |
| Archived files (dead code) | 6 (2,217 LOC) |
| Test files under `tests/` | 128 |
| Approximate test functions | 1,641 |
| Tests passing | 1,842 |
| Ruff issues | 0 |
| Test coverage | 56.18% |
| Dead code (archived) | ~2,217 LOC (3.5%) |
| Functions total | 2,249 |
| `except Exception:` total | 225 (all layers) |
| `except:` (bare) total | 0 |
| Doc claims verified | 83 (88% accurate) |
| Files at 0% coverage | 35 (reduced from 45, ~2,500 LOC) |

Comprehensive re-analysis complete (Phases 0-9): full baseline audit, worktree diff, 8-engine correctness audit, 7-line backtest trust audit, data pipeline reliability, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for full reports.

Phase A-K v2.0 deep audit (2026-07-06): code quality (Fair, 116 duplicates, Wyckoff complexity 40), test quality (mutmut baseline broken), data reliability (B+, 5934/5934 100% readable), engine runtime behavior (B+, 2 critical bugs FSM+Wyckoff), backtest trust (B+, 7/7 lines PASS), signal audit (A-, signal/db.py 93% coverage), performance (A-, 64.4 MB/s), security (B+), observability (2/5, metrics F). Overall scorecard: **3.29/5.0 — B (conditional ready)**. See `docs/reanalysis/` for all 15 reports.

**Corrections from live system map (2026-07-09)**: Wyckoff complexity 76→40 (class max function); signal/db.py coverage 0%→93% (35 tests); eastmoney LOC 1,094→3 (refactored to 4 files). See `I_live_system_map.md`.

5 pre-existing test failures resolved (bc6337bc). 0 ruff issues, 0 pre-existing failures.

## Recent Work (2026-07-13) — v6 修复执行 (六路并行红蓝对抗)

| Phase | Tasks | Summary | Verification |
|---|---|---|---|---|
| **R0 (2026-07-13)** | 4 项代码修复 + 测试导入更新 | signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。更新 7 测试文件导入路径。 | 1678 passed, 0 ruff |
| **R1 (2026-07-13)** | 工程窄化 + 文档纠正 | lppl_visualizer.py 已有 exc_info=True (确认已存在无需改)、AGENTS.md 指标更新 (252 文件/60,351 LOC 活跃)、死代码 ~2,217 LOC 归档。 | 1678 passed, 0 ruff |

**Key corrections from v6 multi-pass verification (2026-07-13):**
- 纠正 v5 虚假完成声明: ui/ `except Exception` 仍为 17 处 (非 2), 从未被纠正
- 新发现死代码: factor_governance.py (156 LOC), portfolio_engine.py (376 LOC) — 已归档
- 纠正: 8 数据源 (非 7), Wyckoff 复杂度 45 (非 40), computation.py 393 LOC (非 242)
- 纠正: interfaces.py 5 个 Protocol (非 4), Alpha score=0.0 3 处 (非 2)
- 纠正: 函数总数 2,249 (非 2,262), except Exception 225 (非 224)
- 确认: 17/17 P0/R 修复全部存在, signal/ 层 100% 文档准确
- 确认: manager_logic.py 6 处 except Exception 已有 as e + exc_info=True, 无需窄化
- 剩余: R1-06 过户费 DRY 统一 (WONTFIX: 3 实现点, 向量化/标量签名不兼容), R3-N01 45 零覆盖文件 (~16h)

## Phase 2/3 Completion (2026-07-08)

All Phase 2 and Phase 3 small/independent tasks executed:

| Task | Summary | Files Changed |
|---|---|---|
| #33 | Expand E2E tests: 3 new engine coverage classes (UnifiedBacktest, SignalArbitrator, UnifiedMatching) | `test_e2e_integration_qa.py` |
| #45 | Signal timeout check in arbitrator: discard signals older than `max_age_seconds` | `arbitrator.py` |
| #47 | Remove `portfolio_engine.py` from `__init__.py` exports | `hands/backtest/__init__.py` |
| #48 | Narrow 8 broad `except Exception:` to specific types in `backtest.py` | `hands/strategies/backtest.py` |
| #49 | Create `brain/wyckoff/constants.py` with 7 named constants; migrate 4 Wyckoff files | `constants.py` (new), `analysis.py`, `engine.py`, `state.py` |
| #50 | Add adapter auto-discovery (`AdapterRegistry.discover()`) | `adapters.py` |
| #51 | Unify position calculation: add `PositionSizerProtocol` to `UnifiedBacktestEngine` | `unified_engine.py` |
| #52 | Create `.github/workflows/benchmark.yml` CI workflow | `benchmark.yml` (new) |
| #53 | Add assertions to 2 weak test functions | `test_indicators.py`, `test_scan_service.py` |
| #57 | Remove 12 vulture-identified dead code items (8 files) | `computation.py`, `numba_optimizer.py`, `events.py`, `baostock.py`, `unified_matching_engine.py`, `data.py` |
| #66 | Replace 2 `datetime.now()` in `time_provider.py` with `self.now()` | `time_provider.py` |

Test results: 245 passed, 1 skipped, 0 ruff issues.

## Remaining Untracked Files

`docs/analysis/` (7 .md files), `docs/pipeline_5round_report.md`, `.coverage`, `data/trade_calendar.csv`, `results/` — not committed.

---

## Control Documents

Read these first:

| File | Purpose |
|---|---|---|
| `AGENTS.md` | First project control context. Updated 2026-07-10 with live system map ref. |
| `docs/reanalysis/I_live_system_map.md` | Live system map (2026-07-09): corrected metrics, dead code inventory, ranked active bugs, data path heat map. |
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
| `docs/reanalysis/Z_investigation_report_20260710.md` | 5-round multi-pass source code investigation (2026-07-10, updated w/ red-blue corrections) — verified 256 files, 17/17 fixes, 15 residual except patterns, research_pipeline thread safety, 51 new tests, 4 dead code files archived |
| `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md` | Comprehensive TDD red-blue adversarial analysis (2026-07-10) — 74 doc claims verified (87% accuracy), 224 except Exception mapped by layer, dead code corrected to ~2,225 LOC, 45 files at 0% coverage (3,791 LOC), 1 truly weak test |
| `docs/remediation/v5_remediation_work_list_20260710.md` | Verified remediation work list (2026-07-10) — all 11 P0 fixes confirmed FIXED, 14 remaining items ranked R0-R3 with file:line evidence, zero hallucination gate |
| `docs/remediation/red_blue_remediation_plan.md` | Red-blue remediation execution plan: Phase 0 (P0-01 through P0-10 core bugs), Phase 1 (P1-01 through P1-07 engineering health), Phase 2 (documentation + portfolio research). |
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
|---|---:|---:|---:|
| `shared` | `src/uniquant/shared/` | 44 | Protocols, constants, config, exceptions, cache, logging, A-share rules, costs, slippage, price collars (dead), time_provider, event_types, factor_governance (dead), config_models. |
| `data` | `src/uniquant/data/` | 67 | Multi-source data ingestion, TDX/local/online sources, data lake, managers, parsers, cleaners, validators, adjusters. |
| `brain` | `src/uniquant/brain/` | 54 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 8 | Standard signal models, adapters, normalization, aggregation, quality checks. |
| `hands` | `src/uniquant/hands/` | 33 | Backtesting, matching, portfolio engine (dead), strategy framework, reports, robustness and sensitivity tools. |
| `risk` | `src/uniquant/risk/` | 6 | Position sizing, drawdown, EVT, structural risk, portfolio optimization. |
| `services` | `src/uniquant/services/` | 31 | DAG service container, analysis orchestration, data service, cache coordination, reports, scan, health, research pipeline. ⚠️ 1,651 LOC legacy dead code (analysis_service_legacy.py). |
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

All phases verified: **1678 tests pass, baseline 100% consistent**. 0 pre-existing failures.

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
| `I_live_system_map.md` | Corrected live system map (2026-07-09) | 256 files verified |

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
| Factor registration/access | `brain/factors/registry.py` (actual) NOT `shared/archive/factor_governance.py` (dead code, archived) | shared/ deprecated with warning |
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
| System overview / metrics | `docs/reanalysis/I_live_system_map.md` | 256 files verified; dead code inventory; ranked active bugs; data path heat map |
| Red-blue analysis | `docs/reanalysis/E_red_blue_analysis.md` | 22-issue confrontation corrected bug counts (4→6), defense lines (5✅/1⚠️/1❌), capability matrix (15✅/2⚠️/3❌) |
| 5-round investigation | `docs/reanalysis/Z_investigation_report_20260710.md` | 256 files verified, 17/17 fixes confirmed, 15 residual except patterns |
| 修复并行化分析 | `docs/remediation/parallel_analysis.md` | 34 项任务并行调度: 24h→7.5h (3.2x) |
| Shenzhen transfer fee exemption | `src/uniquant/hands/backtest/unified_matching_engine.py` + `unified_engine.py` | P1-01: SZ stocks `_has_transfer_fee()` returns `False`; both matching and engine layers updated |
| Adapter alpha=0.0 | `signal/adapters.py:362` | P0-01 **FIXED**: `elif 0 < score < 0.3:` excludes 0.0 (was `elif score < 0.3:` → false SELL) |
| fillna(0.0) factor distortion | `brain/factors/composer.py:183,204,276` | P0-04 **FIXED**: all 3 fillna(0.0) removed |
| Pipeline bare except | `services/research_pipeline.py:239` | P0-08 **FIXED**: narrowed to specific exceptions |
| Wyckoff bare except | `brain/wyckoff/engine.py:251,261,1575,1591` | P0-09 **FIXED**: 4 bare excepts narrowed |
| Signal timeout disabled | `signal/arbitrator.py:39` | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` — backtest-aware context needed for enable |
| price_collar dead | `shared/price_collar.py` | Zero production callers; remove from P1 consideration |
| DynamicSlippage dead | `shared/slippage_model.py:DynamicSlippage` | Never instantiated in default backtest path |
| BoardType unified | `shared/board_registry.py` | 116 LOC — BoardType dual system resolved via registry |
