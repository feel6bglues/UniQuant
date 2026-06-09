# 剩余 5 项修复计划

**基线**: 986 passed, 7 skipped, 0 failed | **生成**: 2026-06-08

---

## 总览

| ID | 问题 | 严重性 | 文件 | 预计耗时 | 复杂度 |
|----|------|--------|------|----------|--------|
| F-16 | test import 风格不一致 | LOW | `tests/test_drawdown_analyzer.py:13` | 1 分钟 | ★ |
| F-11 | `markets.indices` 类型不匹配 | MEDIUM | `risk/structural.py:17` + `config/config.yaml:394` | 5 分钟 | ★ |
| F-15 | `signal/__init__.py` 无导入守卫 | LOW | `signal/__init__.py:7-46` | 5 分钟 | ★ |
| F-13 | Index 数据不足 + 代码无容错 | MEDIUM | `storage_manager.py:552-557` + `data/lake/index/` | 15 分钟 | ★★ |
| F-05 | 前视偏差影响量化 | MEDIUM | 需 A/B 对比实验 | 60 分钟 | ★★★ |

---

## F-16: test import 风格统一

**当前代码** (`tests/test_drawdown_analyzer.py:13`):
```python
from src.uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, DrawdownMetrics, TailRiskMetrics
```

**原因**: `src/` 在 `sys.path` 上（pip install -e .），当前可工作，但依赖运行环境配置。

**修复**: 改为 `from uniquant` 风格，与其余 75 个测试文件一致。
```python
from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, DrawdownMetrics, TailRiskMetrics
```

**验证**: `pytest tests/test_drawdown_analyzer.py -xvs` 全部通过。

**耗时**: 1 分钟。1 行修改。

---

## F-11: `markets.indices` 类型不匹配

### 问题

- **config.yaml**: `markets.indices` 返回 `List[Dict]`:
  ```yaml
  indices:
    - id: "000300.SH"
      name: "沪深300"
  ```
- **structural.py:17**: 期望 `Dict[str, str]`:
  ```python
  self.index_names = config.get("markets.indices", {"000300.SH": "沪深300", ...})
  ```

### 修复方案（选 A）

**方案 A（推荐—改代码适配 YAML）**: 在 `structural.py:17` 加类型转换:
```python
raw = config.get("markets.indices", {})
if isinstance(raw, list):
    self.index_names = {item["id"]: item["name"] for item in raw}
else:
    self.index_names = raw
```

**方案 B（改 YAML 适配代码）**: 将 config.yaml 中 `indices` 改为 dict 格式。

选择方案 A 因为 YAML 的 list-of-dict 格式更通用（前端消费方便），且不改动其他可能依赖此结构的代码。

**验证**: `StructuralRiskManager().index_names` 返回 `{"000300.SH": "沪深300", ...}` 而非 list。

**耗时**: 5 分钟。1 个文件，~5 行修改。

---

## F-15: `signal/__init__.py` 导入守卫

### 问题

当前（`signal/__init__.py:7-46`）全部均为裸 import:
```python
from .aggregator import (
    SignalAggregationMethod, SignalAggregator, ...
)
from .models import (
    AggregatedSignal, Signal, SignalBatch, ...
)
from .normalizer import (
    CZSCSignalNormalizer, IndicatorSignalNormalizer, ...
)
from .quality import (
    SignalQualityAssessor, SignalQualityMetrics, ...
)
from .adapters import (
    AdapterRegistry, CZSCAdapter, EngineAdapter, ...
)
```

若任一子模块导入时崩溃（如 F-02 的 namespace package 掩盖问题），整个 `uniquant.signal` 包无法导入，形成级联故障。

### 修复

参考 `brain/` 和 `services/` 中已使用的 `try/except` 守卫模式:
```python
try:
    from .aggregator import (...)
except ImportError:
    import logging
    logging.getLogger(__name__).warning("signal.aggregator 导入失败")

try:
    from .models import (...)
except ImportError:
    ...

# ... 其余模块同理
```

### 验证

```bash
python3 -c "from uniquant.signal import Signal, SignalAggregator, SignalQualityAssessor; print('OK')"
python3 -c "from uniquant.signal.adapters import create_default_registry; r = create_default_registry(); print(len(r.list_engines()), 'engines')"
```

**耗时**: 5 分钟。1 个文件。

---

## F-13: Index 数据 + 代码容错

### 问题

两层问题:

1. **数据层**: `data/lake/index/` 仅有 `sh000300.parquet`（284 KB），缺少 config.yaml 中列出的其他指数数据
2. **代码层**: `storage_manager.py:556-557` 无容错:
   ```python
   def read_data(self, symbol, data_type="daily", **kwargs):
       file_path = self._get_file_path(symbol, data_type)
       return self.read_parquet(str(file_path))  # ❌ 无 try/except
   ```

### 修复计划

#### 步骤 1: `storage_manager.read_data()` 加容错

修改 `storage_manager.py:556-557`:
```python
def read_data(self, symbol, data_type="daily", **kwargs):
    file_path = self._get_file_path(symbol, data_type)
    if not file_path.exists():
        logger.warning(f"数据文件不存在: {file_path}")
        return pd.DataFrame()
    return self.read_parquet(str(file_path))
```

#### 步骤 2: 检查所有调用方的返回值处理

`read_data` 现在可能返回空的 `DataFrame`，需要确保调用方（`macro_service.py`、`macro_analysis_engine.py`、`analysis_service_v2.py` 等）能正确处理。

**macro_service.py:202** 当前:
```python
df = self.data_service.lake.read_data("sh000300", "index", market="cn")
```
后文有 `if df is not None and not df.empty:` 检查，兼容空 DataFrame。

**analysis_service_v2.py:221-223** 当前:
```python
df = self.data_service.lake.read_data(MarketConstants.INDEX_HS300, data_type="index", market="cn")
if df is not None and not df.empty:
```
兼容空 DataFrame。

**macro_analysis_engine.py:177**: 同 macro_service，需确认有空检查。

#### 步骤 3（非阻塞）: 补充指数数据

运行 `import_index.py` 脚本补充 missing 指数：
```bash
python3 -m src.uniquant.data.services.import_index --output-dir data/lake/index
```

### 验证

```bash
# 文件不存在时返回空 DataFrame 而非崩溃
python3 -c "
from pathlib import Path
import tempfile, os
from uniquant.data.lake.storage_manager import StorageManager
sm = StorageManager(lake_dir=tempfile.mkdtemp())
df = sm.read_data('NONEXISTENT.SH', 'index')
print(f'Empty df: {df.empty}')  # 应打印 True
"
```

**耗时**: 15 分钟。1 个文件 ~5 行修改 + 验证。

---

## F-05: 前视偏差修复影响量化

### 问题

27 个前视偏差已全部加 `.shift(1)` 修复，但修复对 Sharpe/收益率的实际提升缺乏 A/B 对比数据。之前低 Sharpe（0.115）的主因是 Pipeline 信号漏斗阻塞（F-01/F-09），而非前视偏差本身。

### 实验设计

#### 实验 A — 单元回归验证

对每个修改过的指标函数，验证 `.shift(1)` 后的值与修复前不同:

```python
import pandas as pd
import numpy as np

# 模拟数据
df = pd.DataFrame({"close": np.random.randn(100).cumsum() + 100})

# 修复前（自指）
ma_before = df["close"].rolling(5).mean().iloc[-1]

# 修复后（无偏）
ma_after = df["close"].shift(1).rolling(5).mean().iloc[-1]

# 验证不一致
assert ma_before != ma_after, "修复应改变指标值"
```

#### 实验 B — Pipeline E2E 对比

两次运行 `UnifiedResearchPipeline.run()`，一次用修复前代码（git stash），一次用修复后代码，比较:

| 指标 | 修复前 | 修复后 | 变化 |
|------|--------|--------|------|
| 总信号数 | ? | ? | ? |
| 平均置信度 | ? | ? | ? |
| 引擎崩溃数 | ? | 0 | ? |

#### 实验 C（可选）— 回测 A/B

如果 Pipeline 已经能产出信号，运行 `UnifiedBacktestEngine.run()` 对比:
- 修复前 Sharpe、Win Rate、Max DD
- 修复后 Sharpe、Win Rate、Max DD

### 实施步骤

1. 创建 `experiments/2026-06-08_lookahead_ab/` 目录
2. 编写 `run_ab_comparison.py` 脚本:
   - 用 git 暂存当前修复后代码
   - 生成修复前快照（stash pop + 记录结果）
   - 分别运行 pipeline 收集指标
   - 输出对比报告

### 预期结果

前视偏差修复预期的改善方向:
- 指标值更保守（不再自指），信号质量更真实
- 信号数可能略微下降（自指 MA 被纠正后，部分假信号消失）
- Sharpe 应更接近真实值（可能略降，因为自指会膨胀收益）

**耗时**: 60 分钟。1 个实验脚本。

---

## 执行顺序

```
批次 E（今天，15 分钟内）
  E1: F-16 — test import 风格         [1 分钟, 1 行]
  E2: F-11 — markets.indices 类型     [5 分钟, 1 文件]
  E3: F-15 — signal 导入守卫          [5 分钟, 1 文件]
  E4: F-13 — storage_manager 容错     [10 分钟, 1 文件]

批次 F（单独安排）
  F1: F-05 — A/B 对比实验脚本        [60 分钟, 1 脚本]
```

---

## 附录: 各问题代码精确定位

| ID | 文件 | 行 | 当前代码 |
|----|------|-----|----------|
| F-16 | `tests/test_drawdown_analyzer.py` | 13 | `from src.uniquant.risk.drawdown_analyzer import ...` |
| F-11 | `risk/structural.py` | 17-18 | `config.get("markets.indices", {"000300.SH": "沪深300"})` |
| F-11 | `config/config.yaml` | 394-404 | `indices: [{id, name}, ...]` 返回 list |
| F-15 | `signal/__init__.py` | 7-46 | 5 段裸 `from .xxx import ...` |
| F-13 | `data/lake/storage_manager.py` | 556-557 | `read_parquet()` 无 try/except |
| F-13 | `data/lake/index/` | - | 仅 1 文件 `sh000300.parquet` |
