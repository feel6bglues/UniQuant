# 修复计划终审决议

> **审议者**: 量化金融架构师 | **被审议**: `REMEDIATION_REVIEW.md`
> **基于**: 实际代码走读验证 (已验证 EngineFactory/引擎优先级/信号路径/日历)
> **日期**: 2026-06-29

---

## 一、逐项验证结果

### 验证 1: EngineFactory 异常处理 (REMEDIATION_REVIEW.md 新增)

**判决: ❌ 我错了 — 从修复清单中移除**

```
代码验证:
  engine_factory.py:
    Line 46: except Exception as e:
                logger.error(f"Failed to init {name}: {e}")
                raise RuntimeError(...) from e    # ← 重抛!
    Line 90: except Exception as e:
                logger.error(f"Failed to init brain: {e}")
                raise RuntimeError(...) from e    # ← 重抛!

  analysis_service_v2.py:
    Line 351-356: RECOVERABLE_ERRORS = (AttributeError, ImportError, KeyError, ModuleNotFoundError, ...)
                  # RuntimeError 不在其中 → 透传到上层

  research_pipeline.py:
    Line 478-486: _run_single → except Exception as e:
                                      return PipelineResult(success=False, error=str(e))  # 批量模式正常捕获
```

异常从 EngineFactory → `_run_engines`(透传) → `run_ticker_analysis`(透传) → `run`(透传) → `run_batch._run_single`(捕获为失败结果)。**错误正确传播, 非静默失败**。

**结论**: 移除该修复项, 无需改动。

---

### 验证 2: 回测引擎优先级 (原 P0-1 → 建议 P2)

**判决: ✅ 代码存在, 但非正确性缺陷**

```
代码验证:
  unified_engine.py:236-250
    # Step 3: 收集当日信号, 生成挂单
    # 规则: LPPL SELL > BUY > 非LPPL SELL
    for sig in day_signals:
        if (sig.action == "SELL" and position > 0
                and sig.reason and "lppl" in sig.reason.lower()):
            pending_order = {"action": "SELL", ...}
            break
    if pending_order is None:
        for sig in day_signals:
            if sig.action == "BUY" and position == 0:
                pending_order = {"action": "BUY", ...}
                break
    if pending_order is None:
        for sig in day_signals:
            if sig.action == "SELL" and position > 0:
                pending_order = {"action": "SELL", ...}
                break
```

`SignalArbitrator` 输出 `TradingSignal[]` (可能多个), 引擎对同天多个信号做优先级调度。这是合法的执行层职责 — 仲裁器决定"哪些信号生成", 引擎决定"同天多个时先执行哪个"。非 bypass。

**保留为 P2 设计一致性改进**。但如果仲裁器未来 consolidate 到单信号, 此处逻辑可简化。

---

### 验证 3: 特征标记默认值

```
  config.yaml:429: use_research_data_pack: false   # ← 默认关闭
  config.yaml:427: async_event_bus: false           # ← 默认关闭
  config.yaml:415: signal_arbitration: true         # ← 默认开启
  config.yaml:417: factor_gate: "block"             # ← gate 阻塞模式
```

`use_research_data_pack: false` 意味着:
- `_prepare_data()` 走 `fetch_for_brain()` Dict 路径
- `_collect_signals()` 处理引擎 Dict 输出 (非 TradingSignalCollector)
- 4 个引擎的 typed outputs (RegimeOutput/LPPLOutput 等) 通过 `to_dict()` 转回 Dict 再被解析

**信号路径分裂确认**。P0 优先级保留。

---

### 验证 4: TradeCalendar 硬编码

```
  trade_calendar_manager.py:11-68:
    _CN_HOLIDAYS = {"2024-01-01", ..., "2026-12-31"}  # 截至 2026
    # 2027 年春节 2/6, 假期 2/4-2/10 → 未包含

  pyproject.toml: akshare>=1.12.0,<2.0.0  # 依赖已存在
```

2027 年 1 月 1 日起交易日判断错误 → T+1 检查漏洞。**P1 确认**。

---

## 二、终审任务清单 (多线程并行)

### 线程依赖图

```
                  ┌──────────────────┐
                  │  Thread A        │  config.yaml + analysis_service_v2 + data_service
                  │  信号体系统一     │  ~5 files, 2 天
                  └────────┬─────────┘
                           │ (信号路径确定后)
                           ▼
                  ┌──────────────────┐
                  │  Thread D        │  shared/result_store.py + research_pipeline.py
                  │  ResultStore     │  ~2 files (新), 1 天
                  └──────────────────┘

独立线程 (与 A/D 无文件冲突):
  Thread B: TradeCalendar 自动更新  → trade_calendar_manager.py     (0.5 天)
  Thread C: Wyckoff 测试诊断        → test_wyckoff_new_features.py  (0.5 天)
  Thread E: DataFetcher 单入口      → data_fetcher.py              (0.5 天)
  Thread F: 回测 compare + 优先级   → unified_engine.py             (0.5 天)
  Thread G: 废弃代码清理            → 6 文件删除                    (0.5 天)

执行:
  Phase 1 (并行, 互不依赖):
    ├── Thread A  (信号体系统一)
    ├── Thread B  (TradeCalendar)
    └── Thread C  (Wyckoff 诊断)

  Phase 2 (Thread A 完成后):
    ├── Thread D  (ResultStore — 依赖信号路径确认)
    ├── Thread E  (DataFetcher)
    ├── Thread F  (回测改进)
    └── Thread G  (废弃代码清理 — 最后做, 减少 merge conflict)
```

---

### Thread A: 信号体系统一 【P0, 2 天】

**目标**: 翻转 `use_research_data_pack` 为 true, 统一到 typed TradingSignal 路径

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `config/config.yaml:429` | 修改 | `use_research_data_pack: false` → `true` |
| `src/uniquant/services/analysis_service_v2.py` | 修改 | 修复数据准备/引擎输出中的 Dict 路径假设 |
| `src/uniquant/services/data_service.py` | 修改/验证 | `fetch_for_brain` 与 `fetch_research_pack` 输出对齐 |
| `src/uniquant/signal/adapters.py` | 验证 | 6 个适配器在 typed 路径下是否正常运行 |
| `src/uniquant/signal/arbitrator.py` | 验证 | 仲裁器输入已是 TradingSignal, 无需修改 |
| 相关测试文件 | 修改 | 测试预期结果对准新路径 |

**安全措施**:
```python
# config.yaml 修改后首次运行自动生成对比报告
# 同时运行 Dict 路径和 typed 路径, 比较信号差异
# 只在差异为 0 时正式切换
```

**验证标准**: `pytest tests/ -q` 通过 (Wyckoff 12 项除外), 无新增失败

---

### Thread B: TradeCalendar 自动更新 【P1, 0.5 天】

**目标**: 消除硬编码假期, 通过 AkShare 自动获取

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/uniquant/data/managers/trade_calendar_manager.py` | 修改 | 添加 `_auto_update_if_stale()`, 调用 `ak.tool_trade_date_hist_sina()` |

```python
# 核心改动 (~30 行新增)
def _auto_update_if_stale(self, max_age_days: int = 180):
    import akshare as ak
    cache_path = Path(self.data_dir) / "trade_calendar.csv"
    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        age = (time.time() - mtime) / 86400
        if age < max_age_days:
            return  # 缓存够新
    calendar = ak.tool_trade_date_hist_sina()
    calendar.to_csv(cache_path, index=False, encoding="utf-8-sig")
    self._calendar = calendar
```

**验证标准**: `python3 -c "from uniquant.data.managers.trade_calendar_manager import TradeCalendarManager; t=TradeCalendarManager(); print(t.is_trading_day('2027-01-04'))"` 输出正确

---

### Thread C: Wyckoff 测试诊断 【P0, 0.5 天】

**目标**: 诊断 12 个预存失败的根本原因

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `tests/test_wyckoff_new_features.py` | 诊断/修改 | 运行并分类失败原因 |

```bash
# 诊断命令
pytest tests/test_wyckoff_new_features.py -v --tb=long 2>&1 | tee /tmp/wyckoff_diag.log

# 分类:
# 1. 预期行为变更 (feature 导致测试基线变更) → 更新测试
# 2. 意外回归 (代码 bug) → 修复代码
# 3. 测试自身问题 (mock 过期/环境) → 修正测试
```

**验证标准**: 12 项测试全部通过或明确标记为"预期行为变更"

---

### Thread D: ResultStore 研究结果持久化 【P1, 1 天】

**目标**: 分析结果可查询、可对比、可导出

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/uniquant/shared/result_store.py` | **新建** | 结果存储类 (~100 行) |
| `src/uniquant/services/research_pipeline.py` | 修改 | `run()` 结束时调用 `result_store.save()` |
| `tests/test_result_store.py` | **新建** | 3-5 个测试 |

```python
# result_store.py 接口设计
class ResultStore:
    def __init__(self, path: str = "./results"): ...
    def save(self, symbol: str, record: AnalysisRecord) -> None: ...
    def load(self, symbol: str, analysis_date: date) -> Optional[AnalysisRecord]: ...
    def query(self, analysis_date: date) -> list[AnalysisRecord]: ...
    def compare(self, symbol: str, date1: date, date2: date) -> dict: ...
```

**验证标准**: `python3 -c "from uniquant.shared.result_store import ResultStore; rs=ResultStore('/tmp/test_results'); rs.save('000001.SZ', AnalysisRecord(...)); assert rs.load('000001.SZ', date.today()) is not None"`

---

### Thread E: DataFetcher 单入口 【P2, 0.5 天】

**目标**: 消除 DataFetcher 和 DataIngestionService 之间的 SourceRouter 重复

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/uniquant/data/data_fetcher.py` | 修改 | `get_price()` 直接调用 `self.source_router` 而非 `self.ingestion` |
| `src/uniquant/data/data_ingestion_service.py` | 修改 | 改为 DataFetcher 的薄委托层, 保留接口兼容 |

**关键修改**:
```python
# data_fetcher.py
class DataFetcher:
    def get_price(self, symbol, adjust=""):
        ...
        # 之前: df = self.ingestion.fetch_price(symbol)  # 走 DataIngestionService
        # 改为: df = self.source_router.fetch_with_fallback(symbol)  # 走自己的 Router
        df = self.source_router.fetch_with_fallback(symbol)
        ...

# data_ingestion_service.py — 精简为兼容性包装
class DataIngestionService:
    def __init__(self, fetcher: DataFetcher):
        self._fetcher = fetcher
    def fetch_price(self, symbol, source="auto"):
        return self._fetcher.get_price(symbol)
```

**验证标准**: `pytest tests/test_data_fetcher_init_fault_tolerance.py tests/test_data_access_service.py -v` 全部通过

---

### Thread F: 回测系统改进 【P2, 1 天】

**目标 1**: `BacktestResult.compare()` 支持回测结果对比
**目标 2**: 引擎优先级明确注释为"多信号同天调度" (降低维护困惑)

**文件清单**:

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/uniquant/hands/backtest/unified_engine.py` | 修改 | 添加 `BacktestResult.compare()`, 更新优先级注释 |
| `tests/test_backtest_compare.py` | **新建** | 2-3 个测试 |

```python
# BacktestResult 新增
@dataclass
class BacktestResult:
    ...
    def compare(self, other: "BacktestResult") -> dict:
        return {
            "total_return_diff": self.total_return - other.total_return,
            "sharpe_diff": (self.sharpe or 0) - (other.sharpe or 0),
            "max_drawdown_diff": (self.max_drawdown or 0) - (other.max_drawdown or 0),
            "trade_count_diff": len(self.trades) - len(other.trades),
            "win_rate_diff": (self.win_rate or 0) - (other.win_rate or 0),
        }

# unified_engine.py — 更新优先级注释
# 规则: LPPL SELL > BUY > 非LPPL SELL
# 说明: 当仲裁器输出多个信号同天到达时, 按此顺序尝试执行。
#       第一个满足条件的信号被执行, 其余忽略。
#       这是执行层调度, 非仲裁层逻辑。
```

**验证标准**:
```python
r1 = engine.run(df, signals_a, "000001.SH")
r2 = engine.run(df, signals_b, "000001.SH")
diff = r1.compare(r2)
assert "sharpe_diff" in diff
```

---

### Thread G: 废弃代码清理 【P3, 0.5 天】

**目标**: 移除已弃用代码, 减少维护负担

**文件清单**:

| 文件 | LOC | 操作 | 前提 |
|------|-----|------|------|
| `src/uniquant/hands/backtest/engine.py` | 747 | 删除 | 确认零 import 引用 |
| `src/uniquant/hands/backtest/portfolio_engine.py` | 373 | 删除 | 同上 |
| `src/uniquant/hands/backtest/result.py` | 175 | 删除 | 同上 |
| `src/uniquant/risk/historical_risk.py` | 18 | 删除 | 同上 |
| `src/uniquant/data/manager.py` | 12 | 删除 | 同上 |
| `src/uniquant/services/analysis_service_legacy.py` | ~800 | 删除 | 服务容器无引用 |

```bash
# 前置审计
rg "from.*engine import|from.*portfolio_engine|from.*backtest.result|from.*historical_risk|from.*manager import|from.*analysis_service_legacy" src/ tests/

# 无引用 → 删除
# 有引用 → 更新 import 后删除
```

**验证标准**: 删除后 `python3 -c "import uniquant"` 正常, `pytest tests/ -q` 通过数不变

---

### 最终时间线

```
Week 1          Week 2          Week 3
├───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
A■■■■■■■■■■■■■■
 B■■■■
 C■■■■
                   D■■■■■■■■
                    E■■■■
                    F■■■■■■■■
                     G■■■■
```

| 阶段 | 任务 | 并行度 | 工作量 |
|------|------|--------|--------|
| Phase 1 (Week 1) | A + B + C | 3 路并行 | 3 天 |
| Phase 2 (Week 2) | D + E + F + (G 尾端) | 3 路并行 | ~3 天 |
| **总计** | 7 项 | 平均 3 路 | **6 天** |

---

## 三、最终优先级排序

```
必须做 (P0, 功能正确性):
  Thread A: 信号体系统一               → 2 天  ← 消除信号分裂
  Thread C: Wyckoff 测试诊断           → 0.5 天 ← 恢复测试信任

应该做 (P1, 时间敏感/研究效率):
  Thread B: TradeCalendar 自动更新     → 0.5 天 ← 2027 年时间炸弹
  Thread D: ResultStore 研究结果持久化  → 1 天   ← 团队研究可追溯

推荐做 (P2, 工程改进):
  Thread E: DataFetcher 单入口         → 0.5 天 ← 减少困惑
  Thread F: 回测 compare + 优先级注释    → 1 天   ← 参数对比效率

可选做 (P3, 代码健康):
  Thread G: 废弃代码清理               → 0.5 天 ← -2,000 LOC

总计: ~6 天 (3 路并行)
```

---

## 四、最终建议

1. **Thread A (信号体系统一) 是本次修复最有价值的一项**。它直接解决架构中最大的不一致性 — 两条信号路径并行存在, 且默认路径走的是旧 Dict 路线。翻转后, Phase 3/4 的 typed contracts 才真正生效。

2. **Thread B (TradeCalendar) 不应跳过**。2027 年 1 月 1 日是 6 个月后。回测结果一旦产生无法回溯修正, 届时发现的 T+1 漏洞将影响所有在此之后运行的回测。AkShare 依赖已存在, 零新增成本。

3. **Thread G (废弃代码清理) 放在最后**。6 个文件的 import 关系可能与其他线程的修改重叠, 在所有其他变更完成后做 cleanup 最安全。

4. **关于"不做"的决策**: EngineFactory 异常处理 (原 REMEDIATION_REVIEW 新增项) 经代码验证确认非问题, 已从清单中移除。回测引擎优先级 (原 P0-1) 经分析确认是合法的执行层调度职责, 降为 P2 注释改进。
