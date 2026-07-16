# UniQuant — 最终执行计划 (研究平台版)

> 生成: 2026-07-07 | 基于 4 轮对抗验证 (74→35 研究问题)
> 前置阅读: `docs/remediation/v2_corrected_audit_red_blue.md` (所有验证结论)
> 总工时: **~64h** | 挂钟: **~24h (3 人 3 天)** | 比原始生产级计划减少 **56%**

---

## 0. 设计原则

| 原则 | 说明 |
|---|---|
| **研究平台优先** | 只修影响结果正确性 + 管道稳定性 + 可复现性的问题 |
| **1 行修复不排队** | 1-5 行变更直接在主分支上提交, 不等待 Sprint |
| **测试捆绑代码** | 每项代码变更必须附带对应测试 |
| **冲突同工程师串行** | 同一文件的多个修改由同一工程师按顺序执行 |
| **每阶段验收门禁** | 每阶段结束后运行验收命令, 全部通过再进入下一阶段 |

---

## 1. 34 个研究问题汇总

| 优先级 | 数量 | 工时 | 挂钟 | 核心内容 |
|---|---|---|---|---|
| **P0** | 12 | ~9h | 3h | 崩溃修复 + 静默错误 + Parquet 统一 |
| **P1** | 9 | ~33h | 12h | 研究质量 + 可复现性 + 多周期数据 |
| **P2** | 7 | ~15h | 6h | 一致性 + 测试增强 |
| **P3** | 4 | ~6h | 3h | 长期优化 |
| **总计** | **34** | **~64h** | **~24h** | 3 人 3 天 |

---

## 2. 文件冲突矩阵

| 冲突组 | 文件 | 冲突任务 | 解决策略 |
|---|---|---|---|
| A | `limit_checker.py` | #2 (Inf 守卫) + #7 (BoardType 委托) | 同工程师串行: #2→#7, 5min 间隔 |
| B | `research_pipeline.py` | #10 (裸 except) + N2 (种子锁定) | 同工程师串行: #10→N2, 2h 间隔 |
| C | `market_rules.py` | #7 (BoardType 委托) + N3 (price_collar) | 跨阶段: #7 在 P0, N3 在 P1 |
| D | `unified_engine.py` | #23 (基准) + #21 (敏感度) + #51 (仓位) | 跨阶段: #23 P0, #21 P1, #51 P2 |
| E | `brain/wyckoff/` | #29 (复杂度拆分) + #49 (magic numbers) | 同工程师串行: 先重构再提取常量 |
| F | `signal/adapters.py` | #19 (测试) + #50 (自动发现) | 跨阶段: #19 P1, #50 P3 |
| G | `data/sources/` | #20 (基类重构) + #28 (eastmoney 拆分) | 同工程师串行: 先基类后拆分 |

---

## 3. 三工程师并行执行计划

### Phase 0: 核心修复 (3h 挂钟, 9 人时)

**目标**: 修复所有 P0 级崩溃 + 静默错误  
**验收门禁**: `pytest tests/ -q --tb=short` → 1515+ passed, 0 failed  
**策略**: 大部分是 1-5 行变更, 可高度并行

| Eng | 串行顺序 | 任务 | 工时 | 实际变更 | 冲突检查 |
|---|---|---|---|---|---|
| **A** | 1→2→3→4→5 | #2(1m)→#7(30m)→#8(5m)→N1(2h)→#38(30m) | **~3h** | `limit_checker.py:98` +1行; 新建`board_registry.py`; `trade_calendar_manager.py`更新回退; Parquet 模式统一脚本; `slippage_model.py`→`matching_engine.py`适配 | Group A: 串行 ✅ |
| **B** | 1→2→3→4→5 | #10(1m)→N2(2h)→#4(6h)→#23(20m) | **~8h** | `research_pipeline.py:237` 1行; `research_pipeline.py`加种子传播; `signal/db.py`+测试; `unified_engine.py`+benchmark字段 | Group B: 串行 ✅ |
| **C** | 1→2→3→4→5 | #24(5m)→#31(5m)→#32(10m)→#1(verify) | **~1h** | `calculator.py:519` +1行; `regime_analysis_engine.py:42` 改1行; `czsc_analysis_engine.py` 3处接线; 确认 #1 已修复 | 全部独立 ✅ |

**P0 关键代码变更** (全部 1-5 行):

```
#2:  limit_checker.py:98  if pre_close <= 0 or np.isinf(pre_close):
#7:  新建 board_registry.py (30行), limit_checker.py/market_rules.py 委托调用
#8:  trade_calendar_manager.py: 更新硬编码回退 2024→2027
#10: research_pipeline.py:237  except: → except Exception:
#23: unified_engine.py: run() 加 benchmark_returns 参数, BacktestResult 加 benchmark_return 字段
#24: calculator.py:519  prices <= 0 or np.isnan(prices) or np.any(np.isinf(prices)):
#31: regime_analysis_engine.py:42  regime_detector.detect(df)  # 传 DataFrame 而非 symbol
#32: czsc_analysis_engine.py:121/144/154 trend→CZSCOutput, current_state→CZSCOutput
#38: unified_matching_engine.py: slippage_rate: float → Optional[SlippageModel], 适配层
N1:  python3 scripts/unify_parquet_schema.py  # 统一所有 5934 个 parquet 文件为 10 列 datetime64[ns]
```

---

### Phase 1: 研究质量提升 (12h 挂钟, 33 人时)

**目标**: 研究质量 + 可复现性 + 多周期数据  
**验收门禁**: `python3 scripts/staged_full_scan.py --stage canary --max-workers 4`  
**策略**: 较大工作量, 3 人并行, 利用 P0 已修复的基础

| Eng | 串行顺序 | 任务 | 工时 | 冲突检查 |
|---|---|---|---|---|
| **A** | 1→2→3→4 | #20(4h)→#28(4h)→#34(4h)→N3(2h) | **14h** | Group G: 串行; Group C: #7 已在 P0 ✅ |
| **B** | 1→2→3→4→5 | #19(4h)→#21(4h)→#22(1h)→#33(2h)→#53(2h) | **13h** | Group D: #23 已在 P0; Group F: #19 先于 #50(P3) ✅ |
| **C** | 1→2→3→4 | #29(8h)→#49(2h)→#66(1h)→#47(1h) | **12h** | Group E: 串行 ✅ |

**Phase 1 关键交付**:

```
#20: data/sources/base.py 添加 _shared_column_mapping, _parse_date 共享方法
#28: eastmoney.py 1094→<500 行, 按功能域拆分
#34: data/lake/quotes/ 下 1mins/5mins/weekly/monthly 填充数据
N3:  price_collar.py 测试 + market_rules.py 价格有效性验证
#19: 7 个 Adapter 测试 (LPPL, CZSC, Wyckoff, FSM, Regime, Alpha, MA)
#21: unified_engine.py sensitivity_scan(slippages, commissions) 方法
#22: interfaces.py TradingSignal.to_dict() + from_dict() metadata 修复
#33: tests/test_e2e_pipeline.py 扩展 (现有 2 个 E2E 文件, 增加覆盖)
#53: 20+ 弱 assert 测试加 assert
#29: engine.py _step1_phase_determine 183行→7 个独立方法
#49: brain/wyckoff/ 7 个 magic numbers → 常量
#66: time_provider.py datetime.now() → TimeProvider
#47: portfolio_engine.py 确认 DeprecationWarning, 删除 __init__.py 导出
```

---

### Phase 2: 一致性与测试增强 (6h 挂钟, 15 人时)

**目标**: 修复系统不一致性 + 增强测试  
**验收门禁**: `pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=50`  
**策略**: 3 人并行, 每项任务不依赖其他任务

| Eng | 任务 | 工时 | 冲突检查 |
|---|---|---|---|
| **A** | #48: hands 层 broad except 修复 (2h) | **2h** | 独立文件 ✅ |
| **B** | #51: 仓位计算统一 (3h) + #47: Portfolio 删除导出 (1h) | **4h** | Group D: #23(P0)→#21(P1)→#51(P2) ✅ |
| **C** | #49: Wyckoff magic numbers 迁移 (2h) + #66: datetime.now 替换 (1h) + 批量验证 | **3h** | Group E: #29→#49 串行 ✅ |

---

### Phase 3: 长期优化 (3h 挂钟, 6 人时)

**目标**: 可延迟的架构优化  
**验收门禁**: `ruff check src/uniquant/ && pytest tests/ -q`  
**策略**: 1 人执行, 其余工程师休假/文档

| Eng | 任务 | 工时 |
|---|---|---|
| **B** | #45: 信号超时机制 (2h) + #50: 适配器自动发现 (1h) + #52: 性能 CI (2h) + #57: 死代码清理 (1h) | **6h** |

---

## 4. 工程师负载总表

| Phase | Eng A | Eng B | Eng C | 总计 | 挂钟 |
|---|---|---|---|---|---|
| P0 | 3h | 8h | 1h | 12h | **3h** |
| P1 | 14h | 13h | 12h | 39h | **12h** |
| P2 | 2h | 4h | 3h | 9h | **6h** |
| P3 | — | 6h | — | 6h | **3h** |
| **总计** | **19h** | **31h** | **16h** | **66h** | **~24h** |

**负载平衡**: Eng A 19h, Eng B 31h, Eng C 16h。Eng B 负载最高 (信号+回测+E2E 大部分集中在此)。如果 Eng B 成为瓶颈, 可将 #21 (敏感度扫描) 移给 Eng A。

---

## 5. 验证门禁

| 门禁 | 时间 | 命令 | 通过条件 | 失败处理 |
|---|---|---|---|---|
| G0 | P0 结束 | `pytest tests/ -q --tb=short` | 1515+ passed, 0 failed | 回滚未通过 commit, 修复后重试 |
| G1 | P1 结束 | `python3 scripts/staged_full_scan.py --stage canary --max-workers 4` | 20/20 success | 定位失败引擎, 修复后重试 |
| G2 | P2 结束 | `pytest tests/ -q --cov=src/uniquant/ --cov-fail-under=50` | 覆盖 ≥50%, 0 failed | 补充测试 |
| G3 | P3 结束 | `ruff check src/uniquant/ && pytest tests/ -q` | 0 lint, 0 failed | 修复 lint 或测试 |

**最终验收**:
```bash
pytest tests/ -q --tb=short --cov=src/uniquant/ --cov-report=term-missing
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"
```

---

## 6. 回滚策略

| 场景 | 操作 | 说明 |
|---|---|---|
| 单任务失败 | `git revert <commit-hash>` | 每任务独立 commit, 可单独 revert |
| 门禁 G0 失败 | 回滚 P0 所有 commit | P0 是基础, 不修复不能继续 |
| 门禁 G1 失败 | 回滚最后 2 个 commit | 通常是引擎修改导致回归 |
| Parquet 统一(N1)失败 | 保留原始 parquet 备份 | N1 执行前备份 `data/lake/quotes/daily/` |

### 分支策略

```
Phase 0: main → phase-0/* (每人独立分支) → PR → main
Phase 1: main → phase-1/* → PR → main
Phase 2: main → phase-2/* → PR → main
Phase 3: main → phase-3/* → PR → main

每阶段结束时向 main 合并, 运行完整验收门禁
```

---

## 7. 与原始生产级计划的对比

| 维度 | 原始生产级计划 | 研究平台最终版 | 变化 |
|---|---|---|---|
| 问题数 | 74 | **34** | -54% |
| 总工时 | 146.5h | **~66h** | -55% |
| 挂钟时间 | 54h (7 天) | **~24h (3 天)** | -56% |
| 工程师 | 3 | **3** | 不变 |
| 修复内容 | SSL, CVE, Prometheus, Grafana, CI/CD, 80%覆盖 | **崩溃+静默错误+数据损坏+可复现性** | 聚焦研究核心 |
| 核心风险 | 团队在错误的事情上浪费时间 | **团队在正确的事情上高效工作** | 战略转变 |

### 从 74 到 34 的过滤路线

```
原始 74 问题 (生产级)
  │
  ├── 36 个 PRODUCTION 过度设计 → 关闭为 wontfix
  │   ├── 安全加固 (5): SSL, CVE, eval, bandit, rate-limit
  │   ├── 可观测性 (5): Prometheus, Grafana, 结构化日志, health 端点
  │   ├── CI/CD 治理 (9): CODEOWNERS, PR模板, mutmut, 80%覆盖, benchmark CI
  │   ├── 性能优化 (5): ProcessPool, BLAS, 连接池, 重试, 内存分块
  │   ├── 架构纯净 (5): 层依赖, Pydantic schema, 自动发现, 文档比
  │   ├── 代码整洁 (5): dirty 文件, .tmp.lock, TODO, 死代码, 冗余 CSV
  │   └── 数据新鲜度 (2): 28天延迟, 日频更新
  │
  ├── 1 个升为 PRODUCTION (#46 BUY 质量门禁 — 系统性偏差)
  │
  ├── 3 个调整优先级 (#33 P1→P2, #47 P1→P2, #53 P1→P2)
  │
  └── +3 个新发现 (N1 Parquet, N2 种子, N3 price_collar)
       │
       ▼
最终 34 研究问题
```

---

## 8. 执行检查清单

### Phase 0 日 (Day 1, 3h)

```
□ Eng A: #2 limit_checker Inf 守卫 (1min)
□ Eng A: #7 BoardTypeRegistry 新建 (30min)
□ Eng A: #8 TradeCalendar 回退更新 (5min)
□ Eng A: N1 Parquet 模式统一脚本 (2h)
□ Eng A: #38 SlippageModel 适配 (30min)
□ Eng B: #10 裸 except 修复 (1min)
□ Eng B: N2 种子锁定机制 (2h)
□ Eng B: #4 signal/db.py 测试 (6h — 可能跨天)
□ Eng B: #23 基准指数集成 (20min)
□ Eng C: #24 LPPL isinf 守卫 (1min)
□ Eng C: #31 Regime 接口传 df (1min)
□ Eng C: #32 CZSC 接线 (10min)
□ Eng C: 验证 #1 已修复 (1min)
□ Gate G0: pytest tests/ -q 全部通过
```

### Phase 1 日 (Day 2-3, 12h)

```
□ Eng A: #20 数据源基类重构 (4h)
□ Eng A: #28 eastmoney 拆分 (4h)
□ Eng A: #34 多周期数据填充 (4h)
□ Eng A: N3 price_collar 测试 (2h)
□ Eng B: #19 7 个 Adapter 测试 (4h)
□ Eng B: #21 敏感度扫描 (4h)
□ Eng B: #22 to_dict 序列化 (1h)
□ Eng B: #33 E2E 测试扩展 (2h)
□ Eng B: #53 弱 assert 测试增强 (2h)
□ Eng C: #29 Wyckoff 复杂度拆分 (8h)
□ Eng C: #49 magic numbers 迁移 (2h)
□ Eng C: #66 datetime.now 替换 (1h)
□ Eng C: #47 Portfolio 导出删除 (1h)
□ Gate G1: python3 scripts/staged_full_scan.py --stage canary 全通过
```

### Phase 2 日 (Day 3 下午, 6h)

```
□ Eng A: #48 hands 层 broad except 修复 (2h)
□ Eng B: #51 仓位计算统一 (3h)
□ Eng B: #47 确认导出删除 (1h)
□ Eng C: 批量验证 + 代码审查 (3h)
□ Gate G2: pytest --cov-fail-under=50 通过
```

### Phase 3 (Day 3 晚/flexible)

```
□ Eng B: #45 信号超时 (2h), #50 自动发现 (1h), #52 性能 CI (2h), #57 死代码 (1h)
□ Gate G3: ruff check + pytest 通过
□ 最终验收: baseline capture + compare + imports 验证
```

---

## 9. 风险登记表

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| N1 Parquet 统一破坏 5934 个文件 | 中(30%) | 全部数据不可用 | 执行前完整备份 `data/lake/quotes/daily/`; 先在 10 个文件上测试脚本 |
| #4 signal/db.py 测试发现隐藏 bug | 高(60%) | 修复时间延长 | 预留 6h 测试时间; 若发现 bug 立即修复而非 workaround |
| #29 Wyckoff 复杂度拆分引入回归 | 中(40%) | 门禁 G1 失败 | 每步拆分后运行 `pytest tests/test_wyckoff*`; 对比 baseline |
| Eng B 超载 (31h vs 19h/16h) | 中(50%) | Phase 1 延迟 | 将 #21 移给 Eng A; 或将 #33 降为 P2 延后 |
| P0 实际工时 > 3h 挂钟 | 低(20%) | Phase 0 跨天 | 核心变更是 1-5 行; 6h 测试由 Eng B 异步执行不阻塞门禁 |

---

## 10. 完成定义 (Definition of Done)

| 条件 | 检查方式 |
|---|---|
| 所有 34 个问题已修复或已关闭 | 对照本清单逐项确认 |
| 测试套件 1515+ passed, 0 failed | `pytest tests/ -q` |
| 基线一致性 20/20 | `scripts/capture_baseline.py && scripts/compare_baseline.py` |
| canary 扫描 20/20 success | `scripts/staged_full_scan.py --stage canary` |
| 覆盖率 ≥50% | `pytest --cov-fail-under=50` |
| 0 lint 错误 | `ruff check src/uniquant/` |
| 8 层 import 正常 | `python3 -c "import ..."` |
| ServiceContainer 初始化正常 | `python3 -c "from ... ServiceContainer; c.initialize()"` |