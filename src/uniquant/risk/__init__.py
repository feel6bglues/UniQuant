"""
风险管理模块

当前已实现:
- DrawdownAnalyzer: 向量化回撤分析
- PositionSizer: 仓位计算 (T+1 风险惩罚 + CZSC 几何止损)
- EVTRisk / HistoricalSimulationRisk: 历史模拟 VaR/CVaR
- PortfolioOptimizer: 风险平价 + 均值-方差组合优化
- StructuralRiskManager: 结构性风险矩阵
"""

from .drawdown_analyzer import DrawdownAnalyzer

try:
    from .sizer import PositionSizer
except ImportError:
    PositionSizer = None

try:
    from .evt_risk import EVTRisk
except ImportError:
    EVTRisk = None

try:
    from .portfolio_optimizer import PortfolioOptimizer
except ImportError:
    PortfolioOptimizer = None

try:
    from .structural import StructuralRiskManager
except ImportError:
    StructuralRiskManager = None

__all__ = [
    "DrawdownAnalyzer",
    "PositionSizer",
    "EVTRisk",
    "PortfolioOptimizer",
    "StructuralRiskManager",
]
