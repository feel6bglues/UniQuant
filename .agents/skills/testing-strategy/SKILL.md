# 测试策略

## 何时使用
写新测试时；修测试时；验证代码改动时；理解测试基础设施时。

## 当前状态

| 指标 | 值 |
|------|-----|
| 测试文件数 | 10（不含 conftest.py） |
| 可导入文件数 | 1（test_engine_factory.py，其余需 uniquant/czsc 包已安装） |
| 测试函数数 | 65 |
| 测试类数 | 10 |

## 可运行测试清单

| 文件 | 可导入 | 依赖 | 风格 |
|------|--------|------|------|
| `test_engine_factory.py` | ✅ 是（全部 mock） | 仅 stdlib + pytest | class-based |
| `test_czsc_engine.py` | ❌ 否 | `uniquant.brain.czsc.czsc_engine.CZSCEngine` | class-based |
| `test_czsc_bar_list_vectorization.py` | ❌ 否 | `czsc.RawBar`, `czsc.Freq`, `CZSCEngine` | class-based |
| `test_ntf_engine.py` | ❌ 否 | `uniquant.brain.ntf.ntf_engine.NTFEngine` | class-based |
| `test_regime_detector.py` | ❌ 否 | `uniquant.brain.regime.regime_detector.RegimeDetector` | class-based |
| `test_brain_additional.py` | ❌ 否 | `NTFEngine`, `RegimeDetector` | class-based |
| `test_more_analysis_engine_regressions.py` | ❌ 否 | `CzscAnalysisEngine`, `LpplAnalysisEngine`, `RegimeAnalysisEngine` | function-based |
| `test_macro_and_scan_regressions.py` | ❌ 否 | `MacroAnalysisService`, `ScanConfig`, `ScanPipeline` | function-based |
| `test_report_and_ntf_regressions.py` | ❌ 否 | `NtfAnalysisEngine`, `ReportGeneratorEngine` | function-based |
| `test_technical_and_signal_regressions.py` | ❌ 否 | `SignalAnalysisService`, `TechnicalAnalysisService` | function-based |

## pytest 配置

配置文件位置：`docs/pyproject.toml`（注意：项目根目录无 pyproject.toml）

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

**关键说明**：
- `testpaths` = `["tests"]`
- `python_files` = `["test_*.py"]`
- `pythonpath` **未设置**（docs/development/testing.md 文档声称有 `pythonpath = ["src", "."]`，但实际 pyproject.toml 中不存在此配置）
- 运行测试前需要先 `pip install -e .` 或手动将 `src/` 加入 PYTHONPATH

## conftest.py fixtures

实际 conftest.py（`tests/conftest.py`）仅定义 2 个 fixture：

| fixture | 作用域 | 返回类型 | 说明 |
|---------|--------|----------|------|
| `sample_ohlcv_data` | function | `pd.DataFrame` | 252 行 OHLCV，无随机种子，无 amount 列 |
| `sample_wyckoff_data` | function | `pd.DataFrame` | 400 行 OHLCV，无随机种子 |

**⚠️ 与文档不一致**：`docs/development/testing.md` 声称存在 `sample_empty_df`、`sample_nan_df`、`sample_stock_data_short`、`tmp_data_dir` 等 fixture，但实际 conftest.py 中均不存在。文档还声称使用 `np.random.seed(42)` 和包含 `amount` 列，实际代码均无。

**当前无测试文件使用 conftest.py 中的 fixture**——所有测试文件自行构造测试数据。

## 测试模式

### class-based 模式
文件：`test_engine_factory.py`、`test_czsc_engine.py`、`test_czsc_bar_list_vectorization.py`、`test_ntf_engine.py`、`test_regime_detector.py`、`test_brain_additional.py`

```python
class TestEngineFactory:
    def test_initialization(self, factory):
        assert factory._engines == {}
```

特征：`class TestXxx` + `@pytest.fixture` 定义局部 fixture + `self` 参数。

### function-based 模式（回归测试）
文件：`test_more_analysis_engine_regressions.py`、`test_macro_and_scan_regressions.py`、`test_report_and_ntf_regressions.py`、`test_technical_and_signal_regressions.py`

```python
def test_regime_engine_returns_failed_result_on_attribute_error(monkeypatch):
    engine = RegimeAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))
    ...
    assert result["status"] == "failed"
```

特征：顶层 `def test_xxx()` + 模块级辅助函数 `_sample_ohlc_df()` + monkeypatch。

### mock 模式
- `unittest.mock.patch` / `MagicMock`：`test_engine_factory.py`（mock 整个 importlib.import_module）、`test_czsc_engine.py`（patch.object）
- `monkeypatch.setattr`：回归测试文件中广泛使用，用于注入运行时错误

### stub 模式
回归测试文件定义轻量 stub 类替代真实依赖：

```python
class _DummyOrchestrator:
    def __init__(self, df): ...
class _DummyLake:
    def read_data(self, symbol, ...): ...
class _DummyDataService:
    def __init__(self, df): ...
```

出现在：`test_more_analysis_engine_regressions.py`、`test_macro_and_scan_regressions.py`、`test_report_and_ntf_regressions.py`。

## 常见失败原因

| 错误 | 原因 | 修复 |
|------|------|------|
| `ModuleNotFoundError: No module named 'uniquant'` | 包未安装，且未设置 pythonpath | `pip install -e .` 或 `export PYTHONPATH=src:$PYTHONPATH` |
| `ModuleNotFoundError: No module named 'czsc'` | czsc 第三方库未安装 | `pip install czsc`（仅 `test_czsc_bar_list_vectorization.py` 直接依赖） |
| `conftest.py` fixture 缺失 | 文档与实际 conftest 不一致 | 以实际 conftest.py 为准，不要依赖文档描述的不存在 fixture |
| 随机数据不可复现 | conftest fixtures 未设置 `np.random.seed()` | 测试中自行设置种子，或使用确定性数据构造 |

## 推荐测试命令

```bash
# 唯一确定可运行的测试（无需 uniquant 包安装）
pytest tests/test_engine_factory.py -xvs

# 安装项目后运行全部测试
pip install -e ".[dev]"
pytest -xvs

# 只运行回归测试
pytest -k "regressions" -v

# 只运行某个引擎的测试
pytest tests/test_czsc_engine.py -v
```

## 覆盖缺口

以下源模块完全没有测试覆盖：

**brain 层**：
- `uniquant.brain.fsm.fsm` — 有限状态机
- `uniquant.brain.lppl.engine` — LPPL 引擎（仅有 analysis 层回归测试）
- `uniquant.brain.lppl.numba_optimizer` — LPPL numba 优化器

**risk 层**：
- `uniquant.risk.drawdown_analyzer` — 回撤分析器

**shared 层**（全部无测试）：
- `cache/` — 缓存后端、工厂、接口
- `config_loader`、`constants`、`env_config` — 配置
- `cost_model`、`slippage_model`、`optimal_params` — 模型
- `di_container`、`service_container` — 依赖注入
- `error_handling`、`errors`、`exceptions` — 错误处理
- `import_state`、`interfaces`、`limit_checker`、`limits`、`logger_factory`、`retry_decorator`、`utils`

**ui 层**：
- `uniquant.ui.dashboard`、`uniquant.ui.health_check`

## 写新测试的规范

1. **fixture 使用**：当前 conftest.py 仅有 `sample_ohlcv_data` 和 `sample_wyckoff_data`，且无测试使用它们。建议在测试文件内自行构造确定性数据（参考回归测试的 `_sample_ohlc_df()` 模式）。

2. **mock 策略**：
   - 隔离外部依赖用 `unittest.mock.patch` / `MagicMock`
   - 替换 orchestrator/lake/data_service 用轻量 stub 类（`_DummyOrchestrator` 等）
   - 注入运行时错误用 `monkeypatch.setattr`

3. **断言风格**：
   - 直接 `assert result["status"] == "failed"`
   - 字符串包含检查 `"bad regime engine" in result["error"]`
   - 身份检查 `e1 is e2`
   - 属性存在检查 `hasattr(factory, "fsm")`

4. **命名规范**：
   - 文件：`test_<模块名>.py`
   - 类：`Test<功能名>`
   - 函数：`test_<行为描述>`
