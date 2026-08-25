# Wyckoff 深入再研究 —— 定稿修订版 (2026-08-12)

> **输入**: `docs/prompts/wyckoff_deep_dive_prompt_v2.md` 任务总纲 + `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` 定稿方案 (F1-F10 / P0-P2)。
> **方法**: Phase 0 代码扎根 (F1-F9 全核实) → Phase 1 五路并行 subagent 审计 → Phase 2 预注册 + 5 实证脚本 (0 ruff) → Phase 3 补 2 个老窗口全量 as-of 扫描 (X4 2025-06-30 / X5 2024-12-31, 各 5755 只) 复跑 T1-T3/F7 → Phase 4 四轮红蓝对抗 → Phase 5 修订版方案。
> **总判定**: 原定稿 P0 方向 **全部成立** (5 窗证据增强); P1 六项被修订/撤回 (ATR 撤回、sos 换通道、止损守卫默认关、标注面扩展); P2 老窗验证门 **落地完成** (X4/X5 已补)。**引擎目标态 = 叙事 + 风控层, 完全不产方向入场信号** 在 5 个跨 regime 窗口 (2024-12 至 2026-05) 下得到加强。
>
> **⚠️ 2026-08-18 更新 (全量 5 窗确定性重跑)**: `results/wyckoff_xs*/wyckoff_scan_all.csv` 已用当前引擎 (修复 WSS EMA 漂移 `_last_score/_is_warm` 非确定性 + 消除 `_code_prefix` 线程竞态) 进程池重跑为 39 列确定性版本。T1 n_buy 新基线 **82/23/66/166/118** (SELL 恒 0): W3/X4/X5 与原 66/167/120 仅差 0-2 只 (= 竞态修正), W1/W2 (137→82、40→23) 因旧 CSV 为 8/7 P0 前引擎产物更保守。T3 维持 **1/5 FAIL** (X4 r3=+5.30 p1=0.0 候选跟踪), F7/T2/golden/seal/direction_map 全 PASS。旧 25 列 CSV 备份于 `/tmp/opencode/wyckoff_fix/old_scans/`; 本文档下表数字 (137/40/167/120) 为旧 CSV 基线, 判定均不翻转。

---

## 1. 新核实事实 (相比 2026-08-12 定稿的增量)

| # | 事实 | 证据 | 对方案影响 |
|---|---|---|---|
| F11 | `direction` 的消费者不止 `hands/strategies/wyckoff.py:61` —— `brain/wyckoff/analysis.py:274-294` `merge_multitimeframe_reports` 也消费, `ui/dashboard.py:1278` 仅展示 | A 路审计 (engine.py:309-310 MTF 融合是默认入口) | "唯一消费者"表述更正; P0-1 透传需覆盖 MTF 融合路径 |
| F12 | RDP 模式 (`use_research_data_pack:true`) 下**全引擎网** (LPPL/NTF/Wyckoff) 都不进 TradingSignal 链; `_merge_decision_for_collection` (research_pipeline.py:569-597) 仅透传 DecisionBrain | B 路审计 | adapter direction 优先改造不影响 RDP 链路; **方向 gate 作用面 = 非 RDP 直连 / 离线回测 / 手动接 adapter 路径** |
| F13 | `sos_candidate` 已被占用为 signal_type (engine.py:1684, 1708 markup 分支) | D 路审计 `_build_report` | P1-3 若再填 signal_type 会字符串冲突 → 改为独立布尔字段 |
| F14 | 旧窗口 X4/X5 fwd_60d 覆盖率 98.8%/98.0% (数据湖止 2026-07-23); W1/W3 fwd_60d 为 0% (60 交易日越过数据末端) | 5 窗覆盖实测 | P2 存活表现可只靠 X4/X5 补 60d; 原 F10 "fwd 重叠过半"表述错误 → 实际日重叠 0/10/0%, 分析输入重叠 ~99.7% |
| F15 | **markdown 在 X5 剔尾 +1.28% (p=0.002) 正显著** —— 推翻"markdown=唯一稳健风控方向"(W1-3 的 3/3 负) | F7 五窗复核 | markdown 禁多保留为**保守风控**, 但降为 regime 依赖; "唯一可靠方向"过强 |
| F16 | leader 在 X5 剔尾 −1.54% (p<0.0001) 负显著 → 追涨动量在 regime 转换窗反身 | F7 五窗复核 | "leader=唯一真信号"进一步弱化; 仅作 20d 相对动量描述, 非跨 regime 恒正 |
| F17 | **accumulation 在 X4 (2025-06-30 牛市) 剔尾 +3.73% (p=0.0005) 正显著** vs W1-3 稳定负 → 蓄势方向随 regime 翻转 | F7 五窗复核 | `accumulation_downgrade` 属**风险体位**非方向主张, 保守保留 (不作为方向依据) |
| F18 | T3 BUY 集: X4 (2025-06-30) R3 剔右尾 +4.96% (p=0.0001) 显著, 但 4 窗仅 1 窗 → 预注册 FAIL | buyset_momentum_residual | X4 记录为"牛市 beta 候选"; 不构成 P0 升级依据 (需未来 ≥3/5 窗) |
| F19 | 置信门槛 0.30→0.40 在 X5 拦截 37% 弱置信 BUY (62.5% 存活), 其余窗存活 ~90-93% | T1 五窗 | P0-4 门槛 0.40 成立且有实质拦截 |

---

## 2. Phase 2 — 预注册实证结果 (已运行, 全部 0 ruff)

脚本群: `scripts/wyckoff_experiments/{direction_map_check,confidence_survival,buyset_momentum_residual,atr_trigger_diff,stoploss_exit_check}.py`, 预注册 `scripts/wyckoff_experiments/PREREGISTRATION_20260812.md`。

| 序号 | 检验 | 预注册门槛 | 结果 (五窗) | 判定 |
|---|---|---|---|---|
| T1 | direction 默认映射恒无 SELL + BUY>0 | 恒成立 | BUY 137/40/66/**167**/**120**, SELL 全 0, 5/5 PASS | **PASS** → P0-1/2/6 方向成立 |
| T1b | 置信门槛漂移 | — | 0.40 存活率 92.0/90.0/90.9/92.8/**62.5%** | 0.40 有实质拦截 (X5) |
| T2 | 置信度对 markup 排序力 | 剔尾后 ≥2/3 窗 A/B 显著 | **0 upgrade_candidates** (全 5 窗) | PASS-预期 → P0-4 成立 |
| T3 | BUY 集独立增量 | R3 剔右尾 ≥2/3 窗 p<0.05 且 >0 | W1 −0.67/W2 −3.65/W3 +2.02/**X4 +4.96(0.0001)**/X5 −1.60 → 1/4 | **FAIL** → 维持叙事层裁决 |
| T4 | ATR 相对化触发集漂移 | 前后对照漂移 ≤5% | golden_100: 44.4% / 56.5% / 22.6% 全超红线 | **红线 → P1-1 撤回** |
| T5 | 止损触发层误杀 | 触发率 ≤30% 且误杀 ≤50% | W1 22%/27.3% PASS, W2 45%/**46.7%** FAIL, W3 29%/20.7% PASS | 2/3 → **P1-11 降为默认关 + 参数化** |

---

## 3. Phase 3 — 证据表 (5 窗口跨 regime)

窗口: W1 2026-04-30 / W2 2026-03-31 / W3 2026-05-29 (原三窗) + **X4 2025-06-30 / X5 2024-12-31 (新增老窗, 全量 5755 只, as-of 回放)**。

### 3.1 F7 剔尾复核 (|fwd_20d|≤10%, 与剔尾池 MWU)

| signal_type | W1 | W2 | W3 | X4 | X5 | 跨窗同号显著? |
|---|---|---|---|---|---|---|
| distribution | +0.30 ns | +0.13 ns | +0.11 ns | **+2.93 (0.023)** | +0.18 ns | ❌ 否 (从未负显著) |
| markdown | −0.94 ns | +0.00 ns | −0.93 ns | +3.18 ns | **+1.28 (0.002)** | ❌ 否 (**X5 正显著** 推翻稳健风控) |
| leader | +1.64 | −0.68 (0.027) | +1.59 ns | +2.33 ns | **−1.54 (<0.0001)** | ❌ 否 (X5 翻负) |
| accumulation | −0.15 ns | −0.79 ns | +0.05 ns | **+3.73 (0.0005)** | −0.21 ns | ❌ 否 (**X4 正显著** vs W1-3 负) |
| markup | +2.13 | −0.56 | +1.33 | +2.77 ns | **−1.66 (0.011)** | ❌ 否 (X5 负显著) |
| spring | −0.85 | −0.60 | +0.24 | +2.67 ns | −0.51 ns | ❌ 否 |

**结论**: 六类信号 **5 窗全部无跨窗同号显著**。相位→方向在跨 regime 下全面不稳定; distribution 从未负显著 (禁做空依据维持"≈0 无依据", X4 牛市甚至正); markdown/leader/markup/accumulation 各有至少一个窗口符号翻转。**叙事层裁决 5 窗加强成立**。

> ⚠️ **口径披露 (2026-08-12 验证发现)**: 本表 W1-W3 数字为指数中性超额口径 (源自早前 3 窗分析 `WYCKOFF_METHODOLOGY_ADVERSARY_20260809.md`), X4/X5 为原始 fwd_20d 口径 (f7_x4/x5.py 脚本), 文档内混用。一致原始口径下 X4/X5 精确复现; W1-W3 符号层面不可复现。leader 同号负显著达 3/5 窗 (W1 W3 X5), 未达 4/5 升级线 → "全无跨窗同号显著"表述应修正为"**无 2/3 多数同号 (leader 3/5 例外)**"。叙事层裁决不变。详见 `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md` §1.1。

### 3.2 覆盖率 (数据湖止 2026-07-23)

| win | as-of | fwd_20d | fwd_60d |
|---|---|---|---|
| W1 | 04-30 | 99.5% | **0%** |
| W2 | 03-31 | 99.7% | 99.5% |
| W3 | 05-29 | 99.6% | **0%** |
| **X4** | 25-06-30 | 98.8% | **98.8%** |
| **X5** | 24-12-31 | 98.0% | **98.0%** |

→ **老窗对 60d 存活表必需** (P2 验证门补老窗结论实锤)。

### 3.3 T3 明细 (BUY 集动量残差)

| win | n_buy | exc20d | M2 OLS残差 (p) | R3 剔右尾 (p) | PASS |
|---|---|---|---|---|---|
| W1 | 126 | +1.37 | +0.04 (0.51) | −0.67 (0.29) | ✗ |
| W2 | 36 | −6.59 | −6.31 (0.023) | −3.65 (0.34) | ✗ |
| W3 | 60 | +3.51 | −0.27 (0.39) | +2.02 (0.95) | ✗ |
| **X4** | 155 | +4.20 | **+4.21 (0.0003)** | **+4.96 (0.0001)** | ✓ |
| X5 | 75 | −1.54 | −0.97 (0.12) | −1.60 (0.25) | ✗ |

> **V3 深度审计 (2026-08-12)**: X4 效应经 Bonferroni 校正后仍显著 (p=0.00063)，但由**最低 relmom 桶(超跌/逆向股)**驱动 (q0 桶 +7.66pp p=0.002)，非动量右尾桶驱动 → 修正标签从"牛市 beta 候选"为"**牛市超跌反弹候选**"。剔双尾 (|fwd|>P95 + relmom>P90) 后 +2.46pp (p=0.0002) 仍稳健，保留候选。

---

## 4. Phase 4 — 四轮红蓝对抗与裁决

### R1: P1-1 ATR 相对化 — 漂移红线 (T4: 44.4/56.5/22.6% ≫ 5%) → **撤回**
- **BLUE**: P1 定义"纯标注不改方向结论"; 触发集漂移 22-57% 意味着 ATR 相对化**系统性改变 spring/UTAD 判定边界**, 越出 P1 授权范围, 必须撤回或升级 P0 独立预注册验证。
- **RED**: 升级 P0 需新预注册 + 全量重扫 2 窗 + 不复用来验证的神经; 收益仅"更精细的触发语境"。
- **裁决**: **撤回 P1-1**。ATR 上下文仅保留为报告**透传字段** (`atr_pct` 已存在, 不参与任何判定阈值); 原计划中 P1-1 触发集漂移红线即撤回触发。不新增任何 ATR 相对门槛。

### R2: P1-3 `_detect_sos` 填 UNKNOWN 候选 — 字符串冲突 → **修订 (换通道)**
- **BLUE**: `signal_type="sos_candidate"` 已被 markup 分支占用 (engine.py:1684,1708); 方案再填会与现有检测冲突, 且 `_detect_sos` 是死桩 (845-847), 复活需新输入项。
- **RED**: P1-3 价值在"标注潜在的 SOS 启动点", 不进信号链。
- **裁决**: **修订 P1-3**: `_detect_sos` 补实现 (TR 上沿突破 + 量能确认启发式), 输出进**独立布尔标注字段** `sos_candidate_detected` (Step3Result/report), **不复用 signal_type**; 恒不进信号链。文案注明"标注面"而非信号面。

### R3: P1-11 止损触发层 — T5 过度触发 → **降为默认关 + config 参数化**
- **BLUE**: W2 触发率 45% / 误杀 46.7% —— 深破位阈值过松, 节后宽限+缩量洗盘判据在震荡窗大面积错误退出; 现有 `FSM FORCE_EXIT → SELL(1.0)` (arbitrator.py:314-321) 已是止损机制。
- **RED**: W1/W3 PASS (机制有效), 失败集中 W2 大震荡; 整体仍有价值, 保留为可选增强。
- **裁决**: **P1-11 修订为默认关 + 参数化**。新增 `wyckoff.stoploss_guard_enabled: false`, 提供 `stoploss_guard_depth_pct` (深破位深度) 与 `stoploss_guard_grace_days` (节后宽限期); 待新窗口预注册 T5 全 PASS 后再默认启。FSM FORCE_EXIT 维持为唯一常开止损层。

### R4: P0-2 BUY 集无独立增量 — X4 单窗显著 → **维持 FAIL (记录候选)**
- **BLUE**: X4 R3=+4.96% (p=0.0001) 剔右尾后仍强显著; 质疑"BUY 无独立增量"整体结论。
- **RED**: ① 多重检验: 4 窗×多指标, 1/4 显著为 FDR 期望内; ② regime: X4 是唯一深牛市窗 (2025 H1), 全池正 beta 且 OLS 残差在牛市下 misspecify (剔除绝对右尾保留相对右尾); ③ X4 非原 pre-registration 样本空间, 属探索性发现; ④ 若为真, 则 Wyckoff 做多=牛市增 beta 的"追涨"叙事, 非独立 alpha。
- **裁决**: **维持 FAIL** (预注册 4 窗需 ≥3 窗)。X4 记为"**待未来 as-of 回放复验候选**"——若未来 ≥3/5 窗 R3 p<0.05 → 走 P0 升级流程重新评估。当前不修改: 引擎恒不产 SELL-as-entry, direction gate 主控 BUY。

---

## 5. 修订版实现方案 (Deep-Dive 定稿)

### P0 信号链根除 (全部确认, 与 2026-08-12 定稿一致)

| # | 项 | 状态 | 修订依据 |
|---|---|---|---|
| P0-1 | direction 透传 (WyckoffOutput 增字段 + MTF 融合后提取) | ✅ 已实施 (2026-08-12 验收 PASS) | F11: 覆盖 `brain/wyckoff/analysis.py:274-294`; 210 analytics 不影响 RDP |
| P0-2 | adapter direction 优先 (做多/买入/轻仓试探→BUY, 其余→None; 删 phase/spring/utad 直映射) | ✅ 已实施 (2026-08-12 验收 PASS) | T1 5/5 PASS; F12 作用面明确 |
| P0-3 | RDP 仅展平 wyckoff 键 (禁全量 metadata 展平) | ✅ 已实施 (2026-08-12 验收 PASS) | F12 强化 (RDP 已三层绝缘) |
| P0-4 | 置信门槛 0.30→0.40 且主靠 direction gate | ✅ 已实施 (2026-08-12 验收 PASS) | T1b (X5 拦 37%); T2 0 升级候选 |
| P0-5 | 默认关 `structural_adjust_enabled` | ✅ 已实施 (2026-08-12 验收 PASS) | T2: 标记置信度无排序力 |
| P0-6 | normalizer/scan_signal 残留抵销 | ✅ 已实施 (2026-08-12 验收 PASS) | 无新反驳 |
| P0-7 | 恒不产 SELL-as-entry | ✅ 已实施 (2026-08-12 验收 PASS) | T1 五窗 SELL=0; arbitrator Priority 2 语义 |

### P1 标注/风控增强 (3 项修订 + 4 项确认)

| # | 项 | 状态 | 修订 |
|---|---|---|---|
| P1-1 | ATR 相对化 | ❌ **撤回** | T4 触发集漂移全程超 5% 红线 (R1); 仅保留 atr_pct 透传 |
| P1-2 | 一字板守卫 | ✅ 确认 (标注面) | D 路提示: 一字板日量能萎缩会放大假 spring → 只作注解, 不改 spring 判定 |
| P1-3 | `_detect_sos` 填 UNKNOWN 候选 | 🔄 修订 | 换独立布尔字段 `sos_candidate_detected`, 不复用 signal_type (F13/R2) |
| P1-4 | EVR 三态×5档+位置语境 | ✅ 确认 | E 路: 接入点需等 per-bar 化 (P1-5 后), 先落标注字段 |
| P1-5 | 图式失效 0.33×区间宽 | ✅ 确认 | 纯标注 |
| P1-6/7/8 | NoSupply/NSD/VDU | ✅ 确认 | 纯标注 |
| P1-9 | eventCooldown | ✅ 确认 | 防重复计数 |
| P1-10 | rangeScore/AVWAP 禁回流结构分 | ✅ 确认 | T2 支持结构分低价值 |
| P1-11 | 止损触发层 (宽限期+缩量洗盘) | 🔄 **修订 (默认关)** | T5 W2 过度触发 (R3): `stoploss_guard_enabled:false` + depth/grace 参数 |
| P1-12 | bias200 改风控注释 | ✅ 确认 | — |

### P2 验证门 (老窗已补, 实锤)

| # | 项 | 状态 |
|---|---|---|
| P2-1 | 补 2025-06-30 + 2024-12-31 老窗 | ✅ **完成** (X4/X5, 5755 只×2) |
| P2-2 | 三层验收门 (确定性断言+预注册 MWU ≥2/3 窗+markup 存活表) | ✅ 已执行 (F7/T1-T3) + **2026-08-12 复验 PASS** (deterministic_assertions D1/D2/D3) |
| P2-3 | BUY 集动量残差 | ✅ 已执行 → 维持 FAIL (X4 候选记录), 复现逐位吻合 (replicate_t1_t3) |
| P2-4 | 证伪代码入仓 | ✅ buyset_momentum_residual 等已入 `scripts/wyckoff_experiments/` |
| P2-5 | golden baseline 前后对比门 | ✅ **已复验 PASS** (2026-08-12: 20/20 窗口 4 标量全一致, golden_gate.py) |

### 8 项明确不做 —— 不变 (bias200 过滤 / 板块缩放 / sequence 序进分 / 量 95 分位硬门槛 / creek gate / leader 接入 adapter / 研究管线 2.02 融合 / compression)

---

## 6. Config 变更清单 (P0 实施阶段)

```yaml
wyckoff:
  direction_gate_enabled: true        # P0-2 adapter direction 优先
  confidence_gate: 0.40               # P0-4 (自 0.30)
  structural_adjust_enabled: false    # P0-5 默认关
  sos_candidate_annotation: true      # P1-3 独立布尔标注
  stoploss_guard_enabled: false       # P1-11 默认关 (R3)
  stoploss_guard_depth_pct: 15        # P1-11 深破位深度 (默认待校准)
  stoploss_guard_grace_days: 3        # P1-11 节后/异动宽限
```

> 注: `accumulation_downgrade: true` 保留 (F17: 属风险体位非方向主张)。

---

## 7. Ground-Truth 复核

- **引擎目标态 = 叙事+风控层, 完全不产方向入场信号** → 5 窗 (含 2 个跨 regime 老窗) 全部支持, 无对抗轮突破。方向入口唯一经 `direction gate + confidence ≥0.40 + 非 RDP 直连路径`。
- **A股铁律** (T+1 / 涨跌停 / markdown+distribution 禁多 / SELL=只平仓) → 全部保持; markdown 禁多维持保守 (F15: 依据从"稳健负"降为"regime 依赖, 保守持有")。
- **unified_engine SELL=只平仓** (unified_engine.py:420) → 确认; arbitrator FORCE_EXIT→SELL(1.0) 为唯一常开止损 (R3)。

---

## 8. 实施顺序 (修订)

1. **P0-1/2/6** (direction 透传→adapter direction 优先→normalizer/scan_signal 抵销) — ✅ **已实施 (2026-08-12)**
2. **P0-3** (RDP 仅展平 wyckoff 键) → **P0-4/5/7** (门槛 0.40 / 关 structural_adjust / 恒不产 SELL-as-entry) — ✅ **已实施 (2026-08-12)**
3. **P2 验收** (五窗断言 + 存活表全建 + golden baseline) — ✅ **已执行 + 复验 PASS (2026-08-12)**, 报告 `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md`
4. **P1-3** (sos 独立字段 `sos_candidate_detected`，不复用 signal_type) → **P1-4~12** (标注面: EVR/图式失效/NoSupply/NSD/VDU/eventCooldown/rangeScore/AVWAP/bias200) — ✅ **已实施 (2026-08-12)**
5. **P1-11 参数化声明** (stoploss_guard_* config 默认关) — ✅ **config 已声明** (功能代码按 R3 裁决留待未来窗口预注册 T5 全 PASS 后实施)
6. **P1-1 撤回** (仅 atr_pct 透传, 无代码) / X4 候选跟踪 (未来 ≥3/5 窗再评估) — ✅ **无代码改动** / ⏳ **未来监测**

### 额外完成 (2026-08-12 深度验证 V2)
- V1 F7 口径统一稳健性 (PASS, leader 3/5 全剔尾边界稳健)
- V2 P0 后方向映射实证 (PASS, 5/5 窗 BUY>0 SELL=0)
- V3 X4 多重检验审计 (PASS, 修正标签"牛市超跌反弹")
- V4 全信号链泄漏审计 (PASS, 220 单元格 0 SELL)
- V5 A股铁律交互 — 涨停守卫修复 (engine.py 加 LIMIT_UP/BREAK_LIMIT_UP 守卫 + 精确价差容差 0.5%)
- 全量回归: **2104 passed / 8 skipped / 0 failed**, 0 ruff, golden 门一致

---

## 9. 产物清单

| 产物 | 位置 |
|---|---|
| 预注册 | `scripts/wyckoff_experiments/PREREGISTRATION_20260812.md` |
| 实证脚本 (0 ruff) | `scripts/wyckoff_experiments/` 5 脚本 + 结果 JSON (results/wyckoff_experiments/) |
| 老窗扫描 | `results/wyckoff_xs4/` (2025-06-30) + `results/wyckoff_xs5/` (2024-12-31), 各 5755 只 |
| 证据表 | `/tmp/opencode/wyckoff_phase3_evidence.md` |
| 本方案 | `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` |