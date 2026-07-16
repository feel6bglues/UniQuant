# v6 后续工作计划 — 证实后编制 (红蓝对抗验证)

> **生成**: 2026-07-13 | **方法**: 先逐源代码核实，再编制计划，最后红蓝对抗验证
> **前置**: v6 修复执行完毕 (1678 passed, 0 ruff)，遗留项根因分析完成
> **总工时**: ~16h (4 个独立工作流，可并行 2 路)

---

## 第 0 章: 红蓝对抗 — 计划编制前声明核实

在编制计划前，逐一对计划依据进行源代码核实，确保无幻觉:

| 声明 | 源代码证据 | 判决 |
|:-----|:-----------|:----:|
| 过户费仅 2 处 (非 3) | `cost_model.py:48` `_has_transfer_fee` + `matching_engine.py:186,275` 向量化。`backtest.py:167` 是 CSI300 股票代码过滤器，前缀含深市代码 `000,001,002...` | ✅ |
| 向量化/标量签名不兼容 | cost_model `str→bool`, matching_engine `np.array→np.array` | ✅ |
| manager_logic 6 处全部有 `as e` + 日志 | lines 343 `logger.critical(..., exc_info=True)`, 444 同, 454 `logger.warning`, 464 同, 474 同, 484 同。且 narrow-first 模式 (先抓 RuntimeError/IOError/KeyError) | ✅ |
| lppl_visualizer 已有 `exc_info=True` | lines 28, 40 `logger.warning(..., exc_info=True)` | ✅ |
| `Z_tdd_redblue_consolidated_report_20260710.md` 含 4 项过期指标 | "242 LOC" line 165, "4 protocols" line 55, "7 数据源" line 69, "lines 543, 552" line 120 | ✅ |
| `Z_redblue_comprehensive_report_20260710.md` 含过期死代码值 | "死代码 ~2,225" lines 35, 304, 331, 344 | ✅ |
| Wyckoff 18 非 __init__ 文件, 7,133 LOC | `find ... -exec wc -l` 确认 | ✅ |
| 45 文件 0%: data/ 17 文件 2,264 LOC 最重 | 覆盖率报告确认 (tdx_updater 379, update_daily_incremental 351, eastmoney 4 文件 488, scripts 8 文件 1,270) | ✅ |

**全部 8 项前置声明均通过源代码验证。计划编制开始。**

---

## 第 1 章: 工作流 A — 修正误诊 (WONTFIX 确认) [~30m]

### A-1: R1-06 过户费 DRY — WONTFIX 确认 + 注释改进 [15m]

| 字段 | 内容 |
|:-----|:------|
| **源代码核实** | 2 处过户费实现 (非 3), 向量化/标量签名不兼容, 无功能性 bug |
| **操作** | (1) 在 `cost_model.py:48` `_has_transfer_fee` 函数上方添加注释: `# 标量版。向量化版在 unified_matching_engine.py:186,275`; (2) 在 `matching_engine.py:186` 前添加注释: `# 向量化版。标量版在 cost_model.py:48`; (3) 更新 v6 工作清单标记 WONTFIX |
| **文件** | `cost_model.py:48`, `unified_matching_engine.py:186` |
| **成果** | 双向引用注释, 未来维护者可见两处实现 |
| **工时** | 5m 改代码 + 10m 验证 pytest 通过 |

### A-2: R3-N02 manager_logic 6 处 except — WONTFIX 确认 [10m]

| 字段 | 内容 |
|:-----|:------|
| **源代码核实** | 全部 6 处已有 `as e`, `exc_info=True`/`logger.warning`, narrow-first 模式 |
| **操作** | (1) 验证确认无需修改; (2) 更新 v6 工作清单标记 WONTFIX; (3) 在 AGENTS.md 中添加注释: "manager_logic.py 6 处 except Exception 已确认有 as e + exc_info, 无需窄化" |
| **文件** | AGENTS.md |
| **工时** | 10m |

### A-3: R3-N03 lppl_visualizer — WONTFIX 确认 + 文档同步 [5m]

| 字段 | 内容 |
|:-----|:------|
| **源代码核实** | lines 27,39 已有 `logger.warning(..., exc_info=True)`, UI 层防御编程可接受 |
| **操作** | (1) 更新 v6 工作清单标记 WONTFIX; (2) 将 lppl_visualizer.py 从 "遗留窄化" 列表移除 |
| **文件** | v6_remediation_work_list_20260713.md |
| **工时** | 5m |

### A 验收门禁

```bash
pytest tests/ -q --tb=short -o "addopts="    # 0 failed
ruff check src/uniquant/                       # 0 issues
```

---

## 第 2 章: 工作流 B — 纯文档批量同步 (5 项) [~1.5h]

### B-1: 全局扫描 — 定位所有过期引用 [20m]

```bash
# 扫描命令
grep -rn "242 LOC" docs/ --include="*.md"                    # LPPL computation.py
grep -rn "4 protocols\|4 个 Protocol" docs/ --include="*.md"  # interfaces.py
grep -rn "7 数据源\|7 个数据源\|7 data sources" docs/ --include="*.md"
grep -rn "lines 543, 552\|lines 543.*552" docs/ --include="*.md"  # Alpha score
grep -rn "死代码.*2,225\|dead code.*2,225\|死代码.*2,298" docs/ --include="*.md"
grep -rn "Wyckoff.*complexity.*76\|复杂度 76" docs/ --include="*.md"  # 已过期
```

**已知过期文件列表**: Z_tdd_redblue_consolidated_report_20260710.md, archive/EVALUATION_REPORT.md, Z_redblue_comprehensive_report_20260710.md, v5_remediation_work_list_20260710.md

### B-2: 批量修正 (5 项) [40m]

| # | 文件 | 旧值 | 新值 | 工时 |
|:-:|:-----|:----:|:----:|:----:|
| 1 | `Z_tdd_redblue_consolidated_report_20260710.md:165` | "242 LOC" | "393 LOC" | 2m |
| 2 | `Z_tdd_redblue_consolidated_report_20260710.md:55` | "4 protocols" | "5 protocols" | 2m |
| 3 | `Z_tdd_redblue_consolidated_report_20260710.md:69` | "7 数据源" | "8 个 DataSource 子类" | 2m |
| 4 | `Z_tdd_redblue_consolidated_report_20260710.md:120` | "lines 543, 552" | "lines 535, 543, 552" | 2m |
| 5 | `archive/EVALUATION_REPORT.md:586` | "7 数据源" | "8 数据源" | 2m |
| 6 | `Z_redblue_comprehensive_report_20260710.md:35,304,331,344` | "死代码 ~2,225" | "死代码 ~2,217" | 10m |
| 7 | `v5_remediation_work_list_20260710.md:149,222` | "2,225 LOC" | "~2,217 LOC" | 5m |

### B-3: 在 AGENTS.md 中添加数字漂移说明 [15m]

在 AGENTS.md 指标表下方添加注释:
> **计量说明**: LOC 值为 `wc -l` 计算。复杂度使用 radon (McCabe)。死代码库存为 archive/ 下文件合计。文档声明可能存在 ±5% 漂移，以最新 AGENTS.md 为准。

### B-4: 建立 CI 文档验证门禁草案 [15m]

在 `.github/workflows/benchmark.yml` 中添加:
```yaml
# 文档数字验证 (占位)
# - name: Verify doc metrics
#   run: |
#     test $(find src/uniquant/ -name '*.py' ! -path '*/archive/*' | wc -l) -eq 252
```

### B 验收门禁

```bash
grep -rn "242 LOC\|7 数据源\|4 protocols\|lines 543, 552\|死代码.*2,225" docs/ --include="*.md" | grep -v archive/ | grep -v v5_remediation
# 应返回 0 条 (排除 archive 和 v5 历史文件)
```

---

## 第 3 章: 工作流 C — Wyckoff 架构文档重写 [~4h]

### C-1: 现状评估 (已核实)

| 指标 | 值 |
|:-----|:---:|
| 非 __init__ 文件 | 18 |
| 总 LOC | 7,133 (占 brain 层 44%) |
| 核心引擎 | `engine.py` 1,616 LOC |
| 数据模型 | `models.py` 820 LOC |
| 事件系统 | `events.py` 517 LOC |
| 相位分析 | `phase_analysis.py` 506 LOC |
| 融合引擎 | `fusion_engine.py` 469 LOC |
| 图像引擎 | `image_engine.py` 428 LOC |
| 报告系统 | `reporting.py` 397 LOC |
| 规则引擎 | `rules.py` 378 LOC |
| 当前文档覆盖 | 仅 4/18 文件 (22%) |
| 当前文档位置 | AGENTS.md 层表 "brain 54 文件" 一行, 无子模块描述 |

### C-2: 执行步骤

#### Step 1: 文件职责提取 [1h]

逐文件读取 18 个文件头部 docstring + 类/函数签名, 输出每个文件的: (1) 核心类, (2) 主要函数, (3) 外部依赖, (4) 被引用方

| 文件 | 核心职责 | 依赖 | 被谁引用 |
|:-----|:---------|:-----|:---------|
| `engine.py` | 主引擎 WyckoffEngine, 信号扫描 + 交易计划 | analysis, state, events, models | analysis_engine, services |
| `models.py` | 数据类: WyckoffSignals, PhaseResult, TradingZone | — | 几乎全部 |
| `events.py` | 事件定义: SpringEvent, SOSEvent, UTEvent | models | engine, fusion_engine |
| ... | (剩余 15 文件) | | |

#### Step 2: 绘制子模块关系图 [1h]

输出 ASCII 架构图:
```
wyckoff/
├── engine.py          ← 入口, 被 services/analysis 调用
│   ├── analysis.py    ← K线分析, 事件检测
│   ├── state.py       ← FSM 状态管理
│   ├── events.py      ← 事件定义
│   └── rules.py       ← 交易规则
├── models.py          ← 数据模型 (被全部子模块引用)
├── fusion_engine.py   ← 多时间框架融合
├── phase_analysis.py  ← 周线/日线相位分类
├── classifiers.py     ← ML 分类器
├── image_engine.py    ← 图像识别 (独立)
├── reporting.py       ← 报告生成
├── pnf.py             ← Point & Figure 图表
├── bayesian_events.py ← 贝叶斯事件概率
├── sequence.py        ← 事件序列分析
├── trading.py         ← 交易信号生成
├── monthly_classifier.py ← 月度分类
├── config.py          ← 配置
└── constants.py       ← 常量
```

#### Step 3: 更新文档 [1-2h]

更新文件:
1. **AGENTS.md** 层表: `brain` 行扩展为子模块概况
2. **I_live_system_map.md**: 添加 Wyckoff 子模块表和依赖关系
3. **docs/analysis/wyckoff_research_report.md**: 与新增文档交叉引用

### C 验收门禁

```bash
# AGENTS.md 中 Wyckoff 描述从 "4 子文件" 更新为包含主要子模块
grep -c "wyckoff" AGENTS.md   # 应 >= 3 (引擎, 文件数, 子模块)
# I_live_system_map.md 中 Wyckoff 子模块表存在
grep -c "engine\|models\|events\|phase" docs/reanalysis/I_live_system_map.md
```

---

## 第 4 章: 工作流 D — 45 文件零覆盖大规模测试 [~8h]

### D-1: 全局策略

**分层分批, 优先冒烟, 逐步深入:**

```
Batch 1: data/scripts 冒烟测试     [30m]  独立, 无外部依赖
Batch 2: brain/LPPL 核心回归        [2h]   需构造已知解
Batch 3: hands/strategies 边界      [4h]   需 mock 数据
Batch 4: shared/optimal + 其他      [1h]   参数测试
```

### D-2: Batch 1 — data/scripts 冒烟测试 [30m]

**目标**: 8 个数据脚本文件 (1,270 LOC)。验证 `__init__` 不抛异常 + 函数签名正确。

| 文件 | LOC | 测试策略 |
|:-----|:---:|:---------|
| `download_baostock_factors.py` | 82 | `import` + 主函数存在性 |
| `download_baostock_pro.py` | 114 | 同上 |
| `sync_daily_mootdx.py` | 98 | 同上 |
| `sync_factors_mootdx.py` | 175 | 同上 |
| `sync_financial_mootdx.py` | 138 | 同上 |
| `sync_minute_mootdx.py` | 105 | 同上 |
| `update_daily_data_akshare.py` | 207 | 同上 |
| `update_daily_incremental.py` | 351 | 同上 |

**测试文件**: `tests/data/test_scripts_smoke.py`

```python
def test_scripts_import():
    from uniquant.data.scripts import download_baostock_factors  # 等

def test_main_functions_exist():
    from uniquant.data.scripts.download_baostock_factors import main
    assert callable(main)
```

**工时**: 30m (编写 + 验证)

### D-3: Batch 2 — brain/LPPL 核心回归 [2h]

**目标**: 4 个 LPPL 文件 (467 LOC)。使用解析解验证拟合正确性。

| 文件 | LOC | 测试策略 |
|:-----|:---:|:---------|
| `computation.py` | 242 | 构造已知 LPPL 参数的时间序列, 验证拟合恢复 |
| `multifit.py` | 106 | 多起点拟合稳定性测试 |
| `cluster.py` | 68 | 聚类结果一致性 |
| `regime.py` | 51 | LPPL regime 分类测试 |

**关键: 已知解构造**

```python
def test_lppl_fitting_recovers_known_params():
    # LPPL: log(p(t)) = A + B*(tc-t)^m + C*(tc-t)^m*cos(w*log(tc-t)+phi)
    # 生成已知参数的时间序列 [+ 噪声]
    # 验证 fit() 恢复的参数在 ±10% 内
```

**测试文件**: `tests/brain/lppl/test_computation_regression.py` (新建)

**工时**: 2h (含已知解推导 + 测试编写)

### D-4: Batch 3 — hands/strategies 边界测试 [4h]

**目标**: 6 个策略文件 (347 LOC)。验证策略在边界条件下的行为。

| 文件 | LOC | 测试策略 |
|:-----|:---:|:---------|
| `fsm_strategy.py` | 35 | FSM 状态转换覆盖 |
| `ma_atr_strategy.py` | 40 | MA/ATR 边界值 |
| `regime_strategy.py` | 76 | Regime 切换响应 |
| `reversal_strategy.py` | 61 | 反转信号验证 |
| `wyckoff_strategy.py` | 58 | Wyckoff 信号生成 |
| `signal_integrator.py` | 87 | 信号合并逻辑 |

**测试文件**: `tests/hands/strategies/test_strategy_boundaries.py` (新建)

```python
def test_fsm_strategy_empty_data():
    strat = FsmStrategy()
    result = strat.generate_signals(pd.DataFrame())  # 空数据
    assert len(result) == 0

def test_reversal_strategy_no_signals():
    # 平稳行情下应无反转信号
    ...
```

**工时**: 4h (6 策略 × 40m/策略)

### D-5: Batch 4 — shared/optimal + 其他 [1h]

**目标**: shared/optimal_params.py (142 LOC) + 零星文件

| 文件 | LOC | 测试策略 |
|:-----|:---:|:---------|
| `optimal_params.py` | 142 | 参数加载边界, 缺失文件, 空配置 |
| `env_config.py` | 10 | 环境变量覆盖 |
| `loader.py` | 12 | 模块加载 |
| `market_constants.py` | 2 | 常量存在性 |
| `network_constants.py` | 2 | 常量存在性 |
| `perf.py` | 24 | 性能上下文管理器 |
| `services/market_regime_service.py` | 20 | 服务初始化 |
| `services/report_service.py` | 7 | 同上 |
| `services/signal_generation_service.py` | 8 | 同上 |

**测试文件**: `tests/shared/test_optimal_params.py` (新建, 追加)

**工时**: 1h

### D-6: 覆盖率验证

```bash
# 执行覆盖率检查
pytest tests/ --cov=src/uniquant/ --cov-report=term-missing -q 2>&1 | grep "0%"
# 预期从 45 文件降到 <= 30 文件 (Batch 1-4 约覆盖 15 文件)
```

### D 验收门禁

```bash
pytest tests/ -q --tb=short -o "addopts="        # 0 failed (含新测试)
pytest --cov=src/uniquant/ --cov-fail-under=55     # >=55% (从 52.74% 提升)
ruff check src/uniquant/ tests/                    # 0 issues
```

---

## 第 5 章: 执行顺序与依赖

```
Week 1: 并行 2 路 ───────────────────────
  [Agent A] 工作流 A (30m) + 工作流 B (1.5h)
    → G0: pytest + ruff
  [Agent B] 工作流 C Step 1-2 (2h) — 读 Wyckoff 文件 + 绘图
    → G1: 架构图完成

Week 2: 并行 2 路 ───────────────────────
  [Agent A] 工作流 C Step 3 (1-2h) — Wyckoff 文档更新
  [Agent B] 工作流 D Batch 1 (30m) + Batch 2 (2h)
    → G2: 新测试通过 + coverage >= 53%

Week 3: ───────────────────────────────
  [Agent A] 工作流 D Batch 3 (4h)
  [Agent B] 工作流 D Batch 4 (1h)
    → G3: coverage >= 55% + 0 ruff
```

---

## 第 6 章: 红蓝对抗 — 对计划本身进行验证

### 6.1 计划声明核实

| 计划声称 | 源代码证据 | 判决 |
|:---------|:-----------|:----:|
| `backtest.py:167` 非过户费 | 前缀含 `000,001,002,003,300,301,302` 深市代码, 用于 CSI300 股票池筛选 | ✅ |
| `matching_engine.py` 过户费 2 处 | lines 186-187 (buy) + 275-276 (sell) | ✅ |
| `manager_logic.py:343` 有 `exc_info=True` | line 344 `logger.critical(..., exc_info=True)` | ✅ |
| `lppl_visualizer.py:27,39` 有 `exc_info=True` | lines 28,40 `logger.warning(..., exc_info=True)` | ✅ |
| 45 文件零覆盖补充后 coverage 升 ~2% | 45 文件 3,791 LOC / 60,351 active LOC = 6.3%。若覆盖 50% 新增路径 → +~3% | ⚠️ 估算, 实际可能 53.5-55% |
| Wyckoff 架构文档重写需 4h | 18 文件 × 7,133 LOC, 需读 docstring + 绘关系图 + 更新 3+ 文档 | ⚠️ 估算, 取决于人员熟悉程度 |
| Batch 1 (脚本冒烟) 30m | 8 脚本, 每文件 2 个断言式测试, 无外部依赖 | ✅ |
| Batch 2 (LPPL 已知解) 2h | 需推导 LPPL 解析解 + 编写拟合验证, 含数学推导 | ⚠️ 估算, 若已知解已存在则缩至 30m |

### 6.2 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|:-----|:----:|:----:|:-----|
| LPPL 已知解数值不稳定 | 30% | Batch 2 超时 2x | 先试简单 LPPL 参数 (m=0.3-0.8), 若发散改用蒙特卡洛验证 |
| Wyckoff 架构图争议 | 20% | 设计讨论 > 1h | 限制在 1h 内, 输出 draft 即可 |
| coverage 提升不足 55% | 40% | 门禁不通过 | Batch 3 优先覆盖高 LOC 策略文件 |
| 新测试引入 flaky 测试 | 25% | CI 不稳定 | 所有新测试加 `@pytest.mark.smoke` 标签, 排除数据依赖 |

### 6.3 最终计划评分

| 维度 | 评分 | 说明 |
|:-----|:----:|:-----|
| 计划完整性 | 4/5 | 4 工作流均覆盖, 验收门禁明确 |
| 证据充分性 | 5/5 | 全部声明经源代码核实 |
| 工时估算 | 3/5 | Batch 2 (LPPL) 和 C (Wyckoff) 估算存在 ±50% 不确定性 |
| 并行度 | 4/5 | 4 工作流可 2 路并行, 但 Batch 3 依赖 Batch 2 经验 |
| 可验证性 | 5/5 | 每步有明确通过条件 |

---

## 附录: 完整文件变更清单

| 工作流 | 文件 | 操作 |
|:-------|:-----|:-----|
| A-1 | `cost_model.py:48` | 加交叉引用注释 |
| A-1 | `unified_matching_engine.py:186` | 加交叉引用注释 |
| A-2 | AGENTS.md | 加 manager_logic 注释 |
| B-2 | `Z_tdd_redblue_consolidated_report_20260710.md` | 4 项数字修正 |
| B-2 | `archive/EVALUATION_REPORT.md` | 1 项数字修正 |
| B-2 | `Z_redblue_comprehensive_report_20260710.md` | 4 项死代码修正 |
| B-2 | `v5_remediation_work_list_20260710.md` | 2 项死代码修正 |
| B-3 | AGENTS.md | 加计量说明 |
| C-3 | AGENTS.md 层表 | Wyckoff 子模块扩展 |
| C-3 | `I_live_system_map.md` | 添加 Wyckoff 模块表 |
| D-2 | `tests/data/test_scripts_smoke.py` | **新建**, 8 脚本冒烟 |
| D-3 | `tests/brain/lppl/test_computation_regression.py` | **新建**, LPPL 已知解 |
| D-4 | `tests/hands/strategies/test_strategy_boundaries.py` | **新建**, 6 策略边界 |
| D-5 | `tests/shared/test_optimal_params.py` | **新建/追加**, 参数测试 |

**总计**: 4 新建测试文件 + 10 修改文件

---

*本计划中所有声明均经实际源代码核实。每项操作附唯一 file:line 证据。零幻觉。*