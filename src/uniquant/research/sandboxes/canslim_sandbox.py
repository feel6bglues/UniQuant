# -*- coding: utf-8 -*-
"""
CANSLIM 与平均足 (Heikin-Ashi) 动量沙盒适配器 (CANSLIMStrategySandbox)
=====================================================================

包装 O'Neil CANSLIM 动量成长轮动与 Heikin-Ashi 低通平滑趋势跟踪模型，
转换为符合 Research OS 评估规范的连续信号与收益流。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .base_sandbox import BaseStrategySandbox, SandboxSignalEvaluation


class CANSLIMStrategySandbox(BaseStrategySandbox):
    """CANSLIM 动量轮动策略研究沙盒"""

    def __init__(
        self,
        momentum_window: int = 60,
        ha_smooth_window: int = 5,
    ):
        super().__init__(
            strategy_name="CANSLIM_HA_Momentum_Rotation",
            description="CANSLIM Growth Momentum with Heikin-Ashi Low-Pass Filter",
        )
        self.momentum_window = momentum_window
        self.ha_smooth_window = ha_smooth_window

    def compute_heikin_ashi(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算平均足 (Heikin-Ashi) K 线"""
        ha_df = pd.DataFrame(index=df.index)
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
        
        ha_open = np.zeros(len(df))
        ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2.0
            
        ha_df["ha_close"] = ha_close
        ha_df["ha_open"] = ha_open
        ha_df["ha_high"] = np.maximum(df["high"], np.maximum(ha_open, ha_close))
        ha_df["ha_low"] = np.minimum(df["low"], np.minimum(ha_open, ha_close))
        return ha_df

    def run_sandbox_simulation(self, df: pd.DataFrame, **kwargs) -> SandboxSignalEvaluation:
        """运行 CANSLIM 动量与平均足趋势跟踪仿真"""
        if df.empty or len(df) < self.momentum_window:
            return SandboxSignalEvaluation(
                strategy_name=self.strategy_name,
                ic_series=[0.0],
                daily_returns=[0.0],
                turnover_series=[0.0],
            )

        ha = self.compute_heikin_ashi(df)
        closes = df["close"].values
        returns = np.diff(closes) / closes[:-1]
        returns = np.insert(returns, 0, 0.0)

        # 动量得分 + HA 趋势信号
        mom_60 = pd.Series(closes).pct_change(self.momentum_window).fillna(0.0).values
        ha_trend = np.where(ha["ha_close"] > ha["ha_open"], 1.0, 0.0)

        # 复合信号
        signal = mom_60 * ha_trend

        # 策略收益
        strat_returns = (np.sign(signal[:-1]) * returns[1:]).tolist()
        turnover_series = [float(abs(np.sign(signal[i]) - np.sign(signal[i - 1]))) for i in range(1, len(signal))]

        # IC 检验
        fwd_returns = np.roll(returns, -1)
        fwd_returns[-1] = 0.0

        ic_series: List[float] = []
        window = 30
        for i in range(self.momentum_window, len(df)):
            s_w = signal[i - window : i]
            r_w = fwd_returns[i - window : i]
            if np.std(s_w) > 1e-8 and np.std(r_w) > 1e-8:
                ic = float(np.corrcoef(s_w, r_w)[0, 1])
                ic_series.append(ic if not np.isnan(ic) else 0.0)

        return SandboxSignalEvaluation(
            strategy_name=self.strategy_name,
            ic_series=ic_series if ic_series else [0.0],
            daily_returns=strat_returns if strat_returns else [0.0],
            turnover_series=turnover_series if turnover_series else [0.0],
            metadata={
                "mean_momentum": float(np.mean(mom_60)),
                "ha_bullish_ratio": float(np.mean(ha_trend)),
            },
        )
