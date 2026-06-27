# Queue 4 审计报告 V3: 外围代码 (Scripts + Tests + Root + Docs + MagicMock)

**审计时间**: 2026-06-06
**审计范围**:
- `scripts/` (12 文件, 50,509 LOC)
- `tests/` (79 文件, 568,944 LOC)
- 根目录 `*.py` (34 文件, 766,666 LOC)
- `Docs/` (大写) (3 文件, 9,353 LOC)
- `MagicMock/` (255 目录, 9.0 MB)

**总计**: 125 个 Python 源 + 3 个 docs + 255 个 mock 目录

---

## ✅ V2 报告核实

| V2 报告原话 | V3 核实结果 | 状态 |
|------------|------------|------|
| MagicMock 是 Python 测试库的临时目录 | **❌ 严重误报** — V2 混淆 `unittest.mock` 与项目根下的 `MagicMock/` 目录 | ❌ V2 错误 |
| MagicMock 是测试垃圾 | ✅ V2 正确 — 9.0 MB 测试 mock 数据泄漏 | ✅ V2 正确 |
| Docs/ 与 docs/ 重复 | **确认** — `Docs/` 大写 3 文件 (9,353B) vs `docs/` 小写 33+ 文件 | ✅ V2 正确 |
| `scripts/` 6 个 CLI | **核实修正** — 实际 12 个脚本文件 | ⚠️ V2 数量偏差 |
| `tests/` 79 个文件 | **确认** — 79 文件, 568,944B | ✅ V2 正确 |
| 根目录 34 个 .py | **确认** — 34 文件, 766,666B | ✅ V2 正确 |

**V2 严重误报**: V2 把 `MagicMock/` 目录当成 Python `unittest.mock` 模块，认为是 `tests/` 中的 mock 调用痕迹。**实际**: `MagicMock/` 是**测试运行时泄漏的临时数据目录**（含 255 个 `id()` 值命名的子目录），9.0 MB。

---

## 🔴 P0: 严重腐化点 (Critical Issues)

### 1. `MagicMock/` 目录 — 9.0 MB 测试 mock 数据泄漏

**核实**:
- 路径: `MagicMock/mock.data_dir/`
- 255 个数字命名子目录（`123135868693696`、`123135868696432`...）
- 这些数字是 Python `id()` 函数的返回值
- 每个子目录含 `factors/` 和 `lake/` 子目录
- **总大小 9.0 MB**
- **零代码引用** — `grep MagicMock tests/` 仅命中 `unittest.mock` 导入，**无任何代码引用该目录**

**结论**: 这不是代码错误，是**测试运行时的临时数据污染**，应该:
1. 添加到 `.gitignore`
2. 立即从 git 索引中删除
3. 找到生成该目录的代码（可能是某个测试用 `id()` 作为 tempdir 名称）

**修复**:
```bash
# 1. 添加到 .gitignore
echo "MagicMock/" >> .gitignore
echo "mock.data_dir/" >> .gitignore

# 2. 从 git 移除
git rm -r --cached MagicMock/
git commit -m "chore: remove leaked test mock data (9.0 MB)"
```

### 2. `Docs/` (大写) — 3 文件 9,353 字节，与 `docs/` 重复

**核实**:
```
Docs/change.md   1,671 字节
Docs/planner.md  6,603 字节
Docs/task.md     1,079 字节
```
- Linux **大小写敏感**，`Docs/` 与 `docs/` **视为两个不同目录**
- 但 macOS / Windows **大小写不敏感** → 在开发者本地会**相互覆盖**
- `Docs/change.md` 与 `docs/RESTRUCTURE_PLAN.md` **不是同一文件** (diff 验证)
- `Docs/` 3 文件内容是开发计划草稿，**已被整合到 `docs/`** 中更完整的文档

**结论**: `Docs/` 是**残留的早期开发目录**，应该:
- 整合到 `docs/development/` 子目录（如果内容有价值）
- 或直接删除（如果是过期草稿）

**修复**: 确认 `Docs/change.md`、`Docs/planner.md`、`Docs/task.md` 的内容是否已被 `docs/` 完整覆盖 → 是 → 删除 `Docs/`

### 3. 根目录 34 个 .py 文件 — 766 KB 临时分析脚本

**核实**:
| 类别 | 数量 | 大小 | 性质 |
|------|------|------|------|
| Ad-hoc 实验脚本 | 24 | ~650 KB | 一次性运行 |
| 多次迭代版本 | 8 | ~110 KB | `*_v2.py`、`*_experiment.py` |
| 集成脚本 | 2 | ~6 KB | `run_*`、`verify_*` |

**特征**:
- 29/34 文件 import `uniquant.*` (使用源码)
- 5/34 文件完全自包含（无 import）
- 全部含 `if __name__ == "__main__"` 直接运行入口
- 大量文件名带版本后缀: `comprehensive_analysis.py` / `full_a_stock_analysis.py` / `full_a_stock_analysis_optimized.py` / `full_analysis_experiment.py` / `full_analysis_final.py`
- **零测试引用** — `grep -l 'analysis_report\.' tests/` = 0

**问题**:
- 与 `scripts/` 和 `src/uniquant/` **目录职责不清晰**
- 散落根目录，git 索引膨胀
- 无法被 IDE 自动发现（无 `if __name__` 包装？已有）
- 多个版本的"full"分析，**重复造轮子**

**修复**:
1. 整合到 `experiments/` 子目录（带 README 说明一次性脚本性质）
2. 或删除过时版本（保留最新即可）
3. 至少为每个脚本添加 docstring 标注目的

### 4. `scripts/` 中 `offline_full_test.py` 62 字节 — 空壳脚本

**核实**:
```python
# scripts/offline_full_test.py — 62 字节
```
- 极小文件（62B），几乎可断定是占位文件
- 0 个函数、0 个 import、0 个 main

**修复**: 补全实现或删除

---

## 🟠 P1: 重要腐化点 (Major Issues)

### 5. `scripts/` 12 个 CLI — 与 `src/uniquant/` 职责冲突

**核实**:
| 脚本 | 引入的 src 模块 | 冲突点 |
|------|----------------|--------|
| `calculate_factors_single.py` | `uniquant.data.utils.smart_factor_calculator` | 应封装为 CLI 工具 |
| `rebuild_financial_lake.py` | `uniquant.data.services.import_financial` | 同上 |
| `run_market_scan.py` | `uniquant.services.scan_service` | 应作为 service 调用 |
| `verify_tdx_import.py` | `uniquant.data.managers.tdx_updater` | 同上 |

**问题**:
- `scripts/` 是"业务执行"层，**应只调用 CLI 接口**
- 但当前 12 个脚本**直接 import 内部模块**（`uniquant.data.services.import_financial`）
- 内部模块一旦重构（如 `services` 改为 `brain`），所有 scripts **全部失效**

**修复**:
```python
# 错误 (当前):
from uniquant.data.services.import_financial import FinancialImporter

# 正确 (修复后):
import subprocess
subprocess.run(["python", "-m", "uniquant.data.services.import_financial", "--symbols", "000001"])
```

### 6. `tests/conftest.py` — `np.random.randn` 不可重现

```python
@pytest.fixture
def sample_ohlcv_data():
    return pd.DataFrame({
        "open": np.random.randn(252).cumsum() + 100,  # 每次运行都不同
        ...
    })
```

**问题**:
- **无 `np.random.seed()`** → 每次 `pytest` 运行 fixture 数据**完全不同**
- 测试中若用 `pytest.approx(0.05, abs=1e-3)` 类硬编码断言 → **间歇性失败**
- 与 TDD 80%+ 覆盖率要求的"测试可重现"原则**直接冲突**

**修复**:
```python
@pytest.fixture
def sample_ohlcv_data():
    rng = np.random.default_rng(seed=42)  # 固定 seed
    return pd.DataFrame({
        "open": rng.standard_normal(252).cumsum() + 100,
        ...
    })
```

### 7. `tests/unit/` 和 `tests/integration/` 空目录

**核实**:
- `tests/unit/` 存在但为空（仅 `.` 和 `..`）
- `tests/integration/` 存在但为空

**问题**:
- `pytest.ini` 配置 `testpaths = ["tests"]` → 收集空目录
- **没有为未来测试预留结构**（命名约定: `test_unit_*.py` vs `test_integration_*.py`）
- 79 个测试全部在 `tests/` 顶层，**没有 unit/integration 划分**

**修复**:
1. 删除空目录 `tests/unit/` 和 `tests/integration/`
2. 或在 `pyproject.toml` 添加 `python_files = ["test_*.py"]` 标签（`@pytest.mark.unit`）
3. 添加 `pytest.ini` 配置 `markers = unit: Unit tests, integration: Integration tests`

### 8. `tests/test_offline_entry.py` — 396 字节可疑测试

**核实**:
- 79 个测试中最小文件（396B）
- 文件名含 `offline` 但 AGENTS.md 声明 "test_engine_factory.py 是唯一可独立运行测试"
- 76 个其他测试**全部需要 streamlit/data/外部依赖**

**修复**: 验证 `test_offline_entry.py` 是否真的可独立运行

### 9. 根目录散落的 `*_results.json` 和 `*_REPORT.md` — 15+ 个产物

**核实**:
```
backtest_report.json
comprehensive_analysis_results.json
factor_analysis_results.json
factor_effectiveness_multi_window_results.json (141 KB)
factor_effectiveness_results.json
hs300_analysis_errors.json
hs300_analysis_results.json
multi_stock_validation_results.json
multi_window_analysis_results.json
multi_window_index_comparison_results.json
optimization_results.json
optimized_scoring_results.json
quick_deep_optimization_results.json
smoke_test_results.json
validation_results.json
```
- 15 个 JSON 产物，**总大小 > 1 MB**
- 全部是根 .py 脚本的输出
- **未版本化**（无时间戳、无 schema 标签）
- `factor_effectiveness_multi_window_results.json` 141 KB — 最大

**问题**:
- 与 `docs/` 重复（多个 `*_REPORT.md` 同时存在）
- 应放到 `results/` 或 `outputs/` 子目录
- 缺少 `.gitignore` 规则

**修复**:
```bash
# 添加到 .gitignore
*.results.json
*_results.json
```

### 10. `scripts/test_incremental_update.py` — 命名为 `test_*.py` 但在 `scripts/`

**问题**:
- 文件名是 `test_*.py`，pytest 会**尝试收集**
- 但 `testpaths = ["tests"]` 排除了 `scripts/`
- 仍然具有误导性

**修复**: 重命名为 `incremental_update_check.py`

---

## 🟡 P2: 一般腐化点 (Minor Issues)

### 11. `scripts/verify_200.py` (230B) 和 `verify_import.py` (207B) — 极简脚本

**核实**:
- 两个文件均 < 250 字节
- 几乎可断定是一次性 sanity check

**修复**: 删除或合并到 `tests/`

### 12. `scripts/run_market_scan.py` (2030B) — 0 个函数

**核实**:
- 文件 2030B，**0 个函数**（全部是 `if __name__` 顶层代码）
- 应重构为 `def main()`

**修复**: 拆分 main() 为多个函数

### 13. `scripts/generate_chief_review.py` — 无 `__main__` 块

**核实**:
- 1 个函数 `generate_chief_review()`
- **无 `if __name__ == "__main__"` 入口**
- 直接 `python generate_chief_review.py` 无效果

**修复**: 添加 CLI 入口

### 14. `scripts/full_comparison.py` — 0 个 src import

**核实**:
- 3 个函数，**未引用 `uniquant` 任何模块**
- 是独立的数据对比工具

**修复**: 应放到 `tools/` 子目录或合并到 `scripts/run_*.py`

### 15. 根目录 `run_mining.py` (3202B) — 与 `run_resonance_backtest.py` 重复

**修复**: 合并为单一 mining pipeline

### 16. 根目录 `mining_harness.py` (4982B) vs `wyckoff_mining_harness.py` (9334B) — 双 harness

**问题**:
- 两个独立 wyckoff mining harness
- 命名相似但内容不同
- 难以判断哪个是最新版

**修复**: 合并

### 17. 根目录 `wyckoff_rounds.py` (3630B) — 与 wyckoff 实验相关但职责不清

**修复**: 整合到 `experiments/wyckoff/`

### 18. `verify_session5_csi300.py` — 一次性验证脚本

**修复**: 删除或放到 `docs/audit_logs/`

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计文件/目录数 | 125 .py + 3 docs + 255 mock 目录 |
| 审计总字节 | 1.4 MB+ (Python 源) + 9.0 MB (mock) |
| P0 严重问题 | 4 |
| P1 重要问题 | 7 |
| P2 一般问题 | 7 |
| 测试文件数 | 79 (568,944B) |
| 空测试目录 | 2 (`tests/unit/`, `tests/integration/`) |
| MagicMock 泄漏 | 9.0 MB / 255 目录 |
| Docs/ 重复 | 3 文件 (9,353B) |
| 根目录 .py | 34 文件 (766,666B) |
| 一次性脚本 | 24 个 |
| 版本化脚本 | 8 个 (含 _v2, _experiment) |
| 测试结果 JSON | 15+ 个 (> 1 MB) |

---

## 🎯 修复优先级 (Queue 4)

| 优先级 | 项目 | 影响 | 修复成本 |
|--------|------|------|----------|
| **P0** | 删除 `MagicMock/` 9.0 MB 泄漏 | 仓库体积 | 1 行 gitignore + 1 个 git rm |
| **P0** | 删除 `Docs/` (大写) 3 文件 | 路径冲突 | 1 个 rm |
| **P0** | 整理 34 个根 .py 散落 | 仓库结构 | 半天 |
| P1 | `scripts/` 12 CLI 改为 subprocess 调用 | 内部重构保护 | 1 天 |
| P1 | `conftest.py` 添加固定 seed | 测试可重现 | 3 行 |
| P1 | 删除 `tests/unit/` 和 `tests/integration/` 空目录 | 结构清晰 | 1 行 |
| P1 | 验证 `test_offline_entry.py` 是否真可独立运行 | 测试可信度 | 5 分钟 |
| P1 | 添加 `*_results.json` 到 .gitignore | 仓库体积 | 1 行 |
| P1 | `scripts/test_incremental_update.py` 改名 | 命名冲突 | 1 个 mv |
| P2 | 合并 `mining_harness.py` + `wyckoff_mining_harness.py` | 重复代码 | 半天 |
| P2 | 合并 `run_mining.py` + `run_resonance_backtest.py` | 重复代码 | 半天 |
| P2 | 删除 `scripts/verify_200.py` 等极简脚本 | 死代码 | 1 分钟 |

---

## 🔍 与 V2 报告对比 (Cross-Reference)

| V2 报告条目 | V3 状态 |
|------------|---------|
| MagicMock 是 Python 测试库临时目录 | ❌ V2 **严重误报** |
| MagicMock 9.0 MB 是测试垃圾 | ✅ V2 正确 |
| Docs/ 与 docs/ 重复 | ✅ V2 正确 |
| scripts/ 6 个 CLI | ⚠️ 实际 12 个 |
| tests/ 79 文件 | ✅ V2 正确 |
| 根目录 34 个 .py | ✅ V2 正确 |

**V2 准确率**: 50% (V2 误把 MagicMock 误认为 Python 模块)

**V3 新发现**:
- `MagicMock/mock.data_dir/` 实际是**测试运行时临时数据**（255 个 `id()` 命名目录），非 `unittest.mock` 库
- `Docs/` 与 `docs/` 内容**不重复**（3 文件是独立开发计划草稿），但**全部已过期**
- 根目录 34 个 .py 中 24 个是 ad-hoc 一次性脚本，8 个是版本化实验
- `conftest.py` 用 `np.random.randn` 无 seed，**测试不可重现**
- 15+ 个 `*_results.json` 散落根目录（> 1 MB），未在 .gitignore
- `tests/unit/` 和 `tests/integration/` 是空目录
- 79 个测试中除 `test_engine_factory.py` 外，**全部需要外部依赖**（streamlit/数据/网络）
