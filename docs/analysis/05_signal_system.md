# Stage 5 — 信号系统深度分析

> **日期**: 2026-06-29 | **状态**: ✅ 完成
> **范围**: `signal/` (8 文件, 2,669 LOC), `shared/interfaces.py` (TradingSignal, CandidateSignal)
> **测试**: `tests/signal/test_arbitrator.py` (27), `tests/signal/test_adapters.py`, `tests/test_signal.py` (43)

---

## 1. 总览

### 信号流水线

```
Brain 引擎输出 (Dict/typed output)
        │
        ▼
  TradingSignalCollector.collect(data_pack)
        │
        ├─ 8 EngineAdapters (适配器模式)
        │   ├─ LPPLAdapter
        │   ├─ CZSCAdapter
        │   ├─ WyckoffAdapter
        │   ├─ FSMAdapter
        │   ├─ RegimeAdapter
        │   ├─ NTFAdapter
        │   ├─ AlphaScoreAdapter
        │   └─ MAStatusAdapter
        │
        ▼
  List[TradingSignal]            ← 标准信号列表
        │
        ▼
  SignalArbitrator.arbitrate()   ← SELL 优先仲裁
        │
        ▼
  Final TradingSignal(s)         ← 每日至多一个
        │
        ▼
  → UnifiedBacktestEngine       ← 回测执行
```

### 并行信号流水线 (第二路径)

```
Candidates (各引擎原始输出)
        │
        ▼
  SignalArbitrator.arbitrate_candidates()
        │
        ├─ Priority 1: DecisionOutput 硬约束
        │   ├─ FORCE_WAIT / CIRCUIT_BREAK → HOLD
        │   └─ FORCE_EXIT → SELL
        │
        ├─ Priority 2: SELL > BUY
        │
        ├─ Priority 3: FSM BUY → 直接通过
        │
        └─ Priority 4: 非-FSM BUY → PositionSizer 校验
```

### 标准归一化流水线 (旧路径)

```
Engine Raw Output
        │
        ▼
  SignalNormalizer (4 种实现)
        ├─ LPPLSignalNormalizer
        ├─ WyckoffSignalNormalizer
        ├─ IndicatorSignalNormalizer
        └─ CZSCSignalNormalizer
        │
        ▼
  Signal (标准数据类)
        │
  SignalAggregator (4 种方法)
        ├─ WEIGHTED_AVERAGE
        ├─ MAJORITY_VOTE
        ├─ MAX_CONFIDENCE
        └─ CONSENSUS_THRESHOLD
        │
        ▼
  AggregatedSignal / SignalConsensus
        │
  SignalQualityAssessor
        │
  SignalRecord (SQLAlchemy ORM → SQLite)
```

---

## 2. 文件清单

| 文件 | LOC | 职责 |
|------|-----|------|
| `signal/__init__.py` | 113 | 包导出, 4 个子模块延迟导入 |
| `signal/models.py` | 280 | Signal, SignalBatch, SignalConsensus, AggregatedSignal + 5 枚举 |
| `signal/adapters.py` | 604 | 8 个 EngineAdapter + AdapterRegistry + TradingSignalCollector |
| `signal/arbitrator.py` | 386 | SignalArbitrator (2 个仲裁入口) + ArbitrationLog/Report |
| `signal/normalizer.py` | 315 | 4 个 SignalNormalizer + SignalNormalizerRegistry |
| `signal/aggregator.py` | 367 | 4 聚合方法 + SourceWeightManager + TimeWindowAggregator |
| `signal/quality.py` | 289 | SignalQualityAssessor + SignalQualityMetrics + SignalQualityTracker |
| `signal/db.py` | 315 | SQLAlchemy ORM (SignalRecord) + SignalRepository |

---

## 3. 数据模型 (`models.py`)

### 枚举类

| 枚举 | 值数 | 用途 |
|------|------|------|
| `SignalType` | 27 | 9 大类覆盖趋势/动量/波动/量能/形态/LPPL/Wyckoff/CZSC/复合 |
| `SignalSource` | 10 | LPPL, Wyckoff, CZSC, NTF, FSM, Regime, Indicator, Screener, Factor, Ensemble |
| `SignalStrength` | 4 | WEAK(1), MODERATE(2), STRONG(3), VERY_STRONG(4) |

### 核心数据类

```python
@dataclass
class Signal:
    signal_type: SignalType = TREND_NEUTRAL
    source: SignalSource = INDICATOR
    symbol: str = ""
    id: str = uuid4
    direction: int = 0       # 1=看多, -1=看空, 0=中性
    strength: SignalStrength = MODERATE
    confidence: float = 0.5  # [0, 1]
    timestamp: datetime = now
    expiration: datetime | None
    price: float = 0.0
    value: float = 0.0
    metadata: dict = {}
    parent_id: str | None

@dataclass
class SignalBatch:         # 容器 + 过滤 (by_type, by_source, by_strength, by_direction)
@dataclass
class SignalConsensus:      # 共识方向/置信度/一致性比例
@dataclass
class AggregatedSignal:     # 聚合后的信号 + 贡献信号列表
```

---

## 4. 适配器层 (`adapters.py`)

### 8 个适配器

| 适配器 | 输入 keys | 输出规则 |
|--------|-----------|----------|
| `LPPLAdapter` | risk_level, confidence | Danger→SELL, Warning/Warning→HOLD |
| `CZSCAdapter` | is_3rd_buy, bi_count | 三买→BUY (conf=0.5+bi*0.05), 其他→None |
| `WyckoffAdapter` | phase, confidence, spring, utad | Spring+accumulation→BUY, UTAD+distribution→SELL |
| `FSMAdapter` | action, final_decision | BUY/SELL→同动作, HOLD→HOLD |
| `RegimeAdapter` | regime | 冻结→SELL, 正常→HOLD |
| `NTFAdapter` | ntf_side, ntf_intensity | RESISTANCE+intensity≥0.6→SELL, SUPPORT→HOLD |
| `AlphaScoreAdapter` | alpha_score | >0.6→BUY, <0.3→SELL |
| `MAStatusAdapter` | ma_status | ">"→BUY, "<="→SELL |

### TradingSignalCollector

```python
collect(data_pack) → List[TradingSignal]
  # 从 data_pack 按 key 提取 8 个引擎输出 → 适配器转换
  # 发布 SignalGenerated 事件到 EventBus
```

### 适配器注册表

```python
class AdapterRegistry:
    _adapters: Dict[str, EngineAdapter]  # 8 个适配器
    create_default_registry() → 注册全部 8 个
```

---

## 5. 仲裁器 (`arbitrator.py`)

### 引擎优先级 (数值 = 低优先)

```python
ENGINE_PRIORITY = {
    "lppl": 0, "fsm": 1, "czsc": 2, "wyckoff": 3,
    "regime": 4, "ntf": 5, "alpha_score": 6, "ma_status": 7,
}
```

### 仲裁入口 1: `arbitrate(TradingSignal[])`

```
_pick_winner(day_signals, symbol, date_key):
  │
  ├─ 0. 质量阈值过滤 (OOS R² < 0.3 的 SELL 被拒)
  │
  ├─ 1. SELL 优先规则 → 有 SELL 则选最高置信度 SELL
  │
  ├─ 2. 同方向取最高置信度
  │
  └─ 3. 引擎优先级 → 选择优先级最高的信号
```

### 仲裁入口 2: `arbitrate_candidates(CandidateSignal[])`

```
  Priority 1: DecisionOutput 硬约束
    ├─ FORCE_WAIT / CIRCUIT_BREAK → HOLD (空结果)
    ├─ FORCE_EXIT → SELL (强制卖出)
    └─ BUY + shares > 0 → 直接通过
  Priority 2: SELL > BUY
  Priority 3: FSM BUY → 直接通过
  Priority 4: 非-FSM BUY → PositionSizer 校验/计算仓位
```

### 仲裁日志

```python
@dataclass class ArbitrationLog:    # arbitrate() 使用
    symbol, date, total_signals, selected_action, selected_reason,
    selected_confidence, conflicts_resolved, rejection_reasons

@dataclass class ArbitrationReport:  # arbitrate_candidates() 使用
    symbol, date, candidates_count, final_action, final_reason,
    final_confidence, veto_chain, rejected
```

---

## 6. 归一化器 (`normalizer.py`)

### 4 个归一化实现

| 归一化器 | 类型映射 | 强度计算 |
|----------|----------|----------|
| `LPPLSignalNormalizer` | bubble/crash/negative_bubble → SignalType | confidence → strength |
| `WyckoffSignalNormalizer` | accumulation/distribution/spring/utad/lps/sow | confidence → strength |
| `IndicatorSignalNormalizer` | rsi/macd/bb/ma → TREND/MOMENTUM/VOLATILITY | 规则计算 |
| `CZSCSignalNormalizer` | 一买/二买/一卖/二卖/三买/三卖 | bi_count 加权 |

### SignalNormalizerRegistry

```python
registry = SignalNormalizerRegistry()
registry.register("lppl", LPPLSignalNormalizer())
registry.get("lppl").normalize(raw_signal) → Signal
```

---

## 7. 聚合器 (`aggregator.py`)

### 4 种聚合方法

| 方法 | 策略 | 适用场景 |
|------|------|----------|
| `WEIGHTED_AVERAGE` | 加权平均 | 多来源连续信号 |
| `MAJORITY_VOTE` | 多数表决 | 分类决策 (BUY/SELL/HOLD) |
| `MAX_CONFIDENCE` | 最高置信度 | 单个高可信引擎为主 |
| `CONSENSUS_THRESHOLD` | 共识阈值 | 需要 75% 以上一致 |

### SourceWeightManager

- `set_weight(source, weight)`: 手动设置
- `update_weights(performance)`: 基于绩效归一化
- `get_weight(source)`: 默认 1.0，最低 0.1

### TimeWindowAggregator

- `aggregate(signals, window=timedelta(hours=4))`: 时间窗口内聚合
- 支持滑动窗口多信号融合

---

## 8. 质量评估 (`quality.py`)

### SignalQualityAssessor

```python
assess(signal, subsequent_prices, lookahead=20) → bool | None
  # 看多: max(subsequent_prices) > trigger_price * 1.01 → True
  # 看空: min(subsequent_prices) < trigger_price * 0.99 → True
```

### SignalQualityMetrics

```python
precision, recall, f1_score, accuracy, average_lead_time,
hit_rate, false_positive_rate, sample_size, average_confidence,
profit_factor, sharpe_ratio
```

### SignalQualityTracker

- `record_signal(signal)`: 记录信号
- `record_outcome(signal_id, outcome)`: 记录结果
- `get_metrics(source=None, type=None)`: 按来源/类型查询质量指标
- `get_summary()`: 汇总报告

---

## 9. 持久化 (`db.py`)

### ORM 模型

```python
class SignalRecord(Base):  # 表: signals
    id, symbol, signal_type, source, direction, strength,
    confidence, timestamp, expiration, price, value,
    metadata_json, parent_id
```

### SignalRepository

```python
save(signal)                    # 持久化
find_by_symbol(symbol, limit)   # 按股票查询
find_by_time_range(start, end)  # 按时间查询
find_by_type(signal_type)       # 按类型查询
get_statistics(source, days)    # 统计
delete_old(before)              # 清理
```

### SQLAlchemy 优雅降级

```python
try:
    from sqlalchemy import ...
    _SQLA_AVAILABLE = True
except ImportError:
    Base = None
    _SQLA_AVAILABLE = False
```

---

## 10. 关键观察

### 架构风险

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R5-1 | **两套并行信号体系**: `adapters.py` (TradingSignalCollector → TradingSignal) 和 `normalizer.py` (→ Signal) 运行独立的信号转换路径 | `adapters.py`, `normalizer.py` | 运维复杂度, 信号流分裂, 需保持两套逻辑同步 |
| R5-2 | **TradingSignalCollector 适配 key 名不匹配**: `_extract_lppl()` 期望 `risk` + `bubble_confidence`, 但 `LPPLOutput` 输出 `risk_level` | `adapters.py:540-548` | 下游 data_pack 结构调整可能导致信号遗漏 |
| R5-3 | **仲裁器依赖字符串匹配**: `_get_engine_priority()` 通过 `reason.lower()` 包含匹配判断引擎 | `arbitrator.py:235-240` | 脆弱, 改变 reason 字符串格式会破坏仲裁 |
| R5-4 | **质量评估器需要事后价格数据**: `assess()` 依赖 `subsequent_prices` 列表, 在线交易场景不可用 | `quality.py:59-60` | 仅适用于回测/离线分析 |
| R5-5 | **归一化+聚合+质量+DB 路径无运行时调用**: `normalizer`, `aggregator`, `quality`, `db` 4 个模块在主流程中未被调用 | 全部 4 文件 | 可能是死代码或仅用于离线研究 |
| R5-6 | **SQLAlchemy 可选依赖**: 未安装时 `SignalRecord` 类不存在, `from .db import SignalRecord` 会失败 | `db.py:30-37` | import 时可能 AttributeError |

### 设计亮点

| # | 亮点 | 位置 |
|---|------|------|
| S5-1 | **双仲裁入口**: `arbitrate()` 处理 TradingSignal, `arbitrate_candidates()` 处理 CandidateSignal+DecisionOutput — 覆盖两代接口 | `arbitrator.py` |
| S5-2 | **SELL 优先 + 质量门**: OOS R² < 0.3 的低质量 SELL 信号被过滤 | `arbitrator.py:130-148` |
| S5-3 | **Veto 链记录**: 仲裁报告包含完整的 veto_chain 和 rejection_reasons | `arbitrator.py:270-280` |
| S5-4 | **8 适配器注册表**: 可扩展的适配器模式, 新引擎只需注册新 Adapter | `adapters.py:480-520` |
| S5-5 | **SourceWeightManager 自适应**: 基于绩效的权重更新 | `aggregator.py:55-80` |
| S5-6 | **Signal 数据类完整**: 27 种类型, 10 个来源, 4 级强度 — 覆盖全场景 | `models.py` |

### 信号流对比

| 维度 | TradingSignalCollector (主) | Normalizer + Aggregator (副) |
|------|---------------------------|------------------------------|
| 输入 | `Dict[str, Any]` data_pack | `Dict[str, Any]` raw signal |
| 输出 | `TradingSignal` | `Signal` |
| 适配器数 | 8 | 4 |
| 聚合 | 仲裁器 (SELL优先) | 4 种聚合方法 |
| 质量 | 无 | SignalQualityAssessor |
| 持久化 | 无 | SQLAlchemy ORM |
| 运行时调用 | 是 (Pipeline/TradingSignalCollector) | 否 |

### 测试覆盖

| 测试文件 | 函数数 | 覆盖 |
|----------|--------|------|
| `tests/signal/test_arbitrator.py` | 27 | 空信号/单信号/SELL优先/质量门/仲裁日志/候选仲裁 |
| `tests/signal/test_adapters.py` | 未知 | 适配器单元测试 |
| `tests/test_signal.py` | 43 | 模型创建/序列化/批次过滤/归一化 |
| `tests/test_research_pipeline_checkpoint.py` | 7 | Pipeline 仲裁集成 |

---

## 11. 建议

### P1
1. **R5-1 (信号体系分裂)**: 统一两条信号路径 — 选择 TradingSignalCollector 为主路径，正常化/聚合/质量评估可叠加为可选中间件

### P2
2. **R5-3 (字符串匹配仲裁)**: 在 `TradingSignal` 中添加 `source` 字段替代基于 reason 字符串的引擎识别
3. **R5-2 (key 名不匹配)**: 统一 `LPPLOutput.risk_level` vs data_pack `risk` 的 key 名

### P3
4. **R5-4 (质量评估离线)**: 保持离线, 文档标注适用场景
5. **R5-5 (死代码路径)**: 确认 normalizer/aggregator/quality/db 是否被使用, 否则标记弃用
6. **R5-6 (SQLAlchemy 可选)**: `db.py` 中所有 `from .db import SignalRecord` 需用 try/except 包裹

---

## 12. 验证清单

- [x] 读取 `signal/__init__.py` (4 子模块延迟导入)
- [x] 读取 `signal/models.py` (5 枚举 + 4 数据类)
- [x] 读取 `signal/adapters.py` (8 EngineAdapter + Registry + Collector)
- [x] 读取 `signal/arbitrator.py` (2 仲裁入口 + Priority 规则)
- [x] 读取 `signal/normalizer.py` (4 Normalizer + Registry)
- [x] 读取 `signal/aggregator.py` (4 聚合方法 + SourceWeightManager)
- [x] 读取 `signal/quality.py` (QualityAssessor + Metrics + Tracker)
- [x] 读取 `signal/db.py` (SQLAlchemy ORM + Repository + 降级)
- [x] 检查 `shared/interfaces.py` TradingSignal / CandidateSignal 定义
- [x] 检查 `shared/interfaces.py` DecisionOutput (仲裁器硬约束)
- [x] 检查测试覆盖
