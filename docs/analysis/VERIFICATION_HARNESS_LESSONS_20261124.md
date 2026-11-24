# 验证 harness 的经验教训与门禁处方（2026-11-24）

> **定位**：本文是 2026-11-24 N2N 十报告独立专家评审（`docs/analysis/n2n/INDEPENDENT_EXPERT_REVIEW_20261124.md`）
> 之后的一次**跨轮归因 + harness 反思**。它不新增待修 bug，而是回答一个问题：
> **为什么同一类验证失败在这个仓库里反复复发，以及该在 harness 上装什么门才能真正拦住。**
>
> **方法**：① 逐条回源码独立复核专家评审的重指控（未采信评审结论，见 §2 表）；
> ② 把 11-24 的每条失败模式回溯到 2026-05~07 红蓝语料的在库先例（§3 对照表）；
> ③ 审计现有机械门禁的覆盖面（§4）。只读分析，未改任何源码。
>
> **一句话结论**：失败不是"不知道"，而是"已诊断、已命名、已开出处方，却没通电、没跨界搬运"。

---

## 1. 触发事件：11-24 的自评与独立评审之间的鸿沟

2026-11-24 产出的 N2N 报告集形成了自指闭环：

| 层 | 自评结论 | 独立评审结论 |
|---|---|---|
| 10 份 N2N 报告 | 18 个问题，**0 CRITICAL / 0 HIGH**，整体健康度全"✅优秀" | 02/04/05/08/09 报告"部分可信/存疑"，**未审模块也盖"优秀"= 评审诚实性问题** |
| `FINAL_ACCEPTANCE_REPORT` | **4.75/5"优秀"，"完成 P1 后可上线实盘"** | 三方独立认定"证明不了 alpha 可信、证明不了实盘能这么干" |
| 可信度基石 | `DEEP_VERIFICATION_9_REPORTS` 的 **"98.9% 准确率"** | **循环自证**——验证者与被验证者同源自产 |
| 报告 09 头号 P1 结论 | LPPL SELL 优先级遗留，附"精确到行号"的代码 | **该段代码系虚构**：声称 `arbitrator.py:32-42` 是 `LPPL:1(最高)`，实测 `lppl:99(最低)`，方向完全颠倒 |

## 2. 独立复核：评审的重指控全部坐实（未采信评审，直接回源码）

| 指控 | 本次实测（当前工作树） | 结论 |
|---|---|---|
| PositionSizer fail-open | `src/uniquant/signal/arbitrator.py:406` `except Exception: sized_shares = 100`；`src/uniquant/hands/backtest/unified_engine.py:366-368` `shares<=0→100` + `except(...): shares=100` | ✅ 仓位计算失败 → **硬开 1 手**，非拒单 |
| 质量门"缺数据即满分" | `src/uniquant/signal/arbitrator.py:175` `oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)`，且只拦 `sig.action == "SELL"` 不拦 BUY | ✅ 缺数据默认 R²=1.0；买入侧（最需把关）完全不设防 |
| fail-open 系"被钉死的正确行为" | `tests/signal/test_arbitrator.py:170` `test_sizer_exception_falls_back_to_default_shares` **断言 `signals[0].shares == 100`** | ✅ 不是覆盖率漏洞，而是**伪回归**——绿色测试把 bug 钉成正确语义 |
| 评审自身行号漂移 | 评审附录二自纠 4 处（如 `:400-403`→`:406`） | ✅ 连评审也需回代码二次校准；行为断言不变 |

**关键观察**：`run_n2n_verification.py`（产出"PASS"验收、喂给 4.75/5 的端到端脚本）6 轨验证的全是 **happy path**——Track 2 用人为构造的干净冲突断言 Sell-Priority、Track 6 断言缺数据抛 `FileNotFoundError`——但全文 grep **无一处**触及 `sized_shares`/`shares=100`/质量门 `OOS R²`。它证明了"机器组装正确"，从未证明"机器在坏输入下 fail-closed"。

---

## 3. 历史对照：11-24 的每条失败都不是新的

把 11-24 的失败模式逐一回溯到 2026-05~07 红蓝语料，**每一条都有在库先例**：

| 11-24 的失败 | 在库先例（更早） | 距今 |
|---|---|---|
| 虚构代码引用（报告 09） | `docs/archive/REVIEW3_FINAL_VERIFICATION.md:48,54`——Review2 对 Performance 文档 **60% 误报率，含虚构引用**（"line 35 不存在""UNIQUANT_DE_WORKERS 不存在"），裁决"该 Review2 不可信" | **~6 个月** |
| "全绿 / 0 CRITICAL"从没真跑 | `AGENTS_CHANGELOG_ROUNDS.md:158`（第十二轮）——独立复查发现第十、十一轮远程 CI **双双失败**，"通过所有质量门禁"系假 | 第 10–12 轮 |
| 聚合数字 vs 源报告失实 | `docs/reanalysis/Z_redblue_comprehensive_report_20260710.md`——UI `except Exception:` **"声称 2 / 实际 17"（8.5× 低估）**、死代码 LOC 漂移 | 2026-07 |
| 循环自证 | 已是**命名教训**："依赖代码审计，而非审计报告""交叉引用防信息扭曲" | 持续 |
| 门禁 fail-open / 伪造输入 | 第一轮 P0-1"四阶门禁诚实化"删除"捷径伪造"→`TIER_UNRATED`；第二十三轮"不伪造极值"——**Rule 4 就是为这场仗写的** | 第 1、23 轮 |
| 自评过松 / 定级漂移 | `docs/reanalysis/Z_remediation_worksheet_red_blue_analysis.md` 自评其元分析仅 **B（78/100）"可能仍有遗漏"** | 2026-07 |
| 零定量 / 停在"代码看着对" | 反复被"实际运行代码"推翻的纯静态分析（工作表元轮 1："静态分析需动态验证补充"） | 持续 |

**文档漂移**是**被记录最多的单一教训**：`docs/remediation/v6_legacy_root_cause_analysis.md` 遗留项 7 早已写明"doc LOC 硬编码、每次改码即漂移、**无 CI 门禁捕获**"；`docs/reanalysis/README.md` 干脆有一张**"已知失效口径"表**，并警告"已标记 FIXED 的项会静默回退、后来的 agent 会从过期报告里把已删死模块重新引进来"。11-24 报告 01 那句"第 25 轮已修复 freshness SLA"（实则不在运行时路径）正是这张表警告过的"假 FIXED"。

**语料自己记录的两个 meta 事实**：
- `REVIEW3_FINAL_VERIFICATION.md:113`——"**经过 2 轮审查仍遗漏 3 个 CRITICAL 级源码 bug**"（直接承认验证过程本身不可靠）。
- `Z_redblue_comprehensive_report_20260710.md` 结尾写"全部 349 项声明附 file:line 证据，**零幻觉承诺**"，而正文里就躺着那个 8.5× 低估——**自我声明的诚实标签在结构上无效**。

---

## 4. 现有机械门禁的覆盖面审计：缺口在哪

| 维度 | 机械执行？ | 工具 / 阈值 |
|---|---|---|
| ruff 干净 | ✅ | CI `ruff check src/uniquant/ tests/ scripts/`，0 findings |
| 测试通过 | ✅ | CI `pytest tests/ -q` |
| 覆盖率地板 | ✅ | CI `--cov-fail-under=84`（真实 CI 口径） |
| 结构化证据哈希账本 | ✅ | `evidence_manifest.py verify`（仅覆盖 `results/` + `tests/benchmark/`） |
| Rule 4 fail-closed（研究门禁代码） | ✅ | `research/gates/alpha_tier_engine.py` 缺输入→`TIER_UNRATED`（含单测） |
| pip-audit | ⚠️ 非阻断 | `security-audit.yml` 为 `continue-on-error` |
| perf smoke | ⚠️ 触发分支错 | `benchmark.yml` 触发 `develop/main`，当前 `master` 等于永不触发 |
| doc 路径存在性 | ⚠️ **休眠** | `.githooks/pre-commit`→`verify_doc_paths.py`，但 `core.hooksPath → ~/.codex/git-hooks`（目录不存在），且 CI 不跑；且它**主动剥掉 `:NN` 行号**、只验文件存在 |
| **分析报告的事实性/引用/数字** | ❌ **零执行** | 无任何机械门校验 `docs/analysis/**` 的 file:line 引用是否真实、计数是否吻合、聚合数是否对账 |

**结论**：仓库为"代码正确"织了密网（ruff/coverage/哈希账本/fail-closed 门禁），却让"驱动上实盘决策的叙述性报告"处于纯散文状态——**无引用校验、无数字对账、无独立验证方，还允许自评与循环背书**。11-24 的失败恰好全发生在这一层。

---

## 5. 最深的一课：验证栈是"真值盲"的通过/失败过滤器

把 §2 的三条证据叠起来：

- fail-open 不是覆盖率漏洞，而是**被绿色测试钉死的"正确行为"**（`test_sizer_exception_falls_back_to_default_shares`）。
- 仓库自己的端到端验收脚本**回避失败路径**，只测 happy path。
- 伪回归跨越**第 6、8、11 轮 + 11-24** 反复复发（第六轮命名并反转 4 例；第八轮"最重要一课：既有覆盖率测试用 `monkeypatch __file__` 把 bug ① 钉死为正确行为"；第十一轮"旧行为钉死测试未随后门拔除更新"）。

> **最深一课**：整个验证栈——pytest 通过、coverage 84%、N2N 六轨 PASS、ruff 干净——度量的全是"**是否运行 / 是否覆盖 / 是否组装**"，从不度量"**这是不是正确的行为**"或"**这是不是真的**"。伪回归之所以反复复发，是因为这套过滤器对它**结构性失明**：一个把 bug 钉成正确的测试，在所有门禁里都是绿色的。

而缺的这个维度，恰恰是 CLAUDE.md 里**机械执行最弱**的部分：rule 3（不声称未验证结果）与 rule 4（不得伪造输入满足门禁）只保护 `results/` 的结构化工件哈希，对 `docs/analysis/**` 的叙述性声明零执行。

---

## 6. harness 处方（按杠杆 ÷ 成本排序）

历史对照把优先级收敛为一句话：**把语料已验证有效的两样东西机械化——独立证据团出包、数字与引用从当前树重算。**

### P0-A · 把"伪回归"从纪律变成机械门
仓库已会**问**"既有测试是把 bug 钉住了，还是当成了正确行为"，但这只在有人类驱动时发生。机械化：
- 对每条安全关键语义（fail-closed、拒单、熔断、限仓）补**反向断言**测试：坏输入 → **不产出可执行订单 / 产出 `TIER_UNRATED`**。先给 `arbitrator.py:406`、`unified_engine.py:366-368` 补，并把 `test_sizer_exception_falls_back_to_default_shares` **反转为断言拒单**（第六轮反转伪回归的标准动作）。
- 加 CI grep/ruff 守卫：禁止在 sizer/matching 的 `except` 分支给 `shares` 赋**正的魔法常数**。

### P0-B · 叙述性报告的事实性门禁（封虚构引用 + 假 FIXED）
升级 `verify_doc_paths.py` 并**先激活 hook**（指回 `.githooks`、挂进 CI）：
- **引用级校验**：解析 `docs/**/*.md` 的 `file.py:NN-MM`，回源码确认区间存在且含声称符号（能当场抓住报告 09 的虚构代码）。
- **数字对账**：报告写"XX 文件 / YY 行"，用 `find/wc` 实测比对（专家评审即如此抓到"data 40 文件被写成 20 文件"）。
- **聚合数由脚本从明细重算**，禁止人工从子报告转抄（8.5× 低估、80 文件低估皆是 roll-up 算术漂移）。

### P0-C · 禁止自评 + 禁止循环背书（最高杠杆）
- **自评分级不作数**：任何"评级 / 验收 / 健康度"结论必须来自**未参与撰写、且只交换证据不交换观点**的独立验证方（红蓝对抗或另一组 subagent，rubric 相同、互不见对方结论），并产出一张**公开的 corrections 表**（语料证明多轮自纠 + 公开修正表有效）。
- **禁锚同源**：报告不得把可信度锚定在另一份同源自产报告上（"98.9%"正是此病）。交叉验证必须指向**代码/数据**，不指向"另一份自产报告"。

### P1-D · 补齐 rule 3/4 的"报告层"执行
把证据链账本（现仅覆盖 `results/` + `tests/benchmark/`）扩展一个**"声明账本"**：每份 analysis 报告登记其可核查声明（file:line、计数、阈值），`verify` 时逐条回测。

### P1-E · 端到端风险链一次性串验
`run_n2n_verification.py` 加一条 Track：注入"PositionSizer 抛异常 + 合规引擎缺席"的复合故障，断言一笔交易不会带杠杆/满仓/fail-open 地落到下单或展示。（专家评审底线第 3 条：signal→sizer→合规→UI 各报告各审一段，没人串起来验过。）

### P1-F · 把已休眠的机械门唤醒
`pre-commit` hook 休眠、`security-audit.yml` 非阻断、`benchmark.yml` 触发分支错、`verify_doc_paths.py` 不在 CI——**先让已有的门真正通电**，比新增门性价比更高。

### 操作级教训（来自语料"什么让验证失效"的复盘）
1. **验证"问题描述"≠验证"修复方案"**：工作表实测描述准确率 ~90%，**修复方案仅 ~70%**。→ "整改完成"的验收必须独立复核**修复方案本身**。
2. **静态推理必须用执行补**：读代码的结论常被"一跑就翻"。→ 门禁优先"跑出来看"（IC/PBO/Sharpe/延迟实测值）。
3. **信原始源，不信摘要的摘要**：信息"在传递中"丢失是聚合层失实根因。

---

## 7. 收口

这个仓库最了不起的地方，是它诚实地记录了自己反复失败的全过程；最危险的地方，是它把这些失败诊断得清清楚楚、命了名（"伪回归""循环自证""已知失效口径"）、开了方，却把它们关在散文和可选提示词里——**从没让它们变成"不过就 red"的机械门，也从没把代码轮磨出来的红蓝纪律搬到分析报告这条更高风险的产线上。**

唯一的解药语料也已给出并验证过：**独立的、只认证据的第三方核查**——11-24 唯一抓住问题的正是它。把这件事变成通电的门，而不是靠某次恰好有人召集了专家团。

---

*本文仅读取与分析，未修改任何源码。所有 file:line 引用均在 2026-11-24 当前工作树用 `sed/grep` 实测。*