# 快速上手

本指南将帮助你从零开始安装 UniQuant、获取数据、运行分析和回测。

## 环境准备

UniQuant 需要 Python 3.12 或更高版本。推荐使用虚拟环境进行安装。

```bash
# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate    # Linux / macOS
# .venv\Scripts\activate     # Windows

# 安装 UniQuant 及全部可选依赖
pip install -e ".[all]"
```

`[all]` 会同时安装 tdx（通达信）、baostock、curl-cffi、weasyprint（报告导出）和 py-mini-racer（JS 引擎）等可选组件。如果你只需要核心功能，可以直接执行 `pip install -e .`。

安装完成后，验证是否成功：

```bash
python -c "import uniquant; print('UniQuant 安装成功')"
```

## 目录结构

```
UniQuant/
├── config/              # 配置文件 (config.yaml, trading.yaml 等)
├── data/                # 数据湖、缓存、报告
├── scripts/             # 数据下载与更新脚本
├── tests/               # 测试用例
└── src/uniquant/        # 核心源码
    ├── brain/           # 决策引擎 (FSM, Alpha, 信号融合)
    ├── data/            # 数据获取、数据湖、数据管线
    ├── hands/           # 回测引擎、策略执行
    ├── risk/            # 风险计算 (VaR, CVaR, 回撤分析)
    ├── services/        # 服务容器与分析引擎工厂
    ├── shared/          # 常量、异常、成本模型、工具
    ├── signal/          # 技术指标与因子计算
    └── ui/              # Streamlit 仪表盘
```

## 第一步: 配置数据源

编辑 `config/config.yaml`，根据你的环境设置数据路径：

```yaml
base:
  data_lake:
    path: "data/lake"
    compression: "snappy"
    engine: "duckdb"

  # 通达信本地数据路径（如不使用可忽略）
  tdx:
    path: "/home/your_user/.local/share/tdxcfv/drive_c/tc"

cache:
  global:
    enabled: true
    path: "data/cache"
    max_age: 7        # 缓存保留天数
```

UniQuant 内置五个数据源，按优先级依次尝试：

1. **TDX (通达信)** -- 本地数据，速度最快
2. **Baostock** -- 免费 A 股历史数据
3. **Sina (新浪财经)** -- 在线 K 线数据
4. **THS (同花顺)** -- 在线行情数据
5. **Tencent (腾讯财经)** -- 在线行情数据

任何单个数据源初始化失败不会影响其他数据源。系统会自动路由到可用的数据源。

## 第二步: 获取数据

`DataFetcher` 是数据获取的统一入口。以下示例演示如何获取一只股票的日线数据：

```python
from uniquant.data.data_fetcher import DataFetcher

# 初始化数据获取器
fetcher = DataFetcher(data_dir="./data")

# 获取平安银行前复权日线数据
df = fetcher.fetch_stock_daily(
    symbol="000001",
    start_date="2024-01-01",
    end_date="2024-12-31",
    adjust="qfq",           # qfq=前复权, hfq=后复权, ""=不复权
)
print(df.head())
# 输出列: date, open, high, low, close, volume, amount, ...

# 批量获取多只股票
symbols = ["000001", "600036", "601318"]
data = fetcher.fetch_stocks_daily(symbols, "2024-01-01", "2024-12-31")
for sym, df in data.items():
    print(f"{sym}: {len(df)} 条记录")

# 获取指数数据
index_df = fetcher.fetch_index_daily("000300.SH", "2024-01-01", "2024-12-31")
```

此外，项目 `scripts/` 目录下提供了批量数据下载脚本：

- `download_baostock_factors.py` -- 下载 Baostock 因子数据
- `update_daily_data_akshare.py` -- 使用 AkShare 更新日线数据

## 第三步: 初始化服务容器

`ServiceContainer` 是 UniQuant 的依赖注入容器，以 DAG 拓扑初始化所有服务，无循环依赖：

```
StorageManager -> MarketDataReader -> DataService -> AnalysisService
     |                                              |
TradeCalendarManager                     AnalysisEngineFactory
     |                                       |
CacheCoordinator                        FsmAnalysisEngine
                                        CzscAnalysisEngine
                                        LpplAnalysisEngine
                                        RegimeAnalysisEngine
                                        ReportGeneratorEngine
```

使用方式：

```python
from uniquant.services.service_container import ServiceContainer

# 获取单例容器并初始化
container = ServiceContainer.instance()
container.initialize()

# 获取已注册的服务
data_service = container.get("data_service")
engine_factory = container.get("engine_factory")
calendar = container.get("calendar")

# 通过引擎工厂执行分析
# engine_factory 内部封装了 FSM、CZSC、LPPL、Regime 等分析引擎
```

`ServiceContainer.initialize()` 会按顺序创建以下组件：

1. `StorageManager` -- 数据湖读写
2. `TradeCalendarManager` -- 交易日历管理
3. `CacheCoordinator` -- 缓存协调
4. `StockQueryService` -- 股票查询
5. `DataService` -- 数据服务（依赖上述组件）
6. `AnalysisEngineFactory` -- 分析引擎工厂（依赖 DataService）

## 第四步: 运行回测

`BacktestEngine` 支持单资产回测、滚动窗口回测、Walk-forward 验证和压力测试。以下是一个简单的均线交叉策略回测：

```python
import pandas as pd
from uniquant.hands.backtest.engine import BacktestEngine
from uniquant.data.data_fetcher import DataFetcher

# 获取数据
fetcher = DataFetcher(data_dir="./data")
df = fetcher.fetch_stock_daily("600036", "2023-01-01", "2024-12-31", adjust="qfq")

# 定义均线交叉信号生成器
def ma_cross_signal(df_slice: pd.DataFrame, idx: int, context: dict) -> dict:
    """
    双均线交叉策略:
    - 短期均线(5日)上穿长期均线(20日) -> 买入
    - 短期均线下穿长期均线 -> 卖出
    """
    if len(df_slice) < 20:
        return {"action": "HOLD", "reason": "数据不足"}

    close = df_slice["close"]
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()

    if pd.isna(ma5.iloc[-1]) or pd.isna(ma20.iloc[-1]):
        return {"action": "HOLD", "reason": "均线计算中"}

    # 金叉买入
    if len(ma5) >= 2 and ma5.iloc[-1] > ma20.iloc[-1] and ma5.iloc[-2] <= ma20.iloc[-2]:
        return {"action": "BUY", "reason": "MA5上穿MA20"}

    # 死叉卖出
    if len(ma5) >= 2 and ma5.iloc[-1] < ma20.iloc[-1] and ma5.iloc[-2] >= ma20.iloc[-2]:
        return {"action": "SELL", "reason": "MA5下穿MA20"}

    return {"action": "HOLD", "reason": "无信号"}

# 创建回测引擎并运行
engine = BacktestEngine(
    initial_capital=100000.0,      # 初始资金 10万
    commission_rate=0.0003,        # 佣金 万3
    stamp_duty_rate=0.001,         # 印花税 千1 (仅卖出)
    slippage_rate=0.001,           # 滑点 千1
    min_commission=5.0,            # 最低佣金 5元
)

result = engine.run_backtest(
    df=df,
    signal_generator=ma_cross_signal,
    symbol="600036",
    position_size=1000,            # 每次交易 1000 股
)

# 查看回测结果
print(f"总收益率: {result.total_return:.2%}")
print(f"年化收益率: {result.annualized_return:.2%}")
print(f"最大回撤: {result.max_drawdown:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
print(f"胜率: {result.win_rate:.2%}")
print(f"盈亏比: {result.profit_factor:.2f}")
print(f"总交易次数: {result.total_trades}")
```

## 第五步: 查看仪表盘

UniQuant 内置了一个 Streamlit 仪表盘，用于可视化分析结果和回测表现：

```bash
streamlit run src/uniquant/ui/dashboard.py
```

仪表盘默认运行在 8504 端口，在浏览器中打开 `http://localhost:8504` 即可查看。

## 下一步

掌握了基本流程之后，可以继续阅读以下详细指南：

- [回测指南](backtest.md) -- 回测模式、组合回测、压力测试、交易成本配置
- 因子指南 -- 自定义因子、因子注册与组合
- 策略指南 -- FSM 状态机策略、信号融合、仓位管理
- 数据源指南 -- 多数据源配置、数据湖管理、数据质量监控
- 配置指南 -- config.yaml 完整配置项说明
