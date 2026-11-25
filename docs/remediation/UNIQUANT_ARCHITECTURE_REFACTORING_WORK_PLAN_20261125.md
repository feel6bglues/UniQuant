# UniQuant 系统架构重构工作计划（第三方独立审视与收敛方案）

> **文档编号**：`UQ-ARCH-REFACTOR-PLAN-20261125`  
> **编制日期**：2026-11-25  
> **代码基线**：`b1d2415`（`src/uniquant/` 实测 229 个子层 `.py` 文件 / 56,991 LOC，含顶层 `__init__.py` 计 230 文件 / 56,992 LOC）  
> **综合依据**：  
> 1. 兄弟项目参考架构：[WSH-CORE_LIGHTWEIGHT_REFACTORING_BRAIN_SCORING_AND_FACTOR_LAB_PLAN_2026-11-25.md](file:///home/james/Documents/Project/wyckoff/docs/WSH-CORE_LIGHTWEIGHT_REFACTORING_BRAIN_SCORING_AND_FACTOR_LAB_PLAN_2026-11-25.md)  
> 2. 独立复核与专家评审：[N2N_SUBAGENT_COMPREHENSIVE_REPORT.md](file:///home/james/Documents/Project/UniQuant/docs/analysis/n2n/subagent_verification_20261124/N2N_SUBAGENT_COMPREHENSIVE_REPORT.md)、[INDEPENDENT_EXPERT_REVIEW_20261124.md](file:///home/james/Documents/Project/UniQuant/docs/analysis/n2n/INDEPENDENT_EXPERT_REVIEW_20261124.md)、[VERIFICATION_HARNESS_LESSONS_20261124.md](file:///home/james/Documents/Project/UniQuant/docs/analysis/VERIFICATION_HARNESS_LESSONS_20261124.md)  
> 3. 极速数据通道方案：[FAST_DATA_ACQUISITION_STUDY_AND_IMPROVEMENT_PLAN_20261124.md](file:///home/james/Documents/Project/UniQuant/docs/analysis/FAST_DATA_ACQUISITION_STUDY_AND_IMPROVEMENT_PLAN_20261124.md)  
> 4. 本仓库实证与规则基线：[CLAUDE.md](file:///home/james/Documents/Project/UniQuant/CLAUDE.md)、[AGENTS.md](file:///home/james/Documents/Project/UniQuant/AGENTS.md)、[AGENTS_CHANGELOG_ROUNDS.md](file:///home/james/Documents/Project/UniQuant/docs/archive/AGENTS_CHANGELOG_ROUNDS.md)  
> **合规约束**：严格遵循 `CLAUDE.md` 10 项铁律（TDD、ruff 零告警、不虚构未运行结果、不伪造门禁输入、不可变性、保留 A 股交易规则、安全第一、手术式改动、代码小而浅、文档同步）。

---

## 一、 执行摘要与核心现实约束

### 1.1 现行系统“三重分裂”诊断
基于 `b1d2415` 源码核查与独立 N2N 复核（3 CRITICAL / 26 HIGH / 去重约 100 项，总体健康度 B-，UI 为 D），UniQuant 的核心病灶并非“缺少组件”，而是**防线建在孤岛上、多大脑互相打架、工程与实证脱节**：

1. **工程双轨分裂**：
   * **A 轨（生产脚本侧）**：[CrossSectionalPITDataLoader](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/universe/dynamic_pit_loader.py)（DuckDB+Polars）+ `run_full_market_dynamic_pit.py` + [InstitutionalExecutionOrchestrator](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/institutional_execution_orchestrator.py)（`75/25-IH` / CFFEX 3-PB 分仓）+ `reconcile_qar.py` + `unified_daily_eod.py`。直接面向全市场截面与生产执行，但**绕过 `ServiceContainer` 与大部分 `brain/`**。
   * **B 轨（框架服务侧）**：[ServiceContainer](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/service_container.py) → [AnalysisService](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/analysis_service_v2.py) → [DecisionBrain](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/fsm/fsm.py) + `TradingSignalCollector`（8/9 适配器）→ [UnifiedBacktestEngine](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_engine.py)。承载 `brain/`（73 文件 / 20,917 行）与 `services/`（28 文件 / 8,554 行），却在主链路上存在 `pre_close=0.0`、无 `sizer/evt_risk`、`BUY` 短路覆盖 `SELL`、`ComplianceEngine` 未接线、`AlphaTierEngine` 零生产调用方、`EventBus` 零订阅者等断裂。
2. **Alpha 双重证伪与实证边界**：
   * 兄弟方案 `F-10b` 已证伪“纯技术规则”（389 股无偏池 OOS PF `1.12`，MC `p=0.0549`，Bootstrap 95%CI `[0.92, 1.70]`）；`F-11` 已确立 VLM 仅留盘后叙事。
   * UniQuant 第 16/19 轮在 4,643 股动态 PIT 池（含 337 退市股）上已证伪“QAR 纯多头满仓持有”（CAGR `-9.68%`），纯基本面 `Q1` 仅 `+2.35%`，**纯多头超额的 70%~80% 来自宏观择时动态空仓**。
3. **风控口径混用风险**：
   * [PreTradeComplianceEngine](file:///home/james/Documents/Project/UniQuant/src/uniquant/risk/compliance_engine.py) 默认约束（单票 ≤2.5%、行业 ≤10%、净敞口 ±0.5%、Gross ≤175%）面向 `75/25-IH` 市场中性轨，不可原封不动套用至纯多头择时选股轨，必须通过 **Track Profile** 参数化解耦。

### 1.2 从 `WSH-CORE` 吸收的核心架构范式（及本地差异化修正）
* **吸收**：
  1. **Hard Gates（二值 Veto，零分值贡献）与 Alpha Scoring（连续排序）严格分离**；
  2. **先在广义可交易底池做 MAD 去极值 + 申万一级行业内 Rank-ZScore，再过硬门禁**，杜绝小样本幸存池 Z-Score 失真；
  3. **连续化四维正交 `BrainAlphaScore`**（基本面质量 `Qual` + 威科夫结构与有效赔率 `Struct` + 微观量价连续不对称性 `Micro` + 行业动量与 VPVR/冲击摩擦 `Flow - Friction`）替代各适配器不可比的启发式 `confidence` 与 `argmax`；
  4. **无过零奇异点现金流算子**（`OCF_Yield`、`Accrual_Quality`）+ 缺失独立惩罚；
  5. **研究与实盘算子 100% 同源** + Mode A（横截面 RankIC）与 Mode B（事件条件化 $\Delta\mathbb{E}[R]$）双范式检验 + Purged & Embargoed WFO（$\ge 20$ 交易日）+ 低自由度对截断净 $R$-multiple 校准。
* **UniQuant 差异化修正**：
  1. **保留既有机构护城河**：复用 `CrossSectionalPITDataLoader`（DuckDB+Polars）、`InstitutionalExecutionOrchestrator`（75/25-IH & 3-PB）、A 股 5 板块规则、9 列冻结湖契约与第 22 轮打通的 `mootdx.affair` 财务通道；
  2. **严格风险偏序高于评分**：`AlphaScore` 仅掌管买入竞争与排序，**`KillSwitch`、`Compliance`、持仓止损/跌停/宏观冻结 Veto 永远一票否决买入**；
  3. **补齐截面组合回测器**：`UnifiedBacktestEngine` 仅支持单标的，必须在 `hands/backtest/` 新增支持多股槽位竞争的组合回测内核（`PortfolioBacktestRunner`）。

---

## 二、 目标系统架构蓝图

```text
================================================================================
[离线研究控制平面: research/ + brain/factors/] —— 100% 复用 brain/features/ 算子
================================================================================
  Phase 0 因果宽表 (5,522+日线含退市 + 2010+ PIT gpcw + 31申万行业 + tradable_mask)
        │  依托 CrossSectionalPITDataLoader (DuckDB + Polars 引擎)
        ▼
  WalkForwardFactorPipeline (Mode A 横截面 RankIC + Mode B 事件条件化 ΔE[R])
        │  Embargo >= 20d | Placebo Check | Collinearity |ρ|<=0.70 | 净R-multiple Ridge校准
        ▼
  AlphaTierEngine + 持久化 LedgerStore (跨历史累积 BH-FDR / DSR)
        │  仅 TIER_C/D 因子与参数 JSON 允许写入生产配置，并绑定 FactorRegistry
        ▼
================================================================================
[生产运行时主链路: 单向、Fail-Closed、按 Track Profile 参数化]
================================================================================
  1. data/ 极速与契约门禁层
     fast_tdx_stream + 7-IP池 (<90s同步) + 全路径原子写 (补齐gbbq等5处)
     Runtime 强门禁: FreshnessValidator (单标的文件头+内存态) + DataValidator + 统一QFQ口径
        │
        ▼
  2. brain/ 轻量认知与统一评分大脑 (三段式漏斗 + 持仓保护状态机)
     ├── brain/features/     : 全市场广义底池先 MAD + 申万一级行业 Rank-ZScore
     ├── brain/gates/        : 纯二值 Hard Gates (Macro 120d迟滞/冻结、Liquidity、ST/涨跌停、PIT排雷)
     ├── brain/scoring/      : 单一权威 BrainAlphaScore -> 校准期望净 R 倍数 E[R] (按 Regime 调权)
     └── brain/position_fsm/ : 原 DecisionBrain 降格为【已持仓退出/止损/熔断状态机】(强消费 pre_close)
        │
        ▼
  3. signal/ & risk/ 严格偏序仲裁与按轨合规门禁 (严禁 Fail-Open)
     偏序: KillSwitch(损坏默认停机) > Compliance(Track-Profile) > 持仓止损/跌停EXIT > Strategy SELL > AlphaScore BUY
     PositionSizer / PortfolioOptimizer: 异常即拒单(HOLD)，移除 100股兜底；接入单票上限
        │
        ▼
  4. hands/ 双核执行与单一撮合准则
     ├── 截面组合/机构轨: PortfolioBacktestRunner + InstitutionalExecutionOrchestrator (75/25-IH & 3-PB)
     └── 单票事件轨: UnifiedBacktestEngine (坏账平账/真实止损/先滑点后限价/0.01绝对限价/裸码兼容)
        │
        ▼
  5. ui/ & plugins/ 只读诚实观测面与盘后外围插件
     ui/ (仅消费 PipelineResult/ComplianceReport/AlphaTier账本) | plugins/ (盘后VLM/历史研报)
```

---

## 三、 模块与文件级处置矩阵（基于 `b1d2415` 实测 LOC）

> 注：标 `[待AST核]` 的文件在物理删除/合并前，必须先执行全仓 AST 引用与测试依赖扫描，并通过 Strangler Fig 兼容层过渡。

| 域 / 现存规模 | 关键文件与实测 LOC | 处置动作 | 目的与依据 |
| :--- | :--- | :--- | :--- |
| **`brain/lppl/`**<br>11 文件 / 3,304 行 | `calculator.py`(673), `engine.py`(653), `fitting_optimizer.py`(557), `multifit.py`(270), `numba_optimizer.py`(265), `data_manager.py`(210), `core.py`(201), `visualizer.py`(184), `regime.py`(142), `cluster.py`(124) | 1. 切断 [fsm.py:302,327](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/fsm/fsm.py#L302-L328) 对 `ctx.risk=="Danger"` 的强平钩子；<br>2. 整体下沉至 `plugins/diagnostics/lppl/` 或归档。 | 已被 MC 证伪；消除 `LPPLAdapter(diagnostic_only=True)` 与 `DecisionBrain` 强平之间的双路径矛盾。 |
| **`brain/wyckoff/`**<br>29 文件 / 9,283 行 | **下沉区**：`reporting.py`(397), `report_builder.py`(342), `image_engine.py`(428), `pnf.py`(326), `structural_adjuster.py`(149)<br>**收敛区 `[待AST核]`**：`engine.py`(745), `analysis.py`(502), `fusion_engine.py`(469), `phase_analysis.py`(506), `phase_detector.py`(408), `event_detector.py`(572), `events.py`(517), `classifiers.py`(301), `bayesian_events.py`(231), `v_shape_detector.py`(197), `monthly_classifier.py`(89) | 1. 叙事/图像/PnF 下沉至 `plugins/reporting/wyckoff/`；<br>2. 向量化量价原子算子（`effort_result`、TR 紧凑度、VPVR 套牢盘、Spring/Absorption/LPS 检测）收敛进 `brain/features/` 与 `brain/state/`；<br>3. 消除引擎与 `WyckoffAdapter` 双源判 BUY 重复逻辑。 | 现行 44 字段仅 8 个被消费；存在多检测器重叠与规则多写漂移风险。 |
| **`brain/fsm/` & `ntf/`**<br>777 + 192 行 | `fsm.py`(764) | 1. 移除主观整数评分 `_calculate_score` 参与抢买入权；<br>2. 降格为纯持仓状态机 `brain/position_fsm/`；<br>3. `NTF` 交由 Phase 2 Mode A/B 实证裁决去留（未过门禁即下线）。 | 彻底消除“FSM 买分”与“9 适配器 argmax”双脑冲突；对 `NTF` 以实证替代拍脑袋去留。 |
| **`brain/factors/` + `research/`**<br>4,798 + 1,885 行 | `walk_forward_pipeline.py`(344), `cscv_pbo_analyzer.py`, `forensics/`, `alpha_tier_engine.py`(641), `degrees_of_freedom.py`(445), `sandboxes/` | 1. 接入 `CrossSectionalPITDataLoader` 与 `brain/features/` 同源算子；<br>2. `AlphaTierEngine` 强制注入持久化 `LedgerStore`；<br>3. `sandboxes/` 要么补齐真实 WLS 残差 IC + Bootstrap PBO，要么剥离其晋升接口仅留预览；<br>4. 绑定 `FactorAccessLevel` 到 `AlphaTier` 晋升态。 | 解决 `AlphaTierEngine` 零生产调用方、`m=1` 绕过 BH-FDR 惩罚及沙盒恒 `TIER_UNRATED`。 |
| **`services/`**<br>28 文件 / 8,554 行 | `service_container.py`(215), `analysis_service_v2.py`(640), `research_pipeline.py`(650), `health_service.py`(596), `fsm_analysis_engine.py`(247), `data_pipeline_service.py` `[待AST核]` | 1. 删除死壳 `FsmAnalysisEngine` 与 `DataPipelineService`；<br>2. 移除零订阅者 `EventBus` 空壳（改结构化审计日志）；<br>3. `HealthService` 接入容器；<br>4. 消除 `bind_orchestrator` 2-环；补 `get()` 双检锁与 `shutdown()`。 | 消除虚幻可观测性、容器线程安全隐患与装配路径分叉。 |
| **`hands/backtest/`**<br>10 核心文件 / ~1,883 行 | `unified_engine.py`(665), `unified_matching_engine.py`(311) | 1. 修复坏账平账、真实止损执行、先滑点后限价、0.01 元绝对限价；<br>2. **决策下线未接线的 `UnifiedMatchingEngine`**（或强制共享同一 Slippage/Cost/ST 内核）；<br>3. 新增 `PortfolioBacktestRunner` 对接截面选股与机构对冲轨。 | 打通截面选股与槽位竞争回测能力，消灭 3.2x–7.1x 滑点分歧与 ST ±5% 漏检。 |
| **`data/`**<br>40 文件 / 7,808 行 | `tdxdata_online.py`, `data_fetcher.py`, `data_access_service.py`, `tdx_parser.py`, `freshness_validator.py`, `data_validator.py` | 1. 实施 `FAST_DATA_ACQUISITION` Wave 1–3；<br>2. 收口 5 处非原子写；<br>3. 统一 `load_data_with_fallback` 复权口径（消 raw vs qfq 分裂）；<br>4. 运行时边界接入 `DataValidator` 与轻量 `FreshnessValidator`。 | 解决 43 分钟全量同步瓶颈、gbbq 非原子写风险及运行时数据滞后/失真隐患。 |
| **`shared/`**<br>40 文件 / 6,897 行 | `config_models.py`, `config_schema.py`(180), `kill_switch.py`(109), `market_rules.py`, `limit_checker.py` | 1. 合并 `FeatureFlags` 为单一权威模型；<br>2. 修复 `KillSwitch` 读失败 Fail-Open；<br>3. 修复 `get_board_rule` 裸代码 `ValueError` 崩溃并统一调用 `limit_checker._round_limit_price`。 | 消除配置漂移、崩溃重启熔断失效及裸代码异常。 |
| **`ui/`**<br>8 文件 / 3,400 行 | `dashboard.py`(1,568), `manager_logic.py`(548), `components.py`(486), `lppl_visualizer.py`(370) | 1. 拆分 `dashboard_tabs/` 达标 Rule 9（<800 行）；<br>2. 删除 `mock=True` 默认与 `enrich_lake_data` 伪简化信号；<br>3. 接入 `PipelineResult` / `ComplianceReport` / `AlphaTier` 只读展示。 | 治本解决 D 级健康度（4 处崩溃、9 字符校验拒合法输入、Rule 4 数据伪造）。 |

---

## 四、 分阶段详细施工计划（Phase 0 ~ Phase 3）

> **迁移总原则（Strangler Fig + 测试门禁零中断）**：任何阶段均须维持 `ruff check src/uniquant/ tests/ scripts/` 零告警、`evidence_manifest.py verify` 无漂移，且 CI 口径测试覆盖率始终 `>= 84%`。禁止一次性暴力删文件引发 CI 雪崩；先建立新轨与对抗测试 → 开关切换验证 → 迁移或反转旧测试 → 最后物理删除/归档旧模块。

### Phase 0：实盘红线止血与验证 Harness 通电（第 1 周）
**目标**：在不改变整体模块拓扑的前提下，封堵全部已坐实的 CRITICAL/HIGH 级 Fail-Open 与断路缺陷，唤醒机械门禁。

| 任务 ID | 目标文件（行号） | 具体施工内容 | 验收标准与对抗测试（Must-Have） |
| :--- | :--- | :--- | :--- |
| **P0-01** | `analysis_service_v2.py:586-605`<br>`engine_factory.py:88`<br>`fsm.py:302,327` | 1. `_calculate_derived` 从 `stock_df` 写入 `pre_close` 至 `metadata` 并透传至 `MarketSignalContext`；<br>2. `AnalysisEngineFactory.brain` 注入 `evt_risk` 与 `sizer`；<br>3. `DecisionBrain` 增加 `lppl_diagnostic_only` 配置门（默认 True），禁止 `ctx.risk=="Danger"` 触发 `FORCE_EXIT`。 | 新增断言：`pre_close>0` 在生产路径有效触发涨跌停/熔断；`DecisionBrain` 不再对 LPPL Danger 产 SELL；`shares` 不再恒为 100。 |
| **P0-02** | `signal/arbitrator.py:328-344, 404-406`<br>`hands/backtest/unified_engine.py:365-368`<br>`tests/signal/test_arbitrator.py:170` | 1. `arbitrate_candidates` Priority 1 BUY 前强制执行 `SELL`/风险否决优先检查；<br>2. `sizer` 异常分支全部改为拒单（返回 `HOLD` / 0 股），移除 `100` 股魔法常数兜底；<br>3. **反转伪回归**：更新 `test_sizer_exception_falls_back_to_default_shares` 为断言拒单；同步修复 `arbitrate_candidates` 对 `sell_priority` 开关的尊重与 HOLD-blocker 否决（`M5`）。 | 实测 `decision=BUY + candidate SELL` 输出 `SELL`；`sizer` 抛 `InvalidStopLossError` 等异常时产出 0 笔成交且记录拒绝原因。 |
| **P0-03** | `risk/compliance_engine.py:234`<br>`shared/kill_switch.py:55-56`<br>`risk/evt_risk.py:105-115,286-299` | 1. 修正 `gross_leverage = (abs(total_long_cny) + abs(total_short_cny)) / aum_cny`；<br>2. 为 `PreTradeComplianceEngine` 抽象 `TrackProfile`（`neutral_75_25` vs `pure_long`），并接入 `UnifiedBacktestEngine` 与实盘执行前门禁；<br>3. `SharedKillSwitch.__init__` 读存储异常时默认 `_killed=True`；<br>4. `EVTRisk` 空/坏输入显式抛 `RiskCalculationError`（移除默认伪造指标）。 | 实测 `long=150%/short=50%` 必触犯 `gross>175%`；损坏 `kill_switch.json` 重启后 `is_killed==True`；`EVTRisk` 空输入抛错。 |
| **P0-04** | `data_access_service.py:214-244`<br>`services/service_container.py:60-63`<br>`services/research_pipeline.py:462,514`<br>`shared/config_models.py` vs `config_schema.py` | 1. 统一 `load_data_with_fallback` 湖命中与 miss 的复权口径；<br>2. `ServiceContainer.get()` 补齐双检锁；<br>3. `run_batch` 将 `seed` 透传至 `_run_single`；<br>4. 合并 `FeatureFlags` 为单一权威定义（统一 `service_container` 与 `bootstrap` 装配入口）。 | 两分支输出量纲一致回归测试绿；多线程并发 `get()` 返回同一实例；同 `seed` 批次输出确定性一致。 |
| **P0-05** | `ui/dashboard.py:281,434,454,675,1539`<br>`ui/manager_logic.py:121,268`<br>`ui/lppl_visualizer.py:342` | 1. `validate_symbol` 修正为 9 字符正则 `\d{6}\.(SH|SZ|BJ)`；<br>2. `mock` 默认改为 `False`，无数据显式报错；<br>3. 修复 4 处签名/键名/方法缺失崩溃；<br>4. LPPL 图表强制标注 `diagnostic_only（已证伪）` 并删除减仓操作建议。 | 默认标的 `600519.SH` 校验通过；用 `streamlit.testing` 跑通 5 大 tab 冒烟无 `KeyError/TypeError/AttributeError`。 |
| **P0-06** | `.githooks/` & `.github/workflows/`<br>`scripts/maintenance/verify_doc_paths.py`<br>`scripts/maintenance/run_n2n_verification.py` | 1. 激活 `.githooks/pre-commit` 并接入 CI；<br>2. 修正 `benchmark.yml` 触发分支为 `master`；<br>3. `run_n2n_verification.py` 移除合成 `Wyckoff SELL` 探针，改用真实冲突源（如 NTF/QAR），新增 **Track 7（复合故障注入验证：Sizer 异常 + KillSwitch 损坏 + 合规超限）**。 | CI 门禁全绿；Track 1–7 全部 PASS。 |

---

### Phase 1：极速数据通道与因果宽表底座（第 2–3 周）
**目标**：落地极速在线同步，封堵全路径原子写与运行时新鲜度盲区，完成多因子/事件检验所需 15+ 年历史因果底座。

| 任务 ID | 具体施工内容 | 验收标准（Go/No-Go） |
| :--- | :--- | :--- |
| **P1-01** | **极速 TDX 在线通道落地**（严格按 `FAST_DATA_ACQUISITION` Wave 1–3）：新增 `fast_tdx_stream.py`、`tdx_node_pool.py`（7 独立 IPv4 池）；改造 `TdxDataOnlineSource` 为 `threading.local()` 线程隔离 + `close()` 真释放 + `minute=True`；`sync_online_daily`/`minute` 复用 `FreshnessValidator.read_parquet_max_date` 跳过最新标的并将 `batch_size` 调至 500。 | 单标的 RTT `< 40ms`；5,522 标的 `up_to_date` 跳过 `< 5s`，有更新增量全同步 `< 90s`；Bootstrap 装配耗时维持 `< 50ms`（Track 6 红线）。 |
| **P1-02** | **全路径原子写与运行时验证接线**：将 `tdx_parser.py:391,405,432`、`import_financial.py:352`、`smart_factor_calculator.py:239` 共 5 处直写收敛至原子写（tmp + `os.replace`）；在写湖前接入 `DataValidator.validate`（False 阻断）；在 `DataService.fetch_for_brain()` 接入单标的文件级新鲜度校验与告警/补齐策略；`StorageManager.__init__` 增 `.tmp.*` 遗留清理。 | 崩溃仿真测试覆盖 `gbbq.parquet` 零损毁；`High<Low` 等脏帧被写湖门禁 100% 拦截；`online` 网络故障不再伪装空表（打 `source_error` 标记）。 |
| **P1-03** | **Phase 0 历史因果宽表构建**：利用第 22 轮 `mootdx.affair` 官方 HTTP 通道回填 `2010–2023` `gpcw_*.parquet`（补齐旧 584→新 658 列映射与 vintage 清洗）；补齐全部 **31 个申万一级行业指数**历史；整合全市场退市股历史并预计算 `Date × Symbol` 的 `tradable_mask`（停牌/一字板/ST/次新 `<120d`/`ADV20`），接入 `CrossSectionalPITDataLoader`。 | 2010–2026 因果宽表生成耗时 `< 10s`（DuckDB+Polars）；任意调仓日 `effective_ann_date <= T` 零未来泄露断言 100% 通过。 |

---

### Phase 2：`brain/` 大瘦身与 `research/` 实证生杀裁决（第 4–6 周）
**目标**：以影子模式上线 `WSH-CORE` 风格“三段式漏斗”，接通 `AlphaTierEngine` 与持久化账本，用真实样本外数据裁决所有因子与策略的去留。

| 任务 ID | 具体施工内容 | 验收标准（Go/No-Go） |
| :--- | :--- | :--- |
| **P2-01** | **建设同源原子特征库 `brain/features/`**：<br>1. 基本面：`roe_3y_mean`、`roe_delta`、`ocf_yield = OCF_TTM / MktCap`、`accrual_quality`（负分母免疫）、`deduct_np_yoy` + 独立缺失折扣；<br>2. 威科夫连续结构：`tr_compactness`、`effective_rr`（扣除 VPVR 最近上方 `HVN` 阻力）、`vol_clv_asymmetry`、`weis_wave_ratio`、`pullback_dryup`；<br>3. 动量与摩擦：`ind_rs60`（无 15% 硬截断）、`stock_vs_ind_rs20`、`overhead_supply_pct` + `impact_friction`。 | 全部算子纯向量化；单元测试校验 **全域广义底池 MAD 3 倍去极值 + 申万一级行业内 Rank-ZScore** 在门禁过滤前执行。 |
| **P2-02** | **Hard Gates 与 `BrainAlphaScore` 影子上线（`FeatureFlags.scoring_v2`）**：<br>1. `brain/gates/` 收口二值硬门禁（宏观 120 日迟滞/跌停熔断、`ADV20`/涨跌停/ST/Day1 JAC 禁追高、$S/T$ 几何空间律、PIT 硬排雷），严禁门禁给分；<br>2. `brain/scoring/` 按 `Regime` 体制（趋势再吸筹 vs 底部吸筹）输出校准后期望净 $R$ 倍数 $\hat{\mathbb{E}}[R]$；<br>3. `hands/backtest/` 新增轻量 `PortfolioBacktestRunner`（实现槽位竞争 `PortfolioSlotAllocator` 与组合级成交/合规）。 | `scoring_v2=True` 可与旧链路平行运行；在单日延迟 `< 50ms` 内完成全市场横截面打分与槽位排序。 |
| **P2-03** | **唤醒研究控制平面 `research/` 并完成存量体检**：<br>1. `WalkForwardFactorPipeline`（Embargo $\ge 20$ 日）直连 `AlphaTierEngine(ledger=LedgerStore.load())`，补齐 WLS 剥离后 `residual_ic_series` 与块状 Bootstrap `PBO` 计算；<br>2. 修复 Class C 换手 `None -> 0.0`（改 `inf` Fail-Closed）、去 `cross_section_N=500` 硬编码、阈值抽入 `config/research_gates.yaml`；<br>3. 把所有存量指标（Wyckoff/CZSC/NTF/Q1 财务/行业动量）送入 **Mode A（横截面）+ Mode B（事件条件化）** 及 **389 无偏池 / 5,000+ 动态 PIT 全市场扣费回测**。 | 产出仓库首份**真实定量体检报告**（含各因子 `RankIC`, `t_NW`, `PBO`, `BH-FDR q`, 净 `OOS PF`, `Bootstrap 95%CI`）；`FactorRegistry` 自动锁定未达 `TIER_C` 的因子。 |

---

### Phase 3：物理清剪、撮合统一与只读 UI 收口（第 7–8 周）
**目标**：根据 Phase 2 的实证判决，正式切换生产开关、物理清剪冗余代码并重建只读 UI。

| 任务 ID | 具体施工内容 | 验收标准（Go/No-Go） |
| :--- | :--- | :--- |
| **P3-01** | **安全拆弹与物理瘦身（依据 Phase 2 AST 扫描与淘汰名单）**：<br>1. 切换 `scoring_v2` 为唯一默认路径；<br>2. 将 `brain/lppl/`、冗余 `wyckoff` 叙事/图像/PnF 模块、Phase 2 未过门禁的引擎（如若 `NTF` 证伪则一并移除）、零订阅 `EventBus`、`DataPipelineService`、`FsmAnalysisEngine` 移入 `plugins/` 或归档；<br>3. 拆分 `DecisionBrain(FSM)` 为纯持仓管理状态机 `brain/position_fsm/`；<br>4. 消除 `AnalysisService ↔ AnalysisEngineFactory` 的 `bind_orchestrator` 2-环；补容器 `shutdown()` 与 `HealthService` 容器化；统一 `QAR` 与多维策略共用 `PortfolioAllocator` 与 `ComplianceEngine`（按 `TrackProfile` 加载）。 | AST 死代码守卫全绿；`tests/` 随模块迁徙同步更新，真实 CI 口径覆盖率维持 `>= 84%`，`ruff` 0 告警。 |
| **P3-02** | **撮合引擎统一与账目闭环**：<br>1. 决策下线零生产调用方的 `UnifiedMatchingEngine`（或将其与标量引擎收口到唯一 `SlippageModel`/`cost_model.get_stamp_tax_pct`/`board_registry`）；<br>2. 修复 `UnifiedBacktestEngine` 30 日跌停坏账平账（记录 PnL=市值跌幅，现金/权益闭环）、真实止损挂单撮合、先滑点后限价检查、0.01 元绝对限价及裸代码规范化。 | 回测单日权益悬崖归零，`equity_curve[-1] == final_cash` 恒成立；跨 2023-08-28 印花税半减精准校验通过。 |
| **P3-03** | **重建只读诚实 UI 与终验封版**：<br>1. 拆分 `dashboard.py` 为 `dashboard_tabs/`（单文件 `< 800` 行），删除 `enrich_lake_data` 伪信号；<br>2. 前端仅消费 `PipelineResult`、`ComplianceReport` 与 `AlphaTier` 晋升账本，完整展示扣费回测净值、Sharpe/MDD 与合规审计日志；<br>3. 运行完整 N2N Track 1–7 验证，更新 `AGENTS.md`、`docs/index.md` 与 `results/EVIDENCE_MANIFEST.json`。 | `pytest` 全绿、`ruff` 0 告警、`evidence_manifest.py verify` `no drift`、N2N 7 轨 PASS + 定量 Alpha 账本归档。 |

---

## 五、 关键风险与待人工拍板决策清单

| 风险 / 决策项 | 当前不确定性 | 建议应对 / 拍板口径 |
| :--- | :--- | :--- |
| **1. `NTF` 与部分 `Wyckoff` 检测器的去留** | 目前仅有对其代理机制的质疑，缺乏仓库内正式 OOS IC/PBO 证伪数值。 | 不在 Phase 0 盲砍，统一留到 **Phase 2（P2-03）经 `AlphaTierEngine` 实证裁决**，过关保留、不过关清剪。 |
| **2. 纯多头轨能否突破第 16/19 轮的贝塔拖累** | QAR 纯多头 CAGR `-9.68%`、纯 `Q1` 仅 `+2.35%`，纯靠选股未必能在 A 股熊市生存。 | 必须在 Phase 2 把第 19 轮验证有效的**宏观 120 日均线迟滞 + 跌停熔断空仓机制**作为 `MacroGate` 最高优先门禁，与多维选股协同验证。 |
| **3. `PreTradeComplianceEngine` 阈值拆分** | 现行 2.5% 单票 / ±0.5% 净敞口仅适合 `75/25-IH` 对冲轨。 | 要求在 **P0-03** 明确拆出 `TrackProfile` 配置段（`config/compliance.yaml`），严禁将市场中性限额误套至纯多头策略。 |
| **4. 批量测试与 AST 守卫迁移成本** | ~4,000 用例及 `test_uniquant_production_architecture_gates.py` 强依赖现行符号布局。 | 严禁跳过 Phase 2 的影子开关直接删旧文件；每下线一个旧模块必须同 PR 迁走对应单测与守卫断言。 |
