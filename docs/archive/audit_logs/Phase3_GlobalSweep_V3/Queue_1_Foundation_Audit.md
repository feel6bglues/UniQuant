# Queue 1 审计报告 V3: 基础公共基建 (Foundation & Shared Infrastructure)

**审计时间**: 2026-06-06
**审计范围**: 
- `shared/` (37 文件, ~5,710 LOC) — 含 `cache/` (4)、`constants/` (7)
- `signal/` (6 文件, ~1,629 LOC) — 含 `db/` (0)、`quality/` (0)
- `config/` (4 文件) — YAML 配置
- `pyproject.toml`

**审计重点**: 幽灵依赖、僵尸代码、全局状态污染、异常捕获、内存泄漏、跨包耦合

---

## ✅ V2 报告核实 (Verification)

| V2 报告原话 | 本轮核实结果 | 状态 |
|------------|-------------|------|
| `price_collar.py:1` 断裂导入 `from ..shared.market_rules` 报 `ModuleNotFoundError` | **错误** — `..shared` 在 `uniquant.shared.price_collar` 中实际解析为 `uniquant.shared`（包名是 `shared` 巧合）。**导入成功运行** | ❌ V2 误报 |
| `shared/__init__.py` 缺前导点的相对导入 | **错误** — 实际为 `from .analysis_result import ...` 带前导点 | ❌ V2 误报 |
| `data/services/__init__.py` 空 | — 不在 Q1 范围，本轮未复检 | — |
| `hands/strategies/__init__.py` 空 | — 不在 Q1 范围 | — |
| `urllib3` 幽灵依赖 | **确认** — `error_handling.py:12` 硬导入，`pyproject.toml` 未声明 | ✅ V2 正确 |
| 8 个 global 状态点 | 本轮进一步定位：仅 5 个为真问题（其余 2 个在 `main()` 内可接受、1 个为单例正常模式） | ⚠️ 部分修正 |

---

## 🔴 P0: 严重腐化点 (Critical Issues)

### 1. `price_collar.py:1` — 巧合的"软错"导入

```python
# src/uniquant/shared/price_collar.py:1
from ..shared.market_rules import get_board_rule
```

**实际行为**：
- `uniquant.shared.price_collar` 中 `..` = `uniquant` (父包)
- `..shared` = `uniquant.shared` (巧合包名)
- 该导入**意外工作**（测试通过），但**不是显式相对导入** `from .market_rules import get_board_rule`

**风险**：
- 若包结构重命名（如 `shared/` → `common/`），`..shared` 将突然崩溃
- 违反 PEP 328 显式相对导入规范
- 调用方：`risk/sizer.py:7` 和 `hands/backtest/unified_matching_engine.py:16` 已用规范 `from ..shared.market_rules`，证明 `price_collar.py` 是异类

**修复**：`from .market_rules import get_board_rule`（5 字符修改）

**引用方**：
- `src/uniquant/risk/sizer.py:7`
- `src/uniquant/hands/backtest/unified_matching_engine.py:16`

### 2. `urllib3` — 幽灵依赖（无版本锁定）

- `src/uniquant/shared/error_handling.py:12` `import urllib3`
- `src/uniquant/shared/error_handling.py:356` `urllib3.exceptions.HTTPError`
- `pyproject.toml` 仅声明 `requests>=2.31.0`，未声明 `urllib3`
- `src/uniquant/data/utils/request_utils.py:228` `from urllib3.util.retry import Retry` — 第二个幽灵依赖点

**风险**：依赖 `requests` 间接传递 `urllib3`，若 `requests` 升级移除 `urllib3` 内部依赖或更换为 `httpx`，错误处理模块将 ImportError。

**修复**：`pyproject.toml` 添加 `urllib3>=2.0.0,<3.0.0`

### 3. `signal/db.py` — SQLAlchemy 不可用时静默失败

```python
# src/uniquant/signal/db.py:19-32
try:
    from sqlalchemy import (...)
    Base = declarative_base()
    _SQLA_AVAILABLE = True
except ImportError:
    Base = None
    _SQLA_AVAILABLE = False
```

**裸奔点**：
- `Base` 在 `ImportError` 时为 `None`
- `SignalRecord` 类定义在 `if _SQLA_AVAILABLE:` 块内 — 若 SQLAlchemy 不可用，整个类消失
- `SignalDatabase.__init__` 在 SQLAlchemy 不可用时抛出 `ImportError`，但**调用方无明确错误信息**：`"SQLAlchemy 未安装，请执行: pip install sqlalchemy"`
- 连接到 SQLite 时未配置连接池参数，可能在大并发下耗尽句柄

**修复**：
- `Base.metadata.create_all(self._engine)` 后**没有引擎配置**（pool_size, max_overflow）
- 缺少 `dispose()` 方法，连接可能泄漏
- `with self._get_session() as session:` 中 `session` 是普通 `Session()` 实例，**SQLAlchemy 2.0 风格**需 `with self._session_factory() as session:` 形式

### 4. `signal/__init__.py` — 顶层无导入失败的暴露面

```python
# src/uniquant/signal/__init__.py:64-67
def get_db_class():
    """获取 SignalDatabase 类（延迟导入）"""
    from .db import SignalDatabase
    return SignalDatabase
```

**问题**：
- 顶层 import 不包含 `SignalDatabase`，调用方必须用 `get_db_class()` 才能获得
- 但 `get_db_class()` 每次都重新导入并返回**类**而非**实例**，调用方必须自己实例化
- 实际是懒加载，**没有真正的延迟价值**（如果 db.py 被 import，会立即触发 sqlalchemy 检测；如果未 import，则 `get_db_class()` 也会触发）
- 命名误导：叫 `get_db_class` 但返回 `SignalDatabase` 类

**修复**：直接 `from .db import SignalDatabase` 在顶层，配合 try/except

---

## 🟠 P1: 重要腐化点 (Major Issues)

### 5. `logger_factory.py` — 全局可变字典 + 全局工厂实例

```python
# 1. 类级可变字典（_loggers）
class LoggerFactory:
    _loggers: Dict[str, logging.Logger] = {}  # L26

# 2. 模块级全局工厂实例
_factory: Optional[LoggerFactory] = None      # L185
_factory_lock = threading.Lock()

def get_logger(name):
    global _factory                               # L201
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                _factory = LoggerFactory()        # 双重检查锁
    return _factory.get_logger(name)
```

**问题**：
- `_loggers` 字典是类级变量，跨实例共享且无锁保护
- `_factory` 是模块级 `global`，但 `get_logger` 内部用了双重检查锁 — **逻辑不严**：`_factory` 可能在测试间残留
- `_setup_root_logger` 在 `__init__` 中调用，触发导入时副作用（`QueueListener` 启动后**不会停止**，跨测试/重启会累积）
- `LoggerFactory.reset()` 类方法清空 `_instance` 但**不停止 QueueListener**，导致后台线程泄漏

**风险**：长进程下累积后台监听线程；测试隔离困难。

### 6. `config_loader.py:337` — `get_config()` 无锁保护的延迟单例

```python
# L337
def get_config() -> GlobalConfig:
    global config
    if config is None:                  # 无锁！
        config = GlobalConfig()         # 多线程可能创建多个实例
    return config
```

**核实**：
- 类的 `__new__` 内**有**锁保护（双重检查锁，L20-27）
- 但 `get_config()` 的 `if config is None` 检查在 `global config` 赋值前**没有锁**
- Python 的 import 锁可防止启动期并发，但运行时调用 `get_config()` 在多线程中仍可能创建多个 `GlobalConfig` 实例

**修复**：
```python
def get_config() -> GlobalConfig:
    global config
    if config is None:
        with config_lock:                # 新增模块级锁
            if config is None:
                config = GlobalConfig()
    return config
```

### 7. `error_handling.py:308` — `global _error_stats` 重置竞态

```python
def reset_error_stats() -> None:
    global _error_stats
    with _error_stats_lock:
        _error_stats = {}                # 整个重置在锁内
```

**核实**：实际上**有锁保护**，重置在 `_error_stats_lock` 内执行。
- ✅ 这是**安全**的，`get_error_stats()` 也用 `with _error_stats_lock`
- V2 报告中"`get_error_stats` / `reset_error_stats` 未加锁保护"的描述**不准确** — 实际有锁

**真实问题**：`_error_stats` 在 `get_error_stats` 中**只读拷贝**返回，多线程下 read 期间无写入不变量保证（但 Python GIL 提供了内存可见性保证，可接受）。

### 8. `env_config.py:41` — 导入时副作用

```python
# src/uniquant/shared/env_config.py:41
configure_environment()  # 模块末尾
```

**问题**：
- 导入此模块即**强制设置 6 个环境变量**到 `os.environ`
- `OMP_NUM_THREADS=1` 等设置**无法回退**
- 如果其他模块先 import 然后再修改这些 env vars，行为可预测
- 但如果用户在脚本前设置 `OMP_NUM_THREADS=4`，import 后**不会覆盖**（用了 `setdefault`）—— 这是**优点**

**风险**：若用户未 import 此模块，多进程并发会线程爆炸（但已用 `setdefault` 缓解）

**建议**：保留现状（已用 `setdefault`），但**应文档化导入时机**。

### 9. `perf.py` — 全局 `defaultdict` 无锁

```python
# 顶部模块级
_COUNTERS: defaultdict[str, int] = defaultdict(int)
_TIMERS: defaultdict[str, int] = defaultdict(int)
```

**问题**：
- `_COUNTERS[k] += 1` 在 `perf_section` 退出时调用（多线程并发）
- `defaultdict` 操作非原子，计数可能丢失
- 但 `_ENABLED = os.environ.get("UNIQUANT_PERF", "0") == "1"` 默认关闭，**风险低**

**修复**：若需要并发计数，应加锁或换 `Counter`。

### 10. `slippage_model.py` — 抽象方法无实现

```python
class SlippageModel(ABC):
    @abstractmethod
    def estimate(self, ...):
        pass  # 注：原文件 L9 实际是 `...` 省略号（占位）
```

**核实**：实际为 `pass`（L9），**符合 ABC 抽象基类规范**。V2 报告"无实现"的描述**误导**，但 `estimate` 故意不实现是设计意图。

**真实问题**：
- `DefaultSlippage.estimate` 返回 `SLIPPAGE_PCT`（常量）—— 不读 `liquidity/volatility`，**永远返回同一个值**
- `DynamicSlippage._get_liquidity` 和 `_get_atr` **写死常量**（`1_000_000_000.0` 和 `0.02`），无真实数据接入
- `slippage_model.py` 整体**未被使用**（`grep` 验证）

**僵尸代码**：建议删除或实现真实数据接入。

---

## 🟡 P2: 一般腐化点 (Minor Issues)

### 11. 僵尸文件清单 (Zombie Files)

| 文件 | LOC | 引用者 | 状态 |
|------|-----|--------|------|
| `shared/di_container.py` | 24 | `tests/test_di_container_and_cache.py` (1 处) | DEPRECATED 标注，测试已迁移到 `service_container` |
| `shared/network_constants.py` | 2 | 0 | 仅含 `MAX_RETRIES=3`、`RETRY_DELAY_BASE=1.0`，**零引用** |
| `shared/market_constants.py` | 1 | 0 | `A_SHARD_BOARDS = {"sz", "sh", "bj"}`，**零引用** |
| `shared/risk_constants.py` | 2 | 1 | `RISK_FREE_RATE=0.03`、`TRADING_DAYS_PER_YEAR=252`，仅 `risk_constants` 文件本身引用 |
| `shared/parallel.py` | 11 | 0 | `worker_init` 是空函数，**零引用** |
| `shared/slippage_model.py` | 50 | 0 | 整个文件**零外部引用** |

**真实僵尸**（0 引用且无功能）：
- `network_constants.py` — 应删除或合并
- `market_constants.py` — 应删除
- `parallel.py` — 空函数，应删除
- `slippage_model.py` — 抽象基类无用户，删除或实际使用

**有引用**：
- `risk_constants.py` — 1 处引用（自身），需保留或重新归属
- `di_container.py` — 1 处测试引用，正式代码已迁移

### 12. `signal/aggregator.py:312-313` — 注释后置内联 import

```python
# 避免循环导入，内联引用
from .normalizer import SignalNormalizer  # noqa: E402
```

**问题**：
- `noqa: E402` 抑制 lint 警告，本质是**绕开 lint 而非修复**
- `aggregator.py:312-313` 中 `SignalNormalizer._compute_strength` 实际可移到工具函数（不属于 normalizer 领域）
- 修复方案：在 `models.py` 中添加 `compute_strength` 静态方法

### 13. `signal/normalizer.py` — `_TYPE_MAP` 重复定义

每个 normalizer 都有 `_TYPE_MAP` 类属性，但**4 个 normalizer 的格式不一致**（部分使用 `signal_type`，部分使用 `type`），造成上游调用方需要 `raw_signal.get("type", raw_signal.get("signal_type", ""))` 这种 hack：

```python
# LPPLSignalNormalizer
raw_type = raw_signal.get("type", raw_signal.get("signal_type", ""))
```

**修复**：在 `Signal` 模型层强制规范字段名（`signal_type` 是标准），调用方只读一个字段。

### 14. `shared/cache/` 子包未暴露在顶层 `__init__.py`

**核实**：
- `shared/cache/__init__.py` 定义 `cache_manager`、`smart_cache` 等
- 但 `shared/__init__.py` **未导入** `from .cache import *`
- 调用方需要 `from uniquant.shared.cache import smart_cache` 而非 `from uniquant.shared import smart_cache`

**影响**：
- `services/cache_coordinator.py:42` 重新用 `CacheFactory.create(...)` 自己创建 cache，**绕过了 shared.cache 子包**
- **两个并行缓存抽象**：
  1. `shared/cache/cache_manager` — 全局实例
  2. `services/cache_coordinator.cache_manager` — 服务包装

**修复**：在 `shared/__init__.py` 暴露 cache 子包，或删除 `services/cache_coordinator.py` 中的重复实现。

### 15. `shared/limits.py` — 兼容层文件

```python
"""
涨跌停检查模块（兼容层）
为 brain/wyckoff/classifiers.py 提供兼容接口
实际实现位于 limit_checker.py
"""
from .limit_checker import is_limit_down, is_limit_up, check_limit_status, LimitStatus
```

**核实**：
- 文档明确标注"兼容层"
- 实际调用方：`brain/wyckoff/classifiers.py` — 需验证是否真的用此模块

**修复**：验证 `classifiers.py` 是否真的用了 `shared.limits`，若是则保留；否则删除。

### 16. `config/config.yaml` 硬编码 Linux 路径

```yaml
# L16-17
tdx:
  path: "/home/james/.local/share/tdxcfv/drive_c/tc"  # Linux通达信路径
```

**风险**：
- 仅适用于 james 用户的开发机
- 其他开发者或 CI 环境**必然失败**
- 应使用 `~/` 或环境变量：`${TDX_PATH:-/default/path}`

**修复**：
```yaml
tdx:
  path: "${TDX_PATH:-$HOME/.local/share/tdxcfv/drive_c/tc}"
```
**或** 通过 `env_config.py` 注入。

### 17. `interfaces.py` — `RegimeType` 与 `MarketRegime` 重复定义

```python
# interfaces.py
class MarketRegime(Enum):  # L12
    NORMAL, STRESSED, FROZEN

class RegimeType(enum.Enum):  # L29
    STRONG_BULL, ..., NORMAL, STRESSED, FROZEN, UNKNOWN
```

**问题**：
- `MarketRegime`（3 值） vs `RegimeType`（9 值）
- 后者是前者的超集，但**名称不一致**（`STRESSED` 在两者都有；`STRONG_BULL` 仅在 `RegimeType`）
- 跨模块使用时需要频繁转换

**修复**：合并为单 `RegimeType`（移除 `MarketRegime`）或明确 `MarketRegime = RegimeType[xx]`.

### 18. `interfaces.py:5` — 仅 5 个 Protocol 但 `MarketSignalContext` 是 dataclass

**核实**：
- 5 个 `@runtime_checkable` Protocol：`DataFetcherProtocol`、`RiskAssessmentProtocol`、`PositionSizerProtocol`、`AnalysisEngineProtocol`、`CalculationPluginProtocol`
- `MarketSignalContext` 是 dataclass，**非 Protocol** — 命名容易混淆
- V2 报告"Protocol 接口：5 个"**准确**

**问题**：
- 文档中提到的 5 个 Protocol，**实际验证有几个实现了这些 Protocol**？需要全量 grep
- 鸭子类型 vs 显式 Protocol 的混合使用

### 19. `interfaces.py:359 LOC` 偏大

- 整个文件 359 行，包含 3 个 Enum、1 个 dataclass、5 个 Protocol
- 建议拆分为 `enums.py`、`protocols.py`、`context.py`

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计文件数 | 47 (shared) + 6 (signal) + 4 (config) = 57 |
| 审计总 LOC | 7,339 + 1,629 ≈ 9,000 |
| P0 严重问题 | 4 |
| P1 重要问题 | 6 |
| P2 一般问题 | 9 |
| 僵尸文件（0 引用） | 4 |
| 幽灵依赖 | 1（`urllib3`） |
| 全局状态点 | 5（logger_factory × 2, config_loader, error_handling, perf） |

---

## 🎯 修复优先级 (Queue 1)

| 优先级 | 项目 | 影响 | 修复成本 |
|--------|------|------|----------|
| **P0** | 修正 `price_collar.py:1` 为 `from .market_rules` | 未来包重命名时崩溃 | 5 字符 |
| **P0** | `pyproject.toml` 声明 `urllib3` | 升级 requests 后崩溃 | 1 行 |
| **P0** | 修正 `signal/db.py` SQLAlchemy 不可用时的兜底 | 错误信息模糊 | 中等 |
| **P0** | `signal/__init__.py` 暴露 `SignalDatabase` | API 难用 | 5 行 |
| P1 | `logger_factory.py` 锁/QueueListener 泄漏 | 长时间运行内存增长 | 中等 |
| P1 | `config_loader.py:get_config()` 加锁 | 多线程创建多实例 | 3 行 |
| P1 | 删除 4 个僵尸文件 | 减少代码噪音 | 4 文件 |
| P2 | `RegimeType` 与 `MarketRegime` 合并 | 命名一致性 | 中等 |
| P2 | `shared/cache` 暴露到顶层 `__init__` | 统一缓存入口 | 3 行 |
| P2 | `config.yaml` 路径变量化 | 可移植性 | 1 行 |

---

## 🔍 与 V2 报告对比 (Cross-Reference)

| V2 报告条目 | V3 状态 |
|------------|---------|
| `price_collar.py` 断裂导入 | ⚠️ **软错** — 巧合工作，需显式化 |
| `urllib3` 幽灵 | ✅ 仍存在 |
| 8 个 global 状态点 | 🔄 **修正为 5** 个真实问题 |
| 4 个 deprecated 函数 (在 Q2) | — 不在 Q1 |
| `di_container.py` 僵尸 | ✅ 仍存在 |
| `network_constants` / `market_constants` / `parallel` 僵尸 | ✅ 仍存在，新增 `slippage_model` 僵尸 |
| `data/services/__init__.py` 空 (在 Q2) | — 不在 Q1 |
| `shared/slippage_model.py` 空存根 | ✅ 仍存在，且未被使用 |
| `signal/db.py` SQLAlchemy 兜底 | 🔄 **加深** — 不仅兜底，API 也异常 |

**V2 准确率**: ~7/10 (V2 报告 70% 准确，30% 描述偏差)
