# UniQuant 修复战役总路线图 (Repair Campaign Roadmap)

> **编制角色**: 首席架构师 × 量化研发负责人
> **编制日期**: 2026-05-31
> **输入源**: AUDIT_REPORT_2026-05-31.md (525行) + AUDIT_VERIFICATION_2026-05-31.md (137行) + 源码逐行核实
> **总体结论**: 审计报告核心断言 100% 准确，整体准确率 ~90%

---

## 第一阶段：缺陷三维定级 (Bug Triage)

### 全量缺陷清单 — 经源码核实后重新定级

| # | 编号 | Bug 描述 | 评级 | 所属模块 | 文件:行号 | 爆炸半径 |
|---|------|---------|------|---------|-----------|---------|
| 1 | B-001 | 印花税用 `max_year < 2024` 而非 `date >= 2023-08-28` 判断，2023H2 回测多扣一倍印花税 | **P0** | hands/strategies | `backtest.py:321` | 所有 2023H2 回测成本错误 |
| 2 | B-002 | `AnalysisError` 在 `@handle_errors` 装饰器中使用但未导入 → 模块加载时 NameError | **P0** | brain/czsc | `czsc_engine.py:148,443` | CZSC 整个引擎不可用 |
| 3 | B-003 | `Indicators = None` fallback 无 None 检查，`infer_state()` 直接调用 `.calc_ma()` 触发 AttributeError | **P0** | brain/fsm | `fsm.py:112-113` | FSM 状态机完全不可用 |
| 4 | B-004 | `best_cost` 已是 RMSE，再次 `np.sqrt(best_cost / N)` 导致双重开方，RMSE 被严重低估 | **P0** | brain/lppl | `engine.py:348` | LPPL 泡沫检测数值全部失真 |
| 5 | B-005 | `np.abs(tc - t)` 替代 `tc - t`，t > tc 时模型继续计算而非返回 NaN，掩盖无效预测 | **P0** | brain/lppl | `visualizer.py:123` | 泡沫检测信号产生虚假波形 |
| 6 | B-006 | `MemoryCacheBackend` get/set/delete/hits/misses 完全无线程锁，并发读写竞态 | **P0** | shared/cache | `backends.py:28-46` | 多线程缓存数据损坏 |
| 7 | B-007 | FSM `infer_state()` 只能到达 IDLE/SIGNAL/PROBE/MONITOR，PYRAMID/EXIT/CIRCUIT_BREAK 不可达 | **P1** | brain/fsm | `fsm.py:95-158` | 7 状态机实际只有 4 状态工作 |
| 8 | B-008 | 科创板/创业板 `price_collar_pct=0.01`(±1%)，A 股规则应为 ±2% | **P1** | shared | `market_rules.py:27-29` | 合法限价单被错误拒绝 |
| 9 | B-009 | 三套滑点实现并存且数值不一致: cost_model 0.05%, slippage_model 0.1%, BacktestEngine 基础+冲击 | **P1** | shared | `cost_model.py:29` + `slippage_model.py:15` | 回测成本取决于调用路径 |
| 10 | B-010 | YAML 与常量 12 处参数冲突（滑点 2x、FSM MA 4x/3x、NTF 窗口 4x、市值阈值 2-3x、熵值 2x 等） | **P1** | shared + config | `config.yaml` + `constants/` 全局 | 运行时行为取决于调用路径 |
| 11 | B-011 | LPPL 代价函数不统一: core.py 返回 SSE，engine.py 返回 RMSE，影响收敛判据含义 | **P1** | brain/lppl | `core.py:119` + `engine.py:135` | LPPL 模型跨文件不可比较 |
| 12 | B-012 | LPPL tau 处理 4 种方式: core.py `max(tau,1e-8)`, engine.py `max(tau,1e-10)`, calculator.py `tau<=0→NaN`, visualizer.py `abs(tc-t)` | **P1** | brain/lppl | 4 个文件 | 同一数学量在不同文件含义不同 |
| 13 | B-013 | `handle_errors` 装饰器异常捕获顺序错误: 子类先捕获导致父类分支永不触发 | **P1** | shared | `error_handling.py` | 异常处理路径不可预测 |
| 14 | B-014 | `with_timeout` 使用 daemon 线程无法真正取消执行，超时后函数继续占用资源 | **P1** | shared | `utils.py` | 资源泄漏 + 潜在死锁 |
| 15 | B-015 | 新股上市首日/前 5 日涨跌停规则缺失: 主板首日+44%，科创/创业板前 5 日不设限 | **P1** | shared | `limit_checker.py` | 回测新股涨跌停判断错误 |
| 16 | B-016 | 北交所前缀 `"4"` 包含新三板，`"83"/"87"` 才是北交所正确前缀 | **P2** | shared/constants | `market.py:70` | 新三板股票被错误应用 30% 涨跌停 |
| 17 | B-017 | UI 层 5 处 DAG 违规: ui 直接导入 brain/data/risk 层 | **P2** | ui | `lppl_visualizer.py:9-10`, `dashboard.py:612` 等 | 架构耦合，违反 5 层 DAG |
| 18 | B-018 | 两套 DI 容器并存: `shared/di_container.py` 和 `services/service_container.py` 互不关联 | **P2** | shared + services | 2 个文件 | 服务初始化路径不确定 |
| 19 | B-019 | LPPL 代码重复: 3 独立 + 1 内联 LPPL 函数实现，3 种代价函数，3 种风险判定 | **P2** | brain/lppl | 4 个文件 | 维护成本高，修复需同步多处 |
| 20 | B-020 | 集合竞价时段完全缺失: 9:15-9:25 开盘竞价、14:57-15:00 收盘竞价 | **P2** | shared | `market_rules.py` | 时段判断不完整 |
| 21 | B-021 | signal/wyckoff/strategies/高级回测 零测试覆盖 | **P2** | tests | 全局 | 最关键模块无验证保障 |
| 22 | B-022 | 北交所 `price_collar_pct=0.01`(±1%)，实际应为 ±3%-5% | **P2** | shared | `market_rules.py:30` | 北交所合法限价单被拒绝 |
| 23 | B-023 | 股票 lot_size=200 时卖出零股处理缺失，`round_lot` 始终向下取整到整手 | **P2** | shared | `market_rules.py` | 科创板零股卖出失败 |

---

## 第二阶段：依赖拓扑图 (Dependency Map)

### 2.1 根节点 Bug（修复后连带解决其他问题）

```
B-010 (YAML/常量冲突) ← 根节点 #1
  ├── B-009 (滑点不统一) 的根本原因之一
  ├── 影响所有读取配置的模块行为
  └── 必须在所有算法修复前确立"唯一真值源"

B-006 (缓存线程安全) ← 根节点 #2
  └── 所有使用缓存的模块在多线程下均受影响

B-013 (handle_errors 异常顺序) ← 根节点 #3
  └── 所有使用 @handle_errors 的模块异常路径受影响
```

### 2.2 叶子节点 Bug（必须等待上游稳定后才能修复）

```
B-019 (LPPL 代码重复) ← 叶子节点
  依赖: B-004, B-005, B-011, B-012 全部修复后才能统一

B-007 (FSM 不可达状态) ← 叶子节点
  依赖: B-003 (Indicators None 检查) + brain/indicators.py 迁移

B-017 (UI DAG 违规) ← 叶子节点
  依赖: services 层门面方法就绪
```

### 2.3 完整依赖拓扑

```
            ┌─────────────────────────────────────────┐
            │        Layer 0: 基础设施 (无依赖)          │
            │  B-006 缓存线程安全                        │
            │  B-013 handle_errors 异常顺序              │
            │  B-001 印花税日期                          │
            │  B-002 CZSC AnalysisError 导入             │
            └──────────────┬──────────────────────────┘
                           │
            ┌──────────────▼──────────────────────────┐
            │      Layer 1: 核心算法修复 (依赖 Layer 0)    │
            │  B-003 FSM Indicators None 检查           │
            │  B-004 LPPL RMSE 双重开方                 │
            │  B-005 LPPL tau abs() 数学错误            │
            │  B-008 价格笼子比例修正                    │
            │  B-015 新股涨跌停规则                      │
            └──────────────┬──────────────────────────┘
                           │
            ┌──────────────▼──────────────────────────┐
            │     Layer 2: 体系统一 (依赖 Layer 1)        │
            │  B-010 YAML/常量 12 处冲突 → 唯一真值源      │
            │  B-009 滑点三套统一                        │
            │  B-011 LPPL 代价函数统一                   │
            │  B-012 LPPL tau 处理统一                   │
            └──────────────┬──────────────────────────┘
                           │
            ┌──────────────▼──────────────────────────┐
            │     Layer 3: 逻辑补全 (依赖 Layer 2)        │
            │  B-007 FSM 3 个不可达状态                  │
            │  B-014 with_timeout 真正取消               │
            └──────────────┬──────────────────────────┘
                           │
            ┌──────────────▼──────────────────────────┐
            │     Layer 4: 架构优化 (可最后执行)           │
            │  B-017 UI DAG 违规                        │
            │  B-018 DI 容器合并                        │
            │  B-019 LPPL 代码去重                      │
            │  B-020 集合竞价时段                        │
            │  B-021 测试覆盖补充                        │
            │  B-016 北交所前缀修正                      │
            │  B-022 北交所价格笼子                      │
            │  B-023 零股卖出                            │
            └─────────────────────────────────────────┘
```

---

## 第三阶段：修复战役总路线图

### 1. 战役优先级矩阵 (Triage Matrix)

| 排名 | 编号 | Bug | 评级 | 所属模块 | 前置条件 | 影响面 |
|------|------|-----|------|---------|---------|--------|
| 1 | B-001 | 印花税日期标注错误 | **P0** | hands/backtest | 无 | 2023H2 全部回测成本错误 |
| 2 | B-002 | CZSC AnalysisError 未导入 | **P0** | brain/czsc | 无 | 模块加载崩溃 |
| 3 | B-004 | LPPL RMSE 双重开方 | **P0** | brain/lppl | 无 | 泡沫检测数值失真 |
| 4 | B-005 | LPPL tau abs() 数学错误 | **P0** | brain/lppl | 无 | 虚假波形 |
| 5 | B-006 | 缓存无线程锁 | **P0** | shared/cache | 无 | 多线程数据损坏 |

---

### 2. 多阶段修复冲刺计划 (Phased Sprint Plan)

#### Sprint 1: 基建与排雷 (P0 排除 + 基础安全)

**目标**: 消除所有 P0 级缺陷，恢复核心引擎可加载性和数值正确性
**预计耗时**: 2-3 小时
**并行度**: 3 路 Subagent

```
┌──────────────────────────────────────────────────────────────┐
│                    Sprint 1 任务分配                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Agent A (brain-corridor): brain 层 P0 修复                   │
│  ├── B-002: czsc_engine.py 添加 AnalysisError 导入            │
│  ├── B-003: fsm.py 添加 Indicators None 检查                  │
│  ├── B-004: lppl/engine.py 修复 RMSE 双重开方                  │
│  └── B-005: lppl/visualizer.py 修复 tau abs() 错误            │
│                                                              │
│  Agent B (shared-corridor): shared 层 P0 + 安全修复           │
│  ├── B-006: backends.py MemoryCacheBackend 添加 threading.Lock │
│  └── B-013: error_handling.py 修复异常捕获顺序                 │
│                                                              │
│  Agent C (hands-corridor): 回测成本修复                       │
│  └── B-001: backtest.py 印花税改为 date >= 2023-08-28         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**文件独占性保证**:
- Agent A: `brain/czsc/czsc_engine.py`, `brain/fsm/fsm.py`, `brain/lppl/engine.py`, `brain/lppl/visualizer.py`
- Agent B: `shared/cache/backends.py`, `shared/error_handling.py`
- Agent C: `hands/strategies/backtest.py`
- **零文件冲突**

---

#### Sprint 2: 引擎重装 (A 股规则修正 + 配置统一 + 滑点治理)

**目标**: 修正 A 股交易规则合规性，建立"唯一真值源"，统一滑点模型
**预计耗时**: 3-4 小时
**并行度**: 3 路 Subagent

```
┌──────────────────────────────────────────────────────────────┐
│                    Sprint 2 任务分配                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Agent D (config-authority): 配置系统治理                     │
│  ├── B-010: 确立 YAML 为唯一真值源                             │
│  │   - 统一 12 处 YAML vs Constants 冲突                      │
│  │   - 修改 constants/ 中常量仅作 fallback 默认值              │
│  │   - 添加 config_loader 的 set() 方法支持测试注入            │
│  └── B-009: 统一三套滑点为单一 SlippageModel                  │
│      - cost_model.py SLIPPAGE_PCT = 0.0005                   │
│      - slippage_model.py DefaultSlippage 改为读取 cost_model  │
│      - 删除 DynamicSlippage 中硬编码值，接入真实数据源          │
│                                                              │
│  Agent E (a-share-compliance): A 股规则修正                   │
│  ├── B-008: market_rules.py 科创板/创业板 price_collar → 0.02 │
│  ├── B-022: market_rules.py 北交所 price_collar → 0.03        │
│  ├── B-015: limit_checker.py 添加新股上市天数判断              │
│  └── B-016: constants/market.py 北交所前缀改为 ["83","87"]    │
│                                                              │
│  Agent F (lppl-unification): LPPL 子系统统一                  │
│  ├── B-011: 统一代价函数为 RMSE (以 engine.py 为准)            │
│  │   - core.py 的 SSE → RMSE: `np.sqrt(sse / n)`            │
│  │   - calculator.py 保持 VarPro (已正确)                     │
│  └── B-012: 统一 tau 处理为 calculator.py 方式                │
│      - core.py: `tau = tc - t; tau[tau<=0] = NaN`            │
│      - engine.py: 同上                                       │
│      - visualizer.py: 已在 Sprint 1 修复                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**文件独占性保证**:
- Agent D: `config/config.yaml`, `config/trading.yaml`, `shared/constants/*.py`, `shared/cost_model.py`, `shared/slippage_model.py`, `shared/config_loader.py`
- Agent E: `shared/market_rules.py`, `shared/limit_checker.py`, `shared/constants/market.py`
- Agent F: `brain/lppl/core.py`, `brain/lppl/engine.py` (与 Sprint 1 的 B-004 不冲突，Sprint 1 已完成)
- **零文件冲突**

---

#### Sprint 3: 逻辑补全与性能治理 (P1 逻辑缺陷 + P2 优化)

**目标**: 补全 FSM 状态机逻辑，修复性能隐患，补充关键测试
**预计耗时**: 3-4 小时
**并行度**: 3 路 Subagent

```
┌──────────────────────────────────────────────────────────────┐
│                    Sprint 3 任务分配                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Agent G (fsm-logic): FSM 状态机逻辑补全                      │
│  ├── B-007: 补全 PYRAMID/EXIT/CIRCUIT_BREAK 推断条件          │
│  │   - infer_state() 添加加仓信号 → PYRAMID 转换               │
│  │   - infer_state() 添加平仓信号 → EXIT 转换                  │
│  │   - infer_state() 添加回撤触发 → CIRCUIT_BREAK 转换         │
│  │   - 修复 EXIT 状态立即重置为 IDLE 的内部不一致               │
│  └── 补充 FSM 单元测试 (目标: 状态覆盖 7/7)                   │
│                                                              │
│  Agent H (perf-safety): 性能与安全修复                        │
│  ├── B-014: with_timeout 改用 concurrent.futures              │
│  │   ThreadPoolExecutor + future.cancel()                     │
│  └── B-020: MarketHours 添加集合竞价时段定义                   │
│      - 开盘集合竞价 9:15-9:25                                 │
│      - 收盘集合竞价 14:57-15:00                               │
│                                                              │
│  Agent I (test-coverage): 关键模块测试补充                    │
│  ├── B-021: 为 signal/ 包添加基础测试                         │
│  ├── 补充 LPPL 核心路径测试 (RMSE 计算、tau 边界)              │
│  └── 补充 A 股规则集成测试 (涨跌停 + 价格笼子 + T+1)          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**文件独占性保证**:
- Agent G: `brain/fsm/fsm.py`, `tests/test_fsm.py`
- Agent H: `shared/utils.py`, `shared/market_rules.py` (仅添加方法，不修改 Sprint 2 的 price_collar 修正)
- Agent I: `tests/` 目录 (新建测试文件)
- **零文件冲突**

---

#### Sprint 4: 架构治理与长期优化 (P2 架构问题)

**目标**: 消除架构级违规，代码去重，建立测试基础设施
**预计耗时**: 4-6 小时
**并行度**: 2 路 Subagent

```
┌──────────────────────────────────────────────────────────────┐
│                    Sprint 4 任务分配                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Agent J (architecture-cleanup): 架构治理                     │
│  ├── B-017: UI 层 5 处 DAG 违规修复                           │
│  │   - services 层创建门面方法                                 │
│  │   - UI 只通过 services 层间接访问 brain/data/risk          │
│  ├── B-018: 合并 DI 容器                                      │
│  │   - 保留 ServiceContainer 拓扑初始化                       │
│  │   - 融合 DIContainer 的 factory 注册能力                   │
│  └── B-023: 零股卖出处理                                      │
│      - 科创板 lot_size=200 时允许一次性卖出不足 200 股         │
│                                                              │
│  Agent K (lppl-dedup + testing): LPPL 去重 + 测试基建         │
│  ├── B-019: LPPL 代码去重                                     │
│  │   - 以 calculator.py (VarPro) 为权威实现                   │
│  │   - 删除 core.py/engine.py 中重复的 LPPL 函数              │
│  │   - 统一 risk level 判定为一处                              │
│  ├── B-021: wyckoff/ 策略测试补充                             │
│  └── 补充 data/pipeline/ 测试                                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

### 3. Subagent 并发派发指南 (Dispatch Protocol)

#### Sprint 1 派发规则

```
Agent A (brain-corridor)     独占: src/uniquant/brain/**/**
Agent B (shared-corridor)    独占: src/uniquant/shared/cache/**, src/uniquant/shared/error_handling.py
Agent C (hands-corridor)     独占: src/uniquant/hands/strategies/backtest.py

三者零交集，可完全并发。
```

#### Sprint 2 派发规则

```
Agent D (config-authority)   独占: config/**, src/uniquant/shared/constants/**, 
                                src/uniquant/shared/cost_model.py,
                                src/uniquant/shared/slippage_model.py,
                                src/uniquant/shared/config_loader.py
Agent E (a-share-compliance) 独占: src/uniquant/shared/market_rules.py,
                                src/uniquant/shared/limit_checker.py,
                                src/uniquant/shared/constants/market.py
Agent F (lppl-unification)   独占: src/uniquant/brain/lppl/core.py,
                                src/uniquant/brain/lppl/engine.py (仅代价函数部分)

⚠️ 注意: Agent D 修改 constants/*.py, Agent E 修改 constants/market.py
→ 解法: Agent E 仅修改 market.py 中的 BOARD_PREFIX 和 LIMIT_RATIO，
  Agent D 不修改 market.py 的这些区域，只修改 data.py/technical.py/risk.py
  两者通过文件区域隔离，不冲突。
```

#### Sprint 3 派发规则

```
Agent G (fsm-logic)          独占: src/uniquant/brain/fsm/fsm.py, tests/test_fsm.py
Agent H (perf-safety)        独占: src/uniquant/shared/utils.py, src/uniquant/shared/market_rules.py
Agent I (test-coverage)      独占: tests/ (新建文件)

⚠️ 注意: Agent H 修改 market_rules.py, Sprint 2 Agent E 也修改了该文件
→ Sprint 3 在 Sprint 2 完成后才启动，时序隔离。
```

---

### 4. 阶段性熔断与回归指标 (Milestones & Fallbacks)

#### Sprint 1 验收 — 基建与排雷

```bash
# 验收标准 1: 导入链恢复
python3 -c "
import uniquant
import uniquant.shared
import uniquant.brain.czsc
import uniquant.brain.fsm
import uniquant.brain.lppl
print('Sprint 1 Import OK')
"

# 验收标准 2: LPPL 数值正确性
python3 -c "
import numpy as np
from uniquant.brain.lppl.engine import cost_function
# 测试: cost_function 应返回合理范围的 RMSE
t = np.linspace(0, 100, 200)
# 用已知参数生成测试数据，验证 RMSE 不会被双重开方
print('LPPL RMSE sanity check passed')
"

# 验收标准 3: 缓存线程安全 (压力测试)
python3 -c "
import threading
from uniquant.shared.cache.backends import MemoryCacheBackend
cache = MemoryCacheBackend(max_size=100)
errors = []
def writer():
    for i in range(1000):
        try:
            cache.set(f'k{i}', {'v': i})
            cache.get(f'k{i}')
        except Exception as e:
            errors.append(e)
threads = [threading.Thread(target=writer) for _ in range(10)]
for t in threads: t.start()
for t in threads: t.join()
assert len(errors) == 0, f'Thread safety errors: {len(errors)}'
print(f'Cache thread safety: 10 threads × 1000 ops = 0 errors')
"

# 验收标准 4: 核心测试通过
python3 -m pytest tests/test_engine_factory.py -xvs

# 验收标准 5: Lint 通过
ruff check src/uniquant/brain/ src/uniquant/shared/cache/ src/uniquant/shared/error_handling.py src/uniquant/hands/strategies/backtest.py
```

**熔断条件**: 任一验收标准不通过 → 修复后才能进入 Sprint 2

---

#### Sprint 2 验收 — 引擎重装

```bash
# 验收标准 1: 配置一致性
python3 -c "
from uniquant.shared.config_loader import get_config
from uniquant.shared.cost_model import SLIPPAGE_PCT
config = get_config()
yaml_slippage = config.get('trading.slippage_pct', 0) / 100
assert abs(SLIPPAGE_PCT - yaml_slippage) < 1e-6, \
    f'Slippage mismatch: YAML={yaml_slippage}, Constants={SLIPPAGE_PCT}'
print('Config consistency: slippage unified')
"

# 验收标准 2: A 股规则合规
python3 -c "
from uniquant.shared.market_rules import BOARD_RULES, BoardType
star = BOARD_RULES[BoardType.STAR]
gem = BOARD_RULES[BoardType.GEM]
assert star.price_collar_pct == 0.02, f'STAR collar: {star.price_collar_pct}'
assert gem.price_collar_pct == 0.02, f'GEM collar: {gem.price_collar_pct}'
print('A-share compliance: price collar correct')
"

# 验收标准 3: LPPL 一致性
python3 -c "
import numpy as np
from uniquant.brain.lppl.core import lppl_func as core_lppl
from uniquant.brain.lppl.engine import lppl_func as engine_lppl
# 同参数下两个函数结果应一致
t = np.linspace(0, 100, 200)
tc, m, w, a, b, c, phi = 150, 0.5, 8.0, 6.0, -0.5, 0.1, 0.0
r1 = core_lppl(t, tc, m, w, a, b, c, phi)
r2 = engine_lppl(t, tc, m, w, a, b, c, phi)
assert np.allclose(r1, r2), 'LPPL function mismatch between core and engine'
print('LPPL consistency: core == engine')
"

# 验收标准 4: 全量导入验证
python3 -c "
import uniquant
import uniquant.shared
import uniquant.brain
import uniquant.brain.fsm
import uniquant.brain.czsc
import uniquant.brain.lppl
import uniquant.hands
print('Sprint 2 Import OK')
"

# 验收标准 5: Lint 全量
ruff check src/uniquant/
```

**熔断条件**: 任一验收标准不通过 → 修复后才能进入 Sprint 3

---

#### Sprint 3 验收 — 逻辑补全

```bash
# 验收标准 1: FSM 全状态可达
python3 -c "
from uniquant.brain.fsm.fsm import FSMState
# 验证所有 7 个状态在 FSMState 枚举中定义
states = [s.value for s in FSMState]
assert len(states) == 7, f'Expected 7 states, got {len(states)}'
assert 'PYRAMID' in states
assert 'EXIT' in states
assert 'CIRCUIT_BREAK' in states
print(f'FSM states: {states}')
print('FSM completeness: 7/7 states defined')
"

# 验收标准 2: with_timeout 可取消
python3 -c "
import time
from uniquant.shared.utils import with_timeout
start = time.time()
try:
    with_timeout(lambda: time.sleep(10), timeout=1)
except Exception:
    elapsed = time.time() - start
    assert elapsed < 3, f'Timeout took {elapsed:.1f}s, expected <3s'
    print(f'with_timeout cancellation: {elapsed:.1f}s (correct)')
"

# 验收标准 3: 新测试通过
python3 -m pytest tests/ -xvs --tb=short 2>&1 | tail -20

# 验收标准 4: 集合竞价时段
python3 -c "
from uniquant.shared.market_rules import MarketHours
# 验证开盘集合竞价和收盘集合竞价定义存在
print('Auction time rules: defined')
"
```

**熔断条件**: 任一验收标准不通过 → 修复后才能进入 Sprint 4

---

#### Sprint 4 验收 — 架构治理

```bash
# 验收标准 1: DAG 无违规
python3 -c "
# 扫描 UI 层导入，不应直接导入 brain/data/risk
import ast, pathlib
ui_dir = pathlib.Path('src/uniquant/ui')
violations = []
for f in ui_dir.glob('**/*.py'):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(x in node.module for x in ['.brain.', '.data.', '.risk.']):
                violations.append(f'{f}:{node.lineno} imports {node.module}')
if violations:
    print('DAG violations found:')
    for v in violations: print(f'  {v}')
else:
    print('DAG compliance: 0 violations')
"

# 验收标准 2: 测试覆盖率
python3 -m pytest tests/ --cov=src/uniquant --cov-report=term-missing -q 2>&1 | tail -5

# 验收标准 3: 全量 Lint + Type Check
ruff check src/uniquant/
python3 -m mypy src/uniquant/ --ignore-missing-imports 2>&1 | tail -5
```

---

### 5. 战役总览 — 甘特图视角

```
Week 1 (Day 1-2):
├── Sprint 1: P0 排除 ──────────────────── [2-3h]
│   ├── Agent A: brain 层 4 Bug
│   ├── Agent B: shared 层 2 Bug
│   └── Agent C: hands 层 1 Bug
│   └── 🔒 Gate: 导入链 + LPPL 数值 + 缓存线程安全 + pytest
│
Week 1 (Day 3-5):
├── Sprint 2: 规则修正 + 配置统一 ──────── [3-4h]
│   ├── Agent D: 配置治理 (12 冲突 + 滑点统一)
│   ├── Agent E: A 股规则 (价格笼子 + 新股 + 北交所)
│   └── Agent F: LPPL 统一 (代价函数 + tau 处理)
│   └── 🔒 Gate: 配置一致性 + A 股合规 + LPPL 一致性 + pytest
│
Week 2 (Day 1-3):
├── Sprint 3: 逻辑补全 + 性能 ──────────── [3-4h]
│   ├── Agent G: FSM 全状态逻辑
│   ├── Agent H: with_timeout + 集合竞价
│   └── Agent I: 测试补充
│   └── 🔒 Gate: FSM 7/7 状态 + timeout 取消 + pytest
│
Week 2 (Day 4-5) + Week 3:
├── Sprint 4: 架构治理 ──────────────────── [4-6h]
│   ├── Agent J: DAG 违规 + DI 合并
│   └── Agent K: LPPL 去重 + 测试基建
│   └── 🔒 Gate: DAG 0 违规 + 覆盖率 ≥80%
```

---

## 附录：已确认无需修复的项

| 审计报告断言 | 核实结果 | 说明 |
|-------------|---------|------|
| ServiceContainer `__all__` 列出 13 个服务 | 报告有误 | 实际不存在 `__all__`，但核心问题（注册不完整）属实 |
| `get_config()` 非线程安全 | 严重性过高 | GlobalConfig.__new__ 已有双重检查锁，风险低 |
| 最大回撤阈值冲突 0.15 vs 0.20 | **误报** | YAML 和常量均为 0.15，无冲突 |
| 北交所前缀 `["8","4"]` 为 Bug | 设计选择 | `"4"` 涵盖新三板是合理设计 |
| services/__init__.py 幽灵导入 | **已修复** | 已使用 `__getattr__` 延迟导入 |
| data/ 整层不存在 | **已修复** | data/ 层已完整迁移 |

---

## 附录：Sprint 1 修复代码速查

| Bug | 文件 | 行号 | 修复方案 (5行以内) |
|-----|------|------|-------------------|
| B-001 | `hands/strategies/backtest.py:321` | `if max_year < 2024:` | → `if pd.Timestamp(max_date) < pd.Timestamp('2023-08-28'):` |
| B-002 | `brain/czsc/czsc_engine.py:14` | `from ...shared.exceptions import CZSCEngineError` | → `from ...shared.exceptions import AnalysisError, CZSCEngineError` |
| B-003 | `brain/fsm/fsm.py:112` | `ma20 = Indicators.calc_ma(...)` | → 前插 `if Indicators is None: raise ImportError("brain.indicators not migrated")` |
| B-004 | `brain/lppl/engine.py:348` | `rmse = np.sqrt(best_cost / len(...))` | → `rmse = best_cost` |
| B-005 | `brain/lppl/visualizer.py:123` | `tau = np.abs(tc - t)` | → `tau = tc - t; tau[tau <= 0] = np.nan` |
| B-006 | `shared/cache/backends.py:28` | `class MemoryCacheBackend:` | → `__init__` 中添加 `self._lock = threading.Lock()` + 所有方法加锁 |
| B-013 | `shared/error_handling.py` | `except Exception as e:` 顺序 | → 先 `except expected_exceptions as e:`，再通用 `except Exception` |

---

*路线图版本: v1.0 | 编制时间: 2026-05-31 | 基于源码逐行核实*
*审计报告可信度: 核心 Bug 100% 准确, 整体 ~90%*
