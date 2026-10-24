# UniQuant 系统与 CNMM-QAR 策略法医级评估报告（独立审计）

- **审计日期**：2026-10-24
- **审计对象**：commit `0c2f604`（第十轮 QAR 法医数学矫正与 Phase 1-4 生产工程化闭环）
- **审计方法**：主控团队（顶尖交易员 + 量化金融架构师双视角）派出多路分析单元；其中主力为**主线程逐行审计**（回测引擎 711 行 / 费用账本 380 行 / 执行编排器 370 行 / 生产 CLI 173 行 / 复权计算器 328 行 / PIT 宇宙 205 行）+ 1 路 subagent 策略核心深审（`scripts/qar/cnmm_qar_strategy.py` 562 行全读 + `brain/factors/forensics/` 全部 4 文件）+ 实测命令交叉验证。
- **工作树状态**：干净（0 modified 文件），ruff 全绿，所有证据取自当前工作树实测。
- **文档状态**：本报告为独立审计快照。AGENTS.md 第十轮引用的 `UNIQUANT_SYSTEM_AND_QAR_FORENSIC_EVALUATION_REPORT.md` 与 `QAR_PRODUCTION_AND_ENGINEERING_OPTIMIZATION_ACTION_PLAN.md` **在全盘与 git 历史中均不存在**（幻影引用，见 §1）。

---

## 0. 执行摘要（裁决先行）

1. **工程纪律面诚实可靠**：测试收集 3,986 例（与 AGENTS.md 声称精确一致）、定向 47 例全绿、ruff 0 问题、`results/backtest/cnmm_purged_long_horizon/` 存证齐全且今晨重跑逐位一致。
2. **策略绩效与能力声称面系统性夸大**：旗舰回测 CAGR 19.49%/14.58%/9.58% 三轨数字建立在 **105 只纯幸存者面板 + 1-67% 的"对冲"收益发生在股指期货上市之前 + 无资金来源的年息 2.5% + 68% 历史 CFO 被净利润顶替 + 年度点对点回撤口径** 五重粉饰之上。
3. **QAR 策略信号面可信度：3/10；回测数字不应作为真实预期**。方向性假设（会计排雷 + 现金流质量）值得检验，但当前证据链不足以支持任何资本决策。
4. **可用资产**：机构费用账本递归复利数学正确、337/337 退市股数据在湖、复权链路因果正确、动态 PIT 宇宙基础设施已建成——**弹药已备，只是旗舰回测没上膛**。
5. **文档漂移**：AGENTS.md 三项关键声称（五维排雷已实现生产接入 / ROA 顶替 CFO 已彻底拔除 / 两份旗舰报告已产出）与代码现实**相反或不成立**。

---

## 1. 声称 vs 实测交叉验证表

| AGENTS.md / 目标文稿声称 | 裁决 | 证据 |
|---|---|---|
| 全套 3,986 用例收集 | ✅ 属实 | `pytest --co`：231 文件 / 3,986 例 |
| 定向测试（QAR/账本/Phase2/3/4）全绿 | ✅ 属实 | 本次实测 47/47 passed |
| ruff 0 问题 | ✅ 属实 | `ruff check src/ tests/ scripts/` All checks passed |
| CNMM-EX CAGR 19.49% / 乘数 85.70x / MDD 21.79% | ✅ 数字存在 | `results/backtest/cnmm_purged_long_horizon/cnmm_v3_purged_2000_2025_summary_metrics.csv`（2026-10-24 09:28 重生成） |
| CNMM-IH 14.58% / 30.03x / MDD 4.92% / Calmar 2.96 | ✅ 数字存在 | 同上 |
| 75/25-IH 9.58% / MDD 5.19% / LP 净 6.04% | ✅ 数字存在 | 同上 |
| 子周期 2010-2025：CAGR 14.88% / MDD 2.27% / Calmar 6.55 | ✅ 数字存在 | `...subperiod_metrics.csv` |
| 消融（无 Z_CNMM）MaxDD 51.16% / CAGR 10.85% | ⚠️ 数字存在但**归因不成立** | 见 §3.4 |
| 复权假死后门（`actual_drop < expected_drop*0.3`）拔除 | ✅ 属实 | `smart_factor_calculator.py:189-196`——已改为仅记日志，不再跳过事件 |
| 退市股 337/337 数据湖覆盖 | ✅ 属实 | 实测 SSOT type=1 退市 337 只，湖内 337/337 均有日频 parquet |
| 000300TR.SH / 000016TR.SH 全收益基准建成 | ✅ 存在 | `data/lake/quotes/index/000300TR.SH.parquet` 等；⚠️ 但旗舰回测仍用价格指数 |
| 产出《UNIQUANT_SYSTEM_AND_QAR_FORENSIC_EVALUATION_REPORT.md》 | ❌ **不存在** | `find` 全盘 + `git log --all --diff-filter=A` 零命中 |
| 产出《QAR_PRODUCTION_AND_ENGINEERING_OPTIMIZATION_ACTION_PLAN.md》 | ❌ **不存在** | 同上 |
| "彻底拔除以 ROA 顶替 CFO" | ❌ **不属实**（残留并实际大面积生效） | §3.2 |
| "五维会计法医排雷 Z_CNMM" 生产接入 | ❌ **不属实**（五维是死代码；生产为两维内联） | §3.3 |
| Phase 4 "打通 PIT→…→TWAP 全链路生产 CLI" | ❌ **名不副实**（演示产物 + 假 ADV） | §3.6 |

---

## 2. 审计覆盖面

| 文件 | 行数 | 审计深度 |
|---|---:|---|
| `scripts/backtest/run_cnmm_purged_long_horizon.py` | 711 | 逐行（主线程） |
| `scripts/qar/cnmm_qar_strategy.py` | 562 | 逐行（subagent） |
| `src/uniquant/hands/backtest/institutional_fee_ledger.py` | 380 | 逐行 + 手工算术验证 |
| `src/uniquant/hands/backtest/institutional_execution_orchestrator.py` | 370 | 逐行 |
| `scripts/canslim/daily_signal_qar.py` | 173 | 逐行 + 实际产物核对 |
| `src/uniquant/data/utils/smart_factor_calculator.py` | 328 | 逐行 |
| `src/uniquant/data/universe/dynamic_pit_universe.py` | 205 | 逐行 |
| `src/uniquant/brain/factors/forensics/*`（4 文件，含 837 行 ZCNMMCalculator） | — | subagent 全读 + 全仓调用图 |
| 实测数据 | — | 105 股面板 SSOT 交叉核对、337 退市股核验、CFO 覆盖率统计、TR 基准存在性、`results/daily_qar/2024-05-06.json` |

---

## 3. QAR 策略可靠性核心发现

### 3.1 幸存者偏差——全案最大缺陷（P0）

旗舰回测的股票宇宙 = `data/backtest/large_sample_100_panel_processed.csv` **静态 105 股面板**（`run_cnmm_purged_long_horizon.py:74-81`，`stock_codes` 来自该 CSV `:148`）。

**实测（本次运行）**：

- 面板 105 只在 SSOT `data/all_stock_codes.csv` 交叉核对：**已退市 = 0/105**；
- 成分为 2026 年视角的知名蓝筹：平安银行、万科、中兴、格力、五粮液、比亚迪、宁德时代、茅台……（样例代码 `['000001','000002','000063','000069','000568',...]`）；
- 上市时间分布：**2000-05-08 前已上市仅 19 只**（早期调仓年实际候选仅一二十只）；2010 前上市 52 只；2020 后上市 18 只（它们在上市后"空降"进入后期回测）；
- 面板等权基准 25 年 CAGR **17.51%** vs 真实市场基准（上证综指/沪深300 价格指数）**3.86%**——**这 13.65pt 的差就是烙进所有策略数字的幸存者溢价**。

**叠加双重粉饰**：

- `run_cnmm_purged_long_horizon.py:287`：`valid_mask = p0.notna() & p1.notna() & (p0 > 0)` —— 调仓时刻要求股票**下一年（d1）仍有报价**，即用未来存活信息过滤当期组合；中途退市/长期停牌股被静默剔除；
- AGENTS.md / 文稿声称的"消融对照"在同一幸存池上进行——真实全市场的暴雷风险（含 337 只退市股）在入池环节已被结构性消除。

**裁决**：`DynamicPointInTimeUniverse`（337 只退市股 [ipoDate, outDate) 数据齐备、判定逻辑正确）**未接入旗舰回测**。"彻底根除静态 105 股面板幸存者偏差"的声称与事实不符：基础设施修好了，主回测还在用幸存者面板。

### 3.2 CFO 顶替残留（P0）——"彻底拔除"声称不成立

- `run_cnmm_purged_long_horizon.py:241` 与 `cnmm_qar_strategy.py:367`：
  `ann["cfo_yi"] = ann["cfo_yi"].fillna(ann["net_profit_yi"])` —— **CFO 缺失即用净利润回填**，`cfo_proxy` 退化为 `净利润/总资产`（即 ROA），并等价于假设应计项恒为 0；
- 回退二（两处 `:243` / `:369`）：CFO 记录全空时整列 `cfo_yi = net_profit_yi`。

**数据湖实测覆盖率（subagent 运行）**：

| 指标 | 实测值 |
|---|---:|
| 105 股 2,223 份年报中 CFO（CAS 31）命中 | 1,033 份 |
| **缺失** | **1,190 份（53.5%）** |
| 存在缺失的股票 | 84/105 |
| **1999-2015 年报缺失率** | **100%**（数据湖 financial 自 2016Q1 才开始） |
| 2016 / 2017 / 2018+ 缺失率 | 3% / 1% / 0% |

**推论**：25 年回测中 **2000-2016 共 17 个调仓年（68%）的"造血现金流因子"就是净利润/总资产**——恰是 Sloan（1996）指出可靠性最低的成分。AGENTS.md "真实 CAS 31 造血现金流对齐"声称的"拔除 ROA 顶替"，实测上是"仅对 2017 年后的 9 个调仓年成立"。

### 3.3 Z_CNMM "五维会计法医排雷"是死代码（P0）

- **宣称**：DSRI（应收激增）/ AQI（资产质量恶化）/ Sloan（应计背离）/ DEPI（CIP 存贷异常）/ CashTrap（虚增利润）五维加权排雷。
- **现实**：生产信号与回测用的是**内联两维简化式**（`cnmm_qar_strategy.py:418-422` 与 `run_cnmm_purged_long_horizon.py:337-341` 逐字相同）：
  `z_score = 0.6 × cip_z + 0.4 × loss_flag`，`cut = quantile(0.75)`，淘汰前 25%；权重 0.6/0.4、阈值 0.75 **无任何文献引用、无校准过程、无敏感性说明**。
- 837 行的五维引擎 `src/uniquant/brain/factors/forensics/z_cnmm_calculator.py` 全仓 grep：**唯一引用方为 `forensics/__init__.py:7`（再导出）与一个 AST 异常扫描测试**；`tests/test_forensics_factors.py` 只测 Ohlson/Winberry（且这两者不在 QAR 信号链上）——**零生产调用、零行为测试**。
- 无前视部分：两维版的截面 z 标准化为**同年报截面内**标准化（PIT 安全）；60 日动量为 trailing（`cnmm_qar_strategy.py:442`）；复权因子因果。

### 3.4 对冲数学三重缺陷（P0）

核心公式（`run_cnmm_purged_long_horizon.py:414`）：
`r_s6_ih_net = r_s6_ex_net − r_bm − basis_cost + 2.5%`

1. **+2.5% 无风险利率无资金来源**：经典对冲轨 100% 资金已买股票，没有空闲现金生息——年化 2.5% 属无中生有（唯一辩护"保证金利息"在满仓多头结构下不成立）。
2. **2010 年前的虚构对冲**：中国首个股指期货 2010-04-16 才上市（IH 更是 2015-04-20），但回测从 2000 年起就计提对冲轨收益（`yr < 2010 → basis_cost = 1.5%`，`:399-400`）。**2000-2010 的"对冲绝对收益"在现实中不可能交易**，却被复利进 14.58% 全周期 CAGR 与 2010 前子周期指标。
3. **与自家生产模块自相矛盾**：`institutional_execution_orchestrator.py:313-321` 的经典对冲轨公式为 `r_long − r_bm − 2.5%/252`（**无** +rf）；回测为 `−basis + rf`（常态下净 0 拖累）。**同一系统两套对冲账，年化相差 2.5pt**。其余对冲账问题：2023 年 8 月后印花税已第二轮下调（代码 2024-2025 年段沿用 5bps 属实但未含 2024 年 9 月后交易成本结构变化）；常态基差 2.5% 明显低估 IH/IC 现实（2015-2019 年贴水经常 5-12% 年化）；逐年硬编码 2015:12% / 2018:4.5% / 2021:3% / 2023:3.3%（`:400-411`）精确值暗示事后校准取舍。

### 3.5 MaxDD 4.92% 与消融 51.16% 的真面目（P0）

**MaxDD 4.92% 的真实身份**：年度明细实测——**2000→2001 年 CNMM-IH 收益恰为 −4.92%**，即"全周期真实最大回撤 4.92%"= **第一年的单年亏损**（nav_with_base 起点 1.0，cummax 后 dd=4.92%，此后 24 年再无累计回撤超过它）。这是**年度点对点口径（25 个点）**的回撤，非日频净值回撤。

**日频净值与策略组合脱钩**：`build_daily_nav_series`（`:555-601`）生成的日频 NAV 基于 `df_rets[clean_codes].mean(axis=1)`（`:561`）——**105 只全池等权对冲净值，与策略 6 选股组合毫无关系**（且 `daily_roll` 与 `daily_rf` 相互抵消 `:577-579`——日频对冲无成本、无基差、无费用净效应）。**策略组合的真实日频回撤从未被计算过**。

**消融 −51.16% 的真实机制**（年度明细实测，`ablation_no_z_cnmm_ih_pct`）：

| cycle | 基准 | 等权 | CNMM-EX | CNMM-IH | 75/25 | **消融(无Z)** |
|---|---:|---:|---:|---:|---:|---:|
| 2014->2015 | +122.02 | +130.92 | +119.75 | **−2.27** | −3.20 | **−51.16** |
| 2013->2014 | −11.97 | +11.31 | +22.53 | +34.50 | +24.37 | +38.65 |
| 2006->2007 | +202.52 | +206.35 | +197.35 | **−4.17** | −4.63 | −7.31 |

- 消融的 −51.16% 集中在 **2014→2015 周期**：基准 +122%，消融多头组合约 +71%（由反推 `r_abl_ih = r_abl_net − r_bm − basis + rf` 得）——低 beta 动量股赶上超级牛市，对冲空头腿把它打成 −51%。**这是 beta 错配，不是"排雷防止了造假股暴雷"**。
- 且消融组同时剥离了 Q4 排雷与 Z_CNMM 两层门禁（`:364-367` 在 `valid_universe` 全集选优），**消融设计不纯**：(Q4+Z) 联合效应被全部记在"Z_CNMM 头上。
- 配套测试 `tests/test_cnmm_qar_strategy_and_backtest.py:115-116` 仅断言 `mdd > 50.0`——**钉住的是该有缺陷消融设计的输出**，不检验归因纯度。
- AGENTS.md "确凿证实会计法医排雷的不可或缺性" 的因果叙事**不成立**。

### 3.6 生产 CLI `daily_signal_qar.py` 是演示品（P0）

`results/daily_qar/2024-05-06.json` 实测核验：

- **`timestamp_utc: "2026-10-24T01:31:19"`** —— 是**今天生成的回溯日期（2024-05-06）演示产物**；该流水线从未在真实当前日期运行过；
- **ADV 是伪造的**：`daily_signal_qar.py:113` 自注释"模拟 ADV 数据"，`adv = volume × 12.0` → 参与率恒 8.33% < 10% 阈值 → **拆单永不触发**；输出 `slicing_required: 0`、滑点 6.93bps 全部建立在假数据上；
- 硬编码：股票价格 `price=50.0`（`:108`，对 40 只不同个股）、期货价 `futures_price_points=4000.0`（`:99`；2024-05 现实约 3600）；
- **PIT 违规**：`:76` `fiscal_year = as_of_dt.year − 1` —— 1-4 月运行会使用**报告期 12-31 但尚未披露**的年报（多数公司 3-4 月才披露）；配套测试只测 2024-05-06（5 月），**恰好绕开违规区间**；
- **POT 摆设**：`:82` 将 4,643 只 PIT 候选与 105 面板求交 —— 面板外股票在财务/价格数据中无记录、alpha 恒 0，**实际可打分标的仍只有 105 只**；
- 命名错位：track 叫 `75/25-IH`，实际对冲合约是 **IF**（输出 `contract_type: "IF"`）；
- `run_generate_trading_manifest.py` 完全脱产：40 只价格硬编码、目标权重直接 `0.75/N`，与策略无数据流连接；
- 小缺陷：`daily_signal_qar.py:106` 对 6 开头股票标 `.SH`、其余一概 `.SZ` —— 北交所代码会被误标。
- **积极面如实记录**：组合权重分配（40 只 × 1.875% = 75%）、杠杆恒等式（gross 1.75 = 0.75+0.75+0.25）自洽；3 PB 分仓名义合规校验结构存在（但账号名/席位名为虚构演示）。

### 3.7 费用账本与其它工程发现

**费用账本递归复利数学 ✅ 正确（主控手工验证）**：`process_continuous_nav_series`（`institutional_fee_ledger.py:199-309`）——资本底座按毛收益滚动、ACT/365 管理费逐日计提、hurdle 自上次结晶日线性累积、**低于 hurdle 时结晶不重置累积起点（对投资者保守，正确）**、结晶日 carry 实际划转并成为新 HWM、盈利资金回撤期准备金自动冲销。机构级正确的系列法核算。AGENTS.md "挂载 recursive=True"声称属实（`run_cnmm_purged_long_horizon.py:585`）。

**账 config 问题（P1/P2）**：账本报表 Sharpe 用 hurdle 当 rf（`:342-343`，非标准）；回测存在**两套并行 LP 费用口径**（年度循环内简单式 `:422-425` 无 HWM vs 日频账本递归式——`lp_net_real_pct 10.18%` 与日频账本数字不可互相推断）；账本 `start_date="2000-05-08"` 但日频数据首日若晚于它会一次性补收多天管理费（min 1 天，边界风险低）。

**其它（P1/P2）**：回测换手率硬编码 0.25（`:372`）——年度全量重选下真实换手高得多（40 只池即使 60% 重叠，单边换手 ≥35-40%，成本被低估）；回测选股 `max(10, min(40,…))` vs 策略类 `max(30, min(40,…))`（`cnmm_qar_strategy.py:479-482`）**行为分叉——回测所测与"生产策略类"不是同一对象**；`cnmm_qar_strategy.py:231,240` 与回测 `:76,80` 残留 `~/Documents/Project/CNNM/` 兄弟仓绝对路径回退（第五轮清理过的同类缺陷）；数据窗口硬编码 `2026-07-23`；同日多除权事件在回测路径未聚合分算（`calculate()` 逐事件独立计算会产生混合误差，聚合函数 `aggregate_events` 只在并行全市场管线中被调用）；除权日停牌事件被 `idx` 检查跳过（`:159`）；alpha 系数 `0.5×动量 + 0.5×(cfo×5)` 中 5.0 放大系数无依据。

### 3.8 PIT 宇宙与信息时点

- 上市/退市时点判定 `[ipoDate <= as_of < outDate)` 逻辑正确（`dynamic_pit_universe.py:113-114`）；
- **ST 过滤用名称前视**（P1）：`:122` / `:193` 对 SSOT 的 `name` 列（= **2026 年当前名称**）做 ST 匹配——2025 年才戴帽的股票会被追溯剔除出其 2018 年历史候选池。对"生产日常信号"影响有限（生产只关心当下），但对**历史回测若将来接入该池**会系统性美化排雷效果（未来 ST 名单提前排除历史造假股）；
- P2：ST/问题公司年报法定可延至 6-30 披露，5 月初调仓时其年报未披露却被视为可用（回测与生产 CLI 均无年报披露日期兜底）；
- P2：d0 收盘生成信号、d0 收盘成交假设（`:290`）——业界常见但乐观，未在文档中作为已知乐观项披露于对外指标旁。

---

## 4. 数据分析准确率分项

| 环节 | 评分 | 关键事实 |
|---|---:|---|
| 行情复权（GBBQ→hfq 因子） | **7.5/10** | 因果正确、`actual_drop` 假死后门确实拔除（改日志不再跳过）、round 2 分位模仿交易所；P2 缺陷：回测路径同日多事件未聚合、除权日停牌事件跳过 |
| 财务数据（CAS 31） | **4/10** | 财务主列来自手工 CSV 面板而非湖；CFO 2016 前覆盖率为零 → `fillna(net_profit)` 污染 68% 历史 |
| PIT 宇宙 | **6/10** | 上市/退市时点正确；ST 过滤名称前视；未做 ADV 门禁的实际接线 |
| 基准数据 | **5/10** | TR 全收益基准已建成（`quotes/index/`）但旗舰回测未用（仍价格指数）；2005 前上证综指 / 后沪深300 硬拼接；对冲高度下"多头后复权(含股息) vs 价格指数"实际包含约 2%/年股息差——是真实经济收益但口径未在指标旁披露 |
| 绩效度量口径 | **3/10** | MaxDD/Sharpe/Calmar 全部基于 25 个年度点；日频 NAV 是另一个策略（全池等权对冲）；"策略组合日频回撤"从未计算 |
| 回测可复现性 | **9/10** | 存证齐全、今日重跑逐位一致、测试钉住全部关键数字（自证循环，防漂移有效、不证正确） |
| 退市/除权基础设施 | **8/10** | 337/337 退市 parquet 在湖、GBBQ 单轨契约、假死根除——**具备全市场纯净回测的数据条件** |

---

## 5. 评分卡（主控团队裁决）

| 维度 | 评分 | 一句话裁决 |
|---|---:|---|
| 信号面（Z_CNMM/alpha 构造） | **3/10** | 两维简化式顶着五维的名；CFO 半数历史是净利润顶替 |
| 回测可信度 | **2.5/10** | 数字可复现，但基底（幸存者池+虚构对冲+无源利息）不成立 |
| 数据基础设施 | **6.5/10** | 复权/退市/湖是真金白银；财报历史覆盖与 ST 前视是硬伤 |
| 执行与费用 | **5/10** | 费用账本数学正确（7/10）；执行编排是"真接线+占位"混合体；生产 CLI 微观执行是假的（3/10） |
| 生产就绪度 | **2/10** | daily_signal_qar 是回溯日期演示产物，从未在真实日期运行 |
| 文档诚实度 | **4/10** | 两份旗舰报告为幻影引用；五维排雷/CFO 拔除/PIT 打通三项声称与代码相反 |
| 工程纪律（测试/lint/存证） | **9/10** | 3,986 例、ruff 0、证据链可复现——全仓最强资产 |

**最终裁决**：CNMM-QAR 的 19.49%（纯多）/ 14.58%（对冲）/ 9.58%（75/25）三个 CAGR **不能作为真实预期**。粗略敏感性：仅去掉 +2.5% 无源利息与产能不存在的 2010 前对冲账、按真实基差（2015-2019 年 5-12%/年）、并考虑幸存池溢价（面板等权基准一年虚高 ~13.7pt，选股 alpha 同源受染）后，**对冲轨真实口径 alpha 可能折半甚至归零**。方向性假设（在建工程挂起 + 亏损排雷 + 现金流质量在 A 股长期有效）并不因此证伪——它是值得在**含退市股的动态 PIT 全市场池**上重新检验的假设。

---

## 6. 敏感性粗算（供决策参考，非精确重现）

| 调整项 | 对 CNMM-IH CAGR 的影响（方向） |
|---|---|
| 去掉无源 +2.5% rf（2010-2025） | −2.5pt |
| 基差 2.5% → 现实区间（2015-2019 加权 ~6%） | −1.5 ~ −2.5pt |
| 幸存者面板选股收益溢价折减（与等权基准溢价同源） | −3 ~ −8pt（不可精确估计） |
| 换手率 0.25 → 实测化（~1.0 双边） | −0.1 ~ −0.3pt |
| CFO=ROA 顶替年份（2000-2016）改用保守中性分数 | ±（未知，方向不利为主） |

> 结论：折后对冲轨 CAGR 的合理中心估计在 **5-9%** 区间，且尾部风险（日频口径）远大于 4.92% 的年度口径 —— 在进一步重测之前，任何以此为依据的资本决策均不获本审计支持。

---

## 7. 修复路线图

### P0（不修复则一切数字无效）

1. **回测宇宙重建**：旗舰回测切换到 `DynamicPointInTimeUniverse` 全市场池（含 337 只退市股；退市按末日价/破产回收率处理），删除 `run_cnmm_purged_long_horizon.py:287` 的 `p1.notna()` 未来存活过滤；
2. **CFO 纯净化**：删除两处 `fillna(net_profit)`（`run_cnmm_purged_long_horizon.py:241`、`cnmm_qar_strategy.py:367`）；2016 前显式停用现金流因子（NaN 传播为弃权）或回补历史财务数据至 2000；
3. **对冲账统一与真实化**：删除无源 +2.5% rf；2010-04-16 前只跑纯多轨（75/25/对冲轨不定义）；基差模型与 orchestrator 对齐并接入真实历史基差时序（THS/Wind 或湖内 futures 目录）；
4. **生产 CLI PIT 修复**：`daily_signal_qar.py:76` 1-4 月改用 year−2 年报或显示最新已披露期（按公告日期）；真实 ADV 接线（可用湖内 20 日均额）；
5. **ZCNMMCalculator 处置**：接线生产并补行为测试，或删除并停止在 AGENTS.md/文稿中宣称"五维会计法医排雷"；
6. **日频指标落地**：计算策略组合真实日频净值（选定组合而非全池等权）与日频 MaxDD，所有对外指标标注频率口径与成交假设。

### P1

消融重设计（单层剥离：仅关 Z_CNMM、保留 Q4）；TR 全收益基准接入旗舰回测；ST 状态时点化（需带披露日期的 ST 名单数据）；换手率实测化（统计每年实际入选重合度）；统一两套 LP 费用口径（年度简单式并入账本递归式）；回测/策略类 top_n 对齐；清理 `~/Documents/Project/CNNM/` 兄弟仓路径残留（生产侧）。

### P2

同日多除权事件聚合进回测路径；停牌除权事件处理；d0 收盘成交假设显式披露；数据窗口硬编码改配置；`daily_signal_qar.py:106` 北交所代码修复；IF/IH 命名对齐；补齐或删除 AGENTS.md 引用的两份幻影报告。

---

## 8. 验证命令存证（本次审计实测）

```bash
# 测试收集与数字钉证
python3 -m pytest tests/ --collect-only -q        # 231 文件 / 3,986 例
python3 -m pytest tests/test_cnmm_qar_strategy_and_backtest.py \
  tests/test_institutional_fee_ledger.py \
  tests/hands/backtest/test_phase2_institutional_execution_orchestrator.py \
  tests/data/universe/test_phase3_dynamic_pit_and_benchmark.py \
  tests/scripts/test_daily_signal_qar.py tests/test_smart_factor_calculator.py \
  -q                                             # 47 passed
ruff check src/ tests/ scripts/                   # All checks passed!

# 数据实测
# 105 面板与 SSOT 交叉：0/105 退市；2000-05 前上市 19 只
# SSOT type=1 且 outDate 非空：337 只；湖内 337/337 有日频 parquet
# CFO 覆盖：1,033/2,223 命中；缺失 53.5%；1999-2015 缺失 100%
# results/daily_qar/2024-05-06.json timestamp_utc = 2026-10-24T01:31（演示产物）

# 回测存证（2026-10-24 09:28 重生成，数字与 AGENTS.md 声称逐位一致）
results/backtest/cnmm_purged_long_horizon/cnmm_v3_purged_2000_2025_annual_perf.csv
results/backtest/cnmm_purged_long_horizon/cnmm_v3_purged_2000_2025_summary_metrics.csv
results/backtest/cnmm_purged_long_horizon/cnmm_v3_purged_2000_2025_subperiod_metrics.csv
```

---

## 9. 可信资产清单（本轮审计确认的"金子"）

1. `InstitutionalFeeLedger.process_continuous_nav_series` —— 机构级递归复利费用核算，数学正确（本审计手工推导通过）；
2. 337/337 退市股日频 parquet（数据湖）+ GBBO 单轨 + 除权假死根除 —— 全市场纯净回测的**数据弹药已备**；
3. `DynamicPointInTimeUniverse` —— [ipoDate, outDate) 点在时判定正确（除 ST 名称前视待修）；
4. 组合治理层 —— 单票 2.5% 上限 / 行业 10%&4 只 / Decimal 穿透校验（`portfolio_service.py` 起）；
5. 回测可复现性与测试钉证体系 —— 数字防漂移能力一流（尽管目前钉的是错误基底）；
6. 复权链路因果性 —— 无前视。

**下一步总纲**：把这六件真实资产装进 P0 修复路线图的第一项（全市场 PIT 回测重跑），即可在最短路径上得到第一版**可以当作真实预期参考**的 QAR 指标。
