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
from typing import Any, Dict, List, Optional

import pandas as pd

from ..gates.alpha_tier_engine import AlphaTierEngine, PromotionReport


@dataclass
class SandboxSignalEvaluation:
    """策略沙盒信号评测产物

    ⚠️ 诚实门禁要求（P0 修复）：``residual_ic_series``（真实动量残差 IC）与
    ``pbo_value``（真实 Bootstrap PBO）是 Class A 的强制输入，必须由沙盒以真实计算
    结果填充；``gate_inputs``（键 ``b``/``c``/``d``）承载 Class B/C/D 的真实指标。
    任一项缺失时对应门禁不会被捷径伪造，直接判定为 ``TIER_UNRATED``。
    """
    strategy_name: str
    ic_series: List[float]
    daily_returns: List[float]
    turnover_series: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    residual_ic_series: Optional[List[float]] = None
    pbo_value: Optional[float] = None
    gate_inputs: Optional[Dict[str, Dict[str, Any]]] = None


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
        *,
        residual_ic_series: Optional[List[float]] = None,
        pbo_value: Optional[float] = None,
        gate_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs,
    ) -> PromotionReport:
        """将沙盒仿真结果通过 AlphaTierEngine 进行四大门禁硬阶检验。

        Class A 的动量残差 IC / PBO 与 Class B/C/D 的真实指标必须由调用方显式提供
        （既可经仿真产物 ``SandboxSignalEvaluation`` 携带，也可经本方法关键字覆盖）。
        任一缺失即判定为 ``TIER_UNRATED`` —— 绝不回退到捷径伪造。
        """
        engine = tier_engine or AlphaTierEngine()
        sim_result = self.run_sandbox_simulation(df, **kwargs)

        report = engine.evaluate_candidate(
            factor_name=self.strategy_name,
            ic_series=sim_result.ic_series,
            daily_returns=sim_result.daily_returns,
            turnover_series=sim_result.turnover_series,
            residual_ic_series=(
                sim_result.residual_ic_series if residual_ic_series is None else residual_ic_series
            ),
            pbo_value=sim_result.pbo_value if pbo_value is None else pbo_value,
            gate_inputs=sim_result.gate_inputs if gate_inputs is None else gate_inputs,
            audit_metadata={
                "strategy_name": self.strategy_name,
                "description": self.description,
                **sim_result.metadata,
            },
        )
        return report
