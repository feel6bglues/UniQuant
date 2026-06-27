# 性能基准 (Performance Benchmarks)

> 基准环境: Linux | Python 3.12.3 | Intel | 2026-06-17
> 所有测试在 `pip install -e ".[all]"` 后执行，使用默认配置。

## 启动与导入

| 操作 | 耗时 |
|------|-----:|
| `import uniquant.shared` | 0.34s |
| `import uniquant.brain` | 0.85s |
| `import uniquant.data` | 0.02s |
| `import uniquant.signal` | 0.01s |
| `import uniquant.hands` | <0.01s |
| `import uniquant.risk` | <0.01s |
| `import uniquant.services` | <0.01s |
| `ServiceContainer.initialize()` | 0.04s |
| 9 引擎延迟初始化 | 0.002s |

brain 导入最慢（0.85s），因为 `backtrader`、`py_mini_racer`、`streamlit` 等依赖在导入时触发。其余层 <0.05s。

## 测试套件

| 套件 | 耗时 | 结果 |
|------|-----:|------|
| 全量测试 (1255 tests) | 35.7s | 1255 passed, 8 skipped |
| `tests/signal/` | 1.0s | 34 passed |
| `tests/hands/backtest/` | 1.3s | 7 passed |

全量测试时间主要受 I/O 密集型 fixture 初始化影响（~20s）。信号层和回测层测试极快（<2s）。

## 文档维护

| 操作 | 耗时 |
|------|-----:|
| `python3 scripts/verify_doc_paths.py` | 0.07s |
| 扫描 58 个 markdown 文件, 1103 个代码引用 | — |

路径验证 < 0.1s，适合作为 pre-commit hook。

## 仓库规模

| 指标 | 值 |
|------|---:|
| 源码文件 (`src/uniquant/`) | 272 |
| 源码行数 | 61,101 LOC |
| 测试文件 (`tests/`) | 108 |
| 文档文件 (`docs/`) | 203 |

## 建议

- **brain 导入优化**: 0.85s 的导入时间主要是 `backtrader` 和 `py_mini_racer` 的间接依赖。如果启动速度关键，可考虑延迟导入 brain 子模块。
- **全量测试时间**: 35.7s 中有约 20s 是 fixture 初始化。对于开发迭代，使用 `pytest tests/ -q --ignore=tests/test_manager_` 可跳过最慢的 fixture。
