# 实施计划任务卡 — Implementation Plan Task Cards

生成日期：2026-06-10
基于：WS1-WS15 审计发现 + 联合审查委员会评审意见 + 三角色融合执行策略
前置文档：`IMPLEMENTATION_ENTRY_CRITERIA.md`, `FINDINGS_INDEX.md`, `15_refactoring_roadmap.md`

---

## 总览

本实施计划将 WS14/WS15 的重构路线图与审查委员会评审意见融合，分为 **5 个阶段 + 第 0 阶段止血补丁**。与原始 WS15 计划的关键区别：

| 维度 | WS15 计划 | 本计划 |
|:---|:---|---|
| 执行顺序 | Phase 1→2→3→4→5 串行 | **Phase 0(止血)→Phase 1→Phase 3(提前仲裁)→Phase 2(引擎逐个迁移)→Phase 4+5 并行** |
| 引擎重构 | 9 个引擎全部在 Phase 2 迁移 | **DataService/Collector 两端先挤压，引擎逐个替换（每改一个验证一次基线）** |
| 止血补丁 | 无 | **第 0 阶段：今天可合入的 3 个关键修复** |
| 基准验证 | "regression tests" 概念 | **冻结黄金数据集 `baseline_v0.parquet`，浮点数级 100% 一致** |
| 仲裁漂移 | "对比新旧结果" | **《仲裁影响评估报告》+ 量化负责人签字** |
| 工程纪律 | 未展开 | **PR ≤500 行、特性开关三段生命周期、mypy 渐进式、谁主张谁证明** |

---

## 阶段 0 — 止血补丁（今天，Day 0-1）

**目标**：在核心架构重构开始前，用最小代价堵住正在导致研究结果不可靠的漏洞。

**原则**：每个补丁不超过 5 行生产代码改动，不需要特性开关，可以直接合入。

### Task 0.1 — 阻止 LPPL Danger 信号被 CZSC BUY 绕过

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS1-004, WS6-001, FINDINGS_INDEX P0-4 |
| **风险等级** | P0 |
| **文件** | `src/uniquant/hands/backtest/unified_engine.py` |
| **改动** | 在 `run()` 的 Step 3（line 241-258）中：在 `for sig in day_signals` 循环内，先检查 LPPL SELL 信号，命中则直接设挂单并 `break`，不检查后续 CZSC 等 adapter |
| **行数** | 1-2 |
| **测试** | `tests/test_lookahead_bias.py` 加一个 case：LPPL Danger + CZSC 3rd Buy → 期望结果是 SELL |
| **验证命令** | `pytest tests/test_lookahead_bias.py -xvs` |
| **回滚** | 直接 revert 该行 |

```python
# unified_engine.py:run() Step 3（约 line 241-258）for sig in day_signals 循环顶部插入：
if sig.action == "SELL" and "lppl" in sig.reason.lower():
    pending_order = {"action": "SELL", "shares": position, "reason": sig.reason}
    break  # LPPL SELL 优先级最高，直接生成挂单，不检查后续信号
```

### Task 0.2 — 修复回测信号时间戳为 K 线日期而不是 `pd.Timestamp.now()`

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS1-003, WS2-004, WS3-002, FINDINGS_INDEX P0-2 |
| **风险等级** | P0 |
| **文件** | `src/uniquant/services/research_pipeline.py` |
| **改动** | 将 `timestamp = pd.Timestamp.now()` 改为取 K 线最后一根 bar 的日期 |
| **行数** | 1-3 |
| **测试** | `tests/test_historical_signal_series.py` |
| **验证命令** | 手动运行一条已知回测，确认 trade timestamp 在 K 线日期范围内 |
| **回滚** | 直接 revert |

```python
# research_pipeline.py:133
# 旧: timestamp = pd.Timestamp.now()
# 新:
df_stock = collector_pack.get("stock")
timestamp = (
    pd.Timestamp(df_stock.iloc[-1]["date"])
    if df_stock is not None and not df_stock.empty
    else pd.Timestamp.now()
)
```

### Task 0.3 — BacktestResult 添加生存偏差警告

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS3-003, WS10-007, FINDINGS_INDEX P0-3 |
| **风险等级** | P1 |
| **文件** | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/services/research_pipeline.py` |
| **改动** | 在 `BacktestResult` 加 `metadata: Dict[str, Any]` 字段；在 pipeline 中检查 symbol 的 `delist_date` 是否在数据范围内 |
| **行数** | 5 |
| **测试** | `tests/test_survivorship_bias.py` |
| **验证命令** | `pytest tests/test_survivorship_bias.py -xvs` |
| **回滚** | 去掉 metadata 字段不影响已有代码 |

```python
# unified_engine.py: BacktestResult 加 metadata 字段
@dataclass
class BacktestResult:
    trades: List[TradeRecord]
    equity_curve: List[float]
    daily_returns: List[float]
    initial_capital: float = 0.0
    final_cash: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 阶段 1 — 安全网建设（Day 1-10，两周）

### Sprint 1.1 — 黄金基准集（Day 1-3）

**Task 1.1.1** 选定代表性股票池

| 元数据 | 内容 |
|:---|---|
| **文件** | `tests/benchmark/golden_100.txt`（新文件） |
| **内容** | 100 只 A 股：主板 40 + 科创板 10 + 创业板 15 + ST 10 + 已退市 5 + 长期停牌 5 + 高分红 15 |
| **选择标准** | 覆盖所有 board type、ST 状态、分红频率、停牌场景 |
| **验证** | 每只股票都有 5 年以上 K 线数据 |

**Task 1.1.2** 编写基准捕获脚本

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | FINDINGS_INDEX P0-3（验证基础设施） |
| **文件** | `scripts/capture_baseline.py`（新文件） |
| **功能** | 对 100 只股票逐一跑当前系统的完整 `UnifiedResearchPipeline.run()`，将 trades + equity_curve + daily_returns + 因子值序列化为 parquet |
| **输出** | `tests/benchmark/baseline_v0.parquet` |
| **验证命令** | `python scripts/capture_baseline.py --symbols tests/benchmark/golden_100.txt --output tests/benchmark/baseline_v0.parquet` |
| **运行时间** | 每只约 2-5 秒，100 只约 5-10 分钟 |

**Task 1.1.3** 编写基准比对脚本

| 元数据 | 内容 |
|:---|---|
| **文件** | `scripts/compare_baseline.py`（新文件） |
| **功能** | 读取 `baseline_v0.parquet` 和 `baseline_v1.parquet`，比对每笔交易的价格、数量、时间和每日净值曲线 |
| **验收标准** | 浮点数级 `assert_allclose(rtol=1e-10)` 一致。如果有预期漂移（如仲裁规则变更），输出差异报告 |
| **CI 集成** | 每个重构 PR 自动运行 `compare_baseline.py baseline_v0 baseline_v1` |

### Sprint 1.2 — 基础设施契约定义（Day 3-5）

**Task 1.2.1** `TimeProvider` DI 体系

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS2-004, WS4, WS5-009, FINDINGS_INDEX P0-2 |
| **文件** | `src/uniquant/shared/time_provider.py`（新文件） |
| **内容** | 定义 `TimeProvider` Protocol，实现 `RealTimeClock` 和 `SimulatedClock` |
| **行数** | ~40 |
| **测试文件** | `tests/shared/test_time_provider.py` |
| **测试内容** | `RealTimeClock` 返回真实时间；`SimulatedClock.advance_to()` 后 `now()` 返回冻结时间 |
| **验证命令** | `pytest tests/shared/test_time_provider.py -xvs` |
| **回滚** | 新文件，不影响已有代码 |

```python
# shared/time_provider.py
from typing import Protocol
import pandas as pd

class TimeProvider(Protocol):
    def now(self) -> pd.Timestamp: ...

class RealTimeClock:
    def now(self) -> pd.Timestamp:
        return pd.Timestamp.now(tz="Asia/Shanghai")

class SimulatedClock:
    def __init__(self):
        self._frozen: pd.Timestamp | None = None

    def advance_to(self, dt: pd.Timestamp) -> None:
        self._frozen = dt

    def now(self) -> pd.Timestamp:
        return self._frozen if self._frozen is not None else pd.Timestamp.now()
```

**Task 1.2.2** `ResearchDataPack` 类型定义

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS1-002, WS2-001, WS5-002, FINDINGS_INDEX P0-1 |
| **文件** | `src/uniquant/shared/interfaces.py`（追加） |
| **内容** | `ResearchDataPack` dataclass + `to_dict()` / `from_dict()` + `validate()` |
| **行数** | ~60 |
| **测试文件** | `tests/shared/test_research_data_pack.py` |
| **测试内容** | 创建、字段校验、to_dict/from_dict 往返一致性、缺失字段默认值 |
| **验证命令** | `pytest tests/shared/test_research_data_pack.py -xvs` |
| **回滚** | 追加内容，不影响已有代码 |

**Task 1.2.3** `DecisionOutput` 类型定义

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS5-003, FINDINGS_INDEX P0-1 |
| **文件** | `src/uniquant/shared/interfaces.py`（追加） |
| **测试文件** | `tests/shared/test_decision_output.py` |
| **验证命令** | `pytest tests/shared/test_decision_output.py -xvs` |

**Task 1.2.4** `CandidateSignal` 类型定义

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS6-001, WS6-002 |
| **文件** | `src/uniquant/shared/interfaces.py`（追加） |
| **测试文件** | `tests/shared/test_candidate_signal.py` |
| **验证命令** | `pytest tests/shared/test_candidate_signal.py -xvs` |

**Task 1.2.5** `FactorManifest` 类型定义

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS7-001, WS7-007 |
| **文件** | `src/uniquant/shared/factor_governance.py`（新文件，后续扩展） |
| **测试文件** | `tests/shared/test_factor_manifest.py` |
| **验证命令** | `pytest tests/shared/test_factor_manifest.py -xvs` |

**Task 1.2.6** `Event` / `Command` 事件类型定义

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS12-001 |
| **文件** | `src/uniquant/shared/event_types.py`（新文件） |
| **测试文件** | `tests/shared/test_event_types.py` |
| **验证命令** | `pytest tests/shared/test_event_types.py -xvs` |

### Sprint 1.3 — mypy 渐进式引入（Day 5-6）

**Task 1.3.1** 配置 mypy

| 元数据 | 内容 |
|:---|---|
| **文件** | `pyproject.toml`（追加 mypy 配置） |
| **内容** | `disallow_untyped_defs = True` 作用于新/改文件；忽略旧文件 |
| **验证命令** | `mypy src/uniquant/shared/interfaces.py` |

**Task 1.3.2** CI 集成 mypy

| 元数据 | 内容 |
|:---|---|
| **文件** | CI 配置（GitHub Actions 或等价） |
| **内容** | mypy 检查新/改文件，不允许新增未类型标注的函数 |

### Sprint 1.4 — 配置框架 + 特性标志（Day 6-8）

**Task 1.4.1** 引入 `pydantic-settings`

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS9-003, WS9-004, WS9-006, WS9-007 |
| **文件** | `src/uniquant/shared/config_models.py`（新文件） |
| **内容** | `RefactoringConfig`(use_research_data_pack, use_signal_arbitration, use_engine_cache, strict_mode)、`PipelineConfig`(analysis_mode, use_historical_signal_runner) 等模型 |
| **验证命令** | `pytest tests/shared/test_config_models.py -xvs` |
| **特性开关定义** | 所有新行为默认 false，保持现有行为不变 |

```yaml
# config/config.yaml 追加
refactoring:
  use_research_data_pack: false
  use_signal_arbitration: false
  use_strict_timestamps: false
  engine_cache_enabled: false
  factor_gate_mode: "off"     # off | warn | block
```

**Task 1.4.2** 将 `ServiceContainer` 接入配置框架

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/services/service_container.py` |
| **改动** | 初始化时读取 `RefactoringConfig` 并传递给相关服务 |
| **验证** | 特性开关 = false 时，系统行为与之前完全一致 |

### Sprint 1.5 — 出口里程碑：阶段 1 完成检查（Day 9-10）

```bash
# 全部通过才算出口
pytest tests/shared/test_time_provider.py -xvs
pytest tests/shared/test_research_data_pack.py -xvs
pytest tests/shared/test_decision_output.py -xvs
pytest tests/shared/test_candidate_signal.py -xvs
pytest tests/shared/test_factor_manifest.py -xvs
pytest tests/shared/test_event_types.py -xvs
pytest tests/shared/test_config_models.py -xvs
pytest tests/ -q                                   # 全部已有测试依然通过
python scripts/capture_baseline.py --verify-only    # 基准集完好
mypy src/uniquant/shared/interfaces.py              # 新类型检查通过
python3 -c "from uniquant.shared.interfaces import TradingSignal, ResearchDataPack, DecisionOutput; print('Phase 1 exports OK')"
```

---

## 阶段 2 — 最小信号仲裁 + 因子门禁（Day 11-20）

此阶段从 Phase 3（信号仲裁）提前，因为：
1. LPPL 绕过 bug 已经做了最小修复（Task 0.1），但完整的仲裁体系需要契约化
2. 仲裁不依赖引擎迁移完成，可以与 Phase 3（引擎迁移）并行

### Sprint 2.1 — `SignalArbitrator` 实现（Day 11-14）

**Task 2.1.1** 仲裁器核心逻辑

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS6-001, WS6-002, WS6-004, WS6-006, FINDINGS_INDEX P0-4 |
| **文件** | `src/uniquant/signal/arbitrator.py`（新文件） |
| **内容** | `SignalArbitrator.arbitrate(candidates, decision_output, context)` → `Tuple[TradingSignal, ArbitrationReport]` |
| **优先级规则** | 1. FORCE_WAIT / CIRCUIT_BREAK → HOLD（可 veto 所有 BUY）；2. FORCE_EXIT → SELL；3. DecisionBrain BUY + risk-sized shares；4. 非 FSM BUY 候选需 PositionSizer 门禁；5. HOLD 默认 |
| **行数** | ~120 |
| **测试文件** | `tests/signal/test_arbitrator.py` |

```python
# arbitration 优先级伪代码
def arbitrate(self, candidates, decision_output, context, sizer=None):
    if decision_output.final_decision in ("FORCE_WAIT", "CIRCUIT_BREAK"):
        return HOLD("risk_veto", ...)
    if decision_output.final_decision == "FORCE_EXIT":
        return SELL("force_exit", ...)
    if decision_output.final_decision == "BUY" and decision_output.shares > 0:
        return BUY("decision_brain", shares=decision_output.shares)
    if sizer and any(c.action == "BUY" and c.source != "fsm" for c in candidates):
        sized = sizer.calculate_shares(...)
        if sized["suggested_shares"] > 0:
            return BUY("non_fsm_approved", shares=sized["suggested_shares"])
    return HOLD("default_no_trade")
```

测试矩阵（`tests/signal/test_arbitrator.py`）：

| 测试用例 | 输入 | 期望输出 |
|:---|---|---|
| `test_force_wait_veto_blocks_buy` | FORCE_WAIT + CZSC BUY | HOLD，reason="risk_veto" |
| `test_circuit_break_blocks_all` | CIRCUIT_BREAK + any BUY/SELL | HOLD |
| `test_force_exit_wins` | FORCE_EXIT + CZSC BUY | SELL |
| `test_decision_brain_buy_with_shares` | Decision BUY + shares=200 | BUY, shares=200 |
| `test_non_fsm_buy_needs_sizer` | Wyckoff BUY + 无 sizer | HOLD |
| `test_non_fsm_buy_sizer_approves` | Wyckoff BUY + sizer 返回 100 | BUY, shares=100 |
| `test_lppl_sell_not_overridden_by_czsc_buy` | LPPL SELL + CZSC BUY | SELL |
| `test_arbitration_report_metadata` | 任意仲裁场景 | ArbitrationReport 包含所有候选源和理由 |

**Task 2.1.2** 仲裁器接入 Pipeline

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/services/research_pipeline.py` |
| **改动** | `refactoring.use_signal_arbitration==false` 时走旧路径（collector.collect → 直接喂给 backtest）；`==true` 时走仲裁路径 |
| **特性开关** | `config.refactoring.use_signal_arbitration: false`（默认关） |
| **验证命令** | `pytest tests/integration/test_signal_pipeline.py -xvs` |

**Task 2.1.3** 仲裁影响评估报告

实施者在开启特性开关进行灰度后，需产出《仲裁系统上线回测影响评估报告》，内容包括：

```
1. 新旧路径在 golden 100 只股票上的总体统计对比
   - 总收益率变化分布（均值、中位数、极端值）
   - 最大回撤变化分布
   - 夏普比率变化分布
2. 3-5 个"旧版未防住风险、新版成功防住"的交易切片
   - 显示旧路径在 LPPL Danger 下仍然开仓
   - 显示新路径正确阻断
3. 量化研究负责人的签字确认
```

### Sprint 2.2 — `FactorAdmissionGate` 实现（Day 14-16）

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS7-001, WS7-005, WS7-007, WS7-008, WS7-009, FINDINGS_INDEX P0-5 |
| **文件** | `src/uniquant/shared/factor_governance.py`（扩展） |
| **内容** | `FactorAdmissionGate.evaluate(factor_func, manifest, data, config)` → `FactorAdmissionReport` |
| **当前模式** | `factor_gate_mode: "warn"` — 仅记录日志，不阻止注册 |
| **检查项目** | schema 校验、NaN/Inf 检查、IC/IR 计算、walk-forward OOS IC、PBO、冗余度、tradability 检查 |
| **测试文件** | `tests/shared/test_factor_admission_gate.py` |

```python
class FactorAdmissionGate:
    def __init__(self, mode: str = "warn"):
        self.mode = mode  # "off" | "warn" | "block"

    def evaluate(self, manifest, factor_func, data) -> FactorAdmissionReport:
        checks = {}
        checks["schema"] = self._check_schema(manifest, data)
        checks["safety"] = self._check_safety(factor_func, data)
        checks["lookahead"] = self._check_lookahead(factor_func, data)
        checks["ic_ir"] = self._check_ic_ir(factor_func, data)
        checks["oos"] = self._check_oos(factor_func, data)
        checks["pbo"] = self._check_pbo(factor_func, data)
        passed = all(c.passed for c in checks.values())
        if not passed and self.mode == "warn":
            logger.warning(f"Factor {manifest.name} failed admission: {checks}")
        elif not passed and self.mode == "block":
            raise FactorAdmissionError(f"Factor {manifest.name} blocked: {checks}")
        return FactorAdmissionReport(factor_name=manifest.name, passed=passed, checks=checks)
```

### Sprint 2.3 — `TimeProvider` 接入 Pipeline（Day 16-18）

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | FINDINGS_INDEX P0-2 |
| **文件** | `src/uniquant/services/service_container.py`, `src/uniquant/services/research_pipeline.py`, `src/uniquant/services/analysis_service_v2.py` |
| **内容** | `ServiceContainer` 初始化 `RealTimeClock`；`UnifiedResearchPipeline` 接收 `TimeProvider` 依赖注入；`AnalysisService` 使用 `TimeProvider` 代替 `pd.Timestamp.now()` |
| **特性开关** | `refactoring.use_strict_timestamps: false` 时使用旧 `pd.Timestamp.now()`；`true` 时用 `RealTimeClock`（行为不变，为后续 `SimulatedClock` 铺路） |
| **验证命令** | `pytest tests/integration/test_backtest_regression.py -xvs` |

```python
# ServiceContainer 中
if config.refactoring.use_strict_timestamps:
    clock = RealTimeClock()
else:
    clock = None  # 兼容旧代码，仍使用 pd.Timestamp.now()

# ResearchPipeline 注入
self._pipeline = UnifiedResearchPipeline(
    analysis_service=analysis_service,
    backtest_engine=backtest_engine,
    signal_collector=signal_collector,
    time_provider=clock,
)
```

### Sprint 2.4 — 出口里程碑（Day 19-20）

```bash
pytest tests/signal/test_arbitrator.py -xvs
pytest tests/shared/test_factor_admission_gate.py -xvs
pytest tests/integration/test_signal_pipeline.py -xvs
pytest tests/ -q
python3 -c "from uniquant.signal.arbitrator import SignalArbitrator; a=SignalArbitrator(); print('OK')"
```

---

## 阶段 3 — 引擎逐个迁移（Day 21-38，三周）

**核心策略**：两头挤压法，引擎逐个替换。不改动的引擎保持在 dict 模式。

**迁移架构**：

```
[DataService]                               [Collector/Backtest]
     │                                             ▲
     │  ResearchDataPack (typed)                    │  TradingSignal / DecisionOutput (typed)
     │      ↓ to_dict()                             │      ↑ from_dict()
     ▼                                             │
[中间层: 所有 Engine 仍接收 Dict[str, Any]]
     逐个替换: Regime→LPPL→CZSC→Wyckoff→Alpha→...→FSM
```

### Sprint 3.1 — DataService 端挤压（Day 21-23）

**Task 3.1.1** `DataService` 添加 typed 路径

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/services/data_service.py` |
| **改动** | `fetch_for_brain()` 内部调用 `_build_research_data_pack()` 构建 `ResearchDataPack`，然后 `to_dict()` 转回 dict 输出给旧 Engine |
| **新方法** | `fetch_research_data_pack(symbol)` → `ResearchDataPack`（后续直接返回 typed） |
| **验证命令** | `pytest tests/integration/test_data_service_typed.py -xvs` |

```python
def fetch_for_brain(self, symbol, ...):
    """旧方法：返回 Dict[str, Any]（兼容旧引擎）"""
    pack = self._build_research_data_pack(symbol, ...)
    return pack.to_dict()

def fetch_research_data_pack(self, symbol, ...) -> ResearchDataPack:
    """新方法：返回 Typed ResearchDataPack"""
    return self._build_research_data_pack(symbol, ...)

def _build_research_data_pack(self, symbol, ...) -> ResearchDataPack:
    """统一构建逻辑"""
    stock_df = self._load_stock_data(symbol, ...)
    bench_df = self._load_benchmark_data(...)
    etf_df = self._load_etf_data(...)
    return ResearchDataPack(
        symbol=symbol, stock=stock_df, bench=bench_df, etf=etf_df, ...
    )
```

### Sprint 3.2 — 首批引擎迁移（Day 23-26）

**原则**：每改一个引擎，跑一次 golden baseline 验证。

**Task 3.2.1** Regime 引擎迁移

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/brain/regime/regime_detector.py`, `src/uniquant/services/analysis_service_v2.py` |
| **改动** | Regime engine 输入从 `data_pack: Dict` 改为 `pack: ResearchDataPack` |
| **验证** | `python scripts/compare_baseline.py tests/benchmark/baseline_v0.parquet tests/benchmark/baseline_v1.parquet` → 100% 一致 |

**Task 3.2.2** NTF 引擎迁移（同上模式）

**Task 3.2.3** LPPL 引擎迁移（同上模式）

### Sprint 3.3 — 第二批引擎迁移（Day 26-31）

**Task 3.3.1** CZSC 引擎迁移

**Task 3.3.2** Alpha 引擎迁移

**Task 3.3.3** Wyckoff 引擎迁移 + 性能优化

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/brain/wyckoff/engine.py`, `src/uniquant/brain/wyckoff/classifiers.py` |
| **前置步骤** | `py-spy record -o wyckoff_flame.svg -- python ...` 生成火焰图，定位热点 |
| **优化目标** | 将 `itertuples()` 循环替换为 numpy 向量化操作；将独立 classifier 函数用 `@numba.jit(nopython=True)` 编译 |
| **验证** | 基准集结果 100% 一致 + `perf_report` 前后对比至少 3x 加速 |
| **回滚** | 保留旧 engine.py，通过配置开关切换 |

### Sprint 3.4 — DecisionBrain 输出迁移（Day 31-33）

**Task 3.4.1** `DecisionBrain.make_decision()` 输出 `DecisionOutput`

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/brain/fsm/fsm.py` |
| **改动** | 输出从 `Dict[str, Any]` 改为 `DecisionOutput`；提供 `to_dict()` 兼容旧 Collector |
| **验证** | `pytest tests/integration/test_backtest_regression.py -xvs` |

**Task 3.4.2** `MarketSignalContext` 接入

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS2-010, WS5-008, FINDINGS_INDEX P1-6 |
| **文件** | `src/uniquant/services/analysis_service_v2.py`, `src/uniquant/brain/fsm/fsm.py` |
| **改动** | `AnalysisService._make_decision()` 传入 `MarketSignalContext.from_data_pack()` 而不是 raw dict |

### Sprint 3.5 — 剩余引擎迁移 + 旧路径清理（Day 33-37）

**Task 3.5.1** FSM 引擎 + Screener + Indicator 引擎迁移
**Task 3.5.2** 删除 `_build_data_pack()` 旧路径
**Task 3.5.3** 删除 `DecisionBrain._make_decision()` 的 dict 兼容路径
**Task 3.5.4** 删除 `TradingSignalCollector.collect()` 的 dict 兼容路径

### Sprint 3.6 — 出口里程碑（Day 38）

```bash
# 最终验证
python scripts/capture_baseline.py --output tests/benchmark/baseline_v_final.parquet
python scripts/compare_baseline.py baseline_v0 baseline_v_final

# 如果无预期漂移：必须 100% 一致
# 如果有预期漂移（仲裁逻辑）：输出差异报告 + 量化负责人签字

pytest tests/ -q                                       # 全部测试通过
rg "Dict\[str, Any\]" src/uniquant/ | wc -l            # < 50 处（原 430 处）
rg "(pd\.Timestamp|datetime(\.datetime)?)\.now\(" src/uniquant/ | wc -l  # < 10 处（原 126 处，含 pd.Timestamp.now + datetime.now）
mypy src/uniquant/ --disallow-untyped-defs              # 新/改文件全部有类型标注
```

---

## 阶段 4 — EventBus + 可观测性（Day 21-28，与阶段 3 并行）

**因为不依赖引擎迁移完成，此阶段可以与阶段 3 并行执行。**

### Sprint 4.1 — EventBus 同步模式（Day 21-25）

**Task 4.1.1** EventBus 实现

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/shared/event_bus.py`（新文件） |
| **内容** | 同步 `EventBus`，支持 `publish(event)` + `subscribe(event_type, handler)` + 错误隔离 |
| **特性开关** | `refactoring.enable_event_bus: false`（默认关） |
| **测试** | `tests/shared/test_event_bus.py` |

**Task 4.1.2** Pipeline 事件接入

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/services/research_pipeline.py` |
| **事件序列** | `RunStarted` → `DataLoaded` → `EngineCompleted`(×8) → `DecisionProduced` → `SignalsCollected` → `BacktestCompleted` → `RunCompleted` |
| **测试** | `tests/integration/test_event_bus_integration.py` |

### Sprint 4.2 — Metrics 与 Observability（Day 25-28）

**Task 4.2.1** `MetricsRecorder` 实现

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/shared/observability.py`（新文件） |
| **内容** | `InMemoryMetricsRecorder` 记录 counter/histogram/gauge；附加到 `PipelineResult.metadata` |
| **测试** | `tests/shared/test_observability.py` |

**Task 4.2.2** `perf_section()` 埋点

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS8-002 |
| **文件** | `src/uniquant/services/research_pipeline.py`, `src/uniquant/services/analysis_service_v2.py`, `src/uniquant/signal/adapters.py` |
| **内容** | 在每个引擎入口和出口加 `with perf_section("engine_regime")` 等 |
| **验证** | `UNIQUANT_PERF=1 pytest tests/ -xvs` 输出 perf_report |

---

## 阶段 5 — 配置 + 健康检查强化（Day 21-26，与阶段 3 并行）

### Sprint 5.1 — 配置模型强化（Day 21-23）

**Task 5.1.1** `ConfigValidator` 实现

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/shared/config_validator.py`（新文件） |
| **内容** | 在 `ServiceContainer.initialize()` 中验证所有关键配置段：data_sources class 路径可导入、factor registry 一致性、路径存在性 |
| **验证** | 配置缺失时启动失败（Fail Fast） |

**Task 5.1.2** 环境变量叠加

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS9-005, WS9-010 |
| **文件** | `src/uniquant/shared/config_loader.py` |
| **内容** | 允许环境变量覆写配置：`UNIQUANT_TDX_PATH` 覆写 `base.tdx.path` |

### Sprint 5.2 — HealthService 强化（Day 24-26）

**Task 5.2.1** 健康检查拆分

| 元数据 | 内容 |
|:---|---|
| **追溯 ID** | WS11-005, WS13-002, WS13-003, WS13-004 |
| **文件** | `src/uniquant/services/health_service.py` |
| **内容** | 拆分为三层：`liveness()`（进程 + 配置加载）、`readiness()`（数据 + 缓存路径可用）、`diagnostics()`（完整的端到端检查，按需触发） |

**Task 5.2.2** 缓存 + 数据源健康监控

| 元数据 | 内容 |
|:---|---|
| **文件** | `src/uniquant/services/health_service.py` |
| **内容** | 报告缓存命中率、数据源上次成功获取时间、数据新鲜度 |

---

## 实施顺序总图

```text
Week 1 (Day 0-5)    Week 2 (Day 6-10)        Week 3-4 (Day 11-20)          Week 5-7 (Day 21-38)
┌─────────────┐    ┌───────────────┐       ┌──────────────────────┐      ┌────────────────────────┐
│ Phase 0     │    │ Phase 1       │       │ Phase 2 (提前)        │      │ Phase 3 (引擎迁移)     │
│ 止血补丁    │    │ 安全网        │       │ 仲裁 + 因子门禁      │      │ DataService 端挤压     │
│ 3 个 task   │    │ 基准集        │       │ SignalArbitrator     │      │ Regime → LPPL          │
│             │    │ TimeProvider  │       │ FactorGate           │      │ CZSC → Wyckoff → Alpha │
│             │    │ 契约定义      │       │ TimeProvider 接入    │      │ DecisionOutput → FSM   │
│             │    │ mypy + 配置   │       │                      │      │ 旧路径清理             │
└─────────────┘    └───────────────┘       └──────────────────────┘      └────────────────────────┘
                                                    │                              │
                                                    │           并行              │
                                                    └──────────────────────────────┤
                                           ┌──────────────────┐   ┌──────────────┐│
                                           │ Phase 4          │   │ Phase 5      ││
                                           │ EventBus         │   │ Config       ││
                                           │ Metrics          │   │ Health       ││
                                           │ perf_section     │   │ pydantic+env ││
                                           └──────────────────┘   └──────────────┘│
                                                                                  │
                                                                    ┌─────────────┘
                                                                    ▼
                                                          出口检查：基线一致 + 所有测试通过
                                                          Dict[str,Any] < 50
                                                          pd.Timestamp.now() < 10
                                                          mypy 通过
```

---

## 人力和时间估算

| 阶段 | 内容 | 天数 | 需要开发者 | 并行性 |
|:---|:---|---:|:---:|:---|
| Phase 0 | 止血补丁 | 1 | 1 | — |
| Phase 1 | 安全网 | 10 | 1 | — |
| Phase 2 | 仲裁 + 因子 | 10 | 1 | 与 Phase 4/5 并行 |
| Phase 3 | 引擎迁移 | 18 | 1-2 | 与 Phase 4/5 并行 |
| Phase 4 | EventBus + Observability | 8 | 1 | 与 Phase 2/3/5 并行 |
| Phase 5 | Config + Health | 6 | 1 | 与 Phase 2/3/4 并行 |
| **总计** | | **日历 38 天** | **2 人并行** | **实际执行 ~25 人天** |

**建议人员配置**：
- **开发者 A**：Phase 0 → Phase 1 → Phase 2 → Phase 3（全流程核心）
- **开发者 B**：Phase 4 + Phase 5（从 Week 3 开始，与 A 并行）

---

## 风险登记表

| 风险 | 概率 | 影响 | 缓解措施 |
|:---|---:|:---|:---|
| 引擎迁移（Phase 3）改坏了回测逻辑 | 中 | **高** | 黄金基准集 + 每改一个引擎验证一次 + 特性开关回滚 |
| 仲裁逻辑改变了已有回测结果 | 确定 | 中 | 《仲裁影响评估报告》+ 量化负责人签字，非 bug 的漂移视为可接受 |
| `TimeProvider` 替换漏掉 `datetime.now()` | 高 | 中 | `rg "pd\.Timestamp\.now\(|datetime\.now\("` CI 检查 |
| 并行开发导致大量合并冲突 | 中 | 中 | Phase 4/5 修改文件与 Phase 3 不重叠（shared/ 新文件 vs brain/ 旧文件） |
| Wyckoff 优化后行为不一致 | 中 | 中 | golden baseline 验证 + 性能对比 |
| `FactorAdmissionGate` warn 模式形同虚设 | 高 | 低 | 先 warn，逐步切换到 block，给研究员适应期 |

---

## 关闭条件

全部 38 天实施完成后：

```bash
# 1. 全部测试通过
pytest tests/ -q --cov=src/uniquant/
# 覆盖率目标: 每个层 > 80%

# 2. 回测基线一致（或已确认漂移在可接受范围）
python scripts/compare_baseline.py tests/benchmark/baseline_v0.parquet tests/benchmark/baseline_v_final.parquet

# 3. 类型安全
rg "Dict\[str, Any\]" src/uniquant/ | wc -l   # < 50
mypy src/uniquant/ --disallow-untyped-defs      # 新/改文件全部类型标注

# 4. 时间戳安全
rg "(pd\.Timestamp|datetime(\.datetime)?)\.now\(" src/uniquant/ | wc -l  # < 10（仅在 RealTimeClock 中）

# 5. P0/P1 全部解决
# P0-1 ✅ ResearchDataPack 替代 data_pack
# P0-2 ✅ TimeProvider 替代 pd.Timestamp.now()
# P0-3 ✅ 基准集验证 + survivorship warning
# P0-4 ✅ SignalArbitrator 仲裁信号
# P0-5 ✅ FactorAdmissionGate 因子门禁（warn 模式）
# P1-1 ✅ Wyckoff 3x 加速
# P1-2 ✅ ScanService 并行 + checkpoint
# P1-3 ✅ PortfolioEngine 清理
# P1-4 ✅ A 股规则测试化
# P1-5 ✅ 批量 checkpoint
# P1-6 ✅ MarketSignalContext 接入
# P1-7 ✅ 错误分类统一
# P1-8 ✅ Config 注入 + secrets

# 6. 特性开关状态
# arbitration: on（默认开启）
# factor_gate: warn（逐步过渡到 block）
# engine_cache: on（默认开启）
# event_bus: on（默认开启）
# strict_timestamps: on（默认开启）
```
