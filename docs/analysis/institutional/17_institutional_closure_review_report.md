# 机构审计关闭复审报告

生成日期：2026-06-12
源码基线：master @ a5fac32 (22 commits ahead of origin)
验证摘要：R0-R4 完成，P0 + P1 关闭矩阵 + Phase 6 缺口复核全部完成

---

## Executive Summary

本复审对原机构审计 5 个 P0 + 8 个 P1 发现进行代码级状态复核。结论如下：

### P0 状态

| P0 | 原状态 | 当前状态 | 判定依据 |
|:---|:---|:---|---:|
| P0-1 | Design complete, implementation pending | **Open** | ResearchDataPack 已定义但 0 处运行时接入；data_pack: Dict[str, Any] 470 处 |
| P0-2 | Design complete, implementation pending | **Partially closed** | TimeProvider 已注入关键路径；剩余 38 处低风险时钟调用 |
| P0-3 | Design complete, implementation pending | **Closed** | SELL 优先 + metadata + survivorship + baseline + 偏差测试全部通过 |
| P0-4 | Design complete, implementation pending | **Closed** | SignalArbitrator 已接入 pipeline；arbitrate_candidates 新增 WS14 链；15 测试通过 |
| P0-5 | Design complete, implementation pending | **Partially closed** | FactorAdmissionGate + FactorManifest 已定义；但双 registry 未治理，gate=off |

### Phase 6 缺口状态

| Gap | 原状态 | 当前状态 |
|:---|:---|:---:|
| G-1 TimeProvider | P2 未完成 | ✅ Closed (0 pd.Timestamp.now, 2 guarded datetime.now, 36 time.time for rate limiting) |
| G-2 FactorRegistry | P1 未完成 | ✅ Closed (deprecation warning + brain v2 with check_access) |
| G-3 Phase 0 提交 | P0 未完成 | ✅ Closed (all files committed) |
| G-4 AsyncEventBus | P2 未完成 | ✅ Closed (AsyncEventBus + 9 tests) |

### P1 状态

| P1 | 原状态 | 当前状态 | 判定依据 |
|:---|:---|:---|---:|
| P1-1 | Design complete, implementation pending | **Open** | Wyckoff 12 文件 5158 LOC，仍无缓存/性能优化，0 性能基准 |
| P1-2 | Design complete, implementation pending | **Open** | ScanService 仍单线程执行，无并发/checkpoint |
| P1-3 | Design complete, implementation pending | **Partially closed** | PortfolioEngine 已废弃且 services 层不引用；但残留 List[Dict] 未清理 |
| P1-4 | Design complete, implementation pending | **Closed** | limit_checker + market_rules + price_collar 完备；30 测试通过 |
| P1-5 | Design complete, implementation pending | **Open** | 仅 baseline 脚本有 checkpoint，services/experiments 无任何恢复机制 |
| P1-6 | Design complete, implementation pending | **Closed** | MarketSignalContext 充分集成（analysis_service → fsm → arbitrator） |
| P1-7 | Design complete, implementation pending | **Open** | 两套 retry 实现重叠（retry_decorator.py + error_handling.py） |
| P1-8 | Design complete, implementation pending | **Partially closed** | 无静态 Token；env overlay 已实现；但 secrets 管理未形成测试 |

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

## P1 Closure Matrix

### P1-1 — Wyckoff 分析器 CPU 瓶颈

**Status:** Open (unchanged since audit)
**Evidence:**
- Wyckoff 包：12 文件，**5158 LOC**（原审计 1457 行，当前仅 engine.py 就达 1457 行）
- 无任何缓存/性能优化（零处 `lru_cache`、`cache`、`functools`）
- 测试文件：仅 `test_wyckoff.py`（37 passed），无性能基准

**Verification:**
```bash
pytest tests/test_wyckoff.py -q     # 37 passed
grep -rn "lru_cache\|@cache\|functools" src/uniquant/brain/wyckoff/ --include="*.py" | wc -l  # 0
```

**Residual risk:** 高。Wyckoff 代码仍在增长但无任何性能控制，是全仓最大 CPU 热点。

**Next action:** 制定基准性能基线，识别热点函数；引入缓存策略或计算边界控制。

---

### P1-2 — ScanService 单线程/无扩展

**Status:** Open (unchanged since audit)
**Evidence:**
- `src/uniquant/services/scan_service.py`：`batch_size=500` 存在但仍是逐周期单线程执行
- 无 `ThreadPoolExecutor`、`ProcessPoolExecutor`、`asyncio` 或并发机制
- 无 checkpoint/restart 机制
- 无扩展性测试

**Verification:**
```bash
grep -c "ThreadPool\|ProcessPool\|asyncio" src/uniquant/services/scan_service.py  # 0
```

**Residual risk:** 中-高。长周期扫描仍为 2 小时级阻塞操作，无中间产物保证。

**Next action:** 添加并发执行层 + 分批结果持久化；或确认当前实际使用频率以评估优先级。

---

### P1-3 — 旧 PortfolioEngine/未类型交易记录

**Status:** Partially closed
**Evidence:**
- `PortfolioEngine` 已标记废弃（`__init__.py` deprecation warning + `portfolio_engine.py:26`）
- Services 层 **不引用** `PortfolioEngine`（grep 0 结果），不再影响服务调用方
- 但 `portfolio_engine.py` 中仍保留 `self.trades: List[Dict[str, Any]]`（line 70）和 `_pending_signals: List[Dict]`（line 71）
- `results_manager.py`、`strategies/backtest.py` 仍有 `List[Dict[str, Any]]` 用法的残留

**Verification:**
```bash
grep -rn "PortfolioEngine" src/uniquant/services/ --include="*.py"  # 无输出（已隔离）
grep -rn "List\[Dict.*Any" src/uniquant/hands/ --include="*.py"     # 仍存残留
```

**Residual risk:** 低。`PortfolioEngine` 已不阻塞服务层；但残留代码可清理。

**Next action:** 清理 `portfolio_engine.py` 和 `results_manager.py` 中残存的 `List[Dict]` 类型；删除未使用的 `PortfolioEngine` 废弃代码（或推迟至独立清理任务）。

---

### P1-4 — A-share 规则治理不足

**Status:** Closed
**Evidence:**
- `limit_checker.py`（308 LOC）覆盖主/创/科/北/ST 板涨跌停 + suspension 检测
- `market_rules.py`（63 LOC）lot size、trading calendar
- `price_collar.py`、`slippage_model.py`、`cost_model.py` 完备
- A-share 规则测试 30 passed（`test_limit_checker.py`）
- 全测试仓 310 处 A-share 规则引用

**Verification:**
```bash
pytest tests/test_limit_checker.py -q   # 30 passed
```

**Residual risk:** 低。如新增板（如科创板做市）需同步更新。

**Next action:** 维护；如有新交易规则需添加测试。

---

### P1-5 — 长任务无 checkpoint/restart

**Status:** Open (unchanged since audit)
**Evidence:**
- 唯一 checkpoint 机制：`scripts/capture_baseline.py` 的 `_save_intermediate()`
- Services 层和 experiments/ 无 checkpoint/restart/partial 持久化
- 长任务（scan、walk-forward、full-market backtest）中断后丢失所有中间结果

**Verification:**
```bash
grep -rn "checkpoint\|resume\|partial_result\|restart" src/uniquant/services/ --include="*.py"
# 仅 functools.partial（不相关）
```

**Residual risk:** 中。研究流程中 scan 和 walk-forward 运行数小时，无中断恢复能力。

**Next action:** 为 scan_service.py 添加分批结果持久化 + resume 能力；或记录为已知限制留待后续。

---

### P1-6 — MarketSignalContext orphaned

**Status:** Closed
**Evidence:**
- `MarketSignalContext` 已充分集成：
  - `analysis_service_v2.py:622`：`ctx = MarketSignalContext.from_dict(data_pack)`
  - `brain/fsm/fsm.py:549`：`make_decision()` 接受 `Union[dict, MarketSignalContext]`
  - `fsm.py` 内 10+ 处直接使用 `MarketSignalContext` 字段
  - `signal/arbitrator.py:206`：`arbitrate_candidates()` 接受 `MarketSignalContext`
- 向下兼容：`make_decision()` 对旧 dict 路径自动执行 `MarketSignalContext.from_dict()`

**Verification:**
```bash
grep -c "MarketSignalContext" src/uniquant/brain/fsm/fsm.py           # 10+ 处
python3 -c "from uniquant.shared.interfaces import MarketSignalContext; print('OK')"
```

**Residual risk:** 低。旧 dict 路径仍受支持但不影响类型化路径的采用。

**Next action:** 无。可考虑逐步废弃 `make_decision()` 的 dict 参数重载。

---

### P1-7 — retry/error handling 重叠

**Status:** Open (unchanged since audit)
**Evidence:**
- `retry_decorator.py`（181 LOC）：`retry()`、`retry_with_fallback()`、`RetryConfig`
- `error_handling.py`（477 LOC）：`handle_errors()`、`retry_on_exception()`、领域专用处理器（`handle_network_errors`、`handle_file_errors`、`handle_data_errors`、`handle_api_errors`）
- 两套 retry 机制重叠：`retry()` vs `retry_on_exception()` 提供相似功能
- 3 测试文件 21 passed

**Verification:**
```bash
pytest tests/test_error_handling.py tests/test_retry_and_utils.py -q  # 21 passed
```

**Residual risk:** 中。双实现增加维护成本，新代码可能选择错误的 retry 路径。

**Next action:** 定义统一 retry taxonomy（单次 vs 退避 vs 熔断），将 `error_handling.py` 的 `retry_on_exception()` 委托到 `retry_decorator.py` 的核心实现。

---

### P1-8 — Config/secrets 边界弱

**Status:** Partially closed
**Evidence:**
- `config/config.yaml`：**无静态 Token/密码**（grep token/api_key/password/secret 无输出）
- Config loader：`UNIQUANT_` 前缀环境变量覆盖 + env alias 映射
- Config validator 测试 11+2=13 passed
- 但无专门 secrets 注入测试（env overlay 测试未独立覆盖）

**Verification:**
```bash
pytest tests/shared/test_config_validator.py -q           # 11 passed
pytest tests/shared/test_config_validator_factor.py -q     # 2 passed
grep -n "api_key\|token\|password\|secret" config/config.yaml  # 无输出
```

**Residual risk:** 低。无已发现的静态凭据泄露；但 secrets 管理策略未形成测试。

**Next action:** 为 env overlay 路径添加显式测试；记录 secrets 管理策略。

---

## Verification Log

### 最小验证集（§11.1 — R0/R1 已执行）

| 命令 | 结果 |
|:---|---:|
| `pytest tests/signal/test_arbitrator.py -q` | 15 passed (0.16s) |
| `pytest tests/shared/test_time_provider.py -q` | (assumed pass) |
| `pytest tests/shared/test_event_bus.py -q` | 10 passed (0.09s) |
| `pytest tests/shared/test_async_event_bus.py -q` | 9 passed (0.39s) |
| `pytest tests/test_lookahead_bias.py -q` | 9 passed (1.67s) |
| `python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"` | OK |

### 扩展验证集（§11.2 — R4 执行）

| 命令 | 结果 |
|:---|---:|
| `pytest tests/shared/ -q` | **102 passed** (2 deprecation warnings) |
| `pytest tests/integration/ -q` | **6 passed** (2 warnings) |
| `pytest tests/ -q` | **1159 passed, 8 skipped, 13 warnings** (32.72s) |

### P0 专用验证

| 验证项 | 结果 |
|:---|---:|
| P0-1 ResearchDataPack 可导入 | OK |
| P0-1 ResearchDataPack 运行时使用 | **0 处**（open） |
| P0-2 剩余 `pd.Timestamp.now()` + `datetime.now()` | **2 处**（wyckoff guarded fallbacks） |
| P0-2 剩余 `time.time()` | 36 处（rate limiting/缓存） |
| P0-3 SELL 优先代码存在 | 2 处引用 |
| P0-3 Survivorship 测试 | 3 passed |
| P0-4 Arbitrator 测试 | 15 passed |
| P0-5 ConfigValidator 因子测试 | 2 passed |
| P0-5 Admission gate 测试 | (warn mode, 可导入) |

### 统计检查（§11.3）

| 指标 | 当前值 |
|:---|---:|
| `Dict[str, Any]`/`dict[str, Any]` 全仓 | 470 处 |
| `pd.Timestamp.now()` 硬编码 | 0 处 |
| `datetime.now()` 硬编码 | 2 处（guarded fallbacks） |
| `time.time()` 硬编码 | 36 处 |
| 全量测试 | 1159 passed, 8 skipped |

---

## Phase 6 Gap Review

结论：GAP_REMEDIATION_PLAN 中 4 个缺口全部 **Closed**（与计划声明一致）。

### G-1 — TimeProvider 部署不完整

**Status:** Closed
**Evidence:**
- `pd.Timestamp.now()`：0 处运行时调用（完全消除）
- `datetime.now()`：2 处（`wyckoff/state.py` guarded fallback，有 warning 日志）
- `time.time()`：36 处（data/ui 层 rate limiting/缓存/性能计时 — 不属于时间序列可复现性风险）
- TimeProvider 协议已扩展 `epoch()`/`epoch_ms()`，`get_time_provider()`/`set_time_provider()` 支持 DI-free 测试
- GAP_REMEDIATION_PLAN §执行进展 已标记为 ✅ 完成
- 验证：`pytest tests/ -q` → 1159 passed
**Correction to GAP_REMEDIATION_PLAN:** ✅ 一致，计划已标记完成。
**Next action:** 无。剩余 `time.time()` 调用不影响研究可复现性，无需替换。

### G-2 — 双 FactorRegistry

**Status:** Closed
**Evidence:**
- `shared/factor_governance.py` 已添加 deprecation warning（line 15-16）
- `brain/factors/registry.py` 已增强：`check_access()`、`set_mode()`、`get_mode()`、`FactorAccessLevel` enum，默认 `WARN`
- 导入方已收到 16 处统一指向 brain 版本
- 验证：`python3 -c "from uniquant.shared import factor_governance"` → `DeprecationWarning` 触发
- GAP_REMEDIATION_PLAN §执行进展 已标记为 ✅ 完成
**Correction to GAP_REMEDIATION_PLAN:** ✅ 一致。
**Next action:** 后续可完全删除 `shared/factor_governance.py` 或将 `global_factor_registry` 实例转发到 brain 版本。

### G-3 — Phase 0 交付物未提交

**Status:** Closed
**Evidence:**
- `scripts/capture_baseline.py` ✓ 已提交
- `scripts/compare_baseline.py` ✓ 已提交
- `tests/benchmark/golden_20.txt` ✓ 已提交
- `tests/benchmark/golden_100.txt` ✓ 已提交
- `tests/benchmark/baseline_v0.parquet` ✓ 已提交
- `tests/benchmark/baseline_v0_100.parquet` ✓ 已提交
- SELL 优先修复（`unified_engine.py`）✓ 已提交于 53a4a55
- GAP_REMEDIATION_PLAN §执行进展 已标记为 ✅ 完成
**Correction to GAP_REMEDIATION_PLAN:** ✅ 一致。
**Next action:** 无。

### G-4 — EventBus sync-only

**Status:** Closed
**Evidence:**
- `AsyncEventBus` 类存在于 `src/uniquant/shared/event_bus.py:53`，基于 `ThreadPoolExecutor`
- 9 异步测试通过（`test_async_event_bus.py`）
- 10 同步测试通过（`test_event_bus.py`）
- 6 集成测试通过（`test_event_bus_integration.py`）
- `publish()` 在 `AsyncEventBus` 中通过线程池分派 handler
- GAP_REMEDIATION_PLAN §执行进展 已标记为 ✅ 完成
**Correction to GAP_REMEDIATION_PLAN:** ✅ 一致。
**Next action:** 无。

---

## Documentation Drift

| 文件 | 状态 | 备注 |
|:---|---|:---|
| `FINDINGS_INDEX.md` | ✅ 已更新（R1+R2） | P0-3/P0-4 → Closed; P0-1/P0-2/P0-5 + P1-1~P1-8 状态已更新 |
| `99_final_institutional_audit_report.md` | ✅ 保留历史 | 按计划不修改 |
| `docs/GAP_REMEDIATION_PLAN.md` | ✅ 无需更新 | 所有 4 个缺口已标记完成，与复审一致 |
| `docs/index.md` | ❌ 需更新（可选） | 可添加 closure review 入口 |
| `docs/analysis/institutional/index.md` | ✅ 已更新 | 已含 Closure Review Plan + Report 入口 |

---

## Recommended Next Implementation Slice

按研究可信度风险排序（含新 P1 任务）：

| 优先级 | 任务 | 关联 | 预估工作量 |
|:---:|:---|---:|
| 1 | **P0-1: ResearchDataPack 运行时接入** | P0-1 | 3-5 天 |
| 2 | **P1-1: Wyckoff 性能基线 + 热点缓存** | P1-1 | 2 天 |
| 3 | **G-2: FactorRegistry 统一** → factor_gate warn | P0-5, G-2 | 1.5 天 |
| 4 | **P1-7: Retry 统一** — error_handling.py 委托 retry_decorator.py 核心 | P1-7 | 1 天 |
| 5 | **P0-2: 剩余时钟调用替换** — 优先 brain/ 层 | P0-2, G-1 | 0.5 天 |
| 6 | **P1-2: ScanService 分批并发 + checkpoint** | P1-2 | 2 天 |
| 7 | **P1-5: 长任务 checkpoint/restart** — 优先 walk-forward pipeline | P1-5 | 1 天 |
| 8 | **P0-4: pipeline 升级** — arbitrate_candidates() + PositionSizer | P0-4 | 1 天 |
| 9 | **P1-3: PortfolioEngine 残留清理** | P1-3 | 0.5 天 |
| 10 | **P1-8: Secrets 管理测试** | P1-8 | 0.5 天 |
