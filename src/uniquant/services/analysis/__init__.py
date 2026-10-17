"""
Analysis Services Package

本包承载单一职责的分析引擎适配器，由 ``AnalysisEngineFactory``
(``engine_factory.py``) 按需惰性实例化：

- ``fsm_analysis_engine`` / ``czsc_analysis_engine`` / ``lppl_analysis_engine``
- ``regime_analysis_engine`` / ``ntf_analysis_engine`` / ``macro_analysis_engine``
- ``report_generator_engine`` / ``wyckoff_analysis_engine``

第七轮 (2026-10-17) 剪除：生产孤岛 ``macro_service.py`` / ``technical_service.py`` /
``signal_service.py`` 三个 ``*Service`` 门面类 —— 已被 ``analysis_service_v2.AnalysisService``
与 ``AnalysisEngineFactory`` 的引擎适配器取代，生产路径零引用（仅本包 ``__init__`` 的
历史导出与测试保留其存续）；引擎本体的失败降级语义在其各自的 ``*_analysis_engine``
中由测试覆盖。
"""

__all__: list[str] = []

