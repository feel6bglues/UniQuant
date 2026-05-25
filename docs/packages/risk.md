# risk -- 风险管理

`uniquant.risk` 包提供组合优化、仓位管理、回撤分析、极值风险计算和结构性风险评估能力，约 1.3K LOC。该包被 services 层和 ui 层广泛调用，是系统风控体系的核心。

公开导出（`__init__.py`）：

- `PositionSizer`, `InvalidStopLossError`
- `PortfolioOptimizer`, `OptimizerConfig`
- `HistoricalSimulationRisk`
- `StructuralRiskManager`

---

## 组合优化器

`portfolio_optimizer.py` 实现两种经典组合优化方法。

### OptimizerConfig dataclass

```python
@dataclass
class OptimizerConfig:
    risk_free_rate: float = 0.03       # 无风险利率（年化）
    max_weight: float = 0.40           # 单资产最大权重
    min_weight: float = 0.0            # 单资产最小权重
    target_return: Optional[float] = None  # 目标收益率
    max_iterations: int = 1000         # 最大迭代次数
    tolerance: float = 1e-8            # 收敛容差
```

### PortfolioOptimizer

构造接受 `OptimizerConfig`，优化后结果存入实例属性 `weights_`、`expected_return_`、`expected_volatility_`、`sharpe_ratio_`。

#### 风险平价优化 -- optimize_risk_parity()

```python
optimizer.optimize_risk_parity(returns: pd.DataFrame, target_weights=None) -> Dict[str, Any]
```

目标：各资产的风险贡献（risk contribution）相等。

算法流程：
1. 初始等权分配
2. 迭代计算每个资产的边际风险贡献 `marginal_contrib = cov @ weights`
3. 计算风险贡献差值并沿梯度方向调整权重
4. 每步施加 `min_weight` / `max_weight` 约束并归一化
5. 收敛条件：权重变化最大值 < tolerance

返回字典包含：`method`, `weights`, `expected_return`, `expected_volatility`, `sharpe_ratio`, `risk_contributions`, `iterations`。

#### 均值-方差优化 -- optimize_mean_variance()

```python
optimizer.optimize_mean_variance(
    returns: pd.DataFrame,
    expected_returns: Optional[np.ndarray] = None,
    target: str = "max_sharpe"
) -> Dict[str, Any]
```

使用 `scipy.optimize.minimize`（SLSQP 方法），支持三种优化目标：

| target | 说明 |
|--------|------|
| `"max_sharpe"` | 最大化夏普比率（最小化负夏普） |
| `"min_volatility"` | 最小化组合波动率 |
| `"target_return"` | 在目标收益率约束下最小化风险 |

约束条件：权重之和 = 1，每个权重在 `[min_weight, max_weight]` 范围内。

#### 有效前沿 -- get_efficient_frontier()

```python
optimizer.get_efficient_frontier(returns, expected_returns=None, n_points=20) -> pd.DataFrame
```

在最小预期收益到最大预期收益之间均匀采样 `n_points` 个目标收益率，逐一运行 `target_return` 优化，返回包含 `target_return`, `expected_return`, `volatility`, `sharpe_ratio` 列的 DataFrame。

---

## 仓位管理

`sizer.py` 实现 Kelly 准则启发的仓位计算，融合 T+1 惩罚和 CZSC 几何止损。

### PositionSizer

```python
sizer = PositionSizer(initial_capital=100000.0, risk_pct=0.05)
```

#### T+1 隔夜风险惩罚

不同市场的惩罚系数（`market_penalties`）：

| 市场 | 惩罚系数 | 说明 |
|------|----------|------|
| CN | 1.2 | A 股 T+1 交易制度，隔夜持仓风险更高 |
| US | 1.0 | T+0 无额外惩罚 |
| HK | 1.0 | T+0 无额外惩罚 |

#### 手数规则

`_get_lot_size(market, symbol)`:
- CN: 100 股/手
- US: 1 股/手
- HK: 100 股/手（简化处理）

#### 核心计算 -- calculate_shares()

```python
result = sizer.calculate_shares(
    price=10.0,
    stop_loss=9.5,
    market="CN",
    czsc_bottom=9.6,    # CZSC底分型止损
    atr_stop=9.5,       # ATR止损
    symbol="000001.SZ",
)
```

计算流程：

1. **几何止损**：取 `max(atr_stop, czsc_bottom)` 作为最终止损（更保守的价格）
2. **单股风险**：`risk_per_share = price - final_stop`（使用 `safe_round` 精度保护）
3. **T+1 惩罚**：`max_loss_allowed = capital * risk_pct`
4. **股数计算**：`shares = max_loss_allowed / (risk_per_share * penalty)`，向下取整到手数
5. **熔断检查**：如果 `total_value > capital`，触发资金熔断，调整为最大可买股数

返回字典键：`建议动作`, `入场区间`, `几何止损`, `ATR止损`, `执行止损`, `风险敞口`, `建议仓位`, `资金占用`, `是否触发熔断`, `修正仓位`, `penalty_applied`, `risk_per_share`, `max_loss_allowed`。

#### 精度安全工具

模块还提供三个精度安全函数：
- `safe_round(value, precision=2)` -- NaN/Inf 安全的四舍五入
- `safe_compare(a, b, epsilon=1e-9)` -- 浮点数比较
- `safe_divide(numerator, denominator, default=0.0)` -- 除零保护

### InvalidStopLossError

当止损价 >= 入场价时抛出，继承自 `ValueError`。

---

## 回撤分析

`drawdown_analyzer.py` 实现全向量化的回撤分析引擎，零 iterrows，全部使用 NumPy 算子。

### DrawdownMetrics dataclass

| 字段 | 说明 |
|------|------|
| `max_drawdown` | 最大回撤幅度 |
| `max_drawdown_duration` | 最长回撤持续天数 |
| `avg_drawdown` | 平均回撤幅度 |
| `avg_drawdown_duration` | 平均回撤持续天数 |
| `calmar_ratio` | Calmar 比率 = 年化收益 / |MDD| |
| `ulcer_index` | Ulcer 指数 = sqrt(mean(dd^2)) |
| `rolling_mdd_60d` | 60 日滚动最大回撤 |
| `rolling_mdd_120d` | 120 日滚动最大回撤 |
| `rolling_mdd_252d` | 252 日滚动最大回撤 |

### TailRiskMetrics dataclass

| 字段 | 说明 |
|------|------|
| `var_95` / `var_99` | VaR（95%/99%置信区间） |
| `cvar_95` / `cvar_99` | CVaR（条件 VaR） |
| `tail_ratio` | 右尾/左尾比率 |
| `skewness` | 偏度 |
| `kurtosis` | 峰度 |

### StressTestResult dataclass

| 字段 | 说明 |
|------|------|
| `scenario` | 场景名称 |
| `loss_pct` | 损失百分比 |
| `loss_value` | 损失金额 |
| `recovered` | 是否恢复 |
| `recovery_days` | 恢复天数 |

### DrawdownAnalyzer 类

全部为静态/类方法：

#### compute_drawdown_series(equity)

向量化计算回撤序列：

```
rolling_max = np.maximum.accumulate(equity)
dd = (equity - rolling_max) / max(rolling_max, 1e-10)
```

#### compute_rolling_mdd(equity, window)

计算滚动窗口内的最大回撤。

#### analyze_drawdown(equity, annual_return=0.0)

完整回撤分析：
1. 计算回撤序列，提取 MDD、平均回撤
2. 通过 `np.diff` 检测回撤区间的起止点，计算持续时间
3. 计算 Ulcer 指数、Calmar 比率
4. 计算 60/120/252 日滚动 MDD

#### analyze_tail_risk(returns)

尾部风险分析：
- VaR 使用 `np.percentile` 历史分位数法
- CVaR 为超过 VaR 阈值的平均损失
- 偏度/峰度使用矩估计

#### stress_scenario(equity, scenario_name)

内置 5 种历史压力场景：

| 场景 | 冲击幅度 |
|------|----------|
| `2015_crash` | -40% |
| `2016_meltdown` | -10% |
| `2018_bear` | -30% |
| `2020_covid` | -15% |
| `2024_microcap_stampede` | -25% |

---

## 极值风险

### HistoricalSimulationRisk (evt_risk.py)

尽管类名中包含 "EVT"，实际实现使用的是历史模拟方法（百分位 VaR/CVaR），而非真正的极值理论（GPD 拟合）。类初始化时会发出 `DeprecationWarning`。

核心方法：

| 方法 | 说明 |
|------|------|
| `calculate_metrics(returns)` | 综合计算 VaR(95%/99%)、CVaR(95%/99%)、最大回撤、市场状态、NTF 信号 |
| `calculate_var(returns, confidence)` | `VaR = -np.percentile(returns, (1-confidence)*100)` |
| `calculate_cvar(returns, confidence)` | `CVaR = -mean(returns[returns <= -VaR])`，空尾部时 CVaR >= VaR |
| `detect_regime(returns)` | 基于年化波动率和夏普比率检测市场状态：CRISIS/HIGH_VOL/BULL/BEAR/NORMAL |
| `calculate_max_drawdown(returns)` | 累计收益法计算最大回撤 |
| `calculate_ntf_signal(var, max_drawdown, regime)` | 输出 NTF 信号：极度风险/高风险/风险/机会/中性 |
| `calculate_stress_test(returns, scenarios)` | 基于 `RiskCalculationConstants` 中定义的崩盘/加息/衰退场景执行压力测试 |
| `calculate_correlation_matrix(assets_returns)` | 多资产相关性矩阵 |

线程安全：使用 `threading.Lock` 保护 `_metrics_cache`，支持缓存读写和清理。

缓存键生成：基于收益率的 `mean`、`std`、`skew`、`kurtosis` 和 `len` 组合。

### historical_risk.py 中的 HistoricalSimulationRisk

`historical_risk.py` 中的 `HistoricalSimulationRisk` 继承自 `evt_risk.EVTRisk`（实际就是同一个 `HistoricalSimulationRisk`），纯粹作为废弃兼容层存在，初始化时发出 `DeprecationWarning`。

别名：`EVTRisk = HistoricalSimulationRisk`（在 `evt_risk.py` 末尾定义）。

---

## 结构性风险

`structural.py` 实现 `StructuralRiskManager`，提供宏观层面的多指数风险矩阵评估。

### StructuralRiskManager

从配置（`markets.indices`）加载指数名称，默认覆盖沪深300、中证500、中证1000、上证50。

#### get_macro_conclusion(overall_risk)

根据总体风险等级返回宏观结论：

| 风险等级 | 结论 |
|----------|------|
| `Danger` | "宏观环境风险较高，不建议开仓" |
| `Warning` | "宏观环境存在一定风险，建议谨慎开仓" |
| `Safe` | "宏观环境安全，允许开仓" |

#### format_risk_matrix_for_report(risk_matrix)

格式化风险矩阵用于报告输出，提取每个指数的 `tc`（LPPL 临界时间）、`status`、`note`。

#### generate_structural_context(risk_matrix, overall_risk)

生成结构性上下文字典，包含 `risk_matrix`、`overall_risk`、`macro_conclusion`、`index_names`，供报告生成和仪表盘渲染使用。

#### get_risk_emoji(status)

风险状态可视化标记：Safe -> 绿色, Warning -> 黄色, Danger -> 红色。
