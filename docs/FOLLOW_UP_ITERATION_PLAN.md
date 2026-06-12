# 后续深入功能迭代方案 — 修订版

> **基线**: Correction Plan (Phase A-E) 已执行完毕，1139 passed, 8 skipped
> **代码核实**: 2026-06-12，基于 `src/` 实际代码
> **参考**: `FOLLOW_UP_ITERATION_PLAN.md` v1 + 代码核实报告

---

## 核实修正摘要

| 原始方案的问题 | 修正后处理 |
|:---|---|
| Phase 6 写了"新建 MetricsRecorder / ConfigValidator / Health 拆分" | 这些已存在 (`observability.py:42`, `config_validator.py:15`, `health_service.py:59`)，改为"补齐缺口 + 验收" |
| 提出新增 `ErrorEvent` | `ErrorOccurred` 已存在 (`event_types.py:70`)，删除该 proposal |
| FactorAdmissionGate 落点在 deprecated `shared/factor_governance.py:15` | 移入 `brain/factors/registry.py` 或新增 brain-side admission 模块 |
| FactorGate 示例代码调用 `compute_ic_ir(..., factor_func=...)` 不可运行 | `compute_ic_ir` (`analyzer.py:244`) 无 `factor_func` 参数，需先修 walk_forward 集成错位 |
| Dict[str,Any] 写"~100+" | 实际 **468 处** (`rg "Dict\\[str, Any\\]" src/uniquant/`)，目标 <50 不变但工作量上调 |
| NTF 写"SUPPORT→BUY, RESISTANCE→SELL" | 更稳健: SUPPORT 作为 bullish context 不自动 BUY，RESISTANCE 阈值足够才产生 SELL/HOLD |
| Phase 7 死代码清理低估测试依赖 | 保留，但每个项目需确认零测试 import |

---

## Phase 2 — NTF 语义修复 (P0, 1 天)

**核实发现**: `adapters.py:300-304` 比较 `raw_output.get("ntf_side")` 与字符串 `"LONG"`/`"SHORT"`，但 NTF 引擎 (`brain/ntf/ntf_engine.py:85-88`) 实际输出 `"SUPPORT"`/`"RESISTANCE"`。比对永远不成立 → **NTFAdapter.adapt() 对所有真实引擎输出返回 None，NTF 信号被静默丢弃**。这是 P0 级信号丢失 bug。

### 修复方案

**设计依据** (WS6 §4.1):
- SUPPORT → bullish context，不直接自动 BUY
- RESISTANCE → 强度 `>= 0.6` 产生 SELL 候选，否则 HOLD

**改动** (`src/uniquant/signal/adapters.py:300-304`):

```python
# 旧 (bug): side == "LONG" → BUY; side == "SHORT" → SELL
# 新: WS6 语义感知
side = raw_output.get("ntf_side", "NONE")
intensity = float(raw_output.get("ntf_intensity", 0.0))

if side == "SUPPORT":
    # bullish context: 不自动 BUY，infra 层不做方向交易决策
    action = "HOLD"
    confidence = intensity * 0.5
elif side == "RESISTANCE" and intensity >= 0.6:
    action = "SELL"
    confidence = min(intensity, 0.9)
else:
    return None  # NONE / low-intensity RESISTANCE / unknown side
```

`NtfSide` 枚举 (`interfaces.py:18`) 当前值为 `SUPPORT`/`RESISTANCE`，与引擎输出一致，**不需要更改枚举值**。

**测试**: `tests/signal/test_adapters.py` 追加:
- `test_ntf_support_returns_hold` — SUPPORT + 高 intensity → HOLD (不自动 BUY)
- `test_ntf_resistance_high_intensity_sells` — RESISTANCE + 0.8 → SELL
- `test_ntf_resistance_low_intensity_skips` — RESISTANCE + 0.3 → None (跳过)
- `test_ntf_none_returns_none` — NONE → None

**验证**: `pytest tests/signal/test_adapters.py -xvs`

---

## Phase 2.5 — Walk-forward factor_func 集成修复 (P0, 1 天)

### 2.5.1 修复 `compute_ic_ir` 缺少 `factor_func` 参数

**当前 bug**: `walk_forward_pipeline.py:134-143` 调用 `self.analyzer.compute_ic_ir(..., factor_func=factor_func)`，但 `analyzer.py:244-254` 的 `compute_ic_ir()` 签名中没有 `factor_func` 参数。如果 `factor_func` 非 None，当前调用会 TypeError。

**修复路径**: 两种方案择一：

**方案 A** (推荐): 在 `compute_ic_ir` 内执行 factor_func 展开后再传 factor_cols
```python
# analyzer.py:244
def compute_ic_ir(
    self, df, factor_cols, holding_periods=None,
    date_col="date", code_col="code", price_col="close",
    mode=AnalysisMode.BACKTEST, half_life=None,
    factor_func: Optional[Callable] = None,  # 追加
):
    if factor_func is not None:
        df = df.copy()
        df[factor_cols] = factor_func(df)
    ...
```

**方案 B**: 在 walk_forward_pipeline 中先调用 factor_func 展开列，再传纯列名

**测试**: 用已知因子 `alpha_001` 构造 fixture，验证 `walk_forward_pipeline.run(factor_func=...)` 不抛 TypeError

**验证**: `pytest tests/brain/factors/test_walk_forward_pipeline.py -xvs`

---

## Phase 3 — SignalArbitrator.arbitrate_candidates() (P0, 3 天)

### 3.1 CandidateSignal[] 仲裁重载 (WS6-001/002)

**当前状态**: `arbitrator.py:71` 只接受 `List[TradingSignal]`，无 DecisionOutput 感知仲裁。

**改动** (`src/uniquant/signal/arbitrator.py`):

```python
def arbitrate_candidates(
    self,
    candidates: List[CandidateSignal],
    decision_output: Optional[DecisionOutput] = None,
    context: Optional[MarketSignalContext] = None,
    sizer: Optional[PositionSizerProtocol] = None,
) -> Tuple[List[TradingSignal], ArbitrationReport]:
```

**仲裁规则优先级** (WS14 §2.3, 基于 WS6-002):

1. `decision_output.final_decision` 为 `FORCE_WAIT` / `CIRCUIT_BREAK` → 返回 HOLD，拒单理由 `"risk_veto"`
2. `decision_output.final_decision` 为 `FORCE_EXIT` → 返回 SELL，理由 `"force_exit"`
3. `decision_output.action == "BUY"` 且 `decision_output.shares > 0` → 返回权威 BUY
4. 非 FSM 来源的 BUY 候选 → 需要 PositionSizer 计算仓位，未提供 sizer 则拒单
5. LPPL SELL（risk_level==Danger）→ 不可被同日 BUY 覆盖（已在 A.1 实现，此处再加一道仲裁层保底）
6. 默认 HOLD

**类** (`arbitrator.py`):

```python
@dataclass
class ArbitrationReport:
    symbol: str
    date: str
    candidates_count: int
    final_action: str = "HOLD"
    final_reason: str = ""
    final_confidence: float = 0.0
    veto_chain: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)
```

### 3.2 Wiring + 特性开关

**文件**: `src/uniquant/services/research_pipeline.py`
**改动**: `_collect_and_arbitrate_signals()` 在 `signal_arbitration: true` 时走仲裁路径

### 3.3 测试矩阵 (`tests/signal/test_arbitrator.py`)

| 用例 | 输入 | 期望 |
|:---|---|:---|
| `test_arbitrate_candidates_empty` | `[]` | `([], report.passed=True)` |
| `test_force_wait_veto` | FORCE_WAIT + CZSC BUY | HOLD, `veto_chain=["risk_veto"]` |
| `test_force_exit` | FORCE_EXIT + Wyckoff BUY | SELL, `reason="force_exit"` |
| `test_decision_buy_authoritative` | DecisionOutput BUY/shares=200 | BUY/shares=200 |
| `test_non_fsm_needs_sizer` | Wyckoff BUY, sizer=None | HOLD |
| `test_non_fsm_sizer_approves` | Wyckoff BUY, sizer→100 | BUY/100 |
| `test_lppl_sell_not_overridden` | LPPL SELL + CZSC BUY | SELL |
| `test_report_veto_chain` | 3 个候选 2 个拒绝 | report 含完整拒绝列表 |

---

## Phase 4 — SurvivorshipWarning (P1, 1 天)

### 4.1 BacktestResult.metadata survivorship 填充

**当前状态**: `unified_engine.py:274-287` 已填充 symbol/engine/start/end/signal_count，但无 survivorship 字段。

**前置条件**: 需确认退市数据来源。当前 `stock_metadata_manager.py` 存储股票基本信息但不确定是否有 `delist_date`。

**有数据来源时**：

```python
# unified_engine.py run() 返回前
delist_date = self._get_delist_date(symbol)
survivorship_warning = ""
if delist_date is not None:
    last_bar_date = pd.to_datetime(df["date"].iloc[-1]).date()
    if delist_date <= last_bar_date:
        survivorship_warning = (
            f"Symbol delisted {delist_date.isoformat()}; "
            f"backtest extends to {last_bar_date.isoformat()}"
        )
metadata = {
    "symbol": symbol, "engine": "unified",
    "start_date": ..., "end_date": ..., "signal_count": len(signals),
}
if survivorship_warning:
    metadata["survivorship_warning"] = survivorship_warning

return BacktestResult(..., metadata=metadata)
```

**无数据来源时**: 以上静默跳过，metadata 不包含 survivorship_warning 字段。

**测试**: `tests/hands/backtest/test_survivorship_warning.py`

---

## Phase 5 — FactorAdmissionGate brain-side 重构 (P1, 4 天)

### 5.1 迁出 deprecated shim

**当前问题**: `shared/factor_governance.py:15` 已被标记 `DeprecationWarning`。Phase B 实现的前 3 项检查 (naming/documentation/parameters) 仍在 deprecated 模块中。

**目标**: 将 `FactorAdmissionGate` 移入 `brain/factors/admission_gate.py` (新文件)

```python
# src/uniquant/brain/factors/admission_gate.py
class FactorAdmissionGate:
    def __init__(self, registry: FactorRegistry, mode: str = "warn"):
        self._registry = registry
        self._mode = mode
```

### 5.2 修复 walk-forward 集成错位

**当前 bug**: `walk_forward_pipeline.py:134-143` 调用了 `compute_ic_ir(..., factor_func=...)` 但 `analyzer.py:244` 签名不含 `factor_func`。

**修复**: 见 Phase 2.5 方案 A — 在 `compute_ic_ir()` 追加 `factor_func: Optional[Callable] = None` 参数。

### 5.3 扩展 admission 检查 (WS7-004 到 WS7-010)

在 brain-side 模块中扩展 3 项核心检查，复用现有 brain 组件：

| # | 检查 | 方法 | 复用组件 |
|:---|:---|---|:---|
| 4 | **IC/IR** | `_check_ic_ir(manifest, df, factor_cols)` | `FactorAnalyzer.compute_rank_ic()` (analyzer.py:183) |
| 5 | **OOS IC** | `_check_oos(manifest, df, factor_cols)` | `WalkForwardFactorPipeline` (walk_forward_pipeline.py:45) |
| 6 | **PBO** | `_check_pbo(manifest, df, factor_cols)` | auto_mined Reaper Rule: PBO < 0.2 |

### 5.4 不推后 7 项 (Safety/Redundancy/Tradability/Cost)

Reliability/Redundancy/Tradability/Cost 等非核心检查留到二期，因：
- 需要额外的因子依赖 (Safety)、跨因子数据 (Redundancy)、成本模型 (Cost)
- 不影响因子 IC/IR 核心评价

### 5.5 测试 (`tests/brain/factors/test_admission_gate.py`)

新增：
- `test_admission_ic_ir_above_threshold` / `test_admission_ic_ir_below_threshold`
- `test_admission_oos_passes` / `test_admission_oos_fails`
- `test_admission_pbo_below_threshold` / `test_admission_pbo_above_threshold`
- `test_warn_mode_does_not_block` / `test_block_mode_rejects`

---

## Phase 6 — 补齐现有 Observability/Config/Health 缺口 (P1, 2 天)

### 6.1 验收现有组件

**已存在**（不走新建路径）：

| 组件 | 文件:行 | 当前能力 | 有待补充 |
|:---|---|:---|:---|
| `InMemoryMetricsRecorder` | `observability.py:42` | counter/histogram/gauge/snapshot | perf_section 埋点覆盖率 (production 模式下行为) |
| `ConfigValidator` | `config_validator.py:15` | 4 项校验 (sections/paths/classes/refactoring) | factor registry config-vs-code 一致性检查 |
| `HealthService` | `health_service.py:59` | 三层检查 (liveness/readiness/diagnostics) | 缓存命中率报告、数据新鲜度 |

### 6.2 perf_section 埋点补齐 (对照 IMPLEMENTATION_PLAN_TASK_CARDS §Task 4.2.2)

| 埋点位置 | 当前状态 | 改动 |
|:---|---|:---|
| `analysis_service_v2.py` 6 引擎入口/出口 | 已有部分 | 验证每个引擎都有 `with perf_section()` |
| `adapters.py` 信号收集 | 缺失 | 追加 `perf_section("signal_collection")` |
| `research_pipeline.py` 全流程 | 缺失 | 追加 `perf_section("pipeline_total")` |

### 6.3 ConfigValidator factor 一致性检查 (WS7-002)

```python
# config_validator.py 追加
def _validate_factor_config(self) -> List[str]:
    errors = []
    registry = FactorRegistry()
    enabled_factors = config.get("factors", {}).get("enabled", [])
    registered = registry.supported_factors()
    for f in enabled_factors:
        if f not in registered:
            errors.append(f"factor '{f}' enabled in config but not in registry")
    return errors
```

### 6.4 ErrorOccurred 事件验证 (不是新增)

`event_types.py:70` 已有 `ErrorOccurred`。确认：
- `analysis_service_v2.py` 异常路径是否发射 `ErrorOccurred`
- `research_pipeline.py` run() 异常时是否发射

缺失则加发射点，不新增同义事件。

---

## Phase 7 — 死代码清理 + Dict[str,Any] 削减 (P2, 4 天)

### 7.1 Dict[str, Any] 削减

**当前基线**: 468 处 (`rg "Dict\\[str, Any\\]" src/uniquant/ | wc -l`)

**目标**: < 50 处

**批次削减计划**:

| 批次 | 目标层 | 预计减少 | 策略 | 风险 |
|:---|---:|---:|:---|:---:|
| 1 | `brain/` 引擎返回 | ~30 | RegimeOutput/LPPLOutput 化 | 低 — typed contracts 已定义 |
| 2 | `services/` 内部字典 | ~25 | ResearchDataPack/DecisionOutput 化 | 中 — 需改 adapter 调用链 |
| 3 | `data/` 内部 | ~15 | Typed data 容器 | 中 — data 层改动大 |
| 4 | `hands/` 内部 | ~20 | BacktestResult typed 字段 | 低 — 已有 dataclass |
| 5 | `ui/` 组件 | ~30 | 组件 props 接口化 | 高 — UI 层改动验证困难 |

**验证**: 每批次后 `rg "Dict\\[str, Any\\]" src/uniquant/ | wc -l`，确认递减。

### 7.2 死代码清理前需确认零测试依赖

| 项目 | 文件 | 行数 | 需要确认事项 |
|:---|---:|---:|:---|
| 旧 `engine.py` | `hands/backtest/engine.py` | ~400 | `test_*` 是否 import 它 |
| 旧 `backtest.py` | `hands/strategies/backtest.py` | ~530 | SurvivorshipWarning 迁移后 |
| 旧 `report_generator.py` | `hands/backtest/report_generator.py` | ~300 | `reporter.py` 是否完全替代 |
| 旧 `result.py` | `hands/backtest/result.py` | ~120 | `BacktestResult` 迁移后 |

**验证方法**: 删除前 `grep -r "from.*engine import\|import.*engine" tests/` — 确认无 import 后删除。

---

## 总执行顺序 (修订版)

```
Day 1       Day 2-3     Day 4-6      Day 7-9      Day 10-11    Day 12-15
┌────────┐  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐
│ Phase 2 │  │Phase 2.5│  │ Phase 3  │  │ Phase 4+5│  │ Phase 6  │  │ Phase 7   │
│ NTF     │→ │ walk-   │→ │SignalAr- │→ │Survivor  │  │ 补齐     │  │ 死代码    │
│ 语义    │  │ forward │  │bitrator  │  │+Factor   │  │ observ-  │→ │ + Dict    │
│ 修复    │  │ 修复    │  │CandSig   │  │Admission │  │ ability  │  │ 削减      │
└────────┘  └────────┘  └──────────┘  └──────────┘  └──────────┘  └───────────┘
```

**关键依赖**:
- Phase 2 (NTF) → 仲裁输入语义正确 → Phase 3 (SignalArbitrator) 不产生错误仲裁
- Phase 2.5 (walk-forward bug) → Phase 5 (FactorGate IC/IR) 不运行时崩溃
- Phase 4 (Survivorship) → 独立，可穿插进行
- Phase 5 (FactorGate) → 依赖 Phase 2.5
- Phase 6 → 独立，可在 Day 1 开始并行
- Phase 7 → 最后清理，但 Dict 削减可以从 brain/ 层提前开始

---

## 度量与关闭条件

```bash
# 测试通过
pytest tests/ -q
# → 维持 1139+ (无回归)

# 基线比对
python3 scripts/compare_baseline.py tests/benchmark/baseline_v0.parquet tests/benchmark/baseline_v_current.parquet
# → 100% 一致 (仲裁漂移需签字确认)

# Dict[str, Any] 计数
rg "Dict\[str, Any\]" src/uniquant/ | wc -l
# → < 50 (当前 468)

# NTF 语义修复后
python3 -c "
from uniquant.shared.interfaces import NtfSide
assert NtfSide.SUPPORT.value == 'SUPPORT'
assert NtfSide.RESISTANCE.value == 'RESISTANCE'
print('NTF semantic fix OK')
"

# FactorGate 模式
# config factor_gate: "warn" (默认 warn，后续转 block)
```

---

## 风险登记表

| 风险 | 概率 | 影响 | 缓解 |
|:---|---:|:---|:---|
| NTF 语义改后已有回测信号发生变化 | 高 | 中 | 回测基线比对 + 《仲裁影响评估报告》 |
| walk-forward factor_func 修复涉及面广 | 中 | 中 | 优先用方案 B (外部展开)，最小化改动 |
| FactorGate 在 brain/ 新建模块导致导入循环 | 中 | 中 | 父包 `__init__.py` 用 Lazy import |
| Dict 削减 468→50 严重低估 | 确定 | 高 | 优先保证 brain/services 层，UI 层可暂留 |
| 死代码清理破坏测试 | 中 | 高 | 删除前 grep test imports |
