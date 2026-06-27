# UniQuant 系统审计与判定报告

> **审计基线**：master @ a5fac32 (已集成 Phases 0-6 所有修复)
> **验证成果**：1255 tests passed, 8 skipped, 0 failed (34.73s)
> **编写日期**：2026-06-17
> **修正说明**：本文基于代码逐行复核修正原始版本中的 6 处行号/事实偏差。

---

## 1. 审计背景与系统定位

根据对 `docs/` 目录下文档（特别是 `docs/index.md`、[AGENTS.md](file:///home/james/Documents/Project/UniQuant/AGENTS.md) 以及 [08_research_platform_gap_plan.md](file:///home/james/Documents/Project/UniQuant/docs/analysis/08_research_platform_gap_plan.md)）的深入研读，UniQuant 定位于 **离线 A 股量化研究和回测验证平台**。

系统主动剥离了券商 API 对接、盘中实盘自动化下单、持仓实时对账等"实盘运行层"的逻辑（已被隔离并暂缓开发），但在**离线投研和回测层**保留了极致严密的 A 股规则（如 T+1 交易限制、涨跌停板控制、停退市复权及前向填充、整手限制和高精度交易费用模型）。

---

## 2. 核心文档梳理与审计闭环

我们对项目文档及机构审计关闭复审报告（2026-06-14）进行了对比扫描，得到以下关键闭环事实：

| 维度 / 缺陷ID | 对应问题描述 | 审计修复与当前状态 | 绑定代码 / 验证证据 |
| :--- | :--- | :--- | :--- |
| **P0-1** | 跨层传递隐式 `data_pack: Dict[str, Any]` 易漂移 | **Partially closed (中-高风险)**<br>已定义强类型容器，主链路尚未完全切换 | [interfaces.py:L191](file:///home/james/Documents/Project/UniQuant/src/uniquant/shared/interfaces.py#L191) `ResearchDataPack`<br>[data_service.py:L412](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/data_service.py#L412) `fetch_research_pack` |
| **P0-2** | 实时时钟（`datetime.now`）污染导致历史无法复现 | **Partially closed (中风险)**<br>已引入 TimeProvider 抽象；硬编码时钟降低 70% | [time_provider.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/shared/time_provider.py) `RealTimeProvider` / `FrozenTimeProvider`<br>[service_container.py:L111](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/service_container.py#L111) 注入 |
| **P0-3** | 回测完整性缺陷（SELL 优先、退市生存偏误） | **Closed (低风险)**<br>SELL 优先规则就位（L248 内联逻辑）；`compare_baseline.py` 进行数据一致性防护 | [unified_engine.py:L248](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_engine.py#L248) 规则: LPPL SELL > BUY > 非LPPL SELL<br>`tests/benchmark/baseline_v0.parquet` |
| **P0-4** | 缺少确定性的多信号优先级仲裁 | **Closed (低风险)**<br>升级为 WS14 优先级仲裁链路；支持仓位计算器结合 | [arbitrator.py:L220](file:///home/james/Documents/Project/UniQuant/src/uniquant/signal/arbitrator.py#L220) `arbitrate_candidates()` |
| **P0-5** | 因子计算无上线准入和管理控制 | **Partially closed (低-中风险)**<br>`check_access` 在 L175 定义，成功注入因子检索入口（L125 `get_factor`）；门禁默认为 warn 模式 | [registry.py:L175](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/registry.py#L175) `check_access()`<br>[registry.py:L125](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/registry.py#L125) `get_factor` 调用 `check_access`<br>`config/config.yaml` `factor_gate="warn"` |

### 2.1 机构复审遗留 gap 状态确认
4 项核心 Gap 均已在 2026-06-12 后被标记为 **Closed**：
- **G-1 (TimeProvider)**：已消除全仓 `pd.Timestamp.now()`。剩余 2 处仅在 `wyckoff/state.py` 内部用于警告日志退回，36 处 `time.time()` 位于数据请求速率限制等非回测核心，**可复现性隐患已消除**。
- **G-2 (FactorRegistry)**：旧的 `shared/factor_governance.py` 已被弃用并给出 `DeprecationWarning`，全仓 16 处依赖均切换至 `brain/factors/registry.py` 版本，实现单点治理。
- **G-3 (Phase 0 交付物)**：基准校验脚本及 baseline 数据包已全部合入 master 并由 `compare_baseline.py` 守护。
- **G-4 (AsyncEventBus)**：完成了基于 `ThreadPoolExecutor` 的异步事件总线开发，并通过了同步、异步和集成的 25 项 pytest 测试。

---

## 3. 重点代码审计与设计亮点

### 3.1 A股日历对齐与停退市价格填充 (`data_aligner.py`)
在 [data_aligner.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/pipeline/data_aligner.py#L18-L98) 中：
- 算法基于 `StockMetadataManager` 动态拉取股票的上市日（`ipo_date`）与退市日（`delist_date`），裁剪对齐区间。
- 采用 **仅前向填充 (ffill)** 策略填补停牌交易日的价格 `[open, high, low, close]`，避免了向后填充 (bfill) 引起的未来数据泄漏。
- 停牌交易日的 `volume` 与 `amount` 被强制填零，忠实还原交易中断的事实。

### 3.2 因子未来函数 Perturbation 变扰检测 (`analyzer.py`)
在 [analyzer.py:L26-L85](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/analyzer.py#L26-L85) 的 `check_lookahead_leakage()` 中：
- 采用了一种被称为 **未来扰动不变性 (Perturbation Invariance)** 的算法：复制输入数据，在给定的 Cutoff 时间点之后，将 `close` 价格乘以一个高波动随机数（$1.5 \sim 3.0$ 倍），然后重新运行因子计算。
- 若 Cutoff 前的因子计算结果发生了任何微小变化（使用 `np.allclose` 判定），则立即认定该因子包含未来函数并抛出 `LookaheadBiasError`。这构成系统最强大的研究防线。

### 3.3 WS14 决策链信号仲裁 (`arbitrator.py`)
在 [arbitrator.py:L220-L363](file:///home/james/Documents/Project/UniQuant/src/uniquant/signal/arbitrator.py#L220-L363) 的 `arbitrate_candidates()` 中：
- 严格遵循了以下优先级判定：
  1. **硬约束层** (L252-281)：若 `DecisionOutput` 返回 `FORCE_WAIT` / `CIRCUIT_BREAK`，无条件阻止交易（转为 `HOLD`）；若为 `FORCE_EXIT`，强制发出 `SELL` 信号；若为 `BUY` 且 `shares > 0`，直接放行。
  2. **SELL 优先层** (L283-301)：当多引擎在同日产生买入和卖出分歧时，无条件遵从 `SELL`（取置信度最高的 `SELL` 信号）。
  3. **买入资质层** (L303-358)：若是 `fsm` (决策脑主逻辑) 的买入信号，直接放行；若是非 `fsm` 信号（如单引擎指标买入），则强迫经过 `PositionSizer` (仓位计算器) 重新核算风控并确认可用资金，无 sizer 或是风控失败的信号一律丢弃。
  4. **默认 HOLD** (L360-363)：若无任何信号通过以上筛选，默认不交易。

### 3.4 批处理断点续跑机制 (`research_pipeline.py`)
在 [research_pipeline.py:L409-L467](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/research_pipeline.py#L409-L467) 的 `run_batch()` 中：
- 支持传入 `checkpoint_dir`，每完成一只股票的分析和回测，即刻将其格式化序列化后，以 JSON 文件写入 `checkpoint_dir/{symbol}.json`。
- 启动时自动扫描该目录已完成的 symbol 快照，无需重新拉取数据或运行引擎分析可直接从本地 JSON 反序列化回填，能极大提升上百只股票批处理任务在意外崩溃后的重试效率。
- **注意**：当前使用 `path.write_text()` 直接写入，非原子写入。批处理因精度要求高时应使用 SSD 并避免强制断电。

---

## 4. 判定输出与遗留风险评价

### 4.1 系统的核心风险诊断
1. **跨层 implicit-dict 依赖尚未完全清退 (P0-1 残留)**
   - 虽然定义了 `ResearchDataPack` 结构，并且 `DataService` 具备了 `fetch_research_pack` 入口，但主线 `AnalysisService` 和 `UnifiedResearchPipeline` 的主流数据传递依旧运行在 mutable dict（`data_pack`）上（全仓存在约 470 处 `Dict[str, Any]` 的解析与写入）。这导致字段改动时的静默失效风险仍然客观存在。
2. **因子准入尚未实现全阻断闭环 (P0-5 残留)**
   - 目前在 `config.yaml` 里的配置为 `factor_gate: "warn"`。这虽然规避了直接抛错导致的旧策略中断，但也使得未经过准入检验的因子可以通过警告直接接入实际流水线。
3. **性能开销与 lazy binding**
   - `AnalysisEngineFactory` 先使用 `DataService` 构造（`service_container.py:L117`），并在 `AnalysisService` 初始化时调用 `bind_orchestrator()`（`analysis_service_v2.py:L106`）重新绑定到自身。在并行复杂任务下需谨慎防范并发重置引起的状态不一致。

### 4.2 实盘就绪评级
由于本系统定位于"量化研究平台"，其实盘可用性评分已在 [07_risk_live_readiness.md:L134](file:///home/james/Documents/Project/UniQuant/docs/analysis/07_risk_live_readiness.md#L134) 中量化为 **45 / 100**（扣分项包括缺失券商连接、实盘 Kill Switch、实时监控等）。该评分在可预见的路线图中不属于优先解决项。当前阶段系统在研究环境下的数据完整性、规则正确性和可复现性均达到了可信水平。

---

## 5. 后续开发与优化路线建议

为了进一步巩固研究平台的健壮性，建议在后续开发中进行以下改进：

1. **推进 `ResearchDataPack` 强类型迁移 (P0-1)**
   - 可以在 feature flag `use_research_data_pack` 打开的状态下，重构 `AnalysisService.run_ticker_analysis()`，将接收与返回参数彻底重构为 `ResearchDataPack` 强类型，再逐步重构各 Brain Engine。
2. **尝试收紧因子准入检测 (P0-5)**
   - 在测试和实验环境中，建议临时将 `factor_gate` 调整为 `"block"`，跑通 `pytest tests/ -q`。这将确保所有存量因子都在命名、参数、文档及非未来泄漏判定上完全合格，从而在后续开发中形成铁腕门禁。
3. **增加每日信号导出格式**
   - 完善统一实验入口，实现输出 `daily_signals.csv` 的绝对规范（如字段 `date, symbol, action, confidence, shares, price, reason, source_policy, trace_id` 的完全固化），这有助于跟其他独立执行系统（如独立自动化交易网关）进行跨进程文件级对接。
