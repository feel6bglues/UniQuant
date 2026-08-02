# P0 数据净化 + P1 信号传导修复 — 综合分析

> 分析视角：交易员 × 量化金融算法工程师 × 量化金融专家
> 基于：`docs/analysis/WYCKOFF_FULL_SCAN_ANALYSIS_20260802.md` 的诊断结果 + 源码级根因定位
> 日期：2026-08-02

---

## 〇、问题总览

| 级别 | 问题 | 根因（源码级） | 影响 |
|---|---|---|---|
| **P0** | 175 只非 A股个股混入扫描 | `scripts/wyckoff_full_scan.py:52` `--symbols all` 无类型过滤 | 8 只非个股进"买入"信号 |
| **P0** | 复权口径错配致 target 失真 | raw 标的 P&F count target 用未复权价 | 4 只 target/close 5-57x 虚高 |
| **P1** | Spring 从不触发"买入" | `engine.py:1281-1294` LPS 确认是唯一关卡，`rules.py:207` LPS 条件过严 | 66 只 spring 全部"观察/观望" |
| **P1** | markup 追高买入（反理论） | `engine.py:1333-1334` Test/Shakeout→"买入" | 17 只 markup 追高信号 |
| **P1** | 置信度三值退化 | confidence 硬编码 0.3/0.5/0.7 | 84% D 级，无排序力 |

---

## 一、P0 数据净化：交易员视角的"标的池安全"

### 1.1 现状剖析

扫描脚本 `load_symbols()`（scripts/wyckoff_full_scan.py:39-60）：

```python
if kind == "all":
    return sorted(all_symbols)   # ← 无任何类型过滤！
```

`get_symbols()`（storage_manager.py:376）返回 daily/ 根目录全部 parquet 文件名，包含 175 只非个股（ETF 124 / 可转债 40 / B股 6 / 指数 5）。

**交易员直觉**：把可转债、ETF、B股、指数混进 A股选股池，就像把"苹果、橘子、榴莲"放进"苹果"的筐——分析的每个环节（相位、结构、RS）都建立在对 A股个股的交易规则假设上（T+1、涨跌停、ST），而这些标的规则完全不同。**结果毫无可比性**。

### 1.2 可用资产：元数据已存在

`data/all_stock_codes.csv` 的 `type` 字段是**现成的白名单工具**：

| type | 含义 | 数量 | 处理 |
|---|---|---|---|
| 1 | A股股票 | 5540 | ✅ 保留 |
| 2 | 指数 | 596 | ❌ 排除 |
| 4 | 可转债 | 1117 | ❌ 排除 |
| 5 | ETF/LOF | 1616 | ❌ 排除 |

另：`status=0` 表示退市（1174 只），也应排除。

`StockMetadataManager` 已加载该 CSV（stock_metadata_manager.py:85-100），可通过 `get_stock_info(code).stock_type` 查询。

### 1.3 修复方案（推荐白名单优先，黑名单兜底）

```python
# 方案A（推荐）：基于元数据 type 白名单
from uniquant.data.managers.stock_metadata_manager import StockMetadataManager
_mgr = StockMetadataManager(...)
def is_a_stock(symbol):
    info = _mgr.get_stock_info(symbol)
    return info and info.stock_type == "1" and info.stock_status != "0"

# 方案B（兜底）：前缀黑名单（无元数据时的降级）
def is_a_stock_fallback(symbol):
    code = symbol.split(".")[0]
    if symbol.startswith(("15", "16", "11", "12", "13", "20", "90", "999", "5")): return False
    return True
```

**推荐 A+B 双保险**：元数据存在时用 type=1 精确白名单；缺失时降级为前缀黑名单。

### 1.4 复权口径修复（target 失真）

**根因**：raw 标的的 `last_close` 是复权价，而 P&F count target 用未复权数据。修复：
1. **方案1（推荐）**：P&F 计算前统一对 raw 数据做前复权（用 `data/adjusters/` 现有复权工具），保证 target 与 close 同口径
2. **方案2**：raw 标的的 target_1 标注 `NaN` + 状态列 `target_unreliable=True`，不在候选池使用

**交易员底线**：target 是交易计划的核心（决定盈亏比），口径错配的目标价 = 骗人的目标价，宁可缺失不可错用。

---

## 二、P1 信号传导修复：量化工程师视角的"信号完整性"

### 2.1 Spring→买入 断裂的根因链

完整传导链（5 个环节，断裂在第 3 环）：

```
① _scan_spring()      → spring_detected=True (66只)    ✅ 正常
② spring_date/price   → 记录                       ✅ 正常
③ rule6_spring_validation → lps_confirmed          ❌ 全为 False
④ _step5 ACCUMULATION → 需 lps_confirmed=True       ❌ 阻断
⑤ 交易计划方向        → "观察等待"/"空仓观望"       ❌ 无买入
```

**根因在 `rules.py:207` 的 LPS 确认条件**：

```python
low_volume = recent_vol < max_vol * 0.3      # 条件1: 最近3日均量 < 天量柱30%
price_held = post_spring_df["low"].min() >= spring_low * 0.995   # 条件2: 未破Spring极低点
bounce = last_close > last_open              # 条件3: 最后一根收阳
lps_confirmed = low_volume and price_held and bounce   # 三条件 AND
```

**三条件 AND 在真实数据上几乎不可能同时成立**：
- **条件1（缩量）**：`最近3日均量 < 全量最大量30%` 极苛刻。Spring 后若市场活跃，天量柱可能是全历史最大，3日均量很难跌破其30%
- **条件3（收阳）**：要求"最后一根K线收阳"。扫描日是 07-31，若该日恰下跌，条件即失败——**单日噪声否决整笔信号**
- **三条件 AND 累积失败率**：设各条件独立成立率 50%，AND 后仅 12.5%——全量 66 只 spring 无一通过完全符合概率预期

**结论**：这不是"市场没有 Spring+LPS 结构"，而是**判定条件在真实数据上的联合成立概率被设计得过低**。

### 2.2 修复方向（算法工程师视角）

**方案1：放宽条件为加权评分（推荐）**
- 三个条件从"AND 硬门槛"改为"加权分数"：
  - 缩量（0-40分）+ 价格保持（0-30分）+ 反弹强度（0-30分）
  - 总分 ≥60 → lps_confirmed=True
- 单日收阳改为"最近 2-3 日任一收阳"或"累计涨幅>0"
- 消除单日噪声敏感性

**方案2：分级确认**
- 满分 → "一级(LPS确认)" → 做多
- 部分满足 → "二级(待ST)" → 轻仓试探/观察等待
- 全不满足 → 作废

**方案3：时序弹性**
- 允许 LPS 确认窗口放宽至 Spring 后 3-10 个交易日（当前隐含为紧贴 Spring 后）

### 2.3 Markup 追高买入的反理论问题

**现状**（engine.py:1333-1334）：markup 阶段的 Test/Shakeout 事件 → "买入"

**交易员视角**：markup 是 Wyckoff 的 Phase D/E（已上涨确认后），在此追买 = **右侧追高**。全量扫描中 markup 仅 2.6%（171 只），这 17 只"买入"是引擎在高位追涨。这与 walk-forward 历史结论一致——**引擎的"买入"是追涨信号（前 20d +9.05%），不是抄底信号**。

**修复方向**：
- markup 的"买入"应降级为"持有"或"观察"
- 真正的高胜率入场点应在 accumulation 末段 / spring 确认（Phase B→C 转折），而非 markup（Phase D/E）

---

## 三、置信度体系修复（量化工程师视角）

### 3.1 现状：三值退化的根因

查 confidence 来源：

```python
# engine.py 中 confidence 的赋值
confidence = ConfidenceResult(level=..., score=...)  # level 只有 A/B/B+/C/D
```

- confidence 值 = level 映射（A=0.9, B+=0.8, B=0.7, C=0.5, D=0.3）
- 全量扫描中 B 级仅 101 只、无 A 级 → 84% 压入 D=0.3
- **问题不在映射，在于 level 判定本身偏保守**（B 级需要 Spring+LPS+BC+盈亏比≥1.5 同时成立，同受 LPS 关卡限制）

### 3.2 修复方向

1. **LPS 关卡修复后**，B 级占比自然上升（Spring 不再全被卡死）
2. 将 confidence 从"离散 level"改为"连续分数"：`confidence = f(结构评分, 相位一致性, RS, 盈亏比)`，替代纯 level 映射
3. 融合信号：`final_score = 0.5*normalize(structural_score) + 0.3*confidence + 0.2*RS_rank`，输出单一排序指标

---

## 四、市场环境与信号质量的关系（量化金融专家视角）

### 4.1 市场状态对信号质量的根本约束

当前 A股（2026-07-31）：
- distribution 46.2% + markdown 14.8% = **61% 个股处于下跌/派发结构**
- systemic_decline RS 占 64.7%

**量化金融含义**：beta 下行环境中，任何选股模型的"绝对信号"胜率天然被压低。Wyckoff accumulation 标的在此环境下 6m 平均 -21%，**部分是环境拖累，部分是信号失真**——需要剥离市场 beta 才能评估纯 Alpha。

### 4.2 建议的评估框架（修复后的重扫应做）

1. **信号 → 前瞻收益检验**：修复后重扫，对候选池计算 fwd 20d/60d 收益
2. **市场 beta 剥离**：每只标的收益减去同期指数收益（用已有的 RS index_df）
3. **分层验证**：按置信度/结构评分分层，验证"高分=高收益"单调性
4. **bootstrap 显著性**：spring 标的 vs 对照组，检验正收益是否显著

---

## 五、修复路线图（整合版）

### Phase 0 — 数据净化（1-2天）

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| P0-1 | 扫描脚本加证券类型白名单（type=1 + status≠0） | 全量池从 5382 → ~5199 只干净个股 |
| P0-2 | raw 标的统一复权口径或标注 target 不可用 | 无 target/close > 5 异常 |
| P0-3 | 候选池生成复用同一白名单 | candidates.csv 无 ETF/转债/B股 |

### Phase 1 — 信号传导修复（3-5天）

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| P1-1 | rule6 LPS 判定改加权评分（三条件 AND → 分数阈值） | spring 标的 lps_confirmed 率 > 30% |
| P1-2 | 单日收阳改多日窗口 | 消除单日噪声否决 |
| P1-3 | markup 买入降级为持有/观察 | 无 markup 追高"买入" |
| P1-4 | 置信度改连续评分 + 融合排序 | confidence 分布不再 3 值退化 |

### Phase 2 — 重扫验证（1周）

| 步骤 | 内容 |
|---|---|
| P2-1 | 修复后重扫 5199 只 |
| P2-2 | 前瞻收益 + beta 剥离 + 分层单调性验证 |
| P2-3 | 输出最终可交易候选池 + 有效性报告 |

---

## 六、结论

1. **P0 修复有现成资产**（all_stock_codes.csv type 字段），1-2 天可完成，能立即消除标的污染
2. **P1 断裂根因单一明确**：`rules.py:207` 三条件 AND 过严 + 单日噪声敏感，修复后可显著提升 Spring→买入 传导率
3. **置信度退化是 P1 的副产品**：LPS 关卡修复后 B 级自然上升，无需独立重构
4. **市场环境约束真实存在**：即使修复，46% 派发市场下候选池需结合 beta 剥离做绝对/相对收益双重评估

> 最终判断：P0 是纯工程问题（数据过滤），P1 是信号设计问题（判定阈值）。两者独立可解，修复顺序 P0 → P1 → 重扫验证，是当前性价比最高的路径。
