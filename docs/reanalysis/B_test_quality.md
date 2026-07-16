# Phase B — 测试质量深度审计报告

> 日期: 2026-07-06 | 只读分析（未修改 src/uniquant/ 下任何文件）

---

## 总结

| 维度 | 评级 | 详情 |
|---|---|---|
| **变异测试击杀率** | ⚠️ 无法自动运行 | mutmut 3.6.0 因环境配置问题（`config/` 路径依赖 `__file__`）无法完成基准运行 |
| **测试密度** | 2.21 asserts/test | 1461 个测试函数 / 3233 条 assert 语句 |
| **边界条件覆盖** | Good | 241 个 None 测试, 283 个 NaN/边界测试, 62 个异常测试 |
| **测试冗余率** | Low | 无无断言测试文件；部分文件 asserts < test functions |
| **集成/E2E 测试** | Good | 67 个跨层引用, 6 个 E2E 测试文件 |
| **CI 就绪度** | Partial | 基础 CI 存在但缺少覆盖率门禁、并行执行、缓存策略 |
| **参数化测试** | 11 uses | 参数化测试使用率偏低 |

---

## B1 变异测试

### mutmut 执行摘要

对 `src/uniquant/shared/cost_model.py` 尝试运行 mutmut 3.6.0：

```
mutmut run --max-children 2
```

**结果：基线运行失败**。mutmut 的 `_pytest_args_regular_run` 使用 `-x` 标志，且复制的源文件在 `mutants/src/` 下运行时，`config_loader.py` 的 `_root_dir = Path(__file__).parent.parent.parent.resolve()` 解析到 `mutants/src/` 而非项目根目录，导致 `config/config.yaml` 无法加载：

```
AssertionError: assert 'use_research_data_pack' in {}
```

这是因为：
- `config_loader.py` 被复制到 `mutants/src/uniquant/shared/config_loader.py`
- `__file__` 使 `_root_dir` 解析为 `.../mutants/src/`
- 而 `config/config.yaml` 被复制到 `mutants/config/`
- 路径错位导致配置加载失败，进而 `test_config_yaml_has_flag` 测试失败

### 手动变异分析（cost_model.py）

通过对生成后的 `mutants/src/uniquant/shared/cost_model.py` 分析，mutmut 成功生成了 **40 个变异体** 用于 `calculate_sharpe_ratio`，涵盖：
- 条件边界变异（`<` → `<=`, `>=` → `>`）
- 数值变异（`0.0` → `1.0`）
- 调用移除（`np.asarray` 参数置 None）
- 算术运算变异（除数置 None）
- 返回值变异

由于基线运行失败，**无法自动统计击杀率**。手动验证表明 `test_default_rfr_is_3pct`、`test_sharpe_with_positive_returns` 等测试在独立运行中均通过。

### 其他高风险文件变异可行性

| 文件 | 变异体预估 | 测试覆盖 | 可运行性 |
|---|---|---|---|
| `shared/cost_model.py` | ~200 | 4 个测试函数 | ⚠️ 需要修复 config 路径 |
| `shared/market_rules.py` | ~300 | 部分覆盖 | 待评估 |
| `signal/arbitrator.py` | ~500 | 7 个测试 | 待评估 |
| `hands/backtest/unified_matching_engine.py` | ~800 | 有限 | 待评估 |

### 击杀率评估（基于代码审查）

- `calculate_sharpe_ratio`：测试覆盖了默认 RFR、正收益、平坦收益、数据不足等场景，预计击杀率 **>80%**
- 整体击杀率预估：**~70-85%**（未经验证）

---

## B2 测试冗余

### 测试密度统计

| 指标 | 数值 |
|---|---|
| 测试文件数 | 121 |
| 测试函数总数 | 1,461 |
| assert 语句总数 | 3,233 |
| 每测试函数 assert 数 | 2.21 |
| 无 assert 测试文件 | **0** |

### 冗余分析

所有 121 个测试文件均包含 assert 语句，**没有完全无断言的测试文件**。按文件类型分布：

| 目录 | 测试文件 | 测试函数 | 平均 asserts/文件 |
|---|---|---|---|
| 根目录 | 100 | ~1,160 | ~27 |
| `chaos/` | 4 | 89 | ~53 |
| `shared/` | 13 | 131 | ~5 |
| `integration/` | 1 | 6 | ~2 |
| `hands/backtest/` | 1 | 7 | ~2 |

**分析**：部分 `shared/` 和 `integration/` 测试文件 assert 密度较低（如 `test_config_validator_factor.py` 仅 2 个测试函数），但均包含至少一个 assert。**未发现纯副作用测试（无断言）**。

**建议**：
- 检查 assert 密度 < 3 的测试文件，确认是否覆盖足够
- `shared/test_config_validator_factor.py`（2 tests, 少量 assert）可能测试不足

---

## B3 边界条件覆盖

### 统计汇总

| 边界类型 | 匹配数 | 评价 |
|---|---|---|
| 空列表 `[]` | 14+ | Good — 处理空数据 |
| None 检查 | 241 | Excellent — 广泛的 None 防御 |
| NaN/边界值 | 283 | Excellent — 浮点边界覆盖 |
| 异常测试 (`pytest.raises`) | 62 | Good — 异常路径覆盖 |
| 边界日期（1990/2020） | 5+ | Fair — 日期边界有限 |

### 边界覆盖亮点

- **chaos 测试**：`test_brain_boundary.py` 专门测试零价格、负价格等边界场景
- **NaN 测试**：283 处 NaN 检查覆盖所有计算引擎（LPPL、Regime、Wyckoff、NTF）
- **空数据测试**：`test_wyckoff_new_features.py` 验证空 DataFrame 输入
- **异常测试**：62 个 `pytest.raises` 分布于 error_handling、validation 模块

### 边界覆盖缺口

| 缺口类型 | 缺失位置 |
|---|---|
| 极大数据量测试 | 未发现高并发/大数据压力测试 |
| 数值溢出测试 | 未发现 `np.inf` 或浮点溢出专项测试 |
| 极端时间边界 | 如 2038 年问题、Unix 时间戳边界 |
| 并发竞态测试 | 共享缓存/状态的多线程测试有限 |

---

## B4 测试数据质量

### 静态测试数据

| 类型 | 文件 | 用途 |
|---|---|---|
| Parquet 基准 | `tests/benchmark/baseline_v0.parquet` | 回溯测试基线 |
| Parquet 基准 | `tests/benchmark/baseline_v0_100.parquet` | 100 支股票基线 |
| 文本基准 | `tests/benchmark/golden_20.txt` | 20 支 golden 记录 |
| 文本基准 | `tests/benchmark/golden_100.txt` | 100 支 golden 记录 |
| 文本基准 | `tests/benchmark/golden_500.txt` | 500 支 golden 记录 |

### 测试数据多样性评估

- **正常场景**：✅ 所有引擎有标准数据测试
- **边界场景**：✅ 零价格、负价格、空数据（chaos 测试套件）
- **异常场景**：✅ NaN、None、无效符号
- **缺失场景**：
  - ❌ 无正式的 fixture 目录（`tests/fixtures/` 不存在）
  - ❌ 无模拟的盘口/订单簿数据
  - ❌ 无损坏/格式错误的输入数据测试
  - ⚠️ Benchmark 数据为二进制 parquet 格式，难以审查

### Fixture 使用

`conftest.py` 存在但未自定义 fixture。使用 `@pytest.fixture` 装饰器共 **84 处**，主要分布在引擎测试中。参数化测试仅 **11 处**。

**建议**：
- 创建 `tests/fixtures/` 目录存放可复用的测试数据
- 增加 CSV/JSON 格式的透明测试数据文件
- 增加参数化测试使用率

---

## B5 测试并行化

### 当前状态

pytest-xdist 未安装：

```
pytest: error: unrecognized arguments: -n auto
```

所有测试串行执行。完整套件执行时间：

- 完整测试套件（排除覆盖率）：~2-5 分钟（受外部数据源影响）
- 限制：部分测试依赖共享状态（如 `ServiceContainer._instance`），并行执行需隔离

### 并行化可行性

| 测试组 | 可并行性 | 注意事项 |
|---|---|---|
| `tests/shared/` | ✅ 完全独立 | 无共享状态 |
| 根目录测试 | ⚠️ 大部分可并行 | 部分测试有模块级副作用 |
| `tests/chaos/` | ✅ 可并行 | 独立数据生成 |
| `tests/integration/` | ⚠️ 部分可并行 | 依赖 ServiceContainer 单例 |

**建议**：
- 安装 pytest-xdist：`pip install pytest-xdist`
- 对隔离的 shared 测试启用 `-n auto`
- 对 ServiceContainer 相关测试使用 `@pytest.mark.serial` 标记
- 修复共享状态（如 `ServiceContainer._instance`）使其可重置

---

## B6 集成测试缺口

### 跨层测试覆盖

| 跨层测试 | 匹配数 | 覆盖情况 |
|---|---|---|
| `ServiceContainer` | 10+ | 初始化测试 ✅ |
| `run_ticker_analysis` | 4 | 分析服务测试 ✅ |
| `run_batch` | 5 | 批处理测试 ✅ |
| `PipelineResult` | 8 | 管道结果测试 ✅ |

### E2E 测试

| 测试文件 | 测试场景 | 覆盖层级 |
|---|---|---|
| `tests/test_e2e_pipeline.py` | 全链路信号→回溯测试 | 信号 + 回溯测试 |
| `tests/test_e2e_integration_qa.py` | ServiceContainer + 策略 + 数据管道 | 全部 8 层 |
| `tests/chaos/test_e2e_pipeline.py` | 混沌 E2E | 全部 8 层 |

### 集成测试缺口

| 缺失场景 | 风险等级 | 说明 |
|---|---|---|
| 引擎间交互 | Medium | LPPL→Regime→Wyckoff 等联合运行 |
| 数据质量→引擎 | Medium | 脏数据如何影响引擎输出 |
| 实时 vs 历史切换 | Medium | TimeProvider 切换场景 |
| 信号仲裁→下单 | High | Arbitrator 输出到实际交易流程 |
| 批量并行+错误恢复 | Medium | `run_batch` 部分失败处理 |

---

## B7 CI 流水线验证

### GitHub Actions 配置

```yaml
name: CI
on:
  push: { branches: [main, master] }
  pull_request: { branches: [main, master] }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5 (3.12)
      - run: pip install -e ".[all]"
      - run: ruff check src/uniquant/
      - run: pytest tests/ -q --tb=short
```

### CI 成熟度评估（5 分制）

| 维度 | 评分 | 说明 |
|---|---|---|
| 基础设置 | 3/5 | 有 CI 但只有单作业 |
| 测试覆盖门禁 | 0/5 | 未配置覆盖率阈值 |
| 并行执行 | 0/5 | 无 pytest-xdist 或作业矩阵 |
| 缓存 | 0/5 | 无 pip/ 缓存策略 |
| Lint 集成 | 3/5 | ruff 检查但未设门禁 |
| 通知 | 0/5 | 无失败通知配置 |
| **总分** | **6/30** | |

### CI 缺失项

| 缺失项 | 重要性 | 建议 |
|---|---|---|
| 覆盖率门禁 | High | 添加 `--cov-fail-under=50` 到 pytest 参数 |
| 并行测试 | Medium | 安装 pytest-xdist，用 `-n auto` |
| pip 缓存 | High | 添加 `~/.cache/pip` 缓存 |
| 多 Python 版本 | Medium | 测试 3.11/3.12 |
| 依赖审计 | Medium | 添加 `pip-audit` 步骤 |
| 通知机制 | Low | 配置 Slack/邮件通知 |

---

## 综合建议

### P0 — 必须修复
1. **修复合 CI**：添加覆盖率门禁和缓存策略
2. **安装 pytest-xdist**：将测试执行时间减半
3. **建立 fixture 目录**：创建 `tests/fixtures/` 存放标准测试数据

### P1 — 高优先级
1. **修复 mutmut 兼容性**：调整 `config_loader.py` 的 `_root_dir` 解析策略以兼容 mutmut 的目录复制
2. **参数化测试扩展**：增加 `@pytest.mark.parametrize` 使用率（当前仅 11 处）
3. **共享状态隔离**：修复 `ServiceContainer` 等模块级单例以支持并行测试

### P2 — 中优先级
1. **增加日期边界测试**：覆盖 1990-01-01、2038 等极端日期
2. **增加并发测试**：多线程访问共享缓存的场景
3. **扩展集成测试**：引擎间联合运行、信号仲裁到下单全流程

### P3 — 低优先级
1. **CI 通知配置**：添加失败通知
2. **多 Python 版本矩阵测试**
3. **损坏数据输入测试**：格式错误、缺失字段等

---

## ANALYSIS COMPLETE