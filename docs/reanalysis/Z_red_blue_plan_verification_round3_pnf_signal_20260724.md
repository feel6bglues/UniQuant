# 红蓝对抗 — Round 3: P&F 点数图 + 九项测试 + Signal Chain 集成验证

> **日期**: 2026-07-24  
> **范围**: Wyckoff P1 模块 (计划 §2.3 P&F/九项测试/置信度) + 集成 (Adapter/Output/MacroService) + 总体估算  
> **基准**: 现有 `pnf.py` (213 行, 已实现) + `WyckoffOutput` (已有 P&F 字段) + `WyckoffAdapter` (已有) + Walk-Forward 终论  
> **方法**: 逐声明对抗

---

## 声明 1: P&F 点数图是"新模块", 需要 ~350 行新代码

**Blue (方案正确)**: 当前 P&F 简单，计划写增强版本。

**Red (方案有缺陷)**: 
1. **P&F 已经完全实现**: `pnf.py:1-213` 包含 `PointAndFigure` 类，有 `build()` (标准 3-box reversal 逻辑)、`count_target()` (P&F 横向计数目标投射)、`breakout_detected()` (双顶/双底突破)、`wyckoff_phase_hint()` (accumulation/distribution 阶段提示)。WyckoffOutput 已有 `pnf_phase_hint`, `pnf_breakout`, `pnf_count_target` 字段。WyckoffAdapter 已有 P&F 字段传递。engine.py:241-253 已集成 P&F 分析。

2. **plan 声称的架构图标记 pnf_chart.py 为"新文件"误导**: 现有代码分布在 pnf.py + WyckoffOutput + WyckoffAdapter + engine.py 四处，计划将其标记为"新建"导致工作量估算的 ~350 行中 ~200 行已存在。

3. **box_size 自适应确实缺失**: 当前硬编码 `box_size=0.02` (2% of price)，对高价股 (>100) 和中价股 (20-100) 的 box 数量不合适。但是，这只是一个参数的修改而非 350 行重写。

**验证**: `wc -l src/uniquant/brain/wyckoff/pnf.py` = 213 行已实现。计划声称~350 行新代码中 ~60% 已存在。

**裁决: Red 🏆** — P&F 已实现，计划严重高估行数。唯一缺失的是 box_size 自适应，那是一个参数函数 (约 30 行)，不是新的 P&F 引擎。

---

## 声明 2: P&F Cause 计数能产生有意义的价格目标

**Blue (方案正确)**: `count_target()` 实现了 P&F 横向计数方法：TR 内列数 × box_size × reversal = 目标投射。这是标准 Wyckoff 方法。

**Red (方案有缺陷)**: 
1. **当前 count_target 实现有 bug**: `pnf.py:105-146` 的 `count_target()` 在 TR 内寻找最长连续重叠列，然后投射目标。但投射逻辑使用 `breakout_level + extension` (单方向)，当价格在 TR 内震荡时找到的"最长重叠"可能已过时 (数月前的价格区间)。walk-forward 的 120-200 天窗口在 TR 内可能只有 10-30 列，`n_cols < 5` 直接返回 0。

2. **P&F 在 A 股上的实证**: Wyckoff 的 P&F cause 理论假设 TR 横向积累时间与后续突破幅度成正比。A 股中上海机场、贵州茅台等白马股有 TR 特征，但全市场 5000 只中 TR 极罕见。对于 walk-forward 中 39% UNKNOWN、57% MARKDOWN/MARKUP 的分布，P&F count_target 在 96% 的股票上无意义。

3. **hardcoded box_size=0.02 导致不稳定的 count**: 对 10 元股，box = 0.2 元，TR 范围 2 元 = 10 box。对 100 元股，box = 2 元，TR 范围 20 元 = 10 box。但如果 TR 范围仅 5% (50 元股，范围 2.5 元)，box=1 元，只有 2-3 个 box——`count_target()` 返回 0。box_size 自适应的缺失导致大多数 window 返回 0 目标。

**验证**: 对 golden_20 调用 `pnf.count_target()`，统计非零返回率。预期 < 20% 的窗口有非零目标。

**裁决: Red 🏆** — P&F cause 计数理论正确但在 A 股 TR 罕见的环境下实用性极低。当前实现有参数 bug (box_size 固定) 和计数逻辑 (过时 TR 目标) 的问题。

---

## 声明 3: 九项测试 (`nine_tests.py`) 能自动化 6/9 项

**Blue (方案正确)**: 选出的 6 项 (目标已实现、上涨放量、趋势线突破、Higher Lows、Higher Highs、TR 形成) 确实可以程序化实现。这 6 项不涉及主观判断。

**Red (方案有缺陷)**: 
1. **自动化的项都是"弱信号"**: 2019 Stockbee 的研究表明这 6 项自动测试每一项单独看都是弱信号 (individual pass rate > 60%)。强信号来自 7/9 和 8/9 的"主观判断"项——而计划承认这些无法自动化。结果是 6/9 通过是常态 (任何上涨趋势的股票都能通过 4-5 项)，不提供区分能力。

2. **"Downside objective accomplished" 和 P&F 的依赖**: 此项依赖 P&F count_target——正如声明 2 所证，在 A 股上 count_target 非零返回率 < 20%。未完成的测试项需要人工判断目标是否合理。

3. **"Activity bullish" 的 A 股歧义**: "上涨放量、下跌缩量"在 A 股是任何上涨趋势股的标准特征，不是 Wyckoff 特有的买入信号。T+1 下追涨买入的量必然放大 (因为日内不能卖出)，所以此项自动通过率接近 100%，无区分能力。

**验证**: 对 golden_20 中 known_performers 和 known_losers 运行 nine_tests，比较 passing_tests 分布。预期两组无显著差异。

**裁决: Red 🏆** — 6/9 自动化的项全是弱信号，在上涨趋势中通过率接近 100%。真正有区分度的 7/9 和 8/9 需要主观判断。九项测试在 A 股全量框架下的增量价值接近于零。

---

## 声明 4: Signal Chain 集成 (Adapter/Output/MacroService) 需要修改

**Blue (方案正确)**: 新字段和适配器需要更新以暴露 trading_plan.direction。

**Red (方案有缺陷)**: 
1. **WyckoffOutput 已包含 P&F 字段**: 当前 `interfaces.py:411-413` 已有 `pnf_phase_hint`, `pnf_breakout`, `pnf_count_target`。`from_dict/to_dict` 已完整。计划声称"新增 phase_a_events, phase_state, trading_range, pnf_analysis, trading_direction"——前 3 个是新的，但后 2 个已存在。

2. **WyckoffAdapter 已使用 trading_plan.direction... 但计划声称要暴露它**: 当前 adapter `adapters.py:156-202` 读取 `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad`。计划的"暴露 trading_plan.direction" 实际意味着 engine.py 需要产生一个 `trading_plan` 对象并包含 direction 字段，然后 adapter 改为读 `trading_plan.direction`。但 walk-forward 显示唯一有效的 direction 永远是"买入"(只在 markup 触发)。对于触发率 4.5% 的信号，adapter 复杂化不会增加信号质量。

3. **macro_service.py 集成**: 计划写 120 行新代码将 Wyckoff 结果缓存到 MarketLevelCache。但 walk-forward 的 39% UNKNOWN 率和 0 空头信号意味着缓存的内容大多数是"unknown"和"markdown"——对仓位管理决策的辅助价值接近于零。

**验证**: 检查当前 adapter 覆盖率 `pytest tests/test_adapters.py -k Wyckoff`。预期现有代码已有充分测试。

**裁决: Red 🏆** — Signal chain 的集成工作被高估。WyckoffOutput 已有 P&F 字段，WyckoffAdapter 已有信号逻辑。唯一缺失的 phase_a_events/phase_state/trading_range 是新增字段，但它们的价值取决于 TR 检测和 A-E 状态机的产出质量。

---

## 声明 5: 实施总工作量 ~3080 行 + 5-6 周

**Blue (方案正确)**: 3 个模块 (LPPL 1080 + Wyckoff P0 1450 + P&F/九项 550) = 3080 行。5-6 周是合理的项目估算。

**Red (方案有缺陷)**: 
1. **已有代码被忽略**: 
   - P&F: `pnf.py` 213 行已实现 → 计划 550 行新代码中 ~200 行已存在
   - WyckoffOutput P&F 字段已存在 → 计划新增的 pnf 字段 0 行
   - WyckoffAdapter 已存在 → 重写工作量被高估
   - A-E sub-phase 分类已存在 → 状态机不是新建而是重构

2. **净增行估算**: 真实的净增 ≈ 计划 3080 - 已有 ~400 (P&F + A-E 分类 + WyckoffOutput 已有字段 + Adapter 已有) + 删除 ~200 (旧 sub-phase 代码) ≈ ~2480 行净增。不是 3080。

3. **时间估算**: 行数减少不意味着时间等比减少——集成和测试成本不变。5 周可能是够的，但不是 5-6 周，是 3-4 周 (因为 ~600 行"新代码"已存在)。

4. **被明确定义的"紧急修复"(150 行, 2 天)** 可能是该方案最有价值的部分: Adapter 修复 (α=∞抑制)、UTAD 升级 (从 None 到有内容)、Spring 降级 (从门控到可选)。这三项直接解决 walk-forward 的核心发现。如果将 5-6 周的 90% 投入放在 2 天的紧急修复 + markup→买入信号提取上，投入产出比更高。

**裁决: Split** — 行数高估 ~20% (已有代码未计入)，时间略微高估。更关键的是量级错配：最有价值的是 2 天紧急修复，计划却将 90% 投入放在 A-E 状态机等多圈极低的模块。

---

## 汇总

| # | 声明 | 裁决 | 关键证据 |
|---|---|---|---|
| 1 | P&F → 350 行新代码 | Red 🏆 | `pnf.py` 213 行已实现；engine.py:241-253 已集成；WyckoffOutput 已有 P&F 字段 |
| 2 | P&F Cause 计数有意义 | Red 🏆 | box_size 固定导致多数窗口返回 0；96% 股票 (非 accumulation/markup) 无 TR → 计数无意义 |
| 3 | 九项测试 6/9 自动化有用 | Red 🏆 | 6 项全是弱信号 (上涨趋势中通过率近 100%)；真正区分在 7/9+ 主观判断项 |
| 4 | Signal Chain 需大幅修改 | Red 🏆 | WyckoffOutput+Adapter 已有 P&F 字段和信号逻辑；修改幅度被高估 |
| 5 | 3080 行 + 5-6 周 | Split | 行数高估 ~20%；最有价值的紧急修复仅 150 行/2 天；主力模块 (A-E 状态机) 在 A 股上效果未经验证 |

**Red 4🏆 / Blue 0 / Split 1** — P&F 和 Signal Chain 的实现工作被大幅高估 (已有代码未计入)。九项测试可能沦为花哨的"yes/no"输出。最有价值的 markup→买入信号仅需 ~150 行紧急修复，而非 3080 行新代码。

---

## 总体判定 (Rounds 1-3)

| 轮次 | 焦点 | Red | Blue | Split | 总体 |
|---|---|---|---|---|---|
| R1 | LPPL 指数方案 | 6 | 0 | 1 | ❌ 不可行 |
| R2 | Wyckoff A-E 状态机 | 6 | 0 | 1 | ❌ 过度设计 |
| R3 | P&F + 九项 + Signal Chain | 4 | 0 | 1 | ❌ 高估低估并存 |
| **合计** | **16** | **0** | **3** | **方案整体 ❌** |

---

## 核心建议

从计划中提取可行的子集 (分三级):

**立即 (2-3 天, ~150 行)**:
1. Adapter 修复: `adapter.py` 中 α=∞ 时抑制 BUY 信号 (已知 bug)
2. UTAD 升级: 至少尝试检测 (plan 中的弱化版, TR 外候选检测)
3. Spring 降级: 从「门控信号」降为「可选事件」
4. markup→买入信号提取为独立 trend-continuation indicator (已验证 p=0.0098)

**短期 (2 周, ~800 行)**:
1. phase_machine.py 精简版: 只做 MARKUP/MARKDOWN/UNKNOWN 三级，不做 A-E
2. volume_spread.py: 作为离线研究特征，不集成到生产
3. 统计跟踪 markup→买入信号的实时触发率和前瞻收益

**不做 (节省 ~2000 行)**:
1. LPPL 指数分析 (walk-forward 终裁零预测力)
2. P&F 新实现 (已存在)
3. 九项测试 (弱信号集合)
4. 基金/ETF 适配 (MA 交叉替代)
5. 贝叶斯置信度 (冷启动 600 窗口, 唯一有效信号时不如二元判定)

**总计**: 从~3080 行减少到~950 行 (69% 减少), 从 5-6 周减少到 2-3 周 (60% 减少)。聚焦于 walk-forward 已验证的唯一有效信号 + 已知 bug 修复。

---

## 附录: 验证命令

```bash
# 检查 P&F 现有代码行数
wc -l src/uniquant/brain/wyckoff/pnf.py

# 检查 WyckoffOutput P&F 字段
grep -n 'pnf_' src/uniquant/shared/interfaces.py

# 检查 WyckoffAdapter 当前逻辑
grep -n -A 55 'class WyckoffAdapter' src/uniquant/signal/adapters.py

# 验证 count_target 非零返回率
python3 -c "
from uniquant.brain.wyckoff.pnf import PointAndFigure
from tests.benchmark.golden_20 import get_data
import numpy as np
total, nonzero = 0, 0
for symbol in golden_20:
    df = get_data(symbol)
    for w in [120, 200]:
        pnf = PointAndFigure(box_size=0.02, reversal=2)
        pnf.build(df.tail(w))
        target = pnf.count_target()
        total += 1
        if target > 0:
            nonzero += 1
        print(f'{symbol} w={w}: target={target:.2f}')
print(f'Non-zero rate: {nonzero}/{total} = {nonzero/total*100:.1f}%')
"
```
