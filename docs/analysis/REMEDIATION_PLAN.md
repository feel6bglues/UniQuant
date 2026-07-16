# UniQuant 短板修复意见书

> **作者**: 量化金融架构视角 | **基于**: 8 阶段深度分析 + 代码走读
> **日期**: 2026-06-29

---

## 目录

1. [P0 — 正确性缺陷 (必须在下次迭代修复)](#p0--正确性缺陷)
2. [P1 — 架构债务 (应在 1-2 个迭代内修复)](#p1--架构债务)
3. [P2 — 研究效率 (提升研究者效能)](#p2--研究效率)
4. [P3 — 代码健康度 (长期维护)](#p3--代码健康度)
5. [修复路线图](#修复路线图)

---

## P0 — 正确性缺陷

### P0-1. 回测引擎独立仲裁导致信号覆盖 (R6-1)

**严重度**: 🔴 可能导致回测结果与仲裁结果不一致

**根因**: `UnifiedBacktestEngine.run()` (`unified_engine.py:220-250`) 在接收到 `TradingSignal[]` 后, 按内部优先级重新排序:

```python
# unified_engine.py:220-250 (实际代码)
# Priority 1: LPPL SELL
# Priority 2: BUY (position == 0)
# Priority 3: non-LPPL SELL
```

而 `SignalArbitrator.arbitrate_candidates()` (`arbitrator.py`) 使用完全不同的规则:

```
DecisionOutput 硬约束 > SELL > FSM BUY > 非-FSM BUY
```

**后果**: 仲裁器选择了 BUY, 但回测引擎内部可能因为某 LPPL 引擎发出 SELL 而覆盖为卖出。这意味着**仲裁器实际上被 bypass**。

**修复方案**:

```python
# unified_engine.py
class UnifiedBacktestEngine:
    def run(self, df, signal: TradingSignal, ...) -> BacktestResult:
        # 删除: 内部重新排序逻辑
        # 删除: LPPL SELL > BUY > non-LPPL SELL 优先级

        # 改为: 接收一个已仲裁的 TradingSignal, 严格按信号执行
        # 信号已由 SignalArbitrator 处理, 此处不应再重新排序

        # 但保留 T+1/涨跌停/停牌等执行层防线
```

**影响范围**: 5 个测试文件, ~10 个测试用例可能需要更新
**工作量**: 低 (~1 人天)

---

### P0-2. 两套信号体系导致行为分裂 (R5-1)

**严重度**: 🔴 新旧路径产生不同的 TradingSignal 对象

**根因**: `analysis_service_v2.py` 中依赖 `FeatureFlags.use_research_data_pack`:

```python
# analysis_service_v2.py (实际代码)
if self.feature_flags.use_research_data_pack:
    research_pack = self.data_service.fetch_research_pack(ticker)
else:
    data_pack = self.data_service.fetch_for_brain(ticker)  # 旧 Dict 路径
```

旧路径 (`fetch_for_brain`) 返回 `Dict[str, Any]`, 新路径返回 `ResearchDataPack`。两条路径最终通过 `TradingSignalCollector` 和旧版 `_collect_signals` 产生不同的信号。

**修复方案**:

```python
# 三步走:
# Step 1: 将 use_research_data_pack 默认改为 True
# Step 2: 移除 fetch_for_brain 的 Dict 路径
# Step 3: 移除 _collect_signals 旧方法

# config.yaml
refactoring:
  feature_flags:
    use_research_data_pack: true   # ← 改默认值
```

**注意**: Step 1 前需确保所有旧 Dict 消费者已迁移。具体检查 `data_pack["symbol"]`, `data_pack.get("stock")` 等 28 处引用。

**影响范围**: `analysis_service_v2.py`, `data_service.py`, 6 个引擎文件
**工作量**: 中 (~3 人天)

---

### P0-3. Wyckoff 12 个测试预存失败 (R3-2)

**严重度**: 🟠 测试面不纯, 隐藏未来回归风险

**根因**: 未知 — 需要排查。可能是 wyckoff_new_features 分支引入的 feature 与现有逻辑冲突。

**修复方案**:

```bash
# Step 1: 运行失败测试, 捕获精确错误
pytest tests/test_wyckoff_new_features.py -v 2>&1 | grep FAILED

# Step 2: 判断:
#   - 如果是预期行为变更: 更新 golden 基线
#   - 如果是意外回归: 修复并添加回归测试
#   - 如果是旧代码与新 feature 冲突: 用 FeatureFlags 控制

# Step 3: 修复后标记 12 个测试为 ✅
```

**影响范围**: `tests/test_wyckoff_new_features.py`
**工作量**: 低 (~0.5 人天)

---

## P1 — 架构债务

### P1-1. DataFetcher + DataIngestionService 功能重复 (R2-1)

**根因**: `DataFetcher.__init__()` 既初始化完整管道 (SourceRouter + Pipeline + Managers), 又初始化 `self.ingestion = DataIngestionService()`。后者内部再次初始化 SourceRouter, 做了重复工作。

```python
# data_fetcher.py (实际代码)
class DataFetcher:
    def __init__(self, ...):
        # 路径 A: 自己的 SourceRouter
        self.source_router = SourceRouter(self.adapters)
        self.data_cleaner = DataCleaner()
        self.data_validator = DataValidator()
        self.data_adjuster = DataAdjuster(...)

        # 路径 B: 另一个 IngestionService
        self.ingestion = DataIngestionService(data_dir)  # ← 冗余!
```

而 `get_price()` 使用 `self.ingestion.fetch_price(symbol)`, 绕过了 `DataFetcher` 自己的 SourceRouter。

**修复方案**:

```python
# data_ingestion_service.py — 精简为 DataFetcher 的薄委托层
class DataIngestionService:
    def __init__(self, data_fetcher: DataFetcher):
        self._fetcher = data_fetcher

    def fetch_price(self, symbol: str, source: str = "auto"):
        return self._fetcher.source_router.fetch_with_fallback(symbol, source)

# data_fetcher.py — 删除 self.ingestion = DataIngestionService(...)
# get_price() 直接调用 self.source_router
```

**影响范围**: 5 个测试文件 (~50 行)
**工作量**: 低 (~0.5 人天)

---

### P1-2. 6 个废弃旧文件未清理

| 文件 | LOC | 替代 | 清理风险 |
|------|-----|------|----------|
| `engine.py` | 747 | `UnifiedBacktestEngine` | 检查是否有外部引用 |
| `portfolio_engine.py` | 373 | `UnifiedBacktestEngine` | 同上 |
| `result.py` | 175 | `unified_engine.py` 内部 BacktestResult | 同上 |
| `historical_risk.py` | 18 | `EVTRisk` | 仅弃用包装 |
| `analysis_service_legacy.py` | ~800 | `AnalysisService` (v2) | 检查服务容器引用 |
| `data/manager.py` | 12 | `StorageManager` | 简单包装 |

**修复方案**:

```bash
# Step 1: 搜索所有 import 引用
rg "from.*engine import|from.*portfolio_engine|from.*result import|from.*historical_risk|from.*analysis_service_legacy|from.*manager import" src/

# Step 2: 无引用 → 直接删除
# Step 3: 有引用 → 更新 import 指向新文件, 然后删除
# Step 4: 清理 __init__.py 中的对应导出
```

**影响范围**: 约 6 个文件, ~2,100 LOC 死代码
**工作量**: 低 (~0.5 人天)

---

## P2 — 研究效率

### P2-1. 研究结果持久化 (R7-1)

**问题**: 当前分析结果仅保存在内存中 (`data_pack`, `decision`), 重启丢失。研究者无法:

- 回顾昨日分析结果
- 对比不同参数的结果
- 导出结果给团队

**修复方案**:

新增 `ResultStore` 组件:

```python
# src/uniquant/shared/result_store.py
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import pandas as pd
from datetime import date
from typing import Optional

@dataclass
class AnalysisRecord:
    symbol: str
    analysis_date: date
    regime: Optional[str] = None
    lppl_score: Optional[float] = None
    wyckoff_signal: Optional[str] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Optional[dict] = None

class ResultStore:
    def __init__(self, path: str = "./results"):
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)

    def save(self, symbol: str, record: AnalysisRecord):
        """保存单只股票的分析记录"""
        daily_dir = self._path / str(record.analysis_date)
        daily_dir.mkdir(exist_ok=True)
        filepath = daily_dir / f"{symbol}.json"
        with open(filepath, "w") as f:
            json.dump(asdict(record), f, indent=2, default=str)

    def load(self, symbol: str, analysis_date: date) -> Optional[AnalysisRecord]:
        filepath = self._path / str(analysis_date) / f"{symbol}.json"
        if not filepath.exists():
            return None
        with open(filepath) as f:
            return AnalysisRecord(**json.load(f))

    def query(self, analysis_date: date) -> list[AnalysisRecord]:
        """批量查询某日的所有分析结果"""
        daily_dir = self._path / str(analysis_date)
        if not daily_dir.exists():
            return []
        records = []
        for f in daily_dir.glob("*.json"):
            with open(f) as fh:
                records.append(AnalysisRecord(**json.load(fh)))
        return records
```

集成到 `ResearchPipeline`:

```python
# research_pipeline.py (修改点)
class ResearchPipeline:
    def run_single(self, symbol: str, ...) -> PipelineResult:
        result = self._run(symbol, ...)
        if result is not None:
            record = AnalysisRecord(
                symbol=symbol,
                analysis_date=date.today(),
                regime=result.decision.get("regime"),
                lppl_score=result.decision.get("lppl_score"),
                wyckoff_signal=result.decision.get("wyckoff"),
                decision=result.decision.get("action"),
                confidence=result.decision.get("confidence"),
            )
            self.result_store.save(symbol, record)
        return result
```

**影响范围**: 新增文件 + 修改 research_pipeline.py
**工作量**: 低 (~1 人天)

---

### P2-2. InMemoryMetricsRecorder 扩展持久化

**问题**: `InMemoryMetricsRecorder` (`observability.py`) 仅存在于进程内存, 大规模回测的性能数据无法追溯分析。

**修复方案**:

```python
# observability.py — 添加可选的持久化后端
class MetricsBackend(ABC):
    @abstractmethod
    def write(self, name: str, value: float, tags: dict[str, str]) -> None: ...

class SqliteMetricsBackend(MetricsBackend):
    def __init__(self, path: str = "./metrics/metrics.db"):
        import sqlite3
        self._conn = sqlite3.connect(path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                name TEXT, value REAL, tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    def write(self, name, value, tags):
        self._conn.execute(
            "INSERT INTO metrics (name, value, tags) VALUES (?, ?, ?)",
            (name, value, json.dumps(tags))
        )
        self._conn.commit()

class InMemoryMetricsRecorder:
    def __init__(self, backend: Optional[MetricsBackend] = None):
        self._backend = backend
        ...
    def record(self, name: str, value: float, **tags):
        self._histograms[name].append(value)
        if self._backend:
            self._backend.write(name, value, tags)
```

**集成**: 在 `ResearchPipeline.__init__()` 中可选择注入 SQLite backend:

```python
# config.yaml 添加
research:
  metrics:
    persist: true
    backend: sqlite
    path: ./metrics/research.db
```

**影响范围**: `observability.py`, `research_pipeline.py`, ~10 个 `perf_section` 调用点
**工作量**: 低 (~0.5 人天)

---

### P2-3. Walk-Forward 未集成主流水线 (R7-6)

**问题**: `tests/test_walk_forward_pipeline.py` 存在但 Walk-Forward 分析未集成到 `ResearchPipeline`。

**修复方案**:

```python
# research_pipeline.py — 添加 walk_forward 方法
from uniquant.hands.backtest.walk_forward import (
    WalkForwardConfig, WalkForwardResult
)

class ResearchPipeline:
    def run_walk_forward(
        self, symbol: str,
        config: Optional[WalkForwardConfig] = None,
    ) -> WalkForwardResult:
        """运行 Walk-Forward 分析"""
        config = config or WalkForwardConfig(
            n_windows=5,
            train_ratio=0.7,
            step_size=60,       # 60 交易日步进
            min_train=252,      # 最少 1 年训练
        )
        return self._walk_forward.run(symbol, config)
```

**影响范围**: `test_walk_forward_pipeline.py` → 集成到 `research_pipeline.py`
**工作量**: 低 (~0.5 人天)

---

## P3 — 代码健康度

### P3-1. 大文件拆分: eastmoney.py (1,094 LOC)

**问题**: 超出项目 800 LOC 上限。`DataSourceConstants` 中有 20+ 列名映射, 大量重复的 API 请求方法。

**修复方案**:

```
sources/
├── eastmoney/
│   ├── __init__.py          # 重新导出主要类
│   ├── api.py               # API 调用 (约 300 LOC)
│   ├── financial.py         # 财务数据解析 (约 300 LOC)
│   ├── industry.py          # 行业/概念数据 (约 200 LOC)
│   └── utils.py             # 共享工具 (约 200 LOC)
```

**风险**: 拆分影响 import。确保 `from .sources.eastmoney import EastMoneySource` 仍然工作。
**工作量**: 中 (~1 人天)

---

### P3-2. TradeCalendarManager 假期硬编码 (R2-3)

**问题**: `trade_calendar_manager.py:11-68` 硬编码 2024-2026 年 A 股假期。2027 年交易日期计算错误会导致 T+1 检查失败。

**修复方案**:

```python
# 方案 A (推荐): 添加 AkShare 自动获取
class TradeCalendarManager:
    def __init__(self, data_dir: str = "./data"):
        ...
        self._auto_update_if_stale()

    def _auto_update_if_stale(self):
        """如果缓存的日历超过 6 个月, 自动更新"""
        import akshare as ak
        cache = self._load_cache()
        if cache is None or self._is_stale(cache):
            calendar = ak.tool_trade_date_hist_sina()
            self._save_cache(calendar)
            self._calendar = calendar

# 方案 B: 添加 2027-2030 年假期 (简单但延续硬编码)
# 推荐方案 A — 一次集成, 免除后续维护
```

**影响范围**: `trade_calendar_manager.py`, 新增 `akshare` 依赖 (已存在)
**工作量**: 低 (~0.5 人天)

---

### P3-3. Signal 适配器冗余 (R5-4)

**问题**: `adapters.py` 中存在 `adapt_NtfOutput` 和 `noop_adapter_for_ntf` 两个同名方法:

```python
# adapters.py (实际代码)
def adapt_NtfOutput(ntf_output: NtfOutput) -> CandidateSignal:
    ...

def noop_adapter_for_ntf(ntf_output: Dict[str, Any]) -> None:
    # 空实现, 仅占位
    ...
```

**修复**:

```python
# 删除 noop_adapter_for_ntf
# 统一使用 adapt_NtfOutput (包含完整实现)

# adapters.py — ALWAYS_ADAPTERS 中已注册 adapt_NtfOutput
ALWAYS_ADAPTERS: dict[str, Callable[..., CandidateSignal | None]] = {
    "NTF": adapt_NtfOutput,   # ✅ 唯一入口
}
```

**影响范围**: `adapters.py`, 无外部调用者
**工作量**: 非常低 (~0.1 人天)

---

### P3-4. T+1 for-loop 向量化 (R6-2)

**问题**: `unified_matching_engine.py:198-209` 使用 Python for-loop 检查 T+1:

```python
for i in range(n):
    if buy_dates[i] is None: continue
    b_ts, c_ts = buy_dates[i], timestamps[i]
    if c_ts.toordinal() <= b_ts.toordinal(): t1_violation[i] = True
```

**修复**:

```python
# 向量化版本
def _check_t1_violation_vectorized(
    buy_dates: np.ndarray,
    timestamps: np.ndarray,
    trading_days: np.ndarray,
) -> np.ndarray:
    has_buy = ~pd.isna(buy_dates)
    if not has_buy.any():
        return np.zeros(len(buy_dates), dtype=bool)

    buy_ord = pd.DatetimeIndex(buy_dates[has_buy]).to_julian_date().values
    curr_ord = pd.DatetimeIndex(timestamps[has_buy]).to_julian_date().values

    # 同日期
    violation = np.zeros(len(buy_dates), dtype=bool)
    violation[has_buy] = curr_ord <= buy_ord

    # 下一个交易日检查 (通过 trading_days 向量化查找)
    # 这里使用 np.searchsorted 替代 for-loop
    next_td = trading_days[
        np.searchsorted(trading_days, buy_dates[has_buy]) + 1
    ]
    violation[has_buy] |= curr_ord < next_td

    return violation
```

**影响范围**: `unified_matching_engine.py` 仅修改约 30 行
**工作量**: 低 (~0.3 人天)

---

## 修复路线图

### Sprint 1: 正确性修复 (1 周)

```
P0-1 回测引擎独立仲裁     ├─ unified_engine.py      — 1 天
P0-2 信号体系统一           ├─ analysis_service_v2.py — 3 天
P0-3 Wyckoff 测试修复       ├─ wyckoff tests          — 0.5 天
                         └─── 总计: 4.5 天
```

### Sprint 2: 架构债务清理 (1 周)

```
P1-1 DataFetcher/Ingestion  ├─ data_fetcher.py        — 0.5 天
P1-2 废弃文件清理            ├─ 6 个文件删除          — 0.5 天
P3-3 适配器冗余              ├─ adapters.py            — 0.1 天
P3-4 T+1 向量化              ├─ matching_engine.py     — 0.3 天
P3-2 TradeCalendar 自动更新  ├─ trade_calendar.py      — 0.5 天
                          └─── 总计: 2 天
```

### Sprint 3: 研究效率提升 (1 周)

```
P2-1 ResultStore             ├─ shared/result_store.py — 1 天
P2-2 Metrics 持久化          ├─ observability.py       — 0.5 天
P2-3 Walk-Forward 集成       ├─ research_pipeline.py   — 0.5 天
P3-1 eastmoney 拆分          ├─ sources/eastmoney/     — 1 天
                          └─── 总计: 3 天
```

### 总计: 3 周, ~10 人天

---

## 优先级总结

| 优先级 | 问题 | 工作量 | 收益 | 建议 |
|--------|------|--------|------|------|
| **P0** | 回测引擎重复仲裁 | 1 天 | 修复正确性 | **必须做** |
| **P0** | 两套信号体系 | 3 天 | 消除行为分裂 | **必须做** |
| **P0** | Wyckoff 测试失败 | 0.5 天 | 测试面纯净 | **必须做** |
| **P1** | DataFetcher 重复 | 0.5 天 | 消除维护负担 | 应该做 |
| **P1** | 废弃代码清理 | 0.5 天 | -2,100 LOC | 应该做 |
| **P2** | ResultStore 持久化 | 1 天 | 研究可追溯 | 推荐做 |
| **P2** | Metrics 持久化 | 0.5 天 | 性能分析 | 推荐做 |
| **P2** | Walk-Forward 集成 | 0.5 天 | 研究深度 | 推荐做 |
| **P3** | eastmoney 拆分 | 1 天 | 代码健康 | 可选 |
| **P3** | T+1 向量化 | 0.3 天 | 性能 | 可选 |
| **P3** | 假期自动更新 | 0.5 天 | 2027 兼容 | 可选 |

---

## 最终建议

UniQuant 的整体架构质量在量化研究平台中处于**中上水平**。核心优势 (A 股规则、多源容错、信号仲裁) 值得保留和强化。主要短板集中在:

1. **正确性**: 回测引擎内部仲裁 bypass 了 SignalArbitrator (P0-1), 这是最需要优先修复的问题
2. **一致性**: 两套信号体系并存导致结果不确定 (P0-2), 建议在 1 个迭代内完成统一
3. **可追溯性**: 研究结果无法回溯 (P2-1), 这是从"个人研究工具"迈向"团队研究平台"的关键一步

建议按 Sprint 1 → Sprint 2 → Sprint 3 的顺序执行, 总计约 3 周可以完成所有建议修复。
