# Wyckoff Deep-Dive P0 实施验证报告 (2026-08-12)

> **验证对象**: `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` §5 P0 信号链根除七项 + §8 实施顺序第一阶段 (P0-1/2/6→P0-3→P0-4/5/7) 的**代码实施状态**与 **P2 验收门复现**。
> **方法**: `scripts/wyckoff_verify_20260812/` 六脚本实地验证 (A/B/C/D 四组)，全部只读扫描 CSV / 源码 / 配置，禁止改写被测数据。
> **结论**: **P0 七项实施全部落地并验收通过**；T3 维持 FAIL (叙事层裁决，X4 候选跟踪)；P1-3/P1-11 标注面按实施顺序留待 P1 阶段 (INCONCLUSIVE)。

---

## 0. 判定汇总

| 组 | 脚本 | 判定 | 结果文件 |
|---|---|---|---|
| A | `replicate_f7.py` | **PASS** | `results/wyckoff_verify_20260812/replicate_f7.json` |
| A | `replicate_t1_t3.py` | T1 **PASS** / T3 **FAIL** (预期) | `results/wyckoff_verify_20260812/replicate_t1_t3.json` |
| B | `check_impl_state.py` | B1-B8 **PASS** | `results/wyckoff_verify_20260812/check_impl_state.json` |
| C | `verify_seal_as_entry.py` | C1 **PASS** / C2 **INCONCLUSIVE** / C3 **PASS** | `results/wyckoff_verify_20260812/verify_seal_as_entry.json` |
| D | `golden_gate.py` | **PASS** (基线一致) | `results/wyckoff_verify_20260812/golden_gate.json` |
| D | `deterministic_assertions.py` | D1/D2/D3 **PASS** | `results/wyckoff_verify_20260812/deterministic_assertions.json` |

全量回归: **2092 passed / 8 skipped / 0 failed**；`ruff check src/uniquant/ tests/ scripts/`（本轮改动文件）**0**。

---

## 1. A 组 — 实证复现 (F7 / T1 / T3)

### 1.1 F7 五窗六类信号剔尾复核 (`replicate_f7.py`)

方法: clean 池 (fwd_20d 非空 ∩ 剔 ETF ∩ 剔 000/399 指数前缀) → 剔尾 |fwd_20d|≤10% → 每窗每类 MWU (vs 剔尾池其余, 双侧) + 剔尾均值。与定稿 `f7_x4/f7_x5.py` 及 Deep-Dive §3.1 同口径。

| signal_type | W1 | W2 | W3 | X4 | X5 | 同号显著窗口数 | 升级线(≥4) |
|---|---|---|---|---|---|---|---|
| distribution | −3.14 ns | +0.90 ns | −2.93 ns | **+2.93 (0.023)** | +0.18 ns | 1 | 未达 |
| markdown | −4.00 ns | +1.59 ns | −4.04 ns | +3.18 ns | **+1.28 (0.002)** | 1 | 未达 |
| leader | **−0.94 (<0.001)** | +0.14 (0.021) | **−1.29 (<0.001)** | +2.33 ns | **−1.54 (<0.001)** | 3 (负) | 未达 |
| accumulation | **−4.20 (0.003)** | **+2.19 (0.002)** | −2.40 ns | **+3.73 (0.0005)** | −0.21 ns | 0 | 未达 |
| markup | −1.75 ns | +0.55 ns | −1.02 ns | +2.77 ns | **−1.66 (0.011)** | 1 | 未达 |
| spring | −3.05 ns | **−0.53 (0.016)** | −3.77 ns | +2.67 ns | −0.51 ns | 1 | 未达 |

**overall = PASS**: 无信号类达到预注册升级线 (剔尾后 ≥2/3 窗 = ≥4/5 同号 p<0.05)。叙事层裁决 5 窗加强成立。

**重要口径说明 (文档内部不一致，如实披露)**:
- **X4/X5 复现与定稿 §3.1 完全一致** (distribution X4 +2.93 p=0.023 / markdown X5 +1.28 p=0.002 / leader X5 −1.54 p<0.0001 / accumulation X4 +3.73 p=0.0005 / markup X5 −1.66 p=0.011)。
- **W1-W3 复现数值与定稿表不一致** (符号层面): 定稿 W1-W3 数字 (e.g., distribution W1 +0.30, markup W1 +2.13) 源自早前 3 窗分析所用的**指数中性超额**口径; 本复现对 5 窗统一用**原始 fwd_20d** 口径 (与 f7_x4/x5 一致)。定稿 §3.1 表混用了两种口径。
- **leader 例外**: 一致口径下 leader 同号负显著达 3/5 窗 (W1/W3/X5)，未达 4/5 升级线但超过"无跨窗同号"的字面表述 → 定稿"六类信号全无跨窗同号显著"应修正为"**无 2/3 多数同号**"。方向主张不因 3/5 而升级 (F16 追涨动量 regime 反身结论不变)。

### 1.2 T1 direction map + T1b 门槛存活 (`replicate_t1_t3.py`)

| win | as-of | n_buy | SELL(映射) | 做空/卖出文本 | conf≥0.30 | conf≥0.40 | 存活率 0.40 |
|---|---|---|---|---|---|---|---|
| W1 | 04-30 | 137 | 0 | 0 | 100% | 91.97% | **92.0%** |
| W2 | 03-31 | 40 | 0 | 0 | 100% | 90.0% | **90.0%** |
| W3 | 05-29 | 66 | 0 | 0 | 100% | 90.91% | **90.9%** |
| X4 | 25-06-30 | 167 | 0 | 0 | 100% | 92.81% | **92.8%** |
| X5 | 24-12-31 | 120 | 0 | 0 | 100% | 62.5% | **62.5%** |

**T1 PASS**: 5/5 窗 BUY>0 且 SELL==0，与定稿完全一致。T1b 门槛 0.40 在 X5 拦截 37% 弱置信 (62.5% 存活)，其余窗 ~90-93% → P0-4 门槛 0.40 有实质拦截。

### 1.3 T3 BUY 集动量残差 (`replicate_t1_t3.py`)

| win | n_buy(≥0.40) | buy_exc_20d | M2 OLS 残差 (p) | R3 剔右尾 (p) | 独立增量 |
|---|---|---|---|---|---|
| W1 | 126 | +1.37 | +0.04 (0.51) | −0.67 (0.29) | ✗ |
| W2 | 36 | −6.59 | −6.31 (0.023) | −3.65 (0.34) | ✗ |
| W3 | 60 | +3.51 | −0.27 (0.39) | +2.02 (0.95) | ✗ |
| X4 | 155 | +4.20 | **+4.21 (0.0003)** | **+4.96 (0.0001)** | ✓ |
| X5 | 75 | −1.54 | −0.97 (0.12) | −1.60 (0.25) | ✗ |

**T3 = FAIL (维持叙事层裁决)**: 1/5 窗 (X4) 独立增量，未达 ≥2/3 窗升级线。与定稿 §3.3 数字逐位吻合。X4 记录为"牛市 beta 待复验候选"（未来 ≥3/5 窗再评估）。

---

## 2. B 组 — P0 实施状态 (B1-B8, `check_impl_state.py`)

| # | 检查 | 结果 |
|---|---|---|
| B1 | P0-1 WyckoffOutput.direction 字段 + to_dict/from_dict `wyckoff_direction` roundtrip | **PASS** |
| B2 | P0-1 `_extract_from_report` 从 `trading_plan.direction` 提取 (覆盖 MTF 融合 final_report) | **PASS** |
| B3 | P0-3 ResearchPackWriter 仅展平 wyckoff 键 (metadata 无意外键) | **PASS** |
| B4 | P0-2 adapter direction gate — 做多/买入/轻仓试探→BUY, 其余→None; phase/spring/utad 无直映射 | **PASS** |
| B5 | P0-4 config `confidence_gate=0.40` | **PASS** |
| B6 | P0-5 config + engine `structural_adjust_enabled` 默认 false | **PASS** |
| B7 | P0-6 normalizer `_DIRECTION_MAP` 6/6 项为 0 | **PASS** |
| B8 | P0-7 恒不产 SELL-as-entry (scan_signal 恒 BUY/HOLD; normalizer 无 −1 注入) | **PASS** |

**B 组 = PASS (8/8)**。运行时断言 + 配置断言双保险。

---

## 3. C 组 — SELL-as-entry 密封性与标注面状态 (`verify_seal_as_entry.py`)

### C1 (P0-7) 密封性 = **PASS**
- adapter: 13 个候补方向文本 (含 做空/卖出/减仓/清仓/空串/复合文本) 遍历 → 恒 None 或 BUY，**无 SELL**。
- normalizer: distribution/markdown/markup/accumulation/spring/utad normalize 后 direction 恒 0 (无 −1)。
- scan_signal: 合成 accumulation/trading_range fixture → action ∈ {BUY, HOLD}，无 SELL。
- unified_engine: SELL 仅在 `position > 0` 执行 (unified_engine.py:420) → 只平仓语义保持。

### C2 (P1-3 sos 标注面) = **INCONCLUSIVE**
- `sos_candidate` 现状 = signal_type 标注 (engine.py:1699/1723, analysis.py:275-281)，非入口方向。
- 独立布尔字段 `sos_candidate_detected` 未实现，config `sos_candidate_annotation` 未设置 → 按定稿 §8 顺序留待 **P2 验收后 P1-3** 实施。当前无方向泄漏。

### C3 (P1-11 stoploss_guard) = **PASS** (config 默认关声明)
- `stoploss_guard_enabled: false` / `stoploss_guard_depth_pct: 15` / `stoploss_guard_grace_days: 3` 已入 P0 config 段 (§6 清单)。
- 功能代码留待 P1 阶段；FSM FORCE_EXIT→SELL(1.0) 为唯一常开止损层。

---

## 4. D 组 — 三层验收门

### D1 确定性断言映射表 100% (`deterministic_assertions.py`)
- 五窗 T1 断言 (BUY>0 / SELL==0 / 无做空卖出文本) 全过。
- 运行时 adapter 矩阵 10 断言全过 (3 入场方向→BUY / 2 弱置信→None / 5 非入场方向→None)。
- **D1 = PASS**。

### D2 预注册 MWU 门槛
- 六类信号同号显著窗口数 = 1/1/3/0/1/1，无信号类达 4/5 升级线。
- **D2 = PASS** (无方向主张升级 → 维持叙事+风控层)。

### D3 markup 置信存活表
- 0.40 门槛存活率复现: W1 92.0% / W2 90.0% / W3 90.9% / X4 92.8% / X5 62.5%，与定稿 T1b 逐位吻合。
- **D3 = PASS** (参考匹配)。

### D4/P2-5 golden baseline 前后对比门 (`golden_gate.py`)
- git HEAD `baseline_v0.parquet` vs 当前捕获 (golden_20 全管线) → 20/20 窗口 **4 标量字段 (total_signals/total_trades/total_return/final_cash) 全一致**。
- 佐证 F12: P0 改动在 RDP 默认路径下不影响 Wyckoff→TradingSignal 链，无意外漂移。
- **D4 = PASS**。

---

## 5. 验收结论与开放项

- **P0 七项全部落地**: direction 透传 / adapter direction gate / RDP 仅展平 wyckoff 键 / 置信门槛 0.40 / structural_adjust 默认关 / normalizer+scan_signal 抵销 / 恒不产 SELL-as-entry，运行时 + 断言 + 五窗实证三重确认。
- **未发现 SELL-as-entry 泄漏**; 未发现相位/spring/utad 直映射残留。
- **待办**: P1-3 (`sos_candidate_detected` 独立布尔字段) 与 P1-11 (stoploss_guard 功能) 按 §8 顺序在 P2 验收后实施 (C2 INCONCLUSIVE); T3 X4 单窗候选跟踪。
- **文档修正建议**: Deep-Dive §3.1 F7 表 W1-W3 为超额口径与 X4/X5 原始口径混用，应统一口径; "全无跨窗同号"表述修正为"无 2/3 多数同号 (leader 3/5 例外)"。

---

## 6. 产物

| 产物 | 位置 |
|---|---|
| 验证脚本 (0 ruff) | `scripts/wyckoff_verify_20260812/{replicate_f7,replicate_t1_t3,check_impl_state,verify_seal_as_entry,golden_gate,deterministic_assertions,_common}.py` |
| 结果 JSON | `results/wyckoff_verify_20260812/*.json` (6 份) |
| 本报告 | `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md` |

---

## 7. 附录: 深度验证 V2 (2026-08-12 并行执行)

### 背景
对 P0 实施做更深层验证：F7 口径统一稳健性、P0 后方向映射实证、T3 X4 多重检验、全信号链泄漏审计、A股铁律交互。5 路并行 subagent 执行，脚本在 `scripts/wyckoff_deep_verify/`，结果 JSON 在 `results/wyckoff_deep_verify/`。

### 结果汇总

| 任务 | 判定 | 脚本 | 关键发现 |
|---|---|---|---|
| **V1** F7 口径稳健性 | **PASS** | `v1_f7_robustness.py` | leader 3/5 对 4 种剔尾边界 (5/10/15/20%) 和单侧/双侧 MWU 完全稳健；markup/accumulation 在特定边界可达 3 窗但未达 4/5 升级线 |
| **V2** P0 后方向映射 | **PASS** | `v2_post_p0_direction_map.py` | 5/5 窗 BUY>0 且 SELL=0；方向查找表: 7 个唯一文本, 3→BUY, 4→None, 零例外 |
| **V3** X4 多重检验 | **PASS** (维持候选) | `v3_x4_multitest.py` | Bonferroni 校正后 p=0.00063 仍显著；效应由最低 relmom 桶 (超跌) 驱动→修正"牛市 beta"为"**牛市超跌反弹**" |
| **V4** 全信号链泄漏 | **PASS** | `v4_signal_chain_leak.py` | 220 单元格路径覆盖矩阵 0 SELL；arbitrator Wyckoff SELL 分支 = dead code |
| **V5** A股铁律交互 | **修复→PASS** | `v5_ashare_guard.py` | 发现涨停守卫缺口→修复 (`engine.py:1544-1560` 加 LIMIT_UP/BREAK_LIMIT_UP 守卫+精确价差容差)；3 新测试通过 |

### V5 修复详情
**问题**: `engine.py _step5_trading_plan` 原仅 LIMIT_DOWN 强制空仓，缺 LIMIT_UP 守卫。单涨停日 + MARKUP 相位 → direction="做多" → adapter 因 direction∈{做多,买入,轻仓试探} 输出 BUY。该泄漏非 P0 回归 (P0 前后一致)，但属 A股铁律缺口。

**修复**: 增加 LIMIT_UP 和 BREAK_LIMIT_UP 守卫，用精确价差 (0.5% 容差) 避免合成数据误报。新增 `tests/classic_wyckoff/test_limit_up_guard.py` 3 用例。

**最终测试**: 2104 passed / 8 skipped / 0 failed, 0 ruff, golden 门一致。
