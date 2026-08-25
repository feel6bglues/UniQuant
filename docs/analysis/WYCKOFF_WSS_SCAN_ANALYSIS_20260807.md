# WSS 启用后全量扫描分析 + 落实核验报告

> 数据源：`results/wyckoff_full_wss/wyckoff_scan_all.csv`（2026-08-07，WSS 启用后全量 5755 只）
> 对照档案：`docs/analysis/WYCKOFF_FULL_SCAN_ANALYSIS_20260802.md`（WSS 关闭时 5374 只）
> 核验工具：`scripts/classic_wyckoff_compliance.py`（30 项检查）

---

## 一、执行摘要

2026-08-07 WSS 全量训练完成并启用后，重跑全量 Wyckoff 扫描。**结论：P0/P1 修复对引擎输出产生实质改善，但数据净化后仍需以干净个股池（4787 只）为准；相位-收益前瞻验证需 as-of 回放模式补充。**

| 指标 | 2026-08-02 (WSS OFF) | 2026-08-07 (WSS ON) | 变化 |
|---|---|---|---|
| 全量成功 | 5374/5382 | 5755/5755 | 0 失败 |
| 扫描耗时 | 531s (0.099s/只) | 1761s (0.306s/只) | WSS 混合分 3x 开销 |
| A 级置信度 | **0** | **96** (1.7%) | 置信度体系突破 |
| B 级 | 1.6% | 762 (13.2%) | 中间层恢复 |
| 结构分 max | **64.4** | **77.7** | 天花板解除 (P1-2) |
| 结构分 ≥70 | 0 | **300** | 升级路径可达 |
| 结构分 p25-p75 | 58.7-60.9 (span 2.2) | 61.6-65.4 (span 3.8) | 区分度提升 |
| spring→可操作 | **0/66** | **15/36 轻仓试探** (干净池) | 传导断裂修复 (P0) |
| 置信vs结构 pearson | -0.024 | **+0.023** | 由负转正 |

---

## 二、WSS 启用后的全局分布

### 2.1 相位分布（5755 全量）

```
distribution 2640 (45.9%)  |  accumulation 1338 (23.2%)  |  markdown 1164 (20.2%)
unknown 456 (7.9%)         |  markup 157 (2.7%)
```

与 2026-08-02（distribution 46.2% / accumulation 25.2%）一致——市场宽幅震荡偏弱格局不变，相位引擎稳定。

### 2.2 置信度分布（archive: 84% D / 14.3% C / 1.6% B / 0 A）

```
D 4612 (80.1%)  |  B 762 (13.2%)  |  C 285 (5.0%)  |  A 96 (1.7%)
```

**改善**：A 级从 0 → 96，B 级从 1.6% → 13.2%。P0-1/2 置信度 gate 修复 + P1-2 放大使中间层恢复。

### 2.3 结构评分（archive: p25=58.7 p50=60.0 p75=60.9 max=64.4 std=4.3）

```
p10=56.3 p25=61.6 p50=63.3 p75=65.4 p90=68.5 max=77.7 std=6.25
```

**改善**：max 64.4 → 77.7，≥70 分从 0 → 300 只。BASE_AMPLIFICATION 移除天花板（P1-2）。

### 2.4 候选池（C级+ 且 结构分≥55 且 phase∈{accum, distribution}）

```
710 只  (archive: 306 含污染)
  confidence: A 81 / B 492 / C 137
  phase: distribution 389 / accumulation 321
  RS: systemic_decline 365 / leader 230 / follower 111 / weak_independent 4
  spring 内含: 34
```

高价值候选（A/B 级 + leader）：**202 只**（archive: 7 只 B级+leader+spring）。A/B 级 + leader + spring：**15 只**。

### 2.5 置信度 vs 结构分相关性

```
pearson = +0.023   (archive: -0.024)
```

由弱负转为弱正——两个质量维度不再冲突，但仍需融合排序（P1 遗留项）。

---

## 三、P0/P1/P2 落实情况核验（对照档案行动建议）

### 3.1 ✅ P0-1/2 Spring 传导断裂修复

**archive 判定**：`spring 66 → 0 做多（42观察/24空仓）`，与经典 Wyckoff 完全相悖。

**现状**（干净个股池 4787 只）：`spring 36 → 15 轻仓试探 / 21 空仓观望`。

- 传导恢复：spring 命中时若 `conf∈{A,B} 或 rr≥1.5` 给出「轻仓试探」（不再是清一色观望）
- A股铁律守卫保留：弱置信 + 弱 RR 的 spring 仍观望（21/36），markdown/distribution 禁做多

### 3.2 ✅ P1-2 结构评分天花板解除

**archive 判定**：`max 64.4，无 ≥70 分标的，58-62 区间拥挤 70%，评分对排序几乎无贡献`。

**现状**：`max 77.7，≥70 分 300 只，p25-p75 span 2.2→3.8`。WSO base ×5 放大 + WSS 混合分生效后，评分重获区分力。

### 3.3 ✅ P1-1 WSS 训练完成并启用

**archive 判定**：WSS 训练产物全缺，开启 flag 静默 no-op（死分支）。

**现状**：`wss_lookup_v2.json` 418 seqs（1000 只/87977 obs），`config wss_enabled: true`，引擎启动加载 418 seqs。golden_20 A/B：WSS-ON vs OFF 结构分差达 ±13.6。

### 3.4 ✅ P2-1 MultiTimeframeResonance 标注

**archive 判定**：无共振标注字段。

**现状**：`MultiTimeframeContext` 携带 `resonance_count/dir/strength`，`WyckoffOutput` 透传 3 字段，round-trip 保真。仅标注不反向信号。

### 3.5 ⚠️ 遗留项（Compliance 58.3% 未变）

| ID | 状态 | 说明 |
|---|---|---|
| D3-Volume 0% | FAIL | 仅总量能，无 tick 级方向拆分（数据依赖） |
| D5-MTF 25% | PARTIAL | MT-C2 resonance 无 R²/IC 提升比（研究平台定位不符） |
| D6-RS 50% | PARTIAL | RS-C2 ChipAnalysis 未入置信矩阵 |
| D8-AShare 25% | FAIL | CN-C1 box_size 硬编码、CN-C3 P&F 未查涨跌停（CN-C4 复权已 PASS） |
| VS-C1 | FAIL | events.py 154 硬编码阈值 |
| PF-C5 | FAIL | P&F 全量重建（性能项） |

**NONFIX（研究平台定位不符）**：CN-C1/C2/C3、VS-C1/C3、MT-C2、RS-C2、CF-C1。

---

## 四、数据净化与样本口径

- 2026-08-02 已归档 552 个指数文件到 `data/lake/quotes/daily/archive_index/`
- 本次 `--symbols all` 仍扫 5755（含保留的 000300/000905 基准 + ETF/B股/LOF 137 只）
- **干净个股池**（剔除 000xxx.SH/399xxx.SZ 指数前缀 + is_etf）：**4787 只**，供相位/信号分布使用
- 候选池 710 只未剔除 ETF/B股污染段——如需可交易候选，需叠加证券类型白名单（P0-数据层遗留）

---

## 五、结论

| 维度 | 判定 |
|---|---|
| P0 Spring 传导 | ✅ 修复，实盘 36→15 轻仓试探 |
| P1-2 结构分天花板 | ✅ 解除，max 77.7 / ≥70 达 300 |
| P1-1 WSS 训练+启用 | ✅ 418 seqs，A/B ±13.6 分 |
| P2-1 共振标注 | ✅ 透传保真 |
| Compliance | 58.3% (14P/7Pa/9F/30) 未变（与修复范围一致） |
| 相位-收益前瞻 | ⏳ 需 as-of 回放模式补充（fwd_20d 在最新截止日为空） |

**下一步建议**：
1. `--as-of 2026-06-30` 回放模式重跑，量化 WSS-ON 相位→fwd 收益 vs archive 的 -21% 背离是否收敛
2. 候选池加证券类型白名单（剔 159/16x/123/127/200/999 段）产出可交易候选
3. 置信度×结构分融合排序（pearson 已由负转正，融合条件成熟）

---

## 六、补充：as-of 回放相位→前向收益验证（golden_100, 2026-04-30 截止）

数据湖最新交易日 2026-07-19，`--as-of 2026-06-30` 仅剩 17 个前向交易日 < 20d 窗口，全量 fwd 为空。改用 **golden_100 + as-of 2026-04-30**（剩余 56 个前向交易日），可算 20d fwd。

```
phase           n     20d%    ↑/↓
markdown         4   +11.21%   ✗ (理论应下跌)
accumulation    26    +0.30%   ✓ (蓄势偏正)
distribution    47   +14.52%   ✗ (理论应见顶跌)
markup          17    +5.79%   ✓ (理论应续涨)
unknown          6    +2.70%
spring           3  (20d 均非空)
```

**结论**：WSS-ON 下 **markup/accumulation 方向正确，但 distribution 及 markdown"看跌"背离仍存**（distribution 20d 仍 **+14.52%**）。与 archive「相位-收益一致性仅 50%」及 `wyckoff_research_report`「distribution 保证见顶不保证下跌」结论一致。**WSS 改善结构评分区分度，但未改变 distribution/markdown 相位自身的方向预测力不足**——为引擎相位评判固有上限，非 WSS 可解。列为已知局限（D5-MTF / 相位前瞻非引擎强项）。

小样本（golden_100），仅方向性参考，非统计显著。
