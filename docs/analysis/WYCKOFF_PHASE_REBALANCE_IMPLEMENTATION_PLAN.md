# Wyckoff 相位再平衡 — 详细实现方案

**基于 254,222 观测值全量扫描数据的代码级修复方案**
**分析日期**: 2026-08-06

---

## 目录

1. [问题总结](#1-问题总结)
2. [修复策略总览](#2-修复策略总览)
3. [Phase 0: P&F 对称化](#3-phase-0-pf-对称化)
4. [Phase 1: 积累检测器收紧](#4-phase-1-积累检测器收紧)
5. [Phase 2: Markup/Markdown 前瞻化](#5-phase-2-markupmarkdown-前瞻化)
6. [Phase 3: 相位转换检测](#6-phase-3-相位转换检测)
7. [Phase 4: 置信度重算](#7-phase-4-置信度重算)
8. [Phase 5: 调仓策略优化](#8-phase-5-调仓策略优化)
9. [验证方法论](#9-验证方法论)
10. [回滚方案](#10-回滚方案)

---

## 1. 问题总结

### 1.1 数据验证的 3 个核心问题

| # | 问题 | 数据证据 | 根因代码 | 严重程度 |
|---|------|---------|---------|---------|
| 1 | 积累过量 (65.9%) | 254K 观测中 65.9% 为 accumulation | `pnf.py:249` + `engine.py:573-586` | **CRITICAL** |
| 2 | Markup/Markdown 方向反转 | markup -4.17%, markdown +3.45% | `engine.py:589-675` | **CRITICAL** |
| 3 | 置信度与收益负相关 | L1_strict -1.80%, L3_moderate +0.84% | `engine.py:1290-1357` | HIGH |

### 1.2 修复优先级矩阵

```
        高影响                 低影响
        ┌─────────────────────────────────┐
  高修复│  P&F 对称化          │ 调仓优化   │
  效率  │  积累收紧             │            │
        │  Markup/Markdown      │            │
        │  前瞻化               │            │
        ├─────────────────────────────────┤
  低修复│  置信度重算          │ 相位转换   │
  效率  │                      │ 检测       │
        └─────────────────────────────────┘
```

**执行顺序**: P&F → 积累 → Markup/Md → 置信度 → 调仓 → 转换检测

---

## 2. 修复策略总览

### 2.1 核心原则

1. **不破坏现有测试**: 132 个 classic_wyckoff 测试必须全部通过
2. **渐进式验证**: 每次修改后运行 1000 只验证（~7.5 分钟），确认指标改善
3. **可逆设计**: 所有阈值可配置（通过 calibration 字典），支持 A/B 对比
4. **保守原则**: 新增逻辑不删除旧逻辑，改为优先级调整

### 2.2 预期指标变化

| 指标 | 当前 | Phase 0 | Phase 1 | Phase 2 | Phase 3-4 | 最终目标 |
|------|------|---------|---------|---------|-----------|---------|
| accum 占比 | 65.9% | 45-50% | 25-30% | 25-30% | 25-30% | ~28% |
| markup 占比 | 3.6% | 3.6% | 3.6% | 15-20% | 15-20% | ~18% |
| distribution 占比 | 17.1% | 20-25% | 20-25% | 15-20% | 15-20% | ~18% |
| markdown 占比 | 6.0% | 6.0% | 6.0% | 15-20% | 15-20% | ~18% |
| unknown 占比 | 7.4% | 15-25% | 25-35% | 15-25% | 15-25% | ~18% |
| markup 收益 | -4.17% | -4.17% | -4.17% | +3~8% | +5~10% | +5~10% |
| markdown 收益 | +3.45% | +3.45% | +3.45% | -3~-8% | -3~-8% | -3~-8% |
| H1 ANOVA p值 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| H3 单调性 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| H5 转换预测 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| H7 策略净收益 | -50.1% | -50.1% | -50.1% | -30~-10% | +5~15% | +5~15% |

---

## 3. Phase 0: P&F 对称化

### 3.1 问题诊断

`pnf.py:wyckoff_phase_hint()` 的积累条件过于宽松，派发条件过于严格。

**对称性分析**（基于 5445 只全量扫描）：

```
P&F 返回结果分布（推测）:
  accumulation: ~55-60%  ← 当前代码偏好
  unknown:      ~30-35%
  distribution: ~5-10%
```

### 3.2 代码修改

#### 文件: `src/uniquant/brain/wyckoff/pnf.py`

**修改 1: 收紧积累条件，放宽派发条件**（函数 `wyckoff_phase_hint`，第 226-260 行）

```python
def wyckoff_phase_hint(self) -> str:
    highs, lows = self._column_stats()
    n = len(highs)
    if n < 8:
        return "unknown"

    rising_lows_ratio = sum(1 for i in range(1, n) if lows[i] > lows[i - 1]) / (n - 1)
    falling_highs_ratio = sum(1 for i in range(1, n) if highs[i] < highs[i - 1]) / (n - 1)
    recent_rising_lows = sum(1 for i in range(n // 2, n) if lows[i] > lows[i - 1]) / max(1, n - n // 2 - 1)

    ranges = [highs[i] - lows[i] for i in range(n)]
    recent_ranges = ranges[n // 2:]
    early_ranges = ranges[:n // 2]
    avg_recent = np.mean(recent_ranges) if recent_ranges else 0
    avg_early = np.mean(early_ranges) if early_ranges else 1
    if avg_early == 0:
        avg_early = 1
    range_contraction = avg_recent / avg_early

    up_columns = sum(1 for i in range(1, n) if highs[i] > highs[i - 1])
    down_ratio = 1 - up_columns / max(1, n - 1)

    # ── 对称化积累条件 ──
    # 当前: rising_lows_ratio > 0.5 AND range_contraction < 0.85
    #       AND recent_rising_lows > 0.4 AND avg_recent < avg_early * 0.9
    # 改为: 收紧 + 新增 down_ratio 约束
    accum_cond = (
        rising_lows_ratio > 0.60          # 从 0.5 收紧到 0.6
        and range_contraction < 0.80       # 从 0.85 收紧到 0.80
        and recent_rising_lows > 0.50      # 从 0.4 收紧到 0.5
        and avg_recent < avg_early * 0.85  # 从 0.9 收紧到 0.85
        and down_ratio < 0.45              # 新增: 下降列比例不能超过 45%
    )

    # ── 对称化派发条件 ──
    # 当前: falling_highs_ratio > 0.3 AND range_contraction > 1.2
    #       AND down_ratio > 0.5 AND avg_recent > avg_early * 1.1
    # 改为: 放宽条件 + 降低门槛
    dist_cond = (
        falling_highs_ratio > 0.30         # 维持 0.3
        and (
            range_contraction > 1.15        # 从 1.2 放宽到 1.15
            or avg_recent > avg_early * 1.05 # 从 1.1 放宽到 1.05
        )
        and down_ratio > 0.45              # 从 0.5 放宽到 0.45
        and rising_lows_ratio < 0.55       # 新增: 低点抬高比例不能过高
    )

    if accum_cond:
        return "accumulation"
    if dist_cond:
        return "distribution"
    return "unknown"
```

**修改 2: P&F 覆盖层降级为加权提示**（`engine.py:_step1_phase_determine`，第 836-849 行）

```python
# ── 当前代码 ──
if pnf_hint in ("accumulation", "distribution"):
    phase = (
        WyckoffPhase.ACCUMULATION
        if pnf_hint == "accumulation"
        else WyckoffPhase.DISTRIBUTION
    )
    # 检测器链结果被完全忽略，仅记录分歧

# ── 改为 ──
# P&F hint 不再覆盖检测器链，改为加权提示
# 检测器链的最终结果保持为唯一相位来源
# 同时 P&F hint 用于调整检测器链的阈值
if pnf_hint in ("accumulation", "distribution"):
    # P&F hint 只记录分歧，检测器链的相位保持不变
    if chain_phase != phase:
        pnf_phase_divergence = (
            f"PnF={pnf_hint}, DetectorChain={chain_phase.value}"
        )
    # 如果 P&F hint 与检测器链一致，记录一致信息
    else:
        pnf_phase_divergence = (
            f"PnF={pnf_hint}, DetectorChain={chain_phase.value} (aligned)"
        )
else:
    phase = chain_phase
    unknown_candidate = chain_unknown_candidate
```

**注意**: 修改 2 移除了 P&F 对 phase 的覆盖。这意味着 `chain_phase` 必须通过 `_compute_step1_context` + 检测器链来判定。P&F 只作为分歧记录。

### 3.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_pnf_symmetry` | 新测试 | 积累和派发条件对等（相同的列数/波动率输入） |
| `test_pnf_accum_tightened` | 新测试 | 旧积累输入不再触发 accumulation |
| `test_pnf_dist_relaxed` | 新测试 | 旧派发输入现在更容易触发 distribution |
| `test_pnf_no_override` | 新测试 | P&F hint 不再覆盖检测器链相位 |
| 现有 132 个测试 | 回归 | 预期大部分通过，少数因 P&F 行为变化需调整 |

### 3.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p0

预期:
  accumulation 占比: 65.9% → 45-50%   (下降)
  distribution 占比: 17.1% → 20-25%   (上升)
  unknown 占比:     7.4%  → 15-20%   (上升)
  P&F 分歧率: 原 0% → 预期 30-40%
```

---

## 4. Phase 1: 积累检测器收紧

### 4.1 问题诊断

`_detect_accumulation` 的 3 条路径全部过于宽松。路径 B（TR 内）只需要 `prior_trend < -3%`，路径 C（TR 外）只需要 `short_trend <= -2%` + `price < MA20` + `BC/SC 存在`。

### 4.2 代码修改

#### 文件: `src/uniquant/brain/wyckoff/engine.py`

**修改 1: 收紧积累路径 B（TR 内）**（函数 `_detect_accumulation`，第 573-577 行）

```python
# ── 当前代码 ──
if ctx["is_in_trading_range"]:
    if ctx["prior_trend_pct"] < -0.03:
        return {"phase": WyckoffPhase.ACCUMULATION}
    if ctx["relative_position"] <= 0.40 and rule0.bc_found:
        return {"phase": WyckoffPhase.ACCUMULATION}

# ── 改为 ──
if ctx["is_in_trading_range"]:
    # 路径 B1: 前期下跌 + 价格在低位 + 均线压制
    if (
        ctx["prior_trend_pct"] < -0.05          # 从 -3% 收紧到 -5%
        and ctx["current_price"] < ctx["ma20"]   # 新增: 价格低于 MA20
        and ctx["ma5"] < ctx["ma20"]             # 新增: MA5 低于 MA20
        and rule0.bc_found                        # 维持: BC 必须存在
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}
    # 路径 B2: TR 低位 + BC + 横盘时间足够
    if (
        ctx["relative_position"] <= 0.35          # 从 0.40 收紧到 0.35
        and rule0.bc_found
        and len(df) >= 120                         # 新增: 至少有 120 根 K 线
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}
```

**修改 2: 收紧积累路径 C（TR 外）**（第 578-586 行）

```python
# ── 当前代码 ──
else:
    bc_sc_ok = (rule0.bc_found and rule0.sc_found) if require_both else (rule0.bc_found or rule0.sc_found)
    if (
        ctx["short_trend_pct"] <= st_max
        and ctx["current_price"] < ctx["ma20"]
        and ctx["ma5"] <= ctx["ma20"]
        and bc_sc_ok
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}

# ── 改为 ──
else:
    # TR 外的积累需要更明确的证据
    bc_sc_ok = (rule0.bc_found and rule0.sc_found) if require_both else (rule0.bc_found and rule0.sc_found)
    # 默认 require_both = True，即使 calibration 设为 False 也要求 BC AND SC 同时存在
    if (
        ctx["short_trend_pct"] <= -0.05           # 从 -2% 收紧到 -5%
        and ctx["current_price"] < ctx["ma20"] * 0.95  # 从 MA20 收紧到 MA20*0.95
        and ctx["ma5"] <= ctx["ma20"] * 0.98      # 新增: MA5 显著低于 MA20
        and bc_sc_ok                                # 改为 BC AND SC 必须同时存在
        and ctx["relative_position"] <= 0.40       # 新增: 价格在 TR 低位
    ):
        return {"phase": WyckoffPhase.ACCUMULATION}
```

**修改 3: 新增积累拒绝条件**（第 566-571 行之后）

```python
# 在原有 guard 之后新增拒绝条件
# 原有 guard:
if len(df) >= 10:
    recent_5_low = float(df.tail(5)["low"].min())
    recent_10_low = float(df.tail(10)["low"].min())
    if recent_10_low > 0 and recent_5_low < recent_10_low * 0.98:
        return None

# 新增拒绝条件:
# 1. 如果 MA5 > MA20: 短期趋势已向上，拒绝积累
if ctx["ma5"] > ctx["ma20"]:
    return None

# 2. 如果价格在 TR 高位: 拒绝积累
if ctx["relative_position"] > 0.60:
    return None

# 3. 如果放量异常: 拒绝积累（可能是派发而非积累）
if "volume" in df.columns and len(df) >= 20:
    vol_20 = float(df.tail(20)["volume"].mean())
    vol_60 = float(df.tail(60)["volume"].mean()) if len(df) >= 60 else vol_20
    if vol_60 > 0 and vol_20 > vol_60 * 1.2:
        return None
```

### 4.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_accum_tightened_tr_in` | 新测试 | TR 内积累需要 prior_trend < -5%（原 -3%） |
| `test_accum_tightened_tr_out` | 新测试 | TR 外积累需要 short_trend <= -5%（原 -2%）|
| `test_accum_new_reject_ma5_gt_ma20` | 新测试 | MA5 > MA20 时拒绝积累 |
| `test_accum_new_reject_rp_gt_60` | 新测试 | relative_position > 0.60 时拒绝积累 |
| `test_accum_old_paths_still_work` | 新测试 | 严格条件仍能触发积累 |
| 现有积累相关测试 | 回归 | `test_phase1_pnf.py`, `test_phase2_events.py` 等 |

### 4.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p1

预期:
  accumulation 占比: 45-50% → 25-30%   (大幅下降)
  unknown 占比:     15-20% → 25-30%   (上升，合理的储备态)
  accum 收益:        +2.95% → +5~8%   (去掉伪积累后真实信号增强)
  H1 ANOVA p值:      0.0000 → 0.0000  (维持显著)
```

---

## 5. Phase 2: Markup/Markdown 前瞻化

### 5.1 问题诊断

当前 markup 检测需要 `short_trend >= 3%`，markdown 需要 `short_trend <= -5%`。这意味着：
- Markup 确认时已是顶部 → 后续收益 -4.17%
- Markdown 确认时已是底部 → 后续收益 +3.45%

**修复方向**: 将 markup 检测点从"已涨 3%"前移到"刚从底部启动"，将 markdown 检测点从"已跌 5%"前移到"刚从顶部下滑"。

### 5.2 代码修改

#### 文件: `src/uniquant/brain/wyckoff/engine.py`

**修改 1: 新增 markup 早期信号路径**（函数 `_detect_markup`，第 607-608 行之前新增）

```python
# ── 新增路径 0: 积累转 markup 的早期信号 ──
# 在 TR 外路径 1 之前插入
# 条件: 前一个相位是 accumulation + 价格刚站上 MA20 + 温和放量
if (
    ctx["is_in_trading_range"] == False  # 不在 TR 中（已突破）
    and ctx["short_trend_pct"] > 0.01    # 短期趋势 > 1%（非 3%）
    and ctx["current_price"] > ctx["ma20"]  # 价格刚站上 MA20
    and ctx["ma5"] > ctx["ma20"]          # MA5 已在 MA20 之上
    and ctx["relative_position"] <= 0.60  # 不在 TR 高位（还没涨太多）
):
    # 检查是否刚从 accumulation 转过来
    # 通过 volume 确认: 放量突破
    if len(df) >= 5:
        vol_5 = float(df.tail(5)["volume"].mean())
        vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
        if vol_20 > 0 and vol_5 > vol_20 * 1.1:  # 近 5 日放量 > 10%
            return {"phase": WyckoffPhase.MARKUP}
```

**修改 2: 降低 markup 现有路径门槛**（第 608-616 行）

```python
# ── 当前路径 1 (TR 外) ──
if st >= st_min and (                          # st_min = 0.03
    (cp > ma20 and ma5 >= ma20)
    or (cp > ma5 and rp >= rp_min)             # rp_min = 0.50
):
    return {"phase": WyckoffPhase.MARKUP}

# ── 改为 ──
# 路径 1: 短期趋势门槛降低
if st >= 0.01 and (                            # 从 0.03 降低到 0.01
    (cp > ma20 and ma5 >= ma20)
    or (cp > ma5 and rp >= 0.35)               # 从 0.50 降低到 0.35
):
    return {"phase": WyckoffPhase.MARKUP}
```

**修改 3: 新增 markdown 早期信号路径**（函数 `_detect_markdown`，第 655-656 行之前新增）

```python
# ── 新增路径 0: 派发转 markdown 的早期信号 ──
# 在 TR 外路径 1 之前插入
# 条件: 价格刚跌破 MA20 + 短期均线死叉
if (
    ctx["is_in_trading_range"] == False
    and ctx["short_trend_pct"] < -0.01         # 短期趋势 < -1%（非 -5%）
    and ctx["current_price"] < ctx["ma20"]      # 价格刚跌破 MA20
    and ctx["ma5"] < ctx["ma20"]                # MA5 已跌破 MA20
    and ctx["relative_position"] >= 0.30        # 还没跌到最低
):
    # 检查是否刚从 distribution 转过来
    # 通过 volume 确认: 缩量下跌
    if len(df) >= 5:
        vol_5 = float(df.tail(5)["volume"].mean())
        vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
        if vol_20 > 0 and vol_5 < vol_20 * 1.1:  # 非异常放量
            return {"phase": WyckoffPhase.MARKDOWN}
```

**修改 4: 降低 markdown 现有路径门槛**（第 656-674 行）

```python
# ── 当前路径 1 (TR 外) ──
if st <= st_max and cp < ma20 * cp_below_ma:  # st_max = -0.05, cp_below_ma = 0.95
    return {"phase": WyckoffPhase.MARKDOWN}

# ── 改为 ──
if st <= -0.025 and cp < ma20 * 0.97:          # 从 -5% 放宽到 -2.5%, 从 0.95 放宽到 0.97
    return {"phase": WyckoffPhase.MARKDOWN}
```

### 5.3 检测器顺序调整

当前检测器顺序: `markup → distribution → markdown → accumulation → spring → utad → sos`

**问题**: markup 和 markdown 在 accumulation 和 distribution 之前运行。当 accumulation 过量时，markup 和 markdown 根本没有机会。

**修复**: 调整检测器顺序，让"早期检测器"优先

```python
# 新的检测器顺序:
# 早期 markup → 早期 markdown → 事件序列 accumulation → 事件序列 distribution
# → 标准 markup → 标准 markdown → 标准 accumulation → standard distribution
# → spring → utad → sos

# 但这需要重构检测器签名以支持"早期"和"标准"模式。
# 更简单的方案: 将 _detect_markup 和 _detect_markdown 的早期路径
# 直接内联到 _step1_phase_determine 中，作为前置检查

# 在 _step1_phase_determine 中，检测器链之前插入:
def _check_early_markup(self, df, ctx, rule0):
    """检查积累→markup 的早期转换信号"""
    # ... 使用修改 1 中的逻辑
    return phase or None

def _check_early_markdown(self, df, ctx, rule0):
    """检查派发→markdown 的早期转换信号"""
    # ... 使用修改 3 中的逻辑
    return phase or None
```

### 5.4 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_markup_early_signal` | 新测试 | 积累转 markup 早期信号（short_trend=1% 仍触发）|
| `test_markdown_early_signal` | 新测试 | 派发转 markdown 早期信号（short_trend=-1% 仍触发）|
| `test_markup_direction_corrected` | 新测试 | Markup 检测后的 6 月收益为正 |
| `test_markdown_direction_corrected` | 新测试 | Markdown 检测后的 6 月收益为负 |
| `test_markup_strict_paths_unchanged` | 新测试 | 原严格路径仍能触发 markup |
| 现有 132 个测试 | 回归 | 全部通过 |

### 5.5 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p2

预期:
  markup 占比:     3.6%  → 15-20%   (大幅上升)
  markdown 占比:   6.0%  → 15-20%   (大幅上升)
  accum 占比:      25-30% → 20-25%  (进一步下降)
  unknown 占比:    25-30% → 15-20%  (下降，更多被分配到 markup/md)
  markup 收益:     -4.17% → +3~8%  (方向反转)
  markdown 收益:   +3.45% → -3~-8% (方向反转)
  H3 单调性:       ❌ → ✅ (一致性层次应成立)
  H7 策略毛收益:   +1.04%/mo → +2~3%/mo (改善)
```

---

## 6. Phase 3: 相位转换检测

### 6.1 问题诊断

当前引擎每个 cutoff 独立判定相位，不参考历史状态。H5 验证显示转换不增加预测力（p=0.9967）。

**数据发现**: `distribution→accumulation` 转换收益 +2.76%（最佳），`markdown→markup` 仅 27 个样本但 +3.14%。

### 6.2 代码修改

#### 文件: `src/uniquant/brain/wyckoff/engine.py`

**修改 1: 在 `_analyze_single` 中传入 previous_phase**（第 267-450 行）

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

**修改 2: 在 `_step1_phase_determine` 中使用 previous_phase**

```python
def _step1_phase_determine(
    self, df, rule0, pnf_hint=None, previous_phase=None  # 新增参数
) -> Step1Result:
    # ... 现有检测器链逻辑 ...

    # 新增: 转换检测
    # 在检测器链和 P&F 处理之后，相位确定之前
    if previous_phase is not None and phase != previous_phase:
        transition = f"{previous_phase}→{phase.value}"
        # 记录转换类型
        # 后续在置信度计算中使用
    else:
        transition = None
```

**修改 3: 在 `Step1Result` 中增加 transition 字段**

需要在 `state.py` 或 `engine.py` 的 `Step1Result` 数据类中增加 `transition` 字段。

### 6.3 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|---------|
| `test_transition_detection` | 新测试 | 传入 previous_phase 后正确检测转换 |
| `test_transition_confidence_boost` | 新测试 | 特定转换获得置信度加分 |
| `test_transition_no_previous` | 新测试 | previous_phase=None 时行为不变 |

### 6.4 验证指标

```
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p3

预期:
  H5 转换预测: ❌ → ✅ (p < 0.05)
  distribution→accumulation 转换收益: +2.76% → 维持或提升
  H7 策略净收益: 改善（因转换信号更可靠）
```

---

## 7. Phase 4: 置信度重算

### 7.1 问题诊断

当前置信度规则 8（5 条件矩阵）与真实收益负相关。L1_strictest (0.01% 密度) 收益 -1.80%，L3_moderate (8.72% 密度) 收益 +0.84%。

### 7.2 代码修改

#### 文件: `src/uniquant/brain/wyckoff/engine.py`

**修改 1: 新增"位置置信度"维度**（置信度计算函数，第 1290-1357 行附近）

```python
def _compute_position_confidence(self, phase, ctx, step3) -> float:
    """计算价格位置置信度 (0-1)"""
    confidence = 0.5  # 基准

    if phase == WyckoffPhase.ACCUMULATION:
        # 积累在低位时置信度高
        if ctx["relative_position"] <= 0.30:
            confidence += 0.3
        elif ctx["relative_position"] <= 0.50:
            confidence += 0.1
        else:
            confidence -= 0.2  # 高位积累不可信
    elif phase == WyckoffPhase.MARKUP:
        # Markup 在刚突破时置信度高
        if ctx["relative_position"] <= 0.60:
            confidence += 0.3
        elif ctx["relative_position"] <= 0.75:
            confidence += 0.1
        else:
            confidence -= 0.2  # 高位 markup 不可信
    elif phase == WyckoffPhase.DISTRIBUTION:
        # 派发在高位时置信度高
        if ctx["relative_position"] >= 0.70:
            confidence += 0.3
        elif ctx["relative_position"] >= 0.50:
            confidence += 0.1
        else:
            confidence -= 0.2
    elif phase == WyckoffPhase.MARKDOWN:
        # Markdown 在刚跌破时置信度高
        if ctx["relative_position"] >= 0.40:
            confidence += 0.3
        elif ctx["relative_position"] >= 0.25:
            confidence += 0.1
        else:
            confidence -= 0.2  # 低位 markdown 不可信

    return max(0.0, min(1.0, confidence))
```

**修改 2: 新增"相位持续时间"置信度调整**（H6 验证: 4-6 月最佳）

```python
def _compute_duration_confidence(self, step1, previous_phase, duration_months: int = 0) -> float:
    """基于相位持续时间的置信度调整 (H6 验证)"""
    if duration_months <= 0:
        return 0.0
    if 4 <= duration_months <= 6:
        return 0.2  # 最佳区间
    elif 1 <= duration_months <= 3:
        return 0.1  # 早期
    elif 7 <= duration_months <= 12:
        return -0.1  # 过久
    else:
        return -0.2  # 太久
```

**修改 3: 整合到最终置信度**

```python
# 最终置信度 = 原规则 8 置信度 + 位置置信度 × 0.5 + 持续时间置信度 × 0.3
final_confidence = base_confidence + position_conf * 0.5 + duration_conf * 0.3
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
运行: python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p4

预期:
  L1_strictest 收益:  -1.80% → +3~5%  (方向反转)
  L3_moderate 收益:   +0.84% → +2~4% (维持或提升)
  置信度与收益: 负相关 → 正相关
```

---

## 8. Phase 5: 调仓策略优化

### 8.1 问题诊断

当前 H7 策略每月调仓，换手率 2.4%/月，年化成本 6.67%/月，净收益 -50.1%。

### 8.2 代码修改

#### 文件: `scripts/wyckoff_multitf/runner_v3.py`

**修改 1: 仅在相位转换时调仓**（函数 `test_h7_backtest`，第 407-477 行）

```python
# ── 当前逻辑 ──
# 每月调仓: 所有 accumulation+markup 股票
in_strategy = [o for o in at_cutoff if o.month_phase in ("accumulation", "markup")]

# ── 改为 ──
# 仅在相位转换时调仓
# 使用 previous_phase 判断转换
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

### 9.1 验证流程

```
每次修改后:
  1. ruff check src/ tests/ scripts/    (0 容忍)
  2. pytest tests/classic_wyckoff/ -q   (132 测试全过)
  3. python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _verify
     (7.5 分钟，验证相位分布和收益方向)
  4. 对比预期指标 vs 实际指标
  5. 偏差 > 5% 则回滚
```

### 9.2 关键指标监控

| 指标 | 阈值 | 通过条件 |
|------|------|---------|
| accumulation 占比 | 25-35% | 在此范围内 |
| markup 占比 | 12-22% | 在此范围内 |
| distribution 占比 | 12-22% | 在此范围内 |
| markdown 占比 | 12-22% | 在此范围内 |
| markup 收益均值 | > 0% | 正收益 |
| markdown 收益均值 | < 0% | 负收益 |
| H1 ANOVA p值 | < 0.05 | 显著 |
| 现有测试 | 100% | 全部通过 |
| ruff | 0 | 0 错误 |

### 9.3 A/B 对比方案

每次修改后，保存验证结果到 `scripts/wyckoff_multitf/output_v3_ab/` 目录

```bash
# 基线 (Phase 0 前)
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _baseline

# Phase 0
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p0

# Phase 1
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p1

# Phase 2
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _p2

# 对比
python3 -c "
import json
for suffix in ['baseline', 'p0', 'p1', 'p2']:
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
git revert <commit_p0>

# 或回滚到某个阶段
git checkout <commit_before_p0> -- src/uniquant/brain/wyckoff/pnf.py
git checkout <commit_before_p0> -- src/uniquant/brain/wyckoff/engine.py
```

### 10.2 配置回滚

所有阈值修改在 calibration 字典中配置，支持运行时切换：

```python
# 在 config.yaml 中:
wyckoff:
  calibration_v2:
    enabled: false  # 关闭所有 v2 修改
    pnf_symmetry: true
    accum_tighten: true
    markup_early: true
```

---

## 附录 A: 文件修改清单

| 文件 | 修改函数 | 修改类型 | 影响范围 |
|------|---------|---------|---------|
| `pnf.py` | `wyckoff_phase_hint` | 阈值调整 | Phase 0 |
| `engine.py` | `_step1_phase_determine` | P&F 覆盖逻辑 | Phase 0 |
| `engine.py` | `_detect_accumulation` | 3 条路径收紧 + 拒绝条件 | Phase 1 |
| `engine.py` | `_detect_markup` | 新增早期路径 + 降低门槛 | Phase 2 |
| `engine.py` | `_detect_markdown` | 新增早期路径 + 降低门槛 | Phase 2 |
| `engine.py` | `_step1_phase_determine` | 检测器顺序调整 | Phase 2 |
| `engine.py` | `_analyze_single` | 传入 previous_phase | Phase 3 |
| `engine.py` | `Step1Result` | 增加 transition 字段 | Phase 3 |
| `engine.py` | 置信度函数 | 新增位置/持续时间置信度 | Phase 4 |
| `runner_v3.py` | `test_h7_backtest` | 转换驱动调仓 | Phase 5 |

## 附录 B: 新增测试文件

| 测试文件 | 测试内容 | 预期数量 |
|---------|---------|---------|
| `tests/classic_wyckoff/test_phase4_pnf_symmetry.py` | P&F 对称化验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase4_accum_tighten.py` | 积累收紧验证 | 6-8 测试 |
| `tests/classic_wyckoff/test_phase4_markup_early.py` | Markup 前瞻化验证 | 4-6 测试 |
| `tests/classic_wyckoff/test_phase4_markdown_early.py` | Markdown 前瞻化验证 | 4-6 测试 |
| `tests/classic_wyckoff/test_phase4_transition.py` | 相位转换检测验证 | 4-6 测试 |
| `tests/classic_wyckoff/test_phase4_confidence.py` | 置信度重算验证 | 6-8 测试 |