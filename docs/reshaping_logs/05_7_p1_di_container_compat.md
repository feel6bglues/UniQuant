# 05.7 P1 DI Container Compatibility

日期: 2026-06-08

## 状态

已完成。

本阶段处理 `MASTER_REMEDIATION_PLAN.md` 中 P1-7: 兼容 DI 容器反向依赖。

## 风险复核

- `uniquant.shared.di_container` 是 deprecated 兼容模块，但仍存在于 shared 层。
- 该模块导入 `services.service_container` 已是 DAG 例外；更高风险是导入时执行 `container = ServiceContainer.instance()`，创建隐藏全局单例状态。
- 测试或旧脚本只要 import 兼容模块，就会影响后续容器隔离。

## 修复内容

- 保留 `DIContainer = ServiceContainer` 兼容别名。
- 将 `container = ServiceContainer.instance()` 改为 `_LazyContainerProxy()`。
- `_LazyContainerProxy` 在导入时不创建 `ServiceContainer` 单例。
- 只有访问 `container.get(...)`、`container.register(...)` 等属性/方法时，才调用 `ServiceContainer.instance()`。
- 若 `ServiceContainer` 不可用，代理访问时显式抛 `RuntimeError`。

## 新增测试

文件:

- `tests/test_di_container_and_cache.py`

新增覆盖:

- `test_import_does_not_initialize_service_container_singleton`

断言:

- 重新导入 `uniquant.shared.di_container` 后 `ServiceContainer._instance is None`。
- 访问 `module.container.get("missing")` 后才创建单例。
- 原有 `DIContainer()` 注册/get/reset/clear 兼容测试继续通过。

## 验证

- `python3 -m pytest tests/test_di_container_and_cache.py -q` -> 8 passed。
- `python3 -m ruff check src/uniquant/shared/di_container.py tests/test_di_container_and_cache.py` -> 通过。
- `python3 -m pytest tests/test_di_container_and_cache.py tests/test_service_container.py tests/test_p1_data_entry_injection.py -q` -> 23 passed。
- `python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py tests/test_di_container_and_cache.py -q` -> 46 passed。
- `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` -> imports OK。

## 剩余风险

- `shared.di_container` 仍然反向 import services 层以保留兼容别名；本阶段消除了导入时单例初始化副作用，但没有删除兼容模块。
- 本阶段未执行全量 `pytest tests/ -q`。

## 下一挂起点

P0/P1 修复清单已完成。下一步应执行全量回归，并确认是否进入 P2 工程级风险修复范围。
