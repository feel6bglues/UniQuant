"""证据固化脚本：复现 DATA_SOURCE_CONVERGENCE_EVALUATION_REPORT 的实测签名。

用途：预注册评估报告的可复现存证。仅读取本地数据，不修改任何仓库文件。

执行：`.venv/bin/python scratch/verify_mootdx_pytdx_bugs.py`

覆盖签名：
  S1 Volume 100 倍量纲（mootdx 日线 手 vs 数据湖 股）
  S2 mootdx_local 日期过滤失效根因（DatetimeIndex，'date' in df.columns 恒 False）
  S3 StdReader.minute 形参名为 suffix（freq=5 静默降级为 1min）
  S4 GBBQ 原始文件列名为拼音（中文映射不命中）+ 原始 193,506 行 vs 入湖 193,295 行
  S5 上证指数 Bar = 历史交易日全集（vs trade_calendar.csv 差集实测）
  S6 环境版本（mootdx / pytdx）
"""

from __future__ import annotations

import glob
import struct
from importlib.metadata import version

import pandas as pd
from mootdx.reader import StdReader
from pytdx.reader import GbbqReader

TDXDIR = "/home/james/.local/share/tdxcfv/drive_c/tc"
LAKE_600519 = "data/lake/quotes/daily/600519.SH.parquet"
LAKE_GBBQ = "data/fq/gbbq.parquet"
CALENDAR_CSV = "data/trade_calendar.csv"


def s1_volume_scale(reader: StdReader) -> None:
    """S1: 湖 volume / mootdx volume 恒等于 100（手→股）。"""
    raw = reader.daily("600519").reset_index()
    raw["date"] = pd.to_datetime(raw.iloc[:, 0])
    lake = pd.read_parquet(LAKE_600519, columns=["date", "volume"])
    lake["date"] = pd.to_datetime(lake["date"])
    merged = raw[["date", "volume"]].rename(columns={"volume": "vol_raw"}).merge(
        lake.rename(columns={"volume": "vol_lake"}), on="date"
    )
    ratio = (merged["vol_lake"] / merged["vol_raw"]).dropna()
    print(
        f"S1 volume ratio: n={len(ratio)} mean={ratio.mean():.1f} "
        f"std={ratio.std():.2e}  (签名: 100.0, std≈0)"
    )


def s2_date_filter_root_cause(reader: StdReader) -> None:
    """S2: reader.daily() 返回 DatetimeIndex，列中无 'date'。"""
    df = reader.daily("600519")
    has_date_col = "date" in df.columns
    print(
        f"S2 date filter: isinstance(df.index, DatetimeIndex)="
        f"{isinstance(df.index, pd.DatetimeIndex)}, 'date' in df.columns={has_date_col} "
        f"(签名: False -> mootdx_local.py 过滤失效)"
    )


def s3_minute_suffix(reader: StdReader) -> None:
    """S3: freq=5 被 kwargs 吞 -> 1min；suffix=5 才是 5min。"""
    n_freq = len(reader.minute("600519", freq=5))
    n_suffix = len(reader.minute("600519", suffix=5))
    print(
        f"S3 minute: freq=5 -> {n_freq} rows (1min), suffix=5 -> {n_suffix} rows (5min) "
        f"(签名: 17040 / 3408)"
    )


def s4_gbbq_columns() -> None:
    """S4: 原始 gbbq 列名为拼音；原始行数 vs 入湖行数。"""
    df = GbbqReader().get_df(f"{TDXDIR}/T0002/hq_cache/gbbq")
    lake_rows = pd.read_parquet(LAKE_GBBQ).shape[0]
    print(
        f"S4 gbbq: raw rows={len(df)}, lake rows={lake_rows}, "
        f"cols[:5]={list(df.columns)[:5]} (签名: 拼音列名, 中文映射 0 命中)"
    )


def s5_index_calendar() -> None:
    """S5: 上证指数 Bar 日期 vs 交易日历差集。"""
    bars: list[str] = []
    with open(f"{TDXDIR}/vipdoc/sh/lday/sh000001.day", "rb") as fh:
        while True:
            chunk = fh.read(32)
            if len(chunk) < 32:
                break
            bars.append(str(struct.unpack("<I", chunk[0:4])[0]))
    idx = pd.to_datetime(pd.Series(sorted(set(bars))), format="%Y%m%d")
    cal = pd.read_csv(CALENDAR_CSV)
    col = next(c for c in cal.columns if "date" in c.lower())
    cal_d = pd.to_datetime(cal[col])
    only_cal = sorted(set(cal_d) - set(idx))
    future = [d for d in only_cal if d > idx.max()]
    print(
        f"S5 calendar: index bars={len(idx)} ({idx.min().date()} -> {idx.max().date()}), "
        f"calendar rows={len(cal_d)}, calendar-only={len(only_cal)} "
        f"(全部为指数末端之后的未来日: {len(future) == len(only_cal)}), "
        f"index-only={len(set(idx) - set(cal_d))} (签名: 历史差集 0)"
    )


def s6_versions() -> None:
    """S6: 工具链版本。"""
    lday_count = len(glob.glob(f"{TDXDIR}/vipdoc/*/lday/*.day"))
    print(
        f"S6 versions: mootdx={version('mootdx')}, pytdx={version('pytdx')}, "
        f"lday files={lday_count} (签名: pytdx=1.72, 5757)"
    )


def main() -> None:
    reader = StdReader(tdxdir=TDXDIR)
    s1_volume_scale(reader)
    s2_date_filter_root_cause(reader)
    s3_minute_suffix(reader)
    s4_gbbq_columns()
    s5_index_calendar()
    s6_versions()


if __name__ == "__main__":
    main()
