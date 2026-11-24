# 工作流 8：UI 展示 N2N 深度分析报告

> **分析日期**：2026-11-24  
> **代码基线**：`434aab1` (第25轮)  
> **分析范围**：`src/uniquant/ui/` (8 文件, 3,400 行)  
> **方法论**：Name-to-Name 代码级点对点审查  

---

## 0. 模块概览

### 0.1 **文件清单**

| 文件 | 行数 | 职责 |
|------|------|------|
| `dashboard.py` | 1,568 | Streamlit 主仪表盘（UI 入口） |
| `manager_logic.py` | 548 | AssetManager 门面（委托到 Services） |
| `components.py` | 486 | 可复用 Streamlit 组件（风险/FSM/CZSC/报告） |
| `lppl_visualizer.py` | 370 | LPPL 可视化组件 |
| `manager_report_service.py` | 179 | 报告预览/导出/对比服务 |
| `manager_portfolio_analytics_service.py` | 158 | 组合分析服务（风险/优化/压力测试） |
| `health_check.py` | 50 | 系统健康检查 |
| `__init__.py` | 41 | 模块导出 |

### 0.2 **架构特点**

**✅ 门面模式（Facade Pattern）**：
- `AssetManager` 作为门面，委托到 `DataService`、`AnalysisService`、`PortfolioService`
- 保持向后兼容的公共 API（Dashboard 无需修改）
- 服务层通过构造函数注入（依赖倒置）

**✅ 组件化设计**：
- `components.py` 提供可复用的 Streamlit 组件（风险指标、FSM 状态、CZSC 分析、报告预览等）
- 组件与业务逻辑解耦（只负责渲染，不包含业务规则）

---

## 1. Name 定义（命名与契约）

### 1.1 **AssetManager 门面契约**

**AssetManager 类定义** (`manager_logic.py:39-51`)：
```python
class AssetManager:
    """
    Facade for Alpha-Tactician Pro Logic.
    Delegates to DataService, AnalysisService, and PortfolioService.
    Preserves public API for Dashboard compatibility.
    """

    def __init__(self):
        # Initialize Services
        self.data_service = DataService()
        self.analysis_service = AnalysisService(data_service=self.data_service)
        self.portfolio_service = PortfolioService()
        self.portfolio_analytics_service = ManagerPortfolioAnalyticsService(self)
        self.report_service = ManagerReportService(read_report=self.read_report)
```

**✅ 门面模式清晰**：
- AssetManager 组合 5 个服务（data_service, analysis_service, portfolio_service, portfolio_analytics_service, report_service）
- 保持向后兼容的属性代理（`stock_map`, `etf_list`, `lake_root`, `data_svc`）
- 服务层通过构造函数注入（依赖倒置）

### 1.2 **FSMStateInfo 数据类**

**FSMStateInfo 定义** (`manager_logic.py:22-29`)：
```python
@dataclass
class FSMStateInfo:
    """FSM状态信息数据类"""
    current_state: str
    state_desc: str
    transition_reason: str
    ma_status: str
    timestamp: datetime.datetime
```

**✅ 契约清晰**：
- current_state：当前 FSM 状态（IDLE/SIGNAL/PROBE/MONITOR/PYRAMID/EXIT/CIRCUIT_BREAK）
- state_desc：状态描述（中文）
- transition_reason：转换原因
- ma_status：均线状态（MA20 > MA60 或 MA20 <= MA60）
- timestamp：更新时间

### 1.3 **组件函数命名规范**

**components.py 函数清单**：
```python
# 报告组件
render_report_html_preview(html_content, title)
render_report_comparison(compare_result)
render_report_metadata(metadata)
render_report_library_actions(selected_report, reports)
render_report_comparison_selector(reports)

# 组合风险组件
render_portfolio_risk_metrics(risk_data)
render_portfolio_optimizer_result(opt_result)
render_stress_test_results(stress_result)
render_risk_heatmap(symbols, risk_scores)
render_structural_risk_gauges(risks)

# 扫描组件
render_scan_config_panel()
render_stock_rankings(rankings)
render_tech_signals_summary(signals)
render_ic_ir_heatmap(ic_ir_data)

# CZSC 组件
render_czsc_analysis_panel(czsc_data)
render_czsc_zhongshu_analysis(zhongshu_list)
render_czsc_buy_sell_points(bs_points)
plot_czsc_full_chart(symbol, czsc_data)

# FSM 组件
render_fsm_status_panel(current_state, state_desc, transition_reason, ma_status, next_states, timestamp)
render_fsm_state_history(history)

# 压力测试组件
render_stress_scenario_buttons()
render_stress_scenario_results(stress_result)
render_drawdown_dashboard(drawdown_metrics, tail_risk_metrics)

# 健康检查组件
render_health_metrics(network_ok, lake_ok, engine_ok, kb_ok, regime)
render_anti_fragile_metrics(evt_stats, ntf_detected)
```

**✅ 命名规范**：
- 所有组件函数以 `render_` 开头（清晰表达职责）
- 参数命名清晰（`risk_data`, `stress_result`, `current_state` 等）
- 返回值明确（大多数返回 None，只负责渲染）

---

## 2. Name 映射（数据流转映射）

### 2.1 **AssetManager 委托模式**

**query_data_lake 实现** (`manager_logic.py:104-118`)：
```python
def query_data_lake(self, sql_condition: str) -> pd.DataFrame:
    """Scan local parquet lake via Service and enrich with metrics (Facade Logic)."""
    try:
        # 1. Raw Data Scan
        df_raw = self.data_service.query_lake(sql_condition)
        if df_raw.empty:
            return pd.DataFrame()

        return self.enrich_lake_data(df_raw)
    except (ValueError, TypeError) as e:
        logger.error("Invalid input or data format: %s", e)
        return pd.DataFrame()
    except (RuntimeError, IOError, KeyError, NotImplementedError) as e:
        logger.critical("Unexpected error in query_data_lake: %s", e, exc_info=True)
        return pd.DataFrame()
```

**enrich_lake_data 实现** (`manager_logic.py:145-177`)：
```python
def enrich_lake_data(self, df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    df = df_raw.copy()
    
    # 1. 添加 code 和 name 列
    if "code" not in df.columns and "symbol" in df.columns:
        df["code"] = df["symbol"]
    if "code" in df.columns:
        df["name"] = df["code"].apply(lambda c: self.data_service.get_stock_name(c))
    
    # 2. 计算信号（简化版：close > open → BUY）
    if "close" in df.columns and "open" in df.columns:
        df["signal"] = np.where(df["close"] > df["open"], "BUY", "WAIT")
    
    # 3. 计算强度（涨跌幅）
    if "pct_change" in df.columns:
        df["strength"] = (df["pct_change"] / 100.0).round(4)
    
    # 4. 计算 CZSC 统计（简化版：close > high * 0.9 → 3rd_BUY）
    if "close" in df.columns and "high" in df.columns:
        df["czsc_stat"] = np.where(df["close"] > df["high"] * 0.9, "3rd_BUY", "None")
    
    # 5. 重命名列（大写开头，Streamlit 风格）
    rename = {"code": "Code", "name": "Name", "signal": "Signal", "strength": "Strength", 
              "czsc_stat": "CZSC", "close": "Price", "volume": "Volume", "date": "Date"}
    final_rename = {k: v for k, v in rename.items() if k in final.columns}
    return final.rename(columns=final_rename)
```

**✅ 委托模式清晰**：
- AssetManager 委托 `data_service.query_lake()` 获取原始数据
- AssetManager 调用 `enrich_lake_data()` 添加衍生指标（signal, strength, czsc_stat）
- 重命名列为大写开头（Streamlit 风格）

### 2.2 **FSM 状态查询流程**

**get_fsm_state 实现** (`manager_logic.py:304-346`)：
```python
def get_fsm_state(self, ticker: str) -> Optional[FSMStateInfo]:
    try:
        from ...brain.fsm import FSM

        # 1. 获取股票数据（最近 120 天）
        end_date = get_time_provider().now().strftime("%Y-%m-%d")
        start_date = (get_time_provider().now() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
        df = self.get_real_kline_data(ticker, start_date, end_date)

        if df is None or df.empty:
            logger.warning("无法获取 %s 的数据用于FSM状态分析", ticker)
            return None

        # 2. 创建 FSM 实例并推断状态
        fsm = FSM()
        state_result = fsm.infer_state(df)

        # 3. 构建 FSMStateInfo
        return FSMStateInfo(
            current_state=state_result.get("state_name", "IDLE"),
            state_desc=state_result.get("state_desc", ""),
            transition_reason=state_result.get("transition_reason", ""),
            ma_status=state_result.get("ma_status", "N/A"),
            timestamp=get_time_provider().now()
        )

    except (ValueError, TypeError) as e:
        logger.error("FSM状态分析输入错误 (%s): %s", ticker, e)
        return None
    except (RuntimeError, IOError, KeyError) as e:
        logger.error("FSM状态分析失败 (%s): %s", ticker, e)
        return None
```

**✅ 数据流转清晰**：
- AssetManager.get_fsm_state() → DataService.get_real_kline_data() → FSM.infer_state()
- FSM 返回 dict（state_name, state_desc, transition_reason, ma_status）
- AssetManager 转换为 FSMStateInfo 数据类

### 2.3 **报告预览流程**

**get_report_html_preview 实现** (`manager_report_service.py:67-87`)：
```python
def get_report_html_preview(self, file_path: str) -> str:
    try:
        import markdown

        content = self._read_report(file_path)
        if content.startswith("Error") or content == "Report not found.":
            return f"<p>无法读取报告: {content}</p>"

        html_content = markdown.markdown(
            content, extensions=["tables", "fenced_code", "toc"]
        )
        return (
            f"{self._PREVIEW_STYLE}\n"
            f'            <div class="report-preview">\n                {html_content}\n            </div>\n            '
        )
    except ImportError:
        logger.error("markdown模块未安装")
        return "<p>HTML预览需要安装markdown模块: pip install markdown</p>"
    except Exception as exc:
        logger.error("生成HTML预览失败: %s", exc)
        return f"<p>生成预览失败: {exc}</p>"
```

**✅ 数据流转清晰**：
- ManagerReportService.get_report_html_preview() → `_read_report()` 回调 → markdown.markdown() → HTML 字符串
- 使用 `_PREVIEW_STYLE` CSS 样式（绿色主题，表格斑马纹）
- 错误处理：ImportError（markdown 未安装）、通用 Exception（生成失败）

### 2.4 **Kill Switch 集成**

**stop_trading 实现** (`manager_logic.py:530-535`)：
```python
def stop_trading(self, reason: str = "manual_override") -> None:
    get_kill_switch().kill(reason)
    from ..shared.config_loader import get_config
    get_config().set("execution.trading_enabled", False)
    get_config().set("execution.kill_switch_reason", reason)
    logger.warning("TRADING STOPPED via kill switch: %s", reason)
```

**resume_trading 实现** (`manager_logic.py:537-542`)：
```python
def resume_trading(self) -> None:
    get_kill_switch().reset()
    from ..shared.config_loader import get_config
    get_config().set("execution.trading_enabled", True)
    get_config().set("execution.kill_switch_reason", "")
    logger.info("Trading resumed after kill switch reset")
```

**✅ Kill Switch 集成**：
- UI 层通过 `get_kill_switch().kill(reason)` 触发熔断
- 同时更新配置（`execution.trading_enabled = False`）
- 记录熔断原因（`execution.kill_switch_reason = reason`）
- 恢复时重置 Kill Switch 和配置

---

## 3. Name 传播（依赖链追踪）

### 3.1 **AssetManager 依赖链**

```
AssetManager (门面)
    ├─ DataService (数据服务)
    │   ├─ stock_map / etf_list / lake_root
    │   └─ query_lake() / get_real_kline_data() / download_stock()
    ├─ AnalysisService (分析服务)
    │   ├─ macro_engine / analysis_engine_factory
    │   └─ analyze_macro_health() / generate_report()
    ├─ PortfolioService (组合服务)
    │   └─ calculate_position_size() / add_position() / remove_position()
    ├─ ManagerPortfolioAnalyticsService (组合分析服务)
    │   └─ calculate_portfolio_risk_metrics() / optimize_portfolio() / run_stress_test()
    └─ ManagerReportService (报告服务)
        └─ get_report_html_preview() / export_report_to_pdf() / compare_reports()
```

**✅ 依赖链清晰**：
- AssetManager 组合 5 个服务，每个服务职责单一
- DataService 提供数据访问（stock_map, query_lake, get_real_kline_data）
- AnalysisService 提供分析功能（macro_health, generate_report）
- PortfolioService 提供组合管理（position_size, add/remove_position）
- ManagerPortfolioAnalyticsService 提供高级分析（risk_metrics, optimize, stress_test）
- ManagerReportService 提供报告功能（preview, export, compare）

### 3.2 **Streamlit 组件依赖链**

```
dashboard.py (Streamlit 主入口)
    ↓ 调用
components.py (可复用组件)
    ↓ 渲染
st.metric / st.dataframe / st.progress / st.columns / st.markdown
    ↓ 数据来源
AssetManager (门面)
    ↓ 委托
DataService / AnalysisService / PortfolioService / ...
```

**✅ 依赖链清晰**：
- dashboard.py 调用 components.py 中的渲染函数
- components.py 使用 Streamlit API（st.metric, st.dataframe, st.progress 等）
- 数据来源：AssetManager（门面模式）
- AssetManager 委托到具体服务

---

## 4. Name 变异（边界条件与异常）

### 4.1 **空数据处理**

**components.py 空数据保护** (`components.py:160-163`)：
```python
def render_portfolio_risk_metrics(risk_data: Dict[str, Any]) -> None:
    """渲染投资组合风险指标面板"""
    if not risk_data or risk_data.get("status") != "success":
        st.warning("暂无风险指标数据")
        return
```

**✅ 边界条件处理**：
- 所有组件函数都检查空数据（`if not data`）
- 返回错误状态时显示警告（`risk_data.get("status") != "success"`）
- 避免渲染空图表或报错

### 4.2 **依赖缺失降级**

**get_report_html_preview 依赖缺失** (`manager_report_service.py:82-84`)：
```python
except ImportError:
    logger.error("markdown模块未安装")
    return "<p>HTML预览需要安装markdown模块: pip install markdown</p>"
```

**export_report_to_pdf 依赖缺失** (`manager_report_service.py:93-97`)：
```python
try:
    from weasyprint import HTML
except ImportError:
    logger.warning("weasyprint未安装，PDF导出功能受限")
    return ""
```

**✅ 边界条件处理**：
- markdown 模块未安装 → 返回提示信息（不崩溃）
- weasyprint 模块未安装 → 返回空字符串（PDF 导出功能受限）
- 优雅降级，不影响其他功能

### 4.3 **超时保护**

**_fetch_macro_health_safe 超时保护** (`manager_logic.py:255-280`)：
```python
def _fetch_macro_health_safe(self) -> Dict[str, Any]:
    """安全获取宏观健康数据（带超时和异常处理）"""
    default_health = {
        "regime": "NORMAL",
        "ntf_signal": "中性",
        "summary": "宏观环境分析完成",
    }

    try:
        import time
        start_time = time.time()

        macro_health = self.analyze_macro_health(mock=True)

        if time.time() - start_time > NetworkConstants.SHORT_TIMEOUT:
            raise TimeoutError("宏观数据获取超时")

        return macro_health

    except (TimeoutError, ValueError, TypeError) as e:
        logger.warning("获取宏观健康数据异常 (%s): %s", type(e).__name__, e)
        return default_health
    except (RuntimeError, IOError, KeyError) as e:
        logger.warning("获取宏观健康数据失败: %s", e)
        return default_health
```

**✅ 边界条件处理**：
- 记录开始时间，检查是否超过 `NetworkConstants.SHORT_TIMEOUT`
- 超时或异常时返回默认值（不阻塞 UI）
- 区分超时/参数错误（TimeoutError, ValueError, TypeError）和运行时错误（RuntimeError, IOError, KeyError）

### 4.4 **跨股票状态隔离**

**FSM 状态查询隔离** (`manager_logic.py:314-320`)：
```python
from ...brain.fsm import FSM

# 每次查询都创建新的 FSM 实例
fsm = FSM()
state_result = fsm.infer_state(df)
```

**✅ 边界条件处理**：
- 每次调用 `get_fsm_state()` 都创建新的 FSM 实例
- 避免 UI 层的多股票状态污染（与 brain/fsm.py 的 `_last_symbol` 机制一致）

---

## 5. Name 治理（可观测性与可测试性）

### 5.1 **结构化日志**

**AssetManager 日志** (`manager_logic.py:19`)：
```python
logger = get_logger("AssetManager")
```

**日志示例** (`manager_logic.py:416, 535, 542`)：
```python
logger.info("开始全市场扫描，模式: %s, 股票数: %d", scan_mode, len(symbols))
logger.warning("TRADING STOPPED via kill switch: %s", reason)
logger.info("Trading resumed after kill switch reset")
```

**✅ 可观测性**：
- 使用 `get_logger("AssetManager")` 命名日志器（便于过滤）
- 结构化日志（使用 `%s` 占位符，避免 f-string 性能损耗）
- 记录关键操作（扫描、熔断、恢复）

### 5.2 **错误分类处理**

**query_data_lake 错误分类** (`manager_logic.py:113-118`)：
```python
except (ValueError, TypeError) as e:
    logger.error("Invalid input or data format: %s", e)
    return pd.DataFrame()
except (RuntimeError, IOError, KeyError, NotImplementedError) as e:
    logger.critical("Unexpected error in query_data_lake: %s", e, exc_info=True)
    return pd.DataFrame()
```

**✅ 可观测性**：
- 参数错误（ValueError, TypeError）→ logger.error
- 运行时错误（RuntimeError, IOError, KeyError, NotImplementedError）→ logger.critical + exc_info
- 错误分类清晰，便于排查问题

### 5.3 **健康检查组件**

**render_health_metrics 实现** (`components.py:467-486`)：
```python
def render_health_metrics(network_ok: bool, lake_ok: bool, engine_ok: bool, 
                          kb_ok: bool = True, regime: str = "NORMAL") -> None:
    """渲染系统健康指标"""
    st.markdown("### 💚 系统健康状态")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        status = "✅" if network_ok else "❌"
        st.metric("网络", status)

    with col2:
        status = "✅" if lake_ok else "❌"
        st.metric("数据湖", status)

    with col3:
        status = "✅" if engine_ok else "❌"
        st.metric("引擎", status)

    with col4:
        st.metric("市场状态", regime)
```

**✅ 可观测性**：
- 4 个健康指标：网络、数据湖、引擎、市场状态
- 使用 ✅/❌ 图标（直观）
- 市场状态显示 regime（NORMAL/STRESSED/FROZEN）

### 5.4 **报告元数据提取**

**get_report_metadata 实现** (`manager_report_service.py:149-179`)：
```python
def get_report_metadata(self, file_path: str) -> Dict[str, Any]:
    try:
        import re

        path = Path(file_path)
        if not path.exists():
            return {"error": "文件不存在"}

        stat = path.stat()
        content = self._read_report(file_path)

        # 正则提取元数据
        title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        ticker_match = re.search(r"代码[:：]?\s*(\d{6}\.[A-Z]{2})", content)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", content)

        return {
            "status": "success",
            "filename": path.name,
            "title": title_match.group(1) if title_match else path.stem,
            "ticker": ticker_match.group(1) if ticker_match else "Unknown",
            "report_date": date_match.group(1) if date_match else "",
            "file_size_kb": round(stat.st_size / 1024, 2),
            "created": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "line_count": len(content.splitlines()),
            "word_count": len(content.split()),
        }
    except Exception as exc:
        logger.error("获取报告元数据失败: %s", exc)
        return {"error": str(exc)}
```

**✅ 可观测性**：
- 提取报告元数据：title（一级标题）、ticker（股票代码）、report_date（日期）
- 文件统计：file_size_kb、created、line_count、word_count
- 使用正则表达式提取（支持中英文冒号）

---

## 6. 端到端数据流追踪

### 6.1 **典型路径 1：数据湖查询 + UI 渲染**

```
用户在 Streamlit 输入 SQL 条件（如 "code == '600519.SH'"）
    ↓ dashboard.py 调用
AssetManager.query_data_lake(sql_condition)
    ↓ 委托
DataService.query_lake(sql_condition)
    ↓ 返回
df_raw (Parquet 格式，9 列契约: date, open, high, low, close, amount, volume, reserved, code)
    ↓ AssetManager.enrich_lake_data(df_raw)
    ├─ 添加 name 列（get_stock_name()）
    ├─ 计算 signal 列（close > open → BUY）
    ├─ 计算 strength 列（涨跌幅）
    ├─ 计算 czsc_stat 列（close > high * 0.9 → 3rd_BUY）
    └─ 重命名列（Code, Name, Signal, Strength, CZSC, Price, Volume, Date）
    ↓ 返回
df_enriched ( enriched DataFrame)
    ↓ dashboard.py 渲染
st.dataframe(df_enriched, use_container_width=True)
    ↓ 用户看到
股票列表（含信号、强度、CZSC 统计）
```

### 6.2 **典型路径 2：FSM 状态查询 + UI 渲染**

```
用户选择股票（如 "600519.SH"）
    ↓ dashboard.py 调用
AssetManager.get_fsm_state("600519.SH")
    ↓ 委托
DataService.get_real_kline_data("600519.SH", "2024-08-01", "2024-11-24")
    ↓ 返回
df (120 天 K 线数据)
    ↓ 创建 FSM 实例
FSM().infer_state(df)
    ↓ 返回
state_result = {
    "state_name": "MONITOR",
    "state_desc": "股价处于明确的上升趋势，MA20 > MA60，适合持有和监控",
    "transition_reason": "股价处于明确上升趋势，MA20 > MA60，当前价格: 1500.00",
    "ma_status": "MA20 > MA60"
}
    ↓ AssetManager 转换
FSMStateInfo(
    current_state="MONITOR",
    state_desc="股价处于明确的上升趋势...",
    transition_reason="股价处于明确上升趋势...",
    ma_status="MA20 > MA60",
    timestamp=datetime.now()
)
    ↓ dashboard.py 调用
render_fsm_status_panel(
    current_state="MONITOR",
    state_desc="股价处于明确的上升趋势...",
    transition_reason="股价处于明确上升趋势...",
    ma_status="MA20 > MA60",
    next_states=["PYRAMID", "EXIT", "IDLE", "CIRCUIT_BREAK"],
    timestamp="2026-11-24 11:40:00"
)
    ↓ 用户看到
FSM 状态面板（当前状态、描述、转换原因、均线状态、可能的下一个状态）
```

### 6.3 **典型路径 3：Kill Switch 触发 + UI 反馈**

```
用户点击 "停止交易" 按钮
    ↓ dashboard.py 调用
AssetManager.stop_trading(reason="manual_override")
    ↓ 触发
get_kill_switch().kill("manual_override")
    ↓ 持久化
DiskStateStore.save_state(kill_reason="manual_override", killed_at=...)
    ↓ 更新配置
get_config().set("execution.trading_enabled", False)
get_config().set("execution.kill_switch_reason", "manual_override")
    ↓ 记录日志
logger.warning("TRADING STOPPED via kill switch: manual_override")
    ↓ dashboard.py 显示
st.error("⚠️ 交易已停止：manual_override")
    ↓ 用户看到
红色错误提示（交易已停止）
```

---

## 7. 发现的问题

### 7.1 **CRITICAL 级别**

无

### 7.2 **HIGH 级别**

无

### 7.3 **MEDIUM 级别**

无

### 7.4 **LOW 级别**

#### L1: enrich_lake_data 简化版信号计算

**位置**：`manager_logic.py:157, 167`  
**问题**：`signal` 和 `czsc_stat` 使用简化版计算（close > open → BUY, close > high * 0.9 → 3rd_BUY），不是真正的 FSM/CZSC 引擎结果。  
**代码**：
```python
df["signal"] = np.where(df["close"] > df["open"], "BUY", "WAIT")
df["czsc_stat"] = np.where(df["close"] > df["high"] * 0.9, "3rd_BUY", "None")
```

**影响**：数据湖查询结果显示的信号是简化版（仅供快速浏览），不是真实引擎输出。  
**修复建议**：在列名中明确标注（如 `signal_quick`、`czsc_stat_quick`），或在 UI 中添加提示"简化版信号，仅供参考"。

#### L2: dashboard.py 文件过大

**位置**：`dashboard.py` (1,568 行)  
**问题**：dashboard.py 超过 800 行软上限（CLAUDE.md Rule 9），是 UI 模块中最大的文件。  
**影响**：可维护性下降（超过 800 行软上限）。  
**修复建议**：拆分为多个子模块（如 `dashboard_tabs/` 目录，每个 tab 一个文件）。

---

## 8. 与深度验证报告的交叉验证

### 8.1 **已验证的事实**

1. **门面模式**：✅ 已确认（AssetManager 委托到 5 个服务，保持向后兼容 API）
2. **组件化设计**：✅ 已确认（components.py 提供可复用 Streamlit 组件，只负责渲染）
3. **Kill Switch 集成**：✅ 已确认（UI 层通过 `get_kill_switch().kill(reason)` 触发熔断）
4. **超时保护**：✅ 已确认（`_fetch_macro_health_safe()` 检查 `NetworkConstants.SHORT_TIMEOUT`）
5. **跨股票状态隔离**：✅ 已确认（`get_fsm_state()` 每次创建新的 FSM 实例）

### 8.2 **新发现的问题**

1. **简化版信号计算**（LOW）：`enrich_lake_data()` 使用简化版 signal/czsc_stat，不是真实引擎输出
2. **dashboard.py 文件过大**（LOW）：1,568 行，超过 800 行软上限

### 8.3 **架构质量评估**

**✅ 优秀设计**：
- **门面模式**：AssetManager 作为门面，委托到服务层，保持向后兼容
- **组件化**：components.py 提供可复用组件，与业务逻辑解耦
- **错误处理**：区分参数错误和运行时错误，优雅降级（依赖缺失时返回提示信息）
- **超时保护**：宏观数据获取带超时保护，避免阻塞 UI

**⚠️ 改进空间**：
- **信号标注**：简化版信号应明确标注（避免误导）
- **文件拆分**：dashboard.py 应拆分为多个子模块

---

## 9. 结论

### 9.1 **UI 展示模块健康度评估**

- **AssetManager 门面**：✅ 优秀（委托模式、向后兼容、依赖注入）
- **Streamlit 组件**：✅ 优秀（命名规范、空数据保护、错误处理）
- **报告服务**：✅ 优秀（HTML 预览、PDF 导出、报告对比、元数据提取）
- **组合分析服务**：✅ 优秀（风险指标、优化、压力测试）
- **Kill Switch 集成**：✅ 优秀（熔断触发、配置更新、日志记录）
- **超时保护**：✅ 优秀（宏观数据获取、优雅降级）

### 9.2 **关键风险**

1. **简化版信号误导**（LOW）：数据湖查询结果显示的信号是简化版
2. **dashboard.py 可维护性**（LOW）：1,568 行，超过 800 行软上限

### 9.3 **修复优先级**

1. **P2**：拆分 dashboard.py 为多个子模块（L2）
2. **P3**：简化版信号添加标注（L1）

---

**分析人**：Claude (Anthropic)  
**审查时间**：2026-11-24  
**代码引用精度**：所有引用精确到行号  
**交叉验证基础**：DEEP_VERIFICATION_9_REPORTS_20261124.md (98.9% 准确率)  
**下一步**：跨模块集成分析或综合报告
---

# 独立第三方评审意见（资深 A 股交易员视角）

> 评审基线：代码 commit `434aab1` · 评审人：资深 A 股交易员

## 评审结论：**存疑**

UI 架构（门面 + 组件化）干净，但报告对**交易员最关心的"展示会不会误导"几乎零覆盖**，还把两处会直接误导的展示降级为 LOW 或直接漏掉。

## 优点
1. 门面（AssetManager 委托 5 个 Service）+ 组件化（`render_*` 只渲染不含业务规则）分层清晰，空数据保护到位。
2. Kill Switch 在 UI 层同时做三件事：`kill()` + 写配置 `trading_enabled=False` + 记录原因，恢复对称，链路完整。
3. 依赖缺失（markdown/weasyprint）优雅降级、宏观数据带超时保护，UI 不易崩。

## 问题清单

**HIGH — H1（报告遗漏）：宏观数据获取失败时静默回落到 mock 默认值，UI 显示假'正常'。**
`_fetch_macro_health_safe`（§4.3）在超时/异常时返回 `{"regime":"NORMAL","ntf_signal":"中性","summary":"宏观环境分析完成"}`。交易员在 UI 上看到"宏观环境分析完成 / NORMAL"，**无法区分这是真实分析结果还是拉取失败后的占位假数据**。典型的误导性展示 + fail-open 呈现。报告把"超时保护"当优点，却**没指出默认值是伪装成真实结果的 mock**。

**HIGH — H2（报告遗漏）：报告完全没评审'回测结果如何呈现给交易员'。**
全篇覆盖了 FSM/CZSC/报告预览/健康检查，**没有任何一节讨论 dashboard 如何展示回测结果（收益曲线、Sharpe、胜率、profit_factor）**，也没讨论是否标注滑点/成本假设、是否区分"回测"与"可复现实盘"。评审核心之一是"是否存在看起来赚钱但不可复现的展示风险"，这份 UI 报告**对该问题完全交白卷**。指标本身在 04 报告有实现，但"UI 上怎么呈现、加不加免责/敏感性提示"无人评审。这是呈现层最大缺口。

**MEDIUM — M1：数据湖'简化版信号'会误导，报告自评 LOW，低估。**
L1 承认 `signal = close>open→BUY`、`czsc_stat = close>high*0.9→3rd_BUY`（`manager_logic.py:157,167`）是简化版、非真实 FSM/CZSC 引擎输出。UI 直接把含 `Signal=BUY`、`CZSC=3rd_BUY` 的表喂给交易员（§6.1 `st.dataframe(df_enriched)`）。列名就叫 "Signal"/"CZSC"，**没有任何标注说是简化版**。交易员极可能当成真实信号来下单。报告列为 LOW/P3 定级过低——误导性展示应是 HIGH。

**MEDIUM — M2：FSM 状态面板（MONITOR/PYRAMID/EXIT 等）呈现是否会被误解为可执行交易指令，报告未讨论。**
§2.2/§6.2 展示 `render_fsm_status_panel` 输出当前状态与"可能的下一个状态"。交易员看到 "PYRAMID（加仓）""EXIT（离场）"是否清楚这只是状态机推断、不等于已校验可下单的建议？报告未评估这层呈现语义，存在过度解读风险。

**LOW**：dashboard.py 1568 行超 800 行上限，报告已列。

## 需对照代码确认的关键声明
- dashboard 是否展示回测结果，以及是否标注成本/滑点假设、是否提示不可复现。
- `_fetch_macro_health_safe` 的 mock 默认值是否在真实 UI 上被当正常数据渲染。
- `Signal/CZSC` 列在 Streamlit 界面上是否有"简化版/仅供参考"标注。
- "市场状态 regime（NORMAL/STRESSED/FROZEN）"数据来源是真实计算还是同为 mock。
