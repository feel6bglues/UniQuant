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
> 当前树实测：`src/uniquant/` **232** 个 Python 文件 / **58,475** LOC；`tests/` **214** 个测试文件 / **3,093** 个测试函数；`ruff` 0。
> 权威状态与实测口径见 [`AGENTS.md`](AGENTS.md)；架构与交易可落地性评估见
> [`docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`](docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md)。

| 层 | 文件数 | LOC | 说明 |
|----|-------|-----|------|
| `brain/` | 62 | 20,046 | FSM、CZSC、LPPL、NTF、Regime、Wyckoff、indicators、factors、screener |
| `shared/` | 42 | 6,999 | 常量、异常、缓存、配置、成本模型、A 股规则、接口契约 |
| `data/` | 32 | 6,577 | 湖优先单源、managers、parsers、cleaners、validators、复权 |
| `hands/` | 33 | 6,257 | 回测引擎、向量化撮合、策略框架、报告 |
| `services/` | 26 | 8,246 | 服务容器、分析编排、数据服务、科研管线、扫描、健康检查 |
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
P0-2 CI 归零 + 测试环境隔离      ✅ 完成（ruff 0 / 本地 `/tmp` 依赖清除）
P0-2 CI 真绿化（数据湖依赖）      ✅ 完成（130 个真实数据用例声明式跳过，CI 两作业全绿）
P2-1 过户费全市场统一            ✅ 完成（沪深北 A 股 0.01‰ 双向）
P2-2 LPPL 降为遥测               ✅ 完成（diagnostic_only 默认开，仲裁优先级最低）
P2-3 H-A 运行器对齐 ADV 地板     ✅ 完成
P1-1 科研控制平面接入生产因子链   ✅ 完成（自由度账本覆盖扫描/回测因子链）
P1-2 文档漂移修复                ✅ 完成（README / docs/index.md / CLAUDE.md）
P2-3 CI 覆盖率门                 ✅ 完成（真实 CI 口径实测 74.57%，门限 74% 作回归地板）
P2-3 数据湖/results 可复现性      ✅ 完成（证据白名单 + SHA-256 内容哈希账本 + CI 校验）
第三轮 数据层补测                ✅ 完成（data/ 53.9% → 94.2%；13 文件 / 634 用例）
第三轮 历史文档漂移根治          ✅ 完成（docs/reanalysis 60 文件 + docs/archive 10 文件加历史横幅）
第三轮 潜在缺陷修复              ✅ 完成（parse_day_file 截断/NaT、storage_manager 路径遍历）
第四轮 CI 数据湖依赖收口          ✅ 完成（requires_lake/futures_lake/gbbq 三标记 + 集中跳过钩子）
第五轮 CI 收集期中断修复          ✅ 完成（硬编码开发机兄弟仓路径 → 仓库内相对定位 + 防回归守卫）
第五轮 测试导入期 HOME 污染修复    ✅ 完成（静默跳过 5 个真实数据用例 → 删除 + 第二条防回归守卫）
第五轮 CI 首次全绿（自 7509c2a）   ✅ 完成（run 38870946347：test 全 8 步 + coverage + pip-audit 三绿）
第六轮 §7.4 十项疑似缺陷处置       ✅ 完成（8 修 / 2 书面不修；含 4 个"钉住 bug"的用例反转 + 1 个同类兄弟缺陷）
第六轮 "CI 口径"自我打假           ✅ 完成（真实 CI 缺未声明的 czsc → 真实 CI 口径 74.57% / 164 skipped）
第七轮 生产孤岛剪除 + services 补测  ✅ 完成（3 个零调用方门面类剪除；215 用例；services 65.6% → 79.7%）
第七轮 CI 解释器专属日志格式化真 bug  ✅ 完成（6 处 `{}`→`%s`；AST 防复发守卫 + 端到端反证）
第七轮 CI 覆盖率门余量解除          ✅ 完成（真实 CI 77.47%，门限 74 余量由 +0.57pt 升至 +3.47pt）
```

**闭环验证（2026-10-16 第三轮实测，本机含数据湖）**：`pytest tests/` **3226 passed / 2 skipped / 0 failed**（收集 3228）；
`-n 8 --cov` 同口径且逐位一致，覆盖率 **76.05%**（`data/` 层 **94.2%**，最弱层转为 `services/` 63.8%）；
`ruff check src/uniquant/ tests/ scripts/` **All checks passed!**；
`python scripts/maintenance/evidence_manifest.py verify` → **no drift**（50 证据文件 / 942,274 B）。

**本机口径（2026-10-17 第七轮实测，含数据湖 + 手工装的未声明 `czsc`）**：`pytest tests/ -q -n auto`
**3464 passed / 2 skipped / 0 failed / 0 error**（收集 3466；仅 2 个 backtrader 缺依赖 skip；`requires_*` 标记在本机为 no-op，用例全部真跑）；
覆盖率 **78.72%**（25,854 语句 / 5,501 未覆盖）。

**真实 CI 口径（2026-10-17 第七轮实测并更正；依赖集 = `pip install -e ".[all,dev]"`）**：
`pytest tests/` **3278 passed / 165 skipped / 0 failed / 0 error**（收集 3443，每个跳过均带显式原因）；
覆盖率 **77.47%**（25,854 语句 / 5,824 未覆盖）≥ 门限 74（**余量 +3.47 个百分点**——第六轮仅 +0.57，见下）。
真实数据用例依赖的本地数据湖（`data/lake/**`）、GBBQ 基线（`data/fq/gbbq.parquet`）与本地通达信客户端
均不进版本库，CI 上由 `requires_lake` / `requires_futures_lake` / `requires_gbbq` 三标记**声明式跳过**（非静默通过）。

> **第七轮做了什么（2026-10-17）**：① **剪除 3 个生产孤岛**（`services/analysis/{macro,technical,signal}_service.py`，
> 零调用方、职责已被在线 `AnalysisService` + `AnalysisEngineFactory` 承接；整包语句 26,268 → 25,854）；
> ② **`services/` 层补测 215 用例**（`services/` 65.57% → **79.69%**，**不再是历史最弱层；现最弱层为 `hands/` 64.19%**）；
> ③ **修复一个只在 CI 解释器暴露的真 bug**：`services/validation_service.py` 6 处把 `{}` 风格当 `%` 风格参数
> （`logger.warning("… {}", a, b)`）→ stdlib 做 `msg % args` 抛 `TypeError`；本机被 pytest 捕获 handler 掩盖，
> **CI 上会让校验失败路径返回空 `results`、丢失逐项诊断**。已改 `{}`→`%s`（消息文本逐字不变），并加 AST 守卫
> `tests/test_no_logging_format_mismatch.py`（含正/负对照 + 端到端反证）。详见报告 §7.10。

> ⚠️ **"CI 口径"必须连同依赖集一起报（第六轮更正）**：第四/五轮记录的 CI 口径
> `3,081 passed / 151 skipped / coverage 75.57%` 是在**装了 `czsc`** 的解释器上测得的。
> 但 **`czsc` 并非本仓声明依赖**（`pyproject.toml` 的 `dependencies` 与所有 optional-extras 都没有它；
> `pip show czsc` → `Required-by: rs_czsc`，`rs_czsc` 同样未声明），而 CI 只执行
> `pip install -e ".[all,dev]"` → **真实 CI 没有 `czsc`** → 4 个 `pytest.importorskip("czsc")` 模块
> **整块不被收集（少 30 例）**、`tests/test_brain_boundary_qa.py` 再跳 9 例、
> `brain/czsc/czsc_engine.py` 全额计入未覆盖。故**真实 CI 数字是上段**（3052/164/74.57%）。
> 本轮**不修**（把 `czsc` 塞进 `[all]` 会引入 `ta-lib` 系统级 C 库依赖，很可能让 CI 的安装步骤本身变红），
> 仅如实登记为可选依赖治理项。详见报告 §7.9。

**✅ CI 已全绿（2026-10-16 第五轮实测，真实 GitHub Actions）**：push `a434d68` → run **`38870946347`** —— `test` 作业全 8 步 success（含此前长期被 skip 的
`Lint with ruff` 与 `Test with pytest`，后者 ~2.5 min 真跑）、`coverage` 作业 `Test with coverage gate` success（~112 s ⇒ CI 上 74% 门限达标）、
`Security Audit` run `38870946235` success → **三条 check-run 全绿**。这是自 `7509c2a` 以来 CI 首次全绿。

> ⚠️ **CI 曾长期红的三个串联成因**（第四轮曾单因归因于数据湖，已更正）：① `ruff` lint 失败（使 pytest 步骤被
> skip）；② **测试收集期中断**——`tests/test_uniquant_production_architecture_gates.py` 硬编码开发机兄弟仓
> 绝对路径 `/home/james/Documents/Project/CNNM/scratch` → CI 上 `ModuleNotFoundError: order_state_machine`
> → `Interrupted: 1 error during collection` → **零用例执行（exit 2）**；③ 130 个数据湖依赖用例。
> 第五轮修掉 ②（路径改为 `Path(__file__)` 仓库内相对定位 + 从入库的 `scratch/` 导入 + 新增防回归守卫
> `tests/test_no_dev_absolute_paths.py`）。同轮还发现并修复同族缺陷：`tests/test_import_financial.py` 在**导入期**
> 写 `os.environ["HOME"] = "/tmp"`，被 pytest 同进程按文件名顺序导入后污染后续模块，**静默跳过 5 个真实数据用例**
> （本机 2 skip → 7 skip）——已删除，并加第二守卫 `tests/test_no_import_time_env_mutation.py`。详见报告 §7.7。
> **教训**：本地等价复现 CI 必须同时屏蔽**数据依赖**与**开发机专有路径依赖**两类；测试不得依赖导入顺序或进程级可变状态。

> ⚠️ **第六轮补充教训（"CI 口径"必须连同依赖集一起报）**：本地"CI 等价"复现还有**第三类**偏差——**解释器依赖集**。
> 第四/五轮测出的 `151 skipped / 75.57%` 是在装了 `czsc` 的 `.venv` 里得到的，而 `czsc` **并非本仓声明依赖**
> （CI 只装 `.[all,dev]`）→ 真实 CI 为 `164 skipped / 74.57%`。**只报"CI 等价"而不报"装了什么"是会骗人的。**

> ⚠️ **CI 覆盖率门余量（第六轮登记 → 第七轮解除）**：第六轮时门限 `--cov-fail-under=74` 相对**真实 CI 口径 74.57%**
> 仅余 **+0.57 个百分点**，登记为"留给下一轮"的风险项。**第七轮通过剪除孤岛 + 补测 215 用例将其抬到 77.47%（余量 +3.47pt）**，
> 风险解除。**门限始终未动**（降门限=掩盖问题）；若后续新增未覆盖的生产模块再次逼近门限，正确做法仍是**补测**，不是降门限。

> ⚠️ **第七轮新增教训（"本地绿、CI 红"的又一个来源：解释器 handler 行为差异）**：同一个 `logger.warning` 调用，
> 格式化异常在本机被 pytest 的捕获 handler **吞掉**、在 CI 的解释器/配置上**冒泡**——于是缺陷本地不可见、CI 才现形。
> 与 §7.7 的收集期中断同族：**缺陷一直在，只是被环境掩盖**。故本轮为这类"日志格式化 arity 不匹配"加了静态守卫。

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
