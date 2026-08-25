# Wyckoff 相位再平衡 — 最终方案 v3.0

**基于 52,586 观测值（1,000 只 A 股 × 53 月）实证验证**
**分析日期**: 2026-08-06
**前置文档**: WYCKOFF_V3_FULL_SCAN_ANALYSIS.md (原始诊断), WYCKOFF_PHASE_REBALANCE_REDBLUE.md (v1 红蓝对抗), WYCKOFF_PHASE_REBALANCE_IMPLEMENTATION_PLAN_v2.md (v2 修正方案)

---

## 目录

1. [三轮红蓝对抗总结](#1-三轮红蓝对抗总结)
2. [实证基准（52K 观测）](#2-实证基准52k-观测)
3. [修正方案总览](#3-修正方案总览)
4. [Phase 0: 唯一有效的修复 — P&F 覆盖层移除](#4-phase-0-唯一有效的修复--pf-覆盖层移除)
5. [Phase 1: Markdown 检测器重构 — 相对位置约束](#5-phase-1-markdown-检测器重构--相对位置约束)
6. [Phase 2: 市场状态自适应检测](#6-phase-2-市场状态自适应检测)
7. [Phase 3: 相位转换检测](#7-phase-3-相位转换检测)
8. [Phase 4: 置信度重算](#8-phase-4-置信度重算)
9. [Phase 5: 调仓策略优化](#9-phase-5-调仓策略优化)
10. [验证方法论](#10-验证方法论)
11. [回滚方案](#11-回滚方案)
12. [附录: 文件修改清单](#12-附录-文件修改清单)

---

## 1. 三轮红蓝对抗总结

### Round 1: 原始方案 v1 评审

| 议题 | 红队论点 | 蓝队论点 | 实证裁决 | 对 v3.0 的影响 |
|------|---------|---------|---------|---------------|
| P&F 阈值过紧 | 0.6/0.80 等阈值 kill P&F | 理论推导合理 | 红队胜: 99.9% unknown | 放弃阈值修改，仅保留覆盖层移除 |
| Phase 1 收紧积累 | 积累检测器已太紧 | 65.9% 积累证明过松 | 红队胜: 链式积累仅 0.4% | Phase 1 改为放松积累 |
| 方向反转修复 | 反转是结构性问题 | 检测滞后可修复 | 红队胜: 方向反转持续 | 重新设计 Phase 2 |

### Round 2: 修正方案 v2 评审（基于 52K 观测）

| 议题 | 红队论点 | 蓝队论点 | 实证裁决 | 对 v3.0 的影响 |
|------|---------|---------|---------|---------------|
| P&F 校准阈值 | 0.55/0.83 等仍过紧 | 理论校准合理 | 红队胜: 所有候选阈值 0% accum | 放弃所有 P&F 阈值修改 |
| Phase 1 accum 放松 | 44% 触发率过高 | 放松即可 | 红队胜: 44% 远超目标 10-15% | 需要更保守的阈值 |
| Phase 1 markdown 收紧 | 38.4% 仍过高 | 放量确认有效 | 红队胜: 放量确认后仍 38.4% | 需要相对位置约束 |
| Phase 1 markup 放松 | 早期 markup 收益负 | 检测提前即可 | 红队胜: 早期 markup 收益 -1.65% | 无法简单修复，需要市场状态感知 |
| 方向反转 | 时段依赖性强 | 结构性可修复 | 蓝队部分胜: 反转在 ALL 时段存在 | 需要市场状态自适应检测 |

### Round 3: 关键发现

| 发现 | 证据 | 对方案的影响 |
|------|------|-------------|
| P&F 阈值修改完全不需要 | 当前阈值 63/23/14 分布合理，问题在覆盖层 | 删除 Phase 0 阈值修改 |
| Markdown 检测器是最大问题 | 链式 46.4%，需要 rp 约束 + 市场状态感知 | Phase 1 重写 |
| 方向反转在 ALL 时段存在 | 2020-2021 牛: markup +0.51%, md +6.26% | 结构性问题，需市场状态检测 |
| 早期 markup 检测无效 | 早期候选收益 +0.65% (p=0.22) | 需市场状态感知，非简单门槛降低 |
| Markdown 具有双峰特征 | rp<0.15: +3.18%, rp>0.50: -6.23% | 需 rp 约束过滤均值回复 |

---

## 2. 实证基准（52K 观测）

### 当前引擎状态

| 指标 | 当前值 | 问题 |
|------|-------|------|
| accumulation 占比 | 63.2% | ❌ 严重偏多（P&F 覆盖层导致） |
| markup 占比 | 3.0% | ❌ 严重偏少 |
| distribution 占比 | 22.5% | ⚠️ 偏多 |
| markdown 占比 | 7.1% | ❌ 偏少 |
| unknown 占比 | 4.2% | ❌ 偏少 |

### 覆盖层移除后（链式引擎）

| 指标 | 当前值 | 目标 | 问题 |
|------|-------|------|------|
| accumulation 占比 | 0.6% | 10-15% | ❌ 过少 |
| markup 占比 | 16.0% | 15-20% | ✅ 合理 |
| distribution 占比 | 12.0% | 10-15% | ✅ 合理 |
| markdown 占比 | 46.4% | 15-25% | ❌ 过多 |
| unknown 占比 | 24.9% | 25-40% | ✅ 合理 |

### 方向反转（链式引擎）

| 相位 | 3m 收益 | 理论方向 | 诊断 |
|------|--------|---------|------|
| accumulation | +1.78% | 正收益 ✅ | 正确 |
| markup | **-1.64%** | 正收益 ✅ | ❌ **反方向** |
| distribution | +1.40% | 负收益 ❌ | ⚠️ 方向错误 |
| markdown | **+2.27%** | 负收益 ❌ | ❌ **反方向** |

### 时段分析（链式引擎）

| 时段 | markup 收益 | markdown 收益 | 诊断 |
|------|------------|--------------|------|
| 2020-2021 (牛市) | +0.51% (p=0.21) | +6.26% (p=0.00) | markdown 强烈均值回复 |
| 2022-2023 (熊市) | -4.23% (p=0.00) | +0.15% (p=0.52) | markup 追高被套 |
| 2024 (熊市) | -5.90% (p=0.00) | -6.55% (p=0.00) | 双负 — 系统性熊市 |

---

## 3. 修正方案总览

### 3.1 核心发现

1. **P&F 覆盖层移除是唯一有效的修复** — 积累 63.2% → 0.6%。P&F 阈值本身不需要修改（当前阈值 63/23/14 分布合理，问题仅在覆盖层）。
2. **Markdown 检测器是最大问题** — 链式 46.4%，因 `short_trend <= -5% AND price < MA20*0.95` 在月线中过于宽松。需要 `relative_position` 约束（rp>0.30 才触发）。
3. **方向反转是结构性的且时段依赖** — 非简单阈值调整可修复。需要市场状态感知（牛市/熊市/震荡）。
4. **早期 markup 检测无效** — 短趋势 > 0.005 的早期候选收益 +0.65% (p=0.22)，不显著为正。市场状态感知是唯一出路。

### 3.2 实现顺序

```
Phase 0: 移除 P&F 覆盖层                  ← 唯一高置信度修复
    ↓
Phase 1: Markdown 检测器重构 + rp 约束     ← 降低 46.4% → 15-25%
    ↓
Phase 2: 市场状态自适应检测                 ← 修复方向反转
    ├── 2a: 引入市场状态检测器
    ├── 2b: Markup 仅在牛市/震荡中触发
    └── 2c: Markdown 仅在熊市/震荡中触发
    ↓
Phase 3: 相位转换检测                      ← 利用时序信息
    ↓
Phase 4: 置信度重算 + 调仓优化             ← 最终策略优化
```

### 3.3 预期指标变化

| 指标 | 当前 | Phase 0 | Phase 1 | Phase 2 | Phase 3-4 | 最终目标 |
|------|------|---------|---------|---------|-----------|---------|
| accum 占比 | 63.2% | 0.6% | 3-5% | 5-10% | 8-12% | ~10% |
| markup 占比 | 3.0% | 16.0% | 16-18% | 12-18% | 15-20% | ~18% |
| distribution 占比 | 22.5% | 12.0% | 8-12% | 8-12% | 10-15% | ~12% |
| markdown 占比 | 7.1% | 46.4% | 15-25% | 12-20% | 15-25% | ~20% |
| unknown 占比 | 4.2% | 24.9% | 40-55% | 40-55% | 25-40% | ~38% |
| markup 3m 收益 | -0.84% | -1.64% | -1~+1% | +1~3% | +2~5% | +2~5% |
| markdown 3m 收益 | +1.67% | +2.27% | +1~-1% | -1~-3% | -2~-5% | -2~-5% |

---

## 4. Phase 0: 唯一有效的修复 — P&F 覆盖层移除

### 4.1 问题诊断

P&F 覆盖层是积累偏见的绝对主导因素:
- 83.8% 的观测中 P&F 可覆盖（返回 "accumulation" 或 "distribution"）
- 98.1% 的覆盖与检测器链分歧
- 覆盖层移除后积累从 63.2% 降至 0.6%
- **P&F 阈值本身不需要修改**（当前阈值 63/23/14 分布合理）

### 4.2 代码修改

#### 修改 1: 移除 P&F 覆盖层

**文件**: `src/uniquant/brain/wyckoff/engine.py`, 函数 `_step1_phase_determine`（第 836-849 行）

```python
# ── 改为 ──
# P&F hint 不再覆盖检测器链，改为仅记录分歧
# 检测器链的最终结果保持为唯一相位来源
if pnf_hint in ("accumulation", "distribution"):
    if chain_phase != phase_or_chain_phase:
        pnf_phase_divergence = (
            f"PnF={pnf_hint}, DetectorChain={chain_phase.value}"
        )
    else:
        pnf_phase_divergence = (
            f"PnF={pnf_hint}, DetectorChain={chain_phase.value} (aligned)"
        )
phase = chain_phase
unknown_candidate = chain_unknown_candidate
```

**注意**: 与 v1/v2 方案不同，**不做任何 P&F 阈值修改**。当前阈值 63/23/14 分布合理。

### 4.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_pnf_no_override` | 新测试 | P&F hint 不再覆盖检测器链 |
| `test_pnf_thresholds_unchanged` | 新测试 | P&F 阈值未修改 |
| 现有 132 个测试 | 回归 | 预期大部分失败，需更新 |

### 4.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p0_v3

预期:
  accumulation 占比: 63.2% → 0.6%    (覆盖层移除)
  markdown 占比: 7.1% → 46.4%       (待 Phase 1 修复)
  markup 占比: 3.0% → 16.0%         (链式结果)
  P&F 分歧率: 0% → 80%+             (P&F 不再覆盖)
```

---

## 5. Phase 1: Markdown 检测器重构 — 相对位置约束

### 5.1 问题诊断

覆盖层移除后，markdown 检测器过度触发（46.4%）。根因是路径 1（TR 外）的 `short_trend <= -5% AND price < MA20*0.95` 在月线中过于宽松。

**Markdown 方向分析**:
| relative_position | 3m 收益 | 诊断 |
|-------------------|---------|------|
| 0.00-0.15 (低位) | +3.18% | 均值回复 — 伪标记 |
| 0.15-0.30 | -0.13% | 中性 |
| 0.30-0.50 | -2.44% | 真正的下跌趋势 |
| 0.50-1.00 (高位) | -6.23% | 强烈的下跌趋势 |

**结论**: 添加 `rp >= 0.20` 约束可过滤大部分均值回复伪标记。

### 5.2 代码修改

#### 修改 1: Markdown 路径 1 添加 rp 约束

**文件**: `src/uniquant/brain/wyckoff/engine.py`, 函数 `_detect_markdown`（第 656 行）

```python
# ── 当前代码 ──
if st <= st_max and cp < ma20 * cp_below_ma:
    return {"phase": WyckoffPhase.MARKDOWN}

# ── 改为 ──
if st <= st_max and cp < ma20 * cp_below_ma:
    # 新增 rp 约束: 过滤均值回复
    if ctx["relative_position"] >= 0.20:  # 不在极度低位
        # 新增放量确认
        if len(df) >= 5:
            vol_5 = float(df.tail(5)["volume"].mean())
            vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
            if vol_20 > 0 and vol_5 > vol_20 * 1.1:
                return {"phase": WyckoffPhase.MARKDOWN}
```

#### 修改 2: Markdown 路径 2/3 添加 rp 约束

```python
# 路径 2 (BC 跌破)
if (
    rule0.bc_found and rule0.bc_position is not None
    and cp <= rule0.bc_position.price * 0.85  # 从 0.90 收紧
    and cp < ma20 and ma5 <= ma20 and st <= -0.02
    and ctx["relative_position"] >= 0.15  # 新增 rp 约束
):
    return {"phase": WyckoffPhase.MARKDOWN}

# 路径 3 (深跌)
if (
    rule0.bc_found and rule0.bc_position is not None
    and st <= -0.04 and rp <= 0.25
    and cp <= rule0.bc_position.price * 0.75
):
    # 路径 3 在 rp<=0.25 时触发，但 rp 约束不适用
    # 改为: 仅在 rp>=0.15 时触发（过滤均值回复）
    if ctx["relative_position"] >= 0.15:
        return {"phase": WyckoffPhase.MARKDOWN}
```

### 5.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_markdown_rp_constraint` | 新测试 | rp<0.20 时 markdown 不触发 |
| `test_markdown_volume_confirmation` | 新测试 | 需要放量确认 |
| `test_markdown_bc_path_tightened` | 新测试 | BC 跌破门槛从 0.90 收紧到 0.85 |
| 现有 markdown 测试 | 回归 | 更新 |

### 5.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p1_v3

预期:
  markdown 占比: 46.4% → 15-25%    (rp 约束过滤均值回复)
  unknown 占比: 24.9% → 40-55%     (更多观测归入 unknown)
  markup 占比: 16.0% → 16-18%      (维持)
  markdown 3m 收益: 改善方向
```

---

## 6. Phase 2: 市场状态自适应检测

### 6.1 问题诊断

方向反转是结构性的且时段依赖。Markup 收益在牛市 +0.51%、熊市 -4.23%。简单降低门槛无法修复，因为早期 markup 候选收益仅 +0.65% (p=0.22)。

**修复方向**: 引入市场状态检测器，使 markup/markdown 的状态条件依赖于市场状态:
- 牛市: markup 置信度提高，markdown 置信度降低
- 熊市: markdown 置信度提高，markup 置信度降低
- 震荡: 维持当前行为

### 6.2 代码修改

#### 修改 1: 引入市场状态检测器

**文件**: 新增 `src/uniquant/brain/wyckoff/market_state.py`

```python
from enum import Enum
import numpy as np
import pandas as pd


class MarketState(Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


def detect_market_state(index_df: pd.DataFrame, lookback_months: int = 12) -> MarketState:
    """检测市场状态。

    基于沪深 300 指数的月线 MA 趋势 + 波动率。
    """
    if index_df is None or len(index_df) < lookback_months:
        return MarketState.NEUTRAL

    df = index_df.tail(lookback_months)
    closes = df["close"].values
    ma6 = np.mean(closes[-6:]) if len(closes) >= 6 else np.mean(closes)
    ma12 = np.mean(closes)

    if ma6 > ma12 * 1.05:
        return MarketState.BULL
    elif ma6 < ma12 * 0.95:
        return MarketState.BEAR
    else:
        return MarketState.NEUTRAL
```

#### 修改 2: Markup 检测器添加市场状态感知

**文件**: `src/uniquant/brain/wyckoff/engine.py`, 函数 `_detect_markup`

```python
# 在 _detect_markup 开始处添加市场状态检查
def _detect_markup(self, df, ctx, rule0, market_state=None):
    # 在熊市中，markup 需要更强的证据
    if market_state == MarketState.BEAR:
        # 熊市: 需要短期趋势 ≥ 3% + 价格显著高于 MA20
        if ctx["short_trend_pct"] < 0.03:
            return None
        if ctx["current_price"] < ctx["ma20"] * 1.02:
            return None
    # 牛市中，markup 正常触发
    # 震荡中，markup 正常触发
    # ... 现有检测逻辑 ...
```

#### 修改 3: Markdown 检测器添加市场状态感知

```python
def _detect_markdown(self, df, ctx, rule0, market_state=None):
    # 在牛市中，markdown 需要更强的证据
    if market_state == MarketState.BULL:
        # 牛市: 需要短期趋势 < -5% + 价格显著低于 MA20
        if ctx["short_trend_pct"] > -0.05:
            return None
        if ctx["current_price"] > ctx["ma20"] * 0.95:
            return None
    # 熊市中，markdown 正常触发
    # 震荡中，markdown 正常触发
    # ... 现有检测逻辑 ...
```

### 6.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_market_state_bull` | 新测试 | 牛市检测器正确定位 |
| `test_market_state_bear` | 新测试 | 熊市检测器正确定位 |
| `test_markup_bull_market` | 新测试 | 牛市中 markup 正常触发 |
| `test_markup_bear_market` | 新测试 | 熊市中 markup 需要更强证据 |
| `test_markdown_bull_market` | 新测试 | 牛市中 markdown 需要更强证据 |

### 6.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p2_v3

预期:
  markup 3m 收益: -1.64% → +1~3%    (牛市 markup 增加，熊市过滤)
  markdown 3m 收益: +2.27% → -1~-3% (熊市 markdown 增加，牛市过滤)
  markup 占比: 16-18% → 12-18%     (熊市减少)
  markdown 占比: 15-25% → 12-20%   (牛市减少)
```

---

## 7. Phase 3: 相位转换检测

### 7.1 问题诊断

当前引擎每个 cutoff 独立判定相位，不参考历史状态。H5 验证显示转换不增加预测力。

### 7.2 代码修改

#### 修改 1: 在 `_analyze_single` 中传入 previous_phase

**文件**: `src/uniquant/brain/wyckoff/engine.py`, 函数 `_analyze_single`

```python
def _analyze_single(
    self, df, symbol="", period="", pnf_engine=None,
    previous_phase: Optional[str] = None,  # 新增
) -> WyckoffReport:
```

#### 修改 2: 在 `Step1Result` 中增加 transition 字段

```python
@dataclass
class Step1Result:
    phase: WyckoffPhase
    # ... 现有字段 ...
    transition: Optional[str] = None
    transition_confidence: float = 0.0
```

### 7.3 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p3_v3

预期:
  H5 转换预测: ❌ → ✅ (p < 0.05)
  distribution→accumulation 转换收益: 维持或提升
```

---

## 8. Phase 4: 置信度重算

### 8.1 问题诊断

当前置信度规则与真实收益负相关。L1_strictest 收益 -1.80%，L3_moderate 收益 +0.84%。

### 8.2 代码修改

#### 修改 1: 新增位置 + 市场状态置信度

**文件**: `src/uniquant/brain/wyckoff/engine.py`

```python
def _compute_position_confidence(self, phase, ctx, market_state=None):
    confidence = 0.5
    base = 0.3

    if phase == WyckoffPhase.MARKUP:
        # 牛市: 高置信度，熊市: 低置信度
        if market_state == MarketState.BULL:
            confidence += base
        elif market_state == MarketState.BEAR:
            confidence -= base * 0.5
        # 位置加成
        if ctx["relative_position"] <= 0.60:
            confidence += 0.2
    elif phase == WyckoffPhase.MARKDOWN:
        # 熊市: 高置信度，牛市: 低置信度
        if market_state == MarketState.BEAR:
            confidence += base
        elif market_state == MarketState.BULL:
            confidence -= base * 0.5
        # 位置约束
        if ctx["relative_position"] >= 0.40:
            confidence += 0.2

    return max(0.0, min(1.0, confidence))
```

### 8.3 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p4_v3

预期:
  置信度与收益: 负相关 → 正相关
  L1_strictest 收益: -1.80% → +2~4%
  L3_moderate 收益: +0.84% → +2~4%
```

---

## 9. Phase 5: 调仓策略优化

### 9.1 问题诊断

当前 H7 策略每月调仓，换手率 2.4%/月，年化成本 6.67%/月，净收益 -50.1%。

### 9.2 代码修改

**文件**: `scripts/wyckoff_multitf/runner_v3.py`, 函数 `test_h7_backtest`

```python
# ── 改为 ──
# 仅在相位转换时调仓
in_strategy = [
    o for o in at_cutoff
    if o.month_phase in ("accumulation", "markup")
    and o.had_transition
]
```

### 9.3 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| 换手率 | 2.4%/月 | 0.3-0.5%/月 |
| 年化成本 | 6.67%/月 | 0.8-1.5%/月 |
| 策略净收益 | -50.1% | +5~15% |

---

## 10. 验证方法论

### 10.1 3-way 数据分割

| 数据集 | 时间范围 | 用途 |
|--------|---------|------|
| 训练集 | 2020-01 至 2021-12 | 阈值搜索 |
| 验证集 | 2022-01 至 2023-12 | 阈值选择 |
| 测试集 | 2024-01 至 2024-06 | 最终报告 |

### 10.2 验证流程

```
每次修改后:
  1. ruff check src/ tests/ scripts/    (0 容忍)
  2. pytest tests/classic_wyckoff/ -q   (更新后全部通过)
  3. python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _verify
     (~10 分钟，验证相位分布和收益方向)
  4. 对比预期 vs 实际（bootstrap 95% CI 范围）
  5. 偏差超出 CI 则回滚
```

### 10.3 关键指标监控

| 指标 | 目标范围 | 通过条件 |
|------|---------|---------|
| accumulation 占比 | 8-12% | bootstrap 95% CI 在此范围内 |
| markup 占比 | 15-20% | bootstrap 95% CI 在此范围内 |
| distribution 占比 | 10-15% | bootstrap 95% CI 在此范围内 |
| markdown 占比 | 15-25% | bootstrap 95% CI 在此范围内 |
| markup 3m 收益 | > 0% | t-test p < 0.05 为正 |
| markdown 3m 收益 | < 0% | t-test p < 0.05 为负 |
| 现有测试 | 100% | 全部通过 |
| ruff | 0 | 0 错误 |

---

## 11. 回滚方案

### 11.1 逐文件回滚

每个修改独立 commit，可按 commit 回滚：

```bash
git revert <commit_p0_v3>
# 或
git checkout <commit_before_p0_v3> -- src/uniquant/brain/wyckoff/engine.py
```

### 11.2 配置开关

```yaml
wyckoff:
  calibration_v3:
    enabled: false                      # 关闭所有 v3 修改
    pnf_override_removed: true          # Phase 0: 覆盖层移除
    markdown_rp_constraint: false       # Phase 1: 相对位置约束
    market_state_adaptive: false        # Phase 2: 市场状态自适应
    transition_detection: false         # Phase 3: 转换检测
    position_confidence: false          # Phase 4: 位置置信度
```

---

## 12. 附录: 文件修改清单

| 文件 | 修改函数 | 修改类型 | 影响范围 |
|------|---------|---------|---------|
| `engine.py` | `_step1_phase_determine` | P&F 覆盖逻辑移除 | Phase 0 |
| `engine.py` | `_detect_markdown` | 添加 rp 约束 + 放量确认 | Phase 1 |
| `engine.py` | `_detect_markup` | 添加 market_state 参数 | Phase 2 |
| `engine.py` | `_detect_markdown` | 添加 market_state 参数 | Phase 2 |
| `market_state.py` | `detect_market_state` | 新增文件 | Phase 2 |
| `engine.py` | `_analyze_single` | 传入 previous_phase | Phase 3 |
| `engine.py` | `Step1Result` | 增加 transition 字段 | Phase 3 |
| `engine.py` | 置信度函数 | 市场状态感知置信度 | Phase 4 |
| `runner_v3.py` | `test_h7_backtest` | 转换驱动调仓 | Phase 5 |

## 附录 B: 验证脚本

| 脚本 | 功能 | 输入 |
|------|------|------|
| `v9_v2_medium_validation.py` | 52K 观测全面验证 | `--max-stocks 1000` |
| `v9_v2_diagnostic.py` | 方向反转深度诊断 | 加载保存的 JSON |
| `v9_rb_validation.py` | 原始 monkeypatch 反事实 | `--max-stocks 500` |

验证数据: `scripts/wyckoff_multitf/output_v2_validation/v2_medium_rows.json` (52,586 观测)