# Phase 9 — 最终建议路线图 (v2.0)

> 日期: 2026-07-06 (roadmap) / 2026-07-09 (live system map corrections)
> 基于 Phase A-K v2.0 深度审计结论 + Phase I live system map 验证
> **纠正项**: Wyckoff 76→40, signal/db 0%→93%, eastmoney 1094→3, 源文件 251→256, LOC 62,300→62,465, 测试 1,461→1,591

---

## 当前评级总览 (v2.0)

| Phase | 领域 | 评级 |
|---|---|---|
| A | 代码质量 | Fair (3.0/5) — 116 处重复, Wyckoff 复杂度 40 (class total 285), hands 层 5 处非法反向依赖 |
| B | 测试质量 | Fair (2.0/5) — mutmut 基线运行失败, 56 测试无 assert (47 用 raises, 9 真弱), 无击杀率基线 |
| C | 数据质量 | B+ (3.5/5) — 5934/5934 100% 可读, 28 天延迟, 5542 .tmp.lock 残留 |
| D | 引擎正确性 | B+ (3.8/5) — 2 致命 BUG(FSM/Wyckoff), 3 次要, 7 引擎全量采样 0 错误 |
| E | 回测信任 | B+ (3.5/5) — 7 防线全部 PASS, 缺敏感性扫描和 A 股基准 |
| F | 信号系统 | A- (3.8/5) — signal/db.py 93% 覆盖 (35 tests), 适配器层 29% 覆盖 |
| G | 性能 | A- (4.0/5) — I/O 64.4MB/s, GIL 限制 ThreadPoolExecutor |
| H | 安全 | B+ (3.5/5) — 0 严重, 1 高危 eastmoney SSL verify=False |
| I | 可观测性 | C (2.0/5) — 指标系统 F 级完全缺失 |
| J | 综合评分 | **3.29/5.0 — B (有条件就绪)** |

---

## 建议优先级

### P0 — 立即修复 (5 项)

| 项目 | 来源 | 类型 | 预估工时 |
|---|---|---|---|
| 修复 FSM 空 DataFrame `df.iloc[-1]` IndexError 崩溃 | Phase D | Bug | 1h |
| 修复 Wyckoff Inf 数据 OverflowError 崩溃 (WYCKOFF_RECOVERABLE_ERRORS 缺 OverflowError) | Phase D | Bug | 1h |
| 修复 eastmoney.py:76 SSL verify=False | Phase H | 安全 | 0.5h |
| ~~添加 signal/db.py 测试覆盖~~ ✅ 已完成 (35 tests) | Phase F | 测试 | 4h |
| 添加 Prometheus/OpenTelemetry 指标暴露 | Phase I | 可观测 | 8h |

### P1 — 本周修复 (8 项)

| 项目 | 来源 | 类型 |
|---|---|---|
| 清理 .tmp.lock 文件残留 (5542 个) | Phase C | 运维 |
| 修复 mutmut 路径错位 (config_loader.py _root_dir 在 mutants/src/ 下失效) | Phase B | 测试 |
| ProcessPoolExecutor 替代 ThreadPoolExecutor (GIL 加速 3-6x) | Phase G | 性能 |
| 添加 Adapter 层单元测试 (当前仅 NTFAdapter 29% 覆盖) | Phase F | 测试 |
| 清理 116 处重复代码块 (data/sources 间 78 行优先) | Phase A | 重构 |
| 添加滑点/费用敏感性扫描到回测 | Phase E | 回测 |
| TradingSignal 添加 to_dict() 序列化方法 | Phase F | 功能 |
| 集成 A 股基准指数到回测结果 | Phase E | 功能 |

### P2 — 本月修复 (10 项)

| 项目 | 来源 | 类型 |
|---|---|---|
| WyckoffEngine._step1_phase_determine 圈复杂度 40 → ≤20 拆分 | Phase A | 重构 |
| hands 层 5 处非法反向依赖 (hands→data/brain) | Phase A | 重构 |
| LPPL Inf 数据假阳性 (confidence=0.6 Danger) | Phase D | Bug |
| Regime 引擎接口不匹配 (string 符号 vs DataFrame) | Phase D | Bug |
| CZSC fallback 4 处 TODO 接线 | Phase D | 功能 |
| 配置 schema 验证 (Pydantic) | Phase A | 健壮性 |
| 统一 board_type 注册表 (双系统合并) ✅ 已完成 via board_registry.py | Phase K | 重构 |
| 数据延迟从 28 天降至 <1 天 | Phase C | 运维 |
| 添加 E2E 测试 (Pipeline→Brain→Signal→Backtest) ✅ 已完成 (task #33) | Phase B | 测试 |
| 数据湖高频数据接入 (分钟/周/月线) | Phase C | 数据 |

### P3 — Q3 目标 (8 项)

| 项目 | 类型 |
|---|---|
| 变异测试击杀率基线 ≥80% | 测试 |
| CODEOWNERS + PR 模板 | 治理 |
| 替换 rate limiting 为强制配置 | 安全 |
| 性能基准测试 CI 集成 | 测试 |
| 清理 12 处 100% 置信度死代码 | 重构 |
| Grafana 仪表盘配置 | 可观测 |
| 覆盖门禁 50% → 60% → 70% → 80% 阶梯提升 | 测试 |
| 所有模块裸 except 和过度捕获清理 | 异常处理 |

---

## 架构改进建议 (v2.0 新增)

### 5. ProcessPoolExecutor 替代 ThreadPoolExecutor
`run_batch()` 使用 `ThreadPoolExecutor` 受 GIL 限制。在纯 CPU 密集型引擎计算场景，`ProcessPoolExecutor` 可提供 3-6x 加速。需注意进程间 `ServiceContainer` 实例隔离。

### 6. Adapter 层测试覆盖率门禁
当前仅 NTFAdapter 有单元测试 (29%)。建议对 8 个 Adapter 每个增加至少 3 个测试用例（正常/边界/异常），目标 ≥80%。

### 7. signal/db.py 持久化层守卫
315 行 93% 覆盖的持久化层 (35 tests)是生产环境最高风险点。建议: (1) 添加完整 CRUD 测试 (2) 添加连接池超时/重试 (3) 添加事务保护。

### 8. 异常处理标准化
Phase A 发现 1 处裸 except (research_pipeline.py:237)、hands 层 64% except Exception 过度捕获、data 层 49%。建议制定异常处理规范: 顶层捕获、区分可恢复/不可恢复、各层异常互见。

---

## 最终结论

UniQuant v2.0 深度审计完成:

- **256 源文件, 62,465 LOC** — 规模稳定
- **1,591 测试, 1,666 通过 (99.8%)** — 测试覆盖充足
- **综合评分 3.29/5.0 — B (有条件就绪)**
- **阻塞条件**: 5 项 P0 修复 + 指标系统 + signal/db.py 覆盖

**当前就绪状态: Beta → 生产过渡期 (v2.0)**

核心量化逻辑 (引擎 + 回测 + 信号) 评级 B+ ~ A-。
阻塞生产就绪的 5 项 P0 修复预计 15 工时可完成。
修复后预估评级升至 **4.0/5.0 — A- (建议实盘)**。