"""
极小化回测验证: 随机选股 + 等权买入, 验证回测引擎无误
"""
import numpy as np
import pandas as pd
from pathlib import Path

LAKE_DIR = Path("data/lake/quotes/daily")
QUALIFIED = "data/qualified_universe.csv"

symbols = pd.read_csv(QUALIFIED)["symbol"].tolist()
print(f"Universe: {len(symbols)} stocks")

# Load a subset for speed
np.random.seed(42)
test_syms = np.random.choice(symbols, 500, replace=False).tolist()

stock_data = {}
for sym in test_syms:
    fp = LAKE_DIR / f"{sym}.parquet"
    if not fp.exists():
        continue
    df = pd.read_parquet(fp, columns=["date", "open", "high", "low", "close", "volume", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 300:
        continue
    stock_data[sym] = df

print(f"Loaded: {len(stock_data)} stocks")

# Find common dates
all_dates = sorted({str(d)[:10] for sdf in stock_data.values() for d in sdf["date"]})
all_dates = [d for d in all_dates if "2017-01-01" <= d <= "2020-01-01"]

# Pick one rebalance date per month (last trading day)
rebal_dates, ym_set = [], set()
for d in reversed(all_dates):
    ym = d[:7]
    if ym not in ym_set:
        ym_set.add(ym)
        rebal_dates.append(d)
rebal_dates = sorted(rebal_dates[1:])
print(f"Trading days: {len(all_dates)}, Rebalance dates: {len(rebal_dates)}")

# Test: Random stock selection, equal weight, buy at open, hold 1 month
cash = 100_000_000
positions = {}
eq_curve = []

# Also track a "universe index" for comparison
uni_prices = {}

for di, ds in enumerate(all_dates):
    nav = cash
    for sym in list(positions.keys()):
        sdf = stock_data.get(sym)
        if sdf is None:
            continue
        row = sdf[sdf["date"] == ds]
        if row.empty:
            continue
        nav += positions[sym]["shares"] * row["close"].values[0]
    eq_curve.append({"date": ds, "equity": nav, "cash": cash})

    if ds not in rebal_dates:
        continue

    # Get all stocks with data on this date
    available = {}
    for sym, sdf in stock_data.items():
        row = sdf[sdf["date"] == ds]
        if row.empty:
            continue
        r = row.iloc[0]
        available[sym] = r

    if len(available) < 100:
        continue

    # Random selection (300 stocks)
    candidates = list(available.keys())
    np.random.shuffle(candidates)
    selected_syms = set(candidates[:300])
    selected_details = {s: available[s] for s in selected_syms}

    # Sell old positions
    for sym in list(positions.keys()):
        if sym not in selected_syms:
            sdf = stock_data.get(sym)
            if sdf is None:
                continue
            row = sdf[sdf["date"] == ds]
            if row.empty:
                continue
            r = row.iloc[0]
            pos = positions.pop(sym)
            cash += pos["shares"] * r["close"] * (1 - 0.0008)

    # Equal weight buy
    n_stocks = len(selected_details)
    target_per_stock = nav * 0.95 / max(n_stocks, 1)

    for sym, info in selected_details.items():
        ep = info["open"] if info["open"] > 0 else info["close"]
        shares = max(int(target_per_stock / ep) // 100 * 100, 0)
        cost = shares * ep
        if cash < cost or shares <= 0:
            continue
        cash -= cost * (1 + 0.0008)
        positions[sym] = {"shares": shares, "buy_price": ep, "buy_date": ds}

    # Track universe average price for the 300 selected stocks
    close_prices = [info["close"] for info in selected_details.values() if info["close"] > 0]
    uni_prices[ds] = np.mean(close_prices) if close_prices else np.nan

    # Compute portfolio return vs universe return
    print(f"[{ds}] NAV={nav:>10,.0f}  nPos={len(positions)}  Cash={cash:>8,.0f}")

# Liquidate
for sym in list(positions.keys()):
    sdf = stock_data.get(sym)
    if sdf is None:
        continue
    last = sdf.iloc[-1]
    cash += positions[sym]["shares"] * last["close"] * (1 - 0.0008)
positions.clear()

# Final metrics
eq_df = pd.DataFrame(eq_curve)
eq_df["ret"] = eq_df["equity"].pct_change().fillna(0)
eq_df = eq_df[eq_df["ret"] != 0]
n_days = len(eq_df)
n_yrs = n_days / 252
tot_ret = cash / 100_000_000 - 1
ann_ret = (1 + tot_ret) ** (1 / max(n_yrs, 0.1)) - 1
ann_vol = eq_df["ret"].std() * np.sqrt(252)
sharpe = ann_ret / max(ann_vol, 1e-10)
cum = (1 + eq_df["ret"]).cumprod()
dd = (cum / cum.cummax() - 1).min()

print(f"\n{'='*50}")
print(f"RANDOM SELECTION (300 stocks, equal weight)")
print(f"{'='*50}")
print(f"Final NAV: {cash:,.2f}")
print(f"Total Return: {tot_ret:+.2%}")
print(f"Annual Return: {ann_ret:+.2%}")
print(f"Annual Vol: {ann_vol:.2%}")
print(f"Sharpe: {sharpe:.4f}")
print(f"Max DD: {dd:.2%}")
print(f"\nBenchmark: CSI 300 returned approximately:")
print(f"  2018: -25.3%")
print(f"If random selection matches, the engine works correctly.")
