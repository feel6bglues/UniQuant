# 执行计划建议 — Execution Plan Recommendation

生成日期：2026-06-11
前置核实：`IMPLEMENTATION_PLAN_TASK_CARDS.md` × 21 个分析文件 × 实际代码

---

## 1. 核实结论

在执行前对所有可验证声明做了代码级交叉检查：

| 检查项 | 结果 |
|---|---|
| Task 0.1 `_get_day_signals()` 方法存在性 | ❌ 不存在，已修正为 `run()` Step 3 内联循环 |
| Task 0.2 `research_pipeline.py:133` 行号 | ✓ 精确匹配 |
| Task 0.3 `BacktestResult` metadata 字段 | ✓ `unified_engine.py` 缺少，`result.py` 已有 |
| `Dict[str, Any]` 源代码数量 | ✓ 430 处（匹配声称） |
| `pd.Timestamp.now()` 实际数量 | 42 处 + `datetime.now()` 84 处 = **126 处**（匹配总计） |
| `config/config.yaml` refactoring 段 | ✓ 尚不存在（待添加） |
| `MarketSignalContext` 接入状态 | ✓ 已定义但`AnalysisService._make_decision()` 仍传 raw dict |
| 所有计划新建文件 | ✓ 全部尚不存在 |

---

## 2. 建议执行顺序

### 总览

```
Week 1         Week 2-3        Week 4-5          Week 6-8           Week 9-10
┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌───────────┐
│ Phase 0  │  │ Phase 1.1  │  │ Phase 1.2    │  │ Phase 3       │  │ Phase 4+5 │
│ 止血     │  │ 基准集     │  │ 契约定义+配置 │  │ 引擎迁移      │  │ EventBus  │
│ 3 tasks  │  │ golden_100 │  │ TimeProvider │  │ 逐个替换      │  │ 可观测性  │
│          │  │ baseline   │  │ mypy+flags   │  │ 每改一个验证  │  │ Config    │
│          │  │            │  │              │  │               │  │ Health    │
└──────────┘  └────────────┘  └──────────────┘  └───────────────┘  └───────────┘
                                                     │                  │
                                                     └──── 并行 ────────┘
```

### 与任务卡的关键区别

| 维度 | 任务卡原计划 | 建议调整 | 理由 |
|---|---|---|---|
| Phase 0 Task 0.3 | 止血阶段做 | 合并到 Phase 1 | `result.py` 已存在 metadata；生存偏差依赖基准集数据 |
| Phase 2 vs Phase 3 | 并行 | **串行** | 二者都改 `research_pipeline.py` + `adapters.py`，一人开发冲突文件太多 |
| 基准集初始规模 | 100 只 | 先 20 只 → 再扩展 | 20 只 ≈ 2 分钟捕获完成，快速锁定 baseline |
| Wyckoff 优化 | Phase 3 | 推迟到 Phase 3 尾部 | 没有 baseline 保护时优化风险不可控 |

---

## 3. 逐周执行计划（一人开发者）

### 第 1 周 — Phase 0 止血 + 基准集启动

| Day | 任务 | 文件 | 验证 |
|---|---|---|---|
| 1 | **Task 0.1**: LPPL SELL 优先 | `unified_engine.py:248` Step 3 (+2行) | `pytest tests/test_lookahead_bias.py -xvs` |
| 2-3 | **Task 1.1.1**: 选定 20 只代表性股票 | `tests/benchmark/golden_20.txt` | 每只 ≥ 5 年 K 线 |
| 4-5 | **Task 1.1.2**: 基准捕获脚本 | `scripts/capture_baseline.py` | 20 只运行通过 |

### 第 2-3 周 — Phase 1.1 安全网 + 配置框架

| Day | 任务 | 文件 | 验证 |
|---|---|---|---|
| 6-7 | **Task 1.1.2 扩展**: 基准集扩展到 100 只 | `tests/benchmark/golden_100.txt` | `capture_baseline.py --verify-only` |
| 8-9 | **Task 1.1.3**: 基准比对脚本 | `scripts/compare_baseline.py` | 自比对 100% 一致 |
| 10 | **Task 0.3**: BacktestResult metadata | `unified_engine.py` BacktestResult (+1行) | 导入测试 |
| 11-12 | **Task 1.2.1**: TimeProvider | `shared/time_provider.py` | `pytest tests/shared/test_time_provider.py` |
| 13-14 | **Task 1.4.1**: pydantic-settings 配置 | `shared/config_models.py` + `config/config.yaml` | `pytest tests/shared/test_config_models.py` |

### 第 4-5 周 — Phase 1.2 契约定义 + 特性开关

| Day | 任务 | 文件 | 验证 |
|---|---|---|---|
| 15-16 | **Task 1.2.2-4**: ResearchDataPack / DecisionOutput / CandidateSignal | `shared/interfaces.py` | 3 个测试文件通过 |
| 17 | **Task 1.2.5**: FactorManifest | `shared/factor_governance.py` | `pytest tests/shared/test_factor_manifest.py` |
| 18 | **Task 1.2.6**: Event / Command 类型 | `shared/event_types.py` | `pytest tests/shared/test_event_types.py` |
| 19-20 | **Task 1.4.2**: ServiceContainer 接入配置 | `services/service_container.py` | 特性开关 = false 行为不变 |
| 21 | **Task 1.3.1-2**: mypy 渐进式 + CI | `pyproject.toml` + CI | `mypy src/uniquant/shared/interfaces.py` |

### 第 6-7 周 — Phase 2 信号仲裁 + 因子门禁

| Day | 任务 | 文件 | 验证 |
|---|---|---|---|
| 22-24 | **Task 2.1.1**: SignalArbitrator 核心 | `signal/arbitrator.py` | `pytest tests/signal/test_arbitrator.py` |
| 25-26 | **Task 2.1.2**: 仲裁器接入 Pipeline | `research_pipeline.py` | `pytest tests/integration/test_signal_pipeline.py` |
| 27-28 | **Task 2.1.3**: 仲裁影响评估报告 | — | 量化负责人签字 |
| 29-30 | **Sprint 2.2**: FactorAdmissionGate | `shared/factor_governance.py` | warn 模式仅记录日志 |
| 31 | **Sprint 2.3**: TimeProvider 接入 Pipeline | `services/service_container.py` + `analysis_service_v2.py` | 回归测试 |

### 第 8-11 周 — Phase 3 引擎逐个迁移

| Day | 任务 | 文件 | 每步验证 |
|---|---|---|---|
| 32-33 | **Task 3.1.1**: DataService typed 路径 | `data_service.py` | `test_data_service_typed.py` |
| 34 | **Task 3.2.1**: Regime 引擎迁移 | `brain/regime/regime_detector.py` | baseline 100% 一致 |
| 35 | **Task 3.2.2**: NTF 引擎迁移 | `brain/ntf/` | baseline 100% 一致 |
| 36 | **Task 3.2.3**: LPPL 引擎迁移 | `brain/lppl/engine.py` | baseline 100% 一致 |
| 37-38 | **Task 3.3.1**: CZSC 引擎迁移 | `brain/czsc/` | baseline 100% 一致 |
| 39 | **Task 3.3.2**: Alpha 引擎迁移 | `brain/factors/composer.py` | baseline 100% 一致 |
| 40-41 | **Task 3.3.3**: Wyckoff 引擎迁移 + 3x 优化 | `brain/wyckoff/engine.py` | baseline 一致 + perf |
| 42-43 | **Task 3.4.1**: DecisionBrain 输出 DecisionOutput | `brain/fsm/fsm.py` | `test_backtest_regression.py` |
| 44 | **Task 3.4.2**: MarketSignalContext 接入 | `analysis_service_v2.py` | 集成测试 |
| 45-46 | **Task 3.5.1-4**: 剩余引擎 + 旧路径清理 | 多个文件 | `Dict[str,Any]` < 50 |

### 第 8-11 周（并行） — Phase 4 + Phase 5

| Day | 任务 | 文件 | 验证 |
|---|---|---|---|
| 32-35 | **Task 4.1.1-2**: EventBus | `shared/event_bus.py` + `research_pipeline.py` | `test_event_bus.py` |
| 36-38 | **Task 4.2.1-2**: Metrics + perf_section | `shared/observability.py` | `test_observability.py` |
| 39-41 | **Task 5.1.1-2**: ConfigValidator + 环境变量 | `shared/config_validator.py` + `config_loader.py` | Fail Fast 测试 |
| 42-44 | **Task 5.2.1-2**: HealthService 拆分 | `services/health_service.py` | liveness/readiness/diagnostics |

---

## 4. PR 规划建议

### PR 1 — LPPL SELL 优先级修复（今天可合入）

```
分支: fix/lppl-sell-priority
文件: unified_engine.py (+2行), test_lookahead_bias.py (+1 case)
行数: ~15
风险: 低（单行逻辑 + 测试）
```

### PR 2 — 基准集 + 验证工具

```
分支: feat/regression-baseline
文件: golden_100.txt (新), capture_baseline.py (新), compare_baseline.py (新)
行数: ~200
风险: 低（新文件，不影响已有代码）
```

### PR 3 — 契约类型定义

```
分支: feat/typed-contracts
文件: interfaces.py (追加), time_provider.py (新), event_types.py (新),
      factor_governance.py (新), config_models.py (新)
行数: ~400
风险: 低（纯新增类型，无行为改动）
```

### PR 4 — 信号仲裁

```
分支: feat/signal-arbitration
文件: arbitrator.py (新), adapters.py (改), research_pipeline.py (改)
行数: ~200
风险: 中（特性开关保护）
```

### PR 5+ — 引擎逐个迁移

```
每个引擎一个独立 PR:
  refactor/engine-regime
  refactor/engine-lppl
  refactor/engine-czsc
  refactor/engine-wyckoff
  ...
每个 PR < 500 行，每改一个验证一次 baseline
```

---

## 5. 不要做的事情

1. **不要并行 Phase 2 和 Phase 3** — 两个人都改同一文件时合并冲突大于收益；一人开发更不要并行
2. **不要在 Phase 1.1 完成前改任何引擎** — 没有 baseline 保护，改了不知道是否改坏
3. **不要在止血阶段做 Task 0.3** — `result.py` 已有 metadata，该任务依赖基准集数据做生存偏差检测
4. **不要一次改全部 9 个引擎** — 每个引擎一个 PR，每改一个跑一次 `compare_baseline.py`
5. **不要在 Phase 3 中间启动 Wyckoff 优化** — 优化本身改变数值行为，必须先用 baseline 锁住旧行为

---

## 6. 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 基准集股票选少了覆盖不足 | 中 | 高 | 先 20 只快速启动，第 2 周扩展到 100 只 |
| 一人开发 Phase 3 拖延 | 高 | 中 | 每个引擎独立 PR + 验证，可随时暂停 |
| 仲裁逻辑改变回测结果 | 确定 | 中 | 仲裁影响评估报告 + 量化负责人签字 |
| 引擎迁移改坏逻辑 | 中 | 高 | 每个引擎验证 baseline + 特性开关回滚 |
| 第 8 周后疲劳导致质量下降 | 中 | 中 | Phase 4+5 与 Phase 3 并行，可灵活调度 |

---

## 7. 关闭条件

```bash
# 全部完成
pytest tests/ -q --cov=src/uniquant/     # 覆盖率 > 80%
python scripts/compare_baseline.py \      # 基线一致
  tests/benchmark/baseline_v0.parquet \
  tests/benchmark/baseline_v_final.parquet
rg "Dict\[str, Any\]" src/uniquant/      # < 50 处
rg "(pd\.Timestamp|datetime(\.datetime)?)\.now\(" src/uniquant/  # < 10 处
mypy src/uniquant/ --disallow-untyped-defs  # 新/改文件全部类型标注
```
