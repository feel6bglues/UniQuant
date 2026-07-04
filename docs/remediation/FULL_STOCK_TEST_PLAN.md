# 全量本地股票数据测试计划

**日期**: 2026-06-29 | **发布**: Phase 5 修复后 | **基于**: 1410 通过 / 5 预存失败基线

---

## 背景

Phase 5 完成了 7 线程并行修复，其中包括：
- `use_research_data_pack` 默认值翻转 `false → true`
- 两条 CZSC/Wyckoff 引擎输出提取 bug 修复
- Wyckoff BayesianEventDetector 两处数学 bug 修复
- TradeCalendar AkShare 自动更新
- DataFetcher/DataIngestionService 精简
- ResultStore 集成

这些变更需要在大规模数据上验证，确保修复的正确性、系统稳定性和性能。

---

## 环境

| 项目 | 值 |
|---|---|
| 数据湖日线文件 | 5,934 个 parquet (data/lake/quotes/daily/) |
| 股票宇宙 | ~5,000 A股 + 指数/ETF |
| 处理器 | 未知 (由 ThreadPoolExecutor 自适应 `cpu_count//2`) |
| 配置 | `use_research_data_pack: true` (Phase 5 Thread A 翻转) |
| 特征标记 | `signal_arbitration: true`, `factor_gate: "block"` |

---

## Phase 1: 金丝雀测试 — Golden 20

**目标**: 快速冒烟测试，验证管线在 `use_research_data_pack=true` 下正常运转

**方法**: 直接读取 `capture_baseline.py`，手动调用 SerivceContainer + research_pipeline

```bash
pip install -e ".[all]" 2>&1 | tail -3
python scripts/capture_baseline.py
```

**验证清单**:
- [ ] ServiceContainer.initialize() 无异常
- [ ] 20 只股票全部 `result.success == True`
- [ ] 至少 1 只产生信号 (TradingSignal)
- [ ] 至少 1 只产生交易 (BacktestResult.total_trades > 0)
- [ ] BacktestResult.metadata.trace_id 存在
- [ ] 无 RuntimeWarning overflow (fail-fast guard)

**输出**: `tests/benchmark/baseline_v0.parquet`

---

## Phase 2: 扩展测试 — Golden 100

**目标**: 在较大多样化股票集上收集详细指标，验证信号生成和回测质量

**方法**:
```bash
python scripts/capture_baseline.py --stock-list golden_100.txt
```

**收集指标** (每个股票):

| 类别 | 指标 | 来源 |
|---|---|---|
| 引擎 | regime 成功/失败 | PipelineResult.decision |
| 引擎 | LPPL 成功/失败 + risk_level | decision.lppl_risk |
| 引擎 | NTF 成功/失败 + direction | decision.ntf_direction |
| 引擎 | CZSC 成功/失败 + signal | decision.czsc_signal |
| 引擎 | Wyckoff 成功/失败 + phase | decision.wyckoff_phase |
| 引擎 | Alpha 成功/失败 | decision.alpha_score |
| 决策 | action (BUY/SELL/HOLD) | decision.action |
| 决策 | confidence | decision.confidence |
| 信号 | 信号数量 | len(result.signals) |
| 信号 | 信号 action 分布 | 按 TradingSignal.action 分组 |
| 回测 | 交易数量 | result.backtest.total_trades |
| 回测 | 总收益 | result.backtest.total_return |
| 回测 | Sharpe | result.backtest.sharpe (Phase 5 新增) |
| 回测 | 最大回撤 | result.backtest.max_drawdown (Phase 5 新增) |
| 回测 | 胜率 | result.backtest.win_rate (Phase 5 新增) |
| 性能 | 单股耗时 | 时间戳差 |
| 稳定性 | 异常/错误 | result.error |

**分析报告**:
- 引擎故障率排名 (哪个引擎最容易失败)
- 信号产生率 (多少股票产生信号)
- 交易产生率 (多少信号转化为交易)
- 收益分布 (正收益比例, 平均收益)
- 按市场板块细分 (SH 主板 / SZ 主板 / GEM 创业板 / STAR 科创板)

**输出**:
- `tests/benchmark/baseline_v0.parquet`
- 自定义 JSON 汇总报告 `data/golden100_report.json`

---

## Phase 3: 结构化采样 — 500 只随机股票

**目标**: 中等规模测试，发现数据质量问题、稀疏数据失败模式和系统瓶颈

**方法**: 新建脚本 `scripts/staged_full_scan.py`，分阶段执行

```python
# staged_full_scan.py 核心逻辑
def main():
    # Stage 1: 500 only (canary for data quality)
    symbols = load_symbols_from_lake()
    random.seed(42)
    sample = random.sample(symbols, 500)
    pipeline.run_batch(sample, checkpoint_dir="data/checkpoints/stage1/")
    analyze_and_save("data/fullscan_report_stage1.json")
```

**分组 (500 只样本内)**:

| 组 | 筛选 | 预期数量 | 目的 |
|---|---|---|---|
| A | 正常股票 (>120 根K线) | ~400 | 主线测试 |
| B | 新股/次新股 (<120 根K线) | ~50 | 稀疏数据测试 |
| C | 指数/ETF | ~50 | 非股票标的测试 |

**验证清单**:
- [ ] 数据不足股票被跳过 (stock_df empty check)
- [ ] 新股/次新股不触发异常
- [ ] 指数/ETF 不触发异常 (应优雅失败)
- [ ] ThreadPoolExecutor 无死锁/竞争
- [ ] 检查点 checkpoint_dir 每只股票后正确写入
- [ ] 中间中断可恢复 (删除 checkpoint 中最后一只, 重新运行应跳过已完成)
- [ ] Overflow RuntimeWarning 触发 fail-fast (如已配置)

---

## Phase 4: 全量扫描 — 5,934 只

**目标**: 生产规模验证

**方法**: 
```bash
python scripts/staged_full_scan.py --stage full  # 或 python scripts/pipeline_full_scan.py
```

**性能预期** (来自 `08_performance_autopsy.md`):

| 指标 | 目标 | 测量方式 |
|---|---|---|
| 单股平均耗时 | < 5s | 总耗时 / 成功数量 |
| 全量 5000 只耗时 | < 100 min | 实时计时 |
| 内存峰值 | < 4GB | `memory_profiler` 采样 |
| 线程利用率 | > 70% | `top` / `htop` 观察 |

**收集**:
- Engine-level breakdown: 每个引擎的成功/失败/异常数量
- 信号分布: 按 `TradingSignal.action` 和 `TradingSignal.source` 统计
- 决策分布: BUY / SELL / HOLD 占比
- 收益分布: 直方图 + 分位数 (P25/P50/P75)
- 失败根因分析: 对每个 `result.error`, 归类为:
  - `DATA_INSUFFICIENT`: stock_df 为空或不足
  - `ENGINE_CRASH`: 单个引擎异常 (含 overflow)
  - `PIPELINE_ERROR`: pipeline 层面异常
  - `UNKNOWN`: 未归类

**输出**: `data/pipeline_fullscan/report.json` + `data/fullscan_report_final.json`

---

## Phase 5: 深度分析

**目标**: 对整个测试集进行系统性后分析

### A. 引擎故障根因分析

对于每个失败股票，读取 `result.error`，归类并统计:

```python
# 在 staged_full_scan.py 中
def classify_error(error_str: str) -> str:
    if not error_str:
        return "NONE"
    if "stock_df is None" in error_str or "数据不足" in error_str:
        return "DATA_INSUFFICIENT"
    if "overflow" in error_str.lower():
        return "OVERFLOW"
    if "fit" in error_str.lower() and "lppl" in error_str.lower():
        return "LPPL_FIT_FAIL"
    if "failed to" in error_str.lower() and "signal" in error_str.lower():
        return "SIGNAL_FAIL"
    return "OTHER"
```

### B. 信号质量分析

对于所有产生信号的股票:

| 维度 | 分析方法 |
|---|---|
| 信号源分布 | 各 `TradingSignal.source` (regime/lppl/ntf/czsc/wyckoff) 数量 |
| 信号 action 分布 | BUY vs SELL vs HOLD 比例 |
| 信号置信度分布 | 均值、标准差、P25/P50/P75 |
| 多信号冲突率 | 同天多个 signal 且 action 冲突的比例 |
| 信号→交易转化率 | 有信号的股票中有交易的股票比例 |

### C. 回测结果分析

```python
agg_stats = {
    "total_return": {"mean": ..., "median": ..., "p25": ..., "p75": ...},
    "sharpe": {"mean": ..., "median": ..., "positive_pct": ...},
    "max_drawdown": {"mean": ..., "median": ..., "max": ...},
    "win_rate": {"mean": ..., "median": ..., ...},
    "profit_factor": {"mean": ..., "median": ..., ...},
    "trades_per_stock": {"mean": ..., "median": ..., "max": ...},
}
```

### D. 预存 5 失败验证

确认 pre-existing 5 失败仍然可复现且未被修复影响:

| 测试 | 验证 |
|---|---|
| `test_survivorship_warning::test_metadata_trading_days_count` | 仍然失败 |
| `test_unified_matching::TestDefenseB::test_limit_down_blocks_sell` | 仍然失败 |
| `test_unified_matching::TestDefenseE::test_buy_no_stamp_duty` | 仍然失败 |
| `test_unified_matching::TestDefenseE::test_min_commission_enforced` | 仍然失败 |
| `test_unified_matching::TestDefenseF::test_buy_slippage_upward` | 仍然失败 |

---

## 文件与脚本

### 新建脚本: `scripts/staged_full_scan.py`

模板基于 `scripts/pipeline_full_scan.py` (138 行)，扩展:

```
scripts/staged_full_scan.py [--stage canary|medium|full] [--seed 42] [--checkpoint-dir data/checkpoints/]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--stage` | `canary` | canary=20股, medium=500股, full=全部 |
| `--seed` | 42 | 随机采样种子 (仅 medium 模式) |
| `--checkpoint-dir` | `data/checkpoints/fullscan/` | 检查点目录 |
| `--max-workers` | `None` (auto) | 并行线程数 |
| `--report-dir` | `data/fullscan/` | 报告输出目录 |
| `--error-file` | `data/fullscan/errors.csv` | 错误明细 CSV |

### 依赖

- `unquant.services.ServiceContainer` — DAG 初始化
- `UnifiedResearchPipeline.run_batch()` — 批量执行
- `UnifiedBacktestEngine` — 回测引擎
- `AnalysisEngineFactory` — 引擎惰性加载
- `ResultStore` — 结果持久化 (Phase 5 Thread D)

### 输出文件汇总

```
data/
├── fullscan/
│   ├── report_summary.json       # 各阶段汇总统计
│   ├── engine_breakdown.json     # 引擎级别成功/失败分布
│   ├── signal_distribution.json  # 信号按 source/action 分布
│   ├── trade_analysis.json       # 回测结果聚合统计
│   ├── error_details.csv         # 每只股票的错误明细
│   └── error_classification.json # 错误归类统计
└── checkpoints/
    └── fullscan/
        ├── {symbol}.json         # 每只股票的 checkpoint
        └── completed.txt         # 已完成 symbol 列表
```

---

## 执行计划

| 步骤 | 操作 | 预期耗时 |
|---|---|---|
| 1 | 编写 `scripts/staged_full_scan.py` | ~30 min |
| 2 | 运行 Phase 1 (Canary 20) | ~2 min |
| 3 | 分析 Phase 1 结果 | ~3 min |
| 4 | 运行 Phase 2 (Golden 100) | ~8 min |
| 5 | 分析 Phase 2 结果 | ~5 min |
| 6 | 运行 Phase 3 (Medium 500) | ~40 min |
| 7 | 分析 Phase 3 结果 | ~10 min |
| 8 | 运行 Phase 4 (Full 5934) | ~2 h |
| 9 | Phase 5 深度分析 | ~30 min |
| 10 | 生成最终报告 | ~15 min |
| | **总计** | **~4 h** |

---

## 成功标准

| 标准 | 阈值 | 测量方式 |
|---|---|---|
| 管线初始化成功率 | 100% | ServiceContainer.initialize() |
| 单股执行成功率 | > 95% | result.success |
| 信号产生率 | > 10% | with_signals / total |
| 交易产生率 | > 5% | with_trades / total |
| Overflow 异常 | 0 | fail-fast guard |
| ThreadPoolExecutor 死锁 | 0 | 正常完成 |
| 检查点恢复正确性 | 100% | 删除检查点后重新运行验证 |
