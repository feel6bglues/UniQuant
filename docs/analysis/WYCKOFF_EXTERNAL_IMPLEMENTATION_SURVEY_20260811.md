# Wyckoff Python 实现外部调研 (2026-08-11)

> 目标：检索并深读互联网上"Python 实现经典 Wyckoff 分析"的现有方案，
> 提取可借鉴的工程实现，并与 UniQuant 已完成的证伪链结论对照。
> 前情：本项目 60+ 篇研究已证明"相位标签→方向预测"在 A 股无独立正 alpha，
> 引擎降为叙事/风控层。因此外部方案一律以「事件/结构标注质量」而非「方向预测能力」评估。

## 调研范围

| 候选 | 类型 | 是否深读 | 结论 |
|---|---|---|---|
| PyPI `wyckoff` | 晶体学结晶包 | ✗ | **排除**，与交易无关 |
| `abdstg/wyckoff` | LLM agent (Gemini) | ✗ | 排除，非规则化引擎 |
| `cjknox/PyPnF` / `stocktrends` | P&F/renko 制图 | ✗ | 低，本项目已有 `pnf.py`，P&F 已证伪为死循环根源 |
| `ozymandias0123/Wyckoff-Trading-Method-` | MT5 交易 bot | ✅ 1241 行 | 教科书式 naive 实现，负面样本 |
| `casoon/pine-scripts/wyckoff_schematics` | TradingView Pine 指标 | ✅ 1307 行 | **工程化最佳**，标注质量可借鉴 |
| `YoungCan-Wang/WyckoffTradingAgent` | A股 5 层漏斗 agent(LLM) | ✅ 3002 行核心 | A股实战工程，Wyckoff 降为狙击层 |
| `srlcarlg/srl-python-indicators` | Weis & Wyckoff | ✗ | 重可视化，未深读 |

---

## 一、ozymandias0123/Wyckoff-Trading-Method-/Wyckoff.py (负面样本)

MT5 全功能 bot（五步法 / A-E 相位 / 全事件 / 九测试 / 供需求 / Effort vs Result / Telegram）。

### 实现要点
- **事件检测**：`tail(30)` 窗口 + TR = 近 30 bar `high.max()/low.min()`；均价/均幅做基准；全事件 PS/SC/AR/ST/Spring/Test/SOS/LPS/BU/PSY/BC/UTAD/SOW/LPSY。
  - Spring: `low < tr_low*(1-0.0005)` 且 `close > tr_low` 且缩量。
  - UTAD: `high > tr_high*(1+0.0005)` 且 `close < tr_high` 且放量>1.2。
- **相位**：`identify_accumulation_phase` 无状态机——每个 bar 的事件直接覆盖整个 phase 判定（SC/PS→A、ST→B、spring→C、SOS/LPS→D、close>tr*1.01→E），无序列约束。
- **九测试**：test2/3/4/5/6/7/8/9 是简单趋势/动量代理；**test1 直接"其他测试过 5 则补真" → 凑数假测试**。

### 缺陷（对照 UniQuant 证伪链）
1. **事件→相位 one-shot 直映射** = 本项目最初的 `_step1`，无多列序列验证。
2. Spring/UTAD 用固定 0.05% 深度阈值（无 ATR 相对化），极度过拟合价。
3. TR 检查 `tr_range > threshold*2` 直接 return —— 与 `pnf.py` 27K 观测 99.8% unknown 同类弃用。
4. 无回测、无统计验证、无 A 股涨跌停守卫，无单窗/多窗概念。
5. **test1 补真逻辑不可复制**。

---

## 二、casoon/pine-scripts/wyckoff_schematics.pine (最佳标注逻辑)

TradingView Pine v6，1307 行。作者 WavesUnchained。

### 实现要点
- **状态机**：`WyckoffPhase{name, subphase, phaseAE A-E, startBar, rangeHigh/Low, springUtad{bar, price, volRatio}}` + `WyckoffEvent` 事件流 + `WyckoffState`。
- **Schematic #1/#2**：`#1` = Spring/UTAD → Test 序列；`#2` = 无 Spring 直接 SOS/SOW。
- **序列验证（关键）**：`eventBar()` 记录事件 bar 索引，`calcSetupScore` 要求
  `springB < testB < sosB`（Spring→Test→SOS 严格有序）才给 seq+8 分——
  **比引擎 `event_sequence_key` 更强的顺序约束**。
- **事件检测 ATR 相对化**（关键改进）：
  - Spring: `minBreak = max(atr*0.25, rangeWidth*springThreshold%)`，
    `springDepth >= minBreak 且 close>rangeLow 且 wickRatio>=0.25`（下影线比例）。
  - UTAD 对称（上影线比例）。
  - SOS/SOW: `rangeProgress = (close-rangeLow)/rangeWidth >= 70% and volRatio>=1.5`。
  - ST: 回测级别 `within ±5%(climaxRef)` + 缩量 + 窄幅。
  - AR: 需从高潮极值走 ≥1 ATR 才算真反弹（防第一根反抽误标）。
- **Effort vs Result**：`effort=vol/volAvg, result=spread/spreadAvg`；
  `effort>2 & result<0.8` → CLIMAX(90)；`effort>1.5 & result>1.5 & closePos` 分档。
- **双评分**：`rangeScore`(时长 20-80b +20 / 宽度 1-5ATR +25 / 量缩 +20 / 多次枢轴回测 +15 / 高潮量≥2.5 +20) +
  `setupScore`(AR+8 ST+8 phaseC/D+5 spring+18 test+18 sos+14 sosb+12 lps+10 seq+8 RS+8 HTF+8)。
- **突破需要结构完整**：`canMarkup = phaseAE=="D" and setupScore>=50 and (springConfirmed or SOS/LPS存在) and volRatio>=1.2`；
  仅收盘>范围上沿不够（random Phase-B probe 不再触发）。
- **失效**：`invalidBuffer = rangeWidth*0.33`，跌破失效为 RANGING/FAIL。
- RS/HTF/AVWAP 只作分项加分（+8），**不主导相位**——与"leader 唯一真信号"兼容。

### 可借鉴点
1. Spring/UTAD 的 **ATR 相对化 + 影线比例**，替代 A 股引擎 `_scan_spring` 固定 0.5-1.5% 深度。
2. **Spring→Test→SOS 严格序**校验（eventBar），强化引擎 `event_sequence_key`。
3. SOS/SOW 用 `rangeProgress` 而非裸突破，降低假突破。
4. 双评分体系与引擎 `structure_score` 同思路，但惩罚"结构不完整"的突破。

---

## 三、YoungCan-Wang/WyckoffTradingAgent/core/wyckoff_engine.py (A股实战)

5 层漏斗：L1 剥垃圾(板块/市值/流动性/ST) → L2 八通道(RPS/RS/蓄势/地量/护盘/趋势/突破/点火) →
L2.5 Markup → L3 板块共振 → **L4 威科夫狙击(Spring/SOS/LPS/EVR/Compression/TrendPullback)** → L5 退出。

### 实现要点
- **A 股特殊性**：
  - `_is_frozen_board_day`：一字板(日波幅≤1%且开收差≤1%)**排除出 Spring/EVR/SOS 判定**——
    一字跌停无真实换手，"放量/收回"物理上无意义。与引擎 `_step5` 涨跌停处理同源。
  - `_BOARD_VOLATILITY_SCALE {chinext:1.2, star:1.4, bse:1.2}`：价格类阈值(如 EVR 滞涨波幅)
    按板放宽；**量比类不缩放**（量比已按个股归一化，实测四叔板分布几乎重合）。
- **Spring**：TR 用 ATR 动态幅度 `atr_pct*4.0`(cap 30%~60%)；允许"前一日或当日盘中"跌破支撑
  + 当日收回放量 `last/prev > 1.15`。
- **LPS**：MA20 回踩 + 缩量(<0.65) + **creek line 越野确认**（swing high 连线，突破 + 持有容忍）。
- **SOS/JAC**：`pct_min 6%`(原 4.5 追高止损率高) + 量 95% 分位爆量 + 突破 60 日高或 MA50 穿越。
  **注释自曝工程经验**：提高 SOS 阈值 → 被门槛卡掉的边际样本胜率(28.9-38.0%)
  系统性高于留存样本(22.2-29.1%)，即"门槛越高留下样本越差" = **幸存者偏差警告**——
  直接印证本项目"调参数非换语义"的四个死循环之一。
- **EVR**：仅认"低位巨量滞涨"(|pct|≤2% 按板缩放) + 结构确认(近3日不破位)，排除高位派发。
- **Compression**：连续 ATR 收窄 ≤ 历史 20% 分位 + 量枯竭 <0.6 + 方向约束(非下降结构)。
- **UTAD（Distribution 警告）**：`swing_highs[-5:].median()` 阻力 + 突破≥1% + 收回≥0.3%
  + 上影线比≥0.35 + 量比≥1.5 + bias200≥15% → 高位假突破警告。
- **全局 Anti-overfitting**：`global_entry_max_bias_200=25%` 等 bias 上限 + RPS 门。
- **Wyckoff 定位**：L4 仅作最终狙击确认，**主通道是 L2 的 RPS/RS/动量**——
  有意把 Wyckoff 降为非方向层，与 UniQuant"引擎降为叙事/风控层"结论工程化一致。

### 可借鉴点
1. **一字板守卫**进 Spring/SOS/EVR 判定（A 股特有）。
2. **SOS 95% 分位爆量** + bias200 上限。
3. **EVR 双口径**：低位滞涨(做多侧) + 高位派发(做空侧/风控)分流。
4. **门槛-A 胜率反向实证注释**：调参内容直接推进了幸存者偏差认识。

---

## 四、与 UniQuant 证伪链的对照结论

| 外部实现做了什么 | 本项目证伪结论 | 采用的判定 |
|---|---|---|
| ozymandias 事件→相位 one-shot | 03-31 相位映射方向全灭 | ❌ 不引入 |
| casoon Phase D + 序列验证 + setupScore≥50 才突破 | leader×spring 证伪但结构完整性=风控层质量 | ✅ 借鉴标注层 |
| casoon ATR 相对化 Spring/UTAD | `_scan_spring` 0.5-1.5% 固定深度 | ✅ 替代 |
| casoon SOS rangeProgress≥70% | 假突破惩罚 CF-C4 已有 | ✅ 可选强化 |
| YC 一字板守卫 / 板波动缩放 | `_step5` 涨跌停 + A股铁律 | ✅ 已有，可对照 |
| YC SOS 极高阈值=幸存者偏差 | "调参数非换语义"死循环 | ✅ 理论印证 |
| YC 把 Wyckoff 放狙击层 | 引擎降为叙事/风控层 | ✅ 架构印证 |
| 九测试(ozymandias) | 成功率≠alpha，研究管线 Sharpe 2.02 假象 | ❌ 不引入 |

**最终立场**：三个外部方案里没有"能解决 A 股方向预测"的实现——它们全部做"相位→方向"映射，
正是本平台证伪链已推翻的映射。外部价值集中在**事件标注的工程细节**（ATR 相对化、影线比例、
严格序列序、一字板守卫、分位爆量、bias 上限），这些可边际提升引擎作为叙事/风控层的标注质量，
但**不改变"相位无独立正 alpha"的结论**。

## 素材位置
已克隆到 `/tmp/opencode/wyckoff_research/`：
- `Wyckoff-Trading-Method-/Wyckoff.py` (1241 行)
- `pine-scripts/indicators/market_structure/wyckoff_schematics/wyckoff_schematics.pine` (1307 行)
- `yc_wyckoff_engine.py` (YoungCan-Wang，3002 行，raw 抓取) + `yc_wyckoff_events.py` (181 行)

## 待办（可选）
- [ ] 若重启引擎标注层：以 casoon `_scan_spring/_scan_utad` ATR 相对化参数为对照 baseline 写测试
- [ ] 若需要：深读 `srl-python-indicators` 的 Weis & Wyckoff 可视化体系对照 MTF 共振