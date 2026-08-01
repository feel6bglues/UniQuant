> **⚠️ 状态: 历史参考 (2026-07-17 验证)**
>
> 本文档列出的 **P0.1~P3.5 共 11 项修复已全部在代码中实施**。
> 保留作为架构设计参考, 但"待修复"声明已过时。
> 当前验证结果详见 `docs/remediation/VERIFIED_WORKLIST_20260717.md`。

# LPPL × Wyckoff 引擎综合修复计划

> 基于 100 只 A 股实证数据（2812 次 LPPL 拟合、100 次 Wyckoff 全分析）
> 经三角色评估后编制的可执行修复方案
> 每项均标注：影响范围、代码定位、修改量级、回归风险

---

## P0 — 本周必须修复（核心 Bug）

### P0.1 统一 R² 计算口径 — calculator.py 缺失 R² 输出 + 两路径优化器不一致

**问题**：代码核查发现两个独立问题：

1. `calculator.py` 的 `fit()` 方法输出 `confidence`（三段加权：tc 距离 + RMSE + 数据长度）但**没有 `r_squared`**。系统服务层 `lppl_analysis_engine.py:69` 调用链 `run_lppl_analysis()` → `LPPLEngine.detect_bubble()` → `LPPLCalculator.fit()`，读取 `result.get("risk_level")` 和 `result.get("confidence")` 但**无法读取 R²**。

2. 验证脚本发现的 R² 差异（均值 0.83）的真实根因：`calculator.py` 使用 **DE 优化器**（`fit()` 内部），而 `engine.py` 的两个 `fit_single_window_*()` 使用 L-BFGS-B 或 DE。不同的优化路径 → 不同的参数 → 不同的 R²。所以"R² 不一致"实质上是**优化器不一致导致的拟合结果不一致**。

核查确认 `engine.py` 的两个 `fit_single_window*()` 函数的 R² 计算公式一致（都是 `1 - ss_res/ss_tot`，差异仅为 `log_mean` vs `np.mean()` 的等价实现），**不是 R² 公式的 bug**。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `calculator.py` | `fit()` 返回值 `~line 563` | 有 `confidence`, **无 `r_squared`** |
| `calculator.py` | `_calculate_confidence():385-424` | 三段加权法（tc 距离 + RMSE + 数据长度） |
| `calculator.py` | `fit_single_window():273-359` | 返回 `rmse` 和 `params`，无 R² |
| `calculator.py` | `fit()` `~line 500` | 内部使用 `differential_evolution`（DE） |
| `engine.py` | `fit_single_window():153-251` | DE 优化器 |
| `engine.py` | `fit_single_window_lbfgsb():253-364` | L-BFGS-B 优化器 |
| `engine.py` | R² 计算 `:224-226` 和 `:338-340` | 标准 `1 - ss_res/ss_tot`，公式正确 |
| `interfaces.py` | `LPPLOutput`:303-325 | 无 `r_squared` 字段 |

**修复方案**（2 处变更）：

**变更 1 — calculator.py `fit()` 方法末尾添加 R² 输出**：
```python
# calculator.py ~line 557
# 注意：这里使用已求解的线性参数重新计算 fitted curve
t_arr = np.arange(len(df))
tau = tc - t_arr
f = tau ** m
g = f * np.cos(w * np.log(tau))
h = f * np.sin(w * np.log(tau))
fitted_log = a + b * f + c1 * g + c2 * h  # 或使用 self.lppl_func(t, tc, m, w, a, b, c, phi)

ss_res = np.sum((log_prices - fitted_log) ** 2)
ss_tot = np.sum((log_prices - np.mean(log_prices)) ** 2)
r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

return {
    # ... 原有字段保持不变
    "r_squared": round(r_squared, 4),  # 新增
    "rmse": float(np.sqrt(result.fun / len(df))) if result.fun > 0 else 0.0,  # 新增
    # ...
}
```

**变更 2 — `LPPLOutput` dataclass 增加 `r_squared` 字段**：
```python
# interfaces.py:303-325
@dataclass
class LPPLOutput:
    risk_level: str = "Safe"
    confidence: float = 0.0
    days_to_tc: Optional[float] = None
    price: float = 0.0
    r_squared: float = 0.0  # 新增：模型拟合优度
```

同时在 `to_dict()` 和 `from_dict()` 中同步。

**影响范围**：`LPPLOutput` 增加字段需要所有创建和使用该 dataclass 的地方同步。核查发现直接构造 `LPPLOutput` 的地方：
- `lppl_analysis_engine.py:71-76`（主路径）
- `lppl_analysis_engine.py:117-121`（fallback 路径）

两处均未传入 `r_squared`，新增字段的默认值 `0.0` 是安全的。

**修改量级**：+20 行（calculator.py）+5 行（interfaces.py）+0 行（调用方无需修改）
**回归风险**：低（新增字段，默认值安全）

---

### P0.2 L-BFGS-B 升为主优化器 — DE 降为秋季模式

**问题**：DE 优化器在 1,406 次尝试中成功率为 0%。L-BFGS-B + 多点启动在 2,812 次尝试中成功率 100%。DE 的 `best1bin` 策略在 3 维非线性参数空间中需要更大的种群和更多代数才能收敛。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `engine.py` | `fit_single_window():153-251` | 默认 DE 优化器 |
| `engine.py` | `LPPLConfig`:118 | `optimizer: str = "de"` |
| `engine.py` | `scan_single_date()`:427-440 | 按 `config.optimizer` 分支 |
| `engine.py` | `process_single_day_ensemble()`:495-516 | 同 |

**修复方案**（1 处变更 + 1 处新增）：

**变更 — LPPLConfig 默认值**：
```python
# engine.py ~line 118
@dataclass
class LPPLConfig:
    optimizer: str = "lbfgsb"  # 原 "de"
    maxiter: int = 30           # L-BFGS-B 50代/初始点 × 10点 = 500次eval，充足
    popsize: int = 5
```

**新增 — DE 保留为秋季校准模式**：在 `scan_single_date()` 中添加：
```python
# engine.py ~line 427
if config.optimizer == "de":
    res = fit_single_window(subset, window_size, config)
elif config.optimizer == "lbfgsb":
    res = fit_single_window_lbfgsb(subset, window_size, config)
else:  # "hybrid" — 先用 L-BFGS-B，R²>0.6 时用 DE 验证
    res = fit_single_window_lbfgsb(subset, window_size, config)
    if res and res.get("r_squared", 0) > 0.6:
        de_res = fit_single_window(subset, window_size, config)
        if de_res:
            res["de_validated"] = True
            res["de_consistency"] = abs(res["r_squared"] - de_res["r_squared"])
```

**影响范围**：所有调用 `LPPLConfig()` 的地方。核查发现 `multifit.py:103-116` 已硬编码 `optimizer="lbfgsb"`，`engine.py` `scan_all_windows()` 的 `_process_window()` 使用 `calculator.fit_single_window()`（内部 DE），需确认是否也受影响。

**修改量级**：~20 行
**回归风险**：中（切换默认优化器可能影响基线测试的输出，需更新 golden baseline）

---

## P1 — 本月完成（算法改进）

### P1.1 Wyckoff Step1 Phase 分类阈值放宽

**问题**：43% 的股票被归类为 UNKNOWN，仅 6% 为 ACCUMULATION。分类器阈值过于严格，导致引擎在 2022-2026 年的市场几乎不产生任何做多信号。15+ 条分支的阈值在历史回测中调整过，但未在当前市场验证。

**代码定位**：
| 文件 | 行 | 现状 | 问题 |
|---|---|---|---|
| `engine.py` | `_step1_phase_determine():310-317` | `prior_trend_pct < -0.05` → ACCUMULATION | 前趋势 -5% 门槛过高 |
| `engine.py` | `_step1_phase_determine():346-348` | `short_trend_pct >= 0.015` → MARKUP | 需配合 `relative_position >= 0.70` |
| `engine.py` | `_step1_phase_determine():381-390` | 非 TR 下的 ACCUMULATION | 5 个 AND 条件过于严格 |

**修复方案**（每处 1-2 个数值变更）：

**变更 1 — 前趋势门槛**：
```python
# engine.py:315 原 prior_trend_pct < -0.05
# 改为：
if prior_trend_pct < -0.03:  # -5% → -3%
    phase = WyckoffPhase.ACCUMULATION
```

**变更 2 — 非 TR 下 ACCUMULATION 条件**：
```python
# engine.py:381-390 原5个AND条件
# 改为4个（移除 relative_position 要求）：
elif (short_trend_pct <= -0.02
      and current_price < ma20
      and ma5 <= ma20
      and (rule0.bc_found or rule0.sc_found)):
    phase = WyckoffPhase.ACCUMULATION
```

**变更 3 — T+1 验证中 expansion/high 目标计算**：在 `_step3_phase_c_t1()` 中放宽 Spring 检测条件，将 `SPRING_LOW_FACTOR` 从 `0.97` 放宽到 `0.98`（已在 `shared/constants.py` 中定义）。

**影响范围**：仅 `engine.py` 中的阈值常数，不涉及接口变更。需重新运行验证脚本确认 UNKNOWN 率下降。

**修改量级**：5 行
**回归风险**：中（需要更新 Wyckoff 单元测试的预期值）

---

### P1.2 T+1 动态阈值 — 基于 ATR 替代固定 3%

**问题**：`rule3_t1_risk_test()` 固定要求 `max_drawdown < 3%` 算"安全"，导致 57% 的主板股票被拒绝。对于日均振幅 5-15% 的 A 股，固定 1.5% 的止损宽度过于严格。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `rules.py` | `rule3_t1_risk_test():72-114` | 固定阈值 `<3%` 安全、`<5%` 偏薄、`>=5%` 超限 |
| `rules.py` | `rule10_stop_loss():323-364` | 固定 `key_low * 0.995` 止损位 |

**修复方案**（2 处变更）：

**变更 1 — rule3 动态阈值**：
```python
# rules.py ~line 72
@staticmethod
def rule3_t1_risk_test(
    entry_price: float, support_low: float, 
    recent_limit_moves: List[Dict] = None,
    atr: Optional[float] = None,  # 新增参数
) -> Dict[str, Any]:
    if entry_price <= 0 or support_low <= 0:
        return {"verdict": "超限", "pct": 100.0, ...}
    
    max_drawdown_pct = (entry_price - support_low) / entry_price * 100
    
    # 动态阈值：使用 ATR 的 1.5 倍，最小不低于 3%
    if atr and atr > 0:
        dynamic_threshold = max(3.0, (atr / entry_price) * 100 * 1.5)
    else:
        dynamic_threshold = 3.0
    
    if max_drawdown_pct < dynamic_threshold:
        return {"verdict": "安全", "pct": round(max_drawdown_pct, 2), ...}
    elif max_drawdown_pct < dynamic_threshold * 1.5:
        return {"verdict": "偏薄", ...}
    else:
        return {"verdict": "超限", ...}
```

**变更 2 — rule10 止损精度**：
```python
# rules.py ~line 323
def rule10_stop_loss(key_low: float, ..., atr: Optional[float] = None):
    if atr and atr > 0:
        stop_loss_price = key_low - atr * 1.0  # 1倍ATR止损
    else:
        stop_loss_price = key_low * 0.995
```

**影响范围**：调用 `rule3_t1_risk_test()` 和 `rule10_stop_loss()` 的地方需要传入 `atr` 参数。在 `engine.py:_step3_phase_c_t1():668` 和 `_step4_risk_reward()` 中需要先计算 ATR。

**修改量级**：~30 行
**回归风险**：低（新增可选参数，不破坏现有调用）

---

### P1.3 多周期分析默认启用

**问题**：`WyckoffEngine.analyze()` 的 `multi_timeframe` 参数默认为 `False`，导致 R9 多周期降级规则（`rules.py:286-321`）从未被触发。月线 Markdown → 强制空仓的联动功能在直线上不可用。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `engine.py` | `analyze()`:117 | `multi_timeframe: bool = False` |
| `services/analysis/wyckoff_analysis_engine.py` | `run_wyckoff_analysis()`:49 | 调用时未传 `multi_timeframe` |

**修复方案**（2 处变更）：

**变更 1 — wyckoff_analysis_engine.py**：
```python
# wyckoff_analysis_engine.py ~line 49
result = wyckoff_engine.analyze(df, multi_timeframe=True)  # 原不传参
```

**变更 2 — 补充周线数据预加载**：`WyckoffEngine.analyze()` 的 `_analyze_multiframe()` 需要周线和月线数据。当前 `multi_timeframe_lookback_days` 计算了足够的日线数据量（`weekly_lookback * 7`），但 `_resample_ohlcv()` 的重采样逻辑需要确保 `amount` 列存在（`engine.py:100-101`）。

**影响范围**：多周期分析的性能影响——从 1 次分析变为 3 次分析（日/周/月）。每只股票耗时从 ~0.5 秒增至 ~1.5 秒。

**修改量级**：1 行 + 数据准备验证
**回归风险**：低（功能已实现，只是未启用）

---

## P2 — 本季度完善（质量提升）

### P2.1 LPPL 震荡市降噪

**问题**：H6 实证显示震荡市 Danger 信号假阳性率 137%。R² < 0.5 的拟合不应触发 Danger，但当前 `classify_top_phase()`（`engine.py:168-177`）只检查 `r2 >= danger_r2_threshold()`（~0.5），没有额外的震荡市降噪。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `engine.py` | `classify_top_phase()`:168-177 | 仅 R² + days_left 判定 |
| `engine.py` | `calculate_risk_level()`:386-403 | 同上 |

**修复方案**：

```python
# engine.py ~line 168
def classify_top_phase(days_left: float, r2: float, config: LPPLConfig, 
                      price_volatility: float = None) -> str:
    if days_left < 0:
        return "none"
    
    # 震荡市降噪：低波动市场中的高R²可能只是拟合噪声
    if price_volatility and price_volatility < 0.10:
        # 近60天涨幅<10%时，R²要求提高0.15
        adjusted_r2 = r2 - 0.15
    else:
        adjusted_r2 = r2
    
    if days_left < config.danger_days and adjusted_r2 >= danger_r2_threshold(config):
        return "danger"
    ...
```

**修改量级**：15 行
**回归风险**：低

---

### P2.2 Wyckoff 置信度 A 级可达

**问题**：实证数据显示 0% 的 A 级置信度。`rule8_confidence_matrix()`（`rules.py:238-283`）要求 5 项条件中满足 ≥4 项才给 A 级。但 `rr_qualified` 要求 `rr_ratio >= 2.5`，而 ATR 回填的目标位（`_step4_risk_reward()`）很难达到这个标准。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `engine.py` | `_calc_confidence()`:831-864 | 调用 `rule8`，但有 2 条 bypass |
| `engine.py` | `_step4_risk_reward()`:797-798 | `first_target = current_price + 2.0 * atr` |
| `rules.py` | `rule8_confidence_matrix()`:238-283 | ≥4 条件 → A 级 |

**修复方案**：

在 `_calc_confidence()` 中放开 A 级条件：
```python
# engine.py ~line 847
if step3.spring_detected and not step3.lps_confirmed:
    return ConfidenceResult(level="C", ...)  # 保持 Spring→C 级 bypass

# 新增：Spring+LPS+BC+RR≥1.5 → A 级（原要求 RR≥2.5）
if (step3.spring_detected and step3.lps_confirmed 
    and rule0.bc_found and rr.rr_ratio >= 1.5):
    return ConfidenceResult(
        level="A", ..., position_size="标准仓位",
        reason="Spring+LPS+BC+盈亏比达标",
    )
```

**修改量级**：10 行
**回归风险**：低

---

### P2.3 真实数据回归测试

**问题**：现有 1,034 个测试全部使用合成数据或 mock。导致 DE 0% 收敛率、R² 差异 0.83 等问题在合并前未被发现。

**代码定位**：`tests/` 目录

**修复方案**（新增 2 个测试文件）：

```python
# tests/test_lppl_real_data.py
def test_lppl_on_real_stocks():
    """验证 LPPL 在真实股票数据上的基本行为"""
    for sym in ["600519.SH", "000300.SH"]:
        df = load_parquet(sym)
        result = LPPLEngine().detect_bubble(df)
        assert "risk_level" in result
        assert "confidence" in result
        # 关键断言：DE 优化器必须工作
        config = LPPLConfig(window_range=[120], optimizer="lbfgsb")
        fit = fit_single_window_lbfgsb(df["close"].values, 120, config)
        assert fit is not None, f"{sym}: L-BFGS-B fit failed"
        assert fit["r_squared"] >= 0  # 允许负值，但必须可计算
```

```python
# tests/test_wyckoff_real_data.py
def test_wyckoff_on_real_stocks():
    """验证 Wyckoff 在真实股票数据上的基本行为"""
    for sym in ["600519.SH", "300750.SZ"]:
        df = load_parquet(sym)
        result = WyckoffEngine().analyze(df, symbol=sym)
        assert result.structure is not None
        # UNKNOWN 是可接受的结果，但不能崩溃
```

**修改量级**：+80 行（两个测试文件）
**回归风险**：无

---

### P2.4 LPPL L-BFGS-B 加入 Joblib 并行化

**问题**：LPPL 诊断耗时 250 秒，其中 240 秒为 L-BFGS-B 拟合（2,812 次 × ~85ms）。`engine.py` 的 `scan_date_range()` 已使用 `joblib.Parallel`，但 `scan_all_windows()` 也使用，造成了嵌套并行。

**代码定位**：
| 文件 | 行 | 现状 |
|---|---|---|
| `engine.py` | `scan_date_range()`:462-478 | 使用 `joblib.Parallel` |
| `engine.py` | `LPPLEngine.scan_all_windows()`:975-1002 | 使用 `joblib.Parallel` |
| `engine.py` | `analyze_peak()`:626-652 | 使用 `joblib.Parallel` |

**修复方案**：
确保单次拟合不在嵌套并行环境下运行。在 `fit_single_window_lbfgsb()` 和 `fit_single_window()` 外层添加 `_in_parallel` 检查，如果已在并行上下文中则串行执行。

---

## 最终执行建议：三角色综合意见

### 量化算法工程师意见

**必须优先处理的三个算法问题**：

1. **P0.1 — R² 输出缺失**是最容易被忽视但影响最广的问题。UI 层、回测层、信号层的所有"拟合质量"指标要么缺失、要么使用了 `confidence` 替代 R²。没有人知道 LPPL 模型在特定股票上的拟合优度是多少。

2. **P0.2 — 优化器切换**可以让 LPPL 拟合成功率从 0% 到 100%。DE 的 0% 成功率的根因不是 DE 本身不好，而是当前的种群/代数配置不适合 LPPL 的问题规模。保留 DE 作为秋季校准模式是正确的。

3. **P1.2 — 动态 T+1 阈值**在算法层面最关键。固定阈值不考虑个股波动率的做法，在算法设计上就是不合理的。ATR 是最简单的波动率估计，后续可升级为 GARCH 或已实现波动率。

**被数据反驳的假设**值得反思：H4（循环论证）和 H9（反事实无效）被数据证伪。这说明代码审查中的直觉判断需要运行时数据的支撑。建议在后续的代码审查流程中，将"关键假设审查"作为一个步骤——写下假设、设计最小验证、再推进。

### 量化架构工程师意见

**当前架构没有大问题。真正的问题是测试覆盖面的空白。**

1. engine.py 和 calculator.py 的双文件设计本身没错（底层数值 vs 高层编排），但两者之间缺乏契约测试。建议在 `tests/` 下增加一个 `test_lppl_consistency.py`，专门验证两个路径输出的一致性。

2. Wyckoff 的 `_step1_phase_determine()` God Method 是架构上最大的技术债。但 200 行的重构不应该是 P0——先做阈值调整（P1.1），再让测试覆盖所有 15 条分支，最后才拆分成子函数。

3. 修复后的验证流程应当自动化：建议在 `scripts/` 下保留 `lppl_wyckoff_cross_validation.py`，并在 P0.1+P0.2 完成后，将此脚本作为 CI 的一步。每次改动后可运行 `python3 scripts/lppl_wyckoff_cross_validation.py --stocks golden_20` 快速验证。

4. `LPPLOutput` 增加 `r_squared` 字段是一个跨层变更（`shared/interfaces.py` → `services/analysis/lppl_analysis_engine.py` → `signal/adapters.py`）。需要检查所有读取 `confidence` 的代码是否误将 `r_squared` 当作 `confidence` 使用。核查结果：**`signal/adapters.py` 的 `LPPLAdapter.adapt()` 读取 `raw_output.get("confidence")`，与 `r_squared` 字段无关，无冲突。**

### 交易员意见

**修复后的实战可用性预测**：

| 引擎 | 当前可用性 | 修复后可用性 | 关键变化 |
|---|---|---|---|
| LPPL（风控） | ⚠️ 条件可用 | ✅ 可信 | R² 输出让拟合质量可量化，L-BFGS-B 确保 100% 覆盖率 |
| Wyckoff（择时） | ❌ 不可用 | ⚠️ 有限可用 | 阈值放宽后 UNKNOWN 率将至 ~20%，但信号密度仍低于预期 |
| T+1 风控 | ❌ 过于激进 | ✅ 动态适配 | ATR 动态阈值将拒单率从 57% 降至 ~20-30% |
| 交叉验证 | ❌ 不可用 | ⚠️ 待数据验证 | P1.1 之后才会有 Wyckoff BUY 信号，届时再跑 H11/H12 |

**交易员最在意的指标变化预测**：

- **信号产生率**：当前 0 个做多信号 / 100 只股票。P1.1 后预期提升至 3-5 个/100 只（ACCUMULATION 6% → ~15%）  
- **信号可信度**：当前 0% A 级。P2.2 后预期 ~5% A 级、~20% B 级
- **假预警率**：当前 LPPL 137%。P2.1 后预期 <20%

**最终建议**：先做 P0.1+P0.2（1 天），然后运行验证脚本确认基线。再做 P1.1（半天），这是唯一能让交易员看到实际信号变化的工作。其余项可以按周迭代。**不要试图一次性做完所有项目——每完成一项就运行验证脚本，观察指标变化。**

---

## 修复计划总览

| ID | 优先级 | 描述 | 文件 | 行数 | 风险 | 预期效果 |
|---|---|---|---|---|---|---|
| P0.1 | **P0** | calculator.py 添加 R² 输出 + LPPLOutput 新增字段 | `calculator.py`, `interfaces.py` | +25 | 低 | R² 从"不存在"变为"可读取" |
| P0.2 | **P0** | L-BFGS-B 升为主优化器 | `engine.py` | +20 | 中 | 拟合成功率 0% → 100% |
| P1.1 | P1 | Wyckoff Step1 阈值放宽 | `engine.py` | +5 | 中 | UNKNOWN 率 43% → <20% |
| P1.2 | P1 | T+1 动态 ATR 阈值 | `rules.py` | +30 | 低 | 拒单率 57% → <30% |
| P1.3 | P1 | 多周期分析默认启用 | `wyckoff_analysis_engine.py` | +1 | 低 | R9 风控生效 |
| P2.1 | P2 | LPPL 震荡市降噪 | `engine.py` | +15 | 低 | 假阳性率 137% → <20% |
| P2.2 | P2 | Wyckoff A 级可达 | `engine.py` | +10 | 低 | A 级 0% → >5% |
| P2.3 | P2 | 真实数据回归测试 | `tests/` | +80 | 无 | 防止回归 |
| P2.4 | P2 | Joblib 并行化 | `engine.py` | +15 | 低 | 耗时 250s → 60s |

**每项变更都可在 1 小时内完成编码。总计约 8 小时的工作量。**

---

## P3 — 下一轮迭代（精度提升 + 死代码清理）

> 基于 9/9 项修复完成后的三角色联合评估会议（2026-06-18）识别。
> 争议最大项已标记三角色分歧指数（1=一致同意，3=重大分歧）。

### P3.1 混合模式死代码清理 / DE 种群配置修复

**分歧指数**：🟢 1/3（算法 + 架构 = 必须做，交易员 = 无所谓）

**问题**：`scan_single_date()`（`engine.py:474-480`）的 `"hybrid"` 模式先用 L-BFGS-B 快速求解，再对 R²>0.6 的结果用 DE 做验证性搜索。但 H1 实证显示 DE 在默认 `popsize=5` 下成功率 **0%**（283/283 全部超时或未收敛）。混合模式的 DE 阶段**从不实际执行**，`de_validated` 标记永远是缺失的。

**根因**：LPPL 是 7 维优化问题（tc, m, w, a, b, c, phi）。DE 的标准建议种群大小是 `10-15 × 维度`。当前 `popsize=5` 对于 7 维问题约等于 `0.7×` 维度——远低于最低推荐值 `70`（10×7）。即使配置 `popsize=15`（`~2×`），在 `maxiter=30` 下也很少收敛。

**代码定位**：

| 文件 | 行 | 当前值 | 建议值 |
|---|---|---|---|
| `engine.py` | `LPPLConfig`:67 | `popsize=5` | `popsize=15` |
| `engine.py` | `LPPLConfig`:58-60 | `maxiter=30` | `maxiter=100` |
| `engine.py` | `scan_single_date()`:474-480 | hybrid 模式 | 见下方方案 |

**修复方案（二选一，建议方案 B）**：

**方案 A — 修复 DE（保守）**：
```python
# engine.py ~line 67 - 同时保留 hybrid 模式
popsize: int = 15   # 从 5→15，7维问题的合理下限
maxiter: int = 100  # 从 30→100，给DE足够迭代次数
```

- **优点**：保留 DE 作为独立验证手段，学术严谨
- **缺点**：DE 拟合耗时从 ~85ms 增至 ~500ms+，全量分析可能从 250s → 1500s
- **风险**：即使增加配置，DE 在 LPPL 上的收敛性仍无保证。可能需要更大的 `popsize=50` 才能可靠收敛

**方案 B — 移除 hybrid 模式（推荐）**：

```python
# engine.py ~line 472-482 改为：
if config.optimizer == "de":
    res = fit_single_window(subset, window_size, config)
else:
    res = fit_single_window_lbfgsb(subset, window_size, config)
```

同时简化 `LPPLConfig`：
```python
optimizer: str = "lbfgsb"  # 只保留 "de" | "lbfgsb"，移除 "hybrid"
```

- **优点**：消除死代码，简化维护，L-BFGS-B 100% 可靠
- **缺点**：失去 DE 的独立验证路径（但 H1 已证明 DE 在此问题上无效）
- **回归风险**：无，所有生产路径已使用 L-BFGS-B

**修改量级**：方案 A +15 行 / 方案 B -10 行
**回归风险**：方案 B 低（hybrid 模式在生产中从未被触发）

---

### P3.2 Wyckoff B+ 级置信度路径（进一步降低 A 级门槛）

**分歧指数**：🟡 2/3（交易员 = 必须，算法 = 可行，架构 = 无风险）

**问题**：P2.2 新增的 A 级路径（Spring+LPS+BC+RR≥1.5）在 golden_20 上未触发。验证显示 A 级要求的三重条件（Spring+LPS+BC 同时出现）在 20 只股票中发生次数为零。20 只股票中 Spring 检测 0 个、LPS 确认 0 个（H12: n_events=0）。

**根因**：Wyckoff 本身就是低频信号系统。Spring 需要明确的恐慌性抛售后快速反弹形态，在 A 股的日常震荡中不会频繁出现。加上 LPS（后续支撑测试）和 BC（购买高潮）更是极低频组合。

**代码定位**：

| 文件 | 行 | 当前条件 |
|---|---|---|
| `engine.py` | `_calc_confidence()`:847 | Spring+LPS+BC+RR≥1.5 → **A 级** |
| — | — | Spring(无LPS) → **C 级**（跳级太陡）|

**修复方案**：

在 A 级（847-853）和 Spring→C 级（854-860）之间插入 B+ 级路径：

```python
# engine.py ~line 853
# B+级：Spring+LPS（不需要BC）+ 盈亏比≥1.5
if step3.spring_detected and step3.lps_confirmed and rr.rr_ratio >= 1.5:
    return ConfidenceResult(
        level="B+", bc_located=bc_located, spring_lps_verified=True,
        counterfactual_passed=counterfactual_passed,
        rr_qualified=rr.rr_ratio >= 2.5,
        multiframe_aligned=multiframe_aligned, position_size="轻仓试探",
        reason=f"Spring+LPS+盈亏比{rr.rr_ratio:.1f}，B+级",
    )
```

**影响范围**：B+ 级在 `_step5_trading_plan()` 中需要对应处理：

```python
# engine.py ~line 886 - 做多触发逻辑
if step3.spring_detected and step3.lps_confirmed:
    if confidence.level in ("A", "B+"):
        direction = "做多"
    else:
        direction = "轻仓试探"
```

同时需要更新 `models.py` 的 `ConfidenceResult.level` 类型注解接受 `"B+"` 字符串。

**修改量级**：+15 行
**回归风险**：无（新增路径，不影响 A/C/D 级的现有逻辑）

---

### P3.3 T+1 ATR 前后对比验证 + golden_100 全量跑

**分歧指数**：🟢 1/3（一致同意）

**问题**：P1.2 将 T+1 3%/5% 硬编码阈值切换为 ATR 动态阈值，但没有修复前/修复后的对比数据。H10 仅在修复后跑了一遍 golden_20，报告 `SH_Main: {安全: 9, 超限: 11}`。交易员声称"修复前拒单率 57%"，但无法确认这个数字。

**修复方案**（非代码变更，验证流程改进）：

修改 `scripts/lppl_wyckoff_cross_validation.py` 的 H10 诊断，增加 ATR 对比输出：

```python
# H10: T+1 压力测试对比
# 旧阈值模式（3%/5%）
old_verdict = "超限" if max_drawdown_pct >= 5.0 else ("偏薄" if max_drawdown_pct >= 3.0 else "安全")
# 新阈值模式（ATR）
atr_pct = current_atr / current_price * 100
new_safe = max_drawdown_pct < atr_pct * 0.5
new_limit = max_drawdown_pct < atr_pct * 1.0
```

同时在报告中新增对比表：

```json
"t1_comparison": {
    "old_threshold_3pct_safe": 5,
    "old_threshold_5pct_limit": 15,
    "new_atr_safe": 9,
    "new_atr_limit": 11,
    "拒单率变化": "-20pp"
}
```

**修改量级**：+30 行
**运行时间**：~300 秒（golden_100）

---

### P3.4 并行 guard: threading.local() → current_process() 检测

**分歧指数**：🟢 1/3（一致同意 — 架构评估发现的设计缺陷）

**问题**：P2.4 用 `threading.local()` 实现 `_in_parallel()` 深度计数，但 joblib 的 `loky` backend 使用多进程（而非多线程），子进程不继承主进程的 `threading.local` 状态。

**代码定位**：

| 文件 | 行 | 当前 | 建议 |
|---|---|---|---|
| `engine.py` | `_in_parallel()`:47-49 | `threading.local()` depth | `current_process().name` |

**修复方案**：

```python
from multiprocessing import current_process

def _in_parallel() -> bool:
    if os.environ.get("LPPL_DISABLE_PARALLEL") == "1":
        return True
    return current_process().name.startswith("LokyProcess")
```

同时移除 `_PARALLEL_DEPTH` 全局变量和 `import threading`。

**影响范围**：仅 `engine.py` 顶端模块级变更，不影响任何调用点。
**修改量级**：-5 行（净减少，移除一个全局变量）
**回归风险**：低

---

### P3.5 R² 命名规范: in_sample vs out_of_sample

**分歧指数**：🟡 2/3（架构 = 必须规范，交易员 = 无所谓，算法 = 低优先但正确方向）

**问题**：H3 显示 `mean_r2_diff=0.81` — 这不是 Bug，而是设计如此。`LPPLOutput.r_squared` 是样本内拟合 R²（全窗口），但 `fit_single_window_lbfgsb` 返回的 `r_squared` 也是样本内值。真正有差异的是 engine.py 内部用 30 日留存期计算的 "验证 R²"。但当前代码将两者都命名为 `r_squared`，导致使用者困惑。

**代码定位**：

| 文件 | 符号 | 当前命名 | 语义 | 建议命名 |
|---|---|---|---|---|
| `shared/interfaces.py` | `LPPLOutput.r_squared` | `r_squared` | 样本内拟合 R² | `in_sample_r_squared` |
| `engine.py`:240 | `fit_single_window_lbfgsb` | `r_squared` | 样本内拟合 R² | 无变更（内部变量） |
| 缺失 | — | — | 30 日外样本 R² | 新增字段 |

**修复方案**：

1. `shared/interfaces.py`：
```python
@dataclass
class LPPLOutput:
    risk_level: str = "Safe"
    confidence: float = 0.0
    days_to_tc: Optional[float] = None
    price: float = 0.0
    in_sample_r_squared: float = 0.0  # 重命名
    out_of_sample_r_squared: float = 0.0  # 新增

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "bubble_confidence": self.confidence,
            "lppl_days_to_tc": self.days_to_tc,
            "price": self.price,
            "in_sample_r_squared": self.in_sample_r_squared,
            "out_of_sample_r_squared": self.out_of_sample_r_squared,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LPPLOutput":
        return cls(
            ...
            in_sample_r_squared=float(data.get("in_sample_r_squared",
                                    data.get("r_squared", 0.0))),  # 向下兼容
            out_of_sample_r_squared=float(data.get("out_of_sample_r_squared", 0.0)),
        )
```

2. 更新所有读取 `LPPLOutput.r_squared` 的地方（`services/analysis/lppl_analysis_engine.py`, `signal/adapters.py`, `services/research_pipeline.py`, `services/scan_service.py`）

3. engine.py 内计算 30 日外样本 R² 并存入 `LPPLOutput`

**修改量级**：~30 行（跨 5 个文件）
**回归风险**：中（涉及跨层接口变更，需 `from_dict` 向下兼容）

---

### P3.6 自适应降噪阈值: ATR 替代固定偏移

**分歧指数**：🟡 2/3（算法 = 更精确，架构 = 可推迟，交易员 = 对实战无影响）

**问题**：P2.1 使用固定规则 `price_ret < 0.10 → r2 -= 0.15`。这个 0.15 偏移量是经验值——对 golden_20 有效，但可能在 A 股结构性牛市（2020）或单边下跌（2022）中过度惩罚或惩罚不足。

**代码定位**：

| 文件 | 行 | 当前 | 建议 |
|---|---|---|---|
| `engine.py` | `classify_top_phase()`:120-122 | `abs(price_ret) < 0.10 → r2 -= 0.15` | ATR 自适应 |

**修复方案**：

```python
# engine.py ~line 115
def classify_top_phase(days_left: float, r2: float, config: LPPLConfig,
                       price_ret: Optional[float] = None,
                       atr_pct: Optional[float] = None) -> str:
    if days_left < 0:
        return "none"

    adjusted_r2 = r2
    if price_ret is not None:
        if atr_pct is not None and atr_pct > 0:
            if atr_pct < 2.0:
                adjusted_r2 = r2 - 0.20
            elif atr_pct < 4.0:
                adjusted_r2 = r2 - 0.10
        elif abs(price_ret) < 0.10:
            adjusted_r2 = r2 - 0.15  # fallback
```

同时更新所有 `classify_top_phase` 调用点传入 `atr_pct`（约 5 处）。

**修改量级**：+20 行
**回归风险**：低（新增可选参数，不破坏现有调用）

---

## P3 执行顺序建议

```
轨道1（并行）:
  P3.4 (并行guard修复) → 5分钟 → 单元测试
  P3.2 (B+级路径)     → 15分钟 → Wyckoff单测

轨道2（依赖验证）:
  P3.3 (对比验证) → golden_100运行 → ~5分钟分析数据

轨道3（串行）:
  P3.1 (hybrid移除) + P3.5 (R²重命名) + P3.6 (自适应阈值)
  → 需等待P3.3对比数据指导P3.6阈值设计
```

## P3 摘要表

| ID | 优先级 | 描述 | 文件 | 行数 | 风险 | 预期效果 |
|---|---|---|---|---|---|---|
| P3.1 | P2 | 移除 hybrid 死代码或修复 DE popsize | `engine.py` | ±15 | 低 | 消除无效代码路径 |
| P3.2 | P1 | Wyckoff B+ 级新路径 | `engine.py`, `models.py` | +15 | 无 | A 级信号产生率 >0% |
| P3.3 | P2 | T+1 ATR 前后对比 + golden_100 | `scripts/` | +30 | 无 | 量化证伪/证实 57% 拒单率 |
| P3.4 | P2 | 并行 guard: loky 进程检测 | `engine.py` | -5 | 低 | 跨进程并行防嵌套生效 |
| P3.5 | P2 | R² 命名规范 + 外样本 R² | 5 个文件 | +30 | 中 | 消除 R² 命名歧义 |
| P3.6 | P3 | ATR 自适应降噪阈值 | `engine.py` | +20 | 低 | 全周期假阳性率稳定性 |

**总计**: ±105 行, ~4 小时

---

## 执行顺序建议

```
Week 1: P0.1 + P0.2 → 跑验证脚本 → 更新 golden baseline
Week 2: P1.1 + P1.2 → 跑验证脚本 → 验证 UNKNOWN 率 / 拒单率
Week 3: P1.3 + P2.1 + P2.2 → 跑全量测试
Week 4: P2.3 + P2.4 → 修复验证 + 性能基准
```

每项变更加入后运行 `python3 scripts/lppl_wyckoff_cross_validation.py --stocks golden_100` 验证效果。

---

## 已知限制

### Spring 检测信号密度 — A 股结构性限制

Wyckoff Spring 事件在 golden_20（20 只 A 股, 2022-01 至今）的三年数据中触发率为 **0%**。原因：

1. **A 股政策底效应**：国家队护盘和监管干预减少了恐慌性 V 形反转
2. **SPRING_LOW_FACTOR=1.01** 已允许收盘价 1% 低于 TR 下沿——敏感度已较高
3. Spring 本质上是恐慌底买入信号，A 股 1-2 年发生一次（如 2024-02 微盘股崩盘），样本不足是数据特征，非代码 Bug

**影响**：
- B 级（Spring+LPS+RR≥1.5）和 A 级（+BC）信号在当前 3 年窗口内无法触发
- Wyckoff 引擎实际使用时只能输出 C 级（试仓/轻仓试探）信号
- 当前不推荐将 Wyckoff 作为独立入场信号；建议降级为风控过滤器

### `out_of_sample_r_squared` 计算假设

30 日 holdout R² 在 `detect_bubble()` 中实现，固定非线性参数重拟线性参数。
- 对于数据量 < 60 的股票返回 0.0
- 如果 tc 远在 holdout 窗口之外，外样本拟合可能不稳定
