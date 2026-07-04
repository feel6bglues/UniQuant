# Phase 2 — 引擎正确性审计

> 日期: 2026-06-30 | 方法: 逐引擎代码阅读 + 策略逻辑验证 + A 股适用性评估

---

## 总览

| 引擎 | 评级 | 文件数 | 核心逻辑 | 可信度 |
|------|------|--------|----------|--------|
| **Regime** | ✅ A | 1 | 熵分位数 + Z-Score 双因子 | 高 |
| **LPPL** | ✅ A- | 12 | 对数周期幂律 + 系综共识 | 中高（LPPL 固有局限） |
| **NTF** | ✅ B+ | 1 | ETF 成交量脉冲突检测 | 高 |
| **CZSC** | ✅ A- | 1 | 缠论（外部库封装） | 高 |
| **Wyckoff** | ⚠️ B | 19 | 多时间框架 + P&F + 贝叶斯 | 中高（复杂度高） |
| **Alpha** | ✅ B+ | 1 | RS-Slope + 基准路由 | 中高 |
| **FSM** | ✅ A | 1 | 7 状态 Veto-Scoring 架构 | 高 |
| **Indicators** | ✅ A | 1 | 技术指标计算库 | 高 |

---

## 1. RegimeDetector — 市场状态检测 ✅ A

**文件**: `src/uniquant/brain/regime/regime_detector.py` (283 LOC)

### 策略逻辑
```
熵分位数 < threshold → FROZEN
|Z-Score| > threshold → STRESSED
否则 → NORMAL
任何异常 → UNKNOWN
```

### 验证通过项
- ✅ 双因子设计合理：熵 = 价格变化多样性 (流动性)，Z-Score = 换手率拥挤度
- ✅ `_validate_input_data()` 覆盖 None/空/列缺失/全 NaN/数据不足
- ✅ Phase 6 修复：数据不足/熵空/换手率空时返回 UNKNOWN 而非 NORMAL（之前的值会错误地允许交易）
- ✅ 滑动窗口分位数（60 天）适合 A 股
- ✅ 默认值安全：数据不足时 e_pct=0.5（中性）
- ✅ `handle_errors` 装饰器覆盖异常 → UNKNOWN

### 边界条件
| 场景 | 行为 | 正确性 |
|------|------|--------|
| df=None | UNKNOWN | ✅ |
| 缺少 close/volume | UNKNOWN | ✅ |
| 全部 NaN | UNKNOWN | ✅ |
| 不足 min_data_points | UNKNOWN | ✅ |
| 熵计算溢出 | UNKNOWN（catch-all） | ✅ |

### A 股适用性
HS300 指数数据作为输入，适合 A 股。熵值在涨跌停频繁时自然偏低，符合 FROZEN 判定。

---

## 2. LPPL 引擎 — 泡沫检测 ✅ A-

**文件**: `src/uniquant/brain/lppl/engine.py` (1098 LOC) + 11 个辅助文件

### 策略逻辑
```
LPPL(t) = A + B*(tc - t)^m * (1 + C*cos(w*log(tc - t) + φ))
多窗口(40-300d) → 最佳 RMSE → 风险分级(danger/warning/watch)
系综模式(ensemble): 共识度+崩溃时间聚类 → 信号强度
```

### 验证通过项
- ✅ 标准 LPPL 公式实现，参数边界 (m ∈ (0,1), w ∈ (1,50)) 与文献一致
- ✅ 双优化器：DE（全局）+ L-BFGS-B（快速），通过 config 切换
- ✅ L-BFGS-B 使用 10 个初始猜测点，覆盖参数空间的不同区域
- ✅ 风险分级考虑了天数 + R² + 价格收益率（价格涨幅 <10% 时降低 R² 权重）
- ✅ 系综模式用共识率 + tc_std 计算信号强度
- ✅ 样本外 R² (`_calc_oos_r_squared`)：最后 30 天作为验证集
- ✅ 优雅的失败处理：`LPPL_ENGINE_RECOVERABLE_ERRORS` 覆盖所有异常

### 已知局限（LPPL 固有）
| 局限 | 影响 | 缓解 |
|------|------|------|
| 多局部最优 | 拟合可能不收敛到全局最优 | 多初始猜测 + 多窗口取最佳 |
| 过拟合风险 | 高 R² 但不一定有泡沫 | 系综共识度 >0.5 过滤 |
| 参数敏感性 | m/w 的微小变化导致结论不同 | L-BFGS-B + DE 双验证 |
| 计算成本 | DE 模式 ~50x slower | L-BFGS-B 为生产默认 |

### 关键发现: `calculator.py` 中 `log_mean`/`log_std`/`used_de` 未使用变量（ruff 已检测），但无功能性影响。

### A 股适用性
LPPL 在中国市场有实证有效性（多次在泡沫顶部发出预警）。但 A 股的政策市特征（国家队干预、涨跌停）可能导致 LPPL 在极端行情中失效。40-300 天窗口适配 A 股中期趋势。

---

## 3. NTF 引擎 — 国家队因子 ✅ B+

**文件**: `src/uniquant/brain/ntf/ntf_engine.py` (183 LOC)

### 策略逻辑
```
当前成交量 / 前 window 日平均成交量 ≥ threshold → 脉冲检测
  价格分位数 < panic_threshold → SUPPORT（护盘）
  价格分位数 > heat_threshold → RESISTANCE（降温）
  否则 → LIQUIDITY_PULSE
```

### 验证通过项
- ✅ 目标 ETF 正确（510300 沪深300, 510050 上证50, 563300 中证2000）
- ✅ 成交量均值窗口排除当前 bar（`iloc[-(window+1):-1]`），无未来泄漏
- ✅ 价格分位数使用 20 天窗口，合理
- ✅ 三种方向（SUPPORT/RESISTANCE/LIQUIDITY_PULSE）覆盖主要场景
- ✅ 异常处理覆盖所有可恢复错误

### 边界条件
| 场景 | 行为 | 正确性 |
|------|------|--------|
| 数据 < 20 行 | detected=False | ✅ |
| 缺少 volume/vol 列 | detected=False + error | ✅ |
| mean_volume=0 | vol_ratio=1.0（不触发） | ✅ |

### A 股适用性
**核心价值**: A 股特有的"国家队"护盘/降温行为。2024-2026 年国家队频繁买入沪深300 ETF，此引擎能捕捉此类信号。作为**软信号**而非硬交易信号使用。

---

## 4. CZSC 引擎 — 缠论分析 ✅ A-

**文件**: `src/uniquant/brain/czsc/czsc_engine.py` (634 LOC)

### 策略逻辑
```
OHLCV → RawBar → CZSC(外部库) → bi(笔) + signal → 三买检测
```

### 验证通过项
- ✅ 完整的 OHLCV 验证（low <= close <= high, 正数检查, NaN 检查）
- ✅ 向量化过滤：一次性计算有效性掩码（nan_mask + positive_mask + logic_mask）
- ✅ 自动重置分析器：symbol 变化时 `self.analyzer = None`，防止跨股票状态污染
- ✅ 3 种三买检测路径：czsc_signals.cxt_third_buy → 枚举匹配 → 字符串匹配
- ✅ 兼容 volume/vol 双列名
- ✅ `handle_errors` 装饰器安全默认返回值

### 关键设计评价
| 设计 | 评价 |
|------|------|
| `CZSCSignalType` 枚举 | ✅ 避免字符串匹配脆性 |
| `_validate_input_row()` 增量验证 | ✅ 实时数据保护 |
| `_prepare_bar_list()` 向量化过滤 | ✅ 高性能 |
| 跨股票重置 | ✅ 必要但注意：首次调用新股票时无历史分析 |

### 局限性
`analysis_service_v2.py` 中 `get_czsc_signals_from_data` 已被标记弃用（破坏 Data Lake 原则）。CZSC 分析器是状态化的（持有 `self.analyzer`），在多线程场景中需要额外注意。

### A 股适用性
缠论在 A 股有广泛使用基础，三买点位是常见的买入信号。但 czsc 外部库的更新同步需要关注。

---

## 5. Wyckoff 引擎 — 威科夫分析 ⚠️ B

**文件**: `src/uniquant/brain/wyckoff/` (19 个文件) + `services/analysis/wyckoff_analysis_engine.py`

### 策略逻辑
```
多时间框架(周/日/月) → 阶段分类(ACCUMULATION/DISTRIBUTION/等)
  → Spring/UTAD 检测
  → P&F 点图分析(hint/breakout/count_target)
  → RegimeAwarePhaseClassifier(月度)
  → 贝叶斯事件分析
  → 风险/收益评估
  → V3 交易计划 + A 股规则
```

### 验证通过项
- ✅ 多时间框架覆盖完整（WeeklyPhaseClassifier, DailyPhaseClassifier, RegimeAwarePhaseClassifier）
- ✅ OBV 计算从 Python for-loop 改为向量化 NumPy（Phase 6+ 改进）
- ✅ P&F 集成提供独立的横盘突破信号
- ✅ `np.errstate(over='ignore')` 防止 sigmoid 溢出（Phase 6+ 改进）
- ✅ 所有 P&F 和分类器逻辑有 try/except 保护，单个模块失败不影响整体
- ✅ WyckoffOutput 新增 5 个字段与 ResearchDataPack 通信

### ⚠️ 风险点

| 风险 | 详情 | 严重度 |
|------|------|--------|
| **代码重复** | P&F 在 `engine.py` 的 `analyze()` 和 `scan_signal()` 中两次实例化 | 🟡 中 |
| **模块膨胀** | 19 个文件，`engine.py` 1560 LOC | 🟡 中 |
| **实验性代码** | `cnn_classifier.py`、`rl_agent.py` 已 stash，但表明方向发散 | 🟡 低 |
| **Phase 6+ 未验证** | P&F 集成和 RegimeAwarePhaseClassifier 尚未在全量股票扫描中验证 | 🟡 中 |
| **OBV 向量化不彻底** | `DailyPhaseClassifier.classify()` 仍有 Python for-loop OBV | 🟢 低 |

### A 股适用性
威科夫方法在 A 股有实证基础（见 `docs/analysis/wyckoff_research_report.md` — 7 阶段研究）。P&F 过滤器能提升横盘市场中的信号质量。

---

## 6. Alpha Decoupler — 因子信号 ✅ B+

**文件**: `src/uniquant/brain/alpha_decoupler/alpha_decoupler.py` (349 LOC)

### 策略逻辑
```
基准路由(市值) → RS-Slope 计算 → 相关性过滤 → alpha_score
基准: >800亿→沪深300, 200-800亿→中证500, 50-200亿→中证1000, <50亿→中证2000
```

### 验证通过项
- ✅ RS-Slope = 相对强度的线性回归斜率，标准方法
- ✅ 基准路由根据 2024-2026 A 股结构更新阈值（800/200/50 亿）
- ✅ 配置可覆盖（`config.yaml > brain.alpha_decoupler.benchmark_thresholds`）
- ✅ `handle_errors` 安全返回值
- ✅ 调用处使用 `getattr()` 而非 `dict.get()` 适配 typed outputs

### A 股适用性
基准路由逻辑适合 A 股。沪深300/中证500/中证1000/中证2000 的区分是实用的。

---

## 7. FSM / DecisionBrain — 状态机决策 ✅ A

**文件**: `src/uniquant/brain/fsm/fsm.py` (766 LOC)

### 策略逻辑
```
输入(MarketSignalContext)
  1. Veto 检查: FROZEN → FORCE_WAIT | 风险引擎不可用 → FORCE_WAIT | 高风险+无支持 → FORCE_EXIT
  2. 熔断检查: 日内跌幅 >5% → CIRCUIT_BREAK
  3. 评分(score): CZSC(+15) + 趋势(+20) + Alpha(+10) + NTF(+8)
  4. 卖出检查: LPPL_DANGER + MA_REVERSAL + ALPHA_WEAK + REGIME_RISK(STRESSED)
  5. 目标状态: score 驱动 IDLE→SIGNAL→PROBE→MONITOR→PYRAMID→EXIT
  6. 买入检查: LPPL_DANGER + FROZEN + 风控引擎 + 止损 + Alpha 弱 + 涨停
  7. 执行: 仓位计算(cash × risk_pct × kelly_fraction) + T+1 罚分
```

### 验证通过项
- ✅ Veto-Scoring 架构正确：硬约束先否决，软约束再评分
- ✅ SELL 优先：卖出检查在买入检查之前
- ✅ CIRCUIT_BREAK 熔断机制：-5% 阈值后冷却恢复
- ✅ 状态转换验证：`_validate_state_transition` 确保 7 状态图合法性
- ✅ 跨股票重置：symbol 变化时 state=IDLE
- ✅ 状态持久化：FileLock 保护的 JSON 文件，异常时优雅降级
- ✅ Phase 6 正确移除 FROZEN 从 sell_conditions（FROZEN 在 veto 阶段已被拦截）
- ✅ 止损宽度检查：`_stop_loss_blockers` 检查 ATR 止损占比 ≤15%

### 评分权重（源代码提取）
```
IndicatorThresholds:
  FSM_SCORE_CZSC = 15     (三买)
  FSM_SCORE_TREND = 20    (MA20 > MA60)
  FSM_SCORE_ALPHA = 10    (alpha > 0.3)
  FSM_SCORE_NTF = 8       (政策支持)
  总满分: 53
```

### 状态机转换图
```
IDLE → SIGNAL (score≥30, 非三买)
IDLE → PROBE (score≥30, 三买)
SIGNAL → MONITOR (score≥40) | IDLE (score<20)
PROBE → MONITOR (score≥40) | IDLE (score<20) | EXIT
MONITOR → PYRAMID (score≥50) | EXIT (score<10)
PYRAMID → MONITOR | EXIT
EXIT → IDLE
任何 → CIRCUIT_BREAK(日跌>5%)
```

### A 股适用性
FSM 的 MA20/MA60 趋势判断是经典的 A 股趋势跟踪方法。Veto 层的 FROZEN/STRESSED 处理与 A 股流动性风险高度相关。CIRCUIT_BREAK 阈值 5% 适用于 A 股（非科创板/创业板，后者为 20%）。

---

## 8. 引擎间信号冲突分析

| 场景 | LPPL | CZSC | Wyckoff | FSM 决策 | 风险 |
|------|------|------|---------|----------|------|
| LPPL Danger + 三买 | SELL | BUY | 可能冲突 | FSM 检查 SELL 先触发 → SELL/HOLD | ✅ SELL 优先 |
| 流动性枯竭 (FROZEN) | — | — | — | Veto → FORCE_WAIT | ✅ 正确 |
| NTF SUPPORT + LPPL Safe | BUY | BUY | BUY | BUY | ✅ 无冲突 |
| STRESSED + 三买 | — | BUY | — | FSM check sell → REGIME_RISK | ✅ 正确 |

**结论**: FSM 的 Veto-Scoring 架构 + SELL 优先的原则有效控制了信号冲突。唯一的风险是回测引擎内部的独立优先级与 FSM 可能不一致（Phase 1 已识别 R6-1）。

---

## 综合发现

### 🟢 正面
1. 所有引擎都有完整的输入验证和异常处理
2. FSM Veto-Scoring 架构是稳健的决策框架
3. Phase 6 修复（Regime UNKNOWN、TOCTOU、FROZEN 死代码）显著提升了正确性
4. Wyckoff 向量化 OBV 是好的质量改进
5. 弃用 `*_from_data` 方法纠正了 Data Lake 原则违规

### 🟡 需改进
1. **Wyckoff 代码重复**: P&F 在 `analyze()` 和 `scan_signal()` 中重复
2. **OBV 向量化不彻底**: `DailyPhaseClassifier.classify()` 仍使用 for-loop
3. **CZSC 状态化**: `self.analyzer` 在多线程/异步场景不安全
4. **macro_service.py:214**: `datetime` 缺失 import，运行时可能崩溃（基线已发现）

### 🔴 风险
1. Wyckoff 19 文件模块复杂度最高，维护成本大
2. LPPL 优化器多初始猜测策略是启发式的，无收敛保证
3. 5 个预存测试失败的根因仍需排查
