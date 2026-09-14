"""Phase 0 PoC 入口：用真实数据跑通管线。

- 数据源：NeoData（实时，已验证连通）
- 篮子：15 只跨风格流动性龙头（白酒/金融/制造/新能源/医药/消费）
- 输出：factor_frame.csv（真实因子值）、poc_report.csv（IC 评估）、控制台摘要

说明：PoC 用"最新已公告"财务近似 PIT；跨截面样本小（15×2月），
IC 仅用于验证引擎与数据链路，非 WS1 统计结论（全样本需批量接口）。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quant_pipeline import (  # noqa: E402
    NeoDataClient, build_factor_frame, evaluate_factors, rank_ic,
)

QUERY_PY = r"C:\Users\VMW\.workbuddy\skills\neodata-financial-search\scripts\query.py"
PY = r"C:\Users\VMW\.workbuddy\binaries\python\versions\3.13.12\python.exe"
OUT = os.path.dirname(os.path.abspath(__file__))

# 15 只跨风格流动性龙头
BASKET = [
    "600519.SH", "000858.SZ", "601318.SH", "600036.SH", "000333.SZ",
    "002594.SZ", "600900.SH", "601012.SH", "000001.SZ", "600276.SH",
    "603259.SH", "300750.SZ", "600030.SH", "000651.SZ", "601888.SH",
]

MONTHS = [202605, 202606]  # 用这两月作为两个截面，前瞻收益=次月收盘/当月-1


def main():
    client = NeoDataClient(QUERY_PY, PY)

    print("=== [1/3] 拉取真实因子（NeoData）===")
    ff = build_factor_frame(client, BASKET)
    fac_df = ff.to_frame()
    fac_df.index.name = "code"
    fac_df.to_csv(os.path.join(OUT, "factor_frame.csv"), encoding="utf-8-sig")
    print(fac_df.round(4).to_string())

    print("\n=== [2/3] 拉取月线，构造前瞻收益 ===")
    close_all = {}
    for c in BASKET:
        print(f"  月线 {c} ...", flush=True)
        s = client.monthly_close(c, "2025年1月", "2026年8月")
        close_all[c] = s
    close_df = pd_concat(close_all)

    # 用 每股分红(分红派息) + 最新收盘价 补全股息率(%)
    last_ym = close_df.index.max()
    for c in BASKET:
        if pd.isna(ff.dy.get(c, np.nan)):
            div = client.dividend(c)
            per10 = div.get("per10_latest", np.nan)
            price = close_df.at[last_ym, c] if (last_ym in close_df.index and c in close_df.columns) else np.nan
            if not pd.isna(per10) and not pd.isna(price) and price > 0:
                ff.dy[c] = (per10 / 10.0) / price * 100.0

    # 每个截面月：因子(最新) vs 次月前瞻收益
    ic_records = []
    for m in MONTHS:
        if m + 1 not in close_df.index:
            continue
        fwd = (close_df.loc[m + 1] / close_df.loc[m] - 1).rename("fwd_ret")
        eval_df = evaluate_factors(ff, fwd)
        eval_df.insert(0, "cross_section", m)
        ic_records.append(eval_df)
        print(f"\n--- 截面 {m} -> {m+1} 前瞻收益 rank IC ---")
        print(eval_df.to_string(index=False))

    if ic_records:
        full = pd.concat(ic_records, ignore_index=True)
        full.to_csv(os.path.join(OUT, "poc_report.csv"), encoding="utf-8-sig", index=False)
        # 平均 IC（跨截面）
        mean_ic = full.groupby("factor")["rankIC"].mean()
        print("\n=== [3/3] 跨截面平均 rank IC（PoC，小样本）===")
        print(mean_ic.round(4).to_string())
        print("\n⚠️ 样本仅 15 只×2 月，IC 仅验证引擎/数据链路；WS1 全样本结论需批量接口扩容。")


def pd_concat(d: dict):
    import pandas as pd
    return pd.DataFrame(d)


if __name__ == "__main__":
    main()
