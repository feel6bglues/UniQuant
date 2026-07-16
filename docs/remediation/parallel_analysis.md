# UniQuant 修复工作并行化分析报告

> **日期**: 2026-07-10 | **分析基础**: 34 项修复任务, 逐文件依赖分析
> **核心约束**: 同一文件的多处编辑必须串行 (git 冲突), 不同文件可全并行
> **结论**: 原 24h 挂钟 → 优化后 **7.5h** (3.2x 加速), 4 工程师并行

---

## 并行化核心原则

| 约束 | 说明 | 例外 |
|:-----|:------|:-----|
| **同一文件串行** | 同一文件的多次编辑必须串行, 避免冲突 | 文件内不同区域的编辑可由同一 agent 串行处理 |
| **跨文件并行** | 不同文件的编辑无依赖关系, 可全并行 | 无 |
| **测试与源文件并行** | 测试文件独立于源文件, 可并行编辑 | 测试验证必须等源文件编辑完成后 |
| **门禁串行** | `pytest` / `ruff` / `scan` 是最终验证, 必须等所有编辑完成后 | 无 |

---

## Phase 0 并行分析 (P0 紧急修复)

### 文件依赖图

```
research_pipeline.py ─┬─ E-13 (line 562) ── E-14 (line 638) ── TS-01 (line 149-540)
                       │   [串行: 3 处 edit, 因为同一文件, 1h5m]
                       └── 瓶颈路径 ── 最长串行链

akshare_wrapper.py   ── E-10 (line 83) ── E-11 (line 99) ── E-12 (line 107)
                       [串行: 3 处 edit, 6m]

lppl/computation.py  ── E-03 (line 73) ── E-04 (line 223) ── E-05 (line 293)
                       [串行: 3 处 edit, 15m]

lppl/calculator.py   ── E-01 (line 118) ── E-02 (line 480)  [串行: 2 处 edit, 4m]

lppl/numba_optimizer.py ─ E-06 (line 91) ── E-07 (line 171)  [串行: 2 处 edit, 4m]

lppl/visualizer.py   ── E-08 (line 101) ── E-15 (line 182)  [串行: 2 处 edit, 4m]

lppl/data_manager.py ── E-09 (line 117)  [1 处 edit, 2m]

unified_engine.py    ── TS-02 (line 410)  [1 处 edit, 10m]
```

### 最大并行调度

```
Wave 1: 8 路并行 (15m 挂钟) ─────────────────────────────
  Agent 1: research_pipeline.py (E-13→E-14)       [4m]
  Agent 2: akshare_wrapper.py (E-10→E-11→E-12)    [6m]
  Agent 3: lppl/computation.py (E-03→E-04→E-05)   [15m] ← 最长路径
  Agent 4: lppl/calculator.py (E-01→E-02)          [4m]
  Agent 5: lppl/numba_optimizer.py (E-06→E-07)     [4m]
  Agent 6: lppl/visualizer.py (E-08→E-15)          [4m]
  Agent 7: lppl/data_manager.py (E-09)             [2m]
  Agent 8: unified_engine.py (TS-02)               [10m]
  └─ 全部完成后, 所有 Agent 汇合, 运行门禁

Wave 2: 1 路串行 (1h5m 挂钟) ──────────────────────────
  Agent 1: research_pipeline.py (TS-01 + E-13/E-14 已合并) [1h5m]
  └─ 这是因为 TS-01 和 E-13/E-14 都在同一文件, 必须串行
  └─ 但 TS-01 需要 1h (线程安全设计), 这是 Phase 0 的瓶颈

Phase 0 门禁: pytest + ruff + grep LPPL except=0  [5m]
```

**Phase 0 挂钟**: 15m (Wave 1) + 1h5m (Wave 2) + 5m (gate) = **~1h25m**

---

## Phase 1 并行分析 (P1 工程健康)

### 文件依赖图

```
所有 11 个文件完全独立, 无冲突:
  analysis_service_legacy.py  ─── DC-01 (archive)
  signal/quality.py            ─── DC-02 (marker)
  shared/price_collar.py       ─── DC-03 (archive)
  shared/slippage_model.py     ─── DC-04 (marker)
  portfolio_engine.py          ─── DC-06 (marker)
  tests/ (56 弱断言)           ─── DC-05 (4 子路并行)
  tests/test_adapters.py       ─── TC-01 (new tests)
  tests/test_arbitrator.py     ─── TC-02 (new tests)
  tests/test_unified_engine.py ─── TC-03 (new tests)
  tests/test_matching.py       ─── TC-04 (new tests)
  tests/test_analysis_v2.py    ─── TC-05 (new tests)
```

### 最大并行调度

```
Wave 3: 14 路并行 (2h 挂钟) ────────────────────────────
  Agent 1:  DC-01 (archive legacy.py)          [1h]
  Agent 2:  DC-03 (archive price_collar.py)    [30m]
  Agent 3:  DC-02 + DC-04 + DC-06 (markers)   [15m] (3 独立文件, 1 agent)
  Agent 4-7: DC-05 弱断言 (4 路并行, 每路 ~14 测试) [1h]
              ├─ Agent 4: tests/brain/    [1h]
              ├─ Agent 5: tests/data/     [1h]
              ├─ Agent 6: tests/signal/   [1h]
              └─ Agent 7: tests/hands/  [1h]
  Agent 8:  TC-01 (adapters tests)           [2h] ← 最长路径
  Agent 9:  TC-02 (arbitrator tests)         [1h]
  Agent 10: TC-03 (unified_engine tests)     [2h] ← 最长路径
  Agent 11: TC-04 (matching engine tests)    [2h] ← 最长路径
  Agent 12: TC-05 (analysis_v2 tests)        [2h] ← 最长路径
  
Phase 1 门禁: canary 20/20 + coverage >=52%  [5m]
```

**Phase 1 挂钟**: 2h (Wave 3) + 5m (gate) = **~2h 5m**

---

## Phase 2 并行分析 (P2 优化改进)

### 文件依赖图

```
所有 6 个任务完全独立:
  RD-01 (portfolio research)    ─── 设计文档
  RD-02 (metrics design)        ─── 设计文档
  DA-01 (docs/reanalysis/*.md)  ─── 文档修改
  DA-02 (AGENTS.md)             ─── 单文件
  DA-03 (config/config.yaml)    ─── 单文件
  DA-04 (shared/optimal_params) ─── 单文件
```

### 最大并行调度

```
Wave 5+6: 6 路并行 (4h 挂钟) ────────────────────────────
  Agent 1:  RD-01 (portfolio research design)   [4h] ← 最长路径
  Agent 2:  RD-02 (metrics system design)       [4h] ← 最长路径
  Agent 3:  DA-01 (batch fix docs)              [2h]
  Agent 4:  DA-02 (update AGENTS.md)            [30m]
  Agent 5:  DA-03 (verify config.yaml)          [1h]
  Agent 6:  DA-04 (verify optimal_params)       [1h]

Phase 2 门禁: coverage >=55% + doc paths 100%   [5m]
```

**Phase 2 挂钟**: 4h (Wave 5+6) + 5m (gate) = **~4h 5m**

---

## 三阶段并行对比

| 阶段 | 原计划挂钟 | 最大并行后 | 加速比 | 并行 Agent 数 |
|:----:|:---------:|:----------:|:------:|:-------------:|
| Phase 0 | 8h | 1h 25m | **5.6x** | 8 → 1 |
| Phase 1 | 10h | 2h 5m | **4.8x** | 14 → 1 |
| Phase 2 | 6h | 4h 5m | **1.5x** | 6 → 1 |
| **总计** | **24h** | **7h 35m** | **3.2x** | |

---

## 瓶颈分析

### 阶段瓶颈

| 阶段 | 瓶颈 | 原因 | 优化空间 |
|:----:|:------|:-----|:---------|
| Phase 0 | `research_pipeline.py` 1h5m | TS-01 线程安全设计 + E-13/E-14 在同一文件 | 低: 文件内编辑必须串行 |
| Phase 1 | TC-01/03/04/05 各 2h | 测试编写时间, 4 路并行 | 无: 可并行 |
| Phase 2 | RD-01/RD-02 各 4h | 架构设计文档编写 | 低: 设计工作难以并行加速 |

### 资源需求

若用 **4 工程师**:

| 阶段 | 工程师数 | 挂钟 | 并行策略 |
|:----:|:--------:|:----:|:---------|
| Phase 0 | 4 | 1h 25m | 每人 2 文件, 共 8 文件并行 |
| Phase 1 | 4 | 2h 5m | 每人 3-4 任务, 共 14 任务并行 |
| Phase 2 | 2 | 4h 5m | 每人 3 任务, 共 6 任务并行 |

### 最大加速配置 (4 工程师, 全部并行)

```
Day 1 (7.5h):
  ┌─────────────────────────────────────────────────────────┐
  │ Phase 0 (1.5h)                                          │
  │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │
  │   │ Eng1 │ │ Eng2 │ │ Eng3 │ │ Eng4 │  → Gate          │
  │   │ 2 fp │ │ 2 fp │ │ 2 fp │ │ 2 fp │                  │
  │   └──────┘ └──────┘ └──────┘ └──────┘                  │
  │ [research_pipeline 串行瓶颈: Eng1 继续 1h]               │
  ├─────────────────────────────────────────────────────────┤
  │ Phase 1 (2h)                                            │
  │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │
  │   │ Eng1 │ │ Eng2 │ │ Eng3 │ │ Eng4 │  → Gate          │
  │   │ DC   │ │ DC   │ │ TC   │ │ TC   │                  │
  │   └──────┘ └──────┘ └──────┘ └──────┘                  │
  ├─────────────────────────────────────────────────────────┤
  │ Phase 2 (4h)                                            │
  │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │
  │   │ Eng1 │ │ Eng2 │ │ Eng3 │ │ Eng4 │  → Gate          │
  │   │ RD   │ │ RD   │ │ DA   │ │ DA   │                  │
  │   └──────┘ └──────┘ └──────┘ └──────┘                  │
  └─────────────────────────────────────────────────────────┘
```

---

## 结论

| 资源 | 原计划挂钟 | 优化后挂钟 | 加速比 |
|:----:|:---------:|:----------:|:------:|
| 1 工程师 (串行) | 30.5 人时 | 30.5 人时 | 1x |
| 4 工程师 (最大并行) | 24h | **7.5h** | **3.2x** |
| 8 工程师 (Phase 0 饱和) | 8h | **1.5h** | **5.3x** |

**关键瓶颈**: `research_pipeline.py` 3 处编辑 (E-13→E-14→TS-01) 必须串行, 1h5m 是 Phase 0 的挂钟瓶颈. 无法通过增加工程师进一步加速.

**建议**: 4 工程师 1 天完成全部 34 项修复. 或 1 工程师 3 天 (串行, 含测试验证).