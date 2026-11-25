# 风控合规模块 N2N 深度分析 — 独立子代理验证报告

> **报告类型**：独立代码审查子代理（subagent）验证，与既有 Claude 报告（基线 `434aab1`）做交叉复核
> **审查基线**：`b1d2415`（风险源码与 `434aab1` 逐字节一致，`git diff 434aab1 b1d2415 -- src/uniquant/risk/ ...` 为空 → 交叉复核为同基线对照）
> **审查日期**：2026-11-24
> **分析范围**：`src/uniquant/risk/`（5 文件, 1,655 行）+ `src/uniquant/shared/kill_switch.py` + `state_store.py`
> **方法**：先独立分析（未读既有报告前完成源码追踪），后读 `docs/analysis/n2n/05_risk_compliance_n2n.md` 做逐条交叉标注

---

## ① 执行摘要

风控合规模块在**设计形态**上是诚实且认真的：`PreTradeComplianceEngine` 是事前硬门禁 + 二值判定 + SHA-256 防篡改签证；`SharedKillSwitch` 的 `kill()`→磁盘持久化→重启恢复停机态路径正确；VaR/CVaR 明确标注"NOT true EVT"未冒充实务术语；T+1 惩罚系数 CN:1.2 方向正确。

但独立追踪暴露出**两个真实缺口**，均属"风控放水"性质，且既有报告与第三方评审都未完整覆盖：

1. **`PreTradeComplianceEngine` 的 Gross Leverage 公式是错的**（`compliance_engine.py:234`）。`gross_leverage = (long + short + cash) / aum`，而 `cash = aum - long`，代回得 `gross_leverage = 1 + short_weight`——**完全不含 long 项**。实测：long=150%/short=50% 时，真实 gross=200% 应触发，代码却算得 150% **漏报**（fail-open）；long=75%/short=75% 的规范三元，真实 gross=150%，代码却报 175%。"175% 总杠杆"防线实际只约束了空头侧（`1+short≤1.76` ⇒ `short≤76%`），多头侧毫无约束。
2. **`ComplianceEngine` 没有接入回测/实盘执行主链路**。`audit()` 仅在 `manifest_generator.py:297`（清单导出路径）被调用，`unified_engine.py` / `arbitrator.py` / `research_pipeline.py` 均不引用合规引擎。7 大防线对实际产生的信号/持仓**不生效**。

另外确认两个既有报告**未捕获**的 fail-open 路径：
- `SharedKillSwitch` 在**状态存储读取失败**时 `except Exception` 后静默继续，`_killed=False` → **Fail-Open**（`kill_switch.py:55-56`）。实测：损坏 `kill_switch.json` 后重启，`is_killed=False`。与文档声称的 "T9a Fail-Closed" 相悖——Fail-Closed 只在读成功且 `killed=True` 时成立，恰恰在最需要保护的重启恢复场景（磁盘损坏/半写）失效。
- `EVTRisk.calculate_metrics` 空输入返回**伪造的默认指标**（`_get_default_metrics()`：var_95=0.02 等，`evt_risk.py:286-299`），且 `calculate_var/cvar/max_drawdown` 各自 `except` 后返回阈值常量（0.05/0.06/0.2）。Rule 4 要求"缺失输入必须显式失败"，此处改为静默返回貌似合理的数据。实测空输入返回 `var_95=0.05, regime=NORMAL, ntf_signal=中性`。

**健康度评级：B（有条件可用）**。设计良好、参数可配置、签名与持久化路径正确；但 Gross Leverage 公式错误 + 合规引擎未接入执行链路 + 两处 fail-open，构成部署前必须修复的 P0/P1 类问题。

---

## ② 五问逐节点答案

### Q1 定义（Name 定义 / 契约）

| 节点 | 定义 | 证据 |
|---|---|---|
| `PositionSizer` | `initial_capital=100k, risk_pct=0.05, kelly_fraction=None`；T+1 惩罚 `{CN:1.2, US:1.0, HK:1.0}` | `sizer.py:79-84` |
| `InvalidStopLossError` | stop ≥ price 时抛出（fail-fast 正确） | `sizer.py:65-70, 156-158` |
| `HistoricalSimulationRisk` | 历史百分位法；**明确标注非真 EVT** | `evt_risk.py:24-33, 131-149` |
| `PortfolioOptimizer` | Ledoit-Wolf 收缩 + 风险平价/均值-方差 | `portfolio_optimizer.py:20-93` |
| `PreTradeComplianceEngine` | 8 个构造参数全部可配置（含舍入裕度） | `compliance_engine.py:88-107` |
| `ComplianceReport` | verdict 二值 + manifest_hash + breaches | `compliance_engine.py:59-82` |
| `SharedKillSwitch` | 单例 + DiskStateStore 持久化 + hooks | `kill_switch.py:17-58` |

### Q2 映射（数据流映射）

- 信号→仓位：`SignalArbitrator.arbitrate_candidates()` 在 non-FSM BUY 时调 `sizer.calculate_shares`（`arbitrator.py:396-406`）；FSM BUY 在 `fsm.py:429-438` 调 sizer（传 `ctx.atr_stop` + `ctx.czsc_bottom`——**唯一真正传几何止损的路径**）。
- 仓位→执行：`unified_engine.py:354-368` 调 sizer 但**写死** `stop_loss=closes*0.95, czsc_bottom=None`（几何止损在回测中被旁路）。
- 风控指标：`RiskMetrics`（VaR/CVaR/MaxDrawdown）由 `HistoricalSimulationRisk.calculate_metrics` 产出，供 `fsm.py:420-427` 的 `risk_scaler` 与 `health_service.py:14`。
- 合规签证：`manifest_generator.py:297-303` → `PreTradeComplianceEngine.audit()` → `ComplianceReport`（导出清单路径）。
- 熔断：`cffex_engine.py:482-486`（margin call）与 `institutional_execution_orchestrator.py:359`（saga 前 `check()`）触发 kill。

### Q3 传播（依赖链）

```
BacktestResult / LivePosition
→ SignalArbitrator (arbitrator.py:396) / FSM (fsm.py:429) / UnifiedEngine (unified_engine.py:356)
→ PositionSizer.calculate_shares → target_shares（+几何止损 = max(ATR, CZSC_bottom)，sizer.py:150-152）
→ EVTRisk.calculate_metrics → VaR/CVaR/MaxDrawdown/regime → FSM risk_scaler (fsm.py:420-427)
→ PreTradeComplianceEngine.audit → ComplianceResult（仅清单导出，manifest_generator.py:297）
→ SharedKillSwitch.kill → DiskStateStore.put → 重启恢复（kill_switch.py:45-58）
→ arbitrator.py:117 / cffex_engine.py:482 检查 is_killed / margin call → 丢弃信号 / 停机
```

### Q4 变异（边界与异常）

- 止损 ≥ 入场价 → `InvalidStopLossError`（fail-fast，正确）`sizer.py:156-158`。
- 仓位超本金 → 本金熔断截断（`sizer.py:182-187`），但**只截断到 100% 本金 = 单票满仓**，无单仓权重上限（见问题 F）。
- sizer 调用异常 → 调用方 `except: shares=100`（fail-open，`arbitrator.py:404-406` / `unified_engine.py:367-368`）。
- AUM≤0 → `ValueError`（fail-fast，正确）`compliance_engine.py:128-129`。
- 状态存储读失败 → `except Exception` 后 `_killed=False`（fail-open，`kill_switch.py:55-56`）。

### Q5 治理（可观测 / 可测试）

- `ComplianceMetrics` 16 字段 + `evaluated_at` UTC 时间戳（`compliance_engine.py:35-56`）。
- SHA-256 确定性签名 `sort_keys=True`（`compliance_engine.py:282-291`）。
- sizer 返回 13 字段详细字典（`sizer.py:189-203`）。
- 测试：`tests/test_sizer.py`、`tests/test_manifest_generator.py`、`tests/test_evt_risk.py`、`tests/shared/test_persistent_kill_switch.py`、`tests/test_production_kill_switch.py` 均存在且覆盖 kill 持久化与合规判定。

---

## ③ 端到端路径追踪（≥3 条，含异常）

### 路径 1（正常）：信号→仓位→回测
```
FSM BUY (fsm.py:429) → sizer.calculate_shares(price, atr_stop, czsc_bottom=ctx.czsc_bottom, market=CN)
  → final_stop = max(ATR_stop, CZSC_bottom) (sizer.py:150-152)
  → risk_per_share = price - final_stop (sizer.py:155)
  → penalty = 1.2 (CN T+1) → shares = max_loss / (risk_per_share × 1.2) (sizer.py:167)
  → floor to lot → suggested_shares (sizer.py:171-172)
→ 返回 13 字段 dict → FSM final_shares = 建议仓位 × risk_scaler (fsm.py:439)
```
**观察**：几何止损取 max（更靠近入场价）→ 每股风险更小 → **仓位反而更大**。"最保守"标签（`sizer.py:149`）对多头是**方向反转**——取更高的止损确实让单笔风险敞口（风险敞口=risk×penalty）变小，但股数放大。这是语义而非安全缺陷（总风险仍受 `max_loss_allowed` 帽），但标签具误导性（问题 I）。

### 路径 2（异常：仓位超限→合规拒绝）
```
单票 5% AUM 订单 → audit() (compliance_engine.py:170-174)
  → weight=0.05 > max_single_stock_weight+1e-6 (0.025) → breaches.append("单票持仓集中度超限")
  → verdict=REJECTED_BREACH, passed=False (compliance_engine.py:278-279)
  → manifest_hash=SHA-256(...) (compliance_engine.py:289-291)
```
**观察**：判定正确；但此路径仅在 `manifest_generator.py:297` 被调用，**不回测、不实盘、不信号仲裁**（问题 B）。

### 路径 3（异常：KillSwitch 触发 + 重启恢复）
```
cffex_engine.py:482-486  margin_ratio>115% 或 cash<=0 → kill_switch.kill("CFFEX_CRITICAL_MARGIN_DEPLETION...")
  → _killed=True, _reason=... → DiskStateStore.put("kill_switch", {killed:True,...}) (kill_switch.py:68-82)
→ 进程重启 → __init__ 读 state_store.get("kill_switch") → saved.killed=True → _killed=True (kill_switch.py:46-54)
→ arbitrator.py:117 get_kill_switch().is_killed → True → 全部信号丢弃 (arbitrator.py:117-119)
→ 手工 reset() → delete 持久化 (kill_switch.py:90-97)
```
**观察**：Happy path 正确（测试 `test_persistent_kill_switch.py:11-45` 验证重启继承停机态）。**但状态存储读失败时 fail-open**（问题 C）。

### 路径 4（异常：合规引擎未接入 → 单票满仓无兜底）
```
unified_engine.py:354-368  sizer.calculate_shares(stop_loss=closes*0.95, czsc_bottom=None)
  → 返回建议仓位（无单仓权重上限，sizer.py 无 max_single 约束）
  → 若仓位超本金 → 熔断截断到 100% 本金 (sizer.py:182-187) = 单票满仓
  → 无合规引擎 / 无 2.5% 单票上限在此路径生效
```
**观察**：7 大防线（含单票≤2.5%）**对回测/实盘持仓不生效**——唯一压住它的是另一个未接入的模块（问题 B + F）。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### HIGH

#### H1：Gross Leverage 公式错误（漏报多头侧杠杆）
- **证据**：`compliance_engine.py:230` `cash_buffer_cny = aum_cny - total_long_cny`；`:234` `gross_leverage = (total_long_cny + total_short_cny + cash_buffer_cny) / aum_cny`。代回得 `gross_leverage = 1 + short_weight`，**不含 long**。
- **实测**：long=75%/short=75% → 代码 gross=175%，真实 |L|+|S|=150%；long=150%/short=50% → 代码 gross=150%（**漏报**，真实 200% 应触发 175% 上限）。
- **影响**："175% 总杠杆"防线实际只等价于 `short_weight ≤ 76%`，多头侧无杠杆约束。属风控 fail-open。
- **修复**：改为 `gross_leverage = (abs(total_long_cny) + abs(total_short_cny)) / aum_cny`；补充多头杠杆测试（long=150%/short=50% 必须 breach）。

#### H2：ComplianceEngine 未接入执行主链路（7 大防线不生效）
- **证据**：`audit()` 仅在 `manifest_generator.py:297`（清单导出）调用；`unified_engine.py`、`arbitrator.py`、`research_pipeline.py`、`service_container.py` 均无 `PreTradeComplianceEngine`/`audit` 引用（`grep` 全库确认）。
- **影响**：合规引擎再优秀，回测与信号仲裁生成的持仓未经 2.5% 单票 / 10% 行业 / 175% 杠杆 / ±0.5% 净敞口任何一道防线。sizer 的单票满仓（路径 4）无兜底。
- **修复**：在 `unified_engine.run()` 每个交易日对生成持仓调用 `audit()`；或将合规引擎注入 `research_pipeline` 作为持仓后置门禁；补一条"合规引擎在回测路径被调用"的集成测试。

#### H3：sizer 调用失败 fail-open 到固定 100 股
- **证据**：`arbitrator.py:404-406` `except Exception: sized_shares = 100`；`unified_engine.py:367-368` `except (...): shares = 100`。
- **影响**：仓位计算失败（含 `InvalidStopLossError`）时**不是拒绝开仓而是硬编码开 1 手**。风控计算挂了仍会下单。实盘危险逻辑。
- **修复**：改为 fail-closed——失败时拒绝该标的（`HOLD`/跳过），而非开 100 股；或至少区分 `InvalidStopLossError`（应拒绝）与可恢复异常。

#### H4：KillSwitch 状态存储读取失败时 Fail-Open
- **证据**：`kill_switch.py:55-56` `except Exception: logger.error(...)` 后**未置 killed**，`_killed=False`。
- **实测**：写入损坏 JSON 后重启 → `is_killed=False`。
- **影响**：与文档"T9a Fail-Closed 保护"（`kill_switch.py:52`）相悖。最需要保护的**崩溃恢复**场景（磁盘半写/损坏）反而静默放行。这是 Fail-Closed 声称的**反例**。
- **修复**：读失败时默认 `_killed=True`（Fail-Closed 语义），记录并保留原始状态；补损坏存储重启测试。

### MEDIUM

#### M1：EVTRisk 空/坏输入返回伪造默认指标（Rule 4 违反）
- **证据**：`evt_risk.py:105-115`（`calculate_metrics` 捕获所有异常返回 `_get_default_metrics`）、`:286-299`（`_get_default_metrics` 返回 var_95=0.02/var_99=0.04/cvar_95=0.03/cvar_99=0.06/max_dd=0.2/regime=NORMAL/ntf=中性）、`:143,149,170,176,232,240`（各函数 except 后返回阈值常量）。
- **实测**：空输入 → `var_95=0.05, var_99=0.05, cvar_95=0.06, cvar_99=0.06, max_dd=0.2, regime=NORMAL, ntf=中性`——**貌似合理的伪造数据**，而非显式失败。
- **影响**：Rule 4"缺失输入必须显式失败"被绕过；下游 FSM risk_scaler 会把空数据当成"正常市况"继续交易。
- **修复**：空/坏输入应抛 `RiskCalculationError`（让调用方 fail-closed），或返回显式 `None`/NaN 标志；不得回填常数。

#### M2：`uniquant.risk.ComplianceEngine` 包级导出为 None（名称错配）
- **证据**：`__init__.py:11` `from .compliance_engine import ComplianceEngine`，但类名是 `PreTradeComplianceEngine`（`compliance_engine.py:85`）→ `ImportError` 被捕获，`ComplianceEngine = None`；`__init__.py:7` 文档仍写"ComplianceEngine: 交易合规与风控检查"。
- **实测**：`import uniquant.risk as r; r.ComplianceEngine` → `None`，且不在 `__all__`。
- **影响**：任何 `from uniquant.risk import ComplianceEngine` 静默得到 `None`（潜在 AttributeError 延迟爆发）。文档契约与实现不符。
- **修复**：`__init__.py` 改为 `from .compliance_engine import PreTradeComplianceEngine as ComplianceEngine`。

### LOW

#### L1：几何止损"最保守"标签对多头方向反转
- **证据**：`sizer.py:149` "Use the highest stop loss value (most conservative)"；`:155` `risk_per_share = price - final_stop`；`:167` `shares = max_loss/(risk_per_share*penalty)`。取更高止损 → risk_per_share 更小 → **股数更大**。
- **影响**：语义误导（标签与数值行为相反），非安全缺陷（总风险仍受 `max_loss_allowed` 帽）。
- **修复**：改注释为"取更高止损以贴近 CZSC 底分形/降低单股风险敞口"，明确说明股数会放大。

#### L2：PositionSizer 中文字段名（`sizer.py:189-203`）
- 与代码库英文风格不一致；`unified_engine.py:363` 依赖 `"suggested_shares"`（英文）但 sizer 主返回中文键，靠 `position_plan.get("建议仓位")` 混合取值，易错。建议统一。

#### L3：drawdown.py / structural_risk.py / sparse_convex.py 不存在
- 仅 `.pyc` 残留（`risk/__pycache__/drawdown_analyzer.*.pyc` 等），从未被 git 跟踪。工作流文档（及本任务范围描述）列的这三个文件**不存在**。属文档过时。

#### L4：合规参数未接入 config.yaml
- 8 参数可在构造器配置（`compliance_engine.py:88-107`，✅ 满足"是否可配置"），但 `config.yaml` 无 `compliance` 段（仅 `risk.default_risk_pct/circuit_break_pct`），`ManifestGenerator` 只透传 `max_single_stock_weight`（`manifest_generator.py:63-64`），其余用默认值。建议将 7 防线参数纳入配置。

---

## ⑤ 交叉复核矩阵（vs 既有 Claude 报告，基线 `434aab1`，源码与现 HEAD 一致）

| 既有结论 | 级别 | 我方判定 | 依据/说明 |
|---|---|---|---|
| §7.1 CRITICAL：无 | — | **分歧** | 我方发现 H1（Gross Leverage 公式错误）与 H4（KillSwitch Fail-Open on read-error）为 CRITICAL/HIGH 级缺陷，既有报告"无 CRITICAL"不成立。既有报告与第三方评审均未识别 H1 与 H4。 |
| §7.3 M1：VaR/CVaR 非真 EVT，已标注 | MEDIUM | **一致（已标注）** | `evt_risk.py:31-32` 明确 "NOT true EVT"。✅ 符合任务核查点。但既有报告未指出**空输入返回伪造默认指标**（我方 M1，Rule 4 问题）——新增。 |
| §7.3 M2：缺空头总权重检查 | MEDIUM | **一致，但应升级为 HIGH** | 既有报告说"文档 7 大防线实际 6 个"，方向对。但**未识别根本原因**：gross_leverage 公式 `1+short_weight` 已隐含 `short≤76%`，真正的缺口是**多头侧杠杆无约束**（H1）。第三方评审已将其升级为 HIGH——我方认同升级。 |
| §7.4 L1：工作流文档过时（drawdown/structural/sparse 不存在） | LOW | **一致** | 三文件仅 .pyc 残留，从未被 git 跟踪。✅ |
| §7.4 L2：PositionSizer 中文字段名 | LOW | **一致** | `sizer.py:189-203`。✅ |
| §8.1 已验证事实（参数可配置 / 百分位法 / T9a 持久化 / T+1 CN:1.2 / 几何止损 max / 整百股 / PB 1200） | — | **一致** | 逐项复验通过。**但 T9a 仅 happy path 成立**——读失败时 fail-open（我方 H4），既有报告未覆盖该反例。 |
| §9.3 修复优先级：P1=空头权重检查，P2=GPD | — | **分歧（优先级）** | 我方认为 P0/P1 应优先修复 **H2（合规引擎未接入执行链路）** 与 **H1（gross 公式）**，二者是"防线根本不生效"，优先级高于补空头检查；GPD 拟合（既有 P2）是增强项非缺陷，应降级。 |
| 第三方评审 H1：缺空头检查=防线 fail-open，报告降级 MEDIUM | HIGH | **一致（认同升级）** | 第三方评审正确指出 M2 定级与性质不匹配。我方补充：缺的并非单是空头检查，而是 **gross 公式本身错误**（H1）。 |
| 第三方评审 H2：sizer 失败放水到 100 股 | HIGH | **一致（新增我方 H3）** | `arbitrator.py:404-406`/`unified_engine.py:367-368`。既有报告完全遗漏，第三方评审命中，我方独立复现确认。 |
| 第三方评审 H3：sizer 无单仓权重上限，本金熔断允许满仓单票 | HIGH | **一致（我方 H2 佐证）** | `sizer.py:182-187` 只截断到 100% 本金；唯一 2.5% 上限在未接入的合规引擎。既有报告未覆盖，第三方评审命中。 |
| 第三方评审 M2：合规引擎是否接入回测/实盘未说明 | MEDIUM | **一致（我方 H2 证实未接入）** | `grep` 全库确认 `audit()` 仅 `manifest_generator.py:297` 调用。第三方评审质疑成立，我方给出确定性证据。 |
| 第三方评审 M1：回测止损是否真的执行 | MEDIUM | **一致（确认未执行）** | `unified_engine.py:358` 写死 `stop_loss=closes*0.95`，`czsc_bottom=None`；`unified_matching_engine.py` 无 stop-loss 字段；FSM 传 `ctx.czsc_bottom` 但止损仅进 `position_details` 字典（`fsm.py:448`），无对应卖单撮合。**止损在回测中是空转的**。 |
| 第三方评审 需确认项：risk_pct 生产默认 0.05 | — | **确认 0.05，但与 config 0.1 不一致** | `sizer.py:79` 默认 `risk_pct=0.05`；`service_container.py:195` `PositionSizer()` 用默认值；`config_schema.py:135` `default_risk_pct=0.1`。**生产 sizer 未读取 config 的 10%**，实际 5%。 |
| 第三方评审 需确认项：lot_size 对创业板/科创板 | — | **确认正确** | `market_rules.py:20-24` GEM=100/STAR=200；`sizer.py:97-107` 经 `get_board_rule(symbol).lot_size` 读取，正确。 |
| 第三方评审 需确认项：小资金 vs 机构参数错配 | — | **确认** | `PositionSizer()` 默认 `initial_capital=100k`，与 1 亿 AUM 机构示例错配；`risk_pct` 0.05 未接 config。 |

**交叉复核结论**：既有报告（Claude）遗漏 3 项 HIGH（H1 gross 公式、H3 无单仓上限/合规未接入、H4 KillSwitch Fail-Open），且对 2 项仅作 MEDIUM 降级；第三方评审补中 H2/H3 与 M1/M2，但未识别 H1 与 H4。**我方独立发现 H1（gross 公式）与 H4（KillSwitch read-error fail-open）为双方均未捕获的新缺陷**。

---

## ⑥ 结论与建议

**健康度：B（有条件可用）**——设计认真、参数可配置、T9a happy path 正确、签名与持久化到位；但存在部署前必须处理的 fail-open 与公式缺陷。

**问题计数**：HIGH 4（H1 gross 公式错误、H2 合规引擎未接入、H3 sizer 失败放水 100 股、H4 KillSwitch 读失败 Fail-Open）；MEDIUM 2（M1 EVT 空输入伪造指标、M2 包级导出 None）；LOW 4（L1 几何止损标签反转、L2 中文字段名、L3 文档过时、L4 参数未接 config）。

**修复优先级（P0→P2）**：
1. **P0**：H1 修正 gross_leverage 公式（补多头杠杆约束）；H2 将合规引擎接入回测/实盘执行链路；H4 KillSwitch 读失败默认 killed=True。
2. **P1**：H3 sizer 失败改为 fail-closed（拒绝开仓）；M1 EVT 空输入显式抛错（Rule 4）。
3. **P2**：M2 修正包级导出；L1-L4 文档/命名/配置对齐。

**关键不变量**：任何"风控防线"的 fail-open 路径（计算失败仍下单、防线未接入、存储读失败放行）都是实盘红线。建议在 H2 修复后增加一条"合规引擎必须参与每个交易日持仓生成"的集成测试，并明确"回测止损为旁路/空转"这一限制写入文档。
