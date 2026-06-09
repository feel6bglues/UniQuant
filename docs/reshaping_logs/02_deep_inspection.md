# 阶段 2: 分段深度核查

生成时间: 2026-06-08

恢复上下文: 本阶段启动前已重读 `docs/reshaping_logs/01_global_topology.md`。本文件是阶段 3 的唯一输入之一。

范围: 队列 A-D 的对抗性白盒审查。未修改业务代码。

## 总览

本阶段确认的高优先级风险:

- `AnalysisEngineFactory` 由 `ServiceContainer` 注入 `DataService`，但 FSM/Wyckoff 等分析适配器按旧版 `AnalysisService` 接口调用 `_get_cached_result/_optimize_dataframe/_sample_data/ensure_precision_consistency`。这是实际接口契约断裂。
- `AnalysisService.run_ticker_analysis()` 返回 `decision`，但 `UnifiedResearchPipeline` 的 `TradingSignalCollector` 只读取 `data_pack`；最终 FSM 决策未注入 `data_pack`，可能不会进入回测信号列表。
- 多个核心引擎失败被降级为业务默认值，例如 Regime=`NORMAL`、LPPL=`Safe`、Alpha=`0.0`、Wyckoff=`unknown`，形成“分析结果看似成功但子引擎已失效”的风险。
- 数据对齐器对区间首行缺失价格使用 `bfill`，可能把未来价格填到前序停牌日。该逻辑对回测有前视偏差风险。
- 宏观分析在无真实收益数据时使用未注入 seed 的 `np.random.normal()` 生成随机收益，导致同一输入不可复现。
- Monte Carlo 支持 seed，但旧 `BacktestEngine` 调用时未传 seed，报告元数据不可复现。

## 队列 A: 数据与基础设施

### A1. `.shift(-1)`/负 shift

发现:

- 直接负 shift 主要集中在 `brain/factors/analyzer.py` 的离线未来收益标签计算。
- 该模块有 `mode="live"` 防护和显式 lookahead 文档，`_compute_forward_returns()` 与 `compute_ic_ir()` 在 live 模式会抛 `ValueError`。
- 未在数据清洗链、服务编排链发现直接用 `.shift(-1)` 生成交易信号的证据。

判断:

- 因子 IC 的负 shift 是离线标签构造，不能直接判为 bug。
- 阶段 3 应把“离线/实盘模式边界”列为工程约束: 所有调用 `compute_ic_ir()` 的入口必须明确传 `AnalysisMode.BACKTEST` 或禁止实盘路径调用。

### A2. 数据清洗/校验链

证据:

- `data/data_pipeline_service.py` 顺序为 `cleaner.clean_stock_daily()` -> `validator.validate()` -> `adjuster.apply_adjustment()`。
- `DataCleaner.clean()` 会修复 `high < open/close` 和 `low > open/close`。
- `DataValidator.validate()` 再次修复 `High < Low`、`High < Open/Close`、`Low > Open/Close`，并返回 bool。

判断:

- OHLC 异常修复链当前是存在的，与阶段 1 历史背景中“high<open/close 未自动修复”的描述不完全一致。若测试仍失败，重点应检查测试是否绕过 `DataCleaner/DataValidator`，或调用的是 `DataAligner` 而不是 `DataPipelineService`。

### A3. 数据对齐前视偏差

证据:

- `src/uniquant/data/pipeline/data_aligner.py:77-83` 对停牌/缺失价格先 `ffill()`，如果首行仍 NaN 再 `bfill()`。

风险:

- 如果查询窗口从停牌期间开始，`bfill()` 会把窗口内未来第一条真实成交价回填到更早的停牌日。
- 这会让回测在停牌日看到未来价格。即使 volume/amount 被置 0，价格列仍可能影响权益曲线、指标和信号。

建议候选:

- 对窗口首部没有历史价格的停牌行不要 bfill；应删除这些行、保留 NaN 并由上层禁止交易，或要求从 IPO/上一有效交易日前扩展读取窗口。

### A4. 复权前视偏差

证据:

- `DataAdjuster.apply_adjustment()` 使用 `pd.merge_asof(... direction="backward")`。
- QFQ 使用 `latest_factor = df_merged["factor"].iloc[-1]`，且注释说明使用当前 df 最后一日因子避免泄露绝对最新除权事件。
- `get_adjusted_data()` 对 qfq/hfq 传入 `cutoff_date=end_date`。

判断:

- 复权逻辑已经有 point-in-time 意识。阶段 3 不应把它列为 P0，除非队列 A 后续能证明调用方传入了未来范围内的 df。

### A5. 缓存失效边界

证据:

- 并存缓存: `CacheCoordinator` 磁盘缓存、`MarketLevelCache`、`DataFetcher._price_cache`、`StorageManager` 数据湖、`shared.cache` 后端。
- `DataService.rebuild_cache()` 会写湖并设置 `datalake:` key，但未发现广播清理 `DataFetcher._price_cache` 或 `MarketLevelCache` 的逻辑。
- `MarketLevelCache` 只按自然日 `_today()` 失效，benchmark 没有日期判断。
- `DataFetcher._price_cache` 只按 LRU 大小淘汰，没有 TTL 和外部 clear 方法。

风险:

- 同一 symbol 更新后，服务缓存、fetcher LRU、市场级缓存可能出现不一致。
- 市场级 Regime/NTF 在自然日内不随底层指数数据刷新而失效。

严重度候选:

- P1: 缓存污染/陈旧数据风险。

## 队列 B: 核心算法与因子

### B1. 因子配置静默失败

证据:

- `src/uniquant/brain/factors/registry.py:65-78` 在读取 `factors.yaml` override 时捕获 `Exception` 后 `pass`。

风险:

- 配置文件路径错误、YAML 结构错误、配置 loader 行为异常都会被吞掉，因子继续按默认权重注册。
- 这会让因子启停和权重配置失效，但系统表面仍正常运行。

严重度候选:

- P0/P1 边界: 如果配置用于生产策略权重，则是 P0 静默配置失效；若只影响研究默认，则 P1。

### B2. 共线性防线存在但降级不透明

证据:

- `FactorComposer` 默认 `orthogonalize=True`，使用对称正交化消除多因子共线性。
- 若 `linalg.eigh` 失败，仅 warning 并返回原始因子。
- 单个因子计算失败时记录 error 并继续，最终 composite 可能少列。

判断:

- 共线性灾难已有工程防线，不是完全缺失。
- 但“因子缺失/正交化失败后继续产出 composite_score”需要显式暴露元数据，否则研究结论会不可审计。

严重度候选:

- P1: 因子可观测性和研究可追踪性不足。

### B3. 引擎适配器与 DI 契约断裂

证据:

- `src/uniquant/services/service_container.py:96` 创建 `AnalysisEngineFactory(orchestrator=data_svc)`。
- `src/uniquant/services/analysis/fsm_analysis_engine.py:42-64` 调用 `orchestrator._generate_cache_key/_get_cached_result/data_service/_optimize_dataframe/_sample_data`。
- `src/uniquant/services/analysis/wyckoff_analysis_engine.py:22-38` 同样调用旧 orchestrator 接口。
- `src/uniquant/services/analysis/engine_factory.py:30-32` 捕获所有初始化异常后返回 `None`。

风险:

- 容器注入的是 `DataService`，但 FSM/Wyckoff adapter 需要旧 `AnalysisService` 能力。
- 当 `analysis_service_v2._run_wyckoff()` 调用 `self.wyckoff_engine.run_wyckoff_analysis()` 时，`self.wyckoff_engine` 内部 orchestrator 可能没有这些方法，触发 AttributeError，被上层吞为 `wyckoff_phase="unknown"`。
- 这会使引擎成为“哑巴”，且业务结果不会明确暴露 root cause。

严重度候选:

- P0: 接口类型断裂 + 静默默认值。

### B4. 最终 FSM 决策未进入统一信号收集

证据:

- `src/uniquant/services/analysis_service_v2.py:154-168` 计算 `decision` 并放入 `TickerAnalysisResult.decision`，但不写入 `data_pack`。
- `src/uniquant/signal/adapters.py:481-487` 只有当 `data_pack` 有 `"action"` 或 `"final_decision"` 才运行 FSMAdapter。
- `UnifiedResearchPipeline.run()` 调用 `self._collector.collect(data_pack, ...)`，没有把 `analysis.decision` 合并进去。

风险:

- 最终 `DecisionBrain.make_decision()` 的 BUY/SELL/HOLD 可能不会进入回测。
- 回测仍可能收到 MA/CZSC/Alpha/Wyckoff 的信号，因此 E2E 测试可通过，但“最终决策到执行”的主链路断裂。

严重度候选:

- P0: Brain 输出到 Hands 输入的标准契约断裂。

### B5. 引擎默认值导致“安全偏置”

证据:

- `analysis_service_v2._run_regime()` 失败后 `regime="NORMAL"`。
- `_run_lppl()` 失败后 `risk="Safe"`、`bubble_confidence=0.0`。
- `_run_wyckoff()` 失败后 `wyckoff_phase="unknown"`、`confidence=0.0`。
- `_run_alpha()` 失败后 `alpha_score=0.0`。

风险:

- 失败路径被编码成低风险/无信号，容易让系统在关键风险引擎不可用时继续给出看似完整的分析结果。

严重度候选:

- P0: 对 LPPL/Regime 这类风险闸门，失败不能默认为 Safe/NORMAL。

## 队列 C: 撮合与风控

### C1. 新撮合防线通过现有边界测试

已运行:

```bash
python3 -m pytest tests/test_unified_matching.py tests/test_t1_constraint_boundary.py -q
python3 -m pytest tests/chaos/test_matching_auditor.py -q
python3 -m pytest tests/test_e2e_pipeline.py -q
```

结果:

- 31 passed, 1 warning
- 20 passed, 1 warning
- 8 passed, 2 warnings

额外恶意样本:

```text
limit_up_buy_trades 0
suspension_sell_trades [('BUY', 100, 9.906)]
final_cash_nonnegative True
```

判断:

- `UnifiedBacktestEngine` 和 `UnifiedMatchingEngine` 对涨停买入、停牌卖出、T+1、资金不透支已有有效防线。

### C2. 新旧引擎并存仍是风险

证据:

- `hands/backtest/engine.py` 标记 deprecated，但仍被包导出、测试和 chaos 测试使用。
- `hands/backtest/portfolio_engine.py` 标记 deprecated，但仍有 E2E/portfolio 测试调用。
- `hands/backtest/__init__.py` 仍导出 `BacktestEngine` 和旧 `BacktestResult/TradeRecord`。

风险:

- 用户从包入口拿到旧引擎是合理路径，不是死代码。
- 新旧引擎行为长期漂移会让同一策略在不同入口结果不同。

严重度候选:

- P1: 并行撮合体系。

### C3. 旧 `BacktestEngine` 内部有非确定性报告元数据

证据:

- `hands/backtest/engine.py` 在交易数 >= 20 时调用 `MonteCarloSimulator(...).run_shuffle()` 和 `run_bootstrap()`，未传 seed。
- `MonteCarloSimulator` 默认 `seed=None`，内部使用全局 `np.random`。

风险:

- 同一回测输入可能产生不同 metadata。
- 失败后仅 `logger.exception(...); pass`，不会影响回测主体结果。

严重度候选:

- P2/P1: 若报告 metadata 用于策略筛选，升为 P1。

## 队列 D: 异常处理与可重现性

### D1. 全局异常/默认返回面

统计:

| 模式 | 次数 | 文件数 |
|---|---:|---:|
| `@handle_errors` | 88 | 30 |
| `default_return=` | 88 | 30 |
| `except Exception` | 233 | 81 |
| `pass` | 117 | 50 |
| `continue` | 164 | 59 |
| `np.random` | 21 | 6 |
| `random.` | 45 | 16 |
| `RandomState` | 1 | 1 |
| `seed(` | 5 | 3 |

重要边界:

- `handle_errors()` 默认 `reraise=True`，所以不是所有 `default_return` 都会吞异常。
- 真正显式 `reraise=False` 的装饰器集中在 CZSC、AlphaDecoupler、RegimeDetector 和 `safe_*` 包装器。
- 大量显式 `try/except` 仍然会直接返回默认值，不受 `handle_errors` 默认行为保护。

### D2. 明确静默/半静默风险点

核心路径:

- `FactorRegistry.register()` 读取配置失败后裸 `pass`。
- `AnalysisEngineFactory._lazy_init()` 捕获所有 `Exception` 后返回 `None`。
- `analysis_service_v2` 对 Regime/LPPL/CZSC/Wyckoff/Alpha 的失败统一降级为默认业务值。
- `FsmAnalysisEngine`、`WyckoffAnalysisEngine` 的旧 orchestrator 调用失败会被上层转换为默认值。
- `RegimeDetector.detect()` 使用 `reraise=False`，异常时返回 `Regime.UNKNOWN`。
- `AlphaDecoupler` 多个入口使用 `reraise=False`，异常时返回默认 benchmark 或 `0.0`。

边界可接受:

- 数据源 adapter 网络失败返回空 DataFrame，可视为边界容错。
- 请求退避 `random.uniform()`、User-Agent `random.choice()` 不影响研究结果确定性，低优先级。

### D3. 未注入 seed/全局 RNG

研究结果相关:

- `hands/backtest/monte_carlo.py`: 支持 seed，但默认 None，并使用全局 `np.random.seed/permutation/choice`。
- `hands/backtest/engine.py`: 调用 Monte Carlo 时未传 seed。
- `services/analysis/macro_service.py` 和 `services/analysis/macro_analysis_engine.py`: 无真实收益时用 `np.random.normal()` fallback，没有 seed/RNG 注入。
- `hands/strategies/backtest.py`: `_block_bootstrap()` 使用 `np.random.choice()`；主入口会 `np.random.seed(RANDOM_SEED)`，但函数本身没有 RNG 参数。
- `brain/lppl/numba_optimizer.py`: 有默认 `seed=42`，不是未注入；但全局 seed 方式仍会影响并发可复现性，需要低优先级复核。

非研究结果相关:

- `data/sources/realtime_bridge.py` mock tick 使用 `random.random/randint`，属于模拟数据，不应进入生产分析。
- 数据源请求退避和 UA 随机属于网络策略，不列为 P0。

严重度候选:

- P0: 宏观分析随机 fallback 影响风险判断且无 seed。
- P1: Monte Carlo 报告 metadata 默认不可复现。

## 阶段 2 验证记录

只读扫描:

```bash
rg -n "shift\\(-1\\)|future|label|target|next_|pct_change\\(|rolling\\(" src/uniquant/data src/uniquant/brain/factors src/uniquant/brain src/uniquant/services -g '*.py'
rg -n "@handle_errors|default_return=|except Exception|pass$|continue$|np\\.random|random\\." src/uniquant -g '*.py'
```

通过的测试:

```bash
python3 -m pytest tests/test_unified_matching.py tests/test_t1_constraint_boundary.py -q
python3 -m pytest tests/chaos/test_matching_auditor.py -q
python3 -m pytest tests/test_e2e_pipeline.py -q
```

合计: 59 passed，未修改业务代码。

## 阶段 3 输入摘要

建议阶段 3 聚合时优先碰撞以下问题:

- P0 候选: `AnalysisEngineFactory` orchestrator 注入类型断裂。
- P0 候选: FSM 最终决策没有进入 `TradingSignalCollector`。
- P0 候选: 风险引擎失败默认 Safe/NORMAL。
- P0 候选: `DataAligner.bfill()` 对停牌首段可能引入未来价格。
- P0/P1 候选: 因子配置加载失败裸 `pass`。
- P1 候选: 多层缓存无失效广播。
- P1 候选: 新旧回测/撮合体系并行且旧入口仍活跃。
- P1 候选: Monte Carlo 和宏观 fallback 的 RNG 注入不完整。
