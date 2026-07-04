# Phase 1 — 工作树差异分析

> 日期: 2026-06-30 | 提交: dd5faf4 | 分析人: opencode

---

## 1. 本次提交概况

**提交**: `dd5faf4 feat(core): Phase 6+ batch — Wyckoff PnF integration, ResultStore persistence, TOCTOU fix, BacktestResult metrics`

**总量**: 46 文件变更, +9086 / -8118 行

### 变更分类

| 类别 | 文件数 | 占比 |
|------|--------|------|
| 核心源文件 (src/) | 25 | 54% |
| 测试文件 (tests/) | 9 | 20% |
| 文档 (docs/ + AGENTS.md) | 10 | 22% |
| 配置 + 数据 (config/ + data/) | 2 | 4% |

---

## 2. 变更类型分解

### 2.1 Wyckoff 引擎增强（11 个源文件）

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `brain/wyckoff/engine.py` | 功能新增 | P&F 点图分析集成 + RegimeAwarePhaseClassifier + 置信度溢出保护 (np.errstate) |
| `brain/wyckoff/bayesian_events.py` | 修改 | 贝叶斯事件计算调整 |
| `brain/wyckoff/events.py` | 修改 | 事件定义调整 |
| `brain/wyckoff/models.py` | 修改 | 模型字段调整 |
| `brain/wyckoff/monthly_classifier.py` | 修改 | 月线分类器调整 |
| `brain/wyckoff/phase_analysis.py` | **重构** | OBV 计算从 Python for-loop 改为向量化 NumPy |
| `brain/wyckoff/sequence.py` | 修改 | 序列逻辑调整 |
| `services/analysis/wyckoff_analysis_engine.py` | 功能新增 | WyckoffOutput 新增 5 个字段 (pnf_phase_hint, pnf_breakout, pnf_count_target, regime_phase, vshape_detected) |
| `analysis_service_v2.py` | **重构** | CZSC/Wyckoff 输出从 `dict.get()` 改为 `getattr()` — 适配 typed outputs |
| `shared/interfaces.py` | 功能新增 | WyckoffOutput 新增 5 个字段定义 |
| `brain/fsm/fsm.py` | **Bugfix** | FROZEN 状态从 sell conditions 中移除（Phase 6 死代码清理）|

**评估**: Wyckoff 增强有明确的技术方向（P&F + 多时间框架），`getattr()` 改动能逐步淘汰旧 dict 接口。向量化 OBV 是质量改进。**但 engine.py 中 P&F 在 analyze() 和 scan_signal() 中两次实例化，存在代码重复。**

### 2.2 基础设施（8 个源文件）

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `services/market_cache.py` | 功能新增 | `get_or_compute_regime()` 原子化 get-or-compute |
| `services/analysis_service_v2.py` | **重构** | `_run_regime()` 使用新 TOCTOU-safe 路径 |
| `services/research_pipeline.py` | 功能新增 | ResultStore 持久化集成 + Sharpe/MDD 计算 |
| `shared/result_store.py` | **新文件** | AnalysisRecord + ResultStore (JSON 文件存储) |
| `shared/config_models.py` | **默认翻转** | `use_research_data_pack: true` 默认启用 |
| `config/config.yaml` | **默认翻转** | 同上 |
| `hands/backtest/unified_engine.py` | 功能新增 | BacktestResult 新增 4 个属性 (sharpe, max_drawdown, win_rate, profit_factor) + compare() 方法 |
| `hands/__init__.py` | 功能新增 | 添加 DeprecationWarning 到 BacktestEngine/BacktestResult 旧路径 |

**评估**: 这些都是高质量的工程改进。`get_or_compute_regime()` 解决了 Phase 6 识别的 TOCTOU 竞态。ResultStore 提供了研究结果持久化（P1 缺口 R7-1 的修复）。`use_research_data_pack` 默认翻转标志着旧 dict 路径的终极淘汰。

### 2.3 数据层（3 个源文件）

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `data/data_fetcher.py` | **重构** | `get_price()` 跳过 DataIngestionService 直接调用 source_router |
| `data/data_ingestion_service.py` | **重构** | 从独立初始化委托给 DataFetcher |
| `data/managers/trade_calendar_manager.py` | 功能新增 | AkShare 过期自动更新日历 |

**评估**: `DataIngestionService` 大幅瘦身，从自主初始化 5 个数据源改为委托给 `DataFetcher`。这是解决 P2-1（DataFetcher/DataIngestionService 重复）的正确方向。TradeCalendar 自动过期更新解决了 2027 年假期失效问题（P3-3）。

### 2.4 其他核心（3 个源文件）

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `brain/regime/regime_detector.py` | **Bugfix** | 数据不足/熵空/换手率空时返回 UNKNOWN 而非 NORMAL |
| `risk/historical_risk.py` | **删除** | 死代码清理 |
| `scripts/wyckoff_multitf/regime_detector.py` | 修改 | 实验脚本同步 |

**评估**: RegimeDetector 的 fail-open 修复是 Phase 6 的核心输出。`historical_risk.py` 删除是合理的死代码清理。

### 2.5 测试（9 个文件）

| 文件 | 类型 | 测试内容 |
|------|------|----------|
| `test_result_store.py` | **新文件** | ResultStore 存/取/查询/比较/边缘测试 |
| `test_market_cache.py` | **新文件** | MarketCache 基本/TOCTOU/竞态/并发测试 |
| `test_backtest_compare.py` | **新文件** | BacktestResult.compare() 功能测试 |
| `test_trade_calendar_manager.py` | **新文件** | TradeCalendar 加载/保存/查询/边界测试 |
| `test_data_fetcher_get_price_source_router.py` | **新文件** | DataFetcher 集成测试 |
| `test_fsm.py` | 扩展 | FSM 额外测试 |
| `test_regime_detector.py` | 扩展 | RegimeDetector 边界测试 |
| `test_wyckoff_new_features.py` | **新文件** | Wyckoff PnF/phase/bayesian 集成测试 |
| `test_research_data_pack.py` | 修改 | 适配默认 use_research_data_pack=true |

**评估**: 6 个新测试文件覆盖了主要新功能。202 行新增测试代码对 9086 行总变更是合理的比例（2.2%）。

### 2.6 文档（10 个文件）

| 文件 | 类型 |
|------|------|
| `AGENTS.md` | 同步 Phase 6 完成状态 |
| `docs/index.md` | 日期更新 |
| `docs/analysis/00-06` | Stage 0-6 产物同步 |

**评估**: 文档同步是合规的（符合 AGENTS.md 的 "Sync docs with every change" 规则）。

---

## 3. 已 Stash 内容

```
stash@{0}: experimental: wyckoff scripts, cnn/rl classifiers, full-scan scripts, generated data
stash@{1}: WIP on master: docs: commit all 37 audit/analysis/repair documents
stash@{2}: WIP on master: fix: resolve AnalysisService brain/report engine init failures
```

stash@{1} 和 stash@{2} 是早前的 WIP（可清理或丢弃）。stash@{0} 包含：

- `cnn_classifier.py`、`rl_agent.py` — 实验性 ML 模型，未集成到生产路径
- `scripts/wyckoff_multitf/x2-x3*` — 多组 Wyckoff 实验脚本
- `scripts/pipeline_*_scan.py` — 全量扫描脚本（可移至仓库）
- `data/checkpoints/`、`data/fullscan/`、`data/pipeline_fullscan/` — 生成数据
- `results/` — 运行结果

---

## 4. 剩余未跟踪文件

```
docs/analysis/07_risk_research_platform.md
docs/analysis/PLATFORM_EVALUATION.md
docs/analysis/REMEDIATION_FINAL.md
docs/analysis/REMEDIATION_PLAN.md
docs/analysis/REMEDIATION_REVIEW.md
docs/analysis/phase5_fix_task_list.md
docs/analysis/wyckoff_overflow_fix_*.md
docs/pipeline_5round_report.md
docs/remediation/
```

均为分析产物/报告，非生产代码，保持未跟踪状态可接受。

---

## 5. 关键发现

### 🟢 正面
1. **工程纪律好** — 代码变化与 Phase 6 缺口整改高度一致
2. **测试先行** — 6 个新测试文件覆盖主要新功能
3. **逐步淘汰旧路径** — `use_research_data_pack=true` 默认 + DataIngestionService 委托
4. **文档同步** — AGENTS.md 和 docs/index.md 随代码一起更新

### 🟡 需关注
1. **Wyckoff engine.py 代码重复** — P&F 在 `analyze()` 和 `scan_signal()` 中重复实例化
2. **OBV 向量化在第 2 处未改** — `DailyPhaseClassifier.classify()` 仍使用 Python for-loop
3. **DataIngestionService 改为薄委托层** — 现在只是一个 pass-through，可考虑直接移除
4. **macro_service.py:214** — `datetime` 名字缺失，可能运行时崩溃

### 🔴 风险
1. 本次变更的核心源文件（Wyckoff、TOCTOU、ResultStore、BacktestResult）已通过测试但尚未在真实全量扫描中验证
2. 5 个预存测试失败的根因仍未排查
3. brain 层文件数 74→55（-19）的变化发生在更早的提交中，未解释
