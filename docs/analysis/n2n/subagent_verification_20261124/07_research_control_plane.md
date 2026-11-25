# 工作流 7：研究控制平面 N2N 独立复核报告（Subagent 验证）

> **分析日期**：2026-11-24
> **代码基线**：`b1d2415`（与任务基线一致；源码头 434aab1→b1d2415 对 `src/uniquant/research/` 与 `src/` 的 diff 为空，即本报告与既有 Claude 报告核对的源码完全相同）
> **分析范围**：`src/uniquant/research/`（12 文件, 1,885 行：`gates/` `ledger/` `sandboxes/`）+ 上游 `brain/factors/`（Lookahead/AnalysisMode 交叉点）+ 下游 `services/scan_service.py`（生产接线点）
> **方法**：独立 Name-to-Node 代码级点对点审查（先独立分析，后交叉复核既有报告 `docs/analysis/n2n/07_research_control_plane_n2n.md`）
> **执行方式**：静态阅读全部 12 文件 + 运行 3 个研究测试文件（49 passed）+ 2 个实证脚本（`/tmp/opencode/verify_research_findings.py`、`/tmp/opencode/verify_sandbox_provision.py`）

---

## ① 执行摘要

研究控制平面的**统计核心实现是正确且 Rule 4 合规的**（诚实门禁、BH-FDR/Bonferroni/BY 三步校正、Newey-West HAC、DSR 全部核实正确；49 个定向测试全绿）。但**运营接线存在系统性断裂**：

- **四阶晋升引擎（AlphaTierEngine）在当前代码库中没有任何生产调用方** —— 仅被单元测试与沙盒自引用（`sandboxes/__init__.py`）触及，`services/` 与 `scripts/` 无一调用 `evaluate_candidate`/`promote_candidate`。核心防过拟合门禁是**测试专用组件**，未对任何真实因子/策略生效。
- **三个生产沙盒（Wyckoff/CANSLIM/LPPL）从不提供** `residual_ic_series`/`pbo_value`/`gate_inputs`，故 `evaluate_through_gates(df)` **恒返回 `TIER_UNRATED`**（实证确认）。沙盒晋升路径结构上无法晋升任何策略，除非调用方外部手算残差 IC + PBO + B/C/D 输入并显式传入（无生产代码这样做）。
- **Class A 的 BH-FDR 多重测试校正在门禁路径上不累积** —— 门禁读取的 `p_adj_bh_fdr` 来自 `self.ledger`（每次沙盒调用新建的内存账本），单试验族下 `p_adj_bh_fdr == p_raw`（实证确认），多重测试惩罚被绕过。持久化 `LedgerStore` 仅接入了桥接路径（`scan_service.register_factor_trials`），**未**接入门禁引擎。

**健康度评级：C+（条件就绪）** —— 统计门禁本体正确、Rule 4 诚实门禁达标（这是优点），但晋升管道未接线、多重测试防线在门禁路径被绕过、沙盒恒 UNRATED（运营惰性）。

| 级别 | 数量 | 编号 |
|---:|---:|---|
| CRITICAL | 1 | C1 |
| HIGH | 2 | H1, H2 |
| MEDIUM | 3 | M1, M2, M3 |
| LOW | 3 | L1, L2, L3 |

**对既有 Claude 报告的关键分歧**：既有报告评级"优秀/可信"并称"四阶门禁优秀/多重测试校正优秀/依赖链清晰"，但**未核查生产接线**（门禁引擎无生产调用方）、**未核查沙盒真实输入供给**（恒 UNRATED）、**未识别 Class C 换手 fail-open**、**未识别 `cross_section_N=500` 硬编码**。独立评审人已提的 M2（账本持久化未评估）经核实应升级为 HIGH（持久化仅在桥接路径，门禁路径未持久化）。详见 §⑤ 交叉复核矩阵。

---

## ② 五问逐节点答案

> N2N 路径按任务给定，但**首节点名与代码不符**（见 Q1）：`FactorRegistry.register_trial` **不存在**于 `FactorRegistry`（`registry.py` 184 行无此法）；真正的试验注册节点是 `DegreesOfFreedomLedger.register_trial`（`degrees_of_freedom.py:234`）与桥接入口 `register_factor_trials`（`bridge.py:175`）。本报告按**真实**节点作答，并保留任务原路径标注。

### 节点 0：`FactorTrial`（试验/因子注册）
- **任务标注**：`FactorRegistry.register_trial`。
- **Q1 定义**：**不存在**。`FactorRegistry`（`src/uniquant/brain/factors/registry.py:36-184`）仅有 `register/get_all/get_enabled/get_factor/enable/disable/list_factors/set_mode/get_mode/has/check_access`，无 `register_trial`。真实试验注册 = `DegreesOfFreedomLedger.register_trial`（`degrees_of_freedom.py:234-300`）或桥接 `register_factor_trials`（`bridge.py:175-262`）。**任务路径命名有误**。
- **Q2 映射**：试验 → `TrialRecord`（`degrees_of_freedom.py:65-89`），含 `p_raw/effective_m/p_adj_bonferroni/p_adj_bh_fdr/p_adj_by_fdr/alpha_wealth_spent/trial_index`。
- **Q3 传播**：`register_trial` → `compute_effective_m`（`:255`）→ 扣减 Alpha-Wealth（`:263-269`，余额不足抛 `PermissionError`）→ 追加 `_family_map[family_id]`（`:291`）→ `_recompute_family_adjustments(family_id)`（`:293`）。
- **Q4 变异**：余额不足 → `PermissionError`（`:263-267`，硬失败）；桥接路径捕获并置 `alpha_wealth_exhausted=True` 优雅中断（`bridge.py:238-241`）；`compute_effective_m` 空/单相关矩阵回退 `m=len(family)+1`（`:218-219`）。
- **Q5 治理**：`code_git_sha`/`data_snapshot_hash`/`created_at`（UTC ISO）/`metadata` 字段（`:84-89`）；`to_state/from_state` 序列化（`:173-206`）。

### 节点 1：`DegreesOfFreedomLedger.register_trial(trial)`
- **Q1 定义**：`degrees_of_freedom.py:234-300`，线程安全（`RLock`，`:166`）。
- **Q2 映射**：试验 → 校正后 p 值 + Alpha-Wealth 消耗。关键：`m_eff = compute_effective_m(...)`（`:255`）；相关矩阵 >1 检验时按 `m_eff/k` 折算投标（`:257-261`）；`alpha_wealth_spent=actual_bid`（`:284`）。
- **Q3 传播**：`_recompute_family_adjustments` 对该族全量试验动态重算 Bonferroni/BH-FDR/BY（`:293`）。
- **Q4 变异**：**单试验族（门禁默认路径）下 `m=1` → `p_adj_bh_fdr == p_raw`（实证确认）**。`register_sweep`（`:302-368`）批量注册用 `family_budget` 单次整体扣减 + M_eff 折算（`:323-334`）；通过 FDR 试验奖励 Alpha-Wealth（`:296-298, :363-367`）。
- **Q5 治理**：`get_hurdle_report`（`:432-445`）输出族累积试验数/平台总试验数/Alpha 财富/BH/Bonf 显著计数；`LedgerStore` 原子 JSON 落盘（`ledger_store.py:53-79`，`os.replace` 原子写）。

### 节点 2：`AdjustedPValue`（BH-FDR 多重测试校正）
- **Q1 定义**：`_recompute_family_adjustments`，`degrees_of_freedom.py:393-430`。三法：Bonferroni（`:403-406`，`min(1, p_raw × max(m, effective_m))`）；BH Step-Up（`:409-421`，`(m/rank)×p` 排序 + 逆序累积最小值保单调 + clip[0,1]）；BY 任意依赖（`:424-425`，`q_by = q_bh × c_m`，`c_m=Σ1/i`）。
- **Q2 映射**：`p_raw` → `p_adj_bonferroni/p_adj_bh_fdr/p_adj_by_fdr` + `passed_*` 布尔。
- **Q3 传播**：`p_adj_bh_fdr` 被 Class A 门禁消费（`alpha_tier_engine.py:131,152`，阈值 `max_p_adj_bh=0.05`）。
- **Q4 变异**：**BH 实现正确**（Step-Up 单调性经 `np.minimum.accumulate(raw_adjusted[::-1])[::-1]` 保证）；`m=1` 时 `p_adj_bh=p_raw`（无惩罚，见 H2）；空族早退（`:399-400`）。
- **Q5 治理**：`passed_bh_fdr <= fdr_nominal`（`:430`，`fdr_nominal=0.10` 默认 `:157`）；奖励 Alpha-Wealth（`:296-298`）。

### 节点 3：`AlphaTierEngine.evaluate(factor, ic, t_nw, icir, pbo)`
- **Q1 定义**：实际入口 `evaluate_candidate`（`alpha_tier_engine.py:439-540`）→ `promote_candidate`（`:542-641`）。Class A 统计量由 `ClassAEvaluator.compute_newey_west_t`（`:61-86`）计算。
- **Q2 映射**：IC 序列 → `mean_ic/t_nw/p_raw`（`:101`）；`icir = (mean_ic/max(std,1e-8))×√(252/horizon)`（`:103`）；残差 IC 均值/正比率（`:105-108`）。
- **Q3 传播**：诚实门禁（`:472-491`）→ Class A（`:562-578`）→ Class B（`:581-596`）→ Class C（`:599-617`）→ Class D（`:620-639`），逐级早退写 `rejection_reason`。
- **Q4 变异**：缺 `residual_ic_series`/`pbo_value` → `TIER_UNRATED` + 明确拒绝原因（`:478-491`，**Rule 4 合规，实证确认**）；样本量 <10 → `(0,0,1)` 中性值（`:65-66`）；HAC 方差 ≤1e-12 → `t=0,p=1`（`:80-81`）；Class B 的 `top_industry_weights` 做 `np.asarray(...,float64).ravel()` 防御（`:206-208`，消灭 `list**2` 崩溃）。
- **Q5 治理**：`GateResult` 记录 metrics+thresholds+details（`:34-40`）；`PromotionReport` 记录 `passed_class_a/b/c/d`+`rejection_reason`+`audit_metadata`（`:43-53`）；`audit_metadata` 含 `evaluated_at`+`platform_cumulative_trials`（`:555-558`）。

### 节点 4：`AlphaTier`（UNRATED/A/B/C/D）
- **Q1 定义**：`alpha_tier_engine.py:26-32`，`TIER_UNRATED="UNRATED"`、`TIER_A="TIER_A_STATISTICALLY_SUPPORTED"`、`TIER_B="TIER_B_ECONOMICALLY_PLAUSIBLE"`、`TIER_C="TIER_C_TRADABLE_CANDIDATE"`、`TIER_D="TIER_D_REPLICATED_STRATEGY"`。
- **Q2 映射**：四门阈值 Class A（`:135-143`：`min_abs_ic=0.025`、`min_abs_t_nw=3.00`、`min_icir=0.70`、`min_res_ic=0.015`、`min_pos_res_ratio=0.65`、`max_pbo=0.20`、`max_p_adj_bh=0.05`）；Class B（`:231-239`）；Class C（`:297-308`）；Class D（`:402-408`）。
- **Q3 传播**：逐级晋升，失败即止（`:575-577/593-595/614-616/636-638`）。
- **Q4 变异**：Class A 通过但 B 缺输入 → `TIER_A`（`:581-583`，合理：停在已达成的最高阶）；全通过 → `TIER_D`（`:639`）。
- **Q5 治理**：`GateResult.thresholds` 全量暴露（`:158`）；`details` 摘要（`:160`）。

### 节点 5：`FactorAccessLevel`（FREE/WARN/BLOCK）
- **Q1 定义**：`registry.py:17-21`，`FREE="free"`/`WARN="warn"`/`BLOCK="block"`。
- **Q2 映射**：**与 `AlphaTier` 无连线**。`FactorAccessLevel` 仅由配置 `gate_mode` 设置（`service_container.py:179-181`，`FactorAccessLevel(gate_mode)`），并在 `check_access`（`registry.py:174-184`）按**因子名是否注册**判定：BLOCK 未注册→`ValueError`、WARN 未注册→警告、已注册→True。
- **Q3 传播**：`check_access` 被 `get_enabled`（`:121`）/`get_factor`（`:128`）调用；**不消费任何 AlphaTier 结果**。
- **Q4 变异**：`_mode` 默认 `WARN`（`:47`）；`set_mode/get_mode` 线程安全（`:156-165`）。
- **Q5 治理**：单例 + `Lock`（`:43-54`）；`_ensure_loaded` 惰性加载（`:56-61`）。
- **⚠️ 关键发现**：**N2N 末节点"AlphaTier → FactorAccessLevel (FREE/WARN/BLOCK)"在代码中不存在接线**。`FactorAccessLevel` 是"因子名注册"治理门，独立于统计阶；AlphaTier 的 `final_tier` 从未被 `FactorRegistry` 读取。既有报告未覆盖此节点。

---

## ③ 端到端路径追踪

### 路径 1（正常·但测试专用）：真实四门全过 → TIER_D
```
FactorTrial(ledger.register_trial, degrees_of_freedom.py:234) 
→ _recompute_family_adjustments(:393) → p_adj_bh_fdr(:428) [m=1 时 =p_raw]
→ AlphaTierEngine.evaluate_candidate(alpha_tier_engine.py:439) 
  ├ 诚实门禁: residual_ic/pbo 齐备 → 通过(:478-491)
  ├ ClassA.evaluate(:562): |IC|≥0.025 ∧ |t_NW|≥3.00 ∧ |ICIR|≥0.70 ∧ 残差IC·sign≥0.015 ∧ pos≥0.65 ∧ PBO≤0.20 ∧ p_adj_bh≤0.05 → 通过(:145-153)
  ├ ClassB(:584): IRR_IC≥0.50 ∧ |纯IC|≥0.015 ∧ |t|≥2.50 ∧ R²≤0.35 ∧ |size_corr|≤0.30 ∧ maxInd≤0.25 ∧ HHI≤0.15 → 通过(:241-249)
  ├ ClassC(:602): CAGR≥0.12 ∧ SR≥1.00 ∧ |MDD|≤0.18 ∧ Calmar≥0.70 ∧ TO≤0.15 ∧ 保留≥0.65 ∧ minRegime>-0.50 ∧ posRegime≥2 ∧ ADV≥2e7 ∧ Cap≥3e7 → 通过(:310-321)
  ├ ClassD(:623): CleanCorr≥0.999 ∧ DSR≥0.95 ∧ QuarSR≥0.80 ∧ OOS_decay≥0.60 ∧ Adv_decay≥0.80 → 通过(:410-416)
  → final_tier=TIER_D(:639)
```
**结论**：统计链路正确（与 `tests/test_research_os_gates.py::TestAlphaTierHonestGate` 一致）。**但该路径仅存在于测试** —— 无生产调用方（见 C1）。

### 路径 2（异常·缺失输入 → UNRATED，Rule 4 合规）
```
evaluate_candidate("F", ic_series=[...], residual_ic_series=None, pbo_value=None)
→ missing=["residual_ic_series","pbo_value"](:474-477)
→ return PromotionReport(final_tier=TIER_UNRATED, rejection_reason="Class A 捷径已禁用…")(:478-491)
```
**实证确认**：`evaluate_candidate` 缺 `residual_ic_series`+`pbo_value` → `final_tier=UNRATED`，`rejection_reason` 非空。**Rule 4 合规、不静默回退**。

### 路径 3（异常·生产沙盒恒 UNRATED —— 新增关键发现 H1）
```
WyckoffStrategySandbox.run_sandbox_simulation(df) → SandboxSignalEvaluation(ic_series, daily_returns, turnover_series, metadata)  ← 无 residual_ic_series/pbo_value/gate_inputs(wyckoff_sandbox.py:89-98)
→ evaluate_through_gates(df)(base_sandbox.py:71-86) → evaluate_candidate(residual_ic_series=None, pbo_value=None) → TIER_UNRATED
```
**实证确认**：三个沙盒 `evaluate_through_gates(df)`（无外部覆盖）**均返回 `TIER_UNRATED`**（Wyckoff/CANSLIM/LPPL 三者皆然）。即使手动传 `residual_ic_series=sim.ic_series, pbo_value=0.10`，LPPL 仅产 1 个 IC 值（`lppl_sandbox.py:74-79` step=20 抽样），样本量不足亦失败。

### 路径 4（异常·多重测试不累积 —— 新增关键发现 H2）
```
AlphaTierEngine() → self.ledger = DegreesOfFreedomLedger()(alpha_tier_engine.py:437)  ← 每次沙盒调用新建(base_sandbox.py:68)
→ ClassA.evaluate → ledger.register_trial(:110) → 单试验族 m=1 → p_adj_bh_fdr = p_raw(:428)
→ 门禁 p_adj_bh_fdr≤0.05(:152) 退化为"原始 p≤0.05"检查
```
**实证确认**：单试验族下 `p_adj_bh_fdr == p_raw`（`verify_research_findings.py` B 节）。持久化 `LedgerStore` 仅在 `scan_service.py:131-136` 接入 `register_factor_trials`（桥接路径），**未**传入门禁引擎。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### CRITICAL

**C1 — 四阶晋升引擎无生产调用方（测试专用组件）**
- **位置**：`src/uniquant/research/gates/alpha_tier_engine.py:439`（`evaluate_candidate`）、`:542`（`promote_candidate`）；`src/uniquant/research/sandboxes/base_sandbox.py:71`（唯一调用点）；`scripts/factor_mining/run_conditional_validation.py:63`（局部同名函数，非引擎方法）。
- **证据**：`grep -rn "\.evaluate_candidate(\|\.promote_candidate(\|AlphaTierEngine(" src/ scripts/` 仅命中 `base_sandbox.py:68,71`（沙盒自引用）与模块定义；`services/` 无一调用。沙盒类（`Wyckoff/CANSLIM/LPPL`）仅被 `sandboxes/__init__.py` 自引用导出，`services/` 与 `scripts/` 无 import。唯一近似的 `run_conditional_validation.py:63` 是局部 `def evaluate_candidate(panel_mi, cand, states)`（参数签名不同）。
- **影响**：研究控制平面核心防过拟合四阶门禁**未对任何真实因子/策略生效**。桥接路径（`scan_service.register_factor_trials`）虽接线，但只做多重测试登记（`bridge.py`），不做四阶晋升。
- **修复**：在 `services/` 或 `scripts/` 建立真实调用方（如 `scripts/factor_mining/run_alpha_promotion.py`），把 `AlphaTierEngine` 注入生产扫描/研究管道，并接入持久化账本；否则标注为"研究预留组件"而非生产防线。

### HIGH

**H1 — 生产沙盒从不供给真实 Class A 输入 → 恒 `TIER_UNRATED`**
- **位置**：`wyckoff_sandbox.py:89-98`、`canslim_sandbox.py:90-99`、`lppl_sandbox.py:81-91`（`SandboxSignalEvaluation` 均不设 `residual_ic_series/pbo_value/gate_inputs`）；`base_sandbox.py:76-80`（透传 None → `TIER_UNRATED`）。
- **证据**：实证脚本 `verify_sandbox_provision.py`：三沙盒 `residual_ic_series=NO pbo_value=NO gate_inputs=NO`；`evaluate_through_gates(df)` 全部 `final_tier=UNRATED`。
- **影响**：沙盒晋升路径结构上无法晋升任何策略。这本身是 Rule 4 一致的 fail-closed，但意味着沙盒作为"策略沙盒"名不副实 —— 需要调用方外部计算残差 IC + bootstrap PBO + B/C/D 指标，无生产代码执行。
- **修复**：为沙盒提供真实的 `residual_ic_series`（如基于 `ClassBEvaluator.wls_orthogonalize` 对行业/市值剥离后的 IC）与 `pbo_value`（bootstrap，Bailey 2015 块自助），或显式移除沙盒晋升接口并保留为"仿真预览"工具。

**H2 — Class A 的 BH-FDR 多重测试校正在门禁路径不累积（等于原始 p 检查）**
- **位置**：`alpha_tier_engine.py:437`（默认 `DegreesOfFreedomLedger()` 新建）、`base_sandbox.py:68`（每次调用新建引擎）；`degrees_of_freedom.py:428`（单试验族 `p_adj_bh_fdr=p_raw`）；`alpha_tier_engine.py:152`（门禁用 `p_adj_bh_fdr`）；`scan_service.py:131-136`（`LedgerStore` 仅接桥接路径）。
- **证据**：`verify_research_findings.py` A/B 节：默认引擎 `total_trials=0`（未持久化）；单试验族 `p_adj_bh_fdr == p_raw`（True）。
- **影响**：Class A 的 `max_p_adj_bh=0.05` 门在默认路径退化为原始 p 检查，**多重测试惩罚被绕过**。`bridge.py:7-9` 自称"strongest anti-overfitting defence"，但该防线在四阶门禁路径未生效（仅桥接登记路径生效）。
- **修复**：`evaluate_through_gates`/`evaluate_candidate` 接受持久化账本（`LedgerStore.load()` 注入 `AlphaTierEngine(ledger=...)`），使族内试验数跨运行累积；或至少在单次扫描内复用同一引擎实例。

### MEDIUM

**M1 — Class C 换手 fail-open（Rule 4 细粒度违反）：缺 `turnover_series` → `daily_turnover=0.0` 通过 ≤0.15 门**
- **位置**：`alpha_tier_engine.py:527`（`float(np.mean(turnover_series)) if turnover_series else 0.0`）；门禁 `:315`（`daily_turnover <= 0.15`）。
- **证据**：`verify_research_findings.py` C 节：`turnover_series=None` → 派生 `daily_turnover=0.0`，且 `ClassCEvaluator.evaluate(..., daily_turnover=0.0, 其余全过)` → `passed=True`。缺输入被替换为对换手门**最有利**的常量（0 换手=无摩擦），fail-open 而非 fail-closed。
- **影响**：Class C 的换手摩擦约束在"未提供换手数据"时被静默移除（虽需其余 9 项全过才能整体通过，但换手门被架空）。
- **修复**：`turnover_series` 为空时置 `daily_turnover=inf`（fail-closed）或显式拒绝（`missing.append`），并记录拒绝原因。

**M2 — `cross_section_N=500` 硬编码伪造元数据（Rule 9 魔数）**
- **位置**：`alpha_tier_engine.py:118`（`cross_section_N=500`）。
- **证据**：每个 `TrialRecord` 恒记 `cross_section_N=500`，与实际截面无关；不参与门禁判定但作为"测量值"落盘。
- **影响**：数据保真度 —— 账本记录的截面规模是硬编码常量而非实测；Rule 9（无硬编码魔数）违反。
- **修复**：从真实截面推导（`len(cross_section)`）或改为可配置参数。

**M3 — 四门阈值硬编码、无来源依据（Rule 9 魔数 + 无出处）**
- **位置**：`alpha_tier_engine.py:135-143`（Class A）、`:231-239`（Class B）、`:297-308`（Class C）、`:402-408`（Class D）。
- **证据**：四组 `thresholds` 均为方法内字典字面量；`config/*.yaml` 无对应键（`grep min_abs_ic|0.025 ... config/` 无命中）；设计文档（`POST_SIMPLIFICATION...:307`、`N2N_MODULE_ANALYSIS_WORKFLOW:364,371`）仅列参数、无来源引证。`|t_NW|≥3.00`（比 1.96 严格）与 `PBO≤0.20`（Bailey 2015 标准）可辩护；`|IC|≥0.025`、`|ICIR|≥0.70` 无明确文献/设计出处。
- **影响**：承载统计政策的阈值无出处、不可配置（Class A 亦然，与既有报告"Class B/C/D 可配"的表述相反 —— 实为全部硬编码）。Rule 9 违反。
- **修复**：阈值提取为配置（`config/research_gates.yaml`）或类常量并给出处（引证论文/预注册文档），至少写入设计文档出处。

### LOW

**L1 — 未来数据检测与 AnalysisMode 未接入研究控制平面路径**
- **位置**：`check_lookahead_leakage`（`brain/factors/analyzer.py:26-85`，33%/50%/66% 三段未来扰动不变性测试，`:52`）；`AnalysisMode.LIVE` 负 shift 禁止（`analyzer.py:164-169, 284-289`）。沙盒 IC 构造（`wyckoff_sandbox.py:66`、`canslim_sandbox.py:78`、`lppl_sandbox.py:71`）不调用二者。
- **证据**：沙盒用 `np.roll(returns,-1)` 构造预测 IC（信号时刻 i 预测 i→i+1 收益，**无前瞻偏差**——已核实）；但从不运行 `check_lookahead_leakage`，从不按 `AnalysisMode` 门控。
- **影响**：防御纵深缺口（非活跃 bug）：研究控制平面不利用 brain 模块的前瞻防线。33%/50%/66% 三段式与 LIVE 负 shift 禁止本身**实现正确**（已核实）。
- **修复**：沙盒/门禁入口增加可选 `mode` 参数并接入 `AnalysisMode`，在 LIVE 下拒绝负 shift IC。

**L2 — 既有报告 §4.3 引用了分析范围外文件（报告准确性问题）**
- **位置**：既有报告 `docs/analysis/n2n/07_research_control_plane_n2n.md` §4.3 引用 `evt_risk.py:162-165`。
- **证据**：`evt_risk.py` 位于 `src/uniquant/risk/`（389 行），**不在**声明的 `src/uniquant/research/` 范围；该报告自称"所有引用精确到行号"但此条超出模块范围（CVaR 空尾部与四阶门禁无直接关系）。
- **影响**：仅报告引用精度/范围问题，不影响代码。
- **修复**：从研究控制平面报告移除该跨模块引用，或明确标注为"边界条件交叉参考"。

**L3 — `experiment_id` 时间戳同秒碰撞风险**
- **位置**：`alpha_tier_engine.py:111`（`f"exp_{factor_name}_{int(datetime.now().timestamp())}"`）。
- **影响**：同秒同因子多次试验 `experiment_id` 碰撞（非唯一键，`trial_index` 为实际唯一序，风险低）。
- **修复**：加单调计数或 UUID。

---

## ⑤ 交叉复核矩阵（对既有 Claude 报告 `07_research_control_plane_n2n.md`）

> 源码基线 434aab1→b1d2415 对 `src/` 为空 diff，故双方核对同一份代码。

| # | 既有结论 | 双方证据 | 独立裁定 |
|---|---|---|---|
| 1 | §0 文档文件名 `degrees_of_freedom_ledger.py` 实为 `degrees_of_freedom.py`（LOW） | 一致：`ledger/` 实际仅 `degrees_of_freedom.py`（445 行），无 `_ledger` 后缀文件 | **一致**（LOW，纯文档漂移） |
| 2 | §1/§2.1 四阶门禁参数 | 一致：Class A 阈值 `alpha_tier_engine.py:135-143` 逐项吻合 | **一致**（数值正确） |
| 3 | §2.1 "参数来源：行业标准/比1.96严格" | 既有报告给**解释**但**无引证**；`config/` 无键、设计文档无出处（`N2N_WORKFLOW:371` 本身视其为开放问题） | **分歧**：既有报告"来源可辩"高估 —— `|IC|≥0.025`、`|ICIR|≥0.70` 无文献/设计出处（M3） |
| 4 | §2.2 Newey-West t（Bartlett 核 + HAC + 自动滞后） | 一致：`alpha_tier_engine.py:61-86` 实现正确 | **一致** |
| 5 | §2.3 BH-FDR Step-Up + 逆序累积最小值 + BY | 一致：`degrees_of_freedom.py:409-425` 实现正确 | **一致**（实现正确；但"动态累积"效果受 H2 限制） |
| 6 | §2.4/§8.3 Rule 4 诚实门禁"完全符合" | 一致：缺 `residual_ic`/`pbo` → `TIER_UNRATED`+理由（`:478-491`），实证确认 | **一致**（对"输入为 None"情形合规） |
| 7 | §3.1 依赖链"清晰"：AlphaTierEngine→DegreesOfFreedomLedger | 既有报告未核查**账本是否持久化/复用**；实为每次沙盒调用新建内存账本（`base_sandbox.py:68`、`alpha_tier_engine.py:437`），门禁路径 `p_adj_bh=p_raw` | **分歧**：高估 —— 门禁路径多重测试不累积（H2，HIGH） |
| 8 | §3.2/§6.1 Class B 缺输入→TIER_A | 一致：`:578` 设 TIER_A、`:581-583` 早退 | **一致**（停在已达成最高阶，合理） |
| 9 | §4.3 CVaR 空尾部（`evt_risk.py:162-165`） | 既有报告引用了**范围外**文件（`src/uniquant/risk/`） | **分歧**：报告引用精度/范围问题（L2） |
| 10 | §7.4 L2 Class B/C/D 参数硬编码（LOW） | 一致：阈值硬编码；但既有报告称"不像 Class A 那样可配置" —— **实为全部硬编码**（含 Class A） | **分歧**：低估 —— 升为 MEDIUM（M3，且含 Class A，Rule 9） |
| 11 | §9.1 健康度"优秀" | 既有报告仅就引擎本体评审，未核查生产接线/沙盒真实输入供给/换手 fail-open | **分歧**：高估 —— 降为 **C+（条件就绪）**：统计核心正确但晋升管道未接线（C1）、沙盒恒 UNRATED（H1） |
| 12 | 独立评审人 M1（门禁信任上游，高估强度） | 一致：`evaluate_candidate` 仅拦 `None`，不校验上游传入的 `residual_ic_series` 真伪 | **一致**（M1 评审合理；且沙盒恒 `None` → 恒 UNRATED，见 H1） |
| 13 | 独立评审人 M2（账本持久化未评估，"MEDIUM 或 HIGH"） | 核实：`LedgerStore` 仅接 `scan_service.register_factor_trials`（桥接），未接门禁引擎 | **裁定：HIGH**（依评审人自设"持久化决定 MEDIUM/HIGH"，门禁路径未持久化且每次新建 → H2） |

**交叉复核汇总**：既有报告 10 条核心结论中，**5 条一致**（参数数值、Newey-West、BH-FDR 实现、诚实门禁 None 情形、Class B 缺输入→TIER_A），**5 条分歧**（参数来源高估、依赖链高估、范围外引用、硬编码低估、健康度高估），**新增 3 条未覆盖**（C1 无生产调用方、H1 沙盒恒 UNRATED、M1 换手 fail-open、M2 cross_section_N=500）。

---

## ⑥ 结论与建议

### 6.1 结论
1. **统计核心正确**：诚实门禁（Rule 4）、BH-FDR/Bonferroni/BY 三步校正、Newey-West HAC、WLS 正交化、Deflated Sharpe Ratio 全部核实正确；49 个定向测试全绿。**这部分值得肯定**。
2. **运营接线断裂（主要风险）**：四阶晋升引擎**无生产调用方**（C1，CRITICAL）；三沙盒**恒 `TIER_UNRATED`**（H1，HIGH）；门禁路径**多重测试不累积**（H2，HIGH）。三者叠加使"最强防过拟合防线"在真实生产流程中**基本未生效**。
3. **细粒度 Rule 4 缺口**：Class C 换手缺输入 fail-open（M1）；`cross_section_N=500` 伪造元数据（M2）。
4. **治理缺口**：四门阈值硬编码无出处（M3）；未来数据防线未接入研究路径（L1）。

### 6.2 修复优先级
| 优先级 | 项 | 动作 |
|---|---|---|
| **P0** | C1 | 建立真实生产调用方（接入扫描/研究管道），否则标注为"研究预留组件" |
| **P0** | H2 | 门禁引擎注入持久化账本（`LedgerStore.load()`→`AlphaTierEngine(ledger=...)`），或单次扫描复用单引擎 |
| **P1** | H1 | 沙盒供给真实 `residual_ic_series`/`pbo_value`，或移除晋升接口保留"仿真预览"语义 |
| **P1** | M1 | `turnover_series` 空 → fail-closed（`inf` 或显式拒绝） |
| **P2** | M2, M3 | 去魔数：`cross_section_N` 从真实截面推导；阈值提配置并给出处 |
| **P3** | L1, L2, L3 | 接入 `AnalysisMode`/`check_lookahead_leakage`；修既有报告范围外引用；`experiment_id` 加唯一序 |

### 6.3 建议
- 将本报告问题 C1/H1/H2 提交项目决策：四阶门禁要么**真正接入生产**（P0 接线），要么**明确降级为研究预留组件**并在文档标注，避免"防线存在但未启用"的虚假安全感。
- 修复后重跑 `tests/test_research_os_gates.py`、`tests/test_strategy_sandboxes.py`、`tests/test_research_ledger_bridge.py`（49 passed 基线）并补测：换手缺失 fail-closed、门禁账本持久化累积、沙盒真实残差 IC 供给。

---

**分析人**：独立复核子代理（SenseNova / OpenCode）
**审查时间**：2026-11-24
**代码基线**：`b1d2415`
**实证基础**：49 定向测试全绿 + 2 个实证脚本（`/tmp/opencode/verify_research_findings.py`、`/tmp/opencode/verify_sandbox_provision.py`）
**方法声明**：所有 `file:line` 均在本工作树源码核实；未引用任何未经实测的结论。
