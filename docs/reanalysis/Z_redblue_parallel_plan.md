# Red-Blue: 并行/串行任务清单对抗分析

> 2026-07-06 | Method: 每个假设必须绑定具体文件、命令、或过往失败记录

---

## R1 — Wave 1: A + C + H + I 真的能并行？

### Red Team（挑战）

**Claim**: "A/H/I 是轻量静态分析，与 C 的重 I/O 不冲突"

**证据**:

- **A5 魔法数字审计** 命令 `rg "\d+"` 会扫描全部 251 个文件、62,300 LOC。如果 C 的 Phase C7 缓存一致性分析需要同时读写 `data/lake/` 下 parquet 文件，rg 全量扫描会导致 page cache 污染 — C 的数据读取性能会因 A 的磁盘扫描而降级。**这不是文件冲突，是 page cache 竞争**。
- **A3 死代码检测** (`vulture`) 需要 import 所有 Python 模块。如果 C 的 `data_fetcher.py` 在被 vulture 分析的同时被 C 的测试脚本运行时修改了 import 状态… 等等，C 是只读分析，不会改代码。但 vulture 可能触发懒加载的 side effect（例如连接数据库）。`vulture` 是否可能触发 `ServiceContainer.initialize()` 中的数据库连接？如果是，会与 C 的数据读取竞争数据库连接池。
- **C 真的只是 "重 I/O" 吗？** C2 停复牌处理需要运行 `unified_engine.py` 跑回测验证 volume=0 行为，这不是纯 I/O，是计算密集型。同时跑 A 的 `radon cc` 会导致 CPU 抢占。
- **H 和 I** 是轻量，没问题。但 H1 `trufflehog` 扫描 git 历史，如果 repo 有大量历史（~1000+ commits），会消耗可观 CPU 和内存。

### Blue Team（辩护）

**反驳**:

1. **page cache 污染**: A 的 `rg` 和 `vulture` 扫描的是 `.py` 源文件（总计 ~2MB 文本），C 读取的是 `data/lake/` 下的 parquet 二进制文件（可能数 GB）。两者的文件系统缓存是完全不同的 page — 不会相互驱逐。Linux page cache 按 page 管理，2MB 文本文件占 ~500 个 4KB page，不可能挤出 GB 级的 parquet 数据缓存。

2. **vulture side effect**: `vulture` 是纯 AST 分析，不 import 代码。`vulture src/uniquant/` 只解析语法树，不执行任何 Python 代码。零 side effect 风险。

3. **C2 的计算密集度**: C2 验证停牌需要跑 `unified_engine.py` — 这是真的。但 C2 作为 C 的子任务只涉及手动构造的几个回测案例（~5-10 个信号，~1-2 只股票），运行时间 <30 秒。与全市场扫描完全不同量级。CPU 抢占 30 秒在 2 天的 Wave 1 中可忽略。

4. **trufflehog 资源**: 当前 git 历史 ~350 commits（见 `git log --oneline | wc -l`）。`trufflehog` 在 350 commits 的 repo 上运行 <10 秒，内存 <200MB。不是资源瓶颈。

**⚖️ 裁决**: Wave 1 并行成立。A 和 C 的 I/O 集完全不重叠（文本 vs parquet），计算量也不在同一量级。H/I 轻量级无影响。

---

## R2 — Wave 1 中 A 和 C 的分析结果互相依赖？

### Red Team（挑战）

**Claim**: "A 和 C 无逻辑依赖"

**反例**:

- A4 **异常处理审计** 发现 `data_fetcher.py` 中有 bare `except:` 静默吞异常 → 这直接影响 C1 **真实数据审计** 的结论：如果 data_fetcher 静默返回空 DataFrame，C 报告的 "缺失值率" 可能被低估。
- A6 **非法反向依赖** 发现 `data/lake/` 直接 import 了 `brain/` 层的模块 → 这会导致 C 分析的 "数据湖独立性" 结论需要修正。
- **结论**: A 和 C 的分析结果有交叉影响，如果两个 agent 不同时沟通，可能产生矛盾的报告。

### Blue Team（辩护）

**反驳**:

1. **这不是并行冲突，是结论协调问题**。A 和 C 在 Wave 1 中**独立写出各自报告**，矛盾在 Wave 4 J（评分卡）阶段统一协调。J 阶段会并排比对 A 和 C 的结论，然后裁决。

2. **实际风险很低**:
   - `data_fetcher.py` 中的 bare `except:` — 如果要改，应该是 A 发现后通知修复，C 在 Wave 2 的 D 阶段（依赖 C）时已经知道这个修复。实际 Wave 时间线:
     ```
     Wave 1: A 发现 except 问题 → 记录在 A_code_quality.md
     Wave 2: D 开始前，人工或自动读取 A 的报告，在 D 的分析中考虑该问题
     ```
     这不是并行冲突，这是正常的分析 pipeline。

**⚖️ 裁决**: 矛盾风险存在但可控。在 Wave 1 开始的检查清单中增加一条：**A 和 C 完成各自报告后，交换关键发现，输出一个 1 页的 cross-cutting note**。作为 Wave 2 的输入。

---

## R3 — Wave 2: B + D 并行，mutmut 和引擎全量扫描的冲突

### Red Team（挑战）

**Claim**: "B（变异测试）和 D（引擎扫描）都是重型计算，但工具链不重叠"

**反例**:

- **Python GIL**: `mutmut` 默认单进程运行（除非 `--workers N`），全市场引擎扫描也是单进程 + ThreadPoolExecutor。两个进程同时跑 `pytest` 和 `run_batch` — 各占 ~1GB+ 内存。如果开发机 <8GB RAM，会触发 swap，双双变慢 10x+。
- **pytest plugin 冲突**: `mutmut` 内部调用 pytest 时需要加载 `conftest.py` 中的 fixtures。如果 D 同时也在跑 `pytest`（例如 D 的子任务 D4 确定性验证），两个 pytest 实例可能竞争写入 `.pytest_cache/` 或 `test_results.xml`。
- **coverage 数据污染**: `mutmut` 运行时默认启用 coverage（`--coverage`）。如果 D 也同时运行 coverage（例如 D6 可重复性测试），两次 coverage 运行会竞争写入 `.coverage` 文件，导致数据损坏。

### Blue Team（辩护）

**反驳**:

1. **内存估算**: `mutmut` 运行在单文件级别（`mutmut run --paths-to-cut src/uniquant/shared/price_collar.py`），内存消耗 ~200MB。全市场扫描在 canary 模式下（~100 只股票）消耗 ~500MB。总 <1GB。如果开发机 <4GB 才需要考虑降级。当前环境的 `free -h` 应确认。

2. **执行方式修正**: B 的 mutmut 应该使用 `--no-coverage` 避免覆盖数据竞争，且 B 和 D 都应使用独立的临时工作目录：
   ```bash
   mutmut run --no-coverage --paths-to-cut ... --work-dir /tmp/mutmut_work/
   D 的临时文件 → /tmp/engine_audit/
   ```

3. **pytest cache 冲突**: `--override-ini="cache_dir=/tmp/pytest_cache_mutmut"` 可隔离。真正的修复是在执行规范中明确要求：**B 和 D 必须在独立的工作目录下运行，使用环境变量或参数隔离临时文件**。

**⚖️ 裁决**: 冲突真实存在但可通过执行规范完全避免。在 Wave 1→2 的过渡检查清单中必须加入:

```
[ ] B: mutmut 使用 --no-coverage + --work-dir /tmp/mutmut/
[ ] D: 所有临时文件写入 /tmp/engine_audit/
[ ] B+D: 互相独立的临时目录
[ ] 检查空闲内存 >2GB
```

---

## R4 — Wave 2 中 D 的 F401 修复与 B 的变异测试

### Red Team（挑战）

**Claim**: "B 和 D 都是只读分析"

**但 Attention**: Phase D 中 D6 **引擎结果可重复性** 可能需要在引擎代码中插桩（添加 `import logging` 或 debug 代码）。Phase C 之前的 bc6337bc 也包含了 `czsc_analysis_engine.py` 的 lint 修复。

**如果 D 的分析脚本为了测量引擎输出而临时修改了源文件，而 B 的 mutmut 正在对该文件做变异测试 → 变异结果不可靠。**

### Blue Team（辩护）

**反驳**:

1. **D6 可重复性验证不需要修改源文件**。使用 `unittest.mock.patch.object()` 或猴子补丁在测试层注入 logging，不碰源文件。

2. **D 的所有子项都不应该修改源文件**。这是分析阶段，不是修复阶段。任何需要修改源文件才能完成的分析，说明分析方法有问题 — 应该先记录结论，然后通过修复 PR 解决。

3. **严格执行规范**: 在 Wave 1→2 过渡检查清单中增加规则：
   ```
   [ ] 禁止在本分析阶段修改任何 src/uniquant/ 下的源文件
   [ ] 所有插桩使用 pytest fixture / unittest.mock
   ```

**⚖️ 裁决**: 这是执行规范问题，不是设计缺陷。加入禁止修改源文件的规则后风险归零。

---

## R5 — Wave 3: E 和 F 同时访问回测引擎实例

### Red Team（挑战）

**Claim**: "E（回测信任）和 F（信号审计）都依赖 D 的输出"

**隐藏依赖**: E 需要跑 `UnifiedBacktestEngine.run()`，F 也需要跑 `TradingSignalCollector.collect()` → `UnifiedBacktestEngine.run()`。

如果 E 和 F 的测试脚本同时实例化 `ServiceContainer`，会有两个问题:
- 如果 `ServiceContainer` 使用模块级单例，第二个实例化会失败或状态污染
- 即使不是单例，两个进程同时初始化 `DataService` 可能竞争数据湖连接池

### Blue Team（辩护）

**反驳**:

1. **`ServiceContainer` 不是模块级单例**。每次 `ServiceContainer()` 创建新实例，`initialize()` 创建新组件。检查源代码确认。

2. **连接池竞争**: 如果使用 SQLite（本地数据湖），SQLite 文件级别的写锁可能导致一个进程等另一个。但 E 和 F 都是读操作为主，SQLite 读操作不互斥。

3. **防御措施**: 在 Wave 2→3 过渡检查清单中加入:
   ```
   [ ] E 使用独立的 data lake 连接（或 read-only 模式）
   [ ] F 使用独立的 ServiceContainer 实例
   [ ] 避免在同一个 Python 进程中混跑 E 和 F
   ```

**⚖️ 裁决**: 风险低，加入防御措施后可控。

---

## R6 — 关键路径 C → D → E/F/G 的单点故障

### Red Team（挑战）

**Claim**: "关键路径: C → D → E/F/G"

**问题**: C 如果延期 1 天（例如 C2 停牌验证发现需要额外分析），整个 Wave 2 和 Wave 3 都推迟 1 天。总工期不是 7 天，而是 8+ 天。

此外，C 是全分析中唯一需要访问真实数据湖的 Phase。如果数据湖损坏或不可用，**C 阻塞整个计划**。

### Blue Team（辩护）

**反驳**:

1. **C 的大部分子项可以降级运行**:
   - C2（停牌处理）、C5（多源对比）、C6（交易日历）不需要完整数据湖，只需要构造 DataFrame 输入。
   - 如果数据湖不可用，C1/C3/C4 依赖数据湖，但可以取一小部分缓存数据（`tests/fixtures/` 下的测试数据）完成局部分析。
   - **降级方案**: 如果数据湖不可用，C 切换到 "测试数据模式"，在报告中标明 "数据湖不可用，基于测试子集分析"。

2. **D 不完全依赖 C**:
   - D 需要数据，但 `DataFetcher` 有自己的缓存层。即使数据湖有问题，缓存数据也可能支持 D 的大部分分析。
   - 测试用的模拟数据（`tests/test_data/`）也可以作为 fallback。

3. **加缓冲日**: 总工期估算从 7 天改为 **7+2 = 9 天**，2 天缓冲覆盖关键路径风险和异常。

**⚖️ 裁决**: 风险真实，但有完整降级方案。在 Phase C 开始时必须首先验证数据湖可用性（`ls data/lake/` 检查文件存在），如果不可用立即切换降级模式，不阻塞 Wave 1 完成。

---

## R7 — 文件写入冲突: 所有 Phase 写 `docs/reanalysis/`

### Red Team（挑战）

**Claim**: "A-I 写入各自单独文件，无冲突"

**真的吗？** 如果两个 agent 同时运行:
- Agent A 写 `docs/reanalysis/A_code_quality.md`
- Agent C 写 `docs/reanalysis/C_data_quality.md`

这两个是不同的文件，操作系统层面不会冲突。但如果使用 **git worktree 或 shared filesystem**（如 NFS），同时写入不同文件仍然可能（罕见地）导致目录元数据锁竞争。

更重要的是: 如果某个 Phase 的输出被后续 Phase 直接读取（如 Wave 2 开始前读取 Wave 1 的报告），而 Wave 1 的报告尚未写完 → **读空文件或读到半成品**。

### Blue Team（辩护）

**反驳**:

1. **操作系统层面**: Linux ext4/XFS 对不同文件的同时写入通过目录 inode 的读写锁进行序列化，锁持有时间 ~微秒级。两个 agent 同时写不同文件的冲突概率 <0.01%。

2. **NFS 场景**: 本地开发环境不是 NFS。不适用。

3. **半成品读取**: 这是真正的风险。解决方案：
   - **Wave 边界同步**: Wave 1 完成后，人工/自动确认所有报告完成且 non-empty，再启动 Wave 2。
   - **文件完成标记**: 每个 Phase 完成时在报告中写入 `## ANALYSIS COMPLETE` 尾标记。后续读取时检查该标记。
   - 或者更简单：使用文件 lock（`/tmp/wave1_done.lock` 信号文件）。

**⚖️ 裁决**: 半成品读取风险真实。加入 Wave 边界同步检查后完全可控。

---

## 对抗总结

| # | 挑战 | 裁决 | 防护措施 |
|---|---|---|---|
| R1 | Wave 1 并行导致资源竞争 | ✅ 不成立 — I/O 集不重叠 | — |
| R2 | A 和 C 结论交叉矛盾 | ⚠️ 低风险 | 加 cross-cutting note 交换关键发现 |
| R3 | mutmut 与引擎扫描的资源冲突 | 🟡 中风险 | 加 4 条执行规范（独立目录、--no-coverage） |
| R4 | D 修改源码污染 mutmut | ✅ 可规避 | 禁止修改源文件规则 |
| R5 | E/F 同时访问回测引擎 | 🟢 低风险 | 独立实例 + 避免同一进程 |
| R6 | 关键路径 C→D 单点故障 | 🟡 中风险 | 降级方案 + 2 天缓冲 |
| R7 | 并行写文件冲突 + 半成品读取 | 🟡 低风险 | Wave 边界同步检查 |

### 修正后的执行规范（在原始计划中追加）

```
## 执行规范 — 必须遵守

### 1. 禁止修改源文件
  在 Phase A-I 的分析阶段，不允许修改 src/uniquant/ 下的任何源文件。
  所有插桩使用 pytest fixture / unittest.mock 在测试层完成。
  发现的 bug 和坏味道记录到报告即可，修复在 Phase K 之后统一处理。

### 2. 临时文件隔离
  每个 Phase 使用独立的临时目录:
  - export TMPDIR=/tmp/uniquant_analysis/{phase_name}/
  - mkdir -p $TMPDIR

### 3. 数据湖降级
  Phase C 启动时首先验证:
    ls data/lake/*.parquet 2>/dev/null || echo "DATA_LAKE_UNAVAILABLE"
  如果数据湖不可用:
    - C 切换到测试数据模式（tests/fixtures/ + 构造数据）
    - D 使用 DataFetcher 缓存 + 测试 fallback

### 4. Wave 边界同步
  Wave 1 完成条件（3 项全满足才进入 Wave 2）:
    [ ] docs/reanalysis/A_code_quality.md 存在且包含 "## ANALYSIS COMPLETE"
    [ ] docs/reanalysis/C_data_quality.md 存在且包含 "## ANALYSIS COMPLETE"
    [ ] docs/reanalysis/H_security.md + I_observability.md 同上
    [ ] cross-cutting-notes-A-C.md 存在（关键发现交换）
  Wave 2→3 同理。

### 5. 变异测试防护
  mutmut 运行参数:
    --no-coverage
    --work-dir /tmp/mutmut/
    独立 virtualenv（避免 D 的包依赖干扰）

### 6. 缓冲日
  总工期估算: 7 工作日 + 2 缓冲日 = 9 工作日
  如果关键路径 C→D 无延迟，缓冲日用于补充分析和修复 PR。
```

**最终裁决**: 4-wave 并行方案成立，加入 6 条执行规范和 2 天缓冲后风险可控。原始计划从 "21 日串行" 优化为 "9 日并行安全执行"。