# 因子计算性能优化计划

## 基准数据（瓶颈确认）

- **FACTOR 阶段: 76.5s**, 占全流水线 76%
- 10 个因子, 18.8M 行 (5934 股票 × ~3169 个交易日均值)
- `compute_all_factors` 是唯一没有并行化的阶段

## 瓶颈根因

| 问题 | 代价 | 说明 |
|------|------|------|
| 双重串行循环 | 76s 主体 | 10 因子 × 5000 组 = 50,000 次迭代 |
| `.copy()` 调用 | ~15-20s | 每组每个因子做 `.copy()`, 50,000 次 |
| `.sort_values("date")` | ~8-12s | 每组排序 10 次, 实际只需排序一次 |
| `groupby("code")` 重复 | ~5-8s | 10 次 groupby(18M 行) |
| `.loc` 逐组回写 | ~5-8s | 50,000 次标签索引 |
| 所有运算 float64 | 内存 1.44 GB | 缓存未命中, 可压至 float32 |

---

## P0 — 核心加速（投产即用）

### 0.1 并行因子计算

**文件**: `composer.py`

**方案**: 用 `ThreadPoolExecutor(8)` 并行执行 10 个因子。每个因子操作的是同一个 df 的不同副本, 不存在 data race。pandas/numpy 底层释放 GIL, 线程池有效。

```python
def compute_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    def _compute_one(factor):
        try:
            series = pd.Series(index=df.index, dtype=float)
            for group in self._iter_groups(df):
                # group 预排序 + 无 copy
                s = factor.compute_func(group)
                if len(s) != len(group):
                    continue
                series.loc[group.index] = np.asarray(s, dtype=float)
            return factor.name, series
        except Exception as e:
            logger.error(f"因子 {factor.name} 计算失败: {e}")
            return factor.name, None

    enabled = self.registry.get_enabled()
    n_workers = min(os.cpu_count() or 8, len(enabled))
    factor_values = pd.DataFrame(index=df.index)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_compute_one, f): f for f in enabled}
        for future in as_completed(futures):
            name, series = future.result()
            if series is not None:
                factor_values[name] = series
    return factor_values
```

**预期加速**: **~5-6x** (10 因子 / 8 线程, 有序列化开销)
**预期时间**: 76s → **~13-15s**

### 0.2 单次 groupby + 预排序

**文件**: `composer.py`

**方案**: 不再每个因子建 groupby, 改为按 (code, date) 全局排序一次, 将 groupby 结果缓存, 按索引切片传递。

```python
def _prepare_groups(self, df: pd.DataFrame):
    """预排序 + 预分组的优化版本。"""
    if "code" not in df.columns:
        yield df.index, df.sort_values("date")
        return

    sorted_df = df.sort_values(["code", "date"]).reset_index(drop=True)
    # 用 groupby 的 indices 原地切片, 避免 copy
    for _, idx in sorted_df.groupby("code", sort=False).indices.items():
        group = sorted_df.iloc[idx]
        yield group.index, group  # 传原始索引和切片视图
```

**预期加速**: **1.3-1.5x** (消除排序 + copy + 重复 groupby)
**预期时间**: 原 76s → **~50s** (单独此项)

### 0.3 Numba 矢量化滚动因子

**文件**: `custom_factors.py`

**方案**: 对 3 个计算最密集的滚动因子 (volatility_20d, volatility_60d, rsi_14) 创建 Numba 矢量化版本。pandas `.rolling().std()` 背后是循环, Numba 可消除每组的 Python 开销。

```python
from numba import njit
import numpy as np

@njit(cache=True, fastmath=True)
def _numba_rolling_std(values: np.ndarray, window: int, sqrt_n: float) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        s = 0.0
        mean = 0.0
        for j in range(i - window + 1, i + 1):
            mean += values[j]
        mean /= window
        for j in range(i - window + 1, i + 1):
            diff = values[j] - mean
            s += diff * diff
        out[i] = np.sqrt(s / (window - 1)) * sqrt_n
    return out


def compute_volatility_20d_numba(df: pd.DataFrame) -> pd.Series:
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    if not _NUMBA_AVAILABLE:
        return compute_volatility_20d(df)  # fallback
    returns = df["close"].pct_change(fill_method=None).values.astype(np.float64)
    result = _numba_rolling_std(returns, 20, np.sqrt(252))
    return pd.Series(result, index=df.index)
```

**预期加速**: **2-3x** 在滚动因子上, 全局约 **1.3x**
**预期时间贡献**: 原 25-30s → **~10-12s**

### 0.4 合并预期 (P0 合计)

| 步骤 | 单项加速 | 累积时间 |
|------|---------|---------|
| 当前 | 1x | 76s |
| 预排序 + 去 copy | 30% 减少 | ~53s |
| 并行 (8线程) | 5x | ~11s |
| Numba 滚动 | 20% 叠加 | ~9s |
| **P0 总计** | **~8.4x** | **~9s** |

---

## P1 — 中等优化

### 1.1 Float32 压缩

**文件**: `composer.py`

所有因子值可以用 float32 存储 (精度损失 < 1e-7, 对因子排名无影响)。

```python
factor_values[factor.name] = series.astype(np.float32)
```

18M × 10 × 4 bytes = **720 MB** (vs 1.44 GB), 减少内存带宽压力。

### 1.2 因子归并计算

多个因子共享相同的中间计算:

| 归并组 | 共享计算 | 现有因子 |
|--------|---------|---------|
| 动量组 | `close.pct_change()` | momentum_20d, momentum_60d |
| 波动率组 | `returns.rolling()` | volatility_20d, volatility_60d |
| 均线组 | `close.rolling()` | ma_ratio_5_20, ma_ratio_10_60 |

改为一次计算共享中间结果, 避免重复:

```python
def compute_all_factors_batch(self, df: pd.DataFrame) -> pd.DataFrame:
    # 归并分组计算  → 每个因子列
    factors = {}
    factors["momentum_20d"] = df["close"].pct_change(20)
    factors["momentum_60d"] = df["close"].pct_change(60)
    # ... 其他因子
    
    return pd.DataFrame(factors, index=df.index)
```

**预期加速**: **1.2x**

### 1.3 日期分组标准化矢量化

**文件**: `composer.py` 的 `_normalize_factors`

```python
# 矢量化解: 利用 transform
def _normalize_factors(self, df, factor_df, date_col="date"):
    if date_col not in df.columns:
        return self._zscore_frame(factor_df)
    combined = df[[date_col]].join(factor_df)
    normalized = combined.groupby(date_col).transform(
        lambda g: (g - g.mean()) / g.std().replace(0, np.nan)
    )
    return normalized.fillna(0.0)
```

**预期加速**: **2-3x** (消除 Python for 循环)

---

## P2 — 未来优化

| 项 | 方案 | 预期加速 | 备注 |
|----|------|---------|------|
| rewrite 全组因子 | 用 numba 一版计算 4-5 个滚动因子, 单次扫描 | 3-5x | 代码量较大 |
| 惰性因子缓存 | 当输入 df 不变时跳过重复计算 | 无限次后 0s | 需 LRU 缓存 |
| DuckDB 推 SQL | 用 SQL 窗口函数替代 pandas groupby | 5-10x | 适合超大规模 |
| Polars 替换 pandas | `.lazy().group_by().agg()` | 3-5x | 需依赖 |

---

## 实施顺序

```
Week 1    P0.1 并行因子    → 15-20 人时    → 76s → 15s
          P0.2 预排序去copy → 5-8 人时      → 15s → 11s
Week 2    P0.3 Numba 滚动   → 15-20 人时    → 11s → 9s
          P1.1 float32      → 2-3 人时       → 内存减半
          P1.3 标准化矢量化  → 3-5 人时       → 1s → 0.3s
Week 3    P1.2 因子归并     → 8-12 人时      → ~8s
          集成测试 + 回归
```

## 验证

```bash
# 运行微基准
cd src && python -m pytest tests/ -k "factor" -v --benchmark-only

# 全量扫描验证
cd scripts && python run_market_scan.py

# 验证结果一致性 (因子值变化 < 1e-6)
```
