# 阶段 4.2 修复日志：接口契约与强类型信号链路

生成时间: 2026-06-08

输入依据:

- `MASTER_REMEDIATION_PLAN.md` 中步骤 4.2 范围。
- `docs/reshaping_logs/02_deep_inspection.md` 中 P0-1、P0-2。
- `docs/reshaping_logs/04_1_remediation.md` 中 4.1 残留风险。

范围边界:

- 本阶段只修复接口契约断裂点，确保分析引擎 adapter 和执行链路的强类型信号转换可用。
- 未处理阶段 4.3 的被动风控防线。
- 未做 God Object 大拆分。
- 未处理 P1 缓存广播和旧/新回测入口统一。

## 修复项

### 1. AnalysisEngineFactory 不再绑定裸 DataService

文件:

- `src/uniquant/services/analysis/engine_factory.py`
- `src/uniquant/services/analysis_service_v2.py`

变更:

- `AnalysisEngineFactory` 新增 `bind_orchestrator(orchestrator)`。
- `AnalysisService.__init__()` 在接收外部 factory 时，将 factory orchestrator 回绑为当前 `AnalysisService`。
- 回绑后清空已懒加载 engine，避免旧 engine 持有错误 orchestrator。
- 这样 `ServiceContainer` 仍可先创建 factory，再创建 `AnalysisService`，但最终 adapter 看到的是分析编排器契约，而不是裸 `DataService`。

覆盖风险:

- 修复 P0-1 中 `ServiceContainer -> AnalysisEngineFactory(orchestrator=data_svc)` 导致 FSM/Wyckoff 等 adapter 调用 `_get_cached_result/_optimize_dataframe/_sample_data/ensure_precision_consistency` 时接口断裂的问题。

### 2. 引擎初始化失败改为 fail-fast

文件:

- `src/uniquant/services/analysis/engine_factory.py`

变更:

- `_lazy_init()` 初始化失败不再 warning 后返回 `None`。
- 现在记录 error，并抛出 `RuntimeError("Failed to initialize analysis engine <name>")`。
- `brain` 初始化失败同样抛出 `RuntimeError`。

覆盖风险:

- 修复 P0-1 中引擎初始化失败变成 `None`，上层继续输出默认值的静默失效问题。

### 3. AnalysisService 补齐 adapter 所需小接口

文件:

- `src/uniquant/services/analysis_service_v2.py`

变更:

- 新增 `_generate_cache_key()`。
- 新增 `_get_cached_result()` 和 `_set_cached_result()`，委托现有 `DataService` 缓存门面。
- 新增 `_sample_data()`，对超大 DataFrame 做保序下采样。
- 新增 `_optimize_dataframe()`，做轻量 dtype 优化和日期排序。
- 新增 `round_to_precision()` 与 `ensure_precision_consistency()`，复用共享精度常量。
- 初始化 `evt_risk`、`sizer` 占位，兼容 FSM adapter 对风险/仓位组件的懒加载需求。

设计约束:

- 这里只补 adapter 契约，不把旧版 `analysis_service_legacy.py` 的 God Object 职责搬回 v2。
- 缓存仍委托 `DataService`，不新增第三套缓存体系。

覆盖风险:

- 修复 FSM/CZSC/Wyckoff/Macro adapter 对旧 `AnalysisService` 方法的隐式依赖。

### 4. FSM 决策进入 TradingSignalCollector

文件:

- `src/uniquant/services/research_pipeline.py`

变更:

- `UnifiedResearchPipeline.run()` 在收集信号前调用 `_merge_decision_for_collection()`。
- 该方法只创建 collector 用的浅拷贝，不直接污染 `analysis.data_pack` 原对象。
- 支持将 `analysis.decision` 中的 `final_decision` 或 `action` 暴露给 `TradingSignalCollector`。
- 同步传递 `shares`、`confidence`、`reason`、`price` 等 FSM adapter 字段。
- 真实 `DecisionBrain` 输出的 `final_score` 会被归一化为 `confidence = final_score / 100`，并限制在 `[0.0, 1.0]`。

覆盖风险:

- 修复 P0-2 中 `AnalysisService.run_ticker_analysis()` 返回了 `decision`，但 pipeline 只把 `data_pack` 交给 collector，导致最终 FSM 决策无法进入回测的问题。

## 新增回归测试

文件:

- `tests/test_phase4_2_contracts.py`

覆盖用例:

- factory 初始化失败必须 fail-fast 抛 `RuntimeError`，不能返回 `None`。
- `AnalysisService` 构造后必须把外部 factory 的 orchestrator 回绑为自身。
- 回绑后 `factory.fsm.orchestrator is analysis_service`。
- `AnalysisService` 必须暴露 engine adapter 所需的小接口。
- 仅存在 FSM `decision.final_decision=EXECUTE_BUY` 时，pipeline 必须产出标准 `TradingSignal(action="BUY")`。
- 真实 `final_score=87` 必须映射为 `TradingSignal.confidence ~= 0.87`。

## 验证记录

已执行:

```bash
python3 -m pytest tests/test_phase4_2_contracts.py -q
```

结果:

- `3 passed, 2 warnings`

已执行:

```bash
python3 -m pytest tests/test_engine_factory.py tests/test_service_container.py tests/test_e2e_pipeline.py tests/test_analysis_engines.py tests/test_e2e_integration_qa.py -q
```

结果:

- `123 passed, 3 warnings`

已执行:

```bash
python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py -q
```

结果:

- `8 passed, 2 warnings`

已执行:

```bash
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

结果:

- `imports OK`

已执行:

```bash
python3 - <<'PY'
from unittest.mock import Mock
import pandas as pd
from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
from uniquant.services.analysis_service_v2 import AnalysisService

svc = AnalysisService(data_service=Mock(), engine_factory=AnalysisEngineFactory(orchestrator=Mock()))
assert svc._factory._orchestrator is svc
assert svc._factory.fsm.orchestrator is svc
sample = pd.DataFrame({'date': pd.to_datetime(['2025-01-02']), 'close': [10.12345]})
assert len(svc._sample_data(sample, max_rows=10)) == 1
assert svc.ensure_precision_consistency({'confidence': 0.123456, 'close': 10.123456})['confidence'] == 0.1235
print('contract smoke OK')
PY
```

结果:

- `contract smoke OK`

## 残留风险

- 未运行全量 `pytest tests/ -q`，因为项目仍有既有历史失败/收集错误背景，阶段 4.2 只做接口契约手术修复。
- P0-3 风险引擎失败默认 Safe/NORMAL 尚未处理，需要阶段 4.3 与被动风控策略一起收敛。
- P1-1 缓存失效广播仍未处理。
- P1-2 旧/新回测入口统一仍未处理。
- P1-3 服务内部直接 new `DataFetcher/StorageManager` 的数据入口多轨问题仍未处理。
