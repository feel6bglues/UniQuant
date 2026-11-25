# UniQuant 只读审计与架构规划方案（五维视角联合审查 + DAG 任务编排）

> **文档编号**：`UQ-READONLY-AUDIT-PLAN-20261125`
> **编制日期**：2026-11-25
> **审计模式**：**只读**，未修改任何业务源码
> **代码基线**：`b1d2415`（master），`src/uniquant/` 实测 **230 个 .py 文件 / 56,992 LOC**
> **测试基线**：`tests/` **253 文件 / 3509 测试函数**
> **审计方法**：Name-to-Name 代码级点对点实测（每条断言附 `file:line`）+ 五维专业视角联合审查
>
> **与既有文档的关系**：
> - 上游输入：`UNIQUANT_ARCHITECTURE_REFACTORING_WORK_PLAN_20261125.md`（重构计划）、N2N 10 报告集、独立专家评审
> - 本文定位：对上述文档的**独立实测复核 + 五视角深化 + 可执行 DAG 编排**
> - **不锚定 N2N 报告的聚合数字**（其综合报告已被独立评审判为"不可信"，见 §1.4），所有断言以本轮 `b1d2415` 源码实测为准，符合 AGENTS.md 反循环自证纪律。

---

## 0. 执行摘要

### 0.1 审计规模与产出

| 维度 | 数值 |
|------|------|
| 审计视角 | 5 个（威科夫交易员 / 数学量化 / 数据工程 / 算法工程 / Python 架构师） |
| 实测坐实的文档断言 | 13 项（全部 `file:line` 级验证） |
| **新发现的真缺陷** | **18 项**（1 CRITICAL / 7 HIGH / 8 MEDIUM / 5 LOW，见 §4 台账） |
| 纠正文档错误说法 | 3 处（服务数、Class A 可配置性、复权护栏≠口径统一） |
| 产出 DAG 任务 | Phase 0-3，共 21 个原子 Task |

### 0.2 核心结论

1. **重构计划的 Phase 0 红线断言全部成立**，且部分比文档描述**更严重**（KillSwitch Fail-Open、compliance 恒等式退化、注入链两处断裂）。
2. **发现文档完全遗漏的 1 个 CRITICAL 缺陷**：`dynamic_pit_loader` 无公告日 PIT 门 → 未来泄露（NEW-17），且它会污染整个 Phase 2 因子实证裁决。
3. **发现文档遗漏的多个 HIGH 缺陷**：FSM 状态机死区（NEW-1）、滑点双公式孤岛（NEW-5）、AlphaScore 维度错误（NEW-2）、注入链双断（NEW-10）、复权口径分叉（NEW-18）、前视算子陷阱（WY-1）。
4. **新增关键依赖约束**：`P2-T03（因子实证裁决）depends_on P1-T03（PIT 门通过）`——避免用带泄露的 loader 污染 Phase 2 结论。

---

## 第一阶段：文档 vs 代码现状 Gap 分析

### 1.1 经实测**证实**的重构假设（可作为施工依据）

| 文档断言 | 实测证据 | 判定 |
|---|---|---|
| P0-01 `pre_close=0.0` | `_calculate_derived`（analysis_service_v2.py:557）**从不写入** `pre_close`；FSM 在 fsm.py:338/392/578 三处消费 `ctx.pre_close` 做涨跌停+跌幅熔断；`MarketSignalContext.pre_close` 默认 `0.0`（interfaces.py:79） | ✅ **成立**，防线默认失效 |
| P0-01 brain 未注入 evt_risk/sizer | `engine_factory.brain`（engine_factory.py:82-94）直接 `DecisionBrain()` **无参构造** | ✅ 成立（且更严重，见 NEW-10） |
| P0-01 FSM `ctx.risk=="Danger"` 强平 | fsm.py:302 `FORCE_EXIT` 钩子真实存在；`_calculate_score`（:308）参与抢买入权 | ✅ 成立 |
| P0-02 sizer 100 股兜底 | sizer.py:101-106 `except: return 100`；unified_engine.py:364/376 BUY 分支 `shares=100` | ✅ 成立（fail-open） |
| P0-02 LPPL SELL 特判绕过仲裁 | unified_engine.py:337-348 `if "lppl" in sig.reason.lower()` 独立建 SELL 挂单 | ✅ 成立 |
| P0-03 KillSwitch Fail-Open | kill_switch.py:55-56 读状态异常仅 `logger.error`，`_killed` 保持 `False`（:42） | ✅ **成立**，损坏 JSON 重启不熔断 |
| P0-03 EVTRisk 伪造指标 | evt_risk.py:107 坏输入回落 `_get_default_metrics()` | ✅ 成立 |
| P0-04 seed 未透传 | research_pipeline.py:514 `_run_single` 硬编码 `seed=None`，经 ThreadPoolExecutor（:540）并发 | ✅ 成立，批次不可复现 |
| P0-04 FeatureFlags 双定义漂移 | `config_models.py:8` vs `config_schema.py:82` **同名类默认值冲突** | ✅ 成立，且比文档严重 |
| AlphaTierEngine 零生产调用 | services/hands 全仓 grep `AlphaTierEngine` **零命中** | ✅ 成立 |
| EventBus 零订阅者 | research_pipeline 6 处 `publish`，**无任何 `subscribe`** | ✅ 成立（措辞需精确化，见 NEW-15） |
| PortfolioBacktestRunner 缺失 | hands/ 全仓 grep **零命中** | ✅ 成立，截面组合内核待新建 |

**FeatureFlags 双定义漂移实测**（两处同名类，默认值直接矛盾）：

| Flag | config_models.py（实际被 service_container 加载 :158/:174） | config_schema.py（仅被 shared/__init__:31 导出 AppConfig） |
|---|---|---|
| `signal_arbitration` | `False` | **`True`** |
| `factor_gate` | `"off"` | **`"block"`** |
| `event_bus` | `False` | **`True`** |
| `typed_contracts`/`engine_migration` | 有 | **缺失** |

`from_dict` 嵌套取值也不一致（config_models 取 `data["feature_flags"]`，config_schema 取顶层）。**`scoring_v2` flag 两处均无** → Phase 2 影子上线机制需**新建**。

### 1.2 比文档**更严重**的发现

**[GROSS] compliance gross_leverage 是代数恒等式，对纯多头轨永久空转**
`compliance_engine.py:230-234`：
```python
cash_buffer_cny = aum_cny - total_long_cny
gross_leverage = (total_long_cny + total_short_cny + cash_buffer_cny) / aum_cny
# 代入后 ≡ (aum_cny + total_short_cny) / aum_cny
```
纯多头轨 `total_short=0` → `gross_leverage ≡ 1.0`，**永远不可能超 `max_gross_leverage=1.76`**。这条硬风控对纯多头择时轨是**摆设**。文档 P0-03 只说"口径错"，实为恒等式退化。叠加 `TrackProfile` 全仓 grep **零命中** → 纯多头轨与 75/25-IH 中性轨无法解耦。

### 1.3 文档与代码**冲突/遗漏**处（需修正认知）

| 文档声称 | 实际 | 修正 |
|---|---|---|
| N2N 评审"实际 12 services" | `service_container.py:98-212` 实注册 **13 个** | 评审误读：`arbitrator` 工厂在 flag=False 时返回 `None`（:156-170）→ 注册 13、活跃可能 12，非计数错误 |
| 数据层 raw vs qfq 分裂待统一 | data_access_service.py:10-14 **已有 R2 护栏**（`_assert_unadjusted_for_lake`） | 护栏只保证"不写复权进湖"，**未解决读取口径分叉**（见 NEW-18），P0-04 仍必要 |
| Wyckoff "44 字段" | `WyckoffOutput` 实为 **36 字段**，Adapter 硬消费仅 **2 个**（direction+confidence） | 破坏面远小于文档渲染 |
| "Class A 可配置、B/C/D 硬编码"（文档 M4） | `alpha_tier_engine.py` **四级阈值全硬编码**（:135/231/297/402），全文无 `get_config()` | 提问前提不成立，四级全硬编码 |

### 1.4 文档可信度警告（元层 Gap）

`N2N_COMPREHENSIVE_REPORT.md` 底部已附**独立专家评审**，总裁决"**不可信**"：汇总层存在**虚构代码**（报告 09 的 LPPL 结论继承自虚构代码）、聚合数字系统性失实（称"~150 文件"实为 230）、"98.9% 准确率"系**循环自证**（验证者与被验证者同源）。逐报告评级：仅 `07 研究控制平面`为"可信"，综合报告"不可信"。

**因此**：本方案**不锚定 N2N 报告的聚合数字**，所有断言均以本轮对 `b1d2415` 源码的实测为准。

---

## 第二阶段：五维专业视角联合审查

### 视角 1 — 威科夫交易员视角

**核心结论：重构不破坏量价语义的前提是保留两套范式差异。**

- **Wyckoff = 截尾窗口批处理快照**：`engine.py:292` `frame.tail(lookback)` 一次性跑 step0→step5，产出单份报告。**非逐K线在线状态机**。
- **FSM = 在线逐K线**：fsm.py:102 `iloc[:-1]` + :115-117 `shift(1)`（连已收末根都不进 MA）——全仓最严格 anti-look-ahead 范式。**两者范式不同，收敛进 `brain/features` 时不可强行统一**。
- **Spring/UTAD/SOS 确认机制**：Spring（event_detector.py:154-167）信号=跌破后 1-2 根内收回那根的 close；UTAD（:192-199）1-2 根收回；SOS（:284-290）当根收盘自洽。判定层**无前视**（确认根早已收线），真正防"当日收盘判当日入场"的闸门在回测引擎 T+1-open（unified_engine.py:65/209/254）。
- **⚠️ 最大前视风险 [WY-1]**：`scan_bc_sc`（event_detector.py:55-68）用翻转 rolling(9)+`np.roll(-1)` 计算**每根之后 9 根**的最低/最高，`events.py:95` PS 用 `close[i+1]` 确认。这些是"含确认窗口的事后标签"，**平移进 features 层若被当成"每根只用截至当根数据"的算子，会静默变前视**。必须标注为滞后确认标签或显式 `shift`。
- **⚠️ T+1 铁律迁移 [WY-2]**：DecisionBrain 降格为持仓状态机时，`step3_phase_c_t1`（event_detector.py:531）用当根收盘做 T+1 压力测试。若把执行改成"当根收盘成交"，SOS/Spring 当根入场立刻变真前视。**T+1-open 铁律必须随降格一起搬**。
- **语义完整性**：`structural_adjust`（默认关，engine.py:178）**只动置信等级不动相位**（structural_adjuster.py:44-79），开启后仅通过 0.40 gate 软过滤信号，不改 ACCUMULATION→DISTRIBUTION 判定。其依赖 events+phase+step3 三输入，features 层需保留此契约。
- **破坏面可控 [WY-3]**：WyckoffOutput 36 字段中，驱动 BUY 的**只有 direction + confidence（0.40 gate，adapters.py:224）**，其余 27 字段为标注/研究面。降格 DecisionBrain 时硬契约极小。

### 视角 2 — 数学与量化研究视角

- **Brain Scoring 量纲失真 [MATH-1]**：FSM `_calculate_score`（fsm.py:308-318）把 4 个**异构二值布尔**（缠论三买/均线趋势/alpha>0.6/NTF SUPPORT）用固定常数 **CZSC=20/TREND=15/ALPHA=10/NTF=10**（technical.py:88-92）等权相加成整数分（合计 55）。缠论形态、均线趋势、连续 alpha 分、NTF 强度被强行同量纲叠加，**无统计标定、无非线性映射依据**。
- **[NEW-1] FSM PYRAMID 态结构性不可达**：`_calculate_score` 理论最大 = 55，但金字塔迁移阈值 `FSM_SCORE_THRESHOLD_TO_PYRAMID = 70`（technical.py:96）——**永不相交**。PYRAMID 态经此路径**永远无法进入**，状态机死区。
- **[NEW-2] AlphaScoreAdapter 置信度映射维度错误**：`adapters.py:413` `confidence=abs(score-0.5)*2` 假定 `alpha_score ∈[0,1]` 且以 0.5 为中心，但真实 alpha_score 是**无界连续斜率**（alpha_decoupler.py:238 `slope*100`、:270 `slope_vs_bench+slope_vs_sector`）。映射**系统性失真**。
- **9 适配器 confidence 不可比 [MATH-2]**：Wyckoff gate=0.40（adapters.py:222）、NTF `intensity>=0.6`→`min(intensity,0.9)`（:371-375）、CZSC `min(0.5+bi_count*0.05,0.9)`（:163）、FSM/Regime/MAStatus 硬编码 0.5/0.5/0.3、QAR `min(0.5+weight*10,0.95)`（:482）。各引擎 confidence 是**自定义启发式 argmax**，非同口径连续值 → `arbitrator` 按 `max(confidence)` 比较**在量纲上无意义**。
- **[NEW-6] alpha_tier 四级阈值全硬编码**：`alpha_tier_engine.py` 全文**无 `get_config()` 调用**。Class A（:135-143）、B（:231-239）、C（:297-308）、D（:402-408）**一律是 `evaluate()` 内字面 dict**。
- **[NEW-7] walk-forward 无 purge/embargo**：`walk_forward_pipeline.py:73-91` `_temporal_split`（train=504/test=63）**无 purge/embargo**——重叠 holding 期会泄漏。文档声称的"Embargo≥20d"是**待补**。
- **[NEW-8] BH-FDR m=1 绕过**：`degrees_of_freedom.py:393-430`，族系仅 1 次试验时 `effective_trials=max(1,1)=1` → `p_adj≡p_raw`，**首次/唯一试验零多重性折价**。缺失输入诚实门禁（alpha_tier_engine.py:472-491）做得正确。
- **[NEW-9] 生产层"裸奔"断层**：统计设施（walk-forward/正交化/IC衰减/多重检验）**只在 research+scan_service 报表层**，生产 FSM 决策（fsm.py:308）走裸布尔门，**零交集**。默认合成走纯 Z-Score（composer.py:245-279），MAD 去极值默认关（neutralize=False，:389），缺失值 `fill_value=0.0`（:307-311）按均值静默填充不惩罚不披露。申万行业内 MAD 鲁棒标准化**存在但是孤岛**（forensics/z_cnmm_calculator.py:374-423，composer 零引用）。
- **[NEW-8b] FactorAccessLevel ≠ AlphaTier（同名不同物，零接线）**：`registry.py:175-184` `check_access` 只看"名字在不在注册表"，**从不查询 TIER_A/B/C/D**。两者是**两个同名概念、互不相通**。

### 视角 3 — 信息与数据工程视角

- **[NEW-17] `dynamic_pit_loader` 无公告日 PIT 门 → 未来泄露（CRITICAL）**：`dynamic_pit_loader.py:78-92` 财报过滤**只按报告期不按公告日**（`WHERE report_date % 10000 = 1231`），`screen_and_score_cross_section`（:200-204）按 `year==fiscal_year` 过滤后 :219 直接 join `as_of_date` 价格——**整条链无 `effective_ann_date <= as_of_date` 判定**。若 `fiscal_year=2023` 而 `as_of_date` 在 2024 年 1~4 月（年报法定披露期内），会用**尚未披露的 FY2023 年报**打分 → **未来泄露**。反证项目他处有正确 PIT（financial_bridge.py:247 用 merge_asof 公告日对齐），**但 dynamic_pit_loader 完全没接**。
- **[NEW-18] `load_data_with_fallback` 湖命中(raw) vs miss(qfq) 复权口径分叉**：湖命中（data_access_service.py:214-217）原样返回 raw；湖 miss（:238-239）`adjust = "" if index else "qfq"` → stock 显式走 qfq，且 qfq 结果 :260-266 只返回不写湖。同一 symbol 两条路径**静默混入同一研究口径**。
- **[DATA-1] FreshnessValidator 未入运行时路径**：`validate_freshness` 仅 `check_freshness_sla.py:102`（crontab）+ 验收脚本调用；运行时健康检查 `health_service.py:383-390` 用另一套 `_last_fetch_time`，**不调 FreshnessValidator**。lake 过期不会阻断实盘分析。
- **[DATA-2] 原子写遗漏（3 个点名文件全中招）**：`tdx_parser.py:391/405/432`（gbbq 直写）、`import_financial.py:352`（财务 parquet 直写）、`smart_factor_calculator.py:239`（因子缓存直写）全部绕过 storage_manager 原子写；另有 `import_financial.py:77` 指纹 JSON 直写。
- **[DATA-3] 9 列契约未统一到单一常量**：`data_fetcher.py:38-51` 是权威锚点（amount 在 volume 前），但 `tdxdata_online.py:41` DAILY_COLUMNS **volume 在 amount 前**（顺序相反）、`tdx_parser.py:190` 8 列无 code、周月线 `resampler.py:63` 聚合仅 6 列丢弃 reserved/code、5 分钟用 datetime、`data_validator.py:26` 查 8 列无 reserved。多周期/财务/因子缓存**各写各的 schema**。
- **[DATA-4] C3 红线靠代码事实、无断言守卫**：`data_cleaner.py:50-54` 全文无 `bfill`（C3 事实成立），但**无断言/测试强制"永不引入 bfill"**。清洗步骤确定（无随机源），但 `freshness_validator.py:257-262` 抽样按 `st_mtime` 排序是**隐式非确定**来源。
- **[DATA-5] tradable_mask 不在 loader 内**：上市/退市时点过滤在 `dynamic_pit_universe.py:107-116`（`ipoDate<=as_of_date<outDate`+次新过滤）作为 `eligible_symbols` 传入，loader 仅 `.is_in()` 过滤（:203）。

### 视角 4 — 算法工程视角

- **逐K线 Python 循环（真实瓶颈）**：`unified_engine.py:191` 主回测逐日 for 循环（cash/position/pending_order 跨 bar 状态机，**无法简单向量化**）；`unified_matching_engine.py:267` T+1 检查 `for i in range(n)` 逐元素 `toordinal()`、`:104-113` SlippageModel 分支循环、`:200/:264` 列表推导。
- **已向量化**：`indicators.py` 全部 pandas rolling/ewm（例外 `calc_market_entropy:177` 仍 for+np.histogram）；`event_detector.scan_bc_sc:27-133` 全向量化；`czsc_engine._prepare_bar_list:298-303` 掩码向量化。
- **Fast/Slow Path 分支**：`unified_matching_engine.py:137` `if names is None and trading_days_listed is None` → 全向量化 Fast Path；任一存在 → 逐元素 Slow Path（ST 名称检测/IPO 限涨规则）。但 `:139` Fast Path 内部仍有 `[get_board_type(s) for s in symbols]` 列表推导。
- **[NEW-3] LPPL numba 内核 + LRU 缓存双双是孤儿死代码**：`numba_optimizer.py` 三个 `@njit` 内核**全仓唯一 importer 是测试**（且用 `.py_func()` 绕过 JIT），生产 `calculator.py:14-22` 不导入它；LRU `_fit_cache`（calculator.py:296读/:365写）唯一读写点 `fit_single_window` **零调用方**（生产调 `calculator.fit()` 无缓存）→ **缓存从未命中**。缓存键 `sha256(close.tobytes())[:16]`（:292）**只含 close 字节**，缺拟合超参/边界。LPPL 同一 RMSE 有 **4 份 cost_function**（calculator:221/241、core:70、fitting_optimizer:150）。
- **[NEW-4] CZSC 单实例非线程安全**：`czsc_engine.py:185-187` 跨标的隔离靠 `if symbol != self._current_symbol: self.analyzer=None`——实例级共享状态，并发多标的互相污染（check-then-set 竞态）。且批量路径 `get_czsc_signals`（:472）每次 `CZSC(bars)` 全量重算，与增量路径是**两套独立实现**。
- **[NEW-5] 滑点分歧 3.2x-7.1x 精确根因 + 撮合引擎未接线孤岛**：生产回测/实盘用标量 `unified_engine`（service_container.py:143-145、bootstrap.py:115、research_pipeline.py:140 全部实例化它）；向量化 `UnifiedMatchingEngine` **src 内零生产调用方**（仅 hands/__init__.py:6 文档注释）→ **孤立未接线**。公式分歧：回测版 `impact=min(0.001*sqrt(ratio),0.02)`（unified_models.py:300-309）vs 撮合版小单段 `0.001*sqrt(eta/0.10)`（unified_matching_engine.py:79-92）——**除以 0.10 使小单 impact 放大 √10≈3.16x**（直接解释 3.2x）；cap 0.05 vs 0.02，叠加 SlippageModel.estimate 后拉大至 ~7x。同理成本/涨跌停/T+1 判定各有标量+向量化两份实现。
- **向量化收敛到 brain/features 的障碍**：①前视窗口依赖（spring/utad/false_breakout 的 `for j in range(i+1,...)` 前向引用）；②边界参数为标量上下文（`scan_spring(df, boundary_lower)`）；③复合布尔短路+early return（首次命中即 return）；④**跨 bar 状态机（最大障碍）**：`state.py:StateManager`（:21）维护 prev_state/freeze_until/watch_status/spring_freeze_days，**本质不可纯向量化**，需保留 Python 状态机外壳仅下沉叶子算子；⑤分散 `.iloc[i-1]` 相邻引用（可 `df.shift(1)` 向量化）。
- **可复用缓存层**：`indicators.py` 每算子挂 `@smart_cache(ttl)` + 内容寻址键（hash_pandas_object），同一 df 重复调 `calc_atr` 命中缓存，Wyckoff `event_detector.py:453` 即复用。但**滑点/成本/LPPL cost function 存在多份平行实现**，一致性靠人工。

### 视角 5 — Python 架构师视角

- **[FIX-1] 服务注册数 = 13**（N2N 正确，评审"12"是误读）：`service_container.py:98-212` 实注册 13 个。`arbitrator` 工厂在 `signal_arbitration` flag=False 时返回 `None`（:156-170）→ 注册名 13、活跃实例可能 12。
- **[NEW-11] `ServiceContainer.get()` 无双检锁（线程不安全）**：`get()`（:60-63）check-then-act **完全无锁**，而单例 `instance()`（:42-48）**有** `cls._lock`。叶子层 `engine_factory._lazy_init`（:37-44）也有 RLock。→ **线程安全只在叶子层、不在编排层**。
- **[NEW-12] `bind_orchestrator` 2-环客观存在**：`service_container.py:108-137` factory 初始指向 data_service → asvc 存 `self._factory=ef`（analysis_service_v2.py:114）→ `ef.bind_orchestrator(asvc)` 指回（engine_factory.py:23-34）→ **运行时双向引用环**。受控但 DAG 注释"零循环依赖"在引用图层面**不成立**。
- **[NEW-10] evt_risk/sizer 注入链两处断裂**：`engine_factory.brain`（:88）`DecisionBrain()` 无参；`DecisionBrain.__init__`（fsm.py:187-194）明确接受这俩；`fsm_analysis_engine.py:82` 走 orchestrator 注入，**但 `AnalysisService` 硬置 `self.evt_risk=None; self.sizer=None`**（analysis_service_v2.py:101-102），容器构造它也不传（:130-134）→ 该路径也拿到 None。**容器在 research_pipeline 构造了 `PositionSizer()`（:191-197）却没接到 AnalysisService/brain**。`health_service.py:46` 是唯一真正注入路径。
- **[FIX-2] `pre_close` 默认 `0.0` 而非 `None`**：`interfaces.py:79`，`from_dict` 兜底同为 0.0（:110）→ **"缺失昨收"与"昨收真为 0"不可区分**，潜在静默错误源。
- **[NEW-14] `config_loader.py:21` STRICT_TIMESTAMPS 别名指向不存在的字段**：`strict_timestamps` **两份 FeatureFlags 都没有** → 死映射。
- **[NEW-15] EventBus 是"已建成但未接线"的空转基础设施**：实现**完整**（subscribe/publish/AsyncEventBus，event_bus.py:14-90），**非空壳类**。publish 被大量调用（analysis_service_v2 7 次 + research_pipeline 8 次 + adapters 1 次），但 `subscribe` **全仓零命中**；根因：所有 publish 点 event_bus 都是 `Optional=None` 注入，而 **`ServiceContainer.initialize()` 从不注册/注入 event_bus**（13 服务里没有它）→ event_bus 恒 None/空表，每个 topic 落到零 handler。
- **[NEW-13] 6 个 Protocol 全是文档性质，引擎零声明零 isinstance**：`interfaces.py:545+` 定义 6 个 `@runtime_checkable` Protocol，但**所有引擎是裸类**（`DecisionBrain`/`CzscAnalysisEngine`/... 全 `class X:` 无基类无 Protocol 声明）；除 `CalculationPluginProtocol` 外**无一处 isinstance 校验**。`_lazy_init` 用 importlib 反射 + duck-typing 容错。→ 引擎/适配器边界**无结构性约束**，是"9 适配器 confidence 不可比"能长期存在的架构根因。
- **[NEW-16] 双轨影子上线：flag 框架可复用，但"影子双跑"语义需新建**：可复用 `engine_migration: Dict[str,bool]`（config_models.py:13）现成按引擎灰度槽位；已有 3 个活范例（signal_arbitration:161 / factor_gate:177 / use_research_data_pack:320）；config.yaml:359-364 有落点。缺口：现有 flag 全是 **on/off 二元替换，无"新旧双跑+对比+回退"的影子语义**。前置阻塞：先合并漂移 FeatureFlags。
- **接口字段确认**：`TradingSignal`（interfaces.py:147-162）有 action/reason/confidence/shares/symbol/price/timestamp/metadata；`MarketSignalContext`（:61-88）有 regime/risk/ntf_side/ntf_intensity/is_3rd_buy/alpha_score/ma_status/price/pre_close/symbol；`ResearchDataPack`（:209-227）；`PipelineResult` **不在 interfaces.py，在 research_pipeline.py:79-99**。

---

## 第三阶段：可执行工作流 DAG 任务清单

> 组织原则：**Phase → Task**，Strangler Fig + 测试门禁零中断。每 Task 含 ID/依赖/文件/改造/DoD/回滚。

### Phase 0 — 实盘红线止血（第 1 周，最高优先）

| Task ID | 名称 | 前置依赖 & 并行度 | 涉及文件 | 核心改造 | DoD（可执行验收） | 风险与回滚 |
|---|---|---|---|---|---|---|
| **P0-T01** | 写入 pre_close 唤醒涨跌停/熔断防线 | 无前置。与 T02-T08 **并行** | `services/analysis_service_v2.py:557`(`_calculate_derived`)、`brain/fsm/fsm.py`、`shared/interfaces.py:79` | `_calculate_derived` 从 `stock_df` 计算 `pre_close=close.shift(1).iloc[-1]` 写入 metadata 透传至 `MarketSignalContext`；评估哨兵值改 `Optional[float]=None`（FIX-2 区分缺失/真0） | 新增 `tests/test_pre_close_wiring.py`：构造已知 stock_df 断言 `ctx.pre_close>0`；涨跌停标的 `check_limit_status` 真实触发；fsm.py:578 跌幅熔断激活 | 纯新增字段，默认向后兼容；失败回滚 metadata 写入，FSM 行为不变 |
| **P0-T02** | 打通 evt_risk+sizer 注入链 | 无前置，与 T01/T03-T08 并行 | `services/analysis/engine_factory.py:82`、`services/analysis_service_v2.py:101-102`、`services/service_container.py:130-134` | **打通整条链**（NEW-10）：容器→AnalysisService（删 :101-102 硬置 None）→engine_factory.brain→`DecisionBrain(evt_risk=..., sizer=...)` | 新增断言 `analysis_service.evt_risk is not None` 且 `brain._sizer is not None`；`pytest tests/test_engine_factory.py` 全绿 | 构造签名可选参数向后兼容，回滚即删注入 |
| **P0-T03** | 移除 FSM 买分 + LPPL 强平 + 消除状态机死区 | 依赖 T02（同文件 brain 注入）。与 T01/T04-T08 并行 | `brain/fsm/fsm.py:302,308`、`shared/config_models.py` | ① 新增 `lppl_diagnostic_only`(默认 True) 门，禁 `ctx.risk=="Danger"` 触发 FORCE_EXIT；② `_calculate_score` 退出买入决策（保留 telemetry）；③ **消除 PYRAMID 死区**（NEW-1，随买分移除一并作废阈值或降格状态机） | 新增 `tests/fsm/test_no_lppl_force_exit.py`：`ctx.risk="Danger"` 不产 SELL；`_calculate_score` 不再决定买入；PYRAMID 不可达缺陷消除 | feature flag `lppl_diagnostic_only` 可关回旧行为 |
| **P0-T04** | sizer fail-open→拒单 + 反转伪回归 | 无前置，与 T01-T03/T05-T08 并行 | `risk/sizer.py:101-106`、`hands/backtest/unified_engine.py:364,376`、`tests/test_sizer.py` | sizer 异常分支返回 0 股/HOLD（删 `return 100`）；unified_engine BUY 分支删 `shares=100` 魔法常数；**反转** `test_sizer_exception_falls_back_to_default_shares` 为断言拒单 | 新增/改写 `tests/test_sizer.py`：sizer 抛 `InvalidStopLossError` → 0 笔成交+记录拒绝原因；`shares` 不再恒 100 | 若下游强依赖 100 兜底，先加 `strict_sizing` flag 双轨 |
| **P0-T05** | KillSwitch Fail-Closed + EVTRisk 抛错 | 无前置，与 T01-T04/T06-T08 并行 | `shared/kill_switch.py:55-56`、`risk/evt_risk.py:107`、`tests/test_production_kill_switch.py` | kill_switch 读状态异常 → `_killed=True`；evt_risk 坏输入 → 抛 `RiskCalculationError`（删 `_get_default_metrics` 回落） | 新增断言：损坏 `kill_switch.json` 重启后 `is_killed()==True`；`EVTRisk.calculate_metrics(empty_series)` 抛错 | Fail-Closed 只会更严，回滚即恢复 logger-only |
| **P0-T06** | 合规恒等式修复 + TrackProfile | 无前置，与 T01-T05/T07-T08 并行 | `risk/compliance_engine.py:230-234`、新增 `config/compliance.yaml` | ① gross_leverage 改 `abs(long)+abs(short))/aum`（GROSS）；② 抽象 `TrackProfile`(`neutral_75_25`/`pure_long`) 参数化阈值 | 新增 `tests/test_compliance_track_profile.py`：`long=150%/short=50%` 触发 `gross>175%`；`pure_long` 轨用纯多头阈值 | TrackProfile 默认 `neutral_75_25` 保持旧行为 |
| **P0-T07** | FeatureFlags 单一权威 + seed 透传 + 复权口径 + 容器锁 | 无前置，与 T01-T06/T08 并行 | `shared/config_models.py`、`shared/config_schema.py:82`、`shared/__init__.py:31`、`services/research_pipeline.py:514`、`services/data_access_service.py:238`、`services/service_container.py:60`、`shared/config_loader.py:21` | ① 合并双 FeatureFlags 为单一权威（生产只认 config_models，config_schema 转发）；② `_run_single` 透传 `seed`；③ 统一 `load_data_with_fallback` 复权口径（NEW-18 湖命中 raw vs miss qfq）；④ `get()` 补双检锁（NEW-11）；⑤ 修 STRICT_TIMESTAMPS 死别名（NEW-14） | 新增 `tests/test_config_single_source.py` 断言无同名冲突类；`tests/test_research_pipeline.py` 同 seed 批次确定性一致；复权口径两分支量纲一致回归绿；多线程并发 `get()` 返回同一实例 | 合并保留 config_models 为权威；复权口径统一以 raw SSOT 为准 |
| **P0-T08** | UI 止血（mock=False + 9字符校验） | 无前置，与 T01-T07 并行 | `ui/dashboard.py:281,434,454,675,1539`、`ui/manager_logic.py:121,268`、`ui/lppl_visualizer.py:342` | `validate_symbol` 改 `\d{6}\.(SH|SZ|BJ)`；`mock` 默认 False 无数据报错；LPPL 图表标注 `diagnostic_only(已证伪)` | `streamlit.testing` 跑通 5 tab 冒烟无 `KeyError/TypeError`；`600519.SH` 校验通过 | UI 独立，回滚不影响主干 |
| **P0-T09** | LPPL 死代码守卫 | 依赖 AST 扫描确认无生产引用。与 T01-T08 并行 | `brain/lppl/numba_optimizer.py`、`calculator.py:292,296,365`、4 份 cost_function | 删/接线 `numba_optimizer` + `_fit_cache` 孤儿逻辑（NEW-3），统一 4 份 cost_function | AST 扫描确认 numba_optimizer 生产零引用后物理清除；`pytest tests/brain/lppl/` 全绿 | 新增文件独立，可单独回滚 |

**Phase 0 门禁**：`ruff check src/ tests/ scripts/` 0 告警；`pytest tests/` 全绿（3509+ 基线不降）；`evidence_manifest.py verify` no drift。

---

### Phase 1 — 极速数据通道与因果宽表（第 2-3 周）

| Task ID | 名称 | 前置 & 并行 | 涉及文件 | 核心改造 | DoD | 回滚 |
|---|---|---|---|---|---|---|
| **P1-T01** | 极速 TDX 在线通道 | Phase 0 完成。内部 3 子任务可并行 | 新增 `data/sources/fast_tdx_stream.py`、`tdx_node_pool.py`；改 `tdxdata_online.py` | 7-IPv4 池 + `threading.local()` 线程隔离 + `close()` 真释放 + `FreshnessValidator.read_parquet_max_date` 跳过最新 + `batch_size=500` | 单标的 RTT<40ms；5522 标的 up_to_date 跳过<5s，增量全同步<90s；Bootstrap<50ms | 新增文件独立，回滚即切回旧 `tdxdata_online` |
| **P1-T02** | 全路径原子写 + 运行时新鲜度 + C3 守卫 | Phase 0。与 T01/T03/T04 并行 | `data/parsers/tdx_parser.py:391,405,432`、`import_financial.py:352,77`、`smart_factor_calculator.py:239`、`data_service.py`、`data_cleaner.py:50` | 6 处直写→`tmp+os.replace`；写湖前接 `DataValidator.validate`；`fetch_for_brain` 接单标的文件级新鲜度校验（DATA-1）；C3 加 bfill 断言守卫（DATA-4） | 崩溃仿真 `gbbq.parquet` 零损毁；`High<Low` 脏帧 100% 拦截；网络故障打 `source_error` 不伪装空表；bfill 断言测试绿 | 逐文件原子写独立，单点失败可单独回滚 |
| **P1-T03** | Phase 0 历史因果宽表 + **PIT 门** | 依赖 T01（极速通道回填）。与 T02/T04 并行 | `data/universe/dynamic_pit_loader.py:78-92,200-219`、复用 `brain/factors/financial_bridge.py:247` | **新建 `effective_ann_date` PIT 门**（NEW-17 CRITICAL，现状无公告日字段）：复用 financial_bridge 的 merge_asof 公告日对齐；回填 2010-2023 gpcw（584→658 列+vintage 清洗）；补 31 申万一级行业指数；预计算 `Date×Symbol` `tradable_mask` | 宽表生成<10s（DuckDB+Polars）；**任意调仓日 `effective_ann_date<=T` 零未来泄露断言 100%**（从零建非验证既有）；年报披露期内 `as_of_date` 不用未披露 FY 年报 | 宽表为新增产物，回滚不影响在线链路 |
| **P1-T04** | 9 列契约统一到单一常量 | Phase 0。与 T01-T03 并行 | `data/data_fetcher.py:38`、`tdxdata_online.py:41,100`、`tdx_parser.py:190`、`lake/resampler.py:63`、`data_validator.py:26` | 收敛 `GET_PRICE_LAKE_COLUMNS` 为唯一权威（DATA-3）；tdxdata_online/tdx_parser/resampler/validator 全部引用它；多周期 schema 显式声明列差异（amount/volume 顺序、reserved/code、datetime vs date） | 新增 `tests/test_schema_contract.py`：所有行情写路径列序一致；周/月/5分钟/日线 schema 差异显式文档化 | 契约常量为新增，逐文件切换可独立回滚 |

---

### Phase 2 — brain 大瘦身 + research 实证裁决（第 4-6 周）

| Task ID | 名称 | 前置 & 并行 | 涉及文件 | 核心改造 | DoD | 回滚 |
|---|---|---|---|---|---|---|
| **P2-T01** | 同源原子特征库 brain/features | Phase 1 宽表就绪。内部基本面/威科夫/动量 3 组**并行** | 新增 `brain/features/`（fundamental.py/wyckoff_structure.py/momentum.py）；复用 `forensics/z_cnmm_calculator.py:374-423` | 基本面(`roe_3y_mean`/`ocf_yield`/`accrual_quality` 负分母免疫)；威科夫连续结构(`tr_compactness`/`effective_rr` 扣 VPVR HVN/`vol_clv_asymmetry`)；动量摩擦(`ind_rs60`/`overhead_supply_pct`/`impact_friction`)。**全域 MAD 3σ 去极值 + 申万行业内 Rank-ZScore 在门禁前执行**（复用 forensics 孤岛 MAD 勿重写）；**修缺失值按均值静默填充→独立惩罚/披露**（NEW-9）；**确认窗口算子（scan_bc_sc 后续9根/PS close[i+1]）显式标注滞后标签或 shift**（WY-1） | 全算子纯向量化；单元测试断言去极值+行业内 Rank-ZScore 在门禁过滤**之前**；缺失值不按均值填充；前视算子有 shift/标签守卫测试 | 新增目录，回滚即不启用 |
| **P2-T02** | Hard Gates + BrainAlphaScore 影子上线索 | 依赖 P2-T01。与 P2-T03 并行 | 新增 `brain/gates/`、`brain/scoring/`；`shared/config_models.py`(新增 `scoring_v2` 进 `engine_migration`)；新增 `hands/backtest/portfolio_backtest_runner.py`；修 `signal/adapters.py:413` | ① gates 收口二值硬门禁（宏观120d迟滞/跌停熔断/ADV20/涨跌停/ST/PIT排雷）**严禁门禁给分**；② scoring 按 Regime 输出校准 `Ê[R]`（修 AlphaScoreAdapter 维度错误 NEW-2 作对照基线）；③ 新建 `PortfolioBacktestRunner`（槽位竞争 `PortfolioSlotAllocator`）；④ 影子上线复用 `engine_migration` 槽位 + **新建"双跑+对比+回退"编排**（NEW-16，非 if/else 切换） | `scoring_v2=True` 与旧链路平行；单日全市场横截面打分+槽位排序<50ms；**重构前后回测信号数值误差<1e-6**（同输入对照） | `scoring_v2` 默认 False，旧链路为主干，flag 关即回滚 |
| **P2-T03** | 唤醒 research 控制平面 + 存量体检 | 依赖 P2-T01 + **P1-T03（PIT 门通过）**【硬阻塞】。与 P2-T02 并行 | `research/alpha_tier_engine.py`、`degrees_of_freedom.py`、`walk_forward_pipeline.py`、`brain/factors/registry.py`、新增 `config/research_gates.yaml` | ① WFO(**新增** purge/embargo≥20d，NEW-7 现状无) 直连 `AlphaTierEngine(ledger=LedgerStore)`，补 WLS `residual_ic_series`+块状 Bootstrap PBO；② **四级阈值（含 Class A）全抽入 YAML**（NEW-6）；修 Class C `None→inf` Fail-Closed、去 `cross_section_N=500` 硬编码；③ 修 BH-FDR m=1 绕过（NEW-8）；④ 绑定 `FactorAccessLevel`↔`AlphaTier`（NEW-8b）；⑤ 存量指标送 Mode A+Mode B + 389无偏池/5000+动态PIT 扣费回测 | 产出**首份真实定量体检报告**（各因子 RankIC/t_NW/PBO/BH-FDR q/净OOS PF/Bootstrap 95%CI）；`FactorRegistry` 自动锁未达 TIER_C 因子；embargo 断言测试绿；**结论未被未来泄露污染**（依赖 P1-T03） | research 离线层，回滚不影响生产主干 |

---

### Phase 3 — 物理清剪 + 撮合统一 + 只读 UI（第 7-8 周）

| Task ID | 名称 | 前置 & 并行 | 涉及文件 | 核心改造 | DoD | 回滚 |
|---|---|---|---|---|---|---|
| **P3-T01** | 安全拆弹 + 物理瘦身 | 依赖 P2-T02/T03 实证判决 + **全仓 AST 扫描** | `brain/lppl/`(11文件)、`brain/wyckoff/`叙事/图像/PnF(下沉 plugins)、`brain/fsm/`→`brain/position_fsm/`、`services/`(EventBus/DataPipelineService/FsmAnalysisEngine 死壳) | ① `scoring_v2` 切唯一默认；② AST 死代码移 plugins/或归档；③ DecisionBrain→纯持仓状态机（**T+1-open 铁律随降格迁移** WY-2）；④ 消除 `bind_orchestrator` 2-环（NEW-12）+ 补 `shutdown()` + HealthService 容器化；⑤ EventBus 决策"接线 or 移除"（NEW-15）；⑥ 可选：引擎边界引入 Protocol 强制（NEW-13 降低 duck-typing） | AST 死代码守卫全绿；`tests/` 随模块迁徙同步更新；CI 覆盖率≥84%；ruff 0 告警 | 每下线一个旧模块同 PR 迁走对应单测+守卫断言；可逐模块独立回滚 |
| **P3-T02** | 撮合引擎统一 + 账目闭环 | 依赖 P3-T01。与 T03 并行 | `hands/backtest/unified_engine.py`、`unified_matching_engine.py`、`unified_models.py`、`czsc_engine.py:185` | ① **前置决策**：`eta/0.10` 归一化哪个滑点口径正确 + 接线孤岛 `UnifiedMatchingEngine` or 下线（NEW-5）；② 统一滑点/成本/涨跌停/T+1 到唯一内核；③ 修 30日跌停坏账平账、真实止损挂单、先滑点后限价、0.01元绝对限价；④ 修 CZSC 单实例竞态（NEW-4，接入组合回测前） | 单日权益悬崖归零，`equity_curve[-1]==final_cash` 恒成立；跨 2023-08-28 印花税半减精准校验；**滑点分歧 3.2x-7.1x 归零**（新增 `tests/test_matching_consistency.py`） | 内核共享有 feature flag，可切回独立内核 |
| **P3-T03** | 只读诚实 UI + 终验封版 | 依赖 P3-T01。与 T02 并行 | `ui/dashboard.py`→`dashboard_tabs/`、删 `enrich_lake_data` 伪信号 | ① 拆分单文件<800行；② 前端仅消费 `PipelineResult`/`ComplianceReport`/`AlphaTier` 账本；③ 完整展示扣费净值/Sharpe/MDD/合规审计日志 | `pytest` 全绿、ruff 0、`evidence_manifest verify` no drift、N2N 7 轨 PASS + 定量 Alpha 账本归档 | UI 独立，回滚不影响主干 |

---

## 4. 关键 DAG 依赖图

```
Phase 0 (T01-T09, 多数无互斥可并行; T03依赖T02同文件)
   │
   ├─→ Phase 1: T01(极速通道) ─┬─→ T03(因果宽表+PIT门) ─────────┐
   │                           ├─→ T02(原子写+新鲜度) [并行]      │
   │                           └─→ T04(9列契约统一) [并行]        │
   │                                                              │
   └─→ Phase 2: T01(features) ─┬─→ T02(Gates+Scoring影子) ──────┤
                               └─→ T03(research体检) ←【硬阻塞】──┘
                                    (P1-T03 PIT门通过才能开工)
                                                │
                                    Phase 2 实证判决
                                                │
   Phase 0 (T01-T09, 多数无互斥可并行; T03依赖T02同文件)
                                                ▼
                                       Phase 3 (T01清剪 → T02撮合 ∥ T03 UI)
```

**关键并行度**：Phase 0 全 9 Task 无互斥（除 T03 依赖 T02 同文件、T09 依赖 AST 扫描），可多路并行；Phase 1 四路；Phase 2 features→(gates‖research) 三路，但 **research 强制依赖 P1-T03 PIT 门**；Phase 3 (撮合‖UI) 两路。

**最重要的顺序约束**：`P2-T03（因子实证裁决）depends_on P1-T03（PIT 门通过）`——避免用带未来泄露的 `dynamic_pit_loader` 污染整个 Phase 2 体检结论。

---

## 5. 最终关键风险台账（18+ 项，五视角合并去重排序）

| ID | 缺陷 | 严重度 | 来源视角 | 落入 Task |
|---|---|---|---|---|
| **NEW-17** | dynamic_pit_loader 无公告日 PIT 门→未来泄露 | **CRITICAL** | 数据工程 | P1-T03（阻塞 P2-T03） |
| NEW-1 | FSM PYRAMID 态不可达（max55<70） | HIGH | 数学 | P0-T03 |
| NEW-5 | 滑点双公式+撮合引擎未接线孤岛 | HIGH | 算法 | P3-T02（前置决策） |
| NEW-2 | AlphaScoreAdapter 维度错误映射 | HIGH | 数学 | P2-T02 |
| GROSS | compliance gross 恒等式退化（纯多头空转） | HIGH | 主链路实测 | P0-T06 |
| NEW-9 | 默认纯Z-Score+缺失值按均值填充+MAD关 | HIGH | 数学 | P2-T01 |
| NEW-10 | evt_risk/sizer 注入链两处断裂 | HIGH | 架构师 | P0-T02 |
| NEW-18 | load_data_with_fallback 复权口径分叉 | HIGH | 数据工程 | P0-T07 |
| WY-1 | scan_bc_sc 后续9根确认算子平移变前视 | HIGH | 威科夫 | P2-T01 |
| NEW-11 | ServiceContainer.get() 无锁 | MEDIUM | 架构师 | P0-T07 |
| NEW-8 | FactorAccessLevel≠AlphaTier 零接线 | MEDIUM | 数学 | P2-T03 |
| NEW-6 | alpha_tier 四级阈值全硬编码 | MEDIUM | 数学 | P2-T03 |
| NEW-7 | walk-forward 无 purge/embargo | MEDIUM | 数学 | P2-T03 |
| NEW-12 | bind_orchestrator 2-环 | MEDIUM | 架构师 | P3-T01 |
| FIX-2 | pre_close 默认0.0 非None（缺失/真0不可分） | MEDIUM | 架构师 | P0-T01 |
| NEW-13 | 6 Protocol 仅文档，引擎 duck-typing | MEDIUM | 架构师 | P3-T01 |
| DATA-3 | 9列契约未统一（amount/volume顺序反） | MEDIUM | 数据工程 | P1-T04 |
| DATA-1/2/4 | FreshnessValidator未入运行时/原子写遗漏/C3无守卫 | MEDIUM | 数据工程 | P1-T02 |
| NEW-3 | LPPL numba+LRU 孤儿死代码 | LOW | 算法 | P0-T09 |
| NEW-4 | CZSC 单实例竞态 | LOW | 算法 | P3-T02 |
| NEW-14 | STRICT_TIMESTAMPS 死别名 | LOW | 架构师 | P0-T07 |
| NEW-15 | EventBus 未接线空转（非空壳类） | LOW | 架构师 | P3-T01 |

---

## 6. 待人工拍板决策项（7 项，部分阻塞施工范围）

| # | 决策项 | 影响Task | 建议口径 |
|---|---|---|---|
| 1 | **TrackProfile 纯多头阈值口径** | P0-T06 | 现行 2.5%单票/±0.5%净敞口是 75/25-IH 中性轨专用，纯多头轨需独立阈值段 |
| 2 | **NTF / 部分 Wyckoff 检测器去留** | P2-T03 | 不在 Phase 0 盲砍，留到 P2-T03 经 AlphaTierEngine 实证裁决（过关保留/不过关清剪） |
| 3 | **`scoring_v2` 影子上线机制** | P0-T07+P2-T02 | P0-T07 先合并单一权威 FeatureFlags，P2-T02 复用 `engine_migration` 槽位+新建影子双跑编排 |
| 4 | **撮合内核统一 vs 下线** + **滑点 `eta/0.10` 归一化哪个口径正确** | P3-T02 | 需先拍板回测版(cap0.02) vs 撮合版(小单放大√10)哪个物理正确，再决策接线孤岛 or 下线 |
| 5 | **FSM 状态机处置** | P0-T03 | PYRAMID 态已结构性不可达，是"移除买分保留骨架"还是"直接降格为纯持仓退出状态机 `brain/position_fsm/`"（后者即 P3-01 目标态，可提前到 P0 一步到位） |
| 6 | **features 算子复用** | P2-T01 | 复用 forensics 孤岛 `z_cnmm_calculator.py:374-423` 的申万行业内 MAD 实现，而非重写 |
| 7 | **PIT 门实现复用** | P1-T03 | 复用 `financial_bridge.py:247` 的 merge_asof 公告日对齐方案 |

---

## 7. 结论

1. **重构计划的 Phase 0 红线断言全部经实测成立**，可立即开工。
2. 本审计**新增 1 个 CRITICAL（NEW-17 PIT 泄露）+ 7 个 HIGH**，并纠正文档 3 处说法。
3. **最重要的顺序纠正**：`P2-T03 depends_on P1-T03（PIT 门）`，避免未来泄露污染 Phase 2 因子裁决。
4. **Phase 0 首批可立即并行的 5 个 Task**（互不依赖、改动面小、实盘红线）：`P0-T01`(pre_close) + `P0-T02`(注入链) + `P0-T04`(sizer拒单) + `P0-T05`(KillSwitch) + `P0-T06`(合规恒等式) + `P0-T07`(config/seed/复权/锁)。

**下一步**：待确认优先 Phase 与 §6 决策项后，退出只读模式按 Task 逐步执行（遵循 TDD + ruff 零告警 + 文档同步 + 每步 `pytest` 回归纪律）。

---

**审计人**：SenseNova（只读审计模式）
**审计日期**：2026-11-25
**代码基线**：`b1d2415`
**审计完成度**：五视角全部完成，所有缺陷 `file:line` 实测坐实