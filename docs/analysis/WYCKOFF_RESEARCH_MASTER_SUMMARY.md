# Wyckoff 模块研究全景汇总 — 2026-06 至 2026-08

> 定位：docs/ 下全部 Wyckoff 相关研究/分析/验证文档的**统一入口与结论链归档**。
> 范围：2026-06-27 早期研究 → 2026-08-11 动量残差终判，共 6 个研究阶段、60+ 篇文档。
> 方法论主线：**多窗口全量 as-of 回放 + 市场中性超额 + 红蓝对抗 + 右尾剔除/动量残差**逐层收紧，直至唯一幸存候选信号被证伪。
> 最终结论（一览）：**Wyckoff 相位在 A 股无独立正 alpha，方向合成层废弃；引擎降为叙事/风控层（markdown 闸、涨跌停、RR）；RS=leader 是唯一持续正超额信号但其本质 = 20d 相对动量因子。** 各阶段结论演进见 §6。

---

## 1. 文档清单与阶段分组

| 阶段 | 时间 | 主要文档目录 | 主题 |
|---|---|---|---|
| S1 早期研究 | 2026-06-27~29 | `docs/analysis/uniquant_wyckoff_*.md`、`wyckoff_*report/plan/roadmap`、`wyckoff_multitf_*` | V1→V2 修复、三周期(WSO/WSS/共振) 研究管线、回测否定 |
| S2 基线核查 | 2026-07-20 | `docs/reanalysis/` 全系列 + `wyckoff_architecture.md` | 系统级基线、引擎正确性审计 |
| S3 红蓝+Walk-Forward | 2026-07-24 | `docs/reanalysis/Z_*_20260724.md` 共 16 篇 | LPPL/Wyckoff 标准vs实现、walk-forward 终结诊断、参数敏感性 v2 |
| S4 Classic 合规 | 2026-08-02~03 | `WYCKOFF_*_2026080*.md`、`CLASSIC_WYCKOFF_*.md` | P0/P1 修复、Compliance 17%→58.3%、全量扫描基线 |
| S5 相位再平衡 | 2026-08-06 | `WYCKOFF_PHASE_REBALANCE_*.md`(v1/v2/v3/v3.1) | 覆盖层移除、方向反转诊断、研究vs生产对齐 |
| S6 方法论验证 | 2026-08-07 | `WYCKOFF_{VERIFICATION,SYSTEM_ASSESSMENT,METHODOLOGY_SETTING}_*` | 双窗验证、4 路评估、四层正交 |
| S7 对抗+残差终判 | 2026-08-09~11 | `WYCKOFF_{METHODOLOGY_ADVERSARY,FIX_OPTIMIZATION,FIX_REDBLUE,MOMENTUM_RESIDUAL}_20260809.md` | 12 路对抗+W3、leader∧dist 动量残差证伪 |

完整文件清单（含 100+ 篇，红色字母 WYCKOFF 前缀文件为主）见 §7。

---

## 2. S1 早期研究（2026-06-27~29）— 主张到回测否定

### 2.1 关键文档结论

| 文档 | 类型 | 核心结论 |
|---|---|---|
| `uniquant_wyckoff_feature_worklist.md` | 工作清单 | P&F 完全缺失（rg=0 匹配）、86,436 观测、1255 测试全过 |
| `uniquant_wyckoff_session_report_20260627.md` | 执行报告 | 5 大 Bug（Sharpe 年化 ~11×、SOS 过检 109.5%、WSO set 丢顺序）；WSS 436 序列重建；唯一 OOS 失败窗=2020 COVID V 反弹 |
| `wyckoff_correction_plan.md` | 修复方案 | 2,400 快照：UNKNOWN 39%、空仓观望 93.6%、LPS 0/423 spring、跑赢 BH≤24%；A 紧急修复(3天)必做 |
| `wyckoff_backtest_report.md` | 回测报告 | golden_100：BH +353% vs 最佳 v1 104%；转化率 2.2%；**"信号价值为零，结构性不可修复"** |
| `wyckoff_multitf_v3.md` | 验证设计 | 滚动截面 54,000 obs、markdown→accum α+4.5、净年化 12.8 vs BH 8.2、Sharpe 0.92 |
| `wyckoff_research_report.md` | 研究主报告 | 22,148 obs、WSO+WSS+共振 Sharpe 2.02、**卖出>买入（卖出胜率 66.65% vs 买入 46.59%）**、Spring +3.00% "最强单一事件" |

### 2.2 阶段状态

V1→V2 修复中期转折期：06-18 回测判"信号为零"→ 06-24 多周期 v2/v3 改方法 → 06-27 全流水线跑通（86,436 obs）重建乐观预期（Spring 最强、Sharpe 2.02）。
**关键反差先兆**：Spring "最强信号" 与 WSS 436 序列的两大乐观结论，正是 S7 被系统性证伪的对象。

---

## 3. S3 红蓝 + Walk-Forward（2026-07-24）— 理论信号从不触发

### 3.1 Walk-Forward 终结诊断结论链

| 层 | 结论 | 证据 |
|---|---|---|
| LPPL 模型层 | **零预测力** | 93% GBM 噪声拟合 R²>0.3；缺 b<0 / c>0.01 约束；tc 局部搜索→days_to_crash≡12 |
| Wyckoff 信号层 | **理论信号从不触发** | Spring→BUY 0/600、UTAD→SELL 0/600（`_detect_utad`/`_detect_sos` 是 `return None`）、Distribution 条件互斥 0/600 |
| 唯一有效信号 | **markup→"买入" +8.60% (p=0.0098)** | 但被 adapter 静音（不读 `trading_plan.direction`）；前 20d 已涨 +9.05% = 追涨非抄底 |
| 多重比较修正 | p_adj≈0.176 存疑 | 300+ 隐性组合 → 后经同相位复核转正（+1.91%, p=0.0022） |

### 3.2 标准 vs 实现核心 GAP

- **LPPL**：缺 4 大硬约束 + tc 局部搜索 + 非 VP → "曲线拟合非泡沫检测"。
- **Wyckoff**：相位 = MA 交叉/趋势% 冒充（markup=MA5>MA20+3%）；UTAD/SOS 死桩；Distribution 永假；把 A 股不存在的 TR 结构当主线。
- **信号链**：adapter 不读 direction → 唯一有效信号静音。
- **参数敏感性 v2**：W=120 唯一决定性（+3.94%, MW p=0.0000）、同相位对比唯一显著（markup 内 +1.91%, p=0.0022）、100% TR 检测率。

### 3.3 方向收敛

Wyckoff 从"预测引擎"→"标签 + 趋势延续信号"；LPPL 从生产移除。

---

## 4. S4 Classic 合规（2026-08-02~03）— 工程完备但认知错位

### 4.1 Compliance 演进（30 项口径）

```
07-24 框架基线 17% (6/35, 35项口径)
 P0 Phase1 PF-C1/C2/C3 (PnF): 20%→33.3%
 P0 Phase2 ES-C3/ES-C1/PH-C1/PH-C2: →48.3%
 P0 Phase3 CF-C4: →48.3% (P0 8/8 全 PASS)
 P1 CN-C4复权 →51.7% → SQ-C1结构分 →55.0% → RS-C1四分类 →58.3% ★
```

### 4.2 全量扫描基线（2026-08-02, WSS OFF）

- 5374 成功/8 too_short；归档 552 指数文件；175 非 A 股污染（8 只误入买入）
- 结构分 p25=58.66/p50=60.03/max=64.43 高度拥挤，**数学上限 65.7 < 70 阈值 = 结构性死路径**
- 置信度 D 84.1%、A 0；spring 66→0 买入（LPS 死链）
- 候选池 306 只中位盈亏比仅 1.05；WSS 训练产物从不被引擎加载

### 4.3 Classic 合规终态

58.3%（14P/7Pa/9F/30），9 FAIL 多为 GAP/WONTFIX（研究平台定位不符），非阻断。

---

## 5. S5 相位再平衡（2026-08-06）— 调阈值无效，方向反转是结构性问题

### 5.1 v1→v3.1 三次被证伪的演进

| 版本 | 主张 | 证伪证据 |
|---|---|---|
| v1 | P&F 对称化+积累收紧+前瞻化 | 新阈值 27K 验证 **99.9% unknown**；链式积累仅 0.4%（不是过松是过紧） |
| v2 | 阈值温和校准+检测器重新平衡 | 52K 观测仍 **99.8% unknown** → 删除全部 P&F 阈值修改 |
| v3/v3.1 | 收敛 3 项最小集 | **仅覆盖层移除有效**（accum 63.2%→0.6%）；markdown rp=0.15 约束（46.4%→11.4%）；市场状态自适应部分有效 |

### 5.2 研究管线 vs 生产引擎（~50% "对齐"实指生产=抛硬币）

| 维度 | 研究管线 | 生产引擎 |
|---|---|---|
| 相位判定 | 三周期独立+共振投票 | 单月线检测器链 winner-takes-all |
| 置信度 | WSS 连续评分、单调 | 3 值离散 84%D/0%A、负相关 |
| 实证 | t=10.24、多空跨距 +8.07%、Sharpe 2.02 | 理论一致性 **50%（=随机）** |
| 哲学 | 数据驱动 | 规则驱动 |

### 5.3 Python 可行性报告

**不重写**：4 大缺失组件 3 个有现成代码可复用（pnf.py/TR/events.py/sequence.py），增量 ~750 行/5.5 天 → 一致性预测 65-70%。即 FULL_OPTIMIZATION_PLAN 的 S0→S1→S2（9-14 天）。

---

## 6. S6-S7 方法论验证与终判（2026-08-07~11）— 唯一候选被证伪

### 6.1 双窗验证（2026-08-07, W1/W2 全量 as-of）

| 信号 | W1 (04-30) 超额 | W2 (03-31) 超额 | 判定 |
|---|---|---|---|
| **RS=leader** | +5.18% (p<0.001) | +2.12% (p=0.021) | ✅ 唯一双窗显著正 |
| markup | +3.16% | −0.41% | ⚠️ 符号不稳 |
| distribution | +0.84% | +0.77% | ⚠️ 反做空错 |
| **accumulation** | **−1.87%** | **−1.37%** | ❌ 稳定负 |
| **spring** | −1.44% | −3.22% | ❌ 无溢价 W2 显著负 |
| markdown | −3.58% | −1.23% | ✅ 唯一稳定方向→风控 |
| structural IC | −0.083 | +0.032 | ❌ 符号翻转、非排序器 |

### 6.2 方法论四层正交（2026-08-07 SETTING）

**状态≠方向≠排序**：Layer0 phase=叙事（markdown 唯一稳定负→风控闸）；Layer1 RS=leader 唯一 alpha 轴（开仓电子门）；Layer2 spring 仅 leader 池内触发；Layer3 结构分废弃当排序器。

### 6.3 12 路对抗 + W3（2026-08-09 ADVERSARY）

| 攻击面 | 结果 |
|---|---|
| leader×spring | ❌ W1 −5.57% / W2 −7.50%（spring 消解 alpha） |
| structure IC 三窗 | −0.083/+0.032/−0.073 符号翻转成立；leader 内高分反是劣势（8.00 vs 5.07） |
| 决策 DAG (phase∧leader) | ❌ W2 −1.39% / W3 −1.76%（phase 过滤淘汰 leader 好子集） |
| **leader×distribution 候选** | 三窗 **+5.85/+4.09/+9.07**, MWU p<0.01 全三窗 → 初判真信号（后被 6.4 证伪） |
| markdown | 3/3 负 = 唯一稳定风险方向 |

### 6.4 动量残差终判（2026-08-11, MOMENTUM_RESIDUAL）— 独立增量证伪

| 检验 | W1 | W2 | W3 | 结论 |
|---|---|---|---|---|
| M1 分位残差（控动量） | +1.84pp | +4.63pp | +0.91pp | 初看正 |
| M2 OLS残差 | +1.82pp | +4.34pp | +2.30pp | 初看正 |
| **R3 剔右尾后 M2** | +1.06pp (p=0.071) | **+0.01pp (p=0.96)** | **−0.24pp (p=0.76)** | ❌ **增量塌缩=右尾驱动** |
| R4 分位内符号 | 2/6 负 | 1/4 负 | 2/4 负 | 跨窗不一致=噪声 |
| R1 动量周期 40d | 正 | 正 | −0.96pp | 周期敏感非独立因子 |

**终判**：`leader∧distribution` 的正超额 = 20d 相对动量 beta + 少数右尾暴涨股运气。控制动量并剔右尾后 2/3 窗归零——作为 Wyckoff 相位的独立贡献**证伪**。

### 6.5 最终落地建议

- P0（distribution×leader 落地）不落地
- leader 若用应作**纯 20d 相对动量因子**（加极端值约束）
- Wyckoff 引擎降为**叙事/风控层**（markdown 闸、涨跌停、RR），从方向合成中移除相位/spring 独立开仓依据

---

## 7. 完整文档清单（docs/ 中 Wyckoff 相关）

### 7.1 docs/analysis/ 核心（近 60 篇）

```
S1 (06): uniquant_wyckoff_feature_worklist / uniquant_wyckoff_session_report_20260627
         wyckoff_correction_plan / wyckoff_backtest_report / wyckoff_step_verification_plan
         wyckoff_verification_design / wyckoff_verification_final_plan
         wyckoff_practical_implementation_roadmap / wyckoff_multitf_v3 / wyckoff_multitf_verification_plan
         wyckoff_multitf_verification_v2 / wyckoff_research_report / wyckoff_design_vs_implementation_gap_*
         ／基于Python架构的A股多周期威科夫可用性报告(.docx)
S2 (07): 00_architecture_map / 03_brain_engines / 05_signal_system / 07_risk_research_platform
S4 (08-02): WYCKOFF_AUDIT_REDBLUE_FINAL / WYCKOFF_IMPLEMENTATION_AUDIT / WYCKOFF_FULL_SCAN_ANALYSIS
         WYCKOFF_FULL_SCAN_REPORT / WYCKOFF_LPS_REFACTOR_DESIGN / WYCKOFF_OPTIMIZATION_EVALUATION
         WYCKOFF_OPTIMIZATION_TASKLIST / WYCKOFF_P0_P1_FIX_ANALYSIS
S4 (08-03): CLASSIC_WYCKOFF_COMPLIANCE_FRAMEWORK / CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1
         WYCKOFF_CLASSIC_REFACTOR_TASKLIST(_FINAL) / WYCKOFF_QUANT_TO_CLASSIC_ROADMAP
         WYCKOFF_MULTI_PERIOD_VALIDATION / CLASSIC_WYCKOFF_TDD_STANDARD_*　(6 篇)
S5 (08-06): WYCKOFF_V3_FULL_SCAN_ANALYSIS / WYCKOFF_PHASE_REBALANCE_IMPLEMENTATION_PLAN(_v2/v3/v3.1)
         WYCKOFF_PHASE_REBALANCE_REDBLUE / WYCKOFF_V3.1_CLASSIC_ALIGNMENT_EVALUATION
         WYCKOFF_RESEARCH_VS_PRODUCTION_COMPARISON / WYCKOFF_CLASSIC_PYTHON_FEASIBILITY_REPORT
         WYCKOFF_FEASIBILITY_VS_VALIDATION_CROSSCHECK / WYCKOFF_FULL_OPTIMIZATION_PLAN
S6 (08-07): WYCKOFF_WSS_SCAN_ANALYSIS / WYCKOFF_PLAN_RESEARCH / WYCKOFF_VERIFICATION_RED_BLUE
         WYCKOFF_SYSTEM_ASSESSMENT / WYCKOFF_METHODOLOGY_SETTING
S7 (08-09): WYCKOFF_METHODOLOGY_ADVERSARY / WYCKOFF_FIX_OPTIMIZATION / WYCKOFF_FIX_REDBLUE
         WYCKOFF_MOMENTUM_RESIDUAL
```

### 7.2 docs/reanalysis/ 关键（约 20 篇）

```
S2 (07-20): 00-09 全网审计系列 / wyckoff_architecture / Z_investigation_report / Z_tdd_redblue
          Z_red_blue_comprehensive / E_red_blue_analysis / I_live_system_map
S3 (07-24): Z_red_blue_lppl_wyckoff / Z_lppl_wyckoff_standard_vs_implementation_comparison
          Z_red_blue_plan_verification_(final/round2_wyckoff/round3_pnf_signal)
          Z_red_blue_reimplementation_(final/round2_wyckoff/round3_signalchain)
          Z_theory_practice_proposal / Z_walk_forward_theoretical_foundation
          Z_param_sweep_v1_redblue_round(1/2/3) / Z_param_sweep_v2_analysis_report
```

### 7.3 其他位置

- `docs/analysis/LPPL_WYCKOFF_IMPLEMENTATION_PLAN.md`（实施计划，被 S3 全盘否决）
- `docs/repair_plan_lppl_wyckoff.md`、`docs/repair_plan_phase6.md`
- `docs/reshaping_logs/02_lppl_wyckoff_activation.md`、`docs/reshaping_logs/10_walk_forward_results.md`
- `docs/archive/audit_logs/R1_raw/1C_wyckoff_czsc.md` 等历史归档
- 跨期提及：`docs/analysis/institutional/`、`docs/reanalysis/Wyckoff_LPPL_Factor_Pipeline_Verification_Report.md`

---

## 8. 结论链归档（一键跳转）

| 你想查 | 结论 | 报告 |
|---|---|---|
| 研究管线最强效果 | Sharpe 2.02、卖出>买入、OOS 卖出稳定 | `wyckoff_research_report.md` |
| LPPL 为何无效 | MC 93% GBM 噪声拟合、缺物理约束 | `Z_red_blue_lppl_wyckoff_20260724.md` |
| Walk-Forward 终结诊断 | 理论信号从不触发、唯一信号 silent | `Z_red_blue_reimplementation_*` + `Z_theory_practice_proposal` |
| Classic 合规进展 | 58.3%，P0 8/8 + P1 三项 | `CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_*.md` |
| 相位再平衡结论 | 覆盖层移除唯一有效、勿调阈值 | `WYCKOFF_PHASE_REBALANCE_REDBLUE.md` + `_v3.1` |
| 研究 vs 生产差距 | 生产一致性 50%=随机 vs 研究 Sharpe 2.02 | `WYCKOFF_RESEARCH_VS_PRODUCTION_COMPARISON.md` |
| 为什么优化全被证伪 | 结构分 IC 翻转、accum 负、spring 负、markdown 唯一稳定 | `WYCKOFF_VERIFICATION_RED_BLUE_20260807.md` |
| 方法论正交 | 状态≠方向≠排序、四层 | `WYCKOFF_METHODOLOGY_SETTING_20260807.md` |
| leader∧dist 证伪 | 动量残差+右尾剔除 2/3 窗归零 | `WYCKOFF_MOMENTUM_RESIDUAL_20260809.md` |
| 最终落地 | 引擎=叙事/风控层、leader=动量因子 | `WYCKOFF_FIX_REDBLUE_20260809.md` + `WYCKOFF_FIX_OPTIMIZATION_20260809.md` |