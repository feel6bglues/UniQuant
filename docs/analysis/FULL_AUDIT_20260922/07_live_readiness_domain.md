# 07 实盘就绪度域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook | SHA `ddd678a` | 批 B3=L1,L2；批 B4=L3-L6（完成）

## 结论（3 句内）

`daily_signal_ha` 与 `reconcile_ha` **import 成功、`--help` exit 0、py_compile 通过**——L1 入口可用。容量/ADV 地板**产物+代码双在位**且与 AGENTS P10 键级一致；主版本 `AMOUNT_FLOOR=None`。**B4**：live 差距文档抽 **5/5 与代码一致**（含深市过户 bug 仍在）；**无明文密钥**、secret_manager 未接线；kill_switch/PositionSizer **在信号路径**、可观测组件**未入容器键**。

## 证据（file:line @ ddd678a / 本会话命令）

### L1 入口 import + CLI（P0）

| 检查 | 结果 |
|------|------|
| `import daily_signal_ha` | **OK**（`scripts/canslim/daily_signal_ha.py`）；`main`/`compute_state`/`build_target` 在 |
| `import reconcile_ha` | **OK**；`main`/`diff_signal_files`/`build_reconciliation` 在 |
| `daily_signal_ha.py --help` | **exit 0**；usage: `--as-of`；description「H-A 每日信号」 |
| `reconcile_ha.py --help` | **exit 0**；`--signal/--prev-signal/--positions/--prices/--drift-tol-pp`；「H-A 实盘对账」 |
| `py_compile` 四脚本+five_gate | **exit 0** |
| 真实下单 | **未执行**（只读纪律；无 broker 接线调用） |

**关键常量**：`daily_signal_ha.py:25` `AMOUNT_FLOOR = None`（主版本）；`:7` 注释「None 主版本 / 2e7 回撤敏感变体」。

### L2 容量 / ADV 地板（P0）

| AGENTS 断言 | 产物实测 | 一致? | 出处 |
|-------------|----------|:-----:|------|
| 全市场 4943 只 | `_meta.n_universe=4943` | ✓ | `capacity_validation.json` |
| 年化 +9.98%/夏普 0.93/回撤 −22.2% | 0.0998 / 0.933 / −0.2215 | ✓ | `.strategies.FULL_no_floor` |
| F1 FAIL | `F1_fullnet_positive_and_sharpe_ge1=False` | ✓ | `.verdict` |
| 地板块夏普 0.78 回撤 −12.8% | 0.776 / −0.128 | ✓ | `.strategies.FULL_floor2000w` |
| F2 FAIL | `F2_floor_not_harmful=False` | ✓ | `.verdict` |
| ADV 合计中位 28.5 亿、10% 参与、≈2850 万 | 28.5 / 0.1 /（×0.1→28.5 亿侧…）`rough_capacity_per_slot_yi=0.095` | ✓（9500 万/slot 级；AGENTS 2850 万=总量×10% 口径，JSON note 已写公式） | `.capacity` |
| SAMPLE500 +13.18%/1.08 | 0.1318 / 1.078 | ✓ | `.strategies.SAMPLE500_no_floor` |

**ADV≥2000 万地板代码位**：

| 位置 | file:line | 语义 |
|------|-----------|------|
| adapter `amount_floor` 参数 | `ha_unified_adapter.py:91,94` | `None=不限; 2e7 = P10 F2 地板` |
| 45 日中位成交额过滤 | `:108-115` | `amt_med >= amount_floor` |
| 默认调用 | `:230` `build_holdings_map(panel, hot)` **未传 floor** → 默认 None | 主路径无地板 |
| daily_signal 主版本 | `daily_signal_ha.py:25` `AMOUNT_FLOOR=None`；`:84-85` 过滤 | 主版本无地板 ✓ |

**判定**：地板**可配置且有产物**；**生产主默认无地板**——与 AGENTS「主形态=小盘、地板为变体」一致 ✓。

### L3 live vs backtest 抽样 5 条（P1，B4 完成）

源：`docs/reference/live_vs_backtest_differences.md`（420 行；差异汇总表 §5.1 @358-374，共 15 条 1.1–4.3）。

| # | 文档断言 | 代码现状 @ ddd678a | 一致? |
|---|----------|-------------------|:-----:|
| 1.1 | T 日信号 → T+1 **开盘价直接成交**，跳过集合竞价（doc 指 `unified_engine.py:180`） | `unified_engine.py:309` `exec_price_raw = opens[idx]`（行号漂移，语义同） | ✓ |
| 1.3 | **部分成交未建模**（全或无），中度 | matching/engine 无 partial fill 分支（全量或拒） | ✓ |
| 1.4 | **涨跌停封单量未建模**（二元拒绝） | `unified_matching_engine.py:199` `limit_rejected=is_limit_up` 二元 | ✓ |
| 2.3 | 深市过户费被错误免收（文档自判 bug，建议修 `_has_transfer_fee`） | matching 仍 `transfer_fees = np.where(sh_mask, ...)` **仅沪市**@`:207` 等 | ✓（bug 仍在，与文档一致） |
| 2.4 | 滑点模型简化；DynamicSlippage 不在默认 | `DynamicSlippage` 类在 `slippage_model.py:23`，默认 `slippage_model=None` 常数万5 | ✓ |

**DoD**：5 条「文档断言 \| 代码现状 \| 一致?」表 **5/5 一致**（文档本身即差距清单，非错误文档）；2.3 深市过户 bug **确认未修** → 建议项保留（不改码）。

### L4 密钥 / secret_manager（P1，B4 完成）

| 检查 | 结果 |
|------|------|
| 明文密钥模式 rg（api_key/password/token/secret=…） | **0 高危命中** |
| `config/connect.cfg` | **不存在** |
| `config/` 内容 | 仅 `config.yaml`, `factors.yaml`, `optimal_params.yaml`, `trading.yaml` |
| `shared/secret_manager.py` | **存在**；导出于 `shared/__init__.py:32` |
| 生产消费者 | **仅 export，无业务调用点** → 实现在、**未接线** |

**结论**：无明文密钥风险；secret_manager 为**未启用的预留组件**（与 L5 容器未接线同族）。

### L5 可观测性接线（P1，B4 完成）

| 组件 | 实现 | 接线 file:line | service_container 接线? |
|------|------|----------------|:-----------------------:|
| `shared/prometheus_metrics.py` | 在 | （容器无引用） | **否** |
| `shared/observability.py` | 在 | research_pipeline / analysis_service_v2 有引用 | **否**（不进容器键） |
| `shared/kill_switch.py` | 在 | **health_service:8,103-115**；**manager_logic:8,531-541**；**arbitrator:21,112-113,292-297** | **否**（经 arbitrator/health 旁路生效，非容器注册） |

**裁决**：三组件**实现在位**；**容器本身不引用** prometheus/observability/kill_switch → 「容器接线」字面 = **否**；但 kill_switch 已在**信号仲裁与健康管理**路径生效（见 L6）。

### L6 kill_switch / sizer 信号路径（P1，B4 完成）

| 组件 | 调用链 | 在路径? |
|------|--------|:------:|
| **PositionSizer** | `service_container.py:21,166-171` 注册 → `arbitrator.py:19,271,357` 使用 | **是** |
| **kill_switch** | `arbitrator.py:21` import；`:112-113` / `:292-297` 信号路径检查 | **是** |

**结论**：两者均在**信号→仓位/仲裁**路径上，非死代码；容器未把它们当独立 service 键导出不影响生产路径。

## 与历史对账

| 历史 | 状态 |
|------|------|
| L1 两入口可导入/CLI | **✓ 本会话实测** |
| P10 capacity JSON | **✓ 键级全对** |
| ADV≥2000 万在代码 | **✓ 参数化在位，默认关** |
| 2850 万容量叙事 | **✓ 公式在 JSON note** |
| live 差距 15 条文档 | **✓ 抽 5/5 与代码一致**（含 2.3 深市过户 bug 仍在） |
| 无明文密钥 | **✓ 0 命中** |
| secret_manager 接线 | **未接线**（仅 export） |
| 可观测三件套 | 实现在；**容器未接**；kill_switch/sizer **在信号路径** |

## 风险分级

| 级 | 项 |
|----|-----|
| M | 主版本无地板 + C5 指数物理残留：全市场 glob 路径若绕过过滤会污染合格池 |
| M | 深市过户费 2.3 bug 未修（成本低估极轻微，文档已披露） |
| L | secret_manager/prometheus 未接线（无密钥风险，可观测缺口） |
| L | `--help` 未做 dry-run 真数据（避免 Tier-B 全量）；B5 可选最小 `--as-of` 干跑 |

## 建议动作

1. B5：可选 `daily_signal_ha.py --as-of <近期>` 最小干跑（若耗时/数据 OK）— DoD：exit 0 且 JSON 目标数>0。
2. 对账脚本接线进 cron/手工 runbook 文档 — DoD：docs/index 实盘 checklist 一行（批准后）。
3. 修复 2.3 深市过户费 `_has_transfer_fee` — **需拟修改清单**（本审计只记录）。
4. 决定 secret_manager/prometheus 是否入容器 — DoD：ADR 或明确 WONTFIX（B5）。

## 本批变更

B3=L1,L2；B4=L3-L6；仅 FULL_AUDIT 文档；**无源码/config 变更**；**无真实下单**。
