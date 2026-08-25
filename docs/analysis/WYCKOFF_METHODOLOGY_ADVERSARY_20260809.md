# Wyckoff 方法论多轮对抗性分析 — 判定报告

> 对象：`WYCKOFF_METHODOLOGY_SETTING_20260807.md`（跨期正交解耦方法论）
> 方法：12 路红蓝对抗 + 第 3 个独立窗口（W3 as-of 2026-05-29，5755 只全量，本报告专属新增实证）+ 落地代码核验
> 日期：2026-08-09

---

## 零、对抗总表（先给判定）

| # | 攻击面 | 攻击方法 | 证据（三窗） | 方法论裁决 |
|---|---|---|---|---|
| 1 | spring 仅 leader 池内有效 | leader×spring 交互 | W1 −5.57% / W2 −7.50% | ❌ **证伪**（spring 消解 alpha） |
| 2 | 结构分 IC 符号稳定性门 | 三窗 IC | −0.083 / +0.032 / **−0.073** | ✅ **成立**（2/3 负，符号翻转，无排序力） |
| 3 | phase 完全无方向 | 四相位三窗回归 | markdown 双窗 p=0.000/-1.23 | ⚠️ **过强声明**（markdown 是真风控方向） |
| 4 | leader 内结构分低弱 | leader 分层 | 低分更好 6.53/8.00 | ❌ **结构分 predictive 反转** |
| 5 | utad/vdb/pnf 有独立 alpha | 事件扫描 | utad 符号不稳 −0.59/+0.94 | ❌ 无 |
| 6 | leader 集合稳定 | 跨窗重合 | 30 日中仅 **15.9% 重合** | ❌ **高换手信号** |
| 7 | leader MWU 双窗显著 | 检验口径 | W2 仅 Welch t 0.013、**MWU 0.263** | ⚠️ **显著性不稳** |
| 8 | 引擎方向候选池逻辑 | 实际输出 | W1 做多 +4.07 / W2 −4.42 | ❌ **引擎输出方向也符号翻转** |
| 9 | 决策链 DAG（accum/markup∧leader） | 组装测试 | W2 −1.39 / W3 −1.76（vs leader 单独 +2.12/+6.54） | ❌ **DAG 方向淘汰 leader 好子集** |
| 10 | 真实 alpha 来源 | leader×phase 分解 | **distribution** 内 +5.85/+4.09/**+9.07** | 🆕 **修正方法论核心** |
| 11 | 显著性口径问题 | Welch vs MWU | W2 MWU 0.263 | ⚠️ 需稳健检验 |
| 12 | leader 内 Wyckoff 组件增量 | gate 扫描 | 置信 A/B、markup **全部零增量甚至拖累** | ❌ **Wyckoff 组件在 leader 内无 add-on** |

---

## 第一轮：方法论内部逻辑攻击（无新数据）

**攻击点 A — spring 的定位自相矛盾**。方法论 Layer2 说"spring 是无独立 alpha 原力的扳机，仅在 leader 池内有效"，但 §六又说"spring 轻仓试探仅在 leader 内允许"。若 spring 本身无 alpha，为什么还要在 leader 内保留？逻辑上 spring 在 leader 内必然是 explain：要么 spring 做多 → 与 leader×spring 负超额冲突；要么 spring 无做多 → 方法论在 system 内错配了触发器与 alpha 源。

**攻击点 B — 决策链与证据错配**。方法论 Layer0-Layer4 的解耦本身合理，但 §六把"RS=leader 电子门"作为落地，而 DAG 又把 phase∈{accum,markup} 作为 gate——两者都未经验证。方法论把 leader 唯一正 alpha 的池子开在 accum/markup，而未检查 leader 在哪一个 phase 里真正正。

**攻击点 C — 样本不齐**。方法论基于更窗口（W1/W2），且 W2 领袖 MWU 不显著；n 极小（active 池 40-137）。

判定：方法论 **内部逻辑严密但实证基础不足** → 需要第 3 窗攻击验证。

---

## 第二轮：实证攻击（新增 W3 窗口 → 三窗韧性测试）

本轮引入独立于方法论归纳样本的 W3（as-of 2026-05-29，全量 5755），对方法论四支柱做符号稳定性裁定：

### 支柱1：leader 超额（✅ 部分成立，但被限定在 distribution）
```
W1  +5.18% (p<0.001)   W2  +2.12% (ns, MWU 0.26)   W3  +6.54% (p<0.001)
```
仅"leader 偶 然为正"的均值先不成立，2/3 窗 MWU 显著。
**但更强的事实**：leader 的超额几乎全部来自 distribution 相位——

```
leader × distribution:  W1 +5.85%  p=7.9e-6
                        W2 +4.09%  p=0.0067
                        W3 +9.07%  p=1.2e-7
```

distribution 相位内 leader（其含义是"在市场派发/弱势时相对强势"）**三窗显著为正且超越 leader 平均**。方法论 DAG 要求的 phase∈{accum,markup} 恰恰把市场派发期的强势个股排除掉——**DAG 方向明显错配**。

### 支柱2 structure_score
- 三窗 IC：−0.083 / +0.032 / **−0.073**。方法论符号稳定门 |IC|>0.03 且同号 ≥3 窗 × 被否：**需 2 负 1 正**，未满足。结构分**确无排序力**成立。
- 且 W1/W3 的 IC 为**显著负** → 结构分不是"无信息"而是**反向**了 leader（ρ=−0.07/−0.14）。在 leader 内部，**结构分低的更好**（6.53/8.00 vs 高分 3.83/5.07）→ 高结构分不仅无益，还是劣势标记。

### 支柱3 spring
- leader×spring: W1 −5.57% (n=4) / W2 −7.50% (n=15)。方法论 Layer2"spring 仅在 leader 池内触发" → **被 300 窗实证证伪**，spring 触发反而消除 leader 优势。方法论 §六第 3.2 条就错了。

### 支柱4 事件/其他
- utad 双窗 −0.59/+0.94 不显著；pnf/vdb 无稳定 alpha → 这些组件在 leader 内零增量（对抗面12）。

判定：**四个支柱中 2 个需修正，2 个无效**。

---

## 第三轮：显著性口径攻击（统计方法）

方法论宣布 leader 为"双窗显著"（red-blue §五）；但对抗检验：
- **W2**：Welch t = 0.013（均值显著性） vs **Mann-Whitney U = 0.263（分布显著性）**。在均值偏、方差大（α异常大）时，t 检验偏向均值；MWU 对秩更稳健。
- 且 W1 组里 leader 超额>0 占比仅 52.8%，W2 42.1% → 说明"leader 平均为正"很大程度来自**右尾的少数高收益**，而非位置偏移。右侧有 40% 以上 leader 股票超额为负。
- 判定：**显著声明（"leader 双窗显著 p<0.001"）过度，至少 1/3 窗口（W2）不稳健**。后续任何宣称需要 MWU + 中位数 + 位移三口径一致。

---

## 第四轮：落地可行性（生产 engine）—— 结论：方法论的可执行 DAG 处存在死结

方法论建议"leader 电子门"落地于 `_step5`。核验 `engine.py:1421-1422`：

```python
elif step1.phase == WyckoffPhase.DISTRIBUTION:
    direction = "空仓观望"
```

**production RIGHT NOW 的 distribution 分支把 leader∧dist 全部输出为"空仓观望"**（W3 实证：321 只 leader∧dist 候选=空仓）。而方法论自身发现的唯一三窗显著信号正是 leader×distribution。因此：
- 若落地"leader 电子门"，只会在 plan TAGN 层产出"空仓"，候选池 5.6% 中全部不可操作 → 方法论**无法通过现有生产 engine 兑现**。
- 要兑现必须推翻 distribution 禁做空硬编码（研究平台禁做空的目的主因，但 leader∧dist 不需做空，是"多"方向）→ 产生 policy 矛盾：A股铁律?、Wyckoff 理论? 同一条线 conflict。
- 判定：方法论单层正确（状态≠方向）但**落地路径在 engine 与实证之间断裂**。

---

## 第五轮：方法论 vs 更优解 —— 是否存在"真信号"？

对抗性地寻找方法论之外更好的组合：

| 信号 | 三窗平均超额 | 三窗 MWU 显著次数 |
|---|---|---|
| **leader × distribution** | **+6.34%** | **3/3 (p<0.01 all)** |
| leader (all phases) | +4.61% | 2/3 |
| markup (all) | +2.66% | 0/3 (符号不稳) |
| accumulation | −2.57% | 3/3 负 (10% 违背理论) |
| markdown | −3.33% | ⚠️ 唯一稳定负 → 用作风控闸 |
| spring | −2.33% | 无 |

**关键**：
1. **积累/派发 → 证据全指向"相位作为方向"的反解**：accumulation 3/3 负、distribution 3/3 正（反做空）；方法论"相位不作方向"仍成立，但它的替代方向是**"distribution 加多"**而非"accum 加多"。
2. **leader×distribution** 是唯一同时通过"三窗显著 + 三窗 +"的信号——**这是方法论应立足的轴**，而不是 layer1 的纯 leader 或 DAG 的 accum/markup。
3. **markdown 是最强 "方向" 信号（3/3 负）** → 方法论 Layer0 风控闸 position 正确，甚至应升为"退出/空仓"（不只排除）。

---

## 最终判定

**方法论核心原则（状态≠方向≠排序、结构分弃用、markdown 风控）→ 成立（A 级），但有两处结构性错误：**

| 方法论声明 | 判定 | 修正 |
|---|---|---|
| leader = 唯一 alpha 轴 | ⚠️ 成立但过泛 | **细化：alpha 集中于 leader∧distribution（三窗显著）**，leader 单独仅在 2/3 窗显著 |
| spring = leader 内扳机 | ❌ 证伪 | spring 负超额，leader 内反而更差 → 降为"观察"，不从 transmitter |
| phase∈{accum,markup}=D核入 | ❌ 方向错误 | 应由 `leader∧distribution`（+6.34%）替代；markup 不稳 |
| layer3 结构分弃用 | ✅ | 成立且更极端：leader 内高分是劣势标记 |
| markdown 风控 | ✅ | 成立，且可作执行级退出（3/3 负） |

**行动修正（对方法论 §六 的修订）**：
1. **唯一可落地信号改为 `RS=leader ∧ phase=distribution`（做多方向）**——n≈290/窗（5.6% 池），三窗 MWU 全显著；在 engine 内新增分支允许该子集"买入/轻仓试探"，并**单测验证 leader∧dist 不被空仓**。
2. **spring 从"leader 内触发"降级为"通用观察触发器"（不进 decision）**——不再做多。
3. **结构分不作为 leader 内再分层**（否则反而取低分）。
4. **markdown 作为全局 exit/占位 gate**（与方法论一致，无需改）。
5. **验证从严：新增 MWU + 中位 + 位移占比 + 三窗同号门（而非仅 Welch t）**，防重演 W2 假显著。

**方法论总体评级：B-（成立框架 + 内置错误轴 + 落地冲突）**。经此对抗，真正值得保留的核心就是一个 3 字句子：

> **Wyckoff 的价值不为 phase 标签，而在"派发阶段里靠相对强弱（relative strength = leader）做多"——且衍生事件(spring/结构/评分)均无增量。**

—— 一切其他 Wyckoff 理论信号不是不相关，而是**被生产 `_step5` 的 phase 直出映射和置信加权放大掩盖且错配**。