# Queue 4 Audit: 外围与脚本 (Scripts + Tests + Root 散落文件 + Docs)

**审计时间**: 2026-06-06
**审计范围**: 
- 根目录 34 个 `.py` 散落文件 (20,110 LOC)
- `scripts/` 12 文件 (1,537 LOC)
- `tests/` 77 个测试文件 (15,065 LOC)
- `docs/` 102 个文档文件

---

## 🔴 高危: 根目录代码散落 (Root-Level Code Scatter)

**34 个 `.py` 文件**, 共 **20,110 LOC** 散落在项目根目录，构成最大单一技术债来源。

| 类别 | 文件数 | 总 LOC | 状态 |
|------|--------|--------|------|
| 因子分析实验脚本 | 12 | ~7,500 | 一次性脚本，逻辑与 `brain/factors/` 重叠 |
| Wyckoff 挖掘脚本 | 4 | ~3,600 | 逻辑与 `brain/wyckoff/` 重叠 |
| 策略回测脚本 | 6 | ~3,200 | 逻辑与 `hands/backtest/` 重叠 |
| 优化/验证脚本 | 6 | ~3,400 | 逻辑与 `services/` 重叠 |
| 烟测/挖掘脚本 | 6 | ~1,500 | 独立入口但无包注册 |

**所有 34 个文件均有 `if __name__ == "__main__"` 块**，但未在 `pyproject.toml` 注册为 `console_scripts`。

**代表文件**:
| 文件 | LOC | 内容 |
|------|-----|------|
| `research_experiment.py` | 1,184 | 最大根文件，复杂分析管线 |
| `deep_analysis_experiment.py` | 991 | 深度实验，重复 `deep_analysis_v2.py` |
| `multi_window_index_comparison.py` | 982 | 多窗口对比 |
| `comprehensive_analysis.py` | 802 | 综合分析 |
| `full_multi_model_analysis.py` | 803 | 多模型分析 |

---

## 🟠 裂化测试 (Test Decay)

### 1. 模块级别跳过 — 2 个测试文件完全失活
```python
# tests/test_build_financial_v2.py:6
pytest.skip("scripts/build_financial_v2.py not found", allow_module_level=True)

# tests/test_stock_list_cli.py:7
pytest.skip("scripts/stock_list_cli.py not found", allow_module_level=True)
```
- 引用的 `scripts/build_financial_v2.py` 和 `scripts/stock_list_cli.py` **不存在**
- 这两个测试文件的所有测试从未执行

### 2. 条件跳过 — 8 个测试文件部分失活
| 测试文件 | 跳过条件 |
|----------|----------|
| `test_brain_boundary_qa.py` | CZSC 包未安装（9 个测试） |
| `test_wyckoff.py` | classifiers/state 导入链断裂（5 个测试） |
| `test_hands_strategies.py` | backtrader 未安装 |
| `test_e2e_integration_qa.py` | HealthService 依赖缺失 |
| `test_strategies.py` | 无交易信号 |
| `test_field_mapping.py` | 未知 |
| `test_backtest_advanced.py` | 未知 |
| `test_tdx_incremental.py` | 未知 |

### 3. 测试过大文件 (7 tests > 400 lines)
| 文件 | LOC |
|------|-----|
| `test_e2e_integration_qa.py` | 880 |
| `test_brain_boundary_qa.py` | 747 |
| `test_data_chaos_qa.py` | 595 |
| `test_chaos/test_brain_boundary.py` | 555 |
| `test_chaos/test_matching_auditor.py` | 513 |
| `test_chaos/test_e2e_pipeline.py` | 454 |
| `test_chaos/test_data_chaos.py` | 639 |

### 4. `conftest.py` 仅 27 行 — 不足
- 仅提供 2 个 fixture (`sample_ohlcv_data`, `sample_wyckoff_data`)
- 与 77 个测试文件的规模不匹配
- 缺少 mock 管理、共享 fixture、配置复用

---

## 🟡 脚本层问题 (Scripts Layer)

### 1. 存根脚本 (Stub Scripts)
| 文件 | LOC | 内容 |
|------|-----|------|
| `scripts/offline_full_test.py` | 4 | 只有 `RESULTS_DIR = Path("data/results")` — 无执行逻辑 |
| `scripts/verify_200.py` | 9 | 薄包装 `from verify_tdx_import import main; main(...)` |
| `scripts/verify_import.py` | 9 | 同上，深抽样 |

### 2. 硬编码魔数
`scripts/run_market_scan.py` 使用逐行排除 0000xx/0001xx/0002xx 等指数代码，共 30+ 行硬编码 if 条件，应使用 `shared/constants/market.py` 中的 `BoardType` 枚举。

### 3. `scripts/generate_chief_review.py` — 无 `__main__`
唯一没有 `if __name__` 块的脚本，意味着它只能被 import，不能直接运行。

---

## 🟢 测试亮点

### ✅ 测试架构覆盖
- `test_engine_factory.py` — 使用 MagicMock 隔离外部依赖，设计优良
- `tests/chaos/` — 4 个混沌测试覆盖边界/数据/E2E/撮合
- 总计 77 个测试文件，15,065 LOC 测试代码

### ✅ `run_smoke_test.py` 存在
根级别的烟雾测试脚本，可用于 CI 快速验证。

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 根目录散落 .py 文件 | 34 (20,110 LOC) |
| 脚本目录文件 | 12 (1,537 LOC) |
| 测试文件 | 77 (15,065 LOC) |
| 完全失活的测试文件 | 2 |
| 部分跳过的测试文件 | 8 |
| 存根脚本 | 3 |
| docs/ 文档文件 | 102 |

---

## 🎯 建议优先级 (Queue 4)

| 优先级 | 项目 | 影响 |
|--------|------|------|
| P0 | 清理 34 个根目录散落脚本（归档或移入 `scripts/archive/`） | 根治根目录污染 |
| P1 | 修复 `test_build_financial_v2.py` 和 `test_stock_list_cli.py` 引用失效 | 2 个测试文件完全失活 |
| P1 | 扩展 `conftest.py` 至 77 个测试文件的规模 | 测试基础设施不足 |
| P2 | 拆分 7 个 >400 行测试文件 | 可维护性 |
| P2 | 清理 3 个存根脚本 | 无功能代码 |
| P2 | 将 `run_market_scan.py` 硬编码替换为 BoardType 枚举 | 可维护性 |
