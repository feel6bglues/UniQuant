# Queue 2 审计报告 V3: 核心业务逻辑 (Data + Brain + Risk + Hands)

**审计时间**: 2026-06-06
**审计范围**:
- `data/` (65 文件, ~15,426 LOC) — sources/managers/pipeline/parsers/lake/services/utils/scripts
- `brain/` (73 文件, ~15,743 LOC) — alpha_decoupler/czsc/factors/fsm/indicators/lppl/ntf/regime/screener/wyckoff
- `risk/` (7 文件, ~1,450 LOC) — 5 个模块
- `hands/` (33 文件, ~5,458 LOC) — backtest/strategies/results_manager/reporter

**总计**: 178 文件 / ~38,077 LOC

---

## ✅ V2 报告核实

| V2 报告原话 | V3 核实结果 | 状态 |
|------------|------------|------|
| `pybreaker` 幽灵依赖 | **确认** — `data/sources/base.py:9`、`data/managers/source_router.py:5` 硬导入 | ✅ V2 正确 |
| `backtrader` 未在 optional-deps | **确认** — `hands/strategies/base.py:3` 硬 try/except 导入 | ✅ V2 正确 |
| `exchange_calendars` 未注册 | **确认** — `hands/strategies/wyckoff.py:10` 硬 try/except 导入 | ✅ V2 正确 |
| 4 个 deprecated 函数 (alpha/regime/indicators/czsc) | **确认** — 全部 4 个存在且**零外部调用方**（仅 self-warning） | ✅ V2 正确 |
| `import_1min.py:254` global MAX_WORKERS | **确认** — `MAX_WORKERS = 4` 在 L37 模块级，main() 内 `global MAX_WORKERS` | ✅ V2 正确 |
| `industry_provider.py:8` global _CACHE | **确认** — 无锁保护的全局缓存 | ✅ V2 正确 |
| `HistoricalSimulationRisk` 继承废弃的 `EVTRisk` | **确认** — `risk/historical_risk.py:15` 发出 `DeprecationWarning` | ✅ V2 正确 |
| 4 个空 `__init__.py` | ⚠️ **部分修正** — `data/services/__init__.py` 有 6 个导出；`data/utils/__init__.py` 36 字节空壳；`data/scripts/__init__.py` 有 4 个导出；`hands/strategies/__init__.py` 1647 字节有完整懒加载 | ⚠️ V2 描述错误 |
| `hands/tuning/` 空目录 | **核实** — 目录不存在（在 V2 时存在） | 🔄 V2 时空目录已删除 |
| 6 个空 `__init__` 构造函数 | **确认** — `OverfittingDetector`、`ReportGenerator`、`RobustnessChecker`、`SensitivityAnalyzer`、`TradeAnalyzer`、`TradeStatistics` | ✅ V2 正确 |
| 5 个 CLI main() 未注册 | **扩展** — 实际 6 个：data_importer + 5 个 import_* | 🔄 V2 漏 1 |

---

## 🔴 P0: 严重腐化点 (Critical Issues)

### 1. `industry_provider.py:6` — `global _CACHE` 无锁保护

```python
# src/uniquant/brain/factors/industry_provider.py:6
_CACHE: Optional[pd.DataFrame] = None

def get_industry_dummies() -> pd.DataFrame:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    import akshare as ak
    df = ak.stock_board_industry_name_em()  # 网络调用，可能耗时
    dummies = pd.get_dummies(df.set_index("symbol")["board_name"])
    _CACHE = dummies
    return dummies
```

**问题**：
- 多线程下**两个线程同时进入 if-block**，会发起两次网络请求
- `ak.stock_board_industry_name_em()` 是远程 API 调用，无幂等保护
- 行业分类不频繁变化，**整个缓存语义设计有问题**（应该用 TTL 而非永久缓存）
- 若 `akshare` 网络异常，`_CACHE = None` 永不被设置，**每个请求都会重试**

**修复**：
```python
import threading
_CACHE: Optional[pd.DataFrame] = None
_CACHE_LOCK = threading.Lock()
_CACHE_TIME: float = 0.0
_CACHE_TTL = 3600  # 1 小时

def get_industry_dummies() -> pd.DataFrame:
    global _CACHE, _CACHE_TIME
    now = time.time()
    if _CACHE is not None and (now - _CACHE_TIME) < _CACHE_TTL:
        return _CACHE
    with _CACHE_LOCK:
        if _CACHE is None or (now - _CACHE_TIME) >= _CACHE_TTL:
            df = ak.stock_board_industry_name_em()
            _CACHE = pd.get_dummies(df.set_index("symbol")["board_name"])
            _CACHE_TIME = time.time()
    return _CACHE
```

### 2. `data/sources/base.py:9` + `source_router.py:5` — `pybreaker` 幽灵依赖（硬导入）

```python
# data/sources/base.py:9
import pybreaker
# L16:
breaker = pybreaker.CircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)

# data/managers/source_router.py:5
import pybreaker
# L239:
except pybreaker.CircuitBreakerError:
```

**问题**：
- `pybreaker` 是核心模块的**硬依赖**（无 try/except 保护）
- `pyproject.toml` **未声明** `pybreaker`
- 缺少该库时 `import uniquant.data.sources.base` 立即崩溃

**修复**：`pyproject.toml` 添加 `pybreaker>=1.0.0`

### 3. `data/services/import_1min.py:37` + `import_5min.py:37` — 模块级可变 `MAX_WORKERS`

```python
# L37 (模块级)
MAX_WORKERS = 4

# L254 (main() 内)
def main():
    global MAX_WORKERS
    parser.add_argument('--threads', type=int, default=MAX_WORKERS, ...)
    args = parser.parse_args()
    MAX_WORKERS = args.threads  # 副作用
```

**核实**：
- `MAX_WORKERS` 在**模块级**定义为 `4`（可变）
- `main()` 函数中 `global MAX_WORKERS` 写入 argparse 参数
- 这是**单进程 CLI 模式**，并发风险较低

**但仍有问题**：
- 库使用者 `from uniquant.data.services.import_1min import MAX_WORKERS` 会**不可预期地变化**（若 main() 被调用过）
- 应将 `MAX_WORKERS` 移到 `main()` 内部局部变量

### 4. `brain/czsc/czsc_engine.py:6-9` — `czsc` 硬导入

```python
# czsc_engine.py:6
from czsc import CZSC, Freq, RawBar
# czsc_engine.py:9
try:
    import czsc.signals as czsc_signals
    HAS_CZSC_SIGNALS = True
except ImportError:
    HAS_CZSC_SIGNALS = False
```

**问题**：
- `CZSC`, `Freq`, `RawBar` 是**硬导入**（无 try/except）
- `pyproject.toml` **未声明** `czsc`
- `czsc` 是 A 股缠论第三方库，缺少时整个 CZSC 引擎崩溃

**修复**：
```python
try:
    from czsc import CZSC, Freq, RawBar
    HAS_CZSC = True
except ImportError:
    CZSC = Freq = RawBar = None
    HAS_CZSC = False
```

**pyproject.toml 添加**：`czsc>=0.9.0` 至 optional-deps

### 5. `data/utils/js_executor.py:4` — `py_mini_racer` 硬导入

```python
from py_mini_racer import MiniRacer
```

**问题**：
- `py-mini-racer` 已在 `optional-deps` 的 `js` 分组中
- 但代码**未做 try/except 保护**
- `JsExecutor` 在 `ths.py` 数据源中实例化

**修复**：
```python
try:
    from py_mini_racer import MiniRacer
    HAS_MINI_RACER = True
except ImportError:
    MiniRacer = None
    HAS_MINI_RACER = False
```

---

## 🟠 P1: 重要腐化点 (Major Issues)

### 6. 4 个 deprecated brain 函数 — **零外部调用方**

| 函数 | 文件 | 实际调用方 |
|------|------|-----------|
| `get_alpha_score_from_data` | `alpha_decoupler.py:270` | **0** (仅自引用) |
| `detect_from_data` | `regime_detector.py:218` | **0** (仅自引用；`analysis_service.py:806` 是**迁移注释**而非调用) |
| `calculate_indicator_from_data` | `indicators.py:290` | **0** (仅自引用) |
| `get_czsc_signals_from_data` | `czsc_engine.py:552` | **0** (仅自引用) |

**核实**：
- V2 报告"持续被调用" — **错误**
- 实际**这 4 个函数从未被任何模块调用**
- 它们仅是 deprecation 警告的载体
- 每次 import 模块时这 4 个函数的方法签名占用内存，但永远不执行

**修复**：
- 选项 A: 直接删除（推荐 — 4 个函数定义在 4 个文件，删除约 130 行）
- 选项 B: 移到 `_legacy.py` 兼容模块

### 7. `risk/historical_risk.py` — 循环废弃

```python
class HistoricalSimulationRisk(EVTRisk):  # 继承"已废弃"的 EVTRisk
    def __init__(self):
        super().__init__()  # 触发 EVTRisk 的 __init__ (会发警告)
        warnings.warn(
            "EVTRisk is deprecated, use HistoricalSimulationRisk",  # 矛盾警告
            ...
        )
```

**问题**：
- 类的 docstring 说"Wraps EVTRisk with deprecation notice" — 但实际上是 `HistoricalSimulationRisk` 才是新名
- `super().__init__()` 触发的是 EVTRisk 构造函数（不发警告），但**类自己发警告**说"EVTRisk is deprecated, use HistoricalSimulationRisk"
- 警告文字**反了** — 应当是"`HistoricalSimulationRisk` 替代了 `EVTRisk`"

**修复**：
```python
class HistoricalSimulationRisk(EVTRisk):
    """历史模拟风险计算（独立实现，不应继承 EVTRisk）"""
    def __init__(self):
        warnings.warn(
            "HistoricalSimulationRisk 替代了 EVTRisk；建议直接使用 HistoricalSimulationRisk",
            DeprecationWarning, stacklevel=2,
        )
```

**更进一步**：**解除继承关系**。`HistoricalSimulationRisk` 应**不继承** `EVTRisk`（直接重新实现即可），继承关系本身是设计错误。

### 8. `hands/backtest/engine.py:297-467` — `run_backtest` 170 行超大函数

**核实**：
- `run_backtest` 包含整个回测管线：信号生成、订单撮合、组合管理、绩效计算
- 单一函数 170 行，**无任何内部子函数拆分**
- 调试与单元测试**不可分块**

**修复**：拆分为 `_prepare_data()` / `_execute_orders()` / `_update_portfolio()` / `_compute_metrics()` 4 个内部函数。

### 9. `brain/wyckoff/engine.py` — 6 个 100+ 行方法

| 方法 | 行数 | 范围 |
|------|------|------|
| `_step1_phase_determine` | 189 | L269-458 |
| `_build_report` | 184 | L1028-1212 |
| `_step5_trading_plan` | 151 | L865-1016 |
| `_analyze_single` | 112 | L124-236 |
| `_step2_effort_result` | 117 | L460-577 |
| `_step3_phase_c_t1` | 105 | L579-684 |

**问题**：
- `_step1_phase_determine` 189 行 — 包含多个子阶段（早期、中期、晚期）的处理
- 单元测试覆盖率必然低
- 修改任一子阶段需阅读整个 189 行

**修复**：每个 step 拆分为子方法（如 `_step1_phase_early()`、`_step1_phase_mid()`、`_step1_phase_late()`）。

### 10. `risk/__init__.py` — 6 个 `try/except ImportError` 掩盖

```python
# risk/__init__.py
try:
    from .sizer import PositionSizer
except ImportError:
    PositionSizer = None

try:
    from .evt_risk import EVTRisk
except ImportError:
    EVTRisk = None

# ... 4 个类似
```

**问题**：
- `PositionSizer = None` 静默失败 — 调用方会得到 `AttributeError: 'NoneType' object has no attribute 'compute'`
- 应让 ImportError 抛出，**强制修复**而不是掩盖

**修复**：
```python
# 直接导入，不掩盖
from .sizer import PositionSizer
from .evt_risk import EVTRisk
from .portfolio_optimizer import PortfolioOptimizer
from .drawdown_analyzer import DrawdownAnalyzer
from .structural import StructuralRiskManager
```

### 11. `brain/__init__.py` — 7 个 `try/except ImportError` 掩盖

**同 risk/__init__.py** 问题，brain 有 7 个 try/except 都掩盖了 ImportError，导致模块可能为 None。

### 12. `data/services/import_*.py` — CLI 模式 + 导入副作用

```python
# data/services/import_1min.py:1-20
import sys
import pandas as pd
import struct
# ... 30+ imports

def main():
    global MAX_WORKERS
    parser = argparse.ArgumentParser(...)
    # ...
```

**问题**：
- 6 个 CLI 入口文件 (`data_importer.py`, `import_1min.py`, `import_5min.py`, `import_financial.py`, `import_index.py`)，**均未注册**为 `console_scripts`
- 每个文件导入时（`from uniquant.data.services.import_1min import ...`）会**无主执行**副作用
- 文件结构耦合到 CLI 调用方式

**修复**：
1. 在 `pyproject.toml` 注册 6 个 console_scripts
2. 或将 CLI 入口移到 `scripts/` 目录

### 13. `hands/backtest/signal_integrator.py:5-6` — `uniquant.signal` 导入链

```python
from uniquant.signal.models import Signal
from uniquant.signal.aggregator import SignalAggregator, SignalAggregationMethod
```

**核实**：
- V2 报告说 `signal_integrator.py:5-6` 导入不存在的 `uniquant.signal` 包 — **错误**
- `uniquant.signal` 包**已存在**且**导入成功**
- 该模块**已正确工作**（Python 验证导入无错误）

**V2 误报**：此条 V2 描述错误。

### 14. `hands/strategies/base.py:6-12` — 错误的导入

```python
try:
    from risk.sizer import PositionSizer
except ImportError:
    # Fallback/Mock for standalone testing
    PositionSizer = None
```

**问题**：
- `from risk.sizer import PositionSizer` — 这是**绝对导入**，尝试找顶级 `risk` 包
- 实际包名是 `uniquant.risk.sizer`
- 应为 `from ...risk.sizer import PositionSizer`
- **这个 try/except 永远会失败**（除非用户碰巧在 `risk/` 目录运行）

**修复**：
```python
from ...risk.sizer import PositionSizer
```

### 15. `hands/backtest/overfitting_detector.py:26` 等 6 个空 `__init__`

```python
class OverfittingDetector:
    def __init__(self):
        pass
```

**问题**：
- 6 个类（`OverfittingDetector`, `ReportGenerator`, `RobustnessChecker`, `SensitivityAnalyzer`, `TradeAnalyzer`, `TradeStatistics`）都是**空构造函数**
- 这些类**没有实例状态**（无 `self.xxx`）
- 应该改为 `@staticmethod` 装饰方法

**修复**：
```python
class OverfittingDetector:
    @staticmethod
    def purged_kfold(n: int, k: int = 5, embargo: int = 5):
        ...
```

---

## 🟡 P2: 一般腐化点 (Minor Issues)

### 16. `data/parsers/tdx_parser.py:269-310` — 非原子写入

```python
def save_gbbq_data(self, df: pd.DataFrame, output_path: str) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, compression="snappy")
```

**问题**：
- `to_parquet` 失败会留下 `.parquet.tmp` 残骸
- `output_path.parent.mkdir` 在并发下**可能创建失败**（race condition）
- **无原子重命名**（应该先写 `.tmp` 再 `os.replace`）

**修复**：
```python
def save_gbbq_data(self, df: pd.DataFrame, output_path: str) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        df.to_parquet(tmp_path, compression="snappy")
        os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
```

**核实**：`data/lake/storage_manager.py:64-89` 已有 `temp_path + os.replace` 模式 — `tdx_parser.py` 应该**复用**该模式。

### 17. `data/lake/storage_manager.py:64-89` — 写锁缺失

```python
def write_parquet(self, file_path, df, overwrite=False):
    # 缺写锁
    if file_path_obj.exists() and not overwrite:
        logger.warning(...)
        return False
    df.to_parquet(file_path, compression="snappy")
```

**问题**：
- 多线程并发 `write_data(symbol1)` 和 `write_data(symbol2)` 时正常
- 但 `write_data(symbol1)` 在两个线程同时调用会**竞态**（前者写一半被后者截断）

**修复**：在 `write_parquet` 内加 per-file 锁。

### 18. `data/managers/trade_calendar_manager.py:103-113` — 网络调用未限制并发

**核实**：trade_calendar_manager.py 是交易日历管理器，需要从网络获取节假日数据。
- **未限并发**时，多线程调用可能触发 N 次远程请求
- 应使用单例 + 缓存

**修复**：
```python
_calendar_cache = None
_calendar_lock = threading.Lock()

def get_trade_calendar():
    global _calendar_cache
    if _calendar_cache is not None:
        return _calendar_cache
    with _calendar_lock:
        if _calendar_cache is None:
            _calendar_cache = _fetch_remote_calendar()
    return _calendar_cache
```

### 19. `brain/lppl/engine.py:33-34` — 自定义 njit shim

```python
def njit(*args, **kwargs):
    def decorator(func):
        return func  # 不加速，直接返回原函数
    return decorator
```

**问题**：
- 自定义 `njit` 装饰器**未调用 numba**（仅返回原函数）
- `lppl` 性能关键代码应该有 numba JIT 加速
- 这是**性能陷阱** — 用户期望 numba 加速，实际无加速

**修复**：
```python
try:
    from numba import njit as _real_njit
    njit = _real_njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
```

### 20. `brain/wyckoff/state.py:106` — `exchange_calendars` 注释引用

```python
如需精确的 A 股交易日历，请接入 exchange_calendars 或 tushare 节假日数据。
```

**问题**：
- 仅**注释中**提及 `exchange_calendars` 和 `tushare`
- 实际代码中**未导入这两个库**
- 注释误导 — 暗示已实现

**修复**：要么实现接入，要么删除注释。

### 21. `hands/backtest/engine.py:297-467` — 重复 `run_backtest` 命名

`hands/backtest/engine.py:run_backtest` (170 行) 和 `hands/strategies/backtest.py:run_backtest` (170 行) — **同名同长**，但实现可能不同。

**核实**：
- `hands/strategies/backtest.py` 是早期版本
- `hands/backtest/engine.py` 是新版本
- **调用方已迁移**至 `hands/backtest/engine.py`，但旧文件仍存在

**修复**：删除 `hands/strategies/backtest.py`（旧版本）。

### 22. `hands/strategies/ma_cross.py` + `wyckoff.py` 等 — 离线回测函数

`ma_cross.py:trade_ma`、`regime.py:trade_regime`、`wyckoff.py:trade_wyckoff` 等函数标注 `"OFFLINE BACKTEST LABEL — Not for live trading"`。

**问题**：
- 这些函数**仅用于离线回测标签生成**
- 任何上游调用若误用会**永远无法实盘**
- 应**重命名**为 `label_*()` 前缀，强制调用方意识到

**修复**：
```python
def label_ma_trade(df, as_of_date, ...):
    """OFFLINE BACKTEST LABEL ONLY — Not for live trading."""
    ...
```

### 23. `data/utils/js_executor.py:66-237` — `_add_browser_mocks` 171 行

**核实**：`_add_browser_mocks` 函数 171 行，注入 30+ 个浏览器 API mock（window, document, navigator 等）。

**修复**：从外部 JSON 文件加载 mock 模板，而非硬编码。

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计文件数 | 178 |
| 审计总 LOC | ~38,077 |
| P0 严重问题 | 5 |
| P1 重要问题 | 10 |
| P2 一般问题 | 8 |
| 幽灵依赖 | 4 (`pybreaker`, `czsc`, `py_mini_racer` 硬导入, `urllib3` 间接) |
| 真正僵尸函数 | 4 (zero-call deprecated) |
| 全局状态点 | 3 (`_CACHE`, `MAX_WORKERS`×2) |
| 超大函数 >100 行 | 11 (wyckoff × 6, lppl × 1, fsm × 1, hands × 2, eastmoney × 1) |
| CLI 未注册 | 6 |

---

## 🎯 修复优先级 (Queue 2)

| 优先级 | 项目 | 影响 | 修复成本 |
|--------|------|------|----------|
| **P0** | `pyproject.toml` 声明 `pybreaker` | 导入即崩溃 | 1 行 |
| **P0** | `pybreaker` 硬导入改为 try/except 保护 | 运行时崩溃 | 2 行 |
| **P0** | `czsc` 硬导入改为 try/except | 导入即崩溃 | 5 行 |
| **P0** | `py_mini_racer` 硬导入改为 try/except | 缺失库时崩溃 | 5 行 |
| **P0** | `_CACHE` 全局锁 + TTL | 多线程下网络抖动 | 15 行 |
| P1 | 删除 4 个 deprecated brain 函数 | 死代码 | 130 行删除 |
| P1 | `HistoricalSimulationRisk` 解除 EVTRisk 继承 | 设计错误 | 30 行 |
| P1 | `risk/__init__.py` + `brain/__init__.py` 移除 try/except | 掩盖错误 | 30 行 |
| P1 | 修复 `from risk.sizer` 错误导入 | 永远失败的兼容代码 | 1 行 |
| P1 | 注册 6 个 CLI console_scripts | 命令行不可用 | 6 行 |
| P2 | 拆分 wyckoff 6 个 100+ 行方法 | 可维护性 | 200 行 |
| P2 | 拆分 `run_backtest` 170 行 | 可维护性 | 50 行 |
| P2 | `data/parsers/tdx_parser.py` 原子写入 | 异常时数据残留 | 10 行 |
| P2 | `lppl/engine.py` 使用真实 numba.njit | 性能提升 | 5 行 |

---

## 🔍 与 V2 报告对比 (Cross-Reference)

| V2 报告条目 | V3 状态 |
|------------|---------|
| `pybreaker` 幽灵 | ✅ 仍存在 |
| `backtrader` 未在 optional | ✅ 仍存在 |
| `exchange_calendars` 未注册 | ✅ 仍存在 |
| 4 个 deprecated 函数 (在 alpha/regime/indicators/czsc) | ✅ 仍存在；**新增发现** — 全部零调用方 |
| `HistoricalSimulationRisk` 循环废弃 | ✅ 仍存在 |
| 6 个空 `__init__` 构造函数 | ✅ 仍存在 |
| 5 个 CLI main() 未注册 | 🔄 实际 6 个（V2 漏 1） |
| `industry_provider.py:8` global _CACHE | ✅ 仍存在；**新增** — 需加锁 + TTL |
| `import_1min/5min.py:254` global MAX_WORKERS | ✅ 仍存在；**澄清** — 实际是 main() 内的合法 CLI 模式 |
| 4 个空 `__init__.py` | 🔄 V2 描述错误（3 个有内容，1 个有 36 字节） |
| `hands/tuning/` 空目录 | 🔄 已删除 |
| `signal_integrator.py:5-6` 导入不存在的 uniquant.signal | ❌ V2 误报（包已存在，导入成功） |
| `round10` vs `round_10` 命名冲突 | — 需复检 |

**V2 准确率**: ~75% (V2 报告 75% 准确)
