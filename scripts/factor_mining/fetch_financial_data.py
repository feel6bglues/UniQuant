"""TDX 季度财务归档拉取器 — 填充 data/lake/financial/。

数据源: 通达信文件服务器 gpcw{YYYYMMDD}.zip 季度归档 (mootdx.affair)。
经双源交叉验证 (vs 东财线上, docs/analysis/FINANCIAL_DATA_ACQUISITION_PLAN.md §6):
核心字段与公告日期精确一致。

关键处理 (均经实测锁定, 见方案文档 v3 复核修正记录):
- 股票代码在归档 index (6位码) → 按桥接 MARKET_SUFFIX_MAP 规则补交易所后缀
- 列名 strip 尾随空格 + 重复列去重 (keep first)
- 公告日期为 YYMMDD 浮点 → 转 YYYYMMDD 整数 (否则桥接 _normalize_date_series 解析全 NaT)
- 25 字段与桥接 alias_to_standard 严格命中, 零 rename

用法:
    python3 scripts/factor_mining/fetch_financial_data.py            # 全量 2016Q1→最新
    python3 scripts/factor_mining/fetch_financial_data.py --smoke    # 最近 3 期
    python3 scripts/factor_mining/fetch_financial_data.py --start 20180101
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.fetch_financial_data")

ARCHIVE_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "tdx_cw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "lake" / "financial"
CHECKPOINT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "financial_fetch_checkpoint.json"

MIN_QUARTER = 20160101
MIN_ARCHIVE_BYTES = 100_000  # 过滤空壳归档 (如未来期占位文件)
SUFFIX_MAP = {"60": "SH", "68": "SH", "00": "SZ", "30": "SZ", "43": "BJ", "83": "BJ", "87": "BJ"}
_FILENAME_RE = re.compile(r"^gpcw(\d{8})\.zip$")


def period_from_filename(filename: str) -> int:
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ValueError(f"非法归档文件名: {filename}")
    return int(m.group(1))


def to_symbol(code6: str) -> str | None:
    """6 位码 → 带交易所后缀符号; 无法判定返回 None。"""
    suffix = SUFFIX_MAP.get(str(code6)[:2])
    return f"{code6}.{suffix}" if suffix else None


def convert_announcement_int(raw) -> float:
    """TDX 公告日期 YYMMDD 浮点 → YYYYMMDD 整数; 缺失/非法 → NaN。"""
    if raw is None:
        return np.nan
    try:
        fv = float(raw)
    except (TypeError, ValueError):
        return np.nan
    if np.isnan(fv) or fv <= 0:
        return np.nan
    iv = int(fv)
    if iv < 1000000:  # YYMMDD → 20YYMMDD (数据范围 ≥2016, 无世纪歧义)
        return float(20000000 + iv)
    return float(iv)


def prepare_archive_frame(df: pd.DataFrame, report_date: int | None = None) -> pd.DataFrame:
    """清洗单期归档: index→code 列、列名 strip、重复列去重、公告日转整数。"""
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    out = out.loc[:, ~out.columns.duplicated(keep="first")]
    out.index.name = "code"
    out = out.reset_index()
    for col in ("财报公告日期", "业绩快报公告日期", "业绩预告公告日期"):
        if col in out.columns:
            out[col] = out[col].map(convert_announcement_int)
    if report_date is not None:
        out["report_date"] = report_date
    return out


def select_archives(files: list[dict], start: int, end: int) -> list[dict]:
    targets = []
    for f in files:
        m = _FILENAME_RE.match(f.get("filename", ""))
        if not m:
            continue
        period = int(m.group(1))
        if start <= period <= end and int(f.get("filesize", 0)) >= MIN_ARCHIVE_BYTES:
            targets.append(f)
    return sorted(targets, key=lambda x: x["filename"])


def ensure_downloaded(targets: list[dict], cache_dir: Path, retries: int = 3) -> list[Path]:
    from mootdx import affair

    affair_mod = affair.Affair()
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for t in targets:
        name = t["filename"]
        dest = cache_dir / name
        expected = int(t.get("filesize", 0))
        if dest.exists() and dest.stat().st_size == expected:
            paths.append(dest)
            continue
        for attempt in range(1, retries + 1):
            try:
                affair_mod.fetch(downdir=str(cache_dir), filename=name)
                break
            except Exception as e:  # noqa: BLE001 — 网络源, 需宽捕获重试
                logger.warning("下载失败 %s 第%d次: %s", name, attempt, e)
                if attempt == retries:
                    raise
                time.sleep(2 * attempt)
        if dest.exists():
            paths.append(dest)
            logger.info("已下载 %s (%.1f MB)", name, dest.stat().st_size / 1e6)
    return paths


def build_dataset(paths: list[Path]) -> pd.DataFrame:
    """解析全部归档并纵向拼接; 输出含 code(带后缀)/report_date 的长表。"""
    from mootdx import affair

    affair_mod = affair.Affair()
    frames: list[pd.DataFrame] = []
    unmapped: set[str] = set()
    for p in paths:
        period = period_from_filename(p.name)
        raw = affair_mod.parse(downdir=str(p.parent), filename=p.name)
        prepared = prepare_archive_frame(raw, report_date=period)
        symbols = prepared["code"].map(to_symbol)
        unmapped |= set(prepared.loc[symbols.isna(), "code"].astype(str))
        prepared["code"] = symbols
        frames.append(prepared)
        logger.info("已解析 %s: %d 只", p.name, len(prepared))
    if unmapped:
        logger.warning("无法判定交易所后缀的代码 %d 个 (剔除): %s...", len(unmapped), sorted(unmapped)[:10])
    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.dropna(subset=["code"])
    return all_df


def write_symbol_parquets(all_df: pd.DataFrame, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    n_symbols = 0
    for symbol, g in all_df.groupby("code"):
        g = g.sort_values("report_date")
        dest = output_dir / f"{symbol}.parquet"
        tmp = dest.with_suffix(".parquet.tmp")
        g.to_parquet(tmp, index=False)
        tmp.rename(dest)
        n_symbols += 1
    return {"n_symbols": n_symbols, "n_rows": int(len(all_df))}


def save_checkpoint(periods: list[int]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps({"completed_periods": periods}, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TDX 季度财务归档拉取器")
    parser.add_argument("--start", type=int, default=MIN_QUARTER, help="起始报告期 YYYYMMDD")
    parser.add_argument("--end", type=int, default=20991231, help="结束报告期 YYYYMMDD")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--smoke", action="store_true", help="仅最近 3 期")
    args = parser.parse_args(argv)

    t0 = time.time()
    from mootdx import affair

    files = affair.Affair().files()
    logger.info("服务器归档总数: %d", len(files))
    targets = select_archives(files, start=args.start, end=args.end)
    if args.smoke:
        targets = targets[-3:]
    periods = [period_from_filename(t["filename"]) for t in targets]
    logger.info("目标归档 %d 期: %s ... %s", len(targets), periods[0], periods[-1])

    paths = ensure_downloaded(targets, ARCHIVE_CACHE_DIR, retries=args.retries)
    logger.info("下载完成 (%d/%d), 开始解析拼接...", len(paths), len(targets))

    all_df = build_dataset(paths)
    stats = write_symbol_parquets(all_df, OUTPUT_DIR)
    save_checkpoint(periods)

    logger.info(
        "完成: %d 期 → %d 只 × %d 行, %.1fs, 产物 %s",
        len(paths), stats["n_symbols"], stats["n_rows"], time.time() - t0, OUTPUT_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())