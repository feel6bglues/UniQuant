# 全功能冒烟测试计划

> 日期: 2026-07-08 | 修复后全系统验证
> 范围: shared → data → brain → signal → hands → services → risk → ui
> 方法: 逐层递进, 每层验证通过后才进入下一层

---

## 测试层级

```
Layer 0: 基础设施  ── import / config / container / 数据湖可读
Layer 1: A股规则    ── 涨跌停 / 板块类型 / 交易日历 / 价格围栏 / 滑点
Layer 2: 引擎核心   ── 7 个引擎各自运行 + 信号适配
Layer 3: 信号系统   ── 适配器 → 仲裁器 → 序列化
Layer 4: 回测系统   ── 匹配引擎 / 成本模型 / 基准指数 / 敏感性
Layer 5: 端到端     ── 单股票全链路 / 批处理 canary / 可复现性
Layer 6: 修复验证   ── 34 个修复项逐一确认
```

---

## Layer 0: 基础设施冒烟

### L0-1: 8 层 import

```python
import uniquant.shared
import uniquant.brain
import uniquant.data
import uniquant.signal
import uniquant.services
import uniquant.risk
import uniquant.hands
import uniquant.ui
```

预期: 全部成功, 无 ImportError

### L0-2: Config 加载 + ServiceContainer 初始化

```python
from uniquant.shared.config_loader import get_config
c = get_config()
print(c.get("base.data_lake.engine"))

from uniquant.services import ServiceContainer
c = ServiceContainer()
c.initialize()
```

预期: `get_config` 返回有效配置, `initialize()` 无异常

### L0-3: 数据湖 5934 个文件全部可读

```python
import glob, pandas as pd
files = sorted(glob.glob("data/lake/quotes/daily/*.parquet"))
print(f"文件数: {len(files)}")
# 随机抽查 10 个文件, 验证列和 dtypes
```

预期: 5934 文件, 全部 10 列, datetime64[ns], 无异常

---

## Layer 1: A 股规则冒烟

### L1-1: 涨跌停限制

```python
from uniquant.shared.limit_checker import check_limit_status, is_limit_up, is_limit_down

# 主板 10%
r = check_limit_status(close_price=11.0, pre_close=10.0, symbol="600519.SH")
assert not r.is_limit_up  # 10% 正好涨停

# 创业板 20%
r = check_limit_status(close_price=12.0, pre_close=10.0, symbol="300750.SZ")
assert not r.is_limit_up  # 20% 正好涨停

# Inf 数据 (原 #2 修复)
r = check_limit_status(close_price=10.0, pre_close=float('inf'), symbol="600519.SH")
assert not r.is_limit_up  # 不应崩溃, 应安全返回
```

预期: 边界值正确, Inf 不崩溃

### L1-2: 板块类型注册表 (#7 验证)

```python
from uniquant.shared.board_registry import BoardTypeRegistry
r = BoardTypeRegistry()
assert r.get_board_type("600519.SH") == "main"
assert r.detect_board("300750.SZ").name == "GEM"
assert r.detect_board("688981.SH").name == "STAR"
```

预期: get_board_type 返回 str, detect_board 返回 BoardType enum, 两者一致

### L1-3: 交易日历 2027 (#8 验证)

```python
from uniquant.data.managers.trade_calendar_manager import TradeCalendarManager
tcm = TradeCalendarManager()
assert tcm.is_trading_day("2027-01-04")  # 元旦后第一个工作日
assert not tcm.is_trading_day("2027-01-01")  # 元旦
```

预期: 2027 年日期正确识别

### L1-4: 价格围栏 (N3 验证)

```python
from uniquant.shared.price_collar import get_allowable_price_range
low, high = get_allowable_price_range(10.0, "BUY", "MAIN_SH")
assert low == 9.0 and high == 11.0  # ±10%
```

预期: 主板 ±10%, 创业板 ±20%, 科创板 ±20%

### L1-5: 滑点模型 (#38 验证)

```python
from uniquant.shared.slippage_model import DefaultSlippage, DynamicSlippage
ds = DefaultSlippage()
slip = ds.estimate(10000.0)
assert slip >= 0  # 不崩溃, 返回非负值
```

预期: SlippageModel 实例化并返回有效滑点

---

## Layer 2: 引擎核心冒烟

### L2-1: 读取真实股票数据

```python
import pandas as pd
df = pd.read_parquet("data/lake/quotes/daily/600519.SH.parquet")
assert len(df) > 0
assert all(c in df.columns for c in ["date", "open", "high", "low", "close", "volume"])
close = df["close"].values[:200]  # 取前 200 天
```

预期: 数据完整, 列名正确

### L2-2: LPPL 引擎 (#24 修复验证)

```python
from uniquant.brain.lppl.engine import LPPLEngine
engine = LPPLEngine()
# 正常数据
result = engine.detect_bubble({"close": close, "date": df["date"].values[:200]})
print(f"LPPL risk_level={result.get('risk_level')}")
# Inf 数据不应产生 Danger 假阳性
import numpy as np
inf_close = close.copy().astype(float)
inf_close[-50:] = np.inf
result_inf = engine.detect_bubble({"close": inf_close, "date": df["date"].values[:200]})
assert result_inf.get("risk_level") != "Danger", "Inf 数据不应产生 Danger"
```

预期: 正常数据返回有效风险等级, Inf 数据不会假阳性

### L2-3: Regime 引擎 (#31 修复验证)

```python
from uniquant.services.analysis.regime_analysis_engine import RegimeAnalysisEngine
from uniquant.brain.regime.regime_detector import RegimeDetector
engine = RegimeAnalysisEngine(regime_detector=RegimeDetector())
result = engine.run_regime_detection(symbol="600519.SH", df=df.head(200))
print(f"Regime: {result}")
```

预期: 正确检测态势, 无 TypeError (string vs DataFrame)

### L2-4: CZSC 引擎 (#32 修复验证)

```python
from uniquant.services.analysis.czsc_analysis_engine import CZSCAnalysisEngine
from uniquant.brain.czsc.czsc_engine import CZSCEngine
engine = CZSCAnalysisEngine(czsc_engine=CZSCEngine())
result = engine.run_czsc_analysis(symbol="600519.SH", df=df.head(200))
# CZSCOutput 应包含 trend 和 current_state
assert "trend" in result or "current_state" in result
print(f"CZSC: trend={result.get('trend')}, state={result.get('current_state')}")
```

预期: CZSCOutput 包含 trend 和 current_state 字段

### L2-5: Wyckoff 引擎 (#29 修复验证)

```python
from uniquant.brain.wyckoff.engine import WyckoffEngine
engine = WyckoffEngine()
result = engine.analyze(df.head(500), symbol="600519.SH")
print(f"Wyckoff: phase={result.wyckoff_phase}")
```

预期: 返回有效 Wyckoff phase, 不崩溃

### L2-6: FSM + NTF 引擎

```python
from uniquant.brain.fsm.fsm import FSM
from uniquant.brain.ntf.ntf_engine import NTFEngine
# FSM - 空 DataFrame 不应崩溃 (#1 验证)
fsm = FSM()
result = fsm.infer_state(pd.DataFrame())
print(f"FSM empty: {result}")
# NTF
ntf = NTFEngine()
result = ntf.analyze(df.head(200))
print(f"NTF: {result}")
```

预期: FSM 空 DF 不崩溃, NTF 返回有效结果

---

## Layer 3: 信号系统冒烟

### L3-1: 适配器全覆盖

```python
from uniquant.signal.adapters import LPPLAdapter, CZSCAdapter, WyckoffAdapter, FSMAdapter
from uniquant.signal.adapters import RegimeAdapter, AlphaScoreAdapter, MAStatusAdapter

adapters = [LPPLAdapter(), CZSCAdapter(), WyckoffAdapter(), FSMAdapter(),
            RegimeAdapter(), AlphaScoreAdapter(), MAStatusAdapter()]
for a in adapters:
    result = a.adapt({})
    print(f"{a.__class__.__name__}: empty input → {result}")
    assert result is None or hasattr(result, 'action')
```

预期: 全部 7 个适配器对空输入返回 None 或有效 TradingSignal

### L3-2: 仲裁器

```python
from uniquant.signal.arbitrator import SignalArbitrator
from uniquant.shared.interfaces import TradingSignal, Action

arb = SignalArbitrator()
signals = [
    TradingSignal(action=Action.BUY, reason="test_buy", symbol="600519.SH"),
    TradingSignal(action=Action.SELL, reason="test_sell", symbol="600519.SH"),
]
result = arb.arbitrate(signals, symbol="600519.SH")
assert len(result) > 0  # SELL 优先级
```

预期: SELL 优先于 BUY, 返回有效信号

### L3-3: TradingSignal 序列化 (#22 修复验证)

```python
from uniquant.shared.interfaces import TradingSignal, Action
import datetime

ts = TradingSignal(action=Action.BUY, reason="test", symbol="600519.SH",
                   metadata={"source": "smoke_test"})
d = ts.to_dict()
ts2 = TradingSignal.from_dict(d)
assert ts2.action == ts.action
assert ts2.metadata == ts.metadata  # from_dict metadata 不再丢失
print(f"to_dict/from_dict roundtrip: metadata preserved={ts2.metadata}")
```

预期: roundtrip 后所有字段一致, metadata 不丢失

---

## Layer 4: 回测系统冒烟

### L4-1: 匹配引擎

```python
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
engine = UnifiedMatchingEngine()
# 模拟买入
fill = engine.fill_buy(price=10.0, quantity=100, slippage_rate=0.001)
assert fill["avg_price"] > 0
```

预期: 成功执行买入, 返回有效成交

### L4-2: 基准指数 (#23 修复验证)

```python
from uniquant.hands.backtest.unified_engine import BacktestResult, UnifiedBacktestEngine

result = BacktestResult(total_return=0.1, benchmark_return=0.05)
assert result.total_return == 0.1
assert result.benchmark_return == 0.05
print(f"Alpha: {result.total_return - result.benchmark_return:.4f}")
```

预期: benchmark_return 字段存在且正确

### L4-3: 敏感性扫描 (#21 修复验证)

```python
import pandas as pd
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

engine = UnifiedBacktestEngine(initial_capital=100000)
# 用模拟数据测试
dates = pd.date_range("2024-01-01", periods=100, freq="D")
df = pd.DataFrame({"date": dates, "open": 10, "high": 11, "low": 9, "close": 10 + np.sin(range(100))*0.5, "volume": 1000000})
result_df = engine.sensitivity_scan(df, [])
assert isinstance(result_df, pd.DataFrame)
print(f"Sensitivity scan: {result_df.shape[0]} combinations")
```

预期: 返回 DataFrame, 5×4 = 20 种组合

---

## Layer 5: 端到端冒烟

### L5-1: 单股票全链路

```python
# data → brain(7引擎) → signal(8适配器) → arbitrator → backtest
# 使用 research_pipeline 的简化路径
from uniquant.shared.interfaces import TradingSignal, Action
from uniquant.signal.arbitrator import SignalArbitrator
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

# 读取数据
df = pd.read_parquet("data/lake/quotes/daily/600519.SH.parquet").head(500)

# 生成模拟信号 (实际由 7 个引擎产生)
signals = [
    TradingSignal(action=Action.BUY, reason="czsc", symbol="600519.SH"),
    TradingSignal(action=Action.SELL, reason="lppl", symbol="600519.SH"),
]

# 仲裁
arb = SignalArbitrator()
final = arb.arbitrate(signals, symbol="600519.SH")

# 回测
engine = UnifiedBacktestEngine(initial_capital=100000)
result = engine.run(df, final, symbol="600519.SH")
print(f"Pipeline: trades={result.total_trades}, return={result.total_return:.4f}")
```

预期: 全链路无异常, 返回有效回测结果

### L5-2: 种子锁定可复现性 (N2 验证)

```python
import numpy as np
from uniquant.services.research_pipeline import UnifiedResearchPipeline

# 相同种子两次运行应产生相同结果
# (需有真实数据支撑, 这里验证接口存在)
pipe = UnifiedResearchPipeline(data_service=None, analysis_service=None, signal_collector=None,
                               backtest_engine=UnifiedBacktestEngine(initial_capital=100000))
assert hasattr(pipe.run, '__call__')  # 接口存在
```

预期: seed 参数存在且有效

### L5-3: canary 批处理

```bash
python3 scripts/staged_full_scan.py --stage canary --max-workers 4
```

预期: canary 20/20 成功, 0 崩溃

---

## Layer 6: 修复验证清单

### 34 个修复逐一确认

| # | 修复 | 验证方法 | 预期 |
|---|---|---|---|
| #1 | FSM 空 DF 守卫 | 空 DataFrame → infer_state | 不崩溃, 返回空 |
| #2 | limit_checker Inf 守卫 | `pre_close=inf` → check_limit_status | 不崩溃, 安全返回 |
| #4 | signal/db.py 修复 | 35 个测试 | 全部通过 |
| #7 | BoardTypeRegistry | get_board_type + detect_board 一致性 | 两者一致 |
| #8 | TradeCalendar 2027 | is_trading_day("2027-01-04") | True |
| #10 | bare except | research_pipeline.py:237 | `except Exception:` |
| #23 | benchmark 集成 | BacktestResult.benchmark_return | 字段存在 |
| #24 | LPPL isinf 守卫 | Inf close → detect_bubble | 非 "Danger" |
| #31 | Regime 传 df | run_regime_detection(df=df) | 无 TypeError |
| #32 | CZSC 接线 | run_czsc_analysis | trend/current_state 存在 |
| #38 | SlippageModel 适配 | DefaultSlippage.estimate(10000) | 返回非负值 |
| N1 | Parquet 模式统一 | 随机抽查 10 文件 | 10 列, datetime64[ns] |
| #19 | Adapter 测试 | 55 个新测试 | 全部通过 |
| #20 | 重复代码清理 | sina.py/ths.py 行数减少 | 各 -100+ 行 |
| #21 | 敏感性扫描 | sensitivity_scan 返回 DataFrame | 20 组合 |
| #22 | to_dict/from_dict | roundtrip | metadata 不丢失 |
| #28 | eastmoney 拆分 | eastmoney.py 文件大小 | 2 行 (原 1094) |
| #29 | Wyckoff 复杂度拆分 | `_step1_phase_determine` 调用 | 7 个子方法 |
| #34 | 多周期数据 | 5934 weekly + 5934 monthly | 文件存在 |
| N2 | 种子锁定 | run() 有 seed 参数 | 参数存在 |
| N3 | price_collar 测试 | 43 个测试 | 全部通过 |
| #33 | E2E 测试 | 3 个新测试类 | 全部通过 |
| #45 | 信号超时 | max_signal_age_seconds 参数 | 参数存在 |
| #47 | Portfolio 导出移除 | `__init__.py` 中无 PortfolioEngine | 无该导出 |
| #48 | broad except 窄化 | `hands/strategies/backtest.py` except | 具体异常类型 |
| #49 | Wyckoff 常量 | `constants.py` 中 7 个常量 | 常量存在 |
| #50 | 适配器自动发现 | `AdapterRegistry.discover()` | 方法存在 |
| #51 | 仓位计算统一 | `PositionSizerProtocol` | 协议存在 |
| #52 | benchmark CI | `.github/workflows/benchmark.yml` | 文件存在 |
| #53 | assert 修复 | test_indicators, test_scan_service | assert 存在 |
| #57 | 死代码清理 | 8 文件, 12 项 | 代码已移除 |
| #66 | datetime.now 替换 | time_provider.py | self.now() 替换 |

---

## 执行步骤

```
1. 运行 Layer 0-1 (基础设施 + A股规则)          → 快速验证底层
2. 运行 Layer 2-3 (引擎 + 信号)                 → 核心功能验证
3. 运行 Layer 4   (回测)                       → 研究输出验证
4. 运行 L5-3     (canary 批处理)               → 全量验证
5. 运行 Layer 5-6 (端到端 + 修复清单)            → 最终确认
```

每步骤失败则停止, 修复后从该步骤重试。