# Classic Wyckoff 非 P0 实现方案研究 (P1: CN-C4 / SQ-C1 / RS-C1) — 红蓝对抗修订版 v2

> 文档类型: 实现方案研究 (Implementation Plan, 红蓝对抗修订)
> 日期: 2026-08-02 (v2, 经 10 项红蓝对抗裁决修订)
> 范围: 仅覆盖 🟢 值得做项 —— CN-C4 (预复权校验)、SQ-C1 (structural_score)、RS-C1 (相对强弱四分类)。
> 背景: Classic Wyckoff P0 已全部完成 (Compliance 48.3%, P0 8/8 PASS)。本计划基于**研究平台定位** (可复现/可量化/结果可信，非交易执行/风控合规)。
> 前提: 以下所有方案均为**增量增强**，不改变现有 1913 passed 行为；每项独立可交付。

---

## 0. 红蓝对抗摘要 (v1 → v2)

对 v1 设计文档逐项核对源码，10 项声明裁决如下:

| # | 声明 | 裁决 | 修正 |
|---|---|---|---|
| 1 | CN-C4 落点 `_normalize_input_frame` | 蓝胜(有条件) | 补充 `_analyze_multiframe` 透传说明 |
| 2 | SQ-C1 复用 `WSOScorer` | **红胜** | **改用 `event_sequence_score` 纯函数** (WSOScorer 有 EMA/Bayesian 状态，非确定性) |
| 3 | SQ-C1 评分映射 | 红胜(修正) | `event_sequence_score` 返回 (score∈[-1,1], seq_key)，直接 min-max→0-100 |
| 4 | RS-C1 依赖 csi300_index.parquet | 蓝胜 | shape(2430,6)、nulls=0、2016-01-04→2025-12-31 确认 |
| 5 | CN-C4 依赖 `data/fq/` 预复权 OHLC | **红胜** | **`data/fq/` 只有 gbbq.parquet 复权因子表 (189543 行)，无个股预复权 OHLC → 强校验不可行，CN-C4 仅轻量启发式** |
| 6 | RS-C1 `analyze(index_df=...)` | 蓝胜(有条件) | 明确仅 `_analyze_single` 装配，multiframe 经 deepcopy 透传 |
| 7 | ConfidenceResult 5 条件 | 蓝胜 | models.py:504 确认 |
| 8 | WyckoffOutput 缺字段 | 蓝胜 | interfaces.py:403 确认 |
| 9 | compliance 48.3%/11P/7Pa/12F | 蓝胜 | 实测一致 |
| 10 | 目标 compliance ≥55% | **红胜** | **算术错误: 3 项转 PASS → 14P/30 = 46.7%，不达 55%。修正目标为 46.7%** |

**关键修正点**:
1. **SQ-C1 评分基础必须是纯函数** `event_sequence_score` (sequence.py:185)，不得直接实例化复用 `WSOScorer` (有状态)。已核实 `event_sequence_score` 每次 new `WyckoffScorer`，确定性成立。
2. **CN-C4 强校验(列比对)从方案移除**——`data/fq/` 无个股预复权 OHLC，只有复权因子表；引擎层无 symbol 上下文无法对齐因子表，仅保留轻量启发式 + 降级。
3. **compliance 目标修正为 46.7%** (14P/30)，并说明需额外完成 ≥1 项 PARTIAL→PASS 或接受 46.7% 作为本批 P1 的合理终点。

---

## 1. 三项目总览

| ID | 维度 | 现状 (Compliance) | 目标行为 | 数据依赖 | 复杂度 |
|---|---|---|---|---|---|
| CN-C4 | D8-AShare 预复权校验 | FAIL/GAP (无任何检查) | 引擎入口探测未复权数据 → 标记 `adjustment_status=raw` + 信号降级 | 无外部数据 (轻量启发式) | 低 |
| SQ-C1 | D9-Signal structural_score | FAIL/GAP (三处缺字段) | `WyckoffReport`/`WyckoffOutput`/`ConfidenceResult` 增加 `structural_score` (0-100)，由 `event_sequence_score` 派生 | 无新数据 | 低 |
| RS-C1 | D6-RS 相对强弱四分类 | FAIL/GAP (全仓无 RS 代码) | `rs_classify(stock_ts, index_ts)` 四分类，结果进 `WyckoffReport` | `data/csi300_index.parquet` / `000300.SH` index | 中 |

实施顺序: **CN-C4 → SQ-C1 → RS-C1** (复杂度递增；RS-C1 报告扩展复用 SQ-C1 的字段追加模式)。

---

## 2. CN-C4 — 预复权数据校验 (D8-AShare)

### 2.1 TDD 规格

- 规格: "No pre-adjusted data check in engine or data loading path"
- 验收: 未复权数据被拒绝或标记 (研究平台取**标记 + 可信度降级**，不做硬拒绝)

### 2.2 现有代码分析 (红蓝核实)

- **引擎唯一入口**: `WyckoffEngine.analyze(df, symbol, period, multi_timeframe, image_evidence)` (engine.py:137)。
  - `multi_timeframe=False` → `_analyze_single` (engine.py:152)，其内先做列校验，后调 `_normalize_input_frame` (engine.py:113)。
  - `multi_timeframe=True` → `_analyze_multiframe` (engine.py:1661) → `analyze_multiframe` (analysis.py) 回调 `_analyze_single` 生成各周期报告 → `merge_multitimeframe_reports` (analysis.py:195) 用 `copy.deepcopy(daily_report)` 融合。
- **`_normalize_input_frame` 体** (engine.py:113-117): `df.copy()` + `to_datetime(date)` + `sort_values().reset_index()` —— 纯日期/排序归一化，不感知复权，也不要求 volume 列。
- **`_build_report`** (engine.py:1329) 仅被 `_analyze_single` 的 279 行调用；multiframe merge 对未提及的字段走 deepcopy 天然透传。
- **已核实数据事实**: `data/fq/` 仅含 `gbbq.parquet` = 全市场**复权因子表** (189543 行, code/market/date/category/cash_div/split_ratio/rights_ratio/rights_price)，**不存在个股预复权 OHLC**。引擎为纯 OHLC 计算层、无 symbol 上下文，无法对齐因子表 → **强校验方案废弃**。

### 2.3 落点设计 (修订)

**单一插入点**: `_normalize_input_frame` (engine.py:113) 返回前追加复权状态探测。**不改函数签名**。探测结果经 `analyze` → `_analyze_single` 新出的可选字段 `adjustment_status` 暴露到 `WyckoffReport`。

探测逻辑 (纯启发式，仅依赖 OHLC):

```python
def _detect_adjustment_status(close: pd.Series) -> str:
    """返回 "pre_adjusted" | "raw"。

    启发式: A 股单日涨跌停上限 20% (创业板/科创板亦为 20%)。
    前复权数据相邻收盘价 pct_change 不应持续超过 20%；
    未复权数据在除权除息日会出现 >20% 的收盘跳空。
    """
    pct = close.astype(float).pct_change().dropna().abs()
    # 排除连续涨停结构: 前一日本身已涨停(+20%)，次日跳空属正常。
    # 简化: 统计超过 20% 且前一交易日未涨停 (>15%) 的异常跳空天数
    over = (pct > 0.20) & (pct.shift(1).fillna(0) <= 0.15)
    if int(over.sum()) >= 1:
        return "raw"
    return "pre_adjusted"
```

- **`raw` 行为** (研究平台定位，降级不拒绝):
  1. `WyckoffReport.adjustment_status = "raw"`。
  2. `_build_report` 经 `_downgrade_confidence` (engine.py:78，CF-C4 已有模块级降级器) 降 1 级，reason 追加 "未复权数据"。
  3. `WyckoffOutput.adjustment_status` 同步 (interfaces.py:403)。
- **multiframe 透传**: `_analyze_single` 生成的各周期报告均带 `adjustment_status`；`merge_multitimeframe_reports` 用 `deepcopy(daily_report)`，新字段自动保留，无需改 merge 函数。**此点 v1 未声明，已补入测试计划**。

### 2.4 新增/修改文件

| 文件 | 修改 |
|---|---|
| `src/uniquant/brain/wyckoff/engine.py` | 模块级 `_detect_adjustment_status` (靠近 `_downgrade_confidence` 78 行) + `_normalize_input_frame` 调用 + `_analyze_single` 透传 + `_build_report` 装配与降级 |
| `src/uniquant/brain/wyckoff/models.py` | `WyckoffReport` 增加 `adjustment_status: str = "unknown"` |
| `src/uniquant/shared/interfaces.py` | `WyckoffOutput` 增加 `adjustment_status` + to_dict/from_dict |
| `scripts/classic_wyckoff_compliance.py` | CN-C4 检查改为源码特征 (`_detect_adjustment_status` + `adjustment_status` in models) |

### 2.5 测试计划 (TDD)

`tests/classic_wyckoff/test_phase3_nonp0.py`:

1. `test_detect_adjustment_status_pre_adjusted` — 正常连续波动 → `pre_adjusted`。
2. `test_detect_adjustment_status_raw` — 单日 >20% 跳空且前日未涨停 → `raw`。
3. `test_report_marks_raw_adjustment` — raw 数据端到端 `analyze()` → `adjustment_status=="raw"` 且信号置信度 ≤ 对照。
4. `test_multiframe_preserves_adjustment_status` — `analyze(multi_timeframe=True)` 融合后报告保留 `adjustment_status`。**(v2 新增)**
5. `test_output_dict_roundtrip` — `WyckoffOutput` roundtrip 保留 `adjustment_status`。
6. `test_pre_adjusted_passthrough` — 既有 fixture (synthetic_spring_aligned) 得 `pre_adjusted`，回归不破坏。

### 2.6 风险

- 真实创业板/科创板 20cm 连续涨停可能误判 raw。缓解: `pct.shift(1) <= 0.15` 排除涨停延续；即便误判，仅降 1 级，符合"宁可降级不可误信"。**(v2 修订: 加入涨停延续排除)**

---

## 3. SQ-C1 — structural_score 结构完整性评分 (D9-Signal)

### 3.1 TDD 规格

- 规格: "No structural_score field in WyckoffReport, WyckoffOutput, or ConfidenceResult"
- 验收: `structural_score` (0-100) 三处存在，且参与信号 (作为 confidence 加权输入)。

### 3.2 现有代码分析 (红蓝核实)

- **缺失点确认** (compliance.py:533-546): 三处均无 `structural_score`。
- **评分基础** (红蓝修正):
  - ❌ **不得用 `WSOScorer.score_events` (sequence.py:60)** —— 有状态 (EMA `_last_score`/`_is_warm` + 可选 Bayesian 更新)，每次 analyze 调用顺序不同则结果不同，破坏研究平台"可复现"。
  - ✅ **用 `event_sequence_score` (sequence.py:185)** —— 便捷纯函数，每次 new `WyckoffScorer`，无跨调用状态；签名 `(event_types: List[str], has_spring=False, spring_event_count=0, wss_lookup=None) -> (float, str)`，score∈[-1,1]。
  - `detect_all_events` (events.py:475) → `List[WyckoffEvent(event_type, date)]`。
- **`ConfidenceResult`** (models.py:504): 5 条件矩阵 (bc_located/spring_lps_verified/counterfactual_passed/rr_qualified/multiframe_aligned) 确认，无结构维度。
- **`WyckoffOutput`** (interfaces.py:403): 12 字段确认，无 `structural_score`。
- **传播链现状**: `wyckoff_analysis_engine.py:_extract_from_report` (22-89) 手工抽取 report 字段到 `WyckoffOutput`；`WyckoffAdapter.adapt` (adapters.py:159) 读 dict keys 构造 TradingSignal + metadata。

### 3.3 落点设计 (修订)

**新增模块级纯函数** (engine.py，紧邻 `_downgrade_confidence` 78 行，遵循共享助手模式):

```python
def _compute_structural_score(event_types: List[str], step1, step3) -> float:
    """0-100 结构完整性评分 (纯函数，可复现)。

    - event_sequence_score 加权事件序列 → base ∈ [-1,1]；
    - 明确相位 (非 unknown) +0.15，spring/utad 已确认按 step3 质量 +0.05~0.10；
    - clamp 到 [-1,1] → min-max 映射到 [0,100]。
    """
    base, _ = event_sequence_score(event_types)
    phase_bonus = 0.15 if step1.phase != WyckoffPhase.UNKNOWN else 0.0
    event_bonus = 0.0
    if step3.spring_detected:
        event_bonus += 0.05 + 0.05 * float(getattr(step3, "spring_quality", 0.5))
    if step3.utad_detected:
        event_bonus += 0.05
    raw = max(-1.0, min(1.0, base + phase_bonus + event_bonus))
    return round((raw + 1.0) / 2.0 * 100.0, 2)
```

- **事件来源**: `_build_report` 或 `_step5` 处调 `detect_all_events(frame)` 取 `event_type` 列表。相位判定 (PH-C1/C2) 已调用 detect_all_events，若其缓存结果可复用则复用，否则独立计算 (单 ticker 性能非瓶颈)。
- **传播链**:
  1. `_build_report` (engine.py:1329) 计算 → `WyckoffReport.structural_score`。
  2. `ConfidenceResult` (models.py:504) 增加 `structural_score: float = 0.0`，置信度矩阵计算时作加权输入 (与现有 5 条件并存，非破坏性)。
  3. `WyckoffOutput` (interfaces.py:403) 增加 `structural_score`；`_extract_from_report` (wyckoff_analysis_engine.py:22) 透传。
  4. `WyckoffAdapter.adapt` (adapters.py:159) 将 `structural_score` 加入 metadata (研究用途，不改 BUY/SELL/HOLD)。
- **multiframe**: `merge_multitimeframe_reports` deepcopy 自动透传 (验证测试覆盖)。

### 3.4 新增/修改文件

| 文件 | 修改 |
|---|---|
| `src/uniquant/brain/wyckoff/engine.py` | `_compute_structural_score` (纯函数) + `_build_report` 装配 + 置信度矩阵加权 |
| `src/uniquant/brain/wyckoff/models.py` | `ConfidenceResult` + `WyckoffReport` 增加 `structural_score` |
| `src/uniquant/shared/interfaces.py` | `WyckoffOutput` 增加 `structural_score` + dict 同步 |
| `src/uniquant/services/analysis/wyckoff_analysis_engine.py` | `_extract_from_report` 透传 |
| `src/uniquant/signal/adapters.py` | `WyckoffAdapter.adapt` metadata 增加 `wyckoff_structural_score` |
| `scripts/classic_wyckoff_compliance.py` | SQ-C1 检查改为三处字段 + `_compute_structural_score` 源码特征 |

### 3.5 测试计划 (TDD)

`tests/classic_wyckoff/test_structural_score.py`:

1. `test_structural_score_in_all_models` — 三处均有 `structural_score` 且默认值合法 (0-100)。
2. `test_structural_score_range` — 多 fixture 下 `analyze()` 输出 ∈ [0,100]。
3. `test_structural_score_higher_for_clear_phase` — 明确相位 (synthetic_accumulation_event_sequence) score > UNKNOWN 对照。
4. `test_structural_score_deterministic` — **同一输入两次 analyze 得分一致** (纯函数验证，防有状态回归)。**(v2 新增)**
5. `test_structural_score_affects_confidence` — 高/低结构分组 confidence 单调方向一致。
6. `test_output_dict_roundtrip` — `WyckoffOutput` roundtrip 保留 `structural_score`。
7. `test_multiframe_preserves_structural_score` — multiframe 融合后保留。**(v2 新增)**
8. `test_adapter_metadata` — `WyckoffAdapter.adapt` metadata 含 `wyckoff_structural_score`。

### 3.6 风险

- 事件序列计算重复 (相位判定 + 评分各一次) → 性能。缓解: 优先复用缓存；当前非瓶颈。**(v2 明确)**
- 严禁引入有状态 scorer —— 测试 #4 固化回归防线。

---

## 4. RS-C1 — 相对强弱四分类 (D6-RS)

### 4.1 TDD 规格

- 规格: `rs_classify(stock_ts, index_ts) == "leader"`；四分类: **leader / follower / weak_independent / systemic_decline**。
- 验收: 四分类正确 (强于大盘+缩量→leader)；规格输入 "stock > index + low volume → 强势独立"。

### 4.2 现有代码分析 (红蓝核实)

- **全仓无 RS 代码**: grep `rs_`/`relative_strength` 在 `src/uniquant/` 仅命中 `models.py:228 ChipAnalysis` (资金流向，与 RS 无关)。
- **数据依赖确认**:
  - `data/csi300_index.parquet`: **shape (2430, 6)**, cols = [date, open, high, low, close, volume], dtypes (date=datetime64[ns], close=float64, volume=int64), **nulls=0**, 2016-01-04 → 2025-12-31。路径不硬编码进生产代码。
  - 生产 index 接入先例: `analysis_service_v2.py:409` (`MarketConstants.INDEX_HS300`)、`:539` (`"000300.SH"`)。Wyckoff 引擎目前不接收 index。
- **落点**: 纯计算模块放 `brain/wyckoff/relative_strength.py`，不进 8-step 主链；`WyckoffReport` 增加 `relative_strength` 字段。

### 4.3 落点设计 (修订)

**新模块 `src/uniquant/brain/wyckoff/relative_strength.py`**:

```python
@dataclass
class RelativeStrengthResult:
    classification: str          # leader | follower | weak_independent | systemic_decline | unknown
    stock_return_20d: float
    index_return_20d: float
    excess_return: float
    stock_vol_ratio: float       # 个股量比 vs 自身 20d 均值
    sufficient_data: bool = True

def rs_classify(stock_ts: pd.DataFrame, index_ts: pd.DataFrame,
                lookback: int = 20) -> RelativeStrengthResult:
    """对齐两时间轴 (inner join on date)，计算同期收益与量能。

    - systemic_decline: index < 0 且 stock < 0 且 excess < 阈值
    - leader:            excess > 0 且 vol_ratio < 1 (缩量强势独立)
    - follower:          excess > 0 但 vol_ratio >= 1 (放量跟随)
    - weak_independent:  index > 0 且 stock < 0 (逆势走弱)
    """
```

- 与规格对齐: "stock > index + low volume → leader"。阈值 (excess 阈值、vol_ratio=1.0) 模块级常量，供参数敏感性测试。
- **引擎集成 (增量)**: `analyze` 增加**可选参数** `index_df: Optional[pd.DataFrame] = None` (engine.py:137 签名追加，默认 None 不改现有调用方)；非 None 时仅在 `_analyze_single` 计算写入 `WyckoffReport.relative_strength`；multiframe 经 deepcopy 透传日线结论。
- `wyckoff_analysis_engine.py:run_wyckoff_analysis` 从 orchestrator 读 `000300.SH`/`INDEX_HS300` 并透传。
- **`WyckoffOutput.relative_strength: Optional[str]`** 透传。

### 4.4 新增/修改文件

| 文件 | 修改 |
|---|---|
| `src/uniquant/brain/wyckoff/relative_strength.py` | **新模块** — `RelativeStrengthResult` + `rs_classify` |
| `src/uniquant/brain/wyckoff/models.py` | `WyckoffReport` 增加 `relative_strength` + `relative_strength_detail` |
| `src/uniquant/brain/wyckoff/engine.py` | `analyze(index_df=None)` 可选参数 + `_analyze_single` 装配 |
| `src/uniquant/shared/interfaces.py` | `WyckoffOutput` 增加 `relative_strength` |
| `src/uniquant/services/analysis/wyckoff_analysis_engine.py` | `run_wyckoff_analysis` 读 index 并透传 |
| `scripts/classic_wyckoff_compliance.py` | RS-C1 检查改为模块存在 + `rs_classify` 源码特征 |

### 4.5 测试计划 (TDD)

`tests/classic_wyckoff/test_relative_strength.py`:

1. `test_rs_leader` — 个股 20d > 指数且量比 < 1 → `leader` (对齐规格)。
2. `test_rs_follower` — 个股 > 指数但放量 → `follower`。
3. `test_rs_weak_independent` — 指数涨、个股跌 → `weak_independent`。
4. `test_rs_systemic_decline` — 指数跌、个股同步跌无超额 → `systemic_decline`。
5. `test_rs_date_alignment` — 两序列日期错位，inner join 后无 NaN 泄漏。
6. `test_engine_index_df_optional` — 不传 `index_df` → `relative_strength` 为 None，行为与现状一致 (回归)。
7. `test_engine_index_df_integration` — 传 `index_df` → 报告有值。
8. `test_output_dict_roundtrip` — `WyckoffOutput` roundtrip 保留 `relative_strength`。
9. `test_csi300_fixture_alignment` — `data/csi300_index.parquet` 真实数据可读/对齐 (不依赖具体分类)。

### 4.6 风险

- index 缺失 → `index_df=None` 降级，不抛错。分类仅作研究标记。
- 20d 窗口对次新股不足 → `sufficient_data=False` + `classification="unknown"`。
- **multiframe 语义**: 融合报告保留日线 RS，周/月线不单独计算 RS (文档明确，避免过度设计)。

---

## 5. 验收与合规目标 (红蓝修订)

| 项 | 当前 (实测) | 目标 |
|---|---|---|
| Compliance | 48.3% (11P/7Pa/12F, 30 项) | **46.7% → 47.5% 区间 (14P/30)** —— v1 目标 55% 为算术错误。本批 3 项 → 14P/30 = 46.7%；若另有 1 项 PARTIAL→PASS 或 CF-C1 转 PASS 则更高。**如实申报 46.7%**，不虚构 55%。 |
| 新增测试 | — | ≥ 20 (6+8+9) |
| 全套回归 | 1913 passed | 全量通过，无破坏 |
| ruff | 0 | 0 |
| **可复现性** | — | **SQ-C1 纯函数确定性测试** (test #4) |

> 注: v1 声称"≥55% (3 项转 PASS → 15P)"有双重错误 —— 既有 PASS 11 非 12，3 项转 PASS 为 14P 非 15P，且 14/30=46.7% < 55%。v2 修正为如实申报 46.7%。若用户希望达 55%，需将 P1 范围扩大到 🟡 项 (CF-C1/MT-C2/C3/PH-C3/C5)，本批不承诺。

---

## 6. 文档同步清单 (完成后必须执行)

- [x] `AGENTS.md` — 新增 "Classic Wyckoff P1 非 P0 修复" 段，记录三项完成状态 + Compliance 46.7%→实际值 (实测 58.3%)
- [x] `scripts/classic_wyckoff_compliance.py` — 三项检查从静态占位改为源码特征
- [x] `docs/analysis/CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md` — 签字表追加 3 行
- [x] 本文件状态更新 (Pending → Done)

> **执行记录 (2026-08-02)**: CN-C4 → 51.7% (12P)；SQ-C1 → 55.0% (13P)；RS-C1 → **58.3% (14P/7Pa/9F/30)**。三项全部实现并通过 TDD 验收。RS-C1 采用 `relative_strength.py` 纯函数 `rs_classify` (四分类 + 日期对齐)，引擎 `analyze(index_df=None)` 可选接线，不传 index_df 时报告字段为 None (向后兼容)。全套回归 1947 passed, 0 ruff (新增文件)，golden_20 baseline 一致。
>
> **补全记录 (2026-08-02, SQ-C1 置信度加权接线)**: 复核发现 §3.3-2 "置信度矩阵加权输入" 承诺最初未落地 —— `_calc_confidence`/`rule8_confidence_matrix` 均未消费 structural_score，`ConfidenceResult.structural_score` 恒为 0.0。已补实现: 新增模块级纯函数 `_apply_structural_adjustment(confidence, structural_score)` (engine.py)，`_analyze_single` 在置信度计算后调用 —— 恒回填 `structural_score` + 等级单调微调 (≥70 升 1 级 / ≤35 降 1 级，A/D 边界不越界，B+ 归 B，5 条件矩阵成员不变)；`_build_report` 改为透传已算分 (消除重复计算)。新增 8 测试 (回填/升级/降级/居中/单调/B+/矩阵成员/端到端)。全套回归 1955 passed, 0 ruff (新增文件)，golden_20 baseline 一致。compliance SQ-C1 检查补 `_apply_structural_adjustment` 源码特征。

---

## 7. 明确不做 (WONTFIX 备忘)

CN-C1 (box_size 规则)、CN-C2 (T+1 冷却)、CN-C3 (涨停截断)、VS-C1 (结构冲突统计)、VS-C3 (tick 级扫描)、PF-C5 (P&F 支撑阻力)、ES-C2/C5、RS-C2 (资金流影响置信度)、SQ-C2 (部分，TRADE-OFF 维持) —— 均为交易规则类或无数据支撑，与研究平台定位不符。

---

## 8. 红蓝对抗过程记录 (附录)

| 轮次 | 蓝方 (文档声明) | 红方 (源码证据) | 裁判 |
|---|---|---|---|
| R1 | `_normalize_input_frame` 是 CN-C4 落点 | engine.py:113-117 确认只做 copy+to_datetime+sort；但文档未提 multiframe 路径 (engine.py:1661) | 蓝胜，补透传说明 |
| R2 | SQ-C1 复用 WSOScorer 加权 | sequence.py:60-103: score_events 写 `self._last_score` + `_is_warm` + Bayesian 更新 → 跨调用状态 | **红胜** |
| R3 | SQ-C1 可用纯函数替代 | sequence.py:185 `event_sequence_score` 每次 new WyckoffScorer，确定性成立 | 蓝方修正采纳 |
| R4 | `data/fq/` 为预复权数据 | `data/fq/gbbq.parquet` = 复权因子表 (189543 行, code/market/cash_div/split_ratio/rights_ratio/rights_price)，无个股 OHLC | **红胜** |
| R5 | csi300_index.parquet 可用 | shape(2430,6)、nulls=0、2016→2025-12-31 确认 | 蓝胜 |
| R6 | compliance 目标 ≥55% | 11P+3P=14P/30=46.7% ≠ 55% | **红胜** |
| R7 | `_build_report` 是唯一报告装配点 | engine.py:279 调用 (仅 _analyze_single)；multiframe merge 走 deepcopy (analysis.py:195) → 新字段透传 | 蓝胜，补验证 |
| R8 | ConfidenceResult 5 条件 | models.py:504 确认 | 蓝胜 |
| R9 | WyckoffOutput 缺 structural_score | interfaces.py:403 12 字段确认 | 蓝胜 |
| R10 | 3 项全 PASS 后 compliance 计算 | 14P/30 = 46.7%，非 55% | **红胜** |

**净裁决**: 红胜 4 项 (R2/R4/R6/R10 与 R3 修正) —— 全部为**方法正确性**问题 (有状态评分器、数据依赖误判、算术错误)，未动摇三项的可行性与落点；蓝胜 6 项确认基础事实。修订后方案可直接进入实施。
