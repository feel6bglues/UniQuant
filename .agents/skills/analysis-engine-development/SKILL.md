# 分析引擎开发

## 何时使用
开发新分析引擎时；修改现有引擎时；理解引擎注册流程时。

## 引擎开发模式
新引擎必须实现 `AnalysisEngineProtocol.analyze(data, **kwargs) → Dict`。

## AnalysisEngineFactory 注册流程
1. 在 `services/analysis/` 创建 `xxx_analysis_engine.py`
2. 在 `engine_factory.py` 添加 `@property`（见 `engine_factory.py:31-65`）
3. 在 `_lazy_init` 中注册（见 `engine_factory.py:18-29`）

### 已注册引擎列表
| 属性名 | 模块路径 | 类名 |
|--------|----------|------|
| `fsm` | `..analysis.fsm_analysis_engine` | `FsmAnalysisEngine` |
| `czsc` | `..analysis.czsc_analysis_engine` | `CzscAnalysisEngine` |
| `lppl` | `..analysis.lppl_analysis_engine` | `LpplAnalysisEngine` |
| `regime` | `..analysis.regime_analysis_engine` | `RegimeAnalysisEngine` |
| `ntf` | `..analysis.ntf_analysis_engine` | `NtfAnalysisEngine` |
| `macro` | `..analysis.macro_analysis_engine` | `MacroAnalysisEngine` |
| `report` | `..analysis.report_generator_engine` | `ReportGeneratorEngine` |
| `brain` | `...brain.fsm` | `DecisionBrain` |
| `wyckoff` | `..analysis.wyckoff_analysis_engine` | `WyckoffAnalysisEngine` |

## 5 个 Protocol 接口签名

### 1. DataFetcherProtocol (`interfaces.py:102-120`)
```python
@runtime_checkable
class DataFetcherProtocol(Protocol):
    def fetch_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        period: str = "daily",
    ) -> pd.DataFrame: ...
```

### 2. RiskAssessmentProtocol (`interfaces.py:123-140`)
```python
@runtime_checkable
class RiskAssessmentProtocol(Protocol):
    def calculate_metrics(self, returns: pd.DataFrame) -> Dict[str, Any]: ...
```

### 3. PositionSizerProtocol (`interfaces.py:143-171`)
```python
@runtime_checkable
class PositionSizerProtocol(Protocol):
    def calculate_shares(
        self,
        price: float,
        stop_loss: float,
        czsc_bottom: Any,
        market: str = "CN",
        symbol: str = "UNKNOWN",
    ) -> Dict[str, Any]: ...
```

### 4. AnalysisEngineProtocol (`interfaces.py:174-192`)
```python
@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    def analyze(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...
```

### 5. CalculationPluginProtocol (`interfaces.py:195-234`)
```python
@runtime_checkable
class CalculationPluginProtocol(Protocol):
    @property
    def name(self) -> str: ...
    
    @property
    def version(self) -> str: ...
    
    @property
    def description(self) -> str: ...
    
    def calculate(self, data: pd.DataFrame, **kwargs) -> Dict[str, Any]: ...
```

## 已有引擎参考

### FSM 模式（`brain/fsm/fsm.py`）
状态机模式，输入 DataFrame → 输出状态字典。

- **类**: `FSM` (`fsm.py:42-170`)
- **核心方法**: `infer_state(df: pd.DataFrame) -> Dict[str, Any]` (`fsm.py:92`)
- **状态枚举**: `FSMState` (`fsm.py:24-31`)
  - `IDLE`, `SIGNAL`, `PROBE`, `MONITOR`, `PYRAMID`, `EXIT`, `CIRCUIT_BREAK`
- **输入验证**: `_REQUIRED_COLUMNS = frozenset({"close", "high", "low", "open"})` (`fsm.py:48`)
- **返回结构**:
  ```python
  {
      "state": FSMState,
      "state_name": str,
      "state_desc": str,
      "transition_reason": str,
      "ma_status": str,
      "fsm_state": str,
  }
  ```

### LPPL 模式（`brain/lppl/engine.py`）
数值拟合模式，差分进化算法。

- **配置类**: `LPPLConfig` (`engine.py:43-82`)
- **核心函数**: `fit_single_window(close_prices, window_size, config)` (`engine.py:118-215`)
- **优化器**: `scipy.optimize.differential_evolution` (`engine.py:167`)
- **风险分类**: `classify_top_phase(days_left, r2, config)` (`engine.py:101-110`)
  - 返回: `"none"`, `"danger"`, `"warning"`, `"watch"`
- **返回结构**:
  ```python
  {
      "window_size": int,
      "rmse": float,
      "r_squared": float,
      "m": float,
      "w": float,
      "tc": float,
      "days_to_crash": float,
      "is_danger": bool,
      "params": tuple,
  }
  ```

### CZSC 模式（`brain/czsc/czsc_engine.py`）
第三方库封装模式。

- **类**: `CZSCEngine` (`czsc_engine.py:85-623`)
- **信号类型枚举**: `CZSCSignalType` (`czsc_engine.py:32-78`)
  - `FIRST_BUY`, `FIRST_SELL`, `SECOND_BUY`, `SECOND_SELL`, `THIRD_BUY`, `THIRD_SELL`, `UNKNOWN`
- **核心方法**:
  - `update_and_get_signals(df_latest_row: pd.Series) -> Dict[str, Any]` (`czsc_engine.py:158`)
  - `get_czsc_signals(df: pd.DataFrame) -> Dict[str, Any]` (`czsc_engine.py:461`)
- **输入验证**: `REQUIRED_COLUMNS = {"date", "open", "close", "high", "low"}` (`czsc_engine.py:92`)
- **返回结构**:
  ```python
  {
      "bi_count": int,
      "last_bi_direction": int,
      "is_3rd_buy": bool,
      "czsc_signal": str,
      "bottom_fractal": float,
      "czsc_bottom_price": float,
      "signals": Dict,
      "geometry_desc": str,
      "analysis_coverage": float,
      "error": str,
  }
  ```

## 引擎→服务适配器模式
`services/analysis/*_engine.py` 包装 `brain` 层引擎。

### CzscAnalysisEngine 示例 (`czsc_analysis_engine.py:19-207`)
```python
class CzscAnalysisEngine:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
    
    def run_czsc_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        # 1. 生成缓存键
        cache_key = self.orchestrator._generate_cache_key("czsc_analysis", symbol=symbol)
        
        # 2. 尝试从缓存获取结果
        cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
        
        # 3. 获取数据（从数据湖）
        df = self.orchestrator.data_service.lake.read_data(symbol, data_type="stock", market="cn")
        
        # 4. 优化和采样
        df = self.orchestrator._optimize_dataframe(df)
        df = self.orchestrator._sample_data(df, max_rows=AnalysisServiceConstants.SAMPLE_MAX_ROWS_CZSC)
        
        # 5. 调用 brain 层引擎
        from ...brain.czsc.czsc_engine import CZSCEngine
        czsc_engine = CZSCEngine()
        result = czsc_engine.get_czsc_signals(df)
        
        # 6. 缓存结果
        self.orchestrator._set_cached_result(cache_key, result, use_disk=True, ttl=...)
        
        return result
```

## MarketSignalContext
类型化数据包的字段和用法（`interfaces.py:22-99`）。

```python
@dataclass
class MarketSignalContext:
    regime: MarketRegime = MarketRegime.NORMAL
    risk: str = "Safe"
    bubble_confidence: float = 0.0
    ntf_side: NtfSide = NtfSide.NONE
    ntf_intensity: float = 0.0
    is_3rd_buy: bool = False
    bi_count: int = 0
    alpha_score: float = 0.0
    ma_status: Optional[str] = None
    price: float = 0.0
    pre_close: float = 0.0
    symbol: str = ""
    name: Optional[str] = None
    atr_stop: float = 0.0
    czsc_bottom: Optional[float] = None
    market: str = "CN"
    returns: Optional[pd.Series] = None
    lppl_days_to_tc: Optional[float] = None
```

### 枚举类型
- `MarketRegime`: `NORMAL`, `STRESSED`, `FROZEN` (`interfaces.py:8-12`)
- `NtfSide`: `NONE`, `SUPPORT`, `RESISTANCE` (`interfaces.py:15-19`)

### 工厂方法
```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "MarketSignalContext":  # interfaces.py:49
def to_dict(self) -> Dict[str, Any]:  # interfaces.py:79
```

## DecisionBrain 集成
Veto-Scoring 架构（`brain/fsm/fsm.py:173-656`）。

### 核心方法
```python
def make_decision(self, data_packet: Union[dict, MarketSignalContext]) -> Dict[str, Any]:  # fsm.py:481
```

### 决策流程
1. **否决检查**: `_check_veto_conditions(ctx)` (`fsm.py:250`)
   - `FROZEN` → `FORCE_WAIT`
   - `Danger` + 非 `SUPPORT` → `FORCE_EXIT`
2. **得分计算**: `_calculate_score(ctx)` (`fsm.py:262`)
   - `is_3rd_buy` → +CZSC 分
   - `MA20 > MA60` → +趋势分
   - `alpha_score > 阈值` → +Alpha 分
   - `ntf_side == SUPPORT` → +政策分
3. **卖出检查**: `_check_sell_conditions(ctx, score)` (`fsm.py:275`)
4. **状态确定**: `_determine_target_state(score, is_3rd_buy)` (`fsm.py:312`)
5. **买入阻断**: `_check_buy_blockers(ctx, score)` (`fsm.py:329`)
6. **执行买入**: `_execute_buy(ctx, score)` (`fsm.py:360`)

### 状态转换规则 (`fsm.py:414-422`)
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

### 状态持久化
- 状态文件: `data/state/fsm_state.json`
- 保存方法: `_save_state()` (`fsm.py:589`)
- 加载方法: `_load_state()` (`fsm.py:600+`)

## 降级处理
`_fallback_xxx_analysis()` 模式。

### TechnicalAnalysisService 示例 (`technical_service.py:145-179`)
```python
def _fallback_czsc_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
    """当 CZSC 引擎不可用时的降级分析"""
    # 使用基础 MA 均线和价格高低点进行分析
    required_cols = ["open", "high", "low", "close"]
    latest_close = df.iloc[-1]["close"]
    recent_highs = df["high"].tail(20).max()
    recent_lows = df["low"].tail(20).min()
    short_ma = df["close"].rolling(window=5).mean().iloc[-1]
    medium_ma = df["close"].rolling(window=20).mean().iloc[-1]
    # 返回基础分析结果
```

### 触发条件
- `ImportError` / `ModuleNotFoundError` (`czsc_analysis_engine.py:135`)
- `TECHNICAL_RECOVERABLE_ERRORS` (`czsc_analysis_engine.py:138`)

## 缓存策略
2 小时 TTL, memory + disk 双级。

### TTL 常量 (`constants.py:67-68`)
```python
CACHE_TTL_1HOUR = 3600
CACHE_TTL_2HOURS = 7200
```

### 缓存方法 (`technical_service.py:63-88`)
```python
def _generate_cache_key(self, prefix: str, **kwargs) -> str:
    sorted_params = sorted(kwargs.items())
    param_str = "_".join([f"{k}={v}" for k, v in sorted_params])
    return f"{prefix}:{param_str}"

def _get_cached_result(self, cache_key: str, use_disk: bool = False) -> Any:
    # 先查 memory_cache，再查 disk_cache
    # 命中 disk 时回填 memory

def _set_cached_result(self, cache_key: str, result: Any, use_disk: bool = False, ttl: Optional[int] = None) -> bool:
    # 同时写入 memory 和 disk
```

### 各引擎 TTL 配置
| 引擎 | TTL |
|------|-----|
| CZSC | `CACHE_TTL_2HOURS` (7200s) |
| LPPL | `CACHE_TTL_2HOURS` (7200s) |
| Macro | `CACHE_TTL_1HOUR` (3600s) |
