# 基于本地日线的完整威科夫分析实践路线图

> 前提条件：仅有本地 A 股日线 OHLCV Parquet 数据 + Python 运行环境
>
> 目标：用代码实现"完整威科夫分析"——涵盖全部 7 个标志性事件、多周期相位共振、事件序列评分
>
> 基于 UniQuant 现有代码的升级路径

---

## 一、可行性判断

### 仅用日线能否做完整威科夫？

| 威科夫组件 | 是否需要周/月线？ | 能否用日线近似？ | 实现难度 |
|-----------|-----------------|----------------|---------|
| 月线相位判断 | ❌ 需要 12 根月线 | ✅ 需合成月线 | 低 |
| 周线趋势确认 | ❌ 需要周线 | ✅ 需合成周线 | 低 |
| PS/SC/AR/ST 检测 | ✅ 日线即可 | ✅ | 中 |
| **Spring 检测** | ✅ **日线即可** | ✅ **已实现** | — |
| SOS/LPS 检测 | ⚠️ 需周线确认背景 | ✅ 日线可检测局部特征 | 中 |
| JAC（突破） | ⚠️ 需周线确认 | ✅ 日线可检测 | 中-低 |
| 多周期共振 | ⚠️ 本质需要三周期 | ✅ 日线合成周/月线 | 中 |
| 点数图（P&F） | ✅ 日线即可 | ✅ | **高** |

**结论：用日线合成周线/月线，可以实现 90% 以上的威科夫分析功能。** P&F 点数图需要额外的网格算法，但同样基于日线 OHLC。

---

## 二、现有基础（可直接复用的代码）

### 已实现且可用的模块

```
src/uniquant/brain/wyckoff/
├── engine.py          — Spring 检测（1512行，已修复阈值参数化）
│   ├── BC/SC 检测（带 sigmoid 评分，L1317-1378）
│   ├── Spring 检测（核心，L417-459）
│   └── 置信度评分（A/B+/C/D, L835-899）
├── classifiers.py     — Type 1/2/3 量能分类（301行）
├── monthly_classifier.py — 月线相位分类（91行）
├── models.py          — 数据结构定义（818行）
├── rules.py           — 七大量价规则（378行）
├── config.py          — 参数配置（181行）
└── state.py           — 状态管理（295行）

scripts/wyckoff_multitf/
├── runner_v4.py       — 数据加载 + 多周期合成 + 事件研究框架（343行）
├── strategy_v4.py     — 策略回测框架（305行，已修复 bug）
└── verify_all.py      — 验证框架（383行）
```

### 关键已实现功能点

| 功能 | 位置 | 现有程度 |
|------|------|---------|
| 日线→月线合成 | runner_v4.py:87-93 | ✅ `groupby('M')` + OHLCV agg |
| 日线→周线合成 | runner_v4.py:81-86 | ✅ `dt.isocalendar()` week agg |
| BC 检测（Buying Climax） | engine.py:1317-1362 | ✅ 向量化评分 + sigmoid 置信度 |
| SC 检测（Selling Climax） | engine.py:1328-1376 | ✅ 向量化评分 + sigmoid 置信度 |
| Spring 检测 | engine.py:417-459 | ✅ 含下影线、量能、反弹确认 |
| 置信度评分 | engine.py:835-899 | ✅ A/B+/C/D + counterfactual |
| 月线相位 | monthly_classifier.py:24-65 | ✅ 基于统计阈值的规则法 |
| 量能分类 | classifiers.py:40-45 | ✅ Type1/2/3 相对量能 |
| 相对强度 | runner_v4.py:191-195 | ✅ 截面中位数 |
| 前向收益计算 | runner_v4.py:153-155 | ✅ 1/3/6 月前向 |
| 止损/止盈/持有期 | strategy_v4.py:78-255 | ✅ 固定参数 |

---

## 三、需要新建的模块

### 模块架构图

```
wyckoff_analysis/
├── phase.py                  # Phase I: 多周期相位分析（已部分实现）
│   ├── MonthlyPhaseAnalyzer    # 月线相位（复用 monthly_classifier.py）
│   ├── WeeklyPhaseAnalyzer     # 新增：周线相位
│   └── DailyPhaseAnalyzer      # 新增：日线相位（短期趋势）
│
├── events.py                 # Phase II: 完整事件检测（核心新开发）
│   ├── detect_ps()             # 初次支撑 Preliminary Support
│   ├── detect_sc()             # 恐慌抛售 Selling Climax（复用engine SC）
│   ├── detect_ar()             # 自动反弹 Automatic Reaction
│   ├── detect_st()             # 二次测试 Secondary Test
│   ├── detect_spring()         # Spring（复用engine）
│   ├── detect_sos()            # 强势信号 Sign of Strength
│   ├── detect_lps()            # 最后支撑点 Last Point of Support
│   └── detect_jac()            # 跨越溪流 Jump Across Creek
│
├── sequence.py               # Phase III: 事件序列评分
│   ├── EventSequence            # 事件时序管理
│   ├── WSOScorer                # 加权评分振荡器（≈设计文档WSO）
│   └── WSSScorer                # 马尔可夫链统计评分（≈设计文档WSS）
│
├── resonance.py              # Phase IV: 多周期共振过滤
│   └── ResonanceFilter          # 三周期信号确认引擎
│
└── strategy.py               # Phase V: 完整策略引擎
    └── WyckoffStrategy           # 综合交易决策
```

---

## 四、分阶段实施计划

### Phase I（1-2 天）：完善三周期相位分析

#### 目标
让每一根日线都携带其"当前所属"的月线相位、周线相位、日线相位。

#### 技术方案

```python
# 1️⃣ 月线相位（已有） — 每根日线匹配其所属月份的最后12根月线
def get_monthly_phase(daily_data, cutoff_idx):
    """
    输入：全部日线 + 当前索引位置
    输出：当前日线的月线相位标签
    
    注意：必须只使用 cutoff_idx 之前的数据
    """
    df_up_to_cutoff = daily_data.iloc[:cutoff_idx+1]
    # 合成月线（只到当前月）
    monthly = df_up_to_cutoff.resample('ME', closed='right', label='right').agg(...)
    # 取最后12根月线
    m12 = monthly.iloc[-12:]
    # 复用 classify_monthly_phase()
    return classify_monthly_phase(m12)


# 2️⃣ 周线相位（新增） — 基于12根周线的短期趋势
def get_weekly_phase(daily_data, cutoff_idx):
    """
    周线相位分类逻辑（参考月线但使用周线特定阈值）:
      - markdown: 周线趋势 < -5% OR 价格在底部 30%
      - accumulation: 价格在底部 40% + 量缩 + 窄幅
      - markup: 趋势 > +5% + 价格中上
      - distribution: 顶部 + 量价背离
      - unknown: 其他
    """
    # 合成周线（到当前周）
    weekly = daily_data.iloc[:cutoff_idx+1].resample('W', ...).agg(...)
    w12 = weekly.iloc[-12:]
    # 简化版相位判定
    return classify_weekly_phase(w12)  # 阈值缩放到周线级别


# 3️⃣ 日线相位（新增） — 30-60天的短期趋势判断
def get_daily_phase(daily_data, cutoff_idx):
    """
    日线短期趋势:
      - markdown: 20日均线向下 + 价格在均线下
      - accumulation: 价格横盘 + 量缩
      - markup: 20日线向上 + 价格在均线上
      - distribution: 顶部宽幅震荡 + 量缩价滞
    """
    window = daily_data.iloc[cutoff_idx-60:cutoff_idx+1]
    return classify_daily_phase(window)
```

#### 关键难点
- **前视偏差**：必须严格使用 `iloc[:cutoff_idx+1]`，禁止使用未来数据
- **不完整周期**：当前周的周线是不完整的（只有周一到当天的数据），合成时必须只聚合已有数据
- **阈值缩放**：月线的 range=80% 阈值不能直接用在周线上。合理的周线阈值需要统计分析

#### 输出
```
每根日线携带:
  {date, open, high, low, close, volume,
   monthly_phase, weekly_phase, daily_phase,  ← 新增
   phase_resonance}                             ← 三周期是否共振
```

#### 验证方法
- 在 v4 数据上回验：确保三周期相位逻辑合理（如 2020-03 疫情底 = 日线/周线/月线全部 markdown）
- 统计三周期共振率（预期 ~30-40%）

---

### Phase II（3-5 天）：完整事件序列检测

#### 目标
在任意截止时间点，检测过去 60-120 天内发生的全部威科夫事件（PS→SC→AR→ST→Spring→SOS→LPS→JAC）。

#### 检测逻辑

```python
def detect_events(daily_window):
    """
    输入：60-120 天的日线窗口（截止于当前日期）
    输出：事件列表 [{type, date, price, confidence, volume_type}, ...]
    
    返回的事件按时间排序，可能有 0-N 个事件
    """
    events = []
    
    # PS: 初次支撑 — 下降趋势中的第一根放量止跌K线
    # 特征：处于下跌趋势 + 放量 + 下影线 + 收盘在中上部
    ps_event = detect_ps(short_window=20, long_window=60)
    
    # SC: 恐慌抛售 — 天量、长下影线、极端恐慌
    # 特征：成交量 > 2x MA20 + 下影线 > 实体 + 振幅 > 4% + 次日反弹
    sc_event = detect_sc(window=30)  # 复用engine L1328-1376已有实现
    
    # AR: 自动反弹 — SC后的自然反弹
    # 特征：SC后3-5日 + 反弹幅度 > SC低点3% + 量能不放大
    ar_event = detect_ar(sc_event, window=10)
    
    # ST: 二次测试 — 缩量回测SC/Spring低点
    # 特征：价格回到SC/Spring附近 + 成交量 < MA20的60% + 未创新低
    st_event = detect_st(sc_reference, window=30)
    
    # Spring: 弹簧效应 — 假跌破支撑（已有实现）
    spring_event = detect_spring(window=120)  # 复用engine
    
    # SOS: 强势信号 — 放量大涨突破
    # 特征：涨幅 > 3% + 成交量 > 1.5x MA20 + 收盘在全天最高 25%
    sos_event = detect_sos(window=30)
    
    # LPS: 最后支撑点 — SOS后的缩量回踩
    # 特征：SOS后 + 回踩不破SOS低点 + 成交量 < MA20的70%
    lps_event = detect_lps(sos_event, window=20)
    
    # JAC: 跨越溪流 — 放量突破TR上轨
    # 特征：价格突破前期震荡区间高点 + 成交量 > MA20
    jac_event = detect_jac(trading_range, window=20)
    
    return events
```

#### 每类事件的具体检测规则

##### PS（Preliminary Support）— 初次支撑
```
条件:
  1. 前 20 日趋势 = 下跌（收盘价累计跌 > 5%）
  2. 当日成交量 > MA20 的 1.2x
  3. 下影线长度 > 实体长度的 50%（长下影线）
  4. 收盘价在全天振幅的上 40%（收盘在中上位置）
  5. 次日收盘 > 当日收盘（延续性确认）

评分:
  - 成交量比 1.2~1.5x: +1分
  - 成交量比 > 1.5x: +2分
  - 下影线 > 实体 2x: +2分
  - 收盘在顶部 20%: +1分
  - 总分 >= 3: 确认PS
```

##### SC（Selling Climax）— 恐慌抛售
```
条件（复用 engine.py:L417-440，增强）:
  1. 前 20 日趋势下跌 > 8%
  2. 成交量 > MA20 的 2.0x（历史天量级别）
  3. 下影线 > 实体长度
  4. 振幅 > 4%（真实恐慌幅度）
  5. 创 20 日新低后收高
  6. 之后 3 日内有反弹（close > SC close）

评分逻辑同 engine.py:L1328-1376:
  - 量能排名 > 80%: +2分
  - 下影比 > 0.6: +2分，> 0.4: +1分
  - 后续上涨 > 5%: +2分
  - sigmoid 缩放: confidence = 1/(1+exp(-(score-3)))
```

##### AR（Automatic Reaction）— 自动反弹
```
条件:
  1. 在 SC 后 2-5 个交易日内
  2. 累计涨幅 > SC 低点至反弹高点 >= SC 振幅的 30%
  3. 反弹期间成交量 <= MA20 的 1.2x（无量反弹 = 自然行为，非主力拉升）
  4. 反弹高点不过前 TR 中点

评分:
  - 3 日内达标: +2分
  - 5 日内达标: +1分
  - 量能不放大: +1分
```

##### ST（Secondary Test）— 二次测试
```
条件:
  1. 在 SC 或 Spring 后 5-30 个交易日内
  2. 价格回到 SC/Spring 低点附近（不超过低点 + 5%）
  3. 未跌破 SC/Spring 低点
  4. 成交量 < MA20 的 70%（显著缩量 = 供给枯竭的关键证据）
  5. 有下影线（有买盘承接）

这是威科夫体系中最关键的确认信号之一
评分:
  - 成交量 < MA20 的 50%: +3分（极度缩量 = 最强确认）
  - 成交量 < MA20 的 70%: +1分
  - 有下影线: +1分
  - 距离SC/Spring > 10日: +1分（时间越久，测试越有效）
```

##### Spring（弹簧效应）— **已有**
- 直接复用 WyckoffEngine 检测结果（`engine.py`）

##### SOS（Sign of Strength）— 强势信号
```
条件:
  1. 在 ST 或 Spring 确认后（有明确的底部结构）
  2. 日涨幅 > 3%
  3. 成交量 > MA20 的 1.5x
  4. 收盘在最高 25% 内（强势收盘）
  5. 创 N 日新高
  
评分:
  - 涨幅 > 5%: +2分
  - 量比 > 2.0: +2分
  - 创新高: +1分
```

##### LPS（Last Point of Support）— 最后支撑点
```
条件:
  1. 在 SOS 之后（趋势开始转向）
  2. 价格回调但不破 SOS 的低点
  3. 回调幅度不超过 SOS 的 50%（强势回调）
  4. 成交量萎缩至 < MA20 的 80%
  5. 出现下影线或十字星

LPS 可能是买入的最终时机（JAC 突破前最后的低位）
```

##### JAC（Jump Across Creek）— 跨越溪流
```
条件:
  1. 前期已识别明确的 TR（20 日 range < 15% 等）
  2. 价格突破 TR 上轨（前期高点）
  3. 成交量 > MA20
  4. 收盘在 TR 上轨上方

如果 JAC 时 LPS 刚出现不久，是最强突破信号
```

#### 验证方法
- 在已知的经典威科夫形态上可视化验证（如 2020 年 3 月大盘底部）
- 统计各类事件的频率，与设计文档的"年均 6-9 次"对比
- 检查事件序列的合理性（PS→SC→AR→ST→Spring 应依次出现）

---

### Phase III（2-3 天）：事件序列评分系统

#### WSO（Wyckoff Score Oscillator）

```python
class WSOScorer:
    """
    将确认的事件映射为分数 → EMA 平滑 → 交叉信号
    
    事件分数映射（基于月线相位调整）:
    在 accumulation 中:
        PS: +2, SC: +3, AR: +1, ST: +2, Spring: +4, SOS: +3, LPS: +2, JAC: +2
    在 markdown 中:
        Spring: +2, SOS: +2 （降低评分，趋势不利）
    在 markup 中:
        LPS: +2, JAC: +3, SOS: +1
    在 distribution 中:
        UT: -3, 放量滞涨: -2 （反向信号）
    
    信号生成:
        当 EMA(WSO) > +3 且月线为 accumulation:   买入
        当 EMA(WSO) < -3 且月线为 distribution:    卖出
        其余: 持有/观望
    """
```

#### WSS（Wyckoff Statistical Score）

```python
class WSSScorer:
    """
    统计事件序列的历史未来收益分布
    
    步骤:
    1. 扫描历史数据，提取所有事件序列
    2. 对每个序列，统计其后 N 日的收益分布
    3. 找到显著的正收益序列
    
    示例（沿用设计文档）:
        PS→SC→AR→ST 序列 → 未来 20 日上涨概率 75%
        SC→ST→Spring   → 未来 60 日收益均值 +4.2%
        Spring→SOS→LPS → 未来 30 日收益均值 +2.8%
    
    这是一个纯数据驱动的方法：
    - 不需要预设评分权重
    - 完全由历史表现决定
    - 需要足够数据（500 只 × 5 年 × 6000 根K线）
    """
    
    def scan_sequences(self, history):
        """扫描所有 2-4 事件序列，统计未来收益"""
        all_sequences = []
        for stock in stocks:
            events = self.detect_all_events(stock.daily)
            for i in range(len(events) - 1):
                for j in range(i+1, min(i+5, len(events))):
                    seq = events[i:j+1]
                    fwd_ret = compute_forward_return(
                        events[j].date, 
                        hold_days=20
                    )
                    all_sequences.append((seq, fwd_ret))
        
        # 聚合统计
        for seq_type in unique_sequence_types:
            rets = [r for s, r in all_sequences if s == seq_type]
            mean_ret = np.mean(rets)
            t_stat = stats.ttest_1samp(rets, 0)
            # 保存显著序列 (p < 0.05)
    """
```

#### WSO vs WSS 的选择

| 维度 | WSO | WSS |
|------|-----|-----|
| 开发难度 | 低（2 天） | 高（5+ 天） |
| 数据需求 | 低 | 高（需要大量历史序列） |
| 可解释性 | 高（预设权重明确） | 中（统计驱动） |
| 预期效果 | 优于硬规则，但不如 WSS | 可能接近设计文档的 16-25% |
| 过配风险 | 低（权重固定） | 中-高（需要 OOS 验证） |

**建议先实现 WSO**（因为快、可控、可解释性好），再视效果决定是否升级到 WSS。

---

### Phase IV（1 天）：多周期共振过滤

```python
class ResonanceFilter:
    """
    三周期共振规则:
    
    买入信号 = WSO > +3 且 至少满足以下 2 条:
      1. 月线相位 ∈ {accumulation, markup}（长线看多）
      2. 周线相位 ∈ {accumulation, markup}（中线看多）
      3. 日线相位 ≠ distribution（短线不空）
    
    强买入信号 = WSO > +5 且全部满足:
      1. 月线 = accumulation
      2. 周线 = accumulation 或 markup 的开始
      3. 日线 = accumulation 或 SOS
      4. 有 Spring 或 ST 事件在 10 日内确认
    
    卖出信号同理（distribution 相位 + 反向事件）
    """
```

---

### Phase V（1 天）：综合策略引擎

整合 Phase I-IV，形成完整的分析→评分→决策流程：

```python
class WyckoffStrategy:
    def analyze(self, stock_data, cutoff_idx):
        # Phase I: 相位
        mp = get_monthly_phase(stock_data, cutoff_idx)
        wp = get_weekly_phase(stock_data, cutoff_idx)
        dp = get_daily_phase(stock_data, cutoff_idx)
        
        # Phase II: 事件
        events = detect_events(stock_data.iloc[:cutoff_idx+1])
        
        # Phase III: 评分
        wso = WSOScorer.score(events, mp)
        
        # Phase IV: 共振确认
        signal = ResonanceFilter.confirm(wso, mp, wp, dp, events)
        
        return signal  # 'buy' | 'sell' | 'hold'
```

---

## 五、实现优先级与排期

| 优先级 | 模块 | 时间 | 依赖 | 独立价值 |
|--------|------|------|------|---------|
| **P0** | 周线/日线相位分析 | 1 天 | 无 | ✅ 立即提升Spring分析的维度 |
| **P0** | 事件检测：PS/AR/ST/SOS/LPS | 3 天 | Phase I | ✅ 这是设计文档和实际差距最大的环节 |
| **P1** | WSO 评分系统 | 2 天 | 事件检测 | ✅ 替代硬规则，提升信号质量 |
| **P1** | 多周期共振过滤 | 1 天 | Phase I | ✅ 实现设计文档的核心过滤逻辑 |
| **P2** | WSS 统计评分 | 5 天 | 事件检测 + WSO | ⭐ 潜在最大价值，预估 12-16%年化 |
| **P2** | JAC 事件检测 | 0.5 天 | 事件检测 | 补充最后一环 |
| **P3** | P&F 点数图 | 3 天 | 无 | 独立工具，可后续开发 |

**总计工作量**: ~15.5 天（单人全职）

---

## 六、预期效果

### 合理预期（基于当前代码的升级）

| 指标 | 当前（仅 Spring） | 预计（完整 WSO） | 预计（含 WSS） |
|------|-----------------|----------------|---------------|
| vs 非Spring 超额（OOS） | +3.28%（t=5.20） | +4-6%（更精确保留好信号） | +5-8% |
| vs SH 指数 | -2.40%（负超额） | 0% ~ +3%（共振过滤提升质量） | +3-6% |
| 年化（最佳参数） | ~7.6% | ~10-12% | ~12-18% |
| 信号频率 | ~2次/年/股 | ~3-5次/年/股（含多种事件） | ~4-6次/年/股 |
| 夏普比 | 1.28（单参数） | 1.5-2.0 | 1.8-2.5 |

### 与设计文档 16-25% 的差距

**设计文档的 16-25% 年化在几个关键点上可能被高估**：

1. **未扣除全交易成本**（A股印花税+佣金+滑点约 0.13%/笔）
2. **未做严格 OOS 测试**（引用民生金工的 2010-2024 报告，跨度过长可能含数据挖掘偏差）
3. **事件链评分（WSS）确实比单事件 Spring 好**，但 25.04% 接近顶尖量化私募水平，需要审慎看待

**谨慎估计**: 完整 WSO+WSS 系统的实际可达到年化约 12-18%（OOS 验证后），而非文档声称的 25.04%。

---

---

## 七、Phase I 实际验证结果（2026-06-26）

> 基于 500 只 A 股 × 22,148 个观测点 × 三周期相位分析的实际运行结果

### 7.1 已完成的模块

| 模块 | 文件 | 状态 |
|------|------|------|
| 月线相位分类器 | `monthly_classifier.py` | ✅ 已验证 76K 快照 |
| 周线相位分类器 | `phase_analysis.py:WeeklyPhaseClassifier` | ✅ 新建，阈值缩放到周线级别 |
| 日线相位分类器 | `phase_analysis.py:DailyPhaseClassifier` | ✅ 新建，基于 20日均线+短期趋势 |
| 三周期共振分析 | `phase_analysis.py:MultiTimeframeResonance` | ✅ 新建 |
| Phase I 运行器 | `phase1_multitf_analysis.py` | ✅ 22,148 观测点仅需 5 秒 |
| 单元测试 | `test_phase_analysis.py` | ✅ 26 个测试，全部通过 |

### 7.2 相位分布

| 相位 | 月线 | 周线 | 日线 |
|------|------|------|------|
| accumulation | 686 (3.1%) | 222 (1.0%) | 523 (2.4%) |
| markup | 3,006 (13.6%) | 4,441 (20.1%) | 4,078 (18.4%) |
| distribution | 117 (0.5%) | 209 (0.9%) | 66 (0.3%) |
| markdown | 9,542 (43.1%) | 10,275 (46.4%) | 5,727 (25.9%) |
| unknown | 8,797 (39.7%) | 7,001 (31.6%) | 11,754 (53.1%) |

三周期分布总体一致（markdown 主导，符合 2020-2024 年市场特征）。

### 7.3 核心发现

| 发现 | 详情 | 含义 |
|------|------|------|
| **共振具有反向指示性** | bullish 共振 → fwd6m -3.81%；bearish 共振 → fwd6m +2.30% | 强共识出现在拐点附近，是反向指标 |
| **3/3 强共振 = 持续信号** | 仅 17.3% 观测点，但 fwd6m +2.60%（t=5.18） | 三周期完全一致时趋势延续 |
| **周线/日线 markdown = 最强买入信号** | 日线 md +3.02%（t=7.69），周线 md +1.94%（t=6.77） | 短期超卖后反弹显著 |
| **日线 markup = 最强卖出信号** | -3.84%（t=-8.83） | 短期超买后回调 |
| **Spring + accum 确认无效** | 仅 79 次（0.4%），-1.60%（NS），逊于单独 Spring | 做多周期确认会错过大部分 Spring |

### 7.4 对 Phase II 的指导

1. **不要用 concurrent 相位共振作为 Spring 的过滤器**（会使结果更差）
2. **事件序列评分**应该关注**顺序模式**（如 PS→SC→Spring 链），而非同时的相位标签
3. **3/3 强共振**值得作为信号确认条件之一（+2.60% 持续收益）
4. **日线 markdown + 周线 markdown 的 concurrent 状态**本身可作为均值回归入场信号（+3.02%）
5. 数据质量和性能验证通过：22,148 观测点全程仅需 5 秒，8 进程并行高效

## 八、关键工程决策

### 1. 日线合成周线/月线时的防前视偏差

```python
# ✅ 正确做法（当前没有显式做，但 runner_v4 通过切片避免了）
df_right = df.iloc[:cutoff_idx+1]  # 只取到 cutoff 的数据
weekly = df_right.resample('W', closed='right', label='right').agg(...)

# ❌ 错误做法
weekly = df.resample('W').agg(...)  # 使用了全部数据，含未来
```

### 2. 周线阈值的确定

月线的 `range=80%` 不能直接用于周线。周线的自然波动更小，合理的 TR 阈值需要重新统计：

```python
# 统计 500 只股票的周线 range_pct 分布
# 预期：周线 P50 range 约 15-25%，阈值设在 20-30%
weekly_range_threshold = 0.25  # 需要统计分析确证
```

### 3. 事件确认顺序

威科夫事件有严格的先后约束：
```
积累: PS → SC → AR → ST → Spring → SOS → LPS → JAC
派发: PSY → BC → AR' → UT → SOS' → LPO → LPSY
```

事件检测器必须检查时序合理性：若 SC 在 Spring 之后出现，该 SC 应被标记为可疑（时间顺序错误）。这需要在 `EventSequence` 类中实现。

### 4. 数据需求

- 500 只 × 5 年 ≈ 600,000 日线记录 → 足够训练 WSS
- 时间跨度至少包含 1 个完整牛熊周期（2015-2024 约 10 年）
- 不需要高频数据（仅需日线）

### 5. 避免过配的关键

1. **事件检测参数** 必须基于统计分布（如 range_pct P50），而非手动调优
2. **WSS 评分** 必须做严格的 OOS 验证（如 2015-2019 训练 → 2020-2024 验证）
3. **多周期共振** 的过滤强度必须用回测验证（过强则信号太少，过弱则噪音太多）

---

## 九、总结

### 可行
✅ 用日线合成多周期 + 规则 + 事件序列评分 → **完整威科夫分析的基本盘**  
✅ 现有代码至少节省 40% 的开发量（Spring检测、相位分类、BC/SC检测可直接复用）  
✅ 在本地 Python 环境下完全可实现（无外部 API 依赖、无计算瓶颈）  

### 不宜
❌ 追求设计文档的 25.04% 年化（大概率高估，实际应在 12-18%）  
❌ 在 WSO 验证通过前直接做 WSS（WSO 是必需的中间步骤）  
❌ 在事件检测完善前做 RL/ 深度学习（这些是高阶增强，非基础功能）  

### 下一步
1. **立即做**：完善三周期相位分析（1天）
2. **重点投入**：实现完整事件链检测（3天，核心价值最高的环节）
3. **稳步推进**：WSO评分 + 共振过滤（3天）
4. **持续观察**：若WSO有效，升级到WSS（5天，可选）
