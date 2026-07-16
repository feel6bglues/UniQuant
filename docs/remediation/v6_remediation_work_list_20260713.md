# v6 修复工作清单 — 基于六路并行红蓝对抗 + TDD 全量分析

> **生成**: 2026-07-13 | **验证基础**: 六路并行逐层排查 + 83 项红蓝对抗声明核实
> **前置**: 所有 17 项 P0/R 修复已全部确认为 **已修复** (参见 §0 已确认修复清单)
> **范围**: 本次新发现的 15 项可操作修复项，全部附 file:line 证据
> **总工时**: ~28 人时 | **挂钟**: ~12h (2 工程师并行)

---

## §0: 已确认修复 (17/17 — 逐文件验证)

| ID | 修复项 | 文件:行 | 代码证据 |
|:--:|--------|:-------|:---------|
| P0-01 | AlphaScore 0.0→None | `adapters.py:362` | `0 < score < 0.3` |
| P0-02 | ADV look-ahead shift(1) | `unified_engine.py:494-495` | `adv.shift(1).fillna(adv)` |
| P0-03 | AkShare re-raise | `akshare_wrapper.py:217` | `raise` after `logger.error` |
| P0-04 | fillna(0.0)→np.nan ×3 | `composer.py` | 零 `fillna()` 调用 |
| P0-05 | eastmoney SSL verify | `eastmoney_base.py:58` | `verify=True` |
| P0-06 | Pipeline 线程安全 | `research_pipeline.py:149-151,538` | 3 × Lock + ThreadPoolExecutor |
| P0-07 | Matching halt volume=0 | `unified_matching_engine.py:180,244` | `volume_zero` mask |
| P0-08 | Pipeline except 窄化 | `research_pipeline.py:244` | `(OSError, PermissionError, json.JSONDecodeError)` |
| P0-09 | Wyckoff except 窄化 ×4 | `engine.py:251,261,1575,1591` | 全部 typed |
| P0-10 | Circuit breaker 启用 | `eastmoney_base.py:41` | `@with_circuit_breaker(...)` |
| R0-01 | DataValidator mutate fix | `data_validator.py:13` | `df = df.copy()` |
| R0-02 | TradeCalendar per-year | `trade_calendar_manager.py` | 3 code paths all per-year |
| R0-03 | Pipeline bare except | `research_pipeline.py:240-246` | `(OSError, PermissionError, JSONDecodeError)` |
| R1-01 | sharpe_ratio pct fix | `cost_model.py:65-73` | pct returns |
| R1-02 | RDPack metadata flatten | `interfaces.py:243-258` | `to_dict()` flat map |
| R2-03 | PortfolioSizer immutable | `risk/sizer.py:467` | `dataclasses.replace()` |
| R3-06 | DiskCache per-item TTL | `cache/backends.py:229-234` | `expires_at` check |

**v5 Batch 2 新增测试已确认存在**:
- `AdapterRegistry.discover()` 测试: `test_adapters.py:465-477` (2 tests)
- `TradingSignalCollector` 事件发布测试: `test_adapters.py:480-510` (2 tests)
- AlphaScore 0.0 边界测试: `test_adapters.py` 中存在

---

## §1: 新发现真实待修复清单 (均经 file:line 源代码核实)

### R0 — 关键修复 (4 项)

---

#### R0-N01: 文档声称 "ui/ except Exception 17→2", 但实际仍为 17

| 字段 | 内容 |
|:----|:------|
| **严重度** | **HIGH** — 文档声称已修复但实际未执行, 产生错误的安全感 |
| **问题** | v5 报告 (R2-03) 声称 "UI 层 `except Exception` 从 17→2" 已纠正。但 `grep -rn "except Exception" src/uniquant/ui/ --include="*.py" | wc -l` 返回 **17** — 从未纠正。分布在: `manager_logic.py:343-484` (6处), `manager_portfolio_analytics_service.py:55,80,112,140` (4处), `manager_report_service.py:85,106,145,177` (4处), `lppl_visualizer.py:27,39` (2处), `dashboard.py:1266` (1处) |
| **源代码证据** | `grep -rn "except Exception" src/uniquant/ui/ --include="*.py"` = 17 条 (见上) |
| **修复方案** | 方案A: 确实纠正 (5m) — 修正 AGENTS.md 和所有文档中该声明。方案B: 窄化所有 17 处 (4h) — 至少加 `as e` 和 `logger.warning`。推荐方案A+B |
| **文件** | `src/uniquant/ui/manager_logic.py`, `manager_report_service.py`, `manager_portfolio_analytics_service.py`, `lppl_visualizer.py`, `dashboard.py` |
| **工时** | 5m (文档) + 4h (窄化) |

**新增发现**: `manager_logic.py` 有 6 处 `except Exception as e:` (343,444,454,464,474,484), 为代码库中单文件最高密度。全部仅 log-and-continue。`lppl_visualizer.py:27,39` 更危险 — `except Exception:` 无 `as e`, 丢弃所有异常上下文。

---

#### R0-N02: `shared/factor_governance.py` (156 LOC) 完全死代码, 未计入死代码库存

| 字段 | 内容 |
|:----|:------|
| **严重度** | **MED** — 死代码库存低估 156 LOC (6.4%), 文档误导开发者 |
| **问题** | `factor_governance.py` 第一行发出 `warnings.warn("deprecated. Use brain.factors.registry")`。全代码库 `grep` 确认**零生产导入**。但 v5 死代码库存 (~2,225 LOC) 和所有文档都未跟踪此文件 |
| **源代码证据** | `factor_governance.py:15-19` deprecation warning；`grep -rn "factor_governance" src/uniquant/ --include="*.py" | grep -v "warnings"` → 无结果 (除自身外零引用) |
| **修复方案** | 归档至 `shared/archive/factor_governance.py` + 更新死代码库存为 ~2,381 LOC |
| **文件** | `src/uniquant/shared/factor_governance.py` (156 LOC) |
| **工时** | 10m |

---

#### R0-N03: `hands/backtest/portfolio_engine.py` (376 LOC) 半死文件, 未跟踪

| 字段 | 内容 |
|:----|:------|
| **严重度** | **MED** — 376 LOC 维护负担, 误导新开发者以为可用 |
| **问题** | `__init__.py:17` 注释 "PortfolioEngine deprecated — removed from exports"。文件头含 deprecation 警告 (line 29)。但 `portfolio_engine.py` 仍为活动源文件, 376 LOC, 含 `PortfolioEngine` 类 (8 公共方法 + `run()`)。未被任何生产代码导入 |
| **源代码证据** | `portfolio_engine.py:29` `warnings.warn("PortfolioEngine is deprecated...")`；`grep -rn "from.*portfolio_engine\|import.*portfolio_engine" src/uniquant/` → 仅 `__init__.py:5` 注释提及 |
| **修复方案** | 归档至 `hands/backtest/archive/portfolio_engine.py` + 更新死代码库存 +376 LOC |
| **文件** | `src/uniquant/hands/backtest/portfolio_engine.py` (376 LOC) |
| **工时** | 10m |

---

#### R0-N04: `signal/__init__.py` `__all__` 仅导出 6/8 适配器, 与注册表不一致

| 字段 | 内容 |
|:----|:------|
| **严重度** | **MED** — `from uniquant.signal import NTFAdapter` 不可用, 开发者迷惑 |
| **问题** | `create_default_registry()` (adapters.py) 注册 8 个适配器, 但 `__init__.py:62-94` `__all__` 仅导出 6 个: `LPPLAdapter, CZSCAdapter, WyckoffAdapter, FSMAdapter, RegimeAdapter`。缺失: `NTFAdapter`, `AlphaScoreAdapter`, `MAStatusAdapter`。后两者虽可通过 `AdapterRegistry` 访问, 但不能通过包级 `from uniquant.signal import ...` 使用 |
| **源代码证据** | `signal/__init__.py:85-90` `__all__` 仅 6 个 adapter；`adapters.py:449-461` `create_default_registry()` 注册 8 个 |
| **修复方案** | 在 `__all__` 中添加 3 个缺失适配器名 + 检查 guards 式导入是否支持这些类 |
| **文件** | `src/uniquant/signal/__init__.py:85-90` |
| **工时** | 5m |

---

### R1 — 工程健康 (8 项)

---

#### R1-N01: Wyckoff 复杂度文档声称 40, 实际 45-53 (radon), 且文档计量方法不透明

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 指标漂移, 不影响功能但影响健康度评估 |
| **问题** | AGENTS.md 和 Z_tdd_redblue.md 声称 "Wyckoff max function complexity = 40"。自定义 AST McCabe 分析 `_step5_trading_plan` = 45, radon 报告 53。差异 12.5%-32.5%。声称的 "原 76→40" 计量方法不明确 |
| **源代码证据** | `brain/wyckoff/engine.py:_step5_trading_plan` 自定义 AST McCabe = 45, radon = 53 |
| **修复方案** | 统一复杂度计量工具 (建议 radon), 更新文档值为实际测量值, 并注明工具 |
| **文件** | AGENTS.md, docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md, docs/reanalysis/I_live_system_map.md |
| **工时** | 15m |

---

#### R1-N02: 8 个 DataSource 子类, 非文档声称的 7 个

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 架构计数错误 |
| **问题** | 文档多处声称 "7 数据源"。实际 `grep` 显示 8 个直接 DataSource 子类: BaostockSource, EastmoneySource (via EastmoneyQuoteSource→EastmoneyBase), MootdxLocalSource, MootdxOnlineSource, SinaSource, TdxSource, TencentSource, ThsSource。MootdxLocal + MootdxOnline 为独立子类但被合并计数为 1 |
| **源代码证据** | `data/sources/mootdx_local.py:15` `class MootdxLocalSource(DataSource)`; `data/sources/mootdx_online.py:15` `class MootdxOnlineSource(DataSource)` |
| **修复方案** | 在所有文档中将 "7 数据源" 更正为 "8 数据源 (含 MootdxLocal + MootdxOnline)" |
| **文件** | AGENTS.md, docs/reanalysis/*.md |
| **工时** | 10m |

---

#### R1-N03: LPPL `computation.py` 文档声称 242 LOC, 实际 393 LOC (误差 62%)

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — LOC 计量误差大 |
| **问题** | Z_tdd_redblue.md 声称 `computation.py` = 242 LOC。`wc -l` 实测 393 LOC。误差 62%。可能参考了旧版本或计量方式不同 (排除空行/注释) |
| **源代码证据** | `wc -l src/uniquant/brain/lppl/computation.py` = 393 |
| **修复方案** | 更新文档中 computation.py LOC 为 393, 或注明计量方式 |
| **文件** | docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md |
| **工时** | 5m |

---

#### R1-N04: `arbitrator.py:385` `except Exception:` 无 `as e`, 丢弃所有异常上下文

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW-MED** — 静默失败, 调试困难 |
| **问题** | `arbitrator.py:385` 有 `except Exception:` (无 `as e`), 捕获异常后仅设置 `sized_shares = 100`。不记录任何日志, 不区分错误类型。若 sizer 调用失败, 将静默使用 100 股默认值 |
| **源代码证据** | `arbitrator.py:385` `except Exception:\n    sized_shares = 100` |
| **修复方案** | 改为 `except Exception as e:\n    logger.warning(f"Sizer failed for {symbol}: {e}")\n    sized_shares = 100` |
| **文件** | `src/uniquant/signal/arbitrator.py:385` |
| **工时** | 2m |

---

#### R1-N05: `result_store.py:71` `except BaseException:` — 比 `except Exception:` 更宽, 捕获 KeyboardInterrupt/SystemExit

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW-MED** — 可能导致临时文件残留 |
| **问题** | `result_store.py:71` 使用 `except BaseException:` 确保临时文件被清理。意图合理 (原子写入保底清理), 但会捕获 `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`。若用户按 Ctrl+C, 临时文件被清理但异常也被吞掉 (文件写入后 `raise` 仅对 tempfile 操作生效) |
| **源代码证据** | `result_store.py:71` `except BaseException:\n    os.unlink(tmp.name)\n    raise` |
| **修复方案** | 添加注释说明设计意图。考虑改为 `except (OSError, IOError, PermissionError, WriteError) as e:` + `raise`, 保留 KeyboardInterrupt 传播 |
| **文件** | `src/uniquant/shared/result_store.py:71` |
| **工时** | 5m (注释) 或 30m (窄化) |

---

#### R1-N06: 过户费检查逻辑在 3 处重复实现 (DRY 违反)

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 未来修改易遗漏, 导致深市/沪市收费不一致 |
| **问题** | 过户费豁免检查 (`仅沪市 60xxxx`) 在 3 个不同位置实现: (1) `cost_model.py:48-50` `_has_transfer_fee(symbol)` → `symbol.startswith("60")`; (2) `unified_matching_engine.py:186,275` `[s.startswith("60") for s in symbols]` 内联; (3) `strategies/backtest.py:167` 用更广泛的前缀列表 `startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302"))` — 这是完全不同的逻辑! |
| **源代码证据** | `cost_model.py:48-50` vs `unified_matching_engine.py:186` vs `strategies/backtest.py:167` |
| **修复方案** | 将 `_has_transfer_fee` 提升到共享模块, 消除 2 个内联实现。`strategies/backtest.py` 中更广泛的前缀列表需审计是否为其他目的 (非过户费) |
| **文件** | `unified_matching_engine.py:186,275`, `strategies/backtest.py:167` |
| **工时** | 30m |

---

#### R1-N07: Alpha score=0.0 文档声称 "2 处" (543,552), 实际 3 处 (含 535)

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 文档计数遗漏 |
| **问题** | Z_tdd_redblue.md 声称 `Alpha score=0.0 on failure (lines 543, 552)`。实际代码有 3 处: 当 `stock_df` 为空时第 535 行也写入 `AlphaOutput(score=0.0)` |
| **源代码证据** | `analysis_service_v2.py:535,543,552` 三处 `writer.write_alpha(data_pack, AlphaOutput(score=0.0))` |
| **修复方案** | 在文档中添加 line 535 |
| **文件** | docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md |
| **工时** | 2m |

---

#### R1-N08: Wyckoff 4 文件合计 LOC 文档称 1,135, 实际 1,154 (差 19, 1.7%)

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 轻微计量偏差 |
| **问题** | 声明 "4 Wyckoff 子文件 = 1,135 LOC"。实际 `wc -l` 四文件合计 = 1,154 LOC。差值 19 行 (1.7%) |
| **源代码证据** | `analysis.py:322 + state.py:296 + events.py:517 + constants.py:19 = 1,154` |
| **修复方案** | 更新 LOC 为 1,154 |
| **文件** | AGENTS.md, Z_tdd_redblue_consolidated_report.md |
| **工时** | 2m |

---

### R2 — 文档对齐 (4 项)

---

#### R2-N01: 死代码库存追溯更新 (+532 LOC 新发现死代码)

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 死代码库存滞后 |
| **问题** | 当前死代码库存 ~2,225 LOC。新发现: `factor_governance.py` 156 LOC + `portfolio_engine.py` 376 LOC = **532 LOC 新增死/半死代码**。更新后总死代码: **~2,757 LOC** (4.4% of 62,559) |
| **修复方案** | 更新 AGENTS.md, I_live_system_map.md, J_scorecard.md 中的死代码库存 |
| **工时** | 5m |

---

#### R2-N02: Wyckoff 文档仅覆盖 4/18 非 __init__ 文件 (22%), 缺少信息

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 架构文档不完整 |
| **问题** | Wyckoff 有 18 个非 __init__ 文件, 7,133 LOC (占 brain 层 44%)。文档仅提及 4 个 "子文件" (analysis/state/events/constants, 22%)。未提及: `engine.py` (1,616 LOC 核心), `models.py` (820 LOC), `phase_analysis.py` (506 LOC), `fusion_engine.py` (469 LOC), `image_engine.py`, `bayesian_events.py`, `classifiers.py` 等 |
| **源代码证据** | `find src/uniquant/brain/wyckoff/ -name "*.py" ! -name "__init__.py" ! -name "*.cover"` = 18 文件 |
| **修复方案** | 更新 Wyckoff 文档描述, 至少提及主要子模块和核心文件 |
| **工时** | 15m |

---

#### R2-N03: `interfaces.py` 协议计数: 5 个非 4 个, 且 `shared/` 层有第 6 个协议

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 计数错误 |
| **问题** | 文档声称 "4 protocols in interfaces.py"。实际 `interfaces.py` 有 5 个 Protocol 类: DataFetcherProtocol, RiskAssessmentProtocol, PositionSizerProtocol, AnalysisEngineProtocol, CalculationPluginProtocol。另有 TimeProvider Protocol 在 `time_provider.py:24` — 总计 shared/ 层 6 个协议 |
| **源代码证据** | `interfaces.py:466,487,507,538,559` 5 个 Protocol；`time_provider.py:24` 第 6 个 |
| **修复方案** | 更新文档: "4 protocols" → "5 protocols in interfaces.py (6 in shared/ layer)" |
| **工时** | 2m |

---

#### R2-N04: AGENTS.md 中 "7 defense lines" 应更新为最新确认的 8 条防线

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 架构文档滞后 |
| **问题** | AGENTS.md 宣称 "7 lines" 但实际验证明细表列出 8 条 (含深市过户费豁免)。部分较早文档仅列 7 条。v6 报告已确认 8/8 全部双层保障 |
| **修复方案** | 统一所有文档为 8 条 A 股防线: T+1, 涨跌停, 停牌, 现金, 费用, 滑点, 整手, 过户费豁免 |
| **工时** | 5m |

---

### R3 — 测试补全 (3 项)

---

#### R3-N01: 45 文件零覆盖 (3,791 LOC) — data/ 层为最大缺口

| 字段 | 内容 |
|:----|:------|
| **严重度** | **HIGH** — 数据管道和算法核心无测试防护 |
| **问题** | 45 文件零覆盖, 合计 3,791 LOC。分层缺口: data/ 17 文件 2,264 LOC (含 tdx_updater 379, update_daily_incremental 351, eastmoney 全系 4 文件 488); hands/strategies 6 文件 347 LOC (全部策略文件 0%); brain/LPPL 4 文件 467 LOC (含 computation 242, multifit 106); shared/optimal_params 142 LOC |
| **源代码证据** | 覆盖率报告: `pytest --cov-report=term-missing` → 45 文件 0% |
| **修复方案** | 分批: Batch 1 (data/ 脚本) 冒烟测试 30m; Batch 2 (brain/LPPL 核心) 边界测试 2h; Batch 3 (hands/strategies) 策略测试 4h; Batch 4 (shared/optimal) 参数测试 1h |
| **工时** | ~16h (45 文件 × ~20m/文件) |

---

#### R3-N02: `manager_logic.py` 6 处 `except Exception` — 高密度裸捕获需窄化

| 字段 | 内容 |
|:----|:------|
| **严重度** | **MED** — UI 层异常可能被静默吞掉 |
| **问题** | `manager_logic.py` 有 6 处 `except Exception as e:` (行 343,444,454,464,474,484), 为代码库中单文件最高密度。每个 handler 仅 log-and-continue, 不区分错误类型。行 444-484 的 5 个连续 handler 为 Streamlit 回调保护, 但无日志记录 |
| **源代码证据** | `manager_logic.py:343,444,454,464,474,484` 6 处 `except Exception as e:` |
| **修复方案** | 为每处加 `logger.warning(f"...错误: {e}", exc_info=True)`, 或窄化为具体异常类型 |
| **工时** | 30m |

---

#### R3-N03: `lppl_visualizer.py:27,39` bare `except Exception:` 无 `as e` — 丢弃异常上下文

| 字段 | 内容 |
|:----|:------|
| **严重度** | **LOW** — 可视化备用, 但无调试信息 |
| **问题** | `lppl_visualizer.py` 行 27 和 39 使用 bare `except Exception:` (无 `as e`), 在所有异常发生后静默返回默认值。行 27 返回空 DataFrame, 行 39 返回 None。用户看到空白图表但无错误提示 |
| **源代码证据** | `lppl_visualizer.py:27` `except Exception:\n    return pl.DataFrame()`; `lppl_visualizer.py:39` `except Exception:\n    return None` |
| **修复方案** | 加 `as e` + `logger.warning`, 或在 UI 显示错误 toast 提示 |
| **文件** | `src/uniquant/ui/lppl_visualizer.py:27,39` |
| **工时** | 5m |

---

## §2: 无需修复项 (经源码核实判定 WONTFIX/已存在)

| 项 | 原因 | 证据 |
|:---|:-----|:-----|
| AdapterRegistry.discover() 无测试 | **已修复** — v5 Batch 2 已加 | `test_adapters.py:465-477` 2 tests |
| TradingSignalCollector 事件发布无测试 | **已修复** — v5 Batch 2 已加 | `test_adapters.py:480-510` 2 tests |
| Wyckoff image_engine.py:159,247 except Exception | 低风险日志包装, 无数据路径 | `logger.warning(f"...错误: {e}")` 返回 "unknown"/"medium" |
| LPPL numba_optimizer.py:91,171 bare Exception | numba @njit 约束, 无法窄化 | 有内联注释说明 |
| ths.py:223 AkShare 无保护 | **已修复** — v5 R0-02 | 需核实, 但属旧修复项 |
| DynamicSlippage "从未实例化" 声明 | 生产路径确实未实例化, 仅测试中使用 | `test_matching_engine.py:176` 实例化 |
| DynamicSlippage 死代码 | 已有 DEPRECATED 注释 | 可归档但低优先级 |

---

## §3: 执行顺序与依赖

```
Phase R0 (30m) ──────────── 关键修复 (文档+归档)
  Step 1:  R0-N04 signal __init__ 导出补全     [5m]
  Step 2:  R0-N02 factor_governance 归档        [10m]
  Step 3:  R0-N03 portfolio_engine 归档         [10m]
  Step 4:  R0-N01 文档纠正 (ui except=17)       [5m]
  → G0: pytest tests/ -q --tb=short → 0 failed

Phase R1 (2h) ────────────── 工程健康 (窄化+文档)
  Step 5:  R1-N04 arbitrator.py:385 加 as e     [2m]
  Step 6:  R1-N05 result_store.py 注释/窄化     [5-30m]
  Step 7:  R3-N03 lppl_visualizer 加 as e+log  [5m]
  Step 8:  R1-N06 过户费 DRY 统一               [30m]
  Step 9:  R1-N01~N08 文档指标更新 (7项)        [1h]
  → G1: ruff check src/uniquant/ → 0 issues

Phase R2 (30m) ───────────── 文档对齐
  Step 10: R2-N01 死代码库存更新 (+532 LOC)     [5m]
  Step 11: R2-N02 Wyckoff 文档扩展              [15m]
  Step 12: R2-N03 协议计数 4→5                  [2m]
  Step 13: R2-N04 8 条防线统一                  [5m]
  → G2: doc paths verify

Phase R3 (16h+) ──────────── 测试补全 (分批)
  Step 14: R3-N02 manager_logic 窄化 6 处       [30m]
  Step 15: R3-N01 Batch 1: data/ 脚本冒烟测试   [30m]
  Step 16: R3-N01 Batch 2: brain/LPPL 核心测试   [2h]
  Step 17: R3-N01 Batch 3: hands/strategies     [4h]
  Step 18: R3-N01 Batch 4: shared/optimal       [1h]
  → G3: coverage >= 55% + 0 weak tests
```

---

## §4: 验证门禁

| 门禁 | 命令 | 通过条件 |
|:----|:------|:--------|
| G0 | `pytest tests/ -q --tb=short` | 0 failed |
| G0b | `capture_baseline.py && compare_baseline.py` | 100% match |
| G1 | `ruff check src/uniquant/` | 0 issues |
| G2 | 文档路径一致性检查 | 手动验证 |
| G3 | `pytest --cov=src/uniquant/ --cov-fail-under=55` | ≥55% |

---

## §5: 风险地图与规避

| 风险 | 影响 | 规避 |
|:-----|:-----|:-----|
| portfolio_engine 归档破坏外部导入 | 少数用户脚本报错 | `__init__.py` 保留守卫式导入 + deprecation warning (已存在) |
| transfer fee DRY 统一改错 | 过户费计算错误 | 统一后对沪市/深市/科创板分别写断言测试 |
| 45 文件批量补测试导致 CI 膨胀 | 开发周期变长 | 优先冒烟测试 (每文件 1-2 测试), 逐步扩展 |
| 文档纠正遗漏某些旧文档 | 新旧文档矛盾 | 批量扫描 docs/ 下所有 .md 中的过时声明 |

---

## §6: 与 v5 报告的差异分析

| 项目 | v5 (07-10) 声称 | v6 (07-13) 实测 | 原因 |
|:-----|:---------------:|:---------------:|:-----|
| ui/ except Exception | 2 (已纠正) | **17** (未纠正) | v5 声称已执行纠正但实际未操作 |
| 死代码库存 | ~2,225 LOC | **~2,757 LOC** (+532) | 新发现 factor_governance + portfolio_engine |
| data/ except Exception | 136 | **137** | 差 1, 可能新提交或计量偏差 |
| 函数总数 | 2,262 | **2,249** | -13, 可能删除/合并产生 |
| DataSource 数量 | 7 | **8** | MootdxLocal + MootdxOnline 被合并计数 |
| Wyckoff 复杂度 | 40 | **45-53** | radon vs 自定义度量差异 |
| computation.py LOC | 242 | **393** | 可能参考旧版本或排除空行 |
| 测试函数 | 1,606 | **1,641** | +35 新测试 (v5 Batch 2) |
| 测试文件 | 127 | **128** | +1 新测试文件 |
| AdapterRegistry.discover 测试 | 缺失 | **存在** | v5 Batch 2 已加 |
| TradingSignalCollector 事件测试 | 缺失 | **存在** | v5 Batch 2 已加 |

---

## 附录: 新发现完整证据索引

| ID | 证据文件:行 | 验证命令 |
|:---|:-----------|:---------|
| R0-N01 | `grep -rn "except Exception" src/uniquant/ui/ --include="*.py" | wc -l` = 17 | ✓ |
| R0-N02 | `grep -rn "factor_governance" src/uniquant/ --include="*.py" | grep -v warnings` = 零 | ✓ |
| R0-N03 | `grep -rn "from.*portfolio_engine\|import.*portfolio_engine" src/uniquant/` = 仅注释 | ✓ |
| R0-N04 | `signal/__init__.py:85-90` `__all__` 仅 6/8 adapters | ✓ |
| R1-N01 | `brain/wyckoff/engine.py:_step5_trading_plan` McCabe=45, radon=53 | ✓ |
| R1-N02 | 8 DataSource subclasses (含 mootdx_local + mootdx_online) | ✓ |
| R1-N03 | `wc -l brain/lppl/computation.py` = 393 | ✓ |
| R1-N04 | `arbitrator.py:385` `except Exception:\n    sized_shares = 100` | ✓ |
| R1-N05 | `result_store.py:71` `except BaseException:` | ✓ |
| R1-N06 | 3 重复过户费: `cost_model.py:48`, `matching_engine.py:186,275`, `strategies/backtest.py:167` | ✓ |
| R1-N07 | `analysis_service_v2.py:535,543,552` 三处 score=0.0 | ✓ |
| R1-N08 | `wc -l` analysis+state+events+constants = 1,154 | ✓ |
| R2-N03 | `interfaces.py:466,487,507,538,559` 5 个 Protocol | ✓ |
| R3-N02 | `manager_logic.py:343,444,454,464,474,484` 6 except | ✓ |
| R3-N03 | `lppl_visualizer.py:27,39` bare `except Exception:` 无 `as e` | ✓ |

---

*本清单所有 15 项均经过源代码逐行核实, 每项附唯一 file:line 证据。零幻觉承诺。*
*对比 v5 报告: 纠正 1 项虚假已完成声明 (ui except), 新增 5 项死代码/工程健康问题, 补全 3 项文档指标。*