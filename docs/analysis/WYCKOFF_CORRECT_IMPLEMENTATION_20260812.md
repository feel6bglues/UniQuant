# Wyckoff 正确实现方案（定稿）— 红蓝对抗裁决 v1 (2026-08-12)

> 状态：定稿。输入草案 `WYCKOFF_IMPLEMENTATION_DRAFT_v0_20260812.md`，经 **3 路独立红蓝对抗**（引擎现实 / 实证证据 / 外部最佳实践）裁决后成稿。
> 结论一句话：**Wyckoff 引擎正确目标态 = 叙事 + 风控层，完全不产方向入场信号**。本方案把"相位→方向"的 alpha 轴错位从信号链根除，并把标注/风控质量对齐外部最佳实践，全程不引入新的方向主张。

---

## 一、对抗输入的事实基础（4 路代码审计核实，全部成立）

| # | 事实 | 证据 |
|---|---|---|
| F1 | `V3TradingPlan.direction`（含 accumulation 降档/markdown 禁多/涨跌停跳过/假突破惩罚）**从不进入信号链**：`_extract_from_report` 不提取（wyckoff_analysis_engine.py:48-158）→ `WyckoffOutput` 无 direction 字段（interfaces.py:403-476）→ 两 writer 不展平 → `_extract_wyckoff` 不读（adapters.py:610-621） | 三层绝缘 |
| F2 | `WyckoffAdapter.adapt` 用 `phase∈{accumulation}/spring→BUY、phase∈{distribution}/utad→SELL`（adapters.py:180-185）——**alpha 轴错位在信号出口** | 生产唯一 action 源 |
| F3 | **默认配置 `use_research_data_pack: true` 下 Wyckoff 信号整体不进入 TradingSignal 链**（RDP 只写 metadata，research_pipeline 不展平）——已实证 | pack_writer.py:112-119; research_pipeline.py:569-597 |
| F4 | direction 在统一回测/实盘路径**零消费者**；唯一消费是旧离线回测 hands/strategies/wyckoff.py:61 | — |
| F5 | 死桩 `_detect_sos` 恒 None（engine.py:845-847）；死字段 `bypassed`/`vshape_detected` 恒 False | — |
| F6 | **额外两处相位→方向残留**：`signal/normalizer.py:115-122` `_DIRECTION_MAP`（accum/spring→+1、dist/utad→−1）；`engine.py:2040-2051` `scan_signal` 自做 direction→BUY/SELL/HOLD（含永不触发的 SELL 关键词） | 三套映射 |
| F7 | 实证（三窗 + 动量残差 + 新增剔尾复核）：**全部六类信号（distribution/markdown/leader/accumulation/markup/spring）剔尾(|fwd|≤10%)后无一同号显著**。markdown 剔尾后 W1 −1.20(p=0.003)/W2 +0.00(ns)/W3 −0.94(p=0.024)；leader W2 剔尾翻为 −0.68(p=0.027)；distribution 剔尾后 +0.30/+0.13/+0.11 全 ns | 剔尾复核独立重算 |
| F8 | ConfidenceLevel 无 B+（B+ 已被结构性调整归一为 B，models.py:21-27）；float 映射全链统一 A=0.9/B=0.7/C=0.5/D=0.3 | 草案"B+=0.55"为幻影 |
| F9 | unified_engine SELL **仅 position>0 执行**（:420）= SELL 本身就是"只平仓"语义；arbitrator Priority 2 会让 Wyckoff SELL 无条件压掉 BUY（arbitrator.py:338-355） | Q1 裁决依据 |
| F10 | 三窗全在 2026 H1 同 regime（03-31/04-30/05-29），fwd 窗口重叠过半；但池均值 W1 −3.73/W2 +6.56/W3 −6.15（熊-牛-熊对照，仅"对照不足"非"无对照"）；2024-2025 数据可用（wyckoff_full_scan.py 支持任意 --as-of） | — |

---

## 二、最终裁决（P0 信号链根除 / P1 标注风控增强 / P2 验证 / 明确不做）

### P0 — 信号链根除相位→方向（最高优先）

| 项 | 裁决 | 具体方案 | 风险 |
|---|---|---|---|
| **P0-1 direction 透传** | ✅ 采纳 | `WyckoffOutput` 增 `direction:str=""` + to/from_dict；`_extract_from_report` 从**融合后** `report.trading_plan.direction`（含 MTF override，analysis.py:273-296）提取；RDP+legacy 两 writer 各加一行 `wyckoff_direction`；`_extract_wyckoff` 读该键（缺省 ""→None，旧缓存兼容） | 低（纯 plumbing） |
| **P0-2 adapter 语义纠正** | ✅ 采纳 | 以 direction 优先：∈{做多,买入,轻仓试探}→BUY；∈{持有,持有观察,观察等待,空仓观望,""}→None；**删除 phase/spring/utad 直映射**；**恒不产 SELL-as-entry**（F9）。metadata 保留 phase/spring/utad 供叙事。`test_adapters.py:136-212` 12 用例改写 | 中（旧测试钉住 bug） |
| **P0-3 RDP 信号恢复** | ⚠️ 修改后采纳 | **只展平 `wyckoff.to_dict()` 键**（禁止全量 metadata 展平——会连带复活 LPPL/CZSC/NTF/Alpha，LPPL 门槛仅 0.05 会全市场变样）。落 `research_pipeline.py:569-597` 或 `_extract_wyckoff` 内 RDP 感知 | 中-高（范围必须收窄） |
| **P0-4 置信度门槛** | ⚠️ 修改后采纳 | 门槛 0.30→**0.40**（滤纯 D 级噪声；F7：accumulation D 级三窗负超额），**主筛选靠 direction gate 而非置信**（F8：置信 IC 无排序力，filter≠rank）。**不得预设 0.5/0.7**（markup C 级弱真信号会被杀）；最终值由 P2-2 markup-only 存活率回归定 | 低-中 |
| **P0-5 关闭结构性调整通路** | ✅ 新增采纳 | `config` 落 `structural_adjust_enabled: false` 默认关闭——`_apply_structural_adjustment`（结构分→置信→方向，engine.py:111-147）在结构分 IC 三窗符号翻转（−0.083/+0.032/−0.073）+ leader 内高分劣势（低分 8.00 vs 高分 5.07）下**无依据改方向** | 低 |
| **P0-6 normalizer 残留抵销** | ✅ 新增采纳 | `signal/normalizer.py:115-122` `_DIRECTION_MAP` 全置 0（方向只来自外部 direction 字段）；`engine.py:2040-2051` `scan_signal` 映射与 P0-2 对齐（只 BUY/None，删 SELL 残影） | 低 |
| **P0-7 明确不做 SELL-as-exit** | ✅ 裁决 | adapter **不**为"空仓观望"产 SELL（F9：会经 Priority 2 压掉合法 BUY、且 distribution 剔尾后 ≈0 无做空/做多依据）。持仓退出由风险层承担（DecisionOutput FORCE_EXIT、LPPL Danger、NTF RESISTANCE）。markdown 风控已在引擎层实现（rule2 禁多 + direction 空仓 → 不发 BUY） | — |

### P1 — 标注/风控质量增强（纯标注，不改变方向结论）

| 项 | 裁决 | 具体方案 | 风险 |
|---|---|---|---|
| **P1-1 ATR 相对化 + 影线比例** | ⚠️ 修改后采纳 | 签名加 `atr: Optional[float]=None`（8 调用点+3 测试兼容，`test_phase2_events.py:205/261/273`）；`minBreak=max(atr*0.25, rangeWidth*2%)`（pine:265/279 对齐）+ 影线≥0.25 分级（spring_quality/utad_quality）。**触发集变化视为方向级改动**：P2-1 必须输出 before-after 对照，漂移>5% 撤回或升级为 P0 独立验证。链内调用不传 atr 回落 width-based 并记录分歧 | 中-高（触发集必变） |
| **P1-2 一字板守卫** | ✅ 采纳 | 纯函数对齐 yc `_is_frozen_board_day:1052-1066`（日振幅≤1% 且 |开-收|≤1%）；接入 `_scan_spring/_scan_utad/_scan_false_breakout` + rule6 测试日 + EVR 事件日（yc:1333 同例） | 低（只滤物理失真日） |
| **P1-3 _detect_sos 死桩** | ⚠️ 修改后采纳 | 按 rangeProgress≥70% + 量比≥1.5 + 收阳（pine:286-289）实现，**恒返回 UNKNOWN 候选 `sos_candidate`**（不驱动相位）；补 `_build_report` 描述映射（engine.py:1713-1722）；**护栏**：`sos_candidate` 不进入 WyckoffOutput 顶层 signal 字段，回归测试断言永不进 TradingSignal action/reason | 低-中（标签集扰动） |
| **P1-4 门槛-样本护栏** | ✅ 采纳 | `events.py detect_sos` docstring 补"收紧门槛放大幸存者偏差"警示（yc:1438-1441 实证：门槛越高留存样本胜率越低 22.2-29.1% vs 边际 28.9-38.0%） | 无 |
| **P1-5 EVR 增强** | ✅ 新增采纳 | `effort_result.py:17-49`（现 30 日窗口二值背离）升级为 pine 三态×5 档（CLIMAX/DIVERGENCE/CONFIRMATION，strength 65-90，pine:200-225）+ yc 位置语境（低位滞涨 vs 高位派发标注，yc:1280-1284）。进 `vdb_divergence` 档位化，纯标注 | 低 |
| **P1-6 图式失效规则** | ✅ 新增采纳 | invalidationFactor 0.33×区间宽越界 → 标"图式失效"（pine:41,771-779）；对症 accum↔dist 74 次互误已知缺陷（叙事卫生） | 低 |
| **P1-7 No Supply/No Demand/VDU** | ✅ 新增采纳 | 30 行纯标注（pine:320-327,1087-1094），支撑处 no-supply 作 spring 前提叙事 | 低 |
| **P1-8 eventCooldownBars** | ✅ 采纳（低优先） | 10-bar 冷却防同水平重复事件入列表（pine:650/710/717） | 低 |
| **P1-9 rangeScore 叙事面** | ⚠️ 采纳-限定 | range_quality 标注字段（时长 20-80b/宽度 1-5ATR/量缩/测试次数，pine:357-392）+ AVWAP；**严令不得回流 `_compute_structural_score`** | 低 |
| **P1-10 sequence 软标注** | ⚠️ 修改后采纳 | `sequence_state` = SPRING→pending TEST→confirmed 状态机（pine:677-689），**权重恒 0**，不进结构分、不接 direction | 低 |
| **P1-11 止损触发层** | ⚠️ 采纳-限位 | `StopLossResult`/`_build_report` 增 `exit_pending/exit_reason`：节后宽限期（跨≥3 自然日，yc:2600-2612）+ 缩量洗盘不触发（yc:2669-2674）+ 深度破位短路（yc:2656-2663）——**仅持仓退出建议**，不进 adapter entry SELL | 低 |
| **P1-12 bias200 风控标注** | ⚠️ 修改后采纳 | 过滤器**否决**（会砍唯一弱真信号 markup 追涨右尾）；吸收 yc `_leader_risk`"高乖离≥150% 观察"作风控注释字段（yc:1882-1892） | 低 |

### P2 — 实证验证回归门

| 项 | 裁决 | 具体方案 |
|---|---|---|
| **P2-1 老窗口补全** | ⚠️ 修改后采纳 | 必须补 **2025-06-30 + 2024-12-31** 两个全量 as-of 窗（各 ~10min/8workers，wyckoff_full_scan.py 支持）。若坚持不补，声明降级为"仅 2026 H1 相似环境"。显著性检验注明非独立 + 报告 fwd 重叠度（~50%） |
| **P2-2 三层验收门** | ⚠️ 修改后采纳 | (A) 确定性断言（非统计）：P0-2 映射表对三窗 CSV 全量断言 100% 匹配 + 0 SELL + BUY 数>0；(B) 经验回归：adapter BUY 集 20d 超额，**预注册阈值**（MWU p≥0.05 于 ≥2/3 窗）；(C) markup-only 置信度存活表（供 P0-4 定门槛） |
| **P2-3 BUY 集动量残差** | ✅ 新增采纳 | 新 BUY 集跑 `momentum_residual_analysis.py`（markup=追涨，前 20d +9.05%，与 leader∧dist 同机制）；剔尾后 2/3 窗归零则撤回 |
| **P2-4 证伪代码入仓** | ✅ 采纳 | `/tmp/opencode/mresid_robust.py`（R3 剔尾）、`mom_control.py`（纯动量对照）入仓 `scripts/` + ruff，使 F7 证伪链可复现 |
| **P2-5 golden baseline 对比门** | ✅ 新增采纳 | P0 落地是 Wyckoff 信号首次进入统一回测（现默认配置零信号）→ golden_20/100 前后对比（capture_baseline.py），非只靠三窗扫描 |

### 明确不做（红方攻击后维持否决）

- ❌ bias200 作过滤器（砍唯一弱真信号右尾；已改吸收为风控标注 P1-12）
- ❌ 板块波动缩放（平台阈值已相对化；yc:1073-1075 自证量比不缩放；仅若将来用 yc 式 EVR 绝对 pct 门需补）
- ❌ Spring→Test→SOS 序列序进 structural_score（会经 `_apply_structural_adjustment` 泄漏方向；序列序只作 P1-10 软标注权重 0）
- ❌ 量 95 分位作 SOS 硬门槛（幸存者偏差；相对量比≥1.5 即可）
- ❌ LPS creek 作 lps_confirmed gate（改置信度→方向；斜率只作叙事字段）
- ❌ leader/relmom 接入 adapter（六重证据全指向不可复制：W2 MWU 0.263、剔尾 W2 翻负 −0.68、relmom IC 翻转、跨窗重合 7.9-15.9%、leader∧dist 证伪、leader>0 占比 42-53%）
- ❌ 研究管线 Sharpe 2.02 融合（建立在已证伪卖出侧/spring 上，显式废弃）
- ❌ state/reporting/fusion/image/bayesian 本次清理（不参与方向合成，留专项）
- ❌ compression / trend_pullback 原型（新增两个 alpha 幻觉入口）

---

## 三、实施顺序（依赖关系）

1. **P2-4 证伪代码入仓**（最便宜，先做）→ 2. **P0-1/2/6**（信号链根除，核心）→ 3. **P0-3**（RDP 恢复，需 golden baseline 门同步）→ 4. **P0-4/5/7**（门槛/结构分关闭/SELL 语义）→ 5. **P2-1/2/3/5**（回归验证，P0 验收门）→ 6. **P1-1/2/3**（标注增强，trigger 集变更走 before-after 对照）→ 7. **P1-4~P1-12**（纯标注，随插随补）→ 8. AGENTS.md 同步

## 四、验收红线

- P0-3 展平**范围**与 P1-1 触发集漂移是本方案仅有的两处可能"修出更大 bug"的改动：前者靠 wyckoff-only 展平、后者靠 before-after 对照表 + 撤回预案。
- 任何"剔尾后 2/3 窗仍显著"的发现才允许把某标签升为方向依据；当前证据下 Wyckoff 引擎**只做叙事与风控**。

## 五、附：红蓝对抗记录摘要

- **对抗①引擎现实**：裁决 direction 透传可行（低风险 plumbing）；SELL-as-exit 否决（unified_engine SELL=只平仓语义 + Priority 2 误压）；RDP 展平必须收窄 wyckoff-only；P1-1 签名必须 `Optional` 默认值；新增 normalizer/scan_signal 两处残留清理；删除 B+=0.55 幻影。
- **对抗②实证**：新证据（剔尾复核）——**全部六类信号剔尾后无一同号显著**，markdown/leader 的"稳健"表述过强、distribution 禁做空依据从"显著正"降为"≈0 无依据"；P2 必须补 2024/2025 老窗 + 预注册验收阈值；P0-4 门槛提升需 A/B 证明收益中性（不得静音 markup）；关闭 `_apply_structural_adjustment`；BUY 集跑动量残差；废弃研究管线 2.02 融合。
- **对抗③外部实践**：补 3 处结构性遗漏（EVR 增强 P1-5、图式失效 P1-6、NoSupply P1-7）+ 止损触发层 P1-11；二分法过度修正——序列序/bias200 走"软标注/风控注释"档位（P1-10/P1-12）而非非带即弃；板块缩放/95分位/creek gate 维持否决。
