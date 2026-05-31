#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建财务数据湖并输出基础质量校验结果。"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.services.import_financial import FinancialFingerprint, TDXFinancialImporter
from uniquant.shared.constants import STOCK_LIST_FILE

DEFAULT_TDX_DIR = Path(os.environ.get("TDX_FINANCIAL_DIR", "/home/james/.local/share/tdxcfv/drive_c/tc"))


def load_stock_universe(stock_codes_file: Path) -> pd.DataFrame:
    df = pd.read_csv(stock_codes_file, encoding="utf-8-sig")
    filtered = df[df["type"].astype(str).eq("1")].copy()
    if "status" in filtered.columns:
        filtered = filtered[filtered["status"].eq(1)].copy()
    return filtered


def create_sample_stock_file(
    stock_codes_file: Path, meta_dir: Path, sample_size: int, seed: int
) -> Path:
    meta_dir.mkdir(parents=True, exist_ok=True)
    filtered = load_stock_universe(stock_codes_file)
    if sample_size <= 0 or sample_size >= len(filtered):
        target = filtered.sort_values("code").reset_index(drop=True)
    else:
        target = (
            filtered.sample(n=sample_size, random_state=seed)
            .sort_values("code")
            .reset_index(drop=True)
        )

    sample_file = meta_dir / f"stock_universe_{len(target)}.csv"
    target.to_csv(sample_file, index=False, encoding="utf-8-sig")
    return sample_file


def audit_output(output_dir: Path, stock_codes_file: Path) -> Dict[str, object]:
    allowed = load_stock_universe(stock_codes_file)
    allowed_codes = set()
    for raw in allowed["code"]:
        value = str(raw).strip().lower()
        if "." not in value:
            continue
        market, code = value.split(".", 1)
        allowed_codes.add(f"{code}.{market.upper()}")

    required_cols = {"code", "report_date"}
    row_counts = []
    col_counts = []
    summary = {
        "parquet_files": 0,
        "missing_required_cols": [],
        "invalid_code_files": [],
        "disallowed_code_files": [],
        "null_report_date_files": [],
        "duplicate_key_files": [],
        "unsorted_files": [],
        "empty_files": [],
        "row_count_stats": {},
        "column_count_stats": {},
    }

    for path in sorted(output_dir.glob("*.parquet")):
        summary["parquet_files"] += 1
        df = pd.read_parquet(path)
        row_counts.append(len(df))
        col_counts.append(len(df.columns))

        if df.empty:
            summary["empty_files"].append(path.name)
            continue

        missing = sorted(required_cols - set(df.columns))
        if missing:
            summary["missing_required_cols"].append(
                {"file": path.name, "missing": missing}
            )
            continue

        code = path.stem
        code_series = df["code"].astype(str)
        if df["code"].isna().any() or not code_series.eq(code).all():
            summary["invalid_code_files"].append(path.name)
        if code not in allowed_codes:
            summary["disallowed_code_files"].append(path.name)

        report_dates = pd.to_datetime(df["report_date"], errors="coerce")
        if report_dates.isna().any():
            summary["null_report_date_files"].append(path.name)
        if df.duplicated(subset=["code", "report_date"]).any():
            summary["duplicate_key_files"].append(path.name)
        if not report_dates.is_monotonic_increasing:
            summary["unsorted_files"].append(path.name)

    if row_counts:
        row_series = pd.Series(row_counts)
        summary["row_count_stats"] = {
            "min": int(row_series.min()),
            "median": float(row_series.median()),
            "max": int(row_series.max()),
            "mean": round(float(row_series.mean()), 2),
        }

    if col_counts:
        col_series = pd.Series(col_counts)
        summary["column_count_stats"] = {
            "min": int(col_series.min()),
            "median": float(col_series.median()),
            "max": int(col_series.max()),
            "mean": round(float(col_series.mean()), 2),
            "unique_counts": sorted({int(v) for v in col_series.tolist()}),
        }

    return summary


def load_failed_fingerprint_entries(fingerprint_path: Path) -> list[dict]:
    if not fingerprint_path.exists():
        return []

    payload = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    failed = [
        {"file": name, **meta}
        for name, meta in payload.items()
        if meta.get("status") == "failed"
    ]
    return sorted(failed, key=lambda item: item.get("updated_at", ""), reverse=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重建财务数据湖")
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="输出根目录，脚本会在其中创建 lake/financial 和 meta",
    )
    parser.add_argument(
        "--tdx-dir",
        type=Path,
        default=DEFAULT_TDX_DIR,
        help="通达信基础目录，默认使用本机已验证路径",
    )
    parser.add_argument(
        "--stock-codes-file",
        type=Path,
        default=STOCK_LIST_FILE,
        help="股票白名单文件，默认 data/all_stock_codes.csv",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=0,
        help="样本股票数，0 表示全量",
    )
    parser.add_argument("--seed", type=int, default=42, help="抽样种子")
    parser.add_argument("--workers", type=int, default=4, help="解析并发数")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重跑所有 gpcw 文件",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="执行前删除 output-root 下已有内容",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    output_dir = output_root / "lake" / "financial"
    meta_dir = output_root / "meta"
    fingerprint_path = output_root / "financial_fingerprint.json"

    if args.clean_output and output_root.exists():
        shutil.rmtree(output_root)

    output_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    stock_codes_file = create_sample_stock_file(
        stock_codes_file=args.stock_codes_file.resolve(),
        meta_dir=meta_dir,
        sample_size=args.sample_size,
        seed=args.seed,
    )

    importer = TDXFinancialImporter(
        tdx_dir=args.tdx_dir.resolve(),
        output_dir=output_dir,
        stock_codes_file=stock_codes_file,
    )
    importer.fingerprint = FinancialFingerprint(fingerprint_path)
    success, skipped, failed = importer.import_batch(
        limit=0,
        force=args.force,
        workers=args.workers,
    )

    quality = audit_output(output_dir, stock_codes_file)
    failed_sources = load_failed_fingerprint_entries(fingerprint_path)
    summary = {
        "mode": "sample" if args.sample_size > 0 else "full",
        "sample_size": args.sample_size,
        "workers": args.workers,
        "tdx_dir": str(args.tdx_dir.resolve()),
        "stock_codes_file": str(stock_codes_file),
        "output_root": str(output_root),
        "output_dir": str(output_dir),
        "fingerprint_file": str(fingerprint_path),
        "import_result": {
            "parse_success_files": success,
            "parse_skipped_files": skipped,
            "parse_failed_files": failed,
        },
        "failed_source_files": failed_sources,
        "quality": quality,
    }

    summary_path = meta_dir / "rebuild_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    quality_ok = not any(
        [
            quality["missing_required_cols"],
            quality["invalid_code_files"],
            quality["disallowed_code_files"],
            quality["null_report_date_files"],
            quality["duplicate_key_files"],
            quality["unsorted_files"],
            quality["empty_files"],
        ]
    )
    if args.sample_size > 0:
        return 0 if quality_ok else 1
    return 0 if quality_ok and failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
