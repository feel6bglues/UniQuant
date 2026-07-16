# Wyckoff Sub-package Architecture

> Generated 2026-07-14. 18 source files, 7,133 LOC, 44% of `brain/` layer.

## Overview

The Wyckoff sub-package implements Wyckoff method analysis for A-share stocks: phase detection (accumulation/markup/distribution/markdown), event detection (PS/SC/AR/ST/Spring/SOS/LPS/JAC), multi-timeframe fusion, P&F charting, and report generation. The single entry point is `WyckoffEngine` in `engine.py`.

---

## 18-File Summary

| # | File | LOC | Purpose | Key Class(es) | Depends On (wyckoff) | Depends On (external) |
|---|------|----:|---------|---------------|----------------------|-----------------------|
| 1 | `engine.py` | 1,616 | Main analysis engine — single entry point; orchestrates phase detection, event detection, rule validation, multi-timeframe analysis | `WyckoffEngine`, `create_a_share_monthly_engine` | `constants`, `analysis`, `classifiers`, `models`, `rules`, `pnf`, `phase_analysis` | `brain.indicators.indicators`, `shared.constants`, `shared.logger_factory`, `numpy`, `pandas` |
| 2 | `models.py` | 820 | Data models — 30+ dataclasses/enums for phases, signals, reports, analysis results, trading plans | `WyckoffPhase`, `ConfidenceLevel`, `VolumeLevel`, `WyckoffSignal`, `WyckoffStructure`, `WyckoffReport`, `AnalysisResult`, `AnalysisState`, `TradingPlan`, `ImageEvidenceBundle`, `BCPoint`, `SCPoint`, `ChipAnalysis`, `RiskRewardProjection`, `V3TradingPlan`, `LimitMove`, `Rule0Result`, `Step1Result`, `Step2Result`, `Step3Result`, `MultiTimeframeContext`, `TimeframeSnapshot`, `StressTest`, `V3CounterfactualResult`, `ConfidenceResult`, `StopLossResult`, `ChartManifest`, `ChartManifestItem`, `RiskRewardResult`, `FVGResult`, `RegimeAwarePhaseResult` | — | — |
| 3 | `events.py` | 517 | Wyckoff event chain detection — 8 event detectors (PS/SC/AR/ST/Spring/SOS/LPS/JAC) with sigmoid-normalized confidence scores | `WyckoffEvent` (dataclass); `detect_all_events()`, `detect_ps()`, `detect_sc()`, `detect_ar()`, `detect_st()`, `detect_spring()`, `detect_sos()`, `detect_lps()` | — | `numpy`, `pandas`, `numba` |
| 4 | `phase_analysis.py` | 506 | Multi-timeframe phase analysis — weekly/daily/monthly classifiers + resonance detection | `WeeklyPhaseClassifier`, `DailyPhaseClassifier`, `MultiTimeframeResonance`, `RegimeAwarePhaseClassifier` | — | `numpy`, `pandas`, `math` |
| 5 | `fusion_engine.py` | 469 | Fusion engine — merges data analysis and image evidence results, resolves conflicts | `FusionEngine` | `models` | `json`, `pathlib`, `shared.logger_factory` |
| 6 | `image_engine.py` | 428 | Image engine — scans chart image folders, extracts visual evidence, identifies timeframe/symbol | `ImageEngine` | `models` | `os`, `re`, `pathlib`, `shared.logger_factory` |
| 7 | `reporting.py` | 397 | Report generator — Markdown/HTML/CSV/JSON output following SPEC_WYCKOFF_OUTPUT_SCHEMA | `WyckoffReportGenerator` | `models` | `json`, `os`, `pandas`, `shared.time_provider`, `shared.logger_factory` |
| 8 | `rules.py` | 378 | Rule executor — 10 independent Wyckoff trading rules (volume, spread, stop-loss, risk-reward, etc.) | `V3Rules` | `models` | `pandas` |
| 9 | `analysis.py` | 322 | Analysis functions — extracted from engine.py; chips analysis, multi-timeframe, velocity, money flow, divergence | `analyze_chips()`, `analyze_multiframe()`, `build_timeframe_snapshot()`, `compute_avg_price_deviation()`, `compute_money_flow_trend()`, `merge_multitimeframe_reports()`, `compute_velocity()`, `detect_divergence()` | `models`, `rules`, `constants` | `numpy`, `pandas`, `copy` |
| 10 | `classifiers.py` | 301 | Classification functions — extracted from engine.py; sub-phase classification, volume classification, limit move detection | `classify_accumulation_sub_phase()`, `classify_distribution_sub_phase()`, `classify_unknown_candidate()`, `classify_volume()`, `classify_wyckoff_markup_event()`, `detect_limit_moves()` | `models`, `rules` | `pandas`, `shared.constants`, `shared.limits` |
| 11 | `state.py` | 296 | State manager — persistence, continuity tracking, Spring freeze period management | `StateManager` | `models`, `constants` | `json`, `datetime`, `pathlib`, `shared.time_provider`, `shared.logger_factory` |
| 12 | `bayesian_events.py` | 231 | Bayesian probability cloud — Beta posterior updates over detected events for probability collapse scoring | `BayesianEventDetector`, `BayesianEventState` | `events` (docstring ref) | `numpy`, `scipy.stats` |
| 13 | `pnf.py` | 213 | Point & Figure chart engine — 3-box reversal method, column statistics, trendlines | `PointAndFigure`, `PnFBox` | — | `numpy`, `pandas` |
| 14 | `sequence.py` | 202 | Event sequence scoring — WSO (rule-based) + WSS (statistical) blended scorer | `WyckoffScorer`, `WSOScorer`, `WSSScorer` | `bayesian_events` | `json` |
| 15 | `config.py` | 181 | Configuration management — rule engine, image engine, fusion engine configs with YAML loading | `WyckoffConfig`, `RuleEngineConfig`, `ImageEngineConfig`, `FusionConfig`, `load_config()` | — | `os`, `yaml`, `shared.constants`, `shared.logger_factory` |
| 16 | `trading.py` | 125 | Trading simulation helpers — Wyckoff-specific return calculation with entry/stop/target logic | `calculate_wyckoff_return()` | — | `pandas` |
| 17 | `monthly_classifier.py` | 89 | Monthly phase classifier — A-share adapted thresholds from 76K monthly snapshots | `MonthlyPhaseClassifier` | `phase_analysis` (`_obv_trend`) | `numpy`, `pandas` |
| 18 | `constants.py` | 19 | Centralized constants — magic numbers for analysis windows, engine thresholds, freeze days | (module-level constants) | — | — |

---

## Dependency Graph

```
Legend:
  ──>  imports from
  ┌─┐  module
  [E]  external dependency

                    ┌──────────────────────────────────────────────────┐
                    │                 external                          │
                    │  numpy  pandas  numba  scipy  yaml  pathlib       │
                    │  shared.constants  shared.logger_factory          │
                    │  shared.time_provider  shared.limits              │
                    │  brain.indicators.indicators                      │
                    └──────────┬───────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────────────────────┐
          │                    │                                    │
          ▼                    ▼                                    ▼
   ┌──────────┐        ┌────────────┐                       ┌──────────┐
   │ config   │        │ constants  │                       │ models   │
   │ (181)    │        │ (19)       │◄──────┐               │ (820)    │
   └──────────┘        └────────────┘       │               └────┬─────┘
                                              │                    │
                                              │                    │
          ┌───────────────────────────────────┼──── 12 files ─────┤
          │                                   │                    │
          ▼                                   ▼                    ▼
   ┌──────────┐                        ┌──────────┐        ┌──────────┐
   │ pnf      │                        │ events   │        │ rules    │
   │ (213)    │                        │ (517)    │        │ (378)    │
   └──────────┘                        └────┬─────┘        └────┬─────┘
                                             │                    │
                                             │                    │
                                             ▼                    ▼
                                      ┌────────────┐       ┌──────────┐
                                      │ bayesian   │       │ clas-    │
                                      │ _events    │       │ sifiers  │
                                      │ (231)      │       │ (301)    │
                                      └─────┬──────┘       └────┬─────┘
                                             │                    │
                                             ▼                    ▼
                                      ┌────────────┐       ┌──────────┐
                                      │ sequence   │       │ analysis │
                                      │ (202)      │       │ (322)    │
                                      └────────────┘       └────┬─────┘
                                                                 │
                                                                 │
          ┌──────────────────────────────────────────────────────┤
          │                        │                              │
          ▼                        ▼                              ▼
   ┌──────────┐            ┌──────────────┐             ┌──────────────┐
   │ trading  │            │ phase_       │             │   engine     │
   │ (125)    │            │ analysis     │             │  (1,616)     │
   └──────────┘            │ (506)        │             └──────┬───────┘
                           └──────┬───────┘                    │
                                  │                            │
                                  ▼                            ▼
                           ┌──────────────┐            ┌──────────────┐
                           │ monthly_     │            │   image_     │
                           │ classifier   │            │   engine     │
                           │ (89)         │            │  (428)       │
                           └──────────────┘            └──────┬───────┘
                                                               │
                                                               ▼
                                                        ┌──────────────┐
                                                        │   fusion_    │
                                                        │   engine     │
                                                        │  (469)       │
                                                        └──────┬───────┘
                                                               │
                                                               ▼
                                                        ┌──────────────┐
                                                        │   state      │
                                                        │  (296)       │
                                                        └──────────────┘
                                                               │
                                                               ▼
                                                        ┌──────────────┐
                                                        │   reporting  │
                                                        │  (397)       │
                                                        └──────────────┘
```

---

## Layer Architecture

### Layer 0: Foundation (3 files, 1,020 LOC)

| File | LOC | Role |
|------|----:|------|
| `models.py` | 820 | All data types — 30+ dataclasses and enums. Referenced by every other file. Zero internal dependencies. |
| `constants.py` | 19 | Centralized magic numbers. Referenced by `engine`, `analysis`, `state`. Zero internal dependencies. |
| `config.py` | 181 | Configuration dataclasses + YAML loading. Zero internal dependencies. |

### Layer 1: Independent Analysis Modules (6 files, 1,976 LOC)

| File | LOC | Dependencies | Role |
|------|----:|:-------------|------|
| `events.py` | 517 | none | 8 Wyckoff event detectors with Numba-accelerated confidence scoring |
| `pnf.py` | 213 | none | Point & Figure 3-box reversal chart engine |
| `rules.py` | 378 | `models` | 10-rule trading rule validator |
| `phase_analysis.py` | 506 | none | Weekly/daily/monthly phase classifiers + resonance |
| `trading.py` | 125 | none | Trading simulation return calculation |
| `bayesian_events.py` | 231 | (doc-refs `events`) | Bayesian Beta posterior event probability |

### Layer 2: Analysis Composition (3 files, 824 LOC)

| File | LOC | Dependencies | Role |
|------|----:|:-------------|------|
| `analysis.py` | 322 | `models`, `rules`, `constants` | Chips analysis, multi-timeframe snapshots, money flow, divergence detection |
| `classifiers.py` | 301 | `models`, `rules` | Sub-phase classification, volume classification, limit move detection |
| `sequence.py` | 202 | `bayesian_events` | WSO/WSS event sequence scoring blended into unified scores |

### Layer 3: Orchestration (3 files, 2,609 LOC)

| File | LOC | Dependencies | Role |
|------|----:|:-------------|------|
| `engine.py` | 1,616 | `constants`, `analysis`, `classifiers`, `models`, `rules`, `pnf`, `phase_analysis`, `brain.indicators` | **Single entry point.** Orchestrates all analysis phases, signal generation, and report building. |
| `fusion_engine.py` | 469 | `models` | Merges data analysis results with image evidence, resolves conflicts |
| `image_engine.py` | 428 | `models` | Scans chart image files, extracts visual evidence |

### Layer 4: Output (2 files, 693 LOC)

| File | LOC | Dependencies | Role |
|------|----:|:-------------|------|
| `state.py` | 296 | `models`, `constants` | State persistence, continuity tracking, Spring freeze management |
| `reporting.py` | 397 | `models` | Multi-format report generation (Markdown/HTML/CSV/JSON) |

### Standalone (1 file, 89 LOC)

| File | LOC | Dependencies | Role |
|------|----:|:-------------|------|
| `monthly_classifier.py` | 89 | `phase_analysis` (internal fn) | Monthly phase classifier with A-share adapted thresholds |

---

## Public API (`__init__.py` exports)

```
WyckoffEngine          —  engine.py       Main analysis engine
create_a_share_monthly_engine  — engine.py Factory for monthly engine
FusionEngine           —  fusion_engine.py Fusion engine
ImageEngine            —  image_engine.py  Image analysis engine
WyckoffStateManager    —  state.py         State manager (aliased)
WyckoffPhase           —  models.py        Phase enum
ConfidenceLevel        —  models.py        Confidence enum
VolumeLevel            —  models.py        Volume enum
WyckoffSignal          —  models.py        Signal dataclass
WyckoffStructure       —  models.py        Structure dataclass
WyckoffReport          —  models.py        Report dataclass
TradingPlan            —  models.py        Trading plan dataclass
WyckoffConfig          —  config.py        Configuration
load_config            —  config.py        Config loader
V3Rules                —  rules.py         Rule executor
WyckoffReportGenerator —  reporting.py     Report generator
PointAndFigure         —  pnf.py           P&F chart engine
PnFBox                 —  pnf.py           P&F box dataclass
BayesianEventDetector  —  bayesian_events.py Bayesian detector
BayesianEventState     —  bayesian_events.py Bayesian state
```

---

## Key Design Properties

1. **`models.py` is the hub** — 13 of 18 files depend on it. It has zero internal dependencies, making it the natural type contract.
2. **`engine.py` is the single entry point** — No other file bypasses it to reach the brain layer. All public consumers go through `WyckoffEngine.run()`.
3. **No circular dependencies** — The dependency graph is a strict DAG flowing foundation → analysis → orchestration → output.
4. **`events.py` and `pnf.py` are fully independent** — They depend only on external libraries (numpy, pandas, numba), making them testable in isolation.
5. **`constants.py` is minimal** (19 LOC) — Most configuration lives in `config.py` (181 LOC) with YAML loading support.