# UniQuant Documentation Index

> Unified Quantitative Trading Platform for China A-share research, backtesting, and trading workflows.
>
> Updated: 2026-10-17. Post-simplification state. Live measurement: **232** Python files / **58,475** LOC under `src/uniquant/` (incl. the `research/` control plane), **214** test files / **3,093** test functions, **3,464 passed / 2 skipped / 0 failed / 0 error** (dev machine, with the gitignored data lake + the undeclared `czsc`), whole-package coverage **78.72%**, `ruff` 0. **真实 CI 口径**（依赖集 = `pip install -e ".[all,dev]"`，即**无 `czsc`**；且无数据湖 / 无通达信 / 无开发机兄弟仓）: **3,278 passed / 165 skipped / 0 failed / 0 error**（收集 3,443），coverage **77.47%** ≥ 门限 74（**余量 +3.47 pt**）—— 真实数据用例由 `requires_lake` / `requires_futures_lake` / `requires_gbbq` 三标记**声明式跳过**（见 `docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md` §7.6）。⚠️ **"CI 口径"必须连同依赖集一起报**：第四/五轮曾记 `3,081 passed / 151 skipped / 75.57%`，但那是在**装了未声明的 `czsc`** 的本机环境测的，**并非 CI 口径** —— 真实 CI 缺 `czsc` 故 4 个 `importorskip("czsc")` 模块整块不被收集（见报告 §7.9）。CI 曾长期红的第三个成因（**测试收集期中断**：硬编码开发机兄弟仓路径 → `ModuleNotFoundError` → 零用例执行 exit 2）由第五轮修复，并新增两个防回归守卫 `tests/test_no_dev_absolute_paths.py` / `tests/test_no_import_time_env_mutation.py`（见报告 §7.7）。**CI 已全绿**：run `38870946347`（`a434d68`）`test`（全 8 步，含此前被 skip 的 `Test with pytest`）+ `coverage` + `pip-audit` 三条 check-run 全 success —— 自 `7509c2a` 以来首次。**第六轮**（2026-10-16）逐条处置了报告 §7.4 登记的 **10 项生产代码疑似缺陷**（**8 修 / 2 书面不修**，含 4 个"把 bug 钉住"的用例反转 + 1 个同类兄弟缺陷），纪律为"每项 = 定向测试 + 理由 + 裁决"（见报告 §7.8）。**第七轮**（2026-10-17）**剪除 3 个生产孤岛**（`services/analysis/{macro,technical,signal}_service.py`，零调用方；整包语句 26,268 → 25,854）并**补测在线 `services/` 层 215 用例**（`services/` 65.57% → 79.69%，**不再是最弱层；现最弱层为 `hands/` 64.19%**）；同轮发现并修复一个**只在 CI 解释器暴露的真 bug**——`services/validation_service.py` 6 处把 `{}` 风格当 `%` 风格参数（stdlib `logging` 做 `msg % args` → `TypeError`；本机被捕获 handler 掩盖，CI 上使校验失败路径返回空 `results`），已改 `%s` 并加 AST 守卫 `tests/test_no_logging_format_mismatch.py`（见报告 §7.10）。The 2026-07-10 audit numbers (256 files / 62,549 LOC / 1,606 test functions) are retained in `docs/reanalysis/` as historical snapshots and no longer describe the tree. See `docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md` for the current architecture + trading-caliber evaluation. This page is a documentation state boundary. Prefer current source code and control documents over historical migration notes.

---

## Current Truth Sources

Read these first when starting analysis or implementation:

| Document | Status | Purpose |
|---|---|---|
| [Root CLAUDE.md](../CLAUDE.md) | Current | The 10 repository coding rules (source-cited consolidation; the originally-referenced file was never committed). |
| [Root AGENTS.md](../AGENTS.md) | Current | Canonical project control context for agents (wins on any conflict). |
| [Post-Simplification Evaluation](analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md) | Current (2026-10-16) | Architecture + trading-caliber evaluation of the current tree; §5 roadmap, §6 remediation log. |
| [Live System Map](reanalysis/I_live_system_map.md) | Historical (2026-07-09) | Verified architecture at that date: dead code inventory, active bugs ranked, data path heat map. Numbers superseded; methodology still useful. |
| [Analysis Prompt Playbook](ANALYSIS_PROMPT_PLAYBOOK.md) | Current | Direct-call staged prompts for system analysis, checkpoints, artifacts, and validation. |
| [Reshaping Logs Index](reshaping_logs/README.md) | Current | Controlled state-machine logs and audit sequence. |

> **Removed dangling links (2026-10-16):** `docs/STATUS.md`, `docs/EVALUATION_REPORT.md`,
> `docs/VERIFICATION_REPORT.md` and `docs/RESTRUCTURE_PLAN.md` are referenced by older docs
> but do **not** exist in this repository. They have been dropped from the indexes rather
> than left as false pointers.

Historical docs in this folder are still useful, but many describe target architecture or pre-remediation gaps. If a package page says `data`, `signal`, or `hands` are missing, that statement is stale.

---

## Runtime Modules

Current source layout under `src/uniquant/`:

| Module | Current state | Responsibility |
|---|---|---|
| `shared` | Present | Protocols/contracts, constants, config, exceptions, cache, A-share rules, costs, slippage, logging. |
| `data` | Present | Lake-first single-source ingestion (mootdx local/online), data lake, managers, parsers, cleaning, validation, single-track adjustment. |
| `brain` | Present | FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | Present | Adapters, normalization, aggregation, arbitration, quality, typed signal conversion. |
| `hands` | Present | Backtest engines, vectorized matching, strategy framework, reports, robustness tools. |
| `risk` | Present | Position sizing, drawdown, EVT, historical risk, structural risk, portfolio optimization. |
| `services` | Present | Service container, analysis service, data service, research pipeline, reports, scans, health. |
| `research` | Present | QTR-OS research control plane: degrees-of-freedom ledger (multiple-testing corrections), alpha four-tier gates, strategy sandboxes. Wired into the production factor chain (2026-10-16). |
| `ui` | Present | Streamlit dashboard, health checks, manager logic, LPPL visualization. |

Core flow:

`data -> brain/risk/signal -> hands -> services -> ui`

Primary runtime chain:

`DataService.fetch_for_brain()` -> `AnalysisService.run_ticker_analysis()` -> `TradingSignalCollector.collect()` -> `UnifiedBacktestEngine.run()` -> `PipelineResult`

---

## Evidence & Reproducibility (2026-10-16)

The data lake (`data/lake/`, multi-GB) and bulk research output are regenerable and therefore not tracked as blobs. That previously left every published conclusion with no auditable trail in the repository. Three mechanisms now close that gap:

| Mechanism | What it guarantees | Where / command |
|---|---|---|
| **Evidence allow-list** | The structured evidence behind published conclusions (P-series factor studies, H-A reconciliation, migration/QFQ verification, gate verdicts) **is** in the repository | `results/.gitignore` + root `.gitignore` (`results/*`) |
| **Content-hash ledger** | Every tracked evidence file has a recorded SHA-256 + size, so silent edits/drift are detectable | `results/EVIDENCE_MANIFEST.json`; `python scripts/maintenance/evidence_manifest.py build\|verify` |
| **Data-lake baseline** | Records lake counts, schema combinations, seed=42 dimension sampling and the git HEAD at capture time (the baseline file itself is inside the hash ledger) | `results/migration/lake_baseline.json`; `python scripts/maintenance/capture_lake_baseline.py` |

CI runs `evidence_manifest.py verify` on every push, so the evidence chain cannot drift silently. Regenerate the ledger only after an **intentional** evidence change:

```bash
python scripts/maintenance/evidence_manifest.py build   # update the ledger
python scripts/maintenance/evidence_manifest.py verify  # must print "Evidence manifest verified: no drift."
```

> Bulk artifacts (full-market Wyckoff scans, dated per-symbol dumps) stay out of the repository by design; rebuild them with the scripts under `scripts/wyckoff_experiments/` and `scripts/factor_mining/`.

---

## Direct-Call Analysis Workflow

Use [Analysis Prompt Playbook](ANALYSIS_PROMPT_PLAYBOOK.md) to run staged analysis:

| Stage | Topic | Artifact |
|---|---|---|
| 0 | Global architecture | `docs/analysis/00_architecture_map.md` |
| 1 | Services orchestration | `docs/analysis/01_services_orchestration.md` |
| 2 | Data system | `docs/analysis/02_data_system.md` |
| 3 | Brain engines | `docs/analysis/03_brain_engines.md` |
| 4 | Factor system | `docs/analysis/04_factor_system.md` |
| 5 | Signal system | `docs/analysis/05_signal_system.md` |
| 6 | Backtest and matching | `docs/analysis/06_backtest_matching.md` |
| 7 | Risk and live-readiness | `docs/analysis/07_risk_live_readiness.md` |

### v2.0 Deep Audit (2026-07-06)

| Phase | Topic | Artifact |
|---|---|---|
| A | Code quality audit | `docs/reanalysis/A_code_quality.md` |
| B | Test quality audit | `docs/reanalysis/B_test_quality.md` |
| C | Data reliability audit | `docs/reanalysis/C_data_quality.md` |
| D | Engine runtime behavior | `docs/reanalysis/D_engine_behavior.md` |
| E | Backtest trust audit | `docs/reanalysis/E_backtest_trust.md` |
| F | Signal audit | `docs/reanalysis/F_signal_audit.md` |
| G | Performance audit | `docs/reanalysis/G_performance.md` |
| H | Security audit | `docs/reanalysis/H_security.md` |
| I | Observability audit | `docs/reanalysis/I_observability.md` |
| J | Scorecard | `docs/reanalysis/J_scorecard.md` |
| K | Roadmap v2 | `docs/reanalysis/09_final_roadmap.md` |

Each stage includes:

- plan before execution
- concrete reading list
- required artifact
- checkpoint context for resuming after interruption
- validation checklist

---

## Key Source Files

| Concern | File |
|---|---|
| Package metadata | `../pyproject.toml` |
| Main config | `../config/config.yaml` |
| Cross-layer contracts | `../src/uniquant/shared/interfaces.py` |
| Service DAG | `../src/uniquant/services/service_container.py` |
| Analysis orchestrator | `../src/uniquant/services/analysis_service_v2.py` |
| Research pipeline | `../src/uniquant/services/research_pipeline.py` |
| Engine factory | `../src/uniquant/services/analysis/engine_factory.py` |
| Data fetcher | `../src/uniquant/data/data_fetcher.py` |
| Signal adapters | `../src/uniquant/signal/adapters.py` |
| Signal arbitrator | `../src/uniquant/signal/arbitrator.py` |
| Factor governance | `../src/uniquant/brain/factors/registry.py` |
| Feature flags | `../src/uniquant/shared/config_models.py` |
| Time provider | `../src/uniquant/shared/time_provider.py` |
| Typed backtest engine | `../src/uniquant/hands/backtest/unified_engine.py` |
| Vectorized matching engine | `../src/uniquant/hands/backtest/unified_matching_engine.py` |
| Position sizing | `../src/uniquant/risk/sizer.py` |
| Dashboard | `../src/uniquant/ui/dashboard.py` |

---

## Documentation Navigation

### Architecture And State

| Document | Status | Notes |
|---|---|---|
| [Architecture](architecture.md) | Historical/current mixed | Validate against source before citing. |
| [Architecture Topology](ARCHITECTURE_TOPOLOGY.md) | Historical/current mixed | Useful for dependency discussions. |
| [Project Status](archive/STATUS.md) | ⚠️ Archived 2026-05-26 | Historical snapshot, does NOT reflect current codebase. |
| [Closure Review Report (2026-06-12)](analysis/institutional/17_institutional_closure_review_report.md) | Current | Institutional audit closure review — P0/P1/P6 status matrix, verification log. |
> **Note**: Historical audit docs (Phase migration reports, EVALUATION_REPORT.md, VERIFICATION_REPORT.md, old REVIEW/OPTIMIZATION/FIX_PLAN files) have been moved to [archive/](archive/). See [archive/INDEX.md](archive/INDEX.md) for categorized browsing. These remain available for reference via Git history.

### Package Pages

Headers corrected (2026-06-17) to reflect actual file counts. Body content may still reference Phase 0-1 migration state:

| Document | Notes |
|---|---|
| [brain](packages/brain.md) | Validate engine list against `src/uniquant/brain/`. |
| [data](packages/data.md) | Stale if it says data layer is missing. |
| [hands](packages/hands.md) | Stale if it says hands layer is empty. |
| [services](packages/services.md) | Validate against current service files. |
| [shared](packages/shared.md) | Mostly useful, still validate constants layout. |
| [signal](packages/signal.md) | Stale if it says signal layer is missing. |
| [risk](packages/risk.md) | Validate against current risk files. |
| [ui](packages/ui.md) | Validate against current dashboard files. |

### Guides

| Guide | Notes |
|---|---|
| [Quickstart](guides/quickstart.md) | Validate commands against `pyproject.toml`. |
| [Backtest](guides/backtest.md) | Validate against unified engines. |
| [Factors](guides/factors.md) | Validate against current factors package and experiments. |
| [Strategies](guides/strategies.md) | Validate against `hands/strategies`. |
| [Data Sources](guides/data_sources.md) | Fixed stale "merged source" claim (2026-06-17). Runtime: hard-coded `DataFetcher`. |
| [Configuration](guides/configuration.md) | Validate against current config loader and YAML files. |
| [Migration Guide](guides/migration_guide.md) | ✅ Current | API 弃用对照表 + 迁移示例 |

### Development & Whitepaper

| Document | Status | Notes |
|---|---|---|
| [Project Structure](development/project_structure.md) | ⚠️ Partial | Header corrected; body paths may be flat→subpackage era |
| [Testing Guide](development/testing.md) | ✅ Current | 1034 tests methodology matches current state |
| [Performance Benchmarks](development/performance_benchmarks.md) | ✅ Current | Import times, test suite timing, repo metrics |
| [Architecture Whitepaper](whitepaper/ARCHITECTURE_WHITEPAPER.md) | ⚠️ Partial | Header corrected (28%→100%); core content still valid |
| [Deployment Guide](whitepaper/DEPLOYMENT_GUIDE.md) | ⚠️ Partial | Steps valid; module table updated (was 28%→100%) |
| [End-to-End Pipeline Example](examples/end_to_end_pipeline.py) | ✅ Current | Runnable full-chain demo |
| [API Reference](whitepaper/API_REFERENCE.md) | ⚠️ Partial | June 1 snapshot; API surface may have expanded |

### References

| Reference | Notes |
|---|---|
| [A-share Constraints](reference/a_share_constraints.md) | Cross-check with `shared/market_rules.py`, `limit_checker.py`, matching engines. |
| [Live vs Backtest Differences](reference/live_vs_backtest_differences.md) | ✅ Current | 15 quantified gaps between simulation and real trading |
| [Strategy Perf Benchmarks](research/strategy_performance_benchmarks.md) | ✅ Current | 7 engine + full pipeline benchmark with real data |
| [Deployment Architecture](whitepaper/DEPLOYMENT_ARCHITECTURE.md) | ✅ Current | Mermaid topology + startup seq + 40+ component tables |
| [Signal Types](reference/signal_types.md) | Cross-check with `shared/interfaces.py` and `signal/adapters.py`. |
| [Exceptions](reference/exceptions.md) | Cross-check with `shared/exceptions.py`. |
| [Constants](reference/constants.md) | Cross-check with `shared/constants/`. |

---

## Freshness Matrix (2026-06-17)

路径验证 = `python3 scripts/verify_doc_paths.py --json` 自动检查。每次代码重构后运行 `verify_doc_paths.py` 确认结果。

| Document | Last Verified | 路径验证 | Status | Notes |
|---|---|---|---|---|
| `AGENTS.md` | 2026-06-12 | ✅ | ✅ Current | Control context |
| `docs/index.md` | 2026-06-17 | — | ✅ Current | This file |
| `reference/a_share_constraints.md` | 2026-06-17 | ✅ | ✅ Current | Matches `constants/market.py` |
| `reference/exceptions.md` | 2026-06-17 | ✅ | ✅ Current | Matches `shared/exceptions.py` |
| `reference/constants.md` | 2026-06-17 | ✅ | ✅ Current | Matches `shared/constants/` |
| `reference/signal_types.md` | 2026-06-17 | ✅ | ✅ Current | Matches `shared/interfaces.py` |
| `reshaping_logs/` | 2026-06-09 | ✅ | ✅ Current | State machine log |
| `analysis/institutional/` | 2026-06-14 | ✅ | ✅ Current | Institutional audit artifacts |
| `packages/brain.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected (5/30+→74 files/10 subpkgs) |
| `packages/signal.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected |
| `packages/data.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected |
| `packages/hands.md` | 2026-06-17 | ✅ | ⚠️ Partial | BacktestEngine deprecated note added |
| `packages/risk.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected (1/7→7/7) |
| `packages/services.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected (10/24→31/31) |
| `packages/shared.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected (23/29→44/44) |
| `packages/ui.md` | 2026-06-17 | ✅ | ✅ Current | Header corrected (2/8→8/8) |
| `guides/backtest.md` | 2026-06-17 | ✅ | ⚠️ Partial | UnifiedBacktestEngine note added |
| `guides/quickstart.md` | 2026-06-17 | ✅ | ⚠️ Partial | UnifiedBacktestEngine note added |
| `guides/data_sources.md` | 2026-06-17 | ✅ | ⚠️ Partial | Fixed stale "merged source" claim |
| `guides/factors.md` | 2026-06-17 | ✅ | ⚠️ Partial | Validate against current factors package |
| `guides/strategies.md` | 2026-06-17 | ✅ | ⚠️ Partial | Validate against `hands/strategies` |
| `guides/configuration.md` | 2026-06-17 | ✅ | ⚠️ Partial | Validate against current config loader |
| `guides/migration_guide.md` | 2026-06-17 | ✅ | ✅ Current | 8 类弃用 API 对照表 + 迁移示例 |
| `reference/live_vs_backtest_differences.md` | 2026-06-17 | ✅ | ✅ Current | 15 quantified gaps between sim and real trading |
| `research/strategy_performance_benchmarks.md` | 2026-06-17 | — | ✅ Current | 7 engine + 1 pipeline benchmark (real parquet data) |
| `whitepaper/DEPLOYMENT_ARCHITECTURE.md` | 2026-06-17 | — | ✅ Current | Mermaid depl拓扑 + 启动时序 + 组件表 |
| `REMAINING_FIX_PLAN_20260608.md` | 2026-06-17 | — | ⚠️ Archived | Superseded by Phase 0-6 completion |
| `CONSOLIDATED_FINDINGS_20260608.md` | 2026-06-17 | — | ⚠️ Archived | Superseded by Phase 0-6 completion |
| `RESHAPING_REMEDIATION_REPORT_20260609.md` | 2026-06-17 | — | ⚠️ Archived | Superseded by institutional closure |
| `PHASE_COMPLETION_REPORT.md` | 2026-06-17 | — | ⚠️ Archived | Superseded — Phase 0-6 closed |
| `STATUS.md` | 2026-05-26 | — | ⚠️ Archived | Historical snapshot → `archive/STATUS.md` |
| `fix_plan.md` | 2026-05-24 | — | ⚠️ Archived | Old fix plan, all fixes complete → `archive/` |
| `REPAIR_CAMPAIGN_ROADMAP_V3.md` | 2026-05-31 | — | ⚠️ Archived | Phase 0-3 plan, all done → `archive/` |
| `PROJECT_ANALYSIS_REPORT.md` | 2026-05-23 | — | ⚠️ Archived | Early analysis, superseded → `archive/` |
| `ANALYSIS_PROMPT_PLAYBOOK.md` | 2026-06-17 | — | ✅ Current | Direct-call analysis workflow |
| `architecture.md` | 2026-06-17 | — | ⚠️ Mixed | Banner added; file tree has pre-refactor paths |
| `ARCHITECTURE_TOPOLOGY.md` | 2026-06-17 | — | ⚠️ Mixed | Mermaid has pre-refactor file names; note added |
| `DATA_FLOW_WHITEPAPER.md` | 2026-06-17 | — | ⚠️ Partial | Header note + type defs updated; flow paths valid |
| `GAP_REMEDIATION_PLAN.md` | 2026-06-12 | — | ⚠️ Historical | G-1~G-4 all closed (2026-06-12) |
| `MATCHING_ENGINE_AUDIT.md` | 2026-06-07 | — | ⚠️ Historical | Phase 4 audit, findings resolved |
| `REFACTORING_PLAN_COMPLETE.md` | 2026-06-12 | — | ⚠️ Historical | Phase 0-5 completion documented |
| `REMEDIATION_PLAN.md` | 2026-06-10 | — | ⚠️ Historical | Phase 1-4 plan, all work done |
| `analysis/08_research_platform_gap_plan.md` | 2026-06-17 | — | ⚠️ Partial | Valid gap analysis; some planned docs don't exist yet |
| `analysis/09_institutional_research_audit_workbreakdown.md` | 2026-06-17 | — | ⚠️ Partial | Work breakdown for completed audit |
| `development/project_structure.md` | 2026-06-17 | — | ⚠️ Partial | Header corrected; body has stale pre-subpackage paths |
| `development/testing.md` | 2026-06-17 | — | ✅ Current | Testing methodology, 1034 tests accurate |
| `development/performance_benchmarks.md` | 2026-06-17 | — | ✅ Current | Import times, test suite, repo metrics |
| `examples/end_to_end_pipeline.py` | 2026-06-17 | — | ✅ Current | Runnable full-chain pipeline demo |
| `whitepaper/ARCHITECTURE_WHITEPAPER.md` | 2026-06-17 | — | ⚠️ Partial | Header corrected (was 28%→100%); core content still valid |
| `whitepaper/DEPLOYMENT_GUIDE.md` | 2026-06-17 | — | ⚠️ Partial | Fixed pyproject.toml ref; module table updated (was "signal 不存在") |
| `whitepaper/API_REFERENCE.md` | 2026-06-17 | — | ⚠️ Partial | June 1 snapshot; API surface may have expanded |
| `archive/INDEX.md` | 2026-06-17 | — | ✅ Current | Categorized index of 69 archived root docs + 27 audit logs (96 total) |
| `archive/audit_logs/` | 2026-06-07 | — | ⚠️ Archived | 27 Phase 3 audit files, all closed |
| `archive/` (其他) | 2026-05~06 | — | ⚠️ Archived | Superseded historical docs |

## Install And Verification

```bash
pip install -e ".[all]"
pytest tests/ -q
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"
ruff check src/uniquant/
python3 scripts/verify_doc_paths.py
streamlit run src/uniquant/ui/dashboard.py
```

Do not report these as passing unless they were run in the current working tree. 路径验证命令 (`verify_doc_paths.py`) 可在重构后随时运行，确保文档引用的代码路径不失效。

## Pre-commit Hook

```bash
git config core.hooksPath .githooks
```

启用后，每次 `git commit` 自动运行 `verify_doc_paths.py`，阻止包含失效路径的提交。
