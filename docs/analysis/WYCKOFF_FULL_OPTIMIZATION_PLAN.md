# Wyckoff 全链路优化方案 & 项目清单

**综合 5 轮红蓝对抗 + 7 个验证脚本 + 52,586 观测实证**
**参考文档**: v1-v3.1 方案, 经典对齐评估, 可行性验证, 研究管线对比

---

## 执行摘要

经过 5 轮红蓝对抗验证，Wyckoff 引擎的优化可归纳为 **3 个阶段、7 个任务**：

| 阶段 | 时间 | 核心目标 | 方向正确性 | 理论一致性 |
|------|------|---------|-----------|-----------|
| **S0: 紧急修复** | 1-2 天 | 修复分布偏差 | 1/4 → 2/4 | 50% → ~55% |
| **S1: 架构重构** | 5-7 天 | 修复方向反转 | 2/4 → **4/4** | ~55% → **65-70%** |
| **S2: 研究管线对齐** | 3-5 天 | 提升信号质量 | 4/4 维持 | 65-70% → **70-75%** |

**总工作量: 9-14 天，理论一致性提升: 50% → 70-75%**

---

## 阶段 S0: 紧急修复（1-2 天）

### 背景

验证表明当前引擎最明显的问题是**分布偏差**（accum 63.2%, markdown 7.1%），根源是 P&F 覆盖层。S0 修复已在 52K 观测上验证有效。

### 任务清单

| # | 任务 | 文件 | 代码量 | 验证指标 | 红蓝裁决 |
|---|------|------|--------|---------|---------|
| S0.1 | 移除 P&F 覆盖层 | `engine.py:_step1_phase_determine` | 5 行 | accum 63.2%→0.6% | ✅ 唯一有效修复 |
| S0.2 | Markdown rp≥0.15 约束 | `engine.py:_detect_markdown` | 10 行 | markdown 46.4%→11.4%, 方向 -0.55% | ✅ 最佳平衡点 |
| S0.3 | 市场状态自适应检测 | `market_state.py` (新增) + `engine.py` | 50 行 | 牛市 markup +4.61% | ⚠️ 部分有效 |

### S0 预期效果

| 指标 | 修复前 | 修复后 | 目标 |
|------|-------|-------|------|
| accum 占比 | 63.2% | **0.6%** | 3-8% |
| markup 占比 | 3.0% | **16.0%** | 12-18% |
| markdown 占比 | 7.1% | **11.4%** | 15-25% |
| markdown 方向 | +1.67% ❌ | **-0.55% ✅** | 负收益 |
| markup 方向 | -0.84% ❌ | **-1.55% ❌** | 正收益 |
| 理论一致性 | 50% | **~55%** | 65-70% |

### 验证命令

```bash
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _s0_verify
python3 scripts/wyckoff_multitf/v9_v3_validation.py
```

---

## 阶段 S1: 架构重构（5-7 天）

### 背景

S0 修复了分布偏差但未修复方向反转。S1 的核心是**反向共振**——这是首个在 52K 观测上实现 4/4 方向正确的方法。但需要校准 3/3 共振阈值来控制分布极端问题。

### 任务清单

| # | 任务 | 文件 | 代码量 | 工作量 | 前置 |
|---|------|------|--------|--------|------|
| S1.1 | 三周期独立分类器实现 | `monthly_classifier.py`, `phase_analysis.py` 已有 | 复用 | 0.5 天 | 无 |
| S1.2 | 反向共振接入相位判定 | `engine.py:_step1_phase_determine` | 30 行 | 0.5 天 | S1.1 |
| S1.3 | 3/3 共振阈值校准 | `phase_analysis.py:MultiTimeframeResonance` | 10 行 | 0.5 天 | S1.2 |
| S1.4 | 周线/日线分类器接线 | `engine.py:_analyze_single` | 20 行 | 1 天 | S1.1 |
| S1.5 | 因果链评分器实现 | `sequence.py:CausalChainScorer` (新增) | 150 行 | 2 天 | 无 |
| S1.6 | 因果链→相位映射 | `engine.py:_step1_phase_determine` | 30 行 | 1 天 | S1.5 |
| S1.7 | 3/3 共振 + 因果链联合 | `engine.py` | 20 行 | 0.5 天 | S1.3, S1.6 |

### S1.1 三周期分类器复用

**现状**: `MonthlyPhaseClassifier`, `WeeklyPhaseClassifier`, `DailyPhaseClassifier`, `MultiTimeframeResonance` 已在 `phase_analysis.py` 和 `monthly_classifier.py` 中完整实现且通过测试。

**接线方案**:

```python
def _analyze_single(self, df, symbol="", period="", ...):
    # 1. 三周期独立分类
    monthly_df = self._resample_monthly(df)  # 12 根月线
    weekly_df = self._resample_weekly(df)    # 12 根周线
    daily_df = df.tail(60)                   # 60 根日线

    monthly_phase = MonthlyPhaseClassifier().classify(monthly_df)
    weekly_phase = WeeklyPhaseClassifier().classify(weekly_df)
    daily_phase = DailyPhaseClassifier().classify(daily_df)

    # 2. 反向共振相位判定
    phase = self._reverse_resonance_phase(monthly_phase, weekly_phase, daily_phase)

    # 3. 因果链验证
    causal_phase = self._causal_chain_phase(df)
    if causal_phase != "unknown":
        phase = causal_phase  # 因果链优先

    return phase
```

### S1.2 反向共振相位判定

**验证结果**: 反向共振 4/4 方向正确，但 2/3 阈值太宽松。

**修正方案**: 使用 3/3 共振阈值:

```python
def _reverse_resonance_phase(self, monthly, weekly, daily):
    """反向共振相位判定。

    经典 Wyckoff: 共振 = 趋势确认
    A 股实证: 共振 = 反向指示（均值回归主导）
    """
    bullish = {"accumulation", "markup"}
    bearish = {"distribution", "markdown"}
    phases = [monthly, weekly, daily]
    bc = sum(1 for p in phases if p in bullish)
    bc2 = sum(1 for p in phases if p in bearish)

    if bc == 3:
        return WyckoffPhase.DISTRIBUTION  # 3/3 看多 → 强反转
    if bc2 == 3:
        return WyckoffPhase.ACCUMULATION  # 3/3 看空 → 强反转
    # 2/3 或冲突 → 交回因果链或月线
    return monthly
```

### S1.5 因果链评分器

**验证结果**: 简单趋势模型（t=13.138）的预测力是链式相位（t=0.379）的 35 倍，间接支持因果链假设。

**实现方案**:

```python
class CausalChainScorer:
    """经典 Wyckoff 因果链评分器 — 使用 LCS 算法匹配事件序列。"""

    ACCUMULATION_CHAIN = ['PS', 'SC', 'AR', 'ST', 'ST', 'Spring', 'SOS', 'LPS', 'JAC']
    DISTRIBUTION_CHAIN = ['PSY', 'BC', 'UTAD', 'LPSY', 'SOS']

    @classmethod
    def score(cls, event_types):
        """评分: [-1, 1], 信号: 'buy'/'sell'/'hold'."""
        accum_score = cls._lcs_match(event_types, cls.ACCUMULATION_CHAIN)
        dist_score = cls._lcs_match(event_types, cls.DISTRIBUTION_CHAIN)
        # ... 评分逻辑 ...

    @classmethod
    def _lcs_match(cls, events, chain):
        """LCS 算法计算事件序列与经典链的匹配度。"""
        m, n = len(events), len(chain)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if events[i-1] == chain[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        return dp[m][n] / len(chain)
```

### S1 预期效果

| 指标 | S0 后 | S1 后 | 验证基础 |
|------|-------|-------|---------|
| 方向正确性 | 2/4 | **4/4** | 反向共振 52K 验证 |
| markup 方向 | -1.55% ❌ | **+1.72% ✅** | 反向共振验证 |
| markdown 方向 | -0.55% ✅ | **-0.79% ✅** | 反向共振验证 |
| accum 分布 | 0.6% | **10-15%** | 3/3 阈值校准估计 |
| markup 分布 | 16.0% | **5-10%** | 3/3 阈值校准估计 |
| 理论一致性 | ~55% | **65-70%** | 研究管线基准 |

---

## 阶段 S2: 研究管线对齐（3-5 天）

### 背景

研究管线（`scripts/wyckoff_multitf/`）在 22,148 观测上达到 t=10.24, Sharpe 2.02，证明 Wyckoff 事件序列在 A 股有效。生产引擎有多个组件已实现但未启用。

### 任务清单

| # | 任务 | 文件 | 状态 | 工作量 |
|---|------|------|------|--------|
| S2.1 | WSS 查找表启用 | `sequence.py:WSSScorer.load()` | ✅ 代码已实现，`is_loaded` 恒 False | 0.5 天 |
| S2.2 | WSS 接入置信度评分 | `engine.py:_calc_confidence` | ❌ 未接线 | 1 天 |
| S2.3 | 共振过滤接入交易决策 | `engine.py:_build_report` | `MultiTimeframeResonance` 已实现 | 0.5 天 |
| S2.4 | Spring→买入信号传导修复 | `engine.py:_step5_trading_plan` | ❌ 66 只 Spring 0 只买入 | 1 天 |
| S2.5 | P&F 仅用于 TR 识别和目标价 | `engine.py:_step0_bc_tr_scan`, `_step4_risk_reward` | ✅ 已部分实现 | 0.5 天 |

### S2.1 WSS 查找表启用

**现状**: `WSSScorer` 已实现，训练好的 436 种序列查找表已存在，但 `is_loaded` 恒 False。

**修改**:

```python
class WSSScorer:
    def __init__(self, lookup_path=None):
        self.lookup = {}
        self.is_loaded = False
        if lookup_path and Path(lookup_path).exists():
            self.load(lookup_path)

    def load(self, path):
        with open(path) as f:
            self.lookup = json.load(f)
        self.is_loaded = len(self.lookup) > 0
```

**配置**:

```yaml
wyckoff:
  wss_enabled: true  # 默认开启
  wss_lookup_path: "scripts/wyckoff_multitf/output_v4/wss_lookup.json"
```

### S2.2 WSS 接入置信度评分

**现状**: 5 条件矩阵 → 84% D 档，0% A 档，与收益负相关。

**修改**:

```python
def _calc_confidence(self, events, seq_key, phase):
    # WSS 评分替代 5 条件矩阵
    scorer = WyckoffScorer(wss_lookup=WSS_LOOKUP)
    wss_score, signal = scorer.score_sequence(event_types, seq_key)
    # wss_score ∈ [-1, 1], 映射到置信度
    if wss_score >= 0.10: return ConfidenceLevel.A
    if wss_score >= 0.04: return ConfidenceLevel.B
    if wss_score >= -0.03: return ConfidenceLevel.C
    return ConfidenceLevel.D
```

### S2.4 Spring→买入信号传导修复

**现状**: 全量扫描 66 只 Spring 标的 0 只给出"买入"方向。研究管线证明 Spring 是最强单一事件（+3.00%, t=2.02）。

**修改**:

```python
def _step5_trading_plan(self, ...):
    # Spring 检测到 = 独立买入信号（研究管线验证）
    if spring_detected:
        return V3TradingPlan(
            direction="买入",
            entry_price=current_price,
            stop_loss=stop_loss,
            target=target,
            confidence=ConfidenceLevel.B,
            spring_signal=True,
        )
```

### S2 预期效果

| 指标 | S1 后 | S2 后 | 验证基础 |
|------|-------|-------|---------|
| 置信度分布 | 84% D | **< 50% D** | 研究管线 WSS 验证 |
| Spring→买入 | 0/66 | **66/66** | 研究管线 §4.3 |
| 信号质量 | — | **t~10, Sharpe~2** | 研究管线 Phase VII |
| 理论一致性 | 65-70% | **70-75%** | 综合估计 |

---

## 完整项目清单

### 优先级排序

```
P0 (紧急 - 1-2天) ⚠️
  ├── S0.1 移除 P&F 覆盖层
  ├── S0.2 Markdown rp≥0.15 约束
  └── S0.3 市场状态自适应检测

P1 (重要 - 5-7天) 🔴
  ├── S1.1 三周期分类器复用
  ├── S1.2 反向共振接入相位判定
  ├── S1.3 3/3 共振阈值校准
  ├── S1.4 周线/日线分类器接线
  ├── S1.5 因果链评分器实现
  ├── S1.6 因果链→相位映射
  └── S1.7 3/3 共振 + 因果链联合

P2 (提升 - 3-5天) 🟡
  ├── S2.1 WSS 查找表启用
  ├── S2.2 WSS 接入置信度评分
  ├── S2.3 共振过滤接入交易决策
  ├── S2.4 Spring→买入信号传导修复
  └── S2.5 P&F 仅用于 TR 识别和目标价
```

### 依赖关系图

```
S0.1 ──→ S0.2 ──→ S0.3
                      │
                      ▼
                S1.1 ──→ S1.2 ──→ S1.3
                  │                  │
                  ▼                  ▼
                S1.4               S1.7
                  │                  ▲
                  ▼                  │
                S1.5 ──→ S1.6 ──────┘
                                 │
                                 ▼
                    S2.1 ──→ S2.2 ──→ S2.3 ──→ S2.4 ──→ S2.5
```

### 文件修改清单

| 文件 | 修改内容 | 涉及任务 |
|------|---------|---------|
| `engine.py` | P&F 覆盖层移除, rp 约束, 反向共振, 因果链, WSS | S0.1, S0.2, S1.2, S1.6, S2.2 |
| `engine.py` | 市场状态参数, 三周期接线, Spring 传导 | S0.3, S1.4, S2.4 |
| `market_state.py` | 新增文件 | S0.3 |
| `phase_analysis.py` | 3/3 共振阈值校准 | S1.3 |
| `sequence.py` | 因果链评分器, WSS 加载修复 | S1.5, S2.1 |
| `events.py` | 无需修改 | — |
| `config.yaml` | WSS 开关, 共振阈值参数 | S2.1, S1.3 |

### 测试清单

| 测试文件 | 测试内容 | 涉及任务 |
|---------|---------|---------|
| 已有 132 个 classic_wyckoff 测试 | 更新用例 | 全部 |
| `test_phase5_pnf_v2.py` | 覆盖层移除 + rp 约束 | S0.1, S0.2 |
| `test_phase5_market_state.py` | 市场状态自适应 | S0.3 |
| `test_phase5_reverse_resonance.py` | 反向共振 3/3 阈值 | S1.2, S1.3 |
| `test_phase5_causal_chain.py` | 因果链评分器 | S1.5, S1.6 |
| `test_phase5_wss.py` | WSS 加载 + 评分 | S2.1, S2.2 |

### 验证命令

```bash
# 每次修改后
ruff check src/ tests/ scripts/           # 0 容忍
pytest tests/classic_wyckoff/ -q          # 全部通过

# S0 验证
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _s0

# S1 验证
python3 scripts/wyckoff_multitf/v9_feasibility_validation.py  # 方向性检查

# S2 验证
python3 scripts/wyckoff_multitf/runner_v3.py --max-stocks 1000 --output-suffix _s2
python3 scripts/wyckoff_multitf/v9_v3_validation.py           # 综合检查
```

### 回滚方案

```yaml
wyckoff:
  calibration:
    enabled: false          # 关闭所有修改
    pnf_override_removed: true  # S0.1
    markdown_rp: 0.15       # S0.2
    market_state: false     # S0.3
    reverse_resonance: false  # S1.2
    causal_chain: false     # S1.5
    wss_enabled: false      # S2.1
```

---

## 附录: 验证数据总结

### 5 轮红蓝对抗裁决

| 轮次 | 主题 | 裁决 | 关键发现 |
|------|------|------|---------|
| v1 原方案 | P&F 阈值收紧 | ❌ 红队胜 | 所有候选 kill P&F (99.9% unknown) |
| v1 原方案 | Phase 1 积累收紧 | ❌ 红队胜 | 链式积累仅 0.4%, 再收紧=0 |
| v2 修正 | P&F 校准阈值 | ❌ 红队胜 | 所有候选 99.8% unknown |
| v2 修正 | 方向反转 | 🔵 蓝队部分胜 | 时段依赖, 需市场状态感知 |
| v3 验证 | markdown rp 约束 | 🔵 蓝队部分胜 | rp=0.15 最佳 (11.4%, 方向 -0.55%) |
| v3 验证 | 市场状态自适应 | 🟡 红队部分胜 | 牛市 markup +4.61% ✅, 熊市仍 ❌ |
| 可行性 | P&F 投票 | 🟡 红队胜 | 不改善方向, P&F 仅用于 TR/目标价 |
| 可行性 | 反向共振 | 🔵 蓝队胜 | **4/4 方向正确**, 首次突破 |
| 可行性 | 因果链 | 🔵 蓝队部分胜 | 简单趋势模型 t=13.138 是链式 t=0.379 的 35 倍 |

### 7 个验证脚本

| 脚本 | 数据量 | 验证内容 | 关键输出 |
|------|--------|---------|---------|
| `v9_rb_validation.py` | 27K | P&F 覆盖层反事实 | 覆盖层是偏见根源 |
| `v9_v2_medium_validation.py` | 52K | 引擎上下文数据 | 52K 观测基准 |
| `v9_v2_diagnostic.py` | 52K | 方向反转深度分析 | 时段依赖性确认 |
| `v9_v3_validation.py` | 52K + CSI300 | 市场状态自适应 | 牛市 markup +4.61% |
| `v9_v2_pnf_grid.py` | (内嵌) | P&F 阈值网格搜索 | 所有候选 kill P&F |
| `v9_rb_bootstrap.py` | 27K | 统计显著验证 | 95% CI 确认 |
| `v9_feasibility_validation.py` | 52K | 反向共振 + 因果链 | 4/4 方向正确突破 |