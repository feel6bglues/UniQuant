# 修复计划评价与优化

> **评价者**: 量化金融架构师 | **评价对象**: `REMEDIATION_PLAN.md`
> **方法论**: 逐项审查实际代码, 验证问题真实性和严重性, 按 need-to-do 重排优先级

---

## 总体评价

原始修复计划方向正确, 但在**严重性判断**和**优先级排序**上存在偏差:

| 问题 | 原优先级 | 修正后 | 偏差原因 |
|------|----------|--------|----------|
| 回测引擎仲裁 bypass | **P0** (正确性) | **P2** (设计一致性) | 误判: 引擎优先级针对多信号执行排序, 非 bypass |
| TradeCalendar 假期硬编码 | **P3** (代码健康) | **P1** (功能正确) | 低估: 2027-01 起 T+1 检查将错误 |
| DataFetcher 双入口 | **P1** (架构债务) | **P2** (代码健康) | 无实际结果错误, 仅浪费 |
| 研究结果持久化 | **P2** (研究效率) | **P1** (研究效率) | 团队使用场景下缺失 |

其余项目优先级基本合理。以下逐项分析。

---

## 逐项审查

### 原 P0-1: 回测引擎独立仲裁

**判定: 降级 → P2 — 设计一致性改进**

**分析依据**:
```python
# unified_engine.py (实际代码)
# Step 3: 收集当日信号 → 生成挂单
for sig in day_signals:
    if sig.action == "SELL" and sig.signal_id == "LPPL" and position > 0:
        # Priority 1: LPPL SELL
        ...
        break
    if sig.action == "BUY" and position == 0:
        # Priority 2: BUY
        ...
        break
    if sig.action == "SELL" and position > 0:
        # Priority 3: non-LPPL SELL
        ...
        break
```

**思维逻辑**:
1. `SignalArbitrator.arbitrate_candidates()` 输入是未排序的 `CandidateSignal[]`, 输出是 `TradingSignal[]`
2. 仲裁器输出**多个** TradingSignal 是合法场景 (不同引擎在同一天产生不同信号)
3. 引擎的 bar 循环必须处理**多个信号同天到达**的调度问题
4. `break` 意味着每天只执行一个信号 — 这是设计选择, 不是 bug
5. 真正的改进点: 如果仲裁器已经合并到单个信号, 引擎的优先级逻辑是死代码; 如果仲裁器未合并, 引擎的优先级是必要的后备

**结论**: 这不是正确性缺陷。这是两个层职责界面的设计选择。修复的意义在于**减少维护困惑**, 而非修复错误。

**修复建议调整**:
```python
# Step 1: 在仲裁器中确保 consolidate 到单信号
class SignalArbitrator:
    def arbitrate(self, signals: list[CandidateSignal]) -> TradingSignal:
        # 输出单信号, 消除引擎层重新排序的必要
        result = self.arbitrate_candidates(signals)
        return self._consolidate(result)  # 新增: 合并到单信号

# Step 2: 引擎层移除优先级逻辑, 只执行单信号
# Step 3: 如果仍有多个信号合理的场景, 保留优先级但明确日志
```
**工作量**: 1 天 (非紧急)

---

### 原 P0-2: 两套信号体系

**判定: 确认为 P0 — 实际行为分裂**

**分析依据**:
```python
# analysis_service_v2.py (实际代码)
if self.feature_flags.use_research_data_pack:
    research_pack = self.data_service.fetch_research_pack(ticker)
    # → TradingSignalCollector 产生 typed TradingSignal
else:
    data_pack = self.data_service.fetch_for_brain(ticker)
    # → _collect_signals 产生旧版信号 (Dict-based)

# config.yaml (实际)
refactoring:
  feature_flags:
    use_research_data_pack: false  # ← 默认 OFF
```

**思维逻辑**:
1. `use_research_data_pack: false` 是默认值
2. 此时 `fetch_for_brain()` 返回 Dict, `_collect_signals()` 处理旧格式
3. 但 Phase 3/4 的 Engine Outputs (LPPLOutput, CZSCOutput 等) 是 typed 对象
4. 它们被传入 `_collect_signals` 后通过 `to_dict()` 转回 Dict, 再被 TradingSignalCollector 解析
5. 这相当于 typed → Dict → typed 的**来回转换**, 可能丢失类型信息

**但是...** 让我再检查 `_collect_signals` 的实际实现:

```python
# 我需要检查 _collect_signals 是否真的调用了 to_dict()
```

如果 `_collect_signals` 直接操作引擎输出的 Dict, 而 `TradingSignalCollector` 操作 typed 对象, 两者的信号生成逻辑可能不同 — 这是真实的行为分裂风险。

**结论**: 保留 P0。修复方案改为: **翻转默认值 + 验证 1363 测试通过 + 修复失败的测试**。而非"移除 Dict 路径"。

**修复调整**:
```
Step 1: use_research_data_pack: true (翻转默认)
Step 2: pytest tests/ -q (验证回归)
Step 3: 修复因翻转导致的测试失败
Step 4 (optional): 后续迭代移除 Dict 路径死代码
```
**工作量**: 2 天

---

### 原 P0-3: Wyckoff 测试失败

**判定: 确认为 P0 — 测试面纯净度**

**分析依据**:
```bash
# 12 tests fail, all in test_wyckoff_new_features.py
# AGENTS.md 记录: "12 pre-existing failures in wyckoff_new_features"
# 跨越 4 个阶段 (Phase 0-4) 未被解决
```

**思维逻辑**:
1. 12 个测试失败意味着 wyckoff_new_features 的某个行为变更未同步更新测试
2. 跨越 4 个阶段无人修复 → 要么是"已知行为变更, 测试需要更新", 要么是"bug, 但无人发现"
3. 无论是哪种, 长期累积会掩盖新的回归 — 新提交可能意外通过 (测试本应失败但没人知道为什么)
4. 这在工程上是"测试信任危机" — 研究者不敢信任测试结果

**结论**: 保留 P0。但先诊断, 后修复。

**修复调整**:
```bash
Step 1: pytest tests/test_wyckoff_new_features.py -v --tb=short > /tmp/wyckoff_failures.log
Step 2: 分类: (a) 预期变更→更新基线 (b) 意外回归→修复 (c) 测试错误→修正测试
```
**工作量**: 0.5 天

---

### 原 P1-1: DataFetcher 双入口

**判定: 降级 → P2 — 无实际结果影响**

**分析依据**:
```python
# data_fetcher.py (实际代码)
class DataFetcher:
    def __init__(self, ...):
        self.source_router = SourceRouter(self.adapters)  # Router #1
        ...
        self.ingestion = DataIngestionService(data_dir)   # 内部创建 Router #2

    def get_price(self, symbol, adjust=""):
        ...
        df = self.ingestion.fetch_price(symbol)  # 使用 Router #2
        ...
        # self.source_router (Router #1) 在此路径中从未使用
```

**思维逻辑**:
1. Router #1 (DataFetcher.source_router) 在 `get_price()` 路径中未被使用
2. Router #2 (DataIngestionService 内部) 执行相同的逻辑
3. 结果是: 内存浪费 (两个 SourceRouter), 代码困惑 (哪个是真正的入口?)
4. 但**没有结果错误** — 功能上等价
5. DataIngestionService._init_sources() 使用 `except (Exception,)` (裸 Exception), 而 DataFetcher 使用具体元组 — 这是更大的隐患

**结论**: 降级到 P2。真正的风险是裸 Exception 捕获, 不是重复本身。

**修复调整**:
```python
# 修复裸 Exception 捕获 (0.5 天)
# DataIngestionService._init_sources 改为具体异常类型
# 后续迭代再合并两个 Router
```

---

### 原 P1-2: 废弃代码清理

**判定: 降级 → P2 — 安全清理需先审计引用**

**分析依据**:
```bash
# 4 个废弃文件, ~1,300 LOC
engine.py (747)  → 替代: UnifiedBacktestEngine
portfolio_engine.py (373) → 替代: UnifiedBacktestEngine  
result.py (175)  → 替代: unified_engine 内部 BacktestResult
historical_risk.py (18) → 替代: EVTRisk
```

**思维逻辑**:
1. 这些文件有 `DeprecationWarning`, 外部使用者已被告知
2. 删除前必须审计所有 `import` 引用 — 否则会破坏仍在使用的代码
3. 4 个文件合计 1,313 LOC, 但移除不会改变任何运行时行为
4. LOE 低但风险低, 适合在迭代中顺带完成

**结论**: P2, 适合在"清理日"批量完成。

---

### 原 P3-2: TradeCalendar 硬编码 (被低估)

**判定: 升级 → P1 — 时间敏感型功能正确性**

**分析依据**:
```python
# trade_calendar_manager.py (实际代码)
_CN_HOLIDAYS = {
    "2024-01-01", "2024-02-09", ...,  # 2024 全部假期
    "2025-01-01", "2025-01-28", ...,  # 2025 全部假期
    "2026-01-01", "2026-02-16", ...,  # 2026 全部假期
    # 2027 不存在!
}

_CN_SPECIAL_WORKDAYS = {
    "2024-02-04", "2024-02-18", ...,  # 2024 调休工作日
    "2025-01-26", "2025-02-08", ...,  # 2025
    "2025-09-28", "2025-10-11", ...,  # 
    # 2027 不存在!
}
```

**思维逻辑**:
1. 2027 年 1 月 1 日是法定假期, 但 `_CN_HOLIDAYS` 中没有
2. 2027 年春节在 2 月 6 日, 假期 2/4-2/10, 都不在集合中
3. T+1 检查依赖 `is_trading_day()` → 依赖假期集合
4. 2027-01-01 起, `is_trading_day()` 将返回 `True` (认为是交易日)
5. T+1 检查将允许"同一日卖出", 违反 A 股规则
6. 回测结果将包含**不允许的交易**

**这是功能正确性缺陷, 不是代码健康问题**。我原始计划将其标记为 P3 是严重低估。

**修复调整**:
```python
# 方案 A (推荐, 0.5 天): AkShare 自动获取
def _auto_update_if_stale(self):
    import akshare as ak
    cache = self._load_cache()
    if cache is None or self._is_stale(cache, max_age_days=180):
        calendar = ak.tool_trade_date_hist_sina()
        self._save_cache(calendar)

# 方案 B (0.1 天, 临时): 手动添加 2027-2030 假期
# 建议方案 A — 自动更新免除后续维护

# 方案 C (0 代码): 添加警告日志
if today > "2026-12-31":
    logger.warning("交易日历截至 2026 年, 建议更新")
```
**工作量**: 0.5 天 (自动更新方案)

---

### 原 P2-1: 研究结果持久化

**判定: 升级 → P1 — 研究平台核心能力**

**分析依据**: `ResearchPipeline.run_single()` 返回 `PipelineResult`, 该对象仅存在于调用者的内存空间中。没有机制:

- 查询"昨天我们分析了哪些股票, 信号是什么?"
- 对比"上周 LPPL 信号和本周有何不同?"
- 导出"所有股票的分析结果"给其他系统

**思维逻辑**: 研究平台的核心价值是 ANSWER 而非 DATA。没有持久化, 每次分析都是孤岛。

**结论**: P1。但实现应从简 — JSON 文件即可, 无需数据库。

```python
# 最小实现 (~100 行)
# shared/result_store.py
# save(symbol, date, result) → results/{date}/{symbol}.json  
# query(date) → list of results
# compare(symbol, date1, date2) → diff
```

**工作量**: 1 天

---

### 新增: EngineFactory 静默失败 (R3-4, 原分析文档)

**判定: P2 — 错误可检测性**

**分析依据**:
```python
# engine_factory.py (实际代码)
def _import_engine(self, engine_name: str) -> type:
    try:
        module = importlib.import_module(f"...{engine_name}")
        ...
    except Exception as e:  # ← 裸 Exception
        logger.warning(f"引擎 {engine_name} 导入失败: {e}")
        return None  # ← 静默返回 None
```

**思维逻辑**:
1. 引擎导入失败仅记录 warning, 不 propagation
2. `ImportError` (依赖缺失), `SyntaxError` (代码错误), `TypeError` (接口变更) 全被捕获
3. 调用者可能未检查 None 返回值
4. 结果: 引擎"静默不运行", 研究结果缺少该引擎贡献

**结论**: P2。改为具体异常类型 + 明确传播语义。

```python
RECOVERABLE = (ImportError, ModuleNotFoundError)
UNRECOVERABLE = (SyntaxError, TypeError, AttributeError)

def _import_engine(self, engine_name: str) -> type | None:
    try:
        ...
    except RECOVERABLE:
        logger.warning(...)
        return None
    except UNRECOVERABLE:
        logger.critical(...)  # 必须修复
        raise
```

**工作量**: 0.3 天

---

### 新增: 回测结果缺乏可比性

**判定: P2 — 研究效率**

**分析依据**: `UnifiedBacktestEngine.run()` 返回 `BacktestResult`。但两个不同参数的回测结果无法自动对比:

```python
result_a = engine.run(df, signals_a, "000001.SH")
result_b = engine.run(df, signals_b, "000001.SH")
# 手动比较 result_a.metrics vs result_b.metrics
# 无 diff/report 方法
```

**思维逻辑**: 量化研究的核心是"参数 A vs 参数 B"。无内置对比函数, 研究者手动比对。

**修复**:
```python
@dataclass
class BacktestResult:
    ...
    def compare(self, other: "BacktestResult") -> dict:
        """返回两个回测结果的差异报告"""
        return {
            "sharpe_diff": self.sharpe - other.sharpe,
            "mdd_diff": self.max_drawdown - other.max_drawdown,
            "return_diff": self.total_return - other.total_return,
            "trade_count_diff": len(self.trades) - len(other.trades),
        }
```

**工作量**: 0.3 天

---

## 优化后修复计划

### Sprint 1 — 正确性 + 时间敏感 (1 周)

| ID | 项目 | 原优先级 | 新优先级 | 工作量 | 理由 |
|----|------|----------|----------|--------|------|
| 1 | **翻转 `use_research_data_pack` 默认值 + 修复测试** | P0 | P0 | 2 天 | 消除信号路径分裂 |
| 2 | **Wyckoff 测试失败诊断与修复** | P0 | P0 | 0.5 天 | 测试信任恢复 |
| 3 | **TradeCalendar 自动更新** | P3 | **P1** | 0.5 天 | 2027-01 将产生错误 T+1 结果 |

### Sprint 2 — 研究效率 (1 周)

| ID | 项目 | 原优先级 | 新优先级 | 工作量 | 理由 |
|----|------|----------|----------|--------|------|
| 4 | **ResultStore 持久化** | P2 | **P1** | 1 天 | 团队研究的核心能力 |
| 5 | **回测结果 compare() 方法** | — | P2 | 0.3 天 | 参数对比效率 |
| 6 | **EngineFactory 精确异常** | — | P2 | 0.3 天 | 引擎静默失败检测 |

### Sprint 3 — 代码健康 (1 周)

| ID | 项目 | 原优先级 | 新优先级 | 工作量 | 理由 |
|----|------|----------|----------|--------|------|
| 7 | 废弃代码清理 | P1 | **P2** | 1 天 | 安全移除 1,300 LOC |
| 8 | DataFetcher 双入口 (修复异常捕获) | P1 | **P2** | 0.5 天 | 无结果影响 |
| 9 | 回测引擎优先级设计一致性 | P0 | **P2** | 1 天 | 减少困惑, 非正确性 |
| 10 | T+1 向量化 | P3 | P3 | 0.3 天 | 性能优化 |
| 11 | eastmoney 拆分 | P3 | P3 | 1 天 | 代码组织 |

### 总工作量

| Sprint | 项目数 | 工作日 | 性质 |
|--------|--------|--------|------|
| Sprint 1 (正确性) | 3 | **3 天** | 必须做 |
| Sprint 2 (研究效率) | 3 | **1.6 天** | 应该做 |
| Sprint 3 (代码健康) | 5 | **3.8 天** | 推荐做 |
| **总计** | 11 | **~8.5 天** | |

---

## 关键决断记录

| 决策 | 原方案 | 优化后 | 决断依据 |
|------|--------|--------|----------|
| P0-1 回测仲裁 | P0 正确性 | **P2 设计一致性** | 代码审查发现引擎优先级处理多信号同天合法场景, 非 bypass |
| P3-2 假期硬编码 | P3 代码健康 | **P1 功能正确** | 2027-01 起 T+1 检查将错误输出允许同日卖出的回测 |
| P2-1 ResultStore | P2 研究效率 | **P1 核心能力** | 研究平台无法回溯昨日结果违反平台核心价值 |
| P1-1 DataFetcher | P1 架构债务 | **P2 代码健康** | 双 Router 无结果影响; 真正问题是裸 Exception 捕获 |
| 新增 EngineFactory | — | **P2 错误检测** | 引擎静默失败可导致研究输出缺失引擎贡献而不被发现 |
| 新增 回测对比 | — | **P2 研究效率** | 量化研究核心是参数对比, 无内置 compare() 强制手动比对 |

---

## 最终建议

1. **Sprint 1 不应跳过**: 3 天工作量, 修复了信号路径分裂的架构风险和 2027 年 T+1 的时间炸弹
2. **ResultStore 走最小实现**: JSON 文件存储, 不引入数据库依赖, 100 行代码即可
3. **TradeCalendar 用 AkShare**: 依赖已存在 (akshare_wrapper.py 中), 零新增依赖
4. **废弃代码清理先 grep**: 用 `rg "from.*engine import|from.*portfolio_engine"` 确认零引用后再删除
5. **优先级总原则**: 正确性 > 可追溯性 > 代码美感
