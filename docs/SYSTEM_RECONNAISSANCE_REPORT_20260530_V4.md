# UniQuant 系统现状全景侦察报告 (V4)

> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md

> 审计时间：2026-05-30 | 4 路 Subagent 并发审计
> 本报告为 V3 修复后的最终审计

---

## 一、V3 修复验证结果

| # | 修复项 | 状态 | 证据 |
|---|--------|------|------|
| P0-1 | 手数取整 | ✅ 通过 | `engine.py:182`, `unified_matching_engine.py:115` |
| P0-2 | prior_trend_pct | ✅ 通过 | `engine.py:280-288` 实际计算，`engine.py:430` 传入 |
| P0-3 | base.py 导入 | ✅ 通过 | `base.py:12` 使用 `uniquant.risk.sizer` |
| P0-4 | scan_signal 映射 | ✅ 通过 | `engine.py:1407-1408` 7 buy + 6 sell 关键词 |
| P1-1 | 原子写入 | ✅ 通过 | `storage_manager.py` 3 处使用 `os.replace()` |
| P1-2 | 过户费常量 | ✅ 通过 | `cost_model.py:30` 添加 `TRANSFER_FEE_PCT` |
| P1-3 | CZSC 异常统一 | ✅ 通过 | `czsc_engine.py` 使用 `CZSCEngineError` |
| P1-4 | ServiceContainer 锁 | ✅ 通过 | `service_container.py:31,37-43` 双重检查锁 |
| P1-5 | 模块命名冲突 | ✅ 通过 | 3 个 `.py` 文件已删除，仅保留包目录 |
| P1-6 | Walk-Forward mode | ✅ 通过 | `walk_forward_pipeline.py:130,155,179` 使用枚举 |
| P1-7 | NaN 处理 | ✅ 通过 | `data_cleaner.py:26-34` 价格列不填 0 |
| P1-8 | EastmoneySource | ✅ 通过 | `data_fetcher.py:28,71` 已注册 |

**结论：12/12 项修复全部验证通过。**

---

## 二、模块状态矩阵

| 包 | 状态 | 遗留问题 |
|---|------|----------|
| **shared/limits.py** | ✅ 生产可用 | 兼容层正确导出 |
| **shared/cost_model.py** | ⚠️ 勉强可用 | CostConfig.cost_sell 遗漏过户费 |
| **shared/config_loader.py** | ⚠️ 勉强可用 | config=None 模块级变量风险 |
| **data/** | ⚠️ 勉强可用 | fq/factors 目录为空，过户费未集成到引擎 |
| **brain/lppl/** | ✅ 生产可用 | RMSE 正确，置信度已内置 |
| **brain/wyckoff/** | ✅ 生产可用 | prior_trend_pct 已修复，scan_signal 映射完整 |
| **brain/czsc/** | ✅ 生产可用 | CZSCEngineError 统一 |
| **brain/factors/** | ✅ 生产可用 | Walk-Forward mode 枚举正确 |
| **brain/fsm/** | ✅ 生产可用 | 7 状态 FSM + FileLock |
| **hands/backtest/** | ⚠️ 勋强可用 | Sharpe 口径不一致，过户费未集成 |
| **hands/strategies/** | ⚠️ 勋强可用 | B轨 look-ahead bias 无警告 |
| **risk/** | ⚠️ 勋强可用 | EVTRisk 名不副实 |
| **services/** | ⚠️ 勋强可用 | initialize() 无锁 |
| **signal/** | ✅ 生产可用 | 归一化、聚合完整 |
| **ui/** | ✅ 生产可用 | Streamlit 仪表盘完整 |

---

## 三、核心数据流图解

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据采集层]                                      │
│  mootdx本地 ─┐                                                          │
│  mootdx在线 ─┤                                                          │
│  baostock   ─┤                                                          │
│  sina       ─┼─→ SourceRouter ─→ DataFetcher ─→ DataIngestionService    │
│  ths        ─┤     (故障转移)      (LRU缓存)         (同步脚本)          │
│  tencent    ─┤                                                          │
│  eastmoney  ─┘  ✅ 已注册                                               │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ DataFrame(date,open,high,low,close,volume)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [数据存储层]                                      │
│  StorageManager ──→ data/lake/quotes/{daily,weekly,monthly}/*.parquet   │
│       │                ✅ 原子写入 os.replace()                          │
│       └─→ DataAdjuster ──→ 前复权/后复权                                │
│                                                                         │
│  ⚠️ data/fq/ 和 data/factors/ 目录为空，复权因子数据缺失                  │
│  ⚠️ NaN处理: 价格列不填 0 ✅，成交量列填 0 ✅                             │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ 复权后 DataFrame
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [分析引擎层]                                      │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐   │
│  │  LPPL   │  │  Wyckoff │  │  CZSC   │  │  Factors │  │   FSM    │   │
│  │ ✅完整  │  │ ✅完整   │  │ ✅完整  │  │ ✅完整   │  │ ✅完整   │   │
│  │ RMSE正确│  │ prior修复│  │ 异常统一│  │ WF枚举   │  │ 7状态    │   │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └────┬─────┘  └────┬─────┘   │
│       └────────────┴─────────────┴─────────────┴─────────────┘          │
│                              │ AnalysisResult                           │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │              DecisionBrain (brain/fsm/fsm.py)                 │       │
│  └──────────────────────────────┬───────────────────────────────┘       │
└─────────────────────────────────┼───────────────────────────────────────┘
                                  │ 交易信号
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [回测撮合层]                                      │
│  BacktestEngine (逐bar)          UnifiedMatchingEngine (向量化)         │
│       ├─ T+1: 交易日历 ✅              ├─ T+1: 日历日 ⚠️               │
│       ├─ 涨跌停: 5板块 ✅              ├─ 涨跌停: 5板块 ✅              │
│       ├─ 手数取整: ✅                  ├─ 手数取整: ✅                   │
│       └─ 过户费: ❌ 未集成             └─ 过户费: ❌ 未集成              │
│                                                                         │
│  ⚠️ Sharpe 口径不一致 (5处不扣rf，2处rf值不同)                          │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        [风控层]                                          │
│  DrawdownAnalyzer ✅     PositionSizer ✅     PortfolioOptimizer ✅      │
│  EVTRisk ⚠️ 名不副实                                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四、技术债与高危地带雷达

### 🔴 TOP 3 高危代码位置

**1. `config_loader.py:305` — config=None 模块级变量导致隐式空引用**
```python
config = None  # 5 个模块导入此变量，运行时可能为 None
```
`calculator.py:10`、`structural.py:3`、`regime_detector.py:7`、`ntf_engine.py:9`、`alpha_decoupler.py:7` 均导入此变量。如果在 `get_config()` 被首次调用前使用，将抛出 `AttributeError`。

**2. `result.py:100-103` vs `portfolio_engine.py:339` — Sharpe 口径严重不一致**
- `result.py`: rf=2%，daily excess return 方法
- `portfolio_engine.py`: rf=3%，年化收益/年化波动率方法
- `evt_risk.py`、`monte_carlo.py`、`overfitting_detector.py`、`robustness_checker.py`: rf=0%

**3. `service_container.py:58-60` — initialize() 无锁竞态**
```python
def initialize(self) -> None:
    if self._initialized:  # 无锁读
        return
    # ... 初始化逻辑 ...
    self._initialized = True  # 无锁写
```

### 🟡 次高危地带

| # | 位置 | 问题 |
|---|------|------|
| 4 | `engine.py:71-75` | 过户费未集成到 _calculate_commission |
| 5 | `unified_matching_engine.py:32-49` | 过户费未集成到构造函数 |
| 6 | `portfolio_engine.py:115` | 手数取整遗漏 |
| 7 | `cost_model.py:97-98` | CostConfig.cost_sell 遗漏过户费 |
| 8 | `data/fq/` 目录 | 复权因子数据为空 |
| 9 | `evt_risk.py:24,389` | EVTRisk 名不副实 |
| 10 | `brain/__init__.py:8` | FSM 导入未保护 |

---

## 五、遗留问题清单

### HIGH 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| H1 | config=None 模块级变量风险 | `config_loader.py:305` |
| H2 | Sharpe 口径不一致 | `result.py:100` vs `portfolio_engine.py:339` |
| H3 | ServiceContainer.initialize() 无锁 | `service_container.py:58-60` |
| H4 | trading.yaml/factors.yaml 未被 GlobalConfig 加载 | `config_loader.py:66-69` |
| H5 | 过户费未集成到回测引擎 | `engine.py:71-75`, `unified_matching_engine.py:32-49` |

### MEDIUM 级别

| # | 问题 | 文件:行号 |
|---|------|-----------|
| M1 | portfolio_engine.py 手数取整遗漏 | `portfolio_engine.py:115` |
| M2 | CostConfig.cost_sell 遗漏过户费 | `cost_model.py:97-98` |
| M3 | DIContainer 死代码 | `shared/di_container.py:1-80` |
| M4 | brain/__init__.py FSM 导入未保护 | `brain/__init__.py:8` |
| M5 | try/except 静默吞错无日志 | `brain/__init__.py:10-41` |
| M6 | 复权因子数据为空 | `data/fq/`, `data/factors/` |
| M7 | EVTRisk 名不副实 | `evt_risk.py:24,389` |

---

## 六、下一步行动建议

### P0 — 紧急修复

1. **修复 config=None 风险**：5 个文件改用 `get_config()` 而非导入模块级变量
2. **统一 Sharpe 口径**：抽取公共函数，统一 rf 值和计算公式
3. **集成过户费到回测引擎**：`engine.py` 和 `unified_matching_engine.py` 添加过户费计算

### P1 — 重要修复

4. **修复 ServiceContainer.initialize()**：添加锁保护
5. **修复 portfolio_engine.py 手数取整**：`// 100 * 100`
6. **加载遗漏配置文件**：将 trading.yaml 纳入 GlobalConfig
7. **下载复权因子数据**：运行 sync_factors_mootdx.py

### P2 — 改进项

8. **清理 DIContainer 死代码**
9. **保护 brain/__init__.py FSM 导入**
10. **重命名 EVTRisk 为 HistoricalSimulationRisk**

---

*报告生成时间：2026-05-30 | 基于代码事实，零推测*
