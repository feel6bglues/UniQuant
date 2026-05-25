# UniQuant -- 统一量化交易平台

> Unified Quantitative Trading Platform

UniQuant 是一套面向 A 股市场的量化交易系统，代码规模约 50K LOC，基于 Python 3.12+ 构建。
系统划分为 **8 大模块**，覆盖从数据接入、信号生成、因子分析、风险管理到回测撮合的完整量化工作流。

| 模块 | 职责 |
|------|------|
| **brain** | 信号生成引擎 -- CZSC、FSM、LPPL、Wyckoff、因子、指标等多引擎并行 |
| **data** | 数据层 -- 多源数据获取、存储、管道、缓存 |
| **hands** | 回测与策略 -- 向量化撮合回测引擎、策略框架、交易分析 |
| **services** | 服务层 -- DI 容器、分析引擎工厂、业务服务编排 |
| **shared** | 公共基础设施 -- 常量、异常、缓存、配置、成本/滑点模型、A 股约束 |
| **signal** | 信号系统 -- 信号模型、归一化、聚合、质量评估 |
| **risk** | 风险管理 -- 组合优化、仓位管理、回撤分析、EVT/CVaR |
| **ui** | 用户界面 -- Streamlit 仪表盘、Plotly 可视化 |

**核心能力**

- 多源数据接入 (AKShare、通达信、BaoStock 等)
- 多引擎信号生成 (CZSC 缠论、有限状态机、LPPL 泡沫检测、Wyckoff 量价分析)
- 向量化撮合回测，内置 A 股规则 (涨跌停、T+1、印花税等)
- 因子系统 -- 自定义因子注册、IC 分析、因子合成
- 风险管理 -- EVT 极值尾部、CVaR 优化、回撤控制
- Streamlit 仪表盘 -- 交互式策略分析与可视化

---

## 文档导航

### 架构

| 文档 | 说明 |
|------|------|
| [系统架构总览](architecture.md) | 整体架构设计、模块依赖关系、数据流 |

### 包文档

| 文档 | 说明 |
|------|------|
| [brain -- 信号生成引擎](packages/brain.md) | CZSC、FSM、LPPL、Wyckoff、因子引擎、指标计算 |
| [data -- 数据层](packages/data.md) | 数据获取器、存储引擎、数据管道、缓存策略 |
| [hands -- 回测与策略](packages/hands.md) | 回测引擎、策略基类、交易分析器、持仓管理 |
| [services -- 服务层](packages/services.md) | DI 容器、服务工厂、分析引擎编排、业务服务 |
| [shared -- 公共基础设施](packages/shared.md) | 常量、异常体系、成本模型、滑点模型、配置加载 |
| [signal -- 信号系统](packages/signal.md) | 信号模型定义、信号归一化、多信号聚合、质量评分 |
| [risk -- 风险管理](packages/risk.md) | 组合优化、仓位管理、回撤分析、EVT/CVaR |
| [ui -- 用户界面](packages/ui.md) | Streamlit 页面、Plotly 图表、仪表盘布局 |

### 使用指南

| 文档 | 说明 |
|------|------|
| [快速上手](guides/quickstart.md) | 安装、配置、运行第一个回测 |
| [回测指南](guides/backtest.md) | 回测引擎用法、参数配置、结果解读 |
| [因子系统指南](guides/factors.md) | 因子注册、自定义因子、IC 分析、因子合成 |
| [策略开发指南](guides/strategies.md) | 策略基类、信号订阅、仓位管理、策略组合 |
| [数据源接入指南](guides/data_sources.md) | AKShare、通达信、BaoStock 数据源配置 |
| [配置指南](guides/configuration.md) | YAML 配置文件结构、环境变量、运行时配置 |

### 参考手册

| 文档 | 说明 |
|------|------|
| [A 股约束详解](reference/a_share_constraints.md) | 涨跌停、T+1、印花税、最小交易单位等规则 |
| [信号类型参考](reference/signal_types.md) | 所有信号类型定义、字段说明、使用示例 |
| [异常体系参考](reference/exceptions.md) | 自定义异常层次、错误码、处理建议 |
| [常量参考](reference/constants.md) | 全局常量、交易参数默认值、枚举定义 |

### 开发

| 文档 | 说明 |
|------|------|
| [测试指南](development/testing.md) | 测试框架、fixture 说明、运行方式、覆盖率 |
| [项目结构](development/project_structure.md) | 目录布局、模块边界、命名约定 |

---

## 系统要求

- **Python** >= 3.12
- 操作系统：Linux / macOS / Windows (WSL)

### 核心依赖

以下为 `pyproject.toml` 中声明的主要依赖：

| 类别 | 包 | 版本要求 |
|------|-----|---------|
| 数值计算 | numpy | >= 2.0 |
| | pandas | >= 2.0, < 3.0 |
| | scipy | >= 1.10, < 2.0 |
| | numba | >= 0.58, < 1.0 |
| 数据格式 | pyarrow | >= 14.0, < 20.0 |
| | duckdb | >= 0.9 |
| 数据源 | akshare | >= 1.12, < 2.0 |
| | mootdx | >= 0.11.7, < 1.0 |
| Web/解析 | lxml | >= 4.9 |
| | beautifulsoup4 | >= 4.12 |
| | requests | >= 2.31 |
| 可视化 | streamlit | >= 1.20 |
| | plotly | >= 5.0 |
| | matplotlib | >= 3.8, < 4.0 |
| 基础设施 | loguru | >= 0.7 |
| | PyYAML | >= 6.0, < 7.0 |
| | sqlalchemy | >= 2.0 |
| | joblib | >= 1.3, < 2.0 |
| | filelock | >= 3.10 |
| | xxhash | >= 3.4 |

---

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd UniQuant

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 基础安装
pip install -e .

# 完整安装 (包含所有可选依赖)
pip install -e ".[all]"

# 开发安装 (包含测试工具)
pip install -e ".[dev]"
```

### 可选依赖组

| 依赖组 | 安装命令 | 说明 |
|--------|---------|------|
| tdx | `pip install -e ".[tdx]"` | 通达信数据源 (pytdx, tdxpy) |
| baostock | `pip install -e ".[baostock]"` | BaoStock 数据源 |
| curl | `pip install -e ".[curl]"` | curl-cffi HTTP 后端 |
| report | `pip install -e ".[report]"` | PDF 报告生成 (weasyprint) |
| js | `pip install -e ".[js]"` | JavaScript 执行器 (py-mini-racer) |
| all | `pip install -e ".[all]"` | 以上全部 |

---

## 目录结构总览

```
UniQuant/
├── src/uniquant/
│   ├── brain/      -- 信号生成 (CZSC, FSM, LPPL, Wyckoff, 因子, 指标...)
│   ├── data/       -- 数据获取、存储、管道、缓存
│   ├── hands/      -- 回测引擎、策略、交易分析
│   ├── services/   -- 服务容器、分析引擎工厂、业务服务
│   ├── shared/     -- 常量、异常、缓存、配置、成本模型
│   ├── signal/     -- 信号模型、归一化、聚合、质量
│   ├── risk/       -- 组合优化、仓位管理、回撤分析
│   └── ui/         -- Streamlit 仪表盘、可视化
├── tests/          -- 65+ 测试文件
├── config/         -- YAML 配置文件
├── scripts/        -- 数据工具脚本
└── pyproject.toml  -- 项目元数据
```

---

## 快速验证

安装完成后，可通过以下命令验证环境：

```bash
# 运行测试套件
pytest tests/ -v

# 启动 Streamlit 仪表盘
streamlit run src/uniquant/ui/app.py
```
