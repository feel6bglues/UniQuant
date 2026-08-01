# 管线可靠性验证 — 执行计划

> 基于 VERIFIED_WORKLIST_20260717.md 全量验证 + 红蓝对抗修正后编排
> 红蓝对抗报告: `docs/remediation/REN_BLUE_EXECUTION_PLAN_20260717.md`
> 总预计工时: **~14.5h**, 并行 4 轨道最快 **~4.5h**

---

## 依赖关系图

```
Phase 0 (基线)
  ├─ P0-A: 基线捕获 ──── 无依赖
  ├─ P0-B: LPPL 路径统一 ── 无依赖
  └─ P0-C: Spring 验真 ─── 无依赖 (脚本独立加载数据)

Phase 1 (工程)
  ├─ P1-A: 文档修复 ──── 无依赖
  ├─ P1-B: Wyckoff 测试 ── 无依赖
  └─ P1-C: IC 半衰期 ──── 设计先行, 需理解 Analyzer IC 机制

Phase 2 (增强)
  ├─ P2-A: ATR 自适应 ─── 依赖于 P0-B (同文件 engine.py, 需串行)
  ├─ P2-B: 跨引擎测试 ─── 依赖 P0-A (基线数据)
  └─ P2-C: 控制文档同步 ── 依赖全部完成
```

---

## Phase 0 — 立即执行 (预计 4h)

### P0-A: 基线捕获与回归验证

| 属性 | 内容 |
|------|------|
| 目标 | 更新 golden baseline, 确保后续变更可追踪 |
| 文件 | `scripts/capture_baseline.py`, `scripts/compare_baseline.py` |
| 验证 | `scripts/capture_baseline.py` → `scripts/compare_baseline.py` 全绿 |
| 预计 | 30min |

```bash
# 执行
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py
```

**验收标准**: baseline capture 成功, compare 输出 0 diff。

---

### P0-B: LPPL `_process_window` 优化器路径统一

| 属性 | 内容 |
|------|------|
| 目标 | 将 `_process_window` 从 DE 优化器切换到 L-BFGS-B, 统一引擎内优化路径 |
| 风险 | 中 — 输出数值可能变化, 需更新基线 |
| 预计 | 1.5h |

**修改文件**: `src/uniquant/brain/lppl/engine.py`

**变更 1 — `_process_window` 切换为 L-BFGS-B** (行 993-1000):

`fit_single_window_lbfgsb` 和 `LPPLConfig` 均已在 `engine.py` 中定义, 直接调用, 无需额外 import:

```python
@staticmethod
def _process_window(df, window):
    try:
        subset = df["close"].iloc[-window:].values
        config = LPPLConfig(window_range=[window])
        res = fit_single_window_lbfgsb(subset, window, config)
        if res and res.get("rmse", float("inf")) < LPPLConstants.RMSE_REJECT_THRESHOLD:
            res["window"] = window
            return res
    except LPPL_ENGINE_RECOVERABLE_ERRORS:
        logger.exception("单窗口 LPPL 拟合失败")
    return None
```

**变更 2 — `detect_bubble()` 保持 calculator D E 路径不变** (行 1007-1010):

添加注释标记, 确认当前路径为设计选择:

```python
def detect_bubble(self, df: pd.DataFrame, column: str = "close") -> Dict[str, Any]:
    # calculator.fit() 路径 (L-BFGS-B 主优化, DE 降级, 3-param variable projection)
    # 与 scan_all_windows() (7-param 全量 L-BFGS-B) 构成双路径 API
    # ⚠ R² 口径不同: 本方法使用 3-param variable projection (线性参数解析最优),
    #   scan_all_windows 使用 7-param 全局优化 (线性与非线性同时求解),
    #   两者 R² 绝对值不可直接比较
    result = self.calculator.fit(df, column)
    ...
```

**验证**:
```bash
pytest tests/brain/lppl/ tests/test_lppl_real_data.py tests/test_lppl_calculator_defense.py tests/test_lppl_engine_scan_windows.py -x -q
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py
```

**验收标准**: 测试全部通过 (当前 254 → 仍 ≥254), baseline 一致或已更新。

---

### P0-C: Spring/ACCUMULATION 真实数据验真

| 属性 | 内容 |
|------|------|
| 目标 | 在 golden_20 上运行 Wyckoff, 确认 Spring 触发率和 ACCUMULATION 率 |
| 文件 | `scripts/lppl_wyckoff_cross_validation.py` (已有 H12 诊断, 已加固) |
| 预计 | 1.5h |

脚本自动运行全部 H1-H12 诊断，无需指定诊断类型:

```bash
python3 scripts/lppl_wyckoff_cross_validation.py --stocks golden_20
```

> ⚠ **脚本已加固 (2026-07-20)**:
> - Spring 检测: `(signal.signal_type or "").lower() == "spring"` 防御 None/大小写
> - Step3 re-run: `except Exception: pass` → `except (AttributeError,TypeError,ValueError,KeyError) as e: print(...)`
> - Counterfactual: 同上窄化 + 日志
> - H12 裁决: 三态 `CONFIRMED`/`NOT_CONFIRMED`/`NOT_TESTED` 区分零事件场景

**验收标准**: 输出报告包含:
- Spring 触发次数 / 总股票数
- ACCUMULATION 阶段占比 (预期 <20% UNKNOWN)
- A/B+/C 级置信度分布

---

## Phase 1 — 短期执行 (预计 5h)

### P1-A: `repair_plan_lppl_wyckoff.md` 修复状态更新

| 属性 | 内容 |
|------|------|
| 目标 | 在文档头部添加状态横幅, 标注 11 项已修复, 降级为历史参考 |
| 风险 | 无 |
| 预计 | 30min |

**修改文件**: `docs/repair_plan_lppl_wyckoff.md`

在文件顶部添加:

```markdown
> **⚠️ 状态: 历史参考 (2026-07-17 验证)**
>
> 本文档列出的 **P0.1~P3.5 共 11 项修复已全部在代码中实施**。
> 保留作为架构设计参考, 但"待修复"声明已过时。
> 当前验证结果详见 `docs/remediation/VERIFIED_WORKLIST_20260717.md`。
```

**验收标准**: 文档头部醒目提示, 读者不会误读为待办清单。

---

### P1-B: Wyckoff `_step4_risk_reward` 单元测试补充

| 属性 | 内容 |
|------|------|
| 目标 | 为 88 行多源目标位逻辑补充单元测试 |
| 文件 | `tests/test_wyckoff_new_features.py` (追加) |
| 预计 | 2h |

使用 brain 级 `WyckoffEngine` 直接构造, 不依赖 orchestrator。

**测试场景** (完整可运行代码):

```python
# tests/test_wyckoff_new_features.py 追加

def test_step4_risk_reward_tr_upper_source(self, sample_df):
    """TR 上沿作为目标位来源"""
    engine = WyckoffEngine()
    step1 = Step1Result(
        phase=WyckoffPhase.ACCUMULATION, boundary_upper=15.0,
        boundary_lower=10.0, boundary_source="manual",
        is_in_tr=True,
    )
    step3 = Step3Result(spring_detected=True, spring_low_price=10.0)
    rule0 = Rule0Result(
        bc_found=True, tr_upper=15.0, tr_lower=10.0,
        validity="full", confidence_base="B",
    )
    rr = engine._step4_risk_reward(sample_df, step1, step3, rule0)
    assert rr.first_target_source == "tr_upper"
    assert rr.rr_ratio > 0

def test_step4_risk_reward_bearish_candle_source(self, sample_df_with_bearish):
    """大阴线起跌点作为目标位"""
    engine = WyckoffEngine()
    step1 = Step1Result(boundary_upper=0.0, boundary_lower=0.0, boundary_source="manual")
    step3 = Step3Result(spring_detected=True, spring_low_price=10.0)
    rule0 = Rule0Result(bc_found=True, tr_upper=0.0, tr_lower=0.0, validity="full")
    rr = engine._step4_risk_reward(sample_df_with_bearish, step1, step3, rule0)
    assert rr.first_target_source in ("bearish_candle", "tr_upper_fallback")

def test_step4_risk_reward_gap_source(self, sample_df_with_gap):
    """跳空缺口下沿作为目标位"""

def test_step4_risk_reward_atr_stop_loss(self, sample_df):
    """ATR 1 倍止损位计算"""
    engine = WyckoffEngine()
    step1 = Step1Result(boundary_upper=15.0, boundary_lower=10.0, boundary_source="manual")
    step3 = Step3Result(spring_detected=True, spring_low_price=10.0)
    rule0 = Rule0Result(bc_found=True, tr_upper=15.0, tr_lower=10.0, validity="full")
    rr = engine._step4_risk_reward(sample_df, step1, step3, rule0)
    assert rr.stop_loss > 0
    assert rr.rr_verdict in ("pass", "fail")
```

**验证**:
```bash
pytest tests/test_wyckoff_new_features.py -x -v -k "step4"
```

**验收标准**: ≥4 个 step4 测试, 覆盖 TR 上沿/大阴线/跳空/ATR 止损 4 种目标位来源。

---

### P1-C: Factor IC 半衰期加权设计

| 属性 | 内容 |
|------|------|
| 目标 | 为因子 IC 权重引入指数衰减, 使近期 IC 权重高于远期 |
| 文件 | `src/uniquant/brain/factors/composer.py`, `src/uniquant/brain/factors/analyzer.py`, `src/uniquant/brain/factors/registry.py` |
| 风险 | 中 — 涉及因子系统行为变更 |
| 预计 | 设计 1h + 编码 2h + 测试 1h = **4h** |

> ⚠️ `FactorInfo` 已有 `ic_ir_history: Optional[List[float]]` 字段。以下设计复用该字段(或将数据类型从 `Optional` 扩展为 `List[float]`), 不新增命名冲突的 `ic_history` 字段。
>
> `FactorAnalyzer` 已有 `compute_rank_ic()` 和 `compute_ic_ir()` 方法, 设计需整合现有 IC 计算链路。

**设计方案**:

```python
# composer.py _resolve_weights() 中新增
def _apply_ic_decay(self, ic_history: List[float], half_life: int = 60) -> float:
    """IC 指数衰减加权: 近期 IC 权重 > 远期 IC 权重"""
    n = len(ic_history)
    if n == 0:
        return 0.0
    weights = np.exp(-np.log(2) * np.arange(n) / half_life)
    weights = weights / weights.sum()
    return float(np.sum(np.array(ic_history) * weights))
```

```python
# FactorRegistry — 复用已有 ic_ir_history 字段
@dataclass
class FactorInfo:
    ...
    ic_ir_history: Optional[List[float]] = None  # 已有, 扩展为 IC 时间序列
    half_life_days: int = 60  # 新增: IC 半衰期
```

**验收标准**:
- `_apply_ic_decay([0.1, 0.2, 0.3], half_life=60)` → 结果偏向近期 0.3
- 现有测试全部通过, 默认 half_life 不改变现有行为

---

## Phase 2 — 中期执行 (预计 6h)

### P2-A: LPPL `classify_top_phase` ATR 自适应偏移

| 属性 | 内容 |
|------|------|
| 目标 | 用 ATR 百分比替代固定 -0.15 降噪偏移 |
| 文件 | `src/uniquant/brain/lppl/engine.py` |
| 风险 | 低 |
| 预计 | 1h |

```python
# engine.py ~line 108-122
def classify_top_phase(days_left: float, r2: float, config: LPPLConfig,
                       price_ret: Optional[float] = None,
                       atr_pct: Optional[float] = None) -> str:
    if days_left < 0:
        return "none"

    adjusted_r2 = r2
    if atr_pct is not None and atr_pct > 0:
        # ATR 自适应: 低波股票更严格 (r2 下调更多)
        if atr_pct < 2.0:
            adjusted_r2 = r2 - 0.20
        elif atr_pct < 4.0:
            adjusted_r2 = r2 - 0.10
        # ATR >= 4.0 的高波股票不做降噪
    elif price_ret is not None and abs(price_ret) < 0.10:
        adjusted_r2 = r2 - 0.15  # fallback
    ...
```

**验证**:
```bash
pytest tests/brain/lppl/ -x -q
```

**验收标准**: 测试全部通过, 新增参数 atr_pct 不破坏现有调用。

---

### P2-B: 跨引擎集成测试

| 属性 | 内容 |
|------|------|
| 目标 | LPPL→Wyckoff→Factor 三引擎联合压力测试 |
| 文件 | `tests/test_e2e_integration_qa.py` (已有框架, 追加) |
| 预计 | 4h |

> ⚠️ 使用 brain 级引擎 (`LPPLEngine`, `WyckoffEngine`) 而非 orchestrator 级 (`LpplAnalysisEngine`, `WyckoffAnalysisEngine`), 避免 orchestrator 依赖。`LpplAnalysisEngine` 在传 df 时可工作, 但 `WyckoffAnalysisEngine` 即使传 df 也强制访问 orchestrator。

**测试场景**:
```python
from uniquant.brain.lppl.engine import LPPLEngine
from uniquant.brain.wyckoff.engine import WyckoffEngine

def test_lppl_wyckoff_signal_consistency(self, real_stock_df):
    """LPPL Danger + Wyckoff Accumulation 不应同时出现 (矛盾信号)"""
    lppl_result = LPPLEngine().detect_bubble(real_stock_df)
    wyckoff_result = WyckoffEngine().analyze(real_stock_df, multi_timeframe=True)
    lppl_risk = lppl_result.get("risk_level", "Safe")
    wyckoff_phase = str(wyckoff_result.phase).lower()
    assert not (lppl_risk == "Danger" and "accumulation" in wyckoff_phase)

def test_factor_composer_with_real_data(self, real_stock_df):
    """因子合成器在真实数据上不崩溃"""
    composer = FactorComposer()
    result, diag = composer.compose_scores(real_stock_df, return_diagnostics=True)
    assert diag["composite_usable"]
```

**验证**:
```bash
pytest tests/test_e2e_integration_qa.py -x -v -k "lppl_wyckoff or factor"
```

**验收标准**: 新增测试 ≥3 个, 覆盖矛盾信号检测、因子合成稳定性、全链路不崩溃。

---

### P2-C: 控制文档同步

| 属性 | 内容 |
|------|------|
| 目标 | 更新 AGENTS.md, I_live_system_map.md 反映已验证状态 |
| 文件 | `AGENTS.md`, `docs/reanalysis/I_live_system_map.md` |
| 预计 | 30min |

**AGENTS.md 更新要点**:
- 在 `Recent Work` 节添加 2026-07-17 验证条目
- 在 `Known Gaps` 节添加 Spring 结构性限制说明
- 更新测试计数: 截至本次新增 ~15 个测试, 合计 ~1,857 通过

**验收标准**: 文档与代码实际状态一致, 无过时声明。

---

## 并行执行轨道

```
轨道 A (基建)
  P0-A: 基线捕获 ───────────────── 30min
    └→ P2-C: 文档同步 ─────────── 30min

轨道 B (LPPL) — P2-A 串行在 P0-B 后 (同文件 engine.py)
  P0-B: 路径统一 ──────────────── 1.5h  ← 修正: 无循环导入, 常量名 LPPL_ENGINE_RECOVERABLE_ERRORS
    └→ P2-A: ATR 自适应 ───────── 1h

轨道 C (Wyckoff + Factor)
  P0-C: Spring 验真 ───────────── 1.5h  ← 修正: 移除 --diagnosis H12
    ├→ P1-B: Wyckoff 测试 ─────── 2h
    └→ P1-C: IC 半衰期 ────────── 4h   ← 修正: 复用 ic_ir_history, 时间上调

轨道 D (文档 + 集成)
  P1-A: 文档修复 ──────────────── 30min
    └→ P2-B: 跨引擎测试 ───────── 4h   ← 修正: 改用 brain 级引擎, 时间上调
```

---

## 总执行摘要

| Phase | 轨道 | 任务 | 预计 | 风险 |
|-------|------|------|------|------|
| P0-A | A | 基线捕获 | 30min | 低 |
| P0-B | B | LPPL 路径统一 | 1.5h | 中 |
| P0-C | C | Spring 验真 | 1.5h | 低 |
| P1-A | D | 文档修复 | 30min | 无 |
| P1-B | C | Wyckoff 测试 | 2h | 低 |
| P1-C | C | IC 半衰期 | **4h** | 中 |
| P2-A | B | ATR 自适应 | 1h | 低 |
| P2-B | D | 跨引擎测试 | **4h** | 低 |
| P2-C | A | 文档同步 | 30min | 低 |
| **合计** | | | **~14.5h** | |

**并行加速**: 4 轨道可并行执行 → 理论最快 **~4.5h** 完成全部 9 项 (受轨道 B 串行限制)。

> 红蓝对抗报告: `docs/remediation/REN_BLUE_EXECUTION_PLAN_20260717.md`
