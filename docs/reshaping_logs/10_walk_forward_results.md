# 10 Walk-Forward OOS Validation Results

生成时间: 2026-06-09 11:25

## 配置

- 训练窗口: 252d, 测试窗口: 63d
- 窗口数: 4
- 因子: 19 survivors

## OOS IC 汇总

| Metric | Value |
|--------|-------|
| OOS IC Mean | +0.0129 |
| OOS IC Std | 0.0696 |
| OOS ICIR | +0.1857 |

## PBO (Monte Carlo)

| Metric | Value |
|--------|-------|
| Actual OOS IC | +0.0129 |
| Random OOS IC (mean) | +0.0286 |
| PBO | 1.000 |
| Overfit | YES |

## 各窗口 OOS IC

- Window 1: train=2021-01-01..2021-12-20 test=2021-12-21..2022-03-17 → OOS IC=-0.1069
- Window 2: train=2021-03-31..2022-03-17 test=2022-03-18..2022-06-14 → OOS IC=+0.0414
- Window 3: train=2021-06-28..2022-06-14 test=2022-06-15..2022-09-09 → OOS IC=+0.0534
- Window 4: train=2021-09-23..2022-09-09 test=2022-09-12..2022-12-07 → OOS IC=+0.0638

## 最终权重

| Factor | Final Weight | Std Across Windows |
|--------|-------------|-------------------|
| momentum_20d | 0.0435 | 0.0036 |
| momentum_60d | 0.0335 | 0.0578 |
| volatility_20d | 0.0893 | 0.0364 |
| volatility_60d | 0.0874 | 0.0264 |
| ma_ratio_5_20 | 0.0535 | 0.0144 |
| ma_ratio_10_60 | 0.0893 | 0.0144 |
| volume_ratio_5_20 | 0.0304 | 0.0221 |
| rsi_14 | 0.0499 | 0.0202 |
| price_position_20d | 0.0321 | 0.0129 |
| turnover_momentum_20d | 0.0045 | 0.0013 |
| am_wyckoff_action | 0.0955 | 0.0177 |
| am_lppl_days_to_tc | 0.0423 | 0.0218 |
| am_regime_rsi_momentum | 0.0621 | 0.0095 |
| am_entropy_shock | 0.0511 | 0.0163 |
| am_stealth_accumulation | 0.0045 | 0.0157 |
| am_ma_dispersion_regime | 0.1214 | 0.0421 |
| am_wyckoff_contrarian | 0.0538 | 0.0359 |
| am_lppl_oscillation | 0.0513 | 0.0025 |
| am_multi_engine_ensemble | 0.0045 | 0.0141 |

## 存活因子 (传递至 Phase 3)

- `momentum_20d`
- `momentum_60d`
- `volatility_20d`
- `volatility_60d`
- `ma_ratio_5_20`
- `ma_ratio_10_60`
- `volume_ratio_5_20`
- `rsi_14`
- `price_position_20d`
- `turnover_momentum_20d`
- `am_wyckoff_action`
- `am_lppl_days_to_tc`
- `am_regime_rsi_momentum`
- `am_entropy_shock`
- `am_stealth_accumulation`
- `am_ma_dispersion_regime`
- `am_wyckoff_contrarian`
- `am_lppl_oscillation`
- `am_multi_engine_ensemble`
