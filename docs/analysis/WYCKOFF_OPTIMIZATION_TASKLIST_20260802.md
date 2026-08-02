# Classic Wyckoff 优化修复任务清单（2026-08-02）

> 依据：`WYCKOFF_OPTIMIZATION_EVALUATION_20260802.md`（三视角评估 + 3 轮红蓝对抗终局）
> 前提：本清单每一项的**代码触点均经真实源码核实**（行号来自当前工作树），每一项附**红蓝对抗裁决**。
> 执行模式：**严格 TDD**（先写测试 RED → 最小实现 GREEN → 重构），**多 subagent 并行**（Wave 划分见 §2 并行矩阵）。
> 总闸门：所有 fwd 实证验收以 **P0-B 产出（fwd 列 + 全量重扫）** 为数据底座；P0-B 之前仅做单元/集成验收。

---

## 0. 代码事实基线（本次核实，非假设）

| 事实 | 证据 |
|---|---|
| `rule6_spring_validation` 旧签名仅传 `spring_low`，无量参照无测试K线识别 | `rules.py:146-225`；守位用 `post_spring_df["low"].min() >= spring_low*0.995`（`:192`），量能用 `recent_vol < max_vol*0.3`（`:188-190`），反弹单日收阳（`:195-197`） |
| ATR 在 rule6 调用**之后**才计算 | `engine.py:969-977` 调 rule6；`engine.py:1018` 才 `Indicators.calc_atr` → `current_atr` |
| `_scan_spring` 已返回 `pos`（绝对位置），可索引 spring 当日量 | `engine.py:634-670`，返回 `{"date","low","vol_ratio","pos"}` |
| `spring_volume` 变量是**字符串**（rule1 返回中文文本），非数值 | `engine.py:943-960`：`spring_volume = self.rules.rule1_relative_volume(...)` |
| PnF hint 短路：`_step1_phase_determine` 在 hint 明确时直接返回，7 检测器链仅跑 36.8% | `engine.py:737-747`（`if pnf_hint in (...): return`） |
| `_detect_sos` 是空实现 `return None` | `engine.py:733-735` |
| `_calc_confidence` 5 条件矩阵，A 级需 4 条件 | `engine.py:1194`；`rules.py:247-291` `rule8_confidence_matrix`（≥4=A, ≥3=B, ≥2=C, else=D） |
| 结构分数学上限 65.7，≥70 升级路径**不可达**（死路径） | `engine.py:89-138` `_apply_structural_adjustment`（阈值 70/35）；`_compute_structural_score` `:140` 权重和 0.0334+0.03+0.15+0.05+0.10=0.3134 → 映射 65.7 |
| `test_structural_score.py` 直接注入 80.0 绕过死路径，从不验证生产可达性 | `tests/classic_wyckoff/test_structural_score.py:132,158` |
| WSS 死分支：`WyckoffScorer.score_sequence` 需 `is_loaded`，但引擎未接线 | `sequence.py:114-180`（`is_loaded` `:137`；`score_sequence` `:175`）；`wss_lookup_v2.json`（436 seqs）存在未接线 |
| `MultiTimeframeResonance` 已实现且**有 8 测试**但未接线到引擎 | `phase_analysis.py:401`；`tests/test_phase_analysis.py:190` 起；`analysis.py:196` `merge_multitimeframe_reports` 用 rule9 未用 Resonance |
| 全量扫描：5374 成功；66 spring（6 ETF=9.1%）；结构分 p50=60.03 分布极窄 | `results/wyckoff_full/wyckoff_scan_all.csv`；`engine.py` |
| Step2Result 构造点 2 处 | `engine.py:819`（空返回）、`:920`（正常返回） |
| markup 信号置信度未降级（仅 CF-C4/CN-C4 降级） | `engine.py:1558-1563` |

---

## 1. 任务清单（8 项，按优化评估路线图 P0→P3）

### P0-A 【LPS 判定重构】rule6 分层判定 + ATR 上移 + spring 当日量参照

**目标**：修复 LPS 传导率 0%（66 spring 中 lps_confirmed 极低）。守位为硬门槛，量能参照 spring 当日量，反弹用多根窗口。

**代码触点（已核实）**：
- `rules.py:146` `rule6_spring_validation` 签名改为 `(spring_detected, post_spring_df, spring_low, spring_volume=0.0, atr=0.0)`
- `engine.py:969-977` 调用点：传 `spring_volume=数值` + `atr=current_atr`
- `engine.py:1018` ATR 计算**上移**至 spring 检测之前（或 rule6 自行计算）
- `engine.py:943` `spring_volume` 字符串改为数值（新增 `spring_volume_value` 或复用 `df["volume"].iloc[spring_found["pos"]]`）
- `models.py:444` `Step3Result` 新增 `lps_stage: str = "not_test"`、`test_low: Optional[float] = None`

**红蓝对抗裁决**：
- 红方1（参照系）：旧实现量能对比后 spring 窗口 `max_vol`，错误。→ **采纳**：改参照 spring 当日量（`test_vol_ratio <= 1.0`）。
- 红方2（守位过严）：`low.min() >= 0.995` 单根瞬时下影线即否决。→ **采纳**：改"测试K线 low + `max(0.25*ATR, 0.5%)` 容忍"。
- 红方3（反弹单日噪声）：最后收阳被扫描日噪声否决。→ **采纳**：改测试后 5 根窗口内收盘 ≥ 测试高 + 0.5×ATR。
- 蓝方底线：守位不可补偿，禁加权评分。→ **维持**：硬门槛 + 分级（test_held / lps_confirmed）。
- 仲裁：按 `WYCKOFF_LPS_REFACTOR_DESIGN_20260802.md` 执行，参数首版默认值照表 §6.1。

**TDD 测试**：`tests/classic_wyckoff/test_lps_refactor.py`（T1-T7，RED→GREEN）；T8 为真实数据闸门（传导率 >30%）。

**验收**：T1-T7 全过；classic_wyckoff 全套回归；spring 传导率（窗口充足非 ETF）>30%；ruff clean。

**文件边界**：`rules.py`（规则层，独立文件）+ `engine.py` step3 区段 + `models.py` Step3Result。

---

### P0-B 【fwd 数据底座】scan CSV 补 `is_etf` + `fwd_20d/fwd_60d` 列 + 全量重扫

**目标**：为所有后续 fwd 实证验收提供数据底座。扫描输出带前向收益 + ETF 标记。

**代码触点（已核实）**：
- `scripts/wyckoff_full_scan.py:76-157` `analyze_one`：无 fwd、无 is_etf 字段
- `scripts/wyckoff_full_scan.py:181-212` `summarize` / `main`：CSV 列不完整

**红蓝对抗裁决**：
- 红方1（前视泄漏）：fwd_20d/fwd_60d 用扫描日之后数据，需明确"扫描日 as-of"，否则回测前视。→ **采纳**：`is_etf` 与 `fwd_*` 列为**信息列**，不进入引擎决策；扫描脚本声明 `as_of_date`；文档注明"fwd 仅用于研究评估，不参与信号生成"。
- 红方2（ETF 判定）：不能硬编码代码清单。→ **采纳**：基于代码段规则（159/161/166/159xxx ETF、588xxx 科创、5xxxxx 沪 ETF 等），或复用 data 层已有代码分类（若存在）。
- 蓝方（回退安全）：fwd 计算失败不得让扫描失败。→ **采纳**：fwd 缺失时填 NaN 不影响主流程。
- 仲裁：P0-B 是**纯脚本层**，无引擎改动，并行性最高，列为 Wave A 首批。

**TDD 测试**：`tests/scripts/test_wyckoff_full_scan_fwd.py`（analyze_one 输出含 is_etf/fwd 列；fwd 计算正确性；ETF 前缀规则单测）。

**验收**：重跑全量扫描；CSV 含 `is_etf/fwd_20d/fwd_60d` 列；相位-收益、spring-fwd、confidence-fwd 实证表可生成；100 标的冒烟 <5s。

**文件边界**：仅 `scripts/wyckoff_full_scan.py`（+ 新测试）。**无引擎冲突**。

---

### P1-A 【相位拆解】PnF hint degraded 标记 + 去 PnF 主导第 1 步

**目标**：识别 PnF hint 与检测器链的**分歧**，为渐进去 PnF 主导铺路。第 1 步不改变相位结果，只输出分歧标记。

**代码触点（已核实）**：
- `engine.py:737-747` `_step1_phase_determine` PnF 短路
- `engine.py:745-760` 检测器链（仅 hint 非明确时跑）
- `WyckoffReport`（models.py:664）新增 `pnf_phase_divergence: Optional[str]` 或并入 `pnf_analysis`

**红蓝对抗裁决**：
- 红方1（性能）：hint 明确时若仍跑全链，63.2% 标的多 7 检测器开销。→ **采纳**：第 1 步仅对**候选池子集**（如 confidence C+）跑对照，或加 feature flag 默认关。
- 红方2（口径）：分歧定义需明确（hint=accumulation 而链=distribution 才算分歧？）。→ **采纳**：分歧 = hint 与"链主相位"不同。
- 蓝方（渐进性）：不直接移除 PnF 短路，避免 3404 只相位结果漂移。→ **维持**：第 1 步只加标记 + 对照表。
- 仲裁：输出 `pnf_phase_divergence` + 分歧标的清单（CSV），fwd 对比两口径。

**TDD 测试**：`tests/classic_wyckoff/test_p1a_pnf_divergence.py`（分歧标记正确性；flag 默认关不改变现有相位结果）。

**验收**：分歧标的识别；现有 62 classic 测试相位结果不变；fwd 对比表生成。

**文件边界**：`engine.py` step1 区段 + `models.py` + `scripts/wyckoff_full_scan.py`（分歧输出列）。

---

### P1-B 【VDB 量价背离】Step2 补 `_detect_effort_result_divergence`

**目标**：为 Effort/Result 检测补充量价背离证据，修正 step2 证据与 fwd 收益相关性。

**代码触点（已核实）**：
- `engine.py:811-830` `_step2_effort_result`（phenomena 清单 + evidence 累加 + net_bias）
- `models.py:431` `Step2Result`（新增 `vdb_divergence: str = "none"` 字段）
- `engine.py:819/920` 两个构造点

**红蓝对抗裁决**：
- 红方1（重叠）：现有 phenomena 已有"放量滞涨/缩量上推"，VDB 需明确定义增量。→ **采纳**：VDB = 特定背离组合（如价创新高量萎缩 / 价平量放大）单列 `vdb_divergence` 字段，不覆盖现有 evidence。
- 红方2（负向证据）：背离不全是派发，缩量上推在吸筹早期是正常。→ **采纳**：VDB 只做**研究标记 + 置信度微调候选**，不进相位判定硬逻辑。
- 蓝方：纯函数，可独立测试。→ **维持**：提取为 `brain/wyckoff/effort_result.py` 新模块（同 RS-C1 模式），engine 薄接线。

**TDD 测试**：`tests/classic_wyckoff/test_p1b_effort_result.py`（背离检测正反例；net_bias 不变兼容）。

**验收**：新测试过；吸筹/派发证据与 fwd 收益相关性可计算（依赖 P0-B）。

**文件边界**：`effort_result.py`（新）+ `engine.py` step2 区段 + `models.py` Step2Result。

---

### P1-C 【SQ-C1 校准】结构分权重/阈值再校准 + 可达性测试

**目标**：修复结构分**死路径**（≥70 不可达）与分布极窄（p10≈p25）。

**代码触点（已核实）**：
- `engine.py:89-138` `_apply_structural_adjustment`（70/35 阈值）
- `engine.py:140` `_compute_structural_score`（权重和上限 0.3134 → 65.7）
- `tests/classic_wyckoff/test_structural_score.py:132,158` 注入 80.0 的假测试

**红蓝对抗裁决**：
- 红方1（假测试）：测试注入 80.0 从不验证生产可达性。→ **采纳**：新增可达性测试——真实权重路径最高分必须能触发升级分支（或阈值下移使可达）。
- 红方2（改动风险）：权重调整影响 fwd 排序力。→ **采纳**：三选一方案（阈值下移 / 权重重标定 / 移除升级路径），以 rank-IC>0 为闸门。
- 蓝方：SQ-C1 是研究评分，非交易硬门槛，保守改。→ **维持**：不破坏 B+归B 等既有 5 条件矩阵语义。
- 仲裁：先写**可达性测试**（当前 FAIL），再改权重/阈值使 GREEN；rank-IC 对比改前后。

**TDD 测试**：`tests/classic_wyckoff/test_structural_score_reachability.py`（可达性 + 分布拉开 + rank-IC>0）。

**验收**：可达性测试过；结构分分布 p10<p25 拉开；fwd rank-IC>0（依赖 P0-B）。

**文件边界**：`engine.py` 头部区段 + 测试文件。若提取纯函数到 `brain/wyckoff/structural.py` 则并行性提升。

---

### P1-D 【WSS 接线】WSS 接线 + A/B 对比（feature flag）

**目标**：把训练好的 `wss_lookup_v2.json`（436 seqs）接入结构分，A/B 对比。

**代码触点（已核实）**：
- `sequence.py:114-180` `WSSScorer`/`WyckoffScorer`（已实现，`is_loaded` 恒 False）
- `sequence.py:175` `score_sequence` WSS 分支（死分支）
- `wss_lookup_v2.json`（436 seqs，`scripts/wyckoff_multitf/output_v4/`）
- 结构分计算 `engine.py:140` `_compute_structural_score` 未用 WyckoffScorer

**红蓝对抗裁决**：
- 红方1（方差）：436/ALL 序列覆盖有限，多数标的无 WSS → 方差扩大幅受限。→ **采纳**：A/B 先验证有 WSS 标的子集方差扩大 + rank-IC 不降。
- 红方2（回退）：若接线负贡献，需可回退。→ **采纳**：feature flag `wyckoff.wss_enabled` 默认关，A/B 后再决定默认。
- 蓝方：WSSScorer 已有完整实现，接线成本低。→ **维持**。
- 仲裁：接线在 `_compute_structural_score` 内，若 seq_key 命中则 blended = α*WSO + β*WSS（α=0.3/β=0.7）。

**TDD 测试**：`tests/classic_wyckoff/test_p1d_wss_wiring.py`（flag 开/关行为；命中的 seq 走 blended；未命中回退 WSO）。

**验收**：A/B 对比表；接线后结构分方差扩大 + rank-IC 不降；负则回退 WSS 为研究标记。

**文件边界**：`sequence.py` + `engine.py`（结构分调用点）+ `config/config.yaml`。

---

### P2 【MTF 统一】复用 MultiTimeframeResonance 投票 + confidence fwd win-rate 验证 + 阈值收敛

**目标**：消除双口径（rule9 逻辑 vs Resonance），confidence 各档 fwd win-rate 单调性验证。

**代码触点（已核实）**：
- `phase_analysis.py:401` `MultiTimeframeResonance`（已实现 + 8 测试）
- `analysis.py:196` `merge_multitimeframe_reports`（当前用 rule9，未用 Resonance）
- `engine.py:1283-1289` ACCUMULATION 分支（confidence 下游）

**红蓝对抗裁决**：
- 红方1（行为变更）：换 Resonance 会改变现有 MTF 结果，需 A/B。→ **采纳**：feature flag `wyckoff.mtf_resonance` 默认关，A/B 后切换。
- 红方2（单调性数据）：confidence 各档 fwd win-rate 需 P0-B 数据。→ **采纳**：先出实证表再改阈值。
- 蓝方：Resonance 已测，复用成本低。→ **维持**。
- 仲裁：P2 依赖 P0-B，放在后段。事件阈值收敛进 config（`brain.wyckoff.event_thresholds`）。

**TDD 测试**：`tests/classic_wyckoff/test_p2_mtf_resonance.py`（flag 切换后 MTF 结果一致性；阈值收敛不破坏现有事件检测）。

**验收**：双口径消除；confidence 各档 fwd win-rate 单调（或明确不单调的证据）；现有 MTF 测试兼容。

**文件边界**：`analysis.py` + `phase_analysis.py` + `engine.py` + `config/config.yaml`。

---

### P3 【markup 降级 + RS 过滤】markup 追买降级（T2）、RS 仓位过滤（T3）

**目标**：markup "买入"信号（walk-forward 证实 p=0.0098 有效但追涨）加谨慎标记；RS 分类过滤仓位。

**代码触点（已核实）**：
- `engine.py:1558-1563` 已有 CF-C4/CN-C4 降级链，markup 未参与
- `engine.py:1281-1333` markup 分支（`_classify_wyckoff_markup_event`）
- `relative_strength.py`（RS-C1 四分类，已实现，仅研究标记未过滤仓位）

**红蓝对抗裁决**：
- 红方1（样本）：markup "买入"仅 12/171，A/B 统计力不足。→ **采纳**：T2 以 fwd 对比为闸门，样本不足时标注"证据有限"。
- 红方2（追涨性质）：markup 买入 fwd_20d=+13.33% 但前 20d 已 +9.05%，降级可能丢掉有效信号。→ **采纳**：降级只作用于**无 RS 确认**的 markup（leader/weak_independent 不降），保留有效信号。
- 蓝方：CF-C4 已证明降级链可行。→ **维持**。
- 仲裁：markup 信号在 RS∈{follower, systemic_decline} 时置信度降 1 级；RS=leader 不降。

**TDD 测试**：`tests/classic_wyckoff/test_p3_markup_rs.py`（降级规则正反例；RS 组合矩阵）。

**验收**：改后 markup 信号 fwd 收益 ≥ 改前（依赖 P0-B）；现有 markup 分支测试兼容。

**文件边界**：`engine.py` `_build_report` + `relative_strength.py` 用法。

---

## 2. 并行执行矩阵（多 subagent 设计）

**原则**：
1. **engine.py 为单写者文件**——所有动 engine.py 的任务按 Wave B 内顺序执行，避免 git 冲突。
2. **新模块优先**——P1-B（effort_result.py）、P1-C（structural.py 可选提取）用新文件承接纯逻辑，engine 只留薄接线。
3. 每 subagent 拿到：目标、代码触点（file:line）、测试文件路径、验收标准。

| Wave | 任务 | Subagent 分工 | 文件冲突 | 依赖 |
|---|---|---|---|---|
| **A**（并行 4 路） | P0-B / P1-A(flag 默认关) / P1-B / P1-D | 4 个 subagent：scan脚本、step1+models、effort_result+step2、sequence+config | P1-B 与 P1-A 不同 engine 区段（step2 vs step1）→ 可并行 | 无（P1-A/P1-B/P1-D 单测即可） |
| **B**（并行 2 路 + engine 单写者串行） | P0-A / P1-C | 2 个 subagent：rule6+step3+models、结构分头部+测试；engine.py 由 P0-A 先改后 P1-C | rules.py/step3 vs engine头部，区段不重叠 | P0-B 需先出 fwd 底座（Wave A） |
| **C**（并行 2 路） | P2 / P3 | 2 个 subagent：MTF+config、build_report+RS | analysis.py vs engine._build_report 不冲突 | 均依赖 P0-B fwd 实证 |
| **D**（验证汇总） | 全量重扫 + compliance + 回归 + 文档 | 1 个协调 subagent | — | A+B+C 全完成 |

**TDD 红线**：每任务先写测试（RED）→ 实现（GREEN）→ 重构；每 Wave 结束跑该任务新增测试 + `pytest tests/classic_wyckoff/ -q`（62 基线）回归；全部完成后 `ruff check src/uniquant/`。

**里程碑闸门**：
- Wave A 结束：P0-B 产出带 fwd 列的全量扫描 CSV → 解锁 B/C 的 fwd 实证验收。
- Wave B 结束：LPS 传导率 >30%；结构分可达性测试 GREEN。
- Wave C 结束：P2/P3 的 fwd 对比表出。
- Wave D 结束：AGENTS.md + 本清单验收状态更新。

---

## 3. 验收状态跟踪表（执行时逐项更新）

| 任务 | 状态 | 新增测试 | 回归 | ruff | fwd 实证 |
|---|---|---|---|---|---|
| P0-A | ☐ | ☐ | ☐ | ☐ | ☐ |
| P0-B | ☐ | ☐ | ☐ | ☐ | ☐ |
| P1-A | ☐ | ☐ | ☐ | ☐ | ☐ |
| P1-B | ☐ | ☐ | ☐ | ☐ | ☐ |
| P1-C | ☐ | ☐ | ☐ | ☐ | ☐ |
| P1-D | ☐ | ☐ | ☐ | ☐ | ☐ |
| P2 | ☐ | ☐ | ☐ | ☐ | ☐ |
| P3 | ☐ | ☐ | ☐ | ☐ | ☐ |

**最终建议执行顺序**：Wave A（P0-B + P1-A + P1-B + P1-D 并行）→ Wave B（P0-A → P1-C）→ Wave C（P2 + P3 并行）→ Wave D（全量验证 + 文档同步）。
