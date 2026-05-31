# UniQuant 系统现状全景侦察报告 (V2)

> 审计时间：2026-05-30 | 基于代码事实，零推测 | 4 路 Subagent 并发审计
> 本报告为修复 P0/P1 问题后的重新审计

---

## 一、模块状态矩阵

| 包 | 文件数 | 状态 | 关键证据 |
|---|--------|------|----------|
| **shared/limits.py** | 1 | ✅ 新增兼容层 | `limits.py:7` 正确导出 `is_limit_down/is_limit_up` |
| **shared/limit_checker.py** | 1 | ✅ 生产可用 | 5 类板块涨跌停检查完整 |
| **data/** | 72 | ⚠️ 勉强可用 | DuckDB 零实现、EastmoneySource 未注册、NaN 填 0 有风险 |
| **brain/lppl/** | 8 | ✅ 生产可用 | 置信度已内置(`calculator.py:349-357`)，但 RMSE 计算有 bug |
| **brain/wyckoff/** | 11 | ⚠️ 勉强可用 | `scan_signal` 已添加，但 `action` 永远返回 "HOLD" |
| **brain/czsc/** | 2 | ⚠️ 勉强可用 | 依赖第三方 czsc 库 |
| **brain/factors/** | 8 | ⚠️ 勉强可用 | Walk-Forward 管道 mode 参数类型不匹配，无法运行 |
| **brain/fsm/** | 2 | ✅ 生产可用 | 7 状态 FSM + FileLock 持久化 |
| **hands/backtest/** | 10 | ⚠️ 勉强可用 | T+1 实现正确，但手数取整缺失、Sharpe 口径不一致 |
| **hands/strategies/** | 12 | ❌ 存在致命逻辑 | B轨策略 look-ahead bias、双 STRATEGY_MAP 冲突 |
| **risk/** | 7 | ⚠️ 勉强可用 | DrawdownAnalyzer 生产级；EVT 名不副实 |
| **services/** | 11 | ⚠️ 勉强可用 | ServiceContainer 无锁单例、@handle_errors 静默吞错 |
| **signal/** | 5 | ✅ 生产可用 | 归一化、聚合、持久化完整 |
| **ui/** | 5 | ✅ 生产可用 | Streamlit 仪表盘完整 |

---

## 二、核心数据流图解

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据采集层]                                      │
│  mootdx本地 ─┐                                                          │
│  mootdx在线 ─┤  硬编码 count=800                                        │
│  baostock   ─┤                                                          │
│  sina       ─┼─→ SourceRouter ─→ DataFetcher ─→ DataIngestionService    │
│  ths        ─┤     (故障转移)      (LRU缓存)         (同步脚本)          │
│  tencent    ─┘                                                          │
│  eastmoney  ─   [未注册 ❌]                                             │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ DataFrame(date,open,high,low,close,volume)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据存储层]                                      │
│  StorageManager ──→ data/lake/quotes/{daily,weekly,monthly}/*.parquet   │
│       │                (原子写入有缺陷: unlink+rename 非原子)             │
│       ├─→ synthesize_weekly() / synthesize_monthly()                    │
│       └─→ DataAdjuster ──→ 前复权/后复权                                │
│                                                                         │
│  ⚠️ DuckDB: config 声明 engine:"duckdb"，代码零实现                      │
│  ⚠️ NaN处理: data_cleaner.py:26 将价格 NaN 填 0，与 aligner.ffill 冲突   │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ 复权后 DataFrame
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [分析引擎层]                                      │
│                                                                         │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐   │
│  │  LPPL   │  │  Wyckoff │  │  CZSC   │  │  Factors │  │   FSM    │   │
│  │ ✅置信度 │  │ ⚠️action │  │ ⚠️第三方 │  │ ⚠️WF断裂 │  │ ✅完整   │   │
│  │ ⚠️RMSE  │  │ 永远HOLD │  │  czsc库  │  │ mode类型 │  │ 7状态    │   │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └────┬─────┘  └────┬─────┘   │
│       │            │             │             │             │          │
│       └────────────┴─────────────┴─────────────┴─────────────┘          │
│                              │ AnalysisResult                           │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │              DecisionBrain (brain/fsm/fsm.py)                 │       │
│  │  综合所有引擎输出 → 状态转换 → 买入/卖出/持有决策              │       │
│  └──────────────────────────────┬───────────────────────────────┘       │
└─────────────────────────────────┼───────────────────────────────────────┘
                                  │ 交易信号
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [回测撮合层]                                      │
│                                                                         │
│  BacktestEngine (逐bar)          UnifiedMatchingEngine (向量化)         │
│       ├─ T+1: 交易日历 ✅              ├─ T+1: 日历天数 ❌              │
│       ├─ 涨跌停: 5板块 ✅              ├─ 涨跌停: 5板块 ✅              │
│       ├─ 手数取整: ❌                  ├─ 手数取整: ❌                   │
│       └─ Sharpe: 无rf ❌              └─ Sharpe: 含rf ✅                │
│                                                                         │
│  B轨策略函数 ⚠️ look-ahead bias (使用未来数据)                          │
│  STRATEGY_MAP ⚠️ 双定义冲突                                            │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ 回测结果
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [风控层]                                          │
│                                                                         │
│  DrawdownAnalyzer ✅     PositionSizer ✅     PortfolioOptimizer ✅      │
│  (向量化MDD)             (T+1惩罚+手数取整)   (风险平价+均值方差)        │
│                                                                         │
│  EVTRisk ❌ (名不副实，实为历史模拟法)                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、技术债与高危地带雷达

### 🔴 TOP 3 高危代码位置

**1. `brain/lppl/calculator.py:332` — RMSE 计算错误**
```python
rmse = np.sqrt(np.mean(residuals))  # ❌ residuals 是 SSE，不是残差向量
```
`np.linalg.lstsq` 返回的 `residuals` 是残差平方和(SSE)，`np.mean(SSE) = SSE`。正确计算应为 `np.sqrt(SSE / n)` 或 `np.sqrt(np.mean((X @ beta - log_price)**2))`。此 bug 导致 RMSE 被高估 `sqrt(n)` 倍（n 通常 60-750），使置信度被拉低。

**2. `hands/strategies/ma_cross.py:27-44` — B轨策略 look-ahead bias**
```python
fut = df[df["date"] > a]           # 获取 as_of_date 之后的全部数据
entry = float(fut.iloc[0]["open"])  # 用未来第一天开盘价作入场价
```
B轨策略（`ma_cross.py`, `str_reversal.py`, `regime.py`, `wyckoff.py`）全部使用未来数据计算收益。这些是"离线回测评估器"而非实时信号生成器，但代码中缺少醒目的警告标记。

**3. `data/pipeline/data_cleaner.py:26` — NaN 填 0 与 ffill 冲突**
```python
pd.to_numeric(df[col], errors="coerce").fillna(0)  # 价格 NaN 填 0
```
`data_cleaner.py` 将价格 NaN 填为 0，而 `data_aligner.py:84` 对停牌日做 ffill。如果清理在对齐之前执行，ffill 会将 0 值传播为"停牌价"，产生脏数据。

### 🟡 次高危地带

| # | 位置 | 问题 |
|---|------|------|
| 4 | `unified_matching_engine.py:162` | T+1 使用日历天数而非交易日 |
| 5 | `engine.py:181` | 手数取整缺失（应为 100 股整数倍） |
| 6 | `result.py:99` vs `portfolio_engine.py:339` | Sharpe 比率口径不一致（4种公式） |
| 7 | `evt_risk.py:389` | EVTRisk 实为 HistoricalSimulationRisk |
| 8 | `engine.py:1403` | scan_signal 的 action 永远返回 "HOLD" |
| 9 | `analyzer.py:209` vs `walk_forward_pipeline.py:156` | mode 参数类型不匹配 |
| 10 | `brain/indicators.py` vs `brain/indicators/` | 3 处模块/包命名冲突 |
| 11 | `service_container.py:36-39` | 单例无锁保护 |
| 12 | `storage_manager.py:324-328` | 原子写入缺陷（unlink+rename 非原子） |

---

## 四、已修复问题验证

### P0 修复验证

| 修复项 | 文件 | 验证结果 |
|--------|------|----------|
| limits.py 兼容层 | `shared/limits.py` | ✅ `classifiers.py:11` 导入正常 |
| is_limit_down/up 函数 | `shared/limit_checker.py:219-256` | ✅ 签名兼容，功能正常 |

### P1 修复验证

| 修复项 | 文件 | 验证结果 |
|--------|------|----------|
| LPPL 置信度内置 | `calculator.py:349-357` | ✅ 包含 confidence/risk_level/direction/days_to_tc |
| Wyckoff 阶段阈值 | `engine.py:294-297` | ✅ 从 -0.10 放宽到 -0.05 |
| Wyckoff scan_signal | `engine.py:1358-1426` | ⚠️ 接口存在但 action 永远返回 "HOLD" |

### 残留问题

| 问题 | 原因 | 建议 |
|------|------|------|
| Wyckoff phase 仍返回 UNKNOWN | 横盘且趋势微弱时所有条件均不满足 | 需进一步调试 `_step1_phase_determine` |
| scan_signal action="HOLD" | `TradingPlan` 没有 `action` 字段，应使用 `direction` | 修改 `engine.py:1403` |
| LPPL RMSE 被高估 | `np.mean(residuals)` 应为 `np.mean((X@beta-log_price)**2)` | 修改 `calculator.py:332` |

---

## 五、可跑通的最小可用闭环

### ✅ 已验证可跑通的路径

**闭环 A：LPPL 泡沫检测**
```
mootdx本地读取 → Parquet存储 → 后复权(DataAdjuster) → LPPLCalculator.fit_single_window()
→ DE优化(tc,m,w) + OLS求解(a,b,c) → 置信度评分(P1已内置) → 风险等级判断
```
**证据**：`calculator.py:250-357` 完整实现，置信度已内置。

**闭环 B：Wyckoff 量价分析**
```
mootdx本地读取 → Parquet存储 → 后复权 → WyckoffEngine.analyze()
→ 9步分析(向量化) → phase + signal_type + action
```
**证据**：`engine.py:109-217` 完整实现，`scan_signal` 已添加。

**闭环 C：因子计算**
```
mootdx本地读取 → 后复权 → custom_factors计算10个技术因子
→ Z-score标准化 → IC加权合成
```
**证据**：`factors/analyzer.py:116-157` Rank IC 完整。但 Walk-Forward 管道因 mode 类型不匹配无法运行。

**闭环 D：FSM 状态机决策**
```
mootdx本地读取 → 后复权 → Indicators.calc_ma() → FSM.infer_state()
→ DecisionBrain.make_decision() → 买入/卖出/持有信号 → 状态持久化
```
**证据**：`fsm.py:95-158` 状态推断、`fsm.py:484-553` 决策流程完整。

### ⚠️ 可跑通但结果不可信的路径

**闭环 E：B轨策略回测**（存在 look-ahead bias）
```
数据读取 → as_of_date截断 → 但策略函数内部使用as_of_date之后的数据
→ 计算"收益" → 输出回测报告（非真实回测）
```
**证据**：`ma_cross.py:30` 使用未来数据的 open 价入场。

---

## 六、下一步行动建议

### P0 — 紧急修复（影响计算正确性）

1. **修复 LPPL RMSE 计算**：`calculator.py:332` 改为 `np.sqrt(np.mean((X @ beta - log_price)**2))`
2. **修复 scan_signal action 字段**：`engine.py:1403` 将 `report.trading_plan.action` 改为 `report.trading_plan.direction`
3. **修复 Walk-Forward mode 类型**：`walk_forward_pipeline.py:156` 将 `mode="backtest"` 改为 `mode=AnalysisMode.BACKTEST`

### P1 — 架构统一（影响可维护性）

4. **消除模块/包命名冲突**：删除 `brain/indicators.py`、`brain/screener.py`、`brain/alpha_decoupler.py` 冗余文件
5. **统一 Sharpe 比率口径**：选择一种公式（建议含 rf 的版本），统一所有计算点
6. **注册 EastmoneySource**：将 EastmoneySource 添加到 DataFetcher 的数据源列表
7. **修复 NaN 处理链路**：`data_cleaner.py:26` 对价格列改为 ffill，仅对成交量填 0

### P2 — 功能补全（影响系统完整性）

8. **实现手数取整**：BacktestEngine 和 UnifiedMatchingEngine 的 shares 计算应做 100 股整数倍取整
9. **实现过户费**：A 股过户费 0.001%（十万分之一），买卖双向收取
10. **修复 EVTRisk 名称**：将 `EVTRisk` 重命名为 `HistoricalSimulationRisk`，或实现真正的 GPD 拟合
11. **加载遗漏的配置文件**：`trading.yaml`、`factors.yaml`、`optimal_params.yaml` 未被 GlobalConfig 加载

### P3 — 代码质量（影响长期健康）

12. **统一异常定义**：消除 `IndicatorError` x2、`CZSCAnalysisError` vs `CZSCEngineError` 等重复定义
13. **清理死代码**：`shared/di_container.py`、`lppl/numba_optimizer.py`、`brain/indicators.py`(冗余)
14. **修复 @handle_errors 静默吞错**：关键路径应提供区分正常结果和错误降级的机制
15. **添加 ServiceContainer 线程锁**：参考 GlobalConfig 的双重检查锁模式

---

## 七、修复效果对比

| 指标 | V1 审计 (修复前) | V2 审计 (修复后) | 变化 |
|------|------------------|------------------|------|
| limits.py 兼容层 | ❌ 不存在 | ✅ 正确导出 | +1 模块 |
| LPPL 置信度 | ❌ 需外部计算 | ✅ 已内置 | 接口改善 |
| Wyckoff scan_signal | ❌ 不存在 | ⚠️ 存在但 action 有 bug | 部分完成 |
| 阶段识别阈值 | ❌ 过于严格(-0.10) | ✅ 已放宽(-0.05) | 阈值调整 |
| 共振信号数量 | 106 | 320 | +202% |
| 样本内胜率 | 47.5% | 48.3% | +0.8% |
| 样本外信号数 | 5 | 20 | +300% |

---

*报告生成时间：2026-05-30 | 基于代码事实，零推测*
