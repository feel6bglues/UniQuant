# 阶段 1: 总体架构映射

生成时间: 2026-06-08

范围: 只做全局拓扑扫描和高危耦合识别，不进入逐行漏洞修复。下一阶段必须只读取本文件恢复阶段 1 记忆。

## 0. 启动提示词适用性判断

结论: 该提示词适用于 UniQuant 当前状态，但必须做工程化约束，否则容易变成一次超大范围、低精度审计。

适用点:

- 项目体量大且已有历史迁移痕迹，阶段化状态机比一次性全局扫描更安全。
- 代码中确实存在并行体系、兼容层、废弃入口和大量容错返回，适合按 P0/P1/P2 分层收敛。
- “强制落盘 + Halt & Wait”能降低上下文窗口导致的遗漏，适合当前有 263 个 Python 文件、多个历史审计文档的仓库。

需要修正的点:

- “主动清空内存上下文”不能被模型真实执行，只能通过落盘、停止推进、下一阶段只读日志来模拟。
- “每完成一个子步骤都停止”如果严格应用到每个 grep 会导致工作无法推进；本轮解释为每个阶段或队列完成后挂起。
- “终极手术修复”范围过大，阶段 4 必须以阶段 3 的 P0/P1 清单为唯一输入，否则会引入无边界重构风险。
- Fail-Fast 不能简单替换所有 `return pd.DataFrame()` 或 `except`，数据源适配层有些软失败是设计目标。需要区分系统边界容错和核心计算静默失败。

## 1. 物理模块拓扑

实测文件数:

| 层 | 文件数 | 主要职责 |
|---|---:|---|
| `shared` | 37 | Protocol、常量、错误处理、缓存、成本/滑点、涨跌停、限价笼 |
| `data` | 65 | 数据源、数据湖、清洗校验、TDX/AkShare/在线源、导入脚本 |
| `brain` | 73 | FSM、CZSC、LPPL、NTF、Regime、Wyckoff、因子 |
| `risk` | 7 | 仓位、回撤、EVT、组合优化 |
| `signal` | 7 | 信号模型、适配、聚合、质量 |
| `hands` | 34 | 回测、撮合、组合引擎、策略、报告 |
| `services` | 31 | 编排服务、数据服务、分析工厂、缓存协调、研究流水线 |
| `ui` | 8 | Streamlit Dashboard 和管理器 |

当前实际依赖方向大体符合项目约定:

```text
shared -> 基础层
data -> shared
brain/risk/signal -> shared, 少量 data/risk
hands -> shared, data, brain, signal
services -> shared, data, brain, risk, signal, hands
ui -> services, shared, risk
```

扫描得到的跨层 import 计数:

| from \ to | shared | data | brain | risk | signal | hands | services | ui |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| shared | 38 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| data | 100 | 112 | 0 | 0 | 0 | 0 | 0 | 0 |
| brain | 74 | 3 | 90 | 2 | 0 | 0 | 0 | 0 |
| risk | 12 | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| signal | 2 | 0 | 0 | 0 | 11 | 0 | 0 | 0 |
| hands | 55 | 6 | 3 | 0 | 2 | 36 | 0 | 0 |
| services | 69 | 12 | 35 | 5 | 2 | 4 | 23 | 0 |
| ui | 11 | 0 | 0 | 3 | 0 | 0 | 6 | 6 |

高危反向/越层点:

- `shared.di_container` import `services.service_container`，形成 `shared -> services` 反向依赖。虽然文件标记 deprecated，但 `container = ServiceContainer.instance()` 在 import 时仍会实例化主容器别名。
- `brain` 层仍有少量 `data` 依赖，例如 NTF/CZSC/Regime/Alpha 的 deprecated “from data fetcher”路径，违反 Brain 不直接取数的 Data Lake 原则。
- `services.analysis_service_v2` 虽然是重构版编排器，但仍在 `_run_ntf` 中直接新建 `DataFetcher()`，在 `_run_alpha` 中直接新建 `StorageManager()`，绕过了容器注入和共享缓存。
- `ui.manager_portfolio_analytics_service` 直接 import `risk`，属于 UI 越过 services 的便利调用，短期可接受，长期会削弱服务层边界。

## 2. 当前 DI 树

主容器: `src/uniquant/services/service_container.py`

```text
ServiceContainer.instance()
  -> StorageManager()
  -> TradeCalendarManager()
  -> CacheCoordinator()
  -> DataService(storage_manager=storage)
  -> AnalysisEngineFactory(orchestrator=data_svc)
  -> MarketLevelCache()
  -> AnalysisService(data_service=data_svc, engine_factory=engine_factory, market_cache=market_cache)
  -> UnifiedBacktestEngine()
  -> TradingSignalCollector(create_default_registry())
  -> UnifiedResearchPipeline(analysis_service, backtest_engine, signal_collector)
```

DI 风险:

- `AnalysisEngineFactory(orchestrator=data_svc)` 与 `AnalysisService(engine_factory=engine_factory)` 存在语义不一致。分析引擎注释写 orchestrator 是 `AnalysisService`，但容器实际注入 `DataService`。若引擎未来调用 orchestrator 的分析上下文方法，会发生接口断裂。
- `AnalysisEngineFactory._lazy_init()` 捕获所有 `Exception` 后 warning 并返回 `None`。这会把引擎初始化失败降级成运行期空对象，属于阶段 2/3 需要重点确认的 P0 候选。
- `ServiceContainer.reset()` 只清 `_services`，不清 `_factories/_registrations`，`clear()` 才全清。测试环境和长进程热重载可能残留注册状态。
- `shared.di_container` 是兼容入口，导入即触发 `DeprecationWarning` 和 `container = ServiceContainer.instance()`。这不是纯类型别名，会造成隐藏全局状态。

## 3. God Object 候选

按行数、职责混杂和入口活跃度排序:

| 文件 | 行数 | 判断 | 风险 |
|---|---:|---|---|
| `src/uniquant/services/analysis_service_legacy.py` | 1644 | 旧版 God Object | 缓存、验证、采样、引擎调用、报告、扫描混在单类；仍被 `tests/test_results_protocol.py` 直接引用 |
| `src/uniquant/ui/dashboard.py` | 1526 | UI God Object | 页面、数据加载、错误处理、业务调用集中；大量 `@handle_errors(default_return=...)` |
| `src/uniquant/brain/wyckoff/engine.py` | 1457 | 算法 God Object | Wyckoff 多阶段规则、分类、融合可能过度集中 |
| `src/uniquant/data/sources/eastmoney.py` | 1092 | 数据源 God Object | 网络、解析、字段映射、容错集中在单源适配器 |
| `src/uniquant/brain/lppl/engine.py` | 1042 | 算法 God Object | LPPL 扫窗、拟合、风险输出职责集中 |
| `src/uniquant/brain/fsm/fsm.py` | 714 | 决策核心大对象 | 状态、交易约束、风险动作混杂；当前已有跌停卖出测试失败背景 |
| `src/uniquant/hands/backtest/engine.py` | 691 | 旧回测大对象 | 标记 deprecated 但仍被测试和 chaos 测试大量使用 |
| `src/uniquant/data/data_fetcher.py` | 283 | 中枢对象 | 自称“系统的大脑和总指挥”，聚合 Storage、SourceRouter、Cleaner、Validator、Adjuster、多个 Manager、Ingestion、Pipeline 和 LRU 缓存 |

注意: 行数不是充分证据。上述对象在阶段 2 需要按“是否导致静默失败、接口断裂、状态污染、不可测试”继续核实。

## 4. 并行/废弃/冗余体系

### 4.1 分析服务双轨

当前存在:

- `services/analysis_service_v2.py`: 当前 `services.__getattr__("AnalysisService")` 指向的新编排器。
- `services/analysis_service_legacy.py`: 标记 deprecated 的 1644 行旧服务。
- `services/analysis/*_analysis_engine.py`: 工厂懒加载的引擎层。
- `services/analysis/macro_service.py`、`technical_service.py`、`signal_service.py`: 服务化分析入口，和 engine 命名并行。

风险:

- 旧服务仍被测试直接引用，不能直接删除。
- `services/analysis/__init__.py` 只导出 Macro/Technical service，不导出工厂中的多数 engine，命名边界不统一。
- v2 重构后仍保留多处 fallback 默认值，核心引擎失败可能被转换为 `"Safe"`、`"NORMAL"`、`0.0` 等业务默认。

### 4.2 回测/撮合三轨

当前存在:

- `hands/backtest/unified_engine.py`: 推荐入口，强类型 `TradingSignal`。
- `hands/backtest/unified_matching_engine.py`: A 股撮合核心，PortfolioEngine 已复用。
- `hands/backtest/engine.py`: deprecated 单资产 `BacktestEngine`，仍被包导出和多组测试使用。
- `hands/backtest/portfolio_engine.py`: deprecated 组合 `PortfolioEngine`，仍被测试和 E2E 直接使用。

风险:

- 包 `hands/backtest/__init__.py` 仍导出 `BacktestEngine`，但没有导出 `PortfolioEngine`；模块直 import 仍可用。
- 同一业务存在 `BacktestResult/TradeRecord` 两套定义: `unified_engine.py` 和 `result.py`。
- 旧 `BacktestEngine` 和新 `UnifiedBacktestEngine` 的行为可能长期漂移，尤其是 T+1、涨跌停、资金扣减、滑点。

### 4.3 数据入口多轨

当前存在:

- `data/data_fetcher.py`: 高层聚合入口，内部持有 `DataIngestionService` 和 `DataPipelineService`。
- `services/data_service.py`: 服务层数据入口，默认会自行创建 `DataFetcher()`。
- `data/lake/storage_manager.py`: 数据湖读写入口。
- 多个 managers: `market_data_coordinator`、`stock_data_updater`、`cache_manager`、`tdx_updater` 等。

风险:

- `DataFetcher` 和 `DataPipelineService` 默认各自创建/持有资源，可能造成 StorageManager 和缓存状态不共享。
- `DataService` 有自己的缓存协调逻辑，`DataFetcher` 有 `_price_cache`，`MarketLevelCache` 又有市场级缓存，失效广播边界不明确。
- 数据源初始化失败时会跳过，所有源失败时仍可构造空 fetcher。这适合可用性，但对研究流水线可能造成静默空数据。

### 4.4 DI 容器双轨

当前存在:

- `services.service_container.ServiceContainer`: 主容器。
- `shared.di_container.DIContainer/container`: deprecated 兼容别名。

风险:

- shared 层反向依赖 services 层，是 DAG 规则的明确例外。
- 兼容别名会在 import 时创建单例状态，可能影响测试隔离。

## 5. 高危耦合点

1. Brain 输出到 Hands 输入的契约仍是系统最高风险边界。`TradingSignal.from_dict()` 已提供 `"EXECUTE_BUY" -> "BUY"` 等映射，但需确认所有生产路径都经过该适配器，而不是直接把 DecisionBrain dict 喂给旧 BacktestEngine。
2. `AnalysisEngineFactory._lazy_init()` 对引擎初始化失败返回 `None`，而 `AnalysisService` 对子引擎失败继续填默认业务值，形成“引擎静默失效但整体分析成功/失败不明显”的组合风险。
3. 缓存体系分散: `CacheCoordinator`、`MarketLevelCache`、`DataService` cache、`DataFetcher._price_cache`、底层 CacheFactory 并存。阶段 2 队列 A 需要检查缓存失效广播和 stale data 风险。
4. 数据获取存在“系统边界容错”和“核心计算容错”混用。数据源失败返回空 DataFrame 可接受，但核心数据校验、因子、撮合失败返回空值会污染研究结论。
5. `ServiceContainer.initialize()` 的 DI 注入不是全覆盖，服务内部仍自行 new `DataFetcher()`、`StorageManager()`，导致容器宣称的 DAG 和实际运行对象图不完全一致。
6. UI 直接进入 services/risk 并持有大量 default-return 错误处理，适合交互体验，但会掩盖平台层错误。

## 6. 阶段 2 必查清单

队列 A 数据与基础设施:

- 搜索 `.shift(-1)` 并区分标签构造、未来收益计算、交易信号生成三类场景。
- 检查 `DataPipelineService -> DataCleaner -> DataValidator -> DataAdjuster` 的返回值契约。
- 检查 `CacheCoordinator`、`MarketLevelCache`、`DataFetcher._price_cache` 是否有统一 invalidation。

队列 B 核心算法与因子:

- 检查 `brain/factors/composer.py`、`custom_factors.py`、`auto_mined/*` 的高相关因子合成和除零/空样本默认。
- 检查 FSM、LPPL、Wyckoff 阈值是否导致长期 HOLD/unknown/Safe。
- 检查 engine 输出是否全都能转换为 `MarketSignalContext`/`TradingSignal`。

队列 C 撮合与风控:

- 用连续涨停、连续跌停、停牌 volume=0、资金不足、非整手、ST/创业板/北交所、新股上市天数攻击 `UnifiedBacktestEngine`、`BacktestEngine`、`PortfolioEngine`。
- 对比旧新回测引擎的 T+1、涨跌停、现金扣减和滑点一致性。

队列 D 异常处理与可重现性:

- 重点审查 `@handle_errors(... default_return=...)`、`except Exception`、裸 `pass/continue`、`return pd.DataFrame()`。
- 已发现随机入口: `hands/backtest/monte_carlo.py` 使用 `np.random.seed`、`np.random.permutation`、`np.random.choice`；`data/sources/realtime_bridge.py` 和 `data/sources/tencent.py` 使用 `random.*`；`data/sources/sina.py` 使用随机 sleep。
- 区分测试/模拟随机、网络退避随机、研究结果随机。研究结果随机必须支持注入 seed 或 RNG。

## 7. 本阶段证据命令

主要只读命令:

```bash
rg --files -g 'pyproject.toml' -g 'src/uniquant/**/*.py' -g 'tests/**/*.py' -g 'config/**/*.yaml' -g 'docs/**/*.md'
sed -n '1,260p' src/uniquant/services/service_container.py
sed -n '1,260p' src/uniquant/services/analysis/engine_factory.py
sed -n '1,220p' src/uniquant/shared/di_container.py
python3 - <<'PY'  # AST import matrix and file line counts
rg -n 'analysis_service_legacy|analysis_service_v2|BacktestEngine|UnifiedBacktestEngine|PortfolioEngine|DataFetcher|ServiceContainer|deprecated|Legacy' src tests docs -g '*.py' -g '*.md'
rg -n 'np\.random|random\.|default_rng|seed\(|shift\(-1\)|except .*:|pass$|continue$|default_return=|return pd\.DataFrame\(\)' src/uniquant -g '*.py'
```

阶段 1 未运行测试，未修改业务代码。
