# Phase 2: 全局冲突矩阵 (Global Conflict Matrix)

**生成时间**: 2026-06-06
**数据来源**: Queue_1 + Queue_2 + Queue_3 + Queue_4 审计报告

---

## M1 🔴 幽灵依赖跨层链 (Ghost Dependency Chain)

7 个直接导入但未在 `pyproject.toml` 声明的包，分布在 3 个层级。

| 依赖 | 使用层 | 导入方式 | 风险等级 | 发现于 |
|------|--------|----------|----------|--------|
| `urllib3` | shared | 硬导入 | 🔴 缺少即崩溃 | Q1 |
| `pybreaker` | data | 硬导入 | 🔴 缺少即崩溃 | Q2 |
| `backtrader` | hands | try/except 可选 | 🟠 可选功能不可用 | Q2 |
| `exchange_calendars` | hands | try/except 可选 | 🟠 可选功能不可用 | Q2 |
| `st_aggrid` | ui | try/except 可选 | 🟠 仪表盘不完整 | Q3 |
| `streamlit_autorefresh` | ui | try/except 可选 | 🟠 仪表盘不完整 | Q3 |
| `streamlit_echarts` | ui | try/except 可选 | 🟠 仪表盘不完整 | Q3 |

**冲突**: `urllib3` 和 `pybreaker` 缺少即崩溃，但无版本锁定。
**根因**: `pyproject.toml` 从未同步更新，依赖管理流程缺失。

---

## M2 🔴 全局状态污染模式 (Global State Pattern)

`global` 声明跨 5 个模块，构成全系统潜在竞态区域。

| 文件 | 变量 | 类型 | Queue |
|------|------|------|-------|
| `shared/config_loader.py:324` | `config` | 模块级单例 | Q1 |
| `shared/error_handling.py:308` | `_error_stats` | 无锁字典 | Q1 |
| `shared/logger_factory.py:177` | `_factory` | 绕过锁赋值 | Q1 |
| `shared/env_config.py:41` | `OMP_NUM_THREADS` | 环境变量副作用 | Q1 |
| `data/services/import_1min.py:254` | `MAX_WORKERS` | 并发覆盖 | Q2 |
| `data/services/import_5min.py:254` | `MAX_WORKERS` | 并发覆盖 | Q2 |
| `brain/factors/industry_provider.py:8` | `_CACHE` | 无锁缓存 | Q2 |
| `services/health_service.py:503` | `health_service` | 无锁单例 | Q3 |

**冲突**: `shared/` 贡献 4/8 全局状态点，但作为所有上层的基础库，其全局状态影响整个系统。
**根因**: 未采用 DI 容器替代模块级单例模式。

---

## M3 🟡 根目录代码与包内重复 (Root ↔ Package Duplication)

| 根目录文件 | 包内对应 | 重叠内容 |
|-----------|----------|----------|
| `deep_analysis_experiment.py` (991 LOC) | `brain/wyckoff/` | Wyckoff 分析逻辑 |
| `*.py` 因子脚本 (12 文件) | `brain/factors/` | 因子计算/分析 |
| `*.py` 回测脚本 (6 文件) | `hands/backtest/` | 策略回测 |
| `wyckoff_mining_harness.py` | `brain/wyckoff/engine.py` | 挖掘管线 |
| `verify_tdx_import.py` | `data/sources/tdx/` 或 `data/managers/` | TDX 导入验证 |

**冲突**: 同一功能两套实现，根目录一次性和包内维护版本不同步。修改包内代码不会反映到根脚本。
**根因**: V1 → V2 重构时留下旧脚本，未归档。

---

## M4 🟡 空/不足 `__init__.py` (Incomplete Init)

仅 1 个完全空 `__init__.py` + 1 个无导出 `__init__.py`。

| 位置 | 影响 | Queue |
|------|------|-------|
| `data/utils/__init__.py` | 36 字节，`__all__ = []` 无导出 | Q2 |
| `ui/__init__.py` | 1 字节完全空文件 | Q3 |

**已核实**: `data/services/__init__.py` ✅ 有 6 个导出；`data/scripts/__init__.py` ✅ 有 4 个导出；`hands/strategies/__init__.py` ✅ 有 1647 字节懒加载系统。

**冲突**: `shared/` 和 `signal/` 的 `__init__.py` 有完整导出，但与 `ui/__init__.py` 的空文件形成不一致。
**根因**: 重构时未规范化包导出。

---

## M5 🟡 1500+ 行单体文件与散落脚本 (Monolith ↔ Scatter)

| 维度 | 现象 | 规模 |
|------|------|------|
| 单体 | `analysis_service.py` 单一文件 | 1,650 LOC |
| 单体 | `dashboard.py` 单体文件 | 1,524 LOC |
| 散落 | 根目录散落脚本 | 34 files / 20,110 LOC |
| 散落 | 散落地在 2 个子包 | `data/scripts/` (8) + `scripts/` (12) |

**冲突**: 一方面 `services/` 和 `ui/` 文件过度集中（2 文件 3,174 LOC），另一方面根目录 34 文件 20,110 LOC 过度分散。集中与分散并存。
**根因**: Node.js 式的 "脚本即入口" 文化与 Python 包模式的冲突。

---

## M6 🟠 测试裂化 （Test Decay）

| 问题 | 影响范围 | Foundation Q1 | Biz Logic Q2 | Services Q3 | Peripheral Q4 |
|------|----------|---------------|--------------|-------------|---------------|
| 完全跳过 | 2 文件 | - | - | - | ✅ |
| 条件跳过 | 8 文件 | - | ✅ | ✅ | ✅ |
| 过大 (>400) | 7 文件 | - | - | - | ✅ |
| `conftest.py` 不足 | 全部 | - | - | - | ✅ |

**冲突**: 77 测试文件 / 15,065 LOC 的测试资产中，**至少 10 文件含 skip**，**7 文件 >400 行**，而 `conftest.py` 仅 27 行。
**根因**: 测试随功能增量编写，无测试架构审查。

---

## M7 🟠 废弃函数/代码延迟清理 (Deprecated Accumulation)

| 项目 | 类型 | 标记时间 | 引用者 | Queue |
|------|------|----------|--------|-------|
| `get_alpha_score_from_data()` | deprecated 函数 | 未知 | 未知 | Q2 |
| `detect_from_data()` | deprecated 函数 | 未知 | 未知 | Q2 |
| `calculate_indicator_from_data()` | deprecated 函数 | 未知 | 未知 | Q2 |
| `get_czsc_signals_from_data()` | deprecated 函数 | 未知 | 未知 | Q2 |
| `di_container.py` 整文件 | DEPRECATED 模块 | 未知 | 无 | Q1 |

**冲突**: 5 个废弃项目同时存活，且 `risk/historical_risk.py` 继承自废弃的 `EVTRisk`，形成循环废弃链。
**根因**: 无废弃代码清理时间表。

---

## M8 🟠 配置硬编码与查询魔数 (Hardcoded Values)

| 位置 | 值 | 应该使用 | Queue |
|------|-----|----------|-------|
| `config.yaml base.tdx.path` | `/home/james/.local/share/tdxcfv/...` | 环境变量 | Q1 |
| `scripts/run_market_scan.py` | `s.startswith(('000001', '000002', ...))` 30+ 行排除 | `BoardType` 枚举 + 正则 | Q4 |

**冲突**: `shared/constants/market.py` 已定义 `SZ_MAIN_BOARD = ["000", "001"]` 等 30+ 条规则，但脚本仍硬编码。
**根因**: 脚本早于常量定义，重构未覆盖。

---

## ✅ 无冲突项确认 (Clean Confirmed)

以下项目在所有 4 个队列中确认无层间冲突：

1. **5 层 DAG 方向**: 未发现 `services → ui` 等反向依赖
2. **循环依赖**: 未发现 `a → b → a` 型循环
3. **缺失 Protocol**: 5 个 Protocol 接口在 `shared/interfaces.py` 中正确暴露，无断裂引用
4. **YAML 配置覆盖**: 4 个 YAML 文件之间无键名冲突
5. **测试命名**: 77 测试文件命名一致（`test_*.py`），无 `*_test.py` 异构命名

---

## 📊 冲突矩阵总览

| 编号 | 冲突 | 层数 | 严重度 | 影响文件数 |
|------|------|------|--------|-----------|
| M1 | 幽灵依赖链 | 3 | 🔴 | 7 包 |
| M2 | 全局状态污染 | 3 | 🔴 | 8 文件 |
| M3 | 根目录与包重复 | 2 | 🟡 | 34 根文件 ↔ 包内 |
| M4 | 空/不足 `__init__` | 2 | 🟡 | 2 文件 |
| M5 | 单体与散落并存 | 2 | 🟡 | 2 单体 + 34 散落 |
| M6 | 测试裂化 | 全层 | 🟠 | 10 跳过 + 7 过大 |
| M7 | 废弃积累 | 2 | 🟠 | 5 项目 |
| M8 | 硬编码值 | 2 | 🟠 | 2 文件 |
| - | DAG 方向正确 | 全层 | ✅ | - |
| - | 无循环依赖 | 全层 | ✅ | - |
| - | Protocol 完整 | 全层 | ✅ | - |
