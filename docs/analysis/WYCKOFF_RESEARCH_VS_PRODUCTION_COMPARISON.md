# 研究管线 vs 生产引擎: 全面对比分析

## 问题一: 研究管线是否对齐了经典 Wyckoff 分析？

**答案: 部分对齐，但有 4 个关键偏离。** 研究管线是"Wyckoff 启发"的量化系统，统计有效（t=10.24, Sharpe 2.02），但并非经典 Wyckoff 的忠实实现。

### 对齐的部分

| 维度 | 研究管线做法 | 经典 Wyckoff 要求 | 对齐度 |
|------|------------|-----------------|-------|
| 三周期分析 | 月线/周线/日线独立分类 | 月线定趋势、周线定中期、日线定短期 | ✅ |
| 事件检测 | 8 类事件（PS/SC/AR/ST/SOS/LPS/Spring/JAC） | 相同事件集 | ✅ |
| 事件序列 | 检测事件序列并评分 | 事件序列决定相位 | ✅ |
| 卖出信号 | 卖出信号强于买入（均值回归） | 派发后应下跌 | ✅ |
| 成交量确认 | 使用 vol_ratio, vol_trend, obv_trend | 成交量签名确认事件 | ⚠️ 部分 |

### 偏离的部分

| 偏离 | 研究管线做法 | 经典 Wyckoff 要求 | 严重度 |
|------|------------|-----------------|-------|
| **无 P&F 图表** | 使用 OHLCV 柱状图 + range 阈值 | P&F 图是 Wyckoff 分析的基础 | 🔴 根本性 |
| **无 Trading Range 识别** | 用 price_position 和 range_pct 替代 | 先识别 TR 边界，再分析 TR 内行为 | 🔴 根本性 |
| **共振反向指示** | 三周期看多 = 顶部（反向） | 三周期共振 = 趋势确认 | 🔴 理论对立 |
| **无事件因果链** | WSO 独立加权求和（PS=+1.05, SC=+0.94） | 事件按特定顺序形成因果链 | 🟠 方法论差异 |

### 结论

研究管线是**统计有效的量化信号系统**，不是**经典 Wyckoff 分析方法**。它借用了 Wyckoff 的术语和事件框架，但用统计方法（WSO/WSS）替代了经典 Wyckoff 的因果推理（P&F → TR → 事件序列 → 相位 → 目标价）。它的有效性来自 A 股市场的均值回归特性，而非 Wyckoff 理论的因果结构。

---

## 问题二: 研究管线和生产管线的具体区别

### 区别总览

| 维度 | 研究管线 | 生产引擎 | 差距性质 |
|------|---------|---------|---------|
| 相位判定方法 | 三周期独立分类 + 共振投票 | 单月线检测器链 winner-takes-all | **架构级** |
| P&F 使用 | 不使用 | 覆盖层主导 63.2% 相位 | **架构级** |
| 事件序列 | WSO 独立评分 + WSS 统计权重 | 检测器链内联检测，相位后附加 | **架构级** |
| 置信度 | WSS 连续评分（436 种序列） | 3 值离散（84% D, 0% A） | **算法级** |
| 共振过滤 | 接入决策（反向指示性） | 已实现未接入 | **接线级** |
| 方向预测 | t=10.24, 多空跨距 +8.07% | 理论一致性 50%（=随机） | **效果级** |

### 1. 相位判定架构：根本性差异

**研究管线** — 三周期独立分类 + 共振投票:
```
月线 (MonthlyPhaseClassifier)  → 月线相位
周线 (WeeklyPhaseClassifier)   → 周线相位
日线 (DailyPhaseClassifier)    → 日线相位
                                  ↓
                          MultiTimeframeResonance.resonance()
                                  ↓
                            共振投票结果
```

每个周期独立判定，互不影响。三周期共振投票最终决定相位。月线陷入值 **3.1%**，markdown **43.1%**，unknown **39.7%**。方向性已验证: Accum→+3.72%, Mkup→+11.19%, Dist→-3.81% fwd 6m。

**生产引擎** — 单月线检测器链 winner-takes-all:
```
检测器链 (单一月线周期):
  1. _detect_markup     → 如果命中，直接返回 MARKUP
  2. _detect_distribution → 如果命中，直接返回 DISTRIBUTION
  3. _detect_markdown   → 如果命中，直接返回 MARKDOWN
  4. _detect_accumulation → 如果命中，直接返回 ACCUMULATION
  5. _detect_spring
  6. _detect_utad
  7. _detect_sos
  ↓
  P&F 覆盖层 (63.2% 覆盖，覆盖时覆盖检测器链)
```

**核心问题**: 检测器优先级决定了"最好的标的给 markup，最差的给 accumulation"。这导致 accumulation 市场本质上是"剩下的"——不是真正的积累，而是"检测器链没识别的"。这就是为什么 63.2% 的积累中 6 个月收益 -21%。

### 2. 具体代码实现对比

#### 2.1 月线相位分类

**研究管线** (`monthly_classifier.py:MonthlyPhaseClassifier.classify()`):
```python
# 输入: 12 根月线 OHLCV
# 特征: price_pos, trend_pct, vol_trend, range_pct, vol_ratio, ret_6m, vp_corr, obv_trend
# 规则:
if tr < -15 or (r6 < -10 and pp < 0.3):    return 'markdown'
if pp < 0.35 and vt < -0.15 and rp < 80 and vr < 0.85:  return 'accumulation'
if tr > 10 and pp > 0.5 and vt > 0:          return 'markup'
if pp > 0.6 and vp_c < -0.2 and rp > 80:     return 'distribution'
# 无 P&F, 纯 OHLCV 特征
```

**生产引擎** (`engine.py` 检测器链):
```python
# 输入: 120 根月线 OHLCV (实际是 120 根日线合成月线)
# 特征: short_trend, relative_position, prior_trend, ma5, ma20, is_in_tr
# 规则:
if st >= 0.03 and cp > ma20:                 return MARKUP (markup 优先)
if utad_detected:                             return DISTRIBUTION
if st <= -0.05 and cp < ma20 * 0.95:         return MARKDOWN
if prior_trend < -0.03:                       return ACCUMULATION
# P&F 覆盖层 63.2% 覆盖检测器链
```

**关键差异**:
- **研究管线**使用 12 根月线（12 个月），**生产引擎**使用 120 根月线（10 年）
- **研究管线**使用 range_pct = 80% 阈值，**生产引擎**使用 MA 交叉 + 趋势
- **研究管线**使用 OBV 趋势和量价相关性，**生产引擎**不使用
- **研究管线**无 P&F，**生产引擎** P&F 主导

#### 2.2 事件检测

**研究管线** (`events.py:detect_all_events()`):
```python
# 独立于相位运行
events = detect_all_events(window)  # 在 120 日窗口上检测
seq_key = event_sequence_key(events)
# events = [PS, SC, AR, ST, ...]  # 独立于相位
# WSO = Σ(event_weight × confidence)
# 信号: WSO ≥ 0.04 → 买入, WSO ≤ -0.03 → 卖出
```

**生产引擎** (`engine.py` 内联检测):
```python
# 依赖于相位
# 在 _step3_phase_c_t1 中检测 spring/utad/sos
# 检测器链的 _detect_spring 返回 "sc_st_candidate" 但不用作独立信号
# 事件检测结果进入 _calc_confidence 的 5 条件矩阵
```

**关键差异**:
- **研究管线**事件检测独立于相位，事件本身决定交易信号
- **生产引擎**事件检测依赖于相位，相位错了事件也跟着错
- **研究管线** WSO 使用独立权重求和，**生产引擎**使用 5 条件矩阵

#### 2.3 置信度评分

**研究管线** (`sequence.py:WyckoffScorer`):
```python
# WSS 查找表: 436 种序列, 用 f6 收益的 t 统计量校准
# 评分 = t 统计量 × 收益均值 × 胜率
# 连续评分 ∈ [-1, 1]
# 分布: 各档 fwd 收益单调
```

**生产引擎** (`engine.py:_calc_confidence`):
```python
# 5 条件矩阵: 8 个条件 → 4 个等级 (A/B/C/D)
# 84% 落在 D 档 (0.3)
# 0% A 档
# 评分与收益负相关
```

**关键差异**:
- **研究管线**连续评分，各档收益单调
- **生产引擎**3 值离散，84% D 档
- **研究管线**数据驱动（f6 收益校准），**生产引擎**硬编码规则

### 3. 效果对比

| 指标 | 研究管线 | 生产引擎 (当前) | 生产引擎 (+v3.1) |
|------|---------|----------------|-----------------|
| 理论一致性 | 未单独测量 | **50%** (=随机) | **~55%** |
| 方向预测 | **t=10.24** | 无统计显著 | 部分修复 |
| 多空跨距 | **+8.07%** | 无 | 未测量 |
| Sharpe | **2.02** | 未测量 | 未测量 |
| 相位分布 | accum 3%, markup 14%, dist 0.5%, md 43%, unk 40% | accum 63%, markup 3%, dist 20%, md 7%, unk 4% | accum 0.6%, markup 15.5%, md 10%, unk 62% |
| 置信度分布 | 连续有区分 | 84% D, 0% A | 未改 |
| 共振过滤 | 已接入决策 | 实现但未接入 | 未改 |

### 4. 根源差距: 设计哲学

| 维度 | 研究管线 | 生产引擎 |
|------|---------|---------|
| **设计目标** | "统计验证 Wyckoff 信号是否有效" | "逐股给出实时分析报告" |
| **方法论** | 数据驱动: 先收集数据，再统计验证 | 规则驱动: 先定义规则，再硬编码 |
| **相位定义** | 相位是统计分类结果 | 相位是规则推理结果 |
| **事件序列** | 独立于相位，WSO 评分驱动 | 依赖于相位，检测器链内联 |
| **阈值来源** | 经验分布分析（P25/P50 等） | 理论推导 + 硬编码 |
| **验证方式** | 22K 观测 OOS 验证 | 132 个单元测试 |
| **信号使用** | 事件序列评分 → 交易信号 | 相位标签 → 置信度矩阵 → 信号 |

### 结论

**研究管线不是经典 Wyckoff 的忠实实现，但它是统计有效的量化系统。** 它用统计方法（WSO/WSS）替代了经典 Wyckoff 的因果推理（P&F → TR → 事件序列 → 相位），在 A 股市场达到了 t=10.24, Sharpe 2.02 的效果。

**生产引擎既不是经典 Wyckoff，也不是统计有效的量化系统。** 它的相位判定是 50% 随机水平，检测器链架构导致积累变成"剩余标的"，P&F 覆盖层使 63.2% 的相位由历史形态统计主导而非预测。

**v3.1 方案修复了生产引擎最明显的分布偏差（accum 63.2%→0.6%），但未触及研究管线已证明有效的核心组件：三周期独立分类、事件序列独立评分、WSS 统计权重、共振过滤接入决策。**