# 05.4 P1 God Object Containment

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1-4: God Objects 阻碍可测试性。

## 范围边界

- 不拆分 `analysis_service_legacy.py`、`ui/dashboard.py`、Wyckoff/LPPL/FSM 等大文件。
- 不做无测试保护的大规模重构。
- 本轮只做 legacy God Object 的边界收敛: 消除旧分析服务内部绕过注入的数据入口，降低隐藏状态和测试/生产对象图分叉。

## 风险复核

- `analysis_service_legacy.py` 标记 deprecated，但仍被测试直接引用，不能删除。
- 旧服务 `_run_ntf_detection()` 直接创建 `DataFetcher()`，绕过容器/`DataService` 共享 fetcher。
- 旧服务 `_run_alpha_analysis()` 直接创建 `StorageManager()`，绕过 `DataService.lake`。
- 这些点与 P1-3 数据入口多轨属于同类风险，但由于位于 legacy God Object 内，归入 P1-4 containment。

## 修复内容

- `AnalysisService._run_ntf_detection()` 改用 `self.data_service.fetcher`。
- 若 legacy 服务没有注入 `DataService.fetcher`，显式抛出 `DataFetchError`，避免无声创建第二套 fetcher。
- `AnalysisService._run_alpha_analysis()` 改用 `self.data_service.lake`，缺失时回退 `self.data_service.storage_manager`。
- 若 legacy 服务没有注入数据湖，显式抛出 `DataFetchError`。
- 不改变旧类构造签名，不拆分旧类，不修改报告保存协议。

## 新增/扩展测试

文件:

- `tests/test_p1_data_entry_injection.py`

新增覆盖:

- `test_legacy_analysis_service_ntf_uses_injected_data_fetcher`
- `test_legacy_analysis_service_alpha_uses_injected_lake`

## 验证

- `python3 -m pytest tests/test_p1_data_entry_injection.py -q` -> 8 passed。
- `rg -n "DataFetcher\\(|StorageManager\\(" src/uniquant/services/analysis_service_legacy.py src/uniquant/services/analysis_service_v2.py src/uniquant/services/analysis/macro_service.py` -> 无匹配。
- `python3 -m ruff check src/uniquant/services/analysis_service_legacy.py tests/test_p1_data_entry_injection.py` -> 通过。
- `python3 -m pytest tests/test_results_protocol.py tests/test_p1_data_entry_injection.py tests/test_data_and_stock_query_regressions.py tests/test_service_container.py -q` -> 23 passed。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py -q` -> 27 passed。
- `python3 -m pytest tests/test_e2e_pipeline.py tests/test_engine_factory.py tests/test_macro_and_scan_regressions.py -q` -> 18 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 剩余风险

- `analysis_service_legacy.py` 仍是 1600+ 行旧 God Object；当前只做 containment，不做结构拆分。
- `ui/dashboard.py`、Wyckoff、LPPL、FSM、EastMoney 等 God Object 仍需后续分阶段拆解，但不应在阶段 4 无测试大手术。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P1-5 因子合成降级可观测性修复。
