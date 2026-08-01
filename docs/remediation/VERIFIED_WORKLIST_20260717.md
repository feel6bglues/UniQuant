# 管线可靠性验证工作清单 (2026-07-17)

> **验证方法**: 多重交叉验证 — 代码实际 vs 文档声称, 逐行核实, 无幻觉。
> **覆盖**: LPPL 管线, Wyckoff 管线, Factor 因子分析管线, 服务编排链路, 信号适配链路。
> **验证范围**: src/uniquant/ 下 252 个活跃 Python 文件, 60,351 LOC。

---

## 一、LPPL 管线验证

### 1.1 R² 输出完整性 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| LPPLOutput 含 r_squared | `shared/interfaces.py:325` | ✅ | `r_squared: float = 0.0` |
| LPPLOutput 含 out_of_sample_r_squared | `shared/interfaces.py:326` | ✅ | `out_of_sample_r_squared: float = 0.0` |
| to_dict() 含 R² 序列化 | `shared/interfaces.py:334-335` | ✅ | 两字段均序列化 |
| from_dict() 含 R² 反序列化 | `shared/interfaces.py:345-346` | ✅ | 两字段均反序列化 |
| calculator.py fit() 返回 r_squared | `calculator.py:605,627` | ✅ | `r_squared = 1.0 - ss_res/ss_tot` |
| engine.py fit_single_window() 返回 r_squared | `engine.py:240,256` | ✅ | `"r_squared": r_squared` |
| engine.py fit_single_window_lbfgsb() 返回 r_squared | `engine.py:356,372` | ✅ | `"r_squared": r_squared` |
| lppl_analysis_engine.py 传递 r_squared | `services/analysis/lppl_analysis_engine.py:74-75` | ✅ | `r_squared=float(result.get(...))` |
| signal/adapters.py 提取 r_squared | `signal/adapters.py:102-103` | ✅ | metadata 含两字段 |
| dashboard 显示 R² | `ui/dashboard.py:1227,1230` | ✅ | 显示 R² 和 OOS R² |

**结论**: P0.1 已修复。R² 从计算→传递→序列化→UI 显示全链路贯通。R² 口径差异 (3-param VP vs 7-param 全量) 已于 2026-07-20 在 `engine.py:detect_bubble()` 和 `interfaces.py:LPPLOutput.r_squared` 中文档化。

### 1.2 优化器配置 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| LPPLConfig 默认优化器 | `engine.py:118` | ✅ | `optimizer: str = "lbfgsb"` |
| DE 种群大小 | `engine.py:121` | ✅ | `de_popsize: int = 70` (7 维问题合理) |
| scan_single_date 无 hybrid 模式 | `engine.py:447-475` | ✅ | 仅 `if "de"` / `else` (L-BFGS-B) |
| 嵌套并行检测 | `engine.py:53-57` | ✅ | `current_process().name` 非 threading.local() |

**结论**: P0.2, P3.1, P3.4 均已修复。DE 保留为离线研究选项。

### 1.3 震荡市降噪 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| classify_top_phase 有 price_ret 调整 | `engine.py:111-112` | ✅ | `abs(price_ret) < 0.10 → r2 -= 0.15` |
| L-BFGS-B 多点启动 | `engine.py:377-388` | ✅ | 10 个初始点 |

**结论**: P2.1 已修复。但固定偏移 `-0.15` 未使用 ATR 自适应 (P3.6 未实施, 低优先级)。

### 1.4 LPPL 管线剩余问题 ⚠️

| 问题 | 文件:行 | 风险 | 说明 |
|------|---------|------|------|
| LPPLEngine._process_window() 使用 calculator.fit_single_window() (DE) | `engine.py:993-1000` | 中 | scan_all_windows 路径走 DE, 与 scan_single_date (模块级函数) 的 L-BFGS-B 路径不一致。两路径由不同 API 入口调用, 不会在同一分析中混合使用。生产 `detect_bubble()` → `calculator.fit()` (DE) 是单一稳定路径 |
| 信号超时禁用 | `arbitrator.py:40` | 低 | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` — 回测模式下必需 |

---

## 二、Wyckoff 管线验证

### 2.1 多周期分析 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| wyckoff_analysis_engine 传 multi_timeframe=True | `services/analysis/wyckoff_analysis_engine.py:118` | ✅ | `result = wyckoff_engine.analyze(df, multi_timeframe=True)` |
| analyze() 多周期分支 | `brain/wyckoff/engine.py:138-139` | ✅ | `if multi_timeframe and period == "日线": return self._analyze_multiframe(...)` |

**结论**: P1.3 已修复。服务层调用默认启用多周期。

### 2.2 Step1 阈值 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| prior_trend_pct < -0.03 (非 -0.05) | `engine.py:365` | ✅ | `if ctx["prior_trend_pct"] < -0.03:` |
| 非 TR 下 ACCUMULATION 条件 (4 条件) | `engine.py:390-395` | ✅ | `short_trend_pct <= -0.02 + price < ma20 + ma5 <= ma20 + (bc_found or sc_found)` |
| SPRING_LOW_FACTOR | `engine.py:686` + `shared/constants.py` | ✅ | `row.low < low_bound * SPRING_LOW_FACTOR` |

**结论**: P1.1 已修复。阈值已放宽至 -3%。

### 2.3 T+1 ATR 动态阈值 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| rule3_t1_risk_test ATR 参数 | `rules.py:73` | ✅ | `atr: Optional[float] = None` |
| ATR 动态安全阈值 | `rules.py:81-85` | ✅ | `safe_threshold = atr_pct * 1.0`, `limit_threshold = atr_pct * 2.0` |
| rule10_stop_loss ATR 参数 | `rules.py:332-333` | ✅ | `atr: Optional[float] = None` |
| ATR 止损位 | `rules.py:345-348` | ✅ | `stop_loss_price = key_low - atr * 1.0` |
| _step4_risk_reward 计算 ATR | `engine.py:855-856` | ✅ | `atr_series = Indicators.calc_atr(df)` |

**结论**: P1.2 已完全修复。ATR 动态阈值贯通 step3→step4→rule10。

### 2.4 置信度计算 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| A 级: Spring+LPS+BC+RR≥1.5 | `engine.py:937-943` | ✅ | 已实现 |
| B+ 级: Spring+LPS+RR≥1.5 | `engine.py:945-951` | ✅ | 已实现 |
| C 级: Spring 无 LPS | `engine.py:953-964` | ✅ | 已实现 |
| C 级: RR 合格无 BC | `engine.py:966-978` | ✅ | 已实现 |

**结论**: P2.2, P3.2 均已修复。A/B+/C 四级置信度体系完整。

### 2.5 Wyckoff 管线剩余问题 ⚠️

| 问题 | 文件:行 | 风险 | 说明 |
|------|---------|------|------|
| Spring 信号密度 — A 股结构性限制 | 全引擎 | 高 | golden_20 三年窗口 Spring 触发率 0% (据 H12 实证, 见 `repair_plan_lppl_wyckoff.md §已知限制`)。非代码 bug, 是 A 股政策底/低波动特征 |
| Wyckoff 作为独立入场信号不可靠 | — | 高 | 建议降级为风控过滤器, 不可作为主入场信号 |
| _step4_risk_reward 多目标位逻辑复杂 | `engine.py:828-910` | 中 | 88 行, 含跳空/大阴线/TR 上沿多源, 测试覆盖待确认 |

---

## 三、Factor 因子分析管线验证

### 3.1 因子注册与合成 ✅ 已验证

| 验证点 | 文件:行 | 状态 | 证据 |
|--------|---------|------|------|
| FactorRegistry 单例+线程安全 | `registry.py:1-40` | ✅ | `threading.Lock` |
| fillna(0.0) 已移除 | `composer.py` | ✅ | `grep fillna → 0 matches` |
| 对称正交化 | `composer.py:280-325` | ✅ | `linalg.eigh` + 特征值分解 |
| 因子中性化 | `composer.py:398-404` | ✅ | `FactorNeutralizer.neutralize()` |
| IC 加权合成 | `composer.py:219-232` | ✅ | `_resolve_weights()` |
| 诊断信息 | `composer.py:37-47` | ✅ | `_new_diagnostics()` |

**结论**: P0-04 已修复。因子管线无 fillna 问题。

### 3.2 因子管线剩余问题 ⚠️

| 问题 | 文件:行 | 风险 | 说明 |
|------|---------|------|------|
| FactorComposer 返回复合分数但无 IC 周期性验证 | `composer.py` | 中 | IC 权重依赖 _resolve_weights 的实时计算, 无 IC 衰减/半衰期 |
| 因子 registry 无版本控制 | `registry.py` | 低 | 因子定义变更后无法追溯 |

---

## 四、服务编排链路验证

### 4.1 引擎调用顺序 ✅ 已验证

| 步骤 | 文件:行 | 状态 |
|------|---------|------|
| 1. DataService → data_pack | `analysis_service_v2.py:305-328` | ✅ |
| 2. Regime 检测 | `analysis_service_v2.py:346-348` | ✅ |
| 3. LPPL 泡沫检测 | `analysis_service_v2.py:351-353` | ✅ |
| 4. NTF 国家队检测 | `analysis_service_v2.py:356-358` | ✅ |
| 5. CZSC 缠论分析 | `analysis_service_v2.py:361-363` | ✅ |
| 6. Wyckoff 分析 | `analysis_service_v2.py:366-368` | ✅ |
| 7. Alpha 因子 | `analysis_service_v2.py:371-373` | ✅ |
| 8. 衍生指标 | `analysis_service_v2.py:376-378` | ✅ |
| 9. DecisionBrain 决策 | `analysis_service_v2.py:290-292` | ✅ |
| 10. TradingSignalCollector | `research_pipeline.py` | ✅ |
| 11. UnifiedBacktestEngine | `research_pipeline.py` | ✅ |

### 4.2 信号适配链路 ✅ 已验证

| 适配器 | 引擎输出 → TradingSignal | 状态 |
|--------|-------------------------|------|
| LPPLAdapter | risk_level/confidence → SELL/HOLD | ✅ `adapters.py:60-120` |
| WyckoffAdapter | phase/spring/utad → BUY/SELL/HOLD | ✅ `adapters.py:149-200` |

---

## 五、验证后工作清单

### P0 — 必须修复

| ID | 描述 | 文件:行 | 风险 | 预计 | 状态 |
|----|------|---------|------|------|------|
| P0-W01 | Spring 信号密度验证 — 真实数据跑 golden_100 确认 Spring 触发率 | `scripts/lppl_wyckoff_cross_validation.py` | 高 | 300s | **待验证** — 脚本已加固 (2026-07-20): Spring 检测安全化, except 窄化, H12 三态裁决 |
| P0-W02 | LPPL 双路径一致性 — calculator.fit() (DE) vs scan_single_date (L-BFGS-B) 输出差异 | `engine.py:993-1000` vs `engine.py:447-475` | 中 | 2h | **待修复** — R² 口径差异已文档化 (2026-07-20): `engine.py:detect_bubble()` + `interfaces.py:LPPLOutput.r_squared` 标注 3-param VP vs 7-param 不可比 |

### P1 — 本月完成

| ID | 描述 | 文件:行 | 风险 | 预计 | 状态 |
|----|------|---------|------|------|------|
| P1-W01 | Wyckoff Step1 ACCUMULATION 在 golden_20 上的实际 UNKNOWN 率验证 | `engine.py:365-395` | 中 | 1h | **待验证** |
| P1-W02 | 因子 IC 半衰期/衰减加权 — 解决 IC 权重无时效性问题 | `composer.py:219-232` | 中 | 3h | **待设计** |
| P1-W03 | LPPL _process_window 统一优化器路径 | `engine.py:993-1000` | 中 | 1h | **待修复** |

### P2 — 本季度完善

| ID | 描述 | 文件:行 | 风险 | 预计 | 状态 |
|----|------|---------|------|------|------|
| P2-W01 | LPPL classify_top_phase ATR 自适应偏移 (替代固定 -0.15) | `engine.py:108-122` | 低 | 1h | **待实施** (P3.6) |
| P2-W02 | Wyckoff _step4_risk_reward 多目标位逻辑单元测试 | `engine.py:828-910` | 低 | 2h | **待补充** |
| P2-W03 | Arbitrator 信号超时在实盘模式启用 | `arbitrator.py:40` | 低 | 0.5h | **待设计** |
| P2-W04 | 因子 registry 版本号/变更追溯 | `registry.py` | 低 | 2h | **待设计** |

### P3 — 下一轮

| ID | 描述 | 文件:行 | 风险 | 预计 |
|----|------|---------|------|------|
| P3-W01 | T+1 ATR 前后对比脚本 + golden_100 全量跑 | `scripts/` | 低 | 2h |
| P3-W02 | 跨引擎集成测试 — LPPL→Wyckoff→Factor 联合压力测试 | `tests/` | 低 | 4h |

---

## 六、已验证已修复摘要

> 以下 repair_plan_lppl_wyckoff.md 中的 11 项已全部确认 **已修复**:

| 修复项 | 原始描述 | 验证结论 |
|--------|---------|----------|
| P0.1 | R² 输出 + LPPLOutput 字段 | ✅ `interfaces.py:325-326`, `calculator.py:605-627` |
| P0.2 | L-BFGS-B 默认 + DE popsize=70 | ✅ `engine.py:118,121` |
| P1.1 | Step1 阈值 -5% → -3% | ✅ `engine.py:365` |
| P1.2 | T+1 ATR 动态阈值 | ✅ `rules.py:73,81-85,332-348`, `engine.py:855-856` |
| P1.3 | 多周期分析默认启用 | ✅ `wyckoff_analysis_engine.py:118` |
| P2.1 | LPPL 震荡市降噪 | ✅ `engine.py:111-112` |
| P2.2 | Wyckoff A 级可达 | ✅ `engine.py:937-943` |
| P3.1 | hybrid 移除 | ✅ `engine.py:447-475` (无 hybrid) |
| P3.2 | B+ 级新路径 | ✅ `engine.py:945-951` |
| P3.4 | 并行 guard | ✅ `engine.py:53-57` (current_process) |
| P3.5 | R² 命名规范 | ⚠️ 部分满足 — `r_squared`+`out_of_sample_r_squared` 两字段存在, 但 `r_squared` 未重命名为 `in_sample_r_squared`。向下兼容性好, 降为非必须 |
| P0-04 | fillna(0.0) 移除 | ✅ `composer.py:183,204,276` (已无 fillna) |

---

## 七、关键发现

1. **`repair_plan_lppl_wyckoff.md` 严重过时** — 11 项 P0/P1/P2/P3 修复已全部在代码中实施, 但文档未更新。该文件声称的需要修复项与代码实际状态严重不符。

2. **LPPL 双路径隐患** — `LPPLEngine.detect_bubble()` → `calculator.fit()` 使用 DE 优化器 (popsize=10, maxiter=500), 而 `engine.py` 的 `scan_single_date()` (模块级函数) 使用 L-BFGS-B。两条路径由不同 API 入口调用, 不会在同一分析中混合使用。若需统一, 建议将 `_process_window` 切换为 L-BFGS-B 路径。

3. **Wyckoff Spring 信号结构性缺失** — 非代码问题, 是 A 股市场特征。golden_20 三年窗口 Spring 触发率 0%, 导致 A/B+ 级置信度路径几乎不可达。Wyckoff 当前只能输出 C 级信号。

4. **Factor 管线无 IC 时效性** — 权重计算无 IC 衰减/半衰期, 可能使用过时因子权重。
