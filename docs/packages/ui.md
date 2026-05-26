# ui -- 用户界面

> **状态:** ⚠️ 部分可用 | **当前文件:** 2/8 | **可用:** dashboard, health_check

`uniquant.ui` 包基于 Streamlit 构建交互式量化分析仪表盘，约 3.3K LOC。包含主仪表盘布局、可复用组件库、LPPL 可视化、系统健康检查、资产管理逻辑门面以及报告/组合分析服务。

公开导出（`__init__.py`）：

- `AssetManager`, `FSMStateInfo`, `Bi`
- `ManagerReportService`
- `ManagerPortfolioAnalyticsService`
- `LPPLVisualizer`
- `ModuleHealthChecker`

---

## 仪表盘

`dashboard.py` 是系统的主入口页面，直接运行即启动 Streamlit 应用。

### 页面配置

```python
st.set_page_config(
    page_title="Alpha-Tactician Pro V1.0 Sovereign",
    layout="wide",
    initial_sidebar_state="expanded",
)
```

暗色主题 CSS 覆盖（背景 `#0e1117`，组件背景 `#1e2130`）。

### 可选依赖

| 依赖 | 用途 | 降级方案 |
|------|------|----------|
| `st_aggrid` | 交互式表格（选择、排序、过滤） | 回退到 `st.dataframe` |
| `streamlit_autorefresh` | 自动刷新（市场交易时段） | 手动刷新 |
| `streamlit_echarts` | ECharts 交互式图表 | 警告提示 |

### 侧边栏

- **数据导入与同步**：上传自选股清单（CSV/TXT），策略标签设置
- **全局风险偏好**：初始总资产、风险偏好系数（1-100%），高风险实验室模式警告（>15%）
- **战术参数配置**：回顾日期、均线窗口组、CZSC 启用开关
- **自动刷新设置**：启用/禁用、刷新间隔（10-300 秒）、仅交易时间刷新（通过 `MarketHours.is_market_open()` 判断）

### 主工作区 Tab 布局

| Tab | 名称 | 功能 |
|-----|------|------|
| 0 | 宏观驾驶舱 | 系统健康状态、反脆弱指标、结构化风险热力图（LPPL tc）、FSM 状态监控 |
| 1 | 策略扫描器 | 全市场因子扫描（ScanPipeline）、SQL 选股（DuckDB）、ETF 择时 |
| 2 | 深度几何分析 | CZSC 结构分析、K 线图表（ECharts）、战术交易计划卡 |
| 3 | 机会跟踪器 | 持仓管理（AgGrid 表格）、手工录入建仓表单 |
| 4 | 数据管理 | 云端行情下载同步、本地数据湖清单、批量删除 |
| 5 | 投研报表库 | 报表列表、HTML 预览、报告对比、元数据查看 |
| 6 | LPPL 泡沫分析 | 指数选择、天数滑块、LPPL 拟合可视化、模型参数展示 |
| 7 | 风险管理 | 组合风险指标、组合优化、压力测试、风险热力图、应力场景与回撤 |

### 后端初始化

`get_manager()` 使用 `@st.cache_resource` 缓存 `AssetManager` 单例，防止 DuckDB 锁冲突。股票地图在后台线程中异步刷新（`refresh_stock_map_async()`）。

数据查询结果通过 `@st.cache_data` 缓存（TTL 30 分钟至 1 小时），减少重复 API 调用。

### 输入验证

- `validate_symbol(symbol)` -- 验证证券代码格式（6 位数字 + .SH/.SZ 后缀）
- `validate_date_range(start_date, end_date)` -- 验证日期范围（不超过一年）

---

## 组件库

`components.py` 提供全部可复用的 Streamlit 渲染组件，被 `dashboard.py` 调用。

### 报告组件

| 函数 | 说明 |
|------|------|
| `render_report_html_preview(html_content, title)` | HTML 报告预览，使用 `st.components.v1.html` |
| `render_report_comparison(compare_result)` | 报告对比结果：新增/删除行数统计 + diff 代码块 |
| `render_report_metadata(metadata)` | 报告元数据：文件名、标题、股票代码、日期、大小、行数、字数 |
| `render_report_library_actions(selected_report, reports)` | 报表库操作按钮（预览/Markdown/PDF/对比） |
| `render_report_comparison_selector(reports)` | 报告对比选择器下拉框 |

### 组合风险组件

| 函数 | 说明 |
|------|------|
| `render_portfolio_risk_metrics(risk_data)` | 风险指标面板：VaR 95%、CVaR 95%、最大回撤、市场状态 |
| `render_portfolio_optimizer_result(opt_result)` | 组合优化结果：权重表格 + 预期收益/波动率/夏普比率 |
| `render_stress_test_results(stress_result)` | 压力测试结果表格（场景/损失金额） |
| `render_risk_heatmap(symbols, risk_scores)` | 风险热力图（股票/风险分数表格） |

### 扫描组件

| 函数 | 说明 |
|------|------|
| `render_scan_config_panel()` | 扫描配置面板：Top N 滑块 + 因子多选（value/growth/quality/momentum） |
| `render_stock_rankings(rankings)` | 股票排行榜 DataFrame |
| `render_tech_signals_summary(signals)` | 技术信号摘要：买入/卖出信号数量 |
| `render_ic_ir_heatmap(ic_ir_data)` | IC/IR 热力图 |

### 结构风险组件

| 函数 | 说明 |
|------|------|
| `render_structural_risk_gauges(risks)` | 结构风险仪表盘：每个风险项显示进度条 |

### 缠论组件

| 函数 | 说明 |
|------|------|
| `render_czsc_analysis_panel(czsc_data)` | 缠论分析面板：笔数量 |
| `render_czsc_zhongshu_analysis(zhongshu_list)` | 中枢分析列表 |
| `render_czsc_buy_sell_points(bs_points)` | 买卖点展示 |
| `plot_czsc_full_chart(df, bi_list, zhongshu_list, bs_points, ticker)` | 完整缠论图表 |

### 反脆弱与健康组件

| 函数 | 说明 |
|------|------|
| `render_anti_fragile_metrics(evt_stats, ntf_detected)` | 反脆弱性指标：VaR、CVaR、NTF 干预警告 |
| `render_health_metrics(network_ok, lake_ok, engine_ok, kb_ok, regime)` | 系统健康状态：网络/数据湖/引擎/市场状态 |

### FSM 组件

| 函数 | 说明 |
|------|------|
| `render_fsm_status_panel(current_state, state_desc, transition_reason, ma_status, next_states, timestamp)` | FSM 状态面板：当前状态、更新时间、流转原因、均线状态、可能流转方向 |
| `render_fsm_state_history(history)` | FSM 状态历史表格 |

### 压力场景与回撤组件

| 函数 | 说明 |
|------|------|
| `render_stress_scenario_buttons(disabled)` | 5 个应力场景按钮（2015 股灾/2016 熔断/2018 单边熊/2020 新冠/2024 微盘踩踏） |
| `render_stress_scenario_results(scenario_results)` | 场景模拟结果表格 |
| `render_drawdown_dashboard(drawdown_metrics, tail_risk_metrics)` | 回撤分析面板：MDD/持续期/Calmar/Ulcer/滚动MDD + 尾部风险指标 |

---

## LPPL 可视化

`lppl_visualizer.py` 中的 `LPPLVisualizer` 封装 LPPL 泡沫检测和交互式可视化。

### LPPLVisualizer

```python
visualizer = LPPLVisualizer()
```

内部组合 `LPPLEngine`（泡沫检测引擎）和 `LPPLDataService`（数据服务）。

#### run_analysis_and_plot(symbol, days)

完整分析流程：
1. 通过 `LPPLDataService` 获取指数数据
2. 调用 `LPPLEngine.detect_bubble()` 执行泡沫检测
3. 提取模型参数（tc, m, w, a, b, c, phi）
4. 使用 `_lppl_func()` 生成预测曲线（含未来外推）
5. 使用 Plotly 创建交互式图表（K 线 + 拟合红线 + 崩盘点绿色虚线）

返回字典：`success`, `symbol`, `days`, `bubble_result`, `model_params`, `html`, `plot_data`

#### _lppl_func(t, tc, m, w, a, b, c, phi)

LPPL 核心公式实现：

```
f(t) = a + b * (tc - t)^m + c * (tc - t)^m * cos(w * log(tc - t) + phi)
```

#### generate_chart(symbol, days)

简化接口，直接返回 HTML 字符串。

---

## 健康检查

`health_check.py` 中的 `ModuleHealthChecker` 验证系统核心模块的完整性。

### ModuleHealthChecker.check_all()

静态方法，逐一尝试 `importlib.import_module()` 导入以下模块：

| 模块名称 | 导入路径 |
|----------|----------|
| FSM Engine | `uniquant.brain.fsm` |
| CZSC Engine | `uniquant.brain.czsc_engine` |
| LPPL Engine | `uniquant.brain.lppl.engine` |
| LRD Engine | `uniquant.brain.regime_detector` |
| NTF Engine | `uniquant.brain.ntf_engine` |
| EVT Risk | `uniquant.risk.evt_risk` |
| Data Fetcher | `uniquant.data.data_fetcher` |
| Storage Manager | `uniquant.data.lake.storage_manager` |

返回 `Dict[str, bool]`，每个模块名称映射到加载成功/失败状态。

---

## 管理逻辑

`manager_logic.py` 定义 `AssetManager` 门面类，是仪表盘与后端服务之间的统一接口。

### FSMStateInfo dataclass

```python
@dataclass
class FSMStateInfo:
    current_state: str       # 当前 FSM 状态
    state_desc: str          # 状态描述
    transition_reason: str   # 转换原因
    ma_status: str           # 均线状态
    timestamp: datetime      # 时间戳
```

### Bi dataclass

缠论笔数据结构：`dt`（时间）、`price`（价格）、`direction`（方向）。

### AssetManager

门面模式（Facade），内部委托给三大服务：

- `DataService` -- 数据获取、下载、数据湖查询
- `AnalysisService` -- 宏观分析、ETF 扫描、报告生成
- `PortfolioService` -- 仓位计算、持仓管理、结构风险

以及两个 UI 专用服务：

- `ManagerPortfolioAnalyticsService` -- 组合风险分析、优化、压力测试
- `ManagerReportService` -- 报告预览、导出、对比、元数据

主要方法分组：

| 类别 | 方法 |
|------|------|
| 数据 | `refresh_stock_map()`, `get_stock_name()`, `list_data_files()`, `delete_file()`, `download_stock()`, `download_etf_sector_data()`, `get_real_kline_data()`, `query_data_lake()` |
| 分析 | `analyze_macro_health()`, `get_structural_risks()`, `get_macro_returns()`, `scan_etfs()`, `list_reports()`, `read_report()`, `generate_report()`, `run_analysis()` |
| 组合 | `calculate_position_size()`, `get_portfolio()`, `add_position()`, `remove_position()` |
| FSM | `get_fsm_state(ticker) -> FSMStateInfo`, `get_fsm_next_states(current_state) -> List[str]` |
| 扫描 | `run_market_scan(scan_mode, holding_period, max_stocks)` -- 支持 quick/fast/full 三种模式 |
| 风险 | `calculate_portfolio_risk_metrics()`, `optimize_portfolio()`, `run_stress_test()`, `run_stress_scenarios()`, `compute_drawdown_metrics()` |
| 报告 | `get_report_html_preview()`, `export_report_to_pdf()`, `compare_reports()`, `get_report_metadata()` |
| 宏观 | `get_macro_environment()` -- V9.0 新接口，聚合结构风险和宏观健康数据 |

FSM 状态转换图（`get_fsm_next_states`）：

```
IDLE -> [SIGNAL]
SIGNAL -> [PROBE, IDLE]
PROBE -> [MONITOR, EXIT]
MONITOR -> [PYRAMID, EXIT]
PYRAMID -> [MONITOR, EXIT]
EXIT -> [IDLE, SIGNAL]
CIRCUIT_BREAK -> [IDLE]
```

---

## 报告服务

### ManagerReportService

`manager_report_service.py` 提供报告的预览、导出和对比功能。

| 方法 | 说明 |
|------|------|
| `get_report_html_preview(file_path)` | 使用 `markdown` 库将 Markdown 转换为带样式的 HTML（表格、代码块、目录） |
| `export_report_to_pdf(file_path, output_path)` | 使用 `weasyprint` 将 HTML 导出为 PDF（可选依赖） |
| `compare_reports(file_path1, file_path2)` | 使用 `difflib.unified_diff` 对比两份报告，返回新增/删除行数和 diff 内容 |
| `get_report_metadata(file_path)` | 提取元数据：文件名、标题（正则匹配 `# xxx`）、股票代码、日期、文件大小、行数、字数 |

### ManagerPortfolioAnalyticsService

`manager_portfolio_analytics_service.py` 提供组合级别的风险分析服务。

| 方法 | 说明 |
|------|------|
| `calculate_portfolio_risk_metrics(symbols, lookback_days=252)` | 收集各股票收益率，构建等权组合，调用 `EVTRisk.calculate_metrics()` |
| `optimize_portfolio(symbols, method, lookback_days=252)` | 调用 `PortfolioOptimizer`，支持 risk_parity 和 mean_variance |
| `run_stress_test(symbols, scenarios)` | 调用 `EVTRisk.calculate_stress_test()`，默认使用 `RiskCalculationConstants.CRASH_SCENARIOS` |

内部方法：
- `_collect_returns(symbols, lookback_days, min_points, symbol_limit)` -- 收集多只股票的日收益率
- `_build_equal_weight_series(returns_data)` -- 构建等权组合收益率序列

---

## 启动方式

```bash
streamlit run src/uniquant/ui/dashboard.py
```

### UIConstants（在 dashboard.py 中使用的配置）

| 配置 | 值 |
|------|----|
| 默认端口 | 8504（Streamlit 默认，可通过 `--server.port` 覆盖） |
| 主题 | 暗色（CSS 覆盖 `#0e1117` 背景） |
| 布局 | `wide` |
| AgGrid 主题 | `"blue"` |
| 缓存 TTL | `@st.cache_resource` TTL=3600 秒，`@st.cache_data` TTL=1800 秒 |
| 自动刷新间隔 | 默认 30 秒，范围 10-300 秒 |
