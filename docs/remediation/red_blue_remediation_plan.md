# UniQuant 红蓝对抗修复执行计划

> **生成**: 2026-07-09 | **基于**: 7 轮红蓝对抗分析 + 逐代码排查  
> **前置阅读**: `docs/reanalysis/Z_final_synthesis_20260709.md`, `docs/reanalysis/Z_7round_conversation_summary.md`, `docs/remediation/v3_final_execution_plan.md`  
> **修复原则**: 研究平台优先、测试捆绑代码、冲突文件串行执行、每阶段验收门禁  
> **总工时**: 28 人时 (P0-P2) | 挂钟: ~12h (2 工程师 1.5 天)

---

## 第 0 章：新增红蓝发现与原计划对照

以下是从红蓝对抗中新发现的、**原 v3 计划未覆盖**的修复项：

| ID | 红蓝发现 | 严重度 | 工时 | 原计划遗漏原因 |
|---|---|---|---|---|
| **RB-01** | `unified_engine.py:485` Look-ahead bias: rolling().mean() 含当日成交量 -> 滑点偏低 | **HIGH** | 1 行/5m | 测试只验证方向性不验证 ADV 计算 |
| **RB-02** | `research_pipeline.py:491-519` run_batch() 多线程共享属性 | **HIGH** | 4h | 单标的测试从不触发竞争 |
| **RB-03** | `akshare_wrapper.py:215` except Exception 吞异常 -> @retry 永不触发 | **HIGH** | 1 行/1m | v3 #10 只关注了 pipeline except |
| **RB-04** | `unified_matching_engine.py:178-271` 撮合层无 volume=0 检查 | **MED** | 2h | 对抗前被认为 7/7 防线双层 |
| **RB-05** | `matching_engine.py:185,271` + engine.py 深市多收过户费 | **LOW** | 1h | 只关注 cost_model 忽略引擎层漂移 |
| **RB-06** | adapters.py LPPL/Regime 文档阈值错误; quality.py 死代码 | **LOW** | 1h | 信号系统审计前未交叉验证 |
| **RB-07** | signal/quality.py 从未被任何代码调用 | **LOW** | 5m | 未做交叉引用分析 |
| **RB-08** | base.py with_circuit_breaker 定义了但未使用 | **MED** | 1h | 未反向追踪熔断器路径 |

---

## 第 1 章：文件冲突矩阵

| 冲突组 | 文件 | 冲突任务 | 解决策略 |
|---|---|---|---|
| **A** | `unified_matching_engine.py` | RB-04(停牌) + RB-05(过户费) | 串行: RB-04->RB-05 |
| **B** | `unified_engine.py` | #23(基准) + RB-01(ADV) + #21(敏感度) | 串行: RB-01->#23->#21 |
| **C** | `research_pipeline.py` | #10(except窄化) + RB-02(线程安全) | 串行: #10->RB-02 |
| **D** | `adapters.py` | RB-06(文档) + #19(测试) + #50(自动发现) | 串行: RB-06->#19->#50 |
| **E** | `data/utils/akshare_wrapper.py` | RB-03(retry吞异常) | 独立文件 |
| **F** | `composer.py` | #2(fillna) | 独立文件 |
| **G** | `eastmoney_base.py` | RB-08(熔断) + SSL verify | 串行: SSL->熔断 |

---

## 第 2 章：Phase 0 — 核心修复

> **时间**: 4h 挂钟, 10 人时  
> **验收**: `pytest tests/ -q --tb=short` -> 0 failed  
> **基线**: `python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py` -> 100%

### P0-01: [1 行] AlphaScore 0.0->SELL (原 Bug#1)

**文件**: `src/uniquant/signal/adapters.py:362`

```
elif score < 0.3:
```
-->
```
elif 0 < score < 0.3:
```

**测试**: score=0.0 -> result is None (不产生信号)

**工时**: 5m (含测试 15m)

---

### P0-02: [1 行] avg_daily_volume Look-ahead (RB-01)

**文件**: `src/uniquant/hands/backtest/unified_engine.py:485`

```
df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()
```
-->
```
adv = df["volume"].rolling(20, min_periods=1).mean()
df["avg_daily_volume"] = adv.shift(1).fillna(adv)
```

**测试**: 验证 avg_daily_volume[t] 不包含 volume[t]

**工时**: 5m (含测试 30m)

---

### P0-03: [1 行] AkShareWrapper 不吞异常 (RB-03)

**文件**: `src/uniquant/data/utils/akshare_wrapper.py:215-220`

```
except Exception as e:
    logger.error(f"Error calling ak.{method_name}: {e}")
    self._initialized = False
    self._update_method_stats(method_name, False)
    time.sleep(random.uniform(2, 5))
    return None
```
-->
```
except Exception as e:
    logger.error(f"Error calling ak.{method_name}: {e}", exc_info=True)
    self._initialized = False
    self._update_method_stats(method_name, False)
    time.sleep(random.uniform(2, 5))
    raise
```

**需检查所有 12+ 调用点** 是否在 try/except 内调用 call()

**工时**: 1m (调用点审计 15m)

---

### P0-04: [3 行] fillna(0.0)->fillna(np.nan) (原 Bug#2)

**文件**: `src/uniquant/brain/factors/composer.py:183,204,276`

```
return z_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
```
-->
```
return z_df.replace([np.inf, -np.inf], np.nan)
```

**下游安全验证**: _build_composite_frame 用 fill_value=0.0; StockScreener 有 dropna; FactorAnalyzer 用 skipna=True

**工时**: 3m (含验证 15m)

---

### P0-05: [1 行] eastmoney SSL verify=False (v3 #8)

**文件**: `src/uniquant/data/sources/eastmoney_base.py:57`

```
verify=False
```
-->
```
verify=True
```

**工时**: 1m

---

### P0-06: [4h] run_batch() 线程安全 (RB-02)

**文件**: `src/uniquant/services/research_pipeline.py:491-519`

**问题**: `_run_single` 闭包捕获 self，多线程共享 self._metrics / self._event_bus / self._result_store

**修复**:

1. `self._metrics` -> 添加 `threading.Lock()` 保护，或每线程独立 InMemoryMetricsRecorder 实例后再 merge
2. `self._result_store.save()` -> 加文件锁或串行化
3. `np.random.seed(seed)` -> 不在 _run_single 内设置全局 seed
4. `logger.error(...)` -> 加 `exc_info=True`

**工时**: 4h (含测试)

---

### P0-07: [2h] 停牌撮合层缺失 (RB-04)

**文件**: `src/uniquant/hands/backtest/unified_matching_engine.py`

**问题**: fill_buy() 和 fill_sell() 不检查 volume=0

**修复**: 在 fill_buy() 中 limit_rejected 后加入:
```python
volume_zero = np.array([vol <= 0 for vol in volumes], dtype=bool)
rejected = limit_rejected | volume_zero
```

fill_sell() 同理

**测试**: 扩展 TestDefenseC 从 1 个到 3+ 个测试

**工时**: 2h

---

### P0-08: [1m] Pipeline except 窄化 (v3 #10)

**文件**: `src/uniquant/services/research_pipeline.py:495`

```
except Exception as e:
```
-->
```
except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
```

**工时**: 1m

---

### P0-09: [30m] Wyckoff except 窄化 (v3 #4)

**文件**: `src/uniquant/brain/wyckoff/engine.py:251,260,1573,1588`

4 处 `except Exception:` -> 窄化为具体异常类型 + 加 `exc_info=True`

line 1588 最严重: 保护整个 scan_signal，失败时返回伪装正常的 error 结构体

**工时**: 30m

---

### P0-10: [1h] 熔断器启用 (RB-08)

**文件**: `src/uniquant/data/sources/base.py` + `eastmoney_base.py`

将 `with_circuit_breaker(fail_max=5, reset_timeout=30)` 应用到 EastmoneyBase._request()

**工时**: 1h

---

### Phase 0 验收门禁

```bash
pytest tests/ -q --tb=short                         # 0 failed
python3 scripts/capture_baseline.py && compare       # 100% match
python3 -c "import uniquant.shared, ..., uniquant.ui; print('OK')"
```

---

## 第 3 章：Phase 1 — 工程健康

> **时间**: 6h 挂钟, 12 人时  
> **验收**: `python3 scripts/staged_full_scan.py --stage canary --max-workers 4` -> 20/20 success  
> **Lint**: `ruff check src/uniquant/` -> 0 issues  

### P1-01: [2h] 深市过户费多收 (RB-05)

**文件**: `unified_engine.py:_calc_transfer_fee()` + `matching_engine.py:185,271`

**问题**: cost_model.py:48-50 规定 `_has_transfer_fee` 仅沪市(60xxxx)，但引擎和撮合图层对所有股票征收

**修复**: 在过户费计算点加 `symbol.startswith("60")` 判断

**工时**: 2h

### P1-02: [2h] Adapter 测试补全 (v3 #19)

**文件**: `tests/signal/test_adapters.py`

已有 62 测试。补全缺失边界：
1. AlphaScoreAdapter: score=0.0 返回 None
2. RegimeAdapter: FROZEN->HOLD (文档对齐)
3. LPPLAdapter: 验证不产生 BUY

**工时**: 2h

### P1-03: [2h] 敏感性扫描 + 基准指数 (v3 #21+#23)

**文件**: `src/uniquant/hands/backtest/unified_engine.py`

1. 扩展 sensitivity_scan(slippages, commissions)
2. benchmark_returns 参数集成至 run() + BacktestResult

**工时**: 2h

### P1-04: [2h] E2E 扩展 (v3 #33)

**文件**: `tests/test_e2e_pipeline.py` / `test_e2e_integration_qa.py`

新增: 停牌日无交易 / T+1 验证 / 多信号冲突 SelL 优先 / Look-ahead 防护验证

**工时**: 2h

### P1-05: [2h] 信号超时默认启用 (v3 #45)

**文件**: `src/uniquant/signal/arbitrator.py:39`

`DEFAULT_MAX_SIGNAL_AGE_SECONDS = 0.0` -> `= 86400` (24h)

**工时**: 5m (测试 2h)

### P1-06: [1h] 信号质量文档修正 (RB-06+RB-07)

**修正内容**:
1. LPPL 文档: "Safe->BUY" 改为 "从不产生 BUY，只产生 HOLD/Danger->SELL"
2. Regime 文档: "FROZEN->SELL" 改为 "FROZEN->HOLD, STRESSED->HOLD"
3. quality.py 文件头: 标记为 "当前未被生产代码调用"

**工时**: 1h

---

## 第 4 章：Phase 2 — 测试与文档对齐

> **时间**: 2h 挂钟, 6 人时  
> **验收**: `pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=50` -> >=50%  

### P2-01: [1h] 能力矩阵 5 项升格

升级: #4(权重优化), #6(敏感性), #17(回测对比), #18(组合优化器) ⚠️->✅; #8(组合回测) ❌->⚠️

**文件**: AGENTS.md, Z_final_synthesis.md, J_scorecard.md

### P2-02: [1h] 7 条防线文档修正

C. 停牌 ✅->⚠️; E. 成本 备注漂移; G. 整手 按板块

**文件**: docs/reanalysis/Z_final_synthesis.md

### P2-03: [2h] 全面文档漂移修正

扫描全部过时声明: 56 弱测试, Wyckoff 76, Adapter 29%, eastmoney 1094 LOC, mutmut 路径

**文件**: AGENTS.md + docs/reanalysis/*.md

### P2-04: [2h] 组合回测可行性研究

考古 PortfolioEngine (373 LOC) + 工作量估算 (40h) + 设计决策文档

**不实现，仅研究**

---

## 第 5 章：串行执行顺序

```
Phase 0 (4h) ───────────────────────────
  Step 1:  P0-03 (akshare_wrapper retry)     [1m]
  Step 2:  P0-05 (eastmoney SSL verify)      [1m]
  Step 3:  P0-04 (composer fillna x3)        [3m]
  Step 4:  P0-01 (adapters alpha=0.0)        [1m + 测试 15m]
  Step 5:  P0-02 (engine ADV look-ahead)     [1m + 测试 30m]
  Step 6:  P0-08 (pipeline except)           [1m]
  Step 7:  P0-09 (wyckoff except x4)         [30m]
  Step 8:  P0-10 (circuit breaker启用)        [1h]
  Step 9:  P0-07 (matching 停牌)              [2h]
  Step 10: P0-06 (pipeline 线程安全)           [4h]
  -> G0: pytest + baseline

Phase 1 (6h) ───────────────────────────
  Step 11: P1-01 (过户费)                    [2h]
  Step 12: P1-05 (信号超时)                   [2h]
  Step 13: P1-02 (Adapter 测试)              [2h]
  Step 14: P1-03 (敏感性+基准)                [2h]
  Step 15: P1-04 (E2E 扩展)                  [2h]
  Step 16: P1-06 (文档+quality)              [1h]
  -> G1: canary scan + ruff

Phase 2 (2h) ───────────────────────────
  Step 17: P2-01+02+03 (全面文档修正)          [4h]
  Step 18: P2-04 (组合回测研究)               [2h]
  -> G2: coverage + lint
```

---

## 附录：验证门禁速查

| 门禁 | 命令 | 通过条件 |
|---|---|---|
| G0 | `pytest tests/ -q --tb=short` | 0 failed |
| G0b | `capture_baseline.py && compare_baseline.py` | 100% match |
| G1 | `staged_full_scan.py --stage canary --max-workers 4` | 20/20 success |
| G1b | `ruff check src/uniquant/` | 0 issues |
| G2 | `pytest --cov-fail-under=50` | >=50%, 0 failed |
