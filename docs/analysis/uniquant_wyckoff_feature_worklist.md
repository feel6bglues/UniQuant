# UniQuant Wyckoff 未实现功能完整工作列表

> 编制日期: 2026-06-27 | 编制视角: 量化金融架构师 × 算法工程师 × Python 程序员
> 依据: 设计文档 docx 声明 vs 实际代码审计（15 个生产文件 + 27 个研究脚本 + 44 个测试用例）+ 86,436 观测实证结果
> 状态锁定: 当前已有 1,255 个测试通过，基线 100% 一致

---

## 编制总纲

### 分级标准

| 优先级 | 标签 | 定义 | 示例 |
|--------|------|------|------|
| **P0** | 强制实现 | 设计文档核心承诺，代码中完全缺失 | P&F 点数图 |
| **P1** | 高价值 | 可量化改进现有信号系统，实证可验证 | Numba 加速、EMA 平滑 |
| **P2** | 研究扩展 | ML/AI 方法，需独立验证边际增益 | CNN、RL、贝叶斯 |
| **P3** | 工程优化 | 非功能改进，不影响信号逻辑 | 代码组织、测试覆盖 |

### 工作量估算

| 级别 | 代码量 | 典型耗时 | 不确定性 |
|------|:------:|:--------:|:--------:|
| S | < 50 行 | 1-2 小时 | 低 —— 纯工程改动 |
| M | 50-200 行 | 0.5-1 天 | 中 —— 需调参验证 |
| L | 200-500 行 | 2-5 天 | 高 —— 需独立训练 |
| XL | > 500 行 | 1-3 周 | 很高 —— 需完整 pipeline |

### 收益评分（0-10）

- **信号增益**: 预期对 WSO/WSS 多空跨距的贡献（基于 Phase VII 回测框架可验证）
- **架构完整度**: 填补设计文档 vs 实现差距的程度
- **可验证性**: 能否在现有 86K 观测数据上直接 A/B 测试

---

## 功能清单

---

### Phase 1 — 快速实现（高确定性收益）

#### 1.1 P&F 点数图模块

| 属性 | 内容 |
|------|------|
| **优先级** | **P0** |
| **工作量** | M (~150 行) |
| **收益评分** | 信号增益 6 | 架构完整度 9 | 可验证性 8 |
| **依赖** | 现有日线 Parquet 数据湖 |
| **风险** | 低 — 纯算法，无模型调参 |
| **文件路径** | `src/uniquant/brain/wyckoff/pnf.py`（新增） |
| **适配器** | 新增 `pnf` 键到 `AnalysisService` 的 `analysis_result` |

**编制依据**:
- 设计文档 §3"因果法则"中明确宣称"点数图（P&F）算法得到了极为精密的工程化实现"
- 代码审计结果: `rg "point.*figure|pnf|p&f|点数图" src/` → **0 匹配**
- 设计文档声称 P&F 是 "衡量因果关系的核心工具"，但实证报告中的 WSS/WSO 并不依赖 P&F，说明 P&F 是独立可验证的附加信号源
- P&F 的 box 反转算法与现有日线数据完全兼容，可通过 86K 观测做独立回测比较

**实现方案**:

```python
# pnf.py — 核心数据结构与算法
@dataclass
class PnFBox:
    """点数图单格"""
    price_level: float
    column_index: int
    is_x: bool  # True=X列(上涨), False=O列(下跌)

class PointAndFigure:
    """点数图引擎 — 支持高/低/收盘价三种输入模式"""
    
    def __init__(self, box_size: float = 0.01, reversal: int = 3):
        # box_size: 每格价格幅度（ATR百分比或固定百分比）
        # reversal: 反转所需格数（标准=3）
    
    def build(self, ohlc: pd.DataFrame) -> List[PnFBox]:
        """从OHLC构建P&F列序列"""
    
    def count_target(self) -> float:
        """水平计数法：横盘列数 → 目标价位"""
    
    def breakout_detected(self) -> bool:
        """检测P&F突破信号"""
    
    def wyckoff_phase_hint(self) -> str:
        """基于P&F的吸筹/派发阶段提示"""
```

**验证方案**:
1. 在现有 86,436 观测上计算每个观测截止日的 P&F 信号
2. 与 f6 前向收益做点双列相关
3. 与 WSO 信号做叠加对比：P&F+WSO vs WSO 独立的多空跨距

---

#### 1.2 Numba 加速事件检测器

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | S (~20 行改动) |
| **收益评分** | 信号增益 0 | 架构完整度 3 | 可验证性 10 |
| **依赖** | `numba` 包（已在 `pyproject.toml` 中可选） |
| **风险** | 极低 — numba 对 numpy 循环有 >10× 加速 |
| **文件** | `src/uniquant/brain/wyckoff/events.py` |

**编制依据**:
- `events.py` 中 `detect_ps()`(Line 63-114)、`detect_sc()`(Line 117-171)、`detect_sos()`(Line 266-309) 均有显式 for 循环逐 i 扫描
- 每日筛选 Pipeline（`wyckoff_daily_screen.py`）对 5,856 只股票 × 每只运行 `detect_all_events`，for 循环在 `ProcessPoolExecutor` 下成为瓶颈
- 设计文档声称"Numba 底层库批量计算"，但实际代码 0 行 numba
- `@njit` 装饰器对 numpy 数组操作可以无侵入加速 5-20×，无需改变算法逻辑

**改动方案**:

```python
from numba import njit

# 将核心评分循环提取为 numba 函数
@njit(cache=True)
def _score_ps_numba(close, high, low, open_, volume, vol_ma20):
    """Numba 加速的 PS 评分循环"""
    n = len(close)
    scores = np.zeros(n)
    # ... 原 for 循环逻辑
    return scores
```

**验证方案**: 对比加装饰器前后 5,856 只股票的 `detect_all_events` 执行时间。

---

#### 1.3 WSO EMA 平滑

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | S (~10 行改动) |
| **收益评分** | 信号增益 5 | 架构完整度 7 | 可验证性 9 |
| **依赖** | 无 |
| **风险** | 极低 — 现有 WSOScorer 的 `score_events` 返回瞬时分，EWMA 是标准降噪 |
| **文件** | `src/uniquant/brain/wyckoff/sequence.py` |

**编制依据**:
- 设计文档 §"数值映射方法（WSO）"明确: "对离散的得分序列在时间轴上应用指数加权移动平均（EMA），计算出平滑的综合得分 WSO"
- 代码审计: `WSOScorer.score_events()` 返回 `raw = base + seq_bonus + sos_penalty + spring_adj` — **完全无时序平滑**
- 实证报告显示 WSO 单因子 t=6.25（买入），加上 EMA 平滑后可预期减少噪声触发
- `wyckoff_daily_screen.py` 按天运行，天然有时序连续性，适合 EMA

**改动方案**:

```python
class WSOScorer:
    # 新增类变量
    EMA_SPAN: int = 5  # 指数衰减周期
    
    def __init__(self):
        self._last_score: float = 0.0
        self._is_warm: bool = False
    
    def score_events(self, ...) -> float:
        raw = super().score_events(...)
        if not self._is_warm:
            self._last_score = raw
            self._is_warm = True
            return raw
        smoothed = raw * (2/(self.EMA_SPAN+1)) + self._last_score * (1 - 2/(self.EMA_SPAN+1))
        self._last_score = smoothed
        return smoothed
```

**验证方案**: 在 Phase VII 回测中对比 RAW-WSO vs EMA-WSO 的多空跨距和信号数量压缩比。

---

### Phase 2 — 核心研究增强（中等收益确定性）

#### 2.1 贝叶斯概率云模型（轻量版）

| 属性 | 内容 |
|------|------|
| **优先级** | **P2** |
| **工作量** | L (~300 行) |
| **收益评分** | 信号增益 5 | 架构完整度 10 | 可验证性 7 |
| **依赖** | `scipy`（已安装）、或 `pymc`（额外） |
| **风险** | 中 — 模型设计与当前规则系统需要兼容，需评估边际增益 |
| **文件** | `src/uniquant/brain/wyckoff/bayesian_events.py`（新增） |

**编制依据**:
- 设计文档 §"概率云叠加态"是整个方法论的核心创新点，但代码中完全无实施
- 当前 sigmoid 置信度是**静态独立评分**，不包含时序累积证据
- 轻量方案不依赖 MCMC 采样，用 `scipy.stats` 的 Beta 分布做在线更新，保持可解释性
- 现有 86K 观测提供了充分的先验分布估计

**实现方案**:

```python
class BayesianEventDetector:
    """
    轻量贝叶斯事件检测器
    
    不替代现有 events.py, 而是在其上叠加时序后验更新层。
    将每根 K 线的 sigmoid 评分视作似然函数 P(score | event)，
    利用 Beta 分布做在线贝叶斯更新。
    """
    
    def __init__(self, prior_alpha: float = 1.0, prior_beta: float = 1.0):
        # 先验: 基于 86K 观测的 event 先验发生率
        self.posteriors: Dict[str, Beta] = {}
    
    def update(self, event_type: str, score: float, confidence: float):
        """在线后验更新"""
        # 将 sigmoid 置信度映射为观测计数
        pseudo_obs = confidence * 10
        new_alpha = self.posteriors[event_type].a + pseudo_obs * max(0, score)
        new_beta = self.posteriors[event_type].b + pseudo_obs * (1 - abs(score))
        self.posteriors[event_type] = Beta(new_alpha, new_beta)
    
    def collapse_probability(self, event_type: str, threshold: float = 0.8) -> bool:
        """概率坍缩判定 — 后验概率 > 阈值时坍缩为确定事件"""
        return self.posteriors[event_type].mean() > threshold
```

**验证方案**: 
1. 将贝叶斯后验作为 WSO 权重的调节系数
2. 对比 `贝叶斯调节 WSO vs 纯 WSO` 在 86K 观测上的多空跨距和信号压缩比
3. 特别关注：是否降低了 2020 COVID 窗口的误报率

---

#### 2.2 多体制相位分类器（升级版）

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | M (~150 行) |
| **收益评分** | 信号增益 7 | 架构完整度 5 | 可验证性 9 |
| **依赖** | 现有 Phase I 结果（86K 观测已标记相位） |
| **风险** | 低 — 纯规则优化，步进可测 |
| **文件** | `src/uniquant/brain/wyckoff/phase_analysis.py` + `scripts/wyckoff_multitf/regime_detector.py` 集成 |

**编制依据**:
- 当前 `MonthlyPhaseClassifier` 使用固定阈值（tr < -15, rp < 80 等），但 86K 观测已显示年际体制极端差异（2015 f6 中位数 -13.66% vs 2024 +5.16%）
- session report §7 显示买入信号的体制依赖性——卖出信号跨体制稳定但买入信号需要体制过滤器
- 当前 `MarketRegimeDetector` 只基于 CSI 300，未与个股相位联动
- 设计文档强调"多周期共振质询"，但当前共振只有 3 个状态（bullish/bearish/conflicting），没有**强度量化**

**实现方案**:

```python
class RegimeAwarePhaseClassifier:
    """体制自适应相位分类器"""
    
    def __init__(self):
        self.market_regime = MarketRegimeDetector()
    
    def classify(self, df, date):
        regime = self.market_regime.classify(date)  # bull/bear/neutral
        
        # 根据体制动态调整相位阈值
        if regime == 'bull':
            accumulation_threshold = -0.02  # 牛市更容易识别为accumulation
            markup_threshold = 0.03
            markdown_threshold = -0.07  # 更严格
        elif regime == 'bear':
            accumulation_threshold = -0.05  # 更严格
            markup_threshold = 0.05
            markdown_threshold = -0.02  # 更宽松
        
        return self._classify_with_thresholds(df, accumulation_threshold, ...)
```

**验证方案**: 在 86K 观测上回测体制自适应相位 vs 固定阈值的 f6 区分度（卡方检验）。

---

#### 2.3 WSS 集成到每日管道

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | M (~80 行) |
| **收益评分** | 信号增益 4 | 架构完整度 6 | 可验证性 8 |
| **依赖** | `output_v4/wss_lookup_v2.json`（已有） |
| **风险** | 低 — 纯集成工作 |
| **文件** | `scripts/wyckoff_multitf/wyckoff_daily_screen.py` |

**编制依据**:
- session report §10.3 明确记录: "wss_lookup_v2.json 已生成，但 WyckoffScorer 尚未在每日管道中启用 WSS 融合评分"
- 当前 `wyckoff_daily_screen.py:89` 仅使用 `WSOScorer()`（纯 WSO），未加载 WSS 查找表
- research report §8.3 证明: WSO+WSS 多空跨距比纯 WSO 提升 +0.17%（7.47% → 7.64%）
- 这是**已生成数据但未消费的研究资产**，集成 ROI 极高

**改动方案**:

```python
# 当前代码（第89行）
scorer = WSOScorer()

# 改为
WSS_PATH = "scripts/wyckoff_multitf/output_v4/wss_lookup_v2.json"
scorer = WyckoffScorer(wss_path=str(PROJECT_ROOT / WSS_PATH))
```

**验证方案**: 对比每日管道启用 WSS 前后的 top-50 信号命中率（需跟踪后验 f6）。

---

#### 2.4 V 型反转检测器（2020 COVID 补丁）

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | S (~60 行) |
| **收益评分** | 信号增益 6 | 架构完整度 4 | 可验证性 6 |
| **依赖** | 现有日线数据 |
| **风险** | 低 — 独立检测器，不影响现有逻辑 |
| **文件** | `scripts/wyckoff_multitf/regime_detector.py`（扩展）或独立模块 |

**编制依据**:
- session report §7.2: 2020 COVID 窗口是 6 个体制中**唯一卖出信号失效窗口**（卖出 f6 -12.53%，α 衰减 -39.00）
- session report §10.3: "建议加入 V 型反弹检测器或在 MarketRegimeDetector 中加入极端反转标记"
- 这是一个**可定位、可修补**的已知盲点，非系统性缺陷

**实现方案**:

```python
class VShapedReversalDetector:
    """检测 V 型急速反转行情 — 用于标记 Wyckoff 卖出信号的失效区间"""
    
    def detect(self, index_df: pd.DataFrame, lookback: int = 60) -> Dict:
        """返回 '{date}: 'v_top' | 'v_bottom' | none'"""
        # 计算近 N 日最大回撤和最大反弹速度
        # 条件: 跌幅 > 15% 且在 10 日内反弹过半 → v_bottom
        # 条件: 涨幅 > 15% 且在 10 日内回撤过半 → v_top
        # 在 v_top 区间，卖出信号置信度需人工降级
```

---

### Phase 3 — ML/AI 研究（高不确定性，长周期）

#### 3.1 GAF + CNN 事件分类器

| 属性 | 内容 |
|------|------|
| **优先级** | **P2** |
| **工作量** | L (~400 行 + 训练周期) |
| **收益评分** | 信号增益 4 | 架构完整度 8 | 可验证性 5 |
| **依赖** | `torch` + `pyts`（额外 pip），建议 GPU |
| **风险** | 高 — 需独立训练-验证-测试拆分，可能不如规则系统 |
| **文件** | `src/uniquant/brain/wyckoff/cnn_classifier.py`（新增） |

**编制依据**:
- 设计文档 §"格拉姆角场（GAF）转换为二维图像矩阵→CNN"声称为最优解
- 现有 86K 观测 × 120 日窗口可作为有监督训练样本（以实际 f6 正负为标签）
- 需注意: 规则系统已有 t=10.24 效果，CNN 需要显著超越此基线才值得替换
- 更适合作为**补充特征**而非替代规则系统

**实现路径**:
1. 将 86K 观测切片为 120×5（OHLCV）矩阵
2. 用 `pyts.image.GramianAngularField` 变换为 RGB 图像
3. 训练 ResNet-18 迁移学习分类器（买入/卖出/持有）
4. 对比 CNN 信号 vs WSO+WSS 的 f6 多空跨距

---

#### 3.2 RL 交易智能体（回测环境）

| 属性 | 内容 |
|------|------|
| **优先级** | **P3** |
| **工作量** | XL (~600 行 + 训练周期) |
| **收益评分** | 信号增益 3 | 架构完整度 9 | 可验证性 4 |
| **依赖** | `stable-baselines3` + `gym` |
| **风险** | 很高 — RL 在金融时间序列上的过拟合风险极大，需严格 OOS |
| **文件** | `src/uniquant/brain/wyckoff/rl_agent.py`（新增） |

**编制依据**:
- 设计文档 §"Q-learning 交易智能体"完整描述，但代码中不存在
- 实证研究表明 RL 在 A 股日频数据上很难超越简单规则系统（高信噪比环境）
- 考虑到当前规则系统的实证有效性，RL 应该以当前 WSO/WSS 信号为**状态特征**而非替代它们
- 优先级 P3：只有在 P&F、贝叶斯、CNN 都确认边际增益后，RL 才有意义

**建议状态空间**:
```
WSO_score, WSS_score, resonance_dir, regime, PnF_signal, n_events
→ 离散动作: BUY(100%), BUY(50%), HOLD, SELL(50%), SELL(100%)
→ 奖励: f6_return - cost_penalty - drawdown_penalty
```

---

### Phase 4 — 工程加固（维护性改进）

#### 4.1 AShareConstraints 可交易率修复

| 属性 | 内容 |
|------|------|
| **优先级** | **P1** |
| **工作量** | S (~30 行) |
| **收益评分** | 信号增益 3 | 架构完整度 2 | 可验证性 9 |
| **风险** | 低 — 已知 bug，fix 明确 |
| **文件** | `scripts/wyckoff_multitf/ashare_constraints.py` |

**编制依据**:
- session report §10.3: "AShareConstraints 可交易率 100% 可能包含停牌或涨跌停股票"
- 审计确认: `ashare_constraints.py:53` 中使用 `pct > 9.4` 判定涨跌停，但科创板（20%）和北交所（30%）涨跌幅不同
- `can_trade()` 方法未检查股票所属板块

**修复方案**:

```python
def _get_limit_pct(symbol: str) -> float:
    if symbol.endswith('.SH'):
        code_num = int(symbol.split('.')[0])
        if code_num >= 688000:
            return 0.20  # 科创板
    elif symbol.endswith('.SZ'):
        code_num = int(symbol.split('.')[0])
        if code_num >= 300000:
            return 0.20  # 创业板
    # 北交所 8XXXXX
    return 0.10  # 主板

def can_trade(self, symbol, date, daily):
    limit_pct = _get_limit_pct(symbol)
    # 使用动态涨跌幅阈值
    if pct > limit_pct * 0.94:  # 留 0.5% 误差
        return False, "limit_up"
```

---

#### 4.2 测试覆盖补全

| 属性 | 内容 |
|------|------|
| **优先级** | **P3** |
| **工作量** | M (~150 行测试) |
| **收益评分** | 信号增益 0 | 架构完整度 4 | 可验证性 10 |
| **文件** | `tests/test_wyckoff_events.py`、`tests/test_phase_analysis.py` 等 |

**编制依据**:
- 当前 44 个 Wyckoff 测试主要覆盖 `models.py` 的 dataclass 默认值和 `engine.py` 边界 case
- `events.py` 的 `detect_all_events` **没有单元测试**——8 个检测器只有集成测试覆盖
- `sequence.py` 的 WSOScorer/WSSScorer/WyckoffScorer 无独立测试
- 所有 Phase 研究脚本（phase1-phase8）无测试

**优先级说明**: P3 是因为这些代码已经在生产运行（86K 观测验证），未触发 bug，但新增功能时缺乏测试保护。

---

#### 4.3 Cost Model 集成到信号管道

| 属性 | 内容 |
|------|------|
| **优先级** | **P2** |
| **工作量** | S (~40 行) |
| **文件** | `scripts/wyckoff_multitf/wyckoff_daily_screen.py` + `src/uniquant/shared/cost_model.py` |

**编制依据**:
- `cost_model.py` 已有完整的 A 股交易成本函数（佣金 0.03% + 印花税 0.05% + 过户费 0.001% + 滑点 0.05%）
- 但每日信号管道 `wyckoff_daily_screen.py` 输出中**不包含交易成本后的预期收益**
- research report §9 证明 0.182% 成本对 t 统计量影响极小，但不影响在管道中增加成本列

---

## 四、实施路线图

```
Phase 1（1-2 周）                    Phase 2（2-4 周）                    Phase 3 & 4（机动）
┌─────────────────────┐      ┌──────────────────────────┐      ┌──────────────────────────┐
│ 1.1 P&F 点数图       │ ──→  │ 2.1 贝叶斯概率云          │ ──→  │ 3.1 GAF+CNN 实验         │
│ 1.2 Numba 加速       │      │ 2.2 体制自适应相位        │      │ 3.2 RL 实验              │
│ 1.3 WSO EMA 平滑     │      │ 2.3 WSS 集成每日管道      │      │ 4.1 可交易率修复         │
│                      │      │ 2.4 V 型反转检测器        │      │ 4.2 测试覆盖             │
│ 每项都带独立验证       │      │                          │      │ 4.3 Cost 集成            │
│ 与 86K 基线对比       │      │ 每项与 Phase 1 做叠加对比 │      │                          │
└─────────────────────┘      └──────────────────────────┘      └──────────────────────────┘
        ↓                            ↓                                   ↓
  基线对比:                     叠加对比:                            最终系统:
  P&F vs 无P&F                P&F+Bayes+WSS vs 纯WSO              全栈信号链
  WSO-EMA vs WSO-RAW          多空跨距 + t统计量                     ~10 个独立信号维度
```

### 决策门（Gate Check）

每个 Phase 结束时执行：

| 门 | 判断标准 | 通过则... | 不通过则... |
|----|---------|----------|-----------|
| G1 | P&F 信号的 f6 t-test p < 0.05 | 进入 Phase 2 | 搁置 P&F，进入 Phase 2 但下调其权重 |
| G2 | Bayes 调节后多空跨距提升 > 0 | 保留 Bayesian 层 | 移除 Bayesian 层，使用纯规则系统 |
| G3 | CNN 多空跨距 > 规则系统 80% | 进入 RL 实验 | 终止 ML 路线，回归规则系统优化 |

---

## 五、验证框架

每个功能模块必须通过以下验证才能标记为 "完成"：

### 验证清单

- [ ] **单元测试**: 核心算法独立测试（pytest，覆盖率 > 90%）
- [ ] **集成测试**: 与现有 8 类事件检测器 + WSO/WSS 链的端到端测试
- [ ] **回归测试**: `pytest tests/ -q` 必须全部通过（当前 1,255 个）
- [ ] **基线对比**: 新功能输出与现有 86K 观测基线对齐
- [ ] **统计显著性**: 新增信号的 f6 均值差异的 t 检验 p < 0.05
- [ ] **鲁棒性检验**: 在 6 个体制度窗口中至少 4 个保持有效

### 对比模板

```python
# 每个新模块的标准化验证
baseline = load_baseline("output_v4/v4_results.json")  # 86K 观测
new_results = run_with_new_module(baseline, new_module)

for regime in ['2015_crash', '2018_tradewar', '2020_covid', 
               '2021_recovery', '2022_tightening', '2023_bear']:
    bl_signals = baseline.filter(regime=regime, signal='sell')
    new_signals = new_results.filter(regime=regime, signal='sell')
    
    print(f"{regime}: baseline={bl_signals.f6_mean:.2f}% "
          f"new={new_signals.f6_mean:.2f}% "
          f"Δ={new_signals.f6_mean - bl_signals.f6_mean:+.2f}%")
```

---

## 六、文件清单

### 新增文件

| 文件路径 | 功能 | Phase | 预计行数 |
|---------|------|:-----:|:-------:|
| `src/uniquant/brain/wyckoff/pnf.py` | P&F 点数图模块 | 1 | ~150 |
| `src/uniquant/brain/wyckoff/bayesian_events.py` | 贝叶斯概率云模型 | 2 | ~300 |
| `src/uniquant/brain/wyckoff/cnn_classifier.py` | GAF+CNN 分类器 | 3 | ~200 |
| `src/uniquant/brain/wyckoff/rl_agent.py` | RL 交易智能体 | 3 | ~300 |
| `scripts/wyckoff_multitf/v_shape_detector.py` | V 型反转检测器 | 2 | ~60 |

### 修改文件

| 文件路径 | 修改内容 | Phase | 预计改动 |
|---------|---------|:-----:|:-------:|
| `src/uniquant/brain/wyckoff/events.py` | numba `@njit` 装饰器 | 1 | ~20 行 |
| `src/uniquant/brain/wyckoff/sequence.py` | `WSOScorer` 增加 EMA 状态 | 1 | ~15 行 |
| `src/uniquant/brain/wyckoff/phase_analysis.py` | `RegimeAwarePhaseClassifier` | 2 | ~100 行 |
| `src/uniquant/brain/wyckoff/__init__.py` | 导出新模块 | 1-3 | ~5 行 |
| `scripts/wyckoff_multitf/wyckoff_daily_screen.py` | WSS 集成、cost 集成、可交易率修复 | 2+4 | ~50 行 |
| `scripts/wyckoff_multitf/ashare_constraints.py` | 涨跌幅按板块动态判定 | 4 | ~20 行 |
| `scripts/wyckoff_multitf/regime_detector.py` | V 型反转标记接口 | 2 | ~30 行 |
| `tests/test_wyckoff_events.py` | `detect_all_events` 测试 | 4 | ~100 行 |
| `tests/test_sequence.py` | WSOScorer/WSS/WyckoffScorer 测试 | 4 | ~50 行 |

---

## 附录：收益预测与风险评估

### 预期边际收益（基于现有实证数据的保守估计）

| 功能 | 预期多空跨距增益 | 置信度 | 依据 |
|------|:--------------:|:------:|------|
| WSO EMA 平滑 | +0.10~0.30% | 中高 | 信号降噪通用技术，类似 WSS 的 +0.17% |
| P&F 点数图 | +0.20~0.50% | 中 | 独立信号维度，参考共振过滤的 +0.43% |
| 贝叶斯概率云 | +0.10~0.40% | 中低 | 理论增益高但实现不确定性大 |
| 体制自适应相位 | +0.30~0.80% | 高 | 直接解决 session report §7 的买入信号体制依赖 |
| WSS 集成（每日管道）| +0.15~0.20% | 高 | 已有 research report §8.3 的实证数据 |
| V 型反转检测器 | 避免 2020 窗口 -39.00 α 衰减 | 高 | 特定窗口修复 |
| CNN 替代 | > +2.0% 才值得替换 | 极低 | 规则系统 t=10.24，CNN 超越的概率 < 20% |
| RL | > +1.0% 才值得替换 | 极低 | 金融 RL 学术文献普遍表明难以超越简单规则 |

### 风险矩阵

| 功能 | 技术风险 | 研究风险 | 过度拟合风险 | 综合评级 |
|------|:-------:|:-------:|:----------:|:-------:|
| Numba 加速 | 🟢 | 🟢 | 🟢 | **无风险** |
| WSO EMA | 🟢 | 🟢 | 🟡 | **低风险** |
| P&F | 🟢 | 🟡 | 🟡 | **低风险** |
| WSS 集成 | 🟢 | 🟢 | 🟢 | **无风险** |
| V 型检测器 | 🟢 | 🟢 | 🟢 | **无风险** |
| 体制自适应相位 | 🟡 | 🟡 | 🟡 | **中风险** |
| 可交易率修复 | 🟢 | 🟢 | 🟢 | **无风险** |
| 贝叶斯概率云 | 🟡 | 🟡 | 🟡 | **中风险** |
| GAF+CNN | 🟡 | 🔴 | 🔴 | **高风险** |
| RL | 🔴 | 🔴 | 🔴 | **极高风险** |

---

> **最终建议**:
> Phase 1（P&F + Numba + EMA）是确定性最高的 3 项，建议优先实施，
> 预计 1-2 周内即可获得可验证的边际增益。
> Phase 2 中的 WSS 集成和 V 型检测器是低挂果实（已知数据但未消费），
> 可在 Phase 1 并行推进。
> Phase 3 ML 路线建议等待 Phase 1+2 的实证结果后重新评估。
