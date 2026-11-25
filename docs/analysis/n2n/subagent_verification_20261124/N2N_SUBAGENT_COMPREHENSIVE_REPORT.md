# UniQuant 子代理驱动 N2N 独立复核 — 综合分析报告

> **日期**：2026-11-24 · **代码基线**：`b1d2415`（当前 HEAD）
> **执行**：9 个独立子代理并行/串行，逐模块 N2N（node-to-node）代码级审查 + 独立交叉复核
> **复核对象**：既有 Claude 单代理报告集 `docs/analysis/n2n/0*.md`（基线 `434aab1`，第 25 轮）
> **报告目录**：`docs/analysis/n2n/subagent_verification_20261124/`

---

## 0. 执行摘要

### 0.1 一句话结论

> **多子代理独立复核推翻了既有报告"0 CRITICAL / 0 HIGH / 全模块优秀"的结论**：
> 在相同代码基线（`b1d2415`，较既有报告基线 `434aab1` 仅多文档补丁）下，独立复核
> 共发现 **3 CRITICAL / 26 HIGH / 42 MEDIUM / 38 LOW（原始 109 项，跨模块去重后约 100 项）**，
> 且既有报告存在 **至少 5 处事实性缺陷**（虚构代码证据、方向颠倒、计数错误、自相矛盾、
> "第 25 轮已修复"不成立）。

### 0.2 规模与健康度总表

| # | 子代理 | 模块 | 规模 | 健康度 | C | H | M | L | 报告 |
|---|--------|------|------|:---:|:-:|:-:|:-:|:-:|------|
| S1 | 数据流转 | `data/` | 40 文件 / 7,808 行 | **B-** | 0 | 3 | 4 | 3 | `01_data_flow.md` |
| S2 | 分析引擎 | `brain/` | 73 文件 / 20,917 行 | **B-** | 1 | 2 | 5 | 6 | `02_analysis_engines.md` |
| S3 | 信号生成 | `signal/` | 3 文件 / 1,194 行 | **B+** | 0 | 1 | 6 | 3 | `03_signal_generation.md` |
| S4 | 回测撮合 | `hands/backtest/` | ~20 文件 | **B** | 0 | 3 | 4 | 3 | `04_backtest_matching.md` |
| S5 | 风控合规 | `risk/` + `kill_switch.py` | 5+1 文件 | **B** | 0 | 4 | 2 | 4 | `05_risk_compliance.md` |
| S6 | 服务编排 | `services/` | 28 文件 / 8,554 行 | **B** | 0 | 3 | 8 | 7 | `06_service_orchestration.md` |
| S7 | 研究控制平面 | `research/` | 12 文件 / 1,885 行 | **C+** | 1 | 2 | 3 | 3 | `07_research_control_plane.md` |
| S8 | UI 展示 | `ui/` | 8 文件 / 3,400 行 | **D** | 1 | 7 | 6 | 5 | `08_ui_presentation.md` |
| S9 | 跨模块集成 | 全链路 + `interfaces.py` | 端到端 | **B** | 0 | 1 | 4 | 4 | `09_cross_module_integration.md` |
| **Σ** | | | 230 文件 / 56,992 行 | | **3** | **26** | **42** | **38** | |

> 原始合计 109 项。跨模块存在约 8 组重复家庭（LPPL SELL 遗留、ENGINE_PRIORITY、FeatureFlags
> 双模型、13/12 服务、UI 简化信号、QAR 未接线、质量门缺数据放行、LPPL 遥测双路径），
> **去重后独立问题约 100 项**。以下逐模块计数为各子代理独立原始计数（未去重），跨模块重复在
> §4 矩阵中以同一 ID 家庭标注。

### 0.3 与既有报告对比（核心矛盾）

| 维度 | 既有 Claude 报告 | 本多子代理独立复核 | 结论 |
|------|------------------|---------------------|------|
| 问题总数 | 18（0 C / 0 H / 5 M / 13 L） | 109 原始（3 C / 26 H / 42 M / 38 L） | **数量级反转** |
| 整体健康度 | "优秀" | B-~B+ 为主，S7=C+，**S8=D** | **大幅下调** |
| CRITICAL | 0 | **3** | 既有报告漏判全部 3 项 |
| HIGH | 0 | **26** | 既有报告漏判全部 26 项 |
| 事实性缺陷 | — | **≥5 处**（虚构证据/方向颠倒/计数/矛盾/修复谎称） | 既有报告可信度受损 |

### 0.4 独立性声明

9 个子代理均被要求在**未阅读既有报告前独立取证**，完成 N2N 五问、路径追踪、问题分级后，
才进入第 ⑤ 步交叉复核对照既有报告。全部 `file:line` 证据直接取自当前工作树 `b1d2415`，
关键行为结论（H1 Sell-Priority 违反、ST 快路径放行、坏账账目断裂、滑点分歧、KillSwitch
Fail-Open、gross 公式、pre_close 死代码、渲染崩溃、BH-FDR 不累积）均经本机 Python 实测复现。
**本报告未修改任何源码（Rule 8 合规），纯审查产出。**

---

## 1. 方法：工作流与九子代理分解

按 `docs/analysis/n2n/SUBAGENT_N2N_VERIFICATION_WORKFLOW_20261124.md` 执行。每个子代理对
其模块逐节点回答 N2N 五问（**Name 定义 / Name 映射 / Name 传播 / Name 变异 / Name 治理**），
追踪 ≥3 条端到端路径（含 ≥1 条异常路径），发现按 CRITICAL/HIGH/MEDIUM/LOW 分级，并对既有
Claude 报告逐条标注「一致 / 分歧 / 已修复 / 仍遗留」。

**跨模块重复家庭（约 8 组，已在各子代理报告中独立出现）**：
LPPL SELL 优先级遗留（S4/S9）、ENGINE_PRIORITY 方向与 Rule 3 死代码（S3/S9）、FeatureFlags
双模型/双默认值（S3/S9）、13/12 服务计数（S6/S9）、UI 简化信号计算（S8/S9）、QARAdapter
未接线（S3/S9）、质量门缺数据=满分（S3/S9）、LPPL 遥测双路径（S2/S9）。

---

## 2. 核心 CRITICAL / HIGH 发现（N2N 视角，按影响排序）

> 以下为跨模块影响最大、N2N 链路中最该优先处置的发现。每条给出模块、问题、证据位置、N2N 后果。

### CRITICAL（3 项）

| ID | 模块 | 问题 | 证据 | N2N 后果 |
|----|------|------|------|----------|
| **C1-a** | 分析引擎 (S2) | `pre_close` 在 N2N 生产路径**从不写入** `MarketSignalContext`，`interfaces.py:110` 恒读默认 `0.0`，services/brain 层无任何写入 | `interfaces.py:110`；`fsm.py:338/392/578` 三处 `price>0 and pre_close>0` 守卫恒假 | **实盘 FSM 熔断态与涨跌停保护全部失效**；回测路径 `unified_models.py:186` 会 `close.shift(1)` 生成 `pre_close` → **回测-实盘分裂** |
| **C1-b** | 研究控制平面 (S7) | 四阶晋升引擎 `AlphaTierEngine` **无任何生产调用方**，仅测试与沙盒自引用触及 | `services/`、`scripts/` 无一调用 `evaluate_candidate`/`promote_candidate` | **最强防过拟合门禁是测试专用组件**，"防线存在但未启用"的虚假安全感 |
| **C1-c** | UI 展示 (S8) | `validate_symbol`（`dashboard.py:281`）要求代码长度 10，合法 A 股代码（如 600519.SH）为 **9 字符** → 拒绝一切合法输入 | `dashboard.py:281` | **深度几何分析 CZSC 路径对默认代码即失效**，UI 主功能死区 |

### HIGH（重点 14 项，按模块）

| ID | 模块 | 问题 | 证据 | N2N 后果 |
|----|------|------|------|----------|
| H1-sig | 信号 (S3) | 主流水线走 `arbitrate_candidates()`，其 Priority 1 `DecisionOutput` BUY（`:328-341`）在 Priority 2 SELL-over-BUY（`:344`）之前短路 → 任何引擎候选 SELL 被无条件覆盖，**Sell-Priority 不变量在真实路径被违反**（实测复现：decision=BUY+SELL(0.9)→BUY） | `arbitrator.py:328-344`；`research_pipeline.py:373` | 避险 SELL 被覆盖，风控有效性被击穿 |
| H1-risk | 风控 (S5) | `compliance_engine.py:234` Gross Leverage 公式错误：`gross=(L+S+cash)/aum` 代回得 `1+short_weight`，**完全不含 long**；实测 long=150%/short=50% 真实 gross=200% 却漏报（fail-open）；"175% 上限"实际仅约束空头≤76% | `compliance_engine.py:234` | **多头侧杠杆无约束**，防线失效 |
| H2-risk | 风控 (S5) | 合规引擎**未接入回测/实盘执行链路**——`audit()` 仅 `manifest_generator.py:297`（清单导出）调用，7 大防线对实际持仓不生效 | `manifest_generator.py:297`（唯一调用点） | 全部硬风控防线形同虚设 |
| H4-risk | 风控 (S5) | KillSwitch 状态存储**读失败**时 `except` 后 `_killed=False`（`kill_switch.py:55-56`）→ **Fail-Open**，与"T9a Fail-Closed"声称相悖；实测损坏 JSON 重启后 `is_killed=False` | `kill_switch.py:55-56` | 熔断态重启后自动放行开仓，与 Fail-Closed 纪律矛盾 |
| H2-brain | 分析引擎 (S2) | 工厂创建的 `DecisionBrain()` 无 `evt_risk`/`sizer`（`engine_factory.py:88`）→ `fsm.py:414-439 _execute_buy` 恒用 `{"建议仓位":100}`+scaler 1.0 | `engine_factory.py:88`；`fsm.py:414-439` | **实盘仓位恒 100 股、EVT 风控被绕过** |
| H1-brain | 分析引擎 (S2) | LPPL `diagnostic_only=True` 只门控采集器（`adapters.py:116/545`），但 `DecisionBrain` 仍按 `ctx.risk=="Danger"` 走 `fsm.py:302 FORCE_EXIT`/`:327 LPPL_DANGER` → 仲裁转 SELL | `adapters.py:116/545`；`fsm.py:302/327` | **"LPPL 降为遥测"只完成一半，双路径互相矛盾** |
| H2-eb | 服务编排 (S6) | 6 生命周期事件 + `EngineCompleted` 在默认容器装配下**完全不生效**——容器从不传 `event_bus`（`service_container.py:126-137,188-212`），全仓库**零 `.subscribe(`**；`event_bus` 特性开关是死配置 | `service_container.py:126-137,188-212` | 可观测性/事件驱动骨架是死代码 |
| H3-eb | 服务编排 (S6) | `run_batch` 的 `seed` 形参是死参数（`research_pipeline.py:462,514`）——接受但不传播，破坏批次可复现 | `research_pipeline.py:462,514` | 违背第 24 轮"seed 可复现"纪律 |
| H1-eb | 服务编排 (S6) | `ServiceContainer.get()` 懒加载**无锁**（`service_container.py:60-63`）——全部服务唯一入口，并发首取可重复/覆盖实例 | `service_container.py:60-63` | 通用正确性风险（当前单入口未触发，latent） |
| H2-bt | 回测 (S4) | 坏账 0 元出清账目不一致：实测记录 pnl **-1000.51** vs 权益单日 **-900.00**，现金前后不变、仓位市值凭空抹除 | `unified_engine.py`（30 日清退路径） | 绩效指标失真 |
| H1-bt | 回测 (S4) | 滑点双模型分歧：标量 `0.001·√ratio` vs 向量化分段模型，eta≤0.1 时差 3.2 倍、eta=0.5 时 7.1 倍 | `slippage_model.py` vs `unified_matching_engine.py` | 回测成本不可比 |
| H3-bt | 回测 (S4) | 向量化快路径**跳过 ST ±5% 检测**（实测 price/pre=1.05 快路径放行） | `unified_matching_engine.py:136-180` | ST 股回测失真 |
| H1-ui | UI (S8) | `analyze_macro_health` 默认 `mock=True`（`manager_logic.py:121`），`dashboard.py:340` 未关闭；数据缺失时 `macro_analysis_engine.py:78-85` 用 **np.random 伪造收益**并回落 NORMAL，而 `dashboard.py:336` 宣称"基于真实市场数据计算" | `manager_logic.py:121`；`macro_analysis_engine.py:78-85`；`dashboard.py:336/340` | **违反 Rule 4（数据伪造+虚假声明）** |
| F8 | 跨模块 (S9) | `FeatureFlags` 双模型冲突：`config_models.py:10-12` vs `config_schema.py:83-88` 默认值（signal_arbitration False/True、factor_gate off/block）、字段集含/不含 typed_contracts、engine_migration | `config_models.py:10-12`；`config_schema.py:83-88` | 运行时与 schema 行为不一致，配置漂移 |

> 其余 HIGH（S4 另 0 项、S5 另 H3、S7 另 H1/H2、S8 另 H2-H7、S9 另 0 项）见各模块报告 §④。

### S7 关键 HIGH（研究控制平面，防过拟合防线失效）

- **H1**：三生产沙盒（Wyckoff/CANSLIM/LPPL）从不提供 `residual_ic_series`/`pbo_value`/`gate_inputs`
  → `evaluate_through_gates(df)` **恒返回 `TIER_UNRATED`**（实证确认）。
- **H2**：Class A 的 BH-FDR 校正在门禁路径**不累积**——每次沙盒调用新建内存账本，单试验族
  `p_adj_bh_fdr == p_raw`（实证确认），**多重测试惩罚被绕过**；`LedgerStore` 仅接桥接路径，未接门禁引擎。

---

## 3. 既有 Claude 报告的事实性缺陷（≥5 处，证据级）

| # | 缺陷 | 证据 | 说明 |
|---|------|------|------|
| **D1** | **虚构代码证据**（LPPL SELL 优先级） | 既有 `09_cross_module_integration.md` §M1 引 `unified_engine.py:337-348` 的 `if engine=="LPPL" and direction=="SELL": priority=0`；独立核实该文件**无 `priority` 变量**，真实为 `:339-348` 的 `sig.action=="SELL" and "lppl" in sig.reason.lower()` 特判建 SELL 挂单 | 方向对但位置/代码要重述 |
| **D2** | **ENGINE_PRIORITY 方向颠倒** | 既有报告表 `LPPL:1(最高)`；独立核实 `arbitrator.py:32-42` 为 `lppl:99(最低)`, `fsm:1(最高)`, `czsc:2`, `qar:3`, `wyckoff:4`, `regime:5`, `ntf:6`, `alpha_score:7`, `ma_status:8`；键为小写 | 与实现相反 |
| **D3** | **"第 25 轮已修复"不成立**（FreshnessValidator） | 既有 `01_data_flow_n2n.md` §5.2/§9 称已修复；`git show --stat 434aab1` 无 `freshness_validator.py`/`storage_manager.py`；`b1d2415` docs-only | 修复谎称/表述误导 |
| **D4** | **"原子写 ✅"未审计全部写入路径** | 既有 §4.4 只审 `StorageManager.write_parquet`；5 处直写 `to_parquet` 绕过 tmp+replace（含复权基线 `tdx_parser.py:432`） | 结论超出证据范围 |
| **D5** | **"13 服务"计数不实** | 既有 6 处引 13 服务；独立核实 `service_container.py` 注册 **12** 功能服务；`factor_gate` 是配置副作用非服务；无 `PortfolioService`/`RiskEngine` | 计数错误（S6/S9 双重独立确认） |
| **D6** | **自相矛盾**（信号 §4.2 vs §4.3；数据列序 §1.1 vs §7.4；事件顺序） | 既有信号报告 §4.2"SELL 始终优先" vs §4.3"DecisionOutput BUY 优先"矛盾；数据列序两侧完全相同；事件顺序 EngineCompleted 先于 DataLoaded 有误 | 报告内部不一致 |

---

## 4. 独立复核矩阵（逐模块，vs 既有 Claude 报告）

> 汇总各子代理 §⑤ 交叉复核矩阵。**一致**=双方结论吻合；**分歧**=独立复核得出不同判断（附双方证据）；
> **已修复**=基线后修复；**仍遗留**=仍可复现。

| 模块 | 既有自评 | 独立复核判定 | 一致 | 分歧 | 已修复 | 仍遗留 |
|------|----------|--------------|:---:|:---:|:---:|:---:|
| 数据流转 (S1) | 0 C/0 H；"已修复/原子写✅" | **B-**；3 H/4 M/3 L | 3 项（9 列/C3/R2 护栏） | 4 项（原子写、已修复谎称、validator 死调用、调整不一致） | 0 | 10 |
| 分析引擎 (S2) | 0 C/0 H；"全优秀" | **B-**；1 C/2 H/5 M/6 L | 4 机制描述 + 3 LOW | 2 项（漏判 C1/H1/H2；夸大覆盖"只审 4/10 却评全优秀"） | 0 | 14 |
| 信号生成 (S3) | 0 C/0 H；"Sell-Priority✅" | **B+**；1 H/6 M/3 L | 12 项 | 6 项（路径不精确、质量门误标正面、§4.2/4.3 自相矛盾、漏判 H1、健康度高估） | 0 | 10 |
| 回测撮合 (S4) | 0 C/0 H（附 2 第三方评审） | **B**；3 H/4 M/3 L | 七大防线 + 规则 + 快慢路径 | 5 项（自评过松；撤回 M3/M1；L2 上调；H1/H2 新增） | 0 | 10 |
| 风控合规 (S5) | 0 C；"防线 6 个" | **B**；4 H/2 M/4 L | 6 项（参数可配置/百分位法/T9a/T+1/几何止损/整百股） | 5 项（"无 CRITICAL"不成立；M2 升 HIGH；P1 优先级错；H1/H4 双方未捕） | 0 | 10 |
| 服务编排 (S6) | 13 服务/6 事件"优秀" | **B**；3 H/8 M/7 L | 机制描述高度准确（bind_orchestrator/TOCTOU/双检/原子 checkpoint） | 4 项（13 服务不实；6 事件严重高估；事件顺序错；get() 无锁升 HIGH） | 0 | 18 |
| 研究控制平面 (S7) | "优秀"；L2 硬编码 LOW | **C+**；1 C/2 H/3 M/3 L | 5 条（参数数值/Newey-West/BH-FDR 实现/诚实门禁/Class B→TIER_A） | 5 条（参数来源高估；依赖链高估；范围外引用；硬编码低估；健康度高估） | 0 | 9 |
| UI 展示 (S8) | 0 C/0 H | **D**；1 C/7 H/6 M/5 L | 架构层结论（门面/组件化/Kill Switch/超时/状态隔离）均一致 | 2 项（"无 CRITICAL/HIGH"证伪；L1 简化信号升 MEDIUM） | 0 | 19 |
| 跨模块集成 (S9) | M1 遗留；ENGINE_PRIORITY 表 | **B**；1 H/4 M/4 L | 3 项 PASS（9 列契约/9 适配器/KillSwitch Fail-Closed） | 3 项（M1 虚构证据；ENGINE_PRIORITY 颠倒；服务清单/入口不实） | 0 | 9 |

**复核汇总**：一致约 **45 项**（机制/事实层面） · 分歧约 **33 项**（定级、计数、路径、覆盖、证据）
· 已修复 **0 项**（基线 `434aab1→b1d2415` 对 `src/` 为空 diff，全部为架构性遗留） · 仍遗留 **109 原始项**。

### 关键结论

1. **既有报告的"机制描述"高度可信**：七大防线、A 股规则、9 列契约、C3 红线、Newey-West、
   BH-FDR 实现、诚实门禁、bind_orchestrator、MarketLevelCache TOCTOU、KillSwitch Fail-Closed
   等均经独立复核**一致确认**。报告的**事实层**（代码级机制）质量高。
2. **既有报告的"结论层"系统性高估**：其"0 CRITICAL/0 HIGH/全模块优秀"与独立复核结果严重不符，
   9 个模块无一维持"优秀"。根本原因：既有报告**主要审引擎本体/机制**，未核查**生产接线、活路径
   语义、真实输入供给、渲染正确性**——这些恰是 N2N"端到端"最该覆盖的部分。
3. **跨模块重复家庭说明问题集中于少数架构节点**：仲裁活路径（S3/S9）、FeatureFlags 双模型
   （S3/S9）、合规引擎接线（S5）、事件总线（S6）、AlphaTierEngine 接线（S7）、UI 渲染/校验
   （S8）——**"防线存在但未接线"是本次复核最突出的系统性问题**。

---

## 5. N2N 端到端健康度总评

| 维度 | 评级 | 说明 |
|------|:---:|------|
| 数据契约与湖原子写 | ⚠️ B- | 9 列/C3/R2 真实有效；但调整状态不一致（H1）、validator 无运行时调用（H2）、原子写覆盖不全（M1） |
| 分析引擎数学 | ✅ B+ | LPPL/CZSC/Wyckoff/FSM 机制可复现；但生产接线断裂（C1 pre_close/H2 无 sizer） |
| 信号生成与仲裁 | ⚠️ B+ | 适配器层优秀；**活路径 Sell-Priority 被违反（H1）** |
| 回测撮合 | ⚠️ B | 七防线/规则骨架 A 级；滑点双模型、坏账账目、ST 快路径 3 缺陷 |
| 风控合规 | ⚠️ B | 设计认真；**gross 公式错、防线未接线、KillSwitch Fail-Open** |
| 服务编排 | ⚠️ B | DAG 清晰；**事件总线死配置、get() 无锁、seed 失效** |
| 研究控制平面 | ⚠️ C+ | 统计核心正确；**门禁无生产调用方、沙盒恒 UNRATED、BH-FDR 不累积** |
| UI 展示 | ❌ D | 架构良好；**校验拒一切合法输入、mock 伪造、4 处渲染崩溃、回测缺席** |
| **总体（N2N 端到端）** | **⚠️ B-（不可直接投产）** | 契约/机制层达标，**执行层/接线层存在系统性"防线未接线"缺陷** |

**一句话**：数据契约、引擎数学、A 股规则、统计门禁的**本体正确性**高；但**生产接线**（合规引擎、
AlphaTierEngine、事件总线、仲裁活路径、UI 校验/渲染、pre_close 传播）存在系统性断裂，使多条
N2N 关键路径在真实运行时**未真正生效**。**在 P0 修复完成前不建议投产。**

---

## 6. 修复路线图（按 P0/P1/P2）

### P0（投产阻断，必须先修）

| 项 | 问题 | 动作 |
|----|------|------|
| C1-a | pre_close 不传播 | 生产路径（`fetch_for_brain`/`pack_writer`）写入 `pre_close`；回归断言回测=实盘 |
| C1-b | AlphaTierEngine 无生产调用方 | 接入真实扫描/研究管道，或明确标注"研究预留组件" |
| C1-c | UI validate_symbol 拒合法代码 | 长度契约改为 9（或按板块校验） |
| H1-sig | Sell-Priority 活路径被违反 | `arbitrate_candidates` Priority 1 BUY 前对候选 SELL 做 Sell-Priority 检查 |
| H1-risk | gross 公式不含多头 | 修正为含 long 的真实杠杆；补多头约束 |
| H2-risk | 合规引擎未接入 | 接入回测/实盘每日持仓生成 |
| H4-risk | KillSwitch 读失败 Fail-Open | 读失败默认 `killed=True` |
| H1-ui | mock 伪造数据（Rule 4） | 移除 `mock=True` 默认；缺失数据显式失败 |
| F8 | FeatureFlags 双模型 | 统一单一权威模型 + 默认值一致性测试 |
| H1-brain/H2-brain | LPPL 双路径矛盾 / 无 sizer | 决策路径统一走遥测；`DecisionBrain` 注入 `evt_risk`/`sizer` |

### P1（本轮）

H2-eb 事件总线接线、H3-eb seed 传播、H1-eb get() 双检锁、H2-bt 坏账账目闭环、H1-bt 滑点双模型
统一、H3-bt ST 快路径、S7 H1/H2（沙盒真实输入、门禁账本持久化累积）、S8 H2-H5（渲染崩溃）、
S8 H7（回测呈现接入）、M 级项。

### P2（后续）

S4 M1-M4、S5 M1/M2、S6 M 级、S7 M 级、S8 M 级、S9 F1/F2/F4/F9、各 LOW、文档漂移修正。

---

## 7. 建议与下一步

1. **先修 P0 十项**（多为 1-3 行接线或公式修正），每项加**回归测试**（如：pre_close 传播断言、
   合规引擎必须参与每日持仓、KillSwitch 读失败=停机、arbitrate_candidates SELL 优先断言、
   UI 合法代码校验、FeatureFlags 单模型一致性）。
2. **对既有 `docs/analysis/n2n/` 全 10 份报告做一轮代码证据复核**（本报告为其中独立一份），
   修正 D1-D6 事实性缺陷（虚构证据重述、ENGINE_PRIORITY 表、服务计数、事件顺序、列序矛盾）。
3. **重定义 N2N 验证探针**（S9 F1/F4）：探针 1 前提过时、探针 2 "Wyckoff SELL" 不可表示——
   给 `run_n2n_verification.py` 加真实 SELL 冲突源 + "decision=BUY + candidate SELL" 活路径断言，
   避免 H1-sig 长期逃逸。
4. **明确"防线存在但未启用"的风险口径**：AlphaTierEngine、事件总线、合规引擎、回测止损
   均需在文档标注"当前未接线"而非默认"✅"，杜绝虚假安全感。

---

## 8. 独立性声明与边界

- **独立性**：9 个子代理均在**不读取既有报告**的前提下独立取证，后交叉复核；关键结论经本机
  Python 实测（非文档转述）。
- **只读**：未修改任何源码；产出仅新增 `docs/analysis/n2n/subagent_verification_20261124/` 报告
  与 `SUBAGENT_N2N_VERIFICATION_WORKFLOW_20261124.md`（Rule 8 合规）。
- **边界**：未运行全量测试（超出子代理范围）；`file:line` 证据全部来自静态阅读 + 定向行为探针。
  部分 LOW/文档漂移项（如工作流文档文件名）为既有报告自身缺陷，非代码问题。
- **代码基线**：`b1d2415`；既有报告基线 `434aab1`；`434aab1→b1d2415` 对 `src/` 为空 diff，
  故双方核对同一份代码，**分歧纯源于分析方法差异，非代码漂移**。

---

**主会话综合**：OpenCode（SenseNova 6.8 Flash Lite / 商汤日日新） · 2026-11-24
**工作流**：`docs/analysis/n2n/SUBAGENT_N2N_VERIFICATION_WORKFLOW_20261124.md`
**产物**：9 份模块报告 + 本综合报告 + `VERIFICATION_MATRIX.md`
