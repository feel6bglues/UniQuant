# 06.1 P2 TraceID Propagation

日期: 2026-06-08

## 状态

已完成。

本阶段处理 P2-1: 日志追踪缺乏统一 TraceID。

## 风险复核

- `AnalysisService.run_ticker_analysis()` 之前没有 trace id。
- `UnifiedResearchPipeline.run()` 之前没有 trace id。
- 引擎失败状态虽已进入 `engine_status/engine_errors`，但缺少可跨数据、分析、信号、回测串联的 ID。

## 修复内容

- `TickerAnalysisResult` 增加 `trace_id` 字段，默认兼容 `None`。
- `PipelineResult` 增加 `trace_id` 字段，默认兼容 `None`。
- `AnalysisService.run_ticker_analysis(ticker, trace_id=None)`:
  - 未传入时生成 `uuid.uuid4().hex`。
  - 将 trace 写入 `data_pack["trace_id"]`。
  - 将 trace 写入 `data_pack["engine_status_meta"]["trace_id"]`。
  - 成功、数据不足、引擎失败、决策失败路径均返回同一 trace。
- `UnifiedResearchPipeline.run(..., trace_id=None)`:
  - 未传入时生成 `uuid.uuid4().hex`。
  - 将 trace 传给 `AnalysisService.run_ticker_analysis()`。
  - 成功、分析失败、K 线为空路径均返回同一 trace。
  - pipeline 完成日志包含 `trace_id=...`。

## 新增测试

文件:

- `tests/test_phase4_2_contracts.py`

新增/扩展覆盖:

- pipeline 显式传入 `trace_id="trace-p2"` 时，analysis service、data_pack、PipelineResult 均携带同一 trace。
- `AnalysisService.run_ticker_analysis(..., trace_id="trace-analysis")` 会写入 `TickerAnalysisResult.trace_id`、`data_pack["trace_id"]` 和 `engine_status_meta.trace_id`。

## 验证

- `python3 -m pytest tests/test_phase4_2_contracts.py -q` -> 4 passed。
- `python3 -m ruff check src/uniquant/services/analysis_service_v2.py src/uniquant/services/research_pipeline.py tests/test_phase4_2_contracts.py` -> 通过。
- `python3 -m pytest tests/test_phase4_2_contracts.py tests/test_e2e_pipeline.py tests/test_engine_factory.py tests/test_service_container.py -q` -> 25 passed。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py tests/test_di_container_and_cache.py -q` -> 48 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 剩余风险

- trace id 尚未贯穿所有底层数据源、UI 操作和文件输出名；本阶段只覆盖核心 analysis/pipeline 数据结构和日志。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P2-2 UI 层越过 services 调 risk。
