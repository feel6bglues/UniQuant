# 经典 Wyckoff 分析的 Python 实现可行性报告

**评估目标**: 在现有代码基础上，实现经典 Wyckoff 分析的 4 个缺失核心组件
**评估基础**: `src/uniquant/brain/wyckoff/` 现有代码 + `scripts/wyckoff_multitf/` 研究管线

---

## 概述

经典 Wyckoff 分析的完整方法流程:

```
P&F 图表构建 → Trading Range 识别 → 事件序列检测 → 因果链分析 → 相位判定 → 目标价 → 交易决策
     ↓               ↓               ↓               ↓          ↓          ↓
    缺失            缺失            已实现          部分缺失    已实现     部分缺失
```

研究管线已经实现了**事件序列检测 → 评分 → 共振过滤 → 策略**的后半段，但缺少 P&F 图表、TR 识别、因果链的前半段。生产引擎有 P&F 和 TR 识别的代码，但未正确使用。

---

## 组件一: P&F 图表（已有代码，需重构）

### 现有代码

`src/uniquant/brain/wyckoff/pnf.py` — 260 行，已实现:

| 功能 | 方法 | 状态 | 经典 Wyckoff 要求 |
|------|------|------|-----------------|
| P&F 构建 | `build()` | ✅ 标准 3-box reversal | ✅ 正确 |
| 列统计 | `_column_stats()` | ✅ 返回每列 high/low | ✅ 正确 |
| 密集区识别 | `congestion_zone()` | ✅ TR 边界识别 | ✅ 正确 |
| 目标价计算 | `count_target()` | ✅ 水平计数法 | ✅ 正确 |
| 突破检测 | `breakout_detected()` | ✅ 双顶/双底突破 | ✅ 正确 |
| 相位提示 | `wyckoff_phase_hint()` | ⚠️ 阈值过紧 | ✅ 方向正确但需校准 |
| 参数 | `box_size=0.02, reversal=2` | ⚠️ 硬编码 | ✅ 需自适应 |

### 缺失功能

**1. P&F 作为相位判定的基础（非覆盖层）**

当前: P&F 在 `engine.py` 中作为事后附加，覆盖 63.2% 的相位判定。

改为: P&F 应作为**三周期分类器的输入之一**，与月线/周线/日线 OHLCV 分类器并列:

```python
def classify_with_pnf(df_ohlcv, df_pnf):
    # 方法 A: P&F 相位投票（使用 pnf 的 wyckoff_phase_hint）
    pnf_phase = pnf.wyckoff_phase_hint()

    # 方法 B: P&F 密集区 → TR 边界 → 价格在 TR 中的位置
    tr_lower, tr_upper = pnf.congestion_zone()
    price_position = (close - tr_lower) / (tr_upper - tr_lower) if tr_upper > tr_lower else 0.5

    # 方法 C: P&F 突破方向
    has_breakout, breakout_dir = pnf.breakout_detected()

    # 三票合一
    return vote(pnf_phase, price_position, breakout_dir)
```

**2. 自适应 box_size**

当前: `box_size=0.02, reversal=2` 硬编码。

改为: 按价格区间和板块自适应:

```python
def adaptive_box_size(price, board_type):
    # A 股价格分段: <10元 → 0.01, 10-50元 → 0.02, 50-200元 → 0.05, >200元 → 0.10
    if price < 10: return 0.01
    elif price < 50: return 0.02
    elif price < 200: return 0.05
    else: return 0.10
```

**3. P&F 增量更新**

当前: `build()` 每次全量重建（O(n)）。

改为: 支持单根 K 线追加（O(1)），适合实时分析:

```python
def append(self, bar: pd.Series):
    # 只用最后 1 根 OHLC 判断是否新增/反转 P&F 列
    # 避免每次全量重算
```

### 可行性评估

| 维度 | 评估 |
|------|------|
| 代码量 | ~100 行新增（自适应 box_size + 增量更新 + 投票接口） |
| 现有依赖 | pnf.py 全部可复用 |
| 工作量 | 1 天 |
| 风险 | 低 — 已有完整测试 |

---

## 组件二: Trading Range 识别（已有代码，需重构）

### 现有代码

**生产引擎** (`engine.py:_step0_bc_tr_scan`, 第 451-493 行):
- 使用 P&F `congestion_zone()` 作为 TR 边界
- 使用最近 60 日高低点作为 fallback
- 识别 BC/SC 点

**研究管线** (`monthly_classifier.py`):
- 使用 `range_pct = (hi/lo - 1) * 100` 作为波动率指标
- 阈值: 80%（月线）、25%（周线）
- 不识别 TR 边界

### 缺失功能

**1. 三周期 TR 识别**

经典 Wyckoff 要求月线/周线/日线三个周期的 TR 识别:

```python
class TradingRange:
    def __init__(self, upper, lower, source, duration, bars):
        self.upper = upper  # TR 上沿
        self.lower = lower  # TR 下沿
        self.source = source  # P&F / OHLCV / BC
        self.duration = duration  # TR 持续月数
        self.bars = bars  # TR 内的 K 线数

def identify_tr(df, period="monthly", pnf_zone=None):
    """三周期 TR 识别器。

    方法优先级:
      1. P&F congestion_zone (最精确)
      2. 最近 N 月/周/日的高低点 (fallback)
      3. BC/SC 点 (最终 fallback)
    """
    if pnf_zone:
        return TradingRange(*pnf_zone, "pnf", ...)

    # 按周期自适应 lookback
    lookback = {"monthly": 12, "weekly": 24, "daily": 60}[period]
    window = df.tail(lookback)
    upper = window["high"].max()
    lower = window["low"].min()
    range_pct = (upper - lower) / lower

    # 验证 TR 有效性: range_pct 不能太大
    threshold = {"monthly": 0.80, "weekly": 0.50, "daily": 0.30}[period]
    if range_pct <= threshold:
        return TradingRange(upper, lower, "ohlcv", lookback, lookback)
    return None
```

**2. TR 内的价格位置**

经典 Wyckoff 使用价格在 TR 中的位置判断 phase:

```python
def price_in_tr(close, tr):
    """价格在 TR 中的百分位 (0=下沿, 1=上沿)"""
    if tr is None:
        return 0.5
    return (close - tr.lower) / (tr.upper - tr.lower)
```

**3. TR 突破检测**

```python
def tr_breakout(close, tr, volume=None, vol_ma20=None):
    """检测 TR 突破。

    返回: ('up'/'down'/'none', confidence)
    """
    if tr is None:
        return ('none', 0.0)

    # 上突破: close > TR 上沿
    if close > tr.upper * 1.01:
        if volume and vol_ma20 and volume[-1] > vol_ma20 * 1.5:
            return ('up', 0.8)  # 放量突破
        return ('up', 0.5)  # 无量突破（可能假）

    # 下突破: close < TR 下沿
    if close < tr.lower * 0.99:
        if volume and vol_ma20 and volume[-1] > vol_ma20 * 1.5:
            return ('down', 0.8)  # 放量跌破
        return ('down', 0.5)

    return ('none', 0.0)
```

### 可行性评估

| 维度 | 评估 |
|------|------|
| 代码量 | ~150 行（TR 识别器 + 价格位置 + 突破检测） |
| 现有依赖 | engine.py 的 `_step0_bc_tr_scan` 可复用 |
| 工作量 | 1 天 |
| 风险 | 低 — TR 识别逻辑清晰 |

---

## 组件三: 共振反向指示（已有代码，已验证效果）

### 现有代码

**研究管线** (`phase_analysis.py:MultiTimeframeResonance`, 第 401-506 行):
- 完整实现: `resonance()`, `resonance_strength()`, `is_bullish_confirmed()`, `is_bearish_confirmed()`
- 已验证效果: 在 22,148 观测上，共振过滤贡献 +0.43% 多空跨距
- 研究管线发现: 共振是**反向指示**（三周期看多 = 顶部，三周期看空 = 底部）

**生产引擎**: `MultiTimeframeResonance` 已实现 + 测试，但未接入决策。

### 缺失功能

**1. 接入生产引擎的相位判定**

```python
def _step1_phase_determine(self, df, rule0, pnf_hint=None):
    # 1. 三周期独立分类
    monthly_phase = self._classify_monthly(df)
    weekly_phase = self._classify_weekly(df)
    daily_phase = self._classify_daily(df)

    # 2. 共振投票
    res = MultiTimeframeResonance.resonance(monthly_phase, weekly_phase, daily_phase)

    # 3. 共振反向指示接入相位判定
    if res['resonance_dir'] == 'bullish':
        # 三周期看多 = 顶部区域 → 倾向于 distribution/markdown
        phase = WyckoffPhase.DISTRIBUTION
    elif res['resonance_dir'] == 'bearish':
        # 三周期看空 = 底部区域 → 倾向于 accumulation/markup
        phase = WyckoffPhase.ACCUMULATION
    else:
        phase = monthly_phase  # 冲突时以月线为准

    return phase
```

**2. 接入交易决策**

```python
def _build_report(self, ...):
    # 共振过滤
    res = MultiTimeframeResonance.resonance(monthly_phase, weekly_phase, daily_phase)

    if signal_type == "buy" and res['resonance_dir'] == 'bullish':
        # 买入信号 + 共振看多 = 顶部追高，降级
        signal_type = "no_signal"
    elif signal_type == "sell" and res['resonance_dir'] == 'bearish':
        # 卖出信号 + 共振看空 = 底部割肉，降级
        signal_type = "no_signal"
```

### 可行性评估

| 维度 | 评估 |
|------|------|
| 代码量 | ~50 行接线（已实现，只需接入） |
| 现有依赖 | MultiTimeframeResonance 已实现 + 测试 |
| 工作量 | 0.5 天 |
| 风险 | 最低 — 已有完整测试 + 研究管线已验证效果 |

---

## 组件四: 因果事件链（已有部分代码，需扩展）

### 现有代码

**事件检测** (`events.py`, 517 行):
- 8 类事件检测器: `detect_ps()`, `detect_sc()`, `detect_ar()`, `detect_st()`, `detect_sos()`, `detect_lps()`, `detect_jac()`, `detect_spring()`
- 统一入口: `detect_all_events()` → 返回按日期排序的事件列表
- 序列键: `event_sequence_key()` → "PS>SC>AR>ST"

**事件评分** (`sequence.py`, 202 行):
- `WSOScorer`: 独立权重求和（PS=+0.0105, SC=+0.0094, AR=+0.0083, ST=+0.0052, SOS=-0.0137）
- `WSSScorer`: 已知训练好的 436 种序列查找表（但未加载）
- `WyckoffScorer`: 统一接口（WSO + WSS 融合）

### 缺失功能

**1. 经典事件序列因果链**

经典 Wyckoff 的事件序列不是"独立事件加权求和"，而是**因果链**:

```
积累序列: PS → SC → AR → ST → ST → Spring → SOS → LPS → JAC
派发序列: PSY → BC → UTAD → LPSY → SOS → JAC
```

每个序列有**方向性含义**:
- 完整积累序列: 底部确认，应上涨
- 中断的积累序列（PS→SC→无后续）: 底部未确认，仍可能下跌
- 完整派发序列: 顶部确认，应下跌

**因果链评分器**:

```python
class CausalChainScorer:
    """经典 Wyckoff 因果链评分器。

    不依赖独立权重，而是评估事件序列的完整性和顺序。
    """

    ACCUMULATION_CHAIN = ['PS', 'SC', 'AR', 'ST', 'ST', 'Spring', 'SOS', 'LPS', 'JAC']
    DISTRIBUTION_CHAIN = ['PSY', 'BC', 'UTAD', 'LPSY', 'SOS']

    @classmethod
    def score(cls, events: List[str]) -> Tuple[float, str]:
        """评分: [-1, 1], 信号: 'buy'/'sell'/'hold'."""
        seq_key = '>'.join(events)

        # 检查积累序列完整性
        accum_score = cls._chain_match(events, cls.ACCUMULATION_CHAIN)
        dist_score = cls._chain_match(events, cls.DISTRIBUTION_CHAIN)

        # 完整序列 vs 部分序列 vs 无序列
        if accum_score >= 0.7:
            return (0.8, 'buy')  # 完整积累序列 → 强买入
        elif dist_score >= 0.7:
            return (-0.8, 'sell')  # 完整派发序列 → 强卖出
        elif accum_score >= 0.4:
            return (0.3, 'buy')  # 部分积累 → 弱买入
        elif dist_score >= 0.4:
            return (-0.3, 'sell')  # 部分派发 → 弱卖出
        else:
            return (0.0, 'hold')

    @classmethod
    def _chain_match(cls, events, chain):
        """计算事件序列与经典链的匹配度 (0-1)。

        使用最长公共子序列 (LCS) 算法。
        """
        m, n = len(events), len(chain)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if events[i-1] == chain[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        lcs = dp[m][n]
        return lcs / len(chain) if chain else 0
```

**2. 事件序列的相位预测**

研究管线的 WSO 使用事件独立权重做交易信号。经典 Wyckoff 要求**事件序列决定相位**:

```python
def phase_from_events(events, seq_key):
    """根据事件序列判定相位。

    经典规则:
      - 完整积累序列 (PS→SC→AR→ST→ST) → ACCUMULATION
      - 积累 + 突破 (SOS→LPS→JAC) → MARKUP
      - 完整派发序列 (PSY→BC→UTAD) → DISTRIBUTION
      - 派发 + 跌破 (LPSY→SOS down) → MARKDOWN
    """
    if "PS" in seq_key and "SC" in seq_key and seq_key.count("ST") >= 2:
        return "accumulation"
    if "SOS" in seq_key and "JAC" in seq_key:
        return "markup"
    if "UTAD" in seq_key:
        return "distribution"
    if "SOS" in seq_key and "LPS" not in seq_key:
        # SOS 单独出现 → 均值回归陷阱
        return "markdown"
    return "unknown"
```

**3. WSS 查找表启用**

`WSSScorer` 已实现，训练好的 436 种序列查找表已存在，但 `is_loaded` 恒 False:

```python
class WSSScorer:
    def __init__(self, lookup_path=None):
        self.lookup = {}
        self.is_loaded = False
        if lookup_path:
            self.load(lookup_path)

    def load(self, path):
        with open(path) as f:
            self.lookup = json.load(f)
        self.is_loaded = len(self.lookup) > 0

    def score(self, seq_key, has_spring=False):
        if not self.is_loaded:
            return 0.0
        # 直接查找序列权重
        wss = self.lookup.get(seq_key, 0.0)
        if has_spring:
            wss += 0.025  # Spring 独立加分
        return wss
```

### 可行性评估

| 维度 | 评估 |
|------|------|
| 代码量 | ~200 行（因果链评分器 + 事件→相位映射 + WSS 启用） |
| 现有依赖 | events.py 的事件检测 + sequence.py 的 WSS 框架 |
| 工作量 | 1.5 天 |
| 风险 | 中 — 因果链评分器需要单元测试验证 |

---

## 综合实现路线图

### 依赖关系

```
P&F 重构 (1天) → TR 识别 (1天) → 三周期分类器 (1天) → 共振接入 (0.5天) → 因果链 (1.5天) → WSS 启用 (0.5天)
                                                                                ↓
                                                                          相位判定 (完成)
                                                                                ↓
                                                                          交易决策 (完成)
```

### 各阶段工作量

| 阶段 | 组件 | 代码量 | 工作量 | 前置依赖 |
|------|------|--------|--------|---------|
| P0 | P&F 自适应 box_size + 增量更新 | ~100 行 | 1 天 | 无 |
| P1 | TR 三周期识别器 | ~150 行 | 1 天 | P0 (P&F congestion_zone) |
| P2 | 三周期独立分类器 | ~200 行 | 1 天 | P1 (TR 识别作为分类器输入) |
| P3 | 共振接入相位判定 + 交易决策 | ~50 行 | 0.5 天 | P2 (三周期分类器) |
| P4 | 因果链评分器 + 事件→相位映射 | ~200 行 | 1.5 天 | 无 (基于现有 events.py) |
| P5 | WSS 查找表启用 | ~50 行 | 0.5 天 | 无 (查找表已训练好) |
| **总计** | **6 个组件** | **~750 行** | **5.5 天** | — |

### 实现后预期效果

| 指标 | 当前 (引擎) | v3.1 修复后 | 经典 Wyckoff 实现后 | 研究管线基准 |
|------|-----------|-----------|-------------------|------------|
| 相位分布 | accum 63%, md 7% | accum 0.6%, md 10% | accum 3-8%, md 25-40% | accum 3%, md 43% |
| 理论一致性 | 50% | ~55% | **65-70%** | 50% (引擎) |
| markup 方向 | -1.64% | -1.55% | **+3~8%** | +11.19% |
| markdown 方向 | +2.27% | -0.55% | **-3~-8%** | -3.81% |
| 多空跨距 | 无 | 未测量 | **+5~8%** | +8.07% |
| 置信度分布 | 84% D | 84% D | **连续分布** | 连续 |
| TR 识别 | 60 日高低点 | 60 日高低点 | **P&F + 三周期** | 无 |

### 与 v3.1 的关系

v3.1 的 3 处修改（覆盖层移除 + rp 约束 + 市场状态）是**短期修复**，解决最明显的分布偏差。经典 Wyckoff 实现是**中期重构**，从根本上解决相位质量问题。

两者可以并行进行:
- v3.1: 1-2 天，修复分布偏差
- 经典 Wyckoff: 5.5 天，修复相位质量

v3.1 的覆盖层移除是经典 Wyckoff 实现的前提条件（P&F 必须从覆盖层降级为投票输入之一）。

### 风险与注意事项

| 风险 | 描述 | 缓解措施 |
|------|------|---------|
| P&F 在 A 股的有效性 | P&F 图表在 A 股（T+1, 涨跌停）可能效果不如美股 | 保留 OHLCV 分类器作为 fallback，P&F 作为投票输入 |
| 共振反向指示的稳定性 | 研究管线发现共振反向指示，但该结论基于 2020-2024 数据 | 需要 walk-forward 验证，在不同市场环境下测试 |
| 因果链的过拟合 | 经典 9 事件序列在 A 股可能不完整 | WSS 统计权重作为因果链的补充，两者融合评分 |
| 三周期数据的可用性 | 月线需要 12 个月数据，新上市股票不足 | 不足时自动降级为双周期或单周期 |