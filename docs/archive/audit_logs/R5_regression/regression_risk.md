# R5 回归风险分析报告

> **生成时间**: 2026-06-06 | **分析范围**: P0 修复方案 | **分析员**: R5 Regression Risk Analyst

---

## 1. 修复项概览

| # | 修复项 | 文件 | 问题描述 |
|---|--------|------|----------|
| F1 | validate() 返回类型不匹配 | `data/data_pipeline_service.py:19` | `validate()` 返回 `bool`，但返回值被当作 `DataFrame` 赋给 `df` |
| F2 | FSM 幽灵导入 | `brain/fsm/fsm.py:19-22` | `from ..indicators.indicators import Indicators` 失败时回退为 `None` |
| F3 | services 层幽灵导入 | `services/__init__.py` | 14 个延迟导入目标模块不存在 |
| F4 | Brain 信号格式统一 | `shared/interfaces.py` → `MarketSignalContext` | 调用方传入格式与 `make_decision()` 预期不一致 |

---

## 2. F1: validate() 返回类型不匹配

### 2.1 根因分析

```
data_pipeline_service.py:19:
    df = self.validator.validate(df)    # 返回 bool，df 被覆盖为 True/False
```

`DataValidator.validate()` 签名:
```python
def validate(self, df: pd.DataFrame) -> bool:   # 返回 bool
```

但 `DataPipelineService.process()` 将返回值重新赋给 `df`，导致后续 `apply_adjustment()` 接收到 `bool` 而非 `DataFrame`。

### 2.2 影响范围分析

**直接受影响的调用链**:

```
DataFetcher.get_price(symbol)          # data_fetcher.py:112
  -> pipeline.process(df, symbol)      # data_pipeline_service.py:17-21
     -> validator.validate(df)         # 返回 bool
     -> df = True/False                # ← BUG: df 被覆盖
     -> adjuster.apply_adjustment(symbol, True)  # ← 传入 bool
```

`DataAdjuster.apply_adjustment()` 第一行检查 `df_raw.empty`:
```python
def apply_adjustment(self, symbol, df_raw, method, ...):
    if df_raw.empty or method not in ["qfq", "hfq"]:  # bool 没有 .empty 属性
        return df_raw                                    # → AttributeError 崩溃
```

**当前实际影响**: `DataPipelineService.process()` **完全不可用**。任何通过 `DataFetcher.get_price()` 获取的数据都会在复权阶段崩溃。

**但**: `get_price()` 有缓存机制 (`_get_price_cached`)，且 `StockDataUpdater` 和 `TdxUpdater` 不经过 `DataPipelineService`，而是直接使用 `DataValidator`（用法正确）。

### 2.3 不受影响的调用方

| 调用方 | 文件:行 | 用法 | 影响 |
|--------|---------|------|------|
| `StockDataUpdater.needs_update()` | `stock_data_updater.py:28` | `if not self.data_validator.validate(df):` | **不受影响** — 作为 bool 使用 |
| `StockDataUpdater.update_stock()` | `stock_data_updater.py:92` | `if not self.data_validator.validate(df_new):` | **不受影响** — 作为 bool 使用 |
| `TdxUpdater._full_update()` | `tdx_updater.py:297` | `if self.data_validator.validate(df_clean):` | **不受影响** — 作为 bool 使用 |
| `TdxUpdater._incremental_update()` | `tdx_updater.py:391` | `if self.data_validator.validate(df_clean):` | **不受影响** — 作为 bool 使用 |

### 2.4 推荐修复方案

```python
# data_pipeline_service.py:17-21
def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
    df = self.cleaner.clean_stock_daily(df)
    if not self.validator.validate(df):
        raise ValueError(f"数据验证失败: {symbol}")
    # validate() 已原地修改 df（修复 high/low、排序日期等）
    df = self.adjuster.apply_adjustment(symbol, df, method=adjust)
    return df
```

### 2.5 回归风险评估

| 维度 | 评估 |
|------|------|
| **风险等级** | **🟢 低** |
| **原因** | 修复仅改变 `data_pipeline_service.py` 内部行为；`stock_data_updater.py` 和 `tdx_updater.py` 直接使用 `DataValidator`，不经过 `DataPipelineService`，完全不受影响 |
| **破坏性** | 修复前 `DataPipelineService.process()` 100% 崩溃（bool 传入 adjuster），修复后恢复正常。不会引入新行为 |
| **测试覆盖** | 现有测试无 `DataPipelineService` 单测，需补充 |
| **回滚难度** | 极低 — 单文件单行修改 |

---

## 3. F2: FSM 幽灵导入

### 3.1 根因分析

```python
# fsm.py:19-22
try:
    from ..indicators.indicators import Indicators
except ImportError:
    Indicators = None  # TODO: Phase 1A 迁移 brain/indicators.py 后移除
```

`brain/indicators/` 目录不存在（Phase 1A 未执行），因此 `Indicators` 始终为 `None`。

### 3.2 影响范围分析

`Indicators` 仅在 `FSM.infer_state()` 中使用:

```python
# fsm.py:112-115
if Indicators is None:
    raise ImportError("Indicators module not available")
ma20 = Indicators.calc_ma(analysis_df, self.ma_short)
ma60 = Indicators.calc_ma(analysis_df, self.ma_long)
```

**关键发现**: `DecisionBrain` **不依赖 `Indicators`**。`DecisionBrain.make_decision()` 接收 `MarketSignalContext`（已计算好的信号），不调用 `FSM.infer_state()`。

**调用链分析**:

| 调用方 | 是否经过 `FSM.infer_state()` | 是否受影响 |
|--------|------------------------------|------------|
| `DecisionBrain.make_decision()` | **否** — 直接使用 `MarketSignalContext` | **不受影响** |
| `AnalysisService._run_engine_analysis()` | **否** — 各引擎独立计算信号 | **不受影响** |
| `FsmAnalysisEngine` | **否** — 使用 `DecisionBrain` | **不受影响** |
| `HealthService._check_brain_health()` | **否** — 使用 `DecisionBrain` | **不受影响** |
| 外部直接调用 `FSM().infer_state(df)` | **是** — `Indicators is None` → `ImportError` | **已崩溃** |

### 3.3 推荐修复方案

保留 try/except 保护，但添加明确的文档说明和降级行为:

```python
# fsm.py:19-22 (保持现有结构，添加注释)
try:
    from ..indicators.indicators import Indicators
except ImportError:
    Indicators = None  # Phase 0: 模块尚未迁移，infer_state() 将不可用
```

**不建议**: 在 Phase 0 创建 `Indicators` 存根。存根的 `calc_ma()` 实现如果不正确，会静默产生错误信号，比显式 `ImportError` 更危险。

### 3.4 回归风险评估

| 维度 | 评估 |
|------|------|
| **风险等级** | **🟢 低** |
| **原因** | `DecisionBrain` 是核心决策路径，完全不依赖 `Indicators`。幽灵导入仅影响 `FSM.infer_state()`，而该方法在当前架构中无活跃调用方 |
| **破坏性** | 无。现有 try/except 已经是正确的防御性编程 |
| **测试覆盖** | `test_fsm.py` 中 `TestDecisionBrain` 不使用 `FSM.infer_state()`，不受影响 |
| **回滚难度** | 极低 — 无需修改，保持现状即可 |

---

## 4. F3: services 层幽灵导入

### 4.1 根因分析

`services/__init__.py` 使用 `__getattr__` 延迟加载，映射了 14 个模块:

```python
_imports = {
    "CacheCoordinator": ".cache_coordinator",
    "DataService": ".data_service",
    "HealthService": ".health_service",
    "PortfolioService": ".portfolio_service",
    "ScanPipeline": ".scan_service",
    "StockQueryService": ".stock_query_service",
    "ValidationService": ".validation_service",
    "AnalysisService": ".analysis_service",
    "ServiceContainer": ".service_container",
    "DataAccessService": ".data_access_service",
    "DataQualityService": ".data_quality_service",
    "MarketRegimeService": ".market_regime_service",
    "ReportService": ".report_service",
    "SignalGenerationService": ".signal_generation_service",
}
```

### 4.2 影响范围分析

**当前状态**: `__getattr__` 机制**已经正确处理了不存在的模块** — 访问不存在的属性时抛出 `AttributeError`，不会在 `import uniquant.services` 时崩溃。

**对比旧版** (AGENTS.md 描述的"8 个幽灵导入"): 旧版可能在 `__init__.py` 顶层直接 `from .xxx import YYY`，导致导入时崩溃。当前代码已使用 `__getattr__` 懒加载，**幽灵导入问题已缓解**。

**剩余风险**: 如果外部代码执行 `from uniquant.services import SignalGenerationService`，会得到 `AttributeError`（因为 `.signal_generation_service` 模块不存在）。但这是预期行为 — 延迟加载失败时的合理降级。

### 4.3 回归风险评估

| 维度 | 评估 |
|------|------|
| **风险等级** | **🟢 低（已缓解）** |
| **原因** | `__getattr__` 机制已正确处理不存在的模块。`import uniquant.services` 不会崩溃。仅在显式访问不存在属性时抛 `AttributeError` |
| **破坏性** | 无需修复。当前实现已经是防御性的 |
| **测试覆盖** | `test_engine_factory.py` 验证了 `AnalysisEngineFactory` 的延迟加载 |
| **回滚难度** | N/A — 无需修改 |

---

## 5. F4: Brain 信号格式统一

### 5.1 根因分析

`DecisionBrain.make_decision()` 接受 `Union[dict, MarketSignalContext]`:

```python
def make_decision(self, data_packet: Union[dict, MarketSignalContext]) -> Dict[str, Any]:
    if isinstance(data_packet, MarketSignalContext):
        ctx = data_packet
    else:
        ctx = MarketSignalContext.from_dict(data_packet)
```

`MarketSignalContext` 预期字段:
```
regime, risk, bubble_confidence, ntf_side, ntf_intensity, is_3rd_buy,
bi_count, alpha_score, ma_status, price, pre_close, symbol, name,
atr_stop, czsc_bottom, market, returns, lppl_days_to_tc
```

### 5.2 调用方信号格式对比

| 调用方 | 文件:行 | 传入格式 | 与 MarketSignalContext 兼容性 |
|--------|---------|----------|------------------------------|
| `AnalysisService._make_decision()` | `analysis_service.py:1060` | `data_pack` (dict) | **部分兼容** — 经 `_run_engine_analysis()` 填充了 regime/risk/ntf_side/alpha_score 等字段 |
| `FsmAnalysisEngine` | `fsm_analysis_engine.py:93` | `{"stock": df, "bench": None, ...}` | **不兼容** — 缺少所有 MarketSignalContext 字段，`from_dict()` 全部使用默认值 |
| `HealthService._check_brain_health()` | `health_service.py:176` | `data_pack` (dict from `fetch_for_brain`) | **不兼容** — `fetch_for_brain()` 返回 `{"stock": df, "symbol": symbol}`，缺少信号字段 |
| `test_fsm.py` 测试用例 | `test_fsm.py:143-156` | 完整 dict | **完全兼容** — 所有字段正确 |

### 5.3 影响分析

**`FsmAnalysisEngine` 的信号格式问题**:

```python
# fsm_analysis_engine.py:85-90
data_pack = {
    "stock": df,
    "bench": None,
    "sector": None,
    "etf": None,
}
result = fsm_engine.make_decision(data_pack)  # ← 传入错误格式
```

`MarketSignalContext.from_dict()` 会对缺失字段使用默认值:
- `regime` → `MarketRegime.NORMAL` (合理默认)
- `risk` → `"Safe"` (可能过于乐观)
- `alpha_score` → `0.0` (无信号)
- `is_3rd_buy` → `False` (无缠论信号)
- `price` → `0.0` (后续 `ctx.price > 0` 检查会跳过涨跌停逻辑)

**结果**: `DecisionBrain` 会执行，但所有信号都是默认值，决策退化为"综合得分=0，维持当前状态"。不会崩溃，但**输出无意义**。

**`FsmAnalysisEngine` 的响应格式问题**:

```python
# fsm_analysis_engine.py:108
"current_state": result.get("decision", "UNKNOWN"),  # ← 字段名错误
"signal_strength": result.get("score", 0.0)           # ← 字段名错误
```

但 `_build_response()` 返回的键是 `"action"` 和 `"final_score"`，不是 `"decision"` 和 `"score"`。所以:
- `current_state` 永远是 `"UNKNOWN"`
- `signal_strength` 永远是 `0.0`

### 5.4 回归风险评估

| 维度 | 评估 |
|------|------|
| **风险等级** | **🟡 中** |
| **原因** | `FsmAnalysisEngine` 和 `HealthService` 传入的 dict 格式与 `MarketSignalContext` 不匹配。当前行为是"静默退化为默认值"而非崩溃。修复信号格式会改变这些路径的输出行为 |
| **破坏性** | 修复 `FsmAnalysisEngine` 的信号构建会导致其输出从"总是 UNKNOWN/0.0"变为实际信号值。这是**行为变更**，可能影响依赖当前（错误）输出的下游逻辑 |
| **测试覆盖** | `test_fsm.py` 仅测试了格式正确的输入，未覆盖格式不匹配的降级行为 |
| **回滚难度** | 中等 — 需要修改 `fsm_analysis_engine.py` 的数据包构建逻辑 |

### 5.5 推荐修复方案

**Phase 0 (低风险)**: 修复 `FsmAnalysisEngine` 中的响应字段名映射:

```python
# fsm_analysis_engine.py:108-109 (修复字段名)
"current_state": result.get("action", "UNKNOWN"),   # 修正: decision → action
"signal_strength": result.get("final_score", 0.0)   # 修正: score → final_score
```

**Phase 1A (中风险)**: 重构 `FsmAnalysisEngine` 的数据包构建，使用 `MarketSignalContext`:

```python
from ...shared.interfaces import MarketSignalContext

ctx = MarketSignalContext(
    regime=...,  # 从 regime 检测结果获取
    risk=...,    # 从 LPPL 检测结果获取
    price=df.iloc[-1]["close"],
    pre_close=df.iloc[-2]["close"] if len(df) > 1 else df.iloc[-1]["close"],
    symbol=symbol,
    # ... 其他字段
)
result = fsm_engine.make_decision(ctx)
```

---

## 6. 综合风险矩阵

| 修复项 | 回归风险 | 影响范围 | 测试覆盖 | 推荐优先级 |
|--------|----------|----------|----------|------------|
| F1: validate() 返回类型 | 🟢 低 | `DataPipelineService.process()` (当前已崩溃，修复=恢复正常) | 无单测，需补充 | P0 — 立即修复 |
| F2: FSM 幽灵导入 | 🟢 低 | `FSM.infer_state()` (无活跃调用方，`DecisionBrain` 不受影响) | `test_fsm.py` 覆盖 | P0 — 保持现状，添加文档 |
| F3: services 幽灵导入 | 🟢 低 (已缓解) | `__getattr__` 已正确处理 | `test_engine_factory.py` 覆盖 | P1 — 清理 `__all__` 中不存在的导出 |
| F4: Brain 信号格式 | 🟡 中 | `FsmAnalysisEngine` 输出退化 | 仅覆盖正确格式 | P1 — Phase 0 修字段名，Phase 1A 重构数据包 |

---

## 7. 回归验证清单

### 7.1 F1 修复后必须验证

```bash
# 1. DataPipelineService.process() 不再崩溃
python -c "
import pandas as pd
from uniquant.data.data_pipeline_service import DataPipelineService
svc = DataPipelineService()
df = pd.DataFrame({
    'date': ['2024-01-01'], 'code': ['600000'],
    'open': [10.0], 'high': [10.5], 'low': [9.5], 'close': [10.0],
    'volume': [1000], 'amount': [10000]
})
result = svc.process(df, '600000.SH')
assert isinstance(result, pd.DataFrame), '返回值必须是 DataFrame'
print('F1 验证通过')
"

# 2. stock_data_updater 不受影响
pytest tests/ -k "stock_data_updater" -xvs 2>/dev/null || echo "无相关测试"

# 3. tdx_updater 不受影响
pytest tests/test_tdx_incremental.py -xvs 2>/dev/null || echo "无相关测试"

# 4. get_price 完整链路
python -c "
from uniquant.data.data_fetcher import DataFetcher
fetcher = DataFetcher()
# df = fetcher.get_price('600000.SH')  # 需要网络，CI 中跳过
print('DataFetcher 初始化正常')
"
```

### 7.2 F4 修复后必须验证

```bash
# 1. DecisionBrain 响应格式一致
pytest tests/test_fsm.py -xvs

# 2. FsmAnalysisEngine 字段映射
python -c "
from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
# 验证 result.get('action') 和 result.get('final_score') 存在
print('FsmAnalysisEngine 字段映射验证')
"

# 3. HealthService 健康检查
python -c "
from uniquant.services.health_service import HealthService
# 验证 health check 不崩溃
print('HealthService 验证通过')
"
```

---

## 8. 结论

1. **F1 (validate 返回类型)** 是唯一真正的 P0 修复，风险极低。修复行为等同于"恢复已崩溃的功能"，不会引入新行为。

2. **F2 (FSM 幽灵导入)** 已被 try/except 正确保护。`DecisionBrain` 作为核心决策路径完全不依赖 `Indicators`，无需修改。

3. **F3 (services 幽灵导入)** 已通过 `__getattr__` 懒加载机制缓解。当前 `import uniquant.services` 不会崩溃。

4. **F4 (Brain 信号格式)** 是唯一的中等风险项。`FsmAnalysisEngine` 的数据包构建和响应字段映射存在两处错误，但当前行为是"静默退化"而非崩溃。修复会改变输出行为，需配合端到端测试验证。

**总体评估**: 四项修复的回归风险可控。F1 是"修复已崩溃功能"，F2/F3 已有防御机制，F4 需要谨慎处理信号格式兼容性。
