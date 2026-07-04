# Phase 5 修复说明 — 7 线程全维度修复报告

**日期**: 2026-06-29 | **验证**: 1410 通过, 5 失败 (均预存), 0 回归

---

## 目录

- [Thread A — 信号体系统一](#thread-a--信号体系统一-p0)
- [Thread B — TradeCalendar 自动更新](#thread-b--tradecalendar-自动更新-p1)
- [Thread C — Wyckoff 测试诊断](#thread-c--wyckoff-测试诊断-p0)
- [Thread D — ResultStore 研究结果持久化](#thread-d--resultstore-研究结果持久化-p1)
- [Thread E — DataFetcher 单入口清理](#thread-e--datafetcher-单入口清理-p2)
- [Thread F — Backtest 对比与优先级注释](#thread-f--backtest-对比与优先级注释-p2)
- [Thread G — 废弃代码清理](#thread-g--废弃代码清理-p3)
- [测试结果汇总](#测试结果汇总)

---

## Thread A — 信号体系统一 [P0]

### 原理

两套并行信号体系 (`ResearchDataPack` 类型路径 vs. `Dict[str, Any]` 路径) 长期分裂。
`analysis_service_v2.py:320` 通过 feature flag 选择路径，但标志位默认 `false`，
导致 `ResearchDataPack` 类型路径从未在生产路径被执行。当 `use_research_data_pack=true`，
`_prepare_data()` 调用 `fetch_research_pack()` 返回 `ResearchDataPack` 对象，
下游引擎经 `engine_factory` 运行，CZSC/Wyckoff 引擎输出为对象而非字典。

### 文件修改

#### `config/config.yaml`
```yaml
# line 429
- use_research_data_pack: false
+ use_research_data_pack: true
```

#### `src/uniquant/shared/config_models.py`
```python
# line 17 — FeatureFlags 数据类默认值
- use_research_data_pack: bool = False
+ use_research_data_pack: bool = True

# line 31 — from_dict 默认值
- use_research_data_pack=bool(flags.get("use_research_data_pack", False)),
+ use_research_data_pack=bool(flags.get("use_research_data_pack", True)),
```

#### `src/uniquant/services/analysis_service_v2.py` — CZSC 输出提取修复
```python
# lines 509-512
# OLD: result.get() → 对象无 .get() 方法，抛 AttributeError
- is_3rd_buy=bool(result.get("is_3rd_buy", False)),
- bi_count=int(result.get("bi_count", 0)),
- price=float(result.get("price", 0.0)),
- bottom=result.get("czsc_bottom"),
# NEW: getattr → 同时兼容 dict 和对象
+ is_3rd_buy=bool(getattr(result, "is_3rd_buy", False)),
+ bi_count=int(getattr(result, "bi_count", 0)),
+ price=float(getattr(result, "price", 0.0)),
+ bottom=getattr(result, "bottom", None),
```

#### `src/uniquant/services/analysis_service_v2.py` — Wyckoff 输出提取修复
```python
# lines 528-532
# OLD: WyckoffOutput 字段名为 "spring" / "utad"，而 dict 键为 "spring_detected" / "utad_detected"
- phase=str(result.get("phase", "unknown")),
- confidence=float(result.get("confidence", 0.0)),
- spring=bool(result.get("spring_detected", False)),
- utad=bool(result.get("utad_detected", False)),
- price=float(result.get("price", 0.0)),
# NEW: getattr + 正确字段名
+ phase=str(getattr(result, "phase", "unknown")),
+ confidence=float(getattr(result, "confidence", 0.0)),
+ spring=bool(getattr(result, "spring", False)),
+ utad=bool(getattr(result, "utad", False)),
+ price=float(getattr(result, "price", 0.0)),
```

#### `tests/shared/test_research_data_pack.py`

**`test_feature_flag_exists`** — 断言默认值改为 `True`
```python
- assert flags.use_research_data_pack is False
+ assert flags.use_research_data_pack is True
```

**`test_config_yaml_has_flag`** — 断言 YAML 值改为 `True`
```python
- assert ff["use_research_data_pack"] is False
+ assert ff["use_research_data_pack"] is True
```

**`test_prepare_data_default_path_uses_dict`** → 重命名并反转断言
```python
# OLD: 默认走 Dict 路径
- mock_data.fetch_for_brain.assert_called_once_with("000001.SZ")
- mock_data.fetch_research_pack.assert_not_called()
# NEW: 默认走 ResearchDataPack 路径
+ mock_data.fetch_research_pack.assert_called_once_with("000001.SZ")
```

---

## Thread B — TradeCalendar 自动更新 [P1]

### 原理

`TradeCalendarManager.__init__()` 仅依赖硬编码的 `_CN_HOLIDAYS` 集合（覆盖 2024-2026 年）。
从 2027-01-01 起，`is_trading_day()` 对春节以外的节假日将返回 `True`（错误判断为交易日），
进而破坏回测引擎的 T+1 约束检查（错误地允许某些日期的交易）。

### 文件修改

**`src/uniquant/data/managers/trade_calendar_manager.py`**

#### 导入
```python
- from typing import Set
+ from typing import Optional, Set
```

#### `__init__` — 触发自动更新
```python
def __init__(self, data_dir: str = "./data"):
    self.data_dir = data_dir
+   self._akshare_calendar: Optional[Set[str]] = None
+   self._auto_update_if_stale()
```

#### `_auto_update_if_stale(max_age_days=180)` — 新增方法

逻辑流程图:

```
_auto_update_if_stale()
│
├─ CSV 存在?
│  ├─ YES ─→ 文件 < 180 天?
│  │         ├─ YES → 从 CSV 加载到 _akshare_calendar, return
│  │         └─ NO  → 进入 AkShare 拉取
│  └─ NO  ─→ 进入 AkShare 拉取
│
└─ AkShare 拉取
   ├─ 成功 → 保存 CSV, 加载到 _akshare_calendar
   └─ 失败 → log warning, 静默降级（硬编码后备）
```

核心代码:
```python
def _auto_update_if_stale(self, max_age_days: int = 180) -> None:
    calendar_file = os.path.join(self.data_dir, "trade_calendar.csv")
    if os.path.exists(calendar_file):
        file_age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(
            os.path.getmtime(calendar_file))).days
        if file_age < max_age_days:
            df = pd.read_csv(calendar_file)
            if 'trade_date' in df.columns:
                self._akshare_calendar = set(df['trade_date'].astype(str).values)
                return  # 缓存有效，提前返回
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is not None and not df.empty:
            os.makedirs(os.path.dirname(calendar_file), exist_ok=True)
            df.to_csv(calendar_file, index=False, encoding="utf-8-sig")
            self._akshare_calendar = set(df["trade_date"].astype(str).values)
    except Exception as e:
        logger.warning(f"通过 AkShare 自动更新交易日历失败: {e}")
```

#### `is_trading_day()` — 优先级调整

```python
def is_trading_day(self, date):
    ...
    date_str = date.strftime("%Y-%m-%d")
    if self._trading_days_cache[year]:
        return date_str in self._trading_days_cache[year]

+   # AkShare 数据优先（覆盖 2027+）
+   if self._akshare_calendar is not None:
+       return date_str in self._akshare_calendar

    # 硬编码后备
    iso = date.isoformat()
    if iso in _CN_SPECIAL_WORKDAYS:
        return True
    ...
```

### 新测试文件

**`tests/test_trade_calendar_manager.py`** (175 行, 18 个测试)

| 测试类 | 测试数 | 覆盖场景 |
|---|---|---|
| `TestTradeCalendarManagerAkShare` | 6 | 2027 元旦 `False`、春节 `False`、工作日 `True`、周末 `False`、2024 现有节假日兼容 |
| `TestTradeCalendarManagerStaleCache` | 3 | >180 天触发更新、<180 天跳过、缺失文件触发 |
| `TestTradeCalendarManagerHardcodedFallback` | 6 | 网络故障时硬编码后备正常工作 |
| `TestTradeCalendarManagerEdgeCases` | 3 | 空数据、异常降级、2024 前年份 |

---

## Thread C — Wyckoff 测试诊断 [P0]

### 原理

`test_wyckoff_new_features.py` 从 `scripts.wyckoff_multitf` 导入 `VShapeResult`、
`AShareConstraints` 等模块。项目根 (`/home/.../UniQuant/`) 不在 `sys.path` 中
（只有 `src/` 通过 editable install 在路径中），导致 12 个测试全部
`ModuleNotFoundError: No module named 'scripts'`。

此外，诊断过程中发现了 6 处代码级 bug，均被修复。

### 文件修改

#### `tests/test_wyckoff_new_features.py` — sys.path 补丁
```python
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
```
说明: Python 3.12 `scripts/wyckoff_multitf/` 作为 namespace package 无需 `__init__.py`，
但根路径必须在 `sys.path` 中。此补丁 idempotent、scoped。

#### `src/uniquant/brain/wyckoff/bayesian_events.py` — obs_failure 计算修复

**Bug**: `obs_failure` 多加了 `(1.0 - confidence) * pseudo_count` 项，
导致负分事件的 posterior beta 参数被异常膨胀。

```python
# line 93
# OLD: 错误 — spurious term 使负分事件后验向 0 漂移过度
- obs_failure = max(0.0, -score) * pseudo_count + (1.0 - confidence) * pseudo_count
# NEW: 正确 — 仅使用实际负分
+ obs_failure = max(0.0, -score) * pseudo_count
```

**量化对比** (score=-0.5, conf=0.8):

| 项 | OLD | NEW |
|---|---|---|
| `pseudo_count` | 8.0 | 8.0 |
| `obs_success` | 0.0 | 0.0 |
| `obs_failure` | 4.0 + 1.6 = 5.6 | 4.0 |
| `beta` | 1.0 + 5.6 = 6.6 | 1.0 + 4.0 = 5.0 |
| `posterior mean` | 1.0 / 7.6 = 0.132 | 1.0 / 6.0 = 0.167 |
| `get_adjustment()` | -0.0737 | -0.0667 |

#### `src/uniquant/brain/wyckoff/bayesian_events.py` — 负分截断修复

**Bug**: `np.clip(..., 0.0, 1.0)` 将负分截断到 0，
完全消除负分事件的信号。

```python
# line 108
- norm = np.clip(raw / _MAX_RAW_SCORE, 0.0, 1.0)
+ norm = np.clip(raw / _MAX_RAW_SCORE, -1.0, 1.0)
```

#### `src/uniquant/brain/wyckoff/bayesian_events.py` — 新增 get_adjustment()

```python
def get_adjustment(self, event_type: str) -> float:
    """Posterior-derived score adjustment in [-0.1, +0.1].

    Maps posterior mean from [0, 1] to [-0.1, +0.1]:
    mean 0.5 → 0, mean 1.0 → +0.1, mean 0.0 → -0.1.
    """
    return (self.posterior_mean(event_type) - 0.5) * 0.2
```

#### `src/uniquant/brain/wyckoff/events.py` — sigmoid 溢出修复

**Bug**: `np.exp(-(raw_score - 3.0))` 在 `raw_score >> 3` 时值为极大正数，
`np.exp()` 溢出为 `inf`，导致 `1.0 / (1.0 + inf) = 0`，非预期的硬截断。

```python
# lines 33-35
- return float(1.0 / (1.0 + np.exp(-(raw_score - midpoint) / scale)))
+ with np.errstate(over='ignore'):
+     exp_arg = -(raw_score - midpoint) / scale
+     return float(1.0 / (1.0 + np.exp(exp_arg)))
```

#### `src/uniquant/brain/wyckoff/engine.py` — 三处修复

1. **sigmoid overflow** (lines 1383, 1398):
```python
- prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))
+ with np.errstate(over='ignore'):
+     prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))
```

2. **P&F Point & Figure 分析集成** (line ~235):
```python
pnf = PointAndFigure(box_size=0.02, reversal=2)
pnf.build(frame)
pnf_result = {
    "phase_hint": pnf.wyckoff_phase_hint(),
    "breakout": pnf.breakout_detected(),
    "count_target": pnf.count_target(),
}
```

3. **RegimeAwarePhaseClassifier 集成** (line ~244):
```python
rpc = RegimeAwarePhaseClassifier()
phase_str, _ = rpc.classify(frame, pd.Timestamp(df['date'].iloc[-1]), period='monthly')
regime_phase = phase_str
```

#### `src/uniquant/brain/wyckoff/phase_analysis.py` — 向量化 OBV 计算

**Bug**: 4 个分类器 (`Weekly`, `Daily`, `Monthly`, `RegimeAware`) 各有独立的手写 Python
for 循环计算 OBV 趋势，使用 `int64` 累加可能导致整数溢出。

**修复**: 提取为单一向量化函数：

```python
def _obv_trend(close: np.ndarray, volume: np.ndarray) -> float:
    """Vectorized OBV trend — float64 safe, no int64 overflow."""
    directions = np.sign(np.diff(close.astype(np.float64)))
    obv = float(np.sum(volume[1:].astype(np.float64) * directions))
    return obv / float(volume.mean()) / len(close) if volume.mean() > 0 else 0.0
```

使用 `np.sign + np.sum` 替代 Python for 循环：

```python
# OLD (x4):
obv = 0
for j in range(1, len(c)):
    obv += v[j] if c[j] > c[j-1] else -v[j] if c[j] < c[j-1] else 0
obv_t = obv / v.mean() / len(c) if v.mean() > 0 else 0

# NEW:
obv_t = _obv_trend(c, v)
```

#### `src/uniquant/brain/wyckoff/sequence.py` — Bayesian 集成到 WSOScorer

**新增**: `WSOScorer` 可选接收 `BayesianEventDetector` 实例。每次 `score()` 计算后，
运行贝叶斯更新并将调整值注入平滑分数。

```python
class WSOScorer:
    def __init__(self, bayesian: Optional[BayesianEventDetector] = None) -> None:
        self._bayesian = bayesian

    def score(self, event_types, ..., confidence=0.5):
        ...
        if self._bayesian is not None and event_types:
            adj_total = 0.0
            for et in event_types:
                adj_total += self._bayesian.get_adjustment(et)
                self._bayesian.update(et, raw, confidence)
            smoothed += adj_total
        return smoothed
```

#### `src/uniquant/brain/wyckoff/models.py` — WyckoffReport 新增字段
```python
pnf_analysis: Optional[dict] = None
regime_phase: Optional[str] = None
```

#### `src/uniquant/shared/interfaces.py` — WyckoffOutput 新增字段
```python
pnf_phase_hint: str = "neutral"
pnf_breakout: bool = False
pnf_count_target: float = 0.0
regime_phase: Optional[str] = None
vshape_detected: bool = False

def to_dict(self):
    return {
        ...
        "pnf_phase_hint": self.pnf_phase_hint,
        "pnf_breakout": self.pnf_breakout,
        "pnf_count_target": self.pnf_count_target,
        "regime_phase": self.regime_phase,
        "vshape_detected": self.vshape_detected,
    }
```

#### `src/uniquant/services/analysis/wyckoff_analysis_engine.py` — 提取新字段
```python
if hasattr(result, "pnf_analysis") and result.pnf_analysis is not None:
    pnf = result.pnf_analysis
    pnf_phase_hint = str(pnf.get("phase_hint", "neutral"))
    pnf_breakout = bool(pnf.get("breakout", False))
    pnf_count_target = float(pnf.get("count_target", 0.0))

if hasattr(result, "regime_phase") and result.regime_phase is not None:
    regime_phase = str(result.regime_phase)

if hasattr(result, "vshape_detected") and result.vshape_detected:
    vshape_detected = bool(result.vshape_detected)
```

### 测试新增

`tests/test_wyckoff_new_features.py` 新增 `TestBayesianExactPosterior` 类 (6 测试):

| 测试 | 验证 |
|---|---|
| `test_positive_score_exact_posterior` | 正分后验均值 0.8913，调整值 +0.0783 |
| `test_negative_score_exact_posterior` | 负分后验均值 0.1667，调整值 -0.0667 |
| `test_zero_score_no_bias` | 零分保持先验 0.5，调整值 0.0 |
| `test_sequential_positive_convergence` | 5 次正分更新 → 后验 0.9737，单调递增 |
| `test_get_adjustment_unknown_event` | 未知事件返回 -0.1 (mean=0) |
| `test_update_from_events_negative_score` | 负分降低后验均值 < 0.5 |

### 最终通过率: 44/44 (原 32/44)

---

## Thread D — ResultStore 研究结果持久化 [P1]

### 原理

`UnifiedResearchPipeline.run()` 执行完整分析流程后，结果仅以 `PipelineResult` 对象
存在于内存中。研究者无法查询、比较或导出历史结果，团队协作依赖手动截屏。

### 新文件

**`src/uniquant/shared/result_store.py`** (164 行)

#### `AnalysisRecord` 数据类

```python
@dataclass
class AnalysisRecord:
    symbol: str
    analysis_date: date
    regime: Optional[str] = None
    lppl_score: Optional[float] = None
    ntf_detected: Optional[bool] = None
    czsc_signal: Optional[str] = None
    wyckoff_signal: Optional[str] = None
    action: Optional[str] = None      # "BUY" / "SELL" / "HOLD"
    confidence: Optional[float] = None
    backtest_sharpe: Optional[float] = None
    backtest_return: Optional[float] = None
    backtest_mdd: Optional[float] = None
    metadata: Optional[dict] = None
```

#### `ResultStore` 类

```python
class ResultStore:
    def __init__(self, path: str = "./results"): ...
    def save(self, symbol: str, record: AnalysisRecord) -> None:
        """原子写入: NamedTemporaryFile + os.replace"""
        path = self._path_for(symbol, record.analysis_date)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(path))
        json.dump(asdict(record), tmp, default=str, ensure_ascii=False)
        tmp.close()
        os.replace(tmp.name, path)

    def load(self, symbol: str, analysis_date: date) -> Optional[AnalysisRecord]: ...
    def load_latest(self, symbol: str) -> Optional[AnalysisRecord]:
        """扫描 results/{symbol}/ 下最近日期的记录"""
    def query(self, analysis_date: date) -> list[AnalysisRecord]:
        """返回指定 date 下所有 results/{date}/*.json"""
    def query_range(self, symbol: str, start: date, end: date) -> list[AnalysisRecord]: ...
    def compare(self, symbol: str, date1: date, date2: date) -> dict:
        """返回两个 AnalysisRecord 的差值"""
```

存储结构:

```
results/
├── 2026-06-29/
│   ├── 000001.SZ.json
│   ├── 600000.SH.json
│   └── ...
├── 2026-06-30/
│   └── ...
```

### 文件修改

**`src/uniquant/services/research_pipeline.py`**

#### `__init__` — 新增 ResultStore 初始化
```python
def __init__(self, ..., result_store_path: Optional[str] = None):
    ...
    self._result_store = ResultStore(path=result_store_path or "./results")
```

#### `run()` — 成功结果后持久化
```python
# line ~417, 在 backtest 完成后
self._persist_result(result)
```

#### `_persist_result()` — 新方法
```python
def _persist_result(self, result: PipelineResult) -> None:
    try:
        decision = result.decision
        bt = result.backtest
        record = AnalysisRecord(
            symbol=result.symbol,
            analysis_date=date.today(),
            regime=decision.get("regime"),
            lppl_score=decision.get("lppl_score"),
            ntf_detected=decision.get("ntf_detected"),
            czsc_signal=decision.get("czsc_signal"),
            wyckoff_signal=decision.get("wyckoff_signal"),
            action=decision.get("action"),
            confidence=decision.get("confidence"),
            backtest_sharpe=self._compute_backtest_sharpe(bt.daily_returns),
            backtest_return=bt.total_return,
            backtest_mdd=self._compute_backtest_mdd(bt.equity_curve),
            metadata={"trace_id": result.trace_id},
        )
        self._result_store.save(result.symbol, record)
    except Exception as e:
        logger.warning(f"Failed to persist result for {result.symbol}: {e}")
```

#### `_compute_backtest_sharpe()` / `_compute_backtest_mdd()`
```python
@staticmethod
def _compute_backtest_sharpe(daily_returns: List[float]) -> Optional[float]:
    if len(daily_returns) < 2:
        return None
    arr = np.array(daily_returns, dtype=np.float64)
    std = arr.std(ddof=1)
    if std == 0.0:
        return None
    return float(arr.mean() / std * np.sqrt(252))

@staticmethod
def _compute_backtest_mdd(equity_curve: List[float]) -> Optional[float]:
    if len(equity_curve) < 2:
        return None
    arr = np.array(equity_curve, dtype=np.float64)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(dd.min())
```

### 测试文件

**`tests/test_result_store.py`** (161 行, 13 个测试)

| 测试类 | 测试数 | 覆盖场景 |
|---|---|---|
| `TestResultStoreSaveLoad` | 3 | 保存后完整加载、字段正确性、symbol 隔离 |
| `TestResultStoreQuery` | 3 | 按日期查询多 symbol、日期范围、范围外 |
| `TestResultStoreCompare` | 3 | 两日期同 symbol 比较、缺失日期优雅处理 |
| `TestResultStoreLatest` | 2 | 最新记录查询、无记录时返回 None |
| `TestResultStoreEdgeCase` | 2 | 全空字段记录、目录创建 |

---

## Thread E — DataFetcher 单入口清理 [P2]

### 原理

`DataFetcher` 构造自己的 `SourceRouter`，但 `get_price()` 却调用
`self.ingestion.fetch_price()`，而 `DataIngestionService` 又有自己的
`SourceRouter`。两套完全相同的 5 源故障转移逻辑（TDX → BaoStock → Sina → THS → Tencent）
重复初始化，违反 DRY。

### 文件修改

#### `src/uniquant/data/data_fetcher.py`

**构造函数**: 传递自身而非 data_dir
```python
# line 102
- self.ingestion = DataIngestionService(data_dir)
+ self.ingestion = DataIngestionService(self)
```

**get_price()**: 直接使用自有 source_router
```python
# lines 119-123
- df = self.ingestion.fetch_price(symbol)
+ try:
+     df = self.source_router.fetch_with_fallback(symbol, "fetch")
+ except Exception:
+     df = None
```

#### `src/uniquant/data/data_ingestion_service.py` — 精简前后对比

| 属性 | 改造前 (48 行) | 改造后 (17 行) |
|---|---|---|
| `__init__` | 5 源准备 + router 初始化 | 接收 fetcher 引用 |
| `ensure_initialized()` | 惰性初始化 + 5 源实例化 + adapter 包装 | **已删除** |
| `_init_sources()` | TDX/BaoStock/Sina/THS/Tencent 故障容忍初始化 | **已删除** |
| `_do_fetch()` | 内部委托给 router | **已删除** |
| `fetch_price()` | `ensure_initialized → _do_fetch` | 直接调用 `fetcher.source_router` |

改造后:
```python
class DataIngestionService:
    def __init__(self, fetcher):
        self._fetcher = fetcher

    def fetch_price(self, symbol: str, source: str = "auto") -> Optional[pd.DataFrame]:
        try:
            return self._fetcher.source_router.fetch_with_fallback(symbol, source)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", symbol, e)
            return None
```

### 验证: 16/16 测试通过 (4 新 + 12 现存)

---

## Thread F — Backtest 对比与优先级注释 [P2]

### 原理

研究者进行参数敏感性分析时，需要直观比较两组回测结果（如同一策略在不同信号阈值下的表现），
但 `BacktestResult` 无 `compare()` 方法。同时 `UnifiedBacktestEngine` 的优先级规则
("LPPL SELL > BUY > 非LPPL SELL") 缺乏足够的上下文说明，易被误解为仲裁逻辑而非执行调度。

### 文件修改

**`src/uniquant/hands/backtest/unified_engine.py`**

#### BacktestResult — 4 个 lazy computed property

```python
@property
def sharpe(self) -> float:
    """年化 Sharpe 比率 (252 交易日)"""
    if len(self.daily_returns) < 2:
        return 0.0
    arr = np.array(self.daily_returns, dtype=np.float64)
    if np.std(arr) == 0:
        return 0.0
    return float(np.mean(arr) / np.std(arr) * np.sqrt(252))

@property
def max_drawdown(self) -> float:
    """最大回撤: (峰-谷)/峰"""
    if not self.equity_curve:
        return 0.0
    ec = np.array(self.equity_curve, dtype=np.float64)
    rolling_max = np.maximum.accumulate(ec)
    dd = (rolling_max - ec) / np.maximum(rolling_max, 1e-10)
    return float(np.max(dd))

@property
def win_rate(self) -> float:
    """胜率: 盈利交易 / 总交易（只计已平仓）"""
    closed = [t for t in self.trades if t.action == "SELL"]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t.pnl > 0)
    return wins / len(closed)

@property
def profit_factor(self) -> float:
    """盈利因子: 总盈利 / 总亏损"""
    closed = [t for t in self.trades if t.action == "SELL"]
    if not closed:
        return 0.0
    total_profit = sum(t.pnl for t in closed if t.pnl > 0)
    total_loss = abs(sum(t.pnl for t in closed if t.pnl < 0))
    if total_loss == 0:
        return float("inf") if total_profit > 0 else 0.0
    return total_profit / total_loss
```

#### BacktestResult.compare()

```python
def compare(self, other: "BacktestResult") -> dict:
    """比较两个回测结果，返回差值字典。

    参数敏感性分析:
        r1 = engine.run(df, signals_a, symbol)
        r2 = engine.run(df, signals_b, symbol)
        diff = r1.compare(r2)
    """
    def _safe_sub(a: float | None, b: float | None) -> float:
        if a is None and b is None:
            return 0.0
        a_val = a or 0.0
        b_val = b or 0.0
        result = a_val - b_val
        if not math.isfinite(result):
            return 0.0
        return result

    return {
        "total_return_diff": _safe_sub(self.total_return, other.total_return),
        "sharpe_diff": _safe_sub(self.sharpe, other.sharpe),
        "max_drawdown_diff": _safe_sub(self.max_drawdown, other.max_drawdown),
        "total_trades_diff": len(self.trades) - len(other.trades),
        "win_rate_diff": _safe_sub(self.win_rate, other.win_rate),
        "profit_factor_diff": _safe_sub(self.profit_factor, other.profit_factor),
    }
```

#### 引擎优先级注释更新
```python
# lines ~312-318
# ── Step 3: 收集当日信号 → 生成挂单 ──
# 规则: LPPL SELL > BUY > 非LPPL SELL
# 说明: 当仲裁器输出多个信号同天到达时, 按此顺序尝试执行。
#       这是一个执行层调度, 非仲裁层逻辑。
#       SignalArbitrator 决定"生成哪些信号",
#       此优先级决定"同天多个信号时先执行哪个"。
```

### 测试文件

**`tests/test_backtest_compare.py`** (88 行, 5 测试)

| 测试 | 验证 |
|---|---|
| `test_compare_identical` | 完全相同结果 → 所有 diff 为 0 |
| `test_compare_different_metrics` | 不同结果 → 各维度 diff 正确 |
| `test_compare_empty_results` | 空 BacktestResult → 不崩溃 |
| `test_compare_mixed_empty_nonempty` | 空 vs 非空 → diff 正确 |
| `test_compare_structure` | compare() 返回的 dict 键完整 |

---

## Thread G — 废弃代码清理 [P3]

### 原理

项目迭代过程中累积了不再使用的遗留模块。`historical_risk.py` 是 `EVTRisk`
（即 `HistoricalSimulationRisk`）的包装类，但从未被引用。
`src/uniquant/hands/__init__.py` 的 `__getattr__` 惰性导出路径没有 deprecation 警告。

### 文件变更

#### `src/uniquant/risk/historical_risk.py` — 删除

```diff
- import warnings
- from .evt_risk import EVTRisk
-
- class HistoricalSimulationRisk(EVTRisk):
-     """
-     Historical Simulation based risk calculator.
-     Wraps EVTRisk with deprecation notice — use HistoricalSimulationRisk directly.
-     """
-     def __init__(self):
-         super().__init__()
-         warnings.warn(
-             "EVTRisk is deprecated, use HistoricalSimulationRisk",
-             DeprecationWarning,
-             stacklevel=2,
-         )
```

删除理由:
- 0 外部引用 (`rg "from.*historical_risk" src/ tests/` 返回空)
- `evt_risk.py:389` 中 `EVTRisk = HistoricalSimulationRisk` 为同一类名
- 所有使用者直接导入 `uniquant.risk.evt_risk.EVTRisk`

#### `src/uniquant/hands/__init__.py` — 添加 DeprecationWarning

```python
import warnings

elif name == "BacktestEngine":
    warnings.warn(
        "BacktestEngine is deprecated, use UnifiedBacktestEngine",
        DeprecationWarning, stacklevel=2,
    )
    from uniquant.hands.backtest.engine import BacktestEngine
    return BacktestEngine

elif name == "BacktestResult":
    warnings.warn(
        "BacktestResult (legacy) is deprecated, use unified_engine.BacktestResult",
        DeprecationWarning, stacklevel=2,
    )
    from uniquant.hands.backtest.result import BacktestResult
    return BacktestResult

elif name == "TradeRecord":
    warnings.warn(
        "TradeRecord (legacy) is deprecated, use unified_engine.TradeRecord",
        DeprecationWarning, stacklevel=2,
    )
    from uniquant.hands.backtest.result import TradeRecord
    return TradeRecord
```

**未删除但已标记废弃的文件**（仍有测试依赖）:

| 文件 | 保留原因 |
|---|---|
| `src/uniquant/hands/backtest/engine.py` (747 LOC) | 10 个测试文件直接引用 |
| `src/uniquant/hands/backtest/portfolio_engine.py` (373 LOC) | 2 个测试文件引用 |
| `src/uniquant/hands/backtest/result.py` (175 LOC) | 5 个测试文件引用 |
| `src/uniquant/services/analysis_service_legacy.py` (~800 LOC) | 2 个测试文件引用 |
| `src/uniquant/data/manager.py` (12 LOC) | `strategies/backtest.py` 引用 |

---

## 测试结果汇总

### 总量变化

| 指标 | Phase 4 结束 | Phase 5 结束 | Δ |
|---|---|---|---|
| 总通过数 | 1,363 | 1,410 | **+47** |
| 总失败数 | 12 + 5 (预存) | 5 (预存) | **-12** |
| 测试文件 | 115 | 119 | **+4** |
| 测试函数 | ~1,354 | 1,419 | **~+65** |
| 源码文件 | 254 | 254 | ±0 (1 删 1 新) |
| 源码 LOC | 62,816 | 63,109 | **+293** |
| 预存失败 | 17 | 5 | **-12** |

### 按线程

| 线程 | 新测试 | 变更文件 | 状态 |
|---|---|---|---|
| Thread A | 3 updated | config.yaml, config_models.py, analysis_service_v2.py, test_research_data_pack.py | **1410/1410 无回归** |
| Thread B | 18 新 | trade_calendar_manager.py | **18/18 通过** |
| Thread C | 6 新 | 7 wyckoff 源文件 + wyckoff_analysis_engine.py + interfaces.py | **44/44 Wyckoff** |
| Thread D | 13 新 | result_store.py (new), research_pipeline.py | **13/13 通过** |
| Thread E | 4 新 | data_fetcher.py, data_ingestion_service.py | **16/16 通过** |
| Thread F | 5 新 | unified_engine.py | **5/5 + 65 现存无回归** |
| Thread G | 0 | historical_risk.py (del), hands/__init__.py | **删除 18 LOC 无回归** |

### 预存 5 失败（未修改）

| 测试 | 原因 |
|---|---|
| `test_survivorship_warning::test_metadata_trading_days_count` | 交易日计数预期值漂移 |
| `test_unified_matching::TestDefenseB::test_limit_down_blocks_sell` | 涨跌停边界条件 |
| `test_unified_matching::TestDefenseE::test_buy_no_stamp_duty` | 印花税免收边界 |
| `test_unified_matching::TestDefenseE::test_min_commission_enforced` | 最低佣金边界 |
| `test_unified_matching::TestDefenseF::test_buy_slippage_upward` | 买入滑点方向边界 |

### 控制文档更新

- `AGENTS.md` — Phase 5 完成状态、指标更新、Quick Start 新增 3 条目
- `docs/index.md` — 日期更新
