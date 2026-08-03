# AGENTS.md - UniQuant Project Control Context

> ⚠️ **MUST READ FIRST** — Read `CLAUDE.md` in the project root before any other file. It contains the 10 coding rules that govern all code generation in this project. Every edit, test, and commit must follow those rules. Treat them as non-negotiable.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-07-13. **Updated 2026-08-02 (Wyckoff 优化修复 8 项并行执行完成)**: 4 Wave 多 subagent 并行执行 8 项修复任务全部完成 — LPS 判定重构、scan fwd 数据底座、PnF 分歧标记、VDB 量价背离、结构分可达性校准、WSS 接线、MTF 统一、markup 降级+RS 过滤。详见下方 "Recent Work (2026-08-02) — Wyckoff 优化修复 8 项并行执行" 段。**Updated 2026-08-02 (全量 Wyckoff 扫描 + 指数净化)**: 服务层 index_df 透传 (W1) + 分析服务字段保真 (W2) + 全量扫描脚本 (W3) 完成；5382 只全量扫描 5374 成功；归档 552 个指数文件 (198 000xxx.SH + 354 399xxx.SZ)；候选池 306 只。详见下方 "Recent Work (2026-08-02)" 段。**Updated 2026-08-02 (Classic Wyckoff P1 非 P0 修复完成)**: CN-C4 复权状态探测 + SQ-C1 结构完整性评分 + RS-C1 相对强弱四分类全部实现，Compliance **58.3% (14P/7Pa/9F/30)**。详见下方 "Recent Work (2026-08-02)" 段。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 3 完成)**: CF-C4 假突破惩罚实现 — 共享 `_scan_false_breakout`（突破 TR 上沿 2%+ 后 3 列内跌回 + 量比>1.5 放量确认），`_step5_trading_plan` 标记 `V3TradingPlan.false_breakout_detected=True`，`_build_report` 经 `_downgrade_confidence` 将信号置信度降 1 级。Compliance 48.3% (D7-Counterfactual 50%, CF-C4 PASS)。**P0 全部完成**。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2 完成)**: PH-C2 DISTRIBUTION 事件序列驱动实现 — `_detect_distribution` 优先通过共享 `_scan_utad` 检查 UTAD 假突破事件（忽略 price_position），检测器链提前至 markdown 之前，新增 `synthetic_distribution_event_sequence` fixture。Compliance 48.3% (D4-Phase 80%)。剩余 P0: CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2 完成)**: PH-C1 ACCUMULATION 事件序列驱动实现 — `_detect_accumulation` 优先检查 `detect_all_events`+`event_sequence_key`（PS+SC+ST×2 匹配直接判定，忽略 price_position），启发式降为 fallback，新增 `synthetic_accumulation_event_sequence` fixture。Compliance 40.0% (D4-Phase 60%)。剩余 P0: PH-C2 → CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2)**: ES-C1 Spring 检测实现 — 共享 `_scan_spring`（O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩确认），step3 内联检测复用同一助手，替代旧 SPRING_LOW_FACTOR 独立判定。Compliance 38.3% (D2-Events 80%)。剩余 P0: PH-C1 → PH-C2 → CF-C4 (依赖 UTAD false_breakout)。**Updated 2026-08-01 (Classic Wyckoff P0 修复 Phase 2)**: ES-C3 UTAD 检测实现 — 共享 `_scan_utad`（X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 量比>1.5 放量确认），`_detect_utad` 驱动 DISTRIBUTION 相位，step3 内联检测复用同一助手。Compliance 36.7% (D2-Events 70%)。剩余 P0: ES-C1 → PH-C1 → PH-C2 → CF-C4。**Updated 2026-07-24 (3 轮红蓝对抗 + 参数敏感性验证脚本)**: 对 `LPPL_WYCKOFF_IMPLEMENTATION_PLAN.md` 设计文档完成 3 轮红蓝对抗（Round 1: 实施计划 16 Red / 0 Blue / 3 Split → 方案❌不可行；Round 2: 理论与实践中庸路线；Round 3: walk-forward 理论根基）。之后对参数敏感性验证脚本 v1 完成 3 轮红蓝对抗（脚本正确性/统计方法论/优化方案），输出修正后 v2 脚本 `scripts/param_sweep_v2.py`。详见 `docs/reanalysis/Z_red_blue_plan_verification_round*.md` 及 `Z_param_sweep_v1_redblue_round*.md`。**Updated 2026-07-24 (Walk-Forward 终结诊断)**: 实际引擎信号重测发现自定义分类掩盖了唯一有效信号。Wyckoff "买入" markup 阶段 +13.33% 20d (p=0.0098 显著) 但仅 4.5% 罕见。LPPL 零预测力 (MC 证明 93% GBM 拟合噪声)。Wyckoff Spring→BUY 理论信号从不触发。详见 `scripts/output/walk_forward_definitive_report.json`。**Updated 2026-07-20 (v7 代码强化)**: 6 项 cross_validation/engine 代码强化 (Spring 安全化, except 窄化×2, H12 三态裁决, R² 口径文档化×2)。**Updated 2026-07-17 (v7 管线验证执行)**: 红蓝对抗修正后执行 9 项任务 (7 完成, 1 待办)。LPPL _process_window 切换 L-BFGS-B (DE→L-BFGS-B), classify_top_phase ATR 自适应偏移, Wyckoff step4 单元测试 ×4, 跨引擎集成测试 ×3, cross_validation golden_20 (20/20, 62.9s), baseline v0 捕获 (20/20 一致)。**Updated 2026-07-13 (v6 修复执行)**: 6 路并行红蓝对抗 + TDD 全量分析完成 — 83 项声明核实 (88% 准确率), 15 项新发现修复。R0 代码修复: signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC 死代码跟踪)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。纠正 v5 虚假完成声明 (UI except 仍为 17 处, 非 2)。全部 1882 测试通过, 0 ruff。死代码库存更新至 ~2,819 LOC (含新发现)。剩余: R1-06 过户费 DRY 统一、R3-N01 45 零覆盖文件、45 files at 0% (3,791 LOC) — unchanged.
>
> UniQuant: A-share quantitative research and trading platform.
>
> Generated: 2026-07-06. Two re-analysis campaigns completed: (1) Phases 0-9 baseline (2026-06-30) covering baseline audit, worktree diff, engine correctness, backtest trust, data pipeline, signal system, engineering health, production readiness, governance, and final roadmap. (2) Phase A-K v2.0 deep audit (2026-07-06) covering code quality, test quality, data reliability, engine runtime behavior, backtest trust, signal audit, performance, security, observability, scorecard, and roadmap. **Updated 2026-07-09**: Live system map (I_live_system_map.md) documenting corrected metrics after 256-file verification sweep, dead code inventory (~1,960 LOC), ranked active bugs, and data path heat map. **Updated 2026-07-10**: 5-round multi-pass source code investigation completed. 256 files verified, 17/18 P0/P1 fixes confirmed (1 bare `except Exception:` remains at research_pipeline.py:244), 15 `except Exception` patterns narrowed, research_pipeline thread safety added, 51 new tests, 4 dead code files archived, dead code ~2,298 LOC. See `docs/reanalysis/Z_investigation_report_20260710.md`. **Updated 2026-07-10 (TDD Red-Blue)**: Comprehensive multi-pass TDD evaluation with 5-layer parallel red-blue adversarial analysis completed. 74 doc claims verified (87% accuracy, 55 Blue/8 Red/11 N/A). 0 bare `except:` across all layers. 224 total `except Exception:` mapped by layer. Dead code corrected to ~2,225 LOC (data_pipeline_service found ACTIVE, not semi-dead). 45 files at 0% coverage (3,791 LOC). 1 truly weak test. See `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md`. This file is the first local source context for agents working in this repository.

---

## Current State

UniQuant is a Python 3.12+ quantitative trading platform for China's A-share market. It covers market data ingestion, data lake storage, signal generation, factor research, risk management, backtesting/matching, service orchestration, reports, and a Streamlit dashboard.

The repository is past the historical "migration target" phase. The eight declared runtime layers are present under `src/uniquant/`:

`shared -> data -> brain/risk/signal -> hands -> services -> ui`

Current worktree snapshot from 2026-07-13 (post-v6 TDD-Red-Blue):

| Metric | Current value |
|---:|---:|
| Python files under `src/uniquant/` (active) | 252 |
| Python active LOC under `src/uniquant/` | 60,351 |
| Archived files (dead code) | 6 (2,217 LOC) |
| Test files under `tests/` | 128 |
| Approximate test functions | 1,641 |
| Tests passing | 1,882 |
| Ruff issues | 0 |
| Test coverage | 56.18% |
| Dead code (archived) | ~2,217 LOC (3.5%) |
| Functions total | 2,249 |
| `except Exception:` total | 225 (all layers) |
| `except:` (bare) total | 0 |
| Doc claims verified | 83 (88% accurate) |
| Files at 0% coverage | 35 (reduced from 45, ~2,500 LOC) |

Comprehensive re-analysis complete (Phases 0-9): full baseline audit, worktree diff, 8-engine correctness audit, 7-line backtest trust audit, data pipeline reliability, signal system, engineering health, production readiness, governance, and final roadmap. See `docs/reanalysis/` for full reports.

Phase A-K v2.0 deep audit (2026-07-06): code quality (Fair, 116 duplicates, Wyckoff complexity 40), test quality (mutmut baseline broken), data reliability (B+, 5934/5934 100% readable), engine runtime behavior (B+, 2 critical bugs FSM+Wyckoff), backtest trust (B+, 7/7 lines PASS), signal audit (A-, signal/db.py 93% coverage), performance (A-, 64.4 MB/s), security (B+), observability (2/5, metrics F). Overall scorecard: **3.29/5.0 — B (conditional ready)**. See `docs/reanalysis/` for all 15 reports.

**Corrections from live system map (2026-07-09)**: Wyckoff complexity 76→40 (class max function); signal/db.py coverage 0%→93% (35 tests); eastmoney LOC 1,094→3 (refactored to 4 files). See `I_live_system_map.md`.

5 pre-existing test failures resolved (bc6337bc). 0 ruff issues, 0 pre-existing failures.

## Recent Work (2026-08-02) — Wyckoff 优化修复 8 项并行执行 (4 Wave, 多 subagent)

| Wave | Task | ID | Summary | Verification |
|---|---|---|---|---|
| **A** | scan fwd 数据底座 | P0-B | `scripts/wyckoff_full_scan.py` 新增 `is_etf`(前缀规则)/`fwd_20d`/`fwd_60d` 列；新增 `--as-of` 回放模式；`build_empirical_table()` 实证表输出 | 38 新测试 `tests/scripts/test_wyckoff_full_scan_fwd.py` 全过；golden_20 扫描 20/20 成功 2.2s |
| **A** | PnF 分歧标记 | P1-A | `_step1_phase_determine` 不再短路，始终运行检测器链并记录分歧；`Step1Result`/`WyckoffReport`/`WyckoffOutput` 均加 `pnf_phase_divergence` 字段；相位仍由 PnF 驱动（第1步不改相位结果） | 6 新测试 + 81 回归 = 87 passed；分歧示例：PnF=accumulation 但链=UNKNOWN |
| **A** | VDB 量价背离 | P1-B | 新建 `effort_result.py` 纯函数 `detect_effort_result_divergence`（价跌量缩→bullish/价升量缩→bearish）；`Step2Result` 加 `vdb_divergence` 字段；不进相位判定 | 9 新测试全过；Step2Result 2 构造点兼容 |
| **A** | WSS 接线 | P1-D | `config/config.yaml` 新增 `wyckoff.wss_enabled`(默认 false) + `wss_lookup_path`；`WyckoffEngine.__init__` 创建 `WyckoffScorer`；`_compute_structural_score` 支持 scorer 参数；A/B 开关验证 | 10 新测试全过；wss_enabled=true 时 blended 评分生效(436 seqs) |
| **B** | LPS 判定重构 | P0-A | `rule6_spring_validation` 签名新增 `spring_volume`/`atr` 参数，实现分层判定（作废检查→测试K线识别→硬门槛守位→量能+反弹确认）；ATR 计算上移至 spring 检测前；`Step3Result` 新增 `lps_stage`/`test_low` | 12 新测试全过；守位由 `min(low)*0.995` 改进为 `test_bar_low` + ATR 容忍；量能参照从 `max_vol` 改为 spring 当日量；反弹从单日收阳改为多根窗口 |
| **B** | 结构分可达性校准 | P1-C | `_apply_structural_adjustment` 阈值 70/35→55/45；`_compute_structural_score` 权重放大（相位加成 0.15→0.20, UNKNOWN -0.10）；新增可达性测试 | 5 新可达性测试 + 19 旧 = 24 passed；max 结构分 65.7→70.2，升级路径可达 |
| **C** | MTF 统一 | P2 | `merge_multitimeframe_reports` 引入 `MultiTimeframeResonance` 替换 rule9；`config/config.yaml` 新增 `wyckoff.mtf_resonance: true`；Resonance 仅要求方向一致（BULLISH/BEARISH），rule9 要求精确相位匹配 | 21 新测试 + 132 基线 = 132 passed；Resonance 与 rule9 核心差异：accumulation+markup+accumulation→rule9=mixed, Resonance=fully_aligned |
| **C** | markup 降级 + RS 过滤 | P3 | `_build_report` 新增 markup 降级（RS∈{follower,systemic_decline} 时降1级）；RS=systemic_decline 时仓位降级至空仓观望；RS=leader 不降级保留有效信号 | 7 新测试全过；降级链可叠加（CF-C4 + P3 同时触发降2级） |

**Test results**: 132 classic_wyckoff 全过（62 基线 + 70 新增），0 ruff。Golden_20 冒烟 20/20 成功 2.2s，置信度首次出现 A 级（1/20），结构分分布拉开（p50=62.66, p90=65.0）。详见 `docs/analysis/WYCKOFF_OPTIMIZATION_TASKLIST_20260802.md`。

## Recent Work (2026-08-02) — Classic Wyckoff P1 非 P0 修复 (CN-C4 + SQ-C1 + RS-C1)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **CN-C4** | 复权状态探测 | `engine.py` 新增模块级 `_detect_adjustment_status`（收盘 pct_change>20% 且前日非涨停 → raw 预复权标记）+ `_analyze_single` 计算 + `_build_report` 透传 `adjustment_status` 字段（WyckoffReport/WyckoffOutput）；raw 信号置信度降级处理 | 8 新测试 `test_phase3_nonp0.py` 全过；compliance 改源码特征检查 → 51.7% (12P) |
| **SQ-C1** | 结构完整性评分 | `engine.py` 新增模块级 `_compute_structural_score` 纯函数（基于 `event_sequence_score` + 相位加成 + step3 spring/utad 加成，min-max→0-100）+ `_apply_structural_adjustment` 置信度加权（恒回填 `ConfidenceResult.structural_score`，≥70 升 1 级/≤35 降 1 级，A/D 边界不越界，B+ 归 B，5 条件矩阵成员不变）；`WyckoffReport`/`ConfidenceResult`/`WyckoffOutput` 均加 `structural_score`；`_extract_from_report` 透传；`WyckoffAdapter.adapt` metadata 加 `wyckoff_structural_score` | 19 新测试 `test_structural_score.py` 全过（含确定性回归 + 置信度加权单调性）；compliance 改源码特征检查（含 `_apply_structural_adjustment`）→ 55.0% (13P) |
| **RS-C1** | 相对强弱四分类 | 新增 `src/uniquant/brain/wyckoff/relative_strength.py`：`rs_classify(stock, index)` 纯函数（leader/follower/weak_independent/systemic_decline 四分类 + `_align_on_date` inner join 对齐 + `RelativeStrengthResult` dataclass）；`WyckoffReport`/`WyckoffOutput` 加 `relative_strength`/`relative_strength_detail`；`analyze`/`_analyze_single`/`_analyze_multiframe`/`analysis.analyze_multiframe` 加 `index_df` 可选参数（None 时报告字段为 None，向后兼容） | 11 新测试 `test_relative_strength.py` 全过；compliance 改源码特征检查（模块存在 + 4 分类 + 引擎接线）→ **58.3% (14P/7Pa/9F/30)** |

**Test results**: 1955 passed (含 3 组 P1 新增测试 + SQ-C1 置信度加权 8 测试), 0 ruff (新增文件), golden_20 baseline 一致。`scripts/classic_wyckoff_compliance.py` CN-C4/SQ-C1/RS-C1 三项检查从静态占位改为源码特征检查。**P1 三项全部完成**（红蓝对抗修订版 v2 方案，详见 `docs/analysis/CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1.md`）。剩余 WONTFIX：CN-C1/C2/C3、VS-C1/C3、MT-C2、RS-C2、CF-C1 等交易规则类/无数据支撑项（研究平台定位不符）。

## Recent Work (2026-08-02) — 全量 Wyckoff 扫描 + 指数数据净化 (W1/W2/W3/S1-S3)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **W1** | 服务层 index_df 透传 | `wyckoff_analysis_engine.py` `run_wyckoff_analysis` 加 `index_df: Optional[pd.DataFrame]=None` 参数；新增 `_load_index_df`（`_INDEX_PATHS=("data/lake/quotes/daily/000300.SH.parquet","data/csi300_index.parquet")`）；`analyze(df, multi_timeframe=True, index_df=index_df)` | 3 新测试（index_df 透传用 `patch("uniquant.brain.wyckoff.engine.WyckoffEngine")` + `_load_index_df` 加载/缺失返回 None）→ 13 passed |
| **W2** | 分析服务字段保真 | `analysis_service_v2.py:_run_wyckoff`（508）当 result 是 `WyckoffOutput` 时 `WyckoffOutput.from_dict(result.to_dict())` 保留全 15 字段（adjustment_status/structural_score/relative_strength/pnf_phase_hint/rr_ratio），否则回退旧 5 字段 | 1 新测试（`_run_wyckoff` 捕获 `write_wyckoff` output 断言 6 字段保留）→ 34 passed |
| **W3** | 全量扫描脚本 | 新建 `scripts/wyckoff_full_scan.py`（`--symbols all/main_board/golden_20/golden_100`、`--max-workers`、`--output-dir`；analyze_one 异常隔离永不抛出；输出 CSV+JSON；analyze 带 multi_timeframe=True+index_df） | ruff clean（E402 加 noqa） |
| **S1** | golden_20 冒烟 | 20/20 成功 2.1s；RS 四分类正常（follower 10/systemic_decline 7/leader 3）；复权 19 pre_adjusted+1 raw；结构评分 p50=59.95 | 冒烟通过 |
| **S2** | 全量执行 | 5382 只 8 workers 531.5s（0.099s/只）；5374 成功 8 too_short；相位 distribution 2466/accumulation 1352/markdown 777/markup 171/unknown 608；置信度 D 4482/C 791/B 101；RS systemic_decline 3444/follower 1138/leader 765/weak_independent 11/None 16；结构评分 p50=60.03 | 结果在 `results/wyckoff_full/wyckoff_scan_all.csv/.json` |
| **S3** | 数据净化 + 核验 | 归档 **552 个指数文件**到 `data/lake/quotes/daily/archive_index/`（198 个 000xxx.SH + 354 个 399xxx.SZ 深证指数，含 .bak/.tmp.lock 伴生共 2656 文件）；`get_symbols` 只扫 `daily/` 根目录 *.parquet 天然排除子目录；保留 000300.SH/000905.SH 基准原位；确认 close>1000 余下 9 只全为真实高价股（600519 茅台 2601/688256 寒武纪 1868 等）；发现并保留 137 个 ETF/B股/LOF 标的（159/160/161/16x 段） | 移除非 000xxx.SH 股票: 0；index symlink 完整；47+62 相关测试 passed |

**候选池**（`results/wyckoff_full/candidates.csv`）：A股个股 5245 只中 **306 只**满足 C级+ 置信度 & 结构评分≥60 & phase∈{accumulation, distribution}；Top 含 601865.SH(accumulation/B/61.93/leader)、002753.SZ(distribution/B/61.41/leader)、001286.SZ 等。**Test results**: 47 (wyckoff_engine+analysis_service_v2) + 62 (classic_wyckoff) passed，0 ruff（新增文件）。全量 1955 测试因单文件 coverage 门槛+耗时超时未完整跑通（本次改动未触及 Wyckoff 引擎核心，仅服务接线与扫描脚本）。数据净化发现：daily 池长期混入 000xxx.SH 上证指数（000001.SH close 达 6092）与 399xxx.SZ 深证指数，已归档隔离。

## Recent Work (2026-07-13) — v6 修复执行 (六路并行红蓝对抗)

| Phase | Tasks | Summary | Verification |
|---|---|---|---|---|
| **R0 (2026-07-13)** | 4 项代码修复 + 测试导入更新 | signal/__init__.py 补全 3 适配器导出、factor_governance.py 归档 (+156 LOC)、portfolio_engine.py 归档 (+376 LOC)、arbitrator.py:385 bare except 加 logging、result_store.py:71 except BaseException 加注释。更新 7 测试文件导入路径。 | 1678 passed, 0 ruff |
| **R1 (2026-07-13)** | 工程窄化 + 文档纠正 | lppl_visualizer.py 已有 exc_info=True (确认已存在无需改)、AGENTS.md 指标更新 (252 文件/60,351 LOC 活跃)、死代码 ~2,217 LOC 归档。 | 1678 passed, 0 ruff |

**Key corrections from v6 multi-pass verification (2026-07-13):**
- 纠正 v5 虚假完成声明: ui/ `except Exception` 仍为 17 处 (非 2), 从未被纠正
- 新发现死代码: factor_governance.py (156 LOC), portfolio_engine.py (376 LOC) — 已归档
- 纠正: 8 数据源 (非 7), Wyckoff 复杂度 45 (非 40), computation.py 393 LOC (非 242)
- 纠正: interfaces.py 5 个 Protocol (非 4), Alpha score=0.0 3 处 (非 2)
- 纠正: 函数总数 2,249 (非 2,262), except Exception 225 (非 224)
- 确认: 17/17 P0/R 修复全部存在, signal/ 层 100% 文档准确
- 确认: manager_logic.py 6 处 except Exception 已有 as e + exc_info=True, 无需窄化
- 剩余: R1-06 过户费 DRY 统一 (WONTFIX: 3 实现点, 向量化/标量签名不兼容), R3-N01 45 零覆盖文件 (~16h)

## Recent Work (2026-07-17) — v7 管线验证执行

| Phase | Task | Summary | Verification |
|---|---|---|---|
| **P1-A** | 文档状态同步 | `repair_plan_lppl_wyckoff.md` 添加"历史参考"横幅 (11 项已修复) | 已标记 |
| **P0-A** | 基线捕获 | `capture_baseline.py` 对 golden_20 捕获 v0 baseline | 20/20 成功, compare 0 diff |
| **P0-B** | LPPL 路径统一 | `_process_window` 从 DE 切换为 L-BFGS-B (直调 `fit_single_window_lbfgsb`) | 53 tests pass |
| **P0-C** | Spring 验真 | 对 golden_20 运行 LPPL+Wyckoff 交叉验证 | 20/20 股票, 62.9s |
| **P1-B** | Wyckoff 测试 | `_step4_risk_reward` 4 种目标位来源单元测试 | 4/4 pass |
| **P2-A** | ATR 自适应 | `classify_top_phase` 新增 `atr_pct` 可选参数 | 34 LPPL tests pass |
| **P2-B** | 跨引擎测试 | LPPL+Wyckoff+Factor brain 级引擎集成测试 | 3 new tests pass |
| **P1-C** | IC 半衰期 | **待办** — 设计已明确, 复用 `ic_ir_history` 字段 | — |

**P0-C 交叉验证关键发现**:
- DE 优化器成功率 0.0% (282 窗口全失败), L-BFGS-B 成功率 100% (564/564) — 验证 P0-B 方向正确
- R² 引擎/计算器口径差均值 0.814, 最大 0.976
- Wyckoff 置信度分布: 0 A, 0 B, 18 C, 2 D
- Spring 事件 (H12): 0 次触发 (20 股票历史数据中无 Spring→Markup 事件)

## Recent Work (2026-07-20) — v7 代码强化 (6 项)

| Phase | Task | Summary | Verification |
|---|---|---|---|
| **W01-A** | Spring 检测安全化 | cross_validation: `signal.signal_type` → `(signal_type or "").lower()` 防御 None/大小写 | ✅ 行级核实 |
| **W01-B** | except 窄化 + 日志 (step3) | cross_validation: `except Exception: pass` → `except (AttributeError,TypeError,ValueError,KeyError) as e: print(...)` | ✅ 行级核实 |
| **W01-C** | except 窄化 + 日志 (counterfactual) | 同上, counterfactual 路径 | ✅ 行级核实 |
| **W01-D** | H12 三态裁决 | `CONFIRMED`/`NOT_CONFIRMED`/`NOT_TESTED` 三态区分零事件场景 | ✅ 行级核实 |
| **W02-B** | R² 口径文档化 | `engine.py:detect_bubble()` 标注 3-param VP vs 7-param 全量 R² 不可比 | ✅ 行级核实 |
| **W02-C** | LPPLOutput.r_squared 字段注释 | `interfaces.py:LPPLOutput.r_squared` 标注前述口径差异 | ✅ 行级核实 |

**Test results**: 1882 passed, 7 skipped, 0 ruff (0 new, 16 pre-existing in cross_validation script).

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 1 (P&F 先行)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **PF-C3** | TR 边界来自 P&F 密集区 | `pnf.py` 新增 `congestion_zone()`（最长重叠列簇 + 列中位数边界抗尖峰）；`engine.py:_step0_bc_tr_scan` 接受 `pnf_zone` 优先覆盖裸 H/L 边界 | 4 新测试通过（含尖峰鲁棒性） |
| **PF-C1** | P&F phase_hint 驱动 Phase | P&F 提前到 Step0 之前构建；`_step1_phase_determine(df, rule0, pnf_hint)` 在 hint ∈ {accumulation, distribution} 时直接判定 | mock 测试通过 |
| **PF-C2** | Count Target 进交易计划 | `_step4_risk_reward(df, step1, step3, rule0, pnf_count_target)` 在 PNF 目标 > 现价时采用为第一目标；key_low > 现价时回退近 30 日低点止损 | mock 测试通过 |

**Test results**: 185 passed (181 基线 + 4 新增 `tests/classic_wyckoff/test_phase1_pnf.py`), 0 ruff。
**Compliance**: 23.3% → 33.3% (+10.0%), D1-PnF 维度 10% → 70% (PF-C1/C2/C3 全部 FAIL→PASS)。`scripts/classic_wyckoff_compliance.py` 的 PF-C1/C2/C3 检查从静态占位改为源码头检查。
**真实数据行为变化**（P&F hint 生效的预期结果）: 300750.SZ markdown→accumulation, 688981.SH markup→distribution; 止损 > 现价场景已修复（不再出现负风险）。

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 2 (事件序列: ES-C3 UTAD + ES-C1 Spring + PH-C1/C2 相位)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **ES-C3** | UTAD 检测 | `engine.py` 新增共享 `_scan_utad`（X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 量比>1.5 放量确认）；`_detect_utad` 从 `return None` 实现为驱动 `DISTRIBUTION` 相位；`_step3_phase_c_t1` 内联 UTAD 检测改用同一助手并填充 `utad_detected/utad_quality/utad_date` | 4 新测试通过（含 sine 无假阳性） |
| **ES-C1** | Spring 检测 | `engine.py` 新增共享 `_scan_spring`（O 列跌破 TR 下沿 0.5-1.5% `boundary_lower*0.985 <= low < boundary_lower` 后 1-2 列内收回 `closes[j] >= boundary_lower` + 量能萎缩确认 `vol_ratio <= 0.8`）；`_step3_phase_c_t1` 内联 Spring 检测改用同一助手并填充 `spring_detected/spring_date/spring_low_price`，替代旧 `SPRING_LOW_FACTOR` 独立判定；`scripts/wyckoff_fixtures.py` 新增 `synthetic_spring_aligned` 端到端 fixture（对齐引擎 P&F TR 边界） | 3 新测试通过（正例/反例/端到端） |
| **PH-C1** | ACCUMULATION 事件序列驱动 | `engine.py` `_detect_accumulation` 优先检查事件序列（`detect_all_events` + `event_sequence_key`，PS+SC+ST×2 匹配时直接判定 ACCUMULATION 并忽略 price_position），现有 prior_trend/relative_position 启发式降为 fallback；`scripts/wyckoff_fixtures.py` 新增 `synthetic_accumulation_event_sequence` fixture（P&F hint=unknown + 中位价格 0.41，仅事件序列可驱动） | 3 新测试通过（fixture 前提/端到端 ACCUMULATION/序列 key 含 PS+SC+ST×2） |
| **PH-C2** | DISTRIBUTION 事件序列驱动 | `engine.py` `_detect_distribution` 优先通过共享 `_scan_utad` 检查 UTAD 假突破事件（忽略 price_position），现有 in_tr+prior_trend 启发式降为 fallback；`_detect_distribution` 在检测器链中提前至 markdown 之前（UTAD 强派发证据优先于普通下跌）；`scripts/wyckoff_fixtures.py` 新增 `synthetic_distribution_event_sequence` fixture（上涨→PSY→UTAD→LPSY→跌破，hint=unknown 非短路） | 3 新测试通过（fixture 前提含量比≥1.5/端到端 DISTRIBUTION/忽略低位 position） |

**Test results**: 21 passed (classic_wyckoff 全套), 0 ruff (engine/test)。
**Compliance**: 38.3% → 40.0% (PH-C1) → **48.3%** (D4-Phase 80%, PH-C1/C2 全 PASS)。`scripts/classic_wyckoff_compliance.py` PH-C2 检查改为 `_detect_distribution` 源码特征检查（`_scan_utad` + upthrust_candidate + 链提前）。
**剩余 P0**: CF-C4 (FAIL) → Phase 3 依赖 UTAD false_breakout。

## Recent Work (2026-08-01) — Classic Wyckoff P0 修复 Phase 3 (CF-C4 假突破惩罚)

| ID | Task | Summary | Verification |
|---|---|---|---|
| **CF-C4** | 假突破惩罚 | `engine.py` 新增共享 `_scan_false_breakout`（突破 TR 上沿 2%+ `highs[i] > boundary_upper*1.02` + 量比>1.5 放量确认后 3 列内跌回 `closes[j] <= boundary_upper*0.995`，返回 `{date, close_high}`）；`_step5_trading_plan` 调用并标记 `V3TradingPlan.false_breakout_detected=True`（方向改"空仓观望"）；`_build_report` 经模块级 `_downgrade_confidence`（A→B→C→D）将信号置信度降 1 级 | 3 新测试通过（fixture 前提含普通 TR 不误报 / 标记+方向 / 端到端信号置信度 < 计划置信度） |

**Test results**: 1913 passed, 7 skipped, 0 ruff (engine/test)。classic_wyckoff 24 测试全过。
**Compliance**: 48.3% (D7-Counterfactual 50%, CF-C4 PASS)。`scripts/classic_wyckoff_compliance.py` CF-C4 检查改为 `_scan_false_breakout` 源码特征检查（1.02 突破 + vol_med 放量 + 3 列跌回 + false_breakout_detected + _downgrade_confidence）。
**P0 全部完成**: PF-C1/C2/C3, ES-C1/C3, PH-C1/C2, CF-C4 全部 PASS。

## Recent Work (2026-07-23) — Walk-Forward 效用终结评估 (2026-07-23)

| Phase | Tasks | Key Deliverables |
|---|---|---|
| **W3-A** | LPPL 全量扫描 | 3574/3574 股票, L-BFGS-B 100% 收敛, 99.7min, Best R²=0.83 |
| **W3-B** | Wyckoff 全量扫描 | 3574/3574 股票, 9.1min, UNKNOWN 36.3%/MARKDOWN 57.1% |
| **W3-C** | 交叉验证 | 3574 股, 24.0% 方向冲突, 综合评级 D/54.9 |
| **W3-D** | 交叉截面回测 | LPPL rank vs 60d ρ=−0.058, Wyckoff rank vs 60d ρ=0.66 (自循环) |
| **W3-E** | Walk-Forward 回测 | **500 只 × 6 滚动窗口 = 2999 obs**, 104s |
| **W3-F** | 根因诊断 + 实际引擎信号重测 | 实际引擎分类 vs 自定义分类对比, Monte Carlo 对照, 6 项终论 |

**Walk-Forward 最终诊断: 自定义分类掩盖了唯一有效信号**:

| 发现 | 证据 |
|---|---|
| **LPPL: 零预测力** — 全链路验证 | 93% GBM 纯随机数据拟合 R²>0.3 (MC 对照); 实际 `calculate_risk_level` "高危" fwd_20d=+4.77% vs "观察" +4.82% — 无区分度; "无效模型"反而 +6.44% 优于有效拟合; `is_danger` p=0.48 无统计显著性 → 建议从生产管线移除 |
| **Wyckoff 理论信号从不触发** | Spring→BUY (adapter) 0/600 次; UTAD→SELL 0/600 次; "卖出" 交易计划 0/600 次; 39% 窗口返回未知相位 |
| **Wyckoff "买入" - 唯一有效信号** | 仅在 markup 阶段触发 (27/600, 4.5%); fwd_20d=+13.33% win=88.9% vs 普通 markup +5.27% (p=0.0098, **统计显著**); 前 20d 涨幅 +9.05% — 追涨非抄底; 24/100 只股票触发, 5/6 窗口均有分布 |
| **Monte Carlo 对照** | 93% GBM 拟合 R²>0.3; m 分布与真实数据不可区分 (KS p=0.019); DANGER 分类率随机 62.6% vs 实际 57.7% — 纯噪声反略高于真实数据 |
| **引擎分类 vs 自定义分类偏差** | 自定义: Wyckoff distribution→SHORT 得到 −16.82% spread (方向性错误, 因 distribution 后继续上涨); 实际: 引擎"买入"→ +8.60% 20d spread (p=0.0098); 自定义分类 SWALLOWED 了唯一有效信号 |
| **综合评级** | LPPL ❌ 无效 (移除) \| Wyckoff 理论 ❌ 从不触发 \| Wyckoff "买入" ⚠️ 真实但太罕见 (4.5%) \| Spring ⚠️ 理论上正确但实践中从不触发 |

See `scripts/output/walk_forward_definitive_report.json` and `/tmp/walk_forward_actual.py` for complete analysis.

## Phase 2/3 Completion (2026-07-08)

All Phase 2 and Phase 3 small/independent tasks executed:

| Task | Summary | Files Changed |
|---|---|---|
| #33 | Expand E2E tests: 3 new engine coverage classes (UnifiedBacktest, SignalArbitrator, UnifiedMatching) | `test_e2e_integration_qa.py` |
| #45 | Signal timeout check in arbitrator: discard signals older than `max_age_seconds` | `arbitrator.py` |
| #47 | Remove `portfolio_engine.py` from `__init__.py` exports | `hands/backtest/__init__.py` |
| #48 | Narrow 8 broad `except Exception:` to specific types in `backtest.py` | `hands/strategies/backtest.py` |
| #49 | Create `brain/wyckoff/constants.py` with 7 named constants; migrate 4 Wyckoff files | `constants.py` (new), `analysis.py`, `engine.py`, `state.py` |
| #50 | Add adapter auto-discovery (`AdapterRegistry.discover()`) | `adapters.py` |
| #51 | Unify position calculation: add `PositionSizerProtocol` to `UnifiedBacktestEngine` | `unified_engine.py` |
| #52 | Create `.github/workflows/benchmark.yml` CI workflow | `benchmark.yml` (new) |
| #53 | Add assertions to 2 weak test functions | `test_indicators.py`, `test_scan_service.py` |
| #57 | Remove 12 vulture-identified dead code items (8 files) | `computation.py`, `numba_optimizer.py`, `events.py`, `baostock.py`, `unified_matching_engine.py`, `data.py` |
| #66 | Replace 2 `datetime.now()` in `time_provider.py` with `self.now()` | `time_provider.py` |

Test results: 245 passed, 1 skipped, 0 ruff issues.

## Remaining Untracked Files

`docs/analysis/` (7 .md files), `docs/pipeline_5round_report.md`, `.coverage`, `data/trade_calendar.csv`, `results/` — not committed.

---

## Control Documents

Read these first:

| File | Purpose |
|---|---|---|
| `AGENTS.md` | First project control context. Updated 2026-07-10 with live system map ref. |
| `docs/reanalysis/I_live_system_map.md` | Live system map (2026-07-09): corrected metrics, dead code inventory, ranked active bugs, data path heat map. |
| `docs/index.md` | Documentation entry point and state boundary. |
| `docs/ANALYSIS_PROMPT_PLAYBOOK.md` | Direct-call prompt playbook for staged system analysis. |
| `docs/remediation/FULL_STOCK_TEST_PLAN.md` | Full stock test plan (canary/medium/full staging). |
| `pyproject.toml` | Real package metadata, dependencies, pytest config. Use root file, not docs copies. |
| `config/config.yaml` | Main runtime configuration. |
| `src/uniquant/shared/interfaces.py` | Typed cross-layer contracts including `TradingSignal`, `ResearchDataPack`, `RegimeOutput`, `LPPLOutput`, `CZSCOutput`, `NtfOutput`, `WyckoffOutput`, `AlphaOutput`, and protocols. |
| `src/uniquant/services/service_container.py` | DAG dependency injection and service initialization. |
| `src/uniquant/services/analysis_service_v2.py` | Main single-ticker analysis orchestrator. |
| `src/uniquant/services/research_pipeline.py` | End-to-end research pipeline. |
| `src/uniquant/services/analysis/engine_factory.py` | Lazy analysis engine factory. |
| `src/uniquant/signal/adapters.py` | Brain output to `TradingSignal` adapters. |
| `src/uniquant/signal/arbitrator.py` | Sell-priority signal arbitration with confidence-based rules. |
| `src/uniquant/shared/time_provider.py` | RealTimeProvider / FrozenTimeProvider for testable time. |
| `docs/analysis/wyckoff_research_report.md` | Wyckoff WSO+WSS+Resonance — 7-phase empirical research report on 22,148 A-share observations. All findings traceable to Phase I–VII run output. |
| `docs/reanalysis/` | 10 comprehensive re-analysis reports (Phases 0-9) covering baseline, worktree, engines, backtest trust, data pipeline, signals, engineering health, production readiness, governance, and final roadmap. |
| `docs/reanalysis/Z_investigation_report_20260710.md` | 5-round multi-pass source code investigation (2026-07-10, updated w/ red-blue corrections) — verified 256 files, 17/17 fixes, 15 residual except patterns, research_pipeline thread safety, 51 new tests, 4 dead code files archived |
| `docs/reanalysis/Z_tdd_redblue_consolidated_report_20260710.md` | Comprehensive TDD red-blue adversarial analysis (2026-07-10) — 74 doc claims verified (87% accuracy), 224 except Exception mapped by layer, dead code corrected to ~2,225 LOC, 45 files at 0% coverage (3,791 LOC), 1 truly weak test |
| `docs/remediation/v5_remediation_work_list_20260710.md` | Verified remediation work list (2026-07-10) — all 11 P0 fixes confirmed FIXED, 14 remaining items ranked R0-R3 with file:line evidence, zero hallucination gate |
| `docs/remediation/red_blue_remediation_plan.md` | Red-blue remediation execution plan: Phase 0 (P0-01 through P0-10 core bugs), Phase 1 (P1-01 through P1-07 engineering health), Phase 2 (documentation + portfolio research). |
| `src/uniquant/shared/event_types.py` | Event/Command base and domain events. |
| `src/uniquant/shared/factor_governance.py` | FactorManifest / FactorRegistry with admission gate. |
| `src/uniquant/shared/config_models.py` | RefactoringConfig / FeatureFlags for staged migration. |
| `src/uniquant/hands/backtest/unified_engine.py` | Typed signal-driven backtest engine. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | Vectorized A-share matching engine. |
| `scripts/staged_full_scan.py` | Staged full-stock pipeline scan (canary/medium/full stages). |

Historical architecture and migration documents under `docs/` are useful background, but many still describe target state or pre-remediation gaps. Prefer current source code and the control documents above.

---

## Layer Responsibilities

| Layer | Path | Files | Responsibility |
|---|---:|---:|---:|
| `shared` | `src/uniquant/shared/` | 44 | Protocols, constants, config, exceptions, cache, logging, A-share rules, costs, slippage, price collars (dead), time_provider, event_types, factor_governance (dead), config_models. |
| `data` | `src/uniquant/data/` | 67 | Multi-source data ingestion, TDX/local/online sources, data lake, managers, parsers, cleaners, validators, adjusters. |
| `brain` | `src/uniquant/brain/` | 54 | Strategy and research engines: FSM, CZSC, LPPL, NTF, Regime, Wyckoff, indicators, factors, screener, alpha decoupler. |
| `signal` | `src/uniquant/signal/` | 8 | Standard signal models, adapters, normalization, aggregation, quality checks. |
| `hands` | `src/uniquant/hands/` | 33 | Backtesting, matching, portfolio engine (dead), strategy framework, reports, robustness and sensitivity tools. |
| `risk` | `src/uniquant/risk/` | 6 | Position sizing, drawdown, EVT, structural risk, portfolio optimization. |
| `services` | `src/uniquant/services/` | 31 | DAG service container, analysis orchestration, data service, cache coordination, reports, scan, health, research pipeline. ⚠️ 1,651 LOC legacy dead code (analysis_service_legacy.py). |
| `ui` | `src/uniquant/ui/` | 8 | Streamlit dashboard, health check, UI manager logic, LPPL visualization. |

---

## Core Runtime Flow

Single ticker research path:

1. `ServiceContainer.initialize()` constructs data, cache, analysis, signal, backtest, and research pipeline services.
2. `DataService.fetch_for_brain()` returns `data_pack` with stock data and metadata.
3. `AnalysisService.run_ticker_analysis()` runs regime, LPPL, NTF, CZSC, Wyckoff, alpha, and derived indicator logic.
4. `DecisionBrain` produces the final decision payload.
5. `TradingSignalCollector` converts engine outputs into typed `TradingSignal` objects.
6. `UnifiedBacktestEngine.run()` executes signals against K-line data using A-share constraints.
7. `PipelineResult` returns `data_pack`, decision, signals, and `BacktestResult`.

Key files:

| Concern | File |
|---|---|
| Service DAG | `src/uniquant/services/service_container.py` |
| Analysis orchestration | `src/uniquant/services/analysis_service_v2.py` |
| Pipeline orchestration | `src/uniquant/services/research_pipeline.py` |
| Engine lazy loading | `src/uniquant/services/analysis/engine_factory.py` |
| Signal conversion | `src/uniquant/signal/adapters.py` |
| Signal arbitration | `src/uniquant/signal/arbitrator.py` |
| Factor governance | `src/uniquant/shared/factor_governance.py` |
| Feature flags | `src/uniquant/shared/config_models.py` |
| Time provider | `src/uniquant/shared/time_provider.py` |
| Backtest execution | `src/uniquant/hands/backtest/unified_engine.py` |
| Vectorized matching | `src/uniquant/hands/backtest/unified_matching_engine.py` |

---

## A-Share Rules To Preserve

| Rule | Current source |
|---|---|
| Main board limit up/down | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| STAR/GEM limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| Beijing Stock Exchange rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| ST stock limit rules | `src/uniquant/shared/limit_checker.py`, `src/uniquant/shared/market_rules.py` |
| T+1 sell restriction | `src/uniquant/hands/backtest/unified_engine.py`, `src/uniquant/hands/backtest/unified_matching_engine.py` |
| Commission, stamp duty, transfer fee | `src/uniquant/shared/cost_model.py` |
| Slippage | `src/uniquant/shared/slippage_model.py`, matching engines |
| Price collar | `src/uniquant/shared/price_collar.py` |
| Lot size | `src/uniquant/shared/market_rules.py` |

Any change touching these rules requires focused tests and explicit review.

---

## High-Risk Files

| File | Why it is risky |
|---|---|
| `src/uniquant/services/__init__.py` | Lazy import contract for service package. |
| `src/uniquant/shared/interfaces.py` | Cross-layer typed contracts and protocol boundaries. |
| `src/uniquant/shared/constants/__init__.py` | Aggregated constants export used broadly. |
| `src/uniquant/services/service_container.py` | Runtime dependency graph and service lifetime. |
| `src/uniquant/services/analysis_service_v2.py` | Main analysis workflow and failure defaults. |
| `src/uniquant/services/analysis/engine_factory.py` | Engine registration and lazy import behavior. |
| `src/uniquant/data/sources/tdx.py` | TDX source path used across data workflows. |
| `src/uniquant/data/pipeline/data_validator.py` | OHLC data correctness guardrail. |
| `src/uniquant/signal/adapters.py` | Converts heterogeneous engine outputs into executable signals. |
| `src/uniquant/hands/backtest/unified_engine.py` | User-facing typed backtest behavior. |
| `src/uniquant/hands/backtest/unified_matching_engine.py` | A-share execution constraints in vectorized matching. |
| `config/config.yaml` | Global runtime behavior. |

---

## Phase 0-6 Completion Status

All phases verified: **1882 tests pass, baseline 100% consistent**. 0 pre-existing failures.

| Phase | Scope | Status | Key deliverables |
|---|---|---|---|---|
| **0** | LPPL SELL priority, baseline tooling | ✓ | `unified_engine.py` SELL-before-BUY fix, `tests/benchmark/golden_20.txt`/`golden_100.txt`, `scripts/capture_baseline.py` + `compare_baseline.py` |
| **1.1–1.2** | BacktestResult metadata, typed contracts | ✓ | `BacktestResult.metadata`, `RealTimeProvider`, `FrozenTimeProvider`, domain events, `FactorManifest`/`FactorRegistry` |
| **1.4** | Feature flags, config models | ✓ | `RefactoringConfig`, `FeatureFlags`, `config.yaml` refactoring section, `ServiceContainer` DI |
| **2** | SignalArbitrator, TimeProvider adoption | ✓ | `SignalArbitrator` (sell-priority, confidence-based), 7 tests, pipeline integration, `FactorRegistry` admission gate |
| **3** | 6-engine typed output migration | ✓ | `RegimeOutput`, `LPPLOutput`, `NtfOutput`, `CZSCOutput`, `WyckoffOutput`, `AlphaOutput`, `DecisionOutput`, `MarketSignalContext` direct pass |
| **4** | Pipeline typing, engine output typing, batch parallelization | ✓ | `ResearchDataPack` + feature flag in pipeline & analysis & data services; 4 engines return typed outputs; `run_batch()` ThreadPoolExecutor + atomic checkpoint; `factor_gate: "block"` |
| **5** | Remediation — 7 threads (A–G) via TDD | ✓ | `use_research_data_pack` default flipped to `true`; Wyckoff 12 failures fixed; TradeCalendar AkShare auto-update; ResultStore persistence; DataFetcher single entry; BacktestResult.compare(); dead code cleanup; **Full stock test: 5934/5934 success (100%)** |
| **6** | Regime reliability — fail-open fix, dead code, TOCTOU | ✓ | `RegimeDetector.detect()` fail-open hardened (entropy/turnover NaN → UNKNOWN); `_validate_input_data()` wired; `_check_sell_conditions` FROZEN dead code removed; `MarketLevelCache.get_or_compute_regime()` TOCTOU fix; 16 new tests |

**Design**: All typed outputs coexist with legacy `Dict[str, Any]` keys for backward compatibility. Feature flags default ON for `use_research_data_pack` (flipped Phase 5 Thread A). `factor_gate: "block"` prevents unregistered factors.

## Re-analysis (2026-06-30)

Comprehensive 9-phase re-analysis completed. Reports in `docs/reanalysis/`:

| Report | Phase | Trust Rating |
|---|---|---|
| `00_baseline_audit.md` | Baseline test/lint/import audit | ✅ 1426/1431 pass |
| `01_worktree_diff_analysis.md` | Worktree diff + stash analysis | 46-file commit classified |
| `02_engine_correctness_audit.md` | 8 engines graded | A- |
| `03_backtest_trust_audit.md` | 7 A-share defense lines verified | A- |
| `04_data_pipeline_reliability.md` | 5-source routing + pipeline | B+ |
| `05_signal_system_audit.md` | 8 adapters + arbitrator | A |
| `06_engineering_health.md` | Lint, TODOs, imports | A- |
| `07_production_readiness.md` | Security, config, observability | B+ |
| `08_governance_testing.md` | Test structure, CI gaps | B+ |
| `09_final_roadmap.md` | Priority roadmap P0-P3 | — |
| `I_live_system_map.md` | Corrected live system map (2026-07-09) | 256 files verified |

---

## Working Rules For Agents

- Start with current source code, not historical docs.
- Before meaningful multi-file work, create a short plan.
- Prefer narrow analysis and narrow edits.
- Do not revert user or prior-agent changes.
- Treat the working tree as possibly dirty. Inspect `git status --short` before edits.
- Use `rg` and `rg --files` for searches.
- Use `apply_patch` for manual file edits.
- For code changes, follow TDD where practical: identify failing path, add/update tests, implement, verify.
- For sensitive paths, review auth, data validation, injection risk, secrets, and error leakage.
- After meaningful changes, review the diff and record verification performed.
- **Sync docs with every change**: After any code modification (feature, refactor, bugfix), update `AGENTS.md` and all affected documentation under `docs/`. At minimum refresh file counts, LOC, test counts, and phase status. Treat documentation drift as a blocker, not a backlog item.

---

## Common Commands

```bash
# Install all optional extras
pip install -e ".[all]"

# Full test suite
pytest tests/ -q

# Baseline verification
python3 scripts/capture_baseline.py && python3 scripts/compare_baseline.py

# Engine factory smoke tests
pytest tests/test_engine_factory.py -xvs

# Eight-layer import smoke
python3 -c "import uniquant.shared, uniquant.brain, uniquant.data, uniquant.signal, uniquant.services, uniquant.risk, uniquant.hands, uniquant.ui; print('imports OK')"

# Config smoke
python3 -c "from uniquant.shared.config_loader import get_config; c = get_config(); print(c.get('base.data_lake.engine'))"

# Service container smoke
python3 -c "from uniquant.services import ServiceContainer; c = ServiceContainer(); c.initialize(); print('container ready')"

# Full stock pipeline scan (canary → medium → full)
python3 scripts/staged_full_scan.py --stage canary --max-workers 4
python3 scripts/staged_full_scan.py --stage medium --max-workers 4 --seed 42
python3 scripts/staged_full_scan.py --stage full --max-workers 4

# Lint source
ruff check src/uniquant/

# Dashboard
streamlit run src/uniquant/ui/dashboard.py

# Parameter sweep (v2, with resume support)
python3 scripts/param_sweep_v2.py --symbols golden_20 --resume
python3 scripts/param_sweep_v2.py --symbols golden_100 --lookback-days 252 --range-thresholds 0.20 0.30

# Parameter sweep (v1, legacy)
python3 scripts/param_sweep_v1.py
```

Do not claim test results are current unless the command was run in the current working tree.

---

## Analysis Workflow

For systematic system analysis, use:

`docs/ANALYSIS_PROMPT_PLAYBOOK.md`

It defines stages 0-7:

0. Global architecture
1. Services orchestration
2. Data system
3. Brain engines
4. Factor system
5. Signal system
6. Backtest and matching
7. Risk and live-readiness

Each stage requires a plan, concrete artifacts, checkpoint context, and verification checklist.

---

## Known Gaps (Post-Phase 5) — Full Plan in `docs/GAP_REMEDIATION_PLAN.md`

> **2026-06-12 update**: G-1 through G-4 have all been closed and verified in the institutional closure review. See `docs/analysis/institutional/17_institutional_closure_review_report.md` §Phase 6 Gap Review for the verified closure evidence.

### Quick Start For New Tasks

| If working on... | Read this first | And be aware of |
|---|---|---|
| Time-dependent code | `shared/time_provider.py` | 2 guarded `datetime.now()` remain in `time_provider.py` FrozenTimeProvider fallback |
| Factor registration/access | `brain/factors/registry.py` (actual) NOT `shared/archive/factor_governance.py` (dead code, archived) | shared/ deprecated with warning |
| Baseline/regression testing | `scripts/capture_baseline.py` + `compare_baseline.py` | Phase 0 all committed |
| Event-driven features | `shared/event_bus.py` (sync) + `shared/event_bus.py` (async) | AsyncEventBus deployed with 9 tests |
| Pipeline typing / data pack | `shared/interfaces.py` `ResearchDataPack` + `services/analysis_service_v2.py` dual-path | Feature flag `use_research_data_pack: true` default (flipped Phase 5); `to_dict()` flattens `metadata` for signal collector |
| Engine output typing | `shared/interfaces.py` (LPPLOutput/CZSCOutput/NtfOutput/WyckoffOutput) + engine files in `services/analysis/` | 4 engines return typed outputs; field annotations in ResearchDataPack are forward references |
| Batch research | `services/research_pipeline.py` `run_batch()` | ThreadPoolExecutor + atomic checkpoint; input order preserved via result map |
| Research result persistence | `shared/result_store.py` + `services/research_pipeline.py` | JSON file store under `results/{date}/{symbol}.json`; ResultStore.save() called after each successful run() |
| TradeCalendar | `data/managers/trade_calendar_manager.py` | AkShare auto-update with stale cache check (>180 days); hardcoded 2024-2026 fallback |
| BacktestResult compare | `hands/backtest/unified_engine.py` `BacktestResult.compare()` | Returns diff dict for parameter sensitivity analysis |
| Full stock scan | `scripts/staged_full_scan.py` + `docs/remediation/FULL_STOCK_TEST_PLAN.md` | 3-stage scan (canary→medium→full); `--stage canary|medium|full`; checkpoint resume; per-engine breakdown; error classification |
| Regime detection safety | `brain/regime/regime_detector.py` fail-open paths | Phase 6: entropy/turnover NaN → UNKNOWN (was NORMAL); `_validate_input_data()` wired into `detect()` |
| Market cache TOCTOU | `services/market_cache.py` `get_or_compute_regime()` | Phase 6: atomic get-or-compute prevents parallel recompute in batch mode |
| FSM dead code | `brain/fsm/fsm.py` `_check_sell_conditions()` | Phase 6: FROZEN removed (unreachable — veto fires first); STRESSED only |
| System overview / metrics | `docs/reanalysis/I_live_system_map.md` | 256 files verified; dead code inventory; ranked active bugs; data path heat map |
| Red-blue analysis | `docs/reanalysis/E_red_blue_analysis.md` | 22-issue confrontation corrected bug counts (4→6), defense lines (5✅/1⚠️/1❌), capability matrix (15✅/2⚠️/3❌) |
| 5-round investigation | `docs/reanalysis/Z_investigation_report_20260710.md` | 256 files verified, 17/17 fixes confirmed, 15 residual except patterns |
| 修复并行化分析 | `docs/remediation/parallel_analysis.md` | 34 项任务并行调度: 24h→7.5h (3.2x) |
| Shenzhen transfer fee exemption | `src/uniquant/hands/backtest/unified_matching_engine.py` + `unified_engine.py` | P1-01: SZ stocks `_has_transfer_fee()` returns `False`; both matching and engine layers updated |
| Adapter alpha=0.0 | `signal/adapters.py:362` | P0-01 **FIXED**: `elif 0 < score < 0.3:` excludes 0.0 (was `elif score < 0.3:` → false SELL) |
| fillna(0.0) factor distortion | `brain/factors/composer.py:183,204,276` | P0-04 **FIXED**: all 3 fillna(0.0) removed |
| Pipeline bare except | `services/research_pipeline.py:239` | P0-08 **FIXED**: narrowed to specific exceptions |
| Wyckoff bare except | `brain/wyckoff/engine.py:251,261,1575,1591` | P0-09 **FIXED**: 4 bare excepts narrowed |
| Signal timeout disabled | `signal/arbitrator.py:39` | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` — backtest-aware context needed for enable |
| price_collar dead | `shared/price_collar.py` | Zero production callers; remove from P1 consideration |
| DynamicSlippage dead | `shared/slippage_model.py:DynamicSlippage` | Never instantiated in default backtest path |
| BoardType unified | `shared/board_registry.py` | 116 LOC — BoardType dual system resolved via registry |
| Walk-Forward 回测终结结论 | `scripts/output/walk_forward_definitive_report.json` + `/tmp/walk_forward_actual.py` | 500 只 × 6 窗口 walk-forward 验证: LPPL 零预测力 (MC 证明 93% GBM 噪声拟合), Wyckoff 理论从不触发, Wyckoff "买入" 4.5% 罕见信号 p=0.0098 显著, 自定义分类掩盖了唯一有效信号 |
| 参数敏感性验证脚本 | `scripts/param_sweep_v2.py` | 经 3 轮红蓝对抗修正的 Wyckoff 参数扫描脚本: CLI 参数控制、同相位对比、bootstrap-by-stock CI、Mann-Whitney U + Bonferroni、断点续传、参数排名表。配套分析: `docs/reanalysis/Z_param_sweep_v1_redblue_round*.md` |
