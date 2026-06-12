"""
Stage 1: 全市场股票池清洗与安全扩容 (Universe Sanitization)
==========================================================

目标: 将回测标的池从 50 只扩容至全市场, 执行严苛前置过滤。

过滤规则:
  1. ❌ ST / *ST 股票 (名称过滤)
  2. ❌ 次新股: 上市或数据记录 < 120 个交易日
  3. ❌ 流动性枯竭股: 近 20 日日均成交额 < 2000 万

[Halt & Wait]
"""

import os, sys, warnings, time
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_LAKE_DIR = Path("data/lake/quotes/daily")
STOCK_LIST_PATH = Path("src/uniquant/data/stock_list.csv")
ALL_CODES_PATH = Path("src/uniquant/data/all_stock_codes.csv")
LIQUIDITY_DAYS = 20
MIN_AVG_AMOUNT = 20_000_000    # 日均成交额 >= 2000万
MIN_TRADING_DAYS = 120         # 最少 120 个交易日


def load_stock_master() -> pd.DataFrame:
    """加载股票主表, 与 data lake parquet 文件交叉验证。"""
    # 主表
    master = pd.read_csv(STOCK_LIST_PATH)
    master["symbol"] = master["code"].astype(str) + "." + master["market"]

    # IPO 日期
    ipo = pd.read_csv(ALL_CODES_PATH)
    ipo = ipo[ipo["type"] == 1].copy()
    ipo["code_raw"] = ipo["code"].str.replace(r"^[a-z]+\.", "", regex=True)
    ipo_lookup = ipo.set_index("code_raw")["ipoDate"].to_dict()
    master["ipo_date"] = master["code"].astype(str).map(ipo_lookup)

    # 标记 ST
    master["is_st"] = master["name"].str.contains("ST|退", na=False)

    # 是否有 parquet 文件
    parquet_files = set(f.name for f in DATA_LAKE_DIR.glob("*.parquet"))
    master["has_parquet"] = master["symbol"].apply(lambda s: f"{s}.parquet" in parquet_files)

    print(f"  stock_list.csv 股票总数: {len(master)}")
    print(f"  有 parquet 数据: {master['has_parquet'].sum()}")
    print(f"  标记为 ST/*ST/退: {master['is_st'].sum()}")
    return master


def scan_data_lake(master: pd.DataFrame) -> pd.DataFrame:
    """
    扫描 data lake 中的每个股票的:
      - 首末交易日
      - 交易日数量
      - 近 LIQUIDITY_DAYS 天的日均成交额
    """
    symbols = master[master["has_parquet"]]["symbol"].tolist()
    print(f"\n  扫描 {len(symbols)} 个股票的数据湖...")

    records = []
    t0 = time.time()
    batch_size = 200

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        for sym in batch:
            fp = DATA_LAKE_DIR / f"{sym}.parquet"
            try:
                meta = pd.read_parquet(
                    fp, columns=["date", "amount"]
                )
                if meta.empty:
                    records.append({
                        "symbol": sym, "first_date": None, "last_date": None,
                        "trading_days": 0, "avg_amount_20d": 0.0,
                    })
                    continue

                meta["date"] = pd.to_datetime(meta["date"], errors="coerce")
                meta = meta.dropna(subset=["date"]).sort_values("date")
                if meta.empty:
                    records.append({
                        "symbol": sym, "first_date": None, "last_date": None,
                        "trading_days": 0, "avg_amount_20d": 0.0,
                    })
                    continue

                first_dt = meta["date"].iloc[0]
                last_dt = meta["date"].iloc[-1]
                trading_days = len(meta)

                # 最近 20 天成交额
                recent = meta[meta["date"] >= last_dt - pd.Timedelta(days=45)]
                recent_20 = recent.tail(LIQUIDITY_DAYS)
                if len(recent_20) > 5:
                    avg_amt = recent_20["amount"].mean()
                else:
                    avg_amt = recent["amount"].mean() if len(recent) > 0 else 0.0

                records.append({
                    "symbol": sym,
                    "first_date": first_dt,
                    "last_date": last_dt,
                    "trading_days": trading_days,
                    "avg_amount_20d": avg_amt,
                })
            except Exception as e:
                records.append({
                    "symbol": sym, "first_date": None, "last_date": None,
                    "trading_days": 0, "avg_amount_20d": 0.0,
                })

        elapsed = time.time() - t0
        pct = min(100, (i + batch_size) / len(symbols) * 100)
        print(f"    进度 {pct:.0f}% ({i+batch_size}/{len(symbols)}), 耗时 {elapsed:.0f}s",
              end="\r")

    print(f"\n  扫描完成, 耗时 {time.time()-t0:.0f}s")
    return pd.DataFrame(records)


def apply_filters(master: pd.DataFrame, lake_stats: pd.DataFrame) -> pd.DataFrame:
    """执行三层硬性过滤。"""
    df = master.merge(lake_stats, on="symbol", how="left")

    initial = len(df)

    # Filter 1: ST / *ST
    f1_st = df[~df["is_st"]].copy()
    print(f"\n  [Filter 1] 剔除 ST/*ST: {initial - len(f1_st)} 只")

    # Filter 2: 次新股 (< 120 交易日)
    f2_age = f1_st[f1_st["trading_days"] >= MIN_TRADING_DAYS].copy()
    print(f"  [Filter 2] 剔除次新股 (< {MIN_TRADING_DAYS}d): {len(f1_st) - len(f2_age)} 只")

    # Filter 3: 流动性枯竭 (日均成交额 < 2000万)
    f3_liquid = f2_age[f2_age["avg_amount_20d"] >= MIN_AVG_AMOUNT].copy()
    print(f"  [Filter 3] 剔除流动性枯竭 (< {MIN_AVG_AMOUNT//1e6:.0f}M): {len(f2_age) - len(f3_liquid)} 只")

    print(f"\n  ✅ 最终合格股票: {len(f3_liquid)} 只 (从初始 {initial} 只)")
    return f3_liquid


def categorize_market(df: pd.DataFrame) -> pd.DataFrame:
    """按板块统计合格股票分布。"""
    sh_mapping = {"上海主板": "SH主板", "科创板": "STAR"}
    sz_mapping = {"深圳主板": "SZ主板", "创业板": "GEM", "中小板": "SME"}
    market_map = {**{k: v for k, v in [
        ("上海主板", "SH主板"), ("科创板", "STAR"),
        ("深圳主板", "SZ主板"), ("创业板", "GEM"), ("中小板", "SME"),
    ]}}
    # The csv has 'sector' column, not 'market'
    if "sector" in df.columns:
        counts = df["sector"].value_counts()
    else:
        counts = df["market"].value_counts() if "market" in df.columns else pd.Series()
    return counts


def main():
    print("=" * 70)
    print("  Stage 1: 全市场股票池清洗与安全扩容")
    print("  Universe Sanitization — 5000+ → Qualified Pool")
    print("=" * 70)

    if not DATA_LAKE_DIR.exists():
        print(f"\n  ❌ Data lake not found at {DATA_LAKE_DIR}")
        print("  Please ensure data has been synced.")
        return

    # ---- 1. 加载主表 ----
    print("\n[1/4] 加载股票主表...")
    master = load_stock_master()

    # ---- 2. 扫描数据湖 ----
    print("\n[2/4] 扫描 Data Lake 数据质量...")
    lake_stats = scan_data_lake(master)
    print(f"  有有效数据的: {lake_stats['trading_days'].gt(0).sum()}")

    # ---- 3. 执行过滤 ----
    print("\n[3/4] 执行三层硬性过滤...")
    qualified = apply_filters(master, lake_stats)

    # ---- 4. 分布统计 ----
    print("\n[4/4] 板块分布统计:")
    if "sector" in qualified.columns:
        sect_counts = qualified["sector"].value_counts()
        print(f"  {'板块':<16} {'数量':>6} {'占比':>8}")
        print(f"  {'-'*30}")
        for sect, cnt in sect_counts.items():
            print(f"  {sect:<16} {cnt:>6} {cnt/len(qualified):>7.1%}")

    print(f"\n  LPPL 数据服务涉及指数:")
    print(f"    000300.SH (沪深300), 000905.SH (中证500), 000852.SH (中证1000)")

    # ---- 保存结果 ----
    out_path = Path("data/qualified_universe.csv")
    qualified.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ 合格股票池已保存: {out_path}")

    # ---- 报告 ----
    report_path = Path("docs/reshaping_logs/04_universe_expansion.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 04 — 全市场股票池清洗与安全扩容\n\n")
        f.write(f"> **生成**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **过滤日期**: {pd.Timestamp.now().strftime('%Y-%m-%d')}\n\n")

        f.write("## 过滤流水线\n\n")
        f.write("| 阶段 | 操作 | 剩余数量 | 剔除数量 |\n")
        f.write("|------|------|---------|---------|\n")
        initial = len(master)
        f1 = sum(master["is_st"])
        f.write(f"| 初始 | 全市场股票 | {initial} | - |\n")
        f1_rem = initial - len(master[~master["is_st"]])
        f.write(f"| 1 | 剔除 ST/*ST/退市 | {initial - f1_rem} | {f1_rem} |\n")
        f2_age_rem = len(master[~master["is_st"] & (master["has_parquet"])]) - len(qualified)
        # More precise filtering steps:
        non_st = master[~master["is_st"] & master["has_parquet"]]
        f2_rem = len(non_st[non_st["trading_days"] < MIN_TRADING_DAYS]) if "trading_days" in non_st else 0
        f.write(f"| 2 | 剔除次新股 (<{MIN_TRADING_DAYS}d) | ? | ? |\n")
        f3_rem = len(non_st) - f2_rem - len(qualified) if "trading_days" in non_st else 0
        f.write(f"| 3 | 剔除流动性枯竭 (<{MIN_AVG_AMOUNT/1e6:.0f}M) | {len(qualified)} | ? |\n\n")

        f.write("## 板块分布\n\n")
        f.write("| 板块 | 数量 | 占比 |\n")
        f.write("|------|------|------|\n")
        if "sector" in qualified.columns:
            for sect, cnt in sect_counts.items():
                f.write(f"| {sect} | {cnt} | {cnt/len(qualified):.1%} |\n")

        f.write("\n## 统计摘要\n\n")
        f.write(f"- 初始全市场股票: {initial}\n")
        f.write(f"- 合格股票: {len(qualified)}\n")
        f.write(f"- 通过率: {len(qualified)/initial:.1%}\n")
        f.write(f"- 数据源: local parquet lake ({DATA_LAKE_DIR})\n")
        f.write(f"- 数据截止: {lake_stats['last_date'].max()}\n")

        f.write("\n## 过滤规则\n\n")
        f.write("1. **ST / *ST / 退市**: 股票名称含 `ST`、`*ST`、`退` 字样的\n")
        f.write(f"2. **次新股**: 数据记录天数 < {MIN_TRADING_DAYS} 个交易日\n")
        f.write(f"3. **流动性枯竭**: 近 {LIQUIDITY_DAYS} 日均成交额 < {MIN_AVG_AMOUNT/1e8:.1f}亿\n")

        f.write("\n---\n")

    print(f"\n  📋 报告: {report_path}")
    print(f"\n{'='*70}")
    print("  Stage 1 完成!")
    print(f"{'='*70}")
    print("\n  ⏸ [Halt & Wait] — 请确认合格股票池后继续 Stage 2")


if __name__ == "__main__":
    main()
