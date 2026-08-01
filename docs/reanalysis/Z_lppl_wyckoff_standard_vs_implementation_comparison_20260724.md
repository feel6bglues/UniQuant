# LPPL & Wyckoff: 标准理论 vs 本项目实现 — 完整对比分析

> **日期**: 2026-07-24  
> **方法**: 互联网研究（Sornette 2003, Fantazzini 2011, Wyckoff Analytics, 学术综述）+ 源代码逐行比对
> **范围**: LPPL 引擎 1107 行 + Wyckoff 引擎 1616 行 + 信号适配器 620 行

---

## 一、LPPL 标准模型 vs 本项目

### 1.1 标准 Sornette LPPL (2003) 规范

**公式**: `f(t) = a + b(tc-t)^m + c(tc-t)^m · cos(ω·log(tc-t)+φ)`

**四个不可违背的物理约束**（Sornette 2003, Fantazzini 2011, Shu & Song 2024 综述）：

| 约束 | 意义 | 标准值 | 违反后果 |
|---|---|---|---|
| **m ∈ (0,1)** | 临界指数：价格趋近奇点时呈超指数增长 | (0.01, 0.99) | m>1 → 增长减速，不是泡沫 |
| **b < 0** | **线性项必须为负**：加速增长的充要条件 | (-∞, 0) | b>0 → 减速/震荡/均值回复，无奇点 |
| **|c| > 0.01** | 对数周期振荡必须有实际振幅 | (0.01, ∞) | c≈0 → cos 项无意义，无周期泡沫结构 |
| **tc 全局搜索** | 奇点时间必须在整个可行域内搜索 | [0, T+window] | 局部搜索 → 错过长周期泡沫结构 |

**学术工业界标准实践**：

| 维度 | 标准做法 | 来源 |
|---|---|---|
| 优化方法 | **变量投影 (Variable Projection)**：3 个非线性参数 (tc, m, ω) 用 L-BFGS-B，4 个线性参数解析求解 | ETH 金融危机观测站, Fantazzini 2011 |
| 初始点 | 50-200 个初始点，tc 在 [t_early, t_end+100] 均匀分布 | QuantConnect LPPLS 研究 |
| 泡沫验证 | **Monte Carlo p-value** vs 同长度 GBM 模拟 | Shu & Song 2024 综述 |
| R² 用途 | 仅供参考，**不作为泡沫可信度指标** | Sornette et al. 多次指出 |
| 适用场景 | 长历史宏观泡沫（1987、2000 互联网），数月至数年窗口 | 学术文献共识 |
| 个股短窗 | 效果有限，信噪比不足 | QuantConnect 回测: 最大回撤 51.7%, PSR 12.5% |

**ETH 金融危机观测站 (Financial Crisis Observatory)** 生产级 LPPL 管线：
1. 多窗口扫描（500-1000 天滑动窗口）
2. 对每个窗口执行 VP + L-BFGS-B + 50+ 初始点
3. 计算 LPPLS 置信度指标（基于 MC 模拟）
4. 输出：气泡状态指示器 + 崩溃风险概率
5. **不自作主张预测崩盘日期**，只输出相对风险

### 1.2 本项目 LPPL 实现 (`src/uniquant/brain/lppl/engine.py`)

| 维度 | 标准要求 | 项目状态 | 偏差细节 | 后果 |
|---|---|---|---|---|
| m bounds | (0,1) | ✅ (0.1, 0.9) | 轻微收窄可接受 | 无重大问题 |
| w bounds | 自由但不宣过高 | ✅ (6, 13) | 合理范围 | 无重大问题 |
| **b < 0** | **必须为负** | ❌ 无约束 | `engine.py:144-148` 纯 RMSE，无惩罚项 | **拟合任何加速/减速/震荡数据** |
| **c > 0.01** | **必须有振幅** | ❌ 无约束 | `engine.py:396-430` `calculate_risk_level` 不检查 c | cos 项可能 ≈0，模型退化 |
| **tc 搜索** | 全局 [0, T+100] | ❌ [T+3, T+20] | `engine.py:317-328` 10 个初始点 tc 全部在 3-20 天内 | **days_to_crash ≡ 12** |
| 优化方法 | VP + L-BFGS-B | ⚠️ 纯 L-BFGS-B | 7 参数全部数值优化，不是 VP | 精度较低，收敛更慢 |
| 初始点数 | 50-200 | ❌ 10 | 仅 10 个 | 局部最优 |
| 线性参数 | 解析求解 | ❌ 数值优化 | a,b,c1,c2 用 L-BFGS-B 算 | 多 4 维搜索空间 |
| R² 用途 | 仅供参考 | ❌ 作为泡沫指标 | `r2_threshold=0.5` → is_danger | **93% GBM 随机数据达到该阈值** |
| 模型验证 | MC p-value | ❌ 无 | 无 | **无法区分信号 vs 噪声** |
| 风险等级 | 相对概率 | ❌ 5 级绝对分类 | `calculate_risk_level` 只用 days_left+R² | 仅 3/5 级出现，无区分度 |
| 双 API 路径 | — | ❌ 不可比 | `detect_bubble` vs `scan_all_windows` 无协调 | 同一数据两个结果，无法仲裁 |

### 1.3 关键源码证据

```python
# engine.py:144-148 — 纯 RMSE，无 b<0/c>0.01 约束
def cost_function(params, t_data, log_price):
    tc, m, w, a, b, c, phi = params
    fitted = lppl_func(t_data, tc, m, w, a, b, c, phi)
    return float(np.sqrt(np.mean((fitted - log_price) ** 2)))
```

```python
# engine.py:317-328 — 10 初始点 tc 全部在 3-20 天
initial_guesses = [
    [current_t + 5, 0.5, w_mid, ...],   # tc=5
    [current_t + 10, 0.4, w_hi*0.85, ...],
    [current_t + 15, 0.6, w_lo*1.3, ...],
    # ... 全部 tc 在 [3,20] ...
]
```

```python
# engine.py:368-373 — is_danger 不检查 b 和 c
is_danger = (
    (m_bounds[0] < m < m_bounds[1])        # m ✅
    and (w_bounds[0] < w < w_bounds[1])    # w ✅
    and classify_top_phase(...) == "danger" # days+R²
    and r_squared > 0
)  # ❌ 不检查 b<0, 不检查 |c|>0.01
```

---

## 二、Wyckoff 标准分析法 vs 本项目

### 2.1 标准 Wyckoff 方法 (Wyckoff Analytics 权威文献)

**三大法则**：

| 法则 | 内容 | 分析方法 |
|---|---|---|
| **供求法则** | 价格由供求决定 | 价格 + 成交量对照分析 |
| **因果法则** | P&F 横向计数 = 因，后续趋势 = 果 | P&F 点数图测量 Cause |
| **努力 vs 结果** | 成交量与价格背离 → 转折预警 | 放量滞涨/缩量下跌判定吸筹派发 |

**五步流程**：

```
Step 1: 判定大盘趋势 → 决定做多/做空/空仓
Step 2: 选出与大盘同步/更强的个股
Step 3: P&F 计数 → Cause ≥ 最小目标
Step 4: 九项买入/卖出测试 → 启动确认
Step 5: 市场转折点择时 → 设置止损
```

**交易区间 A-E 五阶段结构**（关键！项目完全没有）：

| 相位 | 积累 (Accumulation) | 派发 (Distribution) |
|---|---|---|
| **Phase A** | PS → SC → AR → ST（TR 形成） | PSY → BC → AR → ST（TR 形成） |
| **Phase B** | 多次 ST 积累 Cause（数周-月） | SOW + LPSY 派发 Cause（数周-月） |
| **Phase C** | Spring / 测试（可选） | UT / UTAD（可选） |
| **Phase D** | SOS → LPS（突破确认） | 破 TR 支撑 |
| **Phase E** | Markup（趋势展开） | Markdown（趋势展开） |

**关键结构要求**：
- Spring 和 UTAD 都是**可选的**（不是必须的）— 标准提供两种 Accumulation 示意图（带/不带 Spring）
- **成交量是核心指标**：SC 天量、ST 缩量、SOS 放量确认、LPS 缩量
- P&F 点数图是 Wyckoff **独有的 Cause 计量工具**
- 九项买入/卖出测试**每项必须满足**才能入场（含 P&F 目标、盈亏比≥3:1）

### 2.2 本项目 Wyckoff 实现 (`src/uniquant/brain/wyckoff/engine.py`)

| 维度 | 标准 Wyckoff | 项目实现 | 偏差本质 |
|---|---|---|---|
| **相位检测** | 成交量价差 + TR 结构 | MA 金叉/死叉 + 趋势% | ❌ 动量冒充 Wyckoff |
| **Accumulation** | 需求吸收供应，价跌量缩→放量→缩量 | prior_trend < -3% + TR 内 | ⚠️ 看跌后横盘=积累 |
| **Markup** | SOS + LPS 确认突破 | MA5 > MA20 + 趋势>3% | ❌ 均线突破=金叉 |
| **Distribution** | 供应耗尽需求，价涨量缩→放量→缩量 | is_in_TR + prior_trend > 5% | ❌ 条件互斥，永远不触发 |
| **Markdown** | 破 TR + LPSY | MA5 < MA20 + 跌>5% | ❌ 死叉 |
| **UTAD** | 派发 TR 内假突破 | `return None` | ❌ 空函数死代码 |
| **Spring** | TR Phase C 测试，可选 | `boundary_lower > 0` 必须存在 | ❌ 趋势中无 TR 边界 |
| **SOS** | 量价齐升突破 TR | `close > boundary_upper*0.95 + 量能` | ⚠️ 弱版突破检测 |
| **LPS** | SOS 后缩量回调 | 仅耦合 Spring 路径 | ⚠️ |
| **置信度** | — | Spring+LPS 为门控 | ❌ 结构上限 C 级 |
| **信号输出** | BUY/SELL/HOLD | 不读 `trading_plan.direction` | ❌ 唯一信号被静音 |
| **交易计划** | 做多/做空/空仓 | 91% 空仓观望 | ❌ 超保守 |
| **P&F 计数** | Cause 计量 | 不存在 | ❌ |
| **九项测试** | 入场确认 | 不存在 | ❌ |
| **A-E 结构** | 五阶段 TR 分析 | 单层 if/else | ❌ |
| **成交量分析** | 核心指标 | 仅 Step2 中有部分证据加权 | ❌ 非主判定路径 |

### 2.3 关键源码证据

```python
# engine.py:404-407 — Distribution 只有一行逻辑
def _detect_distribution(self, df, ctx, rule0):
    if ctx["is_in_trading_range"] and ctx["prior_trend_pct"] > 0.05:
        return {"phase": WyckoffPhase.DISTRIBUTION}
    return None
# is_in_trading_range 要求 total_range_pct <= 0.20 AND abs(short_trend) < 0.05
# → 股票在窄幅波动（<5%）的同时 prior 必须 >5% → 互斥 → 0/600 触发
```

```python
# engine.py:379-402 — Markup = MA 金叉
def _detect_markup(self, df, ctx, rule0):
    if st >= 0.03 and (cp > ma20 and ma5 >= ma20):
        return {"phase": WyckoffPhase.MARKUP}
# 任何短线上涨 3% + MA5 > MA20 = markup，无 Wyckoff 结构
```

```python
# engine.py:472-473 — UTAD 是空函数
def _detect_utad(self, df, ctx, rule0):
    """Detect UTAD (Upthrust After Distribution) pattern."""
    return None

# engine.py:476-477 — SOS 也是空函数
def _detect_sos(self, df, ctx, rule0):
    return None
```

```python
# adapters.py:159-177 — 适配器不读 trading_plan.direction
def adapt(self, raw_output, symbol, timestamp, default_shares=100):
    phase = raw_output.get("wyckoff_phase", "unknown")
    confidence = float(raw_output.get("wyckoff_confidence", 0.0))
    spring = raw_output.get("wyckoff_spring", False)
    utad = raw_output.get("wyckoff_utad", False)
    # 从未读取：raw_output.get("trading_plan", {}).get("direction")
    if phase == "unknown" or confidence < 0.3:
        return None  # 39% 直接在这里被过滤
```

---

## 三、项目 Moonshot vs. 标准可行性

| 项目声称的效果 | 标准理论实际能力 |
|---|---|
| LPPL 预测个股崩盘日期 | LPPL 输出宏观泡沫相对风险概率，不自作主张预测具体日期 |
| LPPL 5 级风险分类 | LPPL 输出 0-1 连续概率，无硬分类 |
| Wyckoff 在 120 天窗口检测四相位 | Wyckoff TR 形成需数周-数月，120 天窗口不够 |
| Wyckoff Spring → BUY 信号 | Spring 是 TR 形成后的可选 Phase C 测试，非必须 | 
| Wyckoff UTAD → SELL 信号 | 同上 |
| Wyckoff 置信度 A/B+/B/C/D 分级 | 标准 Wyckoff 无置信度分级系统 |

---

## 四、实证数据验证

项目已执行的 walk-forward 回测（500 只 × 6 窗口 = 2999 观测）：

| 信号 | 触发率 | fwd_20d | 统计显著性 | 真实性 |
|---|---|---|---|---|
| LPPL "高危" | 88/600 (14.7%) | +4.77% | p=0.96 ❌ | 噪声 |
| LPPL is_danger | 66/600 (11.0%) | +3.94% | p=0.48 ❌ | 噪声 |
| Wyckoff "买入" (markup) | 27/600 (4.5%) | +13.33% | p=0.0098 ✅ | **真实但罕见** |
| Wyckoff Spring→BUY | 0/600 (0.0%) | — | — | 结构上不可能 |
| Wyckoff UTAD→SELL | 0/600 (0.0%) | — | — | 死代码 |
| Wyckoff Distribution 相位 | 0/600 (0.0%) | — | — | 条件互斥 |

---

## 五、建议

1. **LPPL**: 当前实现不可修复需从零重写。如保留：b<0 + c>0.01 约束强制、VP 优化、MC p-value 验证、移除 days_to_crash 预测。但在 A 股 120 天窗口信噪比不足，建议移除。
2. **Wyckoff 适配器**: 最小修复暴露 `trading_plan.direction` 为适配器主信号。2-3 小时。
3. **Wyckoff "买入" 信号**: 提取为独立趋势延续指标。需要 Monte Carlo 基准验证 p 值。
4. **Wyckoff Phase A-E 结构**: 当前无 → 需从零构建。
5. **UTAD 死代码**: 删除或实现。
6. **Spring 依赖解耦**: 置信度系统不应以 Spring 为唯一门控。

---

*参考来源: Sornette (2003) "Why Stock Markets Crash", Fantazzini (2011) "Everything You Always Wanted to Know about LPPL", Shu & Song (2024) "Detection of financial bubbles using LPPLS model", Wyckoff Analytics — Wyckoff Method official documentation, QuantConnect LPPLS research backtest.*
