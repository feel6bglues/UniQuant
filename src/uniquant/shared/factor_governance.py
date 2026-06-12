from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..brain.factors.registry import FactorAccessLevel, FactorRegistry

__all__ = [
    "FactorAccessLevel", "FactorManifest", "FactorRegistry",
    "global_factor_registry", "FactorAdmissionGate", "AdmissionResult",
    "CheckResult",
]

warnings.warn(
    "uniquant.shared.factor_governance is deprecated. "
    "Use uniquant.brain.factors.registry.FactorRegistry directly instead.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class FactorManifest:
    """因子清单 — 集中注册和管理所有可用因子

    每个因子注册后记录其名称、描述、数据源和访问级别。
    在 warn/block 模式下可拦截未注册因子的访问。
    """
    name: str
    description: str = ""
    category: str = "generic"
    data_source: str = ""
    access_level: FactorAccessLevel = FactorAccessLevel.FREE
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """单项准入检查结果"""
    check_name: str
    passed: bool
    message: str = ""


@dataclass
class AdmissionResult:
    """因子准入检查结果

    passed: 是否通过所有检查
    checks: 各项检查结果字典 {check_name: CheckResult}
    summary: 汇总信息
    """
    passed: bool
    checks: Dict[str, CheckResult] = field(default_factory=dict)
    summary: str = ""


class FactorAdmissionGate:
    """因子准入网关 — 在注册前进行合规性检查

    模式:
      - "off":  不执行检查, 直接通过
      - "warn": 执行检查但不阻止注册, 记录警告
      - "block": 执行检查并阻止不合规注册

    用法:
        gate = FactorAdmissionGate(mode="warn")
        result = gate.check_admission(manifest)
        if result.passed or gate.mode == "warn":
            FactorRegistry.register(...)
    """

    def __init__(self, mode: str = "warn"):
        if mode not in ("off", "warn", "block"):
            raise ValueError(f"无效的 admission gate 模式: {mode}")
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in ("off", "warn", "block"):
            raise ValueError(f"无效的 admission gate 模式: {mode}")
        self._mode = mode

    def check_admission(self, manifest: FactorManifest) -> AdmissionResult:
        """运行所有准入检查

        Args:
            manifest: 待注册因子的清单

        Returns:
            AdmissionResult 包含所有检查结果
        """
        checks: Dict[str, CheckResult] = {}

        checks["naming"] = self._check_naming(manifest)
        checks["documentation"] = self._check_documentation(manifest)
        checks["parameters"] = self._check_parameters(manifest)

        passed = all(c.passed for c in checks.values())
        failed = [c for c in checks.values() if not c.passed]
        summary_parts = [f"{'✓' if c.passed else '✗'} {c.check_name}: {c.message}" for c in checks.values()]
        summary = "\n".join(summary_parts)

        if not passed and self._mode == "warn":
            summary += f"\n⚠️  因子 {manifest.name} 未通过 {len(failed)} 项检查 (mode=warn, 已放行)"

        return AdmissionResult(
            passed=passed,
            checks=checks,
            summary=summary,
        )

    def _check_naming(self, manifest: FactorManifest) -> CheckResult:
        """命名规范检查: 小写下划线, 长度限制"""
        name = manifest.name
        if not name:
            return CheckResult("naming", False, "因子名为空")
        if len(name) > 128:
            return CheckResult("naming", False, f"因子名过长 ({len(name)} > 128)")
        import re
        if not re.match(r'^[a-z][a-z0-9_]*$', name):
            return CheckResult(
                "naming", False,
                f"因子名 '{name}' 不符合命名规范 (小写字母开头, 小写/数字/下划线)",
            )
        return CheckResult("naming", True, f"命名规范: {name}")

    def _check_documentation(self, manifest: FactorManifest) -> CheckResult:
        """文档完整性检查"""
        if not manifest.description or len(manifest.description.strip()) < 10:
            return CheckResult(
                "documentation", False,
                f"描述过短或为空 ({len(manifest.description or '')} chars, 需要 ≥10)",
            )
        return CheckResult("documentation", True, f"描述长度: {len(manifest.description)} chars")

    def _check_parameters(self, manifest: FactorManifest) -> CheckResult:
        """参数有效性检查"""
        if not manifest.category:
            return CheckResult("parameters", False, "分类 (category) 为空")
        valid_categories = {"technical", "fundamental", "alternative", "custom", "generic"}
        if manifest.category not in valid_categories:
            return CheckResult(
                "parameters", False,
                f"分类 '{manifest.category}' 不在有效范围内: {valid_categories}",
            )
        return CheckResult("parameters", True, f"分类: {manifest.category}")


# 全局因子注册中心 — 引用 brain 的统一单例
global_factor_registry = FactorRegistry()
