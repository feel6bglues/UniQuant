# 简化后全栈架构与交易可落地性评估报告

> **文件**: `docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`
> **评估日期**: 2026-10-16
> **评估基线**: `master` @ `7509c2a`（工作区 clean，无未跟踪污染）
> **评估视角**: 量化金融架构（执行核 / 数据契约 / 科研认识论） × A 股交易员（成本 / 容量 / 制度约束）
> **评估方法**: 只读实测（当前工作树源码 + 真实数据湖 + 实跑测试/lint），**不采信历史文档声明**；所有结论附可复现命令
> **重要口径声明**: 本报告所有数字均在**当前工作树**实跑所得；凡标注"实测"处均可用 §附录 A 命令复现。

---

## 0. 执行摘要（Verdict）

**架构骨相已经很硬，但"简化"把系统推到了新的临界点。**

- 地基（执行不变核、数据湖、PIT 复权、科研记账概念）是**真资产**；
- 但最新、最关键的增值层 —— **"科学可信度控制平面（QTR-OS Research Plane）"** —— 目前处于 **"有壳无芯（伪造输入）」+「崩溃」+「未接线」+「CI 红」** 状态。

一句话结论：**系统已成功从"功能堆砌"瘦身为"可运行的研究/交易平台"，但防过拟合防线（项目唯一区别于普通"曲线拟合脚本"的东西）是实现完成度最差、风险最高的一环。**

### 问题严重度速览

| 级别 | 问题 | 影响 |
|---|---|---|
| 🔴 P0-1 | 研究门禁"捷径路径"伪造 B/C/D 输入，且 Class A 通过即崩溃 | 防过拟合门禁被架空（动量残差门 + PBO 门形同虚设） |
| 🔴 P0-2 | `ruff` CI 实测 31 错（红）；全量测试干净环境 4 fail | CI 管线实际不可信；"2530 passed" 为环境依赖假绿 |
| 🟠 P1-1 | 科研控制平面未接入任何生产因子链 | "最强防线"是孤岛，零真实覆盖 |
| 🟠 P1-2 | 文档严重漂移（README/docs/index/缺失 CLAUDE.md） | 违反项目自身"文档即阻断项"规则 |
| 🟡 P2-1 | 过户费口径过时（仅沪市 60 开头，漏 688/深市/北交所） | 成本低估（~0.1bp/边，量级小但口径失真） |
| 🟡 P2-2 | LPPL 仍占仲裁最高优先级且无质量门 | 唯一经证伪"零预测力"的引擎仍可触发虚警强平 SELL |
| 🟡 P2-3 | 覆盖率门缺失；数据湖/results 全 gitignore | 80% 覆盖率未被 CI 校验；实证结论仓库内不可复现 |

> **✅ 落地状态（2026-10-16）**：P0-1、P0-2、P2-1、P2-2、P2-3（ADV 地板部分）**已修复并验证**；P1-1、P1-2 与 CI 覆盖率门仍开放。详见 [§6 实施落地记录](#6-实施落地记录remediation-log--2026-10-16)。

---

## 1. 实测现状盘点

### 1.1 代码规模（实测）

| 分层 | 文件数 | LOC | 职责备注 |
|---|---:|---:|---|
| `shared` | 42 | 6,957 | 契约、常量、成本、时间抽象、秘钥 |
| `data` | 33 | 6,828 | 湖优先数据访问、复权、清洗、校验、TDX/mootdx 源 |
| `brain` | 62 | 19,968 | FSM/CZSC/LPPL/NTF/Regime/Wyckoff/因子 |
| `signal` | 8 | 2,802 | 适配器、仲裁、归一 |
| `hands` | 33 | 6,254 | 撮合 / 回测 / 执行切片 / CFFEX |
| `risk` | 8 | 2,259 | 仓位、回撤、EVT、组合优化、合规 |
| `services` | 29 | 9,026 | DI 容器、分析编排、扫描、清单生成 |
| `ui` | 8 | 3,400 | Streamlit 仪表盘 |
| **`research`** | **10** | **1,342** | **新增：QTR-OS 科研控制平面（门禁/账本/沙盒）** |
| **合计** | **234** | **58,837** | |

> ⚠️ `README.md` 仍声明"v0.3（44 文件 / ~12.6K LOC，完成度 28%）"——与实际相差 **19 倍文件数 / 4.7 倍 LOC**。

### 1.2 测试与脚本

- 测试文件：**192** 个；`pytest --collect-only` 收敛：**2,532 tests collected**。
- 脚本：**149** 个（研究/运维脚本占比很高，见 `scripts/{canslim,factor_mining,maintenance,qar,backtest}`）。

### 1.3 数据湖（本地，全部 gitignore）

| 数据集 | 数量 | 体积 |
|---|---:|---:|
| 日线 `quotes/daily` | 5,203（5,201 股票 + 000001.SH/000300.SH 基准） | 813M |
| 指数 `quotes/index` | 554 | 0 |
| 财务 `financial` | 5,211 | 2.4G |
| 分红 `dividend` | 5,123 | 21M |
| GBBQ `data/fq/gbbq.parquet` | 1 | 3.6M |

日线 schema（实测 `600519.SH`/`000001.SH`）：`date, open, high, low, close, amount, volume(int64), reserved, code`（9 列，无 `adj_factor`）。`000001.SH` 共 8,741 行。

### 1.4 运行冒烟

```
8-layer + research imports OK
config engine: duckdb
```

八层 + research 导入全通，config 可加载。

---

## 2. 真正的架构资产（应保留并保护）

1. **执行不变核（`hands/backtest`）** —— 方向正确且已落地：
   - 参与率平方根冲击模型：`unified_matching_engine.py:75-92`，`eta = qty / ADV`，小单 `impact→0` 收敛、`eta>0.10` 超线性惩罚、硬截断 5%（500bps）；`quantities` 缺省时回退到日成交活跃度分支（向后兼容）。
   - T+1（`:266-281`）、涨跌停（含 688/ST/北交所/IPO 分支，`:136-179`）、印花税按日期切换（`:290-294`）。
   - **跌停拒卖强制结转** `RETRYING`（`unified_engine.py:431-438`，上限 30 日）与**"结转中禁覆写买单"**（`:476-483`）——对应蓝图 INV-6，已实现。
2. **数据平面**：
   - `CorporateActionAdjuster` **只调价格列、不动 volume**（`corporate_action.py:176-181`）——避免了"现金分红误稀释成交量"这一行业通病。
   - **禁止静默单位矩阵**：gbbq 缺失/清洗后为空/因子非正 → 硬失败并带 resync 指引（`:67-72`、`:123-130`）——正确。
3. **科研记账概念（`research/ledger`）** —— 全项目**最有价值的设计**：`DegreesOfFreedomLedger` 实现 Bonferroni / BH-FDR / BY-FDR / Nyholt-Li-Ji `M_eff` / Alpha-Wealth 熔断（`degrees_of_freedom.py`）。这是"防止把样本内撞大运当alpha"的正解，方向正确。
4. **四级晋升门的严格路径**：`AlphaTierEngine.promote_candidate()`（含 DSR、动量残差、行业+对数市值 WLS 中性化）由 `tests/test_research_os_gates.py` 12 个单测覆盖，要求调用方提供真实 `data_a..data_d`，数学实现基本正确。

---

## 3. 问题清单（逐条含证据）

### 🔴 P0-1　研究门禁的"捷径路径"伪造 B/C/D 输入，且 Class A 通过即崩溃

**位置**: `src/uniquant/research/gates/alpha_tier_engine.py:433-500`（`evaluate_candidate`），
被所有沙盒调用：`src/uniquant/research/sandboxes/base_sandbox.py:55`。

**问题 A —— 伪造输入**：捷径路径把 Class B/C/D 的输入写成常量：

```python
data_a = {"residual_ic_series": ic_arr, "pbo_value": 0.15, ...}     # :451-453
data_b = {"pure_ic_series": ic_arr, "r2_series": np.full(len, 0.05),
          "size_corr_series": np.zeros(...), "top_industry_weights": [0.08,0.07,0.05]}  # :456-461
data_c = {"net_mdd": -0.10, "portfolio_median_adv": 5e7, "calculated_capacity": 5e8, ...}  # :470-479
data_d = {"cleanroom_rank_corr": 0.9995, "quarantine_oos_sharpe": ann_sharpe*0.9, ...}     # :481-488
```

- `residual_ic_series = ic_arr` → **动量残差门"用原始 IC 自己比自己"，恒过**；
- `pbo_value = 0.15` 硬编码 → **PBO 门恒过**。

> 这正是全项目 P2–P14 反复证明的"A 股预测力高度集中于动量"的两道核心防线。捷径等于**把刹车拔掉**。

**问题 B —— 崩溃**：`data_b["top_industry_weights"]` 是 Python `list`，而
`ClassBEvaluator.evaluate` 执行 `hhi_ind = np.sum(top_industry_weights ** 2)`（`:213`）→
**Class A 一旦通过就 `TypeError` 崩溃**：

```
TypeError: unsupported operand type(s) for ** or pow(): 'list' and 'int'
```

**实测证据**（模式无关的强 IC 序列，`residual_ic` 与 `pbo` 走捷径）：

```text
$ .venv/bin/python -c "... eng.evaluate_candidate('synthetic_strong', ic, rets, ...)"
# 崩溃于 alpha_tier_engine.py:213
# 若把 top_industry_weights 改成 np.array，则：
tier: AlphaTier.TIER_D | rejected: None
  Class A: passed=True
  Class B: passed=True
  Class C: passed=True
  Class D: passed=True
```

**为何测试没抓到**：`tests/test_strategy_sandboxes.py` 只断言
`isinstance(report.final_tier, AlphaTier)`（任意 tier 均通过），且其合成数据永远过不了 Class A，
因此**捷径路径的 Class A-pass 分支从未被任何测试覆盖**。

**后果**：A 股最关键的动量残差门 + PBO 门在这条路径上被架空；任何"Class A 侥幸通过"的因子会被一路放行到 Tier D。

---

### 🔴 P0-2　CI lint 实测 31 错（红）；全量测试干净环境 4 fail

**(a) Lint**：`ruff 0.15.14`（与 `pyproject.toml` pin `>=0.15.0,<0.16.0` 一致）执行 CI 命令
`ruff check src/uniquant/ tests/ scripts/` → **Found 31 errors**：

| 规则 | 数量 | 主要文件 |
|---|---:|---|
| F401 unused-import | 26 | `research/sandboxes/{lppl,wyckoff,canslim,base}_sandbox.py`、`services/manifest_generator.py`、`scripts/qar/run_generate_trading_manifest.py`、`tests/test_uniquant_production_architecture_gates.py`(8) 等 |
| E402 module-import-not-at-top | 3 | 脚本 sys.path 引导相关 |
| F541 f-string-no-placeholders | 1 | — |
| F841 unused-variable | 1 | — |

> `.github/workflows/test.yml` 的 **Lint with ruff** 步骤因此**会失败**。这与 `AGENTS.md`"0 ruff（src+tests+scripts）"的声明矛盾。

**(b) 测试**：`.venv/bin/python -m pytest tests/` 实测结果：

```
2526 passed, 2 skipped, 4 failed
```

4 个失败全部来自 `tests/test_data_fetcher_init_fault_tolerance.py`，
根因是 `_write_min_all_stock_codes()`（`:22-30`）向写死的 `/tmp/test_*` 路径写 CSV 却**不创建父目录**：

```
OSError: Cannot save file into a non-existent directory: '/tmp/test_df_lake_first'
```

**环境依赖实证**：在该机器上因历史残留目录而"绿"（提交信息"2530 passed, 0 failed"），
在干净环境**必红**。手工 `mkdir -p` 后该文件 5/5 通过。

> 结论：当前 CI 的"绿"是**假绿**，不可作为回归可信证据。

---

### 🟠 P1-1　科研控制平面未接入生产

全仓检索 `uniquant.research` 的**生产**引用（排除 `src/uniquant/research/` 自身）：

```text
scripts/factor_mining/five_gate.py:33   from uniquant.research.gates.alpha_tier_engine import ClassAEvaluator
tests/test_research_os_gates.py:9,14
tests/test_strategy_sandboxes.py:11,12
```

即：**因子生产链（`scan_service` / `factor composer` / `walk_forward_pipeline`）没有任何一处向 `DegreesOfFreedomLedger` 登记试验**。
"防过拟合最强防线"目前是**孤岛**，未覆盖任何真实因子产出。累计试验数 `total_trials` 在真实研究流程中恒为 0。

> **✅ 2026-10-16 已接入**：`scan_service.ScanPipeline` 现将每次因子分析的全部 `(因子, 持有期)` 试验登记入账本（真实 IC/t → 双侧 student-t p → Bonferroni / BH-FDR / BY-FDR / Alpha-Wealth），`walk_forward_pipeline` 增可选钩子（登记跨窗 t 中位数）。**诚实边界**：analyzer 的 `t` 是**朴素 t（无自相关修正）**，故以 `STUDENT_T` + `autocorr_adjusted=False` 登记，**不冒充** `IC_NEWEY_WEST_T`；`factor_correlation_matrix=None` → `M_eff = m`，不做乐观折扣。见 §6 P1-1。

---

### 🟠 P1-2　文档严重漂移（违反项目自身"文档即阻断项"规则）

- 项目指令要求"先读根目录 `CLAUDE.md`（10 条编码规则）"——**该文件在仓库中不存在**（`find . -name CLAUDE.md` 无结果）。
- `README.md`：声明"v0.3 / 44 文件 / 12.6K LOC / 完成度 28%"，并列出**已在上次大清理中删除**的数据源（Sina/Tencent/THS/Eastmoney/BaoStock）。
- `docs/index.md`：更新时间停留在 **2026-07-10**，仍引用"256 文件 / 62,549 LOC"口径。

> **✅ 2026-10-16 已修复（P1-2）**：**根因定位**——`CLAUDE.md` 并非"从未创建"，而是被根 `.gitignore` 的 `/*.md` 静默忽略（根级 markdown 全部排除），故始终无法提交；已补 `!/CLAUDE.md` 并新建**逐条标注出处**的规则文件（不虚构"原始 10 条"）。`README.md` 整体重写、`docs/index.md` 按实测口径更新。见 §6 P1-2。

---

### 🟡 P2-1　成本模型过户费口径过时

`shared/cost_model.py:48-52` 与 `unified_matching_engine.py:206/295`：

```python
def _has_transfer_fee(symbol: str) -> bool:
    """沪市(60xxxx)收过户费，深市免收。"""
    return symbol.startswith("60")
```

问题：
1. **漏 688（科创板，沪市）** —— 被最新 benchmark 特意纳入撮合的 688 股反而不收过户费；
2. 自 **2022-04-29** 起中国结算已对**沪深北 A 股统一按 0.01‰ 双向**收取，原"深市免收"说明已过时。

量级：~0.1bp/边，对高换手策略年化影响极小，但属**可核验的口径失真**，建议修正注释与掩码。

---

### 🟡 P2-2　LPPL 仍占据仲裁最高优先级，且无质量门

- `signal/arbitrator.py:29`：`"lppl": 0`（最高优先级，数值越小越优先）。
- `signal/adapters.py:491`：`create_default_registry()` 注册 `LPPLAdapter()`
  —— **`diagnostic_only=False` 且 `min_r2=None / min_oos_r2=None`**，即**无任何 R² 质量门**；
- 因此 `risk == "Danger"` 时产出 **SELL**（`adapters.py:109-121`），而仲裁规则 1"SELL 优先于 BUY"（`:198-212`）会使其压过所有 BUY。

> QTR-OS 蓝图明确要求"从 `arbitrator.py` 优先级与 `fsm.py` FORCE_EXIT 否决链中**彻底切除** LPPL，封装为只读遥测特征"。而 walk-forward 终结评估早已判定 LPPL **零预测力**。当前代码状态与蓝图/实证**均相悖**，属可触发虚警强平的活链路。

---

### 🟡 P2-3　工程门禁缺失

- `pyproject.toml` `addopts = "-q"`，CI `pytest tests/ -q --tb=short` **不带 `--cov`** → 编码规范里的"80% 覆盖率"**未被任何 CI 校验**。
- `.gitignore` 忽略 `data/lake/` 与 `results/` → **所有实证结论（P 系列、H-A 对账、对账存证）在仓库内不可复现**，证据链只存在于本机。

> **✅ 2026-10-16 已修复**：CI 新增独立 `coverage` 作业（`--cov-fail-under=68`，实测覆盖率 **70.55%**，定位为**回归地板**而非达成 80% 目标）；`results/` 由"整目录忽略"改为"白名单 + SHA-256 内容哈希账本"，50 个结构化证据文件（≈920 KB）纳入版本库并由 CI 每 push 校验 `verify`。见 §6 P2-3（剩余）。

---

## 4. 交易员视角：能拿什么去实盘？

按项目自身**最严谨的研究链**（P2→P15 反复证伪闭环），**唯一通过完整验证的 alpha 是 H-A（条件 illiquidity × 过热牛态）**：

| 口径 | 表现 | 来源 |
|---|---|---|
| 组合层（500 样本，生产撮合） | 净年化 **+7.43%** / 夏普 **0.68** / 回撤 −14.99% | `results/factor_mining/ha_rotation_sim.json` |
| 全市场（无地板） | −2.46% / −0.04 / −51.2% | 极端微盘摩擦吞噬 |
| 全市场 + ADV≥2000 万地板 | **+6.84%** / 0.59 / −15.3% | 恢复正收益 |
| **容量** | **≈ 2850 万元**（10% 参与率折算） | P10/D+10 |

**关键落地风险**：`scripts/canslim/daily_signal_ha.py:25` 主线 `AMOUNT_FLOOR = None`（**无流动性地板**），
而研究结论却是"**必须有 ADV 地板才能盈利**"。即**生产运行器默认跑的是会被微盘摩擦吞噬的变体**——应尽快对齐。

> **✅ 2026-10-16 已对齐**：`AMOUNT_FLOOR` 已置 `20_000_000.0`，无地板口径降为研究对照（见 §6）。

**结论**：平台的研究"诚实度"很高（持续证伪、不自我欺骗），但**可交易产出是一个受限容量（~2850 万）策略**。
作为系统，它更像"高保真研究/风控台 + 一个可跑的小容量策略"，而非可承载大资金的实盘引擎。

---

## 5. 建议优先级（Roadmap）

| 优先级 | 行动 | 涉及文件 | 工作量 |
|---|---|---|---|
| **P0** | 修 `evaluate_candidate`：删除捷径常量，或改为要求真实 B/C/D 输入；修 `list**2`；为沙盒加"Class A 必须能通过 + 全门断言" | `research/gates/alpha_tier_engine.py`、`research/sandboxes/*`、`tests/test_strategy_sandboxes.py` | 小 |
| **P0** | 测试建目录（`parents=True, exist_ok=True`）+ `ruff --fix` 26 项 F401 → **恢复 CI 绿** | `tests/test_data_fetcher_init_fault_tolerance.py`、各 lint 文件 | 小 |
| **P1** | 把 `DegreesOfFreedomLedger.register_*` 接入 `walk_forward_pipeline` / `composer` 因子链，形成真实审计闭环 | `brain/factors/*`、`services/scan_service.py` | 中 |
| **P1** | 更正 `README.md` / `docs/index.md`；补回或删除 `CLAUDE.md` 引用 | 文档 | 小 |
| **P2** | 过户费口径统一（沪深北 + 688）；LPPL 默认 `diagnostic_only=True` 并从仲裁 SELL 链移除 | `shared/cost_model.py`、`hands/backtest/unified_matching_engine.py`、`signal/arbitrator.py`、`signal/adapters.py` | 小 |
| **P2** | `daily_signal_ha` 主版本对齐 ADV 地板；CI 增加覆盖率门 | `scripts/canslim/daily_signal_ha.py`、`.github/workflows/test.yml` | 小 |

---

## 6. 实施落地记录（Remediation Log · 2026-10-16）

按 §5 优先级分两轮落地，全部在本工作树完成并逐条以实测命令验证：

- **第一轮（2026-10-16 上午）：P0-1 / P0-2 / P2-1 / P2-2 / P2-3（H-A 地板）** —— 见下表前五行。
- **第二轮（2026-10-16 下午）：P1-1 / P1-2 + P2-3 剩余（CI 覆盖率门 + 证据链可复现）** —— 见下表后三行。

| 项 | 实施 | 关键文件 | 验证 |
|---|---|---|---|
| **P0-1** 四阶门禁诚实化 | `evaluate_candidate` 不再伪造：缺 `residual_ic_series` / `pbo_value` → `TIER_UNRATED` + 明确拒绝原因（**禁止**原始 IC 自比 / 硬编码 PBO 捷径）；Class B/C/D 真实指标必须由 `gate_inputs={"b","c","d"}` 提供，缺即在当级早退。`ClassBEvaluator` 对 `top_industry_weights` 做 `np.asarray(...,float64)` 防御（消灭 `list ** 2` 崩溃）。`promote_candidate` 四参数可选 + 逐级早退。`sandboxes/base_sandbox.py`：`SandboxSignalEvaluation` 增 `residual_ic_series`/`pbo_value`/`gate_inputs` 并透传真实输入 | `research/gates/alpha_tier_engine.py`、`research/sandboxes/base_sandbox.py`、`research/sandboxes/lppl_sandbox.py` | 附录 A #4 由 **TypeError 崩溃 → `TIER_UNRATED`**（诚实拒绝，见下方逐字输出）；新增 `TestAlphaTierHonestGate`（真实四门全通过 → `TIER_D`）+ 修 3 处弱断言。`tests/test_strategy_sandboxes.py tests/test_research_os_gates.py` **20 passed** |
| **P0-2** CI 绿 + 测试隔离 | `ruff check --fix`（自动修 27）+ 人工修 3（F841 `lppl_sandbox.py`、E402 `# noqa` ×2）→ lint 归零；`tests/test_data_fetcher_init_fault_tolerance.py::_write_min_all_stock_codes` 增 `root.mkdir(parents=True, exist_ok=True)`，消除对开发机残留 `/tmp` 目录的依赖 | `tests/test_data_fetcher_init_fault_tolerance.py` 等 | `ruff check src/uniquant/ tests/ scripts/` → **All checks passed!**；干净 `/tmp` 下该文件 **5 passed**（原干净环境 4 fail → 0） |
| **P2-1** 过户费全市场统一 | `_has_transfer_fee` 重写为全市场口径：SH `60/68`、SZ `000/001/002/003/300/301/302`、BJ `43/83/87/88/920`，依 2022-04-29 中国结算 **沪深北 A 股统一 0.01‰ 双向**；新增向量化 `has_transfer_fee_mask`（语义与标量版严格一致）；指数/ETF/可转债豁免。撮合引擎三处 `sh_mask` → `fee_mask`。**按项目"交易规则变更须显式复核"要求**，冻结执行基线 `tests/benchmark/baseline_execution_v0.parquet` 以 `scripts/capture_baseline.py --execution` 重生成 | `shared/cost_model.py`、`hands/backtest/unified_matching_engine.py`、`tests/benchmark/baseline_execution_v0.parquet` | `tests/test_cost_model.py test_matching_engine.py test_unified_matching.py` **60 passed** + `tests/benchmark/` **2 passed**；手工矩阵 17 例全对；基线重生成的 diff 证明**仅含预期变动**：成交笔数 95 恒定、沪市（600519/601318/600080）零变化、**深市+科创板由 0 → 实收**（000001.SZ +0.62、000858.SZ +14.34、300750.SZ +16.34、688981.SH +2.85 元），收益漂移 ≤3.3e-5 |
| **P2-2** LPPL 降为遥测 | `LPPLAdapter` 默认 `diagnostic_only=True`（危险态仅写入 metadata，**不产 SELL**）；`create_default_registry` 显式遥测注册；`arbitrator.py` `ENGINE_PRIORITY["lppl"] 0 → 99`（与未知引擎同级=最低），模块文档串同步——LPPL 不再优先于决策引擎、亦不具强制平仓能力 | `signal/adapters.py`、`signal/arbitrator.py` | `tests/signal/ tests/test_signal_arbitrator.py tests/test_lookahead_bias.py tests/test_unified_matching.py` **166 passed**；新增"默认遥测"与"优先级降级"断言 |
| **P2-3** H-A 运行器对齐 ADV 地板 | `daily_signal_ha.py` `AMOUNT_FLOOR: None → 20_000_000.0`；文档串澄明"无地板仅研究对照、非可交易形态" | `scripts/canslim/daily_signal_ha.py` | 新增 `TestLiquidityFloor`；`tests/scripts/test_ha_engineering.py` **17 passed** |
| **P1-1** 科研控制平面接入生产因子链 | `ScanPipeline` 新增 `ledger_enabled=True` / `ledger_path=None` / `ledger_family_id="factor_scan"`；`analyze_factors` 把每 `(因子, 持有期)` 的真实 IC/t 登记进 `DegreesOfFreedomLedger`，结果进 `report["research_ledger"]` 并由 `generate_report` 渲染；`_register_factor_trials` 幂等（实例缓存）。新增 `research/ledger/bridge.py`（`ic_t_stat_to_p_value` 双侧 student-t · `register_factor_trials` · `LedgerAudit`）与 `research/ledger/ledger_store.py`（mkstemp + `os.replace` 原子 JSON；损坏/缺失→空账本）。`degrees_of_freedom.py` 增 `to_state/from_state`（**直接还原 Alpha-Wealth，按原始 p 重算族系校正，不二次计息**）。`walk_forward_pipeline.py` 增可选 `ledger` 钩子（默认 `None`，研究工具行为不变），登记**跨窗 t 中位数**以避开单窗尖峰 | `services/scan_service.py`、`research/ledger/bridge.py`、`research/ledger/ledger_store.py`、`research/ledger/degrees_of_freedom.py`、`brain/factors/walk_forward_pipeline.py` | 新增 `tests/test_research_ledger_bridge.py` **22 用例**；与 `tests/test_walk_forward_pipeline.py` 合并 **42 passed**；相邻套件（`test_research_os_gates` / `test_strategy_sandboxes` / `test_scan_service` / factor 系）全绿；`ruff` 0 |
| **P1-2** 文档漂移修复 | 新建根 `CLAUDE.md`（10 条规则，**逐条标注出处**；文件从未提交的**根因**已定位并修复：`.gitignore` 的 `/*.md` 静默忽略根级 markdown → 增 `!/CLAUDE.md`）。`AGENTS.md` 首行注记该文件从未提交、现为"有出处的诚实合并版"。`docs/index.md` 头部实测口径 + 真源表（历史 live map 降级为历史）+ 删除悬空链接 + 增 `research` 行 + 新增「Evidence & Reproducibility」节。`README.md` 整体重写（删 v0.3 / 28% / 12.6K LOC 与**已删除**的数据源；真实分层表；当前主线状态）。AGENTS 分层表/高风险表/控制文档表漂移一并修正 | `CLAUDE.md`、`AGENTS.md`、`docs/index.md`、`README.md`、`.gitignore` | 逐项对照实测：分层计数 `data 67→33`、`brain 54→62`、`shared 44→42`、`risk 6→8`、`services 31→29`、新增 `research 12`；`sources/tdx.py` 行 → `mootdx_local.py`；`factor_governance` / `price_collar` / `portfolio_engine` / `analysis_service_legacy` 引用全部指向**已物理删除**的文件 → 改为现存真源。`git check-ignore` 前后验证 `CLAUDE.md` 由 ignore → tracked |
| **P2-3（剩余）** CI 覆盖率门 + 证据链可复现 | ① `.coveragerc` 明确 `source=src/uniquant`、omit `ui/*`、排除 `pragma: no cover`/`TYPE_CHECKING` 等；CI 新增 **`coverage` 作业**（`pytest --cov -n auto --timeout=900 --cov-fail-under=68`，与快速 `test` 作业**并行**，不拖慢反馈）。② `results/.gitignore` 白名单 + 根 `.gitignore` `results/`→`results/*`（**目录级排除无法再白名单，必须改为通配**）：把实证结论的结构化证据（P 系列因子研究、H-A 对账、迁移/QFQ 存证、门禁裁决，50 文件 ≈ 920 KB）真正纳入版本库；③ 新增 `scripts/maintenance/evidence_manifest.py`（`build`/`verify`，SHA-256+size 内容哈希账本，CI 每 push 校验）；④ `results/migration/lake_baseline.json` 即数据湖基线存证（本身也在哈希账本内） | `.coveragerc`、`.github/workflows/test.yml`、`results/.gitignore`、`.gitignore`、`results/EVIDENCE_MANIFEST.json`、`scripts/maintenance/evidence_manifest.py` | `evidence_manifest.py verify` → **no drift**（50 文件 / 942,274 B）；新增 `tests/scripts/test_evidence_manifest.py` **23 passed**（含"等长内容改写仍被摘要捕获"反例、缺文件/新增文件/`--allow-missing`/CLI 退出码、真实仓库账本与树一致）；`--cov-fail-under` 门限经反向验证（阈值 68 下小样本必红、阈值 1 下必绿）。**诚实披露：实测全包覆盖率 = 70.55%（26,412 statements / 7,779 missed）**——与 `AGENTS.md` 历史声称的 57.88% 及历史审计的 21.91% 均不符（后者系 `--cov` 未跑完的残缺值），门限 68% 定位为**回归地板**而非达成 80% 目标 |

**P0-1 修复前后（附录 A #4 命令逐字）**：

```text
修复前：TypeError: unsupported operand type(s) for ** or pow(): 'list' and 'int'   # alpha_tier_engine.py:213
修复后：tier = AlphaTier.TIER_UNRATED
        reason = Class A 捷径已禁用：必须提供 residual_ic_series（真实动量残差 IC 序列）、
                 pbo_value（真实 Bootstrap PBO 值）...
```

**全量门禁（本工作树实测）**：

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest tests/ -o addopts="" -p no:cacheprovider -q` | **2596 passed / 2 skipped / 0 failed**（收集 2598） |
| `.venv/bin/python -m pytest tests/ -o addopts="" -p no:cacheprovider -n 8 --timeout=900 --cov` | **2596 passed / 2 skipped / 0 failed**，**3 分 37 秒**，覆盖率 **70.55%** |
| `ruff check src/uniquant/ tests/ scripts/` | **All checks passed!** |
| `python scripts/maintenance/evidence_manifest.py verify` | **no drift**（50 文件 / 942,274 B） |

> **`-n 8` 与单进程结果逐位一致**（2596+2 = 2598 = 单进程 2575 + 本轮新增 23 项证据链用例；亦等于 `--collect-only` 计数），故 CI 覆盖率作业可安全启用 `-n auto` 提速。

**分层覆盖率（2026-10-16 实测，`cov.json` 口径）**：

| 层 | statements | missed | 覆盖率 |
|---|---:|---:|---:|
| `research/` | 704 | 40 | **94.3%** |
| `signal/` | 1,096 | 98 | 91.1% |
| `shared/` | 3,266 | 425 | 87.0% |
| `risk/` | 994 | 267 | 73.1% |
| `brain/` | 9,465 | 2,656 | 71.9% |
| `hands/` | 2,817 | 1,009 | 64.2% |
| `services/` | 4,393 | 1,590 | 63.8% |
| `data/` | 3,676 | 1,694 | **53.9%** |
| **合计（omit `ui/`）** | **26,412** | **7,779** | **70.55%** |

> **口径更正**：`AGENTS.md` 顶部曾记 "coverage 57.88%"（2026-08-05），历史审计（2026-09-14）又记 "21.91%" 并称 `--cov` 会挂起——**两者均不成立**：全包 `--cov` 可正常跑完（3 分 37 秒 / `-n 8`），真实覆盖率为 **70.55%**；历史 21.91% 系 `--cov` 未跑完的残缺值。**`data/` 层 53.9% 为当前最薄弱面**，是下一步补测的优先目标。

> 落实口径更正：报告 §3 中"全量测试干净环境 4 fail"已修复；提交 `7509c2a` 宣称的 "2530 passed" 属**环境依赖假绿**（依赖开发机 `/tmp` 残留目录），修复后干净环境亦全绿。

**§5 Roadmap 关单状态（第二轮后）**：

| 项 | 状态 | 证据 |
|---|---|---|
| P0-1 四阶门禁诚实化 | ✅ 关单 | 附录 A #4：TypeError → 诚实 `TIER_UNRATED` |
| P0-2 CI 归零 + 测试隔离 | ✅ 关单 | `ruff` 0；干净 `/tmp` 下该文件 5/5 |
| P1-1 科研控制平面接入生产 | ✅ 关单 | `scan_service`/`walk_forward_pipeline` 登记真实试验；`tests/test_research_ledger_bridge.py` 22 用例 |
| P1-2 文档漂移 | ✅ 关单 | `CLAUDE.md` 新建；`README.md`/`docs/index.md`/`AGENTS.md` 按实测重写 |
| P2-1 过户费全市场统一 | ✅ 关单 | 基线重生成 diff 仅含预期变动 |
| P2-2 LPPL 降为遥测 | ✅ 关单 | 默认 `diagnostic_only=True` + 优先级 99 |
| P2-3 H-A 对齐 ADV 地板 | ✅ 关单 | `AMOUNT_FLOOR = 20_000_000.0` |
| P2-3 剩余：CI 覆盖率门 | ✅ 关单 | 独立 `coverage` 作业 + `--cov-fail-under=68`（实测 70.55%） |
| P2-3 剩余：数据湖/results 可复现 | ✅ 关单 | 证据白名单 + 内容哈希账本 + CI 校验 |

> **仍开放（不属本报告 §5 范围，供后续决策）**：① `data/` 层覆盖率 53.9%、45 处历史零覆盖文件；② 历史文档（`docs/archive/`、`docs/reanalysis/`）仍含大量已失效口径，未做全量清理；③ 策略容量受限于 ≈2850 万元（H-A 的固有属性，非工程缺陷）。

---

## 附录 A：可复现命令

```bash
# 0) 基线
git rev-parse HEAD && git status --short

# 1) 规模
find src/uniquant -name '*.py' | wc -l
find src/uniquant -name '*.py' -exec cat {} + | wc -l

# 2) 测试收集与全量
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1
.venv/bin/python -m pytest tests/ -q -p no:cacheprovider | tail -5

# 3) CI lint（2026-10-16 修复后：All checks passed）
ruff check src/uniquant/ tests/ scripts/

# 4) P0-1 门禁复现（修复后：诚实 TIER_UNRATED，而非 TypeError 崩溃）
.venv/bin/python - <<'PY'
import numpy as np
from uniquant.research.gates.alpha_tier_engine import AlphaTierEngine
ic = np.full(200, 0.05) + np.random.normal(0, 0.01, 200)
eng = AlphaTierEngine()
print(eng.evaluate_candidate('x', ic.tolist(), [0.001]*200, [0.02]*200))
# → TierVerdict(tier=TIER_UNRATED, ...) 诚实拒绝：缺 residual_ic_series / pbo_value / gate_inputs
PY
.venv/bin/python -m pytest tests/test_strategy_sandboxes.py tests/test_research_os_gates.py -q -p no:cacheprovider

# 5) 测试隔离根因
grep -n "test_df_lake_first\|_write_min_all_stock_codes" tests/test_data_fetcher_init_fault_tolerance.py

# 6) 科研平面接线面（第一轮前：仅 3 处；第一轮后：含生产扫描链）
grep -rn "uniquant.research" --include='*.py' src scripts tests | grep -v "^src/uniquant/research/"

# 7) P1-1 科研控制平面生产接线（第二轮）
grep -rn "register_factor_trials\|research_ledger\|ledger_enabled" --include='*.py' src/uniquant | grep -v ledger/bridge
.venv/bin/python -m pytest tests/test_research_ledger_bridge.py tests/test_walk_forward_pipeline.py -o addopts="" -q -p no:cacheprovider

# 8) P2-3 证据链可复现（第二轮）
.venv/bin/python scripts/maintenance/evidence_manifest.py verify      # → "no drift"
.venv/bin/python scripts/maintenance/capture_lake_baseline.py         # 重新捕获数据湖基线
.venv/bin/python -m pytest tests/scripts/test_evidence_manifest.py -o addopts="" -q -p no:cacheprovider

# 9) P2-3 CI 覆盖率门（第二轮；实测覆盖率 70.55%，门限 68%）
.venv/bin/python -m pytest tests/ -o addopts="" -p no:cacheprovider \
    -n 8 --timeout=900 --cov --cov-report=term:skip-covered --cov-fail-under=68
# 反向验证门限确实生效（小样本 + 高阈值 → 必红）
.venv/bin/python -m pytest tests/scripts/test_evidence_manifest.py --cov --cov-report= --cov-fail-under=68; echo $?   # → 1
```

---

## 附录 B：与历史文档的冲突声明

| 声明来源 | 声明 | 实测 |
|---|---|---|
| `AGENTS.md` | ruff 0（src+tests+scripts） | **31 错** |
| 提交 `7509c2a` | pytest 2530 passed, 0 failed | 干净环境 **4 failed** |
| `AGENTS.md`（顶部指令） | 先读根目录 `CLAUDE.md`（10 条规则） | **文件不存在** |
| `README.md` | v0.3 / 44 文件 / 12.6K LOC | 实际 **234 文件 / 58.8K LOC** |
| `QTR_OS_REFACTORING_BLUEPRINT` | LPPL 从仲裁优先级/FORCE_EXIT 切除 | `arbitrator.py:29` 仍 `lppl:0` |
| `QTR_OS_REFACTORING_BLUEPRINT` | 四级门禁"完成落地并验证通过" | 捷径路径伪造输入且崩溃 |

> **更新（2026-10-16）**：上表第 1、2、5、6 行涉及的偏差**已在第一轮修复**——`ruff` 归零、干净环境全量测试 0 fail、`ENGINE_PRIORITY["lppl"]` 降为 99、四级门禁改为诚实拒绝伪造输入。第 3、4 行（缺失 `CLAUDE.md`、`README.md` 漂移）**已在第二轮 P1-2 修复**——根因是根 `.gitignore` 的 `/*.md` 静默忽略根级 markdown（故该文件"曾经写过却从未提交"），现已补 `!/CLAUDE.md` 并新建**逐条标注出处**的规则文件；`README.md` 已整体重写、`docs/index.md` 已更新口径。详见 §6。

---

*报告结束。所有结论均可由附录 A 命令在当前工作树复现。*
