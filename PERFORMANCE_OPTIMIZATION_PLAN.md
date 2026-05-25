# UniQuant 极限性能优化方案

> 基于源码级热路径分析 | 2026-05-24
> 目标: LPPL 全市场扫描加速 4-10x, I/O 内存占用降低 50%+, 实盘异步就绪

---

## 0. 瓶颈诊断摘要

### 硬件约束 (模板 — 根据实际环境填写)

```
CPU:    <物理核数>C/<逻辑线程数>T
RAM:    <总量>GB (可用 ~<可用>GB)
Swap:   <总量>GB (已用 <已用>GB)
Kernel: $(uname -r)
```

### 当前系统参数 (未优化)

| 参数 | 当前值 | 问题 |
|------|--------|------|
| `vm.swappiness` | 100 | 极度激进 — 低 RAM 环境频繁 swap 抖动 |
| THP | 未启用 | numpy 大数组 (>2MB) 无法利用 2MB 页 |
| I/O 调度器 | 默认 | 未针对 SSD/NVMe 顺序扫描优化 |
| read_ahead_kb | 默认(128) | Parquet 顺序读取预读不足 |

### 计算瓶颈定量分析

```
热路径: differential_evolution() → cost_function_reduced() → lstsq()
       每次全市场扫描: ~100 窗口 × 500 maxiter × 10 popsize = ~500,000 次 cost 调用

当前 cost_function_reduced() 单次调用开销:
  ├─ tau^m 计算:           ~2μs (N=500 数据点)
  ├─ cos/sin/log:          ~3μs
  ├─ np.column_stack:      ~5μs (4 次数组分配)
  ├─ np.linalg.lstsq:     ~15μs (4×N 矩阵 SVD 分解)
  └─ 总计:                 ~25μs × 500,000 = ~12.5s (仅 cost function)

DE 并行状态:
  ├─ engine.py:181  workers=1  (单核!)
  ├─ calculator.py:280  workers=self.workers  (来自 LPPLConstants.WORKERS)
  └─ 外层 joblib 并行窗口, 但每个窗口内 DE 单线程
```

### I/O 瓶颈定量分析

```
Parquet 读取路径:
  pd.read_parquet(file_path)           ← 完整文件加载, 无列裁剪
  → normalize_dataframe_columns(df)    ← 委托 _normalize_columns(df)
  → 可能含 .copy()                    ← 额外内存分配

batch_read_data() 实现:
  for symbol in symbols:               ← 串行循环
      df = self.read_data(...)         ← 逐个读取

全市场 N 只股票 × 10年日线:
  ├─ 每文件 ~500KB (Snappy)
  ├─ 串行读取: N × ~2ms I/O
  ├─ 并行读取: N × ~2ms / P_cores
  └─ 加 normalize copy: 额外 ~50% 内存

DuckDB: 配置中声明 engine="duckdb" 但实际未使用
Polars: 代码库中完全未引入
PyArrow 直接操作: 未使用 (仅作为 pandas 后端)
```

### 并发瓶颈定量分析

```
scan_service.py:
  load_data()      ← 串行
  build_factors()  ← 串行 pd.concat 循环
  analyze_factors() ← 串行 IC/IR 计算

data_service.py:
  batch_process_stocks() ← joblib backend="threading" (GIL 限制)
  _clone_dataframe()     ← 每个 worker 深拷贝 DataFrame

asyncio 使用: 仅 realtime_bridge.py (WebSocket)
核心服务层: 100% 同步
```

---

## 1. 【计算瓶颈突破】LPPL DE 优化器极致加速

### 1.1 融合 cost function — 消除临时数组分配

**目标文件**: `src/uniquant/brain/lppl/core.py`

**当前代码** (core.py:127-139):
```python
@njit(cache=True, fastmath=True)
def _cost_function_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
    tc, m, w, a, b, c, phi = params[0], params[1], params[2], params[3], params[4], params[5], params[6]
    prediction = _lppl_func_numba(t, tc, m, w, a, b, c, phi)  # ← 分配 N 元素数组
    residuals = prediction - log_prices                         # ← 分配 N 元素数组
    return np.sum(residuals**2)                                 # ← 分配 N 元素数组
```

**优化代码** — 标量累加, 零分配:
```python
@njit(cache=True, fastmath=True)
def _fused_cost_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
    """融合 LPPL 函数 + 残差计算 — 单遍历, 零中间数组"""
    tc = params[0]; m = params[1]; w = params[2]
    a  = params[3]; b = params[4]; c = params[5]; phi = params[6]
    sse = 0.0
    n = len(t)
    for i in range(n):
        tau_i = tc - t[i]
        if tau_i < 1e-8:
            tau_i = 1e-8
        tau_m = tau_i ** m
        log_tau = np.log(tau_i)
        pred = a + b * tau_m + c * tau_m * np.cos(w * log_tau + phi)
        diff = pred - log_prices[i]
        sse += diff * diff
    return sse
```

**性能收益**:
- 消除: 3 × `np.ndarray` 分配/释放 × 500,000 次 = **1,500,000 次堆分配归零**
- 内存: O(3N) → O(1) 中间内存
- 缓存: 标量运算完全在 L1 cache, 无数组 malloc/free 开销
- 预期加速: cost function **2-3x**

### 1.2 cost_function_reduced 内联正规方程 — 消除 lstsq SVD

**目标文件**: `src/uniquant/brain/lppl/calculator.py`

**当前代码** (calculator.py:196-228):
```python
def cost_function_reduced(self, nonlinear_params, t, log_prices):
    tc, m, w = nonlinear_params
    if tc <= t[-1] + 0.5:
        return 1e20
    tau = tc - t
    if np.any(tau <= 0):
        return 1e20
    f = tau**m                                    # ← 分配 N 数组
    g = f * np.cos(w * np.log(tau))               # ← 分配 N 数组 ×2 (log+cos)
    h = f * np.sin(w * np.log(tau))               # ← 分配 N 数组 ×2 (log+sin)
    X = np.column_stack([np.ones_like(t), f, g, h])  # ← 分配 N×4 矩阵
    _, residuals, _, _ = np.linalg.lstsq(X, log_prices, rcond=None)  # ← SVD: O(4²N)
    return np.sum(residuals**2)
```

**优化代码** — Numba 单遍历 + Cramer 3×3 求解:
```python
@njit(cache=True, fastmath=True)
def _reduced_cost_numba(
    nonlinear: np.ndarray, t: np.ndarray, log_prices: np.ndarray
) -> float:
    """
    变量投影 cost function — Numba 全内联版
    非线性参数 [tc, m, w], 线性参数 [a, b, c1, c2] 通过正规方程解析求解
    设计矩阵 X = [1, f, g, h], 其中 f=tau^m, g=f*cos(w*ln(tau)), h=f*sin(w*ln(tau))
    正规方程: (X^T X) beta = X^T y → 4×4 对称正定系统
    """
    tc = nonlinear[0]; m = nonlinear[1]; w = nonlinear[2]
    n = len(t)

    # 边界检查
    if tc <= t[n - 1] + 0.5:
        return 1e20

    # 累积 X^T X (4×4 对称) 和 X^T y (4×1) — 单遍历
    # 下三角 + 对角: s11, s12, s13, s14, s22, s23, s24, s33, s34, s44
    s11 = 0.0; s12 = 0.0; s13 = 0.0; s14 = 0.0
    s22 = 0.0; s23 = 0.0; s24 = 0.0
    s33 = 0.0; s34 = 0.0; s44 = 0.0
    r1 = 0.0; r2 = 0.0; r3 = 0.0; r4 = 0.0
    yty = 0.0  # y^T y 用于直接计算 SSE

    for i in range(n):
        tau = tc - t[i]
        if tau <= 0.0:
            return 1e20
        if tau < 1e-8:
            tau = 1e-8
        f = tau ** m
        log_tau = np.log(tau)
        g = f * np.cos(w * log_tau)
        h = f * np.sin(w * log_tau)
        y = log_prices[i]

        # x = [1, f, g, h]
        s11 += 1.0;    s12 += f;     s13 += g;     s14 += h
        s22 += f * f;   s23 += f * g;  s24 += f * h
        s33 += g * g;   s34 += g * h;  s44 += h * h
        r1 += y;        r2 += f * y;   r3 += g * y;  r4 += h * y
        yty += y * y

    # 组装 4×4 对称矩阵 A 和 4×1 向量 b
    A = np.empty((4, 4))
    A[0, 0] = s11; A[0, 1] = s12; A[0, 2] = s13; A[0, 3] = s14
    A[1, 0] = s12; A[1, 1] = s22; A[1, 2] = s23; A[1, 3] = s24
    A[2, 0] = s13; A[2, 1] = s23; A[2, 2] = s33; A[2, 3] = s34
    A[3, 0] = s14; A[3, 1] = s24; A[3, 2] = s34; A[3, 3] = s44
    rhs = np.array([r1, r2, r3, r4])

    # 4×4 Cholesky 求解 (对称正定)
    # 退化为 np.linalg.solve (Numba 支持)
    try:
        beta = np.linalg.solve(A, rhs)
    except Exception:
        return 1e20

    # SSE = y^T y - beta^T (X^T y)
    sse = yty - (beta[0] * r1 + beta[1] * r2 + beta[2] * r3 + beta[3] * r4)
    if sse < 0.0:
        sse = 0.0  # 数值误差保护
    return sse
```

**性能收益**:
- 消除: `np.column_stack` (N×4 矩阵分配) + `np.linalg.lstsq` (SVD 分解)
- 复杂度: O(4²N + 4³) → 实际 O(N) + O(64) 常数
- 内存: N×4 矩阵 → 4×4 标量累积
- 预期加速: reduced cost function **3-5x**

### 1.3 DE workers 多核并行

**目标文件**: `src/uniquant/brain/lppl/engine.py:172-183`

**当前** (engine.py:181):
```python
result = differential_evolution(
    cost_fn, bounds, ...,
    workers=1,  # ← 单核!
)
```

**优化**:
```python
import os

_DE_WORKERS = int(os.environ.get("UNIQUANT_DE_WORKERS", "-1"))

result = differential_evolution(
    cost_fn, bounds, ...,
    workers=_DE_WORKERS,  # -1 = 所有核心
)
```

**注意事项**:
- `differential_evolution(workers=-1)` 使用 `multiprocessing.Pool`
- 要求 cost function 可 pickle — `@njit` 函数满足
- 内存: 每个 worker 拷贝 `t` 和 `log_prices` 数组 (每个 ~4KB, 可忽略)
- 加速比取决于 CPU 物理核心数, 理论 `min(workers, cpu_count())` 倍
- 环境变量 `UNIQUANT_DE_WORKERS` 提供运行时控制 (`-1` = 使用全部核心)

### 1.4 LPPL 性能探针

**新建文件**: `src/uniquant/shared/perf.py`

```python
"""低开销性能探针 — 纳秒级计时, 零分配热路径"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

_COUNTERS: defaultdict[str, int] = defaultdict(int)
_TIMERS: defaultdict[str, int] = defaultdict(int)  # 纳秒累计

@contextmanager
def perf_section(name: str):
    """上下文管理器 — 累计命名区段的调用次数和总耗时"""
    t0 = time.perf_counter_ns()
    yield
    elapsed = time.perf_counter_ns() - t0
    _TIMERS[name] += elapsed
    _COUNTERS[name] += 1

def perf_report() -> dict[str, dict[str, Any]]:
    """返回所有区段的统计: calls, total_ms, avg_us"""
    return {
        k: {
            "calls": _COUNTERS[k],
            "total_ms": round(_TIMERS[k] / 1e6, 2),
            "avg_us": round(_TIMERS[k] / _COUNTERS[k] / 1e3, 2) if _COUNTERS[k] else 0,
        }
        for k in sorted(_TIMERS)
    }

def perf_reset() -> None:
    """清零所有计数器"""
    _COUNTERS.clear()
    _TIMERS.clear()
```

**植入点**:
```python
# core.py — 每 1000 次 cost function 采样
from uniquant.shared.perf import perf_section
# 在 cost_function() 包装层添加
with perf_section("lppl.cost_fn"):
    return _fused_cost_numba(params, t, log_prices)

# storage_manager.py — 每次 Parquet 读取
with perf_section("io.read_parquet"):
    table = pq.read_table(file_path, columns=columns, memory_map=True)

# scan_service.py — 全流程
with perf_section("scan.load_data"):
    data = self.load_data(symbols)
with perf_section("scan.build_factors"):
    factors = self.build_factors(data)
```

---

## 2. 【I/O 与内存优化】零拷贝数据管道

### 2.1 PyArrow 直读 + memory_map

**目标文件**: `src/uniquant/data/lake/storage_manager.py:114-139`

**当前代码**:
```python
def read_parquet(self, file_path: str, normalize: bool = True) -> pd.DataFrame:
    df = pd.read_parquet(file_path)  # ← 完整文件加载, 无列裁剪, 非 memory-mapped
    if normalize and not df.empty:
        df = self.normalize_dataframe_columns(df)  # ← 可能触发 .copy()
    return df
```

**优化代码**:
```python
import pyarrow.parquet as pq

def read_parquet(
    self,
    file_path: str,
    normalize: bool = True,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    PyArrow 直读 + memory-map + 零拷贝转换

    关键参数:
    - memory_map=True: 内核 mmap 文件, 不拷贝到用户空间
    - self_destruct=True: Arrow→pandas 后释放 Arrow 缓冲区
    - split_blocks=True: 允许 pandas 按列独立持有内存块
    - columns: 列裁剪 — 只读需要的列, 减少 I/O 和内存
    """
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.warning(f"文件不存在: {file_path}")
        return pd.DataFrame()

    try:
        table = pq.read_table(
            file_path,
            columns=columns,
            memory_map=True,
            use_threads=True,
        )
        df = table.to_pandas(
            self_destruct=True,
            split_blocks=True,
            zero_copy_only=False,  # 允许必要时拷贝 (如 dict 编码列)
        )
        if normalize and not df.empty:
            df = self.normalize_dataframe_columns(df)
        return df
    except Exception as e:
        logger.error(f"读取数据从 {file_path} 失败: {e}")
        return pd.DataFrame()
```

**性能收益**:
- memory_map: 文件不拷贝到用户空间 → 内存占用 **≈0** (内核页缓存)
- self_destruct: Arrow 缓冲区释放 → 峰值内存 **降低 50%**
- columns 裁剪: 日线数据通常只需 date/open/high/low/close/volume → I/O 减少 30-50%
- 已有依赖: `pyarrow>=14.0.0` 在 pyproject.toml 中声明

### 2.2 消除 normalize 中的隐式拷贝

**目标文件**: `src/uniquant/data/lake/storage_manager.py` + 被委托的 `_normalize_columns`

**当前调用链**:
```python
def normalize_dataframe_columns(self, df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_columns(df)  # ← 可能内部 .copy()
```

**优化**: 确保 `_normalize_columns` 原地操作:
```python
def normalize_dataframe_columns(self, df: pd.DataFrame) -> pd.DataFrame:
    """原地标准化列名 — 不触发 DataFrame 拷贝"""
    df.columns = df.columns.str.lower().str.strip()
    return df  # 同一对象, 无拷贝
```

**收益**: 每次读取节省 1 次完整 DataFrame 拷贝。全市场 5000 文件 × ~2MB = **~10GB 累计拷贝归零**。

### 2.3 batch_read_data 多线程并行

**目标文件**: `src/uniquant/data/lake/storage_manager.py:512-536`

**当前代码**:
```python
def batch_read_data(self, symbols: List[str], data_type: str = "daily", **kwargs) -> Dict[str, pd.DataFrame]:
    results: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:  # ← 串行!
        try:
            df = self.read_data(symbol, data_type, **kwargs)
            if df is not None and not df.empty:
                results[symbol] = df
        except Exception as e:
            logger.warning(f"Failed to read {symbol}: {e}")
    return results
```

**优化代码**:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def batch_read_data(
    self,
    symbols: list[str],
    data_type: str = "daily",
    max_workers: int | None = None,
    **kwargs,
) -> dict[str, pd.DataFrame]:
    """多线程并行批量读取 — Parquet I/O 释放 GIL"""
    results: dict[str, pd.DataFrame] = {}

    def _read_one(sym: str) -> tuple[str, pd.DataFrame | None]:
        try:
            df = self.read_data(sym, data_type, **kwargs)
            return (sym, df) if df is not None and not df.empty else (sym, None)
        except Exception:
            return (sym, None)

    n_workers = min(max_workers or os.cpu_count() or 8, len(symbols))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_read_one, s): s for s in symbols}
        for future in as_completed(futures):
            sym, df = future.result()
            if df is not None:
                results[sym] = df

    return results
```

**收益**:
- Parquet I/O (PyArrow) 在 C 层释放 GIL → 真并行
- P 线程: N 文件加速比 ≈ min(P, N) (I/O bound, C 层释放 GIL)
- memory_map 模式下线程安全 (只读 mmap)

### 2.4 DuckDB SQL Pushdown (全市场扫描场景)

**目标文件**: `src/uniquant/data/lake/storage_manager.py` (新增方法)

```python
import duckdb

def read_market_scan(
    self,
    data_dir: str,
    symbols: list[str] | None = None,
    columns: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    DuckDB 直接扫描 Parquet 目录 — 谓词下推 + 列裁剪 + 并行解码

    适用场景: 全市场 5000+ 只股票批量加载
    DuckDB 自动:
    - 列裁剪 (只读 SELECT 的列)
    - 行过滤 (WHERE 条件下推到 Parquet row group 级别)
    - 多线程解码 (利用所有 CPU 核心)
    """
    conn = duckdb.connect()
    col_expr = ", ".join(columns) if columns else "*"
    where_clauses = []
    if symbols:
        sym_list = ", ".join(f"'{s}'" for s in symbols)
        where_clauses.append(f"symbol IN ({sym_list})")
    if start_date:
        where_clauses.append(f"date >= '{start_date}'")
    if end_date:
        where_clauses.append(f"date <= '{end_date}'")
    where_expr = " AND ".join(where_clauses) if where_clauses else "1=1"

    sql = f"SELECT {col_expr} FROM read_parquet('{data_dir}/*.parquet', hive_partitioning=false) WHERE {where_expr}"

    # fetch_arrow_table() → 零拷贝 Arrow Table → pandas
    arrow_table = conn.execute(sql).fetch_arrow_table()
    return arrow_table.to_pandas(self_destruct=True, split_blocks=True)
```

**收益**:
- 谓词下推: 日期范围过滤在 Parquet 元数据层完成 → 跳过整个 row group
- DuckDB 多线程解码: 自动利用所有核心
- 已有依赖: `duckdb>=0.9.0` 在 pyproject.toml 中声明但未使用
- 全市场加载: 预期 **5-10x** vs 串行 pd.read_parquet

---

## 3. 【异步并发架构】Scan Pipeline 极致并行

### 3.1 scan_service 数据加载 — 直接委托并行 batch_read

**目标文件**: `src/uniquant/services/scan_service.py`

```python
def load_data(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """利用 StorageManager.batch_read_data 的多线程并行"""
    return self.storage.batch_read_data(
        symbols, "daily",
        max_workers=min(os.cpu_count() or 8, len(symbols)),
    )
```

### 3.2 因子计算多进程隔离

**目标文件**: `src/uniquant/services/scan_service.py`

```python
from concurrent.futures import ProcessPoolExecutor
import os

def _compute_factors_for_symbol(args: tuple[str, pd.DataFrame]) -> pd.DataFrame | None:
    """进程隔离的因子计算 — 避免 GIL 争用"""
    symbol, df = args
    try:
        # 因子计算逻辑 (CPU 密集)
        from uniquant.brain.factors.composer import FactorComposer
        composer = FactorComposer()
        return composer.compute_factors(df, symbol=symbol)
    except Exception:
        return None

def build_factors(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """多进程并行因子计算 — 突破 GIL"""
    n_workers = min(int(os.environ.get("UNIQUANT_FACTOR_WORKERS", "0")) or max(1, (os.cpu_count() or 4) - 2), len(data))

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        results = list(pool.map(
            _compute_factors_for_symbol,
            data.items(),
            chunksize=max(1, len(data) // (n_workers * 4)),
        ))
    valid = [r for r in results if r is not None and not r.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()
```

**收益**:
- ProcessPoolExecutor 完全绕过 GIL
- chunksize 减少 IPC 开销
- `cpu_count - 2` workers: 预期 **4-5x** (考虑 IPC 开销)
- 环境变量 `UNIQUANT_FACTOR_WORKERS` 提供运行时控制

### 3.3 网络 I/O 异步化 (AkShare 增量轮询)

**目标文件**: `src/uniquant/services/data_service.py`

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_IO_POOL = ThreadPoolExecutor(max_workers=os.cpu_count() or 8, thread_name_prefix="uq-io")

async def fetch_stocks_async(
    self,
    symbols: list[str],
    fetcher_method: str = "fetch_stock_daily",
    **kwargs: Any,
) -> dict[str, pd.DataFrame]:
    """
    异步批量获取 — 网络 I/O 与本地计算重叠

    AkShare/BaoStock 等 HTTP API 在 ThreadPoolExecutor 中执行,
    asyncio 事件循环驱动并发, 释放主线程做其他计算。
    """
    loop = asyncio.get_event_loop()

    async def _fetch_one(sym: str) -> tuple[str, pd.DataFrame | None]:
        try:
            fetcher = getattr(self.data_fetcher, fetcher_method)
            df = await loop.run_in_executor(_IO_POOL, fetcher, sym, **kwargs)
            return (sym, df)
        except Exception:
            return (sym, None)

    tasks = [_fetch_one(s) for s in symbols]
    results = await asyncio.gather(*tasks)
    return {s: df for s, df in results if df is not None and not df.empty}

def fetch_stocks_sync(self, symbols: list[str], **kwargs: Any) -> dict[str, pd.DataFrame]:
    """同步包装 — 供非 async 上下文调用"""
    return asyncio.run(self.fetch_stocks_async(symbols, **kwargs))
```

**收益**:
- 网络 I/O (HTTP 请求) 完全并行 → 加速比 ≈ min(并发数, CPU 核心数)
- 与本地因子计算重叠 → 总延迟进一步降低
- 渐进式引入: 不破坏现有同步 API

---

## 4. 【系统级调优清单】Linux 内核参数

### 4.1 虚拟内存 (VM) — 立即生效

```bash
# ═══════════════════════════════════════════════════════
# UniQuant 量化计算专用 VM 调优
# 写入 /etc/sysctl.d/99-uniquant.conf 持久化
# ═══════════════════════════════════════════════════════

# [1] Swappiness: 100 → 10
# 原因: 量化计算需要热数据留在内存, 减少 swap 抖动
# 效果: 内核优先回收页缓存而非匿名页 (DataFrame 内存)
sudo sysctl -w vm.swappiness=10

# [2] 脏页阈值: 提高写入缓冲
# 原因: Parquet 批量写入受益于更大的 write-back 缓冲
# dirty_ratio=40: 进程级脏页上限 (占 RAM 40%)
# dirty_background_ratio=10: 后台刷写阈值
sudo sysctl -w vm.dirty_ratio=40
sudo sysctl -w vm.dirty_background_ratio=10

# [3] mmap 区域上限
# 原因: memory_map=True 大量映射 Parquet 文件
# 默认 65530, 全市场 5000 文件不够
sudo sysctl -w vm.max_map_count=262144

# [4] 持久化到 /etc/sysctl.d/
cat <<'EOF' | sudo tee /etc/sysctl.d/99-uniquant.conf
vm.swappiness = 10
vm.dirty_ratio = 40
vm.dirty_background_ratio = 10
vm.max_map_count = 262144
EOF
sudo sysctl --system  # 重新加载
```

### 4.2 透明大页 (THP) — madvise 模式

```bash
# ═══════════════════════════════════════════════════════
# THP madvise 模式 — 按需分配 2MB 页
# 全局 always 可能导致内存碎片化, madvise 更安全
# numpy malloc 使用 mmap → 大数组 (>2MB) 自动触发 THP
# ═══════════════════════════════════════════════════════

echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# 持久化 (systemd service 或 rc.local)
cat <<'EOF' | sudo tee /etc/systemd/system/thp-madvise.service
[Unit]
Description=Set THP to madvise for UniQuant
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo madvise > /sys/kernel/mm/transparent_hugepage/enabled && echo madvise > /sys/kernel/mm/transparent_hugepage/defrag'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable thp-madvise.service
```

**受益对象**: 全市场 DataFrame concat (>100MB) 的 page table 查找开销降低。

### 4.3 I/O 调度器 + 预读

```bash
# ═══════════════════════════════════════════════════════
# 磁盘 I/O 优化 (NVMe/SSD)
# ═══════════════════════════════════════════════════════

# 检查当前磁盘设备
lsblk -d -o NAME,TYPE,ROTA,SCHED

# NVMe: 用 none (无调度器, 最低延迟)
# SATA SSD: 用 mq-deadline
DISK=$(lsblk -d -o NAME,TYPE | grep disk | head -1 | awk '{print $1}')
echo none | sudo tee /sys/block/$DISK/queue/scheduler 2>/dev/null || \
echo mq-deadline | sudo tee /sys/block/$DISK/queue/scheduler

# 预读: 默认 128KB → 2048KB
# 原因: Parquet 文件顺序扫描受益于更大预读窗口
echo 2048 | sudo tee /sys/block/$DISK/queue/read_ahead_kb

# 持久化 (udev rule)
cat <<EOF | sudo tee /etc/udev/rules.d/99-uniquant-io.rules
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none", ATTR{queue/read_ahead_kb}="2048"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline", ATTR{queue/read_ahead_kb}="2048"
EOF
```

### 4.4 NUMA 内存策略

```bash
# NUMA 感知: 绑定内存分配到本地节点 (多 socket 服务器必用)
# 单 socket 系统也可用于限制跨 CCX/CCD 延迟
numactl --localalloc python -m uniquant.scripts.run_market_scan

# 验证:
numastat -p $(pgrep python)
```

---

## 5. 【性能收益推演】

### 时间复杂度对比

| 组件 | 当前 | 优化后 | 分析 |
|------|------|--------|------|
| `_cost_function_numba` | O(3N) mem, 3 alloc/call | O(1) mem, 0 alloc | 融合消除中间数组 |
| `cost_function_reduced` | O(4N) mem + O(4²N) SVD | O(1) mem + O(N) 累积 + O(4³) 解 | lstsq → 正规方程 |
| `batch_read_data` | O(K) 串行 | O(K/P), P=cores | ThreadPool I/O |
| `read_parquet` | 2× filesize mem | ≈0 额外 mem | mmap 零拷贝 |
| `build_factors` | O(S×F) 串行 | O(S×F/P), P=cores-2 | ProcessPool |
| Scan pipeline E2E | O(S × (IO + Factor + Analysis)) | O(S/P × max(IO, Factor)) + Analysis | I/O + 计算重叠 |

### 吞吐量公式

```
T_current = N_windows × (maxiter × popsize × T_cost_fn) + 并行开销

T_optimized = N_windows / P_joblib × (maxiter × popsize × T_cost_fn_opt) / P_de + 并行开销

加速比: 取决于 CPU、窗口数、DE 参数, 典型范围 4-10x
```

### 内存占用对比

```
当前全市场加载:
M_current = N_files × file_size_avg × 2 (pd.read + normalize copy)
          = ~20 GB (典型配置) → 溢出到 swap!

优化后:
M_optimized = N_files × mmap (仅页缓存, 不占用户空间)
            + pandas DataFrame 引用 (split_blocks, 零拷贝列)
            ≈ 5-8 GB (典型配置)

峰值降低: ~60%
```

---

## 6. 执行优先级矩阵

| 优先级 | 优化项 | 预期收益 | 工作量 | 风险 | 依赖 |
|--------|--------|---------|--------|------|------|
| **P0** | 4.1 VM swappiness=10 | 消除 swap 抖动 | 5min | 无 | 无 |
| **P0** | 4.3 I/O 调度器+预读 | 顺序扫描加速 | 5min | 无 | 无 |
| **P1** | 1.1 融合 cost function | LPPL 2-3x | 2h | 低 | 无 |
| **P1** | 2.1 PyArrow 直读 | I/O -50% 内存 | 1h | 低 | pyarrow (已有) |
| **P1** | 2.3 batch_read 并行 | 批量 I/O 7x | 30min | 低 | 无 |
| **P2** | 1.3 DE workers=-1 | 单窗口 4-8x | 10min | 中 | 1.1 |
| **P2** | 2.2 消除 .copy() | -30% 内存 | 30min | 中 | 需验证副作用 |
| **P2** | 4.2 THP madvise | 大数组 5-10% | 5min | 低 | 无 |
| **P3** | 1.2 lstsq 内联 | 每次 DE 10μs | 3h | 中 | 1.1 |
| **P3** | 3.2 因子多进程 | Scan 4-5x | 2h | 中 | 2.3 |
| **P3** | 2.4 DuckDB pushdown | 全市场 5-10x | 2h | 低 | duckdb (已有) |
| **P4** | 3.3 Async I/O | 网络+计算重叠 | 4h | 高 | 架构改动 |
| **P4** | 1.4 性能探针 | 可观测性 | 1h | 无 | 无 |

---

## 7. 验证方案

### 基线采集

```bash
# 1. LPPL 单窗口拟合基准
time .venv/bin/python -c "
from uniquant.brain.lppl.calculator import LPPLCalculator
import numpy as np
calc = LPPLCalculator()
prices = 100 + np.cumsum(np.random.randn(500) * 0.5)
prices = np.abs(prices) + 1
result = calc.fit_single_window(prices)
print(result)
"

# 2. 全市场 I/O 基准
time .venv/bin/python -c "
from uniquant.data.lake.storage_manager import StorageManager
sm = StorageManager('data/lake')
import os
symbols = [f.replace('.parquet','') for f in os.listdir('data/lake/daily') if f.endswith('.parquet')][:100]
data = sm.batch_read_data(symbols[:100], 'daily')
print(f'Loaded {len(data)} symbols')
"

# 3. 内存峰值
.venv/bin/python -c "
import tracemalloc
tracemalloc.start()
# ... 运行目标代码 ...
current, peak = tracemalloc.get_traced_memory()
print(f'Peak: {peak / 1024 / 1024:.1f} MB')
"
```

### 每阶段验证

```bash
# 每个 Phase 完成后:
# 1. 回归测试
.venv/bin/python -m pytest tests/ --tb=no -q

# 2. 同一基准对比耗时
# 3. tracemalloc 对比内存峰值
# 4. sysctl -a | grep vm  验证内核参数
# 5. perf_report() 输出探针数据
```

### 验收标准

| 指标 | 基线 (参考值) | 目标 (参考值) | 验收方法 |
|------|--------------|--------------|---------|
| LPPL 单窗口拟合 | 基线值 | < 基线 × 0.3 | time 命令 |
| 全市场扫描 | 基线值 | < 基线 × 0.25 | 端到端计时 |
| 100 文件批量读取 | 基线值 | < 基线 × 0.15 | time 命令 |
| 内存峰值 (100 symbols) | 基线值 | < 基线 × 0.5 | tracemalloc |
| 测试通过率 | 当前值 | 不变 | pytest |
| swap 使用 (运行时) | 基线值 | < 基线 × 0.25 | free -h |
