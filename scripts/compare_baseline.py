#!/usr/bin/env python3
"""
基线比对脚本 — compare_baseline.py

比较两个基线版本的数值一致性。
用于验证重构/修改是否改变了系统输出。

用法:
  python scripts/compare_baseline.py                           # v0 vs v0 (自检)
  python scripts/compare_baseline.py --v1 baseline_v0 --v2 baseline_v1
  python scripts/compare_baseline.py --list                    # 列出所有基线
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

BASELINE_DIR = Path(__file__).resolve().parent.parent / "tests" / "benchmark"

COMPARE_FIELDS = [
    "success",
    "total_signals",
    "total_trades",
    "total_return",
    "final_cash",
    "equity_curve_len",
]

# 浮点数容差
RTOL = 1e-5
ATOL = 1e-8


def list_baselines():
    files = sorted(BASELINE_DIR.glob("baseline_*.parquet"))
    if not files:
        print("未找到基线文件")
        return
    print("可用基线:")
    for f in files:
        df = pd.read_parquet(f)
        print(f"  {f.name}: {len(df)} 只股票, {int(df['success'].sum())} 成功")


def load_baseline(version: str) -> pd.DataFrame:
    path = BASELINE_DIR / f"baseline_{version}.parquet"
    if not path.exists():
        print(f"基线文件不存在: {path}")
        sys.exit(1)
    return pd.read_parquet(path)


def compare_baselines(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    label1: str = "v0",
    label2: str = "v1",
) -> Tuple[bool, List[str]]:
    issues = []
    all_pass = True

    syms1 = set(df1["symbol"])
    syms2 = set(df2["symbol"])

    only_in_1 = syms1 - syms2
    only_in_2 = syms2 - syms1

    if only_in_1:
        issues.append(f"仅在 {label1} 中存在 ({len(only_in_1)}): {sorted(only_in_1)[:5]}...")
        all_pass = False
    if only_in_2:
        issues.append(f"仅在 {label2} 中存在 ({len(only_in_2)}): {sorted(only_in_2)[:5]}...")
        all_pass = False

    common = syms1 & syms2
    idx1 = df1.set_index("symbol")
    idx2 = df2.set_index("symbol")

    for symbol in sorted(common):
        row1 = idx1.loc[symbol]
        row2 = idx2.loc[symbol]

        # 比较标量字段
        for field in COMPARE_FIELDS:
            if field not in row1.index or field not in row2.index:
                continue
            v1 = row1[field]
            v2 = row2[field]
            if field == "success":
                if bool(v1) != bool(v2):
                    issues.append(f"{symbol} {field}: {v1} vs {v2}")
                    all_pass = False
            elif field == "total_return":
                if not np.isclose(v1, v2, rtol=RTOL, atol=ATOL):
                    issues.append(f"{symbol} {field}: {v1:.6%} vs {v2:.6%}")
                    all_pass = False
            elif isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                if not np.isclose(float(v1), float(v2), rtol=RTOL, atol=ATOL):
                    issues.append(f"{symbol} {field}: {v1} vs {v2}")
                    all_pass = False
            elif v1 != v2:
                issues.append(f"{symbol} {field}: {v1} vs {v2}")
                all_pass = False

        # 比较 equity_curve
        ec1 = _safe_get_list(row1, "equity_curve")
        ec2 = _safe_get_list(row2, "equity_curve")
        if len(ec1) != len(ec2):
            issues.append(f"{symbol} equity_curve length: {len(ec1)} vs {len(ec2)}")
            all_pass = False
        elif len(ec1) > 0:
            diff = np.max(np.abs(np.array(ec1) - np.array(ec2)))
            if diff > ATOL:
                issues.append(f"{symbol} equity_curve max_diff: {diff:.6f}")
                all_pass = False

        # 比较 trade 数量
        trades1 = _safe_get_list(row1, "trades")
        trades2 = _safe_get_list(row2, "trades")
        if len(trades1) != len(trades2):
            issues.append(f"{symbol} trades count: {len(trades1)} vs {len(trades2)}")
            all_pass = False

        # 比较信号数量
        sigs1 = _safe_get_list(row1, "signals")
        sigs2 = _safe_get_list(row2, "signals")
        if len(sigs1) != len(sigs2):
            issues.append(f"{symbol} signals count: {len(sigs1)} vs {len(sigs2)}")
            all_pass = False

    return all_pass, issues


def _safe_get_list(row, key: str) -> list:
    val = row.get(key, [])
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, list):
        return val
    return []


def main():
    parser = argparse.ArgumentParser(description="基线比对")
    parser.add_argument("--v1", default="v0", help="基线版本1 (默认: v0)")
    parser.add_argument("--v2", default="v0", help="基线版本2 (默认: v0, 自检模式)")
    parser.add_argument("--list", action="store_true", help="列出所有基线")
    parser.add_argument("--rtol", type=float, default=RTOL, help="相对容差")
    parser.add_argument("--atol", type=float, default=ATOL, help="绝对容差")

    args = parser.parse_args()

    if args.list:
        list_baselines()
        return

    df1 = load_baseline(args.v1)
    df2 = load_baseline(args.v2)

    all_pass, issues = compare_baselines(df1, df2, args.v1, args.v2)

    print(f"比对 {args.v1} vs {args.v2}")
    print(f"  股票数: {len(df1)} vs {len(df2)}")
    print(f"  结果: {'✓ 一致' if all_pass else '✗ 不一致'}")
    if issues:
        print(f"\n差异 ({len(issues)}):")
        for issue in issues[:20]:
            print(f"  - {issue}")
        if len(issues) > 20:
            print(f"  ... 还有 {len(issues)-20} 个差异")
    else:
        print("  所有字段完全一致")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
