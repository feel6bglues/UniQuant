# 03 因子与策略域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook | SHA `ddd678a` | 批 B3：P0=F1,F2 + P1=F4,F5；批 B4：F3 定稿 + F4 补跑 + F6（P2）

## 结论（3 句内）

H-A 四件套**产物+脚本+预注册全部在位**，P8 核心数（STRAT-A **+15.82%/1.331/−12.9%**）与 AGENTS **精确一致**；conditional H-A **PASS**、capacity F1/F2 **FAIL** 与 AGENTS 叙述一致。**bp 五门幸存**（bp oos_ic 0.0558/ICIR 1.93/PBO 0.166 三门 true）与 P14 一致，但 **P15 组合层数字与 AGENTS 漂移**（JSON +8.91%/0.867 vs AGENTS +9.52%/0.92）→ **C6**。`five_gate.py`+fwd5 回归 4 测试在位；P14 结果文件名实际为 `cash_fcf_dy_test.json`。

## 证据（file:line @ ddd678a / JSON 键路径）

### F1 H-A 主线四件套增量核验（P0，≤15 行）

| # | AGENTS 断言 | 产物实测值 | 一致? | 出处 |
|---|-------------|------------|:-----:|------|
| 1 | P8 STRAT-A 年化 +15.82% | `ann_return=0.1582` | ✓ | `portfolio_validation_ha.json` `.strategies.STRAT_A_cond_illiq` |
| 2 | P8 夏普 1.33 | `sharpe=1.331` | ✓ | 同上 |
| 3 | P8 回撤 −12.9% | `max_drawdown=-0.1288` | ✓ | 同上 |
| 4 | P8 在场 17% | episodes 19 片段（AGENTS） | ✓（结构） | `.episodes` 存在；`_meta.rebalance_every=5` |
| 5 | CTRL-B +13.97%/0.65/−43.7% | 0.1397 / 0.649 / −0.4366 | ✓ | `.strategies.CTRL_B_uncond_illiq` |
| 6 | CTRL-C 6.89%/0.60 | 0.0689 / 0.604 | ✓ | `.strategies.CTRL_C_random_in_state` |
| 7 | H-A 条件验证四门 PASS | `candidates.H-A.verdict=PASS`（H-BL/H-BS/H-C=FAIL） | ✓ | `conditional_validation.json` `.candidates` |
| 8 | P10 全市场 +9.98%/0.93/−22.2% | 0.0998 / 0.933 / −0.2215 | ✓ | `capacity_validation.json` `.strategies.FULL_no_floor` |
| 9 | P10 F1 夏普≥1 FAIL | `verdict.F1_fullnet_positive_and_sharpe_ge1=False` | ✓ | 同上 |
| 10 | 地板块夏普 0.78 回撤 −12.8% | 0.776 / −0.128 | ✓ | `.strategies.FULL_floor2000w` |
| 11 | 容量 ≈2850 万（ADV 28.5 亿×10%） | `held_adv_sum_median_yi=28.5`, `participation=0.1` | ✓ | `.capacity` |
| 12 | ever_held 385 | `_meta.n_ever_held=385` | ✓ | `ha_unified_adapter.json` |
| 13 | 生产引擎样本500 +7.43%/0.68 | rotation `ann_return=0.0764, sharpe=0.6811` | ✓（0.0764≈7.64%，AGENTS 另处 7.43%——**轻微口径差，见备注**） | `ha_rotation_sim.json` |
| 14 | 脚本四件套 | `run_portfolio_validation` / `daily_signal_ha` / `ha_unified_adapter` / `ha_rotation_sim` 全 exists | ✓ | pathlib |
| 15 | 预注册 CONDITIONAL_VALIDATION | `docs/analysis/CONDITIONAL_VALIDATION_PREREGISTRATION.md` exists | ✓ | — |

**备注**：AGENTS P13「样本500 +7.43%/0.68/−14.99%」vs JSON rotation `0.0764/0.6811/−0.1281` — 夏普一致、收益/回撤有差（可能不同 run）。**不改判主线**，记 M 级口径备注。

**主落盘产物路径**：`results/factor_mining/{conditional_validation,portfolio_validation_ha,capacity_validation,ha_unified_adapter,ha_rotation_sim}.json` — **5/5 在位**。

### F2 bp / P15 / five_gate / fwd5（P0）

| 项 | AGENTS | 实测 | 一致? |
|----|--------|------|:-----:|
| bp 五门 OOS IC +0.0558 | 幸存 | `fundamental_factor_test.json` `.per_factor.bp.oos_ic_mean=0.0558` | ✓ |
| bp ICIR 1.93 | 幸存 | `icir=1.9328`, `passed_ic/icir/pbo=True` | ✓ |
| bp PBO 0.166 | 幸存 | `pbo=0.1655`, all three gates True | ✓ |
| five_gate 模块 | 共享 | `scripts/factor_mining/five_gate.py` LOC=228，`correct_fwd5` @36 | ✓ |
| fwd5 回归 4 测试 | 4 | `tests/test_fwd5_regression.py` n=4（future_0_5 / differs_from_buggy / grouped / matches_analyzer） | ✓ |
| P14 测试 19 | 19 | `tests/test_p14_cash_fcf_dy.py` n=**17**（非 19） | **部分**（17≠19，AGENTS 计数含/不含 capex 追加） |
| P14 脚本名 | `run_p14_cash_fcf_dy_test.py` | **不存在**；实际 `scripts/factor_mining/run_cash_fcf_dy_test.py` | **C7 文件名漂移** |
| P14 结果 | （未点名路径） | `results/factor_mining/cash_fcf_dy_test.json` exists | ✓ |
| P15 预注册+结果 | `P15_BP_HA_PORTFOLIO_PREREGISTRATION.md` | exists ✓；结果 `bp_ha_portfolio.json` / `bp_ha_unified.json` exists ✓ | ✓ 路径 |
| **P15 条件 bp +9.52%/0.92/−10.63%** | AGENTS 宣称 | JSON `.strategies.STRAT_A_cond_bp` = **0.0891 / 0.867 / −0.1133** | **❌ C6 数字漂移** |
| P15 vs illiq 夏普 −0.41 | AGENTS | `.verdict.Q4_vs_ha_illiq_sharpe_diff=-0.463` | **≈但不等于 −0.41**（C6 同族） |
| P15 生产 scaled_30 +4.95%/0.52 | AGENTS | `bp_ha_unified.json` `.aggregate.scaled_30` = 0.0495 / 0.5184 | ✓ |
| bp 测试 6 | 6 | `tests/test_bp_ha_portfolio.py` n=6 | ✓ |
| five_gate **结果 JSON** | （未强制） | `results/**/*five*` = **0 命中** | 无独立 five_gate 产物（结果并入 fundamental/cash JSON） |

**裁决 C6**：P15 组合层「+9.52%/夏普0.92/回撤−10.63%/夏普差−0.41」与当前 `bp_ha_portfolio.json` **不一致**（实测 8.91%/0.867/−11.33%/−0.463）。权威序：**JSON 产物 > AGENTS 文字**。可能 AGENTS 写的是另一 run 或 rounded 变体；**以 JSON 为准入文**，P15「可交易无增量、弱于 illiq」**方向结论仍成立**（Q4 大幅为负）。

**裁决 C7**：AGENTS 点名的 `run_p14_cash_fcf_dy_test.py` 不存在 → 实名 `run_cash_fcf_dy_test.py`（文档路径漂移，非功能丢失）。

### F3 注册表规模（P1，B4 完成）

| 项 | 实测 |
|----|------|
| 正确入口 | `uniquant.brain.factors.custom_factors.register_all` @ `custom_factors.py:687` |
| 自动触发 | 模块末行 `:988` 调用 `register_all()` → **import 即注册** |
| registry/包导出 | `register_all` **不在** `registry.py` / `factors/__init__` → B3 ImportError 原因确认 |
| 注册数 | `FactorRegistry.list_factors()` = **39**，全部 `enabled` |
| category | technical **10** / custom **16** / fundamental **13** |

**39 名单**：momentum_20d/60d, volatility_20d/60d, ma_ratio_5_20, ma_ratio_10_60, volume_ratio_5_20, rsi_14, price_position_20d, turnover_momentum_20d, illiq_20d, pv_divergence_20d, cs_momentum_20d, idiosyncratic_vol_20d, max_ret_20d, reversal_1d, amivest_20d, range_20d, skew_20d, reversal_5d, reversal_20d, neg_range_20d, ep_ttm, bp, cfp_ttm, sp_ttm, gross_profitability, accruals, turnover_20d, cash_ratio, fcf_yield, real_dy, cvar_95_60d, max_drawdown_20d, downside_semivol_20d, kurtosis_20d, holder_num_chg_1q, inst_shares_chg_1q, top10_float_chg_1q。

**与 AGENTS 对照**：P11 七 + P12 七 + P14 三 + 既有价量/逻辑因子均已入表；**无挖掘终结后新因子** → 「P12 后终结挖掘」**一致** ✓。

### F4 five_gate / fwd5 可跑性（P1，B4 补跑）

| 文件 | 状态 | 备注 |
|------|------|------|
| `scripts/factor_mining/five_gate.py` | ✓ 228 LOC | docstring 自证 2026-08-28 fwd5 修复 |
| `tests/test_fwd5_regression.py` | ✓ 4 tests | **B4 已跑：4 passed, EXIT=0**（含 pkg_resources DeprecationWarning，非失败） |
| `tests/test_p14_cash_fcf_dy.py` | ✓ 17 | 未单跑（B5 可选） |
| `tests/test_bp_ha_portfolio.py` | ✓ 6 | 未单跑（B5 可选） |

### F5 预注册文档在位（P1）

| 赛道 | 路径 | exists |
|------|------|:------:|
| 条件验证 | `docs/analysis/CONDITIONAL_VALIDATION_PREREGISTRATION.md` | ✓ |
| P12 | `docs/analysis/P12_PREREGISTRATION_TAIL_CHIP_FACTORS.md` | ✓ |
| P14 | `docs/analysis/P14_CASH_FCF_DY_PREREGISTRATION.md` | ✓ |
| fundamental | `docs/analysis/FUNDAMENTAL_FACTOR_PREREGISTRATION.md` | ✓ |
| P15 | `docs/analysis/P15_BP_HA_PORTFOLIO_PREREGISTRATION.md` | ✓ |

对齐抽查（键级，非全文）：P8/H-A/capacity/bp 核数已在 F1/F2 表覆盖 **5+ 行** ✓。

### F6 results/factor_mining 产物矩阵（P2，B4 完成）

- 目录文件数：**23**。
- AGENTS 抽查 14 个被引用 JSON：**全 exists**（conditional_validation / portfolio_validation_ha / capacity_validation / ha_unified_adapter / ha_rotation_sim / fundamental_factor_test / bp_ha_portfolio / bp_ha_unified / cash_fcf_dy_test / p12_tail_chip / overnight / regime_conditional / gp_mining / baseline_walkforward… 以 pathlib 实测为准）。
- 与 F1/F2 键级核验合并 → **产物在位矩阵绿**；无新缺失。

**F4/F3/F6 状态：完成。**

## 与历史对账

| 历史 | 状态 |
|------|------|
| P8 +15.82/1.33 | **✓ JSON 精确** |
| H-A 四门 PASS | **✓** |
| P10 capacity F1/F2 FAIL + 28.5 亿 | **✓** |
| bp 五门幸存 | **✓** |
| P15 +9.52/0.92 | **❌ C6 → 以 JSON 8.91/0.867 为准** |
| P14 脚本路径 | **❌ C7 更名** |
| 挖掘终结 / Tier-B | **不复跑**（本批只核键） |

## 风险分级

| 级 | 项 |
|----|-----|
| **H** | C6：P15 关键数字与产物不一致，若引用 AGENTS 会错报策略表现 |
| M | C7 脚本名漂移；P14 测试 17 vs AGENTS 19 |
| M | rotation 7.64% vs AGENTS 7.43% 口径未锁 |
| five_gate 无独立结果 JSON | **已知 L 级**（结果并入 fundamental/cash JSON） |

## 建议动作

1. 修正 AGENTS P15 段数字为 JSON 值或注明 run id — DoD：AGENTS 与 `bp_ha_portfolio.json` 键一致（批准后）。
2. 修正 AGENTS P14 脚本路径为 `run_cash_fcf_dy_test.py` — DoD：路径 exists。
3. ~~B4：register_all 入口~~ **已完成**；B5：可选 `pytest tests/test_p14_cash_fcf_dy.py tests/test_bp_ha_portfolio.py -q`。

## 本批变更

B3+F1/F2/F4/F5 / B4+F3/F4补跑/F6；仅 FULL_AUDIT 文档；**无源码/config/AGENTS 变更**；**未复跑五门/组合全量**。
