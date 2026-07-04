# Phase 5 — 信号系统审计

> 日期: 2026-06-30 | 方法: 代码审查 + 仲裁逻辑验证 + 适配器映射分析

---

## 报告摘要

信号系统（8 文件, 3 核心模块）是架构最优雅的层之一。适配器模式 + 仲裁器模式 +
不可变设计原则贯彻良好。7 个 EngineAdapter 和 SignalArbitrator 的双仲裁路径可靠。

**信任评级: A** (架构简洁, 逻辑清晰, 测试覆盖良好)

---

## 组件审计

### 适配器层 (Adapters)

7 个注册适配器, 全部实现 `EngineAdapter.adapt()`:

| 适配器 | 输入键 | 输出条件 | 置信度逻辑 |
|---|---|---|---|
| LPPLAdapter | `risk_level`, `confidence` | Danger→SELL, Warning→HOLD, Safe→HOLD | 来自 `bubble_confidence`, 最低 0.05 阈值 |
| CZSCAdapter | `is_3rd_buy`, `bi_count` | True→BUY, False→HOLD | `min(0.5 + bi_count*0.05, 0.9)` |
| WyckoffAdapter | `wyckoff_phase`, `spring`, `utad` | accumulation/spring→BUY, distribution/utad→SELL | `wyckoff_confidence`, 最低 0.3 阈值 |
| FSMAdapter | `action`/`final_decision` | 10 种 action 映射到 BUY/SELL/HOLD | `confidence` (默认 0.5) |
| RegimeAdapter | `regime` | FROZEN→HOLD, STRESSED→HOLD, NORMAL→None | 固定 0.5 |
| NTFAdapter | `ntf_side`, `ntf_intensity` | RESISTANCE + intensity≥0.6→SELL, SUPPORT→HOLD | `min(intensity, 0.9)` |
| AlphaScoreAdapter | `alpha_score` | >0.6→BUY, <0.3→SELL | `abs(score-0.5)*2` |
| MAStatusAdapter | `ma_status` | ">"→BUY, "<="→SELL | 固定 0.3 |

**设计一致性**: 所有适配器遵循以下规则:
- 无策略判断, 纯形态转换
- 无效输入返回 `None` (不产生信号)
- `confidence` 由适配器独立计算
- 元数据通过 `metadata` dict 透传

### TradingSignalCollector

`collect()` 方法从 `data_pack` Dict 中提取 8 个引擎输出, 通过 AdapterRegistry 逐一适配。
收集前 `_extract_*` 方法做键存在性检查, 避免 KeyError。

**信号发布**: 收集到的信号通过 `EventBus.publish(SignalGenerated(...))` 发布。
EventBus 可选, 无依赖时跳过。

### 仲裁器 (SignalArbitrator)

**双仲裁路径**:

| 路径 | 方法 | 用途 |
|---|---|---|
| 简化路径 | `arbitrate(signals, symbol)` | 通用仲裁, 每日至多 1 信号 |
| 完整路径 | `arbitrate_candidates(candidates, decision_output, context, sizer)` | 带 FSM vetos + 仓位计算 |

**仲裁规则链 (简化路径)**:
1. 过滤 HOLD/未知动作 → 只考虑 BUY/SELL
2. 质量阈值过滤: SELL 信号的 `out_of_sample_r_squared` < 0.3 拒绝
3. SELL 优先: 所有 SELL 高于 BUY
4. 同方向取最高 `confidence`
5. 引擎优先级: LPPL > FSM > CZSC > Wyckoff > Regime > NTF > Alpha > MA

**仲裁规则链 (完整路径)**:
1. DecisionOutput 硬约束: FORCE_WAIT/CIRCUIT_BREAK → HOLD, FORCE_EXIT → SELL
2. DecisionOutput BUY + shares → 直接输出
3. SELL 优先 (同简化路径)
4. FSM BUY 直通
5. 非 FSM BUY → PositionSizer 确认
6. HOLD 默认

**引擎优先级表**:
```
lppl:     0 (最高)
fsm:      1
czsc:     2
wyckoff:  3
regime:   4
ntf:      5
alpha:    6
ma:       7 (最低)
```

---

## 发现

### 1. `TradingSignalCollector.collect()` 硬编码 8 个引擎提取
`collect()` 方法逐一手动调用 `_extract_lppl`, `_extract_czsc` 等静态方法。
不是通过注册表自动发现引擎。这意味着注册新适配器后必须手动更新 `collect()` 方法。
这是设计缺口, 但不是 Bug。

### 2. LPPLAdapter 不生成 BUY 信号
LPPLAdapter 的 action 逻辑 (第 86-91 行):
```python
if risk == "Danger": action = "SELL"
elif risk == "Warning": action = "HOLD"
else: action = "HOLD"
```
Safe 状态返回 HOLD, 永不产生 BUY。这是设计决策 (LPPL 是泡沫检测器, 只在泡沫破裂时卖出)。

### 3. 信号流精度控制
每个适配器有独立的精度阈值:
- LPPL: confidence < 0.05 → None (最低)
- Wyckoff: confidence < 0.3 → None
- NTF: intensity < 0.6 → None (仅 RESISTANCE)
- AlphaScore: 0.3–0.6 区间 → None

这些阈值没有统一的配置入口, 硬编码在各适配器中。

### 4. ArbitrationLog 仅记录, 不消费
`arbitrate()` 每次调用追加 `ArbitrationLog` 到 `self._logs`。
`clear_logs()` 可清除, 但 logs 没有持久化或报告生成机制。
仅通过 `ArbitrationReport` (完整路径) 返回给调用方。

---

## 信任评级: A

| 维度 | 评分 | 理由 |
|---|---|---|
| 适配器完整性 | A | 8 引擎全覆盖, 形态转换干净 |
| 仲裁逻辑 | A | 清晰规则链, 双路径, 完整路径有 vetos+sizer |
| 不可变性 | A | 不修改原始信号, 返回新列表 |
| 事件集成 | A | EventBus 可选集成 |
| 信号精度控制 | B+ | 阈值硬编码, 无统一配置 |
