# 红蓝对抗 Round 3 — 信号链 + 工程整合真实有效方案

> **日期**: 2026-07-24  
> **对抗议题**: 在 Round 1 (LPPL) 和 Round 2 (Wyckoff) 的重新设计方案下，信号适配器、仲裁器和工程管线应如何整合？
> **角色**: 🔵 Blue = 最大化保留派 / 🔴 Red = 激进简化派

---

## 审查标准

| 条件 | 门槛 |
|---|---|
| S1 | 适配器输出真实引擎决策，不静音有效信号 |
| S2 | 仲裁器处理信号稀疏性（多数时间无信号） |
| S3 | 管线在引擎级别标记 "不可用" 而非硬失败 |
| S4 | Monte Carlo 验证成为管线内建步骤 |
| S5 | 死代码不会误导后续开发 |

---

## Claim 1: "Adapter 应暴露 Wyckoff trading_plan.direction 为主信号"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 当前 `WyckoffAdapter.adapt()`（`adapters.py:159-202`）只读 `wyckoff_phase`、`wyckoff_confidence`、`wyckoff_spring`、`wyckoff_utad`。它从不读 `trading_plan.direction`（{"空仓观望", "买入", "观察等待", "持有", "做多", "轻仓试探"}）。Walk-forward 实证：adapter 输出 0 个 BUY/SELL（600 次），但引擎内部 `trading_plan.direction="买入"` 出现 27 次（+8.60% spread, p=0.0098）。**Adapter 静音了唯一有效信号** | `adapters.py:159-177` |
| 🔴 Red | 简单暴露 `trading_plan.direction` 有两大风险：①"买入"方向在 markup 阶段触发，本质是追涨信号，单边市回撤时可能巨亏；② 4.5% 触发率的信号在实盘中无法频繁交易。**建议**：不把"买入"直接映射为 BUY，而是映射为"轻度看多"（LONG_WEAK），在资产配置层做仓位限制（如最大 5% 仓位）。同时保留 phase 基础映射路径作为保守对照 | |
| ⚪ Referee | **BLUE WINS 原则上，RED 的实务担忧合理**。Adpater 必须暴露 `trading_plan.direction` — 当前的完全静音是不可接受的。但 RED 建议的方向分级（LONG_WEAK / LONG / LONG_STRONG）是合理的安全设计。**裁决**：Adapter 输出方向分级，同时保留 phase 映射的 HOLD 对照 | |

**Adapter 重写实现**:
```python
# adapters.py — WyckoffAdapter v2
_DIRECTION_MAP = {
    "做多": "BUY",
    "买入": "BUY_WEAK",    # 追涨信号，仓位限制
    "持有": "HOLD",
    "持有观察": "HOLD",
    "轻仓试探": "BUY_WEAK",
    "观察等待": "HOLD_WATCH",
    "空仓观望": "HOLD",
}

class WyckoffAdapterV2(EngineAdapter):
    def adapt(self, raw_output, symbol, timestamp, default_shares=100):
        # 优先从 trading_plan.direction 获取信号
        trading_plan = raw_output.get("trading_plan", {})
        direction = trading_plan.get("direction", "空仓观望")
        action = _DIRECTION_MAP.get(direction, "HOLD")
        
        # 从 phase 获取后备信息
        phase = raw_output.get("wyckoff_phase", "unknown")
        
        # 置信度：优先用 trading_plan 隐含置信度，否则 fallback
        confidence = trading_plan.get("implied_confidence", 
                     raw_output.get("wyckoff_confidence", 0.0))
        
        # 仓位限制：BUY_WEAK 限仓
        if action == "BUY_WEAK":
            max_shares = int(default_shares * 0.5)  # 半仓
        elif action == "BUY":
            max_shares = default_shares
        else:
            max_shares = 0
            
        return TradingSignal(
            action=action,
            reason=f"Wyckoff dir={direction} phase={phase}",
            confidence=confidence,
            shares=max_shares,
            symbol=symbol,
            price=float(raw_output.get("price", 0.0)),
            timestamp=timestamp,
            metadata={
                "trading_direction": direction,
                "wyckoff_phase": phase,
                "signal_source": "trading_plan",
            },
        )
```

---

## Claim 2: "LPPL 应从信号链中完全移除"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔴 Red | 3 轮对抗 + 2 轮实证 + 1 轮 MC 均已证明：LPPL 在 A 股个股 120 天窗口中零预测力。`is_danger` p=0.48，`calculate_risk_level` 无区分度，MC 证明 93% GBM 随机数据 R²>0.3。目前 LPPL 信号在仲裁器 (`signal/arbitrator.py`) 中占据一个决策席位 — 这意味着一个随机信号在稀释其他有效信号的权重。**从信号链中移除 LPPL 会立即提高整体信号质量** | Walk-forward: LPPL is_danger p=0.48; MC: 93% GBM fit |
| 🔵 Blue | 即使在个股级别 LPPL 无效，m 和 ω 参数可以作为**多因子模型的特征**。比如：m 接近 0.9 = 泡沫后期特征，ω 在 6-9 = 周期加速特征。这些特征虽然不足以单独做交易决策，但可以融入因子库作为风险因子。**保留 LPPL 计算管线但不输出独立交易信号** | - |
| ⚪ Referee | **RED WINS 战术上，BLUE WINS 战略上。** 当前仲裁器中的 LPPL 信号席位必须移除 — 它生产噪声。但保留 LPPL 计算作为因子生成器是合理的（不参与信号仲裁，只供因子分析）。**裁决**：LPPL 从 `signal/arbitrator.py` 中移除，保留在 `engine_factory.py` 中作为离线研究选项 | |

---

## Claim 3: "仲裁器应处理信号稀疏性 — '无信号'是有效输出"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 当前仲裁器 (`signal/arbitrator.py`) 在多数信号为 None/HOLD 时行为未定义。Walk-forward 数据显示：Wyckoff 91.2% "空仓观望"，0 BUY/SELL 通过当前 adapter。如果修复 adapter 暴露 "买入"（4.5%），仍然有 ~95% 时间无信号。**仲裁器需要明确处理"多数引擎无信号"的常态**。": 默认输出应为 HOLD，而非尝试从噪声中合成信号 | Walk-forward: Wyckoff 91.2% 空仓观望; 修复后仍 ~95% 无信号 |
| 🔴 Red | 极端信号稀疏性意味着：**任何信号都应该被重视，但任何信号都不能被信任**。在只有 4.5% 时间有信号的情况下，信号的质量 (precision) 远比数量 (recall) 重要。仲裁器的输出应该是三层结构：① 强烈信号（多个引擎共识）→ FULL；② 单一信号（如 Wyckoff"买入"）→ 仓位限制；③ 无信号 → 空仓/现金。**第三层是最重要的 — 承认不知道比假装知道更安全** | - |
| ⚪ Referee | **RED WINS — "无信号"是最诚实最有价值的输出**。仲裁器重构为三层裁决 | |

**仲裁器稀疏性处理实现**:
```python
# arbitrator.py — 三层裁决赛
def arbitrate_v2(signals: List[TradingSignal], config) -> ArbitratedDecision:
    """三层仲裁: 共识 > 单源 > 无信号"""
    non_hold = [s for s in signals if s.action not in ("HOLD", "HOLD_WATCH")]
    
    if not non_hold:
        # 层3: 无信号 — 输出 HOLD
        return ArbitratedDecision(action="HOLD", confidence=0.0,
                                  reason="No engine has actionable signal")
    
    buy_signals = [s for s in non_hold if "BUY" in s.action]
    sell_signals = [s for s in non_hold if "SELL" in s.action]
    
    if buy_signals and sell_signals:
        # 冲突：仲裁器应判定哪个更可靠
        if any(s.action == "SELL" for s in sell_signals):
            # SELL 优先（当前逻辑 — 保留）
            return _resolve_conflict(buy_signals, sell_signals, config)
    
    if len(buy_signals) >= 2:
        # 层1: 共识 — 全仓信号
        return ArbitratedDecision(action="BUY", confidence=0.8,
                                  signals=non_hold,
                                  reason=f"Consensus: {len(buy_signals)} engines agree")
    
    # 层2: 单源信号 — 限仓
    primary = buy_signals[0] if buy_signals else sell_signals[0]
    weak_action = primary.action.replace("BUY", "BUY_WEAK") if "BUY" in primary.action else primary.action
    return ArbitratedDecision(action=weak_action, confidence=primary.confidence * 0.6,
                              signals=[primary],
                              reason=f"Single source: {primary.reason} (position limited)")
```

---

## Claim 4: "Monte Carlo 验证必须成为管线内建步骤"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔴 Red | 当前管线完全没有 MC 验证步骤。LPPL 的问题（93% GBM 拟合 R²>0.3）如果从一开始就做 MC 对照，根本不会上线。Wyckoff "买入"信号的 p=0.0098 也需要 MC 验证排除多重比较偏差。**MC 验证应该成为引擎注册到工厂的强制条件：新增引擎必须通过 MC 验证才能进入生产仲裁** | - |
| 🔵 Blue | MC 验证的计算成本很高。LPPL 需要 1000 GBM × 2s = 2000s 每窗口。Wyckoff 需要 1000 GBM × Wyckoff 引擎运行时间和更复杂的状态机模拟。但如果不做 MC，就无法区分真实 alpha 和过拟合。**折中：在引擎注册时做一次性 MC，生成信号质量的 MC 签名（MC_signature），后续在信号元数据中附带该签名** | |
| ⚪ Referee | **RED WINS — MC 验证是必要门槛**。作为一次性后台作业，成本不是问题。Wyckoff 的 MC 验证（1000 次 GBM × 3s = 3000s ≈ 50 分钟一次性运算）可以做为 CI/CD 步骤或每周离线作业 | |

**MC 验证管线实现**:
```python
# mc_validator.py — Monte Carlo 验证注册器
class MCValidator:
    """所有生产引擎的 MC 验证注册器"""
    
    _registry = {}  # engine_name -> MC_signature
    
    @classmethod
    def validate(cls, engine_name: str, engine_fn: Callable, 
                 n_trials: int = 1000, window: int = 120,
                 n_stocks: int = 100) -> MCSignature:
        """对引擎运行 MC 验证"""
        null_returns = []
        for _ in range(n_trials):
            for _ in range(n_stocks):
                gbm = generate_gbm(window)
                signal = engine_fn(gbm)
                if signal and signal.action != "HOLD":
                    forward_ret = simulate_forward_return(gbm, signal)
                    null_returns.append(forward_ret)
        
        # 计算 null 分布
        null_arr = np.array(null_returns)
        signature = MCSignature(
            engine_name=engine_name,
            p_value=np.mean(null_arr > 0),
            mean_return=float(np.mean(null_arr)),
            std_return=float(np.std(null_arr)),
            sharpe_null=float(np.mean(null_arr) / max(np.std(null_arr), 1e-6)),
            n_signals_null=len(null_arr),
            n_trials=n_trials,
        )
        cls._registry[engine_name] = signature
        return signature
    
    @classmethod
    def can_register(cls, engine_name: str, 
                     p_threshold: float = 0.05,
                     min_signals: int = 20) -> bool:
        """检查引擎是否通过 MC 验证"""
        sig = cls._registry.get(engine_name)
        if sig is None:
            return False
        return sig.p_value < p_threshold and sig.n_signals_null >= min_signals
```

---

## Claim 5: "LPPL 死代码应标记不可用而非删除"

| 角色 | 陈述 | 证据 |
|---|---|---|
| 🔵 Blue | 当前项目已有 LPPL 引擎的完整代码（1107 行）、测试、配置和调用点。完全删除 1107 行代码需要同时更新 engine_factory、analysis_service、config 和测试。如果 Round 1 建议的指数级别 LPPL 未来实现，可能会用到计算器和优化器核心代码。**建议**：在 `engine_factory.py` 中将 LPPL 标记为 `DEPRECATED` 并绕过仲裁器，但保留代码以备后续指数级别实现 | - |
| 🔴 Red | 保留死代码是项目一直以来的问题 — `factor_governance.py`、`portfolio_engine.py`、`price_collar.py` 等等。每段保留的死代码都需要维护：测试需要兼容、导入路径不能断、重构时必须考虑。**删除 1107 行代码 + 更新调用点是一天的工作量**。如果未来要重写 LPPL v2 指数版，应该从头写 — 因为当前代码的约束（120 天窗口、L-BFGS-B 全参优化、tc 局部搜索）和 v2 设计（500+ 天窗口、VP 优化、tc 全局搜索）几乎无共享组件。**保留的计算器核心仅 ~50 行（`lppl_func`+`cost_function`），不值得保留 1107 行壳代码** | 项目历史：保留死代码的成本约 2,200 LOC |
| ⚪ Referee | **RED WINS — 删除优于保留标记为 DEPRECATED**。1107 行中约 1000 行是壳代码（扫描、多窗口、并行化、风险判定），不是核心计算逻辑。核心的 `lppl_func`（~20 行）和 `calculator.py`（665 行，含变量投影等）可以保留在仓库中作为研究工具，但**从生产管线（engine_factory.py → analysis_service_v2.py → arbitrator.py）完全移除**。删除 ~200 行生产管线集成代码，保留 ~1200 行核心计算代码作为离线研究 | |

---

## Round 3 汇总

| Claim | 议题 | Blue | Red | 裁决 | 工作量 |
|---|---|---|---|---|---|
| S1 | Adapter 暴露 trading_plan | ✅ | ⚠️ | **BLUE** + 方向分级 | **2h** |
| S2 | LPPL 从信号链移除 | ⚠️ | ✅ | **RED** — 从仲裁器移除 | **1h** |
| S3 | 仲裁器处理稀疏性 | ✅ | ✅ | **RED** — 三层裁决 | **3h** |
| S4 | MC 验证管线内建 | ⚠️ | ✅ | **RED** — 必要门槛 | **6h** |
| S5 | LPPL 死代码处理 | ⚠️ | ✅ | **RED** — 生产代码删除 | **4h** |

---

## 最终汇总：三 Round 核心产出

```
┌─────────────────────────────────────────────────────────────────┐
│ 三 ROUND 红蓝对抗 — 最终实施路线图                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  立即执行（价值明确，风险低，1-2 天）                             │
│  ─────────────────────────────────────────────                   │
│  ✅ 1. WyckoffAdapter 暴露 trading_plan.direction（2h）          │
│     文件: signal/adapters.py                                     │
│     输出: "买入"→BUY_WEAK、"做多"→BUY、"空仓观望"→HOLD           │
│                                                                  │
│  ✅ 2. LPPL 从仲裁器移除（1h）                                    │
│     文件: signal/arbitrator.py, services/analysis_service_v2.py  │
│     方式: LPPL 信号不参与仲裁，仅保留研究输出                     │
│                                                                  │
│  ✅ 3. UTAD 死代码清理 + Spring 降级（2h）                        │
│     文件: brain/wyckoff/engine.py                                │
│     方式: 删除 _detect_utad，Spring 不再作为置信度门控            │
│                                                                  │
│  短期执行（需要设计评审，3-5 天）                                 │
│  ─────────────────────────────────────────────                   │
│  📋 4. 仲裁器三层稀疏性处理（3h）                                 │
│     文件: signal/arbitrator.py                                   │
│     方式: 共识→全仓、单源→限仓、无信号→空仓                      │
│                                                                  │
│  📋 5. Monte Carlo 验证框架（6h）                                 │
│     文件: services/mc_validator.py (新文件)                       │
│     方式: 引擎注册时一次性 MC 验证，Wyckoff 信号 p 值验证          │
│                                                                  │
│  远期研究（需要独立验证，>1 周）                                   │
│  ─────────────────────────────────────────────                   │
│  🔬 6. Wyckoff "买入" MC 验证（4h）                              │
│     验证 p=0.0098 不是多重比较假阳性                             │
│                                                                  │
│  🔬 7. LPPL v2 指数级别（2-3 周）                                │
│     VP 优化 + b<0 约束 + 全局 tc + MC p-value                    │
│     沪深 300/中证 500 泡沫风险指标                               │
│                                                                  │
│  不执行                                                          │
│  ─────────────────────────────                                   │
│  ❌ LPPL v2 个股级别 — 信噪比不足                                │
│  ❌ Distribution 相位检测 — 120d 窗口不可实现                     │
│  ❌ Wyckoff 完全重写 — 收益不确定，成本 >40h                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```
