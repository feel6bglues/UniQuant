# Wyckoff 相位再平衡 — 修正方案 v2.0

**基于 27,424 观测值红蓝对抗验证的代码级修复方案**
**分析日期**: 2026-08-06
**前置文档**: `WYCKOFF_V3_FULL_SCAN_ANALYSIS.md` (原始诊断), `WYCKOFF_PHASE_REBALANCE_REDBLUE.md` (红蓝对抗评审)

---

## 目录

1. [原始方案缺陷总结](#1-原始方案缺陷总结)
2. [修正方案总览](#2-修正方案总览)
3. [Phase 0: P&F 覆盖层移除 + 阈值校准](#3-phase-0-pf-覆盖层移除--阈值校准)
4. [Phase 1: 检测器链重新平衡](#4-phase-1-检测器链重新平衡)
5. [Phase 2: 方向反转修复 — 预测性检测](#5-phase-2-方向反转修复--预测性检测)
6. [Phase 3: 相位转换检测](#6-phase-3-相位转换检测)
7. [Phase 4: 置信度重算](#7-phase-4-置信度重算)
8. [Phase 5: 调仓策略优化](#8-phase-5-调仓策略优化)
9. [验证方法论](#9-验证方法论)
10. [回滚方案](#10-回滚方案)
11. [附录: 文件修改清单](#11-附录-文件修改清单)

---

## 1. 原始方案缺陷总结

红蓝对抗实证验证发现原始方案存在 3 个致命缺陷:

| 缺陷 | 原始方案 | 实证发现 | 裁决 |
|------|---------|---------|------|
| P&F 新阈值过紧 | 积累 0.60/0.80/0.50/0.85 | 99.9% 返回 unknown → P&F 死亡 | ❌ 拒绝 |
| Phase 1 收紧积累 | 积累从 65.9% → 25-30% | 链式积累已仅 0.4%，再收紧=0 | ❌ 方向错误 |
| Phase 2 放宽 markdown | 门槛从 -5% 改 -2.5% | 链式 markdown 已 47.7%，再放宽=60%+ | ❌ 方向错误 |

**唯一保留的修复**: Phase 0 修改 2 — 移除 P&F 覆盖层（积累 65.4% → 0.4%）

### 实证基准（500 只 × 53 月 = 27,424 观测值）

| 指标 | 当前引擎 | 覆盖层移除后 | 理论目标 |
|------|---------|------------|---------|
| accumulation 占比 | 65.4% | 0.4% | 10-15% |
| markup 占比 | 3.3% | 16.0% | 15-20% |
| distribution 占比 | 20.4% | 11.1% | 10-15% |
| markdown 占比 | 6.8% | 47.7% | 15-25% |
| unknown 占比 | 4.1% | 24.8% | 25-40% |
| markup 3m 收益 | -0.84% | -1.52% | +2~5% |
| markdown 3m 收益 | +1.67% | +2.25% | -2~-5% |
| accumulation 3m 收益 | +1.54% | +3.62% | +3~6% |

---

## 2. 修正方案总览

### 2.1 核心原则

1. **数据驱动阈值**: 所有阈值基于 3-way 数据分割（训练/验证/测试），非理论推导
2. **分步验证**: 每个修改独立测试，使用 bootstrap 95% CI 报告效果
3. **可逆设计**: 所有阈值在 calibration 字典中配置
4. **保守原则**: 先移除覆盖层 → 再诊断 → 再调整，不自上而下指定阈值

### 2.2 实现顺序

```
Phase 0 (覆盖层移除 + 阈值校准) → 测试 → 1000 只验证
    ↓
Phase 1 (检测器链重新平衡)
    ├── 1a: 放松积累检测器 (0.4% → 10-15%)
    ├── 1b: 收紧 markdown 检测器 (47.7% → 15-25%)
    └── 1c: 放宽 markup 检测器 (16% → 15-20%, 收益改善)
    ↓
Phase 2 (方向反转修复 — 预测性检测)
    ├── 2a: 引入积累→markup 转换检测
    └── 2b: 引入分布→markdown 转换检测
    ↓
Phase 3 (相位转换检测 + 置信度重算)
    ↓
Phase 4 (调仓策略优化)
```

### 2.3 预期指标变化（修订版）

| 指标 | 当前 | Phase 0 | Phase 1 | Phase 2 | Phase 3-4 | 最终目标 |
|------|------|---------|---------|---------|-----------|---------|
| accum 占比 | 65.4% | 0.4% | 8-15% | 8-15% | 10-15% | ~12% |
| markup 占比 | 3.3% | 16.0% | 15-20% | 15-20% | 15-20% | ~18% |
| distribution 占比 | 20.4% | 11.1% | 10-15% | 10-15% | 10-15% | ~12% |
| markdown 占比 | 6.8% | 47.7% | 15-25% | 15-25% | 15-25% | ~20% |
| unknown 占比 | 4.1% | 24.8% | 25-40% | 25-40% | 25-40% | ~38% |
| markup 3m 收益 | -0.84% | -1.52% | -1~+1% | +1~3% | +2~5% | +2~5% |
| markdown 3m 收益 | +1.67% | +2.25% | +1~-1% | -1~-3% | -2~-5% | -2~-5% |
| accum 3m 收益 | +1.54% | +3.62% | +2~5% | +3~6% | +3~6% | +3~6% |
| H1 ANOVA p值 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| H3 单调性 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| H5 转换预测 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

---

## 3. Phase 0: P&F 覆盖层移除 + 阈值校准

### 3.1 问题诊断

P&F 覆盖层是积累偏见的绝对主导因素:
- P&F 提示分布: 65.4% 积累, 18.4% 分布, 16.2% unknown
- 覆盖层移除后积累降至 0.4%
- 83.8% 的观测中 P&F 可覆盖，98.1% 的覆盖与检测器链分歧

### 3.2 代码修改

#### 修改 1: 移除 P&F 覆盖层

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_step1_phase_determine`（第 836-849 行）

```python
# ── 当前代码 ──
if pnf_hint in ("accumulation", "distribution"):
    phase = (
        WyckoffPhase.ACCUMULATION
        if pnf_hint == "accumulation"
        else WyckoffPhase.DISTRIBUTION
    )
    if chain_phase != phase:
        pnf_phase_divergence = (
            f"PnF={pnf_hint}, DetectorChain={chain_phase.value}"
        )
else:
    phase = chain_phase
    unknown_candidate = chain_unknown_candidate

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

#### 修改 2: 校准 P&F 阈值

**文件**: `src/uniquant/brain/wyckoff/pnf.py`
**函数**: `wyckoff_phase_hint`（第 226-260 行）

```python
# ── 当前阈值 ──
# 积累: rising_lows_ratio > 0.5 AND range_contraction < 0.85
#        AND recent_rising_lows > 0.4 AND avg_recent < avg_early * 0.9
# 分布: falling_highs_ratio > 0.3 AND range_contraction > 1.2
#        AND down_ratio > 0.5 AND avg_recent > avg_early * 1.1

# ── 改为（温和校准）──
# 积累: 小幅收紧
accum_cond = (
    rising_lows_ratio > 0.55          # 从 0.5 收紧到 0.55
    and range_contraction < 0.83      # 从 0.85 收紧到 0.83
    and recent_rising_lows > 0.45     # 从 0.4 收紧到 0.45
    and avg_recent < avg_early * 0.88  # 从 0.9 收紧到 0.88
    and down_ratio < 0.48             # 新增: 下降列比例 < 48%
)

# 分布: 小幅放宽
dist_cond = (
    falling_highs_ratio > 0.30        # 维持 0.30
    and (
        range_contraction > 1.18      # 从 1.2 放宽到 1.18
        or avg_recent > avg_early * 1.08  # 从 1.1 放宽到 1.08
    )
    and down_ratio > 0.47             # 从 0.5 放宽到 0.47
    and rising_lows_ratio < 0.55      # 维持 0.55
)
```

**注意**: 这些阈值是初步估计。校准将通过网格搜索在训练集上最终确定。

### 3.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_pnf_no_override` | 新测试 | P&F hint 不再覆盖检测器链相位 |
| `test_pnf_calibrated_accum` | 新测试 | 新阈值积累率 30-40%（非 0% 或 65%）|
| `test_pnf_calibrated_dist` | 新测试 | 新阈值分布率 20-30% |
| 现有 132 个测试 | 回归 | 预期大部分失败，需逐用例更新 |

### 3.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p0_v2

预期:
  accumulation 占比: 65.4% → 0.4%     (覆盖层移除)
  P&F 分歧率: 0% → 预期 80%+          (P&F 不再覆盖)
  markup 占比: 3.3% → 16.0%           (链式结果)
  markdown 占比: 6.8% → 47.7%         (链式结果 — 待 Phase 1 修复)
  现有测试: 预期 60-80% 失败，需更新
```

---

## 4. Phase 1: 检测器链重新平衡

### 4.1 问题诊断

覆盖层移除后，检测器链本身存在严重偏见:
- **积累过少**: 0.4%（目标 10-15%）
- **markdown 过多**: 47.7%（目标 15-25%）
- **markup 收益负**: -1.52%（目标 +2~5%）

### 4.2 代码修改

#### 修改 1: 放松积累检测器

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_detect_accumulation`（第 545-587 行）

```python
# ── 当前代码 ──
if ctx["is_in_trading_range"]:
    if ctx["prior_trend_pct"] < -0.03:
        return {"phase": WyckoffPhase.ACCUMULATION}
    if ctx["relative_position"] <= 0.40 and rule0.bc_found:
        return {"phase": WyckoffPhase.ACCUMULATION}
else:
    bc_sc_ok = (rule0.bc_found and rule0.sc_found) if require_both else (rule0.bc_found or rule0.sc_found)
    if (
        ctx["short_trend_pct"] <= st_max  # 默认 -0.02
        and ctx["current_price"] < ctx["ma20"]
        and ctx["ma5"] <= ctx["ma20"]
        and bc_sc_ok
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}

# ── 改为 ──
if ctx["is_in_trading_range"]:
    # 路径 B1: 前期下跌，门槛降低
    if ctx["prior_trend_pct"] < -0.02:  # 从 -0.03 放宽到 -0.02
        return {"phase": WyckoffPhase.ACCUMULATION}
    # 路径 B2: TR 低位 + BC
    if ctx["relative_position"] <= 0.45 and rule0.bc_found:  # 从 0.40 放宽到 0.45
        return {"phase": WyckoffPhase.ACCUMULATION}
else:
    # 路径 C: TR 外，门槛降低，移除 MA5 约束
    bc_sc_ok = rule0.bc_found or rule0.sc_found  # 放宽: 任一即可
    if (
        ctx["short_trend_pct"] <= -0.01  # 从 -0.02 放宽到 -0.01
        and ctx["current_price"] < ctx["ma20"]
        and bc_sc_ok
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}
```

**注意**: 移除了 `MA5 <= MA20` 约束，允许积累在短期均线刚拐头时触发。

#### 修改 2: 收紧 markdown 检测器

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_detect_markdown`（第 634-675 行）

```python
# ── 当前代码 ──
if ctx["is_in_trading_range"]:
    if (
        rule0.bc_found
        and rule0.bc_position is not None
        and cp <= rule0.bc_position.price * 0.85
        and cp < ma20 * cp_below_ma
        and ma5 <= ma20
        and st <= -0.02
    ):
        return {"phase": WyckoffPhase.MARKDOWN}
else:
    if st <= st_max and cp < ma20 * cp_below_ma:  # st_max=-0.05, cp_below_ma=0.95
        return {"phase": WyckoffPhase.MARKDOWN}
    # ... 路径 2/3 (BC 跌破)

# ── 改为 ──
if ctx["is_in_trading_range"]:
    # TR 内 markdown: 增加放量确认
    if (
        rule0.bc_found
        and rule0.bc_position is not None
        and cp <= rule0.bc_position.price * 0.85
        and cp < ma20 * cp_below_ma
        and ma5 <= ma20
        and st <= -0.02
    ):
        # 新增: 放量确认
        if len(df) >= 5:
            vol_5 = float(df.tail(5)["volume"].mean())
            vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
            if vol_20 > 0 and vol_5 > vol_20 * 1.1:
                return {"phase": WyckoffPhase.MARKDOWN}
else:
    # TR 外路径 1: 增加放量确认 + 相对位置约束
    if st <= st_max and cp < ma20 * cp_below_ma:
        if len(df) >= 5:
            vol_5 = float(df.tail(5)["volume"].mean())
            vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
            if vol_20 > 0 and vol_5 > vol_20 * 1.1:
                # 新增: 相对位置约束 — 不在极度低位
                if ctx["relative_position"] >= 0.20:
                    return {"phase": WyckoffPhase.MARKDOWN}
    # 路径 2: 收紧 BC 跌破门槛
    if (
        rule0.bc_found
        and rule0.bc_position is not None
        and cp <= rule0.bc_position.price * 0.85  # 从 0.90 收紧到 0.85
        and cp < ma20
        and ma5 <= ma20
        and st <= -0.02  # 从 0 收紧到 -0.02
    ):
        return {"phase": WyckoffPhase.MARKDOWN}
```

#### 修改 3: 放宽 markup 检测器

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_detect_markup`（第 589-617 行）

```python
# ── 当前代码 ──
if ctx["is_in_trading_range"]:
    if (rp >= 0.55 or st >= st_min) and (
        (cp > ma20 * cp_above_ma and ma5 >= ma20 * 0.96)
        or (cp > ma5 and rp >= rp_min)
    ):
        return {"phase": WyckoffPhase.MARKUP}
else:
    if st >= st_min and (  # st_min=0.03
        (cp > ma20 and ma5 >= ma20)
        or (cp > ma5 and rp >= rp_min)  # rp_min=0.50
    ):
        return {"phase": WyckoffPhase.MARKUP}

# ── 改为 ──
if ctx["is_in_trading_range"]:
    if (rp >= 0.50 or st >= 0.02) and (  # 门槛略微放松
        (cp > ma20 * 0.97 and ma5 >= ma20 * 0.95)
        or (cp > ma5 and rp >= 0.45)
    ):
        return {"phase": WyckoffPhase.MARKUP}
else:
    # TR 外: 新增早期路径 + 降低现有门槛
    # 早期路径: 短期趋势转正即触发
    if (
        st >= 0.005  # 从 0.03 大幅降低到 0.005
        and cp > ma20
        and ma5 >= ma20 * 0.98
        and rp >= 0.35
    ):
        return {"phase": WyckoffPhase.MARKUP}
    # 标准路径: 降低门槛
    if st >= 0.015 and (  # 从 0.03 降低到 0.015
        (cp > ma20 and ma5 >= ma20)
        or (cp > ma5 and rp >= 0.35)  # 从 0.50 降低到 0.35
    ):
        return {"phase": WyckoffPhase.MARKUP}
```

### 4.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_accum_loosened_tr_in` | 新测试 | TR 内积累需要 prior_trend < -2%（原 -3%）|
| `test_accum_loosened_tr_out` | 新测试 | TR 外积累需要 short_trend <= -1%（原 -2%）|
| `test_accum_no_ma5_constraint` | 新测试 | TR 外积累不再要求 MA5 < MA20 |
| `test_markdown_tightened_volume` | 新测试 | markdown 需要放量确认 |
| `test_markdown_tightened_bc` | 新测试 | BC 跌破门槛从 0.90 收紧到 0.85 |
| `test_markup_early_path` | 新测试 | short_trend=0.5% 仍触发 markup |
| `test_markup_lowered_threshold` | 新测试 | short_trend=1.5% 触发 markup |
| 积累/Markup/Markdown 回归 | 回归 | 更新后的测试用例 |

### 4.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p1_v2

预期:
  accumulation 占比: 0.4% → 8-15%      (放松后上升)
  markdown 占比: 47.7% → 15-25%        (收紧后下降)
  markup 占比: 16.0% → 15-20%          (维持或略升)
  unknown 占比: 24.8% → 25-40%         (上升，合理的储备态)
  markup 3m 收益: -1.52% → -1~+1%      (改善方向，但可能仍负)
  markdown 3m 收益: +2.25% → +1~-1%    (改善方向)
```

---

## 5. Phase 2: 方向反转修复 — 预测性检测

### 5.1 问题诊断

方向反转不是 P&F 覆盖层导致的，而是检测器链自身的结构性问题:
- Markup 检测在价格已涨 3% 以上时才确认，此时已是短期顶部
- Markdown 检测在价格已跌 5% 以上时才确认，此时已是短期底部
- 检测器滞后确认导致方向反转

**时段分析确认方向反转的时段依赖性**:
| 时段 | markup 收益 | markdown 收益 |
|------|------------|--------------|
| 2020-2021 (牛市) | +0.22% | +6.24% |
| 2022-2023 (熊市) | -3.44% | +0.02% |
| 2024 (熊市) | -5.56% | -5.63% |

**修复方向**: 引入预测性检测，检测**转换点**而非滞后确认。

### 5.2 代码修改

#### 修改 1: 引入积累→markup 转换检测

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**新增函数**: `_detect_accum_to_markup_transition`

```python
def _detect_accum_to_markup_transition(
    self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result,
    previous_phase: Optional[str] = None,
) -> Optional[dict]:
    """检测积累→markup 的早期转换信号。

    条件:
      1. 前一个相位是 accumulation
      2. 短期趋势转正 (> 0.5%)
      3. 价格刚站上 MA20
      4. MA5 已在 MA20 之上
      5. 相对位置在 0.30-0.60（从低位起来但未到高位）
      6. 放量确认（近 5 日量 > 近 20 日量中位数 * 1.1）
    """
    if previous_phase != "accumulation":
        return None
    if not (0.005 < ctx["short_trend_pct"] < 0.05):
        return None
    if not (ctx["current_price"] > ctx["ma20"] and ctx["ma5"] > ctx["ma20"]):
        return None
    if not (0.30 <= ctx["relative_position"] <= 0.60):
        return None
    if len(df) >= 5:
        vol_5 = float(df.tail(5)["volume"].mean())
        vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
        if vol_20 > 0 and vol_5 > vol_20 * 1.1:
            return {"phase": WyckoffPhase.MARKUP}
    return None
```

#### 修改 2: 引入分布→markdown 转换检测

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**新增函数**: `_detect_dist_to_markdown_transition`

```python
def _detect_dist_to_markdown_transition(
    self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result,
    previous_phase: Optional[str] = None,
) -> Optional[dict]:
    """检测分布→markdown 的早期转换信号。

    条件:
      1. 前一个相位是 distribution
      2. 短期趋势转负 (< -0.5%)
      3. 价格刚跌破 MA20
      4. MA5 已在 MA20 之下
      5. 未放量异常（非恐慌性抛售）
    """
    if previous_phase != "distribution":
        return None
    if not (ctx["short_trend_pct"] < -0.005):
        return None
    if not (ctx["current_price"] < ctx["ma20"] and ctx["ma5"] < ctx["ma20"]):
        return None
    if len(df) >= 5:
        vol_5 = float(df.tail(5)["volume"].mean())
        vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
        if vol_20 > 0 and vol_5 < vol_20 * 1.5:  # 非异常放量
            return {"phase": WyckoffPhase.MARKDOWN}
    return None
```

#### 修改 3: 在检测器链中插入转换检测

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_step1_phase_determine`（第 816-824 行）

```python
# ── 当前检测器链 ──
detectors: List = [
    self._detect_markup,
    self._detect_distribution,
    self._detect_markdown,
    self._detect_accumulation,
    self._detect_spring,
    self._detect_utad,
    self._detect_sos,
]

# ── 改为 ──
# 在现有检测器之前插入转换检测器
detectors: List = [
    self._detect_accum_to_markup_transition,  # 新增: 转换优先
    self._detect_dist_to_markdown_transition,  # 新增: 转换优先
    self._detect_markup,
    self._detect_distribution,
    self._detect_markdown,
    self._detect_accumulation,
    self._detect_spring,
    self._detect_utad,
    self._detect_sos,
]
```

**注意**: 转换检测器需要 `previous_phase` 参数。需在 `_analyze_single` 中传入（见 Phase 3）。

### 5.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_accum_to_markup_transition` | 新测试 | 积累→markup 转换检测（short_trend=0.5% 触发）|
| `test_dist_to_markdown_transition` | 新测试 | 分布→markdown 转换检测（short_trend=-0.5% 触发）|
| `test_markup_direction_corrected` | 新测试 | Markup 检测后的 3 月收益为正（p<0.05）|
| `test_markdown_direction_corrected` | 新测试 | Markdown 检测后的 3 月收益为负（p<0.05）|
| 现有检测器 | 回归 | 转换检测器不影响现有检测器 |

### 5.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p2_v2

预期:
  markup 占比: 15-20% → 15-25%         (转换检测增加早期 markup)
  markdown 占比: 15-25% → 15-25%       (维持)
  markup 3m 收益: -1~+1% → +1~3%       (预测性检测改善方向)
  markdown 3m 收益: +1~-1% → -1~-3%    (预测性检测改善方向)
  H3 单调性: ❌ → ✅                    (一致性层次应成立)
```

---

## 6. Phase 3: 相位转换检测

### 6.1 问题诊断

当前引擎每个 cutoff 独立判定相位，不参考历史状态。H5 验证显示转换不增加预测力（p=0.9967）。
但数据发现特定转换有预测力: `distribution→accumulation` 收益 +2.76%。

### 6.2 代码修改

#### 修改 1: 在 `_analyze_single` 中传入 previous_phase

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**函数**: `_analyze_single`（第 267-450 行）

```python
def _analyze_single(
    self,
    df: pd.DataFrame,
    symbol: str = "",
    period: str = "",
    pnf_engine: Optional[PointAndFigure] = None,
    previous_phase: Optional[str] = None,  # 新增参数
) -> WyckoffReport:
    # ... 现有代码 ...
```

#### 修改 2: 在 `_step1_phase_determine` 中使用 previous_phase

```python
def _step1_phase_determine(
    self, df, rule0, pnf_hint=None, previous_phase=None  # 新增参数
) -> Step1Result:
    # ... 检测器链逻辑 ...

    # 新增: 转换检测
    if previous_phase is not None and phase != previous_phase:
        transition = f"{previous_phase}→{phase.value}"
    else:
        transition = None

    # 转换置信度加分
    confidence_boost = 0.0
    if transition:
        if transition in ("accumulation→markup", "distribution→markdown"):
            confidence_boost = 0.2  # 理论方向转换加分
        elif transition in ("markdown→accumulation", "markup→distribution"):
            confidence_boost = 0.1  # 周期转换加分
```

#### 修改 3: 在 `Step1Result` 中增加 transition 字段

**文件**: `src/uniquant/brain/wyckoff/state.py` 或 `engine.py`

```python
@dataclass
class Step1Result:
    phase: WyckoffPhase
    sub_phase: str = ""
    unknown_candidate: str = ""
    prior_trend_pct: float = 0.0
    is_in_tr: bool = False
    short_trend_pct: float = 0.0
    relative_position: float = 0.5
    ma5: float = 0.0
    ma20: float = 0.0
    boundary_upper: float = 0.0
    boundary_lower: float = 0.0
    boundary_source: List[str] = field(default_factory=list)
    pnf_phase_divergence: Optional[str] = None
    transition: Optional[str] = None  # 新增字段
    confidence_boost: float = 0.0     # 新增字段
```

### 6.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_transition_detection` | 新测试 | 传入 previous_phase 后正确检测转换 |
| `test_transition_confidence_boost` | 新测试 | 特定转换获得置信度加分 |
| `test_transition_no_previous` | 新测试 | previous_phase=None 时行为不变 |

### 6.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p3_v2

预期:
  H5 转换预测: ❌ → ✅ (p < 0.05)
  distribution→accumulation 转换收益: 维持或提升
```

---

## 7. Phase 4: 置信度重算

### 7.1 问题诊断

当前置信度规则 8（5 条件矩阵）与真实收益负相关。L1_strictest 收益 -1.80%，L3_moderate 收益 +0.84%。

### 7.2 代码修改

#### 修改 1: 新增"位置置信度"维度

**文件**: `src/uniquant/brain/wyckoff/engine.py`
**新增函数**: `_compute_position_confidence`

```python
def _compute_position_confidence(self, phase, ctx, step3) -> float:
    confidence = 0.5
    if phase == WyckoffPhase.ACCUMULATION:
        if ctx["relative_position"] <= 0.30:
            confidence += 0.3
        elif ctx["relative_position"] <= 0.50:
            confidence += 0.1
        else:
            confidence -= 0.2
    elif phase == WyckoffPhase.MARKUP:
        if ctx["relative_position"] <= 0.60:
            confidence += 0.3
        elif ctx["relative_position"] <= 0.75:
            confidence += 0.1
        else:
            confidence -= 0.2
    elif phase == WyckoffPhase.DISTRIBUTION:
        if ctx["relative_position"] >= 0.70:
            confidence += 0.3
        elif ctx["relative_position"] >= 0.50:
            confidence += 0.1
        else:
            confidence -= 0.2
    elif phase == WyckoffPhase.MARKDOWN:
        if ctx["relative_position"] >= 0.40:
            confidence += 0.3
        elif ctx["relative_position"] >= 0.25:
            confidence += 0.1
        else:
            confidence -= 0.2
    return max(0.0, min(1.0, confidence))
```

#### 修改 2: 新增"相位持续时间"置信度调整

```python
def _compute_duration_confidence(self, step1, previous_phase, duration_months: int = 0) -> float:
    if duration_months <= 0:
        return 0.0
    if 4 <= duration_months <= 6:
        return 0.2
    elif 1 <= duration_months <= 3:
        return 0.1
    elif 7 <= duration_months <= 12:
        return -0.1
    else:
        return -0.2
```

#### 修改 3: 整合到最终置信度

```python
final_confidence = base_confidence + position_conf * 0.5 + duration_conf * 0.3 + transition_conf * 0.2
```

### 7.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_position_confidence_accum_low` | 新测试 | 积累在低位时置信度高 |
| `test_position_confidence_markup_early` | 新测试 | Markup 在刚突破时置信度高 |
| `test_duration_confidence_4_6m` | 新测试 | 4-6 月持续时间获得加分 |
| `test_confidence_positive_correlation` | 新测试 | 置信度与收益正相关 |

### 7.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p4_v2

预期:
  置信度与收益: 负相关 → 正相关
  L1_strictest 收益: -1.80% → +2~4%
  L3_moderate 收益: +0.84% → +2~4%
```

---

## 8. Phase 5: 调仓策略优化

### 8.1 问题诊断

当前 H7 策略每月调仓，换手率 2.4%/月，年化成本 6.67%/月，净收益 -50.1%。

### 8.2 代码修改

**文件**: `scripts/wyckoff_multitf/runner_v3.py`
**函数**: `test_h7_backtest`（第 407-477 行）

```python
# ── 当前逻辑 ──
in_strategy = [o for o in at_cutoff if o.month_phase in ("accumulation", "markup")]

# ── 改为 ──
# 仅在相位转换时调仓
in_strategy = [
    o for o in at_cutoff
    if o.month_phase in ("accumulation", "markup")
    and o.had_transition  # 只在转换时调仓
]
```

### 8.3 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| 换手率 | 2.4%/月 | 0.3-0.5%/月 |
| 年化成本 | 6.67%/月 | 0.8-1.5%/月 |
| 策略净收益 | -50.1% | +5~15% |

---

## 9. 验证方法论

### 9.1 3-way 数据分割

| 数据集 | 时间范围 | 用途 |
|--------|---------|------|
| 训练集 | 2020-01 至 2021-12 | 阈值搜索（网格搜索） |
| 验证集 | 2022-01 至 2023-12 | 阈值选择（最佳组合） |
| 测试集 | 2024-01 至 2024-06 | 最终结果报告 |

### 9.2 验证流程

```
每次修改后:
  1. ruff check src/ tests/ scripts/    (0 容忍)
  2. pytest tests/classic_wyckoff/ -q   (更新后测试全部通过)
  3. python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _verify
     (约 7.5 分钟，验证相位分布和收益方向)
  4. 对比预期指标 vs 实际指标（bootstrap 95% CI 范围）
  5. 偏差超出 CI 则回滚
```

### 9.3 关键指标监控（含 bootstrap CI）

| 指标 | 目标范围 | 通过条件 |
|------|---------|---------|
| accumulation 占比 | 10-15% | bootstrap 95% CI 在此范围内 |
| markup 占比 | 15-20% | bootstrap 95% CI 在此范围内 |
| distribution 占比 | 10-15% | bootstrap 95% CI 在此范围内 |
| markdown 占比 | 15-25% | bootstrap 95% CI 在此范围内 |
| markup 3m 收益均值 | > 0% | t-test p < 0.05 为正 |
| markdown 3m 收益均值 | < 0% | t-test p < 0.05 为负 |
| H1 ANOVA p值 | < 0.05 | 显著 |
| 现有测试 | 100% | 全部通过（更新后） |
| ruff | 0 | 0 错误 |

### 9.4 A/B 对比方案

```bash
# 基线 (Phase 0 前)
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _baseline_v2

# Phase 0
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p0_v2

# Phase 1
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p1_v2

# Phase 2
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p2_v2

# 对比
python3 -c "
import json
for suffix in ['baseline_v2', 'p0_v2', 'p1_v2', 'p2_v2']:
    with open(f'scripts/wyckoff_multitf/output_v3_{suffix}/v3_results.json') as f:
        d = json.load(f)
    print(f'{suffix}: {d[\"meta\"][\"n_observations\"]} obs')
    # 打印关键指标
"
```

---

## 10. 回滚方案

### 10.1 逐文件回滚

每个修改独立 commit，可按 commit 回滚：

```bash
# 回滚 Phase 0
git revert <commit_p0_v2>

# 或回滚到某个阶段
git checkout <commit_before_p0_v2> -- src/uniquant/brain/wyckoff/pnf.py
git checkout <commit_before_p0_v2> -- src/uniquant/brain/wyckoff/engine.py
```

### 10.2 配置回滚

所有阈值修改在 calibration 字典中配置，支持运行时切换：

```yaml
wyckoff:
  calibration_v2:
    enabled: false                          # 关闭所有 v2 修改
    pnf_override_removed: true              # Phase 0: 覆盖层移除
    pnf_thresholds_v2: false                # Phase 0: 新阈值（默认关闭）
    accum_loosened: false                   # Phase 1: 放松积累
    markdown_tightened: false               # Phase 1: 收紧 markdown
    markup_loosened: false                  # Phase 1: 放宽 markup
    accum_to_markup_transition: false       # Phase 2: 积累→markup 转换检测
    dist_to_markdown_transition: false      # Phase 2: 分布→markdown 转换检测
    transition_detection: false             # Phase 3: 转换检测
    position_confidence: false              # Phase 4: 位置置信度
    duration_confidence: false              # Phase 4: 持续时间置信度
```

---

## 11. 附录: 文件修改清单

| 文件 | 修改函数 | 修改类型 | 影响范围 |
|------|---------|---------|---------|
| `pnf.py` | `wyckoff_phase_hint` | 阈值校准 | Phase 0 |
| `engine.py` | `_step1_phase_determine` | P&F 覆盖逻辑 + 转换检测器插入 | Phase 0, Phase 2, Phase 3 |
| `engine.py` | `_detect_accumulation` | 3 条路径放松 | Phase 1 |
| `engine.py` | `_detect_markdown` | 新增放量确认 + 收紧条件 | Phase 1 |
| `engine.py` | `_detect_markup` | 新增早期路径 + 降低门槛 | Phase 1 |
| `engine.py` | `_detect_accum_to_markup_transition` | 新增函数 | Phase 2 |
| `engine.py` | `_detect_dist_to_markdown_transition` | 新增函数 | Phase 2 |
| `engine.py` | `_analyze_single` | 传入 previous_phase | Phase 3 |
| `engine.py` | `Step1Result` | 增加 transition 字段 | Phase 3 |
| `engine.py` | 置信度函数 | 新增位置/持续时间置信度 | Phase 4 |
| `runner_v3.py` | `test_h7_backtest` | 转换驱动调仓 | Phase 5 |

## 附录 B: 新增测试文件

| 测试文件 | 测试内容 | 预期数量 |
|---------|---------|---------|
| `tests/classic_wyckoff/test_phase5_pnf_v2.py` | P&F 覆盖层移除 + 阈值校准 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase5_accum_loosen.py` | 积累放松验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase5_markdown_tighten.py` | Markdown 收紧验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase5_markup_early.py` | Markup 早期路径验证 | 4-6 测试 |
| `tests/classic_wyckoff/test_phase5_transition_detect.py` | 转换检测验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase5_direction_validation.py` | 方向反转修复验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase5_confidence.py` | 置信度重算验证 | 6-8 测试 |

## 附录 C: 红蓝对抗验证脚本

| 脚本 | 功能 | 使用方式 |
|------|------|---------|
| `scripts/wyckoff_multitf/v9_rb_validation.py` | 真实引擎 monkeypatch 反事实 | `--max-stocks 500` |
| `scripts/wyckoff_multitf/v9_rb_bootstrap.py` | 2000 次 bootstrap 统计验证 | 直接运行 |

验证数据保存在 `scripts/wyckoff_multitf/output_rb_validation/`。