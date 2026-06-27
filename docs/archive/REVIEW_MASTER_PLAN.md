# 总体优化方案审查报告

> 审查日期: 2026-05-31 | 审查对象: `OPTIMIZATION_MASTER_PLAN.md` v1.0
> 交叉审查: `AGENTS.md`, 4 份子优化文档, 实际源码 (231 个 .py 文件)

---

## 1. 总体评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 方案完整性 | 6/10 | 遗漏关键阻塞问题, 模块规模严重低估 |
| 事实准确性 | 4/10 | 文件数偏差 37%, 全量误差 85 个文件 |
| 依赖分析 | 7/10 | 主链条正确, 但缺少跨 doc 冲突识别 |
| 进度估算 | 5/10 | 低估 P0.3 和 P2.2, 未计入幽灵导入修复 |
| 跨文档一致性 | 4/10 | 两处止损模块冲突, T+1 位置不统一 |
| 风险识别 | 6/10 | 遗漏最大风险: 导入阻塞阻止所有测试 |

**综合评分: 5.3/10** — 核心方向正确 (P0 手数取整 / T+1 优先级合理), 但文件数和进度估算存在严重事实错误, 遗漏关键阻塞问题, 跨文档止损策略存在冲突。

---

## 2. 事实准确性 (严重)

### 2.1 实际文件数 vs 文档声明

| 模块 | 文档声称 | 实际 | 偏差 | 严重度 |
|------|---------|------|------|--------|
| shared/ | 23 | **37** | +61% | 🔴 |
| data/ | 62 | **65** | +5% (可接受) | 🟢 |
| brain/ | 11 | **47** | +327% | **🔴🔴** |
| hands/ | 32 | **32** | 0% ✅ | 🟢 |
| risk/ | 7 | **7** | 0% ✅ | 🟢 |
| services/ | 11 | **28** | +155% | 🔴 |
| ui/ | 未计入 | **8** | — | 🟡 |
| signal/ | 未计入 | **6** | — | 🟡 |
| **总计** | **146** | **231** | **+58%** | **🔴** |

brain/ 偏差 327% 是致命错误。`brain/wyckoff/` 有 12 个文件, `brain/lppl/` 有 11 个, `brain/factors/` 有 9 个。文档声称 brain=11, 仅 wyckoff 一个子目录就已经超出。

后果: 方案以 146 个文件为基础估算工作量, 实际需处理 231 个文件, 偏差 85 个文件。P2.2 "统一异常定义" 的扫描/替换工作量被低估约 60%。

### 2.2 AGENTS.md 与优化文档的矛盾

AGENTS.md (v0.3) 声称:
- `data/` 整层不存在 → **错误**: 实际 65 个文件, 9 个子目录
- `hands/` 仅 __init__.py → **错误**: 实际 32 个文件, 8 个子目录 (含 backtest, strategies, tuning)
- `risk/` 仅 drawdown_analyzer → **错误**: 实际 7 个文件 (sizer, portfolio_optimizer, evt_risk 等均存在)
- `brain/` 仅 5 个文件 → **错误**: 实际 47 个文件

结论: AGENTS.md 严重过时 (标记 v0.3), 优化文档虽更接近实际但仍有 ~37% 偏差。**两个文档均不可完全信任作为文件计数依据。**

### 2.3 性能基线问题

文档声称:
- LPPL cost_function 每次调用 ~25μs → 需确认实际环境, Numba JIT 后 ~3μs 合理
- Factors compute_all (10 因子) ~76.5s → 代码中未见对应的批量基准测试, 无法验证
- MatchingEngine fill_buy/sell ~O(n) → 描述模糊, 不是可验证的数字

建议: 添加实际的 `timeit` 或 `pytest-benchmark` 基线测试, 而非估算数字。

---

## 3. 进度安排评估

### 3.1 逐周分析

#### Week 1 (P0): 估计 5 天, 实际需要 7-8 天

| 任务 | 文档估算 | 实际评价 |
|------|---------|----------|
| P0.1 手数取整 | 1 天 | ✅ 合理, ~10 LOC 修改 |
| P0.2 T+1 检查 | 2 天 | ✅ 合理, 新建文件 + 2 处集成 |
| P0.3 复权因子 | 2 天 | **🔴 严重低估**. 新建 `data/fq/` 模块含 2+ 文件, 对接 AKShare/TDX 两个数据源, 编写复权算法, 验证价格一致性. 实际需 4-5 天. |

此外, Week 1 **未包含**幽灵导入修复 (`services/__init__.py` 8 个 + `brain/lppl/__init__.py` 7 个 + `brain/fsm/fsm.py` 1 个 = 16 个破坏性导入), 修复这些是最基本的先决条件。

#### Week 3 (P2): 估计 5 天, 实际需要 7-8 天

| 任务 | 文档估算 | 实际评价 |
|------|---------|----------|
| P2.1 统一板块识别 | 1 天 | ✅ 合理 |
| P2.2 统一异常定义 | 1 天 | **🔴 严重低估**. 扫描 231 个文件的 `raise ValueError/RuntimeError`, 逐一替换为 37 个自定义异常, 跨模块回归测试. 实际需 3-4 天. |
| P2.3 线程安全 | 1 天 | ✅ 合理 |

P2.2 被分配 1 天 (周二), 但同日还要做 P2.1 的统一测试。这是不可能的。

### 3.2 总体进度评估

| 阶段 | 文档估算 | 实际估计 | 偏差 |
|------|---------|----------|------|
| Week 1 (P0) | 5 天 | 7-8 天 | -40% |
| Week 2 (P1) | 5 天 | 5 天 | 0% |
| Week 3 (P2) | 5 天 | 7-8 天 | -40% |
| Week 4 (P3) | 5 天 | 4-5 天 | 0% |
| **合计** | **20 天 (4 周)** | **23-26 天 (5-6 周)** | **-15% 到 -30%** |

**结论**: 4 周过于激进, 合理估计为 **5-6 周**。主要瓶颈: P0.3 复权因子 + 幽灵导入修复 (Week 1) 和 P2.2 异常统一化 (Week 3)。

---

## 4. 依赖分析

### 4.1 正确的依赖链

```
幽灵导入修复 (缺失) ──→ 一切测试 (先决条件)
         │
         ▼
P0 手数取整 ──→ P1 A 股规则门面 ──→ P1 回测引擎集成
P0 T+1 检查 ──→ P2 统一板块识别
P1 A 股规则门面 ──→ P3 动态 T+1 惩罚
P1 LPPL JIT ──→ P3 因子扩展 (性能基础)
```

文档的依赖链基本正确。但遗漏了最重要的前置依赖。

### 4.2 遗漏的依赖 (严重)

**缺失 #1: 幽灵导入修复 → 所有模块的测试**

`services/__init__.py` 有 8 个不存在的导入 (如 `CacheService`, `DataCacheCoordinator`, `FeatureEngineeringService`, `SignalCombinationService`), `brain/lppl/__init__.py` 有 7 个不存在的导入. 除非先修复这些, 否则 `import uniquant.services` 崩溃, 所有涉及 services 的测试无法运行。

**这是个 P0 级阻塞问题, 但优化方案完全未提及。**

**缺失 #2: `brain/fsm/fsm.py` 的 `from ..indicators import Indicators`**
- 这行导入不存在, FSM/DecisionBrain 崩溃
- 影响 `brain/fsm/` 和所有使用 FSM 的策略

**缺失 #3: `engine_factory` 参数错配**
- 影响所有 9 个引擎的初始化

### 4.3 跨文档冲突

**止损模块位置冲突 (🔴 严重):**

| 文档 | 位置 | 类名 | 职责 |
|------|------|------|------|
| `OPTIMIZATION_BACKTEST_ENGINE.md` | `hands/backtest/stop_loss.py` | `StopLossManager` | 回测执行时检查止损 |
| `OPTIMIZATION_RISK_MODULE.md` | `risk/stop_loss.py` | `StopLossPolicy` (ABC) | 止损策略抽象接口 |

两者定位不同 (回测引擎 vs 风险模块), 但职责重叠。如果同时实现, 开发人员将面对 "到底用哪个" 的困惑。

**建议**: 统一到 `risk/stop_loss.py` 定义策略接口, `hands/backtest/` 引用风险模块, 保持 5 层 DAG 的单向依赖。

**T+1 检查位置冲突 (🟡 中):**

| 文档 | 位置 | 方式 |
|------|------|------|
| 主方案 (P0.2) | `shared/t1_checker.py` | 独立函数 |
| 回测引擎文档 | `unified_matching_engine.py` 的 `_check_t1_vectorized` | 实例方法 |

可以共存 (shared 提供纯函数, engine 封装实例方法), 但文档未说明其关系, 可能造成重复实现。

---

## 5. 差距分析

### 5.1 方案完全遗漏的工作项

| # | 工作项 | 优先级 | 影响 | 建议归属 |
|---|--------|--------|------|----------|
| 1 | 修复 services/__init__.py 8 个幽灵导入 | **P0** | 导入链崩溃, 所有测试阻塞 | 新增 Phase 0.0 |
| 2 | 修复 brain/lppl/__init__.py 7 个幽灵导入 | **P0** | LPPL 引擎不可用 | 新增 Phase 0.0 |
| 3 | 修复 brain/fsm/fsm.py 的 `from ..indicators import Indicators` | **P0** | FSM/DecisionBrain 崩溃 | 新增 Phase 0.0 |
| 4 | 修复 engine_factory 构造函数参数错配 | **P0** | 9 个引擎无法初始化 | 新增 Phase 0.0 |
| 5 | PyArrow 列裁剪: `storage_manager.py` 列裁剪 | **P1** | 全量加载性能浪费 60-80% | 并入 Phase 1 (性能) |
| 6 | 并行数据加载: `batch_read_data_parallel` | **P1** | 5000 只股票加载 ~75s→~12s | 并入 Phase 1 (性能) |
| 7 | LRU 数据缓存 | **P2** | 重复读取相同文件 | 并入 Phase 2 |
| 8 | Wyckoff itertuples 向量化 | **P3** | 小窗口, 优先级最低 | 保留 P3 |
| 9 | `services/` 模块测试覆盖 | **P1** | 28 个服务文件几乎无测试 | 新增 |
| 10 | `signal/` 模块 (6 个文件) | 待定 | 信号归一化/聚合, 无计划 | 讨论归属 |

### 5.2 "Phase 0" 应独立存在

当前方案将 P0 定位为紧急正确性修复, 但遗漏了更紧急的"让代码可以导入"的阻塞问题。建议:

```
Phase 0.0: 修复导入链 (1-2 天)
  ├── 修复 services/__init__.py 幽灵导入
  ├── 修复 brain/lppl/__init__.py 幽灵导入
  ├── 修复 brain/fsm/fsm.py 的 Indicators 导入
  ├── 修复 engine_factory 构造函数参数
  └── 验证: python -c "import uniquant; import uniquant.services; print('OK')"

Phase 0.1 (原 P0): 正确性修复 (5-7 天)
  ├── 原 P0.1 手数取整
  ├── 原 P0.2 T+1 检查
  └── 原 P0.3 复权因子
```

---

## 6. 跨文档一致性详细比对

### 6.1 A 股规则模块

| 主方案 | `OPTIMIZATION_A_SHARE_RULES_MODULE.md` | 一致? |
|--------|----------------------------------------|-------|
| P1.1 创建 `shared/a_share_rules.py` | 完整设计: BoardType/LimitMoveType/VolumeLevel/T1RiskLevel | ✅ |
| P1.2 集成引擎 | 未提及引擎集成 (focus 在 Wyckoff 迁移) | 🟡 范围不同 |
| P2.1 统一 limit_checker | Phase 1 兼容层 + Phase 3 清理 | ✅ |

### 6.2 回测引擎

| 主方案 | `OPTIMIZATION_BACKTEST_ENGINE.md` | 一致? |
|--------|-----------------------------------|-------|
| P0.1 手数取整 | 5 个问题中的 #2 | ✅ |
| P0.2 T+1 检查 | 5 个问题中的 #1 | 🟡 位置不同 |
| P1.2 集成 a_share_rules | 未提及 | ❌ 回测文档用 market_rules 直接导入 |
| 新增止损 | P3.3 流动性感知止损 | 🔴 止损模块位置冲突 |

### 6.3 性能优化

| 主方案 | `OPTIMIZATION_PERFORMANCE.md` | 一致? |
|--------|------------------------------|-------|
| P1.3 LPPL JIT | Phase 1 (1-2 天) | ✅ |
| 未提及 | Phase 2 PyArrow 列裁剪 | ❌ 遗漏 |
| 未提及 | Phase 2 并行加载 | ❌ 遗漏 |
| 未提及 | Phase 3 LRU 缓存 | ❌ 遗漏 |

### 6.4 风控模块

| 主方案 | `OPTIMIZATION_RISK_MODULE.md` | 一致? |
|--------|------------------------------|-------|
| P3.2 动态 T+1 惩罚 | Phase 2 DynamicPenaltyCalculator | ✅ |
| P3.3 流动性止损 | Phase 2 StopLossPolicy | 🟡 与回测 doc 冲突 |
| 未提及 | P0 EVTRisk 重命名 | ❌ 遗漏 |
| 未提及 | P0 PortfolioSizer 不可变性 | ❌ 遗漏 |
| 未提及 | P2 真 EVT 实现 | ❌ 遗漏 |
| 未提及 | P2 路径压力测试 | ❌ 遗漏 |

---

## 7. 风险评估补充

### 7.1 文档已识别的风险

| 风险 | 评价 |
|------|------|
| Numba JIT 不兼容 | 合理, 有 HAS_NUMBA fallback |
| 复权因子数据源不稳定 | 合理, 多源备选 |
| 板块识别边界情况 | 合理, 全覆盖测试 |
| 线程安全死锁 | 合理, 使用 Lock 而非 RLock |

### 7.2 文档遗漏的重大风险

| # | 风险 | 概率 | 影响 | 建议缓解 |
|---|------|------|------|----------|
| 1 | **幽灵导入修复破坏 exports** | 高 | 高 | 修复后立即运行 `python -c "import uniquant; import uniquant.services; print('OK')"` |
| 2 | **AGENTS.md 过时导致决策错误** | 高 | 中 | 更新 AGENTS.md 文件计数和状态 |
| 3 | **文件数偏差 37% 导致人力低估** | 一定 | 高 | 重新估算工作量, 按 230+ 文件而非 146 |
| 4 | **止损模块冲突导致重复实现** | 中 | 中 | 统一到 `risk/stop_loss.py`, 回测引擎引用 |
| 5 | **方案执行中发现 data/ 实际有 65 个文件, 但方案无 data/ 优化** | 中 | 中 | 增加 data/ 模块的数据质量/列裁剪/缓存方案 |
| 6 | **回测引擎无单元测试** | 高 | 高 | `tests/` 下无 `test_engine*.py` 覆盖回测, 修改无保护 |
| 7 | **P0.3 复权因子涉及外部数据源, 无网络则阻塞** | 中 | 高 | 优先使用本地 TDX 缓存 |

---

## 8. 建议修改方案

### 8.1 重新排序的优先级

```
Phase 0.0 (新增, 1-2 天): 修复导入链
  ├── 修复 services/__init__.py 幽灵导入 (8 个)
  ├── 修复 brain/lppl/__init__.py 幽灵导入 (7 个)
  ├── 修复 brain/fsm/fsm.py Indicators 导入
  └── 修复 engine_factory 构造函数参数

Phase 0.1 (原 P0, 5-7 天): 正确性修复
  ├── P0.1 手数取整 (engine.py + unified_matching_engine.py)
  ├── P0.2 T+1 统一检查 (shared/t1_checker.py)
  ├── P0.3 复权因子 (data/fq/ 模块) ← 扩展至 4-5 天
  └── P0.4 EVTRisk 重命名 + PortfolioSizer 不可变性 (risk 模块)

Phase 1 (原 P1 + 性能优化, 5-7 天): 质量改进
  ├── P1.1 A 股规则门面模块
  ├── P1.2 回测引擎集成门面
  ├── P1.3 LPPL Numba JIT 激活
  ├── P1.4 PyArrow 列裁剪 (storage_manager.py)
  └── P1.5 并行数据加载

Phase 2 (原 P2, 5-7 天): 架构优化
  ├── P2.1 统一板块识别
  ├── P2.2 统一异常定义 ← 扩展至 3 天
  ├── P2.3 线程安全
  └── P2.4 LRU 数据缓存

Phase 3 (原 P3, 5 天): 功能增强
  ├── P3.1 因子扩展
  ├── P3.2 动态 T+1 惩罚
  ├── P3.3 止损统一 (risk/stop_loss.py + 回测集成)
  └── P3.4 流动性感知止损

Phase 4 (新增, 预留): 高级风险功能
  ├── 真 EVT GPD 实现
  ├── 路径依赖压力测试
  └── 奇异协方差矩阵处理
```

### 8.2 建议时间线: 6-7 周

```
Week 1-2: Phase 0.0 (导入链) + Phase 0.1 (正确性)
Week 3-4: Phase 1 (门面 + 性能)
Week 5:   Phase 2 (架构)
Week 6:   Phase 3 (功能增强)
Week 7:   Phase 4 (高级风控, 可选)
```

### 8.3 文件变更清单修正

实际受影响的文件不只是附录 A 的 14 个。幽灵导入修复影响:
- `src/uniquant/services/__init__.py`
- `src/uniquant/brain/lppl/__init__.py`
- `src/uniquant/brain/fsm/fsm.py`
- `src/uniquant/services/analysis/engine_factory.py`

加上这些, 总变更文件数从 14 → **18+** (加上各模块 __init__.py 的导出更新)。

---

## 9. 结论

**方案核心方向正确** (手数取整 → A 股规则门面 → 回测引擎集成 → 性能优化的链条是合理的), 但存在以下必须修复的问题:

1. **🔴 致命**: 遗漏幽灵导入修复 (阻止所有测试), 此问题优先级应高于一切
2. **🔴 严重**: 文件数偏差 37% (146 vs 231), 导致工作量估算严重失准
3. **🔴 严重**: 跨文档止损模块冲突 (hands/backtest/stop_loss.py vs risk/stop_loss.py)
4. **🟡 中**: P0.3 复权因子工期低估 2x, P2.2 异常统一化工期低估 3x
5. **🟡 中**: AGENTS.md 严重过时 (声明版本 v0.3), 干扰新入开发者判断
6. **🟢 低**: 性能优化遗漏 PyArrow 列裁剪和并行加载

**建议**: 先修复文件计数和依赖分析, 增加 Phase 0.0 幽灵导入修复, 重新估算为 6-7 周, 统一止损模块位置, 然后按修订后的时间线执行。
