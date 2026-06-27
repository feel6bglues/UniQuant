# Phase 6 修复计划 — 信号链完整 + 质量过滤 + 路径验证

> 基于 Phase 5 三角色评估（算法78/架构82/交易员65）识别的跨层信号丢失和仲裁器盲区
> 共计 6 项修复（P6.1–P6.6），跨越 5 个文件，总估算工时 ~3h

---

## 问题全景

```
Brain 层 (有完整语义)         Signal 层 (丢失)           Hands 层 (盲区)
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│ LPPLOutput   │          │ TradingSignal│          │ Arbitrator   │
│  R²: 0.81    │  ──────→ │  confidence  │  ──────→ │  只比conf    │
│  OOS: 0.62   │  丢失    │  reason      │  丢失    │  看不到R²    │
│  model_params│   P6.1   │  action      │   P6.2   │  无法过滤    │
└──────────────┘   P6.2   └──────────────┘    P6.5  └──────────────┘
                                                            ↑
┌──────────────┐          ┌──────────────┐                  │
│ WyckoffOutput│          │ TradingSignal│                  │
│  phase: Acc  │  ──────→ │  confidence  │  ────────────────┘
│  bypassed    │  丢失    │  reason      │   P6.3
│  rr_ratio    │   P6.3   │  action      │
└──────────────┘          └──────────────┘

calc_structural_risk_matrix ──→ 跳过 detect_bubble() → 无 OOS R²  →  P6.4

_calc_confidence bypass ──→ 无 full R8 对比 →  bypass 正确性未知 →  P6.6
```

---

## 文件冲突矩阵

| 文件 | 涉及任务 | 冲突组 |
|---|---|---|
| `shared/interfaces.py` | P6.1 | **I** |
| `signal/adapters.py` | P6.2, P6.3 | **S** |
| `signal/arbitrator.py` | P6.5 | **S** |
| `brain/lppl/engine.py` | P6.4 | **L** |
| `scripts/lppl_wyckoff_cross_validation.py` | P6.6 | **V** |

---

## 任务编排（最大并行度：4）

### Wave 1 — Day 1（4 任务并行）

| 轨道 | 任务 | 文件 | 变更 | 工时 |
|---|---|---|---|---|
| **I** | **P6.1** `TradingSignal` 新增 `metadata: Dict[str, Any] = {}` | `interfaces.py` | +2 | 0.1h |
| **S1** | **P6.2** `LPPLAdapter` 传递 `r_squared`/`out_of_sample_r_squared` 到 metadata | `adapters.py` | +5 | 0.3h |
| **S2** | **P6.3** `WyckoffAdapter` 传递 `phase`/`bypassed`/`rr_ratio` 到 metadata | `adapters.py` | +5 | 0.3h |
| **L** | **P6.4** `calc_structural_risk_matrix` 改用 `detect_bubble()` 获取 OOS R² | `engine.py` | +3 | 0.2h |

### Wave 2 — Day 1-2（2 任务并行）

| 轨道 | 任务 | 文件 | 变更 | 工时 |
|---|---|---|---|---|
| **S** | **P6.5** `SignalArbitrator` 增加 `_quality_threshold: float`，LPPL SELL 信号 OOS R² < 0.3 不执行 | `arbitrator.py` | +10 | 0.5h |
| **V** | **P6.6** 验证脚本：`_calc_confidence` debug 模式对比 bypass vs full R8 | `scripts/lppl_wyckoff_cross_validation.py` | +25 | 1h |

---

## 代码交叉核查结果

| 任务 | 核查结果 | 发现 |
|---|---|---|
| P6.1 | ✅ 确认可行 | `interfaces.py:148-161` `TradingSignal` 7 字段，无 metadata。`field(default_factory=dict)` 向后兼容 |
| P6.2 | ✅ 确认可行 | `adapters.py:76-101` `raw_output` 来自 `LPPLOutput.to_dict()` 含 `r_squared`/OOS R²，适配器忽略——加 2 行即可 |
| P6.3 | ⚠️ 范围需扩大 | `adapters.py:160-185` 适配器需要 `rr_ratio` 和 `bypassed`，但 `_extract_wyckoff()`（行 582-589）不传递这些字段。需同时修改 extract 和 adapter |
| P6.4 | ✅ 确认可行 | `engine.py:1082` `self.calculator.fit()` → `self.detect_bubble()`。返回 dict 格式完全兼容 |
| P6.5 | ✅ 确认可行 | `arbitrator.py:152-166` SELL 优先规则之前可插入质量检查。`TradingSignal.metadata` 提供 OOS R² 来源 |
| P6.6 | ✅ 确认可行 | `engine.py:862-876` 2 条 bypass 路径，加 `_debug_r8_compare` flag 跑 full R8 对比 |

## 代码级规格（三角色审议通过）

### P6.1 — `TradingSignal.metadata`（算法: ✅ 架构: ✅ 交易: ✅）

```python
@dataclass
class TradingSignal:
    action: str
    reason: str = ""
    confidence: float = 0.0
    shares: int = 0
    symbol: str = ""
    price: float = 0.0
    timestamp: Optional[datetime.datetime] = field(default=None, repr=False)
    metadata: Dict[str, Any] = field(default_factory=dict)  # 新增
```

**设计理由**：不破坏已有消费者。`metadata` 默认空 dict，所有现有 `TradingSignal(...)` 构造不受影响。下游消费者按需读取。

### P6.2 — LPPLAdapter 传递质量字段（算法: ✅ 架构: ✅ 交易: ✅）

```python
# adapters.py LPPLAdapter.adapt() return 前
return TradingSignal(
    ...
    metadata={
        "r_squared": float(raw_output.get("r_squared", 0.0)),
        "out_of_sample_r_squared": float(raw_output.get("out_of_sample_r_squared", 0.0)),
    },
)
```

`raw_output` 来自 `LPPLOutput.to_dict()`，包含 `r_squared` 和 `out_of_sample_r_squared`。

### P6.3 — WyckoffAdapter 传递阶段字段（算法: ✅ 架构: ✅ 交易: ✅）

```python
# adapters.py WyckoffAdapter.adapt() return 前
return TradingSignal(
    ...
    metadata={
        "wyckoff_phase": phase,
        "wyckoff_spring": spring,
        "wyckoff_utad": utad,
        "wyckoff_rr_ratio": float(raw_output.get("rr_ratio", 0.0)),
        "wyckoff_bypassed": raw_output.get("bypassed", False),
    },
)
```

### P6.4 — `calc_structural_risk_matrix` 改用 `detect_bubble()`（算法: ✅ 架构: ✅ 交易: ✅）

```python
# engine.py:1082 原代码
result = self.calculator.fit(df, "close")
# 改为
result = self.detect_bubble(df, "close")
```

`detect_bubble()` 返回的 dict 与 `calculator.fit()` 完全兼容（增加 `out_of_sample_r_squared` 键），无破坏性。

### P6.5 — Arbitrator 质量过滤（算法: ✅ 架构: ⚠️ 需讨论 tradeoff 交易: ✅）

```python
class SignalArbitrator:
    def __init__(self, ..., quality_threshold: float = 0.3):
        self._quality_threshold = quality_threshold

    def _pick_winner(self, day_signals, symbol, date_key):
        # 在规则1（SELL优先）之前插入质量检查
        for sig in actionable:
            oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)
            if oos_r2 < self._quality_threshold and sig.action == "SELL":
                # OOS 拟合质量差 → 降级为 HOLD
                log.rejection_reasons.append(
                    f"quality_gate: rejected SELL from {sig.reason} "
                    f"(OOS R²={oos_r2:.2f} < {self._quality_threshold})"
                )
                actionable.remove(sig)
```

**架构师注**：这会改变仲裁行为——原本 OOS R²=0.2 的 LPPL SELL 会被执行，加了过滤后不会。需要默认值保守（0.3 已在 plan 中），并通过 `quality_threshold=0.0` 关闭过滤。

### P6.6 — Bypass vs full R8 对比验证（算法: ✅ 架构: ✅ 交易: ❌ 低优先级）

在 `WyckoffEngine` 中添加 `_debug_r8_compare: bool = False` 模式。启用时，`_calc_confidence` 即使满足 bypass 条件也继续执行 full R8 矩阵，记录对比结果。

**交易员注**：正确性验证有价值，但实战中 bypass 路径的 C 级和 full R8 的 C 级结果相同——改变的概率很低。ROI 相对较低。

---

## 依赖关系图

```
Wave 1 (完全并行)
  P6.1 (interfaces.py)  ───┐
  P6.2 (adapters.py)    ───┤  同时执行
  P6.3 (adapters.py)    ───┤
  P6.4 (engine.py)      ───┘

Wave 2 (并行)
  P6.5 (arbitrator.py) ← 依赖 P6.1 + P6.2 (需要 TradingSignal.metadata + LPPL OOS R²)
  P6.6 (scripts/)      ← 需要 WyckoffEngine 支持 (engine.py 新增 debug 模式)
```

---

## 风险登记册

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `TradingSignal` 新增 `metadata` 字段破坏序列化 | 低 | 中 | `field(default_factory=dict)` 确保向后兼容 |
| `calc_structural_risk_matrix` 改用 `detect_bubble()` 引入性能开销 | 低 | 低 | `detect_bubble()` 的 OOS 计算 ~0.1ms/次 |
| 质量阈值误杀有效 SELL 信号 | 中 | 高 | 默认值 0.3 保守；可通过 `quality_threshold=0.0` 关闭 |
| bypass vs full R8 对比显示无差异 | 高 | 低 | 说明 bypass 道路正确——也是有用信息 |
