# Wyckoff 经典重构任务清单（2026-08-03）

> 依据：6 期多周期实证(理论一致性 50%=随机), 研究管线(t=10.24, Sharpe 2.02) vs 生产引擎差距分析
> 方法：每项经真实代码核实 + 红蓝对抗裁决, 严格 TDD, 支持多 subagent 并行

---

## 0. 代码事实基线（本次核实）

| 事实 | 位置 | 证据 |
|---|---|---|
| 检测器链 winner-takes-all, markup 优先 | `engine.py:796-813` | `detectors = [markup, dist, markdown, accum, spring, utad, sos]; for d in det: result = d(); break` |
| PnF 主导 63.2% 相位 | `engine.py:823-830` | `if pnf_hint in ("accumulation", "distribution"): phase = ...` |
| `_calc_confidence` 硬编码 if/elif | `engine.py:1290-1370` | A/B+/C bypass 路径, 不调用 `rule8_confidence_matrix` 为主路径 |
| WSS 接线默认关 | `engine.py:202-212` | `wss_enabled = cfg.get("wyckoff.wss_enabled", False)` |
| `MultiTimeframeResonance` 未参与决策 | `engine.py:1500-1530` | `multi_timeframe_statement` 仅文本, 不进入信号判定 |
| `_detect_markup` 本质是 MA 趋势 | `engine.py:582-620` | `st >= 0.03 and cp > ma20 and ma5 >= ma20` |
| `_detect_markdown` 本质是 MA 趋势 | `engine.py:638-678` | `st <= -0.05 and cp < ma20 * 0.95` |
| 研究管线 WSS 已训练 436 序列 | `scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json` | 436 seqs, wss ∈ [-0.211, +0.124] |
| `MultiTimeframeResonance` 已实现 | `phase_analysis.py:401-443` | 3 周期投票, 8 测试 |

---

## 1. 任务清单

### P0 【检测器链重构】三周期独立分类 + 事件序列投票制

**目标**: 消除 winner-takes-all 导致的 accumulation↔distribution 双向混淆(74+63次), 理论一致性 50%→65%+。

**代码触点**:
- `engine.py:796-813` `_step1_phase_determine` 检测器链循环
- `engine.py:823-830` PnF 短路
- `engine.py:545-580` `_detect_accumulation` (事件序列 + 启发式)
- `engine.py:582-620` `_detect_markup` (MA 趋势)
- `engine.py:638-678` `_detect_markdown` (MA 趋势)
- `phase_analysis.py:401-443` `MultiTimeframeResonance` (已实现)
- `engine.py:263-270` analyze 入口 `multi_timeframe` 参数

**红蓝对抗**:
- 红方1(回归风险): 改检测器链会破坏 62 现有测试, 这些测试假设 winner-takes-all → **采纳**: 先用 feature flag 隔离, 旧行为用 `wyckoff.legacy_detector_chain: true` 保留, 新行为在 `false` 时启用
- 红方2(数据可用性): 三周期需要月线/周线, 但 `analyze(df, multi_timeframe=False)` 时不提供 → **采纳**: 仅 `multi_timeframe=True` 时启用新投票制, False 时保留旧行为
- 蓝方(事件序列驱动): 事件序列路径(PS+SC+ST×2)已实现, `MultiTimeframeResonance` 已测试 8 用例, 复用成本低 → **维持**
- 仲裁: 增量实施——Phase 1: 加 feature flag + 投票框架(旧行为默认); Phase 2: 在多周期模式下启用投票; Phase 3: 积累实证后切换默认

**TDD 测试**: `tests/classic_wyckoff/test_p0_detector_chain.py`
- T1: flag=true 时旧行为不变(62 回归)
- T2: flag=false + multi_timeframe=true → 使用 Resonance 投票
- T3: 事件序列 PS+SC+ST×2 压倒投票结果
- T4: UTAD 事件压倒投票结果
- T5: 无事件序列时由 Resonance 投票决定

**验收**: 旧行为 62 测试全过; 新投票制下 accumulation↔distribution 双向混淆 < 50 次(6 期多周期验证); theory consistency > 55%; ruff clean

**文件边界**: `engine.py` + `phase_analysis.py` + `config/config.yaml`

---

### P1 【WSS 置信度】WSS 评分替代或补充置信度矩阵

**目标**: 解决 84% D 档和 0% A 档, 使置信度分布有意义且各档 fwd 收益单调。

**代码触点**:
- `engine.py:1290-1370` `_calc_confidence` 硬编码 if/elif
- `engine.py:202-212` WSS 接线(默认关)
- `sequence.py:141-182` `WyckoffScorer` / `WSSScorer`
- `scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json` 436 seqs

**红蓝对抗**:
- 红方1(WSS 负偏): WSS 正值仅 38.3%, 用 WSS 评分会系统性压低置信度 → **采纳**: WSS 不作为替代, 作为**补充维度**加入置信度矩阵混合模型
- 红方2(样本覆盖): 436 seqs 覆盖有限, 多数标的无 WSS → **采纳**: 无 WSS 匹配时回退旧矩阵
- 蓝方(统计严谨): 旧矩阵是硬编码, WSS 至少有 f6 统计验证 → **维持**
- 仲裁: 加权混合——`confidence = α × WSS_score + (1-α) × matrix_score`, α=0.3 默认, 无 WSS 时 α=0

**TDD 测试**: `tests/classic_wyckoff/test_p1_wss_confidence.py`
- T1: WSS 匹配时 α=0.3 混合
- T2: WSS 不匹配时回退旧矩阵
- T3: α=0 时行为不变(回归)
- T4: 混合后置信度分布 > 0% A 档
- T5: 各档 fwd_20d 单调(或明确不单调的证据)

**验收**: 置信度 A 档 > 0%; 各档 fwd_20d 单调; 无 WSS 标的回退不变; ruff clean

**文件边界**: `engine.py` `_calc_confidence` + `sequence.py` (已有)

---

### P2 【共振接入决策】MultiTimeframeResonance 过滤信号

**目标**: 把研究管线最有价值的共振过滤(Phase IV)接入 `_build_report` 信号决策。

**代码触点**:
- `engine.py:1500-1530` `_build_report` markup/markdown 信号分支
- `engine.py:263-270` `analyze(df, multi_timeframe=True)` 入口
- `phase_analysis.py:401-443` `MultiTimeframeResonance`
- `analysis.py:257-282` `merge_multitimeframe_reports` 已用 Resonance(P2 已完成)

**红蓝对抗**:
- 红方1(过度过滤): 共振过滤可能把有效信号也过滤掉(研究管线 bearish 共振+买入 是 +2.83% 最佳子策略) → **采纳**: 共振过滤只做**降级**不做**删除**, 且默认关
- 红方2(数据依赖): 需要多周期数据, 单周期调用时无法过滤 → **采纳**: 仅在 `multi_timeframe=True` 时启用
- 蓝方: 研究管线证明共振过滤增益 +0.43% 多空跨距, 且 `MultiTimeframeResonance` 已实现 → **维持**
- 仲裁: 在 `_build_report` 中, 当 `multi_timeframe=True` 时, 用 Resonance 结果做信号置信度微调——bullish 共振时买入信号降级, bearish 共振时卖出信号降级

**TDD 测试**: `tests/classic_wyckoff/test_p2_resonance_filter.py`
- T1: multi_timeframe=False → 无过滤(旧行为)
- T2: multi_timeframe=True + bullish 共振 + markup → 买入信号降级
- T3: multi_timeframe=True + bearish 共振 + spring → 保留(最佳子策略)
- T4: 共振过滤不改变 `WyckoffReport` 结构(向后兼容)

**验收**: 现有测试全过; 共振过滤后 markup 方向信号 fwd 收益 ≥ 过滤前; ruff clean

**文件边界**: `engine.py` `_build_report` + `phase_analysis.py` (已有)

---

### P3 【检测器优先级调整】MA 检测器移至链尾, 事件序列优先

**目标**: 让事件序列驱动(PS/SC/ST/SOS/Spring/UTAD)优先于 MA 趋势判断, 减少虚假 markup/markdown。

**代码触点**:
- `engine.py:796-813` 检测器链顺序
- `engine.py:582-620` `_detect_markup` (MA 趋势)
- `engine.py:638-678` `_detect_markdown` (MA 趋势)
- `engine.py:545-580` `_detect_accumulation` (事件序列)
- `engine.py:700-715` `_detect_utad` (UTAD)
- `engine.py:545-560` 事件序列 PS+SC+ST×2 路径

**红蓝对抗**:
- 红方1(覆盖降低): 事件序列触发率低(全量扫描中~5%), 移除 MA 检测器后大量股票会 fallback 到 unknown → **采纳**: 不删除 MA 检测器, 只移到最后; 事件序列有匹配时由事件序列决定, 无匹配时由 MA 决定
- 红方2(方向正确率): markup 67% 方向正确率是当前最好的相位, 降低其优先级会降低整体方向正确率 → **采纳**: 保持 markup/markdown 作为 fallback, 但不再作"相位"标签, 改称"trend_up"/"trend_down"
- 蓝方: 事件序列驱动的 accumulation 路径(PS+SC+ST×2)在测试中已证明有效, 只是被优先级压住了 → **维持**
- 仲裁: 新优先级: `accumulation(event) → distribution(UTAD) → spring → utad → markup(MA) → markdown(MA) → sos`。事件序列和 UTAD 有匹配时, 替代 MA 相位

**TDD 测试**: `tests/classic_wyckoff/test_p3_detector_order.py`
- T1: 事件序列 PS+SC+ST×2 匹配时 → accumulation(即使 MA 趋势向上)
- T2: UTAD 匹配时 → distribution(即使 MA 趋势向下)
- T3: 无事件序列时 → 回退 MA 检测器(markup/markdown)
- T4: Spring 匹配时 → spring(不受 MA 趋势影响)

**验收**: 事件序列匹配时相位正确; 无事件序列时回退 MA; 理论一致性 > 55%; ruff clean

**文件边界**: `engine.py` 检测器链顺序

---

## 2. 并行执行矩阵

| Wave | 任务 | 文件冲突 | 依赖 | 说明 |
|---|---|---|---|---|
| **A**(并行 3 路) | P0(flag+框架) / P1(WSS 混合) / P2(共振过滤) | engine.py 不同区段(P0:800-830, P1:1290-1370, P2:1500-1530) | 无 | 3 个 subagent 改 engine.py 不同函数, 无冲突 |
| **B** | P0(投票制多周期) | 依赖 A 的 flag 框架 | P0 flag 就绪 | 启用多周期投票 |
| **C** | P3(检测器顺序) | engine.py 链顺序 | P0 投票制 | 调整优先级 |
| **D** | 全量重扫 + 理论一致性验证 + 文档 | — | A+B+C | 6 期多周期验证 |

## 3. 验收状态跟踪表

| 任务 | 状态 | 新增测试 | 回归(62) | ruff | 理论一致性 |
|---|---|---|---|---|---|
| P0 | ☐ | 5 | ☐ | ☐ | ☐ (>55%) |
| P1 | ☐ | 5 | ☐ | ☐ | ☐ (A>0%) |
| P2 | ☐ | 4 | ☐ | ☐ | ☐ |
| P3 | ☐ | 4 | ☐ | ☐ | ☐ (>55%) |

**预期最终效果**: 理论一致性 50%→65%+; accumulation↔distribution 双向混淆从 74+63 降至 <50; 置信度分布 A>0%、D<80%; 共振过滤增益 +0.5% fwd。