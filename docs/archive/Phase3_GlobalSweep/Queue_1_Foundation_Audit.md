# Queue 1 Audit: 基础公共基建 (Foundation & Shared Infrastructure)

**审计时间**: 2026-06-06
**审计范围**: `shared/` (23 文件) + `signal/` (6 文件) + `config/` (4 YAML) + `pyproject.toml`

---

## 🔴 高危: 断裂的导入路径 (Broken Import)

### 1. `shared/price_collar.py:1` — 双重相对导入错误
```python
from ..shared.market_rules import get_board_rule
```
`price_collar.py` 位于 `src/uniquant/shared/`。`from ..shared` 解析为 `uniquant.shared.shared.market_rules`，该路径**不存在**。
- **后果**: 任何 `import uniquant.shared.price_collar` 将抛出 `ModuleNotFoundError: No module named 'uniquant.shared.shared'`
- **修复**: 应改为 `from .market_rules import get_board_rule`
- **引用者**: 此模块目前被外部调用（见下文）。

<!-- ~~### 2. `shared/__init__.py:5` — 非安全导入~~ 已核实消除 -->
<!-- 代码实际使用 `from .analysis_result import ...`，带前导点。无问题。 -->

---

## 🔴 幽灵依赖 (Ghost Dependency)

### 1. `urllib3` — 使用但未声明
- **文件**: `shared/error_handling.py:12` 导入 `import urllib3`，L356 使用 `urllib3.exceptions.HTTPError`
- **pyproject.toml**: 未声明 `urllib3` 依赖
- **风险**: 仅通过 `requests` 间接引入。若环境中 `requests` 版本不带 `urllib3` 兼容绑定，或 `urllib3` 被自动移除，则 `error_handling.py` 崩溃
- **修复**: 在 `pyproject.toml` 中显式添加 `urllib3>=2.0.0`

---

## 🟠 全局状态污染 (Global State Contamination)

### 1. `shared/config_loader.py:324` — 模块级 None 与函数内延迟初始化
```python
config = None          # L324: 模块级 None
def get_config():      # L327: 函数内才创建实例
    global config
    if config is None:
        config = GlobalConfig()
    return config
```
- 不是急切单例；`config = None` 仅在模块级保留引用占位
- 实际的 `GlobalConfig()` 在首次调用 `get_config()` 时才创建
- 虽使用双重检查锁定（`__new__` + `_lock`），但 `get_config()` 内无锁保护，多线程下可能重复创建

### 2. `shared/error_handling.py:19-24` — 模块级可变共享状态
```python
_error_logger = ...
logger = ...
_error_stats_lock = threading.Lock()
```
- `error_handling.py:308`: `global _error_stats` — 字典在多线程下被多个修饰器并发读写
- `get_error_stats()` / `reset_error_stats()` 未加锁保护

### 3. `shared/logger_factory.py:159,177` — 全局工厂锁 + global 声明
```python
_factory_lock = threading.Lock()
global _factory  # L177
```
- `LoggerFactory.__new__` 使用单例模式（`_factory_lock` 保护），但 `global _factory` 绕过锁直接赋值
- `setup_logger()` 模块级调用（L33+）在导入时副作用，早于配置加载

### 4. `shared/env_config.py:41` — 导入时副作用
```python
configure_environment()
```
- 导入即设置 `OMP_NUM_THREADS=1` 等环境变量，可能在多线程环境中引发竞态

---

## 🟡 僵尸代码 / 废弃模块 (Zombie Code)

### 1. `shared/di_container.py` — 整文件废弃（24 行）
- 文件标明 `DEPRECATED`，仅存为向后兼容
- `DIContainer = ServiceContainer; container = ServiceContainer.instance()` — `instance()` 调用在导入时创建容器
- **当前引用者**: 无（仅自引用）
- **建议**: 立即删除，下一个版本移除

### 2. `shared/network_constants.py` — 仅 2 常量（2 行）
- `MAX_RETRIES = 3`, `RETRY_DELAY_BASE = 1.0`
- **当前引用者**: 无
- **建议**: 合并到 `constants/misc.py` 或 `config.yaml`

### 3. `shared/market_constants.py` — 仅 1 常量（1 行）
- `A_SHARD_BOARDS = {"sz", "sh", "bj"}`
- **当前引用者**: 无
- **建议**: 合并到 `constants/market.py`，该集合已是 `BoardType` 枚举的一部分

### 4. `shared/slippage_model.py:9` — 空存根函数
```python
class SlippageModel(ABC):
    @abstractmethod
    def estimate(self, ...):
        ...
```
- `estimate` 只有 docstring 无实现体
- 整个文件仅 48 行，从未被子类化或引用（除 `cost_model.py` 导入 `SlippageModel`）

### 5. `shared/parallel.py:8` — 空函数
```python
def worker_init():
    pass
```
- 不执行任何操作，导入即定义但未使用

---

## 🟢 信号层 (signal/) 审计

### 发现
| 文件 | 状态 | 备注 |
|------|------|------|
| `models.py` | ✅ 整洁 | 6 个 dataclass，类型完备 |
| `normalizer.py` | ✅ 整洁 | 抽象基类 + 注册表模式，结构清晰 |
| `quality.py` | ✅ 整洁 | dataclass 定义完整 |
| `aggregator.py` | ⚠️ 偏大 | 312 行，含 SignalAggregator(96 行) 和 TimeWindowAggregator |
| `db.py` | ⚠️ | 使用 SQLAlchemy，DB 连接在模块级创建，无连接池配置 |
| `__init__.py` | ✅ | 5 层深导出，API 清晰 |

### 问题
- **signal/db.py** 无异常处理包装，DB 连接失败直接抛出
- **signal/aggregator.py** `TimeWindowAggregator` 无单元测试覆盖

---

## 🟤 配置 (config/) 审计

| 文件 | 大小 | 状态 |
|------|------|------|
| `config.yaml` | 11114 字节 / 430 行 | 覆盖 10+ 模块配置 |
| `trading.yaml` | 1410 字节 | 交易参数 |
| `factors.yaml` | 254 字节 | 因子配置 |
| `optimal_params.yaml` | 4131 字节 | 最优参数 |

### 问题
- `config.yaml` 中定义的 `base.tdx.path` 硬编码为 `/home/james/.local/share/tdxcfv/drive_c/tc`，不可移植
- `optimal_params.yaml` 由 `shared/optimal_params.py:485`（大文件）加载，加载逻辑复杂

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计文件数 | 32 (23+6+3) |
| 高危问题 | 3（1 断裂导入 + 1 幽灵依赖 + 1 导入时副作用） |
| 中危问题 | 6（4 全局状态 + 2 空函数） |
| 低危问题 | 4（废弃/合并项） |
| 总代码行 (shared/.py) | ~4,200 |
| 总代码行 (signal/.py) | ~780 |

---

## 🎯 建议优先级 (Queue 1)

| 优先级 | 项目 | 影响 |
|--------|------|------|
| P0 | 修复 `price_collar.py` 断裂导入 | 任何调用者报 ModuleNotFoundError |
| P1 | 在 pyproject.toml 添加 `urllib3` | 环境兼容性风险 |
| P1 | 清理 `di_container.py` | 废弃代码 + 导入时副作用 |
| P2 | 移除/合并 `network_constants.py`, `market_constants.py` | 减少散落常量文件 |
| P2 | 为 `error_handling.py` `get_error_stats` 加锁 | 多线程竞态风险 |
| P3 | 实现 `slippage_model.py` `estimate` 或移除 | 抽象方法无实现 |
