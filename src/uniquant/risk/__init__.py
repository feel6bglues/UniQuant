"""风险管理模块.

当前已实现:
- PositionSizer: 仓位计算 (T+1 风险惩罚 + CZSC 几何止损)
- EVTRisk / HistoricalSimulationRisk: 历史模拟 VaR/CVaR
- PortfolioOptimizer: 风险平价 + 均值-方差组合优化
- ComplianceEngine: 交易合规与风控检查
"""

try:
    from .compliance_engine import ComplianceEngine
except ImportError:
    ComplianceEngine = None

try:
    from .evt_risk import EVTRisk
except ImportError:
    EVTRisk = None

try:
    from .portfolio_optimizer import PortfolioOptimizer
except ImportError:
    PortfolioOptimizer = None

try:
    from .sizer import PositionSizer
except ImportError:
    PositionSizer = None

__all__ = [
    "PositionSizer",
    "EVTRisk",
    "PortfolioOptimizer",
]
if ComplianceEngine is not None:
    __all__.append("ComplianceEngine")
