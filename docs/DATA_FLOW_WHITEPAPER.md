# UniQuant 数据流生命周期白皮书

> 追踪目标: 数据形态的每一次突变 (Mutation) | 忽略算法数学 | 只关注 Shape/Type/Key/Index
>
> **⚠️ 类型声明更新**: 本文档的 `TradingSignal`, `WyckoffReport` 等类型在 Phase 1-3 已从 `dataclass` 重构为 `Protocol` (见 `shared/interfaces.py`)。数据流路径描述仍然有效，但具体类型定义以源码为准。

---

## 0. 数据形态符号约定

```
DF                    = pd.DataFrame
DF[col1, col2, ...]   = DataFrame 含指定列
DF@index              = DataFrame 的 Index 类型 (DatetimeIndex / RangeIndex / MultiIndex)
Series                = pd.Series
Dict[k_type, v_type]  = Python dict
Signal                = signal.models.Signal (dataclass)  → Phase 3+: signal.adapters 接管
TradingSignal         = shared.interfaces.TradingSignal (Protocol) → Phase 1-3: dataclass→Protocol
WyckoffReport         = brain.wyckoff.models.WyckoffReport (dataclass) → Phase 3: WyckoffOutput
FactorICResult        = brain.factors.analyzer.FactorICResult (dataclass) → 仍有效
→                     = 数据形态转换箭头
⚠️                    = 数据丢失/风险点
🔴                    = 断裂点 (无自动桥接) → Phase 3 大部分已修复
```

---

## 1. 追踪路线 A: 因子管道的向量化血脉

### 1.1 全链路数据形态转换图

```
[Step 0] StorageManager.read_data(symbol)
    输出: DF[date, open, high, low, close, volume, amount, ...]
    Index: RangeIndex (0, 1, 2, ...)
    Shape: (N_days, 8~15 cols)
    ↓
[Step 1] ScanPipeline.load_data()
    操作: self.daily_data[symbol] = DF (per-symbol dict)
    形态不变: Dict[str, DF]
    ↓
[Step 2] ScanPipeline.build_factors()
    操作: pd.concat(dfs, ignore_index=True) + df['code'] = symbol
    输出: self.combined_df = DF[date, open, high, low, close, volume, code, ...]
    Index: RangeIndex (0, 1, ..., total_rows)
    Shape: (N_stocks × N_days, 8~15 cols)
    ⚠️ 内存: 完整拷贝所有股票数据到单个 DataFrame
    ↓
[Step 2.5] _merge_financial_metrics()
    操作: FinancialFactorBridge.process(daily_df, fin_df)
    形态: 按 code groupby → 逐股 merge_asof 财务数据
    输出: combined_df 新增 [eps_ttm, bps, pe_ttm, pb, roe, ...] 列
    Index: 保持 RangeIndex
    ⚠️ merge_asof tolerance="7D" — 最近7天内的财报数据会被合并
    ⚠️ _apply_report_date_offset — 季报+3月, 中报+2月, 年报+4月 (模拟延迟)
    ↓
[Step 3] FactorComposer.compute_all_factors(df)
    操作: 遍历 FactorRegistry.get_enabled() → 逐因子计算
    输入: DF[date, open, high, low, close, volume, code, ...]
    输出: factor_df = DF[momentum_20d, momentum_60d, volatility_20d, ...]
    Index: 与输入 df.index 对齐 (RangeIndex)
    Shape: (N_rows, N_factors)

    关键子操作:
    ├── _iter_groups(df): groupby("code") → 逐股计算
    │   ⚠️ 如果无 "code" 列, 退化为全量计算 (截面混合)
    ├── _sort_group(df): sort_values("date") — 确保时间序列顺序
    ├── factor.compute_func(group_df.copy()):
    │   输入: DF 单股 (date sorted)
    │   输出: Series[float] (同长度, NaN for insufficient data)
    │   ⚠️ .copy() — 每个因子计算都拷贝一份, 内存 O(N_factors × N_rows)
    └── pd.Series(np.asarray(series, dtype=float), index=group_df.index)
        形态: 强制 float64, NaN 保留
    ↓
[Step 4] FactorComposer._normalize_factors(df, factor_df)
    操作: 按日期横截面 Z-score 标准化
    输入: factor_df (同 Step 3 输出)
    输出: normalized_df = 同 shape, 每列 mean≈0, std≈1

    关键子操作:
    ├── df.groupby(date_col).groups → 按日期分组
    ├── _zscore_frame(group_factors):
    │   std = factor_df.std(ddof=0).replace(0, np.nan)
    │   z = (x - mean) / std
    │   ⚠️ 0 方差 → NaN → fillna(0.0) — 静默将常数因子归零
    └── pd.concat(normalized_parts).loc[factor_df.index]
        ⚠️ 必须 .loc[factor_df.index] 重排, 否则 index 顺序可能错乱
    ↓
[Step 5] FactorComposer._symmetric_orthogonalization(normalized)
    操作: F_orth = F @ (F.T @ F)^{-1/2} (特征值分解)
    输入: normalized_df (N_rows × K_factors)
    输出: orth_df (同 shape, 因子间正交)

    关键子操作:
    ├── F_centered = F - F.mean(axis=0) — 再次去均值
    ├── cov_matrix = np.cov(F_centered.T) — K×K 协方差
    ├── eigenvalues, eigenvectors = linalg.eigh(cov_matrix)
    ├── eigenvalues = np.maximum(eigenvalues, 1e-10) — 截断负特征值
    ├── D_inv_sqrt = diag(1/√eigenvalues)
    ├── F_orth = F_centered @ cov_inv_sqrt
    └── 再次 Z-score: (F_orth - mean) / std
        ⚠️ 正交化后再次标准化, 可能改变因子的经济含义
        ⚠️ linalg.LinAlgError fallback → 返回原始因子 (静默降级)
    ↓
[Step 6] FactorComposer._build_composite_frame()
    操作: composite_score = Σ(factor_i × weight_i)
    输入: normalized_df + weights Dict
    输出: result_df = DF[factor1, factor2, ..., composite_score]
    Index: 与输入对齐
    ↓
[Step 7] FactorComposer.process() (兼容性入口)
    操作: result_df = df.copy() + factor_df columns + composite_score
    输出: DF[原始列..., momentum_20d, ..., composite_score]
    Shape: (N_rows, 原始_cols + N_factors + 1)
    ⚠️ df.copy() — 完整拷贝原始 DataFrame
    ↓
[Step 8] ScanPipeline.compose_scores()
    操作: self.combined_df = result_df (in-place 赋值)
    输出: combined_df 含 composite_score
    ↓
[Step 9] ScanPipeline.generate_report()
    操作: StockScreener.generate_top_bottom(combined_df)
    输出: top_df / bottom_df (排序后子集)
    → 写入 Markdown 报告文件
```

### 1.2 关键数据形态审计

#### Index 一致性

| 步骤 | Index 类型 | 是否保持 | 风险 |
|------|-----------|---------|------|
| StorageManager.read_data | RangeIndex | ✓ | 无 |
| pd.concat(dfs) | RangeIndex (ignore_index=True) | ✓ | 无 |
| compute_all_factors | RangeIndex | ✓ | 通过 groupby index 对齐 |
| _normalize_factors | RangeIndex | ⚠️ | `pd.concat(parts).loc[factor_df.index]` 重排 |
| _symmetric_orthogonalization | RangeIndex | ✓ | DataFrame 构造时传入 index |
| _build_composite_frame | RangeIndex | ✓ | Series 基于 normalized.index |

#### NaN 处理链

```
因子计算: rolling(20).std() → 前19行为 NaN
    ↓
_zscore_frame: std=0 → NaN → fillna(0.0)  ⚠️ 静默归零
    ↓
_symmetric_orthogonalization: replace(inf, -inf, nan).fillna(0.0)  ⚠️ 静默归零
    ↓
composite_score: add(..., fill_value=0.0)  ⚠️ NaN 被当作 0 参与加权
```

**风险**: NaN 被层层 fillna(0.0) 替代, 导致:
1. 数据不足的股票获得 composite_score=0.0, 与"中性因子"不可区分
2. 截面排序时, 这些股票会被排在中间位置, 影响 top/bottom 筛选

#### 内存拷贝审计

| 操作 | 拷贝类型 | 内存影响 |
|------|---------|---------|
| `pd.concat(dfs, ignore_index=True)` | 深拷贝 | O(N_stocks × N_days) |
| `factor.compute_func(group_df.copy())` | 深拷贝 × N_factors | O(N_factors × N_rows) |
| `self._zscore_frame(factor_df)` | 深拷贝 | O(N_rows × N_factors) |
| `F_centered = F - F.mean(axis=0)` | numpy 视图 | O(1) |
| `F_orth = F_centered @ cov_inv_sqrt` | numpy 深拷贝 | O(N_rows × N_factors) |
| `result_df = df.copy()` | 深拷贝 | O(N_rows × N_cols) |

**估算**: 对于 5000 股 × 250 天 × 10 因子 = 12.5M 数据点, 峰值内存约 12.5M × 8B × 5 copies ≈ **500MB**

#### 前视偏差检测

```python
# brain/factors/analyzer.py: check_lookahead_leakage()
# 方法: 未来扰动不变性测试
# 1. 计算 baseline = factor_func(df)
# 2. 扰动 df[cutoff:] 的 close 价格 × random(1.5, 3.0)
# 3. 比较 baseline[:cutoff-1] 是否变化
# ⚠️ 只在 WalkForwardFactorPipeline.run() 中被调用
# ⚠️ ScanPipeline 不调用此检测
```

---

## 2. 追踪路线 B: 从 K 线到撮合的断裂血脉

### 2.1 全链路数据形态转换图

```
═══════════════════════════════════════════════════════════════
  ZONE 1: BRAIN 引擎输出 (Dict[str, Any] 非标准化区域)
═══════════════════════════════════════════════════════════════

[Step 0] DataFetcher.get_price(symbol)
    输出: DF[date, open, high, low, close, volume, amount, ...]
    Index: RangeIndex
    ↓
[Step 1] AnalysisService._prepare_data_for_analysis(ticker)
    操作: data_service.fetch_for_brain(ticker)
    输出: data_pack = {
        "stock": DF[date, open, high, low, close, volume, ...],
        "symbol": str,
        "timestamp": str (ISO format),
    }
    类型: Dict[str, Any]
    ↓
[Step 2] AnalysisService._run_engine_analysis(ticker, data_pack)
    操作: 顺序调用 6 个引擎, 结果直接写入 data_pack dict

    ├── _run_regime_detection():
    │   输入: RegimeDetector.get_summary(HS300_df)  ← 注意: 用的是沪深300, 非个股
    │   输出 → data_pack["regime"] = str ("NORMAL"|"STRESSED"|"FROZEN")
    │   输出 → data_pack["entropy"] = float
    │   输出 → data_pack["turnover_z"] = float
    │   ⚠️ 市场级缓存: 同一日所有股票共享同一 regime
    │
    ├── _run_lppl_detection():
    │   输入: LpplAnalysisEngine.run_lppl_analysis(symbol, stock_df)
    │   内部: brain.lppl.engine.LPPLEngine.detect_bubble(df) → Dict
    │   输出 → data_pack["risk"] = str ("Safe"|"Warning"|"Danger")
    │   输出 → data_pack["bubble_confidence"] = float [0,1]
    │   ⚠️ LPPLEngine 内部: calculator.fit(df) → Dict[risk_level, confidence, votes]
    │   ⚠️ 服务层引擎提取 2 个 key, 丢弃 votes 等其他字段
    │
    ├── _run_ntf_detection():
    │   输入: NTFEngine.detect_intervention_from_data(fetcher, etf, start, end)
    │   输出 → data_pack["ntf_side"] = str ("NONE"|"SUPPORT"|"RESISTANCE")
    │   输出 → data_pack["ntf_intensity"] = float [0,1]
    │   输出 → data_pack["ntf_action"] = str
    │   ⚠️ 市场级缓存: 同一日所有股票共享同一 NTF 信号
    │
    ├── _run_czsc_detection():
    │   输入: CzscAnalysisEngine.run_czsc_analysis(symbol, stock_df)
    │   内部: brain.czsc.CZSCEngine.get_czsc_signals(df) → Dict
    │   输出 → data_pack["is_3rd_buy"] = bool
    │   输出 → data_pack["bi_count"] = int
    │   ⚠️ 服务层引擎提取 2 个 key, 丢弃 czsc_signal 等其他字段
    │
    ├── _run_wyckoff_detection():
    │   输入: WyckoffAnalysisEngine.run_wyckoff_analysis(symbol, stock_df)
    │   内部: brain.wyckoff.WyckoffEngine.analyze(df) → WyckoffReport (dataclass!)
    │   ⚠️ 类型断裂: WyckoffReport 是强类型 dataclass, 但被拆解为 Dict keys:
    │   输出 → data_pack["wyckoff_phase"] = str ("accumulation"|"distribution"|...)
    │   输出 → data_pack["wyckoff_confidence"] = float [0,1]
    │   输出 → data_pack["wyckoff_accumulation"] = float
    │   输出 → data_pack["wyckoff_distribution"] = float
    │   输出 → data_pack["wyckoff_spring"] = bool
    │   输出 → data_pack["wyckoff_utad"] = bool
    │   ⚠️ 丢弃: WyckoffReport.signal, .risk_reward, .trading_plan, .chip_analysis
    │   ⚠️ 信息损失: WyckoffPhase enum → str, ConfidenceLevel enum → float
    │
    └── _run_alpha_analysis():
        输入: AlphaDecoupler.get_alpha_score(stock_df, bench_df, sector_df)
        输出 → data_pack["alpha_score"] = float

[Step 2.5] AnalysisService 辅助计算
    ├── _calculate_ma_status():
    │   输出 → data_pack["ma_status"] = str ("MA20 > MA60"|"MA20 <= MA60")
    │   ⚠️ 硬编码 MA20/MA60, 不可配置
    │
    ├── _calculate_returns():
    │   输出 → data_pack["returns"] = Series[float] (pct_change().dropna())
    │   ⚠️ .dropna() 移除第一个值, 长度比 stock_df 少 1
    │
    ├── _calculate_price_and_stop():
    │   输出 → data_pack["price"] = float (最后一行 close)
    │   输出 → data_pack["atr_stop"] = float (price - ATR × 2)
    │
    └── _calculate_technical_indicators():
        输出 → data_pack["indicators"] = Dict[str, float]
        Keys: ma20, ma60, ema20, rsi, macd, macd_signal, macd_hist,
              atr, bollinger_upper, bollinger_middle, bollinger_lower,
              vol_ratio, market_entropy, turnover_z

[Step 3] data_pack 最终形态 (送入 DecisionBrain)
    Dict[str, Any] 包含:
    {
        "stock": DF,                    # 原始 K 线
        "symbol": str,                  # 股票代码
        "regime": str,                  # 市场状态
        "entropy": float,               # 市场熵
        "turnover_z": float,            # 换手率 Z-score
        "risk": str,                    # LPPL 风险等级
        "bubble_confidence": float,     # 泡沫置信度
        "ntf_side": str,                # 国家队方向
        "ntf_intensity": float,         # 国家队强度
        "ntf_action": str,              # 国家队动作
        "is_3rd_buy": bool,             # CZSC 三买
        "bi_count": int,                # CZSC 笔数
        "wyckoff_phase": str,           # Wyckoff 阶段
        "wyckoff_confidence": float,    # Wyckoff 置信度
        "wyckoff_accumulation": float,  # 吸筹分数
        "wyckoff_distribution": float,  # 派发分数
        "wyckoff_spring": bool,         # Spring 检测
        "wyckoff_utad": bool,           # UTAD 检测
        "alpha_score": float,           # Alpha 分离度
        "ma_status": str,               # 均线状态
        "returns": Series,              # 收益率序列
        "price": float,                 # 当前价格
        "atr_stop": float,              # ATR 止损
        "indicators": Dict,             # 技术指标
        "market": str,                  # "CN"
    }

> **Phase 4 类型管道 (可选)**: 受 `use_research_data_pack` 开关控制。
> 开启后 `AnalysisService._run_*` 将引擎输出存入 `ResearchDataPack.regime/.lppl/.czsc/.ntf/.wyckoff/.alpha` 字段,
> `data_pack.metadata` 持有平坦键 (供 `to_dict()` 展开后兼容下游信号收集器)。
> 4 个 AnalysisEngine (LPPL/CZSC/NTF/Wyckoff) 返回类型化输出 (`LPPLOutput`/`CZSCOutput`/`NtfOutput`/`WyckoffOutput`)。
> 默认关闭, Dict 路径完全不受影响。

═══════════════════════════════════════════════════════════════
  ZONE 2: 胶水代码 — Dict → MarketSignalContext 转换
═══════════════════════════════════════════════════════════════

[Step 4] DecisionBrain.make_decision(data_packet)
    操作: MarketSignalContext.from_dict(data_packet)

    映射表:
    ┌─────────────────────────┬──────────────────────────┬──────────────┐
    │ data_pack key           │ MarketSignalContext field │ 类型转换      │
    ├─────────────────────────┼──────────────────────────┼──────────────┤
    │ "regime"                │ regime: MarketRegime      │ str → Enum   │
    │ "risk"                  │ risk: str                 │ 直通          │
    │ "bubble_confidence"     │ bubble_confidence: float  │ 直通          │
    │ "ntf_side"              │ ntf_side: NtfSide         │ str → Enum   │
    │ "ntf_intensity"         │ ntf_intensity: float      │ 直通          │
    │ "is_3rd_buy"            │ is_3rd_buy: bool          │ 直通          │
    │ "bi_count"              │ bi_count: int             │ 直通          │
    │ "alpha_score"           │ alpha_score: float        │ 直通          │
    │ "ma_status"             │ ma_status: Optional[str]  │ 直通          │
    │ "price"                 │ price: float              │ 直通          │
    │ "symbol"                │ symbol: str               │ 直通          │
    │ "atr_stop"              │ atr_stop: float           │ 直通          │
    │ "market"                │ market: str               │ 直通          │
    │ "returns"               │ returns: Optional[Series] │ 直通          │
    ├─────────────────────────┼──────────────────────────┼──────────────┤
    │ ⚠️ "wyckoff_phase"      │ (未映射)                  │ 丢弃          │
    │ ⚠️ "wyckoff_confidence" │ (未映射)                  │ 丢弃          │
    │ ⚠️ "wyckoff_spring"     │ (未映射)                  │ 丢弃          │
    │ ⚠️ "wyckoff_utad"       │ (未映射)                  │ 丢弃          │
    │ ⚠️ "indicators"         │ (未映射)                  │ 丢弃          │
    │ ⚠️ "ntf_action"         │ (未映射)                  │ 丢弃          │
    │ ⚠️ "entropy"            │ (未映射)                  │ 丢弃          │
    │ ⚠️ "turnover_z"         │ (未映射)                  │ 丢弃          │
    └─────────────────────────┴──────────────────────────┴──────────────┘

    ⚠️ 信息丢失: Wyckoff 阶段、Spring/UTAD 检测、技术指标全部被丢弃
    ⚠️ MarketSignalContext.from_dict() 使用 try/except 容错:
        regime_str → MarketRegime(regime_str) 失败时 fallback to NORMAL

═══════════════════════════════════════════════════════════════
  ZONE 3: DecisionBrain 内部决策 → Dict 输出
═══════════════════════════════════════════════════════════════

[Step 5] DecisionBrain.make_decision() 内部
    操作:
    ├── _check_veto_conditions(ctx) → Optional[Dict]
    │   条件: regime=="FROZEN" → FORCE_WAIT
    │   条件: risk=="Danger" && ntf_side!="SUPPORT" → FORCE_EXIT
    │
    ├── _calculate_score(ctx) → int
    │   is_3rd_buy → +score
    │   ma_status → +score
    │   alpha_score > threshold → +score
    │   ntf_side == "SUPPORT" → +score
    │
    ├── _check_sell_conditions(ctx, score) → Optional[Dict]
    │
    └── _determine_target_state(score, is_3rd_buy) → FSMState
        → _execute_buy_logic(ctx, score) 或 _build_response()

    输出: Dict[str, Any] {
        "action": str,           # "BUY"|"SELL"|"HOLD"|"FORCE_WAIT"|"FORCE_EXIT"|"CIRCUIT_BREAK"
        "reason": str,
        "regime": str,
        "risk": str,
        "bubble_confidence": float,
        "ntf_side": str,
        "ntf_intensity": float,
        "is_3rd_buy": bool,
        "bi_count": int,
        "alpha_score": float,
        "final_decision": str,   # 与 action 相同或不同
        "final_score": int,
        "shares": int,           # 仅 BUY 时有值
        "state": str,            # FSM 状态
        "position_details": Dict, # 仓位计算详情 (仅 BUY)
    }

═══════════════════════════════════════════════════════════════
  🔴 断裂点: Brain Dict → TradingSignal 转换 (无自动化)
═══════════════════════════════════════════════════════════════

[Step 6] 🔴 当前无自动桥接
    TradingSignal.from_dict() 存在但未被调用!
    AnalysisService._make_decision() 返回 Dict → 直接存入 JSON 文件
    BacktestEngine.run_backtest() 接受 Callable[[DF, int, Dict], Dict] — 与 Brain 输出无关

═══════════════════════════════════════════════════════════════
  ZONE 4: BacktestEngine 独立回测路径 (与 Brain 完全解耦)
═══════════════════════════════════════════════════════════════

[Step 7] BacktestEngine.run_backtest(df, signal_generator)
    输入:
    - df: DF[date, open, high, low, close, volume, pre_close, avg_daily_volume]
    - signal_generator: Callable[[DF, int, Dict], Dict]
      签名: (df, idx, context) → {"action": "BUY"|"SELL"|"HOLD", "reason": str}
      context = {"position": int, "position_cost": float, "cash": float}

    信号生成:
    for idx in range(len(df)):
        signal = signal_generator(df, idx, {"position": ..., "position_cost": ..., "cash": ...})
        action = signal.get("action", "HOLD")

    ⚠️ 关键发现: BacktestEngine 不使用 Brain 的 DecisionBrain!
        它使用的是 hands/strategies/ 下的独立策略函数:
        - trade_wyckoff(df, as_of_date, ...) → Dict["ret", "days"]
        - trade_ma(df, as_of_date, ...) → Dict["ret", "days"]
        - trade_regime(df, as_of_date, ...) → Dict["ret", "days"]
        - trade_str_reversal(df, as_of_date, ...) → Dict["ret", "days"]

    ⚠️ 两套完全独立的决策体系:
    ┌──────────────────────────────────────────────────────────────┐
    │ 体系 A: AnalysisService → DecisionBrain → JSON 报告         │
    │   - 用于实盘分析和 UI 展示                                   │
    │   - 输出 Dict 存入文件                                       │
    │   - 不与 BacktestEngine 交互                                │
    ├──────────────────────────────────────────────────────────────┤
    │ 体系 B: hands/strategies → BacktestEngine → 统计报告         │
    │   - 用于历史回测                                             │
    │   - 策略函数直接访问 DataFrame, 独立计算                      │
    │   - 不使用 Brain 引擎输出                                    │
    └──────────────────────────────────────────────────────────────┘

[Step 8] BacktestEngine 内部数据流
    for idx in range(len(df)):
        # Step 8.1: 执行前一笔挂单
        if pending_order["action"] == "BUY":
            execute_buy(price=opens_arr[idx], shares=..., pre_close=pre_close_arr[idx], ...)
        elif pending_order["action"] == "SELL":
            execute_sell(price=opens_arr[idx], shares=..., buy_date=..., ...)

        # Step 8.2: 更新权益
        equity = cash + position * closes_arr[idx]

        # Step 8.3: 生成新信号
        signal = signal_generator(df, idx, {position, position_cost, cash})

        # Step 8.4: 下单 (T+0 信号, T+1 执行)
        if action == "BUY" and position == 0:
            pending_order = {"action": "BUY", "size": position_size, "reason": reason}
        elif action == "SELL" and position > 0:
            pending_order = {"action": "SELL", "size": position, "reason": reason, "buy_date": buy_date}

    输出: BacktestResult(initial_capital, trades, equity_curve, daily_returns, ...)
```

### 2.2 断裂点详细审计

#### 断裂点 1: Brain Engine → AnalysisService (信息丢失)

| 引擎 | 原始输出类型 | 服务层提取的 Key | 丢弃的信息 |
|------|-------------|-----------------|-----------|
| LPPLEngine | `Dict[risk_level, confidence, votes, ...]` | risk_level, confidence | votes, window, span, rmse, amplitude |
| CZSCEngine | `Dict[czsc_signal, is_3rd_buy, bi_count, ...]` | is_3rd_buy, bi_count | czsc_signal, 笔段详情 |
| WyckoffEngine | `WyckoffReport` (dataclass, 20+ fields) | phase, confidence, accumulation, distribution, spring, utad | signal, risk_reward, trading_plan, chip_analysis, limit_moves, stress_tests |
| RegimeDetector | `Dict[regime, entropy, turnover_z, ...]` | regime, entropy, turnover_z | 详细 regime 参数 |
| NTFEngine | `Dict[side, intensity, action, ...]` | side, intensity, action | 详细干预信号 |
| AlphaDecoupler | `float` | alpha_score | (无丢弃) |

#### 断裂点 2: data_pack → MarketSignalContext (字段未映射)

data_pack 有 **25+ 个 key**, MarketSignalContext 只映射了 **14 个**。以下字段被静默丢弃:
- `wyckoff_phase`, `wyckoff_confidence`, `wyckoff_spring`, `wyckoff_utad`
- `indicators` (14 个技术指标)
- `entropy`, `turnover_z`
- `ntf_action`

#### 断裂点 3: DecisionBrain → BacktestEngine (完全断裂)

```
DecisionBrain.make_decision() 输出 Dict[action, reason, shares, ...]
    ↓
    🔴 无消费者! 结果写入 JSON 文件, 不传给 BacktestEngine
    ↓
BacktestEngine 使用独立的策略函数:
    trade_wyckoff(df, as_of_date) → Dict[ret, days]
    trade_ma(df, as_of_date) → Dict[ret, days]
    ⚠️ 这些函数内部重新调用 WyckoffEngine, 重复计算!
```

#### 断裂点 4: signal 层 (已实现但未使用)

```
signal/normalizer.py: 4 个 Normalizer 已实现
signal/aggregator.py: 4 种聚合方法已实现
signal/quality.py: 质量评估器已实现
signal/db.py: 持久化已实现

🔴 当前唯一消费者: hands/backtest/signal_integrator.py
   但此模块未被任何主流程调用!
```

### 2.3 策略函数数据形态审计

#### trade_wyckoff(df, as_of_date, csi, ...) 

```
输入: DF[date, open, high, low, close, volume, ...] (全量历史)
      as_of_date: str ("YYYY-MM-DD")

内部操作:
1. av = df[df["date"] <= a]  — 截取截止日期前的数据
   ⚠️ 使用布尔索引, 创建视图 (非拷贝)

2. WyckoffEngine.analyze(av, symbol, period, multi_timeframe=True)
   输入: DF (截取后)
   输出: WyckoffReport (dataclass)

3. 从 WyckoffReport 提取:
   rpt.risk_reward.entry_price → we
   rpt.risk_reward.stop_loss → sl
   rpt.risk_reward.first_target → ft
   rpt.signal.signal_type → signal_type
   rpt.signal.spring_date → spring_date
   rpt.signal.confidence → ConfidenceLevel enum
   rpt.trading_plan.direction → direction

4. 置信度过滤:
   ConfidenceLevel[threshold] → enum 比较
   ⚠️ enum 比较使用 index 位置, 非 value

5. 模拟交易:
   f = df[df["date"] > a].head(mh)  — 未来数据 (前视!)
   逐 bar 遍历: 检查止损/止盈/时间止损
   ⚠️ 这是回测专用, 使用未来数据是预期行为

输出: Dict["ret": float, "days": int]
⚠️ 丢弃: WyckoffReport 的全部结构化信息
```

#### trade_ma(df, as_of_date, ...)

```
输入: DF[date, open, high, low, close, ...]

内部操作:
1. h = df[df["date"] <= a].tail(30) — 截取最近30天
2. mf = h.tail(5)["close"].mean() — 5日均线
3. ms = h.tail(20)["close"].mean() — 20日均线
4. 金叉检测: pf <= ps and mf > ms
5. 模拟交易: 遍历未来数据, 寻找死叉退出点

输出: Dict["ret": float, "days": int] 或 None
```

---

## 3. 暗箱操作清单

### 3.1 静默类型强转

| 位置 | 操作 | 风险 |
|------|------|------|
| `custom_factors.py` | `np.asarray(series, dtype=float)` | int/str 列被静默转为 NaN |
| `_zscore_frame` | `std.replace(0, np.nan)` | 0 方差因子 → NaN → fillna(0.0) |
| `MarketSignalContext.from_dict` | `MarketRegime(regime_str)` 失败 → NORMAL | 非法 regime 值被静默吞掉 |
| `TradingSignal.from_dict` | action_map.get(action, action) | 未知 action 值被直通 |

### 3.2 静默 NaN 丢弃

| 位置 | 操作 | 影响 |
|------|------|------|
| `compute_all_factors` | 因子长度不匹配 → `continue` | 某些股票某些因子静默缺失 |
| `_zscore_frame` | `fillna(0.0)` | 不足数据的因子值变为 0 |
| `_symmetric_orthogonalization` | `fillna(0.0)` | 正交化后 NaN 被归零 |
| `_calculate_returns` | `pct_change().dropna()` | 第一行收益率被丢弃 |
| `compute_rank_ic` | `dropna()` + `intersection()` | NaN 行被静默移除 |

### 3.3 前视偏差操作

| 位置 | 操作 | 安全性 |
|------|------|--------|
| `FactorAnalyzer._compute_forward_returns` | `shift(-holding_period)` | ⚠️ 仅限 mode="backtest", mode="live" 抛异常 |
| `FactorAnalyzer.compute_ic_ir` | `groupby(code)[price_col].shift(-period)` | ⚠️ 同上, 有 mode 保护 |
| `trade_wyckoff` | `df[df["date"] > a].head(mh)` | ✅ 回测专用, 预期行为 |
| `trade_ma` | `df[df["date"] > a]` | ✅ 回测专用 |
| `check_lookahead_leakage` | 扰动 `df[cutoff:]` 的 close | ✅ 检测工具, 非生产代码 |

### 3.4 Index 对齐风险

| 位置 | 操作 | 风险 |
|------|------|------|
| `_normalize_factors` | `pd.concat(parts).loc[factor_df.index]` | 如果 parts 的 index 有重复, loc 行为不可预测 |
| `compute_all_factors` | `factor_series.loc[group_df.index] = series.to_numpy()` | 如果 group_df.index 有重复, 赋值行为不确定 |
| `FinancialFactorBridge.calculate_pe_pb` | `merge_asof(tolerance="7D")` | 时间容差可能导致错误匹配 |

---

## 4. 断裂点缝合方案: Adapter Blueprint

### 4.1 设计目标

1. Brain 引擎输出 → 标准 `Signal` 对象 (自动归一化)
2. `Signal` → `TradingSignal` (自动映射, 零信息丢失)
3. `TradingSignal` → `BacktestEngine` (统一输入)
4. 消除两套并行决策体系

### 4.2 接口设计草案

```python
# === Layer: signal/adapters.py (新建) ===

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd

from .models import Signal, SignalSource, SignalStrength, SignalType


class EngineOutputAdapter(ABC):
    """
    Brain 引擎输出 → 标准 Signal 适配器基类
    
    职责: 将各引擎的 Dict[str, Any] 输出转换为标准 Signal 对象。
    每个 Brain 引擎对应一个 Adapter 实现。
    """
    
    @abstractmethod
    def adapt(self, raw_output: Dict[str, Any], symbol: str, 
              timestamp: Optional[Any] = None) -> Optional[Signal]:
        """
        将引擎原始输出转换为标准 Signal。
        
        Args:
            raw_output: 引擎输出的 Dict (如 LPPLEngine.detect_bubble 返回值)
            symbol: 证券代码
            timestamp: 信号时间戳 (默认 datetime.now())
            
        Returns:
            Signal 对象, 或 None (如果输出不构成有效信号)
        """
        ...
    
    def adapt_batch(self, raw_outputs: List[Dict[str, Any]], 
                    symbol: str) -> List[Signal]:
        """批量适配"""
        return [s for out in raw_outputs 
                if (s := self.adapt(out, symbol)) is not None]


class LPPLAdapter(EngineOutputAdapter):
    """LPPL 引擎输出适配器"""
    
    _RISK_DIRECTION = {"Safe": 0, "Warning": 1, "Danger": -1}
    _RISK_SIGNAL_TYPE = {
        "Safe": SignalType.TREND_NEUTRAL,
        "Warning": SignalType.LPPL_BUBBLE,
        "Danger": SignalType.LPPL_CRASH,
    }
    
    def adapt(self, raw_output: Dict[str, Any], symbol: str,
              timestamp: Optional[Any] = None) -> Optional[Signal]:
        risk_level = raw_output.get("risk_level", raw_output.get("risk", "Safe"))
        confidence = float(raw_output.get("confidence", 0.0))
        
        if confidence < 0.1:
            return None  # 低置信度不生成信号
        
        return Signal(
            signal_type=self._RISK_SIGNAL_TYPE.get(risk_level, SignalType.TREND_NEUTRAL),
            source=SignalSource.LPPL,
            symbol=symbol,
            direction=self._RISK_DIRECTION.get(risk_level, 0),
            strength=SignalStrength.STRONG if confidence > 0.7 else SignalStrength.MODERATE,
            confidence=confidence,
            timestamp=timestamp,
            metadata={
                "votes": raw_output.get("votes", 0),
                "window": raw_output.get("window"),
                "span": raw_output.get("span"),
                "rmse": raw_output.get("rmse"),
            },
        )


class WyckoffAdapter(EngineOutputAdapter):
    """Wyckoff 引擎输出适配器 — 直接消费 WyckoffReport dataclass"""
    
    _PHASE_DIRECTION = {
        "accumulation": 1, "spring": 1, "lps": 1,
        "distribution": -1, "utad": -1, "sow": -1,
    }
    _PHASE_SIGNAL_TYPE = {
        "accumulation": SignalType.WYCKOFF_ACCUMULATION,
        "distribution": SignalType.WYCKOFF_DISTRIBUTION,
        "spring": SignalType.WYCKOFF_SPRING,
        "utad": SignalType.WYCKOFF_UTAD,
        "lps": SignalType.WYCKOFF_LPS,
        "sow": SignalType.WYCKOFF_SOW,
    }
    
    def adapt_from_report(self, report: Any, symbol: str,
                          timestamp: Optional[Any] = None) -> Optional[Signal]:
        """直接从 WyckoffReport 适配 (推荐, 零信息丢失)"""
        if report.signal.signal_type == "no_signal":
            return None
        
        signal_type_str = report.signal.signal_type
        confidence_val = {
            "A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3
        }.get(report.signal.confidence.value, 0.3)
        
        return Signal(
            signal_type=self._PHASE_SIGNAL_TYPE.get(signal_type_str, SignalType.TREND_NEUTRAL),
            source=SignalSource.WYCKOFF,
            symbol=symbol,
            direction=self._PHASE_DIRECTION.get(signal_type_str, 0),
            strength=SignalStrength.STRONG if confidence_val > 0.7 else SignalStrength.MODERATE,
            confidence=confidence_val,
            timestamp=timestamp,
            metadata={
                "phase": report.structure.phase.value,
                "entry_price": report.risk_reward.entry_price,
                "stop_loss": report.risk_reward.stop_loss,
                "first_target": report.risk_reward.first_target,
                "reward_risk_ratio": report.risk_reward.reward_risk_ratio,
                "direction": report.trading_plan.direction,
                "spring_date": report.signal.spring_date,
            },
        )
    
    def adapt(self, raw_output: Dict[str, Any], symbol: str,
              timestamp: Optional[Any] = None) -> Optional[Signal]:
        """从 Dict 适配 (兼容模式, 有信息丢失)"""
        phase = raw_output.get("wyckoff_phase", raw_output.get("phase", "unknown"))
        confidence = float(raw_output.get("wyckoff_confidence", raw_output.get("confidence", 0.0)))
        
        if phase == "unknown" or confidence < 0.3:
            return None
        
        return Signal(
            signal_type=self._PHASE_SIGNAL_TYPE.get(phase, SignalType.TREND_NEUTRAL),
            source=SignalSource.WYCKOFF,
            symbol=symbol,
            direction=self._PHASE_DIRECTION.get(phase, 0),
            strength=SignalStrength.STRONG if confidence > 0.7 else SignalStrength.MODERATE,
            confidence=confidence,
            timestamp=timestamp,
            metadata={
                "accumulation_score": raw_output.get("wyckoff_accumulation", 0.0),
                "distribution_score": raw_output.get("wyckoff_distribution", 0.0),
                "spring_detected": raw_output.get("wyckoff_spring", False),
                "utad_detected": raw_output.get("wyckoff_utad", False),
            },
        )


class CZSCAdapter(EngineOutputAdapter):
    """CZSC 引擎输出适配器"""
    
    def adapt(self, raw_output: Dict[str, Any], symbol: str,
              timestamp: Optional[Any] = None) -> Optional[Signal]:
        is_3rd_buy = raw_output.get("is_3rd_buy", False)
        bi_count = raw_output.get("bi_count", 0)
        
        if not is_3rd_buy and bi_count == 0:
            return None
        
        direction = 1 if is_3rd_buy else 0
        confidence = min(0.5 + bi_count * 0.05, 0.9) if is_3rd_buy else 0.3
        
        return Signal(
            signal_type=SignalType.CZSC_ZHONGSHU_3RD if is_3rd_buy else SignalType.CZSC_BI_END,
            source=SignalSource.CZSC,
            symbol=symbol,
            direction=direction,
            strength=SignalStrength.STRONG if confidence > 0.7 else SignalStrength.MODERATE,
            confidence=confidence,
            timestamp=timestamp,
            metadata={"bi_count": bi_count},
        )


class RegimeAdapter(EngineOutputAdapter):
    """Regime 引擎输出适配器"""
    
    _REGIME_DIRECTION = {"NORMAL": 0, "STRESSED": -1, "FROZEN": 0}
    
    def adapt(self, raw_output: Dict[str, Any], symbol: str,
              timestamp: Optional[Any] = None) -> Optional[Signal]:
        regime = raw_output.get("regime", "NORMAL")
        
        return Signal(
            signal_type=SignalType.TREND_NEUTRAL,
            source=SignalSource.REGIME,
            symbol=symbol,
            direction=self._REGIME_DIRECTION.get(regime, 0),
            strength=SignalStrength.WEAK,
            confidence=0.5,
            timestamp=timestamp,
            metadata={
                "regime": regime,
                "entropy": raw_output.get("entropy", 0.0),
                "turnover_z": raw_output.get("turnover_z", 0.0),
            },
        )


# === 信号收集器 (Signal Collector) ===

class SignalCollector:
    """
    信号收集器 — 从 AnalysisService 的 data_pack 自动提取所有信号
    
    职责:
    1. 遍历所有 Adapter, 从 data_pack 中提取信号
    2. 返回 List[Signal] 供聚合器使用
    """
    
    def __init__(self):
        self._adapters: Dict[SignalSource, EngineOutputAdapter] = {}
    
    def register(self, source: SignalSource, adapter: EngineOutputAdapter) -> None:
        self._adapters[source] = adapter
    
    def collect_from_data_pack(self, data_pack: Dict[str, Any]) -> List[Signal]:
        """从 AnalysisService 的 data_pack 中收集所有信号"""
        signals: List[Signal] = []
        symbol = data_pack.get("symbol", "")
        timestamp = data_pack.get("timestamp")
        
        # LPPL
        if "risk" in data_pack:
            lppl_output = {
                "risk_level": data_pack["risk"],
                "confidence": data_pack.get("bubble_confidence", 0.0),
            }
            if (s := self._adapters.get(SignalSource.LPPL)):
                if (signal := s.adapt(lppl_output, symbol, timestamp)):
                    signals.append(signal)
        
        # Wyckoff
        if "wyckoff_phase" in data_pack:
            wyckoff_output = {
                "wyckoff_phase": data_pack["wyckoff_phase"],
                "wyckoff_confidence": data_pack.get("wyckoff_confidence", 0.0),
                "wyckoff_accumulation": data_pack.get("wyckoff_accumulation", 0.0),
                "wyckoff_distribution": data_pack.get("wyckoff_distribution", 0.0),
                "wyckoff_spring": data_pack.get("wyckoff_spring", False),
                "wyckoff_utad": data_pack.get("wyckoff_utad", False),
            }
            if (s := self._adapters.get(SignalSource.WYCKOFF)):
                if (signal := s.adapt(wyckoff_output, symbol, timestamp)):
                    signals.append(signal)
        
        # CZSC
        if "is_3rd_buy" in data_pack or "bi_count" in data_pack:
            czsc_output = {
                "is_3rd_buy": data_pack.get("is_3rd_buy", False),
                "bi_count": data_pack.get("bi_count", 0),
            }
            if (s := self._adapters.get(SignalSource.CZSC)):
                if (signal := s.adapt(czsc_output, symbol, timestamp)):
                    signals.append(signal)
        
        # Regime
        if "regime" in data_pack:
            regime_output = {
                "regime": data_pack["regime"],
                "entropy": data_pack.get("entropy", 0.0),
                "turnover_z": data_pack.get("turnover_z", 0.0),
            }
            if (s := self._adapters.get(SignalSource.REGIME)):
                if (signal := s.adapt(regime_output, symbol, timestamp)):
                    signals.append(signal)
        
        return signals


def create_default_collector() -> SignalCollector:
    """创建预配置的信号收集器"""
    collector = SignalCollector()
    collector.register(SignalSource.LPPL, LPPLAdapter())
    collector.register(SignalSource.WYCKOFF, WyckoffAdapter())
    collector.register(SignalSource.CZSC, CZSCAdapter())
    collector.register(SignalSource.REGIME, RegimeAdapter())
    return collector
```

### 4.3 集成方案: AnalysisService 改造

```python
# === 改造 AnalysisService.analyze_ticker() ===

def analyze_ticker(self, ticker: str) -> bool:
    data_pack = self._prepare_data_for_analysis(ticker)
    if data_pack is None:
        return False
    
    # Step 1: 运行引擎 (现有逻辑不变)
    if not self._run_engine_analysis(ticker, data_pack):
        return False
    
    # Step 2: 收集信号 (新增)
    from ..signal.adapters import create_default_collector
    collector = create_default_collector()
    signals = collector.collect_from_data_pack(data_pack)
    
    # Step 3: 聚合信号 (新增)
    from ..signal.aggregator import SignalAggregator
    aggregator = SignalAggregator()
    if signals:
        aggregated = aggregator.aggregate(signals)
        data_pack["aggregated_signal"] = aggregated
    
    # Step 4: DecisionBrain 决策 (现有逻辑不变)
    decision_result = self._make_decision(ticker, data_pack)
    
    # Step 5: 生成 TradingSignal (新增)
    from ..shared.interfaces import TradingSignal
    trading_signal = TradingSignal.from_dict(decision_result)
    
    # Step 6: 保存 + 报告 (现有逻辑不变)
    filepath = self._save_analysis_result(ticker, data_pack, decision_result)
    return self._generate_analysis_report(ticker, data_pack, decision_result, filepath)
```

### 4.4 统一回测方案 (长期目标)

```python
# === 目标: BacktestEngine 接受 TradingSignal 输入 ===

class UnifiedBacktestEngine:
    """统一回测引擎 — 接受 TradingSignal 而非 Callable"""
    
    def run_backtest(
        self,
        df: pd.DataFrame,
        signals: List[TradingSignal],  # ← 替代 signal_generator
        symbol: str = "",
    ) -> BacktestResult:
        """
        使用预生成的 TradingSignal 列表进行回测。
        
        信号生成与回测撮合完全解耦:
        1. 信号生成: AnalysisService → SignalCollector → Aggregator → TradingSignal
        2. 回测撮合: UnifiedBacktestEngine.run_backtest(df, signals)
        """
        signal_map: Dict[str, TradingSignal] = {}
        for sig in signals:
            # 按日期索引信号
            key = sig.timestamp.strftime("%Y-%m-%d") if hasattr(sig, "timestamp") else ""
            signal_map[key] = sig
        
        for idx in range(len(df)):
            date_key = pd.Timestamp(df.iloc[idx]["date"]).strftime("%Y-%m-%d")
            signal = signal_map.get(date_key)
            
            if signal is None:
                self.update_equity(df.iloc[idx]["close"])
                continue
            
            if signal.action == "BUY" and self.position == 0:
                self.execute_buy(
                    price=signal.price or df.iloc[idx]["close"],
                    shares=signal.shares or 100,
                    timestamp=pd.Timestamp(df.iloc[idx]["date"]),
                    reason=signal.reason,
                )
            elif signal.action == "SELL" and self.position > 0:
                self.execute_sell(
                    price=signal.price or df.iloc[idx]["close"],
                    shares=self.position,
                    timestamp=pd.Timestamp(df.iloc[idx]["date"]),
                    reason=signal.reason,
                )
            
            self.update_equity(df.iloc[idx]["close"])
        
        return BacktestResult(...)
```

---

## 5. 架构改造路线图

```
Phase 0 (当前): 两套并行决策体系, 手动胶水
    ↓
Phase 1: 实现 signal/adapters.py (4 个 Adapter + SignalCollector)
    ↓
Phase 2: 改造 AnalysisService, 集成 SignalCollector → Aggregator
    ↓
Phase 3: 实现 UnifiedBacktestEngine, 接受 List[TradingSignal]
    ↓
Phase 4: 废弃 hands/strategies/ 旧策略函数, 统一到 signal 层
```

---

*生成时间: 2026-06-07 | 基于源码逐行追踪, 禁止幻觉*
