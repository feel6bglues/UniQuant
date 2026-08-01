# Classic Wyckoff Quantization — TDD Implementation Standard (FINAL)

**版本**: v1.0-final | **状态**: 经 3 轮红蓝对抗（19🏆/5💙）定稿
**对抗记录**: `round1.md` (交易员+架构师), `round2.md` (算法+程序员), `round3.md` (四人联合)
**目标**: 定义"经典威科夫量化实现"的可测试标准，统一 TDD 规范，提供可检验的落实形式

---

## 1. 原则声明（Philosophical Foundation）

经典威科夫量化的实现必须满足以下不可协商的原则：

**P1 — P&F 优先**: 所有结构分析（TR 界定、Phase 判定、突破确认）必须基于 P&F 图。
   *例外*: Phase C（Spring 确认）、Phase D（LPS/BUEC）、Phase E（趋势跟踪）允许使用 OHLC 作为补充视角。OHLC 仅在该 3 个阶段作为 P&F 的辅助输入，不可独立产生 Signal。

**P2 — 事件序列驱动**: Phase 由可验证的事件序列推导（PS→BC→AR→SC→ST→Spring→SOS→LPS→BUEC→UTAD），而非价格相对均线的静态位置。

**P3 — 量能验证**: 每个结构性事件必须有对应的成交量签名验证（签名须含可调节的数值阈值）。无成交量确认的事件不构成有效结构信号。

**P4 — 因果关系量化**: Cause（TR 宽度）× 计数公式 → Effect（价格目标）。Count Target 系数须通过 A 股实证校准。缺乏 Cause→Effect 链条的分析结果不视为 Wyckoff 分析。

**P5 — A 股适配**: 涨跌停截断、T+1 交割、板差异化 box_size 基准、集合竞价缺口处理、前复权数据要求，均为默认生效的规则层。

---

## 2. 核心组件架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       WyckoffClassicEngine                        │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐                │
│  │ PnF     │  │ Event    │  │ VolumeSignature  │                │
│  │ Builder │→│ Sequence │→│ Validator        │                │
│  └─────────┘  └──────────┘  └──────────────────┘                │
│       │            │               │                              │
│       ▼            ▼               ▼                              │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐                │
│  │ Count   │  │ Phase    │  │ RelativeStrength │                │
│  │ Target  │  │ Resolver │  │ Calculator       │                │
│  └─────────┘  └──────────┘  └──────────────────┘                │
│       │            │               │                              │
│       ▼            ▼               ▼                              │
│  ┌──────────────────────────────────────────────────────┐        │
│  │               MultiTimeframe Judge                    │        │
│  └──────────────────────────────────────────────────────┘        │
│       │                                                           │
│       ▼                                                           │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  CounterfactualEngine + TAIntegrationGateway (opt)   │        │
│  └──────────────────────────────────────────────────────┘        │
│       │                                                           │
│       ▼                                                           │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐  │
│  │  AShareAdapter   │  │  PositionSizer (phase-based %)       │  │
│  └──────────────────┘  └──────────────────────────────────────┘  │
│       │                                                           │
│       ▼                                                           │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  QualityGate (FPR + Precision + Sharpe)              │        │
│  └──────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 依赖注入配置

```python
@dataclass
class WyckoffClassicConfig:
    # P&F
    box_size_atr_period: int = 14
    box_size_atr_mult: float = 0.5
    reversal_multiplier: int = 3
    max_pnf_columns: int = 300
    min_pnf_columns: int = 5
    data_min_years: float = 1.5
    incremental_update: bool = True

    # Event Detection - numeric thresholds
    spring_exceed_pct: tuple[float, float] = (0.005, 0.015)  # TR下沿跌穿 0.5%-1.5%
    sc_volume_min_ratio: float = 2.0     # 前50日均量的 2x
    st_min_count: int = 2
    st_volume_decline_ratio: float = 0.7 # 每次测试量能递减至前次的 70% 以下

    # Volume Signatures - numeric thresholds
    vol_high_ratio: float = 1.5
    vol_extreme_ratio: float = 2.5
    vol_low_ratio: float = 0.6
    spread_wide_pct: float = 2.0
    spread_narrow_pct: float = 0.8
    wick_body_ratio: float = 0.3
    close_zone_ratio: float = 0.33  # upper/lower third

    # Phase Resolution
    phase_required_passing: float = 1.0   # required条件必须全部通过
    phase_weighted_threshold: float = 0.6 # optional加权分及格线

    # MTF
    mtf_require_quantitative_evidence: bool = True

    # Counterfactual
    cf_accumulation_days: int = 40
    cf_distribution_days: int = 30
    cf_spring_days: int = 20
    cf_markup_days: int = 60
    cf_count_target_pct: float = 0.80

    # A-Share Adaptation
    board: str = "sse_main"  # sse_main | szse_main | star | gem
    t_plus1_cooldown: bool = True
    limit_up_down_adjust: bool = True
    pre_adjusted_data: bool = True

    # Position Sizing
    pos_phase_a_accum: tuple[float, float] = (0.0, 0.0)    # 不建仓
    pos_phase_b_accum: tuple[float, float] = (0.05, 0.10)  # 底仓 5-10%
    pos_phase_c_accum: tuple[float, float] = (0.10, 0.25)  # 加仓 10-25%
    pos_phase_d_accum: tuple[float, float] = (0.25, 0.50)  # 重仓 25-50%
    pos_phase_e_markup: tuple[float, float] = (0.50, 0.75) # 满仓 50-75%
    pos_phase_distr: tuple[float, float] = (0.0, 0.0)      # 不交易

    # TA Integration (optional)
    ta_integration_enabled: bool = False
```

---

## 3. TDD 验证标准

### 3.1 P&F 构建验证（L0 — Build 层）

| ID | 测试 | 标准 | 通过条件 |
|----|------|------|---------|
| PF-01 | 标准 X/O 交替 | 给定 OHLC 序列，P&F 正确交替 X 列/O 列 | 连续同向 >= box_size 算 1 列；反向 >= reversal × box_size 切换列 |
| PF-02 | box_size 自适应 | 不同价格区间使用不同 box_size（ATR %） | 高价位自动放大 box_size，保持列数可比 |
| PF-03 | 支撑/阻力线检测 | P&F 图上识别水平密集区 | 连续 ≥3 次触碰同一价格水平的列，标记为 S/R |
| PF-04 | 突破识别 | X 列突破 TR 上沿 | 突破列 + 后续 1 列不跌回 TR 内 → "confirmed breakout" |
| PF-05 | TR 界定 | P&F 图上水平密集区上下边界 | TR 上沿 = 密集区最高 X 列顶，下沿 = 密集区最低 O 列底 |
| PF-06 | Count Target | TR 宽度 × 计数公式 | 水平 TR 列数 × box_size × 系数。系数须通过 A 股实证校准，校准报告附于测试套件 |
| PF-07 | 数据窗口边界 | 定义 Builder 的最小数据量和最大列数 | min_data_years >= 1.5, max_columns <= config.max_pnf_columns |
| PF-08 | 增量更新 | 新 K 线到来时增量更新 P&F | 增量更新 O(1)，全量重建 <= 50ms per ticker |

### 3.2 事件序列验证（L1 — Event 层）

| ID | 测试 | 标准 | 数值阈值 |
|----|------|------|---------|
| ES-01 | PS 检测 | 下跌趋势中放量下影线 + 随后的 O 列缩短 | 下影线 >= 实体 2x |
| ES-02 | BC 检测 | 放量上冲至 TR 上沿外 + 随后的 X 列缩短且量能萎缩 | volume >= vol_high_ratio × ma50, 振幅 >= spread_wide_pct |
| ES-03 | SC 检测 | 恐慌放量 + 随后的 X 列收回 | volume >= vol_extreme_ratio × ma50 |
| ES-04 | ST 检测 | SC 后的序列缩量测试低点，>= 2 次，每次量能递减 | st_min_count=2, vol_decline <= vol_decline_ratio |
| ES-05 | Spring 检测 | O 列短暂跌破 TR 下沿后立即收回(1-2列) + 量能萎缩 | exceed=0.5%-1.5% TR下沿, vol <= vol_low_ratio × ma50 |
| ES-06 | SOS 检测 | 突破 TR 上沿 + 放量 + 随后的回测缩量持平 | volume >= vol_high_ratio, 回测缩量 <= ma50 |
| ES-07 | LPS 检测 | SOS 后缩量回测 TR 上沿或略高于 | volume <= vol_low_ratio × ma50 |
| ES-08 | BUEC 检测 | Markup 中短暂回测 + 缩量 + 快速收复 | 回测幅度 < 前冲幅度的 1/3 |
| ES-09 | UTAD 检测 | X 列短暂突破 TR 上沿后立即收回 + 放量 | volume >= vol_high_ratio |
| ES-10 | 事件顺序有效性 | **概率匹配**：使用序列对齐算法（DP 编辑距离）比较观测序列与理论序列 | 匹配度 >= 0.7="标准", 0.4-0.7="非标准", <0.4="无效". 同一根 K 线触发多个事件时按优先级排序 |

#### 3.2.1 事件序列概率匹配算法

```python
def sequence_match_score(
    observed: list[WyckoffEvent],
    theoretical: list[WyckoffEvent]
) -> float:
    """
    使用 Needleman-Wunsch（NW）风格的对齐算法计算观测序列与理论序列的匹配度。
    - 插入/删除罚分: -1
    - 匹配得分: +2
    - 非匹配替换: -1
    归一化：得分 / max(len(observed), len(theoretical))
    """
    # DP 矩阵实现
    # 返回 0.0 - 1.0 的匹配度
```

### 3.3 成交量签名验证（L1 — Volume 层）

每个签名必须附带可调节的数值阈值参数：

| ID | 测试 | 签名模板 | 数值条件（默认值） |
|----|------|---------|------------------|
| VS-01 | BC 签名 | `high_volume + wide_spread + upper_wick + close_in_upper_third` | vol >= 1.5×ma50, spread >= 2.0%, upper_wick/实体 >= 0.3, close >= (H-L)×0.67 |
| VS-02 | SC 签名 | `extreme_volume + wide_spread + lower_wick + close_in_lower_third` | vol >= 2.5×ma50, spread >= 3.0%, lower_wick/实体 >= 0.5, close <= (H-L)×0.33 |
| VS-03 | ST 签名 | `decreasing_volume + narrow_spread + low_close` | vol <= 0.6×ma50, spread <= 0.8%, close in lower half |
| VS-04 | Spring 签名 | `low_volume + narrow_spread + close_above_TR_low` | vol <= 0.6×ma50, spread <= 0.8%, close > TR_lower |
| VS-05 | SOS 签名 | `high_volume + wide_spread + close_above_TR_high + no_upper_wick` | vol >= 1.5×ma50, spread >= 2.0%, close > TR_upper, upper_wick/实体 <= 0.1 |
| VS-06 | UTAD 签名 | `high_volume + upper_wick + close_below_TR_high` | vol >= 1.5×ma50, upper_wick/实体 >= 0.5, close < TR_upper |

签名匹配度 = 满足条件的签名分量数 / 总分变量。所有分量的阈值均可通过 `WyckoffClassicConfig` 调节。

### 3.4 Phase 解决验证（L2 — Phase 层）

每个 Phase 定义拆分为 Required（必须通过）和 Optional（加权）条件：

| ID | Phase | Required (must pass) | Optional (weighted) | 通过条件 |
|----|-------|---------------------|--------------------|---------|
| PH-01 | Phase A Accum | PS + BC + AR 完成 | 量能萎缩 (0.4), 进入 TR 上边界 (0.3), 下边界放量减缓 (0.3) | req=3/3, weighted>=0.6 |
| PH-02 | Phase B Accum | SC + >=2 次 ST | 量能持续萎缩至地量 (0.4), TR 下沿震荡 (0.3), 下边界成交递减 (0.3) | req=2/2, weighted>=0.6 |
| PH-03 | Phase C Accum | Spring + SOS | 缩量 LPS (0.5), 量能萎缩确认 (0.3), TR 收窄 (0.2) | req=2/2, weighted>=0.6 |
| PH-04 | Phase D Accum→Markup | LPS + BUEC + 突破 TR 上沿 | 突破放量 (0.5), 回测缩量 (0.3), 周线确认 (0.2) | req=3/3, weighted>=0.6 |
| PH-05 | Phase E Markup | 更高高点/低点 + SOS 序列 | 趋势加速 (0.4), BREAKOUT 连续列 (0.3), RS>1 (0.3) | req=2/2, weighted>=0.6 |
| PH-06 | Phase A Distrib | PSY 放量上冲无进展 + 上影线 | 量能萎缩 (0.3), TR 上沿测试 (0.4), 内部 K 线缩小 (0.3) | req=2/2, weighted>=0.6 |
| PH-07 | Phase B Distrib | UTAD + >=1 次高位测试 | 量能萎缩 (0.5), 振幅收窄 (0.3), 下边界无明显支撑 (0.2) | req=2/2, weighted>=0.6 |
| PH-08 | Phase C Distrib | UTAD + 跌破 TR 下沿 | 量能确认 (0.5), 回测失败 (0.3), LPSY (0.2) | req=2/2, weighted>=0.6 |
| PH-09 | Phase D Distrib→Markdown | 跌破 TR + 量能确认 + 回测失败 | 振幅扩大 (0.4), 连续 O 列 (0.3), RS<1 (0.3) | req=3/3, weighted>=0.6 |
| PH-10 | Phase E Markdown | 更低高点/低点 + UTAD 序列 | 连续 O 列延伸 (0.5), 无缩量止跌 (0.3), RS<1 (0.2) | req=2/2, weighted>=0.6 |

**置信度判定**:
- required=全通过 AND weighted>=0.9 → **confirmed**
- req=全通过 AND weighted>=0.6 → **probable**
- req=全通过 AND weighted<0.6 → **weak**
- req=未全通过 → **not_detected**

### 3.5 多周期一致性验证（L3 — MTF 层）

| ID | 测试 | 标准 |
|----|------|------|
| MT-01 | 月线主导 | 日线 phase 必须不违反月线 phase 方向。如月线 = Accumulation，日线不可为 Markdown |
| MT-02 | 周线细节 | 周线 phase 提供中间方向的确认/否认。周线与日线矛盾时以周线为准 |
| MT-03 | 三周期对齐 | 月线+周线+日线一致时 → Full Confidence。两周期一致 → Partial。全部不一致 → No Trade |
| MT-04 | 滞后约束 | 月线 = Accumulation 但日线 = Markup → 仅当周线也显示 Markup 时才确认 Markup |
| MT-05 | **量化证据** | MTF 法官的输出必须附带量化证据：多周期对齐 vs 单一周期的信号预测力提升指标。首次实现时报告 R²、信息系数(IC)、夏普比提升比率，作为基线记录 |

### 3.6 相对强弱验证（L3 — RS 层）

| ID | 测试 | 分类输出 | 数值条件 |
|----|------|---------|---------|
| RS-01 | 强势独立 | "大资金独立建仓" | 个股 > 大盘 AND 个股量缩 > 大盘量缩 (vol_ratio < 0.8) |
| RS-02 | 跟风型 | "跟风上涨，风险高" | 个股 > 大盘 AND 个股量放 > 大盘量放 (vol_ratio > 1.2) |
| RS-03 | 弱势独立 | "有资金撤出" | 个股 < 大盘 AND 个股量缩 > 大盘量缩 |
| RS-04 | 系统性下跌 | "系统性下跌，不交易" | 个股 < 大盘 AND 个股量放 ≈ 大盘量放 (0.8 <= ratio <= 1.2) |

**资金流向补充**:
| ID | 测试 | 标准 |
|----|------|------|
| RS-05 | 主力净流入 | 个股主力净流入/流出方向与 RS 分类一致时信号加强，冲突时降权 |
| RS-06 | 大单占比 | 大单成交占比 > 30% 确认资金主动行为；< 15% 怀疑跟风 |

### 3.7 反事实验证（L4 — 综合层）

| ID | 测试 | 方法 | 验证周期 |
|----|------|------|---------|
| CF-01 | Phase 反转确认 | Phase 反转点后 N 天价格方向与预测一致 | Accum=40d, Distrib=30d, Spring=20d, Markup=60d |
| CF-02 | Stop Violation | Price 触及事件止损位则标记"失效" | 触发时即刻 |
| CF-03 | Cause→Effect | Count Target >= config.cf_count_target_pct | phase 反转后至目标位 |
| CF-04 | 假突破惩罚 | P&F 突破后 3 列内跌回 TR 内 | 突破后 3 列内 → 标记假突破，后续降权 0.5 |

---

## 4. A 股微观结构适配层

### 4.1 分板 box_size 基准

| 板块 | 代码前缀 | box_size 基准 | 涨跌停 | 备注 |
|------|---------|-------------|--------|------|
| 上海主板 | 60xxxx | ATR(14)×0.5% | ±10% | 默认基准 |
| 深圳主板 | 00xxxx | ATR(14)×0.5% | ±10% | 同上海 |
| 科创板 | 688xxx | ATR(14)×0.3% | ±20% | 振幅大，box_size 需缩小 |
| 创业板 | 30xxxx | ATR(14)×0.3% | ±20% | 同上 |
| 北交所 | 8xxxxx | ATR(14)×0.4% | ±30% | 高波动另设 |

### 4.2 T+1 冷却观察

Spring 信号触发后需等待 1 个交易日确认：
- Day 0: Spring 检测触发
- Day 1: 冷却日（T+1 锁定，不能卖出/买入已有仓位）
- Day 2: 确认 Spring 有效或失效

### 4.3 涨跌停截断

- 涨停日：P&F 列在涨停价处截断，不计算上影线
- 跌停日：P&F 列在跌停价处截断，不计算下影线
- 连续涨跌停：P&F 按"最大可能列"计算（一个涨停 = 单列最大 spread）

### 4.4 集合竞价缺口

- 开盘缺口 > box_size × 2 时，在 P&F 上标记为"GAP"
- 跳空列不参与 S/R 线检测（非连续交易形成）
- 跳空后第 1 根完整 K 线前，事件检测器暂停

### 4.5 数据要求

- 所有输入 OHLCV 必须为**前复权**数据
- 分红/送股导致的复权跳跃不能作为 P&F 上的有效突破
- 复权跳跃 > box_size × 3 时必须标记数据异常

---

## 5. 测试数据标准

### 5.1 已知历史模式测试集

| ID | 模式 | 数据来源 | 验证内容 |
|----|------|---------|---------|
| KN-01a | 底部 TR (2015.08-2016.12) | 熔断后底部→2017 牛市 | Accumulation Phase A→B→C→D 完整序列 |
| KN-01b | 快速 V 反 (2018.12-2019.03) | 贸易战底部→快速反弹 | A 股特有的 PS→SOS（无 SC/ST/Spring） |
| KN-01c | 疫情放开底 (2022.10-2023.03) | 疫情放开→反弹 | 同上，验证 V 反模式的鲁棒性 |
| KN-02 | 经典 Distribution (2015 牛市顶) | 2015-05 至 2015-07 | UTAD + Markdown 开端 |
| KN-03 | Spring→Markup (2020 年 3 月) | COVID 底部反转 | Spring → SOS → LPS 完整序列 |
| KN-04 | TR 内震荡 | 横盘 6-12 个月 | 不产生 false breakout |
| KN-05 | 跳空缺口测试 | 重大利好/利空后 | 正确处理 P&F 上的跳空 |
| KN-06 | 低流动性 ST 股票 | ST 股日线 | 缩量导致的假信号应被标记 |

### 5.2 标注格式规范

```json
{
  "pattern_id": "KN-01a",
  "name": "bottom_tr_2015_2016",
  "data_file": "fixtures/hs300_2015_2016.parquet",
  "symbol": "000300.SH",
  "board": "sse_main",
  "expected_events": [
    {"index": 45, "event": "PS", "confidence": "high"},
    {"index": 112, "event": "BC", "confidence": "high"},
    {"index": 145, "event": "AR", "confidence": "high"},
    {"index": 220, "event": "SC", "confidence": "high"}
  ],
  "expected_phase_transitions": [
    {"index": 200, "from": "unknown", "to": "phase_a_accum"},
    {"index": 280, "from": "phase_a", "to": "phase_b_accum"},
    {"index": 420, "from": "phase_b", "to": "phase_c_accum"}
  ],
  "expected_trades": [
    {"index": 450, "action": "enter", "phase": "phase_c", "confidence": "probable"},
    {"index": 520, "action": "add", "phase": "phase_d", "confidence": "confirmed"}
  ],
  "manual_annotator": "trader_wyckoff_2026",
  "annotation_date": "2026-07-24"
}
```

### 5.3 合成测试数据

```python
def generate_wyckoff_phase(phase: WyckoffPhase, length: int) -> pd.DataFrame:
    """Generate synthetic OHLCV data matching classic Wyckoff phase patterns."""
```

每个 phase 生成函数必须输出可验证的事件序列。合成数据包括三个子集：

### 5.4 对抗性测试数据

```
Adversarial Test Set:
  ─ Phase 完整模式:      10 accum + 10 distrib + 10 markup + 10 markdown    (40 seqs)
  ─ 随机 OHLCV (GBM):    100 序列，预期 UNKNOWN 率 >= 95%                     (100 seqs)
  ─ 接近但不完全序列:     50 序列（每个 Phase 有 20% 条件缺失）                  (50 seqs)
  ─ 已知假模式:          20 序列（价格特征像 Spring 但量能不符合）               (20 seqs)
  ─ 涨跌停截断测试:      10 序列（含连续涨跌停板）                              (10 seqs)
```

---

## 6. 测试覆盖标准

### 6.1 模式覆盖（取代传统 line/branch 覆盖作为主指标）

| 层级 | 组件 | 模式覆盖率 | 行覆盖（辅助） | 测试类型 |
|------|------|-----------|-------------|---------|
| L0 | P&F Builder | 100% 测试用例覆盖 PF-01~08 | >= 90% | 单元 + 已知模式 |
| L1 | Event Detectors (×10) | 每个事件 >= 3 个测试序列 | >= 90% | 单元 + 合成 + 对抗 |
| L1 | Volume Signatures (×6) | 每个签名 >= 2 个正例 + 1 个反例 | >= 90% | 单元 + 历史 |
| L2 | Phase Resolver | 所有 10 个 phase 至少 1 次 | >= 85% | 事件序列测试 |
| L2 | Count Target | 已知模式 100% 匹配 | 100% | 单元 |
| L3 | Multi-Timeframe | 4 种冲突类型各 >= 1 次 | >= 85% | 三周期合成 |
| L3 | Relative Strength | 4 类 + 资金流向 2 类各 >= 1 次 | >= 85% | 个股+指数合成 |
| L4 | Counterfactual | 4 种反事实各 >= 1 次 | >= 80% | 历史回测 + 对抗 |
| — | A-Share Adapter | 5 个板块各 >= 1 次 | >= 80% | 合成 + 历史 |
| — | TA Gateway (opt) | 3 种 TA 信号各 >= 1 次 | >= 80% | 合成 |

### 6.2 行覆盖补充

行覆盖作为辅助指标，最低要求如上表右列。未达标的行必须在测试报告中注明原因（如"不可达分支：涨跌停截断测试需真实连续涨停数据"）。

---

## 7. 信号质量标准

经典 Wyckoff 实现输出的信号必须附带以下元数据：

```python
@dataclass
class WyckoffSignalQuality:
    # 结构完整性评分 (0-100)
    structural_score: int

    # 信号来源
    detection_path: str  # "event_sequence" | "volume_pattern" | "phase_transition"

    # P&F 证据
    pnf_columns: list[PnFColumn]
    count_target: float
    count_target_met: bool

    # 成交量签名
    volume_confirmations: list[str]

    # 一致性
    monthly_aligned: bool
    weekly_aligned: bool
    daily_aligned: bool

    # 相对强弱 + 资金流向
    relative_strength: str  # "leader" | "follower" | "laggard" | "unknown"
    capital_flow_aligned: bool  # 主力资金方向与信号方向一致

    # Phase 置信度
    phase_confidence: str  # "confirmed" | "probable" | "weak" | "not_detected"
    phase_conditions: dict[str, bool]  # 各条件通过情况

    # 反事实状态
    counterfactual_passed: bool
    last_failure_reason: str = ""

    # A 股适配状态
    board: str
    limit_hit: bool  # 当前是否涨跌停
    t1_cooldown: bool  # 是否在 T+1 冷却期
```

---

## 8. 信号质量门（Quality Gate）

| 指标 | 目标 | 测量方法 |
|------|------|---------|
| Spring Precision | >= 0.30 | 触发的 Spring 中在 CF 验证周期后有效的比例 |
| Spring Recall | >= 0.60 | 覆盖人工标注 Spring 的比例 |
| Breakout Accuracy | >= 0.70 | P&F 突破中后续确认的比例 |
| False Positive Rate | <= 0.10 | 在随机 GBM 数据上误标率 |
| Signal Sharpe | > 0.50 | 信号组合的年化夏普比 |
| Position Sizing Error | <= 0.05 | 实际仓位 vs 目标仓位的 MAE |

每项指标在 CI 中自动测量，不达标时告警但不阻断（降低信号置信度）。

---

## 9. 性能预算

| 组件 | 预算 (per ticker) | 备注 |
|------|------------------|------|
| P&F Builder (增量) | <= 10ms | 增量更新 O(1) |
| P&F Builder (全量) | <= 50ms | 全量重建，仅首次 |
| Event Detection (×10) | <= 5ms | 向量化实现 |
| Volume Signature (×6) | <= 3ms | 向量化实现 |
| Phase Resolution | <= 2ms | 判定表实现 |
| Multi-Timeframe | <= 2ms | 仅需比较 3 个 phase 方向 |
| Relative Strength | <= 2ms | 个股 vs 指数 |
| Counterfactual | <= 5ms | 历史验证 |
| A-Share Adapter | <= 1ms | 配置查表 |
| TA Integration (opt) | <= 5ms | 可选，默认关闭 |
| **Total per ticker** | **<= 35ms** | 增量路径 |
| 5000 tickers | <= 175s (3min) | 单线程；可并行至 8 workers = 22s |

**瓶颈警告**: P&F Builder > 50ms 全量 → 需增量更新架构。
Event Detection > 10ms → 需 Numba JIT。

---

## 10. 仓位管理（Position Sizing）

Phase 映射至仓位比例，基于 Wyckoff 理论中的阶段风险程度：

| Phase | 仓位范围 | 理论依据 | 止损逻辑 |
|-------|---------|---------|---------|
| A (Accum onset) | 0% | 未确认，仅监测 | — |
| B (Accum mid) | 5-10% | SC 确认后底仓 | SC 低点 -1 ATR |
| C (Accum late) | 10-25% | Spring 确认后加仓 | Spring 低点 -1 ATR |
| D (Accum→Markup) | 25-50% | 突破后重仓 | TR 下沿 -0.5 ATR |
| E (Markup) | 50-75% | 趋势延续满仓 | 前一个更低低点 |
| Distribution A-E | 0% | 顶部区域不交易 | — |

仓位管理必须附带止损位（如上所示），并通过 CF-02（Stop Violation）验证。

---

## 11. TA 信号集成网关（可选, L4）

启用 `ta_integration_enabled=True` 后，Wyckoff 信号可与传统 TA 信号协同：

| Wyckoff 信号 | TA 条件 | 权重修正 |
|-------------|---------|---------|
| Spring | RSI(14) < 30（底背离） | strong_buy +0.5 |
| SOS | MACD 金叉 | confirmed_breakout +0.3 |
| BC | Volume EMA12 > EMA26 金叉 | distribution_warning -0.3 |
| 任意 Wyckoff | TA 方向相反 | conflicting -0.3 |

TA 集成器输出最终信号时将 Wyckoff 基础得分 × 权重修正。默认关闭。

---

## 12. 实施检验清单

每个 Phase 实现完成后必须通过以下检查：

```
□ P&F Builder 正确构建 X/O 列，通过 PF-01~08
□ P&F Builder 增量更新通过性能预算 (<=10ms)
□ 所有 Phase 事件检测器有已知历史模式测试
□ 成交量签名模板通过合成数据验证 + 数值阈值可调
□ Phase 序列检测器在 KN-01a~c 上累计 >= 70% 匹配
□ Count Target 计算与 A 股实证校准报告一致
□ 多周期一致性法官正确处理 4 种冲突类型 + 附带量化证据
□ 相对强度计算器 + 资金流向与手动标注一致
□ 反事实验证器在已知假突破上正确标记失效
□ 整个管线输出 WyckoffSignalQuality 结构
□ 管线在"不可判定"数据上返回 UNKNOWN + 原因
□ 对抗性测试套件通过（FPR <= 0.10，随机数据 UNKNOWN >= 95%）
□ A 股适配层覆盖 5 个板块 + T+1 冷却 + 涨跌停截断
□ 仓位管理包含止损验证
□ 性能预算在 CI 中测量（单 ticker <= 35ms）
```

---

## 13. 验证协议

### 13.1 回归测试

```bash
pytest tests/classic_wyckoff/ -q --coverage --tb=short
```

### 13.2 已知模式验证

```bash
pytest tests/classic_wyckoff/test_known_patterns.py -xvs
```
输出必须与 `tests/classic_wyckoff/fixtures/known_patterns.json` 手工标注一致。

### 13.3 对抗性测试

```bash
pytest tests/classic_wyckoff/test_adversarial.py -xvs
```
覆盖随机 GBM、接近但不完全的序列、已知假模式。FPR 阈值违反时告警。

### 13.4 性能测试

```bash
pytest tests/classic_wyckoff/test_performance.py --benchmark
```
性能预算违反时告警。5000 tickers 的压力测试默认关闭（`--runslow`）。

---

## 14. 反红蓝对抗文档要求

每次 Phase 实现后，必须生成对抗文档：
- Red 方（质疑者）列举实现与经典 Wyckoff 理论的偏差
- Blue 方（辩护者）为每个偏差提供工程合理性
- 偏差必须分类为：TRADE-OFF / GAP / ERROR
- GAP 和 ERROR 必须有修复路径

---

## 15. 设计决策记录（ADR）

重大架构决策必须在 `docs/decisions/` 下记录，包含：
- 背景和动机
- 考虑过的替代方案
- 选定方案的理由
- 后果和影响

---

*本文件 v1.0-final 经 3 轮红蓝对抗（19 项 Red 修正 / 5 项 Blue 保留）定稿。*
*对抗记录: `round1.md`（交易员+架构师, 6R/1B）, `round2.md`（算法+程序员, 7R/1B）, `round3.md`（四人联合, 6R/1B）*
