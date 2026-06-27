# Strategy Performance Benchmarks

> Generated: 2026-06-17 15:02:02
> Environment: Python 3.12.3 on Linux x86_64
> Platform: Linux-6.14.0-37-generic-x86_64-with-glibc2.39
> Data source: **REAL**
> Working tree: UniQuant

---

## Overview

This benchmark measures execution time and signal quality for each of UniQuant's strategy engines. 
Each engine is run 3 times; reported times are averages. The engines tested are the core 
analytical components of the Brain layer (regime detection, Wyckoff volume-price analysis, 
CZSC Chan theory, LPPL bubble detection, NTF national team intervention detection, FSM state 
machine, Alpha decoupling) and the full ServiceContainer pipeline.

**Data note:** The DataFetcher API does not return live data in this environment. 
Real parquet files from `data/lake/` are used directly.

---

## Performance Summary

| Engine | Avg Time (ms) | Min (ms) | Max (ms) | Signal Distribution | Avg Confidence | Success Rate |
|--------|--------------:|--------:|--------:|:-------------------|--------------:|-------------:|
| RegimeDetector | 14.37 | 1.48 | 40.07 | NORMAL:3 | 2.9908 | 100% |
| WyckoffEngine | 18.68 | 17.76 | 19.63 | markup:3 | 0.5000 | 100% |
| CZSC | 7.61 | 7.00 | 8.67 | NONE:3 | 0.3000 | 100% |
| LPPLEngine | 562.12 | 515.41 | 621.68 | SAFE:3 | 0.0000 | 100% |
| NTFEngine | 0.22 | 0.16 | 0.32 | NONE:3 | 0.0000 | 100% |
| FSM | 1.43 | 1.14 | 1.86 | PROBE:3 | 0.0000 | 100% |
| AlphaDecoupler | 6.45 | 5.70 | 7.38 | POSITIVE:3 | 1.2652 | 100% |
| FullPipeline (ServiceContainer) | 126.44 | 123.16 | 128.10 | FORCE_WAIT:3 | 0.0000 | 100% |

---

## Engine-by-Engine Analysis

### RegimeDetector

- **Avg execution time:** 14.37 ms
- **Signal distribution:** {'NORMAL': 3}
- **Avg confidence:** 2.9908
- **Success rate:** 100%

### WyckoffEngine

- **Avg execution time:** 18.68 ms
- **Signal distribution:** {'markup': 3}
- **Avg confidence:** 0.5000
- **Success rate:** 100%

### CZSC

- **Avg execution time:** 7.61 ms
- **Signal distribution:** {'NONE': 3}
- **Avg confidence:** 0.3000
- **Success rate:** 100%

### LPPLEngine

- **Avg execution time:** 562.12 ms
- **Signal distribution:** {'SAFE': 3}
- **Avg confidence:** 0.0000
- **Success rate:** 100%

### NTFEngine

- **Avg execution time:** 0.22 ms
- **Signal distribution:** {'NONE': 3}
- **Avg confidence:** 0.0000
- **Success rate:** 100%

### FSM

- **Avg execution time:** 1.43 ms
- **Signal distribution:** {'PROBE': 3}
- **Avg confidence:** 0.0000
- **Success rate:** 100%

### AlphaDecoupler

- **Avg execution time:** 6.45 ms
- **Signal distribution:** {'POSITIVE': 3}
- **Avg confidence:** 1.2652
- **Success rate:** 100%

### FullPipeline (ServiceContainer)

- **Avg execution time:** 126.44 ms
- **Signal distribution:** {'FORCE_WAIT': 3}
- **Avg confidence:** 0.0000
- **Success rate:** 100%

---

## Interpretation

### Execution Time Tiers

| Tier | Range | Typical Engines | Suitable Use Case |
|------|-------|----------------|-------------------|
| Fast | < 50 ms | Regime, NTF, FSM, Alpha | Real-time scanning across full universe |
| Medium | 50–500 ms | CZSC, Wyckoff | Periodic scans, sector-level analysis |
| Slow | > 500 ms | LPPL, Full Pipeline | Deep research on small candidate set |

### Signal Quality Notes

- **Confidence values are engine-specific** and not directly comparable:
  - Regime: entropy-based percentile (0–1). Higher = more liquid/normal.
  - Wyckoff: letter grade A–D mapped to 0.9–0.3.
  - LPPL: R² goodness-of-fit (0–1).
  - Alpha: absolute divergence score.
  - FSM: state descriptor (IDLE/MONITOR/etc.), no numeric confidence.
  - NTF: boolean detection, no confidence scale.
- **Success rate < 100%** indicates engines that hit data quality edge cases.

### Data Quality Impact

- Wyckoff and CZSC depend on multi-period price structure and may behave differently 
  with synthetic vs real data.
- LPPL R² is sensitive to underlying trend shape.

---

## Raw Environment

```
Python:    3.12.3
Platform:  Linux-6.14.0-37-generic-x86_64-with-glibc2.39
Processor: x86_64
CPU count: 16
numpy:     2.4.6
pandas:    2.3.3
Data:      REAL
Stocks in lake: 5934
```

