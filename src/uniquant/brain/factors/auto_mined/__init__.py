"""
auto_mined — 受控自动因子挖掘

使用遗传规划 (Genetic Programming) 结合金融算子,
经过 The Reaper (PBO < 0.2, OOS IC > 0.03) 筛选后方可落地.
"""

from .generator import GeneticFactorMiner, Operator, Terminal, GPTree

__all__ = ["GeneticFactorMiner", "Operator", "Terminal", "GPTree"]
