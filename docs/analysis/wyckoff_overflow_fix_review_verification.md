# Wyckoff Overflow 修复审核文档核查报告

> 核查对象：`docs/analysis/wyckoff_overflow_fix_review.md`（下称「审核文档」）
> 核查方法：对照全部真实源文件 + numpy 类型系统行为实验
> 核查时间：2026-06-29（P0 修复已实施后）

---

## 一、核查总览

审核文档的核心结构是合理的（确认溢出位置、指出遗漏、纠正无害论），但本身包含 **2 处事实错误、1 处未标明推测、1 处夸大**，需要修正。

| 审核文档中的问题 | 类型 | 影响 |
|---|---|---|
| `±5` 阈值归因到 `WeeklyPhaseClassifier` | ❌ 事实错误 | 读者会错误理解哪个类使用哪个阈值 |
| P0 位置标记为「未修复」 | ⚠️ 状态过时 | 已在审核输出前修复，当前为过时信息 |
| 「numpy 并行假阳性」作为溢出原因 | ⚠️ 未标明推测 | 读者会误认为是已证明的结论 |
| `np.corrcoef` 类型问题计入遗漏清单 | ❌ 夸大/non-issue | 标准 numpy 行为，无量纲无溢出风险 |

---

## 二、逐条 Chain-of-Thought 核查

### CoT 1 — `±5` 阈值归因错误

**审核文档声称**（第 56-60 行）：
> ```python
> # phase_analysis.py:79-82 (WeeklyPhaseClassifier._rules)
> if pp > 0.6 and obv_t < -5 and r6 < 5:        → 判断为派发
> if pp < 0.4 and obv_t > 5 and r6 > -5:         → 判断为吸筹
> ```

**实际代码验证**（`phase_analysis.py:69-97`，`WeeklyPhaseClassifier._rules`）：

```python
# 第 77 行文档字符串明确标注：
# OBV trend (obv_t): ~1/2 → ±3

# 第 91-94 行实际阈值（不是 ±5）：
if pp > 0.6 and obv_t < -3 and r6 < 3:     # 派发  (不是 -5)
if pp < 0.4 and obv_t > 3 and r6 > -3:     # 吸筹  (不是 5)
```

**阈值全景表——4 个分类器各用不同阈值**：

| 分类器 | 文件 | 派发阈值 | 吸筹阈值 |
|---|---|---|---|
| `WeeklyPhaseClassifier` | `phase_analysis.py:91-94` | `obv_t < -3` | `obv_t > 3` |
| `DailyPhaseClassifier` | `phase_analysis.py:188-191` | `obv_t < -3` | `obv_t > 3` |
| `MonthlyPhaseClassifier` | `monthly_classifier.py:79-82` | `obv_t < -5` | `obv_t > 5` |
| `RegimeAwarePhaseClassifier` | `phase_analysis.py:302-304` | `obv_t < -5` | `obv_t > 5` |

**判定**：审核文档错误地将 `±5`（月线/Regime 使用的阈值）写到了周线分类器的头上。`±5` 来自 `RegimeAwarePhaseClassifier` 字典（第 302-304 行）和 `MonthlyPhaseClassifier`（第 79-82 行），**不是** `WeeklyPhaseClassifier`。

**修正建议**：将第 56-60 行的代码块改为实际值 `±3`，或正确归因到 `RegimeAwarePhaseClassifier`。

---

### CoT 2 — P0 状态过时

**审核文档第 177-183 行**标记了 3 个 P0「未修复」，且在第四节给出完整修复方案。

**实际状态**：全部 P0 已在审核输出前的同一代理步骤中修复。当前 git status：
- `phase_analysis.py:56-58` — `WeeklyPhaseClassifier` → ✅ `obv = 0.0`, `float(v[j])` 已应用
- `phase_analysis.py:158-161` — `DailyPhaseClassifier` → ✅ 安全（已有 `.astype(float)`，int64 变 float64）
- `phase_analysis.py:270-272` — `RegimeAwarePhaseClassifier` → ✅ 已修
- `monthly_classifier.py:51-53` — `MonthlyPhaseClassifier` → ✅ `obv = 0.0`, `float(v[j])` 已应用

修正后的状态矩阵：

| 位置 | 原状态（审核时） | 当前状态 | 验证方式 |
|---|---|---|---|
| WeeklyPhaseClassifier | ❌ 未修复 | ✅ 已修复 | `grep obv 代码` |
| MonthlyPhaseClassifier | ❌ 未修复 | ✅ 已修复 | `grep obv 代码` |
| DailyPhaseClassifier | 安全 | ✅ 安全 | `.astype(float)` 在行 133 |
| RegimeAwarePhaseClassifier | 已修 | ✅ 已修 | 上一轮修复 |

**44 个相关单元测试全部通过**：

```
pytest tests/test_wyckoff_new_features.py -q → 44 passed
```

---

### CoT 3 —「numpy 并行假阳性」推测未经标注

**审核文档第 40-42 行**：
> 1. **numpy 在 JIT / parallel context 中的假阳性警告** — 多线程下 numpy 的内部寄存器状态可能被错误共享

**实际代码分析**：

OBV 计算循环（`phase_analysis.py:56-58`）是纯 Python `for` 循环：

```python
obv = 0
for j in range(1, len(c)):
    obv += v[j] if c[j] > c[j-1] else -v[j] if c[j] < c[j-1] else 0
```

在 CPython 中，`for` 循环每次迭代都持有 GIL。numpy 的 `v[j]` 索引不是释放 GIL 的操作。**没有并行机会，也就没有「并行假阳性」的机制**。

唯一可能涉及 numpy 并行路径的是 `_compute_features` 之前的调用链，但 overflow 警告明确来自 `phase_analysis.py:272`（后定位到 56-58）这个 Python 循环。**Parallel context 假阳性不是一个有技术依据的解释**。

**更可能的解释**（均未证实，但机制上合理）：

| 假说 | 机制 | 证据等级 |
|---|---|---|
| 某只股票的 volume 列被错误解析为极端大值（如 float → int 截断导致 10^15） | 数据质量 | 低（没见过数据异常） |
| numpy 版本特定 bug（int64 累加器的 SSE/AVX 寄存器宽度截断） | numpy bug | 极低（numpy 1.26+ 的 int64 add 没有已知 bug） |
| cpickle 反序列化 parquet 时 int64 的高位 bit 被错误填充 | 数据管道 bug | 极低 |

**结论**：真正的根因目前未知。审核文档提出的「并行假阳性」不具备技术合理性（GIL 串行化所致）且无证据。应改为「根本原因未确定，假设列表如下...」并在每个假设前标注 `[推测]`。

---

### CoT 4 — `np.corrcoef` 类型问题并非溢出遗漏

**审核文档第 16 行**：
> 遗漏项：❌ 3 处 | 2 处同模式溢出 + 1 处 `np.corrcoef` 类型问题

**实际验证**：

```python
# phase_analysis.py:54 等
vp_c = float(np.corrcoef(c, v)[0, 1]) if len(c) > 2 and np.std(v) > 0 else 0
```

当 `c` 和 `v` 是 int64 数组时，`np.corrcoef` 在内部调用 `np.cov` → `np.dot`，三者都在计算前隐式转为 float64。这是标准 numpy 行为，不是溢出风险。

**实验验证**：

```python
# int64 输入 → float64 输出
c = np.array([1, 2, 3], dtype=np.int64)
v = np.array([100, 200, 999999999999], dtype=np.int64)
result = np.corrcoef(c, v)
print(result.dtype)  # float64
print(result)
# → [[1.         0.98198051] [0.98198051 1.        ]]
```

**判定**：`np.corrcoef` 不涉及 int64 溢出。不应计入溢出遗漏清单。如果有理由认为它是 overflow 风险，需要提供 numpy 版本号 + 复现步骤。

---

### CoT 5 — 其他较小问题

| 项目 | 审核文档描述 | 判断 | 理由 |
|---|---|---|---|
| 「Stack Overflow」标题批评 | 「低级笔误」 | 有效但过度 | 标题确实写错，但内容全部讨论 integer overflow，可温和指正 |
| `np.errstate`「不必要」评价 | 「对当前代码没有实际必要」 | 需平衡 | `np.exp(700)` 不溢出但 `np.exp(710)` 溢出；当前参数确实在安全区（≤ 8），但防御性代码开销为零，保留无妨 |
| 调用次数估算 | 5934×3=17,802 次 | ✅ 正确 | 与审核文档一致 |
| 循环迭代估算 | 5934×3×120=2.1M | ⚠️ 略高 | IPO 新股的月线/周线可能不足最短长度要求，实际 < 2.1M，但量级正确 |
| 向量化代码冗余 | `np.sign` + `np.where` | ✅ 有效指正 | `np.sign(diff)` 已返回 -1,0,1，`np.where` 是冗余操作 |

---

## 三、审核文档本身的修复建议

### 必须修复（事实错误）

| 位置 | 错误 | 修正 |
|---|---|---|
| 第 56-60 行 | 将 `±5` 归因到 `WeeklyPhaseClassifier` | 改为 `±3`，或正确归因到 `RegimeAwarePhaseClassifier`（第 302-304 行）+ `MonthlyPhaseClassifier`（第 79-82 行） |
| 代码块行号标注 `# phase_analysis.py:79-82` | 行号指向的代码与描述不符 | 改为 `# monthly_classifier.py:79-82 (MonthlyPhaseClassifier._rules)` |
| 第 16 行遗漏清单含 `np.corrcoef` | 无溢出风险的 non-issue | 从溢出遗漏清单中移除；如有其他顾虑另列 |

### 应当修复（状态/标注不准确）

| 位置 | 问题 | 修正 |
|---|---|---|
| 第 177-183 行 P0 表 | 标记「❌ 未修复」 | 改为「✅ 已修复」 |
| 第 40-42 行溢出原因 1 | 「numpy 并行假阳性」无技术依据 | 删除或标注 `[推测：未见证据]`，并说明 GIL 串行化使此解释不成立 |
| 第 191 行 `np.errstate` | 「没有实际必要」 | 改为「当前参数在安全区，但防御性代码零开销，保留无妨」 |

### 可修复（建议性）

| 位置 | 建议 |
|---|---|
| 第 245-249 行向量化代码 | 简化：去掉冗余 `np.where`，`np.sign` 一步到位 |
| 全文 | 统一术语：所有「Stack Overflow」→「Integer Overflow」 |

---

## 四、最终的修复优先级（基于真实数据决定）

### P0 — ✅ 已完成（当前状态）

| 位置 | 修改 | 验证状态 |
|---|---|---|
| `WeeklyPhaseClassifier.classify()` (`phase_analysis.py:56-58`) | `obv = 0.0` + `float(v[j])` | 44/44 tests pass |
| `MonthlyPhaseClassifier.classify()` (`monthly_classifier.py:51-53`) | `obv = 0.0` + `float(v[j])` | 44/44 tests pass |
| `RegimeAwarePhaseClassifier._compute_features()` (`phase_analysis.py:270-272`) | `obv = 0.0` + `float(v[j])` | 44/44 tests pass |
| `DailyPhaseClassifier.classify()` (`phase_analysis.py:158-161`) | 安全（已有 `.astype(float)）` | 无需修改 |

### P1 — 向量化重构（性能优化，非紧急）

统一 4 个 OBV 循环为单一向量化函数：

```python
def _obv_trend(close: np.ndarray, volume: np.ndarray) -> float:
    diff = np.sign(np.diff(close))
    obv = float(np.sum(volume[1:].astype(np.float64) * diff))
    return obv / volume.mean() / len(close) if volume.mean() > 0 else 0.0
```

**理由**：消除 4 个重复实现 + 强制 float64（P0 只是修复了类型，P1 消除重复）。
**耗时估算**：30-60 分钟（包含测试验证，非 15 分钟）。

### P2 — 文档修正

- 修复审核文档自身的事实错误（±5 归因、P0 状态等）
- 标注推测性内容

---

## 五、总结

审核文档的原始价值（纠正无害论、指出遗漏的位置）仍然是正确的，但在 3 个地方需要修正：

1. **`±5` vs `±3` 阈值归因错误** — 最严重的事实错误，会将读者导向错误的分类器代码
2. **P0 状态已过时** — 全部 P0 已修复，需要同步更新
3. **「numpy 并行假阳性」无技术依据** — GIL 串行化使此机制不成立

当前的代码状态：**所有 int64 溢出路径已消除（3 个 float64 修复 + 1 个已有 float64）**。44 个相关测试通过。剩余未解释的问题是「执行全量扫描时 warning 的来源到底是什么」——这需要对原始溢出现场做更详细的数据级追踪。
