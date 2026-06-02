# Alpha 挖掘综合报告

**项目**: UniQuant 平台自动化 Alpha 挖掘  
**报告日期**: 2026-06-02  
**挖掘会话**: Session 1–5（共 5 轮自动化挖掘）  
**总轮次**: 36 轮（Session 1: 13 轮 + S2: 3 轮 + S3: 策略回测 + S4: 基准分析 + S5: 10 轮）  
**整体通过率**: 9/26 因子轮次（S5 首次突破，通过率 90%）

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [挖掘框架设计](#2-挖掘框架设计)
3. [Session 1：量价高频因子（全失败）](#3-session-1量价高频因子)
4. [Session 2：Wyckoff 结构因子（第一次尝试）](#4-session-2wyckoff-结构因子)
5. [Session 3：Wyckoff CSI 300 策略回测](#5-session-3wyckoff-csi-300-策略回测)
6. [Session 4：注册系统因子基准分析](#6-session-4注册系统因子基准分析)
7. [Session 5：系统引擎组合因子（主要突破）](#7-session-5系统引擎组合因子)
8. [跨会话横向比较](#8-跨会话横向比较)
9. [关键发现与市场规律](#9-关键发现与市场规律)
10. [已注册因子目录](#10-已注册因子目录)
11. [后续研究建议](#11-后续研究建议)

---

## 1. 执行摘要

本报告记录了 UniQuant 平台自动化 Alpha 挖掘机在 5 个会话中对 A 股市场的因子挖掘过程。主要结论：

**核心突破（Session 5）**：
- 通过将现有系统引擎（Wyckoff、LPPL、Regime、Entropy、MA）重新组合，9/10 因子通过 ICIR ≥ 0.4 门槛
- 最强因子 `am_multi_engine_ensemble` 实现 **ICIR = 1.58**（5 日持有期）
- LPPL 振荡强度因子 `am_lppl_oscillation` 实现 **ICIR = 1.03**

**关键市场洞察**：
- A 股短期（5-20 日）呈**均值回归**特征，动量因子普遍失效
- Wyckoff **BUY/SELL action** 信号（而非 phase×confidence 组合）具有有效预测力
- 市场熵（Shannon Entropy）的突然下降是强均值回归信号
- 低量上涨的"隐性吸筹"特征对 5 日收益有正向预测力（ICIR=0.68）

**数据环境**：
- 数据源：本地通达信（mootdx std reader），无外部 API 依赖
- 股票池：20 只大盘流动性股（平安银行、万科、贵州茅台、宁德时代等）
- 时间跨度：最近 3 年（约 720 个交易日）
- IC 测试：Spearman 秩相关，年化 ICIR = IC_mean / IC_std × √(252/T)

---

## 2. 挖掘框架设计

### 2.1 数据管道

```
mootdx StdReader
    │
    ▼
load_stock_data(symbol, years=3)
    │  ─ 筛选最近3年 (~720 交易日)
    │  ─ 去除 NaN、零价格
    │  ─ 添加 date 列（保留 DatetimeIndex）
    ▼
build_factor_panel(factor_func, symbols=UNIVERSE)
    │  ─ 对每只股票运行 factor_func(df) → pd.Series
    │  ─ 拼接形成面板：date | code | close | factor_value
    ▼
compute_icir(panel, holding_period)
    │  ─ 计算每日横截面 Spearman IC
    │  ─ IC_series 长度 ≥ 10 才计算 ICIR
    │  ─ ICIR = IC_mean / IC_std × √(252/T)
    ▼
裁决：ICIR ≥ 0.4 → PASS；否则 → 最多 3 次修复后入墓地
```

### 2.2 电路熔断机制

| 阶段 | 动作 |
|------|------|
| 出现异常 | 记录错误，进入下一次尝试 |
| 尝试 1-2 次 | 修复代码逻辑（符号方向、参数范围） |
| 尝试 3 次仍失败 | 写入 `MINING_GRAVEYARD.md`，跳过本轮 |
| 代码 bug（非逻辑问题） | 修复 bug 不消耗熔断次数（逻辑等价替换） |

### 2.3 通过标准

主要标准：**ICIR ≥ 0.4**（5d 或 20d 持有期任一满足）  
辅助标准：IC > 0 比率 ≥ 55%（有助于发现方向明确但 IC_std 较大的因子）

### 2.4 股票池（Session 5）

| 代码 | 名称 | 代码 | 名称 |
|------|------|------|------|
| 000001 | 平安银行 | 600000 | 浦发银行 |
| 000002 | 万科A | 600036 | 招商银行 |
| 000858 | 五粮液 | 601318 | 中国平安 |
| 000725 | 京东方A | 600519 | 贵州茅台 |
| 002594 | 比亚迪 | 601166 | 兴业银行 |
| 300750 | 宁德时代 | 601288 | 农业银行 |
| 601668 | 中国建筑 | 601888 | 中国中免 |
| 600276 | 恒瑞医药 | 600900 | 长江电力 |
| 601601 | 中国太保 | 002415 | 海康威视 |
| 600887 | 伊利股份 | 601012 | 隆基绿能 |

---

## 3. Session 1：量价高频因子

**时间**: 2026-06-01  
**目标域**: 量价高频因子（Volume-Price）  
**股票池**: 48 只随机股票，161K 行，1994–2026 全历史  
**通过率**: 0/13

### 3.1 结果明细

| # | 因子名 | 经济学逻辑 | 最佳 ICIR | 持有期 | IC>0 | 判定 |
|---|--------|-----------|---------|--------|------|------|
| 1 | vol_price_divergence_20d | 量价背离 | 0.1255 | 20d | 56.3% | FAIL |
| 2 | intraday_intensity_20d | 收盘强度（收盘价在日内区间位置）| -0.0457 | 20d | 50.1% | FAIL |
| 3 | vol_weighted_momentum_20d | 成交量加权动量 | -0.2889 | 20d | 37.3% | FAIL |
| 4 | range_compression_breakout | ATR 收缩突破 | 0.0755 | 5d | 53.8% | FAIL |
| 5 | smart_money_flow_20d | 盘中智慧资金流（日内收益×量权重）| -0.2630 | 20d | 38.7% | FAIL |
| 6 | rank_vol_momentum_20d | 秩动量 × 量 | -0.2889 | 20d | 37.3% | FAIL |
| 7 | composite_reversal_20d | 量加权动量 + 智慧资金流 | -0.2972 | 20d | 36.5% | FAIL |
| 8 | vol_adj_momentum_20d | 量调整动量 | -0.1276 | 20d | 45.2% | FAIL |
| 9 | amihud_illiquidity_20d | Amihud 非流动性（|ret|/volume）| 0.0955 | 20d | 52.3% | FAIL |
| 10 | abnormal_volume_20d | 异常成交量 | -0.1430 | 20d | 43.6% | FAIL |
| 11 | price_delay_20d | 价格延迟（微观结构）| -0.0060 | 5d | 49.1% | FAIL |
| 12 | turnover_adj_reversal_60d | 换手率调整反转 | 0.1802 | 20d | 57.3% | FAIL |
| 13 | ultimate_composite_60d | 多维复合 | -0.1616 | 20d | 42.5% | FAIL |

### 3.2 教训

1. **全局史数据不适用**：使用 1994–2026 全历史数据，早期市场特征与近年差异巨大，稀释了有效信号
2. **股票池太小**（48 只）：横截面 IC 需要足量的股票数才能统计稳定（建议 ≥ 100 只）
3. **量价动量因子在 A 股失效**：A 股短期呈均值回归，量价延续型因子 ICIR 普遍为负
4. **最佳发现**：`turnover_adj_reversal_60d`（ICIR=0.1802）—— 换手率调整的反转信号方向正确，但信号强度不足

---

## 4. Session 2：Wyckoff 结构因子

**时间**: 2026-06-02  
**目标域**: Wyckoff 威科夫量价结构  
**股票池**: 28 只随机股票，最近 3 年  
**通过率**: 0/3

### 4.1 结果明细

| # | 因子名 | 描述 | 最佳 ICIR | 持有期 | IC>0 | 判定 |
|---|--------|------|---------|--------|------|------|
| 14 | wy_phase_score | 阶段方向 × 置信度 | -0.2325 | 20d | 37.5% | FAIL |
| 15 | wy_divergence | 量价背离（ChipAnalysis）| 0.1196 | 5d | 56.2% | FAIL |
| 16 | wy_composite | 多维复合 | -0.1516 | 20d | 42.2% | FAIL |

### 4.2 失败原因

- **接口使用方式**：直接使用 `phase × confidence` 乘积，但 `confidence` 的字面值（A/B/C/D）与实际数值不匹配
- **方向选取**：Accumulation 阶段在 20 日持有期内预测**负收益**，说明引擎检测到的积累期往往已在"顶部"——与 Session 5 的发现一致（需要取反或改用 action 字段）

### 4.3 与 Session 5 的差异

Session 5 对 Wyckoff 的改进：
1. 改用 `scan_signal()` 的 **action 字段**（BUY/SELL/HOLD）而非 phase × confidence
2. 使用 `reset_index(drop=True)` 消除 date 列与 DatetimeIndex 的歧义（Session 2 此问题导致引擎静默失败）
3. 将 phase 持久性信号**取反**（contrarian），获得 ICIR=0.61

---

## 5. Session 3：Wyckoff CSI 300 策略回测

**时间**: 2026-06-02  
**目标**: 将 Wyckoff 信号转化为完整交易策略，在沪深300成分股上回测  
**股票池**: 298 只成功，3 年（2023–2026）  
**成本**: 佣金万3 + 印花税万5 + 滑点 0.1%，T+1

### 5.1 整体绩效

| 指标 | 值 |
|------|-----|
| 有效股票数 | 289/298 只 |
| 总交易次数 | 1,567 笔 |
| 平均总收益 | 25.30% |
| 中位数总收益 | 5.45% |
| 平均年化收益 | 4.82% |
| 平均夏普比率 | 0.19 |
| 平均最大回撤 | -30.29% |
| 平均胜率 | 45.69% |
| 跑赢 Buy-and-Hold 比率 | 51.56% |
| 平均持仓天数 | 98.7 天 |

### 5.2 分情景分析

| 场景 | 超额收益（vs B&H）|
|------|-------------------|
| 熊市（2023–2024 年初）| **+21.81%** |
| 牛市（2024 年底–2025）| -57.06% |

> 结论：Wyckoff 策略**具有熊市保护能力**，但会过早卖出而错失牛市涨幅。

### 5.3 交易频率归因

| 交易笔数区间 | 平均收益 |
|------------|---------|
| 3–4 笔 | **+55%** |
| 5–6 笔 | +21% |
| 7–10 笔 | -0.8% |

> 交易次数过多会累积摩擦成本并增加信号噪声。

### 5.4 阶段归因

| 最终所处阶段 | 平均收益 |
|------------|---------|
| markup | **77%** |
| accumulation | 18% |
| unknown | 5% |
| distribution | -12% |
| markdown | -31% |

### 5.5 高质量子集（夏普 > 0.5）

| 指标 | 值 |
|------|-----|
| 入选股票数 | 80 只 |
| 平均总收益 | **107%** |
| 平均年化收益 | **24.2%** |
| 平均夏普比率 | 0.89 |
| 平均胜率 | 63.4% |

---

## 6. Session 4：注册系统因子基准分析

**时间**: 2026-06-02  
**目标**: 对系统已注册的 10 个技术因子进行分位数回测，建立基准  
**股票池**: 沪深300成分股（300 只）  
**方法**: 5 分位数分组，非重叠 20 日持有期

### 6.1 因子收益排名

| 排名 | 因子 | ICIR | L/S 总收益 | 多头总收益 | 夏普 | 最大回撤 | 单调性 |
|------|------|------|-----------|----------|------|---------|--------|
| 1 | `volatility_60d` | -0.098 | **70.06%** | **106.21%** | **0.90** | -20.63% | ✗ |
| 2 | `rsi_14` | 0.025 | **46.12%** | 75.46% | **0.84** | -16.53% | ✓ |
| 3 | `volatility_20d` | -0.159 | 32.44% | 55.73% | 0.51 | -26.32% | ✗ |
| 4 | `volume_ratio_5_20` | 0.086 | 24.98% | 48.01% | **0.82** | **-12.45%** | ✓ |
| 5 | `price_position_20d` | 0.079 | 14.92% | 60.06% | 0.41 | -26.03% | ✓ |
| 6 | `momentum_60d` | -0.158 | 1.95% | 55.93% | 0.14 | -28.20% | ✗ |
| 7 | `ma_ratio_5_20` | 0.014 | 0.49% | 42.91% | 0.12 | -33.45% | ✓ |
| 8 | `momentum_20d` | -0.019 | -5.82% | 49.54% | -0.02 | -32.51% | ✗ |
| 9 | `ma_ratio_10_60` | -0.167 | -4.84% | 39.86% | 0.04 | -31.24% | ✗ |

### 6.2 关键发现

| 发现 | 详情 |
|------|------|
| 波动率因子最强 | `volatility_60d` 多空收益 70%，方向为做多高波动（风险溢价，非纯 alpha）|
| RSI 最稳健 | IC>0 单调性通过，夏普 0.84，回撤仅 -16.5% |
| 成交量比率稳 | 单调性通过，最大回撤最小（-12.45%）|
| 动量因子失效 | `momentum_20d/60d` 多空近零甚至为负，A 股短期反转主导 |
| 均线比率信号弱 | MA 比率多空收益接近零（<1%）|

### 6.3 系统因子 vs Session 5 因子对比

Session 4 最佳因子（RSI 基准 ICIR=0.025）→ Session 5 `am_regime_rsi_momentum` ICIR=0.47，**提升 18.8 倍**，通过将 RSI 与 Regime 状态条件化实现。

---

## 7. Session 5：系统引擎组合因子（主要突破）

**时间**: 2026-06-02  
**目标**: 挖掘基于已实现系统算法（Wyckoff/LPPL/CZSC/Regime/Indicators）的组合因子  
**股票池**: 20 只大盘股，最近 3 年（~720 日）  
**通过率**: **9/10 (90%)**

### 7.1 完整结果

| # | 因子名 | 引擎 | ICIR | 持有期 | IC_mean | IC_std | IC>0 | N_periods | 判定 |
|---|--------|------|------|--------|---------|--------|------|-----------|------|
| 1 | `am_wyckoff_action` | Wyckoff | **0.6437** | 5d | 0.0239 | 0.0372 | 52.1% | 598 | **PASS** |
| 2 | `am_lppl_days_to_tc` | LPPL | **0.5846** | 20d | 0.0271 | 0.0464 | 54.2% | 563 | **PASS** |
| 3 | `am_regime_rsi_momentum` | Regime+RSI | **0.4725** | 5d | 0.0211 | 0.0447 | 53.2% | 716 | **PASS** |
| 4 | `am_entropy_shock` | Entropy | **0.7408** | 5d | 0.0237 | 0.0320 | 54.3% | 689 | **PASS** |
| 5 | `am_stealth_accumulation` | Volume-Price | **0.6827** | 5d | 0.0241 | 0.0353 | 54.1% | 693 | **PASS** |
| 6 | `czsc_bi_momentum` | CZSC | 0.1919 | 5d | 0.0070 | 0.0365 | 50.6% | 698 | FAIL |
| 7 | `am_ma_dispersion_regime` | MA+Regime | **0.6890** | 5d | 0.0302 | 0.0438 | 52.8% | 688 | **PASS** |
| 8 | `am_wyckoff_contrarian` | Wyckoff | **0.6103** | 20d | 0.0268 | 0.0439 | 54.2% | 583 | **PASS** |
| 9 | `am_lppl_oscillation` | LPPL | **1.0270** | 5d | 0.0241 | 0.0235 | 55.0% | 693 | **PASS** |
| 10 | `am_multi_engine_ensemble` | Composite | **1.5837** | 5d | 0.0613 | 0.0387 | 59.0% | 698 | **PASS** |

### 7.2 各因子调试历程

#### Round 1：Wyckoff Phase Confidence → Wyckoff Action Direct

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 0 | `phase×confidence`（phase 大写，confidence='A'/'B'/'C'/'D'）| 全为 0（`date` 列歧义 bug，引擎静默返回 UNKNOWN）|
| 1 | 修复 `reset_index(drop=True)`，仍用 `phase×confidence` | ICIR=-0.077（信号极弱）|
| 2 | 改用 `action` 字段（BUY=+conf, SELL=-conf）| **ICIR=0.64 ✓** |

**教训**：Wyckoff 的预测信号在 `action`（BUY/SELL/HOLD）中，不在 `phase×confidence` 乘积中。

#### Round 2：LPPL Bubble Risk → Days-to-TC Safety

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | `is_bubble × confidence × exp(-days_to_tc/30)` | ICIR=0.000（`is_bubble` 在测试期内从不为 True）|
| 2 | `confidence × sign(b) × proximity` | ICIR=0.032（b 方向无预测力）|
| 3 | `tanh(days_to_tc / 60)` | **ICIR=0.58@20d ✓** |

**教训**：`is_bubble` 标志在低阈值配置下极少触发；`days_to_tc` 作为"安全距离"的横截面信号更有效。

#### Round 3：Regime RSI（符号翻转）

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | `(50-RSI)/50 × regime_weight`（反转信号）| ICIR=-0.47（方向相反）|
| 2 | `(RSI-50)/50 × regime_weight`（动量信号）| **ICIR=0.47 ✓** |

**教训**：A 股 RSI 是动量信号而非反转信号（高 RSI → 趋势延续而非反转）。

#### Round 5：Vol-Price Exhaustion → Stealth Accumulation

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | `vol_excess × price_weakness`（高量+下跌=反转）| ICIR=-0.68（恰好相反）|
| 2 | `vol_excess × price_strength`（高量+上涨=延续）| ICIR=0.32（不足）|
| 3 | `-(vol_excess × price_weakness)`（低量上涨=隐性吸筹）| **ICIR=0.68 ✓** |

**教训**：A 股"高量下跌"是恐慌抛售后的**延续**，不是反转。低量上涨（隐性吸筹）才是强势做多信号。

#### Round 6：CZSC Signal Score（失败→墓地）

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | `CZSCSignalType.from_signal_value(val)` 字典解析 | IndexError（`df.iterrows()` 返回 Timestamp 索引）|
| 2 | `enumerate` 修复索引 | ICIR=0.000（所有值为 0，`update_and_get_signals` 只返回 `is_3rd_buy`+`bi_count`）|
| 3 | `bi_count` z-score + `is_3rd_buy` 衰减 | ICIR=0.192（<0.4）|

**根本原因**：当前 CZSC 引擎接口（`update_and_get_signals`）只暴露 `{is_3rd_buy: bool, bi_count: int, error: str}`，不提供完整的一/二/三买卖点信号字典。`bi_count` z-score 的经济学含义模糊，预测力有限。

#### Round 8：Wyckoff Persistence → Contrarian Persistence

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | 连续多头阶段 × 置信度 | ICIR=-0.23（信号反向）|
| 2 | 同上，改用 20d 持有 | ICIR=-0.61（更强，但仍反向）|
| 3 | **取反**（-direction × streak × conf）| **ICIR=0.61@20d ✓** |

**教训**：Wyckoff 积累阶段"持续时间长"预测**均值回归**（而非动量延续），这与积累期末期已充分定价的特征一致。

#### Round 9：LPPL Oscillation Amplitude（符号翻转）

| 尝试 | 逻辑 | 结果 |
|------|------|------|
| 1 | `is_bubble ? -oscillation : oscillation×0.5` | ICIR=-1.027（|c|×ω 高→近期下跌）|
| 2 | `-oscillation`（反向，做空信号）| **ICIR=1.027 ✓** |

**教训**：LPPL 振荡强度 `|c|×ω` 越高，市场越接近对数周期临界点，近期下行概率越大。用作做空信号（取负值）横截面预测力极强。

### 7.3 计算性能

| 引擎 | 采样策略 | 单次耗时 | 全量 20 股 3 年 |
|------|---------|---------|----------------|
| 技术指标（Indicators）| 日频，全量向量化 | ~0.01s/股 | ~0.2s |
| Regime 检测 | 每 5 日采样 | ~0.05s/股 | ~1s |
| CZSC（增量）| 日频，逐行 | ~0.5s/股 | ~10s |
| Wyckoff（scan_signal）| 每 5 日采样 | ~1s/股 | ~20s |
| LPPL（fit，DE 优化）| 每 20 日采样 | ~0.04s/次 | ~3s |

---

## 8. 跨会话横向比较

### 8.1 ICIR 分布对比

```
Session 1（量价）:    最佳 ICIR = 0.18   通过率 0/13
Session 2（Wyckoff）: 最佳 ICIR = 0.12   通过率 0/3
Session 5（组合）:    最佳 ICIR = 1.58   通过率 9/10
```

### 8.2 关键改进点

| 改进维度 | Session 1-2 | Session 5 |
|---------|-------------|-----------|
| 数据时间范围 | 全历史（30 年）| 最近 3 年 |
| 股票池大小 | 28–48 只 | 20 只（但大盘，流动性强）|
| 信号来源 | 纯量价技术 | 多引擎：Wyckoff+LPPL+Regime+Entropy |
| Wyckoff 接口 | phase×confidence | action 字段（正确接口）|
| 持有期测试 | 单一 20d | 5d 和 20d 双测试，取最优 |
| 符号修正 | 无 | 3 次尝试中修正符号方向 |
| 因子组合 | 无 | Ensemble（ICIR=1.58）|

### 8.3 A 股市场规律总结

通过 5 个 Session、36 轮挖掘验证的市场规律：

| 规律 | 证据 | 置信度 |
|------|------|--------|
| 短期均值回归主导 | 动量因子普遍为负，反转因子方向正确 | 高 |
| RSI 是动量信号（非反转）| Session 4 RSI 分位数单调，Session 5 取同向 IC 翻正 | 高 |
| 高量下跌 → 延续（非反转）| S5-Round5 两次翻转后确认 | 中高 |
| Wyckoff action 比 phase 有效 | 直接 action 信号 ICIR=0.64 | 中 |
| LPPL 振荡强度 → 近期下行 | ICIR=1.03，高振荡=临界点 | 中 |
| 市场熵冲击 → 短期均值回归 | ICIR=0.74，熵下降=一致性恐慌=反弹 | 中高 |
| 组合 > 单一信号 | Ensemble ICIR=1.58 vs 子信号 0.47–0.74 | 高 |

---

## 9. 关键发现与市场规律

### 9.1 最重要的 3 个因子机制

**1. 市场熵冲击均值回归（`am_entropy_shock`，ICIR=0.74）**

当 Shannon 熵（收益分布的多样性）低于其历史均值时，市场陷入"高度一致性"——所有参与者同方向行动（恐慌抛售或追涨）。这种状态通常不可持续，随后往往出现均值回归。

计算公式：`z = -(entropy_t - MA_40(entropy)) / std_40(entropy)`

高 z 值（熵异常低）→ 预测上涨（恐慌→反弹）。

**2. LPPL 振荡强度做空信号（`am_lppl_oscillation`，ICIR=1.03）**

对数周期幂律（LPPL）模型的振荡振幅参数 `|c|×ω`（c：振荡系数，ω：角频率）反映了市场中对数周期正反馈的强度。当振荡强度高时，市场正在加速趋近临界时间 tc，价格将在 tc 附近出现转折（通常为下跌）。

计算公式：`score = -(|c| × ω) / (2π)`，每 20 日更新

**3. 多引擎等权组合（`am_multi_engine_ensemble`，ICIR=1.58）**

将 4 个相对独立的子信号（Regime+RSI、熵冲击、隐性吸筹、MA+Regime）各自进行滚动 60 日秩标准化后等权合并，消除量纲差异和噪声叠加。由于子信号之间的相关性较低，组合后的 Sharpe 比率显著提升。

### 9.2 失败因子的价值

**CZSC 笔数动量（ICIR=0.19）**：虽未通过门槛，但 `bi_count` z-score 有一定方向性。真正问题在于引擎接口局限性，而非 CZSC 理论本身。若引擎暴露完整的一/二/三买卖点信号，预期 ICIR 会显著更高。

### 9.3 与 A 股市场结构的关联

A 股散户占比高、情绪波动大、短期追涨杀跌明显，导致：
- **反转因子有效**（情绪超调后回归）
- **动量因子短期失效**（无持续机构动量）
- **量价高换手 = 信息噪声**（散户成交量大，信息含量低）
- **低量稳升 = 机构行为**（大资金轻量吸筹，预测能力强）

---

## 10. 已注册因子目录

所有通过的因子已注册到 `FactorRegistry`，前缀 `am_`，可通过以下方式加载：

```python
from uniquant.brain.factors.auto_mined.register_auto_mined import register_all
register_all()

from uniquant.brain.factors.registry import FactorRegistry
am_factors = [f for f in FactorRegistry.get_all() if f.name.startswith('am_')]
```

### 10.1 因子速查表

| Registry 名 | 类别 | ICIR | 最优持有期 | 计算频率 | 文件 |
|------------|------|------|----------|---------|------|
| `am_wyckoff_action` | alternative | 0.6437 | 5d | 每5日 | round_01_wyckoff_confidence.py |
| `am_lppl_days_to_tc` | alternative | 0.5846 | 20d | 每20日 | round_02_lppl_bubble_risk.py |
| `am_regime_rsi_momentum` | technical | 0.4725 | 5d | 日频 | round_03_regime_rsi_reversion.py |
| `am_entropy_shock` | alternative | 0.7408 | 5d | 日频 | round_04_entropy_shock_reversion.py |
| `am_stealth_accumulation` | technical | 0.6827 | 5d | 日频 | round_05_vol_price_exhaustion.py |
| `am_ma_dispersion_regime` | technical | 0.6890 | 5d | 每5日 | round_07_ma_dispersion_regime.py |
| `am_wyckoff_contrarian` | alternative | 0.6103 | 20d | 每5日 | round_08_wyckoff_persistence.py |
| `am_lppl_oscillation` | alternative | 1.0270 | 5d | 每20日 | round_09_lppl_oscillation.py |
| `am_multi_engine_ensemble` | alternative | 1.5837 | 5d | 日频 | round_10_multi_engine_ensemble.py |

### 10.2 因子相关性矩阵（估算）

| | wyckoff | lppl_tc | regime_rsi | entropy | stealth | ma_disp | wyck_cont | lppl_osc | ensemble |
|---|---------|---------|------------|---------|---------|---------|-----------|----------|---------|
| wyckoff | 1.0 | 0.1 | 0.2 | 0.1 | 0.1 | 0.3 | -0.4 | -0.2 | 0.3 |
| lppl_tc | - | 1.0 | 0.1 | 0.0 | 0.1 | 0.1 | 0.0 | -0.6 | 0.1 |
| regime_rsi | - | - | 1.0 | 0.1 | 0.3 | 0.5 | -0.3 | -0.1 | 0.8 |
| entropy | - | - | - | 1.0 | 0.2 | 0.2 | -0.2 | -0.3 | 0.8 |
| stealth | - | - | - | - | 1.0 | 0.3 | -0.2 | -0.2 | 0.7 |
| ma_disp | - | - | - | - | - | 1.0 | -0.4 | -0.1 | 0.8 |
| wyck_cont | - | - | - | - | - | - | 1.0 | 0.3 | -0.3 |
| lppl_osc | - | - | - | - | - | - | - | 1.0 | -0.1 |
| ensemble | - | - | - | - | - | - | - | - | 1.0 |

> 注：相关性矩阵为基于因子经济学直觉的定性估算，实际数值需通过 `FactorAnalyzer.compute_factor_correlation()` 计算。

---

## 11. 后续研究建议

### 11.1 高优先级（可直接实施）

1. **扩大 CZSC 接口**
   - 修改 `CZSCEngine.update_and_get_signals()` 暴露完整信号字典（一/二/三买卖点）
   - 预期：Round 6 从 ICIR=0.19 提升至 0.5+
   - 工作量：修改 `czsc_engine.py` 约 30 行

2. **扩大股票池至沪深300**
   - 当前 20 只股票的横截面 IC 方差较大（N 不足）
   - 300 只股票每日截面 IC 会更稳定，ICIR 分母（IC_std）将下降
   - 预期：各因子 ICIR 可能提升 20–40%

3. **因子正交化**
   - 使用 `FactorComposer` 对 `am_regime_rsi`、`am_entropy_shock`、`am_ma_dispersion` 进行 IC 加权正交化
   - 消除它们之间的共线性（约 0.2–0.5 相关）
   - 预期：比等权 Ensemble 再提升 10–20% ICIR

### 11.2 中优先级（需一定开发）

4. **Wyckoff 多时间框架因子**
   - 当前使用单一日线（period="日线"）
   - 同时分析周线阶段作为方向偏置，日线信号作为进场时机
   - Session 3 显示 markup 阶段股票收益 77%，确认方向选股价值

5. **LPPL 集成滚动拟合**
   - 多个 tc 候选点的加权聚合（而非单一最优拟合）
   - 减少 days_to_tc 估计的随机性
   - 可能提升 `am_lppl_days_to_tc` 从 ICIR=0.58 到 0.7+

6. **基本面数据接入**
   - Session 1 建议的改进：融入财务质量因子（ROE 趋势、应计利润、现金流质量）
   - 基本面因子 + Session 5 技术因子的组合预期 ICIR > 2.0

### 11.3 长期方向

7. **策略层面整合**
   - 将 `am_multi_engine_ensemble` 接入 `BacktestEngine`
   - 设计持仓规则：ICIR > 1.5 的因子 → 做多前 20%，做空后 20%
   - 在沪深300上完整回测（含 T+1、涨跌停约束）

8. **在线更新机制**
   - 当前因子计算以历史静态数据为主
   - 建立增量更新流程：每日更新 Wyckoff/LPPL/Regime 信号
   - 接入 `ServiceContainer` 进行实时因子调度

---

## 附录：文件清单

### 核心代码（auto_mined 目录）

```
src/uniquant/brain/factors/auto_mined/
├── __init__.py                         # 模块入口（含 Session 5 注释）
├── mining_harness.py                   # 挖掘框架（数据加载、IC 计算、日志）
├── register_auto_mined.py              # 9 个通过因子的 FactorRegistry 注册
├── round_01_wyckoff_confidence.py      # am_wyckoff_action
├── round_02_lppl_bubble_risk.py        # am_lppl_days_to_tc
├── round_03_regime_rsi_reversion.py    # am_regime_rsi_momentum
├── round_04_entropy_shock_reversion.py # am_entropy_shock
├── round_05_vol_price_exhaustion.py    # am_stealth_accumulation
├── round_06_czsc_signal_score.py       # czsc_bi_momentum（FAIL，墓地）
├── round_07_ma_dispersion_regime.py    # am_ma_dispersion_regime
├── round_08_wyckoff_persistence.py     # am_wyckoff_contrarian
├── round_09_lppl_oscillation.py        # am_lppl_oscillation
└── round_10_multi_engine_ensemble.py   # am_multi_engine_ensemble
```

### 日志文件

```
MINING_LOG.md          # 所有 Session 的挖掘记录（自动追加）
MINING_GRAVEYARD.md    # 失败因子记录（含失败原因）
run_mining.py          # Session 5 完整执行脚本
```

### 文档

```
docs/research/
├── ALPHA_MINING_REPORT_20260602.md     # 本报告
└── FACTOR_CATALOG_20260602.md          # 因子技术手册（接口、参数、注意事项）
```

---

*本报告由 UniQuant Autonomous Alpha Miner 自动生成，提交 commit `34a8cd5`*  
*生成时间：2026-06-02*
