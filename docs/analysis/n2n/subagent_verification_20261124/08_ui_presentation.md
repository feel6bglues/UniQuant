# 08 UI 展示模块 N2N 独立子代理验证报告

> **验证基线**：git HEAD = `b1d2415`（工作树）· UI 模块最后提交 `dbcd122`
> **验证人**：独立子代理（未参与既有报告撰写，先独立分析后交叉复核）
> **验证日期**：2026-11-24
> **分析范围**：`src/uniquant/ui/`（8 文件, 3,400 行）
> **方法**：逐节点 Name-to-Name 点对点追踪 + 运行路径推演 + 既有报告交叉复核

---

## ① 执行摘要

**健康度评级：D（存在多个确定性渲染崩溃缺陷 + 一处 Rule 4 伪造数据违反）**

独立分析发现 **1 个 CRITICAL、7 个 HIGH、6 个 MEDIUM、5 个 LOW** 问题（详见 §④）。

核心结论：

1. **UI 模块存在多处"确定性渲染崩溃"缺陷**——多个渲染路径在真实运行时会抛
   `KeyError / TypeError / AttributeError`。既有 Claude 报告在 §7 声明
   "CRITICAL: 无, HIGH: 无"，但本独立验证实测发现至少 **5 个 HIGH 级确定性崩溃**：
   - `render_scan_config_panel()` 返回值与 `dashboard.py` 消费键不一致 → `KeyError: 'scan_mode'`
   - `render_stock_rankings()` 签名(1参) 与调用(2参) 不匹配 → `TypeError`
   - `plot_czsc_full_chart()` 签名 `(symbol, czsc_data)` 与调用 `df=/bi_list=...` 不匹配 → `TypeError`
   - `AssetManager` 缺少 `run_stress_scenarios()` / `compute_drawdown_metrics()` → `AttributeError`
   - `validate_symbol()` 长度校验错误（要求 10 字符，实际合法 A 股代码为 9 字符）→ 拒绝一切合法输入

2. **违反 Rule 4（禁止伪造数据）**：`AssetManager.analyze_macro_health` 的 `mock` 参数默认值为
   `True`（`manager_logic.py:121`），`dashboard.py:340` 的宏观驾驶舱调用未显式关闭 mock；
   当真实收益数据缺失时 `macro_analysis_engine.py:78-85` 会用 `np.random` 生成**随机替代数据**并返回
   `regime="NORMAL"`，而 `dashboard.py:336` 却向用户声明"以下指标**基于真实市场数据计算**"。
   这是典型的 fail-open 呈现 + 数据伪造，与任务书重点核查项直接相关。

3. **LPPL 未标注 "diagnostic_only / 已被证伪"**：`lppl_visualizer.py:342` 的图注只显示
   "置信度/风险等级"；`dashboard.py:1260-1263` 甚至给出可执行建议
   "⚠️ 泡沫警报：建议减仓或设置严格止损 / ✅ 市场正常：可按既定策略操作"。
   与 `AGENTS.md` Round 1 "LPPL 降为遥测" 的定级矛盾，存在误导性可执行展示风险。

4. **任务书描述的 N2N 主路径与实际代码不符**：任务书给的主路径
   `ServiceContainer → StreamlitApp.render → AnalysisService.run_ticker_analysis() → PipelineResult →
   PlotlyFigure → st.plotly_chart()` **在 UI 模块中不存在**。`dashboard.py` 从未调用
   `run_ticker_analysis()`，也从不消费 `PipelineResult` / `PlotlyFigure`；实际 UI 绕过分析管道，
   直接调用 `czsc_engine.run_czsc_analysis()`（`dashboard.py:639`）或门面方法
   `generate_report()`。回测结果（Sharpe/胜率/profit_factor/收益曲线）在 UI **完全缺席**。

5. **交叉复核**：既有 Claude 报告（基线 434aab1）对**架构层**（门面/组件化/Kill Switch/超时保护）
   的描述准确，但其"无 CRITICAL / 无 HIGH"的结论**被本验证证伪**——报告漏检了全部
   5+ 个确定性渲染崩溃缺陷与 mock 伪造数据问题。报告自评 LOW 的"简化版信号"
   （L1）与本验证的分级分歧（我判 MEDIUM，与第三方资深交易员评审意见一致）。

---

## ② 五问逐节点答案

### Q1 —— Name 定义（命名与契约）

| 节点 | 定义 | 位置 | 评估 |
|---|---|---|---|
| `AssetManager` 门面 | 组合 5 服务：`data_service`/`analysis_service`/`portfolio_service`/`portfolio_analytics_service`/`report_service` | `manager_logic.py:46-52` | ✅ 契约清晰，依赖倒置（构造注入） |
| `FSMStateInfo` | 5 字段数据类 | `manager_logic.py:22-29` | ✅ 契约清晰 |
| 组件命名 | 全部 `render_*` 前缀 | `components.py` | ✅ 规范 |
| `ModuleHealthChecker` | 8 模块导入探针 | `health_check.py:24-50` | ✅ 职责单一 |
| `LPPLVisualizer` | 计算+绘制，返回 dict | `lppl_visualizer.py:15-119` | ✅ 契约清晰 |
| **`validate_symbol`** | 校验函数（**契约有误**） | `dashboard.py:273-283` | ❌ **长度契约错误**：要求 `len==10`（`:281`），但合法 A 股代码 `600519.SH` = 9 字符，**拒绝一切合法输入**；错误消息 "应为 6 位数字 + .SH/.SZ"（=9 字符）与校验（=10 字符）自相矛盾 |

> 注：任务书提到 `ui_manager.py/manager_logic.py` 为 AssetManager 门面，但仓库中**不存在 `ui_manager.py`**；
> 门面实际位于 `manager_logic.py`。文件清单与既有报告一致（8 文件）。

### Q2 —— Name 映射（数据流转映射）

| 流转 | 源 | 目标 | 位置 | 评估 |
|---|---|---|---|---|
| `query_data_lake` | `DataService.query_lake()` | `enrich_lake_data()` 加衍生列 | `manager_logic.py:104-118, 145-177` | ✅ 委托清晰 |
| `enrich_lake_data` 信号计算 | `close>open` | `signal` 列 | `manager_logic.py:157` | ⚠️ **简化版**，非真实引擎输出（详见 M4） |
| `enrich_lake_data` CZSC 计算 | `close>high*0.9` | `czsc_stat` 列 | `manager_logic.py:167` | ⚠️ **简化版**（详见 M4） |
| `get_fsm_state` | `get_real_kline_data()` | `FSM().infer_state()` → `FSMStateInfo` | `manager_logic.py:304-346` | ✅ 每次新实例，状态隔离 |
| 报告预览 | `_read_report()` 回调 | `markdown.markdown()` → HTML | `manager_report_service.py:67-87` | ✅ 委托清晰 |
| **UI 主分析路径** | —— | —— | `dashboard.py` | ❌ **不存在**：`run_ticker_analysis()` / `PipelineResult` / `PlotlyFigure` 均未被 UI 消费；UI 绕过分析管道直连引擎（`dashboard.py:639`） |
| **回测结果呈现** | —— | —— | `dashboard.py` | ❌ **完全缺席**：无 Sharpe/胜率/profit_factor/回测收益曲线展示 |

### Q3 —— Name 传播（依赖链追踪）

```
dashboard.py (Streamlit 入口, 1568 行)
  ├─ AssetManager (门面) ── DataService / AnalysisService / PortfolioService
  │                          └─ ManagerPortfolioAnalyticsService / ManagerReportService
  ├─ components.py (render_*) ── st.metric/st.dataframe/st.components.v1.html
  ├─ LPPLVisualizer ── create_lppl_engine()/create_lppl_data_service()
  ├─ ModuleHealthChecker ── importlib.import_module(8 引擎路径)
  └─ (直连) czsc_engine = ServiceContainer...get("engine_factory").czsc   # dashboard.py:629-639
```

**关键传播断裂**：
- `dashboard.py:431-438` 读取 `scan_config['scan_mode']/['holding_period']/['max_stocks']`，
  但 `render_scan_config_panel()`（`components.py:240-250`）只返回 `{top_n, factors}` → **传播到 `KeyError`**。
- `dashboard.py:454-457, 479-482` 以 2 个位置参数调用 `render_stock_rankings()`，
  而函数签名只接受 1 个（`components.py:253`）→ **传播到 `TypeError`**。
- `dashboard.py:675-681` 以 `df=/bi_list=/zhongshu_list=/bs_points=/ticker=` 关键字调用
  `plot_czsc_full_chart()`，签名却为 `(symbol, czsc_data)`（`components.py:350`）→ **传播到 `TypeError`**。
- `dashboard.py:1539, 1555` 调用 `asset_mgr.run_stress_scenarios()` / `asset_mgr.compute_drawdown_metrics()`，
  但 `AssetManager` **未定义**这两个方法（`manager_logic.py` 全文件仅 `run_stress_test` 于 `:509`）→ **传播到 `AttributeError`**。

### Q4 —— Name 变异（边界条件与异常）

| 边界 | 处理 | 位置 | 评估 |
|---|---|---|---|
| 空数据 | 组件层 `if not data` 守卫 | `components.py` 各 `render_*` | ✅ 普遍到位 |
| 依赖缺失 | markdown→提示 / weasyprint→空串 | `manager_report_service.py:82-84, 95-97` | ✅ 优雅降级 |
| 超时 | `SHORT_TIMEOUT` 检查 | `manager_logic.py:270-271` | ✅ 存在，但配合 mock=True（见 H1） |
| 数据缺失 | **mock=True → 随机替代** | `macro_analysis_engine.py:78-85` | ❌ **Rule 4 违反**（fail-open 伪造） |
| 用户输入非法 | `validate_symbol`/`validate_date_range` | `dashboard.py:273-294` | ⚠️ 符号校验**长度错误**（C1） |
| 引擎失败 | `run_czsc_analysis` 用 `if czsc_engine else None` | `dashboard.py:639` | ⚠️ 引擎缺失时静默 None，无 UI 提示 |

### Q5 —— Name 治理（可观测性与可测试性）

| 维度 | 现状 | 位置 | 评估 |
|---|---|---|---|
| 结构化日志 | `get_logger("AssetManager")` + `%s` 占位 | `manager_logic.py:19` 等 | ✅ |
| 错误分类 | ValueError/TypeError → error；Runtime/IO/Key → critical+exc_info | `manager_logic.py:113-118` | ✅ 清晰 |
| 可测试性 | 门面构造注入、`get_time_provider()` 可冻结 | `manager_logic.py:46-52` | ✅ |
| 缓存失效 | `@st.cache_data` 大量使用，但**无 `.clear()`** | `dashboard.py:208-233` | ❌ add/remove 持仓后 `get_portfolio_data()` 不失效（M3） |
| 死参数 | `render_health_metrics(kb_ok)` 声明但从不渲染 | `components.py:467-486` | ⚠️ LOW（L2） |

---

## ③ 端到端路径追踪（≥3 条，含 1 条异常）

### 路径 A（正常）：SQL 选股 → 数据湖查询 → 渲染（但带简化信号风险）

```
用户输入 SQL 条件 ("close > 50")
  → dashboard.py:489  st.text_input
  → dashboard.py:496  get_scan_results(condition)   [@st.cache_data ttl=1800, :208]
  → dashboard.py:212  asset_mgr.query_data_lake(condition)
  → manager_logic.py:108  data_service.query_lake()
  → manager_logic.py:112  enrich_lake_data(df_raw)
      ├─ :157 signal = close>open → BUY/WAIT        ⚠️ 简化版
      ├─ :167 czsc_stat = close>high*0.9 → 3rd_BUY  ⚠️ 简化版
      └─ :175 重命名 Code/Name/Signal/CZSC/Price/Volume/Date
  → dashboard.py:501-525  AgGrid / fallback_aggrid 渲染
  → 用户看到 "Signal=BUY"/"CZSC=3rd_BUY" 列（无"仅供参考"标注）   [M4]
```
**结果**：路径可运行，但 Signal/CZSC 列是简化启发式而非真实引擎输出，且无任何免责标注。

### 路径 B（异常/用户输入）：深度几何分析默认代码 → 校验拒绝 → 功能死区

```
用户进入"深度几何分析" tab（默认 ticker="600519.SH", dashboard.py:573）
  → dashboard.py:578-583  validate_symbol("600519.SH")
  → dashboard.py:281  len(symbol) != 10  → True（"600519.SH" 仅 9 字符）
  → raise ValueError("证券代码格式不正确...")
  → dashboard.py:582  st.error("❌ 证券代码格式不正确")   # 合法代码被误判非法
  → dashboard.py:611  validate_symbol(ticker) 再次 raise
  → dashboard.py:614-616  except ValueError → df_g = pd.DataFrame() 空
  → dashboard.py:667  st.info("暂无CZSC分析数据")  → CZSC 分析永远无法执行   [C1]
```
**结果**：深度几何分析（CZSC 核心引擎路径）对**一切合法 A 股输入**失效——默认代码本身就触发校验失败。

### 路径 C（异常/引擎-扫描）：全市场扫描按钮 → 配置键缺失 → 崩溃

```
用户点击"🚀 开始全市场扫描"（dashboard.py:431）
  → dashboard.py:428  scan_config = render_scan_config_panel()
  → components.py:240-250  return {"top_n", "factors"}    # 无 scan_mode 键
  → dashboard.py:434  scan_config["scan_mode"]  → KeyError: 'scan_mode'   [H2]
  → （若绕过）dashboard.py:454  render_stock_rankings(top, bottom)  → TypeError  [H3]
```
**结果**：全市场扫描渲染路径在真实运行即崩溃，`KeyError` + `TypeError` 双重失败。

### 路径 D（异常/门面缺方法）：风险面板压力场景 → 缺方法 → 崩溃

```
用户点击压力场景按钮（dashboard.py:1536-1544）
  → dashboard.py:1539  asset_mgr.run_stress_scenarios({"equity_curve": ...}, ...)
  → AttributeError: 'AssetManager' object has no attribute 'run_stress_scenarios'   [H5]
  → 同理 dashboard.py:1555  compute_drawdown_metrics()  → AttributeError
```
**结果**：风险管理 tab 5（压力场景&回撤）两个交互均因门面缺方法而崩溃。

---

## ④ 问题清单（分级 + 证据）

### CRITICAL

**C1 — `validate_symbol` 长度契约错误，拒绝一切合法 A 股代码**
- 位置：`dashboard.py:281`（`if len(symbol) != 10`）
- 证据：合法代码 `600519.SH`/`000001.SZ` = 9 字符（6 数字 + `.` + 2 字母）；默认输入
  `dashboard.py:374` 即 `000001.SZ`、`:573` 即 `600519.SH` 均为 9 字符 → 恒触发 `:281` raise；
  错误消息 `:282` "应为 6 位数字 + .SH/.SZ"（=9 字符）与校验值（=10）自相矛盾。
- 影响：**深度几何分析（CZSC 核心路径）对所有合法输入失效**（`:611` → `:614` 空 DataFrame）；
  下载校验（`:887`/`:895`）同样误拒合法代码。
- 修复：`len(symbol) != 9`（或改用 `re.fullmatch(r"\d{6}\.(SH|SZ)")`）。

### HIGH

**H1 — 宏观驾驶舱用 `mock=True` 伪造数据并声明为"真实数据"（Rule 4 违反）**
- 位置：`manager_logic.py:121`（`analyze_macro_health(self, mock=True)` 默认值）；
  `dashboard.py:340`（`asset_mgr.analyze_macro_health()` 未显式关闭 mock）；
  `manager_logic.py:268`（`_fetch_macro_health_safe` 同样硬编码 `mock=True`）；
  `macro_analysis_engine.py:78-85`（`mock=True` 且 `returns.empty` 时 `np.random.default_rng(seed).normal(...)` 生成**随机替代收益**并返回 `regime="NORMAL"`）。
- 证据：`dashboard.py:336` 明确向用户声明 "以下指标**基于真实市场数据计算**"；但 mock 默认开启，
  数据缺失时自动伪造随机数据并回落到 `NORMAL`，UI 无任何"数据缺失/伪造"提示。
- 影响：交易员看到"市场状态 NORMAL / 宏观环境分析完成"无法区分是真实结果还是拉取失败后的
  随机占位；**fail-open 呈现 + 数据伪造**，直接违反 Rule 4（缺失输入必须显式失败）。
- 修复：将 `mock` 默认改为 `False`；`dashboard.py` 显式 `mock=False`；伪造路径返回
  `status="failed"` 并让 UI 显示 `st.error("宏观数据不可用")`，绝不回落到 NORMAL。

**H2 — 扫描配置键缺失 → `KeyError: 'scan_mode'`**
- 位置：`dashboard.py:434-438` 读取 `scan_config["scan_mode"/"holding_period"/"max_stocks"]`；
  但 `render_scan_config_panel()`（`components.py:240-250`）只返回 `{"top_n", "factors"}`。
- 影响：点击"开始全市场扫描"即抛 `KeyError`，扫描 tab 无法使用。
- 修复：`render_scan_config_panel()` 补齐 `scan_mode/holding_period/max_stocks` 键，
  或 `dashboard.py` 改用 `scan_config.get(...)` 并提供默认值。

**H3 — `render_stock_rankings` 参数个数不匹配 → `TypeError`**
- 位置：`dashboard.py:454-457, 479-482` 以 2 个位置参数调用；
  `components.py:253` 签名 `def render_stock_rankings(rankings: pd.DataFrame)`（仅 1 参）。
- 影响：扫描结果展示阶段抛 `TypeError`（扫描成功但无法展示 Top/Bottom）。
- 修复：改为单参数调用（分别渲染 top/bottom），或扩展签名。

**H4 — `plot_czsc_full_chart` 关键字参数不匹配 → `TypeError`**
- 位置：`dashboard.py:675-681` 以 `df=/bi_list=/zhongshu_list=/bs_points=/ticker=` 关键字调用；
  `components.py:350` 签名 `def plot_czsc_full_chart(symbol: str, czsc_data: Dict[str, Any])`。
- 影响：K 线图表子 tab 渲染即抛 `TypeError`。
- 修复：对齐签名（`plot_czsc_full_chart(df=df_g, ticker=ticker)` 或改实现）。

**H5 — `AssetManager` 缺失两个被 UI 调用的方法 → `AttributeError`**
- 位置：`dashboard.py:1539` `asset_mgr.run_stress_scenarios(...)`；`dashboard.py:1555`
  `asset_mgr.compute_drawdown_metrics(...)`；`manager_logic.py` 全文件仅定义 `run_stress_test`（`:509`），
  无 `run_stress_scenarios` / `compute_drawdown_metrics`。
- 影响：风险管理 tab 5 两个交互按钮均抛 `AttributeError`。
- 修复：在 `AssetManager` 补委托方法，或改调 `run_stress_test`/`portfolio_service` 既有方法。

**H6 — LPPL 未标注 "diagnostic_only / 已被证伪"，反而给出可执行建议**
- 位置：`lppl_visualizer.py:342`（图注仅 "置信度/风险等级"，无 diagnostic_only/证伪标注）；
  `dashboard.py:1258-1263`（"💡 分析建议"：`is_bubble` → "泡沫警报：建议减仓或设置严格止损"，
  否则 → "市场正常：可按既定策略操作"）。
- 证据：`AGENTS.md` Round 1 明确定级 "**LPPL 降为遥测**"；但 UI 将其呈现为可据以决策的实时信号。
- 影响：交易员可能据"建议减仓"直接下单，与已证伪的科研定级冲突。
- 修复：在 LPPL 面板与图注显著标注 `⚠️ diagnostic_only —— 模型已被证伪，仅供研究参考，不作为交易依据`；
  删除/弱化"建议减仓/可按既定策略操作"可执行措辞。

**H7 — 回测结果在 UI 完全缺席（N2N 主路径未落地）**
- 位置：`dashboard.py` 全文件无 `run_ticker_analysis()` / `PipelineResult` / `PlotlyFigure` /
  回测收益曲线 / Sharpe / 胜率 / profit_factor 的展示（`grep` 仅在 `:1525` 命中组合收益曲线，
  非回测引擎输出）。
- 影响：任务书描述的 N2N 主路径（AnalysisService → PipelineResult → PlotlyFigure → st.plotly_chart）
  未实现；**回测结果对交易员零呈现**，无法评估"看起来赚钱但不可复现"风险。
- 修复：接入 `AnalysisService.run_ticker_analysis()` 返回的 `PipelineResult`，渲染回测指标
  （Sharpe/胜率/profit_factor/资金曲线）并标注成本/滑点假设与"回测≠可复现实盘"免责提示。

### MEDIUM

**M1 — `render_tech_signals_summary` 类型不匹配 → `AttributeError`**
- 位置：`dashboard.py:460-462` 传入 `scan_result.get("tech_signals", pd.DataFrame())`（来自
  `manager_logic.py:483` 的 `pipeline.screener.tech_signals`，类型为 DataFrame）；
  `components.py:263` 签名 `signals: Dict[str, Any]`，内部 `signals.get("buy_signals", [])`（`:271`）。
- 影响：DataFrame 无 `.get` → 扫描结果技术信号区抛 `AttributeError`。
- 修复：统一类型（dict 或 DataFrame），或按 `isinstance` 分支。

**M2 — `render_stress_test_results` 与 `run_stress_test` 返回结构不匹配 → `AttributeError`**
- 位置：`manager_portfolio_analytics_service.py:107` 返回 `"scenarios": scenarios`（**列表**）；
  `components.py:218-220` 做 `stress_result.get("scenarios", {})` 后 `list(scenarios.items())`。
- 影响：列表无 `.items()` → 风险 tab 3 压力测试结果展示抛 `AttributeError`。
- 修复：组件应读 `scenario_results`（字典），或服务返回 `{scenario: result}` 字典。

**M3 — 缓存失效缺失 → 持仓增删后 UI 显示过期数据**
- 位置：`dashboard.py:208-233` 多个 `@st.cache_data`（`get_portfolio_data` ttl=3600、
  `get_kline_data` ttl=3600）；`dashboard.py:831`（`remove_position` 后 `st.rerun`）、
  `:871`（`add_position` 后 `st.rerun`）、`:899`（`download_stock` 后 `st.rerun`）均**未调用
  `.clear()`**（全文件 `grep '\.clear()'` 零命中）。
- 影响：用户新增/删除持仓后 `st.rerun()`，但 `get_portfolio_data()` 命中 1 小时缓存 →
  组合表仍显示旧数据；下载新行情后 K 线仍显示缓存旧数据。
- 修复：增删/下载后调用 `get_portfolio_data.clear()` / `get_kline_data.clear()`。

**M4 — 数据湖"简化版信号"以真实信号名义展示（分级与既有报告分歧）**
- 位置：`manager_logic.py:157,167`（`signal=close>open→BUY`、`czsc_stat=close>high*0.9→3rd_BUY`）；
  `dashboard.py:501-525` 直接以 `Signal`/`CZSC` 列渲染，无"仅供参考"标注。
- 影响：交易员可能将简化启发式当作真实 FSM/CZSC 信号下单。**我判 MEDIUM**（既有报告判 LOW，
  低估了误导性；与第三方交易员评审意见一致——其判 HIGH，我认为 SQL 选股属次要浏览路径，
  MEDIUM 更公允）。
- 修复：列名改 `Signal_quick`/`CZSC_quick`，或 UI 加"⚠️ 简化版信号，仅供参考，非真实引擎输出"。

**M5 — FSM 状态面板呈现语义可能被误解为可执行交易指令**
- 位置：`components.py:397`（`st.write(f"**可能流转至**: {', '.join(next_states)}")`，
  含 PYRAMID/EXIT）；`manager_logic.py:348-370`（静态状态转换表）。
- 影响：交易员看到 "PYRAMID（加仓）/EXIT（离场）" 未必清楚这仅是状态机推断、非已校验可下单建议。
- 修复：加注 "仅供状态机监控，非交易指令"。

**M6 — `scan_etfs` 硬编码 2024 日期范围 → 数据陈旧**
- 位置：`manager_logic.py:137`（`get_real_kline_data(etf, "20240101", "20241231")`）。
- 影响：ETF 择时扫描恒用 2024 年数据，2026 年运行结果为陈旧/无意义。
- 修复：改用 `get_time_provider()` 动态计算近 N 交易日窗口。

### LOW

**L1 — `dashboard.py` 1,568 行超 800 行软上限**（`CLAUDE.md` Rule 9）
- 位置：`dashboard.py`（1,568 行）。
- 修复：拆分 `dashboard_tabs/` 子模块。

**L2 — `render_health_metrics(kb_ok)` 声明但从不渲染**（死参数）
- 位置：`components.py:467`（参数 `kb_ok: bool = True`），`:471-486` 仅渲染网络/数据湖/引擎/市场状态 4 列，
  `kb_ok` 从未使用。
- 修复：删除参数或新增"熔断"指标列。

**L3 — `is_trading_enabled` fail-open（配置读取失败返回 True）**
- 位置：`manager_logic.py:523-528`（`except Exception: return True`）。
- 影响：配置异常时 UI 显示"交易引擎运行中"，掩盖真实停机态。
- 修复：失败返回 False 并告警。

**L4 — `_fetch_macro_health_safe` 失败回落默认值伪装成正常**
- 位置：`manager_logic.py:257-261`（默认 `{"regime":"NORMAL","ntf_signal":"中性","summary":"宏观环境分析完成"}`）。
- 影响：超时/异常时 UI 显示"宏观环境分析完成/NORMAL"，无法区分真实结果。属 H1 的次级表现。
- 修复：失败返回 `status="failed"` 供 UI 显式提示。

**L5 — `run_analysis` 吞错只返回 bool，丢失错误上下文**
- 位置：`manager_logic.py:291-301`。
- 影响：`generate_report` 失败时 UI 仅显示 "Report generation failed."（`dashboard.py:747`），无根因。
- 修复：返回带 `error` 字段的结构。

---

## ⑤ 交叉复核矩阵（既有报告 `08_ui_presentation_n2n.md`，基线 434aab1）

> 结论口径：**一致** = 本验证支持既有结论；**分歧** = 本验证得出不同判断（附双方证据）；
> **已修复** = 基线后已修复；**仍遗留** = 本验证仍可复现。

| # | 既有结论 | 既有证据 | 本验证判断 | 依据 |
|---|---|---|---|---|
| 1 | AssetManager 门面委托 5 服务，向后兼容，依赖注入 | `manager_logic.py:46-52` | **一致** | 同位置确认 |
| 2 | components.py 只渲染、不含业务规则 | `components.py` 各 `render_*` | **一致** | 确认 |
| 3 | Kill Switch 集成（kill+配置+日志，恢复对称） | `manager_logic.py:530-542` | **一致** | 确认 |
| 4 | 超时保护 `SHORT_TIMEOUT` | `manager_logic.py:270-271` | **一致（但被 H1 削弱）** | 超时检查真实存在，但 mock=True 使"数据缺失"路径伪造而非失败 |
| 5 | 跨股票 FSM 状态隔离（每次新实例） | `manager_logic.py:327` | **一致** | 确认 |
| 6 | 依赖缺失优雅降级（markdown/weasyprint） | `manager_report_service.py:82-84,95-97` | **一致** | 确认 |
| 7 | **CRITICAL: 无 / HIGH: 无** | 既有 §7.1-7.2 | **分歧（证伪）** | 本验证发现 C1 + H2/H3/H4/H5 至少 5 个确定性渲染崩溃；既有报告未检这些签名/键/方法不匹配 |
| 8 | L1 简化版信号（既有判 LOW） | `manager_logic.py:157,167` | **分歧（分级）** | 本验证判 MEDIUM（误导性展示）；与第三方交易员评审"判 HIGH"方向一致，我取 MEDIUM |
| 9 | L2 dashboard.py 1,568 行超上限（既有判 LOW） | `dashboard.py` | **一致** | 确认 |
| 10 | （第三方 H1）mock 默认值伪装正常 | `manager_logic.py:257-261,268` | **一致（深化）** | 本验证进一步确认 `mock=True` 硬编码（`:121`）+ 随机伪造（`macro_analysis_engine.py:78-85`），且 `dashboard.py:336` 宣称"真实数据"——矛盾 |
| 11 | （第三方 H2）回测呈现完全缺席 | 既有 §7 无回测讨论 | **一致** | `grep` 确认 UI 无 `run_ticker_analysis`/`PipelineResult`/`PlotlyFigure`/回测指标 |
| 12 | （第三方 M2）FSM 面板过度解读风险 | `components.py:397` | **一致** | 确认 |
| 13 | 组件空数据保护到位 | `components.py` 各 `if not data` | **一致** | 确认 |
| 14 | 报告元数据正则提取 | `manager_report_service.py:160-162` | **一致** | 确认 |

**关键分歧点**：既有报告 §7 声明"无 CRITICAL / 无 HIGH"，但独立验证发现
**1 个 CRITICAL（C1 校验长度契约）与 7 个 HIGH（H1-H7）**——既有报告把可运行的架构层与
实际渲染正确性混为一谈，漏检了全部渲染路径崩溃与数据伪造问题。
**已修复**：无（基线后 UI 无变更，最后提交 `dbcd122`）。
**仍遗留**：上述 C1/H1-H7/M1-M6 在 HEAD=`b1d2415` 均可复现。

---

## ⑥ 结论与建议

### 结论

UI 模块**架构层**（门面 + 组件化 + 依赖降级 + Kill Switch）设计良好，但**渲染正确性层**
存在系统性缺陷：任务书描述的主 N2N 路径未落地（无 `run_ticker_analysis`/`PipelineResult`/
回测呈现），且多个渲染路径在真实运行时确定性崩溃。更严重的是 H1 违反 Rule 4
（mock 数据伪造 + "真实数据"虚假声明）与 H6（已证伪 LPPL 仍给出可执行建议）。

**健康度评级：D**（架构 B 级，但渲染崩溃 + Rule 4 违反拉低至 D；不可直接上线）。

### 修复优先级建议

1. **P0（立即）**：C1 校验长度、H1 mock 伪造数据、H2-H5 渲染崩溃、H6 LPPL 标注。
2. **P1（本轮）**：H7 回测呈现接入、M1/M2 类型对齐、M3 缓存失效、M4 信号标注、M6 ETF 日期。
3. **P2（后续）**：M5 FSM 语义、L1-L5 治理改进。

### 验证方法说明

- 独立分析在**不读取既有报告**的前提下完成；证据均为 HEAD=`b1d2415` 工作树源码直接核验
  （`grep`/`read` 逐行），无任何虚构。
- 交叉复核仅在独立结论形成后读取既有 `docs/analysis/n2n/08_ui_presentation_n2n.md` 进行对照。
- 建议对 dashboard.py 关键渲染路径补集成测试（`streamlit.testing`）以捕获 H2-H5 类签名/键不匹配。

---

*验证人：独立子代理 · 2026-11-24 · 基线 b1d2415*
