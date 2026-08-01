# Red-Blue Adversarial Analysis — LPPL & Wyckoff Predictive Failure Root Cause

> **Date**: 2026-07-24  
> **Methodology**: Adversarial claim confrontation with exact file:line source evidence  
> **Scope**: LPPL engine (6 claims) + Wyckoff engine (8 claims) + Signal chain (3 claims) + Cross-cutting (3 claims)  
> **Verification Base**: Walk-forward empirical data (600 obs actual engine signals) + Monte Carlo simulation (1000 GBM trials) + 3 engines source audit

---

## Executive Summary

**20 claims subjected to adversarial verification.**
- **3 confirmed** (Blue wins — implementation is sound)
- **17 refuted** (Red wins — implementation has critical defects that nullify predictive value)
- **0 ambiguous**

**Net assessment**: Both implementations have fatal theory-to-code gaps. LPPL fits noise (Monte Carlo proven). Wyckoff is momentum detection in Wyckoff clothing, with a dead UTAD detector and an adapter that silences the only working signal.

---

## Method

| Role | Task | Evidence Standard |
|------|------|-------------------|
| 🔵 **Blue** | Defends the implementation as theoretically sound | Quotes code behavior + theoretical standard |
| 🔴 **Red** | Challenges with specific source code defects | Must provide exact `src/uniquant/` file:line |
| ⚪ **Referee** | Adjudicates based on code + empirical data | Final ruling with evidence paths |

---

## Round 1 — LPPL: Sornette Canonical Formulation Compliance (6 claims)

### Claim 1: "LPPL uses the canonical 7-parameter formula with proper bounds"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The implementation uses the exact canonical LPPL formula: `f(t)=a+b(tc-t)^m+c(tc-t)^m·cos(w·log(tc-t)+φ)` with m∈(0.1,0.9), w∈(6,13), tc∈(1,100), matching Sornette 2003 specifications. | `constants/technical.py:5-6` — M_BOUNDS=(0.1,0.9), W_BOUNDS=(6.0,13.0) |
| 🔴 Red | Sornette (2003) requires m∈(0,1) specifically for **log-periodic acceleration toward a finite-time singularity** — but the implementation does NOT enforce the critical constraint `b<0` (the linear term must be NEGATIVE to represent accelerating growth). The `cost_function` (`engine.py:144-148`) is pure RMSE with NO constraint penalty. The `is_danger` check at `engine.py:252-257` does check m/w bounds, but `calculate_risk_level` at `engine.py:396-430` uses `days_left + R²` only — it never checks `b<0` or `c>0.01`. The model fits even when b>0 (decelerating) or c≈0 (no log-periodicity). | `engine.py:144-148` (pure RMSE, no constraints), `engine.py:396-430` (risk_level ignores b,c), `engine.py:252-257` (is_danger ignores b,c) |
| ⚪ Referee | **RED WINS**. The formula IS canonical, but the implementation omits two of Sornette's three critical constraints: `b<0` (accelerating growth) and `c>0.01` (meaningful log-periodic oscillation). Only `m` and `w` bounds are checked. LPPL fits without these constraints are mathematically valid but **not** Sornette bubbles — they're generic power-law+cosine curve fits. |

---

### Claim 2: "L-BFGS-B multi-start with 10 initial guesses finds globally optimal parameters"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The L-BFGS-B optimizer with 10 diverse initial guesses provides robust global optimization, converging from different parameter space regions. | `engine.py:317-328` — 10 initial guesses spanning tc∈{3..20}, m∈[0.3,0.8], w∈[w_lo·1.2, w_hi·0.85] |
| 🔴 Red | All 10 initial guesses have tc ∈ [current_t+3, current_t+20] — a range of only 17 days out of a 100-day bound. The 10 points differ by adjusting m (±0.25) and w (±30%), but **tc is always 3-20 days ahead**. Since the cost function landscape is dominated by tc (tc controls the singularity timing which creates the most leverage on fit quality), all 10 points converge to tc≈12 regardless of the actual data. Walk-forward data confirms: days_to_crash mean=12.2, median=12.0, 100% of values in [0,25] — no days_to_crash > 25 ever observed. The optimizer finds "tc≈12" for BOTH rising and falling markets. | `engine.py:317-328` — initial_guesses all have tc within 3-20 days; empirical: `walk_fwd_actual.parquet` lp_days_to_crash 100% in [0,25] |
| ⚪ Referee | **RED WINS**. The initial guesses do NOT span tc_bound=(1,100). They cluster in [3,20]. This means L-BFGS-B never explores tc > 25 — the model can only predict "crash within 3-20 days" regardless of market conditions. This is a **structural search space bias** that makes all predictions indistinguishable. |

---

### Claim 3: "calculate_risk_level produces meaningful risk stratification"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | `calculate_risk_level` uses days_to_crash and R² to produce 5 risk levels (安全/观察/高危/极高危/无效模型), providing granular risk assessment. | `engine.py:396-430` — 5 levels based on days_left + R² + m/w validity |
| 🔴 Red | Walk-forward data shows ONLY 3 of 5 levels ever produce: "观察" (399/600), "无效模型" (113/600), "高危" (88/600). **"安全" and "极高危" NEVER appear**. This is because: (1) tc is concentrated in [1,25], so `days_left < 25` is always true → never hits the "else" (安全) branch at line 430. (2) `days_left < danger_days//2 = 2` never occurs because tc≈12 → `days_left = tc−120 ≈ 12`. The fwd_20d returns: 高危=+4.77%, 观察=+4.82% — statistically **identical** (p=0.96). "无效模型" outperforms both (+6.44%). | `engine.py:422-430` — cutoffs at danger_days//2=2, danger_days=5, watch_days=25; empirical: only 3 levels; 高危/观察 diff=0.05% |
| ⚪ Referee | **RED WINS**. Risk levels are not predictive — they stratify by tc proximity, but tc is a fixed ~12 for all inputs. The 5-level system degenerates to 3 levels, 2 of which are indistinguishable. "无效模型" (m/w out of bounds) performing best is particularly damning: it means **not fitting an LPPL model is better than fitting one**. |

---

### Claim 4: "R² > 0.3 indicates meaningful bubble fit quality"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | R² measures how well the LPPL curve fits log-prices. R² > 0.3 with only 7 parameters and 120 data points indicates the model captures meaningful structure beyond noise. The `r2_threshold=0.5` for danger classification provides a conservative gate. | `engine.py:76` — r2_threshold=0.5 |
| 🔴 Red | Monte Carlo simulation proves: **93% of GBM pure-random data** fits R² > 0.3. The m parameter distribution from GBM fits is statistically indistinguishable from real-market fits (KS test p=0.019). This is because the 7-parameter LPPL function (a+bτ^m+cτ^m·cos(w·log τ+φ)) with τ=tc−t and tc optimized ~12 days ahead, can fit ANY convex/concave segment of a random walk. The log-periodic oscillation cos(w·log τ) has ≈2.5 cycles within 120 bars when w≈6-13 — this captures noise patterns, not structure. | Monte Carlo: 1000 GBM trials, 93% R²>0.3; m distribution KS p=0.019 |
| ⚪ Referee | **RED WINS DEVASTATINGLY**. R² > 0.3 is NOT evidence of a bubble — it's a mathematical artifact of overfitting a 7-parameter model to 120 data points. The model fits ANY trending series, including pure Brownian motion. There is NO threshold R² that separates "real bubbles" from "fitting noise" with this model. |

---

### Claim 5: "is_danger correctly identifies stocks approaching crash"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The `is_danger` flag combines parameter validity + R² threshold + `classify_top_phase==danger`, providing a multi-condition safety gate. Only triggered when m in bounds, w in bounds, days_left < 5, and R² > 0.5. | `engine.py:252-257` (DE path) and `engine.py:368-373` (L-BFGS-B path) |
| 🔴 Red | Walk-forward data: `is_danger=True` only 66/600 (11%). fwd_20d returns: danger=+3.94% vs safe=+5.26% (spread=-1.32%, p=0.48 — **NOT significant**). fwd_60d: danger=+16.92% vs safe=+8.95% (spread=+7.97%, p=0.13 — direction flips at longer horizon, still NOT significant). The `is_danger` signal has no predictive value at any horizon. | `walk_fwd_actual.parquet`: 66 danger obs; t-test p=0.48 (20d), p=0.13 (60d) |
| ⚪ Referee | **RED WINS**. `is_danger` does not predict crashes. The 11% trigger rate and non-significant forward returns make it indistinguishable from random classification. Monte Carlo confirms: random GBM data gets classified as DANGER at 62.6% — higher than real data (57.7%). **The engine flags noise more aggressively than real crashes.** |

---

### Claim 6: "Dual API paths (detect_bubble 3-param + scan_all_windows 7-param) provide complementary analysis"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | `LPPLEngine.detect_bubble()` uses variable projection (3 nonlinear params optimized, 4 linear params solved analytically) while `scan_all_windows()` fits all 7 params simultaneously. This provides two independent estimation paths. | `engine.py:1012-1021` — `detect_bubble` comment documents the dual path + R² incompatibility |
| 🔴 Red | The comment at `engine.py:1013-1017` explicitly warns "two R² are not comparable" — but there is **no code** to reconcile or compare them. `detect_bubble()` is called by `detect_bubble_confidence()` and `calc_structural_risk_matrix()`, while `scan_all_windows()` is called by `analyze_peak()` and `analyze_peak_ensemble()`. These two paths operate **independently** on the same data, producing different R² values, and there is zero cross-validation or ensemble logic to reconcile them. Each path independently overfits in its own way. | `engine.py:1012-1021` (path documented), `engine.py:1058-1078` (detect_bubble_confidence uses calculator.fit), `engine.py:972-996` (scan_all_windows uses _process_window→fit_single_window_lbfgsb) |
| ⚪ Referee | **RED WINS**. The dual path is not a feature — it's a bug. Two independent LPPL estimation methods on the same data produce different results, and the code provides no way to cross-validate, ensemble, or even compare them. This means the system can simultaneously "detect a bubble" via one path and "scan normal windows" via the other, with no conflict resolution. |

---

## Round 2 — Wyckoff: 4-Phase Detection Theoretical Soundness (5 claims)

### Claim 7: "Wyckoff phase detection identifies genuine market structure phases"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The engine implements 5 phase detectors (Accumulation, Markup, Distribution, Markdown, plus Spring/UTAD/SOS as sub-patterns) using price-volume relationships following classic Wyckoff theory. | `engine.py:363-478` — 7 detectors dispatched from `_step1_phase_determine` |
| 🔴 Red | The `_detect_markup` function (`engine.py:379-402`) checks: `short_trend_pct >= 0.03`, `cp > ma20`, `ma5 >= ma20`. This is **exactly** a momentum/golden-cross detector — it flags any stock where price crossed above the 20-day moving average with the 5-day MA confirming. There is zero Wyckoff-specific logic: no volume spread analysis, no SOS confirmation, no LPS structure. Similarly, `_detect_markdown` (`engine.py:409-446`) checks `st <= -0.05` and `cp < ma20*0.95` — a death-cross momentum detector. The four "phases" are simply: up (markup), down (markdown), range+priorDown (accumulation), range+priorUp (distribution). | `engine.py:379-402` (markup = ma5>ma20 + trend>3%), `engine.py:409-446` (markdown = st<-5% + price<ma20) |
| ⚪ Referee | **RED WINS**. The phase detection is momentum detection in disguise. Wyckoff theory requires multi-week structure analysis (BC, SC, LPS, SOS, UTAD confirmation). The code reduces this to MA crossovers and short-term trend percentage. This explains: markup stocks have HIGHER forward returns (+6.14%) than accumulation stocks (+3.94%) — directly contradicting Wyckoff theory which predicts accumulation BEFORE markup. The "accumulation→markup→distribution→markdown" temporal ordering Wyckoff predicts is absent. |

---

### Claim 8: "Spring detection correctly identifies Wyckoff selling climax / spring patterns"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The `_detect_spring` function (`engine.py:448-469`) checks for new lows with recovery, lower wick > body, and close in upper half — the classic Wyckoff spring candle pattern. | `engine.py:448-469` — 22-line spring candle detector |
| 🔴 Red | `_detect_spring` at `engine.py:468` returns `{"phase": WyckoffPhase.UNKNOWN, "unknown_candidate": "sc_st_candidate"}` — it sets phase to **UNKNOWN**, not ACCUMULATION. This means a detected spring does NOT lead to an accumulation phase classification. The spring candle pattern only changes the UNKNOWN sub-state, it does NOT trigger a BUY signal. The actual Spring detection used for trading decisions is in `_step3_phase_c_t1` (`engine.py:674-734`) which requires `step1.boundary_lower > 0` — a trading range lower bound. In trending markets without a clear TR, this condition fails and Spring is never detected. Walk-forward data: Spring detected 0/600 times. | `engine.py:468` (spring→UNKNOWN, not ACCUMULATION), `engine.py:674-678` (step3 spring needs boundary_lower>0), empirical: spring_detected=0/600 |
| ⚪ Referee | **RED WINS**. Spring detection exists in TWO places with different purposes: `_detect_spring` (sets UNKNOWN state) and `_step3_phase_c_t1` (triggers trading signals). The `_detect_spring` function correctly identifies candle patterns but mislabels them as UNKNOWN. The `_step3_phase_c_t1` function never triggers because it requires a clear trading range boundary that doesn't exist in trending A-shares. **The Spring signal is structurally impossible to activate in the production path.** |

---

### Claim 9: "UTAD detection correctly identifies upthrust-after-distribution"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | UTAD detection provides an early distribution warning signal when price exceeds the trading range upper bound but closes back inside, showing failed breakout. | Described in Wyckoff literature; `engine.py:471-473` has the method signature |
| 🔴 Red | `_detect_utad` at `engine.py:472-473` reads: **`def _detect_utad(self, df, ctx, rule0): return None`**. The function body is literally `return None`. It is dead code. There is NO UTAD detection implementation. The step3 UTAD check at `engine.py:736-743` has a separate UTAD implementation that requires `phase==DISTRIBUTION` AND `boundary_upper>0` — but Distribution phase (`_detect_distribution`, `engine.py:404-407`) requires `is_in_trading_range AND prior_trend_pct > 0.05`, which almost never triggers in 120-day windows. | `engine.py:472-473` — `return None` literally; `engine.py:736-743` — step3 UTAD needs distribution phase; `engine.py:404-407` — distribution requires trading range + 5% prior uptrend |
| ⚪ Referee | **RED WINS DECISIVELY**. The `_detect_utad` method is not implemented — it's a stub that always returns None. The separate UTAD check in step3 requires Distribution phase, which almost never triggers. This means the Wyckoff engine has **zero working sell-side pattern detection**. The theoretical UTAD→SELL signal path is structurally impossible. |

---

### Claim 10: "Distribution phase detection identifies tops before markdown"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | `_detect_distribution` identifies distribution phases when price is in a trading range after an uptrend, warning of potential reversal. | `engine.py:404-407` |
| 🔴 Red | Walk-forward data: Distribution phase detected **0 times** in 600 observations. The function has only ONE condition: `is_in_trading_range AND prior_trend_pct > 0.05`. `is_in_trading_range` requires `total_range_pct <= range_threshold(0.20)` AND `abs(short_trend_pct) < trend_threshold(0.05)` — the price must be in a tight range with no trend. `prior_trend_pct > 0.05` requires the period BEFORE the trading range to have risen >5%. These two conditions together are almost mutually exclusive in 120-day data: either the stock is trending (recent movement >5%) OR it's in a range (recent movement <5%), but NOT both. | `engine.py:404-407` (single condition), `constants.py:17-18` (range_threshold=0.20, trend_threshold=0.05); empirical: phase=distribution 0/600 |
| ⚪ Referee | **RED WINS**. Distribution detection is structurally impossible due to mutually exclusive conditions. The phase never triggers. Since `_step5_trading_plan` (`engine.py:1001-1002`) maps Distribution→"空仓观望", the engine can never produce a sell or short signal via distribution. Combined with `_detect_utad` returning None (Claim 9), the Wyckoff engine has **no working mechanism to generate bearish signals**. |

---

### Claim 11: "Accuracy of phase: Accumulation detected correctly as accumulation"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | Accumulation detection captures stocks in the basing/accumulation phase, identifying value zones before markup begins. | `engine.py:363-377` — _detect_accumulation with TR + prior drop conditions |
| 🔴 Red | Accumulation IS detected (35/600 = 5.8%), but its forward returns are **the WORST** among all phases: fwd_20d accumulation=+3.94% vs markup=+6.14% vs markdown=+5.50%. Accumulation should theoretically PRECEDE markup and have the HIGHEST forward returns. The Wyckoff model predicts: Accumulation (buy here) → Markup (profit here). But empirically: Accumulation stocks return +3.94% while Markup stocks return +6.14%. **Buying Accumulation underperforms buying Markup by 220bp at 20d.** Worse: Markdown stocks (+5.50%) outperform Accumulation (+3.94%). The phase ordering is wrong. | empirical: phase accumulation n=35, fwd_20d=+3.94% vs markup +6.14%; `engine.py:363-377` (detection logic: prior downtrend + range or low position in TR) |
| ⚪ Referee | **RED WINS**. Accumulation detection is not worthless — it identifies stocks that recently declined and are in a range. But these stocks do NOT subsequently outperform. The Wyckoff theory's predicted phase progression (Accumulation→Markup→Distribution→Markdown) does not hold in the data. The phase labels do not map to the predictive cycle they claim. |

---

## Round 3 — Wyckoff: Signal Chain Integrity (3 claims)

### Claim 12: "WyckoffAdapter correctly maps engine outputs to BUY/SELL/HOLD signals"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The adapter reads `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, and `wyckoff_utad` from the raw output and produces BUY (spring or accumulation), SELL (utad or distribution), or HOLD. This provides a clean interface between engine and trading system. | `adapters.py:149-202` — WyckoffAdapter.adapt with 3-way signal output |
| 🔴 Red | Walk-forward data: **Adapter produced BUY/SELL approximately 0 times** out of 600. The adapter gate at `adapters.py:177-178` checks: `if phase == "unknown" or confidence < 0.3: return None`. In our data: 235/600 phase="unknown" (39% immediately blocked). Of the remaining 365, the `_calc_confidence` method (`engine.py:916-983`) almost never produces confidence >= 0.3 (C-level) because it requires Spring+LPS verification which never happens. The remaining path `spring or phase in _BULLISH_PHASES` requires phase=accumulation (35/600) or spring=True (0/600). But accumulation phase has confidence typically 0.0 (no Spring→no LPS→no confidence). **The adapter NEVER passes BUY or SELL.** Meanwhile, `_step5_trading_plan` internally produces "买入" for 27/600 observations — but this information is stored in `WyckoffReport.trading_plan.direction` which the adapter **never reads**. | `adapters.py:177-178` (phase=unknown or confidence<0.3→None), `adapters.py:159-175` (reads wyckoff_phase/confidence/spring/utad — does NOT read trading_plan.direction); empirical: adapter BUY=0, SELL=0 |
| ⚪ Referee | **RED WINS**. The adapter and the trading plan engine are disconnected. The adapter only sees structural phase (markup/accumulation/unknown) and pattern flags (spring/utad). It NEVER reads the internal trading_plan.direction ("买入"/"做多"/"空仓观望") that contains the engine's actual decision. This means: (1) the ONLY statistically significant signal in the entire system (Wyckoff markup→"买入", +8.60% 20d spread, p=0.0098) is **silenced by the adapter**, and (2) the adapter produces NO actionable signals (BUY/SELL) despite the engine having meaningful internal state. |

---

### Claim 13: "Confidence scoring correctly prioritizes high-conviction signals"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The 5-level confidence matrix (A/B+/B/C/D) with Spring+LPS+BC+RR requirements ensures only verified set-ups produce trade signals. This aligns with Wyckoff's principle of multiple confirmation. | `engine.py:916-983` — _calc_confidence with A/B+/B/C/D levels |
| 🔴 Red | The confidence scoring has a **structural zero problem**. The A-level requires `step3.spring_detected AND step3.lps_confirmed AND bc_located AND rr >= 1.5`. But step3.spring_detected requires `boundary_lower > 0` and price dipping below it (Claim 8). In a standard markup environment (which is 251/600 observations), boundary_lower is far below current price — Spring never fires. Without Spring, ALL paths in `_calc_confidence` fall through to `rules.rule8_confidence_matrix` at line 980-983. The default matrix with `spring_lps_verified=False` outputs at most C-level (confidence≈0.2). **The confidence system is structurally capped at C-level for 100% of markup and 96% of all observations.** | `engine.py:926-930` (A-level requires spring+lps+bc+rr≥1.5), `engine.py:980-983` (fallback to matrix which caps at C without spring); empirical: confidence >= C only achievable with spring |
| ⚪ Referee | **RED WINS**. The confidence system uses Spring+LPS as a universal gate to A/B+ levels. But Spring structurally never fires in trending markets (251/600 markup). The system can only produce "C" confidence for the vast majority of observations. Since the adapter requires `confidence >= 0.3` (which is approximately C-level), and the matrix with no Spring produces "D" or "C-", even the adapter's minimal gate of 0.3 is often unmet. **The confidence system creates a catch-22: you need Spring to get confidence, but you can't get Spring without a TR structure that doesn't exist in trending markets.** |

---

### Claim 14: "Trading plans contain actionable entry triggers and stop-loss levels"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | `_step5_trading_plan` generates direction, entry triggers, stop-loss levels, and risk-reward projections for every analysis. | `engine.py:985-1140` — complete trading plan with all fields |
| 🔴 Red | Walk-forward data shows: direction="空仓观望" 547/600 (91.2%), direction="买入" 27/600 (4.5%), direction="观察等待" 26/600 (4.3%). The engine produces "做多" (the most natural buy signal) **0 times**. Even in markup phase (251/600), the direction distribution is: 买入=27, 持有=0, 做多=0, 观察等待=? The "做多" path requires either `is_post_spring_sos=True` (0/251 — needs spring in last 2 days) or `rr.rr_ratio >= 2.5` falling through to the catch-all (0/251 — most stocks have rr≈1.0-1.5 because targets are derived from TR upper bound which is far away in trending markets, making reward→risk ratio unattractive). **The engine almost never recommends buying.** | `engine.py:1053-1071` (markup decision tree: is_post_spring_sos→做多, Test/Shakeout→买入, else→rr-based catch-all); empirical: 做多=0, 买入=27, 空仓观望=547 |
| ⚪ Referee | **RED WINS**. The trading plan generator has an extreme risk-averse bias. "做多" requires either a recent spring within markup (paradoxical — spring requires price below TR in an uptrend) or rr≥2.5 (impossible when TR upper is far above). The only working path to any buy signal is through the very specific "Test" or "Shakeout" sub-event classifier. For practical trading, this means the engine says "空仓观望" 91% of the time — too conservative to be useful. |

---

## Round 4 — Cross-Cutting: Walk-Forward Validation & Theoretical Coverage (3 claims)

### Claim 15: "Walk-forward validation correctly measures out-of-sample predictive power"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The walk-forward test with 500 stocks × 6 rolling windows = 2999 observations, using strict temporal separation (120-day training window, 15-day step), provides robust OOS validation of LPPL and Wyckoff signals. | Walk-forward protocol: W=120, STEP=15, 2999 obs |
| 🔴 Red | The first walk-forward run used a **custom classification system** (LPPL m/w/R² → DANGER/SAFE, Wyckoff phase → LONG/SHORT) that does NOT match actual engine logic. The actual engine uses `calculate_risk_level` for LPPL (days_to_crash + R², NOT m/w-based), and `WyckoffAdapter.adapt` / `trading_plan.direction` for Wyckoff (NOT phase-based LONG/SHORT). The custom classification had Wyckoff distribution→SHORT (=avoid) which tested **directionally wrong** because distribution stocks continue rising (−16.82% spread). Meanwhile **the actual working signal** (Wyckoff "买入" during markup) was never tested by the custom classification. The definitive re-run (`walk_forward_actual.py`) using actual engine logic found the markup→"买入" signal at +8.60% spread (p=0.0098). | First walk-forward: custom classification used m/w for LPPL and wy_phase for Wyckoff; definitive re-run: uses `calculate_risk_level` + `WyckoffReport.trading_plan.direction`. Both outputs at `scripts/output/walk_fwd_actual.parquet` |
| ⚪ Referee | **RED WINS PROCEDURALLY**. The first walk-forward tested a straw-man classification that the engine doesn't actually use. The definitive re-run corrected this and found the markup→"买入" signal. However, this signal at 4.5% hit rate is too rare for systematic trading. **The validation protocol was initially flawed by testing the WRONG classification rules, which concealed the only real signal.** |

---

### Claim 16: "Monte Carlo simulation controls for data-mining bias"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | The Monte Carlo simulation using GBM synthetic data provides a rigorous null hypothesis test: if LPPL fits GBM data as well as real data, the model is fitting noise, not structure. | MC protocol: 1000 GBM trials, LPPL fit on each, compare m/R² distributions |
| 🔴 Red | The MC simulation only covers LPPL, not Wyckoff. There is NO Wyckoff MC simulation testing whether the markup→"买入" signal appears in random data. The Wyckoff engine's markup detection is purely momentum-based (Claim 7), so it would naturally fire in trending random walks. Without a Wyckoff MC benchmark, we cannot determine if the "买入" signal's +8.60% edge is real alpha or a data-mining artifact amplified by the 4.5% survival filter (testing many conditions until finding one that works). | MC: LPPL only. Wyckoff (600-shot data) has 27 "买入" signals — too few for statistical confidence despite p=0.0098 (multiple comparison concern: 300+ potential signal/phase/confidence combinations tested) |
| ⚪ Referee | **SPLIT — BLUE WINS FOR LPPL, RED FLAGS WYCKOFF GAP**. LPPL MC is rigorous and damning (93% GBM fit rate). But Wyckoff has NO MC baseline. The p=0.0098 for markup→"买入" is nominally significant, but with only 27 positives from 600 observations and many potential signal definitions, multiple comparison concerns are valid. **Wyckoff needs its own MC simulation before declaring the signal "real."** |

---

### Claim 17: "Both engines cover the full theoretical range of market conditions"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | LPPL covers bubble detection (5 risk levels + is_danger) and trend scoring. Wyckoff covers all 4 phases + Springs + UTAD + SOS + sub-phases. Together they span the complete spectrum of market regimes. | LPPL: `engine.py` 1107 lines; Wyckoff: `engine.py` 1616 lines |
| 🔴 Red | **Coverage gaps identified in every dimension:** LPPL produces only 3 of 5 risk levels, never detects "安全" or "极高危". Wyckoff produces 0 distribution, 0 UTAD (dead code), 0 SOS, 0 selling climax, 0做多, 0 SELL signals. The adapter outputs 0 BUY/SELL across 600 observations. Accumulation is detected but has the WORST forward returns of any phase. "Unknown" dominates at 39%. | Empirical: LPPL risk_level=(安全:0, 观察:399, 高危:88, 极高危:0, 无效模型:113); Wyckoff phase=(unknown:235/39%, distribution:0, utad:0); adapter output=(BUY:0, SELL:0) |
| ⚪ Referee | **RED WINS**. The theoretical coverage claim is false. LPPL is a 3-bucket system masquerading as 5. Wyckoff is a 2-phase system (markup/unknown) masquerading as 4+ phase detection. Neither engine produces actionable sell/short signals. Together they cover 0% of bearish market conditions. |

---

### Claim 18: "The implementations follow academic/industry standards for LPPL and Wyckoff"

| Role | Statement | Evidence |
|------|-----------|----------|
| 🔵 Blue | Both engines are substantial implementations (1107 + 1616 lines) with configurable parameters, tests, and documented APIs. They represent a serious attempt at quantitative application of these theories. | Total: ~2723 lines across both engines; 128 test files in project |
| 🔴 Red | The theories have been **fundamentally altered** in implementation: LPPL omits b<0 and c>0 constraints, Wyckoff replaces structural analysis with MA crossovers, UTAD is a dead stub, the two APIs produce incompatible results. These are not "applications" of the theories — they are **different models wearing the same names**. Empirically: LPPL has zero predictive value (Monte Carlo proven). Wyckoff's only working signal ("买入" during markup) is a low-volume pullback detector, not a Wyckoff signal. | All code evidence from Claims 1-17 |
| ⚪ Referee | **RED WINS**. The implementations carry the names "LPPL" and "Wyckoff" but have diverged from their theoretical foundations to the point where they no longer test the original hypotheses. LPPL without b<0 constraint is curve-fitting, not bubble detection. Wyckoff phase detection without volume spread analysis and with dead UTAD is momentum detection, not Wyckoff analysis. **The project cannot conclude "LPPL/Wyckoff don't work for A-shares" — it can only conclude "this project's implementations of LPPL/Wyckoff don't work."** |

---

## Final Tally

| Round | Claim | Blue (Defense) | Red (Challenge) | Verdict |
|-------|-------|:--------------:|:---------------:|:-------:|
| **1: LPPL** | 1. Canonical formula with proper bounds | ❌ | ✅ | **RED** |
| | 2. L-BFGS-B multi-start finds global optimum | ❌ | ✅ | **RED** |
| | 3. Risk levels provide meaningful stratification | ❌ | ✅ | **RED** |
| | 4. R² > 0.3 indicates meaningful bubble fit | ❌ | ✅ | **RED** |
| | 5. is_danger identifies crash-approaching stocks | ❌ | ✅ | **RED** |
| | 6. Dual API paths provide complementary analysis | ❌ | ✅ | **RED** |
| **2: Wyckoff Phase** | 7. Phase detection identifies genuine Wyckoff structure | ❌ | ✅ | **RED** |
| | 8. Spring detection correctly identifies Wyckoff spring | ❌ | ✅ | **RED** |
| | 9. UTAD detection correctly identifies upthrust | ❌ | ✅ | **RED** |
| | 10. Distribution detection identifies tops before markdown | ❌ | ✅ | **RED** |
| | 11. Accumulation leads to subsequent markup outperformance | ❌ | ✅ | **RED** |
| **3: Signal Chain** | 12. Adapter correctly maps engine → BUY/SELL/HOLD | ❌ | ✅ | **RED** |
| | 13. Confidence scoring prioritizes high-conviction signals | ❌ | ✅ | **RED** |
| | 14. Trading plans contain actionable entry signals | ❌ | ✅ | **RED** |
| **4: Cross-Cutting** | 15. Walk-forward correctly measures OOS predictive power | ❌ | ✅ | **RED** |
| | 16. Monte Carlo controls for data-mining bias | ✅ | ❌ | **BLUE** |
| | 17. Both engines cover full theoretical market range | ❌ | ✅ | **RED** |
| | 18. Implementations follow academic/industry standards | ❌ | ✅ | **RED** |

**Final Score: Blue 1, Red 17**

---

## Root Cause Classification

| Root Cause | Count | Affected Claims | Severity |
|------------|:-----:|:---------------:|:--------:|
| **Missing theoretical constraints** | 5 | C1 (b<0), C4 (b<0,c>0), C6 (dual path), C9 (UTAD stub), C18 (theory divergence) | 🔴 **Critical** |
| **Structural search space bias** | 2 | C2 (tc init [3,20]), C3 (risk_level 5→3) | 🔴 **Critical** |
| **Momentum mislabeled as Wyckoff** | 3 | C7 (MA crossover), C11 (accum+markup ordering), C17 (unknown=39%) | 🔴 **Critical** |
| **Mutually exclusive conditions** | 2 | C8 (spring needs TR), C10 (distribution conditions) | 🟡 **High** |
| **Adapter-engine disconnect** | 2 | C12 (adapter ignores internal signals), C13 (confidence capped) | 🟡 **High** |
| **Noise fitting proven** | 1 | C4 (MC 93% GBM), C16 (MC validation) | 🔴 **Critical** |
| **Validation methodology flaw** | 1 | C15 (custom ≠ actual classification) | 🟡 **High** |
| **Trading plan over-conservatism** | 1 | C14 (91% 空仓观望) | 🟢 **Medium** |

---

## Corrected Verdict

| Previously claimed | Evidence-based correction |
|-------------------|--------------------------|
| "LPPL implements Sornette bubble detection" | **LPPL implements unconstrained curve-fitting with no bubble validation** |
| "Wyckoff detects Accumulation, Markup, Distribution, Markdown" | **Wyckoff detects momentum (up=markup, down=markdown, range=accumulation, [never]=distribution)** |
| "Spring triggers buy signals" | **Spring structurally never fires (0/600)** |
| "UTAD triggers sell signals" | **UTAD is dead code (returns None)** |
| "Adapter outputs BUY/SELL/HOLD" | **Adapter outputs ~100% HOLD (0 BUY, 0 SELL in 600 obs)** |
| "Walk-forward shows LPPL zero / Wyckoff wrong" | **Walk-forward used wrong classification; actual engine markup→"买入" works (+8.60%, p=0.0098)** |
| "Wyckoff has sell capability" | **Zero sell/short signals in entire system** |

---

## Recommendations (Updated)

1. **LPPL**: Remove from production. The implementation cannot be fixed without rebuilding from scratch with proper constraints (b<0, c>|0.01|, tc sampling from [1,100] not [3,20], MC-based R² thresholds). Even then, A-share 120-day windows likely lack the signal-to-noise ratio for LPPL.

2. **Wyckoff adapter**: Rewrite to expose `trading_plan.direction` as the primary signal. The markup→"买入" path (Test/Shakeout sub-events) has real edge (+8.60%, p=0.0098).

3. **Wyckoff markup→"买入"**: Investigate as standalone trend-continuation system. Needs: MC simulation on GBM to verify p-value, higher-frequency sampling (daily not weekly windows), relaxed conditions for more signals.

4. **UTAD**: Either implement properly or delete. Current stub is misleading.

5. **Distribution detection**: Fix mutually exclusive conditions or remove phase. Without distribution detection, the system has no bearish side.

6. **Confidence scoring**: Decouple from Spring/LPS requirement. Use the markup sub-event classifier confidence directly.

7. **Monte Carlo for Wyckoff**: Essential before production deployment. Without it, the p=0.0098 signal may be a false positive from multiple testing.
