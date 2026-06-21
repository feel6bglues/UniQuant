# Queue 2 Audit: 全量业务逻辑 (Data + Brain + Risk + Hands)

**审计时间**: 2026-06-06
**审计范围**: `data/` (15426 LOC) + `brain/` (15743 LOC) + `risk/` (1450 LOC) + `hands/` (5458 LOC)
**总计**: ~38,077 LOC, 约 118 个源文件

---

## 🔴 高危: 幽灵依赖 (Ghost Dependencies)

### 1. `pybreaker` — 直接导入但未声明
- **位置**: `data/sources/base.py:9` `import pybreaker`, `data/managers/source_router.py:5` `import pybreaker`
- **pyproject.toml**: ❌ 未声明
- **风险**: 非 try/except 导入，缺少即 **崩溃**
- **修复**: 添加 `pybreaker>=1.0.0` 至 pyproject.toml

### 2. `backtrader` — 可选但未在 optional-dependencies 注册
- **位置**: `hands/strategies/base.py:3` `try: import backtrader as bt`
- **pyproject.toml**: ❌ 不在 `[project.optional-dependencies]` 中
- **修复**: 添加 `backtrader>=1.11` 至 `[project.optional-dependencies]`

### 3. `exchange_calendars` — 可选但未注册
- **位置**: `hands/strategies/wyckoff.py:10` `try: import exchange_calendars as xcals`
- **pyproject.toml**: ❌ 不在 `[project.optional-dependencies]` 中
- **修复**: 添加 `exchange_calendars>=4.0` 至 `[project.optional-dependencies]`

---

## 🔴 高危: 废弃但保留的函数 (Zombie Deprecated Functions)

以下 4 个函数标记 `@deprecated` / 发出 `DeprecationWarning` 但**从未移除**，且持续被调用：

| # | 文件 | 函数 | 行号 |
|---|------|------|------|
| 1 | `brain/alpha_decoupler/alpha_decoupler.py:298` | `get_alpha_score_from_data()` | L275-305 |
| 2 | `brain/regime/regime_detector.py:239` | `detect_from_data()` | L223-243 |
| 3 | `brain/indicators/indicators.py:322` | `calculate_indicator_from_data()` | L290-326 |
| 4 | `brain/czsc/czsc_engine.py:582` | `get_czsc_signals_from_data()` | L557-587 |

**风险**: 每天有代码调用它们产生 Warning 却无清理计划，占用维护认知负担。

---

## 🟠 全局状态污染

### 1. `data/services/import_1min.py:254` + `data/services/import_5min.py:254`
```python
MAX_WORKERS = 4  # L37: 模块级默认值
def main():
    global MAX_WORKERS   # 在 main() 内修改
    MAX_WORKERS = args.threads
```
仅 `main()` 函数内使用 `global`，标准 CLI 模式。风险较低，但模块级可变常量仍可考虑封装。

### 2. `brain/factors/industry_provider.py:8`
```python
global _CACHE
```
可变模块级缓存字典，无锁保护。

### 3. `risk/historical_risk.py:15`
```python
class HistoricalSimulationRisk(EVTRisk):
```
继承自已废弃的 `EVTRisk`，初始化时发出 DeprecationWarning。属于**循环废弃**。

---

## 🟡 结构性缺陷

### 1. `round10` vs `round_10` — 命名冲突
- `auto_mined/round10_abnormal_volume.py` (旧命名方案)
- `auto_mined/round_10_multi_engine_ensemble.py` (新命名方案)
- 两个文件同时存在，均被 `register_auto_mined.py` 引用。未来可能导致导入歧义。

### 2. `hands/tuning/` — 空目录
- 目录存在但无任何 `.py` 文件，也无 `__init__.py`。属于残留空壳。

### 3. 6 个空 `__init__` 构造函数
| 文件 | 类 | 行 |
|------|-----|-----|
| `hands/backtest/overfitting_detector.py:26` | `OverfittingDetector` | `def __init__(self): pass` |
| `hands/backtest/report_generator.py:28` | `ReportGenerator` | `def __init__(self): pass` |
| `hands/backtest/robustness_checker.py:25` | `RobustnessChecker` | `def __init__(self): pass` |
| `hands/backtest/sensitivity_analyzer.py:23` | `SensitivityAnalyzer` | `def __init__(self): pass` |
| `hands/backtest/trade_analysis/analyzer.py:22` | `TradeAnalyzer` | `def __init__(self): pass` |
| `hands/backtest/trade_analysis/statistics.py:24` | `TradeStatistics` | `def __init__(self): pass` |

### 4. 5 个 CLI 入口函数未注册为 `console_scripts`
- `data/managers/baostock_cache_manager.py:134` — `def main()`
- `data/managers/trade_calendar_manager.py:188` — `def main()`
- `data/managers/cache_manager.py:56` — `def main()`
- `data/services/import_1min.py:253` — `def main()` (with argparse)
- `data/services/import_5min.py:253` — `def main()` (with argparse)
- `data/services/import_financial.py:408` — `def main()` (with argparse)
- `data/services/import_index.py:323` — `def main()` (with argparse)

全部未在 `pyproject.toml` 的 `[project.scripts]` 中注册。

### 5. 40+ 函数超过 100 行
典型超大函数（举例）：

| 文件 | 函数 | 行数 |
|------|------|------|
| `brain/wyckoff/engine.py:269` | `_step1_phase_determine` | 189 |
| `brain/wyckoff/engine.py:1028` | `_build_report` | 184 |
| `brain/wyckoff/engine.py:865` | `_step5_trading_plan` | 151 |
| `data/utils/js_executor.py:66` | `_add_browser_mocks` | 171 |
| `hands/backtest/engine.py:297` | `run_backtest` | 170 |
| `hands/strategies/backtest.py:333` | `run_backtest` | 170 |
| `data/sources/baostock.py:93` | `fetch_daily` | 166 |
| `brain/lppl/calculator.py:445` | `fit` | 138 |
| `brain/factors/analyzer.py:243` | `compute_ic_ir` | 137 |
| `data/utils/request_utils.py:42` | `with_request_control` | 134 |
| `brain/wyckoff/models.py:681` | `to_markdown` | 136 |

### 6. `__init__.py` 状态更正
- `data/services/__init__.py` — ✅ 有 `__all__` 导出 6 个服务类
- `data/utils/__init__.py` — ⚠️ 仅 36 字节，`__all__ = []`（无导出）
- `data/scripts/__init__.py` — ✅ 有 `__all__` 导出 4 个函数
- `hands/strategies/__init__.py` — ✅ 1647 字节，完整 `__getattr__` 懒加载系统 + 6 策略导出

---

## 🟢 包架构审计 (Package Structure)

### `data/` 内部结构
| 子包 | 文件数 | 初始化 | 导出 |
|------|--------|--------|------|
| `sources/` | 11 | ✅ | 6 个源类 |
| `managers/` | 12 | ✅ | 9 个管理器 |
| `pipeline/` | 4 | ✅ | 4 个管道组件 |
| `parsers/` | 1 | ✅ | 1 个解析器 |
| `lake/` | 1 | ✅ | StorageManager |
| `services/` | 6 | ✅ | 6 个服务类导出 |
| `utils/` | 7 | ⚠️ | 36 字节空壳，`__all__ = []` |
| `scripts/` | 8 | ✅ | 4 个函数导出 |

### `brain/` 内部结构
所有 9 个子包均有 `__init__.py` 且导出正确。`brain/__init__.py` 使用 try/except 将 6 个引擎标记为可选（`NTFEngine = None`），虽然弹性好但静默吞掉错误。

### `risk/` 内部结构
全部 6 个模块从 `risk/__init__.py` 导出，结构清晰。

### `hands/` 内部结构
- `backtest/` ✅ 完整
- `strategies/` ✅ 1647 字节，含 `__getattr__` 懒加载 + 6 策略导出
- `tuning/` ❌ 空目录（无文件）
- `results_manager.py`, `reporter.py` ✅ 顶层模块

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计总 LOC | 38,077 |
| 幽灵依赖 | 3 (`pybreaker`, `backtrader`, `exchange_calendars`) |
| 废弃函数未清理 | 4 |
| 全局状态点 | 3 |
| 超大函数 (>100行) | 40+ |
| 空/不足 `__init__.py` | 1 (`data/utils/`) |
| 空目录 | 1 (`tuning/`) |
| 未注册 CLI | 7 |

---

## 🎯 建议优先级 (Queue 2)

| 优先级 | 项目 | 影响 |
|--------|------|------|
| P0 | 在 pyproject.toml 添加 `pybreaker` | 导入即崩溃 |
| P0 | 清理 `round10` vs `round_10` 命名冲突 | 导入歧义 |
| P1 | 添加 `backtrader`、`exchange_calendars` 至 optional-deps | 可选功能不可用 |
| P1 | 清理 4 个 deprecated 函数或移除 | 技术债积累 |
| P2 | 注册 7 个 CLI main() 至 console_scripts | 无法通过命令行调用 |
| P2 | 拆分 40+ 超大函数 | 可维护性 |
| P2 | 检查 `data/utils/__init__.py` 是否需补充导出 | 包导出不完整 |
| P3 | 移除 `hands/tuning/` 空目录 | 残留空壳 |
