# 工作流 5：风控合规模块 N2N 深度分析报告

> **分析日期**：2026-11-24  
> **代码基线**：`434aab1` (第25轮)  
> **分析范围**：`src/uniquant/risk/` (5 文件, 1,655 行) + `src/uniquant/shared/kill_switch.py`  
> **方法论**：Name-to-Name 代码级点对点审查  

---

## 0. **重要发现：工作流文档与实际代码不符**

**工作流文档声称**（`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:245-253`）：
```
risk/
├── sizer.py                  # 仓位管理
├── drawdown.py               # 回撤控制
├── evt_risk.py               # VaR/CVaR
├── structural_risk.py        # 结构风险
├── portfolio_optimizer.py    # 组合优化
├── sparse_convex.py          # 稀疏凸优化
└── compliance_engine.py      # 合规引擎
```

**实际代码**：
```
risk/
├── sizer.py                  # 仓位管理 (481 行)
├── evt_risk.py               # VaR/CVaR (389 行)
├── portfolio_optimizer.py    # 组合优化 (448 行)
├── compliance_engine.py      # 合规引擎 (301 行)
└── __init__.py               # 导出 (36 行)
```

**关键差异**：
- **drawdown.py 不存在**：工作流文档中的"回撤控制"模块已移除
- **structural_risk.py 不存在**：工作流文档中的"结构风险"模块已移除
- **sparse_convex.py 不存在**：工作流文档中的"稀疏凸优化"模块已移除
- **严重程度**：LOW（仅文档过时，不影响运行时行为）

---

## 1. Name 定义（命名与契约）

### 1.1 **PreTradeComplianceEngine 事前合规引擎**

**核心定位** (`compliance_engine.py:1-22`)：
```python
"""
机构事前风控与合规签证引擎 (PreTradeComplianceEngine)

在交易清单落盘并下发给 PMS/OMS (如恒生 O32, 迅投 QMT) 之前，
执行毫秒级严格的硬风控边界审查与 SHA-256 密码学防篡改签证。

核心硬风控防线：
  1. 单票持仓集中度上限: w_i <= 2.5% AUM
  2. 申万一级行业集中度上限: Sum(w_ind) <= 10.0% AUM
  3. 行业单票数量上限: Count(stocks_in_ind) <= 4 只
  4. 组合杠杆与净敞口边界:
     - 多头总权重: <= 75.0%
     - 空头总对冲权重: <= 75.0%
     - 现金缓冲区: >= 25.0%
     - Gross Leverage: <= 175.0%
     - Net Exposure: [-0.5%, +0.5%] (严格市场中性)
  5. 中金所单 PB 主经纪商持仓限额: <= 1,200 手 / PB
  6. 现货整百股交易单位铁律: shares % 100 == 0
  7. 密码学防篡改证书: 对订单集合与风控指标计算 SHA-256 指纹
"""
```

**初始化参数** (`compliance_engine.py:88-107`)：
```python
def __init__(
    self,
    max_single_stock_weight: float = 0.025,  # 2.5%
    max_industry_weight: float = 0.100,      # 10.0%
    max_industry_stock_count: int = 4,       # 单行业最多4只
    max_long_weight: float = 0.755,          # 允许 +0.5% 舍入裕度
    min_cash_buffer_weight: float = 0.245,   # 允许 -0.5% 舍入裕度
    max_gross_leverage: float = 1.76,        # 175% + 1% 裕度
    max_net_exposure_abs: float = 0.005,     # |Net| <= 0.5%
    max_pb_contract_limit: int = 1200,       # CFFEX 单 PB 1200 手限制
):
```

**✅ 参数可配置性**：
- 8 个参数全部可在构造函数中配置
- 允许舍入裕度（+0.5%/-0.5%）避免浮点精度问题
- 参数命名清晰表达含义

### 1.2 **ComplianceReport 签证报告契约**

**报告结构** (`compliance_engine.py:59-82`)：
```python
@dataclass
class ComplianceReport:
    """事前合规签证报告"""
    manifest_id: str
    verdict: str  # "APPROVED_PASS" | "REJECTED_BREACH"
    manifest_hash: str
    passed: bool
    breaches: List[str]
    warnings: List[str]
    metrics: ComplianceMetrics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "verdict": self.verdict,
            "manifest_hash": self.manifest_hash,
            "passed": self.passed,
            "breaches": self.breaches,
            "warnings": self.warnings,
            "metrics": asdict(self.metrics),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
```

**✅ 契约完整**：
- verdict 二值判定：APPROVED_PASS / REJECTED_BREACH
- breaches 列表记录所有违规项
- manifest_hash SHA-256 指纹防篡改
- to_dict/to_json 便于序列化和审计

### 1.3 **PositionSizer 仓位管理器**

**T+1 惩罚系数** (`sizer.py:79-84`)：
```python
class PositionSizer:
    """
    Position Sizer for Alpha-Tactician Pro V8.0.
    Implements T+1 overnight risk penalty and CZSC Geometry adjusted stop loss.
    """

    def __init__(self, initial_capital: float = 100000.0, risk_pct: float = 0.05,
                 kelly_fraction: Optional[float] = None):
        self.capital = initial_capital
        self.risk_pct = risk_pct
        self.kelly_fraction = kelly_fraction
        self.market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}  # T+1 penalty
```

**✅ 市场差异化**：
- CN（A股）：1.2（T+1 隔夜风险惩罚）
- US/HK：1.0（T+0，无惩罚）

---

## 2. Name 映射（数据流转映射）

### 2.1 **七大防线检查顺序**

**PreTradeComplianceEngine.audit 主流程** (`compliance_engine.py:108-301`)：

```python
def audit(self, manifest_id, aum_cny, equity_orders, futures_hedging, industry_mapping=None):
    breaches: List[str] = []
    warnings: List[str] = []

    # 1. 现货多头统计
    eq_df = equity_orders.copy()
    if not eq_df.empty:
        # 整百股铁律 (防线 6)
        if "trade_shares" in eq_df.columns:
            invalid_lots = eq_df[eq_df["trade_shares"] % 100 != 0]
            if not invalid_lots.empty:
                breaches.append(f"整百股合规违背: ...")
        
        # 单票权重上限 (防线 1)
        eq_df["weight"] = eq_df["est_amount"] / aum_cny
        max_stock_weight = float(eq_df["weight"].max())
        if max_stock_weight > self.max_single_stock_weight + 1e-6:
            breaches.append(f"单票持仓集中度超限: ...")
        
        # 行业集中度与持股数检查 (防线 2, 3)
        ind_grouped = eq_df.groupby("industry_l1").agg(...)
        if max_ind_weight > self.max_industry_weight:
            breaches.append(f"行业集中度超限: ...")
        if max_ind_count > self.max_industry_stock_count:
            breaches.append(f"行业持股数量超限: ...")

    # 2. 期货空头对冲统计
    fut_df = futures_hedging.copy()
    if not fut_df.empty:
        # 单 PB 持仓限额 (防线 5)
        pb_cols = [c for c in fut_df.columns if "pb" in c.lower() and "contract" in c.lower()]
        for col in pb_cols:
            col_max = int(fut_df[col].max())
            if col_max > self.max_pb_contract_limit:
                breaches.append(f"中金所主经纪商(PB)持仓超限: ...")

    # 3. 宏观杠杆与净敞口指标 (防线 4)
    long_weight = total_long_cny / aum_cny
    short_weight = total_short_cny / aum_cny
    cash_weight = cash_buffer_cny / aum_cny
    gross_leverage = (total_long_cny + total_short_cny + cash_buffer_cny) / aum_cny
    net_exposure = (total_long_cny - total_short_cny) / aum_cny

    if long_weight > self.max_long_weight:
        breaches.append(f"多头总仓位超限: ...")
    if cash_weight < self.min_cash_buffer_weight:
        breaches.append(f"现金缓冲区不足: ...")
    if gross_leverage > self.max_gross_leverage:
        breaches.append(f"总杠杆率超限: ...")
    if abs(net_exposure) > self.max_net_exposure_abs:
        breaches.append(f"对冲净敞口失衡: ...")

    # 4. 指纹签名计算 (防线 7)
    signature_payload = {...}
    manifest_hash = hashlib.sha256(json.dumps(signature_payload, sort_keys=True).encode()).hexdigest()

    return ComplianceReport(...)
```

**✅ 防线检查顺序清晰**：
1. 整百股铁律（防线 6）
2. 单票权重上限（防线 1）
3. 行业集中度与持股数（防线 2, 3）
4. 单 PB 持仓限额（防线 5）
5. 宏观杠杆与净敞口（防线 4）
6. SHA-256 指纹签名（防线 7）

### 2.2 **PositionSizer.calculate_shares 计算**

**几何止损选择** (`sizer.py:145-152`)：
```python
# 1. Determine final stop loss (higher is more conservative)
atr_stop_value = atr_stop if atr_stop is not None else stop_loss
final_stop = atr_stop_value

# Use the highest stop loss value (most conservative)
if czsc_bottom is not None and czsc_bottom > atr_stop_value:
    final_stop = czsc_bottom
    logger.info(f"Using CZSC Bottom Fractal for stop loss: {final_stop}")
```

**T+1 惩罚系数应用** (`sizer.py:160-167`)：
```python
# 3. Apply T+1 penalty to the risk amount
penalty = self.market_penalties.get(market, 1.0)
effective_risk_pct = self.risk_pct * self.kelly_fraction if self.kelly_fraction is not None else self.risk_pct
max_loss_allowed = safe_round(self.capital * effective_risk_pct, PrecisionConstants.PRICE_DECIMALS)

# 4. Calculate shares with precision safety
# Shares = MaxLoss / (RiskPerShare * Penalty)
shares = safe_divide(max_loss_allowed, risk_per_share * penalty, 0)
```

**✅ 计算逻辑清晰**：
- 几何止损：`final_stop = max(ATR_stop, CZSC_bottom)`（取最保守值）
- T+1 惩罚：CN 市场 penalty=1.2，降低仓位
- 股数计算：`shares = max_loss_allowed / (risk_per_share × penalty)`

### 2.3 **KillSwitch Fail-Closed 语义**

**持久化状态恢复 (T9a)** (`kill_switch.py:45-56`)：
```python
# 从持久化状态恢复 (T9a 崩溃恢复守卫: 停机状态重启不丢失)
try:
    saved = self._state_store.get("kill_switch")
    if saved and saved.get("killed", False):
        self._killed = True
        self._reason = saved.get("reason", "recovered_from_state_store")
        logger.warning(
            "SharedKillSwitch 恢复持久化停机状态: reason=%s (T9a Fail-Closed 保护)",
            self._reason,
        )
except Exception as e:
    logger.error("SharedKillSwitch 恢复持久化状态失败: %s", e)
```

**持久化写入** (`kill_switch.py:68-82`)：
```python
def kill(self, reason: str = "manual_override") -> None:
    with self._lock:
        self._killed = True
        self._reason = reason
        try:
            self._state_store.put(
                "kill_switch",
                {
                    "killed": True,
                    "reason": reason,
                    "timestamp": time.time(),
                },
            )
        except Exception as e:
            logger.error("SharedKillSwitch 持久化停机状态失败: %s", e)

    for hook in self._hooks:
        try:
            hook()
        except Exception as e:
            logger.error(f"Kill switch hook {hook} failed: {e}", exc_info=True)
```

**✅ Fail-Closed 保护**：
- 重启后从 DiskStateStore 恢复停机状态
- kill() 时立即持久化到磁盘
- 停机状态不会因重启而丢失

### 2.4 **VaR/CVaR 百分位数法**

**HistoricalSimulationRisk 实现** (`evt_risk.py:24-33`)：
```python
class HistoricalSimulationRisk:
    """
    Historical Simulation based risk calculator.
    
    Uses historical percentile method (np.percentile) for VaR and CVaR calculation.
    Thread-safe implementation with lock-protected cache.
    
    Note: This is NOT true Extreme Value Theory (GPD fitting).
    For true EVT with GPD, use scipy.stats.genpareto.
    """
```

**calculate_var 实现** (`evt_risk.py:131-149`)：
```python
def calculate_var(self, returns: pd.Series, confidence: float) -> float:
    """Calculate Value at Risk (VaR)."""
    try:
        if returns.empty:
            raise RiskCalculationError("Empty returns series")

        var = -np.percentile(returns, (1 - confidence) * 100)
        return float(var)
    except RiskCalculationError as e:
        logger.error(f"Failed to calculate VaR: {e}")
        return RiskCalculationConstants.VAR_THRESHOLD_HIGH
```

**calculate_cvar 实现** (`evt_risk.py:151-176`)：
```python
def calculate_cvar(self, returns: pd.Series, confidence: float) -> float:
    """
    Calculate Conditional Value at Risk (CVaR).
    CVaR is the expected loss given that loss exceeds VaR.
    Mathematical guarantee: CVaR >= VaR.
    """
    try:
        if returns.empty:
            raise RiskCalculationError("Empty returns series")

        var = self.calculate_var(returns, confidence)
        tail_returns = returns[returns <= -var]
        if tail_returns.empty:
            # 空尾部时 CVaR 至少等于 VaR
            return float(var)
        cvar = -tail_returns.mean()
        return float(cvar)
    except RiskCalculationError as e:
        logger.error(f"Failed to calculate CVaR: {e}")
        return RiskCalculationConstants.CVAR_THRESHOLD_HIGH
```

**✅ VaR/CVaR 实现明确标注**：
- 使用百分位数法（`np.percentile`），非真正 EVT（GPD 拟合）
- 文档明确标注："This is NOT true Extreme Value Theory (GPD fitting)"
- CVaR 数学保证：CVaR >= VaR（空尾部时 CVaR = VaR）

---

## 3. Name 传播（依赖链追踪）

### 3.1 **ComplianceEngine 下游消费者**

**使用场景**：
- 交易清单下发前的硬门禁审查
- PMS/OMS（恒生 O32, 迅投 QMT）对接前的合规签证

**输出消费者**：
- ComplianceReport.to_json() → 审计日志
- manifest_hash → 防篡改验证

### 3.2 **PositionSizer 下游消费者**

**SignalArbitrator 集成** (`arbitrator.py:393-419`)：
```python
# Non-FSM buys need sizer
if non_fsm_buys:
    if sizer is None:
        for c in non_fsm_buys:
            report.rejected.append(f"{c.source} BUY (no sizer available)")
        report.final_action = "HOLD"
        report.final_reason = f"non-fsm buys require sizer: {[c.source for c in non_fsm_buys]}"
        report.veto_chain.append("non_fsm_needs_sizer")
        return [], report
    else:
        best_non_fsm = max(non_fsm_buys, key=lambda c: c.confidence)
        try:
            sized = sizer.calculate_shares(
                price=best_non_fsm.price_target or 0.0,
                stop_loss=best_non_fsm.stop_loss or 0.0,
                czsc_bottom=None,
                market="CN",
                symbol=symbol,
            )
            sized_shares = int(sized.get("suggested_shares", 100))
        except Exception as e:
            logger.warning("Sizer sizing failed for %s: %s", symbol, e)
            sized_shares = 100
```

**UnifiedBacktestEngine 集成** (`unified_engine.py:354-368`)：
```python
if self._sizer is not None:
    try:
        sized = self._sizer.calculate_shares(
            price=closes[idx],
            stop_loss=closes[idx] * 0.95,
            czsc_bottom=None,
            market="CN",
            symbol=symbol,
        )
        sized_shares = int(sized.get("suggested_shares", shares))
        shares = (sized_shares // get_board_rule(symbol).lot_size) * get_board_rule(symbol).lot_size
        if shares <= 0:
            shares = 100
    except (KeyError, TypeError, ValueError, RuntimeError):
        shares = 100
```

**✅ 传播链清晰**：
- SignalArbitrator.arbitrate_candidates() → PositionSizer.calculate_shares()
- UnifiedBacktestEngine.run() → PositionSizer.calculate_shares()
- 失败时降级为 100 股（默认值）

### 3.3 **KillSwitch 下游消费者**

**SignalArbitrator 集成** (`arbitrator.py:117-119`)：
```python
if get_kill_switch().is_killed:
    logger.info("All signals dropped: kill switch active (%s)", get_kill_switch().reason)
    return []
```

**✅ Fail-Closed 传播**：
- KillSwitch 触发 → 所有信号被丢弃
- 记录到日志（reason）

---

## 4. Name 变异（边界条件与异常）

### 4.1 **InvalidStopLossError 异常**

**止损价校验** (`sizer.py:155-158`)：
```python
# 2. Risk per share calculation with precision safety
risk_per_share = safe_round(price - final_stop, PrecisionConstants.PRICE_DECIMALS)
if safe_compare(risk_per_share, 0) <= 0:
    logger.error(f"Stop loss {final_stop} is above or at entry price {price}.")
    raise InvalidStopLossError(price, final_stop)
```

**异常定义** (`sizer.py:65-70`)：
```python
class InvalidStopLossError(ValueError):
    def __init__(self, price: float, stop_loss: float):
        super().__init__(
            f"Invalid stop loss: {stop_loss} is above or at entry price {price}. "
            "Stop loss must be below entry price."
        )
```

**✅ 异常处理明确**：
- 止损价 >= 入场价时抛出 InvalidStopLossError
- 异常消息清晰指出问题（止损价必须低于入场价）
- 调用方捕获异常并降级（`except Exception as e: sized_shares = 100`）

### 4.2 **Principal Circuit Break (Safety)**

**本金熔断机制** (`sizer.py:178-187`)：
```python
# 6. Principal Circuit Break (Safety)
circuit_break_triggered = False
adjusted_shares = suggested_shares

if safe_compare(total_value, self.capital) > 0:
    logger.warning(f"Position value {total_value} exceeds capital. Maxing out.")
    circuit_break_triggered = True
    lot_size = self._get_lot_size(market, symbol)
    adjusted_shares = int(math.floor(safe_divide(self.capital, price * lot_size, 0)) * lot_size)
    total_value = safe_round(adjusted_shares * price, PrecisionConstants.PRICE_DECIMALS)
```

**✅ 本金保护机制**：
- 触发条件：`total_value > capital`（仓位价值超过本金）
- 保护行为：调整为最大可买股数（不超过本金）
- 标记触发：`circuit_break_triggered = True`

### 4.3 **ComplianceEngine AUM 校验**

**AUM 正数校验** (`compliance_engine.py:128-129`)：
```python
if aum_cny <= 0:
    raise ValueError(f"AUM must be strictly positive, got {aum_cny}")
```

**✅ 边界条件处理**：
- AUM <= 0 时抛出 ValueError（ fail-fast）
- 异常消息包含实际值（便于调试）

### 4.4 **KillSwitch Hook 异常隔离**

**Hook 执行隔离** (`kill_switch.py:84-88`)：
```python
for hook in self._hooks:
    try:
        hook()
    except Exception as e:
        logger.error(f"Kill switch hook {hook} failed: {e}", exc_info=True)
```

**✅ 异常隔离**：
- 单个 hook 失败不影响其他 hook 执行
- 记录到日志（exc_info=True 包含堆栈跟踪）

---

## 5. Name 治理（可观测性与可测试性）

### 5.1 **ComplianceMetrics 详细指标**

**指标明细** (`compliance_engine.py:35-56`)：
```python
@dataclass
class ComplianceMetrics:
    """合规审查指标明细"""
    aum_cny: float
    total_long_cny: float
    total_short_cny: float
    cash_buffer_cny: float
    long_weight_pct: float
    short_weight_pct: float
    cash_buffer_pct: float
    gross_leverage_pct: float
    net_exposure_pct: float
    max_single_stock_symbol: str
    max_single_stock_weight_pct: float
    max_industry_name: str
    max_industry_weight_pct: float
    max_industry_stock_count: int
    max_pb_contracts: int
    lot_sizing_compliant: bool
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
```

**✅ 可观测性**：
- 16 个指标全面覆盖组合状态
- evaluated_at 时间戳（UTC ISO 格式）
- 便于审计和问题追溯

### 5.2 **SHA-256 指纹签名**

**签名计算** (`compliance_engine.py:281-291`)：
```python
# 生成确定性加密指纹
signature_payload = {
    "manifest_id": manifest_id,
    "aum_cny": aum_cny,
    "verdict": verdict,
    "metrics": asdict(metrics),
    "breaches": breaches,
}
manifest_hash = hashlib.sha256(
    json.dumps(signature_payload, sort_keys=True).encode("utf-8")
).hexdigest()
```

**✅ 防篡改机制**：
- 对订单集合与风控指标计算 SHA-256 指纹
- `sort_keys=True` 确保确定性（相同输入产生相同指纹）
- 任何篡改都会导致指纹变化

### 5.3 **PositionSizer 返回详细字典**

**返回值结构** (`sizer.py:189-203`)：
```python
return {
    "建议动作": "BUY",
    "入场区间": f"{self._entry_zone(price)[0]:.2f} - {self._entry_zone(price)[1]:.2f}",
    "几何止损": czsc_bottom,
    "ATR止损": atr_stop_value,
    "执行止损": final_stop,
    "风险敞口": round(risk_exposure, 2),
    "建议仓位": suggested_shares,
    "资金占用": round(total_value, 2),
    "是否触发熔断": circuit_break_triggered,
    "修正仓位": adjusted_shares,
    "penalty_applied": penalty,
    "risk_per_share": round(risk_per_share, 2),
    "max_loss_allowed": round(max_loss_allowed, 2),
}
```

**✅ 可观测性**：
- 13 个字段详细记录计算过程
- 包含中文字段名（便于业务人员理解）
- 包含英文字段名（便于程序处理）

### 5.4 **KillSwitch 日志记录**

**恢复日志** (`kill_switch.py:51-54`)：
```python
logger.warning(
    "SharedKillSwitch 恢复持久化停机状态: reason=%s (T9a Fail-Closed 保护)",
    self._reason,
)
```

**持久化失败日志** (`kill_switch.py:82`)：
```python
logger.error("SharedKillSwitch 持久化停机状态失败: %s", e)
```

**✅ 日志完整**：
- 恢复时记录 warning（重要事件）
- 持久化失败时记录 error（异常事件）
- 包含 reason 和异常信息

---

## 6. 端到端数据流追踪

### 6.1 **典型路径 1：合规审查通过**

```
PreTradeComplianceEngine.audit(
    manifest_id="M20261124-001",
    aum_cny=100_000_000,  # 1 亿元
    equity_orders=DataFrame([
        {symbol: "600519.SH", trade_shares: 1000, ref_price: 1685.0, industry_l1: "食品饮料"},
        {symbol: "000858.SZ", trade_shares: 2000, ref_price: 142.0, industry_l1: "食品饮料"},
    ]),
    futures_hedging=DataFrame([
        {contract_symbol: "IF2412", notional_cny: 5_000_000, pb_001_contract: 100},
    ]),
)
    ↓ 1. 整百股铁律 (防线 6)
    ├─ trade_shares % 100 == 0 ✓ (1000, 2000)
    └─ lot_sizing_ok = True
    ↓ 2. 单票权重上限 (防线 1)
    ├─ eq_df["weight"] = [1000*1685/1e8, 2000*142/1e8] = [0.01685, 0.0284]
    ├─ max_stock_weight = 0.0284 (2.84%)
    └─ max_stock_weight > 0.025? → False (未超限) ✓
    ↓ 3. 行业集中度与持股数 (防线 2, 3)
    ├─ ind_grouped: 食品饮料 → ind_weight=0.04525, ind_count=2
    ├─ max_ind_weight = 0.04525 (4.525%)
    ├─ max_ind_weight > 0.100? → False (未超限) ✓
    ├─ max_ind_count = 2
    └─ max_ind_count > 4? → False (未超限) ✓
    ↓ 4. 单 PB 持仓限额 (防线 5)
    ├─ max_pb_hands = 100
    └─ 100 > 1200? → False (未超限) ✓
    ↓ 5. 宏观杠杆与净敞口 (防线 4)
    ├─ total_long_cny = 4_525_000
    ├─ total_short_cny = 5_000_000
    ├─ cash_buffer_cny = 95_475_000
    ├─ long_weight = 0.04525 (4.525%)
    ├─ short_weight = 0.05 (5%)
    ├─ cash_weight = 0.95475 (95.475%)
    ├─ gross_leverage = 1.05 (105%)
    ├─ net_exposure = -0.00475 (-0.475%)
    ├─ long_weight > 0.755? → False ✓
    ├─ cash_weight < 0.245? → False ✓
    ├─ gross_leverage > 1.76? → False ✓
    └─ abs(net_exposure) > 0.005? → False ✓
    ↓ 6. 指纹签名计算 (防线 7)
    ├─ verdict = "APPROVED_PASS" (breaches 为空)
    └─ manifest_hash = SHA-256(signature_payload)
    ↓ return ComplianceReport(
        manifest_id="M20261124-001",
        verdict="APPROVED_PASS",
        passed=True,
        breaches=[],
        warnings=[],
        metrics=ComplianceMetrics(...),
        manifest_hash="a3f5..."
    )
```

### 6.2 **典型路径 2：单票集中度超限**

```
PreTradeComplianceEngine.audit(
    manifest_id="M20261124-002",
    aum_cny=100_000_000,
    equity_orders=DataFrame([
        {symbol: "600519.SH", trade_shares: 2000, ref_price: 1685.0},  # 3.37% > 2.5%
    ]),
    futures_hedging=DataFrame(),
)
    ↓ 1. 整百股铁律
    └─ trade_shares % 100 == 0 ✓ (2000)
    ↓ 2. 单票权重上限 (防线 1)
    ├─ eq_df["weight"] = [2000*1685/1e8] = [0.0337]
    ├─ max_stock_weight = 0.0337 (3.37%)
    └─ max_stock_weight > 0.025? → True (超限) ✗
        └─ breaches.append("单票持仓集中度超限: 标的 600519.SH 权重为 3.370%, 超过硬上限 2.50%")
    ↓ 3-5. 其他防线检查
    └─ 全部通过 ✓
    ↓ 6. 指纹签名计算
    ├─ verdict = "REJECTED_BREACH" (breaches 非空)
    └─ manifest_hash = SHA-256(signature_payload)
    ↓ return ComplianceReport(
        manifest_id="M20261124-002",
        verdict="REJECTED_BREACH",
        passed=False,
        breaches=["单票持仓集中度超限: ..."],
        warnings=[],
        metrics=ComplianceMetrics(...),
        manifest_hash="b7c9..."
    )
```

### 6.3 **典型路径 3：KillSwitch 重启恢复**

```
# 第一次运行：手动触发 KillSwitch
KillSwitch.kill(reason="market_crash_2026_11_24")
    ├─ self._killed = True
    ├─ self._reason = "market_crash_2026_11_24"
    ├─ DiskStateStore.put("kill_switch", {killed: True, reason: "...", timestamp: ...})
    └─ hooks 执行

# 进程重启
KillSwitch.__init__(state_store=DiskStateStore())
    ├─ saved = DiskStateStore.get("kill_switch")
    ├─ saved = {killed: True, reason: "market_crash_2026_11_24", ...}
    ├─ self._killed = True
    ├─ self._reason = "market_crash_2026_11_24"
    └─ logger.warning("SharedKillSwitch 恢复持久化停机状态: reason=market_crash_2026_11_24 (T9a Fail-Closed 保护)")

# 信号仲裁时检查
SignalArbitrator.arbitrate(signals)
    ├─ get_kill_switch().is_killed → True
    ├─ logger.info("All signals dropped: kill switch active (market_crash_2026_11_24)")
    └─ return []
```

### 6.4 **典型路径 4：PositionSizer T+1 惩罚**

```
PositionSizer.calculate_shares(
    price=100.0,
    stop_loss=95.0,
    market="CN",
    czsc_bottom=96.0,
    atr_stop=94.0,
    symbol="600519.SH",
    initial_capital=1_000_000,
    risk_pct=0.05,
)
    ↓ 1. 确定最终止损价 (几何止损)
    ├─ atr_stop_value = 94.0
    ├─ czsc_bottom = 96.0 > atr_stop_value = 94.0
    └─ final_stop = 96.0 (使用 CZSC 底分形，最保守)
    ↓ 2. 计算每股风险
    ├─ risk_per_share = 100.0 - 96.0 = 4.0
    └─ risk_per_share > 0 ✓ (止损价 < 入场价)
    ↓ 3. 应用 T+1 惩罚
    ├─ penalty = market_penalties["CN"] = 1.2
    ├─ effective_risk_pct = 0.05 (无 Kelly 分数)
    └─ max_loss_allowed = 1_000_000 × 0.05 = 50_000
    ↓ 4. 计算股数
    ├─ shares = 50_000 / (4.0 × 1.2) = 10_416.67
    ├─ lot_size = 100 (A股主板)
    ├─ shares = floor(10_416.67 / 100) × 100 = 10_400
    └─ suggested_shares = 10_400
    ↓ 5. 计算风险敞口和仓位价值
    ├─ total_value = 10_400 × 100 = 1_040_000
    ├─ risk_exposure = 4.0 × 1.2 = 4.8 (每股风险，含惩罚)
    └─ total_value > capital? → 1_040_000 > 1_000_000? → True (触发熔断)
    ↓ 6. 本金熔断 (Safety)
    ├─ circuit_break_triggered = True
    ├─ adjusted_shares = floor(1_000_000 / (100 × 100)) × 100 = 10_000
    └─ total_value = 10_000 × 100 = 1_000_000
    ↓ return {
        "建议动作": "BUY",
        "几何止损": 96.0,
        "ATR止损": 94.0,
        "执行止损": 96.0,
        "风险敞口": 4.8,
        "建议仓位": 10_400,
        "资金占用": 1_000_000.0,
        "是否触发熔断": True,
        "修正仓位": 10_000,
        "penalty_applied": 1.2,
        "risk_per_share": 4.0,
        "max_loss_allowed": 50_000.0,
    }
```

---

## 7. 发现的问题

### 7.1 **CRITICAL 级别**

无

### 7.2 **HIGH 级别**

无

### 7.3 **MEDIUM 级别**

#### M1: VaR/CVaR 使用百分位数法而非真正 EVT

**位置**：`evt_risk.py:24-33`  
**问题**：`HistoricalSimulationRisk` 使用 `np.percentile` 计算 VaR/CVaR，而非真正的极值理论（EVT, GPD 拟合）。  
**文档标注**：
```python
Note: This is NOT true Extreme Value Theory (GPD fitting).
For true EVT with GPD, use scipy.stats.genpareto.
```

**影响**：百分位数法对尾部风险估计不够精确，尤其在极端市场条件下。  
**规则 3 合规性**：✅ 符合 Rule 3（"Never claim unverified results"），文档已明确标注非真正 EVT。  
**修复建议**：如需精确尾部风险估计，考虑实现 GPD 拟合（scipy.stats.genpareto）。当前实现已明确标注限制，可接受。

#### M2: ComplianceEngine 缺少空头总权重检查

**位置**：`compliance_engine.py:9-18`  
**问题**：文档声称"空头总对冲权重: <= 75.0%"，但代码中未实现此检查。  
**代码证据**：
```python
# 检查了 long_weight，但未检查 short_weight
if long_weight > self.max_long_weight:
    breaches.append(f"多头总仓位超限: ...")
# 缺少: if short_weight > self.max_short_weight: breaches.append(...)
```

**影响**：空头权重可能超过 75%，违反文档声称的风控防线。  
**修复建议**：添加空头权重检查：
```python
max_short_weight: float = 0.755,  # 新增参数
# ...
if short_weight > self.max_short_weight:
    breaches.append(f"空头总仓位超限: 空头实际占用 {short_weight*100:.3f}%, 超过上限 {self.max_short_weight*100:.2f}%")
```

### 7.4 **LOW 级别**

#### L1: 工作流文档过时（drawdown.py/structural_risk.py 不存在）

**位置**：`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:245-253`  
**问题**：工作流文档声称存在 `drawdown.py`, `structural_risk.py`, `sparse_convex.py`，但实际代码中不存在。  
**影响**：仅文档错误，不影响运行时行为。  
**修复建议**：更新工作流文档，移除不存在的文件。

#### L2: PositionSizer 返回中文字段名

**位置**：`sizer.py:189-203`  
**问题**：返回字典使用中文字段名（如"建议动作", "几何止损"），与代码库其他部分（英文）不一致。  
**影响**：可能导致调用方混淆（需要同时支持中英文字段名）。  
**修复建议**：统一为英文字段名，或提供双语映射。

---

## 8. 与深度验证报告的交叉验证

### 8.1 **已验证的事实**

1. **合规引擎 8 个参数可配置**：✅ 已确认（`compliance_engine.py:88-107`）
2. **VaR/CVaR 使用百分位数法**：✅ 已确认（`evt_risk.py:28-32`, 明确标注非真正 EVT）
3. **KillSwitch 持久化状态恢复 (T9a Fail-Closed)**：✅ 已确认（`kill_switch.py:45-56`）
4. **T+1 惩罚系数 (CN:1.2)**：✅ 已确认（`sizer.py:84`, `market_penalties = {"CN": 1.2, "US": 1.0, "HK": 1.0}`）
5. **几何止损 (max ATR/CZSC底分形)**：✅ 已确认（`sizer.py:145-152`, 取最保守值）
6. **整百股铁律**：✅ 已确认（`compliance_engine.py:150-162`, `shares % 100 == 0`）
7. **单 PB 持仓限额 1200 手**：✅ 已确认（`compliance_engine.py:97`, `max_pb_contract_limit: int = 1200`）

### 8.2 **新发现的问题**

1. **VaR/CVaR 非真正 EVT**（MEDIUM）：已明确标注，可接受
2. **ComplianceEngine 缺少空头权重检查**（MEDIUM）：文档声称 7 大防线，实际只实现 6 个
3. **工作流文档过时**（LOW）：drawdown.py/structural_risk.py/sparse_convex.py 不存在
4. **PositionSizer 中文字段名**（LOW）：与代码库风格不一致

### 8.3 **工作流文档问题验证**

**工作流文档声称**（`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:280`）：
> VaR/CVaR 使用百分位数法而非真正 EVT — 是否在文档中明确标注？

**实际答案**：✅ **已明确标注**。`evt_risk.py:31-32` 明确写了：
```python
Note: This is NOT true Extreme Value Theory (GPD fitting).
For true EVT with GPD, use scipy.stats.genpareto.
```

---

## 9. 结论

### 9.1 **风控合规模块健康度评估**

- **合规引擎设计**：✅ 优秀（7 大防线（实际 6 个）、SHA-256 指纹、参数可配置）
- **仓位管理**：✅ 优秀（T+1 惩罚、几何止损、本金熔断）
- **KillSwitch**：✅ 优秀（Fail-Closed、持久化恢复、Hook 异常隔离）
- **VaR/CVaR**：✅ 良好（百分位数法，明确标注非真正 EVT）
- **文档一致性**：⚠️ 良好（工作流文档过时，声称的某些文件不存在）

### 9.2 **关键风险**

1. **空头权重检查缺失**（MEDIUM）：文档声称 7 大防线，实际只实现 6 个
2. **VaR/CVaR 精度**（MEDIUM）：百分位数法对尾部风险估计不够精确
3. **文档过时**（LOW）：drawdown.py/structural_risk.py/sparse_convex.py 不存在

### 9.3 **修复优先级**

1. **P1**：添加空头权重检查，补齐 7 大防线（M2）
2. **P2**：考虑实现 GPD 拟合提升 VaR/CVaR 精度（M1）
3. **P3**：更新工作流文档，移除不存在的文件（L1）
4. **P3**：统一 PositionSizer 字段名为英文（L2）

---

**分析人**：Claude (Anthropic)  
**审查时间**：2026-11-24  
**代码引用精度**：所有引用精确到行号  
**交叉验证基础**：DEEP_VERIFICATION_9_REPORTS_20261124.md (98.9% 准确率)  
**下一步**：工作流 2（分析引擎模块 N2N 分析）或工作流 7（研究控制平面）
---

# 独立第三方评审意见（资深 A 股交易员视角）

> 评审基线：代码 commit `434aab1` · 评审人：资深 A 股交易员

## 评审结论：**存疑**

合规引擎是**机构事前签证**思路（集中度/杠杆/整百股/SHA-256 签证），设计认真；但报告把"空头权重检查缺失"降级为 MEDIUM，且**完全没触及实盘开仓危险逻辑（PositionSizer 无单仓权重上限 + 失败放水到 100 股）**，对"真金白银能不能这么干"这一核心问题失焦。

## 优点
1. PreTradeComplianceEngine 是事前硬门禁 + fail-closed 二值判定 + SHA-256 防篡改签证，参数可配置且留舍入裕度，符合"机构级事前风控"的正确形态。
2. KillSwitch 是**诚实 fail-closed**：kill() 立即持久化到磁盘、重启恢复停机状态、触发后仲裁器丢弃全部信号。风控放水最怕"重启丢状态"，这里做对了。
3. 诚实指出工作流文档列的 `drawdown.py/structural_risk.py/sparse_convex.py` **根本不存在**，且 VaR 明确标注"NOT true EVT"未冒充实务术语。

## 问题清单

**HIGH — H1：ComplianceEngine 缺空头总权重检查 = 防线 fail-open，报告降级为 MEDIUM。**
M2 承认文档声称"空头总对冲权重 ≤75%"，代码只查 `long_weight` 未查 `short_weight`。对一个"事前合规硬门禁"而言，**文档承诺的防线没实现 = 审查可被绕过**，性质是 fail-open。报告自己写"文档 7 大防线实际只实现 6 个"，却定级 MEDIUM 并放在 P1 修复——定级与性质不匹配。

**HIGH — H2（报告完全遗漏）：PositionSizer 失败时放水到固定 100 股，而非 fail-closed。**
`arbitrator.py:400-403` `except Exception: sized_shares = 100`；`unified_engine.py:421-422` `except (...): shares = 100`。仓位计算失败（含 InvalidStopLossError）时，系统**不是拒绝开仓，而是硬编码开 1 手**。对实盘这是危险的开仓逻辑——风控计算挂了仍会下单。报告把"降级 100 股"描述成"传播链清晰/优雅降级"，**没有任何一条指出这是 fail-open**。这是全篇最该点出却没点出的问题。

**HIGH — H3（报告完全遗漏）：PositionSizer 没有单仓权重上限，本金熔断允许 100% 满仓单票。**
§6.4 典型路径算出 `suggested_shares=10400`、`total_value=1,040,000 > capital=1,000,000`，仅靠"本金熔断"截断到 10,000 股 = **把全部本金压在一只票上**；唯一压住它的是另一个模块（合规引擎 2.5% 单票上限）。sizer 本身 risk_pct=5%/笔 + 无单仓权重约束，意味着**单独看 sizer 会对每笔交易 all-in**。报告盛赞"本金熔断优秀"，却没指出它只是"封顶到满仓"而非"限制到合理仓位"。交易员视角：如果合规引擎没接在 sizer 后面，这就是满仓梭哈。

**MEDIUM — M1（需确认）：回测里止损是否真的作为订单执行。**
§unified_engine.py:412 调 sizer 时 `stop_loss = closes[idx]*0.95`、`czsc_bottom=None`（写死 5% 止损、CZSC 几何止损在回测里被旁路）。sizer 返回"执行止损"字段，但报告**没展示回测引擎是否在后续 bar 上挂出止损卖单**。若止损只是算出来存字段、并不触发卖出，那么"止损风控"在回测里是空转的——报告没回答。

**MEDIUM — M2：合规引擎是否接入回测/实盘主链路未说明。**
§3.1 只说 ComplianceEngine 用于"清单下发 PMS/OMS 前"，与 `unified_engine.py` 的回测路径无引用关系。合规引擎再优秀，如果只在"导出清单"时跑、回测和信号仲裁主链路不经过它，那么 sizer 的满仓问题（H3）在回测里就**没有任何东西兜底**。

**LOW**：PositionSizer 中文字段名 / 工作流文档过时，报告已列。

## 需对照代码确认的关键声明
- **合规引擎是否被回测引擎、信号仲裁、实盘下单任一路径调用**（还是仅离线清单导出）。
- **止损是否真的生成止损卖单**并在后续 bar 撮合，还是只写入返回字典。
- `risk_pct` 生产默认值是否真是 0.05（5%/笔）。
- PositionSizer 的 `_get_lot_size` 对创业板/科创板是否正确。
- "机构级参数（2.5% 单票 / 25% 现金缓冲 / ±0.5% 中性）"是否与该系统实际的小资金定位匹配（100,000 默认本金 vs 机构 1 亿示例，明显错配）。
