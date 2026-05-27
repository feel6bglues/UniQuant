# 重构工作流

## 何时使用
执行迁移时；规划重构步骤时；需要了解当前进度时；从 TDX 拉取代码时。

## 当前状态
Phase 0 未开始，完成度 ~28%（44/160 文件）。

```
shared/     ████████████████░░░░  79%  (23/29 文件)
services/   █████████░░░░░░░░░░░  46%  (11/24 文件)
brain/      ███░░░░░░░░░░░░░░░░░  17%  (5/30+ 文件)
ui/         █████░░░░░░░░░░░░░░░  25%  (2/8 文件)
risk/       ███░░░░░░░░░░░░░░░░░  14%  (1/7 文件)
hands/      █░░░░░░░░░░░░░░░░░░░   5%  (1/19+ 文件，空壳)
data/       ░░░░░░░░░░░░░░░░░░░░   0%  (0/40+ 文件)
signal/     ░░░░░░░░░░░░░░░░░░░░   0%  (0/6 文件)
```

**阻塞问题:** `import uniquant.services` 因幽灵导入崩溃（Phase 0 未执行）。

## Phase 路线图

| Phase | 名称 | 时间 | 前置 | 验收命令 |
|-------|------|------|------|----------|
| 0 | 紧急修复 (导入链恢复) | 0.5h | 无 | `python -c "import uniquant; import uniquant.shared; import uniquant.brain.fsm"` |
| 1A | Shared 基础层迁移 | 0.5h | Phase 0 | `python -c "from uniquant.brain.indicators import Indicators; from uniquant.risk.evt_risk import EVTRisk; from uniquant.risk.sizer import PositionSizer"` |
| 1B | Data 全层迁移 | 1.5h | Phase 0, Phase 1A | `python -c "from uniquant.data.data_fetcher import DataFetcher; from uniquant.data.lake.storage_manager import StorageManager"` |
| 1C | Services 层迁移 | 0.5h | Phase 1B (data 层) | `python -c "from uniquant.services.data_service import DataService; from uniquant.services.scan_service import ScanPipeline"` |
| 1D | Brain LPPL + Factor 迁移 | 0.5h | Phase 1A | `python -c "from uniquant.brain.lppl import calculator, core; from uniquant.brain.factors import FactorAnalyzer, FactorComposer"` |
| 1E | Hands + 回测迁移 | 0.3h | Phase 1A (risk), Phase 1B (data) | `python -c "from uniquant.hands.backtest import BacktestEngine, BacktestResult; from uniquant.hands.reporter import Reporter"` |
| 1F | UI 层迁移 | 0.3h | Phase 1C (services) | `python -c "from uniquant.ui.components import render_health_metrics; from uniquant.ui.manager_logic import AssetManager"` |
| 2 | mootdx 数据层适配 | 2.5h | Phase 1B | 端到端测试 mootdx 读取 → Parquet 存储 → 周线月线合成 |
| 3 | 验证 + 修复 | 1.5h | Phase 1 + Phase 2 | `pytest tests/ -v` 通过率 > 80% |
| 4 | 清理 | 0.5h | Phase 3 | `python -c "import uniquant; print('Import OK')" && pytest tests/ -v` |

**总估算:** ~8.6h, ~57 次提交

## 并行执行策略

```
Phase 0 (串行, 必须先完成)
  ↓
Phase 1A ─┬→ Phase 1C → Phase 1F    (路径A: services → UI)
          │
          └→ Phase 1D                (路径C: brain LPPL+Factor, 与A并行)
          │
Phase 1B ─┬→ Phase 1E               (路径B: data → hands回测)
          │
Phase 2 (mootdx适配, 依赖1B)
  ↓
Phase 3 (验证+修复, 依赖全部)
  ↓
Phase 4 (清理)
```

**可并行的 Phase:**
- Phase 1A 完成后: 1C (services) 和 1D (brain LPPL+Factor) 可并行
- Phase 1B 完成后: 1E (hands) 可启动，与 1C/1D 并行
- Phase 1C 完成后: 1F (UI) 可启动

**必须串行的 Phase:**
- Phase 0 → Phase 1A → 所有 1x Phase
- Phase 1B → Phase 2
- Phase 1 + Phase 2 → Phase 3 → Phase 4

## 每个 Phase 的验收标准

### Phase 0: 紧急修复
**验证:** `python -c "import uniquant; import uniquant.shared; import uniquant.brain.fsm"`
**内容:** 修复 7 个幽灵导入 (services/__init__.py, brain/lppl/__init__.py, services/analysis/__init__.py, ui/dashboard.py, brain/fsm/fsm.py, 创建缺失 __init__.py, 删除 WyckoffAnalysisEngine)

### Phase 1A: Shared 基础层
**验证:** `python -c "from uniquant.brain.indicators import Indicators; from uniquant.risk.evt_risk import EVTRisk; from uniquant.risk.sizer import PositionSizer"`
**内容:** 迁移 brain/indicators.py, brain/alpha_decoupler.py, risk/evt_risk.py, risk/sizer.py, shared/market_rules.py, risk/portfolio_optimizer.py, risk/structural.py, brain/ntf/, brain/regime/, 4 个 shared 子模块, 修复 engine_factory.py DecisionBrain 签名

### Phase 1B: Data 全层
**验证:** `python -c "from uniquant.data.data_fetcher import DataFetcher; from uniquant.data.lake.storage_manager import StorageManager"`
**内容:** 迁移 sources (7个数据源), managers (12个管理器), pipeline (3个), parsers (1个), services (6个导入服务), lake (1个), data_fetcher.py, CSV 数据文件

### Phase 1C: Services 层
**验证:** `python -c "from uniquant.services.data_service import DataService; from uniquant.services.scan_service import ScanPipeline"`
**内容:** 迁移核心服务 (4个), 业务服务 (8个), 分析引擎适配器 (4个), 恢复 __init__.py 完整导入

### Phase 1D: Brain LPPL + Factor
**验证:** `python -c "from uniquant.brain.factors import FactorAnalyzer, FactorComposer; from uniquant.brain.screener import StockScreener"`
**内容:** 迁移 LPPL 子模块 (8个), 因子流水线 (8个), screener.py, 恢复 fsm indicators 导入

### Phase 1E: Hands + 回测
**验证:** `python -c "from uniquant.hands.backtest import BacktestEngine; from uniquant.hands.reporter import Reporter"`
**内容:** 迁移 reporter.py, results_manager.py, backtest/ (engine, result), strategies/ (base, fsm_strategy)

### Phase 1F: UI 层
**验证:** `python -c "from uniquant.ui.components import render_health_metrics; from uniquant.ui.manager_logic import AssetManager"`
**内容:** 迁移 components.py, lppl_visualizer.py, manager_logic.py, 恢复 dashboard.py 正常导入

### Phase 2: mootdx 适配
**验证:** 端到端测试 mootdx 读取 → Parquet 存储 → 周线月线合成
**内容:** 新建 mootdx_local.py, mootdx_online.py, mootdx_factor_manager.py, 修改 DataFetcher, 扩展 StorageManager (周线/月线), 新增同步脚本

### Phase 3: 验证 + 修复
**验证:** `pytest tests/ -v` 通过率 > 80%
**内容:** 全量导入验证, 修复 PortfolioOptimizer bug, 修复 Protocol 类型不匹配, 复制 68 个测试文件, 运行测试并修复

### Phase 4: 清理
**验证:** `python -c "import uniquant; print('Import OK')" && pytest tests/ -v`
**内容:** 删除 deprecated 模块, 清理死代码, 拆分 constants.py (可选), 提取 CacheMixin (可选), 补充缺失依赖 (pybreaker, tenacity)

## 文件迁移通用步骤

1. **从 TDX 拷贝** — 源文件路径: `/home/james/Documents/Project/TDX/src/`
2. **修改 import 路径** — 使用批量替换规则:
   ```bash
   # 从 brain/risk/ui/services 出发到 shared:
   # from src.shared.X → from ...shared.X  (或 ..shared.X 取决于层级)
   # 从 services/analysis 出发到 data/brain/risk:
   # from src.data.X → from ...data.X
   ```
3. **适配 shared 依赖** — 检查目标 shared 模块是否已迁移，未迁移则先迁移
4. **更新 `__init__.py`** — 恢复完整导入（Phase 0 中临时改为最小导入）
5. **验证导入** — 运行对应 Phase 的验收命令

### Import 层级深度对照
```
uniquant/shared/     →  ..shared.     (从 brain/risk/ui/services 出发)
uniquant/data/       →  ...data.      (从 services/analysis 出发)
uniquant/brain/      →  ...brain.     (从 services/analysis 出发)
uniquant/risk/       →  ...risk.      (从 services/analysis 出发)
```

### 需要手动处理的文件 (深度差异)
| 文件 | 原始 | 目标 |
|------|------|------|
| `risk/sizer.py:4-6` | `from src.shared.constants/logger_factory/market_rules` | `from ...shared.constants/...` |
| `brain/factors/custom_factors.py:1` | `from src.brain.factors.registry` | `from .registry` |
| `ui/manager_logic.py:1-10` | `from src.services.*` / `from src.data.*` | `from ...services.*` / `from ...data.*` |
| `hands/strategies/base.py` | `from risk.sizer import PositionSizer` | `from ...risk.sizer import PositionSizer` |
| `hands/strategies/__init__.py` | `from src.hands.strategies.*` | `from .xxx` |
| `hands/__init__.py` | `from src.hands.*` | `from ...hands.*` |

## 迁移后必须更新的文档

- `docs/packages/*.md` — 对应包的 API 文档
- `docs/STATUS.md` — 重构进度表
- `docs/development/project_structure.md` — 项目结构

## 阻塞依赖链

```
Phase 0 (导入链恢复)
  → Phase 1A (shared + brain 基础层)
    → Phase 1B (data 全层)
      → Phase 2 (mootdx 适配)
    → Phase 1C (services)
      → Phase 1F (UI)
    → Phase 1D (brain LPPL+Factor)
    → Phase 1E (hands+回测)
      → Phase 3 (验证+修复, 依赖全部)
        → Phase 4 (清理)
```

**关键路径:** Phase 0 → 1A → 1B → 2 → 3 → 4 (~6.5h)
**并行路径:** 1A → 1D, 1B → 1E, 1C → 1F 可与关键路径并行

## TDX 项目路径

```
/home/james/Documents/Project/TDX/  (145 源文件, 68 测试文件)
```

TDX 源码结构:
- `TDX/src/brain/` — indicators.py, alpha_decoupler.py, lppl/, factors/, ntf_engine.py, regime_detector.py, screener.py
- `TDX/src/data/` — sources/ (7个), managers/ (12个), pipeline/ (3个), parsers/, services/ (6个), lake/
- `TDX/src/hands/` — reporter.py, results_manager.py, backtest/, strategies/
- `TDX/src/risk/` — evt_risk.py, sizer.py, portfolio_optimizer.py, structural.py
- `TDX/src/services/` — data_service.py, scan_service.py, portfolio_service.py 等
- `TDX/src/shared/` — market_rules.py, market_constants.py, network_constants.py, price_collar.py, risk_constants.py
- `TDX/src/ui/` — components.py, lppl_visualizer.py, manager_logic.py
- `TDX/tests/` — 68 个测试文件

## Commit 规范

遵循 Conventional Commits:
```
feat(scope): 描述新功能
fix(scope): 描述修复
refactor(scope): 描述重构
test(scope): 描述测试
chore(scope): 描述杂项
```

Scope 取值: `shared`, `brain`, `brain/lppl`, `brain/factors`, `brain/fsm`, `risk`, `data`, `data/sources`, `data/lake`, `data/managers`, `data/services`, `services`, `services/analysis`, `hands`, `hands/backtest`, `hands/strategies`, `ui`
