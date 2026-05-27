
import streamlit as st
from typing import Dict, Any, List, Optional
import pandas as pd

# --- Research Report Components ---

def render_report_html_preview(html_content: str, title: str = "报告预览") -> None:
    """
    渲染报告的HTML预览

    Args:
        html_content: HTML格式的报告内容
        title: 预览标题
    """
    if not html_content:
        st.info("暂无预览内容")
        return

    st.markdown(f"#### {title}")

    # 使用Streamlit的html组件显示
    st.components.v1.html(html_content, height=600, scrolling=True)


def render_report_comparison(compare_result: Dict[str, Any]) -> None:
    """
    渲染报告对比结果

    Args:
        compare_result: 对比结果字典
    """
    if not compare_result or compare_result.get("error"):
        error_msg = compare_result.get("error", "未知错误") if compare_result else "无对比数据"
        st.error(f"对比失败: {error_msg}")
        return

    st.markdown("#### 📊 报告对比结果")

    # 显示统计信息
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("新增行数", compare_result.get("added_lines", 0), delta_color="normal")

    with col2:
        st.metric("删除行数", compare_result.get("removed_lines", 0), delta_color="inverse")

    with col3:
        st.metric("总变化", compare_result.get("total_changes", 0))

    st.divider()

    # 显示diff内容
    diff_content = compare_result.get("diff", "")
    if diff_content:
        st.markdown("#### 📝 详细差异")

        # 使用代码块显示diff
        st.code(diff_content, language="diff")
    else:
        st.info("两份报告内容相同")


def render_report_metadata(metadata: Dict[str, Any]) -> None:
    """
    渲染报告元数据

    Args:
        metadata: 元数据字典
    """
    if not metadata or metadata.get("error"):
        error_msg = metadata.get("error", "未知错误") if metadata else "无元数据"
        st.error(f"获取元数据失败: {error_msg}")
        return

    st.markdown("#### 📋 报告元数据")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**基本信息**")
        st.write(f"📄 文件名: {metadata.get('filename', 'N/A')}")
        st.write(f"📰 标题: {metadata.get('title', 'N/A')}")
        st.write(f"📈 股票代码: {metadata.get('ticker', 'N/A')}")
        st.write(f"📅 报告日期: {metadata.get('report_date', 'N/A')}")

    with col2:
        st.markdown("**文件统计**")
        st.write(f"💾 文件大小: {metadata.get('file_size_kb', 0)} KB")
        st.write(f"🕐 创建时间: {metadata.get('created', 'N/A')}")
        st.write(f"📊 行数: {metadata.get('line_count', 0)}")
        st.write(f"📝 字数: {metadata.get('word_count', 0)}")


def render_report_library_actions(
    selected_report: Optional[Dict[str, Any]],
    reports: List[Dict[str, Any]]
) -> None:
    """
    渲染报表库操作按钮

    Args:
        selected_report: 选中的报告
        reports: 所有报告列表
    """
    if not selected_report:
        st.info("请从上方表格选择一份报告")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("👁️ HTML预览", key="report_html_preview"):
            st.session_state["show_html_preview"] = True

    with col2:
        if st.button("📄 Markdown查看", key="report_md_view"):
            st.session_state["show_md_view"] = True

    with col3:
        if st.button("📥 导出PDF", key="report_export_pdf"):
            st.session_state["export_pdf"] = True

    with col4:
        if st.button("📊 对比报告", key="report_compare"):
            st.session_state["show_compare"] = True


def render_report_comparison_selector(reports: List[Dict[str, Any]]) -> Optional[str]:
    """
    渲染报告对比选择器

    Args:
        reports: 报告列表

    Returns:
        选中的报告路径或None
    """
    if len(reports) < 2:
        st.warning("需要至少两份报告才能进行对比")
        return None

    st.markdown("#### 🔄 选择要对比的报告")

    report_options = {r["Filename"]: r["Path"] for r in reports}

    selected = st.selectbox(
        "选择对比报告",
        options=list(report_options.keys()),
        help="选择要与当前报告进行对比的另一份报告"
    )

    return report_options.get(selected)


# --- Portfolio Risk Components ---

def render_portfolio_risk_metrics(risk_data: Dict[str, Any]) -> None:
    """渲染投资组合风险指标面板"""
    if not risk_data or risk_data.get("status") != "success":
        st.warning("暂无风险指标数据")
        return

    st.markdown("### 📊 组合风险指标")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        var_95 = risk_data.get("var_95", 0)
        st.metric("VaR 95%", f"{var_95:.2%}", help="95%置信区间下的最大可能损失")

    with col2:
        cvar_95 = risk_data.get("cvar_95", 0)
        st.metric("CVaR 95%", f"{cvar_95:.2%}", help="超过VaR时的平均损失")

    with col3:
        max_dd = risk_data.get("max_drawdown", 0)
        st.metric("最大回撤", f"{max_dd:.2%}", help="历史最大回撤幅度")

    with col4:
        regime = risk_data.get("regime", "NORMAL")
        regime_colors = {"NORMAL": "🟢", "STRESSED": "🟡", "FROZEN": "🔴"}
        st.metric("市场状态", f"{regime_colors.get(regime, '⚪')} {regime}")


def render_portfolio_optimizer_result(opt_result: Dict[str, Any]) -> None:
    """渲染组合优化结果"""
    if not opt_result or opt_result.get("status") != "success":
        st.warning("暂无优化结果")
        return

    st.markdown("### ⚖️ 组合优化结果")

    weights = opt_result.get("weights", {})
    if weights:
        df_weights = pd.DataFrame(list(weights.items()), columns=["股票", "权重"])
        df_weights = df_weights.sort_values("权重", ascending=False)
        st.dataframe(df_weights, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("预期收益", f"{opt_result.get('expected_return', 0):.2%}")
    with col2:
        st.metric("波动率", f"{opt_result.get('volatility', 0):.2%}")
    with col3:
        st.metric("夏普比率", f"{opt_result.get('sharpe_ratio', 0):.2f}")


def render_stress_test_results(stress_result: Dict[str, Any]) -> None:
    """渲染压力测试结果"""
    if not stress_result or stress_result.get("status") != "success":
        st.warning("暂无压力测试结果")
        return

    st.markdown("### 🔥 压力测试结果")

    scenarios = stress_result.get("scenarios", {})
    if scenarios:
        df_stress = pd.DataFrame(list(scenarios.items()), columns=["场景", "损失金额"])
        df_stress = df_stress.sort_values("损失金额")
        st.dataframe(df_stress, use_container_width=True)


def render_risk_heatmap(symbols: List[str], risk_scores: Dict[str, float]) -> None:
    """渲染风险热力图"""
    if not risk_scores:
        st.warning("暂无风险数据")
        return

    st.markdown("### 🌡️ 风险热力图")

    df_risk = pd.DataFrame(list(risk_scores.items()), columns=["股票", "风险分数"])
    df_risk = df_risk.sort_values("风险分数", ascending=False)
    st.dataframe(df_risk, use_container_width=True)


# --- Scan Components ---

def render_scan_config_panel() -> Dict[str, Any]:
    """渲染扫描配置面板"""
    st.markdown("### ⚙️ 扫描配置")

    col1, col2 = st.columns(2)
    with col1:
        top_n = st.slider("选取Top N", 10, 100, 50)
    with col2:
        factors = st.multiselect("因子选择", ["value", "growth", "quality", "momentum"], default=["value", "growth"])

    return {"top_n": top_n, "factors": factors}


def render_stock_rankings(rankings: pd.DataFrame) -> None:
    """渲染股票排行榜"""
    if rankings.empty:
        st.warning("暂无排名数据")
        return

    st.markdown("### 📈 股票排行榜")
    st.dataframe(rankings, use_container_width=True)


def render_tech_signals_summary(signals: Dict[str, Any]) -> None:
    """渲染技术信号摘要"""
    if not signals:
        st.warning("暂无技术信号")
        return

    st.markdown("### 📊 技术信号摘要")

    buy_signals = signals.get("buy_signals", [])
    sell_signals = signals.get("sell_signals", [])

    col1, col2 = st.columns(2)
    with col1:
        st.success(f"买入信号: {len(buy_signals)}个")
    with col2:
        st.error(f"卖出信号: {len(sell_signals)}个")


# --- IC/IR Components ---

def render_ic_ir_heatmap(ic_ir_data: Dict[str, Any]) -> None:
    """渲染IC/IR热力图"""
    if not ic_ir_data:
        st.warning("暂无IC/IR数据")
        return

    st.markdown("### 🔥 IC/IR热力图")

    ic_df = ic_ir_data.get("ic_analysis")
    if ic_df is not None and not ic_df.empty:
        st.dataframe(ic_df, use_container_width=True)


# --- Structural Risk Components ---

def render_structural_risk_gauges(risks: Dict[str, Any]) -> None:
    """渲染结构风险仪表盘"""
    if not risks:
        st.warning("暂无风险数据")
        return

    st.markdown("### 🎯 结构风险仪表盘")

    for risk_name, risk_value in risks.items():
        col1, col2 = st.columns([1, 2])
        with col1:
            st.write(risk_name)
        with col2:
            st.progress(risk_value)


# --- CZSC Components ---

def render_czsc_analysis_panel(czsc_data: Dict[str, Any]) -> None:
    """渲染缠论分析面板"""
    if not czsc_data:
        st.warning("暂无缠论数据")
        return

    st.markdown("### 📿 缠论分析")

    bi_count = czsc_data.get("bi_count", 0)
    st.metric("笔数量", bi_count)


def render_czsc_zhongshu_analysis(zhongshu_list: List[Dict]) -> None:
    """渲染中枢分析"""
    if not zhongshu_list:
        st.info("暂无中枢")
        return

    st.markdown("### 中枢分析")
    for zs in zhongshu_list:
        st.write(f"中枢: {zs.get('range', 'N/A')}")


def render_czsc_buy_sell_points(bs_points: List[Dict]) -> None:
    """渲染买卖点"""
    if not bs_points:
        st.info("暂无买卖点")
        return

    st.markdown("### 买卖点")
    for point in bs_points:
        st.write(f"{point.get('type', 'N/A')}: {point.get('price', 'N/A')}")


def plot_czsc_full_chart(symbol: str, czsc_data: Dict[str, Any]) -> None:
    """绘制完整缠论图表"""
    st.markdown(f"### 📿 {symbol} 缠论图表")
    st.info("缠论图表需要专门的渲染组件")


# --- Anti-Fragile Components ---

def render_anti_fragile_metrics(evt_stats: Dict[str, Any], ntf_detected: bool = False) -> None:
    """渲染反脆弱性指标"""
    if not evt_stats:
        st.warning("暂无反脆弱性指标")
        return

    st.markdown("### 🛡️ 反脆弱性指标")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("VaR", f"{evt_stats.get('var_95', 0):.2%}")
    with col2:
        st.metric("CVaR", f"{evt_stats.get('cvar_95', 0):.2%}")

    if ntf_detected:
        st.warning("⚠️ 检测到NTF干预信号")


# --- FSM Components ---

def render_fsm_status_panel(
    current_state: str,
    state_desc: str,
    transition_reason: str,
    ma_status: str,
    next_states: List[str],
    timestamp: str
) -> None:
    """渲染FSM状态面板"""
    st.markdown("### 🔄 FSM状态")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("当前状态", current_state, state_desc)
    with col2:
        st.metric("更新时间", str(timestamp)[:19])  # Trim microseconds if it's a string/datetime

    st.info(f"**流转原因**: {transition_reason}")
    st.write(f"**均线状态**: {ma_status}")
    st.write(f"**可能流转至**: {', '.join(next_states) if next_states else '无'}")


def render_fsm_state_history(history: List[Dict]) -> None:
    """渲染FSM状态历史"""
    if not history:
        st.info("暂无状态历史")
        return

    st.markdown("### 📜 FSM状态历史")

    df_history = pd.DataFrame(history)
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)


# --- Health Check Components ---

def render_health_metrics(network_ok: bool, lake_ok: bool, engine_ok: bool, kb_ok: bool = True, regime: str = "NORMAL") -> None:
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
