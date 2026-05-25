# UniQuant 项目深度分析报告

## 一、项目概述

**UniQuant**（Unified Quantitative Trading Platform）是一个面向 **A 股市场**的统一量化交易平台，项目描述为 "TDX Alpha Tactician + LPPL"。它集成了多种分析引擎、回测框架、风险管理和 Streamlit 可视化界面。

| 项目属性 | 值 |
|---------|---|
| 版本 | 0.1.0 |
| Python | >= 3.12 |
| 布局 | `src` layout |
| 构建 | setuptools + pyproject.toml |
| 核心依赖 | numpy, pandas, scipy, akshare, mootdx, numba, streamlit, duckdb, sqlalchemy |
| 数据存储 | Parquet (snappy) + DuckDB + SQLite + JSON |

---

## 二、架构全景

项目采用 **分层架构**，从上到下分为 6 层：

```
┌─────────────────────────────────────────────────┐
│              UI 层 (Streamlit)                   │
│         dashboard / components / health          │
├─────────────────────────────────────────────────┤
│              服务层 (Services)                    │
│  AnalysisService / DataService / ScanService     │
│  ServiceContainer (DI) / EngineFactory           │
├─────────────────────────────────────────────────┤
│              大脑层 (Brain)                       │
│  LPPL / CZSC / Wyckoff / FSM / NTF / Regime     │
│  Factors / Screener / AlphaDecoupler             │
│  ─── DecisionBrain (Veto-Scoring 总控) ───       │
├─────────────────────────────────────────────────┤
│              双手层 (Hands)                       │
│  BacktestEngine / PortfolioEngine                │
│  UnifiedMatchingEngine / Strategies / MonteCarlo │
├─────────────────────────────────────────────────┤
│              风险+信号层 (Risk + Signal)         │
│  DrawdownAnalyzer / PortfolioOptimizer / Sizer   │
│  SignalAggregator / SignalDB / 36种信号类型      │
├─────────────────────────────────────────────────┤
│              数据层 (Data)                        │
│  DataFetcher / SourceRouter / StorageManager     │
│  TDX / BaoStock / Sina / Tencent / THS / EM    │
│  Pipeline (Clean/Adjust/Validate)                │
└─────────────────────────────────────────────────┘
```

---

## 三、核心模块详解

### 1. Brain 层 — 8 大分析引擎

| 引擎 | 路径 | 功能 |
|------|------|------|
| **LPPL** | `src/uniquant/brain/lppl/engine.py` | Log-Periodic Power Law 泡沫检测，使用差分进化全局优化，风险分级 danger/warning/watch |
| **CZSC** | `src/uniquant/brain/czsc/czsc_engine.py` | 缠中说禅技术分析（笔、线段、中枢、买卖点），依赖第三方 `czsc` 库 |
| **Wyckoff** | `src/uniquant/brain/wyckoff/engine.py` | v3.0 威科夫量价分析，识别吸筹/派发阶段，多周期（日/周/月），含融合引擎 |
| **FSM** | `src/uniquant/brain/fsm/fsm.py` | 有限状态机 + **DecisionBrain** 总控，Veto-Scoring 架构整合所有引擎信号 |
| **NTF** | `src/uniquant/brain/ntf/ntf_engine.py` | 国家队因子引擎，监控大盘 ETF 脉冲成交量异常，识别干预方向 |
| **Regime** | `src/uniquant/brain/regime/regime_detector.py` | 市场体制检测（NORMAL/STRESSED/FROZEN），基于熵值+换手率 Z-Score |
| **Factors** | `src/uniquant/brain/factors/` | 因子系统：Registry(注册) + Composer(合成/IC加权/正交化) + Analyzer(Rank IC/IR) + WalkForward |
| **Screener** | `src/uniquant/brain/screener/screener.py` | 全市场扫描器，Top/Bottom 榜单，技术信号验证 |

**DecisionBrain** 是核心决策枢纽，采用"否决-加权"架构：
1. 先检查否决条件（体制冻结、风险超标、泡沫预警）
2. 再对各引擎信号加权评分
3. 支持状态持久化（`fsm_state.json`），程序重启可恢复

### 2. Hands 层 — 回测与策略

| 组件 | 路径 | 功能 |
|------|------|------|
| **BacktestEngine** | `src/uniquant/hands/backtest/engine.py` | 单标的回测，支持 Rolling Window + Walk-Forward |
| **PortfolioEngine** | `src/uniquant/hands/backtest/portfolio_engine.py` | 多标的组合回测，最大持仓限制 |
| **UnifiedMatchingEngine** | `src/uniquant/hands/backtest/unified_matching_engine.py` | 统一撮合引擎，向量化实现，A 股约束（T+1/涨跌停/佣金/印花税/滑点） |
| **SignalIntegrator** | `src/uniquant/hands/backtest/signal_integrator.py` | 信号-回测集成器 |
| **MonteCarloSimulator** | `src/uniquant/hands/backtest/monte_carlo.py` | Monte Carlo 模拟 + Bootstrap |
| **OverfittingDetector** | `src/uniquant/hands/backtest/overfitting_detector.py` | 过拟合检测（Deflated Sharpe Ratio + Purged K-Fold） |

**策略库**（`src/uniquant/hands/strategies/`）：
- `wyckoff_strategy.py` — 威科夫策略
- `ma_cross.py` — 均线交叉策略
- `str_reversal.py` — 结构反转策略
- `fsm_strategy.py` — FSM 状态驱动策略
- `regime.py` — 体制策略

### 3. Data 层 — 多源数据架构

**数据源**（按优先级）：

| 数据源 | 状态 | 功能 |
|--------|------|------|
| StockDataSource (AKShare) | 启用 | 主力股票数据源 |
| IndexDataSource | 启用 | 指数数据 |
| EtfDataSource | 启用 | ETF 数据 |
| BaoStock | 禁用 | 备用 |
| Sina / Tencent / Eastmoney / THS | 禁用 | 备用 |

**数据存储格式**：

| 数据 | 格式 | 路径 |
|------|------|------|
| 日线行情 | Parquet (snappy) | `data/lake/quotes/daily/*.parquet` |
| 分钟线 | Parquet | `data/lake/quotes/1mins/` / `5mins/` |
| 因子 | Parquet | `data/factors/` |
| 信号 | SQLite | SQLAlchemy |
| FSM 状态 | JSON | `src/data/state/fsm_state.json` |
| 分析缓存 | joblib | `data/cache/analysis/` |

**数据管道**：`DataFetcher` → `SourceRouter`（故障转移）→ `StandardAdapter`（统一接口）→ `DataCleaner` → `DataAdjuster` → `DataValidator` → `StorageManager`（Parquet/DuckDB）

### 4. Risk 层 — 风险管理

| 组件 | 功能 |
|------|------|
| `DrawdownAnalyzer` | 向量化 MDD / Calmar / Ulcer Index / CVaR / 滚动回撤 |
| `PortfolioOptimizer` | Risk Parity + Mean-Variance 优化 |
| `PositionSizer` | 仓位管理（含精度安全函数） |
| `StructuralRiskManager` | 多指数风险矩阵评估 |

### 5. Signal 层 — 信号系统

- **36 种信号类型**（趋势/动量/波动率/成交量/形态/LPPL/威科夫/缠论/复合信号）
- **10 种信号来源**（LPPL/WYCKOFF/CZSC/NTF/FSM/REGIME/INDICATOR/SCREENER/FACTOR/ENSEMBLE）
- **4 种聚合方法**：加权平均 / 多数投票 / 最大置信度 / 共识阈值
- **SignalDatabase**：SQLAlchemy + SQLite 持久化

### 6. UI 层 — Streamlit 可视化

`dashboard.py` 是主入口，集成：
- LPPL 泡沫分析可视化
- CZSC 缠论图表
- FSM 状态面板
- 风险指标/压力测试
- 健康检查

---

## 四、配置体系

4 个 YAML 配置文件：

| 文件 | 内容 |
|------|------|
| `config/config.yaml` | 主配置：数据湖、缓存、网络、数据源、技术指标、缠论、LPPL、市场、风险、大脑 |
| `config/trading.yaml` | 交易配置：策略参数（Wyckoff/MA-ATR/Reversal/Regime）、风险限制、执行参数 |
| `config/factors.yaml` | 因子配置：动量/换手率动量/PE_TTM 等 |
| `config/optimal_params.yaml` | 最优参数 |

通过 `GlobalConfig` 单例访问，支持点号路径：`GlobalConfig.get("brain.ntf.volume_ratio_threshold")`

---

## 五、使用方法

### 1. 安装

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装核心依赖
pip install -e "."

# 安装全部可选依赖
pip install -e ".[all]"

# 仅安装开发工具
pip install -e ".[dev]"
```

**可选依赖组**：
- `[tdx]` — 通达信数据源（pytdx, tdxpy）
- `[baostock]` — BaoStock 数据源
- `[curl]` — curl-cffi 高性能 HTTP
- `[report]` — WeasyPrint PDF 报告
- `[js]` — py-mini-racer JS 执行器
- `[all]` — 全部

### 2. 运行全市场扫描

```bash
python scripts/run_market_scan.py
```

输出报告到 `data/test_scan/`：
- `top_stocks_*.md` — Top 榜单
- `bottom_stocks_*.md` — Bottom 榜单
- `factor_analysis_*.md` — 因子分析
- `market_risk_*.md` — 市场风险
- `tech_signals_top20_*.md` — 技术信号

### 3. 启动 Streamlit UI

```bash
streamlit run src/uniquant/ui/dashboard.py
```

### 4. 因子计算

```bash
# 单股票因子计算
python scripts/calculate_factors_single.py

# 批量因子计算
python scripts/calculate_factors_v15.py
```

### 5. 数据管理

```bash
# 下载 ETF 数据
python scripts/download_etf_data.py

# 重建财务数据湖
python scripts/rebuild_financial_lake.py

# 增量更新验证
python scripts/test_incremental_update.py
```

### 6. 编程接口示例

```python
from uniquant.services.service_container import ServiceContainer
from uniquant.shared.config_loader import GlobalConfig

# 获取配置
threshold = GlobalConfig.get("brain.ntf.volume_ratio_threshold")

# 使用服务容器
container = ServiceContainer()
analysis_service = container.analysis_service
data_service = container.data_service

# 分析单只股票
result = analysis_service.analyze_ticker("600519.SH")

# 全市场扫描
from uniquant.services.scan_service import ScanPipeline
pipeline = ScanPipeline()
report = pipeline.run()
```

### 7. 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 带覆盖率
python -m pytest tests/ --cov=uniquant

# 特定模块
python -m pytest tests/test_lppl_engine_scan_windows.py -v
```

---

## 六、已知问题与重构计划

项目当前有 **53 项已知问题**（12 P0 / 21 P1 / 20 P2），已制定 9 阶段重构计划（详见 `REFACTORING_PLAN_COMPLETE.md`）：

| 阶段 | 名称 | 核心目标 |
|------|------|---------|
| Phase-S | 安全 & 崩溃修复 | 4 个安全漏洞 + 3 个运行时 Bug |
| Phase-0 | 基础设施修复 | 可构建/可测试/可复现 |
| Phase-1a | 回测执行统一 | 统一撮合引擎，消除同 Bar 成交 |
| Phase-1b | 核心路径向量化 | 消除 20 处 iterrows，50-100x 性能提升 |
| Phase-2a | 信号与决策链 | 统一生产/回测决策路径 |
| Phase-2b | 因子系统修复 | 消除因子数据泄露和过拟合 |
| Phase-3 | 回撤归因与风险引擎 | MDD/Calmar/CVaR + 压力测试 |
| Phase-4 | 工程债务清理 | 命名纠正、架构解耦、代码质量 |
| Phase-5~6 | 死代码清理 + A 股微观结构 | DI 容器移除、复权/停牌/板块/新股 |

**关键 P0 问题**：SSL 验证禁用、JS 代码注入、硬编码路径、回测同 Bar 成交、因子权重全样本泄露、策略函数未来数据等。

---

## 七、设计模式总结

| 模式 | 应用 |
|------|------|
| 门面模式 | `DataService` 协调 CacheCoordinator / DataQualityService / StockQueryService |
| 工厂模式 | `AnalysisEngineFactory` 延迟初始化 7 个引擎 |
| 单例模式 | `GlobalConfig` / `FactorRegistry` / `ServiceContainer` |
| 适配器模式 | `StandardAdapter` 统一多数据源接口 |
| 路由模式 | `SourceRouter` 故障转移 + 健康检查 |
| 协议模式 | `protocols.py` 定义数据源能力接口 |
| Veto-Scoring | `DecisionBrain` 先否决再加权 |
| 依赖注入 | `ServiceContainer` 管理服务拓扑 |
| 向量化撮合 | `UnifiedMatchingEngine` 全 NumPy 实现 |
| Walk-Forward | 严格训练/测试分离，防未来数据泄漏 |
