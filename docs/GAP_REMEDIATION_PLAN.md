# 遗留缺口修复计划 (Phase 6)

> 基于 Phase 0-5 完成审计后识别的 4 个遗留缺口。
> 报告日期: 2026-06-11 | 当前测试: 1,085 passed, 0 failed
>
> **2026-06-12 状态更新**：G-1 到 G-4 全部关闭，已验证。本节（§G-1 到 §执行进展前）为历史原始计划，保留供追溯。实际完成状态见下方 §执行进展（已更新测试计数为 1159）。完整关闭证据见 `docs/analysis/institutional/17_institutional_closure_review_report.md` §Phase 6 Gap Review。

---

## 目录

- [G-1: TimeProvider 全库适配](#g-1-timeprovider-全库适配)
- [G-2: FactorRegistry 命名冲突与准入统一](#g-2-factorregistry-命名冲突与准入统一)
- [G-3: Phase 0 交付物提交](#g-3-phase-0-交付物提交)
- [G-4: Async EventBus](#g-4-async-eventbus)
- [执行计划](#执行计划)

---

## G-1: TimeProvider 全库适配

### 现状

`TimeProvider` 协议 (`shared/time_provider.py`) 已在阶段 1 中定义，提供 `now()`、`today()` 和 `timestamp()` 三个方法。但实际部署仅限于 `services/research_pipeline.py` 和 `services/service_container.py` 2 个文件。

全库共有 **~120 处**直接调用系统时钟，分布在 6 个层级：

| 层级 | datetime.now() | pd.Timestamp.now() | datetime.date.today() | time.time() (时钟依赖) | **合计** |
|---|---|---|---|---|---|
| brain/ | 6 | 4 | 0 | 1 | **11** |
| data/ | 21 | 2 | 0 | ~8 | **23** |
| hands/ | 5 | 2 | 0 | 0 | **7** |
| signal/ | 10 | 0 | 0 | 0 | **10** |
| risk/ | 0 | 0 | 0 | 0 | **0** |
| services/ | 10 | 28 | 0 | 0 | **38** |
| shared/ | 7 | 0 | 1 | 0 | **8** |
| ui/ | 8 | 0 | 0 | 2 | **10** |
| **总计** | **67** | **36** | **1** | **~16** | **~120** |

### 目标

让所有 `datetime.now()`、`pd.Timestamp.now()`、`datetime.date.today()` 以及时钟依赖的 `time.time()` 调用都通过 `TimeProvider` 接口完成，实现测试可冻结的时间环境。

### 修复方案

#### 步骤 1: 扩展 TimeProvider 协议

| 新增方法 | 签名 | 替代目标 |
|---|---|---|
| `epoch_ms()` | `() -> int` | `int(time.time() * 1000)` |
| `now_pd()` | `() -> pd.Timestamp` | `pd.Timestamp.now()` |

**文件**: `src/uniquant/shared/time_provider.py`

`FrozenTimeProvider` 实现这些方法即可控制全库时间行为。

#### 步骤 1: 扩展 TimeProvider (已完成)

- 向协议新增 `epoch() -> float` 和 `epoch_ms() -> int`
- 添加模块级 `get_time_provider()` / `set_time_provider()` 支持可切换默认提供者
- `RealTimeProvider` 和 `FrozenTimeProvider` 均实现新方法
- 文件: `src/uniquant/shared/time_provider.py`

#### 步骤 2-7: 按层级逐个适配

按依赖风险从小到大排列：

| 步骤 | 层级 | 文件数 | 调用数 | 状态 | 估算 |
|---|---|---|---|---|---|---|
| 2 | **risk/** | 0 | 0 | ✅ 已验证干净 | — |
| 3 | **shared/** | 4 | 10 | ✅ **完成** | 0.5天 |
| 4 | **hands/** | 3 | 7 | ⏳ 待做 | 0.5天 |
| 5 | **signal/** | 4 | 10 | ⏳ 待做 | 1天 |
| 6 | **brain/** | 4 | 11 | ⏳ 待做 | 1.5天 |
| 7 | **services/** | 8 | 38 | ⏳ 待做 (需 DI 线程化) | 2天 |
| 8 | **data/** | 15 | 23 | ⏳ 待做 (最大难度) | 2天 |
| 9 | **ui/** | 3 | 10 | 低 | 0.5天 |

#### 步骤 10: 验证

- 全回归测试: `pytest tests/ -q` → 0 失败
- 时间冻结测试: 用 `FrozenTimeProvider` 验证某个分析运行结果确定性强
- 基线一致: `python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py`

### 风险与缓解

| 风险 | 缓解 |
|---|---|
| `pd.Timestamp.now()` 用于 `pd.DateOffset` 运算，替换需保持 API 兼容 | 返回的 `pd.Timestamp` 与 `pd.Timestamp.now()` 行为一致 |
| `time.time()` 用于频率限制，需要 epoch 秒而非 datetime | `epoch_ms()` 提供整数毫秒时间戳 |
| 模块级常量在导入时冻结 | 改为惰性求值或函数调用 |
| 测试覆盖不足导致回归 | 每层适配后运行子集测试 |

---

## G-2: FactorRegistry 命名冲突与准入统一

### 现状

代码库中存在两个同名的 `FactorRegistry` 类:

| 版本 | 文件 | 导入数 | 功能 |
|---|---|---|---|
| **治理版** | `shared/factor_governance.py:32` | **0** (无人使用) | 有准入机制 (`check_access()`), 纯元数据 |
| **旧版 (大脑)** | `brain/factors/registry.py:28` | **16** (事实标准) | 无准入, 含 `compute_func` 可调用 |

治理版的 `check_access()` 和 `global_factor_registry` 从未被任何代码引用，准入机制完全处于休眠状态。

### 目标

消除命名冲突，将准入机制部署到实际使用的代码路径上，删除死代码。

### 推荐方案: "反向合并"

向旧版 `brain/factors/registry.py` 添加准入功能，废弃并最终删除 `shared/factor_governance.py`。

#### 步骤 1: 增强旧版 FactorRegistry

向 `brain/factors/registry.py` 中的 `FactorRegistry` 添加:

```python
class FactorAccessLevel(Enum):
    FREE = "free"
    WARN = "warn"
    BLOCK = "block"

class FactorGateConfig:
    mode: FactorAccessLevel = FactorAccessLevel.WARN

class FactorRegistry:
    # 现有代码...
    def set_mode(self, mode: FactorAccessLevel) -> None: ...
    def get_mode(self) -> FactorAccessLevel: ...
    def check_access(self, name: str) -> bool: ...
    def register(self, name, compute_func, category, weight, desc, *,
                 access_level=FactorAccessLevel.FREE, tags=None): ...
```

- `check_access(name)`: 未注册时在 WARN 模式记录日志，BLOCK 模式引发 `ValueError`
- `register()` 参数扩展: 增加 `access_level` 和 `tags`

#### 步骤 2: 替换所有导入路径

将 16 个导入点从 `uniquant.brain.factors.registry` 替换为 `uniquant.shared.factor_governance` (或创建别名转发):

```python
# 在 factor_governance.py 中:
from uniquant.brain.factors.registry import FactorRegistry as _BrainFactorRegistry
# 扩展...
```

或更简单地，直接修改 `brain/factors/registry.py` 后更新所有使用者。

#### 步骤 3: 废弃 shared/factor_governance.py

添加废弃警告并标记:

```python
import warnings
warnings.warn(
    "uniquant.shared.factor_governance is deprecated. "
    "Use uniquant.brain.factors.registry.FactorRegistry instead.",
    DeprecationWarning, stacklevel=2
)
```

#### 步骤 4: 集成到 config/feature flags

将 `config.yaml` 中的 `factor_gate` feature flag 连接到 `FactorRegistry.set_mode()`。

### 备选方案 (已排除)

| 方案 | 理由 |
|---|---|
| 删除 governance 版本 | 会丢失准入机制设计 |
| 强制迁移到 governance 版本 | 破坏 16 个导入点，且 governance 版本缺少 `compute_func` 支持 |

### 验证

- `pytest tests/test_factor_registry.py tests/test_custom_factors.py -xvs` → 通过
- `rg "from.*factor_governance.*import"` → 仅 deprecation warning
- `rg "from.*brain.*factors.*registry.*import"` → 全部指向统一版本
- 全回归: `pytest tests/ -q` → 0 失败

---

## G-3: Phase 0 交付物提交

### 现状

所有 9 项 Phase 0 交付物均存在但未提交:

| # | 文件 | 状态 |
|---|---|---|
| 1 | `unified_engine.py` (SELL 优先级修改) | ` M` 已修改未暂存 |
| 2 | `scripts/capture_baseline.py` | `??` 未追踪 |
| 3 | `scripts/compare_baseline.py` | `??` 未追踪 |
| 4 | `tests/benchmark/golden_20.txt` | `??` 未追踪 |
| 5 | `tests/benchmark/golden_100.txt` | `??` 未追踪 |
| 6 | `tests/benchmark/baseline_v0.parquet` | `??` 未追踪 |
| 7 | `tests/benchmark/baseline_v0_100.parquet` | `??` 未追踪 |
| 8 | `tests/benchmark/baseline_v0_intermediate.parquet` | `??` 未追踪 |
| 9 | `tests/benchmark/baseline_v0_100_intermediate.parquet` | `??` 未追踪 |

### 修复方案

两步提交:

#### 步骤 1: 暂存并提交 Phase 0 代码

```bash
git add src/uniquant/hands/backtest/unified_engine.py
git add scripts/capture_baseline.py scripts/compare_baseline.py
git add tests/benchmark/golden_20.txt tests/benchmark/golden_100.txt
git commit -m "feat(phase-0): LPPL SELL priority and baseline tooling

- SELL-before-BUY: LPPL SELL signal cannot be overridden by same-day BUY
- scripts/capture_baseline.py: baseline capture for golden_{20,100} stock lists
- scripts/compare_baseline.py: regression comparison with configurable tolerance
- tests/benchmark/golden_{20,100}.txt: representative A-share stock lists
"
```

#### 步骤 2: 暂存并提交基线数据 (单独提交)

```bash
git add tests/benchmark/baseline_v0.parquet tests/benchmark/baseline_v0_100.parquet
git add tests/benchmark/baseline_v0_intermediate.parquet tests/benchmark/baseline_v0_100_intermediate.parquet
git commit -m "chore(phase-0): baseline parquet data for regression testing

Baseline generated from golden_20 (100% success) and golden_100 (100% success).
Used by compare_baseline.py for regression detection.
"
```

### 风险

- 基线 parquet 文件 (~500KB) 会增加仓库大小。考虑 `.gitignore` 是否排除后续基线，仅保留初版。
- 确保 `unified_engine.py` 仅包含 SELL 优先级改动，不包含其他未提交修改。

---

## G-4: Async EventBus

### 现状

当前 `EventBus` (`shared/event_bus.py`) 为纯同步实现。`publish()` 方法按顺序串行调用所有 handler，单个慢 handler 会阻塞整个调用链。

### 目标

提供异步 EventBus 变体，将 handler 执行分派到线程池，不阻塞 `publish()` 调用者。

### 修复方案

#### 步骤 1: 创建 AsyncEventBus

**文件**: `src/uniquant/shared/event_bus.py` (扩展)

```python
import threading
from concurrent.futures import ThreadPoolExecutor

class AsyncEventBus(EventBus):
    """异步 EventBus: 使用线程池执行 handler，不阻塞 publish()"""

    def __init__(self, max_workers: int = 4, isolate_errors: bool = True):
        super().__init__(isolate_errors)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eventbus")

    def publish(self, event: Event) -> None:
        for handler in self._subscribers.get(event.topic, []):
            self._executor.submit(self._safe_dispatch, handler, event)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _safe_dispatch(self, handler: EventHandler, event: Event) -> None:
        if self._isolate_errors:
            try:
                handler(event)
            except Exception:
                logger.exception(f"Handler {handler} failed on event {event.topic}")
        else:
            handler(event)
```

#### 步骤 2: 更新 feature flag

```yaml
# config.yaml
refactoring:
  feature_flags:
    async_event_bus: false  # 新增
```

```python
# config_models.py
class FeatureFlags:
    async_event_bus: bool = False
```

#### 步骤 3: ServiceContainer 集成

```python
# service_container.py
if self._config.get("refactoring", {}).get("feature_flags", {}).get("async_event_bus"):
    from ..shared.event_bus import AsyncEventBus
    self._event_bus = AsyncEventBus()
else:
    from ..shared.event_bus import EventBus
    self._event_bus = EventBus()
```

#### 步骤 4: 测试

**文件**: `tests/shared/test_async_event_bus.py`

| 测试 | 描述 |
|---|---|
| `test_publish_non_blocking` | publish() 不等待 handler 完成 |
| `test_multiple_subscribers_parallel` | 多个 handler 并行执行 |
| `test_error_isolation` | 一个 handler 失败不影响其他 |
| `test_shutdown_waits` | shutdown(wait=True) 等待所有任务完成 |
| `test_publish_order_not_guaranteed` | 验证异步不保序 (与同步对比) |

### 风险与缓解

| 风险 | 缓解 |
|---|---|
| 线程安全问题(hander 内共享状态) | 文档说明 handler 应为无状态或使用线程安全数据结构 |
| 资源泄漏(线程池未 shutdown) | `shutdown()` 在 `ServiceContainer.shutdown()` 中调用 |
| 异常丢失 | `_safe_dispatch` 记录所有异常日志 |

---

## 执行进展 (2026-06-11)

| 缺口 | 优先级 | 状态 | 工作量 | 完成情况 |
|---|---|---|---|---|
| **G-3** (Phase 0 提交) | **P0** | **✅ 完成** | 0.5h | 2 次提交, 代码+基线均入库 |
| **G-2** (FactorRegistry) | **P1** | **✅ 完成** | 1 天 | brain 版增强准入; shared 版废弃 |
| **G-4** (Async EventBus) | **P2** | **✅ 完成** | 1 天 | AsyncEventBus + 9 测试 |
| **G-1** (TimeProvider) | **P2** | **✅ 完成** | ~2 天 | 全库 ~120 个时钟调用全部替换为 get_time_provider() |

### G-1 完成统计

| 层级 | 修复调用数 | 修复文件数 |
|---|---|---|
| shared/ | 10 | 4 |
| signal/ | 10 | 5 |
| hands/ | 8 | 4 |
| brain/ | 11 | 6 |
| services/ | 53 | 10 |
| data/ | 21 | 18 |
| ui/ | 11 | 4 |
| **合计** | **~124** | **51** |

### 出口标准跟踪

1. ✅ G-3: `git log` 中包含 Phase 0 提交；`capture_baseline.py && compare_baseline.py` 可运行
2. ✅ G-2: `shared/factor_governance.py` 标记废弃；`brain/factors/registry.py` 包含 `check_access()`；16 个导入点指向统一版本
3. ✅ G-4: `AsyncEventBus` 类存在；feature flag 默认关闭；9 测试覆盖并行调度和错误隔离
4. ✅ G-1: 全库 ~124 个 `datetime.now()` / `pd.Timestamp.now()` 调用全部替换为 `get_time_provider()`；协议扩展 `epoch()` / `epoch_ms()` 支持时间戳需求；模块级 `get_time_provider()` / `set_time_provider()` 支持 DI-free 测试
5. ✅ 全量回归: `pytest tests/ -q` → 1,159 通过，0 失败
6. ✅ 基线一致: `compare_baseline.py` → 100% 匹配
