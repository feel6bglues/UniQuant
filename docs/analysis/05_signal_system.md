# 阶段 5：UniQuant 信号系统分析

> **分析时间**：2026-11-24  
> **依赖阶段**：阶段0-4  
> **核心文件**：`signal/adapters.py`, `signal/arbitrator.py`, `shared/interfaces.py`

---

## 1. 信号系统架构总览

### 1.1 信号流转路径

```mermaid
graph LR
    A[Brain引擎输出<br/>Dict[str, Any]] --> B[EngineAdapter.adapt<br/>9个适配器]
    B --> C[TradingSignalCollector.collect<br/>信号收集]
    C --> D[List[TradingSignal]]
    D --> E[SignalArbitrator.arbitrate<br/>信号仲裁]
    E --> F[最终信号<br/>List[TradingSignal]]
    
    subgraph 可选
    G[Kill Switch<br/>紧急停止]
    H[PositionSizer<br/>仓位计算]
    end
    
    G -.-> E
    H -.-> E
```

### 1.2 核心组件

| 组件 | 职责 | 关键方法 |
|---|---|---|
| `EngineAdapter` | 抽象基类，定义适配器接口 | `adapt()` |
| `AdapterRegistry` | 适配器注册表（自动发现+手动注册） | `register()`, `discover()` |
| `TradingSignalCollector` | 从data_pack收集所有信号 | `collect()` |
| `SignalArbitrator` | 信号仲裁（解决多引擎冲突） | `arbitrate()`, `arbitrate_candidates()` |

---

## 2. TradingSignal数据结构

### 2.1 核心字段

```python
@dataclass
class TradingSignal:
    action: str              # BUY/SELL/HOLD
    reason: str              # 信号原因
    confidence: float        # 置信度 (0.0-1.0)
    shares: int              # 股数
    symbol: str              # 证券代码
    price: float             # 价格
    timestamp: Optional[datetime]  # 时间戳
    metadata: Dict[str, Any] # 元数据
```

### 2.2 字段约束

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `action` | str | BUY/SELL/HOLD | 交易动作 |
| `confidence` | float | 0.0-1.0 | 置信度 |
| `shares` | int | ≥0 | 股数（A股100股整数倍） |
| `price` | float | >0 | 价格 |
| `timestamp` | datetime | 可选 | 回测时使用bar_date |

---

## 3. 9个引擎适配器详解

### 3.1 LPPLAdapter（泡沫检测）

```python
class LPPLAdapter(EngineAdapter):
    """
    默认 diagnostic_only=True（遥测优先）
    LPPL已被Monte-Carlo证伪为零预测力引擎
    （93% GBM噪声即可拟合 R²>0.3）
    """
    
    def __init__(self, diagnostic_only=True, min_r2=None, min_oos_r2=None):
        self.diagnostic_only = diagnostic_only  # 默认True
    
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        risk = raw_output.get("risk_level", "Safe")
        confidence = float(raw_output.get("confidence", 0.0))
        
        if confidence < 0.05:
            return None
        
        # R²质量门
        r2 = float(raw_output.get("r_squared", 1.0))
        oos_r2 = float(raw_output.get("out_of_sample_r_squared", 1.0))
        
        is_diagnostic = self.diagnostic_only
        if (self.min_r2 and r2 < self.min_r2) or (self.min_oos_r2 and oos_r2 < self.min_oos_r2):
            is_diagnostic = True
        
        if risk == "Danger":
            action = "HOLD" if is_diagnostic else "SELL"
        else:
            action = "HOLD"
        
        return TradingSignal(
            action=action,
            confidence=confidence,
            shares=default_shares if action == "SELL" else 0,
            metadata={"r_squared": r2, "out_of_sample_r_squared": oos_r2, "diagnostic_only": is_diagnostic}
        )
```

**关键特性**：
- ✅ 默认diagnostic_only=True（仅遥测，不参与强平）
- ✅ R²质量门（min_r2, min_oos_r2）
- ✅ 低置信度过滤（<0.05返回None）

### 3.2 CZSCAdapter（缠论）

```python
class CZSCAdapter(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        is_3rd_buy = raw_output.get("is_3rd_buy", False)
        bi_count = int(raw_output.get("bi_count", 0))
        
        if not is_3rd_buy and bi_count == 0:
            return None
        
        confidence = min(0.5 + bi_count * 0.05, 0.9) if is_3rd_buy else 0.3
        
        return TradingSignal(
            action="BUY" if is_3rd_buy else "HOLD",
            confidence=confidence,
            shares=default_shares if is_3rd_buy else 0,
        )
```

**信号映射**：
- **BUY**: is_3rd_buy=True（三买成立）
- **HOLD**: is_3rd_buy=False
- **置信度**: min(0.5 + bi_count * 0.05, 0.9)

### 3.3 WyckoffAdapter（威科夫）

```python
class WyckoffAdapter(EngineAdapter):
    """
    P0-2/P0-4/P0-7 (2026-08-12 深入再研究定稿): 引擎目标态 = 叙事+风控层。
    - 方向唯一来自direction gate
    - **恒不产SELL-as-entry**: 非入场方向一律返回None，绝不产生SELL
    """
    
    _ENTRY_DIRECTIONS = {"做多", "买入", "轻仓试探"}
    
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        direction = raw_output.get("wyckoff_direction", "")
        confidence = float(raw_output.get("wyckoff_confidence", 0.0))
        
        # 配置门控
        cfg = get_config()
        if not bool(cfg.get("wyckoff.direction_gate_enabled", True)):
            return None
        gate = float(cfg.get("wyckoff.confidence_gate", 0.40))
        
        if direction not in self._ENTRY_DIRECTIONS or confidence < gate:
            return None
        
        return TradingSignal(
            action="BUY",
            confidence=confidence,
            shares=default_shares,
            metadata={
                "wyckoff_phase": phase,
                "wyckoff_direction": direction,
                "wyckoff_spring": spring,
                "wyckoff_utad": utad,
            }
        )
```

**关键特性**：
- ✅ **恒不产SELL-as-entry**（仅产生BUY或None）
- ✅ 方向门控（direction_gate_enabled）
- ✅ 置信度门控（confidence_gate默认0.40）
- ✅ 入场方向白名单：{做多, 买入, 轻仓试探}

### 3.4 FSMAdapter（状态机）

```python
class FSMAdapter(EngineAdapter):
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
    
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        raw_action = raw_output.get("final_decision", raw_output.get("action", "HOLD"))
        action = self._ACTION_MAP.get(raw_action, "HOLD")
        shares = int(raw_output.get("shares", default_shares if action == "BUY" else 0))
        
        return TradingSignal(action=action, shares=shares, ...)
```

**动作映射**：
- BUY: BUY, ADD, EXECUTE_BUY
- SELL: SELL, EXECUTE_SELL, FORCE_EXIT
- HOLD: HOLD, FORCE_WAIT, CIRCUIT_BREAK, STAY_CURRENT_STATE

### 3.5 RegimeAdapter（市场状态）

```python
class RegimeAdapter(EngineAdapter):
    """
    输出: HOLD (FROZEN/STRESSED) / None (NORMAL) — 从不产生SELL
    """
    
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        regime = raw_output.get("regime", "NORMAL")
        
        if regime == "FROZEN":
            return TradingSignal(action="HOLD", reason="市场冻结", confidence=0.5, shares=0)
        elif regime == "STRESSED":
            return TradingSignal(action="HOLD", reason="市场紧张", confidence=0.5, shares=0)
        else:
            return None  # NORMAL
```

**关键特性**：
- ✅ **从不产生SELL**
- ✅ FROZEN/STRESSED → HOLD
- ✅ NORMAL → None（不产生信号）

### 3.6 NTFAdapter（国家队干预）

```python
class NTFAdapter(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        side = raw_output.get("ntf_side", "NONE")
        intensity = float(raw_output.get("ntf_intensity", 0.0))
        
        if side == "SUPPORT":
            return TradingSignal(action="HOLD", confidence=intensity * 0.5, shares=0)
        elif side == "RESISTANCE":
            if intensity >= 0.6:
                return TradingSignal(action="SELL", confidence=min(intensity, 0.9), shares=default_shares)
        return None
```

**信号映射**：
- **SELL**: RESISTANCE且intensity≥0.6
- **HOLD**: SUPPORT
- **None**: NONE或RESISTANCE但intensity<0.6

### 3.7 AlphaScoreAdapter（Alpha评分）

```python
class AlphaScoreAdapter(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        score = float(raw_output.get("alpha_score", 0.5))
        
        if score > 0.6:
            action = "BUY"
        elif 0 < score < 0.3:
            action = "SELL"
        else:
            return None
        
        return TradingSignal(
            action=action,
            confidence=abs(score - 0.5) * 2,
            shares=default_shares if action != "HOLD" else 0,
        )
```

**信号映射**：
- **BUY**: score > 0.6
- **SELL**: 0 < score < 0.3
- **None**: 0.3 ≤ score ≤ 0.6

### 3.8 MAStatusAdapter（均线状态）

```python
class MAStatusAdapter(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        ma_status = raw_output.get("ma_status", "")
        
        if ">" in ma_status:
            action = "BUY"   # MA20 > MA60
        elif "<=" in ma_status:
            action = "SELL"  # MA20 <= MA60
        else:
            return None
        
        return TradingSignal(action=action, confidence=0.3, ...)
```

**关键特性**：
- 🟡 固定置信度0.3（低质量信号）

### 3.9 QARAdapter（QAR策略）

```python
class QARAdapter(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp=None, default_shares=100):
        is_compliant = raw_output.get("is_compliant", True)
        if not is_compliant:
            return None
        
        weight = float(raw_output.get("weight", 0.0))
        
        if weight > 0:
            action = "BUY"
            confidence = min(0.5 + weight * 10, 0.95)
        elif weight < 0:
            action = "SELL"
            confidence = 0.8
        else:
            return None
        
        return TradingSignal(action=action, confidence=confidence, ...)
```

**信号映射**：
- **BUY**: weight > 0且合规
- **SELL**: weight < 0
- **None**: weight = 0或不合规

---

## 4. 适配器注册表

### 4.1 默认注册表

```python
def create_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    # LPPL：零预测力（MC证伪）→ 默认遥测（diagnostic_only=True），不产SELL强平
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

### 4.2 自动发现机制

```python
@classmethod
def discover(cls, base_module="uniquant.signal.adapters"):
    registry = cls()
    mod = importlib.import_module(base_module)
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, EngineAdapter) and obj is not EngineAdapter:
            engine_name = name.lower().replace("adapter", "").replace("engine", "")
            registry.register(engine_name, obj())
    return registry
```

---

## 5. TradingSignalCollector（信号收集器）

### 5.1 收集流程

```python
class TradingSignalCollector:
    def collect(self, data_pack, timestamp=None, bar_date=None, default_shares=100):
        """
        Args:
            data_pack: AnalysisService._run_engine_analysis()的输出
            timestamp: 信号时间戳（wall clock，仅当bar_date为None时使用）
            bar_date: K-line bar日期（preferred over timestamp for backtest）
        """
        ts = bar_date if bar_date is not None else timestamp  # ✅ bar_date优先
        
        with perf_section("adapter.collect"):
            signals = []
            symbol = data_pack.get("symbol", "")
            
            # 遍历registry中的所有适配器
            for engine_name, adapter in self._registry._adapters.items():
                raw_output = data_pack.get(engine_name, {})
                if not raw_output:
                    continue
                
                signal = adapter.adapt(raw_output, symbol, ts, default_shares)
                if signal is not None:
                    signals.append(signal)
            
            return signals
```

### 5.2 关键设计

- ✅ **bar_date优先于timestamp**：回测时使用K线日期，避免前视偏差
- ✅ **perf_section包装**：性能监控
- ✅ **None过滤**：适配器返回None表示不产生信号

---

## 6. SignalArbitrator（信号仲裁器）

### 6.1 引擎优先级

```python
ENGINE_PRIORITY = {
    "lppl": 99,        # 最低优先级（遥测层）
    "fsm": 1,          # 最高优先级
    "czsc": 2,
    "qar": 3,
    "wyckoff": 4,
    "regime": 5,
    "ntf": 6,
    "alpha_score": 7,
    "ma_status": 8,
}
```

**优先级说明**：
- 数值越小优先级越高
- LPPL(99)：已降为遥测层，不参与方向决策
- FSM(1)：DecisionBrain决策，最高优先级

### 6.2 仲裁规则（_pick_winner方法）

```python
def _pick_winner(self, day_signals, symbol, date_key):
    # 只考虑可执行信号 (BUY/SELL), 过滤HOLD
    actionable = [s for s in day_signals if s.action in ("BUY", "SELL")]
    
    if not actionable:
        return None  # 全是HOLD
    
    # 规则0: 质量阈值过滤 (P6.5)
    if self._quality_threshold > 0.0:
        filtered = []
        for sig in actionable:
            oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)
            if oos_r2 < self._quality_threshold and sig.action == "SELL":
                # 过滤低质量SELL
                continue
            filtered.append(sig)
        actionable = filtered
    
    if not actionable:
        return None
    
    if len(actionable) == 1:
        return actionable[0]
    
    # 规则1: SELL优先于BUY
    if self._sell_priority:
        sells = [s for s in actionable if s.action == "SELL"]
        if sells:
            return self._highest_confidence(sells)
    
    # 规则2: 同方向取最高confidence
    action_groups = {}
    for sig in actionable:
        action_groups.setdefault(sig.action, []).append(sig)
    
    for action in ("BUY", "SELL"):
        if action in action_groups:
            return self._highest_confidence(action_groups[action])
    
    # 规则3: 按引擎优先级
    return self._by_engine_priority(actionable)
```

### 6.3 仲裁规则总结

| 规则 | 条件 | 动作 | 说明 |
|---|---|---|---|
| **规则0** | 质量阈值过滤 | 过滤低质量SELL | OOS R² < threshold |
| **规则1** | sell_priority=True | SELL优先 | 有SELL时拒绝所有BUY |
| **规则2** | 同方向多信号 | 取最高confidence | BUY组或SELL组内竞争 |
| **规则3** | 不同方向无SELL | 按引擎优先级 | FSM(1) > CZSC(2) > ... |

### 6.4 arbitrate_candidates方法（类型化仲裁）

```python
def arbitrate_candidates(self, candidates, decision_output=None, context=None, sizer=None, symbol=""):
    # Priority 1: DecisionOutput硬约束
    if decision_output is not None:
        if decision_output.action in ("FORCE_WAIT", "CIRCUIT_BREAK"):
            return [], report  # HOLD
        
        if decision_output.action == "FORCE_EXIT":
            return [TradingSignal(action="SELL", reason="FORCE_EXIT", confidence=1.0)], report
        
        if decision_output.action == "BUY" and decision_output.shares > 0:
            return [TradingSignal(action="BUY", shares=decision_output.shares)], report
    
    # Priority 2: SELL over BUY
    sell_candidates = [c for c in candidates if c.action == "SELL"]
    if sell_candidates:
        best_sell = max(sell_candidates, key=lambda c: c.confidence)
        return [TradingSignal(action="SELL", confidence=best_sell.confidence)], report
    
    # Priority 3: Non-FSM BUY需要PositionSizer
    buy_candidates = [c for c in candidates if c.action == "BUY"]
    non_fsm_buys = [c for c in buy_candidates if c.source != "fsm"]
    fsm_buys = [c for c in buy_candidates if c.source == "fsm"]
    
    # FSM buys直接通过
    if fsm_buys:
        best_fsm = max(fsm_buys, key=lambda c: c.confidence)
        return [TradingSignal(action="BUY", confidence=best_fsm.confidence)], report
    
    # Non-FSM buys需要sizer
    if non_fsm_buys:
        if sizer is None:
            return [], report  # 无sizer，拒绝BUY
        else:
            best_non_fsm = max(non_fsm_buys, key=lambda c: c.confidence)
            sized = sizer.calculate_shares(...)
            return [TradingSignal(action="BUY", shares=sized.shares)], report
```

### 6.5 Kill Switch集成

```python
if get_kill_switch().is_killed:
    logger.info("All signals dropped: kill switch active (%s)", get_kill_switch().reason)
    return []  # 紧急停止，丢弃所有信号
```

### 6.6 信号过期检查

```python
DEFAULT_MAX_SIGNAL_AGE_SECONDS = 0.0  # 0=禁用; 回测模式下应保持禁用

if sig.timestamp is not None and self._max_signal_age_seconds > 0:
    age = (now - sig.timestamp).total_seconds()
    if age > self._max_signal_age_seconds:
        continue  # 信号过期，丢弃
```

**关键设计**：
- ✅ **默认禁用**（0.0秒）：回测模式下信号时间戳vs壁钟时间不匹配
- ✅ **可配置**：实盘模式可启用过期检查

---

## 7. 信号映射规则总结表

| 引擎 | BUY条件 | SELL条件 | HOLD条件 | 置信度 | 特殊说明 |
|---|---|---|---|---|---|
| **LPPL** | 从不 | Danger且非diagnostic | Safe/Warning/Danger(diagnostic) | confidence | 默认diagnostic_only=True |
| **CZSC** | is_3rd_buy=True | 从不 | is_3rd_buy=False | min(0.5+bi_count*0.05, 0.9) | 缠论三买 |
| **Wyckoff** | direction∈{做多,买入,轻仓试探}且conf≥0.40 | **从不** | 其他 | confidence | 恒不产SELL-as-entry |
| **FSM** | BUY/ADD/EXECUTE_BUY | SELL/FORCE_EXIT | HOLD/CIRCUIT_BREAK | confidence | DecisionBrain决策 |
| **Regime** | 从不 | 从不 | FROZEN/STRESSED | 0.5 | 从不产生BUY/SELL |
| **NTF** | 从不 | RESISTANCE且intensity≥0.6 | SUPPORT | min(intensity,0.9) | 国家队干预 |
| **AlphaScore** | score>0.6 | score<0.3 | 0.3≤score≤0.6 | abs(score-0.5)*2 | Alpha评分 |
| **MAStatus** | MA20>MA60 | MA20≤MA60 | 其他 | 0.3 | 固定低置信度 |
| **QAR** | weight>0且合规 | weight<0 | weight=0 | min(0.5+weight*10,0.95) | QAR策略 |

---

## 8. 信号冲突处理案例

### 8.1 案例1: SELL优先于BUY

```python
# 输入信号
signals = [
    TradingSignal(action="BUY", reason="CZSC 3rd_buy=True", confidence=0.8),
    TradingSignal(action="SELL", reason="NTF RESISTANCE", confidence=0.7),
]

# 仲裁结果
final_signal = arbitrator.arbitrate(signals)
# 输出: TradingSignal(action="SELL", reason="NTF RESISTANCE", confidence=0.7)
# 原因: sell_priority=True，SELL优先于BUY
```

### 8.2 案例2: 同方向取最高置信度

```python
# 输入信号
signals = [
    TradingSignal(action="BUY", reason="CZSC 3rd_buy=True", confidence=0.7),
    TradingSignal(action="BUY", reason="Wyckoff direction=做多", confidence=0.9),
    TradingSignal(action="BUY", reason="MA status=MA20 > MA60", confidence=0.3),
]

# 仲裁结果
final_signal = arbitrator.arbitrate(signals)
# 输出: TradingSignal(action="BUY", reason="Wyckoff direction=做多", confidence=0.9)
# 原因: 同方向取最高置信度
```

### 8.3 案例3: 按引擎优先级

```python
# 输入信号（假设sell_priority=False）
signals = [
    TradingSignal(action="BUY", reason="FSM BUY", confidence=0.6),
    TradingSignal(action="BUY", reason="CZSC 3rd_buy=True", confidence=0.6),
]

# 仲裁结果
final_signal = arbitrator.arbitrate(signals)
# 输出: TradingSignal(action="BUY", reason="FSM BUY", confidence=0.6)
# 原因: 同置信度，按引擎优先级 FSM(1) > CZSC(2)
```

### 8.4 案例4: DecisionOutput硬约束

```python
# 输入候选信号
candidates = [
    CandidateSignal(source="czsc", action="BUY", confidence=0.8),
    CandidateSignal(source="wyckoff", action="BUY", confidence=0.7),
]

# DecisionOutput强制退出
decision_output = DecisionOutput(action="FORCE_EXIT")

# 仲裁结果
final_signals, report = arbitrator.arbitrate_candidates(candidates, decision_output)
# 输出: [TradingSignal(action="SELL", reason="FORCE_EXIT", confidence=1.0)]
# 原因: DecisionOutput硬约束优先级最高
```

---

## 9. confidence、shares、price、timestamp合理性检查

### 9.1 confidence合理性

| 引擎 | 置信度范围 | 合理性评价 |
|---|---|---|
| **LPPL** | 0.05-1.0 | ✅ 合理，低置信度过滤 |
| **CZSC** | 0.5-0.9 (BUY), 0.3 (HOLD) | ✅ 合理，bi_count越高置信度越高 |
| **Wyckoff** | ≥0.40 (门控) | ✅ 合理，置信度门控 |
| **FSM** | 0.5 (默认) | 🟡 固定值，未反映信号强度 |
| **Regime** | 0.5 (固定) | ✅ 合理，HOLD信号无需高置信度 |
| **NTF** | 0.0-0.9 (SELL), 0.0-0.5 (HOLD) | ✅ 合理，intensity越高置信度越高 |
| **AlphaScore** | 0.0-1.0 | ✅ 合理，score偏离0.5越远置信度越高 |
| **MAStatus** | 0.3 (固定) | 🔴 **固定低值**，可能产生低质量信号 |
| **QAR** | 0.5-0.95 (BUY), 0.8 (SELL) | ✅ 合理，weight越高置信度越高 |

### 9.2 shares合理性

```python
# A股规则：100股整数倍
shares = default_shares if action == "BUY" else 0  # 默认100股

# FSM适配器支持自定义shares
shares = int(raw_output.get("shares", default_shares if action == "BUY" else 0))

# Non-FSM BUY需要PositionSizer计算
sized = sizer.calculate_shares(price, stop_loss, ...)
```

**合理性评价**：
- ✅ 默认100股（1手）
- ✅ FSM支持自定义shares
- ✅ Non-FSM BUY通过PositionSizer计算
- 🟡 部分适配器（CZSC/Wyckoff/AlphaScore/MAStatus/QAR）固定使用default_shares

### 9.3 timestamp合理性

```python
# TradingSignalCollector.collect
ts = bar_date if bar_date is not None else timestamp  # ✅ bar_date优先

# 回测时：bar_date = K线日期（避免前视偏差）
# 实盘时：timestamp = wall clock时间
```

**合理性评价**：
- ✅ bar_date优先于timestamp（回测时避免前视偏差）
- ✅ perf_section包装（性能监控）

### 9.4 price合理性

```python
# 大多数适配器从raw_output获取price
price = float(raw_output.get("price", 0.0))

# 默认值0.0可能有问题
```

**合理性评价**：
- 🟡 **默认值0.0**：如果raw_output中没有price，会使用0.0
- **建议**：从data_pack的stock_df获取最新close价格作为fallback

---

## 10. T+1规则影响验证

### 10.1 timestamp对T+1的影响

```python
# 回测时使用bar_date（K线日期）
ts = bar_date if bar_date is not None else timestamp

# T+1规则：T日信号，T+1日执行
# 如果bar_date = 2026-11-24（T日），则信号在2026-11-25（T+1日）执行
```

**关键设计**：
- ✅ bar_date优先：回测时使用K线日期，确保T+1规则正确
- ✅ 默认禁用信号过期检查：回测模式下信号时间戳vs壁钟时间不匹配

### 10.2 潜在风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| **盘中信号** | 盘中产生的信号，bar_date为当日 | FSM盘中模式使用前一日数据计算MA |
| **收盘信号** | 收盘后产生的信号，bar_date为当日 | T+1日开盘执行 |
| **信号过期** | 实盘模式下可能启用过期检查 | 默认禁用（0.0秒） |

---

## 11. A股实盘适配性评价

### 11.1 优势 ✅

1. **Sell-Priority机制** ✅
   - SELL始终优先于BUY
   - 符合A股避险优先原则

2. **Wyckoff恒不产SELL-as-entry** ✅
   - 仅产生BUY或None
   - 避免误卖

3. **bar_date优先于timestamp** ✅
   - 回测时使用K线日期
   - 避免前视偏差

4. **质量门过滤** ✅
   - OOS R² < threshold的SELL被过滤
   - 提高信号质量

5. **Kill Switch集成** ✅
   - 紧急情况停止所有交易
   - Fail-safe机制

6. **DecisionOutput硬约束** ✅
   - FORCE_EXIT/FORCE_WAIT优先级最高
   - DecisionBrain决策优先

7. **PositionSizer集成** ✅
   - Non-FSM BUY需要仓位计算
   - 避免过度仓位

### 11.2 潜在问题 🟡

1. **信号冲突处理简单** 🟡
   - 仅按优先级和置信度
   - 缺乏更复杂的逻辑（如信号融合）

2. **同方向多信号处理** 🟡
   - 仅取最高置信度
   - 未考虑信号融合（如加权平均）

3. **低置信度信号过滤** 🟡
   - MAStatus固定0.3
   - 可能产生低质量信号

4. **QAR适配器新颖** 🟡
   - 基于权重的信号
   - 需要验证实际效果

---

## 12. 改进建议

### 12.1 短期改进（P1）

1. **信号融合机制** 🟡
   - **现状**：同方向多信号时，仅取最高置信度
   - **建议**：考虑加权平均（按引擎优先级加权）
   - **工作量**：4小时

2. **动态置信度阈值** 🟡
   - **现状**：固定quality_threshold=0.3
   - **建议**：根据市场状态（Regime）调整最低置信度要求
   - **工作量**：2小时

3. **price fallback机制** 🟡
   - **现状**：price默认0.0
   - **建议**：从data_pack的stock_df获取最新close价格作为fallback
   - **工作量**：1小时

### 12.2 中期改进（P2）

4. **信号来源追踪** 🟢
   - **现状**：reason字段包含引擎信息，但不结构化
   - **建议**：添加source_engine字段到TradingSignal
   - **工作量**：4小时

5. **信号回测验证** 🟢
   - **现状**：无仲裁前后对比
   - **建议**：记录仲裁前所有信号，回测对比仲裁效果
   - **工作量**：8小时

6. **自适应优先级** 🟢
   - **现状**：固定ENGINE_PRIORITY
   - **建议**：根据近期表现动态调整引擎优先级
   - **工作量**：16小时

---

## 13. 校验清单

- [x] 覆盖LPPL、CZSC、Wyckoff、FSM、Regime、NTF、Alpha、MA（§3，9个适配器）
- [x] 指出多个BUY/SELL同时出现时的风险（§8，4个案例）
- [x] 检查timestamp对回测T+1的影响（§10）
- [x] 给出确定性聚合规则（§6.2，4条仲裁规则）
- [x] TradingSignal字段说明（§2）
- [x] 引擎输出到信号的映射表（§7）
- [x] 信号收集流程（§5）
- [x] 信号冲突案例（§8）
- [x] 当前问题（§11.2）
- [x] 推荐信号优先级和聚合规则（§6.1，§12）
- [x] 实盘信号校验标准（§9-10）

---

## 14. 阶段5结论

UniQuant的信号系统展现了**清晰的适配器模式和严格的仲裁规则**：

### 架构优点 ✅
1. **9个引擎适配器**：统一接口（EngineAdapter.adapt），易于扩展
2. **适配器注册表**：自动发现+手动注册
3. **信号收集器**：bar_date优先于timestamp，避免前视偏差
4. **信号仲裁器**：4条仲裁规则，Sell-Priority机制
5. **Kill Switch集成**：紧急停止，Fail-safe机制
6. **DecisionOutput硬约束**：FORCE_EXIT/FORCE_WAIT优先级最高
7. **PositionSizer集成**：Non-FSM BUY需要仓位计算
8. **质量门过滤**：OOS R² < threshold的SELL被过滤

### 核心机制 ✅
1. **Sell-Priority**：SELL始终优先于BUY（避险优先）
2. **Wyckoff恒不产SELL-as-entry**：仅产生BUY或None
3. **引擎优先级**：FSM(1) > CZSC(2) > QAR(3) > Wyckoff(4) > ... > LPPL(99)
4. **同方向取最高置信度**：BUY组或SELL组内竞争
5. **DecisionOutput硬约束**：FORCE_EXIT/FORCE_WAIT优先级最高

### 主要风险 🟡
1. 🟡 **信号冲突处理简单**：仅按优先级和置信度，缺乏信号融合
2. 🟡 **同方向多信号处理**：仅取最高置信度，未考虑加权平均
3. 🟡 **MAStatus固定低置信度**：0.3可能产生低质量信号
4. 🟡 **price默认0.0**：可能影响PositionSizer计算

**下一阶段**：阶段6 - 回测与撮合分析（深入回测引擎、撮合规则、A股交易约束）

---

**分析人**：Claude (Anthropic)  
**审核状态**：待用户确认  
**产物路径**：`docs/analysis/05_signal_system.md`
