# R1-1D: Factor Pipeline Audit Report (Deep Audit)

## 审计范围
`src/uniquant/brain/factors/` 全层：walk_forward_pipeline.py, analyzer.py, composer.py

## 文件清单
- walk_forward_pipeline.py (214 lines) - Walk-Forward 因子扫描流水线
- analyzer.py (527 lines) - 因子分析器 (IC/IR/IC>0 ratio, lookahead detection)
- composer.py (312 lines) - 因子合成器 (Z-score, 正交化, IC 加权)

---

## 核查项 1: assert 语句在 `python -O` 模式下是否被绕过

**结论: 是，全部 6 处 assert 在 `-O` 模式下被完全绕过。**

### 受影响代码

`walk_forward_pipeline.py` 中 `run()` 方法包含 6 条 assert：

| 行号 | 语句 | 守护内容 |
|------|------|----------|
| 114 | `assert date_col in df.columns` | 列名存在性 |
| 115 | `assert code_col in df.columns` | 列名存在性 |
| 116 | `assert price_col in df.columns` | 列名存在性 |
| 135 | `assert windows, ...` | 最小数据量 |
| 145 | `assert len(train_df) >= self.min_train_days` | 训练窗口长度 |
| 146 | `assert not test_df.empty` | 测试窗口非空 |

### 分析

Python 以 `-O`（优化模式）或 `PYTHONOPTIMIZE=1` 运行时，编译器会在字节码生成阶段直接移除所有 `assert` 语句。这不是运行时条件判断——这些语句从字节码中物理消失，零开销。

**具体风险**:
- **行 114-116**: 缺少必要列的 DataFrame 将静默通过，后续 `df.sort_values([code_col, date_col])` 触发 `KeyError`，错误信息远离源头，难以调试
- **行 135**: 空窗口列表导致 for 循环不执行，返回空结果，下游可能将零权重视为有效
- **行 145**: 训练集过短时静默计算 IC/IR，产出有偏权重
- **行 146**: 空测试窗口导致 `composer.process()` 收到空 DataFrame，可能产出 NaN 合成分数

**严重性: CRITICAL** — 生产环境如果使用 `python -O`（某些容器镜像默认启用），所有输入验证静默失效。

**修复**: 将 assert 替换为 `if ... raise ValueError(...)` 或使用 `@dataclass __post_init__` 验证。

---

## 核查项 2: factor_func 参数传递到 compute_ic_ir — 该参数是否存在

**结论: 不存在。`compute_ic_ir` 签名中没有 `factor_func` 形参，传入将触发 TypeError。**

### 调用端 (walk_forward_pipeline.py:123-132)

```python
if factor_func is not None:
    self.analyzer.compute_ic_ir(
        df,
        factor_cols=factor_cols,
        date_col=date_col,
        code_col=code_col,
        price_col=price_col,
        mode=AnalysisMode.BACKTEST,
        factor_func=factor_func,   # <-- 此参数不存在
    )
```

### 被调用端签名 (analyzer.py:243-253)

```python
def compute_ic_ir(
    self,
    df: pd.DataFrame,
    factor_cols: List[str],
    holding_periods: Optional[List[int]] = None,
    date_col: str = "date",
    code_col: str = "code",
    price_col: str = "close",
    mode: AnalysisMode | str = AnalysisMode.BACKTEST,
    half_life: Optional[int] = None,
) -> Dict[str, Dict[int, FactorICResult]]:
```

### 详细分析

1. **参数不存在**: `compute_ic_ir` 的 9 个形参中无 `factor_func`。Python 在收到未声明的关键字参数时抛出 `TypeError: compute_ic_ir() got an unexpected keyword argument 'factor_func'`。
2. **返回值被丢弃**: 即使参数存在，调用结果未赋值给任何变量（第 124 行），属于 fire-and-forget。
3. **当前安全**: `factor_func` 默认值为 `None`（行 112），`if factor_func is not None` 分支在默认情况下不执行。只有显式传入非 None 的 `factor_func` 才会触发崩溃。
4. **意图不明**: 此代码看起来是未完成的功能——可能意图在调用 `compute_ic_ir` 前先用 `factor_func` 追加因子列到 df，但实现时直接将函数对象作为参数传递。

**严重性: CRITICAL** — 任何按照 `run()` 签名文档传入 `factor_func` 的调用者将立即崩溃。这是一个未完成的 API 接口。

**修复**: 要么从 `run()` 签名移除 `factor_func`，要么在 `compute_ic_ir` 中增加对该参数的支持。

---

## 核查项 3: check_lookahead_leakage 是否在管道中被调用

**结论: 否。该函数在定义后从未被任何代码调用——是死代码。**

### 证据

1. **定义位置**: `analyzer.py:25-84` — 完整实现了基于未来扰动不变性的前视偏差检测算法
2. **全代码库 grep**: `check_lookahead_leakage` 在整个 `src/` 目录中仅出现 1 次（即定义本身）
3. **walk_forward_pipeline.py**: 导入列表仅包含 `AnalysisMode` 和 `FactorAnalyzer`（行 16），未导入 `check_lookahead_leakage`
4. **调用路径分析**: 当 `run()` 接收到 `factor_func` 时（行 123），直接尝试传入不存在的参数（见核查项 2），完全跳过了前视偏差检测

### 影响

这是一个**已实现但未集成的安全检查**。算法逻辑：
1. 运行 `factor_func` 得到基线结果
2. 在 3 个 cutoff 点（33%, 50%, 66%）之后对 close 价格施加随机扰动
3. 重新运行 `factor_func`，检查 cutoff 之前的因子值是否变化
4. 若变化 → 存在前视偏差 → raise `LookaheadBiasError`

即使修复了核查项 2（让 `factor_func` 被正确处理），前视偏差检测仍然缺失。用户可以传入一个在内部使用未来数据的 `factor_func`，Walk-Forward 流水线不会发现。

**严重性: HIGH** — 安全检查函数存在但未接入，是防御体系的空洞。

**修复**: 在 `run()` 中，当 `factor_func is not None` 时，先调用 `check_lookahead_leakage(df, factor_func, factor_cols)`。

---

## 核查项 4: 权重计算是否有时间衰减，half_life 参数是否被传入

**结论: 无时间衰减。`half_life` 参数从未被传入管道。**

### _compute_weights 逻辑 (walk_forward_pipeline.py:80-103)

```python
def _compute_weights(
    self,
    ic_results: Dict[str, Dict[int, Any]],
    factor_cols: List[str],
) -> Dict[str, float]:
    # ...
    for col in factor_cols:
        # ...
        for period, result in period_results.items():
            ir = abs(float(getattr(result, "icir", 0)))
            if ir > best_icir:
                best_icir = ir
        weights[col] = max(best_icir, 0.0)
```

**权重计算方式**: 对每个因子，取所有 holding_period 中 **绝对值最大的 ICIR** 作为原始权重，然后归一化。

### 缺失项分析

| 维度 | 现状 | 影响 |
|------|------|------|
| **时间衰减** | 无。训练窗口内所有日期的 IC 等权 | 6 个月前的 IC 与昨天的 IC 权重相同 |
| **half_life 传递** | `compute_ic_ir` 支持 `half_life` 参数（analyzer.py:252），但管道 3 次调用均未传入 | IC 序列永远使用等权均值 |
| **max 选择** | 使用 `max(abs(ICIR))` 而非加权均值 | 单个持有期的噪声 ICIR 可能主导权重 |

### compute_ic_ir 中的 half_life 机制 (analyzer.py:336-340)

```python
if half_life is not None and len(ic_array) > 1:
    w = _exponential_weights(len(ic_array), half_life)
    ic_mean = float(np.average(ic_array, weights=w))
    variance = np.average((ic_array - ic_mean) ** 2, weights=w)
    ic_std = float(np.sqrt(variance))
```

管道中 3 次 `compute_ic_ir` 调用（行 124, 148, 172）均未传递 `half_life`，因此始终使用等权计算。

### 影响

- 权重对近期市场 regime 变化不敏感
- 训练窗口末尾如果因子结构已变，权重仍然基于历史最优期的表现
- 样本外表现与权重可能严重脱节

**严重性: HIGH** — 时间衰减是 Walk-Forward 方法论的核心要素，缺失将削弱管道的样本外预测能力。

**修复**: 在 `compute_ic_ir` 调用时传入 `half_life`（如 126 天 ≈ 6 个月），并在 `_compute_weights` 中使用加权均值替代 max 选择。

---

## 核查项 5: analyzer.py:301 内联 shift(-period) — mode="live" 防守是否覆盖

**结论: 是。`mode="live"` 防守覆盖了第 301 行，但依赖单一检查点，且存在死代码冗余。**

### 防守链分析

```
compute_ic_ir() 入口 (line 283-288):
  if mode == AnalysisMode.LIVE:
      raise ValueError("Lookahead bias detected: ...")  ← 在此处拦截
  
  # ... 后续代码 ...
  
  line 301: df[fwd_col] = df.groupby(code_col)[price_col].shift(-period) / df[price_col] - 1
            ↑ 仅在 mode=BACKTEST 时执行到此处
```

### 详细分析

1. **入口检查有效**: `compute_ic_ir` 在第 283-288 行检查 `mode == AnalysisMode.LIVE`，若为 LIVE 则直接 raise，不会到达第 301 行。
2. **管道始终传入 BACKTEST**: `walk_forward_pipeline.py` 中所有 3 次调用 `compute_ic_ir` 均传入 `mode=AnalysisMode.BACKTEST`（行 130, 155, 179），因此第 301 行始终执行。
3. **_compute_forward_returns 是死代码**: `analyzer.py:134-180` 定义了独立的 `_compute_forward_returns` 方法（含自己的 mode 检查），但**在整个代码库中从未被调用**（grep 确认仅定义处有匹配）。实际的 forward return 计算在 `compute_ic_ir` 内联完成（第 301 行）。
4. **类型不一致**: `_compute_forward_returns` 的 mode 参数类型为 `str`（默认 `"backtest"`），而 `compute_ic_ir` 的 mode 参数类型为 `AnalysisMode | str`。但由于 `_compute_forward_returns` 是死代码，此不一致无运行时影响。

### 风险评估

当前防线有效，但存在以下结构性风险：

| 风险 | 说明 |
|------|------|
| **单点防护** | 所有 forward return 安全性仅依赖 `compute_ic_ir` 入口检查。若未来有人绕过 `compute_ic_ir` 直接在其他上下文中使用 `shift(-period)` 模式，将失去保护 |
| **死代码误导** | `_compute_forward_returns` 的 mode 检查可能让审计者误以为 forward return 计算已通过此方法统一保护，实际该方法从未被调用 |
| **无运行时自检** | 第 301 行的 `shift(-period)` 没有自身的 mode 检查，完全依赖调用方的入口检查 |

**严重性: MEDIUM** — 当前安全但防御深度不足，死代码增加维护负担和审计复杂度。

**修复**: 删除 `_compute_forward_returns` 死代码，或将第 301 行重构为调用统一的 forward return 计算方法。

---

## 附带发现

### [A1] oos_ic_values 可能包含 NaN — 影响 OOS ICIR 计算

**文件**: `walk_forward_pipeline.py:182-184, 196-199`

第 183 行计算 `window_oos_ic` 时：
```python
window_oos_ic = float(np.mean([r.ic_mean for r in oos_ic_res["composite_score"].values() if hasattr(r, "ic_mean")]))
```
若所有 `ic_mean` 为 NaN，`np.mean` 返回 NaN，后续 `np.mean(oos_arr)` 和 `np.std(oos_arr)` 传播 NaN，导致 `oos_icir` 为 NaN。

**修复**: `oos_ic_values.append` 前增加 `if not np.isnan(window_oos_ic)` 过滤。

### [A2] `_temporal_split` 按 unique 日期切分，不处理缺失交易日

**文件**: `walk_forward_pipeline.py:62-78`

使用 `df[date_col].unique()` 取唯一日期后按索引切分。A 股有长假、个股停牌，`train_window=504` 表示 504 个**出现的日期**，非 504 个交易日历日。

### [A3] 权重稳定性监控缺失

**文件**: `walk_forward_pipeline.py:201-205`

`weight_stability` 计算了每个因子跨窗口的权重标准差，但无告警逻辑。高振荡意味着因子在不同市场状态下表现差异大。

---

## 审计统计

| 核查项 | 结论 | 严重性 |
|--------|------|--------|
| 1: assert -O 绕过 | 全部 6 处被绕过 | CRITICAL |
| 2: factor_func 参数不存在 | 传入将触发 TypeError | CRITICAL |
| 3: check_lookahead_leakage 未调用 | 死代码，安全检查未接入 | HIGH |
| 4: 时间衰减缺失 | half_life 从未传入 | HIGH |
| 5: shift(-period) mode 防守 | 防守有效但依赖单一检查点 | MEDIUM |

| 严重性 | 数量 |
|--------|------|
| CRITICAL | 2 |
| HIGH | 2 |
| MEDIUM | 1 |
| 附带发现 | 3 |
| **合计** | **8** |

## 优先修复路径

1. **立即修复**: 6 处 `assert` → `if raise ValueError` (核查项 1)
2. **立即修复**: 移除或正确实现 `factor_func` 参数 (核查项 2)
3. **短期修复**: 接入 `check_lookahead_leakage` 到管道 (核查项 3)
4. **短期修复**: 传入 `half_life` 并重构权重计算 (核查项 4)
5. **中期改进**: 清理 `_compute_forward_returns` 死代码 (核查项 5)

## 关键代码路径图

```
WalkForwardFactorPipeline.run()
  ├── assert 列名存在 [核查项1: -O 绕过]
  ├── factor_func → compute_ic_ir(factor_func=) [核查项2: 不存在的形参]
  ├── _temporal_split() [A2: 缺失交易日]
  └── for each window:
       ├── assert train_df >= min_train_days [核查项1: -O 绕过]
       ├── assert not test_df.empty [核查项1: -O 绕过]
       ├── compute_ic_ir(train_df) [核查项4: 无 half_life]
       ├── _compute_weights() [核查项4: max 选择无衰减]
       ├── composer.process(test_df)
       └── compute_ic_ir(scored_df) → OOS IC [A1: NaN 传播]

FactorAnalyzer.compute_ic_ir()
  ├── mode == LIVE → raise [有效，覆盖第 301 行]
  ├── check_lookahead_leakage() [核查项3: 已实现但从未调用]
  ├── _compute_forward_returns() [核查项5: 死代码]
  └── inline shift(-period) line 301 [核查项5: 由入口检查保护]
```

---

*审计时间: 2026-06-06 | 审计员: R1-Factor Pipeline Auditor | 基于代码事实*
*核查项: 5 项深度审计 + 3 项附带发现*
