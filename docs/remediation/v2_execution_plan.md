# UniQuant v2.0 — 生产级修复执行计划 v2

> 生成日期: 2026-07-07 | 基于 6 轮元分析 + 文件冲突矩阵 + 3 工程师并行编排
> 来源: `docs/reanalysis/Z_remediation_worksheet_red_blue_analysis.md` 经对抗验证后的优化版本
> 总任务: 37 (31 原始 + 6 新增) → 34 执行单元 (3 组合并)
> 总工时: 122 人时 | 总挂钟时间: 49h (6 个工作日@3 人)
> 执行前必读: `docs/remediation/v2_remediation_worksheet.md` (原始问题描述) + `CLAUDE.md` (编码规则)

---

## 1. 执行原则

| # | 原则 | 说明 |
|---|---|---|
| 1 | **每任务单文件** | 每项任务产出独立的 git commit, 不混合改动 |
| 2 | **先测试后修复** | 每项修复前先写失败测试 → 修复 → 测试通过 |
| 3 | **阶段验收门禁** | 每阶段结束后运行指定的验收命令, 全部通过才进入下一阶段 |
| 4 | **冲突先串后并** | 冲突组的并行经文件冲突矩阵预先验证, 串行依赖严格遵守 |
| 5 | **回滚就绪** | 每个 commit 可单独 revert, 不产生跨任务回滚依赖 |

---

## 2. 冲突组矩阵 (所有任务→文件映射)

### 高冲突文件 (3 个以上任务修改)

| 文件 | 任务 | 冲突原因 | 处理策略 |
|---|---|---|---|
| `brain/wyckoff/engine.py` | P0-02, P2-01, P2-05M | 3 任务改同文件 | **跨阶段串行** P0-02 → P2-01 → P2-05M |
| `services/research_pipeline.py` | P1-03, P3-08M, ADD-03 | 3 任务改同文件 | **跨阶段串行** P1-03 → P3-08M → ADD-03 |
| `hands/backtest/unified_engine.py` | P1-06, P1-08, P2-02 | 3 任务改同文件 | **同工程师串行** Eng B: P1-06 → P1-08, P2-02 跨阶段 |
| `config/config.yaml` | P0-05, P2-06, P2-08, P3-03, P3-06 | 5 任务改不同章节 | **可并行** (不同配置章节) |
| `shared/limit_checker.py` | P0-02, P2-07 | 2 任务 | 跨阶段串行 |
| `shared/market_rules.py` | P2-07, P2-02 | 2 任务 | **先 P2-07 重构 → 后 P2-02 改 import** |
| `pyproject.toml` | P0-05, P3-01, P3-07 | 3 任务 | 同工程师串行 |

### 低冲突文件 (可安全并行)

| 文件 | 任务 | 说明 |
|---|---|---|
| `brain/lppl/calculator.py` | P2-03M (合并后) | ADD-04 已合并入 P2-03M |
| `shared/result_store.py` | ADD-02 (合并入 P3-08M) | 已合并 |
| `data/sources/*.py` | P1-05, P2-08 | 不同内容(重构 vs 配置), 可并行 |
| `services/analysis_service_v2.py` | P0-02, P0-05 | 不同改动点, 可并行 |

---

## 3. 6 阶段并行执行计划

### Phase 0: 崩溃修复与基础设施 (8h 挂钟)

**目标**: 所有 P0 级崩溃修复 + 基础依赖就绪  
**验收门禁**: `pytest tests/ -q` → **1515 passed, 0 failed**  
**回滚策略**: 每项独立 commit, 可单独 revert

| Eng | 串行顺序 | 任务 | 工时 | 改动的文件 | 冲突检查 |
|---|---|---|---|---|---|
| **A** | 1 | P0-05: Prometheus 指标 | 8h | `services/service_container.py`(新建MetricsCollector), `services/__init__.py`, `services/*.py`(插桩), `config/config.yaml`(metrics端口), `pyproject.toml`(prometheus-client依赖) | 独立文件 ✅ |
| **B** | 1→2→3→4 | P1-02 → P0-01 → P0-03 → P1-01 | 2+1+0.5+0.5=4h | `shared/config_loader.py`(环境变量覆盖) → `brain/fsm/fsm.py`(加IndexError+空DF守卫) → `data/sources/eastmoney.py`(删verify=False) → `data/lake/quotes/daily/`(.tmp.lock删除) | 全部独立文件 ✅ |
| **C** | 1→2→3 | P1-07 → P0-04 → P0-02 | 1+4+1=6h | `shared/interfaces.py`(加to_dict+修from_dict metadata) → `signal/db.py`(修正)+`tests/test_signal_db.py`(新建) → `shared/limit_checker.py:98`(加np.isinf)+`services/analysis/wyckoff_analysis_engine.py`(加ArithmeticError)+`services/analysis_service_v2.py`(加ArithmeticError) | 全部独立文件 ✅ |

**Phase 0 关键代码变更**:

```
P0-01 (Eng B):
  fsm_analysis_engine.py:96 前加: if df.empty: return {"action": "HOLD", "reason": "data_empty"}
  FSM_RECOVERABLE_ERRORS += (IndexError,)

P0-02 (Eng C):
  limit_checker.py:98: if pre_close <= 0 or np.isinf(pre_close): return LimitStatus(...)
  wyckoff_analysis_engine.py:10: WYCKOFF_RECOVERABLE_ERRORS += (ArithmeticError,)
  analysis_service_v2.py:47: RECOVERABLE_ERRORS += (ArithmeticError,)

P0-03 (Eng B):
  eastmoney.py:76: verify=False → 移除 (或用 verify='/path/to/ca-bundle.crt')

P0-04 (Eng C):
  tests/test_signal_db.py: 新建, 使用 SignalDatabase 类方法 API
  覆盖: save_signal, save_batch, get_by_id, query_by_symbol, query_by_source,
        query_by_type, get_recent_signals, get_statistics, delete_old

P0-05 (Eng A):
  services/ 下新建 metrics_collector.py
  注册: engine_run_seconds(Histogram), signal_collect_total(Counter),
        backtest_run_seconds(Histogram), data_fetch_errors_total(Counter)
  config.yaml: 添加 metrics.port=9090

P1-02 (Eng B):
  config_loader.py:89: 添加 os.environ.get('UNIQUANT_ROOT', ...) 覆盖

P1-07 (Eng C):
  interfaces.py: TradingSignal 添加 to_dict() 方法
  修复 from_dict() 中 metadata 字段被丢弃的 bug
```

---

### Phase 1: 数据管道与注册表重构 (10h 挂钟)

**目标**: 数据源基类重构 + 板块注册表统一 + 回测增强 + 硬编码路径清理  
**验收门禁**: `pytest tests/ -q --cov=src/uniquant/` → **coverage ≥ 当前基线**  
**硬依赖**: P0-02 已完成(limit_checker 已加 Inf 守卫) → P2-07 可安全改 limit_checker

| Eng | 串行顺序 | 任务 | 工时 | 改动的文件 | 冲突检查 |
|---|---|---|---|---|---|
| **A** | 1→2 | **P2-07** (6h) → **P1-05** (4h) | 10h | `shared/board_registry.py`(新建)→`shared/limit_checker.py`(委托)+`shared/market_rules.py`(委托)+`tests/test_limit_checker.py`+`tests/test_market_rules_drift.py` → `data/sources/base.py`(加共享方法)+各数据源文件(复用基类) | ✅ |
| **B** | 1→2→3 | **P1-06** (4h)→**P1-08** (3h)→**ADD-03** (2h) | 9h | `hands/backtest/unified_engine.py`(加sensitivity_scan)+`tests/test_backtest_sensitivity.py`(新建) → `hands/backtest/unified_engine.py`(加benchmark_returns参数) → 14处`./data`/`./results`(替换为config路径) | Group C: 同工程师串行 ✅ |
| **C** | 1→2 | **P1-03** (4h)→**P2-10** (4h) | 8h | `services/research_pipeline.py`(闭包转模块级函数, profile先行)+`tests/test_research_pipeline_checkpoint.py` → `data/sources/`+`config/config.yaml`(多周期数据配置) | ✅ |

**Phase 1 关键代码变更**:

```
P2-07 (Eng A):
  board_registry.py: 新建 BoardTypeRegistry 类, 统一代码前缀+交易所后缀逻辑
  limit_checker.py: get_board_type() 委托给 registry
  market_rules.py: detect_board() 委托给 registry

P1-05 (Eng A):
  base.py: DataSource 基类添加 _shared_column_mapping, _parse_date 方法
  sina.py/ths.py/其他: 复用基类方法

P1-06 (Eng B):
  unified_engine.py: 添加 sensitivity_scan(slippages, commissions) 方法
  test_backtest_sensitivity.py: 新建, 参数化测试

P1-08 (Eng B):
  unified_engine.py: run() 添加 benchmark_returns: Optional[pd.Series]=None
  BacktestResult: 添加 benchmark_return, alpha, information_ratio 字段

ADD-03 (Eng B):
  14 处硬编码路径: 替换为从 config.yaml 读取的路径

P1-03 (Eng C):
  research_pipeline.py: _run_single 重构为模块级函数, 显式传参
  先运行 profile: python3 -m cProfile 确认 GIL 瓶颈
  如需切换: 替换 ThreadPoolExecutor → ProcessPoolExecutor
  (注意: 闭包必须变成模块级函数才能 pickle)

P2-10 (Eng C):
  config.yaml: 添加 1min/5min/weekly/monthly 数据源配置
  data/lake/quotes/ 下新建子目录
```

---

### Phase 2: 引擎修复与信号测试 (12h 挂钟)

**目标**: Wyckoff 拆分 + LPPL 假阳性修复 + Regime 接口 + CZSC fallback + Adapter 测试 + E2E  
**验收门禁**: `python3 scripts/staged_full_scan.py --stage canary`  
**硬依赖**: P0-01+P0-02 已完成 → P2-09 可执行; P2-07 已完成 → P2-02 可执行

| Eng | 串行顺序 | 任务 | 工时 | 改动的文件 | 冲突检查 |
|---|---|---|---|---|---|
| **A** | 1→2 | **P2-01** (8h)→**P2-08** (4h) | 12h | `brain/wyckoff/engine.py`(拆分_step1_phase_determine)+Wyckoff测试文件验证 → `data/sources/`+`config/config.yaml`(数据更新频率) | Group A: P0-02(Phase0)→P2-01 跨阶段 ✅ |
| **B** | 1→2→3 | **P2-03M** (3h)→**P1-04** (4h)→**P2-09** (4h) | 11h | `brain/lppl/calculator.py`(Inf守卫+NaN比较bug修复)+`brain/lppl/engine.py`(precheck_fit_input加isinf) → `tests/test_signal_adapters.py`(7个适配器)+`tests/test_lppl_calculator_defense.py`(更新) → `tests/test_e2e_pipeline.py`(新建) | P1-04依赖P2-03M: 同工程师串行 ✅ |
| **C** | 1→2→3 | **P2-05M** (6h)→**P2-04** (2h)→**P2-02** (4h) | 12h | `brain/czsc/czsc_engine.py`(3 TODO接线)+`czsc_analysis_engine.py`(trend/current_state→CZSCOutput) → `services/analysis/regime_analysis_engine.py`(传df)+`brain/regime/regime_detector.py` → `hands/strategies/backtest.py`+`hands/strategies/wyckoff.py`+`hands/backtest/engine.py`(依赖迁移) | Group B: P2-07(Phase1)→P2-02 跨阶段 ✅ |

**Phase 2 关键代码变更**:

```
P2-01 (Eng A):
  engine.py: _step1_phase_determine(183行) 拆分为7个方法:
    _detect_accumulation, _detect_markup, _detect_distribution,
    _detect_markdown, _detect_spring, _detect_utad, _detect_sos
  验收: radon cc -s -n C → 无 C 级以上

P2-03M (Eng B):
  calculator.py:519: + or np.any(np.isinf(prices))
  calculator.py: _apply_sornette_constraints: 修复 NaN 比较 bug
    (if b >= 0 and not np.isnan(b): return False)
    (if abs(c) < self.c_min_abs and not np.isnan(c): return False)
  calculator.py: _determine_risk_level: 添加置信度交叉验证
    (if days_to_tc < 10 and not is_valid: return "Unknown")
  engine.py: precheck_fit_input: 加 isinf/NaN 检查

P1-04 (Eng B):
  test_signal_adapters.py: 为7个适配器添加测试
  LPPLAdapter: 覆盖 "Danger"+低置信度→不应 SELL
  WyckoffAdapter: 覆盖 5个输入键组合
  FSMAdapter: 覆盖 错误输入→不应产生错误信号

P2-05M (Eng C):
  czsc_engine.py/czsc_analysis_engine.py:
    trend → CZSCOutput.trend
    current_state → CZSCOutput.current_state
  移除对应 TODO 注释

P2-04 (Eng C):
  regime_analysis_engine.py:42: regime_detector.detect(df) 改传 DataFrame

P2-02 (Eng C):
  hands/ 下 4 文件: 替换 data/brain 直接 import 为 services 层访问
  hands/strategies/wyckoff.py: 通过 AnalysisService 间接调用 WyckoffEngine
```

---

### Phase 3: 质量门禁与配置治理 (12h 挂钟)

**目标**: Config Pydantic 验证 + 裸 except 清理 + mutmut 击杀率 + 死代码 + 行业集中度  
**验收门禁**: `pytest tests/ -q && mutmut run --no-coverage --paths-to-mutate src/uniquant/shared/cost_model.py`  
**硬依赖**: P1-02 已完成 → P3-01 可执行; P2-09 已完成 → P3-04 可执行

| Eng | 串行顺序 | 任务 | 工时 | 改动的文件 | 冲突检查 |
|---|---|---|---|---|---|
| **A** | 1→2 | **P3-08M** (5h)→**P3-04** (4h) | 9h | `services/research_pipeline.py`(bare except→具体异常)+`shared/result_store.py`(BaseException→Exception) → `.github/workflows/benchmark.yml`(新建) | ✅ |
| **B** | 1→2→3 | **P3-01** (4h)→**P3-07** (4h)→**P3-05** (4h) | 12h | `pyproject.toml`(mutmut配置) → `pyproject.toml`(覆盖门禁) → vulture输出文件列表(逐项评估删除) | P3-01+P3-07同文件: 串行 ✅ |
| **C** | 1→2 | **P2-06** (6h)→**ADD-05** (4h) | 10h | `shared/config_models.py`(Pydantic BaseModel)+`config/config.yaml`(模式文档) → `risk/sizer.py`(行业集中度) | ✅ |

**Phase 3 关键代码变更**:

```
P3-08M (Eng A):
  research_pipeline.py:237: except: → except Exception: (或更具体类型)
  result_store.py:71: except BaseException → except Exception

P3-01 + P3-07 (Eng B):
  pyproject.toml: mutmut 击杀率基线 ≥ 80%
  pyproject.toml: 覆盖门禁 50% → 逐步提升至 80%

P2-06 (Eng C):
  config_models.py: 手写 dataclass → Pydantic BaseModel
  添加: UniQuantConfig(BaseModel), 嵌套 SectionConfig
  验收: 配置缺失时 ServiceContainer 初始化立即失败

ADD-05 (Eng C):
  sizer.py:457 TODO → 实现 max_single_sector_pct 约束
  需要: 行业分类数据获取 + 持仓行业聚合 + 超限熔断
```

---

### Phase 4: 可观测性与治理收尾 (7h 挂钟)

**目标**: Grafana 仪表盘 + CI 基准测试 + NumPy BLAS + rate limiting + CODEOWNERS  
**验收门禁**: `pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=80`  
**硬依赖**: P0-05 已完成 → P3-06 可执行

| Eng | 任务 | 工时 | 改动的文件 | 冲突检查 |
|---|---|---|---|---|
| **A** | **P3-06** (4h) | 4h | `deploy/grafana/dashboard.json`(新建, 消费 P0-05 指标) | Group D: 同工程师(P0-05 Eng A) ✅ |
| **B** | **ADD-06** (4h) | 4h | 基础设施: 安装 NumPy 带 BLAS/OpenMP + `pyproject.toml`(依赖更新) | ✅ |
| **C** | **P3-03** (2h)→**P3-02** (1h) | 3h | `config/config.yaml`(rate limiting 强制) → `.github/CODEOWNERS`+.github/PULL_REQUEST_TEMPLATE.md(新建) | ✅ |

---

## 4. 完整时序依赖图

```
Phase 0 (8h wall clock):
  ┌──────────────────────────────────────────────────────────────┐
  │ Eng A: P0-05 (8h) ────────────────────────────────────────── │
  │ Eng B: P1-02(2h) → P0-01(1h) → P0-03(0.5h) → P1-01(0.5h)   │
  │ Eng C: P1-07(1h) → P0-04(4h) → P0-02(1h) ──────────────┐   │
  └──────────────────────────────────────────────────────────│───┘
                                                             │
  Gate: pytest tests/ -q                                     │
                                                             ▼
Phase 1 (10h wall clock):
  ┌──────────────────────────────────────────────────────────────┐
  │ Eng A: P2-07(6h) → P1-05(4h)                                │
  │ Eng B: P1-06(4h) → P1-08(3h) → ADD-03(2h)                  │
  │ Eng C: P1-03(4h) → P2-10(4h)                                │
  └──────────────────────────────────────────────────────────────┘
                                                             │
  Gate: pytest tests/ -q --cov=src/uniquant/                  │
                                                             ▼
Phase 2 (12h wall clock):
  ┌──────────────────────────────────────────────────────────────┐
  │ Eng A: P2-01(8h) → P2-08(4h)    ◄── P0-02 done (Phase 0)   │
  │ Eng B: P2-03M(3h) → P1-04(4h) → P2-09(4h)                  │
  │ Eng C: P2-05M(6h) → P2-04(2h) → P2-02(4h)  ◄── P2-07 done  │
  └──────────────────────────────────────────────────────────────┘
                                                             │
  Gate: python3 scripts/staged_full_scan.py --stage canary    │
                                                             ▼
Phase 3 (12h wall clock):
  ┌──────────────────────────────────────────────────────────────┐
  │ Eng A: P3-08M(5h) → P3-04(4h)    ◄── P2-09 done             │
  │ Eng B: P3-01(4h) → P3-07(4h) → P3-05(4h)  ◄── P1-02 done   │
  │ Eng C: P2-06(6h) → ADD-05(4h)                               │
  └──────────────────────────────────────────────────────────────┘
                                                             │
  Gate: pytest tests/ -q && mutmut run ...                    │
                                                             ▼
Phase 4 (7h wall clock):
  ┌──────────────────────────────────────────────────────────────┐
  │ Eng A: P3-06(4h)               ◄── P0-05 done               │
  │ Eng B: ADD-06(4h)                                           │
  │ Eng C: P3-03(2h) → P3-02(1h)                                │
  └──────────────────────────────────────────────────────────────┘

  Final Gate: pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=80
```

---

## 5. 工程资源需求

### 工程师技能分配

| 工程师 | 专长 | 分配任务特征 |
|---|---|---|
| **Eng A (平台)** | 基础设施、配置管理、可观测性 | P0-05(Prometheus), P2-07(注册表), P1-05(基类重构), P2-01(Wyckoff拆分), P3-08M(except清理), P3-06(Grafana), P2-08(数据更新) |
| **Eng B (交易)** | 回测、信号、适配器、E2E | P1-06(敏感性), P1-08(基准), ADD-03(路径), P2-03M(LPPL), P1-04(Adapter测试), P2-09(E2E), P3-01/P3-07(mutmut+覆盖), P3-05(死代码), ADD-06(BLAS) |
| **Eng C (引擎)** | 策略引擎、信号模型、风险 | P1-07(to_dict), P0-04(DB测试), P0-02(Inf守卫), P1-03(ProcessPool), P2-10(多周期), P2-05M(CZSC), P2-04(Regime), P2-02(依赖清理), P2-06(Pydantic), ADD-05(行业集中度) |

### 技能平衡

| 领域 | 任务数 | 工时 | 工程师 |
|---|---|---|---|
| 引擎与策略 | 11 | 42h | Eng C 主导 |
| 回测与信号 | 11 | 41h | Eng B 主导 |
| 基础设施与平台 | 12 | 39h | Eng A 主导 |

---

## 6. 验证门禁详情

| 门禁 | 时间点 | 命令 | 预期结果 | 失败处理 |
|---|---|---|---|---|
| G0 | Phase 0 结束 | `pytest tests/ -q` | 1515 passed, 0 failed | 阻止进入 Phase 1, 定位失败任务 revert |
| G1 | Phase 1 结束 | `pytest tests/ -q --cov=src/uniquant/` | 覆盖率 ≥ 当前基线 | 阻止进入 Phase 2, 补充测试 |
| G2 | Phase 2 结束 | `python3 scripts/staged_full_scan.py --stage canary --max-workers 4` | 5934/5934 success | 阻止进入 Phase 3, 定位失败引擎 |
| G3 | Phase 3 结束 | `pytest tests/ -q && mutmut run --no-coverage --paths-to-mutate src/uniquant/shared/cost_model.py` | 所有测试通过, mutmut 击杀率 ≥ 80% | 阻止进入 Phase 4, 修复 mutmut 路径 |
| G4 | Phase 4 结束 | `pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=80` | 覆盖率 ≥ 80% | 在 Phase 4 内补充测试直至达标 |

**最终验证 (所有阶段完成后)**:
```bash
pytest tests/ -q --tb=short --cov=src/uniquant/ --cov-report=term-missing
python3 scripts/capture_baseline.py
python3 scripts/compare_baseline.py  # 确认基线无损
ruff check src/uniquant/
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container OK')"
```

---

## 7. 回滚策略

| 场景 | 回滚方式 | 说明 |
|---|---|---|
| 单任务失败 | `git revert <commit-hash>` | 每任务独立 commit, 不影响其他任务 |
| 阶段门禁失败 | 回滚该阶段所有 commit, 修复后重试 | 门禁确保阶段内任务兼容 |
| 发现跨任务回归 | 回滚最后 2 个 commit, 分析原因 | 回归通常是依赖未正确声明导致 |
| Phase 2 E2E 失败 | 回滚 P2-03M 或 P0-01/P0-02, 检查崩溃修复 | E2E 门禁是最重要的质量关卡 |

### 每个 Phase 的 git 分支策略

```
Phase 0: main → phase-0/* (每人独立分支) → main 合并
Phase 1: main → phase-1/* → main
...
Phase 4: main → phase-4/* → main

每阶段结束时向 main 合并, 运行完整验收门禁
门禁失败时: 不回滚 main, 在 feature 分支修复后重新合并
```

---

## 8. 风险登记表

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| P1-03 ProcessPool 重构需要额外架构设计 | 高(70%) | Phase 1 延迟 | 先 profile 再决策; 若复杂度过高, 降为"不重构, 仅加文档" |
| P2-07 双系统统一引入回归 | 中(40%) | Phase 1 门禁失败 | P2-07 有 6 个测试代码验证; 并行维护两套系统直至确认兼容 |
| P2-01 Wyckoff 重构破坏现有信号 | 中(50%) | Phase 2 门禁失败 | 每个拆分步骤单独测试; 与 Phase 0 修复版本对比输出 |
| ADD-03 硬编码路径影响范围超出预期 | 中(30%) | Phase 1 延迟 | 逐文件修改; 每次修改后运行该文件相关测试 |
| P0-05 MetricsCollector 需要额外 HTTP 服务器 | 高(60%) | Phase 0 延迟 | 使用 `prometheus_client.start_http_server` 内建 HTTP; 无需额外框架 |
| 3 工程师资源不足 | 低(20%) | 全周期延迟 | 可降为 2 人执行(调整: Phase 0 降为 2 人需 12h 挂钟) |

---

## 9. 与原工作单的差异摘要

| 变更 | 原工作单 | 本计划 | 理由 |
|---|---|---|---|
| 任务总数 | 31 | 37 (+6) | 6 个新增盲点(裸except, 硬编码路径, NaN比较bug, CZSC TODO, 行业集中度, BLAS) |
| 任务合并 | 无 | 3 组合并(P2-03M, P2-05M, P3-08M) | 冲突文件合并给同一工程师, 避免跨任务冲突 |
| 总工时 | 47h | 122h (49h 挂钟) | 低估 53%(原始分析); 增加新任务 + 更精确估算 |
| 执行模式 | 串行清单 | 3 人并行 + 5 阶段 | 挂钟时间从 47h 降至 49h(3 人), 而非串行的 122h |
| P0-02 修复 | 仅加 OverflowError | 3 处: limit_checker 守卫 + 2 处 RECOVERABLE_ERRORS | 元分析发现 14 层传播链, 仅加 except 不够 |
| P2-06 优先级 | P2 (本月) | P3 (质量治理) | 发现已有 8 个验证器, 非紧急 |
| P2-03 范围 | Inf 守卫 | +NaN比较bug修复 + 置信度交叉验证 | 元分析发现 `_apply_sornette_constraints` NaN 问题 |
| P1-03 优先级 | P1 (本周) | Phase 1 (带profile前置) | 闭包不可 pickle + 无 BLAS, 需先验证 |
| 验证门禁 | 无 | 5 阶段门禁 + 最终验证 | 确保每阶段交付质量 |

---

## 10. 执行检查清单 (供每日站会使用)

### Phase 0 (Day 1-2)
- [ ] Eng A: MetricsCollector 框架就绪
- [ ] Eng B: FSM 空 DF 崩溃修复 + 测试
- [ ] Eng B: EastMoney SSL 修复
- [ ] Eng B: .tmp.lock 已清理
- [ ] Eng B: mutmut 路径修复
- [ ] Eng C: TradingSignal.to_dict + from_dict metadata 修复
- [ ] Eng C: signal/db.py 测试 ≥80%
- [ ] Eng C: limit_checker Inf 守卫 + RECOVERABLE_ERRORS 更新
- [ ] **Gate: pytest tests/ -q 全部通过**

### Phase 1 (Day 2-4)
- [ ] Eng A: BoardTypeRegistry 统一注册表
- [ ] Eng A: 数据源基类复用
- [ ] Eng B: sensitivity_scan 方法
- [ ] Eng B: benchmark_returns 参数
- [ ] Eng B: 硬编码路径清理 (14 处)
- [ ] Eng C: research_pipeline profile + ProcessPool 决策
- [ ] Eng C: 多周期数据配置
- [ ] **Gate: pytest tests/ -q --cov=src/uniquant/ 基线无损**

### Phase 2 (Day 4-6)
- [ ] Eng A: Wyckoff _step1_phase_determine 拆分 (复杂度 76→<C)
- [ ] Eng A: 数据源更新频率配置
- [ ] Eng B: LPPL Inf 守卫 + NaN 比较 bug + 风险交叉验证
- [ ] Eng B: 7 个 Adapter 测试 (≥80%)
- [ ] Eng B: E2E Pipeline 测试
- [ ] Eng C: CZSC trend/current_state 接线
- [ ] Eng C: Regime 接口修复
- [ ] Eng C: hands 层依赖清理
- [ ] **Gate: python3 scripts/staged_full_scan.py --stage canary 全通过**

### Phase 3 (Day 6-8)
- [ ] Eng A: bare except + BaseException 修复
- [ ] Eng A: CI benchmark workflow
- [ ] Eng B: mutmut 击杀率基线 ≥80%
- [ ] Eng B: 覆盖门禁 50%→80%
- [ ] Eng B: vulture 死代码清理
- [ ] Eng C: Pydantic 配置 schema
- [ ] Eng C: 行业集中度约束
- [ ] **Gate: mutmut run --no-coverage 击杀率 ≥80%**

### Phase 4 (Day 8-9)
- [ ] Eng A: Grafana 仪表盘
- [ ] Eng B: NumPy BLAS/OpenMP
- [ ] Eng C: Rate limiting 强制
- [ ] Eng C: CODEOWNERS + PR 模板
- [ ] **Final Gate: pytest --cov-fail-under=80**

---

## 附录: 预计算工时明细

| Phase | 任务数 | 人时 | 挂钟 | 工程师 |
|---|---|---|---|---|
| 0: 崩溃修复 | 6 | 18h | 8h | 3 |
| 1: 数据与注册表 | 7 | 27h | 10h | 3 |
| 2: 引擎与信号 | 8 | 35h | 12h | 3 |
| 3: 质量门禁 | 7 | 31h | 12h | 3 |
| 4: 治理收尾 | 5 | 11h | 7h | 3 |
| **总计** | **34** | **122h** | **49h** | **3** |

> **49 小时挂钟时间** = 6 个工作日 (8h/天, 3 人并行)。相比原工作单的串行 47h, 并行版本在不增加人时(122h vs 47h 的单人版实为 141h)的情况下大幅缩短交付时间。