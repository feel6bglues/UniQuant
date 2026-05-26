# UniQuant 项目状态仪表盘

> 最后更新: 2026-05-26 | 代码版本: 44 文件 | 重构进度: Phase 0 未执行 | 文档: 34 文件 (4 可信, 10 不可信)

---

## 总览

```
完成度: ██████░░░░░░░░░░░░░░ ~28% 源码就绪 (44/160 文件, ~12.6K LOC)
测试数: █░░░░░░░░░░░░░░░░░░░ 10/65+ 测试文件 (仅 1 个可运行)
重构:   ░░░░░░░░░░░░░░░░░░░░ Phase 0 未开始
文档可信度: ████░░░░░░░░░░░░ 25% 可信 (4/23 文档完全可信)
```

---

## 模块状态

### ✅ 已就绪

| 包 | 文件 | 说明 |
|----|------|------|
| `shared/` | 23 | constants, exceptions, config_loader, logger_factory, interfaces, retry_decorator, cost_model, slippage_model, limit_checker, env_config, error_handling, errors, limits, analysis_result, di_container, import_state, optimal_params, utils, cache/ (4 files) |

### ⚠️ 部分就绪

| 包 | 文件 | 缺失模块 |
|----|------|---------|
| `services/` | 11 | data_service, validation_service, cache_coordinator, stock_query_service, scan_service, portfolio_service, data_access_service, data_quality_service, health_service, analysis/fsm_analysis_engine, analysis/lppl_analysis_engine, analysis/macro_analysis_engine, analysis/signal_service, analysis/wyckoff_analysis_engine |
| `brain/` | 5 | indicators, alpha_decoupler, ntf/, regime/, factors/, screener/, wyckoff/, lppl/ (7 of 9 submodules) |
| `ui/` | 2 | components, lppl_visualizer, manager_logic, manager_report_service, manager_portfolio_analytics_service |
| `risk/` | 1 | evt_risk, historical_risk, portfolio_optimizer, sizer, structural |
| `tests/` | 11 | 55+ 测试文件待迁移 |

### 🔴 待迁移

| 包 | 说明 | 迁移阶段 |
|----|------|---------|
| `data/` | 整个数据层 (40+ 文件) | Phase 1B |
| `signal/` | 整个信号层 (6 文件) | 需新建 |
| `hands/backtest/` | 回测引擎 (8+ 文件) | Phase 1E |
| `hands/strategies/` | 策略库 (7+ 文件) | Phase 1E |

---

## 重构进度

| Phase | 名称 | 状态 | 预计时间 |
|-------|------|------|---------|
| 0 | 紧急修复 (导入链恢复) | ⬜ 未开始 | 0.5h |
| 1A | Shared 基础层迁移 | ⬜ 未开始 | 0.5h |
| 1B | Data 全层迁移 | ⬜ 未开始 | 1.5h |
| 1C | Services 层迁移 | ⬜ 未开始 | 0.5h |
| 1D | Brain LPPL + Factor | ⬜ 未开始 | 0.5h |
| 1E | Hands + 回测 | ⬜ 未开始 | 0.3h |
| 1F | UI 层迁移 | ⬜ 未开始 | 0.3h |
| 2 | mootdx 适配 | ⬜ 未开始 | 2.5h |
| 3 | 验证 + 修复 | ⬜ 未开始 | 1.5h |
| 4 | 清理 | ⬜ 未开始 | 0.5h |

---

## 测试状态

| 类别 | 文件数 | 通过 | 失败 | 说明 |
|------|--------|------|------|------|
| brain 引擎 | 5 | ~40 | ~5 | czsc, fsm, ntf, regime |
| services | 4 | ~30 | ~3 | engine_factory, regressions |
| shared | 2 | ~15 | ~2 | error_handling, retry |
| **总计** | **11** | **~85** | **~10** | |

> 测试文件: `tests/` 目录下 11 个文件

---

## 阻塞问题

| # | 问题 | 影响 | 阻塞的 Phase |
|---|------|------|-------------|
| 1 | `import uniquant` 因幽灵导入崩溃 | 所有下游模块无法使用 | Phase 0 |
| 2 | `data/` 包完全不存在 | services/data_service 无法运行 | Phase 1B |
| 3 | `signal/` 包完全不存在 | 信号聚合流程不可用 | 需新建 |
| 4 | `hands/backtest/` 不存在 | 回测能力不可用 | Phase 1E |
| 5 | TDX 源码完整性未验证 | 所有迁移依赖 TDX | Phase 1 |

---

## 文档状态

| 文档 | 状态 | 说明 |
|------|------|------|
| README.md | ✅ 已更新 | 项目入口 |
| STATUS.md | ✅ 本文件 | 状态仪表盘 |
| EVALUATION_REPORT.md | ✅ 新建 | 全景差异分析 (docs vs 代码) |
| VERIFICATION_REPORT.md | ✅ 新建 | 4 Agent 独立核实，修正 7 项数据差异 |
| architecture.md | ⚠️ 需更新 | 描述目标架构，非当前状态 |
| packages/*.md | ⚠️ 需标注 | 描述目标 API，非当前可用 |
| guides/*.md | ❌ 不可用 | 引用不存在的模块，代码示例无法运行 |
| reference/*.md | ✅ 可用 | 基于 constants.py，准确 |
| development/*.md | ⚠️ 需更新 | 测试数和文件清单严重不符 |
| DOC_MANAGEMENT_PLAN.md | ✅ 已更新 | 文档管理规范 |

### 文档可信度分布

```
完全可信 (4):  reference/constants, exceptions, a_share_constraints, packages/shared
部分可信 (9):  architecture, packages/brain/services/risk/ui, STATUS, RESTRUCTURE_PLAN, guides/configuration, index
不可信 (10):   packages/data/hands/signal, guides/quickstart/backtest/factors/strategies/data_sources, development/testing/project_structure
```

详细差异分析请参阅 [EVALUATION_REPORT.md](EVALUATION_REPORT.md)。
