"""因子挖掘数据加载器 — 基于净化数据底座的真实数据挖掘输入。

2026-08-18 P0 净化后新建。与 Wyckoff 扫描池同源的净化符号池:
- 经 `StorageManager.get_symbols(exclude_indices=True)` (默认净剔除指数,
  符号级 SH 000xxx / SZ 399xxx 判定, 不误杀 000001.SZ 等 SZ 主板股)
- 过滤长历史不足的股票 (walk-forward train=504d + test=63d + fwd=5d)

用法:
    from scripts.factor_mining.data_loader import load_factor_universe
    df = load_factor_universe(as_of="2026-05-29", min_days=600)
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import StorageManager  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.data_loader")

_OHLCV_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]
MIN_DAYS_FOR_WALK_FORWARD = 504 + 63 + 10  # train + test + 余量


def load_universe(
    as_of: str | None = None,
    min_days: int = MIN_DAYS_FOR_WALK_FORWARD,
    max_workers: int = 32,
    data_dir: str = "./data",
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """并行加载全市场股票日线并合并为统一长表（净化池）。

    Args:
        as_of: 截断日期 (YYYY-MM-DD)。None=全部历史 (数据湖最新 2026-07-23)。
        min_days: 仅保留日线行数 >= min_days 的股票 (walk-forward 前置条件)。
        max_workers: 并行读取 worker 数。
        data_dir: 数据湖根目录。
        symbols: 显式符号列表 (默认走净化 get_symbols)。

    Returns:
        DataFrame: [date, code, open, high, low, close, volume, amount]
            按 code 排序、日期升序。已剔除指数。
    """
    storage = StorageManager(data_dir)
    all_symbols = symbols if symbols is not None else storage.get_symbols()

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {
            ex.submit(_load_one, storage, s, as_of): s for s in all_symbols
        }
        for fut in as_completed(fut_map):
            sym = fut_map[fut]
            try:
                df = fut.result()
            except Exception as e:  # 单只失败不阻塞
                logger.warning(f"load {sym} failed: {e}")
                continue
            if df is None or df.empty:
                continue
            if len(df) < min_days:
                continue
            df = df.copy()
            df["code"] = sym
            frames.append(df[_OHLCV_COLS + ["code"]])

    if not frames:
        return pd.DataFrame(columns=_OHLCV_COLS + ["code"])

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["code", "date"]).reset_index(drop=True)
    result["date"] = pd.to_datetime(result["date"])
    logger.info(
        f"净化池加载完成: {result['code'].nunique()} 只 × {result['date'].nunique()} 天 "
        f"= {len(result):,} 行 "
        f"({result['date'].min().date()} → {result['date'].max().date()})"
    )
    return result


def _load_one(
    storage: StorageManager, symbol: str, as_of: str | None
) -> pd.DataFrame | None:
    """读取单只股票日线，应用 as_of 截断。"""
    df = storage.read_data(symbol, data_type="daily")
    if df is None or df.empty:
        return None
    if "date" not in df.columns:
        return None
    df = df.sort_values("date")
    if as_of is not None:
        cutoff = pd.to_datetime(as_of)
        df = df[df["date"] <= cutoff]
    return df


def describe_universe(df: pd.DataFrame) -> dict:
    """输出加载后数据集的统计摘要 (供基线报告使用)。"""
    return {
        "n_symbols": int(df["code"].nunique()),
        "n_days": int(df["date"].nunique()),
        "n_rows": int(len(df)),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "median_rows_per_symbol": int(df.groupby("code").size().median()),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="因子挖掘数据加载预览")
    parser.add_argument("--as-of", default=None, help="截断日期 YYYY-MM-DD")
    parser.add_argument("--min-days", type=int, default=MIN_DAYS_FOR_WALK_FORWARD)
    parser.add_argument("--max-workers", type=int, default=32)
    args = parser.parse_args()

    df = load_universe(
        as_of=args.as_of, min_days=args.min_days, max_workers=args.max_workers
    )
    print(describe_universe(df))