# Phase 8 — 治理与测试体系审计

> ⚠️ **历史快照（point-in-time audit）** — 本文档记录的是**撰写时点**的工作树状态。其中的文件数 / LOC / 测试数 / 覆盖率 / 死代码清单 / "已修复" 声明**均可能已失效**，且已知与当前实测口径不符。
> **请勿**将其作为当前状态的依据。当前真相源见 [`docs/index.md`](../index.md)、[`AGENTS.md`](../../AGENTS.md) 与 [`docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`](../analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md)。

> 日期: 2026-06-30 (base) / 2026-07-09 (corrected)
> 方法: 测试结构 + 覆盖率 + CI 就绪度评估
> **纠正**: 测试文件 120→126, 测试函数 1,435→1,666, 失败 5→0

---

## 报告摘要

测试体系健康: 126 测试文件, 1,666 测试函数, 100% 通过率, 测试覆盖所有 8 层。
主要缺口: 无正式覆盖率门禁, 无 E2E 测试, 无 CI 配置。

**测试评级: B+** (数量充足, 结构清晰, 基础设施缺失)

---

## 测试分布

| 层级 | 测试文件数 | 代表性测试文件 |
|---|---|---|
| shared | ~15 | `test_cost_model`, `test_time_provider`, `test_interfaces` |
| data | ~10 | `test_data_fetcher`, `test_source_router` |
| brain | ~20 | `test_regime_detector`, `test_wyckoff`, `test_czsc` |
| signal | ~8 | `test_adapters`, `test_arbitrator` |
| hands | ~20 | `test_unified_engine`, `test_unified_matching`, `test_backtest_compare` |
| risk | ~10 | `test_sizer`, `test_drawdown`, `test_evt` |
| services | ~15 | `test_service_container`, `test_analysis_service` |
| ui | ~2 | dashboard smoke tests |

**总计**: 126 测试文件, 1,666 测试函数

---

## 测试质量

| 维度 | 状态 | 备注 |
|---|---|---|
| TDD 实践 | ✅ | 防线测试套件, 边界条件测试 |
| 断言质量 | ✅ | 具体业务断言, 非简单 assert True |
| Mock 使用 | ✅ | FakeTradeCalendarManager, 模拟数据源 |
| 参数化测试 | ⚠️ | 有限使用, 多由 fixture 驱动 |
| 集成测试 | ✅ | 引擎 + 匹配 + 管线端到端 |
| 性能测试 | ❌ | 无 |

## 测试缺口

| 缺口 | 影响 | 优先级 |
|---|---|---|
| 无覆盖率门禁 | 无法阻止覆盖率退化 | P2 |
| 无 E2E 测试 | 无法验证完整用户流程 | P2 |
| 无 CI 配置 | 无法自动运行测试 | P1 |
| 5 个 pre-existing 失败 | 长期未修复可能掩盖新失败 | P2 |
| 无性能基准 | 无法检测回归 | P3 |

---

## 治理

| 维度 | 状态 | 备注 |
|---|---|---|
| Conventional Commits | ✅ | `feat:`, `fix:`, `docs:`, `chore:` 等 |
| AGENTS.md 同步 | ✅ | 每次代码变更后更新 |
| 文档同步纪律 | ✅ | Phase 0-6 文档维护良好 |
| 安全 PR 审查 | ⚠️ | 无正式 security-reviewer 流程 |
| 代码所有权 | ❌ | 无 CODEOWNERS |

---

## 测试评级: B+

| 维度 | 评分 | 理由 |
|---|---|---|
| 测试数量 | A | 126 文件, 1,666 函数, 8 层全覆盖 |
| 测试质量 | A- | TDD 防线套件, 具体断言 |
| CI/CD | D | 无 CI 配置 |
| 覆盖率门禁 | D | 无门禁 |
| 治理纪律 | A- | Commit 规范, 文档同步 |
