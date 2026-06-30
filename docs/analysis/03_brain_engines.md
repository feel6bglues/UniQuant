# Stage 3 — Brain/Signal 引擎深度分析

> **日期**: 2026-06-29 | **状态**: ✅ 完成
> **范围**: `services/analysis/` (7 引擎适配器), `brain/` (6 核心引擎), `signal/` (仲裁器), `brain/fsm/fsm.py` (DecisionBrain)
> **前置**: `00_architecture_map.md`, `01_services_orchestration.md`

---

## 1. 总览

### 引擎流水线

```
run_ticker_analysis()
  ├─ _prepare_data()               → DataService 获取 data_pack
  └─ _run_engines()                → 串行执行 7 引擎
       ├─ 1. _run_regime()         → RegimeDetector (市场级缓存)
       ├─ 2. _run_lppl()           → LpplAnalysisEngine → LPPLEngine
       ├─ 3. _run_ntf()            → NTFEngine (市场级缓存)
       ├─ 4. _run_czsc()           → CzscAnalysisEngine → CZSCEngine
       ├─ 5. _run_wyckoff()        → WyckoffAnalysisEngine → WyckoffEngine
       ├─ 6. _run_alpha()          → AlphaDecoupler
       └─ 7. _calculate_derived()  → Indicators (MA, ATR, 价格)
  └─ _make_decision()              → DecisionBrain.make_decision()
       └─ TradingSignalCollector   → (Pipeline 层, 在分析服务之外)
```

### 文件映射

| # | 引擎 | 适配器 (services/analysis/) | 核心实现 (brain/) | 输出类型 |
|---|------|---------------------------|-------------------|----------|
| 1 | Regime | `regime_analysis_engine.py` | `brain/regime/regime_detector.py` | `RegimeOutput` |
| 2 | LPPL | `lppl_analysis_engine.py` | `brain/lppl/engine.py` | `LPPLOutput` |
| 3 | NTF | `ntf_analysis_engine.py` | `brain/ntf/ntf_engine.py` | `NtfOutput` |
| 4 | CZSC | `czsc_analysis_engine.py` | `brain/czsc/czsc_engine.py` | `CZSCOutput` |
| 5 | Wyckoff | `wyckoff_analysis_engine.py` | `brain/wyckoff/engine.py` | `WyckoffOutput` |
| 6 | Alpha | (内联在 analysis_service_v2.py) | `brain/alpha_decoupler/alpha_decoupler.py` | `AlphaOutput` |
| 7 | 衍生指标 | (内联在 analysis_service_v2.py) | `brain/indicators/indicators.py` | 嵌入 data_pack |
| 8 | 宏观 | `macro_analysis_engine.py` | 依赖 EVT risk + DataService | Dict |
| 9 | FSM | `fsm_analysis_engine.py` | `brain/fsm/fsm.py` → FSM | Dict |
| — | 决策 | — | `brain/fsm/fsm.py` → `DecisionBrain` | `DecisionOutput` |

---

## 2. 引擎适配器层分析

### 2.1 通用模式

所有 services/analysis 引擎适配器共享以下特征：

```python
class XxxAnalysisEngine:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator  # AnalysisService 实例

    def run_xxx_analysis(self, symbol, df=None) -> TypedOutput:
        # 1. try brain-layer engine
        # 2. catch RECOVERABLE_ERRORS tuple
        # 3. return typed dataclass (with fallback defaults)
```

**RECOVERABLE_ERRORS 元组 (7-8 异常通用)**:
```python
(AttributeError, ImportError, KeyError, ModuleNotFoundError,
 OSError, RuntimeError, TypeError, ValueError)
```
每个引擎适配器定义了自身的版本（macro 引擎少了 `ImportError` 和 `ModuleNotFoundError`）。

### 2.2 各引擎适配器细节

#### RegimeAnalysisEngine
- 两个入口: `run_regime_detection()` (public) 和 `_run_regime_detection()` (private, 带缓存)
- 使用沪深 300 (000300.SH) 作为市场基准
- 两级缓存: 内存缓存 (`self.orchestrator._market_cache['regime']`) + 磁盘缓存 (24h TTL)
- 降级策略: 失败时返回 `{"regime": "NORMAL", "status": "failed"}`
- **注意**: Wrapper 层逻辑与 `analysis_service_v2.py` 中的新 `_run_regime()` 实现不同 — wrapper 仍用旧版 `_market_cache` dict，新实现在 `AnalysisService._run_regime()` 中通过 `MarketLevelCache` 实现

#### LpplAnalysisEngine
- 两个工厂函数: `create_lppl_engine()` 和 `create_lppl_data_service()`
- `run_lppl_analysis()` 尝试 `LPPLEngine.detect_bubble(df)`，失败时回退 `_fallback_lppl_analysis()`
- 回退逻辑: 使用价格振幅 (amplitude) 和收益率偏度/峰度做基本统计检测
- 输出 `LPPLOutput`: risk_level, confidence, days_to_tc, price, r_squared, out_of_sample_r_squared

#### NtfAnalysisEngine
- 使用 510300.SH (沪深 300 ETF) 作为国家队代理指标
- 二级缓存: 内存 (`_market_cache['ntf_signals']`) + 磁盘 (24h TTL)
- **注意**: 同上，wrapper 层逻辑与 `analysis_service_v2.py` 中的新 `_run_ntf()` 实现不同

#### CzscAnalysisEngine
- 依赖 czsc 第三方库包装缠论 (Zen) 分析
- `CZSCSignalType` 枚举 (`一买/一卖/二买/二卖/三买/三卖`) 代替字符串匹配
- `CZSCEngine` 核心: 本地 `RawBar` 构建 → CZSC 对象 → 信号解析
- 输出 `CZSCOutput`: is_3rd_buy, bi_count, price, bottom

#### WyckoffAnalysisEngine
- 调用 `WyckoffEngine.run_wyckoff_analysis()`，输出 `WyckoffOutput`
- WyckoffEngine v3.0 核心: 多周期分析 (日/周/月)、自定义 rules/classifiers/phase_analysis

#### MacroAnalysisEngine
- 最复杂的适配器: 使用 `@handle_errors`, `@retry`, `@validate_inputs` 装饰器链
- 依赖 EVT risk 计算宏观风险指标 (VaR 95/99, CVaR 95/99, max drawdown)
- 两级缓存 (磁盘, 1h TTL)
- 验证服务: 与 `validation_service` 对比标准方法差异
- 精度一致性: `ensure_precision_consistency()` 归一化浮点精度

---

## 3. 核心引擎实现

### 3.1 FSM 状态机 (`brain/fsm/fsm.py`)

**FSM 类**: 基于 MA20/MA60 均线交叉的市场趋势判断

- 7 状态: IDLE, SIGNAL, PROBE, MONITOR, PYRAMID, EXIT, CIRCUIT_BREAK
- 3 个核心方法:
  - `infer_state(df)`: 检查价格与 MA60 关系，判断趋势状态 (SIGNAL/PROBE/MONITOR/IDLE)
  - `_validate_input()`: 确保 OHLC 列完整
  - `_build_state_result()`: 输出包含 `state`, `state_name`, `state_desc`, `transition_reason`, `ma_status`
- Look-ahead Bias 修复: `is_intraday=True` 时排除当前未收盘 K 线

**DecisionBrain 类** — 总控决策引擎 ("Veto-Scoring" 架构)

```
make_decision(data_packet)
  │
  ├─ 1. Symbol 切换检测 → 重置 FSM 状态到 IDLE
  │
  ├─ 2. _check_veto_conditions()
  │   ├─ FROZEN 市场 → FORCE_WAIT
  │   ├─ 风险引擎失败 → FORCE_WAIT
  │   └─ LPPL Danger + 无 NTF 支持 → FORCE_EXIT
  │
  ├─ 3. 熔断检查 (B-007)
  │   └─ 当日跌幅 < -5% → CIRCUIT_BREAK
  │
  ├─ 4. _calculate_score() — 加权评分
  │   ├─ 三买信号      +40 (CZSC)
  │   ├─ MA20 > MA60   +30 (趋势)
  │   ├─ Alpha > 0.6   +20 (Alpha)
  │   └─ NTF 支持      +10 (政策)
  │   └─ 总分范围: 0-100
  │
  ├─ 5. _check_sell_conditions()
  │   ├─ LPPL Danger
  │   ├─ MA 反转 (MA20 <= MA60)
  │   ├─ Alpha < -0.5
  │   ├─ Regime FROZEN/STRESSED
  │   └─ 跌停 → HOLD (非 SELL)
  │
  ├─ 6. _determine_target_state(score, is_3rd_buy)
  │   └─ 阈值驱动: IDLE→SIGNAL(>=50) / SIGNAL→MONITOR(>=60) / MONITOR→PYRAMID(>=80) / EXIT(<20)
  │
  ├─ 7. _check_buy_blockers()
  │   └─ LPPL Danger / FROZEN / 风险引擎失败 / 止损过宽 / Alpha 弱 / 涨跌停
  │
  └─ 8. _execute_buy()
      └─ EVT 风险指标 → PositionSizer → 最终股数 (含风险缩放)
```

**状态持久化**: 通过 `_save_state()` / `_load_state()` 保存到 JSON 文件 (FileLock 保护)，重启后恢复

**状态转换矩阵**:

```
IDLE     → SIGNAL, PROBE, CIRCUIT_BREAK
SIGNAL   → PROBE, IDLE, CIRCUIT_BREAK
PROBE    → MONITOR, IDLE, EXIT, CIRCUIT_BREAK
MONITOR  → PYRAMID, EXIT, IDLE, CIRCUIT_BREAK
PYRAMID  → MONITOR, EXIT, CIRCUIT_BREAK
EXIT     → IDLE, CIRCUIT_BREAK
CIRCUIT_BREAK → IDLE
```

### 3.2 LPPL 泡沫检测 (`brain/lppl/engine.py`)

- LPPLConfig 配置驱动: 多窗口拟合 (40-100 天, 步长 20), 支持 Numba/JIT 加速
- 两种优化器: L-BFGS-B (生产默认) 和 Differential Evolution (离线研究, ~50x 慢)
- Ensemble 架构: 多窗口投票, `consensus_threshold=0.5`
- 输出风险级别: Danger → Warning → Watch → Safe
- 依赖参数: `W_BOUNDS`, `M_BOUNDS`, `RANDOM_SEED` (来自 shared/constants)

### 3.3 CZSC 缠论 (`brain/czsc/czsc_engine.py`)

- 包装 `czsc` 库: `RawBar` 构建 → `CZSC` 对象 → 信号提取
- `CZSCSignalType` 枚举: 一买/一卖/二买/二卖/三买/三卖 + UNKNOWN
- 兼容中英文信号值匹配
- 支持 `volume` 和 `vol` 两种成交量列名

### 3.4 Wyckoff 威科夫 (`brain/wyckoff/engine.py`)

- v3.0 架构: `RegimeAwarePhaseClassifier`, `V3Rules`, `PointAndFigure`
- 多周期分析: 日线/周线/月线, 自动调整回看窗口
- 核心阶段: Accumulation → Markup → Distribution → Markdown
- 输出: `WyckoffReport`, `WyckoffSignal`, `TradingPlan`

### 3.5 Regime 市场状态 (`brain/regime/regime_detector.py`)

- 基于沪深 300 指数的市场状态检测
- 输出: NORMAL, STRESSED, FROZEN, UNKNOWN
- 通过 `get_typed_summary(df)` 返回 `RegimeOutput`

### 3.6 Alpha 分离度 (`brain/alpha_decoupler/alpha_decoupler.py`)

- `get_alpha_score(stock, bench, sector)`: 相对于市场基准和行业基准的超额收益
- 依赖沪深 300 (000300.SH) 和中证 500 (000905.SH) 基准数据

---

## 4. 信号仲裁 (SignalArbitrator)

位于 `src/uniquant/signal/arbitrator.py`

**仲裁规则**:
1. `TradingSignalCollector` 将各引擎输出转为 `CandidateSignal` (typed dataclass)
2. `SignalArbitrator` 基于置信度、方向和强度进行仲裁
3. SELL 优先规则: 当任意引擎发出 SELL 信号时，仲裁器优先处理
4. BUY 信号需要多个引擎共识 + 置信度加权

**仲裁流程**:
```
TradingSignalCollector.collect(data_pack)
  ├─ regime_output   → CandidateSignal
  ├─ lppl_output     → CandidateSignal
  ├─ czsc_output     → CandidateSignal
  ├─ wyckoff_output  → CandidateSignal
  ├─ ntf_output      → CandidateSignal
  ├─ alpha_output    → CandidateSignal
  └─ 聚合 → TradingSignal 列表
      └─ SignalArbitrator.arbitrate()
           └─ 最终 TradingSignal (含 action, confidence, quantity)
```

---

## 5. 关键观察

### 5.1 架构风险

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R3-1 | **双缓存路径**: Regime/NTF wrapper 用旧版 `_market_cache` dict，新版 `AnalysisService._run_regime/_run_ntf` 用 `MarketLevelCache` 类 | `regime_analysis_engine.py:58-76`, `analysis_service_v2.py:370-410` | Wrapper 层的缓存路径可能被绕过或产生不一致 |
| R3-2 | **私有方法跨层耦合**: 所有 wrapper 引擎调用 `self.orchestrator._generate_cache_key()`, `_get_cached_result()`, `_set_cached_result()` — 依赖 AnalysisService 内部实现 | 全部 7 个 wrapper | 重构风险: 修改 AnalysisService 内部方法需同步 7 个 wrapper |
| R3-3 | **报告引擎从未被调用**: `engine_factory.py` 注册了 `report` 引擎 (`ReportGeneratorEngine`)，但 `_run_engines()` 中未调用 | `services/analysis/`, `analysis_service_v2.py` | 死代码 |
| R3-4 | **FsmAnalysisEngine 适配器未被新流程使用**: 旧 FSM 引擎只通过 `AnalysisService._factory.fsm` 暴露，新流程在 `_make_decision()` 中直接调用 `self.brain.make_decision()` | `services/analysis/fsm_analysis_engine.py` | 潜在的死代码路径 |
| R3-5 | **DecisionBrain 硬编码依赖**: `DecisionBrain.__init__()` 中使用 `HistoricalSimulationRisk` 和 `PositionSizer` 作为默认值 | `brain/fsm/fsm.py:278-285` | 违反 DI 原则，难以单元测试 |
| R3-6 | **`ctx.name` 未定义**: `_check_buy_blockers()` 和 `_check_sell_conditions()` 中引用 `ctx.name`，但 `MarketSignalContext` 数据类没有 `name` 字段 | `brain/fsm/fsm.py:410,469` | 运行时可能抛出 AttributeError |

### 5.2 设计亮点

| # | 亮点 | 位置 |
|---|------|------|
| S3-1 | **Veto-Scoring 架构**: 否决条件 (FROZEN/LPPL Danger) 优先级高于评分 | `brain/fsm/fsm.py:550-600` |
| S3-2 | **状态持久化**: 磁盘 JSON + FileLock 保障重启恢复 | `brain/fsm/fsm.py:710-766` |
| S3-3 | **市场级缓存**: Regime/NTF 只需计算一次，全市场共享 (24h TTL) | `analysis_service_v2.py:370-430` |
| S3-4 | **回路熔断**: 当日跌幅 -5% 时触发 `CIRCUIT_BREAK`，恢复后自动回到 IDLE | `brain/fsm/fsm.py:571-597` |
| S3-5 | **Symbol 切换自动重置**: FSM 状态在分析不同股票时自动从 IDLE 开始 | `brain/fsm/fsm.py:556` |
| S3-6 | **Look-ahead Bias 修复**: 盘中模式使用昨日收盘数据计算 MA | `brain/fsm/fsm.py:136-140` |
| S3-7 | **可恢复异常集**: 7-8 种异常的统一捕获，避免引擎崩溃导致全局失败 | 所有 wrapper |

### 5.3 引擎执行顺序依赖

```
regime ──────┐
lppl  ──────┤
ntf   ──────┤
czsc  ──────┼──→ DecisionBrain.make_decision()
wyckoff ────┤     (需要所有引擎输出)
alpha ──────┤
derived ────┘
```

当前没有引擎之间的数据依赖转换 (所有引擎并行就绪，仅串行执行)。`alpha` 引擎依赖于 `data_service.lake` 获取基准数据。

### 5.4 测试覆盖

| 引擎 | 测试文件 | 状态 |
|------|---------|------|
| FSM/DecisionBrain | `tests/test_fsm.py`, `tests/test_factory_core.py` | ✅ 基础覆盖 |
| LPPL | `tests/brain/test_lppl_engine.py` | ✅ |
| CZSC | `tests/brain/test_czsc_engine.py` | ✅ |
| Wyckoff | `tests/test_wyckoff_new_features.py` (12 预存失败) | ⚠️ 12 失败 |
| Regime | `tests/brain/test_regime_detector.py` | ✅ |
| Alpha | `tests/brain/test_alpha_decoupler.py` | ✅ |
| NTF | `tests/brain/test_ntf_engine.py` | ✅ |
| 仲裁器 | `tests/test_signal_arbitrator.py` (7 测试) | ✅ |

---

## 6. 建议

### P1
1. **R3-1 (双缓存)**: 统一 Regime/NTF adapter 使用 `MarketLevelCache`，废弃旧版 `_market_cache` dict
2. **R3-6 (ctx.name)**: 为 `MarketSignalContext` 添加 `name: str = ""` 字段或移除引用

### P2
3. **R3-2 (私有方法耦合)**: 为缓存操作定义 `CacheAdapterProtocol`，wrapper 通过协议而非直接调用 orchestrator
4. **R3-3 (报告引擎)**: 移除或实现实际调用

### P3
5. **R3-5 (硬编码依赖)**: DecisionBrain 完全通过构造器注入依赖
6. **R3-4 (FSM 死代码)**: 清理旧 FSM 适配器或明确弃用路径
7. **Wyckoff 12 预存失败**: 诊断并修复

---

## 7. 验证清单

- [x] 读取所有 7 services/analysis engine wrappers
- [x] 读取 engine_factory.py (9 引擎注册)
- [x] 读取 analysis_service_v2.py (完整 7 引擎编排 + 决策)
- [x] 读取 brain/fsm/fsm.py (FSM + DecisionBrain 完整逻辑)
- [x] 读取 brain/lppl/engine.py (LPPL 核心)
- [x] 读取 brain/czsc/czsc_engine.py (CZSC 核心)
- [x] 读取 brain/wyckoff/engine.py (Wyckoff v3.0 核心)
- [x] 检查 signal/arbitrator.py (信号仲裁)
- [x] 检查 shared/interfaces.py (所有引擎输出类型)
