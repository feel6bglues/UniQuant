# AGENTS.md — UniQuant AI 项目上下文

> UniQuant: A 股量化交易平台 | Python 3.12+ | 当前 v0.6.x (263 .py 文件, 58,231 LOC)
>
> **生成时间**: 2026-06-07 | 基于实测代码,无幻觉

---

## 项目概述

UniQuant 是面向 A 股市场的全栈量化交易系统,覆盖数据接入、信号生成、因子分析、风险度量、回测撮合、UI 仪表盘。已度过 Phase 0 导入期,**所有 8 个声明层均已就位**(`data/` 与 `signal/` 长期存在,与早期文档相反)。当前主线问题是 **12 个测试用例失败 + 2 个收集错误**,集中在 portfolio e2e、FSM 涨跌停决策、数据校验混沌测试。

**技术栈**: Python 3.12+, NumPy, Pandas, SciPy, Numba, PyArrow, mootdx, AkShare, Streamlit, Plotly, pytest

---

## 必须先读的文件

| 文件 | 用途 |
|------|------|
| `AGENTS.md` (本文件) | 项目第一上下文 |
| `pyproject.toml` (根目录,不是 docs/) | 包元数据、依赖、pytest 配置 |
| `src/uniquant/shared/interfaces.py` (365 行) | 5 个 Protocol 接口定义 |
| `src/uniquant/shared/constants/__init__.py` | 7 个常量子模块的统一出口(原 `constants.py` 已拆分) |
| `src/uniquant/services/analysis/engine_factory.py` | 13 个分析引擎的工厂(13 个,不是 9 个) |
| `config/config.yaml` | 主配置文件 |
| `docs/RESTRUCTURE_PLAN.md` | 历史迁移计划(已大半完成,主要参考其目录划分逻辑) |

---

## 关键目录与模块职责

| 包 | 路径 | 文件数 | LOC | 状态 | 职责 |
|---|------|--------|-----|------|------|
| shared | `src/uniquant/shared/` | 37 | 5,716 | ✅ 完整 | Protocol、常量子包、异常、缓存、配置、成本/滑点、涨跌停、限价笼 |
| brain | `src/uniquant/brain/` | 73 | 15,743 | ✅ 完整 | 11 个子包:CZSC 缠论、FSM 状态机、LPPL 泡沫、NTF、Regime、Wyckoff、Factors(含 27 个 auto_mined 因子)、Indicators、Screener、Alpha Decoupler |
| data | `src/uniquant/data/` | 65 | 15,426 | ✅ 完整 | data_fetcher、tdx_loader、11 个数据源(baostock/eastmoney/mootdx_local/online/sina/tdx/tencent/ths)、湖(pipeline/lake/managers/parsers/utils) |
| signal | `src/uniquant/signal/` | 7 | 2,075 | ✅ 完整 | aggregator/normalizer/quality/adapters/models + db 子包 + quality 子包 |
| services | `src/uniquant/services/` | 31 | 8,485 | ✅ 完整 | DAG 容器、13 个分析引擎(平铺)、14 个服务(懒加载)、health/data_access/data_quality/market_regime/report/signal_generation 等 |
| risk | `src/uniquant/risk/` | 7 | 1,450 | ✅ 完整 | drawdown/evt/historical/portfolio_optimizer/sizer/structural(全在) |
| hands | `src/uniquant/hands/` | 34 | 6,087 | ✅ 完整 | backtest/(unified_engine/unified_matching_engine/portfolio_engine/benchmark/monte_carlo/overfitting_detector/param_validator/robustness_checker/sensitivity_analyzer/signal_integrator/trade_analysis) + strategies/ + tuning/ |
| ui | `src/uniquant/ui/` | 8 | 3,248 | ✅ 完整 | dashboard(1518 行)+ health_check + 4 个 manager_* + components + lppl_visualizer |

**配置**: `config/` 含 4 个 YAML (config.yaml, trading.yaml, factors.yaml, optimal_params.yaml)

**测试**: `tests/` 含 76 个 .py 文件,共 966 个用例,**951 通过, 7 跳过, 12 失败, 2 收集错误**

**文档**: `docs/` 含 106 个 .md 文件 (另有 19 个历史文档已归档至 `docs/archive/`), 17 个子目录

---

## 阻塞问题清单(2026-06-07 实测)

| # | 问题 | 影响 | 优先级 | 修复方向 |
|---|------|------|--------|----------|
| 1 | `tests/test_drawdown_analyzer.py:13` 用 `from src.uniquant.risk.drawdown_analyzer import ...` | pytest 收集错误,阻塞整个文件 | P0 | 改为 `from uniquant.risk.drawdown_analyzer import ...` |
| 2 | `tests/test_portfolio_engine_v2.py` 同样 `from src.uniquant...` 风格 | pytest 收集错误,阻塞整个文件 | P0 | 同上,检查全文 `from src.` 前缀 |
| 3 | `tests/test_fsm.py::TestDecisionBrain::test_make_decision_limit_down_sell_blocked` 失败 | FSM 在跌停时未拒绝卖出,违反 A 股规则 | P0 | `brain/fsm/fsm.py` DecisionBrain.make_decision 需结合 `LimitStatus` 检查 |
| 4 | `tests/test_e2e_integration_qa.py::TestImportChain::test_import[uniquant.hands.backtest.portfolio_engine]` 失败 | `uniquant.hands.backtest.portfolio_engine` 导入失败 | P0 | 核查 `hands/backtest/portfolio_engine.py` 模块完整性 |
| 5 | `tests/test_e2e_integration_qa.py::TestPortfolioEngine` 5 个用例失败 | portfolio_run / metrics / reset / 参数对齐全部失败 | P0 | 依赖 #4 修复后重测 |
| 6 | `tests/test_data_chaos_qa.py::TestDataValidatorChaos::test_high_lt_open_close_auto_fix` 失败 | 行情数据 high<open/close 时未自动修复 | P1 | `data/pipeline/data_aligner.py` 校验逻辑 |
| 7 | `tests/` 中存在 `__pycache__` 残留 | 不影响功能,但可能掩盖真实 import 错误 | P3 | `find tests -name __pycache__ -exec rm -rf {} +` |

**已不存在的历史阻塞**(AGENTS.md 旧版列出,全部已修复):
- ✅ `services/__init__.py` 幽灵导入 — 改为 `__getattr__` 懒加载
- ✅ `brain/lppl/__init__.py` 幽灵导入 — 改为 `try/except` 守卫
- ✅ `brain/fsm/fsm.py` `from ..indicators import Indicators` — `brain/indicators/indicators.py` 存在,导入正常
- ✅ `data/` 整层缺失 — 从未缺失(65 文件,15K LOC)
- ✅ `signal/` 整层缺失 — 从未缺失(7 文件,2K LOC)
- ✅ `engine_factory` 参数错配 — `__init__(self, orchestrator)` 签名正确,6 个测试全过

---

## 常用命令(已实测可运行)

```bash
# 安装 (根目录 pyproject.toml 是真实的,可直接用)
pip install -e ".[all]"

# 全量测试(会暴露 12 失败 + 2 收集错误)
pytest tests/ -q

# 排除已知阻塞文件后跑剩余 74 个测试
pytest tests/ -q --ignore=tests/test_drawdown_analyzer.py --ignore=tests/test_portfolio_engine_v2.py

# 单引擎工厂冒烟
pytest tests/test_engine_factory.py -xvs

# 验证全 8 层导入
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('ALL OK')"

# Lint
ruff check src/uniquant/

# 仪表盘
streamlit run src/uniquant/ui/dashboard.py
```

---

## 架构约定

- **5 层 DAG**: `shared` → `data` → `brain/risk/signal` → `hands` → `services` → `ui`
- **单向依赖**: 上层依赖下层,禁止反向,禁止循环
- **Protocol 接口**: 5 个 `@runtime_checkable` Protocol 在 `shared/interfaces.py`,鸭子类型解耦
- **DAG 容器**: `ServiceContainer` 在 `services/service_container.py` 按拓扑顺序初始化 14 个服务
- **懒加载工厂**: `AnalysisEngineFactory` 在 `services/analysis/engine_factory.py` 通过 `importlib.import_module` 延迟加载 13 个分析引擎
- **服务包懒加载**: `services/__init__.py` 用 `__getattr__` 延迟导入子模块,避免深层依赖链
- **常量拆分**: 原 `shared/constants.py` 已拆为 `shared/constants/` 子包(market/technical/risk/data/path/misc),统一由 `__init__.py` 再导出

---

## 代码风格

| 规范 | 示例 | 来源 |
|------|------|------|
| 类名 | `GlobalConfig`, `LimitStatus`, `AlphaTacticianError` | PascalCase |
| 函数/方法 | `get_board_type()`, `check_limit_status()` | snake_case |
| 常量 | `COMMISSION_PCT`, `STAMP_TAX_PCT` | UPPER_SNAKE_CASE |
| 私有方法 | `_load_config()`, `_evict_oldest()` | 单下划线前缀 |
| Docstring | 中文注释, Google 风格 Args/Returns | 混合中英文 |
| 导入顺序 | 标准库 → 第三方 → 本地 (相对导入) | PEP 8 |
| 错误处理 | `@handle_errors()` 装饰器, 自定义异常继承 `AlphaTacticianError` | 37+ 个异常子类 |
| 数据载体 | `@dataclass` + `@classmethod from_dict()` | `MarketSignalContext`, `CostConfig` |
| 配置访问 | `config.get("brain.fsm.ma_short", 20)` | dot-notation |

---

## 高风险区域(禁止随意修改)

| 文件 | 原因 |
|------|------|
| `src/uniquant/services/__init__.py` | 懒加载契约,修改影响所有 `from uniquant.services import X` |
| `src/uniquant/shared/constants/__init__.py` | 7 个常量子模块的聚合出口,常被 import 链广泛依赖 |
| `src/uniquant/shared/interfaces.py` | 5 个 Protocol,修改影响全局类型契约 |
| `config/config.yaml` | 430 行, 全局配置, 影响所有服务 |
| `src/uniquant/services/analysis/engine_factory.py` | 13 个引擎注册, 错误修改导致全部引擎失效 |
| `src/uniquant/data/sources/tdx.py` | 通达信数据源, 在线/本地双路径, 多个 import 链依赖 |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | A 股撮合核心, T+1/涨跌停/印花税三道防线集中处 |

---

## A 股约束速查

| 约束 | 值 | 来源 |
|------|-----|------|
| 主板涨跌停 | ±10% | `shared/limit_checker.py` |
| 科创板/创业板 | ±20% | `shared/limit_checker.py` |
| 北交所 | ±30% | `shared/limit_checker.py` |
| ST 股 | ±5% | `shared/limit_checker.py` |
| 佣金 | 0.03% (万3) | `shared/cost_model.py` |
| 印花税 | 0.05% (万5, 卖方) | `shared/cost_model.py` |
| 最低佣金 | 5 元/笔 | `shared/cost_model.py` |
| 滑点 | 0.05% (万5) | `shared/slippage_model.py` |
| 限价笼 | ±2% 偏离现价 | `shared/price_collar.py` |
| 交易时段 | 9:30-11:30, 13:00-15:00 | `shared/constants/market.py:MarketHours` |
| T+1 | 当日买入次日可卖 | `hands/backtest/unified_matching_engine.py` |

---

## 13 个分析引擎速查

引擎全部平铺在 `src/uniquant/services/analysis/`,**无子目录**。由 `engine_factory` 统一注册:

| 引擎 | 文件 | 职责 |
|------|------|------|
| CZSC | `czsc_analysis_engine.py` | 缠论分型/笔/线段 |
| FSM | `fsm_analysis_engine.py` | 状态机决策(MA 交叉 + 涨跌停) |
| LPPL | `lppl_analysis_engine.py` | 对数周期幂律泡沫检测 |
| NTF | `ntf_analysis_engine.py` | 内日趋势跟随(待 FSM 修复后回归) |
| Regime | `regime_analysis_engine.py` | 市场状态分类 |
| Wyckoff | `wyckoff_analysis_engine.py` | 威科夫量价 |
| Macro | `macro_analysis_engine.py` | 宏观因子 |
| Technical | `technical_service.py` | 技术指标聚合 |
| Signal | `signal_service.py` | 信号归一化 |
| Macro Service | `macro_service.py` | 宏观服务层 |
| Report Generator | `report_generator_engine.py` | 报告生成 |

---

## 修改后验证清单

```bash
# 1. 全 8 层导入
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# 2. 核心测试
pytest tests/test_engine_factory.py -xvs

# 3. 全量测试(预期 12 失败 + 2 收集错误,其他应绿)
pytest tests/ -q --ignore=tests/test_drawdown_analyzer.py --ignore=tests/test_portfolio_engine_v2.py

# 4. Lint
ruff check src/uniquant/

# 5. 配置加载
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# 6. 服务容器初始化(会触发 14 个服务按拓扑序装配)
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); print('container ready')"
```

---

*生成时间: 2026-06-07 | 基于实测, AGENTS.md 旧版 12 天前已不反映现状*
