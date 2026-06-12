# UniQuant Documentation Index

> Unified Quantitative Trading Platform for China A-share research, backtesting, and trading workflows.
>
> Updated: 2026-06-12. Phases 0-5 completion, Phase 6 gaps closed, institutional closure review completed. See [Closure Review Report](analysis/institutional/17_institutional_closure_review_report.md) for P0/P1 status matrix. This page is a documentation state boundary. Prefer current source code and control documents over historical migration notes.

---

## Current Truth Sources

Read these first when starting analysis or implementation:

| Document | Status | Purpose |
|---|---|---|
| [Root AGENTS.md](../AGENTS.md) | Current | First project control context for agents. |
| [Analysis Prompt Playbook](ANALYSIS_PROMPT_PLAYBOOK.md) | Current | Direct-call staged prompts for system analysis, checkpoints, artifacts, and validation. |
| [Reshaping Remediation Report 2026-06-09](RESHAPING_REMEDIATION_REPORT_20260609.md) | Current | Recent remediation, verification, and remaining risks. |
| [Reshaping Logs Index](reshaping_logs/README.md) | Current | Controlled state-machine logs and audit sequence. |
| [Status](STATUS.md) | Check before relying | Project status page; may trail source changes. |

Historical docs in this folder are still useful, but many describe target architecture or pre-remediation gaps. If a package page says `data`, `signal`, or `hands` are missing, that statement is stale.

---

## Runtime Modules

Current source layout under `src/uniquant/`:

| Module | Current state | Responsibility |
|---|---|---|
| `shared` | Present | Protocols, constants, config, exceptions, cache, A-share rules, costs, slippage, logging. |
| `data` | Present | Multi-source data ingestion, data lake, managers, parsers, cleaning, validation, adjustment. |
| `brain` | Present | FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | Present | Adapters, normalization, aggregation, quality, typed signal conversion. |
| `hands` | Present | Backtest engines, vectorized matching, portfolio engine, strategy framework, reports. |
| `risk` | Present | Position sizing, drawdown, EVT, historical risk, structural risk, portfolio optimization. |
| `services` | Present | Service container, analysis service, data service, research pipeline, reports, scans, health. |
| `ui` | Present | Streamlit dashboard, health checks, manager logic, LPPL visualization. |

Core flow:

`data -> brain/risk/signal -> hands -> services -> ui`

Primary runtime chain:

`DataService.fetch_for_brain()` -> `AnalysisService.run_ticker_analysis()` -> `TradingSignalCollector.collect()` -> `UnifiedBacktestEngine.run()` -> `PipelineResult`

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
| Factor governance | `../src/uniquant/shared/factor_governance.py` |
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
| [Project Status](STATUS.md) | Check before relying | May lag current working tree. |
| [Evaluation Report](EVALUATION_REPORT.md) | Historical audit | Useful for doc/code drift background. |
| [Verification Report](VERIFICATION_REPORT.md) | Historical audit | Independent verification notes. |
| [Closure Review Report (2026-06-12)](analysis/institutional/17_institutional_closure_review_report.md) | Current | Institutional audit closure review — P0/P1/P6 status matrix, verification log. |
| [Reshaping Remediation Report 2026-06-09](RESHAPING_REMEDIATION_REPORT_20260609.md) | Current recent audit | Latest remediation context. |

### Package Pages

These pages may contain stale migration-phase statements. Use as background only:

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
| [Data Sources](guides/data_sources.md) | Validate against current sources and managers. |
| [Configuration](guides/configuration.md) | Validate against current config loader and YAML files. |

### References

| Reference | Notes |
|---|---|
| [A-share Constraints](reference/a_share_constraints.md) | Cross-check with `shared/market_rules.py`, `limit_checker.py`, matching engines. |
| [Signal Types](reference/signal_types.md) | Cross-check with `shared/interfaces.py` and `signal/adapters.py`. |
| [Exceptions](reference/exceptions.md) | Cross-check with `shared/exceptions.py`. |
| [Constants](reference/constants.md) | Cross-check with `shared/constants/`. |

---

## Install And Verification

```bash
pip install -e ".[all]"
pytest tests/ -q
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"
ruff check src/uniquant/
streamlit run src/uniquant/ui/dashboard.py
```

Do not report these as passing unless they were run in the current working tree.
