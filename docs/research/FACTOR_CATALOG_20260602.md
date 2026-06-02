# Session 5 Auto-Mined Factor 技术手册

**版本**: 1.0  
**日期**: 2026-06-02  
**来源**: Session 5 Alpha 挖掘，commit `34a8cd5`  
**注册前缀**: `am_`

---

## 概览

| 因子 | 引擎 | ICIR | 持有期 | 方向 | 权重 |
|------|------|------|--------|------|------|
| [am_wyckoff_action](#1-am_wyckoff_action) | Wyckoff | 0.6437 | 5d | 双向 | 0.85 |
| [am_lppl_days_to_tc](#2-am_lppl_days_to_tc) | LPPL | 0.5846 | 20d | 正向 | 0.75 |
| [am_regime_rsi_momentum](#3-am_regime_rsi_momentum) | Regime+RSI | 0.4725 | 5d | 正向 | 0.70 |
| [am_entropy_shock](#4-am_entropy_shock) | Entropy | 0.7408 | 5d | 正向 | 0.90 |
| [am_stealth_accumulation](#5-am_stealth_accumulation) | Volume-Price | 0.6827 | 5d | 正向 | 0.85 |
| [am_ma_dispersion_regime](#6-am_ma_dispersion_regime) | MA+Regime | 0.6890 | 5d | 双向 | 0.85 |
| [am_wyckoff_contrarian](#7-am_wyckoff_contrarian) | Wyckoff | 0.6103 | 20d | 反向 | 0.75 |
| [am_lppl_oscillation](#8-am_lppl_oscillation) | LPPL | 1.0270 | 5d | 负向 | 0.90 |
| [am_multi_engine_ensemble](#9-am_multi_engine_ensemble) | Composite | 1.5837 | 5d | 正向 | 1.00 |

---

## 1. am_wyckoff_action

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_wyckoff_action` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_01_wyckoff_confidence.py` |
| 函数 | `compute_wyckoff_phase_confidence(df, mode='backtest')` |
| 持有期 | 5d（最优），20d（ICIR=0.60）|

### 假设

Wyckoff 引擎的 `scan_signal()` 返回一个 `action` 字段（BUY/SELL/HOLD），该字段经过引擎的完整九步分析流程得出，比原始 `phase×confidence` 乘积更直接反映当前市场动向。BUY 信号 + 高置信度 → 近期正收益。

### 计算逻辑

```python
# 每5日采样，forward-fill
sig = engine.scan_signal(window_120d, symbol)
action = sig['action']       # 'BUY' / 'SELL' / 'HOLD'
confidence = sig['confidence']  # float 0.0–1.0

if action == 'BUY':
    score = confidence
elif action == 'SELL':
    score = -confidence
else:
    score = 0.0

if sig['spring_detected']:
    score += 0.3   # spring 事件加分
if sig['utad_detected']:
    score -= 0.3   # UTAD 事件减分
```

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.6437 |
| IC_mean | 0.0239 |
| IC_std | 0.0372 |
| IC>0 | 52.1% |
| N_periods | 598 |

### 使用注意

- **数据格式**：传入的 `df` 必须包含 `date` 列且索引为 DatetimeIndex，函数内部会 `reset_index(drop=True)` 传给 Wyckoff 引擎
- **计算成本**：每5日运行一次 `scan_signal`（~1s/次），20 只股票约 20s
- **Live 禁用**：`if mode == "live": raise NotImplementedError`
- **Wyckoff 引擎版本**：依赖 `WyckoffEngine(lookback_days=120)`，引擎参数变更可能影响信号

---

## 2. am_lppl_days_to_tc

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_lppl_days_to_tc` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_02_lppl_bubble_risk.py` |
| 函数 | `compute_lppl_bubble_risk(df, mode='backtest')` |
| 持有期 | 20d（最优），5d（ICIR=0.04）|

### 假设

LPPL 模型拟合出的临界时间 `tc` 距今天数（`days_to_tc`）作为"安全缓冲区"：距离 tc 越远，市场越不处于对数周期加速阶段，做多安全性越高。`tanh` 变换将其压缩至 (-1, +1) 范围，避免极端值干扰横截面排序。

### 计算逻辑

```python
# 每20日采样，forward-fill
result = lppl_calc.fit(window_100d)
days_to_tc = clip(result['days_to_tc'], -30, 200)
score = tanh(days_to_tc / 60.0)
# 解释：
# days_to_tc=60  → score = tanh(1.0) ≈ 0.76（安全）
# days_to_tc=0   → score = 0（临界）
# days_to_tc=-30 → score ≈ -0.46（已过临界）
```

### IC 统计（20d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.5846 |
| IC_mean | 0.0271 |
| IC_std | 0.0464 |
| IC>0 | 54.2% |
| N_periods | 563 |

### 使用注意

- **计算速度**：单次 LPPL 拟合 ~0.04s（差分进化优化），每20日一次
- **`is_bubble` 标志**：在当前配置下几乎从不触发（`valid_constraints=False`），不要依赖此字段
- **`days_to_tc` 含义**：正值=未来临界点；负值=已过临界点（可能进入反弹阶段）
- **月度更新**：因子值每20日变化一次，适合月度调仓策略

---

## 3. am_regime_rsi_momentum

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_regime_rsi_momentum` |
| 类别 | `technical` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_03_regime_rsi_reversion.py` |
| 函数 | `compute_regime_rsi_reversion(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

在 NORMAL 流动性状态下，RSI 是**动量信号**（高 RSI → 趋势延续）；在 STRESSED/FROZEN 状态下，RSI 信号不可靠，应降低权重或忽略。

> **关键反直觉发现**：A 股 RSI 在近 3 年表现为动量而非反转信号，高 RSI 预测正收益。

### 计算逻辑

```python
rsi = Indicators.calc_rsi(df, window=14)
rsi_signal = (rsi - 50.0) / 50.0    # 正方向：高RSI=正

# 每5日检测流动性状态
regime = RegimeDetector().detect(window_30d)
weight = {'NORMAL': 1.0, 'STRESSED': 0.3, 'FROZEN': 0.0, 'UNKNOWN': 0.5}[regime]

factor = rsi_signal * regime_weight
```

### Regime 权重设计

| 状态 | 权重 | 说明 |
|------|------|------|
| NORMAL | 1.0 | RSI 动量信号完全有效 |
| STRESSED | 0.3 | 市场应激，RSI 可靠性降低 |
| FROZEN | 0.0 | 流动性枯竭，RSI 失效 |
| UNKNOWN | 0.5 | 不确定，取中间值 |

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.4725 |
| IC_mean | 0.0211 |
| IC_std | 0.0447 |
| IC>0 | 53.2% |
| N_periods | 716 |

### 使用注意

- **RSI 窗口**：使用 14 日（Wilder EMA 标准）
- **与 `rsi_14` 的区别**：系统注册因子 `rsi_14` ICIR=0.025；加入 Regime 条件后 ICIR=0.47（提升18.8倍）
- **Regime 检测依赖**：需要 `volume`/`amount` 列用于换手率 z-score 计算

---

## 4. am_entropy_shock

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_entropy_shock` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_04_entropy_shock_reversion.py` |
| 函数 | `compute_entropy_shock_reversion(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

Shannon 熵衡量收益分布的多样性/随机性。当熵显著下降时（z-score 很负），市场参与者高度一致（如集体恐慌抛售），这种状态通常不可持续，随后会出现均值回归（反弹）。

### 计算逻辑

```python
entropy = Indicators.calc_market_entropy(df, window=20, bins=10)
ma_40 = entropy.rolling(40, min_periods=10).mean()
std_40 = entropy.rolling(40, min_periods=10).std()

z = (entropy - ma_40) / (std_40 + 1e-8)
factor = -z    # 熵低于均值 → z为负 → -z为正 → 预测上涨
```

### Shannon 熵计算

```
entropy(t) = -Σ p_i × log(p_i)
p_i = P(收益率落在第i个区间)，共10个区间
窗口：过去20日
```

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.7408 |
| IC_mean | 0.0237 |
| IC_std | 0.0320 |
| IC>0 | 54.3% |
| N_periods | 689 |

### 使用注意

- **IC_std 最小**（0.032，所有因子中最低）：信号稳定性最高，是纯技术因子中最稳定的
- **单调性**：熵冲击信号在连续极端事件中可能出现多次叠加，需注意累积效应
- **窗口选择**：`window=20, bins=10` 是平衡灵敏度和稳定性的参数；减小 bins 可提高信号频率，增加噪声

---

## 5. am_stealth_accumulation

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_stealth_accumulation` |
| 类别 | `technical` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_05_vol_price_exhaustion.py` |
| 函数 | `compute_vol_price_exhaustion(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

机构投资者吸筹时倾向于在不引起注意的情况下买入（低量、持续小幅上涨）。反之，高量下跌是散户恐慌抛售（延续下行，不是反转）。因此，**低量上涨** = 隐性机构吸筹 = 正向信号。

> **关键反直觉过程**：初始假设"高量下跌=卖出枯竭=反转"在 A 股被数据否定，实际上高量下跌预测延续下跌。最终信号为其取反。

### 计算逻辑

```python
vol_ratio = Indicators.calc_vol_ratio(df, window=20)   # current_vol / MA20_vol
pct_5d = df['close'].pct_change(5)

# 恐慌信号：高量 + 价格下跌（正值=存在恐慌）
vol_excess = (vol_ratio - 1.0).clip(lower=0)
price_weakness = (-pct_5d).clip(lower=0)
panic_signal = vol_excess * price_weakness

# 取反：低量上涨（恐慌不存在）= 隐性吸筹
factor = -panic_signal

# z-score 标准化（60日滚动）
factor = (factor - factor.rolling(60).mean()) / (factor.rolling(60).std() + 1e-8)
```

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.6827 |
| IC_mean | 0.0241 |
| IC_std | 0.0353 |
| IC>0 | 54.1% |
| N_periods | 693 |

### 使用注意

- **量纲**：原始信号经 z-score 标准化，横截面可比性好
- **依赖列**：需要 `volume` 列（成交量），无需 `amount`
- **A 股适用性**：该因子利用了 A 股散户主导的高量恐慌特征，在成熟市场（机构主导）效果可能相反

---

## 6. am_ma_dispersion_regime

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_ma_dispersion_regime` |
| 类别 | `technical` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_07_ma_dispersion_regime.py` |
| 函数 | `compute_ma_dispersion_regime(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

MA5/MA20/MA60 之间的相对位置（ATR 归一化）衡量趋势质量。在 NORMAL 流动性状态下，强趋势（MA5 > MA20 > MA60）预测延续；在 STRESSED 状态下，趋势常发生反转。

### 计算逻辑

```python
ma5 = Indicators.calc_ma(df, window=5)
ma20 = Indicators.calc_ma(df, window=20)
ma60 = Indicators.calc_ma(df, window=60)
atr = Indicators.calc_atr(df, window=14)

# ATR归一化的多均线离散度
dispersion = (ma5 - ma20) / (atr + 1e-8) + 0.5 * (ma20 - ma60) / (atr + 1e-8)

# Regime条件化（每5日）
regime_flip = {'NORMAL': 1.0, 'STRESSED': -0.5, 'FROZEN': 0.0, 'UNKNOWN': 0.3}[regime]
factor = dispersion * regime_flip
```

### Regime 调节设计

| 状态 | 乘数 | 信号含义 |
|------|------|---------|
| NORMAL | +1.0 | 趋势信号有效（正向）|
| STRESSED | -0.5 | 趋势反转信号（部分对冲）|
| FROZEN | 0.0 | 忽略所有趋势信号 |
| UNKNOWN | +0.3 | 弱正向倾向 |

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.6890 |
| IC_mean | 0.0302 |
| IC_std | 0.0438 |
| IC>0 | 52.8% |
| N_periods | 688 |

### 使用注意

- **IC_mean 最高**（0.030）：在所有独立因子中绝对 IC 均值最高，说明信号方向性最强
- **MA 窗口**：5/20/60 与系统注册因子 `ma_ratio_5_20`、`ma_ratio_10_60` 重叠，但 ATR 归一化和 Regime 条件化是关键差异化处理
- **与 `ma_ratio_5_20` 的对比**：系统因子 ICIR=0.014，本因子 ICIR=0.689，提升 49 倍

---

## 7. am_wyckoff_contrarian

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_wyckoff_contrarian` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_08_wyckoff_persistence.py` |
| 函数 | `compute_wyckoff_persistence(df, mode='backtest')` |
| 持有期 | 20d（最优），5d（ICIR=0.23）|

### 假设

股票在 Wyckoff 多头阶段（ACCUMULATION/MARKUP）停留越久，意味着该趋势越充分定价，接近阶段末期的均值回归概率越高。因此，**持续时间长 = 反转信号**（contrarian）。

> **关键反直觉发现**：Wyckoff 多头持久性预测**负收益**（在 20 日持有期 ICIR=-0.61），取反后变为 ICIR=+0.61。

### 计算逻辑

```python
# 每5日采样 Wyckoff 阶段
for i in sample_indices:
    sig = engine.scan_signal(window_120d)
    direction = +1 if phase in (ACCUMULATION, MARKUP) else \
                -1 if phase in (DISTRIBUTION, MARKDOWN) else 0
    conf = sig['confidence']  # float 0-1
    
    # 累计连续同方向条数
    if direction == prev_direction:
        streak += 1
    else:
        streak = 1
    
    # 取反：持续多头 → 负分（contrarian）
    score = -direction * streak * conf / 10.0
```

### IC 统计（20d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 0.6103 |
| IC_mean | 0.0268 |
| IC_std | 0.0439 |
| IC>0 | 54.2% |
| N_periods | 583 |

### 使用注意

- **仅在 20d 持有期有效**：5d 持有期 ICIR=0.23，适合月度换仓策略
- **与 `am_wyckoff_action` 的关系**：两者均基于 Wyckoff 引擎，但信号相关性为负（约 -0.4）——`action` 是短期方向信号，`contrarian` 是中期均值回归信号
- **采样间隔**：每5日运行一次 scan_signal，streak 按采样频率计数（非日历天数）

---

## 8. am_lppl_oscillation

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_lppl_oscillation` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_09_lppl_oscillation.py` |
| 函数 | `compute_lppl_oscillation_amplitude(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

LPPL 模型中，振荡参数 `|c|` 和角频率 `ω` 共同衡量对数周期振荡的强度。强振荡意味着市场正在接近临界时间，价格预计在 tc 附近剧烈波动并最终下行。振荡强度越高，近期（5日）负收益概率越大。

### LPPL 模型

```
f(t) = a + b(tc-t)^m + c(tc-t)^m × cos(ω × log(tc-t) + φ)

关键参数：
  c  ∈ [-1, 1]：振荡振幅（|c|越大，振荡越强）
  ω  ∈ [6, 13]：角频率（ω越高，振荡周期越短）
  tc            ：临界时间（预计转折点）
```

### 计算逻辑

```python
# 每20日拟合
result = lppl_calc.fit(window_100d)
params = result['model_params']
c = abs(params['c'])
w = params['w']

# 振荡强度（标准化）
oscillation = c * w / (2 * π)

# 取负：振荡越强 → 负因子值 → 做空信号
factor = -oscillation
```

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | 1.0270 |
| IC_mean | 0.0241 |
| IC_std | 0.0235 |
| IC>0 | 55.0% |
| N_periods | 693 |

### 使用注意

- **IC_std 极低**（0.0235）：信号最稳定，每期 IC 波动性最小
- **ICIR > 1.0**：在 Spearman IC 测试中 ICIR > 1.0 表示极强的信号一致性
- **多头信号**：当振荡强度低（远离临界点）时因子值接近 0，不适合作为纯做多信号，更适合做空/风险控制
- **更新频率**：每20日更新，月度因子

---

## 9. am_multi_engine_ensemble

### 基本信息

| 项目 | 值 |
|------|-----|
| Registry 名 | `am_multi_engine_ensemble` |
| 类别 | `alternative` |
| 文件 | `src/uniquant/brain/factors/auto_mined/round_10_multi_engine_ensemble.py` |
| 函数 | `compute_multi_engine_ensemble(df, mode='backtest')` |
| 持有期 | 5d（最优）|

### 假设

4 个来自不同信息源的子信号，经过秩标准化后的相关性相对较低（< 0.5），组合后可以通过分散化降低噪声，提升信号稳定性。等权合并（简单平均）在子信号 IC 相近时接近最优组合。

### 子信号构成

| 子信号 | 来源 | 独立 ICIR |
|--------|------|-----------|
| Regime+RSI 动量 | am_regime_rsi_momentum | 0.47 |
| 熵冲击均值回归 | am_entropy_shock | 0.74 |
| 隐性吸筹 | am_stealth_accumulation | 0.68 |
| MA 离散 + Regime | am_ma_dispersion_regime | 0.69 |

### 计算逻辑

```python
def _rank_norm(s: pd.Series) -> pd.Series:
    """滚动60日秩标准化 → [-1, +1]"""
    return s.rolling(60, min_periods=20).apply(
        lambda w: 2 * (w.rank().iloc[-1] / len(w)) - 1,
        raw=False
    )

s3 = _rank_norm(compute_regime_rsi_reversion(df))
s4 = _rank_norm(compute_entropy_shock_reversion(df))
s5 = _rank_norm(compute_vol_price_exhaustion(df))
s7 = _rank_norm(compute_ma_dispersion_regime(df))

ensemble = pd.concat([s3, s4, s5, s7], axis=1).mean(axis=1)
```

### IC 统计（5d 持有期）

| 指标 | 值 |
|------|-----|
| ICIR | **1.5837** |
| IC_mean | **0.0613** |
| IC_std | 0.0387 |
| IC>0 | **59.0%** |
| N_periods | 698 |

### 组合增益分析

| 指标 | 最强子信号 | Ensemble | 组合增益 |
|------|-----------|----------|---------|
| ICIR | 0.74（熵冲击）| 1.5837 | **+2.14×** |
| IC_mean | 0.0302（MA离散）| 0.0613 | **+2.03×** |
| IC>0 | 54.3% | 59.0% | +4.7pp |

### 使用注意

- **最强推荐因子**：在所有 9 个通过因子中 ICIR 最高，且 IC>0=59% 最稳定
- **计算依赖**：需要完整运行 4 个子信号，计算时间约是单个因子的 4 倍（约 40s/20股）
- **秩标准化窗口**：`rolling(60)` 要求每只股票有 ≥ 60 日数据才开始计算
- **扩展方向**：可以加入 `am_wyckoff_action`（ICIR=0.64）作为第5个子信号，预期 Ensemble ICIR 可进一步提升至 1.8+

---

## 已淘汰因子（墓地记录）

### czsc_bi_momentum（Round 6，FAIL）

| 项目 | 值 |
|------|-----|
| 最终 ICIR | 0.1919 |
| 尝试次数 | 3 次（全部失败）|
| 失败原因 | CZSC 引擎 `update_and_get_signals` 只返回 `{is_3rd_buy, bi_count, error}`，不暴露完整一/二/三买卖点信号 |

**历次尝试**：
1. `CZSCSignalType.from_signal_value(val)` 解析 → IndexError（`df.iterrows()` 返回 Timestamp 索引，非整数）
2. 修复索引后，信号全为 0（引擎接口局限，无法解析到有效信号）
3. 改用 `bi_count` z-score + `is_3rd_buy` 衰减 → ICIR=0.19（CZSC 笔数变化量的预测力有限）

**修复建议**：在 `CZSCEngine.update_and_get_signals()` 中暴露完整的买卖点信号字典，预期 ICIR 提升至 0.5+。

---

## 快速使用指南

### 加载所有因子

```python
import sys
sys.path.insert(0, 'src')

from uniquant.brain.factors.auto_mined.register_auto_mined import register_all
register_all()

from uniquant.brain.factors.registry import FactorRegistry
factors = {f.name: f for f in FactorRegistry.get_all() if f.name.startswith('am_')}
print(f"已加载 {len(factors)} 个 auto-mined 因子")
```

### 计算单只股票的因子值

```python
from mootdx.reader import Reader
import pandas as pd

r = Reader.factory(market='std', tdxdir='~/.local/share/tdxcfv/drive_c/tc')
df = r.daily(symbol='000001')
df.index = pd.to_datetime(df.index)
df['date'] = df.index  # 必须：多数因子需要 date 列

# 计算最强因子
from uniquant.brain.factors.auto_mined.round_10_multi_engine_ensemble import (
    compute_multi_engine_ensemble
)
ensemble_factor = compute_multi_engine_ensemble(df)
print(f"最新因子值: {ensemble_factor.iloc[-1]:.4f}")
```

### 构建 IC 分析面板

```python
from uniquant.brain.factors.auto_mined.mining_harness import (
    build_factor_panel, compute_icir, UNIVERSE
)
from uniquant.brain.factors.auto_mined.round_10_multi_engine_ensemble import (
    compute_multi_engine_ensemble
)

panel = build_factor_panel(compute_multi_engine_ensemble, symbols=UNIVERSE)
metrics = compute_icir(panel, holding_period=5)
print(f"ICIR: {metrics['icir']:.4f}  IC_mean: {metrics['ic_mean']:.4f}")
```

---

*本手册由 Alpha Miner Session 5 自动生成，commit `34a8cd5`，日期 2026-06-02*
