# 05.2 P1 Backtest Entry Compatibility Remediation

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1 架构级风险: 旧版回测入口与统一撮合/风控入口并行，关键 A 股执行约束存在行为漂移风险。

## 风险复核

- 旧 `BacktestEngine.execute_buy()` 在资金不足时按任意股数缩减，可能生成非 A 股整手成交。
- 旧 `BacktestEngine.run_backtest()` 的隔日挂单在目标成交日停牌时仍可能成交。
- 旧直接 API 历史上允许 `symbol=""`，但复用统一撮合器后不能把空代码映射为不可识别的 `"UNKNOWN"`，否则会破坏旧测试与旧调用者。

## 修复内容

- `BacktestEngine` 初始化时复用 `UnifiedMatchingEngine`，把旧入口的买入/卖出成交判定收敛到统一撮合实现。
- `execute_buy()` 改为通过 `fill_buy()` 执行资金检查、涨跌停检查、滑点/费用计算、100 股整手约束和成交拒绝。
- `execute_sell()` 改为通过 `fill_sell()` 执行持仓检查、T+1、跌停、停牌、费用和成交拒绝。
- `execute_buy()` / `execute_sell()` 增加显式 `volume <= 0` 停牌拒绝，覆盖旧挂单路径。
- 新增 `_matching_symbol()`，仅在撮合器内部把旧 API 的空 `symbol` 映射为主板默认代码 `600000.SH`，保留外部旧接口允许省略 `symbol` 的兼容性。
- 补充 `name` 参数透传到滚动、Walk-forward、压力和历史压力入口，避免 ST 识别信息在包装入口丢失。
- 清理同文件 lint 问题: 弃用警告移出导入区前置代码，移除未使用的 `highs_arr/lows_arr`。

## 新增测试

- `tests/test_p1_backtest_compat.py::test_legacy_backtest_blocks_pending_buy_on_suspension_bar`
- `tests/test_p1_backtest_compat.py::test_legacy_execute_buy_uses_a_share_lot_rounding_on_cash_shortfall`

## 验证

- `python3 -m ruff check src/uniquant/hands/backtest/engine.py tests/test_p1_backtest_compat.py` -> 通过。
- `python3 -m pytest tests/test_p1_backtest_compat.py tests/test_backtest_engine.py -q` -> 25 passed。
- `python3 -m pytest tests/test_unified_matching.py tests/test_t1_constraint_boundary.py tests/chaos/test_matching_auditor.py tests/test_e2e_pipeline.py -q` -> 59 passed。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py -q` -> 19 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 剩余风险

- `BacktestEngine` 仍是 deprecated 旧入口，当前策略是兼容保留并把关键成交约束委托给统一撮合器，而不是继续扩展旧引擎能力。
- 本阶段未执行全量 `pytest tests/ -q`，只执行了 P1-2 目标测试、旧引擎回归、统一撮合相邻测试、阶段组合测试和导入冒烟。

## 下一挂起点

P1-3 数据入口多轨修复。
