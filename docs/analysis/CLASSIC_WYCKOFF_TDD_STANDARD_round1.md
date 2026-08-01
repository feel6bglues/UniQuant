# Round 1 红蓝对抗 — 顶尖交易员 + 量化金融架构工程师

**对阵**: R1-交易员（经典 Wyckoff 应用实战视角）vs B1-架构师（系统完整性视角）
**目标文件**: `CLASSIC_WYCKOFF_TDD_STANDARD_v0.md`

---

## R1-01（交易员·Red）: P&F 优先原则忽略了大资金行为

**声明**: 标准 P1 要求"所有结构分析必须基于 P&F 图"——但经典 Wyckoff 交易员实际看的是**价量行为**，P&F 只是辅助。Tom Williams (VSA) 学派甚至认为 P&F 没有大资金行为信号重要。

**证据**: 经典 Wyckoff 的核心是"Following the Composite Operator（复合人/大资金）"，大资金的足迹在**成交量分布**（Volumne Profile）上比 P&F 更明显。BC 和 SC 的定义本身需要量能[天量]+价格特征，而非 P&F 列。

**建议**: 将 P1 改为"P&F 优先 + 量价行为验证"——两种视角出现矛盾时，以量价行为为裁决依据。

---

## R1-02（交易员·Red）: Phase C Spring 的量化定义忽略稀释能力

**声明**: ES-05 定义 Spring 为"O 列短暂跌破 TR 下沿后立即收回 + 量能萎缩"。实际 Spring 需要看的是：
1. 跌破深度 < TR 下沿 10%（超过 10% 是 breakdown 不是 spring）
2. 收回后的 3 根 K 线不能再次触及该低点（二次确认）
3. 量能萎缩需要与之前的 ST/SC 量能对比，不应有绝对值标准
4. **最重要的是**：Spring 发生时 TR 下沿已经被多次测试（Time Spent at the Low）

**建议**: 将 Spring 的 4 个条件全部纳入 ES-05 定义，否则会有大量假 Spring（单日跌破立即收回但后面继续跌）。

---

## R1-03（架构师·Red）: MT 层缺少跨周期 Phase 冲突的权值协议

**声明**: MT-03 定义了"三周期对齐/两周期/全不一致"三种状态，但没有定义**当多周期冲突时，日线分析应该放弃还是部分保留**。例如：月线=Accumulation，周线=Markup，日线=UNKNOWN。

**建议**: 增加 MT-05 "冲突解决方案":
- 月线 = Accumulation / Distribution → 周线/日线均不能 Markup/Markdown（override）
- 月线 = UNKNOWN → 以周线为准
- 周线 = UNKNOWN → 以日线为准
- 三周期任何两周期一致 → 第三周期与主流矛盾时标记为"divergent"

---

## R1-04（架构师·Red）: Cause→Effect 的测量窗口定义不完整

**声明**: PF-06 定义了 Count Target = "TR 宽度列数 × box_size × 乘数"，但没有定义：
1. TR 宽度从哪一列开始计数（SC 后的第一列 ST？还是从 Phase B 的第一列？）
2. 计数方向（向上仅 O 列突，向下仅 X 列突破）
3. A 股的涨跌停对 P&F 测量的截断效应

**建议**: 增加 Count Target 的乘数选择规则（参考 Hank Pruden：大 TR→2x, 中 TR→1.5x, 小 TR→1x），以及涨停/跌停时测量计数的截断规则。

---

## R1-05（交易员·Red）: 没有 Position Sizing 与 Wyckoff 的关联

**声明**: 标准完全不涉及仓位管理。经典 Wyckoff 有完整的 Position Sizing 规则：
- Phase A: 0%（观察）
- Phase B: 视 ST 次数——第一次建仓 20%（SC 后第一次 ST），第二次加仓 20%（ST 确认）
- Phase C: Spring → 再加 20%
- Phase D (breakout): 满仓 100%
- Phase E (Markup后期): 逐步减仓
- UTAD: 清仓

**建议**: 增加 Position Sizing 模块在 L4 层。如果一个"Wyckoff 引擎不输出仓位管理建议"，它不完整。

---

## R1-06（架构师·Blue）: RS 层过于简化

**声明**: RS-01~04 将相对强弱简化为 4 种类型。实际 Wyckoff 的相对强弱至少需要 3 个时间段：
- 短期（20 天）：趋势动量
- 中期（60 天）：大盘/个股互动
- 长期（200 天）：大资金方向

**建议**: 将 RS 层改为多时间框架的 RS 向量（RS_20, RS_60, RS_200），而非单一分类。每个时间尺度的 RS 独立计算，最后形成 RS 签名。

---

## 裁决

| ID | 立场 | 严重 | 判决 |
|----|------|------|------|
| R1-01 | 交易员 🏆 | HIGH | v0 P1 过激，改为"P&F + Volume"双视角 |
| R1-02 | 交易员 🏆 | HIGH | Spring 条件需补全 4 项 |
| R1-03 | 架构师 🏆 | MED | 增加冲突解决方案 MT-05 |
| R1-04 | 架构师 🏆 | MED | Count Target 测量窗口需明确 |
| R1-05 | 交易员 🏆 | MED | 增加 Position Sizing L4 组件 |
| R1-06 | 架构师 🏆 | LOW | RS 层改为多时间框架向量 |
| R1-07 | 交易员+架构师 💙 | — | L0-L4 分层正确，事件序列定义清晰 |

**Round 1 修正**: 6 Red 🏆 / 1 Blue 💙 → v1 需更新 P1, ES-05, MT section, PF-06, RS section, 新增 Position Sizing
