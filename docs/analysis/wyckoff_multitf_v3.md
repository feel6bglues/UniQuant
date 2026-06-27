# Wyckoff 多周期验证——修正版 v3

> 解决 v2 的五个缺陷（单点截面、无成本、阈值过严、缺相位持续性、一致性定义粗糙）
>
> 2026-06-24 | v3

---

## v2 缺陷根因分析

| 缺陷 | 根因 | 导致偏差 |
|---|---|---|
| **单点截面** | 只用 2024-12-31 一个时间点做 cutoff | 结论被 2025 Q1 反弹行情绑架（markdown 反弹 +19% 不代表相位本身有效） |
| **无交易成本** | 策略收益比较未扣交易成本 | Markup 策略 +9.24% 是高估的（月频调仓成本约 1-2%/年） |
| **H4 阈值过严** | `accum + week_accum + daily_spring` 单阈值 | 0 次命中 → 无法评估，不是"信号不存在"而是"没找到这个参数的信号" |
| **无相位持续性** | 只取当前相位，不分析相位历史 | 无法区分"持续 Markup"和"刚从 Accum 转 Markup"的本质区别 |
| **H3 一致性粗糙** | `monthly_phase == weekly_phase` 二元判断 | 部分一致（月线 Accum 转周线 Markup）是早期信号却归为"不一致" |

---

## v3 修正方案

### 1. 滚动截面（核心修复）

```
对于每只股票:
  对于每个月末 t in ["2020-01-31", "2020-02-29", ..., "2024-06-28"]:
    截取数据至 t
    运行多周期 Wyckoff 分析（日线/周线/月线）
    记录: 月线相位, 周线相位, 日线 Spring, 置信度
    计算后续 1月/3月/6月收益
```

**数据量**: 54 个月 × 1,000 只 = **54,000 个观测**（vs v2 的 1,000 个）

**关键优势**:
- 覆盖多个市场状态（2020 疫情底, 2021 高点, 2022 熊市, 2023 横盘, 2024 反弹）
- 可以区分"相位本身"和"市场环境"的效应
- 统计效力足够做面板回归（固定效应 + 时间效应）

**计算量估算**:
```
54,000 个截面 × 3 时间框架 × 0.2s / 8 workers ≈ 68 分钟
可接受范围: < 2 小时
```

### 2. 平滑信号阈值（修复 H4）

不再用单阈值，而是测试多个信号规则：

```
宽松度级别:
  L1 (最严): 月线=accum AND 周线=accum AND 周线 Spring AND 日线 Spring
  L2 (较严): 月线=accum AND (周线=accum OR 周线 Spring) AND 日线 Spring
  L3 (中等): 月线 IN (accum, markup) AND 日线 Spring
  L4 (较松): 月线 NOT markdown AND 日线 Spring
  L5 (最松): 日线 Spring（无条件=噪声底限）

对每个级别计算: 
  - 命中数 N（信号密度）
  - 平均 3 月收益（信号质量）
  - 收益/频率 Pareto 前沿
```

这样就能回答"把阈值设在哪里能最大化信息比率"——而不是一刀切说"阈值无效"。

### 3. 相位持续性特征（新增 H5）

每个观测点提取相位历史特征：

```python
features = {
    "current_phase": phase,                                    # v2已有
    "phase_3m_ago": phase_3m_ago,                             # 新增
    "phase_6m_ago": phase_6m_ago,                             # 新增
    "had_transition": phase_3m_ago != phase,                   # 新增: 最近3月是否转换
    "transition_type": f"{phase_3m_ago}→{phase}",             # 新增: 转换类型
    "phase_duration_months": duration,                         # 新增: 当前相位持续月数
    "num_transitions_12m": count,                              # 新增: 12月内转换次数
}
```

检验 H5: `transition_type = "markdown→accumulation"` 的预测力是否显著强于 `phase = "accumulation"`。

### 4. 交易成本模型（修复 H7）

```
策略收益 = 毛收益 - 交易成本

单笔交易成本（A 股）:
  - 佣金: 0.03% × 成交额（最低 5 元/笔）
  - 印花税: 0.1% × 卖出成交额
  - 滑点: 0.1% × 成交额（双向）

年化成本估算:
  月度调仓（每只每年进出 2-6 次）:
    每笔 ~0.23%（佣金 0.03 + 滑点 0.1 + 调整印花税=~0.23%）
    6 次/年 × 0.23% = 1.38%/年
```

### 5. 分层一致性（修复 H3）

```
一致性级别:
  Strong:  月线=周线 Phase AND 置信度都 ≥ B
  Partial: 月线≠周线但 周线 Phase 是月线的"下一阶段"
           (e.g., 月线=accum, 周线=markup → 早期转换信号)
  Weak:    月线≠周线 且 非 Partially 一致
  Conflicting: 月线 Phase 与 周线 Phase 方向相反
           (e.g., 月线=accum, 周线=distribution)

预期: Strong > Partial > Weak ≈ Conflicting
```

---

## 完整假设列表（H1-H7 v3）

| ID | 假设 | 检验 | 修复点 |
|---|---|---|---|
| **H1** | 月线相位预测未来 6 月收益（面板） | 固定效应面板回归 | 从单点→滚动截面 |
| **H2** | Accum > 0, Dist < 0（各截面平均） | 聚类标准误 t-test | 同上 |
| **H3** | 多周期一致性分层→收益排序 | 单调性检验（Jonckheere） | 从二元→4 级分层 |
| **H4** | 不同信号阈值有 Pareto 前沿 | 多重阈值扫描 | 从单阈值→5 级扫描 |
| **H5** | 相位转换历史叠加预测力 | 嵌套模型 F 检验 | 新增 |
| **H6** | 相位持续性提高信号质量 | 分组比较持续时间分组 | 新增 |
| **H7** | 最优策略（含成本）vs BH | 完整回测 | 加入交易成本 |

---

## 实现架构

```python
# 数据结构
@dataclass
class RollingObservation:
    symbol: str
    cutoff_date: str
    monthly_phase: str
    weekly_phase: str
    monthly_conf: str
    weekly_conf: str
    daily_spring: bool
    weekly_spring: bool
    fwd_1m_pct: float
    fwd_3m_pct: float
    fwd_6m_pct: float
    phase_3m_ago: str = ""
    phase_6m_ago: str = ""
    duration_months: int = 0
    had_transition: bool = False

# 核心函数
def generate_rolling_panel(
    records: List[StockRecord],
    start_month: str = "2020-01",
    end_month: str = "2024-06",
    n_jobs: int = 8,
) -> List[RollingObservation]:
    """为每只股票每月末生成一个观测。返回 ~54,000 个行。"""

# 验证函数  
def run_panel_h1(panel: List[RollingObservation]) -> HypothesisResult:
    """固定效应面板: return ~ phase + ret_3m_prior + volatility"""

def scan_h4_thresholds(panel: List[RollingObservation]) -> Dict:
    """ROC 曲线: 不同宽松度下的信号密度 vs 质量"""

def add_phase_history(panel: List[RollingObservation]) -> List[RollingObservation]:
    """为每个观测补上相位历史特征（H5/H6）"""

def run_full_backtest_h7(panel: List[RollingObservation], cost_pct: float) -> StrategyResult:
    """含成本的完整回测"""
```

---

## 预期输出格式

```json
{
  "meta": {
    "n_stocks": 1000,
    "n_months": 54,
    "n_observations": 54000,
    "date_range": "2020-01 to 2024-06"
  },
  "hypotheses": {
    "H1_panel_phase_predicts": {
      "coefficients": {
        "accumulation": 2.34,
        "markup": 1.12,
        "markdown": -2.89,
        "unknown": -0.45
      },
      "f_stat": 15.3,
      "p_value": 0.00001,
      "supported": true
    },
    "H2_accum_dist_direction": {
      "accum_mean": 2.34,
      "dist_mean": -2.89,
      "t_stat": 4.2,
      "p_value": 0.0001,
      "supported": true
    },
    "H3_consistency_monotonic": {
      "strong_mean": 3.12,
      "partial_mean": 1.45,
      "weak_mean": 0.23,
      "conflicting_mean": -1.89,
      "jt_statistic": 3245,
      "p_value": 0.00001,
      "supported": true
    },
    "H4_threshold_pareto": {
      "levels": {
        "L1_strictest": {"n": 12, "mean_ret_pct": 8.5, "hit_rate": 75.0},
        "L2_strict": {"n": 89, "mean_ret_pct": 5.2, "hit_rate": 62.0},
        "L3_moderate": {"n": 1245, "mean_ret_pct": 3.1, "hit_rate": 55.0},
        "L4_loose": {"n": 8900, "mean_ret_pct": 1.2, "hit_rate": 51.0},
        "L5_noise_floor": {"n": 45000, "mean_ret_pct": 0.5, "hit_rate": 48.2}
      },
      "optimal_level": "L2"
    },
    "H5_transition_history": {
      "transition_alpha": {"markdown→accum": 4.5, "accum→markup": 3.2},
      "nested_f_test": {"f_stat": 8.2, "p_value": 0.001, "supported": true}
    },
    "H6_phase_duration": {
      "short_duration_1m": {"mean": -0.5, "n": 5000},
      "medium_duration_3_6m": {"mean": 1.8, "n": 12000},
      "long_duration_12m_plus": {"mean": 0.3, "n": 18000}
    },
    "H7_full_backtest": {
      "optimal_gross_ann": 14.5,
      "optimal_net_ann": 12.8,
      "cost_ann": 1.7,
      "bh_ann": 8.2,
      "excess_ann": 4.6,
      "sharpe": 0.92,
      "max_drawdown": -18.5
    }
  },
  "verdict": "Wyckoff 多周期分析在 A 股具有统计显著和经济显著的预测能力"
}
```

---

## 与 v2 的对比

| 指标 | v2 | v3 | 改进 |
|---|---|---|---|
| 观测数 | 1,000 | **54,000** | 54× |
| 市场状态覆盖 | 1 个（2025 Q1 反弹） | **7 年牛熊** | 7× |
| 统计方法 | 独立 t 检验 | **面板固定效应** | 控制个股异质性 |
| 成本计入 | 无 | **有** | 关键 |
| 信号阈值 | 1 个 | **5 级 Pareto** | 可操作 |
| 相位历史 | 无 | **有（H5/H6）** | 全新维度 |
