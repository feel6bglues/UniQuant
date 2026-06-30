from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger
from ...shared.time_provider import get_time_provider

if TYPE_CHECKING:
    from .result import BacktestResult

logger = get_logger(__name__)


class BacktestReportGenerator:
    """
    回测报告生成器
    
    生成包含以下内容的 HTML 报告:
    - 绩效指标总览
    - 权益曲线图
    - 回撤曲线图
    - 交易统计
    """

    def __init__(self):
        pass

    def generate(self, results: Dict[str, Any], output_path: str, backtest_result: Optional[BacktestResult] = None) -> str:
        """
        生成完整回测 HTML 报告
        
        Args:
            results: 回测结果字典，包含 metrics, equity_curve, trades 等
            output_path: 输出文件路径
            backtest_result: 可选的 BacktestResult 对象，包含 drawdown/tail/stress 指标
            
        Returns:
            生成的 HTML 文件路径
        """
        metrics = results.get("metrics", {})
        equity = results.get("equity_curve", pd.Series(dtype=float))
        trades = results.get("trades", pd.DataFrame())

        sections = [
            self._create_header(),
            self._create_performance_section(metrics),
            self._create_equity_curve_chart(equity),
            self._create_drawdown_chart(self._compute_drawdown(equity)),
            self._create_trade_summary(trades),
        ]

        if backtest_result is not None:
            if backtest_result.drawdown_metrics is not None:
                sections.append(self._create_drawdown_metrics_section(backtest_result.drawdown_metrics))
            if backtest_result.tail_risk_metrics is not None:
                sections.append(self._create_tail_risk_section(backtest_result.tail_risk_metrics))
            if backtest_result.stress_test_results:
                sections.append(self._create_stress_test_section(backtest_result.stress_test_results))

        sections.append(self._create_footer())

        html_content = "\n".join(sections)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"回测报告已生成: {output_path}")
        return output_path

    def _create_header(self) -> str:
        """创建 HTML 头部"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; color: #333; background: #f8f9fa; }}
h1 {{ color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }}
h2 {{ color: #16213e; margin-top: 30px; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th, td {{ padding: 10px 15px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #1a1a2e; color: white; font-weight: 500; }}
tr:hover {{ background: #f1f1f1; }}
.metric-card {{ display: inline-block; margin: 8px; padding: 15px 20px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 160px; }}
.metric-value {{ font-size: 24px; font-weight: bold; color: #e94560; }}
.metric-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
.positive {{ color: #27ae60; }}
.negative {{ color: #e74c3c; }}
.chart-container {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
</style>
</head>
<body>
<h1>回测报告</h1>
<p>生成时间: {get_time_provider().now().strftime("%Y-%m-%d %H:%M:%S")}</p>"""

    def _create_performance_section(self, metrics: Dict[str, Any]) -> str:
        """创建绩效指标部分"""
        if not metrics:
            return "<h2>绩效指标</h2><p>无可用指标</p>"

        def fmt(val: Any, is_pct: bool = False) -> str:
            if val is None or val == float("inf"):
                return "N/A"
            if is_pct:
                return f'{val:.2%}'
            if isinstance(val, float):
                return f'{val:.2f}'
            return str(val)

        def pct_class(val: Any) -> str:
            if isinstance(val, (int, float)) and val > 0:
                return "positive"
            return ""

        return f"""<h2>绩效指标</h2>
<div style="display: flex; flex-wrap: wrap;">
<div class="metric-card"><div class="metric-value {pct_class(metrics.get('total_return', 0))}">{fmt(metrics.get('total_return'), True)}</div><div class="metric-label">总收益率</div></div>
<div class="metric-card"><div class="metric-value {pct_class(metrics.get('annualized_return', 0))}">{fmt(metrics.get('annualized_return'), True)}</div><div class="metric-label">年化收益率</div></div>
<div class="metric-card"><div class="metric-value">{fmt(metrics.get('volatility'), True)}</div><div class="metric-label">年化波动率</div></div>
<div class="metric-card"><div class="metric-value {pct_class(metrics.get('sharpe_ratio', 0))}">{fmt(metrics.get('sharpe_ratio'))}</div><div class="metric-label">夏普比率</div></div>
<div class="metric-card"><div class="metric-value negative">{fmt(metrics.get('max_drawdown'), True)}</div><div class="metric-label">最大回撤</div></div>
<div class="metric-card"><div class="metric-value {pct_class(metrics.get('calmar_ratio', 0))}">{fmt(metrics.get('calmar_ratio'))}</div><div class="metric-label">Calmar 比率</div></div>
<div class="metric-card"><div class="metric-value">{fmt(metrics.get('win_rate'), True)}</div><div class="metric-label">胜率</div></div>
<div class="metric-card"><div class="metric-value">{fmt(metrics.get('profit_factor'))}</div><div class="metric-label">盈亏比</div></div>
</div>
<table>
<tr><th>指标</th><th>值</th></tr>
<tr><td>总交易次数</td><td>{metrics.get('total_trades', 0)}</td></tr>
<tr><td>盈利交易</td><td>{metrics.get('winning_trades', 0)}</td></tr>
<tr><td>亏损交易</td><td>{metrics.get('losing_trades', 0)}</td></tr>
</table>"""

    def _compute_drawdown(self, equity: pd.Series) -> pd.Series:
        """计算回撤序列"""
        if equity.empty:
            return pd.Series(dtype=float)
        rolling_max = equity.expanding().max()
        drawdown = (equity - rolling_max) / rolling_max
        return drawdown

    def _create_equity_curve_chart(self, equity: pd.Series) -> str:
        """使用内联 SVG 创建权益曲线图"""
        if equity.empty or len(equity) < 2:
            return '<div class="chart-container"><h2>权益曲线</h2><p>无数据</p></div>'

        svg = self._series_to_svg(equity, "权益曲线", "#e94560")

        return f"""<div class="chart-container">
<h2>权益曲线</h2>
{svg}
</div>"""

    def _create_drawdown_chart(self, drawdown: pd.Series) -> str:
        """使用内联 SVG 创建回撤曲线图"""
        if drawdown.empty or len(drawdown) < 2:
            return '<div class="chart-container"><h2>回撤曲线</h2><p>无数据</p></div>'

        svg = self._series_to_svg(drawdown, "回撤曲线", "#e74c3c")

        return f"""<div class="chart-container">
<h2>回撤曲线</h2>
{svg}
</div>"""

    def _series_to_svg(self, series: pd.Series, title: str, color: str, width: int = 800, height: int = 300) -> str:
        """将 Series 渲染为 SVG 折线图"""
        values = series.dropna().values
        if len(values) < 2:
            return "<p>数据点不足</p>"

        padding = 40
        plot_w = width - padding * 2
        plot_h = height - padding * 2

        v_min = np.min(values)
        v_max = np.max(values)
        v_range = v_max - v_min if v_max != v_min else 1

        points: List[str] = []
        for i, v in enumerate(values):
            x = padding + (i / max(len(values) - 1, 1)) * plot_w
            y = padding + plot_h - ((v - v_min) / v_range) * plot_h
            points.append(f"{x:.1f},{y:.1f}")

        polyline = " ".join(points)
        y_ticks = 5
        tick_labels = ""
        grid_lines = ""
        for i in range(y_ticks + 1):
            y = padding + (i / y_ticks) * plot_h
            val = v_max - (i / y_ticks) * v_range
            tick_labels += f'<text x="{padding - 8}" y="{y + 4}" text-anchor="end" font-size="10" fill="#666">{val:.2f}</text>'
            grid_lines += f'<line x1="{padding}" y1="{y}" x2="{padding + plot_w}" y2="{y}" stroke="#eee" stroke-width="1"/>'

        zero_y = padding + plot_h - ((0 - v_min) / v_range) * plot_h
        zero_line = ""
        if v_min <= 0 <= v_max:
            zero_line = f'<line x1="{padding}" y1="{zero_y}" x2="{padding + plot_w}" y2="{zero_y}" stroke="#ccc" stroke-width="1" stroke-dasharray="4,4"/>'

        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="{height}">
<rect width="{width}" height="{height}" fill="white"/>
{grid_lines}
{zero_line}
{tick_labels}
<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>
</svg>"""

    def _create_trade_summary(self, trades: pd.DataFrame) -> str:
        """创建交易统计表格"""
        if trades.empty:
            return '<div class="chart-container"><h2>交易统计</h2><p>无交易记录</p></div>'

        table_rows = ""
        for trade in trades.itertuples():
            table_rows += "<tr>"
            for col in trades.columns:
                val = getattr(trade, col)
                if isinstance(val, float):
                    table_rows += f"<td>{val:.4f}</td>"
                else:
                    table_rows += f"<td>{val}</td>"
            table_rows += "</tr>"

        cols = "".join(f"<th>{c}</th>" for c in trades.columns)

        return f"""<div class="chart-container">
<h2>交易统计</h2>
<table><thead><tr>{cols}</tr></thead><tbody>{table_rows}</tbody></table>
</div>"""

    def _create_drawdown_metrics_section(self, dd: Any) -> str:
        return f"""<h2>回撤分析</h2>
<div style="display: flex; flex-wrap: wrap;">
<div class="metric-card"><div class="metric-value negative">{dd.max_drawdown:.2%}</div><div class="metric-label">最大回撤</div></div>
<div class="metric-card"><div class="metric-value">{dd.max_drawdown_duration}</div><div class="metric-label">最大回撤持续(天)</div></div>
<div class="metric-card"><div class="metric-value">{dd.calmar_ratio:.2f}</div><div class="metric-label">Calmar 比率</div></div>
<div class="metric-card"><div class="metric-value">{dd.ulcer_index:.4f}</div><div class="metric-label">Ulcer 指数</div></div>
<div class="metric-card"><div class="metric-value negative">{dd.rolling_mdd_60d:.2%}</div><div class="metric-label">滚动MDD(60d)</div></div>
<div class="metric-card"><div class="metric-value negative">{dd.rolling_mdd_120d:.2%}</div><div class="metric-label">滚动MDD(120d)</div></div>
<div class="metric-card"><div class="metric-value negative">{dd.rolling_mdd_252d:.2%}</div><div class="metric-label">滚动MDD(252d)</div></div>
</div>"""

    def _create_tail_risk_section(self, tr: Any) -> str:
        return f"""<h2>尾部风险</h2>
<div style="display: flex; flex-wrap: wrap;">
<div class="metric-card"><div class="metric-value">{tr.var_95:.2%}</div><div class="metric-label">VaR(95%)</div></div>
<div class="metric-card"><div class="metric-value">{tr.var_99:.2%}</div><div class="metric-label">VaR(99%)</div></div>
<div class="metric-card"><div class="metric-value">{tr.cvar_95:.2%}</div><div class="metric-label">CVaR(95%)</div></div>
<div class="metric-card"><div class="metric-value">{tr.cvar_99:.2%}</div><div class="metric-label">CVaR(99%)</div></div>
<div class="metric-card"><div class="metric-value">{tr.tail_ratio:.2f}</div><div class="metric-label">Tail Ratio</div></div>
<div class="metric-card"><div class="metric-value">{tr.skewness:.2f}</div><div class="metric-label">偏度</div></div>
<div class="metric-card"><div class="metric-value">{tr.kurtosis:.2f}</div><div class="metric-label">峰度</div></div>
</div>"""

    def _create_stress_test_section(self, stress_results: Dict[str, Any]) -> str:
        rows = ""
        for scenario, result in stress_results.items():
            status = "已恢复" if result.recovered else "未恢复"
            rows += f"""<tr><td>{result.scenario}</td><td class="negative">{result.loss_pct:.2%}</td><td class="negative">{result.loss_value:,.2f}</td><td>{status}</td><td>{result.recovery_days}</td></tr>"""
        return f"""<h2>压力测试</h2>
<table>
<thead><tr><th>场景</th><th>损失比例</th><th>损失金额</th><th>恢复状态</th><th>恢复天数</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""

    def _create_footer(self) -> str:
        """创建 HTML 页脚"""
        return """<div class="footer">
<p>UniQuant 回测报告 &copy; 2026</p>
</div>
</body>
</html>"""
