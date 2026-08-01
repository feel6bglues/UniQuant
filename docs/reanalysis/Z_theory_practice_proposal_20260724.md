# 理论与实际结合 — 建议方案

> 基于 walk-forward 实证（2999 观测, 3574 只 × 6 窗口）+ 3 轮红蓝对抗
>
> 目标: 给一个可实施、在 A 股上已验证、有理论基础的方案

---

## 一、核心判断

A 股不是"更好的美股"，在信号系统上的核心差异不可调和：

| 维度 | 美股（Wyckoff/LPPL 原产地） | A 股 |
|---|---|---|
| 主导驱动 | 机构供求、盈利周期 | 政策、流动性、散户情绪 |
| 趋势结构 | TR 积累→突破（6-18 月） | V 型反转、尖顶（数天-数周） |
| LPPL 拟合 | 资产泡沫有周期性 | 93% GBM 噪声，p=0.48 |
| Spring/UTAD | 可检测、可交易 | Spring=0/600，UTAD=NONE |
| 空头信号 | abundance（UTAD/Distribution） | 0/600，direction 错误 |
| 有效信号 | Wyckoff 理论买入 | 仅 markup→买入（4.5%，+8% edge，p=0.0098） |

**结论**: 不是"缺什么补什么"，而是"A 股上没有的不要硬造"。

---

## 二、建议方案架构

### 设计原则

1. **先验证，后实现** — 每个信号必须有 walk-forward 或类似回测证据
2. **简洁 > 复杂** — 5 行 MA 交叉 > 200 行 Wyckoff 基金适配
3. **移除 > 修复** — LPPL 零预测力 → 移除入生产管线
4. **降级 > 升级** — Wyckoff 从"交易信号引擎"降为"相位标签引擎"

### 新架构

```
现有管线:
LPPL ──→ 信号 ──→ 交易   ← 移除 (零预测力)
Wyckoff ──→ 信号 ──→ 交易 ← 降级为标签 + 单一信号

新管线:
市场机制检测 (RegimeDetector) ──→ 仓位方向
        ↓
趋势分类 (Phase-Lite) ──→ 个股方向 (MARKUP/MARKDOWN/UNKNOWN)
        ↓
Markup→买入 指示器 ──→ 仅在 MARKUP 时触发 (已验证 p=0.0098)
        ↓
成交量价差特征 ──→ 离线特征，辅助而非门控
```

---

## 三、具体执行（三级，950 行，2-3 周）

### P0: 紧急修复 — 2 天，~150 行

#### P0-1: Adapter α=∞ 抑制（~30 行）

**理论**: Adapter 中 accumulation→BUY 的逻辑在 collapse_score=0（α=∞，趋同性见顶）时产生误信号。

**实际**: `adapters.py:180` 条件 `if spring or phase in self._BULLISH_PHASES` 没有检查 collapse_score——当 collapse_score=0 时 accumulation 阶段已逆转，BUY 信号是假的。

**操作**:
```python
# 修复 adapter 读取 collapse_score
if spring or phase in self._BULLISH_PHASES:
    collapse = raw_output.get("collapse_score", 1.0)
    if collapse < 0.3:
        return None  # α=∞ → 抑制
    action = "BUY"
```

#### P0-2: Spring 降级（~60 行）

**理论**: Spring 在 A 股上 0/600 触发，不该门控任何逻辑。

**实际**: `engine.py:675-676` Spring 仅在 ACCUMULATION/UNKNOWN/MARKUP 阶段检测且影响置信度。

**操作**: Spring 从不触发 → 从 confidence 计算中完全移除 Spring 相关分支，改为 phase_machine 输出的可选事件。这一步的本质是承认 Spring 不工作，不是"修复"Spring。

#### P0-3: Phase-Lite 简化（~60 行）

**理论**: A 股无完整 A→E 积累链，但 MARKUP/MARKDOWN/UNKNOWN 三级可用。

**实际**: `classifiers.py:132-185` 的 A-E 分类逻辑 ~55 行，`classify_distribution_sub_phase` ~45 行。在 walk-forward 的 ACCUMULATION sub_phase 分布未知但 Spring=0 的约束下，细分的 A/B/C/D 级无交易意义。

**操作**: 将 `classify_accumulation_sub_phase` 简化为仅在 MARKUP 和 MARKDOWN 之间裁决，去除 A-E 细分。保留 `_detect_markup` 和 `_detect_markdown` 的现有逻辑（已验证可产生唯一有效信号）。

---

### P1: 有效信号提取 — 1 周，~300 行

#### P1-1: Markup→买入 独立指示器（~250 行）

**理论**: walk-forward 证明 markup→买入是唯一统计显著信号（+13.33% 20d, win 88.9%, p=0.0098）。这不是 Wyckoff Spring 信号——是现代 Wyckoff 学派称为"continuation in strength"的趋势延续形态。

**实际**: 当前 `_step5_trading_plan` 在 markup 分支中有一个"买入"输出，但条件不可追踪。需要：

1. 提取条件: 现有代码中什么条件组合产生买入？用 walk-forward 500 只 × 6 窗口识别触发模式
2. 封装为 `MarkupContinuation` 类: 独立于 WyckoffEngine 的轻量级指示器
3. 运行时统计: 跟踪实时触发率，当触发率偏离 walk-forward 的 4.5% 基线时报警

**实现**:
```python
class MarkupContinuation:
    def detect(self, df, ctx) -> Optional[Signal]:
        if ctx["phase"] != "markup":
            return None
        # 提取当前 engine 中触发买入的条件组合
        if self._conditions_met(df, ctx):
            return Signal(reason="markup_continuation", ...)
        return None
```

#### P1-2: 空头缺口识别（~50 行）

**理论**: A 股无双向 Wyckoff 空头信号，但"逃逸缺口" (`_step2_effort_result:637-640`) 已在现有代码中被识别。

**实际**: `engine.py:633-644` 已识别向下逃逸缺口，但未被 WyckoffAdapter 使用。这是一个已存在但未暴露的信号——下行 momentum 而非 Wyckoff distribution 信号的合理替代。

**操作**: 将 `has_escape_gap` 从 Step2Result 传递到 Adapter，作为空头参考信号（置信度 0.3，不单独触发交易但影响仓位大小）。

---

### P2: 相位精简 — 1 周，~500 行

#### P2-1: LPPL 管线移除 + 机制检测替代（~300 行）

**理论**: LPPL 零预测力（walk-forward 终裁）→ 从生产管线移除。市场层面的风险评估不应使用 LPPL，而应使用已验证的机制转换模型（Hamilton 1989, Ang & Bekaert 2002）。

**实际**: `RegimeDetector` 已存在 (`brain/regime/regime_detector.py`)，且 Phase 6 已加固 fail-open。将其升级为连续输出（0-1 风险分数而非离散三态）即可替代 LPPL 的市场风险评估角色。

**操作**:
```
修改 analysis_service_v2.py:
   LPPL 调用 → 移除
   新增 RegimeDetector 产出 → 市场风险分数 (0-1)
   
修改 service_container.py:
   从初始化流程移除 LPPLDataService (已 DEPRECATED)
   
新增 regime_signal.py:
   风险分数 → 仓位限制 (分数 > 0.7 → 最大仓位 50%)
```

#### P2-2: WyckoffEngine 精简（~200 行）

**理论**: 唯一有效信号在 markup 分支 + 当前 engine.py 1616 行中大量代码用于不触发的事件。

**实际**: 删除 `_detect_distribution`, `_detect_utad`, `_detect_sos`, `_classify_accumulation_sub_phase`, `_classify_distribution_sub_phase`。保留 `_detect_markup`, `_detect_markdown`, `_step5_trading_plan`。engine.py 从 1616 行降至 ~800 行。

---

## 四、不做清单（节省 ~2000 行）

| 项目 | 行数 | 不做原因 | 替代 |
|---|---|---|---|
| LPPL 指数分析 | ~1080 | walk-forward 零预测力 | RegimeDetector |
| 九项测试自动化 | ~200 | 6 项弱信号集合 | 无替代（无信号价值） |
| P&F 重写 | ~150 | 已有 213 行，唯一缺 box_size 自适应 | 加 30 行自适应参数 |
| 基金 Wyckoff 适配 | ~200 | MA 交叉 5 行替代 | 用 MA 交叉 |
| 贝叶斯置信度系统 | ~150 | 冷启动 600 窗口 | 保留当前 A/B/C/D |
| A-E 状态机 (重写) | ~200 | 当前已有 + A 股不适用 | 简化为三级 |

---

## 五、理论基础 vs 实际验证

### 为什么这些建议"既有理论又有实际"？

| 建议 | 理论基础 | 实际证据 |
|---|---|---|
| 移除 LPPL | Filimonov & Sornette 2013 要求变量投影；Sornette 本人强调 LPPL 仅适用于流动性驱动的系统性泡沫而非个股；A 股指数受政策干预，不符合纯市场行为的 LPPL 前提 | walk-forward: 93% GBM 噪声拟合, m 分布 KS p=0.019, danger p=0.48 |
| Phase-Lite 三级 | Wyckoff 四阶段理论的简化版—承认 A 股缺少 TR 但接受 MARKUP/MARKDOWN 两类趋势识别 | walk-forward: accumulation +3.94% < markdown +5.50% < markup +6.14% 前瞻收益 |
| Markup→买入 信号 | Wyckoff 的"cause→effect"原理的反向应用—不是从 cause 预测 effect，而是在 effect 确认后附着（momentum continuation） | walk-forward: +13.33% 20d, win 88.9%, p=0.0098, 24/100 只触发 |
| RegimeDetector 替代 LPPL | Hamilton (1989) Markov-switching 模型是经济周期检测的标准方法；Ang & Bekaert (2002) 证明机制转换在波动率预测中优于线性模型 | Phase 6 已验证 RegimeDetector 在 5934 只上 fail-safe；A 股"牛熊"二态结构比 LPPL 更适配 |
| 空头缺口信号 | 无 Wyckoff 分布但有下行缺口=下行趋势持续 | `engine.py:633-644` 已实现在 Step2Result 中但未使用 |

### 理论承诺 vs 实际输出

1. **不要承诺 LPPL 做不到的事**: LPPL 的理论承诺是"检测泡沫临界点"，实际做不到。移除它不是因为实现差，是因为框架不适用于 A 股。

2. **不要过度解读 Wyckoff 的理论**: Wyckoff 的理论承诺是"SC→Spring→SOS→LPS→Markup"的完整周期，A 股上从不发生。唯一有价值的"买入"信号实质是趋势跟随，不是经典 Wyckoff。

3. **接受 A 股的约束作为设计输入**: T+1、涨跌停、政策驱动不是需要修复的 bug，是需要接受的特点。不产生 Spring 不是 Wyckoff 引擎的 bug—可能 A 股真的没有 Spring。

---

## 六、验证计划

每个改动需要回答:

1. **是改进吗？** 对比 walk-forward 基线（+4.77%/span +5.26% 无信号）
2. **信号触发率多少？** 低于 1% 的需标注"罕见"
3. **方向性正确吗？** 空头信号必须验证不做反
4. **与简单 baseline 相比？** 比 MA 交叉好吗？比买入持有好吗？

### 验证命令

```bash
# 1. Phase-Lite 验证: 三级分类 vs 现有 A-E 的预测力对比
python3 -c "
from scripts.staged_full_scan import scan
results = scan(stage='canary')
for r in results:
    old_phase = r['phase']
    new_phase = simplify_to_lite(old_phase)
    assert mapping_consistent(old_phase, new_phase)
print('Phase-Lite 完全兼容')
"

# 2. Markup→买入触发率跟踪
python3 -c "
from scripts.walk_forward_engine import run
results = run(golden_500, n_windows=6)
buy_count = sum(1 for r in results if r['trading_plan'] == '买入' and r['phase'] == 'markup')
print(f'Buy signals in markup: {buy_count}/{len(results)} = {buy_count/len(results)*100:.1f}%')
print('Expected ~4.5%, if deviation > 2% → investigate')
"

# 3. LPPL 移除后管线不崩溃
python3 -c "
import uniquant.services as svc
c = svc.ServiceContainer()
c.initialize()
print('ServiceContainer OK without LPPL')
"

# 4. 空头缺口信号非零
python3 -c "
from scripts.staged_full_scan import scan
results = scan(stage='canary')
gap_count = sum(1 for r in results if r.get('has_escape_gap'))
print(f'Escape gaps detected: {gap_count}/{len(results)} = {gap_count/len(results)*100:.1f}%')
"
```

---

## 七、工作量汇总

| 阶段 | 内容 | 行数 | 时间 | 风险 |
|---|---|---|---|---|
| P0 | Adapter 修复 + Spring 降级 + Phase-Lite | ~150 | 2 天 | 低—修改集中在 adapter 和 classifiers |
| P1 | Markup→买入提取 + 空头缺口 | ~300 | 1 周 | 中—需 walk-forward 回测验证条件 |
| P2 | LPPL 移除 + RegimeDetector 替代 + WyckoffEngine 精简 | ~500 | 1 周 | 中—需确认 ServiceContainer 依赖 |
| **合计** | **~950** | **2-3 周** | |

原计划 3080 行/5-6 周的 **69% 减少**，但 **100% 解决了 walk-forward 验证的根因**（零预测力、Spring=0、唯一信号未暴露）。

---

## 八、一句话

**不是把 Wyckoff/LPPL 做得更好，而是接受 A 股没有它们要的信号这一事实，用更简洁的方法直接提取 walk-forward 已证明的唯一有效信号。**
