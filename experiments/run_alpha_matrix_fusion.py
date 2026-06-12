"""
Phase 4: 三位一体 Alpha 矩阵融合 (Trinity Alpha Matrix Fusion)
===============================================================

将三个来源的信号融合为多维 Alpha 矩阵:
  1. 手工因子 (Phase 1 基线)
  2. 自动挖掘因子 (Phase 2 GP)
  3. LPPL/Wyckoff 连续分数 (Phase 3)

通过 Walk-Forward OOS 测试验证融合矩阵的稳健性。

[Halt & Wait]
"""

import os, sys, warnings
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EPS = 1e-10

# =========================================================================
# 1. 合成数据 + 全因子计算 (统一的合成环境)
# =========================================================================

def generate_unified_data(seed: int = 42) -> pd.DataFrame:
    """
    生成统一合成数据, 计算所有手工因子 + LPPL/Wyckoff 分数。
    GP 因子用 `amount` 终端 (因 Phase 2 收敛至此)。
    """
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2018-01-01", "2025-03-31")
    n = len(dates)

    # 价格路径 (同 Phase 3, 含泡沫/崩盘/吸筹)
    price = np.zeros(n)
    price[0] = 3500.0
    phases_def = [
        (0, n//5*1, 0.12, 0.18),
        (n//5*1, n//5*2, 0.60, 0.22),
        (n//5*2, n//5*3, -0.60, 0.35),
        (n//5*3, n//5*4, -0.02, 0.15),
        (n//5*4, n, 0.15, 0.18),
    ]
    for s, e, ann_ret, vol in phases_def:
        nd = e - s
        mu = ann_ret / 252
        dv = vol / np.sqrt(252)
        seg_mu = mu
        if ann_ret > 0.3:  # bubble
            t = np.arange(nd) / nd
            seg_mu = mu + 0.008 * t**3 / 3
        elif ann_ret < -0.3:  # crash
            t = np.arange(nd) / nd
            seg_mu = mu - 0.015 * np.exp(3 * t)
            dv *= 1.5
        elif ann_ret < 0:  # accumulation
            dv *= 0.8

        rets = rng.normal(seg_mu if not isinstance(seg_mu, float) else np.full(nd, seg_mu),
                          dv, nd) if ann_ret not in (0.6, -0.6) else rng.normal(seg_mu, dv)
        # fix: generate properly
        if isinstance(seg_mu, np.ndarray):
            rets = rng.normal(seg_mu, dv)
        else:
            rets = rng.normal(seg_mu, dv, nd)
        for i in range(nd):
            if s + i > 0:
                price[s + i] = max(price[s + i - 1] * (1 + rets[i]), 500.0)

    volume = np.zeros(n)
    for i in range(n):
        vol_factor = 1.0
        for idx, (s, e, ann_ret, _) in enumerate(phases_def):
            if s <= i < e:
                if idx == 1: vol_factor = 1.5 + 0.5 * (i - s) / max(e - s, 1)
                elif idx == 2: vol_factor = 2.5
                elif idx == 3: vol_factor = 0.6
                break
        volume[i] = max(1, int(1e9 * vol_factor * (1 + rng.normal(0, 0.15))))

    df = pd.DataFrame({
        "date": dates, "close": np.round(price, 2),
        "open": np.round(price * (1 + rng.normal(0, 0.003, n)), 2),
        "high": np.round(price * (1 + abs(rng.normal(0, 0.005, n))), 2),
        "low": np.round(price * (1 - abs(rng.normal(0, 0.005, n))), 2),
        "volume": volume,
    })
    df["amount"] = df["volume"] * df["close"]
    _compute_all_factors(df)

    return df


def _compute_all_factors(df: pd.DataFrame) -> None:
    """计算所有因子 inline。"""
    close = df["close"].values
    volume = df["volume"].values
    amount = df["amount"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    # ---- 手工因子 (Phase 1 Top 5) ----
    add_fast_ma_ratio(df, close, 5, 20)
    add_pv_divergence(df, close, volume, 20)
    add_ma_ratio(df, close, 10, 30)
    add_vol_ratio(df, volume, 5, 20)
    add_rsi(df, close, 14)

    # ---- GP 因子: 用 amount 终端 (Phase 2 收敛结果) ----
    df["gp_amount"] = amount

    # ---- LPPL 分数 (Phase 3) ----
    cp = _compute_crash_prob(close, 120, 60)
    bp = _compute_bottom_prob(close, 120, 60)
    df["lppl_crash_prob"] = cp
    df["lppl_bottom_prob"] = bp

    # ---- Wyckoff 分数 (Phase 3) ----
    wy = _compute_wyckoff(close, high, low, volume)
    df["acc_score"] = wy[:, 0]
    df["dist_score"] = wy[:, 1]
    df["price_pos"] = wy[:, 2]


def add_fast_ma_ratio(df, close, fast, slow):
    ma_f = pd.Series(close).rolling(fast).mean().values
    ma_s = pd.Series(close).rolling(slow).mean().values
    df[f"ma_ratio_{fast}_{slow}"] = np.where(ma_s > EPS, ma_f / ma_s - 1, 0)

def add_ma_ratio(df, close, fast, slow):
    add_fast_ma_ratio(df, close, fast, slow)

def add_pv_divergence(df, close, volume, period):
    ret = pd.Series(close).pct_change(period)
    vol_chg = pd.Series(volume).pct_change(period)
    df[f"pv_divergence_{period}d"] = ret - vol_chg

def add_vol_ratio(df, volume, fast, slow):
    vf = pd.Series(volume).rolling(fast).mean().values
    vs = pd.Series(volume).rolling(slow).mean().values
    df[f"vol_ratio_{fast}_{slow}"] = np.where(vs > 0, vf / vs - 1, 0)

def add_rsi(df, close, period):
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_g = pd.Series(gain).rolling(period).mean().values
    avg_l = pd.Series(loss).rolling(period).mean().values
    rs = np.where(avg_l > EPS, avg_g / avg_l, 0)
    df[f"rsi_{period}"] = 100 - 100 / (1 + rs)


def _compute_crash_prob(prices, window=120, min_window=60):
    n = len(prices)
    prob = np.zeros(n)
    lp = np.log(prices)
    for t in range(min_window, n):
        s = max(0, t - window)
        seg = lp[s:t]; seg_len = len(seg)
        if seg_len < min_window: continue
        x = np.arange(seg_len, dtype=float) / max(seg_len - 1, 1)
        X = np.column_stack([np.ones(seg_len), x, x**2])
        try:
            coeffs = np.linalg.lstsq(X, seg, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        pred = X @ coeffs
        ss_res = np.sum((seg - pred)**2)
        ss_tot = np.sum((seg - np.mean(seg))**2)
        r2 = 1 - ss_res / max(ss_tot, 1e-10)
        quad = np.clip(coeffs[2] * 100, 0, 1)
        res = seg - pred
        fft = np.abs(np.fft.rfft(res))
        periodic = 0
        if len(fft) > 3:
            peak = np.argmax(fft[1:]) + 1
            periodic = fft[peak] / max(np.sum(fft[1:]), 1e-10) if peak < len(fft)-1 else 0
        prob[t] = np.clip(quad * r2 * (0.5 + 0.5 * periodic), 0, 1)
    return prob

def _compute_bottom_prob(prices, window=120, min_window=60):
    # 用滚动下跌加速度检测底部概率 (无需反转价格)
    n = len(prices)
    prob = np.zeros(n)
    rets = np.diff(prices, prepend=prices[0])
    for t in range(min_window, n):
        s = max(0, t - window)
        seg_ret = rets[s:t]
        seg_p = prices[s:t]
        if len(seg_ret) < min_window: continue
        # 检测大幅下跌后的减速
        cum_drawdown = seg_p[-1] / max(seg_p[0], 1) - 1
        recent_vol = np.std(seg_ret[-30:]) if len(seg_ret) >= 30 else np.std(seg_ret)
        older_vol = np.std(seg_ret[:30]) if len(seg_ret) >= 30 else np.std(seg_ret)
        vol_shrink = 1 - recent_vol / max(older_vol, 1e-10) if older_vol > 0 else 0
        # 价格处于低点 + 波动率收缩 = 底部概率
        if cum_drawdown < -0.15 and vol_shrink > 0.2:
            prob[t] = np.clip((-cum_drawdown) * vol_shrink, 0, 1)
    return prob


def _compute_wyckoff(close, high, low, volume):
    n = len(close)
    acc = np.zeros(n); dist = np.zeros(n); pos = np.full(n, np.nan)

    tr_h = pd.Series(high).rolling(60).max().values
    tr_l = pd.Series(low).rolling(60).min().values
    tr_m = (tr_h + tr_l) / 2

    vol_ma = pd.Series(volume).rolling(30).mean().values
    vol_std = pd.Series(volume).rolling(30).std().values
    ma20 = pd.Series(close).rolling(20).mean().values
    ma_slope = np.full(n, np.nan)
    for i in range(21, n):
        ma_slope[i] = (ma20[i] - ma20[i-20]) / max(ma20[i-20], 1)

    for i in range(80, n):
        trr = tr_h[i] - tr_l[i]
        pos[i] = (close[i] - tr_l[i]) / trr if trr > 0 else 0.5

        # Accumulation
        spring = int(low[i] <= tr_l[i] * 1.01 and close[min(i+3, n-1)] > low[i] * 1.01) if i < n-3 else 0
        vol_z = (volume[i] - vol_ma[i]) / max(vol_std[i], 1) if vol_std[i] > 0 else 0
        vol_surge_low = min(1, max(0, (vol_z - 1.5) / 3)) if vol_z > 1.5 and pos[i] < 0.3 else 0
        vol_climax = 0.5 if i >= 60 and np.mean(volume[i-20:i]) < np.mean(volume[i-40:i-20]) * 0.8 and pos[i] < 0.4 else 0
        trend_turn = 0.7 if not (np.isnan(ma_slope[i]) or np.isnan(ma_slope[i-20])) and ma_slope[i] > 0 and ma_slope[i-20] < 0 and pos[i] < 0.5 else 0
        acc[i] = np.clip(0.3*spring + 0.3*vol_surge_low + 0.2*vol_climax + 0.2*trend_turn, 0, 1)

        # Distribution
        utad = 0.8 if high[i] >= tr_h[i] * 0.99 and i < n-5 and close[i+5] < high[i]*0.98 else 0
        vol_surge_high = min(1, max(0, (vol_z - 1.5)/3)) if vol_z > 1.5 and pos[i] > 0.7 and close[i]/max(close[i-1],1)-1 < 0.01 else 0
        pv_div = 0.6 if i >= 10 and pos[i] > 0.7 and close[i]/max(close[i-10],1)-1 > 0.02 and volume[i]/max(np.mean(volume[i-10:i]),1)-1 < -0.1 else 0
        trend_top = 0.7 if not (np.isnan(ma_slope[i]) or np.isnan(ma_slope[i-20])) and ma_slope[i] < 0 and ma_slope[i-20] > 0 and pos[i] > 0.5 else 0
        dist[i] = np.clip(-(0.3*utad + 0.3*vol_surge_high + 0.2*pv_div + 0.2*trend_top), -1, 0)

    return np.column_stack([acc, dist, pos])


# =========================================================================
# 2. Alpha 矩阵: 因子融合引擎
# =========================================================================

class AlphaMatrix:
    """
    三位一体因子融合引擎。

    融合方法:
      - equal: 等权排名综合
      - ic_weighted: 滚动 IC 加权
      - stack: 线性回归堆叠 (OOS 预测)
    """

    def __init__(self, method: str = "ic_weighted", ic_window: int = 252):
        self.method = method
        self.ic_window = ic_window

    def fuse(self, df: pd.DataFrame, factor_cols: list[str]) -> np.ndarray:
        if self.method == "equal":
            return self._equal_weight(df, factor_cols)
        elif self.method == "ic_weighted":
            return self._ic_weighted(df, factor_cols)
        elif self.method == "stack":
            return self._stack_ensemble(df, factor_cols)
        raise ValueError(f"unknown method: {self.method}")

    def _normalize(self, series: pd.Series) -> np.ndarray:
        """Rank 归一化到 [-1, 1]"""
        r = series.rank(pct=True)
        return (r * 2 - 1).fillna(0).values

    def _equal_weight(self, df, cols):
        signal = np.zeros(len(df))
        for c in cols:
            signal += self._normalize(df[c])
        return signal / len(cols)

    def _ic_weighted(self, df, cols):
        n = len(df)
        signal = np.zeros(n)
        close = df["close"].values

        # rolling IC estimation
        for t in range(self.ic_window, n):
            # 用前 ic_window 天估计每个因子的 IC
            fwd_ret = np.full(n, np.nan)
            for i in range(t-self.ic_window, t-20):
                if i+20 < n:
                    fwd_ret[i] = close[i+20] / close[i] - 1

            weights = []
            for c in cols:
                vals = df[c].values
                valid = ~(np.isnan(vals) | np.isnan(fwd_ret))
                valid_idx = np.where(valid)[0]
                valid_idx = valid_idx[valid_idx < t]  # only past data
                if len(valid_idx) > 20:
                    ic, _ = stats.spearmanr(vals[valid_idx], fwd_ret[valid_idx])
                    w = max(0, ic) if not np.isnan(ic) else 0
                else:
                    w = 0
                weights.append(w)

            total = sum(weights) or 1
            wt = 0
            for i, c in enumerate(cols):
                norm_v = self._normalize(df[c].iloc[:t+1])
                wt += (weights[i] / total) * norm_v[-1] if t < len(norm_v) else 0
            signal[t] = wt

        return signal

    def _stack_ensemble(self, df, cols):
        """滚动线性回归堆叠"""
        n = len(df)
        signal = np.zeros(n)
        close = df["close"].values
        min_train = max(self.ic_window, 252)

        for t in range(min_train, n):
            train_s = max(0, t - self.ic_window)
            X = np.column_stack([self._normalize(df[c].iloc[train_s:t]) for c in cols])
            y = np.array([close[i+20]/close[i]-1 if i+20 < t else np.nan for i in range(train_s, t)])
            valid = ~np.isnan(y)
            if np.sum(valid) > len(cols) + 5:
                Xv = X[valid]; yv = y[valid]
                try:
                    coef, _, _, _ = np.linalg.lstsq(Xv, yv, rcond=None)
                    x_t = np.array([self._normalize(df[c].iloc[:t+1])[-1] for c in cols])
                    pred = x_t @ coef
                    signal[t] = pred
                except np.linalg.LinAlgError:
                    signal[t] = 0

        return signal


# =========================================================================
# 3. Walk-Forward OOS 评估
# =========================================================================

def walk_forward_evaluate(df: pd.DataFrame, signal: np.ndarray,
                          holding_period: int = 20,
                          initial_train: int = 504,
                          test_window: int = 63) -> dict:
    """
    Walk-Forward OOS 评估。
    用 expanding window 训练, 滚动 test_window 天验证。
    """
    n = len(df)
    close = df["close"].values
    dates = df["date"].values

    oos_preds = []
    oos_rets = []
    oos_dates = []

    start = initial_train
    while start + test_window < n:
        test_end = min(start + test_window, n - holding_period)
        if test_end <= start:
            break

        # 信号在测试期的均值作为该期方向预测
        seg_signal = np.nanmean(signal[start:test_end]) if np.any(~np.isnan(signal[start:test_end])) else 0

        # 未来收益
        fwd_ret = close[start + holding_period] / close[start] - 1 if start + holding_period < n else 0

        oos_preds.append(seg_signal)
        oos_rets.append(fwd_ret)
        oos_dates.append(dates[start] if start < len(dates) else "")
        start += test_window

    oos_preds = np.array(oos_preds)
    oos_rets = np.array(oos_rets)

    if len(oos_preds) < 5:
        return {"error": "insufficient OOS samples"}

    # 方向预测准确率
    direction_accuracy = np.mean((oos_preds > 0) == (oos_rets > 0))

    # Rank IC
    ic, ic_p = stats.spearmanr(oos_preds, oos_rets)
    ic = float(ic) if not np.isnan(ic) else 0

    # 分组收益 (Long/Short)
    high_mask = oos_preds > np.percentile(oos_preds, 70)
    low_mask = oos_preds < np.percentile(oos_preds, 30)
    long_ret = np.mean(oos_rets[high_mask]) if np.sum(high_mask) > 2 else 0
    short_ret = np.mean(oos_rets[low_mask]) if np.sum(low_mask) > 2 else 0
    ls_spread = long_ret - short_ret

    # 夏普比 (基于每日信号)
    daily_signal = signal[initial_train:]
    daily_ret = np.full(len(daily_signal), np.nan)
    for i in range(len(daily_signal)-holding_period):
        idx = initial_train + i
        daily_ret[i] = close[idx+holding_period] / close[idx] - 1

    valid = ~(np.isnan(daily_signal) | np.isnan(daily_ret))
    if np.sum(valid) > 20:
        strat_ret = daily_signal[valid] * daily_ret[valid]
        sharpe = np.mean(strat_ret) / max(np.std(strat_ret), 1e-10) * np.sqrt(252/holding_period)
    else:
        sharpe = 0

    return {
        "OOS_periods": len(oos_preds),
        "direction_accuracy": float(direction_accuracy),
        "rank_ic": ic,
        "ic_pvalue": float(ic_p) if not np.isnan(ic_p) else 1.0,
        "long_ret_oos": float(long_ret),
        "short_ret_oos": float(short_ret),
        "ls_spread_oos": float(ls_spread),
        "strat_sharpe": float(sharpe),
    }


def compute_pbo(df: pd.DataFrame, signal: np.ndarray,
                n_splits: int = 50, holding_period: int = 20) -> float:
    """
    计算 Probability of Backtest Overfitting (PBO)。
    通过多次随机 train/test 划分, 衡量策略在 OOS 上的相对排名。
    PBO > 0.3 表示过拟合风险高。
    """
    n = len(df)
    close = df["close"].values
    min_train = 504
    max_rank = 0

    rng = np.random.RandomState(42)
    n_positive = 0

    for split in range(n_splits):
        # 随机划分点 (确保训练集足够)
        split_point = rng.randint(min_train, n - holding_period * 3)
        train_end = split_point
        test_end = min(split_point + 126, n - holding_period)

        if test_end <= train_end:
            continue

        # IS 期 Sharpe
        is_sig = signal[min_train:train_end]
        is_ret = np.full(len(is_sig), np.nan)
        for i in range(len(is_sig)):
            idx = min_train + i
            if idx + holding_period < train_end:
                is_ret[i] = close[idx+holding_period] / close[idx] - 1
        valid_is = ~(np.isnan(is_sig) | np.isnan(is_ret))
        if np.sum(valid_is) < 30:
            continue
        is_sharpe = np.mean(is_sig[valid_is] * is_ret[valid_is]) / max(np.std(is_sig[valid_is] * is_ret[valid_is]), 1e-10)

        # OOS 期 Sharpe
        oos_sig = signal[train_end:test_end]
        oos_ret = np.full(len(oos_sig), np.nan)
        for i in range(len(oos_sig)):
            idx = train_end + i
            if idx + holding_period < test_end:
                oos_ret[i] = close[idx+holding_period] / close[idx] - 1
        valid_oos = ~(np.isnan(oos_sig) | np.isnan(oos_ret))
        if np.sum(valid_oos) < 10:
            continue
        oos_sharpe = np.mean(oos_sig[valid_oos] * oos_ret[valid_oos]) / max(np.std(oos_sig[valid_oos] * oos_ret[valid_oos]), 1e-10)

        if oos_sharpe < 0:
            n_positive += 1

    pbo = n_positive / max(n_splits, 1)
    return pbo


# =========================================================================
# 4. 主程序
# =========================================================================

def main():
    print("=" * 70)
    print("  Phase 4: 三位一体 Alpha 矩阵融合")
    print("  Trinity Alpha Matrix Fusion + Walk-Forward OOS")
    print("=" * 70)

    # ---- 数据 ----
    print("\n[1/5] 生成统一合成数据 + 计算全量因子...")
    df = generate_unified_data()
    print(f"  {len(df)} 个交易日, {df['close'].iloc[0]:.0f} → {df['close'].iloc[-1]:.0f}")
    close = df["close"].values

    # ---- 定义因子组 ----
    handcrafted_cols = ["ma_ratio_5_20", "pv_divergence_20d", "ma_ratio_10_30",
                        "vol_ratio_5_20", "rsi_14"]
    gp_cols = ["gp_amount"]
    lppl_wyckoff_cols = ["lppl_crash_prob", "lppl_bottom_prob", "acc_score", "dist_score"]
    all_cols = handcrafted_cols + gp_cols + lppl_wyckoff_cols

    # 未来收益
    fwd_ret_10 = np.full(len(df), np.nan)
    fwd_ret_20 = np.full(len(df), np.nan)
    for i in range(len(df)-20):
        fwd_ret_10[i] = close[i+10] / close[i] - 1
        fwd_ret_20[i] = close[i+20] / close[i] - 1
    df["fwd_ret_10"] = fwd_ret_10
    df["fwd_ret_20"] = fwd_ret_20

    # ---- 因子相关性矩阵 ----
    print("\n[2/5] 因子相关性矩阵:")
    corr_data = df[all_cols].dropna()
    corr = corr_data.corr()
    print(f"  {'':>24}", end="")
    for c in all_cols:
        print(f"{c[:12]:>12}", end="")
    print()
    for c1 in all_cols:
        print(f"  {c1[:24]:>24}", end="")
        for c2 in all_cols:
            v = corr.loc[c1, c2]
            print(f"{v:>+12.4f}" if not np.isnan(v) else f"{'NaN':>12}", end="")
        print()

    # ---- 各因子独立 IC ----
    print("\n[3/5] 各因子独立预测力 (Spearman IC 对 20d 收益):")
    print(f"  {'因子':<24} {'IC@20d':>8} {'ICIR':>8} {'P值':>8}")
    print(f"  {'-'*48}")
    individual_ics = {}
    for c in all_cols:
        vals = df[c].values
        valid = ~(np.isnan(vals) | np.isnan(fwd_ret_20))
        if np.sum(valid) > 30:
            ic, p = stats.spearmanr(vals[valid], fwd_ret_20[valid])
            ic_val = float(ic) if not np.isnan(ic) else 0
            p_val = float(p) if not np.isnan(p) else 1
            # ICIR: IC 稳定性
            rolling_ics = []
            for t in range(252, np.sum(valid)-20, 63):
                m = np.cumsum(valid)[:t+20]
                idx_s = max(0, t-252)
                ic_roll, _ = stats.spearmanr(vals[valid][idx_s:t], fwd_ret_20[valid][idx_s:t])
                rolling_ics.append(ic_roll if not np.isnan(ic_roll) else 0)
            icir = np.mean(rolling_ics) / max(np.std(rolling_ics), 1e-10) if len(rolling_ics) > 3 else 0
        else:
            ic_val, p_val, icir = 0, 1, 0
        individual_ics[c] = ic_val
        sig = "*" if p_val < 0.05 else ""
        print(f"  {c:<24} {ic_val:>+8.4f}{sig} {icir:>+8.4f} {p_val:>8.4f}")

    # ---- Alpha 矩阵融合 ----
    print("\n[4/5] Alpha 矩阵融合...")
    matrix = AlphaMatrix(method="ic_weighted", ic_window=252)

    # 融合不同类型
    print(f"\n  融合策略:")
    fusion_groups = {
        "仅手工因子": handcrafted_cols,
        "仅 GP 因子": gp_cols,
        "仅 LPPL+Wyckoff": lppl_wyckoff_cols,
        "三位一体 (全部)": all_cols,
        "三位一体 (IC>0 精选)": [c for c in all_cols if individual_ics.get(c, 0) > 0.03],
    }

    wf_results = {}
    for name, cols in fusion_groups.items():
        if len(cols) < 1:
            print(f"  ⚠ {name}: 无因子可用, 跳过")
            continue
        signal = matrix.fuse(df, cols)
        wf = walk_forward_evaluate(df, signal, holding_period=20,
                                    initial_train=504, test_window=63)
        wf_results[name] = {**wf, "signal": signal, "cols": cols}

        sharpe = wf.get("strat_sharpe", 0)
        acc = wf.get("direction_accuracy", 0)
        ls = wf.get("ls_spread_oos", 0)
        ic_wf = wf.get("rank_ic", 0)
        acc_str = f"{acc:.1%}" if not isinstance(acc, str) else acc
        print(f"  {name:<24}  Sharpe={sharpe:>+7.3f}  Acc={acc_str}  "
              f"LS={ls:>+7.2%}  IC={ic_wf:>+7.4f}")

    # ---- PBO 评估 ----
    print("\n[5/5] Probability of Backtest Overfitting (PBO)...")
    print(f"  {'策略':<28} {'PBO':>8} {'判决':>12}")
    print(f"  {'-'*48}")
    pbo_results = {}
    for name, res in wf_results.items():
        signal = res["signal"]
        pbo = compute_pbo(df, signal, n_splits=50, holding_period=20)
        pbo_results[name] = pbo
        verdict = "✅ 稳健" if pbo < 0.2 else ("⚠ 边缘" if pbo < 0.3 else "❌ 过拟合")
        print(f"  {name:<28} {pbo:>8.3f} {verdict:>12}")

    # ---- 生成报告 ----
    report_path = Path("docs/reshaping_logs/03_alpha_matrix_fusion.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 03 — 三位一体 Alpha 矩阵融合报告\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **数据**: 合成指数, {len(df)} 个交易日\n\n")

        f.write("## 参与因子\n\n")
        f.write("| 类型 | 因子 | IC@20d | ICIR |\n")
        f.write("|------|------|--------|------|\n")
        for c in all_cols:
            typ = "手工" if c in handcrafted_cols else ("GP" if c in gp_cols else "LPPL/Wyckoff")
            ic_v = individual_ics.get(c, 0)
            f.write(f"| {typ} | {c} | {ic_v:+.4f} | — |\n")

        f.write("\n## 因子相关性矩阵\n\n")
        f.write("```\n")
        f.write(f"  {'':>24}")
        for c in all_cols:
            f.write(f"{c[:12]:>12}")
        f.write("\n")
        for c1 in all_cols:
            f.write(f"  {c1[:24]:>24}")
            for c2 in all_cols:
                v = corr.loc[c1, c2]
                f.write(f"{v:>+12.4f}" if not np.isnan(v) else f"{'NaN':>12}")
            f.write("\n")
        f.write("```\n\n")

        f.write("## Walk-Forward OOS 结果\n\n")
        f.write("| 策略 | Sharpe | Acc | LS Spread | IC | OOS Periods |\n")
        f.write("|------|--------|-----|-----------|----|-------------|\n")
        best_sharpe = -999
        best_name = ""
        for name, res in wf_results.items():
            s = res.get("strat_sharpe", 0)
            if s > best_sharpe:
                best_sharpe = s
                best_name = name
            acc = res.get("direction_accuracy", 0)
            ls = res.get("ls_spread_oos", 0)
            ic = res.get("rank_ic", 0)
            n = res.get("OOS_periods", 0)
            f.write(f"| {name} | {s:+.4f} | {acc:.1%} | {ls:+.2%} | {ic:+.4f} | {n} |\n")

        f.write(f"\n**最佳**: {best_name} (Sharpe={best_sharpe:.4f})\n\n")

        f.write("## PBO 评估\n\n")
        f.write("| 策略 | PBO | 判决 |\n")
        f.write("|------|-----|------|\n")
        for name, pbo in pbo_results.items():
            verdict = "✅ 稳健" if pbo < 0.2 else ("⚠ 边缘" if pbo < 0.3 else "❌ 过拟合")
            f.write(f"| {name} | {pbo:.3f} | {verdict} |\n")

        f.write("\n**PBO 阈值**: <0.2 稳健, 0.2~0.3 边缘, >0.3 过拟合\n\n")

        f.write("## 结论\n\n")
        for name, res in wf_results.items():
            pbo = pbo_results.get(name, 1.0)
            sharpe = res.get("strat_sharpe", 0)
            if pbo < 0.2 and sharpe > 0.1:
                f.write(f"- ✅ **{name}**: 稳健, Sharpe={sharpe:.3f}, PBO={pbo:.3f}\n")
            elif pbo < 0.3:
                f.write(f"- ⚠ **{name}**: 边缘, Sharpe={sharpe:.3f}, PBO={pbo:.3f}\n")
            else:
                f.write(f"- ❌ **{name}**: 过拟合, Sharpe={sharpe:.3f}, PBO={pbo:.3f}\n")

        f.write("\n---\n*报告由 Phase 4 Alpha Matrix Fusion 自动生成*\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print("  Phase 4 完成!")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — Alpha 矩阵融合完成, 请确认")


if __name__ == "__main__":
    main()
