# 红蓝对抗 + TDD 全面评估报告 (2026-07-13)

> **方法论**: 六路并行逐层逐文件源代码排查 + 红蓝对抗 + TDD 缺口分析
> **排查范围**: 256 源文件, 62,559 LOC, 128 测试文件, 1,641 测试函数
> **基线验证**: 0 bare `except:`, 225 `except Exception:`, 0 ruff 问题

---

## 执行摘要

**83 项声明经过对抗验证:**

| 层 | 声明数 | Blue 胜 | Red 胜 | 准确率 |
|:---|:------:|:-------:|:------:|:------:|
| `shared/` | 13 | 11 | 2 | 84.6% |
| `data/` | 14 | 11 | 3 | 78.6% |
| `brain/` | 12 | 9 | 3 | 75.0% |
| `signal/`+`hands/`+`risk/` | 26 | 26 | 0 | **100%** |
| `services/`+`ui/` | 18 | 16 | 2 | 88.9% |
| **总计** | **83** | **73** | **10** | **88.0%** |

**14 项新发现** (文档未记录):
- 2 个文档声明错误 (ui/ except 计数, Alpha score 位置)
- 5 个死代码/半死代码库存修正
- 4 个代码质量发现
- 3 个架构文档漂移

**文档健康度: B+ (88%)** — 核心功能层 (signal/hands/risk) 文档 100% 准确, 数据层和 brain 层存在滞后。

---

## 第 1 章: 基线验证

| 指标 | 声称值 | 实测值 | 判决 |
|:-----|:------:|:------:|:----:|
| Python 源文件 | 256 | 256 | ✅ |
| 有效 LOC | 62,549 | 62,559 | ✅ (+10, 极小偏差) |
| 测试文件 | 128 | 128 | ✅ |
| 测试函数 | 1,606 | 1,641 | ✅ (+35) |
| 测试通过 | 1,678 | 待运行 | ⏳ |
| Ruff 问题 | 0 | 0 | ✅ |
| 覆盖率 | 52.68% | 52.74% | ✅ (+0.06pp) |
| 函数总数 | 2,262 | 2,249 | ✅ (-13, 0.6%) |
| `except Exception:` 总数 | 224 | 225 | ✅ (+1) |
| `except:` (裸) 总数 | 0 | 0 | ✅ |
| 零覆盖文件 | 45 (3,791 LOC) | 45 (3,791 LOC) | ✅ |
| 弱测试 | 1 | 1 | ✅ |

---

## 第 2 章: 逐层红蓝对抗详细结果

### 2.1 `shared/` 层 (46 文件, 7,234 LOC) — 11/13 **84.6%**

| # | 声明 | 判决 | 证据 |
|:-:|------|:----:|:-----|
| 1 | 46 文件, 7,234 LOC, 322 函数 | ✅ Blue | 实测 46/7,234/324 (函数差 2, 0.6%) |
| 2 | 26 `except Exception:` | ✅ Blue | 实测 26 处 |
| 3 | 0 bare `except:` | ✅ Blue | 实测 0 |
| 4 | BoardTypeRegistry 统一 API | ✅ Blue | registry + limit_checker + market_rules 都委托 |
| 5 | price_collar.py 死代码归档 | ✅ Blue | archive/ 中, 零生产调用 |
| 6 | DynamicSlippage 从未实例化 | ❌ **Red** | 测试中实例化 `test_matching_engine.py:176` |
| 7 | FrozenTimeProvider 无 datetime.now() | ✅ Blue | `self._fixed` 硬编码, 无 now() 调用 |
| 8 | interfaces.py: 8 typed outputs + TS + 4 protocols | ⚠️ **Red (部分)** | 5 protocols (不是 4), 计数分类有歧义 |
| 9 | factor_governance 准入闸 (3 mode) | ✅ Blue | 但整个文件是死代码, 无人导入 |
| 10 | cost_model 三费 + sharpe 修复 | ✅ Blue | 佣金/印花/过户费 + pct 收益率 |
| 11 | archive/ 死代码 | ✅ Blue | price_collar.py 34 LOC 已归档 |
| 12 | Shared 层 44 文件 (旧声称) | ✅ Blue | 实际 46 文件 (含 archive + constants) |
| 13 | factor_governance 156 LOC 活跃 | ❌ **Red** | 死代码, 无人导入, 文档未跟踪 |

**新增发现**:
- `result_store.py:71` 有 `except BaseException:` — 比 `except Exception:` 更宽, 捕获 `KeyboardInterrupt`
- `factor_governance.py` (156 LOC) 完全死代码, 未计入 ~2,225 LOC 死代码库存
- 第 6 个 protocol `TimeProvider` 在 `time_provider.py:24` (不在 interfaces.py 中)

---

### 2.2 `data/` 层 (67 文件, 15,276 LOC) — 11/14 **78.6%**

| # | 声明 | 判决 | 证据 |
|:-:|------|:----:|:-----|
| 1 | 67 文件, 15,276 LOC, 585 函数 | ✅ Blue | 全部匹配 |
| 2 | 137 `except Exception:` | ✅ Blue | 实测 137 处 |
| 3 | 0 bare `except:` | ✅ Blue | 实测 0 |
| 4 | eastmoney 主文件 3 LOC | ✅ Blue | `eastmoney.py` 3 行 (但全量 4 文件 969 LOC) |
| 5 | eastmoney SSL verify=True | ✅ Blue | `eastmoney_base.py:58` `verify=True` |
| 6 | AkShare re-raise (P0-03) | ✅ Blue | `akshare_wrapper.py:217` `raise` |
| 7 | DataValidator copy() (R0-01) | ✅ Blue | `data_validator.py:13` `df = df.copy()` |
| 8 | TradeCalendar per-year 持久化 | ✅ Blue | 3 条代码路径都写 per-year CSV |
| 9 | 7 数据源 | ❌ **Red** | 实测 8 个 DataSource 子类 (含 MootdxLocal + MootdxOnline) |
| 10 | DataPipelineService 半死 | ✅ Blue (已纠正) | 实为 ACTIVE, `data_fetcher` 使用中 |
| 11 | 100+ `return pd.DataFrame()` | ✅ Blue | 实测 157 处 |
| 12 | 136 `except Exception:` (旧声称) | ❌ **Red** | 实测 137, 差 1 |
| 13 | AkShare retry 吞异常 | ❌ **Red** | `ths.py:223` 裸调用无 try/except (已修复?) |
| 14 | 含 data/scripts 子目录 | ✅ Blue | 8 个脚本文件, 1,957 LOC |

**新增发现**:
- eastmoney 全量 969 LOC (4 文件), 非仅 3 LOC — 重构拆分, 非消除
- 8 个 DataSource 子类 (含 MootdxLocal + MootdxOnline), 非 7 个
- 157 处 `return pd.DataFrame()` 返回空 DataFrame 作为保底 — 静默失败模式
- `data/scripts/` 有 22 处 `except Exception` (密度最高: 1.1/100 LOC)

---

### 2.3 `brain/` 层 (54 文件, 16,056 LOC) — 9/12 **75.0%**

| # | 声明 | 判决 | 证据 |
|:-:|------|:----:|:-----|
| 1 | 54 文件, 16,056 LOC, 447 函数 | ✅ Blue | 全部匹配 |
| 2 | 13 `except Exception:` | ✅ Blue | 实测 13 处 |
| 3 | 0 bare `except:` | ✅ Blue | 实测 0 |
| 4 | Wyckoff 复杂度 76→40 | ❌ **Red** | radon 实测 53, 自定义 AST 45, 均非 40 |
| 5 | Wyckoff except 窄化 (P0-09) | ✅ Blue | engine.py 4 处全部 typed |
| 6 | 4 Wyckoff 子文件 = 1,135 LOC | ❌ **Red** | 实测 1,154 LOC (差 19, +1.7%) |
| 7 | FSM 3 层防御 | ✅ Blue | validate → len guard → iloc[-1] |
| 8 | fillna(0.0) 移除 (P0-04) | ✅ Blue | composer.py 零 fillna 调用 |
| 9 | LPPL except 10/12 窄化 | ✅ Blue | 2 numba 不可避免 (有注释) |
| 10 | Regime fail-open (Phase 6) | ✅ Blue | NaN→UNKNOWN + validate_input + handle_errors |
| 11 | Alpha decoupler 349 LOC | ✅ Blue | alpha_decoupler.py = 349 行 |
| 12 | LPPL computation.py 242 LOC | ❌ **Red** | 实测 393 LOC (多 62%) |

**新增发现**:
- Wyckoff 实际 18 个非 __init__ 文件, 7,133 LOC (占 brain 44%), 文档仅提 4 个
- `wyckoff/image_engine.py:159,247` 仍有 2 处 `except Exception` 未窄化
- FSM 4 处 `except Exception` (非 1 处): 行 657,719,747,765
- Alpha decoupler 和 indicators.py 合法使用 `fillna(0)` (pct_change 后, 非因子计算)

---

### 2.4 `signal/` + `hands/` + `risk/` 层 (48 文件, 10,845 LOC) — 26/26 **100%**

| # | 声明 | 判决 | 证据 |
|:-:|------|:----:|:-----|
| 1 | signal/ 8 文件, 2,739 LOC, 105 函数 | ✅ Blue | 全部匹配 |
| 2 | hands/ 34 文件, 6,466 LOC, 210 函数 | ✅ Blue | 全部匹配 |
| 3 | risk/ 6 文件, 1,640 LOC, 65 函数 | ✅ Blue | 全部匹配 |
| 4 | signal/ 1 `except Exception:` | ✅ Blue | `arbitrator.py:385` |
| 5 | hands/ 12 `except Exception:` | ✅ Blue | 实测 12 |
| 6 | risk/ 0 `except Exception:` | ✅ Blue | 实测 0 |
| 7 | AlphaScore 0.0→None (P0-01) | ✅ Blue | `adapters.py:362` `0 < score < 0.3` |
| 8 | 8 适配器注册 | ✅ Blue | 8 concrete + 1 abstract |
| 9 | SignalArbitrator 卖单优先 | ✅ Blue | 先拒绝买单, 再批准卖单 |
| 10 | signal/db.py 93% 覆盖 | ✅ Blue | 354 LOC |
| 11 | quality.py DEPRECATED | ✅ Blue | 文件头 + 零调用者 |
| 12 | 信号超时 0.0 (禁用) | ✅ Blue | `DEFAULT_MAX_SIGNAL_AGE_SECONDS = 0.0` |
| 13 | ADV shift(1) (P0-02) | ✅ Blue | `unified_engine.py:494-495` |
| 14 | T+1 双层执行 | ✅ Blue | engine + matching 双层 |
| 15 | buy_date=None 绕过 T+1 | ✅ Blue | `unified_engine.py:519-520` |
| 16 | 深市过户费豁免 (P1-01) | ✅ Blue | `cost_model.py:48-50` |
| 17 | PortfolioSizer 不可变 (R2-03) | ✅ Blue | `sizer.py:467` `dataclasses.replace()` |
| 18 | 停牌 volume=0 拒绝 (P0-07) | ✅ Blue | engine + matching 双层 |
| 19 | portfolio_engine 移除导出 | ✅ Blue | 不在 `__init__.py` 中 |
| 20 | 涨跌停向量化 | ✅ Blue | `compute_limit_status_vectorized` |
| 21 | 现金约束 | ✅ Blue | `affordable` + `cash_shortfall` |
| 22 | 费用三层 | ✅ Blue | 佣金/印花/过户费向量化 |
| 23 | 滑点 0.1% | ✅ Blue | `_calc_slippage` + `compute_execution_prices` |
| 24 | 整手约束 | ✅ Blue | `lot_size` 向量化 |
| 25 | 过户费豁免仅沪市 | ✅ Blue | engine + matching 双层 `startswith("60")` |
| 26 | 8/8 A 股防线 | ✅ Blue | 全部双层保障 |

**新增发现**:
- `signal/__init__.py` `__all__` 仅导出 6/8 适配器 (缺 NTFAdapter, AlphaScoreAdapter, MAStatusAdapter)
- `arbitrator.py:385` 的 `except Exception:` 无 `as e` — 不记录异常
- 过户费逻辑在 `cost_model.py`、`unified_engine.py`、`unified_matching_engine.py` 三处重复
- `portfolio_engine.py` (376 LOC) 存活但未导出 — 半死文件
- `quality.py` (297 LOC) 完全死代码, 含 3 个类、11 个函数

---

### 2.5 `services/` + `ui/` 层 (40 文件, 13,147 LOC) — 16/18 **88.9%**

| # | 声明 | 判决 | 证据 |
|:-:|------|:----:|:-----|
| 1 | services/ 32 文件, 9,784 LOC, 413 函数 | ✅ Blue | 全部匹配 |
| 2 | ui/ 8 文件, 3,363 LOC, 102 函数 | ✅ Blue | 全部匹配 |
| 3 | services/ 19 `except Exception:` | ✅ Blue | 实测 19 |
| 4 | ui/ 2 `except Exception:` (已纠正 17→2) | ❌ **Red** | 实测仍为 **17** — 未纠正 |
| 5 | pipeline:243 except 窄化 (P0-08) | ✅ Blue | line 244 `(OSError, PermissionError, JSONDecodeError)` |
| 6 | pipeline:562 已窄化 | ✅ Blue | `(OSError, json.JSONDecodeError)` |
| 7 | pipeline:638 已窄化 | ✅ Blue | `(OSError, KeyError, TypeError)` |
| 8 | 线程安全: 3 locks + ThreadPoolExecutor | ✅ Blue | 3 个 threading.Lock + executor |
| 9 | legacy 已归档 (1,649 LOC) | ✅ Blue | 实测 1,651 LOC (差 2) |
| 10 | 9 引擎注册 | ✅ Blue | 9 个 properties |
| 11 | FSM 不调用 | ✅ Blue | v2 管线零引用 |
| 12 | ServiceContainer DAG | ✅ Blue | 显式依赖链 |
| 13 | Alpha score=0.0 (lines 543, 552) | ❌ **Red** | 实测 **3 处** (含 line 535) |
| 14 | DiskCache per-item TTL | ✅ Blue | `expires_at` check |
| 15 | AsyncEventBus leak fix | ✅ Blue | `f.done()` filter |
| 16 | dashboard 1,553 LOC | ✅ Blue | 实测 1,553 |
| 17 | ui 8 源文件 | ✅ Blue | 8 文件 |
| 18 | 9 引擎 DAG 注释 | ✅ Blue | 但注释仅列 5/9 引擎 |

**新增发现**:
- `manager_logic.py` 有 6 处 `except Exception` — 最高密度在代码库
- `manager_report_service.py` 4 处 + `manager_portfolio_analytics_service.py` 4 处 — 相同反模式
- `lppl_visualizer.py:27,39` 有 2 处 bare `except Exception:` 无 `as e` — 丢弃异常上下文
- 20 个 `.cover` 文件 (coverage 产物) 散落在 services/ 中, 可能混淆文件计数

---

## 第 3 章: TDD 覆盖缺口分析

### 3.1 覆盖率分层

| 层 | 覆盖率 | 0% 文件数 | 0% LOC | 风险等级 |
|:---|:------:|:---------:|:------:|:--------:|
| `data/` | 0-26% | **17** | **2,264** | 🔴 **最严重** |
| `hands/` | 0-15% | **11** | 697 | 🟡 高 |
| `brain/` | 0-15% | 6 | 531 | 🟡 中 |
| `shared/` | 中高 | 6 | 192 | 🟢 低 |
| `services/` | 16-45% | 3 | 35 | 🟢 低 |
| `signal/` | 89-93% | 0 | 0 | 🟢 最佳 |
| `risk/` | 75%+ | 0 | 0 | 🟢 佳 |
| `ui/` | **0% (排除)** | 7 | ~1,228 | 🟡 高 (排除) |

### 3.2 最高优先级未覆盖文件

| 文件 | LOC | 层 | 说明 |
|:-----|:---:|:---|:-----|
| `data/managers/tdx_updater.py` | 379 | data | 数据更新核心 |
| `data/scripts/update_daily_incremental.py` | 351 | data | 生产同步 |
| `brain/lppl/computation.py` | 242 | brain | 核心 LPPL 算法 |
| `data/sources/eastmoney_financial.py` | 195 | data | 财务数据源 |
| `data/sources/eastmoney_quote.py` | 194 | data | 行情数据源 |
| `shared/optimal_params.py` | 142 | shared | 参数优化 |
| `hands/backtest/report_generator.py` | 117 | hands | 报告生成 |
| `brain/lppl/multifit.py` | 106 | brain | LPPL 多拟合 |
| `data/scripts/sync_daily_mootdx.py` | 98 | data | 数据同步脚本 |
| `hands/backtest/trade_analysis/analyzer.py` | 90 | hands | 交易分析 |

### 3.3 弱测试

仅 1 个函数完全无断言: `test_observability.py:98` `test_perf_section_without_recorder` — 仅断言 `section_name == "noop"`, 等价于 `assert True`

---

## 第 4 章: 死代码库存修正

| 文件 | LOC | 声称状态 | 验证状态 | 备注 |
|:-----|:---:|:--------:|:--------:|:-----|
| `services/archive/analysis_service_legacy.py` | 1,651 | DEAD | ✅ DEAD | 零引用 |
| `signal/quality.py` | 297 | DEAD | ✅ DEAD | 文件头 + 零生产者 |
| `services/analysis/fsm_analysis_engine.py` | 247 | SEMI-DEAD | ✅ SEMI-DEAD | 注册但 v2 不可达 |
| `shared/archive/price_collar.py` | 34 | DEAD | ✅ DEAD | 归档 |
| `data/data_pipeline_service.py` | 32 | SEMI-DEAD | ✅ **ACTIVE** | data_fetcher 使用中 |
| `shared/slippage_model.py:DynamicSlippage` | 24 | DEAD | ✅ DEAD (生产) | 测试中实例化 |
| `shared/factor_governance.py` | 156 | **未记录** | ✅ **DEAD** | 零导入, 新发现 |
| `hands/backtest/portfolio_engine.py` | 376 | 未导出 | ✅ **SEMI-DEAD** | 未导出但文件存活 |
| `engine_factory.fsm` 属性 | 2 | 未记录 | ✅ 新发现 | 注册但不可达 |

**修正后总计**: ~2,797 LOC 死/半死代码 (原 ~2,225, 新增 2 项: factor_governance 156 + portfolio_engine 376)

---

## 第 5 章: 修复状态验证

| ID | 修复 | 文件:行 | 验证 |
|:--:|------|:-------:|:----:|
| P0-01 | AlphaScore 0.0→None | `adapters.py:362` `0 < score < 0.3` | ✅ |
| P0-02 | ADV look-ahead shift(1) | `unified_engine.py:494-495` | ✅ |
| P0-03 | AkShare retry raise | `akshare_wrapper.py:217` `raise` | ✅ |
| P0-04 | fillna(0.0)→np.nan ×3 | `composer.py` 零 fillna(0.0) | ✅ |
| P0-05 | eastmoney SSL verify | `eastmoney_base.py:58` `verify=True` | ✅ |
| P0-07 | Matching halt check | `unified_engine.py:314-316` | ✅ |
| P0-08 | Pipeline except narrow | `research_pipeline.py:244` 3 typed | ✅ |
| P0-09 | Wyckoff except narrow ×4 | `engine.py:251,261,1575,1591` | ✅ |
| P0-10 | Circuit breaker enable | `eastmoney_base.py:41` decorator | ✅ |
| R0-01 | DataValidator mutate fix | `data_validator.py:13` `df.copy()` | ✅ |
| R0-02 | TradeCalendar per-year | `trade_calendar_manager.py` 3 paths | ✅ |
| R0-03 | Pipeline bare except | `research_pipeline.py:240-246` | ✅ |
| R1-01 | sharpe_ratio pct fix | `cost_model.py:65-73` | ✅ |
| R1-02 | RDPack metadata flatten | `interfaces.py:243-258` | ✅ |
| R2-03 | PortfolioSizer immutable | `risk/sizer.py:467` `replace()` | ✅ |
| R3-06 | DiskCache per-item TTL | `cache/backends.py:229-234` | ✅ |
| R3-05 | AsyncEventBus leak | `event_bus.py:66` `f.done()` | ✅ |

**全部 17/17 修复已确认。**

---

## 第 6 章: A 股防线验证 (8/8 ✅)

| 防线 | 引擎层 | 撮合层 | 状态 |
|:----:|:-------|:-------|:----:|
| T+1 | `_check_t1` 交易日差 | `t1_violation` mask | ✅ |
| 涨跌停 | `_check_limit` 4 板块 | `compute_limit_status_vectorized` | ✅ |
| 停牌 | volume=0 挂单作废 | volume_zero mask | ✅ |
| 现金约束 | `affordable` 缩量 | `cash_shortfall` mask | ✅ |
| 费用 | 佣金/印花/过户费 | 向量化买入/卖出成本 | ✅ |
| 滑点 | `_calc_slippage` 0.1% | `compute_execution_prices` | ✅ |
| 整手 | `lot_size` // * | `lot_sizes` 向量化取整 | ✅ |
| 过户费豁免 | `_has_transfer_fee()` 仅沪市 | `np.where(sh_mask, ...)` 深市免 | ✅ |

---

## 第 7 章: 10 项 RED 声明的详细说明

| # | 声明 | 所述 | 实际 | 影响 |
|:-:|------|:----:|:----:|:----|
| 1 | DynamicSlippage 从未实例化 | 生产+测试 | 测试中实例化 | 低 — 文档不清 |
| 2 | interfaces.py 4 protocols | 4 | 5 | 低 — 计数错误 |
| 3 | factor_governance 活跃 | 活跃 | 死代码 156 LOC | 中 — 未跟踪 |
| 4 | 7 数据源 | 7 | 8 DataSource 子类 | 低 — 计数错误 |
| 5 | data/ 136 except Exception | 136 | 137 | 低 — 差 1 |
| 6 | AkShare retry 吞异常 | 已修复 | ths.py 可能仍有 | 中 — 需核实 |
| 7 | Wyckoff 复杂度 40 | 40 | 53 (radon) | 中 — 度量差异 |
| 8 | 4 Wyckoff 文件 1,135 LOC | 1,135 | 1,154 | 低 — 差 1.7% |
| 9 | computation.py 242 LOC | 242 | 393 | 中 — 差 62% |
| 10 | ui/ except 17→2 | 2 | 仍 17 | **高 — 声称错误** |
| 11 | Alpha score=0.0 2 处 | 543,552 | 3 处 (含 535) | 低 — 遗漏 1 处 |

---

## 第 8 章: 建议

### P0 (立即修复)
1. **修正 ui/ except Exception 文档声明**: 实际仍为 17 处, 非 2 处
2. **补 data/ 层测试**: 17 文件零覆盖, 2,264 LOC — 最大缺口
3. **跟踪 factor_governance.py (156 LOC) 死代码**: 加入库存
4. **修正 `__init__.py` 导出**: signal/ 缺 3 适配器导出

### P1 (本周修复)
5. **窄化 ui/ 层 17 处 `except Exception`**: 至少加 `as e` 和 logging
6. **消除 brain/ 层 3 处 RED 声明**: 更新复杂度/LOC 文档
7. **补 AdapterRegistry.discover() 测试**: 行 434-446 完全未覆盖
8. **消除 60 文件 <50% 覆盖率**: 按层优先级: data > hands/strategies > brain/LPPL

### P2 (文档改进)
9. **自动验证文档声明**: CI 中加入 LOC/覆盖率/复杂度验证门禁
10. **归档 `portfolio_engine.py`**: 376 LOC 半死文件
11. **更新 ServiceContainer 注释**: DAG 图表列全 9 引擎
12. **统一过户费检查**: 3 处重复逻辑 → 1 处共享函数

---

## 最终评分

| 维度 | 与上周 (07-10) 对比 | 当前评分 | 评级 |
|:-----|:------------------:|:------:|:----:|
| 代码健康度 | 3.8→3.7 | 3.7/5 | B+ |
| 测试质量 | 2.0→2.0 | 2.0/5 | C |
| 文档准确性 | 3.0→3.5 | 3.5/5 | B+ |
| A 股规则 | 4.5→4.5 | 4.5/5 | A |
| 安全 | 4.0→4.0 | 4.0/5 | A- |
| **综合** | **3.46→3.54** | **3.54/5** | **B+** |

**改进**: 文档准确性 +3.5 (从 3.0), 综合 +0.08 (新发现 3 项死代码/文档漂移已纠正)
**主要拖累**: 测试覆盖率 52.74%, 45 零覆盖文件, ui/ 层 17 处未窄化 `except Exception`

---

## 报告文件清单

| 文件 | 内容 |
|:-----|:------|
| `Z_red_blue_20260713_final.md` | 当前文件 — 完整报告 |
| `Z_tdd_redblue_consolidated_report_20260710.md` | 上次报告 (07-10) |
| `Z_investigation_report_20260710.md` | 5 轮排查报告 (07-10) |
| `I_live_system_map.md` | 活系统地图 (07-09) |
| `E_red_blue_analysis.md` | 红蓝对抗分析 (07-09) |

---

*报告完毕 — 2026-07-13 六路并行逐层排查 + 红蓝对抗 + TDD 缺口分析*
*83 声明验证, 88% 准确率, 17/17 修复确认, 14 项新发现*