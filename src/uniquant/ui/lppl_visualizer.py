# Configure logging
from datetime import datetime, timedelta
from typing import Any, Dict

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ...brain.lppl.engine import LPPLEngine
from ...data.services.lppl_data_service import LPPLDataService
from ...shared.logger_factory import get_logger

logger = get_logger("LPPLVisualizer")


class LPPLVisualizer:
    """
    LPPL可视化模块，用于计算和绘制LPPL拟合曲线
    """

    def __init__(self):
        self.lppl_engine = LPPLEngine()
        self.data_service = LPPLDataService()

    def run_analysis_and_plot(
        self, symbol: str = "sh000001", days: int = 350
    ) -> Dict[str, Any]:
        """
        运行LPPL分析并生成可视化图表

        Args:
            symbol: 指数代码
            days: 分析的天数

        Returns:
            包含分析结果和图表数据的字典
        """
        logger.info("正在分析 %s 数据...", symbol)

        # 获取数据
        df = self.data_service.get_index_data(symbol, days)

        if df.empty:
            logger.error("获取 %s 数据失败", symbol)
            return {"success": False, "error": "数据获取失败"}

        # 保存原始日期信息
        original_index = df.tail(days).index

        # 准备拟合数据
        df_fit = df.tail(days).copy()
        df_fit.reset_index(drop=True, inplace=True)

        # 如果原始索引是日期类型，添加到df_fit中
        if hasattr(original_index, "dtype") and "datetime" in str(original_index.dtype):
            df_fit["original_date"] = original_index

        t_data = np.arange(len(df_fit))
        price_data = df_fit["close"].values
        log_price_data = np.log(price_data)

        # 运行LPPL拟合
        logger.info("开始计算 LPPL 参数...")
        bubble_result = self.lppl_engine.detect_bubble(df_fit, column="close")

        if (
            not bubble_result.get("is_bubble", False)
            and bubble_result.get("confidence", 0) < 0.5
        ):
            logger.warning("LPPL拟合结果置信度较低")

        # 提取参数
        model_params = bubble_result.get("model_params", {})
        tc = bubble_result.get("tc", len(df_fit) + 30)
        m = model_params.get("m", 0.5)
        w = model_params.get("w", 10)
        a = model_params.get("a", np.mean(log_price_data))
        b = model_params.get("b", -1)
        c = model_params.get("c", 0.5)
        phi = model_params.get("phi", 0)

        logger.info("拟合完成，准备生成可视化...")

        # 生成可视化用的曲线数据
        plot_data = self._generate_plot_data(df_fit, t_data, tc, m, w, a, b, c, phi)

        # 创建图表
        fig = self._create_plot(df_fit, plot_data, symbol, bubble_result)

        # 生成HTML
        html = fig.to_html(full_html=False, include_plotlyjs="cdn")

        return {
            "success": True,
            "symbol": symbol,
            "days": days,
            "bubble_result": bubble_result,
            "model_params": model_params,
            "html": html,
            "plot_data": plot_data,
        }

    def _lppl_func(self, t, tc, m, w, a, b, c, phi):
        """LPPL函数实现"""
        tau = tc - t
        tau = np.maximum(tau, 1e-8)  # 避免数学错误
        return a + b * (tau**m) + c * (tau**m) * np.cos(w * np.log(tau) + phi)

    def _generate_plot_data(self, df_fit, t_data, tc, m, w, a, b, c, phi):
        """
        生成可视化用的曲线数据

        Args:
            df_fit: 拟合数据
            t_data: 时间数据
            tc: 临界时间
            m, w, a, b, c, phi: LPPL参数

        Returns:
            包含绘图数据的字典
        """
        # 生成时间轴
        current_t = len(df_fit)
        t_future_limit = int(tc)
        t_plot = np.linspace(0, t_future_limit, t_future_limit + 1)

        # 计算对数预测值
        log_prediction = self._lppl_func(t_plot, tc, m, w, a, b, c, phi)

        # 还原为真实价格
        price_prediction = np.exp(log_prediction)

        # 处理日期
        last_real_date = None

        # 首先尝试从索引获取
        if hasattr(df_fit.index, "dtype") and "datetime" in str(df_fit.index.dtype):
            try:
                last_real_date = pd.to_datetime(df_fit.index[-1])
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("从索引获取日期失败: %s", e)

        # 尝试其他可能的日期列
        if last_real_date is None:
            date_columns = [
                "date",
                "date_col",
                "Date",
                "datetime",
                "time",
                "trade_date",
                "original_date",
            ]
            for col in date_columns:
                if col in df_fit.columns:
                    try:
                        last_real_date = pd.to_datetime(df_fit[col].iloc[-1])
                        break
                    except (ValueError, KeyError, TypeError):
                        continue

        # 如果仍然找不到日期列，使用当前日期
        if last_real_date is None:
            logger.warning("无法找到日期列，使用当前日期")
            last_real_date = datetime.now()

        # 生成对应的日期列表
        plot_dates = []
        for t_idx in t_plot:
            if t_idx < current_t:
                date_found = False
                # 尝试从索引获取
                if hasattr(df_fit.index, "dtype") and "datetime" in str(
                    df_fit.index.dtype
                ):
                    try:
                        plot_dates.append(df_fit.index[int(t_idx)])
                        date_found = True
                    except (ValueError, KeyError, TypeError, IndexError) as e:
                        logger.debug("从索引获取绘图日期失败: %s", e)

                # 尝试从列获取
                if not date_found:
                    date_columns = [
                        "date",
                        "date_col",
                        "Date",
                        "datetime",
                        "time",
                        "trade_date",
                        "original_date",
                    ]
                    for col in date_columns:
                        if col in df_fit.columns:
                            try:
                                plot_dates.append(df_fit[col].iloc[int(t_idx)])
                                date_found = True
                                break
                            except (ValueError, KeyError, TypeError, IndexError):
                                continue

                # 如果都没有，使用计算的日期
                if not date_found:
                    days_ahead = int(t_idx - current_t)
                    future_date = last_real_date + timedelta(days=days_ahead * 1.4)
                    plot_dates.append(future_date)
            else:
                # 未来的日期
                days_ahead = int(t_idx - current_t)
                future_date = last_real_date + timedelta(
                    days=days_ahead * 1.4
                )  # 简单估算交易日
                plot_dates.append(future_date)

        return {
            "t_plot": t_plot,
            "price_prediction": price_prediction,
            "plot_dates": plot_dates,
            "crash_date": plot_dates[-1],
            "days_to_crash": tc - current_t,
        }

    def _create_plot(self, df_fit, plot_data, symbol, bubble_result):
        """
        创建Plotly图表

        Args:
            df_fit: 拟合数据
            plot_data: 绘图数据
            symbol: 指数代码
            bubble_result: 泡沫检测结果

        Returns:
            Plotly图表对象
        """
        fig = go.Figure()

        # 添加K线
        if (
            "open" in df_fit.columns
            and "high" in df_fit.columns
            and "low" in df_fit.columns
        ):
            # 使用真实日期作为x轴
            if hasattr(df_fit.index, "dtype") and "datetime" in str(df_fit.index.dtype):
                dates = df_fit.index
            elif "date" in df_fit.columns:
                dates = df_fit["date"]
            elif "date_col" in df_fit.columns:
                dates = df_fit["date_col"]
            else:
                # 如果都没有，使用默认数字索引
                dates = df_fit.index

            fig.add_trace(
                go.Candlestick(
                    x=dates,
                    open=df_fit["open"],
                    high=df_fit["high"],
                    low=df_fit["low"],
                    close=df_fit["close"],
                    name="实际K线",
                )
            )
        else:
            # 如果没有K线数据，只添加收盘价
            if hasattr(df_fit.index, "dtype") and "datetime" in str(df_fit.index.dtype):
                dates = df_fit.index
            elif "date" in df_fit.columns:
                dates = df_fit["date"]
            elif "date_col" in df_fit.columns:
                dates = df_fit["date_col"]
            else:
                # 如果都没有，使用默认数字索引
                dates = df_fit.index

            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=df_fit["close"],
                    mode="lines",
                    name="收盘价",
                    line=dict(color="gray"),
                )
            )

        # 添加LPPL拟合曲线
        fig.add_trace(
            go.Scatter(
                x=plot_data["plot_dates"],
                y=plot_data["price_prediction"],
                mode="lines",
                name="LPPL 模型拟合线",
                line=dict(color="red", width=2),
                opacity=0.8,
            )
        )

        # 标记崩盘日
        crash_date = plot_data["crash_date"]
        fig.add_vline(
            x=crash_date,
            line_dash="dash",
            line_color="green",
            annotation_text="预测崩盘点 (tc)",
        )

        # 设置布局
        fig.update_layout(
            title=f"{symbol} LPPL 泡沫模型拟合分析",
            yaxis_title="价格",
            xaxis_title="日期",
            template="plotly_dark",
            xaxis_rangeslider_visible=False,
            height=600,
            annotations=[
                dict(
                    x=0.05,
                    y=0.95,
                    xref="paper",
                    yref="paper",
                    text=f"置信度: {bubble_result.get('confidence', 0):.2f}<br>风险等级: {bubble_result.get('risk_level', 'Safe')}",
                    showarrow=False,
                    font=dict(size=12),
                    bgcolor="rgba(0, 0, 0, 0.5)",
                    bordercolor="rgba(255, 255, 255, 0.3)",
                    borderwidth=1,
                )
            ],
        )

        return fig

    def generate_chart(self, symbol: str = "sh000001", days: int = 350) -> str:
        """
        生成LPPL可视化图表的HTML

        Args:
            symbol: 指数代码
            days: 分析的天数

        Returns:
            图表的HTML字符串
        """
        result = self.run_analysis_and_plot(symbol, days)

        if result.get("success", False):
            return result.get("html", "")
        else:
            return f"<div style='color: red;'>错误: {result.get('error', '未知错误')}</div>"
