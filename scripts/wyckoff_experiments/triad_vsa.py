"""TRIAD-VSA — 三通道正交量价结构检测器 (研究专用, 纯标注, 恒不产方向信号)。

假说 (对齐 WYCKOFF_DEEP_DIVE_20260812 框架):
  A 流体力学 — 驻点滞止:  A_stag = tanh(k_s/(K_s+η·k_s)), k_s=影线能量(量加权),
                        K_s=净位移能量(量加权) → 放量横盘(影线大/位移小)=吸收
  B 热力学   — 等温潜热:  B_abs  = σ(z(S_grad))·clip(1−m), 熵增且价格钉住
  C 贝叶斯   — 隐状态:    C_abs  = π_A (两态因果前向滤波) + TE_{V→P} (传递熵)

正交混合:
  triad_abs = (A_abs·B_abs·C_abs)^(1/3)   几何平均 → 需三通道共同支持
  agree_abs = majority(≥2 通道 > abs_gate)
  triad_liq = max(A_reflect, liq_jump, B_liq)  任通道清算事件 (标注面)

铁律 (硬编码, 测试强制, 不可关):
  1) 全部特征因果 trailing (无居中窗/无未来对齐) → 前缀不变性对抗测试
  2) 涨跌停棒 (含一字板) = structural, 排除出一切有机特征; 零量/NaN 量棒
     = 非有机; 平盘非涨停棒保持 organic (u=0, 零 churn)
  3) 恒不产 BUY/SELL/direction/signal 字段 → audit_no_direction 断言
  4) 全部输出 ∈[0,1] (latent_store 封顶), 无 inf/NaN 泄漏

预注册常量 (首次校准起点, 非数据拟合; 调整须走 P2 预注册门):
  atr_period=14, ewma_span=5, turb_span=20, range_win=60, reflect_win=3,
  ent_win=120, n_bins=16, grad_win=10, min_bars=30,
  te_win=60, te_lag=1, te_min_pairs=30, self_p=0.95, sigmaA=0.5,
  gammaA=0.5, muD_span=10, liq_theta=0.5 (清算=吸收后验 logit 从 ≥θ 崩塌到 ≤−θ),
  pin_thresh=0.5, limit_tolerance=0.005, pct_floor=1e-4, z_win=120,
  z_minp=60, abs_gate=0.6.

用法: python3 scripts/wyckoff_experiments/triad_vsa.py --symbols golden_20.txt
输出: results/wyckoff_experiments/triad_vsa_{symbol}.csv
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

DAILY = ROOT / "data" / "lake" / "quotes" / "daily"

_EPS = 1e-12
_ANNOTATION_FIELDS = (
    "A_stag",
    "B_abs",
    "C_abs",
    "B_liq",
    "A_reflect",
    "liq_jump",
    "te",
    "triad_abs",
    "triad_liq",
    "agree_abs",
    "latent_store",
)


@dataclass(frozen=True)
class TriadConfig:
    """预注册常量 — 冻结, 修改须走 P2 预注册门."""

    atr_period: int = 14
    ewma_span: int = 5
    turb_span: int = 20
    wick_discount: float = 0.1
    range_win: int = 60
    reflect_win: int = 3
    ent_win: int = 120
    n_bins: int = 16
    grad_win: int = 10
    min_bars: int = 30
    te_win: int = 60
    te_lag: int = 1
    te_min_pairs: int = 30
    self_p: float = 0.95
    sigmaA: float = 0.5
    gammaA: float = 0.5
    muD_span: int = 10
    liq_theta: float = 0.5
    shock_min: float = 1.0
    surge_min: float = 0.2
    pin_thresh: float = 0.5
    limit_tolerance: float = 0.005
    pct_floor: float = 1e-4
    m_star: float = 0.5
    z_win: int = 120
    z_minp: int = 60
    abs_gate: float = 0.6


@dataclass(frozen=True)
class TriadResult:
    """全通道输出. 数值字段全部 ∈[0,1] 或 NaN (latent_store 封顶 1)."""

    A_stag: np.ndarray
    B_abs: np.ndarray
    C_abs: np.ndarray
    B_liq: np.ndarray
    A_reflect: np.ndarray
    liq_jump: np.ndarray
    te: np.ndarray
    triad_abs: np.ndarray
    triad_liq: np.ndarray
    agree_abs: np.ndarray
    latent_store: np.ndarray
    organic: np.ndarray
    structural: np.ndarray

    def to_frame(self, df: pd.DataFrame | None = None) -> pd.DataFrame:
        cols = {f: getattr(self, f) for f in _ANNOTATION_FIELDS}
        cols["organic"] = self.organic
        cols["structural"] = self.structural
        out = pd.DataFrame(cols)
        if df is not None and "date" in df.columns:
            out.insert(0, "date", df["date"].to_numpy())
        return out


# ── 工具: 因果 EWMA / 因果 z / 对称对数收益 ───────────────────────────────


def _ewma(x: np.ndarray, span: int) -> np.ndarray:
    """因果 EWMA, NaN 跳过且保持 (停牌/涨停棒不注入信息)."""
    alpha = 2.0 / (span + 1.0)
    out = np.full(len(x), np.nan, dtype=float)
    prev = np.nan
    for i in range(len(x)):
        v = x[i]
        if np.isnan(v):
            out[i] = prev
            continue
        if np.isnan(prev):
            prev = v
        else:
            prev = alpha * v + (1.0 - alpha) * prev
        out[i] = prev
    return out


def _causal_z(x: np.ndarray, win: int, minp: int) -> np.ndarray:
    """因果滚动 z 分数; std≈0 处返回 0 (不放大噪声)."""
    s = pd.Series(x)
    m = s.rolling(win, min_periods=minp).mean().to_numpy()
    sd = s.rolling(win, min_periods=minp).std().to_numpy()
    out = np.full(len(x), np.nan, dtype=float)
    ok = np.isfinite(m) & np.isfinite(sd)
    out[ok] = np.where(sd[ok] < 1e-9, 0.0, (x[ok] - m[ok]) / np.maximum(sd[ok], 1e-9))
    return out


def _symlog_ret(close: np.ndarray) -> np.ndarray:
    """对称对数收益 (t=0 为 NaN), 对 r≤−1 截断, 无 inf."""
    prev = np.full_like(close, np.nan)
    prev[1:] = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = close / prev - 1.0
    out = np.full(len(close), np.nan, dtype=float)
    ok = np.isfinite(r)
    rv = np.clip(r[ok], -0.9999, None)
    out[ok] = np.where(rv >= 0.0, np.log1p(rv), -np.log1p(-rv))
    return out


def _wild_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder ATR (因果, NaN 跳过)."""
    n = len(close)
    prev = np.full(n, np.nan)
    prev[1:] = close[:-1]
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    tr = np.where(np.isfinite(tr), tr, np.nan)
    return _ewma(tr, 2 * period - 1)


def _limit_pct(symbol: str | None) -> float | None:
    """按代码前缀返回 A 股涨跌幅限制; 无法判定返回 None (不作 censoring)."""
    if not symbol:
        return None
    code = symbol.split(".")[0]
    if not code.isdigit() or len(code) < 3:
        return None
    if code.startswith(("600", "601", "603", "605")) or code.startswith(
        ("000", "001", "002", "003")
    ):
        return 0.10
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "92")):
        return 0.30
    return None


def _structural_mask(
    df: pd.DataFrame,
    limit_pct: float | None,
    tol: float,
) -> np.ndarray:
    """涨跌停 → structural (一字板即"开盘=收盘=涨跌停价", 已被涨跌停覆盖).

    平盘棒 (open=high=low=close) 若不在涨跌停价, 是停牌/无交易态而非
    结构性事件 → 保持 organic (u=0, 零 churn), 避免常量价序列整段被误杀.
    """
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    mask = np.zeros(n, dtype=bool)
    if limit_pct is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            ret_lin = close / np.concatenate(([np.nan], close[:-1])) - 1.0
            th = limit_pct - tol
            mask |= (ret_lin >= th) & (ret_lin > 0.0)
            mask |= (ret_lin <= -th) & (ret_lin < 0.0)
    return mask


# ── 通道 A: 流体力学 驻点滞止 + 激波反射 ──────────────────────────────────


def _channel_a(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr: np.ndarray,
    scale: np.ndarray,
    u: np.ndarray,
    v_eff: np.ndarray,
    v_med: np.ndarray,
    structural: np.ndarray,
    cfg: TriadConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(close)
    gross = (high - low) / np.maximum(atr, _EPS)
    prev = np.full(n, np.nan)
    prev[1:] = close[:-1]
    net = np.abs(close - prev) / np.maximum(atr, _EPS)
    vr = np.clip(v_eff / np.maximum(v_med, _EPS), 0.0, 4.0)
    wick = np.maximum(gross - net, 0.0) * vr
    netv = net * vr
    k_s = _ewma(wick, cfg.turb_span)
    K_s = _ewma(netv, cfg.turb_span)
    a_stag = np.tanh(k_s / (K_s + cfg.wick_discount * k_s + _EPS))

    ubar = _ewma(u, cfg.ewma_span)
    k = _ewma((u - ubar) ** 2, cfg.turb_span)
    K = 0.5 * ubar**2

    bound_hi = pd.Series(high).rolling(cfg.range_win, min_periods=1).max().to_numpy()
    bound_lo = pd.Series(low).rolling(cfg.range_win, min_periods=1).min().to_numpy()
    shock = np.where(
        close > bound_hi,
        (close - bound_hi) / np.maximum(scale, _EPS),
        np.where(close < bound_lo, (close - bound_lo) / np.maximum(scale, _EPS), 0.0),
    )
    k_prev = np.concatenate(([np.nan], k[:-1]))
    surge = k - k_prev
    break_side = np.where(
        (np.abs(shock) >= cfg.shock_min) & (surge > cfg.surge_min),
        np.sign(shock),
        0.0,
    )
    break_side[structural] = 0.0

    reflect = np.zeros(n, dtype=float)
    for t in range(1, n):
        lo = max(0, t - cfg.reflect_win)
        for j in range(lo, t):
            b = break_side[j]
            if b != 0.0 and np.isfinite(bound_hi[j]) and np.isfinite(bound_lo[j]):
                if close[t] <= bound_hi[j] and close[t] >= bound_lo[j]:
                    reflect[t] = 1.0
                    break
    return a_stag, K, reflect


# ── 通道 B: 热力学 熵 / 潜热 ─────────────────────────────────────────────


def _entropy_flow(
    r_w: np.ndarray,
    w: np.ndarray,
    scale: np.ndarray,
    cfg: TriadConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """量价联合分布熵 S / 净流 m / 离散度 T (因果窗口, MM 偏差校正).

    m/T 用**逐棒自身 scale 归一**的收益 (r_w/scale_t) 计算 — 防止单边趋势下
    "窗口均值 / 当前 ATR" 因价格抬升而塌缩, 把趋势误判为价格钉住.
    """
    n = len(r_w)
    S = np.full(n, np.nan)
    m = np.full(n, np.nan)
    T = np.full(n, np.nan)
    for t in range(cfg.ent_win - 1, n):
        sl = slice(t - cfg.ent_win + 1, t + 1)
        rr = r_w[sl]
        ww = w[sl]
        sc = scale[sl]
        valid = np.isfinite(rr) & (ww > 0.0) & np.isfinite(sc) & (sc > 0.0)
        n_eff = int(valid.sum())
        if n_eff < cfg.min_bars:
            continue
        rv = rr[valid]
        wv = ww[valid]
        scv = sc[valid]
        wsum = wv.sum()
        if wsum <= 0.0:
            continue
        wv = wv / wsum
        rvn = rv / scv
        rbar = (wv * rvn).sum()
        m[t] = abs(rbar)
        T[t] = np.sqrt((wv * (rvn - rbar) ** 2).sum())
        lo = np.quantile(rv, 0.02)
        hi = np.quantile(rv, 0.98)
        if hi - lo < 1e-12:
            S[t] = 0.0
            continue
        edges = np.linspace(lo, hi, cfg.n_bins + 1)
        idx = np.clip(np.searchsorted(edges, rv, side="right") - 1, 0, cfg.n_bins - 1)
        p = np.bincount(idx, weights=wv, minlength=cfg.n_bins)
        p = np.maximum(p, 1e-12)
        p = p / p.sum()
        S[t] = -(p * np.log(p)).sum() + (cfg.n_bins - 1) / (2.0 * n_eff)
    return S, m, T


# ── 通道 C: 贝叶斯隐状态 + 传递熵 ────────────────────────────────────────


def _bayes_abs(
    u: np.ndarray,
    q: np.ndarray,
    cfg: TriadConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """两态因果前向滤波: π_A = P(吸收). 非有机棒保持后验 (不注入信息).

    warmup 期先验 = 均匀 0.5 (携带状态 prev_p), NaN 棒只 hold 不传播 NaN,
    避免"未初始化先验 + NaN 传播"把整条后验毒化.
    """
    n = len(u)
    mu_d = _ewma(u, cfg.muD_span)
    pi_a = np.full(n, np.nan)
    logit = np.full(n, np.nan)
    prev_p = 0.5
    prev_logit = 0.0
    for t in range(n):
        if np.isnan(u[t]) or np.isnan(q[t]):
            pi_a[t] = prev_p
            logit[t] = prev_logit
            continue
        l_a = math.exp(-0.5 * (u[t] / cfg.sigmaA) ** 2) * math.exp(
            (q[t] - 1.0) * cfg.gammaA
        )
        mu = mu_d[t] if np.isfinite(mu_d[t]) else 0.0
        l_d = math.exp(-0.5 * ((u[t] - mu) / cfg.sigmaA) ** 2)
        a = (prev_p * cfg.self_p + (1.0 - prev_p) * (1.0 - cfg.self_p)) * l_a
        d = (prev_p * (1.0 - cfg.self_p) + (1.0 - prev_p) * cfg.self_p) * l_d
        tot = a + d
        if not np.isfinite(tot) or tot <= 0.0:
            pi_a[t] = prev_p
            logit[t] = prev_logit
            continue
        prev_p = a / tot
        prev_logit = math.log(prev_p / (1.0 - prev_p + 1e-9))
        pi_a[t] = prev_p
        logit[t] = prev_logit
    return pi_a, logit


def _transfer_entropy(
    sgn: np.ndarray,
    vhi: np.ndarray,
    cfg: TriadConfig,
) -> np.ndarray:
    """TE_{V→P}: H(P_t|P_{t−1}) − H(P_t|P_{t−1},V_{t−1}), 因果窗, /ln3 归一."""
    n = len(sgn)
    ok = np.isfinite(sgn) & np.isfinite(vhi)
    out = np.full(n, np.nan)
    for t in range(cfg.te_win - 1, n):
        lo = max(0, t - cfg.te_win + 1)
        idx = np.arange(lo + 1, t + 1)
        valid = ok[idx] & ok[idx - 1]
        if int(valid.sum()) < cfg.te_min_pairs:
            continue
        s2 = sgn[idx][valid].astype(int)
        s1 = sgn[idx - 1][valid].astype(int)
        v1 = vhi[idx - 1][valid].astype(int)
        n_pairs = len(s2)
        c_pp = np.zeros((3, 3))
        np.add.at(c_pp, (s2 + 1, s1 + 1), 1.0)
        c_ppv = np.zeros((3, 3, 2))
        np.add.at(c_ppv, (s2 + 1, s1 + 1, v1), 1.0)
        p_pp = (c_pp + 1.0) / (n_pairs + 9.0)
        p_prev = p_pp.sum(axis=0)
        h_nv = -np.sum(p_pp * np.log(p_pp / (p_prev[None, :] + 1e-300)))
        p_ppv = (c_ppv + 1.0) / (n_pairs + 18.0)
        p_prevv = p_ppv.sum(axis=0)
        h_v = -np.sum(p_ppv * np.log(p_ppv / (p_prevv[None, :, :] + 1e-300)))
        te = max(0.0, h_nv - h_v) / math.log(3.0)
        out[t] = min(te, 1.0)
    return out


# ── 正交混合 + 契约 ───────────────────────────────────────────────────────


def _fusion(
    a_abs: np.ndarray,
    b_abs: np.ndarray,
    c_abs: np.ndarray,
    gate: float,
) -> tuple[np.ndarray, np.ndarray]:
    valid = np.isfinite(a_abs) & np.isfinite(b_abs) & np.isfinite(c_abs)
    triad = np.full(len(a_abs), np.nan)
    triad[valid] = (a_abs[valid] * b_abs[valid] * c_abs[valid]) ** (1.0 / 3.0)
    agree = np.zeros(len(a_abs), dtype=float)
    for arr in (a_abs, b_abs, c_abs):
        agree += (arr > gate).astype(float)
    agree = (agree >= 2.0).astype(float)
    return triad, agree


def audit_no_direction(res: TriadResult) -> None:
    """无方向契约: 无 buy/sell/direction/signal 字段; 数值全部 ∈[0,1]."""
    banned = ("buy", "sell", "direction", "signal")
    for f in _ANNOTATION_FIELDS:
        assert not any(b in f.lower() for b in banned), f"字段泄漏: {f}"
    for f in _ANNOTATION_FIELDS:
        arr = getattr(res, f)
        v = arr[np.isfinite(arr)]
        assert np.all(v >= -1e-9), f"{f} 下界越界: {v.min()}"
        assert np.all(v <= 1.0 + 1e-9), f"{f} 上界越界: {v.max()}"


# ── 主入口 ─────────────────────────────────────────────────────────────────


def compute_triad(
    df: pd.DataFrame,
    cfg: TriadConfig | None = None,
    symbol: str | None = None,
) -> TriadResult:
    """全通道计算. 输入须含 open/high/low/close/volume. 恒无方向输出."""
    cfg = cfg or TriadConfig()
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns, f"缺列: {col}"
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)
    n = len(close)

    structural = _structural_mask(df, _limit_pct(symbol), cfg.limit_tolerance)
    vol_ok = np.isfinite(volume) & (volume > 0.0)
    organic = (~structural) & vol_ok

    atr = _wild_atr(high, low, close, cfg.atr_period)
    scale = np.maximum(
        np.nan_to_num(atr) / np.maximum(close, _EPS), cfg.pct_floor
    )
    scale = np.maximum(scale, _EPS)

    r_w = _symlog_ret(close)
    u = np.full(n, np.nan)
    u[organic] = r_w[organic] / np.maximum(scale[organic], _EPS)
    u[~np.isfinite(r_w)] = np.nan

    w = np.zeros(n)
    w[organic] = volume[organic]

    v_eff = np.where(organic, volume, np.nan)
    v_med = (
        pd.Series(v_eff).rolling(cfg.ent_win, min_periods=60).median().to_numpy()
    )

    a_stag, _, reflect = _channel_a(
        close, high, low, atr, scale, u, v_eff, v_med, structural, cfg
    )

    S, m, T = _entropy_flow(r_w, w, scale, cfg)
    Sg = np.full(n, np.nan)
    Sg[cfg.grad_win:] = (S[cfg.grad_win:] - S[: n - cfg.grad_win]) / cfg.grad_win
    z_s = _causal_z(Sg, cfg.z_win, cfg.z_minp)
    b_abs = _sigmoid(z_s) * np.clip(1.0 - m / cfg.m_star, 0.0, 1.0)
    b_liq = _sigmoid(-z_s) * np.clip(m / cfg.m_star, 0.0, 1.0)
    z_endo = T * np.maximum(Sg, 0.0) / (m + _EPS)
    latent = np.full(n, np.nan)
    run = 0.0
    for t in range(n):
        if np.isfinite(z_endo[t]) and np.isfinite(T[t]):
            pin = np.isfinite(u[t]) and abs(u[t]) < cfg.pin_thresh
            if pin:
                run = 0.98 * run + z_endo[t]
            else:
                run = 0.98 * run
        latent[t] = min(run, 1.0)

    v_ratio = np.where(v_med > 0.0, v_eff / v_med, np.nan)
    q = np.clip(v_ratio, 0.0, 4.0) * (1.0 / (1.0 + np.abs(u)))
    q[~np.isfinite(q)] = np.nan

    pi_a, logit = _bayes_abs(u, q, cfg)
    logit_prev = np.concatenate(([np.nan], logit[:-1]))
    collapse = (
        np.isfinite(logit)
        & np.isfinite(logit_prev)
        & (logit_prev >= cfg.liq_theta)
        & (logit <= -cfg.liq_theta)
    )
    liq_jump = collapse.astype(float)

    v_hi = np.where(organic & np.isfinite(v_med), (volume > v_med).astype(float), np.nan)
    sgn = np.where(organic, np.sign(r_w), np.nan)
    te = _transfer_entropy(sgn, v_hi, cfg)

    triad_abs, agree = _fusion(a_stag, b_abs, pi_a, cfg.abs_gate)
    liq_any = np.maximum.reduce([reflect, liq_jump, b_liq])
    liq_any = np.where(np.isfinite(liq_any), liq_any, 0.0)
    triad_liq = np.clip(liq_any, 0.0, 1.0)

    res = TriadResult(
        A_stag=a_stag,
        B_abs=b_abs,
        C_abs=pi_a,
        B_liq=b_liq,
        A_reflect=reflect,
        liq_jump=liq_jump,
        te=te,
        triad_abs=triad_abs,
        triad_liq=triad_liq,
        agree_abs=agree,
        latent_store=latent,
        organic=organic,
        structural=structural,
    )
    audit_no_direction(res)
    return res


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(z), 1.0 / (1.0 + np.exp(-z)), np.nan)


# ── 预注册门骨架: 单窗口汇总 (X1-X6 门的最小执行器) ──────────────────────


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _rank_sum_p(x: np.ndarray, y: np.ndarray) -> float:
    """Wilcoxon rank-sum 正态近似 p (双侧)."""
    n1 = len(x)
    n2 = len(y)
    if n1 == 0 or n2 == 0:
        return np.nan
    allv = np.concatenate([x, y])
    order = np.argsort(allv, kind="mergesort")
    n = n1 + n2
    ranks = np.empty(n)
    i = 0
    while i < n:
        j = i
        while j < n and allv[order[j]] == allv[order[i]]:
            j += 1
        avg = (i + j - 1) / 2.0 + 1.0
        ranks[order[i:j]] = avg
        i = j
    u = ranks[:n1].sum() - n1 * (n1 + 1.0) / 2.0
    mu = n1 * n2 / 2.0
    var = n1 * n2 * (n + 1.0) / 12.0
    z = (u - mu) / math.sqrt(max(var, _EPS))
    return min(max(2.0 * (1.0 - _norm_cdf(abs(z))), 0.0), 1.0)


def summarize_window(
    triad_abs: np.ndarray,
    fwd_ret: np.ndarray,
    relmom: np.ndarray | None = None,
    tail_cut: float = 0.10,
) -> dict:
    """预注册窗口汇总: 原始超额 / OLS 动量残差 / 剔尾 rank-sum p."""
    valid = np.isfinite(triad_abs) & np.isfinite(fwd_ret)
    if int(valid.sum()) < 40:
        return {"n": 0, "raw_excess": np.nan, "m2_resid": np.nan, "r3_p": np.nan}
    x = triad_abs[valid]
    y = fwd_ret[valid]
    q_hi = np.quantile(x, 0.9)
    top = y[x >= q_hi]
    rest = y[x < q_hi]
    raw = top.mean() - rest.mean() if len(top) > 0 and len(rest) > 0 else np.nan
    out: dict = {"n": int(valid.sum()), "raw_excess": raw, "m2_resid": np.nan, "r3_p": np.nan}
    if relmom is not None:
        rm = relmom[valid]
        ok2 = np.isfinite(rm)
        if int(ok2.sum()) >= 40:
            xx = x[ok2]
            yy = y[ok2]
            rm2 = rm[ok2]
            coef = np.polyfit(rm2, yy, 2)
            resid = yy - np.polyval(coef, rm2)
            out["m2_resid"] = resid[xx >= np.quantile(xx, 0.9)].mean() - resid[
                xx < np.quantile(xx, 0.9)
            ].mean()
    keep = np.abs(y) <= tail_cut
    if int(keep.sum()) >= 40:
        xt = x[keep]
        yt = y[keep]
        top_t = yt[xt >= np.quantile(xt, 0.9)]
        rest_t = yt[xt < np.quantile(xt, 0.9)]
        out["r3_p"] = _rank_sum_p(top_t, rest_t)
    return out


# ── CLI ────────────────────────────────────────────────────────────────────


def _load_symbols(golden_file: str) -> list[str]:
    p = ROOT / golden_file
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="TRIAD-VSA 三通道正交标注 (纯标注, 无方向)")
    parser.add_argument("--symbols", default="golden_20.txt")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD, 截断到该日")
    parser.add_argument("--outdir", default="results/wyckoff_experiments/triad_vsa")
    args = parser.parse_args()

    symbols = _load_symbols(args.symbols)
    if not symbols:
        print(f"no symbols from {args.symbols}")
        return
    outdir = ROOT / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = TriadConfig()
    for symbol in symbols:
        path = DAILY / f"{symbol}.parquet"
        if not path.exists():
            print(f"skip {symbol}: no data")
            continue
        df = pd.read_parquet(path)
        if args.as_of:
            df = df[df["date"] <= pd.Timestamp(args.as_of)]
        res = compute_triad(df, cfg, symbol)
        frame = res.to_frame(df)
        frame.insert(0, "symbol", symbol)
        frame.to_csv(outdir / f"triad_vsa_{symbol}.csv", index=False)
        last = frame.iloc[-1].to_dict()
        print(
            f"{symbol}: triad_abs={last['triad_abs']:.3f} "
            f"triad_liq={last['triad_liq']:.3f} te={last['te']:.3f}"
        )


if __name__ == "__main__":
    main()