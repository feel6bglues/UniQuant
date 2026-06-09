# 06.4 P2 Randomness Annotation Boundary

日期: 2026-06-08

## 状态

已完成。

本阶段处理 P2-4: 网络退避和模拟数据随机未统一标注。

## 风险复核

全局随机源分为三类:

- 研究/回测随机: Monte Carlo、bootstrap、LPPL optimizer、宏观 mock。
- 网络运行随机: 请求间隔、指数退避 jitter、User-Agent 轮换、数据源限速 sleep。
- 模拟数据随机: `MockDataSource` 生成实时 tick、JS executor 浏览器环境 mock ID。

P0/P1 阶段已经处理研究/回测随机的 seed/RNG 注入。本阶段只处理网络运行随机与模拟数据随机的审计噪音问题。

## 修复内容

- 引入统一源码标记: `NON_RESEARCH_RANDOMNESS`。
- 为以下网络/mock 随机源增加边界注释:
  - `src/uniquant/shared/error_handling.py`
  - `src/uniquant/data/utils/request_utils.py`
  - `src/uniquant/data/utils/akshare_wrapper.py`
  - `src/uniquant/data/utils/js_executor.py`
  - `src/uniquant/data/sources/eastmoney.py`
  - `src/uniquant/data/sources/sina.py`
  - `src/uniquant/data/sources/tencent.py`
  - `src/uniquant/data/sources/realtime_bridge.py`
  - `src/uniquant/data/scripts/update_daily_data_akshare.py`
  - `src/uniquant/data/scripts/update_daily_incremental.py`
- 新增 `tests/test_p2_randomness_annotations.py`:
  - 约束关键网络/mock 随机文件必须包含 `NON_RESEARCH_RANDOMNESS`。
  - 约束宏观 mock 随机仍保持 `mock: bool = False`、`seed: int = 42` 和 `np.random.default_rng(seed)`。
- 更新 `docs/reshaping_logs/README.md` 状态索引，加入 06-3 和 06-4。

## 边界说明

- 本阶段没有改变任何随机行为、请求间隔、User-Agent 选择、mock tick 生成或研究随机种子。
- `brain/lppl/numba_optimizer.py` 属于研究优化随机，已有 seed 参数，不纳入 `NON_RESEARCH_RANDOMNESS`。
- `hands/backtest/monte_carlo.py` 和 `hands/strategies/backtest.py` 属于 P1-6 已处理的可复现路径，不纳入本阶段标记。
- `data/scripts/*` 是 CLI 数据更新脚本，标注目的只是降低审计噪音，不改变脚本节奏。

## 验证

- `python3 -m pytest tests/test_p2_randomness_annotations.py -q` -> 2 passed。
- `python3 -m ruff check tests/test_p2_randomness_annotations.py src/uniquant/shared/error_handling.py src/uniquant/data/utils/request_utils.py src/uniquant/data/utils/akshare_wrapper.py src/uniquant/data/sources/eastmoney.py src/uniquant/data/sources/sina.py src/uniquant/data/sources/tencent.py src/uniquant/data/sources/realtime_bridge.py src/uniquant/data/scripts/update_daily_data_akshare.py src/uniquant/data/scripts/update_daily_incremental.py src/uniquant/data/utils/js_executor.py` -> 通过。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py tests/test_di_container_and_cache.py tests/test_manager_portfolio_analytics_service.py tests/test_p2_randomness_annotations.py -q` -> 54 passed, 5 warnings。
- `git diff --check` on touched P2-4 files -> 通过。

## 下一挂起点

P2 剩余风险复核收口与最终回归。
