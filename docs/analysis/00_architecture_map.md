# Stage 0 — UniQuant 全局架构识别

> 生成日期: 2026-06-29
> 基于当前工作树 (commit c1e0eb1, 254 文件, 62,816 LOC)
> 方法: 阅读 AGENTS.md, docs/index.md, pyproject.toml, config/config.yaml, 扫描 src/uniquant/ 全目录, 阅读核心流程文件

---

## 1. 系统定位

UniQuant 是一个面向中国 A 股的量化投研与交易平台。Python 3.12+，254 个源文件，覆盖：

- 多源数据接入与数据湖存储（TDX 本地、AKShare、mootdx 在线/离线、东方财富、新浪等）
- 因子研究（注册、计算、IC/IR 分析、组合、中性化、滚动验证）
- 信号生成（FSM、CZSC 缠论、LPPL、NTF 国家队、Regime 市场状态、Wyckoff 威科夫、Alpha 选股）
- 风险度量（仓位、回撤、EVT、组合优化）
- 回测与撮合（T+1、涨跌停、停牌、滑点、费用）
- 服务编排（DAG 依赖注入容器）
- Streamlit 仪表盘

---

## 2. 八层模块职责表

| 层 | 路径 | 文件数 | 职责 | 关键依赖方向 |
|---|------|-------|------|-------------|
| `shared` | `src/uniquant/shared/` | 44 | 协议接口、常量、配置、异常、缓存、日志、A 股规则、费用、滑点、价格约束、时间提供器、事件总线、因子治理、特征标记 | 所有层依赖 shared |
| `data` | `src/uniquant/data/` | 65 | 多源数据接入 (TDX/AKShare/东方财富/新浪/腾讯)、数据湖 (DuckDB + Parquet)、清洗、校验、复权、对齐 | → services (DataService 封装) |
| `brain` | `src/uniquant/brain/` | 55 | 7 个策略引擎: FSM 状态机、CZSC 缠论、LPPL 泡沫、NTF 国家队、Regime 市场状态、Wyckoff 威科夫、Alpha 选股 + 因子系统 + 指标 | → services (AnalysisEngine 封装) |
| `signal` | `src/uniquant/signal/` | 8 | TradingSignal 模型、引擎输出适配器、聚合、归一化、质量检查、仲裁器 | → services (research_pipeline) |
| `hands` | `src/uniquant/hands/` | 34 | 回测引擎 (typed unified + legacy)、向量化撮合、投资组合、策略框架、报告、稳健性/敏感性工具 | → services (research_pipeline) |
| `risk` | `src/uniquant/risk/` | 7 | 仓位 sizing、回撤分析、EVT 极值、历史风险、组合优化、结构风险 | → services (portfolio_service) |
| `services` | `src/uniquant/services/` | 32 | 服务 DAG 容器、分析编排、数据服务、缓存协调、投研流水线、扫描、健康检查、报告 | 编排所有下层 |
| `ui` | `src/uniquant/ui/` | 8 | Streamlit 仪表盘、健康检查、LPPL 可视化、组合分析 | → services (health/portfolio) |

**依赖方向 (DAG)**: `shared ← data ← brain ← services → signal → hands`
`shared` 被所有层依赖，不存在循环依赖。

**当前状态验证**: 八层全部存在，import 烟雾测试通过 ✅

---

## 3. 核心数据流

### 3.1 单标的投研流水线 (Main Path)

```
ServiceContainer.initialize()
    ↓
DataService.fetch_for_brain(symbol)
    → 返回 data_pack (Dict[str, Any]) 或 ResearchDataPack (typed, feature-gated)
    ↓
AnalysisService.run_ticker_analysis()
    → AnalysisEngineFactory.lazy_init() 加载各引擎
        → FsmAnalysisEngine.run()
        → CzscAnalysisEngine.run()
        → LpplAnalysisEngine.run()
        → RegimeAnalysisEngine.run()
        → NtfAnalysisEngine.run()
        → WyckoffAnalysisEngine.run()
        → macro + report + technical engines
        → DecisionBrain.make_decision()
    → 写入 data_pack
    ↓
TradingSignalCollector.collect()
    → adapters 将各引擎 Dict 输出转为 TradingSignal
    → signal/arbitrator.py 仲裁多信号冲突
    → 返回 List[TradingSignal]
    ↓
UnifiedBacktestEngine.run()
    → UnifiedMatchingEngine 向量化撮合
    → 返回 BacktestResult (含 metadata)
    ↓
PipelineResult (data_pack + decision + signals + BacktestResult)
```

### 3.2 批处理研究流水线

```
research_pipeline.run_batch(symbols)
    → ThreadPoolExecutor(max_workers) 并行执行单标的流水线
    → 原子检查点: 每个标的完成后写入 checkpoint
    → 返回 PipelineResult 列表
```

### 3.3 配置与特征标记

`config/config.yaml` → `RefactoringConfig` + `FeatureFlags` 控制:

| 标记 | 默认值 | 作用 |
|------|--------|------|
| `signal_arbitration` | true | 是否启用仲裁器 |
| `typed_contracts` | false | 是否启用类型化合约 |
| `factor_gate` | "block" | 因子准入: block/warn/off |
| `use_research_data_pack` | false | 是否使用 ResearchDataPack |
| `async_event_bus` | false | 是否使用异步事件总线 |
| `event_bus` | true | 事件总线开关 |

---

## 4. 关键入口文件清单

| 优先级 | 文件 | 角色 |
|--------|------|------|
| ⭐⭐⭐ | `services/service_container.py` | DAG 容器, 系统初始化入口 |
| ⭐⭐⭐ | `services/analysis_service_v2.py` | 单标分析编排, 引擎调用 |
| ⭐⭐⭐ | `services/research_pipeline.py` | 端到端研究流水线 |
| ⭐⭐ | `services/data_service.py` | 数据服务封装, fetch_for_brain |
| ⭐⭐ | `services/analysis/engine_factory.py` | 懒加载引擎工厂 |
| ⭐⭐ | `signal/adapters.py` | 引擎输出→TradingSignal 适配器 |
| ⭐⭐ | `signal/arbitrator.py` | 多信号仲裁 |
| ⭐⭐ | `hands/backtest/unified_engine.py` | 类型化回测引擎 |
| ⭐⭐ | `hands/backtest/unified_matching_engine.py` | 向量化 A 股撮合 |
| ⭐⭐ | `shared/interfaces.py` | 跨层类型契约 |
| ⭐⭐ | `shared/config_models.py` | 特征标记 + 重构配置 |
| ⭐ | `brain/wyckoff/engine.py` | Wyckoff 主引擎 |
| ⭐ | `brain/lppl/engine.py` | LPPL 泡沫检测 |
| ⭐ | `brain/factors/registry.py` | 因子注册器 (实际使用的) |
| ⭐ | `ui/dashboard.py` | Streamlit 入口 |

---

## 5. 高风险文件清单

| 文件 | 风险原因 | 验证状态 |
|------|---------|---------|
| `services/__init__.py` | 懒加载导入契约 | ✅ 存在 |
| `shared/interfaces.py` | 跨层类型契约, 修改影响所有层 | ✅ 存在 |
| `shared/constants/__init__.py` | 聚合常量, 广泛引用 | ✅ 存在 |
| `services/service_container.py` | DAG 容器, 依赖图正确性 | ✅ DAG 零循环 |
| `services/analysis_service_v2.py` | 核心编排逻辑, 1642→300 行重构 | ✅ 已重构 |
| `services/analysis/engine_factory.py` | 引擎注册 + 懒加载行为 | ✅ 存在 |
| `data/sources/tdx.py` | TDX 数据通路 | ✅ 存在 |
| `data/pipeline/data_validator.py` | OHLC 正确性看门狗 | ✅ 存在 |
| `signal/adapters.py` | 异构引擎→统一信号转换 | ✅ 存在 |
| `hands/backtest/unified_engine.py` | 回测行为准确性 | ✅ 存在 |
| `hands/backtest/unified_matching_engine.py` | A 股撮合约束 | ✅ 存在 |
| `config/config.yaml` | 全局运行时行为 | ✅ 存在 |

---

## 6. 当前架构优点

1. **DAG 依赖方向清晰** — shared ← data ← brain/services → signal → hands，无循环依赖
2. **服务容器隔离** — ServiceContainer 依赖注入解耦了层间直接 import
3. **类型化契约演进** — 6 个引擎输出已类型化 (LPPLOutput/CZSCOutput/NtfOutput/WyckoffOutput/RegimeOutput/AlphaOutput)，向后兼容
4. **特征标记系统** — FeatureFlags 控制新功能灰度发布
5. **懒加载引擎工厂** — AnalysisEngineFactory 延迟初始化降低启动开销
6. **A 股规则独立封装** — limit_checker/market_rules/cost_model/slippage_model/price_collar 各自独立
7. **测试覆盖增长** — 115 测试文件, 1354 测试函数, 1363 通过
8. **批处理并行** — ThreadPoolExecutor + 原子检查点

---

## 7. 当前架构风险

| ID | 风险 | 严重度 | 说明 |
|----|------|--------|------|
| R1 | **brain 层文件数骤减 (74→55)** | 高 | 删除了 19 个文件但无明确记录。可能是合法的重构删除，也可能丢失了功能 |
| R2 | **G-1 TimeProvider 未完全覆盖** | 中 | 仍含 1 个 `pd.Timestamp.now()` (注释中)、2 个 `datetime.now()`、~38 个 `time.time()` |
| R3 | **12 个 Wyckoff 测试预存失败** | 中 | `test_wyckoff_new_features.py` 中 VShape 和 AShareLimitPct 测试失败，存在功能偏差 |
| R4 | **文档大量过时** | 中 | 归档了 ~60+ 个历史分析文档，但 `docs/` 中仍混有大量过时分析报告 |
| R5 | **双 FactorRegistry** | 低 | `shared/factor_governance.py` 已废弃 (带 deprecation 警告)，`brain/factors/registry.py` 是实际在使用 |
| R6 | **ResearchDataPack 默认关闭** | 低 | `use_research_data_pack: false`，类型化 DataPack 尚未默认启用 |
| R7 | **ui 层薄** | 低 | 仅 8 文件 Streamlit 面板，大量分析能力未在前端暴露 |

---

## 8. 文档状态区分

| 类别 | 说明 | 推荐使用 |
|------|------|---------|
| ✅ 当前事实 | AGENTS.md (已更新), docs/index.md (已更新), pyproject.toml, config/config.yaml | **优先使用** |
| ✅ 产物文档 | `docs/analysis/00-07_*.md` (已有历史分析报告) | **交叉参考**, 但需用当前代码验证 |
| ⚠️ 最新分析 | `docs/analysis/comprehensive_architect_analysis.md`, `docs/analysis/comprehensive_docs_analysis_report.md` (2026-06-28) | **最新分析, 可参考** |
| ⚠️ 指南 | `docs/guides/*`, `docs/packages/*` (可能过时) | 用前确认 |
| 📦 归档 | `docs/archive/` (~80+ 文件) | 不直接信任, 仅当需要追溯历史时 |
| 🔄 重构日志 | `docs/reshaping_logs/` (16 个日志) | 变更历史参考 |
| 🧪 研究笔记 | `docs/analysis/wyckoff_*.md`, `docs/research/*` | Wyckoff 专项参考 |

---

## 9. Stage 1 输入清单

Stage 1 (Services Orchestration) 需要:

- [x] `AGENTS.md` — 项目控制上下文 (✓ 已读)
- [x] `docs/index.md` — 文档入口 (✓ 已读)
- [x] `config/config.yaml` — 运行时配置 (✓ 已读)
- [ ] `services/service_container.py` — 完整读取 initialize() 方法
- [ ] `services/analysis_service_v2.py` — 完整读取 run_ticker_analysis 流程
- [ ] `services/research_pipeline.py` — 完整读取 run() 和 run_batch()
- [ ] `services/analysis/engine_factory.py` — 完整读取懒加载注册
- [ ] `services/data_service.py` — fetch_for_brain 接口
- [ ] `services/__init__.py` — 懒加载导入
- [ ] `tests/test_engine_factory.py` — 引擎工厂测试

---

## 校验清单 (Stage 0)

- [x] 覆盖八层模块 (shared/data/brain/signal/hands/risk/services/ui)
- [x] 说明 DAG 依赖方向 (shared ← data ← brain ← services → signal → hands)
- [x] 列出至少 10 个关键文件 (实际列出 15 个)
- [x] 明确哪些旧文档不可直接信任 (archive/ 目录 + 部分 guides/packages)
- [x] 结论绑定到具体文件 (所有表格均使用实际文件路径)
- [x] 区分了当前事实、历史文档、待验证假设
