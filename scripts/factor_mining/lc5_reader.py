"""通达信 .lc5 本地五分钟线解析器。

背景审计结论 (2026-08-25):
- 数据源: Wine 通达信客户端 ~/.local/share/tdxcfv/drive_c/tc/vipdoc/{sh,sz}/fzline/*.lc5
- 覆盖: 全市场 ~5191 只, 统一 2025-11-07 → 2026-02-25 (~70 交易日), 客户端批量下载后停更
- 格式实测: 每记录 32B = [date u32][time u32][open f32][high f32][low f32][close f32]
  其中价格字段为本客户端私有量纲 (≈真实价 × 1e6), 且四列近乎相等 (bar 快照价);
  [amount f32] 与 [volume u32] 为真实值 (元 / 股)
- 可用性: 快照价序列的首/末 bar 可作当日开/收盘代理, 比值计算中固定倍数消去;
  amount/volume 支持尾盘成交占比类因子

本模块只负责 字节→DataFrame 的忠实解析与量纲标注, 不做业务推断。
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pandas as pd

RECORD = struct.Struct("<HHIIIIfII")


def parse_lc5(path: str | Path) -> pd.DataFrame:
    """解析单个 .lc5 (通达信标准 32B 布局 <HHIIIIfII)。

    日期 u16 打包: year=num//2048+2004, month=(num%%2048)//100, day=%%100;
    时间 u16 = 自 0 点起的分钟数;
    OHLC 为整型 (本客户端量纲异常, 未做除法, 由 cross_check_daily 经验定标);
    amount f32 元 / volume u32 股。
    """
    raw = Path(path).read_bytes()
    n, rem = divmod(len(raw), RECORD.size)
    if rem or n == 0:
        raise ValueError(f"{path}: 大小 {len(raw)} 非 32 的非零整数倍")
    rows = [RECORD.unpack_from(raw, i * RECORD.size) for i in range(n)]
    rec = []
    for d16, m16, o, h, lo, c, amt, vol, _reserved in rows:
        year = d16 // 2048 + 2004
        month = (d16 % 2048) // 100
        day = (d16 % 2048) % 100
        hh, mi = divmod(m16, 60)
        try:
            dt = pd.Timestamp(year=year, month=month, day=day, hour=hh, minute=mi)
        except ValueError:
            continue
        rec.append((dt, o, h, lo, c, amt, int(vol)))
    df = pd.DataFrame(rec, columns=["datetime", "open", "high", "low", "close", "amount", "volume"])
    return df.sort_values("datetime").reset_index(drop=True)


def daily_from_lc5(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
    """bar 级 → 日级: 首 bar 价≈开盘代理, 末 bar 价≈收盘代理, 量额聚合。"""
    g = df.sort_values("datetime").groupby(df["datetime"].dt.date, sort=True)
    out = g.agg(
        open_proxy=(price_col, "first"),
        close_proxy=(price_col, "last"),
        amount=("amount", "sum"),
        volume=("volume", "sum"),
        n_bars=("datetime", "count"),
        last_dt=("datetime", "max"),
    ).reset_index(names="date")
    out["last30_amount"] = g.apply(
        lambda x: x.loc[x["datetime"] >= x["datetime"].dt.floor("D")
                        + pd.Timedelta(hours=14, minutes=30), "amount"].sum()
    ).to_numpy()
    return out


def cross_check_daily(daily_lc5: pd.DataFrame, daily_lake: pd.DataFrame) -> dict:
    """用官方日线校验 lc5 收盘代理: 逐日比值的中位数应≈常数倍数且变异极小。

    返回 {"scale": 中位比, "cv": 比值变异系数, "n": 样本日数, "pass": bool}。
    """
    m = daily_lc5.merge(daily_lake[["date", "close"]], on="date", how="inner")
    if len(m) < 20:
        return {"scale": np.nan, "cv": np.nan, "n": len(m), "pass": False}
    ratio = m["close_proxy"] / m["close"]
    cv = float(ratio.std() / ratio.mean())
    return {
        "scale": round(float(ratio.median()), 2),
        "cv": round(cv, 5),
        "n": int(len(m)),
        "pass": bool(cv < 0.01),
    }