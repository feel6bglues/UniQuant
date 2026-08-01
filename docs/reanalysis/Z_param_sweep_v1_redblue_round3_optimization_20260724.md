# Round 3: 参数扫描优化方案红蓝对抗 (2026-07-24)

**目标**: 对脚本 v1 的算法效率、参数空间设计、可扩展性进行对抗

---

## R3-01: 引擎冗余初始化 (Red) 🏆

**声明**: 每个参数组合×每个窗口都 `WyckoffEngine(range_threshold=rt, trend_threshold=tt)`

**问题**: `range_threshold` 和 `trend_threshold` 仅影响 `_compute_step1_context` 中的 `is_in_trading_range` (engine.py:336-338)。此值被用于:
1. `_detect_accumulation`: ctx["is_in_trading_range"] (line 364, 369)
2. `_detect_markup`: ctx["is_in_trading_range"] (line 386, 392)  
3. `_detect_distribution`: ctx["is_in_trading_range"] (line 405)
4. `_detect_markdown`: ctx["is_in_trading_range"] (line 416, 426)
5. `_step1_phase_determine`: 间接通过 detectors (line 493-500)
6. `_step0_bc_tr_scan`: `(tr_upper-tr_lower)/tr_lower <= self.range_threshold * 1.25` (line 293)

但 `_step0_bc_tr_scan` 中的 TR 界定也使用 `range_threshold`，而且影响 `rule0.tr_upper/tr_lower` 是否为 None，这又进一步影响 step1 和 step3。

**结论**: 简单重分类 post-hoc 会遗漏 Step 0 的 TR 界定变化。必须在引擎级完整重跑。

**但优化方案**: 缓存 Step 0 的中间结果（df, bc/sc 点位置），只重跑从 Step 0 开始的后续步骤。约节省 40% 计算。具体: Step 0 中 BC/SC 扫描 ($O(n)$) 与阈值无关，只有 TR 界定 (line 293) 相关。

**优化**: 将阈值变化分两层——Step 0 的 `range_threshold` 变化必须要，但可以缓存原始数据点位置；Step 1 的 threshold 变化只需要重跑 Step 1-5。

**严重性**: MEDIUM — 效率优化 (3x-5x 可能提升)

---

## R3-02: 无断点续传 (Red) 🏆

**声明**: `ProcessPoolExecutor` 运行全部 20 股票 × 6 窗口 × 12 参数组合 ≈ 1440 个任务

**问题**:
- 任何失败（OOM、磁盘满、断电）导致全部重跑
- 没有中间 checkpoint
- `as_completed` 实时写入但 Python 崩溃后全失

**严重性**: HIGH — 生产可用性。对于扩展到 100/500/5934 股票时，不可接受。

**修复**: 每个股票完成后写入独立 parquet，支持 `--resume` 跳过已完成的股票。

---

## R3-03: 参数空间维度不足 (Red) 🏆

**声明**: 扫描 3 个参数: window_size × range_threshold × trend_threshold

**遗漏参数**:
- `lookback_days` (engine.py:81, default=252) — 引擎截取数据长度的关键参数。若 lookback_days=120 且 window_size=252，引擎实际只看 120 天，浪费了更大窗口
- `weekly_lookback` / `monthly_lookback` — 多周期分析的影响
- STEP (window 滑动步长) — 步长影响窗口重叠度

**严重性**: HIGH — `lookback_days` 与 `window_size` 的交互是关键 confounding factor。若 `window_size=252` 但 `lookback_days=120`，实际前 132 天数据被引擎丢弃，分析只基于后 120 天。

**验证**: engine.py:185 `lookback = self.lookback_days` → frame = frame.tail(lookback) (line 191)

---

## R3-04: `golden_20` 代表性的质疑 (Red) 🏆

**声明**: 使用 golden_20 进行验证

**问题**: golden_20 选自不同行业的代表性股票，但 walk-forward 结论基于 3574 股票的全量扫描。20 只股票的抽样误差可能很大：
- 若 20 只中 1-2 只恰好呈现出 Spring 信号 → 比率被放大
- golden_20 的市值/流动性分布可能与全体 A 股不同

**验证**: 但 golden_20 是之前所有基线测试的标准集，保持一致性比随意扩大样本更重要。

**严重性**: MEDIUM — 可扩展到 golden_100 (仍 < 3min) 或 golden_500 (约 15min) 在可接受时间窗口内。

---

## R3-05: 使用完整 parquet 文件而非按需加载 (Red) 🏆

**声明**: 每个股票加载完整历史 (可能 10+ 年日线)

**问题**: 对 golden_20 × 12 参数组合，每只股票被完整加载 12 次（每个 worker 的每个参数组合首次进入 `analyze_stock`）。实际上数据可以一次性加载并广播到子进程。

**优化**: `ProcessPoolExecutor` 的 `initializer` 可以预加载数据，或使用 `multiprocessing.Manager` 共享字典。

**严重性**: LOW — 对 golden_20 影响微小 (总数据 < 50MB)，但对 full 5934 扫描时 (约 5GB parquet) 成为主要瓶颈。

---

## R3-06: 冷启动 (Blue) 💙

**声明**: 使用 `ProcessPoolExecutor` 进行并行

**论证**: 对于 CPU-bound 的 Wyckoff 引擎分析，多进程是最合适的选择。设置 `OMP_NUM_THREADS=1` 和 `MKL_NUM_THREADS=1` 正确避免了 BLAS 线程争抢。使用 `max_workers = cpu_count - 1` 留下了系统余量。

**严重性**: 无 — 正确

---

## R3-07: Parquet 输出格式 (Split) ⚖️

**红方**: Parquet 是二进制格式，不利于人类快速查验。应该同时输出 CSV 或 JSON 报告。

**蓝方**: Parquet 是 pandas 原生格式，保留数据类型 (float 精度、字符串 vs 分类)，大小仅为 CSV 的 1/5。下游分析用 Python/pandas 读取，不需要人类可读。

**折中**: 输出 parquet (给下游分析) + 简短 JSON 汇总报告 (给人看)。参考 `walk_forward_definitive_report.json` 的格式。

---

## R3-08: 无自动参数排名 (Red) 🏆

**声明**: 脚本打印所有参数组合的结果，但无自动排名

**问题**: 18 个参数组合 × 10+ 指标 = 180+ 个数值点。人类无法直观判断"哪个参数组合最好"。需要:
1. 定义单一目标函数 (如: buy_n 的 fwd_20d 夏普比)
2. 按目标函数排序
3. 标注"最优"和"runner-up"参数

**严重性**: MEDIUM — 可用性

---

## R3-09: 未能利用 walk-forward 的滚动窗口特性 (Red) 🏆

**声明**: 每个窗口独立分析，不传递状态

**问题**: Wyckoff 分析本质上是序列化的——今天的 phase 应该基于昨天的 phase 推断。但 walk-forward 滚动窗口（步长 20 天）天然有重叠，当前脚本将每个窗口视为独立样本，丢失了时间序列信息。

**优化**: 对同一参数组合，相邻窗口的 phase 变化轨迹本身是一个重要分析维度: "ACCUMULATION→MARKUP→MARKUP→DISTRIBUTION" 的序列比孤立每个窗口的 phase 更有意义。

**严重性**: MEDIUM — 信号序列一致性是 Wyckoff 方法的核心前提

---

## R3-10: 使用 numpy 自计算 ATR 而非直接使用引擎现有实现 (Split) ⚖️

**红方**: 脚本没有使用引擎做任何 fwd 收益分析以外的计算，而是完全信任引擎输出。这导致无法在引擎失败时做任何 fallback。

**蓝方**: 脚本的定位就是验证引擎行为，不应重复实现引擎逻辑。使用引擎输出是正确的方法。

**折中**: 添加一个"轻量级"的快速路径——对仅参数阈值扫描的场景，可以提取引擎的中间 ctx 并只重分类 `is_in_trading_range`，但需要 `_step0_bc_tr_scan` 也支持快速重评估。

---

## 裁决

| ID | 判定 | 严重性 | 影响 |
|----|------|--------|------|
| R3-01 | **Red** 🏆 | MED | 冗余初始化 (可优化 3-5x) |
| R3-02 | **Red** 🏆 | HIGH | 无断点续传 → 全量重跑风险 |
| R3-03 | **Red** 🏆 | HIGH | 遗漏 `lookback_days` 与 window_size 的交互 |
| R3-04 | **Red** 🏆 | MED | golden_20 的代表性 |
| R3-05 | **Red** 🏆 | LOW | 数据加载冗余 |
| R3-06 | **Blue** 💙 | — | 多进程选择正确 |
| R3-07 | **Split** ⚖️ | LOW | 输出格式选择 |
| R3-08 | **Red** 🏆 | MED | 无自动参数排名 |
| R3-09 | **Red** 🏆 | MED | 丢失时间序列信息 |
| R3-10 | **Split** ⚖️ | LOW | 引擎依赖度 |

**Round 3 总计**: Red 7 🏆 / Blue 1 💙 / Split 2 ⚖️  
**必须修复**: R3-02(断点续传), R3-03(lookback_days), R3-08(参数排名)

---

## Round 3 对优化方案的建议

1. **引擎缓存层**: 将 Step 0 的 BC/SC 扫描结果缓存（按股票×窗口），后续只重跑 TR 界定 + Step 1-5
2. **外部化参数**: 添加 `--lookback-days 252` CLI 参数，与 window_size 正交
3. **断点续传**: 每个股票完成后写 `.done` 标记文件，重启时自动跳过
4. **参数排名**: 在报告中添加按"信号效费比"排名的参数组合表格
5. **时间序列分析**: 添加 phase 转移矩阵（`P(MARKUP→ACCUMULATION)` 等）的统计
6. **自动扩展**: golden_20 → golden_100 → golden_500 的分阶段运行脚本
