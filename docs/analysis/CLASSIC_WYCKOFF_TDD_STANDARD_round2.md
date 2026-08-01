# Round 2 红蓝对抗 — 量化金融算法工程师 + Python 程序员

**对阵**: R2-算法工程师（统计/回测/信号验证视角）vs B2-程序员（实现/可测试/可维护视角）
**目标文件**: `CLASSIC_WYCKOFF_TDD_STANDARD_v0.md`（参考 Round 1 裁决）

---

## R2-01（算法工程师·Red）: 事件序列 ES-10 的"顺序有效性"无法检验

**声明**: ES-10 要求"事件必须按 Wyckoff 理论顺序出现，跳跃顺序标记为非标准"。

**问题**: 日线数据中事件顺序不是确定的线性序列。Spring 可能出现在 SC 未确认之前（假 Spring），SOS 可能出现在 BC 之前（反弹不是 SOS）。ES-10 没有定义：
1. 事件序列的严格/非严格模式
2. "跳跃"的容忍度——SC 后正好第 K 根 K 线出现 ST 算吗？
3. 同一根 K 线触发多个事件（SC+Spring 同一天）怎么处理？

**建议**: 将 ES-10 替换为 **事件序列的概率匹配**——使用动态规划（类似序列对齐算法）计算观测事件序列与理论序列的最小编辑距离。匹配度 > 0.7 算"标准"，0.4-0.7 算"非标准"，<0.4 算"无效"。

---

## R2-02（算法工程师·Red）: VS-01~06 的成交量签名没有定量阈值

**声明**: VS 签名使用 high_volume / wide_spread / upper_wick 等定性标签。

**问题**: "high_volume" 的阈值是什么？
- 前 50 日均量的 1.5x 算 high？2x？
- 不同股票的波动率差异 >10 倍（茅台 vs 小盘银行股）
- 涨跌停日的 volume 可能因流动性消失而异常低

**建议**: 每个 Volume 签名必须附带数值阈值参数，且阈值可被参数扫描验证：

```python
BC_SIGNATURE = VolumeSignature(
    volume_min_ratio=1.5,      # 均量的 1.5x
    spread_min_pct=2.0,        # 振幅 >= 2%
    upper_wick_min_ratio=0.3,  # 上影线 / 实体的最小比值
    close_zone="upper_third",  # 收盘在当根 K 线的上 1/3
    confirmation_bars=0,       # BC 本身即确认，不需要后续 K 线
)
```

---

## R2-03（算法工程师·Red）: 没有 False Positive Rate 质量控制

**声明**: 标准定义了事件检测的通过条件（PF-01~06），但没有定义**误报率上限**。

**问题**:
- 一个宽松的 Spring 检测器可能在 5000 只股票中每天标记 100 个 Spring——但 95% 都是假信号
- 标准只设 coverage（测试覆盖率），没设 precision（精确率）
- 对比现有 engine：Spring 检测率 22% 但 Spring→买入转换率 0%——说明 Spring 检测本身是噪声

**建议**: 增加 **Signal Quality Control** 层：

```yaml
QualityGate:
  spring_precision: ">= 0.3"    # 触发的 Spring 中至少 30% 在 20 天后有效
  spring_recall: ">= 0.6"       # 至少覆盖 60% 的人工标注 Spring
  breakout_accuracy: ">= 0.7"   # P&F 突破至少 70% 后续确认
  false_positive_rate: "<= 0.1" # 随机数据上误报率 <= 10%
  min_sharpe_signal: "> 0.5"    # 信号组合的夏普比下限
```

每个检测器的 FPR 必须在合成随机数据上测量并记录在测试报告中。

---

## R2-04（Python 程序员·Red）: P&F Builder 没有可测量的终止条件

**声明**: PF-01 定义 X/O 列交替但没说清楚 P&F 的**数据窗口**。

**问题**: P&F 需要看多少数据？
- 5 年日线 → 约 1200 交易日 → 可能 200+ 列
- 3 个月日线 → 约 60 交易日 → 可能 10 列
- 标准没有定义 P&F 构建的最小数据量和最大列数上限

**实际影响**: 一个 200 列的 P&F 图性能开销 $O(n^2)$——builder 每次新 K 线到来时要重新构建全图还是增量更新？

**建议**: 
1. 定义 P&F Builder 的数据窗口协议
2. 定义 builder 的最小和最大列数边界
3. 要求 builder 支持增量更新（O(1) per new bar）

---

## R2-05（Python 程序员·Red）: 测试覆盖率目标与实际可测量性不匹配

**声明**: L0 需要 100% branch coverage，L1 需要 95% line coverage。

**问题**:
- P&F Builder 的 `box_size` 自适应逻辑可能只有 3 个分支，100% 可达
- 但 ES-01 `PS 检测` 在已知历史数据上测试时，如果数据恰好不含 PS 模式，该分支是 0%
- Phase Resolver 的 10 个 Phase 状态，每个状态需要特定的序列数据，合成不可用时覆盖率自动打折扣

**建议**: 将覆盖率指标改为**按模式覆盖率**而非按代码行率：

```
Pattern Coverage:
  □ PS 出现在测试集中 → 测试通过
  □ BC 出现在测试集中 → 测试通过
  □ ...
```

而非：
```
Line Coverage:
  ps_detector.py: 95%   ← 这一条没有意义，因为 95% 的"线"是弹性逻辑不是判定分支
```

---

## R2-06（Python 程序员·Red）: 已知模式测试集 KN-01~06 缺乏标注格式

**声明**: KN-01~06 定义了 6 个已知模式测试，但没有定义标注格式。

**问题**: 测试集文件 `known_patterns.json` 应该是什么结构？没有标注格式定义，无法编写解析器和比较器。

**建议**: 增加标注格式规范：

```json
{
  "pattern_id": "KN-01",
  "name": "classic_accumulation_2018_2020",
  "data_file": "fixtures/hs300_2018_2020.parquet",
  "symbol": "000300.SH",
  "expected_events": [
    {"index": 245, "event": "PS", "confidence": "high"},
    {"index": 312, "event": "BC", "confidence": "high"},
    {"index": 345, "event": "AR", "confidence": "high"},
    {"index": 420, "event": "SC", "confidence": "high"}
  ],
  "expected_phase_transitions": [
    {"index": 400, "from": "unknown", "to": "phase_a_accumulation"},
    {"index": 480, "from": "phase_a", "to": "phase_b_accumulation"},
    {"index": 620, "from": "phase_b", "to": "phase_c_accumulation"}
  ],
  "manual_annotator": "trader_wyckoff_2026",
  "annotation_date": "2026-07-24"
}
```

---

## R2-07（算法工程师 + 程序员·Blue）: 组件分层架构设计合理

**声明**: L0 P&F → L1 Event+Volume → L2 Phase → L3 MTF+RS → L4 Counterfactual

**论证**: 五层设计遵循"从数据到信号"的自然递进：
- 下层不可绕过（工程师·Phase 分析必须先跑 P&F）
- 出错时精确定位到层（测试人员·L1 挂了说明 Event 检测有问题，不是 Phase 逻辑）
- 层级依赖注入可以 mock（Python·测试时只需要测当前层，下层数据用 fixture）

**裁决**: 💙 保留

---

## R2-08（算法工程师·Red）: 反事实层 CF-01 的验证周期太短

**声明**: CF-01 "Phase 反转点后 20 个交易日方向必须一致"

**问题**: Phase 反转（Accumulation→Markup）需要的时间窗口通常是数周到数月。20 天不足以验证一个 Phase 反转。

**建议**: 将验证周期改为与 Phase 对应的期望持续时间：
- Accumulation Phase B→C: 验证 40 天
- Distribution Phase B→C: 验证 30 天
- Spring→Markup: 验证 20 天（可以较短，因为 Spring 本身是短期事件）
- Markup Phase D→E: 验证 60 天（趋势延续需更久）

---

## 裁决

| ID | 立场 | 严重 | 判决 |
|----|------|------|------|
| R2-01 | 算法 🏆 | HIGH | 事件序列需概率匹配，非严格顺序 |
| R2-02 | 算法 🏆 | HIGH | 签名需精确数值阈值 |
| R2-03 | 算法 🏆 | HIGH | 缺 FPR 质量控制 |
| R2-04 | 程序员 🏆 | MED | P&F Builder 终止条件未定义 |
| R2-05 | 程序员 🏆 | MED | 覆盖率指标需重构 |
| R2-06 | 程序员 🏆 | MED | 标注格式需规范 |
| R2-07 | 算法+程序 💙 | — | 五层架构保留 |
| R2-08 | 算法 🏆 | MED | CF 验证周期需 phase 适配 |

**Round 2 修正**: 7 Red 🏆 / 1 Blue 💙 → 需更新 ES-10(序列概率匹配), VS(数值阈值), 新增 QualityGate, P&F Builder 窗口定义, 覆盖率指标, 标注格式, CF 周期
