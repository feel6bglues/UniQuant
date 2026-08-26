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

from uniquant.brain.factors.financial_bridge import FinancialFactorBridge  # noqa: E402
from uniquant.data.lake.storage_manager import StorageManager  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.data_loader")

_OHLCV_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]
MIN_DAYS_FOR_WALK_FORWARD = 504 + 63 + 10  # train + test + 余量

# P11 基本面因子所需的额外财务列 (经 bridge extra_fields 并入日线主表)。
# 存量字段直接并入; *_ttm 流量字段由 bridge 按冻结口径先算 TTM。
EXTRA_FINANCIAL_FIELDS = [
    "revenue_ttm", "operating_cost_ttm", "net_profit_parent_ttm",
    "ocf_ttm", "ocf_ps_ttm",
    "total_assets", "total_shares", "free_float_shares",
]


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


def merge_financial_metrics(
    df: pd.DataFrame,
    extra_fields: list[str] | None = None,
    data_dir: str = "./data",
    max_workers: int = 32,
    financial_frames: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """把 data/lake/financial/{code}.parquet 经 FinancialFactorBridge 并入日线长表。

    P11 (2026-08-26): 为基本面因子提供预合并财务列。逐股 merge_asof
    (公告日优先, 缺失回退报告期+披露窗偏移, point-in-time 安全);
    无财务文件的股票保持原行, 新增列置 NaN。

    Args:
        df: load_universe 输出的日线长表 [date, code, ...]。
        extra_fields: 额外财务列 (标准名或 *_ttm)。None=仅 eps_ttm/bps/pe_ttm/pb。
        data_dir: 数据湖根目录。
        max_workers: 并行合并 worker 数。
        financial_frames: 显式财务帧覆盖 {code: DataFrame} (P12: 脚本侧
            派生筹码变化率后传入)。None=从 data/lake/financial 磁盘读取。

    Returns:
        与输入同序同长度; 追加财务列后的 DataFrame。
    """
    if df.empty:
        return df

    fin_dir = Path(data_dir) / "lake" / "financial"
    bridge = FinancialFactorBridge()
    groups = [(sym, g.copy()) for sym, g in df.groupby("code", sort=False)]

    def _load_fin(symbol: str) -> pd.DataFrame | None:
        if financial_frames is not None:
            return financial_frames.get(symbol)
        fin_path = fin_dir / f"{symbol}.parquet"
        if not fin_path.exists():
            return None
        try:
            return pd.read_parquet(fin_path)
        except Exception as e:
            logger.warning(f"read financial {symbol} failed: {e}")
            return None

    def _merge_one(symbol: str, daily: pd.DataFrame) -> pd.DataFrame:
        fin = _load_fin(symbol)
        if fin is None or fin.empty:
            return daily
        try:
            merged = bridge.process(
                daily, fin, price_col="close",
                extra_fields=extra_fields,
            )
            return merged if not merged.empty else daily
        except Exception as e:  # 单只失败不阻塞
            logger.warning(f"merge financial {symbol} failed: {e}")
            return daily

    result_frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_merge_one, s, g): s for s, g in groups}
        for fut in as_completed(fut_map):
            sym = fut_map[fut]
            try:
                result_frames.append(fut.result())
            except Exception as e:
                logger.warning(f"merge task {sym} failed: {e}")

    out = pd.concat(result_frames, ignore_index=True)
    n_fin = int(out["eps_ttm"].notna().sum()) if "eps_ttm" in out.columns else 0
    logger.info(f"财务列合并完成: {out['code'].nunique()} 只, eps_ttm 覆盖 {n_fin:,} 行")
    return out


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