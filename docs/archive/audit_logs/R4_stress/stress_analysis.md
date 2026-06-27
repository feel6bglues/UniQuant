# R4 压力测试分析 — 全市场 5000 只股票场景

> 分析时间: 2026-06-06 | 场景: 5000 stocks × 500 trading days

---

## 分析方法

逐文件审计指定代码段，估算单次调用耗时、全市场累积耗时、内存峰值，并评估 OOM 风险。

---

## 瓶颈 1: `data_fetcher.py` L160-164 — 串行遍历

**代码**:
```python
def fetch_stocks_daily(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    result = {}
    for symbol in symbols:
        result[symbol] = self.fetch_stock_daily(symbol, start_date, end_date)
    return result
```

**问题**: 纯 Python `for` 循环，逐只串行获取。每只股票经历完整链路: `get_price()` → `_get_price_cached()` → `ingestion.fetch_price()` → `pipeline.process()` → `to_datetime()` → 布尔掩码切片。

**单次调用耗时估算**:
| 路径 | 耗时 | 说明 |
|------|------|------|
| 缓存命中 | ~0.5ms | OrderedDict 查找 + DataFrame.copy() |
| 缓存未命中 (本地) | ~5-15ms | pipeline.process() 含清洗/验证/复权 |
| 缓存未命中 (网络 TDX) | ~50-200ms | 网络 I/O + 解析 |
| 缓存未命中 (AkShare) | ~100-500ms | HTTP 请求 + JSON 解析 |

**全市场累积耗时**:
| 场景 | 估算 |
|------|------|
| 纯缓存命中 (warm) | 5000 × 0.5ms = **2.5s** |
| 首次加载 (冷启动) | 5000 × 100ms = **500s (8.3 min)** |
| 含重试/超时 | 可达 **15-30 min** |

**内存**: `result` 字典一次性持有全部 5000 个 DataFrame:
- 每个 DataFrame: 500 rows × 10 cols × 8 bytes ≈ 40KB
- 总计: 5000 × 40KB = **~200MB** (可接受)

**OOM 风险**: **低**。DataFrame 结构紧凑，200MB 在正常范围内。但若每只股票拉取 2500 天 (10 年)，内存升至 ~1GB。

**核心问题**: 不是内存，是 **时间**。冷启动串行 5000 次网络 I/O 无法接受。

---

## 瓶颈 2: `wyckoff/engine.py` L519-527, L530-562, L598-632 — itertuples 循环

**代码片段 A** (L521-526): `recent_20.itertuples()` — 高位炸板遗迹检测
```python
for row in recent_20.itertuples():
    pct = (row.close - row.open) / row.open if row.open > 0 else 0
    if pct > 0.09 and row.high > row.close * 1.02:
        ...
        break
```

**代码片段 B** (L532-562): `for i in range(1, len(recent_20))` + `iloc[i-1]`, `iloc[i]` — 跳空缺口检测
```python
for i in range(1, len(recent_20)):
    prev_row = recent_20.iloc[i - 1]
    curr_row = recent_20.iloc[i]
    # dict-style column access: curr_row["low"], prev_row["high"]
```

**代码片段 C** (L600-630): `reversed(list(recent_20.itertuples()))` — Spring 检测
```python
for row in reversed(list(recent_20.itertuples())):
    if row.low < low_bound * SPRING_LOW_FACTOR:
        ...
        # 还有 rule1_relative_volume() 和 rule6_spring_validation() 调用
        break
```

**问题详解**:

| 片段 | 行数 | 每次迭代开销 | 特殊问题 |
|------|------|-------------|----------|
| A | ≤20 行 | ~2µs | itertuples 本身高效，但有 early break |
| B | 19 行 | ~5-8µs | `iloc` 每次触发 pandas 索引对齐 + Series 构造；`curr_row["low"]` 是 dict-like 访问 |
| C | ≤20 行 | ~3-5µs | `list()` 强制物化 + `reversed()` 额外开销；含 `df.index.get_loc()` (O(log n) 或 O(n)) |

**单次调用耗时 (3 个片段合计)**: ~0.1-0.3ms

**全市场累积**:
- 5000 stocks × 0.2ms = **~1s**
- 若每只股票有多次分析调用 (多时间段扫描): ×5-10 = **5-10s**

**OOM 风险**: **无**。仅处理最近 20 行切片，内存开销可忽略。

**瓶颈严重度**: **低**。itertuples 对小切片 (20 行) 开销有限。但片段 B 的 `iloc` 模式在大规模循环中仍是反模式 — 若 `recent_20` 扩大到数百行则会显著恶化。

**建议**: 片段 B 可用 `itertuples()` 或 numpy 切片替代 `iloc` 避免 Series 构造开销。

---

## 瓶颈 3: `lppl/engine.py` L580-605 — 双 itertuples 循环

**代码**:
```python
# 第一轮: is_danger
for row in df.itertuples():
    is_d = (
        config.m_bounds[0] < row.m < config.m_bounds[1]
        and config.w_bounds[0] < row.w < config.w_bounds[1]
        and row.days_to_crash < config.danger_days
        and row.r_squared > config.r2_threshold
    )
    is_danger_list.append(is_d)

# 第二轮: is_warning
for row in df.itertuples():
    phase = classify_top_phase(float(row.days_to_crash), float(row.r_squared), config)
    is_w = (
        config.m_bounds[0] < row.m < config.m_bounds[1]
        and config.w_bounds[0] < row.w < config.w_bounds[1]
        and phase in {"watch", "warning", "danger"}
    )
    is_warning_list.append(is_w)
```

**问题详解**:
- `df` 的行数取决于 LPPL 参数扫描窗口，通常 200-500 行
- 两次遍历，每行调用 `classify_top_phase()` (含 float 转换 + 函数调用)
- 每次 append 创建新的 Python bool 对象

**单次调用耗时估算**:
| df 行数 | 第一轮 (is_danger) | 第二轮 (is_warning, 含 classify_top_phase) | 合计 |
|---------|--------------------|---------------------------------------------|------|
| 100 行 | ~0.05ms | ~0.15ms | ~0.2ms |
| 300 行 | ~0.15ms | ~0.45ms | ~0.6ms |
| 500 行 | ~0.25ms | ~0.75ms | ~1.0ms |

**全市场累积**:
- 5000 stocks × 0.6ms (假设平均 300 行) = **~3s**
- 若含多窗口扫描 (window_range × scan_step): ×10-50 = **30-150s**

**OOM 风险**: **低**。每只股票处理后即释放，中间列表短暂存活。

**瓶颈严重度**: **中**。单次不高，但 LPPL 的 `analyze_peak()` 内层循环可能对每个候选 peak 重复调用此函数。若每只有 5 个候选 peak，5000 × 5 × 0.6ms = 15s。

**建议**: 可用 pandas 向量化替代两个 itertuples 循环:
```python
df["is_danger"] = (
    (df["m"].between(config.m_bounds[0], config.m_bounds[1])) &
    (df["w"].between(config.w_bounds[0], config.w_bounds[1])) &
    (df["days_to_crash"] < config.danger_days) &
    (df["r_squared"] > config.r2_threshold)
)
```
向量化版本预计快 10-50x。

---

## 瓶颈 4: `czsc/czsc_engine.py` L305-325 — RawBar 对象创建

**代码**:
```python
bars = []
for i in valid_indices:
    try:
        bar = RawBar(
            symbol="STOCK",
            dt=dates[i],
            open=float(opens[i]),
            close=float(closes[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            vol=float(vols[i]),
            amount=float(amounts[i]),
            freq=Freq.D,
        )
        bars.append(bar)
    except CZSC_RECOVERABLE_ERRORS as e:
        ...
```

**问题详解**:
- `RawBar` 是 czsc 包的 dataclass (非 Python `@dataclass`，是 pydantic 或自定义)，字段含 `id`, `symbol`, `dt`, `open`, `close`, `high`, `low`, `vol`, `amount`, `freq`, `cache`, `solid`, `lower`, `upper` 等 ~14 个属性
- 每次创建触发 `__init__` + 可能的校验 + `float()` 转换 × 7
- `bars.append(bar)` 导致 list 动态扩容 (多次 realloc)

**单只股票耗时**:
| 指标 | 值 |
|------|-----|
| 有效行数 | ~490/500 (过滤 NaN/异常后) |
| 单个 RawBar 创建 | ~8-15µs (含 float 转换 + dataclass 初始化) |
| 单只股票总耗时 | 490 × 12µs ≈ **6ms** |

**全市场累积耗时**:
- 5000 × 6ms = **~30s**

**内存峰值估算**:

这是 **关键风险点**。需要区分两种场景:

**场景 A: 串行处理 (当前)** — 同一时刻只有一只股票的 RawBar 在内存
- 490 个 RawBar × ~800 bytes/个 ≈ **400KB** — 可忽略

**场景 B: 批量/并行处理** — 若未来改为并行或缓存所有结果
- 5000 × 490 = **2,450,000 个 RawBar 对象**
- 每个 RawBar: `sys.getsizeof` 约 200-400 bytes，但含 dict/属性引用后实际 **~800-1200 bytes**
- 总计: 2.45M × 1KB = **~2.4GB** (纯 RawBar 对象)
- 加上 bars list 的指针数组: 2.45M × 8 bytes = ~20MB
- 加上已存在的 5000 个 DataFrame: ~200MB
- **合计可达 ~2.6GB**

**OOM 风险**:
| 场景 | 风险 |
|------|------|
| 串行处理 (当前) | **低** — 每只处理完释放 |
| 缓存所有 bars 结果 | **高** — 2.4GB RawBar + 200MB DataFrame |
| 并行 4-8 workers | **中** — 峰值 2.4GB/4 = ~650MB per worker |

**瓶颈严重度**: **中-高**。RawBar 是 czsc 库的硬性需求，无法避免对象创建。瓶颈在于 CZSC 分析本身 (`CZSC(bars)`) 而非对象创建。但若结果被缓存到内存，OOM 风险真实存在。

---

## 瓶颈 5: `hands/backtest/engine.py` L122-147 — T+1 检查 O(n²)

**代码**:
```python
def _check_t1_constraint(self, buy_date: datetime, current_date: datetime) -> bool:
    if buy_date is None:
        return True
    
    if not self.trade_calendar.is_trading_day(current_date):
        return False
    
    trading_days = self.trade_calendar.get_trade_calendar(
        start_date=buy_date.strftime("%Y-%m-%d"),
        end_date=current_date.strftime("%Y-%m-%d")
    )
    
    if trading_days.empty:
        return False
    
    trade_dates = trading_days['trade_date'].values
    buy_idx = np.where(trade_dates == pd.Timestamp(buy_date))[0]
    current_idx = np.where(trade_dates == pd.Timestamp(current_date))[0]
    
    if len(buy_idx) == 0 or len(current_idx) == 0:
        return False
    
    return bool(current_idx[0] - buy_idx[0] >= 1)
```

**问题详解** — **这是最严重的瓶颈**:

1. **`get_trade_calendar()` 每次重新生成**: 内部对 `start_date` 到 `end_date` 的每个年份调用 `generate_trade_calendar()` (含列表操作 + `pd.concat` + 布尔掩码过滤 + sort + reset_index)，创建完整 DataFrame
2. **`pd.Timestamp(buy_date)` 每次重新构造**: 即使 buy_date 不变
3. **`np.where(trade_dates == ...)` 线性扫描**: 对整个 trade_dates 数组做全量比较
4. **两次 `np.where`**: O(n) × 2

**调用频率分析**:
- `execute_sell()` 在回测循环中每个 bar 都可能触发
- 对每只持仓股票，如果策略在每天检查卖出条件，则 T+1 检查频率 = 持仓天数
- 粗略估计: 5000 stocks × 500 bars × 0.2 (平均 20% 时间有持仓) = **500,000 次调用**

**单次调用耗时估算**:
| 步骤 | 耗时 | 说明 |
|------|------|------|
| `is_trading_day()` | ~0.01ms | 内存集合查找 |
| `get_trade_calendar()` | ~0.3-0.8ms | 生成日历 DataFrame (每年 ~150 条) |
| `pd.Timestamp()` 构造 | ~0.005ms | ×2 |
| `np.where` ×2 | ~0.01ms | 对 ~250 元素数组做比较 |
| **单次合计** | **~0.4-0.9ms** | |

**全市场累积耗时**:
```
500,000 calls × 0.6ms (平均) = 300s = 5 min
```

若策略更积极 (每天全仓检查卖出):
```
5000 × 500 × 0.6ms = 1,500s = 25 min
```

**OOM 风险**: **低但有 GC 压力**。每次调用创建临时 DataFrame (~250 行 × 1 col) + numpy 数组，50 万次调用产生大量临时对象，触发频繁 GC，导致 STW (Stop-The-World) 暂停。

**瓶颈严重度**: **高 (I) — 这是全系统最严重的性能瓶颈**。

**根因**: 这个问题的严重度远超表面。它有三个维度的问题:

1. **重复计算**: T+1 判断只需要 `current_date - buy_date >= 2 calendar days`，完全不需要生成完整交易日历。实际只需要判断两个日期之间是否有至少 1 个交易日。
2. **对象分配风暴**: 每次调用创建 DataFrame + numpy 数组 + Timestamp 对象 + Series，50 万次调用导致百万级临时对象。
3. **逻辑复杂度**: 实际 O(1) 的问题被实现为 O(n)。

---

## 全市场累积耗时汇总

| # | 瓶颈 | 单次耗时 | 全市场累积 (5000×500) | 严重度 |
|---|------|---------|----------------------|--------|
| 1 | data_fetcher 串行遍历 | 100ms (冷) | **8.3 min** (冷启动) | **高 (I/O)** |
| 2 | wyckoff itertuples | 0.2ms | **1-10s** | **低** |
| 3 | lppl itertuples | 0.6ms | **3-150s** | **中** |
| 4 | czsc RawBar 创建 | 6ms | **30s** | **中** |
| 5 | backtest T+1 O(n²) | 0.6ms | **5-25 min** | **高 (CPU)** |

**端到端总耗时估算** (串行):
- 冷启动数据加载: ~8 min
- brain 层分析 (wyckoff + lppl + czsc): ~2-5 min
- 回测 (含 T+1): ~5-25 min
- **总计: ~15-40 min**

---

## 内存峰值估算

| 组件 | 内存 | 说明 |
|------|------|------|
| 5000 个 DataFrame (数据) | 200MB - 1GB | 取决于天数 (500 vs 2500 天) |
| data_fetcher result dict | 200MB | 全量持有 |
| brain 分析中间结果 | 50-200MB | 单只处理后释放 |
| czsc RawBar (串行) | <1MB | 同一时刻仅一只 |
| czsc RawBar (若缓存) | **2.4GB** | 5000 × 490 个对象 |
| backtest 临时 DataFrame | <10MB | 短生命周期，但频繁创建 |
| backtest TradeRecord 列表 | 10-50MB | 取决于交易次数 |
| **串行场景峰值** | **~500MB-1.5GB** | 可接受 |
| **缓存 RawBar 场景峰值** | **~3-4GB** | 接近 OOM 临界 |

---

## OOM 风险评估

| 风险场景 | 概率 | 影响 | 说明 |
|----------|------|------|------|
| 串行处理 (当前架构) | **低** | 低 | 每只股票处理完释放，峰值可控 |
| RawBar 结果全部缓存 | **高** | **致命** | 2.4GB RawBar + DataFrame → OOM |
| 并行 4 workers + 缓存 | **中** | 致命 | 每 worker ~800MB，总 ~3.2GB |
| 长周期数据 (10 年) | **中** | 中 | DataFrame 内存 ×5，单只 ~200KB → 总 ~1GB |
| LPPL 多窗口扫描 | **低** | 低 | 中间列表短暂存活 |

**结论**: 当前串行架构下 OOM 风险低。但有两个 **潜在 OOM 触发器**:
1. 若将 RawBar 结果缓存在内存中 (如为重分析或 UI 展示)
2. 若改为并行处理且未做内存预算控制

---

## 修复优先级建议

### P0 (立即修复 — 阻塞生产可用性)

**瓶颈 5: T+1 检查重写**
```python
# 当前 O(n²) 方案 — 每次生成完整日历
def _check_t1_constraint(self, buy_date, current_date):
    trading_days = self.trade_calendar.get_trade_calendar(...)
    # ... O(n) 日历生成 + 2× O(n) np.where

# 修复: O(1) 方案 — 利用已有交易日历
def _check_t1_constraint(self, buy_date, current_date):
    """T+1 检查 — O(1) 方案"""
    if buy_date is None:
        return True
    # 方案 A: 如果已有全量交易日历 (应在初始化时预加载)
    buy_idx = self._trading_day_index[buy_date]
    curr_idx = self._trading_day_index[current_date]
    return curr_idx - buy_idx >= 1

    # 方案 B: 最小化日历生成 (至少避免重复 concat)
    # 将全量日历缓存在 self._full_calendar 中
```

预估修复后: 0.6ms → **<0.01ms**，全市场从 25 min 降至 **<5s**。

### P1 (短期修复 — 提升可接受性)

**瓶颈 1: 数据获取并发化**
```python
# 方案: ThreadPoolExecutor (I/O bound)
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_stocks_daily(self, symbols, start_date, end_date):
    result = {}
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {
            executor.submit(self.fetch_stock_daily, s, start_date, end_date): s
            for s in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            result[symbol] = future.result()
    return result
```

预估修复后: 8.3 min → **~1-2 min** (受 TDX 连接池限制)。

### P2 (中期优化 — 代码质量)

**瓶颈 3: LPPL itertuples → 向量化**
```python
# 替换两个 for 循环为 pandas 向量化操作
df["is_danger"] = (
    df["m"].between(config.m_bounds[0], config.m_bounds[1]) &
    df["w"].between(config.w_bounds[0], config.w_bounds[1]) &
    (df["days_to_crash"] < config.danger_days) &
    (df["r_squared"] > config.r2_threshold)
)
```

**瓶颈 2: wyckoff iloc → itertuples**
片段 B 中的 `recent_20.iloc[i-1]` 和 `recent_20.iloc[i]` 可改为:
```python
prev_rows = recent_20.itertuples()
next(prev_rows)  # skip first
for prev_row, curr_row in zip(prev_rows, recent_20.itertuples()):
    ...
```
当前影响小 (仅 19 行)，但属于技术债。

### P3 (长期架构)

**瓶颈 4: czsc RawBar 内存控制**
- 不要缓存 RawBar 对象。处理完即释放。
- 若需要持久化分析结果，序列化为紧凑格式 (如 parquet) 而非保留 RawBar 对象。
- 考虑 lazy evaluation: 仅在 CZSC 分析时按需创建 RawBar。

---

## 架构级建议

### 内存预算控制

```python
# 在 ServiceContainer 或上层编排器中加入内存门控
MAX_MEMORY_MB = 4096  # 4GB 预算

def analyze_all_stocks(self, symbols, ...):
    """分批处理，每批 N 只股票"""
    BATCH_SIZE = 200  # 每批 200 只
    for batch in chunked(symbols, BATCH_SIZE):
        results = {}
        for symbol in batch:
            results[symbol] = self.analyze_one(symbol, ...)
        yield results  # 让调用方消费后释放
        gc.collect()   # 强制 GC
```

### 交易日历预加载

```python
# 在回测引擎初始化时预加载全量交易日历
class BacktestEngine:
    def __init__(self, ...):
        # 一次性加载，O(1) 查询
        self._full_calendar = self.trade_calendar.get_trade_calendar(
            start_date=backtest_start, end_date=backtest_end
        )
        self._calendar_set = set(self._full_calendar['trade_date'].values)
        self._calendar_index = {
            d: i for i, d in enumerate(self._full_calendar['trade_date'].values)
        }
```

---

## 总结

| 维度 | 评估 |
|------|------|
| **最严重 CPU 瓶颈** | #5 T+1 检查: 25 min, O(n²), 100% 可消除 |
| **最严重 I/O 瓶颈** | #1 串行数据获取: 8 min, 可并发降至 1-2 min |
| **最大 OOM 风险** | #4 RawBar 缓存: 2.4GB (当前串行安全，缓存危险) |
| **当前串行架构总耗时** | 15-40 min (可接受但不理想) |
| **修复后预期总耗时** | 3-8 min (P0+P1 修复后) |
| **OOM 风险 (串行)** | **低** (~500MB-1.5GB) |
| **OOM 风险 (缓存)** | **高** (~3-4GB) |

**核心结论**: 全市场 5000 只股票场景下，当前串行架构不存在 OOM 风险 (峰值 ~1.5GB)，但 T+1 检查和串行数据获取是严重的性能瓶颈 (合计 30+ 分钟)。修复 P0 (T+1 重写) 和 P1 (数据并发) 后可将端到端耗时降至 3-8 分钟。需特别注意避免在内存中缓存 RawBar 对象，否则 OOM 概率显著上升。
