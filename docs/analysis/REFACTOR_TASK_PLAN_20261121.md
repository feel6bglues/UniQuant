# UniQuant 重构任务清单（定稿 v3，经 3 轮红蓝对抗）

> **日期**：2026-11-21 · **性质**：重构施工任务清单（决策依据 + 施工卡，未动任何生产代码）
> **来源**：[PRE_REFACTOR_DEEP_ANALYSIS_20261121.md](PRE_REFACTOR_DEEP_ANALYSIS_20261121.md) §7 的 16 任务 v0 → 自测核验（AST 精确消费者判定）→ **三轮红方对抗**（R1 事实层 / R2 排序半径层 / R3 执行现实层，共 30 处修正吸收）→ 本定稿。
> **行号基准**：2026-11-21 工作树（HEAD 8453393 + 本日文档变更）。开工日行号会漂移，以锚点语义为准。

---

## 1. 排序方法论（六原则，终版）

1. **部署阻断优先**：在目标环境（2026-11-21 已定：云主机 + pip 直装，无 Docker）跑不起来的作业免谈（T1/T3/N1 最前）。
2. **契约与数据真实性红线**：触碰冻结契约（GET_PRICE_RETURN_CONTRACT、9 列 parquet、GBBQ 八列、TradingSignal）的任务必须显式带守卫；**写湖任务必须依赖写路径原子化完成（T2a 先于 Wave 2）**；Rule 4 违规点（伪造数据/假价兜底）修复优先级等同部署阻断。
3. **依赖拓扑 + 同文件串行**：消费者先迁；**同文件任务显式串行**（T3→N1 同 freshness_validator.py；T10-直删A→T2b 同 data_fetcher.py；T2a 内含 T10-storage 子窗）。
4. **测试钉死同窗解**：改守卫测试与被守卫行为同一施工窗口（round8 SURVIVING_MODULES ↔ robustness 四件；chaos 7 用例 ↔ save_data 删除）。
5. **决策与施工分离**：裁决类任务（T6b/T7-裁决）从施工中剥离提前到 Wave 0——统一 Pipeline 是新装配体，不可押在未裁决的装配世界上。
6. **每任务：独立验收命令 + 回滚点 + 三横切义务**（文档同步点 / evidence manifest 入账规程 / AGENTS 轮次分流）。

## 2. 波次依赖图（重编号，消除 v2 跳号）

```
Wave 0  决策与部署阻断（可并行，注意 T3→N1 同文件串行）
  T1a 依赖声明+lockfile+Dockerfile ──> T1b CI 重标定（真网 job 裁决⑧）
  T3 配置消费断裂修复 ──串行──> N1 freshness SLA 重锚（同 freshness_validator.py）
  T7-裁决 装配二选一（用户，⑫ 之②）
  T6b 三链收敛语义设计定稿（用户裁决 ①⑨⑩，产出设计文档）

Wave 1  无争议清理与写路径治理（同文件串行：T10-直删A → T2b）
  T10-直删A 无争议死代码 + 13-14 测试文件改造（先改 round8 守卫）
  T8 逆向依赖清零 ×5（fsm→risk×2【R3-C5 收回】+ walk_forward 三文件 bridge 迁移 + config_validator 反射 + 导出面清理）
  T2a write_parquet 原子化 + 直写者收口 + T10-storage 旧接口删除（同窗；混沌测试改造）
  T2b src 构造器默认参显式化 ≥15 处（依赖 T3 + T10-直删A 串行）
  T2c scripts 层 8 处 cwd 相对构造清理
  T9a 落盘语义设计 + StateStore 接口 + 本地盘实现（与 T7 无耦合）

Wave 2  数据通道闭环（依赖 T1a + T3 + T2a——写湖必须踩原子写）
  T4 日线批量在线同步（含子项：tdxdata 指数市场码实测 + 指数湖 556 分片增量续灌）
  T5 分钟湖同步（前置①在线深度实测定标 ②分钟 parquet 列契约定义 + 分批/断点设计）
  T6c 失真清除（不依赖收敛：unified_daily_eod 合成数据/mock/硬编码 + daily_signal_qar 4000.0 假价 + H-A 裸 FileNotFoundError）

Wave 3  语义重设计（独占窗口，依赖 T6b 设计定稿 + T7-裁决）
  T6d QAR/H-A 接入统一出口（8 核心文件 ~3,466 LOC + 10 测试文件，多日语义重设计）
  T7-实施 按裁决实施装配改造
  T10-直删B sparse_convex / signal-db / signal-quality（等 T6b 裁决 ⑥⑦）

Wave 4  加固（依赖 T7-实施 / T9a）
  T9b 对象存储后端 ──串行──> T13 分布式锁（R3-C9）【单机 VM 场景降级：可选/按需】
  T11 HTTP 健康层 + prometheus 接线 | T12 重复逻辑归一 ×4 | T14 调度编排 | T15 UI 分离（可选） | T16 WSS 资产归仓 | N6 host 主备
```

---

## 3. 详细任务清单

> 格式：目标 → 原因（实际代码证据）→ 锚点 → 施工要点 → 验收命令 → 回滚 → 测试/横切面。

### Wave 0

#### T1a 依赖声明 + lockfile + 环境安装脚本（部署形态已定：云主机 + pip 直装，无 Docker）
- **原因**：tdxdata（第 20~24 轮主通道）/ polars（PIT 加载核心）/ czsc（缠论引擎）均未入 pyproject（唯一命中是 ruff per-file 注释 `pyproject.toml:63`）；三者现装用户 site-packages，`pip install -e ".[all,dev]"` 云主机必缺件。~~Dockerfile~~ **已按 2026-11-21 部署形态裁决（云主机 + pip 直装）剪除**——原 Dockerfile 承载的环境问题改由**环境安装脚本**（apt 系统库 + pip 层，幂等可重复执行）承载。
- **锚点**：`pyproject.toml:10-53`（dependencies + extras：dev/tdx/baostock/curl/report/js，`all` 不含 dev）。
- **要点**：tdxdata≥0.2.13、polars 入主依赖；czsc 进独立 extra 且**不入 `all`**（防 CI 收集面突变）。czsc 代价依据（R3-A5）：ta-lib≥0.6 的 manylinux wheel 已内置 C 库，x86_64 Linux 无系统级 C 库问题；真实代价 = 依赖树体积（~20 传递依赖）。**环境安装脚本三项**：① 系统库（apt/yum）：weasyprint→pango/cairo/gdk-pixbuf、libxml2；② 中文字体（matplotlib/报告生成）；③ 云主机 HOME 天然可写 → mootdx `~/.mootdx` 导入期写目录问题**自动消解**（tests/conftest.py:29-34 无需任何特殊处理）。
- **验收**：`pip install -e ".[all,dev]"` 解析成功 + `pip check` + 环境安装脚本在干净 VM/沙盒一次跑通 + 本地 pytest 收集数与 CI 口径一致。
- **回滚**：git 分支；lockfile 生成需网络，低风险。

#### T1b CI 重标定
- **原因**：改依赖集必然扰动 CI 基线；覆盖率地板按"CI-faithful 依赖集"标定（test.yml:94-115 注释即策略），地板 84（test.yml:147）。
- **裁决 ⑧（R3-A2 修正 + 2026-11-21 用户拍板=A）**：v2"26 个 tdxdata 测试从 skip 变 run"**前提为假**——实测 `tests/data/test_tdxdata_online.py` 26 用例零 skip 标记、假客户端不触网，**当前 CI 已在跑**。**已裁决：新增 nightly 定时真网 job**（装 tdxdata 跑在线兜底/xdxr/财务路径；schedule 触发、不阻塞 PR、失败飞书告警——提前感知 tdx.com.cn/tdxfin 无 SLA 通道的腐坏）。
- **验收**：三口径（本机/CI 数据环境/真实 CI）全绿 + 地板数字按 round-9 政策（低口径-2pt）重推。

#### T3 配置消费断裂修复
- **原因**：① `data_fetcher.py:184` 无参构造 `TdxDataOnlineSource()`，config 的 `tdxdata_online.config.host: 101.35.121.35`（config.yaml:194）零消费，host 只在验证脚本显式传参生效；② `freshness_validator.py:104` 读 `cfg.get("tdx",{}).get("path")`，实际配置在 `base.tdx.path`（config.yaml:18 嵌套）——该分支恒 miss。
- **要点**：host 接线走 config_loader 既有 env 机制（`UNIQUANT_` 前缀 + 别名表，config_loader.py:11-77，**机制已完备只差接线**）；保持 `TdxDataOnlineSource()` 无参构造向后兼容 + `tests/test_get_price_online_fallback.py` 的 `tdxdata_online_source` 属性注入面不变。
- **验收**：host 注入单测 + `pytest tests/test_data_fetcher_init_fault_tolerance.py tests/test_get_price_online_fallback.py`；C6 线程不变量：16 线程双检锁语义（tdxdata_online.py:64-81）+ `_price_cache` 线程安全不恶化。
- **回滚**：单文件 revert。

#### N1 freshness SLA 重锚（T3 后串行，同文件）
- **原因**：T3 修完键错位后读到的 `base.tdx.path` 仍指向容器内不存在的 Wine 路径——L1/L2 SLA 在云上恒死（freshness_validator.py:94-112 双级兜底全 Wine）。**这是 T3 的真上限，单列任务防"修了键没修命"**。
- **要点**：重锚到 tdxdata 服务端最新日期/在线日线对账，替代 `find_tdx_max_date` 的 .day 尾 32 字节比对；`scripts/maintenance/check_freshness_sla.py:101`（`StorageManager()` 无参构造）划归本任务独占。
- **验收**：`pytest tests/test_storage_freshness_sla.py`（:20-35 mock 重写后全绿）+ 无 Wine 目录容器内 SLA 可判定。
- **回滚**：保留旧 Wine 路径分支为最后候选。

#### T7-裁决 装配二选一（用户，半天）
- **原因**：ServiceContainer 唯一生产调用方是 UI（dashboard.py:631-634），全部生产脚本手工装配——两个平行世界；Wave 1-2 的新交付物（T4/T5 脚本、T2c 触碰的脚本、N1）都要回答走哪套，后裁决 = 二次改造（R2-P5）。
- **选项**：A. 生产脚本走 ServiceContainer（懒初始化改造：StorageManager mkdir×7@构造、TradeCalendarManager 构造期可能触网、DataService→MootdxLocalSource 探测本地 TDX）；B. 容器降为 UI 专用 + 抽轻量 bootstrap 供脚本。
- **红线**：test_round17:58 钉死 `service_container` 必须存在——降专用可、物理删除不可。

#### T6b 三链收敛语义设计定稿（用户裁决，产出设计文档）
- **原因**：三套平行决策体系（AnalysisService 七段链 / CNMM-QAR 直连【不产 TradingSignal、不经仲裁器】/ H-A 直连）；**期指腿是账户级名义头寸**（orchestrator.py:44,154-163，hedge_ratio=0.75 / 3 PB 账户），而 `TradingSignal.action` 仅 `"BUY"|"SELL"|"HOLD"` 自由字符串（interfaces.py:155）、`arbitrator.py:155` 只放行 BUY/SELL——**单票信号管道无法无损承载账户级期指腿**（R3-A4）。
- **设计输入三事实**：① action 白名单无 SHORT/HEDGE/leg 字段；② 仲裁器过滤语义；③ 双 kill switch 体系并存（SharedKillSwitch 进程单例 vs orchestrator 内嵌 `enable_kill_switch/quarantine_kill_threshold` :52-58）。
- **裁决 ①⑨⑩**：① QAR 保留独立 vs 收进仲裁框架（承载机构 75/25 对冲语义，产品决策）；⑨ 期指腿表达二选一——扩展 TradingSignal 契约（高风险冻结契约，全仓改动面） vs 期指腿留在账户级编排器不经仲裁器（仲裁器仅管股票腿）；⑩ 双 kill switch 归一 or 并存定义。
- **验收**：设计文档落 docs/analysis/ + 用户书面裁决 + 回写 T6d/T10-直删B 范围。
- **裁决输入更新（2026-11-21 用户拍板）**：⑨=B、⑩=B、①=C 已全部锁定——设计文档在"QAR 股票腿收进统一管道（产 TradingSignal 走仲裁器）+ 期指腿留账户级编排器 + 两级 kill switch（L1 全局落盘 / L2 轨隔离）"框架内落笔，不再论证契约扩展与合并方案；**无悬空裁决，T6b 从裁决文档降为落地设计文档**（细化股票腿接线：cnmm_qar_strategy 打分逻辑 → AnalysisService/Pipeline 的接入缝、daily_signal_qar CLI 的改造形态、TradingSignal 映射表）。

### Wave 1 [已完成 2026-11-21]

> **Wave 1 验收状态**: **全项通过 (PASS)**。
> - T10-直删A: 剪除 12 个废弃模块（signal 5件套、hands robustness 4件套、env_config、structural、drawdown），DataFetcher 实例属性瘦身，StorageManager 废弃接口清理，死代码守卫更新全绿。
> - T2a 写路径原子化: `write_parquet` 采用 FileLock 内 `tmp + os.replace` + 异常清理；`total_return_benchmark.py` 原子化；混沌故障注入测试通过。
> - T8 逆向依赖清零: `brain -> risk` 纯协议注入；`brain -> research` ledger 解耦；`shared -> brain` 反射化；AST 静态逆向边清零；docstring 漂移清除。
> - T2b & T2c 构造器与 cwd 治理: `StorageManager` / `DataFetcher` / `ResultStore` / `LoggerFactory` / `CacheFactory` 默认路径绝对化消除 cwd 依赖，实测 `/tmp` 启动无感；delisted 合成退市数据隔离声明（reserved=65536）。
> - T9a 状态落盘与崩溃恢复: `StateStore` 契约 + `DiskStateStore` 本地盘原子实现；`SharedKillSwitch` 状态持久化落盘与 Fail-Closed 恢复；产出规范文档 `docs/analysis/CRASH_RECOVERY_AND_STATE_SEMANTICS_20261121.md`。

#### T10-直删A 无争议死代码剪除 (已完成)
- **直删面**（AST 零外部消费者实测）：signal models/normalizer/aggregator（db+quality 留 Wave 3 裁决）；risk structural + drawdown（**连带 risk/__init__.py:14 无条件导入改守卫**，:32/:43 已是 try 守卫模式可仿照）；robustness 四件套（**先改 test_round8:79-82 SURVIVING_MODULES**）；env_config；normalize_stock_data 族；LegacyDataFetcher/create_fetcher；StorageManager 旧接口 save_data/save_factor/read_local_raw（src 零生产调用，**与 T2a 同窗施工**）。
- **裁决 ⑪（R3-A7 + 2026-11-21 用户拍板=A）**：**本窗只删实例属性**（:189-199 三个属性，42 个 chaos 测试全存活）；DataCleaner/DataValidator 模块级废弃与否升格 Wave 3 小裁决（clean→validate→adjust 子系统整体废弃，与 T12 同窗）。
- **测试改造面 13-14 文件**：test_signal / test_signal_db / test_e2e_integration_qa / test_backtest_advanced / hands/backtest/test_robustness_and_matching_unit / test_phase4_1_remediation / test_p0_signal_chain_patch / test_drawdown_analyzer / shared/test_optimal_params / data/test_normalizer / round8 守卫 / round17 守卫 / risk/__init__ / **tests/test_data_chaos_qa.py（7 个用例直调 save_data/save_factor：440/446/449/452/455/502/506 附近——R1 遗漏、R3-A1 补收）**。
- **覆盖率地板步骤（R3-C4）**：删的都是有专属测试的模块，总覆盖率方向不可先验判定——**同依赖集前后实测** + 按 round-9 政策重推地板 + 同 PR 改 test.yml `--cov-fail-under`。
- **验收**：`pytest tests/ -q` 全绿 + ruff + round8/9/17 守卫全绿 + 覆盖率口径报告。

#### T8 逆向依赖清零 ×5（R3-C5 收回 fsm 修复位）
- **①② brain→risk**：`brain/fsm/fsm.py:214`（HistoricalSimulationRisk）、`:219`（PositionSizer）→ 改 `shared/interfaces.py:587` 已有 `PositionSizerProtocol` 注入，DecisionBrain 变纯注入。
- **③ brain→research**：`brain/factors/walk_forward_pipeline.py:21,320`——**迁移单元是 3 文件**（walk_forward_pipeline + analyzer.py + composer.py，实测依赖闭包）；**走 bridge 模式**（research/ledger/bridge.py:13 明文 research 不 import brain，原样迁入=制造新逆向边）；连带 5 个 factor_mining 脚本 import + 4 个测试文件（test_walk_forward_pipeline / test_brain_boundary_qa / chaos 边界 / test_research_ledger_bridge）。
- **④ shared→brain**：`shared/config_validator.py:144` FactorRegistry 反射化（连带 shared/test_config_validator_factor.py）。
- **⑤ 导出面清理**（非逆向边）：data/__init__.py:5-6 realtime 桥残留 + sources/__init__.py:4 "10 个数据源"漂移。
- **文档**：00_architecture_map 逆向边表更新。

#### T2a 写路径原子化（含 T10-storage 子窗）
- **原因**：真活写路径 `write_parquet`（storage_manager.py:139-146）是 **FileLock 内裸 `df.to_parquet` 非原子直写**——崩溃留半截分片；v0 把锚点打在零调用的 save_data 上是错位（R1-F3）。**更正**：delisted_ingestor.py:180-195 实测已是 tmp+os.replace（v1 口径错误），仅剩"绕过治理"问题。
- **收口面**：write_parquet → tmp+os.replace；total_return_benchmark.py:98-101 裸 to_parquet + **calculate_dividend_leakage_spread 隐式写者（persist=True 再生落盘）**（R2 发现）。
- **验收（R3-A1 可执行版）**：单元级故障注入——monkeypatch `DataFrame.to_parquet` 中途抛异常/`os._exit(1)`，断言旧分片逐位完好 + 目录无 `*.tmp` 残留（进 test_data_chaos_qa.py 现有文件）；真湖验收用 per-file sha256 前后对照（capture_lake_baseline.py 是摘要级、无 per-file digest——加 digest 模式或脚本外 sha256sum）；受影响分片对照。
- **回滚**：git 分支；新旧写者共用同一 `.parquet.lock` 路径互斥不破坏；无湖 git，sha256 清单是唯一完整性证据。
- **横切**：产 JSON → results/migration/ → git add → `evidence_manifest.py build`（规程见 §5）。

#### T2b src 构造器默认参显式化（T3 后 + T10-直删A 后串行，R3-C6）
- **面（R2-P2 实测 ≥15 处真 cwd 相对）**：storage_manager:59 / data_fetcher:156,560 / trade_calendar_manager:74 / data_pipeline_service:16 / scan_service:101,747 / result_store:42 / logger_factory:87 / cache_factory:61 / backends:177 / config_schema 6 处。config_loader 默认经 `_root_dir` 解析非 cwd 相对，不混计。
- **验收**：从 `/tmp` 启动 CLI 跑通（cwd 无关性测试）。
- **注**：data_pipeline_service 若随 T10-直删A 裁决删除（⑪），本项相应缩面。

#### T2c scripts 层 cwd 相对构造清理
- **面**：run_market_scan.py:12 / wyckoff_calibrate ×2 / wyckoff_ab_compare ×2 / seed_multi_period_data.py:33 / run_gp_mining.py:90（check_freshness_sla.py:101 已划 N1）。（R1-F7 更正：daily_signal_ha 无此问题，其输出用 PROJECT_ROOT 绝对路径。）
- **裁决 ③（2026-11-21 用户拍板=A）**：delisted_ingestor 合成退市 K 线**保留** + 显式标记 + 迁移至隔离命名空间（`data/lake/quotes/daily_synthetic/` 或 reserved 强制位）+ 文档声明"合成数据仅防幸存者偏差、不可用于真实价格分析"+ StorageManager 治理化收口；开工日先核实 reserved=65536 是否本就是标记位。

#### T9a 落盘语义设计 + StateStore 接口 + 本地盘实现
- **原因**：FSM 状态 `data/state/fsm_state.json`+FileLock（fsm.py:703-717）；**saga = `:memory:` 完全无持久化**（saga_compensator.py:80 默认参 + orchestrator.py:99 显式传参）——崩溃即失忆，比"本地文件迁后端"更严重，先设计落盘语义；kill switch 状态不落盘重启即复位。
- **要点**：FSM 状态路径已可注入（fsm.py `_get_state_file_path` 支持 state_file 参数）——接口抽象不依赖 T7 装配裁决（R2-P6），仅 DI 接线（T9b）等 T7。
- **验收**：StateStore 接口 + 本地盘实现 + kill switch 状态落盘单测；崩溃恢复语义文档。

### Wave 2（已完成 2026-11-22）

#### T4 日线批量在线同步（含指数子项）[已完成]
- **原因**：湖写唯一通路仍是 Wine `sync_local_tdx_day.py`；在线批量等价物实测不存在（maintenance/ 只有 sync_online_financial / sync_online_gbbq）。
- **攻克突破**：攻克 tdxdata 新协议指数解析缺陷（指数 K 线多出 4 字节 up_count/down_count 指针偏移与大数据量 zlib 压缩解包），实现 `TdxDataOnlineSource` 支持指数与显式市场码解析。
- **交付落地**：`scripts/maintenance/sync_online_daily.py`（多线程并发、9 列严格契约、snappy parquet、tmp+os.replace 原子落盘、断点指纹更新、支持指数与个股）；单测 `tests/scripts/test_sync_online_daily.py`（8 passed）；实测续灌 000300.SH, 600519.SH, 000001.SZ 至 2026-11-20，存证于 `results/migration/online_daily_sync_summary.json`。

#### T5 分钟湖同步 [已完成]
- **定标与列契约**：修正 `tdxdata_online.py` docstring 定标为 10.5 个月/10,224 根；锁定 8 列分钟 schema `[datetime, open, high, low, close, volume, amount, code]`。
- **交付落地**：`scripts/maintenance/sync_online_minute.py`（多线程并发、8 列契约、atomic 写、指纹管理、支持 5min/1min）；单测 `tests/scripts/test_sync_online_minute.py`（8 passed）；实测 000300.SH 与 600519.SH 5min 续灌，存证于 `results/migration/online_minute_sync_summary.json`。

#### T6c 失真清除 [已完成]
- **清除非法假价**：
  - `unified_daily_eod.py`：移除 date_range + linspace 合成假价格，基准缺失直接抛出 `FileNotFoundError` Fail-Fast；宏观过滤无记录抛出 `ValueError`；`--holdings-json` 入参显式化。
  - `daily_signal_qar.py`：移除 4000.0 期指基准兜底假价；移除 50.0 股票假价与 1 亿 ADV 兜底，湖缺失直接 `FileNotFoundError`/`ValueError` Fail-Closed。
  - `daily_signal_ha.py` & `ha_unified_adapter.py`：基准行情缺失显式抛出 `FileNotFoundError`。
  - `reconcile_qar.py`：移除 50.0 兜底假价，缺失直接抛出异常。
- **单测与行为验证**：`tests/scripts/test_unified_daily_eod.py`、`test_daily_signal_qar.py`、`test_reconcile_qar.py` 全绿。

### Wave 3（已完成 2026-11-22）

#### T6d QAR/H-A 接入统一出口（多日语义重设计，独占窗口）[已完成]
- **影响面**：8 核心文件 ~3,466 LOC（cnmm_qar_strategy 570 / orchestrator 370 / analysis_service_v2 640 / arbitrator 425 / adapters 667 / daily_signal_qar 229 / ha_unified_adapter 307 / unified_daily_eod 258）+ 10 测试文件（test_cnmm_qar_strategy_and_backtest / scripts/test_daily_signal_qar / scripts/test_reconcile_qar / test_phase2_institutional_execution_orchestrator / test_signal_arbitrator / test_cffex_twap_saga_production / test_ha_rotation_buffer / test_bp_ha_portfolio / scripts/test_unified_daily_eod / scripts/test_ha_engineering）。
- **完成项**：
  - `QARAdapter` 实现于 `src/uniquant/signal/adapters.py` 并注册至默认 registry。
  - `SignalArbitrator` 扩展 `ENGINE_PRIORITY`（"qar": 3），重构 `arbitrate` 支持 `(symbol, date)` 横截面多标的独立优选。
  - 四生产入口（`unified_daily_eod.py`, `daily_signal_qar.py`, `daily_signal_ha.py`, `ha_unified_adapter.py`）接入 L1 `SharedKillSwitch` 拦截防御。
  - QAR 股票腿与 H-A Top30 标的统一生成 `TradingSignal` 经 `SignalArbitrator` 仲裁输出，期指腿保持在 `orchestrator` 微观执行。
  - 裁决 ⑤A 落地：`calculator.py`（生产核心）与 `fitting_optimizer.py`（研究专用）架构边界文档化注释。

#### T7-实施 按裁决实施装配改造 [已完成]
- **完成项**：
  - `ServiceContainer` 构造函数改造为纯 `register_factory` 懒加载，消除初始化 IO 开销，降级为 UI 专用。
  - 新建轻量服务组装器 `src/uniquant/services/bootstrap.py`（<50ms 启动，规避全局单例）。
  - 新增 `tests/services/test_bootstrap.py`，全量验证独立性与参数透传。

#### T10-直删B（⑦ 已裁决全删；⑥ 默认剪除、T6b 可翻转）[已完成]
- **完成项**：
  - 物理删除死模块 `src/uniquant/risk/sparse_convex_optimizer.py` 与连带单测 `tests/test_sparse_convex_optimizer.py`。
  - 清理 `src/uniquant/risk/__init__.py` 导出面，保持风控核心四件套纯净。
  - `signal/db.py` 与 `signal/quality.py` 已于 Wave 1 归档删除。

### Wave 4

- **T9b**：对象存储后端 + DI 接线（接线点等 T7）——**与 T13 串行**（R3-C9）。**部署形态降级注（2026-11-21：云主机 + pip 直装）**：单机 VM 场景下本地盘 StateStore + 本地 FileLock 已满足需求，本项与 T13 降为**可选/按需**（多机扩展或湖上对象存储时才启用）；湖迁移 = 一次性 rsync/scp 3.3GB parquet 到云主机盘。
- **T13**：FileLock（storage_manager.py:138）→ 分布式锁（对象存储条件写 / Redis）。
- **T11**：HealthService 三层探针（health_service.py:59-125 已有逻辑）补 HTTP 端点 + `ensure_prometheus_server` 接线（prometheus_metrics.py:23，现全仓零调用；config observability 段字段同步激活）。
- **T12**：代码归一化 ×5→1（storage_manager/stock_metadata_manager/import_financial/dynamic_pit_universe/dynamic_pit_loader）；市场后缀推断 ×3→1；量纲机制 ×3→1（harmonize_local_volume_unit / LOT_TO_SHARE / VOLUME_UNITS 表）；resampler 周/月去重（:31-141）。
- **T14**：cron 假设显式化 + signal JSON→reconcile 文件交接改编排。
- **T15（可选）**：UI 分离——ui→services 单向依赖已是起点；dashboard.py 1,568 行。
- **T16**：WSS JSON（78,547 字节，scripts/wyckoff_multitf/output_v4/）迁包内/对象存储 + config.yaml:387 同步 + engine.py:147-164 读取路径适配。
- **N6**：tdxdata host 主备列表（默认 101.35.121.35 + 东证节点，config.yaml:196 注释已留伏笔）——借 T3 注入缝。

---

## 4. 用户裁决点集中清单（12 项）

> **裁决记录（2026-11-21 用户拍板，12/12 全部收口）**：①C · ②B · ③A · ⑤A · ⑥默认B（T6b 可翻转）· ⑦A · ⑧A · ⑨B · ⑩B · ⑪A（模块级升 Wave 3 小裁决）· ⑫A · ④=随①C保留。

| # | 裁决点 | 所属任务 | 时机 | 裁决（2026-11-21） |
|---|---|---|---|---|
| ① | 三链收敛方向：QAR 保留独立 vs 收进仲裁框架 | T6b | Wave 0 | ✅ **C（2026-11-21 AskUserQuestion 拍板）**：QAR 股票腿（选股/打分/组合构建）收进 AnalysisService 统一管道，产出 TradingSignal 走仲裁器；期指腿留 orchestrator（⑨B） |
| ② | 装配二选一：脚本走容器 vs 容器降 UI 专用 + bootstrap | T7-裁决 | Wave 0 | ✅ **B**：容器降 UI 专用 + 抽轻量 bootstrap，脚本按需组装 |
| ⑨ | 期指腿表达：扩展 TradingSignal 契约 vs 留账户级编排器不经仲裁器 | T6b | Wave 0 | ✅ **B**：期指腿不经 TradingSignal，留账户级编排器，仲裁器仅管股票腿 |
| ⑩ | 双 kill switch 归一 or 并存 | T6b | Wave 0 | ✅ **B**：L1 全局紧急停机（SharedKillSwitch，T9a 落盘）+ L2 策略轨隔离（orchestrator 内嵌），写进风控文档、不合并 |
| ⑧ | 是否新增 tdxdata 真网验收 CI job | T1b | Wave 0 | ✅ **A**：nightly 定时真网 job，不阻塞 PR，失败飞书告警 |
| ⑪ | 构造即弃三件：删实例 vs 删模块 | T10-直删A | Wave 1 | ✅ **A**：Wave 1 先删实例；clean→validate→adjust 子系统整体废弃与否升格 Wave 3 小裁决（与 T12 联动） |
| ③ | delisted_ingestor 合成退市 K 线去留 | T2c/T6 | Wave 1-2 | ✅ **A**：保留 + 显式标记 + 隔离命名空间（`data/lake/quotes/daily_synthetic/` 或 reserved 强制位）+ 文档声明"仅防幸存者偏差" + StorageManager 治理化收口 |
| ⑤ | LPPL calculator 新旧栈定位 | 随 ① | Wave 3 | ✅ **A**：calculator=生产核心，fitting_optimizer=研究专用并加注释边界，维持现状 |
| ⑦ | signal/db + quality 去留 | T10-直删B | Wave 3 | ✅ **A**：全删；统一管道若需持久化，在 T9a StateStore 按云原生重做，git 历史留档 |
| ⑥ | sparse_convex_optimizer 接回与否 | T10-直删B | Wave 3 | ⚠️ 默认 **B 剪除**（T6b 设计明确需要则翻转） |
| ④ | cffex/twap 去留（消费者=orchestrator） | 随 ① | Wave 3 | ✅ **保留**（随 ①C：期指腿留编排器，cffex/twap/saga/FeeLedger 是其执行核心，Phase 2 资产不裁） |
| ⑫ | T5 深度定标后口径修正 + 历史归档边界 | T5 | Wave 2 | ✅ **A**：在线=近期增量；深度历史=Wine .lc5 一次性播种 + 此后在线增量；定标后修 docstring |

### 裁决后果与解锁（2026-11-21，12/12 收口后）

- **部署形态裁决（2026-11-21，推翻 2026-11-20"容器/Serverless"初选）**：**云主机 + pip 直装 + systemd/cron**。T1a 剪除 Dockerfile（改环境安装脚本）；mootdx HOME 问题自动消解；**T9b/T13/T14 单机 VM 场景动机减弱，降级为可选/按需**（本地盘 + 本地 FileLock + cron 即满足）；numba `cache=True` 在可写 VM 盘正常工作（Serverless 冷启动顾虑解除）。
- **全部波次解锁，无阻塞裁决**：Wave 0-4 全部可开工。
- **Wave 0**：T1a/T1b（⑧A 定型）/T3/N1/T7-方向（②B）/T6b 设计输入齐备且方向锁定（①C+⑨B+⑩B）——T6b 从"裁决文档"降为"落地设计文档"（在已定框架内细化股票腿接线方案）。
- **Wave 1**：T10-直删A 按 ⑪A 轻删；T2a/T2b/T2c（含 ③A 合成数据隔离）/T8/T9a。
- **Wave 2**：T4/T5（⑫A 定设计）/T6c。
- **Wave 3**：T6d 方向=①C 锁定（QAR 股票腿收进统一管道 + 期指腿留编排器）；T7-实施=②B；T10-直删B=⑦A 全删 signal/db+quality + ⑥ 默认剪除 sparse_convex（T6b 细化时唯一可翻项）；cffex/twap/saga/FeeLedger **保留**（④）。
- **Wave 4**：T9b/T13 串行 + T11-T16 + N6，无裁决依赖。
- **⑤A 落地槽**：LPPL calculator/fitting_optimizer 边界注释，并入 Wave 3 开工首日（半小时级）。
- **⑪ Wave 3 小裁决**：clean→validate→adjust 子系统整体废弃与否，与 T12 同窗处理。

## 5. 横切义务（每任务通用）

- **Step-0 纪律**：`git status --short`（当前树有未提交文档变更）→ 干净分支 → 读 CLAUDE.md 十规则。当前树脏文件：AGENTS.md / docs/index.md / round8/9/17 守卫测试（今日 AGENTS 瘦身重组）+ 3 个未 track 文档——**开工前先提交或 stash**，防与重构 diff 混杂。
- **evidence manifest 三步规程**（R3-A3）：产 JSON → 置 `results/migration/`（.gitignore 白名单已含，免改）→ `git add` → `python scripts/maintenance/evidence_manifest.py build` → CI verify 绿。**注意：manifest 只覆盖 git ls-files 追踪文件，不 add = verify 静默不报**。
- **文档同步映射**：T1→AGENTS Current State 横幅 + index 依赖口径；T2→02_data_system 存储语义；T3/N1→02_data_system SLA；T4/T5→AGENTS 通道表；T6→05_signal+03_brain；T7→01_services；T8→00_architecture 逆向边表；T10→**AGENTS Layer Responsibilities 表刷新（实测陈旧：表 42/32/60/22/26 vs 实测 40/40/73/24/27，且无过期横幅——违反自身维护规则）**；T16→config+04_factor。
- **AGENTS 轮次分流**：每 Wave ≥1 轮次块进 docs/archive/AGENTS_CHANGELOG_ROUNDS.md（遵守 2026-11-21 维护规则，AGENTS.md 只留最近 2 轮）。

## 6. 三轮红蓝对抗记录

### R1 事实性攻击（8 推翻 + 6 遗漏 + 7 冲突）
F1 幽灵逆向边（data/services 子包与顶层 services 撞名，T8 ×4→×3）· F2 LPPL calculator.py 现役（engine.py:483-485 实用）· F3 T2 锚点打在零调用死接口、活路径 write_parquet 漏列 · F4 saga 实为 `:memory:` 零持久化 · F5 分钟深度口径自相矛盾（2 vs 10.5 个月）· F6 T4 锚点 135-137 是 gbbq 写非日线编排 · F7 `./data` 张冠李戴（真凶 run_market_scan/seed_multi_period）· F8 risk/__init__.py:14 无条件导入。遗漏 N1-N6；冲突 C1-C7（T2×T10 锚点重叠、round8/17 守卫钉死、T6 缺指数前置、线程不变量、CI 地板）。

### R2 排序/半径攻击（8 排序推翻 + 爆炸半径表 + 5 组拆分 + 3 横切）
P-1 N1×T3 同文件 · P-2 T2 路径清单不完整（6 处→≥15 处，3 倍低估）· P-3 T2×T8 config_validator 同文件 · P-4 C5 双重错置（**指数湖已存在 556 分片是续灌非播种**；daily_signal_qar 4000.0 假价升为最重 Rule 4 违规；归 T4）· P-5 T7-裁决提前 Wave 0 · P-6 T9 与 T7 仅 DI 接线耦合 · P-7 T10 三拆 + walk_forward 迁移单元 3 文件 + bridge 模式防新逆向边 · P-8 Wave 2 必须依赖 T2a（写湖踩原子写）。半径：T6 = 多日语义重设计（8 文件 3,466 LOC + 10 测试）；T2 = 3 倍低估。横切：文档同步/manifest/AGENTS 轮次。

### R3 执行现实性攻击（4 阻断 + 3 补强 + 2 修正 + 4 一致性 + 1 纪律）
A1 T2a 崩溃验收无基建 → 故障注入方案 + chaos 7 用例补收 · A2 T1b 前提证伪（26 用例已在跑）→ 真网 job 裁决重写 · A3 manifest 入账需三步规程（不 git add = 静默不入账）· A4 TradingSignal 无腿字段 + 仲裁器过滤 + 双 kill switch → T6b 输入补全 + 裁决 ⑨⑩ · A5 czsc/ta-lib manylinux wheel 已内置 C 库（旧判断过时）· A6 T5 缺分批断点（~72k 请求多小时）· A7 构造即弃三件删实例 vs 删模块（裁决 ⑪）。C5 **v2 丢失 brain→risk×2 修复位 → 收回 T8**；C6 T2b×T10 串行边；C7 Wave 跳号重排；C1 AGENTS 层表陈旧无横幅；C4 T10 覆盖率方向只能实测裁决；C9 T9b↔T13 串行边。step-0 干净分支纪律。

## 7. 诚实边界

- 本清单未执行任何施工；行号基于 2026-11-21 工作树，开工日以锚点语义为准。
- T6d 影响面的 10 个测试文件名未逐一存在性核验（R3 诚实边界），T6d 开工首日先核验。
- T10 覆盖率地板方向（删除后升或降）无法纸面判定——执行期同依赖集前后实测。
- ta-lib 非 x86_64 平台 wheel 覆盖未验证；lockfile 生成需网络。
- 裁决点 ①-⑫ 已于 2026-11-21 全部收口（见 §4 裁决记录）；唯一保留的可翻项=⑥（sparse_convex 剪除为默认，T6b 设计明确需要组合级稀疏投影时可翻转接回）。

---

## 8. 真实代码实测核验记录（2026-11-21 机器核查回写）

> **核验时间**：2026-11-21 20:10 · **核验状态**：✅ **全部 100% 核准闭环（READY）**

1. **测试资产存在性核验（10/10 闭环）**：
   - T6d 影响面的 10 个测试文件在磁盘上逐一核验，全部存在：
     - `tests/test_cnmm_qar_strategy_and_backtest.py` ✅
     - `tests/scripts/test_daily_signal_qar.py` ✅
     - `tests/scripts/test_reconcile_qar.py` ✅
     - `tests/hands/backtest/test_phase2_institutional_execution_orchestrator.py` ✅
     - `tests/test_signal_arbitrator.py` ✅
     - `tests/test_cffex_twap_saga_production.py` ✅
     - `tests/test_ha_rotation_buffer.py` ✅
     - `tests/test_bp_ha_portfolio.py` ✅
     - `tests/scripts/test_unified_daily_eod.py` ✅
     - `tests/scripts/test_ha_engineering.py` ✅
2. **守卫与混沌测试锚点核实**：
   - `tests/test_data_chaos_qa.py` 第 440-514 行确有 16 处调用已弃用的 `save_data` / `save_factor`（覆盖 7-8 个独立测试用例），T2a/T10 同窗改造锚点核实无误。
   - `tests/data/test_tdxdata_online.py` 26 个用例全部基于 `_FakeClient`，零 skip 标记，当前 CI 确实已全绿运行（裁决 ⑧ 修正成立）。
   - `tests/test_round8_pruned_modules_absent.py` 第 64-77 行的 `SURVIVING_MODULES` 确实钉死 robustness 4 件套（T10-直删A 需同窗修改守卫测试属实）。
   - `tests/test_round17_pruned_modules_absent.py` 第 71-82 行与第 105 行确实断言了 `ServiceContainer`（T7 降为专用、不可物理删除的红线属实）。
3. **脚本物理路径确认**：
   - `scripts/daily/unified_daily_eod.py`（物理路径位于 `scripts/daily/`，非 `canslim/`）。
   - `scripts/monitoring/reconcile_qar.py`（物理路径位于 `scripts/monitoring/`）。
   - `scripts/canslim/daily_signal_qar.py`、`daily_signal_ha.py`、`ha_unified_adapter.py`（物理路径位于 `scripts/canslim/`）。
4. **关键数据违规点代码锚点确认**：
   - `scripts/daily/unified_daily_eod.py:86-88` linspace 伪造数据、214 行硬编码推荐股池、249-251 行 mock 持仓。
   - `scripts/canslim/daily_signal_qar.py:106-122` 采用 4000.0 假指数点位兜底并喂入期指风控对冲计算、139 行采用 50.0 假个股价格。
   - `scripts/canslim/daily_signal_ha.py:110-113` 与 `ha_unified_adapter.py:80-88` 裸 FileNotFoundError。
   - `orchestrator.py:44, 154-165` 75/25 机构账户级对冲名义头寸，与 `interfaces.py:155`（BUY/SELL/HOLD）及 `arbitrator.py:155` 契约限制完全吻合。
5. **依赖声明缺口核实**：
   - `pyproject.toml:10-53` 确无 `tdxdata`、`polars`、`czsc`（第 63 行仅为 lint per-file-ignore 注释）。
6. **最终裁决与施工准备结论**：
   - 裁决 ①-⑫ 已全部收口锁定；部署形态确定为云主机 + pip 直装（免 Docker）；全量测试收集数为 4,124 项；本清单已具备直接施工条件。
7. **Wave 3 实施核实与门禁记录（2026-11-22 实测）**：
   - **T10-直删B 闭环**：物理移除 `sparse_convex_optimizer.py` 与 `test_sparse_convex_optimizer.py`，净化 `risk/__init__.py`。
   - **T7-实施 闭环**：`ServiceContainer` 构造函数纯懒加载化，新增 `services/bootstrap.py` 轻量依赖装配器（单次装配耗时 <50ms），配套单测 3/3 绿，容器单测 8/8 绿。
   - **T6d 闭环**：
     - 实现 `QARAdapter` 并注册，扩展 `SignalArbitrator` 优先级表（`qar: 3`），重构 `arbitrate` 支持 `(symbol, date)` 横截面多标的独立仲裁。
     - 4 个生产入口接入全局 L1 `SharedKillSwitch`；QAR 股票腿与 H-A Top30 统一由 `SignalArbitrator` 仲裁输出，期指腿留在 `orchestrator` 执行。
     - ⑤A 落地：LPPL `calculator.py`（生产核心）与 `fitting_optimizer.py`（研究专用）架构边界文档化注释。
   - **门禁核验**：Wave 3 影响测试集 195+ 用例全绿；`ruff check src/ tests/ scripts/` All checks passed!；`evidence_manifest.py verify` no drift。
