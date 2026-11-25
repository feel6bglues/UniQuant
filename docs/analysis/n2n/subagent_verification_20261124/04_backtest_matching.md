# 子代理独立验证报告 — 回测撮合模块 (04_backtest_matching)

> **验证人**：独立审查子代理（SenseNova 6.8 Flash Lite / 商汤日日新）
> **验证日期**：2026-11-24
> **代码基线**：`b1d2415`（HEAD，git 基线）
> **被复核报告**：`docs/analysis/n2n/04_backtest_matching_n2n.md`（Claude 报告，基线 `434aab1`，含两份独立第三方评审意见）
> **分析范围**：`src/uniquant/hands/backtest/`（10 文件，1,883 行核心） + `src/uniquant/shared/`（cost_model / slippage_model / limit_checker / market_rules / board_registry / constants）
> **方法**：独立静态分析（先做）→ 行为探针实证（`python3 -c` 复现）→ 交叉复核（后做，对照既有报告）。
> **独立性声明**：本报告全部结论由验证人独立得出，未先读既有报告结论；既有报告仅用于第 ⑤ 步交叉复核。

---

## ① 执行摘要

UniQuant 回测撮合模块的核心（`UnifiedBacktestEngine.run` 标量主循环 + `UnifiedMatchingEngine` 向量化撮合）整体是**生产可用的**：七大防线（T+1/涨跌停/停牌/资金/成本/滑点/整手）A股规则覆盖扎实，主循环状态机（PENDING→RETRYING→成交/坏账）设计成熟，且配套了较充分的专项测试（`test_unified_matching.py` / `test_limit_down_rollover.py` / `test_t1_constraint_boundary.py` / `test_lookahead_bias.py`）。

但独立验证发现 **3 项 HIGH、4 项 MEDIUM、3 项 LOW**，其中两项是既有报告完全未覆盖的真实缺陷：

1. **坏账清退（0 元出清）的账目不一致**（HIGH）：`unified_engine.py:294-315` 在 30 日跌停后强制 `price=0.0` 出清，但**记录的 SELL PnL 与权益曲线实际跌幅不一致**。实测：记录 `pnl=-1000.51`（按成本价），而权益曲线当日只跌 `-900.00`（按市值），两者差 `100.51` 且**无现金流入**（仓位价值凭空消失）。这是既有报告及两份第三方评审均**未给出数值证据**的方法论隐患（评审 M2 只定性提及）。
2. **标量与向量化滑点模型系统性分歧**（HIGH）：`unified_models.py:288-309`（`0.001·√ratio` 封顶 2%）与 `unified_matching_engine.py:84-92`（分段 `0.001·√(eta/0.10)` 后线性，封顶 5%）是**两个不同模型**。实测在 `eta≤0.10` 时向量化恒为标量 **≈3.2 倍**、`eta=0.5` 时 7.1 倍。两引擎对同一输入产出不同执行价，交叉验证不可比。
3. **向量化快路径跳过 ST ±5% 检测**（HIGH）：`unified_matching_engine.py:137-145` 在 `names is None` 时用主板 ±10% 判定，ST 股被放水；实测 `price/pre=1.05` 时快路径判 `非涨停`、慢路径（name=ST）判 `涨停`。

**关键架构观察**：既有报告 §3.2/§8 大量篇幅描述的**向量化 `UnifiedMatchingEngine` 并未接入生产**——`src/` 全库仅 `hands/__init__.py:6` 文档提及 + 自身定义，无任何生产调用点；生产路径实为标量 `UnifiedBacktestEngine`（`research_pipeline.py:140` / `bootstrap.py:115` / `service_container.py:145`）。因此向量化路径的若干缺陷目前是**潜在**而非在途。

**健康度评级：B（部分可信，存在需修复的真实缺陷）**。七大防线骨架 A 级，但坏账账目不一致 + 滑点双模型分歧 + ST 快路径放水使整体下调为 B。

---

## ② 五问逐节点答案

### Q1 定义（Name 定义与契约）

**输入契约**：`run(df: pd.DataFrame, signals: List[TradingSignal], symbol: str = "", ...) -> BacktestResult`（`unified_engine.py:149-167`）。信号为强类型 `TradingSignal`（`shared/interfaces.py`），与 signal 层解耦，符合"hands 层只吃 `List[TradingSignal]`"的分层纪律。✅

**中间数据契约**：
- `pending_order: Optional[Dict]`（`unified_engine.py:189`）—— 隐式 dict 契约，字段 `action/shares/reason/status/retry_count`，**无 dataclass/类型注解**，靠字符串字面量 `"PENDING"/"RETRYING"` 驱动状态机。⚠️ 契约脆弱（状态机字面量非枚举）。
- `TradeRecord`（`unified_models.py:33-47`）—— 必填 timestamp/action/symbol/price/shares/commission，可选 stamp_duty/transfer_fee/slippage/pnl/reason。✅
- `FillResult`（`unified_matching_engine.py:21-32`）—— 向量化输出，含 `executed_shares/exec_prices/commissions/stamp_duties/slippages/transfer_fees/rejected_mask/t1_violation_mask/limit_violation_mask/cash_shortfall_mask`。✅

**输出契约**：`BacktestResult`（`unified_models.py:49-170`）含 7 项指标属性 + `compare()`/`to_dict()`。✅ 指标边界（空/除零/负）处理齐全。

**Q1 结论**：契约清晰、类型化良好。唯一瑕疵是 `pending_order` 用裸 dict + 字符串字面量而非强类型/枚举（LOW，可维护性）。

### Q2 映射（Name 映射与数据流）

**信号→成交的时间映射**：`index_signals_by_date`（`unified_models.py:195-204`）按 `sig.timestamp.strftime("%Y-%m-%d")` 建索引；主循环 Step3（`unified_engine.py:326-387`）当日生成 `pending_order`，Step1（`unified_engine.py:209-315`）**次交易日 Open 执行**（T+1 延迟）。成交价 = `opens[idx]`（`unified_engine.py:211`）。✅ 无前视（`test_lookahead_bias.py` 锁定）。

**⚠️ 映射失真点**：
- **LPPL 特殊映射**（`unified_engine.py:339-348`）：`sig.reason` 含 `"lppl"` 的 SELL 被**强制置于 BUY 之前**，绕过了 signal 层 `SignalArbitrator` 已完成的仲裁（`signal/arbitrator.py:33` 给了 lppl 权重 99）。同一 `List[TradingSignal]` 在"是否有 lppl reason"下映射到**不同的订单优先级**——映射函数依赖策略语义字符串，破坏了 hands 层"策略无关"契约（Q5 治理）。
- **双引擎同概念异实现**：标量 `UnifiedBacktestEngine` 与向量化 `UnifiedMatchingEngine` 把"涨跌停判定/滑点/成本"映射到**不同公式**（见 Q4/问题 H1）。概念同、实现异 → 交叉验证结果不可比。

**Q2 结论**：时间映射正确（T→T+1 Open）；但 LPPL reason 字符串劫持优先级、双引擎公式分歧，使"信号→成交"映射**非确定且跨引擎不一致**。

### Q3 传播（依赖链与状态传播）

主循环传播状态：`cash / position / position_cost / buy_date / trades / equity_curve / daily_returns / pending_order`（`unified_engine.py:171-189`）。传播路径：

```
cash <- _execute_buy/sell 返回的 remaining_cash
position <- += record.shares (BUY) ; -= record.shares (SELL)
position_cost <- record.price (每次 BUY 覆盖, line 247)
equity <- cash + position * closes[idx] (Step2, line 318)
```

**传播正确性评估**：
- **buy 路径**：`cash` 单调扣减、`position` 递增、`position_cost` 覆盖——✅ 正常。
- **sell 路径**：`cash += net_value`、`position -= shares`、清仓时 `position_cost=0/buy_date=None`（line 277-280）——✅ 正常。
- **⚠️ 坏账路径传播中断**（`unified_engine.py:294-315`）：`position=0`、`position_cost=0`、`buy_date=None`，但 **`cash` 未被增减**。Step2 权益由 `cash + position·close` 算出，`position` 归零 → 权益当日凭空下降 `position·close`，而该笔"卖单"**无现金流入**，且记录 PnL（-成本价·shares）与权益跌幅（-市值）**对不上**。**这是传播链条的真实断裂**（详见问题 H2）。
- **`position_cost` 覆盖仅安全因 BUY 前置守卫**：`_execute_buy` 仅在 `position == 0` 时被触发（`unified_engine.py:351`），故 `position_cost` 每次 BUY 都是新仓成本，无加仓累叠错误。✅（该守卫使"金字塔成本基准"缺陷不可达——见交叉复核分歧 R-分歧2。）

**Q3 结论**：正常买卖传播正确；**坏账清退路径传播断裂**（现金/权益/记录 PnL 三方不一致）是模块最实质缺陷。

### Q4 变异（边界条件与异常）

| 变异点 | 实现 | 行为 | 判定 |
|---|---|---|---|
| 非交易日 | `unified_engine.py:196-205` | 跳过执行，仍更新权益 | ✅ |
| 停牌 C | `unified_engine.py:216-229` | vol=0 拒单；SELL 结转 RETRYING，BUY 作废 | ✅ |
| T+1 A | `unified_engine.py:254-260` | 未达 T+1 结转 RETRYING | ✅ |
| 涨停拒买 B | `unified_engine.py:231-251,548` | Auto-Cancel 不结转 | ✅ |
| 跌停拒卖 B | `unified_engine.py:282-315` | RETRYING 结转，30 日后坏账 | ⚠️ 账目不一致（H2） |
| 资金不足 D | `unified_engine.py:571-585` | 自动减量 + 二次检查 | ✅ |
| 涨停后滑点越界 | `unified_engine.py:548→553` | 限价检查用 raw open，滑点后 exec 可越界 | ⚠️ 见 M1 |
| 互斥排队 INV-6 | `unified_engine.py:327-335` | RETRYING 期间 BUY 信号被拦截 | ✅（但仅记日志，信号丢失） |

**A股规则正确性**：主板 ±10% / 科创创业 ±20% / 北交所 ±30% / ST ±5%（`constants/market.py:79-85`）✅ 与交易所一致；IPO 特殊规则（主板首日 +44%/-36%、科创创业前 5 日无限制、北证首日无限制）✅（`unified_matching_engine.py:161-172`；`limit_checker.py:78-118`）。**但** ST 检测在向量化快路径被跳过（H3）、STAR lot_size=200 但科创板允许 200 以上 1 股递增（L1）。

**Q4 结论**：边界覆盖全面，但两处变异处理失真——坏账账目断裂（H2）、限价检查先于滑点导致执行价越界（M1）。

### Q5 治理（可观测性与可测试性）

- **可观测性**：每条防线拦截均有 `logger.debug/warning`（`unified_engine.py:218/256/332/549/294`）；`metadata` 记录参数+统计+幸存者警告（`unified_engine.py:405-420`）。✅
- **可测试性**：`sensitivity_scan`（`unified_engine.py:100-147`）、专项测试套件（T+1/涨跌停/停牌/资金/成本/滑点/整手/前视/坏账/互斥）覆盖充分。✅
- **⚠️ 分层治理**：hands 层本应策略无关，但 `unified_engine.py:339-348` 通过 `"lppl" in reason` 耦合了 LPPL 策略语义（且 `test_lookahead_bias.py:171-214` 把该耦合锁死为"有意行为"）。这是**层泄漏**（LOW-MEDIUM）。
- **⚠️ 治理盲区**：`UnifiedMatchingEngine` 被 `hands/__init__.py:6` 文档标为"推荐使用"，但**无生产调用点**——文档与实现的治理脱节（并行路径/死文档）。见交叉复核。
- **⚠️ 幸存者偏差**：`unified_engine.py:389-403` 仅 `except (OSError,...): pass` 静默跳过 + 只写 warning 字符串，不剔除退市股——是 best-effort 警告，非修正（与既有评审 M4 一致）。

**Q5 结论**：可观测/可测试良好；分层治理有 LPPL 语义泄漏 + 向量化引擎"文档推荐但未接线"盲区。

---

## ③ 端到端路径追踪

### 路径 1：正常买入 → T+1 卖出（Happy Path）
```
TradingSignal(BUY, 1000, T) → signal_map[T] (unified_models.py:195)
→ Step3 T日: pending_order={BUY,1000,PENDING} (unified_engine.py:350-376)
→ Step1 T+1日: vol>0 ✓ (C) ; _execute_buy (529)
    → B: _check_limit(open, pre_close, BUY) 非涨停 ✓ (548)
    → F: _calc_slippage(open, is_buy=True, 1000, adv) → exec=10.0051 (553)
    → G: lot=100, 1000//100*100=1000 (561)
    → E: commission=max(3,5)=5, transfer=0.01 (567-569)
    → D: total_cost≤cash ✓ (572)
    → TradeRecord(BUY, 10.0051, 1000) ; position=1000, cash-=1005.51
→ Step2: equity=cash+1000·close (318)
→ TradingSignal(SELL, 1000, T+1) → Step1 T+2: _check_t1(buy=T+1,sell=T+2)≥next_td ✓ (255)
    → B: 非跌停 ✓ ; F: sell滑点向下 exec=9.9950 ; E: stamp=value·get_stamp_tax_pct(date) (643)
    → TradeRecord(SELL, 9.9950, 1000, pnl=+1988.88) ; position=0, cash+=net (277-280)
```
**验证**：`test_backtest_core_unit.py:460-501`（round-trip 算术精确）、`test_unified_matching.py:149-163`（次日卖出成功）✅。

### 路径 2：涨停拒买（Auto-Cancel，不结转）
```
TradingSignal(BUY, T) → Step3 T日 pending_order={BUY,PENDING}
→ Step1 T+1日: vol>0 ✓ ; _execute_buy
    → B: ratio=open/pre_close=1.10 ≥ 1.10-0.001 → return False (unified_models.py:258)
    → return None, cash (unified_engine.py:548-550)
→ pending_order=None (line 251, Auto-Cancel) —— 次日绝不追高
```
**验证**：`test_limit_down_rollover.py:136-165`（`test_buy_limit_up_auto_cancels_without_rollover`）✅。

### 路径 3：跌停拒卖 → RETRYING 结转 → 30 日坏账清退（含账目断裂证据）
```
TradingSignal(SELL, T) → Step1 T+1: 跌停 ratio=0.90 ≤ 0.90+0.001 → return None (unified_models.py:260)
→ line 283-292: status=RETRYING, retry_count+1 —— 强制结转
→ 重复 ≤29 次 (retry_count<30) ; 第 30 次 (retry_count=30):
→ line 294-315: logger.warning; bad_debt_record=SELL price=0.0 pnl=-position_cost·position
    position=0, position_cost=0, buy_date=None, pending_order=None  —— **cash 不变**
→ Step2: equity=cash+0·close (318) —— 权益单日跳变
```
**实测（50 日一字跌停，买 100 股@10）**：
```
2024-01-03 BUY  px=10.0051 sh=100
2024-02-22 SELL px=0.0 sh=100 pnl=-1000.51 reason=BAD_DEBT_LIMIT_DOWN_30D_EXPIRED
final_cash=98994.48
equity day36=99894.48 → day37=98994.48   ← 权益单日 -900.00
```
**账目断裂证据**：记录 `pnl=-1000.51`（成本基准），但权益曲线单日跌 `-900.00`（市值基准，=100×9.0）。差值 `100.51`。且 `cash` 前后均 `98994.48`，**无现金流入**——`position·close` 的 900 元市值被凭空抹除，既不进现金、也不与记录 PnL 对齐。**这是既有报告未给出数值证据、第三方评审仅定性提及的实质缺陷。**
**验证**：`test_limit_down_rollover.py:167-209` 断言 `price==0.0` / `reason==BAD_DEBT...`（但**未断言** cash/equity 一致性）。

### 路径 4：T+1 拒卖 → RETRYING 结转（同日/次日前卖出被拒）
```
TradingSignal(SELL, T+1 或同日) → Step1: _check_t1(buy, sell)
    → sell_ord ≤ buy_ord 或 sell < next_td → False (unified_models.py:229-233)
→ line 257-259: status=RETRYING, retry_count+1 —— 结转至下一交易日
→ 次交易日: _check_t1 通过 → _execute_sell 正常成交
```
**验证**：`test_backtest_core_unit.py:541-548`（`test_sell_t1_reject_is_rolled_over`）✅。

### 路径 5：互斥排队保护（RETRYING 拦截 BUY）
```
Step1 T+1: SELL 跌停拒卖 → pending_order.status=RETRYING (line 286)
→ Step3 T+1: pending_order.status=="RETRYING" (line 328)
    → 遍历 day_signals, 仅对 BUY 记 logger.warning (line 331-334)
    → 不进入 else 分支 → **BUY 与新增 SELL 信号均被压制**, pending_order 保持
→ Step1 T+2: RETRYING 卖单置顶重试
```
**验证**：`test_limit_down_rollover.py:86-134`（`test_mutex_queue_protection_blocks_buy_while_retrying`）✅。
**观察**：互斥保护**仅记日志不落账**——被拦截的 BUY 信号**静默丢失**（无 rejected 记录/无回补），若策略依赖该 BUY 会"无声少买"（LOW，可观测性）。

---

## ④ 问题清单（分级 + 证据 + 修复建议）

### CRITICAL
无。

### HIGH

#### H1：标量与向量化滑点模型系统性分歧（双引擎不可比）
- **证据**：`unified_models.py:288-309`（`impact = min(0.001·√(trade_vol/adv), 0.02)`）；`unified_matching_engine.py:84-92`（`eta=qty/adv; eta≤0.10→0.001·√(eta/0.10); eta>0.10→0.001+0.01·(eta-0.10)`，封顶 `0.05`）。**实测**（纯市场冲击，不含基础滑点率 0.0005）：
  ```
  eta=0.0010: scalar=0.001·√0.001=0.000032  vec=0.001·√0.010=0.000100  (3.2×)
  eta=0.0100: scalar=0.001·√0.010=0.000100  vec=0.001·√0.100=0.000316  (3.2×)
  eta=0.1000: scalar=0.001·√0.100=0.000316  vec=0.001·√1.000=0.001000  (3.2×)
  eta=0.5000: scalar=0.001·√0.500=0.000707  vec=0.001+0.004=0.005000    (7.1×)
  ```
  向量化在 `eta≤0.10` 恒为标量 **≈3.2 倍**（√10），`eta>0.10` 达 7.1 倍；且封顶不同（标量 2% vs 向量化 5%）。两模型系统性分歧（方向一致、量级差 3~7 倍）。
- **影响**：同一 `List[TradingSignal]` 经两引擎产出不同执行价 → 交叉验证/结果对比失真。目前向量化未接生产，风险**潜在**；一旦接入即为系统性偏差。
- **修复**：统一为一个滑点模型（建议以向量化分段平方根为准，标量弃用），或至少在 `calculate_slippage` 顶部注释声明其与 `compute_execution_prices` 的差异并加一致性测试（同输入→同输出）。

#### H2：坏账清退（0 元出清）账目不一致
- **证据**：`unified_engine.py:294-315` 置 `position=0` 但 **`cash` 不变**；记录 `pnl=-position_cost·position`（成本基准），权益曲线 Step2 按 `cash+position·close`（市值基准）计算。**实测**：记录 `pnl=-1000.51`，权益单日 `-900.00`，现金前后均 `98994.48`。
- **影响**：① 记录 PnL（-1000.51）≠ 权益跌幅（-900.00），指标（win_rate/profit_factor/total_return）与权益曲线不自洽；② 仓位市值 900 元凭空消失（无现金流入），制造单日"权益悬崖"，扭曲回撤；③ `price=0.0` 为**虚构成交价**，触碰 Rule 4（缺失/伪造数据必须显式失败）。
- **修复**：坏账不应"0 元卖出"并抹除市值；应在日志+metadata 显式标记 `BAD_DEBT` 且**从权益计算中剔除**（或按当日跌停价入账并计入现金），并让记录 PnL 与权益跌幅一致。至少：坏账记录 PnL 应 = `-close·shares`（市值基准），并补 `cash += 0` 注释与一致性测试（断言 `equity_curve[-1] == final_cash`）。

#### H3：向量化快路径跳过 ST ±5% 检测
- **证据**：`unified_matching_engine.py:137-145` 快路径 `names is None and trading_days_listed is None` 时用 `get_board_type(s)`（无 name）→ ST 返回 `main` → 按 ±10% 判定；ST 检测仅在慢路径 `unified_matching_engine.py:154-157`。**实测**：`price/pre=1.05`（ST 涨停位）快路径判 `is_limit_up=False`，慢路径（name=ST）判 `True`。
- **影响**：若调用方未传 `names`，ST 股 ±5% 限价形同虚设（放水）；且 `get_board_type`（board_registry.py:112-113）与 `market_rules.detect_board`（board_registry.py:80-105）ST 匹配语义不同（startswith vs substring），三套 ST 判定不统一。
- **修复**：快路径若无法获得 name，对可能 ST 的标的强制走慢路径；或统一 ST 判定入口（board_registry 单源）。

### MEDIUM

#### M1：限价检查先于滑点 → 执行价可越出涨跌停带
- **证据**：`_execute_buy` 先 `_check_limit(price_raw=open)`（`unified_engine.py:548`）再 `_calc_slippage`（553）；`_execute_sell` 先限价（630）再滑点（635）。滑点后的 `exec_price` 可越过限价带（如 open 距涨停 0.05%，滑点 0.05% → exec 超涨停）。
- **影响**：涨停附近买单以**涨停价以上**成交、跌停附近卖单以**跌停价以下**成交——现实中不可成交。边界单被误放行。
- **修复**：限价检查应基于**含滑点执行价**（先算 `exec_price` 再 `_check_limit(exec_price, ...)`），或执行价钳制在限价带内。

#### M2：LPPL SELL 优先级遗留逻辑（仍存在）
- **证据**：`unified_engine.py:339-348`（`sig.reason` 含 `"lppl"` 的 SELL 先于 BUY 处理）。基线 `b1d2415` 仍在；`test_lookahead_bias.py:171-214` 将其锁定为有意行为（断言 SELL reason=`lppl_exit` 优先）。
- **影响**：hands 层通过 reason 字符串耦合 LPPL 策略语义，绕过 signal 层 `SignalArbitrator`（`signal/arbitrator.py:33` 已给 lppl 权重 99）的仲裁；违反分层（Q5）。实际影响有限（LPPL 默认 `diagnostic_only=True`，`adapters.py:545`，正常不产 SELL），与既有报告 M1 一致。
- **修复**：移除 LPPL 特殊优先级，统一按仲裁结果处理（SELL 优先即够）；若确需保留，应把"lppl 优先"上移到 signal 层仲裁而非 hands 层字符串匹配，并同步修改 `test_lookahead_bias.py`。

#### M3：裸代码（无 .SH/.SZ/.BJ 后缀）触发 `ValueError` 崩溃
- **证据**：`market_rules.get_board_rule` → `detect_board`（`board_registry.py:80-105`）对无交易所后缀代码 `raise ValueError`；`unified_engine.py:364`（PositionSizer 整手）与 `unified_engine.py:560`（`_execute_buy` 整手）均调用。**实测**：`get_board_rule('600000')` → `ValueError: unknown exchange suffix`；而 `get_board_type('600000')` → `main`（安全）。
- **影响**：同一 `symbol` 在限价检查（安全，前缀法）通过、在整手取整（崩溃，后缀法）抛异常——**鲁棒性不一致**。若生产流入裸代码，引擎在买单时崩溃。
- **修复**：`get_board_rule` 对裸代码降级为前缀推断（如 `get_board_type`），或 `_execute_buy`/信号收集统一先规范化 symbol（补交易所后缀）。

#### M4：涨跌停用比例而非交易所绝对限价
- **证据**：`unified_models.py:251-261` 用 `ratio = price/pre_close` 判限；而 `limit_checker.py:34-35,124-127` 已实现 `_round_limit_price`（四舍五入到 0.01 元绝对限价）未被 `check_limit_price` 使用。
- **影响**：低价股/临界价，比例法与绝对限价差一档（交易所按 0.01 元取整）。既有报告评 LOW，两份评审评 MEDIUM——按边界精度影响，取 **MEDIUM**（评审意见更准）。
- **修复**：复用 `limit_checker._round_limit_price` 计算绝对限价后比较。

### LOW

#### L1：STAR lot_size=200 与科创板"200 股以上 1 股递增"不符
- **证据**：`market_rules.py:24`（`BoardType.STAR: BoardRule(lot_size=200)`）；`unified_engine.py:561` 按 `//lot_size*lot_size` 取整。科创板实际为**最低 200 股、200 股以上可 1 股递增**，按 200 取整会低估 200 股以上买单（如 350 股 → 200 股）。
- **修复**：STAR 特殊取整（≥200 后取整到整数股），或文档化说明保守取整。

#### L2：幸存者偏差检查为 best-effort 空转
- **证据**：`unified_engine.py:389-403` `except (OSError,...): pass` 静默；仅 `metadata["survivorship_warning"]` 字符串，不剔除退市股。与既有评审 M4 一致。
- **修复**：至少记录 warning 日志；若能获取退市信息，回测区间应截断至退市前。

#### L3：互斥拦截的 BUY 信号静默丢失 + pending_order 用裸 dict 字面量
- **证据**：`unified_engine.py:328-335` 仅 `logger.warning`，被拦截 BUY 无 rejected 记录/无回补；`unified_engine.py:189` `pending_order: Optional[Dict]` 无类型化。
- **修复**：记录被拦截信号到 metadata/日志结构化字段；`pending_order` 改为 dataclass 或 TypedDict + 枚举状态。

---

## ⑤ 交叉复核矩阵

被复核报告 = `docs/analysis/n2n/04_backtest_matching_n2n.md`（Claude，基线 434aab1），其 §7 自评 **0 CRITICAL / 0 HIGH**，并附两份独立第三方评审（量化算法专家 / 资深 A 股交易员）。逐条标注（**一致 / 分歧 / 仍遗留 / 已修复**）：

| 既有结论 | 类别 | 验证人独立判定 | 标注 |
|---|---|---|---|
| 七大防线 A-G（§2.1，`unified_engine.py:7-15`） | 事实 | 逐条确认存在（A/B/C/D/E/F/G） | **一致** |
| 涨跌停规则 main±10/科创创业±20/北证±30/ST±5（§2.2） | 事实 | `constants/market.py:79-85` 一致 | **一致** |
| T+1 逻辑正确（§2.3） | 事实 | `unified_models.py:229-233` 语义正确 | **一致** |
| 资金永不透支（§2.4） | 事实 | `unified_engine.py:571-585` 二次检查 | **一致** |
| Fast/Slow Path 分支（§3.3） | 事实 | `unified_matching_engine.py:136-180` 确认 | **一致** |
| **M1 LPPL SELL 遗留（§7.3）** | 问题 | 基线 b1d2415 **仍存在**（`unified_engine.py:339-348`） | **仍遗留**（一致确认存在） |
| **L1 向量化 fill_buy 不查 T+1（§7.4）** | 问题 | 确认——但 T+1 仅约束卖出，买入不需查，属**设计分工**而非缺陷 | **分歧**（定为设计合理，非 bug） |
| **L2 限价用比例非绝对价（§7.4）** | 问题 | 确认存在；但严重度评 **MEDIUM**（既有评 LOW 低估，评审更准） | **分歧**（严重度上调） |
| 评审(量化) H1 "零 CRITICAL/HIGH 过松" | 问题 | 验证人独立发现 3 项 HIGH，印证评级过松 | **一致** |
| 评审(量化) H2 "无回测结果" | 问题 | 验证人运行行为探针，部分补足；报告本体仍无绩效曲线 | **部分一致** |
| 评审(量化) M1 win_rate 配对/金字塔 | 问题 | **不可达**——`unified_engine.py:351` `BUY and position==0` 守卫禁止加仓，`max_position` 实测恒 100 | **分歧**（缺陷不成立） |
| 评审(量化) M2 30 日 0 元出清扭曲绩效 | 问题 | 验证人**给出数值证据**：记录 pnl -1000.51 vs 权益 -900.00，现金不变 | **一致且强化**（账目断裂） |
| 评审(量化) M3 固定印花税率 | 问题 | **不成立**——标量 `_execute_sell:643` 传 `timestamp`，`calculate_stamp_duty`（`unified_models.py:270-280`）经 `get_stamp_tax_pct` 用时变税率；向量化 `unified_matching_engine.py:289-294` 亦按日期取率。**实测** 2023-08-27→10.0、2023-08-28→5.0 | **分歧**（非缺陷） |
| 评审(量化) M4 幸存者检查空转 | 问题 | 确认（`except:pass` + 仅 warning 字符串） | **一致** |
| 评审(交易) H1 一字板 vs 开板失真 | 问题 | 确认：仅按 `opens[idx]` 执行，未建模盘中开板 | **一致** |
| 评审(交易) H2 滑点低估/2% 封顶 | 问题 | 确认标量封顶 2%；**补充**：向量化封顶 5% 且模型不同（H1） | **一致并补充** |
| 评审(交易) M1 ST 快路径跳过 | 问题 | 验证人**实测复现**（price/pre=1.05 快路径放行） | **一致**（验证人评 HIGH） |
| 评审(交易) M3 费率未写数值 | 问题 | `cost_model.py:29-34` 有值（佣金万3/印花万5/过户万0.1/滑点万5）；报告未列 | **部分分歧**（代码有值，报告未披露） |

**交叉复核要点**：
1. 既有报告自评 0 CRITICAL/0 HIGH **明显过松**——验证人独立确认 3 项 HIGH（H1 滑点双模型、H2 坏账账目、H3 ST 快路径），其中 H1/H2 为既有报告未覆盖、仅第三方评审定性提及。
2. **两处"分歧"为重要纠正**：评审(量化) M3（固定印花税）与 M1（金字塔 win_rate）在**当前代码下不成立**——前者因标量路径实用时变税率、后者因 `position==0` 守卫禁止加仓。既有报告及评审据此夸大，应予回退。
3. **一处严重度上调**：L2（限价比例法）评审评 MEDIUM 更准，验证人采纳 MEDIUM。
4. **一项"仍遗留"**：LPPL SELL 优先级在 b1d2415 仍存在，与既有报告"未修复"一致；但验证人补充其为**分层违规**（hands 层耦合 LPPL reason 字符串）。

---

## ⑥ 结论与建议

### 健康度评级
**B（部分可信）**。七大防线与 A 股规则骨架 A 级、状态机设计成熟、测试充分；但坏账账目不一致（H2）、滑点双模型分歧（H1）、ST 快路径放水（H3）三处真实缺陷使整体下调。

### 问题计数
| 级别 | 数量 | 编号 |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 3 | H1（滑点双模型）/ H2（坏账账目）/ H3（ST 快路径） |
| MEDIUM | 4 | M1（限价先于滑点越界）/ M2（LPPL 遗留）/ M3（裸代码崩溃）/ M4（限价比例法） |
| LOW | 3 | L1（STAR 整手）/ L2（幸存者空转）/ L3（互斥静默丢失+裸 dict） |

### 修复优先级
1. **P1**：H2 坏账账目一致性（记录 PnL = 权益跌幅，现金/权益闭环）+ 补 `equity_curve[-1]==final_cash` 一致性测试；H3 ST 快路径（统一 ST 判定入口）。
2. **P1/P2**：H1 滑点双模型统一（若向量化拟投产必做）；M1 限价检查基于含滑点执行价。
3. **P2**：M3 裸代码 symbol 规范化；M4 限价用绝对价。
4. **P3**：M2 LPPL 遗留上移仲裁层；L1/L2/L3 低优先。

### 对既有报告的修正意见
- **撤回**：评审(量化) M3（固定印花税，实际用时变）、M1（金字塔 win_rate，`position==0` 守卫不可达）。
- **上调**：L2 限价比例法 LOW→MEDIUM。
- **新增未覆盖**：H1 滑点双模型分歧、H2 坏账账目不一致（含数值证据）、M1 限价先于滑点越界、M3 裸代码崩溃。
- **架构治理**：`UnifiedMatchingEngine` 被文档标"推荐使用"却无生产调用点，建议明确"向量化引擎为预留/实验"或补齐接线。

---

**验证人**：独立审查子代理（SenseNova 6.8 Flash Lite）
**验证日期**：2026-11-24
**代码基线**：`b1d2415`
**证据基础**：静态分析（行级引用）+ 行为探针实证（`python3 -c` 复现：滑点分歧、ST 快路径、坏账账目、印花税时变、金字塔不可达、裸代码崩溃）
**独立性**：全部结论先于阅读既有报告得出；既有报告仅用于第 ⑤ 步交叉复核。
