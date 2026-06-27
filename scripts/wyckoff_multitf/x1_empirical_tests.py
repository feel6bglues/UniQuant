"""
X1: 威科夫多周期 — 六项追加实证测试
====================================
源数据:
  - v4_results.json (86,436 obs: s, c, p, ds, f1, f3, f6)
  - phase2_event_results.json (86,436 obs: events, seq, conf)
  - phase6_combined_results.json (22,148 obs: WSO/WSS scores)
"""

import json, sys, math, time
from pathlib import Path
from collections import defaultdict
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
V4 = OUTPUT / "v4_results.json"
PHASE2 = OUTPUT / "phase2_event_results.json"
PHASE6 = OUTPUT / "phase6_combined_results.json"
T0 = time.time()


def load(path, label):
    with open(path) as f:
        return json.load(f)["data"]


def bootstrap_ci(values, n_iter=10000, alpha=0.05, seed=42):
    arr = np.array(values)
    n = len(arr)
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        boot = rng.choice(arr, size=n, replace=True)
        means[i] = np.mean(boot)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "n": n,
        "mean": float(np.mean(arr)),
        "mean_ci": [float(lo), float(hi)],
        "median": float(np.median(arr)),
        "std": float(np.std(arr, ddof=1)),
        "pos_rate": float((arr > 0).mean()),
    }


def welch_t(a, b):
    a, b = np.array(a), np.array(b)
    n1, n2 = len(a), len(b)
    m1, m2 = np.mean(a), np.mean(b)
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
    se = math.sqrt(v1 / n1 + v2 / n2) if v1 > 0 or v2 > 0 else 0
    if se == 0 or n1 < 2 or n2 < 2:
        return 0.0, 1.0
    t = (m1 - m2) / se
    num = (v1 / n1 + v2 / n2) ** 2
    den = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    dof = num / den if den > 0 else 1
    from scipy.stats import t as tdist
    p = 2 * tdist.sf(abs(t), max(dof - 1e-12, 1))
    return float(t), float(p)


def get_evs(r):
    return r["events"] if isinstance(r["events"], list) else [r["events"]]


# ══════════════════════════════════════════════════════════════
print("=" * 70)
print("  X1: 六项追加实证测试")
print("=" * 70)

# ══════════════════════════════════════════════════════════════
# TEST 1: Spring Bootstrap 置信区间 + 相位条件性分析
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 1: Spring Bootstrap 置信区间 + 相位条件")
print("=" * 70)
t1 = time.time()
v4 = load(V4, "v4_results.json")

springs_by_phase = defaultdict(list)
nonsprings_by_phase = defaultdict(list)
all_spring_f6, all_nonspring_f6 = [], []

for r in v4:
    phase = r.get("p", "unknown")
    if r.get("ds"):
        all_spring_f6.append(r["f6"])
        springs_by_phase[phase].append(r["f6"])
    else:
        all_nonspring_f6.append(r["f6"])
        nonsprings_by_phase[phase].append(r["f6"])

s_ci = bootstrap_ci(all_spring_f6)
ns_ci = bootstrap_ci(all_nonspring_f6)
t_sp, p_sp = welch_t(all_spring_f6, all_nonspring_f6)

t1_results = {
    "spring": s_ci,
    "nonspring": ns_ci,
    "welch_t": t_sp,
    "welch_p": p_sp,
    "by_phase": {},
}

print(f"  Spring 总事件: {s_ci['n']}")
print(f"  Spring f6: {s_ci['mean']:.2f} [{s_ci['mean_ci'][0]:.2f}, {s_ci['mean_ci'][1]:.2f}]")
print(f"  Non-Spring f6: {ns_ci['mean']:.2f}")
print(f"  Spring vs Non-Spring: t={t_sp:.2f} p={p_sp:.4f}")
print(f"  Spring pos_rate: {s_ci['pos_rate']:.1%}")
print()

for phase in sorted(springs_by_phase.keys()):
    sv = np.array(springs_by_phase[phase])
    nv = np.array(nonsprings_by_phase.get(phase, [0]))
    if len(sv) < 5:
        continue
    t_ph, p_ph = welch_t(sv, nv)
    t1_results["by_phase"][phase] = {
        "n_spring": len(sv), "spring_mean": float(np.mean(sv)),
        "n_nonspring": len(nv), "nonspring_mean": float(np.mean(nv)),
        "t": t_ph, "p": p_ph,
    }
    print(f"  {phase}: +Spring f6={np.mean(sv):+.2f} (n={len(sv)}) vs -Spring {np.mean(nv):+.2f}  t={t_ph:.2f}")
print(f"  [{time.time()-t1:.0f}s]")

# ══════════════════════════════════════════════════════════════
# TEST 2: WSS α/β 网格搜索 (使用 phase6 数据)
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 2: WSS α/β 参数网格搜索")
print("=" * 70)
t2 = time.time()
phase6 = load(PHASE6, "phase6_combined_results.json")

# Build WSS lookup from phase2
print("  重建 WSS 查找表...")
phase2 = load(PHASE2, "phase2_event_results.json")
seq_stats = defaultdict(list)
for r in phase2:
    seq = r.get("seq", "")
    if seq:
        seq_stats[seq].append(r["f6"])

wss_lookup = {}
all_t_vals = []
for seq, vals in seq_stats.items():
    arr = np.array(vals)
    n = len(arr)
    if n < 15:
        continue
    mu = np.mean(arr)
    s = np.std(arr, ddof=1)
    t_stat = mu / (s / math.sqrt(n)) if s > 0 else 0
    wr = (arr > 0).mean()
    all_t_vals.append(abs(t_stat))
    wr_bonus = (wr - 0.5) * 2
    wss_lookup[seq] = {"t": t_stat, "wr": wr, "mean": mu, "wss": 0}

max_t = max(all_t_vals) if all_t_vals else 1
for seq, d in wss_lookup.items():
    t_norm = abs(d["t"]) / max_t
    mean_norm = d["mean"] / 100.0
    wr_bonus = (d["wr"] - 0.5) * 2
    d["wss"] = t_norm * mean_norm + 0.3 * wr_bonus * t_norm

print(f"  序列数: {len(wss_lookup)}")

# Grid search
wso_vals = np.array([r.get("wso_score", 0) for r in phase6])
wss_vals = np.array([wss_lookup.get(r.get("seq", ""), {}).get("wss", 0) for r in phase6])
wso_norm = (wso_vals - wso_vals.min()) / (wso_vals.max() - wso_vals.min() + 1e-10)
wss_norm = (wss_vals - wss_vals.min()) / (wss_vals.max() - wss_vals.min() + 1e-10)

grid = []
for alpha_pct in range(0, 101, 5):
    alpha = alpha_pct / 100.0
    combined = alpha * wso_norm + (1 - alpha) * wss_norm
    thresh = np.percentile(combined, 60)
    buy_mask = combined >= thresh
    buy_rets = np.array([r["f6"] for i, r in enumerate(phase6) if buy_mask[i]])
    sell_rets = np.array([r["f6"] for i, r in enumerate(phase6) if not buy_mask[i]])
    if len(buy_rets) < 30:
        continue
    mu_b, mu_s = np.mean(buy_rets), np.mean(sell_rets)
    t_val, p_val = welch_t(buy_rets, sell_rets)
    wr_b = (buy_rets > 0).mean()
    periods = 252 / 126
    sharpe_b = (mu_b / 100.0) / (np.std(buy_rets / 100.0, ddof=1) + 1e-10) * math.sqrt(periods)
    grid.append({
        "alpha": alpha,
        "n_buy": int(len(buy_rets)),
        "buy_f6": float(mu_b),
        "sell_f6": float(mu_s),
        "spread": float(mu_b - mu_s),
        "t": float(t_val),
        "p": float(p_val),
        "win_rate": float(wr_b),
        "sharpe": float(sharpe_b),
    })

best_s = max(grid, key=lambda x: x["sharpe"])
best_t = max(grid, key=lambda x: abs(x["t"]))
best_sp = max(grid, key=lambda x: abs(x["spread"]))

t2_results = {"grid": grid, "best_sharpe": best_s, "best_t": best_t, "best_spread": best_sp}
print(f"  网格点: {len(grid)}")
for g in grid:
    mark = " ← BEST" if g["alpha"] == best_s["alpha"] else ""
    print(f"  α={g['alpha']:.2f}  Sharpe={g['sharpe']:.2f}  spread={g['spread']:.2f}  t={g['t']:.2f}  wr={g['win_rate']:.1%}{mark}")
print(f"  [{time.time()-t2:.0f}s]")

# ══════════════════════════════════════════════════════════════
# TEST 3: 持有期敏感性 (f1/f3/f6)
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 3: 持有期敏感性分析")
print("=" * 70)
t3 = time.time()

periods = [("f1", "21d"), ("f3", "63d"), ("f6", "126d")]
t3_results = {}

for field, label in periods:
    vals = np.array([r[field] for r in v4])
    lo, hi = np.percentile(vals, [1, 99])
    v_clip = np.clip(vals, lo, hi)

    by_phase = defaultdict(list)
    for r in v4:
        phase = r.get("p", "unknown")
        by_phase[phase].append(np.clip(r[field], lo, hi))

    phase_stats = {}
    for ph, pv in by_phase.items():
        arr = np.array(pv)
        mu = np.mean(arr)
        s = np.std(arr, ddof=1)
        n = len(arr)
        t_val = mu / (s / math.sqrt(n)) if s > 0 else 0
        phase_stats[ph] = {"n": n, "mean": float(mu), "t": float(t_val)}

    acc = np.array(by_phase.get("accumulation", [0]))
    mkd = np.array(by_phase.get("markdown", [0]))
    disc_t, disc_p = welch_t(acc, mkd) if len(acc) > 5 and len(mkd) > 5 else (0, 1)

    # Spring discrimination
    spr_f = np.array([r[field] for r in v4 if r.get("ds")])
    nspr_f = np.array([r[field] for r in v4 if not r.get("ds")])
    spr_lo, spr_hi = np.percentile(spr_f, [1, 99])
    spr_clip, nspr_clip = np.clip(spr_f, spr_lo, spr_hi), np.clip(nspr_f, spr_lo, spr_hi)
    s_t, s_p = welch_t(spr_clip, nspr_clip) if len(spr_clip) > 5 and len(nspr_clip) > 5 else (0, 1)

    t3_results[field] = {
        "label": label,
        "overall_mean": float(np.mean(v_clip)),
        "phase_stats": phase_stats,
        "acc_vs_markdown_t": disc_t, "acc_vs_markdown_p": disc_p,
        "acc_mean": float(np.mean(acc)), "markdown_mean": float(np.mean(mkd)),
        "spring_mean": float(np.mean(spr_clip)),
        "nonspring_mean": float(np.mean(nspr_clip)),
        "spring_t": s_t, "spring_p": s_p,
    }
    print(f"  {label}: 积累={np.mean(acc):+.2f} 派发={np.mean(mkd):+.2f} 跨距={disc_t:.2f}  Spring={np.mean(spr_clip):+.2f} vs Non={np.mean(nspr_clip):+.2f}")
print(f"  [{time.time()-t3:.0f}s]")

# ══════════════════════════════════════════════════════════════
# TEST 4: 信号时间衰减
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 4: 信号时间衰减")
print("=" * 70)
t4 = time.time()

yearly = defaultdict(lambda: {"spring": [], "nonspring": [], "accum": [], "markdown": [], "all": []})
for r in v4:
    yr = r["c"][:4]
    if yr < "2015":
        continue
    yearly[yr]["all"].append(r["f6"])
    if r.get("ds"):
        yearly[yr]["spring"].append(r["f6"])
    else:
        yearly[yr]["nonspring"].append(r["f6"])
    ph = r.get("p", "")
    if ph == "accumulation":
        yearly[yr]["accum"].append(r["f6"])
    elif ph == "markdown":
        yearly[yr]["markdown"].append(r["f6"])

t4_results = {}
years = sorted(yearly.keys())
for yr in years:
    d = yearly[yr]
    t4_results[yr] = {}
    for key in ["all", "spring", "nonspring", "accum", "markdown"]:
        arr = np.array(d[key])
        if len(arr) > 5:
            mu, s = np.mean(arr), np.std(arr, ddof=1)
            t_val = mu / (s / math.sqrt(len(arr))) if s > 0 else 0
            t4_results[yr][key] = {"n": len(arr), "mean": float(mu), "t": float(t_val)}
        else:
            t4_results[yr][key] = {"n": 0, "mean": 0.0, "t": 0.0}

# Trend test
yr_nums = np.array([int(y) for y in years])
for key in ["spring", "accum", "markdown"]:
    means = np.array([t4_results[y].get(key, {}).get("mean", np.nan) for y in years])
    valid = ~(np.isnan(means) | (np.array([t4_results[y].get(key, {}).get("n", 0) for y in years]) < 10))
    if valid.sum() > 3:
        from scipy import stats as sp_stats
        slope, intercept, r_val, p_val, std_err = sp_stats.linregress(yr_nums[valid], means[valid])
        t4_results[f"{key}_trend"] = {"slope": slope, "p": p_val, "r": r_val}

print(f"  年份: {', '.join(years)}")
for yr in years:
    d = t4_results[yr]
    print(f"  {yr}: all={d['all']['mean']:.1f}({d['all']['n']})  Spring={d['spring']['mean']:.1f}({d['spring']['n']})  Accum={d['accum']['mean']:.1f}({d['accum']['n']})")
for k in ["spring_trend", "accum_trend", "markdown_trend"]:
    if k in t4_results:
        print(f"  {k}: slope={t4_results[k]['slope']:.4f} p={t4_results[k]['p']:.4f} r={t4_results[k]['r']:.3f}")
print(f"  [{time.time()-t4:.0f}s]")

# ══════════════════════════════════════════════════════════════
# TEST 5: 事件序列预测力排名
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 5: 事件序列预测力排名")
print("=" * 70)
t5 = time.time()

seq_data = defaultdict(list)
for r in phase2:
    seq = r.get("seq", "")
    if seq:
        seq_data[seq].append(r["f6"])

seq_ranked = []
for seq, vals in seq_data.items():
    arr = np.array(vals)
    n = len(arr)
    if n < 15:
        continue
    mu, md = np.mean(arr), np.median(arr)
    s = np.std(arr, ddof=1)
    t_val = mu / (s / math.sqrt(n)) if s > 0 else 0
    wr = (arr > 0).mean()
    n_ev = seq.count(">") + 1
    seq_ranked.append({
        "seq": seq, "n": n, "mean": float(mu), "median": float(md),
        "t": float(t_val), "win_rate": float(wr), "n_events": n_ev,
    })

seq_ranked.sort(key=lambda x: x["mean"], reverse=True)

# Event count efficacy
cnt_eff = defaultdict(list)
for s in seq_ranked:
    cnt_eff[s["n_events"]].append(s["mean"])
cnt_stats = {}
for ne, vals in sorted(cnt_eff.items()):
    arr = np.array(vals)
    cnt_stats[f"{ne}_events"] = {
        "n_seq": len(arr),
        "mean_f6": float(np.mean(arr)),
        "pos_rate": float((arr > 0).mean()),
    }

t5_results = {
    "n_qualified": len(seq_ranked),
    "top_20_best": seq_ranked[:20],
    "top_20_worst": seq_ranked[-20:][::-1],
    "count_effectiveness": cnt_stats,
}
print(f"  合格序列: {t5_results['n_qualified']}")
if seq_ranked:
    b, w = seq_ranked[0], seq_ranked[-1]
    print(f"  最佳: {b['seq']}  f6={b['mean']:.2f} n={b['n']}")
    print(f"  最差: {w['seq']}  f6={w['mean']:.2f} n={w['n']}")
for k, v in sorted(cnt_stats.items()):
    print(f"  {k}: mean_f6={v['mean_f6']:.2f} pos={v['pos_rate']:.1%}")
print(f"  [{time.time()-t5:.0f}s]")

# ══════════════════════════════════════════════════════════════
# TEST 6: 相位条件性事件有效性
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  Test 6: 相位条件性事件有效性")
print("=" * 70)
t6 = time.time()

# Cross-tab: event type × phase → mean f6
ph_ev = defaultdict(lambda: defaultdict(list))
for r in phase2:
    ph = r.get("p", "unknown")
    for ev_type in get_evs(r):
        ph_ev[ev_type][ph].append(r["f6"])

t6_results = {}
for ev_type in ["PS", "SC", "AR", "ST", "SOS", "LPS", "JAC"]:
    if ev_type not in ph_ev:
        continue
    ph_data = dict(ph_ev[ev_type])
    ph_stats = {}
    for ph, vals in ph_data.items():
        arr = np.array(vals)
        n = len(arr)
        mu = float(np.mean(arr))
        s = float(np.std(arr, ddof=1))
        t_val = mu / (s / math.sqrt(n)) if s > 0 else 0
        ph_stats[ph] = {"n": n, "mean": mu, "t": t_val}
    acc = np.array(ph_data.get("accumulation", [0]))
    mkd = np.array(ph_data.get("markdown", [0]))
    disc_t, disc_p = welch_t(acc, mkd) if len(acc) > 5 and len(mkd) > 5 else (0, 1)
    # Bullish events (in accumulation) vs bearish events (in markdown)
    bull_ev = np.array(ph_data.get("accumulation", [0]) + ph_data.get("markup", [0]))
    bear_ev = np.array(ph_data.get("distribution", [0]) + ph_data.get("markdown", [0]))
    bb_t, bb_p = welch_t(bull_ev, bear_ev) if len(bull_ev) > 5 and len(bear_ev) > 5 else (0, 1)
    t6_results[ev_type] = {
        "phase_stats": ph_stats,
        "acc_vs_mkd_t": disc_t, "acc_vs_mkd_p": disc_p,
        "bull_vs_bear_t": bb_t, "bull_vs_bear_p": bb_p,
    }

print("  事件类型在各相位下的 f6 均值:")
for ev_type in ["PS", "SC", "AR", "ST", "SOS", "LPS", "JAC"]:
    if ev_type not in t6_results:
        continue
    ps = t6_results[ev_type]["phase_stats"]
    parts = "  ".join(f"{p}={ps[p]['mean']:.1f}(n={ps[p]['n']})" for p in sorted(ps.keys()))
    disc = t6_results[ev_type]["acc_vs_mkd_t"]
    print(f"  {ev_type:4s}: {parts}  acc-mkd t={disc:.2f}")
print(f"  [{time.time()-t6:.0f}s]")

# ══════════════════════════════════════════════════════════════
# 保存
# ══════════════════════════════════════════════════════════════
results = {
    "test1_spring_bootstrap": t1_results,
    "test2_wss_grid_search": t2_results,
    "test3_hold_sensitivity": t3_results,
    "test4_time_decay": t4_results,
    "test5_event_sequence_power": t5_results,
    "test6_phase_condition_event": t6_results,
    "meta": {"elapsed_s": time.time() - T0},
}

out = OUTPUT / "x1_empirical_results.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\n{'=' * 70}")
print(f"  完成: {time.time() - T0:.0f}s")
print(f"  结果: {out}")
print(f"{'=' * 70}")
