# 全局冲突矩阵 V3 (Global Conflict Matrix V3)

**生成时间**: 2026-06-06
**审计范围**: 跨 Q1 (Foundation) + Q2 (Business Logic) + Q3 (Services/UI) + Q4 (Peripheral)
**总数据源**: 191 个 .py 文件 + 3 docs/3 Docs/ 目录 + 255 MagicMock 目录, ~33.5K LOC + 9.0 MB 泄漏

---

## 一、跨队列冲突映射

### 1.1 全局状态冲突 (Cross-Queue Globals)

| 来源 | 文件:行 | 冲突类型 | 受影响模块 | 风险等级 |
|------|---------|---------|-----------|---------|
| `logger_factory.py:177` | `global _factory` | 类级可变字典无锁 | `shared.*`, `services.*`, `ui.*`, `tests.*` | 🟠 P1 |
| `logger_factory.py:201` | `_loggers = {}` 类级 | 进程间状态污染 | 全局 | 🟠 P1 |
| `health_service.py:498-503` | `global health_service` | 无锁单例 | `services.*`, `ui.*` | 🔴 P0 |
| `config_loader.py:324, 336` | `config = None` + `config = GlobalConfig()` | 延迟单例（合法但脆弱） | `shared.*` | 🟡 P2 |
| `price_collar.py:1` | `from ..shared.market_rules` 软错 | 包名巧合 | `shared.*` | 🟡 P2 |
| `error_handling.py:308` | `_lock = threading.Lock()` 局部锁 | OK（已加锁） | `shared.error_handling` | ✅ OK |
| `industry_provider.py:6` | `global _CACHE` 无锁 | race condition | `brain.factors` | 🟠 P1 |
| `import_1min.py:37, 254` | `MAX_WORKERS = 4` + `global MAX_WORKERS` | shadowing | `data.services` | 🟡 P2 |
| `import_5min.py:37, 254` | 同上 | shadowing | `data.services` | 🟡 P2 |

**冲突域**: 全局可变状态分散在 `shared/`, `services/`, `brain/`, `data/` 4 个包，**未通过统一机制管理**。

### 1.2 幽灵依赖冲突 (Phantom Dependencies)

| 依赖 | 在 pyproject 中 | 实际 import | 触达模块 | 处理状态 |
|------|----------------|------------|---------|---------|
| `pybreaker` | ❌ | `data/sources/base.py:9`, `data/managers/source_router.py:5` | `data.*` | 无 try/except，**启动崩溃** |
| `czsc` | ❌ | `brain/czsc/czsc_engine.py:6-9` | `brain.czsc` | 无 try/except，**启动崩溃** |
| `py_mini_racer` | ❌ (optional: `js`) | `data/utils/js_executor.py:4` | `data.utils` | 无 try/except，**启动崩溃** |
| `urllib3` | ❌ | 多个 `data/sources/*` | `data.sources` | 隐式依赖 `requests` |
| `backtrader` | ❌ | 未知 (回测文件未深查) | `hands.backtest` | 待验证 |
| `exchange_calendars` | ❌ | `services/calendar` | `services` | 待验证 |
| `st_aggrid` | ❌ (V3 P0 建议添加) | `ui/dashboard.py:11` | `ui.dashboard` | try/except 兜底 ✅ |
| `streamlit-autorefresh` | ❌ | `ui/dashboard.py:21` | `ui.dashboard` | try/except 兜底 ✅ |
| `streamlit-echarts` | ❌ | `ui/dashboard.py:28` | `ui.dashboard` | try/except 兜底 ✅ |

**冲突域**: 9 个幽灵依赖，其中 6 个**没有 try/except 保护**（启动级崩溃风险）。

### 1.3 僵尸代码冲突 (Zombie Code)

| 类别 | 文件 | 调用方数 | 优先级 |
|------|------|----------|--------|
| 共享僵尸 | `shared/parallel.py` | 0 | 删除 |
| 共享僵尸 | `shared/network_constants.py` | 0 | 删除 |
| 共享僵尸 | `shared/market_constants.py` | 0 | 删除 |
| 共享僵尸 | `shared/slippage_model.py` | 0 | 删除 |
| 服务僵尸 | `services/report_service.py` | 0 (仅占位) | 实现或删除 |
| 服务僵尸 | `services/signal_generation_service.py` | 0 (仅占位) | 实现或删除 |
| 服务僵尸 | `services/market_regime_service.py` | 0 (仅占位) | 实现或删除 |
| 引擎僵尸 | `brain/alpha_decoupler.py` (deprecated) | 0 外部 | 删除 |
| 引擎僵尸 | `brain/regime_detector.py` (deprecated) | 0 外部 | 删除 |
| 引擎僵尸 | `brain/indicators.py` (deprecated) | 0 外部 | 删除 |
| 引擎僵尸 | `brain/czsc_engine.py` (有新版) | 1 外部 | 标记 deprecated |
| 风险僵尸 | `risk/historical_risk.py:HistoricalSimulationRisk` | 继承 `EVTRisk` (反向) | 重构 |
| 策略僵尸 | `hands/strategies/base.py` 错误绝对导入 | 0 (永远失败) | 修复导入 |
| 文档僵尸 | `Docs/` (大写) 3 文件 | 0 (与 docs/ 重复) | 删除 |
| 数据泄漏 | `MagicMock/` 255 目录 | 0 (非代码) | gitignore + 清理 |

**总计**: 15 类僵尸/死代码, 占 LOC 估算 5-8%

### 1.4 反向依赖冲突 (DAG Violations)

| 违规 | 来源 | 方向 | 期望方向 | 影响 |
|------|------|------|---------|------|
| `from risk.sizer` (绝对) | `hands/strategies/base.py:6-12` | hands → risk (硬编码路径) | hands → services → risk | 启动崩溃 |
| `from ..risk.evt_risk import EVTRisk` | `ui/manager_portfolio_analytics_service.py:47` | ui → risk | ui → services → risk | 违反 5 层 DAG |
| `from ..shared.constants import ...` | `ui/*` 多文件 | ui → shared | OK (符合) | - |
| `from ..services.* import ...` | `ui/*` 多文件 | ui → services | OK (符合) | - |
| `from .health_service import ...` | `services/*` 多文件 | services → services | OK (同层) | - |
| `from .data_service import DataService` | `services/analysis_service.py:24` | services → services | OK (同层) | - |

**冲突域**: 2 处明确反向依赖, 1 处绝对路径硬编码

---

## 二、关键质量指标 (Quality Metrics)

### 2.1 代码规模

| 维度 | 数量 | 备注 |
|------|------|------|
| .py 文件总数 | 191 | 不含 test/unit/integration 空 |
| 总 LOC | ~33,500 | 不含 root .py (768KB) |
| 5 层包数 | 7 (shared/data/brain/risk/signal/hands/services/ui) | 含 ui |
| `shared/` LOC | ~7,200 (23 文件) | 完整 |
| `data/` LOC | ~10,000 (43 文件) | 较完整 |
| `brain/` LOC | ~5,500 (18 文件) | 部分 |
| `services/` LOC | ~7,800 (28 文件) | 阻塞 (含僵尸) |
| `ui/` LOC | ~3,250 (8 文件) | 部分 |
| 根目录散落 .py | 766,666B (34 文件) | 实验性 |
| `scripts/` | 50,509B (12 文件) | CLI |
| `tests/` | 568,944B (79 文件) | 待验证可运行性 |
| `MagicMock/` | 9.0 MB (255 目录) | **泄漏** |

### 2.2 测试覆盖

| 指标 | 数值 | 备注 |
|------|------|------|
| 测试文件数 | 79 | 56 + 3 chaos + 19 大文件 |
| 独立可运行测试 | 1 (`test_engine_factory.py`) | AGENTS.md 声明 |
| 含 `np.random` 无 seed | `conftest.py:all fixtures` | 不可重现 |
| 含 `MagicMock` (Python lib) | 8 测试文件 | 单元测试惯例 |
| 空测试目录 | 2 (`unit/`, `integration/`) | 占位 |
| 测试产物 JSON | 15+ (1 MB+) | 根目录散落 |

### 2.3 单类/单文件过载

| 文件 | LOC | 类/函数 | 问题 |
|------|-----|---------|------|
| `services/analysis_service.py` | 1642 | 1 class (1597 行) | 5+ 职责 |
| `ui/dashboard.py` | 1524 | 0 class (11 defs) | 仪表盘单体 |
| `risk/portfolio_optimizer.py` | 14813B | - | 偏大 |
| `services/scan_service.py` | 551 行 | - | 偏大 |
| `services/portfolio_service.py` | 568 行 | - | 偏大 |
| `services/data_service.py` | 22 KB | - | 偏大 |
| `brain/wyckoff/engine.py` | 6 个 100+ 行方法 | - | 单元测试低 |
| `hands/backtest/engine.py:run_backtest` | 170 行函数 | - | 可读性差 |

### 2.4 死代码体量估算

| 类别 | 文件/类 | 估算 LOC |
|------|---------|----------|
| `shared/` 4 僵尸 | 4 文件 | ~600 LOC |
| `services/` 3 僵尸服务 | 3 类 | ~150 LOC |
| `brain/` 4 deprecated 引擎 | 4 文件 | ~1200 LOC |
| `risk/historical_risk.py` | 1 类 | ~200 LOC |
| `Docs/` 3 文件 | 3 文件 | 9.3 KB |
| 根目录重复脚本 | 估算 8 个 `_v2`/`_experiment` | ~200 KB |
| 估计死代码总占比 | - | **~5-8%** (~2-3K LOC) |

---

## 三、跨模块冲突域汇总

### 3.1 单例冲突域 (Singleton Conflicts)

**问题**: 多个模块各自实现单例，且**未共享锁**
- `logger_factory._factory` (类级)
- `logger_factory._loggers` (类级字典)
- `health_service.health_service` (模块级)
- `config_loader.config` (模块级延迟)
- `industry_provider._CACHE` (模块级)

**影响**:
- 进程间状态污染（fork 子进程时共享）
- 多线程初始化竞态
- 测试隔离困难（mock 注入后残留）

**修复方案**: 引入统一单例基类
```python
# shared/singleton.py
class ThreadSafeSingleton:
    _instances = {}
    _lock = threading.Lock()
    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__new__(cls)
        return cls._instances[cls]
```

### 3.2 配置冲突域 (Config Conflicts)

**问题**:
- `shared/config_loader.py:GlobalConfig` 双重检查锁单例
- `config/config.yaml` 430 行（巨大）
- `config/trading.yaml`, `config/factors.yaml`, `config/optimal_params.yaml` 4 个 YAML
- 多个配置入口，无统一 schema 验证
- `config.yaml:16-17` 硬编码 `tdx.path`

**影响**:
- 配置修改无审计日志
- 默认值与代码常量不同步
- 测试环境配置污染

### 3.3 日志冲突域 (Logging Conflicts)

**问题**:
- `shared/logger_factory.py:177` 全局工厂
- `shared/logger_factory.py:201` `_loggers` 类级字典
- 多个测试文件手工覆盖 `get_logger`
- 没有 log rotation 策略
- 37 个异常类全部用同一 logger

**影响**:
- 日志输出混乱
- 测试间 logger 状态污染

### 3.4 错误处理冲突域 (Error Handling Conflicts)

**核实**:
- `shared/error_handling.py:308` 已有锁（OK）
- 37 个异常子类继承 `AlphaTacticianError`
- `@handle_errors()` 装饰器广泛应用
- `retry` 装饰器在 `shared/retry_decorator.py`
- **问题**: 不同模块对同一错误的 catch 行为不一致
  - `services/analysis/engine_factory.py:_lazy_init` 静默 `return None`
  - `services/data_service.py` 抛出 `DataAccessError`
  - `brain/*` 多数抛出 `AnalysisError`

### 3.5 缓存冲突域 (Cache Conflicts)

**核实**:
- `shared/cache/cache_factory.py:CacheFactory` (单例?)
- `data/managers/source_router.py:5` 引用 `pybreaker` 幽灵
- `services/cache_coordinator.py`
- `ui/manager_portfolio_analytics_service.py:47` 直接调 `EVTRisk`
- 无统一缓存失效/TTL 策略

---

## 四、跨队列依赖关系图

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: ui (8 files, 3.2K LOC)                            │
│  - dashboard.py (1524 行) ← 反向依赖 risk ⚠                 │
└────────────────┬────────────────────────────────────────────┘
                 │ 依赖
┌────────────────▼────────────────────────────────────────────┐
│  Layer 4: services (28 files, 7.8K LOC)                     │
│  - analysis_service.py (1642 行) ← 单类过载 ⚠                │
│  - 3 僵尸服务 (report/signal_generation/market_regime)        │
│  - health_service.py:498 无锁单例 ⚠                          │
└────────────────┬────────────────────────────────────────────┘
                 │ 依赖
┌────────────────▼────────────────────────────────────────────┐
│  Layer 3: hands (1 文件, 仅 __init__) + signal (0 文件)      │
│  - strategies/base.py:6-12 错误绝对导入 ⚠                    │
│  - signal/ 包完全缺失                                        │
└────────────────┬────────────────────────────────────────────┘
                 │ 依赖
┌────────────────▼────────────────────────────────────────────┐
│  Layer 2: brain (18 files, 5.5K) + risk (1 文件)            │
│  - brain 4 deprecated 引擎 0 调用方                         │
│  - wyckoff/engine.py 6 个 100+ 行方法                        │
│  - risk/historical_risk 反向 deprecation ⚠                   │
│  - 4 个 shared 僵尸文件                                      │
└────────────────┬────────────────────────────────────────────┘
                 │ 依赖
┌────────────────▼────────────────────────────────────────────┐
│  Layer 1: data (43 文件, 10K)                               │
│  - pybreaker 幽灵 ⚠                                          │
│  - import_1min/5min shadowing ⚠                              │
└────────────────┬────────────────────────────────────────────┘
                 │ 依赖
┌────────────────▼────────────────────────────────────────────┐
│  Layer 0: shared (23 文件, 7.2K)                            │
│  - price_collar.py:1 软错 ⚠                                  │
│  - logger_factory.py:177/201 全局状态 ⚠                      │
│  - error_handling.py:308 ✅ OK                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、关键风险点排序 (Risk Ranking)

| 等级 | 问题 | 队列 | 文件:行 | 修复成本 |
|------|------|------|---------|---------|
| 🔴 P0 | `MagicMock/` 9 MB 泄漏 | Q4 | - | 1 行 |
| 🔴 P0 | `Docs/` 重复目录 | Q4 | - | 1 个 rm |
| 🔴 P0 | 根目录 34 个 .py 散落 | Q4 | - | 半天 |
| 🔴 P0 | `health_service.py:498` 无锁单例 | Q3 | L498-509 | 3 行 |
| 🔴 P0 | `analysis_service.py` 1597 行单类 | Q3 | L45-1642 | 200+ 行 |
| 🔴 P0 | `ui/dashboard.py:11-29` 3 幽灵依赖未声明 | Q3 | L11,21,28 | 4 行 |
| 🟠 P1 | `services/` 3 僵尸服务 | Q3 | 3 文件 | 3 删除 |
| 🟠 P1 | 双套 analysis 抽象 | Q3 | analysis_service + analysis/ | 100 行 |
| 🟠 P1 | `services/analysis_service.py` | Q3 | 1642 行 | 200+ 行 |
| 🟠 P1 | `logger_factory.py:177,201` 全局 | Q1 | L177,201 | 15 行 |
| 🟠 P1 | `industry_provider.py:6` 无锁缓存 | Q2 | L6 | 5 行 |
| 🟠 P1 | `conftest.py` 无 seed | Q4 | fixtures | 3 行 |
| 🟠 P1 | `services/` 12 CLI 内部 import | Q4 | scripts/ | 1 天 |
| 🟠 P1 | `ui/manager_portfolio_analytics` 反向依赖 | Q3 | L47 | 5 行 |
| 🟠 P1 | `engine_factory.py:43` 静默 None | Q3 | L33-44 | 3 行 |
| 🟠 P1 | `service_container.py:50-91` 无回退 | Q3 | L50-91 | 15 行 |
| 🟠 P1 | `ui/__init__.py` 1 字节空 | Q3 | 1 字节 | 5 行 |
| 🟠 P1 | `brain/` 4 deprecated 0 调用 | Q2 | 4 文件 | 4 删除 |
| 🟠 P1 | `risk/historical_risk.py` 反向 deprecation | Q2 | L15 | 10 行 |
| 🟠 P1 | `hands/strategies/base.py:6-12` 错误绝对导入 | Q2 | L6-12 | 1 行 |
| 🟠 P1 | `shared/` 4 僵尸文件 | Q1 | 4 文件 | 4 删除 |
| 🟠 P1 | `ui/dashboard.py` 1524 行 | Q3 | 1524 行 | 200+ 行 |
| 🟠 P1 | `ui/lppl_visualizer.py` 3 个 70+ 行函数 | Q3 | L42-349 | 50 行 |
| 🟠 P1 | `ui/components.py` 25+ 函数 | Q3 | 1 文件 | 100 行 |
| 🟡 P2 | 11 个幽灵依赖未声明 | Q1+Q2 | 9 文件 | pyproject 9 行 |
| 🟡 P2 | `price_collar.py:1` 软错 | Q1 | L1 | 2 行 |
| 🟡 P2 | `import_1min/5min.py` shadowing | Q2 | L37,254 | 6 行 |
| 🟡 P2 | `config/config.yaml:16-17` 硬编码路径 | Q1 | L16-17 | 2 行 |
| 🟡 P2 | `dashboard.py:250-259` 异步刷新无取消 | Q3 | L250-259 | 10 行 |
| 🟡 P2 | `services/__init__.py:__getattr__` 性能 | Q3 | L16-40 | 5 行 |
| 🟡 P2 | 15+ JSON 产物散落根目录 | Q4 | *.json | gitignore 1 行 |
| 🟡 P2 | `tests/unit/` `tests/integration/` 空 | Q4 | 2 目录 | 1 行 |
| 🟡 P2 | `scripts/test_incremental_update.py` 误命名 | Q4 | 1 文件 | 1 mv |

**总计**: 4 P0 (严重) + 21 P1 (重要) + 7 P2 (一般) = 32 个独立问题

---

## 六、跨队列一致性结论

### 6.1 V2 报告整体准确率: 70-80%

| 队列 | V2 准确率 | 主要偏差 |
|------|----------|---------|
| Q1 Foundation | 70% | 软错误判、错误报告"空 __init__" |
| Q2 Business Logic | 75% | 未识别 deprecation 链路, 未识别 `base.py` 绝对导入 |
| Q3 Services/UI | 80% | `__init__.py` `import importlib` 误判 |
| Q4 Peripheral | 50% | **MagicMock 严重误判** |

### 6.2 V3 修正要点
1. **MagicMock 实际意义** — Python `id()` 临时数据泄漏，9.0 MB
2. **price_collar.py 软错** — 包名巧合（`shared` 正确），非 V2 所述"崩溃"
3. **data/services 与 scripts** — 实际有 6 + 4 个导出（V2 称"空"）
4. **hands/strategies** — 实际有 1647 字节懒加载（V2 称"空"）
5. **5 层 DAG** — 2 处明确违反：`ui/manager_portfolio_analytics → risk`、`hands/strategies/base → risk`（硬编码绝对路径）
6. **brain deprecation** — 4 个引擎 zero 外部调用方，pure dead code
7. **risk/historical_risk** — 反向继承触发 deprecation 警告
8. **CLI 数量** — V2 称 5，V3 实际 6（漏 `data_importer.py`）+ 12 scripts

### 6.3 V3 新发现 (V2 未触及)
- 11 个 100+ 行大函数（wyckoff 6、lppl 1、fsm 1、hands 2、eastmoney 1）
- `HistoricalSimulationRisk` 继承 `EVTRisk` 触发反向 deprecation
- `hands/strategies/base.py:6-12` 错误绝对导入
- `engine_factory.py:33-44` 静默 None 失败
- `service_container.py:50-91` 无失败回退
- `conftest.py` 缺 seed（测试不可重现）
- `MagicMock/` 9 MB 临时数据泄漏

---

## 七、修复路线图建议

### 第一波 (Week 1) — P0 紧急
1. 删除 `MagicMock/` + `Docs/` + 根目录 34 散落
2. 修复 `health_service.py:498` 锁
3. 拆分 `AnalysisService` 1597 行
4. 声明 9 个幽灵依赖

### 第二波 (Week 2-3) — P1 重要
1. 删除 4 个 `shared/` 僵尸文件
2. 删除 3 个 `services/` 僵尸服务
3. 删除 4 个 `brain/` deprecated 引擎
4. 修复 `hands/strategies/base.py` 绝对导入
5. 修复 `risk/historical_risk.py` 反向继承
6. 拆分 `ui/dashboard.py` + `ui/components.py` + `ui/lppl_visualizer.py`
7. 修复 `ui/manager_portfolio_analytics` 反向依赖
8. 修复 `engine_factory.py` 静默失败
9. `conftest.py` 加 seed
10. 补全 `ui/__init__.py`

### 第三波 (Week 4+) — P2 收尾
1. 修复 `import_1min/5min` shadowing
2. 修复 `config.yaml` 硬编码路径
3. 添加 `dashboard.py` 异步刷新取消
4. 优化 `services/__init__.py:__getattr__` 性能
5. 添加根目录 JSON 到 .gitignore
6. 清理空测试目录
7. 重命名 `scripts/test_*.py`

---

*本矩阵为 V3 版, 生成自 Q1/Q2/Q3/Q4 四份报告交叉验证, 涵盖 191 个 .py 文件 + 9.0 MB 泄漏数据 + 32 个独立问题。*
