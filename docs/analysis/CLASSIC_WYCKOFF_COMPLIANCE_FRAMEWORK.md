# Classic Wyckoff Compliance Framework

**版本**: v1.0 | **状态**: 终稿
**目的**: 测量现有 Wyckoff 引擎 (`src/uniquant/brain/wyckoff/`) 的输出在多大程度上符合经典威科夫理论，量化偏差，由数据驱动改进决策。

## 核心原则

本框架不要求改写现有引擎。它通过**可重复的自动化审计**测量引擎行为与经典理论的偏差。偏差分三类：

| 类别 | 含义 | 行动 |
|------|------|------|
| **GAP** | 经典理论有要求但引擎完全不覆盖 | 决定是否新增 |
| **TRADE-OFF** | 引擎有等效实现但方法不同 | 记录理由，不要求改 |
| **ERROR** | 引擎行为与经典理论矛盾且可证明有害 | 必须修复 |

---

## 审计维度

### D1 — P&F 构建合规性

**对照标准**: 经典 Wyckoff 要求所有结构分析基于 P&F 图（3-box reversal method）。
**引擎现状**: `pnf.py:PointAndFigure` 已实现 `build()`/`count_target()`/`breakout_detected()`/`wyckoff_phase_hint()`。引擎仅在 `_analyze_single` 末尾附加调用 P&F，不作为 Phase 判定的输入。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| PF-C1 | P&F 是否参与 Phase 判定 | 检查 `_step1_phase_determine` 是否使用 P&F 数据 | ❌ FAIL — Phase 由 `_compute_step1_context` 的 MA/价格位置决定，P&F 为事后附加 | ERROR |
| PF-C2 | Count Target 是否影响交易计划 | 检查 `V3TradingPlan.target` 是否使用 PNF count target | ❌ FAIL — `_step5_trading_plan` 完全不用 PNF 目标 | ERROR |
| PF-C3 | P&F 支撑/阻力是否参与边界判定 | 检查 `Step1Result.boundary_upper/lower` 来源 | ❌ FAIL — 边界来自 `_step0_bc_tr_scan` 的最近 60 日高低点 | ERROR |
| PF-C4 | box_size 是否自适应价格区间和板块 | 检查 `PointAndFigure.__init__` 参数来源 | ⚠️ PARTIAL — `box_size=0.02, reversal=2` 硬编码在 `engine.py:244` | TRADE-OFF |
| PF-C5 | P&F 增量更新 O(1) | 检查 builder 是否支持单根 K 线追加 | ❌ FAIL — `build()` 每次全量重建 | GAP |

**审计命令**:
```python
from uniquant.brain.wyckoff.pnf import PointAndFigure
# 验证 box_size 与价格/板块的关系
# 验证 break_detected 与 Step1Result.boundary_upper 的关系
```

---

### D2 — 事件序列合规性

**对照标准**: 经典 Wyckoff 定义 PS→BC→AR→SC→ST→Spring→SOS→LPS→BUEC→UTAD 事件序列。
**引擎现状**: `events.py` 实现 7 个检测器（PS/SC/AR/ST/SOS/LPS/JAC），`engine.py` 有额外的 Spring/UTAD SOS/SOS 检测。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| ES-C1 | Spring 定义匹配经典理论 | Spring=O 列跌破 TR 下沿 0.5-1.5% 后立即收回 | ⚠️ PARTIAL — engine.py `_step3_phase_c_t1` 用 `boundary_lower * SPRING_LOW_FACTOR` (0.99=允许1%误差) + `close >= boundary_lower * SPRING_CLOSE_FACTOR` (0.97=收回至97%)。无 P&F X/O 列概念 | TRADE-OFF |
| ES-C2 | 事件顺序是否匹配经典序列 | 审计检测到的事件序列与理论序列的编辑距离 | ⚠️ PARTIAL — `sequence.py:WSOScorer` 用经验权重而非经典序列匹配，且隐藏 6 个 BUEC/UTAD 等事件 | TRADE-OFF |
| ES-C3 | BUEC/UTAD 是否被检测 | 检查 `engine.py` UTAD 和 BUEC 实现 | ❌ FAIL — `_detect_utad` 返回 `None`（硬编码未实现），引擎中无 BUEC 概念 | GAP |
| ES-C4 | SOS 定义是否匹配 | SOS=突破 TR 上沿 + 放量 + 随后的回测缩量 | ⚠️ PARTIAL — `_score_sos_numba` 用 >3% 涨幅和量比，无 TR 上下文绑定。events.py 注释称 threshold 从 3→4 仍 109.5% 检出率 | ERROR |
| ES-C5 | JAC（Jump Across Creek）是否匹配经典 SOS | JAC=TR 突破确认 | ⚠️ PARTIAL — `events.py:detect_jac` 用 20 日 TR 突破 + 量比，但 JAC 不是标准 Wyckoff 事件 | TRADE-OFF |

**审计命令**:
```python
from uniquant.brain.wyckoff.events import detect_all_events, WyckoffEvent
from uniquant.brain.wyckoff.engine import WyckoffEngine
# 比较 detect_all_events 输出与 engine Spring/SOS 检测是否一致
# 测量 SOS 假阳性率
```

---

### D3 — 成交量签名合规性

**对照标准**: 经典 Wyckoff 要求每个结构性事件有对应的成交量签名（BC=high_volume+wide_spread+upper_wick, SC=extreme_volume+wide_spread+lower_wick, 等）。
**引擎现状**: 成交量阈值在 `events.py` 中硬编码（`vol_ratio > 1.2`, `vol_ratio > 2.0` 等 magin number）。engine.py 通过 `V3Rules.rule1_relative_volume` 分类量能等级。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| VS-C1 | 成交量签名是否有可配置数值阈值 | 检查签名参数来源 | ❌ FAIL — `events.py` 硬编码 magic number, 引擎用枚举 | GAP |
| VS-C2 | 同一事件的量能判定在 events.py 和 engine.py 是否一致 | 比较 `_score_ps_numba` 的 vol_ratio 阈值与 `rule1_relative_volume` | ⚠️ PARTIAL — events.py 用 numba 阈值，engine.py 用 `rule1_relative_volume`，互不依赖 | TRADE-OFF |
| VS-C3 | 是否区分买盘/卖盘成交量 | 检查 volume 方向判断 | ❌ FAIL — volume 只有总量，无逐笔成交方向区分，无法区分主动买/卖 | GAP |
| VS-C4 | 量能萎缩的定义是否数值化 | SC→ST→Spring 的递减是否可测 | ⚠️ PARTIAL — `detect_st` 检查 `vol_ratio < 0.8`，`detect_lps` 检查 `vol_ratio < 0.85` | TRADE-OFF |

**审计命令**:
```python
# 扫描 events.py 和 engine.py 的所有硬编码 volume 阈值
import ast, re
# 统计所有 numeric 字面量 > 0.5 的 magic number
```

---

### D4 — Phase 分类合规性

**对照标准**: 经典 Wyckoff Phase 由事件序列推导（SC+ST×2+Spring→Accumulation 等）。
**引擎现状**: `_step1_phase_determine` 使用 7 个检测器（`_detect_markup/markdown/accumulation/distribution/spring/utad/sos`），全部基于 MA 位置和价格位置，**不依赖事件序列**。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| PH-C1 | ACCUMULATION 是否基于事件序列 | 检查 `_detect_accumulation` 逻辑 | ❌ FAIL — 基于 `is_in_trading_range + prior_trend_pct < -0.03` 或 `relative_position <= 0.40 + bc_found` | ERROR |
| PH-C2 | DISTRIBUTION 是否基于事件序列 | 检查 `_detect_distribution` 逻辑 | ❌ FAIL — 仅检查 `is_in_trading_range + prior_trend_pct > 0.05` | ERROR |
| PH-C3 | Phase 置信度是否区分 required/optional | 检查 `ConfidenceResult` | ❌ FAIL — 置信度矩阵用 5 条件组合，非 required/optional + weighted | TRADE-OFF |
| PH-C4 | 月/周/日三周期 phase 是否一致 | 检查 `MultiTimeframeResonance` | ✅ PASS — `phase_analysis.py` 实现共振检测（bullish/bearish/conflicting 三态 + 连续强度分） | ✅ |
| PH-C5 | Sub-phase A/B/C/D/E 细分是否匹配经典 | 检查 `_classify_accumulation_sub_phase` | ⚠️ PARTIAL — `classifiers.py:classify_accumulation_sub_phase` 存在但基于价格和量能趋势，非事件序列 | TRADE-OFF |

**审计命令**:
```python
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.events import detect_all_events
# 对比 engine.analyze().structure.phase 与 event_sequence_phase(events)
# 计算不一致率
```

---

### D5 — 多周期合规性

**对照标准**: 月线主导方向，周线提供确认，日线提供执行时机。
**引擎现状**: `engine.py:analyze` 支持 `multi_timeframe=True` 调用 `_analyze_multiframe`。`phase_analysis.py` 有完整三周期分类器。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| MT-C1 | 月线是否主导日线 | 审计 `_analyze_multiframe` 的 phase 合并逻辑 | ⚠️ PARTIAL — `MultiTimeframeResonance.resonance` 用 2/3 投票，非月线绝对主导 | TRADE-OFF |
| MT-C2 | 三周期对齐是否附带量化证据 | 检查 MTF 输出中是否有预测力提升指标 | ❌ FAIL — `resonance_strength` 只有加权计数，无 R²/IC/夏普比 | GAP |
| MT-C3 | 周线矛盾时是否覆盖日线 | 检查 weekly_aligned 对 ConfidenceResult 的影响 | ⚠️ PARTIAL — `_calc_confidence` 接收 `multiframe` 参数但仅在 debug 路径中使用 | TRADE-OFF |

**审计命令**:
```python
from uniquant.brain.wyckoff.phase_analysis import MultiTimeframeResonance
# 黄金样本上验证 resonance() 的分类
```

---

### D6 — 相对强弱合规性

**对照标准**: RS 分类（强势独立/跟风/弱势独立/系统性）。
**引擎现状**: `engine.py` 中无 RS 计算。`analysis.py` 有 `analyze_chips` 含资金流向分析。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| RS-C1 | RS 分类是否实现 | 搜索 RS/relative strength 引用 | ❌ FAIL — 引擎无 RS 计算 | GAP |
| RS-C2 | 资金流向是否纳入信号 | 检查 chip_analysis 对 trade 决策的影响 | ❌ FAIL — `ChipAnalysis` 字段已定义但不在置信度矩阵中 | GAP |

**审计命令**:
```python
# grep 引擎中 "relative" 或 "strength" 或 "rs" 的引用
```

---

### D7 — 反事实验证合规性

**对照标准**: Phase 反转后验证周期与 Phase 对应（Accum=40d, Distrib=30d, Spring=20d, Markup=60d）。
**引擎现状**: `_step35_counterfactual` 用 forward/backward evidence 评分，规则 7 仲裁，非基于未来价格验证。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| CF-C1 | Phase 反转后验证周期是否 phase 自适应 | 检查 `V3CounterfactualResult` 无时间参数 | ❌ FAIL — 反事实无任何 time-window 概念 | GAP |
| CF-C2 | Stop Violation 标记机制 | 检查止损位是否被事后验证 | ⚠️ PARTIAL — `StopLossResult` 已定义但不参与反事实 | TRADE-OFF |
| CF-C3 | Count Target 达到率验证 | 检查 `pnf_count_target` 是否被事后验证 | ❌ FAIL — `pnf_count_target` 存在但不参与任何事后验证 | GAP |
| CF-C4 | 假突破惩罚机制 | 检查假突破是否导致信号降权 | ⚠️ PARTIAL — UTAD 标记存在但`_detect_utad` 返回 None，永不触发 | ERROR |

**审计命令**:
```python
# 审计 walk-forward 回测中 engine 生成的信号的实际后续回报
# 计算信号准确率、止损命中率、目标位到达率
```

---

### D8 — A 股适配合规性

**对照标准**: 分板 box_size、T+1 冷却、涨跌停截断、集合竞价处理、前复权。
**引擎现状**: `engine.py:244` 有 `_apply_a_stock_rules` 但仅做 Markdown 禁止做多检查。`_step3_phase_c_t1` 含 T+1 压力测试。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| CN-C1 | 分板 box_size | 检查 P&F builder 的 box_size 是否依赖 board | ❌ FAIL — 硬编码 0.02，无板块区分 | GAP |
| CN-C2 | T+1 冷却 | Spring 后是否强制 1 天等待 | ⚠️ PARTIAL — `_step3_phase_c_t1` 计算 T+1 风险但不强制冷却 | TRADE-OFF |
| CN-C3 | 涨跌停截断 | 涨停日是否影响 P&F 列 | ❌ FAIL — P&F builder 不检查涨跌停 | GAP |
| CN-C4 | 数据前复权要求 | 是否有数据预处理检查 | ❌ FAIL — 无数据复权检查逻辑 | GAP |

**审计命令**:
```python
from uniquant.shared.board_registry import BoardType, BoardTypeRegistry
# 检查 engine 是否感知 board type
```

---

### D9 — 信号输出合规性

**对照标准**: 信号附带结构完整性评分、检测路径、Phase 置信度、成交量确认、一致性、RS、反事实状态、A 股适配信息。
**引擎现状**: `WyckoffOutput`/`WyckoffReport`/`ConfidenceResult` 含大量字段但无统一完整性评分。

| # | 检查项 | 测量方法 | 当前评分 | 分类 |
|---|--------|---------|---------|------|
| SQ-C1 | 是否存在结构完整性评分 (0-100) | 搜索 `structural_score` | ❌ FAIL — 不存在 | GAP |
| SQ-C2 | 信号是否附带置信度 phase 来源 | 检查 `WyckoffSignal.phase` 使用情况 | ⚠️ PARTIAL — `WyckoffSignal` 有 phase 字段但 `WyckoffAdapter` 只读 wyckoff_phase | TRADE-OFF |
| SQ-C3 | 是否区分 "不判定" 和 "数据不足" | 检查 UNKNOWN 的细分原因 | ✅ PASS — `unknown_candidate` 有 4 种子状态 | ✅ |

**审计命令**:
```python
from uniquant.signal.adapters import WyckoffAdapter
from uniquant.brain.wyckoff.models import WyckoffReport
# 检查 WyckoffReport → WyckoffSignal 的字段映射完整性
```

---

## 综合评分

| 维度 | 评分 | ERROR | GAP | TRADE-OFF | 优先 |
|------|------|-------|-----|-----------|------|
| D1 P&F | ❌ 0/5 | 3 | 1 | 1 | P0 |
| D2 事件序列 | ⚠️ 1/5 | 2 | 1 | 2 | P0 |
| D3 成交量签名 | ⚠️ 1/4 | 1 | 2 | 1 | P1 |
| D4 Phase 分类 | ⚠️ 2/5 | 3 | 0 | 2 | P0 |
| D5 多周期 | ⚠️ 1/3 | 1 | 1 | 1 | P1 |
| D6 相对强弱 | ❌ 0/2 | 0 | 2 | 0 | P2 |
| D7 反事实 | ❌ 0/4 | 2 | 2 | 0 | P1 |
| D8 A 股适配 | ❌ 0/4 | 0 | 4 | 0 | P1 |
| D9 信号输出 | ⚠️ 1/3 | 0 | 2 | 1 | P2 |
| **合计** | **6/35 (17%)** | **12** | **15** | **8** | |

**优先级定义**:
- P0: 经典 Wyckoff 核心理论要求，违反导致信号逻辑根本性偏差
- P1: 重要但不阻止最小可用版本
- P2: 增强功能，非核心

---

## 使用方法

### 首次基准审计

```bash
python scripts/classic_wyckoff_compliance.py --output docs/compliance/baseline_report.json
```

### 代码修改后重新审计

```bash
python scripts/classic_wyckoff_compliance.py --compare docs/compliance/baseline_report.json
```

### 单维度审计

```bash
python scripts/classic_wyckoff_compliance.py --dimension D1,D2
```

---

## 文件

| 文件 | 用途 |
|------|------|
| `scripts/classic_wyckoff_compliance.py` | 自动化审计执行器 |
| `docs/compliance/baseline_report.json` | 首次基准结果 |
| `docs/analysis/CLASSIC_WYCKOFF_COMPLIANCE_FRAMEWORK.md` | 本文件 |
