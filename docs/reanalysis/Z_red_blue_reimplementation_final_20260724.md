# LPPL & Wyckoff 红蓝对抗 — 最终裁决 + 实施路线图

> **日期**: 2026-07-24  
> **基于**: 3 轮红蓝对抗 × 15 项声明 + Walk-forward 实证 2999 观察 + Monte Carlo 1000 次 GBM 模拟  
> **状态**: 🔴 Red 胜出 11/15, 🔵 Blue 胜出 3/15, ⚖️ Split 1/15

---

## 一、最终裁决

### LPPL 裁决

| 议题 | 裁决 | 关键证据 |
|---|---|---|
| 个股 120d 预测力 | ❌ **零预测力** | 93% GBM R²>0.3; is_danger p=0.48 |
| 加 b<0/c>0.01 约束修复 | ⚠️ **理论上可但实际需 MC 验证** | 约束后收敛率急剧下降 |
| VP 优化改善 | ✅ **必须实施** | Filimonov & Sornette (2013) 标准 |
| MC p-value | ✅ **必要但不实时** | 需预计算查表 |
| 最佳用途 | **指数/行业 ETF 泡沫风险指标** | 非个股交易信号 |
| 生产管线 | **❌ 移除** | 当前代码生产零价值 |

### Wyckoff 裁决

| 议题 | 裁决 | 关键证据 |
|---|---|---|
| 相位检测 | ❌ **MA 金叉/死叉冒充** | markup=趋势>3%+MA5>MA20 |
| Spring 门控 | ❌ **降级为可选事件** | 标准提供无 Spring 积累示意图 |
| UTAD | ❌ **删除死代码** | `return None` + 另有一版需 Distribution |
| Distribution 相位 | ❌ **移除 — 120d 窗口不可检测** | 0/600 触发; 条件互斥 |
| Markup"买入" (Test/Shakeout) | ✅ **真实信号, p=0.0098** | +8.60% 20d spread, 88.9% win rate |
| 置信度系统 | ❌ **重构为分层贝叶斯** | 当前 Spring 门控结构上限 C 级 |
| 最佳用途 | **趋势延续系统** | 非相位预测系统 |

### 信号链裁决

| 议题 | 裁决 | 工作量 |
|---|---|---|
| Adapter 暴露 trading_plan | ✅ **立即修复** | **2h** |
| LPPL 从仲裁器移除 | ✅ **立即修复** | **1h** |
| 仲裁器三层稀疏性 | ✅ **执行** | **3h** |
| MC 验证管线 | ✅ **执行** | **6h** |

---

## 二、实施路线图

```
Week 1: 紧急修复（确定收益，低风险）
─────────────────────────────────────
```

### 任务 1: WyckoffAdapter 重写（2h）

**文件**: `src/uniquant/signal/adapters.py`  
**核心变更**:

```python
# 当前（有问题的版本）
if phase == "unknown" or confidence < 0.3:
    return None  # 静音了所有信号
if spring or phase in _BULLISH_PHASES:
    action = "BUY"   # 从不触发
elif utad or phase in _BEARISH_PHASES:
    action = "SELL"  # 从不触发

# 新版本
trading_plan = raw_output.get("trading_plan", {})
direction = trading_plan.get("direction", "空仓观望")
action = DIRECTION_MAP.get(direction, "HOLD")
# 方向分级: "买入"→BUY_WEAK (50%仓位), "做多"→BUY (100%)
```

**风险**: 低 — 适配器当前输出 0 信号，任何 >0 的输出都是改善  

---

### 任务 2: LPPL 从仲裁器移除（1h）

**文件**: `src/uniquant/signal/arbitrator.py`, `src/uniquant/services/analysis_service_v2.py`  
**方式**: LPPL 信号输出标记为 `signal_source="lppl_research"`，仲裁器过滤非生产信号源  
**验证**: 仲裁器测试更新 — 确认 LPPL 信号不参与 BUY/SELL 裁决  

---

### 任务 3: UTAD 死代码 + Spring 降级（2h）

**文件**: `src/uniquant/brain/wyckoff/engine.py`

**变更**:
- `_detect_utad()`: 删除空函数（`engine.py:471-473`）
- `_step3_phase_c_t1()`: 删除 UTAD 调用分支（`engine.py:735-743`）
- `_calc_confidence()`: 移除 Spring+LPS 门控（`engine.py:926-983`），改用多维度加权
- `_step5_trading_plan()`: Accumulation 路径移除 Spring 依赖

**Spring 降级逻辑**:
```
当前: Spring → LPS → 置信度 A/B+/C → 做多/买入/空仓观望
新:   [SOS → LPS → 突破确认] OR [Spring → LPS → Spring确认]
      两条路径对等，都不依赖对方
```

---

```
Week 2: 架构改善（需要设计，中等风险）
─────────────────────────────────────
```

### 任务 4: 仲裁器三层稀疏性处理（3h）

**文件**: `src/uniquant/signal/arbitrator.py`

**三层结构**:
```
层 1: 多引擎共识 (≥2 BUY) → FULL, confidence=0.8
层 2: 单源信号 (如 Wyckoff"买入") → BUY_WEAK, 50% 仓位
层 3: 无信号 → HOLD, confidence=0.0
```

**变更**: 当前仲裁器假定多数时间有信号→重构为假定多数时间无信号

---

### 任务 5: Monte Carlo 验证框架（6h）

**新文件**: `src/uniquant/services/mc_validator.py`  
**集成**: `src/uniquant/services/engine_factory.py`

**功能**:
- 引擎注册时要求 MC 签名
- 预计算 GBM null 分布表
- Wyckoff "买入"信号 MC 验证（GBM 1000 次 × 120 天）
- 输出：信号是否为噪声（p 值评估）

---

```
Week 3+: 研究项目（需要独立验证，不确定收益）
─────────────────────────────────────
```

### 任务 6: Wyckoff "买入" MC 验证（4h）

**独立脚本**: `scripts/validate_wyckoff_buy_signal.py`

- 1000 次 GBM 模拟 × 100 只股票 × 6 窗口 = 600,000 个假市场
- 运行 Wyckoff 引擎 → 检查是否产生"买入"信号
- 计算 null 分布收益率 → 定位真实 +8.60% 的 p 值（多重比较校正后）

---

### 任务 7: LPPL v2 指数级（可选，2-3 周）

**不依赖现有代码** — 从零实现：

| 组件 | 方案 |
|---|---|
| 优化 | VP: 3 非线性 (tc, m, w) + 4 线性 OLS |
| 约束 | b<0 惩罚 + |c|>0.01 惩罚 |
| 初始点 | 100 个, tc ∈ [0, T+100] 拉丁超立方采样 |
| 目标 | 沪深 300 / 中证 500 / 行业 ETF |
| 窗口 | 500-1000 天 |
| 验证 | MC p-value 查表 |
| 输出 | 泡沫概率 p ∈ [0,1], 不输出 days_to_crash |

---

## 三、不做事项

| 事项 | 原因 |
|---|---|
| LPPL 个股级别重写 | 120d 信噪比不足，MC 已证明 |
| Wyckoff 完全相位系统重写 | 成本 >40h，收益不确定 |
| Distribution 相位实现 | 120d 窗口不可检测，无实证基础 |
| P&F 点数图实现 | 维护成本高，自动化困难 |
| Wyckoff 九项测试全实现 | 过于主观，不适合自动交易 |

---

## 四、成功标准

| 指标 | 当前 | 目标 | 衡量方法 |
|---|---|---|---|
| Wyckoff BUY 信号触发率 | 0/600 (0%) | >20/600 (>3%) | 适配器输出计数 |
| Wyckoff SELL 信号触发率 | 0/600 (0%) | 0/600 (0%)* | 适配器输出计数 |
| LPPL 仲裁器干扰 | 活跃 | 已移除 | 确认不参与仲裁 |
| 仲裁器"无信号"正确率 | 未定义 | 100% | 测试仲裁器三层输出 |
| Wyckoff"买入"MC p 值 | 未测量 | <0.05 或标记为待定 | MC 验证框架 |

*\*Wyckoff 不生产空头信号 — 依赖外部引擎*

---

## 五、文件清单

| 文件 | 操作 | 估算行数变化 |
|---|---|---|
| `src/uniquant/signal/adapters.py` | 修改 WyckoffAdapter | ±30 行 |
| `src/uniquant/signal/arbitrator.py` | 三层稀疏性仲裁 | ±80 行 |
| `src/uniquant/brain/wyckoff/engine.py` | UTAD 删除 + Spring 降级 + 置信度重构 | -50/+100 行 |
| `src/uniquant/services/mc_validator.py` | 新文件 | +200 行 |
| `src/uniquant/services/engine_factory.py` | MC 集成 | ±30 行 |
| `src/uniquant/services/analysis_service_v2.py` | LPPL 信号标记 | ±10 行 |
| `scripts/validate_wyckoff_buy_signal.py` | 新文件 | +300 行 |

**总计**: ~+500 / -50 行净增（绝大部分为 MC 验证框架 + Wyckoff MC 验证脚本）

---

## 六、三 Round 对抗统计

| Round | Claims | Blue Win | Red Win | Split |
|---|---|---|---|---|
| R1: LPPL | 4 | 2 | 1 | 1 |
| R2: Wyckoff | 6 | 0 | 5 | 1 |
| R3: 信号链 | 5 | 1 | 4 | 0 |
| **总计** | **15** | **3** | **10** | **2** |

**主导原则**: 🔴 实用主义获胜 — 在 A 股 120 天窗口的约束下，简化、验证、移除噪声比完美理论更重要。

---

## 七、参考文献

1. Sornette (2003) *Why Stock Markets Crash* — LPPL 四个约束条件
2. Filimonov & Sornette (2013) *A stable and robust calibration scheme for the LPPL model* — 变量投影标准
3. Fantazzini (2011) *Everything You Always Wanted to Know about LPPL* — 全面综述
4. Shu & Song (2024) *Detection of financial bubbles using LPPLS model* — MC p-value 验证方法
5. Wyckoff Analytics — *The Wyckoff Method* — 官方教程（含两种积累示意图）
6. QuantConnect (2023) — *LPPLS for Bubbles in Speculative Markets* — 回测实证（51.7% MDD, 12.5% PSR）
7. ETH Financial Crisis Observatory — *LPPLS Bubble & Crash-Risk Signals* — 生产级 LPPL 管线设计
8. 本项目 walk-forward 回测结果 — `scripts/output/walk_forward_definitive_report.json`
9. 本项目红蓝对抗分析 — `docs/reanalysis/Z_red_blue_lppl_wyckoff_20260724.md`
