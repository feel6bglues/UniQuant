# 阶段 5.1 修复日志：P1-1 缓存失效广播

生成时间: 2026-06-08

输入依据:

- `MASTER_REMEDIATION_PLAN.md` 中 P1-1。
- `docs/reshaping_logs/02_deep_inspection.md` 队列 A5。
- `docs/reshaping_logs/04_3_remediation.md` 残留风险。

范围边界:

- 本阶段只处理多层缓存失效广播。
- 未处理 P1-2 旧/新回测入口统一。
- 未处理 P1-3 数据入口多轨。

## 修复项

### 1. DataFetcher 增加 symbol 级价格缓存清理

文件:

- `src/uniquant/data/data_fetcher.py`

变更:

- 新增 `clear_price_cache(symbol=None, adjust=None)`。
- 支持全量清理、按 symbol 清理、按 `(symbol, adjust)` 精确清理。
- 返回实际删除的 LRU 条目数。

目的:

- 让 `DataFetcher._price_cache` 不再只能依赖容量淘汰。
- 支持数据重建后清除指定 symbol 的陈旧价格缓存。

### 2. DataService 增加集中 invalidation API

文件:

- `src/uniquant/services/data_service.py`

变更:

- 新增 `attach_market_cache(market_cache)`。
- 新增 `_clear_fetcher_price_cache(symbol, adjust)`。
- 新增 `invalidate_symbol_cache(symbol, data_type, market)`。
- `invalidate_symbol_cache()` 会清理 fetcher 价格缓存、删除服务层 datalake cache key，并在 `data_type="index"` 时清理市场级缓存。
- `rebuild_cache()` 在取数前先清 `DataFetcher` 对应 symbol 的价格缓存，避免用旧 LRU 数据重建数据湖。
- `rebuild_cache()` 写湖后调用 `invalidate_symbol_cache()`，再写入新的服务层 cache。

目的:

- 数据写入/重建后，fetcher LRU、DataService cache、MarketLevelCache 不再各自保留旧状态。

### 3. ServiceContainer 接入市场级缓存广播

文件:

- `src/uniquant/services/service_container.py`

变更:

- 容器创建 `MarketLevelCache` 后调用 `data_svc.attach_market_cache(market_cache)`。

目的:

- 生产对象图中，指数数据重建可以清理 Regime/NTF/Benchmark 市场级缓存。

## 新增回归测试

文件:

- `tests/test_p1_cache_invalidation.py`

覆盖用例:

- `DataFetcher.clear_price_cache("600000.SH")` 只清指定 symbol，不误删其它 symbol。
- `DataService.rebuild_cache("600000.SH", data_type="stock")` 在 `fetcher.get_price()` 前清理旧价格缓存。
- `DataService.rebuild_cache("000300.SH", data_type="index")` 会清理 `MarketLevelCache` 中的 Regime、NTF、Benchmark。

## 验证记录

已执行:

```bash
python3 -m pytest tests/test_p1_cache_invalidation.py -q
```

结果:

- `3 passed, 1 warning`

已执行:

```bash
python3 -m pytest tests/test_data_and_stock_query_regressions.py tests/test_service_container.py tests/test_e2e_pipeline.py -q
```

结果:

- `19 passed, 2 warnings`

已执行:

```bash
python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py -q
```

结果:

- `17 passed, 2 warnings`

已执行:

```bash
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

结果:

- `imports OK`

已执行:

```bash
python3 - <<'PY'
from uniquant.services.service_container import ServiceContainer
sc = ServiceContainer()
sc.initialize()
assert sc.get('data_service')._market_cache is sc.get('market_cache')
print('container cache hook OK')
PY
```

结果:

- `container cache hook OK`

## 残留风险

- P1-2 旧/新回测入口统一仍未处理。
- P1-3 数据入口多轨仍未处理。
- `CacheCoordinator` 仍不是事件总线；当前实现是集中 API + 容器注入，后续可升级为显式 `CacheInvalidationEvent`。
