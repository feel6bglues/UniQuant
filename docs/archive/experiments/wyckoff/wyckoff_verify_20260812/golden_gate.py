#!/usr/bin/env python3
"""D 组 — P2-5 golden baseline 前后对比门。

对 golden_20 全管线 (含 RDP) 捕获基线，与 git HEAD 中已提交 baseline_v0.parquet 对比。
P0 改动 (adapter direction gate / structural_adjust 关) 在 RDP 默认路径下不影响
Wyckoff→TradingSignal 链 (F12 三层绝缘), 预期 scalar 字段完全一致。

判定:
  PASS ⇔ total_signals/total_trades/total_return/final_cash 4 标量字段全窗一致
  FAIL ⇔ 任一窗口任一标量漂移 (需人工裁决是否故意)

用法: python3 scripts/wyckoff_verify_20260812/golden_gate.py
输出: results/wyckoff_verify_20260812/golden_gate.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"pandas required: {_ie}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from _common import write_out  # noqa: E402

SCALAR = ["total_signals", "total_trades", "total_return", "final_cash"]


def _run_git_show() -> Path:
    """取 git HEAD 中已提交 baseline_v0.parquet 到临时目录。"""
    tmp = ROOT / "results" / "wyckoff_verify_20260812" / "_tmp_head_baseline_v0.parquet"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "show", "HEAD:tests/benchmark/baseline_v0.parquet"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"git show baseline failed: {proc.stderr.decode()[:200]}")
    tmp.write_bytes(proc.stdout)
    return tmp


def main() -> int:
    head_ref = _run_git_show()
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "capture_baseline.py")],
        cwd=ROOT, check=True,
    )
    old = pd.read_parquet(head_ref)
    new = pd.read_parquet(ROOT / "tests" / "benchmark" / "baseline_v0.parquet")

    diffs: dict = {}
    ok = True
    for symbol in old["symbol"]:
        ro = old[old["symbol"] == symbol]
        rn = new[new["symbol"] == symbol]
        if not len(ro) or not len(rn):
            diffs[symbol] = {"error": "missing in one side"}
            ok = False
            continue
        row = {}
        for c in SCALAR:
            a = float(ro.iloc[0][c])
            b = float(rn.iloc[0][c])
            if abs(a - b) > 1e-6:
                row[c] = {"baseline": a, "current": b}
        if row:
            diffs[symbol] = row
            ok = False

    n = int(len(old))
    results = {
        "pre_registered": True,
        "gate": "P2-5 golden baseline 前后对比 (golden_20, 4 标量字段)",
        "n_symbols": n,
        "identical": ok,
        "diffs": diffs,
        "verdict": "PASS" if ok else "FAIL",
        "note": "P0 改动在 RDP 默认路径下不影响 Wyckoff→TradingSignal 链 (F12 三层绝缘); "
                "预期 4 标量字段全一致; 若 FAIL 需人工裁决是否故意 (如非 RDP 直连信号增减)",
    }
    path = write_out("golden_gate", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())