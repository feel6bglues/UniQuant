# 05.3 P1 Data Entry Injection Remediation

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1-3: 数据入口多轨导致状态不共享。

## 风险复核

- `DataService(storage_manager=...)` 仍会默认创建新的 `DataFetcher()`，使 service 的 `StorageManager` 与 fetcher 的 `StorageManager` 分叉。
- `DataFetcher` 内部又创建独立 `DataPipelineService(data_dir)`，复权链的 `DataAdjuster` 继续持有第二套 `StorageManager`。
- `AnalysisService._run_ntf()` 直接创建 `DataFetcher()`，绕过容器注入的 fetcher 和缓存状态。
- `AnalysisService._run_alpha()` 直接创建 `StorageManager()`，绕过容器注入的数据湖。
- `MacroAnalysisService.detect_ntf_signals()` 也直接创建 `DataFetcher()`，属于同类服务层绕注入路径。

## 修复内容

- `DataPipelineService` 增加 `storage_manager` 注入参数，内部 `DataAdjuster` 复用共享 storage。
- `DataFetcher` 增加 `storage_manager` 和 `pipeline` 注入参数；默认构造时仍兼容 `data_dir`，但注入时会把同一 storage 传给 `DataAdjuster`、`AdjustFactorManager` 和 `DataPipelineService`。
- `DataService` 调整默认对象图:
  - 若传入 `storage_manager`，默认 fetcher 使用同一 storage。
  - 若传入 fetcher 且未传 storage，则 service 复用 fetcher 的 `storage_manager`。
  - `self.lake` 继续指向 `self.storage_manager`。
- `AnalysisService._run_ntf()` 改用 `self.data_service.fetcher`。
- `AnalysisService._run_alpha()` 改用 `self.data_service.lake`。
- `MacroAnalysisService` 增加 `data_fetcher` 注入参数，并默认从 `data_service.fetcher` 取共享 fetcher；无注入时不再隐式 new，而是走已有失败降级路径。
- 清理 `analysis_service_v2` 同文件未使用导入。

## 新增测试

文件:

- `tests/test_p1_data_entry_injection.py`

覆盖:

- `DataFetcher(data_dir=..., storage_manager=...)` 的 pipeline/adjuster 复用同一 storage。
- `DataService(storage_manager=...)` 默认 fetcher 复用 service storage。
- `ServiceContainer.initialize()` 后 `storage -> data_service -> fetcher -> pipeline.adjuster` 是同一 storage 图。
- `AnalysisService._run_ntf()` 使用注入的 `data_service.fetcher`。
- `AnalysisService._run_alpha()` 使用注入的 `data_service.lake`。
- `MacroAnalysisService.detect_ntf_signals()` 使用注入的 fetcher。

## 验证

- `python3 -m pytest tests/test_p1_data_entry_injection.py -q` -> 6 passed。
- `python3 -m pytest tests/test_data_and_stock_query_regressions.py tests/test_service_container.py tests/test_macro_and_scan_regressions.py tests/test_p1_cache_invalidation.py tests/test_p1_data_entry_injection.py -q` -> 24 passed。
- `python3 -m ruff check src/uniquant/data/data_pipeline_service.py src/uniquant/data/data_fetcher.py src/uniquant/services/data_service.py src/uniquant/services/analysis_service_v2.py src/uniquant/services/analysis/macro_service.py tests/test_p1_data_entry_injection.py` -> 通过。
- `python3 -m pytest tests/test_e2e_pipeline.py tests/test_engine_factory.py -q` -> 14 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py -q` -> 25 passed。

## 剩余风险

- `DataService` 和 `DataFetcher` 仍保留默认构造路径，用于脚本和旧调用兼容；P1-3 的约束是容器/服务层共享对象图，不是禁止所有底层类拥有默认构造。
- `analysis_service_legacy.py` 仍有直接构造点，但该文件属于 P1-4 God Object/legacy containment 范围，本阶段未扩展修改。
- `scan_service.py` 等命令式/边界入口仍可显式创建 `StorageManager(data_dir)`，当前视为入口级工厂行为，不纳入本阶段服务图共享修复。

## 下一挂起点

P1-4 God Objects 风险收敛。
