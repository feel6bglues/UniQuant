from datetime import timedelta
from typing import Any, Dict

import matplotlib

matplotlib.use("Agg")  # 强制使用非交互式后端
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class LPPLVisualizer:
    """
    LPPL可视化器
    负责LPPL结果的可视化
    """

    @handle_errors(
        AnalysisError, Exception, default_return=None, log_level=logger.error
    )
    def visualize_fit(
        self, df: pd.DataFrame, result: Dict[str, Any], symbol_name: str
    ) -> str:
        """
        可视化拟合结果

        Args:
            df: 数据DataFrame
            result: LPPL拟合结果
            symbol_name: 证券名称

        Returns:
            图表保存路径
        """
        try:
            params = result["params"]
            window = result["window"]
            tc, m, w, a, b, c, phi = params

            # 准备数据
            df_plot = df.tail(window).copy()
            price_real = df_plot["close"].values

            # 生成预测价格线，包含未来预测
            days_forward = int(tc - len(df_plot)) + 5
            t_future = np.arange(0, len(df_plot) + days_forward)
            log_pred = self._calculate_lppl(t_future, tc, m, w, a, b, c, phi)
            price_pred = np.exp(log_pred)

            # 生成日期索引
            last_date = df_plot["date"].iloc[-1]
            future_dates = [
                last_date + timedelta(days=i) for i in range(1, days_forward + 1)
            ]
            all_dates = list(df_plot["date"]) + future_dates
            crash_date = (
                all_dates[int(tc)] if int(tc) < len(all_dates) else all_dates[-1]
            )

            # 绘图
            plt.figure(figsize=(12, 6))
            plt.plot(df_plot["date"], price_real, "k.", alpha=0.5, label="实际价格")
            plt.plot(
                all_dates,
                price_pred,
                "r-",
                linewidth=2,
                label=f"LPPL拟合 (m={m:.2f}, w={w:.1f})",
            )

            # 崩溃线
            plt.axvline(
                x=crash_date,
                color="g",
                linestyle="--",
                linewidth=2,
                label=f'崩溃目标: {crash_date.strftime("%Y-%m-%d")}',
            )

            plt.title(f"{symbol_name} - LPPL泡沫检测 ({result['span']})", fontsize=14)
            plt.xlabel("日期")
            plt.ylabel("价格")
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.ylim(min(price_real) * 0.9, max(price_real) * 1.2)

            # 保存图片
            img_name = f"lppl_chart_{symbol_name}_{result['span'].split(' ')[0]}.png"
            plt.savefig(img_name)
            logger.info(f"  [图表] 已保存至 {img_name}")
            # plt.show() # 如果需要在界面显示可取消注释，但在服务器运行时可能会报错
            plt.close()

            return img_name
        except Exception as e:
            logger.error(f"Error visualizing fit: {e}")
            return None

    def _calculate_lppl(self, t, tc, m, w, a, b, c, phi):
        """
        计算LPPL模型值

        Args:
            t: 时间序列
            tc: 临界点时间
            m: 缩放指数
            w: 角频率
            a: 常数项
            b: 线性项系数
            c: 周期性项系数
            phi: 相位角

        Returns:
            LPPL模型值
        """
        tau = tc - t
        valid = tau > 0
        tau = np.where(valid, tau, np.nan)
        return a + b * (tau**m) + c * (tau**m) * np.cos(w * np.log(tau) + phi)

    def plot_risk_matrix(self, risk_matrix: Dict[str, Dict[str, Any]]):
        """
        绘制风险矩阵

        Args:
            risk_matrix: 风险矩阵
        """
        try:
            # 提取数据
            symbols = list(risk_matrix.keys())
            tc_days = [risk.get("tc_days", 50) for risk in risk_matrix.values()]
            confidence = [risk.get("confidence", 0) for risk in risk_matrix.values()]
            risk_levels = [risk.get("status", "Safe") for risk in risk_matrix.values()]

            # 创建颜色映射
            color_map = {"Danger": "red", "Warning": "orange", "Safe": "green"}
            colors = [color_map.get(level, "gray") for level in risk_levels]

            # 绘图
            plt.figure(figsize=(12, 6))
            bars = plt.bar(symbols, tc_days, color=colors)
            plt.title("LPPL结构性风险矩阵", fontsize=14)
            plt.xlabel("指数")
            plt.ylabel("到临界点天数 (tc_days)")
            plt.xticks(rotation=45, ha="right")
            plt.grid(axis="y", alpha=0.3)

            # 添加置信度标签
            for i, (bar, conf) in enumerate(zip(bars, confidence)):
                plt.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1,
                    f"{conf:.2f}",
                    ha="center",
                    va="bottom",
                )

            # 添加图例
            from matplotlib.patches import Patch

            legend_elements = [
                Patch(facecolor="red", label="Danger"),
                Patch(facecolor="orange", label="Warning"),
                Patch(facecolor="green", label="Safe"),
            ]
            plt.legend(handles=legend_elements, title="风险等级")

            # 保存图片
            img_name = "lppl_risk_matrix.png"
            plt.tight_layout()
            plt.savefig(img_name)
            logger.info(f"  [图表] 风险矩阵已保存至 {img_name}")
            plt.close()

            return img_name
        except Exception as e:
            logger.error(f"Error plotting risk matrix: {e}")
            return None
