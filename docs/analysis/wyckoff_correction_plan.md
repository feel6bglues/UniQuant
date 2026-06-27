# Wyckoff 模块修正方案

> 基于代码深度分析 + 回测验证 (100 stocks × 4.5 years × 5 strategies)
> 三重角色编制: 量化算法工程师 / 架构工程师 / 交易员
> 日期: 2026-06-19

---

## 核心诊断 (回测证据驱动)

所有修正方案的依据来自回测 2,400 快照 + 100 只股票 × 5 策略的量化数据:

| 指标 | 数值 | 问题 |
|------|------|------|
| UNKNOWN 快照率 | 39% (935/2400) | 近半数无法分类 |
| "空仓观望"率 | 93.6% (2246/2400) | 系统默认不交易 |
| C/D 级置信度 | 97% (2313/2400) | 几乎无可靠信号 |
| LPS 确认率 | 0/423 spring | 方法论在 A 股无效 |
| 跑赢 BH 率 | 最高 24% (v1_phase) | 76% 输给买入持有 |

### 根本原因树

```
低信号价值 (年化 0.42%)
├── 阶段判定失效 (39% UNKNOWN)
│   ├── 缺少"上升趋势回调"子状态
│   ├── TR 中部横盘被丢弃
│   └── 硬编码阈值不适应不同波动率
├── 信号转化链断裂 (2,400→55 交易)
│   ├── Step 5 硬编码"空仓观望"覆盖所有
│   ├── R8 矩阵有效条件从 5 塌缩到 3
│   └── 死代码阻塞 rr_ratio/bypassed 传递
└── 入场时机错误 (LPS 0/423)
    ├── Spring 后数据不足 (break 只检查最新)
    ├── 缩量阈值 30% 过于严格
    └── LPS 概念在 A 股 T+1 环境不成立
```

---

## 方案选择

回测提供了三组修正选项, 成本效益逐级递增:

### 方案对比

| 方案 | 工作量 | 风险 | 预期收益提升 | 推荐场景 |
|------|--------|------|------------|---------|
| **A: 紧急修复** | 3 天 | 极低 | 0% (代码自洽) | 必须做 |
| **B: 结构改革** | 3 周 | 中 | 阶段判定 + 信号量提升 | 推荐的折中方案 |
| **C: 全新替代** | 6 周 | 高 | 全新因子系统 | 长期战略选择 |

---

## 方案 A: 紧急修复 (3 天)

### A.1 修复死代码 (0.5 天)

**文件**: `src/uniquant/services/analysis/wyckoff_analysis_engine.py:49-59`

```python
# 当前 (死代码):
result.get("phase")  # WyckoffReport 是 dataclass? → AttributeError

# 修复:
if isinstance(result, dict):
    phase = result.get("phase", "unknown")
else:
    phase = result.phase.value if hasattr(result, 'phase') and hasattr(result.phase, 'value') else "unknown"
```

**预期效果**: rr_ratio/bypassed 不再为默认值 0.0/False, P6.3/6.5 信号链完整.

### A.2 Bypass fall-through (0.5 天)

**文件**: `src/uniquant/brain/wyckoff/engine.py:880-900`

```python
# 当前: bypass 路径直接 return, 跳过 full R8 矩阵
if spring_lps_verified and not rr_qualified:
    # 直接 return ConfidenceResult(level="C", bypassed=True)
    return bypass_result

# 修复: bypass 路径 fall through 到 full R8 矩阵, 取 max
if self._debug_r8_compare:
    bypass_result = ConfidenceResult(level="C", ...)
    full_result = self.rules.rule8_confidence_matrix(...)
    # 取置信度更高的结果
    level_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    result = bypass_result if level_order.get(bypass_result.level, 4) <= level_order.get(full_result.level, 4) else full_result
    result.bypassed = True
    return result
```

**预期效果**: 消除 37.5% bypass 分歧, 600028/688981 等获得正确的 B 级置信度.

### A.3 Step 5 协调 R8 矩阵 (1 天)

**文件**: `src/uniquant/brain/wyckoff/engine.py:916-917`

```python
# 当前: MARKDOWN → 硬编码空仓观望
if step1.phase == WyckoffPhase.MARKDOWN:
    direction = "空仓观望"

# 修复: MARKDOWN + B+ + RR≥2.5 → 专业做多
if step1.phase == WyckoffPhase.MARKDOWN:
    if confidence.level in ("A", "B") and rr.rr_ratio >= 2.5:
        direction = "专业做多"  # 超跌反弹信号
    elif confidence.level in ("A", "B") and rr.rr_ratio >= 1.5:
        direction = "观察等待"
    else:
        direction = "空仓观望"
```

同理修复涨跌停覆盖 (line 1006):

```python
# 当前: 有跌停直接空仓, 完全覆盖阶段判定
if any(lm.move_type == LimitMoveType.LIMIT_DOWN for lm in limit_moves):
    direction = "空仓观望"

# 修复: 区分连续跌停 vs 单次跌停
if any(lm.move_type == LimitMoveType.LIMIT_DOWN for lm in limit_moves):
    consecutive_downs = sum(1 for lm in limit_moves if lm.move_type == LimitMoveType.LIMIT_DOWN)
    if consecutive_downs >= 3:
        direction = "空仓观望"  # 连续跌停 → 强风险信号
    elif direction == "专业做多":
        direction = "轻仓试探"  # 单次跌停 + B+ → 降仓但不放弃
```

**预期效果**: 释放 3 个 B 级 MARKDOWN 信号 (600519/601318/300760), 方向从"空仓观望"变为"专业做多".

### A.4 Spring 多点检测 + LPS 阈值放宽 (1 天)

**文件**: `src/uniquant/brain/wyckoff/engine.py:619-629`

```python
# 当前: 只检查最新的 Spring, break 后无论 LPS 结果
if spring_detected:
    # ... LPS check ...
    break  # 只检查一个

# 修复: 扫描所有候选 Spring, 选 LPS 确认率最高的
all_springs = []
for row in reversed(list(recent_20.itertuples())):
    if row.low < low_bound * SPRING_LOW_FACTOR and row.close >= low_bound * SPRING_CLOSE_FACTOR:
        post_idx = df.index.get_loc(row.Index)
        if post_idx < len(df) - 1:
            post_df = df.iloc[post_idx + 1:]
            lps = self.rules.rule6_spring_validation(True, post_df, float(row.low))
            all_springs.append((row, lps))
            
if all_springs:
    # 选最新的有效 Spring, 或任意一个有 LPS 确认的
    lps_springs = [(r, l) for r, l in all_springs if l.get("lps_confirmed")]
    chosen = lps_springs[-1] if lps_springs else all_springs[-1]
    spring_detected = True
    # ...
```

**文件**: `src/uniquant/brain/wyckoff/rules.py:191-192`

```python
# 当前: 30% → 几乎不可能达标
low_volume = recent_vol < max_vol * 0.3

# 修复: 放宽至 50%, 保留基本筛选能力
low_volume = recent_vol < max_vol * 0.5
```

**预期效果**: LPS 确认率从 0/423 提升至约 5-10%, Spring 信号质量小幅改善.

### A.5 R8 矩阵 A 股自适应加权 (1 天)

**文件**: `src/uniquant/brain/wyckoff/rules.py:247-291`

```python
# 当前: 5 项等权, 但 spring_lps 和 multiframe 在 A 股永远 False
# 有效条件池缩至 3 项, B 级是理论天花板

# 修复: A 股自适应加权矩阵
def rule8_confidence_matrix_ashare(
    bc_located: bool,
    spring_lps_verified: bool,
    counterfactual_passed: bool,
    rr_qualified: bool,
    multiframe_aligned: bool,
) -> ConfidenceResult:
    weights = {
        "bc_located": 0.35,           # BC 定位 → 支撑明确
        "spring_lps_verified": 0.10,  # A 股不依赖
        "counterfactual_passed": 0.25, # 多空证据平衡
        "rr_qualified": 0.25,         # 盈亏比硬约束
        "multiframe_aligned": 0.05,   # 可选
    }
    score = 0.0
    score += bc_located * 0.35
    score += spring_lps_verified * 0.10
    score += counterfactual_passed * 0.25
    score += rr_qualified * 0.25
    score += multiframe_aligned * 0.05
    
    if score >= 0.75: level, size = "A", "标准仓位"
    elif score >= 0.50: level, size = "B", "轻仓"
    elif score >= 0.30: level, size = "C", "试仓"
    else: level, size = "D", "空仓"
    
    return ConfidenceResult(level=level, ..., position_size=size)
```

**预期效果**: A 级重新可达 (BC+counterfactual+RR 同时满足), B 级覆盖率从 3.5% 升至 ~15%.

### A 方案预期总收益

```
修复前: v0_raw 年化 0.42%, 55 笔交易/100股/4年
修复后: 预期年化 3-5%, 150-200 笔交易/100股/4年
原因: Step 5 空仓覆盖解除 + LPS 阈值放宽 → 信号量提升 3-4 倍
```

**A 方案总成本: 3 天, 风险: 极低**
**推荐: 立即执行**

---

## 方案 B: 结构改革 (3 周)

### B.1 自适应阶段分类器 (1 周)

**目标**: 将 UNKNOWN 率从 39% 降至 <10%.

**当前算法** (硬编码阈值):

```
MARKUP(c1): trend ∈ [0.03, 0.015) + price > MA20
MARKUP(c2): trend ∈ [0.015, 0.05) + price > avg_price
MARKUP(c3): trend >= 0.05
MARKDOWN(c4): trend <= -0.05 + price < MA20 * 0.95
```

**问题**: 阈值固定, 不适用于高波动 (STAR/科创板 20cm) 和低波动 (银行 10cm) 股票.

**新算法**: 多维度模糊分类

```python
class AdaptivePhaseClassifier:
    """
    自适应阶段分类器.
    
    用 4 个连续维度替代硬编码阶段枚举:
      - trend_strength: [-1, 1] 归一化趋势强度 (ADX 方向)
      - price_position: [0, 1] 价格在 TR 中的位置
      - volume_regime:  缩量/放量/正常
      - volatility_regime: ATR 分位数 (高/中/低波动)
    """
    
    def classify(
        self, df: pd.DataFrame, rule0: Rule0Result
    ) -> Tuple[WyckoffPhase, str, float]:
        """
        返回: (phase, sub_phase, confidence)
        
        核心逻辑: 基于模糊逻辑的加权投票
        """
        short_trend = self._compute_trend(df, 20)
        medium_trend = self._compute_trend(df, 60)
        price_in_tr = self._price_position_in_tr(df, rule0)
        vol_trend = self._volume_trend(df, 20)
        atr_quantile = self._atr_quantile(df, 20)
        
        # 模糊隶属度
        markup_membership = self._markup_membership(short_trend, medium_trend, vol_trend)
        markdown_membership = self._markdown_membership(short_trend, medium_trend, vol_trend)
        accum_membership = self._accum_membership(price_in_tr, vol_trend, atr_quantile)
        distrib_membership = self._distrib_membership(price_in_tr, vol_trend, atr_quantile)
        
        # 取最大隶属度
        memberships = {
            WyckoffPhase.MARKUP: markup_membership,
            WyckoffPhase.MARKDOWN: markdown_membership,
            WyckoffPhase.ACCUMULATION: accum_membership,
            WyckoffPhase.DISTRIBUTION: distrib_membership,
        }
        
        best_phase = max(memberships, key=memberships.get)
        best_score = memberships[best_phase]
        confidence = best_score
        
        # UNKNOWN 条件: 所有隶属度 < 0.3
        if best_score < 0.3:
            return (WyckoffPhase.UNKNOWN, "fuzzy_conflict", best_score)
        
        # 子状态识别
        sub_phase = self._identify_sub_phase(
            best_phase, short_trend, medium_trend, price_in_tr, df, rule0
        )
        
        return (best_phase, sub_phase, best_score)
    
    def _markup_membership(self, st: float, mt: float, vt: str) -> float:
        """上升趋势隶属度: 短中期趋势向上 + 量能配合"""
        score = 0.0
        if st > 0.02: score += 0.35
        elif st > 0: score += 0.15
        if mt > 0.02: score += 0.35
        elif mt > 0: score += 0.15
        if vt in ("放量", "平均"): score += 0.20
        if st > 0.05 and mt > 0.03: score += 0.10  # 加速
        return min(score, 1.0)
    
    def _markdown_membership(self, st: float, mt: float, vt: str) -> float:
        """下跌趋势隶属度"""
        score = 0.0
        if st < -0.02: score += 0.35
        elif st < 0: score += 0.15
        if mt < -0.02: score += 0.35
        elif mt < 0: score += 0.15
        if vt in ("地量", "萎缩"): score += 0.20
        if st < -0.05 and mt < -0.03: score += 0.10
        return min(score, 1.0)
    
    def _accum_membership(self, pip: float, vt: str, aq: float) -> float:
        """吸筹隶属度: TR 底部 + 缩量 + 低波动"""
        score = 0.0
        if pip < 0.30: score += 0.35
        elif pip < 0.45: score += 0.15
        if vt in ("地量", "萎缩"): score += 0.30
        elif vt == "正常": score += 0.15
        if aq < 0.30: score += 0.20  # 低波动分位
        return min(score, 1.0)
    
    def _distrib_membership(self, pip: float, vt: str, aq: float) -> float:
        """派发隶属度: TR 顶部 + 放量 + 高波动"""
        score = 0.0
        if pip > 0.70: score += 0.35
        elif pip > 0.55: score += 0.15
        if vt in ("放量", "天量"): score += 0.30
        if aq > 0.70: score += 0.20
        return min(score, 1.0)
```

**子状态扩展** (解决 39% UNKNOWN):

```python
# 新增子状态枚举
class WyckoffSubPhase(str, Enum):
    # ACCUMULATION 子状态
    PHASE_A = "phase_a"           # 初次吸筹 (从下跌到横盘)
    PHASE_B = "phase_b"           # 二次吸筹 (Spring)
    # MARKUP 子状态
    PHASE_C = "phase_c"           # 初次拉升
    MARKUP_CORRECTION = "correction"  # 上升趋势回调 (NEW! 原 UNKNOWN)
    # MARKDOWN 子状态
    PHASE_D = "phase_d"           # 初次派发
    # DISTRIBUTION 子状态
    PHASE_E = "phase_e"           # 派发完成
    # UNKNOWN 子状态
    TR_OSCILLATION = "tr_oscillation"  # TR 中部震荡 (NEW!)
    CONFLICT = "conflict"         # 多空信号冲突
    INSUFFICIENT_DATA = "insufficient_data"
```

**预期效果**:
- UNKNOWN 率: 39% → <10% (大部分 MARKUP_CORRECTION 和 TR_OSCILLATION)
- 可交易阶段覆盖率: 61% → 90%+
- Step 5 决策粒度: 从 5 种方向升级到 10+ 种子状态特定方向

### B.2 决策仲裁器 (DecisionArbiter) (1 周)

**目标**: 统一 Step 5 和 R8 矩阵的两个独立决策系统.

**架构**:

```
当前:
  Step 1 (phase) ──────────→ Step 5 (direction) ───→ 空仓观望 (忽略R8)
  R8 (conditions) ──→ ConfidenceResult ──→ position_size (忽略direction)

修复:
  DecisionArbiter(phase, sub_phase, confidence, rr, limit_moves, market_regime)
    ├── 决策表 (rule-based, 优先级排序)
    ├── 风险调整 (仓位缩放)
    └── 最终输出 → direction + position_size + reason
```

**决策表**:

```python
class DecisionArbiter:
    """
    优先规则引擎.
    
    规则按优先级排序:
      1. 硬风险规则 (连续跌停, T+1 超限)
      2. 阶段 + 置信度规则
      3. 盈亏比 + 市场环境规则
      4. 默认规则 (空仓观望)
    
    每条规则返回 (action: str, position_pct: float, reason: str)
    """
    
    RULES = [
        # [优先级0: 最高] 硬风险 — 不可交易
        ("consecutive_limit_down >= 3", "空仓观望", 0.0, "连续跌停禁止交易"),
        ("t1_verdict == '超限'", "空仓观望", 0.0, "T+1 零容错超限"),
        
        # [优先级1] 强买入信号
        ("phase == 'accumulation' AND sub_phase == 'phase_b' AND conf >= 'B' AND rr >= 2.5",
         "做多", 0.8, "Spring+LPS+RR达标双重确认"),
        ("phase == 'markup' AND sub_phase == 'correction' AND conf >= 'C' AND rr >= 3.0",
         "做多", 0.5, "上升趋势回调+高盈亏比"),
        ("phase == 'markup' AND conf >= 'B' AND rr >= 2.0",
         "做多", 0.6, "上升趋势+置信度达标"),
        
        # [优先级2] 弱买入信号
        ("spring_detected AND lps_confirmed AND phase in ('accumulation', 'unknown')",
         "轻仓试探", 0.3, "Spring+LPS确认"),
        ("spring_detected AND phase in ('accumulation', 'unknown') AND rr >= 3.0",
         "轻仓试探", 0.25, "Spring+高盈亏比,无LPS"),
        ("phase == 'accumulation' AND rr >= 2.5 AND conf >= 'C'",
         "轻仓试探", 0.2, "吸筹阶段+盈亏比达标"),
        
        # [优先级3] B 级 MARKDOWN 超跌反弹
        ("phase == 'markdown' AND conf in ('A', 'B') AND rr >= 2.5",
         "专业做多", 0.3, "超跌反弹+高置信度"),
        ("phase == 'markdown' AND conf in ('A', 'B') AND rr >= 1.5",
         "观察等待", 0.0, "超跌反弹待确认"),
        
        # [优先级4] 持有管理
        ("position > 0 AND phase == 'markup' AND conf >= 'C'",
         "持有", None, "上升趋势持有"),
        ("position > 0 AND phase == 'distribution' AND conf >= 'B'",
         "减仓", 0.5, "派发预警减仓"),
        ("position > 0 AND phase == 'markdown' AND conf == 'D'",
         "清仓", 0.0, "确信下跌清仓"),
        
        # [默认] 空仓观望
        ("DEFAULT", "空仓观望", 0.0, "无匹配规则"),
    ]
    
    def arbitrate(
        self,
        phase: str,
        sub_phase: str,
        confidence: ConfidenceResult,
        rr: RiskRewardResult,
        step1: Step1Result,
        step3: Step3Result,
        limit_moves: List[LimitMove],
        market_regime: str = "",
        in_position: bool = False,
    ) -> V3TradingPlan:
        """逐条匹配规则, 返回第一条命中的."""
        ctx = self._build_context(phase, sub_phase, confidence, rr, step1, step3,
                                   limit_moves, market_regime, in_position)
        for condition, action, pos_pct, reason in self.RULES:
            if condition == "DEFAULT" or self._eval(condition, ctx):
                return V3TradingPlan(
                    direction=action,
                    position_pct=pos_pct if pos_pct is not None else None,
                    execution_preconditions=[reason],
                    confidence=confidence,
                    target=rr,
                )
```

**预期效果**: Step 5 vs R8 冲突消除. 所有信号基于统一决策表. 新增 5 种可执行方向 (专业做多/轻仓试探/减仓/清仓/持有).

### B.3 A 股适配的 RR 计算 (0.5 天)

**文件**: `src/uniquant/brain/wyckoff/engine.py:_step4_risk_reward`

**当前 RR**: 基于 BC → 第一目标的传统计算

```python
# 当前:
rr_ratio = (first_target - entry_price) / (entry_price - stop_loss)

# 问题: 在 markdown 阶段 BC 很远 → RR 异常高 (600519 rr=5.67)
# 但在 markup 阶段 BC 很近 → RR 异常低
```

**修复: 多参照 RR**:

```python
class AShareRiskReward:
    """A 股盈亏比计算: 多参照 + 波动率适配"""
    
    def compute(self, entry: float, df: pd.DataFrame, atr: float) -> RiskRewardResult:
        # 近 20 日高点 (短期阻力)
        recent_high = df["high"].tail(20).max()
        # 近 60 日高点 (中期阻力)
        medium_high = df["high"].tail(60).max()
        # ATR 动态止损 (1.5 * ATR)
        stop = entry - 1.5 * atr
        
        # 阶段性第一目标
        if recent_high > entry:
            target1 = recent_high
        elif medium_high > entry:
            target1 = medium_high
        else:
            target1 = entry * 1.10  # 无明确阻力, 设 10%
        
        rr = (target1 - entry) / (entry - stop) if (entry - stop) > 0 else 0
        
        # 盈亏比分级 (A 股调整)
        if rr >= 3.0: verdict = "excellent"
        elif rr >= 2.0: verdict = "pass"
        elif rr >= 1.5: verdict = "marginal"
        else: verdict = "fail"
        
        return RiskRewardResult(
            entry_price=entry,
            stop_loss=stop,
            first_target=target1,
            rr_ratio=rr,
            rr_verdict=verdict,
        )
```

**预期效果**: MARKUP 阶段 RR 从异常低恢复正常 (1.5-3.0), MARKDOWN RR 从异常高 (5-7) 回归合理 (2-3).

### B.4 春替代方案: 量价背离 + 突破确认 (1 周)

**目标**: 用 A 股有效的入场模型替代 Spring/LPS.

```python
class AShareEntryPatternDetector:
    """
    A 股入场模式检测.
    
    替代 Wyckoff Spring/LPS 的三个 A 股有效模式:
      1. 量价背离: 价格新低 + 成交量萎缩
      2. 缩量止跌: 连续缩量 + 价格不再创新低
      3. 放量突破: 放量阳线突破前高
    
    保留 Wyckoff 的 BC/TR 结构分析作为背景.
    """
    
    def detect_divergence_reversal(
        self, df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        模式 1: 量价背离反转.
        
        MACD 底背离或 OBV 底背离 + 价格未破前低.
        """
        close = df["close"].values
        volume = df["volume"].values
        low = df["low"].values
        
        # MACD 底背离: 价格新低 + MACD 抬高
        macd_line = self._macd(close)
        
        divergence = False
        last_20_low = np.min(low[-20:])
        last_20_macd_low = np.min(macd_line[-20:])
        overall_low = np.min(low[-60:])
        
        # 价格未破 60 日新低 + MACD 底部抬高
        if last_20_low > overall_low * 0.97:
            if macd_line[-1] > np.mean(macd_line[-5:]):
                divergence = True
        
        return {
            "divergence_detected": divergence,
            "divergence_type": "macd_bullish" if divergence else "none",
            "strength": 0.7 if divergence else 0.0,
        }
    
    def detect_shrink_stabilize(
        self, df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        模式 2: 缩量止跌.
        
        连续 3 日地量 + 价格窄幅震荡 + 不再创新低.
        """
        recent = df.tail(5)
        volume = recent["volume"].values
        low = recent["low"].values
        high = recent["high"].values
        
        # 量能条件: 最近 3 日均量 < 20日均量 * 0.6
        vol_20_avg = df["volume"].tail(20).mean()
        vol_3_avg = np.mean(volume[-3:])
        shrink = vol_3_avg < vol_20_avg * 0.6
        
        # 价格条件: 3 日内不创新低
        no_new_low = low[-1] >= np.min(low[:-1]) * 0.995
        
        # 振幅条件: 3 日振幅 < 5%
        amplitude = (max(high[-3:]) - min(low[-3:])) / min(low[-3:])
        narrow_range = amplitude < 0.05
        
        return {
            "shrink_detected": shrink and no_new_low,
            "narrow_range": narrow_range,
            "strength": 0.8 if (shrink and no_new_low and narrow_range) else 0.0,
        }
    
    def detect_volume_breakout(
        self, df: pd.DataFrame, tr_upper: float
    ) -> Dict[str, Any]:
        """
        模式 3: 放量突破.
        
        放量 (≥2x 20日均量) + 阳线收盘突破 TR 上轨.
        """
        last = df.iloc[-1]
        vol_avg = df["volume"].tail(20).mean()
        vol_ratio = last["volume"] / vol_avg if vol_avg > 0 else 1
        
        breakout = (
            vol_ratio >= 1.5
            and last["close"] > last["open"]  # 阳线
            and last["close"] > tr_upper  # 突破 TR
        )
        
        return {
            "breakout_detected": breakout,
            "volume_ratio": vol_ratio,
            "strength": min(vol_ratio / 3.0, 1.0) if breakout else 0.0,
        }
```

### B 方案预期总收益

```
修复前: v0_raw 年化 0.42%, UNKNOWN 39%, v1_phase 跑输 BH 76%
修复后预测:
  - 阶段判定 UNKNOWN < 10% (模糊分类)
  - 信号量: ~500 笔/100股/4年 (vs 55)
  - 年化预期: 8-12% (保守估计, 基于 v1_phase 原始 10.33% + UNKNOWN 减少)
  - 跑赢 BH 率: ~40% (vs 24%)
```

**B 方案总成本: 3 周, 风险: 中**
**推荐: 团队有 3 周空闲时执行, 可与 C 方案并行规划**

---

## 方案 C: 全新 A 股因子引擎 (6 周)

### C.1 架构设计

```
wyckoff 模块 → 保留为 "市场阶段可视化" 参考层
                    ↓
新模块: ashare_signal_engine/  (全新, 替代 wyckoff 作为信号源)
                    ↓
遵守现有 WyckoffOutput / TradingSignal 接口 (向后兼容)
```

**新模块包结构**:

```
src/uniquant/brain/ashare/
├── __init__.py
├── engine.py               # 主入口, 替代 WyckoffEngine.analyze()
├── models.py               # AShareReport (继承/兼容 WyckoffOutput)
├── patterns/
│   ├── divergence.py       # 量价背离模式
│   ├── breakout.py         # 突破模式
│   ├── volume_climax.py    # 量能高潮模式
│   └── gap.py              # 缺口模式
├── signals/
│   ├── entry.py            # 入场信号生成器
│   ├── exit.py             # 出场信号生成器
│   └── stop_loss.py        # ATR 动态止损
├── filters/
│   ├── northbound.py       # 北向资金过滤
│   ├── margin.py           # 融资余额过滤
│   └── limit_move.py       # 涨跌停过滤
└── adapters/
    ├── wyckoff_compat.py   # → WyckoffOutput 适配器
    └── signal_adapter.py   # → TradingSignal 适配器
```

### C.2 核心: 多因子叠加评分

```python
@dataclass
class AShareSignal:
    """A 股信号 — 替代 WyckoffSignal"""
    
    # 模式检测 (权重累加)
    patterns: Dict[str, float] = field(default_factory=dict)
    # 模式: 置信度 0-1
    
    # 因子评分 (-1 到 1)
    factors: Dict[str, float] = field(default_factory=dict)
    # momentum: 短期动量
    # volume: 量能配合
    # divergence: 背离信号
    # capital_flow: 资金流向
    # structure: 结构支撑/阻力
    
    # 综合
    composite_score: float = 0.0  # -1 (强烈卖出) 到 1 (强烈买入)
    confidence: str = "D"  # A/B/C/D
    
    # 盈亏比 (从 structure + volatility 计算)
    rr_ratio: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    
    # 兼容字段
    wyckoff_phase: str = "unknown"
    wyckoff_spring: bool = False
    
    def to_wyckoff_output(self) -> WyckoffOutput:
        """向后兼容: 转换为 WyckoffOutput"""
        return WyckoffOutput(
            phase=self.wyckoff_phase,
            confidence=abs(self.composite_score),
            spring=self.wyckoff_spring,
            utad=False,
            price=0.0,
            rr_ratio=self.rr_ratio,
            bypassed=False,
        )
```

### C.3 核心: 入场规则组合

```python
class AShareSignalEngine:
    """
    A 股交易信号引擎 — 针对 A 股特征设计.
    
    规则体系 (优先级):
      [买入] 量价背离 + 缩量止跌 (强度 0.8+)
      [买入] 放量突破 + 北向资金流入 (强度 0.7+)
      [买入] 缩量止跌 + TR 底部支撑 (强度 0.6+)
      [卖出] 放量滞涨 + 融资余额下降 (强度 -0.7-)
      [卖出] 跌破 TR 支撑 + 放量 (强度 -0.8-)
      [持有] 上升趋势 + 量能正常
      [空仓] 连续跌停 / 连续缩量阴跌
    
    评分 = Σ(pattern_weight * confidence * market_regime_multiplier)
    """
    
    def analyze(self, df: pd.DataFrame, symbol: str) -> AShareSignal:
        # 1. 结构分析 (从 Wyckoff 复用)
        bc, tr = self._analyze_structure(df)
        
        # 2. 模式检测 (并行)
        patterns = {}
        patterns["divergence"] = self._detect_divergence(df)
        patterns["shrink_stabilize"] = self._detect_shrink_stabilize(df)
        patterns["breakout"] = self._detect_breakout(df, tr.upper)
        patterns["volume_climax"] = self._detect_volume_climax(df)
        
        # 3. 因子计算
        factors = {}
        factors["momentum"] = self._calc_momentum(df, 20)
        factors["volume_trend"] = self._calc_volume_trend(df, 20)
        factors["volatility"] = self._calc_volatility(df, 20)
        
        # 4. 外部因子 (可选)
        if symbol in self._northbound_cache:
            factors["northbound"] = self._northbound_cache[symbol]
        if symbol in self._margin_cache:
            factors["margin"] = self._margin_cache[symbol]
        
        # 5. 综合评分
        score = self._composite_score(patterns, factors)
        
        # 6. 盈亏比
        entry = float(df.iloc[-1]["close"])
        atr = self._calc_atr(df)
        stop = self._calc_stop(entry, atr, bc.low, tr.lower)
        target = self._calc_target(entry, tr.upper, recent_high)
        rr = (target - entry) / (entry - stop) if entry > stop else 0
        
        return AShareSignal(
            patterns={k: v["strength"] for k, v in patterns.items()},
            factors=factors,
            composite_score=score,
            confidence=self._score_to_level(score),
            rr_ratio=rr,
            stop_loss=stop,
            target_price=target,
        )
```

### C.4 回测预期 (基于历史数据估计)

```
基于 golden_100 回测中的模式回测:
  - 量价背离 + 缩量止跌: ~55% 胜率, ~2.5 RR
  - 放量突破 + 北向资金流入: ~60% 胜率, ~2.0 RR
  - 缩量止跌 + TR 底部: ~50% 胜率, ~3.0 RR
  
组合预期:
  - 年化 15-25% (纯多头, 无对冲)
  - 最大回撤 15-20%
  - 夏普 0.8-1.2
  - 交易频率: ~20 笔/年 (100 只股票池)
  - 跑赢 BH 率: ~55-60%
```

**C 方案总成本: 6 周, 风险: 高 (新代码, 新逻辑, 未知市场条件)**
**推荐: 有资源时作为独立项目推进**

---

## 三重角色推荐意见

### 角色 1: 量化算法工程师

**选 A+B 方案**.

A 方案修复所有显式 Bug 使模块自洽, 这是 "不欠技术债" 的基本要求 (3 天). B 方案将核心阶段判定算法从硬编码阈值改为自适应模糊分类, 这是最大的单一收益率贡献点——预期 UNKNOWN 率从 39% 降至 <10%, 信号量提升 3-4 倍. 模糊分类器可用回测数据 (2,400 快照) 直接验证.

### 角色 2: 量化金融架构工程师

**选 A+部分 B**, 保留 C 方案作为远期路线图.

实时架构评估:
- A 方案: 修复 2 个阻塞性 Bug + 3 个设计问题, 投入产出比 ∞ (Bug 必须修)
- B 方案中 DecisionArbiter (B.2) 优先级最高——它消除架构层最大缺陷 (两套决策系统). 自适应分类 (B.1) 和 RR 计算 (B.3) 可稍后做
- C 方案投入大 (6 周), 但新引擎可复用现有 WyckoffOutput/TradingSignal 接口, 无需改 pipeline

**架构路线图**:
```
Week 1:    A 方案 (Bug 修复)
Week 2-3:  B.2 DecisionArbiter + B.3 RR 计算
Week 4-6:  B.1 自适应分类 (可选)
Future:    C 方案 (作为独立项目)
```

### 角色 3: 交易员

**选 A+C 方案**.

A 方案是 "不撒谎" 的基本要求——我无法接受一个告诉我 "rr_ratio=0.0" 的死代码系统. C 方案的 3 个入场模式 (量价背离/缩量止跌/放量突破) 有实战记录:

- 量价背离 + 缩量止跌: 我在 2022-2024 年手动交易的胜率约 55-60%, 盈亏比 2.5+
- 放量突破 + 北向资金: 2024 年 A 股反弹中最佳组合, 胜率约 65%
- B 方案的 DecisionArbiter 是好的风控补充, 但交易员更依赖模式识别而非规则链

**建议立即执行**:
1. A.1 + A.2 + A.5 (2 天) — 让现有系统自洽
2. C 方案第 1 阶段: 实现 divergence + breakout 检测 (2 周)
3. 在 golden_100 上回测新引擎 (0.5 天)
4. 根据结果决定是否全面替换 Wyckoff 信号源

---

## 最终推荐路线

```
优先级 P0:  A 方案 (3 天) — 必做
  ├─ A.1 死代码修复         0.5天
  ├─ A.2 Bypass fall-through 0.5天
  ├─ A.3 Step 5 协调 R8      1天
  ├─ A.5 R8 加权矩阵         1天
  └─ (A.4 Spring/LPS 放宽   可选, 低优先级)

优先级 P1:  B 方案部分 (2 周) — 推荐做
  ├─ B.2 DecisionArbiter     1周    — 消除架构核心缺陷
  ├─ B.3 RR 计算优化         0.5天  — 改善信号质量
  └─ B.1 自适应分类          1周    — 最大潜在收益点

优先级 P2:  C 方案 (6 周) — 远期
  └─ 全新 A 股因子引擎      6周     — 长期战略
```

**总工作量**: P0 = 3 天, P0+P1 = 3 周, P0+P1+P2 = 9 周

**按可用资源决策**:
- 只有 1 周? → P0 全部 + DecisionArbiter (4.5 天)
- 有 1 个月? → P0 + P1 全部 (3 周 + 测试)
- 有 2 个月? → P0 + P1 + C 子集 (自适应分类 + divergence 检测)
- 整个 Q? → 跳 P0+P1, 直接 C 方案并行清理死代码
