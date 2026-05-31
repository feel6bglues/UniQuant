# UniQuant 投研实验问题修复建议

> 基于 2026-05-30 多模型共振投研实验发现的问题
> 按优先级排序：P0 (紧急) → P1 (重要) → P2 (改进)

---

## P0 — 紧急修复（阻塞投研流程）

### 1. 模块命名冲突：`uniquant.shared.limits` 不存在

**问题**：`brain/wyckoff/classifiers.py:11` 导入不存在的模块
```python
from uniquant.shared.limits import is_limit_down, is_limit_up  # ❌ 不存在
```

**影响**：Wyckoff 引擎无法正常导入，需在实验脚本中添加 mock 才能运行

**修复方案**：在 `src/uniquant/shared/limit_checker.py` 中添加别名函数

```python
# 在 limit_checker.py 末尾添加
def is_limit_down(data, prev_close, code_prefix, is_st=False):
    """兼容旧接口"""
    price = data.get("close", 0) if isinstance(data, dict) else getattr(data, "close", 0)
    result = check_limit_status(price, prev_close, code_prefix, is_st=is_st)
    return result.get("is_limit_down", False) if isinstance(result, dict) else False

def is_limit_up(data, prev_close, code_prefix, is_st=False):
    """兼容旧接口"""
    price = data.get("close", 0) if isinstance(data, dict) else getattr(data, "close", 0)
    result = check_limit_status(price, prev_close, code_prefix, is_st=is_st)
    return result.get("is_limit_up", False) if isinstance(result, dict) else False
```

或修改 `classifiers.py` 的导入：
```python
# classifiers.py:11 修改为
from uniquant.shared.limit_checker import check_limit_status
# 然后将 is_limit_down/up 调用改为 check_limit_status
```

---

### 2. 复权因子数据缺失

**问题**：`data/fq/` 目录为空，无法执行前后复权

**影响**：
- 使用未复权价格计算收益，结果不可信
- 除权除息日会产生虚假的涨跌幅

**修复方案**：

```bash
# 方案 A：运行已有的复权因子下载脚本
.venv/bin/python src/uniquant/data/scripts/download_baostock_factors.py

# 方案 B：运行 mootdx 复权因子同步
.venv/bin/python src/uniquant/data/scripts/sync_factors_mootdx.py

# 方案 C：手动从 baostock 获取复权因子
```

---

## P1 — 重要修复（影响投研质量）

### 3. LPPL 置信度未内置

**问题**：`LPPLCalculator.fit_single_window()` 不返回置信度，需外部计算

**影响**：每次调用后需额外编写置信度计算逻辑，容易出错

**修复方案**：修改 `calculator.py:335`，在返回结果中增加置信度

```python
# calculator.py:335 修改
fit_result = {
    "params": params,
    "rmse": rmse,
    "t_len": current_t,
    "confidence": self._calculate_confidence_from_params(tc, m, w, b, c, rmse, current_t)
}

def _calculate_confidence_from_params(self, tc, m, w, b, c, rmse, data_len) -> float:
    """从参数直接计算置信度"""
    m_valid = self.m_min < m < self.m_max
    w_valid = self.w_min < w < self.w_max
    b_valid = b < 0
    c_valid = abs(c) > self.c_min_abs

    score = 0.0
    if m_valid:
        score += self.tc_weight
    if w_valid:
        score += self.tc_weight * 0.5
    if b_valid:
        score += self.cost_weight
    if c_valid:
        score += self.cost_weight * 0.5

    # RMSE 惩罚
    if rmse < self.cost_scale:
        score += self.data_weight
    elif rmse < self.cost_scale * 2:
        score += self.data_weight * 0.5

    return min(1.0, score)
```

---

### 4. WyckoffReport 结构过于复杂

**问题**：`analyze()` 返回的 `WyckoffReport` 字段嵌套深，提取信号需多层访问

**影响**：调用方代码复杂，容易出错

**修复方案**：在 `WyckoffEngine` 中增加轻量级接口

```python
# engine.py 末尾添加
@dataclass
class WyckoffSignalSummary:
    """轻量级信号摘要"""
    symbol: str
    date: datetime
    phase: str  # ACCUMULATION, DISTRIBUTION, MARKUP, MARKDOWN, UNKNOWN
    signal_type: str  # SPRING, UTAD, SOS, LPS, NONE
    action: str  # BUY, SELL, HOLD
    confidence: float
    struct_clarity: str

def scan_signal(self, df: pd.DataFrame, symbol: str = "UNKNOWN") -> WyckoffSignalSummary:
    """轻量级信号扫描 - 仅返回信号标签"""
    report = self.analyze(df, symbol=symbol)

    # 提取关键信息
    phase = report.structure.phase.value if report.structure else "UNKNOWN"
    signal_type = report.signal.signal_type.value if report.signal else "NONE"
    action = report.trading_plan.action if report.trading_plan else "HOLD"
    confidence = report.signal.confidence if report.signal else 0.0
    struct_clarity = report.structure.struct_clarity if report.structure else "未知"

    return WyckoffSignalSummary(
        symbol=symbol,
        date=df['date'].iloc[-1],
        phase=phase,
        signal_type=signal_type,
        action=action,
        confidence=confidence,
        struct_clarity=struct_clarity
    )
```

---

### 5. Wyckoff 阶段识别失效

**问题**：实验中 Wyckoff 阶段分布全部为 0，无法识别 ACCUMULATION/DISTRIBUTION

**影响**：共振信号无法正确分类，回测结果不可信

**根因分析**：
- `WyckoffReport.structure.phase` 始终返回 UNKNOWN
- 可能是 `_step1_phase_determine()` 的阈值过于严格

**修复方案**：放宽阶段识别阈值

```python
# engine.py:294 修改阈值
# 原始：prior_trend_pct < -0.10
# 修改为：
if prior_trend_pct < -0.05:  # 从 -10% 放宽到 -5%
    phase = WyckoffPhase.ACCUMULATION
elif prior_trend_pct > 0.05:  # 从 +10% 放宽到 +5%
    phase = WyckoffPhase.DISTRIBUTION
```

---

## P2 — 改进项（提升投研效率）

### 6. 批量扫描接口缺失

**问题**：LPPL 和 Wyckoff 引擎只能逐股票、逐时间点串行扫描

**影响**：20 只股票 × 25 个时间点 × 3 引擎 = 约 30-60 分钟

**修复方案**：增加批量扫描接口

```python
# calculator.py 添加
def fit_batch(self, close_prices_list: List[np.ndarray]) -> List[Optional[Dict]]:
    """批量拟合多个窗口"""
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(self.fit_single_window, close_prices_list))
    return results

# engine.py 添加
def scan_batch(self, df_list: List[pd.DataFrame], symbols: List[str]) -> List[WyckoffSignalSummary]:
    """批量扫描多个股票"""
    return [self.scan_signal(df, sym) for df, sym in zip(df_list, symbols)]
```

---

### 7. Parquet 列名不统一

**问题**：部分文件含 `reserved` 列，部分不含；`code` 列格式不一致

**影响**：数据加载后需额外处理列名

**修复方案**：统一 Parquet 写入规范

```python
# storage_manager.py 写入时统一列名
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'code']

def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
    """统一列名"""
    df = df.copy()
    # 移除非标准列
    for col in df.columns:
        if col not in STANDARD_COLUMNS and col not in ['turnover', 'turnover_rate']:
            df = df.drop(columns=[col])
    # 确保 code 列存在
    if 'code' not in df.columns:
        df['code'] = ''
    return df
```

---

### 8. 信号阈值校准机制缺失

**问题**：LPPL 置信度阈值 (0.4) 和 Wyckoff 阈值均为固定值，容易过拟合

**影响**：样本外表现大幅衰减

**修复方案**：增加 Walk-Forward 校准

```python
# 新增 src/uniquant/brain/calibration/threshold_optimizer.py
class ThresholdOptimizer:
    """阈值优化器 - Walk-Forward 方法"""

    def optimize(
        self,
        signals: List[ResonanceSignal],
        returns: pd.Series,
        n_splits: int = 5
    ) -> Dict[str, float]:
        """滚动优化阈值"""
        optimal_thresholds = []

        for train_idx, test_idx in self._walk_forward_split(signals, n_splits):
            # 在训练集上优化
            train_signals = [signals[i] for i in train_idx]
            train_returns = returns.iloc[train_idx]

            # 网格搜索最优阈值
            best_threshold = self._grid_search(train_signals, train_returns)
            optimal_thresholds.append(best_threshold)

        # 返回平均阈值
        return {
            'lppl_confidence': np.mean([t['lppl_confidence'] for t in optimal_thresholds]),
            'wyckoff_strength': np.mean([t['wyckoff_strength'] for t in optimal_thresholds]),
        }
```

---

### 9. 因子管道与信号管道未打通

**问题**：因子计算独立于 LPPL/Wyckoff 扫描，未实现实时因子暴露

**影响**：共振信号无法实时获取因子调整依据

**修复方案**：在信号扫描时同步计算因子

```python
# research_experiment.py 修改
def scan_with_factors(self, df, symbol, scan_date):
    """带因子的信号扫描"""
    lppl = self.lppl_scanner.scan_window(...)
    wyckoff = self.wyckoff_scanner.scan(df, symbol)

    # 实时计算因子
    factors = self.factor_calculator.calculate(df.tail(60), symbol)

    # 因子调整信号置信度
    if lppl and factors:
        lppl.confidence = self._adjust_confidence_by_factors(lppl.confidence, factors)

    return lppl, wyckoff, factors
```

---

## 优先级排序建议

| 序号 | 问题 | 优先级 | 预计工时 | 影响范围 |
|------|------|--------|----------|----------|
| 1 | 模块命名冲突 | P0 | 0.5h | Wyckoff 引擎无法导入 |
| 2 | 复权因子数据缺失 | P0 | 1h | 所有收益计算不可信 |
| 3 | LPPL 置信度内置 | P1 | 1h | 简化调用方代码 |
| 4 | Wyckoff 轻量级接口 | P1 | 2h | 提升扫描效率 |
| 5 | Wyckoff 阶段识别失效 | P1 | 2h | 共振信号无法分类 |
| 6 | 批量扫描接口 | P2 | 4h | 性能优化 |
| 7 | Parquet 列名统一 | P2 | 1h | 数据一致性 |
| 8 | 阈值校准机制 | P2 | 8h | 防止过拟合 |
| 9 | 因子管道打通 | P2 | 4h | 实时因子调整 |

**总计预计工时**：约 23.5 小时

---

## 建议执行顺序

```
第一轮（Day 1）：
├── P0: 修复模块命名冲突 (0.5h)
├── P0: 下载复权因子数据 (1h)
└── P1: LPPL 置信度内置 (1h)

第二轮（Day 2）：
├── P1: Wyckoff 轻量级接口 (2h)
├── P1: 修复阶段识别阈值 (2h)
└── 验证：重新运行投研实验

第三轮（Day 3-4）：
├── P2: 批量扫描接口 (4h)
├── P2: Parquet 列名统一 (1h)
└── P2: 阈值校准机制 (8h)

第四轮（Day 5）：
├── P2: 因子管道打通 (4h)
└── 全量 A 股实验验证
```

---

*建议基于 2026-05-30 投研实验结果，优先修复 P0 问题后重新验证实验结论。*
