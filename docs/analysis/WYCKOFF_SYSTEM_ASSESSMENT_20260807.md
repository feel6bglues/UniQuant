# Wyckoff 分析：真实实现程度判定 + 差距分析 + 实际超额收益

> 方法：4 路并行 subagent（引擎代码审计 / 经典理论合规 docs / 差距审计 docs / 实证超额数据），再独立交叉验证关键数字。
> 日期：2026-08-07。

---

## 一、真实实现程度判定（代码审计，引擎代码逐函数核实）

### 1.1 结论：**约 75% 完整实现，非 stub**

Wyckoff 经典九步在 `src/uniquant/brain/wyckoff/engine.py`（2104 行，27 文件）**全部接通可调用**，无一 `NotImplemented/pass`。逐步成熟度：

| 步 | 函数 | 实现度 | 备注 |
|---|---|---|---|
| Step0 BC/TR 扫描 | `_step0_bc_tr_scan`+`_scan_bc_sc` | **完整** | 向量化 BC/SC 打分 + P&F 密集区覆盖 |
| Step1 大观/相位 | `_step1_phase_determine`+7 检测器链 | **完整**（1 死桩） | `_detect_sos` 恒 None（SOS 被内联重写） |
| Step2 努力结果 VDB | `_step2_effort_result` | **完整** | 量额/缩量推升/VDB 分歧 |
| Step3 Spring/UTAD/T+1 | `_step3_phase_c_t1`+`_scan_spring/utad` | **完整** | P0 已修 |
| Step3.5 反事实 | `_step35_counterfactual` | **部分** | 只有 `len(evidence)*2.0` 计数，无强度/仿真 |
| Step4 盈亏比 | `_step4_risk_reward` | **完整** | RR 阈值 2.5/1.5 多目标源 + ATR |
| Step5 交易计划 | `_step5_trading_plan` | **完整** | MVP markup / accumulation 降档 / 假突破 gate |
| 报告构建 | `_build_report` | **完整** | 全字段 |
| Answer 面校验 | `_apply_a_stock_rules` | **部分** | 只 rule2，其余重复进 step5 |

### 1.2 四个软肋（真正缺陷）

1. **`_detect_sos` 死桩**（engine.py:845-847 恒 None）——SOS 在 step3 内联重写，命名检测器名存实亡（ES-C4 通过是"SOS rate under limit"另算的）。
2. **B+/enum 不一致**：`_calc_confidence` 产字符串 `"B+"`，而 `ConfidenceLevel` enum 仅 A/B/C/D，靠 `_apply_structural_adjustment` 折成 B 兜底（已修 runtime，但类型不自洽，抽到一个真实 bug）。
3. **3.5 反事实弱**：计数法无强度窗口（CF-C1 FAIL 正是此）。
4. **`BASE_AMPLIFICATION=5.0` 放大 hack**：`_compute_structural_score`（engine.py:164-198）放大 ±0.1 的 WSO base 造分布（span 2.4→10.8）——但**放大分布≠放大预测力**（见 §三实证）。

### 1.3 大量硬编码 magic numbers
虽有 `config.wyckoff.calibration`，但 pnf box 0.02/2.0、BC/SC 打分 0.8/0.6/0.05、markdown 0.85/0.9/0.75、RR 2.5/1.5/1.2、BASE 5.0、相位 ±0.20/-0.10、WSS blend 0.3/0.7 **仍硬编码**（约 30 处）。

## 二、文档差距分析（设计意图 vs 实际）

### 2.1 三套差距口径（必须分清）

| 口径 | 基准 | 结论 |
|---|---|---|
| June 差距审计 | 设计文档 | 当时 8 项核心 0%（P&F/事件/WSS/共振）— **现多已修复**，且 08-02 审计宣布其"严重过时" |
| Aug 合规审计 | 经典 Wyckoff 理论 | **58.3% (14P/7Pa/9F/30)** |
| 研究 vs 生产 | 统计验证的研究管线 | **生产引擎 ≈50% 理论对齐**（ROADMAP 语），研究管线 Sharpe 2.02 |

### 2.2 9 项合规 FAIL（58.3% 的缺口）

| 项 | 维度 | 判定类型 | 性质 |
|---|---|---|---|
| PF-C5 | P&F | GAP | P&F 全量重建，无增量 O(1) |
| VS-C1 | 量能 | GAP | events.py 硬编码 magic 阈值 |
| VS-C3 | 量能 | GAP | 无买卖盘方向拆分 |
| MT-C2 | 多周期 | GAP | resonance 无 R²/IC 提升证据 |
| RS-C2 | 相对强弱 | GAP | ChipAnalysis 未接入置信矩阵 |
| CF-C1 | 反事实 | GAP | 无相位自适应窗口 |
| CN-C1 | A股 | GAP | box_size 无板块区分 |
| CN-C2 | A股 | TRADE‑OFF FAIL | T+1 只算不强制 |
| CN-C3 | A股 | GAP | P&F 不查涨跌停 |

绝大多数是 **GAP（WONTFIX：研究平台定位）或 TRADE-OFF**，非 ERROR → **不构成生产阻断**。

### 2.3 理论经文 vs 实证修正（最关键的差距）

文档（经典 Wyckoff + `wyckoff_research_report`）与实证矛盾点，已在 §三 用双窗口验证：

| 理论主张 | 双窗口实证 | 裁决 |
|---|---|---|
| accumulation 蓄势→涨 | **超额 −1.87/−1.37** | ❌ A股均值回归，理论被证伪 |
| distribution 见顶→跌 | **超额 +0.84/+0.77** | ❌ 反做空错 |
| Spring 是最强买入信号 | **超额 −1.44/−3.22** | ❌ 无 premium，反而偏弱 |
| SOS/买+共振最稳 | —（研究管线 2.02 Sharpe） | ⚠️ 与生产引擎不同步 |

## 三、实际超额收益（双窗口市场中性，交叉验证一致）

### 3.1 信号级超额（20d，减全池均值）

| 信号 | W1 (04-30) 超额 | W2 (03-31) 超额 | 判定 |
|---|---|---|---|
| **RS=leader** | **+5.18%** (p<0.001) | **+2.12%** (p=0.021) | ✅ 唯一双窗显著正 |
| markup | +3.16% (p=0.004) | −0.41% (ns) | ⚠️ 符号不稳 |
| distribution | +0.84% (p=0.043) | +0.77% (p=0.015) | ⚠️ 小正，反做空错 |
| **accumulation** | **−1.87%** (p<0.001) | **−1.37%** (p=0.002) | ❌ 稳定负 |
| **spring= True** | −1.44% (ns) | **−3.22%** (p=0.006) | ❌ 无溢价，W2 显著负 |
| markdown | −3.58% (p<0.001) | −1.23% (p=0.016) | ✅ 方向确认（风控） |
| structural IC | **−0.083** (p<0.001) | **+0.032** (p=0.029) | ❌ 符号翻转，非排序器 |

### 3.2 组合级（20d 年化 ≈×√13）

| 池 | W1 Sharpe | W2 Sharpe |
|---|---|---|
| 全池（市场中性，每窗口定义=0） | 0 | 0 |
| **leader 池** | **0.76** | 0.39 |
| accumulation 池 | −0.44 | −0.36 |

### 3.3 一句话

> **真正持续产生正市场中性超额的唯一信号是 `RS=leader`（均值 +3.7%/20d，Sharpe ~0.61）。** accumulation/spring 是稳定负；distribution 反做空错；结构分不可当排序器。

## 四、综合判定 + 行动清单

### 4.1 实现程度总评
- **工程量级**：九步 + 事件库(7) + P&F + 共振 + WSS + RS 四分类 + 结构分 + A股铁律 —— **体系完整度高（~75%）**，非从零 stub。
- **方法论级**：**与经典理论对齐度 58.3%（合规）**，生产引擎对研究管线的实证对齐 ≈50% → 引擎把"相位标签当方向用"，导致 accumulation/distribution/spring 三大信号跑出负/反超额。
- 结论：**"实现完备但认知错位"** —— 代码多、真信号少。

### 4.2 累计落地价值（2026-08 修复项）重判
| 已落地 | 此轮实证 | 修正 |
|---|---|---|
| P0-1/2 Spring 传导 | spring 超额为负 | 传"轻仓试探"方向对，但 spring 本身无 alpha，应配合 leader |
| P1-2 结构分放大 | IC 符号翻转 | **放大无效（仅造分布）——排序器立场废** |
| WSS 启用 | 结构分布提升 | 提升分布不提升方向（已知） |
| P2-1 共振标注 | 只标注不反向 | 符合"不反向信号"设计 |
| **§六 降档** | accum 超额负 | **方向正确**（降 neg-alpha 的等例）；leader 未接入交易方向为 `gap` |

### 4.3 行动清单（按优先级）
1. **P0：把 RSS 接入交易方向 gate**（当前 only 降级，非 gate）——唯一正 alpha。
2. **P1：accumulation/spring 降档已落地，进一步" spring 仅在 leader 内放大"**（报告 §六已提，未做）。
3. **P1：结构分废弃当排序器，改监督/百分位**（不提高 IC 的 5× 放大保留）。
4. **P2：补 `_detect_sos` 或删死桩** + CF-3.5 强度窗口 + 硬编码 → config。
5. **P2：研究管线（2.02 Sharpe） vs 生产（~50%）的融合** —— 最大未兑现价值。

## 附：证据文件
- `results/wyckoff_xs/wyckoff_scan_all.csv`、`results/wyckoff_xs2/wyckoff_scan_all.csv`（实证）
- `docs/analysis/WYCKOFF_PLAN_RESEARCH_20260807.md`、`WYCKOFF_VERIFICATION_RED_BLUE_20260807.md`、`WYCKOFF_FULL_SCAN_ANALYSIS_20260807.md`