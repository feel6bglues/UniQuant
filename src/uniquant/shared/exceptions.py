class AlphaTacticianError(Exception):
    """Alpha-Tactician 系统基础异常类"""


class DataError(AlphaTacticianError):
    """数据相关错误"""


class DataFetchError(DataError):
    """数据获取错误（网络请求、API调用失败）"""


class DataValidationError(DataError):
    """数据验证错误（数据格式、完整性检查失败）"""


class DataStorageError(DataError):
    """数据存储错误（文件I/O、数据库操作失败）"""


class DatabaseConnectionError(DataStorageError):
    """数据库连接错误"""


class DataAccessError(DataError):
    """数据访问错误"""


class CacheError(DataError):
    """缓存相关错误"""


class AnalysisError(AlphaTacticianError):
    """分析相关错误"""


class LPPLFitError(AnalysisError):
    """LPPL模型拟合错误"""


class CZSCEngineError(AnalysisError):
    """缠论引擎错误"""


class EngineError(AnalysisError):
    """引擎错误"""


class RiskError(AlphaTacticianError):
    """风险管理相关错误"""


class PositionSizingError(RiskError):
    """仓位计算错误"""


class EVTRiskError(RiskError):
    """极值风险计算错误"""


class RiskCalculationError(RiskError):
    """风险计算错误"""


class ServiceError(AlphaTacticianError):
    """服务层错误"""


class AnalysisServiceError(ServiceError):
    """分析服务错误"""


class DataServiceError(ServiceError):
    """数据服务错误"""


class PortfolioServiceError(ServiceError):
    """组合服务错误"""


class UIError(AlphaTacticianError):
    """UI相关错误"""


class DashboardError(UIError):
    """仪表盘错误"""


class VisualizationError(UIError):
    """可视化错误"""


class ConfigurationError(AlphaTacticianError):
    """配置错误"""


class OperationTimeoutError(AlphaTacticianError):
    """操作超时错误"""


class DependencyError(ServiceError):
    """依赖项错误"""


class ValidationError(AlphaTacticianError):
    """验证错误"""


class BacktestError(AlphaTacticianError):
    """回测相关错误"""


# === LPPL Exceptions (from LPPL standalone) ===
class LPPLException(AlphaTacticianError): ...
class DataNotFoundError(LPPLException): ...
class ComputationError(LPPLException): ...

class WyckoffError(AlphaTacticianError): ...
class BCNotFoundError(WyckoffError): ...
class InvalidInputDataError(WyckoffError): ...
class ImageProcessingError(WyckoffError): ...
class FusionConflictError(WyckoffError): ...
class RuleEngineError(WyckoffError): ...
