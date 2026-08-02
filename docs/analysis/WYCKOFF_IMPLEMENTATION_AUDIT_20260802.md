# Wyckoff 实现综合审计报告（2026-08-02）

> 视角：顶尖交易员 + 量化金融算法工程师 + 量化金融专家
> 方法：先核查 `docs/analysis/` 设计文档准确性，再核验 `src/uniquant/brain/wyckoff/` 实际代码
> 结论基准：`scripts/classic_wyckoff_compliance.py` 实跑输出（非文档快照）

---

## 0. 执行摘要

| 维度 | 结果 |
|---|---|
| 合规分数（实跑） | **58.3%**（14P / 7Pa / 9F / 30 项） |
| 文档准确性 | **5 份文档过时/失准**，1 份（VERIFICATION_v1）部分失准 |
| 引擎代码质量 | 良好 — P0 阶段 8 项修复全部真实生效（源码特征验证） |
| 核心方法论 | 硬规则专家系统（非概率图模型），但事件序列驱动已落地 |
| 最大风险 | WSS 统计评分已训练但**从未被引擎加载**；MTF 双口径并存；**SQ-C1 评分数学上限 65.7 < 阈值 70（结构性死路径）** |
| 待修复（P1/P2） | 9 项 FAIL 全部真实（无检查假阳性） |

---

## 1. 文档准确性核查（先查 docs）

### 1.1 过时/失准文档

| 文档 | 日期 | 声明 | 实际代码 | 判定 |
|---|---|---|---|---|
| `wyckoff_design_vs_implementation_gap_analysis.md` | 06-25 | "P&F 0% 未实现" | `pnf.py` 完整实现（congestion_zone/count_target/breakout/phase_hint） | ❌ 严重过时 |
| 同上 | 06-25 | "PS/AR/ST/JAC 0% 未实现" | `events.py` 已实现全部 7 类事件（detect_ps/sc/ar/st/sos/lps/jac） | ❌ 严重过时 |
| 同上 | 06-25 | "WSO/WSS 0%" | `sequence.py` 已实现 WSOScorer/WSSScorer/WyckoffScorer | ❌ 严重过时 |
| 同上 | 06-25 | "多周期共振 0%" | `phase_analysis.py` MultiTimeframeResonance + engine rule9 融合 | ❌ 严重过时 |
| 同上 | 06-25 | "无概率更新" | `bayesian_events.py` BayesianEventDetector（update/posterior/collapse） | ❌ 严重过时 |
| `CLASSIC_WYCKOFF_COMPLIANCE_FRAMEWORK.md` | 07-24 | PF-C1/C2/C3 FAIL、ES-C1/C3 FAIL、PH-C1/C2 FAIL、CF-C4/CN-C4/SQ-C1/RS-C1 FAIL | 合规脚本实跑均 **PASS**（P0/P1 已修复） | ❌ 过时 |
| `CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md` 验收总表 | 08-02 | ES-C3 / PH-C1 / PH-C2 / CF-C4=FAIL（红蓝对抗补充 PH-C1/PH-C2） | 实跑四项均 PASS | ⚠️ 状态列未随修复更新（4 项 P0 核心漂移） |

**核心结论：文档是静态快照，代码是活体。** 以合规脚本输出为准。VERIFICATION_v1 的验收总表"当前状态"列与"实现者/日期"列自相矛盾（实现者标注 08-01 完成但状态列仍是 FAIL）。

### 1.2 准确文档

| 文档 | 判定 |
|---|---|
| `CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md` 的 30 项规格定义 | ✅ 与合规脚本一一对应 |
| `WYCKOFF_FULL_SCAN_ANALYSIS_20260802.md`（本次 P0 诊断） | ✅ 与全量扫描数据一致 |
| `WYCKOFF_LPS_REFACTOR_DESIGN_20260802.md` | ✅ 准确反映 rule6 现状与重构方向（红蓝对抗确认：设计已完整覆盖 max_vol 参照系陷阱——`spring_volume` 参数 + `test_vol_ratio = test_bar_volume / spring_volume`） |

### 1.3 文档漂移根因

1. **6-25 的 gap_analysis 是"设计文档 vs 早期实现"的对比**，当时确实缺失；但 6-28 后事件检测/评分/P&F 已补全，文档未更新。
2. **7-24 的 COMPLIANCE_FRAMEWORK 是 P0 修复前的基线**；8-01 P0 修复完成后未回写。
3. **VERIFICATION_v1 是模板化的验收表**，实现时更新了"实现者/日期"列却漏了"状态"列。

---

## 2. 代码实现核验（再验代码）

### 2.1 已确认真实生效的 P0/P1 修复（源码特征 + 行为双重验证）

| ID | 代码证据 | 判定 |
|---|---|---|
| PF-C1 | `engine.py:747` P&F phase_hint 在 7 检测器之前短路判定 | ✅ |
| PF-C2 | `engine.py:1159` count_target > 现价时作为第一目标（`first_target_source="pnf_count_target"`） | ✅ |
| PF-C3 | `engine.py:417-420` congestion_zone 优先覆盖 TR 边界（`tr_source_override="pnf_congestion"`） | ✅ |
| ES-C1 | `engine.py:634` `_scan_spring` 共享扫描器（`boundary_lower*0.985` 跌破带 + `closes[j]>=boundary_lower` 收回 + `vol_ratio<=0.8` 萎缩），step3 复用 | ✅ |
| ES-C3 | `engine.py:672` `_scan_utad`（`boundary_upper*1.02` 突破 + `<=1.01` 收回 + `vol_ratio>=1.5` 放量），`_detect_utad` 驱动 DISTRIBUTION | ✅ |
| PH-C1 | `engine.py:503-517` 事件序列优先（PS+SC+ST×2 → ACCUMULATION，忽略 price_position） | ✅ |
| PH-C2 | `engine.py:560-567` `_scan_utad` 优先驱动 DISTRIBUTION（忽略 price_position） | ✅ |
| CF-C4 | `engine.py:700` `_scan_false_breakout`（1.02 突破 + 3 列跌回 + 放量）+ step5 标记 + `_build_report:1559` 降级 | ✅ |
| CN-C4 | `engine.py:126` `_detect_adjustment_status`（>20% 跳空探测）+ raw 降级 | ✅ |
| SQ-C1 | `engine.py:140` `_compute_structural_score` + `_apply_structural_adjustment`（≥70 升/≤35 降） | ✅ |
| RS-C1 | `relative_strength.py` 四分类 + `engine.py:369-385` index_df 接线 | ✅ |

### 2.2 9 项真实 FAIL 逐一核实

| ID | 合规脚本判定 | 代码核实 | 真实性 |
|---|---|---|---|
| PF-C5 | `build()` 每次全量重建 | `pnf.py:50` 无增量更新接口 | ✅ 真 |
| VS-C1 | events.py 154 个硬编码数值 | AST 扫描核实（含索引/长度等噪音，但核心阈值 1.2/2.0/0.8 确实硬编码） | ✅ 真（扫描偏宽） |
| VS-C3 | 无买卖盘方向区分 | 数据层仅 OHLCV 总量 | ✅ 真（数据限制） |
| MT-C2 | MTF 无量化改进证据 | 引擎 rule9 融合无 R²/IC/Sharpe | ✅ 真 |
| RS-C2 | ChipAnalysis 未接入置信度 | `_calc_confidence` 不含筹码字段 | ✅ 真 |
| CF-C1 | 反事实无数值时间窗口 | `engine.py:1038` 证据计数评分（pro/con ×2.0），无时间窗 | ✅ 真 |
| CN-C1 | box_size 硬编码 0.02 | `engine.py:284` `PointAndFigure(box_size=0.02, reversal=2)` | ✅ 真 |
| CN-C2 | T+1 只计算不强制 | `rule3_t1_risk_test` 返回 verdict 但 direction 不据此否决（除涨跌停） | ✅ 真 |
| CN-C3 | 涨跌停不影响 P&F | `pnf.py` 无 limit 检查 | ✅ 真 |

---

## 3. 三视角深度评估

### 3.1 交易员视角（Wyckoff 理论忠实度）

**正确之处：**
- Spring 定义（O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩）贴合经典威科夫，且 `_scan_spring` 在相位检测与 step3 间共享，无重复逻辑。
- LPS 确认 + 守位作为硬门槛的方向正确（设计文档已修正，见 LPS 重构设计）。
- 假突破惩罚（CF-C4）符合"TR 上沿 2%+ 突破后 3 列跌回 = 假突破"的经典交易认知。

**严重方法论问题（交易视角）：**

1. **Spring→交易信号的传导率接近 0**（全量扫描：spring 66 只，其中 0 只触发买入；剔除 6 只 ETF 污染后仍为 0）。根因链（红蓝对抗定量分解，65 只可验证标的）：
   - **量能参照系矛盾（红蓝对抗降级为 B 级，原判 A 级）**：`_scan_spring` 用 `vol_ratio <= 0.8`（相对 median）判萎缩，step3 用 `rule1_relative_volume`（相对 **mean** 30 日均线）重判。实证 median/mean=0.917，偏差仅 8%——仅在 vol_ratio∈[0.7,0.8] 窄窗口内缩量被标"平均"（语义反，但**非**报告原判的"被叫放量"）。
   - **rule6 三条件 AND 是最致命根因（A 级，定量分解）**：low_volume 失败率 **92%**（`recent_vol < max(post_vol)*0.3`，整段 `max_vol` 作分母——post_spring 窗口内任何 1 根放量即拉高门槛，正常波动几乎不可能达标，这是**统计参照系陷阱**）；price_held 失败率 68%（`post_spring_df["low"].min()` 把整段区间最低点作门槛）；bounce 失败率 32%。三因全部满足 = 0 只，LPS 通过率 0/65。
   - **结构性矛盾（红方补充）**：27.3% 的 spring 剩余 K 线 <10 根（LPS 验证窗口不足），spring 越新越难验证；tail_skip（spring 贴近数据尾部）仅 1.5%，非主因。
   - **ETF 污染（红方补充）**：66 只 spring 中 6 只（9.1%）是 ETF（159605/159896/159966/161037/161908/166107），T+0 且无个股涨跌停，评估应排除后重算。
   - **LPS 重构设计已完整覆盖此根因**（`spring_volume` 参照 + `test_vol_ratio` + 明确标注"旧：recent_vol < max(post_spring_vol) × 0.3 ← 参照系错误"）——执行即修。
2. **markup 阶段追买**（全量扫描 markup 171 只中 14 只"买入/做多"，红蓝对抗修正原判 17 只）：`engine.py:1333` `"Test"/"Shakeout"` 在 MARKUP 直接给"买入"，这在威科夫框架里是 Phase E 的追涨动作，与"研究平台定位 + 右侧信号"矛盾，且 20d 前涨幅 +9% 证实是追涨。
3. **相位-收益背离**（accum 6m -21.0% / dist 1m +6.9%）：DISTRIBUTION 后继续上涨，说明检测器把"盘整上涨"误判为派发——这是 `_detect_distribution` 的 UTAD 优先 + `prior_trend_pct>0.05` 宽松阈值所致。
4. **confidence 分布失衡**：D 级占 84%（4482/5382），扫描映射 4 档 {A:0.9 / B:0.7 / C:0.5 / D:0.3} 但 A 档几乎不存在（有效 3 档），对研究平台无区分度。

### 3.2 量化算法工程师视角（工程实现质量）

**工程良好实践：**
- 共享扫描器（`_scan_spring/_scan_utad/_scan_false_breakout`）消除 step3 与检测器链的重复实现——符合 CLAUDE.md "Surgical Changes"。
- `_compute_structural_score` 纯函数化 + `event_sequence_score` 依赖注入（wss_lookup 可选）——可复现。
- rule1 的 rolling 均值缓存（`_vol_ma_30_cache`）避免重复计算。
- 合规脚本用 `inspect.getsource` 源码特征检查，非字符串 grep 全表——防误判。

**工程缺陷：**

1. **WSS 统计评分死链（高优先级）**：`scripts/wyckoff_multitf/output_v4/wss_lookup.json`（训练好的 WSS 权重）**从未被引擎加载**。`_compute_structural_score` 调 `event_sequence_score(event_types)` 走默认空 lookup → 纯 WSO 规则路径。`WyckoffScorer` 的 α/β blend 逻辑（0.3/0.7）从未被触发。
2. **MTF 双实现并存（红蓝对抗表述修正）**：`phase_analysis.py:MultiTimeframeResonance`（2/3 投票，附 resonance_strength）vs `analysis.py:merge_multitimeframe_reports`（rule9：markdown_override/distribution_override/degraded/aligned）。引擎走后者；前者**有 8 个独立测试**（`test_phase_analysis.py`）但**未接入引擎生产路径**——准确表述是"**有测试覆盖的双口径并存**"，非纯死代码。两套融合口径并存是设计意图分歧（投票 vs 规则覆盖），需统一决策。
3. **`_detect_sos` 是空壳**（`engine.py:734` `return None`）——SOS 检测器在相位判定链中永不触发，与 ES-C4 的 SOS 检出率警告呼应（events.py 的 SOS 独立存在但引擎相位判定不用）。
4. **P&F phase_hint 短路主导相位（红蓝对抗量化）**：`engine.py:747` 只要 P&F hint ∈ {accum, dist} 就直接覆盖 7 个检测器结果。全量扫描 **3404/5382 = 63.2%** 标的有明确 hint，且 hint 明确时 phase 与 hint 100% 一致（0 不一致）——**7 检测器链只在 36.8% 标的上运行**。PnF 是 3-box reversal + 0.02 固定 box，对低价股（如 0.41 元 fixture）box=0.01 下限失真，hint 可信度无校准。此机制与"相位-收益背离"（accum 6m -21% / dist 1m +6.9%）同源：hint 用 rising_lows_ratio>0.5 + range_contraction<0.85 判"吸筹"实为趋势转涨特征、用 falling_highs_ratio>0.3 + range_contraction>1.2 判"派发"实为已下跌特征——**是过去形态的统计描述，非前瞻信号**。
5. **`.py,cover` 污染源码目录**：19 个 coverage artifact（312KB）混在 `src/uniquant/brain/wyckoff/` 下（7-10 生成），虽未被 import，但污染 lint/打包/代码检索。
6. **`pnf.py:232-233` 死代码**：两个无副作用的 `slice()` 调用残留。

### 3.3 量化金融专家视角（学术严谨性 & 研究价值）

**符合研究平台定位的设计：**
- RS-C1 明确"分类结果作为增量研究标记，不改变信号方向"——对研究平台是正确边界。
- CN-C4 复权状态探测 + raw 降级——避免用错复权数据的系统性偏差。
- SQ-C1 结构评分 min-max→0-100 可解释、可复现。

**学术严谨性质疑：**

1. **structural_score 区分度差（红蓝对抗升级为"结构性死路径"）**：全量扫描 p25=58.7 / p75=60.9 / max=64.4，分布高度拥挤。**决定性根因：`_compute_structural_score` 数学上限 = 65.7 分**——WSO 全正权重和仅 0.0334 + 最大序列 bonus 0.03 + phase 0.15 + event 0.10 → raw 上限 0.3134 → 映射 (0.3134+1)/2×100。**≥70 升级阈值在数学上不可能达到，≤35 降级同理**——不是分布拥挤问题，是**评分函数权重天花板与阈值不匹配**。更严重：`test_adjustment_high_upgrades_level` 直接注入 80 分验证升级逻辑、`test_adjustment_upgrade_via_metadata` 硬编码 80.0，**从不验证生产可达性**——测试绿但功能死，SQ-C1 置信度加权升级路径在生产中是结构性死代码。评分对研究选股无排序力。
2. **置信度与结构/RS 零相关**：全量扫描 pearson(confidence, structural) ≈ 0（红蓝对抗实算 0.049，原判 -0.024 修正）。且因 structural_score 数学上限 65.7 < 阈值 70，`_apply_structural_adjustment` 的升级/降级路径在生产中**永不触发**——不仅微调幅度被 3 档输出抹平，调整逻辑本身不可达。
3. **反事实无时间维度（CF-C1）**：`_step35_counterfactual` 只是正反证据计数仲裁（rule7），没有"相位反转后 N 日验证窗口"的概念——无法验证"如果当时做空会怎样"。
4. **WSS 训练-推理断裂**：训练侧有完整的 phase1-8 流程和 wss_lookup.json，推理侧从不加载。这是**最严重的投入浪费**——训练了统计模型却只用规则路径。
5. **SOS/UTAD 检出率无校准**：events.py 注释自承 109.5% 检出率（每根 K 线超 1 次），引擎直接消费 `detect_all_events` 的事件序列，阈值无实证校准。

---

## 4. 发现清单（按优先级）

### P0（无——本审计不涉及新崩溃级缺陷）

### P1（架构/正确性，建议修复）

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| A1 | **WSS 权重从未加载** | `sequence.py:175` 空 lookup；训练产物存在 | 在引擎初始化加载 `wss_lookup_v2.json`，`_compute_structural_score` 传入 lookup 走 α/β blend |
| A2 | **MTF 双实现** | `phase_analysis.py:401` vs `analysis.py:196`（有测试但未接入引擎） | 统一为 rule9 融合（生产路径），MultiTimeframeResonance 保留测试或注明 legacy |
| A3 | **Spring 量能参照系矛盾（B 级，红蓝对抗降级）** | `_scan_spring` median vs `rule1` mean（偏差仅 8%，仅 [0.7,0.8] 窄窗口语义反） | 统一参照系；spring_quality 用 spring 当日 vol_ratio 直接分级 |
| A4 | **LPS 三条件 AND 过严（A 级，最高优先级，红蓝对抗根因定量）** | `rules.py:207`；low_volume 92% 失败（max_vol 分母参照系陷阱）、price_held 68%、bounce 32%；27.3% 窗口 <10 根；6 只 ETF 污染 | 执行 `WYCKOFF_LPS_REFACTOR_DESIGN`（硬门槛=守位，量能=spring 日量 `test_vol_ratio`，反弹=多K线窗口）——**设计已完整覆盖 max_vol 参照系错误，执行即修** |
| A5 | **confidence 3 档失真** | `_calc_confidence` 0.3/0.5/0.7（A 档几乎不存在，D 占 84%） | 恢复连续值；structural/RS 联动加权 |

### P2（工程卫生 / 研究增强）

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| B1 | `.py,cover` 污染源目录 | 19 文件 312KB | 移入 `src/uniquant/brain/wyckoff/.cover/` 或删除 |
| B2 | `_detect_sos` 空壳 | `engine.py:734` | 实现或用 SOS 候选标注相位 |
| B3 | `pnf.py:232-233` 死代码 | 无副作用 `slice()` | 删除 |
| B4 | VS-C1 硬编码阈值 | events.py 154 数值 | 收敛为 config 常量表 |
| B5 | P&F hint 无校准置信度 | `engine.py:747` 短路 | 给 hint 附加可信度（box 覆盖列数） |

### WONTFIX（数据/定位限制）

- VS-C3（无逐笔方向）、CN-C3（涨跌停入 P&F）、CF-C1（时间窗口反事实）——需 tick 数据或偏离研究平台定位。

---

## 5. 结论

**代码对 Wyckoff 的实现是"硬规则专家系统"的成熟版本**：经典事件（PS/SC/AR/ST/SOS/LPS/JAC + Spring/UTAD/假突破）检测齐全，P0 阶段 8 项修复真实生效，合规实跑 58.3% 可信。

**但存在三处"看起来有、实际断"的裂缝（红蓝对抗复核）：**
1. **WSS 统计评分**——训练了却从不加载，规则路径独走（A1 接线遗漏确凿；红方追加：WSS 信号本身偏负，接线后须校验 f6 口径与有效性）；
2. **LPS 传导链**——spring 66 只 / 0 买入，根因是 rule6 的 max_vol 参照系陷阱（low_volume 92% 失败），理论信号从不落到交易计划；
3. **MTF 共振**——生产用 rule9，MultiTimeframeResonance 有测试但未接入引擎，双口径并存（非纯死代码）。

**核心建议（红蓝对抗后重排）**：优先修 **A4（LPS 重构，设计已就绪且已覆盖根因）** + **SQ-C1 评分函数权重/阈值再校准（数学上限 65.7 vs 阈值 70 = 结构性死路径）**，二者直接决定信号链能否打通与区分度；A1（接 WSS，需先验证有效性）、A2/A5 次之；A3 已降级为 B 级。9 项 FAIL 中 6 项为 P1/P2 可修，3 项（VS-C3/CN-C3/CF-C1）WONTFIX。

---

## 6. 附：验证方法

- 合规实跑：`python3 scripts/classic_wyckoff_compliance.py` → 58.3%（14P/7Pa/9F/30）
- 源码特征验证：`inspect.getsource` + AST 扫描（VS-C1 硬编码计数）
- 行为验证：classic_wyckoff 62 测试全过（`--no-cov`）
- 全量数据：`results/wyckoff_full/wyckoff_scan_all.csv`（5382 只）统计引用
- 红蓝对抗实证（`docs/analysis/WYCKOFF_AUDIT_REDBLUE_FINAL_20260802.md`）：
  - A4 定量分解：spy 捕获 65 只 spring，逐条重算 rule6 三条件（low_volume 92% / price_held 68% / bounce 32%）
  - A3 量能偏差：实算 median/mean=0.917（8%）
  - SQ-C1 数学上限：WSO 全正权重和 0.0334 + bonuses → 上限 65.7
  - P&F hint 覆盖率：3404/5382 = 63.2%，hint 明确时 phase 100% 一致
  - ETF 污染：66 只 spring 中 6 只（9.1%）为 159/161/166 段 ETF

---

## 7. 附：红蓝对抗修订记录（2026-08-02）

| # | 修订点 | 原文档 | 修正后 | 依据 |
|---|---|---|---|---|
| 1 | markup 买入数 | 17 只 | **14 只**（markup 171 只中买入/做多） | 全量扫描 CSV 实算 |
| 2 | A3 严重度 | A 级"缩量被叫放量" | **B 级**，仅 [0.7,0.8] 窄窗口"缩量被叫平均"（8% 偏差） | median/mean=0.917 实证 |
| 3 | A4 根因 | "三条件 AND 过严"（无定量） | **定量分解**：low_volume 92%（max_vol 分母参照系陷阱）+ price_held 68% + bounce 32%；27.3% 窗口<10 根；ETF 9.1% 污染；设计已覆盖根因 | rule6 逐条件 spy 重算 |
| 4 | SQ-C1 区分度 | "≥70 几乎不可达" | **数学上限 65.7 = 结构性死路径**；测试注入 80 分掩盖生产不可达（测试绿但功能死） | WSO 权重求和上限 |
| 5 | A2 MTF | MultiTimeframeResonance "死代码" | **有 8 个独立测试但未接入引擎**，双口径并存 | test_phase_analysis.py |
| 6 | P&F 短路 | 未量化 | **63.2% 标的由 PnF hint 独占判定**，与相位-收益背离同源 | 扫描数据一致性 |
| 7 | confidence | "仅 3 档值 0.3/0.5/0.7" | 4 档映射 {0.9/0.7/0.5/0.3}，A 档几乎不存在，D 占 84% | `_calc_confidence` + 扫描 |
| 8 | pearson(conf,struct) | -0.024 | **≈0（实算 0.049）** | 全量扫描重算 |
| 9 | 文档漂移 | ES-C3/CF-C4 | 补 **PH-C1/PH-C2**（4 项 P0 核心） | VERIFICATION_v1 实跑对照 |
| 10 | 修复优先级 | A1 最高 | **A4 + SQ-C1 权重校准最高**；A1 需先验证 WSS 有效性 | 红蓝对抗裁决 |
