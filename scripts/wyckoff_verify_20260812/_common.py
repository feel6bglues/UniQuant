#!/usr/bin/env python3
"""共享工具 — P0 验证 (2026-08-12 深入再研究验收)。

统一五窗配置 / clean 池口径 / 输出 JSON 落盘。只读扫描 CSV，禁止改写。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"pandas required: {_ie}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "wyckoff_experiments"))

from _symbols import is_index_series  # noqa: E402

WINDOWS = {
    "W1": ("results/wyckoff_xs/wyckoff_scan_all.csv", "2026-04-30"),
    "W2": ("results/wyckoff_xs2/wyckoff_scan_all.csv", "2026-03-31"),
    "W3": ("results/wyckoff_xs3/wyckoff_scan_all.csv", "2026-05-29"),
    "X4": ("results/wyckoff_xs4/wyckoff_scan_all.csv", "2025-06-30"),
    "X5": ("results/wyckoff_xs5/wyckoff_scan_all.csv", "2024-12-31"),
}

SIG_TYPES = ["distribution", "markdown", "leader", "accumulation", "markup", "spring"]
BUY_DIRECTIONS = {"做多", "买入", "轻仓试探"}


def clean_pool(df: pd.DataFrame) -> pd.DataFrame:
    """clean 池: fwd_20d 非空 ∩ 剔 ETF ∩ 剔指数 (符号级, 不误杀 SZ 主板股)。"""
    out = df[df["fwd_20d"].notna()].copy()
    out = out[~out["is_etf"].fillna(False)].copy()
    out = out[~is_index_series(out["symbol"])].copy()
    return out


def load_window(name: str) -> pd.DataFrame:
    path = ROOT / WINDOWS[name][0]
    if not path.exists():
        raise FileNotFoundError(f"missing scan: {path}")
    return clean_pool(pd.read_csv(path))


def sig_mask(df: pd.DataFrame, sig_type: str) -> pd.Series:
    if sig_type == "leader":
        return df["relative_strength"].astype(str) == "leader"
    return df["signal_type"].astype(str) == sig_type


def write_out(name: str, payload: dict) -> Path:
    out = ROOT / "results" / "wyckoff_verify_20260812"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
