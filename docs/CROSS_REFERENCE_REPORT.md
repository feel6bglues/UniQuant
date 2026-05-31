# Cross-Reference Report: Master Plan vs Actual Project State

> 审查日期: 2026-05-31 | 对象: OPTIMIZATION_MASTER_PLAN.md v2
> 方法: 逐行比对 231 个源文件, 交叉 6 份子文档

---

## 综合评分: 7.0/10

| 维度 | v2 评分 | 本审查 | 说明 |
|------|---------|--------|------|
| 方案完整性 | 8/10 | 7/10 | 仍遗漏 EVTRisk/PortfolioSizer 等 risk 模块问题 |
| 事实准确性 | 7/10 | 6/10 | LPPL JIT/线程安全/constants 结构三点有误 |
| 依赖分析 | 9/10 | 8/10 | 遗漏 get_efficient_frontier 对 optimizer 的依赖 |
| 进度估算 | 7/10 | 7/10 | LPPL JIT 实际已就绪，可节省 ~2 天 |
| 跨文档一致性 | 6/10 | 6/10 | 止损方案在子文档未同步更新 |
| 风险识别 | 8/10 | 7/10 | 遗漏回测引擎无单元测试的风险 |

---

## 1. 必须修正的关键事实错误

### 错误 1: LPPL Numba JIT 现状描述不准确

**文档声称** (§5.3):
> "brain/lppl/numba_optimizer.py 已存在但 cost_function_reduced() 未使用 JIT 编译"
> "JIT 后预估: ~3μs/次"

**实际代码** (`numba_optimizer.py:20-264`):
- `_reduced_cost_numba()`: **已使用** `@njit(cache=True, fastmath=True)` 编译
- `_solve_linear_parameters_numba()`: **已使用** `@njit` 编译
- `_de_solve_numba()`: **已使用** `@njit` 编译 (完整 DE 优化器)

文档中提到的 `cost_function_reduced` 函数名**不存在** — 实际名为 `_reduced_cost_numba`。

**真相**: numba 函数已实现、已 JIT 编译、完整可用。`engine.py` 未接入才是真正的问题。

**影响**: 修复从"实现 JIT"降级为"接入 JIT"——约 0.5 天 vs 2 天。

### 错误 2: 线程安全已实现

**文档声称** (§6.3):
> "shared/config_loader.py 中 GlobalConfig 使用 _instance 类变量，无 threading.Lock 保护"

**实际代码** (`config_loader.py:17-25`):
```python
class GlobalConfig:
    _instance = None
    _lock = threading.Lock()
    ...
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
```
**已完全实现**双重检查锁定模式。P2.3 应标记为"已完成"。

### 错误 3: constants 结构描述不准确

**文档声称** (>4 处引用 `shared/constants.py` 为 1139 行单文件)

**实际代码**: `shared/constants/` 是**目录**，含 7 个文件:
- `constants/__init__.py` (145 行，总导出入口)
- `constants/market.py`, `constants/risk.py`, `constants/technical.py`
- `constants/data.py`, `constants/path.py`, `constants/misc.py`

**总计**: 1214 行，但分布在 7 个文件中。引用 `shared/constants` 的方式是正确的（Python 包），但描述为"单文件 1139 行"是错误的。

---

## 2. Phase 依赖验证

### Phase 0.0 (导入链健壮性)
| 预置条件 | 实际状态 | 验证 |
|----------|---------|------|
| services/__init__.py 幽灵导入 | `__getattr__` 懒加载，零导入 | ✅ 无需修复 |
| brain/lppl/__init__.py 幽灵导入 | try/except 条件导入，目标全存在 | ✅ 无需修复 |
| brain/fsm/fsm.py Indicators 导入 | try/except 已保护 | ⚠️ 需链路测试 |
| engine_factory 参数错配 | 仍存在(DecisionBrain 不接受 orchestrator) | ❌ 需修复 |

### Phase 0.1 (正确性修复)
| 文件 | 文档路径 | 实际路径 | 验证 |
|------|---------|----------|------|
| engine.py 硬编码 // 100 | `:103` | 实际在 `execute_buy():121` | ✅ 存在，行号偏差 |
| unified_matching_engine.py // 100 | `:97` | 实际在 `fill_buy():143` | ✅ 存在，行号偏差 |
| shared/t1_checker.py | 新建 | 不存在 | ✅ 待新建 |
| data/fq/ 目录 | 新建 | 不存在 | ✅ 待新建 |

### Phase 1 (重要改进)
| 文件 | 状态 | 验证 |
|------|------|------|
| shared/a_share_rules.py | 不存在 | ✅ 待新建 |
| LPPL JIT 接入 | engine.py 未 import 任何 numba 函数 | ✅ 需接入 |
| numba_optimizer.py JIT 函数 | 已全部 @njit 编译 | ❌ 文档误判为未编译 |

### Phase 2 (架构优化)
| 项 | 状态 | 验证 |
|-----|------|------|
| limit_checker 统一 | get_board_type() 仍返回字符串 | ✅ 需重构 |
| 异常统一化 | 67 处 raise ValueError/RuntimeError 仍存在 | ✅ 需替换 |
| 线程安全 | GlobalConfig 已双检锁 | ❌ 已完成 |

### Phase 3 (功能增强)
| 项 | 状态 | 验证 |
|-----|------|------|
| risk/stop_loss.py | 不存在 | ✅ 需新建 |
| hands/backtest/stop_loss.py | 不存在 | ✅ 需新建 |
| volume_factors.py | 不存在 | ✅ 需新建 |
| sector_factors.py | 不存在 | ✅ 需新建 |

---

## 3. 跨文档一致性检查

| 冲突项 | 子文档 | 主方案 | 状态 |
|--------|--------|--------|------|
| 止损位置 | BACKTEST: `hands/backtest/stop_loss.py` | RISK: `risk/stop_loss.py` | 已声明 |
| T+1 检查 | BACKTEST: `unified_matching_engine` 实例方法 | 主方案: `shared/t1_checker.py` | 可共存 |
| EVTRisk 重命名 | RISK 文档: P0 项 | 主方案: 未收录 | ⚠️ 遗漏 |
| PortfolioSizer | RISK 文档: P0 项 | 主方案: 未收录 | ⚠️ 遗漏 |
| PyArrow 列裁剪 | PERFORMANCE 文档: Phase 2 | 主方案: 未收录 | ⚠️ 遗漏 |

---

## 4. 子文档引用验证

### OPTIMIZATION_BACKTEST_ENGINE.md
- 5 个问题列表: 手数取整、T+1、佣金重算、涨跌停/ST、多空信号
- 主方案涵盖了 #1-2 但缺少 #3-5

### OPTIMIZATION_RISK_MODULE.md
- 要求 EVTRisk → RiskManager 重命名 (主方案没提)
- 要求 PortfolioSizer 不可变性 (主方案没提)
- 要求 DynamicPenaltyCalculator 替代固定 1.2x (主方案 P3.2 有)
- 要求 StopLossPolicy (主方案 P3.3 有，但位置冲突已声明)

### OPTIMIZATION_PERFORMANCE.md
- PyArrow 列裁剪 (3-5x I/O) — 主方案遗漏
- 并行数据加载 (4-8x) — 主方案遗漏
- LRU 缓存 — 主方案遗漏
- LPPL JIT — 已覆盖

---

## 5. 新发现的问题

### 5.1 get_efficient_frontier 损坏
**文件**: `risk/portfolio_optimizer.py:250`
**问题**: `get_efficient_frontier()` 在循环中修改 `self.config.target_return`，但优化器内部使用该状态。并发调用会互相污染。无线程安全保护。

**证据**: `portfolio_optimizer.py:258-267` — 循环设置 target_return，调用优化，再恢复。

### 5.2 回测 engine.py 佣金未在仓位调整后重算
**文件**: `hands/backtest/engine.py:117-123`
**问题**: 在现金不足时缩减仓位后 (`shares = int((self.cash - commission) / exec_price)`)，**佣金未重算**——使用了原始佣金，但仓位已变。

被 REVIEW 文档和在 P0 依赖图中提到但未明确列在文件变更清单中。

### 5.3 unified_matching_engine 硬编码 BOARD_PREFIX 检查
**文件**: `unified_matching_engine.py:148`
**问题**: 整手取整 `// 100 * 100` 硬编码，与 `market_rules.py` 的解耦方案不一致。

### 5.4 测试覆盖率缺失
**文件**: `tests/`
- 无 `test_engine*.py` 覆盖回测
- 无 `test_sizer*.py` 覆盖风控
- 无法验证任何 P0/P1 修改

---

## 6. 输出

```json
{
  "document_score": 7.0,
  "critical_errors": [
    {
      "section": "5.3 (LPPL JIT)",
      "issue": "文档声称 numba_optimizer.py 的 cost_function_reduced() 未使用 JIT 编译，实际 _reduced_cost_numba()、_solve_linear_parameters_numba()、_de_solve_numba() 均已包含 @njit(cache=True, fastmath=True) 完整 JIT 编译。函数名也存在差异（文档写 cost_function_reduced，实际名 _reduced_cost_numba）。",
      "source_evidence": "brain/lppl/numba_optimizer.py:20-264",
      "severity": "HIGH"
    },
    {
      "section": "6.3 (线程安全)",
      "issue": "文档声称 GlobalConfig 单例模式无锁保护，实际 config_loader.py:17-25 已实现 threading.Lock() + 双重检查锁模式。P2.3 已无需修复。",
      "source_evidence": "shared/config_loader.py:17-25",
      "severity": "HIGH"
    },
    {
      "section": "所有引用 constants.py 的地方",
      "issue": "文档将 shared/constants 描述为单文件 1139 行，实际是含 7 个子模块的目录包（共 1214 行分布在 7 个文件中）。所有引用应使用常数包路径。",
      "source_evidence": "shared/constants/ (目录, 7 个 .py 文件)",
      "severity": "MEDIUM"
    }
  ],
  "v2_fix_verification": [
    {
      "issue": "幽灵导入计数 (v1 报告 #1)",
      "was_fixed": false,
      "current_state": "v2 文档 P0.0 声称 services/__init__.py 有 8 个幽灵导入、brain/lppl/__init__.py 有 7 个，但实际代码中 services/ 使用 __getattr__ 懒加载（零直接导入，14 个目标文件全部存在），lppl/ 使用 try/except 条件导入（5 个目标全部存在）。'幽灵导入'描述已过时，但 v2 文档仍按错误数据描述。"
    },
    {
      "issue": "文件数偏差 (v1 报告 #2)",
      "was_fixed": true,
      "current_state": "v2 文档 231 文件计数 100% 准确。brain=47, data=65, hands=32, risk=7, services=28, shared=37, signal=6, ui=8。"
    },
    {
      "issue": "止损模块冲突 (v1 报告 #3/7)",
      "was_fixed": "partial",
      "current_state": "主方案 v2 声明了冲突和统一方案(r→isk/stop_loss.py 定义接口, hands/ 引用)。但 OPTIMIZATION_BACKTEST_ENGINE.md 和 OPTIMIZATION_RISK_MODULE.md 子文档未同步更新。"
    },
    {
      "issue": "P0.3 复权因子工期 (v1 报告 #4)",
      "was_fixed": true,
      "current_state": "v2 文档已将工期从 2 天扩展至 4-5 天。data/fq/ 目录确实不存在，评估合理。"
    },
    {
      "issue": "P2.2 异常统一化工期 (v1 报告 #5)",
      "was_fixed": true,
      "current_state": "v2 文档从 1 天扩展到 3-4 天。实际扫描显示共 67 处需替换，评估合理。"
    },
    {
      "issue": "AGENTS.md 过时 (v1 报告 #6)",
      "was_fixed": false,
      "current_state": "v2 文档声明了 'AGENTS.md 严重过时' 但未提供更新。AGENTS.md 仍声称 data/ 不存在/hands/ 仅空壳/risk/ 仅1文件/brain/ 仅5文件——全部错误。"
    },
    {
      "issue": "T+1 位置不统一 (v1 报告 #8)",
      "was_fixed": true,
      "current_state": "v2 文档提供了 shared/t1_checker.py 与 unified_matching_engine 共存的合理方案。"
    },
    {
      "issue": "Phase 0.0 独立存在 (v1 报告 #9)",
      "was_fixed": true,
      "current_state": "v2 文档新增 Phase 0.0。但内容基于过时幽灵导入数据。"
    },
    {
      "issue": "性能优化遗漏 PyArrow/并行加载 (v1 报告 #10)",
      "was_fixed": false,
      "current_state": "v2 文档未纳入 PyArrow 列裁剪和并行数据加载。OPTIMIZATION_PERFORMANCE.md 中这些项仍被排除在主方案外。"
    }
  ],
  "new_issues_not_in_any_review": [
    {
      "section": "附录 A",
      "issue": "get_efficient_frontier() 方法中 'orchestrator' 拼写错误（应为 'orchestrator'），但与 engine_factory 实际使用的参数名一致。这是贯穿 project 的拼写错误，影响所有 9 个引擎的工厂初始化。",
      "source_evidence": "services/analysis/engine_factory.py:24",
      "severity": "MEDIUM"
    },
    {
      "section": "P0 验收标准",
      "issue": "67 处 raise ValueError/RuntimeError/TypeError/KeyError 分布在 231 个源文件中。需创建自定义异常映射表，而不仅仅是统一替换。shared/exceptions.py 有 37 个异常类，但覆盖率仅为约 55%。",
      "source_evidence": "grep 结果: 67 处匹配",
      "severity": "MEDIUM"
    },
    {
      "section": "P0.1/4.1",
      "issue": "engine.py:execute_buy() 在现金不足缩减仓位后未重算佣金（使用原始 commission 但仓位已变）。即使修复手数取整，佣金计算仍可能偏差。",
      "source_evidence": "hands/backtest/engine.py:117-123",
      "severity": "HIGH"
    },
    {
      "section": "P2/6.1",
      "issue": "unified_matching_engine.py 的 compute_limit_status_vectorized 使用 MarketConstants.LIMIT_RATIO + get_board_type()（字符串），而 market_rules.py 使用 BoardType 枚举 + BOARD_RULES 字典。两个板块识别系统并存且映射关系不完整。",
      "source_evidence": "hands/backtest/unified_matching_engine.py:77-88, shared/market_rules.py:1-35, shared/limit_checker.py:40-60",
      "severity": "MEDIUM"
    },
    {
      "section": "P1/5.3",
      "issue": "LPPL numba_optimizer 的 JIT 函数虽已实现，但全局种子 np.random.seed(seed) 调用是线程不安全的——在多窗口并行 fitting 中会产生竞态条件。",
      "source_evidence": "brain/lppl/numba_optimizer.py:100（_de_solve_numba 中的 np.random.seed）",
      "severity": "MEDIUM"
    }
  ],
  "action_items": [
    "修复 engine_factory _lazy_init(): 使用 inspect.signature 检查 orchestrator 参数，避免 DecisionBrain 等不接受 orchestrator 的引擎静默失败 (0.5 天)",
    "验证 LPPL engine.py 是否已接入 numba_optimizer（当前未接入），若未接入则添加导入路径 (0.5 天)",
    "将 P2.3（线程安全）从计划中移除——GlobalConfig 已实现双检锁",
    "将 P1.3（LPPL JIT 实现）降级为 'LPPL JIT 接入'——JIT 已实现，只需在 engine.py 中导入 numba 函数",
    "更新 AGENTS.md 文件计数为 231，修正 data/hands/risk/brain 状态描述",
    "在两个子文档（BACKTEST_ENGINE.md, RISK_MODULE.md）顶部添加 '以 OPTIMIZATION_MASTER_PLAN.md §7.3 为准' 引用",
    "将 EVTRisk 重命名 + PortfolioSizer 不可变性纳入 Phase 0.1（工作量 <1 天）",
    "将 PyArrow 列裁剪纳入 Phase 1（低风险高收益，3-5x I/O 提升）",
    "补充 test_engine.py 基础回测测试覆盖后再开始 P0.1 修改",
    "修复 engine.py execute_buy() 的佣金未重算问题（与手数取整同位置修复）"
  ]
}
```
