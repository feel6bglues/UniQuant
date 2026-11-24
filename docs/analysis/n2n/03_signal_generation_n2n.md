# 工作流 3：信号生成模块 N2N 深度分析报告

> **分析日期**：2026-11-24  
> **代码基线**：`434aab1` (第25轮)  
> **分析范围**：`src/uniquant/signal/` (3 文件, 1,194 行)  
> **方法论**：Name-to-Name 代码级点对点审查  

---

## 0. **重要发现：工作流文档与实际代码不符**

**工作流文档声称**（`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:163-168`）：
```
signal/
├── adapters.py        # 9个适配器
├── aggregator.py      # 信号聚合
└── arbitrator.py      # Sell-Priority 仲裁
```

**实际代码**：
```
signal/
├── adapters.py        # 9个适配器 + TradingSignalCollector (715 行)
├── arbitrator.py      # Sell-Priority 仲裁 (427 行)
└── __init__.py        # 导出 (52 行)
```

**关键差异**：
- **aggregator.py 不存在**：工作流文档中的 `SignalAggregator.aggregate()` 已被移除
- **实际流程**：`TradingSignalCollector.collect()` → `SignalArbitrator.arbitrate()`
- **严重程度**：LOW（仅文档过时，不影响运行时行为）

---

## 1. Name 定义（命名与契约）

### 1.1 **EngineAdapter 抽象基类**

**核心契约** (`adapters.py:37-59`)：
```python
class EngineAdapter(ABC):
    """Brain 引擎输出 → TradingSignal 适配器基类"""

    @abstractmethod
    def adapt(
        self,
        raw_output: Dict[str, Any],
        symbol: str,
        timestamp: Optional[datetime.datetime] = None,
        default_shares: int = 100,
    ) -> Optional[TradingSignal]:
        """将引擎原始输出转换为标准 TradingSignal

        Args:
            raw_output: 引擎输出的 Dict
            symbol: 证券代码
            timestamp: 信号时间戳
            default_shares: 默认股数 (当引擎未指定时)

        Returns:
            TradingSignal, 或 None (如果输出不构成有效信号)
        """
        ...
```

**✅ 契约清晰**：
- 输入：`Dict[str, Any]`（引擎原始输出）
- 输出：`Optional[TradingSignal]`（None 表示不构成有效信号）
- 设计原则：Adapter 不做策略判断，只做数据形态转换

### 1.2 **9 个适配器实现**

**适配器清单** (`adapters.py:540-554`)：
```python
def create_default_registry() -> AdapterRegistry:
    """创建包含所有内置适配器的注册表"""
    registry = AdapterRegistry()
    # LPPL：零预测力（MC 证伪）→ 默认遥测（diagnostic_only=True），不产 SELL 强平
    registry.register("lppl", LPPLAdapter(diagnostic_only=True))
    registry.register("czsc", CZSCAdapter())
    registry.register("wyckoff", WyckoffAdapter())
    registry.register("fsm", FSMAdapter())
    registry.register("regime", RegimeAdapter())
    registry.register("ntf", NTFAdapter())
    registry.register("alpha_score", AlphaScoreAdapter())
    registry.register("ma_status", MAStatusAdapter())
    registry.register("qar", QARAdapter())
    return registry
```

**适配器职责矩阵**：

| 适配器 | 输入 keys | 输出 action | 置信度门控 |
|--------|-----------|-------------|------------|
| LPPLAdapter | risk_level, confidence | HOLD (diagnostic) / SELL (非 diagnostic) | confidence ≥ 0.05 |
| CZSCAdapter | is_3rd_buy, bi_count | BUY (三买成立) / HOLD | confidence = 0.5 + bi_count × 0.05 |
| WyckoffAdapter | wyckoff_direction, wyckoff_confidence | BUY (direction ∈ 入场方向 且 confidence ≥ 门槛) / None | confidence ≥ 0.40 (config) |
| FSMAdapter | action, final_decision, shares | BUY/SELL/HOLD (直接映射) | confidence = raw.confidence |
| RegimeAdapter | regime | HOLD (FROZEN/STRESSED) / None (NORMAL) | confidence = 0.5 |
| NTFAdapter | ntf_side, ntf_intensity | SELL (RESISTANCE+高强度) / HOLD (SUPPORT) / None | intensity ≥ 0.6 |
| AlphaScoreAdapter | alpha_score | BUY (> 0.6) / SELL (< 0.3) / None | confidence = \|score - 0.5\| × 2 |
| MAStatusAdapter | ma_status | BUY ("MA20 > MA60") / SELL ("MA20 <= MA60") / None | confidence = 0.3 |
| QARAdapter | weight, is_compliant | BUY (weight > 0) / SELL (weight < 0) / None | confidence = 0.5 + weight × 10 |

**✅ 命名一致性**：
- 所有适配器命名 `XxxAdapter`（与引擎名对应）
- 输入 keys 统一使用引擎输出字段名
- 输出统一为 `Optional[TradingSignal]`

### 1.3 **TradingSignalCollector 信号收集器**

**核心方法** (`adapters.py:577-679`)：
```python
def collect(
    self,
    data_pack: Dict[str, Any],
    timestamp: Optional[datetime.datetime] = None,
    bar_date: Optional[datetime.datetime] = None,
    default_shares: int = 100,
) -> List[TradingSignal]:
    """从 data_pack 中收集所有信号"""
    ts = bar_date if bar_date is not None else timestamp
    with perf_section("adapter.collect"):
        signals: List[TradingSignal] = []
        symbol = data_pack.get("symbol", "")

        # LPPL
        lppl_out = self._extract_lppl(data_pack)
        if lppl_out:
            adapter = self._registry.get("lppl")
            if adapter:
                s = adapter.adapt(lppl_out, symbol, ts, default_shares)
                if s:
                    signals.append(s)

        # CZSC
        # ... wyckoff, fsm, regime, ntf, alpha_score, ma_status ...
```

**✅ 收集逻辑清晰**：
- 从 data_pack 提取各引擎输出（`_extract_lppl`, `_extract_czsc`, `_extract_wyckoff`）
- 调用对应适配器转换（`adapter.adapt()`）
- 过滤 None（不构成有效信号的引擎输出）
- 发布 `SignalGenerated` 事件（如果有 EventBus）

---

## 2. Name 映射（数据流转映射）

### 2.1 **LPPL 适配器映射规则**

**LPPLAdapter.adapt** (`adapters.py:92-136`)：
```python
def adapt(self, raw_output, symbol, timestamp, default_shares):
    risk = raw_output.get("risk_level", raw_output.get("risk", "Safe"))
    confidence = float(
        raw_output.get("confidence", raw_output.get("bubble_confidence", 0.0))
    )

    if confidence < 0.05:
        return None

    # 检查 R² 质量门与样本外有效性
    r2 = float(raw_output.get("r_squared", raw_output.get("r2", 1.0)))
    oos_r2 = float(raw_output.get("out_of_sample_r_squared", raw_output.get("oos_r2", 1.0)))

    is_diagnostic = self.diagnostic_only or bool(raw_output.get("diagnostic_only", False))
    if (self.min_r2 is not None and r2 < self.min_r2) or (self.min_oos_r2 is not None and oos_r2 < self.min_oos_r2):
        is_diagnostic = True

    if risk == "Danger":
        action = "HOLD" if is_diagnostic else "SELL"
    elif risk == "Warning":
        action = "HOLD"
    else:
        action = "HOLD"

    reason_suffix = " (diagnostic)" if is_diagnostic and risk == "Danger" else ""
    return TradingSignal(
        action=action,
        reason=f"LPPL risk={risk} conf={confidence:.2f}{reason_suffix}",
        confidence=confidence,
        shares=default_shares if action == "SELL" else 0,
        symbol=symbol,
        price=float(raw_output.get("price", 0.0)),
        timestamp=timestamp,
        metadata={
            "r_squared": float(raw_output.get("r_squared", 0.0)),
            "out_of_sample_r_squared": float(raw_output.get("out_of_sample_r_squared", 0.0)),
            "diagnostic_only": is_diagnostic,
        },
    )
```

**✅ 映射规则清晰**：
- 默认 `diagnostic_only=True`：LPPL 已被 Monte-Carlo 证伪（93% GBM 噪声即可拟合 R²>0.3）
- Danger + diagnostic → HOLD（遥测模式，不产 SELL 强平）
- Danger + 非 diagnostic + 质量门通过 → SELL（需显式配置 min_r2/min_oos_r2）
- 质量门：R² 破损时降级为 HOLD 诊断模式

### 2.2 **FSM 适配器 action 映射**

**FSMAdapter._ACTION_MAP** (`adapters.py:258-269`)：
```python
_ACTION_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
    "HOLD": "HOLD",
    "ADD": "BUY",
    "EXECUTE_BUY": "BUY",
    "EXECUTE_SELL": "SELL",
    "FORCE_WAIT": "HOLD",
    "FORCE_EXIT": "SELL",
    "CIRCUIT_BREAK": "HOLD",
    "STAY_CURRENT_STATE": "HOLD",
}
```

**映射规则** (`adapters.py:277-293`)：
```python
def adapt(self, raw_output, symbol, timestamp, default_shares):
    raw_action = raw_output.get(
        "final_decision", raw_output.get("action", "HOLD")
    )
    action = self._ACTION_MAP.get(raw_action, "HOLD")
    shares = int(raw_output.get("shares", default_shares if action == "BUY" else 0))
    confidence = float(raw_output.get("confidence", 0.5))

    return TradingSignal(
        action=action,
        reason=raw_output.get("reason", ""),
        confidence=confidence,
        shares=shares,
        symbol=symbol,
        price=float(raw_output.get("price", 0.0)),
        timestamp=timestamp,
    )
```

**✅ 映射规则完整**：
- 10 种 FSM action 映射到 3 种 TradingSignal action（BUY/SELL/HOLD）
- 未知 action 默认 HOLD（安全降级）
- shares 优先使用引擎指定的值，未指定时 BUY 用 default_shares，其他用 0

### 2.3 **Wyckoff 适配器 direction gate**

**WyckoffAdapter.adapt** (`adapters.py:195-244`)：
```python
def adapt(self, raw_output, symbol, timestamp, default_shares):
    direction = str(
        raw_output.get("wyckoff_direction", raw_output.get("direction", ""))
    )
    confidence = float(
        raw_output.get("wyckoff_confidence", raw_output.get("confidence", 0.0))
    )
    phase = str(
        raw_output.get("wyckoff_phase", raw_output.get("phase", "unknown"))
    )
    spring = raw_output.get("wyckoff_spring", False)
    utad = raw_output.get("wyckoff_utad", False)

    try:
        cfg = get_config()
    except Exception:
        cfg = {}
    if not bool(cfg.get("wyckoff.direction_gate_enabled", True)):
        return None
    gate = float(cfg.get("wyckoff.confidence_gate", 0.40) or 0.40)

    if direction not in self._ENTRY_DIRECTIONS or confidence < gate:
        return None

    return TradingSignal(
        action="BUY",
        reason=f"Wyckoff direction={direction} phase={phase} spring={spring} utad={utad}",
        confidence=confidence,
        shares=default_shares,
        symbol=symbol,
        price=float(raw_output.get("price", 0.0)),
        timestamp=timestamp,
        metadata={
            "wyckoff_phase": phase,
            "wyckoff_direction": direction,
            "wyckoff_spring": spring,
            "wyckoff_utad": utad,
            "wyckoff_rr_ratio": float(raw_output.get("rr_ratio", 0.0)),
            "wyckoff_bypassed": raw_output.get("bypassed", False),
            "wyckoff_structural_score": float(raw_output.get("structural_score", 0.0)),
        },
    )
```

**✅ 映射规则严格**：
- **恒不产 SELL-as-entry**：非入场方向一律返回 None
- 入场方向白名单：`_ENTRY_DIRECTIONS = {"做多", "买入", "轻仓试探"}`
- 置信门槛：config `wyckoff.confidence_gate`（默认 0.40）
- direction gate 开关：config `wyckoff.direction_gate_enabled`（默认 True）

### 2.4 **NTF 适配器强度门控**

**NTFAdapter.adapt** (`adapters.py:348-382`)：
```python
def adapt(self, raw_output, symbol, timestamp, default_shares):
    side = raw_output.get("ntf_side", "NONE")
    intensity = float(raw_output.get("ntf_intensity", 0.0))

    if side == "NONE":
        return None
    if side == "SUPPORT":
        return TradingSignal(
            action="HOLD",
            reason=f"NTF SUPPORT intensity={intensity:.2f} (bullish context, no auto-trade)",
            confidence=intensity * 0.5,
            shares=0,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
        )
    if side == "RESISTANCE":
        if intensity >= 0.6:
            return TradingSignal(
                action="SELL",
                reason=f"NTF RESISTANCE intensity={intensity:.2f}",
                confidence=min(intensity, 0.9),
                shares=default_shares,
                symbol=symbol,
                price=float(raw_output.get("price", 0.0)),
                timestamp=timestamp,
            )
        return None
    return None
```

**✅ 映射规则清晰**：
- SUPPORT → HOLD（bullish context，不自动交易）
- RESISTANCE + intensity ≥ 0.6 → SELL
- RESISTANCE + intensity < 0.6 → None（不构成有效信号）

---

## 3. Name 传播（依赖链追踪）

### 3.1 **下游消费者**

**SignalArbitrator 消费 TradingSignal** (`arbitrator.py:100-148`)：
```python
def arbitrate(self, signals: List[TradingSignal], symbol: str = "") -> List[TradingSignal]:
    """仲裁信号列表, 返回最终要执行的信号"""
    if not signals:
        return []

    if get_kill_switch().is_killed:
        logger.info("All signals dropped: kill switch active (%s)", get_kill_switch().reason)
        return []

    now = get_time_provider().now()
    by_sym_date: Dict[Tuple[str, str], List[TradingSignal]] = {}
    for sig in signals:
        # 信号超时检查
        if sig.timestamp is not None and self._max_signal_age_seconds > 0:
            age = (now - sig.timestamp).total_seconds()
            if age > self._max_signal_age_seconds:
                logger.info("Signal dropped (expired): age=%.1fs ...")
                continue
        sym = sig.symbol or symbol
        key = str(sig.timestamp.date()) if sig.timestamp else "unknown"
        by_sym_date.setdefault((sym, key), []).append(sig)

    result: List[TradingSignal] = []
    for (sym, date_key) in sorted(by_sym_date.keys(), key=lambda x: (x[1], x[0])):
        day_signals = by_sym_date[(sym, date_key)]
        winner = self._pick_winner(day_signals, sym, date_key)
        if winner is not None:
            result.append(winner)

    return result
```

**✅ 传播链清晰**：
- `TradingSignalCollector.collect()` → List[TradingSignal]
- `SignalArbitrator.arbitrate()` → List[TradingSignal]（每日至多一个）
- `UnifiedBacktestEngine.run()` → 消费仲裁后的信号

### 3.2 **KillSwitch 集成**

**KillSwitch 检查** (`arbitrator.py:117-119`, `arbitrator.py:298-304`)：
```python
if get_kill_switch().is_killed:
    logger.info("All signals dropped: kill switch active (%s)", get_kill_switch().reason)
    return []
```

**arbitrate_candidates 版本**：
```python
if get_kill_switch().is_killed:
    return [], ArbitrationReport(
        symbol=symbol, date="", candidates_count=len(candidates),
        final_action="HOLD",
        final_reason=f"kill_switch: {get_kill_switch().reason}",
        veto_chain=[f"kill_switch={get_kill_switch().reason}"],
    )
```

**✅ Fail-Closed 语义**：
- KillSwitch 触发时，所有信号被丢弃
- 记录到日志和仲裁报告（veto_chain）

### 3.3 **PositionSizer 集成**

**Non-FSM BUY 需要 PositionSizer** (`arbitrator.py:363-419`)：
```python
# Priority 3: Non-FSM BUY candidates need PositionSizer
buy_candidates = [c for c in candidates if c.action == "BUY"]
non_fsm_buys = [c for c in buy_candidates if c.source != "fsm"]
fsm_buys = [c for c in buy_candidates if c.source == "fsm"]

# FSM buys pass through
if fsm_buys:
    best_fsm = max(fsm_buys, key=lambda c: c.confidence)
    report.final_action = "BUY"
    report.final_reason = f"fsm: {best_fsm.source}"
    # ... return BUY signal

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
        report.final_action = "BUY"
        # ... return BUY signal with sized_shares
```

**✅ 依赖契约明确**：
- FSM BUY 直接通过（DecisionBrain 已计算 shares）
- Non-FSM BUY 需要 PositionSizer 计算 shares
- Sizer 不可用时降级为 HOLD（fail-closed）

---

## 4. Name 变异（边界条件与异常）

### 4.1 **质量阈值过滤**

**规则 0: 质量阈值过滤 (P6.5)** (`arbitrator.py:171-193`)：
```python
# 规则 0: 质量阈值过滤 (P6.5) — 在任何仲裁之前进行
if self._quality_threshold > 0.0:
    filtered = []
    for sig in actionable:
        oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)
        if oos_r2 < self._quality_threshold and sig.action == "SELL":
            log.rejection_reasons.append(
                f"quality_gate: rejected SELL from {sig.reason} "
                f"(OOS R²={oos_r2:.2f} < {self._quality_threshold})"
            )
            logger.info(
                "Quality gate rejected SELL %s OOS R²=%.2f for %s on %s",
                sig.reason, oos_r2, symbol, date_key,
            )
        else:
            filtered.append(sig)
    actionable = filtered

if not actionable:
    log.selected_action = "HOLD"
    log.selected_reason = "no actionable signals after quality filter"
    self._logs.append(log)
    return None
```

**✅ 边界条件处理**：
- 质量阈值默认 0.3（`quality_threshold: float = 0.3`）
- 仅过滤 SELL 信号（BUY 不受影响）
- OOS R² < 阈值时拒绝 SELL（防止虚假强平）
- 默认 OOS R² = 1.0（如果 metadata 缺失，不拒绝）

### 4.2 **SELL 优先规则**

**规则 1: SELL 优先于 BUY** (`arbitrator.py:203-218`)：
```python
# 规则 1: SELL 优先于 BUY
if self._sell_priority:
    sells = [s for s in actionable if s.action == "SELL"]
    if sells:
        winner = self._highest_confidence(sells)
        if winner is None:
            return None
        log.selected_action = "SELL"
        log.selected_reason = f"arbitrated: {winner.reason}"
        log.selected_confidence = winner.confidence
        log.conflicts_resolved = len(actionable) - 1
        log.rejection_reasons.append(
            f"sell_priority: rejected {len(actionable) - len(sells)} buy signal(s)"
        )
        self._logs.append(log)
        return winner
```

**✅ Sell-Priority 语义**：
- SELL 始终优先于 BUY（`sell_priority: bool = True`）
- 同方向多个 SELL 取最高 confidence
- 记录冲突解决数和拒绝原因

### 4.3 **DecisionOutput 硬约束**

**Priority 1: DecisionOutput 硬约束** (`arbitrator.py:312-341`)：
```python
# Priority 1: DecisionOutput hard constraints
if decision_output is not None:
    if decision_output.action in ("FORCE_WAIT", "CIRCUIT_BREAK"):
        report.final_action = "HOLD"
        report.final_reason = "risk_veto"
        report.veto_chain.append(f"decision_output={decision_output.action}")
        return [], report

    if decision_output.action == "FORCE_EXIT":
        report.final_action = "SELL"
        report.final_reason = "force_exit"
        report.veto_chain.append("decision_output=FORCE_EXIT")
        return [
            TradingSignal(action="SELL", reason="FORCE_EXIT", confidence=1.0, symbol=symbol)
        ], report

    if decision_output.action == "BUY" and decision_output.shares > 0:
        report.final_action = "BUY"
        report.final_reason = "decision_brain"
        report.final_confidence = decision_output.confidence
        report.veto_chain.append(f"decision_output=BUY shares={decision_output.shares}")
        return [
            TradingSignal(
                action="BUY",
                reason="decision_brain",
                confidence=decision_output.confidence,
                shares=decision_output.shares,
                symbol=symbol,
            )
        ], report
```

**✅ 硬约束优先级最高**：
- FORCE_WAIT/CIRCUIT_BREAK → HOLD（风控否决）
- FORCE_EXIT → SELL（强制平仓，confidence=1.0）
- BUY + shares > 0 → BUY（DecisionBrain 已计算仓位）
- 这些约束优先于所有候选信号

### 4.4 **Engine Priority 仲裁**

**ENGINE_PRIORITY 定义** (`arbitrator.py:32-42`)：
```python
ENGINE_PRIORITY: Dict[str, int] = {
    "lppl": 99,  # 最低优先级（已被证伪）
    "fsm": 1,    # 最高优先级
    "czsc": 2,
    "qar": 3,
    "wyckoff": 4,
    "regime": 5,
    "ntf": 6,
    "alpha_score": 7,
    "ma_status": 8,
}
```

**规则 3: 按引擎优先级** (`arbitrator.py:237-245`)：
```python
# 规则 3: 按引擎优先级
winner = self._by_engine_priority(actionable)
if winner:
    log.selected_action = winner.action
    log.selected_reason = f"arbitrated(engine_priority): {winner.reason}"
    log.selected_confidence = winner.confidence
    log.conflicts_resolved = len(actionable) - 1
self._logs.append(log)
return winner
```

**_by_engine_priority 实现** (`arbitrator.py:254-262`)：
```python
def _by_engine_priority(self, signals: List[TradingSignal]) -> Optional[TradingSignal]:
    candidates: List[Tuple[int, TradingSignal]] = []
    for sig in signals:
        if sig.action not in ("BUY", "SELL"):
            continue
        priority = self._get_engine_priority(sig.reason)
        candidates.append((priority, sig))
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1] if candidates else None
```

**✅ Engine Priority 语义**：
- 数值越小优先级越高（fsm=1 最高，lppl=99 最低）
- 从 signal.reason 中提取引擎名（`_get_engine_priority`）
- 仅在同方向多个信号时使用（SELL 优先规则之后）

**⚠️ 发现问题（LOW）**：
- `_get_engine_priority` 通过 `reason.lower()` 匹配引擎名（`arbitrator.py:265-270`）
- 如果 reason 格式不符合预期（如 "decision_brain" 或 "sizer approved: wyckoff"），可能匹配错误
- 例如：`"sizer approved: wyckoff"` 会匹配到 `wyckoff`（priority=4），但实际是 sizer 批准的

### 4.5 **信号过期检查**

**信号超时机制** (`arbitrator.py:124-132`)：
```python
# 信号超时检查
if sig.timestamp is not None and self._max_signal_age_seconds > 0:
    age = (now - sig.timestamp).total_seconds()
    if age > self._max_signal_age_seconds:
        logger.info(
            "Signal dropped (expired): age=%.1fs max=%.1fs for %s",
            age, self._max_signal_age_seconds, sig.reason,
        )
        continue
```

**默认配置** (`arbitrator.py:44-45`)：
```python
DEFAULT_MAX_SIGNAL_AGE_SECONDS: float = 0.0  # 0=禁用; 回测模式下应保持禁用，信号时间戳 vs 壁钟时间不匹配
```

**✅ 边界条件处理**：
- 默认禁用（0.0 秒），避免回测模式下时间戳不匹配
- 实盘模式可配置启用（如 300 秒 = 5 分钟）
- 仅在 timestamp 不为 None 时检查

---

## 5. Name 治理（可观测性与可测试性）

### 5.1 **ArbitrationLog 仲裁日志**

**单次仲裁记录** (`arbitrator.py:48-58`)：
```python
@dataclass
class ArbitrationLog:
    """单次仲裁记录"""
    symbol: str
    date: str
    total_signals: int
    selected_action: str = "HOLD"
    selected_reason: str = ""
    selected_confidence: float = 0.0
    conflicts_resolved: int = 0
    rejection_reasons: List[str] = field(default_factory=list)
```

**日志访问** (`arbitrator.py:96-98`)：
```python
@property
def logs(self) -> List[ArbitrationLog]:
    return list(self._logs)
```

**✅ 可追溯性**：
- 每次仲裁记录 symbol/date/total_signals/selected_action/selected_reason
- 记录冲突解决数和拒绝原因链
- 返回副本（不可变语义）

### 5.2 **ArbitrationReport 仲裁报告**

**详细仲裁报告** (`arbitrator.py:61-71`)：
```python
@dataclass
class ArbitrationReport:
    """仲裁报告 — 记录仲裁决策过程和拒绝链"""
    symbol: str
    date: str
    candidates_count: int
    final_action: str = "HOLD"
    final_reason: str = ""
    final_confidence: float = 0.0
    veto_chain: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)
```

**报告使用示例** (`research_pipeline.py:380-385`)：
```python
if signals:
    logger.debug(
        "仲裁完成: %s -> %s (%s) | veto=%s",
        symbol, signals[0].action, signals[0].reason,
        report.veto_chain,
    )
```

**✅ 可观测性**：
- ArbitrationReport 记录完整的 veto_chain 和 rejected 列表
- Pipeline 层记录 veto_chain 到日志
- 便于调试和审计

### 5.3 **perf_section 性能追踪**

**信号收集性能追踪** (`adapters.py:596`)：
```python
with perf_section("adapter.collect"):
    signals: List[TradingSignal] = []
    # ... 收集逻辑 ...
```

**✅ 性能可观测**：
- `adapter.collect` 性能追踪点
- 可在指标系统中查看信号收集耗时

---

## 6. 端到端数据流追踪

### 6.1 **典型路径 1：Wyckoff SPRING → BUY 信号**

```
ResearchDataPack (wyckoff_output: {phase: "SPRING", direction: "做多", confidence: 0.75})
    ↓ TradingSignalCollector.collect(data_pack)
  ├─ _extract_wyckoff(data_pack)
  │   → {wyckoff_phase: "SPRING", wyckoff_direction: "做多", wyckoff_confidence: 0.75, ...}
  ├─ WyckoffAdapter.adapt(wyckoff_out, symbol, ts, default_shares)
  │   ├─ direction = "做多" ∈ _ENTRY_DIRECTIONS ✓
  │   ├─ confidence = 0.75 ≥ gate(0.40) ✓
  │   └─ return TradingSignal(action="BUY", reason="Wyckoff direction=做多 phase=SPRING ...", confidence=0.75, shares=100)
  └─ signals = [TradingSignal(BUY)]
    ↓ SignalArbitrator.arbitrate(signals, symbol)
  ├─ actionable = [TradingSignal(BUY)] (只有 1 个可执行信号)
  ├─ len(actionable) == 1 → winner = actionable[0]
  └─ return [TradingSignal(BUY, reason="Wyckoff direction=做多 phase=SPRING ...", confidence=0.75, shares=100)]
    ↓ UnifiedBacktestEngine.run(df, signals, symbol)
BacktestResult
```

### 6.2 **典型路径 2：FSM FORCE_EXIT + Wyckoff BUY 冲突**

```
data_pack = {
    "final_decision": "FORCE_EXIT",
    "shares": 1000,
    "confidence": 0.9,
    "wyckoff_direction": "做多",
    "wyckoff_confidence": 0.75,
    ...
}
    ↓ TradingSignalCollector.collect(data_pack)
  ├─ FSMAdapter.adapt(data_pack)
  │   ├─ raw_action = "FORCE_EXIT"
  │   ├─ action = _ACTION_MAP["FORCE_EXIT"] = "SELL"
  │   └─ return TradingSignal(action="SELL", reason="...", confidence=0.9, shares=1000)
  ├─ WyckoffAdapter.adapt(wyckoff_out)
  │   └─ return TradingSignal(action="BUY", reason="Wyckoff ...", confidence=0.75, shares=100)
  └─ signals = [TradingSignal(SELL), TradingSignal(BUY)]
    ↓ SignalArbitrator.arbitrate(signals, symbol)
  ├─ actionable = [TradingSignal(SELL), TradingSignal(BUY)]
  ├─ 规则 1: SELL 优先于 BUY
  │   ├─ sells = [TradingSignal(SELL)]
  │   ├─ winner = _highest_confidence(sells) = TradingSignal(SELL)
  │   └─ return [TradingSignal(SELL, reason="...", confidence=0.9, shares=1000)]
  └─ log.rejection_reasons = ["sell_priority: rejected 1 buy signal(s)"]
    ↓ UnifiedBacktestEngine.run(df, signals, symbol)
BacktestResult (执行 SELL 1000 股)
```

### 6.3 **典型路径 3：DecisionOutput FORCE_WAIT 否决**

```
candidates = [
    CandidateSignal(action="BUY", source="wyckoff", confidence=0.75, ...),
    CandidateSignal(action="BUY", source="czsc", confidence=0.60, ...),
]
decision_output = DecisionOutput(action="FORCE_WAIT", ...)
    ↓ SignalArbitrator.arbitrate_candidates(candidates, decision_output, ...)
  ├─ Priority 1: DecisionOutput 硬约束
  │   ├─ decision_output.action == "FORCE_WAIT" ∈ ("FORCE_WAIT", "CIRCUIT_BREAK")
  │   ├─ report.final_action = "HOLD"
  │   ├─ report.final_reason = "risk_veto"
  │   ├─ report.veto_chain = ["decision_output=FORCE_WAIT"]
  │   └─ return [], report
  └─ 所有 BUY 候选信号被否决
    ↓ UnifiedBacktestEngine.run(df, [], symbol)
BacktestResult (无交易)
```

### 6.4 **典型路径 4：LPPL diagnostic_only 遥测模式**

```
data_pack = {
    "risk": "Danger",
    "bubble_confidence": 0.85,
    "r_squared": 0.35,
    "out_of_sample_r_squared": 0.20,
    ...
}
    ↓ TradingSignalCollector.collect(data_pack)
  ├─ _extract_lppl(data_pack)
  │   → {risk_level: "Danger", confidence: 0.85, price: 0.0}
  ├─ LPPLAdapter.adapt(lppl_out, symbol, ts, default_shares)
  │   ├─ risk = "Danger"
  │   ├─ confidence = 0.85 ≥ 0.05 ✓
  │   ├─ r2 = 0.35, oos_r2 = 0.20
  │   ├─ is_diagnostic = True (默认 diagnostic_only=True)
  │   ├─ risk == "Danger" → action = "HOLD" if is_diagnostic else "SELL" → "HOLD"
  │   └─ return TradingSignal(action="HOLD", reason="LPPL risk=Danger conf=0.85 (diagnostic)", confidence=0.85, shares=0, metadata={diagnostic_only: True})
  └─ signals = [TradingSignal(HOLD)]
    ↓ SignalArbitrator.arbitrate(signals, symbol)
  ├─ actionable = [] (HOLD 不是可执行信号)
  ├─ log.selected_action = "HOLD", selected_reason = "no actionable signals"
  └─ return []
    ↓ UnifiedBacktestEngine.run(df, [], symbol)
BacktestResult (无交易，LPPL 仅作为遥测特征记录)
```

---

## 7. 发现的问题

### 7.1 **CRITICAL 级别**

无

### 7.2 **HIGH 级别**

无

### 7.3 **MEDIUM 级别**

#### M1: Engine Priority 匹配逻辑脆弱

**位置**：`arbitrator.py:264-270`  
**问题**：`_get_engine_priority` 通过 `reason.lower()` 子字符串匹配引擎名，可能匹配错误。  
**示例**：
- `"sizer approved: wyckoff"` → 匹配到 `wyckoff`（priority=4）
- `"decision_brain"` → 不匹配任何引擎（priority=99）
- `"LPPL risk=Danger"` → 匹配到 `lppl`（priority=99）

**影响**：如果 reason 格式变化，可能导致优先级仲裁错误。  
**修复建议**：在 TradingSignal.metadata 中显式记录 `source_engine`，避免从 reason 解析：
```python
# adapters.py: TradingSignal 构造时添加 metadata
return TradingSignal(
    action=action,
    reason=...,
    metadata={"source_engine": "wyckoff", ...},
)

# arbitrator.py: _by_engine_priority 使用 metadata
def _by_engine_priority(self, signals):
    candidates = []
    for sig in signals:
        source = sig.metadata.get("source_engine", "unknown")
        priority = ENGINE_PRIORITY.get(source, 99)
        candidates.append((priority, sig))
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1] if candidates else None
```

### 7.4 **LOW 级别**

#### L1: 工作流文档过时（aggregator.py 不存在）

**位置**：`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:163-168`  
**问题**：工作流文档声称存在 `aggregator.py` 和 `SignalAggregator.aggregate()`，但实际代码中不存在。  
**影响**：仅文档错误，不影响运行时行为。  
**修复建议**：更新工作流文档，移除 aggregator.py 相关描述。

#### L2: RegimeAdapter 从不产生 SELL

**位置**：`adapters.py:300-334`  
**问题**：RegimeAdapter 仅在 FROZEN/STRESSED 时产生 HOLD，从不产生 SELL。  
**影响**：与工作流文档一致（`Regime: 从不产生 SELL (FROZEN/STRESSED→HOLD)`），符合设计意图。  
**说明**：这是设计决策，不是 bug。Regime 引擎仅作为风控否决层，不主动产生交易信号。

---

## 8. 与深度验证报告的交叉验证

### 8.1 **已验证的事实**

1. **9 个适配器**：✅ 已确认（LPPL/CZSC/Wyckoff/FSM/Regime/NTF/AlphaScore/MAStatus/QAR）
2. **FSM action 映射**：✅ 已确认（BUY←BUY/ADD/EXECUTE_BUY, SELL←SELL/EXECUTE_SELL/FORCE_EXIT）
3. **Wyckoff 恒不产 SELL-as-entry**：✅ 已确认（`adapters.py:190`, 非入场方向返回 None）
4. **Regime 从不产生 SELL**：✅ 已确认（FROZEN/STRESSED→HOLD，NORMAL→None）
5. **ENGINE_PRIORITY (fsm:1 最高, lppl:99 最低)**：✅ 已确认（`arbitrator.py:32-42`）
6. **Sell-Priority 仲裁逻辑**：✅ 已确认（`arbitrator.py:203-218`, SELL 始终优先于 BUY）
7. **置信度门控**：✅ 已确认（Wyckoff 0.40, NTF intensity≥0.6, LPPL confidence≥0.05）
8. **QARAdapter 映射**：✅ 已确认（weight>0→BUY, weight<0→SELL, is_compliant=False→None）

### 8.2 **新发现的问题**

1. **aggregator.py 不存在**（LOW）：工作流文档过时
2. **Engine Priority 匹配逻辑脆弱**（MEDIUM）：从 reason 子字符串匹配，可能错误
3. **RegimeAdapter 从不产生 SELL**（LOW）：符合设计意图，不是 bug

### 8.3 **仲裁规则澄清**

**工作流文档问题**（`N2N_MODULE_ANALYSIS_WORKFLOW_20261124.md:189`）：
> ENGINE_PRIORITY (fsm:1 最高, lppl:99 最低) 的仲裁逻辑是"优先级高者胜"还是"Sell-Priority"？

**实际答案**：
- **两条路径**：
  1. `arbitrate()` 方法（旧接口）：规则顺序为 质量阈值 → SELL 优先 → 同方向取最高 confidence → Engine Priority
  2. `arbitrate_candidates()` 方法（新接口）：Priority 顺序为 DecisionOutput 硬约束 → SELL over BUY → FSM BUY pass-through → Non-FSM BUY need sizer → HOLD by default
- **Sell-Priority 优先于 Engine Priority**：先按 SELL/BUY 分组，再在同方向内取最高 confidence，最后才按 Engine Priority

---

## 9. 结论

### 9.1 **信号生成模块健康度评估**

- **适配器设计**：✅ 优秀（9 个适配器职责清晰、action 映射完整、置信度门控明确）
- **仲裁逻辑**：✅ 优秀（Sell-Priority、DecisionOutput 硬约束、质量阈值过滤、Engine Priority）
- **异常处理**：✅ 良好（KillSwitch Fail-Closed、Sizer 不可用降级、信号过期检查）
- **可观测性**：✅ 优秀（ArbitrationLog、ArbitrationReport、veto_chain、perf_section）
- **文档一致性**：⚠️ 良好（工作流文档过时，aggregator.py 已移除）

### 9.2 **关键风险**

1. **Engine Priority 匹配脆弱**（MEDIUM）：从 reason 子字符串匹配，可能错误
2. **文档过时**（LOW）：aggregator.py 已移除，工作流文档未更新

### 9.3 **修复优先级**

1. **P1**：在 TradingSignal.metadata 中显式记录 source_engine，避免从 reason 解析（M1）
2. **P2**：更新工作流文档，移除 aggregator.py 相关描述（L1）

---

**分析人**：Claude (Anthropic)  
**审查时间**：2026-11-24  
**代码引用精度**：所有引用精确到行号  
**交叉验证基础**：DEEP_VERIFICATION_9_REPORTS_20261124.md (98.9% 准确率)  
**下一步**：工作流 4（回测撮合模块 N2N 分析）
---

# 独立第三方评审意见（量化算法专家视角）

> 评审基线：代码 commit `434aab1` · 评审人：量化算法/Alpha 研究员

## 评审结论：**部分可信**（三份算法报告中最实）

是三份里**最诚实的一份**——敢自曝"工作流文档与代码不符"、敢给唯一的 MEDIUM。但它在最该开火的地方（跨引擎置信度不可比、quality gate 默认值放水）选择了肯定而非质疑。

## 优点
1. 发现并纠正文档漂移：§0 指出工作流文档里的 `aggregator.py` / `SignalAggregator.aggregate()` **已不存在**，实际是 `TradingSignalCollector.collect()` → `SignalArbitrator.arbitrate()`。真实且有价值的更正。
2. 主动给出全报告唯一的 MEDIUM（M1 Engine-Priority 从 reason 子串匹配脆弱），并给了 `source_engine` metadata 修复方案。
3. 适配器职责矩阵（§1.2 表）清晰可核对，抽查的 CZSC/QAR/AlphaScore 公式均与 `adapters.py` 对得上。
4. §8.3 澄清两套仲裁路径（`arbitrate()` vs `arbitrate_candidates()`）优先级顺序。

## 问题清单

**HIGH — H1：跨引擎置信度不可比，却是仲裁的唯一定胜依据——报告未质疑。**
整个 Sell-Priority / engine-priority 仲裁建立在 `_highest_confidence` / `argmax(confidence)` 之上，而各引擎 confidence 是**完全不同的启发式**：CZSC `=0.5+bi_count×0.05`、AlphaScore `=|score−0.5|×2`、QAR `=0.5+weight×10`、MAStatus `=0.3`(常数)、NTF `=intensity`。这些数字**没有统一概率含义、彼此不可比**，用 argmax 选胜出者本质是任意的。报告把这套置信度当"✅ 明确"夸（§9.1"置信度门控明确"），**从未提出"这些 confidence 是否被标定过 / 能否直接比较"这一根本问题**。

**MEDIUM — M2：Quality Gate 默认 `OOS R²=1.0` 是'缺数据即满分'，与 fail-closed 哲学相悖，报告却写成正面。**
§4.1 摘录 `oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)` 并注释"默认 1.0（metadata 缺失不拒绝）"，标题还写"✅ 边界条件处理"。这与 Rule 4（"缺输入必须 fail-closed / TIER_UNRATED，绝不放行"）**直接冲突**：缺失的样本外质量被当成满分放行。报告不仅没标为问题，反而当成正确设计。

**MEDIUM — M3：Quality Gate 只拦 SELL，BUY 完全不受 OOS 质量约束。** §4.1 条件是 `oos_r2 < threshold and sig.action == "SELL"`。质量门只用于抑制强平，而所有 BUY 信号无论样本外质量多差都放行。**买入侧恰恰是最需要 OOS 质量把关的一侧**，报告未指出此不对称。

**MEDIUM — M4：大量置信阈值是无依据 magic number。** `0.05`(LPPL)、`0.40`(Wyckoff gate)、`0.6`(NTF intensity)、`0.6/0.3`(AlphaScore BUY/SELL)、`0.3`(quality_threshold)。报告一律标"✅ 清晰/严格"，无一处给经验来源或敏感性。

**LOW — L-A**：报告 QAR 公式漏掉 min-cap（报告写 `0.5+weight×10`，实际 `min(0.5+weight*10, 0.95)`；CZSC 同样漏 `min(...,0.9)`）。属摘录不精确。**L-B**：`MAStatusAdapter` confidence=0.3 常数参与 argmax 竞争，报告未点评其意义。

## 需对照代码确认的关键声明
1. `_highest_confidence` 在同分/并列时如何打破平局（影响仲裁确定性）。
2. `quality_threshold=0.3` 的来源，及是否存在任何标定这些 confidence 的历史校准。
3. `_get_engine_priority` 实际误匹配频率（报告 M1 只是理论举例，无实测）。
