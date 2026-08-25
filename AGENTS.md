# AGENTS.md - UniQuant Project Control Context

> ⚠️ **MUST READ FIRST** — Read `CLAUDE.md` in the project root before any other file. It contains the 10 coding rules that govern all code generation in this project. Every edit, test, and commit must follow those rules. Treat them as non-negotiable.
>
> UniQuant: A-share quantitative research and trading platform.
>
> **Updated 2026-08-25 (P10/D+10 容量验证 + 工程化落地)**: H-A 工程化两件套。**(1) 全市场容量验证（预注册 F1-F3）**：全市场 4943 只同参重跑——年化 +9.98%/夏普 0.93/回撤 −22.2%，对照 500 采样同代码路径 +13.18%/1.08（P8 原始 +15.82%/1.33）→ **采样含幸运成分，真实预期应以全市场口径为准**；F1(夏普≥1.0)差线 FAIL、地板块（2000万 ADV 地板）夏普 0.78 但回撤减半至 −12.8%→F2 按冻结判据 FAIL（illiq alpha 恰在小盘尾部，地板剔 alpha）；**容量画像：持仓名单 ADV 合计中位 ~28.5 亿/日，按 10% 参与率折算策略容量 ≈ 2850 万元级**——散户/小资金可执行，机构不可直接承载。产物 `capacity_validation.json`。**(2) 每日信号运行器 `daily_signal_ha.py`**：状态判定(MA200+PIT波动分位)→空仓或 Top30 目标组合 JSON 输出，实测当前(2026-07-23)处于过热牛态并产出 30 只目标（合格池 5033）。**(3) unified_engine 适配器 `ha_unified_adapter.py`**：将 H-A 持仓决策转换为 TradingSignal 序列，验证 5 只股票通过引擎完整回测（含万三佣金、万五印花税、千一滑点、单笔最低 5 元），集成路径确认可行。工程化剩余缺口：全股票聚合回测、实盘对账监控。
> **: H-A 工程化两件套。**(1) 全市场容量验证（预注册 F1-F3）**：全市场 4943 只同参重跑——年化 +9.98%/夏普 0.93/回撤 −22.2%，对照 500 采样同代码路径 +13.18%/1.08（P8 原始 +15.82%/1.33）→ **采样含幸运成分，真实预期应以全市场口径为准**；F1(夏普≥1.0)差线 FAIL、地板块（2000万 ADV 地板）夏普 0.78 但回撤减半至 −12.8%→F2 按冻结判据 FAIL（illiq alpha 恰在小盘尾部，地板剔 alpha）；**容量画像：持仓名单 ADV 合计中位 ~28.5 亿/日，按 10% 参与率折算策略容量 ≈ 2850 万元级**——散户/小资金可执行，机构不可直接承载。产物 `capacity_validation.json`。**(2) 每日信号运行器 `daily_signal_ha.py`**：状态判定(MA200+PIT波动分位)→空仓或 Top30 目标组合 JSON 输出，实测当前(2026-07-23)处于过热牛态并产出 30 只目标（合格池 5033）。工程化剩余缺口：分钟级执行/滑点模型、实盘对账监控、unified_engine 接入。
>
> **Updated 2026-08-25 (P9 隔夜/日内因子: 短窗口 OOS 全败 + 日内动量反向发现)**: 分钟数据审计后 A+B 双源落地——B=本机 Wine 通达信客户端 6.1GB（5186 只 .lc5，破解量纲陷阱：OHLC 字段为压缩轨迹不可用、bar 级 VWAP=amount/volume 真实可用），A=服务器分页拉取 492/500（重叠期相关=1.0、scale=1.0，接缝 QA PASS）。拼接窗口 **287 天（2025-06-24→2026-08-25）**。预注册三因子验证：**F1/F2 隔夜动量无信号**（|t|<1）；**F3 日内动量强反向**——fwd5 IC=-0.0522(t=-2.85)、fwd21 -0.0655(残差 -2.60)，前后半一致，方向与预注册(+1)相反 → 按纪律判 FAIL；"日内动量为正"的美股文献前提在 A 股同样被反转结构覆盖，与 P3/P5 第三方收敛。产物 `overnight_validation.json`、`lc5_reader.py`/`convert_local_lc5.py`/`fetch_minute5_server.py`/`run_overnight_validation.py`。⚠️ 边界：单 regime 窗口、287 天功效有限。至此 P1-P9 完成九轮证伪闭环：**唯一幸存策略 = H-A 条件 illiq（P8 已验证可交易形态）**。
>
> **Updated 2026-08-25 (P8/D+9 组合层验证: H-A 可交易性确认)**: 按预注册（脚本 docstring 冻结）执行三臂对照组合回测（500 只剔金融、Top30 等权、5 日再平衡、涨停不可追、单边 15bp 成本、近收盘成交假设）。**STRAT-A(条件 illiq)：年化 +15.82%、夏普 1.33、回撤 −12.9%、在场仅 17%**。分解：Q1 扣成本正收益✓；Q2 择时增量=夏普 +0.68 且把无条件版回撤从 −43.7% 压到 −12.9%（条件化本质是风控叠加）；Q3 选股增量=夏普 +0.73（vs 状态内随机 +6.9% 年化）——择时与选股贡献独立且同时为正。CTRL-B 无条件 illiq 年化 +13.97%/夏普 0.65/回撤 −43.7%；CTRL-C 随机 6.89%/0.60。产物 `results/factor_mining/portfolio_validation_ha.json`，脚本 `scripts/canslim/run_portfolio_validation.py`（19 个状态片段/均长 14 天）。⚠️ 边界：收盘成交假设乐观项已披露、500 只非容量结论、幸存者偏差未含下界修正。下一步=①隔夜因子（分钟数据审计已启动）。
>
> **Updated 2026-08-25 (P7 条件信号定向验证: H-A 幸存)**: 按 P6 预注册流程执行定向验证（`run_conditional_validation.py`，预注册文档 CONDITIONAL_VALIDATION_PREREGISTRATION.md 先行冻结）。**裁决=H-A(illiq_20d @ trend_on∧vol_high, fwd5) 四门全过且在 PIT 状态下幸存**——研究程序启动以来首个通过完整验证的信号。门级（500只，PIT 状态）：IC=+0.0811、NW-t=+5.3(≥3✓)、动量残差 NW-t=+5.6(≥2✓)、块自助 CI=[+0.052,+0.116]全正✓、前后半 [0.112,0.051] 同号✓；PIT≈FULL(+0.113) 排除阈值后视伪影。经济叙事：过热牛市投机资金涌入低流动性股，Amihud 溢价集中兑现；控动量后更强 → 非 P3 动量 beta 家族。**H-B(roe翻转) 双腿败**(长腿 PIT NWt=+0.2 全灭、短腿 −1.9<−3)——按预案不保留胜腿叙事；**H-C(c_single@平静牛) 差线败**(NWt=+2.2<3，其余三门过)。⚠️ 边界：vol_high 态仅占 ~8% 时间（策略多数时间空仓）；IC≠可交易性，组合层（成本/换手/容量）待立项。下一步=D+9 组合层验证或转 ①隔夜因子。
>
> **Updated 2026-08-25 (P6 Regime 条件化诊断: 条件信号存在)**: 按"②regime 分层→①隔夜因子"组合推进第一步。`run_regime_conditional_ic.py`（预注册状态定义：沪深300 MA200 趋势 × 波动三分位，fwd5/fwd21 双视野，|t|≥3 高亮阈值）跑 26 因子×2 视野×6 状态格（500 只，223s）。**裁决=候选条件信号存在**（高亮 240 单元），三大模式：(1) **illiq_20d@(trend_on∧vol_high) IC=+0.1118(t=+10)**——流动性溢价在过热牛市放大 2.4 倍；(2) **roe 跨状态翻转**——trend_on|vol_low +0.032(t=+5.7) vs trend_on|vol_high **−0.129(t=−11.8)**（fwd21）："投机狂热杀质量、平静牛市奖励质量"；(3) c_single_yoy 同构翻转(+0.053 vs −0.027)。反转族(rev_20d)在 vol_high 态最强(+0.095)；动量族全状态恒负 → 反转结构与 regime 无关。产物 `results/factor_mining/regime_conditional_ic.json`；测试 5 用例。⚠️ 诊断性研究：候选信号须走定向四重门验证（含状态内 ICIR/PBO/动量残差）方可成为策略声明。下一步=三大候选的定向验证预注册。
>
> **Updated 2026-08-25 (P5 CANSLIM D+4 生死判定: 路线终止 + 成长陷阱实证)**: 红蓝对抗修订方案后按 MVP 流程执行因子轨四重门（497 只×21 窗，222s，`scripts/canslim/`）。**H1(C)=FAIL ∧ H2(A)=FAIL → 预注册早出口触发，CANSLIM-A股路线终止**。门级：`c_single_yoy`@fwd5 最接近（IC+0.012✓ PBO 0.166✓ 但 ICIR 0.42/动量窗比 0.62 差线）；**核心发现=A股"成长陷阱"实证**——a_cagr3 fwd63 IC=−0.0808(ICIR−0.93)、roe −0.0780、事件法全负、控动量后更负 → 历史高成长/高 ROE 在本窗口强负向预测，与 P3 反彩票+连板网"反转市"三方收敛；CANSLIM"买盈利加速者"前提在 2019-10→2026-05 窗口结构性反向。金融名单冻结 `scripts/canslim/financial_codes.json`(79 只名称验证)；成长边界规则模块 `growth_factors.py` 9 用例。观察性备注："反向 CANSLIM"假说存在但属事后想法，任何后续须全新预注册。详见方案文档 §8。
>
> **Updated 2026-08-24 (P4 财务数据底座落地)**: 基本面赛道数据就绪。**TDX 季度财务归档全量拉取完成**：`scripts/factor_mining/fetch_financial_data.py`（mootdx affair，147 期中取 2016Q1→2026Q2 共 42 期）→ **`data/lake/financial/` 5211 只 × 42 季 × 577 列，2.4GB**。**三重验证闭环**：①桥接契约程序化核对——25/25 字段与 `alias_to_standard` 严格命中、零 rename；②双源交叉验证——vs 东财线上四接口 12 股抽样，11 字段 100% 精确一致 + 公告日期 12/12 吻合（全部差异均为已知口径差：东财 lrb"净利润"=归母口径、revenue 主营 vs 总营收、银行科目）；③端到端锚点——茅台 EPS_TTM@FY2024=68.64 恰为全年 EPS。**实施中发现并修复真 bug**：`FinancialFactorBridge.calculate_eps_ttm` 把同年累计值(YTD)当单季 naive rolling-sum → EPS_TTM 虚增约 4×；修复为年边界差分单季再滚动（跨年 Q1 重置），`TestCumulativeToTTM` 4 用例锁证 + 旧测试语义修正。关键实现细节：公告日期 YYMMDD 浮点必须转 YYYYMMDD 整数（否则桥接 fullmatch 全 NaT）、列名 strip+重复列去重、920xxx 无后缀规则剔除(338)。方案全文 `docs/analysis/FINANCIAL_DATA_ACQUISITION_PLAN.md`（v3 复核修正 + §6 交叉验证 + §7 实施结果）。下一步：基本面因子实现（SUE/应计/ROE/资产增长/EP）走同款 Walk-Forward 四重门。
>
> **Updated 2026-08-19 (因子挖掘 P1 baseline + P2 GP 全量 + P3 逻辑因子)**: 因子挖掘三步完成。**P1 基线** + **P2 GP 挖掘**（前两段同前）。**P3 逻辑驱动因子方向族**：按文献调研 `docs/analysis/LOGIC_FACTOR_RESEARCH_PLAN.md` 实现 7 个新因子（`max_ret_20d`/`reversal_1d`/`amivest_20d`/`range_20d`/`skew_20d`/`reversal_5d`/`reversal_20d`），Walk-Forward 504/63 窗测试（500 只 × 1600d，与 P1 同面板）。**通过四重门 2 个**：`max_ret_20d` IC=-0.0764 ICIR=-11.50 PBO=0.166（最强信号，MAX 效应）、`skew_20d` IC=-0.0316 ICIR=-6.54 PBO=0.166（偏度效应）。**关键发现**：`max_ret_20d` 的 OOS IC 绝对值超越基线最强因子 `idiosyncratic_vol_20d`（0.0764 vs 0.0780），且 PBO 更优（0.166 vs 0.419）。反转族（`reversal_1d`/`5d`/`20d`）IC 均为正但 PBO 偏高（0.307-0.669）未通过。`range_20d` IC 强负（-0.0625）但理论方向错误（高波动→低收益，反彩票解释成立）。**动量残差校验（P2 同款）**：追加控制 20d 动量后，`max_ret_20d` 和 `skew_20d` 的残差 IC 翻正（+0.0486/+0.0165）→ 负 IC 完全由动量驱动，动量门不通过。结论：**无因子通过全部四重门（含动量残差）**，A 股截面预测力高度集中于动量。详见 "P3 逻辑因子" 段。
>
> **Updated 2026-08-18 (因子挖掘功能核查)**: 因子系统**完整存在 + 生产已接入非废弃**——`brain/factors/` 8 模块 2265 行全可用（registry 注册中心 + analyzer IC/IR/前视检测 + composer Z-score/正交化/IC加权 + **13 因子** auto-register + financial_bridge TTM/PE_PB merge_asof + walk_forward 管线 + neutralizer），生产接线确认（`scan_service.py:16-18` build_factors→analyze_factors→compose_scores、`service_container.py:159`、`config_validator.py:109` WS7-002、`screener.py:169`）。GP 自动挖掘在 `experiments/gp_factor_mining/`（研究工具，非生产）；walk_forward 有测试但 src 无调用=扫描工具。**衔接点**：因子管线经 `storage.get_symbols()` 读全池，P0 指数净化未覆盖该路径，符号池是否含 554 指数待单独核查。详见 "Recent Work (2026-08-18) — 因子挖掘功能核查" 段。
>
> **Updated 2026-08-18 (P0 数据净化 + 进程池入仓)**: 第一性原理研究（`docs/analysis/WYCKOFF_FIRST_PRINCIPLES_20260818.md`）发现指数文件未归档（daily/ 仍含 554 指数文件，archive_index/ 为空），`load_symbols("all")` 未过滤指数 → 全量扫描池 5755 只含 554 指数。修复：符号级 `_is_index`（SH 000xxx/399xxx 判定，不误杀 SZ 主板股）+ `all` 分支过滤 + 删除裸前缀 `_INDEX_EXCLUSIONS`（曾误杀 000001.SZ 等）；`wyckoff_full_scan.py` 线程池→**进程池入仓**（`ProcessPoolExecutor` + `_worker_init` 每进程独立引擎，消除 `_code_prefix` 竞态，~64s/窗 32 workers）。5 窗净化重扫 → 5201 只×39 列（旧 5755 备份于 `/tmp/opencode/wyckoff_fix/old_scans_p0/`）。**验证：T1 n_buy 82/23/66/166/118 与基线一致（指数零影响）**（⚠️ 后经"下游裸前缀缺陷修复"段修正为 86/27/69/174/123）、T3 维持 1/5 FAIL（X4 候选）、golden gate PASS、deterministic PASS、direction_map_check 5/5 PASS、275 tests passed、ruff 0。详见 "Recent Work (2026-08-18) — P0 数据净化" 段。
>
> **Updated 2026-08-18 (全量重跑暴露下游裸前缀缺陷 + T1 基线修正)**: P0 净化后全量重跑统计脚本时发现 **P0 修复漏网——方向一致性同源缺陷残留 6 处下游脚本**：`direction_map_check.py:32`/`confidence_survival.py:29`/`buyset_momentum_residual.py:108`/`momentum_residual_analysis.py:140`/`validate_ranking.py:37`/`_common.py:29` 均用裸前缀 `("000","399")` 剔指数 → **每窗误杀 414 只 SZ 主板股票**（000001.SZ 等）。修复：新建共享 `scripts/wyckoff_experiments/_symbols.py`（`is_index_symbol` 符号级判定，语义与 `wyckoff_full_scan._is_index` 一致）+ 6 处替换 + 新测试 `tests/scripts/test_wyckoff_symbols_index.py`（20 用例）。**T1 基线修正**：n_buy 82/23/66/166/118 → **86/27/69/174/123**，clean 池 n 4762/4773/4766/4719/4670 → **5174/5185/5178/5133/5084**（+412/窗 误杀股票回归）。**统计结论不翻转**：T1 5/5 PASS、T2 0 upgrade、T3 仍 1/5 FAIL（X4 r3=+4.54 p=0.0002，此前 +5.30 p=0.0）、F7 PASS、T4/T5 维持 FAIL（P1-1 撤回/P1-11 默认关维持）。详见 "Recent Work (2026-08-18) — 全量重跑 + 下游裸前缀缺陷修复" 段。
>
> **Updated 2026-08-18 (P1 幸存者偏置定量披露 + 开放项#2 box 核验)**: P0 后完成第一性原理研究开放项 #3——**幸存者偏置定量披露**：按 type=1 纯股票口径（`all_stock_codes` 退市股票仅 337 只，非全表 1176）实测 5 窗覆盖率 **0.999–1.013**（W1 5196/5201、W2 5194/5193、W3 5201/5208、X4 5194/5152、X5 5190/5122）→ 幸存者偏置影响 ~0.3%，**推翻**早期"0.73-0.78 覆盖比"的假偏置（那是把基金/转债/指数混入分母）；预注册文档 `scripts/wyckoff_experiments/PREREGISTRATION_20260812.md` 已补每窗覆盖表 + n 更新（5755→5201，T1 实测 n 4762/4773/4766/4719/4670），第一性原理文档 §6.3/§9 同步关闭。**开放项 #2 核验（box 全局步长）**：`pnf.py:27` `_fixed_step` 用全序列中位价，770 只（15%）价格跨 >8 倍；极端 600602.SH（p5=1.92→p95=2587）全局 step=¥0.0745 → 低价段 1.95% 粒度/高价段 0.39% 过密（箱数 33 万）→ **真实简化缺陷**，影响 phase_hint/count_target/congestion_zone 三处标注输出；判定为"标注层已知限制，待专项分段-box 修复"，不产方向故不改引擎。详见 "Recent Work (2026-08-18) — P1 幸存者披露" 段。
>
> **Updated 2026-08-18 (TRIAD-VSA 量价结构标注器)**: 新建三假说正交混合检测器（流体力学驻点滞止 A × 热力学熵/潜热 B × 贝叶斯吸收滤波 C，`triad_abs=(A·B·C)^(1/3)`），纯标注恒无方向（`audit_no_direction` 契约）。三大契约：全因果 trailing（前缀不变性测试）、涨跌停/零量=非有机而平盘非涨停棒保 organic、数值全 ∈[0,1]。TDD 红绿闭环修复 5 个真实缺陷（贝叶斯 warmup NaN 传播毒化→携带状态版；scale 维度错误→分数 ATR `atr/close`；B 通道净流 m_star=0.5 门槛；平盘棒误标 structural；误删 import sys）。`tests/scripts/test_triad_vsa.py` **21 passed**（-W error 零警告）、tests/scripts 全目录 90 passed、ruff 0、Wyckoff 关键回归 31 passed。详见 "Recent Work (2026-08-18) — TRIAD-VSA" 段。
>
> **Updated 2026-08-18 (全量 5 窗重跑 + structural_score 非确定性根因修复)**: 按用户要求重跑全量 Wyckoff 数据分析前对并行/内存利用做出评判并落地修复：(1) **并行利用评判**：`wyckoff_full_scan.py` 用 `ThreadPoolExecutor`(默认 8 workers) 跑 CPU 密集引擎——GIL 使纯 Python 计算串行，32 核机器实测 8→32 workers 无增益（200 只 31.5s→28.7s），而 `ProcessPoolExecutor` 32 workers 仅 1.9s（**线程池慢 ~15 倍**，全量 5755 只从 ~15min/窗降至 72-78s/窗）；(2) **共享引擎竞态确认**：`engine.py:320-321` 每 analyze 写 `self._code_prefix`，被线程并发下 `_step5`(:1586 涨跌停守卫) 与 `detect_limit_moves`(:2101) 读取 → 688/300 等 20cm 规则可能套到主板股票，旧 CSV（8/7 线程池产物）存在此污染；(3) **根因修复（引擎级 bug）**：`_compute_structural_score` 经共享 `self._wss_scorer` 调 `score_sequence`，而 `WSOScorer.score_events`（`sequence.py:90-96`）维护跨调用 EMA 状态 `_last_score/_is_warm`——同一输入在引擎分析过别的股票后得分漂移（实测 000001.SZ 59.03↔61.41）；修复：WSS 分支改用冷启动 `WyckoffScorer(wss_lookup=scorer.wss.lookup)`（复用 lookup 引用，不触发 EMA 累积），新增 `tests/classic_wyckoff/test_structural_score.py` 回归用例 `test_structural_score_shared_engine_cross_call_deterministic`；(4) **全量重跑落地**：临时进程池 runner（/tmp）复刻 as-of 逻辑重跑 5 窗，修复后引擎两次运行 0 差异，`results/wyckoff_xs*/wyckoff_scan_all.csv` 全部更新为 39 列确定性版本（旧 25 列 8/7-8/12 版本备份于 `/tmp/opencode/wyckoff_fix/old_scans/`）；实验/验证脚本全复跑：**T1 PASS（n_buy 82/23/66/166/118，SELL 恒 0）**、**T3 1/5 FAIL**（X4 唯一 PASS r3=+5.30 p1=0.0）、**F7 PASS**、**T2 0 upgrade_candidates**、golden/deterministic/seal **PASS**、direction_map_check 5/5 PASS、classic_wyckoff **170 passed + 1 skipped**、ruff 0。**归因**：W3/X4/X5 n_buy 与 AGENTS 基线仅差 0-2 只（66/167/120 vs 66/166/118，= 线程竞态消除修正）；W1/W2 大幅减少（137→82、40→23）是因为 8/7 旧引擎产物 vs 当前引擎（P0 direction gate + accumulation_downgrade + A股铁律守卫更保守），判定不翻转。详见 "Recent Work (2026-08-18)" 段。
>
> **Updated 2026-08-14 (P0+P1 全量回归核验完成 + bias200 标注缺陷修复)**: 对 P0 七项 + P1-3~12 实施做全量回归与真实数据核验：全量 **2107 passed / 8 skipped / 0 failed（+3 新测试），0 ruff**；golden_20 扫描（`scripts/wyckoff_full_scan.py` 扩展透出 sos_candidate_detected/evr_*/pattern_failure_*/no_supply/nsd/vdu/event_cooldown/range_score/avwap/bias200 14 标注列）确认标注面真实产出（sos=True 2/20、evr 非 none 3/20、pattern_failure 3/20、event_cooldown 7/20、range_score/avwap 全正常）。**发现并修复 bias200 标注缺陷**：`_build_report` 收到 `frame.tail(lookback=120)`（`ENGINE_DEFAULT_LOOKBACK_DAYS=120`），`len(df)>=200` 恒 False → bias200 恒 0.0；修复：`_analyze_single` 截断前保存 `full_frame` 传入 `_build_report`（`full_frame` 参数），bias200 基于全量 MA200，新增 `tests/classic_wyckoff/test_p1_12_bias200.py` 3 用例（长历史非零=手工 MA200 一致/短历史零/Output round-trip）。`evr_position_context` 留空符合定稿 P1-4 "接入点需等 per-bar 化" 设计。B3 检查同步更新允许键集（含 P1 标注键 + 无关 engine 键泄漏负向断言），B1-B8 全 PASS。验证脚本复跑：F7 PASS、T1 PASS、T3 1/5 FAIL（X4 候选）、C1/C3/D1-D3+golden PASS、V1-V5 全 PASS。详见 "Recent Work (2026-08-14) — P0+P1 全量回归核验" 段。
>
> **Updated 2026-08-12 (Wyckoff P0 信号链根除实施完成 + 验收 PASS)**: 按 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` §5/§8 完成 P0 七项实施——P0-1 direction 透传（`WyckoffOutput.direction` + `wyckoff_direction` roundtrip + `_extract_from_report` 提取 MTF 融合后 direction + pack_writer 写入）、P0-2 adapter direction gate（`_ENTRY_DIRECTIONS={做多,买入,轻仓试探}`→BUY 其余→None，删 phase/spring/utad 直映射，读 `direction_gate_enabled:true`）、P0-3 RDP 仅展平 wyckoff 键（`pack_writer.py:114-124`）、P0-4 置信门槛 0.40（`confidence_gate`）、P0-5 `structural_adjust_enabled:false` 默认关（`_apply_structural_adjustment` 门控于 engine.py:452，structural_score 仍作叙事字段回填）、P0-6 `normalizer._DIRECTION_MAP` 6 项全置 0 + `scan_signal` 抵销（仅 direction∈{做多,买入,轻仓试探} 且置信≥0.40→BUY，恒不产 SELL）、P0-7 恒不产 SELL-as-entry。config wyckoff 段新增 `direction_gate_enabled/confidence_gate/structural_adjust_enabled/stoploss_guard_*`（P1-11 默认关参数化声明）。测试同步：`tests/signal/test_adapters.py` 15 用例改新语义、`tests/test_signal.py`/`test_e2e_integration_qa.py` direction 断言 1→0、`test_p3_markup_rs.py` fixture 固定 structural_adjust 语境、新 `tests/test_wyckoff_p0_direction.py` 9 定向用例。**全量 2092 passed / 8 skipped / 0 failed，0 ruff，golden_20 baseline 4 标量全一致**。实地验证 `scripts/wyckoff_verify_20260812/` 六脚本（A 组 F7/T1/T3 复现、B 组 B1-B8 实现状态、C 组 SELL 密封+P1 标注面、D 组三层验收门+golden 门）全部跑通：A 组 F7 **PASS**（无信号类达 4/5 升级线；**口径披露：定稿 F7 表 W1-W3 为指数中性超额口径与 X4/X5 原始口径混用，一致口径下 leader 同号负显著 3/5 窗例外，表述应改为"无 2/3 多数同号"**）、T1 **PASS**（137/40/66/167/120 SELL 全 0）、T3 **1/5 FAIL**（X4 +4.96 p=0.0001 候选跟踪）、B1-B8 **PASS**、C1 **PASS**/C2 INCONCLUSIVE（P1-3 留待 P1 阶段）/C3 **PASS**、D1-D3+golden **PASS**。报告 `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md`。P1 余项（P1-3 sos 独立字段 / P1-4~12 标注 / P1-11 功能）按 §8 顺序后续实施。详见 "Recent Work (2026-08-12) — Wyckoff P0 实施完成" 段。**Updated 2026-08-12 (Wyckoff 深度验证 V2 执行完成)**: 5 路并行 subagent 深度验证 P0 实施 + 1 项修复：V1 F7 口径统一稳健性 (PASS, leader 3/5 全剔尾边界稳健)；V2 P0 后方向映射实证 (PASS)；V3 X4 多重检验审计 (PASS 维持候选, 效应由最低 relmom 桶驱动→修正标签"牛市超跌反弹")；V4 全信号链泄漏审计 (PASS, 220 单元格 0 SELL, arbitrator Wyckoff SELL=dead code)；V5 A股铁律交互 (修复→PASS, 发现涨停守卫缺口—engine.py 缺 LIMIT_UP 守卫, 单涨停日+MARKUP 相位→BUY 泄漏)。修复：engine.py _step5_trading_plan 加 LIMIT_UP/BREAK_LIMIT_UP 守卫 + 精确价差容差 0.5%, 新增 tests/classic_wyckoff/test_limit_up_guard.py 3 用例。**2104 passed / 8 skipped / 0 failed, 0 ruff, golden 门一致**。详 docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md §7。
>
> Generated: 2026-07-13. **Updated 2026-08-12 (Wyckoff 深入再研究定稿)**: 对 08-12 正确实现方案完成深入再研究（Phase 0 代码扎根 F1-F9 + Phase 1 五路 subagent 审计 + Phase 2 预注册 5 实证脚本 + Phase 3 补两个老窗口全量 as-of 扫描 X4 2025-06-30/X5 2024-12-31 各 5755 只 + Phase 4 四轮红蓝对抗），输出修订版 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md`。**增量事实 F11-F19**：direction 消费者不止旧离线回测（`brain/wyckoff/analysis.py:274-294` MTF 融合 + dashboard 展示）；RDP 下全引擎网都不进 TradingSignal 链；`sos_candidate` 已被 markup 分支占用 signal_type (engine.py:1684/1708)；老窗 fwd_60d 覆盖 98.8%/98.0%（W1/W3 为 0%，原 F10"重叠过半"表述错误→实际日重叠 0/10/0% 输入 ~99.7%）；**F7 五窗复核：六类信号全无跨窗同号显著** — markdown 被 X5 剔尾 +1.28%(p=0.002) 推翻"唯一稳健风控"、leader X5 翻负(p<0.0001)、accumulation X4 正显著(p=0.0005) vs W1-3 负、markup X5 负显著(p=0.011) → 相位方向跨 regime 全面不稳定，叙事层裁决 5 窗加强成立。实证裁决：T1 direction map **5/5 PASS**（BUY 137/40/66/167/120、SELL 全 0、0.40 门槛 X5 拦 37%）、T2 置信度零排序力（0 upgrade）、T3 BUY 集 **1/4 窗独立增量 FAIL**（X4 p=0.0001 单窗显著→记"牛市 beta 待复验候选"）、T4 ATR 漂移 44/56/23% 全破 5% 红线→**P1-1 撤回**、T5 止损 W2 45%/46.7% 过度触发→**P1-11 改默认关+参数化**s(config `stoploss_guard_*`)、P1-3 改独立布尔字段 `sos_candidate_detected` 不复用 signal_type。P0 七项全部确认。实施顺序 P0-1/2/6→P0-3→P0-4/5/7→P2 验收→P1-3→P1-4~12（P1-1 撤回/P1-11 默认关）。详见 "Recent Work (2026-08-12) — Wyckoff 深入再研究定稿" 段。**Updated 2026-08-12 (Wyckoff 正确实现方案定稿)**: 4 路并行 subagent 代码审计 + 3 路独立红蓝对抗（引擎现实/实证证据/外部最佳实践），输出定稿 `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md`：引擎正确目标态 **= 叙事 + 风控层，完全不产方向入场信号**。新事实：Wyckoff 信号在默认 `use_research_data_pack:true` 下整体不进 TradingSignal 链（三层绝缘 + 未展平）；`V3TradingPlan.direction` 无处消费（唯一消费者是旧离线回测）；extra 两处相位→方向残留（`signal/normalizer.py:115-122` `_DIRECTION_MAP`、`engine.py:2040-2051` `scan_signal`，共三套映射）；**一切声明剔尾复核（F7）：distribution/markdown/leader/accumulation/markup/spring 六类信号剔尾后均无同号显著** — distribution 禁做空依据从"显著正"降为"≈0 无依据"、markdown"唯一稳健方向"与 leader"接入 adapter"均过强；ConfidenceLevel 无 B+（"B+=0.55"幻影）；unified_engine SELL=只平仓语义。**P0 信号链根除**（direction 透传→adapter direction 优先删 phase/spring/utad 直映射→RDP 仅展平 wyckoff 键→置信门槛 0.30→0.40 且主靠 direction gate→默认关 `structural_adjust_enabled`→normalizer/scan_signal 残留抵销→恒不产 SELL-as-entry）。**P1 标注增强**（ATR 相对化+影线比、一字板守卫、`_detect_sos` 填 UNKNOWN 候选、EVR 三态×5档、图式失效 0.33、NoSupply/NSD/VDU、eventCooldown、rangeScore/AVWAP 叙事面禁回流结构分、sequence 软标注权重0、止损触发层限位、bias200 改风控注释）。**P2 验证门**（补 2025-06-30/2024-12-31 老窗、三层验收门[确定性断言+预注册 MWU p≥0.05@≥2/3窗+markup 存活表]、BUY 集动量残差、证伪代码入仓、golden baseline 门）。8 项明确不做：bias200 过滤、板块缩放、序列序进分、95分位硬门槛、creek gate、leader 接入 adapter、研究管线 2.02 融合、compression。实施顺序 P2-4→P0-1/2/6→P0-3→P0-4/5/7→P2 验收→P1-1/2/3→P1-4~12。详见下方 "Recent Work (2026-08-12) — Wyckoff 正确实现方案定稿" 段。**Updated 2026-08-11 (研究全景归档)**: 为 docs/ 下 60+ 篇 Wyckoff 研究文档建立统一归档入口 `docs/analysis/WYCKOFF_RESEARCH_MASTER_SUMMARY.md`（7 阶段：早期/基线/红蓝WF/Classic合规/相位再平衡/方法论/对抗残差），含 Compliance 演进链 17%→58.3%、研究管线 vs 生产对比（Sharpe 2.02 vs 一致性 50%）、三波证伪证据与完整文档清单。**Updated 2026-08-09 (方法论多轮对抗判定)**: 对方法论 12 路红蓝对抗 + 独立第 3 窗（W3 as-of 2026-05-29 全量 5755）：方法论核心（状态≠方向≠排序、结构分弃用、markdown 风控）成立；但 **alpha 轴错位——`RS=leader ∧ DISTRIBUTION` 三窗 +5.85/+4.09/+9.07（MWU p<0.01）初判为真信号，随后动量残差研究 (2026-08-09) 证伪其独立增量（控动量剔右尾后 2/3 窗归零，见 "动量残差研究" 段）**；leader×spring 也证伪（spring 消解 alpha）、结构分弃用成立。最终：Wyckoff 相位/spring 均无独立正 alpha，引擎降为叙事/风控层。**Updated 2026-08-07 (红蓝对抗验证落地 §六)**: 双窗口全量 as-of 回放（W1 04-30 n=4762 / W2 03-31 n=4773，市场中性超额收益）红蓝对抗验证：structure_score IC 双窗符号翻转（-0.083→+0.032）实为"不稳定"非"无差"→ 废弃当排序器；distribution 超额为正（+0.84/+0.77 双窗复现）反做空错；accumulation 超额为负（-1.87/-1.37）蓄势不涨；leader 双窗显著（MWU p<0.001）唯一真信号。落地 `engine.py`：新增 `_downgrade_direction` + `config wyckoff.accumulation_downgrade=true`，ACCUMULATION 多头方向降 1 档（做多→轻仓试探/轻仓试探→观察等待），distribution/markdown 禁做空已硬编码（步骤5 + rule2）。新增 9 测试 `test_accumulation_downgrade.py`，163 passed / 1 skipped / 0 ruff。详见下方 "2026-08-07 — 红蓝对抗验证 (WYCKOFF_VERIFICATION)" 段。**Updated 2026-08-07 (WSS 启用后全量扫描核验)**: 对照 2026-08-02 档案核验 WSS-ON 全量 5755 只 — A级置信 0→96、B级 1.6%→13.2%、结构分 max 64.4→77.7、≥70 达 300、spring→轻仓试探 15/36（P0 传导修复）、置信vs结构 pearson -0.024→+0.023。fwd 收益需 as-of 回放模式补充。as-of 验证结论：markup/accumulation 方向正确，但 distribution/markdown 20d 看跌背离仍存（+14.5%/+11.2%，已知局限）。详见下方 "2026-08-07 — WSS 启用后全量扫描核验" 段。**Updated 2026-08-07 (WSS 全量训练完成 P1-1 落地)**: 修复 phase1/phase2/phase_e 目录创建缺陷 + runner_v4 检查点 dataclass bug；小样本冒烟→全量 1000 只 runner_v4(87977 obs/11178 spring)+phase2+phase_e → **418 seqs** `wss_lookup_v2.json`；`config wyckoff.wss_enabled=true` 开启，A/B WSS-ON vs OFF 结构分差 ±11.4。详见下方 "Recent Work (2026-08-07) — WSS 全量训练完成 (P1-1 落地)" 段。**Updated 2026-08-07 (Wyckoff P2-1 Resonance 标注完成)**: `MultiTimeframeContext` 加 `resonance_count/direction/strength`，`merge_multitimeframe_reports` 始终计算共鸣（只标注不反向信号），`WyckoffOutput`/`interfaces.py` 透传 3 字段，`_extract_from_report` 接线。26 tests + round-trip 验证。详见下方 "Recent Work (2026-08-07) — Wyckoff 真实价值落地方案" 段。**Updated 2026-08-05 (ruff 存量清理 + 工程修复)**: `tests/` + `scripts/` 存量 ruff 问题由 503 减至 0（`ruff --fix` 自动修 376，`--unsafe-fixes` 审查 75，人工修复 F821/E722/E741/E701/E402 等）。修复真实潜在 bug：补 `phase2_event_analysis.py`(typing)、`phase_e_wss_retrain.py`/`wyckoff_daily_screen.py`(`os` 缺失导入，改动前导入即 NameError)；恢复 `runner_v3.py` 被 ruff 误删的 `prev_at_cutoff` 循环赋值。删除 3 个引用已归档模块（`shared/archive`/`hands.backtest.archive`）的失效测试文件 + `test_e2e_integration_qa.py` 4 用例。修复 `pyproject.toml` 构建后端 `setuptools.backends._legacy(_Backend)`→`setuptools.build_meta:__legacy__`（新版 setuptools 下 `pip install -e .` 可装）；新增 `[tool.ruff.lint.per-file-ignores]` 豁免 `scripts/**` E402（合法 sys.path 引导）。CI `test.yml` lint 覆盖扩至 `src/ tests/ scripts/`。全量 **2051 passed / 22 skipped / 0 failed**，coverage 57.88%。1 项待办：研究脚本（`runner_v3.py` 等 F821 修复项）业务逻辑未运行验证（依赖数据）。 **Updated 2026-08-02 (Wyckoff 优化修复 8 项并行执行完成)**: 4 Wave 多 subagent 并行执行 8 项修复任务全部完成 — LPS 判定重构、scan fwd 数据底座、PnF 分歧标记、VDB 量价背离、结构分可达性校准、WSS 接线、MTF 统一、markup 降级+RS 过滤。详见下方 "Recent Work (2026-08-02) — Wyckoff 优化修复 8 项并行执行" 段。**Updated 2026-08-02 (全量 Wyckoff 扫描 + 指数净化)**: 服务层 index_df 透传 (W1) + 分析服务字段保真 (W2) + 全量扫描脚本 (W3) 完成；5382 只全量扫描 5374 成功；归档 552 个指数文件 (198 000xxx.SH + 354 399xxx.SZ)；候选池 306 只。详见下方 "Recent Work (2026-08-02)" 段。**Updated 2026-08-02 (Classic Wyckoff P1 非 P0 修复完成)**: CN-C4 复权状态探测 + SQ-C1 结构完整性评分 + RS-C1 相对强弱四分类全部实现，Compliance **58.3% (14P/7Pa/9F/30)**。详见下方 "Recent Work (2026-08-02)" 段。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 3 完成)**: CF-C4 假突破惩罚实现 — 共享 `_scan_false_breakout`（突破 TR 上沿 2%+ 后 3 列内跌回 + 量比>1.5 放量确认），`_step5_trading_plan` 标记 `V3TradingPlan.false_breakout_detected=True`，`_build_report` 经 `_downgrade_confidence` 将信号置信度降 1 级。Compliance 48.3% (D7-Counterfactual 50%, CF-C4 PASS)。**P0 全部完成**。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2 完成)**: PH-C2 DISTRIBUTION 事件序列驱动实现 — `_detect_distribution` 优先通过共享 `_scan_utad` 检查 UTAD 假突破事件（忽略 price_position），检测器链提前至 markdown 之前，新增 `synthetic_distribution_event_sequence` fixture。Compliance 48.3% (D4-Phase 80%)。剩余 P0: CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2 完成)**: PH-C1 ACCUMULATION 事件序列驱动实现 — `_detect_accumulation` 优先检查 `detect_all_events`+`event_sequence_key`（PS+SC+ST×2 匹配直接判定，忽略 price_position），启发式降为 fallback，新增 `synthetic_accumulation_event_sequence` fixture。Compliance 40.0% (D4-Phase 60%)。剩余 P0: PH-C2 → CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2)**: ES-C1 Spring 检测实现 — 共享 `_scan_spring`（O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩确认），step3 内联检测复用同一助手，替代旧 SPRING_LOW_FACTOR 独立判定。Compliance 38.3% (D2-Events 80%)。剩余 P0: PH-C1 → PH-C2 → CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2)**: ES-C3 UTAD 检测实现 — 共享 `_scan_utad`（X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 量比>1.5 放量确认），`_detect_utad` 驱动 DISTRIBUTION 相位，step3 内联检测复用同一助手。Compliance 36.7% (D2-Events 70%)。剩余 P0: ES-C1 → PH-C1 → PH-C2 → CF-C4。**Updated 2026-07-24 (3 轮红蓝对抗 + 参数敏感性验证脚本)**: 对 `LPPL_WYCKOFF_IMPLEMENTATION_PLAN.md` 设计文档完成 3 轮红蓝对抗（Round 1: 实施计划 16 Red / 0 Blue / 3 Split → 方案❌不可行；Round 2: 理论与实践中庸路线；Round 3: walk-forward 理论根基）。之后对参数敏感性验证脚本 v1 完成 3 轮红蓝对抗（脚本正确性/统计方法论/优化方案），输出修正后 v2 脚本 `scripts/param_sweep_v2.py`。详见 `docs/reanalysis/Z_red_blue_plan_verification_round*.md` 及 `Z_param_sweep_v1_redblue_round*.md`。**Updated 2026-07-24 (Walk-Forward 终结诊断)**: 实际引擎信号重测发现自定义分类掩盖了唯一有效信号。Wyckoff "买入" markup 阶段 +13.33% 20d (p=0.0098 显著) 但仅 4.5% 罕见。LPPL 零预测力 (MC 证明 93% GBM 拟合噪声)。Wyckoff Spring→BUY 理论信号从不触发。详见 `scripts/output/walk_forward_definitive_report.json`。**Updated 2026-07-20 (v7 代码强化)**: 6 项 cross_validation/engine 代码强化 (Spring 安全化, except 窄化×2, H12 三态裁决, R² 口径文档化×2)。**Updated 2026-07-17 (v7 管线验证执行)**: 红蓝对抗修正后执行 9 项任务 (7 完成, 1 待办)。LPPL _process_window 切换 L-BFGS-B (DE→L-BFGS-B), classify_top_phase ATR 自适应偏移, Wyckoff step4 单元测试 ×4, 跨引擎集成测试 ×3, cross_validation golden_20 (20/20, 62.9s), baseline v0 捕获 (20/20 一致)。**Updated 2026-07-13 (v6 修复执行)**: 6 路并行红蓝对抗 + TDD 全量分析完成 — 83 项声明核实 (88% 准确率), 15 项新发现修复。R0 代码修复: signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC 死代码跟踪)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。纠正 v5 虚假完成声明 (UI except 仍为 17 处, 非 2)。全部 1882 测试通过, 0 ruff。死代码库存更新至 ~2,819 LOC (含新发现)。剩余: R1-06 过户费 DRY 统一、R3-N01 45 零覆盖文件、45 files at 0% (3,791 LOC) — unchanged.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-07-06. Two re-analysis campaigns completed: (1) Phases 0-9 baseline (2026-06-30) covering baseline audit, worktree diff, engine correctness, backtest trust, data pipeline, signal system, engineering health, production readiness, governance, and final roadmap. (2) Phase A-K v2.0 deep audit (2026-07-06) covering code quality, test quality, data reliability, engine runtime behavior, backtest trust, signal audit, performance, security, observability, scorecard, and roadmap. **Updated 2026-07-09**: Live system map (I_live_system_map.md) documenting corrected metrics after 256-file verification sweep, dead code inventory (~1,960 LOC), ranked active bugs, and data path heat map. **Updated 2026-07-10**: 5-round multi-pass source code investigation completed. 256 files verified, 17/18 P0/P1 fixes confirmed (1 bare `except Exception:` remains at research_pipeline.py:244), 15 `except Exception` patterns narrowed, research_pipeline thread safety added, 51 new tests, 4 dead code files archived, dead code ~2,298 LOC. See `docs/reanalysis/Z_investigation_report_20260710.md`. **Updated 2026-07-10 (TDD Red-Blue)**: Comprehensive multi-pass TDD evaluation with 5-layer parallel red-blue adversarial analysis completed. 74 doc claims verified (87% accuracy, 55 Blue/8 Red/11 N/A). 0 bare `except:` across all layers. 224 total `except Exception:` mapped by layer. Dead code corrected to ~2,225 LOC (data_pipeline_service found ACTIVE, not semi-dead). 45 files at 0% coverage (3,791 LOC). 1 truly weak test. See `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md`. This file is the first local source context for agents working in this repository.

---

## Current State

UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot from 2026-07-13 (post-v6 TDD-Red-Blue):

| Metric | Current value |
|---:|---:|
| Python files under `src/uniquant/` (active) | 252 |
| Python active LOC under `src/uniquant/` | 61,889 |
| Archived files (dead code) | 6 (2,217 LOC) |
| Test files under `tests/` | 144 |
| Approximate test functions | 1,934 |
| Tests passing | 2,051 (22 skipped) |
| Ruff issues | 0 (src + tests + scripts) |
| Test coverage | 57.88% |
| Dead code (archived) | ~2,217 LOC (3.5%) |
| Functions total | 2,249 |
| `except Exception:` total | 231 (all layers) |
| `except:` (bare) total | 0 |
| Doc claims verified | 83 (88% accurate) |
| Files at 0% coverage | 35 (reduced from 45, ~2,500 LOC) |

Comprehensive re-analysis complete (Phases 0-9): full baseline audit, worktree diff, 8-engine correctness audit, 7-line backtest trust audit, data pipeline reliability, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for full reports.

Phase A-K v2.0 deep audit (2026-07-06): code quality (Fair, 116 duplicates, Wyckoff complexity 40), test quality (mutmut baseline broken), data reliability (B+, 5934/5934 100% readable), engine runtime behavior (B+, 2 critical bugs FSM+Wyckoff), backtest trust (B+, 7/7 lines PASS), signal audit (A-, signal/db.py 93% coverage), performance (A-, 64.4 MB/s), security (B+), observability (2/5, metrics F). Overall scorecard: **3.29/5.0 — B (conditional ready)**. See `docs/reanalysis/` for all 15 reports.

**Corrections from live system map (2026-07-09)**: Wyckoff complexity 76→40 (class max function); signal/db.py coverage 0%→93% (35 tests); eastmoney LOC 1,094→3 (refactored to 4 files). See `I_live_system_map.md`.

5 pre-existing test failures resolved (bc6337bc). 0 ruff issues, 0 pre-existing failures.

## Recent Work (2026-08-19) — 因子挖掘 P1 基线 (净化真实数据 Walk-Forward + 3 项引擎修复)

按用户决策"先 P1 基线（既有 13 因子真实数据 walk-forward）再 P2（GP 挖掘）、P0 数据底座净化纳入本次"推进，本期完成 P0 loader + P1 基线 + 过程中暴露的 3 项因子引擎真 bug 修复：

| 项 | 结果 |
|---|---|
| **P0 数据加载器** | 新建 `scripts/factor_mining/data_loader.py`（`load_universe` 经 `storage.get_symbols()` 净化池 → 并行多股加载 → `min_days` 过滤 + `as_of` 截断 + `describe_universe`），实测 as-of 2026-05-29 → **5018 只 × 8704 天 × 1629 万行**（5201 - 183 只短历史）；`tests/scripts/test_factor_mining_data_loader.py` **8 用例**（净化剔除指数/SZ 主板股回归/min_days/as_of/格式/单股加载/描述））；
| **P1 Walk-Forward 基线脚本** | 新建 `scripts/factor_mining/run_walk_forward_baseline.py`（`--sample/--full/--as-of/--lookback-days`；复用 `WalkForwardFactorPipeline` 504/63 窗 + `composer.compute_all_factors` 包装为完整 df factor_func + 每测试窗直接算 **每因子 true OOS IC**——管线只给 composite OOS）。**基线（500 只 × 17 窗，as-of 2026-05-29，lookback 1600 交易日）**：composite OOS IC **-0.024 / ICIR -0.61；每因子 true OOS IC 仅 2 正**——`idiosyncratic_vol_20d +0.075`、`illiq_20d +0.070`；其余**全负**（vol_60d -0.104 / momentum_60d -0.070 / momentum_20d -0.062 / ma_ratio_10_60 -0.055 / ma_ratio_5_20 -0.054 / rsi_14 -0.046 / cs_momentum_20d -0.046 / volume_ratio_5_20 -0.038 / price_position_20d -0.038 / pv_divergence_20d ~0.003）。→ **与 Wyckoff 研究结论一致：A股动量/技术相位不可靠、具逻辑的方向因子（低流动溢价/反彩票效应）为正**；既有 13 因子多数无正 OOS alpha → 直接验证 GP 挖掘必要性与"动量残差须控"预注册假设。产物 `results/factor_mining/baseline_walkforward_sample500_oos.json` |
| **引擎修复 (1) pv_divergence 38×** | `custom_factors.py compute_pv_divergence_20d` 原 `rolling(window=20).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])` **每窗口建 Series** → 50 只 77.4s（占全因子计算 99%）。改 `_rolling_rank_pct_last`：`sliding_window_view` + 平均秩公式 `(less+(equal+1)/2)/w` + NaN 掩码，**pandas rank(pct=True) 逐位等价**（合成含 NaN 数组验证 shape/nan-mask/allclose 全等）→ **77s→0.7s** |
| **引擎修复 (2) composer 正交化 NaN 崩溃** | `composer.py:303 _symmetric_orthogonalization` 用 `np.cov(F_centered.T)` 遇含 NaN 因子列（真实数据单股日期/全 NaN 切片）→ `scipy.linalg.eigh` 抛 `ValueError: array must not contain infs or NaNs` 中断整窗。改为剔除非有限行做 EVD、无有效行（<2 有限行）降级返回原因子、正交结果回填有限行+NaN 掩码；`orthogonalization_failed` 诊断保留 |
| **引擎修复 (3) compute_ic_ir 83×** | `analyzer.py:244 compute_ic_ir` 原逐因子×持有期 `df.groupby(date).apply(spearmanr)`（14 因子×3 期×1600 日 = 67200 次 Python 循环）→ 74k 行 **183s**。改每期一次：有效行 → date 分组内 `.rank()` → 组内 Pearson 公式（n·Σxy−ΣxΣy /√((nΣx²−Σx²)(nΣy²−Σy²))）→ **逐日 IC=Spearman**，n<5 置 NaN；与旧参考 14 因子×3 期全量 allclose 逐位验证 → **2.2s（83×）** |
| **测试** | 新增 `tests/test_factor_analyzer_vectorized_ic.py` **3 用例**（向量化=参考等价 / 全持有期 / 稀疏日期不污染）+ loader 8 用例；因子相关测试 **48+46+31 passed**（`test_factor_analyzer`/`walk_forward`/`composer`/`custom_factors`/`analyzer_vectorized_ic` + div_zero/registry/smart_calculator/scan_service），ruff **0** |
| **⚠️ 既有测试隔离问题（非本次引入）** | `tests/test_custom_factors.py::test_custom_factor_registered` 与 test_factor_analyzer/walk_forward/composer 并跑时失败、单独通过（`FactorRegistry.get_factor("turnover_momentum_20d")` 返回 None = 注册中心被其他测试污染）；**stash 验证原始代码并跑同样失败** → 预存在问题，未修 |

**判定**：P1 基线在净化真实数据上完成——**既有 13 因子仅 2 正 OOS IC**，正因子方向符合金融学（Amihud 流动性溢价、Ang 反彩票），负因子（动量/均线/RSI）与 Wyckoff"A股动量不可靠"结论呼应。**P2 GP 挖掘以此为基准门槛**（挖掘因子须 OOS IC > max(0.07, 基线正因子) 才值得落地，且必须过动量残差门——避免挖出差动量为噪声的假因子）。

## Recent Work (2026-08-19) — 因子挖掘 P2 GP 全量完成 (0 幸存 + 遗传算子别名 bug 根因修复)

按"先 P1 基线再 P2 GP"决策完成 P2：接入真实数据全量 GP 挖掘 + 过程中修复一个足以使 mine() Gen1 崩溃的遗传算子真 bug：

| 项 | 结果 |
|---|---|
| **P2 全量 GP 挖掘（净化真实数据）** | `scripts/factor_mining/run_gp_mining.py --n-jobs 16`：pop200×20 代、seed=42、500 只×1600 交易日（与 P1 基线同参数面板），as-of 2026-05-29。**815s 跑完，Reaper v2 幸存 0/25**（门槛 IC>0.0746=基线最正因子 idiosyncratic_vol_20d）。25 候选 gate 分布：**gate_ic 0/25、gate_pbo 0/25、gate_momentum 0/25、gate_diversity 25/25**（仅多样门过，其余全拒）。In-sample 最优解仍为**动量吸引子**（`rsi_14 add vwap` 等 3 个唯一公式克隆，OOS IC=-0.068 / PBO=0.387）；`returns_20d` 系列 OOS IC=-0.0675 / PBO=0.206。→ **GP 复现 P1 基线结论：A股动量/相位无正 OOS alpha，所有挖掘因子被 IC/动量残差门正确拒绝，0 幸存=正确门控结果**（非引擎问题）。产物 `results/factor_mining/gp_mining.json`+`gp_mining_report.md` |
| **遗传算子别名 bug（真 bug，mine() Gen1 崩溃根因）** | mine() 全量首跑 Gen1 崩 `IndexError`（`_to_str` 缺子节点，`to_formula` 取 child_strs[1]）——根因 `_subtree_crossover`（generator.py:748）`n2.children = backup1.children` **跨树共享同一列表对象**，且深度约束回退 `parent1.root = backup1` 使**两个输出树共享节点对象** → 后续 in-place 变异/`_sanitize_tree` 静默破坏对方树，产生 `min`(1子)/`abs`(2子) arity 失配；XO 后检查因别名"延迟显形"（在变异入口才暴露 `entry_bad=1`） |
| **修复** | `_subtree_crossover` 移植子树改 `[copy.deepcopy(c) for c in ...]`（两处，彻底解除跨树列表/节点别名）+ `_sanitize_tree` 对终结点带子节点时 `children.clear()`（兜底）。修复前后 5000 轮 xo→mut 组合循环：原代码在 ~69 迭代即 BAD、修复后 **0 失配** |
| **回归测试** | 新建 `tests/test_gp_factor_mining_crossover.py` **6 用例**（参数化×3 arity 全程链 / 输出树节点集合不相交=别名锁 / sanitize 清终结点子 / mine() 端到端）。**锁证**：对插桩前原始 generator.py 该测试 5/6 FAIL、对修复版全 PASS → 回归确为真 bug 修复。因子管线回归 38 passed（walk_forward/composer/registry），ruff **0** |

**判定**：P2 GP 挖掘在净化真实数据上完成全量闭环——**0/25 幸存（负结果，与 P1 一致）**，同时修复了会崩溃的遗传算子别名 bug。**结论：早期 GP 挖掘"挖出正 IC 因子"的合成数据结论在 A股净化真实数据上不成立**——GP 与既有 13 因子、Wyckoff 研究三方收敛于"A股动量/技术相位无稳定正 alpha"。挖掘路径的全部候选均被四重验证门（IC/PBO/动量残差/多样性）正确拒绝，门控设计有效。未来若继续挖掘，应转向**逻辑驱动的方向因子族**（如 Amihud 流动性的变体、反彩票、低波动异象）而非纯数据挖掘。

## Recent Work (2026-08-19) — 逻辑驱动因子方向族 P3 (7 因子 Walk-Forward 测试)

按 P2 结论转向逻辑驱动因子方向族。文献调研 `docs/analysis/LOGIC_FACTOR_RESEARCH_PLAN.md` 覆盖 3 方向 15 候选，按优先级实现 P0+P1 共 7 个因子，Walk-Forward 504/63 窗测试（500 只 × 1600d，与 P1 同面板）：

| 因子 | 理论 | 预期 | OOS IC | ICIR | PBO | 通过 |
|---|---|---|---|---|---|---|
| **max_ret_20d** | MAX 效应 (Bali et al. 2011) | − | **−0.0764** | **−11.50** | **0.166** | **✓** |
| **skew_20d** | 偏度彩票偏好 (Kumar 2009) | − | **−0.0316** | **−6.54** | **0.166** | **✓** |
| reversal_1d | 1 日反转 (Jegadeesh 1990) | + | +0.0136 | +3.31 | 0.307 | ✗ PBO |
| reversal_5d | 5 日反转 | + | +0.0349 | +7.11 | 0.669 | ✗ PBO |
| reversal_20d | 20 日反转 | + | +0.0548 | +4.19 | 0.669 | ✗ PBO |
| amivest_20d | Amivest 流动性 | − | −0.0063 | −0.69 | 0.166 | ✗ IC |
| range_20d | 价格区间波动 | + | −0.0625 | −7.57 | 0.669 | ✗ 方向 |

**两个通过四重门**：`max_ret_20d`（IC=-0.0764, ICIR=-11.50, PBO=0.166）和 `skew_20d`（IC=-0.0316, ICIR=-6.54, PBO=0.166）。**关键发现**：`max_ret_20d` 的 OOS IC 绝对值超越基线最强因子 `idiosyncratic_vol_20d`（0.0764 vs 0.0780），且 PBO 更优（0.166 vs 0.419）。反转族（1d/5d/20d）IC 均为正但 PBO 偏高（0.307-0.669）因窗口数限制（17 窗）未通过，留待更多数据验证。`range_20d` IC 强负（-0.0625）但方向错误——高波动→低收益，反彩票解释成立（Ang et al. 2006），若取负则合格。

**动量残差校验（P2 同款）**：追加控制 20d 动量后：
- `max_ret_20d` 残差 IC 翻正为 **+0.0486**（仅 5.9% 窗符合预期方向）→ 负 IC 完全由动量驱动，**动量门不通过**
- `skew_20d` 残差 IC 翻正为 **+0.0165**（17.6% 窗符合预期）→ 同理，**不通过**
- `range_20d` 残差 IC 为 **+0.0526**（94.1% 窗正）→ 唯一过动量门，但原始 IC 方向错误
- `neg_range_20d` 残差 IC 翻负为 **-0.0526** → 取负后也不过动量门
- `illiq_20d` 残差 IC 翻负为 **-0.0525** → 基线正因子也不过动量门
- `idiosyncratic_vol_20d` 残差 IC 翻负为 **-0.0563** → 同理

结论：**无因子通过全部四重门（含动量残差）**，A 股截面预测力高度集中于动量。详见 "P3 逻辑因子" 段。

## Recent Work (2026-08-25) — P10/D+10 容量验证 + H-A 工程化

| 项 | 结果 |
|---|---|
| 全市场重跑 | 4943 只（剔金融）：年化 +9.98%/夏普 0.93/回撤 −22.2%；500 采样同路径 +13.18%/1.08 → **采样幸运成分确认，正式预期口径改为全市场版** |
| F1/F2 判定 | F1 夏普 0.93<1.0 差线 FAIL；地板块夏普 0.78 但回撤 −12.8%（减半），按冻结判据 FAIL——illiq alpha 在小盘尾部 |
| **容量结论** | 持仓名单 ADV 合计中位 ~28.5 亿/日；10% 参与率折算 **策略容量 ≈2850 万元**——小资金可执行形态 |
| 信号运行器 | `scripts/canslim/daily_signal_ha.py`：状态判定→JSON 目标组合；实测 2026-07-23 处于过热牛、输出 Top30（合格池 5033）；参数集中常量区便于审计 |

## Recent Work (2026-08-25) — P9 隔夜/日内因子短窗口 OOS 验证

A(服务器)+B(本地客户端) 双源分钟数据落地与验证：

| 项 | 结果 |
|---|---|
| B 路线 | 发现本机 Wine 通达信 vipdoc 6.1GB；.lc5 格式审计：OHLC 整数字段为压缩 ~70× 的衍生轨迹（corr 0.9997 但幅度失真）不可用；bar 级 vwap=amount/volume 经官方日线交叉校验真实可用 |
| A 路线 | mootdx 分页拉取 492/500 只 × 267 天；与本地段重叠期相关=1.0、scale=1.0（同源同口径）；接缝 QA PASS（gap 0.0004 « tol 0.019） |
| 拼接窗口 | **287 天（2025-06-24→2026-08-25）**，minutedaily_full/ |
| F1 on_mom_10 @fwd5 | IC=-0.0109 t=-0.86 → 无信号 |
| F2 on_mom_20 @fwd5 | IC=-0.0033 t=-0.24 → 无信号 |
| **F3 intra_mom_20** | fwd5 IC=**-0.0522**(t=-2.85)、fwd21 **-0.0655**(残差-2.60)、前后半 [-0.062,-0.042] 一致 → 方向与预注册(+1)相反判 FAIL；观察性备注："日内动量"在 A 股同为反转结构 |

新文件：`lc5_reader.py`、`convert_local_lc5.py`、`fetch_minute5_server.py`、`run_overnight_validation.py`（预注册 docstring）、`tests/scripts/test_conditional_stats.py` 等；ruff 净。

## Recent Work (2026-08-25) — P8/D+9 组合层验证 (H-A 可交易性三臂对照)

预注册冻结于 `scripts/canslim/run_portfolio_validation.py` docstring（策略族/共同规则/成本模型先于跑数写死）：

| 臂 | 规则 | 年化 | 夏普 | 最大回撤 | 在场 |
|---|---|---|---|---|---|
| **STRAT-A 条件illiq** | 过热牛时持有 illiq Top30 | **+15.82%** | **1.33** | **−12.9%** | 17% |
| CTRL-B 无条件illiq | 全程 illiq Top30 | +13.97% | 0.65 | −43.7% | 100% |
| CTRL-C 状态内随机 | 同状态随机30只 | +6.89% | 0.60 | −14.3% | 17% |

**三问裁决**：Q1 扣成本正收益 ✓｜Q2 择时贡献 夏普+0.68 且回撤 −43.7%→−12.9%（条件化=风控叠加为主）✓｜Q3 选股贡献 夏普+0.73（illiq 截面排序在状态内有真实选股力）✓。

实现要点：等权30只/5日再平衡+状态切换日/剔除金融79只/当日收盘涨停(+9.5%)不追买/单边15bp成本（含小市值滑点）/决策用 t 日信息作用于 t 日收益（近收盘成交假设，已在预注册披露为乐观项）。19 个过热片段、平均 14.2 天。

## Recent Work (2026-08-25) — P7 条件信号定向验证 (H-A 幸存: 流动性溢价×过热态)

按 P6 裁决启动定向验证。预注册先行冻结 (`docs/analysis/CONDITIONAL_VALIDATION_PREREGISTRATION.md`)：假设/门限(G1 NW-t≥3/G2 块自助CI/G3 残差NW-t≥2/G4 前后半同号)/失败预案全部写死于跑数前。

| 候选 | PIT 主判定 | 结论 |
|---|---|---|
| **H-A: illiq_20d @ trend_on∧vol_high (fwd5)** | **IC=+0.0811, NW-t=+5.3✓, 残差+5.6✓, CI[+0.052,+0.116]✓, 半期[0.112,0.051]✓ → 四门全过** | **✅ 幸存** |
| H-BL: roe 多腿 @ 平静牛 | NW-t=+0.2, CI 含 0 → 四门全败 | ❌ |
| H-BS: roe 空腿 @ 狂热牛 | NW-t=−1.9<−3（全样本口径 −4.2 但按纪律以 PIT 为准） | ❌ |
| H-C: c_single_yoy @ 平静牛 | NW-t=+2.2<3（G2/G3/G4 过） | ❌ 差线 |

关键健全性：(1) **PIT≈FULL**（0.081 vs 0.113）→ 信号非状态分位阈值后视伪影；(2) **动量残差化后更强**（5.6>5.3）→ 不属 P3 动量 beta 家族，为独立溢价源；(3) 前后半均正 → 非窗口内单 regime 伪影。

产物 `results/factor_mining/conditional_validation.json`；统计工具 `conditional_stats.py`（Newey-West t/移动块自助/PIT 波动状态）+ `tests/scripts/test_conditional_stats.py` 5 用例；验证脚本 `run_conditional_validation.py`。

⚠️ 边界声明：vol_high 态仅占窗口 ~8%（130/1600 天），策略大部分时间无持仓；日频 IC 通过 ≠ 可交易——组合层验证（成本/换手/容量/与无条件持有对比）为下一阶段 D+9。

## Recent Work (2026-08-25) — P6 Regime 条件化因子 IC 诊断

按推荐组合"②regime 分层诊断 → ①隔夜因子"执行第一步。脚本 `scripts/factor_mining/run_regime_conditional_ic.py`（预注册冻结：状态定义/视野/高亮阈值见 docstring）：

| 项 | 结果 |
|---|---|
| 设计 | S1=沪深300>MA200 二态 × S2=指数波动 33/67 分位三档 → 6 格；fwd5/fwd21；26 因子（价量22+成长5）；发现规则=格内 n≥100 且 \|t\|≥3 + 跨格异号 FLIP 对 |
| 执行 | 500 只 × 1600 天，趋势 on 占比 0.55，222.9s；高亮 240 单元；产物 `results/factor_mining/regime_conditional_ic.json` |
| **裁决** | **候选条件信号存在**（区别于"全灭"分支） |
| 模式 1 | **illiq_20d @ trend_on∧vol_high：IC=+0.1118 (t=+10.0)** vs 整体 +0.046 —— 流动性溢价在过热阶段放大 2.4× |
| 模式 2 | **roe 大幅翻转（fwd21）：trend_on\|vol_low +0.029(t=+4.3) vs trend_on\|vol_high −0.129(t=−11.8)** —— 平静牛市奖质量、狂热杀质量；c_single_yoy 同构 (+0.053/+0.032 vs −0.027/−0.042) |
| 模式 3 | 反转族在 vol_high 态最强（rev_20d +0.095）；动量族六格恒负 → **A 股反转结构与 regime 无关**（非状态伪影） |
| 测试 | `tests/scripts/test_regime_conditional.py` 5 用例（IC 对 scipy 基准/小截面跳过/状态表/聚合/高亮阈值），ruff 0 |

⚠️ 纪律声明：本诊断为 DIAGNOSTIC——候选信号不直接进系统，须走定向四重门（状态内样本重估 ICIR/PBO/动量残差，注意日频 IC 自相关使名义 t 偏高、vol_high 格 n≈102-130 样本偏薄）。

## Recent Work (2026-08-25) — P5 CANSLIM 因子轨生死判定 (D+4 早出口: 路线终止)

红蓝对抗 (`docs/analysis/CANSLIM_RED_BLUE_ADVERSARY_20260824.md`, CONDITIONAL PASS + A1-A11 修正案) 后按 MVP 执行：

| 项 | 结果 |
|---|---|
| **修正案落地** | §7 参数冻结(主版本门槛写死)/边界规则(R-BASE-NEG/TINY/MIN-HIST/YOUNG/FIN)/H3 中性化/双判据(日频 IC+季频事件法)；金融剔除静态名单 `financial_codes.json` 79 只(新浪板块∪规则命中经名称验证, 79/101 规则误判为地产/ST 已剔)；成长构造器 `growth_factors.py` 9 用例(YTD 年边界差分复用 P4 语义) |
| **D+4 判定** | `run_factor_gate.py` 全量 497 只(净化后494)×21 窗 504/63，222s → **H1(C)=FAIL ∧ H2(A)=FAIL → ⛔ 早出口终止路线**（产物 `results/canslim/factor_gate.json`，方案文档 §8） |
| **门级要点** | `c_single_yoy`@fwd5 最接近幸存(IC+0.012✓/PBO 0.166✓/ICIR 0.42✗/动量窗比0.62✗)——如实记录不改判；其余全败 |
| **核心发现** | **A股成长陷阱实证**：a_cagr3@fwd63 IC=−0.0808/ICIR−0.93、roe@fwd63 −0.0780、事件法中位差全≤0、动量残差更负(−0.0948) → 高历史成长/高ROE 强负向预测；CANSLIM 原版前提在本窗口结构性反向；与 P3(动量beta)+连板网(反转市)三方收敛 |
| **流程价值** | MVP 早出口在最小成本点(单脚本 222s)杀死路线，避免 D+9/D+14 组合回测沉没成本——预注册纪律首次完整闭环 |

## Recent Work (2026-08-24) — P4 财务数据底座落地 (TDX 归档全量拉取 + 累计值 TTM 真 bug 修复)

按"基本面是唯一结构性正交赛道"决策完成数据底座。方案 `docs/analysis/FINANCIAL_DATA_ACQUISITION_PLAN.md`（三源实测对比 → TDX 胜出 → v3 复核修正 3 处错误声明 → §6 双源交叉验证 → §7 实施结果）：

| 项 | 结果 |
|---|---|
| **数据源选型** | TDX 季度归档（mootdx affair，147 期 1988→2026）胜出：25/25 字段严格命中桥接契约（零 rename）、公告日期列与桥接逐字一致、离线批量无限流；akshare 东财批量降为备选（19/25 字段）；baostock 否决（仅比率型） |
| **双源交叉验证** | seed=42 抽 12 只 vs 东财线上：eps/bps/总资产/总负债/股东权益/营业利润/利润总额/**归母净利润**/三大现金流 **100% 一致**，公告日期 12/12 吻合；全部差异均为已知口径差（东财 lrb 净利润=归母口径、revenue 主营 vs 总营收、银行科目）。TDX 数据质量确认 |
| **全量拉取** | `scripts/factor_mining/fetch_financial_data.py`（retry×3/断点缓存 `data/cache/tdx_cw/`/原子写 parquet）：42 期 → **5211 只 × 577 列 × 2.4GB**；920xxx 北交所新股段 338 码无后缀规则剔除 |
| **真 bug：累计值 TTM** | 冒烟 E2E 发现茅台 EPS_TTM=122.99 异常 → 根因：财报行为同年累计值(YTD)，`calculate_eps_ttm` 朴素 rolling(4).sum() 把累计当单季相加 → 虚增约 4×。修复：年边界差分单季再滚动（跨年 Q1 重置），`TestCumulativeToTTM` 4 用例锁证 + 旧测试语义修正 |
| **实现要点** | 公告日期 YYMMDD 浮点→YYYYMMDD 整数（否则桥接 fullmatch 全 NaT）；列名 strip+重复列去重；代码后缀化同桥接 MARKET_SUFFIX_MAP；测试 fetcher 29 用例 |

**验收锚点**：600519 EPS_TTM@FY2024=68.64 恰为全年 EPS；TTM@20260331=66.04 与单季逐项手算一致；相关 69 passed / ruff 0。

## Recent Work (2026-08-18) — 因子挖掘功能核查 (完整存在 + 生产已接入, 非废弃)

按"如何用净化数据底座提高交易价值"探究链对因子系统做完整核查（读全部 8 模块 + 生产调用点）：

| 项 | 结果 |
|---|---|
| **模块盘点** | `src/uniquant/brain/factors/` 8 模块 2265 行全部**完整可用**：`registry.py`(184, 注册中心 + FactorAccessLevel FREE/WARN/BLOCK 门 + 单例线程安全 + 读 factors.yaml)、`analyzer.py`(528, IC/IR/RankIC/ICIR + `check_lookahead_leakage` 前视检测 + generate_report)、`composer.py`(477, Z-score + 对称正交化 + IC 加权 + 跨窗衰减 + FactorNeutralizer 中性化)、`custom_factors.py`(311, **13 因子**: momentum_20d/60d·volatility_20d/60d·ma_ratio_5_20/10_60·volume_ratio_5_20·rsi_14·price_position_20d·turnover_momentum_20d + 逻辑四金刚 illiq_20d(Amihud)/pv_divergence_20d/cs_momentum_20d/idiosyncratic_vol_20d, `register_all()` import 即注册)、`walk_forward_pipeline.py`(266, 时间切分/ICIR 加权/OOS 评估/前视检测/权重稳定性)、`financial_bridge.py`(421, 中文财务字段→标准名 + EPS_TTM 滚动 + PE_TTM/PB merge_asof + 公告日处理)、`neutralizer.py`(40, MAD winsorize + 行业/对数市值回归残差化)、`industry_provider.py`(20) |
| **生产接线（非死代码）** | `scan_service.py:16-18` import FinancialFactorBridge/FactorAnalyzer/FactorComposer → `build_factors`(:221, composer.compute_all_factors) → `_merge_financial_metrics`(:263, 并行 merge_asof + checkpoint) → `analyze_factors`(:332, IC/IR) → `compose_scores`(:371, 合成)；`service_container.py:159` 配置 FactorRegistry mode；`config_validator.py:109` WS7-002 校验 config 启用因子必须已注册；`screener.py:169` 用 `get_enabled()`；`config_loader.py:157` 加载 factors.yaml |
| **挖掘管线定位** | `WalkForwardFactorPipeline` 有测试（`tests/test_walk_forward_pipeline.py` + chaos/boundary QA）但 **src 生产路径无调用 = 研究/扫描工具**；GP 因子挖掘（遗传规划）已迁出生产路径至 `experiments/gp_factor_mining/`（generator.py + run_auto_mining.py，合成数据植入信号 + The Reaper PBO<0.2 ∧ OOS IC>0.05 死神校验），`factors/__init__.py:5` 注明迁移 (2026-06-17) |
| **与 Wyckoff 修复衔接** | 因子管线从 `storage.get_symbols()` 读全池（未走 wyckoff 扫描入口的净化路径）；本次 P0 指数净化只清了 Wyckoff 扫描池（5755→5201），**因子管线的符号池是否含 554 指数需单独核查**；RS=leader（本质=20d 相对动量）可直接作为 `momentum` 类因子输入净化数据重新验证 |

**判定**：因子挖掘功能**完整存在、生产已接入、非废弃**；GP 自动挖掘在 experiments/ 层（研究工具）；下一步"因子挖掘"应从真实数据挖掘管线（walk_forward + IC/IR 门 + PBO 校验）切入，并复用本次净化后的符号池与数据底座。

## Recent Work (2026-08-18) — P0 数据净化 (指数未归档 + load_symbols 过滤) + 进程池入仓

按第一性原理研究 `docs/analysis/WYCKOFF_FIRST_PRINCIPLES_20260818.md` 开放项 #1 落地：

| 项 | 结果 |
|---|---|
| **发现** | AGENTS 曾记"552 指数已归档"，实测 `data/lake/quotes/daily/archive_index/` 为空、daily/ 仍含 **554 指数文件**（200 000xxx.SH + 354 399xxx.SZ）；`load_symbols("all")` 直接 `return sorted(all_symbols)` 无过滤 → 全量扫描池 5755 只含 554 指数 |
| **修复 1（符号级判定）** | 新增 `_is_index`（`scripts/wyckoff_full_scan.py`）：`exch==SH and code.startswith("000")` 或 `exch==SZ and code.startswith("399")` → 指数。**不误杀 SZ 主板股**（000001.SZ 平安银行等）。删除旧裸前缀 `_INDEX_EXCLUSIONS`（含 `"0000"` 等，曾误杀 000001.SZ 主板股）；`all` 分支加 `not _is_index(s)`；ETF 仍保留（is_etf 列标注，供下游筛除，维持"保留 137 ETF"既有决策） |
| **修复 2（进程池入仓）** | `run_scan` ThreadPoolExecutor→**ProcessPoolExecutor** + `_worker_init`（每进程独立 `WyckoffEngine`/`StorageManager`，`initargs=(index_df,)`）——消除共享引擎 `_code_prefix` 竞态（:320-321），`/tmp` 临时 runner 逻辑正式入仓，仓库可复现 |
| **5 窗净化重扫** | `--symbols all --max-workers 32` 5 窗全量（W1 2026-04-30/W2 2026-03-31/W3 2026-05-29/X4 2025-06-30/X5 2024-12-31）→ 每窗 **5201 只×39 列**（旧 5755 行备份于 `/tmp/opencode/wyckoff_fix/old_scans_p0/`），~64s/窗 |
| **验证：T1 零影响** | direction_map_check **5/5 PASS**；T1 n_buy **82/23/66/166/118** 与基线一致（n 4762/4773/4766/4719/4670）→ **554 指数对方向面零影响**（指数本就不产 BUY）；**T3 维持 1/5 FAIL**（X4 r3=+5.30 p=0.0 候选）；golden gate **PASS**、deterministic **PASS**。**⚠️ 2026-08-18 下段修正**：此数字(82/23/66/166/118)仍含下游裸前缀缺陷误杀，正确基线 86/27/69/174/123（见下段"全量重跑 + 下游裸前缀缺陷修复"） |
| **测试** | `tests/scripts/test_wyckoff_full_scan_fwd.py` 新增 5 用例（`_is_index` 参数化 13 例 + load_symbols all 剔除指数保股票/ETF + SZ 主板股回归）→ scripts+classic_wyckoff **275 passed + 1 skipped**，ruff **0** |

**判定**：数据卫生缺口闭合，全量扫描池 5755→5201（净剔 554 指数）；进程池 runner 已入仓消除可复现性风险；结论与旧基线一致（指数零影响），无需重判 T1-F7/T3。

## Recent Work (2026-08-18) — 全量重跑 + 下游裸前缀缺陷修复 (T1 基线修正)

P0 净化后按计划全量重跑全部统计/验证脚本（T1-T5、F7、golden、seal、direction_map），重跑过程发现 **P0 修复漏网的同源缺陷**：

| 项 | 结果 |
|---|---|
| **发现** | P0 只修了 `wyckoff_full_scan.py` 扫描入口，但 **6 个下游消费脚本仍用裸前缀 `("000","399")` 剔指数**：`direction_map_check.py`/`confidence_survival.py`/`buyset_momentum_residual.py`/`momentum_residual_analysis.py`/`validate_ranking.py`/`_common.py`（verify 共用）→ `str.startswith("000")` **误杀全部 000xxx.SZ SZ 主板股票（每窗 414 只）** |
| **根因** | 裸 code 前缀把"指数"与"SZ 主板股票"混为一谈；正确判定须符号级（SH 000xxx=指数、SZ 399xxx=指数，000001.SZ=平安银行非指数） |
| **修复** | 新建共享 `scripts/wyckoff_experiments/_symbols.py`（`is_index_symbol` 符号级判定 + `is_index_series` 向量版 + `drop_index_rows`），语义与 `wyckoff_full_scan._is_index` 完全一致；6 处裸前缀全部替换为符号级判定 |
| **T1 基线修正** | n_buy **82/23/66/166/118 → 86/27/69/174/123**（每窗补回被误杀的 BUY）；clean 池 n **4762/4773/4766/4719/4670 → 5174/5185/5178/5133/5084**（+412/窗 回归） |
| **统计结论不翻转** | T1 仍 **5/5 PASS**（SELL 恒 0）、T2 仍 **0 upgrade**、T3 仍 **1/5 FAIL**（X4 唯一 PASS，r3=+4.54 p=0.0002，此前 +5.30 p=0.0——n 修正导致值略降但显著性维持）、**F7 PASS**、T4 漂移 44%/57%/23% FAIL（P1-1 撤回维持）、T5 W2 45%/47% FAIL（P1-11 默认关维持）、golden/deterministic/seal PASS |
| **测试** | 新建 `tests/scripts/test_wyckoff_symbols_index.py` **20 用例**（18 参数化符号判定 + is_index_series + drop_index_rows 含 SZ 主板回归）；tests/scripts **125 passed**；ruff **0** |
| **真实数据验证** | 修复后新 T1 数字在 direction_map_check 与 replicate_t1_t3 两脚本完全一致（86/27/69/174/123）→ 口径统一 |

**判定**：这是 P0 数据净化修复漏网的最后一个同源缺陷（下游消费侧），现已闭环。旧基线数字（82/23/66/166/118 及 n 4762…）因裸前缀误杀 SZ 主板股而**偏低，正式作废**；新基线 86/27/69/174/123、n 5174/5185/5178/5133/5084。**所有统计结论（恒无方向、T3 1/5、F7 无升级、T4/T5 撤回）不因基线修正翻转**。

## Recent Work (2026-08-18) — P1 幸存者偏置定量披露 + 开放项#2 box 全局步长核验

P0 后完成第一性原理研究剩余开放项核验：

| 项 | 结果 |
|---|---|
| **开放项 #3 幸存者偏置定量披露** | 按 **type=1 纯股票口径**（`all_stock_codes` type=1 股票 5541 只，其中退市仅 **337 只**——1176 是含指数/基金/转债的全表 outDate 数）实测 5 窗覆盖率：**0.999–1.013**（W1 5196/5201、W2 5194/5193、W3 5201/5208、X4 5194/5152、X5 5190/5122）→ **幸存者偏置影响 ~0.3%**，无需降权 |
| **推翻早期假偏置** | 第一性原理文档原记"覆盖比 0.73-0.78"是把基金(5)/转债(11x)/指数(399/000)混入历史在市分母的**假偏置**；真实股票口径接近 1.0 |
| **披露落地** | `scripts/wyckoff_experiments/PREREGISTRATION_20260812.md` §数据窗口 补每窗覆盖表 + n 更新（5755→5201，T1 实测 4762/4773/4766/4719/4670（⚠️ 下游裸前缀缺陷修正后 clean 池 n=5174/5185/5178/5133/5084））+ 移除过期"剔 000xxx/399xxx 前缀"口径（改为净化后 all 池即纯股票）；`docs/analysis/WYCKOFF_FIRST_PRINCIPLES_20260818.md` 推导5/§6.3/§8/§9 同步更新 |
| **开放项 #2 box 全局步长核验** | `pnf.py:27` `_fixed_step` 用**全序列中位价** → 770 只（15% 池）价格跨 >8 倍（600602.SH p5=1.92→p95=2587，141 倍）时：低价段 step 占比 1.95%（合理）、高价段 0.39%（过密，600602 箱数 33 万）→ **真实简化缺陷**，传导到 phase_hint(PF-C1 驱动相位)/count_target(Step4 目标)/congestion_zone(TR 边界) 三处标注输出 |
| **判定** | #2 = "标注层已知限制，待专项分段-box 修复"（不产方向，不动引擎，P&F hint 仅叙事/风控）；已记档 §6.1/§9，不在此轮修复 |

**验证**：P1 为纯披露/文档改动 + 数据核验，未改源码；P0 全量回归 2144 passed / 8 skipped / ruff 0 保持。**剩余开放项**：无（#1/#2/#3 全部关闭或记档）。

## Recent Work (2026-08-18) — TRIAD-VSA 量价结构检测器 (三假说正交混合, 恒无方向)

新建 **TRIAD-VSA** 量价结构标注器（三通道正交混合，纯标注，恒不产方向信号），沿既有 Wyckoff 叙事层裁决方向落地：

| 项 | 结果 |
|---|---|
| **三假说正交混合** | 流体力学驻点滞止/激波反射 (A: wick 能量定义 `A_stag=tanh(k_s/(K_s+η·k_s))`，k_s=影线能量量加权、K_s=净位移能量量加权、η=wick_discount=0.1) × 热力学熵/潜热 (B: `σ(z_s)·clip(1−m/m_star)` + 吸收后验崩塌 liq_jump 双端 collapse 判据) × 信息论贝叶斯吸收滤波 (C: 两态因果前向滤波 + TE_{V→P} 因果窗)。混合：`triad_abs=(A·B·C)^(1/3)`，`agree_abs`=≥2 通道>0.6，`triad_liq`=max(reflect, liq_jump, B_liq) |
| **三大约定全落地** | ① 全部特征因果 trailing（无居中窗/无未来对齐）→ `test_causality_prefix_invariance` 前缀不变性；② 涨跌停棒（含一字板）排除出有机流，零量/NaN 量=非有机，**平盘非涨停棒保持 organic**（停牌态而非结构性事件）；③ 恒无 buy/sell/direction/signal 字段，数值全 ∈[0,1]，`audit_no_direction` 契约测试 |
| **真实报错闭环 (TDD 红绿循环)** | 首跑 12 failed → 修复 3 个真实缺陷：① 删 try/except 时误删 `import sys` (NameError)；② `_structural_mask` 原把一切平盘棒标 structural → 常量价序列整段非有机 → 改仅按涨跌停价判定；③ **贝叶斯 warmup NaN 传播毒化**（`pi_a[t-1]` NaN → 整条后验 NaN）→ 重写携带状态版（均匀先验 0.5，NaN 棒只 hold 不污染）；④ **scale 维度错误**（绝对价格 ATR 11.67 元 / 无量纲收益 0.00995 → u≈0.00085 而非 0.75）→ 改分数 ATR `scale=max(atr/close, pct_floor)`；⑤ B 通道净流加 `m_star=0.5` 门槛（>0.5 ATR/棒 ⇒ 非吸收）→ 稳态 1% 趋势 triad→0 |
| **测试** | `tests/scripts/test_triad_vsa.py` 21 用例（因果前缀不变性/常量价/稳态趋势/涨跌停/一字板/零量/NaN 量/除权跳空/零价/短序列/warmup/TE 可解/正交性/融合共识/无方向契约/limit_pct 前缀/rank_sum/汇总门）**21 passed**（-W error 零警告）；`tests/scripts/` 全目录 **90 passed**；ruff **0**；Wyckoff 关键回归（structural_score/limit_up_guard/accumulation_downgrade）**31 passed** |
| **预注册门** | `TriadConfig` 全部常量冻结（atr_period=14/ent_win=120/n_bins=16/te_win=60/liq_theta=0.5/m_star=0.5/abs_gate=0.6…），调整须走 `PREREGISTRATION_20260812.md` P2 门流程 |

产物：`scripts/wyckoff_experiments/triad_vsa.py`（含 compute_triad/TriadConfig/TriadResult/audit_no_direction/summarize_window/_rank_sum_p/CLI）、`scripts/wyckoff_experiments/__init__.py`、`tests/scripts/test_triad_vsa.py`。

## Recent Work (2026-08-18) — 全量 5 窗重跑 (进程池) + structural_score 非确定性根因修复

按用户要求"对并行/内存利用做评判并重跑全量 Wyckoff 数据分析"，完成并行利用评判、共享引擎竞态确认、引擎级非确定性 bug 修复、全量 5 窗确定性重跑与验证脚本全复跑：

| 项 | 结果 |
|---|---|
| **并行利用评判** | `wyckoff_full_scan.py:252` ThreadPoolExecutor 受 GIL 锁死：8→32 workers 无增益（200 只 31.5s→28.7s），而 ProcessPoolExecutor 32 workers 仅 1.9s（**线程池慢 ~15 倍**）。全量 5755 只/窗从 ~15min 降至 72-78s。主机 32 核、31GiB、load 2.97；relmom `load_cache()` 1.64 GiB/56s |
| **共享引擎竞态确认** | `engine.py:320-321` 每 `analyze` 写 `self._code_prefix`，被线程并发下 `_step5`(:1586 涨跌停守卫) 与 `detect_limit_moves`(:2101) 读取 → 688/300 等 20cm 规则可能套到主板股票。旧 5 窗 CSV（8/7 线程池产物）存在此污染 |
| **根因修复（引擎级 bug）** | `_compute_structural_score` 经共享 `self._wss_scorer` 调 `score_sequence`，`WSOScorer.score_events`（`sequence.py:90-96`）维护跨调用 EMA 状态 `_last_score/_is_warm` → 同一输入在引擎分析过别的股票后得分漂移（实测 000001.SZ 59.03↔61.41）。修复：WSS 分支改用冷启动 `WyckoffScorer(wss_lookup=scorer.wss.lookup)`（复用 lookup 引用，不触发 EMA 累积）。新增 `tests/classic_wyckoff/test_structural_score.py` 回归用例 `test_structural_score_shared_engine_cross_call_deterministic` |
| **全量重跑落地** | 临时进程池 runner `/tmp/opencode/wyckoff_rerun.py`（32 workers，每进程独立引擎，复刻 `analyze_one` as-of 逻辑，不改源码）。修复后引擎两次运行 **0 差异**。`results/wyckoff_xs*/wyckoff_scan_all.csv` 全部更新为 39 列确定性版本（旧 25 列 8/7-8/12 版本备份于 `/tmp/opencode/wyckoff_fix/old_scans/`） |
| **实验/验证脚本全复跑** | **T1 PASS**（n_buy 82/23/66/166/118，SELL 恒 0）、**T3 1/5 FAIL**（X4 唯一 PASS r3=+5.30 p1=0.0；W1 -1.22 p=0.889、W2 None、W3 -2.71 p=0.895、X5 -0.32 p=0.597）、**F7 PASS**、**T2 0 upgrade_candidates**、golden_gate **PASS**（20 只全同）、deterministic_assertions **PASS**、verify_seal_as_entry **PASS**、direction_map_check 5/5 **PASS** |
| **测试** | `tests/classic_wyckoff/` **170 passed + 1 skipped**，ruff 0 |

**T1 n_buy 归因（137/40/66/167/120 → 82/23/66/166/118）**：
- **W3/X4/X5**（66→66、167→166、120→118）差 0-2 只 = 线程池竞态（`_code_prefix` 污染涨跌停守卫）消除后的修正；
- **W1/W2**（137→82、40→23）大幅减少 = 8/7 旧引擎产物（旧 CSV 生成于 8/7，P0 direction gate / accumulation_downgrade / A股铁律守卫落地前）vs 当前引擎更保守。判定不翻转。

**判定**：T1/F7/T2/golden/seal/direction_map 全部稳定 PASS，T3 维持 1/5 FAIL（X4 候选跟踪）。旧 CSV 中 25 列、含线程池竞态与 WSS EMA 漂移污染的数字（如 n_buy 137/40）不再作为基线。

## Recent Work (2026-08-14) — P0+P1 全量回归核验 (bias200 标注缺陷修复)

对 P0 七项 + P1-3~12 实施做全量回归与真实数据核验（下述所有命令均在当前工作树复跑，非引用历史数字）：

| 项 | 结果 |
|---|---|
| **冒烟** | 关键 Wyckoff 子集（P0 direction + limit_up_guard + MTF resonance + spring_conduction + accumulation_downgrade + adapters + signal）全过；`check_impl_state.py` B1-B8 **PASS**（B3 允许键集同步含 P1 标注键 + 无关 engine 键泄漏负向断言：regime/risk/ntf_*/alpha_score 均未泄漏） |
| **全量测试** | **2107 passed / 8 skipped / 0 failed**（872s），0 ruff |
| **验证脚本复跑** | F7 **PASS**（口径披露不变）、T1 **PASS**（SELL 恒 0）、T3 **1/5 FAIL**（X4 候选）、SEAL 密封 **PASS**（C2 INCONCLUSIVE=留档）、D1-D3+golden gate **PASS**（4 标量全一致）、V1-V5 **全 PASS** |
| **golden_20 真实数据标注面** | `scripts/wyckoff_full_scan.py` 扩展透出 14 标注列：sos_candidate_detected True **2/20**、evr_state≠none **3/20**（2 bearish+1 bullish, level=3）、pattern_failure_detected True **3/20**（ratio~2.0）、event_cooldown True **7/20**（days=5）、range_score/avwap 全正常、no_supply/nsd/vdu 0/20（golden_20 无此类量能场景，符合预期） |

**发现并修复 bias200 标注缺陷**：`_build_report` 收到 `frame.tail(lookback=120)`（`constants.py ENGINE_DEFAULT_LOOKBACK_DAYS=120`），`len(df)>=200` 恒 False → **bias200 恒 0.0**（标注字段失效）。修复：`_analyze_single` 在截断前保存 `full_frame`，新增 `_build_report(full_frame=...)` 参数，bias200 基于全量 MA200 计算。新增 `tests/classic_wyckoff/test_p1_12_bias200.py` 3 用例（长历史 bias200 非零=手工 MA200 一致 / 短历史 0 / WyckoffOutput round-trip）。修复后 golden_20 bias200 **20/20 非零真实值**（-0.25~-0.004）。`evr_position_context` 恒空符合定稿 P1-4"接入点需等 per-bar 化 (P1-5 后)"设计——字段已透传，计算留待 per-bar。

## Recent Work (2026-08-12) — Wyckoff P0 实施完成 (信号链根除 + 验收 PASS)

按 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` §5/§8 完成 P0 七项信号链根除实施与四组实地验证：

| P0 | 实施 | 验证 |
|---|---|---|
| P0-1 direction 透传 | `WyckoffOutput.direction` + `wyckoff_direction` roundtrip + `_extract_from_report` 提取 MTF 融合后 direction + pack_writer 写入 | B1/B2 PASS |
| P0-2 adapter direction gate | `_ENTRY_DIRECTIONS={做多,买入,轻仓试探}`→BUY, 其余→None; 删 phase/spring/utad 直映射 | B4 PASS; T1 5/5 PASS |
| P0-3 RDP 仅展平 wyckoff 键 | `pack_writer.py:114-124` 仅展平 wyckoff 键，禁全量 metadata 展平 | B3 PASS |
| P0-4 置信门槛 0.40 | `confidence_gate` 读 config; `scan_signal` 用 `_scan_buy_confidence_gate` | B5 PASS; T1b (X5 拦 37%) |
| P0-5 structural_adjust 默认关 | `_apply_structural_adjustment` 门控于 engine.py:452; structural_score 仍作叙事字段回填 | B6 PASS |
| P0-6 normalizer/scan_signal 抵销 | `_DIRECTION_MAP` 6 项全置 0; scan_signal 仅 direction∈{做多,买入,轻仓试探}且置信≥0.40→BUY, 恒不产 SELL | B7 PASS |
| P0-7 恒不产 SELL-as-entry | adapter 遍历 13 方向文本恒无 SELL; normalizer 恒无 −1; scan_signal 恒 BUY/HOLD; unified_engine SELL=只平仓 | C1 PASS; T1 SELL=0 |

**全量 2092 passed / 8 skipped / 0 failed, 0 ruff, golden_20 baseline 4 标量全一致**。验证脚本 `scripts/wyckoff_verify_20260812/` 六脚本（A 组 F7/T1/T3 复现、B 组 B1-B8 实现状态、C 组 SELL 密封+P1 标注面、D 组三层验收门+golden 门）全部跑通：

- **A 组 F7 PASS**（无信号类达 4/5 升级线；**口径披露：定稿 F7 表 W1-W3 为指数中性超额口径与 X4/X5 原始口径混用，一致口径下 leader 同号负显著 3/5 窗例外，表述应改为"无 2/3 多数同号"**）
- **T1 PASS**（137/40/66/167/120 SELL 全 0）**T3 1/5 FAIL**（X4 +4.96 p=0.0001 候选跟踪）
- **B1-B8 PASS** **C1 PASS** / C2 INCONCLUSIVE（P1-3 留待 P1 阶段） / **C3 PASS**
- **D1-D3+golden PASS**
- 报告: `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md`

P1 余项（P1-3 sos 独立字段 / P1-4~12 标注 / P1-11 功能）按 §8 顺序后续实施。

## Recent Work (2026-08-12) — Wyckoff 深度验证 V2 (V1-V5 并行执行)

5 路并行 subagent 深度验证 P0 实施 + 1 项修复：V1 F7 口径统一稳健性 (PASS, leader 3/5 全剔尾边界 5/10/15/20% 稳健)；V2 P0 后方向映射实证 (PASS, 5/5 窗 BUY>0 SELL=0)；V3 X4 多重检验审计 (PASS 维持候选, 效应由最低 relmom 桶驱动→修正标签为"牛市超跌反弹")；V4 全信号链泄漏审计 (PASS, 220 单元格 0 SELL, arbitrator Wyckoff SELL=dead code)；V5 A股铁律交互 (修复→PASS, 发现涨停守卫缺口—engine.py 缺 LIMIT_UP 守卫, 单涨停日+MARKUP 相位→BUY 泄漏)。修复：`engine.py _step5_trading_plan` 加 LIMIT_UP/BREAK_LIMIT_UP 守卫 + 精确价差容差 0.5%, 新增 `tests/classic_wyckoff/test_limit_up_guard.py` 3 用例。**2104 passed / 8 skipped / 0 failed, 0 ruff, golden 门一致**。详 `docs/verification/WYCKOFF_DEEP_DIVE_VERIFICATION_20260812.md` §7。

## Recent Work (2026-08-12) — Wyckoff 深入再研究定稿 (5 窗跨 regime 实证)

按 `docs/prompts/wyckoff_deep_dive_prompt_v2.md` 对 `WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` 定稿做深入再研究：Phase 0 代码扎根（F1-F9 全核实）+ Phase 1 五路并行 subagent 审计（引擎核心/信号链/实证支撑/外部差距/风控层）+ Phase 2 预注册 5 实证脚本（0 ruff）+ Phase 3 补 **2 个老窗口全量 as-of 扫描**（X4 2025-06-30 / X5 2024-12-31，各 5755 只，~40min/窗）+ Phase 4 四轮红蓝对抗，输出修订版 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md`：

| 维度 | 结果 |
|---|---|
| **F11** direction 消费者 | 不止旧离线回测：`brain/wyckoff/analysis.py:274-294` MTF 融合 + `ui/dashboard.py:1278` 展示 → P0-1 透传需覆盖 MTF 路径 |
| **F12** RDP 冷态 | 默认 `use_research_data_pack:true` 下全引擎网都不进 TradingSignal 链；adapter direction 优先作用面=非 RDP/离线回测 |
| **F13** P1-3 冲突 | `sos_candidate` 已被 markup 分支占用 signal_type (engine.py:1684/1708) → 改独立布尔字段 `sos_candidate_detected` |
| **F14/F10 更正** | 老窗 fwd_60d 覆盖 98.8%/98.0%（W1/W3=0%，60 交易日越过 07-23 数据末端）；原"重叠过半"表述错误 → 实际日重叠 0/10/0%、分析输入重叠 ~99.7% |
| **F7 五窗复核** | 六类信号**全无跨窗同号显著**：markdown X5 剔尾 +1.28%(p=0.002) 推翻"唯一稳健风控"；leader X5 −1.54%(p<0.0001) 翻负；accumulation X4 +3.73%(p=0.0005) vs W1-3 负；markup X5 −1.66%(p=0.011)；distribution 从未负显著。**相位方向跨 regime 全面不稳定 → 叙事层裁决 5 窗加强成立** |
| **T1** direction map | **5/5 PASS**（BUY 137/40/66/167/120，SELL 恒 0）；0.40 门槛 X5 拦 37% 弱置信（存活 62.5%，余窗 ~90-93%） |
| **T2** 置信排序力 | 五窗 **0 upgrade_candidates** → P0-4 门槛 0.40 成立（X5 甚至 C 桶 −2.00% p=0.056） |
| **T3** BUY 动量残差 | **1/4 窗独立增量 FAIL**（X4 p=0.0001 单窗强显著 → 记"牛市 beta 待复验候选"，需未来 ≥3/5 窗升级；W1-3 全负/ns） |
| **T4** ATR 相对化 | 触发集漂移 44.4%/56.5%/22.6% 全破 5% 红线 → **P1-1 撤回**（atr_pct 仅透传） |
| **T5** 止损守卫 | W1 22%/27.3% PASS、W2 45%/46.7% **过度触发 FAIL**、W3 29%/20.7% PASS → **P1-11 默认关 + config 参数化**（`stoploss_guard_enabled/depth_pct/grace_days`），FSM FORCE_EXIT→SELL(1.0) 为唯一常开止损 |

**四轮裁决**：R1=P1-1 撤回；R2=P1-3 换独立布尔字段；R3=P1-11 默认关+参数；R4=P0-2 维持 FAIL（X4 候选跟踪）。P0 七项全部确认（T1/T2 量化支撑）。Config 待 P0 实施：`direction_gate_enabled:true`、`confidence_gate:0.40`、`structural_adjust_enabled:false`、`sos_candidate_annotation:true`、`stoploss_guard_*`（`accumulation_downgrade:true` 保留=风险体位）。实施顺序 **P0-1/2/6→P0-3→P0-4/5/7→P2 验收→P1-3→P1-4~12**（P1-1 撤回/P1-11 默认关）。产物：5 脚本入 `scripts/wyckoff_experiments/`（含 buyset_momentum_residual 等证伪代码）+ `results/wyckoff_xs4|xs5/` 扫描 + `/tmp/opencode/wyckoff_phase3_evidence.md`。

## Recent Work (2026-08-12) — Wyckoff 正确实现方案定稿 (4 路审计 + 3 路红蓝对抗)

对实际代码做 4 路并行 subagent 审计（引擎核心 / 信号链 / 实证支撑 / 外部实现差距）+ Wyckoff 方案草案 v0 → 3 路独立红蓝对抗（引擎现实 / 实证证据 / 外部最佳实践）裁决，输出定稿 `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md`：

**新核实事实**：
- **Wyckoff 信号在默认配置下整体不进 TradingSignal 链**：`use_research_data_pack:true`（config.yaml:484）→ RDP 只写 metadata（pack_writer.py:112-119）→ research_pipeline 不展平（research_pipeline.py:569-597）；且 `_extract_from_report` 不提取 direction、`WyckoffOutput` 无 direction 字段、`_extract_wyckoff` 不读。三层绝缘 + 未展平。
- `V3TradingPlan.direction`（含 accumulation 降档/markdown 禁多/假突破惩罚）**无处消费**，唯一消费者是旧离线回测 `hands/strategies/wyckoff.py:61`。
- **共三套相位→方向映射**：adapter `adapt` 直映射（adapters.py:180-185）+ `signal/normalizer.py:115-122` `_DIRECTION_MAP` + `engine.py:2040-2051` `scan_signal`（含永不触发 SELL 残影）。
- **F7 剔尾复核**：distribution/markdown/leader/accumulation/markup/spring 六类信号剔尾(|fwd|≤10%)后**均无同号显著**。distribution 剔尾后 +0.30/+0.13/+0.11 全 ns → 禁做空依据从"显著正"降为"≈0 无依据"；markdown 剔尾后 W2 +0.00(ns)、leader W2 翻负 −0.68(p=0.027) → "唯一稳健方向"/"接入 leader"均过强。
- ConfidenceLevel 无 B+（models.py:21-27，全链统一 A=0.9/B=0.7/C=0.5/D=0.3）——草案"B+=0.55"为幻影。
- unified_engine SELL **仅 position>0 执行**（unified_engine.py:420）= SELL 即"只平仓"；arbitrator Priority 2 会让 Wyckoff SELL 无条件压掉 BUY。

**P0 信号链根除（引擎正确目标态 = 叙事+风控，完全不产方向入场信号）**：direction 透传（`WyckoffOutput` 增字段 + MTF 融合后提取）→ adapter **direction 优先**（做多/买入/轻仓试探→BUY，其余→None，删 phase/spring/utad 直映射）→ RDP **仅展平 wyckoff 键**（禁全量 metadata 展平，会复活 LPPL 0.05 门槛）→ 置信门槛 0.30→0.40 且主靠 direction gate → 默认关 `structural_adjust_enabled` → normalizer/scan_signal 残留抵销 → **恒不产 SELL-as-entry**。

**P1 标注/风控增强（纯标注，不改方向结论）**：ATR 相对化（签名 `Optional` 默认值，触发集 before-after 对照漂移>5% 撤回）、一字板守卫、`_detect_sos` 填 UNKNOWN 候选（不进 signal）、EVR 三态×5档+位置语境、图式失效 0.33×区间宽、NoSupply/NSD/VDU、eventCooldown、rangeScore/AVWAP 叙事面**禁回流结构分**、sequence 软标注权重0、止损触发层（节后宽限期+缩量洗盘）限位、bias200 改风控注释。

**P2 验证门**：补 **2025-06-30 + 2024-12-31** 老窗（现全 2026 H1 同 regime、fwd 重叠~50%）；三层验收门（确定性断言映射表 100% + 预注册 MWU p≥0.05@≥2/3 窗 + markup 存活表供定门槛）；BUY 集跑 Momentum 残差（markup=追涨同机制）；证伪代码 `mresid_robust.py`/`mom_control.py` 从 /tmp 入仓；golden baseline 前后对比门。

**8 项明确不做**：bias200 过滤、板块波动缩放、sequence 序进分、量 95 分位硬门槛、LPS creek gate、leader 接入 adapter、研究管线 2.02 融合、compression/trend_pullback 原型。

**实施顺序**：P2-4 入仓→P0-1/2/6→P0-3→P0-4/5/7→P2 验收→P1-1/2/3→P1-4~12。

## Recent Work (2026-08-07) — WSS 全量训练完成 (P1-1 落地)

P1-1 "WSS 默认开启阻塞" 从诊断推进到**实际训练并启用**（评估结论:链路可行，核心成本在 runner_v4）:

| 步骤 | 结果 | Verification |
|---|---|---|
| 目录创建缺陷修复 | `phase1_multitf_analysis.py`/`phase2_event_analysis.py`/`phase_e_wss_retrain.py` 均加 `OUTPUT_DIR.mkdir`；修复 `runner_v4.load_checkpoint` `Obs(s=...)`→`Obs(symbol=...)` dataclass 命名 bug（此前一旦有检查点即崩溃） | 0 ruff |
| 小样本冒烟 | `scripts/wyckoff_multitf/smoke_wss_chain.py`（新）5 只→595 obs、20 只→1617 obs/19 seqs，全链 14s 跑通；engine `is_loaded=True` 验证 | smoke_wss_chain.py |
| **全量 runner_v4** | 1000 只（stratified seed=42）→ **87977 obs** / 11178 spring，32 workers，~4min | `output_v4/v4_results.json` |
| **全量 phase2 + phase_e** | phase2 87977 obs 事件链 → `phase_e` **418 qualifying sequences** | `phase2_event_results.json` + `wss_lookup_v2.json` |
| **启用 + A/B** | `config/config.yaml` `wyckoff.wss_enabled: true`；WSS-ON vs OFF 6 只真实股结构分差 **-11.4 ~ +1.6**（000858.SZ -11.4 / 600000.SH -7.0），WSS 实质性重排；Top seq `SC>AR>ST>ST>SOS>JAC>SOS>LPS` wss=+0.121 (t=2.91)，Bottom `PS>PS>PS>SOS>SC>SC` wss=-0.207 (t=-5.10) | 169 passed (classic_wyckoff) + 75 (engine/analysis/phase) |

**工程注意**: `test_p3_markup_rs.py` 加 `_wss_off` autouse fixture（RS 逻辑测试须与 WSS 混合分解耦，否则 config 默认开启后相位被 0.7*WSS 改变）。

## 4 路并行系统评估 (2026-08-07) — 实现程度 + 差距 + 超额实证

多 subagent（引擎代码审计 / 经典理论合规 docs / 差距审计 docs / 实证超额计算）交叉验证：

| 维度 | 结论 |
|---|---|
| 实现完整度 | 九步+事件库(7)+P&F+共振+WSS+RS 四分类+结构分+A股铁律全部接通，~75% 非 stub；软肋：`_detect_sos` 死桩、B+/enum 不一致、3.5 反事实仅计数、~30 处硬编码 |
| 经典合规 | **58.3% (14P/7Pa/9F/30)**；9 FAIL 多为 GAP/TRADE-OFF（研究平台定位 WONTFIX），非阻断 |
| 生产代码错位 | 引擎把"相位标签当方向"→ accumulation/distribution/spring 三大理论信号实证跑负/反；"代码完备但真信号少" |
| 实际超额（20d 市场中性，W1/W2 双窗） | **唯一正超额=RS=leader**（+5.18%/+2.12%，Sharpe ~0.61）；accumulation −1.87/−1.37 稳定负；spring −1.44/−3.22 无溢价；distribution +0.84/+0.77 反做空错；结构分 IC −0.083/+0.032 符号翻转不可当排序器 |
| 行动清单 | ①RSS 接入交易方向 gate（唯一正 alpha）②spring 仅在 leader 内放大 ③结构分废排序器 ④修死桩/硬编码/CF ⑤研究管线(Sharpe 2.02) vs 生产(~50%) 融合 |

报告：`docs/analysis/WYCKOFF_SYSTEM_ASSESSMENT_20260807.md`。

## 方法论多轮对抗性分析 (2026-08-09) — 判定报告

对 `WYCKOFF_METHODOLOGY_SETTING_20260807.md` 12 路红蓝对抗 + 新增独立第 3 窗口（W3 as-of 2026-05-29 全量 5755 只，`results/wyckoff_xs3/`）+ 落地代码核验：

| 攻击面 | 结果 |
|---|---|
| leader×spring 交互 | ❌ 方法论"spring 仅在 leader 池触发"**证伪**：W1 −5.57% / W2 −7.50%（spring 消解 alpha） |
| structure IC 三窗 | −0.083 / +0.032 / **−0.073** → 符号翻转成立；且 leader 内结构分低的更好（8.00 vs 5.07 W3）→ 高分是劣势标记 |
| 显著性口径 | W2: Welch t=0.013 vs **MWU=0.263** → leader "双窗显著"过度，仅 2/3 窗稳健 |
| 决策链 DAG (phase∈accum/markup∧leader) | ❌ W2 −1.39% / W3 −1.76%（vs leader 单独 +2.12/+6.54）→ phase 过滤淘汰 leader 好子集 |
| **真信号：leader×distribution** | 三窗 **+5.85% / +4.09% / +9.07%**，MWU p<0.01 全三窗 —— 唯一稳健正超额（⚠️ 但动量残差研究证伪其独立增量，见下段 `WYCKOFF_MOMENTUM_RESIDUAL_20260809.md`） |
| 引擎落地矛盾 | `engine.py:1421-1422` distribution→空仓观望 硬编码 → W3 全部 321 只 leader∧dist 候选被标空仓，方法论无法经现有生产引擎兑现 |
| markdown 风控 | 3/3 负（−3.6/−1.2/−4.1）→ 唯一稳定风险方向，方法论位置正确 |

**判定**：方法论核心（状态≠方向≠排序、结构分弃用、markdown 风控）成立；但 alpha 轴错位——应为 **`RS=leader ∧ DISTRIBUTION`（做多方向，+6.34% 三窗均值）**而非 phase∈accum/markup；spring/结构分/置信在 leader 内零增量。报告：`docs/analysis/WYCKOFF_METHODOLOGY_ADVERSARY_20260809.md`。

## 动量残差研究 (2026-08-09) — leader∧dist 独立增量证伪

新增脚本 `scripts/wyckoff_experiments/momentum_residual_analysis.py`：从数据湖重建三窗 20d 相对动量（relmom = stk−idx300），对 `leader∧distribution` 做 4 方法对照（M1 分位残差 / M2 OLS残差 / M3 独有子集 / M4 网格）+ R1-R4 稳健性：

| 检验 | W1 | W2 | W3 | 结论 |
|---|---|---|---|---|
| M1 分位残差（控动量） | +1.84pp | +4.63pp | +0.91pp | 初看正 |
| M2 OLS残差（控二次） | +1.82pp | +4.34pp | +2.30pp | 初看正 |
| **R3 剔除右尾后 M2** | +1.06pp (p=0.071) | **+0.01pp (p=0.96)** | **−0.24pp (p=0.76)** | ❌ **增量塌缩=右尾驱动** |
| R4 分位内相位增量符号 | 2/6 负 | 1/4 负 | 2/4 负 | 跨窗不一致=噪声 |
| R1 动量周期 40d | 正 | 正 | **−0.96pp** | 周期敏感非独立因子 |

**判定**：`leader∧distribution` 的正超额 **= 20d 相对动量 beta + 少数右尾暴涨股运气**，控制动量并剔右尾后 2/3 窗归零——作为 Wyckoff 相位的独立贡献**证伪**。**最终建议**：P0（distribution×leader 落地）不落地；leader 若用应作纯 20d 相对动量因子（加极端值约束）；Wyckoff 引擎降为叙事/风控层（markdown 闸、涨跌停、RR），从方向合成中移除相位/spring 独立开仓依据。报告：`docs/analysis/WYCKOFF_MOMENTUM_RESIDUAL_20260809.md`。

## Wyckoff 研究全景归档 (2026-08-11) — docs/ 汇总入口

为 docs/ 下 60+ 篇 Wyckoff 研究与分析文档建立统一归档：`docs/analysis/WYCKOFF_RESEARCH_MASTER_SUMMARY.md`。按 7 个研究阶段（S1 早期 06-27 / S2 基线 07-20 / S3 红蓝+WF 07-24 / S4 Classic 合规 08-02 / S5 相位再平衡 08-06 / S6 方法论 08-07 / S7 对抗+残差 08-09）组织，含核心结论表、Compliance 演进链（17%→58.3%）、研究管线 vs 生产引擎对比（Sharpe 2.02 vs 一致性 50%=随机）、双窗+三窗+动量残差三波证伪证据、以及完整文档清单（docs/analysis + docs/reanalysis + 其他）。跨期反复验证的同一根因：**把相位标签当方向、把事件强度当排序、把单窗小样本当结论** —— 最终幸存者仅 RS=leader（本质=20d 相对动量）与 markdown（风控）。查阅任何 Wyckoff 历史结论请从该汇总入口出发，附带 `docs/index.md` 中的 `wyckoff_research_report.md` 研究管线实证（22,148 obs）。

## Recent Work (2026-08-07) — 红蓝对抗验证落地 (WYCKOFF_VERIFICATION §六)

双窗口全量 as-of 回放实证（`scripts/wyckoff_experiments/validate_ranking.py` 新工具 + `results/wyckoff_xs/` W1 04-30 n=4762、`results/wyckoff_xs2/` W2 03-31 n=4773，均市场中性超额收益）红蓝对抗验证方案报告：

| 声明 | W1 (04-30) | W2 (03-31) | 判定 |
|---|---|---|---|
| structure_score 排序力 | IC **-0.083** (p<0.001 显著负) | IC **+0.032** (显著正) | **符号翻转→"不稳定"非"无差"，废弃当排序器** (黄金100"无差"为假) |
| leader=唯一真信号 | +1.45% vs 池 -3.73% (MWU p<0.001) | +8.68% vs 池 +6.56% | **双窗显著** |
| leader+结构分 | +2.03→-0.41 稀释 | 8.68→6.18 稀释 | 双窗复现稀释 |
| distribution 反做空 | 超额 **+0.84%** | 超额 **+0.77%** | **反做空错**(双窗复现) |
| accumulation 蓄势 | 超额 **-1.87%** | 超额 **-1.37%** | **蓄势不涨, 降档** |
| markdown | 超额 -3.58% | 超额 -1.23% | 唯一可靠方向→风控 |

**落地 (engine.py)_step5_trading_plan**：
- 新增模块级纯函数 `_downgrade_direction`（做多/买入→轻仓试探、轻仓试探→观察等待）
- `config/config.yaml` 新增 `wyckoff.accumulation_downgrade: true`（模块 `get_config` 读取 `__init__` 存 `self._accumulation_downgrade`）
- ACCUMULATION 相位多头方向降 1 档（含假突破/涨跌停强制空仓之后的后置 gate）；只在 ACCUMULATION，markup/unknown 不降
- distribution/markdown 禁做空/做多已硬编码（step5 1395-1398 + rule2），本轮复核确认

**测试**: 新增 `tests/classic_wyckoff/test_accumulation_downgrade.py` 9 用例（降档矩阵 + flag off 保 P0 + markup/unknown 不降 + config 接线）；`test_spring_conduction.py` `_plan` 加 `_engine()` pin `_accumulation_downgrade=False` 隔离 P0 传导；回顾 163 passed / 1 skipped / 0 ruff。报告 `docs/analysis/WYCKOFF_VERIFICATION_RED_BLUE_20260807.md`。

## Recent Work (2026-08-07) — WSS 启用后全量扫描核验 (对照研究档案)

WSS 启用后重跑全量 5755 只（WSS-ON），对照 2026-08-02 研究档案 `WYCKOFF_FULL_SCAN_ANALYSIS_20260802.md` 核验 P0/P1/P2 落实：

| 指标 | 2026-08-02 (WSS OFF) | 2026-08-07 (WSS ON) | 结论 |
|---|---|---|---|
| A 级置信度 | 0 | **96** (1.7%) | 置信度体系突破 |
| B 级 | 1.6% | **762** (13.2%) | 中间层恢复 |
| 结构分 max | 64.4 | **77.7** | P1-2 天花板解除 |
| 结构分 ≥70 | 0 | **300** | 升级路径可达 |
| spring→可操作 | 0/66 | **15/36 轻仓试探** (干净池) | P0 传导修复 |
| 置信vs结构 pearson | -0.024 | **+0.023** | 由负转正 |

- **相位-收益前瞻** fwd_20d/60d 在最新截止日为空（数据湖止于 2026-07-19），改用 golden_100 + as-of 2026-04-30 验证：markup +5.8% ✓ / accumulation +0.3% ✓ 方向正确；但 **distribution 20d 仍 +14.5% / markdown +11.2% 看跌背离仍存**（与 archive 50% 一致性一致）——WSS 改善结构区分度，不改相位方向预测上限，已知局限
- **候选池** 710 只（A/B 492 / C 137），高价值 A/B+leader+spring **15 只**（archive 7 只）
- Compliance 58.3% (14P/7Pa/9F/30) 不变（遗留项均为数据依赖/平台定位不符 WONTFIX）
- 报告：`docs/analysis/WYCKOFF_WSS_SCAN_ANALYSIS_20260807.md`

## Recent Work (2026-08-07) — Wyckoff 真实价值落地方案 (P0/P1/P2)

基于经典 Wyckoff 对照评估 (Compliance 58.3%) 的真实 leverage 点，放弃不可行的总量重写计划，落地可验证子集（全部 TDD + 真实数据验证 + 0 ruff）：

| Phase | Task | Summary | Verification |
|---|---|---|---|
| **P0-1/2** | Spring 传导断裂修复 | `engine.py:_step5_trading_plan` ACCUMULATION 分支（spring_detected 但 lps+conf≥B 原「观察等待」）与 UNKNOWN 分支（原「空仓观望」）→ 当 `conf∈{A,B,B+} 或 rr≥1.5` 时「轻仓试探」；弱置信（C/D）+ 弱 RR 仍观望（A股铁律守卫）。修复真实 bug：`_calc_confidence` 产出 `B+` 字符串但 `ConfidenceLevel` enum 仅 A/B/C/D，原 `["A","B+"]` 无法命中普通 `B` | 真实 120 只 SZ：3 只 spring 修复前 0 只可做多 → 修复后全部轻仓试探（000518 unknown/A/+5.8%、000501 accumulation/B/+3.0%、000338 unknown/C/−3.4%） |
| **P1-2** | 结构分评分天花板 | 根因:真实数据 WSO 事件序列 base 仅 ±0.1 量级，线性 min-max 浪费 3/4 区间。`engine.py` 加 `BASE_AMPLIFICATION=5.0` 放大已验证事件序列贡献 | 真实 220 只 SZ：p25-p75 span **2.4→10.8**（60.3→62.7 vs 64.8→75.6），std 5.38→7.77；reachability（升≥55/降≤45/拉开>5）锚点测试全保 |
| **P1-1** | WSS「默认开启」阻塞诊断→实际训练 | 训练产物全缺（`wss_lookup_v2.json`/`phase2_event_results.json`/`phase1_results.json` 均不存在），开启 flag 会静默 no-op。加启动 WARNING 使死分支可诊断（engine.py:214-224）。**2026-08-07 训练完成**：修复 phase1/phase2/phase_e 目录创建缺陷 + runner_v4 检查点 `Obs(symbol=...)` dataclass bug；小样本(5/20只)冒烟→全量 1000 只 `runner_v4`(87977 obs/11178 spring/32workers/34s)、`phase2`(87977 obs)、`phase_e`(**418 seqs**)；`config wyckoff.wss_enabled=true` 开启，A/B 验证 WSS-ON vs OFF 结构分差达 ±11.4，RS/P3 测试加 `_wss_off` autouse 隔离 | 10+169 passed (test_p1d_wss_wiring + classic_wyckoff)，0 ruff |
| **P2-1** | MultiTimeframeResonance 标注接入交易决策 | `MultiTimeframeContext` 新增 `resonance_count/direction/strength`，`merge_multitimeframe_reports` 始终计算（示意化 flag 只选 alignment 逻辑，不反向信号）；`WyckoffOutput/interfaces.py` 透传 3 字段；`_extract_from_report` 接线 | 26 passed (test_p2_mtf_resonance.py) + 2 (test_wyckoff_analysis_engine.py) |

**Test results**: 169 passed (classic_wyckoff) + test_analysis_service_v2 34 passed，**0 ruff**，WyckoffOutput to/from_dict round-trip 含共振字段。**DNT**: S0.2/S1.2/S1.5 证伪放弃。

## Recent Work (2026-08-05) — ruff 存量清理 + 失效测试移除 + 工程修复

| 项 | 内容 | Verification |
|---|---|---|
| **ruff 全量清理** | `tests/`+`scripts/` 存量 503 错误 → 0：`ruff --fix` 自动修 376，`--unsafe-fixes` 审查 75 (F841)，人工修 11 F821 + 13 手写项 | `ruff check src/ tests/ scripts/` = All checks passed |
| **F821 潜在 bug 修复** | 补 `phase2_event_analysis.py` `from typing import Optional/List`、`phase_e_wss_retrain.py`/`wyckoff_daily_screen.py` `import os`（三者改动前**导入即 NameError**）；`classic_wyckoff_compliance.py` 2 处导入调用改裸调用保留副作用 | `py_compile` 通过；3 脚本 import 烟测 OK |
| **runner_v3 逻辑恢复** | ruff unsafe-fix 误删循环末 `prev_at_cutoff = at_cutoff`（下一轮迭代使用）；重构为 `prev_at_cutoff = None` 初始化 + `is not None` 守卫 | 编译通过；业务逻辑待数据运行验证 (待办) |
| **失效测试移除** | 删除 3 个引用已归档模块（`shared/archive`/`hands.backtest.archive`）的测试文件 + `test_e2e_integration_qa.py` 4 用例（portfolio_engine 等已删死代码） | 2051 passed (含 signal_db 等恢复) |
| **构建后端修复** | `pyproject.toml` `setuptools.backends._legacy(_Backend)` → `setuptools.build_meta:__legacy__`（新版 setuptools 下 `pip install -e .`/`[all]` 可装） | `pip install -e ".[all]"` 成功 |
| **ruff 配置** | 新增 `[tool.ruff.lint.per-file-ignores]` 豁免 `scripts/**` E402（合法 sys.path 引导） | 全量 ruff 0 |
| **CI 扩覆盖** | `test.yml` lint 从 `src/uniquant/` 扩至 `src/ tests/ scripts/` | 防止 tests/scripts 回归 |

**Test results**: 2051 passed / 22 skipped / 0 failed；coverage 57.88% (≥50% 门槛通过)；0 ruff (src+tests+scripts)。**待办**: 研究脚本（`runner_v3.py` 等 F821 修复项）业务逻辑未运行验证（依赖数据）。

## Recent Work (2026-08-05) — pyarrow 升级 + CI Audit 修复

| 项 | 内容 | Verification |
|---|---|---|
| **pyarrow 升级** | `pyproject.toml` pyarrow 约束 `<20.0.0`→`<24.0.0`，允许 23.0.1；修复 PYSEC-2026-113 漏洞（19.0.1→23.0.1），解决 CI "Audit dependencies" 步骤阻塞 | 全量 2051 passed / 22 skipped；ruff 0 |
| **CI Audit 修复** | CI `test.yml` "Audit dependencies" 步骤因 pyarrow 19.0.1 漏洞始终失败（exit 1），Lint/Test 步骤被跳过 → 升级后审计通过 | `gh run list` CI job 待新提交触发 |
| **gh CLI 接入** | 安装 gh 2.45.0 + SSH 认证完成，可通过 `gh run list`/`gh run view` 查 CI 状态 | `gh auth status` → logged in as feel6bglues |

**runner_v3.py 业务验证待办**：`data/lake/quotes/daily/` 目录当前为空（parquet 数据未加载），`runner_v3.py` 依赖真实行情数据运行，暂无法验证。需先填充数据或用合成数据验证。

## Recent Work (2026-08-02) — Wyckoff 优化修复 8 项并行执行 (4 Wave, 多 subagent)

| Wave | Task | ID | Summary | Verification |
|---|---|---|---|---|
| **A** | scan fwd 数据底座 | P0-B | `scripts/wyckoff_full_scan.py` 新增 `is_etf`(前缀规则)/`fwd_20d`/`fwd_60d` 列；新增 `--as-of` 回放模式；`build_empirical_table()` 实证表输出 | 38 新测试 `tests/scripts/test_wyckoff_full_scan_fwd.py` 全过；golden_20 扫描 20/20 成功 2.2s |
| **A** | PnF 分歧标记 | P1-A | `_step1_phase_determine` 不再短路，始终运行检测器链并记录分歧；`Step1Result`/`WyckoffReport`/`WyckoffOutput` 均加 `pnf_phase_divergence` 字段；相位仍由 PnF 驱动（第1步不改相位结果） | 6 新测试 + 81 回归 = 87 passed；分歧示例：PnF=accumulation 但链=UNKNOWN |
| **A** | VDB 量价背离 | P1-B | 新建 `effort_result.py` 纯函数 `detect_effort_result_divergence`（价跌量缩→bullish/价升量缩→bearish）；`Step2Result` 加 `vdb_divergence` 字段；不进相位判定 | 9 新测试全过；Step2Result 2 构造点兼容 |
| **A** | WSS 接线 | P1-D | `config/config.yaml` 新增 `wyckoff.wss_enabled`(默认 false) + `wss_lookup_path`；`WyckoffEngine.__init__` 创建 `WyckoffScorer`；`_compute_structural_score` 支持 scorer 参数；A/B 开关验证 | 10 新测试全过；wss_enabled=true 时 blended 评分生效(436 seqs) |
| **B** | LPS 判定重构 | P0-A | `rule6_spring_validation` 签名新增 `spring_volume`/`atr` 参数，实现分层判定（作废检查→测试K线识别→硬门槛守位→量能+反弹确认）；ATR 计算上移至 spring 检测前；`Step3Result` 新增 `lps_stage`/`test_low` | 12 新测试全过；守位由 `min(low)*0.995` 改进为 `test_bar_low` + ATR 容忍；量能参照从 `max_vol` 改为 spring 当日量；反弹从单日收阳改为多根窗口 |
| **B** | 结构分可达性校准 | P1-C | `_apply_structural_adjustment` 阈值 70/35→55/45；`_compute_structural_score` 权重放大（相位加成 0.15→0.20, UNKNOWN -0.10）；新增可达性测试 | 5 新可达性测试 + 19 旧 = 24 passed；max 结构分 65.7→70.2，升级路径可达 |
| **C** | MTF 统一 | P2 | `merge_multitimeframe_reports` 引入 `MultiTimeframeResonance` 替换 rule9；`config/config.yaml` 新增 `wyckoff.mtf_resonance: true`；Resonance 仅要求方向一致（BULLISH/BEARISH），rule9 要求精确相位匹配 | 21 新测试 + 132 基线 = 132 passed；Resonance 与 rule9 核心差异：accumulation+markup+accumulation→rule9=mixed, Resonance=fully_aligned |
| **C** | markup 降级 + RS 过滤 | P3 | `_build_report` 新增 markup 降级（RS∈{follower,systemic_decline} 时降1级）；RS=systemic_decline 时仓位降级至空仓观望；RS=leader 不降级保留有效信号 | 7 新测试全过；降级链可叠加（CF-C4 + P3 同时触发降2级） |

**Test results**: 132 classic_wyckoff 全过（62 基线 + 70 新增），0 ruff。Golden_20 冒烟 20/20 成功 2.2s，置信度首次出现 A 级（1/20），结构分分布拉开（p50=62.66, p90=65.0）。详见 `docs/analysis/WYCKOFF_OPTIMIZATION_TASKLIST_20260802.md`。

## Recent Work (2026-08-02) — Classic Wyckoff P1 非 P0 修复 (CN-C4 + SQ-C1 + RS-C1)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **CN-C4** | 复权状态探测 | `engine.py` 新增模块级 `_detect_adjustment_status`（收盘 pct_change>20% 且前日非涨停 → raw 预复权标记）+ `_analyze_single` 计算 + `_build_report` 透传 `adjustment_status` 字段（WyckoffReport/WyckoffOutput）；raw 信号置信度降级处理 | 8 新测试 `test_phase3_nonp0.py` 全过；compliance 改源码特征检查 → 51.7% (12P) |
| **SQ-C1** | 结构完整性评分 | `engine.py` 新增模块级 `_compute_structural_score` 纯函数（基于 `event_sequence_score` + 相位加成 + step3 spring/utad 加成，min-max→0-100）+ `_apply_structural_adjustment` 置信度加权（恒回填 `ConfidenceResult.structural_score`，≥70 升 1 级/≤35 降 1 级，A/D 边界不越界，B+ 归 B，5 条件矩阵成员不变）；`WyckoffReport`/`ConfidenceResult`/`WyckoffOutput` 均加 `structural_score`；`_extract_from_report` 透传；`WyckoffAdapter.adapt` metadata 加 `wyckoff_structural_score` | 19 新测试 `test_structural_score.py` 全过（含确定性回归 + 置信度加权单调性）；compliance 改源码特征检查（含 `_apply_structural_adjustment`）→ 55.0% (13P) |
| **RS-C1** | 相对强弱四分类 | 新增 `src/uniquant/brain/wyckoff/relative_strength.py`：`rs_classify(stock, index)` 纯函数（leader/follower/weak_independent/systemic_decline 四分类 + `_align_on_date` inner join 对齐 + `RelativeStrengthResult` dataclass）；`WyckoffReport`/`WyckoffOutput` 加 `relative_strength`/`relative_strength_detail`；`analyze`/`_analyze_single`/`_analyze_multiframe`/`analysis.analyze_multiframe` 加 `index_df` 可选参数（None 时报告字段为 None，向后兼容） | 11 新测试 `test_relative_strength.py` 全过；compliance 改源码特征检查（模块存在 + 4 分类 + 引擎接线）→ **58.3% (14P/7Pa/9F/30)** |

**Test results**: 1955 passed (含 3 组 P1 新增测试 + SQ-C1 置信度加权 8 测试), 0 ruff (新增文件), golden_20 baseline 一致。`scripts/classic_wyckoff_compliance.py` CN-C4/SQ-C1/RS-C1 三项检查从静态占位改为源码特征检查。**P1 三项全部完成**（红蓝对抗修订版 v2 方案，详见 `docs/analysis/CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1.md`）。剩余 WONTFIX：CN-C1/C2/C3、VS-C1/C3、MT-C2、RS-C2、CF-C1 等交易规则类/无数据支撑项（研究平台定位不符）。

## Recent Work (2026-08-02) — 全量 Wyckoff 扫描 + 指数数据净化 (W1/W2/W3/S1-S3)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **W1** | 服务层 index_df 透传 | `wyckoff_analysis_engine.py` `run_wyckoff_analysis` 加 `index_df: Optional[pd.DataFrame]=None` 参数；新增 `_load_index_df`（`_INDEX_PATHS=("data/lake/quotes/daily/000300.SH.parquet","data/csi300_index.parquet")`）；`analyze(df, multi_timeframe=True, index_df=index_df)` | 3 新测试（index_df 透传用 `patch("uniquant.brain.wyckoff.engine.WyckoffEngine")` + `_load_index_df` 加载/缺失返回 None）→ 13 passed |
| **W2** | 分析服务字段保真 | `analysis_service_v2.py:_run_wyckoff`（508）当 result 是 `WyckoffOutput` 时 `WyckoffOutput.from_dict(result.to_dict())` 保留全 15 字段（adjustment_status/structural_score/relative_strength/pnf_phase_hint/rr_ratio），否则回退旧 5 字段 | 1 新测试（`_run_wyckoff` 捕获 `write_wyckoff` output 断言 6 字段保留）→ 34 passed |
| **W3** | 全量扫描脚本 | 新建 `scripts/wyckoff_full_scan.py`（`--symbols all/main_board/golden_20/golden_100`、`--max-workers`、`--output-dir`；analyze_one 异常隔离永不抛出；输出 CSV+JSON；analyze 带 multi_timeframe=True+index_df） | ruff clean（E402 加 noqa） |
| **S1** | golden_20 冒烟 | 20/20 成功 2.1s；RS 四分类正常（follower 10/systemic_decline 7/leader 3）；复权 19 pre_adjusted+1 raw；结构评分 p50=59.95 | 冒烟通过 |
| **S2** | 全量执行 | 5382 只 8 workers 531.5s（0.099s/只）；5374 成功 8 too_short；相位 distribution 2466/accumulation 1352/markdown 777/markup 171/unknown 608；置信度 D 4482/C 791/B 101；RS systemic_decline 3444/follower 1138/leader 765/weak_independent 11/None 16；结构评分 p50=60.03 | 结果在 `results/wyckoff_full/wyckoff_scan_all.csv/.json` |
| **S3** | 数据净化 + 核验 | 归档 **552 个指数文件**到 `data/lake/quotes/daily/archive_index/`（198 个 000xxx.SH + 354 个 399xxx.SZ 深证指数，含 .bak/.tmp.lock 伴生共 2656 文件）；`get_symbols` 只扫 `daily/` 根目录 *.parquet 天然排除子目录；保留 000300.SH/000905.SH 基准原位；确认 close>1000 余下 9 只全为真实高价股（600519 茅台 2601/688256 寒武纪 1868 等）；发现并保留 137 个 ETF/B股/LOF 标的（159/160/161/16x 段） | 移除非 000xxx.SH 股票: 0；index symlink 完整；47+62 相关测试 passed |

**候选池**（`results/wyckoff_full/candidates.csv`）：A股个股 5245 只中 **306 只**满足 C级+ 置信度 & 结构评分≥60 & phase∈{accumulation, distribution}；Top 含 601865.SH(accumulation/B/61.93/leader)、002753.SZ(distribution/B/61.41/leader)、001286.SZ 等。**Test results**: 47 (wyckoff_engine+analysis_service_v2) + 62 (classic_wyckoff) passed，0 ruff（新增文件）。全量 1955 测试因单文件 coverage 门槛+耗时超时未完整跑通（本次改动未触及 Wyckoff 引擎核心，仅服务接线与扫描脚本）。数据净化发现：daily 池长期混入 000xxx.SH 上证指数（000001.SH close 达 6092）与 399xxx.SZ 深证指数，已归档隔离。

## Recent Work (2026-07-13) — v6 修复执行 (六路并行红蓝对抗)

| Phase | Tasks | Summary | Verification |
|---|---|---|---|---|
| **R0 (2026-07-13)** | 4 项代码修复 + 测试导入更新 | signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。更新 7 测试文件导入路径。 | 1678 passed, 0 ruff |
| **R1 (2026-07-13)** | 工程窄化 + 文档纠正 | lppl_visualizer.py 已有 exc_info=True (确认已存在无需改)、AGENTS.md 指标更新 (252 文件/60,351 LOC 活跃)、死代码 ~2,217 LOC 归档。 | 1678 passed, 0 ruff |

**Key corrections from v6 multi-pass verification (2026-07-13):**
- 纠正 v5 虚假完成声明: ui/ `except Exception` 仍为 17 处 (非 2), 从未被纠正
- 新发现死代码: factor_governance.py (156 LOC), portfolio_engine.py (376 LOC) — 已归档
- 纠正: 8 数据源 (非 7), Wyckoff 复杂度 45 (非 40), computation.py 393 LOC (非 242)
- 纠正: interfaces.py 5 个 Protocol (非 4), Alpha score=0.0 3 处 (非 2)
- 纠正: 函数总数 2,249 (非 2,262), except Exception 225 (非 224)
- 确认: 17/17 P0/R 修复全部存在, signal/ 层 100% 文档准确
- 确认: manager_logic.py 6 处 except Exception 已有 as e + exc_info=True, 无需窄化
- 剩余: R1-06 过户费 DRY 统一 (WONTFIX: 3 实现点, 向量化/标量签名不兼容), R3-N01 45 零覆盖文件 (~16h)

## Recent Work (2026-07-17) — v7 管线验证执行

| Phase | Task | Summary | Verification |
|---|---|---|---|
| **P1-A** | 文档状态同步 | `repair_plan_lppl_wyckoff.md` 添加"历史参考"横幅 (11 项已修复) | 已标记 |
| **P0-A** | 基线捕获 | `capture_baseline.py` 对 golden_20 捕获 v0 baseline | 20/20 成功, compare 0 diff |
| **P0-B** | LPPL 路径统一 | `_process_window` 从 DE 切换为 L-BFGS-B (直调 `fit_single_window_lbfgsb`) | 53 tests pass |
| **P0-C** | Spring 验真 | 对 golden_20 运行 LPPL+Wyckoff 交叉验证 | 20/20 股票, 62.9s |
| **P1-B** | Wyckoff 测试 | `_step4_risk_reward` 4 种目标位来源单元测试 | 4/4 pass |
| **P2-A** | ATR 自适应 | `classify_top_phase` 新增 `atr_pct` 可选参数 | 34 LPPL tests pass |
| **P2-B** | 跨引擎测试 | LPPL+Wyckoff+Factor brain 级引擎集成测试 | 3 new tests pass |
| **P1-C** | IC 半衰期 | **待办** — 设计已明确, 复用 `ic_ir_history` 字段 | — |

**P0-C 交叉验证关键发现**:
- DE 优化器成功率 0.0% (282 窗口全失败), L-BFGS-B 成功率 100% (564/564) — 验证 P0-B 方向正确
- R² 引擎/计算器口径差均值 0.814, 最大 0.976
- Wyckoff 置信度分布: 0 A, 0 B, 18 C, 2 D
- Spring 事件 (H12): 0 次触发 (20 股票历史数据中无 Spring→Markup 事件)

## Recent Work (2026-07-20) — v7 代码强化 (6 项)

| Phase | Task | Summary | Verification |
|---|---|---|---|
| **W01-A** | Spring 检测安全化 | cross_validation: `signal.signal_type` → `(signal_type or "").lower()` 防御 None/大小写 | ✅ 行级核实 |
| **W01-B** | except 窄化 + 日志 (step3) | cross_validation: `except Exception: pass` → `except (AttributeError,TypeError,ValueError,KeyError) as e: print(...)` | ✅ 行级核实 |
| **W01-C** | except 窄化 + 日志 (counterfactual) | 同上, counterfactual 路径 | ✅ 行级核实 |
| **W01-D** | H12 三态裁决 | `CONFIRMED`/`NOT_CONFIRMED`/`NOT_TESTED` 三态区分零事件场景 | ✅ 行级核实 |
| **W02-B** | R² 口径文档化 | `engine.py:detect_bubble()` 标注 3-param VP vs 7-param 全量 R² 不可比 | ✅ 行级核实 |
| **W02-C** | LPPLOutput.r_squared 字段注释 | `interfaces.py:LPPLOutput.r_squared` 标注前述口径差异 | ✅ 行级核实 |

**Test results**: 1882 passed, 7 skipped, 0 ruff (0 new, 16 pre-existing in cross_validation script).

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 1 (P&F 先行)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **PF-C3** | TR 边界来自 P&F 密集区 | `pnf.py` 新增 `congestion_zone()`（最长重叠列簇 + 列中位数边界抗尖峰）；`engine.py:_step0_bc_tr_scan` 接受 `pnf_zone` 优先覆盖裸 H/L 边界 | 4 新测试通过（含尖峰鲁棒性） |
| **PF-C1** | P&F phase_hint 驱动 Phase | P&F 提前到 Step0 之前构建；`_step1_phase_determine(df, rule0, pnf_hint)` 在 hint ∈ {accumulation, distribution} 时直接判定 | mock 测试通过 |
| **PF-C2** | Count Target 进交易计划 | `_step4_risk_reward(df, step1, step3, rule0, pnf_count_target)` 在 PNF 目标 > 现价时采用为第一目标；key_low > 现价时回退近 30 日低点止损 | mock 测试通过 |

**Test results**: 185 passed (181 基线 + 4 新增 `tests/classic_wyckoff/test_phase1_pnf.py`), 0 ruff。
**Compliance**: 23.3% → 33.3% (+10.0%), D1-PnF 维度 10% → 70% (PF-C1/C2/C3 全部 FAIL→PASS)。`scripts/classic_wyckoff_compliance.py` 的 PF-C1/C2/C3 检查从静态占位改为源码头检查。
**真实数据行为变化**（P&F hint 生效的预期结果）: 300750.SZ markdown→accumulation, 688981.SH markup→distribution; 止损 > 现价场景已修复（不再出现负风险）。

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 2 (事件序列: ES-C3 UTAD + ES-C1 Spring + PH-C1/C2 相位)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **ES-C3** | UTAD 检测 | `engine.py` 新增共享 `_scan_utad`（X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 量比>1.5 放量确认）；`_detect_utad` 从 `return None` 实现为驱动 `DISTRIBUTION` 相位；`_step3_phase_c_t1` 内联 UTAD 检测改用同一助手并填充 `utad_detected/utad_quality/utad_date` | 4 新测试通过（含 sine 无假阳性） |
| **ES-C1** | Spring 检测 | `engine.py` 新增共享 `_scan_spring`（O 列跌破 TR 下沿 0.5-1.5% `boundary_lower*0.985 <= low < boundary_lower` 后 1-2 列内收回 `closes[j] >= boundary_lower` + 量能萎缩确认 `vol_ratio <= 0.8`）；`_step3_phase_c_t1` 内联 Spring 检测改用同一助手并填充 `spring_detected/spring_date/spring_low_price`，替代旧 `SPRING_LOW_FACTOR` 独立判定；`scripts/wyckoff_fixtures.py` 新增 `synthetic_spring_aligned` 端到端 fixture（对齐引擎 P&F TR 边界） | 3 新测试通过（正例/反例/端到端） |
| **PH-C1** | ACCUMULATION 事件序列驱动 | `engine.py` `_detect_accumulation` 优先检查事件序列（`detect_all_events` + `event_sequence_key`，PS+SC+ST×2 匹配时直接判定 ACCUMULATION 并忽略 price_position），现有 prior_trend/relative_position 启发式降为 fallback；`scripts/wyckoff_fixtures.py` 新增 `synthetic_accumulation_event_sequence` fixture（P&F hint=unknown + 中位价格 0.41，仅事件序列可驱动） | 3 新测试通过（fixture 前提/端到端 ACCUMULATION/序列 key 含 PS+SC+ST×2） |
| **PH-C2** | DISTRIBUTION 事件序列驱动 | `engine.py` `_detect_distribution` 优先通过共享 `_scan_utad` 检查 UTAD 假突破事件（忽略 price_position），现有 in_tr+prior_trend 启发式降为 fallback；`_detect_distribution` 在检测器链中提前至 markdown 之前（UTAD 强派发证据优先于普通下跌）；`scripts/wyckoff_fixtures.py` 新增 `synthetic_distribution_event_sequence` fixture（上涨→PSY→UTAD→LPSY→跌破，hint=unknown 非短路） | 3 新测试通过（fixture 前提含量比≥1.5/端到端 DISTRIBUTION/忽略低位 position） |

**Test results**: 21 passed (classic_wyckoff 全套), 0 ruff (engine/test)。
**Compliance**: 38.3% → 40.0% (PH-C1) → **48.3%** (D4-Phase 80%, PH-C1/C2 全 PASS)。`scripts/classic_wyckoff_compliance.py` PH-C2 检查改为 `_detect_distribution` 源码特征检查（`_scan_utad` + upthrust_candidate + 链提前）。
**剩余 P0**: CF-C4 (FAIL) → Phase 3 依赖 UTAD false_breakout。

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 3 (CF-C4 假突破惩罚)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **CF-C4** | 假突破惩罚 | `engine.py` 新增共享 `_scan_false_breakout`（突破 TR 上沿 2%+ `highs[i] > boundary_upper*1.02` + 量比>1.5 放量确认后 3 列内跌回 `closes[j] <= boundary_upper*0.995`，返回 `{date, close_high}`）；`_step5_trading_plan` 调用并标记 `V3TradingPlan.false_breakout_detected=True`（方向改"空仓观望"）；`_build_report` 经模块级 `_downgrade_confidence`（A→B→C→D）将信号置信度降 1 级 | 3 新测试通过（fixture 前提含普通 TR 不误报 / 标记+方向 / 端到端信号置信度 < 计划置信度） |

**Test results**: 1913 passed, 7 skipped, 0 ruff (engine/test)。classic_wyckoff 24 测试全过。
**Compliance**: 48.3% (D7-Counterfactual 50%, CF-C4 PASS)。`scripts/classic_wyckoff_compliance.py` CF-C4 检查改为 `_scan_false_breakout` 源码特征检查（1.02 突破 + vol_med 放量 + 3 列跌回 + false_breakout_detected + _downgrade_confidence）。
**P0 全部完成**: PF-C1/C2/C3, ES-C1/C3, PH-C1/C2, CF-C4 全部 PASS。

## Recent Work (2026-07-23) — Walk-Forward 效用终结评估 (2026-07-23)

| Phase | Tasks | Key Deliverables |
|---|---|---|
| **W3-A** | LPPL 全量扫描 | 3574/3574 股票, L-BFGS-B 100% 收敛, 99.7min, Best R²=0.83 |
| **W3-B** | Wyckoff 全量扫描 | 3574/3574 股票, 9.1min, UNKNOWN 36.3%/MARKDOWN 57.1% |
| **W3-C** | 交叉验证 | 3574 股, 24.0% 方向冲突, 综合评级 D/54.9 |
| **W3-D** | 交叉截面回测 | LPPL rank vs 60d ρ=−0.058, Wyckoff rank vs 60d ρ=0.66 (自循环) |
| **W3-E** | Walk-Forward 回测 | **500 只 × 6 滚动窗口 = 2999 obs**, 104s |
| **W3-F** | 根因诊断 + 实际引擎信号重测 | 实际引擎分类 vs 自定义分类对比, Monte Carlo 对照, 6 项终论 |

**Walk-Forward 最终诊断: 自定义分类掩盖了唯一有效信号**:

| 发现 | 证据 |
|---|---|
| **LPPL: 零预测力** — 全链路验证 | 93% GBM 纯随机数据拟合 R²>0.3 (MC 对照); 实际 `calculate_risk_level` "高危" fwd_20d=+4.77% vs "观察" +4.82% — 无区分度; "无效模型"反而 +6.44% 优于有效拟合; `is_danger` p=0.48 无统计显著性 → 建议从生产管线移除 |
| **Wyckoff 理论信号从不触发** | Spring→BUY (adapter) 0/600 次; UTAD→SELL 0/600 次; "卖出" 交易计划 0/600 次; 39% 窗口返回未知相位 |
| **Wyckoff "买入" - 唯一有效信号** | 仅在 markup 阶段触发 (27/600, 4.5%); fwd_20d=+13.33% win=88.9% vs 普通 markup +5.27% (p=0.0098, **统计显著**); 前 20d 涨幅 +9.05% — 追涨非抄底; 24/100 只股票触发, 5/6 窗口均有分布 |
| **Monte Carlo 对照** | 93% GBM 拟合 R²>0.3; m 分布与真实数据不可区分 (KS p=0.019); DANGER 分类率随机 62.6% vs 实际 57.7% — 纯噪声反略高于真实数据 |
| **引擎分类 vs 自定义分类偏差** | 自定义: Wyckoff distribution→SHORT 得到 −16.82% spread (方向性错误, 因 distribution 后继续上涨); 实际: 引擎"买入"→ +8.60% 20d spread (p=0.0098); 自定义分类 SWALLOWED 了唯一有效信号 |
| **综合评级** | LPPL ❌ 无效 (移除) \| Wyckoff 理论 ❌ 从不触发 \| Wyckoff "买入" ⚠️ 真实但太罕见 (4.5%) \| Spring ⚠️ 理论上正确但实践中从不触发 |

See `scripts/output/walk_forward_definitive_report.json` and `/tmp/walk_forward_actual.py` for complete analysis.

## Phase 2/3 Completion (2026-07-08)

All Phase 2 and Phase 3 small/independent tasks executed:

| Task | Summary | Files Changed |
|---|---|---|
| #33 | Expand E2E tests: 3 new engine coverage classes (UnifiedBacktest, SignalArbitrator, UnifiedMatching) | `test_e2e_integration_qa.py` |
| #45 | Signal timeout check in arbitrator: discard signals older than `max_age_seconds` | `arbitrator.py` |
| #47 | Remove `portfolio_engine.py` from `__init__.py` exports | `hands/backtest/__init__.py` |
| #48 | Narrow 8 broad `except Exception:` to specific types in `backtest.py` | `hands/strategies/backtest.py` |
| #49 | Create `brain/wyckoff/constants.py` with 7 named constants; migrate 4 Wyckoff files | `constants.py` (new), `analysis.py`, `engine.py`, `state.py` |
| #50 | Add adapter auto-discovery (`AdapterRegistry.discover()`) | `adapters.py` |
| #51 | Unify position calculation: add `PositionSizerProtocol` to `UnifiedBacktestEngine` | `unified_engine.py` |
| #52 | Create `.github/workflows/benchmark.yml` CI workflow | `benchmark.yml` (new) |
| #53 | Add assertions to 2 weak test functions | `test_indicators.py`, `test_scan_service.py` |
| #57 | Remove 12 vulture-identified dead code items (8 files) | `computation.py`, `numba_optimizer.py`, `events.py`, `baostock.py`, `unified_matching_engine.py`, `data.py` |
| #66 | Replace 2 `datetime.now()` in `time_provider.py` with `self.now()` | `time_provider.py` |

Test results: 245 passed, 1 skipped, 0 ruff issues.

## Remaining Untracked Files

`docs/analysis/` (7 .md files), `docs/pipeline_5round_report.md`, `.coverage`, `data/trade_calendar.csv`, `results/` — not committed.

---

## Control Documents

Read these first:

| File | Purpose |
|---|---|---|
| `AGENTS.md` | First project control context. Updated 2026-08-18 (structural_score 确定性修复 + 全量 5 窗进程池重跑) with live system map ref. |
| `docs/reanalysis/I_live_system_map.md` | Live system map (2026-07-09): corrected metrics, dead code inventory, ranked active bugs, data path heat map. |
| `docs/index.md` | Documentation entry point and state boundary. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Direct-call prompt playbook for staged system analysis. |
| `docs/remediation/FULL_STOCK_TEST_PLAN.md` | Full stock test plan (canary/medium/full staging). |
| `pyproject.toml` | Real package metadata, dependencies, pytest config. Use root file, not docs copies. |
| `config/config.yaml` | Main runtime configuration. |
| `src/uniquant/shared/interfaces.py` | Typed cross-layer contracts including `TradingSignal`, `ResearchDataPack`, `RegimeOutput`, `LPPLOutput`, `CZSCOutput`, `NtfOutput`, `WyckoffOutput`, `AlphaOutput`, and protocols. |
| `src/uniquant/services/service_container.py` | DAG dependency injection and service initialization. |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker analysis orchestrator. |
| `src/uniquant/services/research_pipeline.py` | End-to-end research pipeline. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy analysis engine factory. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters. |
| `src/uniquant/signal/arbitrator.py` | Sell-priority signal arbitration with confidence-based rules. |
| `src/uniquant/shared/time_provider.py` | RealTimeProvider / FrozenTimeProvider for testable time. |
| `docs/analysis/wyckoff_research_report.md` | Wyckoff WSO+WSS+Resonance — 7-phase empirical research report on 22,148 A-share observations. All findings traceable to Phase I–VII run output. |
| `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md` | **Wyckoff 深入再研究定稿 (2026-08-12)** — 对 08-12 正确实现方案的 5 窗跨 regime 实证复核（F7 五窗无同号显著、T1 5/5 PASS、T3 1/4 FAIL、T4 漂移红线→P1-1 撤回、T5 过度→P1-11 默认关）、四轮红蓝裁决、修订版 P0/P1/P2 与 config 变更清单。实施 P0 前必读（与 Correct Implementation 两份对照）。**⚠️ 2026-08-18 更新**：`results/wyckoff_xs*/wyckoff_scan_all.csv` 已重跑为 39 列确定性版本（修复 WSS EMA 漂移 + 消除线程池竞态），旧 25 列 CSV 备份于 `/tmp/opencode/wyckoff_fix/old_scans/`。**⚠️ 2026-08-18 (P0) 更新**：净化 554 指数后 5 窗重扫为 **5201 只×39 列**（`all` 池 5755→5201），旧 5755 行 CSV 备份于 `/tmp/opencode/wyckoff_fix/old_scans_p0/`。**⚠️ 2026-08-18 (下游缺陷修正) 更新**：T1 n_buy 正式基线修正为 **86/27/69/174/123**（此前 82/23/66/166/118 受下游裸前缀误杀影响偏低），clean 池 n 5174/5185/5178/5133/5084。 |
| `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` | **Wyckoff 正确实现方案定稿 (2026-08-12)** — 引擎目标态=叙事+风控层；P0 信号链根除（direction 透传/adapter direction 优先/RDP 仅展平 wyckoff 键/置信门槛 0.40/关 structural_adjust/SELL-as-entry 禁）、P1 标注增强 12 项、P2 验证门 5 项、8 项明确不做。实施 P0 前必读。 |
| `docs/reanalysis/` | 10 comprehensive re-analysis reports (Phases 0-9) covering baseline, worktree, engines, backtest trust, data pipeline, signals, engineering health, production readiness, governance, and final roadmap. |
| `docs/reanalysis/Z_investigation_report_20260710.md` | 5-round multi-pass source code investigation (2026-07-10, updated w/ red-blue corrections) — verified 256 files, 17/17 fixes, 15 residual except patterns, research_pipeline thread safety, 51 new tests, 4 dead code files archived |
| `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md` | Comprehensive TDD red-blue adversarial analysis (2026-07-10) — 74 doc claims verified (87% accuracy), 224 except Exception mapped by layer, dead code corrected to ~2,225 LOC, 45 files at 0% coverage (3,791 LOC), 1 truly weak test |
| `docs/remediation/v5_remediation_work_list_20260710.md` | Verified remediation work list (2026-07-10) — all 11 P0 fixes confirmed FIXED, 14 remaining items ranked R0-R3 with file:line evidence, zero hallucination gate |
| `docs/remediation/red_blue_remediation_plan.md` | Red-blue remediation execution plan: Phase 0 (P0-01 through P0-10 core bugs), Phase 1 (P1-01 through P1-07 engineering health), Phase 2 (documentation + portfolio research). |
| `src/uniquant/shared/event_types.py` | Event/Command base and domain events. |
| `src/uniquant/shared/factor_governance.py` | FactorManifest / FactorRegistry with admission gate. |
| `src/uniquant/shared/config_models.py` | RefactoringConfig / FeatureFlags for staged migration. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed signal-driven backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized A-share matching engine. |
| `scripts/staged_full_scan.py` | Staged full-stock pipeline scan (canary/medium/full stages). |

Historical architecture and migration documents under `docs/` are useful background, but many still describe target state or pre-remediation gaps. Prefer current source code and the control documents above.

---

## Layer Responsibilities

| Layer | Path | Files | Responsibility |
|---|---:|---:|---:|
| `shared` | `src/uniquant/shared/` | 44 | Protocols, constants, config, exceptions, cache, logging, A-share rules, costs, slippage, price collars (dead), time_provider, event_types, factor_governance (dead), config_models. |
| `data` | `src/uniquant/data/` | 67 | Multi-source data ingestion, TDX/local/online sources, data lake, managers, parsers, cleaners, validators, adjusters. |
| `brain` | `src/uniquant/brain/` | 54 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 8 | Standard signal models, adapters, normalization, aggregation, quality checks. |
| `hands` | `src/uniquant/hands/` | 33 | Backtesting, matching, portfolio engine (dead), strategy framework, reports, robustness and sensitivity tools. |
| `risk` | `src/uniquant/risk/` | 6 | Position sizing, drawdown, EVT, structural risk, portfolio optimization. |
| `services` | `src/uniquant/services/` | 31 | DAG service container, analysis orchestration, data service, cache coordination, reports, scan, health, research pipeline. ⚠️ 1,651 LOC legacy dead code (analysis_service_legacy.py). |
| `ui` | `src/uniquant/ui/` | 8 | Streamlit dashboard, health check, UI manager logic, LPPL visualization. |

---

## Core Runtime Flow

Single ticker research path:

1. `ServiceContainer.initialize()` constructs data, cache, analysis, signal, backtest, and research pipeline services.
2. `DataService.fetch_for_brain()` returns `data_pack` with stock data and metadata.
3. `AnalysisService.run_ticker_analysis()` runs regime, LPPL, NTF, CZSC, Wyckoff, alpha, and derived indicator logic.
4. `DecisionBrain` produces the final decision payload.
5. `TradingSignalCollector` converts engine outputs into typed `TradingSignal` objects.
6. `UnifiedBacktestEngine.run()` executes signals against K-line data using A-share constraints.
7. `PipelineResult` returns `data_pack`, decision, signals, and `BacktestResult`.

Key files:

| Concern | File |
|---|---|
| Service DAG | `src/uniquant/services/service_container.py` |
| Analysis orchestration | `src/uniquant/services/analysis_service_v2.py` |
| Pipeline orchestration | `src/uniquant/services/research_pipeline.py` |
| Engine lazy loading | `src/uniquant/services/analysis/engine_factory.py` |
| Signal conversion | `src/uniquant/signal/adapters.py` |
| Signal arbitration | `src/uniquant/signal/arbitrator.py` |
| Factor governance | `src/uniquant/shared/factor_governance.py` |
| Feature flags | `src/uniquant/shared/config_models.py` |
| Time provider | `src/uniquant/shared/time_provider.py` |
| Backtest execution | `src/uniquant/hands/backtest/unified_engine.py` |
| Vectorized matching | `src/uniquant/hands/backtest/unified_matching_engine.py` |

---

## A-Share Rules To Preserve

| Rule | Current source |
|---|---|
| Main board limit up/down | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| STAR/GEM limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| Beijing Stock Exchange rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| ST stock limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| T+1 sell restriction | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/hands/backtest/unified_matching_engine.py` |
| Commission, stamp duty, transfer fee | `src/uniquant/shared/cost_model.py` |
| Slippage | `src/uniquant/shared/slippage_model.py`, matching engines |
| Price collar | `src/uniquant/shared/price_collar.py` |
| Lot size | `src/uniquant/shared/market_rules.py` |

Any change touching these rules requires focused tests and explicit review.

---

## High-Risk Files

| File | Why it is risky |
|---|---|
| `src/uniquant/services/__init__.py` | Lazy import contract for service package. |
| `src/uniquant/shared/interfaces.py` | Cross-layer typed contracts and protocol boundaries. |
| `src/uniquant/shared/constants/__init__.py` | Aggregated constants export used broadly. |
| `src/uniquant/services/service_container.py` | Runtime dependency graph and service lifetime. |
| `src/uniquant/services/analysis_service_v2.py` | Main analysis workflow and failure defaults. |
| `src/uniquant/services/analysis/engine_factory.py` | Engine registration and lazy import behavior. |
| `src/uniquant/data/sources/tdx.py` | TDX source path used across data workflows. |
| `src/uniquant/data/pipeline/data_validator.py` | OHLC data correctness guardrail. |
| `src/uniquant/signal/adapters.py` | Converts heterogeneous engine outputs into executable signals. |
| `src/uniquant/hands/backtest/unified_engine.py` | User-facing typed backtest behavior. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | A-share execution constraints in vectorized matching. |
| `config/config.yaml` | Global runtime behavior. |

---

## Phase 0-6 Completion Status

All phases verified: **1882 tests pass, baseline 100% consistent**. 0 pre-existing failures.

| Phase | Scope | Status | Key deliverables |
|---|---|---|---|---|
| **0** | LPPL SELL priority, baseline tooling | ✓ | `unified_engine.py` SELL-before-BUY fix, `tests/benchmark/golden_20.txt`/`golden_100.txt`, `scripts/capture_baseline.py` + `compare_baseline.py` |
| **1.1–1.2** | BacktestResult metadata, typed contracts | ✓ | `BacktestResult.metadata`, `RealTimeProvider`, `FrozenTimeProvider`, domain events, `FactorManifest`/`FactorRegistry` |
| **1.4** | Feature flags, config models | ✓ | `RefactoringConfig`, `FeatureFlags`, `config.yaml` refactoring section, `ServiceContainer` DI |
| **2** | SignalArbitrator, TimeProvider adoption | ✓ | `SignalArbitrator` (sell-priority, confidence-based), 7 tests, pipeline integration, `FactorRegistry` admission gate |
| **3** | 6-engine typed output migration | ✓ | `RegimeOutput`, `LPPLOutput`, `NtfOutput`, `CZSCOutput`, `WyckoffOutput`, `AlphaOutput`, `DecisionOutput`, `MarketSignalContext` direct pass |
| **4** | Pipeline typing, engine output typing, batch parallelization | ✓ | `ResearchDataPack` + feature flag in pipeline & analysis & data services; 4 engines return typed outputs; `run_batch()` ThreadPoolExecutor + atomic checkpoint; `factor_gate: "block"` |
| **5** | Remediation — 7 threads (A–G) via TDD | ✓ | `use_research_data_pack` default flipped to `true`; Wyckoff 12 failures fixed; TradeCalendar AkShare auto-update; ResultStore persistence; DataFetcher single entry; BacktestResult.compare(); dead code cleanup; **Full stock test: 5934/5934 success (100%)** |
| **6** | Regime reliability — fail-open fix, dead code, TOCTOU | ✓ | `RegimeDetector.detect()` fail-open hardened (entropy/turnover NaN → UNKNOWN); `_validate_input_data()` wired; `_check_sell_conditions` FROZEN dead code removed; `MarketLevelCache.get_or_compute_regime()` TOCTOU fix; 16 new tests |

**Design**: All typed outputs coexist with legacy `Dict[str, Any]` keys for backward compatibility. Feature flags default ON for `use_research_data_pack` (flipped Phase 5 Thread A). `factor_gate: "block"` prevents unregistered factors.

## Re-analysis (2026-06-30)

Comprehensive 9-phase re-analysis completed. Reports in `docs/reanalysis/`:

| Report | Phase | Trust Rating |
|---|---|---|
| `00_baseline_audit.md` | Baseline test/lint/import audit | ✅ 1426/1431 pass |
| `01_worktree_diff_analysis.md` | Worktree diff + stash analysis | 46-file commit classified |
| `02_engine_correctness_audit.md` | 8 engines graded | A- |
| `03_backtest_trust_audit.md` | 7 A-share defense lines verified | A- |
| `04_data_pipeline_reliability.md` | 5-source routing + pipeline | B+ |
| `05_signal_system_audit.md` | 8 adapters + arbitrator | A |
| `06_engineering_health.md` | Lint, TODOs, imports | A- |
| `07_production_readiness.md` | Security, config, observability | B+ |
| `08_governance_testing.md` | Test structure, CI gaps | B+ |
| `09_final_roadmap.md` | Priority roadmap P0-P3 | — |
| `I_live_system_map.md` | Corrected live system map (2026-07-09) | 256 files verified |

---

## Working Rules For Agents

- Start with current source code, not historical docs.
- Before meaningful multi-file work, create a short plan.
- Prefer narrow analysis and narrow edits.
- Do not revert user or prior-agent changes.
- Treat the working tree as possibly dirty. Inspect `git status --short` before edits.
- Use `rg` and `rg --files` for searches.
- Use `apply_patch` for manual file edits.
- For code changes, follow TDD where practical: identify failing path, add/update tests, implement, verify.
- For sensitive paths, review auth, data validation, injection risk, secrets, and error leakage.
- After meaningful changes, review the diff and record verification performed.
- **Sync docs with every change**: After any code modification (feature, refactor, bugfix), update `AGENTS.md` and all affected documentation under `docs/`. At minimum refresh file counts, LOC, test counts, and phase status. Treat documentation drift as a blocker, not a backlog item.

---

## Common Commands

```bash
# Install all optional extras
pip install -e ".[all]"

# Full test suite
pytest tests/ -q

# Baseline verification
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py

# Engine factory smoke tests
pytest tests/test_engine_factory.py -xvs

# Eight-layer import smoke
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# Config smoke
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# Service container smoke
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"

# Full stock pipeline scan (canary → medium → full)
python3 scripts/staged_full_scan.py --stage canary --max-workers 4
python3 scripts/staged_full_scan.py --stage medium --max-workers 4 --seed 42
python3 scripts/staged_full_scan.py --stage full --max-workers 4

# Lint source
ruff check src/uniquant/

# Dashboard
streamlit run src/uniquant/ui/dashboard.py

# Parameter sweep (v2, with resume support)
python3 scripts/param_sweep_v2.py --symbols golden_20 --resume
python3 scripts/param_sweep_v2.py --symbols golden_100 --lookback-days 252 --range-thresholds 0.20 0.30

# Parameter sweep (v1, legacy)
python3 scripts/param_sweep_v1.py
```

Do not claim test results are current unless the command was run in the current working tree.

---

## Analysis Workflow

For systematic system analysis, use:

`docs/ANALYSIS_PROMPT_PLAYBOOK.md`

It defines stages 0-7:

0. Global architecture
1. Services orchestration
2. Data system
3. Brain engines
4. Factor system
5. Signal system
6. Backtest and matching
7. Risk and live-readiness

Each stage requires a plan, concrete artifacts, checkpoint context, and verification checklist.

---

## Known Gaps (Post-Phase 5) — Full Plan in `docs/GAP_REMEDIATION_PLAN.md`

> **2026-06-12 update**: G-1 through G-4 have all been closed and verified in the institutional closure review. See `docs/analysis/institutional/17_institutional_closure_review_report.md` §Phase 6 Gap Review for the verified closure evidence.

### Quick Start For New Tasks

| If working on... | Read this first | And be aware of |
|---|---|---|
| Time-dependent code | `shared/time_provider.py` | 2 guarded `datetime.now()` remain in `time_provider.py` FrozenTimeProvider fallback |
| Factor registration/access | `brain/factors/registry.py` (actual) NOT `shared/archive/factor_governance.py` (dead code, archived) | shared/ deprecated with warning |
| Baseline/regression testing | `scripts/capture_baseline.py` + `compare_baseline.py` | Phase 0 all committed |
| Event-driven features | `shared/event_bus.py` (sync) + `shared/event_bus.py` (async) | AsyncEventBus deployed with 9 tests |
| Pipeline typing / data pack | `shared/interfaces.py` `ResearchDataPack` + `services/analysis_service_v2.py` dual-path | Feature flag `use_research_data_pack: true` default (flipped Phase 5); `to_dict()` flattens `metadata` for signal collector |
| Engine output typing | `shared/interfaces.py` (LPPLOutput/CZSCOutput/NtfOutput/WyckoffOutput) + engine files in `services/analysis/` | 4 engines return typed outputs; field annotations in ResearchDataPack are forward references |
| Batch research | `services/research_pipeline.py` `run_batch()` | ThreadPoolExecutor + atomic checkpoint; input order preserved via result map |
| Research result persistence | `shared/result_store.py` + `services/research_pipeline.py` | JSON file store under `results/{date}/{symbol}.json`; ResultStore.save() called after each successful run() |
| TradeCalendar | `data/managers/trade_calendar_manager.py` | AkShare auto-update with stale cache check (>180 days); hardcoded 2024-2026 fallback |
| BacktestResult compare | `hands/backtest/unified_engine.py` `BacktestResult.compare()` | Returns diff dict for parameter sensitivity analysis |
| Full stock scan | `scripts/staged_full_scan.py` + `docs/remediation/FULL_STOCK_TEST_PLAN.md` | 3-stage scan (canary→medium→full); `--stage canary|medium|full`; checkpoint resume; per-engine breakdown; error classification |
| Regime detection safety | `brain/regime/regime_detector.py` fail-open paths | Phase 6: entropy/turnover NaN → UNKNOWN (was NORMAL); `_validate_input_data()` wired into `detect()` |
| Market cache TOCTOU | `services/market_cache.py` `get_or_compute_regime()` | Phase 6: atomic get-or-compute prevents parallel recompute in batch mode |
| FSM dead code | `brain/fsm/fsm.py` `_check_sell_conditions()` | Phase 6: FROZEN removed (unreachable — veto fires first); STRESSED only |
| System overview / metrics | `docs/reanalysis/I_live_system_map.md` | 256 files verified; dead code inventory; ranked active bugs; data path heat map |
| Red-blue analysis | `docs/reanalysis/E_red_blue_analysis.md` | 22-issue confrontation corrected bug counts (4→6), defense lines (5✅/1⚠️/1❌), capability matrix (15✅/2⚠️/3❌) |
| 5-round investigation | `docs/reanalysis/Z_investigation_report_20260710.md` | 256 files verified, 17/17 fixes confirmed, 15 residual except patterns |
| 修复并行化分析 | `docs/remediation/parallel_analysis.md` | 34 项任务并行调度: 24h→7.5h (3.2x) |
| Shenzhen transfer fee exemption | `src/uniquant/hands/backtest/unified_matching_engine.py` + `unified_engine.py` | P1-01: SZ stocks `_has_transfer_fee()` returns `False`; both matching and engine layers updated |
| Adapter alpha=0.0 | `signal/adapters.py:362` | P0-01 **FIXED**: `elif 0 < score < 0.3:` excludes 0.0 (was `elif score < 0.3:` → false SELL) |
| fillna(0.0) factor distortion | `brain/factors/composer.py:183,204,276` | P0-04 **FIXED**: all 3 fillna(0.0) removed |
| Pipeline bare except | `services/research_pipeline.py:239` | P0-08 **FIXED**: narrowed to specific exceptions |
| Wyckoff bare except | `brain/wyckoff/engine.py:251,261,1575,1591` | P0-09 **FIXED**: 4 bare excepts narrowed |
| Signal timeout disabled | `signal/arbitrator.py:39` | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` — backtest-aware context needed for enable |
| price_collar dead | `shared/price_collar.py` | Zero production callers; remove from P1 consideration |
| DynamicSlippage dead | `shared/slippage_model.py:DynamicSlippage` | Never instantiated in default backtest path |
| BoardType unified | `shared/board_registry.py` | 116 LOC — BoardType dual system resolved via registry |
| Walk-Forward 回测终结结论 | `scripts/output/walk_forward_definitive_report.json` + `/tmp/walk_forward_actual.py` | 500 只 × 6 窗口 walk-forward 验证: LPPL 零预测力 (MC 证明 93% GBM 噪声拟合), Wyckoff 理论从不触发, Wyckoff "买入" 4.5% 罕见信号 p=0.0098 显著, 自定义分类掩盖了唯一有效信号 |
| 参数敏感性验证脚本 | `scripts/param_sweep_v2.py` | 经 3 轮红蓝对抗修正的 Wyckoff 参数扫描脚本: CLI 参数控制、同相位对比、bootstrap-by-stock CI、Mann-Whitney U + Bonferroni、断点续传、参数排名表。配套分析: `docs/reanalysis/Z_param_sweep_v1_redblue_round*.md` |

## Recent Work (2026-08-03) — Wyckoff 多周期多阶段实证分析

完成 6 期 as-of 日期(2024-01-31→2026-05-15)对 golden_100 的全量 Wyckoff 扫描，输出相位分布、前向收益、阶段转换统计和经典 Wyckoff 理论一致性评估。

**关键发现**:

| as_of | accum_mean | markup_mean | dist_mean | md_mean | 理论得分 |
|---|---|---|---|---|---|
| 2024-01-31 | +19.29% | +10.37% | +22.07% | +19.71% | 50.0% |
| 2024-06-28 | -3.64% | -1.14% | -1.64% | -4.81% | 50.0% |
| 2024-12-31 | +3.66% | +5.37% | +4.98% | +4.72% | 50.0% |
| 2025-06-30 | +9.55% | +8.23% | +10.58% | +6.29% | 50.0% |
| 2026-01-30 | -2.56% | +6.99% | +1.37% | -1.79% | 50.0% |
| 2026-05-15 | -0.14% | -3.19% | -0.19% | -9.50% | 50.0% |

**总体理论一致性**: 50.0% (12/24) — markup 上涨(4/6)和 markdown 下跌(4/6)方向正确，但 accumulation 不保证上涨(3/6)且 distribution 不保证下跌(2/6)

**阶段转换统计**: 总转换 500 次，正确 198 次(39.6%) — 最大的错误转换是 accumulation→distribution(74 次)和 distribution→accumulation(63 次)，表明引擎频繁混淆积累与派发阶段

**落地评估**: ⚠️ 部分落地 — 引擎在部分市场环境下有效，但需持续改进。引擎能捕捉 markup/markdown 方向，但 accumulation/distribution 相位判定与经典 Wyckoff 理论偏差显著。详见 `scripts/wyckoff_multi_period_analysis.py` 和 `/tmp/multi_period/wyckoff_multi_period_golden_100.json`
