# Phase 4 — 建议门禁清单

> 2026-07-01 | 仅记录建议，未实施
> 基于 Phase 0-3 发现

---

## 1. 代码质量门禁

### G1. Ruff 零容忍

| 字段 | 值 |
|---|---|
| 当前状态 | ✅ 已实现 (`ruff check src/uniquant/` passes) |
| 门禁位置 | CI workflow |
| 建议 | 保持当前状态, 设 CI 阻断 |

### G2. 测试零失败

| 字段 | 值 |
|---|---|
| 当前状态 | ⚠️ 1431 pass / 8 skip (无 fail) |
| 门禁位置 | CI workflow |
| 建议 | `pytest tests/ -q --tb=short` CI step, 任何 failure 阻断合并 |

### G3. 覆盖率门禁提升

| 字段 | 值 |
|---|---|
| 当前门禁 | 50% (`pyproject.toml` `--cov-fail-under=50`) |
| 当前实际 | 50.77% (余量 0.77pp) |
| 建议路径 | 50% → 60% → 70% → 80% |
| 阻断文件 | ~~`signal/db.py` (0%)~~ ✅ 35 tests, 93% coverage, `perf.py` (0%) |
| 备注 | `price_collar.py` (32 行包装函数, 逻辑在 `market_rules.get_board_rule()` 中已测); `slippage_model.py` (44 行抽象死代码, 未接入任何引擎) — 这两个的 0% 不是风险 |

### G4. Import 链完整性

| 字段 | 值 |
|---|---|
| 当前状态 | ✅ 8 层 import pass |
| 建议 | CI 中运行 `python3 -c "import uniquant.shared, ..."` |

### G5. 基线回归检测

| 字段 | 值 |
|---|---|
| 当前状态 | ✅ `capture_baseline.py` + `compare_baseline.py` 可用 |
| 建议 | CI 中运行基线对比, diff 检测回测数值变化 |

---

## 2. 文档门禁

### G6. 文档路径验证

| 字段 | 值 |
|---|---|
| 当前状态 | ✅ `verify_doc_paths.py` 已创建 + pre-commit hook 已配 |
| 建议 | 保持, CI 中添加验证 step |

### G7. 文档-代码比例监控

| 字段 | 值 |
|---|---|
| 当前比率 | 98,128 docs LOC / 62,300 code LOC = **1.57x** |
| 建议阈值 | 新增 .md 时审查是否重复现有内容 |
| 注意 | 不作为自动阻断, 仅 PR 审查提醒 |

### G8. 分析报告去重检查

| 字段 | 值 |
|---|---|
| 问题 | 6 个分析纪元覆盖相同子系统 |
| 建议 | 新分析报告 PR 需声明:"本报告与现有 `reanalysis/` 或 `analysis/` 中哪些内容不同" |

---

## 3. 工程门禁

### G9. 隐式 datetime.now 检测

| 字段 | 值 |
|---|---|
| 风险 | 未通过 `TimeProvider` 的 `datetime.now()` 导致不可测 + 回测时间错位 |
| 检测方法 | `grep -rn "datetime.now\|datetime\.today\|pd\.Timestamp\.now\|pd\.datetime\.now" src/` |
| 当前问题 | `time_provider.py` 中 2 处 guarded fallback |
| 建议 | CI 中添加 grep, 发现则 warn |

### G10. 双系统一致性检查

| 字段 | 值 |
|---|---|
| 目标 | `limit_checker.get_board_type()` vs `market_rules.detect_board()` |
| 建议 | 创建自动化脚本 `scripts/verify_board_consistency.py`, 定期运行 |
| 触发 | 修改 `limit_checker.py` 或 `market_rules.py` 时必运行 |

### G11. 无 `pass` 占位符

| 字段 | 值 |
|---|---|
| 当前 | 已清理 (czsc 工作树修改后) |
| 建议 | `grep -rn "^\s*pass$" src/uniquant/` CI check, 仅允许带 `# noqa` 的例外 |

---

## 4. CI/CD 门禁矩阵

建议的完整 CI pipeline:

```yaml
# 建议顺序 (全部 blocking)
steps:
  - ruff check src/uniquant/
  - pytest tests/ -q --tb=short --cov=src/uniquant --cov-fail-under=50
  - python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui"
  - python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py
  - python3 scripts/verify_doc_paths.py
  - grep -rn "datetime\.now\|\.today()" src/uniquant/ --include="*.py"  # warn only
```

---

## 实施优先级

| 门禁 | 难度 | 影响 | 建议阶段 |
|---|---|---|---|
| G1 Ruff | 已实现 | 高 | — |
| G2 测试 | 已实现 | 高 | — |
| G3 覆盖率 | 低 (改数字) | 高 | P0 |
| G4 Import | 已实现 | 中 | — |
| G5 基线 | 已实现 | 高 | — |
| G6 路径验证 | 已实现 | 中 | — |
| G7 文档比例 | 审查规则 | 低 | P3 |
| G8 去重 | 审查规则 | 低 | P3 |
| G9 datetime.now | 低 (grep) | 中 | P1 |
| G10 双系统 | 低 (脚本) | 中 | P1 |
| G11 pass | 低 (grep) | 低 | P2 |
