# 红蓝对抗 — Round 2: Wyckoff A-E 状态机方案验证

> **日期**: 2026-07-24  
> **范围**: Wyckoff 全量分析方案 (计划 §2.1-2.8) — TR检测 + 成交量价差 + A-E 状态机 + 事件标注 + Spring/UTAD + 贝叶斯置信度  
> **基准**: 当前代码 (`engine.py:1616行`) + Walk-Forward Wyckoff 发现 (Spring 0/600触发, UTAD 永远None, "买入"唯一有效信号)  
> **方法**: 逐声明对抗

---

## 声明 1: 多周期 TR 检测器 (`tr_detector.py`) 能在日/周/月线上可靠识别交易区间

**Blue (方案正确)**: 多周期 TR 检测是标准 Wyckoff 方法。日线 range < 20% + 趋势 < 5% 连续 30 天，加周/月线更大尺度——这种分级检测覆盖了不同时间框架的 TR。

**Red (方案有缺陷)**: 
1. **参数过于刚硬**: "范围 < 20% + 短趋势 < 5% 连续 >= 30 天"——A 股牛短熊长，上涨时 range 远 > 20%，下跌时单边趋势轻易 > 5%。TR 被定义为"盘整"，但 A 股的盘整往往较短 (10-20 天) 就被突破。30 天门槛过滤掉了大多数真实 TR。现有代码 `_step0_bc_tr_scan` 使用 rolling_30d 作为 TR fallback 而非严格的 TR 检测——这暗示纯趋势条件在 A 股上 TR 检测效果不佳。

2. **周/月线数据可用性**: plan 说 `_resample_ohlcv` 已实现 (`engine.py:108-125`)，写 weekly/monthly 只需调用它。但 A 股很多股票的周/月线数据需要 >5 年才能产生有意义的周线 (52×5=260 根) 和月线 (12×5=60 根) TR。walk-forward 用 120-200 天窗口的数据不足以产生有意义的周 TR。

3. **多周期冲突未处理**: 当日线 TR 和周线非 TR 同时成立时，裁决逻辑缺失。日线显示盘整，周线显示上涨趋势——这是最典型的情况，但无规则决定哪个周期主导。

**验证**: 对 golden_20 运行当前 `_step0_bc_tr_scan`，统计 TR 检出率。预期显著低于 Wyckoff 文献报告的典型值。

**裁决: Red 🏆** — TR 检测参数不适应 A 股结构，多周期冲突未处理。现有 rolling_30d fallback 已暗示纯条件检测的局限。

---

## 声明 2: 成交量价差分析 (`volume_spread.py`) 能产生有意义的供求分类

**Blue (方案正确)**: 5 矩阵分类 (SOS/LPS/Neutral/SOW/Drying up) + Effort vs Result 背离是 Wyckoff 的核心工具。公式化后逻辑清晰。

**Red (方案有缺陷)**: 
1. **A 股成交量质量**: A 股成交量存在显著的 T+1 结构特征、大宗交易、对倒交易等非 Wyckoff 供求因素。放量缩量不一定反映真实供求——涨停板的特征是缩量（无卖盘），不是"供应枯竭"。

2. **Volume MA20 在 A 股上的适应性**: A 股换手率远高于美股 (A 股日均 1-3% vs 美股 0.5-1%)，且新股/次新股数月内成交量逐月下降。MA20 成交量均值对新股前 6 个月不适用。

3. **EFFORT_NO_RESULT 在 A 股上的歧义**: "放量盘整"在 A 股中可能意味着吸筹 (机构买入)、派发 (机构出货)、或量化多空博弈。方案中的 5 天累加对比缺乏方向性区分能力。

**验证**: 对 golden_20 中已知的 accumulation/markup 阶段运行 volume_spread 分类，计算 SOS/SOW 准确率。

**裁决: Red 🏆** — 分类矩阵理论正确但适用性在 A 股成交量质量下打折扣。5 天背离累加缺乏统计显著性验证。

---

## 声明 3: A-E 相位状态机 (`phase_machine.py`) 能正确追踪 Wyckoff 阶段演变

**Blue (方案正确)**: 从 UNKNOWN → ACC_A → B → C → D → E → MARKUP 的转换逻辑基于 Wyckoff 标准理论。Hysteresis 机制 (3 bar 确认) 减少震荡市误切换。将当前简单 if-else 链条改为状态机是工程改进。

**Red (方案有缺陷)**: 
1. **当前代码已有 A-E 分类**: `classifiers.py:168-185` 的 `classify_accumulation_sub_phase` 已将 accumulation 分为 Phase A-D (依据 SC/Spring/SOS 位置)，`classify_distribution_sub_phase` 也有类似逻辑。计划的状态机不是"新增"而是"重写"。存在重复设计风险。

2. **A 股上完整 A→E 链极罕见**: Walk-forward 已证明 accumulation 阶段 (无论是何种 A-B-C-D-E) 的整体回报低于 markup——A 股更多是 V 型反转 (跳空启动→持续上涨) 而非经典 Wyckoff 缓慢积累过程。一个完整 A→E 周期通常需要 6-18 个月，而 walk-forward 用 120 天窗口，5000 只 × 6 窗口 = 30000 观测中 Spring 触发率 = 0。

3. **状态转换的不可逆行为**: 状态机假设 ACC_A→B→C→D→E→MARKUP 顺序发生。但 A 股中常见 SC 出现后 price 直接 V 型反弹 (跳空启动 markdown→markup 转换)，不经过 B/C/D/E。这是"双底"而非"积累区"。状态机在这种情况下要么输出 UNKNOWN (因为在 ACC_A 等待 B 信号)，要么错误归类。

4. **Hysteresis 的 3 bar 确认在 A 股上的代价**: A 股 T+1 结构下，3 根 bar 的确认意味着至少 3 天。对短线 (3-5 天交易周期) 来说，确认延迟是不可接受的。对中线 (30-60 天) 则合理。

**验证**: 用 walk-forward 的 27 次"买入"信号回溯检查它们在状态机中的位置。如果所有买入都在 MARKUP 阶段 (预期)，则状态机对交易信号的贡献 = 0。

**裁决: Red 🏆** — 状态机工程改进方向正确但 A-E 在 A 股上极罕见 (Walk-forward Spring=0)。V 型反转场景下状态机卡在 ACC_A。Hysteresis 在 T+1 市是代价权衡。

---

## 声明 4: 事件标注器 (`event_labeler.py`) 能可靠检测 SOS/LPS/SOW/LPSY

**Blue (方案正确)**: 事件检测条件明确 (SOS = close新高 + spread>avg + vol>avg*1.5; LPS = SOS后回调 + 缩量)。这些是标准 Wyckoff 事件定义。

**Red (方案有缺陷)**: 
1. **阈值选择未经 A 股优化**: vol>avg*1.5 过滤掉大多数 A 股短期突破——机构大单建仓时往往分单执行，单日成交量 > avg*1.5 但实际是累计 3-5 天的大单。正确做法是累加 3 天成交量而非逐日判断。

2. **SOS 的 A 股适应性**: A 股中"收盘创新高 + spread > avg + vol > avg*1.5"最常见于涨停板 (spread 小、vol 因涨停缩量)。此条件对涨停板不成立。A 股中最强的 SOS 信号是涨停板 (spread 固定 10%/20%、vol 可能缩小)，但条件被 SOS 过滤器排除。

3. **LPS 在趋势中的歧义**: "SOS 后回调缩量"是典型的 A 股上涨趋势中继。但 A 股回调往往伴随成交量自然萎缩 (因为 T+1 导致追涨者被套不愿卖)。放量回调才是 V 型反转信号——方案正好把信号弄反了：A 股 LPS 应该是 SOS→缩量回调(正常)→放量回调(危险)。

**验证**: 对 golden_20 中确定性的 markup 阶段统计 SOS 检出次数/真实 SOS 次数。预期大量真实 SOS (涨停/大阳线) 被过滤。

**裁决: Red 🏆** — 事件定义是标准 Wyckoff 但阈值未 A 股优化。涨停板 SOS 被遗漏。LPS 方向性判断可能颠倒了 A 股的含义。

---

## 声明 5: Spring/UTAD 检测 (`spring_utad.py`) 能产生非零触发率

**Blue (方案正确)**: 新的 Spring 逻辑比现有更强：TR 边界穿透 2% + 次日收回 + 放量=一级/缩量=二级。UTAD 增加了无 TR 时的候选检测。

**Red (方案有缺陷)**: 
1. **Walk-forward 已证明 Spring 触发率 = 0/600**: 当前代码的 `_detect_spring` 使用了比计划更宽松的条件 (振幅>=2%、下影线>实体、close_loc>=0.58) 但 600 个窗口中触发率为 0。计划的新逻辑 (价格<TR_low*0.98 → 收盘>TR_low) 实际上更严格——它需要明确 TR 边界。当前代码已有 TR 边界检测 + Spring 检测但从未触发。计划没有解释为什么新 Spring 逻辑会触发而旧的不触发。

2. **UTAD 永远 None 是设计选择**: 当前 `_detect_utad` 返回 None 不是实现质量问题，而是作者故意选择——Wyckoff distribution 在 A 股上不存在的实证观察。计划用 UTAD 作为"可选事件，不门控"，但不门控的永远不触发的事件等于不存在。

3. **Spring 的理论问题**: Spring 需要在 TR 下边界附近假突破后收回。A 股的 TR 特征不同于美股：A 股重要的底部往往是 V 型 (缩放量后直接拉起) 而非 TR 积累后的 Spring。walk-forward 的 0/600 触发率说明这不是参数问题，是结构问题。

**验证**: 用新 Spring 逻辑对 golden_20 重新检测。如果触发率仍为 0 (大概率)，Spring 在 A 股上确实不存在。

**裁决: Red 🏆** — 0/600 的实证结果压倒理论推理。计划未解释新逻辑如何克服当前代码的零触发率。UTAD 仍然是设计上的 None 函数。

---

## 声明 6: 贝叶斯置信度 (`confidence_v2.py`) 优于当前 A/B/C/D 评级系统

**Blue (方案正确)**: 基于历史胜率的贝叶斯后验估计确实优于当前硬编码的置信度评级。让数据说话而不是人工设定规则。

**Red (方案有缺陷)**: 
1. **冷启动问题**: 新系统统计池 `signal_stats` 从 0 开始。积累到统计显著水平所需的最小观测数 = ~30 (按 CLT 下限)。按 walk-forward 的"买入"信号 4.5% 触发率，30 次信号需要 30/0.045 ≈ 667 个窗口分析。初期至少 3-6 个月的置信度不可靠。

2. **Win-rate 作为先验的问题**: 当前唯一的有效信号是 markup→"买入" (win rate 88.9%, 20d=+13.33%)。如果贝叶斯先验偏向 markup 买入，则所有其他 w 信号都被压到低位。但这恰恰可能是正确行为——承认 Wyckoff 只有这一个信号。如果系统最终输出"只有 markup 买入能用"，那置信度系统只是验证了 walk-forward。

3. **似然函数权重未经验证**: 5 个条件加权 (volume_confirm 0.25 + trend_clarity 0.25 + rr_quality 0.20 + multi_tf 0.15 + event_quality 0.15) 是人为设定的，不是从数据中学到的。如果 event_quality 在 A 股上无预测力 (因为事件不触发)，它的 0.15 权重浪费了。

**验证**: 用 walk-forward 的 600 个窗口回测贝叶斯置信度 vs 当前 A/B/C/D 的预测力。预期两者无显著差异 (因为有效信号只有一种)。

**裁决: Split** — 贝叶斯方向正确但冷启动 ~600 窗口，人为权重未验证。在只有一种有效信号的约束下，复杂置信度系统不会比简单的"是否在 markup + 是否触发买入"二元判定更好。

---

## 声明 7: 基金/ETF 适配有意义 (跳过 Spring/TR, 三级状态)

**Blue (方案正确)**: 基金跳 Spring/TR + 简化为 MARKUP/MARKDOWN/UNKNOWN 三级，比 Wyckoff 忽略基金更好。最少提供了基金的趋势方向信息。

**Red (方案有缺陷)**: 
1. **"基金简化为趋势方向" = 重复 MA 交叉**: 当基金只输出 MARKUP/MARKDOWN 三级，本质上就是 MA5 > MA20 的三分 (MA5>MA20=MARKUP, MA5<MA20=MARKDOWN, 交叉=UNKNOWN)。MA 交叉的成本是 5 行代码，但 Wyckoff 基金适配需要 200+ 行新代码 + 2 层架构修改。

2. **ETF 的特殊结构**: 某些 ETF (如 510050 上证50 ETF) 的价量关系确实反映供求，因为它们被机构用于对冲和套利。但大部分行业 ETF (如 512*** 系列) 成交量低、价差大，Wyckoff 分析无意义。

3. **基金在 walk-forward 中覆盖面为零**: walk-forward 只覆盖了股票。基金适配的 200+ 行代码未经任何实证验证。计划的风险矩阵承认"基金分析等于白做"但不考虑彻底跳过。

**验证**: 用现有 MA 交叉对基金做回测，比较 3 级 Wyckoff 适配 vs 简单 MA 的信号一致性。预期 >95% 一致。

**裁决: Red 🏆** — 基金适配 = 200+ 行代码实现 5 行 MA 交叉的功能。在 walk-forward 零覆盖的情况下，投入产出比极低。

---

## 汇总

| # | 声明 | 裁决 | 关键证据 |
|---|---|---|---|
| 1 | 多周期 TR 检测 | Red 🏆 | 30天参数过滤了A股短TR；多周期冲突未处理；现有 rolling_30d fallback 已暗示局限 |
| 2 | 成交量价差分类 | Red 🏆 | A股成交量质量 (T+1/涨停缩量/对倒) 降低分类可靠性；MA20对次新股不适用 |
| 3 | A-E 状态机 | Red 🏆 | 当前代码已有 A-E 分类；A股 A→E 链极罕见 (Spring=0)；V型反转卡在 ACC_A |
| 4 | 事件标注 | Red 🏆 | 涨停板 SOS 被遗漏；LPS 方向性在 A 股可能颠倒 |
| 5 | Spring/UTAD | Red 🏆 | Walk-forward 0/600 触发率压倒理论；计划未解释新逻辑如何克服零触发率 |
| 6 | 贝叶斯置信度 | Split | 方向正确但冷启动~600窗口；仅一种有效信号下复杂置信度不优于二元判定 |
| 7 | 基金/ETF 适配 | Red 🏆 | ~200 行 = MA 交叉的5行代码功能；walk-forward 零覆盖；风险矩阵承认"等于白做" |

**Red 6🏆 / Blue 0 / Split 1** — Wyckoff 方案的工程改进方向大多正确 (状态机、贝叶斯、事件标注)，但 A 股的结构特征 (V 型反转、涨停板成交量特征、T+1) 使标准 Wyckoff 工具大部分失效。Walk-forward 已证明唯一有效的信号是 markup→买入 (4.5% 触发率)。

---

## 根本问题

Wyckoff 在 A 股上的核心矛盾：

1. **A 股缺少"积累区"**: Walk-forward 证明 Spring=0/600, UTAD=0/600, distribution→SHORT=−16.82% (方向性错误)。不是参数问题，是 A 股结构问题——A 股趋势更多由政策/流动性驱动 (V 型反转/尖顶)，而非 Wyckoff 式的 TR 积累→突破。

2. **唯一有效信号不是 Wyckoff**: markup→买入的 +8.60% 20d spread (p=0.0098) 本质是"强势趋势中的追涨策略"，Wyckoff 理论 (Spring→买入) 从不触发。Wyckoff 框架在此提供的是分类标签而非预测信号。

3. **工程改进不能创造数据中没有的信号**: 更复杂的状态机、更精细的事件标注、更先进的置信度系统，都不能创造 A 股中不存在 Wyckoff 结构这一事实。

**建议**: 
- 将 Wyckoff 从"预测引擎"降级为"标签引擎"——仅提供当前相位分类 (MARKUP/MARKDOWN/UNKNOWN)，不做交易信号
- markup→买入信号提取为独立趋势跟踪指示器
- P&F 点数图和九项测试作为离线研究特征，不集成到生产管线
- Spring/UTAD/P&F 投入压在 walk-forward 后显著降低优先级

---

## 附录: 验证命令

```bash
# 验证 Spring 在更宽松条件下仍为 0
python3 -c "
from scripts.walk_forward_engine import run_wyckoff_on_window
# 对 golden_20 放宽 Spring 条件重测
results = run_wyckoff_on_window(golden_20, window_size=200, spring_threshold=0.95)
spring_count = sum(1 for r in results if r.get('spring_detected'))
print(f'Total windows: {len(results)}, Spring detected: {spring_count}')
"

# 验证当前 A-E 分类在 5000 只股票上的分布
python3 -c "
from scripts.staged_full_scan import scan
results = scan(stage='canary')
from collections import Counter
sub_phases = Counter(r.get('accumulation_sub_phase', 'N/A') for r in results)
print('Sub-phase distribution:', dict(sub_phases))
"
```
