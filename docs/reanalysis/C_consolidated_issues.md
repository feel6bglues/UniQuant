# Phase 3 — 完整问题记录与整合

> 整合 6 个分析纪元 + 工作树 Delta 的发现
> 2026-07-01 | 仅记录，不修复

---

## 状态总览

```text
分析纪元: 6 个 (archive, analysis, institutional, reshaping_logs, reanalysis, 本报告)
源报告:   10+ 份
问题总数: 22 项
已解决:    7 项 (bc6337bc + BoardType P0.2 closed + signal/db 0% 报告错误纠正)
待处理:   15 项
```

---

## 已解决 (bc6337bc, 2026-06-30)

| # | 问题 | 来源 | 解决方式 |
|---|---|---|---|
| ✅ | `macro_service.py` 未定义 `datetime` | `reanalysis/09_final_roadmap.md` P0 | `import datetime` 已加 |
| ✅ | CI 配置缺失 | `reanalysis/09_final_roadmap.md` P0 | `.github/workflows/test.yml` 已加 |
| ✅ | `DataIngestionService` 僵尸代码 | `reanalysis/09_final_roadmap.md` P1 | 删除 |
| ✅ | 20 个 F401 未使用 import | `reanalysis/09_final_roadmap.md` P1 | Ruff 已清零 |
| ✅ | 5 个 pre-existing 测试失败 | `reanalysis/09_final_roadmap.md` P2 | 全部修复, 1431 pass |

---

## P0 — 立即处理 (4 项)

### P0.1 Coverage 门禁过低

| 字段 | 值 |
|---|---|
| 当前门禁 | 50% (pyproject.toml:59) |
| 当前实际 | 50.77% |
| 目标 | 80% |
| 风险 | 门禁几乎无意义 — 差 0.77% 即触发失败 |
| 关键未覆盖路径 | `price_collar.py` (0%), `slippage_model.py` (0%), `perf.py` (0%) — `signal/db.py` **93%（此前 0% 报告错误）** |

### ~~P0.2 板块类型双系统 (BoardType)~~ ✅ CLOSED (2026-07-09)

| 字段 | 值 |
|---|---|---|
| 系统 A | `limit_checker.get_board_type()` → string: `'main'/'gem'/'sci_tech'/'beijing'/'st'` |
| 系统 B | `market_rules.detect_board()` → `BoardType` enum: `MAIN_SH/MAIN_SZ/GEM/STAR/BEIJING/ST` |
| 被引用 | A: 3 处 (unified_engine, matching_engine, limit_checker 自身); B: 2 处 (market_rules, shared/__init__) |
| 当前一致性 | ✅ **已通过 `board_registry.py` 统一注册表解决** (116 LOC, unified BoardType API) |
| 风险 | ✅ 已消除 — `board_registry.py` 提供双向映射 |
| 建议 | ✅ 已实现 — `BoardTypeRegistry` 统一注册表 |
| 工作树 | 已提交, `board_registry.py` 在 `shared/` 中 |

### P0.3 TradeCalendar 硬编码到期

| 字段 | 值 |
|---|---|
| 文件 | `src/uniquant/data/managers/trade_calendar_manager.py` |
| 硬编码范围 | 2024-2026 (35 个节假日) |
| 覆盖年份 | 3 年 |
| 到期风险 | 2027-01-01 后回测静默使用错误交易日历 |
| AkShare fallback | 存在但需网络且 >180 天 stale 检测 |
| 建议 | 扩展硬编码至 2028 或改为配置化 (`config.yaml`) |

### P0.4 工作树 6 文件未提交

| 文件 | 变更 | 风险 |
|---|---|---|
| `stock_metadata_manager.py` | 死代码删除 (-60 行) | 🟢 无 |
| `result.py` + `unified_engine.py` | Sharpe 比率合并 | 🟢 无 |
| `czsc_analysis_engine.py` | Lint 合规 + TODO 标记 | 🟢 低 |
| `limit_checker.py` + `market_rules.py` | 治理注释 | 🟢 无 |

---

## P1 — 本周处理 (5 项)

### P1.1 Config Schema 验证

| 字段 | 值 |
|---|---|
| 来源 | `reanalysis/09_final_roadmap.md` P2 |
| 当前 | `config.yaml` 无 Pydantic schema, 运行时才暴露错误 |
| 风险 | 配置项缺失/类型错误在运行时崩溃而非启动时 |
| 建议 | 添加 `ConfigModel` Pydantic class + 初始化时验证 |

### P1.2 ServiceContainer.health() 健康检查

| 来源 | `reanalysis/09_final_roadmap.md` P1 |
|---|---|
| 文件 | `src/uniquant/services/health_service.py` (已有基础框架) |
| 当前 | Streamlit dashboard 有健康检查, 但无独立 API 端点 |
| 建议 | `ServiceContainer.health()` 返回各服务状态 dict |

### P1.3 统一 `all_stock_codes.csv` / `stock_list.csv`

| 来源 | `reanalysis/09_final_roadmap.md` P1 |
|---|---|
| 当前 | `StockMetadataManager` 中有两个独立 CSV 路径: `all_stock_codes.csv` (已加载) 和 `stock_list.csv` (`_load_stock_list` 已删除但文件仍存在) |
| 工作树 | `_load_stock_list()` 已删除 |
| 剩余 | 确认 `stock_list.csv` 是否可删除或合并 |

### ~~P1.4 EastMoney 巨型文件~~ ✅ CLOSED

| 来源 | `reanalysis/09_final_roadmap.md` P2 |
|---|---|---|
| 文件 | ~~`src/uniquant/data/sources/eastmoney.py` (1090 LOC)~~ ✅ 已拆分为 4 模块: eastmoney.py (3 LOC re-export), eastmoney_base.py, eastmoney_financial.py, eastmoney_quote.py |
| 原 TODO | 已处理 |
| 建议 | ✅ 已完成 |

### P1.5 GitHub Actions CI 未含基线对比

| 来源 | Phase 2 Delta + 红蓝对抗 |
|---|---|
| 配置 | `.github/workflows/test.yml` 已添加 (28 行) |
| 运行状态 | 可运行 — 覆盖率门禁由 `pyproject.toml:59` addopts 隐式生效, 不需在 CI 中显式指定 |
| 缺失 | 未包含 `scripts/compare_baseline.py` 基线对比步骤 |
| 建议 | CI 中添加基线对比 + 独立覆盖率门禁显式指定 |

---

## P2 — 未来 2 周 (5 项)

### P2.1 代码中 TODO 清理

| 位置 | TODO 内容 | 引入时间 |
|---|---|---|
| `brain/fsm/fsm.py:23` | Phase 1A 迁移后移除 Indicators 回退 | 遗留 |
| `risk/sizer.py:457` | Enforce max_single_sector_pct | 遗留 |
| `data/sources/eastmoney.py:27` | 巨型类拆分 | 遗留 |
| `services/analysis/czsc_analysis_engine.py:121,144,154` | CZSCOutput 字段接入 (工作树新增) | 2026-07-01 |

### P2.2 E2E 测试缺失

| 来源 | `reanalysis/09_final_roadmap.md` P2 |
|---|---|
| 当前 | 单元测试充足 (1431), 无跨层 E2E |
| 建议 | Pipeline → Brain → Signal → Backtest 全链路 E2E |

### P2.3 Prometheus/OpenTelemetry 指标

| 来源 | `reanalysis/07_production_readiness.md` |
|---|---|
| 当前 | 仅 Streamlit dashboard, 无结构化指标输出 |
| 建议 | 添加引擎耗时、信号计数、回测结果指标 |

### P2.4 SlippageModel 抽象类未集成

| 来源 | `reanalysis/09_final_roadmap.md` P3 |
|---|---|
| 当前 | `src/uniquant/shared/slippage_model.py` 存在但 0% 测试覆盖, 未接入引擎 |
| 建议 | 集成 `SlippageModel` 到 matching engine |

### P2.5 无风险利率参数

| 来源 | `reanalysis/09_final_roadmap.md` P3 |
|---|---|
| 当前 | `BacktestResult.sharpe` 使用 `RISK_FREE_RATE=0.03` (cost_model.py:39), 非 0 |
| 建议 | 已满足 — `calculate_sharpe_ratio()` 默认 `risk_free_rate=RISK_FREE_RATE` |
| 状态 | ✅ 已关闭 (红蓝对抗确认: 早期分析错误) |

---

## P3 — 长期 (3 项)

### P3.1 适配器自动发现

| 来源 | `reanalysis/09_final_roadmap.md` 架构建议 2 |
|---|---|
| 当前 | `TradingSignalCollector.collect()` 手动列出 8 个引擎提取方法 |
| 建议 | `AdapterRegistry` 自动发现 |

### P3.2 仓位计算标准化

| 来源 | `reanalysis/09_final_roadmap.md` 架构建议 3 |
|---|---|
| 当前 | `SignalArbitrator` (PositionSizerProtocol) 与 `UnifiedBacktestEngine._execute_buy` (硬编码) 两套逻辑 |
| 建议 | 统一仓位策略 |

### P3.3 性能基准测试

| 来源 | `reanalysis/09_final_roadmap.md` P3 |
|---|---|
| 当前 | 无结构化性能回归测试 |
| 建议 | 添加关键路径基准 |

---

## 问题去重分析

以下问题在多个分析纪元中被**独立发现**：

| 问题 | 被发现的纪元数 | 纪元列表 |
|---|---|---|
| BoardType 双系统 | 3 | reanalysis, institutional, 本报告 |
| Config schema 验证 | 3 | reanalysis, institutional, production_readiness |
| 仓位计算标准化 | 3 | reanalysis, institutional, 架构建议 |
| 适配器自动发现 | 2 | reanalysis, 架构建议 |
| TradeCalendar 硬编码 | 2 | reanalysis, 本报告 |
| Coverage 门禁 | 2 | reanalysis, 本报告 |

**结论**: 22 项问题中有 18 项已在 `reanalysis/09_final_roadmap.md` 中记录。本报告新增 4 项:
1. GitHub Actions CI 未实际运行
2. 6 个工作树文件待提交
3. 覆盖率实际余量仅 0.77%
4. 双系统当前已验证一致但有风险
