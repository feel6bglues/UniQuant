# Phase 5 — Wyckoff Overflow 修复任务清单

> 判定基准：代码 `src/uniquant/brain/wyckoff/` + `src/uniquant/signal/adapters.py` + 5934 只 A 股数据
> 判定原则：Need-to-Do，不做无益优化
> 日期：2026-06-29

---

## 状态总结（任务 0 — 已完成清单）

以下工作已完成并通过验证，不再出现在任务清单中：

| 完成项 | 验证方式 | 工作量 |
|---|---|---|
| `RegimeAwarePhaseClassifier._compute_features()` — `obv = 0.0` + `float(v[j])` | 44/44 tests | 1 min |
| `WeeklyPhaseClassifier.classify()` — `obv = 0.0` + `float(v[j])` | 44/44 tests | 1 min |
| `MonthlyPhaseClassifier.classify()` — `obv = 0.0` + `float(v[j])` | 44/44 tests | 1 min |
| `DailyPhaseClassifier.classify()` — 确认安全（已有 float64 `volume`） | 代码审查 | 1 min |
| `np.errstate(over='ignore')` 防御性 guard × 3 | 44/44 tests | 2 min |
| Alpha 300/500 symlink 修正 | 5-ticker pipeline 无 engine 失败 | 1 min |

**当前 13 个文件有未提交改动**（非本次 session 引入，为 Phase 5 Wyckoff 集成未提交的 pre-existing 改动 + 本次修复）。

---

## 任务 1 — 全量扫描验证（P0）

> 目的：在真实 5934 只股票上确认 overflow 修复有效，获取 signal 分布基线

**为什么是 P0**：所有修复必须在全量数据上验证后才能确认解决。未完成全量扫描 => 我们对溢出是否真的已消除、信号分布是否合理均无数据支撑。

### 子任务 1.1 — 检查全量扫描入口

```bash
grep -n "run_batch\|pipeline_full_scan\|run_research_pipeline" scripts/ -r
```

**预期**：找到可执行的全量扫描脚本或 `PipelineService.run_batch()` 调用方式。

### 子任务 1.2 — 设置 overflow 警告捕获

```python
import warnings
warnings.filterwarnings('error', category=RuntimeWarning, message='.*overflow.*')
```

在扫描入口处加入此 guard，一旦任何 overflow 重新出现立即失败（fail-fast），避免无意义运行。

### 子任务 1.3 — 执行全量扫描

```bash
# 预计 25-30 分钟（5934 stocks × 3 timeframes × ~120 rows each）
python3 scripts/pipeline_full_scan.py 2>&1 | tee logs/full_scan_$(date +%Y%m%d_%H%M).log
```

**验证标准**：
- 0 个 overflow 警告（或 fail-fast 未触发）
- `report.json` 生成，含 signal 类型、数量、confidence 分布
- 0 个 engine 级异常

**估计耗时**：30 分钟（执行）+ 5 分钟（审查 report）
**依赖**：无（所有 fix 已完成）

---

## 任务 2 — FROZEN Regime 诊断（P1）

> 目的：确定全量扫描后 signal 为零是否由 FROZEN regime 导致

**为什么是 P1**：在全量扫描之前无法判断 FROZEN 误报还是正确。如果扫描后 signal 分布合理，则 FROZEN 不是问题（数据恰好在冷冻期）。只有当扫描报告显示系统性的 zero signal 时才升级为 P0。

### 子任务 2.1 — 分析扫描报告的 signal 统计

检查 `report.json` 中每个 ticker 的 signal 计数。如果部分 ticker 有信号、部分没有，说明系统工作正常（FROZEN 只是对某些股票/时期正确标记）。

### 子任务 2.2 — 如果系统性零信号

```python
# 查询 regime detector 的 entropy 判定
regime = RegimeDetector().classify(df)
```

检查是否所有股票的 entropy 都低于 FROZEN 阈值。如果是，阈值可能偏小（`ENTROPY_PERCENTILE_THRESHOLD = 0.2`）。调大一个数量级测试。

### 子任务 2.3 — 修正阈值（如果确认误报）

```python
# src/uniquant/shared/constants/technical.py:195
ENTROPY_PERCENTILE_THRESHOLD = 0.2  # → 0.02? 或从 config 读取
```

**验证标准**：扫描报告有 >0 个非 HOLD 信号
**估计耗时**：15-30 分钟
**依赖**：任务 1 必须完成（需要 `report.json`）

---

## 任务 3 — OBV 向量化重构成公共函数（P1）

> 目的：消除 4 个重复 Python 循环实现，提升性能 10-50x，强制 float64 类型安全

**为什么是 P1 不是 P0**：当前 float64 修复已经正确消除了 overflow 风险，向量化不改变正确性。但 reduce 4 份重复代码 = 降低未来维护遗漏风险。

### 子任务 3.1 — 在 `phase_analysis.py` 中定义公共函数

```python
# 添加在文件顶部
def _obv_trend(close: np.ndarray, volume: np.ndarray) -> float:
    directions = np.sign(np.diff(close))
    obv = float(np.sum(volume[1:].astype(np.float64) * directions))
    return obv / volume.mean() / len(close) if volume.mean() > 0 else 0.0
```

### 子任务 3.2 — 替换 4 个调用者

| 位置 | 替换前 | 替换后 |
|---|---|---|
| `phase_analysis.py` WeeklyPhaseClassifier (L56-59) | 4 行 Python 循环 | `_obv_trend(c, v)` |
| `phase_analysis.py` DailyPhaseClassifier (L158-161) | 4 行 Python 循环 | `_obv_trend(close, volume)` |
| `phase_analysis.py` RegimeAwarePhaseClassifier (L270-273) | 4 行 Python 循环 | `_obv_trend(c, v)` |
| `monthly_classifier.py` MonthlyPhaseClassifier (L51-54) | 4 行 Python 循环 | 导入 + `_obv_trend(c, v)` |

### 子任务 3.3 — 数值一致性验证

```python
# 对比旧实现和新实现对同只股票的输出
old_obv_t = 0.0
for j in range(1, len(c)):
    old_obv_t += float(v[j]) if c[j] > c[j-1] else -float(v[j]) if c[j] < c[j-1] else 0

new_obv_t = _obv_trend(c, v)

assert abs(old_obv_t - new_obv_t) < 1e-10
```

### 子任务 3.4 — 44 个测试通过验证

```bash
pytest tests/test_wyckoff_new_features.py -q
```

**验证标准**：
- 44/44 测试通过
- 数值一致性断言通过
- `timeit` 显示向量化版本比循环快 10x+
- `ruff check src/uniquant/brain/wyckoff/ --quiet` 无新 lint 错误

**估计耗时**：30 分钟（含测试 + 审查）
**依赖**：无（代码改动独立）

---

## 任务 4 — 溢出根因数据追溯（P1）

> 目的：回答「最大 OBV 只有 int64 上限的 0.000002%，溢出从哪里来？」

**为什么不是 P0**：overflow 已被 float64 修复消除，根因未明不影响正确性。但给未来维护留下隐患——如果不知道真正原因，下次类似警告可能被忽视。

### 子任务 4.1 — 在扫描日志中捕获原始溢出位置

在扫描阶段加入 catch_warnings，打印触发 overflow 的 ticker + 数据范围：

```python
import warnings
import traceback

def warn_with_context(message, category, filename, lineno, file=None, line=None):
    if 'overflow' in str(message):
        print(f"[OVERFLOW] {filename}:{lineno} — {message}")
        # 打印当前正在处理的 ticker（从外层上下文获取）

warnings.showwarning = warn_with_context
```

### 子任务 4.2 — 检查触发位置的 OBV 中间值

如果定位到某只特定股票触发 overflow，提取其 volume 列检查最大值和离群值。

**验证标准**：确认根因（数据质量? numpy bug? 其他?）或确认无法复现（旧版本已修复）。
**估计耗时**：20 分钟（如果无法复现则 5 分钟确认后关闭）
**依赖**：任务 1 的全量扫描

---

## 任务 5 — 文档口径统一修正（P2）

> 目的：修复原始分析和审核文档中的事实错误

### 子任务 5.1 — 修正 `wyckoff_overflow_fix_analysis.md`

| 修正项 | 内容 |
|---|---|
| Step 6 标题 | `Stack Overflow` → `Integer Overflow` |
| Step 6 "溢出无害论" | 删除或标注 wraparound 对 `_rules()` 分类的影响 |
| Step 4 计算前提 | 标注实际数据上限 7.3 亿不是 100 亿 |
| 遗漏位置补充 | 标注 Weekly/Monthly 已修复 |
| P0 状态 | 标记已修复 |

### 子任务 5.2 — 修正 `wyckoff_overflow_fix_review.md`（本人已完成）

✅ 已在 2026-06-29 版本中修正：`±5` 归因、P0 状态、`np.errstate` 评价、推测标注。

### 子任务 5.3 — 在 `wyckoff_overflow_fix_analysis.md` 末尾追加「审核后修正记录」

列出审核发现的 2 处 P0 遗漏位置 + 自纠正的 2 处审核事实错误。

**估计耗时**：10 分钟
**依赖**：无

---

## 任务 6 — 死代码清理（P3）

> 清理 `_compute_features(self, df, period)` 的未使用 `period` 参数

**为什么是 P3**：不影响行为，不产生 bug。建议暂缓。

```python
# 改动内容
def _compute_features(self, df: pd.DataFrame) -> Dict:  # 去掉 period
```

改动涉及 4 个 `classify()` 方法内的调用处 + 1 个方法签名。

**估计耗时**：5 分钟
**依赖**：无
**建议**：等向量化重构（任务 3）一起做，避免两次打开文件

---

## 并行执行图

```
时间轴 →
─────────────────────────────────────────────────────────────
任务 1 (全量扫描)  ─────────────────  30m  (唯一占用 GPU/CPU)
                                        │
任务 3 (向量化)     ─────────────       │  (可并行于任务 1)
                                        │
任务 5 (文档修正)   ─────               │  (可并行于任务 1)
                                        │
任务 2 (FROZEN)     ─── 等待 report ────│──  等待任务 1 输出
                                        │
任务 4 (根因追溯)   ─── 等待 overflow ──│──  等待任务 1 输出
                                        │
任务 6 (死代码)     ─── 等待合并 ───────│──  建议等任务 3 合并
```

**并行执行方案**：
1. 启动任务 1（全量扫描）—— 主线程，约 30 分钟
2. 与任务 1 同时启动任务 3（向量化重构）—— 子线程，约 30 分钟，独立于数据
3. 与任务 1 同时启动任务 5（文档修正）—— 子线程，约 10 分钟
4. 任务 1 完成后启动任务 2（FROZEN 诊断）和任务 4（根因追溯）—— 需要 `report.json`
5. 任务 3 完成后启动任务 6（死代码清理）—— 合并到向量化重构的 PR 中

---

## Need-to-Do 判定理由

| 任务 | 标为 PX 的理由 |
|---|---|
| 1 — 全量扫描 | P0 — 没有全量验证就不知道 fix 是否真的解决了问题 |
| 2 — FROZEN 诊断 | P1 — 先看扫描结果，如果有信号则不是问题 |
| 3 — 向量化 | P1 — 性能优化，不改变正确性。消除重复降低维护成本 |
| 4 — 根因追溯 | P1 — overflow 已被消除，根因是知识问题不是 bug |
| 5 — 文档修正 | P2 — 不影响代码，影响团队的文档可信度 |
| 6 — 死代码清理 | P3 — API 清晰但不影响行为 |
