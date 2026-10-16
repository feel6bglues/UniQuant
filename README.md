# UniQuant — 统一量化交易平台

> Unified Quantitative Trading Platform for A-Share Market

**状态:** 生产加固 / 研究收敛 | **Python:** >= 3.12 | **规模:** 236 文件 · 59,594 LOC (`src/uniquant/`)

---

## 项目概述

UniQuant 是一套面向 A 股市场的全栈量化交易系统，覆盖从数据接入、信号生成、因子分析、风险管理到回测撮合的完整量化工作流。

### 核心能力

| 能力 | 说明 |
|------|------|
| 数据接入 | **单源数据湖**：通达信本地 `.day` 解包（`data/lake/quotes/daily`）+ mootdx（local / online）；已收敛为湖优先只读 |
| 多引擎信号生成 | CZSC 缠论、FSM 状态机、LPPL 泡沫检测（遥测）、Wyckoff 量价分析（叙事/风控层） |
| 向量化撮合回测 | 内置 A 股规则 (T+1、分板块涨跌停、印花税、过户费、滑点、lot 取整) |
| 因子系统 | 因子注册中心、IC/IR 分析、Walk-Forward 验证、**科研控制平面（自由度账本 / 多重检验校正）** |
| 风险管理 | EVT 极值尾部、CVaR 优化、回撤控制 |
| Streamlit 仪表盘 | 交互式策略分析与可视化 |

### 系统架构

```
shared/  →  data/  →  brain/ + risk/ + signal/  →  hands/  →  services/  →  ui/
(基础设施)   (数据层)    (分析层)                      (执行层)     (服务层)      (界面层)

research/  —— 横切科研控制平面（自由度账本 · 四阶门禁 · 策略沙盒），已接入生产因子链
```

---

## 项目状态

> 数据源收敛迁移（Step 0–5）与仓内大清理已完成；项目已越过"迁移目标"阶段，处于**生产加固 + 研究收敛**阶段。
> 当前树实测：`src/uniquant/` **236** 个 Python 文件 / **59,594** LOC；`tests/` **194** 个测试文件 / **2,359** 个测试函数；`ruff` 0。
> 权威状态与实测口径见 [`AGENTS.md`](AGENTS.md)；架构与交易可落地性评估见
> [`docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`](docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md)。

| 层 | 文件数 | LOC | 说明 |
|----|-------|-----|------|
| `brain/` | 62 | 20,046 | FSM、CZSC、LPPL、NTF、Regime、Wyckoff、indicators、factors、screener |
| `shared/` | 42 | 6,994 | 常量、异常、缓存、配置、成本模型、A 股规则、接口契约 |
| `data/` | 33 | 6,828 | 湖优先单源、managers、parsers、cleaners、validators、复权 |
| `hands/` | 33 | 6,254 | 回测引擎、向量化撮合、策略框架、报告 |
| `services/` | 29 | 9,122 | 服务容器、分析编排、数据服务、科研管线、扫描、健康检查 |
| `research/` | 12 | 1,877 | 自由度账本、四阶门禁、策略沙盒（已接入生产因子链） |
| `signal/` | 8 | 2,813 | 适配器、归一化、聚合、质量检查、typed signal |
| `ui/` | 8 | 3,400 | Streamlit 仪表盘、健康检查、manager logic、LPPL 可视化 |
| `risk/` | 8 | 2,259 | 仓位、回撤、EVT、结构化风险、组合优化 |

> **历史文档提示**：早期分层文档/状态页（v0.3、"Phase 0 未开始"、`data`/`signal` 不存在等）
> 描述的是迁移前目标态，**均已过时**；此类页面已从索引中移除。以当前源码与 `AGENTS.md` 为准。

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

### 运行测试

```bash
pytest tests/ -q          # 全量
ruff check src/uniquant/ tests/ scripts/   # 必须 "All checks passed!"
```

---

## 目录结构

```
UniQuant/
├── README.md                   — 本文件
├── CLAUDE.md                   — 10 条仓库编码铁律（来源标注的一致性整理）
├── AGENTS.md                   — 项目控制上下文（权威）
├── pyproject.toml              — 项目元数据
├── config/                     — YAML 配置文件
├── data/                       — 运行时数据（数据湖，本地、gitignore）
├── scripts/                    — 数据 / 研究 / 维护脚本
├── src/uniquant/               — 核心源码
│   ├── research/               — 科研控制平面（自由度账本 / 门禁 / 沙盒）
│   ├── brain/                  — 分析引擎
│   ├── data/                   — 湖优先数据层
│   ├── signal/                 — 信号系统
│   ├── hands/                  — 回测与撮合
│   ├── risk/                   — 风险管理
│   ├── services/               — 服务编排层
│   ├── shared/                 — 公共基础设施
│   └── ui/                     — Streamlit 仪表盘
├── tests/                      — 测试用例
└── docs/                       — 项目文档
```

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | 10 条仓库编码铁律（必读） |
| [AGENTS.md](AGENTS.md) | 项目控制上下文与实测状态（权威） |
| [文档索引](docs/index.md) | 文档状态边界与当前真相源 |
| [简化后架构与交易评估](docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md) | 当前树架构 + 交易可落地性评估（含整改记录） |
| [分析提示词手册](docs/ANALYSIS_PROMPT_PLAYBOOK.md) | 分阶段系统分析（Stage 0-7） |
| [包文档](docs/packages/) | 各模块 API 参考 |
| [快速上手](docs/guides/quickstart.md) | 安装与运行 |

---

## 当前工程主线

数据源收敛迁移（Step 0–5）已收官；当前主线为生产加固与研究收敛：

```
数据源收敛 (Step 0-5)          ✅ 完成（单源湖优先只读 + QFQ 官方对账闭环）
仓内大清理 (39 废弃模块)        ✅ 完成
P0-1 四阶门禁诚实化             ✅ 完成（禁止伪造 B/C/D 输入）
P0-2 CI 归零 + 测试环境隔离      ✅ 完成（ruff 0 / 干净环境 0 fail）
P2-1 过户费全市场统一            ✅ 完成（沪深北 A 股 0.01‰ 双向）
P2-2 LPPL 降为遥测               ✅ 完成（diagnostic_only 默认开，仲裁优先级最低）
P2-3 H-A 运行器对齐 ADV 地板     ✅ 完成
P1-1 科研控制平面接入生产因子链   ✅ 完成（自由度账本覆盖扫描/回测因子链）
P1-2 文档漂移修复                ✅ 完成（README / docs/index.md / CLAUDE.md）
P2-3 CI 覆盖率门                 ✅ 完成（实测 70.55%，门限 68% 作回归地板）
P2-3 数据湖/results 可复现性      ✅ 完成（证据白名单 + SHA-256 内容哈希账本 + CI 校验）
```

**闭环验证（2026-10-16 实测）**：`pytest tests/` **2596 passed / 2 skipped / 0 failed**（收集 2598）；
`-n 8 --cov` 同口径且逐位一致，覆盖率 **70.55%**；`ruff check src/uniquant/ tests/ scripts/` **All checks passed!**；
`python scripts/maintenance/evidence_manifest.py verify` → **no drift**（50 证据文件 / 942,274 B）。

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| 数据处理 | NumPy, Pandas, SciPy, Numba |
| 数据存储 | Parquet (PyArrow), DuckDB |
| 数据源 | 通达信本地 `.day`（主）、mootdx（local / online）、通达信财务归档 |
| 可视化 | Streamlit, Plotly, Matplotlib |
| 测试 | pytest |
| 配置 | YAML (PyYAML) |

---

## 许可证

私有项目 — 未经授权禁止使用或分发。
