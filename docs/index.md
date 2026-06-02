# UniQuant — 统一量化交易平台

> Unified Quantitative Trading Platform

UniQuant 是一套面向 A 股市场的量化交易系统，基于 Python 3.12+ 构建。系统划分为 **8 大模块**，覆盖从数据接入、信号生成、因子分析、风险管理到回测撮合的完整量化工作流。

> ⚠️ **状态提示**: 项目正在重构中。标记为 🎯 的文档描述目标状态（重构完成后），标记为 ✅ 的文档描述当前可用功能。详见 [STATUS.md](STATUS.md)。

| 模块 | 职责 | 状态 |
|------|------|------|
| **brain** | 信号生成引擎 -- CZSC、FSM、LPPL 等多引擎并行 | ⚠️ 部分可用 |
| **data** | 数据层 -- 多源数据获取、存储、管道、缓存 | 🔴 待迁移 |
| **hands** | 回测与策略 -- 向量化撮合回测引擎、策略框架 | 🔴 待迁移 |
| **services** | 服务层 -- DI 容器、分析引擎工厂、业务服务编排 | ⚠️ 部分可用 |
| **shared** | 公共基础设施 -- 常量、异常、缓存、配置、成本/滑点模型 | ✅ 基本完整 |
| **signal** | 信号系统 -- 信号模型、归一化、聚合、质量评估 | 🔴 待迁移 |
| **risk** | 风险管理 -- 组合优化、仓位管理、回撤分析 | ⚠️ 部分可用 |
| **ui** | 用户界面 -- Streamlit 仪表盘、Plotly 可视化 | ⚠️ 部分可用 |

---

## 文档导航

### 架构

| 文档 | 状态 | 说明 |
|------|------|------|
| [系统架构总览](architecture.md) | ⚠️ | 整体架构设计（描述目标架构） |
| [项目状态仪表盘](STATUS.md) | ✅ | 实时进度与模块可用性 |
| [文档与代码差异评估](EVALUATION_REPORT.md) | ✅ | 全景差异分析：docs 承诺 vs 代码现实 |
| [评估报告核实报告](VERIFICATION_REPORT.md) | ✅ | 4 Agent 独立核实，修正 7 项数据差异 |

### 包文档

| 文档 | 状态 | 说明 |
|------|------|------|
| [brain -- 信号生成引擎](packages/brain.md) | ⚠️ | 仅 czsc/fsm/lppl 可用，其余待迁移 |
| [data -- 数据层](packages/data.md) | 🎯 | 目标状态，当前不存在 |
| [hands -- 回测与策略](packages/hands.md) | 🎯 | 目标状态，当前仅空壳 |
| [services -- 服务层](packages/services.md) | ⚠️ | 部分可用 (11/24 文件) |
| [shared -- 公共基础设施](packages/shared.md) | ✅ | 基本完整 (23/29 文件) |
| [signal -- 信号系统](packages/signal.md) | 🎯 | 目标状态，当前不存在 |
| [risk -- 风险管理](packages/risk.md) | ⚠️ | 仅 drawdown_analyzer 可用 |
| [ui -- 用户界面](packages/ui.md) | ⚠️ | 仅 dashboard/health_check 可用 |

### 使用指南

| 文档 | 状态 | 前置条件 |
|------|------|---------|
| [快速上手](guides/quickstart.md) | 🎯 | 需要 data 层迁移完成 |
| [回测指南](guides/backtest.md) | 🎯 | 需要 hands 层迁移完成 |
| [因子系统指南](guides/factors.md) | 🎯 | 需要 brain/factors 迁移完成 |
| [策略开发指南](guides/strategies.md) | 🎯 | 需要 hands/strategies 迁移完成 |
| [数据源接入指南](guides/data_sources.md) | 🎯 | 需要 data 层迁移完成 |
| [配置指南](guides/configuration.md) | ✅ | shared/config_loader 已就绪 |

### 参考手册

| 文档 | 状态 | 说明 |
|------|------|------|
| [A 股约束详解](reference/a_share_constraints.md) | ✅ | 涨跌停、T+1、印花税等规则 |
| [信号类型参考](reference/signal_types.md) | 🎯 | 目标状态 (signal 层待迁移) |
| [异常体系参考](reference/exceptions.md) | ✅ | 完整异常层次 |
| [常量参考](reference/constants.md) | ✅ | 所有常量类完整参考 |

### 研究报告

| 文档 | 状态 | 说明 |
|------|------|------|
| [Alpha 挖掘综合报告 2026-06-02](research/ALPHA_MINING_REPORT_20260602.md) | ✅ | 5 个 Session、36 轮因子挖掘全记录，9 因子通过 ICIR≥0.4 |
| [Auto-Mined 因子技术手册 2026-06-02](research/FACTOR_CATALOG_20260602.md) | ✅ | 9 个已注册 am_* 因子的接口、参数、使用指南 |

### 开发

| 文档 | 状态 | 说明 |
|------|------|------|
| [测试指南](development/testing.md) | ⚠️ | 需更新为实际测试数 (11 文件) |
| [项目结构](development/project_structure.md) | ⚠️ | 需更新为实际文件清单 |
| [文档管理计划](DOC_MANAGEMENT_PLAN.md) | ✅ | 文档规范与维护流程 |

---

## 系统要求

- **Python** >= 3.12
- 操作系统：Linux / macOS / Windows (WSL)

### 核心依赖

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
| 可视化 | streamlit | >= 1.20 |
| | plotly | >= 5.0 |
| 基础设施 | loguru | >= 0.7 |
| | PyYAML | >= 6.0, < 7.0 |

---

## 安装

```bash
git clone git@github.com:feel6bglues/UniQuant.git
cd UniQuant
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

---

## 快速验证

```bash
# 运行测试
pytest tests/ -v

# 启动仪表盘
streamlit run src/uniquant/ui/dashboard.py
```
