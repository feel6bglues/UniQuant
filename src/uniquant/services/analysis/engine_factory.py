"""
分析引擎工厂 — 延迟初始化 + 单一职责
AnalysisService 不再直接持有引擎引用
"""

from typing import Any, Dict, Optional

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class AnalysisEngineFactory:
    def __init__(self, orchestrator):
        self._orchestrator = orchestrator
        self._engines: Dict[str, Any] = {}

    def _lazy_init(self, name: str, module_path: str, class_name: str, **kwargs) -> Any:
        if name not in self._engines:
            import importlib
            try:
                mod = importlib.import_module(module_path, package=__package__)
                cls = getattr(mod, class_name)
                self._engines[name] = cls(orchestrator=self._orchestrator, **kwargs)
                logger.debug(f"Lazy-initialized {name}")
            except Exception as e:
                logger.warning(f"Failed to init {name}: {e}")
                return None
        return self._engines[name]

    @property
    def fsm(self):
        return self._lazy_init("fsm", "..analysis.fsm_analysis_engine", "FsmAnalysisEngine")

    @property
    def czsc(self):
        return self._lazy_init("czsc", "..analysis.czsc_analysis_engine", "CzscAnalysisEngine")

    @property
    def lppl(self):
        return self._lazy_init("lppl", "..analysis.lppl_analysis_engine", "LpplAnalysisEngine")

    @property
    def regime(self):
        return self._lazy_init("regime", "..analysis.regime_analysis_engine", "RegimeAnalysisEngine")

    @property
    def ntf(self):
        return self._lazy_init("ntf", "..analysis.ntf_analysis_engine", "NtfAnalysisEngine")

    @property
    def macro(self):
        return self._lazy_init("macro", "..analysis.macro_analysis_engine", "MacroAnalysisEngine")

    @property
    def report(self):
        return self._lazy_init("report", "..analysis.report_generator_engine", "ReportGeneratorEngine")

    @property
    def brain(self):
        return self._lazy_init("brain", "...brain.fsm", "DecisionBrain")

    @property
    def wyckoff(self):
        return self._lazy_init("wyckoff", "..analysis.wyckoff_analysis_engine", "WyckoffAnalysisEngine")
