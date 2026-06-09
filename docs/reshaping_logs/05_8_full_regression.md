# 05.8 Full Regression Closure

日期: 2026-06-08

## 状态

已完成。

本阶段用于收口 P0/P1 修复后的全量回归。未进入 P2 修改。

## 首次全量回归

命令:

```bash
python3 -m pytest tests/ -q
```

首次结果:

- 1014 passed
- 7 skipped
- 5 failed

失败集中在:

- `tests/test_e2e_integration_qa.py::TestBacktestEngineE2E`
- `tests/test_e2e_integration_qa.py::TestDataPipelineE2E::test_cleaner_then_validator_then_backtest`

根因:

- 旧 `BacktestEngine` 在 P1-2 中改为复用 `UnifiedMatchingEngine`。
- 全量 E2E 仍使用 legacy 裸 6 位股票代码 `000001`。
- `_matching_symbol()` 只处理空 symbol，未把裸 6 位代码标准化为 `000001.SZ`。
- 统一撮合器坚持要求 `.SH/.SZ/.BJ` 后缀，因此 `detect_board("000001")` fail-fast 抛出 `ValueError`。

## 补丁

- 扩展 `BacktestEngine._matching_symbol()`:
  - 空 symbol -> `600000.SH`
  - 已带 `.SH/.SZ/.BJ` -> 原样大写返回
  - 裸 6 位 `4/8` 开头 -> `.BJ`
  - 裸 6 位 `0/2/3` 开头 -> `.SZ`
  - 其它裸 6 位 -> `.SH`
- 新增 `tests/test_p1_backtest_compat.py::test_legacy_execute_buy_accepts_bare_six_digit_symbol`。

验证补丁:

```bash
python3 -m pytest tests/test_p1_backtest_compat.py tests/test_backtest_engine.py tests/test_e2e_integration_qa.py::TestBacktestEngineE2E tests/test_e2e_integration_qa.py::TestDataPipelineE2E::test_cleaner_then_validator_then_backtest -q
```

结果:

- 31 passed

目标 lint:

```bash
python3 -m ruff check src/uniquant/hands/backtest/engine.py tests/test_p1_backtest_compat.py
```

结果:

- 通过。

## 最终全量回归

命令:

```bash
python3 -m pytest tests/ -q
```

最终结果:

- 1020 passed
- 7 skipped
- 12 warnings
- 0 failed

## 结论

P0/P1 修复清单已通过全量测试收口。

## 下一挂起点

是否进入 P2 工程级风险修复范围:

- P2-1 TraceID
- P2-2 UI 越层 risk 调用
- P2-3 历史文档状态不一致
- P2-4 mock/network randomness 标注
