"""隔夜/日内因子 — 短窗口 OOS 验证 (预注册 2026-08-25 冻结)。

数据: data/lake/quotes/minutedaily_full/ (本地 lc5 + 服务器拼接, ~267 交易日)
定位: 样本外检验 (该窗口从未参与 P1-P8 任何因子开发), 非独立发现

因子与预期方向 (中国隔夜文献: A 股隔夜均值为负、隔夜情绪反转、日内动量):
  F1 on_mom_10    = Σ on,    10d   dir=-1 @fwd5
  F2 on_mom_20    = Σ on,    20d   dir=-1 @fwd5
  F3 intra_mom_20 = Σ intra, 20d   dir=+1 @fwd5 与 fwd21 双报
门限 (短窗口适配, 统计功效受限如实披露):
  G1 NW-t(lag=h) >= 2.5 (主视野)
  G2 前后半符号一致且各自方向正确
  G3 动量残差 NW-t >= 1.5 同号
  不做 PBO (窗口不足切窗), 已披露
QA 硬性前置: 拼接点前后各20日 |mean(on)| 差异 < 3x 全样本 std; 违反则全部作废。
多重比较: 主检验 4 次, NW-t>=2.5 对应 alpha 约 0.012/次, 如实披露。
裁决: 任一因子过 -> 记候选; 全败 -> 隔夜维度在本窗口证伪。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.factor_mining.conditional_stats import newey_west_t  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data/lake/quotes/minutedaily_full"
OUT_PATH = PROJECT_ROOT / "results/factor_mining/overnight_validation.json"

FACTORS = [
    {"id": "F1_on_mom_10", "col": "on", "win": 10, "direction": -1},
    {"id": "F2_on_mom_20", "col": "on", "win": 20, "direction": -1},
    {"id": "F3_intra_mom_20", "col": "intra", "win": 20, "direction": +1},
]
G1_NWT = 2.5
G3_NWT = 1.5


def build_panel() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("*.parquet"))
    parts = []
    for p in files:
        d = pd.read_parquet(p)
        d["code"] = p.stem
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


def splice_qa(panel: pd.DataFrame, splice_date: str = "2026-02-25") -> dict:
    """接缝完整性 QA。"""
    on_daily = panel.groupby("date")["on"].mean().dropna()
    sd = pd.Timestamp(splice_date)
    pre = on_daily[(on_daily.index <= sd) & (on_daily.index > sd - pd.Timedelta(days=40))]
    post = on_daily[(on_daily.index > sd) & (on_daily.index < sd + pd.Timedelta(days=40))]
    overall_std = float(on_daily.std())
    gap = abs(float(pre.mean()) - float(post.mean()))
    ok = bool(gap < SPOICE_TOL * overall_std)
    return {
        "pre_mean_on": round(float(pre.mean()), 5),
        "post_mean_on": round(float(post.mean()), 5),
        "gap": round(gap, 5), "overall_std": round(overall_std, 5),
        "tolerance": round(SPOICE_TOL * overall_std, 5), "pass": ok,
    }


SPOICE_TOL = 3.0


def daily_ic(panel: pd.DataFrame, factor_col: str, fwd_col: str) -> pd.Series:
    sub = panel[["date", factor_col, fwd_col]].dropna()
    ics = {}
    for dt, g in sub.groupby("date"):
        if len(g) < 30:
            continue
        fr = g[factor_col].rank()
        rr = g[fwd_col].rank()
        n = len(g)
        num = n * float(np.dot(fr, rr)) - float(fr.sum()) * float(rr.sum())
        den = np.sqrt(
            (n * float(np.dot(fr, fr)) - float(fr.sum()) ** 2)
            * (n * float(np.dot(rr, rr)) - float(rr.sum()) ** 2)
        )
        if den > 1e-12:
            ics[dt] = num / den
    return pd.Series(ics)


def residual_ic_series(panel: pd.DataFrame, factor_col: str, fwd_col: str,
                       mom_col: str = "mom20") -> tuple[list, list]:
    """逐日 raw 与 动量残差化 IC (秩回归, 同 P5/P6 方法)。"""
    raws, ress = [], []
    sub = panel[["date", factor_col, fwd_col, mom_col]].dropna()
    for dt, g in sub.groupby("date"):
        if len(g) < 30:
            continue
        fr = g[factor_col].rank()
        rr = g[fwd_col].rank()
        mr = g[mom_col].rank()
        n = len(g)
        num = n * float(np.dot(fr, rr)) - float(fr.sum()) * float(rr.sum())
        den = np.sqrt(
            (n * float(np.dot(fr, fr)) - float(fr.sum()) ** 2)
            * (n * float(np.dot(rr, rr)) - float(rr.sum()) ** 2)
        )
        if den <= 1e-12:
            continue
        raws.append(num / den)
        fv, mv = fr.to_numpy(), mr.to_numpy()
        if mv.var() > 1e-12:
            beta = np.cov(fv, mv)[0, 1] / mv.var()
            resd = fv - beta * mv
            rr2 = rr.to_numpy()
            num2 = n * float(np.dot(resd, rr2)) - float(resd.sum()) * float(rr2.sum())
            den2 = np.sqrt(
                (n * float(np.dot(resd, resd)) - float(resd.sum()) ** 2)
                * (n * float(np.dot(rr2, rr2)) - float(rr2.sum()) ** 2)
            )
            ress.append(num2 / den2 if den2 > 1e-12 else 0.0)
    return raws, ress


def main(argv=None):
    t0 = time.time()
    panel = build_panel()
    n_codes = panel["code"].nunique()
    dates = sorted(panel["date"].unique())

    # fwd 收益与动量
    panel = panel.sort_values(["code", "date"])
    for h in (5, 21):
        panel[f"fwd{h}"] = (
            panel.groupby("code")["close_px"].shift(-h) / panel["close_px"] - 1
        )
    panel["mom20"] = panel.groupby("code")["close_px"].pct_change(20)

    qa = splice_qa(panel)
    print(f"[1/3] 面板 {n_codes} 只 × {len(dates)} 天 ({dates[0].date()} → {dates[-1].date()})")
    print(f"      接缝QA: {'PASS' if qa['pass'] else 'FAIL'} "
          f"(pre={qa['pre_mean_on']} post={qa['post_mean_on']} tol={qa['tolerance']})")

    report = {"_meta": {"n_codes": int(n_codes), "n_days": len(dates),
                        "window": [str(dates[0].date()), str(dates[-1].date())],
                        "splice_qa": qa, "gates": "G1 nwt>=2.5; G2 halves; G3 resid>=1.5"},
              "factors": {}}
    terminated = not qa["pass"]
    for f in FACTORS:
        col = f"{f['col']}_mom_{f['win']}"
        panel[col] = panel.groupby("code")[f["col"]].rolling(f["win"]).sum().reset_index(level=0, drop=True)
        entry = {}
        for h in ([5] if f["col"] == "on" else [5, 21]):
            raws, ress = residual_ic_series(panel.dropna(subset=["mom20"]), col, f"fwd{h}")
            if len(raws) < 60:
                continue
            arr = np.asarray(raws)
            half = len(arr) // 2
            m1, m2 = float(arr[:half].mean()), float(arr[half:].mean())
            d = f["direction"]
            t_raw = newey_west_t(arr, lag=h)
            t_res = newey_west_t(np.asarray(ress), lag=h)
            g1 = bool(d * t_raw >= G1_NWT)
            g2 = bool(d * m1 > 0 and d * m2 > 0)
            g3 = bool(d * t_res >= G3_NWT)
            entry[f"fwd{h}"] = {
                "mean_ic": round(float(arr.mean()), 4),
                "nw_t": round(float(t_raw), 2),
                "resid_nw_t": round(float(t_res), 2),
                "half_means": [round(m1, 4), round(m2, 4)],
                "gates": {"G1": g1, "G2_halves": g2, "G3_resid": g3},
                "passed_all": bool(g1 and g2 and g3 and not terminated),
            }
        report["factors"][f["id"]] = entry
        s = "; ".join(f"{k}: IC={v['mean_ic']:+.4f} t={v['nw_t']:+.1f} "
                      f"{'PASS' if v['passed_all'] else 'FAIL'}"
                      for k, v in entry.items())
        print(f"  {f['id']:<18} {s}")

    report["_meta"]["terminated_by_qa"] = terminated
    report["_meta"]["elapsed_sec"] = round(time.time() - t0, 1)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    survivors = [fid for fid, e in report["factors"].items()
                 if any(v.get("passed_all") for v in e.values())]
    print(f"[3/3] 裁决: 幸存者={survivors if survivors else '无 (本窗口证伪)'}")
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
