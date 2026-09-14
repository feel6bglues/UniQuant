# UniQuant 全栈实证分析报告

> **生成日期**: 2026-09-14
> **方法**: 8 路并行 subagent 实证审计 + 编排层一手复核（零幻觉门：所有量化声明均绑定实测命令输出与 `file:line`）
> **审计边界**: 只读，未修改任何文件
> **分析基线**: commit `47cb51b`，工作树干净，8 层 import 冒烟通过

---

## 1. 执行摘要

UniQuant 是一个**代码完备但信号链在默认配置下整体断开**的 A 股量化研究平台。258 个源文件 / 63,148 LOC，8 层架构（shared→data→brain→signal→hands→risk→services→ui），6 个分析引擎，39 个注册因子，165 个测试文件 / 2,154 个测试函数（**2348 passed / 8 skipped / 0 failed**），A 股规则七道防线全部实现。

**三个最重要发现（均由编排层一手复核确认）**：

1. **PBO 门被构造性证伪** — `five_gate.block_bootstrap_pbo` 在 n_windows=17 时是"峰值窗口位置"的确定性函数，与被测因子数值完全无关。实测映射：peak@win0-2→0.1655、win3-5→0.307、win6-8→0.4195、win9-11→0.5325、win12-14→0.6165、win15-16→0.6695。零假设 N(0,0.02)、真 alpha N(0.0558,0.0289)、负 alpha N(−0.03,0.01) 三种数据生成过程输出**完全相同**（meanPBO=0.4141，P(<0.2)=0.245）。常量数组（无信号）→ PBO=**1.0000**。这不是"偏严的筛选器"，而是"不含任何推断内容的计数函数"。

2. **默认配置下生产管线产出 0 个 TradingSignal** — `ResearchDataPack.to_dict()`（`interfaces.py:214-230`）将 `metadata` 作为嵌套键返回而非展平，`research_pipeline.py:573` 只调用 `to_dict()` 未补展平 → 8 个信号适配器中 **7 个恒不触发**（LPPL/CZSC/Wyckoff/NTF/AlphaScore/MAStatus/Regime），仅 FSMAdapter 存活。

3. **项目级结论"因子挖掘正式终结"不成立** — 将失效的 PBO 门作废后，仅凭产物中已存在的布尔字段重算 `passed_ic ∧ passed_icir ∧ correct_sign ∧ passed_mom`，**17 个唯一因子同时通过其余四门**（含 AGENTS.md 断言"完全由动量驱动"的 max_ret_20d、max_drawdown_20d、sp_ttm、cfp_ttm——它们在产物中 `passed_mom=True`）。

**可交易性裁决**：H-A 条件 illiq 主线结论**不受 PBO 影响**（组合层回测不经五门），维持可交易但容量受限（≈2850 万元级）。但 D+13 的"全市场 −2.46%/−51.16%"**无任何产物支撑**，且现存产物方向相反（+12.55%）。

---

## 2. 项目作用与实现方式

### 2.1 定位

A 股量化研究与交易分析平台，覆盖数据采集 → 数据湖 → 多引擎分析 → 信号生成 → 回测撮合 → 风控 → 服务编排 → UI 的完整链路。研究侧以预注册纪律驱动因子证伪（P1–P15 共 15 轮），工程侧以 A 股铁律（涨跌停/T+1/lot/成本）约束回测。

### 2.2 架构实现

```
shared  (48 files / 7,613 LOC)   协议、常量、配置、A 股规则、成本、时间提供器
data    (67 files / 15,315 LOC)  8 数据源路由、数据湖、管线、校验
brain   (56 files / 18,017 LOC)  6 引擎: Wyckoff/LPPL/CZSC/NTF/FSM/regime + 因子系统 + screener
signal  (8 files  / 2,777 LOC)   TradingSignal 模型、8 适配器、仲裁器、归一化
hands   (33 files / 6,090 LOC)   统一回测引擎、向量化撮合引擎、策略框架
risk    (6 files  / 1,640 LOC)   仓位、回撤、EVT、结构风险、组合优化
services(31 files / 8,295 LOC)   DI 容器、分析编排、扫描、健康、研究管线
ui      (8 files  / 3,400 LOC)   Streamlit dashboard、健康检查
────────────────────────────────
合计 258 files / 63,148 LOC
```

### 2.3 控制流（grep 实证，非文档转述）

```
ServiceContainer.initialize()                    service_container.py:77
 ├─ 12 注册键（analysis/arbitrator/backtest/cache/calendar/data/
 │   engine_factory/market_cache/pipeline/collector/storage/time）
 ├─ FeatureFlag: signal_arbitration=true → SignalArbitrator
 └─ FeatureFlag: factor_gate="block" → FactorRegistry.set_mode(BLOCK)  ← 进程级类单例

UnifiedResearchPipeline.run(symbol)              research_pipeline.py:273
 └─ AnalysisService.run_ticker_analysis          analysis_service_v2.py:263
     ├─ data_service.fetch_research_pack()       [use_research_data_pack=true]
     ├─ _run_engines: regime→lppl→ntf→czsc→wyckoff→alpha→derived
     │    ⚠ 7 处 EngineCompleted publish 全部因 event_bus=None 跳过
     └─ _make_decision → MarketSignalContext + DecisionBrain  ✓ (有展平)
 └─ _merge_decision_for_collection               research_pipeline.py:573
     ⚠ 仅 to_dict()，metadata 未展平            ← 信号链断点
 └─ TradingSignalCollector.collect()             adapters.py:497
     8 适配器：7 个因缺顶层键恒不触发，1 个存活
 └─ arbitrator.arbitrate_candidates              仅保留 BUY/SELL（HOLD 丢弃）
 └─ UnifiedBacktestEngine.run(signals=[])         ← 空信号回测
```

### 2.4 数据底座

| 目录 | 文件数 | 大小 | 口径 |
|---|---:|---:|---|
| `data/lake/quotes/daily` | 5,755 | 805M | TDX 日线，含 554 指数 |
| `data/lake/financial` | 5,211 | 2.4G | TDX 季度归档 42 期 × 577 列 |
| `data/lake/dividend` | 5,123 | 21M | TDX xdxr 真实派现 1990-2026 |

**PIT 正确性：6 项通过 + 2 项存疑**。茅台锚点一手复核：EPS_TTM@FY2024 实测 `68.63999938964844` = 期望 68.64 ✓（双口径 TTM 差分+滚动逻辑正确，跨年 Q1 正确重置）。

---

## 3. 八轴实证发现

### 轴 A — 架构与运行时流

| # | 声明 | 证据 | 判定 | 严重度 |
|---|---|---|---|---|
| F1 | RDP 模式不展平 metadata，与 `_make_decision` 不对称 | `interfaces.py:214-230` / `research_pipeline.py:573` vs `analysis_service_v2.py:616-619` 有 `dict_pack.update(metadata)` | ✗ | **P0** |
| F2 | 8 适配器中 7 个恒不触发 | 探针实测 NOT CALLED；仅 FSMAdapter→HOLD；RegimeAdapter 因 `regime == "FROZEN"` 类型失配恒 None | ✗ | **P0** |
| F3 | arbitrator 开启即清空 HOLD 并硬否决 | `research_pipeline.py:249-262` / `arbitrator.py:286-290,306-312` | ✗ | **P0** |
| F4 | EventBus 生产零实例化 → 全链事件死代码 | `grep "EventBus(" src/` 仅类定义；`service_container.py:175-183` 未传 | ✗ | P1 |
| F5 | `config.yaml:481 event_bus:true` 完全无效 | `FeatureFlags.event_bus` 解析后无读取点 | ✗ | P1 |
| F6 | 引擎状态仅记 regime/lppl，czsc/wyckoff/alpha 失败不可见 | `mark_engine_status` 仅 6 处调用点 | ✗ | P1 |
| F7 | FSM `critical_engines` 含 macro 但 macro 从不运行 → veto 恒空转 | `fsm.py:262` vs `analysis_service_v2.py:351-399` | ✗ | P1 |
| F8 | `data/lake/index/000300.SH.parquet` 缺失 → 全市场级联零信号（静默） | `storage_manager.py:580-583` 解析到空目录；真实文件在 quotes/daily/；空 df → UNKNOWN 并被 `market_cache.py:72-79` sticky 缓存当日 | ✗ | **P1** |
| F9 | 分层契约：违规仅 2 处 | `shared/config_validator.py:116`、`shared/di_container.py:13`（自声明 DEPRECATED） | ⚠ | P2 |
| F10 | 28 死配置键 + 14 死叶子键 | `multi_period.*` 24 个（grep=0 文件）；`wyckoff.stoploss_guard_*` 3 个 | ✗ | P2 |
| F11 | 死岛链：`signal/quality.py`、`normalizer→aggregator→signal_integrator` | `signal/__init__.py` 不导入 quality | ✗ | P1 |
| F12 | 裸 except = **0**（全 src）；services 层 except Exception = 19 | grep 实测 | ✓ | — |

**死代码定量（静态可达性）**：31 个模块 / **7,379 LOC** 完全无 import；66 个模块 / 16,661 LOC（占 26.4%）无测试引用；`shared/optimal_params.py`(349) + `param_validator.py`(112) = **461 LOC 自认死链**（源码注释自证）。

### 轴 B — 数据层与 PIT 正确性

| 风险项 | 证据 | 判定 | 严重度 |
|---|---|---|---|
| 双口径 TTM（累计 YTD vs 单季） | `financial_bridge.py:87-94,308-322`；茅台锚点 68.64 实测一致 | ✓ | — |
| 公告日优先 merge_asof（backward） | `:213-238,408-415`；尾日不可见未生效年报有测试锁证 `test_factor_mining_data_loader.py:149-172` | ✓ | — |
| 指数混入股票池 | `storage_manager.py:18-36`；614×"000xxx"=200 SH 指数+414 SZ 主板股，**0 误判** | ✓ | — |
| **复权状态不可程序化确认** | 日线列仅 `[date,open,high,low,close,amount,volume,reserved,code]`——**无 adjustflag、无 qfq_close**；`_resolve_price_col` 静默 fallback 到 close；实测 000001.SZ 1991 close=49.0 vs 2026 close=11.08 **倒挂**，与 qfq 期望矛盾 | ⚠ | **高** |
| 幸存者偏置不可量化 | `all_stock_codes.csv` outDate **全 NULL**（7579 行） | ⚠ | 中 |
| DataValidator 修复失效 | `data_validator.py:13 df=df.copy()` 后在副本上"修复"，`:82 return True`；`tdx_updater.py:297,391` 只用布尔门，随后 `save_data(symbol, df_clean)` **保存原帧** → High<Low 修复**从未生效** | ✗ | **高** |
| 校验器只告警不阻断 | `amount<=0`、`\|pct_change\|>0.99`、间隔>14d 全 `logger.warning` 仍 return True | ✗ | 高 |
| 列裁剪缺失 | `storage_manager.py:152` `read_parquet` 无 `columns=`；2.4G financial 每文件读全 577 列，**实际仅用 ~25 列（浪费 ~95% I/O）** | ✗ | 中 |

### 轴 C — 6 脑引擎正确性与实证

| 引擎 | LOC | 最长方法 | 圈复杂度峰 | 实证支撑 | 判定 |
|---|---:|---|---:|---|---|
| wyckoff/engine | 2262 | `_build_report` 293 行 | `_step5_trading_plan` **cc=76** | 5 窗 T1 n_buy 86/27/69/174/123 精确一致；fwd20 超额 **2 胜 3 负**（+3.78/−5.96/−1.30/+4.12/−1.15pp） | 代码正确，**无 alpha** |
| lppl/engine | 1107 | `fit_single_window_lbfgsb` 114 行 | 19 | 200 股 OOS R² **87% 为负**（中位 −6.84，min −352.7）；is_bubble **0/200** | **有正确性缺陷** |
| fsm/fsm | 766 | `make_decision` 112 行 | 17 | 无前瞻验证 | 可用，**1 条 veto 死** |
| lppl/calculator | 665 | `fit` 156 行 | 16 | 同上 | **风险分级无质量门** |
| czsc | 634 | 81 行 | 14 | 三买触发率 4.1% | 薄封装，**2 条死分支** |
| regime | 283 | `detect` 60 行 | 11 | 无前瞻验证 | **fail-open 部分失效** |

**代码级缺陷（按严重度）**：

- **严重** `lppl/calculator.py:426-433` `_determine_risk_level(days_to_tc)` 仅看 tc 天数，**无 R²/validate_model 门** → 200 股样本 32.5% 判 Danger 并发 SELL，而 87% OOS R² 为负。对比 `engine.py:396` 有门但生产路径不用它。
- **严重** `indicators.py:214` `calc_turnover_z` 末尾 `z_score.fillna(0)` → `regime_detector.py:171-175` 的 `np.isnan` 防线**恒不触发**（实测全 NaN 成交量 → z=0.0）。
- **高** `regime_detector.py:158-165` `e_pct` 是 60 日窗内 **min-max 位置而非分位数**；熵序列平坦时 min==max → e_pct=0.0 → **FROZEN**（docstring 称 "sliding window percentile" 名不副实）。
- **高** `lppl/engine.py:333-352` 10 次重启**不检查 `res.success`**；实测收敛率 88.3%，未收敛结果可被采纳。
- **中** `czsc_engine.py:211` `CZSC(bars)` 未传 `signals=` → `analyzer.signals` 恒 `{}` → 三买兜底永不执行。

**一手复核（3 股 × 900 日，双次运行逐位一致，确定性 PASS）**：000001.SZ Wyckoff=MARKUP/空仓观望/59.03 + LPPL R²=0.4884/OOS −7.19；600519.SH ACCUMULATION/空仓观望/63.67 + LPPL R²=0.8026/Danger/days_to_tc=0.023/OOS −3.97；300750.SZ ACCUMULATION/64.64 + LPPL R²=0.8190/Safe/OOS −14.01。**LPPL 内部自相矛盾**：600519 `detect_bubble`→is_bubble=False，但 `scan_all_windows`→is_danger=True。

**结论**：6 引擎中**无任何一个通过前瞻验证获得可确认 alpha**。

### 轴 D — 因子研究管线与统计方法论（本次分析最重要轴）

| 门 | 实现 | 统计学判定 | 严重度 |
|---|---|---|---|
| G_IC `\|IC\|>0.01` | 绝对阈值 | 有效但不等尺度：零假设通过率随 `oos_ic_std` 从 **3%（accruals）摆到 77%（momentum_60d）**，家族内 FWER 不均 | 中 |
| G_ICIR `\|ICIR\|>0.5` | mean/std @17 窗 | **真正的判别门**：零假设通过率 6.5% | 低 |
| G_PBO `<0.2` | 块自助 | **❌ 无效估计量**（见下） | **严重** |
| G_MOM rank-OLS | `np.cov(ff_r,mv)[0,1]/mv.var()` | 正确且稳健（rank-OLS=对秩的 OLS=Spearman 偏相关；对 illiq_20d raw-OLS 的 beta 符号会翻转 +0.055 vs −1.08，rank 版是正确选择） | 低 |

**PBO 退化的一手复核（编排层实跑，200 样本/情景）**：

```
峰值位置 → PBO 映射（确定性）：
  win 0-2 → 0.1655   win 3-5 → 0.307    win 6-8 → 0.4195
  win 9-11→ 0.5325   win 12-14→0.6165   win 15-16→0.6695

数据生成过程 → 输出（三者完全相同）：
  零假设 N(0,0.02)            meanPBO=0.4141  P(<0.2)=0.245
  真 alpha N(0.0558,0.0289)  meanPBO=0.4141  P(<0.2)=0.245
  负 alpha N(-0.03,0.01)     meanPBO=0.4141  P(<0.2)=0.245
  常量 0.05（完美稳定因子）   meanPBO=1.0000  P(<0.2)=0.000
```

根因：`RandomState(42)` 每次调用内重置，块抽样序列跨因子完全相同；`arr[best_idx]` 既是重采样源的极值又是判定阈值，`block_size=n/5=3` 的块几乎必然被抽回，`boot[:best_idx+1]` 前缀极值几乎恒 ≥ 阈值 → 计数退化为对位置的计数。**这不是 Bailey–López de Prado 意义上的 PBO**（后者需遍历参数网格/候选集的最大化统计量）。

**后果**：AGENTS.md 的措辞"PBO 淘汰 ≠ 因子无效"方向正确但**严重低估**——更准确的表述是"PBO 未执行任何检验"。同时 **bp 的 PBO=0.166 必须从证据基础中剔除**：它证明的是"bp 最强窗在最前面"（alpha 前置），这是稳健性**担忧**而非支持。bp 的真实证据只剩 ICIR=1.93（t=7.97, p=5.8e-7，低于家族规模 39 的 Bonferroni 阈值 1.28e-3）与动量残差门，两者均独立成立。

**顺带证伪另一条叙述**：AGENTS.md 称 PBO"系统性偏向时序平稳型因子"。实测相反——PBO 奖励**位置靠前**的因子，对尖峰型与平稳型的通过率都在 15% 附近，**不存在"偏向平稳型"**。

**fwd5 修正完备性**：`correct_fwd5` 全仓采纳，`pct_change(-5).shift(-5)` 活代码残留 **0**。

**多因子冗余**：`range_20d` vs `neg_range_20d` rho=**−1.000**（构造性符号翻转，在多重检验预算中重复计数）；`illiq_20d = mean(\|r\|/amt)` 与 `amivest_20d = mean(amt/\|r\|)` 逐日行级**数学互逆**（全面板 rho=−0.406，个股内 ≈−1）却作为两个独立因子同进复合评分。有效独立维度约 **18，非 39**。

**GP 挖掘**：0/25 幸存是**混杂结果，非干净否定**——25 候选实为 **3 个唯一公式**（`vwap`×13、`(vwap add rsi_14)`×7、`(rsi_14 add vwap)`×5），深度仅 {1,2} vs `max_depth=5`，fitness 跨度 4.4%；末端集仅 7 个价量原语，**无流动性/估值/财务通道** → 动量吸引子由架构保证。冠军 `(rsi_14 add vwap)` OOS IC=**−0.0683（负值）**。唯一诚实发现：4000 个体在纯噪声下 max\|ICIR\| 期望 ≈1.09，GP 最佳 ≈1.78，**GP 未过拟合**（这一点是真的）。

### 轴 E — 信号链→回测→撮合 + A 股规则

| 防线 | 实现位置 | 判定 |
|---|---|---|
| ① 涨跌停 | `market.py:79-85` + `board_registry.py:27-31` + `unified_engine.py:546-573`；688/300→20% ✓ | ⚠ **ST 股无 name 参数时退化为主板 10%**（两个引擎均受影响） |
| ② T+1 | `unified_engine.py:517-531` + `unified_matching_engine.py:246-261` | ✓ |
| ③ 成本 | `cost_model.py:29-34`（万三佣金/万五印花/万0.1过户/最低5元）；沪收深免两边一致 | ✓ |
| ④ lot 取整 | `unified_engine.py:657-658` 读 board rule；**vectorized 硬编码 100** → 科创板 200 股被忽略 | ⚠ |
| ⑤ 滑点 | `unified_engine.py:595-620` 用订单量 ✓；**`unified_matching_engine.py:75-79` 用日总成交量** | ⚠ **HIGH** |
| ⑥ 涨停拒买 | 研究层 + 引擎层双重拦截 | ✓ |
| ⑦ price_collar | 零生产调用（grep 确认） | ⚠ 死代码 |

**死代码验证**：`DynamicSlippage`（`slippage_model.py:23`）生产调用者 **0**；`price_collar` from/import **0 匹配**。

**研究口径 vs 生产口径差距（+15.34% → +7.43%）的机制来源**：研究口径 `mean(日收益)` 公式隐含"每日免费等权重置"**幻影收益**——每只股票按 1/30 权重贡献日收益，但实际资金只在 30 只中分配，换股时需卖出回笼→买入新名，资金流转有滑点和时序损失。生产引擎的 slot 级复利消除了线性近似。

**测试实测**：`test_limit_checker` 30 passed / `test_cost_model` 19 / `test_matching_engine` 14 / `test_t1_constraint_boundary` 10 = **73 passed, 0 failed**（`test_unified_matching.py` 超时未完成）。

### 轴 F — 工程健康度 / 数据结构与算法性能

**测试（一手实跑）**：

| 指标 | 实测值 | 判定 |
|---|---|---|
| 全量测试 | **2348 passed / 8 skipped / 0 failed**（1068s，206 warnings） | ✓ |
| 测试文件 / 函数 | 165 / 2,154（AGENTS 记 144 / 1,934 → 漂移 +21/+220） | ⚠ |
| 断言密度 | 4,523 assert，**2.10 asserts/test**，零 assert 文件 **0** | ✓ |
| ruff | src/ **0**、tests/ **0**、scripts/ **18**（全在 `wyckoff_multitf/v9_*`：F841×6/E401×6/F541×2/F401×2/E701×2） | ⚠ **CI lint 当前为红** |
| FactorRegistry 隔离缺陷 | teardown `_factors.clear()`+`register_all()` 已到位 | ✓ 声明属实 |
| 覆盖率 | `--cov-fail-under=50` 被 CI 继承；**全量 `--cov` 在 39% 处确定性挂死**（两次 exit 124，RSS 3GB），二分后定位到顺序依赖型；AGENTS 的 57.88% **不可复现** | ✗ |

**测试注水（关键）**：`tests/hands/strategies/test_strategy_boundaries.py` 13 个测试形如 `s.next()  # no crash on empty state`——**无断言、只验证"不崩溃"、且测的是 mock 替身**（`HAS_BACKTRADER=False`）。`hands/strategies/` 1,629 LOC 真实策略逻辑**实际 0 行为覆盖**。

**8 个 skip 逐条归因**：5 个守卫不存在的脚本；2 个因 backtrader 未装；**1 个掩盖 `stats.erf` 真 bug**（`test_backtest_advanced.py:113`）；**1 个掩盖生产 bug**（`test_e2e_integration_qa.py:603` `AssertionError: assert 'overall_status' in {...}` 被 skip）。

**沉默吞异常**：src/ 中 `except Exception:` 共 **34 处，其中 32 处无 `as e`**（AGENTS 记的"231"是 34 沉默 + 202 已处理混计）。最危险：`hands/backtest/engine.py:542` 的裸 `except Exception: pass` **吞掉了 `stats.erf` AttributeError** → 任何有回撤的回测**静默丢失 overfitting 指标与 Monte Carlo 元数据**（而 `overfitting_metrics` 字段全仓 **0 读取**，是死字段）。

**性能热点（一手实测计时，50 只 × 500 天合成数据）**：

| 路径 | 实测耗时 | 判定 |
|---|---|---|
| `analyzer.compute_ic_ir` 向量化 | **218.83 ms** | ✓ 优化生效 |
| `compute_pv_divergence_20d` sliding_window_view | **54.80 ms**（1.11 ms/只） | ✓ 生效 |
| `composer.compute_all_factors` | **3,876.79 ms** — Python for-loop 遍历 39 因子 × groupby | ⚠ 瓶颈=Python 循环 |
| `five_gate.daily_ic_series` | **876.80 ms**（逐日 np.cov） | ❌ 热点，17 窗×500 股将达数十分钟 |
| `pnf.PointAndFigure.build` | **468.14 ms** | ❌ **600602.SH 产 33.3 万箱**（全局步长 step 占高价段 0.003%） |

**数值正确性缺陷**：`five_gate.py:63` `np.cov(ff_r,mv)` 默认 ddof=1 vs `mv.var()` 默认 ddof=0 **不一致** → beta 偏差 n=20 **+5.26%** / n=50 +2.04% / n=500 +0.20%。影响小截面的动量残差门判定。

**并行正确性**：`wyckoff_full_scan.py:286` 为 ProcessPoolExecutor + 每进程独立引擎 ✓（消除 `_code_prefix` 竞态）；`data_loader.merge_financial_metrics:185` 与 `scan_service.py:299` 用 ThreadPoolExecutor 跑 CPU 密集的 `bridge.process` ⚠（GIL 限制，应改进程池）。GP `_subtree_crossover` deepcopy 修复到位（3000 次 0 泄漏）✓。

**NaN 传播**：全仓 `fillna(0)` **69 处**；`composer.py` **0 处**（AGENTS 声称的 3 处删除属实）✓；但 `indicators.py:214` 的 `z_score.fillna(0)` 使 regime fail-open 防线恒不触发（见轴 C）。

**安全**：无硬编码密钥（`config.yaml` 仅 `client_key: null`）；`signal/db.py` 纯 ORM 零原始 SQL，无注入面 ✓；`connect.cfg` **被 git 追踪且未入 .gitignore**，但检索确认凭据全空（`savepass=0`、`ProxyUser=`、`HKey_KeyString=`）⚠；`error_handling.py:112` `func_args: str(args[:2])` **未脱敏** → 位置参数中的密钥会明文入日志 ⚠。

**依赖治理**：**20 个依赖无上界**；实装漂移 numpy `>=2.0.0`→**2.4.6**、plotly `>=5.0.0`→**6.7.0（跨大版本）**、streamlit→**1.57.0**；**无 lock 文件** → CI 与本地可解析到不同版本。CI 无 mypy（尽管有配置）、无 SAST/密钥扫描（无 gitleaks）、**无 pytest-timeout 看门狗**。

### 轴 G — 研究资产一致性（文档 vs 仓库漂移）

**总判定：漂移严重程度 = 高（结构性）**。19 项关键声明核对中 11 项不符，**其中 3 项是真实错误而非过期快照**（归档死代码、指数归档、/tmp 备份路径均不存在于文件系统与 git 历史）。

| 声明 | 实际 | 类型 |
|---|---|---|
| `custom_factors.py (311 LOC, 13 因子)` | **988 LOC / 39 因子** | **真实错误** |
| `Archived files 6 (2,217 LOC)` | **0 个；`archive/` 目录不存在**；`git log --all -- "*archive*"` 空 | **真实错误**（死代码是**删除**而非归档） |
| `analysis_service_legacy.py (1,651 LOC)` / `factor_governance.py` / `portfolio_engine.py` | 文件不存在，git 历史显示 `2e420f9` 已删除 | **真实错误**（导航表指向不存在文件） |
| `归档 552 个指数文件到 archive_index/` | **目录不存在**；200×000xxx.SH + 354×399xxx.SZ 仍在 `daily/` 根目录（靠 `_is_index` 代码级过滤） | **自相矛盾** |
| 4 处 `/tmp/opencode/wyckoff_fix/old_scans*` 备份 | **目录不存在** → 旧产物不可回溯 | **真实错误** |
| `Test coverage 57.88%` | 实测 21.91%（`FAIL Required 50% not reached`） | **真实错误** |
| `P3 通过四重门 2 个`（max_ret_20d PBO=0.166） | 产物 `logic_factor_test.json`：`n_passed_pbo=0, n_passed_all=0`，PBO=0.307/0.4195，ICIR 由 −11.50/−6.54 变为 **−2.91/−1.60** | **真实错误（产物被覆盖）** |
| `负 IC 完全由动量驱动` / `深跌反弹=纯动量 beta` | 产物中 max_ret_20d `mom_ok=True res=+0.0598`、max_drawdown_20d `res=+0.0473`、sp_ttm `res=+0.0388`、cfp_ttm `res=+0.0255`、bp `res=+0.0502` **全为 True** | **真实错误（最高影响）** |
| `P11 0/7 幸存` | 产物 `n_passed_all=1`（bp） | 自相矛盾 |
| `P12 cvar_95_60d ICIR 4.0`、`max_drawdown_20d PBO=0.166 唯一达标` | ICIR **1.3163**、PBO **0.4195**（`pbo_ok=False`）；PBO 达标者实为 kurtosis_20d / inst_shares_chg_1q | **真实错误** |
| `P15 §5.1 组合层 9/12 数值` | 产物不符（STRAT-A +9.52%→**+8.91%**、CTRL-B −26.84%→**−38.33%**、Q3 +0.19→**+0.311**）；文档 18:04 / AGENTS 18:05 / **JSON 18:08** | **真实错误（文档先于产物写入）** |
| `P13 D+13 全市场 −2.46%/−0.04/−51.16%` | **全库检索 0 命中**；现存产物 `ha_unified_adapter.json` scaled_30 = **+12.55%/1.1226/−20.10%（方向相反）** | **真实错误 + 不可追溯（最高影响）** |
| `bp ICIR 1.93 全场最高` | 同文件 idiosyncratic_vol_20d ICIR=**2.2974** 更高 | **真实错误** |
| `bp 17 窗全正，首窗 0.120` | **逐窗 IC 序列未存档**（`composite` 字段为 `null`），仅能由 PBO 反推 argmax 位置 | **不可追溯** |
| `except Exception total 231` / `252 文件` | 236 / 258 | 过期 |

**追溯性良好的部分（证明漂移非普遍）**：P1 基线 14 项逐值全对；P2 GP `0/25`/门槛 0.0746/gate 分布 0/0/0/25/3 个唯一公式全对；P7 H-A 四门全值全对；P8 三臂 11/11 一致；P9 三因子全对；P10 全对；P14 三因子全对 + T5 spearman 0.7916；P5 全对；P15 §5.2 全对；Wyckoff 5 窗 CSV 5201 行×39 列 + T1 n_buy 86/27/69/174/123 **精确一致、SELL 5/5 窗恒 0**。

**测试保障缺口（根因）**：`tests/` 中**无任何测试覆盖 `block_bootstrap_pbo`**（唯一提及 PBO 的 `test_backtest_advanced.py:132` 属另一实现）。该退化函数在 4 个研究脚本 + 1 个 CANSLIM 脚本中被复用 6 处，零测试即静默穿透。

**文档架构**：`docs/` 7.5MB / **396 个 .md**；`results/` 13MB / 135 个 JSON / 25 目录；孤儿产物 7 个（`h_a_signals`/`wyckoff_asof`/`wyckoff_asof_golden` 各 0 篇文档引用；`h_a_reconcile/` **空目录**却声明为产物目录）；仅 5 篇 docs 引用 `results/factor_mining`；`docs/index.md` 陈旧 7 周；README 仍写"🚧 重构中 | 规模 ~50K LOC（目标）"。

---

## 4. 结论翻转风险评估（核心）

**PBO 门作废后，仅凭产物中已存在的布尔字段重算** `passed_ic ∧ passed_icir ∧ correct_sign ∧ passed_mom`：

| 历史结论 | 原判定 | 重判 | 风险 |
|---|---|---|---|
| **P2 GP 0/25 幸存** | 门控有效 | **仍成立**。GP 用 `generator.py:1023` 另一套合法 PBO（非退化实现）；淘汰主因是 gate_ic（25 候选 OOS IC 全为 −0.068） | 低 |
| **P3 max_ret_20d/skew_20d 通过四重门** | 2 个通过 | **"通过"声明须撤回**（产物 `n_passed_all=0`）。但二者仍通过其余四门 → 属"因 PBO 退化而被误杀" | 高 |
| **P3/P11/P12 动量残差门灭→因子=动量 beta** | 5 因子被归因于动量 | **归因作废**。产物中 5 因子 `passed_mom` 全为 True。根因：fwd5 由"未来5–10日"修正为"未来0–5日"后相关性结构改变，AGENTS 只披露了 fwd5 修正、未披露动量门结论反转 | 高 |
| **P11 bp 幸存** | 五门全过，唯一幸存 | **bp 幸存成立但证据链须修正**：`passed_pbo=True` 仅因 argmax∈{窗0,1,2}，该门无推断内容；其余四门独立成立（IC 0.0558、ICIR 1.93、方向正确、残差 0.0502/pos_frac 0.941）→ **bp 仍可确认为真因子**，但"ICIR 全场最高"须删（idio_vol 2.2974 更高）、"17 窗全正"无产物支撑 | 中 |
| **P12 尾部+筹码 0/7** | 0/7 | 判定仍成立（受 IC/ICIR 与 pos_frac 约束），但"最接近幸存者"细节反转（其 PBO 实为 0.4195） | 中 |
| **P14 cash/fcf/dy 0/3** | 全灭于 PBO | **部分翻转**：产物显示 cash_ratio/fcf_yield `passed_mom=True` 且 ICIR 0.73/0.91 均 >0.5 → 除 PBO 外四门全过 | 中 |
| **`因子挖掘正式终结`**（AGENTS 出现 4 次） | 四轮独立收敛 | **不成立，须撤回**。17 个唯一因子同时通过其余四门：amivest_20d、bp、cash_ratio、cfp_ttm、cvar_95_60d、downside_semivol_20d、fcf_yield、holder_num_chg_1q、idiosyncratic_vol_20d、illiq_20d、max_drawdown_20d、max_ret_20d、neg_range_20d、reversal_5d、skew_20d、sp_ttm、turnover_20d。**唯一杀死它们的门从未生效** | **最高** |
| **`截面预测力集中于动量`** | 五维度证伪收敛 | **不成立**（其核心支撑正是上面 17 个因子的"动量残差门灭"，而该门在当前产物中报告为通过） | **最高** |
| **P5 CANSLIM 路线终止** | 早出口 FAIL | **仍成立**（FAIL 主因 ICIR 0.42<0.5 与 pos_frac 0.619<0.667，非 PBO） | 低 |
| **P7/P8/P10/P15 §5.2 H-A 主线** | 可交易、容量~2850 万、bp 弱于 H-A | **不受 PBO 影响**（组合层回测不经五门）；P15 §5.1 九个数值需以产物为准（判定方向不变：Q4 夏普差 −0.463 仍为负） | 低 |

**若按正确的多重检验框架重判（窗级 t=ICIR×√n + 家族 39 Bonferroni α=1.28e-3）**：

| 因子 | ICIR | t | p | 判定 |
|---|---|---|---|---|
| max_ret_20d | −2.9128 | −12.0 | 1e-10 | 显著（负向） |
| idiosync_vol_20d | 2.2974 | 9.47 | 5.8e-08 | 显著 |
| reversal_20d | 2.0672 | 8.53 | 2.0e-07 | 显著 |
| **bp** | **1.9328** | **7.97** | **5.8e-07** | **显著** |
| turnover_20d | −1.8420 | −7.60 | 8.0e-07 | 显著（负向） |
| illiq_20d | 1.7650 | 7.28 | 1.9e-06 | 显著 |
| sp_ttm | 1.5234 | 6.28 | 1.1e-05 | 显著 |
| cfp_ttm | 1.0137 | 4.18 | 3.0e-04 | 显著 |
| fcf_yield | 0.9058 | 3.73 | 1.8e-03 | 不显著 |
| cash_ratio | 0.7279 | 3.00 | 8.5e-03 | 不显著 |
| real_dy | 0.5322 | 2.20 | 4.0e-02 | 不显著 |

即当前"0 幸存"的全景在正确框架下应改为**"约 10-11 个因子达 Bonferroni 显著"**。

---

## 5. 可交易性裁决

| 策略/因子 | 裁决 | 依据 |
|---|---|---|
| **H-A 条件 illiq**（主线） | **可交易，容量受限** | P7 四门全过（IC 0.0811/NW-t 5.26/CI [0.052,0.1157]/半期 [0.1118,0.0506]）；P8 三臂 +15.82%/1.33/−12.88%（不受 PBO 影响）；**容量 ≈2850 万元**（持仓名单 ADV 合计中位 28.5 亿/日 × 10% 参与率）；ADV≥2000 万地板变体全市场 +6.84%/0.59/−15.32% |
| **bp 价值因子** | **真因子，可作正交卫星** | ICIR 1.93/t=7.97/p=5.8e-7 独立于 PBO 成立；动量残差门独立通过；组合层 +4.95%/0.52/−12.83%（夏普低于 H-A） |
| **17 个"误杀"因子** | **未达可确认标准，非已证伪** | 须先修复五门统计再重判；其中 10-11 个达 Bonferroni 显著 |
| **LPPL** | **已证伪，应从生产管线移除** | OOS R² 87% 为负；is_bubble 0/200；风险分级无 R² 门 |
| **Wyckoff 相位方向** | **无跨窗 alpha，维持叙事+风控层定位** | fwd20 超额 2 胜 3 负；5 窗无同号显著；T1 n_buy 精确一致、SELL 恒 0 |
| **CANSLIM 路线** | **终止（判定不变）** | FAIL 主因 ICIR 与 pos_frac，非 PBO；A 股成长陷阱实证（a_cagr3@fwd63 IC=−0.0808） |
| **GP 挖掘** | **0 幸存为真，但归因需修正** | 非"门控有效"而是"搜索空间坍缩 + 动量吸引子由架构保证" |

---

## 6. 风险登记册 Top 10

| # | 风险 | 严重度 | 证据 | 缓解 |
|---|---|---|---|---|
| R1 | **PBO 门无推断内容，连带推翻"因子挖掘终结"与"动量 beta 归因"** | P0 | `five_gate.py:86-104`；一手复核 3 情景无区分 | 删 PBO 门，换窗级 t + Bonferroni |
| R2 | **默认配置生产管线 0 信号**（7/8 适配器恒不触发） | P0 | `interfaces.py:214-230` 不展平 metadata + `research_pipeline.py:573` | `collector_pack.update(data_pack.metadata)` 一行修复 |
| R3 | **vectorized 撮合滑点公式错误**（用日总量而非订单量 → 冲击恒取上限 10bp，约 6-10× 高估） | P0 | `unified_matching_engine.py:75-79` | 改用 `quantities` |
| R4 | **复权状态不可程序化确认** → EP/BP/PE_TTM 可能系统性失真 | P0 | 日线无 adjustflag/qfq_close；000001.SZ 1991 close=49.0 vs 2026 close=11.08 倒挂 | 补 adjustflag 列或 bridge 显式告警 |
| R5 | **DataValidator 修复从未生效**（修的是被丢弃的副本）→ 脏数据直接入湖 | P0 | `data_validator.py:13,82` + `tdx_updater.py:297,391` | validate 返回修复后 df |
| R6 | **erf bug 被 `except Exception: pass` 吞掉** → 有回撤的回测静默丢失 overfitting 指标 | P1 | `overfitting_detector.py:96` + `engine.py:542` | 窄化异常 |
| R7 | **索引数据路径错** → regime 恒 UNKNOWN → FSM FORCE_WAIT → 全市场静默零信号 | P1 | `storage_manager.py:580-583` 指向空 `data/lake/index/` | 修正路径 |
| R8 | **D+13"全市场 −2.46%/−51.16%"无产物支撑且方向与现存产物相反** | P1 | 全库检索 0 命中；现存产物 +12.55% | 重建三口径产物 |
| R9 | **覆盖率 50% 红线实际早已击穿**（AGENTS 记 57.88%，实测 21.91% 且全量 --cov 挂死） | P1 | pytest coverage 脚注 | 加 pytest-timeout + 定位顺序依赖 |
| R10 | **20 个依赖无上界 + 无 lock 文件** → CI 与本地可解析到不同版本（numpy 2.4.6、plotly 6.7.0 跨大版本） | P2 | `pyproject.toml` | 加 lock 文件 |

---

## 7. 改进路线图

### P0（合计 ~1 天，最高杠杆）

| # | 项 | 验证成本 | 预期收益 |
|---|---|---|---|
| 1 | **删 PBO 门，换窗级 t 检验 + 家族 Bonferroni/FDR(BH)** | ~15 行改动；**5 分钟可重判全部历史结论**（无需重跑数据，直接读 JSON 既有布尔字段） | 消除唯一无效门；恢复 17 个因子可判性 |
| 2 | **RDP metadata 展平**：`research_pipeline.py:574-576` 补 `collector_pack.update(data_pack.metadata)` | 1 行 + 1 测试 | 7/8 适配器复活 |
| 3 | **vectorized 撮合滑点**：`unified_matching_engine.py:75-79` 改用订单量 | ~10 行 + 同输入双引擎对比 | 消除 6-10× 冲击高估 |
| 4 | **修复 DataValidator 修复失效**：validate 返回修复后 df 而非 bool | ~5 行 + 1 测试 | OHLC 脏数据不再入湖 |
| 5 | **补 `block_bootstrap_pbo` 性质测试**（常数/零假设/真 alpha 三者须可区分）→ 测试必红，立即量化失效面 | 10 分钟 | 防止退化函数再次静默穿透（当前**零测试覆盖**） |
| 6 | **补 erf 异常窄化** + 删死字段 `overfitting_metrics` | ~5 行 | 恢复回测诊断能力 |

### P1（合计 ~2 天）

| # | 项 | 验证成本 |
|---|---|---|
| 7 | `five_gate.py:63` ddof 统一（`np.cov(...,ddof=0)/mv.var(ddof=0)`） | 1 行 + 构造 n=20/50/500 对比测试 |
| 8 | `pnf.py` 分段步长（消除 600602.SH 33 万箱） | ~50 行 + P&F 回归 |
| 9 | `lppl/calculator.py:426` 加 R²/validate_model 门 → 预期 Danger 率从 32.5% 塌缩至个位数 | ~10 行 + 200 股复跑 |
| 10 | `regime_detector.py:158-165` e_pct 改分位数（消 min==max→FROZEN 误判） | ~5 行 + FROZEN 触发率对比 |
| 11 | 补存档 `per_win_raw` 逐窗 IC 序列 → 恢复 bp"17 窗全正"可复验性 | 分钟级 |
| 12 | 统一持有期口径（全门只用 fwd5 或全用 [1,5,20] 平均；GP 阈值改用同口径，消 8.5% 错配缺口） | 小时级 |
| 13 | 删 `neg_range_20d`（与 range_20d rho=−1.000）+ 消 illiq/amivest 互逆冗余 → 有效维度 39→~18 | 分钟级 |
| 14 | `storage_manager.py:152` read_parquet 加 `columns=`（financial 577→25 列，I/O −95%） | ~20 行 |
| 15 | 产物版本化（`_meta.run_id` + 按日期分目录，禁覆盖） | ~1h，改 6 个脚本 |

### P2（合计 ~3 天）

| # | 项 | 验证成本 |
|---|---|---|
| 16 | GP 末端集加入流动性/估值/财务通道（illiq、bp、turnover 等 5-8 个）→ 动量吸引子从"架构保证"变为"可检验假设" | 小时-天级 |
| 17 | IC 计算加 winsorize(1%/99%) + 行业/对数市值中性化 | 天级 |
| 18 | `composer.compute_all_factors` 向量化（~100 行，预计 3-5× 加速） | ~6h |
| 19 | `merge_financial_metrics`/`scan_service` 改 ProcessPoolExecutor（CPU 密集，预计 2-4×） | ~10 行 |
| 20 | AGENTS.md 拆为 ≤300 行当前真相 + `docs/changelog/`（只增不改）；建 `results/INDEX.md` 反向索引；文档加"产物: results/..."首行强制 | ~2h |
| 21 | 加 pytest-timeout + 定位顺序依赖型挂死；补 SAST/gitleaks；依赖加上界 + lock 文件 | ~4h |
| 22 | 重建 D+13 三口径产物（当前唯一无产物支撑的重大结论） | ~1h |
| 23 | 恢复 git 历史中的归档死代码与 554 指数归档，或明确改为"已删除"表述 | ~半天 |

---

## 8. 方法论边界声明

1. **审计范围**：只读代码与产物分析，未修改任何文件。所有量化声明来自本次实际运行的命令输出与 `file:line` 证据。
2. **未验证项**：未在 `use_research_data_pack=false` 且索引数据齐备的组合下验证端到端 BUY 信号能否穿越 arbitrator 进入撮合并产生成交；`test_unified_matching.py` 超时未完成；`pip-audit` 因网络阻断无法给出 live 漏洞清单；`all_stock_codes.csv` outDate 全 NULL 致幸存者偏置**无法量化**。
3. **PBO 结论为构造性证明**（确定性映射表 + 三情景无区分），非抽样推断，可辩驳性最低。
4. **"17 个因子通过其余四门"基于产物中已存在的布尔字段重算**，未重跑数据；但 `factor_gates` 对 `expected_dir<0` 会取反 `res_m/tail_m` 并置 `frac_pos=1-frac_pos`，故存储的 `mom_res_mean` 是**符号归一化后**的值——AGENTS 各段叙述混用"原始残差"与"归一化残差"，这是 P3/P11/P12 归因文本与产物矛盾的机械来源。
5. **死代码 31 模块/7,379 LOC 为静态 import 可达性**，未考虑反射/字符串动态导入（实测 `data/` 下 importlib 命中为 0，降低误判风险）；66 模块/16,661 LOC"无测试引用"为静态代理，**不能直接当作 0% 覆盖**。
6. **Wyckoff T1 基线与 P1/P7/P8/P10/P14/P15 §5.2 的核心数值经逐位核对全部一致**，证明漂移是局部可定位的，而非系统性失真。漂移集中于三个机械根因：**产物被覆盖而无版本化**、**研究脚本统计函数无测试**、**预注册文档与产物写入时序倒置**。
7. **本报告的判定标准区分"证伪"与"未达可确认标准"**：PBO 门失效意味着大量因子处于"未达可确认标准"，不等于已证伪；真正已证伪的只有 LPPL（OOS R² 87% 为负）与"因子挖掘终结"这一项目级结论。

---

## 附录 A — 一手复核命令记录

```bash
# 1. PBO 确定性映射与三情景无区分（编排层独立复核，确认 Batch1-D 与 Batch2-G 结论）
.venv/bin/python -c "
from scripts.factor_mining.five_gate import block_bootstrap_pbo
# peak@win{0-2}->0.1655 {3-5}->0.307 {6-8}->0.4195 {9-11}->0.5325 {12-14}->0.6165 {15-16}->0.6695
# 零假设/真alpha/负alpha -> meanPBO=0.4141, P(<0.2)=0.245 (三者相同)
# 常量 0.05 -> 1.0000"

# 2. ResearchDataPack.to_dict() 不展平 metadata（确认 F1/F2）
awk 'NR>=240 && NR<=262' src/uniquant/shared/interfaces.py   # "metadata": self.metadata (嵌套)
sed -n '568,580p' src/uniquant/services/research_pipeline.py  # 仅 to_dict()，无 update(metadata)

# 3. 工程质量
ruff check src/       # All checks passed
ruff check tests/     # All checks passed
ruff check scripts/   # Found 18 errors (wyckoff_multitf/v9_*)
~/.local/bin/pytest tests/ -q -o "addopts="   # 2348 passed, 8 skipped, 0 failed, 1068s

# 4. 因子注册
.venv/bin/python -c "from uniquant.brain.factors.custom_factors import register_all;
  from uniquant.brain.factors.registry import FactorRegistry; register_all();
  print(len(FactorRegistry.get_all()))"   # 39 (custom 16 / fundamental 13 / technical 10)

# 5. 茅台 PIT 锚点
# financial_bridge.calculate_eps_ttm -> FY2024 = 68.63999938964844 (期望 68.64) ✓
```

## 附录 B — 审计分工

| 轴 | 内容 | 状态 |
|---|---|---|
| A | 架构与运行时流（24 项发现 + 完整调用链 + 死分支清单） | ✓ |
| B | 数据层与 PIT 正确性（14 项风险表 + 数据湖完整性 + 锚点验证） | ✓ |
| C | 6 脑引擎正确性与实证（审计表 + 代码级缺陷 + 3 股一手复核） | ✓ |
| D | 因子研究管线与统计方法论（五门有效性判定 + 20 项数字核对 + PBO 基准分析） | ✓ |
| E | 信号→回测→撮合 + A 股规则（七道防线表 + 死代码验证 + 口径差距机制） | ✓ |
| F | 工程健康度 + 数据结构与算法性能（测试/安全/依赖/性能热点/数值正确性） | ✓ |
| G | 研究资产一致性（24 条漂移清单 + 结论翻转评估 + 追溯性核查） | ✓ |
| 编排层 | 独立复核两大头条发现 + 综合 | ✓ |
