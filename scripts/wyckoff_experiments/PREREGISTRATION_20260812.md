# Phase 2 预注册阈值 — Wyckoff Deep-Dive (2026-08-12)

> 运行前固化判定标准。运行后数据原样呈现，不得事后选择性报告。
> 判定语言：达标（PASS）/ 未达标（FAIL）/ 仅报告（INFO）。

## 数据窗口
- 已有：W1(2026-04-30)、W2(2026-03-31)、W3(2026-05-29)，CSV 在 results/wyckoff_xs{,2,3}
- 已有老窗：X4(2025-06-30)、X5(2024-12-31) — 每窗 fwd_20d+fwd_60d 均可用（湖止 2026-07-23）
- **2026-08-18 净化口径**：`all` 池 5755 → **5201**（剔 554 指数，符号级 `_is_index`：SH 000xxx/399xxx）；每窗 **5201 行×39 列**（旧 5755 备份 /tmp/opencode/wyckoff_fix/old_scans_p0/）。统计用 n（fwd_20d 非空）见 T1 实测：4762/4773/4766/4719/4670
- clean 池口径：fwd_20d 非空 ∩ 剔 ETF(is_etf=False)
- **幸存者偏置定量披露（2026-08-18 核验，type=1 纯股票口径）**：

| 窗口 | 历史股票在市(含退市, all_stock_codes type=1) | 湖内扫描成功 | 覆盖率 |
|---|---|---|---|
| W1 2026-04-30 | 5201 | 5196 | 0.999 |
| W2 2026-03-31 | 5193 | 5194 | 1.000 |
| W3 2026-05-29 | 5208 | 5201 | 0.999 |
| X4 2025-06-30 | 5152 | 5194 | 1.008 |
| X5 2024-12-31 | 5122 | 5190 | 1.013 |

  > 每窗覆盖率 ≈ 1.0 → **幸存者偏置影响 ~0.3%**（全部退市股票 337 只不在湖内，但对历史在市分母占比 <1%）。此前按全表(含基金/转债/指数)口径的 0.73-0.78 为假偏置。>1.0 系扫描池含少量 ETF(is_etf=True)所致。
  > 结论降权依据：绿区(<±1%)，无需降权。

## 通用统计协定
- 剔尾：|fwd_20d| ≤ 10%（方案 F7 同口径）
- 显著性：Mann-Whitney U 双侧；升级判断用单侧 p<0.05
- 预注册升级门槛（方案红线）：**剔尾后 ≥2/3 窗 MWU p<0.05 且方向与主张一致 → 才允许把某标签升为方向依据**；否则只作叙事/风控

## 各检验预注册判定

### T1 direction_map_check.py（P2-2A 确定性断言，非统计）
- P0-2 映射：`trading_plan_direction ∈ {做多,买入,轻仓试探}` → BUY；其余 → None（不产 SELL）
- 断言1：每窗 BUY 数 > 0 —— FAIL ⇔ 0
- 断言2：每窗 SELL 数 == 0（映射本身 0 产 SELL）—— FAIL ⇔ >0
- 断言3（覆盖率，INFO）：BUY 数 / clean 池非空仓观望数
- 断言4（P0-4 门槛漂移，INFO）：conf≥0.30 vs conf≥0.40 的 BUY 集变化（增减比例）

### T2 confidence_survival.py（P2-2C markup 存活表）
- markup 信号按 confidence_level(A/B/C/D) × fwd_20d/fwd_60d 超额，剔尾前后各一份
- 判定仅 INFO（供 P0-4 定门槛）；n<30 桶标记"统计力不足"，不参与判定
- 若桶剔尾后 ≥2/3 窗单侧 MWU p<0.05 且超额同号 → 标记"升级候选"（走对抗裁定，不直接采纳）

### T3 buyset_momentum_residual.py（P2-3 BUY 集独立增量判定）
- BUY 集 = direction∈{做多,买入,轻仓试探} ∩ conf≥0.40 ∩ clean 池
- M1 分位残差（relmom 10 分位桶内 BUY vs 非 BUY）、M2 OLS 残差、R3 剔右尾（剔 relmom>P90）后 M2
- PASS(有独立增量) ⇔ 剔右尾后 ≥2/3 窗 M2 单侧 MWU p<0.05 且 M2 均值>0
- FAIL(无独立增量，维持"叙事层"裁决) ⇔ 否则；预期：BUY=追涨动量+右尾（P2-3 预注册陈述）

### T4 atr_trigger_diff.py（P1-1 before-after 触发集对照）
- A=现状 `_scan_spring`（固定 [0.985,1.0)×boundary_lower 深带）；B=方案 minBreak=max(atr*0.25, rangeWidth*2%)
- 每 golden_100 标的 as-of 窗计算 A/B 触发集；漂移率 = |AΔB| / max(|A|,|B|)
- 预注册（方案红线）：**漂移率 >5% → 撤回 P1-1 或升级为 P0 独立验证**；≤5% → 采纳

### T5 stoploss_exit_check.py（P1-11 退出层触发率，golden_100）
- 实现 proposed `_stop_loss_trigger`：节后宽限期（相邻日 gap≥3 自然日）；缩量洗盘（量比<0.8 且跌幅<2%→不触发）；深度破位（≤止损价 0.95 → 短路触发）
- 指标：触发率（触发标的/样本）、误杀率（触发后 5 日内收回至 stop_loss_price 之上）
- PASS ⇔ 触发率 ≤30% 且 误杀率 ≤50%；FAIL ⇔ 否则（过度触发→修改）

## 运行顺序
1. T1-T3 用现有三窗 → 老窗补算后 X4/X5 复跑
2. T4/T5 在 golden_100 上 run（golden_20 先冒烟）
3. 每个脚本固定 seed=42，输出 JSON 留档 results/wyckoff_experiments/
