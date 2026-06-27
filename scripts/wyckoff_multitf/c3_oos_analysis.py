#!/usr/bin/env python3
"""C3: OOS Analysis — Spring strategy on 2015-2019 data vs SH index benchmark."""

import sys, json, time
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"

# Load IS results for comparison
IS_PATH = OUTPUT_DIR / "v4_results.json"
OOS_PATH = OUTPUT_DIR / "oos_results.json"
SH_PATH = DATA_LAKE / "000001.SH.parquet"


def load_sh_index():
    """Load SH index and compute 6-month forward returns for each month-end."""
    df = pd.read_parquet(SH_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    close = df['close'].values
    dates = df['date'].values
    sh_rets = {}
    for i in range(0, len(df)):
        d = pd.Timestamp(dates[i])
        fwd_i = min(i + 126, len(df) - 1)
        ret = (close[fwd_i] / close[i] - 1) * 100
        sh_rets[d.strftime('%Y-%m-%d')] = ret
    return sh_rets


def load_data(path):
    with open(path) as f:
        raw = json.load(f)
    return raw


def compute_oos_metrics(data, sh_rets, label):
    """Compute full analysis for a dataset."""
    obs = data['data']
    print(f"\n{'='*70}")
    print(f"[{label}] {data['meta']['n_obs']} obs, {data['meta']['n_stocks']} stocks")
    print(f"{'='*70}")

    # Phase distribution
    phase_rets = defaultdict(list)
    phase_springs = defaultdict(int)
    for o in obs:
        phase_rets[o['p']].append(o['f6'])
        if o['ds']:
            phase_springs[o['p']] += 1

    print(f"\n── 阶段分布与6月远期收益 ──")
    print(f"  {'阶段':<15} {'观察数':<8} {'平均收益':<10} {'正收益%':<10} {'Spring%':<10}")
    print(f"  {'-'*53}")
    for p in ['accumulation', 'markdown', 'markup', 'distribution', 'unknown']:
        rv = np.array(phase_rets.get(p, []))
        if len(rv) == 0:
            continue
        sp = phase_springs.get(p, 0) / len(rv) * 100
        print(f"  {p:<15} {len(rv):<8} {np.mean(rv):>+8.2f}% {(rv>0).mean()*100:<9.1f}% {sp:<8.1f}%")

    # Spring raw returns
    spring_rets = np.array([o['f6'] for o in obs if o['ds']])
    no_spring_rets = np.array([o['f6'] for o in obs if not o['ds']])

    print(f"\n── Spring原始收益 ──")
    print(f"  Spring事件数: {len(spring_rets)}")
    print(f"  Spring 6月收益: {np.mean(spring_rets):+.2f}% (中位数: {np.median(spring_rets):+.2f}%)")
    print(f"  正收益率: {(spring_rets>0).mean()*100:.1f}%")
    print(f"  非Spring 6月收益: {np.mean(no_spring_rets):+.2f}%")

    if len(spring_rets) > 10 and len(no_spring_rets) > 10:
        t_s, p_s = stats.ttest_ind(spring_rets, no_spring_rets, alternative='greater')
        print(f"  Spring vs 非Spring: t={t_s:.2f} p={p_s:.4f} {'✅' if p_s<0.05 else '❌'}")

    # SH index benchmark (match cutoff dates)
    sh_excess = []
    for o in obs:
        if not o['ds']:
            continue
        sh_ret = sh_rets.get(o['c'])
        if sh_ret is not None:
            sh_excess.append(o['f6'] - sh_ret)

    if sh_excess:
        se = np.array(sh_excess)
        print(f"\n── Spring vs 上证指数 ──")
        print(f"  匹配事件数: {len(se)}")
        print(f"  平均超额: {np.mean(se):+.2f}%")
        t_s, p_s = stats.ttest_1samp(se, 0) if len(se) > 10 else (0, 1)
        print(f"  超额t检验: t={t_s:.2f} p={p_s:.4f} {'✅' if p_s<0.05 else '❌'}")

    # Market state decomposition
    print(f"\n── 市场状态分解 (上证指数月收益 ±3%) ──")
    sh_monthly = _load_sh_monthly()
    states = _classify_market_states(sh_monthly)

    for state_name, thresh in [('牛市 (月>+3%)', 3), ('熊市 (月<-3%)', -3), ('震荡市', 0)]:
        if state_name == '震荡市':
            mask = (states['ret'] >= -3) & (states['ret'] <= 3)
        elif '牛市' in state_name:
            mask = states['ret'] > thresh
        else:
            mask = states['ret'] < thresh

        state_dates = set(states['date'][mask].tolist())
        state_dates_str = set(d.strftime('%Y-%m') for d in state_dates)

        spring_in_state = []
        for o in obs:
            if o['ds']:
                om = o['c'][:7]
                if om in state_dates_str:
                    sh_ret = sh_rets.get(o['c'])
                    if sh_ret is not None:
                        spring_in_state.append(o['f6'] - sh_ret)

        if spring_in_state:
            sv = np.array(spring_in_state)
            t_st, p_st = stats.ttest_1samp(sv, 0) if len(sv) > 10 else (0, 1)
            print(f"  {state_name:<20} N={len(sv):<6} 超额={np.mean(sv):>+8.2f}%  t={t_st:.2f} p={p_st:.4f} {'✅' if p_st<0.05 else '❌'}")

    # Phase + Spring combo
    print(f"\n── 阶段+Spring组合 ──")
    for p in ['accumulation', 'markdown', 'markup', 'distribution', 'unknown']:
        sv = np.array([o['f6'] for o in obs if o['ds'] and o['p'] == p])
        nv = np.array([o['f6'] for o in obs if not o['ds'] and o['p'] == p])
        if len(sv) < 3:
            continue
        print(f"  {p}: +Spring N={len(sv)} {np.mean(sv):+.2f}%  -Spring N={len(nv)} {np.mean(nv):+.2f}%", end="")
        if len(sv) >= 5 and len(nv) >= 5:
            t2, p2 = stats.ttest_ind(sv, nv, alternative='greater')
            print(f"  diff={np.mean(sv)-np.mean(nv):+.2f}% t={t2:.2f} p={p2:.4f} {'✅' if p2<0.05 else '❌'}", end="")
        print()

    return {
        'n_obs': data['meta']['n_obs'],
        'n_stocks': data['meta']['n_stocks'],
        'n_spring': int(len(spring_rets)),
        'spring_raw_mean': round(float(np.mean(spring_rets)), 4) if len(spring_rets) > 0 else 0,
        'spring_raw_median': round(float(np.median(spring_rets)), 4) if len(spring_rets) > 0 else 0,
        'spring_raw_pos_pct': round(float((spring_rets > 0).mean() * 100), 1) if len(spring_rets) > 0 else 0,
        'no_spring_mean': round(float(np.mean(no_spring_rets)), 4) if len(no_spring_rets) > 0 else 0,
        'sh_excess_mean': round(float(np.mean(sh_excess)), 4) if sh_excess else 0,
        'sh_excess_t': round(float(t_s), 4) if sh_excess and len(se) > 10 else 0,
        'sh_excess_p': round(float(p_s), 4) if sh_excess and len(se) > 10 else 1,
        'spring_vs_nosignal_t': round(float(t_s_orig := stats.ttest_ind(spring_rets, no_spring_rets, alternative='greater')[0]), 4) if len(spring_rets) > 10 and len(no_spring_rets) > 10 else 0,
        'spring_vs_nosignal_p': round(float(p_s_orig := stats.ttest_ind(spring_rets, no_spring_rets, alternative='greater')[1]), 4) if len(spring_rets) > 10 and len(no_spring_rets) > 10 else 1,
    }


def _load_sh_monthly():
    df = pd.read_parquet(SH_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['ym'] = df['date'].dt.to_period('M')
    monthly = df.groupby('ym').agg(
        close=('close', 'last'),
        date=('date', 'first')
    ).reset_index()
    monthly['ret'] = monthly['close'].pct_change() * 100
    return monthly.dropna()


def _classify_market_states(monthly):
    return monthly


def main():
    t0 = time.time()
    print("=" * 70)
    print("C3: 样本外检验 (2015-2019)")
    print("=" * 70)

    if not IS_PATH.exists():
        print(f"ERROR: IS数据 {IS_PATH} 不存在")
        sys.exit(1)
    if not OOS_PATH.exists():
        print(f"ERROR: OOS数据 {OOS_PATH} 不存在 — 请先运行 runner_oos.py")
        sys.exit(1)

    sh_rets = load_sh_index()
    print(f"上证指数已加载: {len(sh_rets)} 个交易日")

    is_data = load_data(IS_PATH)
    oos_data = load_data(OOS_PATH)

    is_metrics = compute_oos_metrics(is_data, sh_rets, "样本内 (IS 2020-2024)")
    oos_metrics = compute_oos_metrics(oos_data, sh_rets, "样本外 (OOS 2015-2019)")

    # Cross-period comparison
    print(f"\n{'='*70}")
    print("IS vs OOS 对比")
    print(f"{'='*70}")
    print(f"  {'指标':<25} {'样本内(2020-2024)':>20} {'样本外(2015-2019)':>20} {'差异':>12}")
    print(f"  {'-'*77}")
    for key, label in [
        ('n_spring', 'Spring事件数'),
        ('spring_raw_mean', 'Spring原始收益(均值)'),
        ('spring_raw_median', 'Spring原始收益(中位数)'),
        ('spring_raw_pos_pct', 'Spring正收益率(%)'),
        ('no_spring_mean', '非Spring平均收益'),
        ('sh_excess_mean', '超额收益(vs上证)'),
        ('sh_excess_t', '超额t统计量'),
    ]:
        iv = is_metrics.get(key, 'N/A')
        ov = oos_metrics.get(key, 'N/A')
        if isinstance(iv, (int, float)) and isinstance(ov, (int, float)):
            diff = ov - iv if isinstance(iv, float) else ''
            diff_str = f'{diff:>+11.2f}' if isinstance(diff, float) else ''
            iv_str = f'{iv:>20.2f}' if isinstance(iv, float) else f'{iv:>20}'
            ov_str = f'{ov:>20.2f}' if isinstance(ov, float) else f'{ov:>20}'
        else:
            iv_str = f'{str(iv):>20}'
            ov_str = f'{str(ov):>20}'
            diff_str = ''
        print(f"  {label:<25} {iv_str} {ov_str} {diff_str}")

    print(f"\n── 结论 ──")
    if oos_metrics.get('sh_excess_p', 1) < 0.05:
        print("✅ 样本外检验通过: Spring策略在2015-2019产生显著超额收益")
    else:
        print("❌ 样本外检验失败: Spring策略在2015-2019未产生显著超额收益")

    if oos_metrics.get('spring_raw_mean', 0) > is_metrics.get('spring_raw_mean', 0):
        print("📈 样本外Spring收益高于样本内 (策略更优)")
    else:
        print("📉 样本外Spring收益低于样本内 (策略衰减)")

    # Save
    out = {
        'meta': {'elapsed_seconds': round(time.time() - t0)},
        'in_sample': is_metrics,
        'out_of_sample': oos_metrics,
    }
    out_path = OUTPUT_DIR / 'c3_oos_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n结果已保存到 {out_path}")


if __name__ == '__main__':
    main()
