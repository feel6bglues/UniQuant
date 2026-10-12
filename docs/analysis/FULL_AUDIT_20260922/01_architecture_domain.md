# 01 架构分层域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook 阶段产物 | SHA `ddd678a` | 批 B1=A1,A2；批 B4=A3,A4（完成）

## 结论（3 句内）

八层声明与现实**基本成立**：8/8 层可 import，ServiceContainer DAG 注册 12+ 服务键，跨层 import 以 `*->shared` 为主符合分层。但 **归档死码叙事全面失效**（price_collar / analysis_service_legacy 文件与 archive 目录均不存在），FSM 引擎确认不在 analysis_service_v2 主路径。近 5 个 commit（qtr-os/blueprint）引入 `src/uniquant/research/` 新包并改 signal/backtest/factors，**AGENTS 未完整收录**。

## 证据（file:line @ ddd678a）

### A1 八层 + DAG

| 层 | files | LOC | import |
|----|------:|----:|--------|
| shared | 48 | 7,614 | OK |
| data | 68 | 15,500 | OK |
| brain | 56 | 18,110 | OK |
| signal | 8 | 2,802 | OK |
| hands | 33 | 6,169 | OK |
| risk | 6 | 1,640 | OK |
| services | 31 | 8,305 | OK |
| ui | 8 | 3,400 | OK |

跨层 import（AST 计数，源层→目标层）：hands→shared 28, brain→shared 18, data→shared 10, ui→shared 4, hands→data 3, hands→brain 3, hands→signal 2, 其余≤1。**无 data→brain 等逆流**（与「零循环依赖 DAG」宣称方向一致；未做全闭包证明）。

`ServiceContainer.initialize` 注册键（`service_container.py:105-184`）：storage, calendar, cache, data_service, time_provider, engine_factory, market_cache, analysis_service, backtest_engine, signal_collector, arbitrator, research_pipeline。

### A2 死码/归档

| 项 | 宣称 (live_map) | 实测 |
|----|-----------------|------|
| `shared/archive/price_collar.py` | ARCHIVED 32 LOC | **MISSING**；全仓无 `price_collar.py`；仅 `market_rules.py` 字段名 `price_collar_pct` |
| `services/archive/analysis_service_legacy.py` | ARCHIVED 1,649 LOC | **MISSING**；rg 零引用 |
| `signal/quality.py` | DEAD DEPRECATED 294 | **EXISTS 297 LOC**；生产零引用，测试有引用 |
| `DynamicSlippage` | DEAD default path | **类在** `slippage_model.py:23`；生产零实例化，测试 `test_matching_engine.py:176` |
| `fsm_analysis_engine.py` | Semi-dead | **EXISTS 247**；`engine_factory.py:55` 懒加载；`analysis_service_v2` **无** FsmAnalysisEngine |
| `data_pipeline_service.py` | Active | `data_fetcher.py:126` 调用 `process` ✓ |

### A3 编排（P1，B4 完成）

| 项 | 实测 | file:line @ ddd678a |
|----|------|---------------------|
| ServiceContainer 定义/单例 | `class ServiceContainer` + `instance()` | `service_container.py:32`（initialize 注册 12 键 :105-184） |
| 外部 `instance()` 消费者 | **仅 2**：dashboard、di_container 薄包装 | `ui/dashboard.py:631-634`；`shared/di_container.py:31` |
| analysis_service_v2 → FSM | **0 命中**（rg `fsm\|FSM` 于 v2） | `analysis_service_v2.py` 无 FSM 引用 |
| FSM 仅经 factory 懒加载 | `def fsm` → `_lazy_init("fsm", "..analysis.fsm_analysis_engine", ...)` | `engine_factory.py:54-55` |
| DecisionBrain 路径 | factory 内 `from ...brain.fsm import DecisionBrain` | `engine_factory.py:87` |
| v2 被谁引用 | health_service / manager_logic / research_pipeline / service_container | `:12` / `:7` / `:59` / `:123`（近似行） |

**裁决**：ServiceContainer 是**文档化唯一编排入口**（dashboard 经 `instance()`；di_container 为兼容包装）。FSM **不在 analysis_service_v2 主路径**——「半死/可选引擎」叙事与源码**一致**（B1 预采证实，B4 定稿）。

### A4 未入档提交（P1，B4 完成；AGENTS 滞后）

前提：`git log ddd678a..HEAD` = **空** → 当前 HEAD 即基线 `ddd678a`（无「基线后新提交」）；「5 commit」= 基线及其前 4 个。

| commit | 主题 | 触及 src/ 关键路径? | 层（摘） | AGENTS 收录? |
|--------|------|:-------------------:|----------|:------------:|
| **ddd678a** | CNMM-QAR blueprint + 执行加固 | **是** | factors/financial_bridge, data/{cleaner,validator}, **hands/unified_engine**, tests | 部分（blueprint 叙述） |
| **0114959** | QTR-OS Phase3 | **是** | factors/composer, **brain/wyckoff/pnf**, **signal/adapters**, tests | **否** |
| **e1877ea** | QTR-OS Phase2 | 研究侧 | **research/ledger**, scripts/five_gate | **否** |
| **4b212f9** | QTR-OS Phase0/1 | **是** | **NEW research/{gates,ledger}** (alpha_tier 523, DoF 233), data/corporate_action, **hands/matching+overfitting**, **signal/adapters**, research_pipeline | **否** |
| **68bf789** | 全栈审计 docs 归档 | 否（docs only） | docs/analysis | 是（审计段） |

**信号/回测路径被改**：4b212f9、0114959、ddd678a → **3/5**。**新顶层包** `src/uniquant/research/{gates,ledger}/` 八层表未单列 → 归属待 B5/A5 裁决。

**裁决**：AGENTS **未完整收录** QTR-OS 四提交（尤其 adapters/pnf/matching 触点）→ 风险#9 维持；收尾拟修改清单（批准后）增补摘要表。

## 与历史对账

- AGENTS/index 层文件数（44/65/54…）vs 实测（48/68/56…）：**漂移**（新增 py 或计数口径含/不含 archive）。
- live_map 死码表路径全部过期或文件已删 → **权威序：源码 > live_map**。
- 「零循环依赖」：跨层 import 未见反向 data←brain 等，**弱支持**；未跑 import-linter。

## 风险分级

| 级 | 项 |
|----|-----|
| H | 控制文档死码/归档路径全面失效，误导后续审计 |
| M | research/ 新包未入八层职责表 |
| L | DAG 未做形式化无环证明 |

## 建议动作

1. 更新 live_map 死码表为「已删除 / 在树半死」二分 — DoD：每项 exists+rg 计数表。
2. AGENTS 增补 ddd678a..4b212f9 五提交摘要 — DoD：A4 表入 AGENTS（批准后）。
3. 明确 `research/` 归属层 — DoD：docs/index 运行时模块表一行。

## 本批变更

仅本 FULL_AUDIT 文档；**无源码变更**。
