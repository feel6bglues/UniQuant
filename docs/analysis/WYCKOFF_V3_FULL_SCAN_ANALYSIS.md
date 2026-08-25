# Wyckoff v3 全量扫描数据分析与对齐方案

**分析日期**: 2026-08-06
**数据**: 5445 只 A 股 × 53 月滚动窗口 = 254,222 观测值
**分析人**: 量化金融算法分析师

---

## 一、核心发现：引擎存在系统性相位偏差

### 1.1 相位分布严重失衡

| 相位 | 占比 | Wyckoff 理论预期 | 偏差 |
|------|------|-----------------|------|
| accumulation | **65.9%** | 应短暂，仅在吸筹完成后转为 markup | ❌ 严重偏多 |
| distribution | 17.1% | 应短暂，仅在派发完成后转为 markdown | ⚠️ 偏多 |
| unknown | 7.4% | 检测不出时合理 | 正常 |
| markdown | 6.0% | 应与 accumulation 对称 | ❌ 偏少 |
| markup | 3.6% | 应与 distribution 对称 | ❌ 严重偏少 |

**结论**: 引擎对 `accumulation` 存在 4-5 倍的过量判定，对 `markup` 存在 3-4 倍的漏判。

### 1.2 相位方向与理论矛盾

| 相位 | 6月均值收益 | Wyckoff 理论 | 方向 | 诊断 |
|------|-----------|-------------|------|------|
| accumulation | **+2.95%** | 上涨蓄力 → 应正收益 | ✅ | 正确方向，但被大量横盘期稀释 |
| markup | **-4.17%** | 主升段 → 应正收益 | ❌ | **完全反方向** — 检测到 markup 时已是顶部 |
| distribution | **-1.46%** | 下跌前兆 → 应负收益 | ✅ | 方向正确，但效应微弱 |
| markdown | **+3.45%** | 主跌段 → 应负收益 | ❌ | **完全反方向** — 检测到 markdown 时已是底部 |
| unknown | **-5.20%** | 无判断 → 应有信息 | ✅ | 未知检出的收益最差，说明引擎不做判断时反而风险最高 |

**根本矛盾**: markup 的收益最差（-4.17%），markdown 的收益最好（+3.45%）。**引擎的相位检测与价格走势完全反相位**。

### 1.3 信号阈值 Pareto 分析

| 信号级别 | 密度 | 3月收益均值 | 盈亏比 | 分析 |
|----------|------|-----------|--------|------|
| L1_strictest | 0.01% | -1.80% | 35.7% | 14 个信号，太罕见无意义 |
| L2_strict | 0.87% | -0.86% | 40.1% | 严格信号反而是负收益 |
| **L3_moderate** | **8.72%** | **+0.84%** | **44.2%** | **最佳信号密度比** |
| L4_loose | 0.80% | -2.98% | 36.9% | 宽松信号方向错误 |
| L5_noise | 2.65% | -0.49% | 41.2% | 噪声信号 |
| NoSignal | 86.97% | +0.53% | 44.4% | 无信号时反而好于严格信号 |

**结论**: 最严格的信号（L1+L2）收益为负，中等信号（L3）是唯一正向级别。**引擎的"最优信号"完全不可靠**。

---

## 二、根因分析：代码级问题溯源

### 2.1 P&F 相位覆盖层是偏见的首要来源

在 `engine.py:_step1_phase_determine` 中，P&F 提示优先于检测器链：

```python
if pnf_hint in ("accumulation", "distribution"):
    phase = ACCUMULATION if pnf_hint == "accumulation" else DISTRIBUTION
    # 检测器链结果被完全忽略，仅记录分歧
```

**P&F 积累条件**（`pnf.py:226-260`）过于宽松：
| 条件 | 阈值 | 宽松程度 |
|------|------|---------|
| `rising_lows_ratio > 0.5` | 50% | 横盘市场中极容易满足 |
| `range_contraction < 0.85` | 0.85 | 任何窄幅震荡都符合 |
| `recent_rising_lows > 0.4` | 40% | 后半段 40% 的低点抬高即可 |
| `avg_recent < avg_early * 0.9` | 0.90 | 近期波动轻微缩小即通过 |

**P&F 派发条件**（同样函数）更为严格：
| 条件 | 阈值 | 严格程度 |
|------|------|---------|
| `falling_highs_ratio > 0.3` | 30% | 需要主动高点降低 |
| `range_contraction > 1.2` | 1.20 | 需要范围扩张 > 20% |
| `down_ratio > 0.5` | 50% | 至少一半列是下降 |
| `avg_recent > avg_early * 1.1` | 1.10 | 需要近期波动明显放大 |

**不对称性**: 积累 4 项条件全为"宽松门槛"，派发 4 项条件全为"严格门槛"。在横盘震荡的 A 股市场中，积累条件比派发条件容易满足 4-5 倍。

### 2.2 检测器链积累后备方案过于宽松

当 P&F 返回 `"unknown"` 时，检测器链运行。`_detect_accumulation` 的第 3 条路径（TR 外）门槛极低：

```python
# 路径 C: TR 外
if (short_trend_pct <= -0.02          # 短期趋势 <= -2%
    and current_price < ma20           # 价格低于 MA20
    and ma5 <= ma20                    # MA5 低于 MA20
    and bc_sc_ok):                     # BC 或 SC 存在 → 返回 ACCUMULATION
```

这意味着：**任何股票只要短期下跌 > 2% 且低于 MA20，就会被判定为 accumulation**。这是 65.9% 积累率的根本原因。

### 2.3 Markup 检测延迟导致反向收益

`_detect_markup` 的 TR 外路径 1：
```python
if short_trend >= 0.03                # 短期已涨 3%+
    and (price > ma20 and ma5 >= ma20) # 价格在 MA20 以上
```

**问题**: markup 在价格已涨 3% 以上时才被确认。此时往往是短期顶部而非上涨起点。后续 6 月收益 -4.17% 是因为 markup 确认时已接近峰值。

### 2.4 Markdown 检测延迟导致反向收益

`_detect_markdown` 的 TR 外路径 1：
```python
if short_trend <= -0.05               # 短期已跌 5%+
    and price < ma20 * 0.95            # 价格在 MA20 以下 5%
```

**问题**: markdown 在价格已跌 5% 以上时才被确认。此时往往是短期底部而非下跌起点。后续 6 月收益 +3.45% 是因为 markdown 确认时已接近底部。

### 2.5 综合诊断：相位检测是"滞后确认"而非"预测"

```
真实市场周期: 底部 → 上涨 → 顶部 → 下跌 → 底部
                    |        |        |        |
引擎检测相位:   accumulation  markup  distribution  markdown
                    ↑        ↑        ↑        ↑
                    |        |        |        |
检测触发点:   已跌2%+  已涨3%+  已跌2%+  已跌5%+
              (抄底)  (追高)  (逃顶)  (杀跌)
```

**所有相位检测都是滞后确认**，而非前瞻预测。因此引擎收益方向与 Wyckoff 理论完全相反。

---

## 三、对齐方案

### 3.1 Phase 0: 修复 P&F 积累/派发不对称（高优先级）

**目标**: 消除 P&F 覆盖层对积累的过量偏好

**改动 1: 对称化 P&F 积累条件** (`pnf.py:wyckoff_phase_hint`)

```python
# 当前 (过松):
# rising_lows_ratio > 0.5 AND range_contraction < 0.85
#     AND recent_rising_lows > 0.4 AND avg_recent < avg_early * 0.9

# 改为 (对称化):
# 积累: rising_lows_ratio > 0.6 (收紧) AND range_contraction < 0.80 (收紧)
#        AND recent_rising_lows > 0.5 (收紧) AND avg_recent < avg_early * 0.85 (收紧)
#        AND down_ratio < 0.4 (新增: 下降列比例不能太高)
# 派发: falling_highs_ratio > 0.35 (放宽) OR range_contraction > 1.15 (放宽)
#        AND down_ratio > 0.45 (放宽) OR avg_recent > avg_early * 1.05 (放宽)
```

**改动 2: P&F 覆盖层降级为"加权提示"** (`engine.py:_step1_phase_determine`)

```python
# 当前: P&F hint 直接覆盖检测器链
# 改为: P&F hint 作为检测器链的额外输入，不覆盖
#   - 如果 P&F hint == "accumulation": 检测器链的accumulation阈值降低50%
#   - 如果 P&F hint == "distribution": 检测器链的distribution阈值降低50%
#   - 检测器链的最终结果保持为唯一相位来源
```

### 3.2 Phase 1: 重构积累检测器（高优先级）

**目标**: 将 accumulation 从 65.9% 降至 25-30%

**改动 1: 收紧积累路径 C（TR 外）** (`engine.py:_detect_accumulation`)

```python
# 当前: short_trend <= -2% + price < MA20 + MA5 <= MA20 + BC/SC
# 改为: short_trend <= -5% (收紧) + price < MA20 * 0.95 (收紧)
#        + MA5 <= MA20 * 0.98 (收紧) + BC AND SC 必须同时存在 (收紧)
#        + volume_ratio < 0.8 (新增: 缩量确认)
```

**改动 2: 收紧积累路径 B（TR 内）** (`engine.py:_detect_accumulation`)

```python
# 当前: prior_trend < -3% → ACCUMULATION (太松)
# 改为: prior_trend < -5% AND price < MA20 AND MA5 < MA20 (收紧)
#        + duration_in_tr > 20天 (新增: TR内横盘20天以上)
```

**改动 3: 新增积累拒绝条件** (`engine.py:_detect_accumulation`)

```python
# 新增拒绝条件:
#   - 如果 MA5 > MA20: 拒绝积累（短期趋势已向上）
#   - 如果 volume_20ma > volume_60ma * 1.2: 拒绝积累（放量异常）
#   - 如果 relative_position > 0.60: 拒绝积累（价格在TR高位）
```

### 3.3 Phase 2: 将 Markup/Markdown 改为前瞻检测（高优先级）

**目标**: 将 markup 和 markdown 从"滞后确认"改为"早期识别"

**改动 1: 新增 markup 早期信号** (`engine.py:_detect_markup`)

```python
# 新增路径 0: 积累转 markup 的早期信号
#   - 之前相位是 accumulation
#   - 当前: short_trend > 0% (非负即可，非 3%)
#   - price > MA20 (价格刚站上均线)
#   - volume > MA20 * 1.2 (放量突破)
#   - relative_position > 0.30 (从 TR 低位起来)
#   - 这捕获从 accumulation 到 markup 的转换点
```

**改动 2: 新增 markdown 早期信号** (`engine.py:_detect_markdown`)

```python
# 新增路径 0: 派发转 markdown 的早期信号
#   - 之前相位是 distribution
#   - 当前: short_trend < 0% (非正即可)
#   - price < MA20 (价格刚跌破均线)
#   - MA5 < MA20 (短期均线死叉)
#   - 这捕获从 distribution 到 markdown 的转换点
```

**改动 3: 降低 markup 现有路径门槛** (`engine.py:_detect_markup`)

```python
# TR 外路径 1: short_trend >= 0.03 → 改为 0.01 (提前)
# TR 外路径 2: short_trend >= 0.015, rp >= 0.70 → 改为 rp >= 0.50 (放宽)
# 新增: 如果 event_sequence 包含 SOS → 直接返回 MARKUP
```

### 3.4 Phase 3: 引入相位转换检测（中优先级）

**目标**: 利用相位转换信息增强预测力（当前 H5 不支持）

**改动 1**: 在 `_step1_phase_determine` 中引入转换检测

```python
# 新增参数: previous_phase (从历史状态获取)
# 如果 previous_phase != current_phase:
#   - transition_type = f"{previous_phase}→{current_phase}"
#   - 在 confidence 计算中增加转换加分
#   - accumulation→markup: +1 信心
#   - distribution→markdown: +1 信心
#   - markdown→accumulation: +0.5 信心
```

**改动 2**: 在 `RollingObs.with_history` 中验证转换方向

数据验证:
- distribution→accumulation: **+2.76%** 最佳转换收益 ✅
- 应优先使用此转换作为信号
- markdown→markup: **+3.14%** 但仅 27 个样本 ⚠️ 需更多数据

### 3.5 Phase 4: 优化置信度计算（中优先级）

**目标**: 使置信度与真实收益正相关

**当前问题**: L1_strictest 信号收益为负 (-1.80%)，L3_moderate 收益为正 (+0.84%)。置信度越高收益越差。

**改动**: 将置信度分为"方向置信度"和"价格位置置信度"

```python
# 方向置信度: 基于相位方向正确性
#   - accumulation: 如果 price < MA20 → 高置信度
#   - markup: 如果 price 刚突破 MA20 → 高置信度
#   - distribution: 如果 price > MA20 → 高置信度
#   - markdown: 如果 price 刚跌破 MA20 → 高置信度

# 价格位置置信度: 基于价格在相位中的位置
#   - 如果相位已持续 4-6 月 → 最高置信度 (H6 验证)
#   - 如果相位已持续 > 12 月 → 降级 (过久失效)
```

### 3.6 Phase 5: 降低换手率优化策略（低优先级）

**当前问题**: 策略毛收益 +1.04%/mo 超过 BH 的 +0.81%/mo，但年化换手成本 6.67%/月导致净收益 -50.1%。

**改动**:
1. 仅在相位转换时调仓（非每月调仓）
2. 使用 `transition_type` 作为调仓信号
3. 预期换手率可从 2.4%/月降至 0.5%/月

---

## 四、预期效果

| 指标 | 当前 | 修复后预期 | 验证方法 |
|------|------|-----------|---------|
| accumulation 占比 | 65.9% | 25-30% | 全量扫描 |
| markup 占比 | 3.6% | 15-20% | 全量扫描 |
| markup 收益方向 | -4.17% ❌ | +5~10% ✅ | 全量扫描 |
| markdown 收益方向 | +3.45% ❌ | -3~-8% ✅ | 全量扫描 |
| H1 ANOVA p值 | 0.0000 | 0.0000 | 不变 |
| H3 单调性 | ❌ | ✅ | 一致性层次验证 |
| H5 转换预测 | ❌ | ✅ | 分布→积累转换验证 |
| H7 策略净收益 | -50.1% | +5~15% | 考虑换手成本的回测 |
| 置信度收益关系 | 反向 | 正向 | 信号级别验证 |

---

## 五、实施路径

### 第 1 步: P&F 对称化 + 积累收紧（2 天）
- 修改 `pnf.py:wyckoff_phase_hint` 阈值
- 修改 `engine.py:_detect_accumulation` 收紧条件
- 运行 1000 只验证扫描，确认积累率降至 30% 以下

### 第 2 步: Markup/Markdown 前瞻化（2 天）
- 新增早期信号路径
- 降低现有路径门槛
- 运行全量验证，确认方向正确

### 第 3 步: 相位转换检测（1 天）
- 引入 previous_phase 参数
- 验证转换收益预测力

### 第 4 步: 置信度优化（1 天）
- 重写置信度计算
- 验证信号级别与收益正相关

### 第 5 步: 策略调仓优化（1 天）
- 改为转换驱动调仓
- 验证换手率降至 0.5%/月以下