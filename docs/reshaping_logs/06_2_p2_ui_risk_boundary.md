# 06.2 P2 UI-Risk Boundary Cleanup

日期: 2026-06-08

## 状态

已完成。

本阶段处理 P2-2: UI 层越过 services 直接调用 risk 层。

## 风险复核

- `src/uniquant/ui/manager_portfolio_analytics_service.py` 原先在方法内部直接导入并实例化:
  - `..risk.evt_risk.EVTRisk`
  - `..risk.portfolio_optimizer.OptimizerConfig`
  - `..risk.portfolio_optimizer.PortfolioOptimizer`
- 直接跨层调用出现在:
  - `calculate_portfolio_risk_metrics()`
  - `optimize_portfolio()`
  - `run_stress_test()`
- 这绕过了 `PortfolioService`，导致 UI 业务管理器同时承担数据收集、风险引擎选择和优化器构造职责。

## 修复内容

- `PortfolioService` 新增 service 层封装:
  - `calculate_evt_risk_metrics(portfolio_returns)`
  - `optimize_returns_portfolio(returns_df, method="risk_parity")`
  - `run_evt_stress_test(portfolio_returns, scenarios)`
- `ManagerPortfolioAnalyticsService` 改为:
  - 初始化时复用 `manager.portfolio_service`。
  - 若 manager 未注入，则创建 `PortfolioService()` 作为兼容 fallback。
  - UI 仍负责从 `manager.get_real_kline_data()` 收集 K 线并构造收益序列/收益矩阵。
  - EVT 风险指标、组合优化、压力测试均委托给 `PortfolioService`。
- 新增 `_build_returns_frame()`，避免优化路径在 UI 中重复拼 DataFrame 逻辑。

## 测试约束

- `tests/test_manager_portfolio_analytics_service.py` 改为使用 fake `portfolio_service`，验证 UI 压力测试路径实际委托 service。
- 新增边界测试: `ManagerPortfolioAnalyticsService` 源码不得包含 `..risk` 或 `uniquant.risk`。

## 验证

- `python3 -m pytest tests/test_manager_portfolio_analytics_service.py -q` -> 4 passed。
- `python3 -m ruff check src/uniquant/ui/manager_portfolio_analytics_service.py src/uniquant/services/portfolio_service.py tests/test_manager_portfolio_analytics_service.py` -> 通过。
- `python3 -m pytest tests/test_service_container.py tests/test_final_service_regressions.py -q` -> 11 passed, 2 warnings。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py tests/test_di_container_and_cache.py -q` -> 48 passed, 5 warnings。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 说明

- `src/uniquant/ui/health_check.py` 仍包含字符串 `"uniquant.risk.evt_risk"`，这是模块完整性探针，不是 UI 业务计算绕过 service。本阶段不修改，避免破坏健康检查语义。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P2-3 废弃/僵尸体系与硬编码配置冲突复核。
