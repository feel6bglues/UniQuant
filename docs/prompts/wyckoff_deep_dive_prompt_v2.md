# Wyckoff 正确实现方案 Deep-Dive 研究提示词（v2.0）

> 用途：对 `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` 确立的方案做深入再研究（多 subagent 并行审计 + 验证脚本实证 + 多轮红蓝对抗），输出修订版实现方案。
> 生成：2026-08-12。配合 AGENTS.md 与 CLAUDE.md 使用。

---

## 角色设定（Role Stack）

你同时是三种身份的顶级专家：

1. **量化金融算法分析师**：精通横截面/时间序列推断、多重检验校正、动量残差控制、幸存者偏差；对"A股量化研究项目的 Wyckoff 8 轮证伪史"有完整认知。
2. **顶级交易员**：精通 Wyckoff 理论 + A股微观结构（T+1、涨跌停、一字板、板块联动）；严格区分"叙事价值"与"方向 alpha 价值"。
3. **顶级程序员**：精通 Python / TDD / 多 subagent 并行编排；坚持确定性、可复现、0 ruff、逐行核验、不臆造行号。

## 任务总目标

基于本项目实际代码（`src/uniquant/`、`tests/`、`scripts/`、`config/`），对 `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md` 确立的"Wyckoff 正确实现方案"做深入再研究。不是复述，而是通过：**多 subagent 并行代码审计 → 小规模验证脚本实证 → 数据驱动的多轮红蓝对抗**，逐项【证实/证伪/修订】该方案 P0/P1/P2 与"8 项不做"，最终输出一份有数据支撑、逐行可溯源的【修订版实现方案】到文件。

## Ground Truth（以下为已确立事实，禁止无依据推翻）

- 引擎目标态 = **叙事 + 风控层，完全不产方向入场信号**（除非对抗轮新证据突破）。
- 三层绝缘 + **三套相位→方向映射**（adapter / `normalizer._DIRECTION_MAP` / `engine.scan_signal`）；`V3TradingPlan.direction` 是孤儿数据，唯一消费者是旧离线回测 `hands/strategies/wyckoff.py:61`。
- 六类信号剔尾(|fwd|≤10%)后**无一同号显著**；leader 本质 ≈ 20d 相对动量。
- 任何"正面结论"必须同时通过：**剔尾稳健性 + 动量残差控制 + 老窗外样本 + 预注册阈值**。
- A股铁律：T+1、涨跌停、markdown/distribution 禁做多、`unified_engine` SELL=只平仓语义。

## 必读文件（先读再动手）

1. `docs/analysis/WYCKOFF_CORRECT_IMPLEMENTATION_20260812.md`（本次修订对象）
2. `docs/analysis/WYCKOFF_RESEARCH_MASTER_SUMMARY.md`（研究全景，避免重复劳动）
3. `AGENTS.md`（项目控制上下文 + 全部证伪史）
4. `CLAUDE.md`（10 条编码铁律）
5. 关键代码（逐一精读）：
   - `src/uniquant/brain/wyckoff/engine.py`
   - `src/uniquant/signal/adapters.py`, `normalizer.py`, `arbitrator.py`
   - `src/uniquant/services/analysis/wyckoff_analysis_engine.py`
   - `src/uniquant/services/pack_writer.py`, `research_pipeline.py`
   - `src/uniquant/shared/interfaces.py`
   - `src/uniquant/hands/backtest/unified_engine.py`
   - `config/config.yaml`

## 分阶段执行方法

### Phase 0 — 代码扎根（主智能体自做，先于一切）

- `git status` 确认工作树；用 rg/read 精读关键文件；
- 建立"**现状-方案差异表**"（方案要求 vs 代码现状，逐行标 `文件:行号`）。

### Phase 1 — 多 subagent 并行审计（≥5 路，同时启动）

| 路 | 审计方向 | 核心问题 |
|---|---|---|
| A | 引擎核心 | `_step5_trading_plan` 各 direction 分支是否如方案所述；`_detect_*` 死桩；ATR/一字板接线点；P1-1 改签名后 8 调用点+3 测试兼容性逐点核验 |
| B | 信号链 | direction 透传完整性（WyckoffOutput→writer→`_extract_wyckoff`→adapter→normalizer→arbitrator→unified_engine）；RDP wyckoff-only 展平确切位置；SELL-as-entry 是否有泄漏 |
| C | 实证 | 复算三窗 + 补老窗(2025-06-30/2024-12-31)，核验 F7 剔尾结论、置信存活表、动量残差 |
| D | 外部+A股规则 | P1 各项标注增强 vs 外部参考实现 vs A股微观结构可行性 |
| E | 风险/退出层 | P1-11 止损触发层与 FORCE_EXIT / LPPL Danger / NTF / markdown 风控交互，查重复与冲突 |

**约束**：各 subagent 输出"事实 + 证据(文件:行号) + 裁决建议(采纳/修改/否决)"；禁止输出未验证推测；重复探索用 explore agent 兜底。

### Phase 2 — 验证脚本小规模计算（先定预注册阈值，再写脚本，再出数据）

脚本放 `scripts/wyckoff_experiments/`，确定性、可复现、支持 `--as-of`：

1. `direction_map_check.py` — P0-2 映射表对三窗+老窗做确定性断言（BUY>0、0 SELL、覆盖率）
2. `confidence_survival.py` — markup 置信 A/B/C/D × 20d/60d 超额（剔尾前后）
3. `buyset_momentum_residual.py` — adapter BUY 集 20d 超额 + 动量残差(M1/M2/R3)
4. `atr_trigger_diff.py` — P1-1 before-after 触发集对照（漂移>5% 撤回）
5. `stoploss_exit_check.py` — P1-11 退出层触发率 on golden_100（确认不误杀）

数据规模：golden_20 冒烟 → golden_100 / 分层 1000 只分析。

**预注册**：运行前写明每个检验判定阈值（MWU p≥0.05@≥2/3 窗；剔尾后 2/3 窗显著才升级）；运行后数据**原样呈现**，不得事后选择性报告。

### Phase 3 — 数据分析（实证核验）

逐项对照方案声明 → 输出"**数据证据表**"（声明/数据/阈值/判定）。违反预注册阈值的声明标记为"待对抗裁定"，不得直接采纳。

### Phase 4 — 多轮红蓝对抗（≥4 轮，主智能体主持）

| 轮 | 红方攻击视角 | 攻击重点 |
|---|---|---|
| R1 | 统计严谨性 | 多重检验、regime 非独立、fwd 重叠、尾部依赖、剔尾边界选择 |
| R2 | 代码正确性 | 实现是否真做到宣称行为（逐行反证）；有无新泄漏路径 |
| R3 | A股微观结构 | T+1/涨跌停/一字板/流动性下执行可行性 |
| R4 | 外部+历史幻觉 | 与 yc/pine 参考实现差距；hindsight/过拟合/alpha 幻觉复活 |

**规则**：红方攻击必须有证据/反例/数据；蓝方回应必须基于代码或数据；每项最终裁决 = **采纳 / 修改 / 否决** + 一句理由；幸存结论才进入修订方案。

### Phase 5 — 综合修订 + 输出文件

输出 `docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md`，结构：

1. 结论摘要（一句话）
2. 现状-方案差异表（文件:行号）
3. 验证脚本数据证据表 + 预注册阈值记录
4. 多轮红蓝对抗记录（攻击/回应/裁决）
5. 修订版实现方案（相对 20260812 的 Delta：新增/修改/维持/移除）
6. 修订版不做清单
7. 实施顺序 + 验收门
8. 开放问题/待验证

同步 AGENTS.md。

## 硬性约束

- 一切结论必须有 `文件:行号` 或 数据 依据；无依据主张禁止写入。
- 禁止臆造行号；一切行号先 read 确认。
- 遵守 CLAUDE.md 10 条铁律；TDD；0 ruff；相关测试全绿。
- 不修改 A股规则文件除非附带聚焦测试。
- 不引入新的方向 alpha 主张，除非通过全部预注册门槛。

## 验收标准

- 每个 subagent 交付物有证据链；每个对抗裁决有理由；每个方案 Delta 有数据或代码支撑。
- 脚本可复现（固定 seed、确定性），数据留存 `results/` 或脚本输出目录。
- 抽查全文 0 幻觉行号；ruff 0；相关测试通过。
