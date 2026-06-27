# 因子系统指南

## 概述

UniQuant 因子系统提供了一套完整的多因子研究管道，覆盖因子生命周期的全部阶段：

```
注册 (Register) -> 计算 (Compute) -> 分析 IC/IR (Analyze) -> 合成 (Compose) -> Walk-Forward 验证 (Validate)
```

**核心组件：**

| 组件 | 模块 | 职责 |
|------|------|------|
| FactorRegistry | `brain.factors.registry` | 全局因子注册中心，线程安全单例 |
| FactorAnalyzer | `brain.factors.analyzer` | IC/IR 分析、因子有效性检验 |
| FactorComposer | `brain.factors.composer` | 因子标准化、正交化、加权合成 |
| WalkForwardFactorPipeline | `brain.factors.walk_forward_pipeline` | 样本外 Walk-Forward 滚动验证 |
| FinancialFactorBridge | `brain.factors.financial_bridge` | 财务因子桥接（中文字段映射、PE/PB 计算） |

因子数据流向：原始行情/财务数据经注册因子的计算函数生成因子值，FactorAnalyzer 计算 Rank IC/IR 评估有效性，FactorComposer 进行 Z-score 标准化、对称正交化与 IC 加权合成，最终通过 WalkForwardFactorPipeline 在样本外滚动窗口中验证因子稳定性。

---

## 因子注册 (FactorRegistry)

> **注意**: 项目中存在两个 `FactorRegistry` 类。(1) `brain.factors.registry.FactorRegistry` — **实际使用的注册中心**，单例模式 + 线程安全锁 + `check_access()` 权限控制；(2) `shared.factor_governance.FactorRegistry` — 旧版设计，已标记弃用，仅保留向后兼容桩。所有因子操作应使用 `from uniquant.brain.factors.registry import FactorRegistry`。

`FactorRegistry` 是全局因子注册中心，采用**单例模式 + 线程安全锁**实现。所有因子必须在此注册后，才能被 FactorAnalyzer、FactorComposer 及扫描管道使用。

### 因子元信息 (FactorInfo)

每个注册因子包含以下元信息：

```python
@dataclass
class FactorInfo:
    name: str                    # 因子名称（唯一标识）
    category: str                # 类别: technical / fundamental / alternative / custom
    compute_func: Callable[[pd.DataFrame], pd.Series]  # 计算函数
    default_weight: float = 1.0  # 默认权重
    enabled: bool = True         # 是否启用
    description: str = ""        # 描述信息
    ic_ir_history: Optional[List[float]] = None  # 历史 IC/IR 记录
```

### 因子类别

| 类别 | 说明 |
|------|------|
| `technical` | 技术面因子（动量、波动率、均线、成交量等） |
| `fundamental` | 基本面因子（PE、PB、ROE、利润率等） |
| `alternative` | 另类数据因子 |
| `custom` | 用户自定义因子 |

### register() 方法签名

```python
@classmethod
def register(
    cls,
    name: str,                          # 因子名称（唯一）
    compute_func: Callable,             # 计算函数: (pd.DataFrame) -> pd.Series
    category: str = "custom",           # 因子类别
    default_weight: float = 1.0,        # 默认权重
    description: str = "",              # 描述
):
```

若注册同名因子，旧因子将被覆盖（会输出警告日志）。

### 核心方法

| 方法 | 说明 |
|------|------|
| `register(name, compute_func, ...)` | 注册新因子（线程安全） |
| `get_all()` | 获取所有已注册因子列表 |
| `get_enabled()` | 获取所有已启用因子列表 |
| `get_factor(name)` | 按名称获取单个因子 |
| `enable(name)` | 启用指定因子 |
| `disable(name)` | 禁用指定因子 |
| `list_factors()` | 列出所有因子名称与描述（调试用） |

### 代码示例

```python
from uniquant.brain.factors.registry import FactorRegistry
import pandas as pd

# 注册自定义因子
def compute_my_factor(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(10)

FactorRegistry.register(
    name="my_momentum_10d",
    compute_func=compute_my_factor,
    category="custom",
    default_weight=0.8,
    description="10日动量因子",
)

# 查看所有已启用因子
enabled = FactorRegistry.get_enabled()
for f in enabled:
    print(f"{f.name} ({f.category}) weight={f.default_weight}")

# 禁用/启用因子
FactorRegistry.disable("volatility_60d")
FactorRegistry.enable("volatility_60d")

# 列出所有因子
print(FactorRegistry.list_factors())
```

---

## 内置因子

### 技术面因子 (custom_factors.py)

以下因子在模块加载时自动注册到 FactorRegistry：

| 因子名称 | 类别 | 默认权重 | 描述 |
|----------|------|----------|------|
| `momentum_20d` | technical | 1.0 | 20日动量因子（收益率） |
| `momentum_60d` | technical | 0.9 | 60日动量因子（收益率） |
| `volatility_20d` | technical | 0.8 | 20日波动率因子（年化） |
| `volatility_60d` | technical | 0.7 | 60日波动率因子（年化） |
| `ma_ratio_5_20` | technical | 0.85 | 5日/20日均线比率 |
| `ma_ratio_10_60` | technical | 0.75 | 10日/60日均线比率 |
| `volume_ratio_5_20` | technical | 0.6 | 5日/20日成交量比率 |
| `rsi_14` | technical | 0.8 | 14日 RSI 因子 |
| `price_position_20d` | technical | 0.7 | 20日价格位置因子（当前价在高低点中的相对位置） |
| `turnover_momentum_20d` | technical | 0.85 | 20日换手率动量因子 |

### 配置覆盖 (factors.yaml)

`config/factors.yaml` 可以覆盖因子的启用状态、权重和类别：

```yaml
factors:
  momentum_20d:
    enabled: true
    weight: 1.2
    category: technical

  turnover_momentum_20d:
    enabled: true
    weight: 0.85
    category: technical

  pe_ttm:
    enabled: true
    weight: 0.7
    category: fundamental
```

### 财务桥接因子 (FinancialFactorBridge)

`FinancialFactorBridge` 将 A 股财务报表的中文字段映射为标准英文字段，并计算衍生因子：

**字段映射（部分）：**

| 中文字段 | 标准名称 | 说明 |
|----------|----------|------|
| 基本每股收益 | `eps` | 每股收益 |
| 每股净资产 | `bps` | 每股净资产 |
| 净资产收益率 | `roe` | ROE |
| 营业收入 | `revenue` | 营业收入 |
| 净利润 | `net_profit` | 净利润 |
| 销售毛利率 | `gross_margin` | 毛利率 |
| 销售净利率 | `net_margin` | 净利率 |
| 资产负债率 | `debt_ratio` | 资产负债率 |
| 流动比率 | `current_ratio` | 流动比率 |
| 速动比率 | `quick_ratio` | 速动比率 |
| 总资产 | `total_assets` | 总资产 |
| 归属母公司所有者的净利润 | `net_profit_parent` | 归母净利润 |
| 每股经营现金流量 | `ocf_ps` | 每股经营现金流 |

**衍生因子：**

| 因子名称 | 计算方式 |
|----------|----------|
| `eps_ttm` | 最近 4 个季度 EPS 滚动累加（TTM） |
| `pe_ttm` | 前复权收盘价 / eps_ttm |
| `pb` | 前复权收盘价 / bps |

**使用示例：**

```python
from uniquant.brain.factors.financial_bridge import FinancialFactorBridge

bridge = FinancialFactorBridge()

# 完整处理流程：字段映射 -> TTM 计算 -> PE/PB 计算 -> 合并
result = bridge.process(daily_df, financial_df, price_col="qfq_close")

# 分步使用
mapped = bridge.map_fields(financial_df)       # 中文字段映射
with_ttm = bridge.calculate_eps_ttm(mapped)    # 计算 TTM EPS
merged = bridge.calculate_pe_pb(daily_df, with_ttm)  # 计算 PE/PB

# 获取每只股票最新财务因子
latest = bridge.get_latest_factors(financial_df)
```

---

## 自定义因子开发

### 函数签名

所有因子计算函数必须符合以下签名：

```python
Callable[[pd.DataFrame], pd.Series]
```

- **输入**: `pd.DataFrame`，包含行情数据（至少含 `close` 列，可能含 `open`、`high`、`low`、`volume` 等）
- **输出**: `pd.Series`，因子值序列，index 必须与输入 DataFrame 对齐

### 开发步骤

1. **编写因子计算函数**：

```python
import pandas as pd
import numpy as np

def compute_price_to_ma60(df: pd.DataFrame) -> pd.Series:
    """价格偏离60日均线因子"""
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    ma60 = df["close"].rolling(window=60).mean()
    return (df["close"] - ma60) / ma60.replace(0, np.nan)
```

2. **注册因子**：

```python
from uniquant.brain.factors.registry import FactorRegistry

FactorRegistry.register(
    name="price_to_ma60",
    compute_func=compute_price_to_ma60,
    category="technical",
    default_weight=0.9,
    description="价格偏离60日均线比率",
)
```

3. **使用 FactorAnalyzer 测试有效性**：

```python
from uniquant.brain.factors.analyzer import FactorAnalyzer
from uniquant.brain.factors.composer import FactorComposer

# 先用 Composer 计算因子值
composer = FactorComposer()
factor_df = composer.compute_all_factors(df)

# 将因子值合并到原始数据
df_with_factors = df.copy()
for col in factor_df.columns:
    df_with_factors[col] = factor_df[col]

# IC/IR 分析
analyzer = FactorAnalyzer()
results = analyzer.compute_ic_ir(
    df_with_factors,
    factor_cols=["price_to_ma60"],
    holding_periods=[1, 5, 20],
    mode="backtest",
)

# 查看结果
for factor_name, period_results in results.items():
    for period, result in period_results.items():
        print(f"{factor_name} @ {period}d: IC={result.ic_mean:.4f}, "
              f"IR={result.icir:.4f}, IC>0={result.ic_positive_ratio:.2%}")
```

### 注意事项

- 函数内部须处理输入列缺失的情况，返回全 NaN 的 Series 而非抛出异常
- 因子值应避免前瞻偏差：不要使用未来数据
- 建议对因子值做 winsorize 或 clip 处理异常值
- 因子名称必须唯一，重复注册会覆盖已有因子

---

## IC/IR 分析 (FactorAnalyzer)

`FactorAnalyzer` 使用 Spearman 秩相关系数（Rank IC）衡量因子预测能力。

### 核心概念

- **Rank IC (Information Coefficient)**：因子值的横截面排名与未来收益率排名的 Spearman 相关系数
- **ICIR (IC Information Ratio)**：IC 均值 / IC 标准差，衡量因子预测的稳定性
- **IC > 0 比例**：IC 值为正的时间占比
- **T 统计量**：IC 均值 / (IC 标准差 / sqrt(n))，检验因子是否显著

### compute_ic_ir() API

```python
def compute_ic_ir(
    self,
    df: pd.DataFrame,              # 包含因子值和价格的数据
    factor_cols: List[str],         # 因子列名列表
    holding_periods: Optional[List[int]] = None,  # 持有期，默认 [1, 5, 20]
    date_col: str = "date",         # 日期列名
    code_col: str = "code",         # 股票代码列名
    price_col: str = "close",       # 价格列名
    mode: str = "backtest",         # 运行模式: "backtest" / "live"
    test_size: float = 0.0,         # 测试集比例 (0~1)
) -> Dict[str, Dict[int, FactorICResult]]:
```

**返回值结构**: `Dict[因子名, Dict[持有期, FactorICResult]]`

### FactorICResult 字段

```python
@dataclass
class FactorICResult:
    factor_name: str           # 因子名称
    ic_mean: float             # IC 均值
    ic_std: float              # IC 标准差
    icir: float                # ICIR = ic_mean / ic_std
    ic_positive_ratio: float   # IC > 0 的比例
    ic_t_stat: float           # T 统计量
    n_periods: int             # 观测期数
    test_ic_mean: float = 0.0  # 测试集 IC 均值（启用 temporal_split 时）
    test_icir: float = 0.0     # 测试集 ICIR（启用 temporal_split 时）
```

### 持有期

默认持有期为 `[1, 5, 20]` 天，分别对应日频、周频和月频的预测能力评估。系统对每个持有期独立计算 IC/IR，并选择绝对 ICIR 最优的持有期作为最佳结果。

### Temporal Split（训练/测试分割）

当 `test_size > 0` 时，`compute_ic_ir` 会调用 `temporal_split()` 按时间顺序将数据分为训练集和测试集：

```python
def temporal_split(self, df: pd.DataFrame, test_size: float = 0.3):
    # 按日期排序，前 (1 - test_size) 为训练集，后 test_size 为测试集
```

当训练集与测试集的 IC 均值差异超过 0.1 时，系统会发出过拟合警告。

### 代码示例

```python
from uniquant.brain.factors.analyzer import FactorAnalyzer

analyzer = FactorAnalyzer()

# 基本 IC/IR 分析
results = analyzer.compute_ic_ir(
    df,
    factor_cols=["momentum_20d", "volatility_20d", "rsi_14"],
    holding_periods=[1, 5, 20],
    mode="backtest",
)

# 启用 temporal split 检测过拟合
results = analyzer.compute_ic_ir(
    df,
    factor_cols=["momentum_20d", "volatility_20d"],
    test_size=0.3,   # 30% 作为测试集
    mode="backtest",
)

# 查看测试集表现
for name, period_results in results.items():
    for period, r in period_results.items():
        print(f"{name} @ {period}d: train IC={r.ic_mean:.4f}, "
              f"test IC={r.test_ic_mean:.4f}")

# 获取表现最好的因子
top_factors = analyzer.get_top_factors(metric="icir", top_n=5)
for name, icir in top_factors:
    print(f"{name}: ICIR={icir:.4f}")

# 计算因子相关性矩阵
corr = analyzer.compute_factor_correlation(
    df, factor_cols=["momentum_20d", "volatility_20d", "rsi_14"],
    method="spearman",
)
print(corr)

# 生成分析报告
report = analyzer.generate_report(results)
print(report["summary"])
```

---

## 因子合成 (FactorComposer)

`FactorComposer` 负责将多个因子合成为一个综合评分（composite_score），支持 Z-score 标准化、对称正交化和多种加权方式。

### 核心流程

```
计算所有因子 -> Z-score 横截面标准化 -> 对称正交化（可选） -> 加权合成 composite_score
```

### 构造参数

```python
class FactorComposer:
    def __init__(self, orthogonalize: bool = True):
        # orthogonalize: 是否启用对称正交化（消除因子间共线性）
```

### 标准化 (Z-score)

因子值按**横截面**（同一日期内所有股票）做 Z-score 标准化：

```
z = (x - mean) / std
```

- 当标准差为 0 时，返回 NaN 后填充为 0
- 无穷值替换为 NaN 后填充为 0
- 若数据无日期列，退化为全局标准化

### 加权方式

系统按以下优先级确定因子权重：

1. **IC 加权 (IC-weighted)**：当传入 `ic_results` 时，使用各因子的 ICIR 值作为权重
2. **注册表权重 (Registry)**：当无 IC 结果时，使用 FactorRegistry 中的 `default_weight`
3. **等权 (Equal)**：当因子未注册时，默认权重为 1.0

### 正交化

对称正交化 (Symmetric Orthogonalization) 使用特征值分解消除因子间共线性：

```
F_orth = F @ (F^T @ F)^{-1/2}
```

- 保持因子的对称性和信息含量
- 当因子数不足 2 或特征值分解失败时，自动回退到原始因子

### compose_scores() API

```python
def compose_scores(
    self,
    df: pd.DataFrame,                             # 原始数据
    ic_weights: Optional[Dict[str, float]] = None, # IC 权重（可选）
    factor_cols: Optional[List[str]] = None,       # 指定因子列（可选）
    date_col: str = "date",
) -> pd.DataFrame:
    # 返回包含各标准化因子列和 composite_score 列的 DataFrame
```

### process() API

```python
def process(
    self,
    df: pd.DataFrame,
    factor_cols: Optional[List[str]] = None,
    ic_results: Optional[Dict[str, Any]] = None,
    date_col: str = "date",
    expanding: bool = False,                        # 展开窗口模式（walk-forward）
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    # 返回 (带 composite_score 的 DataFrame, 最终权重字典)
```

当 `expanding=True` 时，系统对每个日期使用展开窗口（从历史起点到当前日期）重新计算 IC/IR 并更新权重，实现简易的 walk-forward 合成。

### 代码示例

```python
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer

# 初始化
composer = FactorComposer(orthogonalize=True)
analyzer = FactorAnalyzer()

# 方式一：直接合成（使用注册表默认权重）
scored_df = composer.compose_scores(df)
print(scored_df[["composite_score"]].head())

# 方式二：先分析 IC/IR，再用 IC 权重合成
ic_results = analyzer.compute_ic_ir(
    df, factor_cols=["momentum_20d", "volatility_20d", "rsi_14"],
    mode="backtest",
)
# 提取权重
ic_weights = {}
for name, period_results in ic_results.items():
    best_result = max(period_results.values(), key=lambda r: abs(r.icir))
    ic_weights[name] = best_result.icir

scored_df = composer.compose_scores(df, ic_weights=ic_weights)

# 方式三：使用 process() 一步完成（含展开窗口）
result_df, weights = composer.process(
    df,
    factor_cols=["momentum_20d", "volatility_20d"],
    expanding=True,   # 展开窗口 walk-forward
)
print("最终权重:", weights)
print(result_df[["composite_score"]].describe())
```

---

## Walk-Forward 因子管道

`WalkForwardFactorPipeline` 实现严格的样本外（Out-of-Sample）滚动验证，确保因子权重始终基于历史数据计算，测试窗口中不使用任何未来信息。

### 工作原理

```
|<-- 训练窗口 (504天) -->|<-- 测试窗口 (63天) -->|
                          |<-- 训练窗口 (504天) -->|<-- 测试窗口 (63天) -->|
                                                    |<-- ...
```

每次滚动：
1. 在训练窗口内计算所有因子的 IC/IR
2. 根据 ICIR 绝对值确定各因子权重（归一化到总和为 1）
3. 将训练窗口的权重应用到测试窗口进行评分
4. 向前滑动一个 test_window 步长，重复上述过程

### 构造参数

```python
class WalkForwardFactorPipeline:
    def __init__(
        self,
        factor_analyzer: Optional[FactorAnalyzer] = None,
        factor_composer: Optional[FactorComposer] = None,
        train_window: int = 504,      # 训练窗口天数（约 2 年交易日）
        test_window: int = 63,        # 测试窗口天数（约 1 季度交易日）
        min_train_days: int = 252,    # 最小训练数据量（约 1 年交易日）
        weight_method: str = "rank_icir",  # 权重计算方法
    ):
```

### run() API

```python
def run(
    self,
    df: pd.DataFrame,
    factor_cols: Optional[List[str]] = None,
    date_col: str = "date",
    code_col: str = "code",
    price_col: str = "close",
) -> WalkForwardResult:
```

### WalkForwardResult 字段

```python
@dataclass
class WalkForwardResult:
    windows: List[WalkForwardWindowResult]   # 每个滚动窗口的详细结果
    final_weights: Dict[str, float]          # 最后一个窗口的权重
    oos_ic_mean: float                       # 所有窗口样本外 IC 均值
    oos_ic_std: float                        # 所有窗口样本外 IC 标准差
    oos_icir: float                          # 样本外 ICIR = oos_ic_mean / oos_ic_std
    weight_stability: Dict[str, float]       # 各因子权重在窗口间的标准差（越小越稳定）
```

### WalkForwardWindowResult 字段

```python
@dataclass
class WalkForwardWindowResult:
    train_start: pd.Timestamp     # 训练窗口起始日期
    train_end: pd.Timestamp       # 训练窗口结束日期
    test_start: pd.Timestamp      # 测试窗口起始日期
    test_end: pd.Timestamp        # 测试窗口结束日期
    ic_mean: Dict[str, float]     # 各因子训练集 IC 均值
    icir: Dict[str, float]        # 各因子训练集 ICIR
    weights: Dict[str, float]     # 本窗口计算的因子权重
    n_train_stocks: int           # 训练集股票数
    n_test_stocks: int            # 测试集股票数
```

### 代码示例

```python
from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline

pipeline = WalkForwardFactorPipeline(
    train_window=504,    # 2 年训练
    test_window=63,      # 1 季度测试
    min_train_days=252,  # 至少 1 年数据
)

# 运行 walk-forward 验证
result = pipeline.run(
    df,
    factor_cols=["momentum_20d", "volatility_20d", "ma_ratio_5_20", "rsi_14"],
    date_col="date",
    code_col="code",
    price_col="close",
)

# 查看样本外整体表现
print(f"OOS IC Mean: {result.oos_ic_mean:.4f}")
print(f"OOS ICIR:    {result.oos_icir:.4f}")
print(f"OOS IC Std:  {result.oos_ic_std:.4f}")

# 查看最终权重
print("最终因子权重:")
for name, weight in result.final_weights.items():
    print(f"  {name}: {weight:.4f}")

# 查看权重稳定性（标准差越小越稳定）
print("权重稳定性:")
for name, std in result.weight_stability.items():
    print(f"  {name}: std={std:.4f}")

# 遍历每个窗口的详细结果
for i, w in enumerate(result.windows):
    print(f"Window {i}: {w.train_start.date()} ~ {w.test_end.date()}, "
          f"stocks: {w.n_train_stocks}/{w.n_test_stocks}")
```

---

## 因子评估指标

以下是因子评估中的核心指标及其判断标准：

| 指标 | 计算方式 | 优秀标准 | 说明 |
|------|----------|----------|------|
| IC Mean | 各期 Rank IC 的均值 | \|IC\| > 0.03 | 因子预测方向和强度 |
| IC IR (ICIR) | IC Mean / IC Std | \|ICIR\| > 0.5 | 因子预测稳定性 |
| IC > 0 比例 | IC 为正的期数占比 | > 55% | 因子方向正确的概率 |
| T 统计量 | IC Mean / (IC Std / sqrt(n)) | \|T\| > 2.0 | 因子显著性检验 |
| Weight Stability | 权重在 walk-forward 窗口间的标准差 | < 0.1 | 因子权重的时间稳定性 |
| OOS IC | 样本外（测试集）IC 均值 | 与训练集 IC 差距 < 0.1 | 防过拟合的关键指标 |

**解读要点：**

- ICIR 是最核心的指标，兼顾了预测力和稳定性
- IC > 0 比例反映因子在大多数时间是否有效
- T 统计量 > 2.0 意味着在 95% 置信水平下因子显著
- OOS IC 与训练集 IC 差异过大（> 0.1）时，系统会发出过拟合警告
- Weight Stability 低的因子权重分配更可靠

---

## 防前瞻偏差

UniQuant 因子系统在多个层面防止前瞻偏差（Lookahead Bias）：

### 1. mode="live" 运行模式守卫

`FactorAnalyzer` 的 `_compute_forward_returns()` 和 `compute_ic_ir()` 方法都检查 `mode` 参数：

```python
if mode == "live":
    raise ValueError(
        "Lookahead bias detected: _compute_forward_returns uses negative shift "
        "which introduces future data. This method is NOT safe for live trading."
    )
```

当 mode 为 `"live"` 时，任何使用未来收益率的操作都会直接抛出 `ValueError`，从根本上阻止实盘中的前瞻偏差。

### 2. 未来时间戳检测

计算前瞻收益率时，系统会检查数据中是否存在超过当前时间的日期：

```python
if "date" in df.columns:
    max_date = pd.to_datetime(df["date"]).max()
    if max_date > pd.Timestamp.now():
        raise ValueError(f"Future timestamp detected in data: {max_date}")
```

### 3. Temporal Split 训练/测试分割

`temporal_split()` 按时间顺序严格切分数据，训练集在前、测试集在后，避免信息泄露：

```python
def temporal_split(self, df, test_size=0.3):
    # 按日期排序，前 70% 训练，后 30% 测试
    # 绝不随机打乱时间序列
```

训练集 IC 与测试集 IC 差异超过 0.1 时自动输出过拟合警告。

### 4. Walk-Forward 窗口隔离

`WalkForwardFactorPipeline` 通过滚动窗口实现最严格的前瞻隔离：

- 训练窗口和测试窗口在时间上严格不重叠
- 权重仅在训练窗口内计算，测试窗口只使用训练得到的权重
- 每次前进一个 `test_window` 步长，全程不接触未来数据

```
[训练 504天] [测试 63天]
              [训练 504天] [测试 63天]
                            [训练 504天] [测试 63天]
```

### 5. 策略层 mode 守卫

内置策略函数（`trade_ma`、`trade_wyckoff`、`trade_str_reversal`）同样检查 `mode` 参数，在 `mode="live"` 时拒绝执行使用未来数据的回测逻辑。
