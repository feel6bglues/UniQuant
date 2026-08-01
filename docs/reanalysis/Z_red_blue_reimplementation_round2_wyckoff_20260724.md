# 红蓝对抗 Round 2 — Wyckoff 真实有效实现方案

> **日期**: 2026-07-24  
> **对抗议题**: 在项目约束下（A 股个股、120 天窗口、生产管线），Wyckoff 应该怎样实现才有真实预测力？
> **角色**: 🔵 Blue = 理论派（Wyckoff 标准方法） / 🔴 Red = 实用派（A 股适配简化）

---

## 审查标准

| 条件 | 门槛 |
|---|---|
| W1 | 相位检测基于成交量价差分析，非 MA 交叉 |
| W2 | Spring 实现可选的 Phase C 测试（非必须 TR 边界） |
| W3 | UTAD 要么实现正确要么显式删除 |
| W4 | 置信度系统不唯一依赖 Spring+LPS 门控 |
| W5 | Adapter 暴露 `trading_plan.direction` |
| W6 | "买入"信号走 Monte Carlo 验证 |
| W7 | 有真实的空头信号（Distribution/Markdown） |

---

## Claim 1: "Wyckoff 相位检测必须基于成交量价差分析"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | Wyckoff 三大法则之首就是供求法则。没有成交量分析的相位检测不配叫 Wyckoff。标准方法：对比价格 spread 和成交量判断供求平衡 — 放量滞涨 = 派发迹象，缩量回调 = 积累迹象。当前项目用 MA 金叉/死叉冒充相位检测，这是根本性的方法论错误 | Wyckoff Analytics 官方教程：SPREAD + VOLUME 为分析核心 |
| 🔴 Red | Blue 理论上完全正确。但**A 股成交量数据质量在 120 天窗口中不足以支撑可靠的成交量价差分析**。A 股存在：量化基金的程序化交易扭曲成交量结构、游资对倒制造虚假成交量、涨跌停板（10%/20%）导致成交量极端变化、北向资金/大宗交易等通道成交量不透明、新股/次新股换手率异常。在实践中，一个"放量滞涨"信号在 A 股有约 40-50% 的假阳性率。**过度依赖成交量的 Wyckoff 实现在 A 股反而会降低信号质量** | A 股实证：游资对倒/涨停板量化交易降低了成交量信号可信度 |
| ⚪ Referee | **SPLIT — RED 的 A 股成交量质量问题不可忽视。BLUE 的理论正确但在 A 股实用性受限。** 折中方案：**成交量作为辅助确认信号**（在 MA 相位检测基础上加权，而非替代）。主相位检测使用价格结构 + TR 分析 + 量能的**组合证据**，单一维度不足以下结论。 | |

**成交量价差分析的 A 股适配实现**:
```python
def compute_volume_spread_evidence(df, lookback=20):
    """计算成交量价差证据分数（适配 A 股低质量成交量）"""
    recent = df.tail(lookback)
    evidence = {"accumulation": 0.0, "distribution": 0.0, "neutral": 0.0}
    
    for i in range(1, len(recent)):
        bar = recent.iloc[i]
        prev = recent.iloc[i-1]
        spread = (bar.high - bar.low) / bar.low
        vol_ratio = bar.volume / max(recent["volume"].median(), 1)
        price_dir = 1 if bar.close > bar.open else -1
        
        # 价格方向 + 成交量 + spread 综合判定
        # 只在多个条件同时满足时加分，减少假阳性
        
        # 放量上涨 + wide spread = 需求主导（可能 SOS）
        if price_dir > 0 and vol_ratio > 1.5 and spread > recent["spread_pct"].median():
            evidence["accumulation"] += 0.15
            
        # 放量下跌 + wide spread = 供应主导（可能 SOW）
        elif price_dir < 0 and vol_ratio > 1.5 and spread > recent["spread_pct"].median():
            evidence["distribution"] += 0.15
            
        # 缩量回调 + narrow spread = 供应枯竭（可能 LPS）
        if price_dir < 0 and vol_ratio < 0.7 and spread < recent["spread_pct"].median():
            evidence["accumulation"] += 0.10
            
        # 放量滞涨 = 努力无结果 → 派发
        if vol_ratio > 1.5 and abs(bar.close - bar.open) / bar.open < 0.005:
            evidence["distribution"] += 0.20
    
    total = sum(evidence.values())
    if total > 0:
        for k in evidence:
            evidence[k] /= total
    return evidence
```

---

## Claim 2: "Spring 当前实现的结构性缺陷可通过移除 boundary_lower 依赖修复"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 标准 Wyckoff 中 Spring 是 TR 边界测试。`boundary_lower > 0` 的要求在 TR 形成后完全合理。但问题出在 TR 检测 — 当前代码的 `is_in_trading_range` 太严格（范围<20% + 短趋势<5%），导致 TR 很难被识别。**修复方向应该是改进 TR 检测，不是移除 boundary_lower 依赖** | `constants.py:17-18`: range_threshold=0.20, trend_threshold=0.05 |
| 🔴 Red | 在实践中，A 股 120 天窗口中 TR 形成且恰好被检测到的概率很低。**Spring 在标准 Wyckoff 中有两种 Accumulation 示意图（带 Spring / 无 Spring）**，说明 Spring 是可选的。当前代码把 Spring 从"可选 Phase C 测试"变成了"必须的门控条件"（置信度和信号输出都以 Spring 为门）。更合理的做法：**移除 Spring 作为置信度和信号的门控**，只在 TR 明确形成时才启用 Spring 检测；无 Spring 时走替代路径（SOS → LPS 确认） | Wyckoff Accumulation Schematic #2: 无 Spring 的积累 TR |
| ⚪ Referee | **RED WINS.** 核心问题不是 Spring 本身，而是**Spring 被错误地设为系统门控**。标准 Wyckoff 明确提供无 Spring 的积累路径。修复方案：Spring 降级为可选补充信号，置信度和交易计划不依赖 Spring | |

**Spring 降级实现**:
```python
# 新的 Spring 定位：可选 Phase C 事件，非门控
def _detect_spring_optional(self, df, boundary_lower):
    """Optional Spring detection - only fires when TR boundary exists"""
    if boundary_lower <= 0:
        return {"spring_detected": False}  # 无 TR 无 Spring — 正常跳过
    # ... 正常 Spring 检测 ...
    
    # 不管 Spring 是否检测到，系统继续走 SOS/LPS 路径
```

---

## Claim 3: "Markup 阶段 '买入' 信号应提取为独立趋势延续策略"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | Walk-forward 实证：markup+"买入" 27/600 (4.5%), fwd_20d=+13.33% (p=0.0098), win rate 88.9%, spread=+8.60% vs 普通 markup。这个信号有真实统计显著性，应该作为独立交易策略提取。当前代码中该信号通过 `_classify_wyckoff_markup_event` 中的 "Test" / "Shakeout" 子事件分类触发 | `engine.py:1055`: `if "Test" in markup_sub_event or "Shakeout" in markup_sub_event: direction = "买入"` |
| 🔴 Red | 只有 27/600 次触发（4.5%），24/100 只股票涉及，但回测用的是**同一数据集的 120 天窗口** — 存在严重的**多重比较偏差**。项目在 walk-forward 中测试了 300+ 个潜在信号组合（3 risk_levels × 5 phases × 5 directions × 4 confidence levels × ...），从中筛选出 p=0.0098 的一个。Bonferroni 校正后 p 值 ≈ 0.0098 × 300 = 2.94 ≈ **不显著**。需要**独立的 Monte Carlo 模拟**来验证该信号的真实性：对 GBM 白噪声运行同样的 markup→"买入"检测逻辑，看同样条件能否产生同样收益 | 300+ 个隐性多重比较 |
| ⚪ Referee | **RED WINS** — BLUE 的实证发现有价值，但多重比较问题是真实的。**最终结论：该信号值得进一步研究，但在 MC 验证前不能作为生产交易信号输出。** | |

---

## Claim 4: "UTAD 必须实现或删除 — 当前死代码状态不可接受"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | `_detect_utad` 是空函数 `return None`（`engine.py:472-473`），但 `_step3_phase_c_t1` 中有独立的 UTAD 实现（`engine.py:735-743`）需要 Distribution 相位触发。两个实现都不工作：第一个永远返回 None，第二个需要 Distribution 相位（0/600） | `engine.py:471-473` 和 `engine.py:735-743` |
| 🔴 Red | **删除是最务实的方案**。"正确的 UTAD 实现"需要：已识别的 Distribution TR + 上边界假突破 + 快速收回。但 Distribution 相位在 A 股 120 天窗口中几乎不会形成 — 该窗口长度不足以形成一个完整的派发 TR。如果把 `_detect_utad` 改成一个简化版 UT 检测器（不需要 Distribution 相位），可能会产生大量假信号。在空头信号缺失的情况下，**不如承认当前引擎没有空头能力**，依靠其他信号源（如 FSM/Regime）提供空头信号 | 实证：Distribution 相位 0/600 |
| ⚪ Referee | **RED WINS — 删除 > 重写 > 保持死代码。** 当前 UTAD 死的 / 写的双重实现在代码维护角度是最差状态。删除 `_detect_utad` 空函数 + 在 `_step5_trading_plan` 中显式标注"本引擎不生产空头信号" | |

---

## Claim 5: "置信度系统应基于多维度确认而非 Spring 门控"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 当前置信度系统（`engine.py:916-983`）分 5 级（A/B+/B/C/D），但 A 和 B+ 级都要求 `spring_detected AND lps_confirmed`。C 级的 bypass 路径也需要 Spring 只是没有 LPS。**这意味着所有无 Spring 的市场（251/600 markup, 235/600 unknown = 81% 的数据）置信度结构上限为 D 级（≈0 置信度）**。标准 Wyckoff 中 Spring 只是 Phase C 的可选事件，置信度应基于：趋势清晰度、成交量确认度、多周期一致性、风险回报比 | `engine.py:926-963` — 所有高置信度路径都经过 Spring |
| 🔴 Red | 置信度系统需要在实际可用的信号上校准。项目当前唯一有效信号是 markup→"买入"（p=0.0098），这个信号的置信度应该用基于历史表现的统计校准（signal quality score），而不是抽象的 Spring+LPS 规则。**真正的置信度 = 该信号在类似条件下的历史胜率 × 当前条件的吻合度** | |
| ⚪ Referee | **RED WINS 实践方案**。置信度重构：用分层贝叶斯方法。上层：信号类型的历史条件胜率（如 markup+"买入" 的历史 20d 胜率 88.9%）。下层：当前结构吻合度（成交量确认、趋势强度、RR 比率）。两者结合 = 最终置信度。脱离 Spring 门控。 | |

**置信度重构实现**:
```python
def compute_confidence_v2(signal_type, historical_stats, current_conditions):
    """分层贝叶斯置信度——不依赖 Spring"""
    # 先验：信号类型的无条件胜率
    prior_win_rate = historical_stats.get(signal_type, {}).get("win_rate_20d", 0.5)
    prior_n = historical_stats.get(signal_type, {}).get("n_observations", 100)
    
    # 似然：当前条件的吻合度
    volume_confirm = current_conditions.get("volume_confirm", 0.5)
    trend_clarity = current_conditions.get("trend_clarity", 0.5)
    rr_quality = min(current_conditions.get("rr_ratio", 1.0) / 3.0, 1.0)
    multi_tf_alignment = 1.0 if current_conditions.get("multi_tf_aligned") else 0.3
    
    likelihood = (volume_confirm * 0.3 + trend_clarity * 0.3 + rr_quality * 0.2 + multi_tf_alignment * 0.2)
    
    # 后验 = 加权平均
    posterior = (prior_win_rate * prior_n + likelihood * 20) / (prior_n + 20)
    return min(max(posterior, 0.0), 1.0)
```

---

## Claim 6: "Wyckoff 应重新定位为趋势延续系统而非相位预测系统"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔴 Red | 当前 Wyckoff 实现声称能检测 Accumulation→Markup→Distribution→Markdown 的相位循环。但实证证明：**Accumulation 的 20d 收益最差（+3.94%），Markup 最好（+6.14%），Markdown 反而比 Accumulation 好（+5.50%）**。相位循环不成立。Wyckoff 在 A 股 120 天窗口中的唯一有效能力是**在已有上升趋势中识别低风险入场点**（markup+"买入"）。应重新定位为**趋势延续信号系统**，不是"市场阶段预测系统" | Walk-forward 实证数据 |
| 🔵 Blue | 如果放弃相位循环预测，Wyckoff 的理论骨架就丢失了。Wyckoff 的核心价值在于"知道市场在大的宏观循环中处于什么位置"。但 RED 的实证数据确实是项目当前代码的诊断结果。**如果重构相位检测（加入成交量分析和 A-E 结构），相位循环预测可能重新成立** — 需要较长时间窗口（>1 年） | |
| ⚪ Referee | **RED WINS 实用方案**。在当前 120 天窗口和 A 股特性约束下，Wyckoff 作为相位循环预测系统不成立。**建议**：保留 Markup/Markdown/Accumulation 作为**趋势+动量状态标签**（而非预测标签），并把 "买入" 信号作为独立的趋势延续信号提取。Distribution 移除（无法检测）。 | |

---

## Round 2 汇总

| Claim | 议题 | Blue | Red | 裁决 |
|---|---|---|---|---|
| W1 | 成交量价差 vs MA 交叉 | ✅ | ⚠️ | **SPLIT** — 成交量作为辅助加权 |
| W2 | Spring 门控问题 | ⚠️ | ✅ | **RED** — Spring 降级为可选 |
| W3 | Markup"买入"信号提取 | ⚠️ | ✅ | **RED** — 需 MC 验证，当前不能上线 |
| W4 | UTAD 死代码 | ✅ | ✅ | **RED** — 删除最优 |
| W5 | 置信度重构 | ⚠️ | ✅ | **RED** — 分层贝叶斯 |
| W6 | Wyckoff 重新定位 | ⚠️ | ✅ | **RED** — 趋势延续系统 |

**核心产出二：Wyckoff 真实有效实现方案**:
```
┌─────────────────────────────────────────────────────────────┐
│ Wyckoff v4 — 真实有效实现                                    │
├─────────────────────────────────────────────────────────────┤
│ 定位：A 股趋势确认 + 趋势延续信号系统，非相位预测系统          │
├─────────────────────────────────────────────────────────────┤
│ 相位检测（简化版）：                                         │
│ ├─ Markup = 趋势>3% + MA 多头（不改 — 已验证有效）           │
│ ├─ Markdown = 趋势<-5% + MA 空头（不改 — 对称处理）          │
│ ├─ Accumulation = 下跌后横盘 + 量能辅助（加成交量确认）       │
│ └─ Distribution = ❌ 移除（实践中不可检测）                   │
│                                                             │
│ Spring 降级为可选事件（非门控）：                              │
│ ├─ 有 TR 边界时启用 Spring 检测                               │
│ ├─ 无 TR 边界时跳过 Spring，只走 SOS→LPS 路径                  │
│ └─ 置信度不依赖 Spring                                       │
│                                                             │
│ UTAD：❌ 删除当前死代码                                       │
│                                                             │
│ 唯一有效信号：Markup + "买入"（Test/Shakeout）：                │
│ ├─ 提取为独立策略模块                                         │
│ ├─ 需要 Monte Carlo 验证                                      │
│ └─ 单信号 20d 胜率 88.9%, 但仅 4.5% 触发率                     │
│                                                             │
│ 信号输出：expose trading_plan.direction 为主信号               │
│ 置信度：分层贝叶斯，不依赖 Spring+LPS 门控                      │
│ 空头信号：依赖外部信号源（FSM/Regime）                          │
└─────────────────────────────────────────────────────────────┘
```

**对项目的建议**：
1. **立即修复**：Adapter 暴露 `trading_plan.direction`（2h）
2. **立即修复**：删除 UTAD 死代码、Spring 降级（1h）
3. **立即修复**：置信度解耦 Spring（3h）
4. **需研究**：Markup"买入"MC 验证（4h）
5. **需研究**：成交量价差加权模块（6h）
6. **不推荐**：完全重写 Wyckoff 相位系统（40h+，收益不确定）
