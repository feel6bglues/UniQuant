# Alpha Mining Graveyard

> Failed factors (ICIR < 0.4 or 3-attempt circuit breaker triggered). Session 2026-06-01.

| # | Name | Attempts | Failure Reason | Date |
|---|------|----------|----------------|------|
| 1 | vol_price_divergence_20d | 1 | ICIR=0.1255 (best@20d), IC=0.0374, IC>0=56.27%. Factor has weak positive IC but high variance (IC_std=0.2979). Volume-price divergence signal too noisy on daily frequency. | 2026-06-01 |
| 2 | intraday_intensity_20d | 1 | ICIR=-0.0457 (best@20d), IC=-0.0135, IC>0=50.06%. Intraday close position within range has near-zero predictive power. Daily range information already priced in. | 2026-06-01 |
| 3 | vol_weighted_momentum_20d | 1 | ICIR=-0.2889 (best@20d), IC=-0.0870, IC>0=37.28%. Moderate reversal signal — volume-weighted momentum has stronger predictive power than raw momentum (ICIR=-0.12) but still below 0.4 threshold. Volume weighting improves signal by 2.4x. | 2026-06-01 |
| 4 | range_compression_breakout | 1 | ICIR=0.0755 (best@5d), IC=0.0215, IC>0=53.81%. Range compression has weak predictive power. ATR ratio alone insufficient; need stronger directional filter. | 2026-06-01 |
| 5 | smart_money_flow_20d | 1 | ICIR=-0.2630 (best@20d), IC=-0.0791, IC>0=38.73%. Smart money flow has moderate reversal power. Intraday returns weighted by volume show consistent negative IC. Close to threshold — may improve with shorter window or rank normalization. | 2026-06-01 |
| 6 | rank_vol_momentum_20d | 1 | ICIR=-0.2889 (best@20d). Cross-sectional rank normalization did not improve over raw vol-weighted momentum. Same ICIR. | 2026-06-01 |
| 7 | composite_reversal_20d | 1 | ICIR=-0.2972 (best@20d), IC=-0.0905, IC>0=36.54%. Best composite so far — combining vol-momentum + smart-money improves slightly over individual components. Still below 0.4. | 2026-06-01 |
| 8 | vol_adj_momentum_20d | 1 | ICIR=-0.1276 (best@20d). Volatility-adjusted momentum (20d Sharpe) weaker than raw momentum. Normalizing by vol removes signal, not just noise. | 2026-06-01 |
| 9 | amihud_illiquidity_20d | 1 | ICIR=0.0955 (best@20d), IC=0.0303, IC>0=52.25%. Amihud illiquidity has weak positive IC. Limited universe (48 stocks) reduces cross-sectional dispersion needed for liquidity factors. | 2026-06-01 |
| 10 | abnormal_volume_20d | 1 | ICIR=-0.1430 (best@20d), IC=-0.0431, IC>0=43.59%. Abnormal volume dispersion has weak reversal power. Volume shock frequency alone insufficient. | 2026-06-01 |
| 11 | price_delay_20d | 1 | ICIR=-0.0060 (best@5d). Return autocorrelation has near-zero predictive power at daily frequency. Price delay effect too weak for daily OHLCV data. | 2026-06-01 |
| 12 | turnover_adj_reversal_60d | 1 | ICIR=0.1802 (best@20d), IC=0.0567, IC>0=57.29%. Turnover-adjusted reversal at 60d horizon has moderate positive IC. Longer lookback weaker than 20d for reversal signals. | 2026-06-01 |
| 13 | ultimate_composite_60d | 1 | ICIR=-0.1616 (best@20d), IC=-0.0501, IC>0=42.51%. 60-day composite weaker than 20-day composite (-0.2972). Longer lookback dilutes reversal signal. | 2026-06-01 |
| 14 | wy_phase_score | 1 | ICIR=-0.2325 (best@20d), IC=-0.0453, IC>0=37.54%. Wyckoff阶段方向×置信度有中等反转信号。Accumulation阶段信号在20日窗口内反而预测负收益,可能因为吸筹周期远长于20日。28只股票×3年数据。 | 2026-06-02 |
| 15 | wy_divergence | 1 | ICIR=0.1196 (best@5d), IC=0.0246, IC>0=56.24%. Wyckoff量价背离信号弱正向IC。ChipAnalysis的divergence_score在5日窗口有一定预测力,但IC_std=0.2060导致ICIR偏低。 | 2026-06-02 |
| 16 | wy_composite | 1 | ICIR=-0.1516 (best@20d), IC=-0.0285, IC>0=42.15%. Wyckoff多维复合信号(阶段+背离+资金流)有弱反转信号。复合后弱于单独phase_score,说明背离和资金流分量引入了噪声。 | 2026-06-02 |
| S5-6 | czsc_bi_momentum | 3 | CZSC engine `update_and_get_signals` only exposes `is_3rd_buy`+`bi_count`, no full buy/sell signal dict. bi_count z-score ICIR=0.19. | 2026-06-02 |
