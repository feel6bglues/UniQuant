# signal -- 信号系统

> **状态:** ✅ 已就绪 | **当前文件:** 9 | **说明:** 8个Adapter + Arbitrator + 归一化/聚合/质量模块全部运行中

`uniquant.signal` 包实现了统一的信号建模、归一化、聚合、质量评估和持久化流水线，约 906 LOC。该包是连接 brain 层（LPPL/Wyckoff/CZSC/NTF/FSM 等引擎）与 risk/hands 层的桥梁：brain 产出原始信号 -> signal 归一化为标准 `Signal` -> 聚合为共识 -> 评估质量 -> 持久化存储。

---

## 信号模型

`models.py` 定义了信号系统的全部数据结构。

### SignalType 枚举（27 种信号类型，9 大类）

| 类别 | 信号类型 |
|------|----------|
| 趋势 | `TREND_BULLISH`, `TREND_BEARISH`, `TREND_NEUTRAL` |
| 动量 | `MOMENTUM_OVERBOUGHT`, `MOMENTUM_OVERSOLD`, `MOMENTUM_DIVERGENCE` |
| 波动 | `VOLATILITY_BREAKOUT`, `VOLATILITY_CONTRACTION` |
| 量能 | `VOLUME_SURGE`, `VOLUME_CLIMAX` |
| 形态 | `PATTERN_BREAKOUT`, `PATTERN_REVERSAL`, `PATTERN_CONTINUATION` |
| LPPL | `LPPL_BUBBLE`, `LPPL_CRASH`, `LPPL_NEGATIVE_BUBBLE` |
| Wyckoff | `WYCKOFF_ACCUMULATION`, `WYCKOFF_DISTRIBUTION`, `WYCKOFF_SPRING`, `WYCKOFF_UTAD`, `WYCKOFF_LPS`, `WYCKOFF_SOW` |
| 缠论 | `CZSC_BI_END`, `CZSC_ZHONGSHU_3RD`, `CZSC_TREND_EXHAUST` |
| 复合 | `COMPOSITE_CONSENSUS`, `COMPOSITE_DIVERGENCE` |

### SignalSource 枚举（10 种信号来源）

`LPPL`, `WYCKOFF`, `CZSC`, `NTF`, `FSM`, `REGIME`, `INDICATOR`, `SCREENER`, `FACTOR`, `ENSEMBLE`

### SignalStrength 枚举（4 个强度等级）

`WEAK`, `MODERATE`, `STRONG`, `VERY_STRONG`

支持 `>=` 比较运算符，用于按强度筛选。

### Signal dataclass

信号的核心数据结构，包含以下字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | `str` | UUID4 | 唯一标识 |
| `symbol` | `str` | `""` | 证券代码 |
| `signal_type` | `SignalType` | `TREND_NEUTRAL` | 信号类型 |
| `source` | `SignalSource` | `INDICATOR` | 信号来源 |
| `direction` | `int` | `0` | 方向：1=看多, -1=看空, 0=中性 |
| `strength` | `SignalStrength` | `MODERATE` | 信号强度 |
| `confidence` | `float` | `0.5` | 置信度 [0, 1] |
| `timestamp` | `datetime` | `now()` | 生成时间 |
| `expiration` | `Optional[datetime]` | `None` | 过期时间 |
| `price` | `float` | `0.0` | 触发价格 |
| `value` | `float` | `0.0` | 信号值 |
| `metadata` | `dict[str, Any]` | `{}` | 附加元数据 |
| `parent_id` | `Optional[str]` | `None` | 父信号 ID |

方法：`is_expired()`, `is_bullish()`, `is_bearish()`, `to_dict()`

### SignalBatch

批量信号容器，提供按类型/来源/强度/方向的过滤方法：

- `add(signal)` -- 添加信号
- `by_type(signal_type)` / `by_source(source)` / `by_strength(min_strength)` / `by_direction(direction)`
- `bullish()` / `bearish()` / `neutral()` -- 快捷方向过滤
- `average_confidence()` -- 批次平均置信度
- 支持 `len()` 和 `[]` 索引

### SignalConsensus

共识结果数据结构：

- `consensus_direction` -- 共识方向
- `consensus_confidence` -- 共识置信度
- `agreement_ratio` -- 一致性比例
- `total_sources` / `agreeing_sources` -- 总来源数/一致来源数
- `is_strong_consensus(threshold=0.75)` -- 判断是否为强共识

### AggregatedSignal

聚合后的信号，包含 `contributing_signals`（贡献信号列表）、`sources`（来源集合）、`agreement_ratio`（一致性比例）、`weighted_score`（加权得分）。

---

## 信号归一化

`normalizer.py` 定义了信号归一化框架，将各引擎的原始输出转换为标准 `Signal` 对象。

### SignalNormalizer (ABC)

抽象基类，声明两个方法：
- `normalize(raw_signal: dict) -> Signal` -- 单条归一化（抽象方法）
- `normalize_batch(raw_signals: list[dict]) -> list[Signal]` -- 批量归一化

### 内置归一化器

| 归一化器 | 来源 | 类型映射 |
|----------|------|----------|
| `LPPLSignalNormalizer` | `SignalSource.LPPL` | bubble -> `LPPL_BUBBLE`, crash -> `LPPL_CRASH`, negative_bubble/anti_bubble -> `LPPL_NEGATIVE_BUBBLE` |
| `WyckoffSignalNormalizer` | `SignalSource.WYCKOFF` | accumulation/distribution/spring/utad/lps/sow -> 对应 Wyckoff 类型 |
| `IndicatorSignalNormalizer` | `SignalSource.INDICATOR` | 基于关键词匹配（overbought/oversold/divergence/breakout/surge/climax） |
| `CZSCSignalNormalizer` | `SignalSource.CZSC` | bi_end -> `CZSC_BI_END`, zhongshu_3rd -> `CZSC_ZHONGSHU_3RD`, trend_exhaust -> `CZSC_TREND_EXHAUST` |

所有归一化器共享 `_compute_strength(confidence)` 静态方法：
- confidence >= 0.8 -> `VERY_STRONG`
- confidence >= 0.6 -> `STRONG`
- confidence >= 0.4 -> `MODERATE`
- 其他 -> `WEAK`

### SignalNormalizerRegistry

注册表模式，管理来源到归一化器的映射：

```python
registry = SignalNormalizerRegistry()
registry.register(SignalSource.LPPL, LPPLSignalNormalizer())
signal = registry.normalize(SignalSource.LPPL, raw_dict)
signals = registry.normalize_batch(SignalSource.LPPL, raw_list)
```

未注册来源的信号会创建默认 `Signal` 对象（保留 raw_signal 为 metadata）。

`create_default_registry()` 工厂函数创建包含全部 4 个内置归一化器的注册表。

---

## 信号聚合

`aggregator.py` 实现多信号融合，支持 4 种聚合方法。

### SignalAggregationMethod 枚举

| 方法 | 说明 |
|------|------|
| `WEIGHTED_AVERAGE` | 加权平均（默认）：按来源权重 * 置信度计算加权方向 |
| `MAJORITY_VOTE` | 多数表决：看多/看空信号数投票 |
| `MAX_CONFIDENCE` | 最大置信度：选取置信度最高的信号 |
| `CONSENSUS_THRESHOLD` | 共识阈值：一致性比例 >= 0.6 时取共识方向 |

### SignalAggregator

核心聚合器类：

- `set_weight(source, weight)` / `get_weight(source)` -- 设置/获取来源权重（默认 1.0）
- `aggregate(signals) -> AggregatedSignal` -- 聚合信号列表
- `aggregate_by_type(signals) -> dict[SignalType, AggregatedSignal]` -- 按信号类型分组聚合
- `calculate_consensus(signals, threshold=0.6) -> SignalConsensus` -- 计算信号共识

### TimeWindowAggregator

时间窗口聚合器：

- 构造参数：`window`（默认 5 分钟）
- `add(signal)` -- 将信号加入缓冲区
- `flush() -> list[AggregatedSignal]` -- 清除过期信号，对当前窗口内的信号按类型聚合

### SourceWeightManager

来源权重管理器，支持基于绩效的自适应权重更新：

- `set_weight(source, weight)` -- 手动设置权重
- `get_weight(source)` -- 获取权重（默认 1.0）
- `update_weights(performance: dict[SignalSource, float])` -- 根据绩效归一化更新权重（最低 0.1）

---

## 信号质量评估

`quality.py` 提供信号质量的事后评估能力。

### SignalQualityMetrics dataclass

质量指标数据结构：

| 字段 | 说明 |
|------|------|
| `precision` | 精确率 |
| `recall` | 召回率 |
| `f1_score` | F1 分数 |
| `accuracy` | 准确率 |
| `average_lead_time` | 平均提前时间（小时） |
| `hit_rate` | 命中率 |
| `false_positive_rate` | 假阳性率 |
| `sample_size` | 样本量 |
| `average_confidence` | 平均置信度 |
| `profit_factor` | 盈利因子 |
| `sharpe_ratio` | 夏普比率 |

### SignalQualityAssessor

静态方法集，对信号进行事后评估：

- `assess(signal, subsequent_prices, lookahead=20)` -- 评估单个信号质量。对看多信号计算未来 lookahead 天内最高价收益，对看空信号计算最低价收益。命中标准：看多 +1%，看空 -1%。
- `calculate_hit_rate(signals, price_data, lookahead=20)` -- 批量计算命中率
- `calculate_accuracy(signals, actual_directions)` -- 计算方向准确率
- `calculate_precision_recall(signals, actual_outcomes)` -- 计算精确率/召回率/F1

### SignalQualityTracker

持续追踪信号质量的跟踪器：

- `record_outcome(signal_id, outcome, source, signal_type)` -- 记录信号结果
- `get_source_quality(source)` -- 按来源查询质量
- `get_type_quality(signal_type)` -- 按信号类型查询质量
- `get_overall_quality()` -- 全局质量
- `summary()` -- 生成完整质量报告（包含 overall + 每个 source + 每个 type）

---

## 信号持久化

`db.py` 使用 SQLAlchemy 实现信号的关系数据库存储。

### SignalRecord (ORM 模型)

映射到 `signals` 表，字段与 `Signal` dataclass 一一对应。`symbol` 和 `timestamp` 建立索引。`metadata` 存储为 JSON 列。

### SignalDatabase

```python
db = SignalDatabase(connection_string="sqlite:///signals.db")
```

主要方法：

| 方法 | 说明 |
|------|------|
| `save_signal(signal)` | 保存单个信号，返回 ID |
| `save_batch(batch)` | 批量保存 SignalBatch |
| `get_by_id(signal_id)` | 按 ID 查询 |
| `query_by_symbol(symbol, start, end, limit=1000)` | 按证券代码查询，按时间倒序 |
| `query_by_source(source, start, end, limit=100)` | 按信号来源查询 |
| `query_by_type(signal_type, limit=100)` | 按信号类型查询 |
| `get_recent_signals(minutes=60)` | 获取最近 N 分钟内的信号 |
| `get_statistics()` | 统计信息：总数、按来源/类型分布、平均置信度、唯一证券数 |
| `delete_old(before)` | 删除指定时间之前的旧信号 |

默认使用 SQLite，可通过 `connection_string` 切换到其他数据库。
