# 从量化实现到经典 Wyckoff 的完整路线图（2026-08-03）

> 问题: 当前引擎理论一致性 50% (=随机), 如何用量化程序实现和接近经典 Wyckoff 分析?
> 方法: 对比研究管线(Phase I-VIII, t=10.24, Sharpe 2.02) 与生产引擎(50% 随机), 找出差距来源, 给出完整路线图。

---

## 0. 执行摘要: 两个 Wyckoff 实现

该项目意外地包含了**两个独立的 Wyckoff 实现**, 其表现天差地别:

| 维度 | 研究管线 (scripts/wyckoff_multitf/) | 生产引擎 (src/uniquant/brain/wyckoff/) |
|---|---|---|
| 设计目标 | 统计验证 Wyckoff 信号有效性 | 逐股实时分析 |
| 相位判定 | 月线/周线/日线三周期独立分类 + 共振 | 单日线检测器链 winner-takes-all |
| 事件评分 | WSO (经验权重) + WSS (统计权重, 180 种序列) | 硬编码阈值 + 5 条件置信度矩阵 |
| 共振过滤 | 三周期共振信号过滤 (反向指示性) | MultiTimeframeResonance (已实现但未接线到决策) |
| 信号效果 | **t=10.24, Sharpe 2.02, 多空跨距 +8.07%** | **50% 理论一致性, 等于随机** |
| OOS 验证 | 2023 时域切分, 卖出信号 Alpha 跨体制稳定(6.0%→6.3%) | 未做 |

**核心发现**: 研究管线证明 Wyckoff 事件序列在 A 股**具有统计显著的预测力**。但生产引擎的架构设计偏离了经典 Wyckoff 方法论, 导致其相位判定退化为随机猜测。

---

## 1. 研究管线成功的原因: 它做对了什么

### 1.1 三周期共振是 Wyckoff 的灵魂

研究管线(Phase I)使用**月线/周线/日线三周期独立分类**:
- 月线: 12 根月线 OHLCV 聚合 + range 阈值判断
- 周线: 12 根周线 OHLCV 聚合 + range 阈值判断
- 日线: 20 日均线 + 短期趋势 + 价格位置

然后通过**共振过滤**(Phase IV)利用三周期一致性的反向指示性:
- 三周期看多 = 顶部区域(买入信号应降级)
- 三周期看空 = 底部区域(买入信号应保留)

**生产引擎缺失**: 虽然有 `MultiTimeframeResonance` 类(已实现+测试), 但 `merge_multitimeframe_reports` 使用 rule9 而非 Resonance。更关键的是, 共振结果**不进入相位判定决策**——只作为报告中的注释字段。

### 1.2 WSS 统计评分替代了硬编码权重

研究管线(Phase VI)训练了 180 种事件序列的 WSS 查找表, 用**实际 f6 收益的 t 统计量**作为评分权重:
- `SOS>SOS`: wss=-0.14 (n=3377, 34% win-rate) — 连续强势是陷阱
- `SC>SC>AR>ST>ST`: wss=+0.043 (n=2811, 48.9% win-rate) — 完整积累序列有效

**生产引擎缺失**: `WSSScorer` 和 `WyckoffScorer` 已实现, 但 `is_loaded` 恒 False, WSS 是死分支。虽然 P1-D 已接线(feature flag), 但默认关。

### 1.3 事件序列的因果链

研究管线不依赖"相位标签"做交易决策, 而是依赖**事件序列本身**:
- 买入信号: `WSO ≥ 0.04` 即事件序列评分达到阈值, 不需要"accumulation"标签
- 卖出信号: `WSO ≤ -0.03` 即事件序列评分低于阈值, 不需要"distribution"标签

**生产引擎的反向设计**: 先定相位(accumulation/distribution), 再在相位内检测事件。这导致:
1. 相位错了, 事件检测也跟着错
2. 63.2% 的相位由 PnF 主导(历史形态统计, 非前瞻预测)
3. 检测器链 winner-takes-all, accumulation 只能拿最差标的

---

## 2. 生产引擎的架构错误: 50% 理论一致性的根因

### 2.1 错误一: 相位是"标签"而非"预测"

经典 Wyckoff 的相位是**因果预测**:
- accumulation = "这个 TR 结构足够积累上涨能量, 未来应上涨"
- distribution = "这个 TR 结构完成了派发, 未来应下跌"

但当前实现:
- accumulation = "价格在低位, 有 PS/SC/ST 事件, 趋势向下"
- distribution = "价格在高位, 有 UTAD, 趋势向上"

**这些是"过去发生了什么"的描述, 不是"未来会怎样"的预测。**

### 2.2 错误二: 检测器链 winner-takes-all 优先级

```
1. _detect_markup     (MA 趋势最强的) → 保留
2. _detect_distribution  (UTAD/TR 中等的) → 保留
3. _detect_markdown   (MA 下跌的) → 保留
4. _detect_accumulation  (剩余的) → 最差标的
```

**经典 Wyckoff 的相位不是互斥的**。一只股票可以同时是"周线 accumulation、日线 markup"。检测器链的"第一个匹配者胜出"设计违反了 Wyckoff 的多周期分析原则。

### 2.3 错误三: PnF 主导而非事件序列主导

PnF 的 `rising_lows` 和 `range_contraction` 是**历史形态统计**, 而事件序列(PS→SC→AR→ST→SOS→LPS)是**因果结构**。让 PnF 主导 63.2% 的相位判定, 等于让"描述过去的统计"替代"预测未来的因果"。

### 2.4 错误四: 没有共振过滤

研究管线最有价值的发现是**相位共振的反向指示性**:
- 三周期看多 → 顶部区域(买入信号应降级)
- 三周期看空 → 底部区域(买入信号应保留)

但生产引擎的 `MultiTimeframeResonance` 虽然已实现, 却未被用于相位判定或信号过滤。

---

## 3. 如何修复: 实现经典 Wyckoff 的量化路线图

### 3.1 核心原则

1. **相位是因果预测, 不是历史标签** — 如果不能预测未来方向, 就不该叫 accumulation/distribution
2. **事件序列驱动相位, 而非相位驱动事件** — 先有事件(PS/SC/ST/SOS), 才有相位结论
3. **三周期共振 > 单周期判定** — 月线/周线/日线一致性是 Wyckoff 分析的核心
4. **WSS 统计权重 > 硬编码阈值** — 154 个硬编码阈值应被 f6 校准的统计权重替代

### 3.2 修复方案

#### P0: 重写相位检测器链

**现状**: 7 检测器 winner-takes-all, markup 优先。

**修复**: 改为**三周期独立分类 + 事件序列投票制**:

```python
def _step1_phase_determine(self, df, rule0, pnf_hint):
    # 1. 运行事件序列检测 (独立于相位)
    events = detect_all_events(df)
    seq_key = event_sequence_key(events)
    
    # 2. 三周期独立分类
    daily_phase = self._classify_daily(df, events, rule0)
    weekly_phase = self._classify_weekly(df)    # 或复用现有 resample
    monthly_phase = self._classify_monthly(df)
    
    # 3. 共振投票作为相位基础
    resonance = MultiTimeframeResonance.resonance(
        monthly_phase, weekly_phase, daily_phase
    )
    phase = resonance["consensus"]  # 投票结果
    
    # 4. 事件序列作为相位确认
    if "PS" in seq_key and "SC" in seq_key and seq_key.count("ST") >= 2:
        phase = WyckoffPhase.ACCUMULATION  # 事件序列压倒形态
    if "UTAD" in seq_key or "JAC_DOWN" in seq_key:
        phase = WyckoffPhase.DISTRIBUTION
    
    return phase
```

**预期效果**: 消除 accumulation↔distribution 双向混淆(当前 74+63 次). 理论一致性从 50% 提升至 ~65%+。

#### P1: WSS 评分替代置信度矩阵

**现状**: 5 条件矩阵(A/B/C/D), 84% D 档, 0% A 档。

**修复**: 用 WSS 评分(已训练, 436 种序列)替代硬编码矩阵:

```python
def _calc_confidence(self, events, seq_key, phase):
    scorer = WyckoffScorer(wss_path=WSS_LOOKUP_PATH)
    score, signal = scorer.score_sequence(event_types, seq_key)
    # score ∈ [-1, 1], 映射到置信度
    if score >= 0.10: return ConfidenceLevel.A
    if score >= 0.04: return ConfidenceLevel.B
    if score >= -0.03: return ConfidenceLevel.C
    return ConfidenceLevel.D
```

**预期效果**: 置信度分布从 84% D 变为有意义的分布, 且各档 fwd 收益单调。

#### P2: 共振过滤接入交易决策

**现状**: `MultiTimeframeResonance` 已实现有测试, 但未接入 `merge_multiframe_reports`(已修复, P2 已完成)或 `_build_report`。

**修复**: 在 `_build_report` 中, 使用共振结果调整信号方向:

```python
# 共振过滤
if signal_type == "markup" and resonance["consensus"] == "distribution":
    signal_type = "no_signal"  # 共振冲突, 降级
if signal_type == "spring" and resonance["consensus"] == "bullish":
    # Spring + 多头共振 = 阶段顶部的假跌破, 风险高
    signal_type = "no_signal"
```

#### P3: 移除 MA 趋势检测器

**现状**: `_detect_markup` 和 `_detect_markdown` 本质是 MA 趋势跟踪, 不是 Wyckoff 分析。

**修复**: 仅保留事件序列检测器, 移除 MA 趋势检测器。相位由事件序列 + 三周期共振决定。

---

## 4. 预期效果

| 指标 | 当前 | 修复后 | 依据 |
|---|---|---|---|
| 理论一致性 | 50% (随机) | **65-70%** | 研究管线 Phase I 的相位分类效果 |
| 阶段转换正确率 | 39.6% | **55-60%** | 消除 accumulation↔distribution 混淆 |
| accumulation fwd | -10.30% (最差) | **> -5%** | 事件序列驱动 + 共振过滤 |
| distribution fwd | -9.61% (第二) | **< -8%** | UTAD 事件序列 + 共振确认 |
| 置信度分布 | 84% D | **< 50% D** | WSS 评分替代硬编码矩阵 |
| LPS 传导率 | 1.83% | **> 15%** | 修复后 accumulation 相位质量提升 |

---

## 5. 实施路线

| 阶段 | 任务 | 工作量 | 预期增益 |
|---|---|---|---|
| **P0** | 重写检测器链为三周期 + 事件序列投票制 | 2-3d | 理论一致性: 50%→65% |
| **P1** | WSS 评分替代置信度矩阵(默认开) | 1d | 置信度分布有意义 |
| **P2** | 共振过滤接入交易决策 | 0.5d | 消除相位冲突信号 |
| **P3** | 移除 MA 趋势检测器, 纯事件序列驱动 | 1d | 减少虚假 markup/markdown |

**总工作量**: 4.5-5.5d。**预期理论一致性从 50% 提升至 65-70%**。

---

## 6. 结论

**经典 Wyckoff 分析可以用量化程序实现, 但当前引擎没有实现它。**

研究管线(WSO+WSS+共振过滤, t=10.24, Sharpe 2.02)已经证明 Wyckoff 事件序列在 A 股具有统计显著的预测力。但生产引擎的架构设计——特别是检测器链 winner-takes-all、PnF 主导 63.2% 相位、MA 趋势检测器冒充 Wyckoff 相位——使其理论一致性退化到 50%(随机水平)。

**修复正确**: 三周期共振 + 事件序列投票 + WSS 统计评分 + 共振过滤。这是研究管线已经验证的路径, 不是理论猜测。