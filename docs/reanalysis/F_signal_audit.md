# Phase F — 信号系统行为审计报告

> 日期: 2026-07-06
> **纠正 (2026-07-09)**: signal/db.py 实际测试覆盖率 93%（35 测试）— 此前 0% 报告错误。见 `test_signal_db.py`。

---

## 总结

信号链路健康度: **A-** (适配器层 A, 仲裁器 A, 数据模型 A, 质量评估 A, 持久化 B+)
signal/db.py 审计结果: **PASS** — 93% 测试覆盖率, 315 行, 35 测试
主要风险: **Adapter 层覆盖仅 29% (仅 NTFAdapter 有单元测试); Signal 模型层缺 TradingSignal 序列化方法**

---

## F1 全链路追踪

### 链路概览

```
Engine Dict Output → EngineAdapter → TradingSignal → TradingSignalCollector → SignalArbitrator → UnifiedBacktestEngine
                        ↑
                AdapterRegistry (8 engines)
```

### 8 个适配器注册

| 适配器 | 引擎 | 输入 keys | 输出 actions | 源码位置 |
|---|---|---|---|---|
| LPPLAdapter | LPPL | risk_level, confidence, bubble_confidence | SELL / HOLD | adapters.py:64 |
| CZSCAdapter | CZSC | is_3rd_buy, bi_count | BUY / HOLD | adapters.py:112 |
| WyckoffAdapter | Wyckoff | wyckoff_phase, confidence, spring, utad | BUY/SELL/HOLD | adapters.py:149 |
| FSMAdapter | FSM/DecisionBrain | final_decision, action, shares, score | BUY/SELL/HOLD (10→3 映射) | adapters.py:209 |
| RegimeAdapter | Regime | regime | HOLD (FROZEN/STRESSED → HOLD) | adapters.py:258 |
| NTFAdapter | NTF | ntf_side, ntf_intensity | SELL(≥0.6)/HOLD | adapters.py:297 |
| AlphaScoreAdapter | AlphaScore | alpha_score | BUY(>0.6)/SELL(<0.3) | adapters.py:345 |
| MAStatusAdapter | MA Status | ma_status | BUY(>)/SELL(<=) | adapters.py:381 |

### 字段映射追踪

```
Engine Output Dict
  → .adapt(raw_output, symbol, timestamp, default_shares)
    → TradingSignal(action, reason, confidence, shares, symbol, price, timestamp, metadata)
      → TradingSignalCollector.collect(data_pack) → List[TradingSignal]
        → SignalArbitrator.arbitrate(signals) → List[TradingSignal] (每日至多一个)
          → UnifiedBacktestEngine.run(signals, ...) → BacktestResult
```

### 关键发现

1. **TradingSignal (`shared/interfaces.py:148`)** 是 dataclass, 有 `from_dict` 但**无 `to_dict` 方法** — 序列化依赖外部代码
2. **TradingSignalCollector** 同时支持 `data_pack` (Dict) 和 `ResearchDataPack` 两条路径, 当前硬编码 8 个引擎提取逻辑
3. **FSMAdapter 的 `_ACTION_MAP`** 映射 10 种原始 action 到 3 种标准 action, 与 `TradingSignal.from_dict` 中的 action_map 重复定义 — 存在双源维护风险
4. **RegimeAdapter** 仅输出 HOLD (FROZEN/STRESSED → HOLD, NORMAL → None), 意味着 Regime 信号永远不产生可执行交易信号, 仅作风控屏障
5. **NTFAdapter** 对 SUPPORT 输出 HOLD + 半强度 confidence, 对 RESISTANCE 仅在高强度(≥0.6)时输出 SELL

### 适配器测试覆盖

| 适配器 | 单元测试 | 覆盖情况 |
|---|---|---|
| NTFAdapter | tests/signal/test_adapters.py | 7 个测试覆盖 |
| LPPLAdapter | 无专用测试 | 0% |
| CZSCAdapter | 无专用测试 | 0% |
| WyckoffAdapter | 无专用测试 | 0% |
| FSMAdapter | 无专用测试 | 0% |
| RegimeAdapter | 无专用测试 | 0% |
| AlphaScoreAdapter | 无专用测试 | 0% |
| MAStatusAdapter | 无专用测试 | 0% |
| TradingSignalCollector | test_e2e_pipeline.py 间接 | 3 个 E2E 测试 |

---

## F2 signal/db.py 强制审计

### 文件总览

- 文件: `src/uniquant/signal/db.py`
- 行数: 315
- 测试覆盖率: **93%** (35 测试, `test_signal_db.py`)
- 此前 0% 报告错误 — 实测已覆盖
- SQLAlchemy 版本: 使用 ORM 模式 (declarative_base + sessionmaker)

### 逐行代码审计

#### 1. 连接管理

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| 连接池 | `create_engine(connection_string, echo=False)` — 使用 SQLAlchemy 默认连接池(QueuePool, 5 连接) | 低 |
| 连接超时 | 无 `pool_timeout` 或 `connect_args` 配置 | 中 |
| 重试机制 | 无 — 数据库连接失败直接抛出异常 | 中 |
| 连接泄露 | 每次调用 `_get_session()` 在 `with` 块中创建, 上下文管理器自动关闭 | 低 |

**建议**: 添加 `pool_timeout=30`, `pool_recycle=3600`, 和生产环境重试逻辑。

#### 2. SQL 注入风险

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| 字符串拼接 | **无** — 所有查询使用 SQLAlchemy ORM 表达式 API (filter, order_by 等) | 无风险 |
| 参数化查询 | SQLAlchemy ORM 自动参数化 | 安全 |
| 原生 SQL | 未使用 `text()` 或原生 SQL | 安全 |

**结论**: 无 SQL 注入风险。

#### 3. 错误处理

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| 异常捕获 | **无** — 所有方法直接抛出异常到调用方 | 高 |
| 优雅降级 | 无 `try/except` 包裹任何数据库操作 | 高 |
| 脏数据处理 | `metadata_json` 反序列化 `json.loads` 无异常处理 | 中 |
| 枚举转换 | `SignalType(self.signal_type)`, `SignalSource(self.source)` 无异常处理 | 中 |

**具体风险点**:
- `SignalRecord.to_signal()` 的 `json.loads` 和 `SignalType/SignalSource/SignalStrength` 构造可能抛出异常
- `save_signal`/`save_batch` 的 `session.merge()` 可能因唯一键冲突等抛出异常
- `get_statistics()` 的 `func.avg` 返回 `Decimal` 类型, `round(float(avg_conf), 4)` 可能失败

**建议**: 所有公开方法包裹 `try/except`, 对枚举转换使用 `.get()` 或默认值回退。

#### 4. 事务管理

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| 显式事务 | 使用 `session.commit()` 手动提交 | 中 |
| 回滚逻辑 | **无** — `session.commit()` 失败时, session 上下文管理器会调用 `rollback()` (SQLAlchemy 默认行为) | 低 |
| 批量操作 | `save_batch` 全部在统一事务中, 原子性有保障 | 良好 |
| 部分写入 | `delete_old` 使用 `session.query.delete()` 批量删除, 未设置同步策略 | 中 |

**建议**: `delete_old` 添加 `synchronize_session='fetch'` 避免会话状态不一致。

#### 5. 并发安全

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| 线程安全 | 每个方法创建独立 Session, Session 非线程安全但每个调用独立 | 低 |
| 锁机制 | 无 | 低 |
| 死锁 | 无显式锁操作 | 低 |

**结论**: 基本线程安全, 因为每个方法调用创建独立 session。

#### 6. 数据格式

| 风险项 | 现状 | 风险等级 |
|---|---|---|
| JSON 序列化 | `json.dumps(signal.metadata, ensure_ascii=False, default=str)` — 正确 | 低 |
| JSON 反序列化 | `json.loads(self.metadata_json)` — 无异常处理 | 中 |
| 时间戳存储 | `DateTime` 列, 存储 Python `datetime` 对象 | 良好 |
| 枚举值 | 存储 `SignalType.value`/`SignalSource.value`/`SignalStrength.value` — 字符串/整数 | 良好 |
| 精度 | `Float` 列, 可能丢失 Decimal 精度 | 低 |

**建议**: `to_signal()` 的 `json.loads` 添加异常处理, 失败时返回空 dict。

### 风险汇总

| 编号 | 风险 | 严重程度 | 修复建议 |
|---|---|---|---|
| DB-1 | ~~0% 测试覆盖~~ **93%（已覆盖）** | ~~CRITICAL~~ ✅ CLOSED | 此前报告错误; 35 测试已覆盖 save/query/delete/statistics/error |
| DB-2 | 无异常处理 | HIGH | 所有公开方法包裹 `try/except`, 日志记录 |
| DB-3 | 无连接配置 | MEDIUM | 添加 `pool_timeout`, `pool_recycle` 参数 |
| DB-4 | 无重试 | MEDIUM | 添加 `tenacity` 或自定义重试装饰器 |
| DB-5 | `delete_old` 同步策略 | LOW | 添加 `synchronize_session='fetch'` |
| DB-6 | `to_signal` 枚举转换风险 | MEDIUM | 添加 `.get()` 默认值回退 |

---

## F3 信号延迟模拟

### 时间戳字段分布

信号模块共 66 处 `timestamp`/`datetime` 引用:

| 文件 | 用途 |
|---|---|
| `adapters.py` | 8 个 EngineAdapter 全部接受 `timestamp` 参数, 传递给 TradingSignal |
| `adapters.py:472-486` | `TradingSignalCollector` 支持 `bar_date`(优先) 和 `timestamp`(fallback) |
| `arbitrator.py:109` | 按 `sig.timestamp.date()` 分组, 支持 `timestamp=None` 归入 `"unknown"` |
| `models.py:124` | `Signal.timestamp` 默认 `get_time_provider().now()` |
| `models.py:155-174` | `to_dict`/`from_dict` 使用 `isoformat()`/`fromisoformat()` |
| `normalizer.py:94-281` | 4 个归一化器使用 `raw_signal.get("timestamp", get_time_provider().now())` |
| `quality.py:199` | `_OutcomeRecord.timestamp` 默认 `get_time_provider().now()` |
| `db.py:52` | `SignalRecord.timestamp` 列, 有索引 |

### 延迟/超时处理

**延迟/超时机制: 完全不存在。**

- `rg "delay|latency|timeout" src/uniquant/signal/` 返回 0 条结果
- 信号模块无任何延迟模拟、超时处理、或过期重试机制
- 信号过期仅通过 `Signal.expiration` 字段, 由 `Signal.is_expired()` 检查

### 时间模型评估

| 方面 | 评分 | 依据 |
|---|---|---|
| 时间戳传递 | A | 全链路传递, adapters → collector → arbitrator 均支持 |
| 时间分组 | A | Arbitrator 按日期分组, 支持 None 回退 |
| 延迟模拟 | F | 无任何延迟/超时/抖动处理 |
| 过期机制 | B | `expiration` 字段存在, 但仅在 `Signal` 模型层, 未在仲裁或执行层应用 |

---

## F4 信号质量开关验证

### 质量评估模块

文件: `src/uniquant/signal/quality.py` (289 行, 93% 测试覆盖)

| 组件 | 功能 | 覆盖 |
|---|---|---|
| `SignalQualityMetrics` | 质量指标数据类 (precision, recall, F1, accuracy, hit_rate, profit_factor, sharpe_ratio) | OK |
| `SignalQualityAssessor` | 评估单个信号命中/未命中, 批处理命中率, 精确率/召回率 | OK |
| `SignalQualityTracker` | 持续追踪, 按来源/类型/全局查询 | OK |

### 质量过滤开关

在 `SignalArbitrator` 中 (`arbitrator.py:154-169`):

```python
if self._quality_threshold > 0.0:
    for sig in actionable:
        oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)
        if oos_r2 < self._quality_threshold and sig.action == "SELL":
            # 拒绝
```

- **默认阈值**: 0.3 (通过 `quality_threshold` 参数控制)
- **作用范围**: 仅对 SELL 信号生效, 检查 `metadata.out_of_sample_r_squared`
- **默认行为**: 当 `out_of_sample_r_squared` 不存在时, 默认 1.0 (通过), 确保向前兼容
- **测试覆盖**: `test_quality_threshold_filters_low_oos_r2_sell` 和 `test_quality_threshold_passes_high_oos_r2_sell` 在 `test_signal_arbitrator.py:58-75`

### 评估

| 方面 | 评分 | 依据 |
|---|---|---|
| 质量过滤 | B+ | 仅对 SELL 有效, BUY 信号无质量过滤 |
| 元数据依赖 | B | 依赖 `out_of_sample_r_squared`, 不是所有引擎都提供 |
| 测试覆盖 | A | 2 个专用测试, PASS |
| 事后评估 | A | `SignalQualityAssessor` + `SignalQualityTracker` 完整 |

---

## F5 Arbitrator 规则验证

### 仲裁规则统计

| 规则 | 优先级 | 描述 | 代码位置 | 测试覆盖 |
|---|---|---|---|---|
| R0: 质量阈值 | 0 | 过滤 OOS R² < threshold 的 SELL 信号 | `arbitrator.py:154-169` | 2 个测试 ✓ |
| R1: SELL 优先 | 1 | 存在 SELL 时, BUY 全部被否决 | `arbitrator.py:172-186` | 4 个测试 ✓ |
| R2: 最高置信度 | 2 | 同方向取最高 confidence | `arbitrator.py:189-203` | 3 个测试 ✓ |
| R3: 引擎优先级 | 3 | LPPL > FSM > CZSC > Wyckoff > Regime > NTF > Alpha > MA | `arbitrator.py:206-213` | 1 个测试 ✓ |

### 候选信号仲裁 (`arbitrate_candidates`)

| 规则 | 优先级 | 描述 | 测试覆盖 |
|---|---|---|---|
| P1: DecisionOutput | 1 | FORCE_WAIT/CIRCUIT_BREAK → HOLD; FORCE_EXIT → SELL; BUY+shares → BUY | 5 个测试 ✓ |
| P2: SELL 优先 | 2 | 同 `arbitrate` 的 SELL 优先 | 1 个测试 ✓ |
| P3: FSM BUY | 3 | FSM BUY 直接通过 (无需 sizer) | 1 个测试 ✓ |
| P4: 非 FSM BUY + sizer | 4 | 非 FSM BUY 需要 PositionSizerProtocol; 无 sizer 则拒绝 | 3 个测试 ✓ |
| P5: 默认 HOLD | 5 | 无匹配规则 → HOLD | 2 个测试 ✓ |

### 测试文件

| 文件 | 测试类 | 测试数 |
|---|---|---|
| `tests/signal/test_arbitrator.py` | TestSignalArbitrator (17), TestSignalArbitratorCandidateSignals (9) | 26 |
| `tests/test_signal_arbitrator.py` | TestArbitrateBasic (5), TestArbitrateCandidates (3), TestArbitrateCandidatesSizer (4), TestCandidateWithDecisionOutput (5), TestArbitrationLog (2) | 19 |

**总计: 45 个测试, 92% 代码覆盖率** — 仲裁器是信号系统中测试最充分的模块。

### 引擎优先级矩阵

```python
ENGINE_PRIORITY = {
    "lppl": 0,    # 最高
    "fsm": 1,
    "czsc": 2,
    "wyckoff": 3,
    "regime": 4,
    "ntf": 5,
    "alpha_score": 6,
    "ma_status": 7,  # 最低
}
```

---

## F6 信号序列化测试

### TradingSignal 序列化

| 方法 | 存在 | 位置 |
|---|---|---|
| `TradingSignal.from_dict()` | ✓ | `shared/interfaces.py:166` |
| `TradingSignal.to_dict()` | **✗** | 不存在 |

### Signal 模型序列化

| 方法 | 存在 | 位置 |
|---|---|---|
| `Signal.to_dict()` | ✓ | `signal/models.py:145` |
| `Signal.from_dict()` | ✓ | `signal/models.py:164` |
| 往返测试 | ✓ | `tests/test_signal.py:53` |

### 序列化评估

| 方面 | 评分 | 依据 |
|---|---|---|
| `Signal` 模型 | A | 完整的 `to_dict`/`from_dict` + 往返测试 |
| `TradingSignal` | B+ | 有 `from_dict` 但无 `to_dict`; `from_dict` 有 action 映射 |
| `ResearchDataPack` | A | 有 `to_dict`/`from_dict` |
| `CandidateSignal` | C | 无序列化方法 (frozen dataclass) |
| `DecisionOutput` | C | 有 `to_dict` 但无 `from_dict` |
| JSON 兼容性 | B | 使用 `isoformat()` 处理 datetime, 未处理 `pd.DataFrame` 序列化 |

---

## 补充发现

### 代码重复

`FSMAdapter._ACTION_MAP` (`adapters.py:216`) 和 `TradingSignal.from_dict` (`shared/interfaces.py:169`) 维护了相同的 action 映射表。这是两个独立维护的副本, 存在不一致风险。

### 信号模块 __init__.py 延迟导入

`__init__.py` 对 `adapters`, `models`, `normalizer`, `aggregator`, `quality` 使用 `try/except` 包裹导入, 静默吞掉 `ImportError`。`db.py` 更是延迟到 `get_db_class()` 函数中。这使 `import uniquant.signal` 可能部分失败而不报错。

### 测试覆盖率

| 模块 | 行覆盖 | 状态 |
|---|---|---|
| `signal/__init__.py` | 54% | 部分 |
| `signal/adapters.py` | 29% | 不足 (仅 NTFAdapter 有测试) |
| `signal/aggregator.py` | 88% | 良好 |
| `signal/arbitrator.py` | 92% | 优秀 |
| `signal/db.py` | 93% | ✅ 此前报告 0% 错误 |
| `signal/models.py` | 97% | 优秀 |
| `signal/normalizer.py` | 84% | 良好 |
| `signal/quality.py` | 93% | 优秀 |

---

## 建议优先级

| 优先级 | 建议 | 影响 |
|---|---|---|
| ~~P0~~ ✅ | ~~为 `signal/db.py` 编写完整测试~~ **已完成** | 93% 覆盖, 35 测试 — 此前 0% 报告错误 |
| P1 | 为所有 8 个适配器添加单元测试 | 当前仅 NTFAdapter 有测试 |
| P2 | 消除 `_ACTION_MAP` 重复定义 | 防止双源背离 |
| P3 | 为 `TradingSignal` 添加 `to_dict()` 方法 | 完善序列化链 |
| P4 | 添加信号延迟模拟/超时处理 | 支持时间敏感场景 |
| P5 | 为 `to_signal()` 添加异常安全处理 | 防止 DB 反序列化崩溃 |
| P6 | 为 BUY 信号添加质量过滤 | 当前仅 SELL 有质量门控 |

---

## 当前测试状态

```
tests/signal/test_arbitrator.py       ... PASS (26 tests)
tests/signal/test_adapters.py         ... PASS (7 tests)

tests/test_signal.py                  ... PASS (26 tests)
tests/test_signal_arbitrator.py       ... PASS (19 tests)

总计: 78 个信号系统测试, 全部通过
```

---

## ANALYSIS COMPLETE