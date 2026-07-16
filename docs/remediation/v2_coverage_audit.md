# UniQuant v2.0 — 覆盖审计报告 (研究平台修正版)

> 日期: 2026-07-07 | **重要: 本报告已按"研究平台"而非"生产交易系统"的标准重新评估**
> 原始报告 (v1) 错误地用生产级标准评估研究平台, 导致 52% 的问题被误判为高优
> 分类标准: **研究平台 = 结果正确性 + 管道稳定性 + 可复现性**, 而非生产级安全/可观测性/治理
> 来源: `docs/remediation/v2_coverage_audit.md` + `docs/remediation/v2_coverage_audit_red_blue.md` R6 重新分类

---

## 0. 关键前提: 这是研究平台, 不是交易系统

### 研究平台 vs 生产交易系统的区别

| 维度 | 研究平台 (UniQuant) | 生产交易系统 | 对我们评估的影响 |
|---|---|---|---|
| **核心目标** | 发现可盈利率因子 | 执行订单, 不亏损 | 结果正确性 > 运行时稳定性 |
| **失败容忍度** | 管道崩溃可重启 | 不可中断 | 崩溃不致命, 但**静默错误致命** |
| **安全需求** | 内网运行 | 公网, 需防攻击 | SSL/CVE 可不修 |
| **可观测性** | stdout + 日志足够 | Prometheus/Grafana 必需 | 指标系统过设计 |
| **测试覆盖** | 核心逻辑覆盖即可 | 全链路 80%+ | 50% 对研究平台可接受 |
| **性能** | 批处理过夜完成即可 | 实时响应 | BLAS/ProcessPool 可延迟 |
| **代码规范** | 单人或小团队 | 多人协作需治理 | CODEOWNERS/PR模板过设计 |

### 核心原则: 只修"会静默产生错误结果"的问题, 不修"生产级加固"问题

```
研究平台必须修:    管道崩溃 + 静默错误结果 + 数据完整性 + 可复现性
研究平台可以延迟:   安全加固 + 可观测性 + CI治理 + 性能优化 + 代码规范
研究平台不相关:     文档比、分析重叠、Git stash
```

---

## 1. 修正后覆盖概览

### 全局数字

| 指标 | 原始(v1) | 修正后(v2) | 变化原因 |
|---|---|---|---|
| 总问题数 | 74 | **68** | 去重2个, 重分类后剔除生产级问题? — **研究平台真实问题数** |
| 研究相关问题 | (未区分) | **32** | 纠正: 52% 的问题对研究平台不适用 |
| 生产级过度设计 | (未区分) | **36** | 降为 P3/P4 或关闭为 wontfix |
| 实际已修复 | 10-12 | **10-12** | 不变 |
| 覆盖率(对32个研究问题) | 63.5% (误导) | **31-37%** | 10-12 已修复 / 32 研究问题 |

### 重新理解"覆盖率"

```
原始报告 (v1): "覆盖率 63.5%" — 错误!
  分母=74 (含52%生产级问题), 分子=47 (含大量"已计划≠已修复")
  对研究平台毫无意义

修正后 (v2): "研究问题覆盖率 31-37%"
  分母=32 (研究平台真实问题), 分子=10-12 (实际已修复)
  剩余 20-22 个研究问题在执行计划中, 尚未执行

修正后: "生产级过度设计占比 52%"
  36 个问题降级, 不纳入修复范围
```

---

## 2. 32 个研究问题的详细列表与优先级

### P0 — 立即修 (12 个) — 崩溃或静默错误

| # | 问题 | 文件 | 性质 | 优先级核心理由 |
|---|---|---|---|---|
| **1** | FSM 空 DF → IndexError 崩溃 | `fsm_analysis_engine.py:96` | 管道崩溃 | 研究管道阻塞 |
| **2** | Wyckoff Inf → OverflowError 崩溃 | `limit_checker.py:72` | 管道崩溃 | 研究管道阻塞 |
| **4+39-43** | `signal/db.py` 0% 覆盖 + 异常处理缺失+ enum 风险 | `signal/db.py` | 数据完整性 | 信号持久化可复现性 |
| **7** | BoardType 双系统 → 涨跌停板错误 | `limit_checker.py`, `market_rules.py` | **静默错误** | 回测使用错误涨跌停限制 |
| **8** | TradeCalendar 2024-2026 硬编码 | `trade_calendar_manager.py` | **静默错误** | 2027 年后使用错误交易日历 |
| **10** | `research_pipeline.py:237` 裸 except | `research_pipeline.py` | 静默掩盖 | 隐藏研究管道 bug |
| **14** | `eastmoney.py` 1090 行巨型类 | `eastmoney.py` | 维护瓶颈 | 阻挡调试和修改 |
| **23** | `BacktestResult` 基准收益率为 0 | `unified_engine.py` | **静默错误** | 夏普比率虚高 |
| **24** | LPPL Inf → "Danger" 假阳性 | `calculator.py:519` | **静默错误** | 错误的研究结论 |
| **31** | Regime 接口传 string 而非 DataFrame | `regime_analysis_engine.py:42` | **静默错误** | 态势感知输出完全错误 |
| **32** | CZSC trend/current_state 未消费 | `czsc_analysis_engine.py` | **信号丢失** | 计算结果未被研究使用 |
| **38** | `SlippageModel` 未集成 | `slippage_model.py` | **静默错误** | 回测无滑点, PnL 虚高 |

### P1 — 本周修 (10 个) — 影响研究质量

| # | 问题 | 文件 | 性质 |
|---|---|---|---|
| **19** | 7/8 Adapter 无测试 | `tests/test_signal_adapters.py` | 信号正确性无保障 |
| **20** | 116 处重复代码 | 跨文件 | 修复一致性无法保证 |
| **21** | 无滑点/费用敏感性扫描 | `unified_engine.py` | 缺失核心研究工具 |
| **22** | `TradingSignal` 无 to_dict | `interfaces.py` | 无法序列化比较信号 |
| **28** | 3 文件 > 1000 LOC | 多处 | 阻挡代码理解和修改 |
| **29** | Wyckoff 复杂度 76 | `engine.py` | 无法验证逻辑正确性 |
| **33** | 无 E2E 测试 | `tests/test_e2e_pipeline.py` | 管道回归无检测 |
| **34** | 分钟/周/月数据为空 | `data/lake/quotes/` | 多周期研究无法进行 |
| **46** | BUY 信号无质量过滤 | `signal/quality.py` | 错误买入信号进入回测 |
| **47** | Portfolio 引擎不一致 | `portfolio_engine.py` | 两套计算逻辑结果不同 |

### P2 — 本月修 (6 个) — 重要但不紧急

| # | 问题 | 文件 | 性质 |
|---|---|---|---|
| **48** | hands 层 8 处 broad except | `hands/strategies/backtest.py` | 掩盖回测错误 |
| **49** | Wyckoff 7 个硬编码 magic numbers | `brain/wyckoff/` | 参数无法研究调优 |
| **51** | 仓位计算分散两处 | `arbitrator.py`,`unified_engine.py` | 仓位结果不一致 |
| **53** | 20+ 无 assert 的测试 | 多处测试文件 | 假阳性测试覆盖 |
| **63** | 多 `except Exception` + 1 bare except | 多处 | 掩盖错误 |
| **66** | `time_provider.py` datetime.now() | `time_provider.py` | 结果不可复现 |

### P3 — 长期修 (4 个) — 可延迟

| # | 问题 | 文件 | 性质 |
|---|---|---|---|
| **45** | 信号系统无超时机制 | `signal/` | 边缘情况, 批处理可重试 |
| **50** | Adapter 无自动发现 | `signal/adapters.py` | 便利性, 不影响正确性 |
| **52** | 无性能回归测试 | — | 批处理过夜完成 |
| **57** | 12 处死代码 | 跨文件 | 惰性代码, 不影响运行 |

---

## 3. 36 个被降级的"生产过度设计"问题

| 类别 | 数量 | 代表性问题 | 降级理由 |
|---|---|---|---|
| **安全加固** | 5 | SSL verify=False, requests CVE, cryptography EOL, eval 注入, bandit | 内网研究平台, 攻击面极小 |
| **可观测性过度** | 5 | Prometheus, Grafana, 结构化日志, health 独立端点, 指标系统 | 研究者读 stdout 而非 dashboard |
| **CI/CD 治理** | 9 | CODEOWNERS, PR模板, mutmut, 80%覆盖门禁, benchmark CI, 覆盖率阶梯 | 单人或小团队研究, 不需要 |
| **性能优化** | 5 | ProcessPoolExecutor, BLAS/OpenMP, 连接池, 重试, 内存分块 | 批处理过夜完成即可 |
| **架构纯净** | 5 | 层依赖清理, Pydantic schema, Adapter 自动发现, 文档比, 分析重叠 | 不改变计算结果 |
| **代码整洁** | 5 | dirty 文件, 冗余 CSV, .tmp.lock, TODO 注释, 死代码 | 不影响运行时行为 |
| **数据新鲜度** | 2 | 28天数据延迟, 日频更新配置 | 研究可使用历史数据 |

**处理建议**: 全部关闭为 `wontfix` (研究平台上下文) 或降为 P4 (永不)。

---

## 4. 修正后执行计划 (32 个研究问题)

### Phase 0: 崩溃修复 + 静默错误修复 (12h 挂钟)

| 优先 | 问题 | 工时 | 工程师 | 交付物 |
|---|---|---|---|---|
| **P0** | #1 FSM IndexError 崩溃 | 1h | A | `fsm_analysis_engine.py:96` 加空 DF 守卫 |
| **P0** | #2 Wyckoff OverflowError 崩溃 | 2h | A | `limit_checker.py:98` 加 Inf 守卫 |
| **P0** | #4+39+43 signal/db.py 修复+测试 | 6h | B | 异常处理 + enum 修复 + 测试 |
| **P0** | #7 BoardType 统一注册表 | 6h | C | `BoardTypeRegistry` 统一两套系统 |
| **P0** | #8 TradeCalendar 动态获取 | 2h | B | AkShare 动态获取 + 无限期缓存 |
| **P0** | #10 裸 except 修复 | 1h | A | `research_pipeline.py:237` `except Exception:` |
| **P0** | #23 基准指数集成 | 3h | B | `BacktestResult` 加 benchmark 字段 |
| **P0** | #24 LPPL Inf 假阳性 | 2h | C | `calculator.py:519` isinf 守卫 + NaN 比较 |
| **P0** | #31 Regime 接口 | 1h | C | 传 df 而非 string |
| **P0** | #32 CZSC 接线 | 2h | C | trend/current_state → CZSCOutput |
| **P0** | #38 SlippageModel 集成 | 3h | B | 集成到 matching engine |

### Phase 1: 研究质量提升 (8h 挂钟)

| 优先 | 问题 | 工时 | 工程师 | 交付物 |
|---|---|---|---|---|
| **P1** | #19 Adapter 测试 | 4h | B | 7 个 Adapter 测试 |
| **P1** | #20 重复代码清理 (data/sources) | 4h | A | 共享基类 |
| **P1** | #21 敏感性扫描 | 4h | B | `sensitivity_scan()` 方法 |
| **P1** | #22 TradingSignal to_dict | 1h | C | `to_dict()` + `from_dict()` metadata 修复 |
| **P1** | #28 大文件拆分 (eastmoney 优先) | 4h | A | eastmoney.py 1090→<500 |
| **P1** | #29 Wyckoff 复杂度 76 拆分 | 8h | A | 7 个独立方法 |
| **P1** | #33 E2E 测试 | 4h | B | `test_e2e_pipeline.py` |
| **P1** | #34 多周期数据 | 4h | C | 1min/5min/weekly/monthly |
| **P1** | #46 BUY 质量过滤 | 2h | C | 仲裁器加 BUY 过滤 |
| **P1** | #47 Portfolio 引擎对齐 | 4h | B | 统一执行路径 |

### Phase 2: 研究可复现性 (4h 挂钟)

| 优先 | 问题 | 工时 | 工程师 | 交付物 |
|---|---|---|---|---|
| **P2** | #48 hands 层 broad except | 2h | A | 窄化异常捕获 |
| **P2** | #49 Wyckoff magic numbers | 2h | C | 迁移为常量 |
| **P2** | #51 仓位计算统一 | 3h | B | 单一路径 |
| **P2** | #53 assert-less 测试补全 | 4h | B | 20+ 测试加 assert |
| **P2** | #63 多 except 清理 | 3h | A | 跨文件修正 |
| **P2** | #66 datetime.now → TimeProvider | 1h | C | `time_provider.py` 修复 |

### 汇总

| Phase | 研究问题数 | 工时 | 挂钟 | 工程量 |
|---|---|---|---|---|
| P0: 崩溃+静默错误 | 11 | 29h | 12h (3人) | **核心: 必须做** |
| P1: 研究质量 | 10 | 39h | 12h (3人) | **重要: 安排做** |
| P2: 可复现性 | 6 | 15h | 6h (3人) | **有价值: 有余力再做** |
| P3: 可延迟 | 4 | 6h | 6h (1人) | **可选: 有时间再做** |
| **总计** | **32** | **89h** | **~24h 挂钟** | **比原始 146.5h 减少 39%** |

---

## 5. 关键对比: 生产级 vs 研究级评估

| 维度 | 原始评估(v1, 生产级) | 修正后(v2, 研究级) | 变化 |
|---|---|---|---|
| 问题总数 | 74 | **32** | -57% |
| 总工时 | 146.5h | **89h** | -39% |
| 挂钟时间 | 54h (7 工作日) | **24h (3 工作日)** | -56% |
| 实际覆盖率 | 9% (10/134, 含盲点) | **31-37%** (10-12/32) | 更诚实 |
| 执行计划可执行性 | 低 (含 36 个不必要任务) | **高** (聚焦研究成果正确性) | 大幅改善 |
| 核心风险 | 团队在错误的事情上浪费时间 | **聚焦在真正影响研究结果的问题** | 战略转变 |

---

## 6. 结论

**核心认知修正**: UniQuant 是研究平台, 不是交易系统。52% 的"问题"实际上不构成问题。

| 误区 | 纠正 |
|---|---|
| "覆盖率仅 9%" | 研究相关问题 32 个, 已修复 10-12 个 → **31-37%**, 加上执行计划覆盖 → **~90%** |
| "必须修 CVEs 和 SSL" | 内网研究平台, 安全风险可接受 |
| "需要 Prometheus/Grafana" | 研究者读 stdout, 不需要 dashboard |
| "需要 80% 覆盖门禁" | 50% 对研究平台足够, 核心路径覆盖即可 |
| "需要 CODEOWNERS/PR模板" | 单人或小团队, 沟通成本低 |

**真正需要关注的 32 个研究问题中**, 最重要的 11 个 (P0) 集中在:

1. **管道不崩溃**: FSM, Wyckoff, signal/db 异常处理 (3 个)
2. **回测结果不静默错误**: BoardType, TradeCalendar, 基准指数, SlippageModel (4 个)
3. **引擎输出正确**: Regime 接口, CZSC 接线, LPPL 假阳性 (3 个)
4. **可复现性**: 裸 except (1 个)

**这 11 个问题的修复工时 = 29h, 3 人 12 小时即可完成。** 这是研究平台真正的修复底线。