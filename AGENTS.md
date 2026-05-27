# AGENTS.md — AI 项目上下文

> UniQuant: A 股量化交易平台 | Python 3.12+ | 当前 v0.3 (44/160 文件, ~12.6K LOC)

---

## 项目概述

UniQuant 是面向 A 股市场的全栈量化交易系统，覆盖数据接入、信号生成、因子分析、风险管理、回测撮合。当前处于重构中期（Phase 0 未开始），**28% 源码就绪**，`data/` 和 `signal/` 包完全不存在。

**技术栈**: Python 3.12+, NumPy, Pandas, SciPy, Numba, PyArrow/DuckDB, mootdx, AkShare, Streamlit, Plotly, pytest

---

## 必须先读的文件

| 文件 | 用途 |
|------|------|
| `AGENTS.md` (本文件) | 项目第一上下文 |
| `.agents/skills/architecture-navigation/SKILL.md` | 5 层 DAG 架构、Protocol、DI 容器 |
| `.agents/skills/import-chain-repair/SKILL.md` | 幽灵导入清单、Phase 0 修复方案 |
| `docs/RESTRUCTURE_PLAN.md` | 迁移执行计划 (Phase 0-4) |
| `docs/EVALUATION_REPORT.md` | 文档 vs 代码差异分析 |
| `src/uniquant/shared/interfaces.py` | 5 个 Protocol 接口定义 |
| `src/uniquant/shared/constants.py` | 全局常量 (1139 行, 30 个类) |
| `config/config.yaml` | 主配置文件 (430 行) |

---

## 关键目录与模块职责

| 包 | 路径 | 文件数 | 状态 | 职责 |
|---|------|--------|------|------|
| shared | `src/uniquant/shared/` | 23 | ✅ 完整 | Protocol 接口、常量、异常、日志、缓存、配置、成本/滑点模型、涨跌停检查 |
| brain | `src/uniquant/brain/` | 5 | ⚠️ 部分 | CZSC 缠论、FSM 状态机、LPPL 泡沫检测 (缺 NTF/Regime/Wyckoff/Factors) |
| services | `src/uniquant/services/` | 11 | ⚠️ 幽灵导入阻塞 | DAG 容器、分析引擎工厂、分析服务编排 |
| risk | `src/uniquant/risk/` | 1 | ⚠️ 最小 | 仅 drawdown_analyzer (缺 sizer/evt_risk/portfolio_optimizer) |
| hands | `src/uniquant/hands/` | 1 | 🔲 空壳 | 仅 __init__.py, 回测/策略均不存在 |
| ui | `src/uniquant/ui/` | 2 | ⚠️ 部分 | Streamlit 仪表盘 (1518 行) + 健康检查 |
| data | `src/uniquant/data/` | 0 | 🔲 不存在 | 整个数据层待迁移 |
| signal | `src/uniquant/signal/` | 0 | 🔲 不存在 | 信号归一化/聚合/持久化待新建 |

**配置**: `config/` 含 4 个 YAML (config.yaml, trading.yaml, factors.yaml, optimal_params.yaml)

**测试**: `tests/` 含 10 个测试文件, 仅 `test_engine_factory.py` 可独立运行

**文档**: `docs/` 含 34 个文件, 4 个完全可信, 10 个描述目标状态不可信

---

## 阻塞问题清单

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| 1 | `services/__init__.py` 8 个幽灵导入 | `import uniquant.services` 崩溃 | Phase 0.1: 删除不存在的导入 |
| 2 | `brain/lppl/__init__.py` 7 个幽灵导入 | LPPL 引擎无法使用 | Phase 0.2: 精简导入 |
| 3 | `brain/fsm/fsm.py` 的 `from ..indicators import Indicators` | FSM/DecisionBrain 崩溃 | Phase 0.6: try/except fallback |
| 4 | `data/` 整层不存在 | 无数据服务, 无回测 | Phase 1B: 从 TDX 迁移 40+ 文件 |
| 5 | `engine_factory` 参数错配 | 所有引擎无法初始化 | Phase 1A.9: 修复构造函数 |

详见 `.agents/skills/import-chain-repair/SKILL.md`

---

## 常用命令

```bash
# 安装 (需要先恢复根目录 pyproject.toml，当前仅在 docs/pyproject.toml)
cp docs/pyproject.toml pyproject.toml
pip install -e ".[all]"

# 测试 (仅 test_engine_factory 确定可运行)
pytest tests/test_engine_factory.py -xvs

# Lint
ruff check src/uniquant/

# 仪表盘
streamlit run src/uniquant/ui/dashboard.py

# 验证导入链
python -c "import uniquant; import uniquant.shared; print('OK')"

# 类型检查 (如果配置了)
mypy src/uniquant/
```

> **注意**: 当前根目录无 `pyproject.toml`（已移至 `docs/pyproject.toml`）。执行 `pip install -e .` 前需先将其复制回根目录。

---

## 架构约定

- **5 层 DAG**: `shared` → `data` → `brain/risk/signal` → `hands` → `services` → `ui`
- **单向依赖**: 上层依赖下层, 禁止反向, 禁止循环
- **Protocol 接口**: 5 个 `@runtime_checkable` Protocol 在 `shared/interfaces.py`, 鸭子类型解耦
- **DAG 容器**: `ServiceContainer` 按拓扑顺序初始化所有服务, 延迟导入避免循环
- **延迟工厂**: `AnalysisEngineFactory` 通过 `@property` + `importlib.import_module` 延迟加载引擎
- **单例模式**: `GlobalConfig` 和 `ServiceContainer` 均为双重检查锁单例

详见 `.agents/skills/architecture-navigation/SKILL.md`

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
| 错误处理 | `@handle_errors()` 装饰器, 自定义异常继承 `AlphaTacticianError` | 37 个异常子类 |
| 数据载体 | `@dataclass` + `@classmethod from_dict()` | `MarketSignalContext`, `CostConfig` |
| 配置访问 | `config.get("brain.fsm.ma_short", 20)` | dot-notation |

---

## 高风险区域 (禁止随意修改)

| 文件 | 原因 |
|------|------|
| `src/uniquant/services/__init__.py` | 8 个幽灵导入, Phase 0 修复目标 |
| `src/uniquant/shared/constants.py` | 1139 行, 30 个常量类, 所有模块依赖 |
| `src/uniquant/shared/interfaces.py` | 5 个 Protocol, 修改影响全局 |
| `config/config.yaml` | 430 行, 全局配置, 影响所有服务 |
| `src/uniquant/services/analysis/engine_factory.py` | 9 个引擎注册, 错误修改导致全部引擎失效 |

---

## Skills 索引

| Skill | 触发场景 |
|-------|---------|
| `architecture-navigation` | 首次进入项目、定位模块、理解依赖关系 |
| `import-chain-repair` | ImportError、Phase 0 修复、新增模块导出 |
| `testing-strategy` | 写测试、修测试、验证改动 |
| `restructure-workflow` | 执行迁移、规划重构步骤 |
| `tdx-migration` | 从 TDX 项目迁移具体模块 |
| `config-and-constants` | 修改配置、添加常量、理解 A 股约束 |
| `analysis-engine-development` | 开发/修改 brain 层引擎 |

---

## 修改后验证清单

```bash
# 1. 导入链验证
python -c "import uniquant; import uniquant.shared; print('import OK')"

# 2. 核心测试
pytest tests/test_engine_factory.py -xvs

# 3. Lint
ruff check src/uniquant/

# 4. 检查新增文件的 __init__.py 导出是否正确
python -c "from uniquant.shared import get_logger, retry; print('shared OK')"

# 5. 检查配置加载
python -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"
```

---

## A 股约束速查

| 约束 | 值 | 来源 |
|------|-----|------|
| 主板涨跌停 | ±10% | `limit_checker.py` |
| 科创板/创业板 | ±20% | `limit_checker.py` |
| 北交所 | ±30% | `limit_checker.py` |
| ST 股 | ±5% | `limit_checker.py` |
| 佣金 | 0.03% (万3) | `cost_model.py` |
| 印花税 | 0.05% (万5, 卖方) | `cost_model.py` |
| 最低佣金 | 5 元/笔 | `cost_model.py` |
| 滑点 | 0.05% (万5) | `cost_model.py` |
| 交易时段 | 9:30-11:30, 13:00-15:00 | `constants.py:MarketHours` |

详见 `.agents/skills/config-and-constants/SKILL.md`

---

*生成时间: 2026-05-26 | 基于代码事实, 禁止幻觉*
