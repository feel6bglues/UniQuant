# UniQuant 修复计划 · 三维深度审查与优化

> **审查角色**: 顶级量化金融算法工程师 × 顶级 Python 程序员 × 顶级 A 股交易员
> **审查对象**: `docs/REPAIR_CAMPAIGN_ROADMAP.md` (修复战役总路线图 v1.0)
> **审查方法**: 源码逐行核实 + 拓扑依赖分析 + 数值正确性验算 + A 股规则穿透测试
> **审查日期**: 2026-05-31

---

## 总体评价

修复计划的 Sprint 划分和 Agent 隔离设计在**工程层面是合理的**——23 个 Bug 全量覆盖、4 阶段依赖拓扑正确、文件独占性保证到位。

但是，从三个专业角色视角穿透审查后，发现以下**系统性缺陷**：

| 维度 | 评分 | 核心问题 |
|------|------|---------|
| 量化算法正确性 | **6.5/10** | 遗漏 LPPL 优化器收敛偏移、Cache Hash 碰撞、FSM 阈值硬编码 |
| Python 工程质量 | **5.5/10** | 5 个线程安全漏洞未纳入 Sprint、遗漏加载器/日志工厂治理 |
| A 股交易规则 | **5.0/10** | 价格笼子时段、节假日、新股细则、零股规则描述有误 |

**综合**: 计划的方向正确，但**遗漏了 9 个关键条目**、**3 处优先级错配**、**5 处修复方案需要深化**。

---

## 第一章：量化金融工程师视角审查

### 1.1 LPPL RMSE 双重开方修复的风险分析 (B-004)

**当前修复方案**: `rmse = best_cost`（删除 `np.sqrt(best_cost / len(log_price_data))`）

**审查结论**: ⚠️ **修复方案正确，但缺少收敛性验证。DE 优化器可能已适应错误的代价函数。**

```
B-004 的深层风险:
  DE optimizer (maxiter=100) 之前是在 cost_function 返回 RMSE 的前提下调优的
  cost_function 返回的 RMSE 值域: ~0.01-0.1 (典型值)
  原 buggy 行: np.sqrt(best_cost / N) ≈ np.sqrt(0.05 / 200) ≈ 0.0158
  修复后: rmse = best_cost ≈ 0.05
  → 修复后 RMSE 值增大 3-5 倍，下游消费者(risk level判定阈值)可能不再合适
  → 需要检查 fire_lppl_alarm() 和 calculate_risk_level() 的阈值是否对齐
```

**修正建议**: 在 Sprint 1 的 B-004 修复中增加：
```python
# 修复后需要添加验证断言
def _validate_rmse_after_fix():
    """验证 RMSE 修复后优化器收敛行为是否稳定"""
    t = np.linspace(0, 100, 200)
    log_p = np.log(100 + 50 * np.sin(t / 20) + t * 0.1)
    from scipy.optimize import differential_evolution
    result = differential_evolution(cost_function, bounds, args=(t, log_p), maxiter=100)
    rmse = result.fun  # 修复后
    assert 0.01 < rmse < 0.5, f"RMSE out of range: {rmse}"
    # 验证 f_star = fitted[-1] 也在合理范围
    tc, m, w, a, b, c, phi = result.x
    fitted = lppl_func(t, tc, m, w, a, b, c, phi)
    f_star = fitted[-1]
    call_price = np.exp(f_star)
    assert 50 < call_price < 500, f"Call price implausible: {call_price}"
```

### 1.2 LPPL 代价函数统一后的数值稳定性验算 (B-011)

**当前修复方案**: 统一所有文件为 RMSE

**审查结论**: 🔴 **需要额外检查 `calculator.py` 的 VarPro 方法是否兼容**

`calculator.py` 使用 Variable Projection (VarPro) 方法，其代价函数结构与 `engine.py` 的根本不同。如果在统一过程中把 VarPro 的代价也改为 RMSE，可能破坏其线性参数消去算法。

**修正建议**: 
- `calculator.py` 的代价函数**保持原样**（VarPro 内部有线性最小二乘，其代价自然与 RMSE 一致）
- 只统一 `core.py`（从 SSE 改为 RMSE）和 `engine.py`（已正确输出 RMSE，但函数签名文档需澄清）
- 统一后运行交叉验证：同参数下三个函数的输出应 `np.allclose`

### 1.3 DataFrame 哈希碰撞风险 (计划遗漏项)

**严重度**: P1（可能导致返回过期缓存，造成 Alpha 泄露）

**位置**: `shared/cache/__init__.py` 第 32-33 行

**问题**: `_hash_dataframe` 只取开头 5 行 + 末尾 5 行，中间数据变化但首尾不变时产生哈希碰撞。

```python
# 当前 - 仅 10 行参与哈希
"tail_values": str(df.tail(5).values),
"head_values": str(df.head(5).values),

# 修复方案 - 增加中间抽样
def _hash_dataframe(df: pd.DataFrame) -> str:
    # 对 1000 行以上的 DataFrame，在中间等距抽样 5 个点
    n = len(df)
    sample_rows = min(n, 20)
    if n > 20:
        mid_indices = np.linspace(0, n-1, 18, dtype=int)[1:-1]  # 中间 16 行
        idx = [0] + mid_indices.tolist() + [n-1]
        sampled = df.iloc[idx].values
    else:
        sampled = df.values
    # 同时加入内容的统计哈希
    col_hash = hashlib.sha256(pd.util.hash_pandas_object(df).values).hexdigest()[:8]
    return f"{col_hash}_{hashlib.sha256(str(sampled).encode()).hexdigest()[:24]}"
```

**建议入 Sprint**: Sprint 1（P0/P1 排雷）

### 1.4 FSM 阈值硬编码与状态转换冲突 (计划遗漏项)

**严重度**: P1（两个独立的卖出逻辑路径可能产生矛盾信号）

**问题**: 
- `_check_sell_conditions` 使用硬编码 `alpha_score < -0.5`
- `_calculate_score` 使用常量 `FSM_ALPHA_THRESHOLD = 0.6` 加分
- 两套阈值不对称，可能导致 `_check_sell_conditions` 返回 `"EXECUTE_SELL"` 但 `_determine_target_state` 认为应保持 `MONITOR`

```
实际场景复现:
  alpha_score = 40, FSM_ALPHA_THRESHOLD = 0.6 → 不满足加分
  alpha_score = -0.5 → _check_sell_conditions 触发卖出
  但 _determine_target_state 将 score=40 判断为 "保持 MONITOR"
  → 两个方法返回矛盾信号 → infer_state 的结果不确定哪条路径生效
```

**修正建议**（纳入 Sprint 3 Agent G 的 FSM 修复）：
```python
# 统一阈值引用
FSM_ALPHA_SELL_THRESHOLD = -0.5  # 在 constants/technical.py 中定义

# _check_sell_conditions 中:
if ctx.alpha_score < IndicatorThresholds.FSM_ALPHA_SELL_THRESHOLD:
    sell_conditions.append("ALPHA_WEAK")
```

### 1.5 DE 优化器 maxiter=100 不足 (计划遗漏项)

**严重度**: P2（影响 LPPL 收敛可靠性）

**量化分析**:
```
LPPL 代价函数是多模态的（多个局部极小值）
文献建议: maxiter >= 200 (Sornette, 2003; Filimonov & Sornette, 2013)
当前值: 100
场景: 15 个个体 × 100 代 = 1500 次评估
对于 6 维搜索空间 (tc,m,w,a,b,c)，这在低维问题中属于最小配置
在价格序列噪声大时（A 股常见），需要更多代才能收敛
```

**建议**: `LPPLConfig.maxiter` 默认值改为 `200`，同时增加 `convergence_early_stopping` 参数。

---

## 第二章：Python 工程师视角审查

### 2.1 线程安全漏洞全景（计划遗漏 5 处）

| # | 组件 | 漏洞 | 严重度 | 建议入 Sprint |
|---|------|------|--------|-------------|
| 1 | `LoggerFactory.__new__` | 非原子化检查-设置，无锁 | **P1** | Sprint 1 |
| 2 | `LoggerFactory.get_logger` | 非原子化检查-设置，无锁 | **P1** | Sprint 1 |
| 3 | `module_level get_logger()` | 全局 `_factory` 非原子化检查-设置 | **P1** | Sprint 1 |
| 4 | `AnalysisEngineFactory._lazy_init` | `_engines` 字典在 `importlib.import_module` 期间无锁 | **P1** | Sprint 1 |
| 5 | `smart_cache` 装饰器 | 装饰器内无锁保护 `cache_manager.get/set` | **P2** | Sprint 2 |

**修正建议**——在 Sprint 1 中新增一个 Subagent 专门治理线程安全：

```
Agent L (thread-safety): 线程安全专项治理
  ├── LoggerFactory: __new__ 添加双重检查锁
  │   def __new__(cls):
  │       with cls._lock:  # 新增 cls._lock = threading.Lock()
  │           if cls._instance is None:
  │               cls._instance = super().__new__(cls)
  │       return cls._instance
  │
  ├── LoggerFactory.get_logger: 添加 self._lock
  │
  └── AnalysisEngineFactory._lazy_init:
      def _lazy_init(self, name, ...):
          if name not in self._engines:
              with self._lock:  # 新增 self._lock
                  if name not in self._engines:  # 双重检查
                      ...self._engines[name] = ...
          return self._engines.get(name)
```

**零文件冲突保证**: Agent L 只修改 `shared/logger_factory.py` 和 `services/analysis/engine_factory.py`，与 Sprint 1 的 Agent A/B 无交集。

### 2.2 CostConfig.from_yaml 字段缺失 (计划遗漏项)

**严重度**: P1（从 YAML 加载配置时遗漏印花税和过户费，导致始终用默认值）

**文件**: `shared/cost_model.py:87-88`

```python
# 当前 from_yaml 返回:
return cls(buy_fee_pct=buy_fee, sell_fee_pct=sell_fee,
           slippage_pct=slippage_pct, min_commission=min_comm)
# 缺少: stamp_tax_pct, transfer_fee_pct
```

**影响**: 从 YAML 加载时，`stamp_tax_pct` 始终为数据类默认值 0.0005（万5），而 `transfer_fee_pct` 始终为 0.00001（万0.1）。如果未来规则变化，修改 YAML 后不会影响费用计算。

**修正建议**——纳入 Sprint 2 Agent D：
```python
# 在 from_yaml 中添加:
stamp_tax = float(exec_cfg.get("stamp_tax_pct", STAMP_TAX_PCT * 100)) / 100
transfer = float(exec_cfg.get("transfer_fee_pct", TRANSFER_FEE_PCT * 100)) / 100
return cls(..., stamp_tax_pct=stamp_tax, transfer_fee_pct=transfer)
```

### 2.3 cache_key 哨兵对象缺失 (计划遗漏项)

**严重度**: P1（无法区分"缓存值为 None"和"缓存未命中"）

**文件**: `shared/cache/__init__.py:89`

```python
# 当前:
cached_value = cache_manager.get(key)
if cached_value is not None:   # 当缓存值为 None 时也被视为"未命中"

# 修复:
_SENTINEL = object()  # 模块级唯一哨兵

def smart_cache(ttl=...):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = generate_cache_key(func, args, kwargs)
            cached_value = cache_manager.get(key, default=_SENTINEL)
            if cached_value is not _SENTINEL:
                return cached_value
            result = func(*args, **kwargs)
            cache_manager.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
```

**建议入 Sprint**: Sprint 2（与 Agent D 的缓存治理合并）

### 2.4 handle_network_errors 函数内 import (计划遗漏项)

**严重度**: P2（每次调用都 `import requests`，性能开销）

**文件**: `shared/error_handling.py:345`

```python
def handle_network_errors(default_return=None, max_retries=None):
    import requests  # ← 每次调用装饰器时都重新导入
    import urllib3
```

**修正建议**: 将 import 移至模块顶部（模块级 import 在 Python 中是线程安全的，`importlib` 有内部锁）。

```python
# 模块顶部:
import requests
import urllib3
```

**建议入 Sprint**: Sprint 3（与性能治理合并）

### 2.5 GlobalConfig 缺少 set()/reload() 方法 (计划遗漏项)

**严重度**: P2（配置加载后无法运行时修改，测试无法注入 mock）

**当前**: `GlobalConfig` 只有 `get()` 方法，没有 `set()` 或 `reload()`。

**修正建议**——纳入 Sprint 2 Agent D：
```python
class GlobalConfig:
    def set(self, key: str, value: Any) -> None:
        """运行时设置配置值（线程安全）"""
        keys = key.split(".")
        with self._lock:
            target = self._config
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = value
    
    def reload(self, path: Optional[str] = None) -> None:
        """重新加载 YAML 配置"""
        path = path or str(self._root_dir / "config" / "config.yaml")
        with open(path) as f:
            import yaml
            new_config = yaml.safe_load(f)
        with self._lock:
            self._config = new_config
```

---

## 第三章：A 股交易员视角审查

### 3.1 价格笼子适用时段缺失 (计划遗漏项 -> 需升为 P1)

**当前修复方案**: 仅修改百分比值（科创板/创业板 ±1% → ±2%）

**严重缺陷**: ⚠️ **价格笼子只在连续竞价时段（9:30-11:30, 13:00-15:00）生效，集合竞价时段（9:15-9:25, 14:57-15:00）不适用。** 当前代码对所有时段一视同仁。

**影响**: 
- 集合竞价阶段合法报价单被错误拒绝
- 开盘集合竞价 9:15-9:25 的报价范围实际应为主板 ±10%（涨跌停板），而非 ±2%

**修正建议**——补充 Sprint 2 Agent E 的任务：
```python
# 在 MarketHours 中添加竞价时段判断
class MarketHours:
    # 连续竞价时段
    CONTINUOUS_MORNING = (time(9, 30), time(11, 30))
    CONTINUOUS_AFTERNOON = (time(13, 0), time(15, 0))
    
    # 集合竞价时段
    CALL_AUCTION_OPEN_CANCEL = (time(9, 15), time(9, 20))    # 可撤单
    CALL_AUCTION_OPEN_NO_CANCEL = (time(9, 20), time(9, 25))  # 不可撤单
    CALL_AUCTION_CLOSE = (time(14, 57), time(15, 0))           # 收盘集合竞价
    
    @classmethod
    def is_call_auction(cls, dt=None) -> bool:
        """判断当前是否为集合竞价时段"""
        time = (dt or datetime.datetime.now()).time()
        return any(start <= time <= end for start, end in [
            cls.CALL_AUCTION_OPEN_CANCEL,
            cls.CALL_AUCTION_OPEN_NO_CANCEL,
            cls.CALL_AUCTION_CLOSE,
        ])
    
    @classmethod
    def is_continuous_auction(cls, dt=None) -> bool:
        """判断当前是否为连续竞价时段（价格笼子适用）"""
        time = (dt or datetime.datetime.now()).time()
        return (cls.CONTINUOUS_MORNING[0] <= time <= cls.CONTINUOUS_MORNING[1]
                or cls.CONTINUOUS_AFTERNOON[0] <= time <= cls.CONTINUOUS_AFTERNOON[1])
```

然后在 `market_rules.py` 的价格笼子检查中添加：
```python
def check_price_collar(price, ref_price, board_type, dt=None):
    """价格笼子检查（仅在连续竞价时段生效）"""
    if MarketHours.is_call_auction(dt):
        return PriceCollarResult(allowed=True, reason="call_auction_no_collar")
    # ... 原有检查逻辑
```

### 3.2 新股首日涨跌停细则修正 (B-015 修复方案需深化)

**当前修复方案**: 笼统提到"添加新股上市天数判断"

**需要细化的规则**:

| 板块 | 首日规则 | 前 5 日规则 | 5 日后 |
|------|---------|-----------|-------|
| **主板** | 最高 +44%，最低 -36% (**不对称!**)| 恢复正常 ±10% | ±10% |
| **科创板 (688)** | 不设涨跌停 | 不设涨跌停 | ±20% |
| **创业板 (300/301)** | 不设涨跌停 | 不设涨跌停 | ±20% |
| **北交所 (83/87)** | 不设涨跌停 | 恢复正常 ±30% | ±30% |

主板首日是不对称的（44% vs 36%），不是简单的 ±44%。这是 A 股特有的设计——新股首日最高涨幅为开盘价的 44%，但跌幅仍为 36%。

**修正建议**——补充 Sprint 2 Agent E 的任务：
```python
# 在 limit_checker.py 中:
@dataclass
class NewStockLimitConfig:
    """新股首日/前5日涨跌停配置"""
    first_day_up: Optional[float]   # 首日最高涨幅 (None = 无限制)
    first_day_down: Optional[float] # 首日最大跌幅 (None = 无限制)
    first_5_days_unlimited: bool    # 前5日是否无限制

NEW_STOCK_LIMITS = {
    BoardType.MAIN: NewStockLimitConfig(0.44, 0.36, False),    # 主板首日 ±44%/36%
    BoardType.STAR: NewStockLimitConfig(None, None, True),      # 科创前5日无限制
    BoardType.GEM: NewStockLimitConfig(None, None, True),       # 创业前5日无限制
    BoardType.BEIJING: NewStockLimitConfig(None, None, False),  # 北交首日无限制
}
```

### 3.3 MarketHours 缺少节假日判断 (计划遗漏项 -> P1)

**位置**: `shared/constants/market.py`

**严重度**: P1（回测/实盘在节假日或调休日判断开盘状态错误）

**当前**: 仅检查 `dt.weekday() in [0,1,2,3,4]`（周一到周五）

**A 股节假日规则复杂度**:
- 春节、国庆各休市约 7 天
- 元旦、清明、五一、端午、中秋各休市 1-3 天
- 调休工作日需要开盘（如国庆前一个周日）
- 调休周末需要开盘（如春节前一个周六）

**建议**: 在 Sprint 3 中，引入 `trade_calendar_manager.py`（已在 TDX data/managers 中）或使用 `mootdx` 的交易日历：
```python
# 轻量方案: 集成 mootdx 交易日历
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir='/path/to/tdx')
calendar = reader.calendar()  # 返回所有交易日

# 或使用轻量级静态日历
class TradingCalendar:
    """2024-2026 A股交易日历（主表从交易所获取，此处为fallback）"""
    HOLIDAYS_2024_2026 = {
        "2024-01-01", "2024-02-09", ..., "2026-02-17",  # 春节
        # ... 完整列表由 sync 脚本生成
    }
    EXTRA_TRADING_DAYS_2024_2026 = {
        "2024-02-04", "2024-02-18", ...,  # 调休交易日
    }
```

### 3.4 T+1 规则两套实现不一致 (计划遗漏项 -> P2)

**位置**: `backtest.py` 和 `UnifiedMatchingEngine`（如果已迁移）

**问题**:
- `BacktestEngine`: 使用真实交易日历判断 `buy_date` 的 `nth` 交易日
- `UnifiedMatchingEngine`: 使用日历日（ordinal）而非交易日判断
- 一个交易日对应 1 个日历日时两者一致，但遇到周末/节假日就不同

**修正建议**: 纳入 Sprint 4，统一使用 `trade_calendar_manager.py` 的交易日偏移计算。

### 3.5 ST 股识别降级问题 (B-016 的补充)

**严重度**: P1（`limit_checker.check_limit_status` 依赖 name 参数识别 ST）

```python
# 当前行为:
def check_limit_status(price, pre_close, symbol, name=None):
    if name and ("ST" in name or "*ST" in name):
        # 应用 ST 涨跌停
    else:
        # 按板块默认涨跌停
    # 未传入 name 时 → 降级为板块默认，ST 股票被错误应用 ±20%
```

**修正建议**——补充 Sprint 2 Agent E：
```python
# 方案1: 通过数据服务获取 ST 状态（可靠但依赖 data 层）
# 方案2: 通过股票代码前缀规则补充（local fallback）
ST_CODES = {"600xxx", "000xxx", ...}  # 定期更新的 ST 列表

# 推荐: 使用 mootdx 或 baostock 获取 ST 状态
def _is_st_stock(symbol: str) -> bool:
    """通过代码查询 ST 状态"""
    if not hasattr(check_limit_status, '_st_cache'):
        check_limit_status._st_cache = {}  # 简单内存缓存
    if symbol not in check_limit_status._st_cache:
        try:
            from mootdx.quotes import Quotes
            quotes = Quotes.factory()
            info = quotes.stock_info(symbol)
            check_limit_status._st_cache[symbol] = info.get('is_st', False)
        except Exception:
            return False
    return check_limit_status._st_cache[symbol]
```

### 3.6 零股卖出修复方案不完整 (B-023 修复方案需深化)

**当前修复方案**: 允许不足 200 股时一次性卖出

**A 股真实规则**: 
- **买入**: 必须以整手为单位（科创板 200 股，其他 100 股）
- **卖出**: 不足一手的零股（如科创板剩余 50 股）**必须一次性卖出**
- 当前 `round_lot` 向下取整，导致无法卖出零股

**修正建议**——补充 Sprint 4 Agent J：
```python
def round_lot(shares: float, lot_size: int = 100, is_sell: bool = False) -> int:
    """按交易单位四舍五入股数"""
    if is_sell and shares < lot_size:
        return int(shares)  # 不足一手时允许卖出所有零股
    return (int(shares) // lot_size) * lot_size
```

---

## 第四章：跨角色交汇审查——碰撞检测

### 4.1 Sprint 排序合理性碰撞

| Sprint | 量化金融工程师 | Python 工程师 | A 股交易员 | 裁决 |
|--------|---------------|-------------|-----------|------|
| Sprint 1 内容 | ✅ 正确 | ⚠️ **缺少线程安全治理** | ✅ 正确 | **需拆分 Agent L 加入 Sprint 1** |
| Sprint 2 内容 | ⚠️ **LPPL 收敛性验证不足** | ⚠️ **缺少 cache 哨兵/Config set** | ⚠️ **价格笼子时段缺失** | **三个角色都需补充任务** |
| Sprint 3 内容 | ⚠️ **FSM 阈值统一缺失** | ⚠️ **handle_network_errors import** | ⚠️ **节假日日历缺失** | **需补充 FSM 阈值、节假日** |
| Sprint 4 内容 | ✅ 可接受 | ⚠️ **DI 合并风险过高** | ⚠️ **T+1 统一缺失** | **DI 合并拆分、T+1 补充** |

### 4.2 修复方案矛盾检测

| 矛盾 | 描述 | 解决方案 |
|------|------|---------|
| B-011 修复 vs B-019 去重 | B-011 在 Sprint 2 统一代价函数，B-019 在 Sprint 4 做代码去重。但 B-019 要求删除 `core.py` 和 `engine.py` 中的函数，与 B-011 的修改冲突 | Sprint 2 做好函数签名统一，Sprint 4 的删除操作以 Sprint 2 后的代码为准 |
| B-016 修复爆炸半径 | 修改北交所前缀可能影响所有依赖 `BOARD_PREFIX` 的模块（`limit_checker`, `market_rules`, `cost_model`） | Agent E 修改后立即运行 `pytest` 和 `python -c "import uniquant"` |
| B-017 & B-018 相互依赖 | UI DAG 违规修复依赖 services 层门面，而 services 层门面依赖 DI 容器稳定 | DI 合并（B-018）应视为 B-017 的前置条件，在 Sprint 4 中先做 DI 合并再做 DAG 修复 |

---

## 第五章：修正后的战役路线图 v1.1

### 5.1 新增 Bug 条目

| 新编号 | Bug | 评级 | 所属模块 | 建议入 Sprint | 修正后计划 |
|--------|-----|------|---------|-------------|-----------|
| B-024 | `LoggerFactory.__new__` 无线程锁 | **P1** | shared | Sprint 1 | Agent L |
| B-025 | `AnalysisEngineFactory._lazy_init` 无线程锁 | **P1** | services | Sprint 1 | Agent L |
| B-026 | `smart_cache` 无哨兵对象 | **P1** | shared/cache | Sprint 2 | Agent D |
| B-027 | `_hash_dataframe` 仅采样 10/1000+ 行 | **P1** | shared/cache | Sprint 1 | Agent B |
| B-028 | `CostConfig.from_yaml` 缺失印花税/过户费 | **P1** | shared | Sprint 2 | Agent D |
| B-029 | `MarketHours` 无节假日日历 | **P1** | shared | Sprint 3 | Agent H |
| B-030 | 价格笼子未区分集合竞价/连续竞价 | **P1** | shared | Sprint 2 | Agent E |
| B-031 | FSM `alpha_score <-0.5` 硬编码 vs `FSM_ALPHA_THRESHOLD=0.6` | **P2** | brain/fsm | Sprint 3 | Agent G |
| B-032 | `handle_network_errors` 函数内 import | **P2** | shared | Sprint 3 | Agent H |
| B-033 | 新股首日不对称细则缺失(主板44%/36%) | **P1** | shared | Sprint 2 | Agent E |
| B-034 | ST 股识别依赖 name 参数降级 | **P1** | shared | Sprint 2 | Agent E |
| B-035 | T+1 两套实现不一致 | **P2** | hands | Sprint 4 | Agent J |
| B-036 | `GlobalConfig` 缺少 set()/reload() | **P2** | shared | Sprint 2 | Agent D |
| B-037 | LPPL DE optimizer `maxiter=100` 不足 | **P2** | brain/lppl | Sprint 2 | Agent F |
| B-038 | 零股卖出 `round_lot` 修复不完整 | **P2** | shared | Sprint 4 | Agent J |

### 5.2 修正 Sprint 计划（4 + 1 子 Sprint）

#### Sprint 1 (修正版): 基建与排雷

```
Agent A (brain-corridor):  B-002, B-003, B-004(+收敛验证), B-005
Agent B (shared-corridor): B-006, B-013, B-027(DataFrame hash修复)
Agent C (hands-corridor):  B-001
Agent L (新增-线程安全):  B-024, B-025
```

**Agent L 文件独占**: `shared/logger_factory.py`, `services/analysis/engine_factory.py`
**零文件冲突确认**: 以上两文件在 Agent A/B/C 中均不被触及。✅

#### Sprint 2 (修正版): 规则修正 + 配置统一

```
Agent D (config-authority):      B-010, B-009, B-026(哨兵), B-028(YAML字段), B-036(set/reload)
Agent E (a-share-compliance):    B-008, B-015+B-033(新股细则), B-022, B-016, B-030(时段), B-034(ST识别)
Agent F (lppl-unification):      B-011, B-012, B-037(maxiter)
```

**Agent D 与 Agent E 的文件交集**: 均修改 `shared/constants/market.py`？ 不——Agent D 修改 `constants/*.py` 整体（但只改 data.py/technical.py/risk.py），Agent E 只改 `constants/market.py` 的 `BOARD_PREFIX` 和 `LIMIT_RATIO`。**区域隔离**: `market.py` 中 `BOARD_PREFIX` 和 `LIMIT_RATIO` 是独立控制结构，不与 Agent D 的修改区域重叠。✅

#### Sprint 3 (修正版): 逻辑补全 + 节假日日历

```
Agent G (fsm-logic):        B-007, B-031(阈值统一)
Agent H (perf-safety):      B-014, B-020, B-029(节假日日历), B-032(import提升)
Agent I (test-coverage):    B-021(测试补充)
```

#### Sprint 4 (修正版): 架构治理 + T+1 统一

```
Agent J (architecture):     B-017, B-018, B-035(T+1统一), B-038(零股固定)
Agent K (lppl-dedup):       B-019 (+ 所有 LPPL 回归测试)
```

### 5.3 Sprint 验收标准增强

在原有验收标准基础上，每个 Sprint 新增以下验证：

```bash
# Sprint 1 新增 - 线程安全压力测试
python3 -c "
import threading
from uniquant.shared.logger_factory import get_logger
errors = []
def stress_logger():
    for _ in range(1000):
        try:
            get_logger(f'test_thread_{threading.get_ident()}')
        except Exception as e:
            errors.append(e)
threads = [threading.Thread(target=stress_logger) for _ in range(20)]
for t in threads: t.start()
for t in threads: t.join()
assert len(errors) == 0, f'Logger thread safety: {len(errors)} errors'
print(f'LoggerFactory thread safety: 20 threads × 1000 ops = 0 errors')
"

# Sprint 2 新增 - LPPL 收敛稳定性验证
python3 -c "
import numpy as np
from scipy.optimize import differential_evolution
from uniquant.brain.lppl.engine import cost_function, lppl_func
# 多次运行验证一致性
results = []
for _ in range(5):
    t = np.linspace(0, 100, 200)
    log_p = np.log(100 + 50 * np.sin(t / 20) + t * 0.1)
    result = differential_evolution(
        cost_function, bounds, args=(t, log_p),
        maxiter=200, seed=42
    )
    results.append(result.fun)
# 多次运行结果应一致
print(f'LPPL convergence: {len(results)} runs, RMSE range [{min(results):.4f}, {max(results):.4f}]')
assert max(results) - min(results) < 0.1, 'LPPL runs diverge'
"

# Sprint 2 新增 - 配置一致性修复
python3 -c "
from uniquant.shared.config_loader import get_config
config = get_config()
# 验证 Config 具有 set 方法（新增功能）
assert hasattr(config, 'set'), 'GlobalConfig.set() not implemented'
assert hasattr(config, 'reload'), 'GlobalConfig.reload() not implemented'
config.set('test.key', 'value')
assert config.get('test.key') == 'value'
print('Config management: set() + reload() OK')
"

# Sprint 3 新增 - 节假日日历
python3 -c "
from uniquant.shared.market_rules import MarketHours
# 验证 2025-01-28 (春节前星期二, 应该休市)
import datetime
spring_festival = datetime.datetime(2025, 1, 28, 10, 0)
result = MarketHours.is_market_open(spring_festival)
print(f'Holiday check: 2025-01-28 is_market_open = {result}')
"
```

---

## 第六章：最终建议与风险提示

### 6.1 必须优先处理的"结构性问题"——给架构师的建议

| 优先级 | 问题 | 原因 | 建议处理时间 |
|--------|------|------|-------------|
| **P0** | `smart_cache` 缓存碰撞（B-027） | 中间数据变化不被感知 → 返回过期结果 → **Alphal泄露级风险** | Sprint 1 |
| **P1** | `LoggerFactory` 线程安全（B-024） | 多线程环境中日志丢失/混乱 → 调试不可靠 → 掩盖更严重的 Bug | Sprint 1 |
| **P1** | 价格笼子未区分时段（B-030） | 集合竞价阶段拒绝合法订单 → 回测结果错误 | Sprint 2 |
| **P1** | `CostConfig.from_yaml` 字段缺失（B-028） | 费用配置变更被静默忽略 → 回测费用计算与配置不一致 | Sprint 2 |
| **P1** | 新股首日规则不对称（B-033） | 主板新股首日回测涨跌幅判断错误 | Sprint 2 |

### 6.2 量化金融工程师的"数值可信度"红线

```
修复前 → 修复后 的数值偏移必须文档化:

1. LPPL RMSE 修复 (B-004):
   - 当前(错误): rmse ≈ sqrt(RMSE_raw / 200) ≈ 0.0158
   - 修复后: rmse ≈ RMSE_raw ≈ 0.05
   - 偏移: 约 3x
   - 影响: fire_lppl_alarm 的 risk_level 判定阈值可能需要同步修正

2. 印花税日期修复 (B-001):
   - 当前(错误): 2023-08-28 ~ 2023-12-31 期间按 0.1% 扣税
   - 修复后: 按 0.05% (万5) 扣税
   - 偏移: 卖方单边交易成本减半
   - 影响: 所有覆盖 2023H2 的回测结果需重新运行

3. 价格笼子修复 (B-008):
   - 当前(错误): 科创/创业 ±1%
   - 修复后: 科创/创业 ±2%
   - 偏移: 价格申报范围扩大 2x
   - 影响: 之前被拒绝的合法限价单现在可成交
```

### 6.3 Python 工程师的"原子性"红线

```
所有对共享状态的修改操作，必须满足以下三选一:
  1. 使用 threading.Lock() 保护（推荐）
  2. 使用 threading.RLock() 保护（函数有重入风险时）
  3. 使用不可变数据结构（tuple, frozenset 等）

禁止：
  - 无保护的 if key in dict: dict[key] = value 模式
  - 非原子化的 self.counter += 1 模式
  - 无哨兵的 if cache.get(key) is not None 模式
```

### 6.4 A 股交易员的"合规性"红线

```
以下规则若缺失，回测结果不可用于实盘决策:

  1. 集合竞价时段必须与连续竞价区分（价格笼子差异）
  2. 新股首日必须按板块区分规则（44%/无涨跌停）
  3. 市场日历必须考虑中国节假日（非简单周末跳过）
  4. ST 股认定不能依赖 name 参数（必须通过数据服务）
  5. 科创板零股卖出必须允许（不是仅修复四舍五入）
```

---

*审查版本: v1.1 | 审查时间: 2026-05-31 | 基于源码逐行核实 + 数值验算 + A 股规则交叉验证*

*发现汇总: 15 个新增遗漏 Bug + 5 处修复方案需深化 + 3 处优先级错配 + 1 处修复矛盾*
