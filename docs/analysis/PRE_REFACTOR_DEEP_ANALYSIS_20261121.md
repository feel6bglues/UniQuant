# UniQuant 重构前深度分析报告（Pre-Refactor Deep Analysis）

> **日期**：2026-11-21 · **性质**：重构决策依据（只读审计，未改任何生产代码）
> **背景**：上云目标 = 容器/Serverless + 对象存储；第 20~24 轮已落地在线数据通道（tdxdata 日线/财务 HTTP/gbbq 官方源/分钟线/实时 snap），离线数据依赖解耦宣告完成。本报告回答：**系统现在长什么样、还剩什么单机假设、重构从哪里切入**。
> **方法**：4 路并行只读 Explore 审计（数据层 / 服务编排 / 信号决策链 / 云部署差距）+ 主线程 AST 导入图与环境硬编码实测 + 记忆/技能上下文。全部结论带 file:line 证据，行号以 2026-11-21 工作树为准。

---

## 1. 执行摘要

**总体判断**：系统分层结构健康（8 层 240 文件 59,834 LOC，24 条层间依赖边仅 9 条逆向且全部有明确修复位），数据通道上云已完成 90%，但**重构的真正主战场不在数据层，而在三个结构性问题**：

1. **三套平行决策体系**（最大架构债）：AnalysisService 七段引擎链、CNMM-QAR 直连（**不产 TradingSignal、不经仲裁器**）、H-A 直连脚本——三条链互不复用，收敛是重构第一刀。
2. **两个平行装配世界**：ServiceContainer（12 服务 DAG）只有 UI 在用；所有生产脚本各自手工组装依赖（含 4 处湖缺时伪造合成数据兜底）。
3. **单机假设残留约 15 处写路径 + 8 个进程级单例**：无 HTTP 层、无分布式锁、无对象存储抽象；`StorageManager` 默认 `./data` CWD 相对且 `save_data` 用 unlink+rename（崩溃丢历史文件窗口）；`env_config.py`（BLAS 单线程强制）是死代码——没人 import。

**上云剩余 P0 差距（5 项）**：依赖声明缺口（**tdxdata/polars/czsc 均未入 pyproject，云镜像按声明构建必缺件**）、日线批量在线同步未闭环（`sync_local_tdx_day.py` 无在线版）、湖级分钟同步未接线（1mins/5mins 目录空）、两处配置消费断裂（freshness 读不存在的键、DataFetcher 不读 tdxdata host 配置）、原子写不统一。

**死代码面显著**：≥15 个模块/接口 src 内零生产消费者（signal 五件套、risk structural、LPPL 旧拟合栈、cffex/twap、robustness 四件套、prometheus exporter 等），重构前可物理剪除以减小迁移面。

---

## 2. 系统规模与分层地图（机械实测）

### 2.1 分层统计（src/uniquant，2026-11-21 实测）

| 层 | 文件数 | LOC | 备注 |
|---|---:|---:|---|
| shared | 40 | 6,734 | 常量/配置/契约/可观测 |
| data | 40 | 7,977 | 三源 + 湖 + 管线 |
| **brain** | **73** | **20,911** | 最大层：wyckoff 16 文件 / factors 14 / lppl 9 |
| risk | 8 | 2,260 | 覆盖率最低层（73.14%）；1 死代码 + 2 嫌疑 |
| signal | 8 | 2,813 | 含一套零消费者的并行体系 |
| hands | 24 | 5,462 | 回测/撮合/机构执行 |
| services | 27 | 8,400 | 编排 + 容器 |
| research | 12 | 1,877 | 门禁/沙盒/账本（依赖方向干净） |
| ui | 8 | 3,400 | Streamlit 单文件 dashboard.py 1,568 行（全仓最大） |
| **合计** | **240** | **59,834** | |

### 2.2 层间导入图（AST 实测）

正向边（合规）：services→shared 84、brain→shared 76、data→shared 62、hands→shared 38、services→brain 19、ui→shared 19、signal→shared 16、risk→shared 11、services→risk 9、ui→services 8、services→data 7、其余小边。

**逆向边（全部 9 条，重构切点已定位）**：

| 逆向依赖 | 位置 | 修复方案 |
|---|---|---|
| brain→risk ×2 | `brain/fsm/fsm.py:214,219`（evt_risk + sizer） | 改 `shared/interfaces.py:587` 已有的 `PositionSizerProtocol` 注入，DecisionBrain 变纯注入 |
| brain→research ×2 | `brain/factors/walk_forward_pipeline.py:21,320` | 整文件迁 research/（它本就是研究编排器，src 内零生产消费者） |
| data→services ×1 | `data/__init__.py:56` | 清理导出面 |
| services→research ×3 | `services/scan_service.py:22-24` | 合规（桥接层设计如此），保留 |
| shared→brain ×1 | `shared/config_validator.py:144` | 因子注册校验改反射/延迟字符串引用 |

brain 内部跨引擎 import 为零（grep 证实）——四引擎全部经 services 层 data_pack 交换，**耦合热点不在 brain 而在 services 与 scripts**。

---

## 3. 数据层审计（A 路）

### 3.1 通道真面目："10 个数据源"是陈旧文档

`sources/` 实际只有 **3 个实现 + base**（`data/sources/__init__.py:4` 的 "10 个数据源实现" docstring 已漂移；`data/__init__.py:5-6` 还列着已删除的 "realtime 实时桥"）。历史 10 源（sina/tencent/ths/eastmoney/baostock 源等）已于 D1/Step3 物理剪除（`tests/test_config_datasources_shrink.py:24-35`）。当前全部数据通道恰 10 条，分布如下：

| 通道 | 后端 | 状态 |
|---|---|---|
| lake | 本地 parquet（SSOT 主源） | ✅ 主力 |
| mootdx_local | 本地 Wine TDX 文件 | ⚠️ 在线兜底第二跳，依赖 Wine 目录 |
| tdxdata_online | 新协议（2026-09） | ✅ 第三跳，日线/实时/财务/xdxr/市值/分钟 |
| mootdx_online | 旧协议 | ❌ 已废弃（enabled:false 保留配置体） |
| akshare（wrapper） | 爬虫 | ✅ 仅指数兜底 + 日历 |
| baostock（_baostock_client） | SDK | ✅ 仅 SSOT/日历生产链（纪律保护） |
| Wine .day/gbbq 解析 | tdx_parser.py | ⚠️ 仅本地（新鲜度锚点用） |
| Wine gpcw*.dat | import_financial | ⚠️ 本地；在线版已落地（sync_online_financial） |
| mootdx.affair 在线财务 | scripts 层 | ✅ 第 22 轮通道 |
| futures lake | 本地 parquet | 衍生湖（akshare 播种） |

### 3.2 get_price 三跳契约（冻结面）

顺序 `_read_lake` → `_fetch_local_fallback` → `_fetch_online_fallback`（`data/data_fetcher.py:256-339`）；9 列契约 `date/open/high/low/close/amount/volume/reserved/code`（:43-53，qfq 追加 adj_factor）；**缓存键 (symbol, adjust) 不含日期窗**——整历史帧缓存后切片，是既有语义非回归；`enable_online_fallback=True` 默认，CI 无 tdxdata 时取数期 ImportError 守卫落空表。

**量纲三套机制并存**（重构归一点）：`harmonize_local_volume_unit`（data_fetcher，手/股混杂自校准）、`LOT_TO_SHARE`（tdxdata 日线×100）、`VOLUME_UNITS` 表（`shared/constants/data.py:55-71`，消费方 normalize_stock_data 本身零调用）。

### 3.3 上云剩余数据缺口（重构第一优先）

1. **日线批量在线同步不存在**：三跳只有单票读语义；湖写唯一通路仍是 `scripts/maintenance/sync_local_tdx_day.py`（Wine .day → 湖）。`fetch_minute`/`fetch_daily` 的在线源**无任何 src 生产调用方**（仅验证脚本）。
2. **湖级分钟同步未接线**：`data/lake/1mins/5mins` 目录空（构造于 `storage_manager.py:66-91`），分钟入湖唯一通路是本地 `sync_minute_mootdx.py`（Wine .lc5）；tdxdata `fetch_minute` 已有（5min 深度 ~10.5 个月）但没人写湖。
3. **新鲜度 SLA 锚点死在 Wine**：`freshness_validator.py:94-112` 读 `TDX_VIPDOC_DIR`/`TDX_PATH` env 兜底 `Path.home()` Wine 路径——容器内恒 None；且 ：104 读 `cfg.get("tdx")` 而 config 是 `base.tdx.path`（**嵌套键错位，该分支永 miss**）。
4. **绕过 StorageManager 的直写者**：`DelistedStockIngestor`（合成退市 K 线直写湖，`delisted_ingestor.py:180-195`）与 `TotalReturnBenchmarkAdapter`（直写 000300TR.SH，`total_return_benchmark.py:98-101`）——重构存储后端时必须一并覆盖。
5. **在线 gbbq 写通道在 scripts 层未收口回 data 层**：`fetch_xdxr_as_gbbq` 产出契约帧但 src 零调用。

### 3.4 死代码与重复（数据层内）

- **死**：DataFetcher 构造即弃的 `data_cleaner/data_validator/pipeline`（`data_fetcher.py:189-201` 全文件无第二处引用）；`LegacyDataFetcher`/`create_fetcher`（仅测试用）；`fetch_stock_real_time` 恒空桩（:485-487）；`save_data/save_factor/read_local_raw` 旧接口（:316-422，src 无调用）；`normalize_stock_data/normalize_multiple_sources/compare_sources`（normalizer.py:96-323，仅测试）；`tdx_parser.calculate_adj_factors`/`get_adjust_factors`/`main()`。
- **重复**：代码归一化 5 份近拷贝（storage_manager/stock_metadata_manager/import_financial/dynamic_pit_universe/dynamic_pit_loader）；市场后缀推断 3 份；周/月合成 90% 逐行相同（resampler.py:31-141）。
- **配置漂移 4 处**：`STOCK_LIST_FILE` 同名双定义（`constants/path.py:27` json vs `:40` csv，后者生效）；`TDX_DIR = PROJECT_ROOT/"tdx"` 是失效默认值；tdxdata host 配置无消费（见 3.3/5.3）；freshness 键错位。

---

## 4. 服务编排 / 配置 / 生产入口（B 路）

### 4.1 ServiceContainer：UI 专用，生产脚本是平行世界

进程内单例（`service_container.py:33-48`），`initialize()` 急切构造 12 服务；**唯一生产调用方是 UI（`ui/dashboard.py:631-634`）**。所有生产脚本（unified_daily_eod / daily_signal_qar / daily_signal_ha / reconcile_qar / 回测脚本）**各自手工组装依赖**——容器编排与生产入口是两套体系，重构必须二选一。

**构造即 IO/触网点**：StorageManager mkdir×7（:59-89）+ 默认 `"./data"` CWD 相对；TradeCalendarManager 构造期可能调 AkShare 刷新日历（`trade_calendar_manager.py:73-108`）；DataService→DataFetcher→MootdxLocalSource 探测本地 TDX。

### 4.2 生产入口全是"一次性 CLI + 外部 cron 假设"

| 入口 | 形态 | 风险点 |
|---|---|---|
| unified_daily_eod | CLI | **持仓硬编码 mock**（:249-251）；**湖缺时伪造合成数据**（:86-97 date_range+linspace）；推荐股池硬编码 4 只 |
| daily_signal_qar | CLI | 读 SSOT + gbbq + 面板 CSV；缺价兜底 50.0 |
| daily_signal_ha | CLI | docstring 自述 cron 假设；`StorageManager("./data")` 相对路径 |
| reconcile_qar | CLI | 纯文件对账，退出码 0/1 语义好；缺价兜底 50.0 |
| 回测两脚本 | CLI | import 时即 mkdir 输出目录 |

全仓**无 API server**（fastapi/uvicorn/flask 零命中）、无消息队列、无 DAG 调度器——进程协作全靠文件系统交接（signal JSON → reconcile，湖 parquet → 各入口）。

### 4.3 配置体系

- env 覆盖机制**已完备**：`UNIQUANT_` 前缀 + 别名表（`TDX_PATH→base.tdx.path` 等）+ `__` 双下划线通用解析 + 自动转型（`config_loader.py:11-77`）——**重构不需要新建机制，只需要把残留硬编码接线过来**。
- 硬编码残留：`config.yaml:18` Wine 路径（可 UNIQUANT_TDX_PATH 覆盖）；`:194` tdxdata host `101.35.121.35:7709`（只能走通配路径，**且 DataFetcher 构造 TdxDataOnlineSource 时根本不读这段配置**——`data_fetcher.py:184` 无参构造，host 只在验证脚本显式传参生效，配置段实际只被测试断言消费）。
- 死配置：observability 段 prometheus_port/health_check_interval 全仓零消费（`ensure_prometheus_server` 零调用）；`network.sources` 三家爬虫 base_url 遗留占位；duckdb engine 未消费。
- 两套解析并存：`shared/config_schema.py:97` 与 `config_models.py` 各自解析 observability/refactoring。

### 4.4 可观测性：有逻辑、无暴露

HealthService 三层探针（liveness/readiness/diagnostics，`health_service.py:59-125`）**已是 K8s 形态但没有 HTTP 端点**；readiness 检查的是本地目录存在性；Prometheus 封装写好了但 exporter 死代码；EventBus 事件即发即失无持久化；日志 RotatingFileHandler 写本地 logs/（cwd 相对）；无 trace 跨服务传播；无分布式锁（仅本地 FileLock `fsm.py:710`）。

---

## 5. 信号决策链审计（C 路）

### 5.1 三条平行决策体系（重构第一刀的靶心）

| 体系 | 路径 | 产出 | 问题 |
|---|---|---|---|
| ① AnalysisService 七段链 | regime→lppl→ntf→czsc→wyckoff→alpha→derived → DecisionBrain → Collector → Arbitrator（`analysis_service_v2.py:351-388,610-629`） | TradingSignal | 正统链，但只有 UI 全链调用 |
| ② CNMM-QAR 直连 | `scripts/canslim/daily_signal_qar.py:34-42` 直连 PIT 池 + `cnmm_qar_strategy`（自算 alpha/自组组合/直调 Orchestrator） | **不产 TradingSignal、不经仲裁器** | 绕过全部安全语义（kill switch/sell-priority） |
| ③ H-A 直连 | `scripts/canslim/ha_unified_adapter.py:155,252` 直接造 TradingSignal 喂回测引擎 | TradingSignal | 绕过 brain 与仲裁 |

另有 `unified_daily_eod.py:93-97` **湖缺时伪造合成数据**——与项目 Rule 4（不伪造数据）精神冲突，重构时应改为 fail-fast 或显式 skip。

**无湖可用性结论**：NTF 强制在线（唯一）；regime/alpha-bench/LPPL 兜底只读湖（缺湖返回 UNKNOWN/0 分）；主行情可在线直驱。

### 5.2 引擎资产状态

- **wyckoff**：拆分后结构良好（engine.py 745 行薄装配）；**WSS 模型权重在 scripts/ 目录**（`config.yaml:387` → `scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json`）——模型资产放错地方，容器化必须打包；`fusion_engine.py` src 内零消费者。
- **lppl**：**两套拟合栈并存**（`calculator.py` 665 行旧实现 vs `fitting_optimizer.py`+`numba_optimizer.py` 新栈）；`@njit(cache=True)` 写盘源码旁（只读镜像下每次重编译，Serverless 冷启动敏感）。
- **signal 层两套对象模型**：生产用 adapters/arbitrator；`models.py/normalizer.py/aggregator.py/db.py(SQLite)/quality.py` **零消费者**且 quality.py 自标 DEPRECATED——五件套可整体剪除。
- **hands**：`STRATEGY_MAP` src 内**无运行时消费者**（纯研究入口）；`unified_matching_engine` 仅研究脚本用；**cffex_engine + twap_execution_slicer src/scripts 生产零消费者（仅测试）**；FeeLedger+Orchestrator 仅 QAR 双脚本；`robustness_checker/monte_carlo/overfitting_detector/sensitivity_analyzer` 零消费者。
- **risk 层**：`structural.py` **全仓零消费者（确认死代码）**；`sparse_convex_optimizer`/`drawdown_analyzer` 仅测试（嫌疑）；sizer/evt_risk/compliance 活跃（QAR/UI/容器三处）。
- **research**：依赖方向干净（bridge 明确"research 不 import brain"）；但 gates/sandboxes 消费方只有 research 自身 + 1 个脚本——控制平面尚无服务层入口。
- **fsm 状态本地盘**：`data/state/fsm_state.json` + FileLock（`fsm.py:695-717`）；saga 用 SQLite 本地文件（`saga_compensator.py:83`）——上云阻断项，需抽 StateStore 接口（本地盘/对象存储双实现）。

---

## 6. 云部署差距审计（D 路）

### 6.1 环境硬编码总表

| 类别 | 位置 | 性质 |
|---|---|---|
| src 内 Wine 路径兜底 ×3 | `freshness_validator.py:110-111`、`tdx_parser.py:549`、`config_validator.py:66` | 容器内需 env 注入 |
| config Wine 路径 | `config.yaml:18`（+分钟线 ：151,156） | 可 UNIQUANT_TDX_PATH 覆盖 |
| scripts /home/james ×5 | param_sweep_v2:38、3 个 qfq 验证脚本、rebuild_financial_lake:21 | 前四者**无覆盖** |
| scripts Path.home() ×10 | sync_local_tdx_day / verify_* / calculate_factors_v15 / convert_local_lc5 / phase_c_execute | 多数可参数覆盖或验证专用 |
| /tmp 硬编码 | momentum_residual_analysis.py:193（无参数） | 脚本级 |
| Windows 盘符残留 | download_etf_data.py:60-64（d:\dfq 猜测链） | 脚本级 |
| tests 42 处 | mock/skip 守卫为主 | CI 有防回归守卫（test_no_dev_absolute_paths） |

### 6.2 仍读 Wine 二进制的 8 个脚本（在线替代对照）

| 脚本 | 在线替代状态 |
|---|---|
| sync_local_tdx_day.py（日线+gbbq→湖） | ❌ **日线批量在线版不存在（P0）**；gbbq 部分已被 sync_online_gbbq.py 替代 |
| rebuild_financial_lake.py | ✅ 已替代（sync_online_financial.py，第 22 轮） |
| convert_local_lc5.py + fetch_minute5_server.py | ❌ 且 fetch_minute5_server 依赖**已死的旧协议 mootdx TCP** |
| download_etf_data.py | ❌ 无 |
| calculate_factors_v15.py / verify_* ×4 | 验证/因子链，上游 gbbq 已可在线产出 |

### 6.3 网络与依赖声明

- **src 无 import 时触网**（全部懒导入）；唯一 import 副作用是 mootdx 在 HOME 下建目录（`tests/conftest.py:29-34` 预建规避其 TOCTOU——**只读容器 FS 会失败**）。
- **pyproject 三缺**：`tdxdata`（第 20~24 轮主通道！）、`polars`（PIT 加载核心）、`czsc`（缠论引擎，CI 已知缺省少 30 用例）——三者目前装在用户 site-packages，**云镜像按 pyproject 构建必缺件**。无 lockfile、无 Dockerfile。
- 系统级：weasyprint→pango/cairo、lxml→libxml2、matplotlib 中文字体。
- **CI 恒不验证在线兜底**：CI 安装集无 tdxdata → `_fetch_online_fallback` 永远走空表路径——上云前应加一个装 tdxdata 的可选 job 或本地验收纪律。

### 6.4 持久化与原子写（对象存储改造的主战场）

- **~15 个本地写目录**：data/lake（7 子目录）、data/fq、data/cache、data/state、data/manifests、data/service_cache、data/quarantine、data/factors、results/{date}、results/daily_qar、results/h_a_signals、results/backtest、logs/、data/.tdx_fingerprints.json。
- **三种原子写并存**：真 `os.replace`（ledger/result_store/research_pipeline/sync_*）✅；**`storage_manager.save_data/save_factor` 用 unlink+rename——目标缺失窗口崩溃丢历史文件**（`storage_manager.py:386-421`）❌；直写（write_parquet:141、import_financial:352）❌。全仓 **0 处 os.fsync**。
- per-symbol parquet 分片本身对象存储友好，但写路径是"读全文件→改→整文件重写"（append 语义），对象存储下无原子 replace 需要两段提交或换后端。
- **FileLock 语义在对象存储上失效**（`storage_manager.py:138`）；`.scan_cache` 检查点、fsm 状态、saga SQLite 同理。
- cwd 相对路径 ×4：`./data`（storage_manager:59）、`./results`（result_store:42）、`logs`（logger_factory:87）、`config_loader.py:114-117` LOG_DIR 误用 cache.path（属性错位 bug）。

### 6.5 进程模型

- `env_config.py`（BLAS 单线程强制）**死代码**——各脚本各自 `os.environ["OMP_NUM_THREADS"]="1"`，常驻容器多副本下 BLAS 线程可能爆炸。
- numba `@njit(cache=True)` ×9 处：只读镜像/临时 FS 下缓存写失败→每次重编译（Serverless 冷启动敏感）。
- joblib loky（`data_service.py:546`）+ 脚本 ProcessPool ×7 + ThreadPool ×8；`cpu_count()` 扩缩与容器 CPU limit 不感知。
- 8 个进程级单例：SharedKillSwitch（**kill 状态不落盘，重启即复位**）、ServiceContainer、GlobalConfig、MetricsRegistry、SecretManager、LoggerFactory、MarketLevelCache、DataFetcher._price_cache（LRU 5000）。

### 6.6 CI/测试面

requires_lake 52 / requires_gbbq 7 / requires_futures_lake 5 = **64 用例 / 12 文件**声明式跳过（`tests/conftest.py:59-103`）；标记外本地 skipif 真数据测试 4 文件；czsc 缺口 ~39 用例。测试 249 文件/3639 函数中约 98% 可在无湖容器跑——**但 CI 对数据管道本身零覆盖**，上云后需用对象存储挂载湖点亮 requires_lake 面。

---

## 7. 重构路线图（优先级建议）

### P0 — 上云阻断项（不修无法部署）

| # | 项 | 动作 | 证据锚点 |
|---|---|---|---|
| 1 | 依赖声明缺口 | pyproject 声明 tdxdata/polars/czsc（czsc 可进 extras 保护 CI）+ 生成 lockfile + Dockerfile | pyproject.toml:10-53 |
| 2 | 存储层统一 os.replace | save_data/save_factor 的 unlink+rename 改 os.replace；路径显式化（env/config 注入替代 `./data`/`./results`/`logs`） | storage_manager.py:386-421 |
| 3 | 配置消费断裂修复 | DataFetcher 构造 tdxdata 源时读 config host；freshness_validator 读 `base.tdx.path` 正确键 | data_fetcher.py:184、freshness_validator.py:104 |
| 4 | 日线批量在线同步 | 新建 sync_online_daily.py（tdxdata 分页拉取 → 复用 sync_local_tdx_day 的写湖编排），替代 Wine 播种 | sync_local_tdx_day.py |
| 5 | 湖级分钟同步 | 接线 tdxdata fetch_minute → 1mins/5mins 湖（增量语义，历史归档另案） | sync_minute_mootdx.py |

### P1 — 架构收敛（重构主体）

| # | 项 | 动作 |
|---|---|---|
| 6 | **三套决策链收敛** | CNMM-QAR 与 H-A 收敛到统一 Pipeline：全部产出 TradingSignal、仲裁器唯一出口、kill switch 全覆盖；unified_daily_eod 湖缺改 fail-fast |
| 7 | 装配世界二选一 | 生产脚本走 ServiceContainer（或容器降为 UI 专用 + 抽轻量 bootstrap）；构造即 IO 的服务改懒初始化 |
| 8 | 逆向依赖清零 | fsm→risk 改协议注入；walk_forward_pipeline 迁 research；data/__init__ 与 shared→brain 解耦 |
| 9 | 状态后端抽象 | FSM StateStore / saga SQLite / ResultStore / MarketLevelCache 抽存储接口（本地盘 + 对象存储双实现）；kill switch 状态落盘 |
| 10 | 死代码物理剪除 | signal 五件套（models/normalizer/aggregator/db/quality）、risk structural.py、LPPL calculator.py 旧栈、wyckoff fusion_engine、cffex+twap（裁决：并入 QAR 链或归档）、robustness 四件套、env_config.py、prometheus exporter 接线或删、StorageManager 旧接口、normalize_stock_data 族、DataFetcher 构造即弃三件 |

### P2 — 质量与可观测（上云后加固）

| # | 项 | 动作 |
|---|---|---|
| 11 | HTTP 健康层 | HealthService 已有三层探针逻辑，补 FastAPI/框架端点；prometheus exporter 接线（现成代码） |
| 12 | 重复逻辑归一 | 代码归一化 ×5→1；市场后缀推断 ×3→1；量纲机制 ×3→1；周月合成去重 |
| 13 | 分布式锁与缓存 | FileLock → 分布式锁（Redis/对象存储条件写）；MarketLevelCache 后端化 |
| 14 | 调度编排 | cron 假设显式化（Argo/Airflow/云函数触发器）；对账链（signal JSON → reconcile）改显式编排 |
| 15 | UI 分离（可选） | UI→services 单向依赖已是好起点；如需分离补 HTTP 边界 |
| 16 | 模型资产归仓 | WSS JSON 从 scripts/ 迁入包内或对象存储；config 路径同步 |

**顺序建议**：P0 全部 → P1-6/7（先收敛决策链与装配）→ P1-8/9/10（并行可做）→ P2 按需。P1-10 死代码剪除建议放在 P1-6 之后做，避免收敛过程中移动即将删除的代码。

---

## 8. 诚实边界与未决项

- 本审计**未执行**任何重构，未改生产代码；行号基于 2026-11-21 工作树，后续轮次会漂移。
- `risk` 层覆盖率 73.14% 为 CI 口径（AGENTS.md 第九轮实测），重构中若剪除死模块该数字会变化。
- 三套决策链收敛方案需要业务裁决：CNMM-QAR 是否保留独立体系（它承载机构 75/25 对冲语义）还是收敛进仲裁框架——**这是产品决策不是纯技术决策**。
- 分钟线历史归档（>10.5 个月深度）仍无在线来源，湖快照依赖保留（第 23 轮已知边界）。
- tdx.com.cn / tdxfin 官方端点无 SLA 承诺；akshare/baostock 爬虫稳定性未知——上云后需要监控与多源冗余设计。
- `czsc` 塞入主依赖会引入 ta-lib 系统级 C 库依赖（第三轮已裁决不进 `[all]`），镜像构建时需显式处理。

---

## 9. 真实代码实测核验记录与勘误（2026-11-21 机器核查回写）

> **核验时间**：2026-11-21 20:10 · **核验方法**：全仓 Python 脚本 AST 机械扫描 + 文件系统逐项定位 + 测试用例收集实测。

### 9.1 规模与层间关系实测核实
1. **全仓文件与 LOC 逐位匹配**：`src/uniquant/` 实测 240 文件 / 59,834 LOC，9 个子层统计与 §2.1 统计 100% 吻合。
2. **Brain 子包文件数勘误**：§2.1 备注中“wyckoff 16 / factors 14 / lppl 9”为历史口径。实测当前磁盘上：`wyckoff` 为 29 文件、`factors` 为 17 文件（12 顶层 + 5 个 `forensics/`）、`lppl` 为 11 文件，合计 73 文件完全精确。
3. **逆向边勘误与确认**：
   - §2.2 逆向边中的 `data -> services`（`data/__init__.py:56`）实为内部子包 `uniquant.data.services` 的 `LPPLDataService`，并非顶层 `services`，已在重构任务清单中更正为内部导入（非逆向依赖）。
   - 其余逆向边完全属实：`brain -> risk` 2 处（`fsm.py:214,219`）、`brain -> research` 2 处（`walk_forward_pipeline.py:21,320`）、`services -> research` 3 处（`scan_service.py:22-24`）、`shared -> brain` 1 处（`config_validator.py:144`）。
   - Brain 内部各引擎之间无直接跨引擎导入（AST 实测 cross-import 为空）。

### 9.2 路径与组件状态勘误
1. **脚本物理路径定位**：
   - `unified_daily_eod.py` 实际物理路径为 `scripts/daily/unified_daily_eod.py`（非 `scripts/canslim/`）。
   - `reconcile_qar.py` 实际物理路径为 `scripts/monitoring/reconcile_qar.py`。
   - `normalizer.py` 位于 `src/uniquant/data/utils/normalizer.py`（总行数恰好 323 行）。
   - `storage_manager.py`、`freshness_validator.py`、`resampler.py` 均位于 `src/uniquant/data/lake/`。
   - `delisted_ingestor.py`、`total_return_benchmark.py` 均位于 `src/uniquant/data/universe/`。
2. **写路径与组件现役确认**：
   - `delisted_ingestor.py:193-195` 实测已使用 `tmp_path + os.replace`。
   - `lppl/calculator.py`（665 行）并非废弃旧栈，已被 `brain/lppl/engine.py:409` 明确引入并由 `LPPLEngine` 消费，确认为现役核心组件。
   - `saga` 事务机在 `saga_compensator.py:80` 及 `orchestrator.py:99` 中实测默认 `db_path=":memory:"`，完全无持久化。
   - `daily_signal_qar.py:106-122` 在湖缺时静默采用 `4000.0` 假价格直接喂入 `plan_futures_hedging_structure`，全仓最重 Rule 4 违规属实；且第 139 行个股真实价格兜底为 `50.0`。
   - `unified_daily_eod.py:86-88` 确实使用 linspace 伪造行情，214 行硬编码 4 股，249-251 行硬编码 mock 持仓。
   - `data/lake/quotes/index/` 恰好包含 556 个 parquet 分片；`1mins` 与 `5mins` 物理目录在磁盘上为空（未生成）。
   - WSS 权重文件 `scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json` 真实存在，大小确为 78,547 字节。
