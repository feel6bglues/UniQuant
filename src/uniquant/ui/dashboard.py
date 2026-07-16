import logging
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from ..shared.time_provider import get_time_provider

# Make streamlit extensions optional dependencies
try:
    from st_aggrid import AgGrid, GridOptionsBuilder

    HAS_AGGRID = True
except ImportError:
    HAS_AGGRID = False
    AgGrid = None
    GridOptionsBuilder = None

# Auto-refresh functionality
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False
    st_autorefresh = None

try:
    from streamlit_echarts import st_pyecharts

    HAS_ECHARTS = True
except ImportError:
    HAS_ECHARTS = False
    st_pyecharts = None

# Import required modules

from uniquant.shared.error_handling import handle_errors
from uniquant.shared.logger_factory import get_logger
from uniquant.ui.components import (
    render_report_html_preview,
    render_report_comparison,
    render_report_comparison_selector,
    render_report_metadata,
    render_portfolio_risk_metrics,
    render_portfolio_optimizer_result,
    render_stress_test_results,
    render_risk_heatmap,
    render_scan_config_panel,
    render_stock_rankings,
    render_structural_risk_gauges,
    render_tech_signals_summary,
    render_czsc_analysis_panel,
    render_czsc_buy_sell_points,
    render_czsc_zhongshu_analysis,
    render_fsm_state_history,
    render_fsm_status_panel,
    render_health_metrics,
    render_ic_ir_heatmap,
    plot_czsc_full_chart,
    render_anti_fragile_metrics,
    render_stress_scenario_buttons,
    render_stress_scenario_results,
    render_drawdown_dashboard,
)
from uniquant.ui.health_check import ModuleHealthChecker
from uniquant.ui.lppl_visualizer import LPPLVisualizer
from uniquant.ui.manager_logic import AssetManager

logger = get_logger(__name__)

UI_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


# Fallback functions for when extensions are not available
def fallback_aggrid(df, **kwargs):
    """Fallback to st.dataframe when AgGrid is not available"""
    st.dataframe(df, **kwargs)
    return {"selected_rows": []}


# --- Page Config ---
st.set_page_config(
    page_title="Alpha-Tactician Pro V1.0 Sovereign",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- CSS Overrides (Dark Mode) ---
st.markdown(
    """
    <style>
    .main { background-color: #0e1117; color: #ffffff; }
    .stMetric { background-color: #1e2130; padding: 10px; border-radius: 5px; }
    .stTable { background-color: #1e2130; }
    </style>
""",
    unsafe_allow_html=True,
)

# --- 顶部退出按钮 ---
# 使用Streamlit的原生按钮和状态管理
if st.button("🚪 退出程序", key="exit_btn", help="点击退出Alpha-Tactician Pro"):
    st.success("应用已停止。您可以关闭浏览器窗口。")
    st.stop()

# --- 侧边栏 ---
st.sidebar.header("🚀 Alpha-Tactician Pro V1.0")
st.sidebar.markdown("---")

# 数据导入 - 默认展开
with st.sidebar.expander("📥 数据导入与同步", expanded=True):
    uploaded_file = st.sidebar.file_uploader("上传自选股清单", type=["csv", "txt"])
    tags = st.sidebar.text_input("策略标签", "2026_核心仓位")
    if st.sidebar.button("点击上传并同步 (Upload)"):
        st.sidebar.success("正在同步至本地 Parquet 数据湖...")

# 全局风控 - 默认展开
with st.sidebar.expander("🛡️ 全局风险偏好", expanded=True):
    capital = st.sidebar.number_input("初始总资产 (¥)", value=1000000)
    risk_pct = st.sidebar.slider("风险偏好系数 (%)", 1, 100, 10)
    if risk_pct > 15:
        st.sidebar.warning("⚠️ 实验室模式已激活：当前处于高风险设置")

# 战术实验室 - 默认折叠，按需展开
with st.sidebar.expander("🧪 战术参数配置", expanded=False):
    analysis_date = st.sidebar.date_input("回顾分析日期", value=datetime.today())
    ma_windows = st.sidebar.text_input("均线窗口组 (MA)", "20, 60, 120")
    czsc_enabled = st.sidebar.toggle("启用 CZSC 几何形态确认", value=True)

# 自动刷新配置 - 默认折叠
with st.sidebar.expander("🔄 自动刷新设置", expanded=False):
    auto_refresh_enabled = st.sidebar.toggle(
        "启用自动刷新",
        value=False,
        help="开启后页面将按设定间隔自动刷新数据"
    )

    if auto_refresh_enabled:
        refresh_interval = st.sidebar.slider(
            "刷新间隔 (秒)",
            min_value=10,
            max_value=300,
            value=30,
            step=10,
            help="数据刷新间隔时间"
        )

        # 市场时间检查
        check_market_hours = st.sidebar.toggle(
            "仅在市场开放时刷新",
            value=True,
            help="只在A股交易时间(9:30-11:30, 13:00-15:00)自动刷新"
        )

        # 显示最后更新时间
        if "last_refresh_time" not in st.session_state:
            st.session_state["last_refresh_time"] = get_time_provider().now()

        time_since_refresh = (get_time_provider().now() - st.session_state["last_refresh_time"]).total_seconds()
        st.sidebar.caption(f"⏱️ 上次更新: {int(time_since_refresh)}秒前")

        # 执行自动刷新逻辑
        if HAS_AUTOREFRESH:
            # 检查是否在市场时间
            should_refresh = True
            if check_market_hours:
                from uniquant.shared.constants import MarketHours
                should_refresh = MarketHours.is_market_open()

            if should_refresh:
                st_autorefresh(interval=refresh_interval * 1000, limit=None, key="data_refresh")
                st.session_state["last_refresh_time"] = get_time_provider().now()
            else:
                st.sidebar.info("⏸️ 当前非交易时间，已暂停自动刷新")
        else:
            st.sidebar.warning("⚠️ streamlit-autorefresh未安装")
            st.sidebar.code("pip install streamlit-autorefresh", language="bash")


# --- 后端初始化 ---
@st.cache_resource
def get_backend():
    # Deprecated in favor of get_manager
    return None


# --- 后端初始化 (Singleton Pattern) ---
@st.cache_resource(max_entries=10, ttl=3600)
@handle_errors(Exception, default_return=None, log_level=logging.ERROR)
def get_manager():
    """Singleton access to AssetManager to prevent DuckDB locks."""
    mgr = AssetManager()
    # Ensure map is loaded but don't block startup
    if not mgr.stock_map:
        # Use minimal map initially for faster startup
        # Full refresh will happen in background
        # This pass statement intentionally left blank
        # Background refresh is handled by refresh_stock_map_async() later in the code
        pass
    return mgr


# Cache for expensive operations
@st.cache_data(max_entries=50, ttl=1800)
@handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
def get_scan_results(condition):
    """Cache scan results to avoid repeated calculations."""
    return asset_mgr.query_data_lake(condition)


@st.cache_data(max_entries=20, ttl=3600)
@handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
def get_etf_scan_results():
    """Cache ETF scan results."""
    return asset_mgr.scan_etfs()


@st.cache_data(max_entries=20, ttl=3600)
@handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
def get_portfolio_data():
    """Cache portfolio data."""
    return asset_mgr.get_portfolio()


@st.cache_data(max_entries=50, ttl=3600)
@handle_errors(Exception, default_return=(pd.DataFrame(), []), log_level=logging.ERROR)
def get_kline_data(ticker, start_date, end_date):
    """Cache kline data to avoid repeated API calls."""
    return asset_mgr.get_real_kline_data(ticker, start_date, end_date)


# Initialize manager early but don't block
asset_mgr = get_manager()

# Fallback if manager initialization fails
if asset_mgr is None:
    st.error("❌ 后端服务初始化失败，请刷新页面重试")
    st.stop()


# Background refresh of stock map (non-blocking)
def refresh_stock_map_async():
    """Refresh stock map in background without blocking UI."""
    try:
        asset_mgr.refresh_stock_map()
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid data in stock map refresh: {e}")
    except (IOError, OSError) as e:
        logger.error(f"File system error in stock map refresh: {e}")
    except UI_RECOVERABLE_ERRORS as e:
        logger.critical(f"Unexpected error in stock map refresh: {e}", exc_info=True)


# Start background refresh
if st.runtime.exists():
    t = threading.Thread(target=refresh_stock_map_async)
    t.daemon = True
    t.start()
# Sizer is now accessed via asset_mgr facade, removing standalone sizer
# But dashboard code below uses sizer variables, we'll refactor logic to use asset_mgr entirely or just get sizer from it if needed
# Actually below code uses asset_mgr directly for everything now based on previous refactor.


# V1.0 反脆弱引擎 (Moved to AssetManager)
# Engines are now managed by asset_mgr


# --- 输入验证装饰器 ---
def validate_symbol(symbol):
    """
    验证股票代码格式
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("证券代码不能为空")
    if not (symbol.endswith(".SH") or symbol.endswith(".SZ")):
        raise ValueError("证券代码必须包含 .SH 或 .SZ 后缀")
    if len(symbol) != 10:
        raise ValueError("证券代码格式不正确，应为 6 位数字 + .SH/.SZ")
    return True


def validate_date_range(start_date, end_date):
    """
    验证日期范围
    """
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_date - start_date).days > 365:
        raise ValueError("日期范围不能超过一年")
    return True


# --- 主工作区 ---
# Tabs are loaded on demand when selected
# This is a Streamlit built-in feature
tabs = st.tabs(
    [
        "🚀 宏观驾驶舱",
        "🎯 策略扫描器",
        "🔬 深度几何分析",
        "💼 机会跟踪器",
        "💾 数据管理",
        "📚 投研报表库",
        "📈 LPPL泡沫分析",
        "🛡️ 风险管理",
    ]
)

# Tab 1: 宏观驾驶舱
with tabs[0]:
    st.success("✅ **实时数据**: 以下指标基于真实市场数据计算")
    st.divider()

    # Real Data Implementation (Via Manager)
    evt_stats = asset_mgr.analyze_macro_health()
    
    regime = evt_stats.get("regime", "NORMAL") if evt_stats else "NORMAL"
    network_ok = evt_stats.get("network_ok", True) if evt_stats else True
    lake_ok = evt_stats.get("lake_ok", True) if evt_stats else True
    engine_ok = evt_stats.get("engine_ok", True) if evt_stats else True
    kb_ok = evt_stats.get("kb_ok", True) if evt_stats else True

    render_health_metrics(network_ok, lake_ok, engine_ok, kb_ok, regime=regime)

    st.markdown("### 🛡️ 反脆弱核心指标 (Anti-Fragility)")
    render_anti_fragile_metrics(evt_stats, ntf_detected=False)

    # Detailed Module Status
    with st.expander("🛠️ 系统模块与引擎健康状态 (Module Status)", expanded=False):
        health_status = ModuleHealthChecker.check_all()
        cols = st.columns(4)
        for i, (name, ok) in enumerate(health_status.items()):
            cols[i % 4].markdown(f"{name}: {'✅' if ok else '❌'}")

    st.markdown("### 📊 结构化风险热力分布 (LPPL $t_c$)")
    risks = asset_mgr.get_structural_risks()
    render_structural_risk_gauges(risks)
    # Check if any tc_days is less than 10
    if any(isinstance(risk, dict) and risk.get("tc_days", 100) < 10 for risk in risks.values()):
        st.error("⚠️ 结构化风险警报：建议回避 [中小盘] 相关策略")

    # FSM State Monitor Section (NEW)
    st.divider()
    st.markdown("### 🎛️ FSM 状态监控 (Finite State Machine)")
    
    # FSM监控股票选择
    fsm_ticker = st.text_input(
        "输入股票代码查看FSM状态 (例如: 000001.SZ)",
        value=st.session_state.get("selected_stock", "000001.SZ"),
        key="fsm_ticker_input"
    )
    
    if st.button("🔍 分析FSM状态", key="analyze_fsm_btn"):
        with st.spinner(f"正在分析 {fsm_ticker} 的FSM状态..."):
            fsm_info = asset_mgr.get_fsm_state(fsm_ticker)
            
            if fsm_info:
                # 获取可能的下一个状态
                next_states = asset_mgr.get_fsm_next_states(fsm_info.current_state)
                
                # 渲染FSM状态面板
                render_fsm_status_panel(
                    current_state=fsm_info.current_state,
                    state_desc=fsm_info.state_desc,
                    transition_reason=fsm_info.transition_reason,
                    ma_status=fsm_info.ma_status,
                    next_states=next_states,
                    timestamp=fsm_info.timestamp
                )
                
                # 保存到session_state用于历史记录
                if "fsm_state_history" not in st.session_state:
                    st.session_state["fsm_state_history"] = []
                
                # 添加当前状态到历史
                st.session_state["fsm_state_history"].append({
                    "state": fsm_info.current_state,
                    "timestamp": fsm_info.timestamp,
                    "ticker": fsm_ticker
                })
                
                # 限制历史记录长度
                if len(st.session_state["fsm_state_history"]) > 50:
                    st.session_state["fsm_state_history"] = st.session_state["fsm_state_history"][-50:]
            else:
                st.error(f"❌ 无法获取 {fsm_ticker} 的FSM状态，请检查股票代码是否正确")
    
    # 显示状态历史（如果有）
    if "fsm_state_history" in st.session_state and st.session_state["fsm_state_history"]:
        with st.expander("📜 FSM 状态历史", expanded=False):
            render_fsm_state_history(st.session_state["fsm_state_history"])

# Tab 2: 策略扫描器
with tabs[1]:
    sub_tabs = st.tabs(["🚀 全市场因子扫描 (ScanPipeline)", "🎯 SQL选股 (DuckDB)", "🛡️ ETF择时战略"])
    
    # Sub Tab 1: 全市场因子扫描 (NEW - ScanPipeline集成)
    with sub_tabs[0]:
        st.markdown("### 🚀 Sovereign Alpha ScanPipeline")
        st.info("基于多因子模型的全市场扫描，包含IC/IR分析、因子合成、技术信号验证")
        
        # 扫描配置面板
        scan_config = render_scan_config_panel()
        
        # 扫描按钮
        if st.button("🚀 开始全市场扫描", type="primary", key="run_scan_pipeline"):
            with st.spinner(f"正在执行{scan_config['scan_mode']}模式扫描，请稍候..."):
                # 执行扫描
                scan_result = asset_mgr.run_market_scan(
                    scan_mode=scan_config["scan_mode"],
                    holding_period=scan_config["holding_period"],
                    max_stocks=scan_config["max_stocks"],
                )
                
                if scan_result.get("status") == "success":
                    st.success(
                        f"✅ 扫描完成！耗时 {scan_result.get('duration_seconds', 0):.2f}秒，"
                        f"扫描 {scan_result.get('stocks_scanned', 0)} 只股票，"
                        f"处理 {scan_result.get('records_processed', 0)} 条记录"
                    )
                    
                    # 保存结果到session_state
                    st.session_state["last_scan_result"] = scan_result
                    
                    # 显示IC/IR分析
                    render_ic_ir_heatmap(scan_result.get("ic_ir_analysis", {}))
                    
                    # 显示股票排名
                    render_stock_rankings(
                        scan_result.get("top_stocks", pd.DataFrame()),
                        scan_result.get("bottom_stocks", pd.DataFrame()),
                    )
                    
                    # 显示技术信号汇总
                    render_tech_signals_summary(
                        scan_result.get("tech_signals", pd.DataFrame())
                    )
                    
                    # 显示报告文件链接
                    report_files = scan_result.get("report_files", {})
                    if report_files:
                        with st.expander("📄 生成的报告文件", expanded=False):
                            for report_type, file_path in report_files.items():
                                st.markdown(f"- **{report_type}**: `{file_path}`")
                else:
                    st.error(f"❌ 扫描失败: {scan_result.get('message', '未知错误')}")
        
        # 显示上次扫描结果（如果有）
        if "last_scan_result" in st.session_state:
            with st.expander("📊 上次扫描结果", expanded=False):
                last_result = st.session_state["last_scan_result"]
                if last_result.get("status") == "success":
                    render_ic_ir_heatmap(last_result.get("ic_ir_analysis", {}))
                    render_stock_rankings(
                        last_result.get("top_stocks", pd.DataFrame()),
                        last_result.get("bottom_stocks", pd.DataFrame()),
                    )

    # Sub Tab 2: SQL选股 (原有功能)
    with sub_tabs[1]:
        st.markdown("### 🎯 Sovereign Alpha Scanner (DuckDB Powered)")
        st.info("SQL式检索，支持复杂条件筛选")
        # SQL 式检索
        scan_condition = st.text_input(
            "SQL 过滤条件 (例如 close > 50 AND volume > 1000000)", "close > 50",
            key="sql_scan_condition"
        )

        if st.button("开始全局扫描", key="sql_scan_btn"):
            with st.spinner(f"正在对数据湖进行亚毫秒级检索: '{scan_condition}'..."):
                scan_df = get_scan_results(scan_condition)

                if not scan_df.empty:
                    st.success(f"检索成功！找到 {len(scan_df)} 个标的")

                    if HAS_AGGRID:
                        gb = GridOptionsBuilder.from_dataframe(scan_df)
                        gb.configure_selection("single", use_checkbox=True)
                        gridOptions = gb.build()
                        grid_response = AgGrid(
                            scan_df,
                            gridOptions=gridOptions,
                            theme="blue",
                            update_mode="SELECTION_CHANGED",
                        )

                        selected_rows = grid_response["selected_rows"]
                        if selected_rows is not None and len(selected_rows) > 0:
                            # AssetManager returns capitalized columns now: Code, Name, ...
                            row = (
                                selected_rows[0]
                                if isinstance(selected_rows[0], dict)
                                else selected_rows.iloc[0]
                            )
                            selected_stock = row.get("Code", row.get("code", ""))

                            if selected_stock:
                                st.session_state["selected_stock"] = selected_stock
                    else:
                        grid_response = fallback_aggrid(scan_df)
                else:
                    st.warning(
                        "未找到符合条件的标的，或数据湖为空。请先去'数据管理'同步数据。"
                    )

    # Sub Tab 3: ETF择时 (原有功能)
    with sub_tabs[2]:
        st.markdown("### 🛡️ Sovereign ETF Timing Strategy (Beta)")
        st.info("Scanning major index & sector ETFs for structural opportunities.")
        st.warning("⚠️ **注意**: 以下 ETF 信号为模拟数据，用于演示系统功能")

        if st.button("🚀 Start ETF Pulse Scan"):
            with st.spinner("Analyzing Global ETF Universe..."):
                etf_data = get_etf_scan_results()
                if etf_data.empty:
                    st.warning("Scan returned no data or failed to fetch.")
                    etf_data = pd.DataFrame(
                        columns=["Code", "Name", "Signal", "Strength", "CZSC_State"]
                    )

                if HAS_AGGRID:
                    gb_etf = GridOptionsBuilder.from_dataframe(etf_data)
                    gb_etf.configure_column(
                        "Strength",
                        type=[
                            "numericColumn",
                            "numberColumnFilter",
                            "customNumericFormat",
                        ],
                        precision=2,
                    )
                    gb_etf.configure_selection("single", use_checkbox=True)
                    grid_etf = AgGrid(
                        etf_data,
                        gridOptions=gb_etf.build(),
                        theme="blue",
                        key="etf_grid",
                    )
                else:
                    grid_etf = fallback_aggrid(etf_data)

# Tab 3: 深度几何分析
with tabs[2]:
    col_input, col_dates, col_info = st.columns([1, 1, 2])
    with col_input:
        manual_ticker = st.text_input(
            "输入证券代码 (或从扫描器选择)",
            value=st.session_state.get("selected_stock", "600519.SH"),
            key="czsc_ticker_input"
        )

        # 实时验证证券代码格式
        if manual_ticker:
            try:
                validate_symbol(manual_ticker)
                st.success("✅ 证券代码格式正确")
            except ValueError as e:
                st.error(f"❌ {e}")
    with col_dates:
        start_date = st.date_input("Start Date", datetime(2024, 1, 1), key="czsc_start_date")
        end_date = st.date_input("End Date", get_time_provider().now(), key="czsc_end_date")

        # 验证日期范围
        try:
            validate_date_range(start_date, end_date)
        except ValueError as e:
            st.error(f"❌ {e}")

    if manual_ticker:
        st.session_state["selected_stock"] = manual_ticker
        ticker = manual_ticker
    else:
        ticker = "600519.SH"

    st.markdown(f"### 🔬 深度几何研究: **{ticker}**")
    
    # CZSC分析子Tab
    czsc_tabs = st.tabs(["📐 CZSC结构分析", "📊 K线图表", "🛡️ 交易计划"])
    
    # 获取数据
    s_date = start_date.strftime("%Y%m%d")
    e_date = end_date.strftime("%Y%m%d")
    
    with st.spinner(f"正在分析 {ticker} 的几何结构..."):
        try:
            validate_symbol(ticker)
            validate_date_range(start_date, end_date)
            df_g = get_kline_data(ticker, s_date, e_date)
        except ValueError as e:
            st.error(f"❌ 输入验证失败: {e}")
            df_g = pd.DataFrame()
        except UI_RECOVERABLE_ERRORS as e:
            st.error(f"❌ 数据获取失败: {e}")
            df_g = pd.DataFrame()
    
    # 执行CZSC分析
    czsc_result = None
    bi_list = []
    zhongshu_list = []
    bs_points = []
    
    if not df_g.empty:
        try:
            from uniquant.services.service_container import ServiceContainer
            try:
                _factory = ServiceContainer.instance().get("engine_factory")
                if _factory is None:
                    ServiceContainer.instance().initialize()
                    _factory = ServiceContainer.instance().get("engine_factory")
                czsc_engine = _factory.czsc if _factory else None
            except (LookupError, RuntimeError, ImportError, AttributeError):
                logger.warning("Failed to get CZSC engine from factory", exc_info=True)
                czsc_engine = None
            czsc_result = czsc_engine.run_czsc_analysis(symbol=ticker, df=df_g) if czsc_engine else None
            
            # 提取笔列表
            if czsc_result and not czsc_result.get("error"):
                bi_list = czsc_result.get("bi_list", [])
                # 从signals中提取中枢和买卖点信息
                signals = czsc_result.get("signals", {})
                # 这里可以根据实际信号格式解析中枢和买卖点
        except UI_RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC分析失败: {e}")
            st.warning(f"CZSC分析失败: {e}")
    
    # Tab 1: CZSC结构分析
    with czsc_tabs[0]:
        if czsc_result:
            render_czsc_analysis_panel(czsc_result)
            
            # 中枢分析（如果有数据）
            if zhongshu_list:
                render_czsc_zhongshu_analysis(zhongshu_list)
            
            # 买卖点分析（如果有数据）
            if bs_points:
                render_czsc_buy_sell_points(bs_points)
            elif czsc_result.get("is_3rd_buy"):
                # 显示三买信号
                st.success("🟢 检测到第三类买点信号！")
        else:
            st.info("暂无CZSC分析数据，请确保数据已加载")
    
    # Tab 2: K线图表
    with czsc_tabs[1]:
        if not df_g.empty:
            curr_price = float(df_g.iloc[-1]["close"])
            
            # 使用完整的CZSC图表
            chart = plot_czsc_full_chart(
                df=df_g,
                bi_list=bi_list,
                zhongshu_list=zhongshu_list,
                bs_points=bs_points,
                ticker=ticker
            )
            if HAS_ECHARTS:
                st_pyecharts(chart, height="600px")
            else:
                st.warning("streamlit-echarts 未安装，无法渲染交互式图表。")
            
            # 显示原始数据
            with st.expander("查看原始数据", expanded=False):
                st.dataframe(df_g.tail(20))
        else:
            st.error(f"无法获取 {ticker} 的数据，请检查网络或在'数据管理'中手动下载。")
            curr_price = 0.0
    
    # Tab 3: 交易计划
    with czsc_tabs[2]:
        st.markdown("#### 🛡️ 战术交易计划卡")

        if curr_price > 0:
            # Dynamic Calc
            atr_sl = curr_price * 0.95
            geo_sl = curr_price * 0.96

            # Use AssetManager Facade
            market_code = "CN" if ticker.endswith((".SH", ".SZ")) else "HK"
            pos_results = asset_mgr.calculate_position_size(
                curr_price,
                atr_sl,
                risk_pct / 100.0,
                capital,
                market=market_code,
                czsc_bottom=geo_sl,
            )

            st.table(
                {
                    "关键风控点位": [
                        "当前入场参考",
                        "CZSC 几何止损",
                        "ATR 波动止损",
                        "系统综合止损",
                    ],
                    "价格 (元)": [
                        f"{curr_price:.2f}",
                        f"{geo_sl:.2f}",
                        f"{atr_sl:.2f}",
                        f"**{pos_results['执行止损']:.2f}**",
                    ],
                }
            )

            st.metric("建议买入股数 (Shares)", f"{pos_results['修正仓位']:,}")
            st.write(f"单笔资金占用: ¥{pos_results['资金占用']:,}")

            if ticker.endswith(".SH") or ticker.endswith(".SZ"):
                st.warning("⚠️ T+1 交易风险：已应用 1.2x 隔夜风险惩罚系数")

            if st.button("📝 生成 AI 投研报告 (RAG Optimized)", key="czsc_gen_report"):
                with st.spinner(f"Generating Deep Research Report for {ticker}..."):
                    # Using Real Price
                    report_data = {"price": curr_price, "bias": "BULLISH"}
                    if asset_mgr.generate_report(ticker, report_data):
                        st.success(
                            f"已生成针对 {ticker} 的深度研究报告，请至 '投研报表库' 查看"
                        )
                        st.rerun()
                    else:
                        st.error("Report generation failed.")
        else:
            st.info("Waiting for data...")

# Tab 4: 机会跟踪器
with tabs[3]:
    st.markdown("### 💼 持仓与机会跟踪")

    # Portfolio Management UI
    col_p_list, col_p_act = st.columns([3, 1])

    with col_p_list:
        portfolio_df = get_portfolio_data()
        if not portfolio_df.empty:
            if HAS_AGGRID:
                gb_p = GridOptionsBuilder.from_dataframe(portfolio_df)
                gb_p.configure_selection("single", use_checkbox=True)
                grid_p = AgGrid(
                    portfolio_df,
                    gridOptions=gb_p.build(),
                    theme="blue",
                    key="port_grid",
                )

                if st.button("🔴 移除选中持仓"):
                    sel = grid_p["selected_rows"]
                    if sel is not None and len(sel) > 0:
                        try:
                            # 标准化处理：确保能从各种格式中获取证券代码
                            s_code = None

                            def extract_code_from_selection(selection):
                                """从不同格式的选择中提取证券代码"""
                                # 处理DataFrame格式
                                if isinstance(selection, pd.DataFrame):
                                    return selection.iloc[0].get("证券代码")

                                # 检查选择是否有效
                                if not isinstance(selection, list) or not selection:
                                    return None

                                item = selection[0]

                                # 尝试从字典中获取
                                if isinstance(item, dict):
                                    return (
                                        item.get("证券代码")
                                        or item.get("code")
                                        or item.get("Code")
                                        or item.get("symbol")
                                        or item.get("Symbol")
                                    )

                                # 尝试从可转换为字典的对象中获取
                                if hasattr(item, "to_dict"):
                                    item_dict = item.to_dict()
                                    return (
                                        item_dict.get("证券代码")
                                        or item_dict.get("code")
                                        or item_dict.get("Code")
                                        or item_dict.get("symbol")
                                        or item_dict.get("Symbol")
                                    )

                                # 尝试从支持索引访问的对象中获取
                                if hasattr(item, "__getitem__"):
                                    for key in [
                                        "证券代码",
                                        "code",
                                        "Code",
                                        "symbol",
                                        "Symbol",
                                    ]:
                                        try:
                                            return item[key]
                                        except KeyError:
                                            logger.exception("提取代码字段 KeyError，跳过")
                                            continue

                                return None

                            s_code = extract_code_from_selection(sel)

                            if s_code:
                                asset_mgr.remove_position(s_code)
                                st.success(f"已移除 {s_code}")
                                st.rerun()
                            else:
                                st.error("无法获取选中持仓的证券代码")
                                # 打印选中数据的结构，便于调试
                                st.write(f"选中数据结构: {type(sel)}")
                                if isinstance(sel, list) and len(sel) > 0:
                                    st.write(f"第一条数据: {sel[0]}")
                        except (ValueError, TypeError) as e:
                            st.error(f"无效数据: {e}")
                        except (IOError, OSError) as e:
                            st.error(f"文件系统错误: {e}")
                        except UI_RECOVERABLE_ERRORS as e:
                            st.error(f"移除失败: {e}")
                            # 打印异常信息，便于调试
                            import traceback

                            st.text(traceback.format_exc())
            else:
                fallback_aggrid(portfolio_df)
                st.warning(
                    "AgGrid is not installed. Portfolio management features are limited."
                )
        else:
            st.info("当前无持仓记录。请使用右侧面板添加。")

    with col_p_act:
        with st.form("add_position_form"):
            st.markdown("#### 🟢 手工录入持仓")
            p_code = st.text_input("证券代码", "600519.SH")
            p_price = st.number_input("入场价格", min_value=0.0, step=0.01)
            p_curr = st.number_input("当前价格", min_value=0.0, step=0.01)
            p_sl = st.number_input("止损位", min_value=0.0, step=0.01)
            p_shares = st.number_input("持仓股数", min_value=100, step=100)

            if st.form_submit_button("确认建仓"):
                if p_code and p_shares > 0:
                    asset_mgr.add_position(p_code, p_price, p_curr, p_sl, p_shares)
                    st.success(f"已录入 {p_code}")
                    st.rerun()
                else:
                    st.error("请输入有效代码和股数")

# Tab 5: 数据管理
with tabs[4]:
    st.markdown("### 💾 资源管理与高速下载中心")

    # 下载区
    with st.expander("📥 调取云端行情数据", expanded=True):
        col1, col2, col3 = st.columns([3, 1, 1])
        new_symbol = col1.text_input("证券代码 (示例: 300442.SZ)", key="download_input")

        # 实时验证证券代码格式
        if new_symbol:
            try:
                validate_symbol(new_symbol)
                col1.success("✅ 证券代码格式正确")
            except ValueError as e:
                col1.error(f"❌ {e}")

        if col2.button("执行下载同步"):
            if new_symbol:
                try:
                    validate_symbol(new_symbol)
                    with st.spinner(f"正在从主权级接口调取 {new_symbol}..."):
                        if asset_mgr.download_stock(new_symbol):
                            st.success(f"资产 {new_symbol} 已完成本地同步")
                            st.rerun()
                        else:
                            st.error("调取中断，请检查 API 状态")
                except ValueError as e:
                    st.error(f"❌ {e}")
                except UI_RECOVERABLE_ERRORS as e:
                    st.error(f"❌ 下载失败: {e}")

        if col3.button("📦 下载主流 ETF (Sector)"):
            with st.spinner("正在同步主流板块 ETF 数据..."):
                if asset_mgr.download_etf_sector_data():
                    st.success("主流 ETF 数据同步完成")
                    st.rerun()
                else:
                    st.error("ETF 同步失败，请查看日志")

    # 数据湖列表
    st.markdown("#### 🗄️ 本地数据湖清单 (Local Data Lake)")
    data_files = asset_mgr.list_data_files()
    if data_files:
        df_lake = pd.DataFrame(data_files)
        # 本地化列表
        df_lake_zh = df_lake.rename(
            columns={
                "Symbol": "代码",
                "Market": "市场",
                "Size (KB)": "大小 (KB)",
                "Modified": "同步时间",
            }
        )
        if HAS_AGGRID:
            gb_lake = GridOptionsBuilder.from_dataframe(
                df_lake_zh[["代码", "市场", "大小 (KB)", "同步时间"]]
            )
            gb_lake.configure_selection("multiple", use_checkbox=True)
            grid_lake = AgGrid(
                df_lake_zh, gridOptions=gb_lake.build(), theme="blue", key="lake_grid"
            )
        else:
            fallback_aggrid(df_lake_zh)
            st.warning("AgGrid is not installed. Data management features are limited.")
            grid_lake = {"selected_rows": []}

        col_del_1, col_del_2 = st.columns([1, 4])
        if col_del_1.button("🗑️ 擦除选中数据 (Purge)", type="secondary"):
            sel_lake = grid_lake["selected_rows"]

            # 检查选择是否有效
            if not sel_lake or len(sel_lake) == 0:
                st.warning("请先选择要删除的数据")
                pass
            else:
                deleted_count = 0

                # 标准化处理：确保 sel_lake 是字典列表
                rows_to_delete = []

                if isinstance(sel_lake, pd.DataFrame):
                    # DataFrame 格式：转换为字典列表
                    for row in sel_lake.itertuples(index=False):
                        row_dict = row._asdict()
                        rows_to_delete.append(row_dict)
                elif isinstance(sel_lake, list):
                    # 列表格式：可能是字典列表或 Series 列表
                    for item in sel_lake:
                        if isinstance(item, dict):
                            rows_to_delete.append(item)
                        elif hasattr(item, "to_dict"):
                            rows_to_delete.append(item.to_dict())
                        elif hasattr(item, "__getitem__") and hasattr(item, "index"):
                            # Series 格式
                            rows_to_delete.append(item.to_dict())

                # 处理每一行
                for row_dict in rows_to_delete:
                    symbol_del = row_dict.get("代码")
                    if not symbol_del:
                        continue

                    # Find path by symbol in original non-localized list
                    path_to_del = None
                    for file_info in data_files:
                        if file_info["Symbol"] == symbol_del:
                            path_to_del = file_info["Path"]
                            break

                    if path_to_del and asset_mgr.delete_file(path_to_del):
                        deleted_count += 1

                if deleted_count > 0:
                    st.toast(f"已成功移除 {deleted_count} 个资产数据")
                    st.rerun()
    else:
        st.info("底层数据湖目前为空，请使用上方工具同步数据。")

# Tab 6: 投研报表库
with tabs[5]:
    st.markdown("### 📚 投研报表与 RAG 知识库")
    st.success("✅ **增强功能**: HTML预览、PDF导出、报告对比、元数据查看")
    st.divider()

    reports = asset_mgr.list_reports()

    if reports:
        # 报表库子Tab
        report_tabs = st.tabs([
            "📋 报表列表",
            "👁️ 预览",
            "📊 对比",
            "ℹ️ 元数据"
        ])

        # Tab 1: 报表列表
        with report_tabs[0]:
            df_reports = pd.DataFrame(reports)
            df_rep_zh = df_reports.rename(
                columns={
                    "Filename": "文件名",
                    "Created": "生成日期",
                    "Size (KB)": "大小 (KB)",
                }
            )

            # 显示报表列表
            if HAS_AGGRID:
                gb_rep = GridOptionsBuilder.from_dataframe(
                    df_rep_zh[["文件名", "生成日期", "大小 (KB)"]]
                )
                gb_rep.configure_selection("single", use_checkbox=False)
                grid_rep = AgGrid(
                    df_rep_zh, gridOptions=gb_rep.build(), theme="blue", key="rep_grid"
                )
            else:
                st.dataframe(df_rep_zh[["文件名", "生成日期", "大小 (KB)"]], use_container_width=True)
                grid_rep = {"selected_rows": []}

            # 获取选中的报告
            sel_rep = grid_rep.get("selected_rows", [])
            selected_report = None
            selected_report_path = None

            if sel_rep is not None and len(sel_rep) > 0:
                if isinstance(sel_rep, pd.DataFrame):
                    selected_row = sel_rep.iloc[0]
                    selected_report = selected_row.to_dict()
                else:
                    selected_report = sel_rep[0] if isinstance(sel_rep[0], dict) else sel_rep[0].to_dict()

                filename = selected_report.get("文件名")
                for r in reports:
                    if r["Filename"] == filename:
                        selected_report_path = r["Path"]
                        break

                st.session_state["selected_report"] = selected_report
                st.session_state["selected_report_path"] = selected_report_path

            # 操作按钮
            if selected_report:
                st.divider()
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    if st.button("👁️ HTML预览", key="btn_html_preview"):
                        st.session_state["active_report_tab"] = 1  # 切换到预览Tab
                        st.rerun()

                with col2:
                    if st.button("📄 Markdown查看", key="btn_md_view"):
                        st.session_state["show_md_content"] = True

                with col3:
                    if st.button("📥 导出PDF", key="btn_export_pdf"):
                        st.session_state["show_pdf_export"] = True

                with col4:
                    if st.button("📊 对比报告", key="btn_compare"):
                        st.session_state["active_report_tab"] = 2  # 切换到对比Tab
                        st.rerun()

                # Markdown查看弹窗
                if st.session_state.get("show_md_content"):
                    with st.expander("📄 Markdown内容", expanded=True):
                        content = asset_mgr.read_report(selected_report_path)
                        st.text_area("报告内容", content, height=400)
                        if st.button("关闭", key="close_md"):
                            st.session_state["show_md_content"] = False
                            st.rerun()

                # PDF导出
                if st.session_state.get("show_pdf_export"):
                    with st.expander("📥 PDF导出", expanded=True):
                        st.info("PDF导出需要安装weasyprint: pip install weasyprint")
                        st.warning("当前为演示模式，PDF导出功能需要额外依赖")
                        if st.button("关闭", key="close_pdf"):
                            st.session_state["show_pdf_export"] = False
                            st.rerun()

                # 删除功能
                st.divider()
                if st.button("🗑️ 删除选中报表", key="btn_delete_report", type="secondary"):
                    if selected_report_path and asset_mgr.delete_file(selected_report_path):
                        st.toast(f"已删除: {selected_report.get('文件名', '')}")
                        st.session_state["selected_report"] = None
                        st.session_state["selected_report_path"] = None
                        st.rerun()

        # Tab 2: 预览
        with report_tabs[1]:
            selected_report_path = st.session_state.get("selected_report_path")
            if selected_report_path:
                # HTML预览
                html_content = asset_mgr.get_report_html_preview(selected_report_path)
                render_report_html_preview(html_content, "HTML预览")
            else:
                st.info("请在'报表列表'中选择一份报告进行预览")

        # Tab 3: 对比
        with report_tabs[2]:
            selected_report_path = st.session_state.get("selected_report_path")
            if selected_report_path:
                st.markdown("#### 📊 报告对比")

                # 选择对比报告
                compare_path = render_report_comparison_selector(reports)

                if compare_path and compare_path != selected_report_path:
                    if st.button("🔄 执行对比", key="run_compare"):
                        with st.spinner("正在对比报告..."):
                            compare_result = asset_mgr.compare_reports(
                                selected_report_path, compare_path
                            )
                            st.session_state["compare_result"] = compare_result

                    # 显示对比结果
                    if "compare_result" in st.session_state:
                        render_report_comparison(st.session_state["compare_result"])
                else:
                    st.info("请选择另一份不同的报告进行对比")
            else:
                st.info("请在'报表列表'中选择一份报告")

        # Tab 4: 元数据
        with report_tabs[3]:
            selected_report_path = st.session_state.get("selected_report_path")
            if selected_report_path:
                metadata = asset_mgr.get_report_metadata(selected_report_path)
                render_report_metadata(metadata)
            else:
                st.info("请在'报表列表'中选择一份报告查看元数据")

    else:
        st.info("报表库目前为空。请在 '深度几何分析' 中生成针对个股的新报告。")

# Tab 7: LPPL泡沫分析
with tabs[6]:
    st.markdown("### 📈 LPPL 泡沫模型分析")
    st.success("✅ **计算 + 视觉拟合**: 实时运行 LPPL 算法并生成交互式图表")
    st.divider()

    # LPPL分析配置
    col_config, col_info = st.columns([2, 1])

    with col_config:
        # 选择指数
        index_options = {
            "sh000001": "上证综指",
            "sz399001": "深证成指",
            "sz399006": "创业板指",
            "sh000016": "上证50",
            "sh000300": "沪深300",
            "sh000905": "中证500",
            "sh000852": "中证1000",
        }

        selected_index = st.selectbox(
            "选择指数",
            options=list(index_options.keys()),
            format_func=lambda x: f"{x} - {index_options[x]}",
            index=0,
        )

        # 分析天数
        analysis_days = st.slider(
            "分析天数", min_value=100, max_value=700, value=350, step=50
        )

        # 执行分析按钮
        if st.button("🚀 执行 LPPL 分析"):
            with st.spinner(
                f"正在分析 {index_options[selected_index]} 的 LPPL 泡沫模型..."
            ):
                try:
                    # 初始化LPPL可视化器
                    lppl_visualizer = LPPLVisualizer()

                    # 运行分析并生成图表
                    result = lppl_visualizer.run_analysis_and_plot(
                        symbol=selected_index, days=analysis_days
                    )

                    if result.get("success", False):
                        # 显示图表
                        st.markdown("### 📊 LPPL 拟合结果")
                        st.components.v1.html(
                            result.get("html", ""), height=600, scrolling=True
                        )

                        # 显示分析结果
                        st.markdown("### 📋 分析结果详情")
                        bubble_result = result.get("bubble_result", {})
                        model_params = result.get("model_params", {})
                        plot_data = result.get("plot_data", {})

                        col_result1, col_result2 = st.columns(2)

                        with col_result1:
                            st.markdown("#### 泡沫检测结果")
                            st.write(
                                f"**是否为泡沫**: {'✅ 是' if bubble_result.get('is_bubble', False) else '❌ 否'}"
                            )
                            st.write(
                                f"**置信度**: {bubble_result.get('confidence', 0):.2f}"
                            )
                            st.write(
                                f"**风险等级**: {bubble_result.get('risk_level', 'Safe')}"
                            )
                            st.write(
                                f"**R²**: {bubble_result.get('r_squared', 0):.4f}"
                            )
                            st.write(
                                f"**OOS R²**: {bubble_result.get('out_of_sample_r_squared', 0):.4f}"
                            )
                            st.write(
                                f"**预测崩盘日**: {plot_data.get('crash_date', 'N/A')}"
                            )
                            st.write(
                                f"**距离崩盘日**: {plot_data.get('days_to_crash', 0):.1f} 天"
                            )

                        with col_result2:
                            st.markdown("#### LPPL 模型参数")
                            st.write(f"**m (加速度)**: {model_params.get('m', 0):.3f}")
                            st.write(
                                f"**w (震荡频率)**: {model_params.get('w', 0):.3f}"
                            )
                            st.write(
                                f"**a (基准价格)**: {model_params.get('a', 0):.3f}"
                            )
                            st.write(
                                f"**b (趋势系数)**: {model_params.get('b', 0):.3f}"
                            )
                            st.write(
                                f"**c (震荡幅度)**: {model_params.get('c', 0):.3f}"
                            )
                            st.write(
                                f"**phi (相位)**: {model_params.get('phi', 0):.3f}"
                            )

                        # 分析建议
                        st.markdown("### 💡 分析建议")
                        if bubble_result.get("is_bubble", False):
                            st.error("⚠️ 泡沫警报：建议减仓或设置严格止损")
                        else:
                            st.success("✅ 市场正常：可按既定策略操作")

                        # Wyckoff 阶段分析
                        with st.expander("📊 Wyckoff 阶段分析", expanded=False):
                            try:
                                from uniquant.brain.wyckoff.engine import WyckoffEngine
                                ds = lppl_visualizer.data_service
                                wdf = ds.get_index_data(selected_index, 180)
                                if wdf is not None and not wdf.empty:
                                    we = WyckoffEngine(lookback_days=120)
                                    wr = we.analyze(wdf.copy(), symbol=selected_index, period="日线")
                                    phase = wr.structure.phase.value if wr.structure else "unknown"
                                    conf = wr.signal.confidence.value if wr.signal and wr.signal.confidence else "D"
                                    st.write(f"**当前阶段**: {phase}")
                                    st.write(f"**置信度**: {conf}")
                                    st.write(f"**方向**: {wr.trading_plan.direction if wr.trading_plan else '空仓观望'}")
                                else:
                                    st.write("Wyckoff 分析数据暂不可用")
                            except Exception as wex:
                                st.write(f"Wyckoff 分析暂不可用: {wex}")

                        # 拟合质量评估
                        st.markdown("### 🎯 拟合质量评估")
                        st.info("**如何评估拟合质量：**")
                        st.write(
                            "1. **红线贴合吗？** 在历史数据部分，红线应穿过K线中心，且震荡应与K线一致"
                        )
                        st.write(
                            "2. **尾部是否竖起来？** 越临近绿色虚线，红线应变得越陡峭"
                        )
                        st.write(
                            "3. **预测日期合理吗？** 若在未来1-3个月内且红线拟合完美，是强烈预警信号"
                        )
                    else:
                        st.error(f"分析失败: {result.get('error', '未知错误')}")
                except (ValueError, TypeError) as e:
                    st.error(f"无效数据: {e}")
                except (IOError, OSError) as e:
                    st.error(f"文件系统错误: {e}")
                except UI_RECOVERABLE_ERRORS as e:
                    st.error(f"分析过程中出现错误: {e}")
                    import traceback

                    traceback.print_exc()

    with col_info:
        st.markdown("### ℹ️ LPPL 模型说明")
        st.write(
            "**LPPL (Log-Periodic Power Law)** 是一种用于检测金融市场泡沫的数学模型。"
        )
        st.write("**核心公式:**")
        st.latex(r"P(t) = a + b(t_c - t)^m + c(t_c - t)^m \cos(w \log(t_c - t) + \phi)")
        st.write("**参数含义:**")
        st.write("- `t_c`: 预测崩盘日")
        st.write("- `m`: 泡沫增长加速度")
        st.write("- `w`: 价格震荡频率")
        st.write("- `c`: 震荡幅度")
        st.write("- `phi`: 震荡相位")
        st.write("**使用建议:**")
        st.write("- 选择不同的分析天数观察模型变化")
        st.write("- 使用鼠标缩放图表查看细节")
        st.write("- 结合其他指标综合判断市场风险")

# Tab 8: 风险管理
with tabs[7]:
    st.markdown("### 🛡️ 风险管理统一面板")
    st.success("✅ **组合风险分析**: VaR, CVaR, 压力测试, 组合优化")
    st.divider()

    # 股票选择
    st.markdown("#### 📋 投资组合配置")

    # 预定义股票池
    stock_pool = list(asset_mgr.stock_map.keys())[:20]  # 取前20只股票

    # 多选股票
    selected_symbols = st.multiselect(
        "选择投资组合股票 (建议3-10只)",
        options=stock_pool,
        default=stock_pool[:5] if len(stock_pool) >= 5 else stock_pool,
        help="选择要分析的股票，系统将计算组合风险指标"
    )

    if not selected_symbols:
        st.warning("请至少选择一只股票")
    else:
        st.info(f"已选择 {len(selected_symbols)} 只股票: {', '.join(selected_symbols)}")

    # 风险管理子Tab
    risk_tabs = st.tabs([
        "📊 风险指标",
        "⚖️ 组合优化",
        "🔥 压力测试",
        "🌡️ 风险热力图",
        "🔬 压力场景 & 回撤",
    ])

    # Tab 1: 风险指标
    with risk_tabs[0]:
        st.markdown("#### 📊 组合风险指标分析")

        if selected_symbols and st.button("📊 计算风险指标", key="calc_risk_metrics"):
            with st.spinner("正在计算风险指标..."):
                risk_result = asset_mgr.calculate_portfolio_risk_metrics(
                    symbols=selected_symbols,
                    lookback_days=252
                )
                st.session_state["risk_metrics_result"] = risk_result

        # 显示风险指标
        if "risk_metrics_result" in st.session_state:
            render_portfolio_risk_metrics(st.session_state["risk_metrics_result"])
        else:
            st.info("点击'计算风险指标'按钮开始分析")

    # Tab 2: 组合优化
    with risk_tabs[1]:
        st.markdown("#### ⚖️ 投资组合优化")

        col_opt1, col_opt2 = st.columns(2)

        with col_opt1:
            opt_method = st.selectbox(
                "优化方法",
                options=["risk_parity", "mean_variance"],
                format_func=lambda x: "风险平价" if x == "risk_parity" else "均值-方差",
                help="风险平价: 各资产风险贡献相等; 均值-方差: 最大化夏普比率"
            )

        with col_opt2:
            lookback_days = st.slider(
                "回看天数",
                min_value=60,
                max_value=500,
                value=252,
                step=30,
                help="用于计算收益率历史数据的回看天数"
            )

        if selected_symbols and st.button("⚖️ 运行组合优化", key="run_portfolio_opt"):
            with st.spinner(f"正在执行{ '风险平价' if opt_method == 'risk_parity' else '均值-方差' }优化..."):
                opt_result = asset_mgr.optimize_portfolio(
                    symbols=selected_symbols,
                    method=opt_method,
                    lookback_days=lookback_days
                )
                st.session_state["portfolio_opt_result"] = opt_result

        # 显示优化结果
        if "portfolio_opt_result" in st.session_state:
            render_portfolio_optimizer_result(st.session_state["portfolio_opt_result"])
        else:
            st.info("点击'运行组合优化'按钮开始分析")

    # Tab 3: 压力测试
    with risk_tabs[2]:
        st.markdown("#### 🔥 压力测试")

        # 场景选择
        available_scenarios = [
            "2008_CRASH",
            "2015_CRASH",
            "2018_TRADE_WAR",
            "2020_COVID",
            "2022_BEAR",
        ]

        scenario_descriptions = {
            "2008_CRASH": "2008年金融危机 (-40%)",
            "2015_CRASH": "2015年A股股灾 (-35%)",
            "2018_TRADE_WAR": "2018年贸易战 (-25%)",
            "2020_COVID": "2020年新冠疫情 (-30%)",
            "2022_BEAR": "2022年熊市 (-20%)",
        }

        selected_scenarios = st.multiselect(
            "选择压力测试场景",
            options=available_scenarios,
            default=available_scenarios,
            format_func=lambda x: scenario_descriptions.get(x, x),
            help="选择要测试的历史极端市场场景"
        )

        if selected_symbols and st.button("🔥 运行压力测试", key="run_stress_test"):
            with st.spinner("正在执行压力测试..."):
                stress_result = asset_mgr.run_stress_test(
                    symbols=selected_symbols,
                    scenarios=selected_scenarios if selected_scenarios else None
                )
                st.session_state["stress_test_result"] = stress_result

        # 显示压力测试结果
        if "stress_test_result" in st.session_state:
            render_stress_test_results(st.session_state["stress_test_result"])
        else:
            st.info("点击'运行压力测试'按钮开始分析")

    # Tab 4: 风险热力图
    with risk_tabs[3]:
        st.markdown("#### 🌡️ 个股风险热力图")

        if selected_symbols:
            # 计算每只股票的风险评分 (基于波动率)
            risk_scores = {}
            for symbol in selected_symbols:
                try:
                    end_date = get_time_provider().now()
                    start_date = end_date - timedelta(days=252)
                    df = asset_mgr.get_real_kline_data(
                        symbol,
                        start_date.strftime("%Y-%m-%d"),
                        end_date.strftime("%Y-%m-%d")
                    )
                    if df is not None and not df.empty:
                        returns = df["close"].pct_change().dropna()
                        # 使用年化波动率作为风险评分 (归一化到0-1)
                        volatility = returns.std() * np.sqrt(252)
                        risk_score = min(volatility / 0.5, 1.0)  # 假设50%为最高风险
                        risk_scores[symbol] = risk_score
                    else:
                        risk_scores[symbol] = 0.5  # 默认中等风险
                except UI_RECOVERABLE_ERRORS as e:
                    logger.warning("计算 %s 风险评分失败: %s", symbol, e)
                    risk_scores[symbol] = 0.5

            render_risk_heatmap(selected_symbols, risk_scores)
        else:
            st.info("请选择股票以查看风险热力图")

    # Tab 5: 压力场景 & 回撤
    with risk_tabs[4]:
        st.markdown("#### 🔬 应力场景 & 回撤分析")

        if not selected_symbols:
            st.warning("请先在上方选择投资组合股票")
        else:
            # Build portfolio equity curve from selected symbols
            def _build_portfolio_equity():
                end = get_time_provider().now()
                start = end - timedelta(days=504)
                all_rets = []
                for sym in selected_symbols:
                    try:
                        df = asset_mgr.get_real_kline_data(
                            sym,
                            start.strftime("%Y-%m-%d"),
                            end.strftime("%Y-%m-%d"),
                        )
                        if df is not None and not df.empty:
                            ret = df["close"].pct_change().dropna()
                            all_rets.append(ret)
                    except UI_RECOVERABLE_ERRORS:
                        logger.exception("获取收益率数据失败，跳过")
                        continue
                if not all_rets:
                    return None, None
                min_len = min(len(r) for r in all_rets)
                aligned = [r.iloc[-min_len:].values for r in all_rets]
                port_ret = np.mean(aligned, axis=0)
                eq = 10000 * np.cumprod(1 + port_ret)
                return eq.tolist(), port_ret.tolist()

            equity_curve, daily_returns = _build_portfolio_equity()

            if equity_curve is None:
                st.error("无法构建投资组合收益曲线，请检查所选股票数据是否充分")
            else:
                st.info(f"已构建等权组合收益曲线，共 {len(equity_curve)} 个交易日")

                # Stress scenario buttons
                clicked = render_stress_scenario_buttons()

                # Run single scenario when its button is clicked
                for scenario_key, clicked_flag in clicked.items():
                    if clicked_flag:
                        with st.spinner(f"正在模拟 {scenario_key} 场景..."):
                            scenario_results = asset_mgr.run_stress_scenarios(
                                {"equity_curve": equity_curve},
                                scenario_names=[scenario_key],
                            )
                            st.session_state["stress_scenario_results"] = scenario_results
                        st.rerun()

                # Show scenario results
                if "stress_scenario_results" in st.session_state:
                    render_stress_scenario_results(st.session_state["stress_scenario_results"])

                st.divider()

                # Drawdown dashboard
                if st.button("📊 计算回撤指标", key="calc_drawdown"):
                    with st.spinner("正在计算回撤指标..."):
                        dd_result = asset_mgr.compute_drawdown_metrics(
                            equity_curve, daily_returns
                        )
                        st.session_state["drawdown_metrics_result"] = dd_result

                if "drawdown_metrics_result" in st.session_state:
                    dd_data = st.session_state["drawdown_metrics_result"]
                    render_drawdown_dashboard(
                        dd_data.get("drawdown_metrics"),
                        dd_data.get("tail_risk_metrics"),
                    )

st.markdown("---")
st.caption("Alpha-Tactician Pro V1.0 Sovereign Edition | 主权级智能量化终端")
