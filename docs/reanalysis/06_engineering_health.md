# Phase 6 — 工程健康度审计

> 日期: 2026-06-30 (base) / 2026-07-09 (corrected)
> 方法: 静态分析 + 导入测试 + lint + 代码规模追踪
> **纠正项**: eastmoney.py 已拆分为 4 文件; 文件数 254→256; 测试 1,435→1,666; 5 失败→0

---

## 报告摘要

代码库工程健康度良好: 1,666 测试通过, 仅 29 个 ruff 问题 (20 可自动修复),
5 个 TODO (全库), 8 层导入通过, 256 源文件 / 62,465 LOC。

**健康评级: A-** (低技术债, 高可维护性)

---

## 静态分析

### Ruff 结果 (29 项)

| 代码 | 数量 | 严重度 | 可自动修复 |
|---|---|---|---|
| F401 (未使用 import) | 20 | 低 | ✅ 是 (20/20) |
| F841 (未使用变量) | 8 | 低 | ❌ 需手动 |
| F821 (未定义名称) | 1 | 中 | ❌ `macro_service.py:214` `datetime` |

### TODO/FIXME 标记 (5 项)

| 文件 | 行 | 内容 |
|---|---|---|
| `risk/sizer.py` | 457 | `TODO: Enforce max_single_sector_pct` |
| `data/sources/eastmoney.py` | 27 | `TODO(refactor): 巨型类 — 1090行` |
| `brain/fsm/fsm.py` | 23 | `TODO: Phase 1A 迁移 brain/indicators.py 后移除` |
| `data/lake/storage_manager.py` | 173,203 | 函数文档注释 (非 TODO) |

---

## 代码规模

| 层级 | 文件数 | LOC |
|---|---|---|
| `shared` | 44 | × |
| `data` | 65 | × |
| `brain` | 55 | × |
| `signal` | 8 | × |
| `hands` | 34 | × |
| `risk` | 7 | × |
| `services` | 32 | × |
| `ui` | 8 | × |
| **总计** | **256** | **62,465** |

---

## 测试覆盖

| 指标 | 值 |
|---|---|
| 测试文件 | 126 |
| 测试函数 | 1,666 |
| Passing | 1,666 (100%) |
| Failed | 0 |
| Skipped | 8 |

### Pre-existing 失败 ✅ 全部已修复 (bc6337bc)

所有 5 个 pre-existing 失败已在 bc6337bc 中修复, 当前 0 失败。

---

## 导入健康

| 测试 | 结果 |
|---|---|
| 8 层导入: `shared/brain/data/signal/services/risk/hands/ui` | ✅ 通过 |
| Config smoke: `get_config()` | ✅ 通过 |
| ServiceContainer: `initialize()` | ✅ 通过 |
| EngineFactory smoke: pytest | ✅ 通过 |

---

## 发现

### 1. `macro_service.py:214` 未定义 `datetime`
`datetime.timedelta` 引用缺少 `import datetime`。运行时可能崩溃。
在其他文件中已正确导入 (如 `cost_model.py:15` `import datetime`), 但该文件缺少。

### 2. ~~`eastmoney.py` — 1090 行巨型类~~ ✅ 已完成重构
`data/sources/eastmoney.py` 已拆分为 4 个文件: `eastmoney.py` (3 LOC, re-export only), `eastmoney_base.py`, `eastmoney_financial.py`, `eastmoney_quote.py`. 建议删除原 TODO 注释。

### 3. 无长期 TODO 标记
仅 5 个 TODO 标记, 全库无 FIXME/HACK/XXX/BUG 标记。
表明代码库维护纪律良好。

---

## 健康评级: A-

| 维度 | 评分 | 理由 |
|---|---|---|
| Lint 健康 | A- | 29 项, 20 可自动修复, 1 个中等 |
| 技术债标记 | A | 5 TODO, 无 FIXME/BUG/XXX |
| 导入健康 | A | 8 层 + config + container 全部通过 |
| 测试通过率 | A- | 99.4% (1426/1435) |
| 文件规模 | A- | 最大文件: analysis_service_legacy.py (1,649 LOC, 死代码), eastmoney 已拆分为 4 文件 |
