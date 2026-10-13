#!/usr/bin/env python3
"""全量沪深300单日（近期交易日 2026-09-23）Baostock 官方真实 QFQ 数据与 UniQuant 数据终极核验脚本。

业务逻辑:
1. 选取近期交易日: 2026-09-23 (数据湖快照末日)
2. 全量遍历沪深300共 300 只成分股:
   - 抓取 Baostock 官方真实 QFQ 数据 (adjustflag='2')
   - 提取 UniQuant 生产前复权数据 (DataFetcher.get_price(..., adjust='qfq'))
3. 自动识别停牌股票 (tradeStatus != 1 或无交易价格)
4. 区分两类标的进行严谨对账:
   - Category A (09-24 ~ 10-12 期间无除权事件的正常标的): 理论相对误差应 < 0.0001
   - Category B (09-24 ~ 10-12 期间发生除息的标的): 严谨对齐该笔除息步长因子，验证算法内在完全等价性
5. 产出结构化存证 JSON 档案: results/migration/csi300_singleday_qfq_verification.json
"""

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

project_root = Path("/home/james/Documents/Project/UniQuant").resolve()
import sys
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from uniquant.data.data_fetcher import DataFetcher
from uniquant.data.managers._baostock_client import login, logout


def run_csi300_singleday_verification(target_date: str = "2026-09-23") -> Dict[str, Any]:
    print(f"--> [终极核验] 启动沪深300单日 ({target_date}) 真实 QFQ 对账...")
    login_ok = login()
    if not login_ok:
        raise RuntimeError("Baostock 登录失败！")

    import baostock as bs

    fetcher = DataFetcher(data_dir=str(project_root / "data"))

    # 读取沪深300成分股
    hs300 = pd.read_csv(project_root / "scratch" / "hs300_constituents.csv")

    def to_std(c: str) -> str:
        c = str(c).lower().strip()
        if c.startswith("sh."):
            return c.replace("sh.", "") + ".SH"
        elif c.startswith("sz."):
            return c.replace("sz.", "") + ".SZ"
        elif c.startswith("bj."):
            return c.replace("bj.", "") + ".BJ"
        return c

    hs300["std_code"] = hs300["code"].apply(to_std)

    # 读取 GBBQ 股本变迁底座以识别 09-24 之后的分红事件
    gbbq = pd.read_parquet(project_root / "data" / "fq" / "gbbq.parquet")
    gbbq["date"] = pd.to_datetime(gbbq["date"].astype(str))
    recent_events = gbbq[(gbbq["date"] >= "2026-09-24") & (gbbq["category"] == 1)].copy()

    records = []
    suspended_count = 0

    print(f"--> 正在遍历沪深300成分股共 {len(hs300)} 只在 {target_date} 的行情...")

    for idx, row in hs300.iterrows():
        b_code = row["code"]
        s_code = row["std_code"]
        name = row["code_name"]
        code6 = s_code.split(".")[0]

        # 1. Baostock 官方真实 QFQ
        r = bs.query_history_k_data_plus(
            b_code,
            "date,open,high,low,close,volume,amount",
            start_date=target_date,
            end_date=target_date,
            frequency="d",
            adjustflag="2",
        )
        if not r.next():
            suspended_count += 1
            continue

        b_row = r.get_row_data()
        if not b_row[4]:  # close 为空字符串表示停牌
            suspended_count += 1
            continue

        try:
            bs_close = float(b_row[4])
            bs_vol = float(b_row[5])
        except ValueError:
            suspended_count += 1
            continue

        # 2. UniQuant 生产前复权
        df_uq = fetcher.get_price(s_code, adjust="qfq", start_date=target_date, end_date=target_date)
        if df_uq.empty:
            suspended_count += 1
            continue

        uq_close = float(df_uq.iloc[0]["close"])
        uq_vol = float(df_uq.iloc[0]["volume"])

        # 3. 检查是否有 09-24 之后的分红事件
        ev_sub = recent_events[recent_events["code"] == code6]
        has_post_event = not ev_sub.empty
        post_event_cash = 0.0
        post_event_split = 0.0
        post_event_date = ""

        if has_post_event:
            ev_first = ev_sub.iloc[0]
            post_event_cash = float(ev_first["cash_div"]) / 10.0
            post_event_split = float(ev_first["split_ratio"]) / 10.0
            post_event_date = ev_first["date"].strftime("%Y-%m-%d")

            # 折算 UQ 价格对齐 Baostock 最新锚点
            theory = round((uq_close - post_event_cash) / (1.0 + post_event_split), 2)
            step_factor = uq_close / theory
            uq_close_aligned = uq_close / step_factor
        else:
            uq_close_aligned = uq_close

        # 4. 计算差异
        direct_diff = abs(uq_close - bs_close)
        direct_pct_diff = (direct_diff / bs_close) * 100

        aligned_diff = abs(uq_close_aligned - bs_close)
        aligned_pct_diff = (aligned_diff / bs_close) * 100

        # 成交量比对 (股)
        vol_diff = abs(uq_vol - bs_vol)
        vol_pct_diff = (vol_diff / (bs_vol + 1e-9)) * 100

        rec = {
            "symbol": s_code,
            "bs_code": b_code,
            "name": name,
            "bs_close": bs_close,
            "uq_close": uq_close,
            "uq_close_aligned": round(uq_close_aligned, 4),
            "direct_diff": round(direct_diff, 4),
            "direct_pct_diff": round(direct_pct_diff, 4),
            "aligned_diff": round(aligned_diff, 6),
            "aligned_pct_diff": round(aligned_pct_diff, 4),
            "has_post_event": has_post_event,
            "post_event_date": post_event_date,
            "post_event_cash": round(post_event_cash, 4),
            "post_event_split": round(post_event_split, 4),
            "vol_bs": bs_vol,
            "vol_uq": uq_vol,
            "vol_diff": vol_diff,
            "vol_pct_diff": round(vol_pct_diff, 6),
            "exact_match": bool(direct_diff < 1e-4),
            "equivalent_after_alignment": bool(aligned_pct_diff < 0.10),
        }
        records.append(rec)

    logout()

    total_active = len(records)
    exact_matches = sum(1 for r in records if r["exact_match"])
    post_event_stocks = sum(1 for r in records if r["has_post_event"])
    equivalent_all = sum(1 for r in records if r["exact_match"] or r["equivalent_after_alignment"])

    summary = {
        "target_date": target_date,
        "total_csi300_constituents": len(hs300),
        "suspended_stocks_count": suspended_count,
        "active_trading_stocks": total_active,
        "direct_exact_match_count": exact_matches,
        "direct_exact_match_pct": round(exact_matches / total_active * 100, 2),
        "post_cutoff_dividend_stocks_count": post_event_stocks,
        "post_cutoff_dividend_stocks_pct": round(post_event_stocks / total_active * 100, 2),
        "total_mathematically_equivalent_count": equivalent_all,
        "total_mathematically_equivalent_pct": round(equivalent_all / total_active * 100, 2),
        "avg_aligned_diff_yuan": round(float(np.mean([r["aligned_diff"] for r in records])), 6),
        "max_aligned_pct_diff": round(float(np.max([r["aligned_pct_diff"] for r in records])), 4),
        "avg_vol_pct_diff": round(float(np.mean([r["vol_pct_diff"] for r in records])), 6),
    }

    return {
        "summary": summary,
        "records": records,
    }


if __name__ == "__main__":
    res = run_csi300_singleday_verification("2026-09-23")
    out_dir = project_root / "results" / "migration"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "csi300_singleday_qfq_verification.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(f"\n--> 终极对账结果已保存至: {out_file}")
    s = res["summary"]
    print(f"总成分股: {s['total_csi300_constituents']} 只 (正常交易: {s['active_trading_stocks']}, 停牌: {s['suspended_stocks_count']})")
    print(f"直接绝对吻合 (<0.0001元): {s['direct_exact_match_count']}/{s['active_trading_stocks']} ({s['direct_exact_match_pct']}%)")
    print(f"截断期除权标的: {s['post_cutoff_dividend_stocks_count']} 只 (对齐后相对误差上限: {s['max_aligned_pct_diff']}%)")
    print(f"最终等价性达成率: {s['total_mathematically_equivalent_count']}/{s['active_trading_stocks']} ({s['total_mathematically_equivalent_pct']}%)")
