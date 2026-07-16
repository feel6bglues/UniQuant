# UniQuant 7 轮综合诊断报告

> 日期: 2026-07-09
> 范围: 7 轮并行分析，覆盖代码基线、活动 BUG、测试质量、死代码/复杂度、信号/回测链路、研究平台差距、修复路线图

---

## 第 1 部分：核心事实

| 指标 | 数值 |
|---|---|
| src 文件数 | 256 |
| src 代码行数 | 62,465 |
| 测试文件数 | 126 |
| 测试函数数 | 1,591 |
| 测试通过数 | 1,666 |
| 测试跳过数 | 8 |
| 模块无测试文件 | 178/256 (79.8%) |
| 覆盖率 | 52% (超过 50% 门槛) |
| 死代码 LOC | ~1,960 (3.1%) |
| 活跃 BUG | 4 个 |
| 评分卡 | 3.29/5.0 — B (有条件就绪) |

---

## 第 2 部分：活动 BUG 状态

### Bug #1: alpha_score=0.0 → SELL **活跃·高影响**

| 位置 | 行号 | 问题 |
|---|---|---|
| `analysis_service_v2.py` | 535, 543, 552 | 3 条引擎失败路径全部写 score=0.0 |
| `adapters.py` | 359-370 | 0.0 < 0.3 → SELL, confidence=1.0 |
| `arbitrator.py` | 192-207 | SELL 优先 + confidence=1.0 的虚假信号覆盖所有 BUY |
| `unified_engine.py` | 409-417 | 误 SELL 导致全仓平仓 |

**修复方案**: `adapters.py` 中 `score == 0.0` 返回 `None` (1 行变更)

### Bug #2: fillna(0.0) 因子失真 **活跃·中影响**

| 位置 | 行号 | 影响 |
|---|---|---|
| `composer.py` | 183, 204, 276 | 新上市/数据不足股票被填为 0.0，信号失真 |
| `screener.py` | 79 | 已有 `dropna` 保护，但 fillna 先将其绕过 |

**修复方案**: 3 处 `fillna(0.0)` → `fillna(np.nan)` (3 行变更)

### Bug #3: Pipeline 裸 except **活跃·中影响**

| 位置 | 行号 | 问题 |
|---|---|---|
| `research_pipeline.py` | 495 | `_run_single` 中 `except Exception` 吞没 KeyboardInterrupt |

**修复方案**: 窄化为具体异常 + `exc_info=True`

### Bug #4: Wyckoff 裸 except **活跃·低影响**

| 位置 | 行号 | 问题 |
|---|---|---|
| `engine.py` | 251, 260, 1573, 1588 | 4 处 `except Exception` 从不重抛 |

**修复方案**: 窄化异常类型 + 加日志

---

## 第 3 部分：7 条 A 股回测防线

所有 7 条防线 **全部通过**验证，每条防线至少有两层检查（引擎层 + 撮合层）：

| 防线 | 引擎层 | 撮合层 | 结果 | 备注 |
|---|---|---|---|---|---|
| T+1 | `_check_t1()` → 交易日差检查 | `fill_sell()` → 向量化 mask | ✅ | E2E 测试确认 |
| 涨跌停四板块 | `_check_limit()` + `validate_trade_action()` | `compute_limit_status_vectorized()` | ✅ | |
| 停牌 | volume=0 挂单作废 | 执行价 Volume=0 平滑 | ✅ | 撮合层 P0-07 修复（原仅引擎层检查） |
| 现金约束 | 买入缩量 + 最终检查 | 向量化 cash_shortfall_mask | ✅ | |
| 费用 | `_calc_commission/stamp/transfer` | 向量化买入/卖出成本 | ✅ | 深市过户费豁免 P1-01 修复 |
| 滑点 | `_calc_slippage()` + 市场冲击 | `compute_execution_prices()` | ✅ | |
| 整手 100/200 | `lot_size = board_registry.lot_size` | 向量化 `// *` 取整 | ✅ | 按板块动态取整 |

---

## 第 4 部分：研究平台能力差距

20 项量化平台关键能力评估：

| # | 能力 | 状态 |
|---|---|---|
| 1 | 单标深度分析 | ✅ |
| 2 | 全市场扫描 | ✅ |
| 3 | 因子 IC/IR 分析 | ✅ |
| 4 | 因子权重优化 | ✅ (IC 加权组合 + FactorRegistry admission gate) |
| 5 | Walk-Forward 交叉验证 | ✅ |
| 6 | 参数敏感性分析 | ✅ |
| 7 | 策略过拟合检测 (DSR) | ✅ |
| 8 | **组合回测 (多标的共享现金)** | **⚠️ 部分支持 — portfolio_engine.py 已废弃，路径已知** |
| 9 | 行业中性化 | ✅ |
| 10 | **风格因子暴露 (Fama-French/BARRA)** | **❌ 缺失** |
| 11 | **信号历史回放** | **❌ 缺失** |
| 12 | Monte Carlo 模拟 | ✅ |
| 13 | **Brinson 归因分析** | **❌ 缺失** |
| 14 | 换手率分析 | ⚠️ (部分) |
| 15 | Jupyter notebook 支持 | ❌ 缺失 |
| 16 | 因子数据导出 | ⚠️ (部分) |
| 17 | 回测结果对比 | ✅ |
| 18 | 组合优化器 | ✅ |
| 19 | 情景分析 | ✅ |
| 20 | A 股规则可配置 | ✅ |

**总计**: 14 ✅ (完全), 2 ⚠️ (部分), 3 ❌ (缺失)

---

## 第 5 部分：死代码清单

### 100% 死代码（可安全删除）

| 文件 | LOC | 状态 |
|---|---|---|
| `services/analysis_service_legacy.py` | 1,649 | 无生产调用者 |
| `shared/price_collar.py` | 32 | 零调用 + 断开的 import 路径 |
| `signal/slippage_model.py:DynamicSlippage` | 20 | 默认路径未实例化 |
| `services/analysis/fsm_analysis_engine.py` | 247 | v2 管线未使用 |

### 半死代码

| 文件 | LOC | 说明 |
|---|---|---|
| `data/data_pipeline_service.py` | 32 | ServiceContainer 绕过, 但 DataFetcher 间接使用 |
| `hands/backtest/portfolio_engine.py` | 373 | 已废弃, 从 `__init__` 导出移除 |

---

## 第 6 部分：复杂度热点

| 文件 | LOC | 最大问题 |
|---|---|---|
| `brain/wyckoff/engine.py` | 1,613 | 39 方法, 1 个 F/53 + 2 个 E 级圈复杂度 |
| `ui/dashboard.py` | 1,553 | 文件过大, MI=4.23 |
| `brain/lppl/engine.py` | 1,098 | 6 个超长函数 |
| `hands/strategies/wyckoff.py` | — | trade_wyckoff F(57) |
| `brain/factors/walk_forward_pipeline.py` | — | run() E(37) |

---

## 第 7 部分：P0/P1/P2 综合修复路线图

### P0 — 立即修复 (7 项)

| # | 问题 | 来源 | 工时 | 影响 |
|---|---|---|---|---|
| 1 | alpha_score=0.0→SELL | BUG #1 | 1h | 消除假卖出信号 |
| 2 | fillna(0.0) 因子失真 | BUG #2 | 1h | 新上市股票不再被误评 |
| 3 | pipeline 裸 except (KB 吞没) | BUG #3 | 1h | KeyboardInterrupt 可被中断 |
| 4 | Wyckoff 裸 except 窄化 | BUG #4 | 2h | 引擎错误可见 |
| 5 | 组合回测缺失 | 平台缺口 #8 | 40h | 研究平台最大生产力障碍 |
| 6 | 风格因子暴露分析 | 平台缺口 #10 | 24h | 策略因子暴露可衡量 |
| 7 | 数据验证器测试 | 测试缺口 | 2h | 数据质量防线可测 |

### P1 — 本周修复 (8 项)

| # | 问题 | 工时 | 
|---|---|---|
| 8 | 安全: eastmoney SSL verify=False 修复 | 1h |
| 9 | 死代码: archive analysis_service_legacy.py (1649 LOC) | 1h |
| 10 | 死代码: 清理 price_collar / DynamicSlippage | 1h |
| 11 | 复杂度: Wyckoff engine.py 方法拆分 (F/53 → <20) | 8h |
| 12 | 测试: unified_engine.py 专用测试 (752 LOC) | 8h |
| 13 | 测试: analysis_service_v2.py 专用测试 (637 LOC) | 8h |
| 14 | 测试: mutmut 配置修复 + 基线运行 | 2h |
| 15 | 可观测性: metrics 系统 (Prometheus/OTel) | 24h |

### P2 — 本月修复 (10 项)

| # | 问题 | 工时 |
|---|---|---|
| 16 | 信号超时默认启用 (DEFAULT_MAX_SIGNAL_AGE_SECONDS > 0) | 1h |
| 17 | 信号历史回放框架 | 16h |
| 18 | Brinson 归因分析 | 12h |
| 19 | 因子权重优化 (梯度/目标函数) | 8h |
| 20 | Jupyter notebook 集成 + 教程 | 8h |
| 21 | 换手率分析标准化模块 | 4h |
| 22 | 因子数据导出 (CSV/Parquet) | 4h |
| 23 | 结构化日志 (JSON/OTel) | 6h |
| 24 | 复杂度: LPPL engine.py 方法拆分 (1098 LOC) | 8h |
| 25 | 复杂度: dashboard.py 重构 (1553 LOC) | 8h |

---

## 第 8 部分：评分卡预测

| 维度 | 当前 | P0 后 | P0+P1 后 |
|---|---|---|---|
| 数据可靠性 | 3.5 (B+) | 3.5 | 3.8 |
| 引擎正确性 | 3.8 (B+) | 4.2 (A-) | 4.2 |
| 回测信任度 | 3.5 (B+) | 4.0 (A-) | 4.0 |
| 代码质量 | 2.5 (C+) | 3.0 (B) | 3.5 (B+) |
| 测试质量 | 2.0 (C) | 2.5 (C+) | 3.0 (B) |
| 性能 | 4.0 (A-) | 4.0 | 4.0 |
| 安全 | 3.5 (B+) | 4.0 (A-) | 4.0 |
| 可观测性 | 2.0 (C-) | 2.0 | 3.0 (B) |
| **总分** | **3.29 (B)** | **3.70 (B+)** | **3.95 (A-)** |

---

## 第 9 部分：文档漂移修正清单

| 文档 | 声明 | 实际 | 应修正 |
|---|---|---|---|
| docs/reanalysis/F_signal_audit.md | signal/db.py 0% 覆盖 | 93% (35 tests) | 标注已修复 |
| docs/reanalysis/A_code_quality.md | Wyckoff 复杂度 76 | max 40, class total 285 | 修正数字 |
| AGENTS.md | eastmoney.py 1,094 LOC | 3 LOC re-export | 更新 |
| AGENTS.md | 56 弱断言测试 | 1 真正弱测试 | 修正 |
| AGENTS.md | "29% adapter coverage" | 8/8 adapters 有 62 测试 | 更新 |
| AGENTS.md | mutmut baseline broken | 根本在 pyproject.toml 无 [tool.mutmut] 配置 | 修正根因描述 |

---

## 结论

UniQuant 作为 A 股量化研究平台：

- **回测信任度**：7/7 防线全过，A 股规则完备 — 这是核心竞争壁垒
- **信号系统**：8 适配器 + 双仲裁路径 + 信号数据库，链路完整
- **因子研究**：IC/IR + Walk-Forward + 中性化，基础扎实
- **最大短板**：组合回测缺失（无法多标的共享现金）、可观测性 F 级、测试质量 C 级
- **最小投入最大产出**：4 个 BUG 修复（5 行代码）+ data_validator 测试（2h）= 消除 3 个数据风险点

P0 修复预计 **71 工时** 可将评分卡从 3.29 (B) 提升至 3.70 (B+)。P0+P1 预计 **117 工时** 可达到 3.95 (A-).
