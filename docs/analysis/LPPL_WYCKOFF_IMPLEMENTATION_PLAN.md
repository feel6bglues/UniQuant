# LPPL 指数泡沫分析 + Wyckoff 全量分析 — 实施计划

> **日期**: 2026-07-24  
> **范围**: (1) LPPL 从个股迁移到指数级别 (2) Wyckoff 完整实现对全量股票+基金  
> **依据**: 3 轮红蓝对抗 (15 项声明) + Walk-forward 实证 (2999 观测) + Monte Carlo 验证

---

## 一、LPPL 指数泡沫分析

### 1.1 覆盖指数范围

使用现有数据基础设施，已支持：

| 类别 | 代码 | 数据源 |
|---|---|---|
| 上证指数 | 000001.SH | TDX 指数 / data/lake/index |
| 上证50 | 000016.SH | 同上 |
| 沪深300 | 000300.SH | 同上 |
| 中证500 | 000905.SH | 同上 |
| 中证1000 | 000852.SH | 同上 |
| 中证2000 | 932000.SH | 同上 |
| 深证成指 | 399001.SZ | 同上 |
| 创业板指 | 399006.SZ | 同上 |
| 11 个沪深300 行业指数 | 000908.SH-000917.SH | `market_coordinator.fetch_sector_daily()` |
| 额外 TDX 行业指数 | 880xxx (880001-880500+) | TDX 板块文件，通过 `fetch_index_daily()` 读取 |

**关键：880xxx 系列**是通达信行业板块指数（约 300-500 个），覆盖 A 股所有申万行业。现有基础设施 `INDEX_PREFIXES=["000","399","880"]` 已识别，`fetch_index_daily()` 已支持。

### 1.2 架构设计

```
┌────────────────────────────────────────────────────────────────────┐
│ brain/lppl_index/                    (新模块，与 brain/lppl/ 独立)  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  optimizer.py     sampler.py       mc_table.py                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐                 │
│  │ VP(L-BFGS │    │ LHS 100pt│    │ GBM null dist│                 │
│  │ + OLS)    │    │ tc∈[0,T+100]  │ p-value lookup                 │
│  └──────────┘    └──────────┘    └──────────────┘                 │
│                                                                    │
│  scanner.py        reporter.py    __init__.py                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐                 │
│  │ 3 windows│    │ prob/    │    │ public API   │                 │
│  │ 500/750/ │    │ mc_p/    │    │               │                 │
│  │ 1000 ens │    │ params   │    │               │                 │
│  └──────────┘    └──────────┘    └──────────────┘                 │
│                                                                    │
│  数据输入: OHLCV (闭高低开成交额) 输出: LPPLIndexReport            │
└────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────────┐
│ services/analysis/macro_service.py  (修改, 增加 LPPLIndex 调用)    │
│  - 初始化时对所有注册指数跑 LPPL index 分析                        │
│  - 结果缓存到 MarketLevelCache                                     │
│  - 供仪表盘和仓位管理决策参考                                      │
└────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────────┐
│ 产出: 每日指数泡沫热力图                                           │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┐              │
│ │ 沪深300  │ 中证500 │ 中证1000│ 上证    │ 创业板  │              │
│ │ p=0.02  │ p=0.31  │ p=0.45  │ p=0.08 │ p=0.12  │              │
│ │ 🟢      │ 🟡      │ 🟡      │ 🟢      │ 🟢      │              │
│ └─────────┴─────────┴─────────┴─────────┴─────────┘              │
│ 行业板块热力图 (880xxx 系列)                                       │
│ ┌─────────┬─────────┬─────────┬─────────┐                        │
│ │ 银行    │ 新能源  │ 半导体  │ 医药    │                        │
│ │ p=0.15  │ p=0.67  │ p=0.73  │ p=0.09  │                        │
│ │ 🟡      │ 🟠      │ 🔴      │ 🟢      │                        │
│ └─────────┴─────────┴─────────┴─────────┘                        │
└────────────────────────────────────────────────────────────────────┘
```

### 1.3 新代码清单（详细）

| # | 文件 | 内容 | 行数 | 前置依赖 |
|---|---|---|---|---|
| 1 | `brain/lppl_index/__init__.py` | 公开 API: `run_index_analysis(df) → LPPLIndexReport` | ~30 | 无 |
| 2 | `brain/lppl_index/optimizer.py` | VP 优化器: 3 参 L-BFGS-B + 4 参 OLS + b<0/\|c\|>0.01 约束 | ~220 | `scipy.optimize`, `scipy.linalg` |
| 3 | `brain/lppl_index/sampler.py` | 拉丁超立方 100 初始点, tc ∈ [0, T+100] | ~100 | `scipy.stats.qmc` |
| 4 | `brain/lppl_index/mc_table.py` | 预计算 GBM null 分布 (vol×window 桶), 运行时查表 | ~300 | `numpy` |
| 5 | `brain/lppl_index/scanner.py` | 三窗口 (500/750/1000d) ensemble | ~180 | 调用 2,3,4 |
| 6 | `brain/lppl_index/reporter.py` | 结果格式化: p 值 + 参数 + 置信度 | ~150 | 无 |
| 7 | `brain/lppl_index/test_optimizer.py` | 合成数据测试: b<0 约束正确性 × 3 | ~100 | pytest |
| 8 | `brain/lppl_index/test_mc.py` | MC p-value 正确性验证 × 2 | ~80 | pytest |

### 1.4 现有代码修改

| # | 文件 | 改什么 | 行数变化 |
|---|---|---|---|
| A | `shared/interfaces.py` | 新增 `LPPLIndexOutput(bubble_probability, mc_p_value, m, omega, r_squared, index_code, index_name)` dataclass | +30 |
| B | `shared/constants/market.py` | `MAJOR_INDEXES` 扩展 (添加 880 行业板块), 新增 `SECTOR_INDEXES` dict | +20 |
| C | `services/analysis/macro_service.py` | `run_lppl_index_analysis()`: 遍历指数列表 → 读数据 → 调用 LPPLIndex → 缓存结果 | +120 |
| D | `services/market_cache.py` | 新增 `lppl_index_cache: Dict[str, LPPLIndexOutput]` | +20 |
| E | `config/config.yaml` | LPPL Index 配置: 窗口长度, p 值阈值, 指数列表 | +15 |

### 1.5 关键实现细节

**VP 优化器核心**:
```python
# optimizer.py — 变量投影的核心 ~40 行
def _build_design_matrix(t, tc, m, w):
    tau = tc - t
    tau = np.maximum(tau, 1e-10)  # 防止除零
    tau_m = tau ** m
    cos_term = tau_m * np.cos(w * np.log(tau))
    sin_term = tau_m * np.sin(w * np.log(tau))
    return np.column_stack([np.ones_like(t), tau_m, cos_term, sin_term])

def _solve_linear(A, y):
    """OLS 解析解"""
    coeffs, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    return coeffs  # (a, b, c1, c2)

def objective(nonlinear_params, t, y):
    tc, m, w = nonlinear_params
    A = _build_design_matrix(t, tc, m, w)
    a, b, c1, c2 = _solve_linear(A, y)
    penalty = 0.0
    if b >= 0:          # b<0 强制
        penalty += 1e6 * (b + 1.0)**2
    c_amp = np.sqrt(c1**2 + c2**2)
    if c_amp < 0.01:    # |c|>0.01 强制
        penalty += 1e6 * (0.01 - c_amp)**2
    residuals = A @ [a, b, c1, c2] - y
    return np.mean(residuals**2) + penalty
```

**tc 采样**:
```python
# sampler.py
def sample_initial_points(t_end, n=100, seed=42):
    """拉丁超立方采样 100 个 (tc, m, w) 初始点"""
    sampler = qmc.LatinHypercube(d=3, seed=seed)
    samples = sampler.random(n=n)
    # tc ∈ [t_end*0.5, t_end+100]
    # m ∈ [0.1, 0.9]
    # w ∈ [6, 13]
    l_bounds = [t_end * 0.5, 0.1, 6.0]
    u_bounds = [t_end + 100, 0.9, 13.0]
    return qmc.scale(samples, l_bounds, u_bounds)
```

### 1.6 执行顺序

```
Phase 1 (Day 1-3):  optimizer.py + sampler.py → 合成数据上验证 RMSE 收敛
Phase 2 (Day 4-6):  mc_table.py + scanner.py → 对沪深300跑完整管线
Phase 3 (Day 7-8):  reporter.py + macro_service.py 集成 → 输出热力图
Phase 4 (Day 9-10): 扩展 880 行业板块 + 测试 + 文档
```

### 1.7 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 约束 b<0 + c>0.01 导致收敛率 < 30% | 高 | 大多数指数窗口无输出 | 降低约束强度；对无法收敛的窗口输出 "INSUFFICIENT" |
| MC p-value 查表表精度不够 | 中 | p 值不准确 | 用 50 个 volatility bucket + 插值 |
| 880 行业指数历史数据不足 1000 天 | 高 | 新板块无法跑 LPPL | 兜底：用最短可用窗口；不足 500 天则跳过 |

---

## 二、Wyckoff 全量分析（股票 + 基金）

### 2.1 覆盖范围

| 资产 | 代码范围 | 数据特征 | 特殊处理 |
|---|---|---|---|
| A 股全量 (~5000) | 6xxxxx/0xxxxx/3xxxxx | OHLCV 完整 | 正常 |
| 科创板 | 688xxx/689xxx | 涨跌幅 20% | `_is_st` 参数 |
| 北交所 | 8xxxxx | 涨跌幅 30% | 单独规则 |
| ETF 基金 | 510xxx/159xxx/518xxx/56xxxx | 成交量小，净值波动小 | 跳过 Spring（TR 罕见）；Markup/Markdown 可用 |
| LOF 基金 | 16xxxx | 同上 | 同上 |
| 封闭式基金 | 50xxxx | 同上 | 同上 |

**ETF/基金特殊处理**: 基金通常无明显的 TR 积累/派发结构（机构申购赎回替代了场内供求）。Phase A-E 的有效性在基金上未知 — Wyckoff 方法本身是为股票发明的。实现时：基金跳过 Spring/UTAD，只跑 Markup/Markdown 相位检测。

### 2.2 架构设计

```
当前 engine.py (1616 行):
┌─────────────────────────────────────────────────────┐
│ WyckoffEngine                                        │
│  ├─ _detect_accumulation()        ← 保留，加入量能    │
│  ├─ _detect_markup()              ← ✅ 保留           │
│  ├─ _detect_distribution()        ← ❌ 删除           │
│  ├─ _detect_markdown()            ← ✅ 保留           │
│  ├─ _detect_spring()              ← 改引用新模块      │
│  ├─ _detect_utad()                ← ❌ 删除空函数     │
│  ├─ _detect_sos()                 ← ❌ 删除空函数     │
│  ├─ _step1_phase_determine()       ← 重写为状态机     │
│  ├─ _step2_...                     ← ✅ 保留           │
│  ├─ _step3_phase_c_t1()           ← 改引用新模块      │
│  ├─ _step4_risk_reward()          ← ✅ 保留           │
│  ├─ _calc_confidence()            ← 引用 confidence_v2 │
│  └─ _step5_trading_plan()        ← ✅ 保留+扩展      │
└─────────────────────────────────────────────────────┘
          │
          ▼ 扩展为:
┌───────────────────────────────────────────────────────────────────┐
│ brain/wyckoff/ (新结构)                                           │
├───────────────────────────────────────────────────────────────────┤
│  engine.py (800 行 — 主流程精简)                                  │
│    ├─ analyze(df, multi_timeframe) → WyckoffReport               │
│    ├─ 调用 tr_detector → phase_machine → event_labeler           │
│    ├─ 调用 volume_spread → spring_utad → confidence_v2           │
│    ├─ 调用 pnf_chart → nine_tests                                │
│    └─ _step5_trading_plan 保留                                    │
│                                                                   │
│  tr_detector.py          ~300行  — 多周期 TR 检测 + Phase A       │
│  volume_spread.py        ~200行  — 成交量价差分析                  │
│  phase_machine.py        ~400行  — A-E 状态机                     │
│  event_labeler.py        ~250行  — SOS/LPS/SOW/LPSY 事件         │
│  spring_utad.py          ~150行  — Spring/UTAD 可选事件           │
│  pnf_chart.py            ~350行  — P&F 点数图 + Cause 计数        │
│  nine_tests.py           ~200行  — 可自动化的九项测试              │
│  confidence_v2.py        ~150行  — 分层贝叶斯置信度               │
│                                                                   │
│  constants.py           不变     — 配置常量                       │
│  analysis.py            不变     — Chip 分析等辅助函数            │
│  classifiers.py         不变     — 分类辅助                       │
│  models.py              扩展     — 新增 A-E 模型                  │
│  rules.py               不变     — 规则引擎                       │
└───────────────────────────────────────────────────────────────────┘
```

### 2.3 模块详细设计

#### tr_detector.py (P0, ~300行)

**功能**: 多周期交易区间检测 + Phase A 事件标注

```
输入: df(日线), df_weekly(周线), df_monthly(月线)
输出: TradingRange(上下边界, 类型, 形成时间, Phase A 事件列表)

算法:
1. 日线: 识别区间（价格范围 < 20% + 短趋势 < 5% 连续 >= 30 天）
2. 周线: 识别更大尺度区间 (范围 < 25% + 连续 8+ 周)
3. 月线: 识别超级区间 (范围 < 30% + 连续 6+ 月)
4. Phase A 事件:
   - 找 SC (Selling Climax): 下跌末段最低点 + 最大 volume + wide spread
   - 找 ST (Secondary Test): SC 后 5-20 天内回头测试 SC 底部 + 缩量
   - 找 PSY (Preliminary Supply): 上涨末段 + 放量滞涨
   - 找 BC (Buying Climax): 上涨末段 + 最大 volume + 最长上影线
5. 边界: TR 的范围 = [min(SC_low, ST_low), max(AR_high, 反弹高点)]

适配基金: 基金跳过 Phase A 事件检测 (SC/ST 只适用于股票)
```

#### volume_spread.py (P0, ~200行)

**功能**: 每根 bar 的供求分类 + Effort vs Result 背离

```
输入: df(OHLCV)
输出: per-bar 分类 (strong_buy/weak_buy/neutral/weak_sell/strong_sell)

算法:
1. 计算 spread_pct = (H-L)/L
2. 计算 vol_ratio = V / V_ma20
3. 分类矩阵:
       Close↑/Spread↑/Vol↑  = SOS (strong demand)
       Close↑/Spread↓/Vol↓  = LPS (weak demand=good)
       Close↓/Spread↑/Vol↑  = SOW (strong supply)
       Close↓/Spread↓/Vol↓  = drying up (supply exhausted)
       Vol↑/Spread↓/Close~  = EFFORT_NO_RESULT (absorption/distribution)
4. Effort vs Result:
   - 累加 5 天 vol_ratio(努力) vs 累加 5 天 spread_pct(结果)
   - 背离: 努力↑结果↓ → 派发检查
   - 背离: 努力↓结果↑ → 积累检查
```

#### phase_machine.py (P0, ~400行)

**功能**: A-E 相位状态机

```
状态: UNKNOWN → ACCUMULATION_PHASE_A → B → C → D → E
               → DISTRIBUTION_PHASE_A → B → C → D → E
               → MARKUP (Phase E already in trend)
               → MARKDOWN (Phase E already in downtrend)

状态转换:
  UNKNOWN → ACC_A: 趋势↓ + TR detected + (SC or ST found)
  UNKNOWN → DIST_A: 趋势↑ + TR detected + (PSY or BC found)
  ACC_A → ACC_B: TR 内 2+ 次 ST, 价格在区间内震荡
  ACC_B → ACC_C: TR 内出现 Spring 或 SOS 信号
  ACC_C → ACC_D: SOS 突破 TR 上边界 + volume 确认
  ACC_D → ACC_E: LPS 缩量回调后继续向上
  ACC_E → MARKUP: 持续新高, volume 温和
  MARKUP → DIST_A: 出现放量滞涨或 BC 信号

特殊状态:
  REACCUMULATION: markup 过程中的短暂横盘重蓄
  REDISTRIBUTION: markdown 过程中的反弹再派发

适配基金: 状态机简化为 MARKUP/MARKDOWN/UNKNOWN 三级
```

#### event_labeler.py (P0, ~250行)

**功能**: 标注 Wyckoff 结构事件

```
检测函数:
  is_sos(bar, context): 收盘创新高 + spread > avg + vol > avg*1.5
  is_lps(bar, context): SOS 后回调 + 缩量(vol < avg*0.7) + 支撑确认
  is_ps(bar, context): 长期下跌后放量止跌 (vol > avg*2.0 + low 创新低后收回)
  is_sc(bar, context): PS 的更强版 (vol > avg*3.0 + spread > max spread)
  is_psy(bar, context): 上涨后放量滞涨 (vol > avg*2.0 + close 在 range 中段)
  is_bc(bar, context): PSY 的更强版 (vol > avg*3.0 + 长上影线)
  is_sow(bar, context): 支撑位破位放量 (close < TR_low + vol > avg*1.5)
  is_lpsy(bar, context): 破位后无力反弹 (close 回到 TR 下边界附近 + vol < avg*0.5)

事件置信度: 每个事件附带 0-1 分, 基于条件满足度加权
```

#### spring_utad.py (P0, ~150行)

**功能**: Spring/UTAD 检测（可选事件，不门控）

```
is_spring(df, boundary_low) → Optional[SpringEvent]:
  1. 有 TR 边界: 价格 < boundary_low*0.98 → 收盘 > boundary_low → spring=True
  2. 无 TR 边界: 局部 20 天新低 → 次日收回 50%+ → spring_candidate=True
  3. Volume: 放量=一级, 缩量=二级(需确认)
  4. 输出: spring_detected, quality, date, price
  5. 关键: 不影响相位判定, 只影响交易计划方向

is_utad(df, boundary_high) → Optional[UTADEvent]:
  1. 有 TR 边界: 价格 > boundary_high*1.02 → 收盘 < boundary_high → utad=True
  2. 无 TR 边界: 局部 20 天新高 → 次日收回 50%+ → utad_candidate=True
  3. 关键: 仅在有 TR 时启用 distribution 路径, 否则跳过
```

#### pnf_chart.py (P1, ~350行)

**功能**: P&F 点数图构建 + Cause 计数

```
class PointAndFigure:
    box_size: float    # 如 0.5(低价) / 1.0(中价) / 5.0(高价)
    reversal: int = 3  # 3-box reversal (标准)
    
    build(df) → pnf_columns:
        # 从 OHLC 构建 P&F 列
        # X 列 = 上涨, O 列 = 下跌
        # 反转条件: 当前方向反向移动 >= box_size * reversal
    
    count_cause(tr_low, tr_high) → (min_target, max_target):
        # 在 TR 内横向计数列数
        # 目标 = 列数 × box_size × reversal
        # min_target = count × box_size + tr_low
        # max_target = count × box_size + tr_high
    
    难点: box_size 自适应选择 (根据价格)
```

#### nine_tests.py (P1, ~200行)

**功能**: 自动化九项买入/卖出测试

```
自动化的 6/9 项:
  1. Downside objective accomplished: P&F 计数目标已接近 (可自动)
  2. Activity bullish: 上涨放量, 下跌缩量 (可自动)
  3. Downward stride broken: 下降趋势线突破 (可自动)
  4. Higher lows: 最近 3 个低点上移 (可自动)
  5. Higher highs: 最近 3 个高点上移 (可自动)
  6. Base forming: TR 已形成 (可自动)
  

}

需主观判断的 3/9 项:
  7. Stock stronger than market: 相对强度 vs 大盘
  8. Estimated profit >= 3x risk: 盈亏比计算 (可近似)
  9. P&F objective: 目标实现确认

输出: passing_tests / total_tests, test_detail[]
```

#### confidence_v2.py (P0, ~150行)

**功能**: 分层贝叶斯置信度

```
class BayesianConfidence:
    signal_stats: Dict[str, SignalStat]  # 从历史回测中积累
    
    def compute(self, signal_type, current_conditions):
        # 先验: 该信号类型的历史 20d 胜率
        prior = self.signal_stats.get(signal_type, default_stat)
        
        # 似然: 当前条件吻合度 (0-1)
        likelihood = (
            volume_confirm * 0.25 +   # 成交量确认
            trend_clarity * 0.25 +     # 趋势清晰度
            rr_quality * 0.20 +        # 盈亏比质量
            multi_tf_aligned * 0.15 +  # 多周期一致
            event_quality * 0.15       # 事件质量
        )
        
        # 后验
        posterior = (prior.win_rate * prior.n + likelihood * 20) / (prior.n + 20)
        return posterior
```

### 2.4 现有代码修改

| # | 文件 | 改什么 | 行数变化 |
|---|---|---|---|
| A | `brain/wyckoff/engine.py` | 精简为~800行: 主流程调用模块化组件, 删除 UTAD/SOS 空函数 | -400/+200 |
| B | `brain/wyckoff/models.py` | 新增 `TradingRange`, `PhaseAEvent`, `PhaseState`, `WyckoffEvent`, `PnFAnalysis` 等 dataclass | +100 |
| C | `shared/interfaces.py` `WyckoffOutput` | 新增 `phase_a_events`, `phase_state`, `trading_range`, `pnf_analysis`, `trading_direction` | +30 |
| D | `signal/adapters.py` `WyckoffAdapter` | 重写为暴露 `trading_plan.direction` | ±30 |
| E | `services/analysis/wyckoff_analysis_engine.py` | 支持资产类型参数 (`asset_type="stock"|"fund"`)，基金跳过 Spring/TR 检测 | +50 |
| F | `brain/wyckoff/constants.py` | 基金专用常量: `FUND_MIN_DATA_ROWS`, `FUND_SKIP_SPRING` | +10 |

### 2.5 基金/ETF 特殊适配 (P0, 嵌入在各模块中)

```python
# phase_machine.py: 基金简化为 3 状态
def run_for_fund(df, ctx):
    """基金没有 TR 结构，只检测马克/马克达"""
    if is_uptrend(df):
        return PhaseState.MARKUP
    elif is_downtrend(df):
        return PhaseState.MARKDOWN
    return PhaseState.UNKNOWN

# tr_detector.py: 基金跳过 A 事件
def detect_trading_range(df, is_fund=False):
    if is_fund:
        return None  # 基金没有可识别的 TR
    # ... 正常 TR 检测
```

### 2.6 当前代码保留/迁移计划

```
engine.py 原始 1616 行:
 保留 (~500 行):
   - WyckoffEngine.__init__()                   + config
   - analyze()                                  主流程框架
   - _detect_markup()                           ✅
   - _detect_markdown()                         ✅
   - _detect_accumulation()                     (加入量能加权)
   - _compute_step1_context()                   上下文计算
   - _step2_causal_analysis()                   因果分析
   - _step4_risk_reward()                       ✅
   - _step5_trading_plan()  markup 分支          ✅
   - _classify_wyckoff_markup_event()           ✅
   - _detect_limit_moves()                      ✅

 重写/重构 (~600 行):
   - _step1_phase_determine()  →  phase_machine.py 状态机
   - _step3_phase_c_t1()      →  spring_utad.py + event_labeler.py
   - _calc_confidence()       →  confidence_v2.py
   - _detect_spring()         →  spring_utad.py

 删除 (~500 行):
   - _detect_distribution()    ❌ 条件互斥
   - _detect_utad()            ❌ 空函数
   - _detect_sos()             ❌ 空函数
   - _step5 中的 ACCUMULATION Spring 门控 ❌
   - 旧置信度系统 (A/B+/B/C/D) ❌
```

### 2.7 执行顺序

```
Phase 1 (Day 1-3): 基础设施
   ├─ volume_spread.py           — 供求分类核心
   ├─ event_labeler.py           — SOS/LPS/SOW 事件
   └─ tr_detector.py             — 多周期 TR 检测
   验证: 对 golden_20 的识别准确率

Phase 2 (Day 4-6): 相位系统
   ├─ phase_machine.py           — A-E 状态机
   ├─ spring_utad.py             — Spring/UTAD 可选事件
   └─ confidence_v2.py           — 分层贝叶斯
   验证: 对 golden_20 的 A→E 识别率 > 60%

Phase 3 (Day 7-10): P&F + 九项测试
   ├─ pnf_chart.py               — P&F 点数图
   └─ nine_tests.py              — 自动化测试
   验证: P&F 横向计数一致性

Phase 4 (Day 11-15): 集成 + 全量回测
   ├─ engine.py 重构              — 精简主流程
   ├─ fund 适配                    — 基金特殊处理
   ├─ WyckoffOutput 扩展          — 输出结构更新
   ├─ WyckoffAdapter 重写         — 暴露 trading_plan.direction
   └─ 全量 walk-forward 回测      — 3574 只 × 6 窗口
   验证:
   - "买入"信号 MC p<0.05 (多重比较校正后)
   - 空头信号触发率 > 0% (UTAD 实现后)
   - 全量回测不崩溃

Phase 5 (Day 16-20): 优化 + 测试
   ├─ 性能优化 (numba/numpy 向量化)
   ├─ 额外测试 (黄金/白银 100 验证)
   └─ 文档 + AGENTS.md 更新
```

### 2.8 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| P&F 点数图 box_size 自适应难以调优 | 高 | 可能导致目标投射失准 | Phase 4 先不输出 P&F count, 作为研究特征 |
| 基金/ETF 无 TR 结构, Wyckoff 不适用 | 极高 | 基金分析等于"白做" | 基金跳到简化的 MARKUP/MARKDOWN 二级分类 |
| 状态机在震荡市频繁切换 | 中 | 信号质量下降 | hysteresis 机制: 相位切换需要 3+ 个 bar 确认 |
| 全量 5000 只回测空头信号仍为 0 | 中 | Distribution 确实无法检测 | 尝试简化的 UTAD 不在 TR 内也检测; 如仍为 0 → 空头标记"依赖外部引擎" |

---

## 三、总工作量汇总

| 模块 | 纯新增 | 修改现有 | 净增行 | 时间 |
|---|---|---|---|---|
| LPPL 指数 | ~1080 | ~+205/-0 | ~1285 | **1人 × 2周** |
| Wyckoff 完整(P0) | ~1450 | ~+420/-900 | ~970 | **1人 × 3周** |
| Wyckoff P&F+九项(P1) | ~550 | ~+0/-0 | ~550 | **1人 × 1周** |
| **合计** | **~3080** | **~+625/-900** | **~2805** | **1人 × 5-6周** |
| 紧急修复优先 | ~0 | ~+150/-60 | ~90 | **1人 × 2天** |

**推荐执行策略**: 紧急修复(2天) → LPPL指数(2周) → Wyckoff P0(3周) → Wyckoff P1(1周，看P0结果决定)  
**并行可能**: LPPL指数 + Wyckoff Phase 1 可并行 (2人 × 3周)
