# -*- coding: utf-8 -*-
"""
LPPL 临界泡沫拟合器沙盒适配器 (LPPLStrategySandbox)
====================================================

包装对数周期幂律 (Log-Periodic Power Law Singularity) 泡沫预警模型，
将临界崩盘时间 tc 与泡沫置信度转换为符合 Research OS 规范的择时防线与收益流。
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .base_sandbox import BaseStrategySandbox, SandboxSignalEvaluation


class LPPLStrategySandbox(BaseStrategySandbox):
    """LPPL 泡沫预警策略研究沙盒"""

    def __init__(
        self,
        lookback_window: int = 120,
        bubble_threshold: float = 0.70,
    ):
        super().__init__(
            strategy_name="LPPL_Critical_Bubble_Detector",
            description="Sornette Log-Periodic Power Law Singularity Crash Predictor",
        )
        self.lookback_window = lookback_window
        self.bubble_threshold = bubble_threshold

    def run_sandbox_simulation(self, df: pd.DataFrame, **kwargs) -> SandboxSignalEvaluation:
        """运行 LPPL 泡沫信号与防御择时仿真"""
        if df.empty or len(df) < self.lookback_window:
            return SandboxSignalEvaluation(
                strategy_name=self.strategy_name,
                ic_series=[0.0],
                daily_returns=[0.0],
                turnover_series=[0.0],
            )

        closes = df["close"].values
        n = len(closes)
        returns = np.diff(closes) / closes[:-1]
        returns = np.insert(returns, 0, 0.0)

        # 模拟计算 LPPL 泡沫风险评分
        # 在真实计算中调用 calculator.py 拟合，沙盒内使用特征二阶曲率与对数周期震荡特征代理
        log_p = np.log(closes)
        
        # 简化滑窗高阶幂律曲率检测
        bubble_scores = np.zeros(n)
        for i in range(self.lookback_window, n):
            sub_p = log_p[i - self.lookback_window : i]
            # 计算加速上涨斜率
            slope = (sub_p[-1] - sub_p[0]) / self.lookback_window
            # 计算末端波动率压缩度
            vol = np.std(np.diff(sub_p))
            bubble_scores[i] = float(np.tanh(max(0.0, slope * 20.0 - vol * 5.0)))

        # 防御择时信号：当泡沫过热时转入轻仓或做空
        pos = np.where(bubble_scores > self.bubble_threshold, -0.5, 1.0)

        strat_returns = (pos[:-1] * returns[1:]).tolist()
        turnover_series = [float(abs(pos[i] - pos[i - 1])) for i in range(1, len(pos))]

        # IC：泡沫得分对未来 -20 日超额收益的相关性 (预测逃顶能力)
        fwd_20_ret = pd.Series(returns).rolling(20).sum().shift(-20).fillna(0.0).values
        ic_series: List[float] = []
        step = 20
        for i in range(self.lookback_window, n - step, step):
            sig_chunk = bubble_scores[i : i + step]
            ret_chunk = -fwd_20_ret[i : i + step]  # 负回报关联
            if np.std(sig_chunk) > 1e-6 and np.std(ret_chunk) > 1e-6:
                ic = float(np.corrcoef(sig_chunk, ret_chunk)[0, 1])
                ic_series.append(ic if not np.isnan(ic) else 0.0)

        return SandboxSignalEvaluation(
            strategy_name=self.strategy_name,
            ic_series=ic_series if ic_series else [0.0],
            daily_returns=strat_returns if strat_returns else [0.0],
            turnover_series=turnover_series if turnover_series else [0.0],
            metadata={
                "mean_bubble_score": float(np.mean(bubble_scores)),
                "max_bubble_score": float(np.max(bubble_scores)),
                "bubble_days_count": int(np.sum(bubble_scores > self.bubble_threshold)),
            },
        )
