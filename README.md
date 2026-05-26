# UniQuant — 统一量化交易平台

> Unified Quantitative Trading Platform for A-Share Market

**状态:** 🚧 重构中 | **Python:** >= 3.12 | **规模:** ~50K LOC (目标)

---

## 项目概述

UniQuant 是一套面向 A 股市场的全栈量化交易系统，覆盖从数据接入、信号生成、因子分析、风险管理到回测撮合的完整量化工作流。

### 核心能力

| 能力 | 说明 |
|------|------|
| 多源数据接入 | TDX/BaoStock/Sina/Tencent/THS/Eastmoney + mootdx 集成 |
| 多引擎信号生成 | CZSC 缠论、FSM 状态机、LPPL 泡沫检测、Wyckoff 量价分析 |
| 向量化撮合回测 | 内置 A 股规则 (T+1、涨跌停、印花税) |
| 因子系统 | 自定义因子注册、IC/IR 分析、Walk-Forward 验证 |
| 风险管理 | EVT 极值尾部、CVaR 优化、回撤控制 |
| Streamlit 仪表盘 | 交互式策略分析与可视化 |

### 系统架构

```
shared/  →  data/  →  brain/ + risk/ + signal/  →  hands/  →  services/  →  ui/
(基础设施)   (数据层)    (分析层)                      (执行层)     (服务层)      (界面层)
```

---

## 项目状态

> ⚠️ **重要提示**: 当前代码库处于重构中期 (Phase 0 未开始)。文档描述的是 v2.0 目标架构 (~160 文件, 50K LOC)，当前为 v0.3 状态 (44 文件, ~12.6K LOC)。**完成度 ~28%，10/23 文档不可信。**
>
> 详细的文档 vs 代码差异分析请参阅 [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md)。

| 包 | 状态 | 文件数 | 完成度 | 说明 |
|----|------|--------|--------|------|
| `shared/` | ✅ 基本完整 | 23 | 79% | 常量、异常、缓存、配置、成本模型 |
| `services/` | ⚠️ 部分可用 | 11 | 46% | analysis_service + service_container + 6 引擎适配器 (幽灵导入阻塞) |
| `brain/` | ⚠️ 部分可用 | 5 | 17% | czsc、fsm、lppl (缺 7 子模块) |
| `ui/` | ⚠️ 部分可用 | 2 | 25% | dashboard、health_check |
| `risk/` | ⚠️ 部分可用 | 1 | 14% | drawdown_analyzer |
| `hands/` | 🔴 空壳 | 1 | 5% | 仅 __init__.py，回测/策略均不存在 |
| `data/` | 🔴 不存在 | 0 | 0% | 整个数据层 (含 mootdx) 待迁移 |
| `signal/` | 🔴 不存在 | 0 | 0% | 整个信号层待新建 |
| **测试** | 🔴 不可运行 | 10 | 10% | 仅 1/10 文件导入不崩溃 |

详细的项目状态仪表盘请查看 [docs/STATUS.md](docs/STATUS.md)。

---

## 快速开始

### 环境要求

- Python >= 3.12
- Linux / macOS / Windows (WSL)

### 安装

```bash
# 克隆仓库
git clone git@github.com:feel6bglues/UniQuant.git
cd UniQuant

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 安装
pip install -e .

# 完整安装 (含可选依赖)
pip install -e ".[all]"
```

### 验证安装

```bash
python -c "import uniquant; print('OK')"
```

> 注意: 当前 `import uniquant` 可能因 `services/__init__.py` 的幽灵导入而失败。需要先执行 Phase 0 修复。

### 运行测试

```bash
pytest tests/ -v
```

---

## 目录结构

```
UniQuant/
├── README.md                   — 本文件
├── RESTRUCTURE_PLAN.md         — 全系统重构计划
├── pyproject.toml              — 项目元数据
├── config/                     — YAML 配置文件
├── data/                       — 运行时数据 (数据湖、缓存)
├── scripts/                    — 数据工具脚本
├── src/uniquant/               — 核心源码
│   ├── brain/                  — 分析引擎 (czsc, fsm, lppl)
│   ├── hands/                  — 回测与策略 (待迁移)
│   ├── risk/                   — 风险管理 (drawdown_analyzer)
│   ├── services/               — 服务编排层
│   ├── shared/                 — 公共基础设施
│   ├── signal/                 — 信号系统 (待迁移)
│   └── ui/                     — Streamlit 仪表盘
├── tests/                      — 测试用例 (11 文件)
└── docs/                       — 项目文档
```

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [项目状态](docs/STATUS.md) | 实时进度仪表盘 |
| [系统架构](docs/architecture.md) | 整体架构设计 |
| [文档与代码差异评估](docs/EVALUATION_REPORT.md) | 全景差异分析报告 |
| [评估报告核实报告](docs/VERIFICATION_REPORT.md) | 4 Agent 独立核实报告 |
| [重构计划](docs/RESTRUCTURE_PLAN.md) | Phase 0-4 执行清单 |
| [快速上手](docs/guides/quickstart.md) | 安装与运行 |
| [包文档](docs/packages/) | 各模块 API 参考 |

---

## 重构计划

项目正在从 TDX 原始项目迁移，执行顺序：

```
Phase 0: 紧急修复 (导入链恢复)         ← 当前
Phase 1A: Shared 基础层迁移
Phase 1B: Data 全层迁移
Phase 1C: Services 层迁移
Phase 1D: Brain LPPL + Factor 迁移
Phase 1E: Hands + 回测迁移
Phase 1F: UI 层迁移
Phase 2: mootdx 数据层适配
Phase 3: 验证 + 修复
Phase 4: 清理
```

详细计划请查看 [docs/RESTRUCTURE_PLAN.md](docs/RESTRUCTURE_PLAN.md)。

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| 数据处理 | NumPy, Pandas, SciPy, Numba |
| 数据存储 | Parquet (PyArrow), DuckDB |
| 数据源 | AkShare, mootdx, BaoStock |
| 可视化 | Streamlit, Plotly, Matplotlib |
| 测试 | pytest |
| 配置 | YAML (PyYAML) |

---

## 许可证

私有项目 — 未经授权禁止使用或分发。
