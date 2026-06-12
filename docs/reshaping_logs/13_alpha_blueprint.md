# 13 — Alpha 蓝图: 四大逻辑因子重构

> **日期**: 2026-06-09
> **状态**: 已部署已验证
> **前因**: 27 个 `am_` 系列因子 PBO=1.000 — 整个因子矿在 OOS 中完全失效

---

## 核心理念

> 丢弃纯数据挖掘, 回归金融逻辑。每个因子必须有可验证的**金融微观结构假设**, 能在经济直觉上解释为什么它应该在 OOS 中持续有效。

---

## 因子概览

| # | 因子 | 金融逻辑 | IC预期 | 数据需求 | 正交性 |
|---|------|---------|--------|---------|-------|
| 1 | ILLIQ | 流动性风险溢价 | + | close, amount | 高(与波动正交) |
| 2 | PV Divergence | 趋势衰竭反转 | - | close, volume | 高(与动量正交) |
| 3 | CS Momentum | 剥离反转的纯动量 | + | close | 部分(与动量20d相关) |
| 4 | Idiosyncratic Vol | 彩票需求效应 | + | close (市场收益) | 高(与市场beta正交) |

---

## 因子 1: ILLIQ (Amihud 非流动性)

### 金融微观结构假设

**Amihud (2002) "Illiquidity and Stock Returns"**:

- ILLIQ 度量**单位成交额(元)所需承受的价格冲击幅度**
- 流动性越差的股票, 投资者面临越高的**隐性交易成本**:
  - 大单进出产生显著价格滑点
  - 做市商要求更宽的买卖价差
  - 持仓周期被迫拉长(无法快速平仓)
- 跨市场证据: ILLIQ 越高的股票, 预期收益越高(**流动性风险溢价**)
- A股特有: 散户主导导致流动性分化严重, 部分小盘股流动性极差

### 公式

```
ILLIQ_t = mean(|r_i| / amount_i) over past 20 trading days
         × 1e9 (数值缩放)
```

其中:
- `r_i` = 第 i 日收益率
- `amount_i` = 第 i 日成交额(元)
- 使用 20 日滚动均值平滑日度噪音

### 实现

```python
returns = df["close"].pct_change().abs()
illiq = returns / df["amount"].replace(0, np.nan)
return illiq.rolling(window=20, min_periods=10).mean() * 1e9
```

### 预测方向

- **做多**: 高 ILLIQ (流动性差) → 高未来收益
- **做空**: 低 ILLIQ (流动性好) → 低未来收益
- **预期 IC**: **正值**

---

## 因子 2: 量价背离 (Price-Volume Divergence)

### 金融微观结构假设

**量价关系的微观基础**:

- **量在价先**: 成交量反映市场参与者的共识强度
- 当价格创新高时:
  - **放量突破** = 多方共识增强 → 趋势可持续
  - **缩量新高** = 买方力量衰竭 → 趋势不可持续, 反转在即
- 这是技术分析中"顶背离"的量化表达, 在 A 股散户情绪驱动行情中尤为显著
- 与行为金融学中"处置效应"一致: 投资者倾向于卖出盈利持仓, 缩量新高表明卖方压力即将释放

### 公式

```
close_pct_rank_20d = rolling percentile rank of close in last 20 days
vol_pct_rank_20d  = rolling percentile rank of volume in last 20 days
PV_divergence = vol_pct_rank - close_pct_rank
```

- `PV_divergence` **值低** (<0): 价升量缩, 趋势衰竭, 看空
- `PV_divergence` **值高** (>0): 价量齐升, 趋势健康, 看多

### 实现

```python
close_rank = df["close"].rolling(20).apply(
    lambda x: pd.Series(x).rank(pct=True).iloc[-1]
)
vol_rank = df["volume"].rolling(20).apply(
    lambda x: pd.Series(x).rank(pct=True).iloc[-1]
)
return vol_rank - close_rank
```

### 预测方向

- **做空**: PV_divergence 低 (价升量缩) → 反转下跌
- **做多**: PV_divergence 高 (价量齐升) → 趋势延续
- **预期 IC**: **正值**

---

## 因子 3: 横截面动量 (Cross-Sectional Momentum)

### 金融微观结构假设

**Jegadeesh & Titman (1993) + Jegadeesh (1990) 综合**:

- 文献发现两个不同时间尺度的收益预测性:
  - **中期动量** (3-12月): 过去涨的继续涨 — **信息渐近扩散**
  - **短期反转** (1-4周): 过去涨的会跌 — **做市商补偿 + 过度反应修正**
- 直接使用 20 日动量会混杂上述两种效应
- 通过 `r20d - r5d` **剥离短期反转**, 保留中期动量信号

### A股特色

- A 股短期反转效应非常强 (散户追涨杀跌后的获利回吐)
- 传统 20d 动量在 A 股 IC 经常为负 (短期反转主导)
- `r20d - r5d` 从 20 日收益中减去最近 5 日的收益, 聚焦于第 6-20 日的趋势

### 公式

```
CSMOM = r_20d - r_5d
      = (P0 / P_{-20} - 1) - (P0 / P_{-5} - 1)
      = P_{-5} / P_{-20} - 1  (可近似理解为第6到第20日的收益)
```

### 实现

```python
r20 = df["close"].pct_change(20)
r5  = df["close"].pct_change(5)
return r20 - r5
```

### 预测方向

- **做多**: CSMOM 高 (中期趋势向上)
- **做空**: CSMOM 低 (中期趋势向下)
- **预期 IC**: **正值** (A股中预期 IC 方向待验证)

---

## 因子 4: 特质波动率 (Idiosyncratic Volatility)

### 金融微观结构假设

**Ang, Hodrick, Xing & Zhang (2006) "The Cross-Section of Volatility and Expected Returns"**:

- 股票收益可以分解为: `r_i = β*r_m + ε` (CAPM 回归残差)
- 残差 ε 的波动率 = **特质波动率 (IVOL)**
- AHXZ 发现: **高 IVOL 股票 → 异常低的未来收益**
- **"彩票需求"解释**: 投资者偏好高 IVOL 股票(潜在的大收益可能),
  愿意支付更高价格, 导致这些股票初始定价过高 → 后续收益低迷
- 这是行为金融学"代表性偏差"和"小数定律"的体现

### A股验证

- A 股散户占比高,"彩票效应"更强
- 游资偏爱炒作小市值、高波动的"妖股"
- 这些股票往往在暴涨后暴跌, 做空高 IVOL 效果显著

### 简化实现

在没有全市场收益率序列时, 使用**滚动去趋势**近似特质波动:

```
ε_t = r_t - MA5(r)
IVOL = σ(ε) over 20 days × sqrt(252)
factor = -IVOL
```

### 实现

```python
returns = df["close"].pct_change()
local_trend = returns.rolling(window=5).mean()
residual = returns - local_trend
ivol = residual.rolling(window=20, min_periods=10).std() * np.sqrt(252)
return -ivol
```

### 预测方向

- **做多**: -IVOL 值高 (低特质波动)
- **做空**: -IVOL 值低 (高特质波动, 即"彩票股")
- **预期 IC**: **正值** (取负后, 高因子值=低IVOL=高未来收益)

---

## 代码变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| ❌ 删除 | `brain/factors/auto_mined/` | 27 个文件, 整目录物理火化 |
| ❌ 删除 | `brain/factors/__init__.py` | 移除 `import auto_mined` |
| ✅ 新增 | `brain/factors/custom_factors.py` | 4 个因子函数 + 注册 |
| ✅ 验证 | 全部通过 | 因子值计算正确, 注册成功 |

## 下一步

1. **[阶段2]**: 在真实 A 股 50 只活跃股票上计算 4 个因子的 IC/ICIR
2. **[阶段3]**: 通过 WalkForwardFactorPipeline 验证 PBO < 0.3
3. **[阶段4]**: 风险加权组合回测, 输出夏普比率和最大回撤

---

*生成时间: 2026-06-09 | 状态: 已部署, 待阶段2验证*
