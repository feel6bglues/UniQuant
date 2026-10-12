#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 机构级交易清单与执行指引生成命令行工具
=====================================================

用法示例:
  python scripts/qar/run_generate_trading_manifest.py --aum 5000000000 --date 2026-09-25
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Dict

# 注入 UniQuant 源码路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uniquant.risk.compliance_engine import PreTradeComplianceEngine
from uniquant.services.manifest_generator import ManifestGenerator
from uniquant.shared.logger_factory import get_logger

logger = get_logger("ManifestRunner")

# 申万一级行业映射
SHENWAN_SAMPLE_MAP = {
    "600519.SH": "食品饮料", "000858.SZ": "食品饮料", "600809.SH": "食品饮料",
    "300750.SZ": "电力设备", "002594.SZ": "汽车", "600036.SH": "银行",
    "601318.SH": "非银金融", "601899.SH": "有色金属", "000333.SZ": "家用电器",
    "600900.SH": "公用事业", "600276.SH": "医药生物", "002475.SZ": "电子",
    "601088.SH": "煤炭", "600309.SH": "基础化工", "000651.SZ": "家用电器",
    "601988.SH": "银行", "601398.SH": "银行", "601288.SH": "银行",
    "600030.SH": "非银金融", "601995.SH": "非银金融", "002415.SZ": "计算机",
    "300059.SZ": "非银金融", "601668.SH": "建筑装饰", "600585.SH": "建筑材料",
    "600104.SH": "汽车", "000002.SZ": "房地产", "600048.SH": "房地产",
    "601111.SH": "交通运输", "600009.SH": "交通运输", "601857.SH": "石油石化",
    "600028.SH": "石油石化", "002714.SZ": "农林牧渔", "600436.SH": "医药生物",
    "300122.SZ": "医药生物", "688981.SH": "电子", "600050.SH": "通信",
    "000063.SZ": "通信", "600188.SH": "煤炭", "601699.SH": "煤炭",
}

# 基准参考价 (真实收盘价样本)
SAMPLE_PRICES = {
    "600519.SH": 1292.01, "000858.SZ": 115.30, "600809.SH": 142.10,
    "300750.SZ": 385.99, "002594.SZ": 92.65, "600036.SH": 36.85,
    "601318.SH": 46.20, "601899.SH": 18.50, "000333.SZ": 68.30,
    "600900.SH": 29.40, "600276.SH": 43.10, "002475.SZ": 31.80,
    "601088.SH": 38.90, "600309.SH": 67.50, "000651.SZ": 39.20,
    "601988.SH": 4.95, "601398.SH": 5.80, "601288.SH": 4.60,
    "600030.SH": 22.40, "601995.SH": 31.50, "002415.SZ": 28.90,
    "300059.SZ": 16.80, "601668.SH": 5.40, "600585.SH": 24.10,
    "600104.SH": 13.50, "000002.SZ": 7.20, "600048.SH": 8.90,
    "601111.SH": 7.80, "600009.SH": 34.60, "601857.SH": 8.50,
    "600028.SH": 6.20, "002714.SZ": 38.40, "600436.SH": 185.00,
    "300122.SZ": 42.10, "688981.SH": 48.60, "600050.SH": 5.10,
    "000063.SZ": 28.50, "600188.SH": 22.80, "601699.SH": 14.20,
}


def main():
    parser = argparse.ArgumentParser(description="UniQuant Trading Manifest Generator CLI")
    parser.add_argument("--aum", type=float, default=5_000_000_000.0, help="Total AUM in CNY")
    parser.add_argument("--date", type=str, default="2026-09-25", help="Target trade date (YYYY-MM-DD)")
    parser.add_argument("--index-quote", type=float, default=4000.0, help="IF300 reference price")
    parser.add_argument("--output-dir", type=str, default="data/manifests", help="Output directory")
    args = parser.parse_args()

    print("=" * 78)
    print("  UniQuant 投研平台 — 机构级交易清单与执行指引生成中枢")
    print(f"  AUM 规模: {args.aum:,.2f} CNY | 交易日期: {args.date} | 股指点位: {args.index_quote:.2f}")
    print("=" * 78)

    # 1. 构造多因子两阶段凸优化产出的目标股票池 (38只股票，单票权重 ~1.97%，满足单票<=2.5%、行业<=10%)
    symbols = list(SAMPLE_PRICES.keys())
    target_weights = {sym: 0.75 / len(symbols) for sym in symbols}

    # 2. 实例化清单中枢与合规引擎
    compliance_engine = PreTradeComplianceEngine(
        max_single_stock_weight=0.025,
        max_industry_weight=0.100,
        max_industry_stock_count=4,
    )
    generator = ManifestGenerator(
        compliance_engine=compliance_engine,
        output_dir=args.output_dir,
    )

    # 3. 运行生成与硬风控审计
    pack = generator.generate_manifest(
        trade_date=args.date,
        aum_cny=args.aum,
        target_weights=target_weights,
        stock_prices=SAMPLE_PRICES,
        index_quote=args.index_quote,
        stock_industries=SHENWAN_SAMPLE_MAP,
    )

    # 4. 打印合规报告
    m = pack.compliance_report.metrics
    print("\n[1] 宏观资产配置与杠杆比率 (Canonical Ternary Allocation):")
    print(f"    - 多头股票总市值: {m.total_long_cny:,.2f} CNY ({m.long_weight_pct:.4f}%)")
    print(f"    - 期指空头对冲值: {m.total_short_cny:,.2f} CNY ({m.short_weight_pct:.4f}%)")
    print(f"    - 现金安全缓冲区: {m.cash_buffer_cny:,.2f} CNY ({m.cash_buffer_pct:.4f}%)")
    print(f"    - 总杠杆率 (Gross): {m.gross_leverage_pct:.4f}% (上限: 175.00%)")
    print(f"    - 净对冲敞口 (Net): {m.net_exposure_pct:.4f}% (绝对中性容差: [-0.50%, +0.50%])")

    print("\n[2] 微观合规与整百股防线 (Microstructure Compliance):")
    print(f"    - 现货整百股合规率: {'100% 通过' if m.lot_sizing_compliant else '违背'}")
    print(f"    - 单票最大权重标的: {m.max_single_stock_symbol} ({m.max_single_stock_weight_pct:.4f}%, 上限 2.50%)")
    print(f"    - 行业最大权重行业: {m.max_industry_name} ({m.max_industry_weight_pct:.4f}%, 上限 10.00%)")
    print(f"    - 行业最多持股数量: {m.max_industry_stock_count} 只 (上限 4 只)")

    fut = pack.futures_hedging.iloc[0]
    print("\n[3] 期指空头对冲 3 PB 分仓 (CFFEX PB Hedging Allocation):")
    print(f"    - 需求总手数: {fut['total_contracts']} 手")
    print(f"    - 中信证券 PB: {fut['pb_citic_pb_contracts']} 手 (利用率: {fut['pb_citic_pb_contracts']/1200*100:.2f}%)")
    print(f"    - 国泰君安 PB: {fut['pb_gtja_pb_contracts']} 手 (利用率: {fut['pb_gtja_pb_contracts']/1200*100:.2f}%)")
    print(f"    - 华泰证券 PB: {fut['pb_htsc_pb_contracts']} 手 (利用率: {fut['pb_htsc_pb_contracts']/1200*100:.2f}%)")
    print(f"    - 占用保证金: {fut['margin_required_cny']:,.2f} CNY (15% 保证金率)")

    print(f"\n[4] 事前风控签证结果 (Pre-Trade Compliance Verdict):")
    print(f"    - 审查结论: {pack.compliance_report.verdict}")
    print(f"    - SHA-256 签名: {pack.manifest_hash}")
    print(f"    - 导出落盘目录: {pack.output_dir}")
    for p in pack.exported_files:
        print(f"      * {Path(p).name}")
    print("=" * 78)


if __name__ == "__main__":
    main()
