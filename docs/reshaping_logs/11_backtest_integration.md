# 11 Backtest Integration Results

生成时间: 2026-06-09 11:34

## 配置

- 数据: 504 天, 5 只股票
- 初始资金: ¥1,000,000/只
- 入场阈值: z > 0.7, 出场阈值: z < -0.3
- 因子权重: cross-sectional IC/IR (全市场)

## 因子权重

| 因子 | 权重 |
|------|------|
| am_regime_rsi_momentum | 0.1084 |
| ma_ratio_5_20 | 0.1006 |
| am_ma_dispersion_regime | 0.0991 |
| rsi_14 | 0.0962 |
| momentum_20d | 0.0960 |
| price_position_20d | 0.0871 |
| ma_ratio_10_60 | 0.0782 |
| momentum_60d | 0.0692 |
| am_wyckoff_contrarian | 0.0653 |
| am_lppl_days_to_tc | 0.0481 |
| am_stealth_accumulation | 0.0385 |
| volatility_60d | 0.0319 |
| am_multi_engine_ensemble | 0.0247 |
| am_entropy_shock | 0.0193 |
| volatility_20d | 0.0182 |
| am_lppl_oscillation | 0.0110 |
| volume_ratio_5_20 | 0.0050 |
| turnover_momentum_20d | 0.0016 |
| am_wyckoff_action | 0.0016 |

## 个股回测

| 股票 | 总收益 | 夏普 | 最大回撤 | 交易数 | 胜率 |
|------|--------|------|----------|--------|------|
| 600000.SH (PingAn) | +0.38% | 1.147 | -0.16% | 4 | 50% |
| 600001.SH (ICBC) | +0.65% | 1.426 | -0.23% | 5 | 40% |
| 600002.SH (PetroChina) | +3.73% | 2.351 | -0.56% | 5 | 40% |
| 600003.SH (CMB) | +1.42% | 1.668 | -0.26% | 6 | 50% |
| 600004.SH (CNShenhua) | +2.27% | 2.006 | -0.44% | 2 | 50% |

## 等权投资组合

| 指标 | 值 |
|------|-----|
| 总投资收益率 | +1.68% |
| 组合夏普比率 | 3.918 |
| 组合最大回撤 | -0.14% |
| 总交易次数 | 22 |
| 活跃股票数 | 5/5 |
