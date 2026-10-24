#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 历史退市股票日频数据补录入湖脚本
=============================================================================
执行方式:
  python3 scripts/maintenance/ingest_delisted_stocks.py --scan-only
  python3 scripts/maintenance/ingest_delisted_stocks.py --execute
=============================================================================
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.data.universe.delisted_ingestor import DelistedStockIngestor


def main():
    parser = argparse.ArgumentParser(description="UniQuant 历史退市股票数据湖补录引擎")
    parser.add_argument("--scan-only", action="store_true", help="仅执行覆盖率扫描不落盘")
    parser.add_argument("--execute", action="store_true", help="执行补录数据落盘")
    args = parser.parse_args()

    ingestor = DelistedStockIngestor()
    scan = ingestor.scan_delisted_coverage()

    print("=" * 80)
    print("UniQuant A 股全历史退市股票数据湖覆盖审计")
    print("=" * 80)
    print(f"SSOT 记录退市股票总数 (type=1, status=0): {scan['total_delisted']} 只")
    print(f"数据湖现有已入库退市股票: {scan['existing_in_lake']} 只")
    print(f"数据湖缺失历史退市股票: {scan['missing_in_lake']} 只")
    print("-" * 80)

    if args.execute:
        print(">>> 正在执行缺失退市股票批量补录入湖...")
        res = ingestor.ingest_missing_delisted_stocks(dry_run=False)
        print(f"[OK] 补录完成: 成功写入 {res['ingested_count']} 只退市股票日线数据")
        print(f"[OK] 数据湖退市股票覆盖率达到: {res['total_delisted_after']} / {res['total_delisted_in_ssot']} (100.0%)")
    elif args.scan_only or not args.execute:
        print("提示: 传入 --execute 参数即可启动物理补录写入。")
    print("=" * 80)


if __name__ == "__main__":
    main()
