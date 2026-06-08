# Queue 3 Audit: 服务编排与 UI (Services + UI)

**审计时间**: 2026-06-06
**审计范围**: `services/` (7767 LOC, 28 文件) + `ui/` (3248 LOC, 8 文件)
**总计**: ~11,015 LOC

---

## 🔴 幽灵依赖 (Ghost Dependencies)

### 1. `st_aggrid` / `streamlit-aggrid` — 使用但未声明
- **位置**: `ui/dashboard.py:11` `from st_aggrid import AgGrid, GridOptionsBuilder`
- **pyproject.toml**: ❌ 未声明
- **类型**: try/except 导入（可选），但文档和依赖缺失

### 2. `streamlit_autorefresh` — 使用但未声明
- **位置**: `ui/dashboard.py:21` `from streamlit_autorefresh import st_autorefresh`
- **pyproject.toml**: ❌ 未声明

### 3. `streamlit_echarts` — 使用但未声明
- **位置**: `ui/dashboard.py:28` `from streamlit_echarts import st_pyecharts`
- **pyproject.toml**: ❌ 未声明

**修复**: 将 `streamlit-aggrid`, `streamlit-autorefresh`, `streamlit-echarts` 添加至 `[project.optional-dependencies]` 或主依赖。

---

## 🟠 全局状态污染

### 1. `services/health_service.py:503` — 模块级单例
```python
global health_service  # L503

def get_health_service():
    global health_service
    if health_service is None:
        health_service = HealthService()
    return health_service
```
- 使用 `global` 关键字而非类级别的 `@classmethod` 或 `@staticmethod`
- 无锁保护，多线程下可能出现竞态（double-checked locking 缺失）

---

## 🟡 架构缺陷

### 1. `services/analysis_service.py` — 1642 行 "上帝对象"
- 单文件 1642 行，包含 6 大引擎调用编排
- 前 10 大函数总长度 ~700 行
- 职责过重：指标计算 + 风险验证 + 数据丰富 + ETF 扫描全部挤在一个类中
- **建议**: 拆分为 `AnalysisCoordinator` + 按领域拆分的服务类

### 2. `ui/dashboard.py` — 1524 行单体 Streamlit 文件
- 虽拆分为小函数（最大 47 行），但单文件仍 >
- 1500 行
- 含 AgGrid / autorefresh / echarts 三个可选可视化引擎
- **建议**: 拆分为 tab-specific 模块文件

### 3. `ui/__init__.py` — 空
- 完全空文件，无任何导出
- 对比 `services/__init__.py`（完整延迟加载架构）明显不一致

<!-- ### 4. `services/__init__.py` 已核实消除 -->
<!-- `import importlib` 在第 37 行的 `__getattr__` 函数内部，是合法的懒导入。无问题。 -->

---

## 🟢 架构亮点（正面）

### ✅ 服务层 DAG 依赖正确性
- `ui/` → `services/` → 下层（data/brain/risk/hands）— **方向完全正确**
- 未发现 `services` 反向依赖 `ui` 的情况
- 未发现循环依赖

### ✅ 引擎工厂设计
- `analysis/engine_factory.py` 使用 `threading.RLock` 双重检查锁定
- 9 个引擎的 lazy-init 注册一致
- 异常隔离：单个引擎初始化失败不影响其他引擎

### ✅ 服务层延迟导入
- `services/__init__.py` 通过 `__getattr__` 延迟加载 14 个服务类
- 避免了 import 时级联触发深度依赖链

---

## 📊 定量指标

| 指标 | 数值 |
|------|------|
| 审计总 LOC | 11,015 |
| 幽灵依赖 (UI 可视化库) | 3 |
| 全局状态点 | 1 |
| 1500+ 行单体文件 | 2 (`analysis_service.py` 1642 行, `dashboard.py` 1524 行) |
| 空 `__init__.py` | 1 (`ui/__init__.py`) |
| DAG 违反 | 0 ✅ |

---

## 🎯 建议优先级 (Queue 3)

| 优先级 | 项目 | 影响 |
|--------|------|------|
| P1 | 声明 3 个 Streamlit 可视化依赖至 pyproject.toml | 仪表盘无法渲染 |
| P2 | 拆分 `analysis_service.py` (1642行) | 可维护性风险 |
| P2 | 拆分 `dashboard.py` (1524行) | 可维护性风险 |
| P2 | 补全 `ui/__init__.py` 导出 | 包完整性 |
| P2 | 修复 `health_service.py` 无锁单例 | 多线程竞态 |
