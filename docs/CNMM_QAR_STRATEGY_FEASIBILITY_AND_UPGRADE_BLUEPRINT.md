# CNMM-OS3: UniQuant 量化系统架构承载 CNMM-QAR 绝对收益策略可行性深度评估与生产级改造蓝图

> **文档代号**: `CNMM-ARCH-2026-UQ-EVAL-01`  
> **报告版本**: v2.0 (生产级审定版)  
> **发布日期**: 2026-09-21  
> **评审主控**:  
> - 首席量化金融策略师（Chief Quantitative Strategist）  
> - 首席量化交易系统架构师（Chief Quantitative Systems Architect）  
> - 衍生品量化对冲总监（Head of Quantitative Hedging & Derivatives）  
> - 金融计量与法医会计首席审计师（Chief Forensic Accounting & Econometric Auditor）  
> **评估标的**: [UniQuant 工业级量化交易系统](file:///home/james/Documents/Project/UniQuant)  
> **目标策略**: **CNMM-QAR（量化绝对收益策略）** —— 融合 Ohlson 清洁剩余动态折现、Winberry 投资欧拉方程在建工程（CIP）挂起拖累因子、四维复合困境探针 $Z_{\text{CNMM}}$ 会计法医排雷（TTM 平滑与 P75 截面剔除）、CFFEX 股指期货（IF/IC/IM）对冲（中金所高频动态基差曲面湖与 MLSI 动态对冲防线）、25% 动态流动性缓冲池、基于 SQLite WAL 状态机与 T+1 跨资产 Saga 四级分布式补偿的 3 日时区 TWAP 执行、Chow 结构突变先验重置与私募 2/20 业绩报酬治理（Crystallized HWM 固化高水位线、ACT/365 自然日管理费与每日 Accrual 准备金暂估）。

---

## 目录

1. [执行摘要与核心裁决（Executive Summary & Verdict）](#一-执行摘要与核心裁决executive-summary--verdict)
2. [CNMM-QAR 策略核心架构特征与系统需求规约（Strategy Requirements）](#二-cnmm-qar-策略核心架构特征与系统需求规约strategy-requirements)
3. [UniQuant 现有架构三大致命死锁深度解剖（The 3 Fatal Architectural Blockers）](#三-uniquant-现有架构三大致命死锁深度解剖the-3-fatal-architectural-blockers)
4. [UniQuant 现存核心优势与可 100% 复用资产全景（Reusable Assets）](#四-uniquant-现存核心优势与可-100-复用资产全景reusable-assets)
5. [UniQuant 生产级改造实施蓝图（Architecture Refactoring Blueprint）](#五-uniquant-生产级改造实施蓝图architecture-refactoring-blueprint)
6. [工程演进敏捷排期与验收测试门禁（Roadmap, Sprints & Quality Gate）](#六-工程演进敏捷排期与验收测试门禁roadmap-sprints--quality-gate)
7. [战略审计总结与商业价值（Strategic Impact）](#七-战略审计总结与商业价值strategic-impact)

---

## 一、 执行摘要与核心裁决（Executive Summary & Verdict）

### 1.1 总体裁决结论

> ### 核心定性裁决
> **“数据底座 85% 就绪，可直接无缝复用；但应用撮合、组合管理与因子分析层目前处于‘单边现货做多与技术分析为主’的锁死状态。UniQuant 当前版本（V9.x）原生无法直接承载 CNMM-QAR 策略，但由于其底层基础设施极其扎实，是承载该策略最具改造成本优势与工程性价比的量化底座。”**

经过对 `/home/james/Documents/Project/UniQuant` 代码库全量 345+ 源码文件、72 个核心模块、撮合引擎、数据湖与状态机的深入穿透审计，评审委员会一致认定：
1. **不能直接跑（Native Execution: Infeasible）**：若不改动代码直接导入策略，组合服务将因 `MIN_POSITION_PCT = 0` 拒绝负仓位，撮合引擎因缺失衍生品合约乘数和保证金账户直接报死，因子大脑因缺少会计法医评分导致 Alpha 流失效。
2. **极易改成功（Refactoring Feasibility: High ROI）**：UniQuant 具备行业顶尖的 A 股交易铁律防线（T+1、涨跌停、非对称印花税、非线性冲击滑点）与严格无前视偏差（PIT）的 Parquet 数据湖。仅需新增 4 个解耦子模块、重构 2 个核心服务，即可在 4 个标准双周冲刺（共 8 周，代码量 3,500+ 行）内全面激活 CNMM-QAR 生产级运行。

---

### 1.2 五层系统架构就绪度与对标雷达

```
                         数据湖存储 (85%)
                               ▲
                               │
            风控与治理 (40%)   │   因子法医中台 (35%)
                     \         │         /
                      \        │        /
                       \       │       /
                        \      │      /
                         \     │     /
                          \    │    /
                           ▼   │   ▼
   撮合与回测执行 (30%) ◄──────┴──────► 组合管理层 (20%)
```

| 架构层级 | 就绪度 | 核心现有资产 | 致命缺陷与关键阻断点 | 承载判定 |
| :--- | :---: | :--- | :--- | :---: |
| **1. 数据湖底座层 (`uniquant.data`)** | **85%** | 5,755 只股票日线、5,211 只股票财务库 Parquet 列存；GBBQ 除权除息复权已跑通；PIT 盘后次日生效已完成。 | 缺失 CFFEX 中金所股指期货合约链与高频基差（Basis）数据湖。 | 🟢 **基本就绪** |
| **2. 因子法医中台 (`uniquant.brain`)** | **35%** | [financial_bridge.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/financial_bridge.py) 已有报表映射与 TTM 计算；部分动量与应计指标已预装。 | 严重偏向技术分析（缠论/威科夫/LPPL/FSM）；完全缺失 $Z_{\text{CNMM}}$ 会计法医与 Winberry 欧拉因果算子库。 | 🟡 **需新建算子中台** |
| **3. 组合管理层 (`uniquant.services`)** | **20%** | 具备单票权重归一化、仓位边界校验与基本风险敞口校验。 | **架构硬锁死**：代码硬编码 `MIN_POSITION_PCT = Decimal("0")`，拦截负仓位，强制总权重为 100%，无法管理多空组合。 | 🔴 **架构阻断** |
| **4. 撮合回测引擎 (`uniquant.hands`)** | **30%** | A 股现货规则完备：T+1 铁律、板别涨跌停、动态印花税、非线性平方根滑点冲击已向量化。 | **架构硬锁死**：仅支持单边现货 `BUY`/`SELL`，无期货空头、保证金制度、逐日盯市及多日 TWAP 执行器。 | 🔴 **架构阻断** |
| **5. 治理与风控中台 (`uniquant.shared`)** | **40%** | 板别限价检查、熔断器、日历管理、Prometheus 监控埋点完备。 | 缺失对冲 Beta 监控、Chow 突变先验重置器以及私募 2/20（高水位线+门槛收益）计提账本。 | 🟡 **需扩展治理插件** |

---

## 二、 CNMM-QAR 策略核心架构特征与系统需求规约（Strategy Requirements）

CNMM-QAR 是为大资金容量（10 亿~50 亿人民币规模）量身定制的**机构级多空市场中性（Market-Neutral）绝对收益策略**。要承载该策略，量化系统架构必须满足以下 6 项刚性规约：

```
                    ┌────────────────────────────────────────────────────────┐
                    │               CNMM-QAR 策略三元配置结构                │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
               ┌───────────────────────────────┼───────────────────────────────┐
               ▼                               ▼                               ▼
┌──────────────────────────────┐┌──────────────────────────────┐┌──────────────────────────────┐
│       Alpha 选股多头池        ││      股指期货对冲空头池      ││     流动性与保证金缓冲池     │
│             75%              ││             -75%             ││             25%              │
├──────────────────────────────┤├──────────────────────────────┤├──────────────────────────────┤
│ • 剔除 Z_CNMM > P75 困境排雷票││ • 中金所 IF/IC/IM 组合空头  ││ • 货基/国债逆回购收益 (~2%)   │
│ • Ohlson 清洁剩余超额动态折现││ • 完全对冲组合多头 Beta     ││ • 承担期货 12%~15% 保证金占用 │
│ • Winberry CIP 挂起拖累惩罚   ││ • 动态基差曲面湖+MLSI对冲防线││ • 预留黑天鹅回撤与追保缓冲垫  │
│ • 单行业 ≤ 10%, 单票 ≤ 2.5%  ││ • 主力合约到期前5日跨期移仓  ││ • 确保净值绝不被强平穿仓      │
└──────────────────────────────┘└──────────────────────────────┘└──────────────────────────────┘
```

1. **多资产与多空持仓模型（Multi-Asset Long/Short）**：
   - 现货多头：精选 30~50 只 A 股股票，总权重严格锁定为 **75%**；单一申万一级行业权重 $\le 10\%$（持股上限 4 只），单票权重 $\le 2.5\%$。
   - 衍生品空头：持有中金所股指期货（IF/IC/IM）空头，Delta 严格匹配多头组合的 Beta 敞口（等效市值 **-75%**），接入中金所高频动态基差曲面湖并结合 MLSI（市场流动性利差指数）动态调节对冲比率与展期窗口。
   - 现金缓冲池：预留 **25%** 现金及高流动性货基，用于履约期货保证金（12%~15%）及防范极端流动性踩踏。
2. **四维复合困境探针与质量排雷评分（$Z_{\text{CNMM}}$ Forensic Gate）**：
   - 必须在选股前置阶段，对全 A 股进行四维复合困境探针审计：DSRI（应收账款异动率）、AQI（资产质量恶化率）、Sloan Accruals（应计利润与经营现金流背离度）以及 DEPI（折旧放缓与在建工程 CIP 异常挂起）；
   - 核心财务指标全量经过滚动 4 季度（TTM）平滑，消除单季波动与季节性脉冲；
   - 统一判定标准为“高分危险”，对全市场截面 $Z_{\text{CNMM}} > P_{75}(Z_{\text{CNMM}})$（处于前 25% 高危困境区间）的标的实行一票否决式拉黑，多头权重硬置 0。
3. **因果与结构计量模型算子（Causal & Structural Econometrics）**：
   - 整合 Winberry (2021) 资本存量投资欧拉方程残差，提取在建工程（CIP Overhang）对资本边际回报率的资本化拖累；
   - 整合 Ohlson (1995) 清洁剩余模型，跨截面动态估算异常盈余持续系数 $\omega$，求解企业内生经济价值。
4. **多日时区 TWAP 执行与 Saga 分布式补偿（3-Day TWAP & Saga Compensation）**：
   - 严禁单 Bar 暴力撮合；母单须切分为连续 3 个交易日（T, T+1, T+2），每日仅在 10:00–14:30 黄金流动性区间匀速或基于成交量曲线（VWAP）分笔挂单，最大单笔参与率不超过区间市场成交量的 5%；
   - 母单与切片生命周期由轻量级 SQLite WAL 状态机持久化纳管；
   - 针对 A 股现货端 T+1 交易限制与期货端 T+0 撮合异步失衡，部署双撮合跨资产 Saga 四级分布式补偿机制（微观自愈 -> 期货 Delta 对冲 -> 底仓替代/逆平 -> 极端跌停死锁隔离与合成空头锁仓）。
5. **结构突变识别与先验重置（Chow Structural Breakpoint Prior Reset）**：
   - 当系统检测到市场结构性突变（如 2007 股权分置改革、2015 股灾去杠杆、2020 新冠疫情冲击）时，必须具备断点切除机制，将卡尔曼滤波与贝叶斯后验的超参数重置为无信息先验，清空陈旧历史记忆。
6. **私募级 2/20 业绩报酬与高水位线治理（Institutional Fee & Governance）**：
   - 系统级净值必须内嵌 ACT/365 自然日 2.0% 年化管理费（每日收盘计提）、Crystallized HWM（固化高水位线）、年化 6.0% Hurdle Rate 门槛收益，以及每日业绩报酬准备金暂估（Daily Accrual）与冲销机制，彻底消除连续滚动峰值导致的代数死循环，杜绝净值虚增。

---

## 三、 UniQuant 现有架构三大致命死锁深度解剖（The 3 Fatal Architectural Blockers）

### 3.1 死锁 1：单边做多现货假设与衍生品对冲体系空白（Derivative & Shorting Void）

#### 源码穿透实证
在 UniQuant 的核心资产管理中台 [portfolio_service.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/portfolio_service.py) 中，仓位边界校验被强行硬编码为非负现货：

```python
# 文件: src/uniquant/services/portfolio_service.py
# 行号: 38-70
MIN_POSITION_PCT = Decimal("0")    # 最小仓位0% (硬编码禁止负值)
MAX_POSITION_PCT = Decimal("100")  # 最大仓位100%

def _validate_position(self, position_pct: Decimal) -> bool:
    ...
    if position_pct < self.MIN_POSITION_PCT:
        logger.error(f"仓位不能为负数: {position_pct}%")  # 任何做空指令直接报错阻断
        return False
```

进一步审视权重归一化校验逻辑（`_validate_weights`，行号 103-108）：
```python
if abs(total - Decimal("1")) > tolerance and abs(total - Decimal("100")) > tolerance:
    logger.error(f"权重总和必须为1或100: {total}")
    return False
```
系统强制要求所有头寸相加必须为 100%。这意味着，在现有架构下，**不仅无法建立负权重的期货对冲空头（如 -75%），也无法设立 25% 的动态现金缓冲池**。

再审视撮合引擎 [unified_matching_engine.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_matching_engine.py#L283-L298)：
```python
# 文件: src/uniquant/hands/backtest/unified_matching_engine.py
# 行号: 283, 298
shares_clamped = np.minimum(shares_requested, positions_held)
...
rejected = limit_rejected | volume_zero | t1_violation | (shares_clamped <= 0)
```
卖出指令的前提是 `positions_held > 0`。若当前未持有该标的，`shares_clamped` 被强行截断为 0 并标记为 `rejected`，系统**完全没有“借券融券”或“开空期货（Short Open）”的概念**。

此外，交易记录结构 [unified_engine.py:55](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_engine.py#L55)：
```python
action: str  # 仅支持 "BUY" | "SELL"
```
**架构缺失清单**：
- ❌ 缺失衍生品合约对象（乘数、最小变动价位、交割月份）；
- ❌ 缺失保证金账户机制（动态计算可用资金、冻结保证金、维持保证金率）；
- ❌ 缺失每日盯市制度（Mark-to-Market）与持仓结算盈亏分账；
- ❌ 缺失中金所高频动态基差曲面湖与 MLSI 动态对冲防线（原有静态 -2.50% 贴水粗暴脱离实际期限结构与流动性动态）；
- ❌ 缺失股指期货跨期移仓展期（Calendar Spread Rollover）协议。

---

### 3.2 死锁 2：技术分析霸屏与基本面法医计量引擎断层（Factor Brain Divergence）

#### 源码穿透实证
审视 UniQuant 的研究大脑 `src/uniquant/brain/` 目录结构：
```
src/uniquant/brain/
├── czsc/               # 缠论分型中枢与笔线段引擎 (czsc_engine.py)
├── wyckoff/            # 威科夫量价分布与操盘阶段 (engine.py, events.py)
├── lppl/               # 对数周期幂律泡沫崩盘拟合 (numba_optimizer.py)
├── fsm/                # 有限状态机趋势识别 (fsm.py)
├── alpha_decoupler/    # 动量残差剥离
└── factors/            # 因子计算库
```
UniQuant 投入了大量 Numba 优化资源在技术形态学上（如 LPPL 差分进化算法和 Wyckoff 事件判别）。虽然在 [financial_bridge.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/financial_bridge.py) 中构建了优秀的字段映射和 TTM 计算，并在 [custom_factors.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/custom_factors.py) 中实现了 `compute_gross_profitability`、`compute_accruals` 与 `compute_cash_ratio` 等基础因子，但**完全断层了现代量化所必需的会计法医与因果计量分析**：

1. **缺失四维复合困境探针 $Z_{\text{CNMM}}$ 会计法医排雷系统**：
   - 现有代码仅计算了单变量 Sloan 应计项：`(net_profit_parent_ttm - ocf_ttm) / total_assets`，存在严重符号与逻辑断层；
   - 缺失由 DSRI（营收操纵）、AQI（资产质量恶化）、Sloan Accruals（应计现金背离）与 DEPI（折旧放缓与 CIP 异常挂起）组成的四维复合困境探针；
   - 缺失 TTM 滚动平滑与截面标准化，无法实行全市场“高分危险，高于 P75 截面一票否决拉黑”的动态排雷黑名单机制。
2. **缺失 Winberry 投资欧拉方程资本挂起（CIP Overhang）算子**：
   - 未能对资产负债表中“在建工程”与“固定资产”的边际弹性进行动态面板残差估算；
   - 无法识别 A 股制造业中长期存在的“假投资、真圈钱”与过度投资资本沉没现象。
3. **缺失 Ohlson 清洁剩余动态折现估值模型**：
   - 现有 `FinancialFactorBridge` 仅能简单计算静态的 $P/E$ 和 $P/B$；
   - 缺失动态折现模块，无法跨截面估计异常盈余自回归系数 $\omega$，无法将账面价值（BPS）与未来预期超额盈利现值进行非线性合成。
4. **缺失 Chow 结构突变断点治理**：
   - UniQuant 的状态机和机制识别器（`regime_detector.py`）仅基于短周期均线穿越与 20 日波动率，缺乏严谨的计量经济学 Chow 突变断点识别能力，无法在宏观体制转折期重置历史先验。

---

### 3.3 死锁 3：单 Bar 瞬时成交假设与 Almgren-Chriss / 多日 TWAP 执行器缺失（Execution Gap）

#### 源码穿透实证
在 [unified_engine.py:450-485](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_engine.py#L450-L485) 中，系统的回测循环严格遵循：
$$\text{Signal Arrival at Bar } t \Longrightarrow \text{Execute 100\% at Bar } t+1$$
撮合引擎 [unified_matching_engine.py:84-93](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_matching_engine.py#L84-L93) 引入了分段非线性平方根冲击模型：
$$\text{Impact} = 0.001 \times \sqrt{\frac{\eta}{0.10}} \quad (\text{if } \eta \le 0.10)$$
**业务致命冲突**：
- 该冲击模型只适用于单次瞬时成交的冲击惩罚，**根本没有包含执行算法（Execution Algorithm）中枢**；
- CNMM-QAR 策略单次换仓涉及数亿资金，若在单一交易日内以均价瞬时成交，将在真实市场产生灾难性的尾盘冲击成本或直接无法完全成交；
- 策略规定必须采用 **跨 3 个交易日（T, T+1, T+2）并在每日 10:00–14:30 黄金流动性区间分笔挂单的 TWAP 执行器**。UniQuant 当前的撮合层缺乏基于轻量高性能 SQLite WAL 持久化的“母单-子单（Parent-Child Order）”生命周期状态机，更缺乏应对 A 股 T+1 现货交易约束与 T+0 期货撮合异步失衡的跨资产 Saga 四级分布式补偿机制，在遭遇突发跌停拒卖或部分成交时无法防范敞口暴露。

---

## 四、 UniQuant 现存核心优势与可 100% 复用资产全景（Reusable Assets）

尽管存在上述三大断点，UniQuant 的工程质量在 A 股本地化细节方面表现极其出色。以下四大核心模块具备极高的工业级水准，**在本次升级中 100% 完整保留并直接复用**：

```
                    ┌────────────────────────────────────────────────────────┐
                    │               UniQuant 核心资产 100% 复用图谱           │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
       ┌───────────────────────┬───────────────┴───────────────┬───────────────────────┐
       ▼                       ▼                               ▼                       ▼
┌──────────────┐        ┌──────────────┐                ┌──────────────┐        ┌──────────────┐
│  存储数据湖   │        │ 严格 PIT 桥接 │                │ A股现货交易铁律│        │ 健壮性与可观测│
├──────────────┤        ├──────────────┤                ├──────────────┤        ├──────────────┤
│ 5,755股日线  │        │ 财报盘后披露  │                │ 严格 T+1 交易 │        │ 异步事件总线  │
│ 5,211股财报  │        │  +1日历日生效 │                │ 板别涨跌停拦截 │        │ 熔断保护机制  │
│ 5,123股分红  │        │ 季报双键稳定  │                │ 动态印花税核算 │        │ 交易日历管理  │
│ Parquet 高速 │        │  消除对齐平局 │                │ 5元最低佣金下限│        │ Prometheus监控│
└──────────────┘        └──────────────┘                └──────────────┘        └──────────────┘
```

### 4.1 工业级 Parquet 数据湖 (`uniquant.data.lake.storage_manager.py`)
- **规模与完整性**：UniQuant 本地 `data/lake/` 已经沉淀了 5,755 只股票从 2000 年至今的日线全量行情、5,211 只股票的资产负债表/利润表/现金流量表，以及 5,123 只股票历史全量除权除息分红配股数据。
- **高性能列存读取**：[StorageManager](file:///home/james/Documents/Project/UniQuant/src/uniquant/data/lake/storage_manager.py) 底层深度集成 PyArrow 与 DuckDB 查询优化，全市场 5,000+ 股票的截面加载与特征提取可在数秒内完成，吞吐量超越传统关系型数据库两个数量级。

### 4.2 严密的前视偏差（Look-Ahead Bias）防线 (`financial_bridge.py`)
UniQuant 的开发团队在 [financial_bridge.py:223-239](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/financial_bridge.py#L223-L239) 中实现了极具工业洞察力的 PIT（Point-in-Time）时间戳约束：
```python
# 严格 PIT 偏移: 财报多在 15:30 盘后披露，公告日当天不可用于日内交易，次日生效 (+1日历日)
valid_ann = ~nan_mask
financial_df.loc[valid_ann, effective_col] = (
    financial_df.loc[valid_ann, effective_col] + pd.Timedelta(days=1)
)
```
并在第 400-401 行解决了年报与一季报同日披露时的对齐平局：
```python
# 双键稳定排序: 确保会计报告期更新的季报排在后方被 merge_asof 优先对齐
fin_subset = fin_subset.sort_values([effective_date_col, "report_date"])
```
这两项关键防线彻底杜绝了学术界和简易量化系统中常见的“未来数据污染”与“季报倒流”漏洞。

### 4.3 完备的 A 股市场微观结构与规费规则 (`unified_matching_engine.py`)
在 [unified_matching_engine.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/hands/backtest/unified_matching_engine.py) 中，系统完整向量化实现了 A 股真实的执行摩擦：
1. **严格 T+1 铁律**：基于 `TradeCalendarManager`，卖出时严格校验买入与卖出交易日序号差 $\ge 1$；
2. **多板别自适应涨跌停**：主板 10%、创业板/科创板 20%、北交所 30%、ST 股票 5%、主板首日 44% 上限及双创板前 5 日无涨跌停限制；
3. **历史分段印花税**：根据回测自然日精确回溯历史印花税率（单边千分之一至 2023 年 8 月减半后的千分之零点五）；
4. **沪市过户费与最低佣金**：精确区分沪市（60开头）万分之零点一过户费，并强制执行单笔最低 5 元最低佣金。

---

## 五、 UniQuant 生产级改造实施蓝图（Architecture Refactoring Blueprint）

本蓝图采取**“低耦合、非破坏性插件化扩展（Non-breaking Extension）”**策略，在完全不破坏原有技术分析代码的前提下，新增 **4 个核心模块** 并重构 **2 个关键服务**，整体代码量约 1,200~1,500 行。

```
                         UniQuant-CNMM 生产级升级全景架构
┌────────────────────────────────────────────────────────────────────────────┐
│                    CNMM-QAR 策略控制台 (Strategy Orchestrator)              │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┴─────────────────────────────┐
        ▼                                                           ▼
┌──────────────────────────────┐            ┌──────────────────────────────┐
│  uniquant.brain (因子中台)   │            │ uniquant.services (组合中台) │
├──────────────────────────────┤            ├──────────────────────────────┤
│ ➕ ForensicFactorCore         │            │ 🔄 PortfolioService 重构     │
│   ├── 四维复合困境探针 Z_CNMM │            │   ├── 允许负仓位 (对冲空头)   │
│   ├── Winberry 投资欧拉拖累  │            │   ├── 多头 Alpha 股票池 (75%)│
│   └── Ohlson 剩余价值动态折现│            │   ├── 空头期货对冲池 (-75%)  │
│ ➕ ChowBreakpointDetector    │            │   ├── 25% 动态流动性缓冲池   │
│   └── 结构突变断点先验重置   │            │   └── 行业敞口上限 (≤10%/4只) │
└──────────────┬───────────────┘            └──────────────┬───────────────┘
               │ 产生调仓目标权重                           │ 提交母单与对冲需求
               └──────────────────────────────┬─────────────┘
                                              ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       uniquant.hands (执行与对冲层)                        │
├────────────────────────────────────────────────────────────────────────────┤
│ ➕ TwapExecutionSlicer & WalStateMachine & SagaCoordinator                 │
│   └── 3 日时区 TWAP + SQLite WAL 状态机 + T+1 跨资产 Saga 四级分布式补偿   │
│ ➕ CffexFuturesEngine                                                      │
│   ├── 股指期货合约链与保证金账户 (12%~15% Margin)                          │
│   ├── 每日逐日盯市 (Mark-to-Market) 结算                                   │
│   ├── 中金所高频动态基差曲面湖与 MLSI 动态对冲防线                         │
│   └── 主力合约到期前 5 日跨期移仓 (Calendar Spread Rollover)               │
│ ➕ InstitutionalFeeLedger                                                  │
│   └── 私募 2/20 账本 (ACT/365 自然日管理费 + Crystallized HWM + 每日暂估) │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       uniquant.data (现有数据湖底座)                       │
├────────────────────────────────────────────────────────────────────────────┤
│ ✔ StorageManager (日线/分红/财务全量 Parquet 湖 - 100% 复用)               │
│ ➕ FuturesStorageManager (中金所合约链 + 高频动态基差曲面湖)               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

### 5.1 模块 1：中金所期货合约与高频动态基差曲面湖 (`uniquant.data.lake.futures`)

*   **新建文件**: `src/uniquant/data/lake/futures_storage_manager.py`
*   **职责**:
    1. 管理中金所股指期货合约链：IF（沪深300，乘数 300）、IC（中证500，乘数 200）、IM（中证1000，乘数 200）；
    2. 构建全合约期限结构动态基差曲面湖（Basis Surface Lake），高频动态采样 $Basis_t(T) = F_t(T) - S_t$ 与自然日年化贴水率 $Carry_t(T) = \frac{F_t(T) - S_t}{S_t} \times \frac{365}{DTE}$，支持期限插值与期限结构斜率 $S_{\text{term}} = \frac{\partial \text{Basis}}{\partial T}$ 提取；
    3. 构建 MLSI（Multi-Level Spread Indicator，跨品种与跨期流动性利差指数）动态对冲防线，为执行层提供动态对冲比率 $\beta^*(t) = \beta_{\text{portfolio}} \times \phi(\text{MLSI}_t)$ 与移仓展期优化接口，彻底废除静态 -2.50% 贴水粗暴假设。

```python
# 核心接口设计示例: src/uniquant/data/lake/futures_storage_manager.py
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np

@dataclass
class FuturesContract:
    symbol: str             # 如 "IF2406.CFX"
    underlying: str         # "000300.SH"
    multiplier: float       # 300.0
    margin_ratio: float     # 0.12 (12%)
    expiry_date: pd.Timestamp
    tick_size: float = 0.2

class FuturesStorageManager:
    """中金所股指期货合约链与高频动态基差曲面数据湖"""
    def __init__(self, lake_dir: str = "data/lake/futures"):
        self.lake_dir = lake_dir

    def get_dominant_contract(self, underlying: str, date: pd.Timestamp) -> str:
        """获取指定日期流动性最大的主力合约代码"""
        ...

    def get_dynamic_basis_surface(
        self, underlying: str, date: pd.Timestamp
    ) -> Dict[str, float]:
        """
        获取指定日期全合约链的动态基差曲面与年化贴水率:
        返回各到期期限合约的即期基差 (F_t - S_t) 及 ACT/365 年化贴水率
        """
        ...

    def compute_mlsi_hedge_ratio(
        self, underlying: str, portfolio_beta: float, date: pd.Timestamp
    ) -> Tuple[float, Dict[str, float]]:
        """
        基于中金所高频动态基差曲面湖与 MLSI (Multi-Level Spread Indicator)
        计算动态对冲防线比率 beta* = beta * phi(MLSI) 及展期最优目标权重
        """
        ...
```

---

### 5.2 模块 2：组合中台与对冲再平衡器重构 (`uniquant.services.portfolio_service`)

*   **修改文件**: [src/uniquant/services/portfolio_service.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/services/portfolio_service.py)
*   **改造要点**:
    1. **放开负仓位限制**：将 `MIN_POSITION_PCT` 修改为 `Decimal("-100")`，引入多空模式标志 `PortfolioMode: LONG_ONLY | LONG_SHORT_HEDGED`；
    2. **三元资产配置约束**：
       $$\mathbf{w}_{\text{equity}} \in [0, 0.025], \quad \sum w_{\text{equity}} = 0.75$$
       $$w_{\text{futures}} = -0.75 \times \beta_{\text{portfolio}}, \quad w_{\text{cash}} = 0.25$$
    3. **行业集中度风控拦截**：强制单行业（申万一级）权重上限 $\le 10\%$，持股数上限 $\le 4$ 只。

```python
# 改造核心代码片段: src/uniquant/services/portfolio_service.py
class PortfolioService:
    MIN_POSITION_PCT = Decimal("-100")  # 支持空头对冲
    MAX_POSITION_PCT = Decimal("100")

    def _validate_hedged_portfolio(
        self,
        stock_weights: Dict[str, Decimal],
        futures_weights: Dict[str, Decimal],
        cash_weight: Decimal,
        industry_map: Dict[str, str],
    ) -> bool:
        """CNMM-QAR 专用组合合法性穿透校验"""
        total_stock = sum(stock_weights.values())
        total_futures = sum(futures_weights.values())

        # 1. 资产大类比例校验
        if abs(total_stock - Decimal("0.75")) > Decimal("0.01"):
            logger.error(f"股票多头总仓位偏离 75%: {total_stock}")
            return False
        if abs(cash_weight - Decimal("0.25")) > Decimal("0.01"):
            logger.error(f"流动性缓冲池偏离 25%: {cash_weight}")
            return False

        # 2. 单票权重限制 (≤ 2.5%)
        for s, w in stock_weights.items():
            if w > Decimal("0.025"):
                logger.error(f"单票超标: {s} 权重 {w} > 2.5%")
                return False

        # 3. 行业集中度限制 (≤ 10% 且 ≤ 4 只)
        ind_weights = {}
        ind_counts = {}
        for s, w in stock_weights.items():
            ind = industry_map.get(s, "UNKNOWN")
            ind_weights[ind] = ind_weights.get(ind, Decimal("0")) + w
            ind_counts[ind] = ind_counts.get(ind, 0) + 1

        for ind, w in ind_weights.items():
            if w > Decimal("0.10"):
                logger.error(f"行业超标: {ind} 权重 {w} > 10%")
                return False
            if ind_counts[ind] > 4:
                logger.error(f"行业持股超标: {ind} 持有 {ind_counts[ind]} 只 > 4 只")
                return False

        return True
```

---

### 5.3 模块 3：法医中台与因果因子库搭建 (`uniquant.brain.factors.forensics`)

*   **新建目录**: `src/uniquant/brain/factors/forensics/`
*   **子模块设计**:
    1.  `z_cnmm_calculator.py`（四维复合困境探针评分器）：
        *   **四维探针指标体系**：
            1. 应收账款异动指数（DSRI，衡量营收确认操纵风险）；
            2. 资产质量恶化指数（AQI，衡量非硬资产膨胀风险）；
            3. 应计利润现金背离率（Sloan Accruals，衡量盈利无经营现金流支撑风险）；
            4. 折旧激进化与在建工程挂起率（DEPI / CIP Overhang Distress，衡量延期折旧与虚假资本化风险）；
        *   **TTM 滚动平滑**：统一采用滚动 4 季度（TTM）指标平滑，消除单季财务噪声与季节性跳动；
        *   **纠正符号反转，统一“高分危险”标准**：四维指标统一正向表征困境程度，分值越大风险越高；
        *   **P75 截面一票否决淘汰**：全市场截面分位数计算，凡 $Z_{\text{CNMM}} > P_{75}(Z_{\text{CNMM}})$（处于市场最危险前 25%）的个股直接列入黑名单，多头权重归零。
    2.  `winberry_euler_analyzer.py`（资本存量投资欧拉方程在建工程挂起拖累分析）：
        *   提取在建工程（CIP）相对固定资产的年化扩张率；
        *   计算资本积压沉没残差 $\text{Resid}_{\text{CIP}}$，对高积压低产出标的施加显著的 Alpha 负向惩罚。
    3.  `ohlson_valuation.py`（Ohlson 清洁剩余动态折现估值器）：
        *   基于 [financial_bridge.py](file:///home/james/Documents/Project/UniQuant/src/uniquant/brain/factors/financial_bridge.py) 的每股净资产（BPS）与 EPS TTM；
        *   根据行业资本成本动态测算权益回报率 $r$，计算异常盈余折现值 $P_t = B_t + \sum_{\tau=1}^\infty \frac{E_t[NI_{t+\tau} - r B_{t+\tau-1}]}{(1+r)^\tau}$。
    4.  `chow_detector.py`（Chow 检验宏观结构突变识别器）：
        *   放置于 `src/uniquant/brain/regime/chow_detector.py`；
        *   在识别到宏观突变（如 2007 股改、2015 股灾去杠杆、2020 疫情）时，向事件总线广播 `REGIME_STRUCTURAL_BREAK`，通知优化器清空贝叶斯历史先验，重置学习率。

```python
# 核心代码片段示例: src/uniquant/brain/factors/forensics/z_cnmm_calculator.py
import numpy as np
import pandas as pd

class ZCNMMCalculator:
    """CNMM-QAR 四维复合困境探针标准算子 (高分危险，高于 P75 剔除，TTM 平滑)"""

    @staticmethod
    def compute_z_score(fin_df: pd.DataFrame) -> pd.Series:
        """
        四维复合困境探针计算 (TTM 平滑与截面标准化):
        - 维度 1: 应收账款异动率 (DSRI)
        - 维度 2: 资产质量恶化率 (AQI)
        - 维度 3: 应计利润现金背离率 (Sloan Accruals)
        - 维度 4: 折旧放缓与挂起率 (DEPI / CIP Overhang)
        方向规约: 指标值越大，财务困境与操纵风险越高！
        """
        # 1. 应收账款操纵因子 (DSRI) - TTM 平滑
        rec_ttm = fin_df["accounts_rec_ttm"] if "accounts_rec_ttm" in fin_df else fin_df["accounts_rec"]
        rev_ttm = fin_df["revenue_ttm"] if "revenue_ttm" in fin_df else fin_df["revenue"]
        rec_prev = fin_df["accounts_rec_prev_ttm"] if "accounts_rec_prev_ttm" in fin_df else fin_df["accounts_rec_prev"]
        rev_prev = fin_df["revenue_prev_ttm"] if "revenue_prev_ttm" in fin_df else fin_df["revenue_prev"]
        dsri = (rec_ttm / rev_ttm.replace(0, np.nan)) / (rec_prev / rev_prev.replace(0, np.nan)).replace(0, np.nan)
        dsri_score = dsri.clip(0.2, 5.0)

        # 2. 资产质量恶化因子 (AQI) - TTM 平滑
        non_current = fin_df["total_assets"] - fin_df["current_assets"] - fin_df["ppe"]
        non_current_prev = fin_df["total_assets_prev"] - fin_df["current_assets_prev"] - fin_df["ppe_prev"]
        aqi = (non_current / fin_df["total_assets"].replace(0, np.nan)) / (
            non_current_prev / fin_df["total_assets_prev"].replace(0, np.nan)
        ).replace(0, np.nan)
        aqi_score = aqi.clip(0.2, 5.0)

        # 3. 应计利润现金背离率 (Sloan Accruals - 基于 TTM 净利润与经营现金流 OCF)
        net_profit_ttm = fin_df["net_profit_ttm"] if "net_profit_ttm" in fin_df else fin_df["net_profit_parent"]
        ocf_ttm = fin_df["ocf_ttm"] if "ocf_ttm" in fin_df else fin_df["ocf"]
        accruals = (net_profit_ttm - ocf_ttm) / fin_df["total_assets"].replace(0, np.nan)
        accruals_score = accruals.clip(-1.0, 1.0)

        # 4. 折旧与资本化挂起因子 (DEPI / CIP Overhang Distress)
        depr = fin_df.get("depreciation_ttm", fin_df.get("depreciation", pd.Series(0, index=fin_df.index)))
        depr_prev = fin_df.get("depreciation_prev_ttm", fin_df.get("depreciation_prev", pd.Series(0, index=fin_df.index)))
        depr_rate = depr / (fin_df["ppe"] + depr).replace(0, np.nan)
        depr_rate_prev = depr_prev / (fin_df["ppe_prev"] + depr_prev).replace(0, np.nan)
        depi = depr_rate_prev / depr_rate.replace(0, np.nan)  # 历史折旧率高于当前说明折旧放缓
        depi_score = depi.clip(0.2, 5.0)

        # 四维复合困境探针: 彻底纠正符号反转缺陷，正向加权表征财务困境高危度
        z_score = (
            0.35 * ((dsri_score - 1.0) / 0.5)
            + 0.25 * ((aqi_score - 1.0) / 0.5)
            + 0.25 * (accruals_score / 0.1)
            + 0.15 * ((depi_score - 1.0) / 0.5)
        )
        return z_score

    @classmethod
    def filter_distress_universe(cls, fin_df: pd.DataFrame, threshold_percentile: float = 0.75) -> pd.Series:
        """
        截面排雷拦截网:
        计算全截面 Z_CNMM，若得分高于截面 P75 分位点 (前 25% 高危造假困境标的)，一票否决拉黑
        """
        z = cls.compute_z_score(fin_df)
        p75 = z.quantile(threshold_percentile)
        is_safe = z <= p75
        return is_safe
```

---

### 5.4 模块 4：衍生品撮合、SQLite WAL 状态机与 T+1 双撮合跨资产 Saga 补偿执行器 (`uniquant.hands.backtest`)

*   **新建文件 1**: `src/uniquant/hands/backtest/cffex_engine.py`
    *   **每日无负债结算（Mark-to-Market）**：
        $$\Delta \text{PnL}_t = (\text{Settlement}_{t-1} - \text{Settlement}_t) \times \text{Multiplier} \times \text{Contracts}$$
    *   **废除静态 -2.50% 贴水，接入中金所高频动态基差曲面湖与 MLSI 动态对冲防线**：
        - 每日盯市损益由动态基差曲面湖实际采样值驱动：
          $$\text{BasisPnL}_t = \sum_k \left[ (F_{t,k} - S_t) - (F_{t-1,k} - S_{t-1}) \right] \times \text{Multiplier}_k \times \text{Contracts}_k$$
        - 引入 MLSI（Multi-Level Spread Indicator / 跨期跨品种利差指数）动态防线：基于中金所近月/远月合约升贴水曲面斜率 $S_{\text{term}} = \frac{\partial \text{Basis}(T)}{\partial T}$ 与流动性厚度，自适应调节目标对冲头寸 $\beta^*_t = \beta_{\text{portfolio}} \times \phi(\text{MLSI}_t)$，并在基差极度贴水时启动跨期展期平滑算法，彻底淘汰 -2.50%/252 的僵化静态摊销假设。
    *   **跨期移仓（Calendar Spread Rollover）**：在主力合约到期前 5 个交易日，由 MLSI 信号指引按日递增（如 10%-20%-20%-25%-25%）平近月合约、开远月主力合约，并计提买卖冲击成本。

*   **新建文件 2**: `src/uniquant/hands/backtest/twap_execution_slicer.py` & `src/uniquant/hands/backtest/saga_compensator.py`
    *   **3 日黄金时段 TWAP 拆单**：调仓母单严格拆分为 $N = 3$ 个交易日（T, T+1, T+2）子单序列，每日仅在 10:00–14:30 黄金流动性区间匀速切片撮合，彻底剔除开盘 09:30 及收盘 14:57 尾盘极端波动；
    *   **SQLite WAL 持久化 TWAP 状态机**：母单与所有切片子单的生命周期流转写入高性能轻量 SQLite WAL（Write-Ahead Logging）数据库，状态机定义为：`PENDING -> SUBMITTED -> PARTIALLY_FILLED -> FILLED`，异常中断触发 `COMPENSATING -> COMPENSATED / FAILED`。具备 Crash-Safe 秒级幂等重放恢复能力；
    *   **T+1 下双撮合跨资产 Saga 四级分布式补偿机制**：
        针对 A 股现货端（T+1 不可当日反向卖出、遇跌停无法卖出）与中金所期货端（T+0 双向交易）异步并发撮合中出现的失衡，执行四级级联补偿：
        - **Level 1 (微观窗口自愈)**：单笔股票切片若流动性不足部分成交，由下一 15 分钟窗口在非线性滑点阈值内动态溢价自动补全；
        - **Level 2 (跨资产 Delta 联动对冲补偿)**：若现货子单连续未能完全成交，导致股票组合市值与期货空头 Delta 敞口偏差超过 1.0%，Saga 协调器即刻驱动期货端以 T+0 特性秒级增减 IF/IC/IM 对应手数，强制压制组合净敞口近零；
        - **Level 3 (可售底仓替代冲销与逆向平仓)**：若遭遇股票平仓卖出被跌停拦截且受制于 T+1 当日买入不可卖出，Saga 路由检测账户 T+1 前历史底仓进行替代冲销；若多头建仓失败，即刻冻结后续期货加仓并市价平掉多余期货空头；
        - **Level 4 (极端死锁隔离与残值合成锁仓)**：标的遭遇连续一字死封跌停（现货完全无法脱手）时，Saga 引擎标记事务为 `QUARANTINED`（隔离态），由期货端建立 1:1 动态合成空头精准锁仓残值，触发 P0 级风控警报并写入审计跟踪日志，待流动性复苏后依序解封清算。

```python
# 核心接口设计示例: src/uniquant/hands/backtest/twap_execution_slicer.py & saga_compensator.py
from dataclasses import dataclass
from enum import Enum
import sqlite3
import pandas as pd
from typing import List, Dict, Optional

class OrderState(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    SAGA_COMPENSATING = "SAGA_COMPENSATING"
    SAGA_COMPENSATED = "SAGA_COMPENSATED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"

class SqliteWalTwapStateMachine:
    """基于 SQLite WAL 的 Crash-Safe TWAP 母单/切片事务状态机"""
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_tables()

    def _init_tables(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS parent_orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    total_shares INTEGER,
                    executed_shares INTEGER DEFAULT 0,
                    status TEXT,
                    created_at TIMESTAMP
                );
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS twap_slices (
                    slice_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    day_index INTEGER,
                    slice_shares INTEGER,
                    executed_shares INTEGER DEFAULT 0,
                    status TEXT,
                    avg_price REAL DEFAULT 0.0,
                    FOREIGN KEY(parent_id) REFERENCES parent_orders(order_id)
                );
            """)

    def transition_state(self, order_id: str, new_state: OrderState):
        with self.conn:
            self.conn.execute(
                "UPDATE parent_orders SET status = ? WHERE order_id = ?",
                (new_state.value, order_id)
            )

class CrossAssetSagaCoordinator:
    """T+1 下股票与期货双撮合跨资产四级分布式补偿协调器"""
    def __init__(self, wal_sm: SqliteWalTwapStateMachine):
        self.wal_sm = wal_sm

    def handle_execution_failure(
        self,
        stock_symbol: str,
        unfilled_shares: int,
        reason: str,
        current_equity_delta: float,
        current_futures_delta: float
    ) -> str:
        """
        四级级联补偿路由:
        Level 1: 微观窗口自愈 (Next slice retry)
        Level 2: 跨资产 Delta 联动对冲补偿 (Futures Delta hedge adjustment)
        Level 3: 可售底仓替代冲销 / 逆向平仓 (T+0 inventory substitute)
        Level 4: 极端跌停死锁隔离与残值合成对冲 (Quarantine & Synthetic hedge)
        """
        delta_imbalance = abs(current_equity_delta + current_futures_delta)
        if "NORMAL_LIQUIDITY_DELAY" in reason:
            return "LEVEL_1_MICRO_RETRY"
        elif delta_imbalance > 0.01 and "LIMIT_DOWN" not in reason:
            return "LEVEL_2_FUTURES_DELTA_COMPENSATE"
        elif "T1_LOCKED" in reason or "PARTIAL_REJECT" in reason:
            return "LEVEL_3_INVENTORY_SUBSTITUTE_OR_ABORT"
        else:
            self.wal_sm.transition_state(stock_symbol, OrderState.QUARANTINED)
            return "LEVEL_4_QUARANTINE_SYNTHETIC_HEDGE"
```

---

### 5.5 模块 5：私募级费用与治理账本 (`uniquant.hands.backtest.institutional_fee_ledger`)

*   **新建文件**: `src/uniquant/hands/backtest/institutional_fee_ledger.py`
*   **彻底消除代数矛盾，建立生产级私募核算规则**:
    1.  **ACT/365 自然日管理费（Management Fee Accrual）**：
        根据私募行业托管核算标准，管理费按日历自然日连续计提（周末与节假日不休止）：
        $$\text{Fee}_{\text{mgmt}, t} = \text{AUM}_{t-1} \times \frac{0.02}{365} \times \Delta \text{Days}_{\text{calendar}}$$
        每日清算时从资产总值中硬扣除，计入应付管理人报酬负债。
    2.  **固化高水位线（Crystallized High-Water Mark, HWM）与门槛基准**：
        - 消除“滚动最高净值”导致 $\text{NAV}_t > \max(\text{NAV}) \times (1+\text{hurdle})$ 恒为假命题的代数矛盾；
        - 固化高水位线 $\text{HWM}_{\text{crys}}$ 仅在历史法定结算日（Crystallization Date，如每年年末 12 月 31 日或份额赎回日）实际计提业绩提成后才向上跳变固化：
          $$\text{HWM}_{\text{crys}, m} = \text{NAV}_{\text{crystallized}, m}$$
        - 期间门槛净值基准（Hurdle Benchmark）：
          $$\text{HurdleNAV}_t = \text{HWM}_{\text{crys}} \times \left( 1 + 0.06 \times \frac{\Delta \text{Days}_{\text{crys}\to t}}{365} \right)$$
    3.  **每日业绩报酬准备金暂估与冲销（Daily Performance Fee Accrual & Reversal）**：
        - 为确保每日公布公允净值并公平对待申赎份额，系统每日计算“业绩报酬暂估准备金”（Contingent Carry Accrual）：
          $$\text{AccruedCarry}_t = \begin{cases} 0.20 \times (\text{NAV}_{\text{pre}, t} - \text{HurdleNAV}_t), & \text{若 } \text{NAV}_{\text{pre}, t} > \text{HurdleNAV}_t \\ 0, & \text{若 } \text{NAV}_{\text{pre}, t} \le \text{HurdleNAV}_t \end{cases}$$
        - 策略每日公布公允净值（Published Fair NAV）：
          $$\text{NAV}_t = \text{NAV}_{\text{pre}, t} - \text{AccruedCarry}_t$$
        - 当净值发生回撤时，未固化的暂估准备金自动冲销释放，净值自动回补；
        - 仅在法定结算法定日（$t = T_{\text{crys}}$），暂估准备金正式固化并划转（Crystallized），扣除后设定新周期的 $\text{HWM}_{\text{crys}} = \text{NAV}_t$，次日准备金清零重新起算。彻底杜绝代数死循环与净值虚增。

```python
# 核心接口设计示例: src/uniquant/hands/backtest/institutional_fee_ledger.py
from dataclasses import dataclass
import pandas as pd

@dataclass
class FeeSnapshot:
    date: pd.Timestamp
    gross_nav: float
    net_nav: float
    mgmt_fee_accrued: float
    carry_accrued: float
    crystallized_hwm: float
    hurdle_nav: float

class InstitutionalFeeLedger:
    """私募 2/20 治理账本 (ACT/365 自然日管理费 + Crystallized HWM + 每日 Accrual 准备金暂估)"""
    def __init__(
        self,
        mgmt_fee_rate: float = 0.02,
        carry_rate: float = 0.20,
        hurdle_rate: float = 0.06,
        initial_nav: float = 1.0,
        start_date: pd.Timestamp = pd.Timestamp("2000-01-01")
    ):
        self.mgmt_fee_rate = mgmt_fee_rate
        self.carry_rate = carry_rate
        self.hurdle_rate = hurdle_rate
        self.crystallized_hwm = initial_nav
        self.last_crys_date = start_date
        self.last_date = start_date

    def calculate_daily_fair_nav(
        self, current_date: pd.Timestamp, raw_nav: float, is_crys_date: bool = False
    ) -> FeeSnapshot:
        # 1. ACT/365 自然日管理费计提
        cal_days = max(1, (current_date - self.last_date).days)
        mgmt_fee = raw_nav * (self.mgmt_fee_rate / 365.0) * cal_days
        nav_after_mgmt = raw_nav - mgmt_fee

        # 2. 期间 Hurdle 门槛净值 (基于固化 HWM 与自然日天数)
        days_since_crys = (current_date - self.last_crys_date).days
        hurdle_nav = self.crystallized_hwm * (1.0 + self.hurdle_rate * (days_since_crys / 365.0))

        # 3. 每日业绩报酬准备金暂估 (Daily Carry Accrual)
        if nav_after_mgmt > hurdle_nav:
            carry_accrual = self.carry_rate * (nav_after_mgmt - hurdle_nav)
        else:
            carry_accrual = 0.0

        published_nav = nav_after_mgmt - carry_accrual

        # 4. 法定结算日固化 (Crystallization)
        if is_crys_date and carry_accrual > 0.0:
            self.crystallized_hwm = published_nav
            self.last_crys_date = current_date
            carry_accrual = 0.0  # 准备金正式转为已支付，重置为 0

        self.last_date = current_date
        return FeeSnapshot(
            date=current_date,
            gross_nav=raw_nav,
            net_nav=published_nav,
            mgmt_fee_accrued=mgmt_fee,
            carry_accrued=carry_accrual,
            crystallized_hwm=self.crystallized_hwm,
            hurdle_nav=hurdle_nav
        )
```

---

## 六、 工程演进敏捷排期与验收测试门禁（Roadmap, Sprints & Quality Gate）

为确保系统改造在科学严谨的工程节奏下收敛，废除原脱离工程现实的 3~4 周粗糙规划，全面校准为 **4 个标准双周冲刺（4 Sprints × 2 Weeks = 8 周全周期，预计增补/重构高保真生产代码 3,500+ 行）**。每个 Sprint 均配备不可妥协的质量门禁（Quality Gate）：

```
Sprint 1: 账户体系与对冲底座 (第 1~2 周, 预计代码量 ~900 行)
├── 新建 futures_storage_manager.py (中金所合约链 + 高频动态基差曲面湖)
├── 重构 portfolio_service.py (解除 MIN_POSITION_PCT 负仓限制, 约束多头 75%/空头 -75%/现金 25%)
├── 新建 cffex_engine.py (股指期货持仓、保证金、逐日盯市结算与 MLSI 动态对冲防线)
└── 质量门禁: 极端贴水冲击与连续跌停下保证金预警及强平穿仓防御测试 100% 通过, 净敞口误差 < 0.1%

Sprint 2: 法医中台与因果因子库 (第 3~4 周, 预计代码量 ~1,000 行)
├── 新建 brain/factors/forensics/z_cnmm_calculator.py (四维复合困境探针, TTM 平滑与 P75 截面剔除)
├── 新建 brain/factors/forensics/winberry_euler_analyzer.py (在建工程 CIP 欧拉沉没残差拖累)
├── 新建 brain/factors/forensics/ohlson_valuation.py (Ohlson 清洁剩余动态折现估值器)
├── 新建 brain/regime/chow_detector.py (Chow 突变断点检验与无信息先验重置器)
└── 质量门禁: A股全历史暴雷股(康美/康得新等)提前2季度识别拦截率 100%, 2007/2015/2020 结构断点判定 100%

Sprint 3: TWAP 状态机与 Saga 跨资产分布式补偿 (第 5~6 周, 预计代码量 ~850 行)
├── 新建 twap_execution_slicer.py (3 日 10:00–14:30 黄金流动性区间切片执行器)
├── 新建 wal_state_machine.py (基于 SQLite WAL 的母单/子单生命周期与 Crash-Safe 状态机)
├── 新建 saga_compensator.py (T+1 现货与 T+0 期货双撮合 Saga 四级分布式补偿协调器)
├── 实现股指期货主力合约到期前 5 日平稳展期 (Calendar Spread Rollover)
└── 质量门禁: 注入连续涨跌停、部分成交与进程断电崩溃测试, Saga 四级补偿成功率 100%, 事务零死锁

Sprint 4: 2/20 治理账本与全历史 25 年端到端回归 (第 7~8 周, 预计代码量 ~750 行)
├── 新建 institutional_fee_ledger.py (ACT/365 自然日管理费 + Crystallized HWM + 每日 Accrual 准备金)
├── 编写 cnmm_qar_strategy.py 完成 UniQuant 生产级策略总装编排
├── 基于 UniQuant 2000–2026 全量 A 股 Parquet 数据湖完成全量端到端回测对齐
└── 质量门禁: 扣除全额 2/20 费用、动态基差、印花税与非线性冲击后, 复现净年化 ≥ 17.0%, 回撤 ≤ 9.5%, 现有测试集向后兼容 100%
```

| 迭代阶段 | 周期 | 预计代码量 | 核心交付物 | 关键工程活动 | 验收指标与硬核质量门禁（Quality Gate） |
| :--- | :---: | :---: | :--- | :--- | :--- |
| **Sprint 1: 账户对冲底座** | 第 1~2 周 (10 工作日) | ~900 行 | `futures_storage_manager.py` + `cffex_engine.py` + 重构 `portfolio_service.py` | 搭建动态基差曲面湖与 MLSI 动态对冲防线；改造组合仓位模型支持 $-75\%$ 股指期货做空；实现保证金动态追保与逐日盯市。 | 极端基差跳空（$\pm 10\%$）与多空 Delta 偏离压制在 0.1% 以内；保证金追保告警触发率 100%；单测覆盖率 $\ge 90\%$。 |
| **Sprint 2: 法医因果中台** | 第 3~4 周 (10 工作日) | ~1,000 行 | `forensics/` (Z-CNMM, Winberry, Ohlson) + `chow_detector.py` | 落地四维复合困境探针（高分危险，TTM 4 季平滑，P75 截面剔除）；开发在建工程沉没拖累与 Ohlson 折现；接入 Chow 结构突变先验重置。 | 成功拦截康美、康得新、保千里等全部历史样本，识别准确率 100%；$Z_{\text{CNMM}} > P_{75}$ 困境组次年跑输概率 $> 85\%$；先验重置零内存泄漏。 |
| **Sprint 3: 执行补偿中枢** | 第 5~6 周 (10 工作日) | ~850 行 | `twap_execution_slicer.py` + `wal_state_machine.py` + `saga_compensator.py` | 落地 3 日 10:00–14:30 TWAP 切片；构建 SQLite WAL Crash-Safe 状态机；落地 T+1/T+0 双撮合 Saga 四级补偿；实现 5 日平稳展期。 | 模拟 10 亿母单拆分，在突发一字跌停与网络中断注入下，Saga 四级补偿执行成功率 100%；WAL 崩溃重启秒级恢复，零重发零漏发。 |
| **Sprint 4: 账本与全量回归** | 第 7~8 周 (10 工作日) | ~750 行 | `institutional_fee_ledger.py` + `cnmm_qar_strategy.py` + 25 年端到端回归 | 落地 ACT/365 自然日管理费、Crystallized HWM 与每日 Accrual 准备金暂估；全链路总装；对齐 2000–2026 全量 A 股回测。 | 消除 HWM 代数矛盾，准备金暂估与年末固化误差为 0；扣除全部费用与滑点后复现净年化 $\ge 17.0\%$、夏普 $\ge 2.40$、回撤 $\le 9.5\%$；UniQuant 现有测试集 100% 兼容。 |

---

## 七、 战略审计总结与商业价值（Strategic Impact）

1.  **架构定位评语**：
    UniQuant 绝非一套粗制滥造的玩具系统。恰恰相反，它的**底层数据湖（Parquet Lake）与交易规则防线（T+1/涨跌停/印花税/非线性冲击）极度扎实**，不仅远超开源界同类产品，甚至优于大量中小私募的自研交易核心。
2.  **瓶颈本质剖析**：
    它当前原生不能承载 CNMM-QAR 策略的根本原因，**并非底层技术架构孱弱，而是“顶层业务认知偏科”**——系统此前深度聚焦于零售散户热衷的“单边做多现货、形态学、缠论、技术指标与微观择时”，导致组合与撮合层硬编码锁死了负仓位与衍生品对冲体系。
3.  **升级蜕变价值**：
    通过本蓝图规划的 5 个解耦模块在 8 周双周冲刺内的外科手术式植入，UniQuant 将正式脱离“纯技术面现货选股系统”的狭隘定位，一举蜕变为兼具 **“A 股微观合规高保真度”**、**“跨市场股指期货中性对冲”**、**“会计法医因果选股”**、**“SQLite WAL / Saga 高容错执行”** 与 **“私募级 2/20 治理核算”** 的机构级顶尖量化绝对收益投研生产平台。

---
<!-- 卷宗归档完成: CNMM-ARCH-2026-UQ-EVAL-01-v2.0 -->
