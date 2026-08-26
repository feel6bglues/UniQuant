"""H-A 实盘对账监控 — 目标信号 vs 实际持仓的漂移报告。

工程化第三件 (2026-08-26)。职责:
1. diff_signal_files: 相邻两日信号的组合差异事件 (建仓/清仓/调仓名单)
2. build_reconciliation: 最新目标组合 vs 账户持仓快照 (CSV) 的逐标的对账

用法:
    python3 scripts/canslim/reconcile_ha.py \\
        --signal results/h_a_signals/2026-07-23.json \\
        --positions positions.csv --prices prices.csv [--drift-tol-pp 1.0]

positions.csv 格式: code,shares[,cash]  (cash 仅需一行给出, 单位元)
prices.csv 格式: code,close  (缺省从 data/lake/quotes/daily/{code}.parquet 取尾价)

规则 (工程约定, 非 alpha 声明):
- HOLD 模式: |实际权重 − 目标权重| > drift_tol_pp → DRIFT; 目标有仓无 → MISSING;
  账户有目标外 → EXTRA
- CASH 模式: 任何非零持仓均 EXTRA
- 输出 JSON 报告 + 控制台表; exit code: 0=GREEN, 1=有异常行
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DRIFT_TOL_PP = 1.0


def _load_signal(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    tgt = payload.get("target_portfolio", {}).get("target", [])
    hot = bool(payload.get("state", {}).get("hot_bull",
                                            not str(payload.get("action", "")).startswith("CASH")))
    return {"date": payload.get("state", {}).get("as_of"), "hot": hot,
            "target": {t["code"]: float(t["weight"]) for t in tgt}}


def diff_signal_files(old_path: Path, new_path: Path) -> list[dict]:
    """相邻信号文件 → 状态转换/调仓事件列表 (单元素或 NOOP)。"""
    old, new = _load_signal(Path(old_path)), _load_signal(Path(new_path))
    if old["hot"] and not new["hot"]:
        return [{"event": "ENTER_CASH", "liquidate": sorted(old["target"])}]
    if not old["hot"] and new["hot"]:
        return [{"event": "ENTER_HOT", "open": sorted(new["target"])}]
    if old["hot"] and new["hot"]:
        added = sorted(set(new["target"]) - set(old["target"]))
        removed = sorted(set(old["target"]) - set(new["target"]))
        kept = sorted(set(old["target"]) & set(new["target"]))
        return [{"event": "REBALANCE", "added": added,
                 "removed": removed, "kept": kept}]
    return [{"event": "NOOP"}]


def load_positions(path: Path) -> tuple[pd.Series, float]:
    """positions.csv → (shares Series by code, cash)。"""
    df = pd.read_csv(path)
    cash = 0.0
    if "cash" in df.columns:
        vals = pd.to_numeric(df["cash"], errors="coerce").dropna()
        cash = float(vals.iloc[0]) if len(vals) else 0.0
    shares = pd.to_numeric(df.set_index("code")["shares"], errors="coerce").fillna(0.0)
    return shares[shares.index.notna()], cash


def load_prices_arg(prices: dict[str, float] | None, path: Path | None) -> dict[str, float]:
    if prices:
        return prices
    if path is None:
        return {}
    df = pd.read_csv(path)
    return {r["code"]: float(r["close"]) for _, r in df.iterrows()}


def build_reconciliation(
    signal_path: Path,
    positions_path: Path,
    prices: dict[str, float] | None = None,
    drift_tol_pp: float = DEFAULT_DRIFT_TOL_PP,
) -> dict:
    """对账核心: 返回逐标的 rows + summary。纯函数, 供 CLI 与测试复用。"""
    sig = _load_signal(Path(signal_path))
    shares, cash = load_positions(Path(positions_path))
    px = load_prices_arg(prices, None)

    mode = "CASH" if not sig["hot"] else "HOLD"
    target = sig["target"]

    all_codes = sorted(set(target) | set(shares[shares > 0].index))
    market_vals: dict[str, float] = {}
    for c in all_codes:
        s = float(shares.get(c, 0.0))
        p = px.get(c)
        market_vals[c] = s * p if p is not None else float("nan")
    known_mv = sum(v for v in market_vals.values() if v == v)
    total_value = known_mv + cash

    rows: list[dict] = []
    n_missing = n_extra = n_drift = 0
    for c in all_codes:
        mv = market_vals[c]
        actual_w = (mv / total_value) if total_value > 0 and mv == mv else float("nan")
        tw = target.get(c)
        if mode == "CASH":
            status = "EXTRA" if (mv == mv and mv > 0) else "OK"
            row_tw = None
        elif tw is None:
            status = "EXTRA"
            row_tw = None
        else:
            row_tw = tw
            if not (mv == mv) or float(shares.get(c, 0.0)) <= 0:
                status = "MISSING"
            else:
                drift_pp = (actual_w - tw) * 100.0
                status = "DRIFT" if abs(drift_pp) > drift_tol_pp else "OK"
        n_missing += status == "MISSING"
        n_extra += status == "EXTRA"
        n_drift += status == "DRIFT"
        rows.append({
            "code": c, "status": status,
            "target_weight": row_tw,
            "actual_weight": round(actual_w, 4) if actual_w == actual_w else None,
            "drift_pp": round((actual_w - tw) * 100.0, 2)
            if (row_tw is not None and actual_w == actual_w) else None,
            "shares": int(shares.get(c, 0.0)),
            "market_value": round(mv, 2) if mv == mv else None,
        })

    cash_weight = (cash / total_value) if total_value > 0 else None
    worst = max(
        (abs(r["drift_pp"]) for r in rows if r["drift_pp"] is not None),
        default=0.0,
    )
    return {
        "signal_date": sig["date"],
        "summary": {
            "mode": mode,
            "total_value": round(total_value, 2),
            "cash_weight": round(cash_weight, 4) if cash_weight is not None else None,
            "n_target": len(target),
            "n_missing": n_missing, "n_extra": n_extra, "n_drift": n_drift,
            "worst_abs_drift_pp": round(worst, 2),
            "drift_tol_pp": drift_tol_pp,
            "healthy": n_missing == 0 and n_extra == 0 and n_drift == 0,
        },
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-A 实盘对账")
    ap.add_argument("--signal", required=True, help="results/h_a_signals/{date}.json")
    ap.add_argument("--prev-signal", default=None, help="上一交易日信号 (可选, 输出转换事件)")
    ap.add_argument("--positions", required=True, help="code,shares[,cash] CSV")
    ap.add_argument("--prices", default=None, help="code,close CSV; 缺省读数据湖尾价")
    ap.add_argument("--drift-tol-pp", type=float, default=DEFAULT_DRIFT_TOL_PP)
    args = ap.parse_args(argv)

    events = None
    if args.prev_signal:
        events = diff_signal_files(Path(args.prev_signal), Path(args.signal))
        for ev in events:
            print("EVENT:", json.dumps(ev, ensure_ascii=False))

    px = load_prices_arg(None, Path(args.prices) if args.prices else None)
    rep = build_reconciliation(Path(args.signal), Path(args.positions), prices=px,
                               drift_tol_pp=args.drift_tol_pp)

    print(json.dumps(rep["summary"], ensure_ascii=False, indent=1))
    bad = [r for r in rep["rows"] if r["status"] != "OK"]
    if bad:
        print(f"\n{'code':<12} {'status':<8} {'tgt_w':>7} {'act_w':>7} {'drift_pp':>9}")
        for r in bad:
            tw = f"{r['target_weight']:.3f}" if r['target_weight'] is not None else "—"
            aw = f"{r['actual_weight']:.3f}" if r['actual_weight'] is not None else "—"
            dp = f"{r['drift_pp']:+.2f}" if r['drift_pp'] is not None else "—"
            print(f"{r['code']:<12} {r['status']:<8} {tw:>7} {aw:>7} {dp:>9}")

    out_dir = PROJECT_ROOT / "results" / "h_a_reconcile"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_fp = out_dir / f"reconcile_{rep['signal_date'] or 'unknown'}.json"
    if events is not None:
        rep["events"] = events
    out_fp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n报告 → {out_fp}")
    return 0 if rep["summary"]["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
