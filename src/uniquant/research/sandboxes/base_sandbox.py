# -*- coding: utf-8 -*-
"""
Research OS Gate 策略沙盒适配基类 (BaseStrategySandbox)
======================================================

为历史策略与探索性模型提供标准化的沙盒环境，
使其无缝接入 QTR-OS Alpha Candidate 四阶晋升引擎 (AlphaTierEngine)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..gates.alpha_tier_engine import AlphaTier, AlphaTierEngine, PromotionReport


@dataclass
class SandboxSignalEvaluation:
    """策略沙盒信号评测产物"""
    strategy_name: str
    ic_series: List[float]
    daily_returns: List[float]
    turnover_series: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategySandbox(ABC):
    """历史策略隔离沙盒抽象基类"""

    def __init__(self, strategy_name: str, description: str = ""):
        self.strategy_name = strategy_name
        self.description = description

    @abstractmethod
    def run_sandbox_simulation(self, df: pd.DataFrame, **kwargs) -> SandboxSignalEvaluation:
        """在历史数据上运行沙盒仿真，产出标准化指标时间序列"""
        pass

    def evaluate_through_gates(
        self,
        df: pd.DataFrame,
        tier_engine: Optional[AlphaTierEngine] = None,
        **kwargs,
    ) -> PromotionReport:
        """将沙盒仿真结果通过 AlphaTierEngine 进行四大门禁硬阶检验"""
        engine = tier_engine or AlphaTierEngine()
        sim_result = self.run_sandbox_simulation(df, **kwargs)

        report = engine.evaluate_candidate(
            factor_name=self.strategy_name,
            ic_series=sim_result.ic_series,
            daily_returns=sim_result.daily_returns,
            turnover_series=sim_result.turnover_series,
            audit_metadata={
                "strategy_name": self.strategy_name,
                "description": self.description,
                **sim_result.metadata,
            },
        )
        return report
