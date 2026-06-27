# UniQuant 文档管理计划

**版本:** v1.0 | **日期:** 2026-05-26 | **状态:** 执行中

---

## 1. 现状分析

### 1.1 文档统计

| 类别 | 文件数 | 状态 |
|------|--------|------|
| 架构文档 | 1 | 完整但与实际代码脱节 |
| 包文档 (packages/) | 8 | 目标状态文档，非当前状态 |
| 指南 (guides/) | 6 | 质量高，但引用不存在的模块 |
| 参考 (reference/) | 4 | 完整，基于 shared/constants/ |
| 开发 (development/) | 2 | 与实际严重不符 |
| 修复计划 | 1 | 引用不存在的文件 |
| 重构计划 | 1 | 全部未执行 |
| **总计** | **23** | |

### 1.2 核心问题

| 问题 | 影响 | 严重度 |
|------|------|--------|
| 文档描述的是目标状态，非当前状态 | 新开发者无法理解系统实际能力 | HIGH |
| 测试文档声称 65+ 文件，实际仅 11 个 | 误导贡献者 | HIGH |
| 指南引用不存在的模块 (data/, signal/, hands/backtest/) | 代码示例无法运行 | HIGH |
| fix_plan.md 引用不存在的文件 | 修复计划不可执行 | MEDIUM |
| 无 README.md | 项目入口缺失 | HIGH |
| 文档无版本标记 | 无法追踪文档与代码的对应关系 | MEDIUM |

---

## 2. 文档管理策略

### 2.1 文档分层模型

```
Layer 0: README.md              — 项目入口，5 分钟了解项目
Layer 1: 架构文档                — 系统设计，面向架构师
Layer 2: 包文档 (packages/)     — 模块 API，面向开发者
Layer 3: 指南 (guides/)         — 使用教程，面向用户
Layer 4: 参考 (reference/)     — 常量/异常/信号速查
Layer 5: 开发 (development/)   — 贡献指南
Layer 6: 计划文档               — 重构/修复计划（归档）
```

### 2.2 文档与代码同步规则

#### 规则 1: 文档必须标注适用版本

每个文档头部包含状态标记：

```markdown
> **状态:** ✅ 当前可用 | ⚠️ 部分可用 | 🎯 目标状态（重构后）
> **适用代码版本:** 当前 | 目标版本 v2.0
```

#### 规则 2: 不存在的模块必须标注

当文档引用尚未实现的模块时：

```markdown
> ⚠️ 以下模块尚未迁移，计划在 Phase 1B 中完成：
> - `data/sources/base.py`
> - `data/lake/storage_manager.py`
```

#### 规则 3: 代码示例必须可验证

每个代码示例标注是否可在当前代码库运行：

```python
# ✅ 可运行 (requires: shared.constants)
# ⚠️ 需要 Phase 1B 完成后可运行
```

#### 规则 4: 重构计划归档

已完成或不再适用的计划文档移至 `docs/archive/`，并标注最终状态。

### 2.3 文档更新触发条件

| 触发事件 | 需要更新的文档 |
|----------|---------------|
| 新模块迁移到 UniQuant | 对应包文档、项目结构 |
| Phase 执行完成 | 重构计划 checklist、相关包文档 |
| 新增测试文件 | 测试指南 |
| API 变更 | 对应包文档的 API 部分 |
| 配置文件变更 | 配置指南 |

---

## 3. 目录结构调整

### 当前结构

```
docs/
├── architecture.md
├── fix_plan.md
├── index.md
├── development/
│   ├── project_structure.md
│   └── testing.md
├── guides/
│   ├── backtest.md
│   ├── configuration.md
│   ├── data_sources.md
│   ├── factors.md
│   ├── quickstart.md
│   └── strategies.md
├── packages/
│   ├── brain.md
│   ├── data.md
│   ├── hands.md
│   ├── risk.md
│   ├── services.md
│   ├── shared.md
│   ├── signal.md
│   └── ui.md
└── reference/
    ├── a_share_constraints.md
    ├── constants.md
    ├── exceptions.md
    └── signal_types.md
```

### 目标结构

```
docs/
├── DOC_MANAGEMENT_PLAN.md    — 本文档
├── STATUS.md                 — 项目状态仪表盘（新）
├── architecture.md           — 系统架构（保留，标注状态）
├── fix_plan.md               — 归档（标注：待执行）
├── index.md                  — 更新导航，区分可用/目标
│
├── packages/                 — 包文档（标注模块实际状态）
│   ├── brain.md              — ⚠️ 仅 czsc/fsm/lppl 可用
│   ├── data.md               — 🎯 目标状态（当前不存在）
│   ├── hands.md              — 🎯 目标状态（当前仅 __init__.py）
│   ├── risk.md               — ⚠️ 仅 drawdown_analyzer 可用
│   ├── services.md           — ⚠️ 部分可用
│   ├── shared.md             — ✅ 基本完整
│   ├── signal.md             — 🎯 目标状态（当前不存在）
│   └── ui.md                 — ⚠️ 仅 dashboard/health_check 可用
│
├── guides/                   — 使用指南（保留，标注依赖）
│   ├── quickstart.md         — ⚠️ 需要 data 层迁移后可用
│   ├── backtest.md           — 🎯 目标状态
│   ├── factors.md            — 🎯 目标状态
│   ├── strategies.md         — 🎯 目标状态
│   ├── data_sources.md       — 🎯 目标状态
│   └── configuration.md      — ✅ 可用
│
├── reference/                — 参考手册（保留）
│   ├── a_share_constraints.md
│   ├── constants.md
│   ├── exceptions.md
│   └── signal_types.md
│
├── development/              — 开发文档（更新）
│   ├── project_structure.md  — 更新为实际文件清单
│   └── testing.md            — 更新为实际测试状态
│
└── archive/                  — 归档（新建）
    └── restructure_plan.md   — 重构计划归档
```

---

## 4. 任务清单

### Phase 1: 立即执行

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 1.1 | 创建 README.md | `README.md` | HIGH |
| 1.2 | 创建 STATUS.md | `docs/STATUS.md` | HIGH |
| 1.3 | 更新 index.md 区分实际/目标 | `docs/index.md` | HIGH |
| 1.4 | 为 packages/ 添加状态标记 | `docs/packages/*.md` | HIGH |

### Phase 2: 一周内完成

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 2.1 | 更新 project_structure.md 为实际状态 | `docs/development/project_structure.md` | MEDIUM |
| 2.2 | 更新 testing.md 为实际测试数 | `docs/development/testing.md` | MEDIUM |
| 2.3 | 为 guides/ 添加依赖标注 | `docs/guides/*.md` | MEDIUM |
| 2.4 | 归档 fix_plan.md | `docs/archive/fix_plan.md` | LOW |

### Phase 3: 重构过程中

| # | 任务 | 触发条件 |
|---|------|---------|
| 3.1 | 每个 Phase 完成后更新对应包文档 | Phase 1A-1F 完成 |
| 3.2 | 更新 STATUS.md 进度 | 每个 Phase 完成 |
| 3.3 | 移除"目标状态"标记，改为"当前可用" | 对应模块迁移完成 |
| 3.4 | 更新 testing.md 测试文件数 | Phase 3 测试迁移完成 |

---

## 5. 文档质量标准

### 5.1 每个包文档必须包含

1. **模块状态** — 标注 ✅/⚠️/🎯
2. **公开导出** — `__init__.py` 的实际导出列表
3. **核心类/函数** — 签名、参数、返回值
4. **代码示例** — 标注是否可运行
5. **依赖关系** — 依赖哪些其他包

### 5.2 每个指南必须包含

1. **前置条件** — 需要哪些模块已就绪
2. **安装步骤** — 如何安装依赖
3. **完整代码** — 可直接复制运行
4. **预期输出** — 运行后应看到什么

### 5.3 每个参考文档必须包含

1. **源码位置** — 定义在哪个文件
2. **完整字段** — 所有字段/枚举值
3. **使用示例** — 最少 1 个

---

## 6. 版本管理

文档版本与代码版本解耦，但需标注对应关系：

| 文档版本 | 对应代码状态 | 说明 |
|----------|-------------|------|
| v1.0 | 当前 (44 文件) | 基线文档 |
| v2.0 | Phase 1 完成后 | 迁移完成文档 |
| v3.0 | Phase 2 完成后 | mootdx 集成文档 |

每个文档底部标注：

```markdown
*文档版本: v1.0 | 最后更新: 2026-05-26*
*适用代码: src/uniquant/ (44 files, Phase 0 未执行)*
```
