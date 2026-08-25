# 逻辑驱动因子方向族 — 文献调研与设计方案

> **生成**: 2026-08-19
> **背景**: P1 基线确认 13 个既有因子仅 2 个正 OOS IC（`idiosyncratic_vol_20d +0.075`、`illiq_20d +0.070`），P2 GP 挖掘 0/25 幸存 — 纯数据挖掘在 A 股行不通，须转向有金融学理论支撑的**逻辑驱动因子**。
> **前置文档**: `results/factor_mining/baseline_walkforward_sample500_oos.json`、`results/factor_mining/gp_mining.json`

---

## 目录

1. [总体方法论](#1-总体方法论)
2. [方向 A: Amihud 流动性溢价族](#2-方向-a-amihud-流动性溢价族)
3. [方向 B: 反彩票/低波动异象族](#3-方向-b-反彩票低波动异象族)
4. [方向 C: 反转与尾部风险族](#4-方向-c-反转与尾部风险族)
5. [因子间相关性预估](#5-因子间相关性预估)
6. [测试方案](#6-测试方案)
7. [风险与局限](#7-风险与局限)

---

## 1. 总体方法论

### 1.1 选择标准

| 维度 | 要求 |
|---|---|
| **理论依据** | 有金融学第一性原理（风险补偿/行为偏差/市场摩擦） |
| **可复现性** | 仅用 OHLCV + amount + volume（当前数据湖中可用字段） |
| **因果性** | 仅用过去信息（天然 trailing window，无 lookahead） |
| **与基线正因子正交性** | 与 `idiosyncratic_vol_20d`/`illiq_20d` 的横截面 \|corr\| < 0.7 |
| **A 股适应性** | 不依赖融券卖空、T+0、衍生品 |

### 1.2 候选因子管线

```
理论 → 因子公式 → 实现 → 单因子 Walk-Forward → 四重门
                                            ├─ IC > 0 (正方向)
                                            ├─ ICIR > 0.5
                                            ├─ PBO < 0.2
                                            └─ 多样门 |corr| < 0.7
```

### 1.3 数据面

与 P1 基线完全一致：500 只 seed=42、as-of 2026-05-29、lookback 1600 交易日、504/63 窗 Walk-Forward。

---

## 2. 方向 A: Amihud 流动性溢价族

### 2.1 理论基础

**Amihud (2002)** "Illiquidity and Stock Returns: Cross-Section and Time-Series Effects", *Journal of Financial Markets*。

核心思想：非流动性是股票的一项风险特征。投资者要求**流动性溢价**来补偿难以快速低成本变现的风险。Amihud 指标定义为：

```
ILLIQ_d = |r_d| / amount_d
```

即**每单位成交额带来的价格冲击**。ILLIQ 越高 = 流动性越差 = 预期收益越高。

**A 股实证**：已有 `illiq_20d +0.070` 为 P1 基线中仅有的两个正因子之一，说明流动性溢价在 A 股成立。但基础版本是最简单的 20d 均值，窗口和变换可能改进。

### 2.2 候选因子

#### A-1: `illiq_10d`

| 项目 | 内容 |
|---|---|
| 公式 | `mean(|r|/amount, 10d, min_periods=5) × 1e9` |
| 预期方向 | +（高非流动性 = 高收益） |
| 与已有差异 | 更短窗口，对流动性突变更敏感 |
| 理论支持 | 流动性冲击在短期更显著（Acharya & Pedersen 2005） |
| 风险 | 噪音更高，IC 可能不稳定 |

#### A-2: `illiq_60d`

| 项目 | 内容 |
|---|---|
| 公式 | `mean(|r|/amount, 60d, min_periods=30) × 1e9` |
| 预期方向 | + |
| 与已有差异 | 更长窗口，更稳定 |
| 理论支持 | 流动性溢价是长期风险补偿，长窗更精确 |
| 风险 | 变化缓慢，对短期风格切换不敏感 |

#### A-3: `amivest_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `mean(amount / |r|, 20d, min_periods=10)` |
| 预期方向 | −（高 Amivest = 高流动性 = 低收益） |
| 与已有差异 | Amivest 与 Amihud 反号，概念上更直观（"流动性"而非"非流动性"） |
| 理论支持 | Amivest (1970s) 为最早流动性指标之一，在 A 股有独立预测力 |
| 风险 | 当 |r| → 0 时 Amivest → ∞，须截断 |

#### A-4: `illiq_sqrt_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `sqrt(mean(|r|/amount, 20d, min_periods=10) × 1e9)` |
| 预期方向 | + |
| 与已有差异 | sqrt 变换削减极端值（Amihud 分布右偏严重） |
| 理论支持 | 对数/平方根变换在截面回归中更稳健 |
| 风险 | 非线性变换可能弱化信号 |

#### A-5: `dollar_volume_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `mean(amount, 20d, min_periods=10)` |
| 预期方向 | −（高成交额 = 高流动性 = 低收益） |
| 与已有差异 | 纯美元成交额，不涉及收益率，是最简单的流动性代理 |
| 理论支持 | 流动性水平（而非价格冲击）也有独立预测力 |
| 风险 | 与市值高度相关，可能只是市值因子的代理 |

### 2.3 方向 A 总评

| 因子 | 预期 IC 方向 | 与 `illiq_20d` 相关度 | 增量价值 | 优先级 |
|---|---|---|---|---|
| `illiq_10d` | + | 高 (~0.85) | 低（短窗补充） | ★★★ |
| `illiq_60d` | + | 高 (~0.80) | 中（跨期稳定性） | ★★★ |
| `amivest_20d` | − | 中 (~0.6) | **高**（新信息维度） | ★★★★★ |
| `illiq_sqrt_20d` | + | 极高 (~0.95) | 低（几乎等价） | ★★ |
| `dollar_volume_20d` | − | 中 (~0.5) | **高**（新维度但需排除市值代理） | ★★★★ |

---

## 3. 方向 B: 反彩票/低波动异象族

### 3.1 理论基础

**Ang, Hodrick, Xing & Zhang (2006)** "The Cross-Section of Volatility and Expected Returns", *Journal of Finance*。发现**高特质波动股票未来收益低**（IVOL 异象）。同年 **Ang et al. (2009)** 在国际市场验证。

**Bali, Cakici & Whitelaw (2011)** "Maxing Out: Stocks as Lotteries and the Cross-Section of Expected Returns", *Journal of Financial Economics*。发现过去一个月**最大日收益（MAX）最高**的股票未来收益最低。解释：投资者有**彩票偏好**（overweight 小概率大收益），对彩票型股票过度需求推高当前价格，导致未来低收益。

**Kumar (2009)** "Hard-to-Value Stocks, Behavioral Biases, and Stock Returns" — 偏度也是彩票偏好的代理变量。

**A 股实证**：`idiosyncratic_vol_20d +0.075` 为 P1 基线最正因子，说明反彩票效应在 A 股成立。

### 3.2 候选因子

#### B-1: `max_ret_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `max(weekly_ret, 20d)` — 过去 20 日最大日收益率（原 Bali et al. 用月最大日收益） |
| 预期方向 | −（高 MAX = 彩票偏好 = 未来低收益） |
| 与已有差异 | 全新因子，与 `idiosyncratic_vol_20d` 相关但不同（MAX 捕捉极端右尾，IVOL 捕捉整体波动） |
| 文献证据 | 美国市场 MAX 因子独立于 IVOL（Bali et al. 2011 Table 6）；A 股也有实证（Carpenter et al. 2021） |
| 优先级 | ★★★★★ |

#### B-2: `skew_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `skew(daily_ret, 20d)` — 日收益率偏度 |
| 预期方向 | −（高正偏度 = 彩票偏好 = 未来低收益） |
| 与已有差异 | 偏度与 MAX 相关但不同（偏度度量整个分布不对称，MAX 只关注尾端） |
| 文献支持 | 偏度在 A 股有独立预测力（Zhong & Wan 2020） |
| 风险 | 20d 窗口短，偏度估计噪音大 |
| 优先级 | ★★★★ |

#### B-3: `cvar_95_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `mean(ret[ret < percentile(ret, 5)], 20d)` — 5% 条件 VaR（左尾预期损失） |
| 预期方向 | +（高尾部风险 = 风险补偿溢价） |
| 与已有差异 | 与 IVOL 不同（IVOL 度量整体波动，CVaR 只关注左尾极端损失） |
| 文献支持 | 左尾风险在截面有正溢价（Kelly & Jiang 2014, Atilgan et al. 2020） |
| 风险 | 20d 窗口短，尾部估计极不稳定 |
| 优先级 | ★★★ |

#### B-4: `idiosyncratic_vol_60d`

| 项目 | 内容 |
|---|---|
| 公式 | `−1 × 20d std of (ret − 10d rolling mean of ret) × √252`（与已有 `idiosyncratic_vol_20d` 同公式但换 60d 窗口） |
| 预期方向 | +（高 IVOL = 低收益，因子值 = −IVOL，所以高因子值 = 高收益） |
| 与已有差异 | 长窗口 IVOL 可能更稳定 |
| 优先级 | ★★★ |

#### B-5: `range_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `(max(high, 20d) − min(low, 20d)) / close` — 20d 价格区间比 |
| 预期方向 | +（高波动 = 正溢价） |
| 与已有差异 | 用 H/L 替代收益 std，对极端值更稳健 |
| 文献支持 | 波动率有正溢价（Ang et al. 2006 的镜像） |
| 优先级 | ★★★★ |

### 3.3 方向 B 总评

| 因子 | 预期 IC 方向 | 与 `idiosyncratic_vol_20d` 相关度 | 增量价值 | 优先级 |
|---|---|---|---|---|
| `max_ret_20d` | − | 中 (~0.5) | **高**（独立维度） | ★★★★★ |
| `skew_20d` | − | 中 (~0.4) | 中 | ★★★★ |
| `cvar_95_20d` | + | 中 (~0.5) | 中（理论明确但估计不稳） | ★★★ |
| `idiosyncratic_vol_60d` | + | 极高 (~0.9) | 低 | ★★★ |
| `range_20d` | + | 高 (~0.7) | 中（稳健性改善） | ★★★★ |

---

## 4. 方向 C: 反转与尾部风险族

### 4.1 理论基础

**Jegadeesh (1990)** "Evidence of Predictable Behavior of Security Returns", *Journal of Finance*。发现**1 月/1 周反转效应**：短期过去赢家未来跑输。

**De Bondt & Thaler (1985)** "Does the Stock Market Overreact?", *Journal of Finance*。发现**3-5 年长期反转**：过去 3-5 年输家未来 3-5 年跑赢赢家。

**A 股特殊性**：与美国市场不同，A 股**短期反转更显著**（个人投资者占比高、追涨杀跌行为更突出），而**动量效应不显著**（这与 P1 基线一致：`momentum_20d -0.062`、`momentum_60d -0.070` 均为负，说明 A 股实际上有反转而非动量）。

### 4.2 候选因子

#### C-1: `reversal_1d`

| 项目 | 内容 |
|---|---|
| 公式 | `−1 × ret_1d` — 昨日收益率的负值 |
| 预期方向 | +（买跌卖涨，昨日跌 = 今日涨） |
| 与已有差异 | 全新。P1 基线无日度反转因子 |
| 文献支持 | 1 日反转在 A 股极为显著（个人投资者过度反应后修正） |
| 风险 | 超高换手率、交易成本可能吞噬收益 |
| 优先级 | ★★★★★ |

#### C-2: `reversal_5d`

| 项目 | 内容 |
|---|---|
| 公式 | `−1 × ret_5d` — 过去 5 日收益率的负值 |
| 预期方向 | + |
| 与已有差异 | 与 `momentum_20d` 逻辑相反（动量 = 正系数，反转 = 负系数） |
| 文献支持 | 周度反转在 A 股显著（与个人投资者追涨杀跌一致） |
| 优先级 | ★★★★ |

#### C-3: `reversal_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `−1 × ret_20d` |
| 预期方向 | + |
| 与已有差异 | 与 `momentum_20d` 完全相反方向，但 P1 基线中 `momentum_20d` 的 OOS IC 为 **−0.062**，说明实际上 20d 反转成立 |
| 优先级 | ★★★★（验证性：P1 已暗示其存在） |

#### C-4: `max_drawdown_20d`

| 项目 | 内容 |
|---|---|
| 公式 | `max_drawdown(close, 20d)` — 过去 20 日最大回撤（从峰值到谷值的最大跌幅） |
| 预期方向 | +（高风险 = 补偿溢价） |
| 与已有差异 | 与波动率不同（回撤度量路径依赖的下行风险） |
| 文献支持 | 最大回撤在截面有预测力（Bali et al. 2020） |
| 优先级 | ★★★ |

### 4.3 方向 C 总评

| 因子 | 预期 IC 方向 | 与已有因子相关度 | 增量价值 | 优先级 |
|---|---|---|---|---|
| `reversal_1d` | + | 低 | **高**（全新维度） | ★★★★★ |
| `reversal_5d` | + | 低~中 | 中 | ★★★★ |
| `reversal_20d` | + | 高（与动量反号） | 验证性 | ★★★★ |
| `max_drawdown_20d` | + | 中 | 中 | ★★★ |

---

## 5. 因子间相关性预估

```
                        illiq  idio  max  skew  rev1  rev5  rev20  amivest  range
illiq_20d              1.00  0.25  0.10  0.05  0.05  0.10  0.20   0.60    0.20
idiosyncratic_vol_20d  0.25  1.00  0.50  0.40  0.20  0.30  0.40   0.10    0.70
max_ret_20d            0.10  0.50  1.00  0.60  0.30  0.40  0.50   0.05    0.30
skew_20d               0.05  0.40  0.60  1.00  0.10  0.15  0.20   0.05    0.20
reversal_1d            0.05  0.20  0.30  0.10  1.00  0.50  0.30   0.05    0.10
reversal_5d            0.10  0.30  0.40  0.15  0.50  1.00  0.60   0.05    0.15
reversal_20d           0.20  0.40  0.50  0.20  0.30  0.60  1.00   0.10    0.25
amivest_20d            0.60  0.10  0.05  0.05  0.05  0.05  0.10   1.00    0.10
range_20d              0.20  0.70  0.30  0.20  0.10  0.15  0.25   0.10    1.00
```

关键观察：
- **A 方向内**：`illiq_*` 之间高度相关（~0.8-0.95），`amivest_20d` 与 `illiq_20d` 中度相关（~0.6），提供新信息
- **B 方向内**：`max_ret_20d` 与 `idiosyncratic_vol_20d` 中度相关（~0.5），`skew_20d` 更低（~0.4），彼此不冗余
- **C 方向内**：反转因子之间高度相关（~0.5-0.6），但 1d/5d/20d 各有不同频率
- **跨方向**：A 与 B 之间基本正交（~0.1-0.25），C 与 A/B 也低相关（~0.05-0.3）—— 三个方向提供**正交的 alpha 源**

---

## 6. 测试方案

### 6.1 优先级排序

| 优先级 | 因子 | 理由 |
|---|---|---|
| **P0** | `max_ret_20d` | 理论最坚实、增量最大、与已有因子正交性最好 |
| **P0** | `reversal_1d` | 全新维度、A 股特殊性最强、预期 IC 最显著 |
| **P0** | `amivest_20d` | 流动性新维度、与 `illiq_20d` 互补 |
| P1 | `range_20d` | 稳健波动率代理 |
| P1 | `skew_20d` | 彩票偏好第二维度 |
| P1 | `reversal_5d` | 反转频率补充 |
| P1 | `reversal_20d` | 验证 P1 基线暗示 |
| P2 | `illiq_10d` / `illiq_60d` | 已有因子微调 |
| P2 | `cvar_95_20d` | 尾部风险理论明确但估计不稳 |
| P2 | `max_drawdown_20d` | 增量有限 |
| P3 | `illiq_sqrt_20d` / `idiosyncratic_vol_60d` | 几乎等价于已有因子 |

### 6.2 实施步骤

**Phase 1: 实现 P0 因子（3 个）**
1. `max_ret_20d` — `df["close"].pct_change() per code → rolling(20).max()`
2. `reversal_1d` — `−1 × df["close"].pct_change(1)`
3. `amivest_20d` — `rolling(20).apply(mean(amount / |r|))`，截断 |r| < 0.0001 防除零

**Phase 2: 单因子 Walk-Forward 测试**
- 复用 `scripts/factor_mining/run_walk_forward_baseline.py` 架构
- 每次只测一个因子（避免 composer 正交化干扰）
- 输出：每因子每窗 OOS IC、ICIR、PBO、动量残差化 IC

**Phase 3: 组合测试**
- 将 P0 通过的因子（IC > 0 且 ICIR > 0.5）与基线正因子组合
- 测试 composite OOS IC 是否超单纯基线
- 测试 IC 加权 vs 等权

**Phase 4: 扩展测试**
- P1 因子实现 + 测试
- 全通过因子组合的 Walk-Forward 完整管线

### 6.3 验收标准

| 门 | 标准 |
|---|---|
| **IC 正方向** | OOS IC > 0（与理论预期方向一致） |
| **ICIR 门槛** | OOS ICIR > 0.5 |
| **PBO** | < 0.2（块 Bootstrap，2000 次） |
| **动量残差** | 控 20d 动量后残差 IC > 0 且 ≥2/3 窗正 |
| **多样性** | 与基线正因子 \|corr\| < 0.7 |
| **组合增量** | 添加后 composite OOS IC 超过基线 composite |

---

## 7. 风险与局限

### 7.1 已知风险

1. **财务数据缺失**：`data/lake/financial/` 为空，无法使用 PE/PB/ROE、应计利润、资产增长率等基本面因子。一旦财务数据到位，可扩展方向：
   - 盈利因子（Fama-French RMW）：高 ROE 股票跑赢低 ROE
   - 投资因子（Fama-French CMA）：低投资率股票跑赢高投资率
   - 质量因子（Asness et al. 2019）：综合质量

2. **换手率缺失**：`turnover` 列不可用（`turnover_momentum_20d` 目前返回全 NaN），因此无法计算换手率因子。如未来 `circulating_market_cap` 到位，可从 `amount / circulating_market_cap` 推算。

3. **反转因子交易成本**：`reversal_1d` 换手率极高（每天调仓），在 A 股万二印花税 + 万三佣金下可能收益被吞噬。需要在回测中扣除交易成本做净收益分析。

4. **MAX 效应在 A 股的局限性**：A 股涨跌停制度压低了极端日收益，可能削弱 MAX 效应。但 20cm 涨跌幅（科创板/创业板）股票可能仍有显著 MAX 效应。

5. **多因子共线性**：IC 加权组合中，如果多个因子同时"失效"（IC 同时翻负），组合会受冲击。需要关注因子间的条件相关性。

### 7.2 与 P1/P2 结论的衔接

- 如果 P0 因子中有多个通过验收，则**逻辑驱动因子**路线被验证为 A 股有效方向，可继续扩展
- 如果全部不通过，则 A 股截面预测力被进一步证伪，与 Wyckoff 研究结论完全一致——此时应考虑放弃横截面选股，转向**择时/资产配置**路线
- 本研究的所有代码和结论将与 P1 基线、P2 GP 挖掘一样，完全可复现、可证伪

---

## 参考文献

1. Amihud, Y. (2002). Illiquidity and stock returns: cross-section and time-series effects. *Journal of Financial Markets*, 5(1), 31-56.
2. Acharya, V. V., & Pedersen, L. H. (2005). Asset pricing with liquidity risk. *Journal of Financial Economics*, 77(2), 375-410.
3. Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2006). The cross-section of volatility and expected returns. *Journal of Finance*, 61(1), 259-299.
4. Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2009). High idiosyncratic volatility and low returns: International and further US evidence. *Journal of Financial Economics*, 91(1), 1-23.
5. Bali, T. G., Cakici, N., & Whitelaw, R. F. (2011). Maxing out: Stocks as lotteries and the cross-section of expected returns. *Journal of Financial Economics*, 99(2), 427-446.
6. Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. *Journal of Finance*, 45(3), 881-898.
7. De Bondt, W. F. M., & Thaler, R. (1985). Does the stock market overreact? *Journal of Finance*, 40(3), 793-805.
8. Kumar, A. (2009). Hard-to-value stocks, behavioral biases, and stock returns. *Journal of Financial and Quantitative Analysis*, 44(6), 1375-1401.
9. Kelly, B., & Jiang, H. (2014). Tail risk and asset prices. *Review of Financial Studies*, 27(10), 2841-2871.
10. Carpenter, J. N., Lu, F., & Whitelaw, R. F. (2021). The real value of China's stock market. *Journal of Financial Economics*, 139(3), 679-706.