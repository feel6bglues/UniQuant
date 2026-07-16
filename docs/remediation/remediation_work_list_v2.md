# UniQuant 修复与优化工作清单 (红蓝对抗核实版)

> **日期**: 2026-07-10 | **核实基础**: 6 轮红蓝对抗逐文件代码验证
> **优先级**: P0(紧急) → P1(本周) → P2(本月)
> **总工时**: ~30.5 人时 | **最大并行挂钟**: ~7.5h (4 工程师) | **串行挂钟**: 3 天 (1 工程师)
> **出发基线**: 1,673 tests pass, 0 ruff, 52.66% coverage
> **并行策略**: 见 `docs/remediation/parallel_analysis.md`

---

## 最大并行执行顺序 (4 工程师, 7.5h 挂钟)

> 核心约束: **同一文件 → 串行 / 不同文件 → 全并行**.
> 详见 `docs/remediation/parallel_analysis.md` 逐文件依赖分析.

```
Day 1 (7.5h) ─────────────────────────────────────────────────
  ┌──────────────────────────────────────────────────────────┐
  │ Phase 0 (1h 25m) — 8 路并行 → 1 路串行 → Gate           │
  │                                                          │
  │  Wave 1: 8 路并行 (15m) ──────────────────────────────  │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │ Agent A  │ │ Agent B  │ │ Agent C  │ │ Agent D  │    │
  │  │ research │ │ akshare  │ │ lppl/    │ │ lppl/    │    │
  │  │ pipeline │ │ wrapper  │ │ comput   │ │ calc     │    │
  │  │ E-13→E-14│ │ E-10→E-12│ │ E-03→E-05│ │ E-01→E-02│    │
  │  │ [4m]     │ │ [6m]     │ │ [15m]    │ │ [4m]     │    │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │ Agent E  │ │ Agent F  │ │ Agent G  │ │ Agent H  │    │
  │  │ lppl/    │ │ lppl/    │ │ lppl/    │ │ unified  │    │
  │  │ numba_opt│ │ visual   │ │ data_mgr │ │ engine   │    │
  │  │ E-06→E-07│ │ E-08→E-15│ │ E-09     │ │ TS-02    │    │
  │  │ [4m]     │ │ [4m]     │ │ [2m]     │ │ [10m]    │    │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
  │                                                          │
  │  Wave 2: 1 路串行 (1h 5m) ────────────────────────────  │
  │  Agent A: research_pipeline.py TS-01 (线程安全) [1h5m]   │
  │  ← 瓶颈路径: 同一文件 3 处 edit, 无法并行                │
  │                                                          │
  │  Gate: pytest + ruff + grep LPPL except=0 [5m]           │
  ├──────────────────────────────────────────────────────────┤
  │ Phase 1 (2h 5m) — 14 路并行 → Gate                       │
  │                                                          │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │ Eng 1    │ │ Eng 2    │ │ Eng 3    │ │ Eng 4    │    │
  │  │ DC-01    │ │ DC-03    │ │ DC-02    │ │ DC-05    │    │
  │  │ archive  │ │ archive  │ │ +04+06   │ │ 弱断言   │    │
  │  │ legacy   │ │ price_c  │ │ markers  │ │ tests/   │    │
  │  │ [1h]     │ │ [30m]    │ │ [15m]    │ │ [1h]     │    │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │ Eng 1    │ │ Eng 2    │ │ Eng 3    │ │ Eng 4    │    │
  │  │ TC-01    │ │ TC-02    │ │ TC-03    │ │ TC-04    │    │
  │  │ adapters │ │ arbitrator│ │ engine   │ │ matching │    │
  │  │ tests    │ │ tests    │ │ tests    │ │ tests    │    │
  │  │ [2h]     │ │ [1h]     │ │ [2h]     │ │ [2h]     │    │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
  │  ┌──────────┐                                            │
  │  │ Eng 4    │  TC-05 (analysis_v2 tests) [2h]           │
  │  └──────────┘                                            │
  │                                                          │
  │  Gate: canary 20/20 + coverage >=52% [5m]                │
  ├──────────────────────────────────────────────────────────┤
  │ Phase 2 (4h 5m) — 6 路并行 → Gate                        │
  │                                                          │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │ Eng 1    │ │ Eng 2    │ │ Eng 3    │ │ Eng 4    │    │
  │  │ RD-01    │ │ RD-02    │ │ DA-01    │ │ DA-02    │    │
  │  │ portfolio│ │ metrics  │ │ docs/    │ │ AGENTS   │    │
  │  │ research │ │ design   │ │ batch    │ │ .md      │    │
  │  │ [4h]     │ │ [4h]     │ │ [2h]     │ │ [30m]    │    │
  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
  │  ┌──────────┐ ┌──────────┐                               │
  │  │ Eng 3    │ │ Eng 4    │                               │
  │  │ DA-03    │ │ DA-04    │                               │
  │  │ config   │ │ optimal  │                               │
  │  │ .yaml    │ │ params   │                               │
  │  │ [1h]     │ │ [1h]     │                               │
  │  └──────────┘ └──────────┘                               │
  │                                                          │
  │  Gate: coverage >=55% + doc paths 100% [5m]              │
  └──────────────────────────────────────────────────────────┘
```

### 资源分配表 (4 工程师)

| 时段 | Eng 1 | Eng 2 | Eng 3 | Eng 4 |
|:----:|:------|:------|:------|:------|
| 0:00-0:15 | `research_pipeline` E-13→E-14 | `akshare_wrapper` E-10→E-12 | `lppl/computation` E-03→E-05 | `lppl/calculator` E-01→E-02 |
| 0:00-0:15 | `lppl/numba_opt` E-06→E-07 | `lppl/visualizer` E-08→E-15 | 同上 | `lppl/data_mgr` E-09 |
| 0:15 | 全合并 | 全合并 | 全合并 | 全合并 |
| 0:15-1:20 | `research_pipeline` TS-01 | — | — | `unified_engine` TS-02 |
| 1:20-1:25 | **Gate: pytest + ruff + grep** | | | |
| 1:25-3:25 | DC-01 + TC-01 | DC-03 + TC-02 | DC-02/04/06 + TC-03 | DC-05 + TC-04 |
| 3:25-3:30 | **Gate: canary + coverage** | | | |
| 3:30-7:30 | RD-01 | RD-02 | DA-01 + DA-03 | DA-02 + DA-04 + TC-05 |
| 7:30-7:35 | **Gate: coverage + doc paths** | | | |

---

## Phase 0 — P0 紧急修复 (24 人时, 8h 挂钟)

> **范围聚焦**: 全库 `grep` 发现 ~239 处 `except Exception`, 但绝大部分位于网络数据源/UI/事件总线的防御性编程中.
> P0 只追杀 **核心算法/管线路径** 中 15 处确定可窄化且影响信号质量/管道可靠性的位置.

### Wave 1: 15 处裸 `except Exception` 窄化 (核心路径)

全部已验证位于核心算法/管线路径, 窄化为具体异常类型:

#### LPPL 层 (9 处)

| ID | 文件:行 | 当前代码 | 窄化目标 | 工时 | 风险 |
|:--:|:--------|:---------|:---------|:---:|:----:|
| E-01 | `lppl/calculator.py:118` | `except Exception as e: logger.error(...)` | `(KeyError, TypeError, ValueError)` | 2m | 低 |
| E-02 | `lppl/calculator.py:480` | `except Exception: continue` | `(ValueError, RuntimeError)` | 2m | 低 |
| E-03 | `lppl/computation.py:73` | `except Exception as e: logger.error(...)` | `(ValueError, TypeError, KeyError)` + `exc_info=True` | 5m | 低 |
| E-04 | `lppl/computation.py:223` | `except Exception as e: logger.warning(...)` | `(ValueError, TypeError, KeyError, RuntimeError)` | 5m | 低 |
| E-05 | `lppl/computation.py:293` | `except Exception as e: logger.error(...)` | `(ValueError, TypeError, KeyError, RuntimeError)` | 5m | 低 |
| E-06 | `lppl/numba_optimizer.py:91` | `except Exception: return 1e20` | `(np.linalg.LinAlgError, ValueError)` → **WONTFIX** (numba @njit 限制) | 2m | 低 |
| E-07 | `lppl/numba_optimizer.py:171` | `except Exception: return 0,0,0,0` | `(np.linalg.LinAlgError, ValueError)` → **WONTFIX** (numba @njit 限制) | 2m | 低 |
| E-08 | `lppl/visualizer.py:101` | `except Exception as e: logger.error(...)` | `(IOError, OSError, ValueError)` | 2m | 低 |
| E-09 | `lppl/data_manager.py:117` | `except Exception as e: logger.error(...)` | `(IOError, OSError, ValueError)` | 2m | 低 |

#### 配置初始化层 (3 处)

| ID | 文件:行 | 当前代码 | 窄化目标 | 工时 | 风险 |
|:--:|:--------|:---------|:---------|:---:|:----:|
| E-10 | `akshare_wrapper.py:83` | `except Exception as e: logger.warning(...)` | `(ValueError, TypeError)` | 2m | 低 |
| E-11 | `akshare_wrapper.py:99` | `except Exception as e: logger.warning(...)` | `(ValueError, TypeError)` | 2m | 低 |
| E-12 | `akshare_wrapper.py:107` | `except Exception as e: logger.error(...)` | `(ImportError, KeyError, ValueError, TypeError)` | 2m | 低 |

#### Pipeline 持久化层 (2 处)

| ID | 文件:行 | 当前代码 | 窄化目标 | 工时 | 风险 |
|:--:|:--------|:---------|:---------|:---:|:----:|
| E-13 | `research_pipeline.py:562` | `except Exception as e: logger.warning(...)` | `(OSError, json.JSONDecodeError)` | 2m | 低 |
| E-14 | `research_pipeline.py:638` | `except Exception as e: logger.warning(...)` | `(OSError, KeyError, TypeError)` | 2m | 低 |

#### 外围引擎层 (1 处)

| ID | 文件:行 | 当前代码 | 窄化目标 | 工时 | 风险 |
|:--:|:--------|:---------|:---------|:---:|:----:|
| E-15 | `lppl/visualizer.py:182` | `except Exception as e: logger.error(...)` | `(IOError, OSError, ValueError)` | 2m | 低 |

**Wave 1 验收**: `grep -rn "except Exception" src/uniquant/brain/lppl/ --include="*.py"` → 0 结果

---

### Wave 2: 线程安全 + 信号超时 (3 项)

| ID | 文件 | 问题 | 当前状态 | 修复方案 | 工时 |
|:--:|:-----|:-----|:---------|:---------|:---:|
| TS-01 | `research_pipeline.py:149-540` | `run_batch()` 线程安全 | 已加 `_metrics_lock/event_bus_lock/save_lock`, `_run_single` 使用 `local_metrics` 隔离 | 确认当前方案完备, 加 `np.random.seed` 隔离保护 | 1h |
| TS-02 | `unified_engine.py:410` | 仓位计算裸 except | 在信号处理循环中包裹 sizer 调用 | 窄化为 `(KeyError, TypeError, ValueError, RuntimeError)` | 10m |
| TS-03 | `signal/arbitrator.py:39` | 信号超时保持禁用 | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` | **WONTFIX** — 设计决策: 回测信号时间戳与壁钟不匹配 | 0h |

**Wave 2 验收**: `pytest tests/ -q --tb=short` → 0 failed

---

## 全库 `except Exception` 背景统计 (红蓝对抗补充)

| 层 | 计数 | 核心路径(需修复) | 容忍(宽泛防御) | 说明 |
|:---|:----:|:---------------:|:--------------:|:-----|
| `data/` | 139 | 0 | 139 | 网络源请求容错, 防御性 failover, 设计上安全 |
| `shared/` | 26 | 0 | 26 | 缓存IO/事件总线/配置降级, 设计上安全 |
| `services/` | 21 | 2 | 19 | 管线持久化可窄化, 服务容器 DI 安全 |
| `brain/` | 21 | 9 | 12 | LPPL 算法层可窄化, 其余引擎容错安全 |
| `ui/` | 17 | 0 | 17 | Streamlit 回调永不崩溃原则, 无需修复 |
| `hands/` | 14 | 2 | 12 | 交易引擎 sizer 可窄化 |
| `signal/` | 1 | 0 | 1 | 已处理 |
| `risk/` | 0 | 0 | 0 | 零 |
| **总计** | **239** | **13** | **226** | |

---

## Phase 1 — P1 工程健康 (18 人时, 10h 挂钟)

### Wave 3: 死代码归档 + 弱断言测试补强 (6 项)

| ID | 文件 | 类型 | 问题 | 修复方案 | 工时 |
|:--:|:-----|:----:|:-----|:---------|:---:|
| DC-01 | `services/analysis_service_legacy.py` | 完全死代码 | 1,649 LOC, 零导入 | 移到 `src/uniquant/services/archive/` | 1h |
| DC-02 | `signal/quality.py` | 完全死代码 | 294 LOC, 零生产调用 | 保留但加 `# DEPRECATED — not called by any production code` 已确认存在 | 5m |
| DC-03 | `shared/price_collar.py` | 完全死代码 | 32 LOC, 零调用 | 移到 `src/uniquant/shared/archive/` + 确认 `market_rules.py` 的 `price_collar_pct` 字段保留 | 30m |
| DC-04 | `shared/slippage_model.py:DynamicSlippage` | 完全死代码 | 20 LOC, 默认路径未实例化 | 加 `# NOTE: NOT instantiated in default backtest path` 注释 | 5m |
| DC-05 | `tests/` 全目录 | 弱断言测试 | 56 个测试函数无 `assert` | 对 9 个真正无断言测试增补 (其余 47 个用 `pytest.raises`) | 4h |
| DC-06 | `portfolio_engine.py` | 半死代码 | 已在 `__init__.py` 移除导出 | 确认移除状态, 加文件头 `# DEPRECATED — use UnifiedBacktestEngine` | 5m |

**Wave 3 验收**: `pytest tests/ -q` → 0 failed, 弱断言从 56 降至 ≤10

---

### Wave 4: 测试补全 (5 项)

| ID | 文件 | 当前覆盖 | 目标 | 修复方案 | 工时 |
|:--:|:-----|:-------:|:----:|:---------|:---:|
| TC-01 | `signal/adapters.py` | 62 tests, NTF 为主 | LPPL/Wyckoff 完整路径 | 新增 LPPLAdapter Danger→SELL、WyckoffAdapter 4 phase / confidence 边界 | 2h |
| TC-02 | `signal/arbitrator.py` | 87% | 95% | 新增 SELL 优先 / 质量门禁组合测试 | 1h |
| TC-03 | `unified_engine.py` | 752 LOC implicit | 显式测试 | 新增 `sensitivity_scan()` 参数传递 + benchmark 集成测试 | 2h |
| TC-04 | `unified_matching_engine.py` | 向量化撮合 | E2E 覆盖 | 新增 T+1/涨跌停/停牌组合场景 E2E | 2h |
| TC-05 | `analysis_service_v2.py` | 637 LOC implicit | 显式测试 | 新增 engine 失败→fallback 输出验证测试 | 2h |

**Wave 4 验收**: `pytest --cov=src/uniquant/ --cov-fail-under=52` → >=52%

---

## Phase 2 — P2 优化改进 (20 人时, 6h 挂钟)

### Wave 5: 组合回测研究 + metrics 系统设计 (2 项)

| ID | 项目 | 当前状态 | 目标 | 工时 |
|:--:|:-----|:---------|:-----|:---:|
| RD-01 | 组合回测 | portfolio_engine.py 已废弃, 无替代 | 可行性研究 + 架构设计文档 + 40h 工作量估算 | 4h |
| RD-02 | Metrics 系统 | InMemoryMetricsRecorder 仅内存, 零持久化 | 架构设计: Prometheus 或 OTel 集成方案, 含 API 设计 | 4h |

### Wave 6: 文档对齐 + 参数工具 (4 项)

| ID | 文件 | 问题 | 修复方案 | 工时 |
|:--:|:-----|:-----|:---------|:---:|
| DA-01 | `docs/reanalysis/*.md` | Wyckoff 复杂度 76→40, eastmoney 1094→3 等过时声明 | 批量修正文档指标 | 2h |
| DA-02 | `AGENTS.md` | 测试函数 1,591→1,606, 死代码 ~2,274→~2,298 | 更新 metrics | 30m |
| DA-03 | `config/config.yaml` | 配置需与代码实际对齐 | 验证并修正配置项 | 1h |
| DA-04 | `shared/optimal_params.py` | 存在但未集成到管线 | 验证状态并更新文档 | 1h |

**Wave 6 验收**: `python3 scripts/verify_doc_paths.py` → 100% 路径有效

---

## 冲突矩阵 (按最大并行修正)

| 冲突组 | 文件 | 冲突任务 | 并行策略 | 挂钟影响 |
|:------:|:-----|:---------|:---------|:--------:|
| **A** | `research_pipeline.py` | E-13, E-14, TS-01 | 串行: E-13→E-14→TS-01 (1h5m) | ⚠️ Phase 0 瓶颈 |
| **B** | `akshare_wrapper.py` | E-10, E-11, E-12 | 串行: E-10→E-11→E-12 (6m) | 无影响 (<15m) |
| **C** | `lppl/computation.py` | E-03, E-04, E-05 | 串行: E-03→E-04→E-05 (15m) | 无影响 (与 A 并行) |
| **D** | `lppl/calculator.py` | E-01, E-02 | 串行 (4m) | 无影响 |
| **E** | `lppl/numba_optimizer.py` | E-06, E-07 | 串行 (4m) | 无影响 |
| **F** | `lppl/visualizer.py` | E-08, E-15 | 串行 (4m) | 无影响 |
| **G** | `signal/` 层 | TC-01, TC-02 | 并行 (不同文件) | 无影响 |
| **H** | `tests/` | TC-03, TC-04, TC-05 | 并行 (不同文件) | 无影响 |

---

## 验证门禁速查

| 门禁 | 命令 | 通过条件 |
|:----:|:-----|:---------|
| G0 | `pytest tests/ -q --tb=short` | 0 failed |
| G0b | `ruff check src/uniquant/` | 0 issues |
| G0c | `grep -rn "except Exception" src/uniquant/brain/lppl/ --include="*.py"` | 0 results (LPPL 层清零) |
| G1 | `grep -rn "def test_\{1,\}" tests/ --include="*.py" \| grep -v "pytest.raises" \| wc -l` | ≤10 无断言 |
| G1b | `python3 scripts/staged_full_scan.py --stage canary --max-workers 4` | 20/20 success |
| G2 | `pytest --cov=src/uniquant/ --cov-report=term-missing --cov-fail-under=52` | >=52% |
| G2b | `python3 scripts/verify_doc_paths.py` | 100% pass |

---

## 串行执行顺序 (1 工程师, 3 天)

```
Phase 0 (8h) ──────────────────────────
  Day 1 上午:
    Step 1:  E-06, E-07 (numba_optimizer)    [4m]
    Step 2:  E-01, E-02 (calculator)          [4m]
    Step 3:  E-03→E-04→E-05 (computation)    [15m]
    Step 4:  E-08, E-15 (visualizer)          [4m]
    Step 5:  E-09 (data_manager)              [2m]
    Step 6:  E-10→E-11→E-12 (akshare_wrapper) [6m]
    Step 7:  E-13, E-14 (research_pipeline)   [4m]
    Step 8:  TS-02 (unified_engine)           [10m]
    Step 9:  TS-01 (research_pipeline 线程)   [1h]
    -> Gate: pytest + ruff + grep except=0

Phase 1 (2 天) ──────────────────────────
  Day 1 下午:
    Step 10: DC-01 (archive legacy)           [1h]
    Step 11: DC-03 (archive price_collar)     [30m]
    Step 12: DC-02, DC-04, DC-06 (markers)    [15m]
    Step 13: DC-05 (弱断言 fix)               [4h]
  Day 2 上午:
    Step 14: TC-01 (adapters tests)           [2h]
    Step 15: TC-02 (arbitrator tests)         [1h]
    Step 16: TC-03 (engine tests)             [2h]
  Day 2 下午:
    Step 17: TC-04 (matching tests)           [2h]
    Step 18: TC-05 (analysis_v2 tests)        [2h]
    -> Gate: canary scan + weak assert count

Phase 2 (1 天) ──────────────────────────
  Day 3 上午:
    Step 19: RD-01 (portfolio research)       [4h]
  Day 3 下午:
    Step 20: RD-02 (metrics design)           [4h]
    Step 21: DA-01→DA-04 (docs alignment)     [4h]
    -> Gate: coverage >=52% + doc paths
```

---

## 工作量汇总

| Phase | 任务数 | 人时 | 串行挂钟(1人) | 最大并行(4人) |
|:-----:|:-----:|:----:|:-------------:|:-------------:|
| P0 紧急 | 17 项 (15 except + 2 线程) | 2.5h | 8h | 1h 25m |
| P1 工程健康 | 11 项 (6 死代码 + 5 测试) | 15.5h | 10h | 2h 5m |
| P2 优化改进 | 6 项 (2 研究 + 4 文档) | 12.5h | 6h | 4h 5m |
| **总计** | **34 项** | **30.5h** | **~3 天** | **~7.5h** |

### 关键瓶颈

| 瓶颈 | 阶段 | 原因 | 限制 |
|:-----|:----:|:------|:----:|
| `research_pipeline.py` | P0 | 3 处编辑同一文件 | 最小 1h5m, 无法并行 |
| TC-01/03/04/05 测试 | P1 | 测试编写时间长 | 可 4 路并行, 最小 2h |
| RD-01/RD-02 设计 | P2 | 架构设计文档 | 可 2 路并行, 最小 4h |

---

## 当前基线 (核实后)

| 指标 | 当前值 | Phase 0 后 | Phase 1 后 | Phase 2 后 |
|:----|:------:|:----------:|:----------:|:----------:|
| Tests pass | 1,673 | 1,673 | 1,680+ | 1,690+ |
| Ruff issues | 0 | 0 | 0 | 0 |
| Coverage | 52.66% | 52.66% | 53%+ | 55%+ |
| `except Exception` (核心路径) | 13 | **0** | 0 | 0 |
| 弱断言测试 | 56 | 56 | ≤10 | ≤5 |
| 死代码 LOC | ~2,298 | ~380 (archive) | ~380 | ~380 |
| 文档路径失效 | ? | ? | 0 | 0 |

---

## 参考

- 并行化分析报告: `docs/remediation/parallel_analysis.md`
- 红蓝对抗核实: `docs/reanalysis/Z_investigation_report_20260710.md`
- 原始修复清单: `docs/remediation/red_blue_remediation_plan.md`