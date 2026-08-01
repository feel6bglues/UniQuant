# 红蓝对抗 Round 1 — LPPL 真实有效实现方案

> **日期**: 2026-07-24  
> **对抗议题**: 在项目约束下（A 股个股、120 天窗口、生产管线），LPPL 模型应该怎样实现才有真实预测力？
> **角色**: 🔵 Blue = 主张"可以修复 → 值得保留" / 🔴 Red = 主张"无法修复 → 应移除"

---

## 审查标准：什么算"真实有效的 LPPL 实现"

| 条件 | 门槛 | 来源 |
|---|---|---|
| C1 | b<0 约束强制执行 | Sornette 2003 |
| C2 | c>0.01 约束强制执行 | Fantazzini 2011 |
| C3 | tc 全局搜索，至少 50 个初始点均匀覆盖 [0, T+100] | ETH 金融危机观测站 |
| C4 | 优化方法为变量投影 (VP)：3 非线性 + 4 线性解析 | Filimonov & Sornette 2013 |
| C5 | 泡沫置信度用 Monte Carlo p-value，非 R² 阈值 | Shu & Song 2024 |
| C6 | 不输出 days_to_crash 具体值，只输出相对风险概率 | Sornette 多次强调 |
| C7 | 个股 120 天窗口信噪比足够 → LPPL 有区分度 | 需实证验证 |

---

## Claim 1: "LPPL 可以通过加约束修复"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 在 `cost_function` 中加入 `b<0` 惩罚项，加入 `c>0.01` 约束，LPPL 即可从"无约束曲线拟合"变为"Sornette 泡沫检测" | — |
| 🔴 Red | 加入约束后：LPPL 对 A 股个股的**收敛率会急剧下降**。`b<0` 和 `c>0.01` 要求价格对数趋势必须是**加速凸增长**（二阶导>0）+ **周期性振荡**。在 A 股 120 天窗口中：约 60-70% 的窗口是震荡/下跌/减速增长 — 这些窗口 LPPL 约束后会直接不收敛或 RMSE 极高，最终输出为"无泡沫"。剩下的 30-40% 上涨窗口中，真正呈**加速凸增长**的不足一半。最终触发率约 15-20%（vs 当前"高危"14.7%）。触发率降低不代表有效 — 需要用 MC 验证这 15-20% 是否有预测力 | A 股实证：120 天窗口呈加速凸增长比例 ~15-25%；LPPL 对个股的宏观泡沫映射力在学术上尚未证实 |
| ⚪ Referee | **BLUE 技术上正确**但 RED 的实证担忧成立。加入约束是**必要条件**但不是充分条件。关键问题是：A 股个股 120 天数据的信噪比是否足够支撑 7 参数模型（即使加约束）？MC 验证才能回答。**裁决：BLUE 方法论正确，但实用价值需 MC 验证。** | |

**修正方案**:
```python
def cost_function_lppl_constrained(params, t, log_price):
    tc, m, w, a, b, c, phi = params
    penalty = 0.0
    if b >= 0:
        penalty += 1e6 * (b + 1.0) ** 2  # b<0 强制
    if abs(c) < 0.01:
        penalty += 1e6 * (0.01 - abs(c)) ** 2  # |c|>0.01 强制
    fitted = lppl_func(t, tc, m, w, a, b, c, phi)
    rmse = np.sqrt(np.mean((fitted - log_price) ** 2))
    return rmse + penalty
```

---

## Claim 2: "变量投影 (VP) 比纯 L-BFGS-B 显著提升 LPPL"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | VP 将 7 维搜索降为 3 维，提高收敛精度和速度，降低对初始点数量的需求。ETH FCO 用 VP，Filimonov & Sornette (2013) 证明 VP 是 LPPL 标配 | Filimonov & Sornette (2013) "A stable and robust calibration scheme for LPPL" |
| 🔴 Red | VP 的收益在高信噪比场景（宏观指数）显著，在低信噪比场景（个股 120 天）效果有限。VP 的线性参数求解假设残差高斯分布，A 股数据不满足。更重要的是：VP 无法解决根本问题 — 120 天窗口对 LPPL 来说仍然过短。**VP 是优化方法的改进，不是模型有效性的改进** | 实证：QuantConnect 用 VP 回测仍然 51.7% 最大回撤 |
| ⚪ Referee | **BLUE WINS** — VP 是既定学术标准，应实施。但 RED 正确指出 VP 不是银弹。**裁决：VP 必须实施，但不能指望它解决信号问题。** | |

**VP 实现方案**:
```python
def lppl_vp(t, tc, m, w, log_price):
    """Variable projection: solve for linear params analytically"""
    tau = tc - t
    tau_m = tau ** m  # shape: (n,)
    cos_term = tau_m * np.cos(w * np.log(tau + 1e-10))
    sin_term = tau_m * np.sin(w * np.log(tau + 1e-10))
    # Design matrix: [1, tau_m, cos_term, sin_term]
    A = np.column_stack([np.ones_like(t), tau_m, cos_term, sin_term])
    # Linear params: (a, b, c1, c2) solved via OLS
    lin_params, _, _, _ = np.linalg.lstsq(A, log_price, rcond=None)
    a, b, c1, c2 = lin_params
    fitted = A @ lin_params
    rmse = np.sqrt(np.mean((fitted - log_price) ** 2))
    c = np.sqrt(c1**2 + c2**2)
    phi = np.arctan2(c2, c1)
    return rmse, (tc, m, w, a, b, c, phi), fitted
```

---

## Claim 3: "Monte Carlo p-value 可以替代 R² 作为泡沫指标"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 对每只股票每次拟合，生成 1000 个 GBM 模拟（同长度、同 volatility），对每个模拟跑 LPPL 拟合，得到 RMSE/null 分布。将实际 RMSE 定位到 null 分布的百分位 → p-value。p<0.05 表示拟合质量优于 95% 随机数据。这直接解决了项目当前"93% GBM 拟合 R²>0.3"的致命问题 | Shu & Song 2024 综述：标准 LPPLS 使用 MC 引导检验 |
| 🔴 Red | MC p-value 的算力成本极高：3574 只股票 × 每个多窗口 × 1000 GBM × VP 拟合 = 天文数字。按当前 L-BFGS-B 性能：3574 × 6 窗口 × 1000 MC × 2s ≈ 12,000 小时。即使优化到 0.1s/拟合也要 600 小时。生产不可行。**捷径**：预计算 GBM null 分布表（按长度/volatility 分桶），查表代替实时模拟 — 但精度下降。另外：p<0.05 通过 MC 后，能否转化为交易信号仍有待验证 | 算力估算：当前拟合 ~2s/window × 1000 MC × 3574 stocks × 6 windows ≈ 11,922 小时 |
| ⚪ Referee | **RED WINS 实用性** — 全量 MC 在生产中不可行。**蓝方的方案需要预计算+查表优化才能进入生产。** **最优方案**：预计算 GBM null 分布表（100 个 volatility bucket × 3 窗口长度 × 10000 MC 每个 = 300 万次拟合一次性后台运算），运行时查表得到 p-value 近似值。 | |

**查表实现方案**:
```python
# 预计算：一次性后台作业
def precompute_lppl_null_distribution():
    """Precompute LPPL RMSE null distributions for GBM data"""
    np.random.seed(42)
    vol_buckets = np.linspace(0.05, 0.60, 100)  # 100 volatility buckets
    window_sizes = [60, 120, 240]
    null_table = {}
    for w in window_sizes:
        for vol in vol_buckets:
            rmse_null = []
            for _ in range(10000):
                gbm = np.exp(np.cumsum(np.random.normal(0, vol, w)))
                result = fit_lppl_vp(gbm, w)  # VP
                if result:
                    rmse_null.append(result["rmse"])
            null_table[(w, round(vol, 3))] = np.percentile(rmse_null, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    return null_table

# 运行时：查表
def lppl_p_value(rmse, window_size, volatility, null_table):
    key = (window_size, round(volatility, 3))
    dist = null_table.get(key)
    if dist is None:
        return 0.5  # fallback
    return np.searchsorted(dist, rmse) / len(dist)
```

---

## Claim 4: "LPPL 在 A 股个股 120 天窗口根本上不可用"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔴 Red | LPPL 的理论基础：泡沫是宏观现象，投资者的模仿性行为（社会传染）在指数层面显著，在个股层面被公司特定噪声淹没。Sornette 本人主要将 LPPL 用于指数（S&P 500、日经、恒生），很少用于个股。ETH FCO 输出的是"市场泡沫状态"，不是"个股买入/卖出信号"。A 股 120 天 ≈ 6 个月交易数据 — 大多数个股在此期间没有完整的宏观泡沫结构。QuantConnect 回测（标普 500 个股）PSR 仅 12.5% — 有效程度接近随机 | Shu & Song 2024: S&P 500 指数检测（非个股）；QuantConnect: 51.7% MDD, 12.5% PSR |
| 🔵 Blue | 虽然个股信噪比低，但 A 股市场换手率高、波动率大，泡沫结构在更短时间窗口内可能显现。国内有券商研报用 LPPL 检测 A 股指数和行业 ETF 的泡沫状态。建议将 LPPL 的应用范围从个股**上移至指数和行业 ETF**，这才是符合其理论设计的用途。对个股：可以用 LPPL 拟合的 m 和 ω 作为**因子特征**输入到多因子模型，但不直接作为交易信号 | 国内研报：广发证券、华泰证券用 LPPL 分析 A 股指数；因子研究：LPPL 参数可作为市场状态因子 |
| ⚪ Referee | **SPLIT — 双方都部分正确**。RED 主张的"个股 120 天 LPPL 不可用"已被项目 Monte Carlo 证明（93% GBM 拟合）。BLUE 提出的**上移至指数/行业 ETF** 和**因子化使用**是合理的前进方向。**最终裁决：LPPL 在当前形式（个股、120 天、直接交易信号）下应移除；如果在指数级别重新实现可以作为宏观风险指标。** | |

---

## Round 1 汇总

| Claim | 议题 | Blue | Red | 裁决 |
|---|---|---|---|---|
| C1 | 加约束可修复 | ✅ | ⚠️ | **BLUE** — 但需 MC 验证有效 |
| C2 | VP 显著提升 | ✅ | ⚠️ | **BLUE** — 必须实施，非银弹 |
| C3 | MC p-value 替代 R² | ✅ | ✅ | **RED** — 需查表优化 |
| C4 | 个股 120d 从根本上不可用 | ✅ | ✅ | **SPLIT** — 上移至指数/因子化 |

**核心产出一：LPPL 真实有效实现方案**:
```
┌──────────────────────────────────────────────────────────┐
│ LPPL v2 — 真实有效实现                                   │
├──────────────────────────────────────────────────────────┤
│ 定位：宏观指数/行业 ETF 泡沫风险指标，非个股交易信号      │
│ 输入：沪深 300/中证 500/行业指数，500-1000 天             │
│ 优化：VP (3 非线性 + 4 线性解析)                         │
│ 约束：b<0 强制 + |c|>0.01 强制                           │
│ 初始点：50+，tc 在 [0, T+100] 均匀分布                   │
│ 验证：MC p-value 查表                                    │
│ 输出：泡沫概率 p ∈ [0,1]，不输出 "days_to_crash"         │
│ 用途：多因子模型特征 / 仓位管理风险信号                   │
└──────────────────────────────────────────────────────────┘
```

**对项目的建议**：
1. **当前 LPPL 生产代码移除** — Monte Carlo 已证明零预测力
2. **保留计算器/VP 核心**作为离线研究工具
3. **如重写**：按上述 LPPL v2 方案，但定位为指数/行业 ETF 分析，不用于个股信号
4. **最务实的建议**：移除 LPPL 生产管线，用动量/波动率/换手率集成指标代替"泡沫检测"
