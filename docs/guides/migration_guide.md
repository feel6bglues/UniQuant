# 迁移指南 (Migration Guide)

UniQuant 经历了多次重构。本文档列出所有已弃用（deprecated）的 API 及其替代品，帮助迁移旧代码。

> **原则**: 弃用 API 仍可运行但会发出 `DeprecationWarning`。请优先使用新 API。

---

## 1. 回测引擎迁移

| 弃用 | 替代 | 主要变化 |
|------|------|---------|
| `BacktestEngine` (`hands/backtest/engine.py`) | `UnifiedBacktestEngine` (`hands/backtest/unified_engine.py`) | 输入从 `signal_generator` 函数改为 `List[TradingSignal]` |
| `PortfolioEngine` (`hands/backtest/portfolio_engine.py`) | `UnifiedBacktestEngine` | 同上 + 多标的支持在 `UnifiedBacktestEngine` 外部循环实现 |
| `hands/strategies/backtest` | `ResearchPipeline` (`services/research_pipeline.py`) | 一键化：分析→信号→回测 |
| `BaseStrategy` (`hands/strategies/`) | `STRATEGY_MAP` (`hands/strategies/registry.py`) | 注册表模式替代继承 |

### 迁移示例: BacktestEngine → UnifiedBacktestEngine

**旧代码 (BacktestEngine):**

```python
from uniquant.hands.backtest.engine import BacktestEngine

def signal_gen(df_slice, idx, context):
    if some_condition:
        return {"action": "BUY", "reason": "信号"}
    return {"action": "HOLD", "reason": "无信号"}

engine = BacktestEngine(initial_capital=100000.0)
result = engine.run_backtest(df=df, signal_generator=signal_gen, symbol="600036", position_size=500)
```

**新代码 (UnifiedBacktestEngine):**

```python
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.signal.adapters import TradingSignalCollector, create_default_registry
from uniquant.shared.interfaces import TradingSignal

collector = TradingSignalCollector(create_default_registry())
signals = collector.collect(data_pack, symbol="600036")
# 或手动构造 TradingSignal
# signals = [TradingSignal(action="BUY", symbol="600036", ...)]

engine = UnifiedBacktestEngine(initial_capital=100000.0)
result = engine.run(df=df, signals=signals, symbol="600036")
```

### 迁移示例: BacktestEngine 滚动/Walk-Forward/压力测试

旧版 `BacktestEngine` 内置了 `run_rolling_backtest()`, `run_walk_forward()`, `run_stress_test()` 方法。`UnifiedBacktestEngine` 仅提供单次 `run()`。如需这些模式，有两种选择：

1. **使用 `ResearchPipeline`** — 如果只需要标准回测流程
2. **外部循环组合 `UnifiedBacktestEngine.run()`** — 自定义窗口分割

```python
# Walk-Forward 外部循环示例
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

def walk_forward(df, signals, train_window=252, test_window=63):
    results = []
    for start in range(0, len(df) - train_window, test_window):
        train_end = start + train_window
        test_end = min(train_end + test_window, len(df))
        train_df, test_df = df.iloc[start:train_end], df.iloc[train_end:test_end]
        engine = UnifiedBacktestEngine(initial_capital=100000.0)
        result = engine.run(df=test_df, signals=signals, symbol="600036")
        results.append(result)
    return results
```

---

## 2. 数据组件迁移

| 弃用 | 替代 | 说明 |
|------|------|------|
| `DataLake` (旧) | `StorageManager` (`data/lake/storage_manager.py`) | Parquet 文件存储的直接操作 |
| `DataPipeline` (旧) | `DataPipelineService` (`data/data_pipeline_service.py`) | Cleaner → Validator → Adjuster 编排 |

以上旧类在文档 `packages/data.md` 中被标记为弃用，但实际代码中这些名称可能以兼容桩存在。直接使用新类即可。

---

## 3. 服务层迁移

| 弃用 | 替代 | 说明 |
|------|------|------|
| `AnalysisService (v1)` (`services/analysis_service_legacy.py`) | `AnalysisService (v2)` (`services/analysis_service_v2.py`) | ~300 行纯编排器替代 1642 行上帝对象 |
| `di_container` (`shared/di_container.py`) | `ServiceContainer` (`services/service_container.py`) | DAG 拓扑 + 单例 + 工厂注册 |

`AnalysisService v1` 的调用方式:

```python
# 旧 (v1, deprecated)
from uniquant.services.analysis_service import AnalysisService

# 新 (v2)
from uniquant.services.analysis_service_v2 import AnalysisService
```

`AnalysisService v2` 构造函数签名为 `AnalysisService(data_service=..., engine_factory=...)`，不再接受旧版 `orchestrator` 参数。`ServiceContainer.initialize()` 已自动使用 v2。

---

## 4. 风险模块迁移

| 弃用 | 替代 | 说明 |
|------|------|------|
| `EVTRisk` (`risk/evt_risk.py`) | `HistoricalSimulationRisk` (`risk/historical_risk.py`) | VaR/CVaR 计算的更新实现 |

```python
# 旧
from uniquant.risk import EVTRisk
risk = EVTRisk()

# 新
from uniquant.risk import EVTRisk  # 别名指向 HistoricalSimulationRisk
# 或直接:
from uniquant.risk.historical_risk import HistoricalSimulationRisk
risk = HistoricalSimulationRisk()
```

---

## 5. 因子注册迁移

| 弃用 | 替代 | 说明 |
|------|------|------|
| `shared.factor_governance.FactorRegistry` | `brain.factors.registry.FactorRegistry` | 旧版设计桩，带 `check_access()` 权限控制的实际注册中心 |

```python
# 旧 (deprecated)
from uniquant.shared.factor_governance import FactorRegistry

# 新
from uniquant.brain.factors.registry import FactorRegistry

# 新 API 额外支持:
FactorRegistry.check_access("my_factor")  # WARN/BLOCK 模式
FactorRegistry.set_mode("my_factor", "block")  # 设为阻止模式
```

---

## 6. Brain 引擎方法迁移

这些函数在迁移到服务层编排后被标记弃用:

| 弃用方法 | 模块 | 替代 |
|----------|------|------|
| `get_czsc_signals_from_data()` | `brain/czsc/czsc_engine.py` | `CZSCEngine.get_summary()` |
| `calculate_indicator_from_data()` | `brain/indicators/indicators.py` | 直接调用 `IndicatorCalculator` 实例方法 |
| `detect_from_data()` | `brain/regime/regime_detector.py` | `RegimeDetector.get_summary()` |
| `get_alpha_score_from_data()` | `brain/alpha_decoupler/alpha_decoupler.py` | `AlphaDecoupler.get_summary()` |

---

## 7. 错误处理工具迁移

| 弃用函数 | 替代 |
|----------|------|
| `retry_on_exception()` | `retry_decorator.retry()` |
| `handle_network_errors()` | `retry_decorator.retry()` + `@handle_errors` |
| `handle_file_errors()` | `@handle_errors` |
| `handle_data_errors()` | `@handle_errors` |
| `handle_api_errors()` | `retry_decorator.retry()` + `@handle_errors` |
| `retry_on_failure()` | `retry_decorator.retry()` / `retry_decorator.retry_with_fallback()` |

```python
# 旧
from uniquant.shared.utils import retry_on_failure
result = retry_on_failure(my_func, max_retries=3, delay=0.1)

# 新
from uniquant.shared.retry_decorator import retry
@retry(max_retries=3, delay=0.1)
def my_func():
    ...
```

---

## 8. 完整迁移路线图

| 任务 | 依赖 | 风险 |
|------|------|------|
| ServiceContainer → `get("analysis_service")` 返回 v2 | 无 | 低 (v1→v2 签名兼容) |
| BacktestEngine → UnifiedBacktestEngine | 信号需先迁移到 TradingSignal | 中 (API 不兼容) |
| di_container → ServiceContainer | 无 | 低 (懒加载兼容) |
| FactorRegistry → brain.factors.registry | 无 | 低 (接口兼容) |
| 错误处理工具 | 无 | 低 (函数签名不同) |

大多数迁移可以通过 `grep -r "legacy_pattern" src/` 检查旧代码引用位置，逐个替换。
