# Round 1: 参数扫描脚本 v1 红蓝对抗 (2026-07-24)

**目标**: 对 `scripts/param_sweep_v1.py` 进行设计级红蓝对抗，暴露正确性、效率、可维护性问题

---

## R1-01: `WyckoffReport.trading_plan` 类型不匹配 (Red) 🏆

**声明**: 脚本从 `rep.trading_plan.direction` 读取方向字段

**证据**: 
- `WyckoffReport` 的 `trading_plan` 字段类型是 `TradingPlan` (model.py:116-133)
- `TradingPlan.direction` 注释自称支持 `"long"` / `"empty"` (model.py:119)
- 但引擎 `_step5_trading_plan` 实际写入的值是 `"做多"`, `"买入"`, `"持有"`, `"空仓观望"` (engine.py:996-1080)
- 脚本中 `tp_direction == "买入"` 做 buy/nobuy 对比 (line 156) — 漏掉了 `"做多"` 和 `"持有"`

**严重性**: HIGH — buy spread 统计结果被系统性低估 2-3 倍。walk-forward"唯一有效信号"的结论会因为漏掉半数以上买入信号而偏误。

**验证**: 
```
direction 实际分布: "做多"(多名) / "买入"(少名) / "持有"(多名) / "空仓观望"(多数)
脚本只捕获: "买入" (少数场景: markup+Test/Shakeout)
```

---

## R1-02: Forward 收益为 0.0 时毒化均值 (Red) 🏆

**声明**: `fwd_*` 在超出数据范围时设为 0.0

**问题**: 当 window 对应分析点的 fwd_60d 超出数据结尾时，脚本写入 `fwd_60d = 0.0`。这些 0.0 被无差别平均进 buy/nobuy 对比中，使得长窗口的后续 fwd 收益均值被系统性拉低。

**严重性**: MEDIUM-HIGH — fwd_60d 结果不可信，fwd_20d 在 window 靠近结尾时也受害。且 window 越靠尾部越严重，引入了时间结构偏差。

---

## R1-03: `ttest_ind` 对小样本的滥用 (Red) 🏆

**声明**: `if len(buy) >= 3 and len(nobuy) >= 3: t, p = ttest_ind(buy["fwd_20d"], nobuy["fwd_20d"])`

**问题**:
1. ttest_ind 假设两组独立同分布且方差齐性。`buy` 样本量可低至 3，`nobuy` 可高达数百，Levene 检验几乎必然显著
2. 多重比较 (12+ 参数组合的 buy/nobuy 对比) 没有校正 (Bonferroni/Holm)
3. p 值在报告中无多重比较标注

**严重性**: MEDIUM — p 值不可靠，可能产生假阳性显著发现

---

## R1-04: `WyckoffSignal.confidence` 是 Enum 而非字符串 (Red) 🏆

**声明**: `extract_report` 中 `c = getattr(s, "confidence", None)` 然后 `str(c.value if hasattr(c, "value") else (c or ""))`

**验证**: `WyckoffSignal.confidence: ConfidenceLevel` (model.py:95) — `ConfidenceLevel` 是 Enum。当前代码能工作但有 `AttributeError` 风险——如果 `s` 不是 `WyckoffSignal` 实例而是 `dict`，`hasattr` 返回 True 但 `.value` 可能不存在。

**严重性**: LOW — 能工作但脆弱

---

## R1-05: `Phase` 枚举对比的字符串化 (Red) 🏆

**声明**: `phase = str(rep.structure.phase.value)` — 但 `WyckoffPhase` 枚举值有 `ACCUMULATION = "accumulation"`。而脚本中后续检查 `tp_direction == "买入"` 用的是中文值。

**问题**: 这本身一致，但如果 `WyckoffPhase` 添加新成员或值变化，字符串化会静默继续。使用 `WyckoffPhase.ACCUMULATION` 枚举对比更安全。

**严重性**: LOW — 维护性问题

---

## R1-06: 日志缺失 — 错误全静默 (Red) 🏆

**声明**: `except Exception as e: ext = {"phase": "ERROR", ...} ` — 静默吞噬所有异常

**问题**: 分析引擎抛出的任何错误（数据格式、除零、类型错误）都被静默吞噬为 "ERROR"。用户看到"Spring=0"、"UNKNOWN=120"但不知道这是因为引擎真的没有信号还是因为崩了。

**严重性**: MEDIUM — 故障诊断时间 +∞

---

## R1-07: `ProcessPoolExecutor` 与引擎线程安全 (Red) 🏆

**声明**: `WyckoffEngine` 在 `ProcessPoolExecutor` 的多进程中运行

**问题**: 
- `WyckoffEngine.__init__` 创建 `V3Rules()` 实例 (engine.py:98)，其中可能含有非 fork-safe 的资源
- `_debug_r8_compare` 等调试标志是实例状态，跨进程 OK
- 但 `Indicators.calc_atr` 调用 numpy/pandas 操作，多进程下可能因 OpenMP 线程争抢而降速（虽已设置 `OMP_NUM_THREADS=1`）

**严重性**: LOW-MEDIUM — 效率降级而非正确性

---

## R1-08: 数据加载不处理复权 (Red) 🏆

**声明**: `df = pd.read_parquet(DATA_DIR / f"{symbol}.parquet")` 直接读取

**问题**: 日线 parquet 数据是前复权还是后复权？若未经复权，历史价格断裂将导致 TR 边界错误，fwd 收益被分红/送股扭曲。

**严重性**: MEDIUM — 影响所有窗口的 fwd 收益精度

---

## R1-09: `multi_timeframe=False` 固定 (Blue) 💙

**声明**: `rep = eng.analyze(segment, symbol=symbol, multi_timeframe=False)` 使用单周期

**论证**: `multi_timeframe=False` 是合理的——多周期需要周线/月线数据，而脚本只传入日线 segment。引擎自动走 `_analyze_single` 路径 (engine.py:139-140)。此参数设置正确。

**严重性**: 无 — 正确

---

## R1-10: Window 方向合理性 (Blue) 💙

**声明**: `starts = list(range(max_start, ws - 1, -STEP))[:MAX_WINDOWS]` — 从最新向历史滑动

**论证**: 这是正确的——walk-forward 通常从最新数据开始向历史方向滑动，反映"如果我在当时分析会得到什么结论"。与 `walk_forward_actual.py` 方向一致。

**严重性**: 无 — 正确

---

## R1-11: `getattr` 防御式读取的容错问题 (Split) ⚖️

**声明**: `extract_report` 大量使用 `getattr(rep.structure, "trading_range_high", None)` 等

**Red 方**: `getattr` 带默认值掩盖了真正的数据缺失/结构变化。当 engine 升级 fields 时，脚本静默返回 0.0 而非报错。
**Blue 方**: 防御式读取是必要的——`WyckoffReport` 是 dataclass，字段可能为 None。如果直接 `rep.structure.trading_range_high` 而其为 None，下游 float() 会报错。

**折中**: 对关键字段 (phase, signal_type) 应使用严格读取 + 显式 fallback；对非关键字段 (tr_upper/lower) 可以使用 getattr。

---

## 裁决

| ID | 判定 | 严重性 |
|----|------|--------|
| R1-01 | **Red** 🏆 | HIGH — direction 漏检 2-3x |
| R1-02 | **Red** 🏆 | MED-HIGH — fwd 均值毒化 |
| R1-03 | **Red** 🏆 | MED — 统计方法缺陷 |
| R1-04 | **Red** 🏆 | LOW — 脆弱型 |
| R1-05 | **Red** 🏆 | LOW — 维护性 |
| R1-06 | **Red** 🏆 | MED — 静默失败 |
| R1-07 | **Red** 🏆 | LOW-MED — 效率 |
| R1-08 | **Red** 🏆 | MED — 数据复权 |
| R1-09 | **Blue** 💙 | 无问题 |
| R1-10 | **Blue** 💙 | 无问题 |
| R1-11 | **Split** ⚖️ | 设计权衡 |

**Round 1 总计**: Red 8 🏆 / Blue 2 💙 / Split 1 ⚖️  
**必须修复**: R1-01, R1-02, R1-03, R1-06, R1-08  
**建议修复**: R1-04, R1-05, R1-07

---

## Round 1 对脚本 v1 的修正建议

1. **R1-01 fix**: buy 信号包括 `"做多"`, `"买入"`, `"持有"` 三种方向
2. **R1-02 fix**: 标记 fwd 不可用 (NaN)，在聚合时 dropna
3. **R1-03 fix**: 用非参数检验 (Mann-Whitney U) 替代 ttest_ind；添加 Bonferroni 校正
4. **R1-06 fix**: 添加 `missing_warnings` 计数和错误日志
5. **R1-08 fix**: 验证数据复权状态或使用前复权数据
