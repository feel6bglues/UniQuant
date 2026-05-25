# 信号类型完整参考

本文档基于 `uniquant.signal.models` 和 `uniquant.signal.normalizer` 模块，详细描述 UniQuant 系统中所有信号类型、来源、强度等级及归一化映射规则。

---

## SignalType 枚举

`SignalType` 定义于 `src/uniquant/signal/models.py`，使用 `auto()` 自动编号。共 27 个成员，按功能分为 9 个类别。

### 趋势类 (3)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `TREND_BULLISH` | 趋势看多 | 趋势 | INDICATOR / FSM / REGIME | +1 |
| `TREND_BEARISH` | 趋势看空 | 趋势 | INDICATOR / FSM / REGIME | -1 |
| `TREND_NEUTRAL` | 趋势中性 | 趋势 | 任意（默认值） | 0 |

`TREND_NEUTRAL` 是 `Signal` 数据类的 `signal_type` 默认值，也是各归一化器在无法匹配输入类型时的兜底值。

### 动量类 (3)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `MOMENTUM_OVERBOUGHT` | 超买 | 动量 | INDICATOR | -1 |
| `MOMENTUM_OVERSOLD` | 超卖 | 动量 | INDICATOR | +1 |
| `MOMENTUM_DIVERGENCE` | 动量背离 | 动量 | INDICATOR | 视 value 正负 |

### 波动率类 (2)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `VOLATILITY_BREAKOUT` | 波动率突破 | 波动率 | INDICATOR | 视 value 正负 |
| `VOLATILITY_CONTRACTION` | 波动率收缩 | 波动率 | INDICATOR / REGIME | 0 |

### 成交量类 (2)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `VOLUME_SURGE` | 放量突破 | 成交量 | INDICATOR / NTF | 视 value 正负 |
| `VOLUME_CLIMAX` | 量能高潮 | 成交量 | INDICATOR / NTF | 视 value 正负 |

### 形态类 (3)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `PATTERN_BREAKOUT` | 形态突破 | 形态 | SCREENER / INDICATOR | +1 |
| `PATTERN_REVERSAL` | 形态反转 | 形态 | SCREENER / INDICATOR | 视上下文 |
| `PATTERN_CONTINUATION` | 形态延续 | 形态 | SCREENER / INDICATOR | 继承前趋势 |

### LPPL 类 (3)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `LPPL_BUBBLE` | LPPL 泡沫 | LPPL | LPPL | +1 |
| `LPPL_CRASH` | LPPL 崩盘 | LPPL | LPPL | -1 |
| `LPPL_NEGATIVE_BUBBLE` | LPPL 负泡沫 | LPPL | LPPL | +1 |

LPPL 归一化器中 `LPPL_BUBBLE` 和 `LPPL_NEGATIVE_BUBBLE` 默认方向为 +1，`LPPL_CRASH` 默认方向为 -1。若原始信号显式提供 `direction` 字段，则覆盖默认值。

### Wyckoff 类 (6)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `WYCKOFF_ACCUMULATION` | 威科夫吸筹 | Wyckoff | WYCKOFF | +1 |
| `WYCKOFF_DISTRIBUTION` | 威科夫派发 | Wyckoff | WYCKOFF | -1 |
| `WYCKOFF_SPRING` | 威科夫弹簧 | Wyckoff | WYCKOFF | +1 |
| `WYCKOFF_UTAD` | 威科夫 UTAD | Wyckoff | WYCKOFF | -1 |
| `WYCKOFF_LPS` | 威科夫 LPS | Wyckoff | WYCKOFF | +1 |
| `WYCKOFF_SOW` | 威科夫 SOW | Wyckoff | WYCKOFF | -1 |

方向规则来自 `WyckoffSignalNormalizer.normalize()`：`ACCUMULATION`、`SPRING`、`LPS` 为看多方向 (+1)，其余为看空方向 (-1)。

### CZSC 类 (3)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `CZSC_BI_END` | 缠论笔终结 | CZSC | CZSC | 由原始信号决定 |
| `CZSC_ZHONGSHU_3RD` | 缠论中枢三买/三卖 | CZSC | CZSC | 由原始信号决定 |
| `CZSC_TREND_EXHAUST` | 缠论趋势力竭 | CZSC | CZSC | 由原始信号决定 |

CZSC 类信号的方向完全依赖原始信号中的 `direction` 字段，归一化器不做默认推断。

### 复合类 (2)

| 枚举名 | 中文名 | 类别 | 典型来源 | 方向 |
|---|---|---|---|---|
| `COMPOSITE_CONSENSUS` | 复合共识 | 复合 | ENSEMBLE | 由聚合结果决定 |
| `COMPOSITE_DIVERGENCE` | 复合分歧 | 复合 | ENSEMBLE | 0 |

---

## SignalSource 枚举

`SignalSource` 定义了信号的产生来源，共 10 个成员。

| 枚举名 | 中文描述 | 对应 brain 模块 |
|---|---|---|
| `LPPL` | Log-Periodic Power Law 泡沫检测引擎 | `brain.lppl_engine` |
| `WYCKOFF` | 威科夫量价分析引擎 | `brain.wyckoff_engine` |
| `CZSC` | 缠中说禅笔段中枢引擎 | `brain.czsc_engine` |
| `NTF` | 非线性趋势跟随引擎 | `brain.ntf_engine` |
| `FSM` | 有限状态机决策引擎 | `brain.fsm_engine` |
| `REGIME` | 市场状态（regime）检测器 | `brain.regime_detector` |
| `INDICATOR` | 传统技术指标（RSI、MACD、布林带等） | `brain.indicator_engine` |
| `SCREENER` | 选股筛选器 | `brain.screener` |
| `FACTOR` | 多因子模型 | `brain.factor_engine` |
| `ENSEMBLE` | 集成/聚合层 | `brain.ensemble` |

---

## SignalStrength 枚举

`SignalStrength` 定义了信号的四级强度，使用 `auto()` 编号，数值递增。

| 枚举名 | 中文名 | auto() 值 | 含义 |
|---|---|---|---|
| `WEAK` | 弱 | 1 | 置信度 < 0.4 |
| `MODERATE` | 中等 | 2 | 0.4 <= 置信度 < 0.6 |
| `STRONG` | 强 | 3 | 0.6 <= 置信度 < 0.8 |
| `VERY_STRONG` | 极强 | 4 | 置信度 >= 0.8 |

### 比较逻辑

`SignalStrength` 重载了 `__ge__` 运算符，基于 `auto()` 数值进行比较：

```python
def __ge__(self, other):
    if self.__class__ is other.__class__:
        return self.value >= other.value
    return NotImplemented
```

这使得 `SignalBatch.by_strength(min_strength)` 中的 `s.strength >= min_strength` 比较合法。例如：

```python
SignalStrength.STRONG >= SignalStrength.MODERATE  # True
SignalStrength.WEAK >= SignalStrength.STRONG       # False
```

置信度到强度的映射由 `LPPLSignalNormalizer._compute_strength()` 方法统一实现，所有归一化器共享该逻辑：

```python
@staticmethod
def _compute_strength(confidence: float) -> SignalStrength:
    if confidence >= 0.8:
        return SignalStrength.VERY_STRONG
    elif confidence >= 0.6:
        return SignalStrength.STRONG
    elif confidence >= 0.4:
        return SignalStrength.MODERATE
    return SignalStrength.WEAK
```

---

## Signal 数据结构

`Signal` 是所有信号的统一数据载体，定义为 `@dataclass`，包含 13 个字段。

| 字段名 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `id` | `str` | `uuid.uuid4()` | 信号唯一标识符，自动生成 UUID |
| `symbol` | `str` | `""` | 股票代码，如 `"000001.SZ"` |
| `signal_type` | `SignalType` | `TREND_NEUTRAL` | 信号类型枚举 |
| `source` | `SignalSource` | `INDICATOR` | 信号来源枚举 |
| `direction` | `int` | `0` | 方向：+1 看多，-1 看空，0 中性 |
| `strength` | `SignalStrength` | `MODERATE` | 信号强度等级 |
| `confidence` | `float` | `0.5` | 置信度，范围 [0.0, 1.0] |
| `timestamp` | `datetime` | `datetime.now()` | 信号生成时间戳 |
| `expiration` | `Optional[datetime]` | `None` | 信号过期时间，`None` 表示不过期 |
| `price` | `float` | `0.0` | 信号关联的价格 |
| `value` | `float` | `0.0` | 信号原始数值（如 LPPL 拟合值、CZSC 分数） |
| `metadata` | `dict[str, Any]` | `{}` | 额外元数据字典 |
| `parent_id` | `Optional[str]` | `None` | 父信号 ID，用于追踪信号衍生关系 |

### 实例方法

- `is_expired() -> bool`：检查信号是否已过期（`expiration` 为 `None` 时返回 `False`）
- `is_bullish() -> bool`：`direction > 0`
- `is_bearish() -> bool`：`direction < 0`
- `to_dict() -> dict[str, Any]`：序列化为字典，`timestamp` 和 `expiration` 转为 ISO 格式字符串

---

## SignalBatch

`SignalBatch` 是信号的批量容器，支持按多种维度进行过滤。

| 字段名 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `signals` | `list[Signal]` | `[]` | 信号列表 |
| `source` | `SignalSource` | `INDICATOR` | 批次来源 |
| `timestamp` | `datetime` | `datetime.now()` | 批次时间戳 |
| `metadata` | `dict[str, Any]` | `{}` | 批次元数据 |

### 过滤方法

| 方法 | 签名 | 描述 |
|---|---|---|
| `by_type` | `by_type(signal_type: SignalType) -> list[Signal]` | 按信号类型过滤 |
| `by_source` | `by_source(source: SignalSource) -> list[Signal]` | 按信号来源过滤 |
| `by_strength` | `by_strength(min_strength: SignalStrength) -> list[Signal]` | 按最低强度过滤，使用 `>=` 比较 |
| `by_direction` | `by_direction(direction: int) -> list[Signal]` | 按方向过滤（+1 / 0 / -1） |
| `bullish` | `bullish() -> list[Signal]` | 等价于 `by_direction(1)` |
| `bearish` | `bearish() -> list[Signal]` | 等价于 `by_direction(-1)` |
| `neutral` | `neutral() -> list[Signal]` | 等价于 `by_direction(0)` |

### 辅助方法

- `add(signal: Signal) -> None`：追加信号到批次
- `average_confidence() -> float`：计算批次内所有信号的平均置信度，空批次返回 0.0
- `__len__() -> int`：返回信号数量
- `__getitem__(index: int) -> Signal`：按索引访问信号

---

## SignalConsensus 与 AggregatedSignal

### SignalConsensus

`SignalConsensus` 描述多个信号源之间的共识状态。

| 字段名 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `signals` | `list[Signal]` | `[]` | 参与共识的信号列表 |
| `consensus_direction` | `int` | `0` | 共识方向 |
| `consensus_confidence` | `float` | `0.0` | 共识置信度 |
| `agreement_ratio` | `float` | `0.0` | 一致性比率，范围 [0.0, 1.0] |
| `total_sources` | `int` | `0` | 参与的信号源总数 |
| `agreeing_sources` | `int` | `0` | 方向一致的信号源数量 |
| `timestamp` | `datetime` | `datetime.now()` | 共识计算时间 |

关键方法：

```python
def is_strong_consensus(self, threshold: float = 0.75) -> bool:
    return self.agreement_ratio >= threshold and self.consensus_confidence >= threshold
```

当一致性比率和置信度同时达到阈值（默认 0.75）时，视为强共识。

### AggregatedSignal

`AggregatedSignal` 是多信号聚合后的结果。

| 字段名 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `signal_type` | `SignalType` | （必填） | 聚合后的信号类型 |
| `direction` | `int` | `0` | 聚合方向 |
| `confidence` | `float` | `0.0` | 聚合置信度 |
| `contributing_signals` | `list[Signal]` | `[]` | 参与聚合的原始信号 |
| `sources` | `set[SignalSource]` | `set()` | 贡献的信号源集合 |
| `agreement_ratio` | `float` | `0.0` | 一致性比率 |
| `weighted_score` | `float` | `0.0` | 加权综合分数 |
| `timestamp` | `datetime` | `datetime.now()` | 聚合时间 |

`AggregatedSignal` 通常由 `ENSEMBLE` 来源的聚合层生成，其 `contributing_signals` 保留了原始信号的完整引用，便于回溯分析。

---

## SignalAlert

`SignalAlert` 用于将信号包装为告警事件。

| 字段名 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `signal` | `Signal` | （必填） | 触发告警的信号对象 |
| `alert_type` | `str` | `"info"` | 告警级别，如 `"info"`、`"warning"`、`"critical"` |
| `message` | `str` | `""` | 告警消息文本 |
| `triggered_at` | `datetime` | `datetime.now()` | 告警触发时间 |
| `acknowledged` | `bool` | `False` | 是否已确认 |

方法：

- `acknowledge() -> None`：将 `acknowledged` 设置为 `True`，表示告警已被处理。

---

## 归一化映射表

归一化器定义于 `src/uniquant/signal/normalizer.py`，负责将各引擎的原始输出转换为统一的 `Signal` 对象。所有归一化器均继承自抽象基类 `SignalNormalizer`。

### LPPLSignalNormalizer

来源：`SignalSource.LPPL`

| 原始信号 `type` 值 | 映射到 SignalType | 默认方向 |
|---|---|---|
| `"bubble"` | `LPPL_BUBBLE` | +1 |
| `"crash"` | `LPPL_CRASH` | -1 |
| `"negative_bubble"` | `LPPL_NEGATIVE_BUBBLE` | +1 |
| `"anti_bubble"` | `LPPL_NEGATIVE_BUBBLE` | +1 |
| 其他 / 空 | `TREND_NEUTRAL` | 视 direction 字段 |

原始信号字段映射：
- `symbol` -> `Signal.symbol`
- `confidence` -> 经 `_compute_strength()` 转换为 `Signal.strength`，同时 `clamp(0.0, 1.0)` 后赋值给 `Signal.confidence`
- `price` -> `Signal.price`
- `lppl_value` -> `Signal.value`
- `direction`（可选）-> 若提供则覆盖默认方向
- 其余字段 -> `Signal.metadata`

### WyckoffSignalNormalizer

来源：`SignalSource.WYCKOFF`

| 原始信号 `phase` 值 | 映射到 SignalType | 方向 |
|---|---|---|
| `"accumulation"` | `WYCKOFF_ACCUMULATION` | +1 |
| `"distribution"` | `WYCKOFF_DISTRIBUTION` | -1 |
| `"spring"` | `WYCKOFF_SPRING` | +1 |
| `"utad"` | `WYCKOFF_UTAD` | -1 |
| `"lps"` | `WYCKOFF_LPS` | +1 |
| `"sow"` | `WYCKOFF_SOW` | -1 |
| 其他 / 空 | `TREND_NEUTRAL` | -1（按 else 分支） |

方向判定逻辑：

```python
direction = 1 if signal_type in (
    SignalType.WYCKOFF_ACCUMULATION, SignalType.WYCKOFF_SPRING, SignalType.WYCKOFF_LPS
) else -1
```

原始信号字段映射：
- `symbol` -> `Signal.symbol`
- `confidence` -> 经 `_compute_strength()` 转换为 `Signal.strength`
- `price` -> `Signal.price`
- `wyckoff_score` -> `Signal.value`
- 其余字段 -> `Signal.metadata`

### IndicatorSignalNormalizer

来源：`SignalSource.INDICATOR`

使用关键词匹配，依次检查原始信号 `type` 字段中是否包含以下关键词：

| 关键词 | 映射到 SignalType |
|---|---|
| `"overbought"` | `MOMENTUM_OVERBOUGHT` |
| `"oversold"` | `MOMENTUM_OVERSOLD` |
| `"divergence"` | `MOMENTUM_DIVERGENCE` |
| `"breakout"` | `VOLATILITY_BREAKOUT` |
| `"surge"` | `VOLUME_SURGE` |
| `"climax"` | `VOLUME_CLIMAX` |
| 均不匹配 | `TREND_NEUTRAL` |

方向判定逻辑：

```python
direction = 1 if value > 0 else (-1 if value < 0 else raw_signal.get("direction", 0))
```

即优先根据 `value` 正负判定方向，`value` 为零时回退到原始信号的 `direction` 字段。

原始信号字段映射：
- `symbol` -> `Signal.symbol`
- `confidence` -> 经 `_compute_strength()` 转换为 `Signal.strength`
- `price` -> `Signal.price`
- `value` -> `Signal.value`
- `direction`（回退值）-> `Signal.direction`
- 其余字段 -> `Signal.metadata`

### CZSCSignalNormalizer

来源：`SignalSource.CZSC`

| 原始信号 `type` 值 | 映射到 SignalType |
|---|---|
| `"bi_end"` | `CZSC_BI_END` |
| `"zhongshu_3rd"` | `CZSC_ZHONGSHU_3RD` |
| `"trend_exhaust"` | `CZSC_TREND_EXHAUST` |
| 其他 / 空 | `TREND_NEUTRAL` |

方向完全由原始信号的 `direction` 字段决定（默认为 0）。

原始信号字段映射：
- `symbol` -> `Signal.symbol`
- `confidence` -> 经 `_compute_strength()` 转换为 `Signal.strength`
- `price` -> `Signal.price`
- `czsc_value` -> `Signal.value`
- `direction` -> `Signal.direction`
- 其余字段 -> `Signal.metadata`

### SignalNormalizerRegistry

`SignalNormalizerRegistry` 管理所有归一化器的注册和分发。`create_default_registry()` 预注册了以下四个归一化器：

```python
def create_default_registry() -> SignalNormalizerRegistry:
    registry = SignalNormalizerRegistry()
    registry.register(SignalSource.LPPL, LPPLSignalNormalizer())
    registry.register(SignalSource.WYCKOFF, WyckoffSignalNormalizer())
    registry.register(SignalSource.INDICATOR, IndicatorSignalNormalizer())
    registry.register(SignalSource.CZSC, CZSCSignalNormalizer())
    return registry
```

对于未注册归一化器的信号源（如 `NTF`、`FSM`、`REGIME`、`SCREENER`、`FACTOR`、`ENSEMBLE`），`normalize()` 方法会生成一个带有默认值的 `Signal` 对象，其 `metadata` 包含完整的原始信号字典。
