# 红蓝对抗: EXECUTION_PLAN_20260717.md

> 执行计划的每项任务逐一红蓝对抗核实
> 2026-07-17

---

## 总体评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 可行性 | **7/10** | 3 个代码片段直接不可执行 (P0-B ×2, P0-C) |
| 完整性 | **8/10** | P2-B 缺少 orchestrator 依赖说明 |
| 风险分级 | **6/10** | P0-B 标"中"但实际含编译错误 |
| 依赖图 | **7/10** | P2-A 真依赖 P0-B (修改同一文件) 未体现 |
| 时间估算 | **8/10** | 总体合理, 但 P1-C 低估 (IC 半衰期依赖 Analyzer 改造) |

**红蓝对抗判定: 有条件通过 (需修正 6 项 BLOCKER 后执行)**

---

## 逐项红蓝对抗

### P0-A: 基线捕获与回归验证 ✅ 【蓝胜】

| 核查项 | 蓝方 (计划方) | 红方 (对抗方) | 判定 |
|--------|-------------|-------------|------|
| `scripts/capture_baseline.py` 存在 | 是 | 225 行, 存在 | ✅ |
| `scripts/compare_baseline.py` 存在 | 是 | 184 行, 存在 | ✅ |
| 命令可执行 | `python3 scripts/capture_baseline.py && ...` | 已验证存在 | ✅ |
| 时间估算 30min | — | 合理 | ✅ |

**蓝方胜出。可直接执行。**

---

### P0-B: LPPL `_process_window` 优化器路径统一 ❌ 【红胜 — 2 个 BLOCKER】

#### BLOCKER #1: 循环导入 (Critical)

| 核查项 | 蓝方 (计划) | 红方 (实际代码) | 判定 |
|--------|------------|----------------|------|
| 当前实现 | L993 `from ...brain.lppl.calculator import LPPLCalculator` | ✅ 正确 | — |
| 计划修改 | 替换为 `from ...brain.lppl.engine import ...` | ❌ **循环导入** — 当前文件就是 `engine.py` | ❌ |

**当前代码** (L992-1005):
```python
@staticmethod
def _process_window(df, window):
    try:
        from ...brain.lppl.calculator import LPPLCalculator as Calc
        calculator = Calc()
        subset = df["close"].iloc[-window:].values
        res = calculator.fit_single_window(subset)
        if res and res.get("rmse", float("inf")) < LPPLConstants.RMSE_REJECT_THRESHOLD:
            res["window"] = window
            return res
    except LPPL_ENGINE_RECOVERABLE_ERRORS:
        logger.exception("单窗口 LPPL 拟合失败")
        pass
    return None
```

✅ `fit_single_window_lbfgsb` 是 `engine.py` 的模块级函数 (L269)
❌ `from ...brain.lppl.engine import ...` 从自身导入

**修正**: 直接调用, 不需要 import 语句:
```python
subset = df["close"].iloc[-window:].values
config = LPPLConfig(window_range=[window])
res = fit_single_window_lbfgsb(subset, window, config)
```

#### BLOCKER #2: 错误常量名 (Critical)

| 核查项 | 蓝方 (计划) | 红方 (实际代码) | 判定 |
|--------|-----------|----------------|------|
| 异常捕获名 | `except RECOVERABLE_ERRORS:` | 实际是 `LPPL_ENGINE_RECOVERABLE_ERRORS` | ❌ |

**修正**: 用 `LPPL_ENGINE_RECOVERABLE_ERRORS` (已在 engine.py 顶部定义)

#### 风险升级: 中 → 高

以上 2 个错误导致代码无法运行。

**时间估算 1.5h 合理 (含基线重捕)。**

---

### P0-C: Spring/ACCUMULATION 真实数据验真 ❌ 【红胜 — 1 个 BLOCKER】

#### BLOCKER #3: `--diagnosis` 参数不存在

| 核查项 | 蓝方 (计划) | 红方 (实际代码) | 判定 |
|--------|------------|----------------|------|
| 命令 | `--stocks golden_20 --diagnosis H12` | 脚本无 `--diagnosis` 参数 | ❌ |

**脚本实际参数**: `--stocks`, `--max`, `--start`, `--output`, `--skip-lppl`, `--skip-wyckoff`, `--skip-cross`

H12 是内置诊断（共 H1-H12），脚本始终运行全部 12 项。

**修正**:
```bash
python3 scripts/lppl_wyckoff_cross_validation.py --stocks golden_20
```

#### 依赖声明错误

| 蓝方标 | 红方发现 |
|--------|---------|
| P0-C 依赖 P0-A (基线数据) | ❌ 脚本独立从 golden list 加载数据 |

**红方胜出。命令修正后可执行。时间估算 1.5h 合理。**

---

### P1-A: 文档修复 ✅ 【蓝胜】

横幅方案合理, 最小侵入, 无风险。30min 合理。

---

### P1-B: Wyckoff `_step4_risk_reward` 测试 ⚠️ 【蓝胜】

| 核查项 | 红方验证 |
|--------|---------|
| `WyckoffEngine._step4_risk_reward` 返回 `RiskRewardResult` | ✅ `rr.first_target_source`, `rr.rr_ratio` 均存在 |
| 可构造 `Step1Result(phase=ACCUMULATION, boundary_upper=12.0, ...)` | ✅ 验证通过 |
| `engine._step4_risk_reward(df, step1, step3, rule0)` 可调用 | ✅ 返回 `first_target=12.0, source=tr_upper, rr_ratio=0.46` |
| `...` 占位符 | ⚠️ 文档内可接受, 需注明是伪代码 |
| 4 个场景覆盖 | ✅ TR上沿/大阴线/跳空/ATR止损 完整 |
| `sample_df` fixture | ⚠️ 需在 conftest 或测试文件中定义 |

时间 2h 合理（含 fixture 设置）。

---

### P1-C: Factor IC 半衰期 ⚠️ 【红蓝平局】

| 核查项 | 红方发现 |
|--------|---------|
| `FactorInfo` 已有 `ic_ir_history: Optional[List[float]]` | ⚠️ 计划新增 `ic_history` 造成字段命名冲突 |
| `FactorAnalyzer` 已有 `compute_rank_ic()`, `compute_ic_ir()` | ✅ 有底层的 IC 计算机制 |
| 时间估算 2.5h | ❌ **低估→4h** (设计 1h + 编码 2h + 测试 1h) |

**核心问题**: 需决定是复用 `ic_ir_history` 还是新建独立字段。设计阶段需论证。

---

### P2-A: ATR 自适应 ⚠️ 【红胜 — 隐含依赖】

| 核查项 | 红方发现 |
|--------|---------|
| `classify_top_phase` 位置 | ✅ engine.py 模块级函数 |
| 新增 `atr_pct=None` 可选参数 | ✅ 向后兼容 |
| 依赖图 | ❌ P2-A 和 P0-B 都改 engine.py — 需串行 P0-B→P2-A |

**修正**: 轨道 B 内 P0-B→P2-A 串行, 总 2.5h。

---

### P2-B: 跨引擎测试 ❌ 【红胜 — 1 个 BLOCKER】

#### BLOCKER #4: WyckoffAnalysisEngine 依赖 orchestrator

```python
# 计划代码 (不可运行)
WyckoffAnalysisEngine(...).run_wyckoff_analysis("TEST", real_stock_df)
```

WyckoffAnalysisEngine 即使 df 已传, 第 2 行也访问 `self.orchestrator._generate_cache_key()` — orchestrator=None 时崩溃。

LpplAnalysisEngine 则是当 df 非 None 时不访问 orchestrator。

**修正**: 测试底层 brain 引擎:
```python
from uniquant.brain.lppl.engine import LPPLEngine
from uniquant.brain.wyckoff.engine import WyckoffEngine

lppl_result = LPPLEngine().detect_bubble(real_stock_df)
wyckoff_result = WyckoffEngine().analyze(real_stock_df, multi_timeframe=True)
```

时间 3h → **4h**（含模拟引擎 setup）。

---

### P2-C: 文档同步 ✅ 【蓝胜】

注意测试计数校准 (本次新增 ~15 个, 非 209)。30min 合理。

---

## 修正后执行计划

### BLOCKER 修正清单

| # | 任务 | 问题 | 修正 |
|---|------|------|------|
| 1 | P0-B | 循环导入 | 移除 import 语句, 直接调用 `fit_single_window_lbfgsb` |
| 2 | P0-B | 常量名错误 | `RECOVERABLE_ERRORS` → `LPPL_ENGINE_RECOVERABLE_ERRORS` |
| 3 | P0-C | `--diagnosis` 不存在 | 移除该标志, 仅用 `--stocks golden_20` |
| 4 | P2-B | orchestrator 依赖 | 改用 brain 级引擎 (LPPLEngine / WyckoffEngine) |
| — | P2-A | 隐含依赖 | 更新依赖图: P2-A 串行在 P0-B 后 |
| — | P1-C | 时间低估 | 2.5h → 4h |

### 时间修正

| 任务 | 原估算 | 修正后 |
|------|--------|--------|
| P0-A | 30min | 30min |
| P0-B | 1.5h | 1.5h |
| P0-C | 1.5h | 1.5h |
| P1-A | 30min | 30min |
| P1-B | 2h | 2h |
| P1-C | 2.5h | **4h** |
| P2-A | 1h | 1h |
| P2-B | 3h | **4h** |
| P2-C | 30min | 30min |
| **合计** | **~12h** | **~14.5h** |
| **并行** | **~4h** | **~4.5h** |

### 并行轨道

```
轨道 A (基建)         轨道 B (LPPL)        轨道 C (Wyckoff+Factor)  轨道 D (文档+集成)
P0-A: 30min           P0-B: 1.5h           P0-C: 1.5h               P1-A: 30min
  └→ P2-C: 30min        └→ P2-A: 1h (串行)   ├→ P1-B: 2h              └→ P2-B: 4h (brain引擎)
                                               └→ P1-C: 4h
```
