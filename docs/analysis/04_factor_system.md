# Stage 4 - Factor System

Generated: 2026-06-09

Scope: `brain/factors` factor registration, calculation, IC/IR evaluation, composition, neutralization, walk-forward validation, and look-ahead controls. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0-3 artifacts and the Stage 4 playbook requirements.
2. Inspect `FactorRegistry`, `custom_factors`, `FactorAnalyzer`, `FactorComposer`, `FactorNeutralizer`, and `WalkForwardFactorPipeline`.
3. Inspect `config/factors.yaml`, experiment scripts, and factor tests.
4. Separate offline research behavior from live-safe behavior.
5. Identify current factor admission gaps and propose executable production criteria.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` | Architecture baseline. |
| `docs/analysis/01_services_orchestration.md` | Service orchestration baseline. |
| `docs/analysis/02_data_system.md` | Data-system baseline. |
| `docs/analysis/03_brain_engines.md` | Brain-engine baseline and Stage 5 handoff. |
| `src/uniquant/brain/factors/registry.py` | Factor metadata, singleton registry, config overrides. |
| `src/uniquant/brain/factors/custom_factors.py` | Current manually registered technical and logic factors. |
| `src/uniquant/brain/factors/analyzer.py` | Rank IC, ICIR, forward return, live/backtest mode, look-ahead checker. |
| `src/uniquant/brain/factors/composer.py` | Factor computation, normalization, orthogonalization, weighting, diagnostics. |
| `src/uniquant/brain/factors/neutralizer.py` | MAD winsorization and size/industry residualization. |
| `src/uniquant/brain/factors/walk_forward_pipeline.py` | Temporal train/test split and out-of-sample factor validation. |
| `src/uniquant/brain/factors/__init__.py` | Package import contract and custom factor side-effect registration. |
| `src/uniquant/brain/factors/auto_mined/__init__.py` | New controlled auto-mining package boundary. |
| `src/uniquant/brain/factors/auto_mined/generator.py` | Genetic factor mining framework entry. |
| `config/factors.yaml` | Enabled/weight/category overrides for selected factors. |
| `experiments/run_factor_ic_evaluation.py` | Mock-universe factor IC and collinearity pruning workflow. |
| `experiments/run_walk_forward_pipeline.py` | Mock walk-forward OOS and PBO report workflow. |
| `experiments/run_real_data_ic.py` | TDX real-data IC/ICIR workflow for four logic factors. |
| `tests/test_factor_analyzer.py` | Analyzer Rank IC, ICIR, reports, best-period tests. |
| `tests/test_factor_registry.py` | Registration, enable/disable, listing tests. |
| `tests/test_custom_factors.py` | Turnover momentum behavior and registration test. |
| `tests/test_factor_div_zero_defense.py` | NaN/Inf and division-by-zero defense tests. |
| `tests/test_walk_forward_pipeline.py` | Temporal split, weight, OOS metric, and no-lookahead boundary tests. |

## 3. 因子注册机制

Current registration path:

```text
import uniquant.brain.factors
  -> factors/__init__.py imports custom_factors
  -> custom_factors.register_all()
  -> FactorRegistry.register(...)
  -> config/factors.yaml overrides enabled/weight/category
  -> FactorComposer.registry.get_enabled()
```

Concrete facts:

| Concern | Current behavior | Evidence |
|---|---|---|
| Registry object | `FactorRegistry` is a singleton with a class-level `_factors` dict and lock. | `src/uniquant/brain/factors/registry.py:28-45` |
| Metadata | Each factor has `name`, `category`, `compute_func`, `default_weight`, `enabled`, `description`, optional IC history. | `src/uniquant/brain/factors/registry.py:13-23` |
| Config overrides | `register()` reads `factors.<name>` from config and can skip disabled factors or override weight/category. | `src/uniquant/brain/factors/registry.py:48-83`, `config/factors.yaml` |
| Enabled set | `get_enabled()` returns registered factors whose `enabled` flag is true. | `src/uniquant/brain/factors/registry.py:96-101` |
| Runtime toggles | `enable()` / `disable()` mutate registry state in memory. | `src/uniquant/brain/factors/registry.py:108-119` |
| Auto registration | `custom_factors.py` calls `register_all()` at import time. | `src/uniquant/brain/factors/custom_factors.py:198-311` |

Current registered manual pool:

| Group | Factors |
|---|---|
| Baseline technical | `momentum_20d`, `momentum_60d`, `volatility_20d`, `volatility_60d`, `ma_ratio_5_20`, `ma_ratio_10_60`, `volume_ratio_5_20`, `rsi_14`, `price_position_20d`, `turnover_momentum_20d` |
| Logic factors | `illiq_20d`, `pv_divergence_20d`, `cs_momentum_20d`, `idiosyncratic_vol_20d` |

The config file currently overrides only `momentum_20d`, `turnover_momentum_20d`, and `pe_ttm` (`config/factors.yaml`). `pe_ttm` is configured but not registered in `custom_factors.py`; unless another module registers it, this config entry is inert.

Auto-mined factor state is transitional. `src/uniquant/brain/factors/__init__.py:5` says old `auto_mined/` output was removed after PBO failure, while `src/uniquant/brain/factors/auto_mined/__init__.py:1-10` exposes a new `GeneticFactorMiner` framework. Therefore the correct current status is: old generated factor library has been purged, but a new controlled mining framework exists and still needs production admission evidence.

## 4. 因子计算流程

`FactorComposer.compute_all_factors()` is the current common computation path:

```text
input df
  -> get enabled factors from FactorRegistry
  -> group by code when code exists
  -> sort each code group by date
  -> call factor.compute_func(group_df, mode=mode) or fallback to factor.compute_func(group_df)
  -> enforce same output length as input group
  -> assemble factor value DataFrame on original index
  -> record diagnostics for requested/computed/failed factors
```

Evidence: `src/uniquant/brain/factors/composer.py:82-136`.

Key properties:

| Property | Status |
|---|---|
| Per-symbol rolling safety | Good: groups by `code` and sorts by `date` before rolling computations. |
| Output shape guard | Good: length mismatch is detected and marked as failed when no valid values remain. |
| Factor failure behavior | Degraded rather than fatal: failed factors are logged and recorded in diagnostics. |
| Mode propagation | Partial: composer passes `mode` to factor functions that accept it, otherwise falls back silently. |
| Field requirements | Mostly implicit: each factor checks required columns locally and returns all-NaN if fields are missing. |

Composition path:

```text
compute_all_factors()
  -> optional factor_cols filtering
  -> resolve weights from IC results or registry defaults
  -> per-date cross-sectional z-score normalization
  -> optional symmetric orthogonalization
  -> weighted sum into composite_score
  -> optional neutralization by industry dummies and log market cap
```

Evidence:

- Weight resolution: `src/uniquant/brain/factors/composer.py:151-174`.
- Per-date normalization: `src/uniquant/brain/factors/composer.py:185-204`.
- Composite score construction: `src/uniquant/brain/factors/composer.py:206-232`.
- Symmetric orthogonalization: `src/uniquant/brain/factors/composer.py:234-282`.
- `compose_scores()` neutralization hook: `src/uniquant/brain/factors/composer.py:284-350`.
- Compatibility `process()` entry: `src/uniquant/brain/factors/composer.py:352-401`.

The current A-share factor calculations are all historical rolling transforms and do not require future prices at calculation time. Examples:

- `momentum_20d` uses `close.pct_change(20)` (`custom_factors.py:7-12`).
- `illiq_20d` uses past absolute return divided by amount with a 20-day rolling mean (`custom_factors.py:88-104`).
- `cs_momentum_20d` uses past 20-day and past 5-day returns (`custom_factors.py:131-151`).
- `idiosyncratic_vol_20d` uses recent return residual volatility and returns negative IVOL (`custom_factors.py:154-175`).

## 5. IC/IR 分析流程

`FactorAnalyzer.compute_ic_ir()` is explicitly an offline evaluation method, not a live-trading signal method.

Current flow:

```text
input df with date/code/close/factor columns
  -> mode normalization: "backtest" or "live"
  -> LIVE mode raises ValueError immediately
  -> sort by code/date
  -> for each holding period:
       future_return = close.shift(-period) / close - 1, grouped by code
  -> for each date:
       Rank IC = Spearman(factor cross-section, forward return cross-section)
  -> aggregate IC mean, IC std, ICIR, IC positive ratio, t-stat, n_periods
  -> store each factor's best absolute-ICIR period in self.results
```

Evidence:

- Mode enum: `src/uniquant/brain/factors/analyzer.py:87-97`.
- LIVE guard: `src/uniquant/brain/factors/analyzer.py:283-288`.
- Negative shift forward return: `src/uniquant/brain/factors/analyzer.py:297-302`.
- Daily cross-sectional Rank IC: `src/uniquant/brain/factors/analyzer.py:316-329`.
- ICIR/t-stat aggregation: `src/uniquant/brain/factors/analyzer.py:334-359`.
- Best-period selection: `src/uniquant/brain/factors/analyzer.py:225-241`, `370-373`.

Backtest mode vs live mode:

| Mode | Allowed behavior | Current guardrail |
|---|---|---|
| `AnalysisMode.BACKTEST` / `"backtest"` | Allows negative shift because it is measuring future realized returns for research. | Default mode in `compute_ic_ir()`. |
| `AnalysisMode.LIVE` / `"live"` | Must not compute future returns. | Raises `ValueError` before any forward-return calculation. |

Negative shift risk:

The expression `df.groupby(code_col)[price_col].shift(-period)` is necessary for IC labeling but is a future-data operation. It is safe only when all outputs are research metrics. It must not be used to generate live signals, online factor values, dashboard "current score" rankings, or order decisions.

Current experiments use this correctly as research:

- `experiments/run_factor_ic_evaluation.py` computes IC@5d/20d on a mock universe, prunes collinearity, and writes a research report.
- `experiments/run_walk_forward_pipeline.py` manually rolls train/test windows, evaluates OOS IC, and estimates PBO against random combinations.
- `experiments/run_real_data_ic.py` uses TDX data and `AnalysisMode.BACKTEST` to evaluate four logic factors across 1/5/20-day horizons.

## 6. 未来函数防护机制

Current protection has three layers:

| Layer | Mechanism | Evidence | Status |
|---|---|---|---|
| Live IC guard | `compute_ic_ir(..., mode=LIVE)` raises because IC requires future returns. | `analyzer.py:283-288` | Strong for analyzer entry. |
| Future timestamp guard | `_compute_forward_returns()` checks `date > now`, but this helper is not the main path used by `compute_ic_ir()`. | `analyzer.py:170-179` | Partial; duplicated logic should be consolidated. |
| Perturbation test | `check_lookahead_leakage()` changes future close prices and checks whether earlier factor values change. | `analyzer.py:25-84` | Useful but only run when caller passes `factor_func` to walk-forward pipeline. |

Walk-forward validation also reduces leakage by separating train and test windows:

- `_temporal_split()` creates windows where train end precedes test start (`walk_forward_pipeline.py:62-78`).
- `run()` computes IC weights only on `train_df` (`walk_forward_pipeline.py:153-172`).
- It applies trained weights to `test_df` and evaluates `composite_score` OOS (`walk_forward_pipeline.py:178-194`).
- Tests assert no overlap and `max(train_dates) < min(test_dates)` (`tests/test_walk_forward_pipeline.py`).

Important issue to fix before relying on `factor_func` mode: `WalkForwardFactorPipeline.run()` calls `self.analyzer.compute_ic_ir(..., factor_func=factor_func)` when `factor_func` is provided (`walk_forward_pipeline.py:134-143`), but `FactorAnalyzer.compute_ic_ir()` has no `factor_func` parameter (`analyzer.py:243-253`). Tests currently mock `compute_ic_ir` in the end-to-end path, so this real integration path can fail with `TypeError`.

## 7. 样本内、样本外、滚动验证

Current validation levels:

| Level | Current implementation | Assessment |
|---|---|---|
| In-sample IC/IR | `FactorAnalyzer.compute_ic_ir()` on the full DataFrame. | Useful first filter only; not sufficient for production. |
| Cross-sectional correlation | `compute_factor_correlation()` and experiment-level pruning. | Useful collinearity check, but production threshold should be configured and logged. |
| Out-of-sample holdout | `WalkForwardFactorPipeline` computes train weights and evaluates test composite IC. | Good direction; needs real integration coverage without mocks. |
| Walk-forward | Rolling train/test windows with final weights, OOS IC mean/std/ICIR, weight stability. | Present. |
| PBO | Experiment script estimates random-combo PBO. | Present in experiment, not formalized into pipeline result or admission gate. |
| Real-data check | `experiments/run_real_data_ic.py` pulls TDX data for 50 named A-share stocks. | Useful smoke, but universe is small and hand-selected. |

## 8. 因子上线标准

The project needs an executable factor admission checklist. Recommended minimum criteria:

| Gate | Required criterion | Implementation target |
|---|---|---|
| Schema | Factor declares required columns, lookback, direction, category, and live-safe status. | Extend `FactorInfo` or add a factor manifest. |
| Calculation safety | Output length equals input length, no `Inf`, acceptable NaN warmup only, no cross-symbol contamination. | Existing composer and div-zero tests cover part of this. |
| Look-ahead safety | Perturbation invariance passes for each candidate factor. | Run `check_lookahead_leakage()` in a test/CI workflow. |
| In-sample efficacy | Abs mean Rank IC above threshold for at least one configured horizon, with minimum `n_periods`. | Use `FactorAnalyzer` report. |
| Stability | IC positive ratio, t-stat, and rolling IC stability meet thresholds across subperiods. | Add explicit thresholds to config. |
| OOS efficacy | Walk-forward OOS IC mean and OOS ICIR pass thresholds. | Use `WalkForwardFactorPipeline`. |
| Overfit control | PBO below threshold; current auto-mining package doc names `PBO < 0.2` and `OOS IC > 0.03`. | Formalize in pipeline result and CI/report gate. |
| Redundancy | Average cross-sectional correlation below threshold or factor survives pruning. | Productionize experiment pruning. |
| A-share tradability | Exclude or penalize ST, suspended, limit-up/down locked, tiny liquidity, and untradeable names at evaluation and backtest time. | Coordinate with data quality, signal, and backtest stages. |
| Cost-aware backtest | Factor portfolio improves after A-share commissions, stamp duty, slippage, lot size, and T+1. | Stage 6 backtest integration. |

Admission should write a versioned report containing data source, universe, date range, factor code hash or version, thresholds, all metrics, and pass/fail decision. A factor should not be enabled in `config/factors.yaml` for production solely because it has a positive in-sample IC.

## 9. 当前因子体系风险

1. `pe_ttm` appears in `config/factors.yaml` but is not registered by current custom factors. This creates configuration drift and false confidence that a fundamental factor is active.
2. `FactorRegistry._ensure_loaded()` only marks `_loaded=True`; actual custom-factor loading depends on package import side effects. Direct imports of `registry.py` alone can leave the registry empty unless `custom_factors` has been imported.
3. `compute_ic_ir()` contains the correct LIVE guard, but the negative-shift implementation is still easy to misuse if caller uses default backtest mode in an online path.
4. `WalkForwardFactorPipeline.run(factor_func=...)` has a signature mismatch against `FactorAnalyzer.compute_ic_ir()`, making the real factor-function leakage-check path suspect.
5. OOS/PBO thresholds exist in comments and experiments, not as a single enforced admission gate.
6. `FactorComposer._resolve_weights()` can use signed ICIR weights, while `WalkForwardFactorPipeline._compute_weights()` uses absolute ICIR. These are different portfolio assumptions and need an explicit policy.
7. Factor metadata does not encode whether higher values mean better expected return. For negative-premium concepts, the sign is embedded in function output, which is harder to audit.
8. Neutralization is available but optional and caller-supplied; industry and size data availability is not guaranteed in the main pipeline.
9. Current real-data IC experiment uses 50 named stocks, not a complete A-share survivorship-bias-controlled universe.
10. Many auto-mined files are deleted in the current worktree while a new generator exists. This is a transition state; production status should remain "not admitted" until reports prove OOS/PBO gates.

## 10. 从研究到实盘的改进路线

1. Define a factor manifest: required fields, lookback, direction, category, live-safe flag, neutralization requirement, and minimum history.
2. Make registration deterministic: `FactorRegistry._ensure_loaded()` should import known factor modules or the application should own one explicit bootstrap path.
3. Convert experiment thresholds into config-backed admission gates and produce machine-readable reports.
4. Fix `WalkForwardFactorPipeline.run(factor_func=...)` integration so look-ahead checking and IC computation work on the same candidate function.
5. Standardize weight semantics: choose signed ICIR, absolute ICIR with separate direction, or constrained long-only weights, then enforce consistently in composer and walk-forward.
6. Expand real-data validation to a broad, point-in-time A-share universe with delisting/suspension/ST/limit filters.
7. Add cost-aware factor portfolio backtests before enabling production weights.
8. Feed admitted `composite_score` into signal generation only after Stage 5 defines conflict handling with DecisionBrain risk vetoes.

## 11. 阶段结论

The factor subsystem is research-capable and has several strong building blocks: thread-safe registry metadata, per-symbol rolling computation, cross-sectional normalization, optional orthogonalization, IC/IR analytics, explicit LIVE blocking for forward-return IC, walk-forward OOS structure, and NaN/Inf defense tests.

It is not yet a complete production factor-admission system. The main gaps are deterministic registration, formal admission gates, real integration coverage for candidate `factor_func`, complete A-share universe validation, explicit weight-direction policy, and cost-aware backtest linkage.

## 12. 校验清单

| Check | Status |
|---|---|
| 区分 backtest mode 和 live mode | Done: `compute_ic_ir()` allows only backtest and raises in live mode. |
| 说明 negative shift 风险 | Done: forward return labeling uses grouped `shift(-period)` and must stay offline. |
| 说明样本内、样本外、滚动验证 | Done: IC/IR, correlation, walk-forward OOS, PBO experiment, real-data check covered. |
| 提出可执行的因子准入标准 | Done: schema, safety, look-ahead, IC, OOS, PBO, redundancy, tradability, cost-aware gates listed. |
| 结论绑定到具体文件/函数 | Done throughout with file and line references. |

## 13. 下一阶段输入

Stage 5 should inspect how factor outputs and other engine outputs become executable signals:

- `src/uniquant/signal/adapters.py`
- `src/uniquant/signal/models.py`
- `src/uniquant/signal/collector.py`
- `src/uniquant/signal/aggregator.py`
- `src/uniquant/signal/quality.py`
- `src/uniquant/shared/interfaces.py`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- Tests covering signal adapters, signal collection, and pipeline-to-backtest behavior.

Key Stage 5 questions:

1. Should `DecisionBrain` risk vetoes suppress all lower-level BUY/SELL adapter signals?
2. Should failed/missing factor or alpha data produce HOLD/no-signal instead of SELL?
3. How should future `composite_score` be converted into `TradingSignal` without bypassing A-share risk filters?
4. Are signal confidence, priority, and timestamp semantics consistent enough for backtest execution?
