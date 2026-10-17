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
| `shared` | 42 | 6,994 | 契约、常量、成本、时间抽象、秘钥 |
| `data` | 32 | 6,496 | 湖优先数据访问、复权、清洗、校验、TDX/mootdx 源 |
| `brain` | 62 | 20,046 | FSM/CZSC/LPPL/NTF/Regime/Wyckoff/因子 |
| `signal` | 8 | 2,813 | 适配器、仲裁、归一 |
| `hands` | 33 | 6,254 | 撮合 / 回测 / 执行切片 / CFFEX |
| `risk` | 8 | 2,259 | 仓位、回撤、EVT、组合优化、合规 |
| `services` | 29 | 9,122 | DI 容器、分析编排、扫描、清单生成 |
| `ui` | 8 | 3,400 | Streamlit 仪表盘 |
| **`research`** | **12** | **1,877** | **新增：QTR-OS 科研控制平面（门禁/账本/沙盒 + 自由度账本桥）** |
| **合计** | **235** | **59,261** | （含 `src/uniquant/__init__.py`） |

> 上表为 **2026-10-16 第三轮结束时的实测**；首次盘点时为 `data 33 / research 10 / 合计 234`——差异来自第三轮删除 `data/managers/cache_manager.py` 与第二轮新增 `research/ledger/{bridge,ledger_store}.py`。

> ⚠️ `README.md` 仍声明"v0.3（44 文件 / ~12.6K LOC，完成度 28%）"——与实际相差 **19 倍文件数 / 4.7 倍 LOC**。

### 1.2 测试与脚本

- 测试文件：**205** 个；`pytest --collect-only` 收敛：**3,198 tests collected**（首次盘点时为 192 文件 / 2,532 tests）。
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
>
> **⚠️ 2026-10-16 口径更正（第四轮）**：第一轮把这条收敛为"干净环境 0 fail"，但那只清除了
> **`/tmp` 残留目录**这一项环境依赖。**真实 CI 仍然红**——因为另有一类依赖从未被处理：
> 约 **130 个"真实数据"用例**硬依赖本地、**gitignored** 的数据湖
> （`data/lake/**`）、GBBQ 基线（`data/fq/gbbq.parquet`）与本地通达信客户端，而 CI 三者皆无。
> 详见 §7.6（CI 真绿化）。下文 "(b)" 的 `2526 passed / 4 failed` 数字**仅**描述 `/tmp` 问题；
> CI 真实的失败面是 **130**。
>
> **⚠️ 2026-10-16 二次更正（§7.7）**：CI 红是**三个串联成因**，数据湖只是其中之一，且**不是最先
> 发生的那个**：(1) `ruff` lint 失败（使 pytest 步骤被 skip，见 run `38398996210` 步骤表）；(2) **测试收集期
> 中断**——`tests/test_uniquant_production_architecture_gates.py` 硬编码开发机兄弟仓绝对路径
> `/home/james/Documents/Project/CNNM/scratch` 并 `from order_state_machine import …` → CI 上
> `ModuleNotFoundError` → `Interrupted: 1 error during collection` → **零用例执行（exit 2）**；
> (3) 130 个数据湖依赖用例。第二项只有在 pytest 真正跑起来后才暴露，此前被 (1) 掩盖。详见 §7.7。

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

> **仍开放（不属本报告 §5 范围，供后续决策）**：① 策略容量受限于 ≈2850 万元（H-A 的固有属性，非工程缺陷）；② `services/` 层覆盖率 63.8% 为当前最薄弱面（`data/` 层已于第三轮补齐，见 §7）。

---

## 7. 第三轮：数据层补测 + 历史文档漂移根治（2026-10-16）

第二轮结束时仍开放 ①②（`data/` 层 53.9%、历史文档失效口径）——本轮收口，纪律为**只补测试与文档、不改生产语义**。

### 7.1 数据层补测：53.9% → 94.2%

`data/` 层既是整包覆盖率最低面，又是**生产链路的入口**（湖优先读、单轨复权、清洗、校验、TDX 解包、主数据/日历）。本轮新增/扩充 **13 个测试文件 / 634 用例**（`tests/data/` 全量 634 passed）：

| 测试文件 | 用例 | 覆盖的目标模块（覆盖率变化） |
|---|---:|---|
| `test_storage_manager_extra.py` | 121 | `lake/storage_manager.py`（R-5 主数据硬失败守卫、新鲜度 SLA、读写契约、路径遍历） |
| `test_baostock_and_metadata.py` | 109 | `managers/_baostock_client.py` 19.8→**100%**；`baostock_cache_manager` 7.4→93.8%；`trade_calendar_manager` 67.1→97.4%；`stock_metadata_manager` 77.2→99% |
| `test_data_fetcher_extra.py` | 95 | `data_fetcher.py`（湖优先链、LRU 缓存、normalize/adjust/slice、委托面；`__new__` 无副作用构造） |
| `test_sources_and_factor_utils.py` | 71 | `sources/mootdx_online.py` 22.1→100%；`smart_factor_calculator` 58.7→97%；`utils/akshare_market_service.py` 54.5→94% |
| `test_futures_and_financial_import.py` | 63 | `services/futures_storage_manager.py` 76.3→100%；`services/import_financial.py` 44.3→99% |
| `test_akshare_wrapper.py` | 33 | `utils/akshare_wrapper.py` 0→高覆盖（假 `time`/`random` + `sys.modules` 注入假 akshare，**不触网**） |
| `test_normalizer.py` | 31 | `utils/normalizer.py` 31.9→**100%**（含 `_validate_data` 告警断言） |
| `test_tdx_parser_day_and_io.py` | 30 | `parsers/tdx_parser.py`（`.day` 解包、GBBQ 8 列契约、写盘守卫） |
| `test_market_coordinator_and_pipeline.py` | 30 | `managers/market_data_coordinator.py` 35.1→**100%**；`data_pipeline_service.py` 55.6→高覆盖 |
| `test_datasource_base.py` | 22 | `sources/base.py` 抽象契约 + 上下文管理器 + `close()` 语义 |
| `test_lppl_data_service.py` | 15 | `services/lppl_data_service.py` 13.3→96.8% |
| `test_data_layer_cleanup.py` | 10 | 死代码物理删除守卫 + `data/__init__.py` 懒加载契约（含子进程"重模块未被急切导入"断言） |
| `test_scripts_smoke.py` | 4 | `data/scripts/` 脚本导入冒烟 |

**分层覆盖率（第三轮实测，`coverage json` 口径）**：

| 层 | statements | missed | 覆盖率 | 第二轮 |
|---|---:|---:|---:|---:|
| `research/` | 704 | 40 | 94.3% | 94.3% |
| **`data/`** | **3,511** | **202** | **94.2%** | **53.9%** |
| `signal/` | 1,096 | 98 | 91.1% | 91.1% |
| `shared/` | 3,266 | 423 | 87.0% | 87.0% |
| `risk/` | 994 | 267 | 73.1% | 73.1% |
| `brain/` | 9,465 | 2,654 | 72.0% | 71.9% |
| `hands/` | 2,817 | 1,009 | 64.2% | 64.2% |
| **`services/`** | **4,393** | **1,592** | **63.8%** | 63.8% |
| **合计（omit `ui/`）** | **26,247** | **6,285** | **76.05%** | **70.55%** |

- `data/` 层 statements 3,676→3,511（含删除 `cache_manager.py`），missed 1,694→**202**。
- 当前最薄弱面转为 **`services/` 63.8%**（下一轮优先）。
- `data/` 残留未覆盖：`parsers/tdx_parser.py` 81.8%、`lake/storage_manager.py` 92.7%、`scripts/sync_minute_mootdx.py` 68.9%、`sources/mootdx_local.py` 75.6%、`corporate_action.py` 89.7%（多为 mootdx 真读者分支或需要真实 TDX/GBBQ 文件的分支）。

### 7.2 死代码剔除与潜在缺陷修复

**剔除（物理删除，附守卫测试）**：

| 目标 | 依据 |
|---|---|
| `data/managers/cache_manager.py`（整文件） | 全仓零 importers 实测（`rg`） |
| `data/sources/base.py` 215 → ~90 行 | 重复的列处理工具（`utils/normalizer.py` 为唯一实现）；仅保留 `DataSource` ABC 契约 |
| `data/services/lppl_data_service.py` 4 个方法 + `Dict` 导入 | 零调用者的死分支 |

**潜在缺陷修复（本轮定位并修复，全部附回归测试）**：

1. `parsers/tdx_parser.py::parse_day_file` —— **32 字节记录截断**：原按 `len(buf)//32` 切分，遇尾部残字节产生错位帧；改用 `struct.calcsize(_DAY_STRUCT)` 精确步长。
2. `parsers/tdx_parser.py::parse_day_file` —— **NaT 索引污染**：`set_index('date')` 后未剔除解析失败行，NaT 行进入下游；补 `df[df.index.notna()]`。
3. `lake/storage_manager.py` —— **路径遍历守卫失效**：原 `str(resolved).startswith(str(data_dir))` 存在前缀碰撞（`data_evil/` 被误判为 `data/` 之下）；改用 `Path.is_relative_to`。
4. `data_pipeline_service.py` × `pipeline/data_cleaner.py` —— **日期契约不一致（如实登记，未擅改语义）**：cleaner 用严格 `pd.to_datetime`（垃圾串抛 `DateParseError`），`process` 用 `errors="coerce"` + dropna。因 cleaner 先跑，`process` 的宽容分支对垃圾串**不可达**（仅 `None`/NaT 可达）。已用测试锁定实际契约（`test_garbage_date_raises_in_cleaner_not_silently_dropped`），并将两层的执行顺序（clean → validate → adjust）固化为断言。

### 7.3 历史文档漂移根治（`docs/archive/` + `docs/reanalysis/`）

策略：**目录级 README + 逐文件历史横幅（脚本化、仅插入）**，保留历史而非删除（`docs/archive/INDEX.md` 为既有范式）。

- 新建 `docs/reanalysis/README.md`（目录边界声明 + 当前真相源指引）。
- 59 个 `docs/reanalysis/*.md` 追加历史横幅（含 README 共 60 文件）。**逐文件与 `git show HEAD:<path>` 做插入式字节级校验：除新增横幅块外，正文逐字节不变。**
- `docs/archive/` 原有 24 文件已带横幅，本轮补齐剩余 **10 文件**（`DOC_MANAGEMENT_PLAN.md`、`RESTRUCTURE_PLAN.md`、`verify_algo.md` 等），同样通过插入式字节级校验（每文件 +3 行）。
- 横幅统一样式：声明"已归档 / 历史快照，不代表当前代码状态"，并指向 `docs/index.md` 与 `AGENTS.md`。
- `docs/archive/` 另含子目录（`Phase3_GlobalSweep/`、`audit_logs/`，共 27 个 .md）——已被目录级 `INDEX.md` 边界覆盖，且含重复归档（`Phase3_GlobalSweep` 在两处），**保持原样不删**。

### 7.4 未修的疑似问题（如实登记，不扩大本轮范围）

三个并行补测子代理在执行中发现、**超出本轮范围故未修**的疑似缺陷：

| # | 位置 | 现象 | 影响面 |
|---|---|---|---|
| 1 | `import_financial._normalize_stock_code` | 无数字字符串被伪造成 `"000000.SZ"` | 无白名单模式可能写入垃圾 parquet |
| 2 | `futures_storage_manager.get_dynamic_basis_surface` | `try/except → 0.0` 对 NaN 收盘价不生效 | NaN `term_slope` 可能入湖 |
| 3 | `import_financial.main()` | 第二阶段全部写失败仍 `return 0` | 编排层误判成功 |
| 4 | `stock_metadata_manager` | `stock_status` 恒 `None`（全仓无消费者） | 死字段 |
| 5 | `stock_metadata_manager.get_stock_info("sh.600519")` | 仅剥离 `.SH/.SZ/.BJ`，小写前缀查不到 | 缓存键归一不全 |
| 6 | `trade_calendar_manager.get_trade_calendar` | 回退分支对非法日期重新抛出 | 兜底不兜底 |
| 7 | `baostock_cache_manager` | 写死**相对**路径 `data/all_stock_codes.csv` | CWD 依赖 |
| 8 | `handle_errors`（`akshare_wrapper` / `_baostock_client`） | 默认 `reraise=True`，使 `default_return=` 失效 | 装饰器语义误导 |
| 9 | `akshare_wrapper.call` | 任何异常置 `_initialized=False`，重试循环改为"重初始化"而非"重放上游调用" | 上游仅触达一次 |
| 10 | `sources/mootdx_online._normalize_columns` | 可产生重复 `volume` 列；无 手→股 换算 | 模块 `enabled=false`（网络兜底待裁决），当前不在生产链路 |

> **➡️ 十项已于第六轮逐条处置（8 修 / 2 书面不修），含 4 个"把 bug 钉住"的用例反转与 1 个同类兄弟缺陷。见 §7.8。**
> 其中第 7 项为**安全关键**（改绝对路径必须同步改测试夹具，否则会覆盖已入库 SSOT），见 §7.8.2。

### 7.5 CI 覆盖率门更新

`.github/workflows/test.yml` 覆盖率作业 `--cov-fail-under` 由 **68 → 74**（实测 76.05%，留 ~2 点环境余量）——定位为**回归地板**，非 80% 达成线。

**第三轮全量门禁（本工作树实测）**：

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest tests/ -o addopts="" -p no:cacheprovider` | **3226 passed / 2 skipped / 0 failed**（收集 3228） |
| `.venv/bin/python -m pytest tests/ -o addopts="" -p no:cacheprovider -n 8 --timeout=900 --cov` | **3226 passed / 2 skipped / 0 failed**，**3 分 24 秒**，覆盖率 **76.05%** |
| `ruff check src/uniquant/ tests/ scripts/` | **All checks passed!** |
| `python scripts/maintenance/evidence_manifest.py verify` | **no drift** |

---

## 7.6 第四轮：CI 真绿化（本地数据湖依赖声明式跳过）

**触发**：推送 `3cf39ac` 后 CI **`test` 作业失败**（run `38858639286`）。同期 origin 上 2026-10-13 的
`7509c2a` 也是**失败**——即 CI 自那之后**一直是红的**，与本次推送无关。

> **⚠️ 本节只解决三个红因中的第三个。** 真实 CI 当时**一个用例都没跑**：pytest 在**收集期**就
> 因硬编码开发机绝对路径而中断（exit 2）。本节修完数据湖依赖后 CI **仍然红**，直到 §7.7 修掉
> 收集期中断才真正跑起来。历史成因排序见 §7.7。

**根因（实测，非推断）**：`7509c2a`（"扩充执行基线覆盖…并消除静默 skip 硬化守护"）在
`tests/benchmark/test_benchmark_execution.py` 里加了硬断言
`assert quote_path.exists(), "执行基线标的数据文件缺失 (严禁静默 skip 掩盖)"`，指向
`data/lake/quotes/daily/000001.SZ.parquet`——**该目录整个 gitignored，CI 上永远不存在**。
同类的"真实数据"用例还有一批：它们读 `data/lake/**`、`data/fq/gbbq.parquet`（GBBQ 基线）
或**本机 Wine 通达信客户端**（`~/.local/share/tdxcfv`）。CI runner 三者皆无 → 必红。

> 即：第一轮 P0-2 只清掉了 **`/tmp` 残留目录**这一项环境依赖，而**数据湖依赖**从未处理；
> 当时"干净环境 0 fail"的结论**不完整**（§3 P0-2 已加更正）。

**复现方法（可复现，且不改动真实 `data/`）**：本机无 root，用**私有 mount 命名空间**
把 CI 的数据环境"套"到工作树上——将 CI 仅有的 `data/`（2 个 tracked CSV）bind-mount 覆盖真实
`data/`，并把本地通达信目录 bind-mount 到空目录：

```bash
REPO=/home/james/Documents/Project/UniQuant
rm -rf /tmp/opencode/ci_data /tmp/opencode/ci_empty /tmp/opencode/ci_empty_cnnm
mkdir -p /tmp/opencode/ci_data /tmp/opencode/ci_empty /tmp/opencode/ci_empty_cnnm
cp $REPO/data/all_stock_codes.csv $REPO/data/qualified_universe.csv /tmp/opencode/ci_data/
# 三个 mount 缺一不可：数据湖、本地通达信、以及**开发机兄弟仓**（收集期中断的真凶，见 §7.7）
unshare -rm --propagation private sh -c '
  mount --bind /tmp/opencode/ci_data       '"$REPO"'/data
  mount --bind /tmp/opencode/ci_empty      /home/james/.local/share/tdxcfv
  mount --bind /tmp/opencode/ci_empty_cnnm /home/james/Documents/Project/CNNM
  cd '"$REPO"' && .venv/bin/pytest tests/ -q --tb=short
'
# 离开命名空间后 mount 自动消失，真实 data/ 与通达信目录未被触碰
```

> ⚠️ **踩坑记录（本轮代价最大的一课）**：前两个 mount 只覆盖了"缺数据"，**第三个**（屏蔽兄弟仓）
> 才覆盖"缺代码"。缺了它，本机永远复现不出 CI 的收集期中断——这正是 §7.6 修完数据湖依赖后
> CI 仍红的根本原因。**本地等价复现必须同时屏蔽"数据依赖"与"开发机专有路径依赖"两类。**

> 注：`git clone` 到别处**不能**复现 CI——editable 安装（`.pth` → 真实仓库 `src/`）会让
> `mootdx_local` 兜底读到本机通达信，掩盖缺失数据湖。必须同时屏蔽**数据湖**与**本地通达信**。

**修复（纪律：只动测试，不改生产语义）**：`tests/conftest.py` 增三类**声明式标记** +
集中跳过钩子 `pytest_collection_modifyitems`，缺数据时挂**显式 skip 原因**（点名缺失物与
重建脚本），而非让它失败、更非让它**在空表上静默通过**：

| 标记 | 判定 | 缺失时原因 |
|---|---|---|
| `requires_lake` | `data/lake/**` 存在任一 parquet | 本地数据湖未生成（gitignored） |
| `requires_futures_lake` | `data/lake/futures/**` 存在 parquet | 期货数据湖未生成 |
| `requires_gbbq` | `data/fq/gbbq.parquet` 存在 | GBBQ 基线缺失，附重建命令 |

标记面（共 **130** 个用例）：

| 文件 | 用例数 | 标记 |
|---|---:|---|
| `tests/test_csi300_qfq_smoke.py` | 109 | `requires_lake` + `requires_gbbq`（模块级） |
| `tests/test_corporate_action_adjuster.py` | 5 + 2 | 5 × `requires_lake`；2 × `requires_gbbq`（初始化/无事件） |
| `tests/test_futures_storage_manager.py` | 5 | `requires_futures_lake` |
| `tests/test_cnmm_qar_strategy_and_backtest.py` | 4（2 类） | `requires_lake` |
| `tests/scripts/test_ha_engineering.py` | 2 | `requires_lake`（`TestHoldingsMapCadence`） |
| `tests/benchmark/test_benchmark_execution.py` | 1 | `requires_lake`（**保留**原"严禁静默 skip"断言：湖在而标的缺失仍硬失败） |
| `tests/test_storage_freshness_sla.py` | 1 | `requires_lake` |
| `tests/test_get_price_contract.py` | 1 | `requires_gbbq`（默认 qfq 路径） |

同环境**修复前**的失败清单（实测，与上表逐项对应）：`test_csi300_qfq_smoke` 109、
`test_corporate_action_adjuster` 7、`test_futures_storage_manager` 5、`test_ha_engineering` 2、
`test_cnmm_qar_strategy_and_backtest` 4（2 类）、`test_benchmark_execution` 1、
`test_get_price_contract` 1、`test_storage_freshness_sla` 1 = **130**。

**验证（同一私有命名空间，逐项实测）**：

| 口径 | 命令 | 结果 |
|---|---|---|
| **修复前**（守卫 stash 掉，同一命名空间） | `pytest tests/ -q --tb=no --junit-xml=…` | **126 failed / 4 error** = 失败面 **130**（同环境 21 skip）→ `errors="4" failures="126" skipped="21" tests="3228"` |
| **修复后**（本地等价复现，`test` 口径） | 同上 | **0 failed / 0 error**（`errors="0" failures="0" skipped="151" tests="3228"`）**⚠️ 口径不正（依赖集含未声明的 `czsc`）——见 §7.9** |
| **修复后**（本地等价复现，`coverage` 口径） | `pytest -n auto --timeout=900 --cov --cov-fail-under=74` | **0 failed / 0 error**，~~75.57%（26,247 语句 / 6,411 未覆盖）~~ **⚠️ 真实 CI 口径 = 74.57%（26,268 / 6,681）——见 §7.9** → **Required test coverage of 74% reached** |
| 本机（含数据湖） | `pytest tests/ -q -n 8` | **3226 passed / 2 skipped / 0 failed**（标记在本机为 no-op，全部真跑） |
| `ruff check src/uniquant/ tests/ scripts/` | — | **All checks passed!** |

**覆盖率口径（重要）**：**⚠️ 本段数字已被 §7.9 更正**——此处"CI 口径 75.57%"是在**装了未声明的 `czsc`**
的解释器上测得的，**并非真实 CI 口径**。真实 CI（`.[all,dev]`，无 `czsc`）为 **74.57%**（26,268 / 6,681）。
本机口径当时为 76.05%（含 `czsc` + 数据湖）。门限 **74** 相对**真实 CI 口径**余量仅 **+0.57 点**（非 ~1.6 点）。
`.github/workflows/test.yml` 注释亦已同步更正。

**残余诚实说明**：CI 上有 **151** 个 skip（130 个本次新增 + 21 个既有环境守卫，如
`test_tdx_parser_gbbq_mapping` 依赖本机通达信路径）。跳过**不等于**验证——这些用例的
回归保护只在持有本地数据湖的开发机上生效；这是本仓"数据湖不可入版本库"这一前提的
**必然代价**，而非可消除的缺陷。

---

## 7.7 第五轮：CI 收集期中断（真正的第一红因，exit 2）

**症状**：§7.6 修复推送后（`2c55790`，run `38867037638`）CI **仍然红**，且两个作业在 **76 秒**内
失败——远短于应跑完 3000+ 用例的时间，本身就是"一个用例都没跑"的信号。

**诊断通道**：仓库读取权限受限（`gh` job log 403 "Must have admin rights"），因此本轮在
`.github/workflows/test.yml` 的 pytest 步骤里增加了**失败摘要发布为 check-run 注解**
（`::error title=pytest-digest::…`，截断到有界长度）。免鉴权读注解即得全貌：

```
[failure] pytest-digest :: !!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!
[failure] pytest-digest :: E   ModuleNotFoundError: No module named 'order_state_machine'
[failure] pytest-digest :: ERROR tests/test_uniquant_production_architecture_gates.py
[failure] .github:48      :: Process completed with exit code 2.
```

**根因（硬编码开发机绝对路径）**：`tests/test_uniquant_production_architecture_gates.py` 把
**兄弟仓**的绝对路径插进 `sys.path`：

```python
UNIQUANT_ROOT = Path("/home/james/Documents/Project/UniQuant")
CNNM_ROOT     = Path("/home/james/Documents/Project/CNNM")      # ← CI 无此目录
CNNM_SCRATCH  = CNNM_ROOT / "scratch"
sys.path.insert(0, str(CNNM_SCRATCH))
from order_state_machine import (...)                            # 本机解析自 CNNM 兄弟仓
```

本机兄弟仓存在 → **恒绿**；CI 无此目录 → 模块级 import 抛 `ModuleNotFoundError` →
pytest **在收集期整体中断**。pytest 退出码语义：`0` 全过 / `1` 有用例失败 / **`2` 收集期错误**；
**exit 2 意味着零用例执行**——这解释了 76 秒的"失败"，也解释了为何 §7.6 的数据湖修复看似
生效却无济于事（数据湖只是"缺数据"，这一项是"缺代码"，先炸）。

**为什么长期未被发现**：
1. 本机（开发机）兄弟仓恒存在，本地永远复现不出；
2. §7.6 的命名空间复现只屏蔽了 `data/` 与本地通达信，**没有屏蔽兄弟仓**——只覆盖了"数据依赖"，
   漏掉了"开发机专有路径依赖"；
3. CI 上 pytest 在此前**从未真正跑起来过**：run `38398996210`（`7509c2a`）失败在 **Lint with ruff**
   步骤，其 `Test with pytest` 是 **skipped**。即该缺陷自该文件引入起就潜伏，被 lint 失败掩盖。

**CI 红的完整三因账（串联，非并列）**：

| # | 成因 | 首次暴露 | 现象 | 处置 |
|---|---|---|---|---|
| 1 | **`ruff` lint 失败** | `7509c2a` / `631829f6` | `Lint with ruff` 失败 → pytest 步骤 **skip** | 第一轮 P0-2（`ruff --fix` 27 自动 + 3 人工）→ 归零 |
| 2 | **收集期中断（exit 2）** | `3cf39ac`（lint 修好后 pytest 首次真正运行） | `ModuleNotFoundError: order_state_machine` → **零用例执行** | **本条（§7.7）** |
| 3 | **130 个数据湖/GBBQ/通达信依赖用例** | 同上（收集修好后才可见） | 126 failed / 4 error | 第四轮 `7de0d83`（三标记声明式跳过） |

> 即：**"CI 自 `7509c2a` 起一直是红的"这一判断成立，但把它单一归因于数据湖硬断言是错的。**
> `7509c2a` 的 CI 失败其实是 **ruff**；数据湖依赖与收集期中断都是**在 pytest 真正运行后**才显形的。

**修复（纪律：只动测试与 CI，不改生产语义）**：
1. `tests/test_uniquant_production_architecture_gates.py`：路径全部改为 `Path(__file__)` 派生的
   仓库内相对定位（`REPO_ROOT = Path(__file__).resolve().parents[1]`）；`order_state_machine` 改从
   **仓库内已入库的** `scratch/` 导入（`git ls-files` 确认 tracked，且与本机 CNNM 副本逐字节一致）；
   `ENGINE_PATH` 同样改为 `UNIQUANT_SRC / "uniquant" / …`。
2. `tests/test_tdx_parser_gbbq_mapping.py`：通达信 gbbq 路径由硬编码改为
   `TDX_HOME` 环境变量 / `Path.home()` 兜底（CI 上仍走既有 `skipif`，行为不变但不再硬编码用户名）。
3. **新增回归守卫** `tests/test_no_dev_absolute_paths.py`：AST 级扫描 `tests/**/*.py` 的字符串字面量，
   命中 `^(/(home|Users)|[A-Za-z]:\\{1,2}Users)/<user>/` 即失败，并在报错里给出文件:行:字面量；
   另含**正对照**用例（用字符串拼接构造样例，避免守卫自伤），防止守卫空转。
   范围仅 `tests/`——`scripts/` 是研究脚本，允许"环境变量兜底 + 开发机默认值"写法。

**验证（逐项实测）**：

| 口径 | 命令/条件 | 结果 |
|---|---|---|
| 修复前（CI 实证） | check-run 注解 | `Interrupted: 1 error during collection` → exit 2 → **0 用例** |
| 修复后（本次命名空间，**额外**屏蔽兄弟仓） | `pytest tests/test_uniquant_production_architecture_gates.py` | **17 passed**（该文件全部用例真跑） |
| 修复后（全量，CI 等价：无湖/无通达信/**无兄弟仓**） | `pytest tests/ -q` | `errors="0" failures="0" skipped="151" tests="3232"`（run **3081**）**⚠️ 该行口径不正**——见 §7.9：真实 CI 为 `skipped=164 tests=3216`（依赖集须与 `.[all,dev]` 一致，即**无 `czsc`**） |
| 修复后（coverage 口径） | `-n auto --timeout=900 --cov --cov-fail-under=74` | ~~75.57%（26,247 / 6,411）~~ **⚠️ 更正为 74.57%（26,268 / 6,681）** ≥ 74 → **Required test coverage of 74% reached**（见 §7.9） |
| 本机（含数据湖） | `pytest tests/ -q` | **3230 passed / 2 skipped / 0 failed**（收集 3232；标记为 no-op，用例全部真跑） |
| 本机（含数据湖，`HOME` 污染修复生效） | 同上，skip 明细 | 仅 **2** 个 backtrader 缺依赖 skip；**此前 7 个**（多出的 5 个 = gbbq 真实数据用例被静默跳过） |
| `ruff check src/uniquant/ tests/ scripts/` | — | **All checks passed!** |
| 守卫正对照 ×2 | `test_guard_detects_*` | **pass**（两守卫均非空转；另有植入违规文件的端到端反证） |
| **已绿化验证（真实 GitHub Actions，非本地等价）** | push `a434d68` → CI run **`38870946347`** | `test` 作业**全 8 步 success**（含此前长期被 skip 的 **`Lint with ruff`** 与 **`Test with pytest`**，后者 ~2.5 min 真跑：`Audit dependencies`/`Lint with ruff`/`Verify evidence manifest`/`Test with pytest` 全绿）；`coverage` 作业 **`Test with coverage gate` success**（~112 s ⇒ CI 上 `--cov-fail-under=74` 达标）；`Security Audit` run **`38870946235`** success → **三条 check-run 全绿**。这是自 `7509c2a` 以来 CI **首次全绿** |

**附带发现（同一失败类：导入期全局状态改写 `HOME`）**：复现过程中本机全量套件出现 **7** 个 skip
而非预期的 **2** 个——多出的 5 个正是 `test_tdx_parser_gbbq_mapping.py` 的真实数据用例。根因**实测定位**：
`tests/test_import_financial.py:9` 在**模块顶层**执行 `os.environ["HOME"] = "/tmp"`。pytest 在同一进程内
按文件名顺序导入所有测试模块，而 `test_import_financial.py` 字典序在前——故其后导入的
`test_tdx_parser_gbbq_mapping.py` 求值 `skipif` 时看到的 `HOME` 已是 `/tmp` → `Path.home()` 解析到
`/tmp/...` → gbbq 真文件"不存在" → **静默跳过 5 个真实数据用例**（不报错、不告警）。

- 该行改写对本用例**毫无必要**——被测模块 `import_financial.py` 全文不读 `HOME`/`home`，纯遗留污染 → **已删除**。
- 同类风险由第二个守卫锁死：`tests/test_no_import_time_env_mutation.py` —— AST 扫描 `tests/**/*.py`
  **顶层**语句中的 `os.environ[...] = ...` / `os.environ.update(...)` / `os.putenv(...)`；豁免
  `conftest.py`（其中集中设置环境变量是正当用法）与 `scripts/`；含**正对照**用例防空转。
- **端到端反证**：临时放入 `tests/test_zz_temp_env_leak.py`（内容 `os.environ["HOME"] = "/tmp"`）→
  守卫必红并点名 `test_zz_temp_env_leak.py:3 -> assign`；删除后复绿。

> 本条与 §7.7 主因同属一族——**"全局状态 + 导入顺序"**：主因是"缺代码"（收集期崩溃，**响亮失败**），
> 本条是"静默改变行为"（悄悄少跑 5 个用例，**无声**）。共同教训：测试不得依赖导入顺序或进程级可变状态。

**教训（本轮代价最大的一课）**：本地等价复现 CI 必须同时屏蔽**两类**依赖——
**数据依赖**（数据湖/GBBQ/通达信）与**开发机专有路径依赖**（兄弟仓绝对路径）。
只屏蔽前者，会得到"修完仍红、且本机复现不出来"的假象。已写入 §7.6 复现配方与
`AGENTS.md`，并以此守卫锁死。

---

## 7.8 第六轮：§7.4 十项疑似问题处置（2026-10-16）

**纪律变更声明（刻意为之）**：第三/四/五轮的纪律是"**只动测试与 CI，不改生产语义**"。
§7.4 十项是当时**唯一剩余的显式待办**，且**全部位于生产代码**——要关闭它们就必须突破该纪律。
本轮的纪律改为：**每项改动 = 定向回归测试 + 明确理由 + 书面裁决（修 / 不修）**，逐项可追溯。
裁决取自三个并行**只读** `explore` 子代理的逐项取证（定位 / 调用方 / 既有测试）/ 以及对每一处源码的直接复读，
并且对每一项都回答了一个关键问题：**既有测试是把 bug "钉住"了，还是把 bug "当成了正确行为"**——后者即"伪回归"，
必须连同用例语义一起反转（本轮共反转 4 个此类用例）。

### 7.8.1 处置总表

| # | 位置 | 裁决 | 理由（含调用方证据） | 回归测试 |
|---|---|---|---|---|
| 1 | `import_financial._normalize_stock_code` | **修复** | 无数字输入（`"abc"` / `"..."` / 纯符号）经 `digits.zfill(6)` 被**伪造成 `"000000.SZ"`**。无白名单模式（`allowed_stock_codes` 为空）下会写出垃圾 parquet。改为返回 `None`（"无法归一的代码"），由 stage1 `map` 落 NaN、stage2 跳过 | `tests/test_import_financial.py`（+3 断言：`"abc"`/`"..."`/空 均为 `None`） |
| 2 | `futures_storage_manager.get_dynamic_basis_surface` | **修复** | 原护栏 `try/except → 0.0` **对 NaN 不生效**：`np.polyfit` 遇非有限输入**不一定抛异常**（stub 验证：返回 NaN + `RankWarning`）→ NaN `term_slope` 可入湖。三层加固：① 非有限**现货**收盘价 → `ValueError`（与"无现货行"同类，响亮失败）；② 非有限**合约**收盘价 → **跳过该合约**（与"该合约当日无行"同类）；③ 拟合结果显式 `np.isfinite` 检查 → 非有限回退 `0.0`（与退化分支一致） | 原 `test_basis_surface_nan_close_propagates_nan_term_slope`（**钉住了 bug**）→ 反转+拆分为 3 例：`..._skips_non_finite_close_contract` / `..._non_finite_spot_close_raises` / `..._non_finite_fit_falls_back_to_zero`（monkeypatch `np.polyfit` 返回 NaN） |
| 3 | `import_financial._write_single_stock` / `import_batch` / `main()` | **修复** | 原实现把"**真实写入失败**"与"**按规则跳过**"压成同一个 `False`；`import_batch` 只把后者计入局部 `write_fail`，且**不并入返回值** → **阶段2全量写失败时 `main()` 仍 `return 0`**，编排层误判成功。改为：`_write_single_stock` 对真实 IO/数据异常**向上抛出**（`False` 仅表示跳过）；`import_batch` 分设 `write_skipped` / `write_failed` 计数，返回值第三项 = **解析失败 + 写入失败** | 原 `test_write_single_stock_io_failure_returns_false`（**钉住 bug**）→ `..._io_failure_raises`；原 `test_import_batch_write_failure_is_logged` → 拆 2 例：`..._write_failure_is_counted_as_failure`（`(1,0,1)`）/ `..._write_skip_is_not_a_failure`（跳过仍 `(1,0,0)`，防两类混淆） |
| 4 | `stock_metadata_manager._load_all_codes`（守卫行） | **修复** | `_normalize_columns` 已把 `status`→`stock_status`，但守卫仍 `getattr(row, 'status', None)`；`itertuples` 下**永无 `status` 属性** → `stock_status` 恒 `None`。**消费者确实存在**：`storage_manager.get_stock_metadata()` 会输出该字段（故非"死字段"而是"静默失效字段"） | 原 `test_populated_status_column_is_ignored`（**钉住 bug**）→ `..._is_loaded`（`"0"` / `"1"`） |
| 5 | `stock_metadata_manager.get_stock_info` | **修复** | 缓存键由模块级 `_normalize_stock_code` 统一为**后缀**格式（Step4 已修**写侧**），但**查侧**只剥 `.SH/.SZ/.BJ` → 裸 `sh.600519` 永不命中 → `storage_manager` 退市守卫**静默失效**。改为先用同一归一函数归一化，再以原子键查询（保留原后缀探测为兜底） | 原 `test_get_stock_info_does_not_accept_baostock_prefix`（**钉住 bug**）→ `..._accepts_baostock_prefix`（`sh.600519` / `sz.000001` / `bj.430047`） |
| 6 | `trade_calendar_manager.get_trade_calendar` 回退分支 | **不修（设计如此）** | 回退分支只针对**内部错误**；调用方传入**非法日期字符串**属编程错误，**响亮抛出（fail-fast）优于静默返回空日历**（静默空日历会让下游"以为休市"）。既有用例即按此语义钉住，且该语义是正确的 | 保留 `test_get_trade_calendar_invalid_dates_propagate_from_fallback`（语义正确，不动） |
| 7 | `baostock_cache_manager`（+ 同类兄弟 `hands/reporter.py`，**附带发现**） | **修复** | 写死**相对**路径 `data/all_stock_codes.csv` → 行为依赖 CWD，从非仓库根目录运行时写到错位置。抽为模块常量 `OUTPUT_PATH` / `TEMP_PATH`（= `shared.constants.path.STOCK_LIST_FILE`，绝对 SSOT），3 处引用全替换；`reporter._load_stock_names` 同类问题改用同一常量 | 新增 `test_cache_output_paths_are_absolute_ssot`、`test_cache_writes_to_absolute_path_not_cwd`；**夹具同步改造为 monkeypatch 常量指向 `tmp_path`**（安全关键，见 §7.8.2） |
| 8 | `handle_errors(default_return=...)` | **不修默认值，仅修文档** | 默认 `reraise=True` 会**先 `raise`**，使 `default_return=` 短路失效。全仓约 **30 处**调用点传了非 None `default_return` 却未传 `reraise=False`（属既有 fail-fast 约定）。**改默认值 = 静默改变这 30 处的失败语义**（10× 爆炸半径），远超本轮收益。仅在 docstring 如实标注该陷阱 | `tests/test_error_handling*.py`（语义不变，仅文档） |
| 9 | `akshare_wrapper.call` "只重初始化不重放" | **不修（claim 部分被否证）** | 领域错误经 `handle_errors(reraise=True)` 抛出后**确会进入重试**；生产中 `_init_akshare()` 成功即置 `_initialized=True` → **上游调用确实重放**。"只重初始化不重放"仅在**重初始化被 mock 成 no-op** 的测试场景成立（属测试构造的假象，非生产缺陷）。"任何异常即重置会话"是既有策略，无证据表明改之有利 | 保留 `test_domain_error_toggles_uninitialized` / `test_generic_error_toggles_uninitialized`（后者证明会重放 5 次） |
| 10 | `mootdx_local` / `mootdx_online._normalize_columns` | **修复（仅重复列）/ 不修（手→股）** | 原映射同时含 `volume→volume` 与 `vol→volume`，两列并存时 rename 产出**重复 `volume` 列**（落湖/pyarrow 报错，或静默取错列）。改为：仅做真正的别名重命名、目标列已存在时不覆盖、并存时保留规范列并丢弃别名（并 `warning`）。**"手→股"换算不修**：mootdx 输出单位为"手"，换算系数**跨 11 类资产不一致**（`compat.py`），属消费方归一化职责；硬编码 ÷100 会在非股票资产上出错 | 新增 `tests/test_mootdx_local_bugs.py` ×4（vol 单列改名 / volume 单列不动 / 两列并存→单列且规范列胜出 / datetime→date）+ `tests/data/test_sources_and_factor_utils.py` ×1（online 两列并存） |

**净效果**：**8 项改生产代码**（#1、#2、#3、#4、#5、#7（含兄弟）、#8（仅文档）、#10（仅重复列处理）），
**2 项书面裁决不修**（#6 设计如此、#9 claim 否证）。**无一项改变对外契约签名**；
`import_batch` 返回值语义变化（第三项 = 解析失败+写入失败）已同步其**唯一**调用方
`scripts/rebuild_financial_lake.py`（键名改为 `success_files`/`skipped_files`/`failed_files`，`rg` 确认无其它读取方）。

### 7.8.2 安全关键：改了绝对路径就必须同步改夹具

第 7 项是本轮**唯一可能造成版本库破坏**的改动，记录下防线：

- 改动前 `create_baostock_cache` 写**相对** `data/all_stock_codes.csv`，而测试夹具靠
  `monkeypatch.chdir(tmp_path)` 把它"关"进 `tmp`。
- 一旦路径变成**绝对**，若沿用 `chdir` 夹具，测试**就会覆盖真实、已入库、全系统 SSOT 的**
  `data/all_stock_codes.csv`（8,879 行）。
- 因此**同一提交内**必须把夹具改为 `monkeypatch.setattr(bcm, "OUTPUT_PATH", tmp_path/"data"/...)`
  等（`chdir` 保留作纵深防御），并**实测**该文件 `mtime` 与内容未变：
  `ls -l --time-style=full-iso data/all_stock_codes.csv` → `2026-08-19 12:21:53`（本轮未触碰）。

### 7.8.3 第六轮验证（本工作树实测）

| 口径 | 命令 | 结果 |
|---|---|---|
| 定向（本轮触及的 5 个测试文件 + 2 个 error-handling 文件） | `pytest tests/test_import_financial.py tests/data/test_futures_and_financial_import.py tests/data/test_baostock_and_metadata.py tests/data/test_sources_and_factor_utils.py tests/test_mootdx_local_bugs.py tests/test_error_handling*.py` | **279 passed** |
| 数据域广域回归 | `pytest tests/data tests/test_import_financial.py tests/test_mootdx_local_bugs.py tests/test_report_paths.py tests/test_results_manager_extra.py` | **661 passed** |
| 本机全量（含数据湖 + `czsc`） | `.venv/bin/python -m pytest tests/ -q -n 8` | **3240 passed / 2 skipped / 0 failed**（收集 3242；= 第五轮 3230 + 本轮新增 **10**） |
| CI 等价（三 mount；完整依赖） | 见 §7.6 配方的三个 `mount --bind` | **3091 passed / 151 skipped / 0 failed / 0 error**（收集 3242；= 第五轮 3081 + 10，跳过量**不变**） |
| CI 等价（三 mount；`.[all,dev]` 真实依赖集） | 同上，但用无 `czsc` 的解释器 | **3052 passed / 164 skipped / 0 failed / 0 error**（收集 3216）——**这才是真实 CI 的数字**，见 §7.9 |
| 本机覆盖率 | `-n 8 --cov --cov-fail-under=74` | **76.08%**（26,268 语句 / 6,284 未覆盖）≥ 74 |
| CI 等价覆盖率（`.[all,dev]` 依赖集） | `-n auto --timeout=900 --cov --cov-fail-under=74` | **74.57%**（26,268 / 6,681）≥ 74 → `Required test coverage of 74% reached`（余量仅 **+0.57 pt**，见 §7.9 风险提示） |
| `ruff` | `ruff check src/uniquant/ tests/ scripts/` | **All checks passed!** |
| SSOT 未被测试污染 | `ls -l --time-style=full-iso data/all_stock_codes.csv` | `2026-08-19 12:21:53`，**未变** |

---

## 7.9 第六轮附带发现：CI 从未装上 `czsc`（并更正第五轮"CI 口径"）

这是本轮**最重要的诚实更正**——它推翻了一个此前被当作既成事实的口径。

**事实链（可复现）**：

1. `src/uniquant/brain/czsc/czsc_engine.py:6` 顶层 `from czsc import CZSC, Freq, RawBar`（**未加守卫**）；
   `brain/czsc/__init__.py` 用 `try/except ImportError → CZSCEngine = None` 兜住，故包导入不炸。
2. **`czsc` 不在 `pyproject.toml` 的 `dependencies`，也不在任何一个 optional-extras**（`dev`/`tdx`/`baostock`/`curl`/`report`/`js`/`all`）中。
   实测 `.venv/bin/pip show czsc` → `Required-by: rs_czsc`（`rs_czsc` 同样未声明）→ **本机 `czsc` 是手工装的开发机附加物**。
3. CI 的安装步骤是 `pip install -e ".[all,dev]"` → **真实 CI 里没有 `czsc`**。
4. 后果（在本机用"`.[all,dev]` 依赖集"的解释器 + 三 mount 实测）：
   - 4 个 `pytest.importorskip("czsc")` 模块**整个不被收集** → 少 **30** 个用例
     （`test_czsc_engine.py`、`test_czsc_bar_list_vectorization.py`、`test_technical_and_signal_regressions.py`、`test_more_analysis_engine_regressions.py`）；
   - `test_brain_boundary_qa.py` 另有 **9** 例以 `czsc package not installed` 跳过；连上 4 个模块级 skip 条目共 **+13** 跳过；
   - `czsc_engine.py`（及其同包模块）**从未被导入** → 其语句在覆盖率统计里**全额计入未覆盖**。

**因此更正**：第五轮/§7.6/§7.7 记录的"CI 口径 **3,081 passed / 151 skipped / 收集 3,232**、coverage **75.57%**"
是在**装了 `czsc` 的本机等价环境**里测的，**并非 CI 口径**。**真实 CI 口径 = 3,052 passed / 164 skipped / 0 failed / 0 error（收集 3,216）、coverage 74.57%**。
差额（约 270 未覆盖语句 + 30 用例）恰好由"缺 `czsc`"解释。**§7.6/§7.7 与 `docs/index.md`/`AGENTS.md`/`README.md` 的对应数字已同步更正。**

**为什么不在本轮"修"（如把 `czsc` 加进 `[all]`）**：`pip show czsc` 的 `Requires` 含 **`ta-lib`**——
这是需要**系统级 C 库**的包，`pip install` 常因缺该库而**构建失败**。把它塞进 `[all]` 会让 CI 的
`pip install -e ".[all,dev]"` 步骤本身变红，属**用更大风险换更小收益**。正确处置是**如实登记**
（可选依赖必须"声明 + 守卫 + 显式跳过"，现状是"未声明 + 半守卫 + 隐式不收集"），
若要根治应走独立立项（把 `czsc` 放入独立 extra 并在 CI 显式跳过该 extra，或换成纯 Python 的等价实现）。

**风险提示（交给下一轮）**：CI 覆盖率门限 `--cov-fail-under=74` 在**真实 CI 口径下余量仅 +0.57 个百分点**。
本轮不动门限（动门限=掩盖问题），但若后续新增未覆盖的生产模块，**大概率会把 CI 打红**——
届时正确做法是补测，而非降门限。

**本轮新生效的"文档纪律"**：**任何"CI 口径"数字必须注明解释器依赖集**（是否含未声明的开发机附加包）。
仅写"CI 等价"而不同时写"依赖集"是会骗人的——这正是本轮踩到的坑。

---

## 7.10 第七轮：生产孤岛剪除 + `services/` 层覆盖率补测 + 一个只在 CI 解释器暴露的真 bug（2026-10-17）

本轮目标（用户指定）：**剪除生产孤岛**（`services/analysis/` 下三个零调用方的 `*Service` 门面类）+
**抬升在线 `services/` 模块覆盖率**。两条都要求"有证据 + 有裁决"，故沿用第六轮纪律：
**每项改动 = 定向测试 + 明确理由 + 书面裁决**。

### 7.10.1 生产孤岛剪除（3 文件；整包语句 26,268 → 25,854，−414）

| 文件 | 裁决 |
|---|---|
| `services/analysis/macro_service.py` | **剪除**（−120 未覆盖语句） |
| `services/analysis/technical_service.py` | **剪除**（−118） |
| `services/analysis/signal_service.py` | **剪除**（−59） |

**证据**（三路并行**只读** `explore` 子代理 + 主线直接复读源码）：

1. **生产零调用方**：`src/` 内除 `services/analysis/__init__.py` 的历史导出外**无任何 import**；`scripts/` 亦无。
2. **职责已被在线路径取代**：三者是早期"每个引擎配一个门面"的遗留壳，其职责已由
   `analysis_service_v2.AnalysisService`（主编排）+ `services/analysis/engine_factory.AnalysisEngineFactory`
   （引擎适配器）承接；对应**在线**引擎是 `analysis/{macro,regime,ntf,lppl,fsm,report_generator,czsc}_analysis_engine.py`。
3. **其唯一独有安全属性在剪除后仍受保护（不产生回归面）**：`macro_service` 曾被测试锁定
   "空返回时**不得**用 `np.random.random` 兜底"。该契约在**在线的** `analysis/macro_analysis_engine.py` 上
   同样有测试（本轮补齐后 100% 覆盖；随机性契约另见 `tests/test_p2_randomness_annotations.py` 的在线化改写）。
   → **删壳不删守卫**。
4. 全仓仅 **3 个测试文件**引用它们，均已相应处置：删除 `tests/test_technical_and_signal_regressions.py`（4 例全针对已删门面）；
   `tests/test_macro_and_scan_regressions.py` → `git mv` 为 `tests/test_scan_service_regressions.py`（仅保留在线
   `ScanPipeline.load_data` 用例，4 → 1）；`tests/test_phase4_1_remediation.py` 删 1 例（`macro_service` 空返回契约，已在线化）；
   `tests/test_p2_randomness_annotations.py` 扫描清单去掉已删路径。

**附带清理**：`services/analysis/__init__.py` 改为 `__all__ = []` + 理由 docstring；`services/__init__.py` 引擎清单 docstring 同步；
5 篇文档（`docs/packages/services.md`、`docs/ARCHITECTURE_TOPOLOGY.md`、`docs/development/project_structure.md`、
`docs/whitepaper/ARCHITECTURE_WHITEPAPER.md`、`docs/whitepaper/DEPLOYMENT_ARCHITECTURE.md`）删除对应 mermaid 节点/边
+ 正文引用（含"已剪除"注记）。

### 7.10.2 `services/` 层覆盖率补测（6 个新测试文件 / 215 测试函数）

全部为**新增测试文件**，**不改生产语义**；`ruff check` 干净。逐模块实测（**本机口径**，before = 同一份代码 + 第六轮末测试集）：

| 模块 | 测试数 | before | after |
|---|---:|---|---|
| `services/data_quality_service.py` | 34 | 145/122 = **16%** | 145/0 = **100%** |
| `services/stock_query_service.py` | 26 | 111/61 = **45%** | 111/0 = **100%** |
| `services/validation_service.py` | 27 | 189/52 = **72%** | 189/0 = **100%** |
| `services/health_service.py` | 42 | 263/137 = **48%** | 263/0 = **100%** |
| `services/data_access_service.py` | 30 | 174/54 = **69%** | 174/0 = **100%** |
| `analysis/regime_analysis_engine.py` | ↓ 56 例共覆盖 | 39/21 = **46%** | 39/0 = **100%** |
| `analysis/ntf_analysis_engine.py` | 同上 | 40/21 = **48%** | 40/0 = **100%** |
| `analysis/lppl_analysis_engine.py` | 同上 | 54/15 = **72%** | 54/0 = **100%** |
| `analysis/fsm_analysis_engine.py` | 同上 | 88/23 = **74%** | 88/2 = **98%** |
| `analysis/report_generator_engine.py` | 同上 | 81/27 = **67%** | 81/0 = **100%** |
| `analysis/macro_analysis_engine.py` | 同上 | 66/13 = **80%** | 66/0 = **100%** |
| `analysis/czsc_analysis_engine.py` | 同上 | 74/20 = **73%** | 74/2 = **97%** |
| **`services/` 层合计（剪除后文件集）** | | 3,979/1,370 = **65.57%** | 3,979/808 = **79.69%** |

新增文件：`tests/test_data_quality_service_unit.py`(34)、`tests/test_stock_query_service_unit.py`(26)、
`tests/test_validation_service_coverage.py`(27)、`tests/test_health_service_unit.py`(42)、
`tests/test_data_access_service_unit.py`(30)、`tests/test_analysis_engine_adapters_unit.py`(56)。
**注**：`data_access_service` 的写湖护栏用例为**新增非重复**场景（护栏本身未被削弱）；7 个分析引擎适配器沿
`tests/test_more_analysis_engine_regressions.py` 既有的 orchestrator-stub 模式（不触网、不读真实数据湖）。

**层间格局变化**：`services/` 由**历史最弱层**（第三轮口径 63.8%）升至 **79.3–79.7%** →
**当前最弱层变为 `hands/` 64.19%**（两口径一致）。

### 7.10.3 真 bug：`{}` 风格占位符被当作 `%` 风格参数（6 处，同一文件）

**发现方式**：Agent A 新增的 `validation_service` 用例在**本机 `.venv` 全绿**，在**CI 等价解释器上 5 例失败**。
这是"本地绿、CI 红"的又一实例（延续 §7.7 的主题），故按第六轮纪律取证、修复、加守卫。

**根因**：`services/validation_service.py` 的 6 处告警把 **`{}` 风格**当成了 **`%` 风格**参数：

```python
logger.warning("Max drawdown validation failed: calculated={}, expected={}", calc_value, exp_value)
```

stdlib `logging` 做 `msg % args`：消息里没有 `%` 转换符而多出 2 个参数 → `TypeError: not all arguments converted during string formatting`。

**两重后果**：
1. **与解释器无关的生产后果**：本该打印"哪一项校验失败"的告警，被替换成 stderr 上的 `--- Logging error ---` 回溯（告警丢失）。
2. **可升级为功能缺陷**：若 handler 让格式化异常向上冒泡（**捕获型/结构化 handler 即如此**——这正是 CI 解释器上的表现），
   异常会被该方法自身的 `except (ValueError, KeyError, TypeError)` 吞掉并走通用错误分支 →
   **恰好在校验失败时 `results` 变成空字典**，调用方再也拿不到逐项诊断。

**为何本机绿**：本机 pytest 捕获 handler 吞掉了格式化异常，代码"看起来"正常。**缺陷一直在，只是被环境掩盖。**

**修复**：6 处 `{}` → `%s`（消息文本逐字不变）；**不改**其它语义、**不改** `except` 分支。

**防复发守卫**（新增 `tests/test_no_logging_format_mismatch.py`，AST 静态扫描 `src/uniquant/**`）：
取日志方法（`debug/info/warning/warn/error/critical/exception`）的**第一个位置参数**，若是字符串**字面量**则统计
`%` 转换符数量并与其余位置参数数量比较，**不相等即失败**；含**正对照**（必须命中 `{}`-当-参数的原型）
与**负对照 9 例**（`%%` 转义、`%.2f`、`%(name)s` 映射键、`"Progress: 50% of universe"` 这类文本百分号、
`exc_info=` 关键字、`logger.log(level, msg, …)` 消息在第 2 位 → 不误报）。
**端到端反证**：把 `validation_service.py` 第 93 行临时改回 `{}` → 守卫**必红并点名** `validation_service.py:93 -> logger.warning() placeholders=0 args=2`；恢复后复绿。

**同类兄弟清剿**：以同一规则扫描全 `src/` → 修复后 **0 命中**（该缺陷类**仅**存在于这一个文件，无遗漏）。

### 7.10.4 第七轮验证（本工作树实测）

| 口径 | 命令 | 结果 |
|---|---|---|
| 本机全量（含数据湖 + `czsc`） | `.venv/bin/python -m pytest tests/ -q -o addopts="" -n auto --timeout=900` | **3,464 passed / 2 skipped / 0 failed / 0 error**（收集 3,466；第六轮 3,240 → **+224**） |
| CI 等价（三 mount；`.[all,dev]` **真实依赖集**，**无** `czsc`） | 见 §7.6 配方三个 `mount --bind` + `/tmp/opencode/civenv/bin/python` | **3,278 passed / 165 skipped / 0 failed / 0 error**（收集 3,443；第六轮 3,052 → **+226**）——**这才是真实 CI 的数字** |
| 本机覆盖率 | `-n auto --cov` | **78.72%**（25,854 / 5,501）（第六轮 76.08% → 剪除 76.55% → 补测 **78.72%**） |
| CI 等价覆盖率（`.[all,dev]` 依赖集） | `-n auto --cov --cov-fail-under=74` | **77.47%**（25,854 / 5,824）≥ 74 → **余量 +3.47 pt**（第六轮仅 **+0.57 pt**，§7.9 的风险提示已解除） |
| 层间覆盖率（CI 口径） | 同上报告聚合 | `services` **79.34%** / `data` 92.95% / `signal` 91.06% / `research` 94.32% / `shared` 87.11% / `risk` 73.14% / `brain` 69.17% / **`hands` 64.19%（现最弱）** |
| 定向：新增测试 | `pytest tests/test_{data_quality,stock_query,validation}_service*.py tests/test_health_service_unit.py tests/test_data_access_service_unit.py tests/test_analysis_engine_adapters_unit.py` | **215 passed** |
| 防复发守卫 | `pytest tests/test_no_logging_format_mismatch.py` | **3 passed**（含正/负对照） |
| `ruff` | `ruff check src/uniquant/ tests/ scripts/` | **All checks passed!** |
| 证据链 | `python scripts/maintenance/evidence_manifest.py verify` | **no drift** |
| SSOT 未被测试污染 | `ls -l --time-style=full-iso data/all_stock_codes.csv` | `2026-08-19 12:21:53`，**未变** |

**新增测试纪律**：本轮新增 215 个用例全在**新文件**中，未削弱任何既有断言；删除的用例仅针对**已剪除**的门面类。

---

## 附录 A：可复现命令

```bash
# 0) 基线
git rev-parse HEAD && git status --short

# 1) 规模
find src/uniquant -name '*.py' | wc -l
find src/uniquant -name '*.py' -exec cat {} + | wc -l

# 2) 测试收集与全量
.venv/bin/python -m pytest tests/ --collect-only -o addopts="" -q | tail -2
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

# 10) 第四轮 CI 真绿化：在私有 mount 命名空间里复现 CI 的数据环境
#     （CI 上只有 2 个 tracked CSV，没有 data/lake、data/fq、本地通达信）
REPO=/home/james/Documents/Project/UniQuant
rm -rf /tmp/opencode/ci_data /tmp/opencode/ci_empty /tmp/opencode/ci_empty_cnnm
mkdir -p /tmp/opencode/ci_data /tmp/opencode/ci_empty /tmp/opencode/ci_empty_cnnm
cp $REPO/data/all_stock_codes.csv $REPO/data/qualified_universe.csv /tmp/opencode/ci_data/
# 10a) CI `test` 作业口径 → 期望 0 failed / 0 error
#      ⚠️ 必须用与 CI 相同的依赖集（`.[all,dev]`，**不含未声明的 czsc**）才等价：
#        .venv 含手工装的 czsc → 2 skipped / 收集 3466（**非** CI 口径；第七轮）
#        真实 CI 依赖集       → 165 skipped / 收集 3443（见 §7.9 更正 + §7.10.4）
unshare -rm --propagation private sh -c '
  mount --bind /tmp/opencode/ci_data       '"$REPO"'/data
  mount --bind /tmp/opencode/ci_empty      /home/james/.local/share/tdxcfv
  mount --bind /tmp/opencode/ci_empty_cnnm /home/james/Documents/Project/CNNM
  cd '"$REPO"' && /tmp/opencode/civenv/bin/python -m pytest tests/ -q --tb=short
'
# 10b) CI `coverage` 作业口径 → 期望 77.47% ≥ 74（真实 CI 依赖集；第七轮，余量 +3.47 pt）
unshare -rm --propagation private sh -c '
  mount --bind /tmp/opencode/ci_data       '"$REPO"'/data
  mount --bind /tmp/opencode/ci_empty      /home/james/.local/share/tdxcfv
  mount --bind /tmp/opencode/ci_empty_cnnm /home/james/Documents/Project/CNNM
  cd '"$REPO"' && /tmp/opencode/civenv/bin/python -m pytest tests/ -q -n auto --timeout=900 \
    --cov --cov-report=term:skip-covered --cov-fail-under=74
'
# 标记面（本机含数据湖时为 no-op，用例全部真跑）
grep -rn "requires_lake\|requires_futures_lake\|requires_gbbq" tests/ --include='*.py'
# 11) 防回归守卫：`tests/` 不得出现硬编码开发机绝对路径（§7.7 的真凶）
#     端到端反证：临时放入 tests/test_zz_temp_planted_path.py 内容 `sys.path.insert(0, "/home/james/...")`
#     → 守卫必红；删除后复绿。
.venv/bin/python -m pytest tests/test_no_dev_absolute_paths.py tests/test_no_import_time_env_mutation.py -q

# 12) 第六轮：§7.4 十项处置的定向回归（2026-10-16）
.venv/bin/python -m pytest tests/test_import_financial.py tests/data/test_futures_and_financial_import.py \
    tests/data/test_baostock_and_metadata.py tests/data/test_sources_and_factor_utils.py \
    tests/test_mootdx_local_bugs.py tests/test_error_handling.py tests/test_error_handling_additional.py -q
# 安全关键：确认 SSOT 未被测试污染（mtime 应保持 2026-08-19）
ls -l --time-style=full-iso data/all_stock_codes.csv
# §7.9：证明真实 CI 依赖集里没有 czsc（故其 4 个测试模块不被收集）
.venv/bin/pip show czsc | grep -E "^(Required-by)"      # → Required-by: rs_czsc（未被本项目声明）
grep -n "czsc" pyproject.toml                            # → 仅一条 ruff per-file-ignore，无依赖声明

# 13) 第七轮：生产孤岛剪除 + `services/` 层覆盖率补测 + 日志格式化真 bug（2026-10-17）
# 13a) 剪除后生产孤岛应为零残留（仅剩 __init__ 的理由注记与测试注释）
rg -n "macro_service|technical_service|signal_service|MacroService|TechnicalService|SignalService" src/ tests/ scripts/
.venv/bin/python -c "import uniquant.services.analysis as a; print(a.__all__)"   # → []
# 13b) 已剪除文件在 HEAD 中仍可取证（HEAD~1 侧），确认"功能已由在线引擎承接"
ls src/uniquant/services/analysis/*.py
# 13c) 覆盖率补测（215 例，全在新文件）
.venv/bin/python -m pytest tests/test_data_quality_service_unit.py tests/test_stock_query_service_unit.py \
    tests/test_validation_service_coverage.py tests/test_health_service_unit.py \
    tests/test_data_access_service_unit.py tests/test_analysis_engine_adapters_unit.py -q -p no:cacheprovider
# 13d) 日志格式化守卫（含正/负对照）
.venv/bin/python -m pytest tests/test_no_logging_format_mismatch.py -q -p no:cacheprovider
# 端到端反证：把 validation_service.py:93 的 %s 改回 {} → 守卫必红并点名 file:line；恢复后复绿
#      `sed -i 's/calculated=%s, expected=%s/calculated={}, expected={}/' src/uniquant/services/validation_service.py`（仅第 93 行那处）
# 13e) 全量（本机 / CI 等价）与覆盖率；期望见 §7.10.4（dev 3464 passed / CI 3278 passed；dev 78.72% / CI 77.47%）
```

---

## 附录 B：与历史文档的冲突声明

| 声明来源 | 声明 | 实测 |
|---|---|---|
| `AGENTS.md` | ruff 0（src+tests+scripts） | **31 错** |
| 提交 `7509c2a` | pytest 2530 passed, 0 failed | 干净环境 **4 failed**；**真实 CI ~130 failed**（数据湖依赖）；且该提交在 CI 上 **`Test with pytest` 从未运行**（被 **ruff lint 失败** skip）——见 §7.7 三因账 |
| `AGENTS.md`（顶部指令） | 先读根目录 `CLAUDE.md`（10 条规则） | **文件不存在** |
| `README.md` | v0.3 / 44 文件 / 12.6K LOC | 实际 **234 文件 / 58.8K LOC** |
| `QTR_OS_REFACTORING_BLUEPRINT` | LPPL 从仲裁优先级/FORCE_EXIT 切除 | `arbitrator.py:29` 仍 `lppl:0` |
| `QTR_OS_REFACTORING_BLUEPRINT` | 四级门禁"完成落地并验证通过" | 捷径路径伪造输入且崩溃 |

> **更新（2026-10-16）**：上表第 1、2、5、6 行涉及的偏差**已在第一轮修复**——`ruff` 归零、`ENGINE_PRIORITY["lppl"]` 降为 99、四级门禁改为诚实拒绝伪造输入。第 3、4 行（缺失 `CLAUDE.md`、`README.md` 漂移）**已在第二轮 P1-2 修复**——根因是根 `.gitignore` 的 `/*.md` 静默忽略根级 markdown（故该文件"曾经写过却从未提交"），现已补 `!/CLAUDE.md` 并新建**逐条标注出处**的规则文件；`README.md` 已整体重写、`docs/index.md` 已更新口径。详见 §6。
> **第二轮/第三轮的"CI 已绿"表述不成立**：真正的 CI 失败面直到**第四轮**才被定位——`/tmp` 依赖（4 例）只是其中一小部分，主体是约 **130** 个硬依赖本地数据湖/GBBQ/本地通达信的用例。第四轮以 `requires_lake` / `requires_futures_lake` / `requires_gbbq` 三标记 + 集中跳过钩子收口；**但该轮仍未使 CI 变绿**——真实 CI 在 pytest **收集期**就被硬编码的开发机兄弟仓路径中断（`ModuleNotFoundError: order_state_machine` → exit 2 → 零用例执行），直到 **§7.7（第五轮）** 才修掉。三因串联的完整账见 §7.7。
>
> **⚠️ 更早的假绿**：run `38398996210`（`7509c2a`）失败在 **Lint with ruff** 步骤，其 `Test with pytest` 是 **skipped**——即 2026-10-13 的 `7509c2a` 提交信息里"pytest 2530 passed, 0 failed"从未在 CI 上真实发生过。上表第 2 行的实测栏据此更正。
>
> **⚠️ 第六轮更正（"CI 口径"的自我打假，2026-10-16）**：第四/五轮多处记录的
> "CI 口径 = **3,081 passed / 151 skipped / 收集 3,232**、coverage **75.57%**"**并非 CI 口径**——
> 它是在装了 `czsc`（**未在 `pyproject.toml` 声明**、由开发机手工安装的 `rs_czsc` 带入）的解释器上测得的。
> 真实 CI 执行 `pip install -e ".[all,dev]"`，**没有 `czsc`** → 4 个 `importorskip("czsc")` 模块整块不被收集（少 30 例）、
> `test_brain_boundary_qa.py` 再跳 9 例 → **3,052 passed / 164 skipped / 0 failed / 0 error（收集 3,216）、coverage 74.57%**。
> **教训**：报"CI 口径"必须连同**依赖集**一起报；只报"CI 等价"而隐含"本机装了什么"是会骗人的。详见 §7.9。
>
> **⚠️ 第七轮更正（2026-10-17）**：第六轮记录的"**3,052 passed / 164 skipped / 收集 3,216**、coverage **74.57%**"
> 是本轮之前的真值；第七轮剪除 3 个生产孤岛（整包语句 26,268 → **25,854**）并新增 **215** 个覆盖用例后，
> **真实 CI 口径变为 3,278 passed / 165 skipped / 0 failed / 0 error（收集 3,443）、coverage 77.47%**，
> 门限 74 的余量由 **+0.57 pt 升至 +3.47 pt**。同时更正一处**"本地绿、CI 红"**的隐藏缺陷：
> `services/validation_service.py` 的 6 处 `{}`-当-`%`-参数日志在 CI 解释器上会使校验失败路径**返回空 `results`**
> （本机被捕获 handler 掩盖）——已修复并加 AST 守卫锁死（§7.10.3）。**层间最弱层由 `services/` 变为 `hands/` 64.19%**。

---

*报告结束。所有结论均可由附录 A 命令在当前工作树复现。*
