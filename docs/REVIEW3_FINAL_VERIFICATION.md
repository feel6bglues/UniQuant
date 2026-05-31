# 第三轮深度核实报告 — 最终综合验证

**核实日期**: 2026-05-31
**方法**: 5 路并行 Agent，每路逐行交叉对照源码与优化文档
**范围**: OPTIMIZATION_MASTER_PLAN, A_SHARE_RULES, BACKTEST_ENGINE, PERFORMANCE, RISK_MODULE

---

## 综合评分

| 文档 | v1 (Review1) | v2 (Review2) | v3 (本轮源码核实) |
|------|:------------:|:------------:|:----------------:|
| **MASTER_PLAN** | 5.3 | 7.5 | **7.0** |
| **A_SHARE_RULES** | 6.5 | 7.5 | **5.5** |
| **BACKTEST_ENGINE** | 6.5 | 8.0 | **6.0** |
| **PERFORMANCE** | 6.0 | 7.5 | **5.0** |
| **RISK_MODULE** | 6.5 | 8.0 | **8.0** |

---

## 一、本轮新发现的 CRITICAL 级 Bug（Review1/2 全部遗漏）

### Bug 1: `calculator.py:247-249` — SSE² 而非 SSE（Performance）
`np.linalg.lstsq` 返回 `array([SSE])`，代码对其 `np.sum(residuals**2)` 产生 SSE²。导致 `_calculate_confidence` 中 cost_weight (40%) 永远接近 1.0，完全无效。
**修复**: `return residuals[0] if residuals.size > 0 else 0.0`

### Bug 2: `_check_limit_constraint` 返回 `LimitStatus` 但调用者用 `not`（Backtest §2.3）
Python dataclass 永远 truthy，`not LimitStatus(...)` 永远 `False` → **限价检查静默关闭**。
**修复**: 调用处改 `not ...` 为 `limit_status.can_buy` / `limit_status.can_sell`

### Bug 3: `classify_volume` 签名与调用者不兼容（A-Share §3.3/5.3）
文档 `(volume, volume_series, window=30)` vs 源码 `(volume, volume_series, rules: V3Rules)`。调用者全部传 `rules`。
**修复**: 恢复 `rules` 参数

### Bug 4: `classify_limit_move` 算法完全不同（A-Share §5.2）
文档用 OHLC/pre_close 比率 + `>=`，源码用 open-relative change + `is_limit_up/is_limit_down` + `<`。
**修复**: 对齐源码算法

---

## 二、Review2 可靠性评估

| 文档 | 有效 | 误报/虚构 | 误报率 |
|------|:---:|:---------:|:------:|
| **PERFORMANCE** | 2 | **3** — workers=-1 假阳性、line 35 不存在、UNIQUANT_DE_WORKERS 不存在 | **60%** |
| **A_SHARE** | 10 | 1 | ~9% |
| **BACKTEST** | 6 | 0 | 0% |
| **RISK** | 4 | 0 | 0% |
| **MASTER** | 3 | 0 | 0% |

**Performance 文档的 Review2 不可信**。

---

## 三、所有 Review 轮次未发现的源码 Bug 汇总

| # | 文件 | 行号 | Bug | 严重度 | 发现轮次 |
|---|------|------|-----|:------:|:--------:|
| 1 | `calculator.py` | 247-249 | SSE² → cost_weight 无效 | **CRITICAL** | **R3** |
| 2 | `calculator.py` | 309-321 | DE strategy: scipy `best/1/bin` vs Numba `rand/1/bin` | HIGH | **R3** |
| 3 | `cost_model.py` | 82-88 | `from_yaml` 未读 stamp_tax/transfer_fee | MEDIUM | **R3** |
| 4 | `cost_model.py` vs `portfolio_optimizer.py` | 104 vs 28 | Rf 2% vs 3% 不一致 | MEDIUM | **R3** |
| 5 | `drawdown_analyzer.py` | 2-3 | docstring 假称 "零 iterrows" | HIGH | Review1+R3 |
| 6 | `drawdown_analyzer.py` | 69-71 | `max_dd_pct` 是 `loss_pct` 别名 | MEDIUM | **R3** |
| 7 | `portfolio_optimizer.py` | 330-346 | `get_efficient_frontier` 突变 config | CRITICAL | Review1+未修 |
| 8 | `numba_optimizer.py` | 100 | `np.random.seed` 线程不安全 | MEDIUM | **R3** |
| 9 | `engine.py` | 117-123 | shares 缩减后未重算佣金 | HIGH | **R3** |
| 10 | `constants/market.py` | 68 | `BOARD_PREFIX['sci_tech']` 缺 `"689"` | MEDIUM | Review2+未修 |

---

## 四、最终优先执行建议

### P0 — 立即修复（~2h 总工作量）

| # | 修复项 | 文件 | 工时 |
|---|--------|------|:----:|
| 1 | SSE² → SSE | `calculator.py:247-249` | ~10min |
| 2 | `not LimitStatus(...)` → `.can_buy` | `engine.py:173,229` | ~15min |
| 3 | `get_efficient_frontier` 去突变 | `portfolio_optimizer.py:330-346` | ~1h |
| 4 | `classify_volume` 签名恢复 `rules` 参数 | A-Share 文档 §3.3 | ~15min |
| 5 | `classify_limit_move` 算法对齐源码 | A-Share 文档 §5.2 | ~30min |

### P1 — 本周修复

| # | 修复项 | 文件 | 工时 |
|---|--------|------|:----:|
| 6 | LPPL DE strategy 差异文档化 | Performance 文档 | ~15min |
| 7 | shares 缩减后重算佣金 | `engine.py:117-123` | ~30min |
| 8 | `np.random.seed` → `RandomState` | `numba_optimizer.py:100` | ~30min |
| 9 | `"689"` / `"302"` 补入 `BOARD_PREFIX` | `constants/market.py:68` | ~5min |
| 10 | 过户费补入买入路径 | `portfolio_engine.py:134` | ~15min |

### P2 — 本月修复

| # | 修复项 | 文件 | 工时 |
|---|--------|------|:----:|
| 11 | `compute_rolling_mdd` 向量化 | `drawdown_analyzer.py:92-100` | ~1h |
| 12 | `from_yaml` 读 stamp_tax/transfer_fee | `cost_model.py:82-88` | ~30min |
| 13 | Rf 利率统一: 2% vs 3% | `cost_model.py:104`, `portfolio_optimizer.py:28` | ~15min |
| 14 | 先加回测测试再改引擎代码 | `tests/test_backtest*.py` | ~2h |
| 15 | Risk 引擎注册到 `AnalysisEngineFactory` | `engine_factory.py:31-73` | ~1h |

---

## 五、结论

**关键发现**:
1. **Review2 对 Performance 文档不可信**（60% 误报率，含虚构代码引用）
2. **经过 2 轮审查仍遗漏 3 个 CRITICAL 级源码 bug**: SSE²、not LimitStatus 静默失效、分类算法不匹配
3. **Master Plan 中 2 个 Phase 项基于过时信息**: LPPL JIT 已完成、GlobalConfig 线程安全已完成
4. **本轮首次发现 3 个 CRITICAL + 4 个 HIGH 问题**

**建议**: 先执行 P0 修复（~2h），再更新文档，然后关闭优化阶段进入实现。
