# Phase 9 — 最终建议路线图

> 日期: 2026-06-30 | 基于 Phase 0-8 审计结论

---

## 当前评级总览

| Phase | 领域 | 评级 |
|---|---|---|
| 0 | 基线审计 | ✅ 1426 pass / 5 pre-existing |
| 1 | 工作树分析 | ✅ 46 文件提交, 3 stash |
| 2 | 引擎正确性 | A- (7/8 引擎 A 级, Wyckoff B⚠️) |
| 3 | 回测信任 | A- (7 防线全部通过) |
| 4 | 数据管道 | B+ (架构好, 轻度碎片化) |
| 5 | 信号系统 | A (8 适配器, 仲裁逻辑清晰) |
| 6 | 工程健康 | A- (低技术债, 29 lint, 5 TODO) |
| 7 | 生产就绪 | B+ (安全好, 可观测待增强) |
| 8 | 治理测试 | B+ (测试好, CI/CD 缺失) |

---

## 建议优先级

### P0 (立即处理)

| 项目 | 文件 | 类型 |
|---|---|---|
| 修复 `macro_service.py:214` 未定义 `datetime` | `src/.../macro_service.py` | Bug |
| 添加 CI 配置 (GitHub Actions) | — | 基础设施 |
| 设置测试覆盖率门禁 (80%) | `pyproject.toml` | 测试 |

### P1 (本周)

| 项目 | 类型 |
|---|---|
| ~~删除 `DataIngestionService` 僵尸代码~~ | ✅ `bc6337bc` |
| 统一 `all_stock_codes.csv` / `stock_list.csv` | 数据 |
| 添加 `ruff check --fix` 修复 20 个 F401 未使用 import | Lint |
| 添加健康检查端点 `ServiceContainer.health()` | 运维 |

### P2 (未来 2 周)

| 项目 | 类型 |
|---|---|
| 添加 E2E 测试 (Pipeline → Brain → Signal → Backtest) | 测试 |
| 修复 5 个 pre-existing 测试失败 | 测试 |
| 拆分 `eastmoney.py` (1090 LOC) | 重构 |
| 添加配置 schema 验证 (Pydantic) | 健壮性 |
| 添加 Prometheus/OpenTelemetry 指标 | 可观测 |

### P3 (未来 1-2 月)

| 项目 | 类型 |
|---|---|
| 添加性能基准测试 | 测试 |
| 添加 CODEOWNERS | 治理 |
| 替换 `limit_checker.get_board_type()` / `detect_board()` 为统一注册表 | 重构 |
| 集成 `SlippageModel` 抽象类到引擎 | 一致性 |
| 添加无风险利率参数到 `BacktestResult.sharpe` | 正确性 |

---

## 架构改进建议

### 1. 统一板块类型注册表
当前两个识别路径 (`limit_checker.get_board_type()` + `market_rules.detect_board()`) 独立。
建议创建 `BoardTypeRegistry` 作为单一真相源, 所有组件从此引用。

### 2. 适配器自动发现
`TradingSignalCollector.collect()` 手动列出 8 个引擎提取方法。建议改为
通过 `AdapterRegistry` 自动发现已注册的引擎方法。

### 3. 仓位计算标准化
当前仓位计算分布在 `SignalArbitrator.arbitrate_candidates()` (使用 `PositionSizerProtocol`)
和 `UnifiedBacktestEngine._execute_buy()` (硬编码 lot 取整)。建议统一仓位策略。

### 4. 配置 schema 验证
当前配置 (`config.yaml`) 无 schema 验证。建议添加 Pydantic model 验证,
捕获缺失/类型错误的配置项在初始化时, 而非运行时。

---

## 最终结论

UniQuant 是一个 **成熟的 A 股量化研究平台**:

- **254 源文件, 62,389 LOC** — 规模适中
- **1,435 测试, 99.4% 通过** — 测试覆盖充足
- **8 引擎, 7 防线, 5 源路由** — 架构鲁棒
- **5 TODO, 29 lint, 0 FIXME** — 技术债务极低

**当前就绪状态: Beta → 生产过渡期**

核心量化逻辑 (引擎 + 回测 + 信号) 已达到生产质量。
主要缺口在运维基础设施 (CI/CD, 健康检查, 指标, 日志聚合)。
填补这些缺口后, 可称为生产就绪。
