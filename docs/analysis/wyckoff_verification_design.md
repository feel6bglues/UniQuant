# Wyckoff Method in A-Shares: Verification Framework Design

## 1. Problem Diagnosis

Previous backtest (`wyckoff_correction_roi.py`) had five fatal flaws:

| Flaw | Impact |
|---|---|
| **Preselected universe** — golden_100 was 100 large-cap liquid stocks with +32% BH return | Results don't generalize; BH was 1.2% on 500 random stocks |
| **Methodology mismatch** — Wyckoff tape-reading forced into monthly-rebalance multi-strategy backtest | Lost Wyckoff's core edge (context-dependent entries, not periodic signals) |
| **No statistical inference** — only point estimates (mean, sharpe), no confidence intervals | Cannot distinguish signal from noise |
| **No factor decomposition** — attribution unknown | Captured momentum/size premium, not Wyckoff alpha |
| **Regime-agnostic** — tested over one 4.5-year period only | Cannot determine regime dependency |

## 2. Core Insight: What Wyckoff Actually Claims

Wyckoff is **not** a periodic signal generator. It is a **market context framework** with three layers:

```
Layer 1: Phase Identification (宏观)
  Accumulation → Markup → Distribution → Markdown
  ← — — 可验证 with daily OHLC — — →

Layer 2: Price-Volume Relationship (中观)
  Springs / Upthrusts / LPS / LPO
  ← 可近似验证 with daily OHLC — →

Layer 3: Tape Reading (微观)
  Bid-ask imbalance, speed of execution, absorption
  ← 需要 tick/level2 数据才能充分验证 →
```

**This framework design tests Layers 1 and 2. Layer 3 requires Level-2 data.**

## 3. Verification Strategy: Five Modules

### Module A: Universe Construction (无偏)
- All A-shares with ≥750 trading days (≈3yr) + ≥200 trading days of continuous data
- **Delisted stocks included** to avoid survivorship bias
- Stratified by market cap quintile
- Train period: 2015-01 — 2021-12 (≈7yr, multiple regimes)
- Test period: 2022-01 — 2026-06 (≈4.5yr)

### Module B: Individual Pattern Tests (统计检验)
Test each Wyckoff concept independently with bootstrap CIs:

| Hypothesis | Test | Expected |
|---|---|---|
| H1: Daily Springs predict positive alpha | Event study: t+5/20/60 return | Mean > 0 |
| H2: Upthrusts predict negative alpha | Event study: t+5/20/60 return | Mean < 0 |
| H3: Volume climax predicts reversal | Logit: climax → next 20d sign | AUC > 0.55 |
| H4: Accumulation → long, Distribution → short | Conditional forward returns | Monotonic |
| H5: Volume-lead relationship predicts phase change | Cross-correlation at lag -5 to +5 | Lead > lag |
| H6: Phase 2/4 (trend) vs 1/3 (range) volatility regime | Variance ratio test | Phase 2/4 > Phase 1/3 |

**Multiple hypothesis correction**: Benjamini-Hochberg FDR < 0.05  
**Sample splitting**: 1,000 bootstrap iterations for each estimate

### Module C: Factor Model (归因)
For each stock-event, decompose into factor contributions:

```
r_i = α + β_mkt·MKT + β_size·SMB + β_value·HML + β_mom·MOM + β_illiq·ILLIQ + ε
```

- **Test**: Is the Wyckoff-event intercept α significantly different from 0?
- **H0**: α = 0 (Wyckoff is fully explained by known factors)
- **H1**: α ≠ 0 (Wyckoff contains independent information)

Factor construction from A-share universe (long-short portfolios).

### Module D: Context-Dependent Strategy (贴近实战)
Instead of periodic rebalancing, implement a **threshold-based strategy**:

```
Entry Rules (Wyckoff-aligned):
  - Accumulation phase + Spring + volume contraction → Buy
  - Markup phase + normal pullback → Hold/Add
  - Distribution phase + Upthrust + volume expansion → Sell/Short
  - Markdown phase → Cash

Exit Rules:
  - Phase change detected → reassess all positions
  - Stop loss: ATR-based (2× ATR)
  - Take profit: RR ratio > 3:1 partial, > 5:1 full
```

This is closer to how Wyckoff traders actually operate.

### Module E: Regime Decomposition
Split test period into regimes using a 2-state HMM on SH-Index returns:

| Regime | A-share periods | Expected Wyckoff efficacy |
|---|---|---|
| Bull (trending up) | 2019Q1-2021Q1 | Phase trends work, Springs work |
| Bear (trending down) | 2015Q3, 2018, 2022Q1-Q4 | Distribution/Markdown best |
| Sideways (range) | 2016-2017, 2023-2024 | Phase boundaries most valuable |

Report strategy performance conditioned on regime.

## 4. Data Selection Rationale

### Inclusion Criteria
| Criterion | Rationale |
|---|---|
| ≥750 trading days listed | Minimum for multi-year phase analysis |
| ≥1 trading day per 20-day average liquidity | Prevent stale/micro-cap noise |
| Include delisted stocks | Anti-survivorship-bias |
| IPO + 250-day seasoning | Price discovery period |

### Exclusion Applied After Universe Construction
None — let the data speak.

### Sample Sizes (Estimated)
| Step | Stocks | Events |
|---|---|---|
| Full universe | ~4,500-5,000 | — |
| After liquidity filter | ~3,500-4,000 | — |
| Springs (daily detection) | — | ~80,000-150,000 |
| Upthrusts (daily detection) | — | ~60,000-120,000 |
| Phase changes | — | ~30,000-50,000 |

Large N → statistical tests have adequate power.

## 5. Output Metrics

| Metric | Purpose | Standard |
|---|---|---|
| Mean excess return (event) | Does pattern have predictive value? | +bootstrap 95% CI |
| Hit rate | Directional accuracy | > 55% |
| Information Coefficient (IC) | Rank correlation | Spearman ρ > 0.03 |
| Factor alpha | Independent from known factors | t-stat > 2.0 |
| Sharpe ratio (strategy) | Risk-adjusted return | > 0.5 |
| Max drawdown | Risk | < 30% |
| Regime P&L split | Where does it work? | > 50% of P&L from 1 regime → caution |

## 6. Code Structure

```
scripts/wyckoff_verification/
  __init__.py
  a_universe.py          — Universe construction
  b_pattern_tests.py     — Individual hypothesis tests
  c_factor_model.py      — Factor decomposition
  d_strategy.py          — Context-dependent strategy
  e_regime.py            — Regime decomposition
  runner.py              — Orchestrates all modules
  config.py              — Parameters
  output/                — Results directory
```

## 7. Rigor Checklist

- [ ] Survivorship bias eliminated (delisted stocks included)
- [ ] Look-ahead bias eliminated (only lagged signals)
- [ ] Transaction costs swept (0/0.1/0.3/0.5% one-way)
- [ ] Multiple hypothesis correction (BH FDR < 0.05)
- [ ] Bootstrap confidence intervals (1,000 iterations)
- [ ] Train/test temporal split (no random shuffle)
- [ ] Factor model decomposition
- [ ] Regime-conditioned reporting
- [ ] Sensitivity analysis for all parameters
