# Phase J — 生产就绪度评分卡

> 日期: 2026-07-06 (scorecard) / 2026-07-09 (live system map corrections)
> 基于 Phase A–I 报告结论 + Phase I live system map 验证，8 维度加权评估
> **纠正项**: Wyckoff 复杂度 76→40 (单个函数 max, class total 285), signal/db 覆盖率 0%→93%, eastmoney LOC 1094→3

---

## 综合评分

| 维度 | 权重 | 评分(1-5) | 加权 | 评级 |
|---|---|---|---|---|
| 数据可靠性 | 20% | 3.5 | 0.70 | B+ |
| 引擎正确性 | 20% | 3.8 | 0.76 | B+ |
| 回测信任度 | 15% | 3.5 | 0.53 | B+ |
| 代码质量 | 10% | 2.5 | 0.25 | C+ |
| 测试质量 | 10% | 2.0 | 0.20 | C |
| 性能 | 10% | 4.0 | 0.40 | A- |
| 安全 | 10% | 3.5 | 0.35 | B+ |
| 可观测性 | 5% | 2.0 | 0.10 | C- |
| **总分** | **100%** | | **3.29** | **B** |

颜色指示: A(≥4.0) B(≥3.0) C(≥2.0) D(≥1.0) F(<1.0)

---

## 每个维度的评分理由

### 数据可靠性 [3.5/5] — B+

- **优点**: 5934/5934 文件 100% 可读，覆盖 1992-01-02 ~ 2026-06-08 完整区间；多源数据管线（通达信/本地/在线）已稳定运行。
- **扣分项**: 数据延迟 28 天（对实盘信号影响重大）；5542 个 `.tmp.lock` 文件残留（无需修复但数量大）；分钟/周/月线目录为空，仅有日线；`fq/` 复权目录不存在，复权因子依赖通达信本地计算；16 处异常值集中在 1992-1994 年早期数据。
- **评级**: B+ — 日线数据可靠，但分钟/复权缺失 + 28 天延迟严重限制实盘适用性。

### 引擎正确性 [3.8/5] — B+

- **优点**: 7 引擎全量采样 100 文件 0 错误；内存/CPU 极低（50 文件 0.25s, 2.3MB）；83 个 seed 引用确保确定性可重复；信号仲裁健全（SELL 优先 + 质量门禁）。
- **扣分项**: 2 个致命 BUG（FSM 空 DataFrame IndexError 崩溃、Wyckoff Inf 溢出 OverflowError 崩溃）；3 个次要问题（LPPL Inf 假阳性、Regime 接口不匹配、CZSC fallback 未消费 TODO）。
- **评级**: B+ — 运行时稳定性优秀，但 2 个空数据崩溃场景需立即修复才能达到生产级。

### 回测信任度 [3.5/5] — B+

- **优点**: 7 条 A 股防线全部 PASS（T+1、涨跌停、停牌、资金约束、费用、滑点、整手）；回测出具 `BacktestResult` 含完整元数据；`sensitivity_scan()` 支持滑点/佣金遍历 + 基准收益率集成。
- **扣分项**: 组合引擎路径不一致；默认无风险利率 3%。
- **评级**: B+ — 核心合规执行正确，敏感性扫瞄已补齐，但组合回测路径仍不完整。

### 代码质量 [2.5/5] — C+

- **优点**: 类型提示覆盖率较高（`shared/interfaces.py` 定义了完整 typed contracts）；文件按层组织，职责清晰。
- **扣分项**: 116 处重复代码块（`data/sources` 间 78 行重复）；`brain` 层圈复杂度最高 5.42，WyckoffEngine._step1_phase_determine 函数复杂度 40（class total 285）；~2,298 LOC 死代码/半死代码（含 1,649 LOC analysis_service_legacy.py）；1 处裸 except（`research_pipeline.py:237`）；`hands` 层 5 处违反依赖方向（hands→data/brain）；3 个文件超 1000 LOC。
- **评级**: C+ — 结构设计合理但实现质量粗糙，死代码和高复杂度函数是维护隐患。

### 测试质量 [2.0/5] — C

- **优点**: 测试套件规模较大（~1,606 测试函数, 1,673 pass）；`cost_model` 变异测试 40 个变异体在独立运行中全部通过。
- **扣分项**: mutmut 变异测试基线运行失败（路径错位导致 `config/config.yaml` 无法加载），未获得击杀率数据；56 测试函数无 `assert`（47 使用 raises, 9 真正弱, 并非 20+）；`signal/db.py` 315 行 93% 测试覆盖（35 tests — 此前 0% 报告错误）；Adapter 层覆盖仅 29%（仅 NTFAdapter 有单元测试）。
- **评级**: C — 测试数量可观但质量参差不齐，核心 CRUD 和适配器层存在重大覆盖缺口，变异测试无法运行意味着无法量化测试有效性。

### 性能 [4.0/5] — A-

- **优点**: 数据 I/O 64.4 MB/s，全量 5934 票顺序读 19s；无内存泄漏（20 次循环增长仅 24KB）；最慢 10 票为长历史大盘股（600519.SH 7879 行 3.4ms）。
- **扣分项**: 冷/热启动比 10.1x（缓存预热代价大）；GIL 限制 ThreadPoolExecutor，推荐 ProcessPoolExecutor（预估 3-6x 加速）。
- **评级**: A- — 单进程性能优异，瓶颈明确且可预测，GIL 限制是已知问题且有明确优化路径。

### 安全 [3.5/5] — B+

- **优点**: 0 严重漏洞；密钥从环境变量读取；日志过滤敏感字段；无 pickle/无 subprocess/无 SQL 注入风险（无数据库 SQL）。
- **扣分项**: 1 高危（`eastmoney.py:76` SSL verify=False）；3 中危（requests CVE-2023-32681、cryptography 41.x EOL、缺安全扫描工具）；2 低危（urllib3 CVE-2024-37891、速率限制未强制）。
- **评级**: B+ — 基础安全实践到位，但有已知 CVE 未修复和关键下载器证书验证关闭的问题。

### 可观测性 [2.0/5] — C-

- **优点**: 日志体系 B 级（~60 WARNING, ~80 ERROR, ~10 CRITICAL）；健康检查 A- 级（ServiceContainer 已实现健康检查端点）。
- **扣分项**: 指标系统 F 级 — 完全缺失，无 Prometheus/OTel/metrics API；无结构化日志；8 条可观测性改进建议均未实施。
- **评级**: C- — 生产系统最薄弱的维度。日志够用、健康检查有、但指标完全缺失是无法运行的基本门槛。

---

## P0/P1/P2 修复清单

### P0 — 立即修复 (5 项)

| # | 问题 | 来源 | 预估工时 |
|---|---|---|---|
| 1 | FSM 空 DataFrame IndexError 崩溃 | Phase D | 2 小时 |
| 2 | Wyckoff Inf 溢出 OverflowError 崩溃 | Phase D | 2 小时 |
| 3 | `signal/db.py` 315 行 93% 覆盖（35 tests）— **此前 0% 报告错误** | Phase F | ✅ Already fixed |
| 4 | `eastmoney.py:76` SSL verify=False 高危漏洞 | Phase H | 1 小时 |
| 5 | 完整的 metrics 系统缺失（Prometheus/OTel）— 生产运行最低要求 | Phase I | 24 小时 |

### P1 — 本周修复 (8 项)

| # | 问题 | 来源 | 预估工时 |
|---|---|---|---|
| 6 | 解决 28 天数据延迟 — 实盘信号的时间敏感数据源 | Phase C | 8 小时 |
| 7 | 清理 5542 个 `.tmp.lock` 文件 | Phase C | 1 小时 |
| 8 | 修复 mutmut 路径错位使变异测试可运行 | Phase B | 2 小时 |
| 9 | 补齐 Adapter 层测试覆盖（当前仅 29%） | Phase F | 6 小时 |
| 10 | 修复 requests/cryptography 已知 CVE | Phase H | 2 小时 |
| 11 | 为 WyckoffEngine._step1_phase_determine 做圈复杂度降级（40→<20, class total 285） | Phase A | 4 小时 |
| 12 | 消除 12 处 100% 置信度死代码 | Phase A | 2 小时 |
| 13 | 修复 `research_pipeline.py:237` 裸 except | Phase A | 1 小时 |

### P2 — 本月修复 (12 项)

| # | 问题 | 来源 | 预估工时 |
|---|---|---|---|
| 14 | 消除 116 处重复代码块（优先 data/sources 层） | Phase A | 8 小时 |
| 15 | 为 20+ 无 assert 测试函数补充断言 | Phase B | 4 小时 |
| 16 | 分钟/周/月线数据管线 | Phase C | 16 小时 |
| 17 | 复权因子目录（fq/）实现 | Phase C | 8 小时 |
| 18 | 滑点/费用敏感性扫描工具 | Phase E | ✅ Already fixed in red-blue P1-03 |
| 19 | 组合引擎路径对齐 | Phase E | 4 小时 |
| 20 | A 股基准指数集成（沪深 300 / 中证 500） | Phase E | ✅ Already fixed in red-blue P1-03 |
| 21 | 5 处 hands→data/brain 依赖方向违规修复 | Phase A | 3 小时 |
| 22 | ProcessPoolExecutor 迁移（预估 3-6x 加速） | Phase G | 6 小时 |
| 23 | 实现结构化日志（JSON/OTel） | Phase I | 6 小时 |
| 24 | 引入安全扫描工具（bandit/dependency-check） | Phase H | 3 小时 |
| 25 | 强制速率限制中间件 | Phase H | 2 小时 |

---

## 生产就绪总评分

**综合评分: 3.29/5.0 — B（有条件就绪）**

**是否建议实盘: 有条件**

**主要阻碍（必须解决方可实盘）:**

1. **指标系统缺失（可观测性 F 级）** — 无法监控运行时健康、无法告警、无法事后排查。这是最根本的阻塞项。无 Prometheus/OTel 等价于盲飞。
2. **FSM/Wyckoff 空数据崩溃** — 任何边界数据（新股、停牌恢复首日）都会导致任务级崩溃，实盘中不可接受。
3. **`signal/db.py`** — 此前报告 0% 覆盖，验证后实际为 93%（35 tests）✅ 此项已非阻塞。
4. **SSL verify=False 高危** — 工具链核心下载器绕过证书校验，存在 MITM 敏感数据泄露风险。
5. **28 天数据延迟** — 实盘策略依赖近实时数据，28 天延迟使信号完全不可用。

**解决以上 5 项后的预估评分: 4.0/5.0 — A-（建议实盘）**

---

## ANALYSIS COMPLETE