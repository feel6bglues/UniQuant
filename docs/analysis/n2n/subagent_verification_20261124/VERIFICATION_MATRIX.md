# N2N 独立复核 — 交叉核对矩阵

> **日期**：2026-11-24 · **基线**：`b1d2415`（既有报告基线 `434aab1`，`src/` 为空 diff）
> **口径**：**一致**=双方结论吻合；**分歧**=独立复核不同判断（附双方证据）；**已修复**=基线后修复；**仍遗留**=可复现。
> 完整逐条矩阵见各模块报告 §⑤；本表为跨模块汇总。

---

## 1. 既有 Claude 报告结论 → 独立复核裁定（关键行）

### 数据流转（S1）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| 9 列契约 `amount` 在 `volume` 前 | 一致 | `data_fetcher.py:41-51`；湖实测 8 样本吻合；`reindex` 强制 |
| C3 红线禁 bfill | 一致 | `data_cleaner.py:52-54` |
| 量纲自校准 `[60,160]` | 一致（补 M2） | 既有漏掉 `<5 行静默 no-op` |
| 原子写机制 ✅ | **分歧（上调）** | 只审 `StorageManager.write_parquet`；5 处直写绕过（M1，含 `tdx_parser.py:432`） |
| FreshnessValidator"第 25 轮已修复" | **分歧（不成立）** | `434aab1` 无该文件变更；`b1d2415` docs-only |
| M1 FreshnessValidator 未集成（MEDIUM） | 一致（**上调 HIGH**） | 门禁不在运行时=滞后照常交易 |
| L1 列序文档不一致 | 一致（**自相矛盾**） | §1.1 与 §7.4 两侧完全相同 |
| L2 在线源静默空表（LOW） | 一致（**上调 MEDIUM**） | Fail-Open 违反 Rule 4 |
| DataValidator 只读门禁 | **分歧（漏关键事实）** | 无运行时调用方（H2） |
| 大脑取数路径 | **分歧（漏调整不一致）** | H1：湖命中 raw vs 湖 miss qfq |

### 分析引擎（S2）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| 双栈边界隔离 / LPPL 边界 / L-BFGS-B / FSM Veto-Scoring / Wyckoff Step0-5 | 一致 | 机制描述可复现 |
| L1 双路径 R² / L2 状态文件 / L3 structural_adjust | 一致 | 3 个 LOW 均确认 |
| §7.1-7.3 CRITICAL/HIGH/MEDIUM=无 | **分歧（漏判）** | 漏 C1（pre_close 死代码）/H1（LPPL 双路径矛盾）/H2（无 sizer/risk） |
| §9.1 全部 7 引擎"优秀" | **分歧（夸大覆盖）** | 只审 4/10；NTF"待审查"；Factors/Regime 无正文却优秀 |
| §9.1 含 walk_forward/forensics | **分歧（缺项）** | 未审 OOS/PBO/forensics |
| 独立评审 M3"LPPL MC 证伪 93%" | **分歧（方法缺）** | 无 MC 实现/零假设锚点 |
| 独立评审 M2（R² 尺度） | **分歧（尺度未标）** | 实际在 log 价格尺度 |

### 信号生成（S3）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| §0 aggregator 不存在 | 一致（补强） | 但主链是 `arbitrate_candidates` 非 `arbitrate()` |
| 适配器职责矩阵 | 部分一致 | 漏 min-cap（CZSC/QAR） |
| FSM action 映射 / Wyckoff 恒不产 SELL / NTF 0.6 | 一致 | 均确认；NTF 0.6 未标硬编码（补 M6） |
| §3.1 传播链 collect→arbitrate→run | **分歧（路径不精确）** | 主链 `arbitrate_candidates`（`research_pipeline.py:373`） |
| §4.1 质量门默认 R²=1.0"边界处理✅" | **分歧（误标正面）** | 缺数据=满分放行，违反 Rule 4；几乎不触发（死代码） |
| §4.2 Sell-Priority"SELL 始终优先" | **分歧（仅 arbitrate() 成立）** | 主链 `arbitrate_candidates` BUY 先短路（H1 实测） |
| §4.3 DecisionOutput 硬约束 | **分歧（与 §4.2 自相矛盾）** | 证实 BUY 短路 SELL |
| §4.4 ENGINE_PRIORITY | 一致（数值）补强 | 数值吻合；但 Rule 3 死代码、sell_priority=False 时 SELL 恒输 |
| §5-6 可观测性/典型路径 | 一致/部分一致 | 路径 1/3/4 吻合；路径 2 路径不同结论一致 |
| §7.1-7.2 CRITICAL/HIGH=无 | **分歧** | 漏 H1（Sell-Priority 活路径违反） |
| §9 健康度"优秀" | **分歧（降 B+）** | 漏 H1 与 M2-M6 |

### 回测撮合（S4）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| 七大防线 A-G / 涨跌停规则 / T+1 / 资金 / 快慢路径 | 一致 | 逐条确认 |
| M1 LPPL SELL 遗留 | 仍遗留 | `unified_engine.py:339-348`（分层违规） |
| L1 向量化 fill_buy 不查 T+1 | **分歧（设计合理）** | T+1 仅约束卖出，非 bug |
| L2 限价比例法（LOW） | **分歧（升 MEDIUM）** | 评审更准 |
| 评审(量化) H1"0 C/H 过松" | 一致 | 独立发现 3 HIGH 印证 |
| 评审(量化) M1 金字塔 win_rate | **分歧（不成立）** | `position==0` 守卫禁止加仓，max_position 恒 100 |
| 评审(量化) M2 30 日 0 元出清 | 一致且强化 | 记录 pnl -1000.51 vs 权益 -900.00，账目断裂 |
| 评审(量化) M3 固定印花税 | **分歧（不成立）** | 标量 `_execute_sell:643` 传 timestamp，实为时变；实测 8-27→10.0/8-28→5.0 |
| 评审(交易) M1 ST 快路径 | 一致（评 HIGH） | 实测 price/pre=1.05 快路径放行 |
| 评审(交易) M3 费率未写数值 | 部分分歧 | `cost_model.py:29-34` 有值，报告未列 |

### 风控合规（S5）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| §7.1 CRITICAL=无 | **分歧** | 漏 H1（gross 公式）/H4（KillSwitch Fail-Open） |
| §7.3 M1 VaR/CVaR 非真 EVT 已标注 | 一致（补 M1） | 但漏"空输入返回伪造默认指标" |
| §7.3 M2 缺空头检查（MEDIUM） | 一致（**升 HIGH**） | 根因是 gross 公式 `1+short_weight`，多头无约束 |
| §7.4 L1/L2 文档/字段名 | 一致 | drawdown/structural/sparse 仅 .pyc；中文字段名 |
| §8.1 已验证事实 | 一致（补 H4 反例） | T9a 仅 happy path；读失败 fail-open |
| §9.3 修复优先级 P1=空头检查 | **分歧（优先级）** | 应先修 H2（未接线）/H1（gross 公式） |
| 评审 H1 缺空头检查 | 一致（认同升级） | 并补充 gross 公式本身错误 |
| 评审 H2 sizer 放水 100 股 | 一致（新增 H3） | `arbitrator.py:404-406`/`unified_engine.py:367-368` |
| 评审 H3 无单仓上限 | 一致（H2 佐证） | 唯一 2.5% 上限在未接入的合规引擎 |
| 评审 M2 合规引擎是否接入 | 一致（H2 证实未接入） | `audit()` 仅 `manifest_generator.py:297` |
| 评审 M1 回测止损是否执行 | 一致（未执行） | `unified_engine.py:358` 写死 0.95；止损空转 |
| 需确认 risk_pct 生产默认 | 确认（0.05 vs config 0.1） | 生产 sizer 未读 config 10% |

### 服务编排（S6）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| 13 服务注册 ✅ | **分歧** | 实为 12 `register_factory`；factor_gate 非服务 |
| DAG 无循环 ✅ | 部分一致/分歧 | 注册层无环（一致）；docstring"零循环"与实际 2-环矛盾 |
| bind_orchestrator ✅ | 一致 | `service_container.py:135-136` + `engine_factory.py:23-34` 正确 |
| 6 事件发布顺序 ✅ | **分歧（严重）** | 顺序错；且事件从不发布、全库零订阅（H2） |
| 特性开关加载 ✅ | 部分一致 | signal_arbitration/factor_gate 正确；event_bus 死配置 |
| 懒加载 RLock 双检 ✅ | 一致 | 引擎工厂成立；`get()` 无锁成立（但应判 HIGH） |
| get() 无锁（MEDIUM） | 一致（**升 HIGH**） | 全部服务唯一入口 + 有状态 |
| ConfigValidator 仅告警 | 一致（纠正引用） | Rule 4 援引不准，属 Fail-Fast |
| MarketLevelCache.set_ntf / brain 绕过 _lazy_init | 一致 | L3/L4 |
| 评审 H1 get() 无锁判 HIGH | 一致 | 补充"latent"限定 |
| 评审 H2 失败传播 | 一致（降 MEDIUM） | 无原子回滚、_initialized 末尾置位 |
| 评审 M2 无 shutdown | 一致 | services/ 无 shutdown/close |
| （报告未覆盖）事件总线不接线 | **新增 HIGH** | H2 |
| （报告未覆盖）run_batch seed 死参数 | **新增 HIGH** | H3 |

### 研究控制平面（S7）

| # | 既有结论 | 独立裁定 | 说明 |
|---|---|---|---|
| 1 | 文档文件名 LOW | 一致 | `degrees_of_freedom.py` |
| 2 | 四阶门禁参数 | 一致 | Class A 阈值逐项吻合 |
| 3 | 参数来源"可辩" | **分歧（高估）** | 无引证/出处（M3） |
| 4 | Newey-West t | 一致 | `alpha_tier_engine.py:61-86` 正确 |
| 5 | BH-FDR Step-Up | 一致（实现正确） | 但"累积"效果受 H2 限制 |
| 6 | Rule 4 诚实门禁"完全符合" | 一致（None 情形合规） | |
| 7 | 依赖链"清晰" | **分歧（高估）** | 账本不持久化，门禁路径 p_adj=p_raw（H2） |
| 8 | Class B 缺输入→TIER_A | 一致 | `:578` 合理 |
| 9 | §4.3 CVaR 空尾部引用 | **分歧（范围外）** | 引用 `src/uniquant/risk/` 越界 |
| 10 | L2 Class B/C/D 硬编码 LOW | **分歧（升 MEDIUM）** | 实为全部硬编码（含 Class A） |
| 11 | 健康度"优秀" | **分歧（降 C+）** | 未核查生产接线/真实输入供给（C1/H1） |
| 12 | 评审 M1 门禁信任上游 | 一致 | 仅拦 None |
| 13 | 评审 M2 账本持久化未评估 | **裁定 HIGH** | 门禁路径未持久化每次新建（H2） |

### UI 展示（S8）

| # | 既有结论 | 独立裁定 | 说明 |
|---|---|---|---|
| 1-6 | 门面/组件化/Kill Switch/超时/状态隔离/依赖降级 | 一致 | 架构层结论成立 |
| 7 | CRITICAL=无 / HIGH=无 | **分歧（证伪）** | 漏 C1 + 5 个确定性渲染崩溃（H2-H5） |
| 8 | L1 简化信号（LOW） | **分歧（升 MEDIUM）** | 误导性展示 |
| 9 | L2 dashboard 1568 行超限 | 一致 | |
| 10 | 评审 H1 mock 默认伪装正常 | 一致（深化） | mock=True 硬编码 + np.random 伪造 + "真实数据"宣称矛盾 |
| 11 | 评审 H2 回测呈现缺席 | 一致 | UI 无 run_ticker_analysis/PipelineResult/PlotlyFigure |
| 12-14 | FSM 面板/空数据保护/报告正则 | 一致 | |

### 跨模块集成（S9）

| 既有结论 | 独立裁定 | 说明 |
|---|---|---|
| M1 LPPL SELL 优先级 | **仍遗留（证据需重述）** | 方向成立；但既有代码证据系虚构（无 priority 变量；真实为 reason 含 "lppl" 特判） |
| ENGINE_PRIORITY 表（LPPL=1 最高） | **分歧（方向颠倒）** | `arbitrator.py:32-42`：lppl=99 最低、fsm=1 最高、qar=3；键小写 |
| H1 数据入口 fetch_history | **仍遗留（描述性）** | 真实入口 `DataService.fetch_for_brain`/`fetch_research_pack` |
| "13 服务 + Portfolio/RiskEngine" | **仍遗留（事实错误）** | 实为 12 功能服务；无 PortfolioService/RiskEngine |
| M2/L2 enrich_lake_data 简化信号 | 仍遗留 | `ui/manager_logic.py:156-169` 非真实引擎输出 |
| L1 degrees_of_freedom_ledger.py | 仍遗留 | 实为 `degrees_of_freedom.py` |
| 9 列契约一致 / 9 适配器统一 / KillSwitch Fail-Closed | **一致（PASS）** | 三处跨模块契约健康 |

---

## 2. 汇总统计

| 模块 | 一致 | 分歧 | 已修复 | 仍遗留 |
|------|:---:|:---:|:---:|:---:|
| 数据流转 S1 | 3 | 4 | 0 | 10 |
| 分析引擎 S2 | 4 | 2 | 0 | 14 |
| 信号生成 S3 | 12 | 6 | 0 | 10 |
| 回测撮合 S4 | 8 | 5 | 0 | 10 |
| 风控合规 S5 | 6 | 5 | 0 | 10 |
| 服务编排 S6 | 8 | 4 | 0 | 18 |
| 研究控制平面 S7 | 5 | 5 | 0 | 9 |
| UI 展示 S8 | 11 | 2 | 0 | 19 |
| 跨模块集成 S9 | 3 | 3 | 0 | 9 |
| **Σ** | **60** | **36** | **0** | **109** |

> 一致 60 项多为机制/事实层（可复现）；分歧 36 项集中在**定级（过松/过紧）、计数、路径、
> 覆盖（漏审）、证据（虚构/方向颠倒）、自相矛盾**；已修复 0 项（`src/` 为空 diff）。

---

## 3. 结论

1. **既有报告事实层质量高**（60 项机制/事实一致），但**结论层系统性高估**（36 项分歧）。
2. **"0 CRITICAL / 0 HIGH / 全优秀"不成立**——9 模块独立复核均发现既有报告未捕获的
   CRITICAL/HIGH，集中在**生产接线与活路径语义**。
3. **已修复 0 项**：基线 `434aab1→b1d2415` 对 `src/` 为空 diff，全部问题仍遗留。
4. **最突出系统性问题**：多条 N2N 关键路径存在"**防线存在但未接线**"（合规引擎、AlphaTierEngine、
   事件总线、仲裁活路径、UI 校验/渲染、pre_close 传播）。
