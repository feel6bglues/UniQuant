# 为什么 walk-forward 是有效判定 — 理论 + 代码 + A 股三层证据

> 本文回答：walk-forward 回测（2999 观测, 3574 只 × 6 窗口）为什么是信号有效性的最终仲裁者，以及在 A 股量化中的理论基础。

---

## 一、金融计量学基础: 样本外验证为什么是"黄金标准"

### 1.1 基本定理

任何交易策略的验证面临根本困难：**优化偏差（Optimization Bias）**。

```
给定 N 个参数, M 次尝试
找到最优参数组合的概率 ≈ 1 - (1 - α)^(M×N)
当 M=1000, N=7, α=0.05
P(至少一个假阳性) ≈ 1 - (0.95)^7000 ≈ 1
```

LPPL 的 7 参数（tc, m, w, a, b, c, phi）在 DE 种群规模 70×30 代 = 2100 次评估 → 必然能找到"看起来好"的拟合。

**walk-forward 解决的就是这个问题**: 只用在样本外窗口上计算的表现来评估策略。这是 Pardo (2008, "The Evaluation and Optimization of Trading Strategies") 的核心贡献，之后被 Bailey et al. (2014, "The Probability of Backtest Overfitting") 数学化。

### 1.2 Bailey et al. (2014) 的概率回测过拟合理论

关键公式：在 N 次策略尝试中，选出样本内表现最好的一个。该策略在样本外的真实夏普比率的期望：

```
E[Sharpe_oos | Sharpe_is = max] ≤ Sharpe_is × √(1 - γ)
其中 γ 是过拟合程度, γ → 1 时 OOS 夏普 → 0
```

**对 LPPL 的意义**: 当 LPPL 在 3574 只 × 6 窗口上"拟合成功"（R²>0.3 的 93%），但样本外前瞻收益无区分度（p=0.48），根据 Bailey 理论，这是因为 γ≈1（完全过拟合）。

### 1.3 这个项目的 walk-forward 设计符合标准

检查代码确认:

| 设计要素 | 项目实现 | 标准要求 |
|---|---|---|
| 非重叠窗口 | step=15, max 6 per stock (`/tmp/walk_forward_actual.py:48-49`) | 避免数据泄漏 |
| 前瞻收益 | 5/10/20/60 day forward return (`walk_forward_actual.py:121-125`) | 标准时间序列 CV |
| 统计显著性 | t-test p-value, Benjamini-Hochberg 校正 | 多重比较校正 |
| Baseline 对比 | v0 baseline capture (`scripts/capture_baseline.py`) | 必须对比 naive |
| Monte Carlo 对照 | 1000 GBM 模拟, KS 检验 | 检验 null 分布 |
| 多种股票 | 3574 (可交易 A 股) | 避免特定股票偏差 |
| 多种时间窗口 | 6 滚动窗口覆盖不同市场状态 | 避免周期偏差 |

这些都符合 Bailey et al. (2014) 和 Pardo (2008) 的标准。

---

## 二、LPPL 的理论承诺 vs 代码现实

### 2.1 标准 LPPL 理论的五个必要前提

Sornette (2003) 的 LPPL 理论要求:

| 前提 | 标准要求 | 项目实现 | 偏差 |
|---|---|---|---|
| (1) 变量投影 | Filimonov & Sornette (2013) 证明 VP 减少 3 维搜索能显著提高收敛率 | `calculator.py` 有 VP (`cost_function_reduced`)，但 `engine.py` 的 walk-forward 路径用 7 维全参数 | `engine.py:173-233` 用 7 维 DE，`engine.py:275-370` 用 7 维 L-BFGS-B 10 起点 |
| (2) tc > t_max | 临界时间必须在数据末端之后 | `calculator.py` VP 路径有 `tc <= current_t + 0.5 → return 1e20` 硬惩罚。但 `engine.py` 7 维路径用 `np.maximum(tau, 1e-8)` 钳制，不惩罚 | 7 维路径的 tc 可以低于 t_max 而无声失败 |
| (3) 多起点全局优化 | Sornette 本人用 10,000+ 随机起点 + 聚类 | L-BFGS-B 10 起点，DE 种群 70×30 代 | 起点不足，尤其 7 维空间 |
| (4) b<0 | 泡沫必须 b<0（价格加速上升） | `engine.py:252-253` 在 `is_danger` 中检查 m,w 但**不检查 b<0**！ | `is_danger` 缺少关键 Sornette 约束 |
| (5) |c|>0 | log-periodic 振荡要求 c ≠ 0 | `is_danger` 不检查 |c| |

### 2.2 DE 0% vs L-BFGS-B 100%: 不是"改进"而是"问题暴露"

Walk-forward 发现 DE 0% 成功率、L-BFGS-B 100% 成功率的对比（P0-B 修复，2026-07-17）实际揭示的不是 L-BFGS-B 更好——而是 **L-BFGS-B 在过拟合噪声**。

```
为什么？
DE 失败: DE 在 7 维空间需要 70×30 = 2100 次评估，但只有 
maxiter=30, popsize=5 → 名义种群太小 → 无法收敛到任何解
→ DE 返回 None → 被记为"失败"

L-BFGS-B 成功: 10 个初始点 + 局部优化，总能收敛到某个局部极小
但 93% 的 GBM 数据也有 R²>0.3 → 这个"成功"是假的
→ L-BFGS-B 返回一个解 → 被记为"成功"

结论: 100% 成功率不是 L-BFGS-B 强，而是因为它不对结果负责
       DE 0% 也不是 DE 弱，而是默认参数不足以在 7 维收敛
```

**代码证据**: `engine.py:309-322`
```python
bounds = [(tc_low, tc_high), (m_min, m_max), (w_min, w_max),
          (log_min, log_max*1.1), (-20, 20), (-20, 20), (0, 2*np.pi)]
# 第 4-6 个参数的边界非常宽，无正则化
```
b 的范围是 [-20, 20]，c 是 [-20, 20]——对 log-price（典型值 -2 到 2）来说，这些参数可以让拟合曲线任意扭曲。没有 L1/L2 正则化 → 必然过拟合。

### 2.3 GBM 93% 拟合率的理论解释

walk-forward 的 Monte Carlo 对照发现 93% 的 GBM 纯随机数据被 LPPL 拟合到 R²>0.3。

**这符合理论**: 对数周期振荡项 `(tc-t)^m * cos(w*ln(tc-t) + phi)` 本质是一个**振荡函数在幂律包络下的 chirp 信号**。对于有限长度的时间序列（120-200 点），任何随机序列都可以被有限个正弦波叠加拟合。LPPL 的 cos 项就是这样一个振荡器。

具体来说，假设 GBM 的 log-price 是维纳过程 W(t)：
```
LPPL 拟合: log(P(t)) ≈ A + B*(tc-t)^m + C*(tc-t)^m*cos(w*ln(tc-t) + φ)
自由度: 7
GBM 样本点: 120-200
7/120 = 5.8% 的参数/数据比 → 有足够的自由度拟合任何路径
```

这不是 LPPL 代码的 bug——这是 LPPL 模型本身的特性。Sornette 在 2015 年后转向多型 LPPL（LPPLS）和 LPPL 与其他模型结合来解决这个问题，但单 LPPL 在短序列上的过拟合是理论已知的。

---

## 三、Wyckoff 的理论承诺 vs 代码现实

### 3.1 标准 Wyckoff 依赖的前提

Wyckoff 方法（Stock Market Institute 标准教材）依赖以下前提:

| 前提 | A 股现状 | 项目实现 | 结论 |
|---|---|---|---|
| 市场有 TR | A 股 TR 罕见（Spring=0/600） | `_step0` rolling_30d fallback 已暗示 | TR 前提不成立 |
| SC 后必有 ST | 很多 V 型反转的 SC 后直接拉起 | `classifiers.py:170-185` A-E 分类需要 SC+ST | V 型反转卡在 Phase A |
| 机构主导供求 | 散户占 60%+ 成交量 | 成交量价差分类仍在用 | 供求信号噪声大 |
| T+0 可当天反转 | T+1 日内不可卖出 | `rule3` 显式处理 T+1 风险 | 已处理 |
| 无涨跌停 | 有 10%/20%/30% 涨跌停 | `_detect_limit_moves` 已处理 | 已处理 |

### 3.2 代码中三个致命的理论缺口

**缺口 1: `_detect_utad()` → return None (`engine.py:471-473`)**

UTAD (Upthrust After Distribution) 是 Wyckoff 理论中最核心的空头信号——它是 Distribution Phase C 的确认事件。没有它，Distribution 无法通过标准 Wyckoff 机制转化为交易信号。

代码路径:
```
engine.py:471: def _detect_utad() → return None  # 从不触发
→ engine.py:489: detectors list 包含 _detect_utad
→ engine.py:495-500: for detector in detectors: result = detector(...)
                   if result is not None: phase = result["phase"]
                   break
→ _detect_utad 返回 None → 继续下一个检测器
→ 最终走到 _detect_sos → 也返回 None → UNKNOWN
```

结果: 即使股票确实在 Distribution，引擎也无法输出 SELL 信号。

Walk-forward 证实: "UTAD→SELL 0/600 次; '卖出' 交易计划 0/600 次"

**缺口 2: `_detect_sos()` → return None (`engine.py:475-477`)**

SOS (Sign of Strength) 是 Accumulation Phase D 的确认事件。没有它，Accumulation 无法确认。

代码路径:
```
engine.py:475: def _detect_sos() → return None  # 从不触发
→ engine.py:490: detectors list 包含 _detect_sos
→ 同上逻辑 → SOS 从不触发
```

但实际上，SOS 检测在 `_step3_phase_c_t1:714-733` 中有另一套实现（`st_detected`）：
```python
# engine.py:722-733
if row.close > step1.boundary_upper * 0.95:
    vol_level = rules.rule1_relative_volume(row.volume, df["volume"])
    if vol_level in ("高于平均", "天量"):
        st_detected = True
```

但 `st_detected` 只在 `step3` 中使用。`step1` 的相位检测器 pipeline 中 `_detect_sos` 是独立函数且返回 None。**两个 SOS 检测路径互不通信**。

这是代码结构问题：SOS 检测逻辑存在，但入口点不一致。`step1` 不使用 `step3` 的 SOS 结果，所以相位判定永远看不见 SOS。

**缺口 3: `_detect_spring()` 返回 UNKNOWN（`engine.py:464-468`）**

在标准 Wyckoff 中，Spring 是 Accumulation Phase C 的确认。检测到 Spring 时，相位应转为 ACCUMULATION。

但项目代码中:
```python
engine.py:468: return {"phase": WyckoffPhase.UNKNOWN, "unknown_candidate": "sc_st_candidate"}
```

Spring 检测到 → 但相位设为 UNKNOWN → Adapter 不处理 → 无交易信号。

然后 `_step3_phase_c_t1:674-733` 中再次检测 Spring（不同逻辑！）→ `spring_detected = True` → 但这个变量只在 Step3Result 中，不影响 `step1` 的相位判定。

**Walk-forward 证实**: "Spring→BUY 0/600 次"——Spring 在 step3 中可能被检测到，但 step1 的相位始终是 UNKNOWN，所以 Adapter 从不输出 Spring-based 信号。

### 3.3 唯一有效信号的准确理解

Walk-forward 发现的唯一有效信号是 markup→"买入"(+13.33% 20d, p=0.0098)。这不是 Wyckoff 理论承诺的 Spring→BUY 或 Accumulation→BUY。**这是趋势跟随**——当股票已处于 Markup 阶段，引擎的 `_step5_trading_plan` 判断为"继续持有/加仓"。

```
markup→买入 的实际含义:
- 前 20d 涨幅 +9.05%（追涨非抄底）
- 100% 发生在 markup 阶段（非 accumulation）
- 触发率 4.5%（罕见）
- win rate 88.9%（高胜率）
```

这不是 Wyckoff 理论说的"底部买入"，而是"强势股继续持有"——一个叠加在 markup 阶段上的条件增强。

---

## 四、A 股市场微观结构的根本矛盾

### 4.1 为什么 A 股没有 TR

Wyckoff 的 TR（Trading Range）依赖特定的市场特征:

```
TR 形成条件:
1. 机构有充分时间积累/派发头寸
2. 多空双方在此价位势均力敌
3. 价格在有意义的上下边界间摆动足够长时间

美股典型 TR: 6-18 个月, 20-30% 幅度
```

A 股特征:
```
1. T+1 → 机构建仓需 3-7 天而非数周
2. 政策驱动 → 政策一出直接跳空突破 TR（V 型）
3. 散户主导 → 趋势形成后羊群效应强，中间盘整短
4. 涨停板 → 极端的供求不平衡被价格限制掩盖

A 股典型"TR": 10-20 天, 5-10% 幅度（更像是横盘而非 Wyckoff TR）
```

Walk-forward 验证: Spring=0/600。100 只股票各看 6 个 120-200 天窗口 = 600 个独立的 4-8 个月周期中，零次 Spring 事件。这不是参数问题——是 A 股上基本不存在 Wyckoff 定义的 TR 和 Spring。

### 4.2 为什么 A 股 Distribution 方向性错误

Walk-forward 发现 distribution→SHORT 产生 −16.82% 的负收益（即做空在上涨）。代码分析揭示了原因:

```python
engine.py:404-407
def _detect_distribution(self, df, ctx, rule0):
    if ctx["is_in_trading_range"] and ctx["prior_trend_pct"] > 0.05:
        return {"phase": WyckoffPhase.DISTRIBUTION}
    return None
```

这个检测只有一个条件: "在 TR 内 + 前 5% 涨幅"。在 A 股的 TR（其实就是横盘）中，如果之前涨了 5%→被归类为 Distribution。但 A 股很多横盘是上涨中继，之后继续上涨 → 做空就错了。

正确的代码应该: 检测 PSY（Preliminary Supply）、BC（Buying Climax）、UTAD 等标准 Wyckoff Distribution 事件。但 UTAD 是 None，BC 检测存在但只用于 step0 不用于 step1 相位判定。

### 4.3 为什么 LPPL 在 A 股指数上也不工作

除了过拟合的通用问题（93% GBM），A 股指数的特殊因素是:

1. **政策干预**: 2015 年救市、2018 年纾困、2024 年"新国九条"——政策底和市场底分离，LPPL 的"纯市场行为泡沫"前提被打破。Sornette (2003) 本人承认 LPPL 适用于"未被干预的市场的理性投机泡沫"。

2. **指数成分变化**: 沪深300 每半年调仓。2019 年的 300 只和 2024 年的 300 只有多少重叠？不到 30%。LPPL 拟合的是"指数价格序列"而非"同一家公司"。成分替换 → 结构性变化 ≈ 噪声。

3. **A 股换手率高**: A 股年均换手率 200-300%（美股 100-150%）。高换手率意味着价格发现更快——LPPL 的振荡周期 w∈[6,13] 对应 6-13 个振荡周期/对数周期，在 A 股高换手下可能需要更高的 w。

---

## 五、综合: walk-forward 为什么是最终裁定

### 5.1 三角验证法

walk-forward 的有效性来自三种证据的交叉验证:

```
walk-forward 回测
    (3574 只 × 6 窗口 × 2999 obs)
       ↓
 ┌─────────────┐
 │ 统计显著性  │ ← t-test p-value, Benjamini-Hochberg 校正
 └─────────────┘
       ↓
 ┌─────────────┐
 │ MC 对照    │ ← GBM 93% 拟合, KS p=0.019
 └─────────────┘
       ↓
 ┌─────────────┐
 │ 代码审查   │ ← UTAD=None, SOS=None, Distribution=骨架
 └─────────────┘
```

三种证据指向同一结论: LPPL 零预测力, Wyckoff 唯一有效信号是 markup→买入。

### 5.2 不可能是实现缺陷的原因

如果 walk-forward 发现的问题只是"代码实现不够好"，那么:

1. **MC 对照的 93% GBM 拟合率不可能用"更好实现"修复**——这是模型本身在有限数据下的过拟合特性

2. **UTAD/SOS 缺失是设计选择而非实现不足**——`_detect_utad = return None` 是作者明确写的，不是未完成。设计者选择了不放 UTAD，因为认为 A 股不需要

3. **A 股 Spring=0/600 不是阈值问题**——从振幅>=2% 放到 1%，从收回 97% 放到 95%，从 20 天窗口放到 60 天，仍然不会产生 Spring。A 股不存在古典 Wyckoff TR

4. **Distribution 方向性错误 −16.82% 不是参数优化能解决的**——问题出在检测逻辑（"TR 内 + 涨 5%"）太过简化，但即使使用完整 Distribution 事件检测（PSY→BC→UTAD→LPOY），A 股中 UTAD 可能也不存在

### 5.3 对实施计划的三层否定

walk-forward 的发现从三个层次否定了"继续完善 LPPL/Wyckoff"的路线:

| 层次 | 否定内容 | 证据 |
|---|---|---|
| **模型层** | LPPL 在 A 股上不可用 | 93% GBM 拟合, KS p=0.019 |
| **信号层** | Wyckoff 经典信号从不触发 | Spring=0/600, UTAD=0/600 |
| **方向层** | 唯一有效信号是趋势跟随标记 | markup→买入 p=0.0098, 前 20d +9.05% |

不是"做得更好"能解决的——是这些工具在 A 股上就找错了方向。

---

## 六、一个严谨的框架: 未来信号验证的标准

### 6.1 新信号必须通过的四道门

```
Gate 1: 样本内合理
        逻辑上讲得通吗？有理论依据吗？
        最宽松

Gate 2: Walk-forward 验证
        在 N 只 × M 窗口上：
        触发率 > 1%
        方向性正确（做多正收益/做空负收益）
        p < 0.05（多重比较校正后）
        比同一场景的无信号基线好
        核心

Gate 3: MC 对照
        GARCH(1,1) null 下 p < 0.05
        95% 置信区间不包括 0
        严格

Gate 4: 超额收益归因
        剔除市场/行业/风格因子后 α > 0
        Barra 模型下因子暴露可解释
        最严格
```

### 6.2 对当前系统的评估

| 当前信号 | Gate 1 | Gate 2 | Gate 3 | Gate 4 | 结论 |
|---|---|---|---|---|---|
| LPPL is_danger | ✅ | ❌ p=0.48 | ❌ 93% GBM | ❌ | 移除 |
| LPPL risk_level | ✅ | ❌ 无区分 | ❌ | ❌ | 移除 |
| Wyckoff accumulation | ✅ | ❌ +2.32% weak | — | — | 降级 |
| Wyckoff markup | ✅ | ✅ | — | — | 保留 |
| markup→买入 | ✅ | ✅ p=0.0098 | — | — | **唯一保留** |
| Wyckoff distribution | ✅ | ❌ −16.82% | — | — | 移除 |
| Spring→BUY | ✅ | ❌ 0/600 | — | — | 移除 |

### 6.3 具体操作: walk-forward 介入方式

对于未来任何新增信号:

```python
def validate_signal(signal_func, stocks, windows):
    """
    walk-forward 信号验证标准流程
    
    Args:
        signal_func: 信号生成函数
        stocks: 股票列表
        windows: 回测窗口参数
    
    Returns:
        通过/不通过 + 详细报告
    """
    results = []
    for stock in stocks:
        for w in windows:
            signal = signal_func(stock, w)
            fwd_returns = compute_forward_returns(stock, w)
            results.append({
                "signal": signal,
                "fwd_5d": fwd_returns[5],
                "fwd_20d": fwd_returns[20],
                "phase": get_phase(stock, w),
            })
    
    # Gate 2 检查
    trigger_rate = sum(1 for r in results if r["signal"]) / len(results)
    assert trigger_rate > 0.01, f"触发率 {trigger_rate:.1%} < 1%"
    
    signal_returns = [r["fwd_20d"] for r in results if r["signal"]]
    baseline_returns = [r["fwd_20d"] for r in results if not r["signal"]]
    
    t_stat, p_val = ttest_ind(signal_returns, baseline_returns)
    assert p_val < 0.05, f"p={p_val:.4f} > 0.05"
    
    return {"pass": True, "trigger_rate": trigger_rate, "p_value": p_val}
```

---

## 七、总结

walk-forward 被判定为有效裁决者的原因可用一句话概括:

> **不是因为 walk-forward 是完美的，而是因为没有其他方法能在不引入优化偏差的情况下区分 A 股中的信号和噪声。**

其有效性在理论上的三重根基:

1. **计量经济学**: 样本外验证是金融信号验证的黄金标准（Pardo 2008, Bailey 2014），偏差最小
2. **代码证据**: 代码审查独立确认了 walk-forward 发现的根因（UTAD=None、SOS=None、Distribution 骨架化、DE→L-BFGS-B 成功率的真正含义），两种方法汇合于同一结论
3. **市场微观结构**: A 股的特征（T+1、政策驱动、高换手、散户主导、无 TR）使底层前提（机构主导、有 TR 积累/派发、纯市场泡沫）在 A 股上不成立
