# 05.5 P1 Factor Composition Diagnostics

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1-5: 因子合成降级不透明。

## 风险复核

- `FactorComposer.compute_all_factors()` 中单因子计算失败只记录日志，调用方无法从结果定位失败因子。
- `process()` / `compose_scores()` 会继续产出 `composite_score`，但无法说明 composite 是完整、降级还是不可用。
- `_symmetric_orthogonalization()` 失败时返回原始因子，之前没有结构化标记 `orthogonalization_failed=True`。

## 修复内容

- `FactorComposer` 增加 `last_diagnostics`。
- 新增 `get_last_diagnostics()`，返回诊断副本，避免外部修改内部状态。
- `compute_all_factors(..., return_diagnostics=True)` 可返回 `(factor_df, diagnostics)`。
- `compose_scores(..., return_diagnostics=True)` 可返回 `(result_df, diagnostics)`。
- `process(..., return_diagnostics=True)` 可返回 `(result_df, weights, diagnostics)`。
- 默认调用保持原返回值不变，兼容旧调用者。
- diagnostics 字段包括:
  - `requested_factors`
  - `computed_factors`
  - `used_factors`
  - `missing_requested_factors`
  - `failed_factors`
  - `orthogonalization_attempted`
  - `orthogonalization_failed`
  - `orthogonalization_error`
  - `composite_status`
  - `composite_usable`
- composite 状态规则:
  - `OK`: 有可用因子且无失败/缺失/正交化降级。
  - `DEGRADED`: 有可用因子，但存在失败因子、请求缺失因子或正交化失败。
  - `UNAVAILABLE`: 无可用因子，composite 不可用。

## 新增测试

文件:

- `tests/test_factor_composer.py`

新增覆盖:

- `test_process_reports_failed_factor_diagnostics`
- `test_compose_scores_reports_orthogonalization_failure`
- `test_compute_all_factors_can_return_diagnostics`

## 验证

- `python3 -m pytest tests/test_factor_composer.py -q` -> 9 passed。
- `python3 -m ruff check src/uniquant/brain/factors/composer.py tests/test_factor_composer.py` -> 通过。
- `python3 -m pytest tests/test_factor_composer.py tests/test_walk_forward_pipeline.py tests/test_financial_bridge.py tests/test_stock_screener.py -q` -> 56 passed。
- `python3 -m pytest tests/test_macro_and_scan_regressions.py tests/test_technical_and_signal_regressions.py -q` -> 8 passed。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py -q` -> 36 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 剩余风险

- 诊断当前保存在 composer 层，scan/report 层尚未把 diagnostics 写入最终研究报告。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P1-6 Monte Carlo/Bootstrap 默认可复现修复。
