# 05.6 P1 Monte Carlo Reproducibility

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1-6: Monte Carlo/Bootstrap 默认不可复现。

## 风险复核

- `MonteCarloSimulator` 已在前序修复中默认 `seed=42`，并使用 `np.random.default_rng()`，不再依赖全局 `np.random`。
- 旧 `BacktestEngine` 仍未显式传入 Monte Carlo seed，报告 metadata 缺少 seed 标记。
- deprecated `hands/strategies/backtest.py::_block_bootstrap()` 内部直接调用 `np.random.choice()`，函数自身没有 RNG 注入参数。

## 修复内容

- `BacktestEngine.__init__()` 增加 `monte_carlo_seed: Optional[int] = RANDOM_SEED`。
- 旧回测引擎生成 Monte Carlo metadata 时显式创建 `MonteCarloSimulator(n_simulations=200, seed=self.monte_carlo_seed)`。
- 旧回测结果 metadata 写入 `monte_carlo_seed`。
- `_block_bootstrap()` 增加 `rng: Optional[np.random.Generator] = None` 参数。
- `_block_bootstrap()` 默认使用 `np.random.default_rng(RANDOM_SEED)`，显式传入 RNG 时完全由调用者控制。
- deprecated 策略回测的 Monte Carlo 循环创建单个 seeded generator，并传入每次 `_block_bootstrap()`，保证样本序列可复现且每次模拟不是同一条样本。
- 清理目标文件 lint:
  - `hands/strategies/backtest.py` 弃用警告移到导入之后。
  - `TDX_DATA_DIR` 赋值移到导入区之后。
  - 移除 `monte_carlo.py` 未使用局部变量。

## 新增测试

文件:

- `tests/test_p1_reproducibility.py`

覆盖:

- `_block_bootstrap()` 接受注入 RNG，且不受全局 `np.random.seed()` 影响。
- 旧 `BacktestEngine` 运行 Monte Carlo metadata 时使用配置的 `monte_carlo_seed`。

## 验证

- `python3 -m pytest tests/test_p1_reproducibility.py -q` -> 2 passed。
- `python3 -m ruff check src/uniquant/hands/backtest/engine.py src/uniquant/hands/strategies/backtest.py src/uniquant/hands/backtest/monte_carlo.py tests/test_p1_reproducibility.py` -> 通过。
- `python3 -m pytest tests/test_p1_reproducibility.py tests/test_backtest_advanced.py tests/test_backtest_engine.py tests/test_p1_backtest_compat.py -q` -> 45 passed, 1 skipped。
- `python3 -m pytest tests/test_strategies.py tests/test_hands_strategies.py -q` -> 17 passed, 2 skipped。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py -q` -> 38 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。
- `rg -n "np\\.random\\.choice|np\\.random\\.permutation|np\\.random\\.seed" src/uniquant/hands -g '*.py'` -> 仅剩 deprecated 策略回测主入口的 `np.random.seed(RANDOM_SEED)`，不再位于 bootstrap 抽样函数内部。

## 剩余风险

- deprecated `hands/strategies/backtest.py` 主入口仍调用 `np.random.seed(RANDOM_SEED)` 以保持旧脚本整体输出稳定；这不是本阶段的隐式抽样风险，但仍属于旧脚本全局状态残留。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P1-7 兼容 DI 容器反向依赖修复。
