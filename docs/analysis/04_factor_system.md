# Stage 4 — 因子系统深度分析

> **日期**: 2026-06-29 | **状态**: ✅ 完成
> **范围**: `brain/factors/` (8 文件), `shared/factor_governance.py`, `shared/config_models.py`, `shared/config_loader.py`
> **依赖**: `config.yaml` → `refactoring.feature_flags.factor_gate`

---

## 1. 总览

### 因子系统架构

```
external scripts (full_a_stock_analysis.py etc.)
        │
        ▼
  custom_factors.py        ← register_all() → 14 factors
        │
  ┌─────┴────────┐
  ▼              ▼
FactorRegistry  FactorAnalyzer  ← IC/IR/IC>0 ratio
(singleton)            │
  │                    ▼
  │             FactorComposer  ← Z-score + orthogonal + IC weighting
  │                    │
  │                    ▼
  │             WalkForwardPipeline  ← train/test separation
  │
  └─── check_access() → admission gate (WARN/BLOCK/OFF)
           │
           ▼
   shared/factor_governance.py  (deprecated → re-exports from brain/)
   FactorAdmissionGate          (registration-time checks)
```

### 文件清单

| 文件 | LOC | 职责 |
|------|-----|------|
| `brain/factors/registry.py` | 184 | 全局单例注册中心, 线程安全, 准入检查 |
| `brain/factors/analyzer.py` | 528 | IC/IR 计算, Rank IC, 前视偏差检测, 因子相关性 |
| `brain/factors/composer.py` | 401 | Z-score 标准化, 对称正交化, IC 加权合成, 降级处理 |
| `brain/factors/custom_factors.py` | 311 | 14 个技术/逻辑因子实现 + `register_all()` |
| `brain/factors/financial_bridge.py` | 421 | 中文财务字段→标准因子映射, PE_TTM/PB 计算 |
| `brain/factors/neutralizer.py` | 40 | MAD 缩尾 + 行业/市值回归中性化 |
| `brain/factors/industry_provider.py` | 20 | akshare 行业分类哑变量 |
| `brain/factors/walk_forward_pipeline.py` | 246 | Walk-Forward 因子扫描, 训练/测试严格分离 |
| `shared/factor_governance.py` | 170 | 已弃用, 仅 re-export + FactorAdmissionGate |

### 测试文件

| 测试 | 函数数 | 覆盖 |
|------|--------|------|
| `tests/test_factor_registry.py` | 10 | 注册/覆盖/启用/禁用/准入检查/WARN/BLOCK |
| `tests/test_factor_analyzer.py` | 12 | IC/ICIR/相关性/前视偏差/持有期/边缘情况 |
| `tests/test_factor_composer.py` | 9 | Z-score/正交化/IC加权/降级/缺失因子/坏因子 |
| `tests/test_factor_div_zero_defense.py` | 11 | 零除防御/空数据/单值/NaN |
| `tests/shared/test_factor_manifest.py` | 4 | 因子清单数据类 |
| `tests/shared/test_factor_admission_gate.py` | 13 | 3 种模式/3 项检查/命名/文档/参数 |
| **合计** | **59** | — |

---

## 2. FactorRegistry 注册中心 (`registry.py`)

### 核心设计

- **单例模式**: `__new__` 确保全局唯一实例
- **线程安全**: `threading.Lock` 保护所有读写操作
- **延迟加载**: `_ensure_loaded()` 在首次查询时触发，与 `register_all()` 在 import 时调用的默认注册配合

### 公共 API

```python
FactorRegistry.register(name, compute_func, category, default_weight, description)
FactorRegistry.get_all()          → List[FactorInfo]
FactorRegistry.get_enabled()     → List[FactorInfo]   # 触发 check_access
FactorRegistry.get_factor(name)  → Optional[FactorInfo]  # 触发 check_access
FactorRegistry.has(name)         → bool
FactorRegistry.enable(name) / disable(name)
FactorRegistry.list_factors()    → Dict[str, str]  # name → description
FactorRegistry.check_access(name) → bool  # WARN/BLOCK 模式拦截
FactorRegistry.set_mode(mode)    → FactorAccessLevel
```

### 准入检查机制

```python
check_access(name):
    if name in _factors: return True
    if _mode == BLOCK: raise ValueError(f"未注册因子被拦截: {name}")
    if _mode == WARN: logger.warning("未注册因子访问: %s (mode=warn)", name)
    return True
```

三模式:
- **OFF** (`config: "off"`): 不检查, 全部放行
- **WARN** (`config: "warn"`): 记录警告但放行 (默认)
- **BLOCK** (`config: "block"`): 拦截未注册因子 → `ValueError`

### 配置集成

```python
# register() 内部读取 config.yaml:
cfg.get(f"factors.{name}")  # 支持 enabled/weight/category 覆盖
# 加载失败时主动 raise (不静默回退)
```

---

## 3. Custom Factors (`custom_factors.py`)

### 14 个注册因子

| # | 因子名 | 类别 | 默认权重 | 描述 |
|---|--------|------|---------|------|
| 1 | `momentum_20d` | technical | 1.0 | 20日动量 (收益率) |
| 2 | `momentum_60d` | technical | 0.9 | 60日动量 |
| 3 | `volatility_20d` | technical | 0.8 | 20日波动率 (年化) |
| 4 | `volatility_60d` | technical | 0.7 | 60日波动率 |
| 5 | `ma_ratio_5_20` | technical | 0.85 | 5/20日均线比率 |
| 6 | `ma_ratio_10_60` | technical | 0.75 | 10/60日均线比率 |
| 7 | `volume_ratio_5_20` | technical | 0.6 | 5/20日成交量比率 |
| 8 | `rsi_14` | technical | 0.8 | 14日 RSI |
| 9 | `price_position_20d` | technical | 0.7 | 20日价格位置 (0-1) |
| 10 | `turnover_momentum_20d` | technical | 0.85 | 20日换手率动量 |
| 11 | `illiq_20d` | custom | 1.0 | Amihud 非流动性 |
| 12 | `pv_divergence_20d` | custom | 1.0 | 量价背离 |
| 13 | `cs_momentum_20d` | custom | 1.0 | 横截面动量 |
| 14 | `idiosyncratic_vol_20d` | custom | 1.0 | 特质波动率 (IVOL) |

### 注册时机

```python
# __init__.py:
from . import custom_factors  # 导入即触发 register_all()
```

通过 `from . import custom_factors` 在包加载时自动注册。

---

## 4. FactorAnalyzer (`analyzer.py`)

### 分析模式

```python
class AnalysisMode(Enum):
    BACKTEST = auto()  # 允许负 shift (未来数据, 仅离线)
    LIVE = auto()      # 禁止未来数据泄漏, 抛出 ValueError
```

- `compute_forward_returns()` 在 `mode="live"` 时直接抛出 `ValueError` 防止前视偏差
- `compute_ic_ir()` 增加半衰期加权支持 (exponential weights)

### 核心方法

| 方法 | 用途 | 复杂度 |
|------|------|--------|
| `compute_rank_ic(factor, returns)` | Spearman 秩相关 → IC | O(n) |
| `compute_ic_ir(df, factor_cols, ...)` | 多持有期 IC/IR/IC>0 比例 | O(factors × periods × days) |
| `compute_factor_correlation(factors)` | 因子相关性矩阵 | O(f² × n) |

### Look-ahead 检测

`check_lookahead_leakage()`: 通过对未来价格进行扰动 (1.5-3.0x)，验证因子值在扰动前后不变。若因子值变化则抛出 `LookaheadBiasError`。

### IC/IR 算法

```python
# 向量化: 使用 groupby 替代内层日期循环
df[fwd_col] = df.groupby(code_col)[price_col].shift(-period) / df[price_col] - 1
# 每日 IC → IC 序列 → IC_mean / IC_std → ICIR
ic_series = df.groupby(date_col).apply(calc_daily_ic)
ic_mean = np.mean(ic_series)  # 或半衰期加权
```

---

## 5. FactorComposer (`composer.py`)

### 合成流水线

```
compose(df, factor_names)
  │
  ├─ 1. FactorRegistry.get_enabled() → 验证因子已注册
  │
  ├─ 2. 逐因子计算 → df[factor_name]
  │      └─ 对失败因子: 记录到 diagnostics["failed_factors"]
  │
  ├─ 3. Z-score 标准化 (横截面)
  │
  ├─ 4. 对称正交化 (可选, default=True)
  │      └─ scipy.linalg 对称正交化
  │
  ├─ 5. IC 加权合成
  │      └─ weight = ICIR / sum(ICIR)
  │
  └─ 6. 诊断输出
         ├─ composite_status: OK / DEGRADED / UNAVAILABLE
         └─ composite_usable: bool
```

### 降级策略

- 缺失因子 → `missing_requested_factors`
- 计算失败的因子 → `failed_factors`
- 正交化失败 → `orthogonalization_failed`
- 只要有 `used_factors` 就标记为 `DEGRADED` 但 `composite_usable=True`
- 零可用因子 → `UNAVAILABLE`, `composite_usable=False`

---

## 6. WalkForwardPipeline (`walk_forward_pipeline.py`)

### 设计

```python
WalkForwardFactorPipeline(
    train_window=504,   # ~2年
    test_window=63,     # ~3月
    min_train_days=252, # 最小训练天数
    weight_method="rank_icir",  # 权重方法
)
```

### 流水线

```
run(df)
  │
  ├─ 滚动窗口: 每 test_window 天前进一次
  │
  ├─ 训练窗口: IC/IR 计算 → 因子权重
  │
  ├─ 测试窗口: 用训练权重合成复合因子
  │
  └─ 输出 WalkForwardResult
       ├─ windows: List[WalkForwardWindowResult]
       ├─ final_weights: Dict[str, float]
       ├─ oos_ic_mean / oos_ic_std / oos_icir
       └─ weight_stability: Dict[str, float]
```

### 严格泄漏控制

- 训练窗口 `train_window` 天 → 计算 IC/IR → 确定权重
- 测试窗口 `test_window` 天 → 用训练权重打分
- 滚动前进，永不使用未来数据

---

## 7. 财务因子桥接 (`financial_bridge.py`)

### 中文 → 英文字段映射

26 个字段映射 (eps, roe, bps, cash, revenue, net_profit 等)，从中文 Parquet 财务数据转换为标准英文因子名。

### 计算因子

- `PE_TTM`: 价格 / 近四季每股收益
- `PB`: 价格 / 每股净资产

### 别名解析

```python
FINANCIAL_FIELD_ALIASES = {
    "total_assets": ["总资产", "资产总计"],
    "equity": ["股东权益", "所有者权益（或股东权益）合计", ...],
    ...
}
```

---

## 8. Neutralizer (`neutralizer.py`)

### 两步中性化

```
neutralize(factor, industry_dummies, log_market_cap):
    1. MAD_Winsorize(factor, n=5)  # 极端值处理
    2. OLS 回归: y ~ 1 + log_market_cap + industries
    3. residual = y - X @ β  # 中性化后残差
```

### 边界保护

- `len(factor) < 10` → 直接返回
- `valid.sum() < 10` → 直接返回 (有效样本不足)

---

## 9. Industry Provider (`industry_provider.py`)

```python
get_industry_dummies() → pd.DataFrame  # akshare 行业分类 → one-hot
get_log_market_cap(symbols, price_df, shares_outstanding) → pd.Series
```

全局单例缓存 `_CACHE`，首次调用后不再请求 akshare。

---

## 10. shared/factor_governance.py (已弃用)

### 状态 (G-2 已关闭)

```
2025-06: 两个 FactorRegistry (shared/ 0 用户 vs brain/ 16 导入)
2026-06-12: shared/ 添加 DeprecationWarning, 全部 re-export from brain/
2026-06-29: 已验证 — 导入时输出 DeprecationWarning
```

### 残留内容

- `FactorManifest`: 因子注册前使用的清单数据类 (8 字段)
- `CheckResult` / `AdmissionResult`: 检查结果数据类
- `FactorAdmissionGate`: 注册前合规性检查 (3 项: 命名/文档/参数)
  - 未被 `FactorRegistry.register()` 实际调用 — 是独立的"预注册"检查
- `global_factor_registry`: 指向 `brain.factors.registry.FactorRegistry` 的引用

**注意**: `FactorAdmissionGate` (shared/) 和 `FactorRegistry.check_access()` (brain/) 是两个独立的准入检查机制。前者是注册前检查，后者是运行时访问检查。两者目前没有集成。

---

## 11. 关键观察

### 架构风险

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R4-1 | **注册前检查未集成**: `FactorAdmissionGate` 和 `FactorRegistry.register()` 独立运行，gate 的检查结果不影响注册 | `shared/factor_governance.py:60`, `brain/factors/registry.py:46` | Gate 形同虚设 |
| R4-2 | **因子注册时序依赖**: `custom_factors.register_all()` 在 import 时调用。若在导入前调用 `FactorRegistry` 方法，因子不可用 | `brain/factors/__init__.py` | 竞态, `_ensure_loaded()` 只设置标志不触发注册 |
| R4-3 | **财务桥接的数据来源不明确**: `FinancialFactorBridge` 依赖外部 Parquet 文件，无配置化路径 | `financial_bridge.py` | 部署时需携带数据文件 |
| R4-4 | **industry_provider 硬编码 akshare**: `get_industry_dummies()` 直接调用 akshare，无 mock/fallback | `industry_provider.py:12` | 测试困难, AKShare 网络失败=服务失败 |
| R4-5 | **WalkForwardPipeline 未集成到服务容器**: `walk_forward_pipeline.py` 是独立类，未被 `ServiceContainer` 管理 | `walk_forward_pipeline.py` | 离线研究专用, 非运行时功能 |

### 设计亮点

| # | 亮点 | 位置 |
|---|------|------|
| S4-1 | **CASIC 四大逻辑因子**: ILLIQ / PV Divergence / CS Momentum / Idiosyncratic Vol — 基于学术文献, 可解释性强 | `custom_factors.py:281-302` |
| S4-2 | **Look-ahead 检测**: `check_lookahead_leakage()` 通过未来价格扰动验证因子无前视偏差 | `analyzer.py:26-85` |
| S4-3 | **LIVE/BACKTEST 双模式**: 因子分析器在 LIVE 模式下完全禁止前视函数 | `analyzer.py:88` |
| S4-4 | **Composer 降级诊断**: 详细诊断输出 (缺失/失败/正交化) 而非静默回退 | `composer.py:26-50` |
| S4-5 | **Walk-Forward 严格分离**: 滚动训练/测试窗口, OOS IC/IR 评估, 权重稳定性 | `walk_forward_pipeline.py` |
| S4-6 | **配置驱动因子开关**: `config.yaml` 支持 `factors.{name}.enabled` 运行时禁用 | `registry.py:58-64` |

### 使用路径

| 路径 | 入口 | 因子数量 | 用途 |
|------|------|---------|------|
| 扫描分析 | `full_a_stock_analysis.py` 等 | 14+ | 批量全市场因子计算 |
| 回测 | `FactorComposer` via `walk_forward_pipeline` | 按需 | 因子合成与评估 |
| 运行时 | `DecisionBrain._calculate_score()` | 0 | 只使用 alpha_score (AlphaDecoupler), 未使用 FactorRegistry |
| 财务 | `FinancialFactorBridge` | 26+财务 | PE_TTM/PB 等基本面因子 |

---

## 12. 建议

### P1
1. **R4-1 (Gate 未集成)**: 在 `FactorRegistry.register()` 中调用 `FactorAdmissionGate.check_admission()`, 或废弃 gate

### P2
2. **R4-4 (akshare 硬编码)**: 为 `industry_provider` 添加缓存回退和 mock 接口
3. **R4-2 (注册时序)**: `register_all()` 改为显式调用而非 import 副作用, 或在 `FactorRegistry` 首次使用时自动触发

### P3
4. **R4-3 (财务数据源)**: 配置化财务 Parquet 路径
5. **R4-5 (WalkForward 未集成)**: 保持独立, 属于离线研究工具
6. **运行时因子集成**: 将 `FactorRegistry` 因子接入 `AnalysisService` 或 `ResearchPipeline`, 使 DecisionBrain 可消费因子评分

---

## 13. 验证清单

- [x] 读取 `brain/factors/registry.py` (单例, 线程安全, 准入检查)
- [x] 读取 `brain/factors/custom_factors.py` (14 因子 + register_all)
- [x] 读取 `brain/factors/analyzer.py` (IC/IR, 前视检测, LIVE/BACKTEST 模式)
- [x] 读取 `brain/factors/composer.py` (Z-score, 正交化, IC 加权, 降级)
- [x] 读取 `brain/factors/neutralizer.py` (MAD + OLS 中性化)
- [x] 读取 `brain/factors/financial_bridge.py` (26 财务字段映射, PE_TTM/PB)
- [x] 读取 `brain/factors/industry_provider.py` (akshare → one-hot)
- [x] 读取 `brain/factors/walk_forward_pipeline.py` (滚动窗口, 严格泄漏控制)
- [x] 读取 `brain/factors/__init__.py` (导入即注册)
- [x] 读取 `shared/factor_governance.py` (弃用状态, re-export, G-2 关闭)
- [x] 读取 `shared/config_models.py` (factor_gate 配置)
- [x] 检查测试覆盖 (6 文件, 59 函数)
- [x] 检查 config.yaml 的 factor_gate 集成
- [x] 检查 G-2 关闭状态
