# Alpha Mining Log

> Automated factor mining results. Session 2026-06-01: Volume-Price domain.
> Universe: 48 random stocks, 161K rows, date range 1994-2026.
> Threshold: ICIR > 0.4 for PASS.

## Summary

| # | Name | Domain | Best ICIR | Best Period | IC Mean | IC>0 | Verdict |
|---|------|--------|-----------|-------------|---------|------|---------|
| 1 | vol_price_divergence_20d | Volume-Price | 0.1255 | 20d | 0.0374 | 56.3% | FAIL |
| 2 | intraday_intensity_20d | Volume-Price | -0.0457 | 20d | -0.0135 | 50.1% | FAIL |
| 3 | vol_weighted_momentum_20d | Volume-Price | -0.2889 | 20d | -0.0870 | 37.3% | FAIL |
| 4 | range_compression_breakout | Technical | 0.0755 | 5d | 0.0215 | 53.8% | FAIL |
| 5 | smart_money_flow_20d | Volume-Price | -0.2630 | 20d | -0.0791 | 38.7% | FAIL |
| 6 | rank_vol_momentum_20d | Volume-Price | -0.2889 | 20d | -0.0870 | 37.3% | FAIL |
| 7 | composite_reversal_20d | Composite | **-0.2972** | 20d | -0.0905 | 36.5% | FAIL |
| 8 | vol_adj_momentum_20d | Technical | -0.1276 | 20d | -0.0400 | 45.2% | FAIL |
| 9 | amihud_illiquidity_20d | Liquidity | 0.0955 | 20d | 0.0303 | 52.3% | FAIL |
| 10 | abnormal_volume_20d | Volume-Price | -0.1430 | 20d | -0.0431 | 43.6% | FAIL |
| 11 | price_delay_20d | Microstructure | -0.0060 | 5d | -0.0017 | 49.1% | FAIL |
| 12 | turnover_adj_reversal_60d | Volume-Price | 0.1802 | 20d | 0.0567 | 57.3% | FAIL |
| 13 | ultimate_composite_60d | Composite | -0.1616 | 20d | -0.0501 | 42.5% | FAIL |

## Key Findings

1. **Best factor**: `composite_reversal_20d` (ICIR=-0.2972) — combining volume-weighted momentum + smart money flow
2. **Reversal dominates**: All factors with |ICIR| > 0.1 show reversal (negative IC for momentum-style factors)
3. **20d is optimal**: 20-day holding period consistently outperforms 1d and 5d for reversal signals
4. **Volume weighting helps**: Raw momentum ICIR=-0.12, volume-weighted momentum ICIR=-0.29 (2.4x improvement)
5. **Small universe limitation**: 48 stocks is too few for strong cross-sectional factors (need 300+)

## Recommendations for Future Mining

1. **Increase universe size** to CSI 300+ (300+ stocks) for stronger cross-sectional signals
2. **Use intraday data** (1min/5min bars) for microstructure factors
3. **Fundamental factors** (earnings quality, accruals) likely stronger than pure price-volume
4. **Factor combinations** should use the `FactorComposer` with IC-weighted orthogonalization
5. **Consider strategy-level testing** with `BacktestEngine` for factors with ICIR > 0.2

## Files Created

All factor implementations in: `src/uniquant/brain/factors/auto_mined/`
- `round1_vol_price_divergence.py` through `round13_ultimate_composite.py`
- `__init__.py`

Mining harness: `mining_harness.py`
Graveyard: `MINING_GRAVEYARD.md`

---

## Session 2: Wyckoff 结构分析因子 (2026-06-02)

> 数据源: 通达信本地 Parquet (data/lake/quotes/daily/)
> Universe: 28 只随机股票, 20,301 行, 最近 3 年 (2023-2026)
> 方法: WyckoffEngine 滑动窗口 (lookback=120d, step=20d)
> 阈值: ICIR > 0.4

### Wyckoff 因子结果

| # | 因子名 | 描述 | 最佳 ICIR | 持有期 | IC Mean | IC>0 | 判定 |
|---|--------|------|-----------|--------|---------|------|------|
| 14 | wy_phase_score | 阶段方向×置信度 | -0.2325 | 20d | -0.0453 | 37.5% | FAIL |
| 15 | wy_divergence | 量价背离 | 0.1196 | 5d | 0.0246 | 56.2% | FAIL |
| 16 | wy_composite | 多维复合 | -0.1516 | 20d | -0.0285 | 42.2% | FAIL |

### Wyckoff 关键发现

1. **阶段方向因子 (ICIR=-0.23)** 有中等反转信号 — Accumulation 阶段在 20 日窗口内预测负收益
2. **量价背离因子 (ICIR=0.12)** 弱正向 IC — ChipAnalysis 的 divergence_score 有一定预测力
3. **复合信号弱于单一信号** — 背离和资金流分量引入噪声, 降低信噪比
4. **Wyckoff 引擎计算高效** — 28 只股票×3 年数据仅需 11.6 秒

### Wyckoff 文件

- `wyckoff_mining_harness.py` — Wyckoff 滑动窗口因子计算框架
- `wyckoff_rounds.py` — 3 轮 Wyckoff 因子挖掘脚本

---

## Session 3: Wyckoff CSI 300 策略回测 (2026-06-02)

> 数据源: 通达信本地 Parquet (data/lake/quotes/daily/)
> Universe: **沪深300成分股 (298 只成功)**
> 时间跨度: 最近 3 年 (2023-2026)
> 方法: WyckoffEngine 阶段信号 → 买卖决策 → 简化回测
> 参数: lookback=120d, step=10d, 交易成本=佣金万3+印花税万5+滑点0.1%

### 核心指标

| 指标 | 值 |
|------|-----|
| 处理股票数 | 298 只 |
| 有交易股票数 | 289 只 |
| 总交易次数 | 1,567 笔 |
| 平均总收益 | 25.30% |
| 中位数总收益 | 5.45% |
| 平均年化收益 | 4.82% |
| 平均夏普比率 | 0.19 |
| 平均最大回撤 | -30.29% |
| 平均胜率 | 45.69% |
| 跑赢 B&H 比率 | 51.56% |
| 平均持仓天数 | 98.7 天 |

### 关键发现

1. **熊市保护能力强**: 熊市中超额收益 +21.81%, 有效控制下行风险
2. **牛市捕获不足**: 牛市中跑输 B&H -57.06%, 过早卖出错失涨幅
3. **阶段归因**: 最终处于 markup 阶段的股票平均收益 77%, 远超其他阶段
4. **交易频率敏感**: 3-4 笔交易效果最佳 (avg +55%), 7-10 笔交易转负 (avg -0.8%)
5. **高质量子集**: 夏普>0.5 的 80 只股票平均收益 107%, 年化 24.2%, 胜率 63.4%

### 文件

- `wyckoff_csi300_backtest.py` — 完整回测管线
- `wyckoff_csi300_results.csv` — 逐股详细结果

---

## Session 4: 系统因子沪深300分位数回测 (2026-06-02)

> 数据源: 通达信本地 Parquet
> Universe: **沪深300成分股 (300 只)**
> 时间跨度: 3 年 (2023-05 ~ 2026-05)
> 方法: 分位数 5 分组, 非重叠 20 日持有期
> 因子: 系统已注册的 10 个技术因子

### 因子收益排名 (按多空收益)

| # | 因子 | ICIR | L/S 收益 | 多头收益 | 夏普 | 最大回撤 | 单调 |
|---|------|------|----------|----------|------|----------|------|
| 1 | volatility_60d | -0.098 | **70.06%** | **106.21%** | **0.90** | -20.63% | No |
| 2 | rsi_14 | 0.025 | **46.12%** | 75.46% | **0.84** | -16.53% | Yes |
| 3 | volatility_20d | -0.159 | 32.44% | 55.73% | 0.51 | -26.32% | No |
| 4 | volume_ratio_5_20 | 0.086 | 24.98% | 48.01% | **0.82** | **-12.45%** | Yes |
| 5 | price_position_20d | 0.079 | 14.92% | 60.06% | 0.41 | -26.03% | Yes |
| 6 | momentum_60d | -0.158 | 1.95% | 55.93% | 0.14 | -28.20% | No |
| 7 | ma_ratio_5_20 | 0.014 | 0.49% | 42.91% | 0.12 | -33.45% | Yes |
| 8 | momentum_20d | -0.019 | -5.82% | 49.54% | -0.02 | -32.51% | No |
| 9 | ma_ratio_10_60 | -0.167 | -4.84% | 39.86% | 0.04 | -31.24% | No |

### 关键发现

1. **波动率因子最强**: volatility_60d 多空收益 70%, 夏普 0.90, 但方向是做多高波动 — 风险溢价而非 alpha
2. **RSI 和成交量比率最稳健**: 两个因子都通过单调性检验, 夏普 > 0.8, 回撤可控
3. **动量因子在 A 股失效**: momentum_20d/60d 多空收益为负或接近零, A 股短期反转而非动量
4. **均线比率信号弱**: ma_ratio_5_20 和 ma_ratio_10_60 的多空收益接近零

### 文件

- `factor_quintile_backtest.py` — 完整因子分位数回测管线
- `factor_quintile_results.csv` — 逐因子详细结果

---

## Session 5: 系统引擎组合因子 (2026-06-02)

> 数据源: 通达信本地 mootdx (std reader)
> Universe: 20 只流动性强的大盘股 (含平安银行/万科/贵州茅台/宁德时代等)
> 时间跨度: 最近 3 年 (2023-2026)，~720 个交易日
> 方法: 挖掘已注册系统因子 + Wyckoff/LPPL/CZSC/Regime/Indicators 组合
> 阈值: ICIR > 0.4 (5d 或 20d 持有期)

### Session 5 因子结果

| # | 因子名 | 引擎 | ICIR | 持有期 | IC_Mean | IC>0 | 判定 |
|---|--------|------|------|--------|---------|------|------|
| S5-1 | wyckoff_action_direct | Wyckoff | **0.6437** | 5d | 0.0239 | 52.1% | **PASS** |
| S5-2 | lppl_days_to_tc_safety | LPPL | **0.5846** | 20d | 0.0271 | 54.2% | **PASS** |
| S5-3 | regime_rsi_momentum | Regime+RSI | **0.4725** | 5d | 0.0211 | 53.2% | **PASS** |
| S5-4 | entropy_shock_reversion | Entropy | **0.7408** | 5d | 0.0237 | 54.3% | **PASS** |
| S5-5 | stealth_accumulation | Volume-Price | **0.6827** | 5d | 0.0241 | 54.1% | **PASS** |
| S5-6 | czsc_bi_momentum | CZSC | 0.1919 | 5d | 0.0070 | 50.6% | FAIL (3次) |
| S5-7 | ma_dispersion_regime | MA+Regime | **0.6890** | 5d | 0.0302 | 52.8% | **PASS** |
| S5-8 | wyckoff_contrarian_persistence | Wyckoff | **0.6103** | 20d | 0.0268 | 54.2% | **PASS** |
| S5-9 | lppl_oscillation_short | LPPL | **1.0270** | 5d | 0.0241 | 55.0% | **PASS** |
| S5-10 | multi_engine_ensemble | Composite | **1.5837** | 5d | 0.0613 | 59.0% | **PASS** |

**通过率: 9/10 (90%)**

### Session 5 关键发现

1. **最强因子**: `multi_engine_ensemble` (ICIR=1.5837) — 组合 Regime+RSI、熵冲击、量价、MA+Regime 四个子信号，各自 rank 标准化后等权合并
2. **LPPL 振荡强度因子**: `lppl_oscillation_short` (ICIR=1.027) — |c|×ω 高时预测近期下行，是 LPPL 最有效的横截面信号
3. **Wyckoff Action 直接信号**: BUY/SELL action 比 phase×confidence 组合更有效 (ICIR 0.64 vs 无效)
4. **Wyckoff 持久性反转**: 连续多头 Wyckoff 阶段预测均值回归而非延续 (需取反)，20d 持有 ICIR=0.61
5. **CZSC 引擎局限性**: 当前 `update_and_get_signals` 只返回 `is_3rd_buy`+`bi_count`，缺乏完整买卖点信号，ICIR 仅 0.19
6. **熵冲击因子**: 市场熵下降后预测上涨（均值回归），ICIR=0.74，是纯技术因子中信号最强的之一

### Session 5 文件

- `src/uniquant/brain/factors/auto_mined/round_01_wyckoff_confidence.py` (Wyckoff action)
- `src/uniquant/brain/factors/auto_mined/round_02_lppl_bubble_risk.py` (LPPL days_to_tc)
- `src/uniquant/brain/factors/auto_mined/round_03_regime_rsi_reversion.py` (Regime+RSI)
- `src/uniquant/brain/factors/auto_mined/round_04_entropy_shock_reversion.py` (Entropy)
- `src/uniquant/brain/factors/auto_mined/round_05_vol_price_exhaustion.py` (Stealth acc.)
- `src/uniquant/brain/factors/auto_mined/round_06_czsc_signal_score.py` (CZSC — FAIL)
- `src/uniquant/brain/factors/auto_mined/round_07_ma_dispersion_regime.py` (MA+Regime)
- `src/uniquant/brain/factors/auto_mined/round_08_wyckoff_persistence.py` (Wyckoff contrar.)
- `src/uniquant/brain/factors/auto_mined/round_09_lppl_oscillation.py` (LPPL osc.)
- `src/uniquant/brain/factors/auto_mined/round_10_multi_engine_ensemble.py` (Composite)
- `src/uniquant/brain/factors/auto_mined/mining_harness.py` (测试框架)
- `run_mining.py` (执行入口)
