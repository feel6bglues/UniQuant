"""
分析结果统一格式模块
提供标准化的分析结果封装
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AnalysisStatus(Enum):
    """分析状态枚举"""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class AnalysisResult:
    """
    统一分析结果格式
    所有分析模块必须返回此格式
    """

    # 基本状态
    status: AnalysisStatus
    success: bool

    # 分析数据
    data: Dict[str, Any] = field(default_factory=dict)

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 错误信息
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)
    processing_time_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        Returns:
            Dict: 结果字典
        """
        return {
            "status": self.status.value,
            "success": self.success,
            "data": self.data,
            "metadata": self.metadata,
            "error": self.error,
            "warnings": self.warnings,
            "timestamp": self.timestamp.isoformat(),
            "processing_time_ms": self.processing_time_ms,
        }

    @classmethod
    def ok(
        cls,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        processing_time_ms: Optional[float] = None,
    ) -> "AnalysisResult":
        """
        创建成功结果

        Args:
            data: 分析数据
            metadata: 元数据
            processing_time_ms: 处理时间(毫秒)

        Returns:
            AnalysisResult: 成功结果
        """
        return cls(
            status=AnalysisStatus.SUCCESS,
            success=True,
            data=data,
            metadata=metadata or {},
            processing_time_ms=processing_time_ms,
        )

    @classmethod
    def partial(
        cls,
        data: Dict[str, Any],
        warnings: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AnalysisResult":
        """
        创建部分成功结果

        Args:
            data: 分析数据
            warnings: 警告信息列表
            metadata: 元数据

        Returns:
            AnalysisResult: 部分成功结果
        """
        return cls(
            status=AnalysisStatus.PARTIAL,
            success=True,
            data=data,
            metadata=metadata or {},
            warnings=warnings,
        )

    @classmethod
    def create_error(
        cls, error: str, metadata: Optional[Dict[str, Any]] = None
    ) -> "AnalysisResult":
        """
        创建失败结果

        Args:
            error: 错误信息
            metadata: 元数据

        Returns:
            AnalysisResult: 失败结果
        """
        return cls(
            status=AnalysisStatus.ERROR,
            success=False,
            data={},
            metadata=metadata or {},
            error=error,
        )

    @classmethod
    def failed(
        cls,
        error: str,
        warnings: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AnalysisResult":
        """
        创建分析失败结果

        Args:
            error: 错误信息
            warnings: 警告信息列表
            metadata: 元数据

        Returns:
            AnalysisResult: 失败结果
        """
        return cls(
            status=AnalysisStatus.FAILED,
            success=False,
            data={},
            metadata=metadata or {},
            error=error,
            warnings=warnings or [],
        )

    def add_warning(self, warning: str) -> "AnalysisResult":
        """
        添加警告信息

        Args:
            warning: 警告信息

        Returns:
            AnalysisResult: 自身（链式调用）
        """
        self.warnings.append(warning)
        return self

    def add_metadata(self, key: str, value: Any) -> "AnalysisResult":
        """
        添加元数据

        Args:
            key: 键
            value: 值

        Returns:
            AnalysisResult: 自身（链式调用）
        """
        self.metadata[key] = value
        return self

    def get_data_field(self, field: str, default: Any = None) -> Any:
        """
        获取数据字段

        Args:
            field: 字段名
            default: 默认值

        Returns:
            字段值或默认值
        """
        return self.data.get(field, default)

    def is_valid(self) -> bool:
        """
        检查结果是否有效

        Returns:
            bool: 是否有效
        """
        return self.success and self.status in (
            AnalysisStatus.SUCCESS,
            AnalysisStatus.PARTIAL,
        )


class AnalysisResultBuilder:
    """
    分析结果构建器
    提供流式API构建分析结果
    """

    def __init__(self):
        """初始化构建器"""
        self._data: Dict[str, Any] = {}
        self._metadata: Dict[str, Any] = {}
        self._warnings: List[str] = []
        self._error: Optional[str] = None
        self._status = AnalysisStatus.SUCCESS
        self._success = True

    def with_data(self, key: str, value: Any) -> "AnalysisResultBuilder":
        """
        添加数据

        Args:
            key: 键
            value: 值

        Returns:
            AnalysisResultBuilder: 自身
        """
        self._data[key] = value
        return self

    def with_metadata(self, key: str, value: Any) -> "AnalysisResultBuilder":
        """
        添加元数据

        Args:
            key: 键
            value: 值

        Returns:
            AnalysisResultBuilder: 自身
        """
        self._metadata[key] = value
        return self

    def with_warning(self, warning: str) -> "AnalysisResultBuilder":
        """
        添加警告

        Args:
            warning: 警告信息

        Returns:
            AnalysisResultBuilder: 自身
        """
        self._warnings.append(warning)
        if self._status == AnalysisStatus.SUCCESS:
            self._status = AnalysisStatus.PARTIAL
        return self

    def with_error(self, error: str) -> "AnalysisResultBuilder":
        """
        设置错误

        Args:
            error: 错误信息

        Returns:
            AnalysisResultBuilder: 自身
        """
        self._error = error
        self._status = AnalysisStatus.ERROR
        self._success = False
        return self

    def mark_failed(self) -> "AnalysisResultBuilder":
        """
        标记为失败

        Returns:
            AnalysisResultBuilder: 自身
        """
        self._status = AnalysisStatus.FAILED
        self._success = False
        return self

    def build(self) -> AnalysisResult:
        """
        构建结果

        Returns:
            AnalysisResult: 分析结果
        """
        return AnalysisResult(
            status=self._status,
            success=self._success,
            data=self._data,
            metadata=self._metadata,
            error=self._error,
            warnings=self._warnings,
        )
