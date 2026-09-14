# -*- coding: utf-8 -*-
"""T26 LPPL 泡沫监测 (HS300 指数)
模型: log P(t) = A + B(tc-t)^m [1 + C cos(ω·ln(tc-t) + φ)]
  m∈(0,1): 超指数加速   ω>0: 对数周期振荡   tc: 临界时间
拟合: scipy least_squares, 多起点, 约束 m/ω/tc
输出: 当前窗口是否泡沫加速 + 临界时间 + 置信度; 滚动窗口历史泡沫期对照
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from scipy.optimize import least_squares

idx = json.load(open("mx_fin_data/hs300_index.json"))
# 时间轴: 按月递增
seq = sorted((int(k), v) for k, v in idx.items() if v and v > 0)
ts = np.arange(len(seq))
px = np.array([v for _, v in seq])
print(f"HS300 指数: {len(seq)} 个月点 ({seq[0][0]}~{seq[-1][0]})", flush=True)

def lppl_resid(params, t, y):
    A, B, C, m, w, tc, phi = params
    dt = tc - t
    if np.any(dt <= 0):
        return np.full_like(y, 1e6)
    if not (0 < m < 1) or w <= 0:
        return np.full_like(y, 1e6)
    logdt = np.log(dt)
    return A + B * dt ** m * (1 + C * np.cos(w * logdt + phi)) - y

def fit_lppl(t, y, n_starts=24):
    t = t.astype(float)
    y = y.astype(float)
    span = t[-1] - t[0]
    best = None
    rng = np.random.default_rng(42)
    for _ in range(n_starts):
        tc0 = t[-1] + span * rng.uniform(0.1, 0.6)
        A0 = y[-1]
        B0 = rng.uniform(-0.5, 0.5)
        C0 = rng.uniform(-1, 1)
        m0 = rng.uniform(0.1, 0.9)
        w0 = rng.uniform(2, 25)
        phi0 = rng.uniform(-np.pi, np.pi)
        try:
            res = least_squares(lppl_resid, [A0, B0, C0, m0, w0, tc0, phi0],
                                args=(t, y), max_nfev=4000, verbose=0)
            if best is None or res.cost < best.cost:
                best = res
        except Exception:
            continue
    if best is None:
        return None
    p = best.x
    A, B, C, m, w, tc, phi = p
    resid = best.fun
    r2 = 1 - np.var(resid) / np.var(y - y.mean())
    return {"A": A, "B": B, "C": C, "m": m, "w": w, "tc": tc, "phi": phi, "r2": r2, "cost": best.cost}

def bubble_score(fit):
    """泡沫评分: 0-100. m 小(加速强) + |B|大 + 振荡规则 + 拟合优度高"""
    if fit is None:
        return 0.0
    m, w, C, r2 = fit["m"], fit["w"], abs(fit["C"]), fit["r2"]
    s = 0.0
    s += (0.9 - m) / 0.9 * 40          # m 越接近 0 越加速
    s += min(abs(fit["B"]), 1.0) * 20  # 幂律幅度
    s += min(C, 1.0) * 20              # 振荡幅度
    s += max(r2, 0) * 20               # 拟合优度
    return min(s, 100)

# ---------- 全窗口拟合 ----------
print("\n=== 全窗口 LPPL 拟合 ===")
full = fit_lppl(ts, np.log(px))
if full:
    print(f"  tc(临界)={full['tc']:.0f}月 | m={full['m']:.3f} | ω={full['w']:.2f} | C={full['C']:.3f} | R2={full['r2']:.3f}")
    print(f"  泡沫评分: {bubble_score(full):.0f}/100")
    tc_date = seq[-1][0] + int((full['tc'] - len(seq)) * 100) // 12 * 1 if full['tc'] > len(seq) else seq[-1][0]
    print(f"  临界点约在: 数据末月 {seq[-1][0]} 之后 {(full['tc']-len(seq)):.1f} 个月 → 约 {seq[-1][0] + int((full['tc']-len(seq))*100)//12*1}")

# ---------- 滚动窗口 (每 60 月, 步进 6 月) ----------
print("\n=== 滚动 LPPL (窗口60月, 步进6月) ===")
rows = []
win = 60
for i in range(0, len(seq) - win + 1, 6):
    t_w = ts[i:i + win]
    y_w = np.log(px[i:i + win])
    end_m = seq[i + win - 1][0]
    f = fit_lppl(t_w, y_w, n_starts=16)
    sc = bubble_score(f)
    if f:
        horizon = f["tc"] - win  # 距窗口末的月数
        rows.append({"month": end_m, "score": sc, "m": f["m"], "w": f["w"],
                     "tc_horizon": horizon, "r2": f["r2"]})
        flag = " <== 泡沫" if sc > 60 else ""
        print(f"  {end_m}: 评分 {sc:5.1f} | m={f['m']:.2f} | tc+{horizon:+.0f}月{flag}", flush=True)
    else:
        rows.append({"month": end_m, "score": np.nan, "m": np.nan, "w": np.nan,
                     "tc_horizon": np.nan, "r2": np.nan})
        print(f"  {end_m}: 拟合失败", flush=True)

import pandas as pd
df = pd.DataFrame(rows)
df.to_csv("mx_fin_data/lppl_rolling.csv", index=False)

# ---------- 当前状态 ----------
print("\n=== 当前状态 (2026-08) ===")
cur = df.iloc[-1]
print(f"  泡沫评分: {cur['score']:.0f}/100 | m={cur['m']:.2f} | ω={cur['w']:.2f}")
if cur["score"] > 60:
    print(f"  ⚠️ 处于泡沫加速期, 临界时间约 tc+{cur['tc_horizon']:.0f} 月")
elif cur["score"] > 40:
    print(f"  ⚠️ 泡沫萌芽期, 临界时间约 tc+{cur['tc_horizon']:.0f} 月")
else:
    print("  ✅ 无明显泡沫加速特征")
