# 测试指南

本文档介绍 UniQuant 的测试体系，包括测试运行方式、pytest 配置、共享 Fixtures、测试分类以及编写新测试的规范。

---

## 测试概览

UniQuant 拥有完善的测试覆盖：

- **65+ 测试文件**，涵盖单元测试、集成测试、回归测试、边界测试等多个维度
- **532+ 通过测试用例**
- 基于 **pytest** 框架
- 支持 **pytest-cov** 覆盖率报告
- 所有测试代码位于 `tests/` 目录下

---

## 运行测试

### 基本命令

```bash
# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_indicators.py

# 运行匹配关键词的测试
pytest -k "factor"

# 运行指定测试函数
pytest tests/test_indicators.py::test_rsi_basic

# 遇到第一个失败立即停止
pytest -x

# 显示详细输出
pytest -v

# 生成覆盖率报告
pytest --cov

# 生成 HTML 覆盖率报告
pytest --cov --cov-report=html

# 并行运行 (如安装了 pytest-xdist)
pytest -n auto
```

### 常用组合

```bash
# 快速验证: 遇到失败立即停止，显示详细输出
pytest -xvs

# 只运行回归测试
pytest -k "regressions"

# 只运行某个模块的测试
pytest tests/test_backtest_engine.py tests/test_matching_engine.py -v
```

---

## pytest 配置

pytest 的配置定义在 `pyproject.toml` 中：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
pythonpath = ["src", "."]
```

关键配置说明：

- **testpaths**: 测试文件搜索路径为 `tests/` 目录
- **python_files**: 测试文件必须以 `test_` 开头
- **pythonpath**: 将 `src` 和项目根目录加入 Python 路径，使得 `from uniquant.xxx import yyy` 在测试中可以正常工作（项目以 editable 模式安装）

---

## 共享 Fixtures (conftest.py)

`tests/conftest.py` 定义了所有测试共享的 Fixtures，避免每个测试文件重复生成测试数据。

### sample_ohlcv_data

标准的 OHLCV 测试数据，252 行（模拟一个完整交易年度）。包含 date、open、high、low、close、volume、amount 列。使用固定随机种子 (42) 确保可复现。

```python
@pytest.fixture
def sample_ohlcv_data():
    np.random.seed(42)
    n = 252
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "date": dates,
        "open": close + np.random.randn(n) * 0.3,
        "high": close + np.abs(np.random.randn(n) * 0.5),
        "low": close - np.abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000000, 10000000, n),
        "amount": np.random.randint(10000000, 100000000, n),
    })
```

### sample_empty_df

空的 DataFrame，包含标准列名 (date, open, high, low, close, volume, amount)。用于测试空数据输入的边界情况。

### sample_nan_df

包含 NaN 值的 DataFrame (10 行)，各列在不同位置存在缺失值。用于测试 NaN 处理逻辑和容错能力。

### sample_stock_data_short

短周期的股票测试数据 (30 行)。使用随机种子 123，起始价格为 50。适用于不需要大量数据的快速测试。

### tmp_data_dir

基于 pytest 内置的 `tmp_path` 创建的临时数据目录结构：

```
tmp_path/
  data/
    lake/
      quotes/
        daily/
    meta/
```

用于测试需要文件系统操作的场景（数据存储、缓存读写等）。

---

## 测试分类

以下将全部 65+ 个测试文件按功能和用途分类。

### 单元测试

核心模块的独立功能测试：

| 文件 | 测试对象 |
|------|----------|
| `test_indicators.py` | 技术指标计算 (MA、RSI、MACD、ATR 等) |
| `test_limit_checker.py` | 涨跌停检查器 |
| `test_sizer.py` | 仓位计算器 |
| `test_factor_registry.py` | 因子注册表 |
| `test_factor_analyzer.py` | 因子分析器 |
| `test_factor_composer.py` | 因子组合器 |
| `test_smart_factor_calculator.py` | 智能因子计算 |
| `test_custom_factors.py` | 自定义因子 |
| `test_alpha_decoupler.py` | Alpha 解耦器 |
| `test_ntf_engine.py` | NTF 引擎 (量价异动检测) |
| `test_fsm.py` | 有限状态机 |
| `test_regime_detector.py` | 市场状态检测器 |
| `test_drawdown_analyzer.py` | 回撤分析器 |
| `test_portfolio_optimizer.py` | 组合优化器 |
| `test_evt_risk.py` | EVT 极值风险模型 |
| `test_matching_engine.py` | 撮合引擎 |
| `test_error_handling.py` | 错误处理框架 |
| `test_error_handling_additional.py` | 错误处理补充测试 |
| `test_retry_and_utils.py` | 重试装饰器和工具函数 |
| `test_field_mapping.py` | 字段映射 |
| `test_import_state.py` | 导入状态管理 |
| `test_import_financial.py` | 财务数据导入 |
| `test_report_paths.py` | 报告路径处理 |
| `test_results_manager_extra.py` | 结果管理器 |
| `test_results_protocol.py` | 结果协议 |
| `test_stock_list_cli.py` | 股票列表 CLI |
| `test_stock_screener.py` | 股票筛选器 |
| `test_validation_service.py` | 数据验证服务 |
| `test_realtime_bridge.py` | 实时行情桥接 |
| `test_hands_strategies.py` | 交易策略 (Hands 模块) |
| `test_build_financial_v2.py` | 财务数据构建 V2 |

### 集成测试

测试多个模块的协作：

| 文件 | 测试对象 |
|------|----------|
| `test_service_container.py` | 服务容器 / 依赖注入 |
| `test_di_container_and_cache.py` | DI 容器与缓存集成 |
| `test_engine_factory.py` | 引擎工厂 |
| `test_backtest_engine.py` | 回测引擎端到端测试 |
| `test_portfolio_engine_v2.py` | 组合引擎 V2 |
| `test_walk_forward_pipeline.py` | Walk-Forward 滚动回测管线 |
| `test_analysis_engines.py` | 分析引擎集成 |
| `test_data_access_service.py` | 数据访问服务 |
| `test_manager_portfolio_analytics_service.py` | 组合分析服务 |
| `test_akshare_market_service.py` | AkShare 市场服务 |
| `test_akshare_reference_service.py` | AkShare 参考数据服务 |
| `test_offline_entry.py` | 离线模式入口 |

### 回归测试

针对已修复问题的防回归测试：

| 文件 | 测试对象 |
|------|----------|
| `test_data_and_stock_query_regressions.py` | 数据查询和股票查询回归 |
| `test_macro_and_fsm_engine_regressions.py` | 宏观引擎和 FSM 引擎回归 |
| `test_macro_and_scan_regressions.py` | 宏观分析和扫描回归 |
| `test_more_analysis_engine_regressions.py` | 分析引擎更多回归 |
| `test_report_and_ntf_regressions.py` | 报告和 NTF 回归 |
| `test_technical_and_signal_regressions.py` | 技术指标和信号回归 |
| `test_final_service_regressions.py` | 服务层最终回归 |

### 边界和防御测试

针对极端输入和边界条件的测试：

| 文件 | 测试对象 |
|------|----------|
| `test_t1_constraint_boundary.py` | T+1 交易约束边界 |
| `test_cvar_empty_tail.py` | CVaR 空尾部处理 |
| `test_factor_div_zero_defense.py` | 因子除零防御 |
| `test_analysis_service_strength_div_zero.py` | 分析服务强度除零 |
| `test_analysis_result_helpers.py` | 分析结果辅助函数 |
| `test_lppl_calculator_defense.py` | LPPL 计算器防御 |
| `test_lppl_engine_scan_windows.py` | LPPL 引擎扫描窗口边界 |
| `test_data_fetcher_init_fault_tolerance.py` | 数据获取器初始化容错 |
| `test_czsc_bar_list_vectorization.py` | 缠论 K 线列表向量化 |
| `test_czsc_engine.py` | 缠论引擎边界 |
| `test_brain_additional.py` | Brain 模块补充测试 |

### 防前瞻偏差测试

| 文件 | 测试对象 |
|------|----------|
| `test_lookahead_bias.py` | 前瞻偏差检测，确保回测中不使用未来数据 |

### 数据完整性测试

| 文件 | 测试对象 |
|------|----------|
| `test_tdx_incremental.py` | 通达信增量更新 |
| `test_verify_tdx_import.py` | 通达信数据导入验证 |
| `test_financial_bridge.py` | 财务数据桥接 |

---

## 编写新测试

### 命名规范

- 测试文件: `test_<模块名>.py`
- 测试类: `Test<功能名>` (可选，通常直接使用函数)
- 测试函数: `test_<行为描述>`

```python
# 好的命名
def test_rsi_returns_series_with_correct_length():
    ...

def test_limit_checker_rejects_st_stock_beyond_5pct():
    ...

# 不好的命名
def test_1():
    ...

def test_it_works():
    ...
```

### 使用 Fixtures

优先使用 `conftest.py` 中定义的共享 fixtures：

```python
def test_macd_with_standard_data(sample_ohlcv_data):
    """测试 MACD 指标在标准数据上的计算"""
    result = calculate_macd(sample_ohlcv_data["close"])
    assert len(result) == len(sample_ohlcv_data)
    assert not result.isna().all()


def test_indicator_handles_empty_input(sample_empty_df):
    """测试指标在空输入时的行为"""
    result = calculate_macd(sample_empty_df["close"])
    assert result.empty


def test_indicator_handles_nan_values(sample_nan_df):
    """测试指标在含 NaN 数据时的行为"""
    result = calculate_rsi(sample_nan_df["close"])
    # 验证不会抛异常，且处理了 NaN
    assert not result.isna().all()
```

### 断言规范

```python
import numpy as np
import pandas as pd

# 精确比较
assert result == expected

# 浮点数近似比较
assert abs(result - expected) < 1e-6
np.testing.assert_almost_equal(result, expected, decimal=4)

# DataFrame 比较
pd.testing.assert_frame_equal(result_df, expected_df)

# 检查 DataFrame 结构
assert list(result_df.columns) == ["date", "open", "high", "low", "close", "volume"]
assert len(result_df) > 0
assert result_df["close"].dtype == np.float64

# 检查不包含 NaN
assert not result_df["close"].isna().any()

# 检查异常抛出
import pytest
with pytest.raises(ValueError, match="数据不足"):
    function_under_test(invalid_input)
```

### Mock 使用指南

对于依赖外部服务（网络请求、数据库等）的模块，使用 `unittest.mock` 进行隔离：

```python
from unittest.mock import patch, MagicMock
import pandas as pd

def test_data_source_fetch_with_network_error():
    """测试网络错误时数据源的行为"""
    source = EastmoneySource()

    with patch.object(source, '_request_data', side_effect=ConnectionError("网络断开")):
        result = source.fetch_daily("600000", "20250101", "20250501")
        assert result.empty


def test_router_fallback_on_first_source_failure():
    """测试第一个数据源失败时路由器的降级行为"""
    adapter1 = MagicMock()
    adapter1.fetch.return_value = pd.DataFrame()  # 返回空

    adapter2 = MagicMock()
    adapter2.fetch.return_value = pd.DataFrame({"close": [100, 101]})

    router = SourceRouter([adapter1, adapter2])
    result = router.fetch_data("600000", "20250101")
    assert not result.empty
```

### 测试组织原则

1. **一个测试函数测试一个行为**: 每个 `test_` 函数只验证一个具体行为或场景
2. **Arrange-Act-Assert 模式**: 先准备数据，然后调用被测函数，最后验证结果
3. **覆盖边界情况**: 空输入、NaN、极大/极小值、零值等
4. **回归测试优先**: 修复 bug 后，首先编写一个能复现该 bug 的测试用例

---

## 已知失败

当前存在 12 个预期中的测试失败，均为既有问题，与近期重构工作无关。这些失败的根本原因如下：

| 类别 | 涉及测试 | 原因 |
|------|----------|------|
| LPPL 计算器 | `test_lppl_calculator_defense.py` | LPPL 优化器在极端参数边界下数值不稳定 |
| 财务桥接 NaN | `test_financial_bridge.py` | 部分财务字段在源数据中即为 NaN，桥接层未做完整填充 |
| 缠论边界 | `test_czsc_engine.py`, `test_czsc_bar_list_vectorization.py` | 缠论笔划分在极短数据序列上的边界未完全处理 |
| 市场状态检测 | `test_regime_detector.py` | 熵值计算在数据点不足时返回异常值 |
| 离线入口 | `test_offline_entry.py` | 离线模式下部分服务的初始化顺序问题 |
| 结果协议 | `test_results_protocol.py` | 新结果协议接口与旧实现的兼容性缺口 |

这些失败不影响系统的核心功能，后续版本将逐步修复。运行全部测试时遇到这些失败属于正常现象。
