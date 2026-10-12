# 06 工程健康域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 ANALYSIS_PROMPT_PLAYBOOK 阶段产物 | SHA `ddd678a` | 会话实测 2026-09-22 | 批 B1=E1,E2；批 B4=E3-E7（完成）

## 结论（3 句内）

本会话 Tier-A 实测：`ruff check src/ tests/ scripts/` **exit 1 / 18 errors**（全部位于 `scripts/wyckoff_multitf/v9_*` 存量，与 AGENTS 2026-08-26 声明一致）；全量 `pytest tests/ -q` **存在失败**（见 §E1 附录，17 个 FAILED 清单入文，计数以本次复跑汇总为准——若汇总行缺失则标 BLOCKED 项）。三方指标全面漂移：实测 **src 264 py / 64,438 LOC / 172 test 文件 / 2,204 test 函数**，对照 live_map/index（256/62,549/1,606）与 AGENTS 快照表（252 文件/2,051 通过/57.88% 覆盖）均不一致。

## 证据（file:line @ ddd678a）

| 断言 | 实测 | 来源 |
|------|------|------|
| ruff 全量 | **18 errors, exit 1** | 本会话 `ruff check src/ tests/ scripts/` |
| ruff 分布 | 全在 `scripts/wyckoff_multitf/v9_*.py`（E401/F841/F541/F401/E701） | 同上输出 |
| src py 文件数 | **264**（排除 `__pycache__`/`archive`） | 本会话 pathlib 扫描 |
| src LOC | **64,438** | 同上 wc 等价 |
| test 文件 | **172** (`tests/**/test_*.py`) | 同上 |
| test 函数 | **2,204** (AST `test_*`) | 同上 |
| 八层 import 冒烟 | 8/8 OK + `IMPORT_SMOKE_OK` | 本会话 `python3 -c import …` |
| ServiceContainer | `SC_IMPORT_OK`；`initialize` 注册 storage/calendar/cache/data_service/time_provider/engine_factory/market_cache/analysis_service/backtest_engine/signal_collector/arbitrator/research_pipeline | `service_container.py:105-184` |
| archive 目录 | **0 个** `*/archive/` 于 src/ | 本会话 `find src -type d -name archive` |
| CI | `test.yml`: ruff `src/uniquant/ tests/ scripts/` + `pytest tests/ -q`；`security-audit.yml` pip-audit；`benchmark.yml` | `.github/workflows/*.yml` |
| coverage 工具 | 本环境 **无 `coverage`/`pytest_cov` 模块**；`.coverage` 存在但 mtime 2026-09-14（**未复跑，沿用旧库**） | import 失败 + stat |
| bare `except:` 全 src | **0** | `rg 'except\s*:' src/uniquant` → BARE_COUNT=0 |
| `except Exception:` 全 src | **34** | EXC_COUNT=34 |

### E1 pytest（本会话 Tier-A 实测）

- 命令：`python3 -m pytest tests/ -q --tb=no -p no:cacheprovider` → **exit 1**，原始输出存 `/tmp/opencode/pytest_b1_full.txt`。
- **汇总（定稿）**：short test summary **16 FAILED**（`grep -c ^FAILED` = 16；passed 总数行未写入截断文件 → 按 16 FAILED 入文，**不宣称 0 failed**）。
- **FAILED 全清单（16 条，本会话 short summary 原文）**：

  | # | 测试 ID | 家族 |
  |---|---------|------|
  | 1-4 | `tests/chaos/test_data_chaos.py::TestDataValidatorChaos::{high_less_than_low, high_less_than_open_close, low_greater_than_open_close, 99_percent_drop}` | DataValidator 自动修复 |
  | 5-10 | `tests/test_data_chaos_qa.py::{test_high_lt_low_auto_fix, test_extreme_drop_over_99_pct, test_high_lt_open_close_auto_fix, test_all_columns_present, test_date_gap_warning, TestPipelineIntegration::test_full_dirty_pipeline}` | DataValidator 自动修复 |
  | 11 | `tests/scripts/test_factor_mining_data_loader.py::test_merge_financial_metrics_merges_and_ttm` | 财务 merge/fixture |
  | 12 | `tests/scripts/test_ha_engineering.py::TestRotationSimArithmetic::test_two_slot_exact_nav_with_impact` | H-A 轮换引擎算术 |
  | 13-16 | `tests/test_fundamental_factors.py::TestCalculateFieldTtm::{test_single_quarter_field_ttm_is_rolling_sum, test_cumulative_field_ttm_year_boundary_diff, test_ocf_ps_ttm_matches_scale, test_codes_isolated}` | TTM 滚动 |

- **根因样本（本会话定向复跑，`--tb=line` 原文）**：

  | 家族 | 断言 | 实测 vs 期望 | 根因判读 |
  |------|------|--------------|----------|
  | DataValidator（10 个） | `assert False is True` @ `test_data_chaos.py:208` | stderr「数据验证失败: 发现 3 条 High < Low」；`validate()` 返回 False | **修复路径未生效或未 return True**——测试期望 auto-fix 后 True，实际仍判失败 |
  | TTM（4 个） | `np.allclose([nan,nan,nan,400,400,400], [100,200,300,400,400,400])` @ `test_fundamental_factors.py:113` | 前 3 期 NaN，第 4 期起才出值 | **TTM 窗口/年边界差分实现与测试期望不一致**（测试期望前 3 期即有滚动值） |
  | HA 轮换（1 个） | `np.isclose(199945.79, 199803.0, atol=1)` @ `test_ha_engineering.py:269` | 实际 199945.79 / 214745.79 / 214532.33 vs 期望 199803 | **冲击/滑点或 NAV 复利口径漂移 ~143**（合成算术测试，非数据依赖） |
  | 财务 loader（1 个） | `eps_ttm.notna().all()` 失败 @ `test_factor_mining_data_loader.py:163` | stderr「全量股票代码文件不存在: /tmp/…/all_stock_codes.csv」 | **测试 fixture 缺失**（临时目录无 CSV）→ 环境/夹具问题，非源码逻辑 |

- pytest_cov 缺失 → 覆盖率 **Tier-B：未复跑，沿用 AGENTS 2026-08-05 声明 57.88%**，标注风险。

### E2 三方对账

| 指标 | live_map / index (2026-07-09/10) | AGENTS 快照表 (2026-07-13 段) | AGENTS 最新相关 (2026-08-26) | 本会话实测 | 裁决 |
|------|----------------------------------|-------------------------------|------------------------------|------------|------|
| Python files | 256 | 252 | — | **264** | **源码 > 文档**；三方皆旧 |
| LOC | 62,549 | 60,351 (活跃) | — | **64,438** | 同上 |
| Test functions | 1,606 | — | — | **2,204** | 同上 |
| Tests passing | 1,673 / 0 fail | 2,051 (22 skip) | 2,303 / 8 skip / 0 fail (P12) | **16 FAILED（exit 1）** | **与 0 failed 声明冲突** → 冲突裁决 C2 |
| Ruff | 0 | 0 | 改动文件 r0；v9_* 存量 18 已知 | **18（仅 v9_*）** | 与 AGENTS「v9 存量 18」**一致**；与「0 ruff」全局表述**部分冲突** |
| Dead/archived | ~2,298 / archive 存在叙述 | 6 files 2,217 LOC archived | — | **archive 目录 0；quality+DynSlip+fsm 半死在树** | live_map 路径失效 → C3 |

### E3 覆盖率（B4 复确认）

- `import coverage` / `import pytest_cov` → **仍失败（模块缺失）** → **BLOCKED**。
- 0% 文件清单：**未复跑**，不引用旧 35/45 文件列表为现状；Tier-B 沿用 **57.88%**（AGENTS 2026-08-05）。
- 风险#6/#10 维持。

### E4 死码 LOC（B4 实测定稿）

| 文件 | LOC | ext_refs | 判定 |
|------|----:|----------|------|
| `signal/quality.py` | **297** | 5（偏 tests） | 半死 DEPRECATED |
| `shared/slippage_model.py`（整文件） | **47** | 1（类定义外测试） | DynamicSlippage 默认路径外 |
| `services/analysis/fsm_analysis_engine.py` | **247** | factory 懒加载；v2 无 | 半死（可选引擎） |
| `shared/config_models.py` | **71** | feature flag 模型 | 小，随 config |
| `shared/di_container.py` | **42** | **0**（除自身） | 薄包装/近死 |
| `shared/price_collar.py` | — | **MISSING** | 已删除 |
| `shared/factor_governance.py` | — | **MISSING** | 已删除 |
| `services/analysis_service_legacy.py` | — | **MISSING** | 已删除 |
| `*/archive/` 目录 | — | **0 个** | C3 |

**树内所列和 ≈ 784 LOC** vs AGENTS「~2.2k 死码/2,217 archived」→ **口径裁决**：AGENTS 含**已删除** legacy（1,651）+ factor_governance 等历史归档；**当前树内半死码远小于 2.2k**。不新开 C 号，并入 E2/C3 族备注；收尾建议改 AGENTS 表为「已删 / 在树半死」二分（批准后）。

### E5 CI workflows（B4 完成）

| 文件 | 关键步骤 |
|------|----------|
| `.github/workflows/test.yml` | `ruff check src/uniquant/ tests/ scripts/`（:30）+ `pytest tests/ -q --tb=short` + pip-audit |
| `.github/workflows/benchmark.yml` | Benchmark job（92 行级） |
| `.github/workflows/security-audit.yml` | pip-audit |

**3/3 在位**；lint 范围与 E6 一致。

### E6 lint 配置（P2，B4 完成）

- `pyproject.toml:57` `[tool.ruff.lint.per-file-ignores]` 存在；`:58-60` 注释豁免 scripts sys.path 引导语境；`"scripts/**" = ["E402"]`（E401/F841 等**未**豁免 → v9_* 仍红）。
- `test.yml:30` `ruff check src/uniquant/ tests/ scripts/` → **范围覆盖 src/tests/scripts** ✓；当前树 CI lint **预期 FAIL（18）**。

### E7 会话 git status 快照（P2，B4 完成）

```
# 首（B4 取证时）与尾（写盘前复核）一致：
?? docs/analysis/FULL_AUDIT_20260922/
?? docs/analysis/PROMPT_ADVERSARY_20260922.md
?? docs/prompts/full_project_audit_prompt_v2.md
TRACKED=0
```

**READ-ONLY 纪律保持**：仅白名单 untracked；0 tracked 修改。

## 与历史对账

- AGENTS「0 ruff (src+tests+scripts)」与本会话 **src+tests=0、scripts=18** → 表述过宽；v9 存量例外已披露。
- AGENTS「2303 passed / 0 failed」与本会话 **16 FAILED（exit 1）** → **重大冲突 C2**（根因四家族：DataValidator 自动修复 10、TTM 滚动 4、HA 算术 1、财务 fixture 1）。
- live_map archive 路径与「6 archived files」→ **文件系统 0 archive** → C3。

## 风险分级

| ID | 级 | 风险 |
|----|----|------|
| C2 | **C** | 全量测试 16 失败 vs 历史 0 failed——回归门失效；四家族根因已定位 |
| C2a | **H** | DataValidator auto-fix 10 个失败——数据质量防线测试绿区可能已红 |
| C2b | **M** | TTM 4 个——`calculate_field_ttm` 与测试期望口径不一致（前 3 期 NaN） |
| C2c | **M** | HA 算术 1 个——轮换引擎 NAV 期望值漂移 ~143（非数据依赖） |
| M1 | **H** | CI lint 含 scripts 必红（18 ruff） |
| M2 | **M** | coverage 工具缺失，57.88% 不可会话复证 |
| M3 | **M** | 三方文件/LOC/测试数全面漂移，控制文档失真 |

## 建议动作（含 DoD）

1. **修/隔离 16 个 FAILED**（根因四家族已定位，见 §E1 根因表）— DoD：`pytest tests/ -q` 汇总行 0 failed 或全部标注 skip 原因。
2. **ruff v9 或 per-file-ignore** — DoD：`ruff check src/ tests/ scripts/` exit 0。
3. **刷新 AGENTS/index/live_map 指标**（收尾批准制）— DoD：数字=本会话实测（264/64438/16 FAILED）。

## 附录 A：本会话命令摘要（E1/E2/E4-E7）

```
ruff check src/ tests/ scripts/  → 18 errors, exit 1（全 v9_* scripts）
pytest tests/ -q --tb=no         → exit 1, short summary 16 FAILED（原文 /tmp/opencode/pytest_b1_full.txt）
pathlib scan                     → src 264/64438, tests 172, test_fns 2204
八层 import                      → 8/8 OK
BARE_COUNT=0  EXC_COUNT=34
根因定向复跑 --tb=line           → 4 家族样本已入 §E1 根因表
# B4：
import coverage/pytest_cov       → FAIL → E3 BLOCKED
wc -l quality/slippage/fsm/...   → 297/47/247/71/42；MISSING price_collar/factor_governance/legacy；archive 0
ls .github/workflows             → test.yml, benchmark.yml, security-audit.yml
rg per-file-ignores pyproject    → :57 在位；test.yml:30 ruff 全范围
git status（首=尾）              → 3 untracked 白名单；TRACKED=0
```
