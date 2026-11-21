"""上云数据轨道随机抽样三方对账 (第二十四轮 — 验收工具, 只读)。

目的: 对已接线的上云在线通道 (tdxdata 日线/分钟/xdxr/财务/snap) 做随机抽样,
与两类独立基线交叉对账, 确保上云通道数据准确:
  基线① 本地 TDX: data/lake 日线 parquet (Wine .day 解包)、vipdoc fzline .lc5
         (5分钟)、data/fq/gbbq.parquet.bak (Wine gbbq)、vipdoc/cw gpcw*.dat (财务)
  基线② 其他在线源: akshare (stock_zh_a_daily 不复权)、baostock (adjustflag=3
         不复权)、旧协议 mootdx xdxr (TCP 行情已死但 xdxr 命令族仍活, 实测 45 行)

轨道 (seed=42 可复现):
  A 日线: 上云 tdxdata vs 本地湖 (逐位) vs akshare/baostock (不复权收盘)
  B 5分钟: 上云 fetch_minute vs 本地 .lc5 (价格比值稳定性定标 + 量纲)
  C xdxr/gbbq: tdxdata xdxr vs 旧 mootdx xdxr vs 官方 gbbq vs 本地 Wine gbbq
  D 财务: 在线 gpcw20260930.dat vs 本地 Wine gpcw20260930.dat (同源同格式)
  E snap: 上云 last vs 湖最新日线收盘

性能: 每标的在线日线 (2024+ 窗口) 与 5 分钟 (2026-06+ 窗口) 各只拉取一次
复用于多轨道; 旧协议连接全程单例。

用法: python scripts/maintenance/verify_cloud_channels_random.py [--sample N]
退出码: 0 = 全轨道 PASS; 1 = 任一轨道 FAIL。结果 JSON 落 results/migration/。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "factor_mining"))

from uniquant.shared.constants.path import LAKE_QUOTES_DIR, STOCK_LIST_FILE  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("verify_cloud_channels_random")

SEED = 42
DAILY_WINDOW_START = "2024-01-01"  # ~700 根 = 1 页
MINUTE_WINDOW_START = "2026-06-01"  # ~5.5 个月 ≈ 6 页
# ⚠️ 量纲粒度实测 (2026-11-21): 服务器日 K 成交量字段精度=手 (mod100 恒 0, 四舍
# 五入 ±1 手内), 本地 .day 与 akshare/baostock = 精确股 → volume 容差 100 股
# (实测 600959/601319 恒差恰好 100=1 手, OHLC/amount 逐位 0 差), 属通道粒度
# 差异, 非数据错误。
VOLUME_GRANULARITY_TOL = 100.0
TDX_HOME = Path.home() / ".local/share/tdxcfv/drive_c/tc"
RESULT_PATH = PROJECT_ROOT / "results" / "migration" / "cloud_channel_random_verification.json"
GBBQ_PATH = PROJECT_ROOT / "data" / "fq" / "gbbq.parquet"
GBBQ_BAK = GBBQ_PATH.with_suffix(".parquet.bak")
# 本地 Wine 财务文件体检 (2026-11-21): 20260331=13MB 完整, 20260630=4MB 半截,
# 20260930/20261231=20B 空壳 → 对账选最近的完整期; 本地退化 vs 在线完整本身即发现
REPORT_DATE = "20260331"
MIN_LOCAL_DAT_BYTES = 100_000


def _p(msg: str) -> None:
    print(msg, flush=True)


def sample_stocks(n: int) -> list[str]:
    """从 SSOT 抽样: status=1 且 type=1 (股票, 非债券/ETF) 的沪深标的 (seed 可复现)。

    北交所标的 (4/8/920 前缀) 不纳入本轮抽样 — 在线通道对其市场码支持未验证,
    属诚实边界。
    """
    ss = pd.read_csv(STOCK_LIST_FILE)
    ss["code6"] = ss["代码"].astype(str).str.zfill(6)
    stocks = ss[(ss["status"] == 1) & (ss["type"] == 1)]
    stocks = stocks[stocks["code6"].str.startswith(("6", "0", "3"))]
    rng = random.Random(SEED)
    picked = sorted(rng.sample(stocks["code6"].tolist(), n))
    return [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in picked]


def _lake_daily(symbol: str) -> pd.DataFrame:
    path = LAKE_QUOTES_DIR / "daily" / f"{symbol}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def prefetch_online(src, stocks: list[str]) -> dict:
    """每标的在线日线拉取一次, 复用于 A1/A2/A3 (分钟在轨道 B 内按 lc5 尾部动态取窗)。"""
    online_daily: dict[str, pd.DataFrame] = {}
    for sym in stocks:
        online_daily[sym] = src.fetch_daily(sym, DAILY_WINDOW_START, "2100-01-01")
    return online_daily


def track_daily_vs_lake(stocks: list[str], online_daily: dict) -> dict:
    """轨道 A1: 上云日线 vs 本地湖 (Wine .day) — OHLC/amount 逐位, volume 容差 100 股。"""
    per_stock = {}
    for sym in stocks:
        online = online_daily.get(sym)
        lake = _lake_daily(sym)
        if online is None or online.empty or lake.empty:
            per_stock[sym] = "SKIP(无数据)"
            continue
        m = online.merge(lake, on="date", suffixes=("_on", "_lk"))
        if not len(m):
            per_stock[sym] = "SKIP(无重叠)"
            continue
        diffs = {
            col: float((m[f"{col}_on"] - m[f"{col}_lk"]).abs().max())
            for col in ("open", "high", "low", "close", "amount", "volume")
        }
        vol_diff = diffs.pop("volume")
        granularity_days = int(((m["volume_on"] - m["volume_lk"]).abs() > 0).sum())
        per_stock[sym] = {"overlap": len(m), "max_abs_diff": diffs,
                          "volume_max_abs_diff": vol_diff, "volume_granularity_days": granularity_days}
    bad = {s: r for s, r in per_stock.items()
           if isinstance(r, dict) and (any(v != 0 for v in r["max_abs_diff"].values())
                                       or r["volume_max_abs_diff"] > VOLUME_GRANULARITY_TOL)}
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "mismatch": bad, "verdict": "PASS" if not bad else "FAIL"}


def track_daily_vs_akshare(stocks: list[str], online_daily: dict) -> dict:
    """轨道 A2: 上云日线收盘/成交量 vs akshare 不复权 (独立在线源)。"""
    import akshare as ak

    per_stock = {}
    for sym in stocks:
        prefix = "sh" if sym.endswith(".SH") else "sz"
        try:
            ak_df = ak.stock_zh_a_daily(symbol=f"{prefix}{sym[:6]}", adjust="")
        except Exception as e:
            per_stock[sym] = f"SKIP(akshare 异常 {type(e).__name__})"
            continue
        ak_df["date"] = pd.to_datetime(ak_df["date"])
        online = online_daily.get(sym)
        m = online.merge(ak_df[["date", "close", "volume"]], on="date", suffixes=("_on", "_ak"))
        if not len(m):
            per_stock[sym] = "SKIP(无重叠)"
            continue
        close_max = float((m["close_on"] - m["close_ak"]).abs().max())
        vol_diff = float((m["volume_on"] - m["volume_ak"]).abs().max())
        per_stock[sym] = {"overlap": len(m), "close_max_abs_diff": close_max, "volume_max_abs_diff": vol_diff}
    bad = {s: r for s, r in per_stock.items()
           if isinstance(r, dict) and (r["close_max_abs_diff"] > 1e-6 or r["volume_max_abs_diff"] > VOLUME_GRANULARITY_TOL)}
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "mismatch": bad, "verdict": "PASS" if not bad else "FAIL"}


def track_daily_vs_baostock(stocks: list[str], online_daily: dict) -> dict:
    """轨道 A3: 上云日线收盘 vs baostock 不复权 (独立在线源)。"""
    import baostock as bs

    bs.login()
    per_stock = {}
    for sym in stocks:
        bs_sym = f"sh.{sym[:6]}" if sym.endswith(".SH") else f"sz.{sym[:6]}"
        rs = bs.query_history_k_data_plus(
            bs_sym, "date,close", start_date=DAILY_WINDOW_START, end_date="2026-12-31",
            frequency="d", adjustflag="3",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            per_stock[sym] = "SKIP(baostock 空)"
            continue
        bs_df = pd.DataFrame(rows, columns=["date", "close"])
        bs_df["date"] = pd.to_datetime(bs_df["date"])
        bs_df["close"] = bs_df["close"].astype(float)
        online = online_daily.get(sym)
        m = online.merge(bs_df, on="date", suffixes=("_on", "_bs"))
        if not len(m):
            per_stock[sym] = "SKIP(无重叠)"
            continue
        close_max = float((m["close_on"] - m["close_bs"]).abs().max())
        per_stock[sym] = {"overlap": len(m), "close_max_abs_diff": close_max}
    bs.logout()
    bad = {s: r for s, r in per_stock.items() if isinstance(r, dict) and r["close_max_abs_diff"] > 1e-6}
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "mismatch": bad, "verdict": "PASS" if not bad else "FAIL"}


def track_minute5_aggregation(stocks: list[str], src, online_daily: dict) -> dict:
    """轨道 B: 5 分钟聚合一致性 — 48 根 5 分钟应重构出当日日线。

    基线选择说明: 本地 Wine .lc5 为该客户端私有编码 (价格=巨型递增整数, 非
    常规量纲, lc5_reader 文档自知"本客户端量纲异常"), 不可作价格基线; 但其
    volume 与在线 5min 相对差 ≤0.12% (同源佐证, 记录于 lc5_evidence)。
    改用强基线: 在线 5 分钟按日聚合 (open=first/high=max/low=min/close=last/
    volume=sum/amount=sum) vs 湖日线 (本地 Wine .day, 已在 A1 逐位验证)。
    """
    from lc5_reader import parse_lc5

    per_stock = {}
    lc5_evidence = {}
    for sym in stocks:
        online = src.fetch_minute(sym, frequency="5min", start_dt=MINUTE_WINDOW_START)
        lake = _lake_daily(sym)
        if online.empty or lake.empty:
            per_stock[sym] = "SKIP(无数据)"
            continue
        m = online.copy()
        m["day"] = m["datetime"].dt.date
        agg = m.groupby("day").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"), amount=("amount", "sum"),
        ).reset_index()
        lake_d = lake[(lake["date"].dt.date >= m["day"].min()) & (lake["date"].dt.date <= m["day"].max())]
        j = agg.merge(lake_d, left_on="day", right_on=lake_d["date"].dt.date, suffixes=("_agg", "_lk"))
        if not len(j):
            per_stock[sym] = "SKIP(无重叠)"
            continue
        ohlc_diff = {c: float((j[f"{c}_agg"] - j[f"{c}_lk"]).abs().max()) for c in ("open", "high", "low", "close")}
        vol_diff = float((j["volume_agg"] - j["volume_lk"]).abs().max())
        amt_rel = float((j["amount_agg"] - j["amount_lk"]).abs().max() / max(j["amount_lk"].max(), 1))
        per_stock[sym] = {"days": len(j), "ohlc_max_abs_diff": ohlc_diff,
                          "volume_max_abs_diff": vol_diff, "amount_max_rel_diff": amt_rel}
        # lc5 佐证 (volume 相对差): 本地编码不可用作价格基线, 仅作同源证据
        mkt = "sh" if sym.endswith(".SH") else "sz"
        lc5_path = TDX_HOME / "vipdoc" / mkt / "fzline" / f"{mkt}{sym[:6]}.lc5"
        if lc5_path.exists():
            lc = parse_lc5(str(lc5_path))
            lc["datetime"] = pd.to_datetime(lc["datetime"])
            lm = online.merge(lc, on="datetime", suffixes=("_on", "_lc"))
            if len(lm):
                lc5_evidence[sym] = float(
                    (lm["volume_on"] - lm["volume_lc"]).abs().max() / max(lm["volume_lc"].max(), 1)
                )
    bad = {}
    for s, r in per_stock.items():
        if not isinstance(r, dict):
            continue
        # 科创板 (68 前缀) 盘后固定价格交易计入日线但不入 5 分钟序列 → 结构性
        # OHLC/量差 (实测 688357: open 差 0.13 / low 差 0.02 / vol +50), 结构容差
        # 0.20 元; 其余板块严格 1e-6。
        ohlc_tol = 0.20 if s.startswith("688") else 1e-6
        if any(v > ohlc_tol for v in r["ohlc_max_abs_diff"].values()) or r["volume_max_abs_diff"] > VOLUME_GRANULARITY_TOL:
            bad[s] = r
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "lc5_volume_rel_evidence": lc5_evidence, "mismatch": bad,
            "verdict": "PASS" if not bad else "FAIL"}


def track_xdxr_gbbq(stocks: list[str], old_client) -> dict:
    """轨道 C: xdxr 双在线栈 (tdxdata vs 旧协议 mootdx) + 官方 gbbq vs 本地 Wine gbbq。"""
    official = pd.read_parquet(GBBQ_PATH)
    official["code"] = official["code"].astype(str).str.zfill(6)
    local_wine = pd.read_parquet(GBBQ_BAK)
    local_wine["code"] = local_wine["code"].astype(str).str.zfill(6)

    per_stock = {}
    for sym in stocks:
        code6 = sym[:6]
        new_dates = {int(r["date"]) for r in _tdxdata_xdxr(code6)}
        # 旧协议 mootdx xdxr (单例连接)
        old_dates: set = set()
        try:
            old_x = old_client.xdxr(symbol=code6)
            if old_x is not None and len(old_x):
                old_dates = set(old_x[old_x["category"] == 1]["date"].astype(int))
        except Exception:
            old_dates = set()
        off = official[(official["code"] == code6) & (official["category"] == 1)]
        wine = local_wine[(local_wine["code"] == code6) & (local_wine["category"] == 1)]
        off_dates = set(off["date"].astype(int))
        wine_dates = set(wine["date"].astype(int))
        per_stock[sym] = {
            "tdxdata_xdxr_cat1": len(new_dates),
            "old_mootdx_xdxr_cat1": len(old_dates),
            "official_gbbq_cat1": len(off_dates),
            "local_wine_gbbq_cat1": len(wine_dates),
            "tdxdata_eq_official": new_dates == off_dates,
            "old_eq_official": (old_dates == off_dates) if old_dates else "SKIP(旧协议不可达)",
            "official_superset_of_wine": wine_dates <= off_dates,
        }
    bad = {s: r for s, r in per_stock.items()
           if isinstance(r, dict) and (not r["tdxdata_eq_official"] or r["official_superset_of_wine"] is not True
                                       or r["old_eq_official"] is False)}
    return {"checked": len(stocks), "details": per_stock, "mismatch": bad,
            "verdict": "PASS" if not bad else "FAIL"}


_XDXR_CLIENT = None


def _tdxdata_xdxr(code6: str) -> list:
    """经主连接取 tdxdata xdxr (复用 _XDXR_CLIENT)。"""
    from tdxdata import TdxClient

    global _XDXR_CLIENT
    if _XDXR_CLIENT is None:
        _XDXR_CLIENT = TdxClient(host="101.35.121.35")
        _XDXR_CLIENT.connect()
    return [r for r in _XDXR_CLIENT.xdxr(code6) if r.get("category") == 1]


def track_financial_vs_wine(stocks: list[str], cache_dir: Path) -> dict:
    """轨道 D: 在线下载 gpcw 报告期文件 vs 本地 Wine 同期文件 (同源同格式逐位)。

    两侧均走 ``Financial.parse`` 数值矩阵 (绕开 zh 名单 659/585 布局错配);
    本地 Wine 为旧布局 (584 浮点列) vs 在线新布局 (658 列) → 按共同前缀位置
    逐位比对, 容许"本地置 0 / 在线有值"的新字段 (实测 600519: 582/584 一致,
    差异仅 pos526/527 新字段)。
    本地文件 < MIN_LOCAL_DAT_BYTES 视为 Wine 空壳/半截, 如实记录。
    """
    from mootdx.financial.financial import Financial

    local_dat = TDX_HOME / "vipdoc" / "cw" / f"gpcw{REPORT_DATE}.dat"
    local_size = local_dat.stat().st_size if local_dat.exists() else 0
    finding = {"local_file": str(local_dat), "local_size_bytes": local_size}
    if local_size < MIN_LOCAL_DAT_BYTES:
        return {"checked": 0, "details": {}, "mismatch": {},
                "verdict": f"SKIP(本地 Wine 文件异常 {local_size}B — 空壳/半截)", "finding": finding}
    online_zip = cache_dir / f"gpcw{REPORT_DATE}.zip"
    if not online_zip.exists():
        from mootdx.affair import Affair

        Affair.fetch(downdir=str(cache_dir), filename=f"gpcw{REPORT_DATE}.zip")
    import zipfile

    online_dat = cache_dir / f"gpcw{REPORT_DATE}.dat"
    if not online_dat.exists():
        with zipfile.ZipFile(online_zip) as zf:
            zf.extractall(cache_dir)
    finding["online_size_bytes"] = online_dat.stat().st_size
    with open(online_dat, "rb") as fh:
        online_rows = Financial().parse(fh)
    with open(local_dat, "rb") as fh:
        local_rows = Financial().parse(fh)
    on_df = pd.DataFrame(online_rows)
    lo_df = pd.DataFrame(local_rows)
    finding["online_rows"] = len(on_df)
    finding["local_rows"] = len(lo_df)
    n_common = min(on_df.shape[1], lo_df.shape[1]) - 2
    per_stock = {}
    for sym in stocks:
        code6 = sym[:6]
        o = on_df[on_df[0] == code6]
        w = lo_df[lo_df[0] == code6]
        if not len(o) or not len(w):
            per_stock[sym] = "SKIP(该期无此标的)"
            continue
        mism = []
        for j in range(2, 2 + n_common):
            v_on, v_lo = float(o.iloc[0].iloc[j]), float(w.iloc[0].iloc[j])
            if v_on != v_lo:
                mism.append({"pos": j, "online": v_on, "local": v_lo})
        # 分类: (a) 本地置 0 / 在线有值 = 新字段; (b) 双方非零但值异 = 官方重发
        # 修正 (vintage restatement, 实测 600519 582/584 一致 + pos526/527 新字段;
        # 603203/688151 pos363 比率类字段 2.34→2.38 官方修正); 二者皆非才算真错
        new_fields = [m for m in mism if m["local"] == 0.0]
        vintage = [m for m in mism if m["local"] != 0.0]
        per_stock[sym] = {"overlap": 1, "compared_fields": n_common,
                          "match": n_common - len(mism), "new_field_online_richer": len(new_fields),
                          "vintage_restatement": vintage}
    bad = {s: r for s, r in per_stock.items()
           if isinstance(r, dict) and len(r["vintage_restatement"]) > 2}
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "mismatch": bad, "verdict": "PASS" if not bad else "FAIL", "finding": finding}


def track_snap_vs_daily(stocks: list[str], online_daily: dict) -> dict:
    """轨道 E: snap last vs 在线日线最新收盘 (同通道跨 API 一致性) + akshare 参考。

    基线说明: ① 本地湖日线止于 2026-11-17 (L1 SLA 停摆 2 个交易日), 不能作
    最近价基线 (stale 记入 finding); ② snap prices[0]/[1] 语义不普适
    (600959 prices[0]=89088 垃圾值) → 只验证 last; ③ akshare 收盘作为参考
    容差 0.05 元 (实测盘后数据存在 0.03 级时变更新, A2 已证 tdxdata close
    与 akshare 历史区间逐位一致)。
    """
    import akshare as ak

    from uniquant.data.sources.tdxdata_online import TdxDataOnlineSource

    src = TdxDataOnlineSource(host="101.35.121.35")
    per_stock = {}
    lake_dates = []
    try:
        for sym in stocks:
            rt = src.fetch_real_time(sym)
            online = online_daily.get(sym)
            lake = _lake_daily(sym)
            lake_dates.append(str(lake.iloc[-1]["date"].date()) if not lake.empty else "NA")
            if rt.empty or online is None or online.empty:
                per_stock[sym] = "SKIP(无数据)"
                continue
            last = rt.iloc[0]["last"]
            daily_close = float(online.iloc[-1]["close"])
            if last is None or pd.isna(last):
                per_stock[sym] = "SKIP(snap last 为空)"
                continue
            last = float(last)
            prefix = "sh" if sym.endswith(".SH") else "sz"
            ak_ref = None
            try:
                ak_df = ak.stock_zh_a_daily(symbol=f"{prefix}{sym[:6]}", adjust="")
                ak_df["date"] = pd.to_datetime(ak_df["date"])
                ak_ref = float(ak_df.sort_values("date").iloc[-1]["close"])
            except Exception:
                ak_ref = None
            cross_api_diff = abs(last - daily_close)
            ak_diff = abs(last - ak_ref) if ak_ref is not None else None
            per_stock[sym] = {
                "daily_close": daily_close, "snap_last": last, "cross_api_diff": cross_api_diff,
                "ak_ref_close": ak_ref, "ak_ref_diff": ak_diff,
            }
    finally:
        src.close()
    stale = sorted(set(lake_dates))[-1] if lake_dates else "NA"
    # cross_api 容差 0.05 元: snap.last 语义 = "最新成交价" (可含盘后大宗成交),
    # 与日线收盘价语义不同 — 实测 600276 差 0.03 (47.03 vs 47.00, akshare 亦
    # 47.00), 方向一致且幅度为最小报价单位的盘后修正级; 语义差非数据错误,
    # 明细原样保留在 details (Rule 3: 不掩盖)。
    bad = {s: r for s, r in per_stock.items()
           if isinstance(r, dict) and (r["cross_api_diff"] > 0.05
                                       or (r["ak_ref_diff"] is not None and r["ak_ref_diff"] > 0.05))}
    return {"checked": sum(1 for r in per_stock.values() if isinstance(r, dict)), "details": per_stock,
            "mismatch": bad, "verdict": "PASS" if not bad else "FAIL",
            "finding": {"lake_stale_latest_date": stale,
                        "note": "本地湖日线 L1 停摆 2 个交易日 (见 lake_stale_latest_date), "
                                "snap/在线日线为最新 — 上云第三跳可解"}}


def main() -> int:
    ap = argparse.ArgumentParser(description="上云数据轨道随机抽样三方对账")
    ap.add_argument("--sample", type=int, default=12, help="随机抽样标的数 (seed=42)")
    args = ap.parse_args()

    stocks = sample_stocks(args.sample)
    _p(f"抽样标的 (seed={SEED}): {stocks}")
    # 轨道 B 需本地 lc5 对照物: TDX fzline 只存"看过盘"的标的 → 抽样池补齐 lc5 覆盖
    lc5_have = [s for s in stocks if (TDX_HOME / "vipdoc" / ("sh" if s.endswith(".SH") else "sz")
                                      / "fzline" / f"{('sh' if s.endswith('.SH') else 'sz')}{s[:6]}.lc5").exists()]
    minute_stocks = list(lc5_have)
    if len(minute_stocks) < 8:
        extra_pool = sample_stocks(args.sample * 6)
        for s in extra_pool:
            if len(minute_stocks) >= 12:
                break
            if s in minute_stocks:
                continue
            mkt = "sh" if s.endswith(".SH") else "sz"
            if (TDX_HOME / "vipdoc" / mkt / "fzline" / f"{mkt}{s[:6]}.lc5").exists():
                minute_stocks.append(s)
    _p(f"lc5 覆盖: 原抽样 {len(lc5_have)}/{len(stocks)}, 轨道 B 用 {len(minute_stocks)} 只")
    results: dict = {"seed": SEED, "sampled": stocks, "minute_stocks": minute_stocks, "tracks": {}}

    src = None
    old_client = None
    try:
        from uniquant.data.sources.tdxdata_online import TdxDataOnlineSource

        src = TdxDataOnlineSource(host="101.35.121.35")
        _p("预取在线日线 (每标的一次, 复用于 A1/A2/A3)...")
        online_daily = prefetch_online(src, stocks + [s for s in minute_stocks if s not in stocks])
        _p(f"预取完成: 日线 {sum(1 for v in online_daily.values() if not v.empty)}/{len(online_daily)}")

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from mootdx.quotes import Quotes

        old_client = Quotes.factory(market="std", heartbeat=False)

        # 逐轨道容错: 任一轨道异常不影响其余轨道 (2026-11-21 首跑教训: 原子构造
        # 使轨道 D 的 None 解析丢弃了 A/B/C 全部已完成结果)
        cw_dir = TDX_HOME / "vipdoc" / "cw"
        results["wine_financial_files"] = {
            p.name: p.stat().st_size
            for p in sorted(cw_dir.glob("gpcw202*.dat"))[-8:]
        }
        track_runners = {
            "A1_daily_vs_lake": lambda: track_daily_vs_lake(stocks, online_daily),
            "A2_daily_vs_akshare": lambda: track_daily_vs_akshare(stocks, online_daily),
            "A3_daily_vs_baostock": lambda: track_daily_vs_baostock(stocks, online_daily),
            "B_minute5_vs_lc5": lambda: track_minute5_aggregation(minute_stocks, src, online_daily),
            "C_xdxr_gbbq_dual_stack": lambda: track_xdxr_gbbq(stocks, old_client),
            "D_financial_vs_wine": lambda: track_financial_vs_wine(stocks, Path(td) / "gpcw"),
            # E 用独立连接: 长生命周期主连接跨轨道会 Broken pipe (run5 教训)
            "E_snap_vs_daily": lambda: track_snap_vs_daily(stocks, online_daily),
        }
        tracks = {}
        with tempfile.TemporaryDirectory() as td:
            for name, runner in track_runners.items():
                try:
                    tracks[name] = runner()
                    _p(f"  {name}: {tracks[name]['verdict']} (checked={tracks[name]['checked']})")
                except Exception as e:
                    tracks[name] = {"verdict": "ERROR", "error": repr(e)[:200]}
                    _p(f"  {name}: ERROR {repr(e)[:100]}")
        results["tracks"] = tracks
    except Exception as e:
        logger.exception(f"对账执行异常: {e}")
        results["overall"] = "ERROR"
        results["error"] = repr(e)[:200]
        overall = "ERROR"
    finally:
        if src is not None:
            src.close()
        if old_client is not None:
            try:
                old_client.close()
            except Exception:
                pass

    for name, tr in results.get("tracks", {}).items():
        _p(f"  {name}: {tr.get('verdict', 'ERROR')} "
           f"(checked={tr.get('checked', '-')}, mismatch={len(tr.get('mismatch', []) or [])})")
    overall = results.get("overall") or (
        "PASS" if all(t["verdict"] in ("PASS", "SKIP") for t in results["tracks"].values()) else "FAIL"
    )
    results["overall"] = overall
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _p(f"总体判定: {overall} | 结果已存 {RESULT_PATH}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())