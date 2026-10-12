#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 0 基线捕获: 冻结 data/lake 内容摘要 → results/migration/lake_baseline.json.

依据 `docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md` §5 Step 0.1。全程只读湖,
唯一副作用 = 写输出 json (目录自动创建)。采集内容:

- quotes/daily 与 quotes/index: 文件数 (daily 内指数 symlink 用 Path.is_symlink()
  排除后另计)、总行数、每文件 last_date 的 min/max、schema 唯一列集组合及计数;
- financial 文件数; fq/gbbq.parquet 行数;
- 股票池: **轻量法** (二选一之一) —— 不 import StorageManager, 直接扫描
  daily/*.parquet 排除 symlink+指数符号, 语义镜像
  `StorageManager.get_symbols(exclude_indices=True)`; 附 data/all_stock_codes.csv
  的 sha256 作为对账锚点;
- 量纲交叉指标: seed=42 从 daily 文件名抽样 ≥20 只, 计算 amount/close/volume
  的 p25/median/p75 (R1 单位契约对账基线锚点);
- 生成时间与 git HEAD hash。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.wyckoff_experiments._symbols import is_index_symbol  # noqa: E402

DEFAULT_LAKE_ROOT = PROJECT_ROOT / "data/lake"
DEFAULT_GBBQ_PATH = PROJECT_ROOT / "data/fq/gbbq.parquet"
DEFAULT_ALL_STOCK_CODES = PROJECT_ROOT / "data/all_stock_codes.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "results/migration/lake_baseline.json"

MAX_WORKERS_CAP = 16
SCALE_METRICS = ("amount", "close", "volume")


def list_parquet_files(directory: Path) -> tuple[list[Path], list[str]]:
    """列出目录下普通 parquet 文件与 symlink 文件名 (各按名称排序)。"""
    regular: list[Path] = []
    symlinks: list[str] = []
    if not directory.exists():
        return regular, symlinks
    for path in sorted(directory.glob("*.parquet")):
        if path.is_symlink():
            symlinks.append(path.name)
        else:
            regular.append(path)
    return regular, symlinks


def _read_parquet_meta(path: Path) -> dict[str, Any]:
    """单文件元数据: rows / last_date / 列名集合。"""
    parquet_file = pq.ParquetFile(str(path))
    columns = list(parquet_file.schema_arrow.names)
    rows = parquet_file.metadata.num_rows
    last_date: str | None = None
    if "date" in columns:
        series = pd.read_parquet(path, columns=["date"])["date"].dropna()
        if len(series) > 0:
            last_date = pd.Timestamp(series.max()).strftime("%Y-%m-%d")
    return {"rows": rows, "last_date": last_date, "columns": columns}


def scan_parquet_dir(directory: Path, *, max_workers: int = 16) -> dict[str, Any]:
    """并发扫描目录: 计数 (排除 symlink)、总行数、last_date 分布、schema 组合。"""
    regular, symlinks = list_parquet_files(directory)
    workers = max(1, min(max_workers, MAX_WORKERS_CAP))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        metas = list(pool.map(_read_parquet_meta, regular))

    schema_counts: dict[tuple[str, ...], int] = {}
    last_dates: list[str] = []
    total_rows = 0
    for meta in metas:
        total_rows += int(meta["rows"])
        key = tuple(sorted(set(meta["columns"])))
        schema_counts[key] = schema_counts.get(key, 0) + 1
        if meta["last_date"]:
            last_dates.append(meta["last_date"])

    variants = [
        {"columns": list(cols), "file_count": count}
        for cols, count in sorted(schema_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "dir": str(directory),
        "file_count": len(regular),
        "symlink_count": len(symlinks),
        "symlink_files": symlinks,
        "total_rows": total_rows,
        "last_date_min": min(last_dates) if last_dates else None,
        "last_date_max": max(last_dates) if last_dates else None,
        "schema_variants": variants,
    }


def compute_dimension_stats(
    frames: Iterable[pd.DataFrame],
) -> dict[str, dict[str, float | None]]:
    """amount/close/volume 合并样本的 p25/median/p75 (NaN 剔除, 线性插值)。"""
    parts: list[pd.DataFrame] = []
    for frame in frames:
        present = [m for m in SCALE_METRICS if m in frame.columns]
        if not present:
            continue
        parts.append(
            pd.DataFrame(
                {m: pd.to_numeric(frame[m], errors="coerce") for m in present}
            )
        )

    empty = {"p25": None, "median": None, "p75": None}
    if not parts:
        return {m: dict(empty) for m in SCALE_METRICS}
    combined = pd.concat(parts, ignore_index=True)

    stats: dict[str, dict[str, float | None]] = {}
    for metric in SCALE_METRICS:
        if metric not in combined.columns:
            stats[metric] = dict(empty)
            continue
        series = combined[metric].astype(float).dropna()
        if series.empty:
            stats[metric] = dict(empty)
        else:
            stats[metric] = {
                "p25": float(series.quantile(0.25)),
                "median": float(series.quantile(0.50)),
                "p75": float(series.quantile(0.75)),
            }
    return stats


def _read_scale_columns(path: Path) -> pd.DataFrame:
    available = set(pq.ParquetFile(str(path)).schema_arrow.names)
    columns = [m for m in SCALE_METRICS if m in available]
    if not columns:
        return pd.DataFrame(columns=list(SCALE_METRICS))
    return pd.read_parquet(path, columns=columns)


def sample_dimension_stats(
    daily_dir: Path, *, sample_n: int = 20, seed: int = 42, max_workers: int = 16
) -> dict[str, Any]:
    """从 daily 文件名按 seed 抽样, 读量纲三列计算分布指标。"""
    regular, _ = list_parquet_files(daily_dir)
    names = sorted(path.stem for path in regular)
    k = min(sample_n, len(names))
    sampled = random.Random(seed).sample(names, k) if k else []
    paths = [daily_dir / f"{symbol}.parquet" for symbol in sampled]

    workers = max(1, min(max_workers, MAX_WORKERS_CAP))
    frames: list[pd.DataFrame] = []
    if paths:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            frames = list(pool.map(_read_scale_columns, paths))

    return {
        "method": "sampled daily parquet files",
        "seed": seed,
        "n_sampled": len(sampled),
        "sampled_symbols": sampled,
        "metrics": compute_dimension_stats(frames),
    }


def list_stock_symbols(daily_dir: Path) -> list[str]:
    """股票池符号: daily 普通文件 (非 symlink) 剔指数, 排序。"""
    regular, _ = list_parquet_files(daily_dir)
    return sorted(path.stem for path in regular if not is_index_symbol(path.stem))


def collect_stock_pool(
    daily_dir: Path, all_stock_codes_csv: Path | None = None
) -> dict[str, Any]:
    """股票池快照: 数量 + 排序集合 sha256 (轻量法, 不 import StorageManager)。"""
    symbols = list_stock_symbols(daily_dir)
    pool: dict[str, Any] = {
        "method": (
            "lightweight (不 import StorageManager): 扫描 daily/*.parquet 排除 "
            "symlink+指数符号, 语义镜像 StorageManager.get_symbols(exclude_indices=True)"
        ),
        "count": len(symbols),
        "sha256": hashlib.sha256("\n".join(symbols).encode("utf-8")).hexdigest(),
    }
    if all_stock_codes_csv is not None and all_stock_codes_csv.exists():
        pool["all_stock_codes_csv"] = {
            "path": str(all_stock_codes_csv),
            "sha256": hashlib.sha256(all_stock_codes_csv.read_bytes()).hexdigest(),
        }
    else:
        pool["all_stock_codes_csv"] = None
    return pool


def parquet_row_count(path: Path) -> int | None:
    if not path.exists():
        return None
    return pq.ParquetFile(str(path)).metadata.num_rows


def git_head(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_baseline(
    lake_root: Path,
    *,
    gbbq_path: Path = DEFAULT_GBBQ_PATH,
    all_stock_codes_csv: Path | None = DEFAULT_ALL_STOCK_CODES,
    sample_n: int = 20,
    seed: int = 42,
    max_workers: int = 16,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """采集基线 (只读)。"""
    daily_dir = lake_root / "quotes" / "daily"
    index_dir = lake_root / "quotes" / "index"
    financial_dir = lake_root / "financial"

    financial_regular, financial_symlinks = list_parquet_files(financial_dir)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_head": git_head(project_root),
        "quotes_daily": scan_parquet_dir(daily_dir, max_workers=max_workers),
        "quotes_index": scan_parquet_dir(index_dir, max_workers=max_workers),
        "financial": {
            "dir": str(financial_dir),
            "file_count": len(financial_regular),
            "symlink_count": len(financial_symlinks),
        },
        "fq_gbbq": {"path": str(gbbq_path), "rows": parquet_row_count(gbbq_path)},
        "stock_pool": collect_stock_pool(daily_dir, all_stock_codes_csv),
        "dimension_stats": sample_dimension_stats(
            daily_dir, sample_n=sample_n, seed=seed, max_workers=max_workers
        ),
    }


def _print_summary(baseline: dict[str, Any], output: Path) -> None:
    daily = baseline["quotes_daily"]
    index = baseline["quotes_index"]
    dim = baseline["dimension_stats"]
    amount = dim["metrics"]["amount"]
    print(f"[baseline] output={output}")
    print(
        f"[baseline] quotes/daily: files={daily['file_count']} "
        f"symlinks={daily['symlink_count']} rows={daily['total_rows']} "
        f"last={daily['last_date_min']}..{daily['last_date_max']}"
    )
    print(
        f"[baseline] quotes/index: files={index['file_count']} "
        f"rows={index['total_rows']} last={index['last_date_max']}"
    )
    print(
        f"[baseline] financial files={baseline['financial']['file_count']}; "
        f"fq/gbbq rows={baseline['fq_gbbq']['rows']}"
    )
    pool = baseline["stock_pool"]
    print(
        f"[baseline] stock pool: count={pool['count']} "
        f"sha256={pool['sha256'][:16]}... (method: lightweight)"
    )
    print(
        f"[baseline] dimension sample: n={dim['n_sampled']} seed={dim['seed']} "
        f"amount median={amount['median']} p25={amount['p25']} p75={amount['p75']}"
    )
    print(f"[baseline] git_head={baseline['git_head']}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture read-only data lake baseline (migration Step 0.1)"
    )
    parser.add_argument("--lake-root", type=Path, default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gbbq", type=Path, default=DEFAULT_GBBQ_PATH)
    parser.add_argument("--all-stock-codes", type=Path, default=DEFAULT_ALL_STOCK_CODES)
    parser.add_argument("--sample-n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-workers", type=int, default=16)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    baseline = build_baseline(
        args.lake_root,
        gbbq_path=args.gbbq,
        all_stock_codes_csv=args.all_stock_codes,
        sample_n=args.sample_n,
        seed=args.seed,
        max_workers=args.max_workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _print_summary(baseline, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
