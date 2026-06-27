# Wyckoff Multi-Timeframe Verification — Design & Implementation Plan

> 基于通达信本地日线合成周线/月线, 对 Wyckoff 方法在 A 股市场进行完整多周期验证
>
> Version: 1.0
> Date: 2026-06-24

---

## 0. 核心认知：Wyckoff 是什么（以及不是什么）

### 错误的理解（之前的验证所基于的）
- ❌ Wyckoff 是定时调仓的信号发生器（每 40 天输出一次多/空/空仓）
- ❌ Wyckoff 是日线级别的技术指标（RSI/MACD 的替代品）
- ❌ Wyckoff 是高频交易策略（每天产生信号）

### 正确的理解
- ✅ Wyckoff 是一个 **多时间框架市场语境框架**
- ✅ 它回答的是「市场现在处于哪个阶段」而不是「明天该买还是该卖」
- ✅ 它需要 **自上而下分析**: 月线定方向 → 周线定位置 → 日线定时机
- ✅ 它的核心优势是 **过滤**（筛掉逆势信号）而不是预测
- ✅ 它是 **位置交易（position trading）**，持有周期以月计而非以天计

### 为什么之前的验证失败了
| 问题 | 原因 | 后果 |
|---|---|---|
| 单一日线分析 | 日线噪音淹没阶段信号 | 500K 事件但效应量接近 0 |
| 40 日滚动窗口 | 窗口太短，无法识别 1-3 年的积累/派发阶段 | 42% UNKNOWN |
| 多空信号回测 | Wyckoff 不是定时输出策略 | 86K 交易，成本吃光全部微弱优势 |
| 未解决幸存者偏差 | golden_100 大蓝筹 | 样本外全部失效 |

---

## 1. 核心创新：多时间框架合成

### 1.1 周线合成

从通达信日线数据合成周线 OHLCV：

```
规则:
  - 按 ISO 周（周一到周五）聚合
  - open    = 该周第一个交易日的开盘价
  - high    = 该周最高价（5 日最高）
  - low     = 该周最低价（5 日最低）
  - close   = 该周最后一个交易日的收盘价
  - volume  = 该周日成交量之和
  - amount  = 该周日成交额之和
  - n_days  = 该周实际交易日数（处理节假日缺失）
```

**数据范围**: A 股约 5,900 只, 每只 ~250-300 根周线（5 年）

### 1.2 月线合成

```
规则:
  - 按自然月（calendar month）聚合
  - open    = 该月第一个交易日的开盘价
  - high    = 该月最高价
  - low     = 该月最低价
  - close   = 该月最后一个交易日的收盘价
  - volume  = 该月日成交量之和
  - amount  = 该月日成交额之和
  - n_days  = 该月实际交易日数
```

**数据范围**: 每只 ~60 根月线（5 年）

### 1.3 多时间框架数据匹配

建立时间索引关系表：

| 日线日期 | 所在周 | 所在月 | 日线索引 | 周线索引 | 月线索引 |
|---|---|---|---|---|---|
| 2024-01-02 | 2024-W1 | 2024-01 | 0 | 0 | 0 |
| ... | ... | ... | ... | ... | ... |

这允许我们在事件研究中将日线事件映射到其周线/月线上下文。

---

## 2. Wyckoff 多时间框架分析框架

### 2.1 月线阶段检测（宏观语境）

**输入**: 36-60 根月线（3-5 年）

**检测方法**: 使用系统现有的 `WyckoffEngine.analyze()`，但输入换为月线数据

**输出阶段**:
| 阶段 | 定义 | 月线特征 | 预期未来 6 月收益 |
|---|---|---|---|
| Accumulation | 积累 | 价格横盘在低位, 成交量萎缩, 振幅收窄 | 正（均值回归+趋势启动） |
| Markup | 上涨 | 价格趋势向上, 成交量放量, 高点上移 | 正（趋势延续） |
| Distribution | 派发 | 价格横盘在高位, 成交量放大, 振幅加大 | 负（趋势反转） |
| Markdown | 下跌 | 价格趋势向下 | 负（趋势延续） |
| Unknown | 未知 | 无法判定 | ~0（随机） |

**预期效果**: 月线阶段分类应显著预测 6 个月后的收益。这是整个验证的 **第一性假设**——如果月线阶段不能预测未来收益，Wyckoff 在 A 股根本不可用。

### 2.2 周线确认（中观语境）

**输入**: 12-24 根周线（3-6 个月）

**检测方法**: 同样用 `WyckoffEngine.analyze()` 输入周线

**核心功能**:
1. 确认月线阶段的判断（如果月线=Accumulation 而周线=Markup → 不一致, 降低信心）
2. 识别周线级别的 Spring/UT（结构性的支撑/阻力测试）
3. 检测阶段转换的早期信号（月线还在 Accumulation 但周线已转 Markup → 提前入场信号）

**预期效果**: 月周一致时信号质量提升 50%+

### 2.3 日线执行（微观语境）

**输入**: 20-60 根日线（1-3 个月）

**核心功能**:
1. **仅在月线+周线确认后**寻找入场点
2. 日线 Spring → Accumulation 阶段确认后的入场信号
3. 日线 Upthrust → Distribution 阶段确认后的离场/做空信号
4. 日线主要用于时机选择（timing），而非方向判断（direction）

### 2.4 层次化信号生成规则

信号层级体系（决定性规则表）：

```
信号等级 = f(月线阶段, 周线阶段, 周线模式, 日线模式)

Level A — 最高确信: 月线积累 + 周线积累 + 周线 Spring + 日线 Spring
  → 入场信号, 正常仓位
Level B — 高确信: 月线积累 + 周线积累 + 日线 Spring
  → 入场信号, 半仓
Level C — 中确信: 月线积累 + 周线 Spring + 日线 Spring
  → 入场信号, 1/3 仓
Level D — 低确信: 仅日线 Spring
  → 放弃交易（这是之前验证的全部内容——D 级信号）
```

**核心假设**: A/B 级信号的胜率和收益显著高于 C/D 级。这是验证的 **第二性假设**。

---

## 3. 验证方案

### 3.1 验证范围

| 维度 | 设计 |
|---|---|
| 数据 | 通达信日线 + 合成周线/月线 |
| 样本 | 全部 A 股（~5,900 只）, 分层抽样 1,000 只 |
| 时间 | 2010-01 — 2026-06（~16.5 年） |
| 训练/测试 | 时间序列切分: 训练 2010-2021, 测试 2022-2026 |
| 分层标准 | 日均成交额 5 分位, 确保大小盘覆盖 |
| 偏差控制 | 包含已退市股票, 排除上市不足 2 年的新股 |

### 3.2 验证假设 (H1-H7)

| ID | 假设 | 检验方法 | 预期 |
|---|---|---|---|
| **H1** | 月线阶段可预测未来 6 个月收益 | 按月线阶段分组统计 F-检验 | Accum > Markdown |
| **H2** | 月线 Accumulation 段正收益, Distribution 段负收益 | 单样本 t 检验（对 0） | Accum: μ>0, Dist: μ<0 |
| **H3** | 多时间框架一致（月周同向）时信号质量优于不一致时 | 分组比较 t 检验 | 一致组胜率 > 不一致组 ≥ 10% |
| **H4** | 层次化信号（Level A/B）优于单一日线信号（Level D） | 配对样本检验 | A > D 在 95% 置信水平 |
| **H5** | 月线阶段转换附近（Acc->Markup, Dist->Markdown）是最高 alpha 区域 | 事件研究：阶段转换前/后 3 个月 | 转换窗口超额收益显著 |
| **H6** | 周线 Spring 在月线 Accumulation 中比在 Markdown 中更有效 | 交互效应检验（ANOVA） | 交互项显著 |
| **H7** | 全策略（多时间框架 + 层次信号 + A 股成本）可跑赢买入持有 | 完整回测 | 夏普 > 0.5, 超额收益 > 3%/年 |

### 3.3 统计方法

| 检验 | 适用假设 | 阈值 |
|---|---|---|
| Bootstrap 均值差异（1,000 次） | H1, H2 | 95% CI 不重叠 |
| Welch's t-test | H3, H4, H5 | p < 0.05（BH 校正） |
| Two-way ANOVA | H6 | 交互项 F-test p < 0.05 |
| 完整回测 + 滚动窗口 | H7 | 夏普, 最大回撤, 超额收益 |

### 3.4 基准和成本模型

| 基准 | 说明 |
|---|---|
| 买入持有（BH） | 等权持有所选股票 |
| 等权全市场 | 等权持有全样本 |
| 动量因子 | 12-1 月动量前 20% |
| 低波因子 | 过去 252 日波动率最低 20% |

**成本模型**（完整 A 股）:
- 佣金: 0.03%（最低 5 元/笔）
- 印花税: 0.1%（仅卖出）
- 滑点: 0.1%（成交价偏移）
- T+1 约束: 当日买入次日才能卖出
- 涨跌停限制: ±10%（ST ±5%, 科创板/创业板 ±20%）

### 3.5 输出度量

```python
# 每只股票的验证输出
{
    "symbol": "600519.SH",
    "monthly_phases": [
        {"date": "2022-01", "phase": "accumulation", "confidence": "B"},
        ...
    ],
    "weekly_signals": [
        {"date": "2022-03-15", "phase": "accumulation", "spring": True, "level": "A"},
        ...
    ],
    "daily_entries": [
        {"date": "2022-03-18", "entry_price": 1680, "signal_level": "A",
         "monthly_phase": "accumulation", "weekly_phase": "accumulation",
         "exit_date": "2022-08-15", "exit_price": 1950, "pnl_pct": 16.07},
        ...
    ],
    "summary": {
        "total_return_pct": 124.5,
        "annualized_return_pct": 14.2,
        "sharpe": 1.08,
        "max_drawdown_pct": -18.5,
        "n_trades": 12,
        "win_rate": 75.0,
        "avg_hold_months": 4.2,
    }
}
```

---

## 4. 预期效果与实际验证目标

### 4.1 预期信号频率

| 时间框架 | 事件类型 | 每只股票每年次数 | 1000 只总计 |
|---|---|---|---|
| 月线 | 阶段判定 | 2-4 次（每 3-6 个月变化一次） | 2,000-4,000 |
| 月线 | 阶段转换 | 0.5-1 次（1-2 年一次转换） | 500-1,000 |
| 周线 | Spring/UT | 3-6 次（每 2-4 个月一次） | 3,000-6,000 |
| 日线 | Spring/UT（无过滤） | 20-50 次 | 20,000-50,000 |
| **日线 | Level A/B 入场信号** | **2-6 次** | **2,000-6,000** |

**多时间框架过滤效果**: 减少 90%+ 的伪信号

### 4.2 验证的三种可能结果

| 结果 | 含义 | 行动建议 |
|---|---|---|
| **H1-H7 全部支撑** | Wyckoff 多周期分析在 A 股有效 | 实盘部署, 持续优化 |
| **H1/H2 不支撑** | 月线阶段不可预测 | **停止**, Wyckoff 不适合 A 股 |
| **H1/H2 支撑但 H3/H4 不支撑** | 月线有用但多周期协同无效 | 仅用月线定方向, 日线用其他方法入场 |

### 4.3 成功标准

| 条件 | 必须 | 期望 |
|---|---|---|
| H1 (月线预测力) | F-test p < 0.05 | 单调性: Acc > Markup > Markdown |
| H2 (Acc/Dist 方向) | t-test p < 0.05 | 效应量 > 3%/半年 |
| H4 (层次化优势) | A比D胜率高10% | A胜率 > 60%, D胜率 < 50% |
| H7 (全策略表现) | 夏普 > 0.5 | 年化超额 > 5% |

---

## 5. 实现结构

```
scripts/wyckoff_multitf_verification/
  __init__.py
  config.py                    — 配置参数
  data_synthesis.py            — 日线→周线/月线合成
  a_universe.py                — 无偏样本构建
  b1_monthly_phase.py          — H1/H2: 月线阶段预测力
  b2_weekly_confirmation.py    — H3: 周线确认效果
  b3_hierarchical_signals.py   — H4/H6: 层次信号对比
  b4_phase_transition.py       — H5: 阶段转换事件研究
  c_full_strategy.py           — H7: 完整多周期策略
  d_regime_analysis.py         — 市场状态归因
  runner.py                    — 主入口
  output/                      — 结果输出
```

### 5.1 各模块关键 API

```python
# data_synthesis.py
def synthesize_bars(df_daily: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (weekly_df, monthly_df) with OHLCV columns."""

# b1_monthly_phase.py
def compute_monthly_phases(df_monthly: pd.DataFrame) -> List[MonthlyPhase]:
    """Run WyckoffEngine.analyze() on monthly bars."""

def phase_forward_returns(
    df_daily: pd.DataFrame,
    phases: List[MonthlyPhase]
) -> Dict[str, List[float]]:
    """For each monthly phase, compute 6-month forward return."""

# b3_hierarchical_signals.py
def hierarchical_vs_daily_only(
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    df_monthly: pd.DataFrame
) -> Dict:
    """Compare Level A/B signals vs Level D.
      Returns win rates, mean returns for each level."""
```

### 5.2 与现有系统的集成

直接复用 `src/uniquant/brain/wyckoff/engine.py` 中的 `WyckoffEngine.analyze()`:

```python
from uniquant.brain.wyckoff.engine import WyckoffEngine

engine = WyckoffEngine()
# 月线分析
monthly_result = engine.analyze(monthly_df)
monthly_phase = monthly_result.get("phase")
monthly_conf = monthly_result.get("confidence")

# 周线分析
weekly_result = engine.analyze(weekly_df)
weekly_phase = weekly_result.get("phase")

# 日线检测 Spring
springs = detect_springs(daily_df)  # 使用现有逻辑
```

这意味着验证的不是一个「新 Wyckoff」，而是 **系统中已有的 WyckoffEngine 在更高时间框架上的表现**。

---

## 6. 数据选取细则

### 6.1 通达信日线数据源

```
路径: data/lake/quotes/daily/{symbol}.parquet
格式: date, open, high, low, close, amount, volume, code, market
规模: ~5,900 只股票, 每只 > 10 年数据
```

### 6.2 筛选标准

| 标准 | 值 | 原因 |
|---|---|---|
| 最少上市天数 | ≥750（~3 年） | 月线分析需要至少 36 根月线 |
| 最少的月线数 | ≥36 | 3 年的月线才能判断阶段 |
| 最少交易额 | > 0 | 排除无交易僵尸股 |
| 包含退市股 | 是 | 幸存者偏差控制 |
| IPO 保护期 | 250 交易日后纳入 | 新股价格发现期 |

### 6.3 分层抽样

```
流动性分层（按日均成交额）:
  Q1: < 5 百万（微盘）
  Q2: 5M - 30M（小盘）
  Q3: 30M - 150M（中盘）
  Q4: 150M - 1B（大盘）
  Q5: > 1B（超大/蓝筹）

每层抽取 200 只 → 总样本 1,000 只
```

### 6.4 时间区间划分

| 区间 | 用途 | 特点 |
|---|---|---|
| 2010-01 ~ 2021-12 | 训练集 | 包含多轮牛熊 |
| 2022-01 ~ 2026-06 | 测试集 | 样本外验证 |
| 2015-01 ~ 2016-02 | Bear 子集 | 熔断/股灾 |
| 2019-01 ~ 2021-02 | Bull 子集 | 结构性牛市 |
| 2023-01 ~ 2024-09 | Sideways 子集 | 横盘震荡 |

---

## 7. 实施步骤

```
Phase 0: 数据准备 (1 天)
  0.1 扫瞄全市场 parquet 文件, 统计元数据
  0.2 合成周线/月线
  0.3 构建无偏样本（分层抽样 1,000 只）
  0.4 存入缓存目录避免重复合成

Phase 1: 月线阶段分析 (2 天)
  1.1 运行 WyckoffEngine.analyze() 在月线上
  1.2 按阶段分组统计 6 个月后收益
  1.3 Bootstrap CI + ANOVA 检验 H1/H2
  1.4 输出: 月线阶段预测力报告

Phase 2: 周线确认分析 (1 天)
  2.1 运行 WyckoffEngine.analyze() 在周线上
  2.2 周月一致性分组统计 (H3)
  2.3 周线 Spring 在不同月线阶段下的表现 (H6)
  2.4 输出: 多时间框架协同报告

Phase 3: 层次化信号对比 (1 天)
  3.1 实现 Level A/B/C/D 信号生成
  3.2 对比各层级的胜率、收益、交易频率
  3.3 Bootstrap 差异检验 (H4)
  3.4 输出: 层次信号有效性报告

Phase 4: 阶段转换事件研究 (1 天)
  4.1 检测月线阶段转换时间点
  4.2 事件窗口分析（前后 3 个月）
  4.3 超额收益 t 检验 (H5)
  4.4 输出: 阶段转换 alpha 报告

Phase 5: 完整策略回测 (2 天)
  5.1 实现多周期条件入场/出场逻辑
  5.2 A 股全成本模型
  5.3 与基准对比 (H7)
  5.4 敏感性分析（参数扫描）
  5.5 输出: 完整策略表现报告

Phase 6: 汇总与结论 (0.5 天)
  6.1 汇总所有假设检验结果
  6.2 三个可能结论的判断树
  6.3 最终建议
```

**总工作量**: ~8.5 天（可并行 Phase 1-4 中的独立计算）

---

## 8. 与传统验证的关键区别

| 维度 | 之前（单一日线） | 本次（多时间框架） |
|---|---|---|
| 时间粒度 | 40 日滚动窗口 | 月线（宏观）/ 周线（中观）/ 日线（微观） |
| 信号频率 | 86,662 次/1000 只/4.5 年 | 预期 ~3,000 次（减少 96%） |
| 持有周期 | 18 天（过度交易） | 2-6 个月（位置交易） |
| 交易成本 | 占收益的 60%+ | 预期 < 20% |
| Phase 来源 | 股票自身日线 | 股票自身月线/周线/日线 |
| 幸存者偏差 | 存在（golden_100） | 无偏分层 1,000 只 |
| 统计效力 | N 大但效应量小 | N 适中但效应量大 |
| 与实战的差距 | 大（没人按 40 天调参） | 小（专业 Wyckoff 交易员的操作方式） |

---

## 9. 风险与限制

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 月线数据点不足（60 根月线/5 年） | 中 | 统计效力降低 | Bootstrap CI + Bayesian 方法 |
| 合成周线/月线丢失日内信息 | 高 | Spring/UT 精度下降 | 承认限制, 仅验证宏观阶段 |
| A 股政策突变影响阶段有效性 | 中 | 样本外失效 | 多区间测试（2015/2018/2022） |
| WyckoffEngine 在月线上表现差 | 低-中 | 检验可能不支撑 H1 | 这是验证本身要回答的问题 |
| Level2 数据缺失无法验证 tape-reading | 高 | 只能验证 Layer 1/2 | 文档中明确标注限制 |
