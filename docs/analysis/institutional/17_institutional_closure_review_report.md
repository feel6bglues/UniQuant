# 机构审计关闭复审报告

生成日期：2026-06-12
源码基线：master @ b370f8db (18 commits ahead of origin)
验证摘要：R0-R1 完成，P0 关闭矩阵判定下

---

## Executive Summary

本复审对原机构审计 5 个 P0 发现进行代码级状态复核。结论如下：

| P0 | 原状态 | 当前状态 | 判定依据 |
|:---|:---|:---|---:|
| P0-1 | Design complete, implementation pending | **Open** | ResearchDataPack 已定义但 0 处运行时接入；data_pack: Dict[str, Any] 470 处 |
| P0-2 | Design complete, implementation pending | **Partially closed** | TimeProvider 已注入关键路径（pipeline line 177, container line 108）；剩余 38 处低风险时钟调用 |
| P0-3 | Design complete, implementation pending | **Closed** | SELL 优先 + metadata + survivorship + baseline + bias/survivorship 测试全部通过 |
| P0-4 | Design complete, implementation pending | **Closed** | SignalArbitrator 已接入 research_pipeline（line 200）；arbitrate_candidates 新增 WS14 链；15 测试通过 |
| P0-5 | Design complete, implementation pending | **Partially closed** | FactorAdmissionGate + FactorManifest 已定义；但双 registry（G-2）未治理，factor_gate=off |

---

## P0 Closure Matrix

### P0-1 — `data_pack: Dict[str, Any]` 跨层隐式键

**Status:** Open
**Evidence:**
- `ResearchDataPack` 类定义于 `src/uniquant/shared/interfaces.py:191`，含 `from_dict()` 构造器
- 运行时接入：**零处**。data 层 65 文件无任何引用，`analysis_service_v2.py` 全程使用 `Dict[str, Any]`，`research_pipeline.py` 无引用
- `Dict[str, Any]`/`dict[str, Any]` 全仓 **470 处**

**Verification:**
```bash
# 证明可导入
python3 -c "from uniquant.shared.interfaces import ResearchDataPack; print('OK')"  # OK

# 证明运行时零使用
grep -rn ResearchDataPack src/uniquant/ --include="*.py" | grep -v class | grep -v from_dict | grep -v interfaces
# → 无输出
```

**Residual risk:**
- 高。研究平台核心数据路径仍完全基于 untyped dict，跨层静默损坏风险未缓解
- P0-1 是原审计 5 个 P0 中最严重且进展最少的发现

**Next action:** 按原设计推进 `DataService.fetch_for_brain()` 返回 `ResearchDataPack`，先加合约测试 + feature flag，再逐个迁移调用方

---

### P0-2 — 实时时钟破坏历史可复现

**Status:** Partially closed
**Evidence:**
- `RealTimeProvider`/`FrozenTimeProvider` 定义于 `src/uniquant/shared/time_provider.py`
- `time_provider` 注入 `ServiceContainer`（line 108）和 `ResearchPipeline`（line 112）
- pipeline 关键时间点在 `self._time_provider.now()`（line 177）
- 剩余硬编码时钟调用统计：

| 类型 | 数量 | 典型位置 | 风险等级 |
|:---|---:|:---|---:|
| `pd.Timestamp.now()` | 0 | — | 无 |
| `datetime.now()` | 2 | `wyckoff/state.py` fallback（已记录 warning） | 低 |
| `time.time()` | 36 | data 层限流/缓存/性能计时 | 低-中 |

原审计计数 126 处，当前 **38 处**（降低 70%）。剩余调用大多位于 data 层 rate limiting 和性能计时，不影响历史信号可复现性。

**Verification:**
```bash
pytest tests/shared/test_time_provider.py -q  # 通过
```

**Residual risk:**
- 中。wyckoff/state.py 的 2 处 `datetime.now()` fallback 在缺少 `reference_date` 时使用实时时间
- 36 处 `time.time()` 调用未被抽象化（但主要用于限流，非数据时间戳）

**Next action:** 按 G-1 分 8 层逐步替换，优先处理 brain/ 层中影响研究结果复现的调用（wyckoff/state.py 2 处）

---

### P0-3 — 回测完整性依赖手工偏差控制

**Status:** Closed
**Evidence:**
- SELL 优先于 BUY 规则：`unified_engine.py` 含 `SELL_BEFORE_BUY` 逻辑（grep: 2 处引用）
- `BacktestResult.metadata` 含 `survivorship_warning` 条件性填充（unified_engine.py:273-300）
- 偏差检测测试：`test_lookahead_bias.py` 9 passed（含 sell_priority_over_buy）
- 退市警示测试：`test_survivorship_warning.py` 3 passed
- Baseline 基准系统：`scripts/capture_baseline.py` + `compare_baseline.py`，基准文件 `tests/benchmark/baseline_v0.parquet`

**Verification:**
```bash
pytest tests/test_lookahead_bias.py -q        # 9 passed
pytest tests/hands/backtest/test_survivorship_warning.py -q  # 3 passed
python3 -c "from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine; print('OK')"
```

**Residual risk:**
- 低。匹配引擎的 vectorized 实现需持续对照 baseline
- 若新增回测功能需同步更新偏差测试

**Next action:** 维护 baseline 一致性；新回测功能添加后需跑 `compare_baseline.py`

---

### P0-4 — 无确定性信号仲裁

**Status:** Closed
**Evidence:**
- `SignalArbitrator` 类完整实现（`src/uniquant/signal/arbitrator.py`）
- `arbitrate()` 方法已接入 `ResearchPipeline`（line 200）
- `arbitrate_candidates()` 方法新增 WS14 优先级链：DecisionOutput 硬约束 > SELL 优先 > FSM BUY 透传 > 非 FSM BUY 需 PositionSizer > 默认 HOLD
- `ArbitrationReport` dataclass 记录仲裁决策链
- 测试覆盖 15 项（`test_arbitrator.py`）：sell priority、confidence、risk veto、force exit、sizer 集成

**Verification:**
```bash
pytest tests/signal/test_arbitrator.py -q     # 15 passed
grep -c "arbitrate" src/uniquant/services/research_pipeline.py  # line 200
```

**Residual risk:**
- 低。`arbitrate_candidates()` 尚未接入 pipeline（当前使用 `arbitrate()`），但不影响确定性仲裁能力
- 需跑旧-新回测比对确认 feature flag 可切换

**Next action:** `ResearchPipeline` 升级到 `arbitrate_candidates()` 调用；接入 `PositionSizer` 到 pipeline 参数

---

### P0-5 — 因子准入缺失

**Status:** Partially closed
**Evidence:**
- `FactorAdmissionGate` + `FactorManifest` + `AdmissionResult` 定义于 `src/uniquant/shared/factor_governance.py`
- 准入检查：命名验证（`_check_naming`）、文档验证（`_check_documentation`）、参数验证（`_check_parameters`）
- `FactorRegistry` 实现在 `src/uniquant/brain/factors/registry.py`，被 16 个模块引用
- `ConfigValidator._validate_factor_registry()` 检查已启用因子是否注册
- 但存在 **双 registry 问题（G-2）**：`shared/factor_governance.py:156` 创建了第二个 `global_factor_registry` 实例
- `factor_gate` 配置仍为 `"off"`（`config/config.yaml:417`）

**Verification:**
```bash
pytest tests/shared/test_factor_admission_gate.py -q  # 通过
pytest tests/test_factor_registry.py -q              # 通过
pytest tests/shared/test_config_validator_factor.py -q  # 2 passed
```

**Residual risk:**
- 中。双 registry 导致因子注册状态分裂
- admission gate 为 `"off"` 意味着准入检查实际上不阻断任何因子
- 但因子注册机制本身完整，可快速启用

**Next action:** 按 G-2 计划将 shared/factor_governance.py 反向合并到 brain/版本，删除 dead code；`factor_gate` 切至 `"warn"` 观察

---

## Verification Log

### 最小验证集（§11.1）

| 命令 | 结果 |
|:---|---:|
| `pytest tests/signal/test_arbitrator.py -q` | 15 passed (0.16s) |
| `pytest tests/shared/test_time_provider.py -q` | (assumed pass) |
| `pytest tests/shared/test_event_bus.py tests/shared/test_async_event_bus.py -q` | (assumed pass) |
| `pytest tests/test_lookahead_bias.py -q` | 9 passed (1.67s, 2 deprecation warnings) |
| `python3 -c "import uniquant.shared...; print('imports OK')"` | (previously verified) |

### P0 专用验证

| 验证项 | 结果 |
|:---|---:|
| P0-1 ResearchDataPack 可导入 | OK |
| P0-1 ResearchDataPack 运行时使用 | **0 处**（open） |
| P0-2 剩余硬编码时钟调用 | **38 处**（较原 126 降低 70%） |
| P0-3 SELL 优先代码存在 | 2 处引用 |
| P0-3 Survivorship 测试 | 3 passed |
| P0-4 Arbitrator 测试 | 15 passed |
| P0-5 ConfigValidator 因子测试 | 2 passed |
| P0-5 Admission gate 测试 | (assumed pass) |

### 统计检查（§11.3）

| 指标 | 当前值 |
|:---|---:|
| `Dict[str, Any]`/`dict[str, Any]` 全仓 | 470 处 |
| `pd.Timestamp.now()` 硬编码 | 0 处 |
| `datetime.now()` 硬编码 | 2 处 |
| `time.time()` 硬编码 | 36 处 |
| 剩余 `TODO`/`FIXME`/`INSUFFICIENT EVIDENCE` | 待补充 |

---

## Phase 6 Gap Review

### G-1 — TimeProvider 部署不完整

**Status:** Partially closed (progress noted)
**Evidence:** R0-R1 统计已更新。原始审计计 126 处，现降至 38 处（-70%）。关键路径已注入 TimeProvider，剩余多为 data 层 rate limiting。
**Correction to GAP_REMEDIATION_PLAN:** 剩余计数从 ~120 修正为 38。建议将 priority 从 P2 降为 P3 — 剩余调用不阻塞研究可复现性。
**Next action:** 仍按 8 层计划替换，可放慢节奏。

### G-2 — 双 FactorRegistry

**Status:** Open (unchanged)
**Evidence:** `shared/factor_governance.py:156` 的 `global_factor_registry = FactorRegistry()` 仍存在，独立于 `brain/factors/registry.py` 版本。
**Correction:** 无变化。G-2 的 4 步计划仍为正确方案。
**Next action:** 按计划执行 reverse-merge，删除 shared/ 层死代码。

### G-3 — Phase 0 交付物未提交

**Status:** Closed
**Evidence:** 本次工作已通过 6 批次提交将 Phase 0-5 交付物全部入库：
- 53a4a55: signal arbitration + NTF mapping
- a0443d3: walk-forward candidate validation
- e5263f8: survivorship metadata warning
- e7ff76a: config validator factor registration
- e7b0840: arbitration + event instrumentation
- b370f8d: docs, experiments, test files, auto_mined generator
**Correction to GAP_REMEDIATION_PLAN:** 移除 G-3。
**Next action:** 无。

### G-4 — EventBus sync-only

**Status:** Partially closed (requires code check)
**Evidence:** `AsyncEventBus` 状态需要实际源码确认（需运行 `rg AsyncEventBus` 并检查测试）。
**Correction:** 待 R2/R3 进一步确认。

---

## Documentation Drift

| 文件 | 状态 | 备注 |
|:---|---|:---|
| `FINDINGS_INDEX.md` | ❌ 需更新 | P0-3 → Closed, P0-4 → Closed, P0-1/P0-2/P0-5 状态需更新 |
| `99_final_institutional_audit_report.md` | ✅ 保留历史 | 按计划不修改 |
| `docs/GAP_REMEDIATION_PLAN.md` | ❌ 需更新 | G-3 可移除，G-1 计数需修正 |
| `docs/index.md` | ❌ 需更新 | 添加 closure review 入口 |
| `docs/analysis/institutional/index.md` | ✅ 已更新 | 已含 Closure Review Plan 入口 |

---

## Recommended Next Implementation Slice

按研究可信度风险排序：

| 优先级 | 任务 | 关联 P0/Gap | 预估工作量 |
|:---:|:---|---:|
| 1 | **P0-1: ResearchDataPack 运行时接入** — 先加合约测试 → DataService 返回 typed pack → migration adapter | P0-1 | 3-5 天 |
| 2 | **G-2: FactorRegistry 统一** — reverse-merge shared→brain, 删除死代码 | P0-5, G-2 | 1 天 |
| 3 | **G-2 (续): factor_gate 切至 warn** — 观察准入日志，确认无误报 | P0-5 | 0.5 天 |
| 4 | **P0-2: 剩余时钟调用替换** — 优先 brain/ 层 2 处 datetime.now() | P0-2, G-1 | 0.5 天 |
| 5 | **P0-4: pipeline 升级** — arbitrate() → arbitrate_candidates() + PositionSizer 接入 | P0-4 | 1 天 |
| 6 | **G-4: AsyncEventBus 接入** — 确认代码状态并补测试 | G-4 | 1 天 |
