# 06.5 P2 Final Closure

日期: 2026-06-08

## 状态

已完成。

本阶段用于收口 P2 工程级剩余风险修复，并执行最终回归。

## 输入状态

只读取并复核以下已落盘文件:

- `MASTER_REMEDIATION_PLAN.md`
- `docs/reshaping_logs/06_1_p2_trace_id.md`
- `docs/reshaping_logs/06_2_p2_ui_risk_boundary.md`
- `docs/reshaping_logs/06_3_p2_docs_state_boundary.md`
- `docs/reshaping_logs/06_4_p2_randomness_annotations.md`
- `docs/reshaping_logs/README.md`

## P2 闭环复核

| 风险 | 状态 | 证据 |
|------|------|------|
| P2-1 TraceID 缺失 | 已闭环 | `06_1_p2_trace_id.md` |
| P2-2 UI 越层调用 risk | 已闭环 | `06_2_p2_ui_risk_boundary.md` |
| P2-3 历史文档状态混乱 | 已闭环 | `06_3_p2_docs_state_boundary.md` |
| P2-4 网络/mock 随机未标注 | 已闭环 | `06_4_p2_randomness_annotations.md` |

## 最终验证

### P1/P2 组合回归

命令:

```bash
python3 -m pytest tests/test_phase4_1_remediation.py tests/test_phase4_2_contracts.py tests/test_phase4_3_risk_guardrails.py tests/test_p1_cache_invalidation.py tests/test_p1_backtest_compat.py tests/test_p1_data_entry_injection.py tests/test_factor_composer.py tests/test_p1_reproducibility.py tests/test_di_container_and_cache.py tests/test_manager_portfolio_analytics_service.py tests/test_p2_randomness_annotations.py -q
```

结果:

- 54 passed
- 5 warnings

### 全量测试

命令:

```bash
python3 -m pytest tests/ -q
```

结果:

- 1024 passed
- 7 skipped
- 12 warnings
- 0 failed

### 导入门禁

命令:

```bash
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

结果:

- imports OK

### P2 触达文件 lint

命令:

```bash
python3 -m ruff check tests/test_p2_randomness_annotations.py tests/test_manager_portfolio_analytics_service.py tests/test_phase4_2_contracts.py src/uniquant/services/analysis_service_v2.py src/uniquant/services/research_pipeline.py src/uniquant/services/portfolio_service.py src/uniquant/ui/manager_portfolio_analytics_service.py src/uniquant/shared/error_handling.py src/uniquant/data/utils/request_utils.py src/uniquant/data/utils/akshare_wrapper.py src/uniquant/data/utils/js_executor.py src/uniquant/data/sources/eastmoney.py src/uniquant/data/sources/sina.py src/uniquant/data/sources/tencent.py src/uniquant/data/sources/realtime_bridge.py src/uniquant/data/scripts/update_daily_data_akshare.py src/uniquant/data/scripts/update_daily_incremental.py
```

结果:

- 通过。

### Diff 格式检查

命令:

```bash
git diff --check
```

结果:

- 通过。

## 全仓 lint 说明

命令:

```bash
python3 -m ruff check src/uniquant tests
```

结果:

- 未通过。
- 共 117 个既有全仓 lint 问题，集中在历史/未纳入本轮 P2 修改范围的文件，例如:
  - `src/uniquant/brain/lppl/core.py`: E402/E702。
  - `src/uniquant/hands/backtest/portfolio_engine.py`: E402。
  - 多个测试文件: 未使用 import、重复测试函数名、无占位 f-string。
- 本轮不扩展修复 117 个 lint 项，避免 P2 收口变成大规模历史风格债清理。
- 本轮 P2 触达文件 lint 已通过。

## 结论

P0/P1/P2 当前计划内风险均已完成修复或边界收敛，并通过全量测试。

## 下一挂起点

是否进入全仓 lint 历史债清理，或准备提交/生成最终变更摘要。
