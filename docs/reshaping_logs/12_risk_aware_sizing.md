# 12 Risk-Aware Position Sizing

生成时间: 2026-06-09 12:21

## 配置

- 数据: 504 天, 5 只股票
- 初始资金: ¥1,000,000/只
- 入场阈值: z > 0.7, 出场阈值: z < -0.3
- PositionSizer: risk_pct=5%, kelly_fraction=0.25
- PortfolioSizer: max_single=10%, max_daily_loss=2%

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

## 个股风险回报

| 股票 | 收益 | 最大回撤 | 交易数 |
|------|------|----------|--------|

## 组合风险 (EVTRisk + DrawdownAnalyzer)

| 指标 | 值 |
|------|-----|
| 组合收益 | +1.79% |
| 组合夏普 | 3.982 |
| 最大回撤 | -0.13% |
| VaR 95% | 0.00015210634339709922 |
| CVaR 95% | 0.000265863610884202 |
| 市场状态 | BULL |
| 综合结论 | 市场状态: BULL
95% VaR: 0.02%
最大回撤: 0.13%
NTF信号: 机会
宏观环境分析完成 |

## PositionSizer 使用

- **CN 市场惩罚**: 1.2× 风险乘数 (PositionSizer.market_penalties)
- **Kelly 分数**: 每笔交易动态计算 (基于历史胜率/盈亏比)
- **止损**: ATR-based (2× ATR below entry)
- **整手取整**: 100 股一手的 A 股规则
- **总交易次数**: 22

## 组合风控 (PortfolioSizer)

- 单一标的上限: 10% (max_single=0.10)
- 每日亏损熔断: -2% (超过则暂停交易)
- 总风险敞口: 25% 权益
