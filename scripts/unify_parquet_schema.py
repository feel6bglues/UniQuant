#!/usr/bin/env python3
"""
Unify all 5934 daily K-line parquet files to the canonical schema.

Canonical schema (10 columns, datetime64[ns]):
    date, open, high, low, close, amount, volume, reserved, code, market

Fixes:
    1. 510300.parquet: missing 'reserved', 'market'; wrong column order; datetime64[ms]
    2. 391 files: missing 'market' column; datetime64[us]
    3. 5542 files: already canonical (no-op)
"""

import shutil
import sys
from pathlib import Path

import pandas as pd

DAILY_DIR = Path("data/lake/quotes/daily")
CANONICAL_COLS = ["date", "open", "high", "low", "close", "amount", "volume", "reserved", "code", "market"]
BACKUP_SUFFIX = ".bak"


def derive_market(filename: str) -> str:
    """Derive market from filename (e.g. 000001.SH.parquet -> 'SH')."""
    stem = filename.removesuffix(".parquet")
    if "." in stem:
        _, market = stem.rsplit(".", 1)
        return market.upper()
    return ""


def normalize_file(filepath: Path) -> tuple[bool, str]:
    """Normalize a single parquet file to the canonical schema. Returns (modified, reason)."""
    try:
        df = pd.read_parquet(filepath)
    except Exception as e:
        return False, f"ERROR: cannot read - {e}"

    original_cols = list(df.columns)
    original_dtype = str(df["date"].dtype)

    # Check if already canonical
    if original_cols == CANONICAL_COLS and original_dtype == "datetime64[ns]":
        return False, "already canonical"

    # Step 1: ensure 'reserved' column exists
    if "reserved" not in df.columns:
        df["reserved"] = 0

    # Step 2: ensure 'market' column exists
    if "market" not in df.columns:
        market_val = derive_market(filepath.name)
        df["market"] = market_val

    # Step 3: if 'code' is missing (unlikely, but handle)
    if "code" not in df.columns:
        df["code"] = ""

    # Step 4: reorder to canonical columns
    df = df[[c for c in CANONICAL_COLS if c in df.columns]]

    # Step 5: cast date to datetime64[ns]
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")

    # Step 6: ensure numeric types
    for col in ["open", "high", "low", "close", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in ["volume", "reserved"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("int64")

    # Write back
    df.to_parquet(filepath, index=False)

    return True, f"fixed: cols {original_cols} -> {CANONICAL_COLS}, dtype {original_dtype} -> datetime64[ns]"


def main():
    files = sorted(f for f in DAILY_DIR.iterdir() if f.suffix == ".parquet")
    total = len(files)
    print(f"Found {total} parquet files in {DAILY_DIR}")

    # Phase 1: backup
    print("\n=== Phase 1: Backup originals ===")
    backed_up = 0
    for fp in files:
        backup_path = fp.with_suffix(fp.suffix + BACKUP_SUFFIX)
        if not backup_path.exists():
            shutil.copy2(fp, backup_path)
            backed_up += 1
    print(f"Backed up {backed_up} files (skipped {total - backed_up} already backed up)")

    # Phase 2: normalize
    print("\n=== Phase 2: Normalize schemas ===")
    modified = 0
    unchanged = 0
    errors = 0
    for fp in files:
        ok, msg = normalize_file(fp)
        if ok:
            modified += 1
            print(f"  MODIFIED {fp.name}: {msg}")
        elif msg.startswith("ERROR"):
            errors += 1
            print(f"  ERROR    {fp.name}: {msg}")
        else:
            unchanged += 1

    # Summary
    print("\n=== Summary ===")
    print(f"  Total files:      {total}")
    print(f"  Modified:         {modified}")
    print(f"  Unchanged:        {unchanged}")
    print(f"  Errors:           {errors}")

    if modified > 0:
        print(f"\nBackups saved with '{BACKUP_SUFFIX}' suffix in {DAILY_DIR}")
        print("To restore a file: cp <file>.parquet.bak <file>.parquet")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())