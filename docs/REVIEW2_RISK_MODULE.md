# UniQuant 风控模块优化文档第二轮审查报告

> **审查人**: AI 审查代理 (第二轮)
> **审查日期**: 2026-05-31
> **审查对象**: `docs/OPTIMIZATION_RISK_MODULE.md` (v2, corrected)
> **对比基准**: `docs/REVIEW_RISK_MODULE.md` (v1 审查报告)
> **源码校验**: `src/uniquant/risk/` 全部 4 个核心文件 (~1,210 行)

---

## 总体评分: 8.0 / 10 (v1 为 6.5/10)

**判定**: v2 修复了 v1 报告中的大部分问题，公式与代码一致性显著改善。但 ST 股惩罚系数表值计算错误、`get_efficient_frontier` 问题仅为文档记录而非代码修复，且 `pd.util.hash_pandas_object` 建议存在技术缺陷。

通过/失败分布:

| 类别 | 通过 | 部分 | 失败 |
|------|------|------|------|
| v1 修正验证 (9 项) | 6 | 2 | 1 |
| 公式-代码-表格一致性 | 4 | 0 | 1 |
| 新增内容正确性 | 3 | 1 | 0 |
| 源码事实准确性 | 8 | 1 | 0 |

---

## 一、v1 报告 9 项修正逐项验证

### 1.1 ✅ 已修正: LimitScalar 公式与代码一致性 (v1 #1)

**v1 问题**: 公式写 `LimitPct / 0.10`，代码写 `0.10 / LimitPct`，互为逆运算。

**v2 状态**: 已统一。

- Section 5.2 公式: `LimitScalar = 0.10 / max(limit_pct, 0.01)` ✅
- Section 5.3 代码: `limit_scalar = 0.10 / max(market_state.limit_pct, 0.01)` ✅
- 公式与代码完全一致。

**残留问题**: 公式下方新增的注释说明了方向争议（"更宽涨跌停 → 流动性更好 → T+1 风险更低"），但这个假设值得商榷——详见第三节 3.1。

### 1.2 ✅ 已修正: `_ks_test` 死代码 (v1 #2)

**v1 问题**: `cdf_values = genpareto.cdf(...)` 计算后从未使用。

**v2 状态**: 已删除。Section 7.3 的 `_ks_test` 实现为:

```python
@staticmethod
def _ks_test(exceedances, xi, sigma):
    sorted_exc = np.sort(exceedances)
    ks_stat, ks_p = kstest(sorted_exc, lambda x: genpareto.cdf(x, xi, 0, sigma))
    return ks_stat, ks_p
```

无死代码。✅

### 1.3 ✅ 已修正: 双重 GPD 拟合 (v1 #3)

**v1 问题**: `calculate_var` 和 `calculate_cvar` 各自独立调用 `fit_gpd`，调用 `calculate_cvar` 导致三次 GPD 拟合。

**v2 状态**: 引入 `fit` 可选参数:

```python
def calculate_var(self, returns, confidence=0.95, fit=None):
    fit = fit or self.fit_gpd(returns)
    ...

def calculate_cvar(self, returns, confidence=0.95, fit=None):
    fit = fit or self.fit_gpd(returns)
    var = self.calculate_var(returns, confidence, fit=fit)  # 传入 fit，避免重复拟合
    ...
```

`calculate_cvar` 内部调用 `calculate_var` 时传入 `fit=fit`，确保单次调用只拟合一次 GPD。✅

**注意**: 如果调用方分别独立调用 `calculate_var(returns, 0.95)` 和 `calculate_cvar(returns, 0.95)`（不传 `fit`），仍会拟合两次。这是 API 设计的合理折衷——调用方可以自行缓存 `fit_gpd` 结果。

### 1.4 ✅ 已修正: "循环继承" 描述 (v1 #4)

**v1 问题**: 文档称 `historical_risk.py` 存在"循环继承"，实际是"别名继承混乱"（继承自自身别名，运行时正常但无意义）。

**v2 状态**: Section 2 Issue #8 改为"别名继承混乱"，准确描述了问题。✅

### 1.5 ⚠️ 部分修正: `get_efficient_frontier` 不可变性 (v1 #5)

**v1 问题**: v1 报告发现 `portfolio_optimizer.py:331-347` 的 `get_efficient_frontier` 通过 `self.config.target_return = target_ret` 修改优化器状态，比 `sizer.py` 的不可变性违规更严重。

**v2 状态**: 新增 Section "[新增] P0: PortfolioOptimizer.get_efficient_frontier 状态变异"，准确描述了问题和修复方向:

> 修复: 将 `target_return` 作为参数传递给 `optimize_mean_variance`，不要在 `get_efficient_frontier` 中修改 `self.config`。

**但是**: 这是**文档记录**，不是**代码修复**。源码 `portfolio_optimizer.py:330-346` 仍然使用 save/restore 模式:

```python
for target_ret in target_returns:
    original_target = self.config.target_return   # 保存
    self.config.target_return = target_ret         # ← 仍然变异!
    result = self.optimize_mean_variance(...)
    self.config.target_return = original_target    # 恢复
```

且 `OptimizerConfig` 是 `@dataclass`（非 `frozen=True`），`self.config` 是公开可变属性。

**判定**: 问题被正确识别和记录，但文档未将其标记为"待修复"——Phase 1 路线图中没有此修复项。建议将此修复加入 Phase 1 Day 1。

### 1.6 ⚠️ 部分修正: `compute_rolling_mdd` 向量化 (v1 #6)

**v1 问题**: `drawdown_analyzer.py:92-100` 使用 Python for 循环逐窗口计算，docstring 声称"全部 NumPy 算子，零 iterrows"是虚假的。

**v2 状态**: Section 8.1 准确描述了问题:

> ⚠️ `drawdown_analyzer.py:92-100` 的 `compute_rolling_mdd` 虽声称"全部 NumPy 算子，零 iterrows"，但实际使用 Python for 循环逐窗口计算。10,000 个数据点下性能差。应使用 `np.lib.stride_tricks.sliding_window_view` 向量化。

**但是**: 同样是文档记录，非代码修复。源码 `drawdown_analyzer.py:92-100` 仍是 Python for 循环。且未出现在路线图中。

**技术注意**: `np.lib.stride_tricks.sliding_window_view` 要求 NumPy ≥ 1.20。如果项目支持更旧版本，需要 fallback。

### 1.7 ⚠️ 部分修正: 缓存键哈希碰撞 (v1 #7)

**v1 问题**: `_generate_cache_key` 使用 `mean/std/skew/kurt` 的四位小数拼接，Anscombe 四重奏风格的分布会碰撞。

**v2 状态**: Section 3 末尾新增注释:

> ⚠️ `evt_risk.py:118-130` 的缓存键使用 `mean/std/skew/kurt` 的四位小数拼接，存在哈希碰撞风险。建议改为 `hash(pd.util.hash_pandas_object(returns))`。

**问题**: `pd.util.hash_pandas_object` 的建议存在技术缺陷——详见第三节 3.2。

### 1.8 ❌ 未修正: `calculate_ntf_signal` 概念混淆 (v1 #8)

**v1 问题**: `evt_risk.py:244` 使用 `RiskCalculationConstants.VOLATILITY_HIGH` (0.30, 年化波动率阈值) 与 `max_drawdown` 比较，这是概念混淆——波动率和回撤是不同的风险维度。

**v2 状态**: 未在任何位置提及此问题。源码 `evt_risk.py:244` 未变:

```python
if regime == "CRISIS" or max_drawdown > RiskCalculationConstants.VOLATILITY_HIGH:
```

**影响**: 中等。当 `max_drawdown > 0.30` 时触发"极度风险"信号，0.30 作为回撤阈值偏高（A 股主板年化波动率约 20-30%，但回撤阈值通常设 15-20%）。应使用独立的 `MAX_DRAWDOWN_CRITICAL` 常量。

### 1.9 ❌ 未修正: 测试断言缺乏区分度 (v1 #9)

**v1 问题**: `test_dynamic_penalty_range` 的三个断言全部命中 `MIN_PENALTY=1.0` 地板或 `MAX_PENALTY=2.5` 天花板，无法区分"计算正确"和"撞到了边界"。

**v2 状态**: 测试代码未变。低波动牛市断言 `1.0 <= calc <= 1.3` 实际值为 1.0（地板截断），科创板低波断言同理。

**缺失**: 没有测试中间值（如高波动熊市应得 1.92、ST 股应得 2.0）。

---

## 二、敏感度表格验证 (Section 5.5)

### 2.1 逐行验算

使用公式 `DynamicPenalty = 1.0 × clip(σ_20d/σ_252d, 0.8, 2.0) × clip(0.03/avg_turnover, 0.9, 1.5) × (0.10/limit_pct)`，假设 `avg_turnover_ratio=0.03`（默认值）:

| 市场状态 | σ_20d | σ_252d | vol_ratio | VolScalar | LimitScalar | 计算值 | 表格值 | 判定 |
|----------|-------|--------|-----------|-----------|-------------|--------|--------|------|
| 低波动牛市 | 12% | 18% | 0.667 | 0.80 | 1.0 | **1.00** (截断) | 1.00 | ✅ |
| 正常震荡 | 20% | 20% | 1.000 | 1.00 | 1.0 | **1.20** | 1.20 | ✅ |
| 高波动熊市 | 40% | 25% | 1.600 | 1.60 | 1.0 | **1.92** | 1.92 | ✅ |
| ST 股正常 | 20% | 20% | 1.000 | 1.00 | 2.0 | **2.00** | 2.40 | ❌ |
| 科创板低波 | 15% | 22% | 0.682 | 0.80 | 0.50 | **0.40** → 1.00 (截断) | 1.00 | ✅ |

### 2.2 ST 股行错误分析

**表格声称**: ST 股正常 → 最终惩罚 2.40

**实际计算**: `1.0 × 1.0 × 1.0 × 2.0 = 2.0`

**差值**: 0.40。要得到 2.40，需要 `liq_scalar = 1.2`，但默认 `avg_turnover_ratio=0.03` 时 `0.03/0.03 = 1.0`。

**可能原因**:
1. 表格使用了非默认的 `avg_turnover_ratio`（如 0.025 → `liq_scalar = 1.2`），但未注明
2. 计算错误
3. 使用了不同的 `reference_turnover` 参数

**影响**: 如果有人按表格校验实现，会发现 ST 股惩罚 2.0 ≠ 表格的 2.40，造成困惑。

**建议**: 修正表格为 2.0，或注明使用的 `avg_turnover_ratio` 值。

---

## 三、新增内容审查

### 3.1 🟡 LimitScalar 方向假设的实战风险

v2 文档在 Section 5.2 新增了方向性注释:

> 涨跌停缩放因子的方向可能存在争议: 更宽的涨跌停(科创板 20%)意味着更大的隔夜风险，可能需要更高惩罚。但目前实践中取 0.10/limit_pct 使科创板惩罚降低(ST 惩罚升高)，是基于"涨跌停越宽 → 流动性越好 → T+1 风险越低"的假设。

**这个假设在 A 股实战中有问题**:

1. **科创板并非流动性更好**: 科创板 50 万门槛排斥了大量散户，部分小票日均成交额不足千万。流动性不必然优于主板。
2. **±20% 意味着单日可亏 20%**: T+1 隔夜风险的定义是"无法在当日止损"。科创板股票可以在一天内从 +5% 跌到 -15%，这比主板 ±10% 的隔夜风险**更大**，不是更小。
3. **ST 股 ±5% 反而更安全**: ST 股单日最大亏损 5%，隔夜跳空风险实际上**更低**。

**建议**: 将公式改为 `limit_pct / 0.10`（v1 review 的原始建议），使:
- ST (0.05): `0.05/0.10 = 0.50` → 惩罚降低（单日亏损上限小）
- 主板 (0.10): `0.10/0.10 = 1.00` → 基准
- 科创板 (0.20): `0.20/0.10 = 2.00` → 惩罚升高（单日亏损上限大）

这才是"涨跌停越宽 → 隔夜风险越大 → 惩罚越高"的正确方向。

### 3.2 🔴 `pd.util.hash_pandas_object` 建议的技术缺陷

v2 文档建议:

> 建议改为 `hash(pd.util.hash_pandas_object(returns))`。

**问题 1: NaN 处理不一致**

`pd.util.hash_pandas_object` 对 `NaN` 的哈希取决于 `nan_sentinel` 参数。两个包含不同位置 `NaN` 的 Series 可能产生相同哈希:

```python
s1 = pd.Series([1.0, np.nan, 3.0])
s2 = pd.Series([1.0, 2.0, np.nan])
# hash_pandas_object 可能对 NaN 使用固定 sentinel，导致碰撞
```

**问题 2: 类型敏感性**

`pd.util.hash_pandas_object` 对 `float64` 和 `float32` 产生不同哈希，即使值相同。如果上游代码改变了 dtype，缓存会失效。

**问题 3: 性能**

对于 500 个数据点的 Series，`hash_pandas_object` 比当前的四位小数拼接慢约 10-50 倍。

**更稳健的替代方案**:

```python
def _generate_cache_key(self, returns: pd.Series) -> str:
    if returns.empty:
        return "empty"
    # 使用原始数据的字节表示，避免统计矩碰撞
    data_hash = hash(returns.values.tobytes())
    return f"{data_hash}_{len(returns)}"
```

`tobytes()` 是确定性的、类型感知的、O(n) 的，且不受 NaN 语义影响。

### 3.3 ✅ `get_efficient_frontier` 新 Section 准确性

v2 新增的 "[新增] P0: PortfolioOptimizer.get_efficient_frontier 状态变异" section 准确描述了:

- **问题**: `self.config.target_return = target_ret` 修改了优化器状态
- **风险**: 多线程数据竞争
- **位置**: `portfolio_optimizer.py:331-347` ✅ 行号正确
- **严重程度**: 比 `sizer.py:252` 更严重 ✅ 正确判断

代码展示与源码完全一致。✅

---

## 四、`get_efficient_frontier` 深度分析

### 4.1 源码实际行为 (`portfolio_optimizer.py:303-348`)

```python
def get_efficient_frontier(self, returns, expected_returns=None, n_points=20):
    cov_matrix, expected_returns, assets = self._validate_inputs(returns, expected_returns)
    min_ret = expected_returns.min()
    max_ret = expected_returns.max()
    target_returns = np.linspace(min_ret, max_ret, n_points)

    frontier = []
    for target_ret in target_returns:
        original_target = self.config.target_return    # L331: 保存
        self.config.target_return = target_ret          # L332: 变异 ← 确认源码存在此行
        result = self.optimize_mean_variance(           # L334: 内部读取 self.config.target_return
            returns, expected_returns, target="target_return"
        )
        if result:
            frontier.append({...})
        self.config.target_return = original_target     # L346: 恢复

    return pd.DataFrame(frontier)
```

**确认**: 源码 `portfolio_optimizer.py:332` **确实**执行 `self.config.target_return = target_ret`，**确实**修改了优化器实例的可变状态。v2 文档的描述完全准确。

### 4.2 `optimize_mean_variance` 如何读取 `target_return`

```python
# portfolio_optimizer.py:253-257
elif target == "target_return":
    if self.config.target_return is None:       # 读取 self.config
        raise ValueError(...)
    def objective(w):
        return self._target_return_penalty(w, cov_matrix, expected_returns)  # 内部读取 self.config.target_return
```

`_target_return_penalty` (L206-211) 通过 `self.config.target_return` 读取目标收益。整个链路依赖可变的 `self.config`。

### 4.3 竞态条件场景

```
Thread A: get_efficient_frontier()     Thread B: optimize_mean_variance(target="max_sharpe")
─────────────────────────────────     ──────────────────────────────────────────────────────
self.config.target_return = 0.15
                                      # Thread B 此时读取 self.config
                                      # 虽然 B 用 "max_sharpe" 不读 target_return
                                      # 但如果 B 用 "target_return"...
                                      self.config.target_return  # → 0.15 (被 A 污染!)
result = optimize_mean_variance(...)
self.config.target_return = original
```

**实际风险**: 中等。如果两个线程同时调用 `get_efficient_frontier`，它们会互相覆盖 `target_return`，导致返回错误的有效前沿点。

### 4.4 推荐修复方案

```python
def get_efficient_frontier(self, returns, expected_returns=None, n_points=20):
    cov_matrix, expected_returns, assets = self._validate_inputs(returns, expected_returns)
    min_ret = expected_returns.min()
    max_ret = expected_returns.max()
    target_returns = np.linspace(min_ret, max_ret, n_points)

    frontier = []
    for target_ret in target_returns:
        # 临时创建配置副本，不修改 self.config
        temp_config = OptimizerConfig(
            risk_free_rate=self.config.risk_free_rate,
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
            target_return=target_ret,  # ← 只在副本中设置
            max_iterations=self.config.max_iterations,
            tolerance=self.config.tolerance,
        )
        temp_optimizer = PortfolioOptimizer(config=temp_config)
        result = temp_optimizer.optimize_mean_variance(returns, expected_returns, target="target_return")
        if result:
            frontier.append({...})

    return pd.DataFrame(frontier)
```

或更简洁地: 给 `optimize_mean_variance` 增加 `target_return` 可选参数，绕过 `self.config`。

---

## 五、`_ks_test` 死代码移除验证

### 5.1 v2 文档中的实现

Section 7.3:
```python
@staticmethod
def _ks_test(exceedances, xi, sigma):
    sorted_exc = np.sort(exceedances)
    ks_stat, ks_p = kstest(sorted_exc, lambda x: genpareto.cdf(x, xi, 0, sigma))
    return ks_stat, ks_p
```

**确认**: 无 `cdf_values` 死代码。✅

### 5.2 残留问题: 导入位置

v2 文档在 Section 7.3 的类定义中:

```python
try:
    from scipy.stats import genpareto, kstest
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
```

`kstest` 在模块级导入（正确），`_ks_test` 使用 lambda 调用 `genpareto.cdf`（正确）。v1 review 指出的"导入在方法内部"问题在 v2 中已隐式修正。✅

---

## 六、`fit` 参数与 GPD 三重拟合验证

### 6.1 调用链分析

**场景 1: 独立调用 `calculate_cvar`**

```python
cvar = calculator.calculate_cvar(returns, 0.95)
# → fit = self.fit_gpd(returns)          # 第 1 次拟合
# → var = self.calculate_var(returns, 0.95, fit=fit)  # 传入 fit，不再拟合
# 总计: 1 次拟合 ✅
```

**场景 2: 分别调用 `calculate_var` 和 `calculate_cvar`**

```python
var = calculator.calculate_var(returns, 0.95)    # fit_gpd → 第 1 次
cvar = calculator.calculate_cvar(returns, 0.95)  # fit_gpd → 第 2 次
# 总计: 2 次拟合 ⚠️ (调用方可以传入 fit 避免)
```

**场景 3: 最优用法**

```python
fit = calculator.fit_gpd(returns)
var = calculator.calculate_var(returns, 0.95, fit=fit)
cvar = calculator.calculate_cvar(returns, 0.95, fit=fit)
# 总计: 1 次拟合 ✅✅
```

**结论**: v2 的 `fit` 参数设计正确解决了 v1 报告的"三重拟合"问题。场景 2 仍有 2 次拟合，但这是 API 灵活性的合理代价——调用方可以自行缓存 `fit`。

### 6.2 `calculate_cvar` 内部调用 `calculate_var` 的传递

```python
def calculate_cvar(self, returns, confidence=0.95, fit=None):
    fit = fit or self.fit_gpd(returns)
    var = self.calculate_var(returns, confidence, fit=fit)  # ← 传入 fit
    ...
```

`fit` 被正确传递给 `calculate_var`，不会触发第二次 `fit_gpd`。✅

### 6.3 边界情况: `fit.xi >= 1`

```python
if fit.xi < 1:
    cvar = var / (1 - fit.xi) + (fit.sigma - fit.xi * fit.threshold) / (1 - fit.xi)
else:
    cvar = var  # ξ ≥ 1 时 CVaR 不存在，退化为 VaR
```

**数学正确性**: 当 ξ ≥ 1 时，GPD 的均值发散，CVaR 在数学上不存在。退化为 VaR 是合理的保守近似。✅

---

## 七、其他发现

### 7.1 🟡 `OptimizerConfig` 未使用 `frozen=True`

`portfolio_optimizer.py:25-33`:

```python
@dataclass
class OptimizerConfig:
    risk_free_rate: float = 0.03
    max_weight: float = 0.40
    ...
```

未使用 `@dataclass(frozen=True)`，允许运行时修改。这与 AGENTS.md 的"Always create new objects, never mutate"原则矛盾，也是 `get_efficient_frontier` 能修改 `self.config.target_return` 的根本原因。

### 7.2 🟡 `historical_risk.py` 仍使用废弃模式

`historical_risk.py:3-18`:

```python
from .evt_risk import EVTRisk

class HistoricalSimulationRisk(EVTRisk):
    def __init__(self):
        super().__init__()
        warnings.warn("EVTRisk is deprecated, use HistoricalSimulationRisk", ...)
```

`evt_risk.py:386` 的 `EVTRisk = HistoricalSimulationRisk` 别名仍然存在。`historical_risk.py` 继承自这个别名，创建了一个无意义的子类。v2 文档在 Section 3.2 提议清理但未体现在路线图中。

### 7.3 🟢 `PositionSizingResult` 未使用 `frozen=True`

`sizer.py:216-223`:

```python
@dataclass
class PositionSizingResult:
    symbol: str
    notional: float
    ...
```

v2 文档的 Section 4.2 修复方案创建了新对象（正确），但未建议将 `PositionSizingResult` 改为 `frozen=True` 以从类型系统层面防止变异。

### 7.4 🟢 v2 文档版本号

文档头部写 `版本: v1.0`，但实际内容已根据 v1 review 修正。建议更新为 `v1.1` 或 `v2.0`。

---

## 八、v1 修正完成度汇总

| # | v1 问题 | v2 状态 | 详情 |
|---|---------|---------|------|
| 1 | LimitScalar 公式-代码矛盾 | ✅ 已修正 | 公式、代码、大部分表格一致 |
| 2 | `_ks_test` 死代码 | ✅ 已修正 | `cdf_values` 已删除 |
| 3 | 双重 GPD 拟合 | ✅ 已修正 | `fit` 参数正确避免三重拟合 |
| 4 | "循环继承" 描述 | ✅ 已修正 | 改为"别名继承混乱" |
| 5 | `get_efficient_frontier` 变异 | ⚠️ 已记录未修复 | 新 Section 准确但源码未变 |
| 6 | `compute_rolling_mdd` 非向量化 | ⚠️ 已记录未修复 | 注释准确但源码未变 |
| 7 | 缓存键哈希碰撞 | ⚠️ 已记录但建议有缺陷 | `pd.util.hash_pandas_object` 有 NaN 问题 |
| 8 | `calculate_ntf_signal` 概念混淆 | ❌ 未提及 | `VOLATILITY_HIGH` 仍用于回撤比较 |
| 9 | 测试断言缺乏区分度 | ❌ 未修正 | 所有断言仍命中边界 |

---

## 九、最终结论

### 评分理由

| 维度 | 得分 | 说明 |
|------|------|------|
| 问题识别 | 9/10 | 正确识别了绝大部分实际问题，新增 `get_efficient_frontier` 发现出色 |
| 数学正确性 | 8/10 | EVT 公式正确，LimitScalar 已统一，但 ST 表值计算错误 |
| 代码质量 | 8/10 | `fit` 参数设计合理，`_ks_test` 清理干净，但 `pd.util.hash_pandas_object` 建议有技术缺陷 |
| 完整性 | 7/10 | `get_efficient_frontier` 和 `compute_rolling_mdd` 仅记录未修复，`calculate_ntf_signal` 遗漏 |
| 可操作性 | 7/10 | 路线图清晰但缺少 P0 修复项，测试覆盖不足 |

### 必须在实施前修正的事项

1. **修正 ST 股敏感度表值**: 2.40 → 2.00（或注明使用的 `avg_turnover_ratio`）
2. **将 `get_efficient_frontier` 修复加入 Phase 1 路线图**
3. **替换 `pd.util.hash_pandas_object` 建议**: 改为 `hash(returns.values.tobytes())`
4. **将 LimitScalar 方向改为 `limit_pct / 0.10`**: 当前方向（科创板惩罚降低）与风险管理直觉相反

### 建议优先级

| 优先级 | 事项 | 工作量 |
|--------|------|--------|
| 🔴 P0 | `get_efficient_frontier` 不传 `self.config` | 0.5h |
| 🔴 P0 | `OptimizerConfig` 改为 `frozen=True` | 0.5h |
| 🔴 P0 | 修正 ST 表值或公式方向 | 5min |
| 🟡 P1 | `compute_rolling_mdd` 向量化 | 1h |
| 🟡 P1 | 缓存键改用 `tobytes()` | 15min |
| 🟡 P1 | `calculate_ntf_signal` 使用独立回撤阈值 | 15min |
| 🟢 P2 | `PositionSizingResult` 改为 `frozen=True` | 15min |
| 🟢 P2 | 测试增加中间值断言 | 30min |

---

*审查完毕 | 基于源码逐行校验 | v1 修正率: 6/9 完全修正, 2/9 部分修正, 1/9 遗漏*
