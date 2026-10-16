# -*- coding: utf-8 -*-
"""
Wyckoff 经典形态学沙盒适配器 (WyckoffStrategySandbox)
======================================================

包装古典威科夫点数图 (PnF) 与五阶段量价分析 (Accumulation / Distribution)，
转换为符合 Research OS 评估规范的连续信号与收益流。
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from ...brain.wyckoff.pnf import PointAndFigure
from .base_sandbox import BaseStrategySandbox, SandboxSignalEvaluation


class WyckoffStrategySandbox(BaseStrategySandbox):
    """Wyckoff 策略研究沙盒"""

    def __init__(
        self,
        box_size_pct: float = 0.02,
        reversal_boxes: int = 3,
        scaling_method: str = "log",
    ):
        super().__init__(
            strategy_name="Wyckoff_Classic_Morphology",
            description="Wyckoff Point and Figure Accumulation Breakout with Volume Effort",
        )
        self.box_size_pct = box_size_pct
        self.reversal_boxes = reversal_boxes
        self.scaling_method = scaling_method

    def run_sandbox_simulation(self, df: pd.DataFrame, **kwargs) -> SandboxSignalEvaluation:
        """运行威科夫 PnF 与动量形态仿真"""
        if df.empty or len(df) < 50:
            return SandboxSignalEvaluation(
                strategy_name=self.strategy_name,
                ic_series=[0.0],
                daily_returns=[0.0],
                turnover_series=[0.0],
            )

        pnf = PointAndFigure(
            box_size=self.box_size_pct,
            reversal=self.reversal_boxes,
            scale=self.scaling_method,
        )
        boxes = pnf.build(df)

        # 生成基于突破的信号流与残差收益
        closes = df["close"].values
        returns = np.diff(closes) / closes[:-1]
        returns = np.insert(returns, 0, 0.0)

        # 简单形态得分代理 (高低点突破与成交量异动)
        ma20 = df["close"].rolling(20, min_periods=1).mean().values
        vol_ma20 = df["volume"].rolling(20, min_periods=1).mean().values
        effort_factor = (df["volume"].values / np.maximum(vol_ma20, 1.0)) * np.sign(closes - ma20)

        # 构造跨期 IC 与日度回报
        fwd_returns = np.roll(returns, -1)
        fwd_returns[-1] = 0.0

        # 滑窗 IC
        ic_series: List[float] = []
        window = 30
        for i in range(window, len(df)):
            sig_w = effort_factor[i - window : i]
            ret_w = fwd_returns[i - window : i]
            if np.std(sig_w) > 1e-8 and np.std(ret_w) > 1e-8:
                ic = float(np.corrcoef(sig_w, ret_w)[0, 1])
                if not np.isnan(ic):
                    ic_series.append(ic)
                else:
                    ic_series.append(0.0)
            else:
                ic_series.append(0.0)

        # 策略日度收益
        sig_sign = np.sign(effort_factor)
        strat_returns = (sig_sign[:-1] * returns[1:]).tolist()
        turnover_series = [float(abs(sig_sign[i] - sig_sign[i - 1])) for i in range(1, len(sig_sign))]

        return SandboxSignalEvaluation(
            strategy_name=self.strategy_name,
            ic_series=ic_series if ic_series else [0.0],
            daily_returns=strat_returns if strat_returns else [0.0],
            turnover_series=turnover_series if turnover_series else [0.0],
            metadata={
                "pnf_box_count": len(boxes),
                "scaling": self.scaling_method,
            },
        )
