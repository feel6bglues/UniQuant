# Wyckoff 相位再平衡 — 最终验证方案 v3.1

**基于 52,586 观测值（1,000 只 A 股 × 53 月）实证验证**
**分析日期**: 2026-08-06
**验证脚本**: `v9_v2_medium_validation.py`, `v9_v3_validation.py`

---

## 1. 三轮红蓝对抗总结

### Round 1: v3.0 P&F 阈值校准（52K 观测验证）

**红队论点**: P&F 阈值修改会导致 P&F 死亡（如 v1/v2 方案所示）。当前阈值 63/23/14 分布合理，问题仅在覆盖层。

**蓝队论点**: 需要校准阈值以平衡积累/分布比例。

**实证裁决: 红队胜**:
- 所有候选阈值（A1-A5, D1-D4）均导致 P&F 99.8%+ unknown
- 当前阈值 63.0% accum / 23.1% dist / 13.9% unknown — 分布合理
- **P&F 阈值不需要修改。覆盖层移除是唯一需要的修复。**

### Round 2: Phase 1 markdown rp 约束（52K 观测验证）

**红队论点**: rp 约束会过度过滤 markdown（低于 15-25% 目标）。

**蓝队论点**: rp=0.20 是最佳平衡点。

**实证裁决: 蓝队部分胜**:
| rp 阈值 | 剩余 markdown | 均值回复过滤 | 方向正确性 |
|---------|--------------|-------------|-----------|
| 0.10 | 18.8% | 59.6% | -0.14% (接近 0) |
| **0.15** | **11.4%** | **75.5%** | **-0.55% (接近正确)** |
| 0.20 | 6.5% | 85.9% | -0.56% (正确) |
| 0.25 | 2.9% | 93.7% | -2.65% (正确) |

- **rp=0.15 是最佳选择**: 11.4% 接近 15-25% 目标，方向 -0.55% 接近正确
- rp=0.20 过度过滤（6.5% 低于目标）
- 过滤出的均值回复 markdown（rp<0.15）有 +3.18% 收益 — 正确过滤

### Round 3: Phase 2 市场状态自适应检测（52K 观测验证）

**红队论点**: 市场状态自适应不能完全修复方向反转。markup 在熊市和震荡中仍然方向错误。

**蓝队论点**: 市场状态自适应是修复方向反转的唯一途径。

**实证裁决: 红队部分胜**:
- 牛市: markup +4.61% ✅（正确方向）
- 熊市: markup -1.80% ❌（仍错误，但比 -4.23% 改善）
- 震荡: markup -3.71% ❌（仍错误）
- 自适应抑制后: markup 16.0% → 15.5%（改善有限）
- **方向反转是部分修复但不是完全修复。markup 在熊市和震荡中仍然方向错误，因为 markup 检测器本质上是动量指标，在非牛市中任何反弹都是均值回复。**

---

## 2. 最终方案 v3.1

### 2.1 核心修改

| 修改 | 文件 | 具体变更 | 预期影响 |
|------|------|---------|---------|
| **P0**: 移除 P&F 覆盖层 | `engine.py` | 检测器链为唯一相位来源 | accum 63.2% → 0.6% |
| **P1**: markdown rp=0.15 约束 | `engine.py` | `_detect_markdown` 添加 rp≥0.15 | markdown 46.4% → 11.4% |
| **P2**: 市场状态自适应 | `market_state.py` + `engine.py` | 新增 market_state 检测器 | markup 方向改善 |

### 2.2 预期指标

| 指标 | 当前 | Phase 0 | Phase 1 | Phase 1+2 | 最终目标 |
|------|------|---------|---------|-----------|---------|
| accum 占比 | 63.2% | 0.6% | 0.6% | 0.6% | 3-8% |
| markup 占比 | 3.0% | 16.0% | 16.0% | 15.5% | 12-18% |
| distribution 占比 | 22.5% | 12.0% | 12.0% | 12.0% | 10-15% |
| markdown 占比 | 7.1% | 46.4% | **11.4%** | **10.0%** | 10-20% |
| unknown 占比 | 4.2% | 24.9% | 60.0% | 61.9% | 40-60% |
| markup 3m 收益 | -0.84% | -1.64% | -1.64% | -1.55% | +1~3% |
| markdown 3m 收益 | +1.67% | +2.27% | **-0.55%** | **-1.13%** | -1~-3% |

### 2.3 代码修改

#### Phase 0: 移除 P&F 覆盖层

**文件**: `engine.py`, `_step1_phase_determine`（第 836-849 行）

```python
# P&F hint 不再覆盖检测器链，改为仅记录分歧
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

#### Phase 1: Markdown rp=0.15 约束

**文件**: `engine.py`, `_detect_markdown`

```python
# 在 TR 外路径 1 添加 rp 约束
if st <= st_max and cp < ma20 * cp_below_ma:
    if ctx["relative_position"] >= 0.15:  # 新增: rp 约束
        if len(df) >= 5:
            vol_5 = float(df.tail(5)["volume"].mean())
            vol_20 = float(df.tail(20)["volume"].mean()) if len(df) >= 20 else vol_5
            if vol_20 > 0 and vol_5 > vol_20 * 1.1:
                return {"phase": WyckoffPhase.MARKDOWN}
```

#### Phase 2: 市场状态自适应检测

**新增文件**: `market_state.py`

```python
from enum import Enum
import numpy as np
import pandas as pd


class MarketState(Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


def detect_market_state(index_df: pd.DataFrame, lookback_months: int = 12) -> MarketState:
    if index_df is None or len(index_df) < lookback_months:
        return MarketState.NEUTRAL
    df = index_df.tail(lookback_months)
    ma6 = df["close"].iloc[-6:].mean()
    ma12 = df["close"].mean()
    ratio = ma6 / ma12
    if ratio > 1.05:
        return MarketState.BULL
    elif ratio < 0.95:
        return MarketState.BEAR
    return MarketState.NEUTRAL
```

**文件**: `engine.py`, `_detect_markup`

```python
def _detect_markup(self, df, ctx, rule0, market_state=None):
    # 熊市: markup 需要更强证据
    if market_state == MarketState.BEAR:
        if ctx["short_trend_pct"] < 0.03:
            return None
        if ctx["current_price"] < ctx["ma20"] * 1.02:
            return None
    # 牛市: markup 正常触发
    # ... 现有检测逻辑 ...
```

**文件**: `engine.py`, `_detect_markdown`

```python
def _detect_markdown(self, df, ctx, rule0, market_state=None):
    # 牛市: markdown 需要更强证据
    if market_state == MarketState.BULL:
        if ctx["short_trend_pct"] > -0.05:
            return None
        if ctx["current_price"] > ctx["ma20"] * 0.95:
            return None
    # ... 现有检测逻辑（含 Phase 1 rp 约束）...
```

### 2.4 验证脚本

| 脚本 | 功能 | 输入 |
|------|------|------|
| `v9_v2_medium_validation.py` | 52K 观测全面验证 | `--max-stocks 1000` |
| `v9_v3_validation.py` | Phase 1+2 组合仿真 | 直接运行（加载 52K 数据） |
| `v9_rb_validation.py` | P&F 覆盖层反事实 | `--max-stocks 500` |

### 2.5 验证指标

```
运行: python3 scripts/wyckoff_multitf/v9_v3_validation.py

预期:
  markdown 占比: 46.4% → 11.4% (rp=0.15)
  markdown 3m 收益: +2.27% → -0.55% (方向修复)
  markup 占比: 16.0% → 15.5% (自适应抑制)
  unknown 占比: 24.9% → 60.0% (合理储备态)
```

### 2.6 回滚方案

```yaml
wyckoff:
  calibration_v3:
    enabled: false
    pnf_override_removed: true
    markdown_rp_threshold: 0.15
    market_state_adaptive: false
```

---

## 3. 文件输出清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `docs/analysis/WYCKOFF_PHASE_REBALANCE_IMPLEMENTATION_PLAN_v3.md` | 896 行 | v3.0 方案 |
| `docs/analysis/WYCKOFF_PHASE_REBALANCE_IMPLEMENTATION_PLAN_v3.1.md` | 本文件 | 最终验证方案 |
| `scripts/wyckoff_multitf/v9_v2_medium_validation.py` | 52K 观测采集 | 引擎 + 上下文数据 |
| `scripts/wyckoff_multitf/v9_v3_validation.py` | Phase 1+2 仿真 | 市场状态 + rp 约束 |
| `scripts/wyckoff_multitf/v9_rb_validation.py` | P&F 反事实 | 原 monkeypatch 验证 |
| `scripts/wyckoff_multitf/output_v2_validation/v2_medium_rows.json` | 52,586 观测 | 原始数据 |
| `scripts/wyckoff_multitf/output_v3_validation/v3_validation_summary.json` | 验证摘要 | 数值结果 |