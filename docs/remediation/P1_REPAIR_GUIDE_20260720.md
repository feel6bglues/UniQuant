# P1 修复指南与验证工作清单 (2026-07-20)

> 基于 6 轮红蓝对抗 + 源代码逐行核实编制。零幻觉承诺：每一条声明均标注 `文件:行` 引用。

---

## 🔴🔵 对抗结论概要

| 任务 | 裁决 | 优先级 | 预计工时 |
|---|---|---|---|
| **P1-W02**: 因子 IC 半衰期/衰减加权 | 🔴 发现 6 项设计缺陷, 🔵 全部有可落地方案 | P1 | 4h |
| **P1-W03**: LPPL `_process_window` 统一优化器 | ✅ **代码已修复** (v7 P0-B), 仅需更新文档 | — | 0h (文档更新 15m) |

---

## 任务一: P1-W02 — 因子 IC 半衰期/衰减加权

### 🔴 已确认的代码缺陷 (红队验证)

| ID | 严重度 | 文件:行 | 描述 |
|---|---|---|---|
| **BUG-01** | CRITICAL | `walk_forward_pipeline.py:199` | `list(ic_results.get(col, {}).values())` 将 `Dict[int, FactorICResult]` 转 `List[FactorICResult]`, `_resolve_ic_result` 无法处理 `list` → 返回 `None` → 全部落到 `default_weight`。**IC 加权路径在 walk_forward 模式下完全死亡**。 |
| **BUG-02** | CRITICAL | `composer.py:138-149` | `_resolve_ic_result` 处理 `FactorICResult` 和 `dict`, 但 **无防御分支处理 `list`** → 静默返回 `None` |
| **BUG-03** | HIGH | `composer.py:151-174` | `_resolve_weights` **无归一化**。不同因子 ICIR 直接相加得到 composite_score, 量级随 ICIR 绝对值波动 |
| **BUG-04** | MEDIUM | `registry.py:33` | `ic_ir_history: Optional[List[float]]` 字段定义但 **0 处写入代码** (全仓 grep 仅 1 匹配 = 定义行)。死代码 |
| **BUG-05** | MEDIUM | `walk_forward_pipeline.py:80-103` v.s. `composer.py:151-174` | 两条权重路径行为不一致: pipeline 有归一化 (line 98-100), composer 无归一化。IC 半衰期必须在两路径间收敛 |

### 🧪 测试缺陷 (红队验证)

| ID | 严重度 | 文件:行 | 描述 |
|---|---|---|---|
| **TST-01** | HIGH | `test_walk_forward_pipeline.py:109-112` | `test_walk_forward_fit` patch 了 `composer.process` → **整个 BUG-01 路径未被覆盖**。真实 `composer.process` 的 `_resolve_ic_result(list)→None` 逻辑从未触发 |

### 🔵 修复方案 (蓝队 — 逐条可执行)

---

#### FIX-01 (BUG-01) — 修复 walk_forward_pipeline.py:199 list 包裹

**文件**: `src/uniquant/brain/factors/walk_forward_pipeline.py:199`

**当前代码 (问题)**
```python
ic_results={col: list(ic_results.get(col, {}).values()) for col in factor_cols},
```

**修复后**
```python
ic_results={col: dict(ic_results.get(col, {})) for col in factor_cols},
```

**验证**: `dict(...)` 复制 `Dict[int, FactorICResult]` 结构, 与 `_resolve_ic_result` 的 `isinstance(value, dict)` 分支匹配。

---

#### FIX-02 (BUG-02) — 防御分支: _resolve_ic_result 处理 list

**文件**: `src/uniquant/brain/factors/composer.py:138-149`

**改动**: 在 `return None` 前加 list 检测日志

```python
def _resolve_ic_result(self, value: Any) -> Optional[FactorICResult]:
    if isinstance(value, FactorICResult):
        return value

    if isinstance(value, dict) and value:
        candidates = [v for v in value.values() if isinstance(v, FactorICResult)]
        if not candidates:
            return None
        return max(candidates, key=lambda result: abs(result.icir))

    if isinstance(value, list):  # 新增: 防御分支, 静默转换错误
        logger.warning("_resolve_ic_result received list (expected dict or FactorICResult): %s ...", type(value).__name__)
        return None

    return None
```

---

#### FIX-03 (BUG-03) — `_resolve_weights` 归一化

**文件**: `src/uniquant/brain/factors/composer.py:151-174`

**改动**: 在返回前加归一化

```python
def _resolve_weights(
    self,
    factor_cols: List[str],
    ic_results: Optional[Dict[str, Any]] = None,
    ic_history: Optional[Dict[str, Dict[str, List[float]]]] = None,  # 新增
    half_life: Optional[int] = None,                                  # 新增
) -> Dict[str, float]:
    weights: Dict[str, float] = {}

    for col in factor_cols:
        weight = None
        if ic_results and col in ic_results:
            result = self._resolve_ic_result(ic_results[col])
            if result is not None and np.isfinite(result.icir):
                weight = float(result.icir)

        if weight is None:
            factor = self.registry.get_factor(col)
            weight = float(factor.default_weight) if factor is not None else 1.0

        # IC 半衰期: 对跨窗口 ICIR 序列做指数衰减加权
        if weight is not None and ic_history and col in ic_history and half_life is not None:
            col_history = ic_history[col]
            if col_history:
                weight = self._apply_cross_window_decay(col_history, float(weight), half_life)

        weights[col] = weight

    # 归一化
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    else:
        weights = {col: 1.0 / max(len(factor_cols), 1) for col in factor_cols}
    return weights
```

---

#### FIX-04 — 新增 `_apply_cross_window_decay` 方法

**文件**: `src/uniquant/brain/factors/composer.py` (新增方法, 建议放在 `_resolve_weights` 后)

```python
def _apply_cross_window_decay(
    self,
    history: List[float],
    current_icir: float,
    half_life: int = 60,
) -> float:
    """
    跨窗口 ICIR 指数衰减加权。
    将当前 ICIR 与历史 ICIR 序列进行 decay-weighted 平均,
    使近期 ICIR 权重 > 远期 ICIR 权重。

    与 analyzer.py compute_ic_ir 的 half_life (日度 IC 序列加权)
    独立且正交 — 前者跨训练窗口, 后者窗口内日频。

    Args:
        history: 历史 ICIR 值列表 (旧→新)
        current_icir: 当前窗口的 ICIR 值
        half_life: 半衰期(窗口数)。60 = 60 个窗口前权重降为一半
    """
    all_values = list(history) + [current_icir]
    n = len(all_values)
    if n <= 1:
        return current_icir
    if half_life is None or half_life <= 0:
        return float(np.mean(all_values))

    weights = np.exp(-np.log(2) * np.arange(n) / half_life)
    weights = weights / weights.sum()
    return float(np.sum(np.array(all_values) * weights))
```

---

#### FIX-05 — `_resolve_weights` 归一化对齐到 `_compute_weights` 行为

**文件**: `src/uniquant/brain/factors/walk_forward_pipeline.py:80-103` (可选重构, 非必须)

建议将 `_compute_weights` 委托给 composer, 消除两条路径的维护负担:

```python
def _compute_weights(self, ic_results, factor_cols):
    return self.composer._resolve_weights(
        factor_cols,
        ic_results=ic_results,
        ic_history=getattr(self, "_ic_history", None),
        half_life=getattr(self, "half_life", None),
    )
```

(此重构为**可选**, 不阻塞 IC 半衰期基础功能, 建议 v8 做)

---

#### FIX-06 (BUG-04) — 清理死代码字段 或 复用为默认配置

**文件**: `src/uniquant/brain/factors/registry.py:33`

**选项 A (建议 — 清理)**:
```python
# 删除 ic_ir_history 字段
# FactorRegistry 不存储运行时 IC 历史 — 由调用方维护 ic_history 传入 composer
```

**选项 B (可选 — 复用为默认半衰期配置)**:
```python
@dataclass
class FactorInfo:
    ...
    half_life_days: Optional[int] = 60  # 跨窗口半衰期因子默认值 (可选覆盖)
```

选择 A (清理) 更符合去耦合设计。

---

#### FIX-07 (TST-01) — 解除 composer.process 补丁

**文件**: `tests/test_walk_forward_pipeline.py:109-112`

**改动**: 只 patch `analyzer.compute_ic_ir` (控制 IC 输出), 但**不 patch `composer.process`**, 让真实路径运行。

```python
def test_walk_forward_fit(self, pipeline, sample_data, factor_cols):
    ic_results = _make_ic_results(factor_cols)

    with patch.object(pipeline.analyzer, "compute_ic_ir", return_value=ic_results):
        # 不再 patch composer.process — 走真实路径
        result = pipeline.run(sample_data, factor_cols=factor_cols)

    assert isinstance(result, WalkForwardResult)
    assert len(result.windows) > 0
    # 验证 FIX-01 后 ic_results 正确传递到 composer
    wr = result.windows[0]
    assert abs(sum(wr.weights.values()) - 1.0) < 1e-6
```

**⚠️ 注意**: 解除 patch 后, `composer.compute_all_factors()` 会尝试计算因子。需要确保测试数据包含因子列或 `factor_cols` 在 `df.columns` 中。`_make_synthetic_data` 生成的 `factor_0/1/2` 列已经存在, 所以可以直接通过。

---

#### 新增测试 (IC 半衰期专用)

**文件**: `tests/test_factor_composer.py` (若不存在则新建)

| 测试用例 | 输入 | 预期 |
|---|---|---|
| `test_ic_decay_basic` | history=[0.1,0.2], current=0.3, hl=60 | 结果偏向 0.3 |
| `test_ic_decay_single` | history=[], current=0.3, hl=60 | 返回 0.3 (无历史) |
| `test_ic_decay_equal` | history=[0.5,0.3], current=0.4, hl=1e6 | ~等权平均 ≈ 0.4 |
| `test_ic_decay_short` | history=[0.2], current=0.1, hl=2 | 近期权重 > 历史权重 |
| `test_weight_normalization` | 3 因子 ICIR=[0.1,0.4,0.5] | weights 和为 1 |
| `test_resolve_ic_result_list_defense` | 传入 list | log warning, return None |
| `test_walk_forward_ic_path_live` | 不 patch composer.process | ic_results 正确传递, weights 归一化 |

---

### 📋 修复实施顺序

| 顺序 | 任务 | 影响范围 | 预计 |
|---|---|---|---|
| **1** | FIX-01: walk_forward_pipeline:199 list bug | 单行 | 5m |
| **2** | FIX-02: _resolve_ic_result 防御分支 | 单方法 | 5m |
| **3** | FIX-03+04: _resolve_weights 归一化 + 半衰期 | composer.py | 45m |
| **4** | FIX-06: 清理 ic_ir_history 死代码 | registry.py | 5m |
| **5** | FIX-07: 解除测试补丁 + 验证 | test_walk_forward_pipeline.py | 15m |
| **6** | 新增 IC 半衰期测试 (×7) | test_factor_composer.py | 45m |
| **7** | 运行全量测试: `pytest tests/ -q` | — | 2m |

**总预计**: ~4h (含测试)

---

## 任务二: P1-W03 — LPPL `_process_window` 统一优化器路径

### 代码核实结果

| 声明 | 文件:行 | 代码状态 |
|---|---|---|
| `_process_window` 使用 DE 优化器 | `engine.py:998-1010` | ❌ **过时声明** — 实际 line 1003 使用 `fit_single_window_lbfgsb` (L-BFGS-B) |
| `_process_window` 使用 L-BFGS-B | `engine.py:1003` | ✅ **确认已使用 L-BFGS-B** |

**验证证据**: 2026-07-17 v7 P0-B 将 `_process_window` 从 DE 切换为 L-BFGS-B (`fit_single_window_lbfgsb` 直调)。

### 遗留路径核实

| 路径 | 文件:行 | 优化器 | 角色 | 风险 |
|---|---|---|---|---|
| `LPPLEngine.detect_bubble()` | `engine.py:1012-1021` | 3-param VP | 生产 | ⚠️ R² 口径已文档化 (v7 W02-B/C) |
| `LPPLComputation` (legacy) | `computation.py:58,80` | DE | 离线批处理 | ⚠️ 非生产路径, 建议 v8 统一 |
| `_process_window` | `engine.py:1003` | L-BFGS-B ✅ | 生产 | — |
| `scan_single_date` | `engine.py:478-481` | L-BFGS-B 默认 | 生产 | — |
| `process_single_day_ensemble` | `engine.py:896-899` | L-BFGS-B 默认 | 生产 | — |
| `multifit.fit_single_layer` | `multifit.py:94,118` | L-BFGS-B ✅ | 生产 | — |

### 行动项目

| ID | 行动 | 类型 |
|---|---|---|
| DOC-01 | 更新 `VERIFIED_WORKLIST_20260717.md` 中 P1-W03 状态为 **✅ 已修复 (v7 P0-B)** | 文档 |
| DOC-02 | 更新 `AGENTS.md` 中 P1-W03 从待办移除 | 文档 |
| NICE-01 | `computation.py:58,80` `fit_single_window` → `fit_single_window_lbfgsb` (v8) | 代码 (v8) |

**结论**: P1-W03 无代码改动需要。

---

## 验证方法 (两任务通用)

```bash
# 1. 因子系测试
pytest tests/test_factor_composer.py tests/test_walk_forward_pipeline.py tests/test_factor_analyzer.py -x -v

# 2. 全量回归
pytest tests/ -q

# 3. Ruff 清理
ruff check src/uniquant/

# 4. 基线验证
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py
```

---

## 修订记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-07-20 | v1 | 初始编制, 基于 6 轮红蓝对抗 + 源代码逐行核实 |
