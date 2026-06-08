# UniQuant 终极修复战役 — 分级外科手术计划

> 基于 16 轮深度审计(2,923 行 / 132 KB) + 最终勘误 + 交叉核实修正
> 生成: 2026-06-07 v2 | 审计员: Minimax-M3
> **修正说明**:经二次核实,修正了 Sprint 1.2 多余文件、Sprint 1.3a MDD 根因重判、
> 补充 6 项未覆盖的 P1-P2 问题。见 docs/FIVE_STAGE_ROUND2_FINDINGS_20260607.md 第五阶段。

---

## 核心修复纪律

1. **最小侵入原则 (Minimal Surgery)**: 只修复指定 Bug,禁止重构周边代码
2. **拒绝静默失败 (Fail-Fast)**: 让系统尽早崩溃,不带着错误数据继续跑
3. **分步落盘 (Halt & Commit)**: 每个 Sprint 完成后必须 Halt & Wait, 确认后再继续
4. **先归文件,后改代码**: 手动操作(M1)在 AI 改代码前完成

---

## Sprint 1: 止血与可重现性 (真正的 P0 级)

### 1.1 修复异常吞噬黑洞 (P0)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/shared/error_handling.py` + 全库 28 处 `except pass/continue` |
| **操作** | (1) `handle_errors` 装饰器默认参数改 `reraise=True`; (2) `default_return=None` 时记录 ERROR 日志; (3) 全库搜索 `except Exception:` 后紧跟 `pass`/`continue` 的代码(核实确认 **28 处**), 每处插入 `logger.exception("静默吞噬异常: ...")` |
| **备注** | 核实发现 **88 处 @handle_errors 调用中 0 处显式设 `reraise=True`**——100% 吞异常。改默认值后全部恢复 fail-fast 行为 |
| **预估改动** | ~50 行 |

### 1.2 修复随机性失控 — 精简版 (P0)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/hands/backtest/monte_carlo.py` (+ `tests/conftest.py` 追加) |
| **操作** | (1) `mc.py` 中 `run_shuffle`/`bootstrap` 的 `np.random.permutation`/`np.random.choice` 加 `seed` 参数,默认 `from uniquant.shared.constants import RANDOM_SEED`; (2) `tests/conftest.py` 两处 fixture 顶部加 `np.random.seed(42)` |
| **精简说明** | 经核实,`overfitting_detector.py` 和 `robustness_checker.py` **不含任何 random 调用**,已从计划中移除 |
| **预估改动** | ~10 行 |

### 1.3a 修复 MDD 666% 数据污染 (P0)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/risk/drawdown_analyzer.py` |
| **操作** | 算法公式 `(equity - rolling_max) / max(rolling_max, 1e-10)` 用于正常正数 equity 曲线是正确的。实测 666% 的根因是 **数据污染导致 equity 含负值/零值**(R1 发现:未复权数据被静默返回)——算法本身没问题,但缺少输入校验。追加: `if np.any(equity <= 0): logger.warning(...)` 并在 analyze_drawdown 入口处做 equity 合法性检查 |
| **预估改动** | ~10 行 |

### 1.3b 补 Wyckoff 缺失常量 (P0)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/shared/constants/technical.py` |
| **操作** | 在 `IndicatorThresholds` 类中添加 `SAMPLE_MAX_ROWS_WYCKOFF = 800` |
| **核实确认** | `wyckoff_analysis_engine.py:37` **确实引用** `IndicatorThresholds.SAMPLE_MAX_ROWS_WYCKOFF`,常量缺失导致 Wyckoff 引擎运行时报 AttributeError,信号从未上线 |
| **预估改动** | **1 行** |

---

## Sprint 2: 架构歧义消除与死链复活 (P1)

### 2.1 消灭 AnalysisService v1/v2 歧义 (P0 级隐患)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/services/analysis_service.py` → `analysis_service_legacy.py`; `services/__init__.py` |
| **操作** | (1) v1 重命名 + 内部方法打 Deprecation 警告; (2) `__init__.py` 懒加载字典中 `"AnalysisService"` 指向 `.analysis_service_v2` |
| **预估改动** | ~20 行 |

### 2.2 统一双 STRATEGY_MAP (P0 级隐患)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/hands/strategies/__init__.py`, `registry.py` |
| **操作** | 删除 `__init__.py` 中无生产引用的 `STRATEGY_MAP`; 全局唯一走 `registry.STRATEGY_MAP`; 旧 `BaseStrategy` 类加 `@deprecated` |
| **预估改动** | ~10 行 |

### 2.3a 复活 auto_mined 因子 (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/brain/factors/auto_mined/__init__.py` |
| **操作** | 调起 `register_auto_mined.register_all()` |
| **预估改动** | **1 行** |

### 2.3b factors.yaml 闸门 (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/shared/config_loader.py`, `brain/factors/registry.py` |
| **操作** | `factors.yaml` 接入 `GlobalConfig`; `FactorRegistry` 注册时读取 YAML 中 `enabled`/`weight` |
| **预估改动** | ~30 行 |

---

## Sprint 3: 防线补齐与配置对齐 (P1-P2)

### 3.1 修复 DataValidator 隐藏 Bug (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/data/pipeline/data_validator.py` |
| **操作** | (1) 修复第 28 行 `high_validate` 未定义变量; (2) 加 `amount > 0` 基础校验; (3) 禁止默默返回未复权数据 |
| **预估改动** | ~10 行 |

### 3.2 消除 YAML risk 命名冲突 (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `config/trading.yaml`, `src/uniquant/shared/cost_model.py`, `shared/loader.py`, `hands/strategies/wyckoff.py` |
| **操作** | `trading.yaml` 中 `risk` → `execution_risk`; 同步修改 3 处独立读取路径 |
| **核实** | `config/config.yaml` 和 `config/trading.yaml` **确实都有顶层 `risk:` key**,语义不同(`config.yaml` = 策略层默认风控,`trading.yaml` = 执行层仓位约束),静默错误风险真实 |
| **预估改动** | ~15 行 |

### 3.3a 修复日志双重打印 + LoggerFactory 迁移 (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/shared/logger_factory.py` + `data/scripts/` 下 8 个文件 |
| **操作** | (1) `_setup_root_logger()` 中设子 logger `propagate=False`,防止根/子重复输出(59MB 日志根因); (2) 将 `data/scripts/` 下 8 个 `logging.basicConfig()` 迁移到 `LoggerFactory.get_logger()` |
| **预估改动** | ~25 行 |

### 3.3b 缓存治理:TTL 合并 + 容量限制 (P1)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/shared/constants/data.py`, `shared/cache/backends.py` |
| **操作** | (1) **合并 TTL 双重定义**:`DataServiceConstants` L121-131 与 `CacheConstants` L176-183 有 7 个完全相同的 TTL 常量(注释写"兼容旧代码"),删掉旧的那份,统一走 `CacheConstants`; (2) `DiskCacheBackend` 加 `max_size` 参数(总容量上限); (3) 确认 LRU 实现正确(评论已写 LRU,实现 `min(access_times)` 确为 LRU) |
| **预估改动** | ~20 行 |

### 3.3c LoggerFactory 绕过治理 (P2)

| 字段 | 内容 |
|---|---|
| **目标文件** | `brain/wyckoff/` 下 6 个文件 + `data/tdx_loader.py` + `brain/lppl/computation.py`, `core.py` 等 |
| **操作** | 核实确认 **22 文件**`import logging` 但未用 `get_logger`。将这 22 个文件的 `logging.getLogger()` 替换为 `from ...shared.logger_factory import get_logger; logger = get_logger(__name__)` |
| **预估改动** | ~25 行(每文件 1 行 import 替换) |

### 3.3d 数据陈旧检测 (P2)

| 字段 | 内容 |
|---|---|
| **目标文件** | `src/uniquant/data/lake/storage_manager.py` |
| **操作** | 加 `validate_freshness(max_lag_days=7)` 方法,启动时扫描 parquet 文件最近日期,输出陈旧文件清单 + 警告 |
| **预估改动** | ~20 行 |

### 3.3e 旧文档加 obsolete 标记 (P2)

| 字段 | 内容 |
|---|---|
| **目标文件** | `docs/` 下 `FULL_*_2012_2025.md`, `COMPREHENSIVE_*`, `AUDIT_REPORT_*` 等 15+ 个 2026-05-23 ~ 05-31 的旧报告 |
| **操作** | 每文件顶部加一行: `> **Obsolete as of 2026-06-07** — 见 FIVE_STAGE_ANALYSIS_REPORT_20260607.md / FIVE_STAGE_ROUND2_FINDINGS_20260607.md` |
| **预估改动** | ~15 行(每文件 1 行 banner) |

---

## 手动操作 (前置 + 后置)

### M1: 归文件 — 保障 baseline 可复现 (Sprint 1 之前)

```bash
mkdir -p experiments/2026-06-07_baseline
git mv run_portfolio_simulation.py experiments/2026-06-07_baseline/
git mv run_diagnostic.py experiments/2026-06-07_baseline/
git mv run_optimized_simulation.py experiments/2026-06-07_baseline/
git mv run_oos_blind_test.py experiments/2026-06-07_baseline/
git mv run_oos_risk_rescue.py experiments/2026-06-07_baseline/
git mv portfolio_tearsheet.png experiments/2026-06-07_baseline/
git mv diagnostic_tearsheet.png experiments/2026-06-07_baseline/
git mv optimized_tearsheet.png experiments/2026-06-07_baseline/
git mv oos_tearsheet.png experiments/2026-06-07_baseline/
git mv rescue_tearsheet.png experiments/2026-06-07_baseline/
echo "# 2026-06-07 Baseline" > experiments/2026-06-07_baseline/README.md
echo "生成脚本对应: portfolio→run_portfolio_simulation.py 等" >> experiments/2026-06-07_baseline/README.md
echo "" >> experiments/2026-06-07_baseline/README.md
echo "## 验证命令" >> experiments/2026-06-07_baseline/README.md
echo "pytest tests/test_unified_matching.py -v  # 撮合防线回归" >> experiments/2026-06-07_baseline/README.md
git add experiments/
git commit -m "chore: archive 2026-06-07 baseline experiments"
```

### M2: 回归验证 (Sprint 1 后 + Sprint 2 后各跑一次)

```bash
# 撮合引擎防线回归
pytest tests/test_unified_matching.py -v

# 50 股票 Baseline 验证(确保 MDD 数字正确)
cd experiments/2026-06-07_baseline
python3 run_portfolio_simulation.py

# 全量测试(预期 12 fail + 2 收集错误→修复后应减少)
pytest tests/ -q
```

---

## 改动总量估计

| Sprint | 任务数 | 预估行数 | 风险等级 |
|---|---|---|---|
| Sprint 1 | 5 项(含精简) | ~80 行 | 高(核心逻辑修改) |
| Sprint 2 | 4 项 | ~60 行 | 中(命名/引用修改) |
| Sprint 3 | 5 项(3.3a-3.3e) | ~95 行 | 低-中(数据/日志/缓存) |
| 手动 M1 | 1 项 | 10 条 git 命令 | 低 |
| **总计** | **15 项** | **~235 行** | — |

**相比 v1 的变化**:
- 删除了 Sprint 1.2 中不存在的 `overfitting_detector.py`/`robustness_checker.py`
- Sprint 1.3a 从"重写算法"改为"加输入校验"(根因是数据污染,非算法错误)
- 追加了 Sprint 3.3c(LoggerFactory 22 文件迁移)、3.3d(数据陈旧检测)、3.3e(旧文档标记)
- Sprint 3.3a 扩展了 `data/scripts/` 8 文件迁移
- Sprint 3.3b 扩展了 TTL 双重定义合并
- 任务数从 14 项增至 15 项,行数从 ~195 增至 ~235

---

## 执行顺序

```
M1(归文件) → Sprint 1(5 项, H&W) → M2(回归) → Sprint 2(4 项, H&W) → M2(回归) → Sprint 3(6 项, H&W)
```

每个 Sprint 后的 **Halt & Wait** 必须严格遵守,不得跳过。
