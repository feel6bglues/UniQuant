#!/usr/bin/env python3
"""
Seed multi-period K-line data into data/lake/quotes/.

- weekly/   : aggregated from daily (open=first, high=max, low=min, close=last, volume=sum, amount=sum)
- monthly/  : aggregated from daily (same rules)
- 1mins/    : placeholder — requires TDX local data or AkShare online source
- 5mins/    : placeholder — requires TDX local data or AkShare online source

Usage:
    python3 scripts/seed_multi_period_data.py [--symbols N] [--overwrite]

    --symbols N   Process only first N symbols (default: all 5934)
    --overwrite   Overwrite existing weekly/monthly files
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.uniquant.data.lake.storage_manager import StorageManager


def main():
    parser = argparse.ArgumentParser(description="Seed multi-period K-line data")
    parser.add_argument("--symbols", type=int, default=None, help="Process only first N symbols")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    mgr = StorageManager(data_dir="./data")
    all_symbols = mgr.get_symbols()
    print(f"Found {len(all_symbols)} symbols with daily data")

    if args.symbols:
        all_symbols = sorted(all_symbols)[: args.symbols]
        print(f"Processing first {len(all_symbols)} symbols")

    # --- Placeholder for 1min/5min ---
    placeholder_dir = Path("./data/lake/quotes/1mins")
    placeholder_dir.mkdir(parents=True, exist_ok=True)
    placeholder_file = placeholder_dir / "README.md"
    placeholder_file.write_text(
        "# 1-Minute K-Line Data\n\n"
        "This directory is populated by TDX or AkShare data sources.\n\n"
        "Configuration in config.yaml:\n"
        "  multi_period.intraday.1min\n\n"
        "TDX source: tdx.get_security_bars(1, symbol, ...)\n"
        "AkShare: akshare.stock_zh_a_hist_min_em(symbol, period='1', ...)\n"
    )
    print(f"Created placeholder: {placeholder_file}")

    placeholder_dir_5 = Path("./data/lake/quotes/5mins")
    placeholder_dir_5.mkdir(parents=True, exist_ok=True)
    placeholder_file_5 = placeholder_dir_5 / "README.md"
    placeholder_file_5.write_text(
        "# 5-Minute K-Line Data\n\n"
        "This directory is populated by TDX or AkShare data sources.\n\n"
        "Configuration in config.yaml:\n"
        "  multi_period.intraday.5min\n\n"
        "TDX source: tdx.get_security_bars(5, symbol, ...)\n"
        "AkShare: akshare.stock_zh_a_hist_min_em(symbol, period='5', ...)\n"
    )
    print(f"Created placeholder: {placeholder_file_5}")

    # --- Synthesize weekly and monthly ---
    weekly_ok = 0
    monthly_ok = 0
    weekly_skip = 0
    monthly_skip = 0
    errors = []
    t0 = time.time()

    for i, symbol in enumerate(sorted(all_symbols)):
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(
                f"  [{i+1}/{len(all_symbols)}] "
                f"weekly={weekly_ok} monthly={monthly_ok} "
                f"skip_w={weekly_skip} skip_m={monthly_skip} "
                f"err={len(errors)} {elapsed:.1f}s"
            )

        # Weekly
        weekly_path = mgr.weekly_dir / f"{symbol}.parquet"
        if weekly_path.exists() and not args.overwrite:
            weekly_skip += 1
        else:
            try:
                df = mgr.synthesize_weekly(symbol)
                if not df.empty:
                    weekly_ok += 1
            except Exception as e:
                errors.append(f"weekly:{symbol}:{e}")

        # Monthly
        monthly_path = mgr.monthly_dir / f"{symbol}.parquet"
        if monthly_path.exists() and not args.overwrite:
            monthly_skip += 1
        else:
            try:
                df = mgr.synthesize_monthly(symbol)
                if not df.empty:
                    monthly_ok += 1
            except Exception as e:
                errors.append(f"monthly:{symbol}:{e}")

    elapsed = time.time() - t0
    print(f"\n=== Summary ===")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / max(len(all_symbols), 1):.2f}s/symbol)")
    print(f"Weekly  : {weekly_ok} generated, {weekly_skip} skipped (already exist)")
    print(f"Monthly : {monthly_ok} generated, {monthly_skip} skipped (already exist)")
    if errors:
        print(f"Errors  : {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")

    # Verify
    print("\n=== Verification ===")
    for period in ["weekly", "monthly", "1mins", "5mins"]:
        d = Path(f"./data/lake/quotes/{period}")
        files = list(d.glob("*.parquet")) if period in ("weekly", "monthly") else list(d.iterdir())
        size = sum(f.stat().st_size for f in files if f.suffix == ".parquet" or f.name == "README.md")
        print(f"  {period}/: {len(files)} files, {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()