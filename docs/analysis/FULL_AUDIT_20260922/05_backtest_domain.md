# 05 回测可信度域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook 阶段产物 | SHA `ddd678a` | 批 B2=B1约束；批 B3=B2鞍律+成本等；批 B5=B6 baseline + 单测补跑

## 结论（3 句内）

A 股七类执行约束（T+1、涨跌停买拒/卖拒、印花税卖方、佣金万3+最低5元、滑点万5、整手 lot、过户费）**全部在 `unified_engine` + `unified_matching_engine` + `cost_model`/`market_rules`/`limit_checker` 实现且默认开启**，并有**成体系测试**（matching 14+21、limit_checker 30、cost_model 19）。DynamicSlippage 仍为死路径（注释自证 + 全 src 仅类定义 1 引用），常数 `SLIPPAGE_PCT` 为唯一默认生效滑点。**B3 鞍律**：`REBALANCE_EVERY=5` + 非再平衡日 `carried` 沿用在位，2 鞍律回归测试 ID 存在；**B4** `walk_forward_definitive_report.json` 路径**不存在（C8）**。

## 证据（file:line @ ddd678a）

### B1 约束×实现×测试×默认 开关表（P0）

| 约束 | 实现 file:line | 默认开启? | 测试文件 | 关键测试 ID（节选） |
|------|----------------|:---------:|----------|---------------------|
| **T+1** | `unified_engine.py:8` 宣称；`:352-355` 执行前检查+结转；`:576-589` `_check_t1` 序号差≥1 | **是**（内联，无 off 开关） | `tests/test_matching_engine.py`；`tests/test_unified_matching.py` | `test_t1_violation_rejected`、`test_t1_next_day_allowed`、`test_buy_sell_same_day_sell_rejected`、`test_sell_next_trading_day_allowed` |
| **涨停不买** | `unified_matching_engine.py:199` `limit_rejected=is_limit_up`（买）；`:130-180` 板别涨跌停计算；`limit_checker.py:110-134` | **是** | `test_matching_engine.py`、`test_unified_matching.py`、`test_limit_checker.py`（30） | `test_limit_up_rejection`、`test_limit_up_blocks_buy`、`test_limit_up_main_board` |
| **跌停不卖** | `unified_matching_engine.py:263` `limit_rejected=is_limit_down`（卖）；`unified_engine` 防线 B 宣称 `:9` | **是** | 同上 + `test_limit_down_rollover.py` | `test_limit_down_rejection`、`test_limit_down_blocks_sell` |
| **印花税（卖方）** | `cost_model.py:29-31,44-45,62` `get_stamp_tax_pct`；matching `:39` 默认 0.0005 | **是** | `tests/test_cost_model.py`（19） | `test_stamp_tax_is_0_05pct_sell_side`、`test_buy_no_stamp_duty`、`test_stamp_duty_on_sell` |
| **佣金万3 + 最低5元** | `cost_model.py:29,32,61` `max(value*COMMISSION, MIN_COMMISSION)`；matching `:38,40` | **是** | `test_cost_model.py` | `test_commission_is_0_03pct`、`test_min_commission_is_5_cny` |
| **滑点（常数万5）** | `cost_model.py:33` `SLIPPAGE_PCT=0.0005`；`slippage_model.py:14-17` `DefaultSlippage`；matching `:41` 默认 | **是** | `test_matching_engine.py`、`test_cost_model.py` | `test_slippage_is_0_05pct`、`test_slippage_model_adapter_default` |
| **过户费** | `cost_model.py:36-37` `TRANSFER_FEE_PCT` 并入 COST_BUY/SELL | **是** | `test_cost_model.py` | `test_transfer_fee_is_0_001pct` |
| **整手 100 股** | `market_rules.py:12-17,21-26,38-40` `round_lot`；`unified_engine.py:715-731`；matching `:211,217` `// lot_sizes` | **是** | `test_market_rules_drift.py`；matching 内隐含 | board lot 表 MAIN/GEM/BEIJING/ST=100，STAR=200 |
| **信号 T→T+1 Open 成交** | `unified_engine.py:160,307` 挂单 Step1 | **是** | matching/engine 测试 | 时序约定文档化 |

**cost_model 权威常量**（`cost_model.py:29-33`）：

```
COMMISSION_PCT = 0.0003   # 万3
STAMP_TAX_PCT  = 0.0005   # 万5 (2023-08-28 起)
MIN_COMMISSION = 5.0
SLIPPAGE_PCT   = 0.0005   # 万5
```

**market_rules 板别**（`market_rules.py:21-26`）：MAIN_SH/SZ lot=100 limit=10%；GEM lot=100 limit=20%；STAR lot=200 limit=20%；BEIJING lot=100 limit=30%；ST lot=100 limit=5%。

### 测试覆盖矩阵（存在性，非复跑）

| 测试文件 | test_fns | 覆盖约束 |
|----------|--------:|----------|
| `tests/test_matching_engine.py` | 14 | 买/卖执行、涨跌停拒、T+1、印花、滑点适配、现金不足 |
| `tests/test_unified_matching.py` | 21 | 同日卖拒、次日卖允、涨跌停、停牌、现金非负、买无印花 |
| `tests/test_limit_checker.py` | 30 | 六板涨跌停比例、IPO 前5日、容差 |
| `tests/test_cost_model.py` | 19 | 佣金/印花/滑点/过户费/RFR/Sharpe |
| `tests/test_limit_down_rollover.py` | — | 跌停结转 |
| `tests/test_market_rules_drift.py` | — | lot/板别漂移 |
| `tests/chaos/test_matching_auditor.py` | — | 混沌审计 |
| `tests/test_unified_engine.py` | **MISSING** | engine 顶层无专测；T+1 覆盖靠 matching 测试 |

**缺测项**：

1. `tests/test_unified_engine.py` 不存在 — `unified_engine` 主路径（`_check_t1`、信号→成交时序、BAD_DEBT 等）**无同名专测**，部分行为被 `test_unified_matching` 间接覆盖。
2. STAR `lot_size=200` 的整手回归未在抽样 ID 中看到专测（`test_market_rules_drift` 或含，未逐条打开）。

### B2 H-A hmap 5 日鞍律 + ha_rotation_sim（P0）

| 项 | 实测 | file:line / ID |
|----|------|----------------|
| `REBALANCE_EVERY = 5` | **在位** | `scripts/canslim/ha_unified_adapter.py:51` |
| 非再平衡日 **carried** 前一日持仓 | **在位**（D+13 修复核心） | `:121` `rebal = (ti - last_rebal) >= REBALANCE_EVERY`；`:123` `carried = hmap.get(dates[ti-1], set())`；`:140` `hmap[dt] = carried` |
| 再平衡日重建 Top30 | 在位 | `:134` `hmap[dt] = {c for c,_ in candidates[:TOP_N]}` |
| 热日外空仓 | 在位 | `:137` `hmap[dt] = set()` |
| **鞍律回归测试 1** | ID 存在 | `tests/scripts/test_ha_engineering.py::test_five_day_cadence_not_daily_rebuild` |
| **鞍律回归测试 2** | ID 存在 | `…::test_holdings_persist_between_rebalances` |
| 引擎算术测试 | 在位 | `…::test_two_slot_exact_nav_with_impact` |
| 测试文件总数 | **16** test_fns | （AGENTS 记 17——**1 差**，或含参数化口径） |
| **已知** | 全量 pytest 中 HA 家族 **1 FAILED** | `test_ha_engineering.py:269` NAV 199945.79 vs 199803（B1 C2c）——**鞍律两测试未在 FAILED 清单**，鞍律本身未红 |

**ha_rotation_sim**（`scripts/canslim/ha_rotation_sim.py` 358 LOC）：

- 自证 30 持久 slot、NAV 复利、生产匹配（万3/千1滑点/万5印花/最低5元/过户/T+1/涨停拒/lot100）@ docstring 16-20
- `engine_params` 键在 JSON：`commission_rate=0.0003, stamp=0.0005, min_commission=5.0` @ 文件 60-63
- 产物 `ha_rotation_sim.json`：`ann_return=0.0764, sharpe=0.6811, max_drawdown=-0.1281, n_slots` 键在（AGENTS +7.43/0.68 **≈**，见 03 备注）
- **DoD**：鞍律关键行 file:line ✓；2 鞍律测试 ID ✓；`ha_rotation_sim` 在位 ✓

### B3 成本口径三套（P1）

| 场景 | 口径 | file:line | 与引擎一致? |
|------|------|-----------|:-----------:|
| 引擎默认 | 佣金万3 + 印花万5卖 + 滑点万5 + 最低5元 + 过户 | `cost_model.py:29-33` | 基准 |
| 研究组合 P8/P15 | **单边 15bp**（佣金+均摊印花+小市值滑点合并） | `run_portfolio_validation.py:15-16,50` `COST_ONE_SIDE=0.0015` | **不一致但已声明** |
| AGENTS/rotation 文字「千一滑点」 | vs `SLIPPAGE_PCT=0.0005`（万5） | `ha_rotation_sim.py:16` 注释；`cost_model.py:33` | **C9**：注释/AGENTS 千一 vs 源码万5；以常量+`engine_params` 为准 |

**裁决**：15bp 研究口径**已在 docstring 预注册声明**（非静默）→ B3 DoD「不一致是否已有文档声明」= **是（15bp）**；「千一滑点」与万5 常量冲突 → **C9**。权威序：源码常量 + 实测 `engine_params` > 文字。

### B4 LPPL 历史终结产物（P1）

| 路径（AGENTS 引用） | exists |
|---------------------|:------:|
| `scripts/output/walk_forward_definitive_report.json` | **False** |
| `scripts/output/` | **False（目录不存在）** |

**裁决 C8**：AGENTS 多处引用的 LPPL/Walk-Forward 终结 JSON **本树不存在**（可能未 commit / 在 /tmp / 已清理）。标注 **「路径失效，未复跑，历史结论沿用 AGENTS:2026-07-23，产物不可核」** → 进 Tier-B/风险表。

### B5 滑点路径（P1）

| 项 | 实测 |
|----|------|
| `DynamicSlippage` 全 src 引用 | **仅 1**：`slippage_model.py:23` 类定义本身 → **零实例化** ✓ |
| 默认生效 | `unified_matching_engine.py:41` `slippage_rate=DEFAULT`；`:43` `slippage_model=None` 时不走 model |
| 常数 | `SLIPPAGE_PCT=0.0005`（`cost_model.py:33`） |

### B6 golden / baseline 捕获（P2，B5 完成）

| 项 | exists | 备注 |
|----|:------:|------|
| `scripts/capture_baseline.py` | ✓ 7455B | **py_compile OK**；CLI `--stock-list`/`--verify-only` |
| `scripts/compare_baseline.py` | ✓ 5742B | **py_compile OK**；`--list`/`--v1/--v2` |
| `tests/benchmark/golden_20.txt` | ✓ 1150B | |
| `tests/benchmark/golden_100.txt` | ✓ 3484B | |
| `tests/benchmark/golden_500.txt` | ✓ 4996B | |
| `baseline_v0.parquet` | ✓ | capture 输出在位 |
| `baseline_v0_100.parquet` / `_intermediate` | ✓ | |

**DoD**：exists + compile 表 ✓。**未实际跑 capture 全量**（Tier-B；B5 只验工具链可编译）。

### B5 单文件 pytest 补跑（WBS 允许）

| 文件 | 结果 |
|------|------|
| `tests/test_p14_cash_fcf_dy.py` | **EXIT=0** |
| `tests/test_bp_ha_portfolio.py` | **6 passed, EXIT=0** |
| `tests/test_fwd5_regression.py` | **4 passed, EXIT=0**（B4） |

（全量 pytest 仍为 B1 的 16 FAILED 快照——单文件绿≠全量绿，见 C2。）

## 与历史对账

| AGENTS / live_map | 实测 | 裁决 |
|-------------------|------|------|
| 七条 A 股防御线仍在 | 上表 9 约束全在位默认开 | **✓ 维持** |
| P1-01 SZ 过户费豁免 | matching 有 `_has_transfer_fee` 线索 | 未在本批展开（成本细节随 C9） |
| DynamicSlippage dead | 类在、注释自证、默认 None、引用=1 | **✓ 维持** |
| D+13 hmap 鞍律修复 | carried@123,140 + 2 测试 ID | **✓ 维持**（测试文件 16 vs AGENTS 17 记差） |
| ha_rotation_sim 入仓 | 358 LOC + JSON 键全 | **✓** |
| walk_forward_definitive_report.json | **文件不存在** | **C8 引用失效** |
| 成本三套 | 15bp / 万5滑 / 千1文字 已各自声明 | **M 披露 + C9** |
| 全量回测数字 P8/P10/P13 | — | **Tier-B 不复跑**（03 已核 JSON 键） |

## 风险分级

| 级 | 项 |
|----|-----|
| **H** | C8：LPPL 终结报告路径失效，关键负结论不可从产物复核 |
| **M** | C9：千一滑点文字 vs 万5 常量 |
| M | `test_unified_engine.py` 缺失；成本三套跨报告可比性 |
| L | STAR lot=200 专测未逐条确认 |

## 建议动作

1. 补 `tests/test_unified_engine.py` — **需批准的新增测试**。
2. 归档或重建 `walk_forward_definitive_report.json` 或改 AGENTS 引用为「已丢失，结论沿用」— DoD：路径 exists 或文档改口（批准后）。
3. 统一滑点表述：cost_model 万5 为准 — DoD：rg「千一滑点」仅史档。
4. ~~可选 pytest 鞍律~~ **B5 已补**：p14/bp/fwd5 单文件 EXIT=0；`test_ha_engineering` 仍见全量 FAILED 中 1 条（C2c），未单独复跑。

## 本批变更

B1=B1约束 / B2鞍律 / B3成本等 / B5=B6+单测补跑；仅本 FULL_AUDIT 文档；**无源码变更**；未复跑全量回测。
