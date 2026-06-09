# 阶段 4.3 修复日志：被动风控防线

生成时间: 2026-06-08

输入依据:

- `MASTER_REMEDIATION_PLAN.md` 中步骤 4.3 范围。
- `docs/reshaping_logs/02_deep_inspection.md` 中 P0-3。
- `docs/reshaping_logs/04_2_remediation.md` 中残留风险。

范围边界:

- 本阶段只做被动风控闸门，不改整体撮合结构。
- 未处理 P1 缓存广播、旧/新回测统一、数据入口多轨。
- 未做大规模策略参数重构。

## 修复项

### 1. 强类型风险上下文补充 engine_status / engine_errors

文件:

- `src/uniquant/shared/interfaces.py`

变更:

- `MarketRegime` 新增 `UNKNOWN`。
- `MarketSignalContext` 新增 `engine_status` 和 `engine_errors` 字段。
- `from_dict()` / `to_dict()` 支持双向传递关键引擎状态。

目的:

- 让服务层写入的 `ENGINE_FAILED` / `DATA_UNAVAILABLE` 能跨越 Brain 与 Pipeline 边界，进入最终决策。

### 2. AnalysisService 将关键风险失败标记为 UNKNOWN / ENGINE_FAILED

文件:

- `src/uniquant/services/analysis_service_v2.py`

变更:

- `_run_regime()` 在指数数据不可用时返回 `regime="UNKNOWN"`，并写入 `engine_status["regime"]="DATA_UNAVAILABLE"`。
- `_run_regime()` 发生异常时写入 `regime="UNKNOWN"`，`engine_status["regime"]="ENGINE_FAILED"`。
- `_run_lppl()` 在结果缺失 `risk_level` 或状态异常时写入 `risk="ENGINE_FAILED"`、`bubble_confidence=1.0`，并记录 `engine_status["lppl"]="ENGINE_FAILED"`。
- 关键失败路径会同步写入 `engine_errors` 便于审计。

目的:

- 不再把风险引擎失败伪装成 `NORMAL/Safe`。
- 让上层 DecisionBrain 有可判别的 fail-closed 语义。

### 3. DecisionBrain 增加被动风控闸门

文件:

- `src/uniquant/brain/fsm/fsm.py`

变更:

- `_build_response()` 增加 `engine_status` / `engine_errors` 回传。
- 新增 `_risk_engine_blockers()`，识别 `REGIME_UNKNOWN`、`RISK_ENGINE_FAILED` 等关键风险失效状态。
- 新增 `_stop_loss_blockers()`，识别 `STOP_LOSS_MISSING`、`STOP_LOSS_INVALID`、`STOP_LOSS_TOO_WIDE`。
- `_check_veto_conditions()` 在关键风险引擎失效时直接返回 `FORCE_WAIT`，并携带阻断原因。
- `_check_buy_blockers()` 在买入路径叠加风险引擎与止损阻断。

目的:

- 风险 unknown/failed 时不再允许 BUY。
- ATR / 绝对止损缺失或过宽时不再允许 BUY。

### 4. 新增风控回归测试

文件:

- `tests/test_phase4_3_risk_guardrails.py`

覆盖用例:

- `risk="ENGINE_FAILED"` 时不得 BUY。
- `regime="UNKNOWN"` 时不得 BUY。
- `atr_stop=0` 时不得 BUY。
- `atr_stop` 对应亏损比例过宽时不得 BUY。
- `AnalysisService` 的 Regime 失败必须写成 `UNKNOWN` + `DATA_UNAVAILABLE/ENGINE_FAILED`。
- `AnalysisService` 的 LPPL 失败必须写成 `ENGINE_FAILED`。

## 验证记录

已执行:

```bash
python3 -m pytest tests/test_phase4_3_risk_guardrails.py -q
```

结果:

- `6 passed, 1 warning`

已执行:

```bash
python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py -q
```

结果:

- `14 passed, 2 warnings`

已执行:

```bash
python3 -m pytest tests/test_fsm.py tests/test_analysis_engines.py tests/test_e2e_pipeline.py tests/test_e2e_integration_qa.py -q
```

结果:

- `129 passed, 3 warnings`

已执行:

```bash
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

结果:

- `imports OK`

## 残留风险

- P1 缓存失效广播仍未处理。
- P1 旧/新回测入口统一仍未处理。
- P1 数据入口多轨仍未处理。
- 风险闸门目前是保守 fail-closed，后续若要细化阈值需要配置化和审计追踪。
