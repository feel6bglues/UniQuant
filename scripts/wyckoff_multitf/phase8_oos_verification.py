"""
Phase 8 — OOS 时域切分验证
============================
核心问题: WSS 查找表和参数在全量数据上训练和测试, 存在过配风险。

方法: 按 cutoff_date 分为训练集 (2020-2022) 和测试集 (2023-2024)。

三阶段:
  A: WSO 纯信号验证 — 固定权重, 无训练参数
  B: WSS 统计评分验证 — 训练集训 lookup → 测试集应用
  C: 参数优化验证 — 阈值 + α/β 在训练集优化 → 测试集验证

输出: OOS 衰减率 + Bootstrap 95% 置信区间
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.uniquant.brain.wyckoff.sequence import WSOScorer
from src.uniquant.shared.cost_model import calculate_sharpe_ratio

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).parent / "output_v4"
MIN_SEQ_TRAIN = 5     # min observations for a sequence in training
MIN_SEQ_TEST = 3      # min observations for meaningful test stats
BOOTSTRAP_N = 2000    # bootstrap resamples
ALPHA = 0.05          # significance level


# ── Data structures ──────────────────────────────────────────────────────

@dataclass
class FoldResult:
    name: str
    n: int = 0
    buy_n: int = 0
    sell_n: int = 0
    buy_mean: float = 0.0
    sell_mean: float = 0.0
    buy_median: float = 0.0
    sell_median: float = 0.0
    buy_t: float = 0.0
    sell_t: float = 0.0
    buy_sharpe: float = 0.0
    sell_sharpe: float = 0.0
    spread: float = 0.0
    spread_t: float = 0.0
    overall_mean: float = 0.0
    overall_t: float = 0.0
    overall_sharpe: float = 0.0
    overall_win_rate: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


# ── Helpers ──────────────────────────────────────────────────────────────

def robust_stats(returns: np.ndarray, winsorize_pct: float = 1.0) -> dict:
    if len(returns) < 3:
        return {}
    n = len(returns)
    lo, hi = np.percentile(returns, [winsorize_pct, 100 - winsorize_pct])
    w = np.clip(returns, lo, hi)
    mean = float(np.mean(returns))
    median = float(np.median(returns))
    wmean = float(np.mean(w))
    wstd = float(np.std(w, ddof=1))
    wse = wstd / math.sqrt(n)
    w_t = wmean / wse if wse > 0 else 0.0
    wins = returns[returns > 0]
    returns[returns < 0]
    win_rate = len(wins) / n if n > 0 else 0.0
    sharpe = calculate_sharpe_ratio(returns / 100.0, period_days=126)
    return {
        "n": n, "mean": mean, "median": median,
        "winsorized_mean": wmean, "winsorized_std": wstd,
        "winsorized_t": w_t, "win_rate": win_rate, "sharpe": sharpe,
        "clip_lo": lo, "clip_hi": hi,
    }


def bootstrap_ci(values: np.ndarray, stat_fn, n_boot: int = BOOTSTRAP_N, ci: float = 0.95) -> Tuple[float, float]:
    """Bootstrap confidence interval for any statistic."""
    if len(values) < 10:
        return (0.0, 0.0)
    stats = []
    for _ in range(n_boot):
        sample = np.random.choice(values, size=len(values), replace=True)
        stats.append(stat_fn(sample))
    stats = sorted(stats)
    alpha = (1 - ci) / 2
    lo_idx = int(alpha * len(stats))
    hi_idx = int((1 - alpha) * len(stats))
    return (float(stats[lo_idx]), float(stats[hi_idx]))


def fmt_pct(v: float) -> str:
    return f"{v:+.4f}"


def compute_results(rets: np.ndarray, buy_rets: np.ndarray, sell_rets: np.ndarray, name: str) -> FoldResult:
    sa = robust_stats(rets)
    sb = robust_stats(buy_rets) if len(buy_rets) >= 3 else {}
    ss = robust_stats(sell_rets) if len(sell_rets) >= 3 else {}

    spread = 0.0
    spread_t = 0.0
    if sb and ss and sb["n"] >= 3 and ss["n"] >= 3:
        spread = sb["winsorized_mean"] - ss["winsorized_mean"]
        spread_se = math.sqrt(
            sb["winsorized_std"]**2 / sb["n"] + ss["winsorized_std"]**2 / ss["n"]
        )
        spread_t = spread / spread_se if spread_se > 0 else 0.0

    return FoldResult(
        name=name,
        n=sa.get("n", 0),
        buy_n=sb.get("n", 0),
        sell_n=ss.get("n", 0),
        buy_mean=sb.get("winsorized_mean", 0.0),
        sell_mean=ss.get("winsorized_mean", 0.0),
        buy_median=sb.get("median", 0.0),
        sell_median=ss.get("median", 0.0),
        buy_t=sb.get("winsorized_t", 0.0),
        sell_t=ss.get("winsorized_t", 0.0),
        buy_sharpe=sb.get("sharpe", 0.0),
        sell_sharpe=ss.get("sharpe", 0.0),
        spread=spread,
        spread_t=spread_t,
        overall_mean=sa.get("winsorized_mean", 0.0),
        overall_t=sa.get("winsorized_t", 0.0),
        overall_sharpe=sa.get("sharpe", 0.0),
        overall_win_rate=sa.get("win_rate", 0.0),
    )


def compute_wso_signal(row: Dict) -> str:
    """Compute WSO signal from raw event data."""
    events = row.get("events", [])
    if not events:
        return "hold"
    if isinstance(events, list) and len(events) > 0 and isinstance(events[0], dict):
        event_types = [e.get("type", "") for e in events]
    else:
        event_types = events if isinstance(events, list) else []
    has_spring = row.get("ds", False)
    spring_count = sum(1 for e in event_types if e == "Spring")
    score = WSOScorer.score_events(event_types, has_spring=has_spring, spring_event_count=spring_count)
    return WSOScorer.signal(score)


def compute_wso_score(row: Dict) -> float:
    """Compute raw WSO score from raw event data."""
    events = row.get("events", [])
    if not events:
        return 0.0
    if isinstance(events, list) and len(events) > 0 and isinstance(events[0], dict):
        event_types = [e.get("type", "") for e in events]
    else:
        event_types = events if isinstance(events, list) else []
    has_spring = row.get("ds", False)
    spring_count = sum(1 for e in event_types if e == "Spring")
    return WSOScorer.score_events(event_types, has_spring=has_spring, spring_event_count=spring_count)


def compute_signal_rets(
    rows: List[Dict],
    signal_field: str = "",
    cost: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute returns for buy/sell signals.

    If signal_field is empty, compute WSO from events on the fly.
    """
    buy_rets, sell_rets = [], []
    for r in rows:
        if signal_field:
            sig = r.get(signal_field, "hold")
        else:
            sig = compute_wso_signal(r)
        if sig == "hold":
            continue
        f6 = r.get("f6", 0.0)
        if not math.isfinite(f6):
            continue
        if sig == "buy":
            buy_rets.append(f6 - cost)
        elif sig == "sell":
            sell_rets.append(-f6 - cost)
    buy_arr = np.array(buy_rets, dtype=np.float64)
    sell_arr = np.array(sell_rets, dtype=np.float64)
    return np.concatenate([buy_arr, sell_arr]), buy_arr, sell_arr


def train_wss_lookup(train_rows: List[Dict]) -> Dict[str, float]:
    """Train WSS lookup on training set only.

    For each sequence type, compute a combined score based on:
    - f6 mean (winsorized)
    - t-statistic
    - win rate

    Only keep sequences with N >= MIN_SEQ_TRAIN.
    """
    by_seq: Dict[str, List[float]] = defaultdict(list)
    for r in train_rows:
        seq = r.get("seq", "")
        if not seq or seq in ("NONE", "LOW_CONF"):
            continue
        f6 = r.get("f6", 0.0)
        if math.isfinite(f6):
            by_seq[seq].append(f6)

    lookup: Dict[str, float] = {}
    for seq, vals in by_seq.items():
        if len(vals) < MIN_SEQ_TRAIN:
            continue
        arr = np.array(vals, dtype=np.float64)
        lo, hi = np.percentile(arr, [1, 99])
        w = np.clip(arr, lo, hi)
        mean = float(np.mean(w))
        std = float(np.std(w, ddof=1))
        n = len(w)
        se = std / math.sqrt(n)
        t_stat = mean / se if se > 0 else 0.0
        win_rate = float(np.mean(w > 0))
        # Combined WSS score: direction * significance * consistency
        score = np.sign(mean) * abs(t_stat) * win_rate
        # Scale to roughly [-1, 1] range
        score = max(-1.0, min(1.0, score / 5.0))
        lookup[seq] = round(score, 6)

    return lookup


def apply_wss(
    rows: List[Dict],
    lookup: Dict[str, float],
    alpha: float = 0.3,
    beta: float = 0.7,
) -> List[Dict]:
    """Apply WSS lookup to rows, computing blended WSO+WSS scores.

    Returns modified rows with 'wyckoff_score' and 'wyckoff_sig'.
    """
    result = []
    for r in rows:
        rw = dict(r)
        raw_events = r.get("events", [])
        seq = r.get("seq", "")
        has_spring = r.get("ds", False)

        # Normalize events to list of types
        if isinstance(raw_events, list) and len(raw_events) > 0 and isinstance(raw_events[0], dict):
            event_types = [e.get("type", "") for e in raw_events]
        else:
            event_types = raw_events if isinstance(raw_events, list) else []

        # WSO base score
        wso_score = WSOScorer.score_events(event_types, has_spring=has_spring)

        # WSS blend if available
        wss_val = lookup.get(seq)
        if wss_val is not None:
            blended = alpha * wso_score + beta * wss_val
        else:
            blended = wso_score

        rw["wyckoff_score"] = round(blended, 6)
        rw["wyckoff_sig"] = WSOScorer.signal(blended)
        result.append(rw)
    return result


def grid_search_thresholds(
    rows: List[Dict],
    lookup: Dict[str, float],
    alpha: float = 0.3,
    beta: float = 0.7,
) -> Tuple[float, float, float, float]:
    """Grid search for optimal buy/sell thresholds + alpha/beta.

    Returns (best_buy_thresh, best_sell_thresh, best_alpha, best_beta).
    """
    buy_candidates = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
    sell_candidates = [-0.01, -0.02, -0.03, -0.04, -0.05, -0.06, -0.08, -0.10]
    alpha_candidates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]

    best_spread_t = -float("inf")
    best_params = (0.04, -0.03, 0.3, 0.7)

    apply_wss(rows, lookup) if lookup else rows

    for bt in buy_candidates:
        for st in sell_candidates:
            for a in alpha_candidates:
                b = 1.0 - a
                # Modify rows with this alpha/beta
                if lookup:
                    mod_rows = apply_wss(rows, lookup, alpha=a, beta=b)
                else:
                    mod_rows = list(rows)

                # Temporarily adjust thresholds
                WSOScorer.BUY_THRESHOLD = bt
                WSOScorer.SELL_THRESHOLD = st

                # Compute signals
                buy_rets, sell_rets = [], []
                for rw in mod_rows:
                    if lookup:
                        sig = rw.get("wyckoff_sig", "hold")
                    else:
                        sig = compute_wso_signal(rw)
                    if sig == "hold":
                        continue
                    f6 = rw.get("f6", 0.0)
                    if not math.isfinite(f6):
                        continue
                    if sig == "buy":
                        buy_rets.append(f6)
                    elif sig == "sell":
                        sell_rets.append(-f6)

                if len(buy_rets) < 10 or len(sell_rets) < 10:
                    continue

                b_arr = np.array(buy_rets)
                s_arr = np.array(sell_rets)
                b_mean = float(np.mean(b_arr))
                s_mean = float(np.mean(s_arr))
                spread = b_mean - s_mean
                b_se = float(np.std(b_arr, ddof=1)) / math.sqrt(len(b_arr))
                s_se = float(np.std(s_arr, ddof=1)) / math.sqrt(len(s_arr))
                spread_se = math.sqrt(b_se**2 + s_se**2)
                spread_t = spread / spread_se if spread_se > 0 else 0.0

                if spread_t > best_spread_t:
                    best_spread_t = spread_t
                    best_params = (bt, st, a, b)

    # Restore defaults
    WSOScorer.BUY_THRESHOLD = 0.04
    WSOScorer.SELL_THRESHOLD = -0.03

    return best_params


def fmt_row(r: FoldResult) -> str:
    return (
        f"  {r.name:<35} "
        f"N={r.n:>5,}  "
        f"B={r.buy_n:>5,}/{r.sell_n:>5,}  "
        f"买={r.buy_mean:>+7.2f}(t={r.buy_t:>+6.2f})  "
        f"卖={r.sell_mean:>+7.2f}(t={r.sell_t:>+6.2f})  "
        f"跨距={r.spread:>+7.2f}(t={r.spread_t:>+6.2f})  "
        f"总={r.overall_mean:>+7.2f}(t={r.overall_t:>+6.2f})  "
        f"夏普={r.overall_sharpe:>6.3f}  "
        f"胜率={r.overall_win_rate:>5.1%}"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    out = OUTPUT_DIR

    # ── 0. Load & split ──
    with open(out / "phase2_event_results.json") as f:
        all_data = json.load(f)
    rows = all_data["data"]

    train_rows = [r for r in rows if r["c"] <= "2022-12-31"]
    test_rows = [r for r in rows if r["c"] >= "2023-01-01"]
    # Ensure no overlap
    test_rows = [r for r in test_rows if r["c"] > "2022-12-31"]

    print(f"{'='*70}")
    print("  Phase 8 — OOS 时域切分验证")
    print(f"{'='*70}")
    print(f"  总观测: {len(rows):,}")
    print(f"  训练集 (≤2022-12-31): {len(train_rows):,}")
    print(f"  测试集 (≥2023-01-01): {len(test_rows):,}")
    print(f"  切分比: {len(train_rows)/len(rows):.1%} / {len(test_rows)/len(rows):.1%}")
    print()

    # ── Stage A: WSO 纯信号 ──
    print(f"{'─'*70}")
    print("  Stage A: WSO 纯信号 — 固定经验权重, 无训练")
    print(f"{'─'*70}")

    wso_train_all, wso_train_b, wso_train_s = compute_signal_rets(train_rows)
    wso_test_all, wso_test_b, wso_test_s = compute_signal_rets(test_rows)

    r_wso_train = compute_results(wso_train_all, wso_train_b, wso_train_s, "WSO 训练集")
    r_wso_test = compute_results(wso_test_all, wso_test_b, wso_test_s, "WSO 测试集")
    print(fmt_row(r_wso_train))
    print(fmt_row(r_wso_test))

    # OOS decay
    decay_wso = (r_wso_test.spread - r_wso_train.spread) / abs(r_wso_train.spread) if r_wso_train.spread != 0 else 0
    print(f"  OOS 多空衰减: {decay_wso:+.2%}")
    print()

    # ── Stage B: WSS 训练 & 验证 ──
    print(f"{'─'*70}")
    print("  Stage B: WSS 统计评分 — 训练集训 lookup → 测试集应用")
    print(f"{'─'*70}")

    # Train WSS lookup on training set only
    print(f"  正在训练 WSS lookup (训练集, N≥{MIN_SEQ_TRAIN})...")
    wss_lookup = train_wss_lookup(train_rows)
    print(f"  训练完成: {len(wss_lookup)} 种序列在查找表中")
    print("  测试集中可被 WSS 覆盖的观测: ", end="")

    # Apply to test set
    test_with_wss = apply_wss(test_rows, wss_lookup)
    test_wss_all, test_wss_b, test_wss_s = compute_signal_rets(test_with_wss, "wyckoff_sig")

    # Also compute train set WSO+WSS for comparison (using same lookup - in-sample!)
    train_with_wss = apply_wss(train_rows, wss_lookup)
    train_wss_all, train_wss_b, train_wss_s = compute_signal_rets(train_with_wss, "wyckoff_sig")

    # How many test observations have WSS coverage?
    test_covered = sum(1 for r in test_with_wss if r.get("seq") in wss_lookup and r["seq"] not in ("NONE", "LOW_CONF"))
    test_total_with_seq = sum(1 for r in test_with_wss if r.get("seq", "") not in ("NONE", "LOW_CONF", ""))
    print(f"{test_covered:,} / {test_total_with_seq:,} 个有序列的观测 ({(test_covered/test_total_with_seq*100) if test_total_with_seq else 0:.1f}%)")

    r_wss_train = compute_results(train_wss_all, train_wss_b, train_wss_s, "WSO+WSS 训练集 (已见)")
    r_wss_test = compute_results(test_wss_all, test_wss_b, test_wss_s, "WSO+WSS 测试集 (未见)")

    print(fmt_row(r_wss_train))
    print(fmt_row(r_wss_test))

    decay_wss = (r_wss_test.spread - r_wss_train.spread) / abs(r_wss_train.spread) if r_wss_train.spread != 0 else 0
    print(f"  OOS 多空衰减: {decay_wss:+.2%}")

    # WSS vs WSO on test set
    wss_vs_wso = r_wss_test.spread - r_wso_test.spread
    print(f"  测试集上 WSS vs WSO 增益: {wss_vs_wso:+.4f}")
    print()

    # ── Stage C: 参数优化 (阈值 + α/β) ──
    print(f"{'─'*70}")
    print("  Stage C: 参数优化 — 训练集网格搜索 → 测试集验证")
    print(f"{'─'*70}")

    # Option 1: WSO-only parameter optimization
    print("  1/3. 网格搜索 WSO 阈值 (训练集)...")
    bt_wso, st_wso, _, _ = grid_search_thresholds(train_rows, {}, alpha=0.3, beta=0.7)
    print(f"      最优 WSO 阈值: 买入≥{bt_wso:.2f}, 卖出≤{st_wso:.2f}")

    # Apply to test set
    old_bt, old_st = WSOScorer.BUY_THRESHOLD, WSOScorer.SELL_THRESHOLD
    WSOScorer.BUY_THRESHOLD = bt_wso
    WSOScorer.SELL_THRESHOLD = st_wso
    opt_test_all, opt_test_b, opt_test_s = compute_signal_rets(test_rows)
    WSOScorer.BUY_THRESHOLD, WSOScorer.SELL_THRESHOLD = old_bt, old_st

    r_opt_wso_test = compute_results(opt_test_all, opt_test_b, opt_test_s, "WSO 最优阈值 测试集")

    # Option 2: WSO+WSS threshold + α/β optimization
    print("  2/3. 网格搜索 WSO+WSS 阈值 + α/β (训练集)...")
    bt_wss, st_wss, alpha_opt, beta_opt = grid_search_thresholds(train_rows, wss_lookup)
    print(f"      最优 WSO+WSS: 买入≥{bt_wss:.2f}, 卖出≤{st_wss:.2f}, α={alpha_opt:.2f}, β={beta_opt:.2f}")

    WSOScorer.BUY_THRESHOLD = bt_wss
    WSOScorer.SELL_THRESHOLD = st_wss
    test_opt_wss = apply_wss(test_rows, wss_lookup, alpha=alpha_opt, beta=beta_opt)
    opt_test_all2, opt_test_b2, opt_test_s2 = compute_signal_rets(test_opt_wss, "wyckoff_sig")
    WSOScorer.BUY_THRESHOLD, WSOScorer.SELL_THRESHOLD = old_bt, old_st

    r_opt_wss_test = compute_results(opt_test_all2, opt_test_b2, opt_test_s2, "WSO+WSS 最优参数 测试集")

    # Option 3: Full-sample thresholds (the ones we've been using)
    print("  3/3. 全量阈值参考: 买入≥0.04, 卖出≤-0.03, α=0.3, β=0.7")
    r_default_wss_test = r_wss_test  # already computed above
    print()

    # ── Bootstrap confidence intervals ──
    print(f"{'─'*70}")
    print("  Bootstrap 置信区间 (95%)")
    print(f"{'─'*70}")
    for label, rets, buy_rets, sell_rets in [
        ("WSO 训练集", wso_train_all, wso_train_b, wso_train_s),
        ("WSO 测试集", wso_test_all, wso_test_b, wso_test_s),
        ("WSS 训练集", train_wss_all, train_wss_b, train_wss_s),
        ("WSS 测试集", test_wss_all, test_wss_b, test_wss_s),
    ]:
        if len(rets) < 10:
            continue
        mean_ci = bootstrap_ci(rets, np.mean)
        buy_mean_ci = bootstrap_ci(buy_rets, np.mean) if len(buy_rets) >= 10 else (0, 0)
        sell_mean_ci = bootstrap_ci(sell_rets, np.mean) if len(sell_rets) >= 10 else (0, 0)
        print(f"  {label:<20} "
              f"总均值 [{mean_ci[0]:>+7.2f}, {mean_ci[1]:>+7.2f}]  "
              f"买 [{buy_mean_ci[0]:>+7.2f}, {buy_mean_ci[1]:>+7.2f}]  "
              f"卖 [{sell_mean_ci[0]:>+7.2f}, {sell_mean_ci[1]:>+7.2f}]")
    print()

    # ── Summary comparison ──
    print(f"{'─'*70}")
    print("  OOS 验证汇总")
    print(f"{'─'*70}")
    print(f"  {'配置':<35} {'多空跨距':>10} {'t':>8} {'衰减率':>10} {'总N':>7} {'买N':>6} {'卖N':>6}")
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*10} {'-'*7} {'-'*6} {'-'*6}")

    results_list = [
        ("WSO 训练集 (默认参数)", r_wso_train),
        ("WSO 测试集 (默认参数)", r_wso_test),
        ("WSO 测试集 (最优阈值)", r_opt_wso_test),
        ("WSO+WSS 训练集 (已见)", r_wss_train),
        ("WSO+WSS 测试集 (默认参数)", r_default_wss_test),
        ("WSO+WSS 测试集 (最优参数)", r_opt_wss_test),
    ]

    baseline_spread = r_wso_train.spread
    for label, r in results_list:
        decay = (r.spread - baseline_spread) / abs(baseline_spread) if baseline_spread != 0 else 0
        print(f"  {label:<35} {r.spread:>+10.2f} {r.spread_t:>+8.2f} {decay:>+10.2%} {r.n:>7,} {r.buy_n:>6,} {r.sell_n:>6,}")

    print()

    # ── Final verdict ──
    print(f"{'─'*70}")
    print("  OOS 验证结论")
    print(f"{'─'*70}")

    verdicts = []

    # WSO test significance
    if abs(r_wso_test.spread_t) >= 3.0:
        verdicts.append("✅ WSO 强验证通过: 测试集跨距 t≥3.0, 信号方向稳定")
    elif abs(r_wso_test.spread_t) >= 2.0:
        verdicts.append("⚠️ WSO 弱验证通过: 测试集跨距 t≥2.0, 需要谨慎")
    else:
        verdicts.append("❌ WSO 验证不通过: 测试集跨距 t<2.0")

    # WSS marginal value on test
    if r_wss_test.spread > r_wso_test.spread and abs(r_wss_test.spread_t) >= 2.0:
        verdicts.append("✅ WSS 在测试集上超越 WSO, 统计评分有效")
    elif r_wss_test.spread > r_wso_test.spread:
        verdicts.append("⚠️ WSS 在测试集上略优于 WSO, 但幅度有限")
    else:
        verdicts.append("⚠️ WSS 在测试集上未超越 WSO, 统计评分未带来 OOS 增益")

    # Overall test performance
    best_test_spread = max(r_wss_test.spread, r_opt_wss_test.spread, r_opt_wso_test.spread)
    best_test_t = max(r_wss_test.spread_t, r_opt_wss_test.spread_t, r_opt_wso_test.spread_t)
    if abs(best_test_t) >= 3.0:
        verdicts.append(f"✅ 最佳 OOS 跨距 {best_test_spread:+.2f} (t={best_test_t:+.2f}), 策略具统计显著性")
    elif abs(best_test_t) >= 2.0:
        verdicts.append(f"⚠️ 最佳 OOS 跨距 {best_test_spread:+.2f} (t={best_test_t:+.2f}), 边缘显著")
    else:
        verdicts.append(f"❌ 最佳 OOS 跨距 {best_test_spread:+.2f} (t={best_test_t:+.2f}), 不显著")

    decay_rate = (best_test_spread - r_wso_train.spread) / abs(r_wso_train.spread) if r_wso_train.spread != 0 else 0
    if abs(decay_rate) < 0.3:
        verdicts.append(f"✅ OOS 衰减率 {decay_rate:+.1%}, 策略稳健")
    elif abs(decay_rate) < 0.5:
        verdicts.append(f"⚠️ OOS 衰减率 {decay_rate:+.1%}, 中度衰减")
    else:
        verdicts.append(f"❌ OOS 衰减率 {decay_rate:+.1%}, 严重衰减")

    for v in verdicts:
        print(f"  {v}")

    # ── Save results ──
    results_dict = {
        "split": {"train_end": "2022-12-31", "train_n": len(train_rows),
                   "test_start": "2023-01-01", "test_n": len(test_rows)},
        "stage_a_wso": {
            "train": r_wso_train.to_dict(),
            "test": r_wso_test.to_dict(),
            "decay": decay_wso,
        },
        "stage_b_wss": {
            "wss_lookup_size": len(wss_lookup),
            "train": r_wss_train.to_dict(),
            "test": r_wss_test.to_dict(),
            "decay": decay_wss,
            "wss_vs_wso_on_test": wss_vs_wso,
        },
        "stage_c_params": {
            "wso_optimal_thresholds": {"buy": bt_wso, "sell": st_wso},
            "wss_optimal_params": {"buy": bt_wss, "sell": st_wss,
                                    "alpha": alpha_opt, "beta": beta_opt},
            "test_wso_opt": r_opt_wso_test.to_dict(),
            "test_wss_opt": r_opt_wss_test.to_dict(),
        },
        "verdicts": verdicts,
    }

    with open(out / "phase8_oos_verification.json", "w") as f:
        json.dump(results_dict, f, indent=2, ensure_ascii=False)
    print(f"\n  已保存: {out / 'phase8_oos_verification.json'}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
