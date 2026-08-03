# Wyckoff 经典重构最终任务清单（2026-08-03）

> 三视角(交易员/算法工程师/量化金融专家)红蓝对抗, 基于真实代码核实, 严格 TDD

---

## 0. 代码事实基线（本次核实确认）

| 事实 | 位置 | 证据 |
|---|---|---|
| 检测器链 winner-takes-all, markup 优先 | `engine.py:802-819` | `detectors = [markup, dist, markdown, accum, spring, utad, sos]; for d in det: break` |
| PnF 短路 63.2% 标的 | `engine.py:829-836` | `if pnf_hint in ("accumulation","distribution"): phase = ...` |
| `_calc_confidence` 硬编码 A/B+/C 旁路 | `engine.py:1306-1376` | 先检 A/B+/C bypass, 最后 fallback `rule8_confidence_matrix` |
| `_apply_structural_adjustment` 已调置信度 | `engine.py:89-138` | 结构分 ≥55 升 1 级 / ≤45 降 1 级 |
| WSS 默认关 | `engine.py:202-212` | `wss_enabled: false` |
| 共振未入决策 | `engine.py:1540-1700` | `_build_report` 无共振引用 |
| `_analyze_multiframe` 已实现 | `engine.py:340-420` | 周线/月线重采样 + 三周期分析 |
| `MultiTimeframeResonance` 已实现 | `phase_analysis.py:401-443` | 3 周期投票, 8 测试 |
| 事件序列检测在 step3 运行 | `engine.py:990-1030` | `detect_all_events` 在 step3 内部 |
| `rule8_confidence_matrix` 5 条件矩阵 | `rules.py:247-291` | met_count≥4=A, ≥3=B, ≥2=C, else=D |

---

## 1. 任务清单（经三视角红蓝对抗核实）

### P0 【检测器链重构】三周期独立分类 + 事件序列投票制

**三视角红蓝对抗**:

| 视角 | 红方攻击 | 蓝方辩护 | 终裁 |
|---|---|---|---|
| **交易员** | "目视 Wyckoff 必看多周期, 单日线判定是错的。但 `multi_timeframe=True` 才启用意味着默认路径仍用旧方法" | "月线/周线/日线一致性是 Wyckoff 灵魂, 必须启用" | **保持 multi_timeframe 守卫, 但** 将 `multi_timeframe` 默认从 `False` 改为 `True`(已有 `analyze(df, multi_timeframe=True)` 路径) |
| **算法工程师** | "多周期重采样有性能开销, 周线/月线需 100+/12+ 根 K 线, 部分标的过短" | "`_analyze_multiframe` 已实现, 重采样是向量化操作(<1ms/只)" | 接受。短标的自动走 `_analyze_single` 回退路径 |
| **量化金融专家** | "50% 理论一致性是结构性问题, 仅改投票制不够——事件序列检测必须也前置" | "投票制 + 事件序列压倒(PS+SC+ST×2) 组合才能解决" | **P0 + P3 必须合并执行**: 投票制 + 事件序列优先, 缺一不可 |

**终裁**: P0 与 P3 **合并为一项**。新检测器逻辑:
1. `multi_timeframe=True` 时: 三周期共振投票决定基础相位
2. 事件序列(PS+SC+ST×2)压倒共振结果 → accumulation
3. UTAD 压倒共振结果 → distribution
4. `multi_timeframe=False` 时: 保持旧 winner-takes-all 作为 fallback

**代码触点(已核实)**:
- `engine.py:802-819` 检测器链循环
- `engine.py:829-836` PnF 短路
- `engine.py:545-580` `_detect_accumulation` 事件序列路径
- `engine.py:582-620` `_detect_markup` MA 趋势
- `engine.py:638-678` `_detect_markdown` MA 趋势
- `phase_analysis.py:401-443` `MultiTimeframeResonance`
- `engine.py:263-270` `analyze(df, multi_timeframe)` 默认改为 `True`

**TDD 测试**: `tests/classic_wyckoff/test_p0_voting_chain.py`
- T1: `multi_timeframe=True` + 共振 bullish + 无事件序列 → markup
- T2: `multi_timeframe=True` + 共振 bullish + PS+SC+ST×2 → **accumulation**(压倒)
- T3: `multi_timeframe=True` + 共振 conflicting + UTAD → **distribution**(压倒)
- T4: `multi_timeframe=False` → 旧行为不变(62 回归)
- T5: 短标的无多周期数据 → 回退单周期

**验收**: 旧行为 62 测试全过; 新投票制下 accumulation fwd > -8%(从 -10.30% 改善); 理论一致性 > 55%

---

### P1 【WSS 置信度混合】WSS 评分作为置信度矩阵的补充维度

**三视角红蓝对抗**:

| 视角 | 红方攻击 | 蓝方辩护 | 终裁 |
|---|---|---|---|
| **交易员** | "84% D 档对交易员来说是对的——84% 的股票确实不该交易。我不想看到更多 A 档, 我想要更少的假信号" | "当前 0% A 档意味着最佳 setup(Spring+LPS+BC) 也无法获得高置信度, 这是死路径" | **保持 A 档门槛, 但用 WSS 补充中间档(C→B, B→A)的区分度** |
| **算法工程师** | "`_apply_structural_adjustment` 已用结构分调了置信度。再加 WSS 是重复调" | "结构分影响 ±1 级, WSS 是事件序列统计评分, 两者正交——结构分看完整度, WSS 看历史胜率" | WSS 作为**额外条件**加入 `rule8_confidence_matrix`, 增加 `wss_qualified` 第 6 条件 |
| **量化金融专家** | "WSS 训练在 f6=126d, 生产用 fwd_20d, 时间口径不匹配" | "WSS 的排序是序数——高分序列在不同时间窗口下保持高分" | 接受。但需要先验证 WSS 在 fwd_20d 下的 Spearman 秩相关 > 0.3 |

**终裁**: WSS 不作为置信度替代或混合, 而是作为 `rule8_confidence_matrix` 的**第 6 条件**(`wss_qualified`)。当 WSS 评分 > 0.04 时, 条件满足, 矩阵从 5 条件变为 6 条件, 自然提升 A/B 档的触发率。

**代码触点(已核实)**:
- `engine.py:1306-1376` `_calc_confidence` 硬编码 if/elif
- `rules.py:247-291` `rule8_confidence_matrix` 5 条件
- `engine.py:202-212` WSS 接线
- `sequence.py:141-182` `WyckoffScorer` / `WSSScorer`

**TDD 测试**: `tests/classic_wyckoff/test_p1_wss_6th_condition.py`
- T1: WSS 评分 > 0.04 时 `wss_qualified=True`, 6 条件中 ≥5 → A 级
- T2: WSS 评分 < 0.04 时 `wss_qualified=False`, 回退 5 条件矩阵
- T3: WSS 无匹配时 `wss_qualified=False`, 不报错
- T4: `wss_enabled=false` 时 `wss_qualified=False`, 行为不变

**验收**: 置信度 A 档 > 0%; 各档 fwd_20d 单调; 无 WSS 标的回退不变; ruff clean

---

### P2 【共振过滤接入决策】MultiTimeframeResonance 过滤信号

**三视角红蓝对抗**:

| 视角 | 红方攻击 | 蓝方辩护 | 终裁 |
|---|---|---|---|
| **交易员** | "bearish 共振 + 买入是 +2.83% 最佳子策略, 绝不能过滤掉" | "bullish 共振 + 买入 = -2.85% 是亏损信号, 必须过滤" | **单向过滤**: 仅在 `bullish 共振 + 买入信号` 时降级, `bearish 共振 + 买入信号` 保留 |
| **算法工程师** | "`multi_timeframe=True` 时才可用, 默认 `False` 意味着多数调用不受益" | `multi_timeframe` 默认改为 `True` 后(P0), 所有调用都受益 | 依赖 P0 的 `multi_timeframe` 默认改 `True` |
| **量化金融专家** | "`multiframe_aligned` 已在置信度矩阵中作为第 5 条件, 再加共振过滤是重复" | "`multiframe_aligned` 是二值(对齐/不对齐), 共振是四值(bullish/bearish/conflicting/unknown), 信息量更大" | 不对齐(Loss)。共振过滤作为**信号降级层**, 置信度矩阵仍用 `multiframe_aligned`。两层正交 |

**终裁**: 在 `_build_report` 中, 当 `multi_timeframe=True` 时:
- `resonance_dir=bullish` + 买入信号(markup/spring) → 信号降 1 级
- `resonance_dir=bearish` + 买入信号 → 保留(最佳子策略)
- 卖出信号同理: bearish 共振 + 卖出 → 降级, bullish 共振 + 卖出 → 保留

**代码触点(已核实)**:
- `engine.py:1540-1700` `_build_report` 信号判定
- `engine.py:263-270` `multi_timeframe` 参数
- `phase_analysis.py:401-443` `MultiTimeframeResonance`

**TDD 测试**: `tests/classic_wyckoff/test_p2_resonance_filter.py`
- T1: `multi_timeframe=False` → 无过滤
- T2: `multi_timeframe=True` + bullish 共振 + markup → 降 1 级
- T3: `multi_timeframe=True` + bearish 共振 + spring → 保留
- T4: `multi_timeframe=True` + bullish 共振 + 卖出 → 保留

**验收**: 现有测试全过; 共振过滤后 markup 信号 fwd 收益 ≥ 过滤前; ruff clean

---

### P3 【检测器优先级调整】事件序列检测器移至链首

**三视角红蓝对抗**:

| 视角 | 红方攻击 | 蓝方辩护 | 终裁 |
|---|---|---|---|
| **交易员** | "Spring/UTAD 是我最看重的信号, 它们应该在链首。当前被 MA 趋势压住, 我永远看不到 Spring 信号" | "完全同意。Spring 是最强单一事件(+3.00%), 但仅 1.5% 覆盖率, 当前被 markup 吃掉了" | **事件序列检测器移至链首**, Spring/UTAD/accumulation(event) 在 markup 之前 |
| **算法工程师** | "事件序列检测(`detect_all_events`)已在 step3 运行, 移至 step1 无额外开销" | "但 step1 时 events 尚未检测——需要提前运行或复用 step3 结果" | 在 `_step1_phase_determine` 内提前调 `detect_all_events`, 结果缓存供 step3 复用 |
| **量化金融专家** | "事件序列覆盖仅 ~5%, 即便移至链首, 95% 标的仍由 MA 决定" | "5% × 5374 = 269 只标的。这 269 只的相位正确率从 50%(随机) 提升到 ~70%, 贡献显著" | 低覆盖率不是问题, 是**信号纯度**。随时间推移可扩充事件序列覆盖 |

**终裁**: 新检测器顺序:
1. `_detect_accumulation(event)` — PS+SC+ST×2 事件序列
2. `_detect_spring` — Spring 形态
3. `_detect_utad` — UTAD 形态
4. `_detect_markup` — MA 趋势(fallback)
5. `_detect_distribution` — TR+prior_trend(fallback)
6. `_detect_markdown` — MA 下跌(fallback)
7. `_detect_sos` — 空

**代码触点(已核实)**:
- `engine.py:802-819` 检测器链表
- `engine.py:545-580` `_detect_accumulation` 事件序列路径
- `engine.py:693-700` `_detect_spring` (K线形态)
- `engine.py:700-715` `_detect_utad`
- `engine.py:582-620` `_detect_markup` (MA 趋势)
- `engine.py:638-678` `_detect_markdown` (MA 趋势)

**TDD 测试**: `tests/classic_wyckoff/test_p3_detector_priority.py`
- T1: 事件序列 PS+SC+ST×2 匹配 → accumulation(即使 MA 向上)
- T2: UTAD 匹配 → distribution(即使 MA 向下)
- T3: Spring 匹配 → spring(不进入 markup)
- T4: 无事件序列 → 回退 MA 检测器(markup/markdown)
- T5: 缓存事件序列结果供 step3 复用

**验收**: 事件序列匹配时相位正确; 无事件序列时回退 MA; 理论一致性 > 55%; ruff clean

---

## 2. 并行执行矩阵

| Wave | 任务 | 文件 | 冲突 | 依赖 |
|---|---|---|---|---|
| **A**(并行 3 路) | P0(投票框架) / P1(第 6 条件) / P2(共振过滤) | engine.py 不同函数(P0:800-830, P1:1290-1370, P2:1540-1700) + phase_analysis.py + rules.py | 无 | 无 |
| **B** | P3(检测器顺序) | engine.py:802-819 链顺序 | 与 P0 同文件但不同行 | P0 先完成(避免冲突) |
| **C** | 全量重扫 + 6 期多周期验证 + 文档 | — | 无 | A+B |

## 3. 验收状态跟踪表

| 任务 | 状态 | 新增测试 | 回归(62) | ruff | 理论一致性 | 核心指标 |
|---|---|---|---|---|---|---|
| **P0** | ☐ | 5 | ☐ | ☐ | ☐ (>55%) | accum fwd > -8% |
| **P1** | ☐ | 4 | ☐ | ☐ | ☐ (A>0%) | A 档 > 0% |
| **P2** | ☐ | 4 | ☐ | ☐ | ☐ | markup fwd ≥ 过滤前 |
| **P3** | ☐ | 5 | ☐ | ☐ | ☐ (>55%) | accum↔dist 混淆 < 50 |

**预期最终效果**: 理论一致性 50%→65%+; accumulation fwd 从 -10.30% 改善至 > -8%; 置信度 A 档 > 0%; 双向混淆从 74+63 降至 < 50。