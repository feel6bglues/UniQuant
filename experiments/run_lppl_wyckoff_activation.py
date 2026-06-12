"""
Phase 3: LPPL 与 Wyckoff 引擎深度唤醒 (Deep Engine Activation)
===============================================================

目标:
  1. LPPL: 提取连续"崩溃概率" (Crash Probability, 0~1)
  2. Wyckoff: 提取连续"吸筹置信度" (0~1) 和"派发置信度" (-1~0)
  3. 回测它们对 10d/20d 绝对收益的预测能力

方法:
  - 在含人造泡沫/吸筹模式的合成指数数据上验证
  - LPPL: 使用 rolling window 拟合 + 连续概率转换
  - Wyckoff: 使用简化量价分析提取连续分数

[Halt & Wait]
"""

import os, sys
from pathlib import Path
os.environ["PYTHONWARNINGS"] = "ignore"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# =========================================================================
# 1. 合成市场指数数据 (含人造泡沫 + 吸筹模式)
# =========================================================================

def generate_market_data_with_bubbles(seed: int = 42) -> pd.DataFrame:
    """
    生成含已知泡沫/崩盘特征的合成市场指数。

    结构:
      Phase A (2018-01 ~ 2019-12): 缓慢上升 30% (~正常牛市)
      Phase B (2020-01 ~ 2021-02): LPPL 泡沫加速 120%
      Phase C (2021-03 ~ 2022-10): 崩盘 -45%
      Phase D (2022-11 ~ 2024-01): 底部震荡吸筹
      Phase E (2024-02 ~ 2025-01): 缓慢回升 25%
    """
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2018-01-01", end="2025-03-31")
    n = len(dates)
    price = np.zeros(n)
    price[0] = 3500.0  # CSI 300-like starting point

    # Phase definitions: (start_idx, end_idx, annualized_return, volatility)
    phases = [
        (0, n//5*1, 0.12, 0.18),       # Slow rise
        (n//5*1, n//5*2, 0.60, 0.22),   # LPPL bubble acceleration
        (n//5*2, n//5*3, -0.60, 0.35),  # Crash
        (n//5*3, n//5*4, -0.02, 0.15),  # Bottom accumulation
        (n//5*4, n, 0.15, 0.18),        # Recovery
    ]

    for idx, (s, e, ann_ret, vol) in enumerate(phases):
        n_days = e - s
        daily_mu = ann_ret / 252
        daily_vol = vol / np.sqrt(252)

        if idx == 1:  # LPPL bubble
            t = np.arange(n_days) / n_days
            bubble_mu = daily_mu + 0.008 * t**3 / 3
            rets = rng.normal(bubble_mu, daily_vol)
        elif idx == 2:  # Crash
            t = np.arange(n_days) / n_days
            crash_mu = daily_mu - 0.015 * np.exp(3 * t)
            rets = rng.normal(crash_mu, daily_vol * 1.5)
        elif idx == 3:  # Accumulation
            rets = rng.normal(daily_mu, daily_vol * 0.8, n_days)
        else:
            rets = rng.normal(daily_mu, daily_vol, n_days)

        for i in range(n_days):
            if s + i > 0:
                price[s + i] = max(price[s + i - 1] * (1 + rets[i]), 500.0)

    # Volume: higher during bubble and crash, lower during accumulation
    volume = np.zeros(n)
    for i in range(n):
        phase_idx = sum(1 for p in phases if i >= p[1]) if i >= phases[-1][3] else next(p_idx for p_idx, (s, e, _, _) in enumerate(phases) if s <= i < e)
        # Simple phase-based volume
        base_vol = 1e9
        if i < n//5*1: vol_factor = 1.0
        elif i < n//5*2: vol_factor = 1.5 + 0.5 * (i - n//5*1) / (n//5)  # rising
        elif i < n//5*3: vol_factor = 2.5  # panic
        elif i < n//5*4: vol_factor = 0.6  # low
        else: vol_factor = 1.0
        volume[i] = max(1, int(base_vol * vol_factor * (1 + rng.normal(0, 0.15))))

    df = pd.DataFrame({
        "date": dates,
        "close": np.round(price, 2),
        "open": np.round(price * (1 + rng.normal(0, 0.003, n)), 2),
        "high": np.round(price * (1 + abs(rng.normal(0, 0.005, n))), 2),
        "low": np.round(price * (1 - abs(rng.normal(0, 0.005, n))), 2),
        "volume": volume,
    })
    df["amount"] = df["volume"] * df["close"]

    print(f"  [指数] {len(df)} 个交易日, {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"    价格: {df['close'].iloc[0]:.0f} → {df['close'].iloc[-1]:.0f}")
    print(f"    最大回撤: {(df['close'].min() / df['close'].iloc[0] - 1):.1%}")
    return df


# =========================================================================
# 2. 连续 LPPL 崩溃概率提取器
# =========================================================================

def compute_lppl_crash_prob(
    prices: np.ndarray,
    window: int = 120,
    min_window: int = 60,
) -> np.ndarray:
    """
    滚动窗口 LPPL 崩溃概率 [0, 1]。

    使用简化 LPPL 拟合: 对每个时间窗口,
    用抛物线近似代替 DE 优化的 LPPL 模型。
    当价格呈超指数增长时, crash_prob 升高。

    对于每个窗口:
      - 计算 price 与抛物线 + 对数周期性振动的拟合度
      - 拟合度越高 → crash_prob 越高
      - 距离窗口末端的加速度越强 → crash_prob 越高
    """
    n = len(prices)
    crash_prob = np.zeros(n)
    log_prices = np.log(prices)

    for t in range(min_window, n):
        s = max(0, t - window)
        seg = log_prices[s:t]
        seg_len = len(seg)

        if seg_len < min_window:
            continue

        x = np.arange(seg_len, dtype=float)
        x_norm = x / max(seg_len - 1, 1)

        # LPPL-inspired: fit quadratic (super-exponential)
        X = np.column_stack([np.ones(seg_len), x_norm, x_norm**2])
        try:
            coeffs = np.linalg.lstsq(X, seg, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue

        # Quadratic coefficient > 0 means accelerating growth
        quad_coeff = coeffs[2]

        # Fit quality (R²)
        pred = X @ coeffs
        ss_res = np.sum((seg - pred)**2)
        ss_tot = np.sum((seg - np.mean(seg))**2)
        r2 = 1 - ss_res / max(ss_tot, 1e-10)

        # Log-periodic oscillation detection: look at residuals pattern
        residuals = seg - pred
        # FFT to check for periodic component
        fft = np.abs(np.fft.rfft(residuals))
        if len(fft) > 3:
            peak_idx = np.argmax(fft[1:]) + 1  # skip DC
            if peak_idx < len(fft) - 1:
                # Ratio of dominant frequency power to total
                periodic_ratio = fft[peak_idx] / max(np.sum(fft[1:]), 1e-10)
            else:
                periodic_ratio = 0
        else:
            periodic_ratio = 0

        # Crash probability = acceleration × fit quality × log-periodic signal
        accel_signal = np.clip(quad_coeff * 100, 0, 1)  # normalized acceleration
        prob = accel_signal * r2 * (0.5 + 0.5 * periodic_ratio)
        crash_prob[t] = np.clip(prob, 0, 1)

    return crash_prob


def compute_lppl_bottom_prob(
    prices: np.ndarray,
    window: int = 120,
    min_window: int = 60,
) -> np.ndarray:
    """
    滚动窗口 LPPL 底部反转概率 [0, 1]。

    类似于 crash_prob 但检测负泡沫 (加速下跌后的反弹)。
    """
    # Same logic, but on negated log returns = detect crash then reversal
    neg_prices = -prices + 2 * prices[-1]
    inv_prob = compute_lppl_crash_prob(neg_prices, window, min_window)
    return inv_prob


# =========================================================================
# 3. 连续 Wyckoff 分数提取器
# =========================================================================

def compute_wyckoff_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    提取连续 Wyckoff 分数。

    Accumulation Score [0, 1]:
      - 计算 TR (交易区间) 边界
      - 检测弹簧 (Spring) = 价格跌破 TR 下界后快速收回
      - 检测底部放量 = 价格在低位时成交量放大
      - 综合 → 吸筹置信度

    Distribution Score [-1, 0]:
      - 检测 UTAD (派发) = 价格突破 TR 上界后无力维持
      - 检测顶部放量滞涨
      - 综合 → 派发置信度
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    date = df["date"].values
    n = len(close)

    # Rolling TR boundaries (60-day)
    tr_window = 60
    tr_high = pd.Series(high).rolling(tr_window).max().values
    tr_low = pd.Series(low).rolling(tr_window).min().values
    tr_mid = (tr_high + tr_low) / 2

    # Volume Z-score (30-day rolling)
    vol_ma = pd.Series(volume).rolling(30).mean().values
    vol_std = pd.Series(volume).rolling(30).std().values

    # Price position in TR
    price_pos = np.full(n, np.nan)
    for i in range(tr_window, n):
        tr_range = tr_high[i] - tr_low[i]
        if tr_range > 0:
            price_pos[i] = (close[i] - tr_low[i]) / tr_range

    # Trend: 20-day MA slope
    ma20 = pd.Series(close).rolling(20).mean().values
    ma_slope = np.full(n, np.nan)
    for i in range(21, n):
        ma_slope[i] = (ma20[i] - ma20[i-20]) / max(ma20[i-20], 1)

    # Accumulation score
    acc_score = np.zeros(n)
    dist_score = np.zeros(n)

    for i in range(tr_window + 20, n):
        # ---- Accumulation signals ----

        # 1. Spring detection: price dips below TR low then recovers
        lookback = 30
        spring_signal = 0
        if i >= lookback * 2:
            recent_low = np.min(low[max(0, i-lookback):i+1])
            prev_low = np.min(low[max(0, i-lookback*2):i-lookback])
            if low[i] <= tr_low[i] * 1.01:  # near TR low
                # Check for bounce
                future_idx = min(i + 5, n - 1)
                if close[min(i+3, n-1)] > low[i] * 1.01:
                    spring_signal = 1

        # 2. Volume surge at low: accumulation volume
        vol_surge_low = 0
        if i >= 30 and not np.isnan(vol_std[i]) and vol_std[i] > 0:
            vol_z = (volume[i] - vol_ma[i]) / max(vol_std[i], 1)
            if vol_z > 1.5 and price_pos[i] < 0.3:
                vol_surge_low = min(1, (vol_z - 1.5) / 3)

        # 3. Decreasing volume on dips (selling climax → absorption)
        vol_climax = 0
        lookback_20 = 20
        if i >= lookback_20 * 2:
            recent_vol = np.mean(volume[i-lookback_20:i])
            older_vol = np.mean(volume[i-lookback_20*2:i-lookback_20])
            if recent_vol < older_vol * 0.8 and price_pos[i] < 0.4:
                vol_climax = 0.5

        # 4. MA slope turning up (from low base)
        trend_turn = 0
        if i >= 40 and not np.isnan(ma_slope[i]) and not np.isnan(ma_slope[i-20]):
            if ma_slope[i] > 0 and ma_slope[i-20] < 0 and price_pos[i] < 0.5:
                trend_turn = 0.7

        acc_score[i] = np.clip(
            0.3 * spring_signal +
            0.3 * vol_surge_low +
            0.2 * vol_climax +
            0.2 * trend_turn, 0, 1
        )

        # ---- Distribution signals ----

        # 1. UTAD-like: price pushes above TR high then fails
        utad_signal = 0
        if high[i] >= tr_high[i] * 0.99:
            future_idx = min(i + 5, n - 1)
            if close[future_idx] < high[i] * 0.98:
                utad_signal = 0.8

        # 2. Volume surge at high: distribution
        vol_surge_high = 0
        if i >= 30 and not np.isnan(vol_std[i]) and vol_std[i] > 0:
            vol_z = (volume[i] - vol_ma[i]) / max(vol_std[i], 1)
            if vol_z > 1.5 and price_pos[i] > 0.7:
                # Check if close is weak (small gain or loss on high volume)
                daily_ret = close[i] / max(close[i-1], 1) - 1
                if daily_ret < 0.01:  # not strong up on this volume
                    vol_surge_high = min(1, (vol_z - 1.5) / 3)

        # 3. Price-Volume divergence: price high but volume decreasing
        pv_div = 0
        if i >= 20 and price_pos[i] > 0.7:
            recent_vol_chg = volume[i] / max(np.mean(volume[i-10:i]), 1) - 1
            recent_price_chg = close[i] / max(close[i-10], 1) - 1
            if recent_price_chg > 0.02 and recent_vol_chg < -0.1:
                pv_div = 0.6

        # 4. MA slope topping
        trend_top = 0
        if i >= 40 and not np.isnan(ma_slope[i]) and not np.isnan(ma_slope[i-20]):
            if ma_slope[i] < 0 and ma_slope[i-20] > 0 and price_pos[i] > 0.5:
                trend_top = 0.7

        raw_dist = (
            0.3 * utad_signal +
            0.3 * vol_surge_high +
            0.2 * pv_div +
            0.2 * trend_top
        )
        dist_score[i] = np.clip(-raw_dist, -1, 0)

    result = pd.DataFrame({
        "date": date,
        "close": close,
        "acc_score": acc_score,
        "dist_score": dist_score,
        "price_pos": price_pos,
    })
    return result


# =========================================================================
# 4. 预测力回测
# =========================================================================

def evaluate_predictive_power(
    df: pd.DataFrame,
    score_name: str,
    scores: np.ndarray,
    holding_periods: list = [10, 20],
) -> dict:
    """
    评估分数对未来绝对收益的预测力。

    使用 Spearman Rank IC 和方向准确率。
    """
    from scipy import stats

    results = {}
    close = df["close"].values
    n = len(close)

    for hp in holding_periods:
        # Forward returns
        fwd_rets = np.full(n, np.nan)
        for i in range(n - hp):
            fwd_rets[i] = close[i + hp] / close[i] - 1

        valid = ~(np.isnan(scores) | np.isnan(fwd_rets))
        s = scores[valid]
        r = fwd_rets[valid]

        if len(s) < 30:
            results[f"IC@{hp}d"] = 0
            results[f"Accuracy@{hp}d"] = 0
            continue

        # Rank IC
        ic, _ = stats.spearmanr(s, r)

        # Direction accuracy
        correct = np.mean((s > np.median(s)) == (r > np.median(r)))
        # Also: long-only when score > threshold
        threshold = np.percentile(s, 70)
        long_mask = s > threshold
        if np.sum(long_mask) > 5:
            long_ret = np.mean(r[long_mask])
        else:
            long_ret = 0

        results[f"IC@{hp}d"] = float(ic) if not np.isnan(ic) else 0
        results[f"Accuracy@{hp}d"] = float(correct)
        results[f"LongRet@{hp}d"] = float(long_ret)

    return results


def main():
    print("=" * 70)
    print("  Phase 3: LPPL 与 Wyckoff 引擎深度唤醒")
    print("  Deep Engine Activation — Continuous Score Extraction")
    print("=" * 70)

    # ---- 1. 数据 ----
    print("\n[1/4] 生成含泡沫/吸筹模式的合成指数数据...")
    df = generate_market_data_with_bubbles()
    prices = df["close"].values

    # ---- 2. LPPL 连续概率 ----
    print("\n[2/4] 提取 LPPL 连续崩溃概率...")
    lppl_crash = compute_lppl_crash_prob(prices, window=120, min_window=60)
    lppl_bottom = compute_lppl_bottom_prob(prices, window=120, min_window=60)

    df["lppl_crash_prob"] = lppl_crash
    df["lppl_bottom_prob"] = lppl_bottom

    # 信号在关键时间点
    key_dates = {
        "2020-06": "泡沫加速期",
        "2021-02": "泡沫顶点",
        "2021-07": "崩盘中期",
        "2022-10": "底部区域",
        "2023-06": "吸筹期",
    }
    print("\n  LPPL 信号在关键时间点的分布:")
    print(f"  {'日期':<12} {'标签':<12} {'Crash Prob':>12} {'Bottom Prob':>12}")
    print(f"  {'-'*48}")
    for dt_str, label in key_dates.items():
        mask = df["date"].astype(str).str.startswith(dt_str)
        subset = df[mask]
        if not subset.empty:
            row = subset.iloc[0]
            print(f"  {dt_str:<12} {label:<12} {row['lppl_crash_prob']:>12.4f} {row['lppl_bottom_prob']:>12.4f}")

    # Crash prob statistics during different phases
    print("\n  LPPL Crash Prob 按阶段统计:")
    n = len(df)
    for phase_name, s, e in [
        ("正常上升", 0, n//5*1),
        ("泡沫加速", n//5*1, n//5*2),
        ("崩盘", n//5*2, n//5*3),
        ("底部吸筹", n//5*3, n//5*4),
        ("回升", n//5*4, n),
    ]:
        cp = lppl_crash[s:e]
        bp = lppl_bottom[s:e]
        print(f"    {phase_name:<10} crash={np.mean(cp):.4f}±{np.std(cp):.4f}  bottom={np.mean(bp):.4f}±{np.std(bp):.4f}")

    # ---- 3. Wyckoff 连续分数 ----
    print("\n[3/4] 提取 Wyckoff 连续吸筹/派发分数...")
    wyckoff = compute_wyckoff_scores(df)
    df["acc_score"] = wyckoff["acc_score"].values
    df["dist_score"] = wyckoff["dist_score"].values
    df["price_pos"] = wyckoff["price_pos"].values

    print("\n  Wyckoff 信号在关键时间点的分布:")
    print(f"  {'日期':<12} {'标签':<12} {'Accum':>8} {'Dist':>8} {'PricePos':>10}")
    print(f"  {'-'*50}")
    for dt_str, label in key_dates.items():
        mask = df["date"].astype(str).str.startswith(dt_str)
        subset = df[mask]
        if not subset.empty:
            row = subset.iloc[0]
            print(f"  {dt_str:<12} {label:<12} {row['acc_score']:>8.4f} {row['dist_score']:>8.4f} {row['price_pos']:>10.4f}")

    print("\n  Wyckoff 分数按阶段统计:")
    for phase_name, s, e in [
        ("正常上升", 0, n//5*1),
        ("泡沫加速", n//5*1, n//5*2),
        ("崩盘", n//5*2, n//5*3),
        ("底部吸筹", n//5*3, n//5*4),
        ("回升", n//5*4, n),
    ]:
        ac = wyckoff["acc_score"].values[s:e]
        dc = wyckoff["dist_score"].values[s:e]
        nz_ac = ac[ac > 0]
        nz_dc = dc[dc < 0]
        ac_str = f"μ={np.mean(ac):.3f}" + (f" signal={len(nz_ac)}d" if len(nz_ac) > 0 else "")
        dc_str = f"μ={np.mean(dc):.3f}" + (f" signal={len(nz_dc)}d" if len(nz_dc) > 0 else "")
        print(f"    {phase_name:<10}  acc: {ac_str}  dist: {dc_str}")

    # ---- 4. 预测力回测 ----
    print("\n[4/4] 预测力评估 (10d/20d 绝对收益)...")
    print(f"  {'信号':<20} {'IC@10d':>8} {'IC@20d':>8} {'Acc@10d':>8} {'Acc@20d':>8}")
    print(f"  {'-'*52}")

    all_results = {}
    for name, series in [
        ("LPPL Crash Prob", df["lppl_crash_prob"].values),
        ("LPPL Bottom Prob", df["lppl_bottom_prob"].values),
        ("Wyckoff Accum", df["acc_score"].values),
        ("Wyckoff Dist", df["dist_score"].values),
    ]:
        res = evaluate_predictive_power(df, name, series, holding_periods=[10, 20])
        all_results[name] = res
        print(f"  {name:<20} {res['IC@10d']:>+8.4f} {res['IC@20d']:>+8.4f} "
              f"{res['Accuracy@10d']:>8.1%} {res['Accuracy@20d']:>8.1%}")

    # ---- 生成报告 ----
    report_path = Path("docs/reshaping_logs/02_lppl_wyckoff_activation.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 02 — LPPL & Wyckoff 连续分数提取与回测\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **数据**: 合成指数, {len(df)} 个交易日\n\n")

        f.write("## LPPL 连续崩溃概率\n\n")
        f.write("### 设计\n\n")
        f.write("使用 120 天滚动窗口拟合抛物线 + 对数周期振动:\n")
        f.write("- **加速系数**: 二次项系数 → 超指数增长度量\n")
        f.write("- **拟合质量**: R² 衡量模型解释力\n")
        f.write("- **周期分量**: FFT 残差频谱分析 → 对数周期振荡检测\n\n")

        f.write("### 按阶段统计\n\n")
        f.write("| 阶段 | Crash Prob μ±σ | Bottom Prob μ±σ |\n")
        f.write("|------|-----------------|------------------|\n")
        for phase_name, s, e in [
            ("正常上升", 0, n//5*1), ("泡沫加速", n//5*1, n//5*2),
            ("崩盘", n//5*2, n//5*3), ("底部吸筹", n//5*3, n//5*4),
            ("回升", n//5*4, n),
        ]:
            f.write(f"| {phase_name} | {np.mean(lppl_crash[s:e]):.4f}±{np.std(lppl_crash[s:e]):.4f} | {np.mean(lppl_bottom[s:e]):.4f}±{np.std(lppl_bottom[s:e]):.4f} |\n")

        f.write("\n### 关键时间点\n\n")
        f.write("| 日期 | 标签 | Crash Prob | Bottom Prob |\n")
        f.write("|------|------|------------|-------------|\n")
        for dt_str, label in key_dates.items():
            row = df[df["date"].astype(str).str.startswith(dt_str)].iloc[0]
            f.write(f"| {dt_str} | {label} | {row['lppl_crash_prob']:.4f} | {row['lppl_bottom_prob']:.4f} |\n")

        f.write("\n## Wyckoff 连续分数\n\n")
        f.write("### 设计\n\n")
        f.write("**吸筹置信度 [0, 1]**:\n")
        f.write("- Spring 检测: 价格跌破 TR 下界后收回 (30%)\n")
        f.write("- 底部放量: 低位成交量激增 (30%)\n")
        f.write("- 缩量回调: 抛售高潮后成交量萎缩 (20%)\n")
        f.write("- 趋势扭转: MA 斜率由负转正 (20%)\n\n")
        f.write("**派发置信度 [-1, 0]**:\n")
        f.write("- UTAD: 价格突破 TR 上界后无力上涨 (30%)\n")
        f.write("- 高位放量滞涨: 高成交量下价格不涨 (30%)\n")
        f.write("- 量价背离: 价格创新高但成交量萎缩 (20%)\n")
        f.write("- 趋势见顶: MA 斜率由正转负 (20%)\n\n")

        f.write("### 按阶段统计\n\n")
        f.write("| 阶段 | Accum μ | Acc Signal Days | Dist μ | Dist Signal Days |\n")
        f.write("|------|---------|----------------|--------|-----------------|\n")
        for phase_name, s, e in [
            ("正常上升", 0, n//5*1), ("泡沫加速", n//5*1, n//5*2),
            ("崩盘", n//5*2, n//5*3), ("底部吸筹", n//5*3, n//5*4),
            ("回升", n//5*4, n),
        ]:
            ac = wyckoff["acc_score"].values[s:e]
            dc = wyckoff["dist_score"].values[s:e]
            f.write(f"| {phase_name} | {np.mean(ac):.3f} | {np.sum(ac>0):.0f}d | {np.mean(dc):.3f} | {np.sum(dc<0):.0f}d |\n")

        f.write("\n## 预测力评估\n\n")
        f.write("| 信号 | IC@10d | IC@20d | Acc@10d | Acc@20d |\n")
        f.write("|------|--------|--------|---------|---------|\n")
        for name, res in all_results.items():
            f.write(f"| {name} | {res['IC@10d']:+.4f} | {res['IC@20d']:+.4f} | {res['Accuracy@10d']:.1%} | {res['Accuracy@20d']:.1%} |\n")

        f.write("\n---\n*报告自动生成*\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print("  Phase 3 完成!")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — LPPL & Wyckoff 激活完成, 请确认后继续 Phase 4")


if __name__ == "__main__":
    main()
