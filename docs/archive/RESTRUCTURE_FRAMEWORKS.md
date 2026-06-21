# UniQuant 重构框架方案汇总

> 基于 5 个并行分析 Agent 的深度研究 | 2026-05-27
>
> 范围: 算法层、数据层、风险/模型层、回测层、服务编排层

---

## 总览：五大框架现状

| 框架 | 现有文件 | 目标文件 | 完成度 | 核心阻塞 |
|------|---------|---------|--------|---------|
| **算法层** (brain/) | 5 | 30+ | 17% | 幽灵导入, Indicators 缺失 |
| **数据层** (data/) | 0 | 40+ | 0% | 整层不存在 |
| **风险层** (risk/) | 1 | 7 | 14% | __init__.py 缺失 |
| **回测层** (hands/) | 1 | 19+ | 5% | 整层空壳 |
| **服务层** (services/) | 11 | 24 | 46% | 8 个幽灵导入 |

---

## 一、算法层框架 (brain/)

### 1.1 已实现引擎

| 引擎 | LOC | 能力 | 接口 |
|------|-----|------|------|
| CZSCEngine | 623 | 缠论笔段中枢, 6 种买卖信号 | `get_czsc_signals(df)` |
| FSM + DecisionBrain | 656 | 7 状态机, Veto-Scoring 决策 | `infer_state(df)` / `make_decision(ctx)` |
| LPPLEngine | 992 | LPPL 泡沫检测, DE/L-BFGS-B 双优化器 | `detect_bubble_confidence(close)` |

### 1.2 缺失引擎 (按优先级)

| 优先级 | 引擎 | 依赖 | 工作量 |
|--------|------|------|--------|
| P0 | Indicators (10 种技术指标) | 无 | ~400 LOC |
| P0 | RegimeDetector (市场状态) | Indicators | ~250 LOC |
| P0 | NTFEngine (国家队因子) | 无 | ~200 LOC |
| P1 | AlphaDecoupler (超额收益解耦) | 无 | ~350 LOC |
| P1 | FactorRegistry (因子注册) | 无 | ~300 LOC |
| P1 | FactorAnalyzer (IC/IR 分析) | FactorRegistry | ~400 LOC |
| P2 | FactorComposer (多因子合成) | FactorAnalyzer | ~300 LOC |
| P2 | StockScreener (全市场扫描) | FactorComposer | ~400 LOC |
| P2 | WyckoffEngine (威科夫分析) | Indicators | ~1200 LOC |

### 1.3 关键重构机会

1. **接口统一**: 三个引擎方法签名不统一 (`update_and_get_signals` / `infer_state` / `detect_bubble`)，均未实现 `AnalysisEngineProtocol.analyze()`。建议添加统一适配层。

2. **并行化**: LPPL 的 `differential_evolution` 已支持 `workers` 参数（当前设为 1 避免嵌套死锁）。CZSC 的批量模式可向量化。

3. **缓存优化**: 各引擎独立缓存（2h TTL），可共享缓存键前缀减少重复计算。

4. **DecisionBrain 依赖链**: `make_decision()` 需要 6 个信号源 (regime/risk/bubble/ntf/czsc/alpha)，当前仅 CZSC 和 FSM 可用。补齐 Indicators → Regime → NTF 是关键路径。

---

## 二、数据层框架 (data/)

### 2.1 架构设计 (8 子包)

```
data/
├── sources/      # 9 个数据源 (mootdx离线/在线, TDX, BaoStock, Sina, Tencent, THS, Eastmoney, RealtimeBridge)
├── managers/     # 13 个管理器 (SourceRouter, 元数据, 交易日历, 复权因子, 增量更新等)
├── pipeline/     # 3 个管道 (DataCleaner, DataValidator, DataAdjuster)
├── lake/         # StorageManager (Parquet + Snappy + FileLock)
├── parsers/      # TDX 二进制解析器
├── services/     # 6 个导入服务 (日线, 1min, 5min, 财务, 指数, LPPL)
├── utils/        # 工具 (normalizer, akshare_wrapper, js_executor)
└── scripts/      # 同步脚本
```

### 2.2 数据源优先级 (SourceRouter 路由)

| 层级 | 数据源 | 速度 | 离线 | 分钟线 | 财务 |
|------|--------|------|------|--------|------|
| Tier 1 | mootdx 离线 | 极快 | ✅ | ✅ | ❌ |
| Tier 1 | mootdx 在线 | 快 | ❌ | ✅ | ❌ |
| Tier 2 | TDX 本地 | 快 | ✅ | ✅ | ✅ |
| Tier 3 | BaoStock | 中 | ❌ | ✅ | ✅ |
| Tier 4 | Sina/Tencent/THS | 慢 | ❌ | ✅ | ❌ |
| Tier 5 | Eastmoney | 慢 | ❌ | ✅ | ✅ |

### 2.3 数据湖设计

**目录结构**:
```
data/lake/
├── daily/          # 日线 Parquet (按股票代码分区)
├── 1mins/          # 1 分钟线
├── 5mins/          # 5 分钟线
├── weekly/         # 周线 (从日线合成)
├── monthly/        # 月线 (从日线合成)
├── financial/      # 财务数据
├── index/          # 指数数据
└── quarantine/     # 质量问题数据隔离区
```

**日线→周线/月线合成算法**:
- 周线: 同一周内第一个交易日 open, 最高价 high, 最低价 low, 最后一个交易日 close, 成交量 volume 合计
- 月线: 同理按月聚合

### 2.4 mootdx 集成方案

```python
# 离线读取 (Tier 1, 最快)
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir='/path/to/tdx')
daily = reader.daily(symbol='600519')

# 在线获取 (Tier 1)
from mootdx.quotes import Quotes
client = Quotes.factory(market='std', heartbeat=True)
realtime = client.quotes(symbol=['600519'])

# 复权因子
from mootdx.utils.factor import fq_factor
factor = fq_factor('600519', 'qfq')
```

### 2.5 迁移量

| 来源 | 文件数 | LOC |
|------|--------|-----|
| TDX 迁移 | 52 | ~14,100 |
| 新建 (mootdx) | 7 | ~700 |
| **总计** | **59** | **~14,800** |

---

## 三、风险与模型框架 (risk/)

### 3.1 已实现

| 模块 | LOC | 能力 |
|------|-----|------|
| DrawdownAnalyzer | 191 | 向量化回撤, MDD, Calmar |
| CostModel | 97 | 佣金/印花税/滑点/最低佣金 |
| LimitChecker | 212 | 涨跌停检查, 板块识别, 交易验证 |

### 3.2 缺失模块

| 模块 | 核心算法 | 依赖 |
|------|---------|------|
| PositionSizer | Kelly 准则 + T+1 惩罚 | CostModel, LimitChecker |
| EVTRisk | VaR/CVaR (GPD 拟合) | scipy.stats |
| PortfolioOptimizer | Risk Parity / Mean-Variance | numpy, scipy |
| StructuralRisk | 多指数风险矩阵 | numpy |

### 3.3 仓位管理算法

```
建议股数 = 最大允许亏损 / (单位风险 × 惩罚系数)

其中:
  最大允许亏损 = capital × risk_pct (默认 10%)
  单位风险 = price - max(atr_stop, czsc_bottom)
  惩罚系数 = 1.2 (CN, T+1 惩罚) / 1.0 (US/HK)
  最终股数 = floor(shares / 100) × 100  (A 股 100 股/手)
```

### 3.4 风险度量算法

**VaR (历史模拟法)**:
```
VaR_95 = percentile(returns, 5)
CVaR_95 = mean(returns[returns < VaR_95])
```

**EVT (极端值理论)**:
```
1. 选择阈值 u = percentile(returns, 10)
2. 拟合 GPD: G(x) = 1 - (1 + ξx/σ)^(-1/ξ)
3. VaR = u + σ/ξ × ((n/n_u × p)^(-ξ) - 1)
```

### 3.5 A 股约束实现

| 约束 | 实现位置 | 状态 |
|------|---------|------|
| T+1 | 回测引擎 (hands/) | 待迁移 |
| 涨跌停 | limit_checker.py | ✅ |
| 印花税 | cost_model.py | ✅ |
| 佣金 | cost_model.py | ✅ |
| 滑点 | cost_model.py | ✅ |
| 交易时段 | constants.py:MarketHours | ✅ |

---

## 四、回测框架 (hands/)

### 4.1 核心引擎

| 引擎 | 职责 | 关键特性 |
|------|------|---------|
| BacktestEngine | 单资产回测 | 4 种模式 (单次/滚动/Walk-Forward/压力) |
| UnifiedMatchingEngine | 向量化撮合 | T+1/涨跌停/滑点/佣金 NumPy 实现 |
| PortfolioEngine | 组合回测 | 多资产资金分配+再平衡 |

### 4.2 信号驱动流程

```
T 日: 策略生成信号 → {"action": "BUY"/"SELL"/"HOLD", "reason": "..."}
T+1 日开盘: UnifiedMatchingEngine 执行撮合
  → 检查 T+1 约束
  → 检查涨跌停
  → 计算滑点和佣金
  → 更新持仓和现金
```

### 4.3 策略框架

| 策略 | 权重 | 信号逻辑 |
|------|------|---------|
| MA Cross | 0.35 | MA5/MA20 金叉死叉 |
| Wyckoff | 0.30 | 威科夫量价分析 |
| Reversal | 0.20 | 短期超卖反弹 |
| Regime | 0.15 | 市场状态驱动 |

### 4.4 分析工具

| 工具 | 用途 |
|------|------|
| MonteCarloSimulator | 随机排列+Bootstrap 统计显著性 |
| OverfittingDetector | Deflated Sharpe Ratio (DSR) |
| RobustnessChecker | 不同市场条件稳健性 |
| SensitivityAnalyzer | 参数敏感性 (OAT) |
| BenchmarkComparator | CAPM Alpha/Beta, 信息比率 |

---

## 五、服务编排框架 (services/)

### 5.1 现有问题

1. **幽灵导入**: `services/__init__.py` 导出 8 个不存在的模块
2. **AnalysisService 过重**: 1650 行, 职责过多
3. **引擎串行执行**: 10 个引擎串行运行, 8 个可并行
4. **缺失核心服务**: DataService, CacheCoordinator 等

### 5.2 DAG 拓扑

```
StorageManager ──→ DataService ──→ AnalysisEngineFactory
      ↓                    ↓
TradeCalendarManager       ├─→ FsmAnalysisEngine
      ↓                    ├─→ CzscAnalysisEngine
CacheCoordinator           ├─→ LpplAnalysisEngine
                           ├─→ RegimeAnalysisEngine
                           └─→ ReportGeneratorEngine
```

### 5.3 缺失服务设计

| 服务 | 职责 | 依赖 |
|------|------|------|
| DataService | 数据门面, 缓存优先 | StorageManager, CacheCoordinator |
| CacheCoordinator | 缓存一致性, 健康监控 | shared/cache/ |
| ScanPipeline | 全市场扫描流水线 | FactorComposer, StockScreener |
| PortfolioService | 组合风险计算 | PositionSizer, EVTRisk |
| HealthService | 模块健康检查 | 所有服务 |
| StockQueryService | 股票代码映射 | 数据层元数据 |
| DataQualityService | 数据质量监控 | DataValidator |
| ValidationService | 计算结果验证 | 各引擎 |

### 5.4 重构机会

1. **拆分 AnalysisService**: 1650 行 → 4 个子服务 (已部分拆分: Macro/Technical/Signal/Wyckoff)
2. **引擎并行化**: `_run_engine_analysis` 中 10 个引擎, 8 个可并行 (ThreadPoolExecutor)
3. **降级策略**: 每个引擎已有 `_fallback_xxx_analysis()` 模式, 可统一
4. **缓存策略**: memory + disk 双级, 2h TTL, 可按引擎类型差异化

---

## 六、统一执行计划

### Phase 0: 紧急修复 (0.5-1h)
- [ ] services/__init__.py: 删除 8 个幽灵导入
- [ ] brain/lppl/__init__.py: 仅保留 engine.py 导入
- [ ] services/analysis/__init__.py: 删除 signal_service/wyckoff 导入
- [ ] brain/fsm/fsm.py: try/except 包裹 indicators 导入
- [ ] 创建 risk/__init__.py (最小导出)
- [ ] 验证: `python -c "import uniquant; import uniquant.shared"`

### Phase 1A: 基础层迁移 (1-1.5h)
- [ ] 迁移 brain/indicators.py (10 种技术指标)
- [ ] 迁移 brain/ntf/, brain/regime/
- [ ] 迁移 risk/sizer.py, risk/evt_risk.py
- [ ] 修复 engine_factory DecisionBrain 参数
- [ ] 验证: `python -c "from uniquant.brain.indicators import Indicators"`

### Phase 1B: 数据层迁移 (2-3h)
- [ ] 迁移 data/ 全层 (52 文件)
- [ ] 创建 data/__init__.py
- [ ] 验证: `python -c "from uniquant.data.data_fetcher import DataFetcher"`

### Phase 1C: 服务层迁移 (1-1.5h, 依赖 Phase 1B)
- [ ] 迁移 DataService, CacheCoordinator 等 8 个服务
- [ ] 恢复 services/__init__.py 完整导入
- [ ] 验证: `python -c "from uniquant.services.data_service import DataService"`

### Phase 2: mootdx 适配 (2-3h, 依赖 Phase 1B)
- [ ] 迁移 DataService, CacheCoordinator 等 8 个服务
- [ ] 恢复 services/__init__.py 完整导入
- [ ] 验证: `python -c "from uniquant.services.data_service import DataService"`

### Phase 1D: 算法层补全 (0.5-1h)
- [ ] 迁移 LPPL 子模块 (8 文件)
- [ ] 迁移因子系统 (8 文件)
- [ ] 迁移 screener.py
- [ ] 验证: `python -c "from uniquant.brain.factors import FactorAnalyzer"`

### Phase 1E: 回测层迁移 (0.5-1h)
- [ ] 迁移 hands/backtest/ (12 文件)
- [ ] 迁移 hands/strategies/ (9 文件)
- [ ] 迁移 reporter.py, results_manager.py
- [ ] 验证: `python -c "from uniquant.hands.backtest import BacktestEngine"`

### Phase 1F: UI 层迁移 (0.3-0.5h)
- [ ] 迁移 components.py, lppl_visualizer.py, manager_logic.py
- [ ] 恢复 dashboard.py 正常导入
- [ ] 验证: `streamlit run src/uniquant/ui/dashboard.py`

### Phase 3: 验证 (2-3h)
- [ ] 迁移 68 个测试文件
- [ ] 修复 import 路径
- [ ] pytest 通过率 > 80%

### Phase 4: 清理 (0.5h)
- [ ] 删除 deprecated 模块 (errors.py, limits.py, di_container.py)
- [ ] 补充缺失依赖 (pybreaker, tenacity)
- [ ] 可选: 拆分 constants.py

**总估算: ~14-18h (现实估计, 含调试缓冲) | ~10-12h (乐观估计) | ~20-25h (悲观估计)**

---

*生成时间: 2026-05-27 | 基于代码和文档事实, 禁止幻觉*
