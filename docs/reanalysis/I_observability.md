# Phase I — 可观测性与运维审计报告

审计日期: 2026-07-06
审计范围: `src/uniquant/` 全部 Python 源文件
审计方法: 代码静态分析 + 结构扫描

---

## I1 日志审计

### 日志基础设施

| 项目 | 状态 |
|---|---|
| 日志框架 | Python 标准库 `logging` |
| 工厂模式 | `LoggerFactory` 单例 (线程安全，`RLock`) |
| 全局入口 | `get_logger(name)` / `setup_logger(name)` |
| 配置文件 | `config.yaml` → `base.logging.*` 全部可配置 |
| 日志轮转 | `RotatingFileHandler`，10MB/file，保留 5 份 |
| 线程安全 | `QueueHandler` + `QueueListener` 异步写文件 |
| 控制台输出 | 同步 `StreamHandler(sys.stdout)` |
| 格式 | `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"` (纯文本) |

### 日志级别统计

| 级别 | 使用频次 | 典型场景 |
|---|---|---|
| `DEBUG` | ~30 处 | 回测引擎订单级细节 (T+1 拒绝、涨停/跌停拒绝) |
| `INFO` | ~50 处 | 数据加载成功、更新完成、报告生成、模块加载 |
| `WARNING` | ~60 处 | 数据缺失、文件不存在、参数不匹配、验证失败 |
| `ERROR` | ~80 处 | 文件 I/O 失败、数据解析失败、引擎异常 |
| `CRITICAL` | ~10 处 | UI 层意外异常 (manager_logic, dashboard, portfolio_analytics) |

### 日志使用评估

**优势:**
- `LoggerFactory` 单例实现良好，线程安全，配置可外部化
- 文件日志使用 `QueueHandler` + `QueueListener` 避免阻塞
- 日志级别使用基本合理，`ERROR` 用于可恢复的异常，`CRITICAL` 用于意外崩溃
- `handle_errors` 装饰器统一 `log_level=logging.ERROR` 默认值

**问题:**
- 无结构化日志 (JSON)，纯文本格式不利于日志聚合系统 (ELK/Loki) 解析
- 无 `extra` 上下文传递，关键字段 (trace_id, symbol, engine) 被嵌入格式化字符串而非结构化字段
- `logger.exception()` 使用不足 — 很多 `logger.error()` 未带 `exc_info=True`
- `DEBUG` 日志集中在回测引擎，大脑/信号/风险层基本无 DEBUG 输出
- 无独立错误日志文件 (所有级别混合写入同一文件)
- 日志文件路径 `logs/alpha_tactician.log` 固定，无法按日期/模块拆分

### 日志轮转配置

```
max_bytes=10MB
backupCount=5
```

最小建议：`max_bytes=100MB`, `backupCount=10`。当前配置在批量全量扫描时可能频繁轮转。

---

## I2 健康检查

### 服务层健康检查 (`HealthService`)

文件: `src/uniquant/services/health_service.py` (565 行)

**三层检查体系:**

| 层级 | 方法 | 检查内容 | 依赖 |
|---|---|---|---|
| Liveness | `liveness()` | 进程存活 + 配置加载 | 仅内存 |
| Readiness | `readiness()` | 数据湖路径 + 缓存路径 + 配置验证 | 文件系统 |
| Diagnostics | `diagnostics()` / `get_system_health()` | 全链路端到端 | 所有服务 |

**子系统健康检查覆盖:**

| 检查方法 | 覆盖范围 |
|---|---|
| `_check_data_service_health()` | 数据获取、缓存状态 |
| `_check_analysis_service_health()` | 宏观健康分析 (EVT) |
| `_check_brain_health()` | FSM 决策引擎 |
| `_check_risk_health()` | EVT 风险指标计算 |
| `_check_cache_health()` | 缓存统计 |
| `_check_data_lake_health()` | 数据湖目录 + 文件数 |
| `_check_system_health()` | CPU/内存/磁盘 (psutil) |

**附加功能:**
- `_get_system_metrics()`: 缓存大小、命中率、数据源时效性
- `_get_health_recommendations()`: 基于状态生成运维建议
- `export_health_report()`: 导出 JSON/文本格式报告
- `save_health_report()`: 持久化到文件
- `get_health_history()`: 最近 100 条历史记录

### UI 层健康检查 (`ModuleHealthChecker`)

文件: `src/uniquant/ui/health_check.py` (50 行)

检查 8 个核心模块的导入完整性:
- FSM Engine, CZSC Engine, LPPL Engine, LRD Engine, NTF Engine
- EVT Risk, Data Fetcher, Storage Manager

### 评估

**优势:**
- 三层检查体系 (liveness/readiness/diagnostics) 设计合理，符合 K8s 探针规范
- 覆盖 7 个子系统，功能完整
- `RECOVERABLE_ERRORS` 元组统一捕获非致命异常
- 历史记录 + 导出功能

**问题:**
- **无 HTTP 端点** — `HealthService` 是纯类，未暴露为 HTTP API (`/health`, `/ready`, `/live`)
- 无 Streamlit 内置健康检查端点 (Streamlit 本身不支持自定义路由)
- 无定时自动健康检查 (需外部调度器或 cron)
- 脑健康检查硬编码 `601339` 作为测试股票，可能在生产中不存在
- `diagnostics()` 简化为 `get_system_health()` 别名，未实现真正的全链路端到端检查

---

## I3 错误可追踪性

### trace_id 覆盖

| 位置 | 使用方式 |
|---|---|
| `shared/event_types.py:23` | `event_id: str = field(default_factory=lambda: uuid.uuid4().hex)` |
| `shared/event_types.py:33` | `command_id: str = field(default_factory=lambda: uuid.uuid4().hex)` |
| `shared/event_types.py:84` | `AnalysisRequest.__init__` 接受 `trace_id` 参数 |
| `services/analysis_service_v2.py` | 全流程传递 `trace_id`，附着到 `data_pack.metadata` |
| `services/research_pipeline.py` | 全流程传递 `trace_id`，附着到 `PipelineResult` |
| `signal/models.py:120` | `TradingSignal.id = uuid4().hex` |

### 异常层次结构

文件: `src/uniquant/shared/exceptions.py` (123 行)

```
AlphaTacticianError
├── DataError
│   ├── DataFetchError
│   ├── DataValidationError
│   ├── DataStorageError
│   │   └── DatabaseConnectionError
│   ├── DataAccessError
│   └── CacheError
├── AnalysisError
│   ├── LPPLFitError
│   ├── CZSCEngineError
│   └── EngineError
├── RiskError
│   ├── PositionSizingError
│   ├── EVTRiskError
│   └── RiskCalculationError
├── ServiceError
│   ├── AnalysisServiceError
│   ├── DataServiceError
│   ├── PortfolioServiceError
│   └── DependencyError
├── UIError
│   ├── DashboardError
│   └── VisualizationError
├── ConfigurationError
├── OperationTimeoutError
├── ValidationError
├── BacktestError
├── LPPLException (基类)
│   ├── DataNotFoundError
│   └── ComputationError
└── WyckoffError
    ├── BCNotFoundError
    ├── InvalidInputDataError
    ├── ImageProcessingError
    ├── FusionConflictError
    └── RuleEngineError
```

### 评估

**优势:**
- `trace_id` 在分析服务和研究管道中端到端传递
- 异常层次结构完善，覆盖数据、分析、风险、服务、UI 各层
- 事件系统自带 `event_id` / `command_id` UUID

**问题:**
- **no `request_id`** — 无 HTTP 请求级追踪 ID，因为系统无 HTTP 入口
- 异常实例不携带 `trace_id` 上下文 — 异常被抛出时丢失调用链 ID
- 异常被捕获时，`logger.error()` 很少附加 `trace_id` 到日志中
- 日志消息不是结构化的，trace_id 嵌入在字符串中，无法被日志系统自动索引
- 无 OpenTelemetry / OpenTracing 集成

---

## I4 指标暴露

### 指标系统集成状态

| 技术 | 状态 |
|---|---|
| Prometheus | ❌ 未集成 |
| OpenTelemetry | ❌ 未集成 |
| 自定义指标 | ❌ 无 |
| Micrometer | ❌ 不适用 |

### 现有"指标"相关代码

搜索到的 `metrics` 引用全部为业务指标（回测绩效、风险指标），而非系统可观测性指标：
- `BacktestResult.metrics` — 回测绩效指标 (夏普、回撤、胜率等)
- `risk_metrics` — VaR/CVaR 等风险指标
- `performance_metrics` — 组合绩效
- `_get_system_metrics()` — 只是内存字典，非 Prometheus 格式

### 评估

指标系统完全缺失。这是可观测性中最大的缺口。

关键缺失:
- 无 Prometheus `/metrics` 端点
- 无业务指标暴露 (信号数量、分析延迟、数据新鲜度、错误率)
- 无 JVM/系统指标 (psutil 仅用于健康检查临时查看)
- 无 Grafana 仪表盘配置
- 无指标聚合或持久化

---

## I5 告警规则建议

基于代码库关键路径分析，建议以下 10 条告警规则:

### 数据层 (P0)

| 规则 | 触发条件 | 严重性 |
|---|---|---|
| 数据新鲜度告警 | 任一股票数据最后更新 > 2 个交易日 | P0 |
| 数据获取失败率 | 批量更新失败率 > 10% | P0 |
| 数据湖存储异常 | 写入文件失败 (原子写入失败) | P1 |
| 复权因子更新失败 | 复权任务返回失败 | P1 |

### 分析引擎层 (P0)

| 规则 | 触发条件 | 严重性 |
|---|---|---|
| 引擎分析失败率 | 单引擎分析失败率 > 5% (连续 100 次) | P0 |
| 决策失败 | FSM 决策引擎返回 None 或失败 | P1 |
| 宏观健康异常 | EVT 风险指标计算失败 | P1 |

### 回测层 (P1)

| 规则 | 触发条件 | 严重性 |
|---|---|---|
| 回测结果异常 | 夏普比率 < -1.0 或最大回撤 > 50% (全量扫描) | P1 |
| 匹配引擎错误 | 匹配引擎抛出未捕获异常 | P1 |

### 系统层 (P2)

| 规则 | 触发条件 | 严重性 |
|---|---|---|
| 磁盘空间不足 | 数据湖磁盘使用率 > 85% | P2 |
| 内存使用过高 | 系统内存使用率 > 80% | P2 |
| 缓存命中率低下 | 缓存命中率 < 50% (连续 1 小时) | P2 |

### 信号层 (P2)

| 规则 | 触发条件 | 严重性 |
|---|---|---|
| 信号适配器错误 | 信号适配器转换失败率 > 5% | P2 |
| 仲裁冲突 | 连续 10 次以上信号仲裁结果为冲突 | P2 |

---

## I6 资源监控

### Dashboard 资源监控现状

文件: `src/uniquant/ui/dashboard.py` (1553 行)

**现有健康监控面板** (Tab 1: 宏观驾驶舱):
- `render_health_metrics(network_ok, lake_ok, engine_ok, kb_ok, regime)` — 4 个布尔状态 + 1 个 regime 状态
- `ModuleHealthChecker.check_all()` — 8 个模块导入完整性检查 (折叠展开)
- `render_structural_risk_gauges(risks)` — LPPL 结构风险仪表盘
- `render_anti_fragile_metrics(evt_stats)` — 反脆弱核心指标
- `render_drawdown_dashboard(drawdown_metrics, tail_risk_metrics)` — 回撤仪表盘

**缺失的资源监控:**
- ❌ CPU 使用率实时监控
- ❌ 内存使用率实时监控
- ❌ 磁盘使用率监控
- ❌ 缓存命中率趋势图
- ❌ 数据新鲜度仪表盘
- ❌ 引擎错误率时间序列
- ❌ 信号生成速率监控
- ❌ 分析延迟监控 (P99/P95)

### psutil 使用情况

`HealthService._check_system_health()` 和 `_get_uptime()` 使用 `psutil` 检查系统指标，但:
- 仅在手动调用健康检查时运行，非持续监控
- 结果未暴露到 Dashboard 或持久化
- `psutil` 标记为可选依赖 (ImportError 静默降级)

---

## 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| I1 日志 | B | 基础完善，无结构化，无 ELK 集成 |
| I2 健康检查 | A- | 三层体系完善，缺 HTTP 端点 |
| I3 错误追踪 | B | trace_id 端到端，异常类完善，缺结构化上下文 |
| I4 指标 | F | 完全缺失 Prometheus/OTel |
| I5 告警 | N/A | 未实现，仅建议 |
| I6 资源监控 | D | 基础 psutil 存在，未集成到 UI |

**总体可观测性成熟度: 2/5** — 日志和健康检查基本就绪，指标和追踪系统完全缺失。

---

## 关键改进建议 (按优先级)

1. 集成 Prometheus 客户端，暴露 `/metrics` 端点 (信号计数、分析延迟、错误率、数据新鲜度)
2. 日志格式改为 JSON (结构化)，附加 `trace_id` / `symbol` / `engine` 等字段
3. 为 HealthService 添加 HTTP 端点 (`/health`, `/ready`, `/live`)
4. 异常类添加 `trace_id` 属性，异常被捕获时自动记录
5. Dashboard 添加系统资源面板 (CPU/内存/磁盘/缓存命中率)
6. 独立错误日志文件，与其他日志分离
7. 增加 DEBUG 日志覆盖率到大脑/信号/风险层
8. Grafana 仪表盘配置 (基于 Prometheus 指标)

## ANALYSIS COMPLETE