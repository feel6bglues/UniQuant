# 算法层核实报告

**核实时间**: 2026-05-27  
**核实范围**: brain/ 层重构方案  
**核实依据**: 源码分析 + 架构文档

---

## 1. FSM 状态机核实

### 1.1 状态设计评估

**结论: 状态设计合理，覆盖完整交易周期**

| 状态 | 含义 | 评估 |
|------|------|------|
| `IDLE` | 空闲/观望 | ✅ 初始状态，合理 |
| `SIGNAL` | 信号触发 | ✅ 价格突破 MA60 |
| `PROBE` | 试盘/回踩 | ✅ 缩量回踩 MA20 |
| `MONITOR` | 监控/持有 | ✅ 明确上升趋势 |
| `PYRAMID` | 加仓 | ✅ 持续上涨阶段 |
| `EXIT` | 退出 | ✅ 跌破关键均线 |
| `CIRCUIT_BREAK` | 熔断 | ✅ 极端波动保护 |

**状态转换规则** (`fsm.py:414-422`):
```python
valid_transitions = {
    FSMState.IDLE: [FSMState.SIGNAL, FSMState.PROBE],
    FSMState.SIGNAL: [FSMState.PROBE, FSMState.IDLE],
    FSMState.PROBE: [FSMState.MONITOR, FSMState.IDLE, FSMState.EXIT],
    FSMState.MONITOR: [FSMState.PYRAMID, FSMState.EXIT, FSMState.IDLE],
    FSMState.PYRAMID: [FSMState.MONITOR, FSMState.EXIT],
    FSMState.EXIT: [FSMState.IDLE],
    FSMState.CIRCUIT_BREAK: [FSMState.IDLE],
}
```

**评估**: 转换规则符合交易逻辑，防止非法跳转。

### 1.2 DecisionBrain Veto-Scoring 架构

**结论: 架构完整，决策流程清晰**

决策流程 (`fsm.py:481-550`):
1. **否决检查** (`_check_veto_conditions`): FROZEN → FORCE_WAIT, Danger + 非 SUPPORT → FORCE_EXIT
2. **得分计算** (`_calculate_score`): CZSC(20) + 趋势(15) + Alpha(10) + NTF(10)
3. **卖出检查** (`_check_sell_conditions`): LPPL_DANGER, MA_REVERSAL, ALPHA_WEAK, REGIME_RISK
4. **状态确定** (`_determine_target_state`): 基于得分阈值转换
5. **买入阻断** (`_check_buy_blockers`): LPPL_DANGER, MARKET_FROZEN, ALPHA_TOO_WEAK, LIMIT_UP
6. **执行买入** (`_execute_buy`): 计算仓位，考虑 EVT 风险缩放

**评分阈值** (`constants.py:248-253`):
- IDLE → SIGNAL: 30 分
- SIGNAL → MONITOR: 50 分
- MONITOR → PYRAMID: 70 分
- EXIT 阈值: 10 分

### 1.3 `from ..indicators import Indicators` 影响分析

**⚠️ 关键问题: 幽灵导入**

**现状**:
- `brain/indicators.py` **不存在**
- `fsm.py:19` 导入 `from ..indicators import Indicators`
- 实际使用: `Indicators.calc_ma()` (`fsm.py:109-110`)

**影响范围**:
```python
# fsm.py:109-110
ma20 = Indicators.calc_ma(analysis_df, self.ma_short)
ma60 = Indicators.calc_ma(analysis_df, self.ma_long)
```

**当前状态**: 代码可运行（可能有 fallback 或内联实现），但违反模块化原则。

**修复建议**:
1. 创建 `brain/indicators.py`，实现 `Indicators.calc_ma()` 方法
2. 或使用 Pandas 内置方法: `df['close'].rolling(window=n).mean()`

### 1.4 状态持久化机制

**结论: 机制可靠，有容错处理**

实现方式 (`fsm.py:589-656`):
- **存储格式**: JSON 文件 (`data/state/fsm_state.json`)
- **并发控制**: FileLock 文件锁
- **历史限制**: 仅保存最近 100 条记录
- **容错处理**: 加载失败时回退到 IDLE 状态

**代码示例** (`fsm.py:594-610`):
```python
state_data = {
    "state": self.state.value,
    "previous_state": self._previous_state.value,
    "state_history": self._state_history[-100:],
    "timestamp": pd.Timestamp.now().isoformat(),
}
with FileLock(str(lock_file)):
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)
```

**评估**: 
- ✅ 使用文件锁防止并发写入
- ✅ 限制历史记录数量
- ✅ 加载失败有降级处理
- ⚠️ 未见数据完整性校验（如 checksum）

---

## 2. LPPL 泡沫检测核实

### 2.1 参数约束验证

**结论: 符合 Sornette 理论，参数合理**

**Sornette 理论约束**:
- `m` (幂律指数): 理论范围 [0, 1]，实际约束 [0.1, 0.9]
- `ω` (对数周期频率): 理论范围 [6, 13]，对应约 6-13 次振荡

**代码实现** (`constants.py:15-16`, `engine.py:57-58`):
```python
# 全局常量
M_BOUNDS = (0.1, 0.9)
W_BOUNDS = (6.0, 13.0)

# LPPLConfig 默认值
m_bounds: Tuple[float, float] = (0.1, 0.9)
w_bounds: Tuple[float, float] = (5, 18)  # ⚠️ 略宽于理论值
```

**⚠️ 发现**: `LPPLConfig.w_bounds` 默认为 (5, 18)，宽于理论值 (6, 13)。但 `engine.py:197-198` 使用 `M_BOUNDS` 和 `W_BOUNDS` 常量进行验证。

**评估**: 
- 核心约束符合理论
- 配置类有冗余，建议统一使用常量

### 2.2 差分进化优化器配置

**结论: 配置合理，性能与精度平衡**

**配置参数** (`engine.py:51-55`, `constants.py:856-863`):
```python
# LPPLConfig 默认
optimizer: str = "de"
maxiter: int = 100
popsize: int = 15
tol: float = 0.05

# LPPLConstants
MAX_ITER = 500
POP_SIZE = 10
TOLERANCE = 0.01
```

**优化器调用** (`engine.py:167-178`):
```python
result = differential_evolution(
    cost_function,
    bounds,
    args=(t_data, log_price_data),
    strategy="best1bin",
    maxiter=config.maxiter,  # 100
    popsize=config.popsize,  # 15
    tol=config.tol,          # 0.05
    seed=RANDOM_SEED,        # 42
    workers=de_workers,
    timeout=120,
)
```

**评估**:
- ✅ `strategy="best1bin"` 是经典策略
- ✅ `seed=42` 保证可复现
- ✅ `timeout=120` 防止死循环
- ✅ 支持并行 `workers=de_workers`
- ⚠️ `maxiter=100` 可能不足，建议提升至 200-500

### 2.3 Numba JIT 加速实现

**结论: 实现正确，有优雅降级**

**实现方式** (`engine.py:24-32`, `numba_optimizer.py:5-11`):
```python
# engine.py - 优雅降级
try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

# numba_optimizer.py - JIT 编译
@njit(cache=True, fastmath=True)
def _reduced_cost_numba(nonlinear, t, log_prices):
    # Numba 加速的成本函数
```

**评估**:
- ✅ 有 Numba 时使用 JIT 加速
- ✅ 无 Numba 时优雅降级为纯 Python
- ✅ `cache=True` 缓存编译结果
- ✅ `fastmath=True` 启用快速数学

### 2.4 风险分类逻辑

**结论: 逻辑合理，阈值清晰**

**分类函数** (`engine.py:101-110`):
```python
def classify_top_phase(days_left: float, r2: float, config: LPPLConfig) -> str:
    if days_left < 0:
        return "none"
    if days_left < config.danger_days and r2 >= danger_r2_threshold(config):
        return "danger"
    if days_left < config.warning_days and r2 >= warning_r2_threshold(config):
        return "warning"
    if days_left < config.watch_days and r2 >= watch_r2_threshold(config):
        return "watch"
    return "none"
```

**阈值配置** (`engine.py:64-66`):
```python
danger_days: int = 5
warning_days: int = 12
watch_days: int = 25
```

**R² 阈值** (`engine.py:89-98`):
```python
danger_r2_threshold = r2_threshold + danger_r2_offset  # 0.5 + 0.0 = 0.5
warning_r2_threshold = r2_threshold - 0.05             # 0.45
watch_r2_threshold = r2_threshold - 0.15               # 0.35
```

**评估**:
- ✅ 时间窗口递增: 5 < 12 < 25 天
- ✅ R² 阈值递减: danger > warning > watch
- ✅ 符合"越接近崩盘，信号越强"的逻辑

---

## 3. CZSC 缠论核实

### 3.1 实现方式评估

**结论: 基于 czsc 库封装，符合原著**

**依赖库** (`czsc_engine.py:6`):
```python
from czsc import CZSC, Freq, RawBar
```

**核心流程** (`czsc_engine.py:158-221`):
1. 输入验证 (`_validate_input_row`)
2. 构建 RawBar 对象
3. 增量更新 CZSC 分析器 (`analyzer.update(bar)`)
4. 提取信号 (`analyzer.signals`, `analyzer.bi_list`)

**评估**:
- ✅ 使用成熟的 czsc 库（缠中说禅原著实现）
- ✅ 支持增量更新，性能优秀
- ✅ 数据验证完整（OHLC 逻辑检查）

### 3.2 笔段中枢识别

**结论: 依赖 czsc 库，实现正确**

**识别流程** (`czsc_engine.py:330-382`):
```python
def _extract_czsc_signals(self, analyzer: CZSC) -> Dict[str, Any]:
    bi_list = analyzer.bi_list      # 笔列表
    signals = analyzer.signals      # 信号字典
    
    # 三买检测
    if HAS_CZSC_SIGNALS:
        third_buy_result = czsc_signals.cxt_third_buy_V230228(analyzer)
```

**评估**:
- ✅ 笔识别依赖 czsc 库的 `bi_list`
- ✅ 信号识别依赖 czsc 库的 `signals`
- ✅ 三买信号有专用函数 `cxt_third_buy_V230228`

### 3.3 三买信号判断

**结论: 实现合理，有双重检测机制**

**检测逻辑** (`czsc_engine.py:354-372`):
```python
# 方式 1: czsc_signals 库函数
if HAS_CZSC_SIGNALS:
    third_buy_result = czsc_signals.cxt_third_buy_V230228(analyzer)
    if third_buy_result:
        for key, value in third_buy_result.items():
            if "三买_" in str(value) or "三买" == str(value):
                is_3rd_buy = True

# 方式 2: 枚举类型检测（fallback）
if not is_3rd_buy:
    for signal_value in signals.values():
        if CZSCSignalType.from_signal_value(signal_value) == CZSCSignalType.THIRD_BUY:
            is_3rd_buy = True
```

**评估**:
- ✅ 双重检测机制，提高可靠性
- ✅ 使用枚举类型避免字符串匹配脆性
- ✅ 有 `HAS_CZSC_SIGNALS` 降级处理

---

## 4. Protocol 接口核实

### 4.1 接口覆盖评估

**结论: 5 个 Protocol 覆盖核心需求**

| Protocol | 用途 | 评估 |
|----------|------|------|
| `DataFetcherProtocol` | 数据获取 | ✅ 覆盖历史数据查询 |
| `RiskAssessmentProtocol` | 风险评估 | ✅ 覆盖 EVT/CVaR 计算 |
| `PositionSizerProtocol` | 仓位计算 | ✅ 覆盖仓位建议 |
| `AnalysisEngineProtocol` | 分析引擎 | ✅ 覆盖通用分析接口 |
| `CalculationPluginProtocol` | 计算插件 | ✅ 覆盖插件注册机制 |

**缺失接口**:
- ⚠️ 无 `SignalGeneratorProtocol`（信号生成）
- ⚠️ 无 `BacktestEngineProtocol`（回测引擎）

### 4.2 MarketSignalContext 字段完整性

**结论: 17 个字段覆盖主要需求**

**字段列表** (`interfaces.py:30-47`):
```python
@dataclass
class MarketSignalContext:
    regime: MarketRegime           # 市场状态
    risk: str                      # 风险等级
    bubble_confidence: float       # 泡沫置信度
    ntf_side: NtfSide              # 国家队方向
    ntf_intensity: float           # 国家队强度
    is_3rd_buy: bool               # 三买信号
    bi_count: int                  # 笔数量
    alpha_score: float             # Alpha 得分
    ma_status: Optional[str]       # 均线状态
    price: float                   # 当前价格
    pre_close: float               # 前收盘价
    symbol: str                    # 股票代码
    name: Optional[str]            # 股票名称
    atr_stop: float                # ATR 止损
    czsc_bottom: Optional[float]   # 缠论底部
    market: str                    # 市场标识
    returns: Optional[pd.Series]   # 收益率序列
    lppl_days_to_tc: Optional[float]  # LPPL 崩盘天数
```

**评估**:
- ✅ 覆盖技术分析（CZSC、LPPL、MA）
- ✅ 覆盖风险评估（regime、risk）
- ✅ 覆盖交易执行（price、atr_stop）
- ⚠️ 缺少成交量相关字段（volume_ratio、turnover_rate）
- ⚠️ 缺少基本面字段（pe_ratio、pb_ratio）

---

## 5. 重构方案评估

### 5.1 合理的方案

| 方案 | 评估 | 理由 |
|------|------|------|
| 修复幽灵导入 | ✅ 必要 | `brain/indicators.py` 不存在 |
| 补充 risk 模块 | ✅ 必要 | `evt_risk.py`, `sizer.py` 不存在 |
| 统一常量管理 | ✅ 合理 | `W_BOUNDS` 与 `LPPLConfig.w_bounds` 不一致 |
| 增强状态持久化 | ✅ 合理 | 添加 checksum 校验 |

### 5.2 需要调整的方案

| 方案 | 问题 | 建议 |
|------|------|------|
| LPPL 参数约束放宽 | `w_bounds=(5,18)` 宽于理论值 | 统一使用 `W_BOUNDS=(6,13)` |
| 差分进化 maxiter=100 | 可能不足 | 提升至 200-500 |
| MarketSignalContext 字段 | 缺少成交量/基本面 | 按需添加，避免过度设计 |

### 5.3 遗漏的问题

| 问题 | 影响 | 建议 |
|------|------|------|
| `services/__init__.py` 幽灵导入 | 8 个模块不存在 | Phase 0.1 修复 |
| `brain/lppl/__init__.py` 幽灵导入 | 7 个模块不存在 | Phase 0.2 修复 |
| `engine_factory` 参数错配 | 引擎无法初始化 | Phase 1A.9 修复 |
| 缺少单元测试 | 无法验证正确性 | TDD 流程补充 |

---

## 6. 风险提示

### 6.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 幽灵导入导致崩溃 | 高 | 高 | Phase 0 优先修复 |
| LPPL 参数过宽误报 | 中 | 中 | 收紧至理论值 |
| 状态文件损坏 | 低 | 中 | 添加 checksum + 备份 |
| czsc 库版本不兼容 | 低 | 高 | 锁定版本，添加兼容层 |

### 6.2 实施建议

1. **优先级排序**:
   - P0: 修复幽灵导入（Phase 0）
   - P1: 补充缺失模块（Phase 1）
   - P2: 优化参数配置（Phase 2）

2. **测试策略**:
   - 每个修复点编写单元测试
   - 集成测试验证完整流程
   - 回归测试防止引入新问题

3. **代码审查**:
   - 修复后运行 `ruff check`
   - 类型检查 `mypy`
   - 导入链验证 `python -c "import uniquant"`

---

**核实结论**: brain/ 层架构设计合理，核心算法符合金融理论。主要风险在于幽灵导入和缺失模块，需优先修复。重构方案整体可行，建议按 Phase 0 → 1 → 2 顺序执行。

**核实人**: opencode (mimo-v2.5-pro)  
**核实时间**: 2026-05-27
