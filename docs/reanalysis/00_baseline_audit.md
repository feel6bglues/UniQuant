# Phase 0 — 基线审计报告

> 日期: 2026-06-30 | 提交: dd5faf4 | 分析人: opencode

---

## 1. 运行基线

| 检查项 | 结果 | 详情 |
|--------|------|------|
| `pytest tests/ -q --tb=short` | **1426 pass, 5 fail, 8 skip** | 5 个预存失败（survivorship_warning + unified_matching） |
| `ruff check src/uniquant/` | **29 errors** | 均为 F401（未使用导入）/ F841（未使用变量）/ F821（未定义变量） |
| 八层导入 | **✅ 通过** | `shared, data, brain, signal, hands, risk, services, ui` |
| `container.initialize()` | **✅ 通过** | ServiceContainer DAG 初始化成功 |
| `git status --short` | **仅未跟踪分析文档** | 工作树干净 |

## 2. 当前项目度

| 指标 | 值 |
|------|-----|
| Python 源文件 | 252 |
| 源文件 LOC | 62,389 |
| 测试文件 | 120 |
| 测试通过 | 1,426 |
| 测试失败 | 5（pre-existing） |

### 分层统计

| 层 | 文件数 | LOC | 说明 |
|----|--------|-----|------|
| shared | 45 | 7,132 | +1 文件（result_store.py）自上次基线 |
| data | 65 | 15,532 | 未变动 |
| brain | 53 | 15,977 | -19 文件（比 74 个的旧计数减少，合并/清理后） |
| signal | 8 | 2,669 | +1 文件 |
| hands | 34 | 6,336 | 未变动 |
| risk | 6 | 1,638 | -1 文件（historical_risk.py 被删除） |
| services | 32 | 9,741 | +1 文件 |
| ui | 8 | 3,363 | 未变动 |

## 3. Ruff 问题分类

| 模式 | 计数 | 严重度 | 说明 |
|------|------|--------|------|
| F401 未使用导入 `datetime` | 15 | 低 | `datetime` 已导入但未使用，多数在 data/scripts 中 |
| F841 未使用变量 | 6 | 低 | 赋值后未使用 |
| F821 未定义名称 `datetime` | 1 | **中** | `macro_service.py:214` 缺少 import |
| 总计 | 29 个 | 低 | 20 个可 `--fix` 自动修复 |

**关键发现**: `macro_service.py:214` 的 `datetime.timedelta` 引用缺少 import — 这是一个运行时 bug 点。

## 4. 测试失败详情

```
FAILED tests/hands/backtest/test_survivorship_warning.py::TestSurvivorshipWarning::test_metadata_trading_days_count
FAILED tests/test_unified_matching.py::TestDefenseB_LimitUpDown::test_limit_down_blocks_sell
FAILED tests/test_unified_matching.py::TestDefenseE_AsymmetricCosts::test_buy_no_stamp_duty
FAILED tests/test_unified_matching.py::TestDefenseE_AsymmetricCosts::test_min_commission_enforced
FAILED tests/test_unified_matching.py::TestDefenseF_SlippageDirection::test_buy_slippage_upward
```

**诊断**: 5 个测试均为此前 Phase 5/6 中已确认的预存失败，与本轮提交无关。

---

## 基线结论

项目当前处于健康状态：**1426/1431（99.6%）测试通过**，八层导入正常，工作树干净。预存失败的 5 个测试需要独立排查，但不影响其余功能。29 个 lint 问题中仅 `macro_service.py:214` 可能造成运行时错误。
