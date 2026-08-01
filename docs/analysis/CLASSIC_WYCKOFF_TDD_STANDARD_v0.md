# Classic Wyckoff Quantization — TDD Implementation Standard (DRAFT v0)

**版本**: v0-草案 | **状态**: 待 3 轮红蓝对抗
**目标**: 定义"经典威科夫量化实现"的可测试标准，统一 TDD 规范，提供可检验的落实形式

---

## 1. 原则声明（Philosophical Foundation）

经典威科夫量化的实现必须满足以下四条不可协商的原则：

**P1 — P&F 优先**: 所有结构分析（TR 界定、Phase 判定、突破确认）必须基于 P&F 图，OHLC 仅作为补充视角。
**P2 — 事件序列驱动**: Phase 由可验证的事件序列推导（PS→BC→AR→SC→ST→Spring→SOS→LPS→BUEC→UTAD），而非价格相对均线的静态位置。
**P3 — 量能验证**: 每个结构性事件必须有对应的成交量签名验证。无成交量确认的事件不构成有效结构信号。
**P4 — 因果关系量化**: Cause（TR 宽度）× 计数公式 → Effect（价格目标）。缺乏 Cause→Effect 链条的分析结果不视为 Wyckoff 分析。

---

## 2. 核心组件架构

```
┌─────────────────────────────────────────────────────┐
│                  WyckoffClassicEngine                │
├─────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ PnF     │  │ Event    │  │ VolumeSignature  │   │
│  │ Builder │→│ Sequence │→│ Validator        │   │
│  └─────────┘  └──────────┘  └──────────────────┘   │
│       │            │               │                 │
│       ▼            ▼               ▼                 │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Count   │  │ Phase    │  │ RelativeStrength │   │
│  │ Target  │  │ Resolver │  │ Calculator       │   │
│  └─────────┘  └──────────┘  └──────────────────┘   │
│                     │               │                │
│                     ▼               ▼                │
│              ┌──────────────────────────┐            │
│              │    MultiTimeframe Judge  │            │
│              └──────────────────────────┘            │
└─────────────────────────────────────────────────────┘
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
| PF-06 | Count Target | TR 宽度 × 计数公式 | 水平 TR 列数 × box_size × 1 (简单) 或 × 1.5/2/3 (强势/中等/弱势) |

### 3.2 事件序列验证（L1 — Event 层）

| ID | 测试 | 标准 |
|----|------|------|
| ES-01 | PS 检测 | 下跌趋势中放量下影线，随后的 O 列缩短 |
| ES-02 | BC 检测 | 放量上冲至 TR 上沿外，随后的 X 列缩短且量能萎缩（AR） |
| ES-03 | SC 检测 | 恐慌放量（前 50 日均量的 ≥2x）+ 随后的 X 列收回（AR） |
| ES-04 | ST 检测 | SC 后的序列缩量测试低点，至少 2 次，每次量能递减 |
| ES-05 | Spring 检测 | O 列短暂跌破 TR 下沿后立即收回（1-2 列内返回 TR 内）+ 量能萎缩 |
| ES-06 | SOS 检测 | 突破 TR 上沿的 X 列 + 成交放量 + 随后的回测缩量持平 |
| ES-07 | LPS 检测 | SOS 后缩量回测 TR 上沿或略高于 TR 上沿 |
| ES-08 | BUEC 检测 | Markup 中的短暂回测 + 量能萎缩 + 快速收复 |
| ES-09 | UTAD 检测 | X 列短暂突破 TR 上沿后立即收回 + 放量 |
| ES-10 | 事件顺序有效性 | 事件必须按 Wyckoff 理论顺序出现，跳跃顺序标记为"非标准" |

### 3.3 成交量签名验证（L1 — Volume 层）

| ID | 测试 | 签名模板 |
|----|------|---------|
| VS-01 | BC 签名 | `high_volume + wide_spread + upper_wick + close_in_upper_third` |
| VS-02 | SC 签名 | `extreme_volume + wide_spread + lower_wick + close_in_lower_third + climax_label` |
| VS-03 | ST 签名 | `decreasing_volume + narrow_spread + low_close` |
| VS-04 | Spring 签名 | `low_volume + narrow_spread + close_above_TR_low` |
| VS-05 | SOS 签名 | `high_volume + wide_spread + close_above_TR_high + no_upper_wick` |
| VS-06 | UTAD 签名 | `high_volume + upper_wick + close_below_TR_high` |

### 3.4 Phase 解决验证（L2 — Phase 层）

| ID | 测试 | Phase 定义 |
|----|------|-----------|
| PH-01 | Phase A (Accumulation) | PS + BC + AR 完成 + 量能萎缩进入 TR 上边界 |
| PH-02 | Phase B (Accumulation) | SC + 连续 ST（≥2 次）+ 量能持续萎缩至地量 |
| PH-03 | Phase C (Accumulation) | Spring + SOS + 缩量 LPS |
| PH-04 | Phase D (Accumulation→Markup) | LPS + BUEC + 高支撑测试 → 突破 TR 上沿 |
| PH-05 | Phase E (Markup) | 持续的更高高点和更低低点 + SOS 序列 |
| PH-06 | Phase A (Distribution) | PSY(努力上冲但无进展) + 放量 + 上影线 |
| PH-07 | Phase B (Distribution) | UTAD + 连续高位测试 + 量能萎缩 |
| PH-08 | Phase C (Distribution) | UTAD + LPSY + 跌破 TR 下沿 |
| PH-09 | Phase D (Distribution→Markdown) | 跌破 TR 下沿 + 量能确认 + 回测失败 |
| PH-10 | Phase E (Markdown) | 持续更低高点和更低低点 + UTAD 序列 |

### 3.5 多周期一致性验证（L3 — MTF 层）

| ID | 测试 | 标准 |
|----|------|------|
| MT-01 | 月线主导 | 日线 phase 必须不违反月线 phase 方向。如月线 = Accumulation，日线不可为 Markdown |
| MT-02 | 周线细节 | 周线 phase 提供中间方向的确认/否认。周线与日线矛盾时以周线为准 |
| MT-03 | 三周期对齐 | 月线+周线+日线一致时 → Full Confidence。两周期一致 → Partial。全部不一致 → No Trade |
| MT-04 | 滞后约束 | 月线 = Accumulation 但日线 = Markup → 仅当周线也显示 Markup 时才确认 Markup |

### 3.6 相对强弱验证（L3 — RS 层）

| ID | 测试 | 分类输出 |
|----|------|---------|
| RS-01 | 强势独立 | 个股 > 大盘 && 个股量缩 > 大盘量缩 → "大资金独立建仓" |
| RS-02 | 跟风型 | 个股 > 大盘 && 个股量放 > 大盘量放 → "跟风上涨，风险高" |
| RS-03 | 弱势独立 | 个股 < 大盘 && 个股量缩 > 大盘量缩 → "有资金撤出" |
| RS-04 | 系统性下跌 | 个股 < 大盘 && 个股量放 ≈ 大盘量放 → "系统性下跌，不交易" |

### 3.7 反事实验证（L4 — 综合层）

| ID | 测试 | 方法 |
|----|------|------|
| CF-01 | Phase 反转确认 | Phase 反转点后 20 个交易日的价格方向必须与 phase 预测一致 |
| CF-02 | Stop Violation | 如果 price 触及事件止损位，原事件标记为"失效" |
| CF-03 | Cause→Effect 验证 | Count Target 必须至少达到 80% 的测量距离才算有效 |
| CF-04 | 假突破惩罚 | P&F 突破后 3 列内跌回 TR 内 → 标记为"假突破"，后续降权 |

---

## 4. 测试数据标准

### 4.1 已知历史模式测试集

| ID | 模式 | 数据来源 | 验证内容 |
|----|------|---------|---------|
| KN-01 | 经典 Accumulation (2018-2020 沪深 300) | 已知底部区域 | 正确识别 Phase A→B→C→D 序列 |
| KN-02 | 经典 Distribution (2015 牛市顶) | 2015-05 至 2015-07 | 正确识别 UTAD + Markdown 开端 |
| KN-03 | Spring→Markup (2020 年 3 月) | COVID 底部反转 | Spring 检测 → SOS → LPS 完整序列 |
| KN-04 | TR 内震荡 | 横盘 6-12 个月的股票 | 不产生 false breakout |
| KN-05 | 跳空缺口测试 | 重大利好/利空后 | 正确处理 P&F 上的跳空 |
| KN-06 | 低流动性 ST 股票 | ST 股日线数据 | 缩量导致的假信号应被标记 |

### 4.2 合成测试数据生成

```python
def generate_wyckoff_phase(phase: WyckoffPhase, length: int) -> pd.DataFrame:
    """Generate synthetic OHLCV data matching classic Wyckoff phase patterns."""
    # Phase A (Accum): downward drift → PS → BC → AR → range
    # Phase B (Accum): SC → ST×3 → volume drying
    # Phase C (Accum): Spring → SOS → LPS
    # Phase E (Markup): higher highs + pullback tests
    # etc.
```

每个 phase 生成函数必须输出可验证的事件序列。

---

## 5. 测试覆盖标准

| 层级 | 组件 | 最低覆盖率 | 测试类型 |
|------|------|-----------|---------|
| L0 | P&F Builder | 100% branch | 单元测试 + 已知历史模式 |
| L1 | Event Detectors (×10) | 95% line | 单元测试 + 合成数据 |
| L1 | Volume Signatures (×6) | 95% line | 单元测试 + 历史数据 |
| L2 | Phase Resolver | 90% branch | 事件序列测试 |
| L2 | Count Target | 100% branch | 单元测试 |
| L3 | Multi-Timeframe Judge | 90% branch | 三周期合成数据 |
| L3 | Relative Strength | 90% line | 个股+指数合成数据 |
| L4 | Counterfactual | 85% line | 历史回测 |

---

## 6. 信号质量标准

经典 Wyckoff 实现输出的信号必须附带以下元数据：

```python
@dataclass
class WyckoffSignalQuality:
    # 结构完整性评分 (0-100)
    # 基于：序列完成度、量能确认度、多周期一致性
    structural_score: int
    
    # 信号来源
    detection_path: str  # "event_sequence" | "volume_pattern" | "phase_transition"
    
    # P&F 证据
    pnf_columns: List[PnFColumn]
    count_target: float
    count_target_met: bool
    
    # 成交量签名
    volume_confirmations: List[str]  # ["BC_signature", "SC_signature", ...]
    
    # 一致性
    monthly_aligned: bool
    weekly_aligned: bool
    daily_aligned: bool
    
    # 相对强弱
    relative_strength: str  # "leader" | "follower" | "laggard" | "unknown"
    
    # 反事实状态
    counterfactual_passed: bool
    last_failure_reason: str = ""
```

---

## 7. 实施检验清单

每个 Phase 实现完成后必须通过以下检查：

```
□ P&F Builder 正确构建 X/O 列，通过 PF-01~06
□ 所有 Phase 事件检测器有已知历史模式测试
□ 成交量签名模板通过合成数据验证
□ Phase 序列检测器在已知 Accumulation/Distribution 序列上 100% 匹配
□ Count Target 计算与已知 Wyckoff 计数结果一致
□ 多周期一致性法官正确处理 4 种冲突类型
□ 相对强度计算器输出与手动标注一致
□ 反事实验证器在已知假突破上正确标记失效
□ 整个管线输出 WyckoffSignalQuality 结构
□ 管线在"不可判定"数据上返回 UNKNOWN + 原因
```

---

## 8. 验证协议

### 8.1 回归测试

每轮代码修改后运行：
```bash
pytest tests/classic_wyckoff/ -q --coverage --tb=short
```

### 8.2 已知模式验证

```bash
pytest tests/classic_wyckoff/test_known_patterns.py -xvs
```
输出必须与 `tests/classic_wyckoff/fixtures/known_patterns.json` 中的手工标注一致。

### 8.3 随机数据鲁棒性

```bash
pytest tests/classic_wyckoff/test_random_data.py
```
在随机 OHLCV 数据上必须返回 UNKNOWN，错误标记 ≤5%。

---

## 9. 反 Red-Blue 对抗文档要求

每次 Phase 实现后，必须生成对抗文档：
- Red 方（质疑者）列举实现与经典 Wyckoff 理论的偏差
- Blue 方（辩护者）为每个偏差提供工程合理性
- 偏差必须分类为：TRADE-OFF / GAP / ERROR
- GAP 和 ERROR 必须有修复路径

---

*本文件为草案 v0，将经过至少 3 轮红蓝对抗后方可定稿。*
