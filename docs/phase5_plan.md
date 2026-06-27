# Phase 5 综合计划 — 清偿 + 验证 + UI 适配

> P0-P3 完成 15 项修复（1267 tests pass, 0 failures, ruff clean）  
> P4 计划已编制（见 `repair_task_schedule_phase4.md`）  
> Phase 5 整合 P4 清偿、golden_100 全量验证、Streamlit UI 适配，作为系统上线前的最后一轮

---

## 范围总览

| 阶段 | 内容 | 文件数 | 变更量 | 工时 |
|---|---|---|---|---|
| **Wave 1** | P4.1a + P4.1b + P4.2a + P4.2b/P4.5 | 5 | +65 | 3.3h |
| **Wave 2** | P4.3 + P4.4 | 2 | +18 | 0.6h |
| **Wave 3** | golden_100 全量验证 + 报告生成 | 0（仅运行） | 0 | ~10min |
| **Wave 4** | Streamlit UI: R² + OOS 显示 | 2 | +10 | 0.5h |
| **Total** | — | 7 文件修改 | ~93 | ~4.5h |

---

## 文件冲突矩阵

| 文件 | Wave | 冲突组 |
|---|---|---|
| `services/analysis/lppl_analysis_engine.py` | W1 | **I** |
| `brain/lppl/engine.py` | W1, W2 | **L** |
| `brain/wyckoff/engine.py` | W1 | **W** |
| `scripts/lppl_wyckoff_cross_validation.py` | W1 | **S** |
| `docs/repair_plan_lppl_wyckoff.md` | W2 | I |
| `ui/dashboard.py` | W4 | **U1** |
| `ui/lppl_visualizer.py` | W4 | **U2** |

---

## 执行编排

### Wave 1 — Day 1（4 任务并行）

| 轨道 | 任务 | 文件 | 变更 | 工时 |
|---|---|---|---|---|
| **I** | **P4.1a** 读取 `r_squared`/`out_of_sample_r_squared` 传入 LPPLOutput | `lppl_analysis_engine.py` | +2 | 0.3h |
| **L** | **P4.1b** `detect_bubble()` 增加 30 日 holdout R² 计算 | `brain/lppl/engine.py` | +25 | 2h |
| **W** | **P4.2a** `_calc_confidence` 增加 bypass 计数器 | `brain/wyckoff/engine.py` | +8 | 0.5h |
| **S** | **P4.2b+P4.5** H6 bypass 统计 + H10 逐股票表 | `scripts/lppl_wyckoff_cross_validation.py` | +30 | 0.5h |

**验证**：`pytest tests/ -q` (1267 pass, 0 fail) + `ruff check src/uniquant/`

### Wave 2 — Day 2（2 任务并行）

| 轨道 | 任务 | 文件 | 变更 | 工时 |
|---|---|---|---|---|
| **L** | **P4.3** LPPLConfig `de_popsize: int = 70` | `brain/lppl/engine.py` | +3 | 0.3h |
| **I** | **P4.4** 文档新增"已知限制—Spring 信号密度" | `docs/repair_plan_lppl_wyckoff.md` | +15 | 0.3h |

**验证**：`python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py`

### Wave 3 — Day 2（1 任务，运行验证）

| 轨道 | 任务 | 命令 | 工时 |
|---|---|---|---|
| **V** | **golden_100 全量验证** | `python3 scripts/lppl_wyckoff_cross_validation.py --stocks golden_100 --output reports/golden_100_full.md` | ~10min |

**验证**：报告含 H1-H12 全部指标，H3 R² 均值 > 0.6，H6 fp_rate < 20%

### Wave 4 — Day 2（2 任务并行，UI 层）

| 轨道 | 任务 | 文件 | 变更 | 工时 |
|---|---|---|---|---|
| **U1** | 仪表盘新增 R² + OOS R² 显示列 | `ui/dashboard.py:1200-1235` | +5 | 0.3h |
| **U2** | 图表标注增加 R²（in + oos） | `ui/lppl_visualizer.py:342` | +5 | 0.2h |

**验证**：`streamlit run src/uniquant/ui/dashboard.py` 视觉确认

---

## 依赖关系图

```
Wave 1 (完全并行)
  P4.1a (I)  ───┐
  P4.1b (L)  ───┤ 同时执行
  P4.2a (W)  ───┤
  P4.2b+S (S) ──┘

Wave 2 (并行)
  P4.3  (L)  ← P4.1b 完成后 → 同文件
  P4.4  (I)  ← P4.1a 完成后 → 不同文件，独立

Wave 3 (单任务)
  golden_100 验证 ← P4.2b/P4.5 完成后
    → 脚本已具备 H6/H10 新统计

Wave 4 (并行)
  U1 (dashboard.py)  ← 无前置依赖（不依赖 LPPLOutput 变更）
  U2 (visualizer.py) ← 无前置依赖（读取 bubble_result dict 而非 LPPLOutput）
```

---

## 三角色审议修正

审议结论记录于 `AGENTS.md` 会话上下文。核心修正：

1. **P4.1b** 技术规范：holdout 分割点 = `len(df) - 30`，固定 tc/m/w 非线性参数，只重拟 a/b/c1/c2 线性参数，计算 `1 - ss_res/ss_tot`
2. **P4.2b** 降级：仅计数器，不做 bypass 正确性验证
3. **P4.5** H10 新增"分歧条目"子表（仅列新旧判定不同的股票）
4. **Wave 4 重分配**：U1a（`r_squared` 显示）提前至 Wave 1；U1b（OOS R²）保留 0.2h；新增 W4.3 Wyckoff 阶段分布可视化 +0.5h

## 修正后总工时

| 阶段 | 原工时 | 修正 | 最终 |
|---|---|---|---|
| Wave 1 | 3.3h | +U1a 0.3h | **3.6h** |
| Wave 2 | 0.6h | — | **0.6h** |
| Wave 3 | ~10min | — | **~10min** |
| Wave 4 | 0.5h | -0.3h(U1a移出) +0.5h(W4.3新增) | **0.7h** |
| **Total** | **4.5h** | — | **~5h** |

## 风险登记册

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| P4.1b OOS R² 计算复杂度超预期 | 中 | 中 | holdout R² 用现有 model_params 重算线性参数即可，不涉及新优化 |
| golden_100 运行超 30 分钟 | 低 | 低 | 已有 batch 模式，atomic checkpoint 可用 |
| dashboard 的 `LPPLVisualizer` 不兼容 `detect_bubble()` 返回格式变化 | 低 | 中 | P4.1b 只加新 key，不改已有 key → 向后兼容 |
| bypass_rate 初始数据为 0（样本不足） | 高 | 低 | 正常运行——golden_100 会提供更丰富的 Spring 事件 |
