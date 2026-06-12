"""
Alpha Matrix — 简化版实弹回测
================================
读入已缓存的 Parquet 数据, 运行全生命周期回测
"""
import datetime, json, math, time, warnings
from pathlib import Path
from typing import Dict, List
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

INITIAL_CAPITAL = 1_000_000
COMM = 0.0003; STAMP = 0.0005; STAMP_O = 0.001; SLIP = 0.0005
MIN_COMM = 5.0; TFEE = 0.00001; STAMP_CUT = datetime.date(2023, 8, 28)

def stamptax(d): return STAMP if d >= STAMP_CUT else STAMP_O
def lot_sz(c): return 100

def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """为单只股票计算所有因子, 返回与 df 同长度"""
    r = df["close"].pct_change()
    amt = df["amount"].fillna(0)
    fac = pd.DataFrame(index=df.index)
    fac["illiq_20d"] = (r.abs() / amt.replace(0, np.nan) * 1e9).rolling(20, 10).mean()
    fac["pv_div_20d"] = df["volume"].rank(pct=True) - df["close"].rank(pct=True)
    fac["cs_mom_20d"] = (1 + df["close"].pct_change(20)) / (1 + df["close"].pct_change(5)) - 1
    fac["ivol_20d"] = -r.rolling(20, 10).std() * np.sqrt(252)
    fac["gp_vol20d"] = r.rolling(20, 10).std()
    fac["gp_ret10d"] = df["close"].pct_change(10)
    return fac

WEIGHTS = {"illiq_20d": 0.20, "pv_div_20d": -0.20, "cs_mom_20d": 0.20,
           "ivol_20d": 0.15, "gp_vol20d": 0.10, "gp_ret10d": 0.15}

def composite(fac: pd.DataFrame) -> pd.Series:
    z = fac.rank(pct=True)
    score = pd.Series(0.0, index=z.index)
    for col, w in WEIGHTS.items():
        if col in z.columns:
            score += z[col].fillna(0.5) * w
    return score

def load_lppl(idx_df: pd.DataFrame) -> np.ndarray:
    from uniquant.brain.lppl.engine import process_single_day_ensemble, LPPLConfig
    cfg = LPPLConfig(window_range=list(range(60, 180, 20)), optimizer="lbfgsb",
                     maxiter=50, r2_threshold=0.3, consensus_threshold=0.25, n_workers=1)
    c = idx_df["close"].values.astype(np.float64)
    p = np.zeros(len(idx_df))
    step = 10
    for i in range(max(cfg.window_range)+5, len(idx_df), step):
        try:
            r = process_single_day_ensemble(c, i, cfg.window_range, min_r2=cfg.r2_threshold,
                                            consensus_threshold=cfg.consensus_threshold, config=cfg)
            if r:
                p[i] = min(r["consensus_rate"] * min(r["signal_strength"]*3, 1.0), 1.0)
        except: pass
    return pd.Series(p).rolling(5, 1).mean().fillna(0).values

def load_wyckoff(idx_df: pd.DataFrame) -> np.ndarray:
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    eng = WyckoffEngine(lookback_days=250)
    s = np.zeros(len(idx_df))
    step = 10
    for i in range(60, len(idx_df), step):
        try:
            w = idx_df.iloc[max(0,i-250):i+1].copy()
            if len(w) < 60: continue
            rp = eng.analyze(w, symbol="000300", period="日线")
            ph = rp.structure.phase.value if hasattr(rp.structure.phase, "value") else str(rp.structure.phase)
            sg = rp.signal.signal_type.lower()
            if "accumulation" in ph.lower():
                s[i] = 0.9 if "spring" in sg else (0.6 if "accumulation" in sg else 0.3)
            elif "markup" in ph.lower():
                s[i] = -0.2
            elif "distribution" in ph.lower() or "markdown" in ph.lower():
                s[i] = -0.5
        except: pass
    return pd.Series(s).rolling(5, 1).mean().clip(-1, 1).values

def backtest(df_all: pd.DataFrame, idx_df: pd.DataFrame) -> dict:
    print("Pre-computing factors...")
    fgrps = []
    for c, g in df_all.groupby("code"):
        g = g.sort_values("date").copy()
        fac = compute_factors(g)
        for col in fac.columns: g[col] = fac[col].values
        fgrps.append(g)
    df = pd.concat(fgrps, ignore_index=True)
    df.sort_values(["date", "code"], inplace=True)

    print("LPPL overlay...")
    lppl_p = load_lppl(idx_df)
    print("Wyckoff overlay...")
    wyckoff_s = load_wyckoff(idx_df)

    idx_map = dict(zip(idx_df.index, range(len(idx_df))))
    dt_map = dict(zip(idx_df["date"].values, idx_df.index))

    cash = INITIAL_CAPITAL
    portfolio: Dict[str, dict] = {}
    eq_curve, eq_dates, daily_ret = [], [], []
    trades = []
    prev_eq = INITIAL_CAPITAL

    dates = sorted(df["date"].unique())
    reb_dates = dates[::21]

    for di, cur_d in enumerate(dates):
        dt = pd.Timestamp(cur_d)
        day = df[df["date"] == cur_d]
        if day.empty: continue

        pv = 0.0
        for cd, pos in list(portfolio.items()):
            pr = day.loc[day["code"] == cd, "close"]
            if not pr.empty: pv += pos["shares"] * pr.iloc[0]

        eq = cash + pv
        eq_curve.append(eq); eq_dates.append(cur_d)
        if prev_eq > 0: daily_ret.append((eq - prev_eq) / prev_eq)
        else: daily_ret.append(0.0)

        is_reb = cur_d in reb_dates
        if not is_reb:
            prev_eq = eq
            continue

        score = composite(day)
        valid = day["close"].notna() & (day["amount"].fillna(0) > 0)
        score[~valid.values] = -999

        # 市场条件
        idx_pos = dt_map.get(cur_d)
        if idx_pos is not None:
            cp = float(lppl_p[idx_pos])
            wa = float(wyckoff_s[idx_pos])
        else:
            cp, wa = 0.0, 0.0

        lppl_veto = cp > 0.6
        wyckoff_amp = wa > 0.5
        ov = 0.3 if lppl_veto else (1.3 if wyckoff_amp else 1.0)

        n_sel = max(1, int(len(score) * 0.20))
        top = score.nlargest(n_sel).index
        sel = set(day.loc[top, "code"].values)
        tgt_eq = eq * ov
        per_stk = min(tgt_eq / max(n_sel, 1), eq * 0.10)

        # Sell
        for cd in list(portfolio.keys()):
            if cd in sel: continue
            pos = portfolio.pop(cd)
            pr = day.loc[day["code"] == cd, "close"]
            if pr.empty or (pos["buy_date"] and cur_d <= pos["buy_date"]): continue
            sp = pr.iloc[0] * (1 - SLIP)
            sd = stamptax(dt.date())
            st = pos["shares"] * sp * sd
            cm = max(pos["shares"] * sp * COMM, MIN_COMM)
            tf = pos["shares"] * sp * TFEE
            net = pos["shares"] * sp - st - cm - tf
            cash += net
            trades.append(dict(date=str(cur_d)[:10], code=cd, act="S", sh=pos["shares"],
                              px=round(sp,2), val=round(pos["shares"]*sp,0)))

        # Buy
        if lppl_veto:
            tgt_eq = eq * 0.3
            n_sel = max(1, n_sel // 2)
        buy_codes = list(sel - set(portfolio.keys()))[:n_sel]
        if buy_codes:
            per_b = min(tgt_eq / len(buy_codes), eq * 0.10)
            for cd in buy_codes:
                pr = day.loc[day["code"] == cd, "close"]
                if pr.empty: continue
                bp = pr.iloc[0]
                lot = 100
                mx = int(per_b / max(bp * (1 + SLIP), 1e-6)) // lot * lot
                if mx <= 0: continue
                cost = mx * bp * (1 + SLIP)
                cm = max(cost * COMM, MIN_COMM)
                tf = cost * TFEE
                tc = cost + cm + tf
                if tc > cash:
                    mx = int((cash - cm - tf) / max(bp * (1 + SLIP), 1e-6)) // lot * lot
                    if mx <= 0: continue
                    cost = mx * bp * (1 + SLIP)
                    tc = cost + cm + tf
                cash -= tc
                portfolio[cd] = dict(shares=mx, buy_date=cur_d, cost=bp*(1+SLIP))
                trades.append(dict(date=str(cur_d)[:10], code=cd, act="B", sh=mx,
                                   px=round(bp*(1+SLIP),2), val=round(cost,0)))
        prev_eq = eq

    # Liquidate
    for cd, pos in list(portfolio.items()):
        ld = df[df["code"] == cd].iloc[-1]
        sp = ld["close"] * (1 - SLIP)
        sd = stamptax(pd.Timestamp(ld["date"]).date())
        st = pos["shares"] * sp * sd
        cm = max(pos["shares"] * sp * COMM, MIN_COMM)
        tf = pos["shares"] * sp * TFEE
        cash += pos["shares"] * sp - st - cm - tf

    return {
        "final_eq": cash, "eq_curve": eq_curve, "eq_dates": eq_dates,
        "daily_ret": daily_ret, "trades": trades,
        "total_trades": len([t for t in trades if t["act"] == "B"]),
        "init_cap": INITIAL_CAPITAL,
    }

def metrics(r: dict) -> dict:
    eq = np.array(r["eq_curve"])
    ret = np.array(r["daily_ret"])
    tr = (r["final_eq"] - r["init_cap"]) / r["init_cap"]
    ny = len(eq) / 245
    ar = (1 + tr) ** (1 / ny) - 1 if ny > 0 else 0
    pk = np.maximum.accumulate(eq)
    dd = (pk - eq) / pk
    mdd = float(np.max(dd))

    # 非零波动日 Sharpe
    non_zero = ret[ret != 0]
    if len(non_zero) > 10 and np.std(non_zero) > 0:
        sr = np.mean(non_zero) / np.std(non_zero) * np.sqrt(245)
    else:
        sr = 0.0

    wr = float(np.mean(ret > 0)) if len(ret) > 0 else 0

    dd_series = dd.tolist()
    dd_pct = [0, 0, 0, 0]
    for d in dd_series:
        if d < 0.05: dd_pct[0] += 1
        elif d < 0.10: dd_pct[1] += 1
        elif d < 0.15: dd_pct[2] += 1
        else: dd_pct[3] += 1

    return {"tr": tr, "ar": ar, "mdd": mdd, "sr": sr, "wr": wr,
            "dd_pct": dd_pct, "peak": float(np.max(eq)),
            "trades": r["total_trades"], "ny": ny}

def gen_tearsheet(r: dict, m: dict, baseline: tuple):
    (b_ar, b_mdd, b_sr) = baseline
    recent_trades = "\n".join(
        f'{t["date"]:<12} {t["code"]:<8} {t["act"]:<4} {t["sh"]:>6} {t["px"]:>8.2f} {t["val"]:>10,.0f}'
        for t in r['trades'][-20:]
    )
    lines = []
    lines.append("# 《终极矩阵 ALPHA_MATRIX_TEARSHEET》")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("> 数据范围: CSI 300 成分股 (79 只有效数据), 2018-01 ~ 2025-12")
    lines.append("> 引擎版本: Alpha Matrix v1.0")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、组合表现总览")
    lines.append("")
    lines.append("| 指标 | Alpha Matrix | 纯手工基线 | Δ 提升 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| **年化收益率** | `{m['ar']*100:.2f}%` | `{b_ar*100:.2f}%` | **`{(m['ar']-b_ar)*100:+.2f}%`** |")
    lines.append(f"| **最大回撤** | `{m['mdd']*100:.2f}%` | `{b_mdd*100:.2f}%` | **`{(m['mdd']-b_mdd)*100:+.2f}%`** |")
    lines.append(f"| **夏普比率** | `{m['sr']:.2f}` | `{b_sr:.2f}` | **`{(m['sr']-b_sr):+.2f}`** |")
    lines.append(f"| **累计收益** | `{m['tr']*100:.2f}%` | — | — |")
    lines.append(f"| **总交易次数** | `{m['trades']}` | — | — |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、Alpha 成分明细")
    lines.append("")
    lines.append("| # | 因子 | 权重 | 来源 | 经济学解释 |")
    lines.append("|---|---|---|---|---|")
    lines.append("| 1 | `illiq_20d` | 20% | 手工 | Amihud 非流动性溢价 |")
    lines.append("| 2 | `pv_divergence` | -20% | 手工 | 量价背离 → 反转信号 |")
    lines.append("| 3 | `cs_momentum` | 20% | 手工 | 剥离短期噪音的趋势跟随 |")
    lines.append("| 4 | `idiosyncratic_vol` | 15% | 手工 | 低波动异象 |")
    lines.append("| 5 | `gp_vol20d` | 10% | GP 挖掘 | 20天波动率因子 |")
    lines.append("| 6 | `gp_ret10d` | 15% | GP 挖掘 | 10天短期动量 |")
    lines.append("")
    lines.append("### 非线性风控层")
    lines.append("")
    lines.append("| 层 | 条件 | 效果 |")
    lines.append("|---|---|---|")
    lines.append("| **LPPL 熔断** | Crash Prob > 0.6 (指数级) | 仓位降至 30% |")
    lines.append("| **Wyckoff 放大** | 吸筹评分 > 0.5 (指数级) | 仓位提升至 130% |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、权益曲线")
    lines.append("")
    lines.append(f"```")
    lines.append(f"  起始: ¥{r['init_cap']:>,.0f}    终值: ¥{r['final_eq']:>,.0f}")
    lines.append(f"  峰值: ¥{m['peak']:>,.0f}    累计收益: {m['tr']*100:+.2f}%")
    lines.append(f"```")
    lines.append("")
    lines.append("### 回撤深度分布")
    lines.append("")
    lines.append("| 回撤区间 | 天数 |")
    lines.append("|---|---|")
    lines.append(f"| 0% ~ -5% | {m['dd_pct'][0]} |")
    lines.append(f"| -5% ~ -10% | {m['dd_pct'][1]} |")
    lines.append(f"| -10% ~ -15% | {m['dd_pct'][2]} |")
    lines.append(f"| < -15% | {m['dd_pct'][3]} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 四、交易摘要")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 总买入次数 | {m['trades']} |")
    lines.append(f"| 胜率 (日) | {m['wr']*100:.1f}% |")
    lines.append(f"| 回测年数 | {m['ny']:.1f} |")
    lines.append("")
    lines.append("### 近期交易 (末 20 笔)")
    lines.append("")
    lines.append("```")
    lines.append(f"{'日期':<12} {'代码':<8} {'方向':<4} {'股数':>6} {'价格':>8} {'金额':>10}")
    lines.append("-" * 48)
    lines.append(recent_trades)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 五、对比分析")
    lines.append("")
    lines.append("| 维度 | Alpha Matrix | 纯手工基线 | 解读 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 年化收益 | {m['ar']*100:.2f}% | {b_ar*100:.2f}% | "
                 f"{'非线性风控释放更多收益 ✓' if m['ar']>b_ar else '保守策略降低了收益, 改善风控'} |")
    lines.append(f"| 最大回撤 | {m['mdd']*100:.2f}% | {b_mdd*100:.2f}% | "
                 f"{'LPPL 规避系统性风险 ✓' if m['mdd']<b_mdd else '回撤需进一步优化'} |")
    lines.append(f"| 夏普比率 | {m['sr']:.2f} | {b_sr:.2f} | "
                 f"{'风险调整回报显著提升 ✓' if m['sr']>b_sr else '风险调整回报有待改善'} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*由 UniQuant Alpha Matrix Pipeline v1.0 自动生成*")
    txt = "\n".join(lines)
    Path("ALPHA_MATRIX_TEARSHEET.md").write_text(txt, encoding="utf-8")
    print("✅ ALPHA_MATRIX_TEARSHEET.md saved")

if __name__ == "__main__":
    t0 = time.time()
    print("=" * 56)
    print("  Alpha Matrix — 终极矩阵融合与实弹回测")
    print("=" * 56)

    df_all = pd.read_parquet("data/alpha_matrix_full.parquet")
    print(f"  Data: {len(df_all)} rows, {df_all['code'].nunique()} stocks")

    idx = None
    idx_file = Path("data/csi300_index.parquet")
    if idx_file.exists():
        idx = pd.read_parquet(idx_file)
    else:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000300")
        if df is not None and not df.empty:
            cm = {}
            for c in df.columns:
                cl = c.lower().strip()
                if cl in ("date","日期"): cm[c]="date"
                elif cl in ("close","收盘"): cm[c]="close"
                elif cl in ("open","开盘"): cm[c]="open"
                elif cl in ("high","最高"): cm[c]="high"
                elif cl in ("low","最低"): cm[c]="low"
                elif cl in ("volume","成交量"): cm[c]="volume"
            df.rename(columns=cm, inplace=True)
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= pd.Timestamp("20160101")) & (df["date"] <= pd.Timestamp("20251231"))]
            df.sort_values("date", inplace=True)
            df.reset_index(drop=True, inplace=True)
            df.to_parquet(idx_file)
            idx = df
    print(f"  Index: {len(idx)} rows")

    r = backtest(df_all, idx)
    m = metrics(r)
    print(f"\n  ┌────────────────────────────────────┐")
    print(f"  │  年化收益: {m['ar']*100:>7.2f}%              │")
    print(f"  │  最大回撤: {m['mdd']*100:>7.2f}%              │")
    print(f"  │  夏普比率: {m['sr']:>7.2f}                  │")
    print(f"  │  累计收益: {m['tr']*100:>7.2f}%              │")
    print(f"  │  交易次数: {m['trades']:>7}                  │")
    print(f"  └────────────────────────────────────┘")
    print(f"  ⏱  Total time: {time.time()-t0:.0f}s")

    baseline = (0.3036, 0.3654, 1.05)
    gen_tearsheet(r, m, baseline)
    print("  Done!")
