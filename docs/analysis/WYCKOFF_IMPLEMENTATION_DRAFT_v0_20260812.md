# Wyckoff 正确实现方案草案 v0 (2026-08-12) — 红蓝对抗输入

> 本文件为红蓝对抗的**输入草案**，非最终结论。对抗后输出定稿文件。
> 生成依据：4 路并行 subagent 实际代码审计（引擎/信号链/实证/外部实现对照）+ 本项目 60+ 篇证伪链研究。

## 一、审计关键事实（草案的事实基础）

1. **信号链三层绝缘**：引擎 `V3TradingPlan.direction`（engine.py:1588，含 accumulation 降档/markdown 禁多/涨跌停跳过/假突破惩罚）→ `_extract_from_report` 不提取（wyckoff_analysis_engine.py:48-158）→ `WyckoffOutput`（interfaces.py:403-476）**无 direction 字段** → `write_wyckoff` 不展平 → `_extract_wyckoff`（adapters.py:610-621）不取 → `WyckoffAdapter.adapt`（adapters.py:180-185）**用 phase∈{accumulation}/spring→BUY、phase∈{distribution}/utad→SELL**。
2. **比 phase→方向更严重**：默认配置 `use_research_data_pack: true` 下，RDPackWriter 只写 metadata（pack_writer.py:112-119），`_merge_decision_for_collection` 不展平（research_pipeline.py:574-575），`_extract_wyckoff` 顶层取不到 → **Wyckoff 信号在默认配置下根本不进入 TradingSignal 链**（已实证）。
3. **direction 唯一消费者**：`hands/strategies/wyckoff.py:61`（旧离线回测，非统一引擎链）；UI 展示（dashboard.py:1278）。实盘/统一回测路径零消费。
4. **死桩/死字段**：`_detect_sos`（engine.py:845-847）恒 None；`bypassed`、`vshape_detected` 恒 False；state/reporting/fusion/image/bayesian 未接线。
5. **实证结论（三窗复现）**：structure_score IC 符号翻转（−0.083/+0.032/−0.073）；accumulation 三窗负超额（−1.87/−1.37/−3.15）；distribution 正超额（+0.84/+0.77/+2.12，p 仅单样本 t 口径成立）；spring 生产引擎负（−1.44/−3.22）；leader∧distribution 动量残差剔尾后 2/3 窗归零；**markdown 三窗 3/3 负超额（−3.58/−1.23/−4.05）唯一稳健方向**；RS=leader 本质 20d 相对动量（relmom IC 自身符号不稳 +0.172/−0.078/+0.129）。
6. **生产引擎 vs 研究结论背离**：config 无 `distribution_leader_enabled`/`structural_adjust_enabled`，"引擎已降为叙事/风控层"的宣称当前不真。
7. **外部最佳实践**（casoon pine / YoungCan-Wang yc_engine）：ATR 相对化 minBreak+影线比例、Spring→Test→SOS 严格序列序、一字板守卫、量 95% 分位爆量、bias200 上限、门槛-样本幸存者偏差护栏。其中 ATR 相对化/一字板守卫与平台约束兼容，其余多数在"相位不作方向"约束下应弃或降为纯标注。

## 二、方案草案 v0（待对抗）

### P0-信号链修复（alpha 轴错位修复）
- **P0-1 direction 透传**：`WyckoffOutput` 增 `direction` 字段；`_extract_from_report` 提取 `result.trading_plan.direction`；`write_wyckoff`（RDP+legacy 两路）展平；`_extract_wyckoff` 读取。
- **P0-2 adapter 语义纠正**：`WyckoffAdapter.adapt` 改以 `direction` 优先：direction∈{做多,买入,轻仓试探} → BUY；∈{空仓观望,观察等待} → HOLD/None；**删除 phase∈accum/dist 直映射**。distribution 不再产出 SELL（禁做空）。
- **P0-3 RDP 信号丢失修复**：`_merge_decision_for_collection` 将 wyckoff 等 metadata 展平到顶层（或 collect 前 `wyckoff_output.to_dict()` 合并），恢复默认配置下信号产出。
- **P0-4 置信度门槛**：adapter 阈值从 `<0.3` 提升（D 级=0.3 现可过）或改为仅接受 direction 为做多/买入/轻仓试探 且 confidence 达标。

### P1-标注/风控增强（不改变方向结论，纯标注与守卫）
- **P1-1 ATR 相对化 + 影线比例**：`_scan_spring`/`_scan_utad` 增 `atr` 形参（_step3 已算 atr_series，engine.py:1077），`minBreak=max(atr*0.25, rangeWidth*2%)` + 影线≥0.25 分级（spring_quality/utad_quality），对齐外部实现且不硬删触发集。
- **P1-2 一字板守卫**：新增纯函数（对齐 yc `_is_frozen_board_day`:1052-1066），在 `_scan_spring`/`_scan_utad`/`_scan_false_breakout` 过滤一字板日（当日量价确认物理失真）。
- **P1-3 _detect_sos 死桩填充**：按 rangeProgress≥70% + 量比≥1.5 + 收阳实现，但**返回 UNKNOWN 候选 `sos_candidate`**（不驱动相位→方向）。
- **P1-4 门槛-样本反向护栏**：events.py detect_sos docstring 补"收紧门槛放大幸存者偏差"警示（yc:1438-1441 实证）。

### P2-实证验证回归门
- **P2-1 三窗回归**：新增实现后重扫三窗 as-of（wyckoff_full_scan.py），用 validate_ranking.py（升级：E2 中性化、E4 三口径 MWU/Welch/t、中位数、>0占比）+ momentum_residual_analysis.py 验证：①新 adapter 输出方向与引擎 direction 一致；②不引入新的相位→方向 alpha 幻觉。
- **P2-2 关键决策代码入仓**：`/tmp/opencode/mresid_robust.py`（R3 剔尾）与 `mom_control.py`（纯动量对照）入仓 scripts/，使 F7 证伪链可复现。
- **P2-3 config 对齐宣称**：落 `distribution_leader_enabled=false`、`structural_adjust_enabled`（或明确关闭）等开关，使"叙事/风控层"宣称在代码为真。

### 明确不做的（红蓝对抗重点攻击对象）
- ❌ bias200 作过滤器（砍掉唯一弱真信号 markup 追涨）
- ❌ 板块波动缩放（阈值已相对化；外部实证恶化样本）
- ❌ Spring→Test→SOS 序列序进入 structural_score（会经 _apply_structural_adjustment 间接改方向）
- ❌ 量 95% 分位作 SOS 硬门槛（幸存者偏差）
- ❌ LPS creek 作 lps_confirmed gate（改置信度→方向）

## 三、待对抗问题清单（红蓝各自攻击/辩护）
1. direction 优先 vs phase 兜底：distribution 状态在引擎=空仓观望，adapter 曾=SELL。改后 distribution 是否恒 HOLD？若用户已持仓 Wyckoff 分布式信号是否该给平仓提示？（决定是否需要 SELL-as-exit 而非 SELL-as-entry）
2. RDP 修复是否引入回归：展平 metadata 会否影响 CZSC/LPPL/Alpha/Regime 等其他引擎信号？
3. P0-4 置信度门槛定多少？B+（0.55？）vs A？会不会把唯一弱真信号（markup 追涨）也过滤掉？
4. P1-1 ATR 相对化是否会改变 spring→轻仓试探 的触发集分布（影响 direction 输出）？如何保证"不改变方向结论"可验证？
5. 死桩清理范围：_detect_sos 填 UNKNOWN 候选 vs 保持 None？state/reporting/fusion/image 是否本次清理？
6. P2 回归的样本与窗口局限（三窗同 2026 上半年同 regime）如何声明？
7. 是否有必要把 leader/relmom 接入 adapter（唯一正超额）？还是保持"Wyckoff 引擎完全不产方向"的纯粹叙事/风控定位？

## 四、交付物
- 定稿方案文档 `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md`（含红蓝对抗记录）
- AGENTS.md 同步